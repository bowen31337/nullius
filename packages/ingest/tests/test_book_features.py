"""Derived book features at 1 second resolution, computed from the L2 diffs.

These tests are the feature statement for app_spec.xml feature 20 —
*"System computes derived book features at 1 second resolution from L2 diffs,
persisting depth at 5, 10, 25 and 50 bps per side"* — read as behaviour of the
reconstruction, the depth computation, the store and the worker they stand on:

* raw diffs are deltas, so the book is *reconstructed* — a level sets a price's
  quantity and a ``"0"`` quantity removes it — and the book is carried across
  seconds, because a snapshot is a state, not a diff;
* depth is measured off the mid, in the four 5/10/25/50 bps bands, per side, and
  the bands are nested, so a wider band never holds less than a narrower one;
* a one-sided book has no mid and emits no row — an honest absence rather than a
  defaulted feature;
* a second is emitted only when a raw diff landed in it, so the feature log is
  paced by genuine book changes, not by the worker's cycle cadence;
* the reconstructed book is *persisted* with each record, so a restart resumes
  the reconstruction from the derived log rather than re-deriving it from raw
  diffs that may since have left the 90-day window;
* the 1s grid floors exactly, with no float touching an instant;
* the derived log is append-only and permanent, landing in the same staging area
  the seal copies out of;
* damaged bytes are refused rather than reconstructed into a plausible book.

The module docstring in ``nullius_ingest.book_features`` is the design note;
these tests are the behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from nullius_ingest import (
    BPS_THRESHOLDS,
    BOOK_FEATURES_STREAM,
    FEATURE_SLICE,
    FEATURE_SLICE_MILLISECONDS,
    BookFeatureBatch,
    BookFeatureCorruptError,
    BookFeatureError,
    BookFeatureParseError,
    BookFeatureRecord,
    BookFeatureRow,
    BookFeatureStore,
    BookFeatureWorker,
    BookState,
    IngestSupervisor,
    StagingArea,
    StreamClass,
    parse_book_features,
)
from nullius_ingest.book_diffs import BookDiffStore
from nullius_ingest.book_features import register_book_feature_worker
from nullius_ingest.registry import WorkerRegistry, default_worker_registry

UTC = timezone.utc

#: A flush instant; the feature grid is decided from elapsed time, so the tests
#: use explicit instants rather than depending on when the suite runs.
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

#: ``T0`` as epoch milliseconds — the spelling a venue's event time arrives in.
T0_MS = int(T0.timestamp() * 1000)


def epoch_ms(moment: datetime) -> int:
    """``moment`` as epoch milliseconds — the spelling a venue's event time uses."""
    return int(moment.timestamp() * 1000)


# -- The 1 second grid --------------------------------------------------------


def test_the_grid_slice_is_exactly_one_second() -> None:
    assert FEATURE_SLICE == timedelta(seconds=1)
    assert FEATURE_SLICE_MILLISECONDS == 1000


def test_ten_raw_windows_fall_into_one_feature_window() -> None:
    # Feature 19's grid is 100 ms; ten of them fall into one 1s feature window.
    # The raw tier's own grid function floors the 100 ms boundaries exactly, so
    # the ten raw windows that open inside one second stay ten distinct 100 ms
    # windows; this tier's 1s floor collapses all ten of them to the same second.
    from nullius_ingest import align_to_window
    from nullius_ingest.book_features import _floor_to_second

    assert align_to_window(T0 + timedelta(milliseconds=100)) == T0 + timedelta(milliseconds=100)
    assert align_to_window(T0 + timedelta(milliseconds=900)) == T0 + timedelta(milliseconds=900)
    assert _floor_to_second(T0 + timedelta(milliseconds=100)) == _floor_to_second(
        T0 + timedelta(milliseconds=900)
    ) == T0


def test_a_second_floors_exactly() -> None:
    from nullius_ingest.book_features import _floor_to_second

    assert _floor_to_second(T0 + timedelta(milliseconds=1999)) == T0 + FEATURE_SLICE
    assert _floor_to_second(T0 + timedelta(milliseconds=2000)) == T0 + 2 * FEATURE_SLICE


def test_a_naive_instant_is_refused() -> None:
    from nullius_ingest.book_features import _floor_to_second

    with pytest.raises(ValueError, match="timezone-aware"):
        _floor_to_second(datetime(2026, 3, 1, 12, 0, 0))


# -- Venue-shaped raw diffs ---------------------------------------------------


def diff(
    event_time_ms: int = T0_MS,
    symbol: str = "BTCUSDT",
    bids: list | None = None,
    asks: list | None = None,
) -> dict:
    """One venue-shaped depth delta, spelled the way Binance's stream does."""
    return {
        "e": "depthUpdate",
        "E": event_time_ms,
        "s": symbol,
        "U": 1,
        "u": 2,
        "b": bids if bids is not None else [["100.50", "1.000"]],
        "a": asks if asks is not None else [["101.50", "1.000"]],
    }


def flush(*diffs: dict) -> dict:
    """A full delta response carrying the given diffs."""
    return {"diffs": list(diffs)}


def make_store(tmp_path) -> BookFeatureStore:
    """A store over a fresh staging area."""
    return BookFeatureStore(StagingArea(tmp_path / "staging"))


def make_diff_store(tmp_path, *batches: dict) -> BookDiffStore:
    """A raw-diff store pre-seeded with the given venue batches, in order."""
    store = BookDiffStore(StagingArea(tmp_path / "staging"))
    for batch in batches:
        store.record(batch, written_at=T0)
    return store


def clock_at(moment: datetime):
    return lambda: moment


# -- Reconstruction -----------------------------------------------------------


def test_a_level_sets_its_price_and_a_removal_deletes_it() -> None:
    # A diff sets a price's quantity; a "0" quantity removes the level.  The book
    # is a state, so after a set-then-remove the price is gone.
    state = BookState()
    state.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]], asks=[["101.50", "1"]]))
    state.apply(_row("BTCUSDT", T0, bids=[["100.50", "0"]]))

    assert state.best_bid() is None
    assert state.best_ask() == Decimal("101.50")


def _row(
    symbol: str,
    window_start: datetime,
    bids: list | None = None,
    asks: list | None = None,
):
    """A raw :class:`BookDiffRow`, the thing the book is folded from."""
    from nullius_ingest.book_diffs import BookDiffRow, PriceLevel

    def levels(pairs, side):
        return tuple(
            PriceLevel(side=side, price=p, quantity=q) for p, q in (pairs or [])
        )

    return BookDiffRow(
        symbol=symbol,
        window_start=window_start,
        first_update_id=1,
        last_update_id=2,
        levels=levels(bids, "bids") + levels(asks, "asks"),
    )


def test_a_level_set_in_one_second_is_standing_the_next() -> None:
    # The book is carried across seconds: a level set in one second and untouched
    # the next is still standing, because a snapshot is a state, not a diff.
    state = BookState()
    state.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]], asks=[["101.50", "1"]]))
    state.apply(_row("BTCUSDT", T0 + FEATURE_SLICE, bids=[["100.40", "2"]]))

    assert state.best_bid() == Decimal("100.50")
    assert state.best_ask() == Decimal("101.50")


def test_a_two_sided_book_has_a_mid() -> None:
    state = BookState()
    state.apply(_row("BTCUSDT", T0, bids=[["100.00", "1"]], asks=[["102.00", "1"]]))

    assert state.mid() == Decimal("101.00")


def test_a_one_sided_book_has_no_mid() -> None:
    # A book with an empty side has no mid: a depth measured off a guessed
    # reference would be a feature the market never had.
    state = BookState()
    state.apply(_row("BTCUSDT", T0, bids=[["100.00", "1"]]))

    assert state.mid() is None
    assert state.has_both_sides() is False


def test_the_best_level_carries_its_size_with_its_price() -> None:
    # The read seam feature 21 stands on: the microprice weights each side's
    # price by the *other* side's resting size and the best-level OFI counts the
    # change in the best level's size, so the size at the top is a fact the
    # derived tier asks for — and it is the size *at the best price*, not a sum
    # over the side.
    state = BookState()
    state.apply(
        _row(
            "BTCUSDT",
            T0,
            bids=[["100.50", "1"], ["100.40", "7"]],
            asks=[["101.50", "3"], ["101.60", "9"]],
        )
    )

    assert state.best_bid_quantity() == Decimal("1")
    assert state.best_ask_quantity() == Decimal("3")


def test_an_empty_side_has_neither_its_best_price_nor_its_size() -> None:
    # The pair describes one side: ``None`` for both or neither, so a caller can
    # never weight a price by a size the book never had.
    state = BookState()
    state.apply(_row("BTCUSDT", T0, bids=[["100.50", "1"]]))

    assert state.best_bid() == Decimal("100.50")
    assert state.best_bid_quantity() == Decimal("1")
    assert state.best_ask() is None
    assert state.best_ask_quantity() is None

    empty = BookState()
    assert empty.best_bid_quantity() is None
    assert empty.best_ask_quantity() is None


# -- Depth at bps -------------------------------------------------------------


def test_depth_counts_levels_within_a_band_off_the_mid() -> None:
    # 5 bps of a mid of 101.00 is 0.05% — so a bid at 100.99 (0.01% below) is
    # inside, and a bid at 100.90 (0.099% below) is outside.
    state = BookState()
    state.apply(
        _row(
            "BTCUSDT",
            T0,
            bids=[["100.99", "1"], ["100.90", "1"]],
            asks=[["101.01", "1"]],
        )
    )

    assert state.depth_within("bids", Decimal("101.00"), 5) == Decimal("1")
    assert state.depth_within("bids", Decimal("101.00"), 10) == Decimal("2")


def test_wider_bands_never_hold_less_than_narrower_ones() -> None:
    # The bands are nested — widening bps only ever adds levels — so a 50 bps
    # depth is never below a 25 bps one on the same side.
    state = BookState()
    state.apply(
        _row(
            "BTCUSDT",
            T0,
            bids=[["100.90", "1"], ["100.50", "1"], ["99.00", "1"]],
            asks=[["101.00", "1"]],
        )
    )

    depths = [state.depth_within("bids", Decimal("101.00"), bps) for bps in BPS_THRESHOLDS]
    assert list(depths) == sorted(depths)
    assert depths[-1] >= depths[0]


def test_an_ask_band_is_measured_above_the_mid() -> None:
    # A mid of 100.45, 5 bps up is 100.45 * 1.0005 = 100.500225 — so an ask at
    # 100.50 is inside the 5 bps band, and asks at 100.55 and 101.00 are outside.
    state = BookState()
    state.apply(
        _row(
            "BTCUSDT",
            T0,
            bids=[["100.40", "1"]],
            asks=[["100.50", "1"], ["100.55", "1"], ["101.00", "1"]],
        )
    )

    assert state.depth_within("asks", Decimal("100.45"), 5) == Decimal("1")
    assert state.depth_within("asks", Decimal("100.45"), 50) == Decimal("2")


def test_an_empty_band_is_an_exact_zero_not_a_bare_int() -> None:
    # A book whose spread is wider than the band has *nothing* inside it — the
    # normal state of a wide market, not an error.  The depth is then an exact
    # ``Decimal("0")``: a measurement ("nothing rests this close"), and the type
    # the row requires.  A bare ``sum`` over an empty generator would return
    # builtin ``int`` 0 here, which the row rightly refuses as a depth — so this
    # pins the accumulator, not just the value.
    state = BookState()
    state.apply(
        _row("BTCUSDT", T0, bids=[["100.00", "1"]], asks=[["101.00", "1"]])
    )
    # A spread of 100 bps against a mid of 100.50 puts nothing within 5 bps.
    for side in ("bids", "asks"):
        depth = state.depth_within(side, Decimal("100.50"), 5)

        assert depth == 0
        assert isinstance(depth, Decimal)
        assert not isinstance(depth, int)


def test_a_wide_book_still_produces_a_row_with_empty_bands() -> None:
    # The consequence that matters: a symbol trading wider than 10 bps — where
    # the 5 bps bands are genuinely empty — must still snapshot a row rather
    # than failing the worker.  Nothing resting close to the mid is a feature
    # value, not a reason to emit no feature.
    state = BookState()
    state.apply(
        _row("BTCUSDT", T0, bids=[["100.00", "1"]], asks=[["101.00", "1"]])
    )

    from nullius_ingest.book_features import _depth_row

    row = _depth_row("BTCUSDT", T0, state)

    assert row is not None
    assert row.bid_depth[5] == Decimal(0)
    assert row.ask_depth[5] == Decimal(0)
    assert row.bid_depth[50] == Decimal("1")  # the level is inside the wide band
    assert row.canonical()["bid_depth"]["5"] == "0"


def test_a_bad_side_is_refused() -> None:
    state = BookState()
    with pytest.raises(ValueError, match="bids.*asks"):
        state.depth_within("middle", Decimal("101.00"), 5)


# -- The feature row ----------------------------------------------------------


def test_a_row_carries_the_four_bands_per_side() -> None:
    row = _feature_row("BTCUSDT", T0, bids=[["100.90", "1"]], asks=[["101.00", "1"]])

    assert tuple(row.bid_depth) == BPS_THRESHOLDS
    assert tuple(row.ask_depth) == BPS_THRESHOLDS
    assert row.reference_price == Decimal("100.95")


def test_a_row_floors_its_window_onto_the_1s_grid() -> None:
    row = _feature_row(
        "BTCUSDT",
        T0 + timedelta(milliseconds=1999),
        bids=[["100.90", "1"]],
        asks=[["101.00", "1"]],
    )

    assert row.window_start == T0 + FEATURE_SLICE


def test_depth_values_are_canonical_strings() -> None:
    # A persisted feature is the feature value, not a float that could drift on a
    # re-render, so depths are rendered as canonical decimal strings in the
    # persisted form — while remaining Decimals in memory, where a consumer sums
    # and compares them without re-parsing.
    row = _feature_row("BTCUSDT", T0, bids=[["100.90", "1.5"]], asks=[["101.00", "2"]])

    assert row.bid_depth[5] == Decimal("1.5")
    assert isinstance(row.bid_depth[5], Decimal)
    assert row.canonical()["bid_depth"]["5"] == "1.5"


def test_a_row_with_the_wrong_band_keys_is_refused() -> None:
    with pytest.raises(BookFeatureParseError, match="exactly the thresholds"):
        BookFeatureRow(
            symbol="BTCUSDT",
            window_start=T0,
            reference_price=Decimal("101"),
            best_bid=Decimal("100"),
            best_ask=Decimal("102"),
            bid_depth={5: Decimal("1"), 10: Decimal("1")},
            ask_depth={5: Decimal("1"), 10: Decimal("1"), 25: Decimal("1"), 50: Decimal("1")},
        )


def test_a_row_with_a_negative_depth_is_refused() -> None:
    with pytest.raises(BookFeatureParseError, match="negative"):
        BookFeatureRow(
            symbol="BTCUSDT",
            window_start=T0,
            reference_price=Decimal("101"),
            best_bid=Decimal("100"),
            best_ask=Decimal("102"),
            bid_depth={bps: Decimal("-1") for bps in BPS_THRESHOLDS},
            ask_depth={bps: Decimal("1") for bps in BPS_THRESHOLDS},
        )


def test_a_row_with_a_naive_window_is_refused() -> None:
    with pytest.raises(BookFeatureParseError, match="timezone-aware"):
        BookFeatureRow(
            symbol="BTCUSDT",
            window_start=datetime(2026, 3, 1, 12, 0, 0),
            reference_price=Decimal("101"),
            best_bid=Decimal("100"),
            best_ask=Decimal("102"),
            bid_depth={bps: Decimal("1") for bps in BPS_THRESHOLDS},
            ask_depth={bps: Decimal("1") for bps in BPS_THRESHOLDS},
        )


def _feature_row(symbol, window_start, bids, asks):
    from nullius_ingest.book_features import _depth_row

    state = BookState()
    state.apply(_row(symbol, window_start, bids=bids, asks=asks))
    return _depth_row(symbol, window_start, state)


# -- The batch ----------------------------------------------------------------


def test_a_batch_hashes_canonically() -> None:
    # Two cycles producing the same features and closing book hash identically,
    # whatever order the symbols were folded in — the content hash is over the
    # features, not the fold order.
    batch_a = BookFeatureBatch(
        rows=[_feature_row("BTCUSDT", T0, [["100.90", "1"]], [["101.00", "1"]])],
        closing_books={"BTCUSDT": _state([["100.90", "1"]], [["101.00", "1"]])},
        from_window=None,
        to_window=T0,
        from_raw_sequence=0,
        to_raw_sequence=1,
    )
    batch_b = BookFeatureBatch(
        rows=[_feature_row("BTCUSDT", T0, [["100.90", "1"]], [["101.00", "1"]])],
        closing_books={"BTCUSDT": _state([["100.90", "1"]], [["101.00", "1"]])},
        from_window=None,
        to_window=T0,
        from_raw_sequence=0,
        to_raw_sequence=1,
    )

    assert batch_a.source_sha256 == batch_b.source_sha256


def test_an_empty_batch_with_no_advance_is_refused() -> None:
    # An empty cycle is not a record: a batch that neither emits a row nor
    # advances the raw frontier is refused before anything is written.
    with pytest.raises(BookFeatureParseError, match="no-progress"):
        BookFeatureBatch(
            rows=[],
            closing_books={},
            from_window=None,
            to_window=None,
            from_raw_sequence=0,
            to_raw_sequence=0,
        )


def test_a_batch_that_advances_the_frontier_without_rows_is_kept() -> None:
    # A cycle that consumes new raw records but crosses no new second still
    # persists — the book moved — so the frontier advances.
    batch = BookFeatureBatch(
        rows=[],
        closing_books={},
        from_window=None,
        to_window=None,
        from_raw_sequence=0,
        to_raw_sequence=1,
    )

    assert batch.source_sha256  # a valid, hashable batch


def _state(bids, asks):
    state = BookState()
    state.apply(_row("BTCUSDT", T0, bids=bids, asks=asks))
    return state


# -- The store: append-only, permanent ----------------------------------------


def test_a_batch_persists_as_the_next_record(tmp_path) -> None:
    store = make_store(tmp_path)
    batch = BookFeatureBatch(
        rows=[_feature_row("BTCUSDT", T0, [["100.90", "1"]], [["101.00", "1"]])],
        closing_books={"BTCUSDT": _state([["100.90", "1"]], [["101.00", "1"]])},
        from_window=None,
        to_window=T0,
        from_raw_sequence=0,
        to_raw_sequence=1,
    )

    record = store.record(batch, computed_at=T0)

    assert record.sequence == 1
    assert record.row_count == 1
    assert store.current().sequence == 1


def test_a_second_record_appends_rather_than_overwrites(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch(T0, seq=1), computed_at=T0)
    store.record(_batch(T0 + FEATURE_SLICE, seq=2), computed_at=T0 + FEATURE_SLICE)

    assert [r.sequence for r in store.records()] == [1, 2]
    assert store.records()[0].batch.rows[0].window_start == T0
    assert store.records()[1].batch.rows[0].window_start == T0 + FEATURE_SLICE


def _batch(window_start, seq):
    return BookFeatureBatch(
        rows=[_feature_row("BTCUSDT", window_start, [["100.90", "1"]], [["101.00", "1"]])],
        closing_books={"BTCUSDT": _state([["100.90", "1"]], [["101.00", "1"]])},
        from_window=None,
        to_window=window_start,
        from_raw_sequence=seq - 1,
        to_raw_sequence=seq,
    )


def test_a_record_round_trips_its_closing_book(tmp_path) -> None:
    # The closing book travels in the record and reads back as the same book, so
    # a restart can seed its reconstruction from it.
    store = make_store(tmp_path)
    record = store.record(_batch(T0, seq=1), computed_at=T0)

    book = record.closing_book("BTCUSDT")
    assert book.best_bid() == Decimal("100.90")
    assert book.best_ask() == Decimal("101.00")


def test_a_record_carries_both_hashes(tmp_path) -> None:
    store = make_store(tmp_path)
    record = store.record(_batch(T0, seq=1), computed_at=T0)

    assert record.source_sha256 == record.batch.source_sha256
    assert record.payload_sha256
    assert record.source_sha256 != record.payload_sha256


def test_records_land_where_the_seal_looks(tmp_path) -> None:
    # §4.1 puts this stream in the same append-only staging area as every other,
    # so the seal copies it into the snapshot the same way — and, like funding,
    # nothing expires it.
    store = make_store(tmp_path)
    store.record(_batch(T0, seq=1), computed_at=T0)

    assert store.root == tmp_path / "staging" / "bookFeatures"
    assert store.root.is_dir()


def test_windows_reports_the_1s_boundaries(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch(T0, seq=1), computed_at=T0)
    store.record(_batch(T0 + FEATURE_SLICE, seq=2), computed_at=T0 + FEATURE_SLICE)

    assert store.windows() == (T0, T0 + FEATURE_SLICE)


def test_rows_for_returns_a_symbols_features_at_a_window(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch(T0, seq=1), computed_at=T0)

    rows = store.rows_for("BTCUSDT", T0 + timedelta(milliseconds=500))

    assert len(rows) == 1
    assert rows[0].window_start == T0  # any instant in the window matches


# -- Corruption ---------------------------------------------------------------


def test_a_damaged_document_is_refused_on_read(tmp_path) -> None:
    # A record whose document no longer matches its recorded hash is corruption:
    # a reader that reconstructed a feature from it would be reconstructing a
    # book that never existed.  The damage is caught on a fresh read from disk —
    # the payload is captured when the store is built, so the corruption a later
    # reader must survive is exactly a restart reading bytes changed on disk.
    store = make_store(tmp_path)
    store.record(_batch(T0, seq=1), computed_at=T0)
    path = tmp_path / "staging" / "bookFeatures" / "1.bin"
    body = path.read_bytes()
    sabotaged = body.replace(b"100.90", b"999.99")
    path.write_bytes(sabotaged)

    with pytest.raises(BookFeatureCorruptError, match="source hash"):
        make_store(tmp_path).records()


def test_a_truncated_file_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(_batch(T0, seq=1), computed_at=T0)
    path = tmp_path / "staging" / "bookFeatures" / "1.bin"
    path.write_bytes(path.read_bytes()[:-20])

    with pytest.raises(BookFeatureCorruptError):
        make_store(tmp_path).records()


def test_a_mismatched_sequence_is_refused(tmp_path) -> None:
    # The envelope's recorded sequence must match the filename the file landed
    # under — a file that describes itself as a different sequence is not one
    # this store wrote.
    store = make_store(tmp_path)
    store.record(_batch(T0, seq=1), computed_at=T0)
    path = tmp_path / "staging" / "bookFeatures" / "1.bin"
    import json

    envelope = json.loads(path.read_bytes().decode())
    envelope["sequence"] = 2
    path.write_bytes(json.dumps(envelope).encode())

    with pytest.raises(BookFeatureCorruptError, match="does not describe itself"):
        make_store(tmp_path).records()


def test_a_damaged_closing_book_is_refused(tmp_path) -> None:
    # A damaged closing book would seed a restarted worker's reconstruction from
    # a book the market never had, so it is refused rather than trusted.
    store = make_store(tmp_path)
    store.record(_batch(T0, seq=1), computed_at=T0)
    path = tmp_path / "staging" / "bookFeatures" / "1.bin"
    body = path.read_bytes().decode()
    body = body.replace('"bids":', '"bidz":')
    path.write_bytes(body.encode())

    with pytest.raises(BookFeatureCorruptError):
        make_store(tmp_path).records()


# -- The worker: reconstruct, snapshot, persist -------------------------------


def test_a_cycle_reconstructs_and_persists_one_row(tmp_path) -> None:
    # The worker's whole job: read feature 19's raw diffs, reconstruct the book,
    # snapshot the depth off the mid, and persist one derived row.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.90", "1"]], asks=[["101.00", "1"]])),
    )
    worker = BookFeatureWorker(make_store(tmp_path), diffs, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.sequence == 1
    assert result.rows_written == 1
    row = worker.store.current().batch.rows[0]
    assert row.symbol == "BTCUSDT"
    assert row.window_start == T0
    assert row.reference_price == Decimal("100.95")
    assert row.bid_depth[5] == Decimal("1")
    # The depth is a Decimal in memory (a computed value, not a venue spelling),
    # and only rendered to a string in the persisted canonical form.
    assert row.canonical()["bid_depth"]["5"] == "1"


def test_a_cycle_snapshots_each_second_that_carried_a_diff(tmp_path) -> None:
    # Raw diffs at every 100 ms from T0 to T0+1s span two seconds — the 1s floor
    # puts ten of them in second T0 and one in second T0+1s — so the cycle emits
    # two 1s snapshots, one per second that carried a diff, not one per cycle.
    diffs = make_diff_store(
        tmp_path,
        flush(
            *(
                diff(event_time_ms=T0_MS + 100 * i, bids=[["100.90", "1"]], asks=[["101.00", "1"]])
                for i in range(11)
            )
        ),
    )
    worker = BookFeatureWorker(make_store(tmp_path), diffs, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.rows_written == 2
    assert worker.store.windows() == (T0, T0 + FEATURE_SLICE)


def test_a_one_sided_book_emits_no_row(tmp_path) -> None:
    # A second whose book has an empty side has no mid and emits no row — the
    # honest absence rather than a defaulted feature.  The cycle still advances
    # the raw-log frontier, so the diff is not re-folded on the next cycle; the
    # record it persists carries zero rows.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.90", "1"]], asks=[])),
    )
    worker = BookFeatureWorker(make_store(tmp_path), diffs, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.rows_written == 0
    assert result.sequence == 1
    assert worker.store.current().batch.rows == ()


def test_a_wide_spread_symbol_still_snapshots(tmp_path) -> None:
    # End to end: a symbol whose book is wider than 10 bps has genuinely empty
    # 5 bps bands, and the cycle must persist a row for it rather than failing.
    # This is the ordinary state of a thin or volatile market, and it used to
    # abort the whole cycle — the empty bands came back as builtin ``int`` 0,
    # which the row refuses as a depth.
    diffs = make_diff_store(
        tmp_path,
        # A mid of 101.10 with a 100 bps spread: nothing within 5 bps of the mid.
        flush(diff(event_time_ms=T0_MS, bids=[["100.60", "1"]], asks=[["101.60", "1"]])),
    )
    worker = BookFeatureWorker(make_store(tmp_path), diffs, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.rows_written == 1
    row = worker.store.current().batch.rows[0]
    assert row.reference_price == Decimal("101.10")
    assert row.bid_depth[5] == Decimal(0)
    assert row.ask_depth[5] == Decimal(0)
    assert row.canonical()["bid_depth"]["5"] == "0"


def test_a_second_is_emitted_only_when_a_diff_landed_in_it(tmp_path) -> None:
    # The feature log is paced by genuine book changes, not by the worker's cycle
    # cadence: a second with no diff in it is not a snapshot.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.90", "1"]], asks=[["101.00", "1"]])),
    )
    worker = BookFeatureWorker(make_store(tmp_path), diffs, clock=clock_at(T0))

    worker.run_cycle()

    assert worker.store.windows() == (T0,)


def test_a_no_new_data_cycle_persists_nothing(tmp_path) -> None:
    # A cycle that consumes no new raw records appends nothing and reports
    # sequence=0, rows_written=0 — the honest no-progress cycle.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.90", "1"]], asks=[["101.00", "1"]])),
    )
    store = make_store(tmp_path)
    worker = BookFeatureWorker(store, diffs, clock=clock_at(T0))
    worker.run_cycle()

    result = worker.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0
    assert len(store.records()) == 1


def test_a_restart_resumes_from_the_persisted_book(tmp_path) -> None:
    # The load-bearing reason the derived tier exists: raw diffs are 90-day-
    # retained and then gone, so a restart after the window has slid must rebuild
    # the book from the derived log's closing book, not from the raw store.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.90", "1"]], asks=[["101.00", "1"]])),
    )
    store = make_store(tmp_path)
    BookFeatureWorker(store, diffs, clock=clock_at(T0)).run_cycle()

    # A restarted worker, over the same stores, does not re-emit the second it
    # already emitted — it resumes past the frontier.
    restarted = BookFeatureWorker(store, diffs, clock=clock_at(T0 + FEATURE_SLICE))
    result = restarted.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0
    assert len(store.records()) == 1


def test_a_restart_reconstructs_a_level_set_before_the_window(tmp_path) -> None:
    # A level set in one record and carried into the next must survive a restart
    # that seeds from the closing book: the reconstruction resumes from state, not
    # from raw diffs.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.90", "1"]], asks=[["101.00", "1"]])),
    )
    store = make_store(tmp_path)
    BookFeatureWorker(store, diffs, clock=clock_at(T0)).run_cycle()

    # The next raw record only *touches* bids — it does not re-send the ask.  A
    # worker that seeded from an empty book would see a one-sided book here; a
    # worker that seeds from the closing book still has the ask standing.
    diffs.record(
        flush(diff(event_time_ms=T0_MS + 1000, bids=[["100.80", "3"]], asks=[])),
        written_at=T0 + FEATURE_SLICE,
    )
    restarted = BookFeatureWorker(store, diffs, clock=clock_at(T0 + FEATURE_SLICE))
    result = restarted.run_cycle()

    assert result.rows_written == 1
    row = store.current().batch.rows[0]
    assert row.best_ask == Decimal("101.00")  # carried from the closing book
    assert row.best_bid == Decimal("100.90")


def test_a_no_raw_data_cycle_persists_nothing(tmp_path) -> None:
    # An empty raw store simply yields empty cycles — there is no unconfigured-
    # fetch path, because the worker's input is the internal raw-diff store.
    diffs = make_diff_store(tmp_path)
    worker = BookFeatureWorker(make_store(tmp_path), diffs, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0


def test_the_worker_rejects_mis_wired_collaborators(tmp_path) -> None:
    diffs = make_diff_store(tmp_path)
    with pytest.raises(TypeError, match="persists into a BookFeatureStore"):
        BookFeatureWorker("not a store", diffs)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="reads from a BookDiffStore"):
        BookFeatureWorker(make_store(tmp_path), "not a diff store")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="clock must be a callable"):
        BookFeatureWorker(make_store(tmp_path), diffs, clock=7)  # type: ignore[arg-type]


def test_the_store_rejects_something_that_is_not_a_staging_area() -> None:
    with pytest.raises(TypeError, match="writes into a StagingArea"):
        BookFeatureStore("not staging")  # type: ignore[arg-type]


def test_the_worker_satisfies_the_ingest_worker_protocol(tmp_path) -> None:
    from nullius_ingest import IngestWorker

    diffs = make_diff_store(tmp_path)
    worker = BookFeatureWorker(make_store(tmp_path), diffs)

    assert isinstance(worker, IngestWorker)
    assert worker.stream_class is BOOK_FEATURES_STREAM


def test_the_worker_runs_under_the_supervisor(tmp_path) -> None:
    # A book-feature worker is an IngestWorker like any other: the supervisor
    # runs it on its own thread and reports its rows, so this stream composes
    # with every other rather than beside them.
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.90", "1"]], asks=[["101.00", "1"]])),
    )
    worker = BookFeatureWorker(make_store(tmp_path), diffs, clock=clock_at(T0))

    report = IngestSupervisor([worker]).run_cycle()

    assert report.ok
    assert report.outcome_for(StreamClass.BOOK_FEATURES).rows_written == 1
    assert worker.store.current().sequence == 1


def test_the_worker_needs_no_venue_fetch(tmp_path) -> None:
    # Unlike every earlier stream worker, this one owns no venue fetch: its input
    # is the internal raw-diff store.  There is no unconfigured-fetch path — an
    # empty raw store simply yields an empty cycle.
    diffs = make_diff_store(tmp_path)
    worker = BookFeatureWorker(make_store(tmp_path), diffs, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0


# -- Registration and composition -------------------------------------------


def test_the_member_registers_a_worker_for_the_bookfeatures_stream() -> None:
    # Importing the package fires the registration — the plugin convention every
    # later ingest feature follows, with no shared file edited.
    assert BOOK_FEATURES_STREAM in default_worker_registry()
    assert StreamClass.BOOK_FEATURES in default_worker_registry()


def test_the_composed_app_supervises_the_bookfeatures_stream() -> None:
    from app.module_loader import create_app, Registration
    import nullius_ingest
    from pathlib import Path

    member_src = Path(nullius_ingest.__file__).resolve().parent.parent
    component = create_app(member_src, registry=Registration()).get("ingest")

    assert StreamClass.BOOK_FEATURES in component


def test_registering_an_explicit_store_revises_the_same_worker(tmp_path) -> None:
    # A re-registered class is a revision of the same worker, never a second
    # worker — so a deployment that wires stores does not end up with two
    # book-feature workers competing for the same sequence numbers.
    registry = WorkerRegistry()
    store = make_store(tmp_path)
    diffs = make_diff_store(
        tmp_path,
        flush(diff(event_time_ms=T0_MS, bids=[["100.90", "1"]], asks=[["101.00", "1"]])),
    )
    register_book_feature_worker(
        store=store, diff_store=diffs, clock=clock_at(T0), registry=registry
    )
    register_book_feature_worker(
        store=store, diff_store=diffs, clock=clock_at(T0), registry=registry
    )

    assert len(registry) == 1
    worker = registry.build_workers()[0]
    assert worker.run_cycle().sequence == 1


def test_registering_an_explicit_store_does_not_pollute_the_default(tmp_path) -> None:
    # A registration is a deployment act, not a global side effect: wiring
    # explicit stores must not replace the auto-discovered worker for every later
    # composition in the process.
    auto_discovered = worker_from_default(BOOK_FEATURES_STREAM)
    store = make_store(tmp_path)

    factory = register_book_feature_worker(store=store, diff_store=make_diff_store(tmp_path))

    # The caller gets its wired worker...
    assert factory().store.staging.root == store.staging.root
    # ...while the default registry still composes the environment-resolved one,
    # untouched by the registration above.
    still_default = worker_from_default(BOOK_FEATURES_STREAM)
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


def test_registering_a_non_callable_clock_is_refused() -> None:
    with pytest.raises(TypeError, match="clock must be a callable"):
        register_book_feature_worker(clock=7)  # type: ignore[arg-type]


def test_the_composed_worker_reports_an_unconfigured_store_as_a_stream_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature 16's contract: a mis-wired stream is that stream's own failure in
    # the report and every other stream keeps ingesting — not a component that
    # fails to compose.  Here the raw-diff store points at an empty lake, so the
    # worker cycles empty rather than failing to load.
    from nullius_ingest import FunctionWorker

    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))

    worker = worker_from_default(BOOK_FEATURES_STREAM)
    supervisor = IngestSupervisor(
        [worker, FunctionWorker(StreamClass.KLINES, lambda: 12)]
    )

    report = supervisor.run_cycle()

    # An empty raw store yields an empty cycle — the stream is healthy, just
    # idle — so the feature stream is ok and the klines stream ran.
    assert report.ok
    assert report.outcome_for(StreamClass.BOOK_FEATURES).rows_written == 0
    assert report.outcome_for(StreamClass.KLINES).rows_written == 12


# -- Constants the spec names -------------------------------------------------


def test_the_declared_resolution_and_bands_are_the_specs() -> None:
    assert FEATURE_SLICE == timedelta(seconds=1)
    assert FEATURE_SLICE_MILLISECONDS == 1000
    assert BPS_THRESHOLDS == (5, 10, 25, 50)
    assert BOOK_FEATURES_STREAM is StreamClass.BOOK_FEATURES
    assert str(BOOK_FEATURES_STREAM) == "bookFeatures"
