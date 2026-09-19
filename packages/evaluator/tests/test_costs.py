"""Feature 79 — applying the cost model to the aligned returns.

app_spec.xml feature 79: *"System applies the cost model to the aligned
returns, persisting a post-cost signal return series per symbol."*
docs/nullius-tech-architecture.md §6.1 names the step — ``7. apply_costs
venue fee schedule + queue-position fill model`` — and §9.2 names what it
leaves behind (``signal_returns.parquet``, "per-symbol, per-period,
post-cost ← enables ir_marginal").

This suite tests the application and the persistence as the two halves of
one feature sentence, because each is separately assertable and a bug in
either would be masked by the other:

* **the arithmetic** — ``post_cost = gross − charge``, per symbol, per bar,
  per horizon, with the charge carried beside the net so the row explains
  the difference;
* **one series per horizon** — the result carries exactly the five horizons
  the spec names, always, including a horizon whose coverage is empty;
* **the cost model is the one shared library** — the fee arithmetic is an
  *injected* seam, so this module computes no fee of its own. The tests
  drive it with a stub schedule, which is the only way to state that as a
  property: a member that had hard-coded 10 bps would fail to price a
  schedule it was handed;
* **one evaluation prices one schedule** — a quote answered under a
  different ``(venue, version)`` is refused, because §15 treats a changed
  cost model as its own failure case;
* **the support rule** — a quote that does not live on exactly the charged
  support is refused in both directions, and a *missing* charge is refused
  rather than priced at zero ("a missing charge is not a free trade");
* **the input contract** — a bundle that is not step 5's own result, a
  schedule that is not callable, a node id that is not a name, a cost model
  that does not resolve to a pair, and a bundle with nothing chargeable;
* **persistence** — the series round-trips through the store losslessly
  (including the evaluation's grid, which cannot be rebuilt from the rows),
  the grain is one row per symbol per period, a re-persist upserts rather
  than doubles, a read-back of a node never costed is ``None``, and a stored
  row whose net does not equal its own gross less its own charge is refused
  as a tamper rather than loaded as a plausible-looking lie;
* **the records** — read-only capture, hashability, and the hand-built
  record invariants.

The gated bundle is produced by the real step-5 path where it matters (a
stub oracle over a real alignment) and hand-built where the test is about
step 7's own contract — the same split ``test_gate.py`` uses.
"""

from __future__ import annotations

import datetime as dt
import math
import sqlite3

import pytest

from evaluator import (
    HORIZONS,
    SIGNAL_RETURNS_GRID_TABLE,
    SIGNAL_RETURNS_TABLE,
    AlignedTargets,
    CostModelRef,
    CostQuote,
    CostRequest,
    EvaluatorCostError,
    EvaluatorStoreError,
    GatedTargets,
    OracleRequest,
    OracleResponse,
    PostCostReturns,
    PostCostSeries,
    PostCostStore,
    RawScoreVector,
    SignalExecution,
    TargetSeries,
    align_targets,
    apply_costs,
    cost_model_ref,
    gate_targets,
    load_signal_returns,
    persist_signal_returns,
)

_START = dt.date(2026, 9, 1)
_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)


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


def _closes(
    by_symbol: dict[str, list[float]], days: tuple[dt.date, ...]
) -> dict[str, dict[dt.date, float]]:
    """A fetched closes mapping — one close per symbol per grid day."""
    return {
        symbol: dict(zip(days, prices)) for symbol, prices in by_symbol.items()
    }


# The main scenario.  A 12-bar grid, three rebalance dates at its head —
# so horizons 1, 2 and 5 cover all three, horizon 10 covers the first two,
# and horizon 20 covers none (the empty-but-carried case step 7 must not
# ask a schedule about).  AAA compounds a distinct rate per bar so the gross
# rows differ across dates, which is what lets the arithmetic tests tell one
# bar's charge from another's.
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_DAILY = [1.0 + 0.01 + 0.005 * i for i in range(11)]
_COMPOUND = [100.0]
for _rate in _DAILY:
    _COMPOUND.append(_COMPOUND[-1] * _rate)
_MAIN_EXECUTION = _execution(_REBALANCE)
_MAIN_CLOSES = _closes({"AAA": _COMPOUND, "BBB": [50.0] * 12}, _GRID)
_MAIN = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)

#: The horizons the main scenario has coverage at.
_COVERED = (1, 2, 5, 10)


def _oracle(alignment: AlignedTargets):
    """A stub oracle whose real branch is the identity — §7.2's ask seam."""

    def ask(request: OracleRequest) -> OracleResponse:
        aligned = alignment.targets(request.horizon)
        return OracleResponse(
            target_series={day: dict(aligned.at(day)) for day in aligned.dates()},
            charges_budget=False,
        )

    return ask


def _gated(alignment: AlignedTargets = _MAIN) -> GatedTargets:
    """Step 5's own result, through the real gate over a real alignment."""
    return gate_targets(
        alignment,
        _oracle(alignment),
        node_id="node_1",
        campaign_id="camp_1",
        depth=2,
    )


def _flat_schedule(bps: float = 10.0):
    """A stub fee schedule: a flat ``bps`` charge on every symbol and bar.

    Deliberately not the real cost library — §6.2 and feature 69 require the
    fee arithmetic to live in one shared library, and this suite's job is to
    prove the evaluator neither holds nor duplicates it.  The stub is what
    makes that assertable: the charge the evaluator applies is the charge it
    was *told*, whatever number the test picks.
    """
    calls: list[CostRequest] = []
    rate = bps / 10_000.0

    def schedule(request: CostRequest) -> CostQuote:
        calls.append(request)
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={
                day: {symbol: rate for symbol in request.symbols}
                for day in request.gross_returns
            },
        )

    return schedule, calls


def _hand_bundle(
    *,
    snapshot_name: str = "snap_abc123",
    horizon_values: dict[int, dict[dt.date, dict[str, float]]] | None = None,
    rebalance_dates: tuple[dt.date, ...] | None = None,
    charges_budget: bool = False,
) -> GatedTargets:
    """A hand-built gated bundle — step 7's input, built to the test's order.

    Hand-built rather than gated because most of this suite is about step
    7's *own* contract, which should be assertable without re-running steps
    4 and 5 to arrange a shape.  Where the gate's ruling actually matters
    (that a non-gated value is refused) the test uses ``_gated``.
    """
    values = horizon_values or {
        horizon: {
            _REBALANCE[0]: {"AAA": 0.01, "BBB": -0.02},
            _REBALANCE[1]: {"AAA": 0.03, "BBB": 0.04},
        }
        for horizon in HORIZONS
    }
    series = {
        horizon: TargetSeries(
            horizon=horizon,
            snapshot_name=snapshot_name,
            values=values.get(horizon, {}),
        )
        for horizon in HORIZONS
    }
    return GatedTargets(
        snapshot_name=snapshot_name,
        rebalance_dates=rebalance_dates or _REBALANCE,
        series=series,
        charges_budget=charges_budget,
    )


def _returns_columns(database_url: str) -> list[tuple]:
    """Every raw row of the signal-returns table, in a stable order."""
    parsed = database_url.removeprefix("sqlite:///")
    with sqlite3.connect(parsed) as connection:
        return connection.execute(
            f"SELECT horizon, rebalance_date, symbol, gross_return, charge, "
            f"post_cost_return FROM {SIGNAL_RETURNS_TABLE} "
            "ORDER BY horizon, rebalance_date, symbol"
        ).fetchall()


# -- The arithmetic ------------------------------------------------------------


def test_the_post_cost_return_is_the_gross_less_the_charge() -> None:
    schedule, _ = _flat_schedule(bps=10.0)
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)

    gross = _MAIN.targets(1).values
    net = out.returns(1)
    for day, row in gross.items():
        for symbol, value in row.items():
            assert net[day][symbol] == pytest.approx(value - 0.001)


def test_the_charge_is_carried_beside_the_net_so_the_row_explains_itself() -> None:
    # "how much did the fee schedule eat?" is the first question anyone asks
    # of a cost-adjusted number, and a series storing only the net cannot
    # answer it without re-running a fee assumption that may have moved.
    schedule, _ = _flat_schedule(bps=25.0)
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)

    day = _REBALANCE[0]
    assert dict(out.charges(1)[day]) == {"AAA": 0.0025, "BBB": 0.0025}
    for symbol in ("AAA", "BBB"):
        assert out.returns(1)[day][symbol] == pytest.approx(
            _MAIN.targets(1).at(day)[symbol] - 0.0025
        )


def test_the_charge_the_schedule_states_is_the_charge_applied() -> None:
    # The load-bearing "no second implementation" property: the evaluator
    # applies the number it was handed, whatever it is.  A member holding
    # its own 10 bps constant would answer with that constant here.
    schedule, _ = _flat_schedule(bps=7.5)
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    assert out.charges(1)[_REBALANCE[0]]["AAA"] == pytest.approx(0.00075)


def test_a_maker_rebate_is_priced_rather_than_refused() -> None:
    # A negative charge (a rebate) is a real venue feature and the spec
    # never rules it out; refusing one would be inventing a fee policy
    # inside the evaluator, which is the one place that must not hold one.
    schedule, _ = _flat_schedule(bps=-2.0)
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    assert out.charges(1)[_REBALANCE[0]]["AAA"] == pytest.approx(-0.0002)
    assert out.returns(1)[_REBALANCE[0]]["AAA"] == pytest.approx(
        _MAIN.targets(1).at(_REBALANCE[0])["AAA"] + 0.0002
    )


def test_a_zero_charge_leaves_the_gross_return_untouched() -> None:
    schedule, _ = _flat_schedule(bps=0.0)
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    for day, row in _MAIN.targets(1).values.items():
        for symbol, value in row.items():
            assert out.returns(1)[day][symbol] == value


def test_the_series_covers_exactly_the_dates_the_gate_answered_on() -> None:
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    for horizon in HORIZONS:
        assert out.costed(horizon).dates() == _MAIN.targets(horizon).dates()


# -- The ask -------------------------------------------------------------------


def test_the_schedule_is_asked_once_per_covered_horizon() -> None:
    schedule, calls = _flat_schedule()
    apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)

    # Horizon 20 has nothing aligned, so there is nothing to charge and no
    # ask: the five-horizon shape promise is kept by an empty series, not by
    # a question about nothing.
    assert [call.horizon for call in calls] == list(_COVERED)


def test_the_request_carries_the_evaluations_own_terms() -> None:
    schedule, calls = _flat_schedule()
    apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)

    first = calls[0]
    assert first.node_id == "node_1"
    assert (first.venue, first.version) == (_VENUE, _VERSION)
    assert first.horizon == 1
    assert first.symbols == ("AAA", "BBB")
    aligned = _MAIN.targets(1).dates()
    assert first.date_range == (aligned[0], aligned[-1])


def test_the_request_carries_the_gross_returns_themselves() -> None:
    # A schedule that cannot see the returns cannot charge a model that
    # depends on them, and one handed only a summary would answer for a
    # world nobody ran.
    schedule, calls = _flat_schedule()
    apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    day = _REBALANCE[0]
    assert dict(calls[0].gross_returns[day]) == dict(
        _MAIN.targets(1).at(day)
    )


def test_a_request_restates_the_support_of_the_series_it_carries() -> None:
    day = _REBALANCE[0]
    request = CostRequest(
        node_id="node_1",
        venue=_VENUE,
        version=_VERSION,
        horizon=1,
        symbols=("AAA", "BBB"),
        date_range=(day, day),
        gross_returns={day: {"AAA": 0.01, "BBB": -0.02}},
    )
    assert request.symbols == ("AAA", "BBB")
    assert request.venue == _VENUE


def test_a_request_cannot_claim_a_date_range_its_returns_do_not_span() -> None:
    day = _REBALANCE[0]
    with pytest.raises(EvaluatorCostError, match="producer that drifted"):
        CostRequest(
            node_id="node_1",
            venue=_VENUE,
            version=_VERSION,
            horizon=1,
            symbols=("AAA",),
            date_range=(_REBALANCE[0], _REBALANCE[1]),
            gross_returns={day: {"AAA": 0.01}},
        )


def test_a_request_cannot_name_symbols_its_returns_do_not_carry() -> None:
    day = _REBALANCE[0]
    with pytest.raises(EvaluatorCostError, match="same support"):
        CostRequest(
            node_id="node_1",
            venue=_VENUE,
            version=_VERSION,
            horizon=1,
            symbols=("AAA", "BBB"),
            date_range=(day, day),
            gross_returns={day: {"AAA": 0.01}},
        )


def test_a_request_may_use_the_wire_spelling_of_its_dates() -> None:
    # §7.2 and this seam are service boundaries, and ISO is the wire
    # spelling — the same courtesy the gate extends its own answers.  The
    # numbers, though, are numbers: YAML's ``1e-4`` arrives parsed, and a
    # string that flowed this far unparsed would be a producer bug this
    # module should not paper over with a coercion.
    request = CostRequest(
        node_id="node_1",
        venue=_VENUE,
        version=_VERSION,
        horizon=1,
        symbols=("AAA",),
        date_range=(_REBALANCE[0], _REBALANCE[0]),
        gross_returns={_REBALANCE[0].isoformat(): {"AAA": 0.01}},
    )
    assert request.gross_returns[_REBALANCE[0]]["AAA"] == 0.01


def test_a_request_refuses_a_gross_return_spelled_as_a_string() -> None:
    day = _REBALANCE[0]
    with pytest.raises(EvaluatorCostError, match="must be a number"):
        CostRequest(
            node_id="node_1",
            venue=_VENUE,
            version=_VERSION,
            horizon=1,
            symbols=("AAA",),
            date_range=(day, day),
            gross_returns={day: {"AAA": "0.01"}},
        )


def test_a_request_refuses_an_empty_gross_series() -> None:
    with pytest.raises(EvaluatorCostError, match="asks a fee schedule about nothing"):
        CostRequest(
            node_id="node_1",
            venue=_VENUE,
            version=_VERSION,
            horizon=1,
            symbols=("AAA",),
            date_range=(_REBALANCE[0], _REBALANCE[0]),
            gross_returns={},
        )


def test_a_request_refuses_a_non_finite_gross_return() -> None:
    day = _REBALANCE[0]
    with pytest.raises(EvaluatorCostError, match="not finite"):
        CostRequest(
            node_id="node_1",
            venue=_VENUE,
            version=_VERSION,
            horizon=1,
            symbols=("AAA",),
            date_range=(day, day),
            gross_returns={day: {"AAA": math.nan}},
        )


def test_a_schedule_that_raises_propagates() -> None:
    # The seam's failures are its own, like an HTTP client's; dressing them
    # as cost errors would hide the seam.
    class Boom(RuntimeError):
        pass

    def exploding(request: CostRequest) -> CostQuote:
        raise Boom("the schedule is not reachable")

    with pytest.raises(Boom):
        apply_costs(_gated(), exploding, node_id="node_1", cost_model=_REF)


# -- One series per horizon ----------------------------------------------------


def test_the_result_carries_one_series_per_horizon_always() -> None:
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    assert tuple(sorted(out.series)) == HORIZONS
    assert out.horizons == HORIZONS


def test_a_horizon_with_nothing_aligned_is_carried_empty() -> None:
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    empty = out.costed(20)
    assert empty.horizon == 20
    assert empty.dates() == ()
    assert empty.at(_REBALANCE[0]) == {}


def test_the_budget_directive_survives_step_seven() -> None:
    # §7.2's one crossing bit is carried *through* step 7, untouched.  Step 7
    # has no use for it, but the later steps receive this record rather than
    # the gate's — and feature 84's trial charge is written precisely when an
    # evaluation went wrong, so "ask the gate again" is not available to it.
    # Losing the bit here would be unrecoverable, not merely inconvenient.
    gated = _hand_bundle(charges_budget=True)
    schedule, _ = _flat_schedule()
    out = apply_costs(gated, schedule, node_id="node_1", cost_model=_REF)
    assert out.charges_budget is True

    gated = _hand_bundle(charges_budget=False)
    out = apply_costs(gated, schedule, node_id="node_1", cost_model=_REF)
    assert out.charges_budget is False


def test_the_bundle_refuses_a_directive_that_is_not_a_bool() -> None:
    # A bit is not an int that happens to be 0 or 1 — the gate's own rule,
    # restated on the record that forwards it.
    series = {
        horizon: PostCostSeries(
            horizon=horizon,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={},
            charges={},
        )
        for horizon in HORIZONS
    }
    with pytest.raises(EvaluatorCostError, match="charges_budget must be a bool"):
        PostCostReturns(
            node_id="node_1",
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            cost_model=_REF,
            series=series,
            charges_budget=1,  # type: ignore[arg-type]
        )


def test_the_bundle_carries_the_gates_own_grid_and_snapshot() -> None:
    schedule, _ = _flat_schedule()
    gated = _gated()
    out = apply_costs(gated, schedule, node_id="node_1", cost_model=_REF)
    assert out.snapshot_name == gated.snapshot_name
    assert out.rebalance_dates == gated.rebalance_dates
    assert out.node_id == "node_1"


def test_the_bundle_is_stamped_with_the_cost_model_that_priced_it() -> None:
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    assert out.cost_model == _REF
    assert out.cost_model_reference == f"{_VENUE}/{_VERSION}"


def test_costing_the_same_input_twice_is_the_same_value() -> None:
    schedule, _ = _flat_schedule()
    first = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    second = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    assert first == second
    assert hash(first) == hash(second)


def test_costing_the_alignment_directly_is_refused() -> None:
    # Costs are applied to the world the evaluation is actually measured
    # in.  A node whose targets were block-permuted was measured against a
    # different world, and charging the real returns while the metrics
    # measure the permuted ones would price one experiment and report
    # another — which is why feature 79 depends on feature 76, not 75.
    schedule, _ = _flat_schedule()
    with pytest.raises(EvaluatorCostError, match="GatedTargets"):
        apply_costs(_MAIN, schedule, node_id="node_1", cost_model=_REF)


def test_costing_a_raw_mapping_is_refused() -> None:
    schedule, _ = _flat_schedule()
    with pytest.raises(EvaluatorCostError, match="GatedTargets"):
        apply_costs({1: {}}, schedule, node_id="node_1", cost_model=_REF)


def test_a_bundle_with_nothing_chargeable_is_refused() -> None:
    # Five empty series would report a costed evaluation for one that
    # measured nothing.
    empty = _hand_bundle(horizon_values={horizon: {} for horizon in HORIZONS})
    schedule, calls = _flat_schedule()
    with pytest.raises(EvaluatorCostError, match="nothing to measure|no computable target"):
        apply_costs(empty, schedule, node_id="node_1", cost_model=_REF)
    assert calls == []


def test_an_uncallable_schedule_is_refused() -> None:
    with pytest.raises(EvaluatorCostError, match="must be a callable"):
        apply_costs(_gated(), "not callable", node_id="node_1", cost_model=_REF)


def test_a_node_id_that_is_not_a_name_is_refused() -> None:
    schedule, _ = _flat_schedule()
    with pytest.raises(EvaluatorCostError, match="node_id"):
        apply_costs(_gated(), schedule, node_id="   ", cost_model=_REF)


def test_a_schedule_that_returns_something_else_is_refused() -> None:
    with pytest.raises(EvaluatorCostError, match="must return a CostQuote"):
        apply_costs(
            _gated(),
            lambda request: {"charges": {}},
            node_id="node_1",
            cost_model=_REF,
        )


def test_an_accessor_refuses_a_horizon_outside_the_spec_set() -> None:
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    with pytest.raises(EvaluatorCostError, match="not one of the horizons"):
        out.costed(3)


# -- One evaluation prices one cost model --------------------------------------


def test_a_quote_answered_under_another_cost_model_is_refused() -> None:
    # §15's failure table treats a changed cost model as its own case:
    # applying another schedule's charges would file these returns under one
    # cost model's provenance while computing them with another's.
    def other_schedule(request: CostRequest) -> CostQuote:
        return CostQuote(
            venue="kraken_spot",
            version=_VERSION,
            costs={
                day: {symbol: 0.001 for symbol in request.symbols}
                for day in request.gross_returns
            },
        )

    with pytest.raises(EvaluatorCostError, match="one cost model"):
        apply_costs(_gated(), other_schedule, node_id="node_1", cost_model=_REF)


def test_a_quote_answered_under_another_version_is_refused() -> None:
    def newer_schedule(request: CostRequest) -> CostQuote:
        return CostQuote(
            venue=_VENUE,
            version="2027.01.1",
            costs={
                day: {symbol: 0.001 for symbol in request.symbols}
                for day in request.gross_returns
            },
        )

    with pytest.raises(EvaluatorCostError, match="one cost model"):
        apply_costs(_gated(), newer_schedule, node_id="node_1", cost_model=_REF)


def test_the_cost_model_may_arrive_as_the_shared_librarys_config() -> None:
    # §6.2's shared library resolves its own identity record
    # (cost_model.config.CostModelConfig, feature 59) — and this member must
    # not import the cost-model package to read it.  Duck-typing the pair is
    # what makes the seam usable without creating a package dependency, or
    # tempting a second (venue, version) reader into existing beside the
    # library's own.
    class ResolvedConfig:
        venue = _VENUE
        version = _VERSION
        source = "/z0/cost_model.yaml"

    schedule, calls = _flat_schedule()
    out = apply_costs(
        _gated(), schedule, node_id="node_1", cost_model=ResolvedConfig()
    )
    assert out.cost_model == _REF
    assert calls[0].venue == _VENUE


def test_a_cost_model_without_a_pair_is_refused() -> None:
    with pytest.raises(EvaluatorCostError, match="venue, version"):
        cost_model_ref({"venue": _VENUE})


def test_a_blank_venue_is_refused() -> None:
    with pytest.raises(EvaluatorCostError, match="blank"):
        CostModelRef(venue="  ", version=_VERSION)


def test_a_non_string_version_is_refused() -> None:
    with pytest.raises(EvaluatorCostError, match="must be a string"):
        CostModelRef(venue=_VENUE, version=1.0)


def test_a_cost_model_ref_coerces_to_itself() -> None:
    assert cost_model_ref(_REF) is _REF


# -- The support rule ----------------------------------------------------------


def _schedule_quoting(quote_map):
    """A stub schedule answering with an explicit ``{date: {symbol: charge}}``."""

    def schedule(request: CostRequest) -> CostQuote:
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs=quote_map(request),
        )

    return schedule


def test_a_missing_charge_is_refused_rather_than_priced_at_zero() -> None:
    # The tempting repair — price the missing bar at zero — would understate
    # cost in the one direction the whole method cares about, and would do it
    # silently, inside the artifact replay reads back.
    def quote_map(request: CostRequest) -> dict:
        days = sorted(request.gross_returns)
        return {
            day: {symbol: 0.001 for symbol in request.symbols}
            for day in days[:-1]
        }

    with pytest.raises(EvaluatorCostError, match="not a free trade"):
        apply_costs(
            _gated(), _schedule_quoting(quote_map), node_id="n", cost_model=_REF
        )


def test_a_charge_for_an_unscored_date_is_refused() -> None:
    def quote_map(request: CostRequest) -> dict:
        days = sorted(request.gross_returns)
        quoted = {day: {s: 0.001 for s in request.symbols} for day in days}
        quoted[dt.date(2030, 1, 1)] = {s: 0.001 for s in request.symbols}
        return quoted

    with pytest.raises(EvaluatorCostError, match="scored no returns on"):
        apply_costs(
            _gated(), _schedule_quoting(quote_map), node_id="n", cost_model=_REF
        )


def test_a_missing_symbol_charge_is_refused() -> None:
    def quote_map(request: CostRequest) -> dict:
        return {
            day: {request.symbols[0]: 0.001} for day in request.gross_returns
        }

    with pytest.raises(EvaluatorCostError, match="not a free trade"):
        apply_costs(
            _gated(), _schedule_quoting(quote_map), node_id="n", cost_model=_REF
        )


def test_a_charge_for_an_unscored_symbol_is_refused() -> None:
    def quote_map(request: CostRequest) -> dict:
        return {
            day: {**{s: 0.001 for s in request.symbols}, "ZZZ": 0.001}
            for day in request.gross_returns
        }

    with pytest.raises(EvaluatorCostError, match="whom nobody scored"):
        apply_costs(
            _gated(), _schedule_quoting(quote_map), node_id="n", cost_model=_REF
        )


def test_a_quote_carrying_no_charges_is_refused_by_the_record() -> None:
    with pytest.raises(EvaluatorCostError, match="no charges at all"):
        CostQuote(venue=_VENUE, version=_VERSION, costs={})


def test_a_quote_refuses_a_non_finite_charge() -> None:
    with pytest.raises(EvaluatorCostError, match="not finite"):
        CostQuote(
            venue=_VENUE,
            version=_VERSION,
            costs={_REBALANCE[0]: {"AAA": math.inf}},
        )


def test_a_quote_refuses_a_bool_as_a_charge() -> None:
    # True is not a fee, and the arithmetic would happily carry it.
    with pytest.raises(EvaluatorCostError, match="must be a number"):
        CostQuote(
            venue=_VENUE, version=_VERSION, costs={_REBALANCE[0]: {"AAA": True}}
        )


# -- The records ---------------------------------------------------------------


def test_the_series_captures_its_mappings_read_only() -> None:
    values = {_REBALANCE[0]: {"AAA": 0.01}}
    charges = {_REBALANCE[0]: {"AAA": 0.001}}
    series = PostCostSeries(
        horizon=1,
        snapshot_name="snap_abc123",
        venue=_VENUE,
        version=_VERSION,
        values=values,
        charges=charges,
    )
    values[_REBALANCE[0]]["BBB"] = 9.9
    with pytest.raises(TypeError):
        series.values[_REBALANCE[0]]["BBB"] = 9.9  # type: ignore[index]


def test_the_series_refuses_a_return_and_a_charge_on_different_dates() -> None:
    with pytest.raises(EvaluatorCostError, match="same support"):
        PostCostSeries(
            horizon=1,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={_REBALANCE[0]: {"AAA": 0.01}},
            charges={_REBALANCE[1]: {"AAA": 0.001}},
        )


def test_the_series_refuses_a_return_and_a_charge_for_different_symbols() -> None:
    with pytest.raises(EvaluatorCostError, match="does not explain"):
        PostCostSeries(
            horizon=1,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={_REBALANCE[0]: {"AAA": 0.01}},
            charges={_REBALANCE[0]: {"AAA": 0.001, "BBB": 0.001}},
        )


def test_the_series_refuses_a_horizon_outside_the_spec_set() -> None:
    with pytest.raises(EvaluatorCostError, match="not one of the horizons"):
        PostCostSeries(
            horizon=3,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={},
            charges={},
        )


def test_the_series_refuses_a_blank_snapshot_name() -> None:
    with pytest.raises(EvaluatorCostError, match="sealed snapshot"):
        PostCostSeries(
            horizon=1,
            snapshot_name=" ",
            venue=_VENUE,
            version=_VERSION,
            values={},
            charges={},
        )


def test_a_bundle_built_by_hand_must_carry_one_series_per_horizon() -> None:
    series = {
        horizon: PostCostSeries(
            horizon=horizon,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={},
            charges={},
        )
        for horizon in HORIZONS[:-1]
    }
    with pytest.raises(EvaluatorCostError, match="one series per horizon"):
        PostCostReturns(
            node_id="node_1",
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            cost_model=_REF,
            series=series,
            charges_budget=False,
        )


def test_a_bundle_must_name_the_cost_model_its_series_were_priced_under() -> None:
    with pytest.raises(EvaluatorCostError, match="cost model"):
        PostCostReturns(
            node_id="node_1",
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            cost_model={"venue": _VENUE, "version": _VERSION},
            series={},
            charges_budget=False,
        )


def test_a_bundle_must_carry_one_snapshot() -> None:
    series = {
        horizon: PostCostSeries(
            horizon=horizon,
            snapshot_name="other_snap" if horizon == 1 else "snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={},
            charges={},
        )
        for horizon in HORIZONS
    }
    with pytest.raises(EvaluatorCostError, match="one sealed world"):
        PostCostReturns(
            node_id="node_1",
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            cost_model=_REF,
            series=series,
            charges_budget=False,
        )


def test_a_bundle_must_carry_one_cost_model_across_its_series() -> None:
    series = {
        horizon: PostCostSeries(
            horizon=horizon,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version="2027.01.1" if horizon == 1 else _VERSION,
            values={},
            charges={},
        )
        for horizon in HORIZONS
    }
    with pytest.raises(EvaluatorCostError, match="one evaluation prices one"):
        PostCostReturns(
            node_id="node_1",
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            cost_model=_REF,
            series=series,
            charges_budget=False,
        )


def test_a_bundle_refuses_a_series_filed_under_the_wrong_horizon() -> None:
    series = {
        horizon: PostCostSeries(
            horizon=2 if horizon == 1 else horizon,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={},
            charges={},
        )
        for horizon in HORIZONS
    }
    with pytest.raises(EvaluatorCostError, match="wrong horizon"):
        PostCostReturns(
            node_id="node_1",
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            cost_model=_REF,
            series=series,
            charges_budget=False,
        )


def test_a_bundle_refuses_an_unsorted_rebalance_grid() -> None:
    with pytest.raises(EvaluatorCostError, match="sorted and de-duplicated"):
        PostCostReturns(
            node_id="node_1",
            snapshot_name="snap_abc123",
            rebalance_dates=(_REBALANCE[1], _REBALANCE[0]),
            cost_model=_REF,
            series={},
            charges_budget=False,
        )


def test_the_records_are_hashable_values() -> None:
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    assert isinstance(hash(out), int)
    assert isinstance(hash(out.costed(1)), int)
    assert isinstance(hash(CostQuote(venue=_VENUE, version=_VERSION, costs={
        _REBALANCE[0]: {"AAA": 0.001}
    })), int)


# -- Persistence ---------------------------------------------------------------


def test_the_post_cost_series_round_trips_through_the_store(
    evaluator_env: dict[str, str],
) -> None:
    schedule, _ = _flat_schedule(bps=12.0)
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)
    back = load_signal_returns("node_1", _REF)

    assert back == out
    assert back.returns(1) == out.returns(1)
    assert back.charges(1) == out.charges(1)
    assert back.snapshot_name == out.snapshot_name


def test_the_round_trip_returns_the_grid_the_evaluation_scored(
    evaluator_env: dict[str, str],
) -> None:
    # The grid cannot be rebuilt from the series rows.  A rebalance date at
    # the end of the bar grid has no forward return at any horizon — there
    # are no bars left to measure one over — so it is a date the evaluation
    # *scored* while no horizon's series carries it.  A reader that rebuilt
    # the grid by unioning the rows would report an evaluation that scored
    # fewer dates than it did, silently shrinking the window every consumer
    # downstream of §9.2 computes over.
    tail = _GRID[11]
    execution = _execution(_REBALANCE + (tail,))
    alignment = align_targets(execution, _MAIN_CLOSES)
    gated = gate_targets(
        alignment,
        _oracle(alignment),
        node_id="node_1",
        campaign_id="camp_1",
        depth=2,
    )

    schedule, _ = _flat_schedule()
    out = apply_costs(gated, schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)
    back = load_signal_returns("node_1", _REF)

    assert back.rebalance_dates == alignment.rebalance_dates
    assert tail in back.rebalance_dates
    scored = set().union(*(set(back.costed(h).dates()) for h in HORIZONS))
    assert tail not in scored
    assert scored < set(back.rebalance_dates)


def test_the_budget_directive_round_trips_through_the_store(
    evaluator_env: dict[str, str],
) -> None:
    # Persisted with the grid for the same reason: a directive dropped on the
    # way back is one no later step can recover.
    schedule, _ = _flat_schedule()
    out = apply_costs(
        _hand_bundle(charges_budget=True),
        schedule,
        node_id="node_1",
        cost_model=_REF,
    )
    persist_signal_returns(out)
    back = load_signal_returns("node_1", _REF)
    assert back.charges_budget is True
    assert back == out


def test_a_stored_directive_that_is_not_a_bit_is_refused(
    evaluator_env: dict[str, str],
) -> None:
    # Stored as an INTEGER because sqlite has no boolean, but coercion with
    # bool() would read an edited "2" as a statement about statistical budget.
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)

    parsed = evaluator_env["DATABASE_URL"].removeprefix("sqlite:///")
    with sqlite3.connect(parsed) as connection:
        connection.execute(
            f"UPDATE {SIGNAL_RETURNS_GRID_TABLE} SET charges_budget = 2"
        )
        connection.commit()

    with pytest.raises(EvaluatorStoreError, match="not the"):
        load_signal_returns("node_1", _REF)


def test_the_grain_is_one_row_per_symbol_per_period_per_horizon(
    evaluator_env: dict[str, str],
) -> None:
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)

    rows = _returns_columns(evaluator_env["DATABASE_URL"])
    expected = sum(
        len(row) for horizon in HORIZONS for row in out.returns(horizon).values()
    )
    assert len(rows) == expected
    assert len({(r[0], r[1], r[2]) for r in rows}) == len(rows)


def test_the_stored_gross_is_the_gate_s_supplied_return_not_the_net(
    evaluator_env: dict[str, str],
) -> None:
    # With the gross beside the charge and the net, the artifact answers
    # what the signal predicted, what the schedule took and what was left,
    # from one read — and "the schedule was applied" becomes a fact about
    # stored data rather than a claim about a code path.
    schedule, _ = _flat_schedule(bps=10.0)
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)

    rows = _returns_columns(evaluator_env["DATABASE_URL"])
    assert rows
    for horizon, stored_day, symbol, gross, charge, net in rows:
        day = dt.date.fromisoformat(stored_day)
        assert gross == pytest.approx(_MAIN.targets(horizon).at(day)[symbol])
        assert charge == pytest.approx(0.001)
        assert net == pytest.approx(gross - charge)


def test_a_re_persist_upserts_rather_than_doubling_the_periods(
    evaluator_env: dict[str, str],
) -> None:
    # §9.2's artifact is loaded as a single dense `nodes × periods` array
    # (feature 174); a duplicated period would read to every consumer as a
    # longer history.
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)
    before = len(_returns_columns(evaluator_env["DATABASE_URL"]))
    persist_signal_returns(out)
    assert len(_returns_columns(evaluator_env["DATABASE_URL"])) == before


def test_a_re_application_at_a_different_rate_refreshes_the_stored_numbers(
    evaluator_env: dict[str, str],
) -> None:
    first, _ = _flat_schedule(bps=10.0)
    out = apply_costs(_gated(), first, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)

    second, _ = _flat_schedule(bps=20.0)
    again = apply_costs(_gated(), second, node_id="node_1", cost_model=_REF)
    persist_signal_returns(again)

    back = load_signal_returns("node_1", _REF)
    assert back == again
    assert back.charges(1)[_REBALANCE[0]]["AAA"] == pytest.approx(0.002)


def test_two_cost_models_land_beside_each_other_rather_than_on_top(
    evaluator_env: dict[str, str],
) -> None:
    # The (venue, version) pair is in the primary key because the same
    # node's returns priced under two fee schedules are two series — §15
    # treats a changed cost model as its own failure case, and collapsing
    # them would file one schedule's numbers under another's provenance.
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)

    other = CostModelRef(venue=_VENUE, version="2027.01.1")

    def other_schedule(request: CostRequest) -> CostQuote:
        return CostQuote(
            venue=other.venue,
            version=other.version,
            costs={
                day: {s: 0.005 for s in request.symbols}
                for day in request.gross_returns
            },
        )

    second = apply_costs(
        _gated(), other_schedule, node_id="node_1", cost_model=other
    )
    persist_signal_returns(second)

    assert load_signal_returns("node_1", _REF).charges(1)[_REBALANCE[0]][
        "AAA"
    ] == pytest.approx(0.001)
    assert load_signal_returns("node_1", other).charges(1)[_REBALANCE[0]][
        "AAA"
    ] == pytest.approx(0.005)


def test_reading_a_node_that_was_never_costed_is_none(
    evaluator_env: dict[str, str],
) -> None:
    assert load_signal_returns("nobody", _REF) is None


def test_persisting_refuses_a_value_that_is_not_step_7s_result(
    evaluator_env: dict[str, str],
) -> None:
    with pytest.raises(EvaluatorCostError, match="PostCostReturns"):
        persist_signal_returns({1: {}})


def test_persisting_without_a_store_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    with pytest.raises(EvaluatorStoreError, match="DATABASE_URL is not set"):
        persist_signal_returns(out)


def test_reading_without_a_store_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(EvaluatorStoreError, match="DATABASE_URL is not set"):
        load_signal_returns("node_1", _REF)


def test_an_unsupported_store_scheme_is_refused_by_name(
    evaluator_env: dict[str, str],
) -> None:
    # Construction is deliberately I/O-free, so the URL is parsed on first
    # use — the identity store's stance, and the reason the factory can
    # build this component in any environment.
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    with pytest.raises(EvaluatorStoreError, match="unsupported"):
        PostCostStore("postgresql://localhost/nullius").persist(out)


def test_a_store_with_a_host_is_refused(evaluator_env: dict[str, str]) -> None:
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    with pytest.raises(EvaluatorStoreError, match="must not carry a host"):
        PostCostStore("sqlite://otherhost/x.db").persist(out)


def test_construction_performs_no_io(tmp_path) -> None:
    # Composition-time work must not touch the disk: the factory builds this
    # component on every create_app(), in any environment.
    target = tmp_path / "never-created" / "evaluator.db"
    PostCostStore(f"sqlite:///{target}")


def test_the_store_resolves_from_the_environment(
    evaluator_env: dict[str, str],
) -> None:
    assert PostCostStore.resolve().database_url == evaluator_env["DATABASE_URL"]


def test_the_store_refuses_an_environment_with_no_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(EvaluatorStoreError, match="DATABASE_URL is not set"):
        PostCostStore.resolve()


def test_a_stored_row_that_does_not_net_out_is_refused(
    evaluator_env: dict[str, str],
) -> None:
    # The read path recomputes the net from the row's own terms rather than
    # trusting it, so a row edited outside this package fails to reconstruct
    # instead of loading as a plausible-looking lie.
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)

    parsed = evaluator_env["DATABASE_URL"].removeprefix("sqlite:///")
    with sqlite3.connect(parsed) as connection:
        connection.execute(
            f"UPDATE {SIGNAL_RETURNS_TABLE} SET post_cost_return = 99.0 "
            "WHERE node_id = 'node_1' AND horizon = 1"
        )
        connection.commit()

    with pytest.raises(EvaluatorStoreError, match="disagrees with itself"):
        load_signal_returns("node_1", _REF)


def test_a_series_without_its_grid_row_is_refused(
    evaluator_env: dict[str, str],
) -> None:
    # The grid row and the series rows are written in one transaction, so a
    # series without a grid was not written by this store's writer —
    # rebuilding a grid from the series would silently understate what the
    # evaluation scored.
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)

    parsed = evaluator_env["DATABASE_URL"].removeprefix("sqlite:///")
    with sqlite3.connect(parsed) as connection:
        connection.execute(f"DELETE FROM {SIGNAL_RETURNS_GRID_TABLE}")
        connection.commit()

    with pytest.raises(EvaluatorStoreError, match="no grid row"):
        load_signal_returns("node_1", _REF)


def test_the_store_is_created_idempotently(
    evaluator_env: dict[str, str],
) -> None:
    # A fresh database and an existing one take one path, so no migration
    # step is needed for this member.
    schedule, _ = _flat_schedule()
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    store = PostCostStore(evaluator_env["DATABASE_URL"])
    store.persist(out)
    assert store.load("node_1", _REF) == out


def test_a_store_with_an_empty_url_is_refused() -> None:
    with pytest.raises(EvaluatorStoreError, match="non-empty database URL"):
        PostCostStore("   ")


def test_loading_refuses_a_non_name_node_id(
    evaluator_env: dict[str, str],
) -> None:
    with pytest.raises(EvaluatorStoreError, match="node id"):
        load_signal_returns("", _REF)


def test_the_persisted_columns_carry_what_the_record_carries(
    evaluator_env: dict[str, str],
) -> None:
    schedule, _ = _flat_schedule(bps=10.0)
    out = apply_costs(_gated(), schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)

    parsed = evaluator_env["DATABASE_URL"].removeprefix("sqlite:///")
    with sqlite3.connect(parsed) as connection:
        rows = connection.execute(
            f"SELECT node_id, venue, version, snapshot_name "
            f"FROM {SIGNAL_RETURNS_TABLE}"
        ).fetchall()
    assert rows
    assert all(
        row == ("node_1", _VENUE, _VERSION, out.snapshot_name) for row in rows
    )


def test_the_charged_support_is_exactly_the_gates_supply(
    evaluator_env: dict[str, str],
) -> None:
    # Persistence writes what step 7 computed and invents no dates, so the
    # stored support is the gate's own — the same rule the gate enforced at
    # its ask, restated one step downstream.
    schedule, _ = _flat_schedule()
    gated = _gated()
    out = apply_costs(gated, schedule, node_id="node_1", cost_model=_REF)
    persist_signal_returns(out)
    back = load_signal_returns("node_1", _REF)

    for horizon in HORIZONS:
        assert set(back.costed(horizon).dates()) == set(
            gated.targets(horizon).dates()
        )
