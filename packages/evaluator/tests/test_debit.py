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
  campaign_id, outcome, charges_budget)`` answering ``(record, appended)``)
  is charged, its answer read back through the charge constructor, an
  appended row held to the terms it was asked to write, and a *retry*
  answered by the prior row rather than refused — the §14 contract working;
* **the composition** — the real ``ledger.TrialLedger`` satisfies the seam
  with no adapter, a failed evaluation's charge lands its failure outcome in
  the real table, a retry writes nothing, and a UUID spelling is compared by
  the identity it names, not the text it arrived in.
"""

from __future__ import annotations

import dataclasses
import os

import pytest
from evaluator import (
    DEBIT_STEP,
    HORIZONS,
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
    """The landed row a stub answers with — the five fields the step reads."""

    def __init__(self, **overrides: object) -> None:
        self.seq: int = 1
        self.node_id: str = NODE
        self.campaign_id: str = CAMPAIGN
        self.outcome: str = "ok"
        self.charges_budget: bool = True
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
        self.calls: list[tuple[object, object, object, object]] = []
        self.answer = answer

    def debit(
        self, node_id: object, campaign_id: object, outcome: object,
        charges_budget: object,
    ) -> object:
        self.calls.append((node_id, campaign_id, outcome, charges_budget))
        if self.answer is not _FAITHFUL:
            return self.answer
        return (
            _Row(
                node_id=node_id, campaign_id=campaign_id, outcome=outcome,
                charges_budget=charges_budget,
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
            )


def test_a_charge_refuses_an_identity_that_is_not_a_name() -> None:
    for identity in ("", "   ", None, 5, b"node"):
        with pytest.raises(EvaluatorDebitError, match="node_id"):
            TrialCharge(
                node_id=identity, campaign_id=CAMPAIGN, outcome="ok",
                charges_budget=True,
            )
        with pytest.raises(EvaluatorDebitError, match="campaign_id"):
            TrialCharge(
                node_id=NODE, campaign_id=identity, outcome="ok",
                charges_budget=True,
            )


def test_a_charge_is_a_frozen_fact() -> None:
    # The charge is append-only accounting's unit: superseded by new rows,
    # never edited in place.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        charge.outcome = "error"  # type: ignore[misc]


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
        NODE, CAMPAIGN, SandboxResult(fail_class="oom"), charges_budget=True
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
    )
    assert charge.outcome == "error"
    assert charge.charges_budget is False


# -- the debit, against a stub seam ----------------------------------------------


def test_the_debit_hands_the_seam_the_charges_own_terms() -> None:
    ledger = _StubLedger()
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=False
    )
    debited = debit_trial(charge, ledger)
    # The seam was called positionally with exactly the four terms.
    assert ledger.calls == [(NODE, CAMPAIGN, "ok", False)]
    assert debited.appended is True
    assert debited.seq == 1
    assert debited.charge.node_id == NODE
    assert debited.charge.outcome == "ok"
    assert debited.charge.charges_budget is False


def test_a_failed_evaluation_is_charged_with_its_failure_outcome() -> None:
    # The feature's own sentence, end to end at the seam: a sandbox timeout
    # consumed a hypothesis, so its charge crosses the seam carrying the
    # timeout — and the debit answers with the row that holds it.
    ledger = _StubLedger(answer=(_Row(outcome="timeout"), True))
    charge = charge_failure(
        NODE, CAMPAIGN, SandboxResult(fail_class="timeout"),
        charges_budget=True,
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is True
    assert debited.charge.outcome == "timeout"
    assert ledger.calls == [(NODE, CAMPAIGN, "timeout", True)]


def test_a_retry_is_answered_by_the_prior_row_not_refused() -> None:
    # §14: the spot-reclaimed worker retries, the debit is idempotent by
    # node, and the prior row stands exactly as first written — the retry's
    # own terms are the losers, and the disagreement is visible, not raised.
    prior = _Row(seq=7, outcome="timeout", charges_budget=True)
    ledger = _StubLedger(answer=(prior, False))
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is False
    assert debited.seq == 7
    assert debited.charge.outcome == "timeout"
    assert debited.charge.charges_budget is True


def test_the_seam_must_answer_the_two_part_shape() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    for answer in (_Row(), (_Row(), True, "extra"), None, _Row):
        with pytest.raises(EvaluatorDebitError, match="\\(record, appended\\)"):
            debit_trial(charge, _StubLedger(answer=answer))


def test_the_appended_flag_must_be_a_genuine_bool() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    with pytest.raises(EvaluatorDebitError, match="appended"):
        debit_trial(charge, _StubLedger(answer=(_Row(), 1)))


def test_the_sequence_must_be_one_a_ledger_could_assign() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    for seq in (0, -1, True, "1", 1.0):
        with pytest.raises(EvaluatorDebitError, match="seq"):
            debit_trial(charge, _StubLedger(answer=(_Row(seq=seq), True)))


def test_the_landed_record_must_carry_the_five_fields() -> None:
    # A seam that did not answer the question it was asked is refused
    # naming the field it is missing.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
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
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    with pytest.raises(EvaluatorDebitError, match="outcome"):
        debit_trial(charge, _StubLedger(answer=(_Row(outcome="crashed"), True)))
    with pytest.raises(EvaluatorDebitError, match="charges_budget"):
        debit_trial(charge, _StubLedger(answer=(_Row(charges_budget=1), True)))


def test_an_answer_for_another_node_is_refused() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    other = "99999999-9999-9999-9999-999999999999"
    with pytest.raises(EvaluatorDebitError, match="another"):
        # match text: "...cannot be answered by another's row..."
        debit_trial(charge, _StubLedger(answer=(_Row(node_id=other), True)))


def test_an_appended_row_may_not_disagree_with_the_charge() -> None:
    # An append is written from this call's own terms, so a disagreement is
    # a seam that did not write what it was handed.
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=False
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
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=False
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
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
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
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    with pytest.raises(RuntimeError, match="store unreachable"):
        debit_trial(charge, _Broken())


def test_a_debited_trial_is_validated_where_it_is_stated() -> None:
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
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
    ledger = _real_ledger()
    charge = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is True
    assert debited.seq >= 1
    assert debited.charge.outcome == "ok"
    assert ledger.count() == 1


def test_a_failed_evaluation_lands_its_failure_outcome_in_the_real_ledger() -> None:
    # The feature sentence against the real table: the evaluation timed
    # out, the hypothesis was consumed anyway, and the row that lands says
    # so — classifiable by every later 'how did the trials end?' read.
    ledger = _real_ledger()
    charge = charge_failure(
        NODE, CAMPAIGN, SandboxResult(fail_class="timeout"),
        charges_budget=True,
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


def test_a_retry_against_the_real_ledger_writes_nothing() -> None:
    # §14's contract against the real idempotent debit: the retry is
    # answered by the first row's sequence, the table does not grow, and
    # the outcome the retry asked for is the loser.
    ledger = _real_ledger()
    charge = charge_failure(
        NODE, CAMPAIGN, SandboxResult(fail_class="crash"), charges_budget=True
    )
    first = debit_trial(charge, ledger)
    retried = TrialCharge(
        node_id=NODE, campaign_id=CAMPAIGN, outcome="ok", charges_budget=True
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
    )
    debited = debit_trial(charge, ledger)
    assert debited.appended is True
    assert debited.charge.node_id == NODE
    assert debited.charge.campaign_id == CAMPAIGN
