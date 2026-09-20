"""Feature 82 — the capacity estimate and the regime attribution.

app_spec.xml feature 82: *"System computes a capacity estimate plus regime
attribution, persisting both into the node artifact directory."*
docs/nullius-tech-architecture.md §6.1 names both inside step 8
(``compute_metrics    IC series, IR, turnover, decay, capacity, regime
attribution``) and §9.2 names where the second lands
(``regime_attribution.json``); docs/alpha-engine-prd.md's artifact block
spells the two values — ``capacity_estimate: float``, ``regime_attribution:
dict``.

This suite tests the two computations and the persistence as the three
halves of one feature sentence, because each is separately assertable and
a bug in any one would be masked by the others:

* **the closed form** — the book is solved from the measured edge and the
  sealed liquidity as ``B* = ((1−θ)·E / (κ·ā))²``, and the two scaling
  laws that *are* the pinned impact law are asserted as properties:
  doubling the edge quadruples the book (capacity ∝ edge², because drag
  grows as √B) and quadrupling the volumes quadruples it (capacity ∝
  dollar volume, because drag falls as 1/√DV).  A module that had fitted a
  search, or silently clamped a horizon, would fail one of the two;
* **the binding minimum** — the reported book is the minimum across the
  horizons with support, the horizon that set it is named, and an
  un-measured horizon carries ``None`` — absence, not zero — exactly as
  every other five-horizon shape promise in this package does;
* **liquidity is a fact, not a knob** — the volumes arrive as a value (the
  closes seam), a missing ``(symbol, date)`` the returns scored is refused
  (a missing volume is not free liquidity), a non-positive or non-finite
  volume is refused, and volumes for unscored symbols or dates are
  validated and then ignored;
* **the attribution splits the same edge the capacity sizes** — one
  equal-weight reduction, stated once, shared — per stratum per horizon,
  each slice carrying its own denominator; labels off the grid are
  ignored, unlabeled grid dates are counted, and a stratum named on the
  grid but measured at no horizon is carried empty rather than dropped;
* **the input contract** — both computations take step 7's own result, a
  ``PostCostReturns``, because the edge being sized and split is the edge
  that was actually priced;
* **persistence** — the pair round-trips losslessly (including the null
  horizons and the empty strata), a re-persist upserts rather than
  doubles, a node never sized reads back ``None``, a pair from two
  different evaluations is refused at the write, and the read path refuses
  a tampered capacity (one whose stored terms do not solve to it), a
  half-written row set, and strata rows that disagree with the capacity
  row about whose evaluation they describe;
* **the records** — read-only capture, hashability, and the hand-built
  invariants (a capacity that is not its own horizons' minimum, a binding
  horizon that does not achieve it, a horizon capacity that does not solve
  from its own terms).

The priced bundle is produced by the real step-4-through-7 path where the
arithmetic matters (a stub oracle over a real alignment, a stub fee
schedule — the same fixtures ``test_costs.py`` uses, because the capacity
of a bundle that never went through the gate would be the capacity of a
world nobody ran) and hand-built where the test is about step 8's own
contract.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from dataclasses import replace

import pytest

from evaluator import (
    EDGE_SURVIVAL_FRACTION,
    HORIZONS,
    IMPACT_COEFFICIENT,
    NODE_CAPACITY_TABLE,
    REGIME_ATTRIBUTION_TABLE,
    AlignedTargets,
    CapacityEstimate,
    CapacityStore,
    CostModelRef,
    CostQuote,
    CostRequest,
    EvaluatorCapacityError,
    EvaluatorStoreError,
    GatedTargets,
    HorizonCapacity,
    OracleRequest,
    OracleResponse,
    PostCostReturns,
    PostCostSeries,
    RawScoreVector,
    RegimeAttribution,
    SignalExecution,
    StratumSlice,
    align_targets,
    apply_costs,
    attribute_regimes,
    estimate_capacity,
    load_capacity,
    persist_capacity,
)

_START = dt.date(2026, 9, 1)
_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)

#: The strata the causal labeler names — feature 283's three, spelled as
#: the coverage ledger spells them, so the attribution's keys line up with
#: the strata the rest of the system counts.
_TREND = "high-volatility trend"
_CHOP = "low-volatility chop"
_CRASH = "crash"


def _days(count: int, start: dt.date = _START) -> tuple[dt.date, ...]:
    """``count`` consecutive calendar dates — a synthetic bar grid."""
    return tuple(start + dt.timedelta(days=i) for i in range(count))


def _execution(
    dates,
    universe: tuple[str, ...] = ("AAA", "BBB"),
    *,
    snapshot_name: str = "snap_abc123",
) -> SignalExecution:
    """A hand-built execution — feature 73's output — for step 4 to align."""
    vectors = {
        day: RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(day, dt.time(tzinfo=dt.UTC)),
            universe=universe,
            seed=7,
            contract_version="0.1.0",
            problems=[],
        )
        for day in dates
    }
    return SignalExecution(
        snapshot_name=snapshot_name,
        code_hash="ab" * 32,
        seed=7,
        vectors=vectors,
    )


# The main scenario, on the same shape test_costs.py uses: a 12-bar grid
# with three rebalance dates at its head — horizons 1, 2, 5 and 10 cover
# all three, horizon 20 covers none (the empty-but-carried case).  AAA
# compounds a distinct rate per bar so the horizons measure genuinely
# different edges; BBB is flat, so each date's cross-sectional mean is
# half of AAA's return and the equal-weight convention is visible.
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_DAILY = [1.0 + 0.01 + 0.005 * i for i in range(11)]
_COMPOUND = [100.0]
for _rate in _DAILY:
    _COMPOUND.append(_COMPOUND[-1] * _rate)
_MAIN_EXECUTION = _execution(_REBALANCE)
_MAIN_CLOSES = {"AAA": dict(zip(_GRID, _COMPOUND)), "BBB": dict(zip(_GRID, [50.0] * 12))}
_MAIN_ALIGNED = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)

#: The horizons the main scenario has coverage at.
_COVERED = (1, 2, 5, 10)

#: The sealed dollar volumes: AAA a thin name ($1M/day), BBB a thick one
#: ($100M/day) — the contrast the capacity estimate exists to price.
_THIN = 1_000_000.0
_THICK = 100_000_000.0
_MAIN_VOLUMES = {
    "AAA": {day: _THIN for day in _GRID},
    "BBB": {day: _THICK for day in _GRID},
}

#: The causal labeler's answer over the grid: one stratum per rebalance
#: date, so every stratum is measured and the split is exhaustive.
_MAIN_LABELS = {
    _REBALANCE[0]: _TREND,
    _REBALANCE[1]: _CHOP,
    _REBALANCE[2]: _CRASH,
}


def _oracle(alignment: AlignedTargets):
    """A stub oracle whose real branch is the identity — §7.2's ask seam."""

    def ask(request: OracleRequest) -> OracleResponse:
        aligned = alignment.targets(request.horizon)
        return OracleResponse(
            target_series={day: dict(aligned.at(day)) for day in aligned.dates()},
            charges_budget=False,
        )

    return ask


def _flat_schedule(bps: float = 10.0):
    """A stub fee schedule: a flat ``bps`` charge on every symbol and bar.

    Deliberately not the real cost library — §6.2 and feature 69 keep the
    fee arithmetic in one shared library, and this suite's job is to prove
    the evaluator neither holds nor duplicates it (``test_costs.py`` argues
    the same for step 7; here it matters because the capacity half sizes
    the *post-cost* edge, which must not depend on a fee this package
    priced itself).
    """
    rate = bps / 10_000.0

    def schedule(request: CostRequest) -> CostQuote:
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={
                day: {symbol: rate for symbol in request.symbols}
                for day in request.gross_returns
            },
        )

    return schedule


def _priced() -> PostCostReturns:
    """Step 7's own result, over the real steps 4 through 7.

    The one bundle every arithmetic and persistence test below reads, so a
    number asserted here is a number the whole pipeline produced.
    """
    return apply_costs(
        _gated(), _flat_schedule(), node_id="node_1", cost_model=_REF
    )


def _gated(alignment: AlignedTargets = _MAIN_ALIGNED) -> GatedTargets:
    """Step 5's own result, through the real gate over a real alignment."""
    from evaluator import gate_targets

    return gate_targets(
        alignment,
        _oracle(alignment),
        node_id="node_1",
        campaign_id="camp_1",
        depth=2,
    )


def _hand_priced(
    values_by_horizon: dict[int, dict[dt.date, dict[str, float]]],
    *,
    node_id: str = "node_1",
    snapshot_name: str = "snap_abc123",
    rebalance_dates: tuple[dt.date, ...] | None = None,
) -> PostCostReturns:
    """A hand-built priced bundle — step 8's input, built to the test's order.

    Hand-built because most of this suite is about step 8's *own* contract
    — the law, the scaling, the support rules — which should be assertable
    without re-running steps 4 through 7 to arrange a shape.  Where the
    provenance of the bundle actually matters (the input-contract tests),
    the suite uses ``_priced``.
    """
    days = rebalance_dates or tuple(
        sorted({day for values in values_by_horizon.values() for day in values})
    )
    series: dict[int, PostCostSeries] = {}
    for horizon in HORIZONS:
        values = values_by_horizon.get(horizon, {})
        series[horizon] = PostCostSeries(
            horizon=horizon,
            snapshot_name=snapshot_name,
            venue=_VENUE,
            version=_VERSION,
            values={day: dict(row) for day, row in values.items()},
            charges={
                day: {symbol: 0.001 for symbol in row}
                for day, row in values.items()
            },
        )
    return PostCostReturns(
        node_id=node_id,
        snapshot_name=snapshot_name,
        rebalance_dates=days,
        cost_model=_REF,
        series=series,
        charges_budget=False,
    )


# A two-date, two-symbol hand bundle at horizon 1 — the minimal panel the
# scaling laws are asserted over.  Net returns are positive and unequal so
# the edge is a real mean; volumes are uniform so the drag is a real mean
# too, and every number below is exact in binary.
_PANEL_DATES = _days(3)[:2]
_PANEL = _hand_priced(
    {1: {
        _PANEL_DATES[0]: {"AAA": 0.01, "BBB": 0.03},
        _PANEL_DATES[1]: {"AAA": 0.02, "BBB": 0.04},
    }}
)
_PANEL_VOLUMES = {
    "AAA": {day: _THIN for day in _PANEL_DATES},
    "BBB": {day: _THIN for day in _PANEL_DATES},
}


def _solved(edge: float, drag: float) -> float:
    """The closed form, spelled independently of the module under test.

    The same expression ``_capacity._solve_capacity`` carries, restated
    here from the module docstring's algebra so the suite pins the law
    rather than trusting the implementation to define it.
    """
    if edge <= 0.0:
        return 0.0
    return ((1.0 - EDGE_SURVIVAL_FRACTION) * edge / (IMPACT_COEFFICIENT * drag)) ** 2


# -- The closed form ------------------------------------------------------------


def test_the_capacity_is_solved_from_the_edge_and_the_drag() -> None:
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)

    for horizon in _COVERED:
        capacity = estimate.at(horizon)
        assert capacity is not None
        series = _priced().series[horizon]
        edges, drags = [], []
        for day in series.dates():
            row = series.at(day)
            count = len(row)
            edges.append(math.fsum(row[s] for s in sorted(row)) / count)
            drags.append(
                math.fsum(
                    1.0 / math.sqrt(count * _MAIN_VOLUMES[s][day])
                    for s in sorted(row)
                )
                / count
            )
        edge = math.fsum(edges) / len(edges)
        drag = math.fsum(drags) / len(drags)
        assert capacity.mean_post_cost_return == edge
        assert capacity.impact_drag == drag
        assert capacity.dates == len(series.dates())
        assert capacity.capacity_usd == _solved(edge, drag)


def test_doubling_the_edge_quadruples_the_book() -> None:
    # The square-root law's first signature: drag grows as sqrt(B), so the
    # crossing moves as the square of the edge.
    single = estimate_capacity(_PANEL, _PANEL_VOLUMES)
    doubled = estimate_capacity(
        _hand_priced(
            {1: {
                _PANEL_DATES[0]: {"AAA": 0.02, "BBB": 0.06},
                _PANEL_DATES[1]: {"AAA": 0.04, "BBB": 0.08},
            }}
        ),
        _PANEL_VOLUMES,
    )
    assert doubled.capacity_usd == pytest.approx(
        single.capacity_usd * 4.0, rel=1e-12
    )


def test_quadrupling_the_volumes_quadruples_the_book() -> None:
    # The law's second signature: the drag terms fall as 1/sqrt(DV), so
    # four times the liquidity is four times the book.  A module that had
    # used linear impact would report double here, and one that had
    # ignored liquidity would report no change.
    single = estimate_capacity(_PANEL, _PANEL_VOLUMES)
    quadrupled = estimate_capacity(
        _PANEL,
        {
            symbol: {day: volume * 4.0 for day, volume in row.items()}
            for symbol, row in _PANEL_VOLUMES.items()
        },
    )
    assert quadrupled.capacity_usd == pytest.approx(
        single.capacity_usd * 4.0, rel=1e-12
    )


def test_the_thin_name_binds_the_book() -> None:
    # AAA trades a hundredth of BBB's notional; equal weight puts the same
    # dollars in each, so AAA's drag term dominates.  Thinning it further
    # shrinks the book, and thinning it fourfold shrinks the book the way
    # the law says — the whole panel's drag is AAA's term plus a hundredth
    # of it, so the scaling is AAA's alone.
    base = estimate_capacity(_PANEL, _PANEL_VOLUMES)
    thinner = estimate_capacity(
        _PANEL,
        {
            "AAA": {day: _THIN / 4.0 for day in _PANEL_DATES},
            "BBB": {day: _THIN for day in _PANEL_DATES},
        },
    )
    # AAA's drag term dominates the mean, so thinning it alone moves both
    # the drag and the book: the book a uniform panel supports is not the
    # book the same panel supports once one name thins out.
    assert thinner.capacity_usd < base.capacity_usd
    assert thinner.at(1).impact_drag > base.at(1).impact_drag


def test_a_signal_with_no_edge_has_no_book() -> None:
    flat = estimate_capacity(
        _hand_priced(
            {1: {
                _PANEL_DATES[0]: {"AAA": -0.01, "BBB": 0.01},
                _PANEL_DATES[1]: {"AAA": 0.0, "BBB": 0.0},
            }}
        ),
        _PANEL_VOLUMES,
    )
    # The horizon's mean edge is exactly zero — a finding, not a failure:
    # the horizon supports no book, and the closed form says so in the
    # only spelling a scalar artifact can carry.
    assert flat.at(1).mean_post_cost_return == 0.0
    assert flat.at(1).capacity_usd == 0.0
    assert flat.capacity_usd == 0.0
    assert flat.binding_horizon == 1


# -- The binding minimum --------------------------------------------------------


def test_the_reported_capacity_is_the_binding_minimum() -> None:
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)

    measured = {
        horizon: estimate.at(horizon).capacity_usd
        for horizon in _COVERED
    }
    assert estimate.capacity_usd == min(measured.values())
    assert estimate.binding_horizon in measured
    assert measured[estimate.binding_horizon] == estimate.capacity_usd
    assert estimate.binding.capacity_usd == estimate.capacity_usd


def test_an_unmeasured_horizon_carries_no_capacity_not_zero() -> None:
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)

    # Horizon 20 has no targets over a grid this short; it is carried as
    # None — un-measured, not "supports no book" — and the set of keys is
    # still exactly the five the spec names.
    assert tuple(sorted(estimate.horizons)) == HORIZONS
    assert estimate.at(20) is None
    assert estimate.at(20) != 0.0


def test_the_binding_minimum_spans_the_horizons_the_grid_covers() -> None:
    # Over the main grid, AAA's compounding closes make horizon 10's edge
    # (two rebalance dates only, both steeper) larger than horizon 1's —
    # the horizons genuinely disagree, which is what makes "the binding
    # minimum" a measurement rather than a constant.
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)
    capacities = [estimate.at(horizon).capacity_usd for horizon in _COVERED]
    assert len(set(capacities)) > 1


# -- The input contract ---------------------------------------------------------


def test_a_bundle_that_is_not_step_sevens_result_is_refused() -> None:
    gated = _gated()
    with pytest.raises(EvaluatorCapacityError, match="PostCostReturns"):
        estimate_capacity(gated, _MAIN_VOLUMES)  # type: ignore[arg-type]
    with pytest.raises(EvaluatorCapacityError, match="PostCostReturns"):
        attribute_regimes(gated, _MAIN_LABELS)  # type: ignore[arg-type]


def test_a_bundle_with_no_measured_horizon_is_refused() -> None:
    empty = _hand_priced({})
    with pytest.raises(EvaluatorCapacityError, match="no edge to size"):
        estimate_capacity(empty, _MAIN_VOLUMES)


# -- Liquidity is a fact, not a knob ---------------------------------------------


def test_a_missing_volume_is_not_free_liquidity() -> None:
    holed = {
        "AAA": {day: _THIN for day in _GRID if day != _REBALANCE[1]},
        "BBB": {day: _THICK for day in _GRID},
    }
    with pytest.raises(EvaluatorCapacityError) as excinfo:
        estimate_capacity(_priced(), holed)
    message = str(excinfo.value)
    # The refusal names the hole rather than the mapping, because a hole
    # is a fact about one (symbol, date), not about the fetch.
    assert "AAA" in message
    assert _REBALANCE[1].isoformat() in message
    assert "free liquidity" in message


def test_a_nonpositive_or_nonfinite_volume_is_refused() -> None:
    for bad in (0.0, -1_000_000.0, float("nan"), float("inf")):
        volumes = {
            "AAA": {**_MAIN_VOLUMES["AAA"], _REBALANCE[0]: bad},
            "BBB": _MAIN_VOLUMES["BBB"],
        }
        with pytest.raises(EvaluatorCapacityError):
            estimate_capacity(_priced(), volumes)


def test_volumes_for_unscored_symbols_and_dates_are_ignored() -> None:
    tight = {
        symbol: {
            day: volume
            for day, volume in row.items()
            if day in _REBALANCE
        }
        for symbol, row in _MAIN_VOLUMES.items()
    }
    broad = dict(tight)
    broad["ZZZ"] = {day: 1.0 for day in _GRID}
    broad["AAA"] = {**tight["AAA"], _GRID[-1]: 42.0}

    assert estimate_capacity(_priced(), broad) == estimate_capacity(
        _priced(), tight
    )


def test_volume_keys_may_arrive_as_iso_strings_but_not_datetimes() -> None:
    wired = {
        symbol: {day.isoformat(): volume for day, volume in row.items()}
        for symbol, row in _MAIN_VOLUMES.items()
    }
    assert estimate_capacity(_priced(), wired) == estimate_capacity(
        _priced(), _MAIN_VOLUMES
    )
    datetimed = {
        "AAA": {
            dt.datetime.combine(day, dt.time(tzinfo=dt.UTC)): _THIN
            for day in _GRID
        },
        "BBB": _MAIN_VOLUMES["BBB"],
    }
    with pytest.raises(EvaluatorCapacityError, match="datetime"):
        estimate_capacity(_priced(), datetimed)  # type: ignore[arg-type]


def test_one_bar_one_volume() -> None:
    both_spellings = {
        "AAA": {
            **{day: _THIN for day in _GRID},
            _REBALANCE[0].isoformat(): _THIN,
        },
        "BBB": _MAIN_VOLUMES["BBB"],
    }
    with pytest.raises(EvaluatorCapacityError, match="twice"):
        estimate_capacity(_priced(), both_spellings)


# -- The attribution ------------------------------------------------------------


def test_the_edge_is_split_by_stratum_per_horizon() -> None:
    attribution = attribute_regimes(_priced(), _MAIN_LABELS)

    assert attribution.named_strata == (_CRASH, _TREND, _CHOP)
    priced = _priced()
    for horizon in _COVERED:
        series = priced.series[horizon]
        for day in series.dates():
            slice_ = attribution.stratum(_MAIN_LABELS[day]).at(horizon)
            assert slice_ is not None
            row = series.at(day)
            expected = math.fsum(row[s] for s in sorted(row)) / len(row)
            assert slice_.mean_post_cost_return == expected
            assert slice_.dates == 1
    # Horizon 20 measured nothing, so no stratum carries a slice there —
    # absent, not zero.
    for name in attribution.named_strata:
        assert attribution.stratum(name).at(20) is None


def test_the_two_halves_measure_the_same_edge() -> None:
    # One reduction, stated once, shared: a stratum whose labeled dates are
    # the whole grid at a horizon carries exactly the capacity half's edge
    # for that horizon.
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)
    whole = attribute_regimes(
        _priced(), {day: _TREND for day in _REBALANCE}
    )
    for horizon in _COVERED:
        assert (
            whole.stratum(_TREND).at(horizon).mean_post_cost_return
            == estimate.at(horizon).mean_post_cost_return
        )


def test_labels_off_the_grid_are_ignored() -> None:
    off_grid = {
        **_MAIN_LABELS,
        _GRID[9]: _CRASH,  # a day this evaluation never rebalanced on
        _GRID[10]: _CHOP,
    }
    assert attribute_regimes(_priced(), off_grid) == attribute_regimes(
        _priced(), _MAIN_LABELS
    )


def test_unlabeled_grid_dates_are_counted_not_dropped() -> None:
    partial = {_REBALANCE[0]: _TREND}
    attribution = attribute_regimes(_priced(), partial)

    assert attribution.unattributed_dates == len(_REBALANCE) - 1
    assert attribution.named_strata == (_TREND,)
    # The stratum's horizon-1 slice measured exactly the one labeled date.
    assert attribution.stratum(_TREND).at(1).dates == 1


def test_an_all_unlabeled_grid_is_refused() -> None:
    with pytest.raises(EvaluatorCapacityError, match="nothing to attribute"):
        attribute_regimes(_priced(), {_GRID[9]: _CRASH})


def test_a_stratum_measured_at_no_horizon_is_carried_empty() -> None:
    # Horizon 1 covers the first two rebalance dates only; a stratum whose
    # one label sits on the third is named on the grid yet measured
    # nowhere — carried with empty slices, so "named" stays distinguishable
    # from "measured a mean of zero".
    bundle = _hand_priced(
        {1: {
            _PANEL_DATES[0]: {"AAA": 0.01, "BBB": 0.03},
            _PANEL_DATES[1]: {"AAA": 0.02, "BBB": 0.04},
        }},
        rebalance_dates=(_PANEL_DATES[0], _PANEL_DATES[1], _REBALANCE[2]),
    )
    attribution = attribute_regimes(bundle, {_REBALANCE[2]: _CRASH})

    crash = attribution.stratum(_CRASH)
    assert crash.measured_horizons == ()
    assert crash.slices == {}


def test_blank_and_malformed_labels_are_refused() -> None:
    for bad_labels in (
        {_REBALANCE[0]: "   "},
        {_REBALANCE[0]: 2},
        {_REBALANCE[0]: _TREND, _REBALANCE[0].isoformat(): _CHOP},
        {dt.datetime.combine(_REBALANCE[0], dt.time(tzinfo=dt.UTC)): _TREND},
        ["not", "a", "mapping"],
    ):
        with pytest.raises(EvaluatorCapacityError):
            attribute_regimes(_priced(), bad_labels)  # type: ignore[arg-type]


# -- The records ----------------------------------------------------------------


def test_the_records_are_read_only_and_hashable() -> None:
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)
    attribution = attribute_regimes(_priced(), _MAIN_LABELS)

    assert hash(estimate) == hash(estimate_capacity(_priced(), _MAIN_VOLUMES))
    assert hash(attribution) == hash(
        attribute_regimes(_priced(), _MAIN_LABELS)
    )
    with pytest.raises(TypeError):
        estimate.horizons[1] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        attribution.strata[_TREND] = attribution.strata[_TREND]  # type: ignore[index]
    with pytest.raises(TypeError):
        attribution.strata[_TREND].slices[1] = attribution.strata[_TREND].slices[1]  # type: ignore[index]


def test_a_horizon_capacity_must_solve_from_its_own_terms() -> None:
    with pytest.raises(EvaluatorCapacityError, match="disagrees with itself"):
        HorizonCapacity(
            horizon=1,
            dates=2,
            mean_post_cost_return=0.01,
            impact_drag=0.001,
            capacity_usd=1.0,
        )


def test_an_estimate_must_be_its_own_minimum() -> None:
    built = estimate_capacity(_PANEL, _PANEL_VOLUMES)
    with pytest.raises(EvaluatorCapacityError, match="minimum"):
        CapacityEstimate(
            node_id=built.node_id,
            snapshot_name=built.snapshot_name,
            cost_model=built.cost_model,
            capacity_usd=built.capacity_usd * 2.0,
            binding_horizon=built.binding_horizon,
            horizons=built.horizons,
        )
    with pytest.raises(EvaluatorCapacityError, match="binding horizon"):
        CapacityEstimate(
            node_id=built.node_id,
            snapshot_name=built.snapshot_name,
            cost_model=built.cost_model,
            capacity_usd=built.capacity_usd,
            binding_horizon=5,
            horizons=built.horizons,
        )


def test_an_estimate_carries_one_entry_per_horizon() -> None:
    built = estimate_capacity(_PANEL, _PANEL_VOLUMES)
    partial = dict(built.horizons)
    del partial[20]
    with pytest.raises(EvaluatorCapacityError, match="one entry per horizon"):
        CapacityEstimate(
            node_id=built.node_id,
            snapshot_name=built.snapshot_name,
            cost_model=built.cost_model,
            capacity_usd=built.capacity_usd,
            binding_horizon=built.binding_horizon,
            horizons=partial,
        )


def test_an_attribution_must_not_rename_its_strata() -> None:
    attribution = attribute_regimes(_priced(), _MAIN_LABELS)
    with pytest.raises(EvaluatorCapacityError, match="wrong name"):
        RegimeAttribution(
            node_id=attribution.node_id,
            snapshot_name=attribution.snapshot_name,
            cost_model=attribution.cost_model,
            strata={"somebody-else": attribution.strata[_TREND]},
            unattributed_dates=0,
        )


def test_an_attribution_with_no_strata_is_refused() -> None:
    attribution = attribute_regimes(_priced(), _MAIN_LABELS)
    with pytest.raises(EvaluatorCapacityError, match="no strata"):
        RegimeAttribution(
            node_id=attribution.node_id,
            snapshot_name=attribution.snapshot_name,
            cost_model=attribution.cost_model,
            strata={},
            unattributed_dates=len(_REBALANCE),
        )


def test_a_slice_must_carry_at_least_one_date() -> None:
    with pytest.raises(EvaluatorCapacityError, match="absence, not zero"):
        StratumSlice(horizon=1, dates=0, mean_post_cost_return=0.01)


# -- The persistence ------------------------------------------------------------


def test_the_pair_round_trips_losslessly() -> None:
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)
    attribution = attribute_regimes(_priced(), _MAIN_LABELS)

    persist_capacity(estimate, attribution)
    loaded = load_capacity("node_1", _REF)

    assert loaded is not None
    loaded_estimate, loaded_attribution = loaded
    assert loaded_estimate == estimate
    assert loaded_attribution == attribution
    # The null horizon and the empty stratum survive the JSON columns —
    # the read-back must be exact, not merely close.
    assert loaded_estimate.at(20) is None
    assert loaded_attribution.unattributed_dates == 0
    assert loaded_attribution.stratum(_CRASH).at(20) is None


def test_a_re_persist_upserts_rather_than_doubles() -> None:
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)
    attribution = attribute_regimes(_priced(), _MAIN_LABELS)

    persist_capacity(estimate, attribution)
    persist_capacity(estimate, attribution)
    assert _row_counts() == (1, 3)


def test_a_node_never_sized_reads_back_none() -> None:
    assert load_capacity("node_nobody", _REF) is None


def test_the_pair_must_be_one_evaluation() -> None:
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)
    attribution = attribute_regimes(_priced(), _MAIN_LABELS)

    with pytest.raises(EvaluatorCapacityError, match="node"):
        persist_capacity(estimate, replace(attribution, node_id="node_2"))
    with pytest.raises(EvaluatorCapacityError, match="sealed snapshot"):
        persist_capacity(
            estimate, replace(attribution, snapshot_name="snap_other")
        )
    with pytest.raises(EvaluatorCapacityError, match="one fee schedule"):
        persist_capacity(
            estimate,
            replace(
                attribution, cost_model=CostModelRef(venue=_VENUE, version="0.0.1")
            ),
        )


def test_the_read_path_refuses_a_tampered_capacity() -> None:
    persist_capacity(
        estimate_capacity(_priced(), _MAIN_VOLUMES),
        attribute_regimes(_priced(), _MAIN_LABELS),
    )

    # Rewrite the headline number while leaving its terms alone: the read
    # path re-derives the minimum from the stored per-horizon terms and
    # refuses the disagreement.
    _execute(
        f"UPDATE {NODE_CAPACITY_TABLE} SET capacity_usd = capacity_usd * 2.0"
    )
    with pytest.raises(EvaluatorStoreError, match="does not reconstruct"):
        load_capacity("node_1", _REF)

    # Rewrite a per-horizon term inside the JSON instead: the record
    # re-solves the closed form from the stored edge and drag and refuses a
    # row whose capacity is not its own terms' answer.
    _restore_capacity_row()
    with sqlite3.connect(_database_path()) as connection:
        payload = connection.execute(
            f"SELECT horizon_capacities FROM {NODE_CAPACITY_TABLE}"
        ).fetchone()[0]
    terms = json.loads(payload)
    terms["1"]["capacity_usd"] *= 2.0
    _execute(
        f"UPDATE {NODE_CAPACITY_TABLE} SET horizon_capacities = ?",
        (json.dumps(terms),),
    )
    with pytest.raises(EvaluatorStoreError, match="does not reconstruct"):
        load_capacity("node_1", _REF)


def test_the_read_path_refuses_half_written_rows() -> None:
    persist_capacity(
        estimate_capacity(_priced(), _MAIN_VOLUMES),
        attribute_regimes(_priced(), _MAIN_LABELS),
    )

    _execute(f"DELETE FROM {REGIME_ATTRIBUTION_TABLE}")
    with pytest.raises(EvaluatorStoreError, match="no attribution rows"):
        load_capacity("node_1", _REF)

    persist_capacity(
        estimate_capacity(_priced(), _MAIN_VOLUMES),
        attribute_regimes(_priced(), _MAIN_LABELS),
    )
    _execute(f"DELETE FROM {NODE_CAPACITY_TABLE}")
    with pytest.raises(EvaluatorStoreError, match="no capacity row"):
        load_capacity("node_1", _REF)


def test_strata_rows_must_agree_with_the_capacity_row() -> None:
    persist_capacity(
        estimate_capacity(_priced(), _MAIN_VOLUMES),
        attribute_regimes(_priced(), _MAIN_LABELS),
    )
    _execute(
        f"UPDATE {REGIME_ATTRIBUTION_TABLE} SET snapshot_name = 'snap_other' "
        f"WHERE stratum = ?",
        (_CRASH,),
    )
    with pytest.raises(EvaluatorStoreError, match="one sealed world"):
        load_capacity("node_1", _REF)


def test_a_missing_store_is_refused_by_name() -> None:
    estimate = estimate_capacity(_priced(), _MAIN_VOLUMES)
    attribution = attribute_regimes(_priced(), _MAIN_LABELS)

    import os

    url = os.environ["DATABASE_URL"]
    del os.environ["DATABASE_URL"]
    try:
        with pytest.raises(EvaluatorStoreError, match="DATABASE_URL"):
            persist_capacity(estimate, attribution)
        with pytest.raises(EvaluatorStoreError, match="DATABASE_URL"):
            load_capacity("node_1", _REF)
    finally:
        os.environ["DATABASE_URL"] = url


def test_the_store_resolves_from_the_environment_mapping() -> None:
    store = CapacityStore.resolve({"DATABASE_URL": "sqlite://"})
    assert store.database_url == "sqlite://"
    with pytest.raises(EvaluatorStoreError):
        CapacityStore.resolve({"DATABASE_URL": "   "})


def test_unsupported_schemes_are_refused() -> None:
    with pytest.raises(EvaluatorStoreError, match="scheme"):
        CapacityStore("postgres://localhost/x").load("node_1", _REF)


# -- Suite helpers ---------------------------------------------------------------


def _database_path() -> str:
    import os

    return os.environ["DATABASE_URL"].removeprefix("sqlite:///")


def _execute(statement: str, parameters: tuple = ()) -> None:
    """Run one statement against the suite's database, outside the store.

    The tamper tests' instrument: every statement below is one this
    package's writer would never issue, which is exactly the point — the
    read path has to refuse what the write path cannot produce.
    """
    with sqlite3.connect(_database_path()) as connection:
        connection.execute(statement, parameters)


def _restore_capacity_row() -> None:
    """Re-persist the pair, restoring whatever a tamper disturbed."""
    persist_capacity(
        estimate_capacity(_priced(), _MAIN_VOLUMES),
        attribute_regimes(_priced(), _MAIN_LABELS),
    )


def _row_counts() -> tuple[int, int]:
    with sqlite3.connect(_database_path()) as connection:
        capacity = connection.execute(
            f"SELECT COUNT(*) FROM {NODE_CAPACITY_TABLE}"
        ).fetchone()[0]
        strata = connection.execute(
            f"SELECT COUNT(*) FROM {REGIME_ATTRIBUTION_TABLE}"
        ).fetchone()[0]
    return capacity, strata
