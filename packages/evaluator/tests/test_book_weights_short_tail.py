"""The ``"short_tail"`` research book — short each date's bottom score decile,
long every other scored name, equal-weight within each leg.

additions_spec_short_tail_book.xml: the committed preregistration results
(``docs/preregistration/2026-10-20-m2-wide-h5-v2.RESULT.md``, "Decile profile
of each committed pick") show the return gradient living in the *bottom*
decile of scores alone — the top decile never the best bucket, deciles 2
through 10 flat — so the tail-decile book spends half its gross financing a
long bet the ranking never supported.  Under ``"short_tail"`` each date's
book is short the bottom ``floor(n/10)`` names of that date's ranking at
``-0.5/k`` each and long every remaining scored name at ``+0.5/(n-k)`` each:
equal-weight within each leg, dollar-neutral at gross 1 by construction, the
long leg the market-like complement of the short rather than a second decile
bet.  The score's magnitude is unused; ties are broken by symbol name.  The
same thin-cross-section refusal guards it as guards the tail-decile book
(**by name, naming the date and the count** through
:func:`evaluator.compute_node_metrics`), ``vols`` is ignored under it, the
beta-neutral leg rescale composes *after* the legs are formed, and
:attr:`evaluator.NodeMetrics.tail_k` records ``k`` per date under it exactly
as under ``"tail_decile"``.

This suite is self-contained — it does not import ``test_book_weights.py``'s,
``test_book_weights_inverse_vol.py``'s or
``test_book_weights_tail_decile.py``'s fixtures, but re-pins the same
hand-computed cross-section those suites pin, so the "the other three
weightings reproduce today" checks compare against a fixture another suite
already proved correct — and runs with no database, so it is safe under
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
    book_weights,
    compute_node_metrics,
)
from evaluator._metrics import (
    INVERSE_VOL_WEIGHTING,
    SHORT_TAIL_WEIGHTING,
    TAIL_DECILE_MIN_LEG,
    TAIL_DECILE_WEIGHTING,
    WEIGHTINGS,
    Z_WEIGHTING,
)

_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)
_START = dt.date(2026, 9, 1)
_D0 = _START
_D1 = _START + dt.timedelta(days=1)

# The same hand-computed cross-section ``test_book_weights.py`` pins (and
# ``test_book_weights_tail_decile.py`` re-pins), so the "the other three
# weightings reproduce today" checks below are comparing against fixtures
# other suites already proved correct rather than one this file invented.
_SCORES = {"A": 3.0, "B": 1.0, "C": -3.0, "D": -1.0}
_PLAIN_WEIGHTS = {"A": 0.375, "B": 0.125, "C": -0.375, "D": -0.125}
_BETAS = {"A": 1.2, "C": 0.8}
_NEUTRAL_WEIGHTS = {"A": 0.275, "B": 0.125, "C": -0.475, "D": -0.125}


def _hand_priced(
    returns_by_date: dict[dt.date, dict[str, float]],
    *,
    horizon: int = 1,
) -> PostCostReturns:
    """A hand-built, single-horizon priced bundle — step 8's input (the same
    shape ``test_book_weights.py``, ``test_book_weights_inverse_vol.py`` and
    ``test_book_weights_tail_decile.py`` use)."""
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


def _decile_scores(count: int, *, step: float = 1.0) -> dict[str, float]:
    """``count`` symbols named ``S00``…``S{count-1}`` with strictly increasing
    scores, so the ranking is unambiguous and the tie-break never fires."""
    return {f"S{i:02d}": (i + 1) * step for i in range(count)}


def _shifted_returns(
    scores: dict[str, float], *, shift: int = 5
) -> dict[str, float]:
    """Forward returns whose ordering is the scores' own, rotated by ``shift``
    names — a cross-section the ranking is *related* to but does not
    reproduce, so a second date's information coefficient differs from the
    first's.  Two dates sharing one IC would have a zero standard error of
    the mean and ``ic_tstat`` refuses that by design."""
    ordered = sorted(scores)
    count = len(ordered)
    return {
        ordered[i]: scores[ordered[(i + shift) % count]] for i in range(count)
    }


# -- 1. The legs themselves: 20 names, k=2, −0.25 and +1/36 ------------------


def test_twenty_names_gives_two_shorts_at_a_quarter_and_eighteen_longs():
    scores = _decile_scores(20)
    weights = book_weights(scores, weighting=SHORT_TAIL_WEIGHTING)
    assert len(weights) == 20
    # The bottom decile alone is the short leg…
    assert weights["S00"] == pytest.approx(-0.25, abs=1e-12)
    assert weights["S01"] == pytest.approx(-0.25, abs=1e-12)
    # …and *every other scored name* is long, equal-weight: the long leg is
    # the complement of the short, the whole point of the weighting — no
    # name sits at zero the way the tail-decile book's middle deciles do.
    longs = {s for s, w in weights.items() if w > 0.0}
    assert longs == {f"S{i:02d}" for i in range(2, 20)}
    assert all(
        weights[s] == pytest.approx(1.0 / 36.0, abs=1e-12) for s in longs
    )
    assert sum(1 for w in weights.values() if w < 0.0) == 2
    assert sum(1 for w in weights.values() if w == 0.0) == 0


def test_twenty_name_book_is_gross_one_and_net_zero():
    weights = book_weights(_decile_scores(20), weighting=SHORT_TAIL_WEIGHTING)
    assert math.fsum(weights.values()) == pytest.approx(0.0, abs=1e-12)
    assert math.fsum(abs(v) for v in weights.values()) == pytest.approx(
        1.0, abs=1e-12
    )


def test_fifty_names_gives_five_shorts_at_a_tenth_and_forty_five_longs():
    scores = _decile_scores(50)
    weights = book_weights(scores, weighting=SHORT_TAIL_WEIGHTING)
    short_leg = {s for s, w in weights.items() if w < 0.0}
    long_leg = {s for s, w in weights.items() if w > 0.0}
    assert short_leg == {f"S{i:02d}" for i in range(5)}
    assert long_leg == {f"S{i:02d}" for i in range(5, 50)}
    assert all(weights[s] == pytest.approx(-0.1, abs=1e-12) for s in short_leg)
    assert all(
        weights[s] == pytest.approx(1.0 / 90.0, abs=1e-12) for s in long_leg
    )
    assert math.fsum(weights.values()) == pytest.approx(0.0, abs=1e-12)
    assert math.fsum(abs(v) for v in weights.values()) == pytest.approx(
        1.0, abs=1e-12
    )


def test_the_scores_magnitude_is_unused():
    """A monotone rescaling of the scores leaves the short-tail book exactly
    as it was — the book is a function of the ranking alone."""
    scores = _decile_scores(20)
    stretched = {symbol: value * 1e6 for symbol, value in scores.items()}
    assert book_weights(stretched, weighting=SHORT_TAIL_WEIGHTING) == (
        book_weights(scores, weighting=SHORT_TAIL_WEIGHTING)
    )


# -- 2. Ties are broken by symbol name ---------------------------------------


def test_ties_are_broken_by_symbol_name():
    """Ten names all tied at one score fill the bottom decile by the *first*
    names in the sorted order — a dict's insertion order must not decide
    which."""
    tied_low = {name: 1.0 for name in "JIHGFEDCBA"}
    tied_high = {name: 2.0 for name in "TSRQPONMLK"}
    scores = {**tied_low, **tied_high}
    weights = book_weights(scores, weighting=SHORT_TAIL_WEIGHTING)
    assert {s for s, w in weights.items() if w == -0.25} == set("AB")
    # Every other name — tied or not — is long the complement's equal share.
    assert {s for s, w in weights.items() if w > 0.0} == set(scores) - set("AB")


def test_tie_break_is_independent_of_dict_order():
    scores = {f"S{i:02d}": float((i % 5) + 1) for i in range(20)}
    reordered = {symbol: scores[symbol] for symbol in reversed(list(scores))}
    assert book_weights(scores, weighting=SHORT_TAIL_WEIGHTING) == (
        book_weights(reordered, weighting=SHORT_TAIL_WEIGHTING)
    )


# -- 3. Too thin a cross-section is refused, naming the count ----------------


def test_fifteen_names_is_refused_naming_the_count():
    with pytest.raises(EvaluatorMetricsError) as refusal:
        book_weights(_decile_scores(15), weighting=SHORT_TAIL_WEIGHTING)
    message = str(refusal.value)
    assert "15" in message
    assert "floor(15/10) = 1" in message
    assert str(TAIL_DECILE_MIN_LEG) in message


@pytest.mark.parametrize("count", [1, 5, 9, 10, 11, 15, 19])
def test_every_cross_section_below_twenty_is_refused(count: int):
    with pytest.raises(EvaluatorMetricsError, match="scored symbols"):
        book_weights(_decile_scores(count), weighting=SHORT_TAIL_WEIGHTING)


def test_exactly_twenty_names_is_the_first_accepted_cross_section():
    weights = book_weights(_decile_scores(20), weighting=SHORT_TAIL_WEIGHTING)
    assert sum(1 for w in weights.values() if w < 0) == TAIL_DECILE_MIN_LEG
    assert sum(1 for w in weights.values() if w > 0) == 18


def test_the_per_date_refusal_names_the_date_and_the_count():
    """``compute_node_metrics`` is the per-date caller, so its refusal says
    *which* rebalance date's cross-section was too thin as well as how many
    names it held."""
    scores = {_D0: _decile_scores(20), _D1: _decile_scores(15)}
    priced = _hand_priced({_D0: _decile_scores(20), _D1: _decile_scores(15)})
    with pytest.raises(EvaluatorMetricsError) as refusal:
        compute_node_metrics(priced, scores, weighting=SHORT_TAIL_WEIGHTING)
    message = str(refusal.value)
    assert _D1.isoformat() in message
    assert "15" in message
    assert _D0.isoformat() not in message


# -- 4. The beta-neutral rescale composes after the legs are formed ----------


def test_betas_compose_after_the_legs_are_formed():
    from evaluator._metrics import _beta_neutral_weights

    scores = _decile_scores(20)
    betas = {"S19": 1.2, "S00": 0.8}
    plain = book_weights(scores, weighting=SHORT_TAIL_WEIGHTING)
    expected = _beta_neutral_weights(plain, betas)
    assert book_weights(scores, betas, weighting=SHORT_TAIL_WEIGHTING) == (
        pytest.approx(expected)
    )


def test_beta_neutral_short_tail_book_is_beta_zero_and_gross_one():
    """Every name rated: the rescale lands the book's net beta on exactly
    zero (1e-12) while gross stays 1 — the long leg is eighteen names now,
    and the split has to reach across all of them."""
    scores = _decile_scores(20)
    betas = {f"S{i:02d}": 0.6 + 0.05 * i for i in range(20)}
    weights = book_weights(scores, betas, weighting=SHORT_TAIL_WEIGHTING)
    book_beta = math.fsum(weights[s] * betas[s] for s in weights)
    assert book_beta == pytest.approx(0.0, abs=1e-12)
    assert math.fsum(abs(v) for v in weights.values()) == pytest.approx(
        1.0, abs=1e-12
    )
    # The legs are still equal-weight within themselves after the rescale —
    # the rescale scales a leg's rated names, it does not re-rank them.
    longs = [weights[s] for s in weights if weights[s] > 0.0]
    shorts = [weights[s] for s in weights if weights[s] < 0.0]
    assert len(longs) == 18 and len(set(longs)) == 1
    assert len(shorts) == 2 and len(set(shorts)) == 1


# -- 5. vols is ignored under short_tail --------------------------------------


def test_vols_is_ignored_under_short_tail():
    scores = _decile_scores(20)
    vols = {symbol: 0.1 * (1 + i) for i, symbol in enumerate(scores)}
    assert book_weights(scores, vols=vols, weighting=SHORT_TAIL_WEIGHTING) == (
        book_weights(scores, weighting=SHORT_TAIL_WEIGHTING)
    )


# -- 6. The other three weightings are unchanged ------------------------------


def test_default_weighting_is_z():
    assert book_weights(_SCORES) == pytest.approx(_PLAIN_WEIGHTS)
    assert book_weights(_SCORES, weighting=Z_WEIGHTING) == pytest.approx(
        _PLAIN_WEIGHTS
    )


def test_z_weighting_reproduces_the_existing_fixture_to_1e_12():
    explicit = book_weights(_SCORES, _BETAS, weighting=Z_WEIGHTING)
    default = book_weights(_SCORES, _BETAS)
    for symbol, value in _NEUTRAL_WEIGHTS.items():
        assert explicit[symbol] == pytest.approx(value, abs=1e-12)
        assert abs(explicit[symbol] - default[symbol]) <= 1e-12


def test_inverse_vol_weighting_reproduces_the_existing_fixture_to_1e_12():
    """``vols=`` has meant inverse-vol to every caller since it existed, so it
    keeps meaning that — an old call is unchanged by the new spelling."""
    scores = {"A": 3.0, "B": 1.0}
    vols = {"A": 0.3, "B": 0.1}
    scaled = {"A": 3.0 / 0.3, "B": 1.0 / 0.1}
    gross = math.fsum(abs(v) for v in scaled.values())
    expected = {s: v / gross for s, v in scaled.items()}
    for spelling in (Z_WEIGHTING, INVERSE_VOL_WEIGHTING):
        weights = book_weights(scores, vols=vols, weighting=spelling)
        for symbol, value in expected.items():
            assert weights[symbol] == pytest.approx(value, abs=1e-12)


def test_tail_decile_weighting_reproduces_the_existing_fixture_to_1e_12():
    """The tail-decile book over the tail-decile suite's own 20-name fixture
    is exactly what that suite pinned: two shorts, two longs, sixteen zeros —
    a fourth member of the vocabulary changed none of it."""
    scores = _decile_scores(20)
    weights = book_weights(scores, weighting=TAIL_DECILE_WEIGHTING)
    assert weights["S00"] == pytest.approx(-0.25, abs=1e-12)
    assert weights["S01"] == pytest.approx(-0.25, abs=1e-12)
    assert weights["S18"] == pytest.approx(0.25, abs=1e-12)
    assert weights["S19"] == pytest.approx(0.25, abs=1e-12)
    for symbol in list(scores)[2:18]:
        assert weights[symbol] == 0.0


def test_an_unknown_weighting_is_refused_naming_all_four():
    with pytest.raises(EvaluatorMetricsError) as refusal:
        book_weights(_SCORES, weighting="short_tale")
    message = str(refusal.value)
    assert "short_tale" in message
    for name in WEIGHTINGS:
        assert name in message


def test_inverse_vol_weighting_without_vols_is_still_refused_by_name():
    with pytest.raises(EvaluatorMetricsError) as refusal:
        book_weights(_SCORES, weighting=INVERSE_VOL_WEIGHTING)
    message = str(refusal.value)
    assert INVERSE_VOL_WEIGHTING in message
    assert Z_WEIGHTING in message


# -- 7. compute_node_metrics: the book, the IC and tail_k --------------------

_PANEL_SCORES = _decile_scores(20)
_PANEL_RETURNS_D1 = _shifted_returns(_PANEL_SCORES)


def _two_date_panel() -> PostCostReturns:
    """Two dates of the 20-name cross-section, priced so each date's book
    return is a hand-computable number and the two dates' ICs differ."""
    return _hand_priced({_D0: _PANEL_SCORES, _D1: _PANEL_RETURNS_D1})


def test_compute_node_metrics_short_tail_book_return_matches_book_weights():
    scores = {_D0: _PANEL_SCORES, _D1: _PANEL_SCORES}
    priced = _two_date_panel()
    metrics = compute_node_metrics(priced, scores, weighting=SHORT_TAIL_WEIGHTING)
    expected_weights = book_weights(
        _PANEL_SCORES, weighting=SHORT_TAIL_WEIGHTING
    )
    expected_return = math.fsum(
        expected_weights[s] * _PANEL_SCORES[s] for s in expected_weights
    )
    assert metrics.book_returns[_D0] == pytest.approx(
        expected_return, abs=1e-12
    )


def test_compute_node_metrics_short_tail_matches_a_direct_per_date_rebuild():
    """Every measured date's book return is the short-tail book's own return,
    rebuilt in the test from the ranking by hand — the whole chain, checked
    per date (1e-12)."""
    scores = {_D0: _PANEL_SCORES, _D1: _PANEL_SCORES}
    priced = _two_date_panel()
    metrics = compute_node_metrics(priced, scores, weighting=SHORT_TAIL_WEIGHTING)
    for day, returns_row in ((_D0, _PANEL_SCORES), (_D1, _PANEL_RETURNS_D1)):
        weights = book_weights(scores[day], weighting=SHORT_TAIL_WEIGHTING)
        expected = math.fsum(
            weights[symbol] * returns_row[symbol] for symbol in weights
        )
        assert metrics.book_returns[day] == pytest.approx(expected, abs=1e-12)


def test_compute_node_metrics_records_tail_k_per_date():
    scores = {_D0: _decile_scores(20), _D1: _decile_scores(50)}
    returns = {
        _D0: _decile_scores(20),
        _D1: _shifted_returns(_decile_scores(50)),
    }
    priced = _hand_priced(returns)
    metrics = compute_node_metrics(priced, scores, weighting=SHORT_TAIL_WEIGHTING)
    assert dict(metrics.tail_k) == {_D0: 2, _D1: 5}


def test_tail_k_is_empty_under_the_other_weightings():
    scores = {_D0: _PANEL_SCORES, _D1: _PANEL_SCORES}
    priced = _two_date_panel()
    assert dict(compute_node_metrics(priced, scores).tail_k) == {}
    assert (
        dict(compute_node_metrics(priced, scores, weighting=Z_WEIGHTING).tail_k)
        == {}
    )


def test_the_rank_ic_is_still_measured_over_the_whole_cross_section():
    """The short-tail book trades only against the bottom decile, but the
    information coefficient is a property of the ranking — it stays the full
    joined cross-section's rank correlation, exactly as under the other
    weightings."""
    scores = {_D0: _PANEL_SCORES, _D1: _PANEL_SCORES}
    priced = _two_date_panel()
    short = compute_node_metrics(priced, scores, weighting=SHORT_TAIL_WEIGHTING)
    plain = compute_node_metrics(priced, scores)
    assert short.ic_series == plain.ic_series
    assert short.ic_mean == pytest.approx(plain.ic_mean)


def test_vols_handed_beside_short_tail_is_ignored_by_compute_node_metrics():
    scores = {_D0: _PANEL_SCORES, _D1: _PANEL_SCORES}
    vols = {
        day: {symbol: 0.1 * (1 + i) for i, symbol in enumerate(_PANEL_SCORES)}
        for day in (_D0, _D1)
    }
    priced = _two_date_panel()
    with_vols = compute_node_metrics(
        priced, scores, vols=vols, weighting=SHORT_TAIL_WEIGHTING
    )
    without = compute_node_metrics(
        priced, scores, weighting=SHORT_TAIL_WEIGHTING
    )
    assert with_vols.vol_dropped == {}
    for day, value in without.book_returns.items():
        assert with_vols.book_returns[day] == pytest.approx(value, abs=1e-12)
