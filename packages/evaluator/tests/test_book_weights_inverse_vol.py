"""additions_spec_engine_edge_recovery.xml feature 1 — inverse-volatility weights.

A correct ranking of a crypto cross-section is not a tradable book: three to
five times of volatility dispersion across names means the plain
``w_i = z_i / Σ|z_j|`` book hands most of its gross to the few most volatile
names, so a signal whose ordering is right can still lose money on the names
whose noise dominates.  :func:`evaluator.book_weights` therefore gains a
keyword-only ``vols`` (and :func:`evaluator.compute_node_metrics` a keyword-only
``vols`` panel), and with it each score is divided by its own symbol's
volatility before the book is normalized: ``w_i ∝ z_i / vol_i``, still gross 1
and net 0, with the existing beta-neutral leg rescale applied *after* the vol
scaling.  A symbol missing from ``vols``, or carrying a non-finite or
non-positive one, is refused by name rather than silently defaulted.

This suite is self-contained — it does not import ``test_metrics.py``'s,
``test_book_weights.py``'s or ``test_metrics_beta_neutral.py``'s fixtures — and
runs with no database, so it is safe under pytest-xdist with no isolation
beyond what the module import needs.
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
from evaluator._metrics import _beta_neutral_weights

_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)
_START = dt.date(2026, 9, 1)
_D0 = _START
_D1 = _START + dt.timedelta(days=1)

# The same hand-computed cross-section ``test_book_weights.py`` pins: gross
# |3|+|1|+|-3|+|-1| = 8 -> A=0.375, B=0.125, C=-0.375, D=-0.125.
_SCORES = {"A": 3.0, "B": 1.0, "C": -3.0, "D": -1.0}
_PLAIN_WEIGHTS = {"A": 0.375, "B": 0.125, "C": -0.375, "D": -0.125}

_D0_RETURNS = {"A": 0.04, "B": 0.02, "C": -0.01, "D": 0.03}
_D1_SCORES = {"A": 1.0, "B": 3.0, "C": -1.0, "D": -3.0}
_D1_RETURNS = {"A": 0.05, "B": -0.02, "C": 0.02, "D": -0.03}


def _hand_priced(
    returns_by_date: dict[dt.date, dict[str, float]],
    *,
    horizon: int = 1,
) -> PostCostReturns:
    """A hand-built, single-horizon priced bundle — step 8's input (the shape
    ``test_metrics_beta_neutral.py`` and ``test_book_weights.py`` use)."""
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


def _scaled_weights(scores: dict[str, float], vols: dict[str, float]) -> dict[str, float]:
    """The inverse-vol book spelled out independently of the module."""
    scaled = {symbol: value / vols[symbol] for symbol, value in scores.items()}
    gross = sum(abs(value) for value in scaled.values())
    return {symbol: value / gross for symbol, value in scaled.items()}


# -- 1. vols=None is today's book exactly ------------------------------------


def test_vols_none_reproduces_todays_weights_exactly():
    assert book_weights(_SCORES, vols=None) == book_weights(_SCORES)
    assert book_weights(_SCORES, vols=None) == _PLAIN_WEIGHTS


def test_vols_of_all_ones_leaves_the_weights_unchanged():
    """Dividing every score by 1 is the identity on the normalized book."""
    ones = {symbol: 1.0 for symbol in _SCORES}
    assert book_weights(_SCORES, vols=ones) == pytest.approx(book_weights(_SCORES))


# -- 2. Two names, equal scores, vols 1 and 4 -> 4:1 --------------------------


def test_two_name_fixture_gets_weights_four_to_one_in_magnitude():
    # z/vol: A = 1/1 = 1, B = -1/4 = -0.25; gross = 1.25 -> A = +0.8, B = -0.2.
    weights = book_weights({"A": 1.0, "B": -1.0}, vols={"A": 1.0, "B": 4.0})
    assert weights == pytest.approx({"A": 0.8, "B": -0.2})
    assert abs(weights["A"] / weights["B"]) == pytest.approx(4.0)


def test_the_low_volatility_name_is_the_one_that_gets_the_gross():
    """The whole point: the quiet name carries the book, not the loud one."""
    loud = book_weights({"A": 1.0, "B": -1.0})
    quiet = book_weights({"A": 1.0, "B": -1.0}, vols={"A": 0.25, "B": 4.0})
    assert abs(quiet["A"]) > abs(loud["A"])
    assert abs(quiet["A"]) / abs(quiet["B"]) == pytest.approx(16.0)


# -- 3. Gross 1 and net 0 with vols ------------------------------------------


def test_inverse_vol_book_is_gross_one_and_net_zero():
    # _SCORES is centered (3+1-3-1 = 0) and each offsetting pair (A/C, B/D)
    # carries the same vol, so dividing by positive vols leaves the scaled
    # cross-section centered too and the book's net weight at 0.
    vols = {"A": 0.5, "B": 2.0, "C": 0.5, "D": 2.0}
    weights = book_weights(_SCORES, vols=vols)
    assert math.fsum(abs(v) for v in weights.values()) == pytest.approx(1.0, abs=1e-12)
    assert math.fsum(weights.values()) == pytest.approx(0.0, abs=1e-12)
    assert weights == pytest.approx(_scaled_weights(_SCORES, vols))


def test_an_asymmetric_vols_panel_grosses_one_even_though_net_need_not_be_zero():
    """Gross exposure is 1 unconditionally; net 0 is a property of the scores.

    A per-symbol positive scale does not preserve the *sum* of a centered
    cross-section, so an inverse-vol book can carry a small net tilt — which
    is why the net-zero pin above uses a vols panel that is symmetric across
    each offsetting pair.
    """
    vols = {"A": 0.5, "B": 2.0, "C": 1.0, "D": 0.25}
    weights = book_weights(_SCORES, vols=vols)
    assert math.fsum(abs(v) for v in weights.values()) == pytest.approx(1.0, abs=1e-12)
    assert math.fsum(weights.values()) != pytest.approx(0.0, abs=1e-12)


# -- 4. The beta rescale composes after the vol scaling ----------------------


# A and B are the long leg (B carries no beta); C and D are the short leg (D
# carries no beta). beta_L = beta_A = 1.2, beta_S = beta_C = 0.8, gl = 0.4 —
# the same split test_book_weights.py hand-computes, so the vol-scaled weights
# here are known and the rescale can be checked against _beta_neutral_weights.
_BETAS = {"A": 1.2, "C": 0.8}
_VOLS = {"A": 0.5, "B": 2.0, "C": 1.0, "D": 0.25}


def test_beta_rescale_composes_after_vol_scaling():
    vols = _VOLS
    scaled = _scaled_weights(_SCORES, vols)
    expected = _beta_neutral_weights(scaled, _BETAS)

    weights = book_weights(_SCORES, _BETAS, vols=vols)

    assert weights == pytest.approx(expected)
    # And it is genuinely not either transform alone.
    assert weights != pytest.approx(book_weights(_SCORES, _BETAS))
    assert weights != pytest.approx(book_weights(_SCORES, vols=vols))


def test_vol_scaled_beta_neutral_book_stays_gross_one():
    weights = book_weights(_SCORES, _BETAS, vols=_VOLS)
    assert math.fsum(abs(v) for v in weights.values()) == pytest.approx(1.0, abs=1e-12)


def test_beta_rescale_is_computed_on_the_vol_scaled_weights_not_the_plain_ones():
    """The beta split moves when the weights move — proof of the order.

    On this fixture the vol scaling concentrates the long leg in A (0.5 vol)
    and the short leg in C (1.0 vol), so the leg betas the rescale sees are
    the scaled ones' betas, not the plain book's.
    """
    plain = _beta_neutral_weights(book_weights(_SCORES), _BETAS)
    reversed_order = _scaled_weights(
        {symbol: value for symbol, value in plain.items()}, _VOLS
    )
    assert book_weights(_SCORES, _BETAS, vols=_VOLS) != pytest.approx(reversed_order)


# -- 5. The refusals, by name -------------------------------------------------


def test_missing_vol_is_refused_by_name():
    with pytest.raises(EvaluatorMetricsError, match="'C'"):
        book_weights(_SCORES, vols={"A": 1.0, "B": 1.0, "D": 1.0})


def test_missing_vol_refusal_names_the_symbol_and_the_parameter():
    with pytest.raises(EvaluatorMetricsError, match="missing from book_weights' vols"):
        book_weights(_SCORES, vols={"A": 1.0, "B": 1.0, "C": 1.0})


@pytest.mark.parametrize("bad", [0.0, -1.0, -0.5])
def test_non_positive_vol_is_refused_by_name(bad: float):
    vols = {"A": bad, "B": 1.0, "C": 1.0, "D": 1.0}
    with pytest.raises(EvaluatorMetricsError, match="'A'") as excinfo:
        book_weights(_SCORES, vols=vols)
    assert "not positive" in str(excinfo.value)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_vol_is_refused(bad: float):
    vols = {"A": bad, "B": 1.0, "C": 1.0, "D": 1.0}
    with pytest.raises(EvaluatorMetricsError, match="not finite|NaN"):
        book_weights(_SCORES, vols=vols)


def test_non_numeric_vol_is_refused():
    vols = {"A": "0.5", "B": 1.0, "C": 1.0, "D": 1.0}
    with pytest.raises(EvaluatorMetricsError, match="must be a number"):
        book_weights(_SCORES, vols=vols)


def test_vol_scaling_that_overflows_to_non_finite_is_refused():
    """Finite inputs, non-finite quotient: refused rather than yielding NaN.

    A score near the double maximum over a near-denormal vol divides to
    ±inf, whose normalization is ``inf / inf`` — a book of NaNs. Every other
    non-finite intermediate in this module is refused, so this is too.
    """
    scores = {"A": 1e308, "B": -1e308}
    vols = {"A": 5e-324, "B": 5e-324}
    with pytest.raises(EvaluatorMetricsError, match="is not finite"):
        book_weights(scores, vols=vols)


def test_vols_not_a_mapping_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="vols must map"):
        book_weights(_SCORES, vols=["not", "a", "mapping"])


def test_vols_keyed_by_empty_symbol_name_is_refused():
    with pytest.raises(EvaluatorMetricsError, match="non-empty symbol"):
        book_weights(_SCORES, vols={"": 1.0})


# -- 6. compute_node_metrics wires the day's vols into the day's book ---------

_VOLS_BY_DATE = {_D0: _VOLS, _D1: _VOLS}
_SCORES_BY_DATE = {_D0: _SCORES, _D1: _D1_SCORES}
_RETURNS_BY_DATE = {_D0: _D0_RETURNS, _D1: _D1_RETURNS}


def test_compute_node_metrics_reproduces_book_weights_per_date_with_vols():
    priced = _hand_priced(_RETURNS_BY_DATE)

    metrics = compute_node_metrics(priced, _SCORES_BY_DATE, vols=_VOLS_BY_DATE)

    for day, scores, returns in (
        (_D0, _SCORES, _D0_RETURNS),
        (_D1, _D1_SCORES, _D1_RETURNS),
    ):
        expected_weights = book_weights(scores, vols=_VOLS_BY_DATE[day])
        expected_return = math.fsum(
            expected_weights[symbol] * returns[symbol] for symbol in expected_weights
        )
        assert metrics.book_returns[day] == pytest.approx(expected_return)


def test_compute_node_metrics_reproduces_book_weights_with_vols_and_betas():
    priced = _hand_priced(_RETURNS_BY_DATE)
    betas = {_D0: _BETAS, _D1: _BETAS}

    metrics = compute_node_metrics(
        priced, _SCORES_BY_DATE, betas=betas, vols=_VOLS_BY_DATE
    )

    expected_weights = book_weights(_SCORES, _BETAS, vols=_VOLS)
    expected_return = math.fsum(
        expected_weights[symbol] * _D0_RETURNS[symbol] for symbol in expected_weights
    )
    assert metrics.book_returns[_D0] == pytest.approx(expected_return)


def test_compute_node_metrics_vols_none_reproduces_the_existing_book_returns():
    """Every number with ``vols=None`` is identical to before the parameter."""
    priced = _hand_priced(_RETURNS_BY_DATE)

    omitted = compute_node_metrics(priced, _SCORES_BY_DATE)
    explicit_none = compute_node_metrics(priced, _SCORES_BY_DATE, vols=None)

    assert omitted == explicit_none
    assert omitted.book_returns == explicit_none.book_returns
    for day, expected in explicit_none.book_returns.items():
        assert omitted.book_returns[day] == pytest.approx(expected, abs=1e-12)
    # And the vols panel genuinely moves the book.
    scaled = compute_node_metrics(priced, _SCORES_BY_DATE, vols=_VOLS_BY_DATE)
    assert scaled.book_returns[_D0] != pytest.approx(omitted.book_returns[_D0])


def test_compute_node_metrics_ic_is_unchanged_by_vols():
    """ic_mean/ic_tstat/ic_series are rank-based on the scores, not the weights."""
    priced = _hand_priced(_RETURNS_BY_DATE)

    without = compute_node_metrics(priced, _SCORES_BY_DATE)
    with_vols = compute_node_metrics(priced, _SCORES_BY_DATE, vols=_VOLS_BY_DATE)

    assert with_vols.ic_series == without.ic_series
    assert with_vols.ic_mean == pytest.approx(without.ic_mean)
    assert with_vols.ic_tstat == pytest.approx(without.ic_tstat)


def test_compute_node_metrics_refuses_a_missing_date_row_by_name():
    priced = _hand_priced(_RETURNS_BY_DATE)
    with pytest.raises(EvaluatorMetricsError, match="no row for"):
        compute_node_metrics(priced, _SCORES_BY_DATE, vols={_D0: _VOLS})


# -- 6b. A name a date's vols row does not carry is dropped from that book ----
#
# The spec's own case: a perpetual delisted in place (FTTUSDT) has a constant
# archived close, so its trailing window measures a volatility of exactly 0.0
# and the row computed from that window does not name it.  Refusing the whole
# evaluation over one untradeable name would discard every other name's
# measurement with it, so that name is dropped from the date's book and the
# survivors renormalised to gross 1 — with the drop counted in vol_dropped.
# The rank IC for the date is still measured over the *full* joined
# cross-section (a frozen name has a score and a return of 0, and the ranking
# is not measured on the book's membership).

#: A is the frozen name: absent from the vols row, present in the scores and
#: the priced panel.
_D0_VOLS_WITHOUT_A = {"B": 2.0, "C": 1.0, "D": 0.25}
_FULL_VOLS_BY_DATE = {_D0: _VOLS, _D1: _VOLS}
_DROPPING_VOLS_BY_DATE = {_D0: _D0_VOLS_WITHOUT_A, _D1: _VOLS}


def test_a_symbol_with_no_vol_is_dropped_from_that_dates_book():
    """The frozen name is absent from the book; the rest are renormalised."""
    priced = _hand_priced(_RETURNS_BY_DATE)

    metrics = compute_node_metrics(
        priced, _SCORES_BY_DATE, vols=_DROPPING_VOLS_BY_DATE
    )

    survivors = {symbol: _SCORES[symbol] for symbol in ("B", "C", "D")}
    expected = book_weights(survivors, None, vols=_D0_VOLS_WITHOUT_A)
    expected_return = math.fsum(
        expected[symbol] * _D0_RETURNS[symbol] for symbol in survivors
    )
    # The dropped name contributes nothing, so the book return is the
    # survivors' weighted return alone.
    assert metrics.book_returns[_D0] == pytest.approx(expected_return)
    # The date it was dropped from is the one the panel thinned; every other
    # date measured a complete book.
    assert metrics.vol_dropped[_D0] == 1
    assert metrics.vol_dropped[_D1] == 0
    assert set(metrics.vol_dropped) == {_D0, _D1}
    # And the drop genuinely moved the book — it is not the full book's return.
    full = compute_node_metrics(priced, _SCORES_BY_DATE, vols=_FULL_VOLS_BY_DATE)
    assert metrics.book_returns[_D0] != pytest.approx(full.book_returns[_D0])


def test_the_thinned_book_still_grosses_one_and_nets_zero():
    """Renormalising through book_weights keeps the book's size and neutrality.

    A dedicated three-name fixture, because the surviving row must itself be a
    centered, symmetric pair for the *scaled* row to stay centered (the caveat
    :func:`test_an_asymmetric_vols_panel_grosses_one_even_though_net_need_not_be_zero`
    documents) — with the frozen name present the full book is a different,
    wider cross-section.
    """
    # Two dates, because ic_tstat is refused over a single measured date.
    returns = {
        _D0: {"FROZEN": 0.0, "LONG": 0.04, "SHORT": -0.04},
        _D1: {"FROZEN": 0.0, "LONG": -0.03, "SHORT": 0.05},
    }
    scores = {
        _D0: {"FROZEN": 2.0, "LONG": 1.0, "SHORT": -1.0},
        _D1: {"FROZEN": -2.0, "LONG": 1.0, "SHORT": -1.0},
    }
    survivor_vols = {"LONG": 0.5, "SHORT": 0.5}
    priced = _hand_priced(returns)

    metrics = compute_node_metrics(
        priced,
        scores,
        # FROZEN has no vol on either date: a flat window.
        vols={_D0: survivor_vols, _D1: survivor_vols},
    )

    weights = book_weights({"LONG": 1.0, "SHORT": -1.0}, None, vols=survivor_vols)
    assert math.fsum(abs(w) for w in weights.values()) == pytest.approx(
        1.0, abs=1e-12
    )
    assert "FROZEN" not in weights
    # Equal scores under equal vols: the thinned book is gross 1 and net 0.
    assert weights["LONG"] == pytest.approx(0.5)
    assert weights["SHORT"] == pytest.approx(-0.5)
    assert math.fsum(weights.values()) == pytest.approx(0.0, abs=1e-12)
    assert metrics.vol_dropped == {_D0: 1, _D1: 1}
    for day in (_D0, _D1):
        expected = math.fsum(
            weights[s] * returns[day][s] for s in ("LONG", "SHORT")
        )
        assert metrics.book_returns[day] == pytest.approx(expected)


def test_the_ic_is_unchanged_by_dropping_a_name_from_the_book():
    """The coefficient is measured on the full joined cross-section, not the book."""
    priced = _hand_priced(_RETURNS_BY_DATE)

    full = compute_node_metrics(priced, _SCORES_BY_DATE, vols=_FULL_VOLS_BY_DATE)
    dropped = compute_node_metrics(
        priced, _SCORES_BY_DATE, vols=_DROPPING_VOLS_BY_DATE
    )

    assert dropped.ic_series == full.ic_series
    assert dropped.ic_mean == pytest.approx(full.ic_mean)
    assert dropped.ic_tstat == pytest.approx(full.ic_tstat)


def test_vol_dropped_is_empty_when_vols_is_not_given():
    """A z-weighted book never drops a name, so its record carries no drops."""
    priced = _hand_priced(_RETURNS_BY_DATE)

    metrics = compute_node_metrics(priced, _SCORES_BY_DATE)

    assert dict(metrics.vol_dropped) == {}
    assert compute_node_metrics(
        priced, _SCORES_BY_DATE, vols=_FULL_VOLS_BY_DATE
    ).vol_dropped == {_D0: 0, _D1: 0}


def test_a_zero_vol_a_caller_hands_in_is_still_refused_by_the_panel_check():
    """The drop rule is for a name the row omits, not for a row that carries 0.0.

    A vol of exactly 0.0 in the panel is a caller's arithmetic error — the row
    computed from a window never carries one, since ``compute_vols`` omits
    such a symbol — and it is refused by name rather than read as a drop.
    """
    priced = _hand_priced(_RETURNS_BY_DATE)
    bad = {_D0: {"A": 0.0, "B": 1.0, "C": 1.0, "D": 1.0}, _D1: _VOLS}
    with pytest.raises(EvaluatorMetricsError, match="not positive") as excinfo:
        compute_node_metrics(priced, _SCORES_BY_DATE, vols=bad)
    assert "FTT" not in str(excinfo.value)  # names the symbol it was given
    assert "'A'" in str(excinfo.value)


def test_book_weights_called_directly_still_refuses_a_zero_vol():
    """``book_weights`` is unchanged: an incomplete or bad row is refused."""
    survivors = {"B": _SCORES["B"], "C": _SCORES["C"], "D": _SCORES["D"]}
    with pytest.raises(EvaluatorMetricsError, match="not positive") as excinfo:
        book_weights(
            {"A": _SCORES["A"], **survivors},
            None,
            vols={**_D0_VOLS_WITHOUT_A, "A": 0.0},
        )
    assert "'A'" in str(excinfo.value)
    # And a scored symbol the row simply omits is still refused by name too.
    with pytest.raises(EvaluatorMetricsError, match="missing from book_weights' vols"):
        book_weights({"A": _SCORES["A"], **survivors}, None, vols=_D0_VOLS_WITHOUT_A)


def test_compute_node_metrics_refuses_a_non_positive_vol():
    priced = _hand_priced(_RETURNS_BY_DATE)
    bad = {_D0: {"A": 0.0, "B": 1.0, "C": 1.0, "D": 1.0}, _D1: _VOLS}
    with pytest.raises(EvaluatorMetricsError, match="not positive"):
        compute_node_metrics(priced, _SCORES_BY_DATE, vols=bad)


def test_compute_node_metrics_refuses_a_non_finite_vol():
    priced = _hand_priced(_RETURNS_BY_DATE)
    bad = {_D0: {"A": math.inf, "B": 1.0, "C": 1.0, "D": 1.0}, _D1: _VOLS}
    with pytest.raises(EvaluatorMetricsError, match="not finite|NaN"):
        compute_node_metrics(priced, _SCORES_BY_DATE, vols=bad)


def test_compute_node_metrics_refuses_a_datetime_keyed_vols_panel():
    priced = _hand_priced(_RETURNS_BY_DATE)
    bad = {dt.datetime(2026, 9, 1, 12): _VOLS}
    with pytest.raises(EvaluatorMetricsError, match="calendar dates"):
        compute_node_metrics(priced, _SCORES_BY_DATE, vols=bad)


def test_compute_node_metrics_refuses_a_vols_panel_that_is_not_a_mapping():
    priced = _hand_priced(_RETURNS_BY_DATE)
    with pytest.raises(EvaluatorMetricsError, match="vols must map"):
        compute_node_metrics(priced, _SCORES_BY_DATE, vols=["not", "a", "mapping"])
