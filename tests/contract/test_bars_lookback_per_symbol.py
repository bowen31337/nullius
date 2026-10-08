"""bug_spec_bars_lookback_per_symbol.xml — ``bars``' lookback counts per symbol.

``MarketWindow.bars(freq, lookback=N)`` used to take the trailing ``N`` rows
of the whole multi-symbol frame — so over a real snapshot's 23-40 symbols, a
20-to-120-row lookback left each symbol with 0-5 candles, lookback features
were uncomputable, and the authoring prompt's own example signal
(``EXAMPLE_SIGNAL_SOURCE``) returned a constant zero vector that
``evaluator.normalize_scores`` refused.

The fix: ``lookback`` counts rows *per symbol*. For each symbol present in the
frame, ``bars`` returns that symbol's own trailing ``lookback`` candles at or
before ``t``, and the result is reassembled oldest-first by ``(symbol,
open_time)``. A symbol with fewer than ``lookback`` candles of its own
contributes all of them — never padded, never an error. ``lookback=None``
and the ``t``-truncation are unchanged; only the trailing-slice discipline
changed from "across the frame" to "per symbol".

This suite exercises the fix at the symptom's own scale (40 symbols x 60
daily candles), plus the edge cases the bug's ``expected`` section names:
a thin symbol, ``lookback=0``, ``lookback=None``, truncation combined with the
per-symbol slice, and ordering stability.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pa = pytest.importorskip(
    "pyarrow", reason="the bars lookback suite requires pyarrow (a declared dependency)"
)
pl = pytest.importorskip(
    "polars", reason="the bars lookback suite requires polars (a declared dependency)"
)

from contract import MarketWindow, bars_frame_name

N_SYMBOLS = 40
N_DAYS = 60
SYMBOLS = tuple(f"SYM{index:02d}USDT" for index in range(N_SYMBOLS))


def _day(offset: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)


#: Well after the last candle in every fixture below, so the window's own
#: physical truncation is a no-op except in the test that deliberately checks
#: it combined with the per-symbol slice.
T = _day(1000)


def _grid_frame(thin_symbol: str | None = None, thin_count: int | None = None) -> pa.Table:
    """``N_SYMBOLS`` symbols x ``N_DAYS`` daily candles, oldest first per
    symbol. ``thin_symbol`` (if given) carries only ``thin_count`` of its own
    candles, the rest unaffected -- the "fewer candles than lookback" case.
    """
    symbols: list[str] = []
    open_times: list[datetime] = []
    closes: list[str] = []
    for symbol in SYMBOLS:
        count = thin_count if symbol == thin_symbol else N_DAYS
        for day in range(count):
            symbols.append(symbol)
            open_times.append(_day(day))
            closes.append(f"{100.0 + day:.2f}")
    return pa.table(
        {
            "symbol": symbols,
            "open_time": pa.array(open_times, type=pa.timestamp("us", tz="UTC")),
            "close": closes,
        }
    )


@pytest.fixture
def window() -> MarketWindow:
    return MarketWindow(
        T, SYMBOLS, frames={bars_frame_name("1d"): _grid_frame()}
    )


# --- each symbol gets its own trailing lookback ------------------------------


def test_each_symbol_gets_exactly_lookback_rows(window):
    answer = window.bars("1d", 20)
    assert answer.height == N_SYMBOLS * 20
    for symbol in SYMBOLS:
        rows = answer.filter(pl.col("symbol") == symbol)
        assert rows.height == 20
        # The trailing 20 of 60 daily candles: days 40..59.
        assert rows["open_time"].to_list() == [_day(d) for d in range(40, 60)]


def test_a_lookback_wider_than_a_symbols_history_returns_all_of_it(window):
    answer = window.bars("1d", N_DAYS + 500)
    assert answer.height == N_SYMBOLS * N_DAYS
    for symbol in SYMBOLS:
        rows = answer.filter(pl.col("symbol") == symbol)
        assert rows.height == N_DAYS
        assert rows["open_time"].to_list() == [_day(d) for d in range(N_DAYS)]


def test_a_symbol_with_fewer_candles_than_lookback_returns_all_of_its_own():
    thin = SYMBOLS[7]
    frame = _grid_frame(thin_symbol=thin, thin_count=5)
    window = MarketWindow(T, SYMBOLS, frames={bars_frame_name("1d"): frame})

    answer = window.bars("1d", 20)
    thin_rows = answer.filter(pl.col("symbol") == thin)
    assert thin_rows.height == 5
    assert thin_rows["open_time"].to_list() == [_day(d) for d in range(5)]

    # Every other symbol is unaffected: still 20 of its own 60.
    other = answer.filter(pl.col("symbol") == SYMBOLS[0])
    assert other.height == 20


# --- lookback=0 and lookback=None --------------------------------------------


def test_lookback_zero_is_empty_with_the_columns_kept(window):
    answer = window.bars("1d", 0)
    assert answer.height == 0
    assert answer.columns == ["symbol", "open_time", "close"]


def test_lookback_none_returns_every_candle_the_window_carries(window):
    answer = window.bars("1d", None)
    assert answer.height == N_SYMBOLS * N_DAYS


# --- t-truncation still holds, combined with the per-symbol slice -----------


def test_truncation_runs_before_the_per_symbol_slice():
    # A window whose decision time lands inside the 60-day grid: the candles
    # opened after it must never count toward "the trailing 5", on the same
    # discipline every other accessor's truncation enforces.
    cutoff_day = 50
    t = _day(cutoff_day)
    window = MarketWindow(
        t, SYMBOLS, frames={bars_frame_name("1d"): _grid_frame()}
    )
    answer = window.bars("1d", 5)
    for symbol in (SYMBOLS[0], SYMBOLS[-1]):
        rows = answer.filter(pl.col("symbol") == symbol)
        assert rows.height == 5
        assert rows["open_time"].to_list() == [
            _day(d) for d in range(cutoff_day - 4, cutoff_day + 1)
        ]
    # None of the post-cutoff candles (days 51..59) ever appear.
    assert answer["open_time"].max() == t


def test_truncation_to_nothing_is_empty_with_the_columns_kept():
    # t before every candle: the truncation leaves 0 rows, and a positive
    # lookback over 0 rows must still answer empty-with-columns, not raise.
    t = _day(-1)
    window = MarketWindow(t, SYMBOLS, frames={bars_frame_name("1d"): _grid_frame()})
    answer = window.bars("1d", 20)
    assert answer.height == 0
    assert answer.columns == ["symbol", "open_time", "close"]


# --- ordering: oldest-first by (symbol, open_time) --------------------------


def test_ordering_is_oldest_first_by_symbol_then_open_time(window):
    answer = window.bars("1d", 20)
    pairs = list(zip(answer["symbol"].to_list(), answer["open_time"].to_list()))
    assert pairs == sorted(pairs)


def test_ordering_holds_for_a_mixed_history_universe_too():
    thin = SYMBOLS[3]
    frame = _grid_frame(thin_symbol=thin, thin_count=7)
    window = MarketWindow(T, SYMBOLS, frames={bars_frame_name("1d"): frame})
    answer = window.bars("1d", 20)
    pairs = list(zip(answer["symbol"].to_list(), answer["open_time"].to_list()))
    assert pairs == sorted(pairs)


# --- validation and the empty-frame miss are unaffected ----------------------


def test_a_negative_lookback_is_still_refused(window):
    from contract import BarsAccessError

    with pytest.raises(BarsAccessError):
        window.bars("1d", -1)


def test_a_window_carrying_no_bars_frame_still_answers_empty():
    window = MarketWindow(T, SYMBOLS)
    answer = window.bars("1d", 20)
    assert answer.shape == (0, 0)
