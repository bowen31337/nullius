"""Feature 7 — ``MarketWindow.bookfeat`` returns derived order-book features.

app_spec.xml, "Signal Contract & Market Window", feature 7: *System exposes
MarketWindow.bookfeat by feature name, which returns derived order-book
features at 1 second resolution.*  docs/nullius-tech-architecture.md §5.1
declares the accessor (``bookfeat(self, name: str, lookback: int) ->
pl.DataFrame``), and §4.1 fixes the tier behind it — the *derived* half of
the L2 retention decision: raw diffs roll away after 90 days, while the
derived book features they were folded into are persisted permanently at
1s resolution.  The families §4.1 names — depth at 5/10/25/50 bps each
side, microprice, spread, OFI over several windows, cancel/replace rate,
trade-size moments — are the rows this accessor hands a signal, one row
per symbol per closed second.

That gives this suite five halves, each failing in a different direction:

* **the rows are that feature's rows** — the accessor reads one frame name,
  ``bookfeat:<name>``, exactly, and returns those rows verbatim: the derived
  tier's canonical fixed-point spellings come back as they were persisted,
  never re-rendered, and the accessor never reaches into feature 9's
  ``feature:`` namespace, feature 8's observed borrow stream, or a
  *neighbouring* feature's frame — a miss for one name is never another
  name's rows.
* **the row promise is kept, or refused** — feature 7 says *1 second
  resolution rows*, and every family in the tier shares the two columns
  that promise is checkable over: a present bookfeat frame must carry
  ``symbol`` and ``window_start``; one that does not is refused with a named
  error naming the missing columns, however much of it the caller asked
  for.  Extra columns — the ladder's bands, the reference price — pass
  through untouched.
* **a miss is empty, never a substitute** — a window carrying no frame
  under the name answers with an empty DataFrame, on the same stance
  features 8 and 9 take: an empty answer cannot leak a wrong number,
  whereas a "helpful" fallback to the nearest name silently would.
* **the lookback is the shared discipline** — ``None`` is every row, a
  non-negative int is the trailing rows counted across the whole frame (so
  over a per-symbol-per-second frame it spans whole seconds), an over-long
  count is the whole frame, ``0`` is empty, and negative / ``bool`` /
  non-int are refused — reported even against a window carrying nothing,
  so a caller bug never reads as a data gap.
* **the name is a validated component, and the encoding round-trips** —
  non-empty, unpadded, free of the separator and path separators, so
  ``bookfeat:<name>`` is injective and parseable; the parser refuses every
  foreign frame name, and the enumeration reports only the bookfeat frames
  a window carries.

Feature 10 (which this accessor must satisfy) is pinned separately in
``test_market_window_accessors.py``; the last test here re-asserts the one
thing this feature could plausibly have broken — that adding an accessor
did not add a timestamp parameter.  Feature 14's payload channel carries
the frames by name, so the rows are also pinned to survive the trip to the
sandbox.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

# pyarrow and polars are declared dependencies of the contract member, so under
# the canonical invocation (which is what the acceptance gate runs) both are
# present.  The guard keeps a partially installed environment from turning a
# missing wheel into a collection error that takes the whole repository suite
# down with it — the same idiom ``test_payload.py`` and
# ``test_market_window_borrow.py`` use.
pa = pytest.importorskip(
    "pyarrow", reason="the bookfeat-accessor suite requires pyarrow (a declared dependency)"
)
pl = pytest.importorskip(
    "polars", reason="the bookfeat-accessor suite requires polars (a declared dependency)"
)

from contract import (  # noqa: E402
    BOOKFEAT_REQUIRED_COLUMNS,
    BORROW_FRAME_NAME,
    BookfeatAccessError,
    MarketWindow,
    bookfeat_frame_name,
    bookfeat_frame_names,
    feature_frame_name,
    inspect_accessors,
    parse_bookfeat_frame_name,
)
from contract.bookfeat import (  # noqa: E402
    check_bookfeat_frame,
    select_bookfeat_frame,
    validate_bookfeat_lookback,
)
from contract.features import FeatureAccessError, validate_lookback  # noqa: E402
from contract.window import _timestamp_param_names  # noqa: E402

T = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
UNIVERSE = ("BTCUSDT", "ETHUSDT")

#: The three closed 1 second windows the fixtures carry, oldest first — two
#: symbols per second, so a lookback over the frame spans whole seconds and
#: the newest row sits exactly on the decision time's second.
SECONDS = (
    datetime(2026, 9, 1, 11, 59, 58, tzinfo=timezone.utc),
    datetime(2026, 9, 1, 11, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
)


# --- fixtures ---------------------------------------------------------------


def _frame(**columns: list) -> "pa.Table":
    return pa.table(columns)


@pytest.fixture
def depth_frame() -> "pa.Table":
    """The depth ladder over two symbols and three closed seconds.

    The shape a host materializes from the sealed snapshot's ``bookfeat/``
    partitions for the depth family (feature 20): one row per symbol per
    closed 1 second window, the reference price and the four bps bands per
    side in the derived tier's canonical fixed-point spelling — the value
    the computation produced, not a float that could drift on a re-render.
    """
    return _frame(
        symbol=["BTCUSDT", "ETHUSDT"] * 3,
        window_start=pa.array(
            [second for second in SECONDS for _ in range(2)],
            type=pa.timestamp("us", tz="UTC"),
        ),
        reference_price=["100.5000", "50.2500"] * 3,
        best_bid=["100.4900", "50.2400"] * 3,
        best_ask=["100.5100", "50.2600"] * 3,
        bid_depth_5=["12.5000", "8.0000"] * 3,
        bid_depth_10=["40.0000", "21.0000"] * 3,
        bid_depth_25=["150.0000", "90.0000"] * 3,
        bid_depth_50=["410.0000", "260.0000"] * 3,
        ask_depth_5=["11.0000", "9.5000"] * 3,
        ask_depth_10=["38.0000", "19.5000"] * 3,
        ask_depth_25=["141.0000", "88.0000"] * 3,
        ask_depth_50=["395.0000", "255.0000"] * 3,
    )


@pytest.fixture
def microprice_frame() -> "pa.Table":
    """A second family's rows — the microstructure half (feature 21)."""
    return _frame(
        symbol=["BTCUSDT", "ETHUSDT"],
        window_start=pa.array(
            [SECONDS[-1], SECONDS[-1]], type=pa.timestamp("us", tz="UTC")
        ),
        microprice=["100.5012", "50.2498"],
        spread=["0.0200", "0.0200"],
        ofi_60=["1.5000", "-0.5000"],
    )


@pytest.fixture
def window(depth_frame, microprice_frame) -> MarketWindow:
    """A window carrying two bookfeat families plus frames it must not confuse."""
    return MarketWindow(
        T,
        UNIVERSE,
        frames={
            bookfeat_frame_name("depth"): depth_frame,
            bookfeat_frame_name("microprice"): microprice_frame,
            # Feature 9's namespace: a *base* feature that happens to share a
            # name with a derived family — a different frame, in both
            # directions.
            feature_frame_name("depth", "1"): _frame(
                symbol=["BTCUSDT"], score=[9.9]
            ),
            # Feature 8's observed stream, and a frame no accessor owns.
            BORROW_FRAME_NAME: _frame(
                symbol=["BTCUSDT"], borrow_rate=["0.0001"]
            ),
            "bars": _frame(ts=[1], close=[1.0]),
        },
    )


# --- the rows are that feature's rows ----------------------------------------


def test_bookfeat_returns_the_rows_the_window_carries(window, depth_frame):
    # The positive half: the rows under the feature's own frame name come
    # back as a DataFrame of exactly those rows.
    assert window.bookfeat("depth").equals(pl.from_arrow(depth_frame))


def test_the_accessor_returns_a_polars_dataframe(window):
    # §5.1 declares ``-> pl.DataFrame``; the Arrow table the window stores is
    # an implementation detail of the transport, not the accessor's return
    # type.
    assert isinstance(window.bookfeat("depth"), pl.DataFrame)


def test_the_values_come_back_as_the_host_carried_them(window):
    # Column *types* are the host's, and the derived tier persists canonical
    # fixed-point strings — so "100.5000" must come back as that string, not
    # re-rendered into a float whose rounding an audit could not tell from
    # the computation's own.  A signal that wants floats casts them itself,
    # where the cast is visible in its own code.
    prices = window.bookfeat("depth")["reference_price"].to_list()
    assert prices[0] == "100.5000"
    assert window.bookfeat("depth").schema["reference_price"] == pl.String


def test_every_row_is_stamped_with_its_closed_second(window):
    # The resolution half of the promise, as the caller experiences it: the
    # rows carry their ``window_start`` — one closed 1 second window per row,
    # oldest first, the newest second exactly the decision time's own.  The
    # lattice is a fact about the stream the ingest tier computed; what the
    # accessor promises is that the stamp travels with the rows.
    stamps = window.bookfeat("depth")["window_start"].to_list()
    assert stamps == [second for second in SECONDS for _ in range(2)]


def test_extra_columns_pass_through_untouched(window):
    # The four bps bands per side are exactly the columns a depth consumer
    # reads, and the reference price is what a reader recomputes a band
    # against — a contract that dropped or renamed them would be forbidding
    # what it cannot promise, and quietly breaking every family's consumers.
    answer = window.bookfeat("depth")
    assert set(answer.columns) == {
        "symbol",
        "window_start",
        "reference_price",
        "best_bid",
        "best_ask",
        "bid_depth_5",
        "bid_depth_10",
        "bid_depth_25",
        "bid_depth_50",
        "ask_depth_5",
        "ask_depth_10",
        "ask_depth_25",
        "ask_depth_50",
    }
    assert answer["ask_depth_5"].to_list()[0] == "11.0000"


def test_two_families_answer_from_their_own_frames(window, microprice_frame):
    # "By feature name" selects the family: the microstructure rows come
    # from the microstructure frame, with that family's own value columns —
    # never mixed with the ladder's, though both are 1 second resolution
    # rows over the same symbols and seconds.
    answer = window.bookfeat("microprice")
    assert answer.equals(pl.from_arrow(microprice_frame))
    assert "bid_depth_5" not in answer.columns


def test_a_name_the_window_does_not_carry_is_empty_not_a_neighbours(
    window, depth_frame
):
    # The exact-match half of "by feature name": a miss for one name is
    # never another name's rows, however similar the families are.  A
    # substituted depth ladder would hand a signal depth numbers under a
    # microprice promise, which is precisely the silent wrong answer an
    # empty frame exists to avoid.
    miss = window.bookfeat("trade_flow")
    assert miss.shape == (0, 0)
    assert window.bookfeat("depth").height == depth_frame.num_rows


def test_bookfeat_does_not_read_the_feature_namespace(window):
    # A *base* feature named "depth" lives at ``feature:depth:1`` — feature
    # 9's versioned namespace, a different frame.  The bookfeat accessor
    # reads only the derived tier's own names, so the base feature's
    # ``score`` column never leaks into the ladder's rows.
    answer = window.bookfeat("depth")
    assert "score" not in answer.columns
    assert answer.height == 6


def test_feature_does_not_read_the_bookfeat_frame(window):
    # The inverse direction of the same separation: ``feature("depth", "1")``
    # answers from the versioned frame, never from the derived tier — so a
    # signal cannot be handed raw 1 second rows under an address that
    # promises one definition's output.
    answer = window.feature("depth", "1")
    assert "bid_depth_5" not in answer.columns
    assert answer["score"].to_list() == [9.9]


def test_bookfeat_does_not_read_the_borrow_stream(window):
    # Feature 8's observed stream is a frame with no separator in its name,
    # and a derived family may legally be *called* "borrow": the address is
    # ``bookfeat:borrow``, which is not the stream's.  A window carrying the
    # stream but no such family answers empty — not the stream's rates.
    assert window.bookfeat("borrow").shape == (0, 0)
    assert "borrow_rate" not in window.bookfeat("borrow").columns


def test_the_returned_frame_does_not_alias_the_windows_storage(window):
    # The conversion is zero-copy (Arrow and Polars share buffers), so the two
    # are views of the same values.  What matters is that neither side can be
    # written through: a window is immutable (feature 4), and a converted
    # Polars frame never writes back into the window's table.
    before = window.bookfeat("depth")["bid_depth_5"].to_list()
    frame = window.bookfeat("depth")
    frame = frame.with_columns(pl.lit("0").alias("bid_depth_5"))
    assert window.bookfeat("depth")["bid_depth_5"].to_list() == before


# --- the row promise is kept, or refused -------------------------------------


def test_a_frame_missing_a_required_column_is_refused():
    # Feature 7 says *1 second resolution rows*, not "a frame": a host that
    # materialized some other shape under a derived feature's name is refused
    # loudly, at the accessor, rather than handing a signal a frame whose
    # missing column surfaces as a cryptic ColumnNotFoundError three frames
    # inside the signal.
    for missing in BOOKFEAT_REQUIRED_COLUMNS:
        columns = {
            "symbol": ["BTCUSDT"],
            "window_start": pa.array(
                [SECONDS[0]], type=pa.timestamp("us", tz="UTC")
            ),
        }
        del columns[missing]
        with pytest.raises(BookfeatAccessError):
            window = MarketWindow(
                T,
                UNIVERSE,
                frames={bookfeat_frame_name("depth"): _frame(**columns)},
            )
            window.bookfeat("depth")


def test_the_refusal_names_the_missing_columns():
    # Actionable, not just loud: the error names what the contract expected,
    # so a host learns precisely which columns to materialize.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            bookfeat_frame_name("depth"): _frame(
                window_start=pa.array(
                    [SECONDS[0]], type=pa.timestamp("us", tz="UTC")
                )
            )
        },
    )
    with pytest.raises(BookfeatAccessError, match=r"symbol.*window_start"):
        window.bookfeat("depth")


def test_the_refusal_fires_whatever_the_lookback():
    # A frame that is not 1 second resolution rows is wrong as a frame, not
    # as a slice of rows: the check precedes the slicing, so even a caller
    # asking for no rows at all hears about the host's mistake.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            bookfeat_frame_name("depth"): _frame(symbol=["BTCUSDT"], mid=["1"])
        },
    )
    with pytest.raises(BookfeatAccessError):
        window.bookfeat("depth", lookback=0)
    with pytest.raises(BookfeatAccessError):
        window.bookfeat("depth")


def test_a_frame_of_only_the_required_columns_is_answerable():
    # The check is deliberately minimal — exactly the two columns every
    # family in the tier shares — so a host carrying nothing else is not
    # refused for austerity's sake.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            bookfeat_frame_name("depth"): _frame(
                symbol=["BTCUSDT"],
                window_start=pa.array(
                    [SECONDS[0]], type=pa.timestamp("us", tz="UTC")
                ),
            )
        },
    )
    assert window.bookfeat("depth")["symbol"].to_list() == ["BTCUSDT"]


def test_check_bookfeat_frame_is_the_pure_core_of_the_refusal(depth_frame):
    # The row-shape check, exercised apart from the window and the DataFrame
    # conversion: it accepts the conforming frame quietly and refuses a
    # non-conforming one by naming what is missing.
    check_bookfeat_frame(depth_frame)  # no raise
    with pytest.raises(BookfeatAccessError, match="window_start"):
        check_bookfeat_frame(_frame(symbol=["BTCUSDT"]))


def test_check_bookfeat_frame_reads_either_column_spelling(depth_frame):
    # Arrow spells it ``column_names``, polars ``columns``; the check is over
    # the row *shape*, so a host may run it while still holding a polars
    # frame — and a value with neither spelling is refused as not a frame.
    check_bookfeat_frame(pl.from_arrow(depth_frame))
    with pytest.raises(BookfeatAccessError):
        check_bookfeat_frame(object())


# --- a miss is empty, never a substitute --------------------------------------


def test_a_window_carrying_no_bookfeat_frames_answers_empty():
    # The host materialized nothing from the ``bookfeat/`` partitions (or no
    # derived stream had produced a row by ``t``): the honest answer is no
    # rows, not an exception and not a fallback to whatever frame the window
    # does carry.
    assert MarketWindow(T, UNIVERSE).bookfeat("depth").height == 0
    assert MarketWindow(
        T, UNIVERSE, frames={"bars": _frame(close=[1.0])}
    ).bookfeat("depth").height == 0


def test_a_miss_and_an_empty_read_are_distinguishable(window):
    # Two shapes of empty, on the same terms as features 8 and 9: a window
    # that carries no frame for the name yields a frame with *no columns* —
    # the window holds no schema for data it was never given — while a
    # present frame read down to nothing yields 0 rows *with* the frame's
    # columns.  So the columns say whether the feature was there at all.
    miss = MarketWindow(T, UNIVERSE).bookfeat("depth")
    empty_read = window.bookfeat("depth", lookback=0)

    assert miss.height == 0 and empty_read.height == 0
    assert miss.columns == []
    assert set(empty_read.columns) >= {"symbol", "window_start"}


def test_a_missing_feature_reports_as_a_missing_column_not_a_silent_zero():
    # The consequence of the shape above, stated as the caller experiences
    # it: asking a miss for its column raises rather than handing back
    # something that could be summed into a zero.  A "helpful" empty frame
    # with invented columns would let a signal compute on absent data and
    # produce a plausible number, which is worse than an exception at the
    # call site.
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        MarketWindow(T, UNIVERSE).bookfeat("depth")["bid_depth_5"]


# --- the lookback is the shared discipline -------------------------------------


def test_lookback_none_returns_every_row_the_window_carries(
    window, depth_frame
):
    assert window.bookfeat("depth", None).height == depth_frame.num_rows


def test_lookback_returns_the_trailing_rows(window):
    # "The last N rows" is the recent end of an oldest-first frame — the
    # seconds nearest the decision time, which is what a 1 second resolution
    # feature means.
    answer = window.bookfeat("depth", lookback=2)
    assert answer["symbol"].to_list() == ["BTCUSDT", "ETHUSDT"]
    assert answer["window_start"].to_list() == [SECONDS[-1], SECONDS[-1]]


def test_the_trailing_count_spans_symbols_not_per_symbol(window):
    # The lookback counts *rows* across the whole frame, so over a
    # per-symbol-per-second frame it spans whole seconds: the last 4 rows of
    # six (2 symbols × 3 seconds) are the last two seconds, both symbols —
    # not the last 4 seconds of one symbol.  Slicing per symbol is the
    # host's business, at materialization; the accessor re-slices nothing.
    answer = window.bookfeat("depth", lookback=4)
    assert answer["window_start"].to_list() == [
        SECONDS[-2],
        SECONDS[-2],
        SECONDS[-1],
        SECONDS[-1],
    ]


def test_a_lookback_larger_than_the_frame_returns_the_whole_frame(
    window, depth_frame
):
    # Not an error, and not an empty frame: "the last 500 rows" of a 6-row
    # frame is those 6 rows.  The alternative — an out-of-range offset —
    # would make a caller's over-long lookback read as "no data".
    assert window.bookfeat("depth", lookback=500).height == depth_frame.num_rows


def test_lookback_zero_is_an_empty_frame_not_the_whole_frame(window):
    # The off-by-one worth pinning: 0 rows means 0 rows.  If this ever
    # returned everything, a caller asking for "no rows" would silently get
    # the window's whole history.
    assert window.bookfeat("depth", lookback=0).height == 0


def test_a_lookback_on_an_absent_frame_is_still_empty():
    # Validation and lookup are independent: the miss stays a miss.
    assert MarketWindow(T, UNIVERSE).bookfeat("depth", lookback=2).height == 0


def test_a_negative_lookback_is_refused(window):
    # Refused rather than clamped: a negative count means the caller's
    # arithmetic went wrong, and clamping would hide it behind a plausible
    # answer.  A ValueError, because it is a caller bug at the accessor.
    with pytest.raises(BookfeatAccessError):
        window.bookfeat("depth", lookback=-1)


def test_a_boolean_lookback_is_refused(window):
    # ``True`` is an ``int`` in Python and would silently mean "the last one
    # row" — a wrong answer that looks like a right one, which is the failure
    # mode this whole module is built against.
    with pytest.raises(BookfeatAccessError):
        window.bookfeat("depth", lookback=True)


def test_a_non_integer_lookback_is_refused(window):
    for bad in ("2", 2.0, [2]):
        with pytest.raises(BookfeatAccessError):
            window.bookfeat("depth", lookback=bad)


def test_a_malformed_name_is_refused(window):
    # The name is a component of a frame address, so the same discipline
    # feature 9 applies to its components applies here: a name carrying the
    # separator, a path separator, padding or emptiness is a caller bug, not
    # a miss — refused rather than read as "no such feature".
    for bad in ("depth:1", "depth/1", " depth", "", 1, None):
        with pytest.raises(BookfeatAccessError):
            window.bookfeat(bad)


def test_a_malformed_request_is_reported_even_against_an_empty_window():
    # Ordering, pinned: the *question* is validated before the window is
    # consulted, so a typo against a window carrying nothing still reports
    # the typo rather than reading as "no rows for that feature".
    empty = MarketWindow(T, UNIVERSE)
    with pytest.raises(BookfeatAccessError):
        empty.bookfeat("depth", lookback=-1)
    with pytest.raises(BookfeatAccessError):
        empty.bookfeat("depth:1")


def test_the_refusal_is_bookfeats_own_not_the_feature_accessors():
    # The discipline is shared with ``feature`` and ``borrow`` (one rule for
    # what a lookback means) but the error is this accessor's: a stack trace
    # out of ``ctx.bookfeat(...)`` must not point the reader at
    # ``contract.features`` for a rule about a different accessor.
    with pytest.raises(BookfeatAccessError) as raised:
        MarketWindow(T, UNIVERSE).bookfeat("depth", lookback=-1)
    assert not isinstance(raised.value, FeatureAccessError)


# --- the name is a validated component, and the encoding round-trips ----------


def test_bookfeat_frame_name_round_trips_through_the_parser():
    # The address of a derived feature is one string, and the parser is its
    # inverse: whatever conforming name a host materialized under, the
    # enumeration reads the same name back — so "which features does this
    # window carry?" and "give me that feature's rows" cannot disagree.
    for name in ("depth", "microprice", "trade_flow", "bookfeat", "borrow"):
        assert parse_bookfeat_frame_name(bookfeat_frame_name(name)) == name


def test_a_separator_in_a_name_is_refused():
    # The load-bearing refusal: with ``:`` allowed inside a name,
    # ``bookfeat:a:1`` would be a frame name the two-part parser cannot read
    # back — a feature whose rows the accessor finds but the enumeration
    # cannot name.  Refusing the separator keeps the encoding injective and
    # the parser a total inverse.
    with pytest.raises(BookfeatAccessError):
        bookfeat_frame_name("a:1")


def test_path_separators_and_control_characters_are_refused():
    # A frame name travels into a payload manifest and, on the
    # materialisation side, toward a filesystem (§4.2's ``bookfeat/``
    # partitions), so a component that could escape its segment is not a
    # name a caller may choose — the same refusal :mod:`contract.features`
    # applies to its components.
    for bad in ("a/b", "a\\b", "a\0b", "a\nb", "a\x7fb"):
        with pytest.raises(BookfeatAccessError):
            bookfeat_frame_name(bad)


def test_a_padded_empty_or_non_string_name_is_refused():
    # Unpadded and non-empty, because a frame address a caller cannot
    # re-type is a typo waiting to read as a data gap; a non-string because
    # ``frames.get`` would silently miss it and answer "no such feature"
    # for a request that was never a name at all.
    for bad in (" depth", "depth ", "  ", 1, b"depth"):
        with pytest.raises(BookfeatAccessError):
            bookfeat_frame_name(bad)


def test_distinct_names_give_distinct_frames():
    # Injectivity, the property the separator refusal buys: two families
    # never share an address, so one family's rows cannot be read under
    # another's name.
    names = ("depth", "microstructure", "trade_flow")
    addresses = {bookfeat_frame_name(name) for name in names}
    assert len(addresses) == len(names)


def test_parse_refuses_every_foreign_frame_name():
    # Total over any value: a feature frame (three parts), the observed
    # borrow stream (no separator), a plain frame, a malformed bookfeat
    # spelling, and a non-string are all *not* bookfeat frames — reported as
    # ``None`` rather than guessed at.
    for foreign in (
        feature_frame_name("depth", "1"),
        BORROW_FRAME_NAME,
        "bars",
        "bookfeat",
        "bookfeat:",
        "bookfeat:depth:1",
        ":bookfeat",
        object(),
    ):
        assert parse_bookfeat_frame_name(foreign) is None


def test_bookfeat_frame_names_enumerates_only_bookfeat_frames(window):
    # The discoverable half of the contract: over a window carrying two
    # families plus the frames it must not confuse them with, the
    # enumeration reports exactly the two, sorted — so a caller told its
    # feature is missing can tell a typo from a gap.
    assert bookfeat_frame_names(window.frames) == ("depth", "microprice")
    assert bookfeat_frame_names({}) == ()


def test_select_bookfeat_frame_validates_before_consulting_the_mapping():
    # The lookup core refuses a malformed name before the mapping is
    # touched, so the accessor's ordering guarantee ("the question is
    # validated first") is the helper's behaviour, not an accident of where
    # the accessor calls it.
    with pytest.raises(BookfeatAccessError):
        select_bookfeat_frame({}, "depth:1")


# --- validation core -----------------------------------------------------------


def test_validate_bookfeat_lookback_accepts_none_and_non_negative_ints():
    assert validate_bookfeat_lookback(None) is None
    assert validate_bookfeat_lookback(0) == 0
    assert validate_bookfeat_lookback(7) == 7


def test_validate_bookfeat_lookback_refuses_everything_else():
    for bad in (-1, True, False, 1.0, "1", [1]):
        with pytest.raises(BookfeatAccessError):
            validate_bookfeat_lookback(bad)


def test_validate_bookfeat_lookback_shares_the_feature_discipline():
    # One lookback discipline across every accessor: the two validators
    # answer and refuse the same domain, so ``bookfeat`` cannot drift from
    # ``feature`` and ``borrow`` over what a lookback means.
    for value in (None, 0, 1, 10**6):
        assert validate_bookfeat_lookback(value) == validate_lookback(value)
    for bad in (-1, True, 1.0, "1"):
        with pytest.raises(ValueError):
            validate_bookfeat_lookback(bad)
        with pytest.raises(ValueError):
            validate_lookback(bad)


# --- the rows survive the payload channel (feature 14) -------------------------


def test_the_rows_travel_with_the_payload(depth_frame):
    # The sandbox holds no filesystem and obtains its window only as Arrow
    # IPC bytes (feature 14, §5.2), and frame names are what the payload
    # manifest records.  So a window that crossed the channel still answers
    # the named feature's rows — canonical spellings included — the
    # enumeration still names the families it carries, and a rebuilt window
    # that never carried them still answers empty.
    window = MarketWindow(
        T, UNIVERSE, frames={bookfeat_frame_name("depth"): depth_frame}
    )
    rebuilt = window.to_arrow().materialize()
    assert rebuilt.bookfeat("depth").equals(window.bookfeat("depth"))
    assert rebuilt.bookfeat("depth")["reference_price"].to_list() == [
        "100.5000",
        "50.2500",
    ] * 3
    assert bookfeat_frame_names(rebuilt.frames) == ("depth",)

    empty = MarketWindow(
        T, UNIVERSE, frames={"bars": _frame(close=[1.0])}
    )
    assert empty.to_arrow().materialize().bookfeat("depth").shape == (0, 0)


# --- feature 10 still holds ------------------------------------------------------


def test_the_new_accessor_takes_no_timestamp_argument():
    # Feature 10's requirement, re-asserted over the surface *this* feature
    # changed: adding an accessor is exactly the edit that could have
    # reintroduced a widening parameter, and `name` and `lookback` — a
    # feature and an amount of data, not instants — must not be flagged as
    # one.
    assert _timestamp_param_names(MarketWindow.bookfeat) == ()
    assert "bookfeat" in inspect_accessors()
