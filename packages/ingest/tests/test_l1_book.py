"""L1 best bid/ask snapshots off the websocket feed, at 1 second resolution, retained permanently.

These tests are the feature statement for app_spec.xml feature 19 —
*"System ingests L1 best bid/ask snapshots at 1 second resolution, persisting
rows retained permanently"* — read as behaviour of the book-ticker store, the
one-cycle worker and the parser they stand on:

* a flush lands as the next record in an append-only log, and a prior record's
  bytes are never rewritten by a later one;
* each flush is persisted — the feature says *each* flush is persisted, and the
  log is the permanent history a reader reaches back across;
* the snapshots are floored onto the 1 second grid, so two quotes inside the
  same second share a window start and a reader unions by it;
* the prices and quantities are read back off the persisted record in the
  venue's own spelling, and damaged bytes are refused rather than parsed into a
  plausible-looking quote;
* a failed flush is refused *before* anything is written, so the log never
  records a flush that did not happen.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nullius_ingest import (
    L1_BOOK_STREAM,
    L1BookBatch,
    L1BookCorruptError,
    L1BookError,
    L1BookParseError,
    L1BookRecord,
    L1BookRow,
    L1BookStore,
    L1BookWorker,
    StagingArea,
    StreamClass,
    align_to_window,
    parse_l1_book,
    window_start_for,
)
from nullius_ingest.l1_book import register_l1_book_worker
from nullius_ingest.registry import WorkerRegistry, default_worker_registry

UTC = timezone.utc

#: A snapshot instant; the grid is decided from elapsed time, so the tests use
#: explicit instants rather than depending on when the suite runs.
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

#: Half a second after T0 — inside the same 1 second window, so it floors to T0.
T_PLUS_500MS = datetime(2026, 3, 1, 12, 0, 0, 500_000, tzinfo=UTC)

#: Exactly one second after T0 — the next window's start.
T_PLUS_1S = datetime(2026, 3, 1, 12, 0, 1, tzinfo=UTC)

#: Well past the first window — unambiguously a later second.
T_PLUS_5S = datetime(2026, 3, 1, 12, 0, 5, tzinfo=UTC)


def btc_snapshot(
    bid: str = "61234.50",
    ask: str = "61234.60",
    bid_qty: str = "1.200",
    ask_qty: str = "0.850",
) -> dict:
    """One venue-shaped book-ticker snapshot, the way a feed spells it."""
    return {
        "symbol": "BTCUSDT",
        "bid": bid,
        "ask": ask,
        "bidQty": bid_qty,
        "askQty": ask_qty,
        # A real bookTicker carries an update id and an order id alongside the
        # top of book; they are ignored, so a snapshot that carries them must
        # still parse.
        "updateId": 1234567890,
        "orderId": 9876543210,
    }


def eth_snapshot(
    bid: str = "3021.10",
    ask: str = "3021.20",
    bid_qty: str = "5.00",
    ask_qty: str = "4.10",
) -> dict:
    return {
        "symbol": "ETHUSDT",
        "bid": bid,
        "ask": ask,
        "bidQty": bid_qty,
        "askQty": ask_qty,
    }


def snapshot(
    symbol: str,
    bid: str,
    ask: str,
    bid_qty: str,
    ask_qty: str,
    event_time: int,
) -> dict:
    """One venue-shaped snapshot carrying an explicit event time."""
    return {
        "symbol": symbol,
        "b": bid,
        "a": ask,
        "B": bid_qty,
        "A": ask_qty,
        "E": event_time,
    }


def payload(*snapshots: dict) -> dict:
    """A full book-ticker response carrying the given snapshots, wrapped in ``bookTickers``."""
    return {"bookTickers": list(snapshots)}


def data_wrapped_payload(*snapshots: dict) -> dict:
    """The ``{"data": [...]}`` wrapper some endpoints use."""
    return {"data": list(snapshots)}


def row(
    symbol: str = "BTCUSDT",
    window_start: datetime = T0,
    bid: str = "61234.50",
    ask: str = "61234.60",
    bid_qty: str = "1.200",
    ask_qty: str = "0.850",
) -> L1BookRow:
    return L1BookRow(
        symbol=symbol,
        window_start=window_start,
        bid_price=bid,
        ask_price=ask,
        bid_quantity=bid_qty,
        ask_quantity=ask_qty,
    )


# -- The 1 second grid ------------------------------------------------------


def test_align_to_window_floors_onto_the_second() -> None:
    assert align_to_window(T0) == T0
    assert align_to_window(T_PLUS_500MS) == T0
    assert align_to_window(T_PLUS_1S) == T_PLUS_1S


def test_window_start_for_places_an_epoch_millisecond_on_the_grid() -> None:
    # 1_772_366_400_500 ms is half a second past T0, so it floors to T0.
    assert window_start_for(1_772_366_400_500) == T0
    # 1_772_366_401_000 ms is exactly the next second.
    assert window_start_for(1_772_366_401_000) == T_PLUS_1S


def test_window_start_for_refuses_a_non_integer() -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        window_start_for(1_772_366_400.5)  # type: ignore[arg-type]


def test_align_to_window_refuses_a_naive_instant() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        align_to_window(datetime(2026, 3, 1, 12, 0, 0))


# -- Parsing the venue's document -------------------------------------------


def test_parses_the_quotes_of_every_snapshot() -> None:
    batch = parse_l1_book(payload(btc_snapshot(), eth_snapshot()))

    assert [r.symbol for r in batch.rows] == ["BTCUSDT", "ETHUSDT"]
    assert batch.rows[0].bid_price == "61234.50"
    assert batch.rows[0].ask_price == "61234.60"
    assert batch.rows[0].bid_quantity == "1.200"
    assert batch.rows[0].ask_quantity == "0.850"


def test_prices_and_quantities_are_kept_verbatim_in_the_venues_spelling() -> None:
    # Whether the venue said "61234.50" or "61234.5" is a fact about the venue,
    # and the raw series keeps it rather than re-rendering it.
    batch = parse_l1_book(payload(btc_snapshot(bid="61234.500", ask_qty="0.8")))

    assert batch.rows[0].bid_price == "61234.500"
    assert batch.rows[0].ask_quantity == "0.8"


def test_a_numeric_price_is_spelled_as_a_string() -> None:
    batch = parse_l1_book(payload(btc_snapshot(bid=61234.5, ask_qty=0.85)))

    assert batch.rows[0].bid_price == "61234.5"
    assert batch.rows[0].ask_quantity == "0.85"


def test_a_snapshot_with_extra_fields_parses() -> None:
    # A real bookTicker carries an updateId and orderId alongside the top of
    # book; they are ignored, so a snapshot that carries them must still parse.
    batch = parse_l1_book(payload(btc_snapshot()))

    assert batch.rows[0].symbol == "BTCUSDT"


def test_a_snapshot_is_placed_on_the_grid_by_its_event_time() -> None:
    # An event time half a second into the window floors the whole snapshot to
    # the window's start.
    batch = parse_l1_book(
        payload(snapshot("BTCUSDT", "61234.50", "61234.60", "1.0", "1.0", 1_772_366_400_500))
    )

    assert batch.rows[0].window_start == T0


def test_accepts_a_bare_list_of_snapshots() -> None:
    batch = parse_l1_book([btc_snapshot(), eth_snapshot()])

    assert [r.symbol for r in batch.rows] == ["BTCUSDT", "ETHUSDT"]


def test_accepts_the_wrapped_response_some_endpoints_use() -> None:
    batch = parse_l1_book(data_wrapped_payload(btc_snapshot()))

    assert [r.symbol for r in batch.rows] == ["BTCUSDT"]


def test_accepts_a_single_symbol_response() -> None:
    batch = parse_l1_book(btc_snapshot())

    assert [r.symbol for r in batch.rows] == ["BTCUSDT"]


def test_accepts_json_bytes() -> None:
    import json

    batch = parse_l1_book(json.dumps(payload(btc_snapshot())).encode("utf-8"))

    assert [r.symbol for r in batch.rows] == ["BTCUSDT"]


def test_an_empty_response_is_refused() -> None:
    with pytest.raises(L1BookParseError, match="at least one row"):
        parse_l1_book(payload())


def test_a_snapshot_without_a_symbol_is_refused() -> None:
    snap = btc_snapshot()
    del snap["symbol"]
    with pytest.raises(L1BookParseError, match="symbol"):
        parse_l1_book(payload(snap))


def test_a_snapshot_without_a_bid_is_refused() -> None:
    snap = btc_snapshot()
    del snap["bid"]
    with pytest.raises(L1BookParseError, match="no bid"):
        parse_l1_book(payload(snap))


def test_a_snapshot_without_an_ask_is_refused() -> None:
    snap = btc_snapshot()
    del snap["ask"]
    with pytest.raises(L1BookParseError, match="no ask"):
        parse_l1_book(payload(snap))


def test_a_snapshot_without_a_bid_quantity_is_refused() -> None:
    snap = btc_snapshot()
    del snap["bidQty"]
    with pytest.raises(L1BookParseError, match="no bid quantity"):
        parse_l1_book(payload(snap))


def test_a_snapshot_without_an_ask_quantity_is_refused() -> None:
    snap = btc_snapshot()
    del snap["askQty"]
    with pytest.raises(L1BookParseError, match="no ask quantity"):
        parse_l1_book(payload(snap))


def test_a_snapshot_without_an_event_time_is_refused() -> None:
    snap = btc_snapshot()
    del snap["E"]
    with pytest.raises(L1BookParseError, match="no event time"):
        parse_l1_book(payload(snap))


def test_a_payload_that_is_not_json_is_refused() -> None:
    with pytest.raises(L1BookParseError, match="not valid JSON"):
        parse_l1_book(b"{not json")


# -- The content hash: same quotes hash the same ----------------------------


def test_same_quotes_hash_the_same_whatever_order_they_arrive_in() -> None:
    forward = parse_l1_book(payload(btc_snapshot(), eth_snapshot()))
    reversed_ = parse_l1_book(payload(eth_snapshot(), btc_snapshot()))

    assert forward.source_sha256 == reversed_.source_sha256


def test_changing_one_quote_changes_the_hash() -> None:
    unchanged = parse_l1_book(payload(btc_snapshot()))
    changed = parse_l1_book(payload(btc_snapshot(bid="61234.51")))

    assert unchanged.source_sha256 != changed.source_sha256


# -- The store: append-only, permanent --------------------------------------


def make_store(tmp_path) -> L1BookStore:
    return L1BookStore(StagingArea(tmp_path / "staging"))


def test_the_first_flush_lands_as_record_one(tmp_path) -> None:
    store = make_store(tmp_path)

    record = store.record(payload(btc_snapshot(), eth_snapshot()), written_at=T0)

    assert isinstance(record, L1BookRecord)
    assert record.sequence == 1
    assert record.row_count == 2
    assert record.symbols == ("BTCUSDT", "ETHUSDT")
    assert record.path == tmp_path / "staging" / "bookTicker" / "1.bin"
    assert record.path.read_bytes()  # the record is durably on disk


def test_each_flush_is_a_new_record_rather_than_an_overwrite(tmp_path) -> None:
    # The feature statement, read as the log's behaviour: each flush's rows are
    # retained permanently, one record after another.
    store = make_store(tmp_path)

    first = store.record(payload(btc_snapshot(bid="61234.50")), written_at=T0)
    second = store.record(payload(btc_snapshot(bid="61234.51")), written_at=T_PLUS_1S)

    assert (first.sequence, second.sequence) == (1, 2)
    assert first.path != second.path
    # Record 1's bytes are untouched by record 2's arrival: the log is a
    # permanent history, not a slot.
    assert store.record_at(1) is not None
    assert store.record_at(1).batch.rows[0].bid_price == "61234.50"
    assert store.record_at(2).batch.rows[0].bid_price == "61234.51"


def test_an_earlier_records_bytes_are_never_rewritten(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_snapshot()), written_at=T0)
    committed = (tmp_path / "staging" / "bookTicker" / "1.bin").read_bytes()

    store.record(payload(btc_snapshot(bid="99999.99")), written_at=T_PLUS_1S)
    store.record(payload(eth_snapshot()), written_at=T_PLUS_5S)

    assert (tmp_path / "staging" / "bookTicker" / "1.bin").read_bytes() == committed


def test_records_are_read_back_oldest_first(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_snapshot()), written_at=T0)
    store.record(payload(eth_snapshot()), written_at=T_PLUS_1S)

    records = store.records()

    assert [r.sequence for r in records] == [1, 2]
    assert records[0].written_at == T0
    assert records[1].written_at == T_PLUS_1S


def test_current_and_previous_name_the_comparison_point(tmp_path) -> None:
    store = make_store(tmp_path)
    assert store.current() is None  # nothing flushed yet — no quote to offer
    assert store.previous() is None

    store.record(payload(btc_snapshot()), written_at=T0)
    assert store.previous() is None  # a first record has nothing behind it

    store.record(payload(btc_snapshot(bid="61234.51")), written_at=T_PLUS_1S)

    current, previous = store.current(), store.previous()
    assert current is not None and previous is not None
    assert (previous.sequence, current.sequence) == (1, 2)
    assert current.batch.rows[0].bid_price == "61234.51"


def test_the_log_survives_a_restart(tmp_path) -> None:
    # A fresh store over the same staging tree resumes appending past what a
    # prior run persisted — the seed-from-what-is-durable moment the resume
    # watermark gives a restarted worker, applied to the L1 log.
    store = make_store(tmp_path)
    store.record(payload(btc_snapshot()), written_at=T0)

    restarted = L1BookStore(StagingArea(tmp_path / "staging"))
    second = restarted.record(payload(eth_snapshot()), written_at=T_PLUS_1S)

    assert second.sequence == 2
    assert [r.sequence for r in restarted.records()] == [1, 2]


def test_a_failed_parse_consumes_no_sequence(tmp_path) -> None:
    # Parse-then-write, so a rate-limit body never appears in the log as a flush
    # that happened.
    store = make_store(tmp_path)

    with pytest.raises(L1BookParseError):
        store.record({"snapshotData": []}, written_at=T0)

    assert store.records() == ()
    assert store.current() is None
    # And the next honest flush still claims sequence 1: no hole was left.
    assert store.record(payload(btc_snapshot()), written_at=T_PLUS_1S).sequence == 1


def test_a_naive_written_at_is_refused(tmp_path) -> None:
    # written_at is a fact about elapsed wall-clock time, so a naive timestamp
    # is unsubtractable from an aware one at exactly the boundary the record's
    # place in the write history turns on.
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.record(payload(btc_snapshot()), written_at=datetime(2026, 3, 1, 12, 0))


def test_written_at_is_normalised_to_utc(tmp_path) -> None:
    store = make_store(tmp_path)
    offset = timezone(timedelta(hours=9))

    record = store.record(
        payload(btc_snapshot()), written_at=datetime(2026, 3, 1, 21, 0, tzinfo=offset)
    )

    assert record.written_at == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    assert record.written_at.tzinfo is UTC


def test_a_record_exposes_the_span_of_window_starts_it_covers(tmp_path) -> None:
    store = make_store(tmp_path)
    record = store.record(payload(btc_snapshot(), eth_snapshot()), written_at=T0)

    assert record.first_time == T0
    assert record.last_time == T0


# -- Corruption: damaged bytes are refused ----------------------------------


def test_damaged_record_bytes_are_refused(tmp_path) -> None:
    # A log a reader trusts for the market's top of book must not hand back a
    # plausible-looking quote assembled from bytes that changed.
    store = make_store(tmp_path)
    store.record(payload(btc_snapshot()), written_at=T0)

    path = tmp_path / "staging" / "bookTicker" / "1.bin"
    tampered = path.read_bytes().replace(b'"61234.60"', b'"99999.99"')
    assert tampered != path.read_bytes()  # the tamper actually changed bytes
    path.write_bytes(tampered)

    restarted = L1BookStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(L1BookCorruptError, match="not the bytes that were committed"):
        restarted.current()


def test_unreadable_record_bytes_are_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_snapshot()), written_at=T0)

    (tmp_path / "staging" / "bookTicker" / "1.bin").write_bytes(b"not json")

    restarted = L1BookStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(L1BookCorruptError, match="not readable as a"):
        restarted.records()


def test_a_record_file_that_disagrees_with_its_name_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_snapshot()), written_at=T0)

    path = tmp_path / "staging" / "bookTicker" / "1.bin"
    path.write_bytes(path.read_bytes().replace(b'"sequence":1', b'"sequence":7'))

    restarted = L1BookStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(L1BookCorruptError, match="does not describe itself"):
        restarted.records()


def test_reading_a_record_that_was_never_recorded_is_none(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_snapshot()), written_at=T0)

    # An honest absence, distinct from the corrupt-bytes case above: a number
    # that simply never happened is not damage.
    assert store.record_at(9) is None
    with pytest.raises(ValueError, match="must be positive"):
        store.record_at(0)


# -- The worker: flush each cycle, persist ----------------------------------


def clock_at(moment: datetime):
    return lambda: moment


def test_a_cycle_persists_a_record_and_reports_its_sequence(tmp_path) -> None:
    calls = []

    def fetch() -> dict:
        calls.append(1)
        return payload(btc_snapshot(), eth_snapshot())

    worker = L1BookWorker(make_store(tmp_path), fetch, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.sequence == 1  # the record, i.e. the log's watermark
    assert result.rows_written == 2  # the snapshots the record carries
    assert len(calls) == 1
    assert worker.stream_class is StreamClass.L1_BOOK
    assert worker.store.current().sequence == 1


def test_a_quiet_cycle_polls_nothing_and_claims_no_progress(tmp_path) -> None:
    # A feed that delivered no snapshot this slice is a successful zero-row
    # cycle, not a failure: a liquid book ticks continuously but a quiet one can
    # legitimately go a cycle without a quote.
    store = make_store(tmp_path)

    def fetch():
        return None

    worker = L1BookWorker(store, fetch, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0
    assert len(store.records()) == 0  # nothing was written


def test_a_failed_flush_leaves_the_log_untouched_and_raises(tmp_path) -> None:
    # The failure the supervisor converts into this stream's StreamFailure: the
    # worker raises, the boundary records it, no sequence is consumed.
    store = make_store(tmp_path)
    worker = L1BookWorker(store, lambda: b"<html>429</html>", clock=clock_at(T0))

    with pytest.raises(L1BookParseError):
        worker.run_cycle()

    assert store.records() == ()


def test_the_worker_rejects_mis_wired_collaborators(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(TypeError, match="persists into an L1BookStore"):
        L1BookWorker("not a store", lambda: payload(btc_snapshot()))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="fetch must be a zero-argument"):
        L1BookWorker(store, "not callable")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="clock must be a callable"):
        L1BookWorker(store, lambda: payload(btc_snapshot()), clock=7)  # type: ignore[arg-type]


def test_the_store_rejects_something_that_is_not_a_staging_area() -> None:
    with pytest.raises(TypeError, match="writes into a StagingArea"):
        L1BookStore("not staging")  # type: ignore[arg-type]


# -- Registration and composition -------------------------------------------


def test_the_member_registers_a_worker_for_the_book_ticker_stream() -> None:
    # Importing the package fires the registration — the plugin convention
    # every later ingest feature follows, with no shared file edited.
    assert L1_BOOK_STREAM in default_worker_registry()
    assert StreamClass.L1_BOOK in default_worker_registry()


def test_registering_an_explicit_fetch_revises_the_same_worker(tmp_path) -> None:
    # A re-registered class is a revision of the same worker, never a second
    # worker — so a deployment that wires a client does not end up with two L1
    # book workers competing for the same sequence numbers.
    registry = WorkerRegistry()
    store = make_store(tmp_path)
    register_l1_book_worker(
        lambda: payload(btc_snapshot()),
        store=store,
        clock=clock_at(T0),
        registry=registry,
    )
    # Registering the same class again replaces the factory in place.
    register_l1_book_worker(
        lambda: payload(eth_snapshot()),
        store=store,
        clock=clock_at(T0),
        registry=registry,
    )

    assert len(registry) == 1
    worker = registry.build_workers()[0]
    assert worker.run_cycle().sequence == 1
    assert store.current().symbols == ("ETHUSDT",)


def l1_book_worker_from_default() -> L1BookWorker:
    """The default registry's L1 book worker, selected by stream class.

    Selected rather than indexed: the registry builds one worker per registered
    class in sorted order, so a positional ``[0]`` silently starts naming a
    different stream the moment another ingest member lands.
    """
    for worker in default_worker_registry().build_workers():
        if worker.stream_class == L1_BOOK_STREAM:
            return worker
    raise AssertionError("the default registry has no L1 book worker")


def test_registering_an_explicit_fetch_does_not_pollute_the_default(tmp_path) -> None:
    # A registration is a deployment act, not a global side effect: wiring an
    # explicit fetch must not replace the auto-discovered worker for every later
    # composition in the process — which is exactly how a test would be handed a
    # worker bound to a store that has since been deleted.
    auto_discovered = l1_book_worker_from_default()
    store = make_store(tmp_path)

    factory = register_l1_book_worker(
        lambda: payload(btc_snapshot()), store=store, clock=clock_at(T0)
    )

    # The caller gets its wired worker...
    assert factory().store.staging.root == store.staging.root
    # ...while the default registry still composes the environment-resolved one,
    # untouched by the registration above.
    still_default = l1_book_worker_from_default()
    assert still_default.store.staging.root == auto_discovered.store.staging.root
    assert still_default.store.staging.root != store.staging.root


def test_registering_a_non_callable_fetch_is_refused() -> None:
    with pytest.raises(TypeError, match="fetch must be a zero-argument"):
        register_l1_book_worker("nope")  # type: ignore[arg-type]


def test_the_composed_worker_reports_an_unconfigured_fetch_as_a_stream_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature 16's contract: an unconfigured stream is that stream's own failure
    # in the report and every other stream keeps ingesting — not a component
    # that fails to compose.
    from nullius_ingest import FunctionWorker, IngestSupervisor

    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))
    worker = L1BookWorker(
        L1BookStore(StagingArea(tmp_path / "lake" / "staging")),
        lambda: (_ for _ in ()).throw(L1BookError("no fetch wired")),
    )
    supervisor = IngestSupervisor(
        [worker, FunctionWorker(StreamClass.KLINES, lambda: 12)]
    )

    report = supervisor.run_cycle()

    failure = report.outcome_for(StreamClass.L1_BOOK)
    assert failure is not None and not failure.ok
    assert failure.failure.error_type == "L1BookError"
    assert report.outcome_for(StreamClass.KLINES).rows_written == 12


def test_records_land_where_the_seal_looks(tmp_path) -> None:
    # The stream's staging log is what a seal copies into its snapshot, so the
    # permanent history becomes part of the sealed record rather than a sidecar
    # a replay would have to reconstruct from live requests.
    store = make_store(tmp_path)
    store.record(payload(btc_snapshot()), written_at=T0)

    assert store.root == tmp_path / "staging" / "bookTicker"
    assert store.root.is_dir()
    assert store.staging.root == tmp_path / "staging"


def test_records_are_retained_permanently_not_expired(tmp_path) -> None:
    # Unlike the L2 book diffs, which a rolling 90-day window drops, this
    # stream's §4.1 row is *forever*: there is deliberately no prune, and the
    # append-only area never expires a record.
    store = make_store(tmp_path)
    for i in range(5):
        store.record(payload(btc_snapshot(bid=f"61234.{i:02d}")), written_at=T0 + timedelta(seconds=i))

    assert len(store.records()) == 5
    assert store.row_count() == 5
    # The store offers no retention pass — the log is permanent by structure.
    assert not hasattr(store, "prune")


def test_a_batch_exposes_its_symbols_and_span() -> None:
    batch = parse_l1_book(payload(btc_snapshot(), eth_snapshot()))

    assert batch.symbols == ("BTCUSDT", "ETHUSDT")
    assert batch.first_time == T0
    assert batch.last_time == T0
    assert batch.for_symbol("BTCUSDT")[0].bid_price == "61234.50"


def test_a_row_carries_the_venues_two_sides_verbatim() -> None:
    parsed = parse_l1_book(payload(btc_snapshot(bid="61234.500", ask="61234.600")))
    r = parsed.rows[0]

    assert r.bid_price == "61234.500"
    assert r.ask_price == "61234.600"
    assert r.spread == "61234.500/61234.600"
