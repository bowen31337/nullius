"""bug_spec_turnover_cost_charge.xml — turnover cost on the dollar-neutral book.

COST-1: step 7 (:func:`evaluator.apply_costs`) charges one taker fee per
symbol, uniformly, and that fee *cancels* in the dollar-neutral book
:func:`evaluator.compute_node_metrics` measures — ``Σ w_i (r_i − f) =
Σ w_i r_i − f · Σ w_i``, and ``Σ w_i = 0`` by construction — so a signal that
reshuffles its whole book every bar and one that never touches it reported
the identical ``ir_standalone``, and changing the fee rate changed nothing in
the node metrics. The fix gives :func:`compute_node_metrics` a keyword-only
``cost_per_unit_traded`` that charges the book's own traded notional,
``Σ|w_d − w_{d-1}|`` (``Σ|w_d|`` on the first book date), against the book
return itself, which cannot cancel.

This suite is self-contained (it does not import ``test_metrics.py``'s
fixtures), covers no persistence or horizon-selection behaviour (that is
``test_metrics.py``'s job), and runs with no database, so it is safe under
pytest-xdist with no isolation beyond what the module import needs.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest
from evaluator import (
    HORIZONS,
    CostModelRef,
    EvaluatorMetricsError,
    PostCostReturns,
    PostCostSeries,
    compute_node_metrics,
)

_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)
_START = dt.date(2026, 9, 1)
_D0 = _START
_D1 = _START + dt.timedelta(days=1)
_D2 = _START + dt.timedelta(days=2)


def _hand_priced(
    returns_by_date: dict[dt.date, dict[str, float]],
    *,
    horizon: int = 1,
) -> PostCostReturns:
    """A hand-built, single-horizon priced bundle — step 8's input."""
    series: dict[int, PostCostSeries] = {}
    for h in HORIZONS:
        values = returns_by_date if h == horizon else {}
        series[h] = PostCostSeries(
            horizon=h,
            snapshot_name="snap_abc123",
            venue=_VENUE,
            version=_VERSION,
            values={day: dict(row) for day, row in values.items()},
            charges={
                day: {symbol: 0.001 for symbol in row} for day, row in values.items()
            },
        )
    return PostCostReturns(
        node_id="node_1",
        snapshot_name="snap_abc123",
        rebalance_dates=tuple(sorted(returns_by_date)),
        cost_model=_REF,
        series=series,
        charges_budget=False,
    )


def _population_ir(values: list[float]) -> float:
    """The mean-over-population-std ratio, spelled independently of the module."""
    n = len(values)
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / n
    return mean / math.sqrt(variance)


# -- The reproduction: the uniform fee cancels, traded-notional cost does not --


# Three dates, three symbols. AAA and BBB carry the whole signal; CCC's
# return is pinned at exactly 0.0 on every date, so whatever weight CCC
# holds contributes nothing to the book return — it exists purely to move
# the book's *weights* (and so its turnover) without moving the book's
# *return*. AAA and BBB are scored ±1.0 on every date (never flipped), and
# CCC is scored ±1.0 too, so |z_AAA| + |z_BBB| + |z_CCC| = 3 on every date
# regardless of CCC's sign — the normalizing denominator is constant, so
# w_AAA = 1/3 and w_BBB = -1/3 on every date in *both* paths below, and the
# book return, Σ w_i r_i, is bit-identical between them.
_TURNOVER_RETURNS = {
    _D0: {"AAA": 0.09, "BBB": -0.03, "CCC": 0.0},
    _D1: {"AAA": -0.03, "BBB": 0.09, "CCC": 0.0},
    _D2: {"AAA": 0.06, "BBB": -0.06, "CCC": 0.0},
}

# Low turnover: CCC's sign never changes, so the book's weights never move
# after the first date — zero turnover beyond the unavoidable entry.
_LOW_TURNOVER_SCORES = {
    _D0: {"AAA": 1.0, "BBB": -1.0, "CCC": 1.0},
    _D1: {"AAA": 1.0, "BBB": -1.0, "CCC": 1.0},
    _D2: {"AAA": 1.0, "BBB": -1.0, "CCC": 1.0},
}

# High turnover: CCC's sign flips every date, moving 2/3 of the book's
# weight on each of the two transitions — pure turnover with zero effect on
# the gross book return, since CCC never earns anything.
_HIGH_TURNOVER_SCORES = {
    _D0: {"AAA": 1.0, "BBB": -1.0, "CCC": 1.0},
    _D1: {"AAA": 1.0, "BBB": -1.0, "CCC": -1.0},
    _D2: {"AAA": 1.0, "BBB": -1.0, "CCC": 1.0},
}

# The shared gross book return per date (Σ w_i r_i with w_AAA=1/3, w_BBB=-1/3,
# w_CCC contributing 0): 1/3*0.09 - 1/3*(-0.03) = 0.04; 1/3*(-0.03) -
# 1/3*0.09 = -0.04; 1/3*0.06 - 1/3*(-0.06) = 0.04.
_GROSS_BOOK = [0.04, -0.04, 0.04]

# Traded notional per date. Entry (first book date) is always Σ|w| = 1.0 for
# both paths, since the normalized book always has unit gross exposure. The
# low path never moves afterwards (0.0 each transition); the high path moves
# CCC's weight by 2/3 on each of the two transitions.
_LOW_TRADED = [1.0, 0.0, 0.0]
_HIGH_TRADED = [1.0, 2.0 / 3.0, 2.0 / 3.0]


def test_turnover_never_moves_ir_when_uncosted():
    """Reproduces the bug: with no cost, turnover has no effect on ir_standalone."""
    low = compute_node_metrics(
        _hand_priced(_TURNOVER_RETURNS), _LOW_TURNOVER_SCORES
    )
    high = compute_node_metrics(
        _hand_priced(_TURNOVER_RETURNS), _HIGH_TURNOVER_SCORES
    )
    assert low.turnover != pytest.approx(high.turnover)
    assert low.ir_standalone == pytest.approx(high.ir_standalone)
    assert low.ir_standalone == pytest.approx(_population_ir(_GROSS_BOOK))


def test_a_cost_separates_the_high_turnover_path_by_the_expected_amount():
    """With a cost, the higher-turnover path's IR is lower by the traded difference."""
    cost = 0.03
    low_net = [g - cost * t for g, t in zip(_GROSS_BOOK, _LOW_TRADED)]
    high_net = [g - cost * t for g, t in zip(_GROSS_BOOK, _HIGH_TRADED)]
    assert low_net != high_net  # the entry charge is identical; later dates diverge

    low = compute_node_metrics(
        _hand_priced(_TURNOVER_RETURNS),
        _LOW_TURNOVER_SCORES,
        cost_per_unit_traded=cost,
    )
    high = compute_node_metrics(
        _hand_priced(_TURNOVER_RETURNS),
        _HIGH_TURNOVER_SCORES,
        cost_per_unit_traded=cost,
    )
    assert low.ir_standalone == pytest.approx(_population_ir(low_net))
    assert high.ir_standalone == pytest.approx(_population_ir(high_net))
    assert high.ir_standalone < low.ir_standalone
    for day, expected in zip(sorted(_TURNOVER_RETURNS), low_net):
        assert low.book_returns[day] == pytest.approx(expected)
    for day, expected in zip(sorted(_TURNOVER_RETURNS), high_net):
        assert high.book_returns[day] == pytest.approx(expected)


# -- A hand-computed three-date example, including the entry charge -----------


def test_a_hand_computed_three_date_example_including_entry_charge():
    """Walks the net book return by hand for a book that flips every bar.

    Two symbols, scores ±1.0 flipping every date, so the book is
    w = (0.5, -0.5) on day 0, (-0.5, 0.5) on day 1, (0.5, -0.5) on day 2.

    Traded notional:
      * day 0 (entry, no predecessor): |0.5| + |-0.5| = 1.0
      * day 0 -> day 1: |-0.5-0.5| + |0.5-(-0.5)| = 1.0 + 1.0 = 2.0
      * day 1 -> day 2: |0.5-(-0.5)| + |-0.5-0.5| = 1.0 + 1.0 = 2.0

    Gross book returns (Σ w_i r_i):
      * day 0: 0.5*0.02 + (-0.5)*(-0.01) = 0.010 + 0.005 = 0.015
      * day 1: (-0.5)*0.05 + 0.5*(-0.02) = -0.025 - 0.010 = -0.035
      * day 2: 0.5*0.01 + (-0.5)*(-0.02) = 0.005 + 0.010 = 0.015

    At cost_per_unit_traded = 0.01 (1%), the net book returns are the gross
    minus cost times the traded notional above:
      * day 0: 0.015 - 0.01*1.0 = 0.005
      * day 1: -0.035 - 0.01*2.0 = -0.055
      * day 2: 0.015 - 0.01*2.0 = -0.005
    """
    returns_by_date = {
        _D0: {"AAA": 0.02, "BBB": -0.01},
        _D1: {"AAA": 0.05, "BBB": -0.02},
        _D2: {"AAA": 0.01, "BBB": -0.02},
    }
    scores = {
        _D0: {"AAA": 1.0, "BBB": -1.0},
        _D1: {"AAA": -1.0, "BBB": 1.0},
        _D2: {"AAA": 1.0, "BBB": -1.0},
    }
    expected_net = [0.005, -0.055, -0.005]
    expected_ir = _population_ir(expected_net)

    metrics = compute_node_metrics(
        _hand_priced(returns_by_date), scores, cost_per_unit_traded=0.01
    )

    assert metrics.book_returns[_D0] == pytest.approx(0.005)
    assert metrics.book_returns[_D1] == pytest.approx(-0.055)
    assert metrics.book_returns[_D2] == pytest.approx(-0.005)
    assert metrics.ir_standalone == pytest.approx(expected_ir)


def test_traded_notional_treats_a_symbol_absent_from_one_side_as_zero_weight():
    """A symbol newly entering the book is charged its full weight as traded.

    Day 0 scores only AAA and BBB (w = 0.5, -0.5). Day 1 adds CCC, which was
    never in day 0's book at all (not merely zero-weighted there) — the
    traded notional on day 1 must treat CCC's absent day-0 weight as 0, so
    its whole day-1 weight (0.5) counts as traded, on top of the 0.25 each
    AAA and BBB moved by (the book shrinks from 0.5/-0.5 to 0.25/-0.25 to
    make room for CCC): traded_d1 = |0.25-0.5| + |-0.25-(-0.5)| + |0.5-0| =
    0.25 + 0.25 + 0.5 = 1.0.
    """
    returns_by_date = {
        _D0: {"AAA": 0.02, "BBB": -0.01},
        _D1: {"AAA": -0.03, "BBB": 0.04, "CCC": 0.01},
    }
    scores = {
        _D0: {"AAA": 1.0, "BBB": -1.0},
        _D1: {"AAA": 1.0, "BBB": -1.0, "CCC": 2.0},
    }
    cost = 0.02
    # Entry traded (day 0) = |0.5| + |-0.5| = 1.0; day 1's traded (worked out
    # in the docstring above) is also 1.0, so both dates are charged cost*1.0.
    expected_net = [0.015 - cost * 1.0, -0.0125 - cost * 1.0]

    metrics = compute_node_metrics(
        _hand_priced(returns_by_date), scores, cost_per_unit_traded=cost
    )

    assert metrics.book_returns[_D0] == pytest.approx(expected_net[0])
    assert metrics.book_returns[_D1] == pytest.approx(expected_net[1])
    assert metrics.ir_standalone == pytest.approx(_population_ir(expected_net))


# -- The default reproduces today's figures exactly -----------------------------


def test_zero_cost_matches_the_old_uncosted_figures():
    """cost_per_unit_traded=0.0 (the default) reproduces every figure unchanged."""
    priced = _hand_priced(_TURNOVER_RETURNS)
    baseline = compute_node_metrics(priced, _HIGH_TURNOVER_SCORES)
    explicit_zero = compute_node_metrics(
        priced, _HIGH_TURNOVER_SCORES, cost_per_unit_traded=0.0
    )
    assert baseline == explicit_zero
    assert baseline.book_returns == explicit_zero.book_returns
    assert baseline.ir_standalone == explicit_zero.ir_standalone
    assert baseline.turnover == explicit_zero.turnover


# -- Refusals ---------------------------------------------------------------------


def test_a_negative_cost_is_refused():
    """A negative cost would pay the book for trading — refused, not applied."""
    priced = _hand_priced(_TURNOVER_RETURNS)
    with pytest.raises(EvaluatorMetricsError, match="non-negative"):
        compute_node_metrics(
            priced, _LOW_TURNOVER_SCORES, cost_per_unit_traded=-0.001
        )


def test_a_nan_cost_is_refused():
    """A NaN cost would reach every book return dressed as a measurement."""
    priced = _hand_priced(_TURNOVER_RETURNS)
    with pytest.raises(EvaluatorMetricsError, match="finite"):
        compute_node_metrics(
            priced, _LOW_TURNOVER_SCORES, cost_per_unit_traded=float("nan")
        )


def test_an_infinite_cost_is_refused():
    """A non-finite cost is refused the same way a NaN one is."""
    priced = _hand_priced(_TURNOVER_RETURNS)
    with pytest.raises(EvaluatorMetricsError, match="finite"):
        compute_node_metrics(
            priced, _LOW_TURNOVER_SCORES, cost_per_unit_traded=float("inf")
        )
