"""Aggregated trades off the websocket feed, compressed and retained permanently.

These tests are the feature statement for app_spec.xml feature 18 —
*"System ingests aggTrades from the websocket feed, persisting compressed
rows retained permanently"* — read as behaviour of the aggTrade store, the
worker and the parser they stand on:

* a flush lands as the next record in an append-only log, and a prior record's
  bytes are never rewritten by a later one;
* the rows are **compressed** before they are written — the one property this
  stream adds — and decompressed on the read path, so the permanent tape
  occupies a fraction of its raw size and the bytes a seal copies are the
  compressed ones;
* each flush is persisted and retained permanently — the feature says *each*
  flush is persisted, and the log is the permanent history a reader walks back
  across; there is no retention window that drops a flush;
* prices and quantities are kept verbatim in the venue's own spelling, and a
  failed flush — a rate-limit body, a truncated frame — is refused *before*
  anything is written, so the log never records a flush that did not happen;
* the trades are read back off the persisted, decompressed record, and damaged
  bytes (a non-gzip file, a hash mismatch) are refused rather than parsed into
  a plausible-looking tape;
* a quiet cycle — a fetch that returns no trades — is a zero-row success, not a
  failure.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

import pytest

from nullius_ingest import (
    AGG_TRADES_STREAM,
    COMPRESSION,
    AggTradeBatch,
    AggTradeCorruptError,
    AggTradeError,
    AggTradeParseError,
    AggTradeRecord,
    AggTradeRow,
    AggTradeStore,
    AggTradeWorker,
    StagingArea,
    StreamClass,
    parse_agg_trades,
)
from nullius_ingest.agg_trades import register_agg_trade_worker
from nullius_ingest.registry import WorkerRegistry, default_worker_registry

UTC = timezone.utc

#: A trade instant, as epoch milliseconds — the way a websocket feed spells it.
T0_MS = 1_772_366_400_000
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def trade(
    *,
    symbol: str = "BTCUSDT",
    agg_id: int = 100,
    price: str = "61234.50",
    quantity: str = "0.5",
    first: int = 100,
    last: int = 102,
    event_ms: int = T0_MS,
    maker: bool = True,
) -> dict:
    """One venue-shaped aggTrade, the way a websocket feed spells it."""
    return {
        "e": "aggTrade",
        "E": event_ms,
        "s": symbol,
        "a": agg_id,
        "p": price,
        "q": quantity,
        "f": first,
        "l": last,
        "m": maker,
    }


def payload(*trades: dict) -> dict:
    """A full aggTrade response carrying the given trades, as a bare list."""
    return {"aggTrades": list(trades)}


def row(agg_id: int = 100, price: str = "61234.50", quantity: str = "0.5") -> AggTradeRow:
    return AggTradeRow(
        symbol="BTCUSDT",
        agg_id=agg_id,
        price=price,
        quantity=quantity,
        first_trade_id=agg_id,
        last_trade_id=agg_id,
        event_time=T0,
        is_buyer_maker=True,
    )


def make_store(tmp_path) -> AggTradeStore:
    return AggTradeStore(StagingArea(tmp_path))


# -- Parsing the venue's document -------------------------------------------


def test_parses_every_field_of_a_trade() -> None:
    parsed = parse_agg_trades(payload(trade()))

    assert isinstance(parsed, AggTradeBatch)
    assert len(parsed) == 1
    only = parsed.rows[0]
    assert only.symbol == "BTCUSDT"
    assert only.agg_id == 100
    assert only.price == "61234.50"
    assert only.quantity == "0.5"
    assert only.first_trade_id == 100
    assert only.last_trade_id == 102
    assert only.event_time == T0
    assert only.is_buyer_maker is True


def test_price_and_quantity_are_kept_verbatim_in_the_venues_spelling() -> None:
    # The tape must not round anything: whether the venue said "61234.50" or
    # "61234.5" is a fact about the venue, and re-rendering it would make an
    # audit unable to tell a venue change from our own lossy parse.
    parsed = parse_agg_trades(payload(trade(price="61234.500", quantity="0.5000")))
    only = parsed.rows[0]
    assert only.price == "61234.500"
    assert only.quantity == "0.5000"


def test_a_numeric_price_is_spelled_not_rounded() -> None:
    # A venue that sends a bare number for a price must still be kept verbatim
    # — repr, not a float round-trip that would drop trailing zeros.
    parsed = parse_agg_trades(payload(trade(price=61234.5, quantity=2)))
    only = parsed.rows[0]
    assert only.price == "61234.5"
    assert only.quantity == "2"


def test_a_float_price_is_rendered_exactly() -> None:
    # repr(float) is the honest spelling, not str(float): 0.1 must not become
    # a silently-rounded value on the permanent tape.
    parsed = parse_agg_trades(payload(trade(price=0.1, quantity=1)))
    assert parsed.rows[0].price == repr(0.1)


def test_accepts_a_bare_list() -> None:
    parsed = parse_agg_trades([trade(), trade(agg_id=101)])
    assert len(parsed) == 2


def test_accepts_a_json_string_body() -> None:
    body = json.dumps(payload(trade()))
    parsed = parse_agg_trades(body)
    assert len(parsed) == 1


def test_accepts_a_json_bytes_body() -> None:
    body = json.dumps(payload(trade())).encode("utf-8")
    parsed = parse_agg_trades(body)
    assert len(parsed) == 1


def test_accepts_a_single_trade_object() -> None:
    parsed = parse_agg_trades(trade())
    assert len(parsed) == 1


def test_accepts_a_data_wrapped_payload() -> None:
    parsed = parse_agg_trades({"data": [trade()]})
    assert len(parsed) == 1


def test_accepts_an_already_parsed_batch() -> None:
    first = parse_agg_trades(payload(trade()))
    assert parse_agg_trades(first) is first


def test_long_form_field_names() -> None:
    # A venue that spells the fields out rather than using Binance's short
    # letters must parse to the same row.
    doc = {
        "aggTradeId": 100,
        "price": "61234.50",
        "quantity": "0.5",
        "firstTradeId": 100,
        "lastTradeId": 102,
        "eventTime": T0_MS,
        "is_buyer_maker": False,
        "symbol": "BTCUSDT",
    }
    parsed = parse_agg_trades([doc])
    only = parsed.rows[0]
    assert only.agg_id == 100
    assert only.is_buyer_maker is False


def test_event_time_is_placed_exactly_on_the_epoch() -> None:
    # 1772308800000 ms is exactly 2026-03-01T12:00:00Z; no float rounding.
    parsed = parse_agg_trades(payload(trade(event_ms=T0_MS)))
    assert parsed.rows[0].event_time == T0


# -- Parsing refusals: a failed flush consumes no sequence --------------------


def test_an_empty_batch_is_refused() -> None:
    with pytest.raises(AggTradeParseError, match="at least one row"):
        parse_agg_trades({"aggTrades": []})


def test_a_trade_with_no_symbol_is_refused() -> None:
    bad = trade()
    del bad["s"]
    with pytest.raises(AggTradeParseError, match="symbol"):
        parse_agg_trades([bad])


def test_a_trade_with_no_agg_id_is_refused() -> None:
    bad = trade()
    del bad["a"]
    with pytest.raises(AggTradeParseError, match="aggregated trade id"):
        parse_agg_trades([bad])


def test_a_reversed_trade_range_is_refused() -> None:
    bad = trade(first=102, last=100)
    with pytest.raises(AggTradeParseError, match="does not end before it begins"):
        parse_agg_trades([bad])


def test_a_non_integer_agg_id_is_refused() -> None:
    bad = trade()
    bad["a"] = "not-an-int"
    with pytest.raises(AggTradeParseError, match="integer id"):
        parse_agg_trades([bad])


def test_a_fractional_agg_id_is_refused() -> None:
    bad = trade()
    bad["a"] = "100.5"
    with pytest.raises(AggTradeParseError, match="integer id"):
        parse_agg_trades([bad])


def test_a_bool_maker_flag_is_required() -> None:
    bad = trade()
    del bad["m"]
    with pytest.raises(AggTradeParseError, match="maker flag"):
        parse_agg_trades([bad])


def test_a_stringy_maker_flag_is_refused_not_coerced() -> None:
    # A truthy string must not masquerade as a real maker flag on the tape.
    bad = trade()
    bad["m"] = "true"
    with pytest.raises(AggTradeParseError, match="must be a boolean"):
        parse_agg_trades([bad])


def test_a_trade_with_no_event_time_is_refused() -> None:
    bad = trade()
    del bad["E"]
    with pytest.raises(AggTradeParseError, match="no event time"):
        parse_agg_trades([bad])


def test_a_naive_iso_event_time_is_refused() -> None:
    bad = trade()
    bad["E"] = "2026-03-01T12:00:00"
    with pytest.raises(AggTradeParseError, match="naive"):
        parse_agg_trades([bad])


def test_a_non_trade_document_is_refused() -> None:
    with pytest.raises(AggTradeParseError, match="not a trade"):
        parse_agg_trades({"nothing": "here"})


def test_invalid_json_is_refused() -> None:
    with pytest.raises(AggTradeParseError, match="not valid JSON"):
        parse_agg_trades("{not json")


# -- The store: append-only, compressed, permanent ----------------------------


def test_a_flush_lands_as_the_next_record(tmp_path) -> None:
    store = make_store(tmp_path)

    first = store.record(payload(trade(agg_id=100)), written_at=T0)
    second = store.record(payload(trade(agg_id=101)), written_at=T0)

    assert first.sequence == 1
    assert second.sequence == 2
    assert first.row_count == 1
    assert second.row_count == 1


def test_a_prior_records_bytes_are_never_rewritten(tmp_path) -> None:
    store = make_store(tmp_path)

    store.record(payload(trade(agg_id=100)), written_at=T0)
    file1_before = store.path_for(1).read_bytes()
    store.record(payload(trade(agg_id=101)), written_at=T0)
    file1_after = store.path_for(1).read_bytes()

    # The first record's bytes are exactly what was committed after a second
    # append — the append-only guarantee, and the thing a permanent tape relies
    # on: a later record never touches an earlier one's file.
    assert file1_before == file1_after


def test_the_written_bytes_are_compressed(tmp_path) -> None:
    store = make_store(tmp_path)

    record = store.record(payload(trade()), written_at=T0)

    blob = record.path.read_bytes()
    # gzip magic: the record on disk is compressed, which is the whole of
    # feature 18's "compressed" and what a seal copies.
    assert blob[:2] == b"\x1f\x8b"
    # And it decompresses back to a valid envelope naming this stream.
    envelope = json.loads(gzip.decompress(blob))
    assert envelope["stream"] == "aggTrades"
    assert envelope["sequence"] == record.sequence


def test_the_payload_hash_is_over_the_compressed_bytes(tmp_path) -> None:
    store = make_store(tmp_path)

    record = store.record(payload(trade()), written_at=T0)

    assert record.payload_sha256 == hashlib_sha256(record.path.read_bytes())


def test_the_source_hash_is_over_the_uncompressed_document(tmp_path) -> None:
    store = make_store(tmp_path)

    record = store.record(payload(trade()), written_at=T0)

    # source_sha256 answers "did the trades change?": it is over the canonical
    # document, not the compressed bytes, so it is stable across a codec change.
    assert record.source_sha256 == record.batch.source_sha256


def test_the_compression_is_named_and_stored(tmp_path) -> None:
    store = make_store(tmp_path)
    assert store.compression == COMPRESSION == "gzip"


def test_records_round_trip_through_the_compressed_file(tmp_path) -> None:
    store = make_store(tmp_path)

    store.record(payload(trade(agg_id=100, price="61234.50", quantity="0.5")), written_at=T0)

    reread = store.records()
    assert [r.sequence for r in reread] == [1]
    only = reread[0].batch.rows[0]
    assert only.agg_id == 100
    assert only.price == "61234.50"
    assert only.quantity == "0.5"
    assert only.event_time == T0
    assert only.is_buyer_maker is True


def test_current_previous_and_record_at(tmp_path) -> None:
    store = make_store(tmp_path)

    store.record(payload(trade(agg_id=100)), written_at=T0)
    store.record(payload(trade(agg_id=101)), written_at=T0)

    assert store.current() is not None
    assert store.current().sequence == 2
    assert store.previous() is not None
    assert store.previous().sequence == 1
    assert store.record_at(1) is not None
    assert store.record_at(1).sequence == 1
    assert store.record_at(99) is None


def test_an_empty_store_has_no_current(tmp_path) -> None:
    store = make_store(tmp_path)
    assert store.current() is None
    assert store.previous() is None
    assert store.records() == ()


def test_a_reconstructed_store_reads_what_a_prior_run_wrote(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(trade(agg_id=100)), written_at=T0)
    store.record(payload(trade(agg_id=101)), written_at=T0)

    # A restart over the same staging tree resumes reading the permanent tape.
    reopened = AggTradeStore(StagingArea(tmp_path))
    assert reopened.row_count() == 2
    assert [r.sequence for r in reopened.records()] == [1, 2]


def test_appends_are_gap_free_and_never_overwrite(tmp_path) -> None:
    store = make_store(tmp_path)
    for i in range(100, 105):
        store.record(payload(trade(agg_id=i)), written_at=T0)
    # The append-only log is gap-free 1..5, and every record is still readable.
    assert [r.sequence for r in store.records()] == [1, 2, 3, 4, 5]
    assert store.row_count() == 5


def test_rows_are_retained_permanently_no_prune(tmp_path) -> None:
    # The §4.1 row is *forever*: unlike the book-diff store there is no prune,
    # no expiry, no retention window.  Every flush stays, however old.
    store = make_store(tmp_path)
    store.record(payload(trade(event_ms=T0_MS)), written_at=T0)
    # A prune method would contradict the permanent row; the store has none.
    assert not hasattr(store, "prune")
    assert store.row_count() == 1


# -- Damaged bytes are refused, not parsed around -----------------------------


def test_a_non_gzip_file_is_refused_as_corrupt(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(trade()), written_at=T0)

    # Corrupt sequence 1 with undecompressable bytes, then re-read from disk so
    # the tampered file — not the in-memory cache — is what the store meets.
    store.path_for(1).write_bytes(b"not gzip at all")
    with pytest.raises(AggTradeCorruptError, match="gzip"):
        AggTradeStore(StagingArea(tmp_path)).records()


def test_a_hash_mismatch_is_refused_as_corrupt(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(trade()), written_at=T0)

    blob = store.path_for(1).read_bytes()
    envelope = json.loads(gzip.decompress(blob))
    envelope["source_sha256"] = "deadbeef"
    tampered = gzip.compress(json.dumps(envelope).encode("utf-8"), mtime=0)
    store.path_for(1).write_bytes(tampered)
    # A record whose recomputed document hash disagrees with the one it
    # recorded: the bytes on disk are not the bytes that were committed.
    with pytest.raises(AggTradeCorruptError, match="bytes are not the bytes"):
        AggTradeStore(StagingArea(tmp_path)).records()


def test_a_wrong_sequence_in_the_envelope_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(trade()), written_at=T0)

    blob = store.path_for(1).read_bytes()
    envelope = json.loads(gzip.decompress(blob))
    envelope["sequence"] = 999
    tampered = gzip.compress(json.dumps(envelope).encode("utf-8"), mtime=0)
    store.path_for(1).write_bytes(tampered)
    with pytest.raises(AggTradeCorruptError, match="does not describe itself"):
        AggTradeStore(StagingArea(tmp_path)).records()


# -- The worker ---------------------------------------------------------------


def test_a_cycle_persists_the_flush(tmp_path) -> None:
    store = make_store(tmp_path)
    worker = AggTradeWorker(store, lambda: payload(trade(agg_id=100)), clock=lambda: T0)

    result = worker.run_cycle()

    assert result.sequence == 1
    assert result.rows_written == 1
    assert store.current() is not None


def test_a_quiet_cycle_writes_nothing_and_reports_zero(tmp_path) -> None:
    store = make_store(tmp_path)
    worker = AggTradeWorker(store, lambda: None, clock=lambda: T0)

    result = worker.run_cycle()

    # A quiet feed is a zero-row success, not a failure: a liquid book prints
    # continuously but a quiet one can legitimately go a cycle without a trade.
    assert result.sequence == 0
    assert result.rows_written == 0
    assert store.current() is None


def test_a_failed_flush_writes_nothing_and_raises(tmp_path) -> None:
    store = make_store(tmp_path)

    def broken_fetch() -> dict:
        raise AggTradeError("websocket dropped")

    worker = AggTradeWorker(store, broken_fetch, clock=lambda: T0)

    with pytest.raises(AggTradeError):
        worker.run_cycle()
    assert store.current() is None


def test_a_parse_failure_consumes_no_sequence(tmp_path) -> None:
    store = make_store(tmp_path)

    def bad_fetch() -> dict:
        return {"aggTrades": []}  # an empty flush is a failed flush

    worker = AggTradeWorker(store, bad_fetch, clock=lambda: T0)

    with pytest.raises(AggTradeParseError):
        worker.run_cycle()
    # No sequence was spent, so the next honest flush still claims sequence 1.
    assert store._staging.current(AGG_TRADES_STREAM) == 0
    good_worker = AggTradeWorker(store, lambda: payload(trade()), clock=lambda: T0)
    assert good_worker.run_cycle().sequence == 1


def test_the_worker_owns_only_the_aggtrades_stream(tmp_path) -> None:
    store = make_store(tmp_path)
    worker = AggTradeWorker(store, lambda: payload(trade()), clock=lambda: T0)
    assert worker.stream_class is StreamClass.AGG_TRADES
    assert worker.stream_class is AGG_TRADES_STREAM


def test_the_worker_rejects_a_wrong_store() -> None:
    with pytest.raises(TypeError):
        AggTradeWorker(object(), lambda: payload(trade()))  # type: ignore[arg-type]


# -- Registration and composition -------------------------------------------


def test_the_member_registers_a_worker_for_the_aggtrades_stream() -> None:
    # Importing the package fires the registration — the plugin convention
    # every later ingest feature follows, with no shared file edited.
    assert AGG_TRADES_STREAM in default_worker_registry()
    assert StreamClass.AGG_TRADES in default_worker_registry()


def test_the_default_registry_now_includes_aggtrades() -> None:
    # Feature 18 lands as a registration: the auto-discovered worker set grows
    # to include aggTrades alongside the streams that already landed.
    assert StreamClass.AGG_TRADES in {
        w.stream_class for w in default_worker_registry().build_workers()
    }


def test_the_composed_app_supervises_the_aggtrades_stream() -> None:
    from app.module_loader import create_app, Registration
    from pathlib import Path

    import nullius_ingest

    member_src = Path(nullius_ingest.__file__).resolve().parent.parent
    component = create_app(member_src, registry=Registration()).get("ingest")

    assert StreamClass.AGG_TRADES in component


def test_registering_an_explicit_fetch_revises_the_same_worker(tmp_path) -> None:
    store = make_store(tmp_path)
    registry = WorkerRegistry()

    def fetch() -> dict:
        return payload(trade(agg_id=100))

    build = register_agg_trade_worker(fetch, store=store, registry=registry)
    worker = build()

    assert worker.run_cycle().sequence == 1
    # Re-registering the same class revises the one worker, never adds a second.
    assert len(registry) == 1


def test_an_unconfigured_worker_reports_the_streams_own_failure(tmp_path) -> None:
    from nullius_ingest.supervisor import IngestSupervisor

    store = make_store(tmp_path)
    # The auto-discovered worker's fetch raises until a deployment wires one.
    worker = AggTradeWorker(store, lambda: (_ for _ in ()).throw(AggTradeError("unconfigured")))
    supervisor = IngestSupervisor([worker])

    report = supervisor.run_cycle()
    failure = report.outcome_for(StreamClass.AGG_TRADES)

    assert failure is not None and not failure.ok
    assert failure.failure.error_type == "AggTradeError"


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
