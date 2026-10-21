"""bug_spec_null_carry_leak.xml, bug 1 — the carry moves into the target seam.

Under ``context.instrument == "perp"``, the post-cost return the metrics
reduce used to be ``price_return - fee - funding_carry``, with the carry
read in ``orchestrator._evaluate._cost_schedule_from_context``'s ``charges()``
closure — keyed by the request's own ``(date, symbol)``, which is to say,
by the *recipient* of whatever target value a planted null happened to
permute in. The null branch (``nulloracle.blockpermute.
block_permute_cross_section``, applied by ``TargetEndpoint`` to the series
``orchestrator._targets.snapshot_forward_returns`` serves) permutes the price
return across symbols within a date, but the carry was added downstream of
that permutation, so it never moved with it: a null's served value for
symbol A was ``(price return of A's donor) - fee - (A's own carry)``, not
the donor's own post-cost return. A signal that is a function of funding or
basis therefore correlated with its own unpermuted carry, biasing the
planted null for those themes upward.

The fix folds the carry into the target seam itself: ``snapshot_forward_
returns`` now serves the *funded* return (price return minus the funding
carry over the holding window) under perp, before either branch — real or
permuted — is built, and the cost schedule quotes the uniform fee alone on
every instrument. This file is the five tests bug_spec_null_carry_leak.xml
names for that fix, one per claim:

1. a four-symbol, two-rebalance-date fixture whose funding carries two
   symbols positive and two negative — permuted under a seed whose
   derangement swaps a positive-carry symbol with a negative-carry one —
   prices to exactly the donor's own post-cost value, not a mix of the
   recipient's carry and the donor's price;
2. the same fixture, unpermuted (a real node): the post-cost panel equals
   ``r - fee - carry`` to floating-point precision;
3. a non-perp context's served value is byte-identical to a direct
   close-to-close computation off the same closes;
4. a signal equal to ``-funding`` has a mean rank correlation near zero
   against the permuted post-cost panel over 200 seeds, on a 20-symbol,
   12-date fixture with alternating-sign carries — the statistical claim
   the bug's own measurement made, now cleared;
5. ``_cost_schedule_from_context``'s ``charges()`` quotes the same fee
   under perp as it does for the spot default, for the same request.

No test opens a network connection, reads a real credential, or writes
outside this process's memory — every context here is a bare duck-typed
``SimpleNamespace`` carrying only the attributes the functions under test
read (the same courtesy ``test_snapshot_targets.py`` and
``test_cost_pit_cross_section.py`` already extend), so no sealed snapshot is
staged and the suite runs in well under a second.
"""

from __future__ import annotations

import datetime as dt
import random
import statistics
from types import SimpleNamespace
from typing import Any

import pytest
from cost_model import TAKER, FeeSchedule
from evaluator import (
    HORIZONS,
    CostModelRef,
    CostRequest,
    GatedTargets,
    TargetSeries,
    apply_costs,
)
from nulloracle.blockpermute import block_permute_cross_section
from orchestrator._evaluate import _cost_schedule_from_context, _funding_carry
from orchestrator._targets import snapshot_forward_returns

_VENUE = "binance_usdm"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)
_SCHEDULE = FeeSchedule(venue=_VENUE, taker_bps=5.0, maker_bps=5.0)
_FEE = _SCHEDULE.fee_fraction(TAKER)
_SNAPSHOT_NAME = "snap_null_carry_target_test"


def _request(
    *,
    symbols: tuple[str, ...] | None = None,
    date_range: tuple[dt.date, dt.date] | None = None,
    horizon: int | None = None,
) -> Any:
    return SimpleNamespace(symbols=symbols, date_range=date_range, horizon=horizon)


def _gated_multi(
    values_by_horizon: dict[int, dict[dt.date, dict[str, float]]]
) -> GatedTargets:
    """A hand-built, step-5 bundle carrying ``values_by_horizon`` verbatim at
    the horizons it names and the empty series at every other (feature 75's
    shape promise) — the same helper ``test_perp_instrument.py`` already
    proved, generalized to populate more than one horizon at once.
    """
    dates = tuple(sorted({day for values in values_by_horizon.values() for day in values}))
    series = {
        h: TargetSeries(
            horizon=h,
            snapshot_name=_SNAPSHOT_NAME,
            values=values_by_horizon.get(h, {}),
        )
        for h in HORIZONS
    }
    return GatedTargets(
        snapshot_name=_SNAPSHOT_NAME,
        rebalance_dates=dates,
        series=series,
        charges_budget=False,
    )


def _priced(gated: GatedTargets, context: Any, *, node_id: str) -> Any:
    return apply_costs(
        gated, _cost_schedule_from_context(context), node_id=node_id, cost_model=_REF
    )


# -- Test 1 & 2: the four-symbol fixture ------------------------------------

#: Sorted order matters: the derangement below is drawn over this exact
#: tuple, and A/B carry positive funding while C/D carry negative — the pair
#: a null must swap to expose the leak the bug reports.
SYMBOLS_4 = ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")
_FOUR_DAYS = tuple(dt.date(2026, 3, 1) + dt.timedelta(days=i) for i in range(4))
#: Entry dates d0 and d1 both have a valid horizon-1 and horizon-2 exit
#: inside this four-day span — "two rebalance dates" at either horizon.
_ENTRY_DAYS = _FOUR_DAYS[:2]
#: Found by exhaustive search over block_permute_cross_section(seed=..,
#: block_days=2) against a sentinel panel: the single derangement this seed
#: draws for this four-symbol membership swaps AAAUSDT<->CCCUSDT and
#: BBBUSDT<->DDDUSDT — the positive-carry/negative-carry swap the bug's own
#: reproduction describes, reproducible from the seed alone.
_SWAP_SEED = 12
_SWAP_BLOCK_DAYS = 2

_DAILY_MOVES = {
    "AAAUSDT": (0.01, -0.02, 0.015),
    "BBBUSDT": (-0.015, 0.03, -0.005),
    "CCCUSDT": (0.02, 0.01, -0.01),
    "DDDUSDT": (-0.01, -0.005, 0.02),
}
_BASE_PRICE = {"AAAUSDT": 100.0, "BBBUSDT": 150.0, "CCCUSDT": 200.0, "DDDUSDT": 250.0}
#: A and B carry positive funding, C and D negative — the fixture the bug's
#: own reproduction names.
_DAILY_FUNDING = {"AAAUSDT": 0.002, "BBBUSDT": 0.002, "CCCUSDT": -0.002, "DDDUSDT": -0.002}


def _four_symbol_context() -> Any:
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol in SYMBOLS_4:
        price = _BASE_PRICE[symbol]
        path = {_FOUR_DAYS[0]: price}
        for index, move in enumerate(_DAILY_MOVES[symbol]):
            price = price * (1.0 + move)
            path[_FOUR_DAYS[index + 1]] = price
        closes[symbol] = path

    funding = {
        symbol: {day: _DAILY_FUNDING[symbol] for day in _FOUR_DAYS} for symbol in SYMBOLS_4
    }

    return SimpleNamespace(
        closes=closes,
        horizon=1,
        instrument="perp",
        funding=funding,
        cost_schedule=_SCHEDULE,
    )


def _price_return(context: Any, symbol: str, entry: dt.date, exit_: dt.date) -> float:
    return context.closes[symbol][exit_] / context.closes[symbol][entry] - 1.0


class TestANullsDerangementCarriesTheDonorsOwnCarryAlong:
    def test_a_swapped_pair_prices_to_exactly_the_donors_post_cost_value(self) -> None:
        context = _four_symbol_context()
        target = snapshot_forward_returns(context)

        values_by_horizon: dict[int, dict[dt.date, dict[str, float]]] = {}
        permuted_by_horizon: dict[int, dict[dt.date, dict[str, float]]] = {}
        for horizon in (1, 2):
            panel = target(_request(date_range=(_ENTRY_DAYS[0], _ENTRY_DAYS[-1]), horizon=horizon))
            assert set(panel) == set(_ENTRY_DAYS)  # both entries land inside the 4-day span
            values_by_horizon[horizon] = panel
            permuted_by_horizon[horizon] = block_permute_cross_section(
                panel, seed=_SWAP_SEED, block_days=_SWAP_BLOCK_DAYS
            )

        real_priced = _priced(
            _gated_multi(values_by_horizon), context, node_id="node-null-carry-real"
        )
        null_priced = _priced(
            _gated_multi(permuted_by_horizon), context, node_id="node-null-carry-null"
        )

        swap = {"AAAUSDT": "CCCUSDT", "BBBUSDT": "DDDUSDT", "CCCUSDT": "AAAUSDT", "DDDUSDT": "BBBUSDT"}
        for horizon in (1, 2):
            for day in _ENTRY_DAYS:
                for symbol, donor in swap.items():
                    assert null_priced.returns(horizon)[day][symbol] == pytest.approx(
                        real_priced.returns(horizon)[day][donor], abs=1e-15
                    )

    def test_a_real_node_post_cost_panel_equals_r_minus_fee_minus_carry(self) -> None:
        context = _four_symbol_context()
        target = snapshot_forward_returns(context)
        panel = target(_request(date_range=(_ENTRY_DAYS[0], _ENTRY_DAYS[-1]), horizon=1))
        priced = _priced(_gated_multi({1: panel}), context, node_id="node-null-carry-real-h1")

        for day in _ENTRY_DAYS:
            exit_day = _FOUR_DAYS[_FOUR_DAYS.index(day) + 1]
            for symbol in SYMBOLS_4:
                r = _price_return(context, symbol, day, exit_day)
                carry = _funding_carry(context, symbol, day, 1)
                expected = r - _FEE - carry
                assert priced.returns(1)[day][symbol] == pytest.approx(expected, abs=1e-12)


# -- Test 3: a non-perp context is untouched --------------------------------


def test_a_non_perp_context_is_byte_identical_to_a_direct_computation() -> None:
    days = tuple(dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(6))
    closes = {
        "AAA": {day: 100.0 + 1.3 * i for i, day in enumerate(days)},
        "BBB": {day: 50.0 - 0.7 * i for i, day in enumerate(days)},
    }
    # No `instrument` or `funding` attribute at all — the bare duck-typed
    # context several of this module's own callers already extend the same
    # courtesy to.
    context = SimpleNamespace(closes=closes, horizon=2)
    target = snapshot_forward_returns(context)

    series = target(_request())
    for day, row in series.items():
        index = days.index(day)
        for symbol, value in row.items():
            direct = closes[symbol][days[index + 2]] / closes[symbol][days[index]] - 1.0
            assert value == direct


# -- Test 4: the statistical claim, 200 seeds -------------------------------

N_SYMBOLS = 20
N_DATES = 12
MARKET_SEED = 20261021
PERMUTE_SEEDS = tuple(range(1, 201))
BLOCK_DAYS = 6
CARRY_MAGNITUDE = 0.01


def _alternating_sign_market() -> Any:
    symbols = tuple(f"SYM{i:02d}" for i in range(N_SYMBOLS))
    days = tuple(dt.date(2026, 2, 1) + dt.timedelta(days=i) for i in range(N_DATES))
    rng = random.Random(MARKET_SEED)

    closes: dict[str, dict[dt.date, float]] = {}
    for symbol in symbols:
        price = 100.0 * (1.0 + rng.uniform(-0.3, 0.3))
        path = {days[0]: price}
        for day in days[1:]:
            price = max(1.0, price * (1.0 + rng.gauss(0.0, 0.02)))
            path[day] = price
        closes[symbol] = path

    # Alternating sign, constant across days — the same shape the bug's own
    # funding-crowding theme reads, and the simplest fixture that makes a
    # symbol's own carry a fixed, date-independent quantity.
    funding_rate = {
        symbol: CARRY_MAGNITUDE * (1.0 if index % 2 == 0 else -1.0)
        for index, symbol in enumerate(symbols)
    }
    funding = {symbol: {day: funding_rate[symbol] for day in days} for symbol in symbols}

    context = SimpleNamespace(
        closes=closes,
        horizon=1,
        instrument="perp",
        funding=funding,
        cost_schedule=_SCHEDULE,
    )
    return context, symbols, days, funding_rate


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = average
        i = j + 1
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    spread_x = (sum((x - mean_x) ** 2 for x in xs)) ** 0.5
    spread_y = (sum((y - mean_y) ** 2 for y in ys)) ** 0.5
    return numerator / (spread_x * spread_y) if spread_x and spread_y else 0.0


def _spearman(xs: list[float], ys: list[float]) -> float:
    return _pearson(_ranks(xs), _ranks(ys))


def test_minus_funding_has_near_zero_mean_rank_correlation_against_the_permuted_panel() -> None:
    context, symbols, days, funding_rate = _alternating_sign_market()
    target = snapshot_forward_returns(context)
    # One rebalance date per day with a horizon-1 exit inside the span.
    panel = target(_request(date_range=(days[0], days[-2]), horizon=1))
    assert set(panel) == set(days[:-1])

    signal = [-funding_rate[symbol] for symbol in symbols]

    ics: list[float] = []
    for seed in PERMUTE_SEEDS:
        permuted = block_permute_cross_section(panel, seed=seed, block_days=BLOCK_DAYS)
        # Priced through the same cost schedule a live evaluation reduces —
        # the recipient-keyed carry the bug added here is exactly what this
        # test must not see leak back in post-fix.
        priced = _priced(
            _gated_multi({1: permuted}), context, node_id=f"node-null-carry-stat-{seed}"
        )
        for day in permuted:
            row = priced.returns(1)[day]
            ics.append(_spearman(signal, [row[symbol] for symbol in symbols]))

    mean_ic = statistics.mean(ics)
    assert abs(mean_ic) <= 0.05


# -- Test 5: charges() quotes the same fee on perp as on spot ---------------


def test_charges_under_perp_quotes_the_same_fee_as_the_spot_default() -> None:
    days = tuple(dt.date(2026, 4, 1) + dt.timedelta(days=i) for i in range(2))
    gross_returns = {
        days[0]: {"AAA": 0.01, "BBB": -0.02},
        days[1]: {"AAA": 0.02, "BBB": 0.03},
    }
    request = CostRequest(
        node_id="node-charges-parity",
        venue=_VENUE,
        version=_VERSION,
        horizon=1,
        symbols=("AAA", "BBB"),
        date_range=(days[0], days[1]),
        gross_returns=gross_returns,
    )

    spot_context = SimpleNamespace(cost_schedule=_SCHEDULE)
    perp_context = SimpleNamespace(
        cost_schedule=_SCHEDULE,
        instrument="perp",
        funding={"AAA": {days[0]: 0.01, days[1]: 0.01}, "BBB": {days[0]: -0.01, days[1]: -0.01}},
    )

    spot_quote = _cost_schedule_from_context(spot_context)(request)
    perp_quote = _cost_schedule_from_context(perp_context)(request)

    assert perp_quote.costs == spot_quote.costs
    for row in perp_quote.costs.values():
        for cost in row.values():
            assert cost == pytest.approx(_FEE)
