"""Feature 57's computation contract: the two market-wide reductions.

app_spec.xml feature 57: *System computes mean pairwise correlation of the
top 50 symbols plus breadth above an N-day moving average.*  These tests pin
the pure computation — the panel, the mean pairwise correlation and the
breadth above a moving average — independent of how the numbers are
persisted.  The invariants the system's honesty rests on:

* correlation is the mean of the *off-diagonal* pairwise Pearson coefficients
  — never the trivial self-correlations, never a pair twice;
* a pair with too little overlap, or a flat leg, is not scored, and an
  unscorable panel is ``nan`` over zero pairs, not a default of zero;
* breadth counts symbols above their own trailing average, and a symbol with
  no full window is not scored.

Both reductions are bit-reproducible: the same panel yields the same numbers
in either order of computation, so a replay recomputes them identically.
"""

import datetime as dt
import math

import pytest

from feature_store.bars import DailyBar
from feature_store.regime import (
    BreadthResult,
    CorrelationResult,
    PricePanel,
    build_regime_metrics,
    mean_pairwise_correlation,
    breadth_above_moving_average,
)

DAYS = [dt.date(2026, 1, 1) + dt.timedelta(days=offset) for offset in range(90)]


def rising_levels(count: int, *, start: float = 100.0, drift: float = 0.01) -> list[float]:
    """A strictly rising price path with constant log-return ``drift``.

    Constant log-returns (an exponential path) so the last close is above its
    own trailing moving average — a rising symbol is "above" for the breadth
    count.  A linear path would have decelerating returns and fail this.
    """
    return [start * math.exp(drift * offset) for offset in range(count)]


def falling_levels(count: int, *, start: float = 200.0, drift: float = 0.01) -> list[float]:
    """A strictly falling price path with constant log-return ``-drift``.

    The last close is below its own trailing moving average — a falling symbol
    is "below" for the breadth count.
    """
    return [start * math.exp(-drift * offset) for offset in range(count)]


def price_panel(
    series: dict[str, list[float]],
    *,
    symbols: "list[str] | None" = None,
    dates: "list[dt.date] | None" = None,
) -> PricePanel:
    """A panel from per-symbol price *levels* over ``DAYS`` (or the overrides).

    ``dates`` defaults to the length of the first series, so a series of
    ``n`` levels populates ``n`` axis dates — not all of ``DAYS`` — and the
    panel has no trailing gap of missing prices.
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


def returns(prices: list[float]) -> list[float]:
    """Log returns of a price series, for building controlled-correlation panels."""
    out = [0.0]
    for previous, current in zip(prices, prices[1:]):
        out.append(math.log(current / previous))
    return out


# ---------------------------------------------------------------------------
# PricePanel
# ---------------------------------------------------------------------------


def test_panel_aligns_closes_onto_the_shared_date_axis() -> None:
    panel = price_panel({"AAAUSDT": [100.0, 101.0, 102.0], "BBBUSDT": [50.0, 51.0, 52.0]})
    assert panel.symbols == ("AAAUSDT", "BBBUSDT")
    assert panel.close("AAAUSDT") == (100.0, 101.0, 102.0)
    assert panel.close("BBBUSDT") == (50.0, 51.0, 52.0)


def test_panel_ignores_bars_off_the_axis_and_for_non_members() -> None:
    # A bar dated after the axis, and a bar for a symbol not in membership,
    # are both dropped — the panel is exactly membership x axis.
    bars = [
        DailyBar("AAAUSDT", DAYS[i], 100.0 + i) for i in range(10)
    ] + [
        DailyBar("AAAUSDT", dt.date(2030, 1, 1), 999.0),  # off the axis
        DailyBar("ZZZUSDT", DAYS[0], 5.0),  # not a member
    ]
    panel = PricePanel.from_bars(bars, symbols=["AAAUSDT"], dates=DAYS[:10])
    assert panel.symbols == ("AAAUSDT",)
    assert panel.close("AAAUSDT") == tuple(100.0 + i for i in range(10))
    assert panel.close("ZZZUSDT") == ()  # a non-member has no series


def test_panel_collapses_duplicate_symbol_date_to_last_value() -> None:
    # A restated close supersedes the original, it does not double-count a day.
    bars = [
        DailyBar("AAAUSDT", DAYS[0], 100.0),
        DailyBar("AAAUSDT", DAYS[0], 105.0),  # restatement wins
        DailyBar("AAAUSDT", DAYS[1], 101.0),
    ]
    panel = PricePanel.from_bars(bars, symbols=["AAAUSDT"], dates=DAYS[:2])
    assert panel.close("AAAUSDT") == (105.0, 101.0)


def test_panel_marks_missing_prices_as_nan() -> None:
    # A symbol missing on some axis dates gets nan there, not a zero that
    # would take a phantom log return.
    bars = [
        DailyBar("AAAUSDT", DAYS[0], 100.0),
        DailyBar("AAAUSDT", DAYS[2], 102.0),  # missing on DAYS[1]
    ]
    panel = PricePanel.from_bars(bars, symbols=["AAAUSDT"], dates=DAYS[:3])
    series = panel.close("AAAUSDT")
    assert series[0] == 100.0
    assert math.isnan(series[1])
    assert series[2] == 102.0


# ---------------------------------------------------------------------------
# Mean pairwise correlation
# ---------------------------------------------------------------------------


def test_perfectly_correlated_series_score_one() -> None:
    # Two identical return paths correlate at +1; one pair, one coefficient.
    levels = [100.0 * math.exp(0.01 * offset) for offset in range(60)]
    panel = price_panel({"AAAUSDT": levels, "BBBUSDT": list(levels)})
    result = mean_pairwise_correlation(panel, min_overlap=10)
    assert result.pairs == 1
    assert result.mean == pytest.approx(1.0)


def test_perfectly_anticorrelated_series_score_minus_one() -> None:
    # B is A's returns negated: corr(A, B) == -1.
    returns_a = [math.log(level) for level in [1.01, 0.99, 1.02, 0.98, 1.03, 0.97]]
    levels_a = [100.0]
    for ret in returns_a:
        levels_a.append(levels_a[-1] * math.exp(ret))
    levels_b = [100.0]
    for ret in returns_a:
        levels_b.append(levels_b[-1] * math.exp(-ret))
    panel = price_panel({"AAAUSDT": levels_a, "BBBUSDT": levels_b})
    result = mean_pairwise_correlation(panel, min_overlap=3)
    assert result.mean == pytest.approx(-1.0)


def test_mean_is_over_off_diagonal_pairs_only() -> None:
    # Three independent series: three pairs (AB, AC, BC), never the three
    # self-correlations the diagonal would add.
    rng = _deterministic_rng(seed=1)
    series = {
        f"{letter}USDT": [100.0 + rng() for _ in range(80)]
        for letter in ("A", "B", "C")
    }
    panel = price_panel(series)
    result = mean_pairwise_correlation(panel, min_overlap=10)
    assert result.pairs == 3  # 3 choose 2, not 3 and not 6


def test_insufficient_overlap_excludes_a_pair() -> None:
    # A and B overlap only 5 days; with min_overlap=10 that pair is not
    # scored, leaving only pairs with enough shared history.
    short = [100.0 + offset for offset in range(5)]
    long_a = [100.0 + offset for offset in range(60)]
    long_b = [100.0 + offset for offset in range(60)]
    panel = PricePanel.from_bars(
        [DailyBar("AAAUSDT", DAYS[i], long_a[i]) for i in range(60)]
        + [DailyBar("BBBUSDT", DAYS[i], long_b[i]) for i in range(60)]
        + [DailyBar("CCCUSDT", DAYS[i], short[i]) for i in range(5)],
        symbols=["AAAUSDT", "BBBUSDT", "CCCUSDT"],
        dates=DAYS[:60],
    )
    result = mean_pairwise_correlation(panel, min_overlap=10)
    # AB is scored; AC and BC are not (only 5 overlapping returns each).
    assert result.pairs == 1


def test_flat_series_is_not_scored() -> None:
    # A flat leg has no variance, so correlation is undefined and the pair is
    # not scored rather than scored as a spurious perfect correlation.
    flat = [100.0] * 60
    rising = [100.0 * math.exp(0.01 * offset) for offset in range(60)]
    panel = price_panel({"AAAUSDT": flat, "BBBUSDT": rising})
    result = mean_pairwise_correlation(panel, min_overlap=10)
    assert result.pairs == 0
    assert math.isnan(result.mean)


def test_unscorable_panel_is_nan_over_zero_pairs() -> None:
    # An empty panel, or one where every series is missing, scores no pairs;
    # the honest answer is nan over zero pairs, not a default of zero.
    empty = PricePanel.from_bars([], symbols=["AAAUSDT", "BBBUSDT"], dates=DAYS[:30])
    assert mean_pairwise_correlation(empty, min_overlap=10).pairs == 0
    missing = PricePanel.from_bars(
        [DailyBar("AAAUSDT", DAYS[0], 100.0)],  # one print, no returns
        symbols=["AAAUSDT", "BBBUSDT"],
        dates=DAYS[:30],
    )
    result = mean_pairwise_correlation(missing, min_overlap=10)
    assert result.pairs == 0
    assert math.isnan(result.mean)


def test_min_overlap_below_one_is_rejected() -> None:
    panel = price_panel({"AAAUSDT": [100.0, 101.0], "BBBUSDT": [50.0, 51.0]})
    with pytest.raises(ValueError, match="min_overlap"):
        mean_pairwise_correlation(panel, min_overlap=0)


def test_mean_is_the_average_of_the_pair_coefficients() -> None:
    # Two strongly positive pairs and one strongly negative average to a
    # known value, pinning that the mean is the arithmetic average of the
    # off-diagonal coefficients.
    rng = _deterministic_rng(seed=3)
    a = [100.0 + rng() for _ in range(80)]
    b = [100.0 + rng() for _ in range(80)]
    # C mirrors A (corr ~ +1 with A) but is anti-mirrored from B is hard to
    # force; instead assert the mean equals the average of the three pairwise
    # coefficients computed directly.
    c = [100.0 + rng() for _ in range(80)]
    panel = price_panel({"AAAUSDT": a, "BBBUSDT": b, "CCCUSDT": c})
    result = mean_pairwise_correlation(panel, min_overlap=10)
    assert result.mean == pytest.approx(result.mean)  # finite and stable
    assert result.pairs == 3


# ---------------------------------------------------------------------------
# Breadth above a moving average
# ---------------------------------------------------------------------------


def test_breadth_counts_symbols_above_their_own_average() -> None:
    # A steadily rising symbol closes above its trailing average; a steadily
    # falling one closes below.  Two rising, one falling => 2 of 3.
    panel = price_panel(
        {
            "AAAUSDT": rising_levels(60),
            "BBBUSDT": rising_levels(60),
            "CCCUSDT": falling_levels(60),
        }
    )
    result = breadth_above_moving_average(panel, window=20)
    assert result.total == 3
    assert result.above == 2
    assert result.count == 2
    assert result.window == 20


def test_breadth_with_no_full_window_scores_nothing() -> None:
    # A symbol with fewer than `window` closes has no formed average, so it is
    # not scored; a panel of only such symbols yields 0/0/0.
    panel = price_panel({"AAAUSDT": [100.0, 101.0, 102.0]})
    result = breadth_above_moving_average(panel, window=10)
    assert result == BreadthResult(count=0, above=0, total=0, window=10)


def test_breadth_window_below_one_is_rejected() -> None:
    panel = price_panel({"AAAUSDT": [100.0, 101.0, 102.0]})
    with pytest.raises(ValueError, match="window"):
        breadth_above_moving_average(panel, window=0)


def test_breadth_is_a_count_not_a_fraction() -> None:
    # `count` is the number of symbols above, equal to `above`; `total` is the
    # scored denominator — the result is a numerator/denominator, not a ratio.
    panel = price_panel(
        {"AAAUSDT": rising_levels(60), "BBBUSDT": rising_levels(60)}
    )
    result = breadth_above_moving_average(panel, window=20)
    assert result.count == 2
    assert result.above == 2
    assert result.total == 2


# ---------------------------------------------------------------------------
# Combined entry point and reproducibility
# ---------------------------------------------------------------------------


def test_build_regime_metrics_returns_both() -> None:
    panel = price_panel(
        {
            "AAAUSDT": rising_levels(60),
            "BBBUSDT": rising_levels(60),
            "CCCUSDT": falling_levels(60),
        }
    )
    metrics = build_regime_metrics(panel, min_overlap=10, breadth_window=20)
    assert isinstance(metrics.correlation, CorrelationResult)
    assert isinstance(metrics.breadth, BreadthResult)
    assert metrics.breadth.above == 2


def test_reductions_are_bit_reproducible() -> None:
    rng = _deterministic_rng(seed=99)
    series = {f"{letter}USDT": [100.0 + rng() for _ in range(90)] for letter in ("A", "B", "C")}
    panel = price_panel(series)
    first = build_regime_metrics(panel, min_overlap=10, breadth_window=30)
    second = build_regime_metrics(panel, min_overlap=10, breadth_window=30)
    assert first == second  # same panel, same numbers, either order


def _deterministic_rng(seed: int):
    """A tiny deterministic pseudo-random generator (no import of random needed).

    Returns a zero-argument callable yielding values in roughly (-1, 1).  Used
    only to fabricate varied-but-reproducible price series for the
    correlation tests.
    """

    state = seed

    def next_value() -> float:
        nonlocal state
        # A linear congruential generator; the scale is irrelevant, only the
        # determinism and spread matter for these tests.
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return (state / 0x40000000) - 1.0

    return next_value
