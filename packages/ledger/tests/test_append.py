"""The store of feature 86: one row per evaluation, one never-reused sequence.

``TrialLedger.append`` is the whole of the feature's sentence — *System
persists one trial_ledger row per evaluation under a monotonically
increasing sequence number* — and these tests hold it to both halves:

* **one row per evaluation**: every append is exactly one INSERT; the
  count of rows equals the count of appends, and the record the append
  returns is the row the table now holds;
* **monotonically increasing sequence number**: successive appends draw
  strictly increasing numbers, the numbers survive the connection that
  spent them (a fresh store on the same database continues the count),
  concurrent appends serialise onto distinct increasing numbers, and —
  the property that makes the guarantee the table's rather than the
  rows' — deleting the highest row out from under the sequence does not
  let the next append reuse the spent number.

The deletion probe reaches under the store with raw SQL on purpose.
Feature 92 will deny UPDATE and DELETE at the database itself, and the
append path will never issue them; the point of the probe is that the
monotonicity does not *wait* for that enforcement — ``AUTOINCREMENT``'s
high-water mark is persisted beside the rows, so the guarantee holds
even against a hand that should not exist.  Proving it now is proving
the sequence is a fact about the ledger, not an artefact of nobody
having deleted anything yet.
"""

from __future__ import annotations

import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ledger import (
    DATABASE_URL_ENV,
    TRIAL_LEDGER_TABLE,
    TrialLedger,
    TrialLedgerRecord,
    TrialRecordError,
    TrialStoreError,
)
from ledger.record import utc_now

NODE_A = uuid.uuid4()
NODE_B = uuid.uuid4()
CAMPAIGN = uuid.uuid4()
# The outcome these feature-86 tests debit with: any of the four would
# do, and 'ok' is the one an evaluation that ran to its persist step
# ends in.  The outcome's own behaviour — persistence, refusal, the
# legacy upgrade — is test_outcome.py's subject.
OUTCOME = "ok"


# -- The append and the sequence -------------------------------------------


def test_the_first_append_is_assigned_sequence_one(test_ledger: TrialLedger) -> None:
    record = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    assert record.seq == 1


def test_successive_appends_increase_monotonically(
    test_ledger: TrialLedger,
) -> None:
    # Three evaluations, three charges, three numbers in the order debited.
    seqs = [
        test_ledger.append(node, CAMPAIGN, OUTCOME).seq
        for node in (NODE_A, NODE_B, NODE_A)
    ]
    assert seqs == [1, 2, 3]
    assert all(later > earlier for earlier, later in zip(seqs, seqs[1:]))


def test_one_row_per_append(test_ledger: TrialLedger) -> None:
    for _ in range(4):
        test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    assert test_ledger.count() == 4
    assert len(test_ledger.rows()) == 4


def test_two_evaluations_of_one_node_are_two_rows(
    test_ledger: TrialLedger,
) -> None:
    # At feature 86 the honest counter counts what it is told: a node
    # debited twice is two charges, and the idempotent debit keyed by
    # node_id is feature 95's contract, layered on this seam later.
    first = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    second = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    assert first.seq != second.seq
    assert test_ledger.count() == 2


def test_the_append_returns_the_row_the_table_holds(
    test_ledger: TrialLedger,
) -> None:
    returned = test_ledger.append(NODE_B, CAMPAIGN, OUTCOME)
    assert test_ledger.get(returned.seq) == returned
    assert test_ledger.rows()[-1] == returned


def test_the_row_carries_what_was_appended(test_ledger: TrialLedger) -> None:
    record = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    assert isinstance(record, TrialLedgerRecord)
    assert record.node_id == str(NODE_A)
    assert record.campaign_id == str(CAMPAIGN)
    assert record.ts.tzinfo is not None


def test_the_schema_is_created_on_first_use_and_is_idempotent(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        columns = [row[1] for row in info]
    # §8's first four columns in declaration order, plus feature 91's
    # outcome — the five the append itself owns.  The stamps of features
    # 87-90 land on this same table as they arrive; they are deliberately
    # absent now.
    assert columns == ["seq", "ts", "node_id", "campaign_id", "outcome"]
    # A second connect (every operation) takes the same path.
    assert test_ledger.count() == 1


# -- The sequence outlives the connection ----------------------------------


def test_the_sequence_survives_a_fresh_store_on_the_same_database(
    test_database_url: str,
) -> None:
    # The store holds no connection between operations; the database file
    # is the coordination point.  A brand-new instance — the next process,
    # as far as the ledger is concerned — continues the count rather than
    # restarting it, because the sequence's state is persisted beside the
    # rows, not derived from them.
    first = TrialLedger(test_database_url)
    first.append(NODE_A, CAMPAIGN, OUTCOME)
    first.append(NODE_B, CAMPAIGN, OUTCOME)

    second = TrialLedger(test_database_url)
    record = second.append(NODE_A, CAMPAIGN, OUTCOME)

    assert record.seq == 3
    assert second.count() == 3
    assert [row.seq for row in second.rows()] == [1, 2, 3]


def test_a_spent_number_is_never_reused_even_after_the_maximum_row_is_deleted(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The one probe that reaches under the store: delete every row with
    # raw SQL — including the maximum — and the next append still draws a
    # number above every number ever spent.  A bare rowid alias would
    # restart at max(visible rows)+1 = 1 here; AUTOINCREMENT's high-water
    # mark is what makes "monotonically increasing" a property of the
    # ledger rather than of the rows that happen to remain in it.
    for _ in range(3):
        test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"DELETE FROM {TRIAL_LEDGER_TABLE}")
    assert test_ledger.count() == 0

    record = test_ledger.append(NODE_B, CAMPAIGN, OUTCOME)

    assert record.seq == 4
    assert [row.seq for row in test_ledger.rows()] == [4]


def test_concurrent_appends_take_distinct_increasing_sequences(
    test_ledger: TrialLedger,
) -> None:
    # Each append opens its own connection, so eight threads debiting at
    # once serialise on the database's write lock and come away with eight
    # distinct numbers — the set 1..8, with no gap and no double-spend.
    with ThreadPoolExecutor(max_workers=8) as pool:
        seqs = [
            record.seq
            for record in pool.map(
                lambda _: test_ledger.append(NODE_A, CAMPAIGN, OUTCOME), range(8)
            )
        ]
    assert sorted(seqs) == list(range(1, 9))
    assert test_ledger.count() == 8


# -- The stamp -------------------------------------------------------------


def test_an_explicit_stamp_is_persisted_not_recomputed(
    test_ledger: TrialLedger,
) -> None:
    stamp = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)

    def lying_clock() -> datetime:
        raise AssertionError("the clock must not be read when ts is given")

    record = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, ts=stamp, clock=lying_clock)
    assert record.ts == stamp
    assert test_ledger.get(record.seq) == record


def test_an_explicit_stamp_in_another_offset_is_normalised(
    test_ledger: TrialLedger,
) -> None:
    aedt = timezone(timedelta(hours=10))
    record = test_ledger.append(
        NODE_A, CAMPAIGN, OUTCOME, ts=datetime(2026, 9, 20, 15, 0, 0, tzinfo=aedt)
    )
    assert record.ts == datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)


def test_the_default_clock_stamps_aware_utc(test_ledger: TrialLedger) -> None:
    before = utc_now()
    record = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    after = utc_now()
    assert before <= record.ts <= after


def test_the_stored_stamp_is_the_iso_text_with_an_offset(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    record = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    with sqlite3.connect(db_path) as connection:
        (stored,) = connection.execute(
            f"SELECT ts FROM {TRIAL_LEDGER_TABLE} WHERE seq = ?", (record.seq,)
        ).fetchone()
    assert stored == record.ts.isoformat()
    assert stored.endswith("+00:00")


# -- Validation happens before the ledger is touched ------------------------


@pytest.mark.parametrize(
    "node, campaign",
    [
        ("not-a-uuid", str(CAMPAIGN)),
        (str(NODE_A), "not-a-uuid"),
        (1234, str(CAMPAIGN)),
        (str(NODE_A), None),
    ],
)
def test_a_malformed_evaluation_is_refused_and_spends_no_sequence_number(
    test_ledger: TrialLedger, node: object, campaign: object
) -> None:
    with pytest.raises(TrialRecordError):
        test_ledger.append(node, campaign)
    assert test_ledger.count() == 0


def test_a_naive_stamp_is_refused_before_the_write(
    test_ledger: TrialLedger,
) -> None:
    with pytest.raises(TrialRecordError, match="timezone-aware"):
        test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, ts=datetime(2026, 9, 20, 5, 0, 0))
    assert test_ledger.count() == 0


def test_a_clock_that_is_not_callable_is_refused(
    test_ledger: TrialLedger,
) -> None:
    with pytest.raises(TrialRecordError, match="clock must be callable"):
        test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, clock="now")  # type: ignore[arg-type]


# -- Reading back -----------------------------------------------------------


def test_rows_read_back_in_sequence_order(test_ledger: TrialLedger) -> None:
    for node in (NODE_A, NODE_B, NODE_A, NODE_B):
        test_ledger.append(node, CAMPAIGN, OUTCOME)
    rows = test_ledger.rows()
    assert [row.seq for row in rows] == [1, 2, 3, 4]
    assert [row.node_id for row in rows] == [str(NODE_A), str(NODE_B)] * 2


def test_get_returns_none_for_a_sequence_the_ledger_never_assigned(
    test_ledger: TrialLedger,
) -> None:
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    assert test_ledger.get(1) is not None
    assert test_ledger.get(2) is None
    # Numbers the ledger could not have assigned name no row — and are not
    # coerced into one by SQLite's column affinity.
    assert test_ledger.get("1") is None  # type: ignore[arg-type]
    assert test_ledger.get(0) is None
    assert test_ledger.get(True) is None


def test_a_malformed_row_on_disk_is_refused_by_its_seq(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The read path revalidates through the record constructor, so a row
    # that wandered in from outside the append — here, a hand-edited naive
    # stamp — is refused rather than served: in an append-only log, one
    # unreadable row is evidence, not noise.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET ts = ? WHERE seq = 1",
            ("2026-09-20T05:00:00",),
        )
    with pytest.raises(TrialRecordError, match="seq=1"):
        test_ledger.rows()


def test_an_empty_ledger_reads_as_empty(test_ledger: TrialLedger) -> None:
    assert test_ledger.rows() == ()
    assert test_ledger.count() == 0
    assert test_ledger.get(1) is None


# -- The store's own configuration ------------------------------------------


def test_resolve_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///somewhere/ledger.db")
    ledger = TrialLedger.resolve()
    assert isinstance(ledger, TrialLedger)
    assert ledger.database_url == "sqlite:///somewhere/ledger.db"


@pytest.mark.parametrize("unset", ["", "   "])
def test_resolve_treats_blank_as_absent(
    monkeypatch: pytest.MonkeyPatch, unset: str
) -> None:
    # An unconfigured store is a discoverable state, not an error — the
    # composed application simply carries no ledger component.
    monkeypatch.setenv(DATABASE_URL_ENV, unset)
    assert TrialLedger.resolve() is None


def test_resolve_reads_a_handed_environment_over_the_process_one() -> None:
    ledger = TrialLedger.resolve({DATABASE_URL_ENV: "sqlite:///handed.db"})
    assert ledger is not None
    assert ledger.database_url == "sqlite:///handed.db"


def test_a_non_sqlite_scheme_is_refused_by_name() -> None:
    # The Postgres trial ledger arrives with the versioned migration
    # (feature 103); pretending to speak it now would hide a misrouted
    # URL behind a mysterious file.
    ledger = TrialLedger("postgresql://user@host/trials")
    with pytest.raises(TrialStoreError, match="scheme 'postgresql'"):
        ledger.path


def test_a_sqlite_url_with_a_host_is_refused() -> None:
    ledger = TrialLedger("sqlite://elsewhere/ledger.db")
    with pytest.raises(TrialStoreError, match="must not carry a host"):
        ledger.path


def test_a_pathless_sqlite_url_is_refused() -> None:
    # The in-memory spelling would give every operation its own database;
    # the second append would restart the sequence at 1 — a wrong count
    # wearing a right one's clothes.
    for url in ("sqlite://", "sqlite:///:memory:"):
        with pytest.raises(TrialStoreError, match="no database path"):
            TrialLedger(url).path


def test_an_empty_url_is_refused_at_construction() -> None:
    with pytest.raises(TrialStoreError, match="non-empty"):
        TrialLedger("  ")


def test_the_store_creates_its_file_on_first_use(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # Construction is composition-time work and touches no disk; the first
    # operation brings both the file and the table into being.
    assert not db_path.exists()
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME)
    assert db_path.is_file()
