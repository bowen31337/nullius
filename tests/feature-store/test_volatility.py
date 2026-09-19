"""Feature 55's computation contract: multi-horizon realized volatility and vol-of-vol.

app_spec.xml feature 55: *System computes multi-horizon realized volatility
plus volatility-of-volatility, persisting each as a versioned regime
feature.*  These tests pin the pure computation — the market's magnitude at
several horizons and the instability of that magnitude — independent of how
the numbers are persisted.  The invariants the honesty of the feature rests
on:

* realized volatility is computed at *several* horizons at once, each the
  annualized root-mean-square of the trailing ``horizon`` returns (squared
  returns, deliberately not demeaned), so the horizons are comparable — the
  same market reading the same at every horizon, a spike reading higher at
  the short ones;
* a window with a gap in it is ``nan``, never a number averaged over a
  different elapsed time than the horizon names — and a measured calm
  (every return zero) is ``0.0``, a different fact from an unscored one;
* vol-of-vol is the *population* standard deviation of a trailing window of
  the base realized-vol series, with the window's mean beside it, so a
  wide-but-low vol regime reads differently from a wide-and-high one;
* both consume the market return series — the equal-weighted cross-sectional
  mean — so the magnitude measured is the market's, not one symbol's.

Both reductions are bit-reproducible: the same panel yields the same numbers
in either order of computation, so a replay recomputes them identically.
"""

import datetime as dt
import math

import pytest
from feature_store.bars import DailyBar
from feature_store.regime import PricePanel
from feature_store.volatility import (
    ANNUALIZATION_PERIODS,
    DEFAULT_BASE_WINDOW,
    DEFAULT_HORIZONS,
    DEFAULT_VOL_WINDOW,
    build_volatility_metrics,
    realized_volatility,
    rolling_realized_volatility,
    volatility_of_volatility,
)
from feature_store.volatility_persistence import encode_realized_volatility

DAYS = [dt.date(2026, 1, 1) + dt.timedelta(days=offset) for offset in range(140)]


def price_panel(
    series: dict[str, list[float]],
    *,
    symbols: "list[str] | None" = None,
    dates: "list[dt.date] | None" = None,
) -> PricePanel:
    """A panel from per-symbol price *levels* over ``DAYS`` (or the overrides).

    Mirrors the helper in the regime and dispersion suites: ``dates`` defaults
    to the length of the first series, so an ``n``-level series populates
    ``n`` axis dates and the panel carries no trailing gap of missing prices.
    """
    if dates is None:
        first_len = next(iter(series.values())).__len__()
        dates = DAYS[:first_len]
    symbols = symbols if symbols is not None else list(series)
    bars = [
        DailyBar(symbol, date, levels[i])
        for symbol, levels in series.items()
        for i, date in enumerate(dates)
        if i < len(levels)
    ]
    return PricePanel.from_bars(bars, symbols=symbols, dates=dates)


def levels_from_returns(initial: float, step_returns: list[float]) -> list[float]:
    """Price levels from a list of log returns, one price per arrival."""
    levels = [initial]
    for step in step_returns:
        levels.append(levels[-1] * math.exp(step))
    return levels


def alternating_returns(count: int, *, amplitude: float = 0.02) -> list[float]:
    """A return path of constant magnitude and flipping sign."""
    return [amplitude if index % 2 == 0 else -amplitude for index in range(count)]


def scale() -> float:
    """The version-1 annualization factor."""
    return math.sqrt(ANNUALIZATION_PERIODS)


# ---------------------------------------------------------------------------
# Multi-horizon realized volatility
# ---------------------------------------------------------------------------


def test_constant_returns_yield_the_same_vol_at_every_horizon() -> None:
    # Same magnitude every day: the per-period root-mean-square is that
    # magnitude at every horizon alike — the comparability the per-period
    # normalization buys (a raw sum of squares would grow with the window).
    result = realized_volatility([0.01] * 80)
    for horizon, value in zip(result.horizons, result.volatilities):
        assert value == pytest.approx(0.01 * scale())
        assert result.observations[result.horizons.index(horizon)] == horizon


def test_volatility_matches_the_root_mean_square_of_squares() -> None:
    # Known returns over a known window: the estimate is sqrt(mean of
    # squares) annualized — hand-computed, so the estimator cannot drift.
    result = realized_volatility([0.01, 0.02], horizons=(2,))
    expected = math.sqrt((0.01**2 + 0.02**2) / 2) * scale()
    assert result.volatilities == (pytest.approx(expected),)


def test_the_estimator_is_deliberately_not_demeaned() -> None:
    # A demeaned estimator over [0.01, 0.03] would give sqrt(variance) = 0.01;
    # the realized-volatility estimator gives the root-mean-square ~0.0224.
    # Over daily windows the mean return is noise, and demeaning would import
    # the error of a mean estimate into a variance estimate.
    result = realized_volatility([0.01, 0.03], horizons=(2,))
    assert result.volatilities[0] == pytest.approx(
        math.sqrt((0.01**2 + 0.03**2) / 2) * scale()
    )
    assert result.volatilities[0] > 0.02 * scale() * 0.9  # not the demeaned 0.01


def test_every_requested_horizon_is_reported_in_order() -> None:
    # The feature's "multi-horizon" clause: every requested horizon is
    # present, in the order asked for, with one volatility and one count each.
    result = realized_volatility(alternating_returns(80), horizons=(5, 10, 21))
    assert result.horizons == (5, 10, 21)
    assert len(result.volatilities) == 3
    assert len(result.observations) == 3
    assert result.at(10) == pytest.approx(result.volatilities[1])


def test_default_horizons_are_several() -> None:
    # The version-1 definition computes more than one horizon: "multi-
    # horizon" is the contract, and a single horizon would not satisfy it.
    result = realized_volatility([0.01, -0.02, 0.03] * 30)
    assert result.horizons == DEFAULT_HORIZONS
    assert len(DEFAULT_HORIZONS) >= 2


def test_a_horizon_beyond_the_history_is_nan_over_zero_observations() -> None:
    # A horizon longer than the series cannot be served: nan over zero
    # observations, and the count says so — never a default of zero.
    result = realized_volatility([0.01, -0.01] * 3, horizons=(1, 50))
    assert result.at(50) != result.at(50)  # nan
    assert result.observations[result.horizons.index(50)] == 0


def test_a_gap_inside_one_window_leaves_only_that_horizon_unscored() -> None:
    # A nan return is an absent observation.  It spoils exactly the windows
    # that must contain it: the horizon-10 window (the final ten slots) is
    # clean while the horizon-21 window, which has to span the gap, is nan
    # with the count reporting how many of its slots were present.
    series = [0.01] * 30
    series[10] = float("nan")
    result = realized_volatility(series, horizons=(10, 21))
    assert result.at(10) == pytest.approx(0.01 * scale())
    assert math.isnan(result.at(21))
    assert result.observations == (10, 20)


def test_a_gap_does_not_reach_further_back() -> None:
    # The strict window never borrows older returns to fill a gap: reaching
    # back would average a different elapsed time than the horizon names.
    series = [0.01] * 10 + [float("nan")] * 2 + [0.01] * 10
    result = realized_volatility(series, horizons=(12,))
    assert math.isnan(result.at(12))
    assert result.observations == (10,)  # 12 slots, 10 present


def test_zero_returns_are_a_measured_calm_not_an_unscored_one() -> None:
    # Every return present and zero: the market measurably did not move —
    # 0.0, a different fact from nan (nothing measured) and from a default
    # of zero a reader might mistake for it.
    result = realized_volatility([0.0] * 40, horizons=(10, 21))
    assert result.volatilities == (0.0, 0.0)
    assert result.observations == (10, 21)


def test_annualization_scales_every_horizon_alike() -> None:
    # annualization=1 reports the per-day estimate: the same measurement in
    # different units, not a different measurement.
    annualized = realized_volatility([0.02] * 25, horizons=(10,))
    per_day = realized_volatility([0.02] * 25, horizons=(10,), annualization=1.0)
    assert annualized.at(10) == pytest.approx(per_day.at(10) * scale())


def test_at_raises_for_a_horizon_that_was_not_computed() -> None:
    result = realized_volatility([0.01] * 30, horizons=(10,))
    with pytest.raises(KeyError, match="horizon 7"):
        result.at(7)


def test_scored_drops_unscored_horizons() -> None:
    series = [0.01] * 30
    series[10] = float("nan")
    result = realized_volatility(series, horizons=(10, 21))
    assert list(result.scored()) == [10]


def test_empty_horizons_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one horizon"):
        realized_volatility([0.01] * 10, horizons=())


def test_horizon_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        realized_volatility([0.01] * 10, horizons=(0,))


def test_duplicate_horizons_are_rejected() -> None:
    with pytest.raises(ValueError, match="distinct"):
        realized_volatility([0.01] * 10, horizons=(5, 5))


def test_non_integer_horizons_are_rejected() -> None:
    with pytest.raises(TypeError, match="integers"):
        realized_volatility([0.01] * 10, horizons=(10.5,))


def test_bad_annualization_is_rejected() -> None:
    for bad in (0.0, -365.0, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="annualization"):
            realized_volatility([0.01] * 10, horizons=(5,), annualization=bad)


# ---------------------------------------------------------------------------
# The rolling base series
# ---------------------------------------------------------------------------


def test_rolling_volatility_is_aligned_to_the_series() -> None:
    # One vol per position of the series, the first window-1 positions nan
    # (the window is not yet full) — the same alignment the breadth moving
    # average uses.
    vols = rolling_realized_volatility([0.01] * 10, window=3)
    assert len(vols) == 10
    assert all(math.isnan(vol) for vol in vols[:2])
    assert vols[-1] == pytest.approx(0.01 * scale())


def test_rolling_volatility_matches_each_trailing_window() -> None:
    # Position i is the realized vol over exactly returns [i-window+1 .. i]:
    # hand-computed for a small varying series, so the sliding cannot drift.
    series = [0.01, 0.02, -0.01, 0.03, 0.01]
    vols = rolling_realized_volatility(series, window=3)
    for index in (2, 3, 4):
        window = series[index - 2 : index + 1]
        expected = math.sqrt(math.fsum(value**2 for value in window) / 3) * scale()
        assert vols[index] == pytest.approx(expected)


def test_rolling_window_holding_a_gap_is_nan_then_recovers() -> None:
    # A nan poisons exactly the windows that must contain it; once it slides
    # out, the vol is scored again over a full window.
    series = [0.01] * 3 + [float("nan")] + [0.01] * 4
    vols = rolling_realized_volatility(series, window=3)
    assert math.isnan(vols[3])  # window [0.01, 0.01, nan]
    assert math.isnan(vols[4])  # window [0.01, nan, 0.01]
    assert math.isnan(vols[5])  # window [nan, 0.01, 0.01]
    assert vols[6] == pytest.approx(0.01 * scale())


def test_rolling_window_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        rolling_realized_volatility([0.01] * 5, window=0)


def test_the_base_series_and_the_horizon_agree_bit_for_bit() -> None:
    # The version-1 base window (21) is one of the horizons, so the final
    # element of the rolling base series and the horizon-21 estimate are the
    # same number bit for bit — one definition of "the vol", not two
    # spellings of it that drift apart in the last ulp.  Exact ``==``, not
    # approx: both reductions sum their window with math.fsum.
    series = [_rng_like(index, "Z") for index in range(80)]
    trailing = realized_volatility(series, horizons=(21,))
    rolling = rolling_realized_volatility(series, window=21)
    assert rolling[-1] == trailing.at(21)


# ---------------------------------------------------------------------------
# Volatility-of-volatility
# ---------------------------------------------------------------------------


def test_steady_vol_yields_zero_vol_of_vol() -> None:
    # Constant-magnitude returns make every base vol identical, so their
    # population standard deviation is exactly 0: a market whose vol is high
    # but steady — a different regime from the same mean with swings.
    vols = volatility_of_volatility(
        alternating_returns(90), base_window=5, window=40
    )
    assert vols.vol_of_vol == pytest.approx(0.0)
    assert vols.mean_vol == pytest.approx(0.02 * scale())
    assert vols.n == 40


def test_vol_of_vol_matches_the_population_stddev_of_the_vols() -> None:
    # Hand-computed end to end: a return path whose base vols take known
    # values, the vol-of-vol the population standard deviation of the final
    # window of them (divide by n, not n-1 — the window is the set being
    # described, not a sample from a larger one).
    series = [0.01] * 20 + [0.02] * 20  # one amplitude step
    base_window = 2
    window = 30  # straddles the step: low vols, the transition, high vols
    expected_vols = [float("nan")] + [
        math.sqrt(
            (series[i - 1] ** 2 + series[i] ** 2) / base_window
        )
        * scale()
        for i in range(1, len(series))
    ]
    result = volatility_of_volatility(
        series, base_window=base_window, window=window
    )
    tail = [vol for vol in expected_vols[-window:] if not math.isnan(vol)]
    mean = math.fsum(tail) / len(tail)
    stddev = math.sqrt(
        math.fsum((vol - mean) ** 2 for vol in tail) / len(tail)
    )
    assert result.n == len(tail) == window
    assert result.mean_vol == pytest.approx(mean)
    assert result.vol_of_vol == pytest.approx(stddev)
    assert result.vol_of_vol > 0.0  # the step registered


def test_a_regime_shift_yields_a_positive_vol_of_vol() -> None:
    # A calm half followed by a violent half: the base vols step up, and the
    # vol-of-vol says the magnitude itself moved — the fact a plain vol
    # cannot express.  The vol window straddles the step; one sitting wholly
    # inside either regime would read steady vol, which is the point.
    series = [0.01] * 40 + [0.05] * 40
    result = volatility_of_volatility(series, base_window=5, window=60)
    assert result.vol_of_vol > 0.0
    low = 0.01 * scale()
    high = 0.05 * scale()
    assert low < result.mean_vol < high


def test_thin_vol_window_is_nan_with_the_mean_reported() -> None:
    # Fewer complete vols in the tail than the window names: nan — a
    # vol-of-vol over part of a window is a different elapsed time than the
    # one asked for — but the mean over what is present is still reported,
    # the same courtesy dispersion extends to a thin cross-section.
    series = [0.01] * 10 + [float("nan")] + [0.02] * 10
    # base_window=3: the gap poisons vols at positions 10, 11, 12; the final
    # window=10 vols (positions 12..19... see below) hold one nan.
    result = volatility_of_volatility(series, base_window=3, window=10)
    assert math.isnan(result.vol_of_vol)
    assert 0 < result.n < 10
    assert not math.isnan(result.mean_vol)


def test_no_observations_at_all_is_nan_over_zero() -> None:
    # A series too short to form even one base vol: nothing was measured,
    # over zero observations — not a zero a reader would mistake for calm.
    result = volatility_of_volatility(
        [0.01] * 5, base_window=21, window=60
    )
    assert math.isnan(result.vol_of_vol)
    assert math.isnan(result.mean_vol)
    assert result.n == 0


def test_base_window_below_two_is_rejected() -> None:
    with pytest.raises(ValueError, match="base_window"):
        volatility_of_volatility([0.01] * 30, base_window=1, window=10)


def test_vol_window_below_two_is_rejected() -> None:
    with pytest.raises(ValueError, match="window"):
        volatility_of_volatility([0.01] * 30, base_window=5, window=1)


# ---------------------------------------------------------------------------
# Combined entry point and reproducibility
# ---------------------------------------------------------------------------


def test_build_volatility_metrics_returns_both() -> None:
    panel = price_panel(
        {"AAAUSDT": levels_from_returns(100.0, alternating_returns(90))}
    )
    metrics = build_volatility_metrics(
        panel, horizons=(5, 10), base_window=5, vol_window=20
    )
    assert metrics.realized.horizons == (5, 10)
    assert metrics.realized.at(5) == pytest.approx(0.02 * scale())
    assert metrics.vol_of_vol.base_window == 5
    assert metrics.vol_of_vol.window == 20


def test_build_computes_over_the_market_return_not_one_symbol() -> None:
    # Two members with mirror-image paths average to a flat market return,
    # so the market's realized volatility is a measured zero — the cross-
    # sectional mean, not either member's path.
    panel = price_panel(
        {
            "AAAUSDT": levels_from_returns(100.0, alternating_returns(60)),
            "BBBUSDT": levels_from_returns(
                100.0, alternating_returns(60, amplitude=-0.02)
            ),
        }
    )
    metrics = build_volatility_metrics(
        panel, horizons=(10,), base_window=5, vol_window=20
    )
    assert metrics.realized.at(10) == pytest.approx(0.0, abs=1e-12)
    assert metrics.vol_of_vol.vol_of_vol == pytest.approx(0.0, abs=1e-12)


def test_reductions_are_bit_reproducible() -> None:
    panel = price_panel(
        {
            f"{letter}USDT": levels_from_returns(
                100.0, [_rng_like(i, letter) for i in range(90)]
            )
            for letter in ("A", "B", "C")
        }
    )
    first = build_volatility_metrics(
        panel, horizons=(5, 10, 21), base_window=5, vol_window=20
    )
    second = build_volatility_metrics(
        panel, horizons=(5, 10, 21), base_window=5, vol_window=20
    )
    assert first == second


def test_reproducibility_is_payload_bytes_even_when_values_are_nan() -> None:
    # A panel too short to serve a horizon yields nan, and ``nan != nan``
    # means the dataclass comparison is False for an *honest* recomputation.
    # The reproducibility the replay path actually depends on is the encoded
    # payloads, which stay byte-identical regardless of nan — so this pins
    # that the two statements are different claims, and only the second one
    # holds unconditionally.
    panel = price_panel(
        {"AAAUSDT": levels_from_returns(100.0, [0.01] * 5)}
    )
    first = build_volatility_metrics(panel, horizons=(63,))
    second = build_volatility_metrics(panel, horizons=(63,))
    assert math.isnan(first.realized.at(63))
    assert first != second
    # ...but the encoded payloads — what a replay compares — are identical.
    assert encode_realized_volatility(
        first.realized, top_n=1
    ) == encode_realized_volatility(second.realized, top_n=1)
    assert repr(first.realized.volatilities) == repr(second.realized.volatilities)


def test_defaults_form_one_coherent_definition() -> None:
    # The version-1 definition: several horizons, a base window that is one
    # of them (one definition of "the vol", not two), a vol window over it,
    # and the crypto calendar for annualization.
    assert len(DEFAULT_HORIZONS) >= 2
    assert DEFAULT_BASE_WINDOW in DEFAULT_HORIZONS
    assert DEFAULT_VOL_WINDOW >= 2
    assert ANNUALIZATION_PERIODS == 365.0


def _rng_like(index: int, salt: str) -> float:
    """A deterministic, varied log return — no ``random`` import needed."""
    state = (1103515245 * (index + 1) + 12345 * (ord(salt) + 1)) & 0x7FFFFFFF
    return ((state / 0x40000000) - 1.0) * 0.02
