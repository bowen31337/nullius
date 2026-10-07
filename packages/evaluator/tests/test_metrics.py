"""Feature 80 — the node metrics: ic_mean, ic_tstat, ir_standalone, turnover.

app_spec.xml feature 80: *"System computes ic_mean, ic_tstat, ir_standalone
and turnover, persisting each as a scalar on the node record."*
docs/nullius-tech-architecture.md §6.1 names the step
(``compute_metrics    IC series, IR, turnover, decay, capacity, regime
attribution``), §9.1 names the four columns on the ``node`` table
(``ic_mean``, ``ic_tstat``, ``ir_standalone``, ``turnover``), and
docs/alpha-engine-prd.md's node block spells the same four under ``metrics``
(``ic_mean``, ``ic_tstat``, ``ir_standalone``, ``turnover``).

This suite tests the computation and the persistence as the two halves of one
feature sentence, because each is separately assertable and a bug in either
would be masked by the other:

* **the four scalars are measured from the post-cost returns** — asserted as
  the *property* that makes them the right scalars for this pipeline: they are
  computed from step 7's own record (a bundle that never went through the gate
  is refused), over the shortest horizon the priced panel covers, so a signal
  that earns its edge only after costs on the shortest horizon is the strongest
  claim the node can make;
* **``ic_mean`` is the mean of the per-date Spearman coefficient** — the *same*
  coefficient feature 81 measures, so it is invariant to any strictly
  increasing rescale of the score, exactly negated when the signal is read in
  reverse, and the mean of the very series the artifact files as
  ``ic_series.parquet``;
* **``ic_tstat`` is ``ic_mean`` over the standard error of the mean** — the
  population convention (the dates are the whole sample), with ``n ≥ 2``
  required, so a t-statistic over one date is refused rather than defaulted to
  a fabricated infinity;
* **``ir_standalone`` is the equal-weight book's information ratio** — the mean
  per-date unit-book post-cost return divided by its population standard
  deviation, and refused when that return never varies;
* **``turnover`` is the equal-weight book's mean per-date fractional
  turnover** — ``½ · Σ |w_d − w_{d−1}|`` averaged over the rebalances that have
  a predecessor;
* **the input contract** — step 7's own result and step 3's own output; a
  bundle that is not priced, a panel that covers no horizon, and scores that
  are malformed are all refused;
* **persistence** — the four scalars round-trip losslessly, a re-persist
  upserts rather than doubles, a node never measured reads back ``None``, and
  the read path refuses a tampered row (an ic_mean edited while its series was
  left alone);
* **the record** — read-only capture, hashability, and the hand-built
  invariants (a mean that is not its own series' mean, a date count that
  disagrees with the series it summarises, a turnover_dates that is not one
  fewer than the date count).

The priced bundle is produced by the real step-4-through-7 path where the
provenance matters (a stub oracle over a real alignment, a stub fee schedule —
the same fixtures ``test_costs.py`` and ``test_capacity.py`` use, because a
metric measured against a bundle that never went through the gate would be a
metric of a world nobody ran) and hand-built where the test is about step 8's
own contract.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
import os
import sqlite3
from contextlib import closing

import pytest
from evaluator import (
    HORIZONS,
    NODE_METRICS_TABLE,
    AlignedTargets,
    CostModelRef,
    CostQuote,
    CostRequest,
    EvaluatorMetricsError,
    EvaluatorStoreError,
    GatedTargets,
    NodeMetrics,
    OracleRequest,
    OracleResponse,
    PostCostReturns,
    PostCostSeries,
    RawScoreVector,
    SignalExecution,
    align_targets,
    apply_costs,
    compute_node_metrics,
    gate_targets,
    load_node_metrics,
    persist_node_metrics,
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


# The main scenario, on the same shape test_costs.py and test_capacity.py use:
# a 12-bar grid with three rebalance dates at its head — horizons 1, 2, 5 and
# 10 cover all three, horizon 20 covers none (the empty-but-carried case).
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_DAILY = [1.0 + 0.01 + 0.005 * i for i in range(11)]
_COMPOUND = [100.0]
for _rate in _DAILY:
    _COMPOUND.append(_COMPOUND[-1] * _rate)
_MAIN_EXECUTION = _execution(_REBALANCE)
_MAIN_CLOSES = {
    "AAA": dict(zip(_GRID, _COMPOUND)),
    "BBB": dict(zip(_GRID, [50.0] * 12)),
}
_MAIN_ALIGNED = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)


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

    Deliberately not the real cost library — §6.2 and feature 69 keep the fee
    arithmetic in one shared library, and this suite's job is to prove the
    evaluator's *metrics* half neither holds nor duplicates it.  The rate is
    nonzero so the scalars really are measured against net returns and not, by
    accident of a zero charge, against the gross ones.
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


def _gated(alignment: AlignedTargets = _MAIN_ALIGNED) -> GatedTargets:
    """Step 5's own result, through the real gate over a real alignment."""
    return gate_targets(
        alignment,
        _oracle(alignment),
        node_id="node_1",
        campaign_id="camp_1",
        depth=2,
    )


def _priced() -> PostCostReturns:
    """Step 7's own result, over the real steps 4 through 7."""
    return apply_costs(
        _gated(), _flat_schedule(), node_id="node_1", cost_model=_REF
    )


def _hand_priced(
    values_by_horizon: dict[int, dict[dt.date, dict[str, float]]],
    *,
    node_id: str = "node_1",
    snapshot_name: str = "snap_abc123",
    rebalance_dates: tuple[dt.date, ...] | None = None,
) -> PostCostReturns:
    """A hand-built priced bundle — step 8's input, built to the test's order.

    Hand-built because most of this suite is about step 8's *own* contract —
    the four scalars, the horizon, the refusals — which should be assertable
    without re-running steps 4 through 7 to arrange a shape.  Where the
    provenance of the bundle actually matters (the input-contract tests), the
    suite uses ``_priced``.
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


def _scores(
    per_date: dict[dt.date, dict[str, float]],
) -> dict[dt.date, dict[str, float]]:
    """The normalized scores — step 3's output — keyed by rebalance date."""
    return {day: dict(row) for day, row in per_date.items()}


def _flipped_scores(rebalance_dates: tuple[dt.date, ...]) -> dict[dt.date, dict[str, float]]:
    """Scores whose ranking alternates across the dates — so the per-date IC varies.

    ``_priced`` prices only AAA and BBB, and its AAA return always outranks BBB's,
    so a score ranking AAA above BBB every date gives the same coefficient on
    every date (ic_se zero, ic_tstat undefined).  Alternating the ranking makes
    the coefficient swing between +1 and −1, which is the variation ic_tstat and
    turnover need.  CCC is named to show it is simply ignored — it is not priced.
    """
    return {
        day: ({"AAA": 1.0, "BBB": -1.0, "CCC": 0.0} if index % 2 == 0 else {"AAA": -1.0, "BBB": 1.0, "CCC": 0.0})
        for index, day in enumerate(rebalance_dates)
    }


def _spearman_reference(
    scores: dict[str, float], returns: dict[str, float]
) -> float:
    """The Spearman correlation, spelled independently of the module under test.

    Spearman's coefficient *is* the Pearson correlation of the two
    cross-sections' average ranks, so that is what is written here — sorted
    positions, fractional ranks for ties, then the ordinary product-moment
    formula.  Spelled in its own terms rather than by calling anything in the
    package, so the suite pins the coefficient rather than trusting the
    implementation to define it.
    """
    symbols = sorted(set(scores) & set(returns))

    def ranks(values: dict[str, float]) -> dict[str, float]:
        ordered = sorted((values[symbol], symbol) for symbol in symbols)
        out: dict[str, float] = {}
        index = 0
        while index < len(ordered):
            stop = index
            while stop + 1 < len(ordered) and ordered[stop + 1][0] == ordered[index][0]:
                stop += 1
            for position in range(index, stop + 1):
                out[ordered[position][1]] = (index + stop + 2) / 2.0
            index = stop + 1
        return out

    score_ranks = ranks(scores)
    return_ranks = ranks(returns)
    count = float(len(symbols))
    score_mean = sum(score_ranks.values()) / count
    return_mean = sum(return_ranks.values()) / count
    covariance = sum(
        (score_ranks[s] - score_mean) * (return_ranks[s] - return_mean)
        for s in symbols
    )
    score_spread = sum((score_ranks[s] - score_mean) ** 2 for s in symbols)
    return_spread = sum((return_ranks[s] - return_mean) ** 2 for s in symbols)
    return covariance / math.sqrt(score_spread * return_spread)


def _ic_series_reference(
    scores_by_date: dict[dt.date, dict[str, float]],
    returns_by_date: dict[dt.date, dict[str, float]],
) -> dict[dt.date, float]:
    """The per-date IC series, by an independent spelling — the series ic_mean is over."""
    return {
        day: _spearman_reference(scores_by_date[day], returns_by_date[day])
        for day in sorted(set(scores_by_date) & set(returns_by_date))
    }


# A three-symbol, three-date panel whose per-date coefficients *vary* — the
# generic scenario most of the computation tests measure over.  The scores and
# the returns are deliberately not aligned in ranking, so the per-date IC is
# not constant (which would make ic_se zero and ic_tstat undefined) and the
# equal-weight book return is not constant (which would make ir_standalone
# undefined).
_D0 = _START
_D1 = _START + dt.timedelta(days=1)
_D2 = _START + dt.timedelta(days=2)
_VARIED_SCORES = {
    _D0: {"AAA": 1.0, "BBB": 0.0, "CCC": -1.0},
    _D1: {"AAA": 0.5, "BBB": -0.5, "CCC": 1.0},
    _D2: {"AAA": 0.2, "BBB": 1.0, "CCC": -0.5},
}
_VARIED_RETURNS = {
    _D0: {"AAA": 0.03, "BBB": 0.0, "CCC": -0.02},
    _D1: {"AAA": -0.03, "BBB": 0.01, "CCC": 0.02},
    _D2: {"AAA": 0.05, "BBB": -0.01, "CCC": -0.02},
}


# -- The horizon ----------------------------------------------------------------


def test_the_horizon_is_the_shortest_covered():
    """The four scalars are computed over the shortest horizon the panel covers."""
    # Horizons 1 and 5 both cover the three dates; horizon 2 covers none.  The
    # shortest covered horizon is 1, so the four scalars are computed over 1.
    priced = _hand_priced({1: _VARIED_RETURNS, 5: _VARIED_RETURNS})
    metrics = compute_node_metrics(priced, _scores(_VARIED_SCORES))
    assert metrics.horizon == 1


def test_a_panel_that_covers_no_horizon_is_refused():
    """A bundle whose every series is empty measured nothing — no metrics to store."""
    priced = _hand_priced({}, rebalance_dates=())
    scores = _scores({_START: {"AAA": 1.0, "BBB": -1.0}})
    with pytest.raises(EvaluatorMetricsError, match="covers no horizon"):
        compute_node_metrics(priced, scores)


def test_the_horizon_is_a_function_of_the_panel_not_a_knob():
    """Two deployments report the same four numbers for the same node."""
    priced = _hand_priced({2: _VARIED_RETURNS, 5: _VARIED_RETURNS})
    scores = _scores(_VARIED_SCORES)
    first = compute_node_metrics(priced, scores)
    again = compute_node_metrics(_hand_priced({2: _VARIED_RETURNS, 5: _VARIED_RETURNS}), scores)
    assert (first.ic_mean, first.ic_tstat, first.ir_standalone, first.turnover) == (
        again.ic_mean,
        again.ic_tstat,
        again.ir_standalone,
        again.turnover,
    )
    assert first.horizon == 2


# -- ic_mean --------------------------------------------------------------------


def test_ic_mean_is_the_mean_of_the_per_date_coefficient():
    """ic_mean is the equal-weight mean of the per-date Spearman coefficient."""
    priced = _hand_priced({1: _VARIED_RETURNS})
    metrics = compute_node_metrics(priced, _scores(_VARIED_SCORES))
    reference = _ic_series_reference(_VARIED_SCORES, _VARIED_RETURNS)
    assert metrics.horizon == 1
    assert metrics.dates == 3
    assert metrics.ic_mean == pytest.approx(sum(reference.values()) / len(reference))
    assert metrics.ic_series.keys() == set(reference)
    for day in reference:
        assert metrics.ic_series[day] == pytest.approx(reference[day])


def test_ic_mean_is_invariant_to_a_rescale_of_the_score():
    """A strictly increasing rescale of the score leaves ic_mean unchanged."""
    base = _VARIED_SCORES
    rescaled = {
        day: {sym: math.exp(value) * 100 + 5 for sym, value in row.items()}
        for day, row in base.items()
    }
    priced = _hand_priced({1: _VARIED_RETURNS})
    base_metrics = compute_node_metrics(priced, _scores(base))
    rescaled_metrics = compute_node_metrics(priced, _scores(rescaled))
    assert base_metrics.ic_mean == pytest.approx(rescaled_metrics.ic_mean)


def test_ic_mean_is_negated_when_the_signal_is_read_in_reverse():
    """Reading the signal in reverse negates ic_mean."""
    reverse = {day: {sym: -value for sym, value in row.items()} for day, row in _VARIED_SCORES.items()}
    priced = _hand_priced({1: _VARIED_RETURNS})
    forward_metrics = compute_node_metrics(priced, _scores(_VARIED_SCORES))
    reverse_metrics = compute_node_metrics(priced, _scores(reverse))
    assert forward_metrics.ic_mean == pytest.approx(-reverse_metrics.ic_mean)


# -- ic_tstat -------------------------------------------------------------------


def test_ic_tstat_is_mean_over_standard_error():
    """ic_tstat is ic_mean divided by the population standard error of the mean."""
    priced = _hand_priced({1: _VARIED_RETURNS})
    metrics = compute_node_metrics(priced, _scores(_VARIED_SCORES))
    reference = list(_ic_series_reference(_VARIED_SCORES, _VARIED_RETURNS).values())
    mean = sum(reference) / len(reference)
    variance = sum((value - mean) ** 2 for value in reference) / len(reference)
    standard_error = math.sqrt(variance) / math.sqrt(len(reference))
    assert metrics.ic_se == pytest.approx(standard_error)
    assert metrics.ic_tstat == pytest.approx(mean / standard_error)


def test_a_tstat_over_one_date_is_refused():
    """A t-statistic over one date names a zero standard error — refused, not infinity."""
    priced = _hand_priced({1: {_START: {"AAA": 0.01, "BBB": -0.01, "CCC": 0.0}}})
    scores = _scores({_START: {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0}})
    with pytest.raises(EvaluatorMetricsError, match="fewer than two|standard error"):
        compute_node_metrics(priced, scores)


def test_a_constant_per_date_coefficient_is_refused():
    """A metrics whose per-date IC never varies names a zero standard error — refused."""
    # Two symbols: the per-date IC is always +1 or -1 in magnitude.  Two dates
    # with the same ranking give a constant IC, so ic_se is zero.
    returns = {
        _START: {"AAA": 0.03, "BBB": -0.02},
        _START + dt.timedelta(days=1): {"AAA": 0.02, "BBB": -0.03},
    }
    priced = _hand_priced({1: returns})
    scores = _scores(
        {
            _START: {"AAA": 1.0, "BBB": -1.0},
            _START + dt.timedelta(days=1): {"AAA": 2.0, "BBB": -2.0},
        }
    )
    with pytest.raises(EvaluatorMetricsError, match="same information|standard error"):
        compute_node_metrics(priced, scores)


# -- ir_standalone --------------------------------------------------------------


def test_ir_standalone_is_the_signal_weighted_books_information_ratio():
    """ir_standalone is the mean signal-weighted book return over its population std.

    The book on each date is the dollar-neutral portfolio the day's own
    normalized scores define — ``w_i = z_i / Σ|z_j|`` over the symbols that
    date's scores and returns share — not the equal-weight market every node
    scored on the same snapshot would otherwise share. The expected book is
    hand-computed from that weight here, independently of the module under
    test's own weighting arithmetic.
    """
    priced = _hand_priced({1: _VARIED_RETURNS})
    metrics = compute_node_metrics(priced, _scores(_VARIED_SCORES))
    book = {}
    for day, returns_row in _VARIED_RETURNS.items():
        score_row = _VARIED_SCORES[day]
        symbols = sorted(set(score_row) & set(returns_row))
        gross = sum(abs(score_row[symbol]) for symbol in symbols)
        weights = {symbol: score_row[symbol] / gross for symbol in symbols}
        book[day] = sum(weights[symbol] * returns_row[symbol] for symbol in symbols)
    mean = sum(book.values()) / len(book)
    variance = sum((value - mean) ** 2 for value in book.values()) / len(book)
    std = math.sqrt(variance)
    assert metrics.ir_standalone == pytest.approx(mean / std)


def test_ir_standalone_is_refused_when_the_book_return_is_constant():
    """A book that never varies has no reward-to-variance ratio — refused, not zero."""
    # The scores are constant across dates (AAA=1.0, BBB=-1.0, CCC=0.0), so the
    # signal-weighted book is always w = {AAA: 0.5, BBB: -0.5, CCC: 0.0} — CCC
    # never enters the book return. AAA and BBB are pinned to 0.02 and 0.0 on
    # every date (book return 0.5*0.02 - 0.5*0.0 = 0.01, bit-identical each
    # time), while CCC alone varies to keep the per-date rank correlation (and
    # so ic_tstat) defined: CCC at 0.01 ranks between BBB and AAA (matching the
    # score ranking, IC = 1), at -0.01 ranks below both (IC = 0.5), and at 0.03
    # ranks above both (IC = 0.5) — not all equal, so ic_se is nonzero and this
    # test reaches the book-return refusal rather than the IC one.
    returns_by_date = {
        _START: {"AAA": 0.02, "BBB": 0.0, "CCC": 0.01},
        _START + dt.timedelta(days=1): {"AAA": 0.02, "BBB": 0.0, "CCC": -0.01},
        _START + dt.timedelta(days=2): {"AAA": 0.02, "BBB": 0.0, "CCC": 0.03},
    }
    priced = _hand_priced({1: returns_by_date})
    scores = _scores(
        {
            _START: {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0},
            _START + dt.timedelta(days=1): {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0},
            _START + dt.timedelta(days=2): {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0},
        }
    )
    with pytest.raises(EvaluatorMetricsError, match="constant|ir_standalone|dividing by zero"):
        compute_node_metrics(priced, scores)


# -- turnover -------------------------------------------------------------------


def test_turnover_is_the_mean_fractional_turnover():
    """turnover is ½·Σ|w_d − w_{d−1}| averaged over the rebalances with a predecessor.

    The weights are the signal weights ``w_i = z_i / Σ|z_j|``, not equal
    weight, so the book only moves when the *scores* change — here the scores
    are identical on the first two dates (so the book is identical, no matter
    that CCC's own return differs) and flip on the third, when CCC also drops
    out of the scored universe.
    """
    returns_by_date = {
        _START: {"AAA": 0.03, "BBB": -0.01, "CCC": 0.0},
        _START + dt.timedelta(days=1): {"AAA": -0.02, "BBB": 0.04, "CCC": 0.01},
        _START + dt.timedelta(days=2): {"AAA": 0.01, "BBB": 0.02},
    }
    priced = _hand_priced({1: returns_by_date})
    scores = _scores(
        {
            _START: {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0},
            _START + dt.timedelta(days=1): {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0},
            _START + dt.timedelta(days=2): {"AAA": -1.0, "BBB": 1.0},
        }
    )
    metrics = compute_node_metrics(priced, scores)
    # Day 0 and day 1 share the same scores over the same joined cross-section
    # {AAA, BBB, CCC}: gross = |1|+|-1|+|0| = 2, so w = {AAA: 0.5, BBB: -0.5,
    # CCC: 0.0} on both — identical books, so the first interval's turnover is
    # ½·(0 + 0 + 0) = 0.
    #
    # Day 2 scores {AAA: -1.0, BBB: 1.0} (CCC unscored): gross = |-1|+|1| = 2,
    # so w = {AAA: -0.5, BBB: 0.5} (CCC absent, weight 0). Against day 1's
    # {AAA: 0.5, BBB: -0.5, CCC: 0.0}, the second interval's turnover is
    # ½·(|-0.5-0.5| + |0.5-(-0.5)| + |0-0|) = ½·(1.0 + 1.0 + 0.0) = 1.0.
    #
    # Mean over the two intervals: (0 + 1.0) / 2 = 0.5.
    assert metrics.turnover == pytest.approx(0.5)
    assert metrics.turnover_dates == 2


# -- The input contract ---------------------------------------------------------


def test_a_bundle_that_never_went_through_the_gate_is_refused():
    """compute_node_metrics reduces step 7's own result, not a hand-made dict."""
    scores = _scores({_START: {"AAA": 1.0, "BBB": -1.0}})
    with pytest.raises(EvaluatorMetricsError, match="step 7"):
        compute_node_metrics({"not": "a bundle"}, scores)  # type: ignore[arg-type]


def test_a_scored_date_the_panel_never_prices_is_ignored():
    """A scored date the priced grid does not carry is not a pair — ignored."""
    returns_by_date = {
        _START: {"AAA": 0.03, "BBB": -0.02, "CCC": 0.01},
        _START + dt.timedelta(days=1): {"AAA": -0.01, "BBB": 0.04, "CCC": 0.0},
    }
    priced = _hand_priced({1: returns_by_date})
    scores = _scores(
        {
            _START: {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0},
            _START + dt.timedelta(days=1): {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0},
            # A third scored date the priced grid does not carry — not a pair,
            # so it is ignored and never appears in the series.
            _START + dt.timedelta(days=9): {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0},
        }
    )
    metrics = compute_node_metrics(priced, scores)
    assert metrics.dates == 2
    assert metrics.ic_series.keys() == {_START, _START + dt.timedelta(days=1)}


def test_a_symbol_one_side_carries_is_not_in_the_joined_cross_section():
    """A symbol one side carries and the other does not is simply not paired."""
    returns_by_date = {
        _START: {"AAA": 0.03, "BBB": -0.02, "CCC": 0.05},
        _START + dt.timedelta(days=1): {"AAA": 0.03, "BBB": -0.02, "CCC": 0.01},
    }
    priced = _hand_priced({1: returns_by_date})
    scores = _scores(
        {_START: {"AAA": 1.0, "BBB": -1.0}, _START + dt.timedelta(days=1): {"AAA": -1.0, "BBB": 1.0}}
    )  # no CCC — it is priced but not scored, so it is not in the joined cross-section
    metrics = compute_node_metrics(priced, scores)
    # Day 0 ranks AAA above BBB in both score and return (IC +1); day 1 ranks AAA
    # below BBB in the score but above it in the return (IC −1).  CCC is priced
    # but never scored, so it is excluded from both cross-sections.
    reference = (
        _spearman_reference({"AAA": 1.0, "BBB": -1.0}, {"AAA": 0.03, "BBB": -0.02})
        + _spearman_reference({"AAA": -1.0, "BBB": 1.0}, {"AAA": 0.03, "BBB": -0.02})
    ) / 2
    assert metrics.ic_mean == pytest.approx(reference)


def test_a_malformed_score_is_refused():
    """A non-finite score would reach the metrics dressed as a measurement."""
    priced = _hand_priced({1: {_START: {"AAA": 0.03, "BBB": -0.02, "CCC": 0.01}}})
    scores = _scores({_START: {"AAA": float("nan"), "BBB": -1.0, "CCC": 0.0}})
    with pytest.raises(EvaluatorMetricsError, match="not finite|NaN"):
        compute_node_metrics(priced, scores)


def test_a_datetime_keyed_score_is_refused():
    """The metrics pair one rebalance date's cross-section with that date's return."""
    priced = _hand_priced({1: {_START: {"AAA": 0.03, "BBB": -0.02, "CCC": 0.01}}})
    scores = {dt.datetime(2026, 9, 1): {"AAA": 1.0, "BBB": -1.0, "CCC": 0.0}}
    with pytest.raises(EvaluatorMetricsError, match="datetime"):
        compute_node_metrics(priced, scores)  # type: ignore[dict-item]


# -- Persistence ----------------------------------------------------------------


def test_the_four_scalars_round_trip():
    """The four scalars persist and read back losslessly, beside their series."""
    priced = _priced()
    scores = _scores(_flipped_scores(priced.rebalance_dates))
    metrics = compute_node_metrics(priced, scores)
    persist_node_metrics(metrics)
    loaded = load_node_metrics("node_1", _REF)
    assert loaded is not None
    assert loaded.horizon == metrics.horizon
    assert loaded.ic_mean == metrics.ic_mean
    assert loaded.ic_tstat == metrics.ic_tstat
    assert loaded.ir_standalone == metrics.ir_standalone
    assert loaded.turnover == metrics.turnover
    assert loaded.ic_series == metrics.ic_series


def test_a_repersist_upserts_rather_than_doubles():
    """A re-measurement over the same bundle refreshes the row, not adds a second."""
    priced = _priced()
    scores = _scores(_flipped_scores(priced.rebalance_dates))
    metrics = compute_node_metrics(priced, scores)
    persist_node_metrics(metrics)
    persist_node_metrics(metrics)
    with closing(sqlite3.connect(os.environ["DATABASE_URL"].split("///", 1)[1])) as connection:
        rows = connection.execute(
            f"SELECT COUNT(*) FROM {NODE_METRICS_TABLE}"
        ).fetchone()[0]
    assert rows == 1


def test_a_node_never_measured_reads_back_none():
    """The honest answer for an evaluation this store never measured is None."""
    assert load_node_metrics("node_never", _REF) is None


def test_a_tampered_row_is_refused():
    """An ic_mean edited while its series was left alone is refused, not trusted."""
    priced = _priced()
    scores = _scores(_flipped_scores(priced.rebalance_dates))
    metrics = compute_node_metrics(priced, scores)
    persist_node_metrics(metrics)
    with closing(sqlite3.connect(os.environ["DATABASE_URL"].split("///", 1)[1])) as connection, connection:
        connection.execute(
            f"UPDATE {NODE_METRICS_TABLE} SET ic_mean = ic_mean + 1"
        )
    with pytest.raises(EvaluatorStoreError, match="disagrees|does not reconstruct"):
        load_node_metrics("node_1", _REF)


def test_the_store_refuses_an_unconfigured_database():
    """A missing store is refused by name, not silently skipped."""
    priced = _priced()
    scores = _scores(_flipped_scores(priced.rebalance_dates))
    metrics = compute_node_metrics(priced, scores)
    with pytest.raises(EvaluatorStoreError, match="DATABASE_URL"):
        persist_node_metrics(metrics, database_url="")


# -- The record -----------------------------------------------------------------


def test_the_record_is_hashable_and_read_only():
    """The record is a frozen value: hashable, and its fields cannot be reassigned."""
    priced = _priced()
    scores = _scores(_flipped_scores(priced.rebalance_dates))
    metrics = compute_node_metrics(priced, scores)
    hash(metrics)
    with pytest.raises(dataclasses.FrozenInstanceError):
        metrics.ic_mean = 0.0  # type: ignore[misc]


def test_a_mean_that_is_not_its_own_series_mean_is_refused():
    """A hand-built record whose ic_mean disagrees with its series is refused."""
    with pytest.raises(EvaluatorMetricsError, match="disagrees with itself"):
        NodeMetrics(
            node_id="node_1",
            snapshot_name="snap_abc123",
            cost_model=_REF,
            horizon=1,
            dates=2,
            ic_mean=0.999,
            ic_se=0.1,
            ic_tstat=9.99,
            ir_standalone=0.5,
            turnover=0.3,
            turnover_dates=1,
            ic_series={_START: 0.1, _START + dt.timedelta(days=1): 0.2},
        )


def test_a_date_count_that_disagrees_with_the_series_is_refused():
    """A record whose date count disagrees with its series is refused."""
    with pytest.raises(EvaluatorMetricsError, match="denominator"):
        NodeMetrics(
            node_id="node_1",
            snapshot_name="snap_abc123",
            cost_model=_REF,
            horizon=1,
            dates=3,
            ic_mean=0.15,
            ic_se=0.1,
            ic_tstat=1.5,
            ir_standalone=0.5,
            turnover=0.3,
            turnover_dates=1,
            ic_series={_START: 0.1, _START + dt.timedelta(days=1): 0.2},
        )


def test_a_turnover_dates_that_disagrees_is_refused():
    """A record whose turnover_dates is not one fewer than the date count is refused."""
    with pytest.raises(EvaluatorMetricsError, match="turnover"):
        NodeMetrics(
            node_id="node_1",
            snapshot_name="snap_abc123",
            cost_model=_REF,
            horizon=1,
            dates=3,
            ic_mean=0.15,
            ic_se=0.1,
            ic_tstat=1.5,
            ir_standalone=0.5,
            turnover=0.3,
            turnover_dates=5,
            ic_series={
                _START: 0.1,
                _START + dt.timedelta(days=1): 0.2,
                _START + dt.timedelta(days=2): 0.15,
            },
        )
