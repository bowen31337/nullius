"""Bug fix — ir_standalone, cost_adjusted_ir and turnover measure the node's
own book, not the equal-weight market.

bug_spec_first_scored_campaign.xml bug 1: four scored nodes with ic_mean
+0.0058, +0.0212, -0.0155 and -0.0116 all reported the *same* ir_standalone
and cost_adjusted_ir, because ``_metrics.py`` built each date's book return as
the equal-weight mean of every symbol's forward return — a number that never
reads the node's own scores, so every node scored on the same snapshot shared
one number regardless of what it scored.

The fix: the node's book on each rebalance date is the dollar-neutral
long-short portfolio its own normalized scores define over that date's joined
cross-section — weight ``w_i = z_i / Σ|z_j|``, so gross exposure is 1 and net
is 0 — and ``ir_standalone``, ``turnover`` and (via
:attr:`~evaluator.NodeMetrics.book_returns`) ``cost_adjusted_ir`` all reduce
from that book's per-date returns rather than the market's.

This suite tests :func:`evaluator.compute_node_metrics` directly, with
hand-built priced bundles (the same ``_hand_priced`` shape ``test_metrics.py``
uses) so each scenario is exact and provenance-free. ``book_returns`` is
asserted directly rather than through a full ``persist_node`` round trip,
because :mod:`evaluator._persist_store`'s ``cost_adjusted_ir`` is now nothing
more than the mean of that one field (``math.fsum(book_returns.values()) /
len(book_returns)``) — proving the field is the node's own signal-weighted
book is exactly what proves the cost-adjusted axis is too.
"""

from __future__ import annotations

import datetime as dt
import math
import random

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


def _days(count: int, start: dt.date = _START) -> tuple[dt.date, ...]:
    return tuple(start + dt.timedelta(days=i) for i in range(count))


def _hand_priced(
    returns_by_date: dict[dt.date, dict[str, float]],
    *,
    horizon: int = 1,
    node_id: str = "node_1",
    snapshot_name: str = "snap_abc123",
) -> PostCostReturns:
    """A hand-built step-7 result over one horizon — the others carried empty.

    Mirrors ``test_metrics.py``'s ``_hand_priced`` (kept local rather than
    imported, so this suite stands on its own): a fixed, nonzero charge is
    folded into every value, so this is unmistakably a *post-cost* return and
    not a gross one reused by accident.
    """
    days = tuple(sorted(returns_by_date))
    series: dict[int, PostCostSeries] = {}
    for h in HORIZONS:
        values = returns_by_date if h == horizon else {}
        series[h] = PostCostSeries(
            horizon=h,
            snapshot_name=snapshot_name,
            venue=_VENUE,
            version=_VERSION,
            values={day: dict(row) for day, row in values.items()},
            charges={
                day: {symbol: 0.0005 for symbol in row}
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


def _negate(scores: dict[dt.date, dict[str, float]]) -> dict[dt.date, dict[str, float]]:
    return {day: {sym: -value for sym, value in row.items()} for day, row in scores.items()}


def _equal_weight_mean(returns_by_date: dict[dt.date, dict[str, float]], day: dt.date) -> float:
    row = returns_by_date[day]
    return sum(row.values()) / len(row)


# -- Two opposite signals: equal-magnitude, opposite-sign IR --------------------


# The scores and the returns are deliberately not aligned in ranking, so the
# per-date IC is not constant (a constant IC gives a zero ic_se, refused) and
# the resulting book return is not constant either (a constant book return
# gives a zero ir_standalone denominator, refused).
_OPPOSITE_RETURNS = {
    _START: {"A": 0.03, "B": 0.0, "C": -0.02},
    _START + dt.timedelta(days=1): {"A": -0.03, "B": 0.01, "C": 0.02},
    _START + dt.timedelta(days=2): {"A": 0.05, "B": -0.01, "C": -0.02},
}
_OPPOSITE_SCORES = {
    _START: {"A": 1.0, "B": 0.0, "C": -1.0},
    _START + dt.timedelta(days=1): {"A": 0.5, "B": -0.5, "C": 1.0},
    _START + dt.timedelta(days=2): {"A": 0.2, "B": 1.0, "C": -0.5},
}


def test_opposite_signals_give_equal_magnitude_opposite_sign_ir():
    """Reading the signal in reverse mirrors the book, not the market.

    Before the fix, ``per_date_return`` was the equal-weight market mean,
    which does not depend on the scores at all — so ``s`` and ``-s`` reported
    the *same* ir_standalone. The dollar-neutral book flips sign exactly when
    every weight does, so the fixed ir_standalone must be exact negations.
    """
    priced = _hand_priced(_OPPOSITE_RETURNS)
    forward = compute_node_metrics(priced, _OPPOSITE_SCORES)
    reverse = compute_node_metrics(priced, _negate(_OPPOSITE_SCORES))

    assert forward.ic_mean == pytest.approx(-reverse.ic_mean)  # unchanged by this fix
    assert abs(forward.ir_standalone) > 1e-6, "the scenario must carry a real edge"
    assert reverse.ir_standalone == pytest.approx(-forward.ir_standalone)
    assert abs(reverse.ir_standalone) == pytest.approx(abs(forward.ir_standalone))
    # The bug, named directly: before the fix these two were equal.
    assert forward.ir_standalone != pytest.approx(reverse.ir_standalone)


def test_book_returns_are_the_signals_book_not_the_equal_weight_market():
    """``book_returns`` — what cost_adjusted_ir reduces — mirrors the signal.

    ``_persist_store._cost_adjusted_ir`` is the mean of
    :attr:`NodeMetrics.book_returns`; proving this series is the node's own
    weighted book (and not the one equal-weight market every node scored on
    the same snapshot would share) is exactly what proves cost_adjusted_ir is
    fixed too.
    """
    priced = _hand_priced(_OPPOSITE_RETURNS)
    forward = compute_node_metrics(priced, _OPPOSITE_SCORES)
    reverse = compute_node_metrics(priced, _negate(_OPPOSITE_SCORES))

    assert forward.book_returns.keys() == forward.ic_series.keys()
    for day in forward.book_returns:
        # Exact negation between opposite signals...
        assert reverse.book_returns[day] == pytest.approx(-forward.book_returns[day])
    # ...and not, on at least one date, the equal-weight market mean the bug
    # reported for every node regardless of its scores (compared as a whole
    # series rather than date by date, since one date's book return and
    # market mean can coincide by chance without the series being equal).
    market = {day: _equal_weight_mean(_OPPOSITE_RETURNS, day) for day in forward.book_returns}
    assert any(
        abs(forward.book_returns[day] - market[day]) > 1e-6 for day in forward.book_returns
    )

    forward_cost_adjusted_ir = math.fsum(forward.book_returns.values()) / len(
        forward.book_returns
    )
    reverse_cost_adjusted_ir = math.fsum(reverse.book_returns.values()) / len(
        reverse.book_returns
    )
    assert reverse_cost_adjusted_ir == pytest.approx(-forward_cost_adjusted_ir)


# -- An uncorrelated signal: IR near zero over a long seeded panel --------------


def test_uncorrelated_signal_has_ir_near_zero_over_a_long_panel():
    """A signal independent of the returns has no edge to weight into a book."""
    rng = random.Random(20260928)
    symbols = ("A", "B", "C", "D", "E")
    dates = _days(200)
    returns_by_date = {
        day: {symbol: rng.gauss(0.0, 0.01) for symbol in symbols} for day in dates
    }
    scores = {
        day: {symbol: rng.gauss(0.0, 1.0) for symbol in symbols} for day in dates
    }
    priced = _hand_priced(returns_by_date)
    metrics = compute_node_metrics(priced, scores)
    assert metrics.dates == len(dates)
    assert abs(metrics.ir_standalone) < 0.3


def test_perfect_foresight_signal_has_a_large_positive_ir():
    """A signal that tracks the forward return earns a large, positive IR.

    Weighting each symbol roughly by its own realized return makes every
    date's book return close to a sum of squares over a gross-exposure-1 book
    — rarely small and essentially never negative — so the reward-to-variance
    ratio across dates is large. The score is the return plus a small
    independent perturbation rather than the return exactly: scoring the
    return exactly would make the per-date rank correlation exactly +1.0 on
    *every* date (a literal identity has no order for the perturbation to
    reshuffle), which is the constant-IC case ic_tstat refuses — a refusal
    that would fire regardless of the book-weighting fix and so would prove
    nothing about it.
    """
    rng = random.Random(20260929)
    symbols = ("A", "B", "C", "D", "E")
    dates = _days(60)
    returns_by_date = {
        day: {symbol: rng.gauss(0.0, 0.01) for symbol in symbols} for day in dates
    }
    scores = {
        day: {symbol: value + rng.gauss(0.0, 0.002) for symbol, value in row.items()}
        for day, row in returns_by_date.items()
    }
    priced = _hand_priced(returns_by_date)
    metrics = compute_node_metrics(priced, scores)
    assert metrics.ir_standalone > 1.0


# -- Turnover: zero for an unchanging ranking, maximal for a full reversal ------


# Four symbols (not three): with only three, half of the nonzero return
# patterns collide on the same Spearman value against any fixed reference
# ranking, which makes it easy to build a scenario whose per-date IC is
# accidentally constant (refused) while the book return still varies as
# intended. Four symbols give enough permutations that the two properties
# this section wants — the IC varies, the book does what the formula says —
# can be chosen independently.
_UNCHANGING_RANKING_SCORES = {
    day: {"A": 1.5, "B": 0.5, "C": -0.5, "D": -1.5} for day in _days(2)
}
_UNCHANGING_RANKING_RETURNS = {
    _START: {"A": 0.05, "B": 0.02, "C": 0.01, "D": -0.01},
    _START + dt.timedelta(days=1): {"A": 0.01, "B": 0.05, "C": -0.01, "D": 0.02},
}


def test_turnover_is_zero_for_an_unchanging_ranking():
    """The same scores every date hold the same book — no weight changes hands."""
    priced = _hand_priced(_UNCHANGING_RANKING_RETURNS)
    metrics = compute_node_metrics(priced, _UNCHANGING_RANKING_SCORES)
    assert metrics.turnover_dates == 1
    assert metrics.turnover == pytest.approx(0.0)


_FULL_REVERSAL_SCORES = {
    _START: {"A": 1.5, "B": 0.5, "C": -0.5, "D": -1.5},
    _START + dt.timedelta(days=1): {"A": -1.5, "B": -0.5, "C": 0.5, "D": 1.5},
}
# The same returns both dates: against day 0's score the ranking matches
# exactly (IC +1); against day 1's exactly negated score it is the exact
# reverse (IC -1) — varying IC, from a book that flips to its own negation.
_FULL_REVERSAL_RETURNS = {
    day: {"A": 0.05, "B": 0.02, "C": 0.01, "D": -0.01} for day in _days(2)
}


def test_turnover_is_maximal_for_a_full_reversal():
    """The book flipping to its exact negation turns over the whole of itself.

    ``w_{d} = -w_{d-1}`` makes ``½ · Σ|w_d - w_{d-1}| = ½ · Σ|2w_{d-1}| = 1``
    for a gross-exposure-1 book — the largest a bounded turnover can be.
    """
    priced = _hand_priced(_FULL_REVERSAL_RETURNS)
    metrics = compute_node_metrics(priced, _FULL_REVERSAL_SCORES)
    assert metrics.turnover_dates == 1
    assert metrics.turnover == pytest.approx(1.0)


# -- A dollar-neutral book is unmoved by the market's own average return -------


# Four symbols, so the per-date rank pattern has enough permutations that an
# exact-zero-sum, constant score still measures a genuinely varying per-date
# IC (with three symbols, half the possible rank patterns collide on the same
# correlation value — see ``_CONSTANT_BOOK_RETURNS`` below, where that
# collision is instead the point).
_NEUTRAL_SCORES = {
    day: {"A": 1.5, "B": 0.5, "C": -0.5, "D": -1.5} for day in _days(3)
}
_NEUTRAL_RETURNS = {
    _START: {"A": 0.04, "B": 0.02, "C": 0.01, "D": -0.01},
    _START + dt.timedelta(days=1): {"A": -0.01, "B": 0.01, "C": 0.02, "D": 0.04},
    _START + dt.timedelta(days=2): {"A": 0.02, "B": 0.05, "C": -0.01, "D": 0.0},
}


def test_markets_average_return_does_not_move_a_dollar_neutral_book():
    """Adding a constant to every return that date cannot move a net-zero book.

    Before the fix, the market's own average return *was* the book's return
    (the per-date equal-weight mean), so shifting every symbol by the same
    amount shifted the reported IR. A book whose weights sum to zero nets the
    shift away exactly.
    """
    shift = 0.1
    shifted_returns = {
        day: {symbol: value + shift for symbol, value in row.items()}
        for day, row in _NEUTRAL_RETURNS.items()
    }
    unshifted = compute_node_metrics(_hand_priced(_NEUTRAL_RETURNS), _NEUTRAL_SCORES)
    shifted = compute_node_metrics(_hand_priced(shifted_returns), _NEUTRAL_SCORES)

    for day in unshifted.book_returns:
        assert shifted.book_returns[day] == pytest.approx(unshifted.book_returns[day])
    assert shifted.ir_standalone == pytest.approx(unshifted.ir_standalone)
    # The market itself manifestly moved — the equal-weight mean would not
    # have been invariant, which is the property the bug violated.
    assert _equal_weight_mean(shifted_returns, _START) != pytest.approx(
        _equal_weight_mean(_NEUTRAL_RETURNS, _START)
    )


# -- The "constant book" refusal still fires, on the node's own book -----------


# A and B carry the book's whole weight (+0.5 / -0.5) and are held to the
# same two values on every date; C and D tie at the cross-sectional mean
# score (0.0) and so carry weight 0 — multiplying a weight of exactly 0.0
# against whatever C and D return contributes exactly 0.0 to the book's sum,
# so the book return is bit-for-bit the same each day no matter where C and
# D fall. Moving C and D *between* A and B on one date (instead of outside
# both, as on the others) changes which symbols are adjacent in that date's
# joined cross-section, which is enough to move the per-date rank
# correlation without touching the book at all.
_CONSTANT_BOOK_SCORES = {
    day: {"A": 1.0, "B": -1.0, "C": 0.0, "D": 0.0} for day in _days(3)
}
_CONSTANT_BOOK_RETURNS = {
    _START: {"A": 0.05, "B": 0.03, "C": 0.10, "D": -0.05},
    _START + dt.timedelta(days=1): {"A": 0.05, "B": 0.03, "C": 0.04, "D": 0.10},
    _START + dt.timedelta(days=2): {"A": 0.05, "B": 0.03, "C": 0.01, "D": 0.04},
}


def test_a_constant_dollar_neutral_book_is_still_refused():
    """The refusal's meaning is unchanged: a book that never varies has no IR.

    Constructed so the *node's own* weighted book return is constant across
    dates — not the market's, which is what the pre-fix refusal actually
    checked.
    """
    priced = _hand_priced(_CONSTANT_BOOK_RETURNS)
    # "constant" only appears in ir_standalone's own refusal message (not
    # ic_tstat's "same information coefficient" one), so a match here proves
    # this scenario's per-date IC does vary and the book return is what was
    # refused.
    with pytest.raises(EvaluatorMetricsError, match="constant"):
        compute_node_metrics(priced, _CONSTANT_BOOK_SCORES)
