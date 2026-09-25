"""Feature 349's seam: one structured log record per replay.

app_spec.xml, "Observability & Dashboards", feature 349: *System emits
one structured log record per replay carrying policy version, world
id, beta, score and committed pick* — docs §16's structured-logging
sentence for the replay half of the pair.  These tests pin the seam
:mod:`ops.replay_log` lands:

* **one record per call** — each ``emit_replay_log`` call puts exactly
  one stdlib ``LogRecord`` on the named logger, at INFO, and a refused
  ask puts nothing on the stream at all (the ask is validated before
  the logger is asked, the ordering every seam in this member holds
  toward the thing it writes);
* **structured means named fields** — the five fields §16's tuple
  names ride the record as attributes (``extra``), in the tuple's own
  order, and the message is the derived ``key=value`` line so a
  plain-text handler carries the same five facts a structured one
  reads;
* **the miss is emitted, never refused** — a policy that emitted no
  pick is scored ``-inf`` (feature 249's floor), and the record is the
  testimony an operator counts the miss rate against; refusing it
  would hide exactly the replays the rate is about;
* **the carrier is feature 249's TerminalPick, read duck-typed** —
  pinned with a plain stand-in for the unit contract and with the
  replay member's own record (importable through the conftest's scan
  roots) for the drift the duck-typing could silently suffer: if the
  sibling renamed ``pick`` or ``score``, this seam would refuse every
  real answer, and the pin turns that from a runtime surprise into a
  test failure;
* **no component, no store, no clock** — the sentence says *emits*,
  not *persists* (feature 255's row is the persistence half), so the
  member's registration is untouched and the module owns no table, no
  ``DATABASE_URL`` and no timestamp of its own (the ``LogRecord``'s
  ``created`` is the emission's label).
"""

from __future__ import annotations

import ast
import logging
import math
from pathlib import Path
from urllib.parse import urlparse

import pytest
import replay
from ops import (
    OPS_COMPONENT_NAME,
    OPS_DASHBOARD_COMPONENT_NAME,
    OPS_DISCOVERY_RATE_COMPONENT_NAME,
    OPS_LIVE_METRIC_COMPONENT_NAME,
    OPS_META_OVERFIT_COMPONENT_NAME,
    OPS_TYPE_B_DEPTH_COMPONENT_NAME,
    REPLAY_LOG_LEVEL,
    REPLAY_LOG_LOGGER_NAME,
    OpsError,
    ReplayLogError,
    ReplayLogRecord,
    emit_replay_log,
)

from app.module_loader import Registration, scan_components

MEMBER_SRC = Path(__import__("ops").__file__).resolve().parent.parent

#: §16's tuple, spelled once for the suite: the five names, in the
#: sentence's own order, so the fields mapping and the line derive of
#: them can be pinned against the section rather than against another
#: spelling in this module.
THE_FIVE_FIELDS = (
    "policy_version",
    "world_id",
    "beta",
    "score",
    "committed_pick",
)


class _Commit:
    """A stand-in for feature 222's CommittedPick — exactly the one
    attribute the seam reads, and nothing else."""

    __slots__ = ("node_id",)

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


class _Terminal:
    """A stand-in for feature 249's TerminalPick — exactly the two
    attributes the seam reads (the pick absent-able, the score always
    present), and nothing else.  A member never imports another
    member's *types* to test what crosses the seam; the duck-typed
    carrier is the honest way to do it, and it proves the seam
    validates what it reads."""

    __slots__ = ("pick", "score")

    def __init__(self, pick, score) -> None:
        self.pick = pick
        self.score = score


def _emitted(caplog) -> list[logging.LogRecord]:
    """The records this seam put on the stream, in emission order —
    filtered by logger name so a test's assertion is about this seam's
    records and nothing else the process may have logged."""
    return [r for r in caplog.records if r.name == REPLAY_LOG_LOGGER_NAME]


def _code_of(module) -> str:
    """A module's *code* as unparsed text, with every docstring
    stripped — the promotion member's own technique, so a test can
    assert a claim about what a module does (registers nothing, opens
    no store, reads no clock) without tripping on the prose that says
    so."""
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    holders = [tree]
    holders += [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for holder in holders:
        body = holder.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            holder.body = body[1:]
    return ast.unparse(tree)


# -- one record per replay ---------------------------------------------------------------


def test_one_call_emits_exactly_one_record(caplog) -> None:
    # The feature's own count: one replay, one structured record.  Not
    # zero (a seam that dropped records would quietly shrink the miss
    # rate), not two (a seam that emitted per field would give a
    # pipeline five partial records to reassemble).
    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        record = emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", 0.5)
    emitted = _emitted(caplog)
    assert len(emitted) == 1
    assert emitted[0].message == record.line


def test_the_record_is_emitted_at_info_on_the_named_logger(caplog) -> None:
    # INFO, because §10.4's arithmetic makes the volume argument
    # (200 worlds × 40 revisions ≈ 8000 records per dreaming cycle):
    # WARNING would page eight thousand times a cycle for routine
    # testimony, DEBUG would default the stream off.  The logger name
    # is a literal constant — not ``__name__``, which the loader's
    # synthetic-name wrinkle would re-spell under a re-execution — and
    # it nests under "ops" so the deployment's one handler on the
    # parent captures the member's whole log surface.
    assert REPLAY_LOG_LOGGER_NAME == "ops.replay_log"
    assert REPLAY_LOG_LEVEL == logging.INFO
    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", 0.5)
    (emitted,) = _emitted(caplog)
    assert emitted.name == REPLAY_LOG_LOGGER_NAME
    assert emitted.levelno == REPLAY_LOG_LEVEL


def test_a_handler_on_the_ops_parent_captures_the_record() -> None:
    # The dotted-name decision, pinned: the record propagates from
    # "ops.replay_log" through "ops" to the root, so a deployment's
    # single configuration of the parent — one handler, one level —
    # ships this seam's records and the evaluation records feature 348
    # will emit beside them.  One knob, not one per seam: the seam's
    # own logger carries no level of its own (NOTSET), so the parent's
    # INFO is the effective level the emission passes.
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    parent = logging.getLogger("ops")
    handler = _Capture(level=logging.INFO)
    parent.addHandler(handler)
    previous_level = parent.level
    parent.setLevel(logging.INFO)
    try:
        emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", 0.5)
    finally:
        parent.setLevel(previous_level)
        parent.removeHandler(handler)
    assert len(captured) == 1
    assert captured[0].name == REPLAY_LOG_LOGGER_NAME
    assert captured[0].policy_version == "rev-3"


def test_two_replays_emit_two_records_in_order(caplog) -> None:
    # The stream is per-replay testimony, and §10.4's pool is 200
    # worlds × 40 revisions of it: two calls answer two records, in
    # emission order, each carrying its own replay's identity.
    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        first = emit_replay_log(_Terminal(None, -math.inf), "rev-3", "world-1", 0.5)
        second = emit_replay_log(_Terminal(_Commit("node-9"), 0.75), "rev-4", "world-2", 0.25)
    emitted = _emitted(caplog)
    assert [r.message for r in emitted] == [first.line, second.line]
    assert emitted[0].world_id == "world-1"
    assert emitted[1].world_id == "world-2"


# -- structured means named fields -------------------------------------------------------


def test_the_five_fields_ride_the_record_as_attributes(caplog) -> None:
    # Structured, in the sense a pipeline means: the five values are
    # attributes of the emitted LogRecord (passed as ``extra``), so a
    # structured formatter reads them without parsing anything.
    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", 0.5)
    (emitted,) = _emitted(caplog)
    assert emitted.policy_version == "rev-3"
    assert emitted.world_id == "world-12"
    assert emitted.beta == 0.5
    assert emitted.score == 0.25
    assert emitted.committed_pick == "node-7"


def test_fields_is_exactly_the_five_names_in_the_sentences_order() -> None:
    # §16's tuple is the schema: the mapping carries the five names the
    # sentence spells, in the sentence's own order, and no sixth field
    # a later edit could grow opinions the deployment's parser would
    # then have to track.
    record = ReplayLogRecord(
        policy_version="rev-3",
        world_id="world-12",
        beta=0.5,
        score=0.25,
        committed_pick="node-7",
    )
    assert tuple(record.fields) == THE_FIVE_FIELDS
    assert record.fields["policy_version"] == "rev-3"
    assert record.fields["committed_pick"] == "node-7"


def test_fields_is_a_fresh_mapping_per_read() -> None:
    # A dict, not a frozen proxy: the deployment's serializer owns the
    # mapping's next step (``json.dumps`` refuses a proxy), and the
    # freshness is what lets a caller treat its copy as its own —
    # mutating one read's mapping cannot reach the record or the next
    # read of it.
    record = ReplayLogRecord("rev-3", "world-12", 0.5, 0.25, "node-7")
    first = record.fields
    first["score"] = 99.0
    assert record.fields["score"] == 0.25
    assert record.fields is not first


def test_the_line_names_every_field(caplog) -> None:
    # The message a plain-text handler prints: every field, once, in
    # §16's order, as ``key=value`` — derived from the same mapping the
    # ``extra`` carriage reads, so the line and the attributes cannot
    # disagree about what the record says.
    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        record = emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", 0.5)
    (emitted,) = _emitted(caplog)
    assert emitted.message == record.line
    assert record.line == (
        "replay policy_version=rev-3 world_id=world-12 "
        "beta=0.5 score=0.25 committed_pick=node-7"
    )


# -- the miss is emitted, never refused --------------------------------------------------


def test_the_miss_is_emitted_not_refused(caplog) -> None:
    # Feature 249's law, held at the emission: a policy that emitted
    # no pick is scored the floor, and the record is testimony of that
    # scoring — the miss rate is counted off this stream, and a seam
    # that refused the miss would hide exactly the replays the rate is
    # about.  The pick is absent (None), not dashed and not zero: the
    # decision that was never made stays distinguishable from one that
    # was.
    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        record = emit_replay_log(_Terminal(None, -math.inf), "rev-3", "world-12", 0.5)
    (emitted,) = _emitted(caplog)
    assert emitted.score == -math.inf
    assert emitted.committed_pick is None
    assert record.committed is False
    assert "committed_pick=None" in emitted.message
    assert "score=-inf" in emitted.message


def test_the_flag_and_the_pick_read_separately() -> None:
    # The split feature 249's own record documents for the dreaming
    # loop that logs per run: ``committed`` is the flag (never stored,
    # derived), ``committed_pick`` is the address, and a caller that
    # branches on "did this revision commit" does not have to spell
    # the sentinel comparison this record already owns.
    miss = emit_replay_log(_Terminal(None, -math.inf), "rev-3", "world-12", 0.5)
    made = emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", 0.5)
    assert (miss.committed, miss.committed_pick) == (False, None)
    assert (made.committed, made.committed_pick) == (True, "node-7")


def test_the_real_terminal_pick_emits_through_the_seam(caplog) -> None:
    # The drift pin the duck-typing owes: the replay member's own
    # record — the carrier the dreaming loop actually holds — emits
    # through this seam for both polarities, with the member's own
    # floor spelled for the miss.  If the sibling renamed ``pick`` or
    # ``score``, this is where it stops being a runtime surprise.
    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        miss = emit_replay_log(
            replay.TerminalPick(pick=None, score=replay.NON_COMMITTING_SCORE),
            "rev-3",
            "world-12",
            0.5,
        )
    (emitted,) = _emitted(caplog)
    assert miss.score == replay.NON_COMMITTING_SCORE == -math.inf
    assert emitted.score == -math.inf
    assert emitted.committed_pick is None


def test_a_real_committed_pick_carries_its_node_id(caplog) -> None:
    # Feature 222's pick is the address the record carries, read as
    # the pick made it: the policy-runtime member's own value type
    # (validated at its construction) emits its node id unchanged.
    from policy_runtime import CommittedPick

    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        emit_replay_log(
            replay.TerminalPick(pick=CommittedPick(node_id="node-42"), score=-0.125),
            "rev-9",
            "world-3",
            0.25,
        )
    (emitted,) = _emitted(caplog)
    assert emitted.committed_pick == "node-42"
    assert emitted.score == -0.125


# -- the ask is refused before anything is emitted ---------------------------------------


def test_a_carrier_with_no_score_is_refused_and_emits_nothing(caplog) -> None:
    # Not a terminal answer: the record is shaped around the pair the
    # terminal requirement answers (the pick absent-able, the score
    # always present), and a carrier with no score answers no completed
    # scoring.  Refused before the logger is asked — nothing lands on
    # the stream.
    class _NotATerminal:
        __slots__ = ()

    with (
        caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME),
        pytest.raises(ReplayLogError, match="no `score`"),
    ):
        emit_replay_log(_NotATerminal(), "rev-3", "world-12", 0.5)
    assert _emitted(caplog) == []


def test_a_carried_pick_that_names_no_node_is_refused(caplog) -> None:
    # A pick that names no node is a decision no address answers, and
    # testimony of one would be a committed pick no node could back.
    class _Addressless:
        __slots__ = ()

    with (
        caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME),
        pytest.raises(ReplayLogError, match="no node id"),
    ):
        emit_replay_log(_Terminal(_Addressless(), 0.25), "rev-3", "world-12", 0.5)
    assert _emitted(caplog) == []


@pytest.mark.parametrize(
    "bad_pick",
    [
        _Commit("   "),
        _Commit(""),
        42,
        True,
    ],
)
def test_a_pick_the_record_would_have_to_respell_is_refused(bad_pick, caplog) -> None:
    # The record carries the address as the pick made it: a blank or a
    # non-string is refused rather than str()-ed into a spelling the
    # pick never made — testimony that re-spelled its own address
    # would be an address nobody committed to.
    with (
        caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME),
        pytest.raises(ReplayLogError, match="committed pick"),
    ):
        emit_replay_log(_Terminal(bad_pick, 0.25), "rev-3", "world-12", 0.5)
    assert _emitted(caplog) == []


@pytest.mark.parametrize(
    "bad_score",
    [
        None,
        "0.25",
        True,
        float("nan"),
    ],
)
def test_a_score_that_is_not_a_real_number_or_the_miss_is_refused(bad_score, caplog) -> None:
    # A NaN compares false against everything and would read as "no
    # scoring" — the one reading testimony must never support, and the
    # same reason feature 249 refuses to score one and the row's
    # writer refuses to persist one.  A non-number (and a bool, which
    # is ``1``) names no verdict at all.  The miss is ``-inf`` and is
    # *not* here: it is emitted, never refused.
    with (
        caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME),
        pytest.raises(ReplayLogError, match="score"),
    ):
        emit_replay_log(_Terminal(_Commit("node-7"), bad_score), "rev-3", "world-12", 0.5)
    assert _emitted(caplog) == []


@pytest.mark.parametrize(
    "bad_beta",
    [
        None,
        "0.5",
        True,
        float("inf"),
        float("-inf"),
        float("nan"),
    ],
)
def test_a_beta_no_reader_could_reproduce_under_is_refused(bad_beta, caplog) -> None:
    # The beta is the hyperparameter the score was earned under: an
    # infinity (either sign) is a value outside the space the scoring
    # was made in, a NaN is not a hyperparameter, and a bool is a flag
    # standing where a number belongs.
    with (
        caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME),
        pytest.raises(ReplayLogError, match="beta"),
    ):
        emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", bad_beta)
    assert _emitted(caplog) == []


@pytest.mark.parametrize(
    "bad_id",
    [
        None,
        42,
        "",
        "   ",
    ],
)
@pytest.mark.parametrize("which", ["policy_version", "world_id"])
def test_an_id_that_names_no_replay_is_refused(bad_id, which, caplog) -> None:
    # The pair is the identity every downstream count groups by — the
    # miss rate, the per-(policy, world) verdict, the argmax — and an
    # id that names nothing writes testimony no pair names.
    with caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME):
        if which == "policy_version":
            with pytest.raises(ReplayLogError, match="policy version"):
                emit_replay_log(
                    _Terminal(_Commit("node-7"), 0.25), bad_id, "world-12", 0.5
                )
        else:
            with pytest.raises(ReplayLogError, match="world id"):
                emit_replay_log(
                    _Terminal(_Commit("node-7"), 0.25), "rev-3", bad_id, 0.5
                )
    assert _emitted(caplog) == []


def test_the_refusals_are_the_members_vocabulary(caplog) -> None:
    # One base so a caller catches the member as a whole: a caller
    # that wrote ``except OpsError`` around its emission loop catches
    # the refused ask without importing the module that raises it.
    assert issubclass(ReplayLogError, OpsError)
    with (
        caplog.at_level(logging.INFO, logger=REPLAY_LOG_LOGGER_NAME),
        pytest.raises(OpsError),
    ):
        emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "", "world-12", 0.5)
    assert _emitted(caplog) == []


def test_a_hand_built_record_is_held_to_the_same_law() -> None:
    # The record is publicly constructible (a test, a later adapter
    # over recorded answers), and a frozen value that validated
    # nothing would lend the seam's guarantees to testimony nobody
    # stood behind — so construction refuses what the emission path
    # refuses, on both halves of the pair.
    with pytest.raises(ReplayLogError):
        ReplayLogRecord(policy_version="", world_id="world-12", beta=0.5, score=0.25, committed_pick=None)
    with pytest.raises(ReplayLogError):
        ReplayLogRecord(policy_version="rev-3", world_id="world-12", beta=0.5, score=float("nan"), committed_pick=None)
    with pytest.raises(ReplayLogError):
        ReplayLogRecord(policy_version="rev-3", world_id="world-12", beta=float("inf"), score=0.25, committed_pick="node-7")
    with pytest.raises(ReplayLogError):
        ReplayLogRecord(policy_version="rev-3", world_id="world-12", beta=0.5, score=0.25, committed_pick="  ")
    # And the miss constructs, because the miss is testimony:
    miss = ReplayLogRecord("rev-3", "world-12", 0.5, -math.inf, None)
    assert miss.committed is False


# -- no store, no component, no clock ----------------------------------------------------


def test_the_sentence_demands_no_state_so_nothing_composes() -> None:
    # The member's registration-grows-per-feature law: each feature
    # composes only if its sentence demands state a deployment holds,
    # and an emission demands none — the scan still registers exactly
    # the stateful components (the route, the dashboard, the
    # live-metrics store, feature 347's meta-overfit gap store, feature
    # 346's discovery-rate store and feature 345's Type-B depth store)
    # and no ``replay-log`` seventh.
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    assert sorted(component.name for component in components) == sorted(
        {
            OPS_COMPONENT_NAME,
            OPS_DASHBOARD_COMPONENT_NAME,
            OPS_LIVE_METRIC_COMPONENT_NAME,
            OPS_META_OVERFIT_COMPONENT_NAME,
            OPS_DISCOVERY_RATE_COMPONENT_NAME,
            OPS_TYPE_B_DEPTH_COMPONENT_NAME,
        }
    )
    assert "ops-replay-log" not in registry.names()


def test_the_module_never_restates_the_row_or_reads_a_clock() -> None:
    # The persistence half is feature 255's row, and this seam is the
    # emission half: no SQL, no DATABASE_URL, no store of its own on
    # the code (docstrings stripped) — and no clock either, because
    # the one timestamp the emission carries is the LogRecord's own
    # ``created``, read where the record is made.  The sibling is
    # never imported: the carrier arrives duck-typed, so the module
    # carries no handle on ``replay`` at any scope.
    from ops import replay_log as module

    code = _code_of(module)
    for absent in (
        "SELECT",
        "DATABASE_URL",
        "sqlite3",
        "uuid",
        "datetime",
        "time.",  # no clock of the module's own — the LogRecord's created is the label
        "import replay",
        "from replay",
        "@register",
    ):
        assert absent not in code, absent


def test_the_module_never_touches_a_database_when_emitting(test_database_url: str) -> None:
    # Importing the member (which every factory scan does) must cost
    # no I/O: the seam owns no store, so the emission path never opens
    # one — the database the fixtures point at stays untouched by an
    # emission, unlike the store-holding surfaces beside it.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", 0.5)
    assert not database_path.exists()
