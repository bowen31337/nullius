"""bug_spec_metrics_horizon.xml — compute_node_metrics gains a horizon keyword.

:func:`evaluator.compute_node_metrics` always measured the four scalars over
:data:`evaluator.METRICS_HORIZON` — the shortest horizon :data:`evaluator.
HORIZONS` names that the priced panel covers — and no caller had any way to
name the horizon an evaluation was actually configured for: a horizon-5
weekly config, or native-horizon OOS replay, both still reduced over whatever
horizon happened to be shortest. The fix gives :func:`compute_node_metrics` a
keyword-only ``horizon: int | None = None``: ``None`` (the default)
reproduces the old "shortest covered" policy byte-for-byte, and an explicit
``horizon`` measures the four scalars, ``ic_series``, ``book_returns`` and
``turnover_series`` over that horizon's series instead — refused, naming the
horizon asked for and the horizons the panel covers, when the spec does not
name it or the panel carries no rebalance date for it.

The fixture below prices the same three rebalance dates at both horizon 1 and
horizon 5, with a horizon-5 return row on each date built as the *exact
value-reversal* of that date's horizon-1 row (the same returns, reassigned to
symbols in the opposite rank order). Reversing a full ranking negates its
Spearman correlation against any fixed third ranking (reflection about the
mean rank flips every deviation's sign, leaving the standard deviations
unchanged), so the per-date coefficients at horizon 5 are exactly the
negation of horizon 1's, date for date — a clean, independently-checkable way
to prove the keyword actually changes which panel is reduced over, without
either horizon's per-date series being constant (which would trip the
existing "ic_se would be zero" refusal before the horizon selection is even
exercised).

Most of this suite builds its own fixture above, the way
``test_metrics_turnover_cost.py`` and ``test_metrics_beta_neutral.py`` do for
their own added keyword; one test additionally reuses ``test_metrics.py``'s
own main fixture (``_hand_priced``/``_VARIED_SCORES``/``_VARIED_RETURNS``) to
pin the same ``horizon=None`` equivalence against a bundle that suite's other
tests already exercise. It runs with no database beyond what
``test_metrics.py``'s own module-level fixture construction needs, so it is
safe under pytest-xdist with no isolation beyond what the module import
needs.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest
import test_metrics
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
_DATES = (_D0, _D1, _D2)


def _hand_priced(
    values_by_horizon: dict[int, dict[dt.date, dict[str, float]]],
    *,
    rebalance_dates: tuple[dt.date, ...] = _DATES,
) -> PostCostReturns:
    """A hand-built priced bundle covering more than one horizon at once."""
    series: dict[int, PostCostSeries] = {}
    for h in HORIZONS:
        values = values_by_horizon.get(h, {})
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
        rebalance_dates=rebalance_dates,
        cost_model=_REF,
        series=series,
        charges_budget=False,
    )


# The same cross-section every date (AAA > BBB > CCC), so the dollar-neutral
# book's weights — a function of the scores alone — stay constant across
# dates; only the *returns* differ per date and per horizon below.
_SCORES = {day: {"AAA": 3.0, "BBB": 2.0, "CCC": 1.0} for day in _DATES}

# Horizon-1 returns: D0 and D2 rank AAA > BBB > CCC exactly (same order as the
# scores, Spearman +1); D1 swaps the top two (BBB > AAA > CCC, Spearman
# +0.5) — the per-date coefficient is not constant, so ic_se is not zero, but
# every date is still positively correlated.
_H1_RETURNS = {
    _D0: {"AAA": 0.05, "BBB": 0.02, "CCC": -0.03},
    _D1: {"BBB": 0.04, "AAA": 0.03, "CCC": -0.02},
    _D2: {"AAA": 0.06, "BBB": 0.01, "CCC": -0.04},
}

# Horizon-5 returns: the exact value-reversal of the horizon-1 row on each
# date (the same three numbers, reassigned to symbols in the opposite rank
# order), which negates that date's coefficient exactly: +1 -> -1, +0.5 ->
# -0.5, +1 -> -1.
_H5_RETURNS = {
    _D0: {"CCC": 0.05, "BBB": 0.02, "AAA": -0.03},
    _D1: {"CCC": 0.04, "AAA": 0.03, "BBB": -0.02},
    _D2: {"CCC": 0.06, "BBB": 0.01, "AAA": -0.04},
}

# ic_mean is the equal-weight mean of the per-date coefficients: (1 + 0.5 +
# 1) / 3 at horizon 1, and its exact negation at horizon 5.
_EXPECTED_H1_IC_MEAN = 5.0 / 6.0
_EXPECTED_H5_IC_MEAN = -5.0 / 6.0

_PRICED = _hand_priced({1: _H1_RETURNS, 5: _H5_RETURNS})


def test_horizon_none_reproduces_the_shortest_covered_policy_byte_for_byte():
    """horizon=None is the same measurement as leaving the keyword out."""
    implicit = compute_node_metrics(_PRICED, _SCORES)
    explicit_none = compute_node_metrics(_PRICED, _SCORES, horizon=None)
    assert implicit == explicit_none
    for field in dataclasses.fields(implicit):
        left = getattr(implicit, field.name)
        right = getattr(explicit_none, field.name)
        if isinstance(left, float):
            assert left == pytest.approx(right, abs=1e-12)
        else:
            assert left == right
    assert implicit.horizon == 1
    assert implicit.ic_mean == pytest.approx(_EXPECTED_H1_IC_MEAN, abs=1e-12)


def test_an_explicit_horizon_measures_that_horizons_series():
    """horizon=5 reduces over the horizon-5 series, not the shortest covered."""
    metrics = compute_node_metrics(_PRICED, _SCORES, horizon=5)
    assert metrics.horizon == 5
    assert metrics.ic_mean == pytest.approx(_EXPECTED_H5_IC_MEAN, abs=1e-12)
    assert dict(metrics.ic_series) == {
        _D0: pytest.approx(-1.0),
        _D1: pytest.approx(-0.5),
        _D2: pytest.approx(-1.0),
    }
    # The sign of the evidence genuinely flipped between horizons — this is
    # the behaviour the bug made unreachable, not just a different number.
    default = compute_node_metrics(_PRICED, _SCORES)
    assert default.horizon == 1
    assert default.ic_mean > 0.0
    assert metrics.ic_mean < 0.0


def test_a_horizon_the_panel_does_not_cover_is_refused_naming_both():
    """A horizon the spec names but the panel has no rebalance date for."""
    with pytest.raises(EvaluatorMetricsError) as excinfo:
        compute_node_metrics(_PRICED, _SCORES, horizon=10)
    message = str(excinfo.value)
    assert "10" in message
    assert "1, 5" in message


def test_a_horizon_outside_the_spec_is_refused():
    """A horizon HORIZONS does not name at all (3 is not one of 1,2,5,10,20)."""
    assert 3 not in HORIZONS
    with pytest.raises(EvaluatorMetricsError, match="not one of the horizons"):
        compute_node_metrics(_PRICED, _SCORES, horizon=3)


def test_a_non_integer_horizon_is_refused():
    """A horizon must be an int or None — not silently coerced."""
    with pytest.raises(EvaluatorMetricsError):
        compute_node_metrics(_PRICED, _SCORES, horizon=5.0)  # type: ignore[arg-type]
    with pytest.raises(EvaluatorMetricsError):
        compute_node_metrics(_PRICED, _SCORES, horizon=True)  # type: ignore[arg-type]


def test_horizon_none_matches_an_existing_suites_fixture_to_1e_minus_12():
    """horizon=None, against test_metrics.py's own main fixture, to 1e-12.

    ``test_metrics.py`` is this package's own suite for compute_node_metrics,
    and its ``_hand_priced({1: _VARIED_RETURNS}, ...)`` / ``_VARIED_SCORES``
    pairing is the fixture ``test_the_horizon_is_the_shortest_covered`` and
    half a dozen other scalar tests already measure. Reusing it here (rather
    than only this file's own fixture above) pins the same equivalence
    against a bundle this suite already trusts independently.
    """
    priced = test_metrics._hand_priced({1: test_metrics._VARIED_RETURNS})
    scores = test_metrics._scores(test_metrics._VARIED_SCORES)
    implicit = compute_node_metrics(priced, scores)
    explicit_none = compute_node_metrics(priced, scores, horizon=None)
    assert implicit == explicit_none
    for field in dataclasses.fields(implicit):
        left = getattr(implicit, field.name)
        right = getattr(explicit_none, field.name)
        if isinstance(left, float):
            assert left == pytest.approx(right, abs=1e-12)
        else:
            assert left == right
    assert implicit.horizon == 1
