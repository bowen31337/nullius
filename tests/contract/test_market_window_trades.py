"""Feature 6 — ``MarketWindow.trades`` returns the tape, sliced by seconds.

app_spec.xml, "Signal Contract & Market Window", feature 6: *System exposes
MarketWindow.trades over a lookback in seconds, which returns aggregated trade
rows truncated at the decision time.*  docs/nullius-tech-architecture.md §5.1
declares the accessor (``trades(self, lookback_s: int) -> pl.DataFrame``),
§4.1 fixes the stream behind it (``aggTrades | WS | continuous | forever,
compressed`` — the tape feature 18's workers persist), and §4.2's snapshot
layout carries it under ``trades/`` partitions, which is what a host
materializes into a window's frames.

That gives this suite six halves, each failing in a different direction:

* **the rows are the tape's rows** — the accessor reads one fixed frame name
  and returns those rows, verbatim: the venue's own string spellings of price
  and quantity come back as the venue spelled them, never re-rendered, and
  the accessor never reaches into feature 9's ``feature:`` namespace (a
  *computed* feature named "trades" is a different frame, in both
  directions).
* **the rows are truncated at the decision time** — the half this feature is
  named for.  The window's physical guarantee (feature 4: pre-sliced
  host-side) means an honest window carries no post-``t`` rows, and on such
  a window the truncation is a no-op that returns the whole frame; but a
  frame that *does* carry a print after ``t`` — a host bug, a hand-built
  window — never answers with it, with a lookback or without one.  A trade
  exactly *at* ``t`` is not after it, and comes back.
* **the lookback is in seconds, not rows** — the one accessor whose is.  The
  trailing slice is the closed interval ``[t - lookback_s, t]`` computed
  against the decision time on ``event_time``: a trade exactly
  ``lookback_s`` seconds old is within it, ``None`` is every row the window
  carries (still truncated), an over-long span is the whole (truncated)
  frame, and ``0`` is the instant ``t`` itself — normally nothing, and
  never the whole history.  Negative / ``bool`` / non-int are refused,
  reported even against a window carrying nothing.
* **the row promise is kept, or refused** — feature 6 says *rows*, so a
  present trades frame must carry ``symbol`` and ``event_time`` (which book,
  which instant — the two columns the accessor's own mechanics turn on);
  one that does not is refused with a named error naming the missing
  columns, however much of it the caller asked for.  And because the
  truncation and the seconds lookback are promises about *instants*, a
  present ``event_time`` that does not carry instants (a string column) is
  refused by name rather than compared lexicographically.  Extra columns
  pass through untouched.
* **a miss is empty, never a substitute** — a window carrying no trades
  frame answers with an empty DataFrame, on the same stance features 7, 8
  and 9 take: an empty answer cannot leak a wrong number, whereas a
  "helpful" fallback to another frame silently would.
* **the truncation core is instant-exact** — pinned apart from the window
  via the exported :func:`contract.trades.truncate_trades_frame`: the
  closed-interval boundaries, a naive ``event_time`` column read as UTC,
  an aware column in a foreign zone compared *as instants*, and coarser
  units (``ms``) against which the bounds still land exactly.

Feature 10 (which this accessor must satisfy) is pinned separately in
``test_market_window_accessors.py``; the last test here re-asserts the one
thing this feature could plausibly have broken — that adding an accessor did
not add a timestamp parameter.  Feature 14's payload channel carries the
frame by name, so the rows are also pinned to survive the trip to the
sandbox.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

# pyarrow and polars are declared dependencies of the contract member, so under
# the canonical invocation (which is what the acceptance gate runs) both are
# present.  The guard keeps a partially installed environment from turning a
# missing wheel into a collection error that takes the whole repository suite
# down with it — the same idiom ``test_payload.py``,
# ``test_market_window_feature.py`` and ``test_market_window_borrow.py`` use.
pa = pytest.importorskip(
    "pyarrow", reason="the trades-accessor suite requires pyarrow (a declared dependency)"
)
pl = pytest.importorskip(
    "polars", reason="the trades-accessor suite requires polars (a declared dependency)"
)
# ``pyarrow.compute`` is not bound by a bare ``import pyarrow``, and one test
# trims a fixture with it.
import pyarrow.compute as pc  # noqa: E402

from contract import (  # noqa: E402
    TRADES_FRAME_NAME,
    TRADES_REQUIRED_COLUMNS,
    TradesAccessError,
    MarketWindow,
    feature_frame_name,
    inspect_accessors,
)
from contract.features import FeatureAccessError, validate_lookback  # noqa: E402
from contract.trades import (  # noqa: E402
    check_trades_frame,
    truncate_trades_frame,
    validate_trades_lookback,
)
from contract.window import _timestamp_param_names  # noqa: E402

T = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
UNIVERSE = ("BTCUSDT", "ETHUSDT")


# --- fixtures ---------------------------------------------------------------


def _trades_frame(**columns: list) -> "pa.Table":
    return pa.table(columns)


def _at(hour: int, minute: int, second: int, microsecond: int = 0) -> datetime:
    return datetime(2026, 9, 1, hour, minute, second, microsecond, tzinfo=timezone.utc)


@pytest.fixture
def tape_frame() -> "pa.Table":
    """Five aggregated trades over two symbols, oldest first, venue-spelled.

    The shape a host materializes from the sealed ``trades/`` partitions:
    feature 18's :class:`~nullius_ingest.agg_trades.AggTradeRow` verbatim —
    the venue's own string spellings for price and quantity, integer ids,
    an aware-UTC ``event_time`` on the microsecond lattice, a genuine maker
    flag.  Laid out against ``T`` so every boundary this suite pins is a
    named row: 134.75s old, exactly 60s old, 29.5s old, 1ms old, and
    exactly *at* the decision time.
    """
    return _trades_frame(
        symbol=["BTCUSDT", "ETHUSDT", "BTCUSDT", "ETHUSDT", "BTCUSDT"],
        agg_id=[101, 202, 102, 203, 103],
        price=[
            "61234.50",
            "3001.25",
            "61235.00",
            "3001.50",
            "61236.00",
        ],
        quantity=["0.00100", "1.25000", "0.00200", "0.80000", "0.00150"],
        first_trade_id=[1001, 2001, 1002, 2002, 1003],
        last_trade_id=[1001, 2002, 1002, 2003, 1004],
        event_time=pa.array(
            [
                _at(11, 58, 45, 250_000),
                _at(11, 59, 0, 0),
                _at(11, 59, 30, 500_000),
                _at(11, 59, 59, 999_000),
                _at(12, 0, 0, 0),
            ],
            type=pa.timestamp("us", tz="UTC"),
        ),
        is_buyer_maker=[False, True, False, True, False],
    )


@pytest.fixture
def window(tape_frame) -> MarketWindow:
    """A window carrying the tape plus frames it must not confuse."""
    return MarketWindow(
        T,
        UNIVERSE,
        frames={
            TRADES_FRAME_NAME: tape_frame,
            "bars": _trades_frame(close=[1.0]),
            # A *computed* feature that happens to be named "trades" —
            # feature 9's namespace, a different frame in both directions.
            feature_frame_name("trades", "1"): _trades_frame(
                symbol=["BTCUSDT"], score=[9.9]
            ),
        },
    )


# --- the rows are the tape's rows -------------------------------------------


def test_trades_returns_the_rows_the_window_carries(window, tape_frame):
    # The positive half: the rows under the tape's own frame name come back
    # as a DataFrame of exactly those rows — an honestly-built window is
    # already sliced at t, so the truncation is a no-op that changes nothing.
    assert window.trades().equals(pl.from_arrow(tape_frame))


def test_the_accessor_returns_a_polars_dataframe(window):
    # §5.1 declares ``-> pl.DataFrame``; the Arrow table the window stores is
    # an implementation detail of the transport, not the accessor's return
    # type.
    assert isinstance(window.trades(), pl.DataFrame)


def test_the_prices_come_back_as_the_venue_spelled_them(window):
    # Column *types* are the host's, and the ingest side keeps the venue's
    # own string spelling verbatim — so "61234.50" must come back as that
    # string, not re-rendered into a float whose rounding an audit could not
    # tell from the exchange's own.  A signal that wants floats casts them
    # itself, where the cast is visible in its own code.
    prices = window.trades()["price"].to_list()
    assert prices[0] == "61234.50"
    assert window.trades().schema["price"] == pl.String


def test_the_trades_come_back_in_the_tapes_own_order(window):
    # The tape is time-ordered, and a predicate slice preserves order: the
    # rows come back oldest first, so a signal walking them forward walks
    # the market's own chronology.
    times = window.trades(60)["event_time"].to_list()
    assert times == sorted(times)


def test_extra_columns_pass_through_untouched(window):
    # The ids, the maker flag, the quantity — the venue's own record of its
    # trades is exactly what the frame is for, and a contract that dropped
    # or renamed any of it would be forbidding what it cannot promise.
    answer = window.trades()
    assert set(answer.columns) == {
        "symbol",
        "agg_id",
        "price",
        "quantity",
        "first_trade_id",
        "last_trade_id",
        "event_time",
        "is_buyer_maker",
    }
    assert answer["is_buyer_maker"].to_list() == [False, True, False, True, False]
    assert answer["last_trade_id"].to_list() == [1001, 2002, 1002, 2003, 1004]


def test_trades_does_not_read_the_feature_namespace(window):
    # A *computed* feature named "trades" lives at ``feature:trades:1`` — a
    # different frame, addressed by feature 9's versioned namespace.  The
    # trades accessor reads only the tape's own name, so the computed
    # feature's ``score`` column never leaks into the tape's rows.
    answer = window.trades()
    assert "score" not in answer.columns
    assert answer.height == 5


def test_feature_does_not_read_the_trades_frame(window):
    # The inverse direction of the same separation: ``feature("trades", "1")``
    # answers from the versioned frame, never from the observed tape — so a
    # signal cannot be handed raw trades under an address that promises one
    # definition's output.
    assert "event_time" not in window.feature("trades", "1").columns
    assert window.feature("trades", "1")["score"].to_list() == [9.9]


def test_the_returned_frame_does_not_alias_the_windows_storage(window):
    # The conversion is zero-copy (Arrow and Polars share buffers), so the two
    # are views of the same values.  What matters is that neither side can be
    # written through: a window is immutable (feature 4), and a converted
    # Polars frame never writes back into the window's table.
    before = window.trades()["price"].to_list()
    frame = window.trades()
    frame = frame.with_columns(pl.lit("0").alias("price"))
    assert window.trades()["price"].to_list() == before


# --- truncated at the decision time -----------------------------------------


def test_rows_after_the_decision_time_never_come_back():
    # The half the feature is named for.  The window's physical guarantee
    # means an honest host never materializes a post-t row — but the promise
    # is about *rows*, rows are checkable, and these rows carry the instant
    # to check against.  A frame carrying prints after t (a host bug, a
    # hand-built window) answers without them.
    frame = _trades_frame(
        symbol=["BTCUSDT", "ETHUSDT", "BTCUSDT", "BTCUSDT"],
        event_time=pa.array(
            [
                _at(11, 59, 59, 0),
                _at(12, 0, 0, 0),
                _at(12, 0, 0, 1),
                _at(12, 0, 5, 0),
            ],
            type=pa.timestamp("us", tz="UTC"),
        ),
    )
    window = MarketWindow(T, UNIVERSE, frames={TRADES_FRAME_NAME: frame})
    expected = [_at(11, 59, 59, 0), _at(12, 0, 0, 0)]
    assert window.trades()["event_time"].to_list() == expected
    assert window.trades(3600)["event_time"].to_list() == expected
    # And a zero-width lookback is the instant t itself — the print at t,
    # never the ones after it.
    assert window.trades(0)["event_time"].to_list() == [_at(12, 0, 0, 0)]


def test_the_truncation_runs_whatever_the_lookback(tape_frame):
    # Feature 6's sentence puts the truncation before the lookback: it is not
    # a piece of the lookback's arithmetic but the ceiling every slice
    # returns under, so a caller cannot out-range it with a wider span.
    mischievous = _trades_frame(
        symbol=["BTCUSDT"] * 2,
        event_time=pa.array(
            [_at(11, 0, 0, 0), _at(13, 0, 0, 0)],
            type=pa.timestamp("us", tz="UTC"),
        ),
    )
    window = MarketWindow(T, UNIVERSE, frames={TRADES_FRAME_NAME: mischievous})
    assert window.trades()["symbol"].to_list() == ["BTCUSDT"]
    assert window.trades(10**6)["symbol"].to_list() == ["BTCUSDT"]


def test_a_trade_exactly_at_the_decision_time_comes_back(window):
    # The boundary, pinned inclusively: a trade at exactly t is not *after*
    # t.  Excluding it would make the truncation [t - lookback, t) and let
    # an off-by-one hide inside a boundary nobody can see.
    answer = window.trades(60)
    assert answer["event_time"].to_list()[-1] == T


def test_an_honest_window_returns_its_whole_tape(window, tape_frame):
    # The no-op half: on a window whose rows are all at or before t — what
    # feature 4's pre-slicing guarantees — the checked truncation changes
    # nothing, and trades() is exactly the frame the host materialized.
    assert window.trades().height == tape_frame.num_rows


# --- the lookback is in seconds, not rows -----------------------------------


def test_lookback_none_returns_every_row_the_window_carries(window, tape_frame):
    assert window.trades(None).height == tape_frame.num_rows


def test_a_seconds_lookback_spans_the_trailing_wall_clock(window):
    # "The last 60 seconds" is computed against t on event_time: of the
    # fixture's five trades (134.75s, exactly 60s, 29.5s, 1ms and 0 old),
    # the last four are within it and the 134.75s-old print is not.  A row
    # count could not express this — and on the tape it would be a different
    # amount of market every minute.
    answer = window.trades(60)
    assert answer["agg_id"].to_list() == [202, 102, 203, 103]


def test_the_seconds_span_is_not_per_symbol(window):
    # The lookback is a wall-clock interval against t, not a per-symbol
    # budget: both symbols' prints inside the span come back, interleaved as
    # the tape carries them.  Per-symbol slicing is the signal's business.
    answer = window.trades(60)
    assert set(answer["symbol"].to_list()) == {"BTCUSDT", "ETHUSDT"}


def test_a_trade_exactly_lookback_seconds_old_is_within(window):
    # The lower boundary, pinned inclusively: age exactly lookback_s means
    # "the last lookback_s seconds", so the 11:59:00 print is inside a 60s
    # lookback ending at 12:00:00.  Exclusive here would silently drop a
    # boundary print nobody could see being dropped.
    assert 202 in window.trades(60)["agg_id"].to_list()


def test_a_one_second_lookback_is_the_recent_prints_only(window):
    assert window.trades(1)["agg_id"].to_list() == [203, 103]


def test_a_lookback_wider_than_the_tapes_span_returns_the_whole_tape(
    window, tape_frame
):
    # Not an error, and not an empty frame: "the last hour of trades" over a
    # two-minute tape is that tape (truncated at t, which it already is).
    assert window.trades(3600).height == tape_frame.num_rows


def test_a_zero_seconds_lookback_is_the_decision_instant_not_the_history(window):
    # The off-by-one worth pinning: 0 seconds is the instant t itself — a
    # duration of nothing, so normally no rows (a print exactly at t is the
    # exception, and the fixture carries one to say so).  If this ever
    # returned everything, a caller asking for no time would silently get
    # the window's whole history.
    answer = window.trades(0)
    assert answer["agg_id"].to_list() == [103]
    assert answer["event_time"].to_list() == [T]


def test_a_zero_seconds_lookback_on_a_tape_with_no_print_at_t_is_empty(tape_frame):
    # The same rule without the exception: no print exactly at t, and 0
    # seconds answers nothing — 0 rows *with* the frame's columns, the
    # shape that distinguishes it from a miss.
    trimmed = tape_frame.filter(
        pc.less_equal(
            tape_frame.column("event_time"),
            pa.scalar(_at(11, 59, 59, 999_000), type=pa.timestamp("us", tz="UTC")),
        )
    )
    window = MarketWindow(T, UNIVERSE, frames={TRADES_FRAME_NAME: trimmed})
    answer = window.trades(0)
    assert answer.height == 0
    assert answer.columns == tape_frame.column_names


def test_a_lookback_on_an_absent_frame_is_still_empty():
    # Validation and lookup are independent: the miss stays a miss.
    assert MarketWindow(T, UNIVERSE).trades(2).height == 0


def test_a_negative_lookback_is_refused(window):
    # Refused rather than clamped: a negative span means the caller's
    # arithmetic went wrong, and clamping would hide it behind a plausible
    # answer.  A ValueError, because it is a caller bug at the accessor.
    with pytest.raises(TradesAccessError):
        window.trades(-1)


def test_a_boolean_lookback_is_refused(window):
    # ``True`` is an ``int`` in Python and would silently mean one second —
    # a wrong answer that looks like a right one, which is the failure mode
    # this whole module is built against.
    with pytest.raises(TradesAccessError):
        window.trades(True)


def test_a_non_integer_lookback_is_refused(window):
    for bad in ("2", 2.0, [2]):
        with pytest.raises(TradesAccessError):
            window.trades(bad)


def test_a_malformed_request_is_reported_even_against_an_empty_window():
    # Ordering, pinned: the *question* is validated before the window is
    # consulted, so a typo against a window carrying nothing still reports the
    # typo rather than reading as "no rows for this stream".
    empty = MarketWindow(T, UNIVERSE)
    with pytest.raises(TradesAccessError):
        empty.trades(-1)


def test_the_refusal_is_trades_own_not_the_feature_accessors():
    # The discipline is shared with ``feature`` (one rule for what a lookback
    # counts) but the error is this accessor's: a stack trace out of
    # ``ctx.trades(...)`` must not point the reader at ``contract.features``
    # for a rule about a different accessor.
    with pytest.raises(TradesAccessError) as raised:
        MarketWindow(T, UNIVERSE).trades(-1)
    assert not isinstance(raised.value, FeatureAccessError)


# --- the row promise is kept, or refused ------------------------------------


def test_a_frame_missing_a_required_column_is_refused():
    # Feature 6 says *rows*, not "a frame": a host that materialized some
    # other shape under the tape's name is refused loudly, at the accessor,
    # rather than handing a signal a frame whose missing column surfaces as
    # a cryptic ColumnNotFoundError three frames inside the signal.
    for missing in TRADES_REQUIRED_COLUMNS:
        columns = {
            "symbol": ["BTCUSDT"],
            "event_time": pa.array(
                [_at(11, 59, 0, 0)], type=pa.timestamp("us", tz="UTC")
            ),
        }
        del columns[missing]
        window = MarketWindow(
            T, UNIVERSE, frames={TRADES_FRAME_NAME: _trades_frame(**columns)}
        )
        with pytest.raises(TradesAccessError):
            window.trades()


def test_the_refusal_names_the_missing_columns():
    # Actionable, not just loud: the error names what the contract expected,
    # so a host learns precisely which columns to materialize.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={TRADES_FRAME_NAME: _trades_frame(price=["61234.50"])},
    )
    with pytest.raises(TradesAccessError, match=r"symbol.*event_time"):
        window.trades()


def test_the_refusal_fires_whatever_the_lookback():
    # A frame that is not trade rows is wrong as a frame, not as a slice of
    # rows: the check precedes the slicing, so even a caller asking for no
    # time at all hears about the host's mistake.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={TRADES_FRAME_NAME: _trades_frame(symbol=["BTCUSDT"])},
    )
    with pytest.raises(TradesAccessError):
        window.trades(0)
    with pytest.raises(TradesAccessError):
        window.trades()


def test_a_frame_of_only_the_required_columns_is_answerable():
    # The check is deliberately minimal — exactly the two columns the
    # accessor's own mechanics turn on — so a host carrying nothing else is
    # not refused for austerity's sake.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            TRADES_FRAME_NAME: _trades_frame(
                symbol=["BTCUSDT"],
                event_time=pa.array(
                    [_at(11, 59, 0, 0)], type=pa.timestamp("us", tz="UTC")
                ),
            )
        },
    )
    assert window.trades()["symbol"].to_list() == ["BTCUSDT"]


def test_an_event_time_that_is_not_instants_is_refused():
    # The check the siblings do not make and this accessor must: the
    # truncation and the seconds lookback are promises about *instants*, so
    # an event_time spelled as a string would be compared lexicographically
    # — right until the first month boundary, in a way no test over a fixed
    # range would catch.  Refused by name, whatever the lookback.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            TRADES_FRAME_NAME: _trades_frame(
                symbol=["BTCUSDT"],
                event_time=["2026-09-01T11:59:30+00:00"],
            )
        },
    )
    with pytest.raises(TradesAccessError, match="event_time"):
        window.trades()
    with pytest.raises(TradesAccessError, match="event_time"):
        window.trades(60)


def test_an_epoch_integer_event_time_is_refused_too():
    # The same refusal for the other common re-spelling: an integer count of
    # epoch milliseconds is an instant's *encoding*, not an instant, and
    # guessing the unit would be exactly the silent wrong comparison the
    # named refusal exists to prevent.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            TRADES_FRAME_NAME: _trades_frame(
                symbol=["BTCUSDT"], event_time=[1793668770000]
            )
        },
    )
    with pytest.raises(TradesAccessError, match="event_time"):
        window.trades()


def test_check_trades_frame_is_the_pure_core_of_the_refusal(tape_frame):
    # The row-shape check, exercised apart from the window and the DataFrame
    # conversion: it accepts the conforming frame quietly and refuses a
    # non-conforming one by naming what is missing.
    check_trades_frame(tape_frame)  # no raise
    with pytest.raises(TradesAccessError, match="event_time"):
        check_trades_frame(_trades_frame(symbol=["BTCUSDT"]))


def test_check_trades_frame_reads_either_column_spelling(tape_frame):
    # Arrow spells it ``column_names``, polars ``columns``; the check is over
    # the row *shape*, so a host may run it while still holding a polars
    # frame — and a value with neither spelling is refused as not a frame.
    check_trades_frame(pl.from_arrow(tape_frame))
    with pytest.raises(TradesAccessError):
        check_trades_frame(object())


# --- a miss is empty, never a substitute ------------------------------------


def test_a_window_carrying_no_trades_frame_answers_empty():
    # The host materialized nothing for this stream (or nothing had printed
    # by ``t``): the honest answer is no rows, not an exception and not a
    # fallback to whatever frame the window does carry.
    assert MarketWindow(T, UNIVERSE).trades().height == 0
    assert MarketWindow(
        T, UNIVERSE, frames={"bars": _trades_frame(close=[1.0])}
    ).trades().height == 0


def test_a_miss_and_an_empty_read_are_distinguishable(window, tape_frame):
    # Two shapes of empty, on the same terms as features 7, 8 and 9: a window
    # that carries no trades frame yields a frame with *no columns* — the
    # window holds no schema for data it was never given — while a present
    # frame read down to nothing yields 0 rows *with* the frame's columns.
    # So the columns say whether the tape was there at all.
    miss = MarketWindow(T, UNIVERSE).trades()
    empty_read = MarketWindow(
        T,
        UNIVERSE,
        frames={
            TRADES_FRAME_NAME: _trades_frame(
                symbol=[],
                event_time=pa.array([], type=pa.timestamp("us", tz="UTC")),
            )
        },
    ).trades()

    assert miss.height == 0 and empty_read.height == 0
    assert miss.columns == []
    assert set(empty_read.columns) >= set(TRADES_REQUIRED_COLUMNS)


def test_a_missing_price_reports_as_a_missing_column_not_a_silent_zero():
    # The consequence of the shape above, stated as the caller experiences it:
    # asking a miss for its column raises rather than handing back something
    # that could be summed into a zero.  A "helpful" empty frame with invented
    # columns would let a signal compute on absent data and produce a
    # plausible number, which is worse than an exception at the call site.
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        MarketWindow(T, UNIVERSE).trades()["price"]


# --- the truncation core is instant-exact -----------------------------------


def test_the_pure_core_slices_the_closed_interval(tape_frame):
    # [t - lookback_s, t], both ends inclusive, order preserved — pinned
    # apart from the window so the boundary semantics are testable without
    # a fixture that happens to land inside them.
    sliced = truncate_trades_frame(tape_frame, T, 60)
    assert sliced["agg_id"].to_pylist() == [202, 102, 203, 103]
    assert truncate_trades_frame(tape_frame, T, 1)["agg_id"].to_pylist() == [203, 103]
    assert truncate_trades_frame(tape_frame, T, 0)["agg_id"].to_pylist() == [103]


def test_the_pure_core_truncates_without_a_lookback(tape_frame):
    # lookback_s=None is the upper bound alone: every row at or before t,
    # which over this fixture is all of them — and over a mischievous frame
    # drops the post-t prints exactly as the accessor does.
    assert truncate_trades_frame(tape_frame, T, None).num_rows == tape_frame.num_rows
    mischievous = _trades_frame(
        symbol=["BTCUSDT"] * 2,
        event_time=pa.array(
            [_at(11, 59, 0, 0), _at(12, 0, 0, 1)],
            type=pa.timestamp("us", tz="UTC"),
        ),
    )
    assert truncate_trades_frame(mischievous, T, None).num_rows == 1


def test_a_naive_event_time_column_is_read_as_utc():
    # The system's convention — naive means UTC — applied to the column: a
    # host that materialized naive timestamps gets the same slice an aware
    # host does, because the bounds are compared against the column in its
    # own spelling of the same instants.
    frame = _trades_frame(
        symbol=["BTCUSDT", "ETHUSDT"],
        event_time=pa.array(
            [datetime(2026, 9, 1, 11, 59, 30), datetime(2026, 9, 1, 12, 0, 0)],
            type=pa.timestamp("ms"),
        ),
    )
    window = MarketWindow(T, UNIVERSE, frames={TRADES_FRAME_NAME: frame})
    assert window.trades(60).height == 2
    assert window.trades(10).height == 1


def test_an_aware_column_in_a_foreign_zone_slices_by_instant():
    # A column displaying Tokyo time is still a column of *instants*, and the
    # bounds travel as the instants they name: the same wall-clock lookback
    # selects the same trades a UTC column would.  Comparing displayed wall
    # values across zones would be exactly the silent wrong comparison.
    frame = _trades_frame(
        symbol=["BTCUSDT", "ETHUSDT"],
        event_time=pa.array(
            # The instants a UTC column would carry — 29.5s before t and
            # exactly at it — materialized into a column that *displays*
            # them in Tokyo; the type, not the values, is what differs.
            [
                datetime(2026, 9, 1, 11, 59, 30, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
            ],
            type=pa.timestamp("us", tz="Asia/Tokyo"),
        ),
    )
    window = MarketWindow(T, UNIVERSE, frames={TRADES_FRAME_NAME: frame})
    assert window.trades(60).height == 2
    assert window.trades(10).height == 1


def test_the_bounds_land_exactly_on_coarser_units():
    # A millisecond-resolution column against a microsecond decision time:
    # the bounds convert to the column's own unit, so a trade exactly on the
    # boundary is included and nothing is lost to a rounding nobody asked
    # for.
    frame = _trades_frame(
        symbol=["BTCUSDT"] * 3,
        event_time=pa.array(
            [
                datetime(2026, 9, 1, 11, 58, 59, 999_500),
                datetime(2026, 9, 1, 11, 59, 0, 0),
                datetime(2026, 9, 1, 11, 59, 0, 1_000),
            ],
            type=pa.timestamp("ms"),
        ),
    )
    window = MarketWindow(T, UNIVERSE, frames={TRADES_FRAME_NAME: frame})
    assert window.trades(60).height == 2  # the boundary print and the one after


def test_the_core_refuses_a_non_instant_column_by_name(tape_frame):
    # The named refusal, pinned apart from the accessor: the message carries
    # the actual type, so a host learns what event_time is rather than what
    # it is not.
    with pytest.raises(TradesAccessError, match="string"):
        truncate_trades_frame(
            _trades_frame(symbol=["A"], event_time=["2026-09-01"]), T, 60
        )


# --- validation core --------------------------------------------------------


def test_validate_trades_lookback_accepts_none_and_non_negative_ints():
    assert validate_trades_lookback(None) is None
    assert validate_trades_lookback(0) == 0
    assert validate_trades_lookback(7) == 7


def test_validate_trades_lookback_refuses_everything_else():
    for bad in (-1, True, False, 1.0, "1", [1]):
        with pytest.raises(TradesAccessError):
            validate_trades_lookback(bad)


def test_validate_trades_lookback_shares_the_feature_discipline():
    # One lookback discipline across every accessor: the two validators answer
    # and refuse the same domain, so ``trades`` cannot drift from ``feature``
    # over what a lookback counts — the unit differs, the rule does not.
    for value in (None, 0, 1, 10**6):
        assert validate_trades_lookback(value) == validate_lookback(value)
    for bad in (-1, True, 1.0, "1"):
        with pytest.raises(ValueError):
            validate_trades_lookback(bad)
        with pytest.raises(ValueError):
            validate_lookback(bad)


# --- the rows survive the payload channel (feature 14) ----------------------


def test_the_trades_travel_with_the_payload(tape_frame):
    # The sandbox holds no filesystem and obtains its window only as Arrow IPC
    # bytes (feature 14, §5.2), and frame names are what the payload manifest
    # records.  So a window that crossed the channel still answers the tape —
    # venue spellings and microsecond instants included, truncation included
    # — and a rebuilt window that never carried the tape still answers empty.
    window = MarketWindow(T, UNIVERSE, frames={TRADES_FRAME_NAME: tape_frame})
    rebuilt = window.to_arrow().materialize()
    assert rebuilt.trades().equals(window.trades())
    assert rebuilt.trades(60).equals(window.trades(60))
    assert rebuilt.trades()["price"].to_list()[0] == "61234.50"

    empty = MarketWindow(
        T, UNIVERSE, frames={"bars": _trades_frame(close=[1.0])}
    )
    assert empty.to_arrow().materialize().trades().shape == (0, 0)


# --- feature 10 still holds -------------------------------------------------


def test_the_new_accessor_takes_no_timestamp_argument():
    # Feature 10's requirement, re-asserted over the surface *this* feature
    # changed: adding an accessor is exactly the edit that could have
    # reintroduced a widening parameter, and `lookback_s` — a duration, not
    # an instant — must not be flagged as one.
    assert _timestamp_param_names(MarketWindow.trades) == ()
    assert "trades" in inspect_accessors()
