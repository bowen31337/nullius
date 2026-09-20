"""Feature 154's log: append-only, self-chaining, and durable through a sink.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 154: *System
persists an access audit record per read of the null sidecar key, which
exactly one service account may request.*  This suite is the log half:
:class:`infra.security.audit_log.AuditLog` and its sinks — the chain that
makes a dropped or edited record detectable, the read-back that confirms a
write, and the fail-closed rule that a record which cannot be persisted
refuses the read it describes.  The record's field set is in
``test_record.py``; the read chokepoint is in ``test_read.py``.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from infra.security.audit_log import (
    GENESIS,
    AuditChainError,
    AuditDecision,
    AuditLog,
    AuditRecord,
    AuditSink,
    AuditSinkError,
    AuditTrailError,
    FileAuditSink,
    InMemoryAuditSink,
)


def _append(log: AuditLog, **overrides) -> AuditRecord:
    """Append a well-formed granted record, fields overridable per test."""
    fields = {
        "requester_account": "svc",
        "granted_account": "svc",
        "decision": AuditDecision.GRANTED,
        "reference": "kms:arn:aws:kms:us-east-1:0:key/k",
        "reason": "the account the key is granted to read it",
    }
    fields.update(overrides)
    return log.append(**fields)


class TamperedSink(InMemoryAuditSink):
    """An in-memory sink whose records a test may reach in and alter.

    The chain's whole subject is what a *later hand* can do to a log, so the
    tampering has to be expressible for the detection to be testable — and
    doing it through a named double, rather than by reaching into the sink's
    private list from four tests, says plainly what each test is: a store
    somebody edited after the fact.  Nothing outside this suite has any
    reason to alter a sink's records, and nothing in the module offers a way.
    """

    def _held_list(self) -> list[AuditRecord]:
        """The sink's records, as the mutable list a tamperer would find."""
        return self._held

    def drop(self, index: int) -> None:
        """Remove one record — the silently shortened log."""
        del self._held_list()[index]

    def swap(self, first: int, second: int) -> None:
        """Exchange two records — the reordering a re-chain would hide."""
        held = self._held_list()
        held[first], held[second] = held[second], held[first]

    def replace(self, index: int, record: AuditRecord) -> None:
        """Substitute one record — the edit a re-digest would hide."""
        self._held_list()[index] = record

    def rewrite(self, records: list[AuditRecord]) -> None:
        """Replace the whole log — the rebuilt chain only the sequence catches."""
        self._held_list()[:] = records


@pytest.fixture
def tamperable() -> tuple[AuditLog, TamperedSink]:
    """A log over a sink a test may tamper with.  Returns ``(log, sink)``."""
    sink = TamperedSink("tamperable")
    return AuditLog(sink), sink


def _rebuild(source: AuditRecord, **overrides) -> AuditRecord:
    """A record shaped like ``source`` with fields overridden — an edit."""
    fields = {
        "sequence": source.sequence,
        "previous_digest": source.previous_digest,
        "requester_account": source.requester_account,
        "granted_account": source.granted_account,
        "decision": source.decision,
        "reference_label": source.reference_label,
        "reason": source.reason,
        "timestamp": source.timestamp,
    }
    fields.update(overrides)
    return AuditRecord(**fields)


# -- one record per append, in order -------------------------------------------


def test_an_empty_log_verifies(mem_log: AuditLog) -> None:
    """A log with no records is a chain that holds — vacuously, and correctly."""
    assert mem_log.verify() == ()


def test_an_append_persists_one_record(mem_log: AuditLog) -> None:
    """One append is one record — the count is the feature's "per read"."""
    _append(mem_log)
    assert len(mem_log.records) == 1


def test_appends_keep_order(mem_log: AuditLog) -> None:
    """Records are held in append order, which is the order the chain walks."""
    for _ in range(3):
        _append(mem_log)
    assert [r.sequence for r in mem_log.records] == [0, 1, 2]


def test_the_first_record_chains_from_genesis(mem_log: AuditLog) -> None:
    """The first record's predecessor link is ``GENESIS`` — verifiably first."""
    assert _append(mem_log).previous_digest == GENESIS


def test_each_record_names_its_predecessor(mem_log: AuditLog) -> None:
    """Every record after the first names the digest of the one before it."""
    first = _append(mem_log)
    second = _append(mem_log)
    assert second.previous_digest == first.digest()


def test_the_chain_verifies(mem_log: AuditLog) -> None:
    """A log that was only ever appended to verifies and returns its records."""
    for _ in range(4):
        _append(mem_log)
    assert mem_log.verify() == mem_log.records


def test_a_new_log_over_a_used_sink_continues_the_chain(mem_sink: InMemoryAuditSink) -> None:
    """The sink holds the chain, not the log — a second log continues it."""
    AuditLog(mem_sink).append(
        requester_account="svc",
        granted_account="svc",
        decision=AuditDecision.GRANTED,
        reason="first",
    )
    second = _append(AuditLog(mem_sink))
    assert second.sequence == 1
    assert AuditLog(mem_sink).verify() == mem_sink.records()


# -- the chain detects what happened to the log --------------------------------


def test_verify_refuses_a_dropped_record(tamperable) -> None:
    """Removing a middle record breaks the successor's link — detected."""
    log, sink = tamperable
    for _ in range(3):
        _append(log)
    sink.drop(1)
    with pytest.raises(AuditChainError):
        log.verify()


def test_verify_refuses_a_dropped_first_record(tamperable) -> None:
    """Removing the first record breaks the new head's link from GENESIS."""
    log, sink = tamperable
    for _ in range(2):
        _append(log)
    sink.drop(0)
    with pytest.raises(AuditChainError):
        log.verify()


def test_verify_refuses_a_reordering(tamperable) -> None:
    """Swapping two records breaks both links — order is part of the chain."""
    log, sink = tamperable
    for _ in range(3):
        _append(log)
    sink.swap(0, 1)
    with pytest.raises(AuditChainError):
        log.verify()


def test_verify_refuses_an_edited_record(tamperable) -> None:
    """Editing a record's fields breaks the chain at the record after it."""
    log, sink = tamperable
    _append(log)
    _append(log)
    held = log.records
    sink.replace(0, _rebuild(held[0], requester_account="someone-else"))
    with pytest.raises(AuditChainError):
        log.verify()


def test_verify_refuses_a_rebuilt_log(tamperable) -> None:
    """A log re-chained from scratch is caught by the sequence, not the links."""
    log, sink = tamperable
    for _ in range(3):
        _append(log)
    held = log.records
    # Re-chain as if the second record had never existed: every link is
    # consistent, and only the sequence disagrees with the position — which
    # is why verify checks both.
    rebuilt = _rebuild(
        held[2], sequence=2, previous_digest=held[0].digest()
    )
    sink.rewrite([held[0], rebuilt])
    with pytest.raises(AuditChainError):
        log.verify()


# -- the two questions an operator asks ----------------------------------------


def test_granted_reads_are_the_expected_case(mem_log: AuditLog) -> None:
    """A granted read is recorded as granted, and filtered as such."""
    _append(mem_log)
    assert len(mem_log.granted_reads()) == 1
    assert mem_log.refused_reads() == ()


def test_refused_reads_are_the_case_the_feature_exists_for(mem_log: AuditLog) -> None:
    """A refused attempt is recorded and filterable — the line an operator wants."""
    _append(mem_log, decision=AuditDecision.REFUSED, requester_account="intruder")
    assert len(mem_log.refused_reads()) == 1
    assert mem_log.refused_reads()[0].requester_account == "intruder"
    assert mem_log.granted_reads() == ()


def test_a_record_carries_both_identities_on_a_refusal(mem_log: AuditLog) -> None:
    """Who asked and who holds it — both, so the refusal is actionable."""
    record = _append(
        mem_log, decision=AuditDecision.REFUSED, requester_account="intruder"
    )
    assert record.requester_account == "intruder"
    assert record.granted_account == "svc"
    assert record.granted is False


# -- the log refuses a sink it cannot trust ------------------------------------


def test_a_log_needs_a_sink() -> None:
    """A log with nowhere to write is the failure the feature prevents."""
    with pytest.raises(AuditTrailError):
        AuditLog(None)


def test_a_sink_needs_a_name() -> None:
    """A sink that cannot be named cannot be reported as the one that failed."""
    with pytest.raises(AuditTrailError):
        InMemoryAuditSink("")


def test_a_sink_that_raises_on_append_is_a_sink_error(mem_sink: InMemoryAuditSink) -> None:
    """A sink that will not take the record refuses the append, loudly."""

    class _BrokenSink(AuditSink):
        def append(self, record):
            raise AuditSinkError("the store is down")

        def records(self):
            return ()

    with pytest.raises(AuditSinkError):
        _append(AuditLog(_BrokenSink("broken")))


def test_a_sink_that_loses_the_record_is_refused(mem_sink: InMemoryAuditSink) -> None:
    """A sink that swallows the append cannot be believed — the read is refused."""

    class _LosingSink(AuditSink):
        """Accepts the record and keeps nothing — the silent audit hole."""

        def append(self, record):
            return None

        def records(self):
            return ()

    with pytest.raises(AuditSinkError):
        _append(AuditLog(_LosingSink("losing")))


def test_a_sink_that_returns_a_different_record_is_refused() -> None:
    """A sink that gives back other bytes than it took is refused, not believed."""

    class _RewritingSink(AuditSink):
        def append(self, record):
            return AuditRecord(
                sequence=record.sequence,
                previous_digest=record.previous_digest,
                requester_account="someone-else",
                granted_account=record.granted_account,
                decision=record.decision,
                reference_label=record.reference_label,
                reason=record.reason,
                timestamp=record.timestamp,
            )

        def records(self):
            return ()

    with pytest.raises(AuditSinkError):
        _append(AuditLog(_RewritingSink("rewriting")))


def test_the_base_sink_is_abstract() -> None:
    """The base class states both halves of a sink's contract as unimplemented."""
    sink = AuditSink("base")
    with pytest.raises(NotImplementedError):
        sink.append(None)
    with pytest.raises(NotImplementedError):
        sink.records()


# -- two appenders, one sink: the collision is refused at the read --------------
#
# A single-threaded test cannot *produce* the interleaving — it needs two
# appenders to each read the sink before either writes, which one thread
# cannot do.  What it can do is put the sink into the state the interleaving
# produces and check that the append refuses it.  That state is: two records
# physically in the log, both claiming the same position, because both
# appenders computed it from the same read.  `RacingSink` below lands that
# state on write, so the append under test is the second of the two.


class RacingSink(InMemoryAuditSink):
    """A sink where a competing appender wins the slot on every write.

    Models the *outcome* of the race exactly: another appender, having
    computed the same position from the same read of the log, wrote there
    first, and this record ends up after it.  Both lines are in the log and
    both claim the same position — the state a chained log cannot be in.
    """

    def append(self, record: AuditRecord) -> AuditRecord:
        """Land ``record`` *behind* a foreign record that took its slot."""
        if record.sequence == len(self.records()):
            super().append(
                AuditRecord(
                    sequence=record.sequence,
                    previous_digest=record.previous_digest,
                    requester_account="racing-appender",
                    granted_account=record.granted_account,
                    decision=record.decision,
                    reference_label=record.reference_label,
                    reason="another appender computed this position first",
                    timestamp=0.0,
                )
            )
        return super().append(record)


def test_a_colliding_append_is_refused() -> None:
    """Two appenders that computed the same position cannot both land there.

    The sequence and the predecessor link are computed from a read of the
    sink, so two logs racing on one sink both compute position *n*. Only
    one line can be the log's record at *n*, and the second append is
    refused rather than allowed to leave a log whose positions and
    sequences disagree.
    """
    with pytest.raises(AuditSinkError):
        _append(AuditLog(RacingSink("racing")))


def test_the_loser_of_a_race_does_not_serve_its_key() -> None:
    """The refusal is what keeps a read from being served on a broken chain.

    The whole reason the collision is checked at append time rather than
    left to :meth:`verify`: the caller here is a key read, and discovering
    the broken chain during a later audit would be discovering it after the
    key was already out.
    """
    with pytest.raises(AuditSinkError):
        _append(AuditLog(RacingSink("racing")))


def test_the_collision_leaves_a_log_verify_refuses() -> None:
    """The state the append refuses is one verify refuses too — same condition, both halves.

    Checked by writing the colliding record straight to the sink, bypassing
    :meth:`AuditLog.append`: the log then genuinely holds two records
    claiming position 0, and :meth:`verify` names it.  The append-time check
    is what keeps that state from being *reached* by a real read.
    """
    sink = InMemoryAuditSink("collided")
    sink.append(
        AuditRecord(
            sequence=0,
            previous_digest=GENESIS,
            requester_account="svc",
            granted_account="svc",
            decision=AuditDecision.GRANTED,
            reference_label="<none>",
            reason="the account the key is granted to read it",
            timestamp=0.0,
        )
    )
    sink.append(
        AuditRecord(
            sequence=0,  # the same slot, from the racing appender
            previous_digest=GENESIS,
            requester_account="racing-appender",
            granted_account="svc",
            decision=AuditDecision.GRANTED,
            reference_label="<none>",
            reason="another appender computed this position first",
            timestamp=0.0,
        )
    )
    with pytest.raises(AuditChainError):
        AuditLog(sink).verify()


def test_a_sequential_second_log_appends_cleanly(mem_sink: InMemoryAuditSink) -> None:
    """Two logs used in turn is not a collision — the ordinary multi-process case."""
    _append(AuditLog(mem_sink))
    second = _append(AuditLog(mem_sink))
    assert second.sequence == 1
    assert AuditLog(mem_sink).verify()[1].sequence == 1


def test_the_collision_check_is_not_a_blanket_refusal(mem_sink: InMemoryAuditSink) -> None:
    """An append with no competing writer lands — the check is specific to a real collision.

    Guards against the check having become "refuse if anything looks odd":
    the ordinary case of many appends to one sink, in turn, must keep
    working, which is the case a deployment actually runs.
    """
    log = AuditLog(mem_sink)
    for _ in range(5):
        _append(log)
    assert [r.sequence for r in log.verify()] == [0, 1, 2, 3, 4]


# -- the file sink: the durable spelling ---------------------------------------


def test_a_file_sink_round_trips(file_sink: FileAuditSink, mem_log: AuditLog) -> None:
    """A record written to a file reads back identical — the chain survives a process."""
    log = AuditLog(file_sink)
    written = _append(log)
    (read_back,) = log.records
    assert read_back.to_json() == written.to_json()
    assert read_back.digest() == written.digest()


def test_a_file_sink_chains_across_log_objects(file_sink: FileAuditSink) -> None:
    """A second log over the same file continues the chain — the file is the log."""
    for _ in range(3):
        _append(AuditLog(file_sink))
    assert AuditLog(file_sink).verify()[2].sequence == 2


def test_a_file_sink_holds_one_json_object_per_line(file_sink: FileAuditSink) -> None:
    """The file is newline-delimited JSON — one parseable record per line."""
    log = AuditLog(file_sink)
    for _ in range(3):
        _append(log)
    lines = file_sink.path.read_bytes().splitlines()
    assert len(lines) == 3
    for line in lines:
        assert isinstance(json.loads(line), dict)


def test_a_file_sink_write_is_0600(file_sink: FileAuditSink) -> None:
    """The log file is owner-only — it names the accounts and the read history."""
    _append(AuditLog(file_sink))
    assert stat.S_IMODE(os.stat(file_sink.path).st_mode) == 0o600


def test_a_file_sink_creates_its_directory(file_sink: FileAuditSink) -> None:
    """A sink creates the directory it was pointed at rather than failing."""
    _append(AuditLog(file_sink))
    assert file_sink.path.is_file()


def test_a_file_sink_directory_is_0700(file_sink: FileAuditSink) -> None:
    """The directory is owner-only — a 0600 file in a listable directory still leaks names."""
    _append(AuditLog(file_sink))
    assert stat.S_IMODE(os.stat(file_sink.path.parent).st_mode) == 0o700


def test_a_file_sink_tightens_a_pre_existing_directory(tmp_path) -> None:
    """A directory that was already world-listable is corrected, not inherited."""
    directory = tmp_path / "loose"
    directory.mkdir()
    os.chmod(directory, 0o755)
    sink = FileAuditSink("file", directory / "audit.jsonl")
    _append(AuditLog(sink))
    assert stat.S_IMODE(os.stat(directory).st_mode) == 0o700


def test_a_file_sink_tightens_a_pre_existing_file(tmp_path) -> None:
    """A log that already exists with wider bits is corrected on the next append.

    ``os.O_CREAT``'s mode applies only when the file is *created*, so a log
    restored from an archive that dropped modes, or hit by a ``chmod -R``,
    would keep the wide bits forever while the sink reported success.
    """
    path = tmp_path / "audit.jsonl"
    path.write_bytes(b"")
    os.chmod(path, 0o644)
    _append(AuditLog(FileAuditSink("file", path)))
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_a_tightened_file_still_appends(file_sink: FileAuditSink) -> None:
    """Tightening is not a rewrite: the appended line lands and the chain holds."""
    log = AuditLog(file_sink)
    for _ in range(3):
        _append(log)
    assert stat.S_IMODE(os.stat(file_sink.path).st_mode) == 0o600
    assert [r.sequence for r in log.verify()] == [0, 1, 2]


def test_an_unwritten_file_sink_reads_empty(file_sink: FileAuditSink) -> None:
    """A sink with no file holds no records — a miss, not a failure."""
    assert file_sink.records() == ()
    assert AuditLog(file_sink).verify() == ()


def test_a_file_sink_refuses_unreadable_bytes(file_sink: FileAuditSink) -> None:
    """A line that is not JSON is refused, never skipped — a skipped line is a hole."""
    _append(AuditLog(file_sink))
    with file_sink.path.open("ab") as handle:
        handle.write(b"not json at all\n")
    with pytest.raises(AuditTrailError):
        file_sink.records()


def test_a_file_sink_refuses_a_non_object_line(file_sink: FileAuditSink) -> None:
    """A JSON array is not a record — a record is a set of named fields."""
    file_sink.path.parent.mkdir(parents=True, exist_ok=True)
    file_sink.path.write_bytes(b"[1, 2, 3]\n")
    with pytest.raises(AuditTrailError):
        file_sink.records()


def test_a_file_sink_refuses_a_line_missing_a_field(file_sink: FileAuditSink) -> None:
    """A record that cannot state its chain position is not evidence."""
    _append(AuditLog(file_sink))
    fields = json.loads(file_sink.path.read_bytes().splitlines()[0])
    del fields["decision"]
    file_sink.path.write_bytes(
        (json.dumps(fields, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    with pytest.raises(AuditTrailError):
        file_sink.records()


def test_a_file_sink_refuses_an_unwritable_directory(tmp_path) -> None:
    """A sink whose path cannot be a file refuses the append, loudly."""
    blocked = tmp_path / "a-file"
    blocked.write_bytes(b"")
    with pytest.raises(AuditSinkError):
        _append(AuditLog(FileAuditSink("blocked", blocked / "nested" / "audit.jsonl")))


def test_the_file_sink_resolves_its_path_from_the_environment(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured sink names where the log goes; an unset one is ``None``."""
    from infra.security.audit_log import AUDIT_LOG_PATH_ENV

    assert FileAuditSink.from_env({}) is None
    assert FileAuditSink.from_env({AUDIT_LOG_PATH_ENV: "  "}) is None
    configured = FileAuditSink.from_env({AUDIT_LOG_PATH_ENV: str(tmp_path / "a.jsonl")})
    assert configured is not None
    assert configured.path == tmp_path / "a.jsonl"


def test_the_in_memory_sink_is_process_local(mem_sink: InMemoryAuditSink) -> None:
    """An in-memory sink holds only for the process — the ephemeral deployment."""
    _append(AuditLog(mem_sink))
    assert len(mem_sink.records()) == 1
    assert InMemoryAuditSink("another").records() == ()
