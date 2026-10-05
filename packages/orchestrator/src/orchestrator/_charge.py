"""The charge — the caller of ``evaluator.debit_trial`` a live run lacked.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 6:
*System persists one evaluated node's debit to the trial ledger with
orchestrator._charge.charge_node(node_id, campaign_id, *, outcome,
charges_budget, epoch_id, evaluator_hash, snapshot_hash, cost_model_hash,
ledger), and it answers the evaluator's DebitedTrial.*  The spec's
addition summary names the hole precisely — *"No caller of
evaluator.debit_trial exists"* — and the hole was deliberate: the
evaluator owns the charge (its vocabulary, its validation, its read-back
of the landed row) but never decides *when* a live evaluation is charged,
because before this member nothing assembled the terms a live run holds
at the moment step 11 arrives.  This module is that caller, and it is
deliberately the thinnest seam in the member: two spellings of one
forwarding — :func:`charge_node`, for an evaluation the caller watched
complete and whose outcome it therefore states, and
:func:`charge_failed_node`, for one that failed — and nothing of its own
in between.  §6.1's step 11 is the evaluator's step; the orchestrator's
part is *reaching* it from a live run, once per evaluated node, failed
ones included (the spec's own constraint: *"Every evaluated node, failed
ones included, is debited exactly once with all nine terms"*).

**The charge is the evaluator's, all nine terms of it.**  :func:`charge_node`
states the eight terms a live run holds — the two identities, the
outcome, the directive, the epoch and the provenance triple — and the
ninth, ``charge_units``, is left at the evaluator's own
:data:`~evaluator.DEFAULT_CHARGE_UNITS` (§8's ``DEFAULT 1.0``), the
sanctioned spelling for an ordinary evaluation.  That is not a term this
module forgot: a unit above one is a cross-validated evaluation's fact,
spec A's evaluations are ordinary ones, and a parameter nobody in this
member's callers could honestly fill would be a seam waiting to be
guessed through.  The tests read the landed row back and assert all nine
terms on it, so the full charge — not the historical four-term charge
the debit-seam bug found being forwarded — is what crosses.

**The failure path is a first-class spelling, and the classification is
the evaluator's.**  :func:`charge_failed_node` hands the failure itself
to :func:`evaluator.charge_failure`, which classifies it into §8's four
outcomes — a :class:`~evaluator.SandboxResult` by its recorded
``fail_class``, a raised exception as ``'error'`` — because this member
owns no failure vocabulary of its own and must not grow one: a second
spelling of "which failure is which outcome" beside the evaluator's
would drift exactly the way the debit seam did.  The remaining terms are
stated identically on both paths — the failure does not unmake the
epoch, the provenance triple or the directive — which is what makes the
failed charge as auditable as the completed one.

**The directive is forwarded, never recomputed.**  ``charges_budget`` is
§7.2's opaque bit, the one thing that crosses the sidecar barrier, and
the spec's rule is the evaluator's own (feature 90): *supplied, never
computed*.  This module passes the value — or the step-5/step-7 record
carrying it — through untouched, and holds no knowledge that could
recompute it: the orchestrator never reads a node's null status, the
sidecar key or any ``is_null`` value (the spec's standing constraint), so
null-ness reaches a charge only as the bit the null target route
answered.  The null direction is the one the tests pin — a ``False``
directive lands ``False``, because a bit "corrected" to ``True`` is a
null node inflating the ``K_effective`` the ledger derives from this
column.

**Idempotency is answered, not implemented.**  §14's contract — failures
retry; debits are idempotent by ``node_id`` — is held by the evaluator
and the ledger beneath it, and this module adds no memo of its own: a
per-process "already charged" set would be a second, weaker idempotency
that disagrees with the ledger's the moment a spot-reclaimed worker
retries on another machine.  So a second charge for the same node is
simply forwarded, and the answer is the ledger's existing record —
``appended`` ``False``, the prior sequence, the landed charge standing
exactly as first written, the retry's terms the losers the append-only
row already documents.  One node, one row, however many attempts
reached this seam.

**No error of this module's own.**  A refused charge is refused by the
evaluator — an outcome outside the four, a missing epoch or provenance
term, a miswired seam — and surfaces as the evaluator's own
:class:`~evaluator.EvaluatorDebitError`; a failed store surfaces as the
ledger member's own error, unwrapped, the same stance the evaluator
takes at the same seam.  Translating either into an orchestrator error
would hide which side of the seam refused, and the spec's export list
for this member names no charge error — the refusal vocabulary for a
charge is Z0's, called and never changed.  The one thing the forwarding
does guarantee is *when* refusals happen: the evaluator validates before
the seam is touched, so a refused charge spends no sequence number, and
the tests assert the ledger holds nothing after one.

**The ledger is the injected "ledger" component.**  An object exposing
``debit(node_id, campaign_id, outcome, charges_budget, charge_units,
epoch_id, evaluator_hash, snapshot_hash, cost_model_hash)`` answering
``(record, appended)`` — the shape the ledger member's
:class:`ledger.TrialLedger` already speaks, satisfied structurally with
no adapter, the same injection the evaluator documents for the same
seam.  This module opens no database and owns no table: the trial
ledger's rows are the ledger member's, and the orchestrator's whole
contribution to step 11 is arriving at it with a complete charge.
"""

from __future__ import annotations

from evaluator import (
    DebitedTrial,
    GatedTargets,
    PostCostReturns,
    TrialCharge,
    charge_failure,
    debit_trial,
)

__all__ = ["charge_failed_node", "charge_node"]


def charge_node(
    node_id: str,
    campaign_id: str,
    *,
    outcome: str,
    charges_budget: bool | GatedTargets | PostCostReturns,
    epoch_id: str,
    evaluator_hash: str,
    snapshot_hash: str,
    cost_model_hash: str,
    ledger: object,
) -> DebitedTrial:
    """Charge one completed evaluation — step 11 reached from a live run.

    The evaluation ran to the end and the caller watched it, so the
    outcome is *stated*, never classified: ``'ok'`` for a run whose
    pipeline completed, ``'tripwire_fail'`` when step 10's verdict is the
    outcome the caller holds.  The remaining terms are the live run's own
    facts — the directive the oracle answered at step 5 (the bit itself,
    or the :class:`~evaluator.GatedTargets` /
    :class:`~evaluator.PostCostReturns` record carrying it, forwarded
    untouched), the sequestered epoch the charge is booked against, and
    the provenance triple naming the frozen evaluator, the sealed
    snapshot and the cost model.  ``charge_units`` is deliberately not a
    parameter: an ordinary evaluation's unit is the evaluator's own
    default (§8's ``1.0``), and spec A evaluates ordinary trials.

    Builds the evaluator's :class:`~evaluator.TrialCharge` and hands it
    to :func:`evaluator.debit_trial` with the injected ``ledger``; the
    answer is the evaluator's :class:`~evaluator.DebitedTrial` — the
    landed charge, its sequence, and whether this call wrote it.  A
    second charge for the same node is answered by the ledger's existing
    record with ``appended`` ``False`` (idempotent by node, §14), and a
    charge the evaluator refuses raises its
    :class:`~evaluator.EvaluatorDebitError` before the ledger is
    touched, spending no sequence number.
    """
    charge = TrialCharge(
        node_id=node_id,
        campaign_id=campaign_id,
        outcome=outcome,
        charges_budget=charges_budget,
        epoch_id=epoch_id,
        evaluator_hash=evaluator_hash,
        snapshot_hash=snapshot_hash,
        cost_model_hash=cost_model_hash,
    )
    return debit_trial(charge, ledger)


def charge_failed_node(
    node_id: str,
    campaign_id: str,
    failure: object,
    *,
    charges_budget: bool | GatedTargets | PostCostReturns,
    epoch_id: str,
    evaluator_hash: str,
    snapshot_hash: str,
    cost_model_hash: str,
    ledger: object,
) -> DebitedTrial:
    """Charge one failed evaluation — the failure path's own spelling.

    A failed evaluation still consumed a hypothesis, so it is charged —
    with the outcome :func:`evaluator.charge_failure` classifies from the
    ``failure`` itself (a :class:`~evaluator.SandboxResult` by its
    recorded ``fail_class``, a raised exception as ``'error'``), never
    one this member invents.  The keyword terms are :func:`charge_node`'s
    own, stated for the same reasons and held to the same validation:
    the failure does not unmake the epoch, the provenance triple or the
    directive, and ``charges_budget`` is whatever the oracle answered
    before the evaluation failed — or the caller's conservative ``True``
    when it failed before the gate was asked.

    Builds the charge through :func:`evaluator.charge_failure` and hands
    it to :func:`evaluator.debit_trial`, so the answer and the
    idempotency are exactly :func:`charge_node`'s: the evaluator's
    :class:`~evaluator.DebitedTrial`, one row per node however many
    attempts failed, and the evaluator's refusal — a failure shape it
    cannot classify, a missing term — before the ledger is touched.
    """
    charge = charge_failure(
        node_id,
        campaign_id,
        failure,
        charges_budget=charges_budget,
        epoch_id=epoch_id,
        evaluator_hash=evaluator_hash,
        snapshot_hash=snapshot_hash,
        cost_model_hash=cost_model_hash,
    )
    return debit_trial(charge, ledger)
