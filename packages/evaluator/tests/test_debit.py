"""Feature 84 — the trial charge: step 11, written however the evaluation ended.

app_spec.xml feature 84: *"System persists an irreversible trial charge with
its failure outcome even when the evaluation failed, because a failed
evaluation still consumed a hypothesis."*  docs/nullius-tech-architecture.md
§6.1 names the step (``11. debit_ledger   append trial record
(irreversible)``) and its note fixes the exception that is the feature:
*"step 11 happens even if the node fails.  A failed evaluation still consumed
a hypothesis."*  §8 fixes the row's outcome vocabulary (``ok | timeout |
error | tripwire_fail``) and §14 fixes the retry contract ("Failures retry;
ledger debits are idempotent by ``node_id``").

This suite tests the charge, the classification and the debit as the three
halves of one feature sentence, each separately assertable:

* **the charge** — a frozen value over two identities, one of §8's four
  outcomes, and §7.2's opaque budget directive accepted as the bit itself or
  as the step-5/step-7 record that carries it (never derived, never
  defaulted), with every term refused rather than folded when it is outside
  the contract;
* **the classification** — the pipeline's own failure vocabulary becomes the
  ledger's four: a sandbox hard kill is ``'timeout'``, every other recorded
  fail class and every raised exception (a raised ``TimeoutError`` included)
  is ``'error'``, a conforming run is *refused* (it is not a failure — its
  outcome is ``'ok'``, stated by the caller), and an unknown fail class is
  refused rather than fabricated into a fifth outcome;
* **the debit** — the injected structural seam (``debit(node_id,
  campaign_id, outcome, charges_budget, charge_units, epoch_id,
  evaluator_hash, snapshot_hash, cost_model_hash)`` answering ``(record,
  appended)``) is charged with the whole §8 row, its answer read back
  through the charge constructor, an appended row held to the terms it was
  asked to write, and a *retry* answered by the prior row rather than
  refused — the §14 contract working;
* **the composition** — the real ``ledger.TrialLedger`` satisfies the seam
  with no adapter, a completed or failed evaluation's charge lands its
  whole row (identities, outcome, directive, unit, the sequestered
  ``epoch_id`` and feature 87's provenance triple) in the real table, a
  retry writes nothing, and a UUID spelling is compared by the identity it
  names, not the text it arrived in.

The row's required terms outside the four the evaluator's own compute
produces — the epoch (feature 88) and the provenance triple (feature 87) —
are the *ledger's* columns, and this suite fixes values for them the way
the pipeline's caller would: a fast-frozen digest, a sealed snapshot and a
loaded cost model, none of which the evaluator derives and none of which it
may default. A charge missing any of them is refused here, by this member's
own constructor, before the seam is touched.
"""

from __future__ import annotations

import dataclasses
import os

import pytest
from evaluator import (
    DEBIT_STEP,
    DEFAULT_CHARGE_UNITS,
    HORIZONS,
    PROVENANCE_HASH_LENGTH,
    TRIAL_OUTCOMES,
    CostModelRef,
    DebitedTrial,
    EvaluatorDebitError,
    GatedTargets,
    PostCostReturns,
    PostCostSeries,
    SandboxResult,
    TargetSeries,
    TrialCharge,
    charge_failure,
    debit_trial,
    failure_outcome,
)

SNAPSHOT = "snap_20240101"
NODE = "11111111-2222-3333-4444-555555555555"
CAMPAIGN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

#: The three terms of feature 87's provenance triple and feature 88's
#: epoch, as the pipeline's caller would supply them: 64-hex sha256
#: spellings (feature 70's frozen evaluator, §4.2's sealed snapshot,
#: feature 60's loaded cost model) and the sealing process's epoch name.
#: None of these is derived by the evaluator; the charge carries them
#: because §8's columns are NOT NULL and the ledger refuses a row that
#: cannot name them.
EPOCH = "epoch-0007"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH = "cd" * 32
COST_MODEL_HASH = "ef" * 32


def _required() -> dict[str, object]:
    """The four row terms the evaluator supplies but never computes.

    Spread into every charge construction so the term under test in each
    test is the only one moving — the epoch and the provenance triple are
    the *ledger's* required columns (features 87-88), stated the same way
    a pipeline caller states them.
    """
    return {
        "epoch_id": EPOCH,
        "evaluator_hash": EVALUATOR_HASH,
        "snapshot_hash": SNAPSHOT_HASH,
        "cost_model_hash": COST_MODEL_HASH,
    }


# -- hand-built carriers, for the directive's read-back -------------------------


def _gated(directive: bool) -> GatedTargets:
    """Step 5's record carrying the directive, empty of targets.

    The gate's own bundle shape (one series per horizon, one snapshot) with
    no values: the charge reads the bit off it and nothing else, so the
    targets themselves are not under test here.
    """
    return GatedTargets(
        snapshot_name=SNAPSHOT,
        rebalance_dates=(),
        series={
            h: TargetSeries(horizon=h, snapshot_name=SNAPSHOT, values={})
            for h in HORIZONS
        },
        charges_budget=directive,
    )


def _post_cost(directive: bool) -> PostCostReturns:
    """Step 7's record carrying the directive, empty of returns."""
    series = {
        h: PostCostSeries(
            horizon=h,
            snapshot_name=SNAPSHOT,
            venue="binance",
            version="v1",
            values={},
            charges={},
        )
        for h in HORIZONS
    }
    return PostCostReturns(
        node_id=NODE,
        snapshot_name=SNAPSHOT,
        rebalance_dates=(),
        cost_model=CostModelRef(venue="binance", version="v1"),
        series=series,
        charges_budget=directive,
    )


# -- stub seam ------------------------------------------------------------------


class _Row:
    """The landed row a stub answers with — the fields the step reads.

    The real ledger's ``TrialLedgerRecord`` carries all of these (§8's ten
    columns), so the stub answers with the same shape: the five the step
    started with, the unit, and feature 88's epoch and feature 87's
    provenance triple.
    """

    def __init__(self, **overrides: object) -> None:
        self.seq: int = 1
        self.node_id: str = NODE
        self.campaign_id: str = CAMPAIGN
        self.outcome: str = "ok"
        self.charges_budget: bool = True
        self.charge_units: float = DEFAULT_CHARGE_UNITS
        self.epoch_id: str = EPOCH
        self.evaluator_hash: str = EVALUATOR_HASH
        self.snapshot_hash: str = SNAPSHOT_HASH
        self.cost_model_hash: str = COST_MODEL_HASH
        for name, value in overrides.items():
            setattr(self, name, value)


# The stub's "answer faithfully" marker — distinct from any answer a test
# could can, including None (which a broken seam might well answer with).
_FAITHFUL = object()


class _StubLedger:
    """A ledger seam answering exactly what the test wants it to answer.

    Records the terms it was debited with (so a test can assert what crossed
    the seam), and answers with a canned ``answer`` — anything at all, to
    test the step's handling of shapes it must refuse — or, by default,
    faithfully: the ``(row, appended)`` pair the real ledger's append path
    answers with, the row echoing the terms it was handed.
    """

    def __init__(self, answer: object = _FAITHFUL) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.answer = answer

    def debit(
        self, node_id: object, campaign_id: object, outcome: object,
        charges_budget: object, charge_units: object, epoch_id: object,
        evaluator_hash: object, snapshot_hash: object,
        cost_model_hash: object,
    ) -> object:
        self.calls.append((
            node_id, campaign_id, outcome, charges_budget, charge_units,
            epoch_id, evaluator_hash, snapshot_hash, cost_model_hash,
        ))
        if self.answer is not _FAITHFUL:
            return self.answer
        return (
            _Row(
                node_id=node_id, campaign_id=campaign_id, outcome=outcome,
                charges_budget=charges_budget, charge_units=charge_units,
                epoch_id=epoch_id, evaluator_hash=evaluator_hash,
                snapshot_hash=snapshot_hash, cost_model_hash=cost_model_hash,
            ),
            True,
        )


# -- the charge -----------------------------------------------------------------


def test_the_step_name_is_the_pipelines_own_spelling() -> None:
    # §6.1's own line for step 11, so a caller naming where a charge comes
    # from and the feature's own vocabulary spell the one step.
    assert DEBIT_STEP == "debit_ledger"


def test_the_outcome_vocabulary_is_section_eights_four_in_order() -> None:
    # §8's column comment is the authority both members spell against; the
    # composition tests below run the real ledger under this vocabulary.
    assert TRIAL_OUTCOMES == ("ok", "timeout", "error", "tripwire_fail")


def test_a_charge_accepts_each_outcome_of_the_vocabulary() -> None:
    for outcome in TRIAL_OUTCOMES:
        charge = TrialCharge(
            node_id=NODE, campaign_id=CAMPAIGN, outcome=outcome,
            charges_budget=True,
            **_required(),
        )
        assert charge.outcome == outcome
        assert charge.charges_budget is True


def test_a_charge_refuses_an_outcome_outside_the_vocabulary() -> None:
    # An absent, misspelled, case-variant or non-string outcome is refused
    # naming the four — before the ledger is touched.
    for outcome in (None, "crashed", "Timeout", "OK", 1, ""):
        with pytest.raises(EvaluatorDebitError, match="outcome"):
            TrialCharge(
                node_id=NODE, campaign_id=CAMPAIGN, outcome=outcome,
                charges_budget=True,
                **_required(),
            )


def test_a_charge_reads_the_directive_off_the_carrier_records() -> None:
    # The failure path cannot re-ask the gate, so the bit is accepted from
    # the records the pipeline already holds — step 5's and step 7's.
    for carrier, expected in (
        (_gated(False), False),
        (_gated(True), True),
        (_post_cost(False), False),
        (_post_cost(True), True),
    ):
        charge = TrialCharge(
            node_id=NODE, campaign_id=CAMPAIGN, outcome="error",
            charges_budget=carrier,
            **_required(),
        )
        assert charge.charges_budget is expected


def test_a_charge_refuses_a_directive_that_is_not_the_bit_or_a_carrier() -> None:
    # The bit is supplied, never derived (feature 90): a 1, a 0, an absent
    # None and an arbitrary object that merely spells the attribute are all
    # refused.
    class _LooksLikeACarrier:
        charges_budget = False

    for directive in (1, 0, None, "true", _LooksLikeACarrier()):
        with pytest.raises(EvaluatorDebitError, match="charges_budget"):
            TrialCharge(
                node_id=NODE, campaign_id=CAMPAIGN, outcome="ok",
                charges_budget=directive,
                **_required(),
            )


def test_a_charge_refuses_an_identity_that_is_not_a_name() -> None:
    for identity in ("", "   ", None, 5, b"node"):
        with pytest.raises(EvaluatorDebitError, match="node_id"):
            TrialCharge(
                node_id=identity, campaign_id=CAMPAIGN, outcome="ok",
                charges_budget=True,
                **_required(),
            )
        with pytest.raises(EvaluatorDebitError, match="campaign_id"):
            TrialCharge(
                node_id=NODE, campaign_id=identity, outcome="ok",
                charges_budget=True,
                **_required(),
            )


def test_a_charge_is_a_frozen_fact() -> None:
    # The charge is append-only accounting's unit: superseded by new rows,
    # never edited in place.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        charge.outcome = "error"  # type: ignore[misc]


# -- features 87-89: the terms the ledger requires and the evaluator supplies -----


def test_the_provenance_length_matches_the_evaluators_own_hash_width() -> None:
    # §8's three provenance columns are CHAR(64) and feature 70's evaluator
    # hash is the first of them, so the one width this module validates
    # against is the width the evaluator member already coins.
    from evaluator import EVALUATOR_HASH_LENGTH

    assert PROVENANCE_HASH_LENGTH == EVALUATOR_HASH_LENGTH == 64


def test_a_charge_carries_the_epoch_and_the_provenance_triple() -> None:
    # The defect's own terms: the charge names the sequestered epoch it is
    # booked against (feature 88) and the evaluator, snapshot and cost
    # model that produced it (feature 87) — and folds an uppercase spelling
    # to the lowercase hex the columns hold.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH.upper(),
        snapshot_hash=SNAPSHOT_HASH.upper(),
        cost_model_hash=COST_MODEL_HASH.upper(),
    )
    assert charge.epoch_id == EPOCH
    assert charge.evaluator_hash == EVALUATOR_HASH
    assert charge.snapshot_hash == SNAPSHOT_HASH
    assert charge.cost_model_hash == COST_MODEL_HASH
    # The unit defaults to §8's own 1.0 for an ordinary evaluation.
    assert charge.charge_units == DEFAULT_CHARGE_UNITS


def test_a_charge_refuses_an_absent_epoch_or_provenance_term() -> None:
    # The ledger's columns are NOT NULL and its write refuses an absent
    # term with required=True; the refusal lives *here* too, so a charge
    # missing a term never reaches the seam and spends no sequence number
    # (the defect was exactly that the seam was reached with four terms).
    # Both the explicit None and the omitted term are refused by this
    # member's own error, naming the field — never Python's arity
    # TypeError, which would name no term at all.
    for field in ("epoch_id", "evaluator_hash", "snapshot_hash",
                  "cost_model_hash"):
        stated_none = _required()
        stated_none[field] = None
        with pytest.raises(EvaluatorDebitError, match=field):
            TrialCharge(
                node_id=NODE, campaign_id=CAMPAIGN, outcome="ok",
                charges_budget=True, **stated_none,
            )
        omitted = _required()
        del omitted[field]
        with pytest.raises(EvaluatorDebitError, match=field):
            TrialCharge(
                node_id=NODE, campaign_id=CAMPAIGN, outcome="ok",
                charges_budget=True, **omitted,
            )


def test_a_charge_refuses_a_blank_epoch_and_a_malformed_hash() -> None:
    # A name that names no epoch, and a provenance term that is not the
    # sha256 hexdigest's own spelling — a short hash, a non-hex token or a
    # sha256:-prefixed image reference — are refused, each naming the term
    # that moved.
    blank_epoch = _required()
    blank_epoch["epoch_id"] = "   "
    with pytest.raises(EvaluatorDebitError, match="epoch_id"):
        TrialCharge(
            node_id=NODE, campaign_id=CAMPAIGN, outcome="ok",
            charges_budget=True, **blank_epoch,
        )
    for bad in ("deadbeef", "z" * 64, "sha256:" + EVALUATOR_HASH):
        malformed = _required()
        malformed["evaluator_hash"] = bad
        with pytest.raises(EvaluatorDebitError, match="evaluator_hash"):
            TrialCharge(
                node_id=NODE, campaign_id=CAMPAIGN, outcome="ok",
                charges_budget=True, **malformed,
            )


def test_a_charge_refuses_a_unit_that_is_not_a_positive_finite_real() -> None:
    # §8's charge_units is REAL NOT NULL DEFAULT 1.0; a NaN would land as
    # NULL on a row this append-only ledger cannot correct, an infinity
    # would poison every later sum, and zero is the spelling of "free".
    for units in (0, -1, 0.0, float("nan"), float("inf"), True, "1", None):
        with pytest.raises(EvaluatorDebitError, match="charge_units"):
            TrialCharge(
                node_id=NODE, campaign_id=CAMPAIGN, outcome="ok",
                charges_budget=True, **_required(), charge_units=units,
            )


def test_a_charge_states_a_cross_validated_unit() -> None:
    # A cross-validated evaluation whose folds each compare a fit states
    # the folds' count instead of the ordinary 1.0.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(), charge_units=5,
    )
    assert charge.charge_units == 5.0
    assert isinstance(charge.charge_units, float)


def test_charge_failure_carries_the_epoch_and_provenance() -> None:
    # The failure path names the same row as the completed path: a failed
    # evaluation still charged an epoch against a snapshot under a cost
    # model, and the charge says so.
    charge = charge_failure(
        NODE, CAMPAIGN, SandboxResult(fail_class="timeout"),
        charges_budget=True, **_required(),
    )
    assert charge.epoch_id == EPOCH
    assert charge.evaluator_hash == EVALUATOR_HASH
    assert charge.snapshot_hash == SNAPSHOT_HASH
    assert charge.cost_model_hash == COST_MODEL_HASH


def test_the_landed_record_must_carry_the_epoch_and_provenance() -> None:
    # A seam whose landed row omits a required term is refused naming the
    # field — the read-back defence applied to §8's newer columns too.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )

    class _NoEpoch:
        seq = 1
        node_id = NODE
        campaign_id = CAMPAIGN
        outcome = "ok"
        charges_budget = True
        charge_units = DEFAULT_CHARGE_UNITS
        evaluator_hash = EVALUATOR_HASH
        snapshot_hash = SNAPSHOT_HASH
        cost_model_hash = COST_MODEL_HASH

    with pytest.raises(EvaluatorDebitError, match="epoch_id"):
        debit_trial(charge, _StubLedger(answer=(_NoEpoch(), True)))


def test_an_appended_row_may_not_disagree_on_the_epoch_or_provenance() -> None:
    # The appended-row check covers §8's newer columns: a seam that writes
    # a different epoch or a different provenance than it was handed did
    # not write what it was asked to.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    with pytest.raises(EvaluatorDebitError, match="disagrees"):
        debit_trial(
            charge, _StubLedger(answer=(_Row(epoch_id="epoch-9999"), True))
        )
    with pytest.raises(EvaluatorDebitError, match="disagrees"):
        debit_trial(
            charge,
            _StubLedger(answer=(_Row(evaluator_hash="00" * 32), True)),
        )


# -- the failure classification --------------------------------------------------


def test_a_sandbox_hard_kill_is_a_timeout() -> None:
    # §8's own split: the wall-clock watchdog's kill is the one failure
    # class that is its own outcome.
    assert failure_outcome(SandboxResult(fail_class="timeout")) == "timeout"
    assert failure_outcome("timeout") == "timeout"


def test_every_other_recorded_fail_class_is_an_error() -> None:
    for fail_class in ("oom", "crash", "violation", "payload", "empty"):
        assert failure_outcome(SandboxResult(fail_class=fail_class)) == "error"
        assert failure_outcome(fail_class) == "error"


def test_a_contract_refusal_is_an_error() -> None:
    # The signal ran, returned, and the contract refused the return:
    # problems without a fail class, §8's "failed any other way".
    refused = SandboxResult(problems=["wrong length"])
    assert failure_outcome(refused) == "error"


def test_a_raised_failure_is_an_error_even_a_timeout_error() -> None:
    # The sandbox records its kills as values, never exceptions, so a
    # timeout that arrives raised is a host-side failure wearing a familiar
    # name.
    assert failure_outcome(TimeoutError("step never returned")) == "error"
    assert failure_outcome(ValueError("bad window")) == "error"


def test_a_conforming_run_is_not_a_failure() -> None:
    # A completed run's outcome is 'ok', stated by the caller that watched
    # it complete — classifying it from a failure it did not have would
    # understate a successful evaluation as a failed one.
    with pytest.raises(EvaluatorDebitError, match="not a failure"):
        failure_outcome(SandboxResult())


def test_an_unknown_fail_class_is_refused_not_folded() -> None:
    # A drifted vocabulary must not become a fabricated fifth outcome.
    with pytest.raises(EvaluatorDebitError, match="not a failure class"):
        failure_outcome("segfault")
    with pytest.raises(EvaluatorDebitError, match="not a failure class"):
        failure_outcome(SandboxResult(fail_class="segfault"))


def test_an_unrecognized_failure_shape_is_refused() -> None:
    for shape in (42, None, {"fail_class": "timeout"}):
        with pytest.raises(EvaluatorDebitError, match="classifies"):
            failure_outcome(shape)


# -- the failure path's spelling -------------------------------------------------


def test_charge_failure_builds_the_failed_evaluations_charge() -> None:
    # Feature 84's sentence as one call: the failure is classified, the
    # directive is the caller's statement (the conservative True when the
    # gate never answered), and the charge comes back unpersisted.
    charge = charge_failure(
        NODE, CAMPAIGN, SandboxResult(fail_class="oom"), charges_budget=True,
        **_required(),
    )
    assert isinstance(charge, TrialCharge)
    assert charge.outcome == "error"
    assert charge.charges_budget is True
    assert charge.node_id == NODE
    assert charge.campaign_id == CAMPAIGN


def test_charge_failure_reads_the_directive_off_a_surviving_record() -> None:
    # A failure after the gate answered (step 6 raised, say) still has the
    # record to read the bit from.
    charge = charge_failure(
        NODE, CAMPAIGN, RuntimeError("purge failed"),
        charges_budget=_gated(False),
        **_required(),
    )
    assert charge.outcome == "error"
    assert charge.charges_budget is False


# -- the debit, against a stub seam ----------------------------------------------


def test_the_debit_hands_the_seam_the_charges_own_terms() -> None:
    ledger = _StubLedger()
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=False,
        **_required(),
    )
    debited = debit_trial(charge, ledger)
    # The seam was called positionally with the whole §8 row: the four
    # terms the evaluator's own compute produces, the unit, and the epoch
    # and provenance the ledger requires (features 87-89).
    assert ledger.calls == [
        (NODE, CAMPAIGN, "ok", False, DEFAULT_CHARGE_UNITS, EPOCH,
         EVALUATOR_HASH, SNAPSHOT_HASH, COST_MODEL_HASH)
    ]
    assert debited.appended is True
    assert debited.seq == 1
    assert debited.charge.node_id == NODE
    assert debited.charge.outcome == "ok"
    assert debited.charge.charges_budget is False
    assert debited.charge.epoch_id == EPOCH
    assert debited.charge.evaluator_hash == EVALUATOR_HASH


def test_a_failed_evaluation_is_charged_with_its_failure_outcome() -> None:
    # The feature's own sentence, end to end at the seam: a sandbox timeout
    # consumed a hypothesis, so its charge crosses the seam carrying the
    # timeout — and the debit answers with the row that holds it.
    ledger = _StubLedger(answer=(_Row(outcome="timeout"), True))
    charge = charge_failure(
        NODE, CAMPAIGN, SandboxResult(fail_class="timeout"),
        charges_budget=True,
        **_required(),
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is True
    assert debited.charge.outcome == "timeout"
    assert ledger.calls == [
        (NODE, CAMPAIGN, "timeout", True, DEFAULT_CHARGE_UNITS, EPOCH,
         EVALUATOR_HASH, SNAPSHOT_HASH, COST_MODEL_HASH)
    ]


def test_a_retry_is_answered_by_the_prior_row_not_refused() -> None:
    # §14: the spot-reclaimed worker retries, the debit is idempotent by
    # node, and the prior row stands exactly as first written — the retry's
    # own terms are the losers, and the disagreement is visible, not raised.
    prior = _Row(seq=7, outcome="timeout", charges_budget=True)
    ledger = _StubLedger(answer=(prior, False))
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is False
    assert debited.seq == 7
    assert debited.charge.outcome == "timeout"
    assert debited.charge.charges_budget is True


def test_the_seam_must_answer_the_two_part_shape() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    for answer in (_Row(), (_Row(), True, "extra"), None, _Row):
        with pytest.raises(EvaluatorDebitError, match="\\(record, appended\\)"):
            debit_trial(charge, _StubLedger(answer=answer))


def test_the_appended_flag_must_be_a_genuine_bool() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    with pytest.raises(EvaluatorDebitError, match="appended"):
        debit_trial(charge, _StubLedger(answer=(_Row(), 1)))


def test_the_sequence_must_be_one_a_ledger_could_assign() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    for seq in (0, -1, True, "1", 1.0):
        with pytest.raises(EvaluatorDebitError, match="seq"):
            debit_trial(charge, _StubLedger(answer=(_Row(seq=seq), True)))


def test_the_landed_record_must_carry_the_five_fields() -> None:
    # A seam that did not answer the question it was asked is refused
    # naming the field it is missing.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )

    class _NoNodeId:
        seq = 1
        campaign_id = CAMPAIGN
        outcome = "ok"
        charges_budget = True

    with pytest.raises(EvaluatorDebitError, match="node_id"):
        debit_trial(charge, _StubLedger(answer=(_NoNodeId(), True)))


def test_the_landed_row_is_rebuilt_through_the_charge_constructor() -> None:
    # Read back, not trusted: an answer whose outcome has drifted outside
    # the vocabulary or whose directive is not a bit is refused here rather
    # than laundered into the charge the caller believes.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    with pytest.raises(EvaluatorDebitError, match="outcome"):
        debit_trial(charge, _StubLedger(answer=(_Row(outcome="crashed"), True)))
    with pytest.raises(EvaluatorDebitError, match="charges_budget"):
        debit_trial(charge, _StubLedger(answer=(_Row(charges_budget=1), True)))


def test_an_answer_for_another_node_is_refused() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    other = "99999999-9999-9999-9999-999999999999"
    with pytest.raises(EvaluatorDebitError, match="another"):
        # match text: "...cannot be answered by another's row..."
        debit_trial(charge, _StubLedger(answer=(_Row(node_id=other), True)))


def test_an_appended_row_may_not_disagree_with_the_charge() -> None:
    # An append is written from this call's own terms, so a disagreement is
    # a seam that did not write what it was handed.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=False,
        **_required(),
    )
    with pytest.raises(EvaluatorDebitError, match="disagrees"):
        debit_trial(
            charge, _StubLedger(answer=(_Row(charges_budget=True), True))
        )
    with pytest.raises(EvaluatorDebitError, match="disagrees"):
        debit_trial(charge, _StubLedger(answer=(_Row(outcome="error"), True)))


def test_a_disagreement_on_a_retry_is_not_a_refusal() -> None:
    # The mirror of the test above: the same disagreement with appended
    # False is the prior row standing as first written.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=False,
        **_required(),
    )
    debited = debit_trial(
        charge, _StubLedger(answer=(_Row(charges_budget=True), False))
    )
    assert debited.appended is False
    assert debited.charge.charges_budget is True


def test_a_non_charge_is_refused() -> None:
    # The charge's terms are validated where they are stated; a debit of
    # anything else would bypass that validation.
    with pytest.raises(EvaluatorDebitError, match="TrialCharge"):
        debit_trial((NODE, CAMPAIGN, "ok", True), _StubLedger())  # type: ignore[arg-type]


def test_a_ledger_without_a_callable_debit_is_refused() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    for ledger in (object(), None, {"debit": "not callable"}):
        with pytest.raises(EvaluatorDebitError, match="debit"):
            debit_trial(charge, ledger)


def test_the_seams_own_failures_propagate_unwrapped() -> None:
    # A store error is the ledger's to report — the same stance the oracle
    # and cost-schedule seams take.
    class _Broken:
        def debit(self, *args: object) -> object:
            raise RuntimeError("store unreachable")

    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    with pytest.raises(RuntimeError, match="store unreachable"):
        debit_trial(charge, _Broken())


def test_a_debited_trial_is_validated_where_it_is_stated() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    with pytest.raises(EvaluatorDebitError, match="TrialCharge"):
        DebitedTrial(charge="ok", seq=1, appended=True)  # type: ignore[arg-type]
    with pytest.raises(EvaluatorDebitError, match="seq"):
        DebitedTrial(charge=charge, seq=0, appended=True)
    with pytest.raises(EvaluatorDebitError, match="appended"):
        DebitedTrial(charge=charge, seq=1, appended=1)  # type: ignore[arg-type]


# -- the composition: the real ledger under this debit ---------------------------


def _real_ledger():  # type: ignore[no-untyped-def]
    # Importable only under the workspace's all-packages environment; the
    # member itself imports no sibling, and neither does this check cross
    # into its source — the composition is the test's to perform.
    from ledger import TrialLedger

    return TrialLedger(os.environ["DATABASE_URL"])


def test_the_real_ledger_satisfies_the_seam_with_no_adapter() -> None:
    # The regression this bug is about: the real TrialLedger's debit
    # requires epoch_id and the provenance triple (required=True), so a
    # four-term debit was refused outright. The charge now carries the
    # whole §8 row and the call lands it, no adapter between.
    ledger = _real_ledger()
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is True
    assert debited.seq >= 1
    assert debited.charge.outcome == "ok"
    assert ledger.count() == 1
    # Every required term is on the landed row, read back from the table.
    row = ledger.rows()[0]
    assert row.epoch_id == EPOCH
    assert row.evaluator_hash == EVALUATOR_HASH
    assert row.snapshot_hash == SNAPSHOT_HASH
    assert row.cost_model_hash == COST_MODEL_HASH
    assert row.charge_units == DEFAULT_CHARGE_UNITS
    assert row.ts.tzinfo is not None


def test_a_failed_evaluation_lands_its_failure_outcome_in_the_real_ledger() -> None:
    # The feature sentence against the real table: the evaluation timed
    # out, the hypothesis was consumed anyway, and the row that lands says
    # so — classifiable by every later 'how did the trials end?' read.
    ledger = _real_ledger()
    charge = charge_failure(
        NODE, CAMPAIGN, SandboxResult(fail_class="timeout"),
        charges_budget=True,
        **_required(),
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is True
    rows = ledger.rows()
    assert len(rows) == 1
    assert rows[0].outcome == "timeout"
    assert rows[0].node_id == NODE
    assert rows[0].campaign_id == CAMPAIGN
    assert rows[0].charges_budget is True
    assert rows[0].seq == debited.seq
    # The failure path names the same row as the completed path: the epoch
    # and the provenance triple survive the failure (features 87-88).
    assert rows[0].epoch_id == EPOCH
    assert rows[0].evaluator_hash == EVALUATOR_HASH


def test_a_cross_validated_unit_lands_in_the_real_ledger() -> None:
    # The unit is supplied, not defaulted, when the trial cost more than an
    # ordinary one — and the ledger stores the real (feature 89).
    ledger = _real_ledger()
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(), charge_units=5,
    )
    debit_trial(charge, ledger)
    assert ledger.rows()[0].charge_units == 5.0


def test_a_charge_missing_a_required_term_is_refused_by_this_member() -> None:
    # The defect was that a four-term charge was *forwarded* to a ledger
    # that refused it, so the ledger's own TrialRecordError was the error a
    # caller saw — and a ledger that *had* relaxed its columns would have
    # silently accepted the partial row. The refusal now lives here, in
    # this member's own constructor: the charge cannot be built without its
    # epoch and provenance, so there is no partial charge to forward and
    # the real ledger's state is untouched.
    ledger = _real_ledger()
    with pytest.raises(EvaluatorDebitError, match="epoch_id"):
        TrialCharge(  # type: ignore[call-arg]
            node_id=NODE, campaign_id=CAMPAIGN, outcome="ok",
            charges_budget=True,
        )
    assert ledger.count() == 0


def test_a_retry_against_the_real_ledger_writes_nothing() -> None:
    # §14's contract against the real idempotent debit: the retry is
    # answered by the first row's sequence, the table does not grow, and
    # the outcome the retry asked for is the loser.
    ledger = _real_ledger()
    charge = charge_failure(
        NODE, CAMPAIGN, SandboxResult(fail_class="crash"), charges_budget=True,
        **_required(),
    )
    first = debit_trial(charge, ledger)
    retried = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True,
        **_required(),
    )
    second = debit_trial(retried, ledger)
    assert second.appended is False
    assert second.seq == first.seq
    assert second.charge.outcome == "error"
    assert ledger.count() == 1


def test_a_uuid_spelling_is_compared_by_the_identity_it_names() -> None:
    # The ledger canonicalises UUID spellings at its write, so an uppercase
    # spelling lands lowercase — and the node-identity check reads the two
    # as the same node rather than refusing the debit over the text.
    ledger = _real_ledger()
    charge = TrialCharge(
        node_id=NODE.upper(), campaign_id=CAMPAIGN.upper(), outcome="ok",
        charges_budget=True,
        **_required(),
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is True
    assert debited.charge.node_id == NODE
    assert debited.charge.campaign_id == CAMPAIGN
