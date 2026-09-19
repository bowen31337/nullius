"""Feature 56's computation contract: dispersion and several-lag autocorrelation.

app_spec.xml feature 56: *System computes cross-sectional return dispersion
plus return autocorrelation at several lags.*  These tests pin the pure
computation — the cross-section's width and the market return's memory —
independent of how the numbers are persisted.  The invariants the honesty of
the feature rests on:

* dispersion is the *population* standard deviation of the latest log returns
  over the scored cross-section, with the equal-weighted mean and the scored
  count travelling beside it;
* a cross-section too thin to be one (fewer than ``min_symbols``) is ``nan``,
  never a default of ``0.0`` that a reader would mistake for lockstep;
* autocorrelation is computed at *several* lags at once, each a
  pairwise-complete Pearson of the market return against its own shift, and a
  lag the history cannot serve is ``nan`` over zero pairs — not a zero;
* the market return is the equal-weighted cross-sectional mean, so the memory
  measured is the market's, not one symbol's.

Both reductions are bit-reproducible: the same panel yields the same numbers
in either order of computation, so a replay recomputes them identically.
"""

import datetime as dt
import math

import pytest
from feature_store.bars import DailyBar
from feature_store.dispersion import (
    DEFAULT_LAGS,
    AutocorrelationResult,
    DispersionResult,
    build_dispersion_metrics,
    cross_sectional_dispersion,
    market_return_series,
    return_autocorrelation,
)
from feature_store.dispersion_persistence import encode_autocorrelation
from feature_store.regime import PricePanel

DAYS = [dt.date(2026, 1, 1) + dt.timedelta(days=offset) for offset in range(120)]


def price_panel(
    series: dict[str, list[float]],
    *,
    symbols: "list[str] | None" = None,
    dates: "list[dt.date] | None" = None,
) -> PricePanel:
    """A panel from per-symbol price *levels* over ``DAYS`` (or the overrides).

    Mirrors the helper in the regime suite: ``dates`` defaults to the length of
    the first series, so an ``n``-level series populates ``n`` axis dates and
    the panel carries no trailing gap of missing prices.
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
    """A strongly negatively autocorrelated return path (lag 1 ≈ -1)."""
    return [amplitude if index % 2 == 0 else -amplitude for index in range(count)]


# ---------------------------------------------------------------------------
# Cross-sectional dispersion
# ---------------------------------------------------------------------------


def test_dispersion_of_identical_returns_is_zero() -> None:
    # Every member moved by the same log return, so the cross-section has no
    # width: dispersion is exactly 0 and the mean is that shared return.
    step = 0.01
    shared = levels_from_returns(100.0, [step] * 40)
    panel = price_panel(
        {"AAAUSDT": list(shared), "BBBUSDT": list(shared), "CCCUSDT": list(shared)}
    )
    result = cross_sectional_dispersion(panel)
    assert result.n == 3
    assert result.dispersion == pytest.approx(0.0)
    assert result.mean_return == pytest.approx(step)


def test_dispersion_matches_the_population_standard_deviation() -> None:
    # Three members whose latest returns are known exactly; dispersion is the
    # population (divide-by-n) standard deviation of those three numbers.
    latest = {"AAAUSDT": 0.05, "BBBUSDT": 0.01, "CCCUSDT": -0.03}
    panel = price_panel(
        {
            symbol: levels_from_returns(100.0, [0.0] * 30 + [value])
            for symbol, value in latest.items()
        }
    )
    result = cross_sectional_dispersion(panel)
    values = list(latest.values())
    mean = math.fsum(values) / len(values)
    expected = math.sqrt(math.fsum((v - mean) ** 2 for v in values) / len(values))
    assert result.n == 3
    assert result.mean_return == pytest.approx(mean)
    assert result.dispersion == pytest.approx(expected)
    assert result.dispersion > 0.0


def test_dispersion_uses_only_the_latest_return() -> None:
    # Two panels identical except for their final-day returns differ in
    # dispersion: the cross-sectional width is measured on the panel's final
    # period, not over its history.
    calm = price_panel(
        {
            "AAAUSDT": levels_from_returns(100.0, [0.0] * 30 + [0.01]),
            "BBBUSDT": levels_from_returns(100.0, [0.0] * 30 + [0.01]),
        }
    )
    wide = price_panel(
        {
            "AAAUSDT": levels_from_returns(100.0, [0.0] * 30 + [0.10]),
            "BBBUSDT": levels_from_returns(100.0, [0.0] * 30 + [-0.10]),
        }
    )
    assert cross_sectional_dispersion(calm).dispersion == pytest.approx(0.0)
    assert cross_sectional_dispersion(wide).dispersion > 0.0


def test_a_gap_on_the_final_date_is_not_scored_no_fallback() -> None:
    # The cross-section is the one that existed on the panel's final date, so a
    # member with no print there is dropped — it is NOT scored on its last
    # traded pair, which would give it a return spanning a different interval
    # from every other member's.
    dates = DAYS[:5]
    bars = [
        DailyBar("AAAUSDT", dates[i], 100.0 * math.exp(0.01 * i)) for i in range(5)
    ] + [
        DailyBar("BBBUSDT", dates[i], 50.0 * math.exp(0.01 * i)) for i in range(4)
    ]  # BBBUSDT has a gap on the final date
    panel = PricePanel.from_bars(
        bars, symbols=["AAAUSDT", "BBBUSDT"], dates=dates
    )
    result = cross_sectional_dispersion(panel, min_symbols=2)
    assert result.n == 1  # only AAAUSDT scored
    assert math.isnan(result.dispersion)  # one symbol is not a cross-section
    assert result.mean_return == pytest.approx(0.01)  # AAAUSDT's own return


def test_dispersion_skips_a_member_with_no_return() -> None:
    # A symbol present on the last date only has no return to contribute, so
    # it is not scored — it neither widens nor narrows the spread.
    dates = DAYS[:31]
    bars = (
        [
            DailyBar("AAAUSDT", dates[i], levels_from_returns(100.0, [0.01] * 30)[i])
            for i in range(31)
        ]
        + [
            DailyBar("BBBUSDT", dates[i], 100.0 * math.exp(0.02 * i))
            for i in range(31)
        ]
        + [DailyBar("CCCUSDT", dates[-1], 50.0)]  # one print, no return
    )
    panel = PricePanel.from_bars(
        bars, symbols=["AAAUSDT", "BBBUSDT", "CCCUSDT"], dates=dates
    )
    result = cross_sectional_dispersion(panel)
    assert result.n == 2


def test_thin_cross_section_is_nan_not_zero() -> None:
    # A single scored symbol is not a cross-section: reporting 0.0 would claim
    # the universe moved in lockstep when nothing was measured.
    panel = price_panel({"AAAUSDT": levels_from_returns(100.0, [0.01] * 30)})
    result = cross_sectional_dispersion(panel, min_symbols=2)
    assert result.n == 1
    assert math.isnan(result.dispersion)
    # The mean over the one scored symbol is still reported.
    assert result.mean_return == pytest.approx(0.01)


def test_empty_cross_section_is_nan_over_zero_symbols() -> None:
    panel = PricePanel.from_bars([], symbols=["AAAUSDT", "BBBUSDT"], dates=DAYS[:30])
    result = cross_sectional_dispersion(panel)
    assert result.n == 0
    assert math.isnan(result.dispersion)
    assert math.isnan(result.mean_return)


def test_min_symbols_below_two_is_rejected() -> None:
    panel = price_panel({"AAAUSDT": [100.0, 101.0], "BBBUSDT": [50.0, 51.0]})
    with pytest.raises(ValueError, match="min_symbols"):
        cross_sectional_dispersion(panel, min_symbols=1)


# ---------------------------------------------------------------------------
# Market return series
# ---------------------------------------------------------------------------


def test_market_return_is_the_equal_weighted_mean() -> None:
    # Two members with opposite returns on the final day average to zero; the
    # market series is the cross-sectional mean, not either member's path.
    panel = price_panel(
        {
            "AAAUSDT": levels_from_returns(100.0, [0.0] * 30 + [0.04]),
            "BBBUSDT": levels_from_returns(100.0, [0.0] * 30 + [-0.04]),
        }
    )
    series = market_return_series(panel)
    assert series[-1] == pytest.approx(0.0)


def test_market_return_is_aligned_to_periods_not_dates() -> None:
    # An n-date panel carries n-1 period returns, element i being the return
    # from date i to date i+1 — the same alignment a single symbol's returns
    # use, applied across the cross-section.
    panel = price_panel({"AAAUSDT": levels_from_returns(100.0, [0.01] * 10)})
    series = market_return_series(panel)
    assert len(series) == 10  # 11 closes, 10 returns
    assert series[0] == pytest.approx(0.01)
    assert series[-1] == pytest.approx(0.01)


def test_market_return_marks_a_wholly_unscorable_period_missing() -> None:
    # A period where no member has a return is nan — an absent observation,
    # not a zero return that would read as a flat day.
    dates = DAYS[:3]
    bars = [
        DailyBar("AAAUSDT", dates[0], 100.0),
        # nothing on dates[1]
        DailyBar("AAAUSDT", dates[2], 102.0),
    ]
    panel = PricePanel.from_bars(bars, symbols=["AAAUSDT"], dates=dates)
    series = market_return_series(panel)
    # The two returns are dates[0]->dates[1] (both missing) and
    # dates[1]->dates[2] (only the right side present); neither is scorable.
    assert len(series) == 2
    assert all(math.isnan(value) for value in series)


# ---------------------------------------------------------------------------
# Return autocorrelation
# ---------------------------------------------------------------------------


def test_alternating_series_is_strongly_negatively_autocorrelated() -> None:
    # A series whose sign flips every step correlates at ~ -1 with its own
    # one-step shift — the cleanest possible statement of "several lags".
    series = alternating_returns(60)
    result = return_autocorrelation(series, lags=(1, 2), min_observations=10)
    assert result.at(1) == pytest.approx(-1.0)
    # At lag 2 the flips line up again: ~ +1.
    assert result.at(2) == pytest.approx(1.0)


def test_persistent_series_is_positively_autocorrelated() -> None:
    # Returns drawn from a slowly-varying path resemble their own recent past.
    series = [0.01 * math.sin(index / 12.0) for index in range(80)]
    result = return_autocorrelation(series, lags=(1,), min_observations=10)
    assert result.at(1) > 0.5


def test_several_lags_are_all_reported_in_order() -> None:
    # The feature's "at several lags" clause: every requested lag is present,
    # in the order asked for, with one coefficient and one count each.
    series = alternating_returns(60)
    result = return_autocorrelation(series, lags=(1, 2, 3, 5, 10), min_observations=5)
    assert result.lags == (1, 2, 3, 5, 10)
    assert len(result.coefficients) == 5
    assert len(result.observations) == 5
    assert result.as_dict()[3] == pytest.approx(result.at(3))


def test_default_lags_are_several() -> None:
    # The version-1 definition computes more than one lag: "at several lags"
    # is the contract, and a single lag would not satisfy it.
    result = return_autocorrelation([0.01, -0.02, 0.03] * 20)
    assert result.lags == DEFAULT_LAGS
    assert len(DEFAULT_LAGS) >= 2


def test_lag_beyond_the_history_is_nan_over_zero_pairs() -> None:
    # A lag longer than the series cannot be served: nan over zero pairs, and
    # the count says so — never a default of zero.
    series = [0.01, -0.01] * 3  # 6 observations
    result = return_autocorrelation(series, lags=(1, 50), min_observations=2)
    assert result.at(50) != result.at(50)  # nan
    assert result.observations[result.lags.index(50)] == 0


def test_insufficient_history_leaves_a_lag_unscored() -> None:
    # Three overlapping pairs against a floor of ten: the lag is reported
    # unscored rather than as a coefficient the data does not support.
    series = [0.01, -0.02, 0.03, 0.01, -0.02]
    result = return_autocorrelation(series, lags=(1,), min_observations=10)
    assert result.observations == (4,)
    assert math.isnan(result.at(1))
    assert result.scored() == {}


def test_flat_series_is_not_scored() -> None:
    # No variance either side of the shift: correlation is undefined, and the
    # pair is not scored rather than reported as a spurious perfect one.
    result = return_autocorrelation([0.0] * 40, lags=(1,), min_observations=5)
    assert math.isnan(result.at(1))


def test_missing_values_are_skipped_pairwise() -> None:
    # nan observations drop out of the overlap count without poisoning the
    # remaining pairs — the same pairwise-complete rule feature 57 uses.
    series = [0.01, -0.01, float("nan"), 0.01, -0.01, 0.01, -0.01, 0.01]
    result = return_autocorrelation(series, lags=(1,), min_observations=2)
    # 7 shifted pairs; the nan at index 2 spoils the pairs it sits on either
    # side of, leaving 5 scored.
    assert result.observations == (5,)
    assert not math.isnan(result.at(1))


def test_lag_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="lag 0"):
        return_autocorrelation([0.01, -0.01] * 10, lags=(0,))


def test_duplicate_lags_are_rejected() -> None:
    with pytest.raises(ValueError, match="distinct"):
        return_autocorrelation([0.01, -0.01] * 10, lags=(1, 1))


def test_empty_lags_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one lag"):
        return_autocorrelation([0.01, -0.01] * 10, lags=())


def test_min_observations_below_two_is_rejected() -> None:
    with pytest.raises(ValueError, match="min_observations"):
        return_autocorrelation([0.01, -0.01] * 10, lags=(1,), min_observations=1)


def test_at_raises_for_a_lag_that_was_not_computed() -> None:
    result = return_autocorrelation([0.01, -0.01] * 10, lags=(1,))
    with pytest.raises(KeyError, match="lag 7"):
        result.at(7)


# ---------------------------------------------------------------------------
# Combined entry point and reproducibility
# ---------------------------------------------------------------------------


def test_build_dispersion_metrics_returns_both() -> None:
    panel = price_panel(
        {
            "AAAUSDT": levels_from_returns(100.0, alternating_returns(60)),
            "BBBUSDT": levels_from_returns(100.0, [0.005] * 60),
        }
    )
    metrics = build_dispersion_metrics(panel, lags=(1, 2), min_observations=5)
    assert isinstance(metrics.dispersion, DispersionResult)
    assert isinstance(metrics.autocorrelation, AutocorrelationResult)
    assert metrics.dispersion.n == 2
    assert metrics.autocorrelation.lags == (1, 2)


def test_reductions_are_bit_reproducible() -> None:
    panel = price_panel(
        {
            f"{letter}USDT": levels_from_returns(100.0, [_rng_like(i, letter) for i in range(90)])
            for letter in ("A", "B", "C")
        }
    )
    first = build_dispersion_metrics(panel, lags=(1, 2, 3), min_observations=5)
    second = build_dispersion_metrics(panel, lags=(1, 2, 3), min_observations=5)
    assert first == second


def test_reproducibility_is_payload_bytes_even_when_values_are_nan() -> None:
    # A panel too short to score a lag yields nan, and ``nan != nan`` means the
    # dataclass comparison is False for an *honest* recomputation.  The
    # reproducibility the replay path actually depends on is the encoded
    # payloads, which stay byte-identical regardless of nan — so this pins that
    # the two statements are different claims, and only the second one holds
    # unconditionally.
    panel = price_panel(
        {
            "AAAUSDT": levels_from_returns(100.0, alternating_returns(3)),
            "BBBUSDT": levels_from_returns(100.0, [0.01] * 3),
        }
    )
    first = build_dispersion_metrics(panel, lags=(1,), min_observations=10)
    second = build_dispersion_metrics(panel, lags=(1,), min_observations=10)
    # Every lag is unscored here, so naive equality is False by nan semantics...
    assert math.isnan(first.autocorrelation.at(1))
    assert first != second
    # ...but the encoded payloads — what a replay compares — are identical.
    assert encode_autocorrelation(
        first.autocorrelation, top_n=2
    ) == encode_autocorrelation(second.autocorrelation, top_n=2)
    assert repr(first.autocorrelation.coefficients) == repr(
        second.autocorrelation.coefficients
    )


def _rng_like(index: int, salt: str) -> float:
    """A deterministic, varied log return — no ``random`` import needed."""
    state = (1103515245 * (index + 1) + 12345 * (ord(salt) + 1)) & 0x7FFFFFFF
    return ((state / 0x40000000) - 1.0) * 0.02
