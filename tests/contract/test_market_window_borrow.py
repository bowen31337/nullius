"""Feature 8 — ``MarketWindow.borrow`` returns margin borrow rate rows.

app_spec.xml, "Signal Contract & Market Window", feature 8: *System exposes
MarketWindow.borrow which returns margin borrow rate rows used as a real-time
crowding proxy.*  docs/nullius-tech-architecture.md §5.1 declares the accessor
(``borrow(self, lookback: int) -> pl.DataFrame``), §4.1 fixes the stream behind
it (``Funding / borrow rate | REST | 1m | forever`` — the 60-second poll of
feature 23), and the PRD names the use: margin borrow rate is *a real-time
crowding indicator that substitutes for paid short-interest data*, so the rows
this accessor hands back are the crowding observation a signal conditions on.

That gives this suite four halves, each failing in a different direction:

* **the rows are the borrow rows** — the accessor reads one fixed frame name
  and returns those rows, verbatim: the venue's own string spelling of a rate
  comes back as the venue spelled it, never re-rendered, and the accessor
  never reaches into feature 9's ``feature:`` namespace (a *computed* feature
  named "borrow" is a different frame, in both directions).
* **the row promise is kept, or refused** — feature 8 says *rows*, not "a
  frame", so a present borrow frame must carry ``symbol`` and ``borrow_rate``;
  one that does not is refused with a named error naming the missing columns,
  however much of it the caller asked for.  Extra columns pass through
  untouched — the crowding proxy legitimately reads ``utilization`` and
  ``reading_time``, and the contract loses nothing by carrying them.
* **a miss is empty, never a substitute** — a window carrying no borrow frame
  answers with an empty DataFrame, on the same stance feature 9 takes: an
  empty answer cannot leak a wrong number, whereas a "helpful" fallback to
  another frame silently would.
* **the lookback is the shared discipline** — ``None`` is every row, a
  non-negative int is the trailing rows counted across the whole frame, an
  over-long count is the whole frame, ``0`` is empty, and negative / ``bool``
  / non-int are refused — reported even against a window carrying nothing,
  so a caller bug never reads as a data gap.

Feature 10 (which this accessor must satisfy) is pinned separately in
``test_market_window_accessors.py``; the last test here re-asserts the one
thing this feature could plausibly have broken — that adding an accessor did
not add a timestamp parameter.  Feature 14's payload channel carries the
frame by name, so the rows are also pinned to survive the trip to the sandbox.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

# pyarrow and polars are declared dependencies of the contract member, so under
# the canonical invocation (which is what the acceptance gate runs) both are
# present.  The guard keeps a partially installed environment from turning a
# missing wheel into a collection error that takes the whole repository suite
# down with it — the same idiom ``test_payload.py`` and
# ``test_market_window_feature.py`` use.
pa = pytest.importorskip(
    "pyarrow", reason="the borrow-accessor suite requires pyarrow (a declared dependency)"
)
pl = pytest.importorskip(
    "polars", reason="the borrow-accessor suite requires polars (a declared dependency)"
)

from contract import (  # noqa: E402
    BORROW_FRAME_NAME,
    BORROW_REQUIRED_COLUMNS,
    BorrowAccessError,
    MarketWindow,
    feature_frame_name,
    inspect_accessors,
)
from contract.borrow import (  # noqa: E402
    check_borrow_frame,
    validate_borrow_lookback,
)
from contract.features import FeatureAccessError, validate_lookback  # noqa: E402
from contract.window import _timestamp_param_names  # noqa: E402

T = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
UNIVERSE = ("BTCUSDT", "ETHUSDT")


# --- fixtures ---------------------------------------------------------------


def _borrow_frame(**columns: list) -> "pa.Table":
    return pa.table(columns)


@pytest.fixture
def borrow_frame() -> "pa.Table":
    """Three polls over two symbols, oldest first, in the venue's spelling.

    The shape a host materializes from the sealed ``borrow/`` partitions: one
    row per symbol per poll, ``borrow_rate`` kept as the venue's own string
    (feature 23's verbatim discipline — ``"0.0001"``, not ``0.0001``), plus
    the passthrough columns a crowding proxy reads alongside the rate.
    """
    return _borrow_frame(
        symbol=[
            "BTCUSDT",
            "ETHUSDT",
            "BTCUSDT",
            "ETHUSDT",
            "BTCUSDT",
            "ETHUSDT",
        ],
        borrow_rate=[
            "0.00010000",
            "0.00020000",
            "0.00010000",
            "0.00030000",
            "0.00070000",
            "0.00030000",
        ],
        funding_rate=[
            "0.00010000",
            "0.00010000",
            "0.00010000",
            "0.00010000",
            "0.00010000",
            "0.00010000",
        ],
        utilization=[0.31, 0.12, 0.30, 0.44, 0.71, 0.45],
        reading_time=pa.array(
            [
                datetime(2026, 9, 1, 11, 58, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 11, 58, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 11, 59, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 11, 59, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
            ],
            type=pa.timestamp("us", tz="UTC"),
        ),
    )


@pytest.fixture
def window(borrow_frame) -> MarketWindow:
    """A window carrying the borrow frame plus frames it must not confuse."""
    return MarketWindow(
        T,
        UNIVERSE,
        frames={
            BORROW_FRAME_NAME: borrow_frame,
            "bars": _borrow_frame(ts=[1], close=[1.0]),
            # A *computed* feature that happens to be named "borrow" — feature
            # 9's namespace, a different frame in both directions.
            feature_frame_name("borrow", "1"): _borrow_frame(
                symbol=["BTCUSDT"], score=[9.9]
            ),
        },
    )


# --- the rows are the borrow rows -------------------------------------------


def test_borrow_returns_the_rows_the_window_carries(window, borrow_frame):
    # The positive half: the rows under the stream's own frame name come back
    # as a DataFrame of exactly those rows.
    assert window.borrow().equals(pl.from_arrow(borrow_frame))


def test_the_accessor_returns_a_polars_dataframe(window):
    # §5.1 declares ``-> pl.DataFrame``; the Arrow table the window stores is
    # an implementation detail of the transport, not the accessor's return
    # type.
    assert isinstance(window.borrow(), pl.DataFrame)


def test_the_rates_come_back_as_the_venue_spelled_them(window):
    # Column *types* are the host's, and the ingest side keeps the venue's own
    # string spelling verbatim — so "0.00010000" must come back as that string,
    # not re-rendered into a float whose rounding an audit could not tell from
    # the exchange's own.  A proxy that wants floats casts them itself, where
    # the cast is visible in its own code.
    rates = window.borrow()["borrow_rate"].to_list()
    assert rates[0] == "0.00010000"
    assert rates[4] == "0.00070000"
    assert window.borrow().schema["borrow_rate"] == pl.String


def test_a_numeric_borrow_rate_column_is_equally_valid():
    # The promise is the *columns*, not their types: a host that materialized
    # floats satisfies "margin borrow rate rows" just as fully, and the
    # accessor must not prefer one rendering over the other.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            BORROW_FRAME_NAME: _borrow_frame(
                symbol=["BTCUSDT"], borrow_rate=[1e-4]
            ),
        },
    )
    assert window.borrow()["borrow_rate"].to_list() == [1e-4]


def test_extra_columns_pass_through_untouched(window):
    # ``utilization`` and ``reading_time`` are exactly the columns the PRD's
    # crowding proxy reads alongside the rate ("margin borrow rate and
    # utilization"), so a contract that dropped or renamed them would be
    # forbidding what it cannot promise — and quietly breaking the proxy.
    answer = window.borrow()
    assert answer["utilization"].to_list()[0] == 0.31
    assert answer["reading_time"].to_list()[-1] == datetime(
        2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc
    )
    assert set(answer.columns) == {
        "symbol",
        "borrow_rate",
        "funding_rate",
        "utilization",
        "reading_time",
    }


def test_borrow_does_not_read_the_feature_namespace(window):
    # A *computed* feature named "borrow" lives at ``feature:borrow:1`` — a
    # different frame, addressed by feature 9's versioned namespace.  The
    # borrow accessor reads only the stream's own name, so the computed
    # feature's ``score`` column never leaks into the crowding proxy's rows.
    answer = window.borrow()
    assert "score" not in answer.columns
    assert answer.height == 6


def test_feature_does_not_read_the_borrow_frame(window):
    # The inverse direction of the same separation: ``feature("borrow", "1")``
    # answers from the versioned frame, never from the observed stream — so a
    # signal cannot be handed raw borrow rows under an address that promises
    # one definition's output.
    assert "borrow_rate" not in window.feature("borrow", "1").columns
    assert window.feature("borrow", "1")["score"].to_list() == [9.9]


def test_the_returned_frame_does_not_alias_the_windows_storage(window):
    # The conversion is zero-copy (Arrow and Polars share buffers), so the two
    # are views of the same values.  What matters is that neither side can be
    # written through: a window is immutable (feature 4), and a converted
    # Polars frame never writes back into the window's table.
    before = window.borrow()["borrow_rate"].to_list()
    frame = window.borrow()
    frame = frame.with_columns(pl.lit("0").alias("borrow_rate"))
    assert window.borrow()["borrow_rate"].to_list() == before


# --- the row promise is kept, or refused ------------------------------------


def test_a_frame_missing_a_required_column_is_refused():
    # Feature 8 says *rows*, not "a frame": a host that materialized some
    # other shape under the stream's name is refused loudly, at the accessor,
    # rather than handing a signal a frame whose missing column surfaces as a
    # cryptic ColumnNotFoundError three frames inside the signal.
    for missing in BORROW_REQUIRED_COLUMNS:
        columns = {
            "symbol": ["BTCUSDT"],
            "borrow_rate": ["0.0001"],
        }
        del columns[missing]
        window = MarketWindow(
            T, UNIVERSE, frames={BORROW_FRAME_NAME: _borrow_frame(**columns)}
        )
        with pytest.raises(BorrowAccessError):
            window.borrow()


def test_the_refusal_names_the_missing_columns():
    # Actionable, not just loud: the error names what the contract expected,
    # so a host learns precisely which columns to materialize.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={BORROW_FRAME_NAME: _borrow_frame(rate=["0.0001"])},
    )
    with pytest.raises(BorrowAccessError, match=r"symbol.*borrow_rate"):
        window.borrow()


def test_the_refusal_fires_whatever_the_lookback():
    # A frame that is not borrow rate rows is wrong as a frame, not as a
    # slice of rows: the check precedes the slicing, so even a caller asking
    # for no rows at all hears about the host's mistake.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={BORROW_FRAME_NAME: _borrow_frame(symbol=["BTCUSDT"])},
    )
    with pytest.raises(BorrowAccessError):
        window.borrow(lookback=0)
    with pytest.raises(BorrowAccessError):
        window.borrow()


def test_a_frame_of_only_the_required_columns_is_answerable():
    # The check is deliberately minimal — exactly the two columns every
    # consumer of borrow rate rows needs — so a host carrying nothing else is
    # not refused for austerity's sake.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            BORROW_FRAME_NAME: _borrow_frame(
                symbol=["BTCUSDT"], borrow_rate=["0.0001"]
            )
        },
    )
    assert window.borrow()["borrow_rate"].to_list() == ["0.0001"]


def test_check_borrow_frame_is_the_pure_core_of_the_refusal(borrow_frame):
    # The row-shape check, exercised apart from the window and the DataFrame
    # conversion: it accepts the conforming frame quietly and refuses a
    # non-conforming one by naming what is missing.
    check_borrow_frame(borrow_frame)  # no raise
    with pytest.raises(BorrowAccessError, match="borrow_rate"):
        check_borrow_frame(_borrow_frame(symbol=["BTCUSDT"]))


def test_check_borrow_frame_reads_either_column_spelling(borrow_frame):
    # Arrow spells it ``column_names``, polars ``columns``; the check is over
    # the row *shape*, so a host may run it while still holding a polars
    # frame — and a value with neither spelling is refused as not a frame.
    check_borrow_frame(pl.from_arrow(borrow_frame))
    with pytest.raises(BorrowAccessError):
        check_borrow_frame(object())


# --- a miss is empty, never a substitute ------------------------------------


def test_a_window_carrying_no_borrow_frame_answers_empty():
    # The host materialized nothing for this stream (or the poll had not run
    # at ``t``): the honest answer is no rows, not an exception and not a
    # fallback to whatever frame the window does carry.
    assert MarketWindow(T, UNIVERSE).borrow().height == 0
    assert MarketWindow(
        T, UNIVERSE, frames={"bars": _borrow_frame(close=[1.0])}
    ).borrow().height == 0


def test_a_miss_and_an_empty_read_are_distinguishable(window):
    # Two shapes of empty, on the same terms as feature 9: a window that
    # carries no borrow frame yields a frame with *no columns* — the window
    # holds no schema for data it was never given — while a present frame read
    # down to nothing yields 0 rows *with* the frame's columns.  So the
    # columns say whether the stream was there at all.
    miss = MarketWindow(T, UNIVERSE).borrow()
    empty_read = window.borrow(lookback=0)

    assert miss.height == 0 and empty_read.height == 0
    assert miss.columns == []
    assert set(empty_read.columns) >= {"symbol", "borrow_rate"}


def test_a_missing_rate_reports_as_a_missing_column_not_a_silent_zero():
    # The consequence of the shape above, stated as the caller experiences it:
    # asking a miss for its column raises rather than handing back something
    # that could be summed into a zero.  A "helpful" empty frame with invented
    # columns would let a signal compute on absent data and produce a
    # plausible number, which is worse than an exception at the call site.
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        MarketWindow(T, UNIVERSE).borrow()["borrow_rate"]


# --- the lookback is the shared discipline ----------------------------------


def test_lookback_none_returns_every_row_the_window_carries(window, borrow_frame):
    assert window.borrow(None).height == borrow_frame.num_rows


def test_lookback_returns_the_trailing_rows(window):
    # "The last N rows" is the recent end of an oldest-first frame — the end
    # nearest the decision time, which is what a crowding proxy means.
    answer = window.borrow(lookback=2)
    assert answer["symbol"].to_list() == ["BTCUSDT", "ETHUSDT"]
    assert answer["borrow_rate"].to_list() == ["0.00070000", "0.00030000"]


def test_the_trailing_count_spans_symbols_not_per_symbol(window):
    # The lookback counts *rows* across the whole frame, so over a
    # per-symbol-per-poll frame it spans whole polls: the last 4 rows of six
    # (2 symbols × 3 polls) are the last two polls, both symbols — not the
    # last 4 polls of one symbol.  Slicing per symbol is the host's business,
    # at materialization; the accessor re-slices nothing.
    answer = window.borrow(lookback=4)
    assert answer["reading_time"].to_list() == [
        datetime(2026, 9, 1, 11, 59, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 11, 59, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
    ]


def test_a_lookback_larger_than_the_frame_returns_the_whole_frame(
    window, borrow_frame
):
    # Not an error, and not an empty frame: "the last 500 rows" of a 6-row
    # frame is those 6 rows.  The alternative — an out-of-range offset —
    # would make a caller's over-long lookback read as "no data".
    assert window.borrow(lookback=500).height == borrow_frame.num_rows


def test_lookback_zero_is_an_empty_frame_not_the_whole_frame(window):
    # The off-by-one worth pinning: 0 rows means 0 rows.  If this ever
    # returned everything, a caller asking for "no rows" would silently get
    # the window's whole history.
    assert window.borrow(lookback=0).height == 0


def test_a_lookback_on_an_absent_frame_is_still_empty():
    # Validation and lookup are independent: the miss stays a miss.
    assert MarketWindow(T, UNIVERSE).borrow(lookback=2).height == 0


def test_a_negative_lookback_is_refused(window):
    # Refused rather than clamped: a negative count means the caller's
    # arithmetic went wrong, and clamping would hide it behind a plausible
    # answer.  A ValueError, because it is a caller bug at the accessor.
    with pytest.raises(BorrowAccessError):
        window.borrow(lookback=-1)


def test_a_boolean_lookback_is_refused(window):
    # ``True`` is an ``int`` in Python and would silently mean "the last one
    # row" — a wrong answer that looks like a right one, which is the failure
    # mode this whole module is built against.
    with pytest.raises(BorrowAccessError):
        window.borrow(lookback=True)


def test_a_non_integer_lookback_is_refused(window):
    for bad in ("2", 2.0, [2]):
        with pytest.raises(BorrowAccessError):
            window.borrow(lookback=bad)


def test_a_malformed_request_is_reported_even_against_an_empty_window():
    # Ordering, pinned: the *question* is validated before the window is
    # consulted, so a typo against a window carrying nothing still reports the
    # typo rather than reading as "no rows for this stream".
    empty = MarketWindow(T, UNIVERSE)
    with pytest.raises(BorrowAccessError):
        empty.borrow(lookback=-1)


def test_the_refusal_is_borrows_own_not_the_feature_accessors():
    # The discipline is shared with ``feature`` (one rule for what a lookback
    # means) but the error is this accessor's: a stack trace out of
    # ``ctx.borrow(...)`` must not point the reader at ``contract.features``
    # for a rule about a different accessor.
    with pytest.raises(BorrowAccessError) as raised:
        MarketWindow(T, UNIVERSE).borrow(lookback=-1)
    assert not isinstance(raised.value, FeatureAccessError)


# --- validation core --------------------------------------------------------


def test_validate_borrow_lookback_accepts_none_and_non_negative_ints():
    assert validate_borrow_lookback(None) is None
    assert validate_borrow_lookback(0) == 0
    assert validate_borrow_lookback(7) == 7


def test_validate_borrow_lookback_refuses_everything_else():
    for bad in (-1, True, False, 1.0, "1", [1]):
        with pytest.raises(BorrowAccessError):
            validate_borrow_lookback(bad)


def test_validate_borrow_lookback_shares_the_feature_discipline():
    # One lookback discipline across every accessor: the two validators answer
    # and refuse the same domain, so ``borrow`` cannot drift from ``feature``
    # over what a lookback means.
    for value in (None, 0, 1, 10**6):
        assert validate_borrow_lookback(value) == validate_lookback(value)
    for bad in (-1, True, 1.0, "1"):
        with pytest.raises(ValueError):
            validate_borrow_lookback(bad)
        with pytest.raises(ValueError):
            validate_lookback(bad)


# --- the rows survive the payload channel (feature 14) ----------------------


def test_the_borrow_rows_travel_with_the_payload(borrow_frame):
    # The sandbox holds no filesystem and obtains its window only as Arrow IPC
    # bytes (feature 14, §5.2), and frame names are what the payload manifest
    # records.  So a window that crossed the channel still answers the borrow
    # rows — verbatim spellings included — and a rebuilt window that never
    # carried the stream still answers empty.
    window = MarketWindow(
        T, UNIVERSE, frames={BORROW_FRAME_NAME: borrow_frame}
    )
    rebuilt = window.to_arrow().materialize()
    assert rebuilt.borrow().equals(window.borrow())
    assert rebuilt.borrow()["borrow_rate"].to_list() == [
        "0.00010000",
        "0.00020000",
        "0.00010000",
        "0.00030000",
        "0.00070000",
        "0.00030000",
    ]

    empty = MarketWindow(
        T, UNIVERSE, frames={"bars": _borrow_frame(close=[1.0])}
    )
    assert empty.to_arrow().materialize().borrow().shape == (0, 0)


# --- feature 10 still holds -------------------------------------------------


def test_the_new_accessor_takes_no_timestamp_argument():
    # Feature 10's requirement, re-asserted over the surface *this* feature
    # changed: adding an accessor is exactly the edit that could have
    # reintroduced a widening parameter, and `lookback` — an amount of data,
    # not an instant — must not be flagged as one.
    assert _timestamp_param_names(MarketWindow.borrow) == ()
    assert "borrow" in inspect_accessors()
