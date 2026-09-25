"""Feature 338's act: the revised beta-four persisted per cycle.

app_spec.xml, "Forward-Test Tracking", feature 338: *System persists the
revised beta-four value per cycle, fed back from observed sim-reality
divergence.*  These tests pin the five halves of that sentence:

* **persists** — the revision lands in this member's own table, one row
  per cycle, and a hand that reaches past the store is refused at the
  read (the value layer re-derives the blend);
* **the revised beta-four value** — the figure is the blend of the
  standing value with the observed divergences at feature 228's
  pseudo-count strength, computed by the store and never a parameter,
  exact to the last bit because both sides are arithmetic this member
  performed itself;
* **per cycle** — the cycle is the key, one row each: a retry over
  unmoved evidence answers the standing row, moved evidence is refused
  naming the repair (the next cycle), and the table's own ``UNIQUE``
  holds the law against a concurrent writer;
* **fed back** — each cycle's prior is the previous cycle's revised
  figure (the chain is the loop's memory), with the zero-evidence law
  at every link: no measurable signal answers the standing value
  exactly, an empty chain answers feature 260's own ``0.5`` default;
* **from observed sim-reality divergence** — the evidence is prd §7.1's
  fourth term's own quantity, ``|IC_forward − IC_backtest|`` per
  measured signal over feature 337's operands, with feature 339's
  classification of the absences; feature 340's cost ledger is swept
  and carried beside the blend — deliberately not an addend in it.

The value laws are pinned here too: an instance whose stated figure is
not the arithmetic of its own evidence is refused, so a fabricated
coefficient cannot reach the dreaming loop's next cycle.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from types import SimpleNamespace

import forward.beta_four
import pytest
from conftest import (
    CAMPAIGN_ID,
    CRITERIA_DOCUMENT,
    DECIDED_AT,
    EPOCH_ID,
    FORWARD_DAYS,
    NODE_ID,
    REGISTERED_AT,
    code_of,
)
from forward import (
    BETA_FOUR_PRIOR,
    BETA_FOUR_WEIGHT,
    DATABASE_URL_ENV,
    FORWARD_BETA_FOUR_ERROR_CODE,
    FORWARD_BETA_FOUR_SEAM,
    FORWARD_BETA_FOUR_TABLE,
    FORWARD_IDENTITY_ERROR_CODE,
    REVISED_BETA_FOUR_KEY,
    BetaFourRevision,
    ForwardBetaFourError,
    ForwardBetaFourRevisions,
    ForwardIdentityError,
    ForwardRecord,
    ForwardRecords,
    ForwardStoreError,
    revised_beta_four,
    standing_beta_four,
)
from forward.observation import ForwardObservations
from forward.reconciliation import reconcile_fill_costs
from forward.retention import ForwardIcRetentions, ForwardRetentionError

#: The promotion boundary this suite is measured against, restated so a
#: conftest change that moved ``DECIDED_AT`` fails at the first fixture
#: rather than somewhere inside a refusal message — the same discipline the
#: observation, retention and priors suites take.
DECIDED = dt.datetime.fromisoformat(DECIDED_AT)

#: The boundary day, and the first day an observation may honestly name.
BOUNDARY_DAY = dt.date(2026, 3, 1)
FIRST_DAY = dt.date(2026, 3, 2)

#: The backtest edge every measured fixture lands.  The divergences below
#: are kept clear of every tie by margins no float representation can
#: close, so the blends asserted are decisions of the *data*.
BACKTEST = 0.2

#: Three observed days whose mean is ``0.0967`` — a signal whose live IC
#: fell well short of the backtest that promoted it, the flattering case.
DECLINE = (0.12, 0.11, 0.06)
DECLINE_MEAN = sum(DECLINE) / len(DECLINE)
DECLINE_DIVERGENCE = abs(DECLINE_MEAN - BACKTEST)

#: Two observed days of exactly the backtest figure — the vindicated case,
#: whose divergence is zero and whose only honest effect is to pull the
#: coefficient toward nothing to penalize.
VINDICATED = (0.2, 0.2)

#: Two observed days of collapse — the catastrophic case, whose divergence
#: (``1.1``) exceeds the standing value itself, the one direction that
#: *raises* the coefficient: the term it weights was nowhere near expensive
#: enough for a fleet this far from its backtests.
COLLAPSE = (-0.9, -0.9)
COLLAPSE_DIVERGENCE = abs(sum(COLLAPSE) / len(COLLAPSE) - BACKTEST)

#: A second and a third signal's identity, so the classification tests
#: hold a fleet rather than a singleton.
SECOND_NODE = "33333333-3333-4333-8333-333333333333"
THIRD_NODE = "44444444-4444-4444-8444-444444444444"
FOURTH_NODE = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def revisions(promoted_signal: ForwardRecords) -> ForwardBetaFourRevisions:
    """The revision store over the record's own store — 338's seam.

    Built with :meth:`ForwardBetaFourRevisions.over` off the very store the
    record was opened through, so the writer and the opener point at one
    database by construction — the shape a deployment reaches when it asks
    the composed ``forward`` component for the act.
    """
    return ForwardBetaFourRevisions.over(promoted_signal)


def _observe(
    store: ForwardRecords,
    node_id: str,
    coefficients: tuple[float, ...],
    *,
    first_day: dt.date = FIRST_DAY,
    backtest: float | None = BACKTEST,
) -> None:
    """Measure a signal the way the pipeline would, through 333 and 337.

    The observations land through feature 333's own act and the backtest
    figure through feature 337's, so every divergence the blend folds is a
    figure the member actually persisted — a hand-written row would pin the
    evidence against a fixture the suite made up.
    """
    observations = ForwardObservations.over(store)
    for offset, coefficient in enumerate(coefficients):
        observations.append_observation(
            node_id,
            observed_on=first_day + dt.timedelta(days=offset),
            live_ic=coefficient,
            forward_days=FORWARD_DAYS,
        )
    if backtest is not None:
        ForwardIcRetentions.over(store).record_backtest_ic(
            node_id, backtest_ic=backtest
        )


def _promote_second_signal(store: ForwardRecords, node_id: str) -> None:
    """A further signal's closed promotion in the *same* database.

    :func:`conftest.promote_signal` brings the database up as well as filing
    the row, and its ``epoch_ledger`` insert is unconditional — so a second
    call against a database that already holds the epoch collides on the
    primary key.  This helper does the part that is per-signal, with the
    same fixed instant the fixture used, so every signal shares one
    boundary and the divergences below differ only by their coefficients.
    """
    from promotion import PreRegistrations, PromotionCriteria
    from promotion.decision import PromotionDecisions

    registrations = PreRegistrations(store.database_url)
    connection = registrations._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, ?)",
                (node_id, CAMPAIGN_ID, "macro", 1),
            )
    finally:
        connection.close()
    registrations.pre_register(
        node_id,
        EPOCH_ID,
        PromotionCriteria(**CRITERIA_DOCUMENT),
        clock=lambda: dt.datetime.fromisoformat(REGISTERED_AT),
    )
    PromotionDecisions(store.database_url).record_decision(
        node_id, decided_at=DECIDED
    )


@pytest.fixture
def measured_signal(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> ForwardRecord:
    """One signal measured through its decline — the fleet's measured case."""
    assert opened_record.promoted_at == DECIDED
    assert opened_record.observed_on == BOUNDARY_DAY
    _observe(promoted_signal, NODE_ID, DECLINE)
    return opened_record


def _blend(prior: float, divergences: tuple[float, ...]) -> float:
    """The blend, spelled in the test the way the module spells it.

    One accumulation in one deterministic order, so the equality asserted
    against the store's figure is bitwise: the same adds, the same divide.
    """
    total = 0.0
    for divergence in divergences:
        total += divergence
    return (BETA_FOUR_WEIGHT * prior + total) / (BETA_FOUR_WEIGHT + len(divergences))


# -- The persistence and the blend ------------------------------------------------


def test_an_empty_chain_answers_the_default_and_persists_it(
    store: ForwardRecords,
) -> None:
    """The zero-evidence law at the chain's head, as a row that stands.

    A database holding no record at all — the youngest deployment — answers
    feature 260's own ``0.5`` for its first cycle, and *persists* it: the
    row is what makes the figure the standing value the next cycle blends
    from rather than a number a caller recomputed.  The prior is pinned to
    the scoring member's default by value, not by import: a member never
    imports a sibling, so the suite states the ``0.5`` the seam applies
    when a caller names none.
    """
    revision, created = ForwardBetaFourRevisions.over(store).revise("cycle-1")

    assert created is True
    assert revision.sequence == 1
    assert revision.cycle_id == "cycle-1"
    assert revision.prior_beta_four == BETA_FOUR_PRIOR == 0.5
    assert revision.prior_weight == BETA_FOUR_WEIGHT
    assert revision.observed_divergences == 0
    assert revision.divergence_sum == 0.0
    assert revision.revised_beta_four == 0.5
    assert revision.observed_through is None
    assert revision.unbacktested == 0
    assert revision.unobserved == 0
    assert revision.zero_backtest == 0
    assert revision.cost_reconciliations == 0
    assert revision.cost_divergence_bps == 0.0
    assert revision.revised_at.tzinfo is not None
    # And it stands: a second store over the same database — the shape a
    # reader in another process takes — answers the same row, because the
    # table is the memory and no store holds a cache.
    standing = ForwardBetaFourRevisions(store.database_url).standing()
    assert standing == revision


def test_the_blend_is_the_pseudo_count_law_over_the_observed_divergences(
    revisions: ForwardBetaFourRevisions, measured_signal: ForwardRecord
) -> None:
    """The sentence's arithmetic, exact: prior 0.5 at weight six, one
    divergence ``(6 × 0.5 + 0.1033…) / 7``.

    The equality is bitwise on purpose — both sides are the same adds and
    the same divide over the same figures, so anything but equality is a
    different arithmetic rather than a rounding artefact, and the value
    layer's own re-derivation (pinned below) would refuse the row.
    """
    revision, created = revisions.revise("cycle-1")

    assert created is True
    assert revision.observed_divergences == 1
    assert revision.divergence_sum == DECLINE_DIVERGENCE
    assert revision.revised_beta_four == _blend(BETA_FOUR_PRIOR, (DECLINE_DIVERGENCE,))
    assert revision.revised_beta_four != BETA_FOUR_PRIOR
    assert revision.observed_through == FIRST_DAY + dt.timedelta(days=len(DECLINE) - 1)


def test_severity_above_the_standing_value_raises_it_and_vindication_lowers_it(
    store: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """The feedback's two directions, and they are the evidence's own: the
    blend is a tracker that moves the coefficient toward the fleet's own
    mean observed divergence.

    A signal that collapsed a full point short of the backtest that
    promoted it is a divergence *larger than the standing value* — the
    coefficient rises, because the term it weights was nowhere near
    expensive enough for a fleet this far from its backtests.  A signal
    whose live IC *met* its backtest is a backtest the forward test
    vindicated — the divergence is zero and the blend pulls the coefficient
    toward nothing to penalize, which is *below* the default, not equal to
    it: one honest signal is already evidence that the standing penalty was
    more than the fleet needs.
    """
    _observe(store, NODE_ID, COLLAPSE)
    catastrophic, _ = ForwardBetaFourRevisions.over(store).revise("cycle-1")
    assert catastrophic.observed_divergences == 1
    assert catastrophic.divergence_sum == COLLAPSE_DIVERGENCE
    assert catastrophic.revised_beta_four > BETA_FOUR_PRIOR
    assert catastrophic.revised_beta_four == _blend(
        BETA_FOUR_PRIOR, (COLLAPSE_DIVERGENCE,)
    )

    elsewhere = SimpleNamespace(
        database_url=store.database_url.replace("forward-test.db", "vindicated.db")
    )
    other_store = ForwardRecords(elsewhere.database_url)
    other_store._connect().close()
    from conftest import promote_signal

    promote_signal(elsewhere.database_url)
    other_store.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    _observe(other_store, NODE_ID, VINDICATED)
    vindicated, _ = ForwardBetaFourRevisions.over(elsewhere).revise("cycle-1")

    assert vindicated.observed_divergences == 1
    assert vindicated.divergence_sum == 0.0
    assert vindicated.revised_beta_four < BETA_FOUR_PRIOR
    assert vindicated.revised_beta_four == (BETA_FOUR_WEIGHT * BETA_FOUR_PRIOR) / (
        BETA_FOUR_WEIGHT + 1
    )


def test_the_row_carries_its_own_evidence(
    revisions: ForwardBetaFourRevisions, measured_signal: ForwardRecord
) -> None:
    """A coefficient without its evidence is a number the next cycle cannot
    audit itself against, so the evidence travels on the row.

    The summary is the loop's read (the figure under the spec's own three
    words, the prior and the divergences beside it) and the row mapping
    names the table's own columns — the discipline every record in this
    workspace follows.
    """
    revision, _ = revisions.revise("cycle-1")

    assert revision.observed_mean_divergence == DECLINE_DIVERGENCE
    summary = revision.summary()
    assert summary[REVISED_BETA_FOUR_KEY] == revision.revised_beta_four
    assert summary["prior_beta_four"] == BETA_FOUR_PRIOR
    assert summary["observed_divergences"] == 1
    assert summary["observed_mean_divergence"] == DECLINE_DIVERGENCE
    assert summary["unbacktested_signals"] == 0
    assert summary["observed_through"] == revision.observed_through.isoformat()
    assert summary["revised_at"] == revision.revised_at.isoformat()

    row = revision.row()
    assert row["cycle_id"] == "cycle-1"
    assert row["prior_weight"] == BETA_FOUR_WEIGHT
    assert row["revised_beta_four"] == revision.revised_beta_four
    assert row["divergence_sum"] == DECLINE_DIVERGENCE


def test_the_derived_means_are_absent_over_no_evidence(
    store: ForwardRecords,
) -> None:
    """The mean divergence and the per-rebalance cost mean are derived, and
    over nothing they are absent — an honest ``None``, never a zero that
    would read as a measurement of nothing."""
    revision, _ = ForwardBetaFourRevisions.over(store).revise("cycle-1")

    assert revision.observed_mean_divergence is None
    assert revision.mean_cost_divergence_bps is None


# -- The fleet read ---------------------------------------------------------------


def test_the_classification_tallies_what_it_cannot_measure(
    store: ForwardRecords, promoted_signal: ForwardRecords
) -> None:
    """Feature 339's classification, one act earlier in the same loop: the
    revision counts the absences it cannot fold rather than refusing them.

    Four signals: one measured; one whose backtest has not landed (feature
    337's writer is a separate call, and a young deployment's outer loop
    must not block on the one figure that has not arrived); one whose
    backtest is exactly zero — observed, even, because the classification
    reads the figure and not the row count, and a signal with no measured
    edge made no claim the forward test could flatter; and one with a
    divisor the observation job has not reached.  Only the first is folded.
    """
    store.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    _observe(store, NODE_ID, DECLINE)
    for node in (SECOND_NODE, THIRD_NODE, FOURTH_NODE):
        _promote_second_signal(store, node)
        store.open_record(node, forward_days=FORWARD_DAYS)
    _observe(store, THIRD_NODE, DECLINE, backtest=0.0)  # zero-backtest
    ForwardIcRetentions.over(store).record_backtest_ic(
        FOURTH_NODE, backtest_ic=BACKTEST
    )  # unobserved

    revision, _ = ForwardBetaFourRevisions.over(store).revise("cycle-1")

    assert revision.observed_divergences == 1
    assert revision.unbacktested == 1
    assert revision.zero_backtest == 1
    assert revision.unobserved == 1
    assert revision.revised_beta_four == _blend(BETA_FOUR_PRIOR, (DECLINE_DIVERGENCE,))


def test_a_negative_backtest_refuses_the_whole_revision(
    store: ForwardRecords, promoted_signal: ForwardRecords
) -> None:
    """The contradicted-promotion refusal: promotion requires a positive
    edge (prd §11), so a negative figure on a promoted signal's record is
    a value wearing the column's name — and the aggregate refuses rather
    than filters, because a coefficient taught from a fleet it silently
    filtered is a coefficient nobody calibrated."""
    store.open_record(NODE_ID, forward_days=FORWARD_DAYS)
    _observe(store, NODE_ID, DECLINE, backtest=-0.05)

    with pytest.raises(ForwardBetaFourError) as refusal:
        ForwardBetaFourRevisions.over(store).revise("cycle-1")

    message = str(refusal.value)
    assert FORWARD_BETA_FOUR_ERROR_CODE in message
    assert NODE_ID in message
    assert "positive" in message
    # And nothing landed: the refusal is of the cycle, not of one signal.
    assert ForwardBetaFourRevisions(store.database_url).standing() is None


def test_a_record_of_two_vintages_refuses(
    store: ForwardRecords, promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """A divergence is a gap between two windows, so a record whose rows
    disagree about where one of them begins charges the coefficient for a
    vintage that never existed — the one-vintage law, restated in this
    module's own words as its siblings restate it in theirs."""
    _observe(store, NODE_ID, DECLINE)
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET promoted_at = ? WHERE observed_on != ?",
                ("2026-04-01T12:00:00+00:00", BOUNDARY_DAY.isoformat()),
            )
    finally:
        connection.close()

    with pytest.raises(ForwardBetaFourError) as refusal:
        ForwardBetaFourRevisions.over(store).revise("cycle-1")

    message = str(refusal.value)
    assert FORWARD_BETA_FOUR_ERROR_CODE in message
    assert DECIDED_AT in message
    assert "2026-04-01T12:00:00+00:00" in message


def test_a_backtest_outside_the_bounds_arrives_in_337s_vocabulary(
    store: ForwardRecords, promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """A stored ``2.5`` is not a large IC but a number that has stopped
    being one, and the one spelling of *is this a coefficient* this member
    has is feature 337's gate — so the refusal arrives in that vocabulary,
    untouched, rather than re-framed here."""
    _observe(store, NODE_ID, DECLINE)
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET backtest_ic = 2.5 WHERE observed_on = ?",
                (BOUNDARY_DAY.isoformat(),),
            )
    finally:
        connection.close()

    with pytest.raises(ForwardRetentionError):
        ForwardBetaFourRevisions.over(store).revise("cycle-1")


# -- The chain --------------------------------------------------------------------


def test_each_cycles_prior_is_the_previous_revisions_figure(
    revisions: ForwardBetaFourRevisions,
    promoted_signal: ForwardRecords,
    measured_signal: ForwardRecord,
) -> None:
    """*"Fed back"* made structural: row ``k``'s prior is row ``k−1``'s
    revised figure, so the chain is the loop's own memory and a reader can
    verify every blend from the rows alone.

    The evidence moves between the cycles (one more observed day), so the
    second blend is over a different divergence — the chain tracks the
    fleet, it does not repeat the first cycle's arithmetic.
    """
    first, _ = revisions.revise("cycle-1")
    _observe(promoted_signal, NODE_ID, (0.01,), first_day=FIRST_DAY + dt.timedelta(days=10))

    moved_mean = (sum(DECLINE) + 0.01) / (len(DECLINE) + 1)
    moved_divergence = abs(moved_mean - BACKTEST)

    second, _ = revisions.revise("cycle-2")

    assert second.sequence == 2
    assert second.prior_beta_four == first.revised_beta_four
    assert second.revised_beta_four == _blend(
        first.revised_beta_four, (moved_divergence,)
    )
    assert second.revised_beta_four < first.revised_beta_four  # honesty compounds

    chain = revisions.revisions()
    assert [row.cycle_id for row in chain] == ["cycle-1", "cycle-2"]
    assert [row.sequence for row in chain] == [1, 2]
    assert chain[1].prior_beta_four == chain[0].revised_beta_four
    assert revisions.standing() == second


def test_a_cycle_over_no_measurable_signal_answers_the_standing_value_exactly(
    store: ForwardRecords,
) -> None:
    """The zero-evidence law at every *link*, not only at the head: ``n = 0``
    makes the blend the prior, so a second cycle over a still-empty fleet
    answers the first cycle's figure — the chain does not drift, and the
    evidence has to move for the coefficient to."""
    revisions = ForwardBetaFourRevisions.over(store)
    first, _ = revisions.revise("cycle-1")
    assert first.revised_beta_four == BETA_FOUR_PRIOR

    second, created = revisions.revise("cycle-2")

    assert created is True
    assert second.sequence == 2
    assert second.prior_beta_four == first.revised_beta_four
    assert second.observed_divergences == 0
    assert second.revised_beta_four == first.revised_beta_four


def test_a_retry_over_unmoved_evidence_answers_the_standing_row(
    revisions: ForwardBetaFourRevisions, measured_signal: ForwardRecord
) -> None:
    """The worker died between the row and the response, and the worker
    that takes over revises again: the same cycle over the same evidence
    is the same revision arriving twice — answered untouched, ``created``
    ``False``, with nothing else landed."""
    first, created = revisions.revise("cycle-1")
    assert created is True

    again, created_again = revisions.revise("cycle-1")

    assert created_again is False
    assert again == first
    assert again.sequence == first.sequence
    assert again.revised_at == first.revised_at
    assert len(revisions.revisions()) == 1


def test_moved_evidence_under_a_revised_cycle_is_refused_and_the_next_cycle_takes_it(
    revisions: ForwardBetaFourRevisions,
    promoted_signal: ForwardRecords,
    measured_signal: ForwardRecord,
) -> None:
    """The one-row-per-cycle law's per-cycle face: a cycle's revision is
    that cycle's fact, once.  The dreaming loop may already have run the
    cycle on the standing figure — every ``replay_score`` row carries the β
    it ran with — so a moved-evidence re-revision is refused naming the
    repair, and the moved evidence is the *next* cycle's to fold."""
    standing, _ = revisions.revise("cycle-1")
    _observe(promoted_signal, NODE_ID, (0.01,), first_day=FIRST_DAY + dt.timedelta(days=10))

    with pytest.raises(ForwardIdentityError) as refusal:
        revisions.revise("cycle-1")

    message = str(refusal.value)
    assert FORWARD_IDENTITY_ERROR_CODE in message
    assert "cycle-1" in message
    assert repr(standing.revised_beta_four) in message
    assert "new cycle" in message  # the repair is named, not just the fault

    moved, _ = revisions.revise("cycle-2")
    assert moved.prior_beta_four == standing.revised_beta_four


def test_the_one_row_per_cycle_law_is_also_the_tables(
    revisions: ForwardBetaFourRevisions, measured_signal: ForwardRecord
) -> None:
    """The write path checks first so its refusal can name the standing
    row; the ``UNIQUE (cycle_id)`` is what holds the law against a
    concurrent writer and a hand that reaches past this store."""
    revision, _ = revisions.revise("cycle-1")
    connection = revisions._connect()
    try:
        with pytest.raises(sqlite3.IntegrityError), connection:
            connection.execute(
                f"INSERT INTO {FORWARD_BETA_FOUR_TABLE} "
                "(cycle_id, prior_beta_four, prior_weight, "
                "observed_divergences, divergence_sum, unbacktested, "
                "unobserved, zero_backtest, cost_reconciliations, "
                "cost_divergence_bps, observed_through, revised_beta_four, "
                "revised_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "cycle-1",
                    revision.prior_beta_four,
                    revision.prior_weight,
                    revision.observed_divergences,
                    revision.divergence_sum,
                    revision.unbacktested,
                    revision.unobserved,
                    revision.zero_backtest,
                    revision.cost_reconciliations,
                    revision.cost_divergence_bps,
                    revision.observed_through.isoformat(),
                    revision.revised_beta_four,
                    revision.revised_at.isoformat(),
                ),
            )
    finally:
        connection.close()

    assert len(revisions.revisions()) == 1


# -- The cost face ----------------------------------------------------------------


def test_the_cost_ledger_is_swept_and_carried_beside_the_blend(
    revisions: ForwardBetaFourRevisions,
    store: ForwardRecords,
    measured_signal: ForwardRecord,
) -> None:
    """docs §6.2 names the realized-modeled fill-cost gap *"exactly the
    quantity ``β₄`` penalizes"*, so the cycle sweeps feature 340's whole
    ledger and carries its count and its signed sum on the row.

    Carried, not blended: the IC-face blend is the same figure it was with
    an empty ledger, because no document states a conversion between a
    basis-point gap and the IC gap the term charges on — and a test that
    found the sum nudging the coefficient would have found invented
    arithmetic.
    """
    reconcile_fill_costs(
        "book-alpha",
        rebalance_ts=dt.datetime(2026, 3, 5, 12, tzinfo=dt.UTC),
        realized_cost_bps=12.5,
        modeled_cost_bps=11.0,
        database_url=store.database_url,
    )
    reconcile_fill_costs(
        "book-alpha",
        rebalance_ts=dt.datetime(2026, 3, 6, 12, tzinfo=dt.UTC),
        realized_cost_bps=10.0,
        modeled_cost_bps=10.5,
        database_url=store.database_url,
    )

    revision, _ = revisions.revise("cycle-1")

    assert revision.cost_reconciliations == 2
    # Signed, in the ledger's own order: +1.5 then -0.5, the positive face
    # (the model understating — prd's cost model optimism) surviving the
    # negative one rather than being erased by an absolute value.
    assert revision.cost_divergence_bps == 1.0
    assert revision.mean_cost_divergence_bps == 0.5
    assert revision.revised_beta_four == _blend(BETA_FOUR_PRIOR, (DECLINE_DIVERGENCE,))


# -- The value laws ---------------------------------------------------------------


def _raw_revision(**overrides: object) -> BetaFourRevision:
    """A well-formed revision, with one field overridden per refusal test.

    The blend is recomputed over the overridden evidence where the figure
    itself is not the field under test, so each refusal pinned below is a
    refusal of *one* law and not collateral from a stale figure.
    """
    fields: dict[str, object] = {
        "sequence": 1,
        "cycle_id": "cycle-1",
        "prior_beta_four": BETA_FOUR_PRIOR,
        "prior_weight": BETA_FOUR_WEIGHT,
        "observed_divergences": 1,
        "divergence_sum": DECLINE_DIVERGENCE,
        "unbacktested": 0,
        "unobserved": 0,
        "zero_backtest": 0,
        "cost_reconciliations": 0,
        "cost_divergence_bps": 0.0,
        "observed_through": FIRST_DAY + dt.timedelta(days=len(DECLINE) - 1),
        "revised_beta_four": _blend(BETA_FOUR_PRIOR, (DECLINE_DIVERGENCE,)),
        "revised_at": dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
    }
    fields.update(overrides)
    return BetaFourRevision(**fields)  # type: ignore[arg-type]


def test_a_fabricated_revised_figure_is_refused() -> None:
    """The re-derivation law: ``revised_beta_four`` must be the blend of the
    evidence stored beside it, exactly.  Both sides are arithmetic this
    member performed itself, so anything but equality is a figure that was
    never the blend — a hand that reached past the store."""
    with pytest.raises(ForwardBetaFourError) as refusal:
        _raw_revision(revised_beta_four=0.99)

    assert FORWARD_BETA_FOUR_ERROR_CODE in str(refusal.value)
    assert "0.99" in str(refusal.value)


def test_evidence_and_its_figures_cannot_disagree() -> None:
    """A sum over no addends is a measurement nobody made, a vintage over
    no evidence is a day nothing was measured on, evidence with no day
    under it is a row this store did not write, and a cost figure over no
    swept rebalance is a divergence nobody measured — four faces of one
    law, each refused rather than silently re-read."""
    with pytest.raises(ForwardBetaFourError, match="divergence_sum"):
        _raw_revision(observed_divergences=0, divergence_sum=0.1, revised_beta_four=BETA_FOUR_PRIOR, observed_through=None)
    with pytest.raises(ForwardBetaFourError, match="vintage"):
        _raw_revision(observed_divergences=0, divergence_sum=0.0, revised_beta_four=BETA_FOUR_PRIOR, observed_through=FIRST_DAY)
    with pytest.raises(ForwardBetaFourError, match="no vintage"):
        _raw_revision(observed_through=None)
    with pytest.raises(ForwardBetaFourError, match="cost divergence"):
        _raw_revision(cost_divergence_bps=1.0, revised_beta_four=_blend(BETA_FOUR_PRIOR, (DECLINE_DIVERGENCE,)))


def test_the_strength_is_not_a_dial() -> None:
    """The pseudo-count is feature 228's idiom at the strength feature 339
    holds its own prior at, enforced by equality: a row blended at any
    other strength would be a revision nobody calibrated."""
    with pytest.raises(ForwardBetaFourError) as refusal:
        _raw_revision(prior_weight=7.0)

    message = str(refusal.value)
    assert FORWARD_BETA_FOUR_ERROR_CODE in message
    assert repr(BETA_FOUR_WEIGHT) in message


def test_a_coefficient_is_a_finite_nonnegative_real() -> None:
    """The scoring member's own law, restated at the persistence layer: a
    NaN would make every downstream score a NaN the argmax silently drops,
    and a negative coefficient would counterfeit a bonus through the
    penalty seam — the inversion of prd §7.1's *honest, not merely high*."""
    with pytest.raises(ForwardBetaFourError, match="negative"):
        _raw_revision(prior_beta_four=-0.1, revised_beta_four=_blend(-0.1, (DECLINE_DIVERGENCE,)))
    with pytest.raises(ForwardBetaFourError, match="finite"):
        _raw_revision(revised_beta_four=float("nan"))
    with pytest.raises(ForwardBetaFourError, match="real number"):
        _raw_revision(revised_beta_four=True, revised_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC))


def test_counts_and_sequences_are_whole_and_minted() -> None:
    """``True`` is not a census of anything, ``1.5`` signals is a count of
    nothing the tables hold, and a sequence below 1 is a number the chain's
    ``AUTOINCREMENT`` never minted — rows this store did not write."""
    with pytest.raises(ForwardBetaFourError, match="whole count"):
        _raw_revision(observed_divergences=True, divergence_sum=0.0, revised_beta_four=BETA_FOUR_PRIOR, observed_through=None)
    with pytest.raises(ForwardBetaFourError, match="whole count"):
        _raw_revision(unbacktested=1.5)
    with pytest.raises(ForwardBetaFourError, match="numbered from 1"):
        _raw_revision(sequence=0)


def test_hand_edited_rows_are_refused_at_the_read(
    revisions: ForwardBetaFourRevisions, measured_signal: ForwardRecord
) -> None:
    """SQLite will accept anything another tool inserts, and the readers
    this table exists for (the dreaming loop's β, an operator auditing the
    chain) run later and elsewhere — so the read refuses a row no revision
    can be rebuilt as, *naming the row it came from*."""
    revision, _ = revisions.revise("cycle-1")
    connection = revisions._connect()
    try:
        with connection:
            connection.execute(
                f"UPDATE {FORWARD_BETA_FOUR_TABLE} SET revised_at = 'not-a-moment' "
                "WHERE sequence = ?",
                (revision.sequence,),
            )
    finally:
        connection.close()

    with pytest.raises(ForwardBetaFourError) as refusal:
        revisions.standing()

    message = str(refusal.value)
    assert FORWARD_BETA_FOUR_ERROR_CODE in message
    assert "not-a-moment" in message
    assert str(revision.sequence) in message


def test_a_row_lying_about_its_own_blend_is_refused_at_the_read(
    revisions: ForwardBetaFourRevisions, measured_signal: ForwardRecord
) -> None:
    """The re-derivation law runs on the read path too: a stored figure
    that disagrees with the evidence stored beside it would otherwise reach
    the dreaming loop as a coefficient nobody computed."""
    revision, _ = revisions.revise("cycle-1")
    connection = revisions._connect()
    try:
        with connection:
            connection.execute(
                f"UPDATE {FORWARD_BETA_FOUR_TABLE} SET revised_beta_four = 0.123 "
                "WHERE sequence = ?",
                (revision.sequence,),
            )
    finally:
        connection.close()

    with pytest.raises(ForwardBetaFourError) as refusal:
        revisions.revisions()

    message = str(refusal.value)
    assert FORWARD_BETA_FOUR_ERROR_CODE in message
    assert str(revision.sequence) in message
    assert "cycle-1" in message


# -- The ask ----------------------------------------------------------------------


def test_a_cycle_that_states_nothing_is_refused_before_any_database(
    store: ForwardRecords,
) -> None:
    """The cycle is the dreaming iteration the revision feeds, named by the
    outer-loop job that runs the recalibration — an id that states nothing
    names no cycle a revision could belong to, and the refusal comes
    *before* the database is touched so a refused call leaves no file
    behind."""
    revisions = ForwardBetaFourRevisions(store.database_url)

    for ask in (None, "", "   "):
        with pytest.raises(ForwardBetaFourError) as refusal:
            revisions.revise(ask)

        assert FORWARD_BETA_FOUR_ERROR_CODE in str(refusal.value)

    assert not revisions.path.exists()


def test_get_refuses_an_unaskable_cycle_and_answers_an_absent_one(
    revisions: ForwardBetaFourRevisions, measured_signal: ForwardRecord
) -> None:
    """An unrevised cycle and an unaskable one are different facts, so the
    point read answers ``None`` for the first and refuses the second."""
    revision, _ = revisions.revise("cycle-1")

    assert revisions.get("cycle-1") == revision
    assert revisions.get("never-revised") is None
    with pytest.raises(ForwardBetaFourError):
        revisions.get("   ")


# -- The ladder -------------------------------------------------------------------


def test_over_reads_the_one_attribute_the_composed_component_exposes(
    database_url: str,
) -> None:
    # The bridge from the seat: one question — "what is the composed
    # forward-record store?" — and this act holds the writer for the same
    # database the record and its observations landed in.  The attribute
    # is the seam, not a class: the loader imports a member under a
    # synthetic name, so the composed store is structurally a
    # ForwardRecords and never the same class object a direct import
    # yields, and an isinstance would defeat the composition this
    # workspace runs on.
    from forward import ForwardRecords

    composed = ForwardRecords(database_url)
    over_composed = ForwardBetaFourRevisions.over(composed)
    assert over_composed.database_url == composed.database_url
    over_duck = ForwardBetaFourRevisions.over(
        SimpleNamespace(database_url=database_url)
    )
    assert over_duck.database_url == database_url
    assert FORWARD_BETA_FOUR_SEAM == "database_url"
    with pytest.raises(TypeError):
        ForwardBetaFourRevisions.over(SimpleNamespace())


def test_resolve_reads_the_url_the_deployment_names() -> None:
    # The composed-component resolution: DATABASE_URL names the store, an
    # empty or whitespace value counts as unset, and absent is a
    # discoverable deployment state (no component composes) rather than an
    # exception — the stance every store in this workspace takes.
    assert ForwardBetaFourRevisions.resolve({}) is None
    assert ForwardBetaFourRevisions.resolve({"DATABASE_URL": "   "}) is None
    resolved = ForwardBetaFourRevisions.resolve({"DATABASE_URL": "sqlite:///x.db"})
    assert resolved is not None
    assert resolved.database_url == "sqlite:///x.db"
    assert ForwardBetaFourRevisions.resolve({"DATABASE_URL": " sqlite:///x.db "}) is not None


def test_the_module_level_spellings_write_and_read_one_database(
    store: ForwardRecords, measured_signal: ForwardRecord
) -> None:
    """The act as one call for the caller that wants it without holding a
    store — the outer-loop job's recalibration step — writing and reading
    the same database the store spelling would, and splitting on the same
    seam the member's other acts split on: the reader without a store
    answers ``None`` where the writer refuses by name."""
    revision = revised_beta_four("cycle-1", env={DATABASE_URL_ENV: store.database_url})

    assert revision.cycle_id == "cycle-1"
    assert standing_beta_four(env={DATABASE_URL_ENV: store.database_url}) == revision
    assert standing_beta_four(env={}) is None

    with pytest.raises(ForwardStoreError) as refusal:
        revised_beta_four("cycle-2", env={})

    message = str(refusal.value)
    assert FORWARD_BETA_FOUR_ERROR_CODE in message
    assert DATABASE_URL_ENV in message


# -- The table and the member's own claims ----------------------------------------


def test_the_table_holds_the_fourteen_columns_the_row_names(
    revisions: ForwardBetaFourRevisions, measured_signal: ForwardRecord
) -> None:
    """The persistence is the feature, so the shape is pinned against the
    table itself: the chain's own number, the cycle, the prior and its
    strength, the evidence (sum, count, three tallies, the cost face, the
    vintage), the blend, and the one clock-read figure."""
    revisions.revise("cycle-1")
    connection = revisions._connect()
    try:
        cursor = connection.execute(
            f"PRAGMA table_info({FORWARD_BETA_FOUR_TABLE})"
        )
        columns = {row[1] for row in cursor.fetchall()}
        cursor.close()
    finally:
        connection.close()

    assert columns == {
        "sequence",
        "cycle_id",
        "prior_beta_four",
        "prior_weight",
        "observed_divergences",
        "divergence_sum",
        "unbacktested",
        "unobserved",
        "zero_backtest",
        "cost_reconciliations",
        "cost_divergence_bps",
        "observed_through",
        "revised_beta_four",
        "revised_at",
    }


def test_the_module_authors_its_own_table_and_no_ones_elses(
    store: ForwardRecords,
) -> None:
    """The member-owned stance :mod:`forward.reconciliation` takes, pinned
    as code rather than prose: this module's *code* holds the one
    ``CREATE TABLE`` for its own per-cycle grain, and none for any table
    the migration tree owns — those it runs through the owners' own
    statements, as :mod:`forward.schema` always has."""
    code = code_of(forward.beta_four)

    # The f-string placeholder survives unparsing, the same spelling the
    # reconciliation suite pins its own DDL with: one CREATE TABLE, one
    # INSERT target, and the one-row-per-cycle law held in the schema
    # itself — which this member *may* state on its own table where 0108
    # declined to hold the observation law on its.
    assert code.count("CREATE TABLE") == 1
    assert "CREATE TABLE IF NOT EXISTS {FORWARD_BETA_FOUR_TABLE}" in code
    assert "UNIQUE (cycle_id)" in code
    assert "AUTOINCREMENT" in code
    assert code.count("INSERT INTO") == 1
    assert "INSERT INTO {FORWARD_BETA_FOUR_TABLE}" in code


def test_the_revised_value_is_never_a_parameter(
    revisions: ForwardBetaFourRevisions,
) -> None:
    """The caller names the cycle; everything else is read.  The signature
    is pinned because it is the feature's sharpest edge: a caller that
    could hand over a coefficient could hand the dreaming loop one nobody
    computed, past the store whose whole job is to compute it."""
    import inspect

    parameters = inspect.signature(revisions.revise).parameters

    assert list(parameters) == ["cycle_id"]
