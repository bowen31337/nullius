"""Feature 6, the charge — one node's debit, reached from a live run.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 6:
*System persists one evaluated node's debit to the trial ledger with
orchestrator._charge.charge_node(node_id, campaign_id, *, outcome,
charges_budget, epoch_id, evaluator_hash, snapshot_hash, cost_model_hash,
ledger), and it answers the evaluator's DebitedTrial.*  The member is
wiring over Z0 — the evaluator owns the charge's vocabulary and the
ledger owns the row — so every test here runs the *real* seam end to
end: a :class:`ledger.TrialLedger` over a throwaway SQLite database
(the spec's own sentence), charged through the two spellings, read back
row by row.  No adapter is built and no fake answers for the ledger,
because the feature's whole claim is that the evaluator's charge and
the ledger member's debit already speak to each other and the
orchestrator only has to arrive with the terms.

One test per claim the feature sentence makes:

* **the answer** — :func:`charge_node` answers the evaluator's
  :class:`~evaluator.DebitedTrial`, this call appended the row, and the
  landed row carries all nine terms: the two identities, the outcome,
  the directive, the unit at §8's default ``1.0``, the epoch and the
  provenance triple.  Read off ``ledger.rows()``, not off the answer, so
  the claim is about what the ledger holds.

* **the nine terms, in the evaluator's order** — a recording seam
  delegating to the real ledger captures the one ``debit`` call's
  positional terms and holds them against the order the evaluator's own
  debit sends (``charge_units`` fifth, between the directive and the
  epoch) — the order the debit-seam bug fixed, pinned here so a
  reordering cannot drift silently through wiring that never names it.

* **idempotent by node, both spellings** — a second
  :func:`charge_node` for a node already charged answers the ledger's
  existing record (``appended`` ``False``, the prior sequence, the
  landed terms standing as first written) and the table does not grow;
  and the §14 story across the two spellings — a worker whose run
  failed and charged ``'timeout'``, retried to completion — still holds
  one row saying ``'timeout'``.

* **the failure path** — :func:`charge_failed_node` charges the outcome
  the evaluator classifies from the failure itself (a ``timeout``
  :class:`~evaluator.SandboxResult` as ``'timeout'``, a raised exception
  as ``'error'``) with the same remaining terms, so a failed node's row
  is as auditable as a completed one's.

* **the directive, verbatim** — ``False`` lands ``False`` and ``True``
  lands ``True``: the bit the oracle answered is forwarded, never
  recomputed, and the null direction (a ``False`` "corrected" to
  ``True``) is the inflation of ``K_effective`` this member must never
  commit.

* **refusals are the evaluator's, and spend nothing** — an outcome
  outside §8's four and a truncated provenance hash are refused with the
  evaluator's own :class:`~evaluator.EvaluatorDebitError`, untranslated
  (this module defines no error), before the ledger is touched: the
  throwaway database holds no row after either.

* **the module's surface** — ``__all__`` names exactly the feature's
  two spellings, which feature 8 re-exports from the package.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.  Each test takes a fresh SQLite
file (never ``sqlite://`` in-memory: an in-memory database is
per-connection, so an idempotency assertion would pass or fail on
connection pooling rather than on the store).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evaluator import (
    DEFAULT_CHARGE_UNITS,
    DebitedTrial,
    EvaluatorDebitError,
    SandboxResult,
)
from ledger import TrialLedger
from orchestrator._charge import charge_failed_node, charge_node

#: The evaluated node, in the UUID spelling the tree store's rows carry.
#: Version and variant nibbles are well-formed so the ledger's
#: canonicalisation is a no-op and the assertions read the identity as
#: stated.
NODE = "11111111-2222-4333-8444-555555555555"

#: A second node, for the tests that charge two evaluations on one
#: ledger and read both rows back.
OTHER_NODE = "99999999-8888-4777-8666-555555555555"

#: The campaign both nodes belong to.
CAMPAIGN = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: The sequestered epoch the charges are booked against (feature 88) —
#: the holdout's own spelling, an opaque name this module never coins.
EPOCH = "epoch-2026-10-05-a"

#: The provenance triple (feature 87), three distinct well-formed sha256
#: spellings so a term landing in the wrong column cannot pass.
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH = "cd" * 32
COST_MODEL_HASH = "ef" * 32


@pytest.fixture
def ledger(tmp_path: Path) -> TrialLedger:
    """The real trial ledger over a throwaway SQLite database.

    The spec's own sentence — *tests use a TrialLedger over a throwaway
    SQLite database* — taken literally: the ledger member's store, bound
    to a per-test file under the pytest temporary directory, creating
    its schema on first use.  A file rather than an in-memory database
    because the store opens one connection per operation, and a row
    written over one in-memory connection is invisible to the next — the
    idempotency assertions would then test pooling, not the store.
    """
    return TrialLedger(f"sqlite:///{tmp_path / 'charge-test.db'}")


class _RecordingLedger:
    """A seam that records the terms it was handed, then delegates.

    The evaluator's debit read-back rebuilds the landed row through the
    charge's constructor, so a fake answering a hand-built record would
    only be testing the fake.  Delegating to the real ledger answers
    exactly what a charge expects, and the recorded tuple reads the
    terms as they crossed the seam — the one place the positional order
    is visible.
    """

    def __init__(self, real: TrialLedger) -> None:
        self._real = real
        self.calls: list[tuple[object, ...]] = []

    def debit(self, *terms: object) -> object:
        self.calls.append(terms)
        return self._real.debit(*terms)


def test_charge_node_lands_one_row_with_all_nine_terms(
    ledger: TrialLedger,
) -> None:
    # The feature sentence's whole claim, read off the table: the answer
    # is the evaluator's DebitedTrial, this call appended, and the one
    # row the ledger holds names all nine terms — the eighth and ninth
    # (the unit, at the evaluator's own §8 default) included, because a
    # charge that arrived without them is the four-term charge the
    # debit-seam bug was about.
    debited = charge_node(
        NODE,
        CAMPAIGN,
        outcome="ok",
        charges_budget=True,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    assert isinstance(debited, DebitedTrial)
    assert debited.appended is True
    assert debited.seq >= 1
    assert ledger.count() == 1

    row = ledger.rows()[0]
    assert row.node_id == NODE
    assert row.campaign_id == CAMPAIGN
    assert row.outcome == "ok"
    assert row.charges_budget is True
    assert row.charge_units == DEFAULT_CHARGE_UNITS
    assert row.charge_units == 1.0
    assert row.epoch_id == EPOCH
    assert row.evaluator_hash == EVALUATOR_HASH
    assert row.snapshot_hash == SNAPSHOT_HASH
    assert row.cost_model_hash == COST_MODEL_HASH
    assert row.seq == debited.seq


def test_the_nine_terms_cross_the_seam_in_the_evaluator_s_order(
    ledger: TrialLedger,
) -> None:
    # The charge is built with all nine terms and forwarded as one
    # positional call, in the evaluator's own order — node, campaign,
    # outcome, directive, *unit*, epoch, then the triple — the order the
    # debit seam fixed.  Wiring that only forwarded what it happened to
    # name could reorder terms the ledger validates positionally, so the
    # one call is captured and held against the exact tuple.
    seam = _RecordingLedger(ledger)
    charge_node(
        NODE,
        CAMPAIGN,
        outcome="ok",
        charges_budget=False,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=seam,
    )
    assert seam.calls == [
        (
            NODE,
            CAMPAIGN,
            "ok",
            False,
            DEFAULT_CHARGE_UNITS,
            EPOCH,
            EVALUATOR_HASH,
            SNAPSHOT_HASH,
            COST_MODEL_HASH,
        )
    ]


def test_a_second_charge_answers_the_ledger_s_existing_record(
    ledger: TrialLedger,
) -> None:
    # Idempotent by node, and the idempotency is *answered*, not
    # enforced here: the second call — deliberately carrying different
    # terms, a retry that ended differently with a different directive —
    # is answered by the first row (same sequence, appended False, the
    # landed terms standing exactly as first written) and the table does
    # not grow.  The retry's terms are the losers, which is the §14
    # contract working, not a fault to raise through.
    first = charge_node(
        NODE,
        CAMPAIGN,
        outcome="ok",
        charges_budget=True,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    second = charge_node(
        NODE,
        CAMPAIGN,
        outcome="error",
        charges_budget=False,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    assert second.appended is False
    assert second.seq == first.seq
    assert second.charge.outcome == "ok"
    assert second.charge.charges_budget is True
    assert ledger.count() == 1
    assert ledger.rows()[0].outcome == "ok"


def test_a_failed_charge_then_a_completed_charge_is_still_one_row(
    ledger: TrialLedger,
) -> None:
    # §14's story across the two spellings: the worker's run timed out
    # and charged 'timeout', the spot-reclaimed retry completed 'ok' —
    # and the node holds one row saying 'timeout', because one
    # evaluation consumed one hypothesis however many attempts it took.
    failed = charge_failed_node(
        NODE,
        CAMPAIGN,
        SandboxResult(fail_class="timeout"),
        charges_budget=True,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    retried = charge_node(
        NODE,
        CAMPAIGN,
        outcome="ok",
        charges_budget=True,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    assert failed.appended is True
    assert retried.appended is False
    assert retried.seq == failed.seq
    assert retried.charge.outcome == "timeout"
    assert ledger.count() == 1


def test_charge_failed_node_lands_the_classified_failure_outcome(
    ledger: TrialLedger,
) -> None:
    # The failure path charges the outcome the *evaluator* classifies —
    # a timeout SandboxResult as 'timeout', a raised exception as
    # 'error' — with the same remaining terms as the completed path, so
    # the failed node's row is as auditable as a completed one's: the
    # failure did not unmake the epoch, the triple or the unit.
    timed_out = charge_failed_node(
        NODE,
        CAMPAIGN,
        SandboxResult(fail_class="timeout"),
        charges_budget=True,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    raised = charge_failed_node(
        OTHER_NODE,
        CAMPAIGN,
        RuntimeError("the signal raised"),
        charges_budget=True,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    assert timed_out.appended is True
    assert raised.appended is True
    assert ledger.count() == 2
    outcomes = {row.node_id: row.outcome for row in ledger.rows()}
    assert outcomes[NODE] == "timeout"
    assert outcomes[OTHER_NODE] == "error"
    for row in ledger.rows():
        assert row.charges_budget is True
        assert row.charge_units == DEFAULT_CHARGE_UNITS
        assert row.epoch_id == EPOCH
        assert row.evaluator_hash == EVALUATOR_HASH
        assert row.snapshot_hash == SNAPSHOT_HASH
        assert row.cost_model_hash == COST_MODEL_HASH


def test_the_directive_lands_exactly_as_the_oracle_answered_it(
    ledger: TrialLedger,
) -> None:
    # "Passed exactly as the oracle answered it, and never recomputed":
    # both bits land as they were answered, read off the rows.  The
    # null direction is the one that matters — a False directive
    # "corrected" to True is a null node inflating the K_effective the
    # ledger derives from this column, the one error direction that
    # lets a false discovery through.
    charge_node(
        NODE,
        CAMPAIGN,
        outcome="ok",
        charges_budget=False,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    charge_node(
        OTHER_NODE,
        CAMPAIGN,
        outcome="ok",
        charges_budget=True,
        epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ledger=ledger,
    )
    directives = {row.node_id: row.charges_budget for row in ledger.rows()}
    assert directives[NODE] is False
    assert directives[OTHER_NODE] is True


def test_a_refused_charge_is_the_evaluator_s_own_and_spends_no_row(
    ledger: TrialLedger,
) -> None:
    # This module defines no error: a charge the evaluator refuses
    # surfaces as the evaluator's own EvaluatorDebitError, untranslated
    # — an outcome outside §8's four, a truncated provenance hash — and
    # the refusal happens before the seam is touched, so the ledger
    # holds no row and no sequence number was spent on either attempt.
    with pytest.raises(EvaluatorDebitError, match="outcome"):
        charge_node(
            NODE,
            CAMPAIGN,
            outcome="crashed",
            charges_budget=True,
            epoch_id=EPOCH,
            evaluator_hash=EVALUATOR_HASH,
            snapshot_hash=SNAPSHOT_HASH,
            cost_model_hash=COST_MODEL_HASH,
            ledger=ledger,
        )
    with pytest.raises(EvaluatorDebitError, match="evaluator_hash"):
        charge_node(
            NODE,
            CAMPAIGN,
            outcome="ok",
            charges_budget=True,
            epoch_id=EPOCH,
            evaluator_hash="ab" * 16,
            snapshot_hash=SNAPSHOT_HASH,
            cost_model_hash=COST_MODEL_HASH,
            ledger=ledger,
        )
    with pytest.raises(EvaluatorDebitError, match="failure"):
        charge_failed_node(
            NODE,
            CAMPAIGN,
            "kaput",
            charges_budget=True,
            epoch_id=EPOCH,
            evaluator_hash=EVALUATOR_HASH,
            snapshot_hash=SNAPSHOT_HASH,
            cost_model_hash=COST_MODEL_HASH,
            ledger=ledger,
        )
    assert ledger.count() == 0
    assert ledger.rows() == ()


def test_the_module_exports_exactly_its_two_names() -> None:
    # The private module's surface is the feature's two spellings and
    # nothing else — the names feature 8 re-exports from the package —
    # so a caller reaching for orchestrator._charge finds exactly the
    # charge and no accidental neighbours.
    from orchestrator import _charge

    assert set(_charge.__all__) == {"charge_node", "charge_failed_node"}
    assert callable(_charge.charge_node)
    assert callable(_charge.charge_failed_node)
