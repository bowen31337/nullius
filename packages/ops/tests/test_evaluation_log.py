"""Feature 348's seam: one structured log record per evaluation.

app_spec.xml, "Observability & Dashboards", feature 348: *System emits
one structured log record per evaluation carrying the full provenance
triple plus node_id and campaign_id* — docs §16's structured-logging
sentence for the evaluation half of the pair (349's replay half is
this suite's sibling, ``test_replay_log.py``).  These tests pin the
seam :mod:`ops.evaluation_log` lands:

* **one record per call** — each ``emit_evaluation_log`` call puts
  exactly one stdlib ``LogRecord`` on the named logger, at INFO, and a
  refused ask puts nothing on the stream at all (the ask is validated
  before the logger is asked, the ordering every seam in this member
  holds toward the thing it writes);
* **structured means named fields** — the five fields §16's sentence
  names (the provenance triple in §8's declaration order, then the two
  ids the sentence adds) ride the record as attributes (``extra``),
  in the sentence's own order, and the message is the derived
  ``key=value`` line so a plain-text handler carries the same five
  facts a structured one reads;
* **the spellings are canonical** — the three hash terms fold to the
  lowercase 64-hex §8's ``CHAR(64)`` columns hold and the two ids to
  the hyphenated lowercase UUID §8's ``UUID`` columns store, so the
  record joins the row it mirrors at a stream-side join instead of
  drifting from it by casing;
* **the carrier is the charge, read duck-typed** — pinned with a plain
  stand-in for the unit contract and with the ledger member's own
  record (importable through the conftest's scan roots) for the drift
  the duck-typing could silently suffer: if the sibling renamed
  ``evaluator_hash``, this seam would refuse every real charge, and
  the pin turns that from a runtime surprise into a test failure.
  The pre-stamp row (triple ``None``) is refused, not emitted — that
  ``None`` is a fact about the ledger's history, not provenance an
  evaluation ran under;
* **no component, no store, no clock** — the sentence says *emits*,
  not *persists* (feature 87's stamp on the trial row is the
  persistence half), so the member's registration is untouched and
  the module owns no table, no ``DATABASE_URL`` and no timestamp of
  its own (the ``LogRecord``'s ``created`` is the emission's label).
"""

from __future__ import annotations

import ast
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import ledger
import pytest
from ops import (
    EVALUATION_LOG_LEVEL,
    EVALUATION_LOG_LOGGER_NAME,
    EvaluationLogError,
    EvaluationLogRecord,
    OpsError,
    emit_evaluation_log,
)

from app.module_loader import Registration, scan_components

MEMBER_SRC = Path(__import__("ops").__file__).resolve().parent.parent

#: §16's sentence, spelled once for the suite: the provenance triple in
#: §8's declaration order (the order ``PROVENANCE_COLUMNS`` states and
#: the table's columns land in), then the two ids the sentence adds —
#: so the fields mapping and the line derive of them can be pinned
#: against the section rather than against another spelling in this
#: module.
THE_FIVE_FIELDS = (
    "evaluator_hash",
    "snapshot_hash",
    "cost_model_hash",
    "node_id",
    "campaign_id",
)

#: One evaluation's five facts, distinct per term so a swap anywhere in
#: the seam is detectable: three sha256 hexdigests (feature 70's, §4.2's
#: seal's, feature 60's) and the two identity columns §8 declares.
EVALUATOR_HASH = "e" * 64
SNAPSHOT_HASH = "5" * 64
COST_MODEL_HASH = "c" * 64
NODE_ID = "55555555-5555-5555-5555-555555555555"
CAMPAIGN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"

#: The stand-in's five attributes, keyed by name — the one spelling the
#: missing-field and swap tests read, so a stand-in minus one field (or
#: with one overridden) is built from the same values the happy path
#: emits.
_THE_FACTS = {
    "evaluator_hash": EVALUATOR_HASH,
    "snapshot_hash": SNAPSHOT_HASH,
    "cost_model_hash": COST_MODEL_HASH,
    "node_id": NODE_ID,
    "campaign_id": CAMPAIGN_ID,
}


class _Trial:
    """A stand-in for the charge an evaluation was booked as — exactly
    the five attributes the seam reads, and nothing else.  A member
    never imports another member's *types* to test what crosses the
    seam; the duck-typed carrier is the honest way to do it, and it
    proves the seam validates what it reads."""

    __slots__ = (
        "campaign_id",
        "cost_model_hash",
        "evaluator_hash",
        "node_id",
        "snapshot_hash",
    )

    def __init__(
        self,
        evaluator_hash: str = EVALUATOR_HASH,
        snapshot_hash: str = SNAPSHOT_HASH,
        cost_model_hash: str = COST_MODEL_HASH,
        node_id: str = NODE_ID,
        campaign_id: str = CAMPAIGN_ID,
    ) -> None:
        self.evaluator_hash = evaluator_hash
        self.snapshot_hash = snapshot_hash
        self.cost_model_hash = cost_model_hash
        self.node_id = node_id
        self.campaign_id = campaign_id


def _stand_in_without(name: str) -> SimpleNamespace:
    """The stand-in minus one field — the carrier that does not state
    one of the five facts the sentence names."""
    return SimpleNamespace(
        **{key: value for key, value in _THE_FACTS.items() if key != name}
    )


def _stand_in_overriding(name: str, value: object) -> SimpleNamespace:
    """The stand-in with one field's value replaced — the carrier that
    states all five facts but one of them in a shape the record could
    not honestly carry."""
    return SimpleNamespace(**{**_THE_FACTS, name: value})


def _emitted(caplog) -> list[logging.LogRecord]:
    """The records this seam put on the stream, in emission order —
    filtered by logger name so a test's assertion is about this seam's
    records and nothing else the process may have logged."""
    return [r for r in caplog.records if r.name == EVALUATION_LOG_LOGGER_NAME]


def _code_of(module) -> str:
    """A module's *code* as unparsed text, with every docstring
    stripped — the promotion member's own technique, so a test can
    assert a claim about what a module does (registers nothing, opens
    no store, reads no clock) without tripping on the prose that says
    so.  ``ast.unparse`` drops comments with the prose, so the check
    below sees code only."""
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


def _charged_trial(outcome: str = "ok") -> ledger.TrialLedgerRecord:
    """The ledger member's own record for one charged evaluation — the
    carrier the evaluation's debit actually answers, built through the
    sibling member's own constructor so the drift pin reads what the
    charge path really states, not a second spelling of it."""
    return ledger.TrialLedgerRecord(
        seq=1,
        ts=datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC),
        node_id=NODE_ID,
        campaign_id=CAMPAIGN_ID,
        outcome=outcome,
        charges_budget=True,
        epoch_id="sequestered-epoch-7",
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
    )


# -- one record per evaluation -------------------------------------------------------------


def test_one_call_emits_exactly_one_record(caplog) -> None:
    # The feature's own count: one evaluation, one structured record.
    # Not zero (a seam that dropped records would quietly shrink any
    # count the stream is held against), not two (a seam that emitted
    # per field would give a pipeline five partial records to
    # reassemble).
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        record = emit_evaluation_log(_Trial())
    emitted = _emitted(caplog)
    assert len(emitted) == 1
    assert emitted[0].message == record.line


def test_the_record_is_emitted_at_info_on_the_named_logger(caplog) -> None:
    # INFO, because the record's volume is the ledger's own grain (one
    # row per evaluation is the system's unit of accounting): WARNING
    # would page once per charge for routine testimony, DEBUG would
    # default the stream off — and the replay half already ships at
    # INFO, so one level for the pair is what makes the parent's knob a
    # single knob.  The logger name is a literal constant — not
    # ``__name__``, which the loader's synthetic-name wrinkle would
    # re-spell under a re-execution — and it nests under "ops" so the
    # deployment's one handler on the parent captures the member's
    # whole log surface.
    assert EVALUATION_LOG_LOGGER_NAME == "ops.evaluation_log"
    assert EVALUATION_LOG_LEVEL == logging.INFO
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        emit_evaluation_log(_Trial())
    (emitted,) = _emitted(caplog)
    assert emitted.name == EVALUATION_LOG_LOGGER_NAME
    assert emitted.levelno == EVALUATION_LOG_LEVEL


def test_a_handler_on_the_ops_parent_captures_both_halves_of_the_pair() -> None:
    # The dotted-name decision, pinned for the pair: both records
    # propagate from their "ops.*" loggers through "ops" to the root,
    # so a deployment's single configuration of the parent — one
    # handler, one level — ships the evaluation records and the replay
    # records §16's sentence states as one structured-logging surface.
    # One knob, not one per seam: neither logger carries a level of its
    # own (NOTSET), so the parent's INFO is the effective level both
    # emissions pass.
    from ops import REPLAY_LOG_LOGGER_NAME, emit_replay_log

    class _Commit:
        __slots__ = ("node_id",)

        def __init__(self, node_id: str) -> None:
            self.node_id = node_id

    class _Terminal:
        __slots__ = ("pick", "score")

        def __init__(self, pick, score) -> None:
            self.pick = pick
            self.score = score

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
        emit_evaluation_log(_Trial())
        emit_replay_log(_Terminal(_Commit("node-7"), 0.25), "rev-3", "world-12", 0.5)
    finally:
        parent.setLevel(previous_level)
        parent.removeHandler(handler)
    assert [r.name for r in captured] == [
        EVALUATION_LOG_LOGGER_NAME,
        REPLAY_LOG_LOGGER_NAME,
    ]
    assert captured[0].campaign_id == CAMPAIGN_ID
    assert captured[1].policy_version == "rev-3"


def test_two_evaluations_emit_two_records_in_order(caplog) -> None:
    # The stream is per-evaluation testimony, and the ledger's grain is
    # one row per evaluation: two calls answer two records, in emission
    # order, each carrying its own evaluation's identity.
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        first = emit_evaluation_log(_Trial(node_id=NODE_ID))
        second = emit_evaluation_log(
            _Trial(
                evaluator_hash="d" * 64,
                snapshot_hash="6" * 64,
                cost_model_hash="f" * 64,
                node_id="77777777-7777-7777-7777-777777777777",
                campaign_id="99999999-9999-9999-9999-999999999999",
            )
        )
    emitted = _emitted(caplog)
    assert [r.message for r in emitted] == [first.line, second.line]
    assert emitted[0].node_id == NODE_ID
    assert emitted[1].node_id == "77777777-7777-7777-7777-777777777777"


# -- structured means named fields ---------------------------------------------------------


def test_the_five_fields_ride_the_record_as_attributes(caplog) -> None:
    # Structured, in the sense a pipeline means: the five values are
    # attributes of the emitted LogRecord (passed as ``extra``), so a
    # structured formatter reads them without parsing anything.
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        emit_evaluation_log(_Trial())
    (emitted,) = _emitted(caplog)
    assert emitted.evaluator_hash == EVALUATOR_HASH
    assert emitted.snapshot_hash == SNAPSHOT_HASH
    assert emitted.cost_model_hash == COST_MODEL_HASH
    assert emitted.node_id == NODE_ID
    assert emitted.campaign_id == CAMPAIGN_ID


def test_fields_is_exactly_the_five_names_in_the_sentences_order() -> None:
    # §16's sentence is the schema: the mapping carries the triple in
    # §8's declaration order then the two ids the sentence adds, and no
    # sixth field a later edit could grow opinions the deployment's
    # parser would then have to track.
    record = EvaluationLogRecord(
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        node_id=NODE_ID,
        campaign_id=CAMPAIGN_ID,
    )
    assert tuple(record.fields) == THE_FIVE_FIELDS
    assert record.fields["evaluator_hash"] == EVALUATOR_HASH
    assert record.fields["campaign_id"] == CAMPAIGN_ID


def test_fields_is_a_fresh_mapping_per_read() -> None:
    # A dict, not a frozen proxy: the deployment's serializer owns the
    # mapping's next step (``json.dumps`` refuses a proxy), and the
    # freshness is what lets a caller treat its copy as its own —
    # mutating one read's mapping cannot reach the record or the next
    # read of it.
    record = EvaluationLogRecord(
        EVALUATOR_HASH, SNAPSHOT_HASH, COST_MODEL_HASH, NODE_ID, CAMPAIGN_ID
    )
    first = record.fields
    first["node_id"] = "00000000-0000-0000-0000-000000000000"
    assert record.fields["node_id"] == NODE_ID
    assert record.fields is not first


def test_the_line_names_every_field(caplog) -> None:
    # The message a plain-text handler prints: every field, once, in
    # §16's order, as ``key=value`` — derived from the same mapping the
    # ``extra`` carriage reads, so the line and the attributes cannot
    # disagree about what the record says.
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        record = emit_evaluation_log(_Trial())
    (emitted,) = _emitted(caplog)
    assert emitted.message == record.line
    assert record.line == (
        f"evaluation evaluator_hash={EVALUATOR_HASH} "
        f"snapshot_hash={SNAPSHOT_HASH} cost_model_hash={COST_MODEL_HASH} "
        f"node_id={NODE_ID} campaign_id={CAMPAIGN_ID}"
    )


# -- the spellings are canonical, so the record joins the row ------------------------------


def test_an_uppercase_or_padded_hash_folds_to_the_rows_spelling(caplog) -> None:
    # A hash pasted from a report is commonly uppercase or
    # whitespace-padded, means the same value, and is folded rather
    # than refused — the same treatment the ledger's own stamp gives
    # the columns this record mirrors, so the record joins the row at a
    # stream-side join instead of drifting from it by casing.
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        record = emit_evaluation_log(
            _Trial(
                evaluator_hash=f"  {EVALUATOR_HASH.upper()} ",
                snapshot_hash=SNAPSHOT_HASH.upper(),
                cost_model_hash=COST_MODEL_HASH,
            )
        )
    (emitted,) = _emitted(caplog)
    assert record.evaluator_hash == EVALUATOR_HASH
    assert record.snapshot_hash == SNAPSHOT_HASH
    assert emitted.evaluator_hash == EVALUATOR_HASH
    assert emitted.snapshot_hash == SNAPSHOT_HASH


def test_a_uuid_object_and_a_bare_hex_spelling_canonicalize(caplog) -> None:
    # §8's identity columns are UUIDs, and the row stores the canonical
    # hyphenated lowercase spelling so it joins against the tree store;
    # the record mirrors the row, so a :class:`uuid.UUID` object and a
    # bare 32-hex spelling both canonicalize to that one form — the
    # stream's testimony and the row it mirrors name the same
    # evaluation in the same spelling.
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        record = emit_evaluation_log(
            _Trial(
                node_id=uuid.UUID(NODE_ID),
                campaign_id=CAMPAIGN_ID.replace("-", "").upper(),
            )
        )
    (emitted,) = _emitted(caplog)
    assert record.node_id == NODE_ID
    assert record.campaign_id == CAMPAIGN_ID
    assert emitted.node_id == NODE_ID
    assert emitted.campaign_id == CAMPAIGN_ID


# -- the carrier is the charge, read duck-typed --------------------------------------------


def test_the_ledgers_own_trial_record_emits_through_the_seam(caplog) -> None:
    # The drift pin the duck-typing owes: the ledger member's own
    # record — the carrier the evaluation's debit answers, carrying
    # six more facts than the seam reads — emits through this seam
    # with all five fields intact and none of the rest leaked onto the
    # record.  If the sibling renamed ``evaluator_hash`` or
    # ``campaign_id``, this is where it stops being a runtime surprise.
    trial = _charged_trial()
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        record = emit_evaluation_log(trial)
    (emitted,) = _emitted(caplog)
    assert record.evaluator_hash == trial.evaluator_hash
    assert record.snapshot_hash == trial.snapshot_hash
    assert record.cost_model_hash == trial.cost_model_hash
    assert record.node_id == trial.node_id
    assert record.campaign_id == trial.campaign_id
    assert tuple(record.fields) == THE_FIVE_FIELDS
    assert emitted.evaluator_hash == EVALUATOR_HASH
    assert emitted.snapshot_hash == SNAPSHOT_HASH
    assert emitted.cost_model_hash == COST_MODEL_HASH
    assert emitted.node_id == NODE_ID
    assert emitted.campaign_id == CAMPAIGN_ID
    # The carrier's other facts — seq, ts, outcome, charge, epoch — are
    # the row's, not the sentence's, and none of them ride the record.
    assert not hasattr(emitted, "outcome")
    assert not hasattr(emitted, "epoch_id")


def test_a_failed_evaluations_record_ships_the_same_five_fields(caplog) -> None:
    # §16's sentence names identity fields and no verdict, and §8's
    # outcome vocabulary exists because a failed trial is as chargeable
    # a fact as a successful one: an errored evaluation's record emits
    # — the identity the record carries exists whatever the verdict
    # was, and the stream counts evaluations, not verdicts.
    with caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME):
        record = emit_evaluation_log(_charged_trial(outcome="error"))
    (emitted,) = _emitted(caplog)
    assert emitted.node_id == NODE_ID
    assert tuple(record.fields) == THE_FIVE_FIELDS
    assert "outcome" not in record.fields


def test_a_prestamp_row_names_no_provenance_and_is_refused(caplog) -> None:
    # ``None`` is the *read's* spelling for a ledger row that predates
    # feature 87's stamp — a statement about the ledger's history, not
    # provenance an evaluation ran under — and the ledger's own write
    # seams refuse the same absence for the same reason: a charge that
    # cannot name its triple is a charge no replay can reproduce.
    # Refused before the logger is asked; nothing lands on the stream.
    pre_stamp = ledger.TrialLedgerRecord(
        seq=2,
        ts=datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC),
        node_id=NODE_ID,
        campaign_id=CAMPAIGN_ID,
        outcome="ok",
        charges_budget=True,
    )
    assert pre_stamp.evaluator_hash is None
    with (
        caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME),
        pytest.raises(EvaluationLogError, match="evaluator_hash.*required"),
    ):
        emit_evaluation_log(pre_stamp)
    assert _emitted(caplog) == []


# -- the ask is refused before anything is emitted -----------------------------------------


@pytest.mark.parametrize("missing", THE_FIVE_FIELDS)
def test_a_carrier_that_does_not_state_a_field_is_refused(missing, caplog) -> None:
    # The record's schema is §16's sentence, and a carrier that does
    # not state one of the five fields names no evaluation the ledger
    # could join — testimony of one would be a structured record nobody
    # booked.  Refused before the logger is asked.
    with (
        caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME),
        pytest.raises(EvaluationLogError, match=f"no `{missing}`"),
    ):
        emit_evaluation_log(_stand_in_without(missing))
    assert _emitted(caplog) == []


def test_a_bare_object_is_refused_naming_what_arrived(caplog) -> None:
    # The reader refuses naming what arrived, so the repair is
    # findable: a carrier with none of the five fields is a caller bug
    # at the emission, not a silent empty record.
    class _Nothing:
        __slots__ = ()

    with (
        caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME),
        pytest.raises(EvaluationLogError, match="has no `evaluator_hash`"),
    ):
        emit_evaluation_log(_Nothing())
    assert _emitted(caplog) == []


@pytest.mark.parametrize(
    "bad_hash",
    [
        None,
        "",
        "   ",
        "e" * 63,
        "e" * 65,
        "z" * 64,
        "sha256:" + "e" * 64,
        42,
        True,
    ],
)
@pytest.mark.parametrize(
    "column", ["evaluator_hash", "snapshot_hash", "cost_model_hash"]
)
def test_a_hash_that_is_not_the_digests_own_spelling_is_refused(
    bad_hash, column, caplog
) -> None:
    # The one shape the ledger's stamp holds all three columns to: the
    # sha256 hexdigest's own 64-hex spelling.  A ``sha256:``-prefixed
    # value is an *image reference*, not the hash over it; a short
    # hash, a non-hex token or a non-string names no evaluator,
    # snapshot or cost model this system recorded; ``None`` is the
    # pre-stamp read's spelling, refused as such above.
    with (
        caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME),
        pytest.raises(EvaluationLogError),
    ):
        emit_evaluation_log(_stand_in_overriding(column, bad_hash))
    assert _emitted(caplog) == []


def test_an_image_reference_is_refused_on_its_own_ground(caplog) -> None:
    # The refusal a stream-side join exists to need: a digest compared
    # against a hash must get "different" only when the values differ,
    # never because one side carried the algorithm prefix the other
    # shed — the same ground the ledger's own stamp refuses it on.
    with (
        caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME),
        pytest.raises(EvaluationLogError, match="image reference"),
    ):
        emit_evaluation_log(
            _stand_in_overriding("cost_model_hash", "sha256:" + COST_MODEL_HASH)
        )
    assert _emitted(caplog) == []


@pytest.mark.parametrize(
    "bad_id",
    [
        None,
        42,
        True,
        "node-7",
        "",
        "not-a-uuid-at-all",
    ],
)
@pytest.mark.parametrize("which", ["node_id", "campaign_id"])
def test_an_id_that_is_not_a_uuid_is_refused(bad_id, which, caplog) -> None:
    # §8's identity columns are ``UUID`` and the row stores the
    # canonical spelling that joins against the tree store: an id that
    # is not a UUID names no evaluation the ledger could join, and
    # testimony that re-spelled its own identity would be an identity
    # nothing answers.
    with (
        caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME),
        pytest.raises(EvaluationLogError, match="is a UUID"),
    ):
        emit_evaluation_log(_stand_in_overriding(which, bad_id))
    assert _emitted(caplog) == []


def test_the_refusals_are_the_members_vocabulary(caplog) -> None:
    # One base so a caller catches the member as a whole: a caller
    # that wrote ``except OpsError`` around its emission loop catches
    # the refused ask without importing the module that raises it.
    assert issubclass(EvaluationLogError, OpsError)
    with (
        caplog.at_level(logging.INFO, logger=EVALUATION_LOG_LOGGER_NAME),
        pytest.raises(OpsError),
    ):
        emit_evaluation_log(_Trial(node_id="node-7"))
    assert _emitted(caplog) == []


def test_a_hand_built_record_is_held_to_the_same_law() -> None:
    # The record is publicly constructible (a test, a later adapter
    # over the charge path), and a frozen value that validated nothing
    # would lend the seam's guarantees to testimony nobody stood
    # behind — so construction refuses what the emission path refuses,
    # on all five fields.
    with pytest.raises(EvaluationLogError):
        EvaluationLogRecord(
            evaluator_hash="short",
            snapshot_hash=SNAPSHOT_HASH,
            cost_model_hash=COST_MODEL_HASH,
            node_id=NODE_ID,
            campaign_id=CAMPAIGN_ID,
        )
    with pytest.raises(EvaluationLogError):
        EvaluationLogRecord(
            evaluator_hash=None,
            snapshot_hash=SNAPSHOT_HASH,
            cost_model_hash=COST_MODEL_HASH,
            node_id=NODE_ID,
            campaign_id=CAMPAIGN_ID,
        )
    with pytest.raises(EvaluationLogError):
        EvaluationLogRecord(
            evaluator_hash=EVALUATOR_HASH,
            snapshot_hash=SNAPSHOT_HASH,
            cost_model_hash=COST_MODEL_HASH,
            node_id="node-7",
            campaign_id=CAMPAIGN_ID,
        )
    with pytest.raises(EvaluationLogError):
        EvaluationLogRecord(
            evaluator_hash=EVALUATOR_HASH,
            snapshot_hash=SNAPSHOT_HASH,
            cost_model_hash=COST_MODEL_HASH,
            node_id=NODE_ID,
            campaign_id=42,
        )
    # And the canonical fold holds for a hand-built record too:
    built = EvaluationLogRecord(
        EVALUATOR_HASH.upper(),
        SNAPSHOT_HASH,
        COST_MODEL_HASH,
        uuid.UUID(NODE_ID),
        CAMPAIGN_ID,
    )
    assert built.evaluator_hash == EVALUATOR_HASH
    assert built.node_id == NODE_ID
    assert built.line.startswith("evaluation evaluator_hash=")


# -- no store, no component, no clock ------------------------------------------------------


def test_the_sentence_demands_no_state_so_nothing_composes() -> None:
    # The member's registration-grows-per-feature law: each feature
    # composes only if its sentence demands state a deployment holds,
    # and an emission demands none — the scan still registers exactly
    # the stateful components (the two read-only routes, the dashboard,
    # the live-metrics store, feature 347's meta-overfit gap store,
    # feature 346's discovery-rate store, feature 345's Type-B depth
    # store, feature 344's calibration store and feature 342's
    # instrument-status rail)
    # and no ``evaluation-log`` of its own.
    from ops import (
        OPS_COMPONENT_NAME,
        OPS_DASHBOARD_COMPONENT_NAME,
        OPS_DISCOVERY_RATE_COMPONENT_NAME,
        OPS_INSTRUMENT_STATUS_COMPONENT_NAME,
        OPS_LIVE_METRIC_COMPONENT_NAME,
        OPS_META_OVERFIT_COMPONENT_NAME,
        OPS_NULL_CALIBRATION_COMPONENT_NAME,
        OPS_REGIME_COVERAGE_COMPONENT_NAME,
        OPS_TYPE_B_DEPTH_COMPONENT_NAME,
    )

    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    assert sorted(component.name for component in components) == sorted(
        {
            OPS_COMPONENT_NAME,
            OPS_INSTRUMENT_STATUS_COMPONENT_NAME,
            OPS_REGIME_COVERAGE_COMPONENT_NAME,
            OPS_DASHBOARD_COMPONENT_NAME,
            OPS_LIVE_METRIC_COMPONENT_NAME,
            OPS_META_OVERFIT_COMPONENT_NAME,
            OPS_DISCOVERY_RATE_COMPONENT_NAME,
            OPS_TYPE_B_DEPTH_COMPONENT_NAME,
            OPS_NULL_CALIBRATION_COMPONENT_NAME,
        }
    )
    assert "ops-evaluation-log" not in registry.names()


def test_the_module_never_restates_the_row_or_reads_a_clock() -> None:
    # The persistence half is feature 87's stamp on the ledger's row,
    # and this seam is the emission half: no SQL, no DATABASE_URL, no
    # store of its own on the code (docstrings stripped) — and no clock
    # either, because the one timestamp the emission carries is the
    # LogRecord's own ``created``, read where the record is made.  The
    # sibling is never imported: the carrier arrives duck-typed, so the
    # module carries no handle on ``ledger`` at any scope.  ``uuid`` is
    # deliberately absent from the refused list below, unlike the
    # replay half's suite: this seam imports it to *validate* the ids'
    # canonical spelling, never to coin one — all five fields are
    # required constructor arguments, none defaulted, so there is no
    # path that could mint an identity.
    from ops import evaluation_log as module

    code = _code_of(module)
    for absent in (
        "SELECT",
        "DATABASE_URL",
        "sqlite3",
        "datetime",
        "time.",  # no clock of the module's own — the LogRecord's created is the label
        "import ledger",
        "from ledger",
        "@register",
    ):
        assert absent not in code, absent


def test_the_module_never_touches_a_database_when_emitting(
    test_database_url: str,
) -> None:
    # Importing the member (which every factory scan does) must cost
    # no I/O: the seam owns no store, so the emission path never opens
    # one — the database the fixtures point at stays untouched by an
    # emission, unlike the store-holding surfaces beside it.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    emit_evaluation_log(_Trial())
    assert not database_path.exists()
