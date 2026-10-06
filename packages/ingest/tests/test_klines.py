"""Klines (1m/1h/1d) off a REST backfill and a websocket tail, retained permanently.

These tests are the feature statement for app_spec.xml feature 17 —
*"System ingests 1m, 1h and 1d klines from REST backfill plus a websocket
tail, persisting rows into the staging area"* — read as behaviour of the
kline store, the tail worker, the backfiller and the parser they stand on:

* a flush or a backfill page lands as the next record in an append-only log,
  and a prior record's bytes are never rewritten by a later one;
* the OHLCV fields are kept **verbatim** in the venue's own spelling, and the
  interval is one of 1m, 1h or 1d — a candle of any other interval is refused;
* each flush's or page's candles are persisted and retained permanently — the
  §4.1 row is *forever*, so there is no retention window that drops a candle;
* the open and close instants are placed exactly on the epoch lattice, and a
  failed flush or a short backfill page is refused *before* anything is written,
  so the log never records a flush or page that did not happen;
* the candles are read back off the persisted record, and damaged bytes (a
  non-envelope file, a hash mismatch, a wrong sequence) are refused rather than
  parsed into a plausible-looking series;
* a quiet cycle — a fetch that returns no candles — is a zero-row success, not
  a failure;
* the backfill pages an inclusive range and refuses a page that did not cover
  it, so a range is only marked filled when the page provably filled it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from nullius_ingest import (
    KLINES_STREAM,
    KlineBackfillError,
    KlineBackfiller,
    KlineBatch,
    KlineCorruptError,
    KlineError,
    KlineParseError,
    KlineRecord,
    KlineRow,
    KlineStore,
    KlineWorker,
    StagingArea,
    StreamClass,
    parse_klines,
)
from nullius_ingest.klines import register_kline_worker
from nullius_ingest.registry import WorkerRegistry, default_worker_registry

UTC = timezone.utc

#: A candle open instant, as epoch milliseconds — the way a venue spells it.
T0_MS = 1_772_366_400_000
T1_MS = 1_772_366_460_000  # one minute later, for a 1m candle's close
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 3, 1, 12, 1, 0, tzinfo=UTC)


def candle(
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    open: str = "61234.50",
    high: str = "61300.00",
    low: str = "61200.00",
    close: str = "61250.00",
    volume: str = "12.5",
    open_time: int = T0_MS,
    close_time: int = T1_MS,
    trades: int = 42,
) -> dict:
    """One venue-shaped kline, the long-form mapping spelling."""
    return {
        "symbol": symbol,
        "interval": interval,
        "open": open,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_time": open_time,
        "close_time": close_time,
        "trades": trades,
    }


def payload(*candles: dict) -> dict:
    """A full kline response carrying the given candles, as a bare list."""
    return {"klines": list(candles)}


def row(
    *,
    open: str = "61234.50",
    high: str = "61300.00",
    low: str = "61200.00",
    close: str = "61250.00",
    volume: str = "12.5",
    open_time: datetime = T0,
    close_time: datetime = T1,
    trades: int = 42,
) -> KlineRow:
    return KlineRow(
        symbol="BTCUSDT",
        interval="1m",
        open=open,
        high_price=high,
        low_price=low,
        close=close,
        volume=volume,
        open_time=open_time,
        close_time=close_time,
        trade_count=trades,
    )


def make_store(tmp_path) -> KlineStore:
    return KlineStore(StagingArea(tmp_path))


# -- Parsing the venue's document -------------------------------------------


def test_parses_every_field_of_a_candle() -> None:
    parsed = parse_klines(payload(candle()), "1m")

    assert isinstance(parsed, KlineBatch)
    assert len(parsed) == 1
    only = parsed.candles[0]
    assert only.symbol == "BTCUSDT"
    assert only.interval == "1m"
    assert only.open == "61234.50"
    assert only.high_price == "61300.00"
    assert only.low_price == "61200.00"
    assert only.close == "61250.00"
    assert only.volume == "12.5"
    assert only.open_time == T0
    assert only.close_time == T1
    assert only.trade_count == 42


def test_open_and_close_are_placed_exactly_on_the_epoch() -> None:
    # 1772366400000 ms is exactly 2026-03-01T12:00:00Z; no float rounding.
    parsed = parse_klines(payload(candle(open_time=T0_MS, close_time=T1_MS)), "1m")
    only = parsed.candles[0]
    assert only.open_time == T0
    assert only.close_time == T1


def test_prices_and_volume_are_kept_verbatim_in_the_venues_spelling() -> None:
    # Whether the venue said "61234.50" or "61234.5" is a fact about the venue,
    # and re-rendering it would make an audit unable to tell a venue change from
    # our own lossy parse.
    parsed = parse_klines(
        payload(candle(open="61234.500", high="61300.0000", volume="12.5000")), "1m"
    )
    only = parsed.candles[0]
    assert only.open == "61234.500"
    assert only.high_price == "61300.0000"
    assert only.volume == "12.5000"


def test_a_numeric_price_is_spelled_not_rounded() -> None:
    # A venue that sends a bare number for a price must still be kept verbatim —
    # repr, not a float round-trip that would drop trailing zeros.
    parsed = parse_klines(payload(candle(open=61234.5, volume=2)), "1m")
    only = parsed.candles[0]
    assert only.open == "61234.5"
    assert only.volume == "2"


def test_a_float_price_is_rendered_exactly() -> None:
    # repr(float) is the honest spelling, not str(float): 0.1 must not become a
    # silently-rounded value on the permanent tape.
    parsed = parse_klines(payload(candle(open=0.1, volume=1)), "1m")
    assert parsed.candles[0].open == repr(0.1)


def test_accepts_a_bare_list() -> None:
    parsed = parse_klines([candle(), candle(close="61251.00")], "1m")
    assert len(parsed) == 2


def test_accepts_a_json_string_body() -> None:
    body = json.dumps(payload(candle()))
    parsed = parse_klines(body, "1m")
    assert len(parsed) == 1


def test_accepts_a_json_bytes_body() -> None:
    body = json.dumps(payload(candle())).encode("utf-8")
    parsed = parse_klines(body, "1m")
    assert len(parsed) == 1


def test_accepts_a_data_wrapped_payload() -> None:
    parsed = parse_klines({"data": [candle()]}, "1m")
    assert len(parsed) == 1


def test_accepts_an_already_parsed_batch() -> None:
    first = parse_klines(payload(candle()), "1m")
    assert parse_klines(first, "1m") is first


def test_accepts_a_positional_array_candle() -> None:
    # The venue's per-symbol klines REST returns each candle as a fixed-length
    # array — [open_time, open, high, low, close, volume, close_time,
    # quote_volume, trade_count] — with no symbol field of its own: the symbol
    # is the request parameter, so it is passed as the fallback.
    array = [
        T0_MS, "61234.50", "61300.00", "61200.00", "61250.00", "12.5", T1_MS,
        "858.11", 42,
    ]
    parsed = parse_klines([array], "1m", symbol="BTCUSDT")
    only = parsed.candles[0]
    assert only.symbol == "BTCUSDT"
    assert only.open == "61234.50"
    assert only.open_time == T0
    assert only.close_time == T1
    assert only.trade_count == 42


def test_short_form_field_names() -> None:
    # A venue that uses the short letters rather than the long names must parse
    # to the same row.
    doc = {
        "s": "BTCUSDT",
        "o": "61234.50",
        "h": "61300.00",
        "l": "61200.00",
        "c": "61250.00",
        "v": "12.5",
        "O": T0_MS,
        "C": T1_MS,
        "n": 42,
    }
    parsed = parse_klines([doc], "1m")
    only = parsed.candles[0]
    assert only.open == "61234.50"
    assert only.trade_count == 42


def test_multiple_symbols_in_one_batch() -> None:
    parsed = parse_klines(
        payload(candle(symbol="BTCUSDT"), candle(symbol="ETHUSDT")), "1m"
    )
    assert parsed.symbols == ("BTCUSDT", "ETHUSDT")
    assert parsed.for_symbol("ETHUSDT")[0].symbol == "ETHUSDT"


def test_the_interval_is_carried_and_named() -> None:
    parsed = parse_klines(payload(candle()), "1h")
    assert parsed.interval == "1h"
    assert parsed.candles[0].interval == "1h"


# -- Parsing refusals: a failed flush consumes no sequence --------------------


def test_an_empty_batch_is_refused() -> None:
    with pytest.raises(KlineParseError, match="at least one candle"):
        parse_klines({"klines": []}, "1m")


def test_a_candle_with_no_symbol_is_refused() -> None:
    bad = candle()
    del bad["symbol"]
    with pytest.raises(KlineParseError, match="symbol"):
        parse_klines([bad], "1m")


def test_a_candle_with_no_open_is_refused() -> None:
    bad = candle()
    del bad["open"]
    with pytest.raises(KlineParseError, match="open"):
        parse_klines([bad], "1m")


def test_a_candle_with_no_close_is_refused() -> None:
    bad = candle()
    del bad["close"]
    with pytest.raises(KlineParseError, match="close"):
        parse_klines([bad], "1m")


def test_a_candle_with_no_volume_is_refused() -> None:
    bad = candle()
    del bad["volume"]
    with pytest.raises(KlineParseError, match="volume"):
        parse_klines([bad], "1m")


def test_a_candle_with_no_open_time_is_refused() -> None:
    bad = candle()
    del bad["open_time"]
    with pytest.raises(KlineParseError, match="open time"):
        parse_klines([bad], "1m")


def test_a_candle_with_no_close_time_is_refused() -> None:
    # A candle's close time is the next candle's open time; without it the
    # candle is not a closed candle, so it is refused rather than guessed.
    bad = candle()
    del bad["close_time"]
    with pytest.raises(KlineParseError, match="close time"):
        parse_klines([bad], "1m")


def test_a_wrong_interval_is_refused() -> None:
    # §4.1 names exactly 1m, 1h and 1d; a candle of any other interval is
    # refused rather than persisted under a spelling the reader cannot trust.
    with pytest.raises(KlineParseError, match="interval"):
        parse_klines(payload(candle(interval="5m")), "5m")


def test_a_reversed_candle_is_refused() -> None:
    # A candle that closes before it opens is not a candle this module can
    # record — the pair is the candle's span, and a reversed one would make the
    # series appear to run backwards.
    bad = candle(open_time=T1_MS, close_time=T0_MS)
    with pytest.raises(KlineParseError, match="before it opens"):
        parse_klines([bad], "1m")


def test_a_non_instant_open_time_is_refused() -> None:
    # The venue's klines instant is epoch milliseconds; a naive ISO string is
    # not a valid venue spelling and is refused before any candle is placed.
    bad = candle()
    bad["open_time"] = "2026-03-01T12:00:00"
    bad["close_time"] = "2026-03-01T12:01:00"
    with pytest.raises(KlineParseError, match="epoch-millisecond instant"):
        parse_klines([bad], "1m")


def test_a_negative_trade_count_is_refused() -> None:
    bad = candle()
    bad["trades"] = -1
    with pytest.raises(KlineParseError, match="trade count"):
        parse_klines([bad], "1m")


def test_a_non_candle_document_is_refused() -> None:
    with pytest.raises(KlineParseError, match="no candle list"):
        parse_klines({"nothing": "here"}, "1m")


def test_invalid_json_is_refused() -> None:
    with pytest.raises(KlineParseError, match="not valid JSON"):
        parse_klines("{not json", "1m")


def test_a_positional_array_that_is_too_short_is_refused() -> None:
    array = [T0_MS, "61234.50", "61300.00"]  # missing close, volume, close_time
    with pytest.raises(KlineParseError, match="at least"):
        parse_klines([array], "1m")


# -- The store: append-only, permanent ----------------------------------------


def test_a_flush_lands_as_the_next_record(tmp_path) -> None:
    store = make_store(tmp_path)

    first = store.record(payload(candle(open="61234.50")), written_at=T0, interval="1m")
    second = store.record(payload(candle(open="61235.00")), written_at=T0, interval="1m")

    assert first.sequence == 1
    assert second.sequence == 2
    assert first.row_count == 1
    assert second.row_count == 1
    assert first.first_open == T0
    assert first.last_open == T0


def test_a_prior_records_bytes_are_never_rewritten(tmp_path) -> None:
    store = make_store(tmp_path)

    store.record(payload(candle(open="61234.50")), written_at=T0, interval="1m")
    file1_before = store.path_for(1).read_bytes()
    store.record(payload(candle(open="61235.00")), written_at=T0, interval="1m")
    file1_after = store.path_for(1).read_bytes()

    # The first record's bytes are exactly what was committed after a second
    # append — the append-only guarantee, and the thing a permanent tape relies
    # on: a later record never touches an earlier one's file.
    assert file1_before == file1_after


def test_the_payload_hash_is_over_the_written_bytes(tmp_path) -> None:
    store = make_store(tmp_path)

    record = store.record(payload(candle()), written_at=T0, interval="1m")

    assert record.payload_sha256 == hashlib_sha256(record.path.read_bytes())


def test_the_source_hash_is_over_the_uncompressed_document(tmp_path) -> None:
    store = make_store(tmp_path)

    record = store.record(payload(candle()), written_at=T0, interval="1m")

    # source_sha256 answers "did the candles change?": it is over the canonical
    # document, not the written bytes, so it is stable across a re-serialization.
    assert record.source_sha256 == record.batch.source_sha256


def test_records_round_trip_through_the_file(tmp_path) -> None:
    store = make_store(tmp_path)

    store.record(
        payload(candle(open="61234.50", volume="12.5")), "1m", written_at=T0
    )

    reread = store.records()
    assert [r.sequence for r in reread] == [1]
    only = reread[0].batch.candles[0]
    assert only.open == "61234.50"
    assert only.volume == "12.5"
    assert only.open_time == T0
    assert only.close_time == T1
    assert only.trade_count == 42


def test_current_previous_and_record_at(tmp_path) -> None:
    store = make_store(tmp_path)

    store.record(payload(candle(open="61234.50")), written_at=T0, interval="1m")
    store.record(payload(candle(open="61235.00")), written_at=T0, interval="1m")

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
    store.record(payload(candle(open="61234.50")), written_at=T0, interval="1m")
    store.record(payload(candle(open="61235.00")), written_at=T0, interval="1m")

    # A restart over the same staging tree resumes reading the permanent tape.
    reopened = KlineStore(StagingArea(tmp_path))
    assert reopened.row_count() == 2
    assert [r.sequence for r in reopened.records()] == [1, 2]


def test_appends_are_gap_free_and_never_overwrite(tmp_path) -> None:
    store = make_store(tmp_path)
    for i in range(5):
        store.record(payload(candle(open=f"61234.{i}")), written_at=T0, interval="1m")
    # The append-only log is gap-free 1..5, and every record is still readable.
    assert [r.sequence for r in store.records()] == [1, 2, 3, 4, 5]
    assert store.row_count() == 5


def test_rows_are_retained_permanently_no_prune(tmp_path) -> None:
    # The §4.1 row is *forever*: unlike the book-diff store there is no prune,
    # no expiry, no retention window.  Every candle stays, however old.
    store = make_store(tmp_path)
    store.record(payload(candle(open_time=T0_MS)), written_at=T0, interval="1m")
    # A prune method would contradict the permanent row; the store has none.
    assert not hasattr(store, "prune")
    assert store.row_count() == 1


def test_a_failed_record_consumes_no_sequence(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(KlineParseError):
        store.record(payload(candle(open="")), written_at=T0, interval="1m")
    # No sequence was spent, so the next honest flush still claims sequence 1.
    assert store._staging.current(KLINES_STREAM) == 0
    assert store.record(payload(candle()), written_at=T0, interval="1m").sequence == 1


# -- Damaged bytes are refused, not parsed around -----------------------------


def test_a_non_envelope_file_is_refused_as_corrupt(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(candle()), written_at=T0, interval="1m")

    # Corrupt sequence 1 with undecodable bytes, then re-read from disk so the
    # tampered file — not the in-memory path — is what the store meets.
    store.path_for(1).write_bytes(b"not json at all")
    with pytest.raises(KlineCorruptError, match="not readable"):
        KlineStore(StagingArea(tmp_path)).records()


def test_a_hash_mismatch_is_refused_as_corrupt(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(candle()), written_at=T0, interval="1m")

    blob = store.path_for(1).read_bytes()
    envelope = json.loads(blob.decode("utf-8"))
    envelope["source_sha256"] = "deadbeef"
    tampered = json.dumps(envelope).encode("utf-8")
    store.path_for(1).write_bytes(tampered)
    # A record whose recomputed document hash disagrees with the one it
    # recorded: the bytes on disk are not the bytes that were committed.
    with pytest.raises(KlineCorruptError, match="bytes are not the bytes"):
        KlineStore(StagingArea(tmp_path)).records()


def test_a_wrong_sequence_in_the_envelope_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(candle()), written_at=T0, interval="1m")

    blob = store.path_for(1).read_bytes()
    envelope = json.loads(blob.decode("utf-8"))
    envelope["sequence"] = 999
    tampered = json.dumps(envelope).encode("utf-8")
    store.path_for(1).write_bytes(tampered)
    with pytest.raises(KlineCorruptError, match="does not describe itself"):
        KlineStore(StagingArea(tmp_path)).records()


def test_a_missing_key_in_the_envelope_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(candle()), written_at=T0, interval="1m")

    blob = store.path_for(1).read_bytes()
    envelope = json.loads(blob.decode("utf-8"))
    del envelope["source_sha256"]
    store.path_for(1).write_bytes(json.dumps(envelope).encode("utf-8"))
    with pytest.raises(KlineCorruptError, match="missing"):
        KlineStore(StagingArea(tmp_path)).records()


# -- The tail worker ----------------------------------------------------------


def test_a_cycle_persists_the_flush(tmp_path) -> None:
    store = make_store(tmp_path)
    worker = KlineWorker(store, lambda: payload(candle(open="61234.50")), clock=lambda: T0)

    result = worker.run_cycle()

    assert result.sequence == 1
    assert result.rows_written == 1
    assert store.current() is not None


def test_a_quiet_cycle_writes_nothing_and_reports_zero(tmp_path) -> None:
    store = make_store(tmp_path)
    worker = KlineWorker(store, lambda: None, clock=lambda: T0)

    result = worker.run_cycle()

    # A quiet feed is a zero-row success, not a failure: a candle closes on its
    # interval boundary, and a quiet cycle between boundaries is legitimate.
    assert result.sequence == 0
    assert result.rows_written == 0
    assert store.current() is None


def test_a_failed_flush_writes_nothing_and_raises(tmp_path) -> None:
    store = make_store(tmp_path)

    def broken_fetch() -> object:
        raise KlineError("websocket dropped")

    worker = KlineWorker(store, broken_fetch, clock=lambda: T0)

    with pytest.raises(KlineError):
        worker.run_cycle()
    assert store.current() is None


def test_a_parse_failure_consumes_no_sequence(tmp_path) -> None:
    store = make_store(tmp_path)

    def bad_fetch() -> object:
        return payload(candle(open=""))  # an empty flush is a failed flush

    worker = KlineWorker(store, bad_fetch, clock=lambda: T0)

    with pytest.raises(KlineParseError):
        worker.run_cycle()
    assert store._staging.current(KLINES_STREAM) == 0
    good_worker = KlineWorker(store, lambda: payload(candle()), clock=lambda: T0)
    assert good_worker.run_cycle().sequence == 1


def test_the_worker_owns_only_the_klines_stream(tmp_path) -> None:
    store = make_store(tmp_path)
    worker = KlineWorker(store, lambda: payload(candle()), clock=lambda: T0)
    assert worker.stream_class is StreamClass.KLINES
    assert worker.stream_class is KLINES_STREAM


def test_the_worker_rejects_a_wrong_store() -> None:
    with pytest.raises(TypeError):
        KlineWorker(object(), lambda: payload(candle()))  # type: ignore[arg-type]


def test_a_naive_clock_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    worker = KlineWorker(store, lambda: payload(candle()), clock=lambda: datetime(2026, 3, 1))
    with pytest.raises(ValueError):
        worker.run_cycle()


# -- The backfill -------------------------------------------------------------


def test_a_page_fills_a_range_and_lands_as_a_record(tmp_path) -> None:
    staging = StagingArea(tmp_path)
    backfiller = KlineBackfiller(staging, _range_fetch, "1m")

    record = backfiller.page("BTCUSDT", T0_MS, T0_MS)

    assert record.sequence == 1
    assert record.row_count == 1
    assert record.first_open == T0
    assert record.last_open == T0


def test_a_page_covers_a_multi_candle_range(tmp_path) -> None:
    staging = StagingArea(tmp_path)

    def multi_fetch(symbol, interval, first, last):
        # Three consecutive 1m candles covering the inclusive range.
        return [
            _array_candle(symbol, first + i * 60_000, first + i * 60_000 + 60_000)
            for i in range(3)
        ]

    backfiller = KlineBackfiller(staging, multi_fetch, "1m")
    record = backfiller.page("BTCUSDT", T0_MS, T0_MS + 120_000)

    assert record.sequence == 1
    assert record.row_count == 3
    assert record.first_open == T0
    assert record.last_open == datetime(2026, 3, 1, 12, 2, tzinfo=UTC)


def test_a_short_page_is_refused_and_leaves_the_range_open(tmp_path) -> None:
    staging = StagingArea(tmp_path)

    def short_fetch(symbol, interval, first, last):
        # Asked for two candles, returned one — the range is not filled.
        return [_array_candle(symbol, first, first + 60_000)]

    backfiller = KlineBackfiller(staging, short_fetch, "1m")
    with pytest.raises(KlineBackfillError, match="did not fill"):
        backfiller.page("BTCUSDT", T0_MS, T0_MS + 60_000)
    # Nothing was appended — the range is still open.
    assert staging.current(KLINES_STREAM) == 0


def test_a_page_that_stops_short_of_the_end_is_refused(tmp_path) -> None:
    staging = StagingArea(tmp_path)

    def short_fetch(symbol, interval, first, last):
        # Returned candles that start right but stop before the last open.
        return [_array_candle(symbol, first, first + 60_000)]

    backfiller = KlineBackfiller(staging, short_fetch, "1m")
    with pytest.raises(KlineBackfillError) as excinfo:
        backfiller.page("BTCUSDT", T0_MS, T0_MS + 60_000)
    # The error names precisely what was still missing.
    assert excinfo.value.requested_last == T0_MS + 60_000
    assert excinfo.value.covered_last == T0_MS


def test_a_reversed_backfill_range_is_refused(tmp_path) -> None:
    staging = StagingArea(tmp_path)
    backfiller = KlineBackfiller(staging, _range_fetch, "1m")
    with pytest.raises(ValueError, match="reversed"):
        backfiller.page("BTCUSDT", T0_MS + 60_000, T0_MS)


def test_a_backfill_pages_land_in_open_time_order(tmp_path) -> None:
    staging = StagingArea(tmp_path)

    def fetch(symbol, interval, first, last):
        return [_array_candle(symbol, first, first + 60_000)]

    backfiller = KlineBackfiller(staging, fetch, "1m")
    backfiller.page("BTCUSDT", T0_MS, T0_MS)
    backfiller.page("BTCUSDT", T0_MS + 60_000, T0_MS + 60_000)

    records = KlineStore(staging).records()
    assert [r.sequence for r in records] == [1, 2]
    assert records[0].first_open == T0
    assert records[1].first_open == datetime(2026, 3, 1, 12, 1, tzinfo=UTC)


def test_a_backfiller_rejects_a_wrong_interval(tmp_path) -> None:
    with pytest.raises(KlineParseError, match="interval"):
        KlineBackfiller(StagingArea(tmp_path), _range_fetch, "5m")  # type: ignore[arg-type]


def _range_fetch(symbol, interval, first, last):
    # A fetch that returns exactly the single candle at ``first`` — used where
    # the range is a single candle.
    return [_array_candle(symbol, first, first + 60_000)]


def _array_candle(symbol, open_ms, close_ms):
    return [
        open_ms, "61234.50", "61300.00", "61200.00", "61250.00", "12.5",
        close_ms, "858.11", 42,
    ]


def test_the_trade_count_is_read_from_binance_index_8_not_7() -> None:
    # A row straight from Binance's own public klines API documentation
    # example: index 7 is the quote asset volume (a decimal string), index 8
    # is the trade count (an integer) — the two are easy to swap by one, and
    # this pins the correct one against a real recorded row.
    recorded_binance_row = [
        1499040000000,
        "0.01634790",
        "0.80000000",
        "0.01575800",
        "0.01577100",
        "148976.11427815",
        1499644799999,
        "2434.19055334",
        308,
        "1756.87402397",
        "28.46694368",
        "17928899.62484339",
    ]
    parsed = parse_klines([recorded_binance_row], "1d", symbol="ETHBTC")
    only = parsed.candles[0]
    assert only.trade_count == 308
    assert only.volume == "148976.11427815"
    assert only.close == "0.01577100"


# -- Registration and composition -------------------------------------------


def test_the_member_registers_a_worker_for_the_klines_stream() -> None:
    # Importing the package fires the registration — the plugin convention
    # every later ingest feature follows, with no shared file edited.
    assert KLINES_STREAM in default_worker_registry()
    assert StreamClass.KLINES in default_worker_registry()


def test_the_default_registry_now_includes_klines() -> None:
    # Feature 17 lands as a registration: the auto-discovered worker set grows
    # to include klines alongside the streams that already landed.
    assert StreamClass.KLINES in {
        w.stream_class for w in default_worker_registry().build_workers()
    }


def test_the_composed_app_supervises_the_klines_stream() -> None:
    from app.module_loader import Registration, create_app
    from pathlib import Path

    import nullius_ingest

    member_src = Path(nullius_ingest.__file__).resolve().parent.parent
    component = create_app(member_src, registry=Registration()).get("ingest")

    assert StreamClass.KLINES in component


def test_registering_an_explicit_fetch_revises_the_same_worker(tmp_path) -> None:
    store = make_store(tmp_path)
    registry = WorkerRegistry()

    def fetch() -> object:
        return payload(candle(open="61234.50"))

    build = register_kline_worker(fetch, store=store, registry=registry)
    worker = build()

    assert worker.run_cycle().sequence == 1
    # Re-registering the same class revises the one worker, never adds a second.
    assert len(registry) == 1


def test_an_unconfigured_worker_reports_the_streams_own_failure(tmp_path) -> None:
    from nullius_ingest.supervisor import IngestSupervisor

    store = make_store(tmp_path)
    # The auto-discovered worker's fetch raises until a deployment wires one.
    worker = KlineWorker(
        store, lambda: (_ for _ in ()).throw(KlineError("unconfigured"))
    )
    supervisor = IngestSupervisor([worker])

    report = supervisor.run_cycle()
    failure = report.outcome_for(StreamClass.KLINES)

    assert failure is not None and not failure.ok
    assert failure.failure.error_type == "KlineError"


def test_end_to_end_backfill_then_tail_resume_without_duplicates(tmp_path) -> None:
    # Feature 17 end to end, in one flow over a single staging tree: the klines
    # document parses and persists, a REST backfill fills a requested range, a
    # restarted store resumes from the last persisted sequence with no duplicate
    # rows, and the websocket tail appends a live flush alongside the history.
    staging = StagingArea(tmp_path)

    # (1) A REST backfill pages a two-candle inclusive range into the log.
    def range_fetch(symbol, interval, first, last):
        return [
            _array_candle(symbol, first, first + 60_000),
            _array_candle(symbol, first + 60_000, first + 120_000),
        ]

    backfiller = KlineBackfiller(staging, range_fetch, "1m")
    backfilled = backfiller.page("BTCUSDT", T0_MS, T0_MS + 60_000)
    assert backfilled.sequence == 1
    assert backfilled.row_count == 2
    assert backfilled.first_open == T0
    assert backfilled.last_open == datetime(2026, 3, 1, 12, 1, tzinfo=UTC)

    # (2) A restart over the same staging tree resumes from the last sequence —
    # the permanent tape is read back, and no candle is replayed or duplicated.
    resumed = KlineStore(staging)
    assert resumed.current() is not None
    assert resumed.current().sequence == 1
    assert [r.sequence for r in resumed.records()] == [1]

    # (3) The websocket tail appends a live flush alongside the backfilled
    # history — the next record, not a rewrite, in the same append-only log.
    store = KlineStore(staging)
    worker = KlineWorker(
        store, lambda: payload(candle(open="61235.00")), clock=lambda: T0
    )
    cycle = worker.run_cycle()
    assert cycle.rows_written == 1

    # The log is now the backfill page (seq 1) plus the live flush (seq 2):
    # two distinct records, gap-free, with the backfilled bytes untouched.
    records = KlineStore(staging).records()
    assert [r.sequence for r in records] == [1, 2]
    assert records[0].sequence == backfilled.sequence
    assert records[0].source_sha256 == backfilled.source_sha256
    assert records[1].row_count == 1


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
