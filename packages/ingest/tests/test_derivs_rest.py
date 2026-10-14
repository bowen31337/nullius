"""``--source rest``: funding and futbars backfilled from Binance's live
USD-M REST API, so a lake can be staged through yesterday rather than
through the last published monthly archive file.

``additions_spec_derivs_rest.xml`` feature 1, read as behaviour of
:mod:`nullius_ingest.derivs_backfill`'s ``--source rest`` path:

* only ``funding`` and ``futbars`` are allowed under ``rest`` -- ``metrics``
  is refused with a clear error, at both the library and the CLI door;
* the spot-to-UM symbol mapping resolves against ``GET /fapi/v1/exchangeInfo``'s
  ``symbols`` list, through the same ``SCALE_PREFIX`` rule the archive crawl
  uses, not the archive at all;
* funding pages ``GET /fapi/v1/fundingRate`` by ``startTime``/``endTime``,
  advancing by the previous page's last ``fundingTime + 1``, and floors each
  ``fundingTime`` to the whole second before bucketing it, so a settlement
  reported 1 ms past a day boundary lands exactly where the archive's own
  (whole-second) ``calc_time`` would;
* futbars pages ``GET /fapi/v1/klines`` the same way, rescales by the
  symbol's scale factor exactly as the archive path does, and never writes a
  candle whose close time has not happened yet (today's open candle);
* a day built from REST settlements/candles is byte-for-byte what the
  archive path writes for the same settlements/candles;
* a 418/429 is retried with backoff (reusing bars_backfill's own retry
  plumbing); any other HTTP failure, or a 429/418 that persists past the
  retry bound, fails that (stream, symbol) job, counted in the summary
  line's ``failed``.

Fixture provenance: ``fixtures/derivs_rest/rest_responses.json`` carries one
recorded-shaped ``exchangeInfo`` listing, one three-settlement ``fundingRate``
sample (the exact ``fundingTime`` the spec's own verified-shape note cites,
1791936000001 -- 1 ms past a UTC midnight) and one ``klines`` candle, reused
by the parity tests below to build the identical scenario through the
archive path. No test here makes a network call: every fetch is a recorded,
in-memory callable, and every test uses its own ``tmp_path`` lake, so the
suite passes under pytest-xdist.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import nullius_ingest.derivs_backfill as derivs_backfill_module
import pyarrow.parquet as pq
import pytest
from nullius_ingest.bars_backfill import HttpResponse
from nullius_ingest.derivs_backfill import (
    SOURCE_REST,
    DerivsBackfillError,
    backfill_derivs,
    main,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "derivs_rest" / "rest_responses.json").read_text(
        encoding="utf-8"
    )
)

ARCHIVE_BASE_URL = "https://data.binance.vision"
ARCHIVE_LISTING_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


def _no_sleep(_seconds: float) -> None:
    pass


def _ms(instant: datetime) -> int:
    return int(instant.timestamp() * 1000)


def _write_universe(tmp_path: Path, symbols: Sequence[str]) -> Path:
    path = tmp_path / "universe.json"
    path.write_text(json.dumps({"symbols": list(symbols)}), encoding="utf-8")
    return path


def _read_parquet(lake: Path, stream: str, symbol: str, day: date) -> dict[str, object]:
    path = lake / "staging" / stream / f"symbol={symbol}" / f"date={day.isoformat()}" / "part-0.parquet"
    table = pq.read_table(path)
    row = table.to_pylist()
    assert len(row) == 1, f"expected exactly one row at {path}, got {len(row)}"
    return row[0]


def _partition_exists(lake: Path, stream: str, symbol: str, day: date) -> bool:
    return (
        lake / "staging" / stream / f"symbol={symbol}" / f"date={day.isoformat()}" / "part-0.parquet"
    ).is_file()


# -- The injected REST fetch: recorded JSON, keyed by path and call order ----


class FakeRest:
    """An injected :data:`~nullius_ingest.bars_backfill.BinanceFetch`.

    ``exchange_info`` answers ``/exchangeInfo`` once, every call.
    ``funding_pages``/``kline_pages`` map a UM symbol to its scripted list of
    pages -- one page consumed per call to ``/fundingRate``/``/klines`` for
    that symbol, in order; a call past the last scripted page answers an
    empty list (an exhausted, honestly-quiet page). Every call is recorded
    in :attr:`calls`.
    """

    def __init__(
        self,
        *,
        exchange_info: Mapping[str, object],
        funding_pages: Mapping[str, Sequence[list]] | None = None,
        kline_pages: Mapping[str, Sequence[list]] | None = None,
    ) -> None:
        self.exchange_info = exchange_info
        self.funding_pages = {symbol: list(pages) for symbol, pages in (funding_pages or {}).items()}
        self.kline_pages = {symbol: list(pages) for symbol, pages in (kline_pages or {}).items()}
        self._funding_index: dict[str, int] = {}
        self._kline_index: dict[str, int] = {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, params: Mapping[str, str]) -> HttpResponse:
        self.calls.append((path, dict(params)))
        if path == "/exchangeInfo":
            return HttpResponse(200, {}, json.dumps(self.exchange_info).encode("utf-8"))
        if path == "/fundingRate":
            symbol = params["symbol"]
            index = self._funding_index.get(symbol, 0)
            pages = self.funding_pages.get(symbol, [])
            page = pages[index] if index < len(pages) else []
            self._funding_index[symbol] = index + 1
            return HttpResponse(200, {}, json.dumps(page).encode("utf-8"))
        if path == "/klines":
            symbol = params["symbol"]
            index = self._kline_index.get(symbol, 0)
            pages = self.kline_pages.get(symbol, [])
            page = pages[index] if index < len(pages) else []
            self._kline_index[symbol] = index + 1
            return HttpResponse(200, {}, json.dumps(page).encode("utf-8"))
        raise AssertionError(f"unexpected path {path!r}")


# -- The injected archive fetch, for the "built both ways" parity tests -----


def _make_zip(csv_rows: Sequence[Sequence[str]]) -> tuple[bytes, bytes]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in csv_rows:
        writer.writerow(row)
    csv_bytes = buffer.getvalue().encode("utf-8")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as bundle:
        bundle.writestr("data.csv", csv_bytes)
    zip_bytes = zip_buffer.getvalue()
    digest = hashlib.sha256(zip_bytes).hexdigest()
    checksum_bytes = f"{digest}  data.csv\n".encode()
    return zip_bytes, checksum_bytes


class FakeArchive:
    """A minimal injected ArchiveFetch -- one UM symbol, one monthly file.

    Mirrors ``test_derivs_backfill.py``'s own fixture class, duplicated here
    (rather than cross-imported) so this file stands alone.
    """

    def __init__(self, *, listing_symbol: str, files: Mapping[str, bytes]) -> None:
        self.listing_keys = [
            f"data/futures/um/monthly/klines/{listing_symbol}/1d/{listing_symbol}-1d-2023-01.zip"
        ]
        self.files = dict(files)

    def __call__(self, url: str) -> HttpResponse:
        if url.startswith(ARCHIVE_LISTING_URL):
            contents = "".join(f"<Contents><Key>{key}</Key></Contents>" for key in self.listing_keys)
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                f"{contents}<IsTruncated>false</IsTruncated></ListBucketResult>"
            ).encode()
            return HttpResponse(200, {}, body)
        body = self.files.get(url)
        if body is None:
            return HttpResponse(404, {}, b"not found")
        return HttpResponse(200, {}, body)


def _funding_url(symbol: str, month: str) -> str:
    return f"{ARCHIVE_BASE_URL}/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"


def _futbars_url(symbol: str, month: str) -> str:
    return f"{ARCHIVE_BASE_URL}/data/futures/um/monthly/klines/{symbol}/1d/{symbol}-1d-{month}.zip"


# -- 1. only funding and futbars are allowed under rest; metrics is refused --


def test_metrics_is_refused_under_rest(tmp_path: Path) -> None:
    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])

    with pytest.raises(DerivsBackfillError, match="metrics"):
        backfill_derivs(
            tmp_path / "lake", "2026-01-01", "2026-01-01",
            symbols_from=symbols_path, streams=["funding", "futbars", "metrics"],
            source="rest", sleep=_no_sleep,
        )


def test_main_refuses_metrics_under_rest_with_exit_code_and_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])

    exit_code = main(
        [
            "--lake", str(tmp_path / "lake"),
            "--first", "2026-01-01",
            "--last", "2026-01-01",
            "--symbols-from", str(symbols_path),
            "--streams", "metrics",
            "--source", "rest",
        ],
        sleep=_no_sleep,
    )

    assert exit_code == 1
    assert "metrics" in capsys.readouterr().err


# -- 2. symbol mapping resolves via exchangeInfo, not the archive crawl -------


def test_symbol_mapping_resolves_via_exchange_info_not_the_archive(tmp_path: Path) -> None:
    fetch = FakeRest(exchange_info=_FIXTURE["exchange_info"], funding_pages={}, kline_pages={})
    symbols_path = _write_universe(tmp_path, ["BTCUSDT", "PEPEUSDT", "NOPERPUSDT"])
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, "2026-01-01", "2026-01-01",
        symbols_from=symbols_path, streams=["funding"], source="rest",
        fetch=fetch, sleep=_no_sleep,
    )

    exchange_info_calls = [call for call in fetch.calls if call[0] == "/exchangeInfo"]
    assert len(exchange_info_calls) == 1

    by_symbol = {r.symbol: r for r in results}
    assert by_symbol["BTCUSDT"].status == "ok"
    assert by_symbol["PEPEUSDT"].status == "ok"
    assert by_symbol["NOPERPUSDT"].status == "skipped"

    symbol_map = json.loads((lake / "staging-meta" / "um-symbol-map.json").read_text())
    assert symbol_map["BTCUSDT"] == {"um_symbol": "BTCUSDT", "scale": 1}
    assert symbol_map["PEPEUSDT"] == {"um_symbol": "1000PEPEUSDT", "scale": 1000}
    assert symbol_map["NOPERPUSDT"] == {"um_symbol": None, "scale": None}


# -- 3. funding: pagination, the +1 ms bucketing rule, and archive parity ----


def test_funding_rest_pagination_advances_by_last_funding_time_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(derivs_backfill_module, "FUNDING_REST_PAGE_LIMIT", 2)

    page1 = [
        {"symbol": "BTCUSDT", "fundingTime": _ms(datetime(2026, 2, 1, 8, 0, tzinfo=UTC)), "fundingRate": "0.00010000", "markPrice": "1", "rateType": ""},
        {"symbol": "BTCUSDT", "fundingTime": _ms(datetime(2026, 2, 1, 16, 0, tzinfo=UTC)), "fundingRate": "0.00005000", "markPrice": "1", "rateType": ""},
    ]
    page2 = [
        {"symbol": "BTCUSDT", "fundingTime": _ms(datetime(2026, 2, 2, 0, 0, tzinfo=UTC)), "fundingRate": "-0.00002000", "markPrice": "1", "rateType": ""},
    ]
    fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "BTCUSDT"}]},
        funding_pages={"BTCUSDT": [page1, page2]},
    )
    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, "2026-02-01", "2026-02-01",
        symbols_from=symbols_path, streams=["funding"], source="rest",
        fetch=fetch, sleep=_no_sleep,
    )

    funding_calls = [call for call in fetch.calls if call[0] == "/fundingRate"]
    assert len(funding_calls) == 2, "a full first page (== the limit) must trigger a second request"
    assert int(funding_calls[1][1]["startTime"]) == page1[-1]["fundingTime"] + 1, (
        "the second page must start exactly where the first page's last fundingTime left off"
    )

    [result] = results
    assert result.status == "ok"
    row = _read_parquet(lake, "funding", "BTCUSDT", date(2026, 2, 1))
    # All three settlements -- two from page 1, one from page 2 -- land on
    # the same day: the third is exactly D+1 00:00, which the day-boundary
    # rule credits back to D.
    assert row["n_settlements"] == 3
    assert row["funding_rate_sum"] == "0.00013000"
    assert row["funding_rate_last"] == "-0.00002000"


def test_funding_rest_matches_archive_including_plus_one_ms_bucketing(tmp_path: Path) -> None:
    sample = _FIXTURE["funding_btcusdt_sample"]
    rest_fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "BTCUSDT"}]},
        funding_pages={"BTCUSDT": [sample]},
    )
    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])
    rest_lake = tmp_path / "lake_rest"

    rest_results = backfill_derivs(
        rest_lake, "2026-10-13", "2026-10-13",
        symbols_from=symbols_path, streams=["funding"], source="rest",
        fetch=rest_fetch, sleep=_no_sleep,
    )
    assert rest_results[0].status == "ok"
    rest_row = _read_parquet(rest_lake, "funding", "BTCUSDT", date(2026, 10, 13))

    # The archive's own calc_time is already whole-second -- the REST
    # sample's third settlement is the live venue's "+1 ms" artifact over
    # the very same instant (1791936000001 vs. 1791936000000).
    archive_rows = [
        ["calc_time", "funding_interval_hours", "last_funding_rate"],
        *[[str(entry["fundingTime"] - (1 if idx == 2 else 0)), "8", entry["fundingRate"]] for idx, entry in enumerate(sample)],
    ]
    zip_bytes, checksum_bytes = _make_zip(archive_rows)
    archive_fetch = FakeArchive(
        listing_symbol="BTCUSDT",
        files={
            _funding_url("BTCUSDT", "2026-10"): zip_bytes,
            _funding_url("BTCUSDT", "2026-10") + ".CHECKSUM": checksum_bytes,
        },
    )
    archive_lake = tmp_path / "lake_archive"

    archive_results = backfill_derivs(
        archive_lake, "2026-10-13", "2026-10-13",
        symbols_from=symbols_path, streams=["funding"], source="archive",
        fetch=archive_fetch, sleep=_no_sleep,
    )
    assert archive_results[0].status == "ok"
    archive_row = _read_parquet(archive_lake, "funding", "BTCUSDT", date(2026, 10, 13))

    assert rest_row == archive_row
    assert rest_row["n_settlements"] == 3
    assert rest_row["funding_rate_sum"] == "0.00011596"
    assert rest_row["funding_rate_last"] == "0.00001025"


# -- 4. futbars: pagination, the open candle, rescaling, and archive parity --


def _rest_candle(day: date, close: str, *, trades: int = 10) -> list:
    open_ms = _ms(datetime.combine(day, datetime.min.time(), tzinfo=UTC))
    close_ms = open_ms + 86_400_000 - 1
    return [open_ms, "100.0", "110.0", "90.0", close, "1000.0", close_ms, "100000.0", trades, "400.0", "40000.0", "0"]


def test_futbars_rest_pagination_advances_by_last_open_time_plus_one_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(derivs_backfill_module, "FUTBARS_REST_PAGE_LIMIT", 2)

    page1 = [_rest_candle(date(2026, 3, 1), "100.0"), _rest_candle(date(2026, 3, 2), "101.0")]
    page2 = [_rest_candle(date(2026, 3, 3), "102.0")]
    fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "BTCUSDT"}]},
        kline_pages={"BTCUSDT": [page1, page2]},
    )
    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, "2026-03-01", "2026-03-03",
        symbols_from=symbols_path, streams=["futbars"], source="rest",
        fetch=fetch, sleep=_no_sleep, clock=lambda: datetime(2026, 3, 10, tzinfo=UTC),
    )

    kline_calls = [call for call in fetch.calls if call[0] == "/klines"]
    assert len(kline_calls) == 2, "a full first page (== the limit) must trigger a second request"
    assert int(kline_calls[1][1]["startTime"]) == page1[-1][0] + 86_400_000, (
        "the second page must start the day after the first page's last open time"
    )

    [result] = results
    assert result.status == "ok"
    assert result.rows_written == 3
    assert _read_parquet(lake, "futbars", "BTCUSDT", date(2026, 3, 3))["fut_close"] == "102.0"


def test_futbars_rest_open_candle_is_never_written(tmp_path: Path) -> None:
    closed = _rest_candle(date(2026, 5, 9), "105.0")
    still_open = _rest_candle(date(2026, 5, 10), "107.0")  # today -- not yet closed
    fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "BTCUSDT"}]},
        kline_pages={"BTCUSDT": [[closed, still_open]]},
    )
    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])
    lake = tmp_path / "lake"

    # "Now" is midday on the 10th: that day's own candle has not closed yet.
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    results = backfill_derivs(
        lake, "2026-05-09", "2026-05-10",
        symbols_from=symbols_path, streams=["futbars"], source="rest",
        fetch=fetch, sleep=_no_sleep, clock=lambda: now,
    )

    [result] = results
    assert result.status == "ok"
    assert result.rows_written == 1
    assert _partition_exists(lake, "futbars", "BTCUSDT", date(2026, 5, 9))
    assert not _partition_exists(lake, "futbars", "BTCUSDT", date(2026, 5, 10))


def test_futbars_rest_matches_archive_and_rescales_the_1000_contract(tmp_path: Path) -> None:
    entry = _FIXTURE["klines_1000pepeusdt_sample"][0]
    rest_fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "1000PEPEUSDT"}]},
        kline_pages={"1000PEPEUSDT": [[entry]]},
    )
    symbols_path = _write_universe(tmp_path, ["PEPEUSDT"])
    rest_lake = tmp_path / "lake_rest"
    now = datetime(2024, 5, 15, tzinfo=UTC)  # well after the candle's own close

    rest_results = backfill_derivs(
        rest_lake, "2024-05-08", "2024-05-08",
        symbols_from=symbols_path, streams=["futbars"], source="rest",
        fetch=rest_fetch, sleep=_no_sleep, clock=lambda: now,
    )
    assert rest_results[0].status == "ok"
    rest_row = _read_parquet(rest_lake, "futbars", "PEPEUSDT", date(2024, 5, 8))

    # The 1000-scale rescale this test is pinned on: the raw close divided
    # by 1000, the raw volumes multiplied by 1000, quote_volume unchanged.
    assert rest_row["fut_close"] == "0.00000001256"
    assert rest_row["fut_volume"] == "123456789012000"
    assert rest_row["taker_buy_volume"] == "61728394506000"
    assert rest_row["quote_volume"] == entry[7]

    # The archive's CSV row is this same candle, in the archive's own
    # string-column shape -- exactly what the REST row builder also feeds
    # _parse_futbars_rows, field for field.
    archive_header = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore",
    ]
    archive_rows = [archive_header, [str(value) for value in entry]]
    zip_bytes, checksum_bytes = _make_zip(archive_rows)
    archive_fetch = FakeArchive(
        listing_symbol="1000PEPEUSDT",
        files={
            _futbars_url("1000PEPEUSDT", "2024-05"): zip_bytes,
            _futbars_url("1000PEPEUSDT", "2024-05") + ".CHECKSUM": checksum_bytes,
        },
    )
    archive_lake = tmp_path / "lake_archive"

    archive_results = backfill_derivs(
        archive_lake, "2024-05-08", "2024-05-08",
        symbols_from=symbols_path, streams=["futbars"], source="archive",
        fetch=archive_fetch, sleep=_no_sleep,
    )
    assert archive_results[0].status == "ok"
    archive_row = _read_parquet(archive_lake, "futbars", "PEPEUSDT", date(2024, 5, 8))

    assert rest_row == archive_row


# -- 5. a 429/418 is retried with backoff; past the bound, it fails the job --


def test_a_429_then_success_retries_with_backoff(tmp_path: Path) -> None:
    attempts = {"n": 0}
    sleeps: list[float] = []

    def fetch(path: str, params: Mapping[str, str]) -> HttpResponse:
        if path == "/exchangeInfo":
            return HttpResponse(200, {}, json.dumps({"symbols": [{"symbol": "BTCUSDT"}]}).encode())
        if path == "/fundingRate":
            attempts["n"] += 1
            if attempts["n"] == 1:
                return HttpResponse(429, {"Retry-After": "2"}, b"rate limited")
            return HttpResponse(200, {}, json.dumps([]).encode())
        raise AssertionError(f"unexpected path {path!r}")

    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])
    results = backfill_derivs(
        tmp_path / "lake", "2026-01-01", "2026-01-01",
        symbols_from=symbols_path, streams=["funding"], source="rest",
        fetch=fetch, sleep=sleeps.append,
    )

    assert attempts["n"] == 2
    assert results[0].status == "ok"
    assert 2.0 in sleeps


def test_429_past_the_retry_bound_fails_that_symbols_job(tmp_path: Path) -> None:
    def fetch(path: str, params: Mapping[str, str]) -> HttpResponse:
        if path == "/exchangeInfo":
            return HttpResponse(200, {}, json.dumps({"symbols": [{"symbol": "BTCUSDT"}]}).encode())
        return HttpResponse(429, {"Retry-After": "0"}, b"rate limited")

    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])
    lines: list[str] = []
    exit_code = main(
        [
            "--lake", str(tmp_path / "lake"),
            "--first", "2026-01-01",
            "--last", "2026-01-01",
            "--symbols-from", str(symbols_path),
            "--streams", "funding",
            "--source", "rest",
        ],
        emit=lines.append,
        fetch=fetch,
        sleep=_no_sleep,
    )

    assert exit_code == 1
    result_lines = [json.loads(line) for line in lines if "status" in json.loads(line)]
    assert result_lines[0]["status"] == "error"
    summary = json.loads(lines[-1])
    assert summary["failed"] == 1


def test_a_418_also_retries_with_backoff(tmp_path: Path) -> None:
    attempts = {"n": 0}

    def fetch(path: str, params: Mapping[str, str]) -> HttpResponse:
        if path == "/exchangeInfo":
            return HttpResponse(200, {}, json.dumps({"symbols": [{"symbol": "BTCUSDT"}]}).encode())
        if path == "/klines":
            attempts["n"] += 1
            if attempts["n"] == 1:
                return HttpResponse(418, {"Retry-After": "0"}, b"teapot")
            return HttpResponse(200, {}, json.dumps([]).encode())
        raise AssertionError(f"unexpected path {path!r}")

    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])
    results = backfill_derivs(
        tmp_path / "lake", "2026-01-01", "2026-01-01",
        symbols_from=symbols_path, streams=["futbars"], source="rest",
        fetch=fetch, sleep=_no_sleep, clock=lambda: datetime(2026, 1, 5, tzinfo=UTC),
    )

    assert attempts["n"] == 2
    assert results[0].status == "ok"


def test_a_non_retryable_http_error_fails_the_symbols_job_not_retried(tmp_path: Path) -> None:
    # Distinct from the 418/429 retry path above: a plain error status (here
    # 500) is never retried at all, and immediately fails that (stream,
    # symbol) job -- counted in the summary line's "failed", exactly as a
    # 429 persisting past the retry bound is.
    attempts = {"n": 0}

    def fetch(path: str, params: Mapping[str, str]) -> HttpResponse:
        if path == "/exchangeInfo":
            return HttpResponse(200, {}, json.dumps({"symbols": [{"symbol": "BTCUSDT"}]}).encode())
        if path == "/fundingRate":
            attempts["n"] += 1
            return HttpResponse(500, {}, b"internal error")
        raise AssertionError(f"unexpected path {path!r}")

    symbols_path = _write_universe(tmp_path, ["BTCUSDT"])
    lines: list[str] = []
    exit_code = main(
        [
            "--lake", str(tmp_path / "lake"),
            "--first", "2026-01-01",
            "--last", "2026-01-01",
            "--symbols-from", str(symbols_path),
            "--streams", "funding",
            "--source", "rest",
        ],
        emit=lines.append,
        fetch=fetch,
        sleep=_no_sleep,
    )

    assert attempts["n"] == 1, "a non-retryable status must not be retried"
    assert exit_code == 1
    result_lines = [json.loads(line) for line in lines if "status" in json.loads(line)]
    assert result_lines[0]["status"] == "error"
    assert "500" in result_lines[0]["error"]
    summary = json.loads(lines[-1])
    assert summary["failed"] == 1
    assert not _partition_exists(tmp_path / "lake", "funding", "BTCUSDT", date(2026, 1, 1))


def test_archive_source_is_unchanged_default(tmp_path: Path) -> None:
    # SOURCE_REST is not the default; a caller naming neither --source still
    # gets the archive path (proved elsewhere, but pinned here as this
    # module's own contract).
    import inspect

    assert inspect.signature(backfill_derivs).parameters["source"].default != SOURCE_REST
