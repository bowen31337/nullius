"""additions_spec_forward_shadow.xml feature 1 — the research book's per-date
weights as one public function.

:func:`evaluator.book_weights` is the one spelling of the dollar-neutral,
gross-1 book (``w_i = z_i / Σ|z_j|``) and its optional beta-neutral leg
rescale (:func:`evaluator._metrics._beta_neutral_weights`) that
:func:`evaluator.compute_node_metrics` already computed privately, per date,
for its own book return and turnover. Exposing it publicly lets a forward
shadow (a daily job that scores a stored node on fresh data and writes a
venue book) trade exactly the book an evaluation scored, rather than a
second, possibly drifting, re-implementation of the same arithmetic —
:func:`~evaluator.compute_node_metrics` now calls this function for its own
per-date weights.

This suite is self-contained — it does not import ``test_metrics.py``'s or
``test_metrics_beta_neutral.py``'s fixtures, though it hand-verifies the same
two-leg example those suites already proved correct — and runs with no
database, so it is safe under pytest-xdist with no isolation beyond what the
module import needs.
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
    book_weights,
    compute_node_metrics,
)

_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)
_START = dt.date(2026, 9, 1)
_D0 = _START
_D1 = _START + dt.timedelta(days=1)


# -- 1. Hand-computed plain and beta-neutral examples ------------------------

# gross = |3|+|1|+|-3|+|-1| = 8.
_SCORES = {"A": 3.0, "B": 1.0, "C": -3.0, "D": -1.0}
_PLAIN_WEIGHTS = {"A": 0.375, "B": 0.125, "C": -0.375, "D": -0.125}
# A and B are the long leg (B carries no beta); C and D are the short leg (D
# carries no beta). beta_L = beta_A = 1.2 (A is the long leg's only rated
# symbol); beta_S = beta_C = 0.8 (C is the short leg's only rated symbol);
# gl = 0.8 / (1.2 + 0.8) = 0.4, so the long leg targets gross 0.4 and the
# short leg targets gross 0.6. B (unrated, long) keeps its weight 0.125
# unscaled, so A's rated gross must reach 0.4 - 0.125 = 0.275 (from 0.375:
# scale 0.275/0.375). D (unrated, short) keeps its weight -0.125 unscaled, so
# C's rated gross must reach 0.6 - 0.125 = 0.475 (from 0.375: scale
# 0.475/0.375). Rescaled weights: A=0.275, B=0.125, C=-0.475, D=-0.125.
_BETAS = {"A": 1.2, "C": 0.8}
_NEUTRAL_WEIGHTS = {"A": 0.275, "B": 0.125, "C": -0.475, "D": -0.125}


def test_hand_computed_plain_weights():
    assert book_weights(_SCORES) == pytest.approx(_PLAIN_WEIGHTS)


def test_hand_computed_beta_neutral_weights():
    assert book_weights(_SCORES, _BETAS) == pytest.approx(_NEUTRAL_WEIGHTS)


def test_betas_none_is_the_default_and_reproduces_the_plain_book():
    assert book_weights(_SCORES, None) == book_weights(_SCORES)


# -- 2. Net weight 0 and gross 1 within 1e-12 --------------------------------


def test_plain_book_is_net_zero_and_gross_one():
    # _SCORES is already cross-sectionally centered (3+1-3-1=0), so the
    # plain book's net weight is 0, not merely its gross.
    weights = book_weights(_SCORES)
    assert math.fsum(weights.values()) == pytest.approx(0.0, abs=1e-12)
    assert math.fsum(abs(v) for v in weights.values()) == pytest.approx(
        1.0, abs=1e-12
    )


def test_beta_neutral_book_stays_gross_one():
    # Net weight is not pinned to 0 under partial beta coverage (only the
    # rated symbols' net *beta* is, per item 3 below); total gross exposure
    # is always 1 regardless, because the two legs' targets (gl and 1-gl)
    # always sum to 1.
    weights = book_weights(_SCORES, _BETAS)
    assert math.fsum(abs(v) for v in weights.values()) == pytest.approx(
        1.0, abs=1e-12
    )


# -- 3. Book beta 0 within 1e-12 when every symbol has a beta ----------------

_FULL_COVERAGE_SCORES = {"A": 4.0, "B": 2.0, "C": -3.0, "D": -2.0, "E": -1.0}
_FULL_COVERAGE_BETAS = {"A": 1.5, "B": 0.9, "C": 1.0, "D": 0.6, "E": 1.2}


def test_book_beta_is_zero_within_tolerance_when_every_symbol_is_rated():
    weights = book_weights(_FULL_COVERAGE_SCORES, _FULL_COVERAGE_BETAS)
    book_beta = math.fsum(
        weights[symbol] * _FULL_COVERAGE_BETAS[symbol] for symbol in weights
    )
    assert book_beta == pytest.approx(0.0, abs=1e-12)


# -- 4. The degenerate-leg fallback ------------------------------------------


def test_fallback_when_one_leg_has_no_rated_symbol():
    """Only long-leg symbols carry a beta; the short leg has none rated."""
    betas = {"A": 1.2, "B": 0.5}
    assert book_weights(_SCORES, betas) == book_weights(_SCORES)


def test_fallback_when_beta_l_plus_beta_s_is_not_positive():
    """beta_L + beta_S <= 0 (a negative benchmark beta outweighing the other)."""
    betas = {"A": -1.0, "C": 1.0}  # beta_L=-1.0, beta_S=1.0, sum=0.0
    assert book_weights(_SCORES, betas) == book_weights(_SCORES)


def test_fallback_when_unrated_weight_exceeds_a_legs_target_gross():
    """The unrated member of a leg already claims more than that leg's target."""
    # Long leg: A (rated, small weight 0.1), B (unrated, large weight 0.4).
    # Short leg: C (rated, 0.3), D (rated, 0.2). beta_L=2.0, beta_S=1.0,
    # gl=1/3~=0.333, but B alone (unrated) already carries 0.4 > gl, so the
    # long leg's rated gross target (gl - 0.4) is negative.
    scores = {"A": 0.1, "B": 0.4, "C": -0.3, "D": -0.2}
    betas = {"A": 2.0, "C": 1.0, "D": 1.0}
    assert book_weights(scores, betas) == book_weights(scores)


# -- 5. The refusals ----------------------------------------------------------


def test_empty_scores_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="at least one"):
        book_weights({})


def test_zero_gross_scores_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="zero gross"):
        book_weights({"A": 0.0, "B": 0.0})


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_score_is_refused(bad: float):
    with pytest.raises(EvaluatorMetricsError, match="not finite|NaN"):
        book_weights({"A": bad, "B": 1.0})


def test_non_numeric_score_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="must be a number"):
        book_weights({"A": "1.0", "B": -1.0})


def test_scores_not_a_mapping_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="map symbol"):
        book_weights(["not", "a", "mapping"])


def test_empty_symbol_name_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="non-empty symbol"):
        book_weights({"": 1.0, "B": -1.0})


def test_betas_not_a_mapping_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="betas must map"):
        book_weights(_SCORES, betas=["not", "a", "mapping"])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_beta_is_refused(bad: float):
    with pytest.raises(EvaluatorMetricsError, match="not finite|NaN"):
        book_weights(_SCORES, betas={"A": bad})


def test_non_numeric_beta_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="must be a number"):
        book_weights(_SCORES, betas={"A": "1.2"})


# -- 6. Agreement with compute_node_metrics on a small synthetic panel -------

_D0_RETURNS = {"A": 0.04, "B": 0.02, "C": -0.01, "D": 0.03}
_D1_SCORES = {"A": 1.0, "B": 3.0, "C": -1.0, "D": -3.0}
_D1_RETURNS = {"A": 0.05, "B": -0.02, "C": 0.02, "D": -0.03}
_BETAS_BY_DATE = {_D0: _BETAS, _D1: _BETAS}


def _hand_priced(
    returns_by_date: dict[dt.date, dict[str, float]],
    *,
    horizon: int = 1,
) -> PostCostReturns:
    """A hand-built, single-horizon priced bundle — step 8's input (the same
    shape ``test_metrics_beta_neutral.py`` uses)."""
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


def test_compute_node_metrics_book_return_agrees_with_book_weights():
    """For one evaluation date, the book return ``compute_node_metrics``
    derives from its internal per-date weights equals ``book_weights``' own
    dot product with the same returns — the two cannot drift because the
    former calls the latter.
    """
    scores = {_D0: _SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    priced = _hand_priced(returns_by_date)

    metrics = compute_node_metrics(priced, scores)
    expected_weights = book_weights(_SCORES)
    expected_return = math.fsum(
        expected_weights[symbol] * _D0_RETURNS[symbol] for symbol in expected_weights
    )
    assert metrics.book_returns[_D0] == pytest.approx(expected_return)


def test_compute_node_metrics_beta_neutral_book_return_agrees_with_book_weights():
    scores = {_D0: _SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    priced = _hand_priced(returns_by_date)

    metrics = compute_node_metrics(priced, scores, betas=_BETAS_BY_DATE)
    expected_weights = book_weights(_SCORES, _BETAS)
    expected_return = math.fsum(
        expected_weights[symbol] * _D0_RETURNS[symbol] for symbol in expected_weights
    )
    assert metrics.book_returns[_D0] == pytest.approx(expected_return)


def test_entry_day_traded_notional_agrees_with_book_weights_gross():
    """COST-1's entry-day charge is the full cost of putting the book on —
    ``traded_d = Σ|w_d|`` for the first rebalance date, which has no
    predecessor to subtract against. On that date the charge behaves exactly
    as "turnover" would on a one-date panel: the whole book, not half of a
    change. Diffing an uncosted and a unit-costed run isolates that quantity,
    and it names ``book_weights``' own gross directly.
    """
    scores = {_D0: _SCORES, _D1: _D1_SCORES}
    returns_by_date = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}
    priced = _hand_priced(returns_by_date)

    uncosted = compute_node_metrics(priced, scores)
    costed = compute_node_metrics(priced, scores, cost_per_unit_traded=1.0)
    expected_gross = math.fsum(abs(v) for v in book_weights(_SCORES).values())

    assert uncosted.book_returns[_D0] - costed.book_returns[_D0] == pytest.approx(
        expected_gross
    )
