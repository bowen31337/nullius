"""L2 book diffs at 100 millisecond resolution, under a rolling 90 day window.

These tests are the feature statement for app_spec.xml feature 19 —
*"System ingests L2 book diffs at 100 millisecond resolution, persisting raw
diffs under a rolling 90 day retention window"* — read as behaviour of the diff
store, its retention window and the worker they stand on:

* a flush lands as the next record in an append-only log, and a prior record's
  bytes are never rewritten by a later one;
* every raw diff sits on an exact 100 millisecond lattice, and the venue's own
  price and quantity spellings are kept verbatim — this is the raw tier, so a
  re-rendered value would destroy the one thing raw data is for;
* a record that has fallen wholly outside the window is *retired* — the file is
  gone, not rewritten — while a record that still touches the window is kept
  whole, so retention never splits a batch;
* the sequence space stays monotonic across a prune and a restart, because the
  newest record is kept as the watermark anchor;
* a failed flush — a truncated frame, an empty response — is refused *before*
  anything is written, so the log never records a flush that did not happen;
* damaged bytes are refused rather than parsed into a plausible-looking book.

The module docstring in ``nullius_ingest.book_diffs`` is the design note; these
tests are the behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nullius_ingest import (
    ASKS,
    BIDS,
    BOOK_DIFFS_STREAM,
    RETENTION,
    SLICE,
    BookDiffBatch,
    BookDiffCorruptError,
    BookDiffError,
    BookDiffParseError,
    BookDiffRecord,
    BookDiffRow,
    BookDiffStore,
    BookDiffWorker,
    IngestSupervisor,
    PriceLevel,
    Side,
    StagingArea,
    StreamClass,
    align_to_window,
    parse_book_diffs,
    window_start_for,
)
from nullius_ingest.book_diffs import register_book_diff_worker
from nullius_ingest.registry import WorkerRegistry, default_worker_registry

UTC = timezone.utc

#: A flush instant; retention is decided from elapsed time, so the tests use
#: explicit instants rather than depending on when the suite runs.
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

#: ``T0`` as epoch milliseconds — the spelling a venue's event time arrives in.
T0_MS = int(T0.timestamp() * 1000)

#: The instant a prune compares against, and the instant it is run at.  A prune
#: at ``NOW`` cuts off at ``NOW - RETENTION``, so anchoring the cutoff and
#: deriving ``NOW`` from it is what keeps these fixtures honest: "before the
#: cutoff" has to mean *outside the window*, which it only does relative to the
#: cutoff the prune actually uses.
CUTOFF = T0
NOW = CUTOFF + RETENTION


def epoch_ms(moment: datetime) -> int:
    """``moment`` as epoch milliseconds — the spelling a venue's event time uses."""
    return int(moment.timestamp() * 1000)


#: The three points the window boundary turns on, read against ``CUTOFF``.  A
#: record is expired when its *newest* slice has reached the cutoff, so these
#: are a record that has left the window, one sitting on it, and one inside it.
BEFORE_CUTOFF = CUTOFF - timedelta(days=1)  # outside: its newest slice is past
ON_CUTOFF = CUTOFF  # touching: its oldest slice is exactly the cutoff
AFTER_CUTOFF = CUTOFF + timedelta(days=1)  # inside: comfortably retained


# -- Venue-shaped payloads --------------------------------------------------


def diff(
    event_time_ms: int = T0_MS,
    symbol: str = "BTCUSDT",
    first: int = 10,
    last: int = 15,
    bids: list | None = None,
    asks: list | None = None,
) -> dict:
    """One venue-shaped depth delta, spelled the way Binance's stream does."""
    return {
        "e": "depthUpdate",
        "E": event_time_ms,
        "s": symbol,
        "U": first,
        "u": last,
        "b": [["100.50", "1.000"]] if bids is None else bids,
        "a": [["101.50", "0"]] if asks is None else asks,
    }


def flush(*diffs: dict) -> dict:
    """A full delta response carrying the given diffs."""
    return {"diffs": list(diffs)}


# -- The 100 millisecond grid ------------------------------------------------


def test_events_inside_one_slice_share_a_window() -> None:
    # The feature's "100 millisecond resolution", read as the grid's behaviour:
    # several diffs inside one slice belong to one window.
    batch = parse_book_diffs(
        flush(diff(event_time_ms=T0_MS), diff(event_time_ms=T0_MS + 99))
    )

    assert batch.rows[0].window_start == batch.rows[1].window_start == T0


def test_events_one_slice_apart_are_adjacent_windows() -> None:
    batch = parse_book_diffs(
        flush(diff(event_time_ms=T0_MS), diff(event_time_ms=T0_MS + 100))
    )

    assert batch.rows[1].window_start - batch.rows[0].window_start == SLICE


def test_the_grid_slice_is_exactly_one_hundred_milliseconds() -> None:
    assert SLICE == timedelta(milliseconds=100)
    assert window_start_for(T0_MS + 100) - window_start_for(T0_MS) == SLICE


@pytest.mark.parametrize(
    "offset_ms, expected_offset_ms",
    [(0, 0), (1, 0), (99, 0), (100, 100), (101, 100), (199, 100), (200, 200)],
)
def test_the_grid_floors_exactly(offset_ms: int, expected_offset_ms: int) -> None:
    # No float enters the arithmetic, so a boundary is a boundary: 99 ms past a
    # window start is still that window, 100 ms is the next one.
    assert window_start_for(T0_MS + offset_ms) == T0 + timedelta(
        milliseconds=expected_offset_ms
    )


def test_an_unaligned_instant_floors_onto_the_grid() -> None:
    moment = datetime(2026, 3, 1, 12, 0, 0, 129_999, tzinfo=UTC)

    assert align_to_window(moment) == datetime(2026, 3, 1, 12, 0, 0, 100_000, tzinfo=UTC)


def test_an_aligned_instant_is_unchanged() -> None:
    moment = datetime(2026, 3, 1, 12, 0, 0, 100_000, tzinfo=UTC)

    assert align_to_window(moment) == moment


def test_the_grid_normalises_to_utc() -> None:
    offset = timezone(timedelta(hours=9))
    moment = datetime(2026, 3, 1, 21, 0, 0, 123_456, tzinfo=offset)

    aligned = align_to_window(moment)

    assert aligned == datetime(2026, 3, 1, 12, 0, 0, 100_000, tzinfo=UTC)
    assert aligned.tzinfo is UTC


def test_a_naive_instant_is_refused() -> None:
    # The grid is a lattice over honest instants; a naive one has no offset to
    # floor against, and assuming UTC would place a diff in a window wrong by
    # the offset.
    with pytest.raises(ValueError, match="timezone-aware"):
        align_to_window(datetime(2026, 3, 1, 12, 0, 0))


def test_a_row_floors_its_window_onto_the_grid() -> None:
    row = BookDiffRow(
        symbol="BTCUSDT",
        window_start=datetime(2026, 3, 1, 12, 0, 0, 187_500, tzinfo=UTC),
        first_update_id=1,
        last_update_id=2,
    )

    assert row.window_start == datetime(2026, 3, 1, 12, 0, 0, 100_000, tzinfo=UTC)
    assert row.window_end == datetime(2026, 3, 1, 12, 0, 0, 200_000, tzinfo=UTC)


def test_a_window_start_that_is_not_an_integer_is_refused() -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        window_start_for(T0_MS + 0.5)  # type: ignore[arg-type]


# -- Raw fidelity ------------------------------------------------------------


def test_price_and_quantity_are_kept_verbatim_in_the_venues_spelling() -> None:
    # The raw tier's whole job.  Whether the venue said "1.000" or "1" is a
    # fact about the venue, and re-rendering it would make an audit unable to
    # tell a venue change from our own lossy parse.
    batch = parse_book_diffs(flush(diff(bids=[["100.5000", "1.000"]])))
    bid = batch.rows[0].bids[0]

    assert bid.price == "100.5000"
    assert bid.quantity == "1.000"


def test_a_numeric_level_is_spelled_as_a_string() -> None:
    # Venues are inconsistent about JSON types for the same field, so scalars
    # are spelled rather than rejected.
    batch = parse_book_diffs(flush(diff(bids=[[100.5, 1.0]])))
    bid = batch.rows[0].bids[0]

    assert bid.price == repr(100.5)
    assert bid.quantity == repr(1.0)


def test_a_zero_quantity_is_kept_as_a_removal() -> None:
    # A "0" quantity is a level *removal*, and the raw tier keeps it as the
    # venue sent it: dropping it would silently delete the information that a
    # level went away.
    batch = parse_book_diffs(
        flush(diff(bids=[["100.50", "0"]], asks=[["101.50", "0"]]))
    )
    row = batch.rows[0]

    assert row.asks[0].quantity == "0"
    assert row.asks[0].is_removal is True
    assert row.is_removal_only is True


def test_a_non_zero_quantity_is_not_a_removal() -> None:
    batch = parse_book_diffs(flush(diff(bids=[["100.50", "1.000"]])))

    assert batch.rows[0].bids[0].is_removal is False
    assert batch.rows[0].is_removal_only is False


def test_the_object_level_spelling_is_accepted() -> None:
    batch = parse_book_diffs(
        flush(diff(bids=[{"price": "100.50", "quantity": "1.0"}], asks=[]))
    )

    assert batch.rows[0].bids[0].price == "100.50"
    assert batch.rows[0].bids[0].quantity == "1.0"


def test_the_qty_level_spelling_is_accepted() -> None:
    batch = parse_book_diffs(
        flush(diff(bids=[{"price": "100.50", "qty": "1.0"}], asks=[]))
    )

    assert batch.rows[0].bids[0].quantity == "1.0"


def test_sides_are_tagged_onto_their_levels() -> None:
    batch = parse_book_diffs(
        flush(diff(bids=[["100.50", "1"]], asks=[["101.50", "2"]]))
    )
    row = batch.rows[0]

    assert [l.side for l in row.bids] == [BIDS]
    assert [l.side for l in row.asks] == [ASKS]
    assert isinstance(row.bids[0].side, Side)


def test_an_absent_side_is_an_empty_side_not_a_refusal() -> None:
    # A touched-side-only diff is ordinary: a message that only changed bids
    # carries no asks, and that is not a malformed diff.
    batch = parse_book_diffs({"diffs": [{"E": T0_MS, "s": "BTCUSDT", "U": 1, "u": 2, "b": [["1", "1"]]}]})
    row = batch.rows[0]

    assert len(row.bids) == 1
    assert row.asks == ()


def test_a_single_diff_object_is_accepted() -> None:
    # A caller that flushed one diff is as legitimate as one that flushed a batch.
    batch = parse_book_diffs(diff())

    assert len(batch) == 1
    assert batch.rows[0].symbol == "BTCUSDT"


def test_a_bare_list_of_diffs_is_accepted() -> None:
    batch = parse_book_diffs([diff(), diff(symbol="ETHUSDT")])

    assert batch.symbols == ("BTCUSDT", "ETHUSDT")


def test_accepts_json_bytes_and_strings() -> None:
    import json

    body = json.dumps(flush(diff()))

    assert parse_book_diffs(body.encode()).symbols == ("BTCUSDT",)
    assert parse_book_diffs(body).symbols == ("BTCUSDT",)


def test_extra_venue_fields_are_ignored() -> None:
    # A real depthUpdate carries an event type, a transact time and a pair
    # alongside the fields this module reads; they are ignored, not refused.
    body = diff()
    body["T"] = T0_MS
    body["pair"] = "BTCUSDT"

    assert len(parse_book_diffs(flush(body))) == 1


def test_the_venue_single_letter_spellings_are_read() -> None:
    batch = parse_book_diffs([{"E": T0_MS, "s": "BTCUSDT", "U": 7, "u": 9, "b": [["1", "2"]]}])
    row = batch.rows[0]

    assert (row.symbol, row.first_update_id, row.last_update_id) == ("BTCUSDT", 7, 9)


def test_update_ids_are_persisted_as_integers_not_spellings() -> None:
    # Unlike a price, an update id is *compared* — the gap detector's whole job
    # is sequence continuity — so it is parsed to an integer rather than kept
    # as the venue's spelling.
    batch = parse_book_diffs(flush(diff(first=10, last=15)))
    row = batch.rows[0]

    assert row.first_update_id == 10
    assert row.last_update_id == 15


# -- Strictness: refused before anything is written --------------------------


def test_a_diff_with_no_event_time_is_refused() -> None:
    # Without the venue's instant the diff cannot be placed on the grid, and
    # substituting our own clock would invent a fact about when the venue saw
    # the book — a raw row whose window is a guess is worse than no row.
    with pytest.raises(BookDiffParseError, match="carries no event time"):
        parse_book_diffs({"diffs": [{"s": "BTCUSDT", "U": 1, "u": 2, "b": [["1", "1"]]}]})


def test_a_diff_without_a_symbol_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="non-empty 'symbol'"):
        parse_book_diffs({"diffs": [{"E": T0_MS, "U": 1, "u": 2}]})


def test_a_diff_without_an_update_id_range_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="no first update id"):
        parse_book_diffs({"diffs": [{"E": T0_MS, "s": "BTCUSDT", "u": 2}]})


def test_a_reversed_update_id_range_is_refused() -> None:
    # The pair is the continuity evidence feature 25's detector reads, and a
    # reversed one would make a gap appear to run backwards.
    with pytest.raises(BookDiffParseError, match="does not end before it begins"):
        parse_book_diffs(flush(diff(first=15, last=10)))


def test_a_price_listed_twice_on_one_side_is_refused() -> None:
    # Two levels for one (side, price) make "the quantity at this price"
    # ambiguous, and picking one arbitrarily is a silent choice between two
    # different books.
    with pytest.raises(BookDiffParseError, match="more than once"):
        parse_book_diffs(
            flush(diff(bids=[["100.50", "1"], ["100.50", "2"]], asks=[]))
        )


def test_the_same_price_on_opposite_sides_is_not_a_duplicate() -> None:
    batch = parse_book_diffs(
        flush(diff(bids=[["100.50", "1"]], asks=[["100.50", "2"]]))
    )

    assert len(batch.rows[0].levels) == 2


def test_a_container_level_value_is_refused() -> None:
    # Storing a nested object's repr would be a record that looks like data and
    # is not.
    with pytest.raises(BookDiffParseError, match="must be scalars"):
        parse_book_diffs(flush(diff(bids=[["100.50", {"nested": 1}]])))


def test_a_level_that_is_not_a_pair_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="a level is"):
        parse_book_diffs(flush(diff(bids=[["100.50"]])))


def test_a_level_that_is_neither_form_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="a level is"):
        parse_book_diffs(flush(diff(bids=[42])))


def test_an_object_level_without_a_price_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="no 'price' field"):
        parse_book_diffs(flush(diff(bids=[{"quantity": "1"}])))


def test_an_object_level_without_a_quantity_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="neither a 'quantity'"):
        parse_book_diffs(flush(diff(bids=[{"price": "1"}])))


def test_a_level_side_list_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="expected a list of levels"):
        parse_book_diffs(flush(diff(bids="not a list")))


def test_an_empty_flush_is_refused() -> None:
    # An empty response is a rate-limit body, a truncated frame or a reconnect
    # with nothing behind it — never a diff.  Persisting it would make a failed
    # cycle indistinguishable from a quiet one.
    with pytest.raises(BookDiffParseError, match="at least one row"):
        parse_book_diffs({"diffs": []})


def test_a_payload_with_no_diffs_list_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="no diffs list"):
        parse_book_diffs({"symbolData": []})


def test_a_payload_that_is_not_json_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="not valid JSON"):
        parse_book_diffs(b"<html>rate limited</html>")


def test_a_non_positive_event_time_is_refused() -> None:
    with pytest.raises(BookDiffParseError, match="is positive"):
        parse_book_diffs(flush(diff(event_time_ms=0)))


# -- The content hash --------------------------------------------------------


def test_the_same_book_hashes_the_same_whatever_order_it_arrives_in() -> None:
    # The content hash answers "did the book change?", so a venue that merely
    # reordered a diff has not changed a single price.
    forward = parse_book_diffs(
        flush(diff(symbol="BTCUSDT"), diff(symbol="ETHUSDT"))
    )
    reversed_ = parse_book_diffs(
        flush(diff(symbol="ETHUSDT"), diff(symbol="BTCUSDT"))
    )

    assert forward.source_sha256 == reversed_.source_sha256
    # ...while the persisted document keeps the venue's own order, because that
    # is what a human diffing two records reads.
    assert forward.symbols == ("BTCUSDT", "ETHUSDT")
    assert reversed_.symbols == ("ETHUSDT", "BTCUSDT")


def test_the_same_book_hashes_the_same_whatever_order_its_levels_arrive_in() -> None:
    forward = parse_book_diffs(flush(diff(bids=[["1", "1"], ["2", "2"]], asks=[])))
    reversed_ = parse_book_diffs(flush(diff(bids=[["2", "2"], ["1", "1"]], asks=[])))

    assert forward.source_sha256 == reversed_.source_sha256


def test_changing_one_quantity_changes_the_hash() -> None:
    before = parse_book_diffs(flush(diff(bids=[["100.50", "1.000"]])))
    after = parse_book_diffs(flush(diff(bids=[["100.50", "2.000"]])))

    assert before.source_sha256 != after.source_sha256


def test_changing_a_window_changes_the_hash() -> None:
    before = parse_book_diffs(flush(diff(event_time_ms=T0_MS)))
    after = parse_book_diffs(flush(diff(event_time_ms=T0_MS + 100)))

    assert before.source_sha256 != after.source_sha256


# -- The batch's span --------------------------------------------------------


def test_a_batch_spans_from_its_earliest_to_its_latest_window() -> None:
    batch = parse_book_diffs(
        flush(diff(event_time_ms=T0_MS), diff(event_time_ms=T0_MS + 300))
    )

    assert batch.window_start == T0
    # The span's end is one slice past the latest window, not the latest window
    # itself: retention compares this instant against the cutoff.
    assert batch.window_end == T0 + SLICE * 4
    assert batch.window_end - batch.window_start == SLICE * 4


def test_a_batch_counts_its_rows_and_levels() -> None:
    batch = parse_book_diffs(
        flush(
            diff(bids=[["1", "1"], ["2", "2"]], asks=[["3", "3"]]),
            diff(symbol="ETHUSDT", bids=[["4", "4"]], asks=[]),
        )
    )

    assert len(batch) == 2
    assert batch.level_count() == 4


def test_a_batch_deduplicates_its_symbols() -> None:
    batch = parse_book_diffs(
        flush(diff(symbol="BTCUSDT"), diff(symbol="BTCUSDT", first=50, last=60))
    )

    assert batch.symbols == ("BTCUSDT",)


def test_a_batch_selects_one_symbols_rows() -> None:
    batch = parse_book_diffs(
        flush(diff(symbol="BTCUSDT"), diff(symbol="ETHUSDT"))
    )

    assert len(batch.for_symbol("BTCUSDT")) == 1
    assert batch.for_symbol("SOLUSDT") == ()


# -- The record log ---------------------------------------------------------


def make_store(tmp_path) -> BookDiffStore:
    return BookDiffStore(StagingArea(tmp_path / "staging"))


def test_the_first_flush_lands_as_record_one(tmp_path) -> None:
    store = make_store(tmp_path)

    record = store.record(flush(diff()), written_at=T0)

    assert isinstance(record, BookDiffRecord)
    assert record.sequence == 1
    assert record.row_count == 1
    assert record.symbols == ("BTCUSDT",)
    assert record.window_start == T0
    assert record.path == tmp_path / "staging" / "bookDiffs" / "1.bin"
    assert record.path.read_bytes()  # the record is durably on disk


def test_each_flush_is_a_new_record_rather_than_an_overwrite(tmp_path) -> None:
    store = make_store(tmp_path)

    first = store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    second = store.record(
        flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE
    )

    assert (first.sequence, second.sequence) == (1, 2)
    assert first.path != second.path
    assert store.record_at(1).window_start == T0
    assert store.record_at(2).window_start == T0 + SLICE


def test_an_earlier_records_bytes_are_never_rewritten(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff()), written_at=T0)
    committed = (tmp_path / "staging" / "bookDiffs" / "1.bin").read_bytes()

    store.record(flush(diff(bids=[["999", "1"]])), written_at=T0 + SLICE)
    store.record(flush(diff(symbol="ETHUSDT")), written_at=T0 + SLICE * 2)

    assert (tmp_path / "staging" / "bookDiffs" / "1.bin").read_bytes() == committed


def test_records_are_read_back_oldest_first(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)

    records = store.records()

    assert [r.sequence for r in records] == [1, 2]
    assert records[0].written_at == T0
    assert records[1].written_at == T0 + SLICE


def test_current_and_previous_name_the_comparison_point(tmp_path) -> None:
    store = make_store(tmp_path)
    assert store.current() is None
    assert store.previous() is None

    store.record(flush(diff()), written_at=T0)
    assert store.previous() is None  # a first record has nothing behind it

    store.record(flush(diff(bids=[["100.50", "2"]])), written_at=T0 + SLICE)

    current, previous = store.current(), store.previous()
    assert current is not None and previous is not None
    assert (previous.sequence, current.sequence) == (1, 2)
    assert current.batch.rows[0].bids[0].quantity == "2"


def test_a_record_round_trips_its_raw_values(tmp_path) -> None:
    # The store must read back exactly what the venue sent — this is the raw
    # tier, and a round trip that re-rendered a price would be the one
    # corruption that matters.
    store = make_store(tmp_path)
    store.record(
        flush(diff(bids=[["100.5000", "1.000"]], asks=[["101.50", "0"]])),
        written_at=T0,
    )

    row = BookDiffStore(StagingArea(tmp_path / "staging")).records()[0].batch.rows[0]

    assert row.bids[0].price == "100.5000"
    assert row.bids[0].quantity == "1.000"
    assert row.asks[0].quantity == "0"


def test_the_log_survives_a_restart(tmp_path) -> None:
    # A fresh store over the same staging tree resumes appending past what a
    # prior run persisted — the seed-from-what-is-durable moment the resume
    # watermark gives a restarted worker.
    store = make_store(tmp_path)
    store.record(flush(diff()), written_at=T0)

    restarted = BookDiffStore(StagingArea(tmp_path / "staging"))
    second = restarted.record(flush(diff(symbol="ETHUSDT")), written_at=T0 + SLICE)

    assert second.sequence == 2
    assert [r.sequence for r in restarted.records()] == [1, 2]


def test_a_failed_parse_consumes_no_sequence(tmp_path) -> None:
    # Parse-then-write, so a truncated frame never appears in the log as a
    # flush that happened.
    store = make_store(tmp_path)

    with pytest.raises(BookDiffParseError):
        store.record({"diffs": []}, written_at=T0)

    assert store.records() == ()
    assert store.current() is None
    # And the next honest flush still claims sequence 1: no hole was left.
    assert store.record(flush(diff()), written_at=T0 + SLICE).sequence == 1


def test_a_naive_written_at_is_refused(tmp_path) -> None:
    # Retention is decided from elapsed time, so a naive timestamp is
    # unsubtractable from an aware one at exactly the boundary the rule turns on.
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.record(flush(diff()), written_at=datetime(2026, 3, 1, 12, 0))


def test_written_at_is_normalised_to_utc(tmp_path) -> None:
    store = make_store(tmp_path)
    offset = timezone(timedelta(hours=9))

    record = store.record(
        flush(diff()), written_at=datetime(2026, 3, 1, 21, 0, tzinfo=offset)
    )

    assert record.written_at == T0
    assert record.written_at.tzinfo is UTC


def test_written_at_is_kept_apart_from_the_rows_window(tmp_path) -> None:
    # Our own ingest lag must never decide which window a diff belongs to: the
    # grid comes from the venue's instant, retention from ours.
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0 + timedelta(hours=1))

    record = store.current()

    assert record.window_start == T0
    assert record.written_at == T0 + timedelta(hours=1)


# -- The reader seam the derived features stand on ---------------------------


def test_rows_in_window_unions_across_records(tmp_path) -> None:
    # A batch makes no completeness claim about a window, so the honest way to
    # ask what the book did in one is to ask the log, not to open one file.
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS, bids=[["1", "1"]], asks=[])), written_at=T0)
    store.record(
        flush(diff(event_time_ms=T0_MS + 50, bids=[["2", "2"]], asks=[])),
        written_at=T0 + SLICE,
    )

    rows = store.rows_in_window("BTCUSDT", T0)

    assert len(rows) == 2
    assert {r.bids[0].price for r in rows} == {"1", "2"}


def test_rows_in_window_accepts_any_instant_inside_the_window(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)

    # Any instant in the window names the window.
    assert len(store.rows_in_window("BTCUSDT", T0 + timedelta(milliseconds=50))) == 1
    assert len(store.rows_in_window("BTCUSDT", T0)) == 1


def test_rows_in_window_excludes_other_windows_and_symbols(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(
        flush(
            diff(event_time_ms=T0_MS),
            diff(event_time_ms=T0_MS + 100),
            diff(event_time_ms=T0_MS, symbol="ETHUSDT"),
        ),
        written_at=T0,
    )

    rows = store.rows_in_window("BTCUSDT", T0)

    assert len(rows) == 1
    assert rows[0].symbol == "BTCUSDT"
    assert rows[0].window_start == T0


def test_windows_are_the_distinct_grid_windows_retained(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(
        flush(
            diff(event_time_ms=T0_MS),
            diff(event_time_ms=T0_MS + 50),
            diff(event_time_ms=T0_MS + 100),
        ),
        written_at=T0,
    )

    assert store.windows() == (T0, T0 + SLICE)


def test_row_count_totals_the_retained_raw_diffs(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(), diff(symbol="ETHUSDT")), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)

    assert store.row_count() == 3


# -- Damage is refused, not parsed around ------------------------------------


def test_damaged_record_bytes_are_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(bids=[["100.50", "1.000"]])), written_at=T0)

    path = tmp_path / "staging" / "bookDiffs" / "1.bin"
    damaged = path.read_bytes().replace(b'"1.000"', b'"9.999"')
    assert damaged != path.read_bytes()  # the tamper actually changed bytes
    path.write_bytes(damaged)

    restarted = BookDiffStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(BookDiffCorruptError, match="not the\\s+bytes that were committed"):
        restarted.current()


def test_unreadable_record_bytes_are_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff()), written_at=T0)

    (tmp_path / "staging" / "bookDiffs" / "1.bin").write_bytes(b"not json")

    restarted = BookDiffStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(BookDiffCorruptError, match="not readable as a"):
        restarted.records()


def test_a_record_file_that_disagrees_with_its_name_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff()), written_at=T0)

    path = tmp_path / "staging" / "bookDiffs" / "1.bin"
    path.write_bytes(path.read_bytes().replace(b'"sequence":1', b'"sequence":7'))

    restarted = BookDiffStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(BookDiffCorruptError, match="does not describe itself"):
        restarted.records()


def test_reading_a_record_that_was_never_recorded_is_none(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff()), written_at=T0)

    # An honest absence, distinct from the corrupt-bytes case above: a number
    # that simply never happened is not damage.
    assert store.record_at(9) is None
    with pytest.raises(ValueError, match="must be positive"):
        store.record_at(0)


# -- The rolling 90 day window -----------------------------------------------


def test_a_record_inside_the_window_is_retained(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(
        flush(diff(event_time_ms=epoch_ms(AFTER_CUTOFF))), written_at=AFTER_CUTOFF
    )

    report = store.prune(now=NOW)

    assert report.retired == ()
    assert len(store.records()) == 1


def test_a_record_wholly_outside_the_window_is_retired(tmp_path) -> None:
    # The feature's "rolling 90 day retention window", read as the log's
    # behaviour: the file is *gone*, not rewritten.
    store = make_store(tmp_path)
    first = store.record(
        flush(diff(event_time_ms=epoch_ms(BEFORE_CUTOFF))), written_at=BEFORE_CUTOFF
    )
    # The anchor: newer and itself inside the window, so the first record is a
    # genuine retirement candidate rather than the stream's watermark.
    store.record(
        flush(diff(event_time_ms=epoch_ms(AFTER_CUTOFF))), written_at=AFTER_CUTOFF
    )

    report = store.prune(now=NOW)

    assert report.retired == (first.sequence,)
    assert report.rows_retired == 1
    assert not first.path.exists()
    assert [r.sequence for r in store.records()] == [2]


def test_the_boundary_turns_on_the_records_newest_slice(tmp_path) -> None:
    # Retention decides from the record's *newest* slice: expired when that
    # slice has reached the cutoff.  Two records straddle that rule from either
    # side, one slice apart, so this pins both the ``<=`` and the choice of
    # ``window_end`` over ``window_start``:
    #
    #   ends exactly *on* the cutoff  -> expired   (``<=``; ``<`` would retain)
    #   starts exactly *at* the cutoff -> retained (touching the window)
    #
    # With both present and an anchor newer than each, an implementation that
    # compared the wrong end, or got the boundary off by one slice, cannot
    # satisfy both assertions at once.
    store = make_store(tmp_path)
    ends_on_cutoff = store.record(
        flush(diff(event_time_ms=epoch_ms(ON_CUTOFF - SLICE))), written_at=ON_CUTOFF
    )
    starts_at_cutoff = store.record(
        flush(diff(event_time_ms=epoch_ms(ON_CUTOFF))), written_at=ON_CUTOFF
    )
    store.record(
        flush(diff(event_time_ms=epoch_ms(AFTER_CUTOFF))), written_at=AFTER_CUTOFF
    )

    report = store.prune(now=NOW)

    assert ends_on_cutoff.window_end == store.cutoff(NOW)
    assert starts_at_cutoff.window_end > store.cutoff(NOW)
    assert report.retired == (ends_on_cutoff.sequence,)
    assert [r.sequence for r in store.records()] == [
        starts_at_cutoff.sequence,
        3,
    ]


def test_a_batch_straddling_the_cutoff_is_retained_whole(tmp_path) -> None:
    # Splitting a batch would rewrite bytes and break both append-only and
    # content addressing, so retention over-keeps by at most a single record.
    # The record below genuinely spans the cutoff: one row has left the window,
    # the other is comfortably inside it.  Its *newest* slice is what decides,
    # and that is inside — so the whole batch stays, expired row and all.
    store = make_store(tmp_path)
    straddling = store.record(
        flush(
            diff(event_time_ms=epoch_ms(BEFORE_CUTOFF)),
            diff(event_time_ms=epoch_ms(AFTER_CUTOFF)),
        ),
        written_at=AFTER_CUTOFF,
    )
    # An anchor newer than the straddling record, so it is a retirement
    # candidate at all.
    store.record(
        flush(diff(event_time_ms=epoch_ms(AFTER_CUTOFF + timedelta(days=1)))),
        written_at=AFTER_CUTOFF + timedelta(days=1),
    )

    report = store.prune(now=NOW)

    # The record spans the cutoff — window_start outside, window_end inside —
    # which is exactly what makes the choice of end load-bearing here.
    assert straddling.window_start < store.cutoff(NOW) < straddling.window_end
    assert report.retired == ()
    assert straddling.path.exists()
    assert straddling.sequence in [r.sequence for r in store.records()]
    # Over-kept, not silently trimmed: the expired row is still on disk.
    assert store.rows_in_window("BTCUSDT", BEFORE_CUTOFF)


def test_prune_is_idempotent(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)
    now = T0 + RETENTION + SLICE

    first = store.prune(now=now)
    second = store.prune(now=now)

    assert first.retired == (1,)
    assert second.retired == ()
    assert second.rows_retired == 0


def test_is_expired_is_the_one_definition_of_leaving_the_window(tmp_path) -> None:
    # ``is_expired`` is the rule, and every other retention surface is a view of
    # it: ``expired_sequences``/``retained`` report it, and ``prune`` retires
    # exactly what it names.  So the rule is pinned here directly, on the three
    # records that between them make each way of getting it wrong visible:
    #
    #   wholly outside      -> expired     (an always-False rule fails here)
    #   ending on the cutoff-> expired     (a ``<`` boundary fails here)
    #   spanning the cutoff -> not expired (an always-True rule, or one that
    #                                       measured window_start, fails here)
    #
    # The third is the load-bearing one: it is the only record whose start and
    # end fall on opposite sides of the cutoff, so it is the only one that can
    # tell "newest slice" apart from "oldest slice".
    store = make_store(tmp_path)
    outside = store.record(
        flush(diff(event_time_ms=epoch_ms(BEFORE_CUTOFF))), written_at=BEFORE_CUTOFF
    )
    on_cutoff = store.record(
        flush(diff(event_time_ms=epoch_ms(ON_CUTOFF - SLICE))), written_at=ON_CUTOFF
    )
    spanning = store.record(
        flush(
            diff(event_time_ms=epoch_ms(BEFORE_CUTOFF)),
            diff(event_time_ms=epoch_ms(AFTER_CUTOFF)),
        ),
        written_at=AFTER_CUTOFF,
    )

    cutoff = store.cutoff(NOW)
    assert cutoff == CUTOFF
    assert outside.window_end <= cutoff
    assert on_cutoff.window_end == cutoff
    assert spanning.window_start < cutoff < spanning.window_end

    assert store.is_expired(outside, NOW)
    assert store.is_expired(on_cutoff, NOW)
    assert not store.is_expired(spanning, NOW)

    # And the views agree with the rule, record for record.
    assert store.expired_sequences(now=NOW) == (outside.sequence, on_cutoff.sequence)
    assert [r.sequence for r in store.retained(now=NOW)] == [spanning.sequence]


def test_expired_sequences_deletes_nothing(tmp_path) -> None:
    # The observability half: an operator can see what is due to go without
    # anything leaving the lake.
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)

    assert store.expired_sequences(now=T0 + RETENTION + SLICE) == (1,)
    assert len(store.records()) == 2  # nothing was deleted


def test_retained_reports_the_window_without_pruning(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)

    retained = store.retained(now=T0 + RETENTION + SLICE)

    assert [r.sequence for r in retained] == [2]
    assert len(store.records()) == 2  # nothing was deleted


def test_the_cutoff_is_ninety_days_before_now(tmp_path) -> None:
    store = make_store(tmp_path)
    now = T0 + timedelta(days=365)

    assert store.cutoff(now) == now - timedelta(days=90)
    assert RETENTION == timedelta(days=90)


def test_a_naive_prune_instant_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.prune(now=datetime(2026, 3, 1, 12, 0))


def test_pruning_an_empty_log_is_a_no_op(tmp_path) -> None:
    store = make_store(tmp_path)

    report = store.prune(now=T0 + RETENTION * 10)

    assert report.retired == ()
    assert report.retained_sequences == ()
    assert len(store.records()) == 0


def test_pruning_never_retires_the_newest_record(tmp_path) -> None:
    # The watermark here is derived from the files on disk, so retiring every
    # file would let the next append reuse a sequence this log has already
    # spent, and record_at(1) would start answering with a different record.
    store = make_store(tmp_path)
    only = store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)

    report = store.prune(now=T0 + RETENTION * 10)

    assert report.retired == ()
    assert store.current().sequence == only.sequence


def test_the_sequence_stays_monotonic_after_everything_expires(tmp_path) -> None:
    # A stream whose whole window has lapsed keeps its last record as the
    # anchor and keeps counting upward.
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)
    far = T0 + RETENTION * 10

    store.prune(now=far)
    store.prune(now=far)

    assert [r.sequence for r in store.records()] == [2]
    assert store.record(flush(diff(event_time_ms=T0_MS + 200)), written_at=far).sequence == 3


def test_a_backfilled_older_window_is_over_kept_rather_than_swept(tmp_path) -> None:
    # Appends are normally time-ordered, but feature 26's backfill can land an
    # older window behind a newer one.  The walk stops at the first record still
    # inside the window, so an expired record appended *behind* that stop is
    # never reached and survives the prune.
    #
    # Over-keeping is the only safe direction here: the window is a promise
    # about what has left, so the failure that matters is retiring something a
    # caller still expects, never holding something too long.  This pins the
    # behaviour so a later "optimisation" that scans the whole log — and would
    # therefore sweep the backfill — has to argue for itself.
    store = make_store(tmp_path)
    now = T0 + RETENTION * 2
    fresh = T0_MS + 91 * 86_400_000
    store.record(flush(diff(event_time_ms=fresh)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)  # the backfill
    store.record(flush(diff(event_time_ms=fresh + 86_400_000)), written_at=T0)

    report = store.prune(now=now)

    # Sequence 2 is genuinely outside the window — it would be retired in a
    # time-ordered log — but the walk stops at sequence 1 and never sees it.
    assert store.is_expired(store.record_at(2), now)
    assert report.retired == ()
    assert [r.sequence for r in store.records()] == [1, 2, 3]


def test_the_report_renders_a_line_an_operator_reads(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)

    retired = store.prune(now=T0 + RETENTION + SLICE)
    quiet = store.prune(now=T0 + RETENTION + SLICE)

    assert "retired 1 records" in retired.render()
    assert retired.retired_count == 1
    assert "nothing expired" in quiet.render()
    assert quiet.retired_count == 0


def test_a_restart_after_a_prune_resumes_past_the_retained_log(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)
    now = T0 + RETENTION + SLICE
    store.prune(now=now)

    restarted = BookDiffStore(StagingArea(tmp_path / "staging"))

    assert [r.sequence for r in restarted.records()] == [2]
    assert restarted.record(
        flush(diff(event_time_ms=T0_MS + 200)), written_at=now
    ).sequence == 3


def test_a_retired_records_read_is_none_not_an_error(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)
    store.prune(now=T0 + RETENTION + SLICE)

    # Retired is an honest absence, like a number that never happened —
    # distinct from the corrupt-bytes case, which raises.
    assert store.record_at(1) is None
    assert store.record_at(2) is not None


def test_retention_does_not_touch_another_stream(tmp_path) -> None:
    # §4.1's retention column is per-stream: the funding and exchangeInfo logs
    # are kept forever, and nothing here may retire across streams.
    from nullius_ingest import FUNDING_STREAM

    store = make_store(tmp_path)
    area = store.staging
    area.append(FUNDING_STREAM, payload=b"a funding poll", rows=1)

    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)
    store.prune(now=T0 + RETENTION + SLICE)

    assert len(area.staged(FUNDING_STREAM)) == 1


def test_records_land_where_the_seal_looks(tmp_path) -> None:
    # §4.1 puts this stream in the same append-only staging area as every other,
    # so the seal copies it into the snapshot the same way.
    store = make_store(tmp_path)
    store.record(flush(diff()), written_at=T0)

    assert store.root == tmp_path / "staging" / "bookDiffs"
    assert store.root.is_dir()
    assert store.staging.root == tmp_path / "staging"


# -- The worker --------------------------------------------------------------


def clock_at(moment: datetime):
    return lambda: moment


def test_a_cycle_persists_a_record_and_reports_its_sequence(tmp_path) -> None:
    calls = []

    def fetch() -> dict:
        calls.append(1)
        return flush(diff(), diff(symbol="ETHUSDT"))

    worker = BookDiffWorker(make_store(tmp_path), fetch, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.sequence == 1  # the record, i.e. the log's watermark
    assert result.rows_written == 2  # the raw diffs the record carries
    assert len(calls) == 1
    assert worker.stream_class is StreamClass.BOOK_DIFFS
    assert worker.store.current().sequence == 1


def test_a_cycle_rolls_the_retention_window(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)

    worker = BookDiffWorker(
        store,
        lambda: flush(diff(event_time_ms=T0_MS + 200)),
        clock=clock_at(T0 + RETENTION + SLICE),
    )
    worker.run_cycle()

    report = worker.last_retention()
    assert report is not None
    assert report.retired == (1,)
    assert not (tmp_path / "staging" / "bookDiffs" / "1.bin").exists()


def test_the_window_rolls_even_when_the_flush_fails(tmp_path) -> None:
    # Retention is a property of elapsed time, not of ingest health: a feed
    # that has been down for a week still gives back what left the window.
    store = make_store(tmp_path)
    store.record(flush(diff(event_time_ms=T0_MS)), written_at=T0)
    store.record(flush(diff(event_time_ms=T0_MS + 100)), written_at=T0 + SLICE)

    def broken_fetch() -> dict:
        raise BookDiffError("websocket dropped")

    worker = BookDiffWorker(
        store, broken_fetch, clock=clock_at(T0 + RETENTION + SLICE)
    )

    with pytest.raises(BookDiffError):
        worker.run_cycle()

    assert worker.last_retention().retired == (1,)
    assert not (tmp_path / "staging" / "bookDiffs" / "1.bin").exists()


def test_no_retention_report_before_the_first_cycle(tmp_path) -> None:
    # Distinct from a cycle that ran and expired nothing, which is a report
    # with an empty ``retired``.
    worker = BookDiffWorker(make_store(tmp_path), lambda: flush(diff()))

    assert worker.last_retention() is None


def test_a_quiet_prune_cycle_reports_an_empty_retirement(tmp_path) -> None:
    worker = BookDiffWorker(make_store(tmp_path), lambda: flush(diff()), clock=clock_at(T0))

    worker.run_cycle()

    report = worker.last_retention()
    assert report is not None and report.retired == ()


def test_a_failed_flush_leaves_the_log_untouched_and_raises(tmp_path) -> None:
    # The failure the supervisor converts into this stream's StreamFailure: the
    # worker raises, the boundary records it, no sequence is consumed.
    store = make_store(tmp_path)
    worker = BookDiffWorker(store, lambda: b"<html>429</html>", clock=clock_at(T0))

    with pytest.raises(BookDiffParseError):
        worker.run_cycle()

    assert store.records() == ()


def test_a_worker_cycle_writes_one_record_for_many_slices(tmp_path) -> None:
    # Resolution is a fact about the rows, not the file count: one cycle writes
    # one record holding however many 100 ms slices the flush carried.
    def fetch() -> dict:
        return flush(*(diff(event_time_ms=T0_MS + 100 * i) for i in range(10)))

    store = make_store(tmp_path)
    worker = BookDiffWorker(store, fetch, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.rows_written == 10
    assert result.sequence == 1
    assert len(store.records()) == 1
    assert len(store.windows()) == 10


def test_the_worker_rejects_mis_wired_collaborators(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(TypeError, match="persists into a BookDiffStore"):
        BookDiffWorker("not a store", lambda: flush(diff()))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="fetch must be a zero-argument"):
        BookDiffWorker(store, "not callable")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="clock must be a callable"):
        BookDiffWorker(store, lambda: flush(diff()), clock=7)  # type: ignore[arg-type]


def test_the_store_rejects_something_that_is_not_a_staging_area() -> None:
    with pytest.raises(TypeError, match="writes into a StagingArea"):
        BookDiffStore("not staging")  # type: ignore[arg-type]


def test_the_worker_satisfies_the_ingest_worker_protocol(tmp_path) -> None:
    from nullius_ingest import IngestWorker

    worker = BookDiffWorker(make_store(tmp_path), lambda: flush(diff()))

    assert isinstance(worker, IngestWorker)
    assert worker.stream_class is BOOK_DIFFS_STREAM


def test_the_worker_runs_under_the_supervisor(tmp_path) -> None:
    # A book-diff worker is an IngestWorker like any other: the supervisor runs
    # it on its own thread and reports its rows, so this stream composes with
    # every other rather than beside them.
    store = make_store(tmp_path)
    worker = BookDiffWorker(
        store, lambda: flush(diff(), diff(symbol="ETHUSDT")), clock=clock_at(T0)
    )

    report = IngestSupervisor([worker]).run_cycle()

    assert report.ok
    assert report.outcome_for(StreamClass.BOOK_DIFFS).rows_written == 2
    assert store.current().sequence == 1


def test_a_failed_flush_is_isolated_to_this_stream(tmp_path) -> None:
    # Feature 16's contract on this stream: a failed flush is this stream's own
    # failure and every other stream keeps ingesting.
    from nullius_ingest import FunctionWorker

    def broken_fetch() -> dict:
        raise BookDiffError("websocket dropped")

    supervisor = IngestSupervisor(
        [
            BookDiffWorker(make_store(tmp_path), broken_fetch, clock=clock_at(T0)),
            FunctionWorker(StreamClass.KLINES, lambda: 12),
        ]
    )

    report = supervisor.run_cycle()

    failure = report.outcome_for(StreamClass.BOOK_DIFFS)
    assert failure is not None and not failure.ok
    assert failure.failure.error_type == "BookDiffError"
    assert report.outcome_for(StreamClass.KLINES).rows_written == 12


# -- Registration and composition -------------------------------------------


def test_the_member_registers_a_worker_for_the_bookdiff_stream() -> None:
    # Importing the package fires the registration — the plugin convention
    # every later ingest feature follows, with no shared file edited.
    assert BOOK_DIFFS_STREAM in default_worker_registry()
    assert StreamClass.BOOK_DIFFS in default_worker_registry()


def test_the_composed_app_supervises_the_bookdiff_stream() -> None:
    from app.module_loader import create_app, Registration
    import nullius_ingest
    from pathlib import Path

    member_src = Path(nullius_ingest.__file__).resolve().parent.parent
    component = create_app(member_src, registry=Registration()).get("ingest")

    assert StreamClass.BOOK_DIFFS in component


def test_registering_an_explicit_fetch_revises_the_same_worker(tmp_path) -> None:
    # A re-registered class is a revision of the same worker, never a second
    # worker — so a deployment that wires a client does not end up with two
    # book-diff workers competing for the same sequence numbers.
    registry = WorkerRegistry()
    store = make_store(tmp_path)
    register_book_diff_worker(
        lambda: flush(diff()), store=store, clock=clock_at(T0), registry=registry
    )
    register_book_diff_worker(
        lambda: flush(diff(symbol="ETHUSDT")),
        store=store,
        clock=clock_at(T0),
        registry=registry,
    )

    assert len(registry) == 1
    worker = registry.build_workers()[0]
    assert worker.run_cycle().sequence == 1
    assert store.current().symbols == ("ETHUSDT",)


def test_registering_an_explicit_fetch_does_not_pollute_the_default(tmp_path) -> None:
    # A registration is a deployment act, not a global side effect: wiring an
    # explicit fetch must not replace the auto-discovered worker for every later
    # composition in the process.
    auto_discovered = worker_from_default(BOOK_DIFFS_STREAM)
    store = make_store(tmp_path)

    factory = register_book_diff_worker(
        lambda: flush(diff()), store=store, clock=clock_at(T0)
    )

    # The caller gets its wired worker...
    assert factory().store.staging.root == store.staging.root
    # ...while the default registry still composes the environment-resolved one,
    # untouched by the registration above.
    still_default = worker_from_default(BOOK_DIFFS_STREAM)
    assert still_default.store.staging.root == auto_discovered.store.staging.root
    assert still_default.store.staging.root != store.staging.root


def worker_from_default(stream: StreamClass):
    """The default registry's worker for ``stream``, selected by stream class.

    Selected rather than indexed: the registry builds one worker per registered
    class in sorted order, so a positional ``[0]`` would silently start naming a
    different stream the moment another member lands.
    """
    for worker in default_worker_registry().build_workers():
        if worker.stream_class == stream:
            return worker
    raise AssertionError(f"the default registry has no worker for {stream}")


def test_registering_a_non_callable_fetch_is_refused() -> None:
    with pytest.raises(TypeError, match="fetch must be a zero-argument"):
        register_book_diff_worker("nope")  # type: ignore[arg-type]


def test_an_unconfigured_fetch_is_that_streams_failure_not_a_composition_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature 16's contract: an unconfigured stream is that stream's own failure
    # in the report and every other stream keeps ingesting — not a component
    # that fails to compose.
    from nullius_ingest import FunctionWorker

    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))

    worker = worker_from_default(BOOK_DIFFS_STREAM)
    supervisor = IngestSupervisor(
        [worker, FunctionWorker(StreamClass.KLINES, lambda: 12)]
    )

    report = supervisor.run_cycle()

    failure = report.outcome_for(StreamClass.BOOK_DIFFS)
    assert failure is not None and not failure.ok
    assert failure.failure.error_type == "BookDiffError"
    assert report.outcome_for(StreamClass.KLINES).rows_written == 12


def test_the_composed_worker_reports_an_unconfigured_fetch_as_a_stream_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nullius_ingest import FunctionWorker

    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))
    worker = BookDiffWorker(
        BookDiffStore(StagingArea(tmp_path / "lake" / "staging")),
        lambda: (_ for _ in ()).throw(BookDiffError("no fetch wired")),
    )
    supervisor = IngestSupervisor(
        [worker, FunctionWorker(StreamClass.KLINES, lambda: 12)]
    )

    report = supervisor.run_cycle()

    failure = report.outcome_for(StreamClass.BOOK_DIFFS)
    assert failure is not None and not failure.ok
    assert failure.failure.error_type == "BookDiffError"
    assert report.outcome_for(StreamClass.KLINES).rows_written == 12


# -- Constants the spec names -------------------------------------------------


def test_the_declared_resolution_and_window_are_the_specs() -> None:
    assert SLICE == timedelta(milliseconds=100)
    assert RETENTION == timedelta(days=90)
    assert BOOK_DIFFS_STREAM is StreamClass.BOOK_DIFFS
    assert str(BOOK_DIFFS_STREAM) == "bookDiffs"
