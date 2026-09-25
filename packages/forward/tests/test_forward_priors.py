"""Feature 339's act: decay priors revised from observed forward half-life.

app_spec.xml, "Forward-Test Tracking", feature 339: *System updates decay
priors from observed forward half-life, which returns revised inputs to
campaign planning.*  These tests pin the four halves of that sentence:

* **updates** — the prior moves only as evidence accumulates, and the
  zero-evidence answer is the prior itself (prd §5's own 90 days, held at
  feature 228's pseudo-count strength), the way feature 228's zero-evidence
  path equals ``schedule(beta)``;
* **from observed forward half-life** — the half-life is the day the
  *prefix* retention — feature 337's own statistic, computed on prefixes —
  first falls to §11's half line.  A single noisy day below the line does
  not date a crossing (§C10's *"statistically meaningful window"*), a
  signal that never falls to half is **censored** — its bound counted,
  never averaged in — and the per-signal spelling refuses what the
  aggregate counts, each absence naming its one-call repair;
* **returns revised inputs** — the answer is a
  :class:`~forward.priors.DecayPriorRevision` carrying the figure beside
  its evidence, its absences and its vintage, rendered as the mapping a
  campaign planner feeds ``plan_grid`` (the risk register's own mitigation:
  *"feed half-life into ``plan_grid``"*);
* **campaign planning** — no figure is a parameter, nothing is persisted,
  and no clock is read: the revision is a pure function of the rows
  features 332, 333 and 337 already hold, re-derived on every call.

The value laws are pinned here too: an instance whose stated half-life,
crossing or revised figure is not the arithmetic of its own evidence is
refused, so a fabricated timescale cannot reach ``plan_grid``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import FrozenInstanceError
from pathlib import Path

import forward.priors
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
    DATABASE_URL_ENV,
    FORWARD_DECAY_PRIOR_ERROR_CODE,
    FORWARD_PRIOR_SEAM,
    PRIOR_HALF_LIFE_DAYS,
    PRIOR_WEIGHT,
    RETENTION_LINE,
    REVISED_HALF_LIFE_KEY,
    DecayPriorRevision,
    ForwardDecayPriorError,
    ForwardDecayPriors,
    ForwardHalfLife,
    ForwardRecord,
    ForwardRecordError,
    ForwardRecords,
    ForwardRetentionError,
    forward_half_life,
    revised_decay_prior,
)
from forward.observation import ForwardObservations
from forward.retention import ForwardIcRetentions

#: The promotion boundary this suite is measured against, restated so a
#: conftest change that moved ``DECIDED_AT`` fails at the first fixture
#: rather than somewhere inside a refusal message — the same discipline the
#: observation and retention suites take.
DECIDED = dt.datetime.fromisoformat(DECIDED_AT)

#: The boundary day, and the first day an observation may honestly name.
BOUNDARY_DAY = dt.date(2026, 3, 1)
FIRST_DAY = dt.date(2026, 3, 2)

#: The backtest edge every measured fixture lands, and its §11 half.  The
#: figures below keep every prefix mean clear of the line by a margin no
#: float representation can close, so the crossings asserted are decisions
#: of the *data* rather than of the arithmetic.
BACKTEST = 0.2
HALF = BACKTEST * RETENTION_LINE

#: Three observed days whose prefix means are ``0.12``, ``0.115`` and
#: ``0.0967`` — the third is the first at or below half, so the half-life
#: is three days from the boundary.
DAYS = tuple(dt.date(2026, 3, 2) + dt.timedelta(days=i) for i in range(3))
DECLINE = (0.12, 0.11, 0.06)
HALF_LIFE = 3
CROSSING_MEAN = sum(DECLINE) / len(DECLINE)

#: Six observed days all above half — the healthy young signal, whose
#: half-life is a bound and not a value.
STABLE = (0.12, 0.12, 0.12, 0.12, 0.12, 0.12)


@pytest.fixture
def priors(promoted_signal: ForwardRecords) -> ForwardDecayPriors:
    """The prior store over the record's own store — 339's seam.

    Built with :meth:`ForwardDecayPriors.over` off the very store the record
    was opened through, so the reader and the opener point at one database by
    construction — the shape a deployment reaches when it asks the composed
    ``forward`` component for the act.
    """
    return ForwardDecayPriors.over(promoted_signal)


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
    figure through feature 337's, so every figure the half-life dates its
    crossing on is a figure the member actually persisted — a hand-written
    row would pin the boundary against a fixture the suite made up.
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


@pytest.fixture
def declining_record(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> ForwardRecord:
    """One signal measured through its decline — the reached case."""
    assert opened_record.promoted_at == DECIDED
    assert opened_record.observed_on == BOUNDARY_DAY
    _observe(promoted_signal, NODE_ID, DECLINE)
    return opened_record


def _promote_second_signal(store: ForwardRecords, node_id: str) -> None:
    """A second signal's closed promotion in the *same* database.

    :func:`conftest.promote_signal` brings the database up as well as filing
    the row, and its ``epoch_ledger`` insert is unconditional — so a second
    call against a database that already holds the epoch collides on the
    primary key.  This helper does the part that is per-signal, with the
    same fixed instant the fixture used, so every signal shares one
    boundary and the half-lives below differ only by their coefficients.
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


# -- The half-life: observed -----------------------------------------------------


def test_the_half_life_is_the_day_the_prefix_mean_falls_to_half(
    priors: ForwardDecayPriors, declining_record: ForwardRecord
) -> None:
    """The sentence's noun, dated once: prefix means ``0.12``, ``0.115``,
    ``0.0967`` against a half of ``0.1`` — the third day is the half-life.

    The prefix mean is feature 337's statistic computed on prefixes, so the
    crossing is the day §11's criterion first fails: retention of exactly
    half is the criterion *not* holding (``> 0.5``), and a store that dated
    the crossing on the day's own figure instead would answer ``2`` — one
    noisy day moved the boundary.
    """
    answer = priors.half_life(NODE_ID)

    assert answer.reached
    assert answer.half_life_days == HALF_LIFE
    assert answer.crossing_on == BOUNDARY_DAY + dt.timedelta(days=HALF_LIFE)
    assert answer.live_ic_at_crossing == pytest.approx(CROSSING_MEAN, abs=1e-12)
    assert answer.live_ic_at_crossing <= HALF
    assert answer.boundary_on == BOUNDARY_DAY
    assert answer.backtest_ic == BACKTEST


def test_the_answer_carries_its_own_evidence(
    priors: ForwardDecayPriors, declining_record: ForwardRecord
) -> None:
    """The days and the record's whole extent travel with the figure.

    ``observed_days`` and ``observed_through`` carry the record's *whole*
    extent and not the crossing's: a signal crossed on day 3 and observed
    through day 3 is the fixture's shape, but the fields must state the rows
    they came from so a reader can tell a half-life over three days from
    one over thirty — the same reason :class:`~forward.retention.
    IcRetention` carries its day count.
    """
    answer = priors.half_life(NODE_ID)

    assert answer.node_id == NODE_ID
    assert answer.observed_days == len(DECLINE)
    assert answer.observed_through == max(DAYS)
    summary = answer.summary()
    assert summary["half_life_days"] == HALF_LIFE
    assert summary["crossing_on"] == (BOUNDARY_DAY + dt.timedelta(days=3)).isoformat()
    assert summary["boundary_on"] == BOUNDARY_DAY.isoformat()
    assert summary["reached"] is True


def test_one_noisy_day_below_the_line_is_not_a_crossing(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """§C10's *"statistically meaningful window"*, read as the prefix mean.

    Three days ``0.15``, ``0.15``, ``0.02`` against a half of ``0.1``: the
    third day's own figure is far below the line, but the mean over the
    window is ``0.1067`` and has not fallen.  A store that dated the
    half-life on the daily figure would hand ``plan_grid`` a timescale one
    noisy day produced.
    """
    _observe(promoted_signal, NODE_ID, (0.15, 0.15, 0.02))
    answer = ForwardDecayPriors.over(promoted_signal).half_life(NODE_ID)

    assert not answer.reached
    assert answer.half_life_days is None
    assert answer.crossing_on is None
    assert answer.live_ic_at_crossing is None
    assert answer.observed_days == 3


def test_a_signal_that_never_falls_to_half_is_censored_not_refused(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """The healthy young signal is the good case, and it is answered.

    A censored signal's half-life is *greater than* the days observed — a
    bound, not a value — and the answer states exactly that: no crossing
    figures, the days it was observed beside it, and a summary whose
    ``null`` and ``reached: false`` a reader can tell apart from *never
    measured*.
    """
    _observe(promoted_signal, NODE_ID, STABLE)
    answer = ForwardDecayPriors.over(promoted_signal).half_life(NODE_ID)

    assert not answer.reached
    assert answer.half_life_days is None
    assert answer.observed_days == len(STABLE)
    assert answer.observed_through == FIRST_DAY + dt.timedelta(days=len(STABLE) - 1)
    summary = answer.summary()
    assert summary["half_life_days"] is None
    assert summary["crossing_on"] is None
    assert summary["reached"] is False


def test_a_crossing_is_dated_from_the_boundary_not_the_first_row(
    priors: ForwardDecayPriors, declining_record: ForwardRecord
) -> None:
    """The offset is measured from the record's own boundary day.

    Day one of the observations is 2026-03-02 — one day *after* the
    boundary — so a half-life of three days names 2026-03-04, and a store
    that counted rows instead of days would answer the row index and drift
    one day per missed observation.  The backfill case is the same law at
    the far end: a missed day skips an offset without moving the boundary.
    """
    answer = priors.half_life(NODE_ID)
    assert (answer.crossing_on - answer.boundary_on).days == answer.half_life_days


# -- The prior: revised ----------------------------------------------------------


def test_zero_observations_answer_the_prior_exactly(
    promoted_signal: ForwardRecords,
) -> None:
    """The zero-evidence law: nothing measured, and the prior stands.

    §5's own figure — 90 days — is what campaign planning carries before
    any forward evidence exists, so the revision over an empty table is the
    prior to the byte, exactly the way feature 228's zero-evidence path
    equals ``schedule(beta)``.  An approximation here would be a prior that
    moved before any signal was measured.
    """
    revision = ForwardDecayPriors.over(promoted_signal).revise()

    assert revision.signals == ()
    assert revision.revised_half_life_days == PRIOR_HALF_LIFE_DAYS
    assert revision.revised_half_life_days == 90.0
    assert revision.observed_half_lives == 0
    assert revision.censored_signals == 0
    assert revision.observed_through is None


def test_the_revision_blends_the_observed_half_lives_into_the_prior(
    promoted_signal: ForwardRecords, declining_record: ForwardRecord
) -> None:
    """Two half-lives — 3 days and 7 days — move 90 to 68.75 exactly.

    ``(6 × 90 + 3 + 7) / (6 + 2)`` is exact in binary, so the blend is
    asserted without an epsilon: the revision is arithmetic over whole days
    and one float division, and a figure that needed a tolerance would be a
    figure the store did not compute.
    """
    second = "33333333-3333-4333-8333-333333333333"
    _promote_second_signal(promoted_signal, second)
    promoted_signal.open_record(second, forward_days=FORWARD_DAYS)
    # Six days at 0.11 (prefix mean 0.11, above the 0.1 half), then 0.02:
    # the seventh day's prefix mean is 0.68/7 ≈ 0.0971 — the crossing.
    _observe(promoted_signal, second, (0.11,) * 6 + (0.02,))

    revision = ForwardDecayPriors.over(promoted_signal).revise()

    assert sorted(revision.half_lives) == [HALF_LIFE, 7]
    assert revision.observed_half_lives == 2
    assert revision.revised_half_life_days == (PRIOR_WEIGHT * 90.0 + 3 + 7) / (
        PRIOR_WEIGHT + 2
    )
    assert revision.revised_half_life_days == 68.75


def test_censored_signals_are_counted_not_averaged_in(
    promoted_signal: ForwardRecords, declining_record: ForwardRecord
) -> None:
    """A bound is not a value: the healthy signal moves nothing.

    One signal crossed at day 3; one is censored at six days above half.
    The blend takes the reached half-life alone — averaging the censored
    signal's six days in as though it had died on its last observed day
    would tighten the prior toward pessimism precisely when the fleet is
    healthy, the exact fabrication :mod:`forward.retention` refuses when it
    declines to average missed days as zeroes.
    """
    second = "33333333-3333-4333-8333-333333333333"
    _promote_second_signal(promoted_signal, second)
    promoted_signal.open_record(second, forward_days=FORWARD_DAYS)
    _observe(promoted_signal, second, STABLE)

    revision = ForwardDecayPriors.over(promoted_signal).revise()

    assert revision.observed_half_lives == 1
    assert revision.censored_signals == 1
    assert revision.revised_half_life_days == (PRIOR_WEIGHT * 90.0 + HALF_LIFE) / (
        PRIOR_WEIGHT + 1
    )


def test_the_revision_counts_what_it_could_not_measure(
    promoted_signal: ForwardRecords, declining_record: ForwardRecord
) -> None:
    """Unbacktested, unobserved and edgeless signals are named, not fatal.

    A young deployment's outer loop must not be blocked by the figures that
    have not arrived: a signal whose backtest has not landed, one the
    observation job has not reached, and one whose backtest is an honest
    zero are all counted in the answer — visible absences, the stance
    feature 337's reader takes toward an unconfigured deployment rather
    than the one its writer takes toward a missing figure.
    """
    unbacktested = "33333333-3333-4333-8333-333333333333"
    unobserved = "44444444-4444-4444-8444-444444444444"
    edgeless = "55555555-5555-4555-8555-555555555555"
    for node in (unbacktested, unobserved, edgeless):
        _promote_second_signal(promoted_signal, node)
        promoted_signal.open_record(node, forward_days=FORWARD_DAYS)
    _observe(promoted_signal, unbacktested, STABLE, backtest=None)
    ForwardIcRetentions.over(promoted_signal).record_backtest_ic(
        unobserved, backtest_ic=BACKTEST
    )
    ForwardIcRetentions.over(promoted_signal).record_backtest_ic(
        edgeless, backtest_ic=0.0
    )
    _observe(promoted_signal, edgeless, STABLE, backtest=None)

    revision = ForwardDecayPriors.over(promoted_signal).revise()

    assert revision.unbacktested == 1
    assert revision.unobserved == 1
    assert revision.zero_backtest == 1
    assert len(revision.signals) == 1  # the declining fixture only
    summary = revision.summary()
    assert summary["unbacktested_signals"] == 1
    assert summary["unobserved_signals"] == 1
    assert summary["zero_backtest_signals"] == 1


def test_the_summary_is_the_input_campaign_planning_was_promised(
    promoted_signal: ForwardRecords, declining_record: ForwardRecord
) -> None:
    """The risk register's mitigation, rendered: *feed half-life into
    ``plan_grid``*.

    The mapping carries the revised figure under its own name beside the
    evidence that qualifies it — the prior it moved from, the half-lives it
    summed, the signals it could not measure, the vintage it was read at —
    because a planning input without its evidence is a number a campaign
    cannot audit itself against.
    """
    revision = ForwardDecayPriors.over(promoted_signal).revise()
    summary = revision.summary()

    assert summary[REVISED_HALF_LIFE_KEY] == revision.revised_half_life_days
    assert summary["prior_half_life_days"] == PRIOR_HALF_LIFE_DAYS
    assert summary["prior_weight"] == PRIOR_WEIGHT
    assert summary["observed_half_lives"] == 1
    assert summary["half_lives"] == [HALF_LIFE]
    assert summary["measured_signals"] == 1
    assert summary["observed_through"] == max(DAYS).isoformat()


def test_the_evidence_names_each_signal_once_ascending(
    promoted_signal: ForwardRecords, declining_record: ForwardRecord
) -> None:
    """The whole-table read is ordered, so two revisions compare entry for
    entry — the determinism the store's ``ORDER BY`` buys and the answer's
    construction law keeps."""
    second = "33333333-3333-4333-8333-333333333333"
    _promote_second_signal(promoted_signal, second)
    promoted_signal.open_record(second, forward_days=FORWARD_DAYS)
    _observe(promoted_signal, second, STABLE)

    revision = ForwardDecayPriors.over(promoted_signal).revise()

    assert [signal.node_id for signal in revision.signals] == sorted(
        [NODE_ID, second]
    )


def test_two_revisions_of_unmoved_rows_answer_equal_figures(
    priors: ForwardDecayPriors, declining_record: ForwardRecord
) -> None:
    """No memo, no cache: both inputs are read on every call.

    A prior that read a stale copy would move campaign planning on a track
    record that had already moved — the same reason :mod:`forward.
    retention` keeps no memo of its ratio — so the store re-derives, and
    two calls over the same rows answer equal frozen values.
    """
    assert priors.revise() == priors.revise()


def test_the_vintage_spans_every_row_the_revision_read(
    promoted_signal: ForwardRecords, declining_record: ForwardRecord
) -> None:
    """``observed_through`` is the table's own latest measurement.

    The revision reads the whole fleet, and an observation on a signal the
    blend could not use — its backtest never landed — is still a
    measurement the table holds: dating the vintage after it would state a
    revision taken before rows the reader had already seen.
    """
    unbacktested = "33333333-3333-4333-8333-333333333333"
    _promote_second_signal(promoted_signal, unbacktested)
    promoted_signal.open_record(unbacktested, forward_days=FORWARD_DAYS)
    late_day = dt.date(2026, 3, 20)
    ForwardObservations.over(promoted_signal).append_observation(
        unbacktested, observed_on=late_day, live_ic=0.1, forward_days=FORWARD_DAYS
    )

    revision = ForwardDecayPriors.over(promoted_signal).revise()

    assert revision.observed_through == late_day
    assert revision.unbacktested == 1


# -- The per-signal refusals -----------------------------------------------------


def test_a_signal_with_no_record_is_refused_naming_the_repair(
    priors: ForwardDecayPriors,
) -> None:
    """No boundary, no half-life — and opening one silently is the
    fabrication the record exists to prevent."""
    missing = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(ForwardDecayPriorError) as raised:
        priors.half_life(missing)
    assert FORWARD_DECAY_PRIOR_ERROR_CODE in str(raised.value)
    assert "POST /forward/promote" in str(raised.value)


def test_an_unobserved_record_is_refused_not_answered_with_zero(
    priors: ForwardDecayPriors, opened_record: ForwardRecord
) -> None:
    """A half-life of zero days would read as a signal that died on the
    spot; an unrun job is not that, and the two must not read alike in
    front of a prior that moves campaign planning."""
    with pytest.raises(ForwardDecayPriorError) as raised:
        priors.half_life(NODE_ID)
    assert FORWARD_DECAY_PRIOR_ERROR_CODE in str(raised.value)
    assert "feature 333" in str(raised.value)


def test_an_unbacktested_record_is_refused_naming_feature_337(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """Half of §11's line is half *of the backtest figure* — a record whose
    divisor has not landed has no line to fall to."""
    _observe(promoted_signal, NODE_ID, DECLINE, backtest=None)
    with pytest.raises(ForwardDecayPriorError) as raised:
        ForwardDecayPriors.over(promoted_signal).half_life(NODE_ID)
    assert FORWARD_DECAY_PRIOR_ERROR_CODE in str(raised.value)
    assert "record_backtest_ic" in str(raised.value)


def test_a_zero_backtest_is_refused_at_the_ask_and_counted_in_the_aggregate(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """The honest figure of an edgeless signal: nothing to halve.

    The two spellings take the two stances the module documents — the ask
    refuses because its caller asked about one signal; the aggregate counts
    because a fleet is heterogeneous on purpose — and both are pinned here
    so neither silently becomes the other.
    """
    _observe(promoted_signal, NODE_ID, DECLINE, backtest=0.0)
    priors_store = ForwardDecayPriors.over(promoted_signal)

    with pytest.raises(ForwardDecayPriorError) as raised:
        priors_store.half_life(NODE_ID)
    assert FORWARD_DECAY_PRIOR_ERROR_CODE in str(raised.value)

    revision = priors_store.revise()
    assert revision.zero_backtest == 1
    assert revision.observed_half_lives == 0


def test_a_negative_backtest_refuses_both_spellings(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """A figure wearing the column's name: promotion requires a positive
    edge, and the half of a negative coefficient is not a threshold anyone
    defined.  Feature 337 stores the figure; this module refuses to date a
    decay against it, in the aggregate as well, because a prior moved by it
    would move campaign planning on an edge that points the other way."""
    _observe(promoted_signal, NODE_ID, DECLINE, backtest=-0.2)
    priors_store = ForwardDecayPriors.over(promoted_signal)

    with pytest.raises(ForwardDecayPriorError):
        priors_store.half_life(NODE_ID)
    with pytest.raises(ForwardDecayPriorError) as raised:
        priors_store.revise()
    assert FORWARD_DECAY_PRIOR_ERROR_CODE in str(raised.value)


def test_a_backtest_outside_the_coefficients_bound_refuses_in_337s_vocabulary(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """A hand-edited ``2.5`` is feature 337's gate to refuse, not this
    module's to restate — the coefficient validator has one spelling in the
    member, and its refusal propagates as itself, the way the record
    contract's own refusals do through every later act."""
    _observe(promoted_signal, NODE_ID, DECLINE)
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET backtest_ic = 2.5 WHERE node_id = ?",
                (NODE_ID,),
            )
    finally:
        connection.close()

    with pytest.raises(ForwardRetentionError):
        ForwardDecayPriors.over(promoted_signal).half_life(NODE_ID)
    with pytest.raises(ForwardRetentionError):
        ForwardDecayPriors.over(promoted_signal).revise()


def test_two_vintages_refuse_in_this_modules_own_vocabulary(
    promoted_signal: ForwardRecords, opened_record: ForwardRecord
) -> None:
    """A boundary nobody can state dates no offsets — the one-vintage law,
    refused here in this module's words the way the observation and
    retention modules refuse it in theirs."""
    _observe(promoted_signal, NODE_ID, DECLINE)
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET promoted_at = ? "
                "WHERE node_id = ? AND observed_on != ?",
                ("2026-04-01T12:00:00+00:00", NODE_ID, BOUNDARY_DAY.isoformat()),
            )
    finally:
        connection.close()

    with pytest.raises(ForwardDecayPriorError) as raised:
        ForwardDecayPriors.over(promoted_signal).half_life(NODE_ID)
    assert FORWARD_DECAY_PRIOR_ERROR_CODE in str(raised.value)
    assert "promoted_at" in str(raised.value)
    with pytest.raises(ForwardDecayPriorError):
        ForwardDecayPriors.over(promoted_signal).revise()


def test_a_malformed_identity_is_refused_before_any_database_is_opened(
    tmp_path: Path,
) -> None:
    """The record contract's own refusal, propagated as itself — and the
    ask validates before anything is opened, so a refused call over a URL
    nothing has touched leaves no file behind.  (The fixture's own database
    already exists by the time a store over it is built — the promote
    step wrote it — so the no-file claim is asked over a fresh URL, which
    is the only state where the assertion can mean anything.)"""
    fresh = ForwardDecayPriors(f"sqlite:///{tmp_path / 'unasked.db'}")
    assert not fresh.path.exists()

    with pytest.raises(ForwardRecordError):
        fresh.half_life("not-a-uuid")

    assert not fresh.path.exists()


# -- The value laws --------------------------------------------------------------


def _measured_answer(**overrides: object) -> ForwardHalfLife:
    """The fixture's reached answer, rebuilt field by field, for the laws."""
    fields: dict[str, object] = {
        "node_id": NODE_ID,
        "boundary_on": BOUNDARY_DAY,
        "observed_days": len(DECLINE),
        "observed_through": max(DAYS),
        "backtest_ic": BACKTEST,
        "half_life_days": HALF_LIFE,
        "crossing_on": BOUNDARY_DAY + dt.timedelta(days=HALF_LIFE),
        "live_ic_at_crossing": CROSSING_MEAN,
    }
    fields.update(overrides)
    return ForwardHalfLife(**fields)  # type: ignore[arg-type]


def test_a_crossing_mean_above_the_line_is_refused() -> None:
    """An instance whose own figures do not fall to half dates a crossing
    that did not happen — the re-derivation law that keeps a fabricated
    half-life away from the blend."""
    with pytest.raises(ForwardDecayPriorError) as raised:
        _measured_answer(live_ic_at_crossing=0.15)
    assert FORWARD_DECAY_PRIOR_ERROR_CODE in str(raised.value)


def test_an_offset_the_crossing_day_does_not_produce_is_refused() -> None:
    """The half-life is the distance between two dates the record holds,
    and an instance whose own dates do not produce it is refused rather
    than carried."""
    with pytest.raises(ForwardDecayPriorError):
        _measured_answer(half_life_days=HALF_LIFE + 1)


def test_a_censored_signal_carrying_crossing_figures_is_refused() -> None:
    """A bound wearing a value's clothes: censoring with a dated crossing
    would let the aggregate average the bound in as though the signal had
    died on the day stated."""
    with pytest.raises(ForwardDecayPriorError):
        _measured_answer(
            half_life_days=None,
            crossing_on=BOUNDARY_DAY + dt.timedelta(days=HALF_LIFE),
            live_ic_at_crossing=CROSSING_MEAN,
        )


def _reached_signal(node_id: str, days: int) -> ForwardHalfLife:
    """A minimal reached half-life, offset ``days`` from the boundary."""
    crossing = BOUNDARY_DAY + dt.timedelta(days=days)
    return ForwardHalfLife(
        node_id=node_id,
        boundary_on=BOUNDARY_DAY,
        observed_days=days,
        observed_through=crossing,
        backtest_ic=BACKTEST,
        half_life_days=days,
        crossing_on=crossing,
        live_ic_at_crossing=HALF,
    )


def test_a_revision_the_evidence_does_not_blend_is_refused() -> None:
    """The revised figure is not a parameter: an instance whose own
    half-lives do not produce it would hand ``plan_grid`` a decay timescale
    nobody computed."""
    with pytest.raises(ForwardDecayPriorError) as raised:
        DecayPriorRevision(
            prior_half_life_days=PRIOR_HALF_LIFE_DAYS,
            prior_weight=PRIOR_WEIGHT,
            signals=(_reached_signal(NODE_ID, 3),),
            unbacktested=0,
            unobserved=0,
            zero_backtest=0,
            observed_through=max(DAYS),
            revised_half_life_days=42.0,
        )
    assert FORWARD_DECAY_PRIOR_ERROR_CODE in str(raised.value)
    assert "blend" in str(raised.value)


def test_the_prior_is_not_a_dial_the_caller_may_choose() -> None:
    """§13.4's recalibration starts from the 90-day horizon the prd states;
    an answer built over some other prior is not this feature's answer."""
    with pytest.raises(ForwardDecayPriorError):
        DecayPriorRevision(
            prior_half_life_days=30.0,
            prior_weight=PRIOR_WEIGHT,
            signals=(),
            unbacktested=0,
            unobserved=0,
            zero_backtest=0,
            observed_through=None,
            revised_half_life_days=30.0,
        )
    with pytest.raises(ForwardDecayPriorError):
        DecayPriorRevision(
            prior_half_life_days=PRIOR_HALF_LIFE_DAYS,
            prior_weight=1.0,
            signals=(),
            unbacktested=0,
            unobserved=0,
            zero_backtest=0,
            observed_through=None,
            revised_half_life_days=90.0,
        )


def test_a_vintage_before_the_evidence_is_refused() -> None:
    """A revision dated before the rows it carries would state a track
    record that had not happened yet."""
    with pytest.raises(ForwardDecayPriorError):
        DecayPriorRevision(
            prior_half_life_days=PRIOR_HALF_LIFE_DAYS,
            prior_weight=PRIOR_WEIGHT,
            signals=(_reached_signal(NODE_ID, 3),),
            unbacktested=0,
            unobserved=0,
            zero_backtest=0,
            observed_through=BOUNDARY_DAY,
            revised_half_life_days=(PRIOR_WEIGHT * 90.0 + 3) / (PRIOR_WEIGHT + 1),
        )


def test_the_answers_are_frozen() -> None:
    """A moved answer is a moved boundary: the crossing and the blend are
    decisions the rows made, not fields a caller may edit after the fact."""
    answer = _measured_answer()
    with pytest.raises(FrozenInstanceError):
        answer.half_life_days = 99  # type: ignore[misc]
    revision = DecayPriorRevision(
        prior_half_life_days=PRIOR_HALF_LIFE_DAYS,
        prior_weight=PRIOR_WEIGHT,
        signals=(),
        unbacktested=0,
        unobserved=0,
        zero_backtest=0,
        observed_through=None,
        revised_half_life_days=PRIOR_HALF_LIFE_DAYS,
    )
    with pytest.raises(FrozenInstanceError):
        revision.revised_half_life_days = 99.0  # type: ignore[misc]


def test_the_derived_tallies_cannot_drift_from_the_evidence() -> None:
    """The counts a planner reads are derived from the signals carried,
    never tallied beside them — a second copy of one fact is a copy that
    can drift, the reason feature 294's count is derived and not
    incremented."""
    revision = DecayPriorRevision(
        prior_half_life_days=PRIOR_HALF_LIFE_DAYS,
        prior_weight=PRIOR_WEIGHT,
        signals=(
            _reached_signal(NODE_ID, 3),
            ForwardHalfLife(
                node_id="33333333-3333-4333-8333-333333333333",
                boundary_on=BOUNDARY_DAY,
                observed_days=2,
                observed_through=BOUNDARY_DAY + dt.timedelta(days=2),
                backtest_ic=BACKTEST,
                half_life_days=None,
                crossing_on=None,
                live_ic_at_crossing=None,
            ),
        ),
        unbacktested=1,
        unobserved=2,
        zero_backtest=3,
        observed_through=BOUNDARY_DAY + dt.timedelta(days=3),
        revised_half_life_days=(PRIOR_WEIGHT * 90.0 + 3) / (PRIOR_WEIGHT + 1),
    )

    assert revision.observed_half_lives == 1
    assert revision.censored_signals == 1
    assert revision.half_lives == (3,)
    assert revision.summary()["censored_signals"] == 1


# -- The ladder ------------------------------------------------------------------


def test_over_reads_the_seam_off_the_composed_store(
    promoted_signal: ForwardRecords,
) -> None:
    """One URL, one table, five acts: the bridge from the seat to the
    revision holds the reader for the same database the component points
    at, and a second store constructed beside the component is exactly
    what this refuses to be."""
    store = ForwardDecayPriors.over(promoted_signal)
    assert store.database_url == promoted_signal.database_url

    with pytest.raises(TypeError) as raised:
        ForwardDecayPriors.over(object())
    assert FORWARD_PRIOR_SEAM in str(raised.value)


def test_the_module_level_spellings_resolve_the_url_or_the_env(
    promoted_signal: ForwardRecords, declining_record: ForwardRecord
) -> None:
    """A caller holding only a URL gets the same answers a caller holding
    the store does — the ladder features 333, 340 and 337 climb, spelled
    one feature later again."""
    url = promoted_signal.database_url
    assert forward_half_life(NODE_ID, database_url=url).half_life_days == HALF_LIFE
    assert (
        revised_decay_prior(database_url=url).revised_half_life_days
        == (PRIOR_WEIGHT * 90.0 + HALF_LIFE) / (PRIOR_WEIGHT + 1)
    )
    assert revised_decay_prior(env={DATABASE_URL_ENV: url}).observed_half_lives == 1


def test_an_unnamed_database_refuses_rather_than_answering_the_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dangerous failure is specific: a revision that ran and a
    revision that never consulted a database answer the *same shape* — 90
    days with counts beside it — so the refusal is the only thing that
    keeps them apart."""
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(ForwardDecayPriorError) as raised:
        revised_decay_prior()
    assert DATABASE_URL_ENV in str(raised.value)


def test_resolve_answers_none_when_nothing_names_a_database() -> None:
    """The reader's spelling, and deliberately the same one feature 337's
    reader answers with: a deployment with no relational store holds no
    prior reader, which is a discoverable state rather than an
    exception."""
    assert ForwardDecayPriors.resolve({}) is None
    assert (
        ForwardDecayPriors.resolve({DATABASE_URL_ENV: "sqlite:///tmp/none.db"})
        is not None
    )


def test_the_store_refuses_an_empty_url_at_construction() -> None:
    """A wiring fault is a fact about the store, and the store is the wrong
    place to discover it on every call."""
    with pytest.raises(ForwardDecayPriorError):
        ForwardDecayPriors("  ")


# -- The module's own laws -------------------------------------------------------


def test_the_module_authors_no_ddl_and_names_no_registry() -> None:
    """The schema law and the module law, asserted on the *code* with
    docstrings stripped: the module has to be able to say *no table* in its
    own prose while authoring none, and ``promotion_registry`` appearing in
    it would be a second reader of a table the window seam owns."""
    text = code_of(forward.priors)
    for token in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE INDEX"):
        assert token not in text, f"forward.priors authors DDL: {token}"
    assert "promotion_registry" not in text


def test_the_module_reads_no_clock() -> None:
    """Every date in both answers is the table's own — boundary days,
    crossing days, the latest observed day — never the writer's, for the
    reason :mod:`forward.observation` refuses a default day: a revision
    dated ``now`` would be a prior revised against whatever the job
    schedule happened to be."""
    text = code_of(forward.priors)
    assert "utc_now" not in text
    assert "datetime.now" not in text
    assert "dt.now" not in text


def test_the_prior_constants_are_the_prds_own_figures() -> None:
    """90 days is §5's and §11's figure — the horizon the whole member is
    shaped around is the zero-evidence prior; six is feature 228's
    pseudo-count strength; the line is §11's own half and deliberately not
    §C10's 40% (that line demotes a signal, this one dates it)."""
    assert PRIOR_HALF_LIFE_DAYS == 90.0
    assert PRIOR_WEIGHT == 6.0
    assert RETENTION_LINE == 0.5


def test_the_module_is_exported_from_the_member_root() -> None:
    """The surface is spelled once, at the root, the way every act in this
    member is — a caller imports ``forward`` and holds the ladder."""
    import forward

    for name in (
        "ForwardDecayPriors",
        "ForwardHalfLife",
        "DecayPriorRevision",
        "ForwardDecayPriorError",
        "FORWARD_DECAY_PRIOR_ERROR_CODE",
        "FORWARD_PRIOR_SEAM",
        "PRIOR_HALF_LIFE_DAYS",
        "PRIOR_WEIGHT",
        "RETENTION_LINE",
        "REVISED_HALF_LIFE_KEY",
        "forward_half_life",
        "revised_decay_prior",
    ):
        assert name in forward.__all__, name
        assert getattr(forward, name, None) is not None, name
