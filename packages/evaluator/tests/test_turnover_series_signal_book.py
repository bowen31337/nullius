"""Bug fix — ``turnover_series.parquet`` renders the signal-weighted book.

720f8f4 moved ``compute_node_metrics``'s ``turnover`` scalar to the node's own
signal-weighted book (``w_i = z_i / Σ|z_j|``), but left
``evaluator._artifact.render_turnover_series`` rebuilding an equal-weight book
(``1/n`` over each date's *priced* symbols) straight from the
``PostCostReturns`` panel — a renderer that receives no scores and so cannot
know the weights the scalar was reduced from. The artifact's per-date record
disagreed with the scalar it is supposed to be the per-date record of.

The fix carries ``NodeMetrics.turnover_series`` — the per-date series
``compute_node_metrics`` already reduces to ``turnover`` — and has
``render_turnover_series`` render that series rather than re-derive one. This
suite is the regression coverage the bug's own fix calls for:

* the rendered series' mean equals ``metrics.turnover`` by construction, even
  when the scored symbols differ from the priced ones (the case the old
  equal-weight reconstruction got wrong);
* two differently-weighted signals over the same panel render different
  series;
* a ``NodeMetrics`` rebuilt from the store (no ``turnover_series``, the shape
  :mod:`evaluator._metrics_store` reads back) is refused, not silently
  rendered from an equal-weight fallback.
"""

from __future__ import annotations

import datetime as dt

import pytest
from evaluator import (
    HORIZONS,
    CostModelRef,
    EvaluatorArtifactError,
    NodeMetrics,
    PostCostReturns,
    PostCostSeries,
    compute_node_metrics,
    render_turnover_series,
)

_START = dt.date(2026, 9, 1)
_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)


def _hand_priced(
    values_by_horizon: dict[int, dict[dt.date, dict[str, float]]],
    *,
    node_id: str = "node_1",
    snapshot_name: str = "snap_abc123",
) -> PostCostReturns:
    """A hand-built priced bundle — step 7's own result, built to the test's order."""
    days = tuple(
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
                day: {symbol: 0.001 for symbol in row} for day, row in values.items()
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


_D0 = _START
_D1 = _START + dt.timedelta(days=1)
_D2 = _START + dt.timedelta(days=2)

# Three symbols priced on every date; the scores below only ever name AAA and
# BBB, so the joined (book) cross-section is narrower than the priced one —
# the exact shape the old equal-weight-over-the-priced-panel rendering got
# wrong, because CCC was never in anyone's book. AAA's return outranks BBB's
# on days 0 and 2 but not on day 1, so the per-date rank correlation varies
# (not constant, which would leave ic_se and ic_tstat undefined).
_RETURNS = {
    _D0: {"AAA": 0.02, "BBB": -0.01, "CCC": 0.03},
    _D1: {"AAA": 0.05, "BBB": 0.01, "CCC": 0.01},
    _D2: {"AAA": 0.03, "BBB": 0.01, "CCC": -0.02},
}


def test_rendered_mean_matches_the_metrics_turnover_when_scored_differs_from_priced():
    """The rendered series' mean is metrics.turnover when scored ≠ priced symbols."""
    priced = _hand_priced({1: _RETURNS})
    scores = {
        _D0: {"AAA": 1.0, "BBB": -1.0},
        _D1: {"AAA": -1.0, "BBB": 1.0},
        _D2: {"AAA": 1.0, "BBB": -1.0},
    }
    metrics = compute_node_metrics(priced, scores)

    rendered = render_turnover_series(priced, metrics)

    assert len(rendered) == metrics.turnover_dates
    assert sum(rendered.values()) / len(rendered) == pytest.approx(metrics.turnover)
    # CCC is priced every date but scored on none, so it never enters the
    # book: the rendered series is exactly the metrics' own per-date series,
    # not a reconstruction over all three priced symbols.
    assert rendered == {
        day.isoformat(): value for day, value in metrics.turnover_series.items()
    }


def test_two_differently_weighted_signals_render_different_series():
    """Two signals with different per-symbol weights over one panel turn over differently.

    Both name all three symbols every date (so the book is a genuine
    three-way split rather than a single long/short pair, where any full
    sign flip between dates saturates turnover at 1.0 regardless of the
    magnitudes involved) — the two score sets put different relative weight
    on AAA, BBB and CCC, so the two books (and their per-date turnover) part
    ways.
    """
    priced = _hand_priced({1: _RETURNS})
    scores_a = {
        _D0: {"AAA": 2.0, "BBB": -1.0, "CCC": 0.5},
        _D1: {"AAA": 1.0, "BBB": -2.0, "CCC": 1.0},
        _D2: {"AAA": -1.0, "BBB": 1.0, "CCC": 2.0},
    }
    scores_b = {
        _D0: {"AAA": 1.0, "BBB": -2.0, "CCC": 1.0},
        _D1: {"AAA": 2.0, "BBB": -1.0, "CCC": 0.5},
        _D2: {"AAA": -2.0, "BBB": 0.5, "CCC": 1.0},
    }
    metrics_a = compute_node_metrics(priced, scores_a)
    metrics_b = compute_node_metrics(priced, scores_b)

    rendered_a = render_turnover_series(priced, metrics_a)
    rendered_b = render_turnover_series(priced, metrics_b)

    assert rendered_a != rendered_b
    assert sum(rendered_a.values()) / len(rendered_a) == pytest.approx(
        metrics_a.turnover
    )
    assert sum(rendered_b.values()) / len(rendered_b) == pytest.approx(
        metrics_b.turnover
    )


def test_a_record_without_turnover_series_is_refused_not_equal_weighted():
    """A NodeMetrics rebuilt from the store (no turnover_series) is refused."""
    priced = _hand_priced({1: _RETURNS})
    scores = {
        _D0: {"AAA": 1.0, "BBB": -1.0},
        _D1: {"AAA": -1.0, "BBB": 1.0},
        _D2: {"AAA": 1.0, "BBB": -1.0},
    }
    metrics = compute_node_metrics(priced, scores)
    # The shape evaluator._metrics_store.load_node_metrics reconstructs: the
    # four scalars and ic_series only, no book_returns and no turnover_series
    # — a record rebuilt from the store, not the one compute_node_metrics
    # produced.
    reloaded = NodeMetrics(
        node_id=metrics.node_id,
        snapshot_name=metrics.snapshot_name,
        cost_model=metrics.cost_model,
        horizon=metrics.horizon,
        dates=metrics.dates,
        ic_mean=metrics.ic_mean,
        ic_se=metrics.ic_se,
        ic_tstat=metrics.ic_tstat,
        ir_standalone=metrics.ir_standalone,
        turnover=metrics.turnover,
        turnover_dates=metrics.turnover_dates,
        ic_series=metrics.ic_series,
    )
    assert reloaded.turnover_series == {}

    with pytest.raises(EvaluatorArtifactError, match="turnover_series"):
        render_turnover_series(priced, reloaded)
