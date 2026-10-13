"""additions_spec_research_book_v2.xml feature 1 — beta-neutral legs.

The dollar-neutral book (``w_i = z_i / Σ|z_j|``) is net-zero but not
benchmark beta-neutral: a book tilted toward low-beta names on one side and
high-beta names on the other carries a residual market-beta exposure that is
not the signal's edge. :func:`compute_node_metrics` gains a keyword-only
``betas`` (``{date: {symbol: beta}}``, default ``None``); when supplied, each
date's long leg (``w > 0``) and short leg (``w < 0``) are weight-averaged
into ``β_L`` and ``β_S`` over the symbols either leg has a beta for, and the
rated symbols of each leg are rescaled so the whole leg (rated weight plus
whatever unrated weight it already carries, left untouched) reaches gross
``gl = β_S / (β_L + β_S)`` for the long leg and ``1 − gl`` for the short — the
split that zeroes the book's net beta when every symbol is rated, while
total gross exposure stays 1. A date falls back to the plain weights when
either leg has no rated symbol, ``β_L + β_S ≤ 0``, or the unrated weight
already parked in a leg would leave its rated symbols a non-positive gross to
carry.

This suite is self-contained (it does not import ``test_metrics.py`` or
``test_metrics_turnover_cost.py``'s fixtures) and runs with no database, so
it is safe under pytest-xdist with no isolation beyond what the module
import needs.
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


# -- 1. A hand-computed two-date example, including partial beta coverage -----

# Day 0: A and B are the long leg (B carries no beta), C and D are the short
# leg (D carries no beta).
#   scores -> weights (gross 8): A=3 (0.375), B=1 (0.125), C=-3 (-0.375),
#   D=-1 (-0.125).
#   beta_L = beta_A = 1.2 (A is the long leg's only rated symbol).
#   beta_S = beta_C = 0.8 (C is the short leg's only rated symbol).
#   gl = 0.8 / (1.2 + 0.8) = 0.4, so the long leg targets gross 0.4 and the
#   short leg targets gross 0.6.
#   B (unrated, long) keeps its weight 0.125 unscaled, so A's rated gross must
#   reach 0.4 - 0.125 = 0.275 (from 0.375: scale 0.275/0.375).
#   D (unrated, short) keeps its weight -0.125 unscaled (gross 0.125), so C's
#   rated gross must reach 0.6 - 0.125 = 0.475 (from 0.375: scale 0.475/0.375).
#   Rescaled weights: A=0.275, B=0.125, C=-0.475, D=-0.125 (gross 1.0).
_D0_SCORES = {"A": 3.0, "B": 1.0, "C": -3.0, "D": -1.0}
_D0_RETURNS = {"A": 0.04, "B": 0.02, "C": -0.01, "D": 0.03}
_D0_WEIGHTS = {"A": 0.275, "B": 0.125, "C": -0.475, "D": -0.125}

# Day 1: the same four symbols and the same betas, scores reversed in
# magnitude between the leg's rated and unrated member.
#   scores -> weights (gross 8): A=1 (0.125), B=3 (0.375), C=-1 (-0.125),
#   D=-3 (-0.375).
#   beta_L = beta_A = 1.2, beta_S = beta_C = 0.8 (unchanged, since A and C are
#   still each leg's only rated symbol) -> gl=0.4 again.
#   B (unrated) keeps 0.375, so A's rated gross must reach 0.4-0.375=0.025
#   (from 0.125: scale 0.2). D (unrated) keeps -0.375, so C's rated gross
#   must reach 0.6-0.375=0.225 (from 0.125: scale 1.8).
#   Rescaled weights: A=0.025, B=0.375, C=-0.225, D=-0.375 (gross 1.0).
_D1_SCORES = {"A": 1.0, "B": 3.0, "C": -1.0, "D": -3.0}
_D1_RETURNS = {"A": 0.05, "B": -0.02, "C": 0.02, "D": -0.03}
_D1_WEIGHTS = {"A": 0.025, "B": 0.375, "C": -0.225, "D": -0.375}

_BETAS = {
    _D0: {"A": 1.2, "C": 0.8},
    _D1: {"A": 1.2, "C": 0.8},
}


def _book_return(weights: dict[str, float], returns: dict[str, float]) -> float:
    return math.fsum(weights[symbol] * returns[symbol] for symbol in weights)


def _plain_weights(row: dict[str, float]) -> dict[str, float]:
    """The plain dollar-neutral book, independent of this module's arithmetic."""
    gross = sum(abs(value) for value in row.values())
    return {symbol: value / gross for symbol, value in row.items()}


def test_hand_computed_two_date_example_with_partial_beta_coverage():
    """Walks the rescaled weights by hand over two dates (see the comments above)."""
    scores = {_D0: _D0_SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    expected_d0 = _book_return(_D0_WEIGHTS, _D0_RETURNS)
    expected_d1 = _book_return(_D1_WEIGHTS, _D1_RETURNS)

    metrics = compute_node_metrics(
        _hand_priced(returns_by_date), scores, betas=_BETAS
    )

    assert metrics.book_returns[_D0] == pytest.approx(expected_d0)
    assert metrics.book_returns[_D1] == pytest.approx(expected_d1)

    # Turnover between the two (same symbol set both days):
    # |0.025-0.275| + |0.375-0.125| + |-0.225-(-0.475)| + |-0.375-(-0.125)|
    # = 0.25*4 = 1.0, halved.
    assert metrics.turnover_series[_D1] == pytest.approx(0.5)


def test_rescaled_weights_feed_the_cost_1_turnover_charge():
    """The same two dates, now with a turnover cost on the rescaled book."""
    scores = {_D0: _D0_SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    cost = 0.01
    # Entry traded (day 0, no predecessor) = gross of the rescaled book = 1.0.
    # Day 1's traded notional is 2x the turnover above (turnover halves it).
    expected_d0 = _book_return(_D0_WEIGHTS, _D0_RETURNS) - cost * 1.0
    expected_d1 = _book_return(_D1_WEIGHTS, _D1_RETURNS) - cost * 1.0

    metrics = compute_node_metrics(
        _hand_priced(returns_by_date),
        scores,
        betas=_BETAS,
        cost_per_unit_traded=cost,
    )

    assert metrics.book_returns[_D0] == pytest.approx(expected_d0)
    assert metrics.book_returns[_D1] == pytest.approx(expected_d1)


def test_ic_is_unchanged_by_betas_because_it_is_rank_based():
    """ic_mean/ic_tstat/ic_series depend only on scores and returns, not weights."""
    scores = {_D0: _D0_SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    priced = _hand_priced(returns_by_date)

    without_betas = compute_node_metrics(priced, scores)
    with_betas = compute_node_metrics(priced, scores, betas=_BETAS)

    assert with_betas.ic_series == without_betas.ic_series
    assert with_betas.ic_mean == pytest.approx(without_betas.ic_mean)
    assert with_betas.ic_tstat == pytest.approx(without_betas.ic_tstat)
    # But the book itself changed: the rescale moved the book returns.
    assert with_betas.book_returns != without_betas.book_returns


# -- 2. The book beta (Σ w·β) is 0 within 1e-12 when every symbol has a beta --

# Returns are pinned to equal each symbol's own beta that date, so the book's
# post-cost return, Σ w_i * r_i, *is* the book's beta, Σ w_i * β_i, letting
# the public book_returns field stand in for a weight the record does not
# otherwise expose.
_FULL_COVERAGE_BETAS = {
    _D0: {"A": 1.5, "B": 0.9, "C": 1.0, "D": 0.6, "E": 1.2},
    _D1: {"A": 1.5, "B": 0.9, "C": 1.0, "D": 0.6, "E": 1.2},
}
_FULL_COVERAGE_SCORES = {
    _D0: {"A": 4.0, "B": 2.0, "C": -3.0, "D": -2.0, "E": -1.0},
    _D1: {"A": 1.0, "B": 5.0, "C": -2.0, "D": -3.0, "E": -1.0},
}


def test_book_beta_is_zero_within_tolerance_when_every_symbol_is_rated():
    returns_by_date = {day: dict(row) for day, row in _FULL_COVERAGE_BETAS.items()}

    metrics = compute_node_metrics(
        _hand_priced(returns_by_date),
        _FULL_COVERAGE_SCORES,
        betas=_FULL_COVERAGE_BETAS,
    )

    assert len(metrics.book_returns) == 2
    for day, book_beta in metrics.book_returns.items():
        assert book_beta == pytest.approx(0.0, abs=1e-12), (day, book_beta)


# -- 3. None equals today's figures --------------------------------------------


def test_betas_none_is_the_default_and_reproduces_the_plain_book():
    scores = {_D0: _D0_SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    priced = _hand_priced(returns_by_date)

    omitted = compute_node_metrics(priced, scores)
    explicit_none = compute_node_metrics(priced, scores, betas=None)
    assert omitted == explicit_none
    assert omitted.book_returns == explicit_none.book_returns

    expected_d0 = _book_return(_plain_weights(_D0_SCORES), _D0_RETURNS)
    expected_d1 = _book_return(_plain_weights(_D1_SCORES), _D1_RETURNS)
    assert omitted.book_returns[_D0] == pytest.approx(expected_d0)
    assert omitted.book_returns[_D1] == pytest.approx(expected_d1)
    # And it differs from the beta-neutral book over the same panel.
    neutralized = compute_node_metrics(priced, scores, betas=_BETAS)
    assert neutralized.book_returns[_D0] != pytest.approx(omitted.book_returns[_D0])


# -- 4. The fallback on degenerate legs -----------------------------------------


def test_fallback_when_one_leg_has_no_rated_symbol():
    """Only long-leg symbols carry a beta; the short leg has none rated.

    A second, fully-rated control date (D1) is included only because
    ic_tstat needs at least two measured dates; the assertion is about D0.
    """
    scores = {_D0: _D0_SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    betas = {
        _D0: {"A": 1.2, "B": 0.5},  # both long-leg symbols; none short
        _D1: _BETAS[_D1],
    }

    metrics = compute_node_metrics(
        _hand_priced(returns_by_date), scores, betas=betas
    )

    expected = _book_return(_plain_weights(_D0_SCORES), _D0_RETURNS)
    assert metrics.book_returns[_D0] == pytest.approx(expected)


def test_fallback_when_beta_l_plus_beta_s_is_not_positive():
    """beta_L + beta_S <= 0 (a negative benchmark beta outweighing the other side)."""
    scores = {_D0: _D0_SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    betas = {
        _D0: {"A": -1.0, "C": 1.0},  # beta_L=-1.0, beta_S=1.0, sum=0.0
        _D1: _BETAS[_D1],
    }

    metrics = compute_node_metrics(
        _hand_priced(returns_by_date), scores, betas=betas
    )

    expected = _book_return(_plain_weights(_D0_SCORES), _D0_RETURNS)
    assert metrics.book_returns[_D0] == pytest.approx(expected)


def test_fallback_when_unrated_weight_exceeds_a_legs_target_gross():
    """The unrated member of a leg already claims more than that leg's gl/1-gl."""
    # Long leg: A (rated, small weight 0.1), B (unrated, large weight 0.4).
    # Short leg: C (rated, 0.3), D (rated, 0.2).
    d0_scores = {"A": 0.1, "B": 0.4, "C": -0.3, "D": -0.2}
    d0_returns = {"A": 0.01, "B": -0.02, "C": 0.05, "D": 0.03}
    scores = {_D0: d0_scores, _D1: _D1_SCORES}
    returns_by_date = {_D0: d0_returns, _D1: _D1_RETURNS}
    # beta_L = beta_A = 2.0 (only rated long), beta_S = (0.3*1+0.2*1)/0.5 = 1.0
    # gl = 1.0 / 3.0 = 1/3 ~= 0.3333, but B alone (unrated) already carries
    # 0.4 > gl, so the long leg's rated gross target (gl - 0.4) is negative.
    betas = {
        _D0: {"A": 2.0, "C": 1.0, "D": 1.0},
        _D1: _BETAS[_D1],
    }

    metrics = compute_node_metrics(
        _hand_priced(returns_by_date), scores, betas=betas
    )

    expected = _book_return(_plain_weights(d0_scores), d0_returns)
    assert metrics.book_returns[_D0] == pytest.approx(expected)


# -- 5. Non-finite betas are refused ---------------------------------------------


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_beta_is_refused(bad: float):
    scores = {_D0: _D0_SCORES}
    returns_by_date = {_D0: _D0_RETURNS}
    betas = {_D0: {"A": bad, "C": 0.8}}

    with pytest.raises(EvaluatorMetricsError, match="not finite|NaN"):
        compute_node_metrics(_hand_priced(returns_by_date), scores, betas=betas)


def test_non_numeric_beta_is_refused():
    scores = {_D0: _D0_SCORES}
    returns_by_date = {_D0: _D0_RETURNS}
    betas = {_D0: {"A": "1.2", "C": 0.8}}

    with pytest.raises(EvaluatorMetricsError, match="must be a number"):
        compute_node_metrics(_hand_priced(returns_by_date), scores, betas=betas)


def test_betas_keyed_by_datetime_is_refused():
    scores = {_D0: _D0_SCORES}
    returns_by_date = {_D0: _D0_RETURNS}
    betas = {dt.datetime(2026, 9, 1, 12): {"A": 1.2}}

    with pytest.raises(EvaluatorMetricsError, match="calendar dates"):
        compute_node_metrics(_hand_priced(returns_by_date), scores, betas=betas)


def test_betas_not_a_mapping_is_refused():
    scores = {_D0: _D0_SCORES}
    returns_by_date = {_D0: _D0_RETURNS}

    with pytest.raises(EvaluatorMetricsError, match="betas must map"):
        compute_node_metrics(
            _hand_priced(returns_by_date), scores, betas=["not", "a", "mapping"]
        )
