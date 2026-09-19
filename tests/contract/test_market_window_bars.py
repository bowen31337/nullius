"""Feature 5 — ``MarketWindow.bars`` returns candle rows, truncated at ``t``.

app_spec.xml, "Signal Contract & Market Window", feature 5: *System exposes
MarketWindow.bars for 1m, 1h and 1d frequencies, which returns a Polars frame
containing no row later than the window decision time.*  docs/nullius-tech-
architecture.md §5.1 declares the accessor (``bars(freq, lookback) ->
pl.DataFrame``), §4.1 fixes the stream behind it (``Klines 1m/1h/1d | REST
backfill + WS | continuous | forever`` — the candle stream feature 17's worker
persists), and §4.2's snapshot layout carries it under ``bars/`` partitions,
which is what a host materializes into a window's frames.

That gives this suite the same halves the trades suite pins, each failing in a
different direction, plus the one this accessor owns:

* **the rows are the candles' rows** — the accessor reads one frame name per
  frequency and returns those rows, verbatim: the venue's own string spellings
  of open/high/low/close/volume come back as the venue spelled them, never
  re-rendered, and the accessor never reaches into feature 9's ``feature:``
  namespace (a *computed* feature named "1m" is a different frame, in both
  directions).
* **the frame is truncated at the decision time** — the half this feature is
  named for.  The window's physical guarantee (feature 4: pre-sliced host-side)
  means an honest window carries no candle opened after ``t``; but a frame that
  *does* carry one — a host bug, a hand-built window — never answers with it,
  with a lookback or without one.  A candle opened exactly *at* ``t`` is not
  after it, and comes back.  The instant the truncation is measured against is
  the candle's ``open_time`` — its place in the open-time-ordered series.
* **the frequency is a closed vocabulary, the one thing this accessor
  validates** — ``"1m"``/``"1h"``/``"1d"`` and nothing else: a request for any
  other cadence is refused (the stream has no rows under it), reported even
  against a window carrying nothing.  Each frequency lives under its own frame
  name, ``bars:<freq>``, and the lookup is exact — a window carrying "1h"
  answers ``bars("1m")`` with an empty frame, not the other cadence's candles.
* **the lookback is a row count, not a duration** — the candle stream is
  bucketed, so ``lookback`` counts rows on the shared discipline every other
  accessor uses: ``None`` is every row the window carries (still truncated), a
  non-negative ``int`` is the trailing rows, and negative / ``bool`` / non-int
  are refused rather than clamped.
* **the row promise is kept, or refused** — feature 5 says a *Polars frame*, so
  a present bars frame must carry ``symbol`` and ``open_time`` (which book,
  which candle-open instant — the two columns the accessor's own mechanics turn
  on); one that does not is refused with a named error naming the missing
  columns, however much of it the caller asked for.  And because the truncation
  is a promise about *instants*, a present ``open_time`` that does not carry
  instants (a string column) is refused by name rather than compared
  lexicographically.  Extra columns pass through untouched.
* **a miss is empty, never a substitute** — a window carrying no frame under
  ``bars:<freq>`` answers with an empty DataFrame, on the same stance features
  6, 7 and 8 take: an empty answer cannot leak a wrong number, whereas a
  "helpful" fallback (another frequency's candles) silently would.
* **the truncation core is instant-exact** — pinned apart from the window via
  the exported :func:`contract.bars.truncate_bars_frame`: a candle opened after
  ``t`` never comes back, a candle opened at ``t`` does, a naive ``open_time``
  column read as UTC, and an aware column in a foreign zone compared *as
  instants*.

Feature 10 (which this accessor must satisfy) is pinned separately in
``test_market_window_accessors.py``; the last test here re-asserts the one
thing this feature could plausibly have broken — that adding an accessor did
not add a timestamp parameter.  Feature 14's payload channel carries the frame
by name, so the rows are also pinned to survive the trip to the sandbox.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

# pyarrow and polars are declared dependencies of the contract member, so under
# the canonical invocation (which is what the acceptance gate runs) both are
# present.  The guard keeps a partially installed environment from turning a
# missing wheel into a collection error that takes the whole repository suite
# down with it — the same idiom ``test_payload.py``,
# ``test_market_window_feature.py`` and ``test_market_window_trades.py`` use.
pa = pytest.importorskip(
    "pyarrow", reason="the bars-accessor suite requires pyarrow (a declared dependency)"
)
pl = pytest.importorskip(
    "polars", reason="the bars-accessor suite requires polars (a declared dependency)"
)
# ``pyarrow.compute`` is not bound by a bare ``import pyarrow``, and one test
# trims a fixture with it.
import pyarrow.compute as pc  # noqa: E402

from contract import (  # noqa: E402
    BARS_FREQUENCIES,
    BARS_REQUIRED_COLUMNS,
    BarsAccessError,
    MarketWindow,
    bars_frame_name,
    feature_frame_name,
    inspect_accessors,
)
from contract.bars import (  # noqa: E402
    check_bars_frame,
    truncate_bars_frame,
    validate_bars_freq,
    validate_bars_lookback,
)
from contract.features import FeatureAccessError  # noqa: E402
from contract.window import _timestamp_param_names  # noqa: E402

T = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
UNIVERSE = ("BTCUSDT", "ETHUSDT")


# --- fixtures ---------------------------------------------------------------


def _bars_frame(**columns: list) -> "pa.Table":
    return pa.table(columns)


def _at(hour: int, minute: int, second: int, microsecond: int = 0) -> datetime:
    return datetime(2026, 9, 1, hour, minute, second, microsecond, tzinfo=timezone.utc)


@pytest.fixture
def candles_frame() -> "pa.Table":
    """Five closed 1m candles over two symbols, oldest first, venue-spelled.

    The shape a host materializes from the sealed ``bars/`` partitions for the
    1m frequency (feature 17): one row per closed candle, the OHLC in the
    venue's own string spelling, an aware-UTC ``open_time`` on the microsecond
    lattice, ``close_time`` and a trade count.  Laid out against ``T`` so every
    boundary this suite pins is a named candle: 90s before t, 60s before, 30s
    before, 1ms before, and exactly *at* the decision time.
    """
    return _bars_frame(
        symbol=["BTCUSDT", "ETHUSDT", "BTCUSDT", "ETHUSDT", "BTCUSDT"],
        interval=["1m"] * 5,
        open=["61234.50", "3001.25", "61235.00", "3001.50", "61236.00"],
        high_price=["61240.00", "3002.00", "61238.00", "3002.50", "61239.00"],
        low_price=["61230.00", "3000.00", "61233.00", "3001.00", "61235.00"],
        close=["61235.00", "3001.50", "61236.00", "3002.00", "61237.00"],
        volume=["12.50000", "8.00000", "10.25000", "9.10000", "11.00000"],
        open_time=pa.array(
            [
                _at(11, 58, 30, 0),
                _at(11, 59, 0, 0),
                _at(11, 59, 30, 0),
                _at(11, 59, 59, 999_000),
                _at(12, 0, 0, 0),
            ],
            type=pa.timestamp("us", tz="UTC"),
        ),
        close_time=pa.array(
            [
                _at(11, 58, 30, 0) + __import__("datetime").timedelta(minutes=1),
                _at(11, 59, 0, 0) + __import__("datetime").timedelta(minutes=1),
                _at(11, 59, 30, 0) + __import__("datetime").timedelta(minutes=1),
                _at(11, 59, 59, 999_000) + __import__("datetime").timedelta(minutes=1),
                _at(12, 0, 0, 0) + __import__("datetime").timedelta(minutes=1),
            ],
            type=pa.timestamp("us", tz="UTC"),
        ),
        trade_count=[101, 202, 102, 203, 103],
    )


@pytest.fixture
def window(candles_frame) -> MarketWindow:
    """A window carrying the 1m candles plus frames it must not confuse."""
    return MarketWindow(
        T,
        UNIVERSE,
        frames={
            bars_frame_name("1m"): candles_frame,
            # A second frequency, present, that a "1m" query must not read.
            bars_frame_name("1h"): _bars_frame(
                symbol=["BTCUSDT"],
                interval=["1h"],
                open=["61000.00"],
                open_time=pa.array(
                    [_at(11, 0, 0, 0)], type=pa.timestamp("us", tz="UTC")
                ),
            ),
            "bars": _bars_frame(close=[1.0]),
            # A *computed* feature that happens to be named "1m" — feature 9's
            # namespace, a different frame in both directions.
            feature_frame_name("1m", "1"): _bars_frame(
                symbol=["BTCUSDT"], score=[9.9]
            ),
        },
    )


# --- the frequency vocabulary ------------------------------------------------


def test_the_frequency_vocabulary_is_the_three_intervals():
    assert BARS_FREQUENCIES == ("1m", "1h", "1d")


def test_a_frequency_outside_the_vocabulary_is_refused(window):
    for bad in ("5m", "1w", "1M", "m", ""):
        with pytest.raises(BarsAccessError):
            window.bars(bad)


def test_a_non_string_frequency_is_refused(window):
    for bad in (1, None, ["1m"]):
        with pytest.raises(BarsAccessError):
            window.bars(bad)


def test_the_refusal_is_reported_even_against_an_empty_window():
    # Ordering, pinned: the *question* is validated before the window is
    # consulted, so a request for a cadence the stream does not carry still
    # reports the typo rather than reading as "no rows for this frequency".
    with pytest.raises(BarsAccessError):
        MarketWindow(T, UNIVERSE).bars("5m")


def test_validate_bars_freq_accepts_the_three_and_refuses_the_rest():
    for good in BARS_FREQUENCIES:
        assert validate_bars_freq(good) == good
    for bad in ("2m", "1d ", " 1h", 1, None, True):
        with pytest.raises(BarsAccessError):
            validate_bars_freq(bad)


# --- the rows are the candles' rows ------------------------------------------


def test_bars_returns_the_rows_the_window_carries(window, candles_frame):
    # The positive half: the rows under the frequency's own frame name come
    # back as a DataFrame of exactly those rows — an honestly-built window is
    # already sliced at t, so the truncation is a no-op that changes nothing.
    assert window.bars("1m").equals(pl.from_arrow(candles_frame))


def test_the_accessor_returns_a_polars_dataframe(window):
    # §5.1 declares ``-> pl.DataFrame``; the Arrow table the window stores is
    # an implementation detail of the transport, not the accessor's return
    # type.
    assert isinstance(window.bars("1m"), pl.DataFrame)


def test_the_prices_come_back_as_the_venue_spelled_them(window):
    # Column *types* are the host's, and the ingest side keeps the venue's own
    # string spelling verbatim — so "61234.50" must come back as that string,
    # not re-rendered into a float whose rounding an audit could not tell from
    # the exchange's own.  A signal that wants floats casts them itself.
    opens = window.bars("1m")["open"].to_list()
    assert opens[0] == "61234.50"
    assert window.bars("1m").schema["open"] == pl.String


def test_extra_columns_pass_through_untouched(window):
    # The OHLC, close_time, trade_count, interval — the venue's own record of
    # its candles is exactly what the frame is for, and a contract that dropped
    # or renamed any of it would be forbidding what it cannot promise.
    answer = window.bars("1m")
    assert set(answer.columns) == {
        "symbol",
        "interval",
        "open",
        "high_price",
        "low_price",
        "close",
        "volume",
        "open_time",
        "close_time",
        "trade_count",
    }
    assert answer["trade_count"].to_list() == [101, 202, 102, 203, 103]
    assert answer["high_price"].to_list() == [
        "61240.00",
        "3002.00",
        "61238.00",
        "3002.50",
        "61239.00",
    ]


def test_bars_does_not_read_the_feature_namespace(window):
    # A *computed* feature named "1m" lives at ``feature:1m:1`` — a different
    # frame, addressed by feature 9's versioned namespace.  The bars accessor
    # reads only the candle frame, so the computed feature's ``score`` column
    # never leaks into the candles' rows.
    answer = window.bars("1m")
    assert "score" not in answer.columns
    assert answer.height == 5


def test_feature_does_not_read_the_bars_frame(window):
    # The inverse direction of the same separation: ``feature("1m", "1")``
    # answers from the versioned frame, never from the observed candle stream —
    # so a signal cannot be handed raw candles under an address that promises
    # one definition's output.
    assert "open_time" not in window.feature("1m", "1").columns
    assert window.feature("1m", "1")["score"].to_list() == [9.9]


def test_a_frequency_query_does_not_read_a_neighbour(window):
    # A window carrying 1m and 1h candles answers bars("1h") from the 1h frame
    # only — never the 1m candles, and never the bare ``bars`` frame.
    answer = window.bars("1h")
    assert answer.height == 1
    assert answer["interval"].to_list() == ["1h"]


def test_the_returned_frame_does_not_alias_the_windows_storage(window):
    # The conversion is zero-copy (Arrow and Polars share buffers), so the two
    # are views of the same values.  What matters is that neither side can be
    # written through: a window is immutable (feature 4), and a converted
    # Polars frame never writes back into the window's table.
    before = window.bars("1m")["open"].to_list()
    frame = window.bars("1m").with_columns(pl.lit("0").alias("open"))
    assert window.bars("1m")["open"].to_list() == before


# --- truncated at the decision time ------------------------------------------


def test_rows_after_the_decision_time_never_come_back():
    # The half the feature is named for.  The window's physical guarantee means
    # an honest host never materializes a candle opened after t — but the
    # promise is about *rows*, rows are checkable, and these rows carry the
    # open instant to check against.  A frame carrying candles opened after t (a
    # host bug, a hand-built window) answers without them, with or without a
    # lookback.
    frame = _bars_frame(
        symbol=["BTCUSDT", "BTCUSDT", "BTCUSDT", "BTCUSDT"],
        open=["1", "2", "3", "4"],
        open_time=pa.array(
            [
                _at(11, 59, 59, 0),
                _at(12, 0, 0, 0),
                _at(12, 0, 0, 1),
                _at(12, 5, 0),
            ],
            type=pa.timestamp("us", tz="UTC"),
        ),
    )
    window = MarketWindow(T, UNIVERSE, frames={bars_frame_name("1m"): frame})
    expected = [_at(11, 59, 59, 0), _at(12, 0, 0, 0)]
    assert window.bars("1m")["open_time"].to_list() == expected
    assert window.bars("1m", 3600)["open_time"].to_list() == expected


def test_the_truncation_runs_whatever_the_lookback():
    # Feature 5's sentence puts the truncation before the lookback: it is the
    # ceiling every slice returns under, so a caller cannot out-range it with a
    # wider span.
    frame = _bars_frame(
        symbol=["BTCUSDT"] * 2,
        open=["1", "2"],
        open_time=pa.array(
            [_at(11, 0, 0, 0), _at(13, 0, 0, 0)],
            type=pa.timestamp("us", tz="UTC"),
        ),
    )
    window = MarketWindow(T, UNIVERSE, frames={bars_frame_name("1m"): frame})
    assert window.bars("1m")["symbol"].to_list() == ["BTCUSDT"]
    assert window.bars("1m", 10**6)["symbol"].to_list() == ["BTCUSDT"]


def test_a_candle_opened_exactly_at_the_decision_time_comes_back(window):
    # The boundary, pinned inclusively: a candle opened at exactly t is not
    # *after* t.  Excluding it would make the truncation [.., t) and let an
    # off-by-one hide inside a boundary nobody can see being dropped.
    answer = window.bars("1m")
    assert answer["open_time"].to_list()[-1] == T


def test_an_honest_window_returns_its_whole_candle_frame(window, candles_frame):
    # The no-op half: on a window whose candles are all opened at or before t —
    # what feature 4's pre-slicing guarantees — the checked truncation changes
    # nothing, and bars() is exactly the frame the host materialized.
    assert window.bars("1m").height == candles_frame.num_rows


# --- the lookback is a row count ---------------------------------------------


def test_lookback_none_returns_every_row_the_window_carries(window, candles_frame):
    assert window.bars("1m", None).height == candles_frame.num_rows


def test_a_row_count_lookback_takes_the_trailing_rows(window):
    # The candle stream is bucketed, so lookback counts rows: the trailing two
    # candles of an oldest-first frame are the two nearest the decision time.
    answer = window.bars("1m", 2)
    assert answer["trade_count"].to_list() == [203, 103]


def test_a_lookback_wider_than_the_frame_returns_the_whole_frame(window, candles_frame):
    # Not an error, and not an empty frame: "the last 500 candles" over a 5-row
    # frame is those 5 rows (truncated at t, which they already are).
    assert window.bars("1m", 500).height == candles_frame.num_rows


def test_a_zero_row_lookback_is_zero_rows_with_the_columns(window, candles_frame):
    # lookback=0 is the empty-but-not-a-miss shape: 0 rows *with* the frame's
    # columns, the shape that distinguishes "no rows" from "no such frame".
    answer = window.bars("1m", 0)
    assert answer.height == 0
    assert answer.columns == list(candles_frame.column_names)


def test_a_negative_lookback_is_refused(window):
    # Refused rather than clamped: a negative count means the caller's
    # arithmetic went wrong, and clamping would hide it behind a plausible
    # answer.  A ValueError, because it is a caller bug at the accessor.
    with pytest.raises(BarsAccessError):
        window.bars("1m", -1)


def test_a_boolean_lookback_is_refused(window):
    # ``True`` is an ``int`` in Python and would silently mean one row — a
    # wrong answer that looks like a right one, which is the failure mode this
    # whole module is built against.
    with pytest.raises(BarsAccessError):
        window.bars("1m", True)


def test_a_non_integer_lookback_is_refused(window):
    for bad in ("2", 2.0, [2]):
        with pytest.raises(BarsAccessError):
            window.bars("1m", bad)


def test_a_malformed_lookback_is_reported_even_against_an_empty_window():
    # Ordering, pinned: the *question* is validated before the window is
    # consulted, so a typo against a window carrying nothing still reports the
    # typo rather than reading as "no rows for this frequency".
    with pytest.raises(BarsAccessError):
        MarketWindow(T, UNIVERSE).bars("1m", -1)


def test_the_refusal_is_bars_own_not_the_feature_accessors():
    # The discipline is shared with ``feature`` (one rule for what a lookback
    # counts) but the error is this accessor's: a stack trace out of
    # ``ctx.bars(...)`` must not point the reader at ``contract.features`` for a
    # rule about a different accessor.
    with pytest.raises(BarsAccessError) as raised:
        MarketWindow(T, UNIVERSE).bars("1m", -1)
    assert not isinstance(raised.value, FeatureAccessError)


# --- the row promise is kept, or refused -------------------------------------


def test_a_frame_missing_a_required_column_is_refused():
    # Feature 5 says a *Polars frame*, not "a frame": a host that materialized
    # some other shape under a frequency's name is refused loudly, at the
    # accessor, rather than handing a signal a frame whose missing column
    # surfaces as a cryptic ColumnNotFoundError three frames inside the signal.
    for missing in BARS_REQUIRED_COLUMNS:
        columns = {
            "symbol": ["BTCUSDT"],
            "open_time": pa.array(
                [_at(11, 59, 0, 0)], type=pa.timestamp("us", tz="UTC")
            ),
        }
        del columns[missing]
        window = MarketWindow(
            T, UNIVERSE, frames={bars_frame_name("1m"): _bars_frame(**columns)}
        )
        with pytest.raises(BarsAccessError):
            window.bars("1m")


def test_the_refusal_names_the_missing_columns():
    # Actionable, not just loud: the error names what the contract expected, so
    # a host learns precisely which columns to materialize.  A frame carrying
    # neither required column names both.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            bars_frame_name("1m"): _bars_frame(
                open=["61234.50"],
                open_time=pa.array(
                    [_at(11, 59, 0, 0)], type=pa.timestamp("us", tz="UTC")
                ),
            )
        },
    )
    with pytest.raises(BarsAccessError, match=r"symbol.*open_time"):
        window.bars("1m")


def test_the_refusal_fires_whatever_the_lookback():
    # A frame that is not candle rows is wrong as a frame, not as a slice of
    # rows: the check precedes the slicing, so even a caller asking for no rows
    # at all hears about the host's mistake.  Here the frame carries ``symbol``
    # but not ``open_time`` — the instant the truncation is computed against —
    # so it is refused however much of it the caller asked for.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            bars_frame_name("1m"): _bars_frame(
                symbol=["BTCUSDT"],
                open=["1"],
            )
        },
    )
    with pytest.raises(BarsAccessError):
        window.bars("1m", 0)
    with pytest.raises(BarsAccessError):
        window.bars("1m")


def test_a_frame_of_only_the_required_columns_is_answerable():
    # The check is deliberately minimal — exactly the two columns the
    # accessor's own mechanics turn on — so a host carrying nothing else is not
    # refused for austerity's sake.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            bars_frame_name("1m"): _bars_frame(
                symbol=["BTCUSDT"],
                open_time=pa.array(
                    [_at(11, 59, 0, 0)], type=pa.timestamp("us", tz="UTC")
                ),
            )
        },
    )
    assert window.bars("1m")["symbol"].to_list() == ["BTCUSDT"]


def test_an_open_time_that_is_not_instants_is_refused():
    # The check the siblings do not make and this accessor must: the truncation
    # is a promise about *instants*, so an open_time spelled as a string would
    # be compared lexicographically — right until the first month boundary, in
    # a way no test over a fixed range would catch.  Refused by name, whatever
    # the lookback.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            bars_frame_name("1m"): _bars_frame(
                symbol=["BTCUSDT"],
                open_time=["2026-09-01T11:59:30+00:00"],
            )
        },
    )
    with pytest.raises(BarsAccessError, match="open_time"):
        window.bars("1m")
    with pytest.raises(BarsAccessError, match="open_time"):
        window.bars("1m", 60)


def test_an_epoch_integer_open_time_is_refused_too():
    # The same refusal for the other common re-spelling: an integer count of
    # epoch milliseconds is an instant's *encoding*, not an instant, and
    # guessing the unit would be exactly the silent wrong comparison the named
    # refusal exists to prevent.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            bars_frame_name("1m"): _bars_frame(
                symbol=["BTCUSDT"], open_time=[1793668770000]
            )
        },
    )
    with pytest.raises(BarsAccessError, match="open_time"):
        window.bars("1m")


def test_check_bars_frame_is_the_pure_core_of_the_refusal(candles_frame):
    # The row-shape check, exercised apart from the window and the DataFrame
    # conversion: it accepts the conforming frame quietly and refuses a
    # non-conforming one by naming what is missing.
    check_bars_frame(candles_frame)  # no raise
    with pytest.raises(BarsAccessError, match="open_time"):
        check_bars_frame(_bars_frame(symbol=["BTCUSDT"]))


def test_check_bars_frame_reads_either_column_spelling(candles_frame):
    # Arrow spells it ``column_names``, polars ``columns``; the check is over
    # the row *shape*, so a host may run it while still holding a polars frame —
    # and a value with neither spelling is refused as not a frame.
    check_bars_frame(pl.from_arrow(candles_frame))


# --- the truncation core, pinned apart from the window -----------------------


def test_truncate_bars_frame_drops_candles_opened_after_t(candles_frame):
    # The exported core, exercised directly: candles opened after t are
    # filtered out, those at or before t are kept, in the frame's own order.
    out = truncate_bars_frame(candles_frame, T)
    assert out.column("open_time").to_pylist() == candles_frame.column(
        "open_time"
    ).to_pylist()  # an honest frame is unchanged


def test_truncate_bars_frame_keeps_only_up_to_t():
    frame = _bars_frame(
        symbol=["BTCUSDT", "BTCUSDT", "BTCUSDT"],
        open=["1", "2", "3"],
        open_time=pa.array(
            [_at(11, 0, 0, 0), _at(12, 0, 0, 0), _at(12, 0, 1, 0)],
            type=pa.timestamp("us", tz="UTC"),
        ),
    )
    out = truncate_bars_frame(frame, T)
    assert out.column("open_time").to_pylist() == [_at(11, 0, 0, 0), _at(12, 0, 0, 0)]


def test_truncate_bars_frame_reads_a_naive_column_as_utc():
    # A naive open_time is read as UTC — the convention every stored timestamp
    # in this system carries — so the UTC bound slices it directly.
    frame = _bars_frame(
        symbol=["BTCUSDT", "BTCUSDT"],
        open=["1", "2"],
        open_time=pa.array(
            [_at(11, 0, 0, 0), _at(13, 0, 0, 0)], type=pa.timestamp("us")
        ),
    )
    out = truncate_bars_frame(frame, T)
    # A naive column keeps its naive spelling — "naive means UTC" is about how
    # the bound is compared, not about re-tagging the column's own values.
    assert out.column("open_time").to_pylist() == [
        datetime(2026, 9, 1, 11, 0, 0)
    ]


def test_truncate_bars_frame_compares_an_aware_column_as_instants():
    # A column in a foreign zone is compared *as instants*: a candle that
    # opened at the same instant as t, only spelled in Tokyo time, is not after
    # t and comes back.
    from datetime import timedelta

    tokyo = timezone(timedelta(hours=9))
    frame = _bars_frame(
        symbol=["BTCUSDT", "BTCUSDT"],
        open=["1", "2"],
        open_time=pa.array(
            [
                datetime(2026, 9, 1, 21, 0, 0, tzinfo=tokyo),  # == 12:00:00Z == T
                datetime(2026, 9, 1, 22, 0, 0, tzinfo=tokyo),  # == 13:00:00Z  > T
            ],
            type=pa.timestamp("us", tz="Asia/Tokyo"),
        ),
    )
    out = truncate_bars_frame(frame, T)
    assert out.num_rows == 1


def test_truncate_bars_frame_refuses_a_non_timestamp_column():
    frame = _bars_frame(
        symbol=["BTCUSDT"],
        open=["1"],
        open_time=["2026-09-01T11:59:30+00:00"],
    )
    with pytest.raises(BarsAccessError, match="open_time"):
        truncate_bars_frame(frame, T)


def test_truncate_bars_frame_refuses_a_naive_decision_time():
    frame = _bars_frame(
        symbol=["BTCUSDT"],
        open=["1"],
        open_time=pa.array(
            [_at(11, 0, 0, 0)], type=pa.timestamp("us", tz="UTC")
        ),
    )
    # A naive decision time is a legitimate value on the window's convention
    # (naive means UTC) — the core reads it as UTC, not refuses it.  What it
    # refuses is a decision time that is not a datetime at all.
    assert truncate_bars_frame(frame, datetime(2026, 9, 1, 12, 0, 0)).num_rows == 1
    with pytest.raises(BarsAccessError):
        truncate_bars_frame(frame, "2026-09-01T12:00:00Z")


# --- the naming, exported and invertible -------------------------------------


def test_bars_frame_name_encodes_the_frequency():
    for freq in BARS_FREQUENCIES:
        assert bars_frame_name(freq) == f"bars:{freq}"


def test_a_bad_frequency_has_no_frame_name():
    with pytest.raises(BarsAccessError):
        bars_frame_name("5m")


# --- feature 10: no widening accessor ----------------------------------------


def test_the_bars_accessor_takes_no_timestamp():
    # The one thing adding an accessor could plausibly have broken: bars takes
    # a frequency and a row-count lookback, and no parameter that reads as a
    # time, so no caller can widen the window through it.
    assert _timestamp_param_names(MarketWindow.bars) == ()
    assert "bars" in inspect_accessors()
