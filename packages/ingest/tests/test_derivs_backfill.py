"""USD-M futures derivatives backfilled into point-in-time daily lake streams.

``additions_spec_derivatives_inputs.xml``: *System backfills USD-M futures
funding rates, futures daily klines and daily open-interest metrics from the
free archive into point-in-time daily lake streams*, read as behaviour of
:mod:`nullius_ingest.derivs_backfill`.

**Fixture provenance.** ``tests/fixtures/binance_archive_um/`` pins five real
files downloaded from Binance's public data archive (``https://data.binance.vision``,
no API key, no auth) on 2026-10-12, each with the ``.CHECKSUM`` sidecar the
archive itself publishes next to it:

* ``BTCUSDT-fundingRate-2020-01.zip`` —
  ``data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2020-01.zip``
* ``BTCUSDT-1d-2020-01.zip`` —
  ``data/futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip``
* ``1000PEPEUSDT-fundingRate-2023-05.zip`` —
  ``data/futures/um/monthly/fundingRate/1000PEPEUSDT/1000PEPEUSDT-fundingRate-2023-05.zip``
* ``1000PEPEUSDT-1d-2023-05.zip`` —
  ``data/futures/um/monthly/klines/1000PEPEUSDT/1d/1000PEPEUSDT-1d-2023-05.zip``
* ``BTCUSDT-metrics-2021-01-01.zip`` —
  ``data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2021-01-01.zip``

Every test checks a pinned file's checksum before trusting its bytes. A
handful of tests below also build a small CSV and zip it in memory (never
downloaded, never claiming to be an archive file) for cases no real file
conveniently demonstrates: a millisecond/microsecond unit mix on a made-up
symbol, a metrics day with a trailing boundary row, and a deliberately
wrong ``.CHECKSUM``.

Covers:

* the funding day-boundary rule (``(D 00:00, D+1 00:00]``), including a
  settlement timestamped exactly at a day's own midnight rolling back to the
  previous day, and the mirror case — a settlement at ``D+1 00:00`` crediting
  back to ``D``;
* the ``1000``-scale symbol mapping and the futures-to-spot price rescale,
  plus a symbol with no UM perpetual producing no rows;
* the metrics last-snapshot rule and the dropped trailing row stamped at the
  next day's midnight;
* millisecond and microsecond ``calc_time``/``open_time`` inputs;
* resume without refetching an already-written month;
* a checksum mismatch that skips the month, reports it, and exits 1;
* spot bars backfill is unaffected by parametrizing the shared archive
  helpers bars_backfill.py and this module both call.

No network: every fetch is a recorded, in-memory callable. Every test uses
its own ``tmp_path`` lake, so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from nullius_ingest.bars_backfill import ARCHIVE_LISTING_URL, HttpResponse
from nullius_ingest.bars_backfill import backfill_bars as spot_backfill_bars
from nullius_ingest.derivs_backfill import (
    DerivsBackfillError,
    backfill_derivs,
    main,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "binance_archive_um"
_SPOT_FIXTURES = Path(__file__).parent / "fixtures" / "binance_archive"

ARCHIVE_BASE_URL = "https://data.binance.vision"


def _no_sleep(_seconds: float) -> None:
    pass


# -- Loading and verifying the pinned fixtures --------------------------------


def _verify_and_read(zip_name: str) -> tuple[bytes, bytes]:
    """``(zip_bytes, checksum_bytes)`` for a pinned fixture, checksum verified."""
    zip_path = _FIXTURES / zip_name
    checksum_path = _FIXTURES / f"{zip_name}.CHECKSUM"
    zip_bytes = zip_path.read_bytes()
    checksum_bytes = checksum_path.read_bytes()
    expected = checksum_bytes.decode("utf-8").split()[0]
    actual = hashlib.sha256(zip_bytes).hexdigest()
    assert actual == expected, (
        f"{zip_name} does not match its pinned .CHECKSUM; refusing to trust its bytes"
    )
    return zip_bytes, checksum_bytes


# -- Building synthetic in-memory CSV zips for the edge cases -----------------


def _make_zip(csv_rows: Sequence[Sequence[str]]) -> tuple[bytes, bytes]:
    """A one-member zip of ``csv_rows`` and its sha256 ``.CHECKSUM`` line."""
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


# -- The fake archive: one URL-keyed fetch, with a call counter --------------


def _s3_listing_xml(keys: Sequence[str]) -> bytes:
    contents = "".join(f"<Contents><Key>{key}</Key></Contents>" for key in keys)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"{contents}"
        "<IsTruncated>false</IsTruncated>"
        "</ListBucketResult>"
    ).encode()


class FakeArchive:
    """An injected :data:`~nullius_ingest.bars_backfill.ArchiveFetch`.

    ``listing_symbols`` answers the UM symbol discovery crawl (every one of
    them reported as owning a klines archive, which is all discovery looks
    at). ``files`` maps an exact URL to the bytes it returns (status 200);
    any other URL -- including a month or day this module never provided a
    zip for -- answers 404, exactly as the real archive would for a period
    it never published. Every call is recorded in :attr:`calls`, so a test
    can assert a resumed run made none.
    """

    def __init__(self, *, listing_symbols: Sequence[str], files: Mapping[str, bytes]):
        self.listing_keys = [
            f"data/futures/um/monthly/klines/{symbol}/1d/{symbol}-1d-2023-01.zip"
            for symbol in listing_symbols
        ]
        self.files = dict(files)
        self.calls: list[str] = []

    def __call__(self, url: str) -> HttpResponse:
        self.calls.append(url)
        if url.startswith(ARCHIVE_LISTING_URL):
            return HttpResponse(status=200, headers={}, body=_s3_listing_xml(self.listing_keys))
        body = self.files.get(url)
        if body is None:
            return HttpResponse(status=404, headers={}, body=b"not found")
        return HttpResponse(status=200, headers={}, body=body)


def _url(prefix: str, symbol: str, filename: str, *, subdir: str | None = None) -> str:
    parts = [prefix.strip("/"), symbol]
    if subdir:
        parts.append(subdir)
    parts.append(filename)
    return f"{ARCHIVE_BASE_URL}/" + "/".join(parts)


def _funding_url(symbol: str, month: str) -> str:
    return _url("data/futures/um/monthly/fundingRate/", symbol, f"{symbol}-fundingRate-{month}.zip")


def _futbars_url(symbol: str, month: str) -> str:
    return _url(
        "data/futures/um/monthly/klines/", symbol, f"{symbol}-1d-{month}.zip", subdir="1d"
    )


def _metrics_url(symbol: str, day: str) -> str:
    return _url("data/futures/um/daily/metrics/", symbol, f"{symbol}-metrics-{day}.zip")


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


# -- 1. the funding day-boundary rule, including the D+1 00:00 settlement ----


def test_funding_day_boundary_rule_including_the_d_plus_one_midnight_settlement(
    tmp_path: Path,
) -> None:
    zip_bytes, checksum_bytes = _verify_and_read("BTCUSDT-fundingRate-2020-01.zip")
    fetch = FakeArchive(
        listing_symbols=["BTCUSDT"],
        files={
            _funding_url("BTCUSDT", "2020-01"): zip_bytes,
            _funding_url("BTCUSDT", "2020-01") + ".CHECKSUM": checksum_bytes,
        },
    )
    symbols_path = tmp_path / "universe.json"
    symbols_path.write_text(json.dumps({"symbols": ["BTCUSDT"]}), encoding="utf-8")
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, "2020-01-01", "2020-01-03",
        symbols_from=symbols_path, streams=["funding"],
        fetch=fetch, sleep=_no_sleep,
    )

    [result] = results
    assert result.stream == "funding"
    assert result.symbol == "BTCUSDT"
    assert result.status == "ok"
    assert result.rows_written == 3

    # 2020-01-01's own settlement at exactly 00:00:00 rolls back to
    # 2019-12-31 (outside the window) -- only the 08:00 and 16:00
    # settlements are its own.
    day1 = _read_parquet(lake, "funding", "BTCUSDT", date(2020, 1, 1))
    assert day1["n_settlements"] == 2
    assert day1["funding_rate_sum"] == "-0.00022047"
    assert day1["funding_rate_last"] == "-0.00009664"

    # 2020-01-02 picks up its own 00:00:00.002, 08:00 and 16:00 settlements
    # *plus* 2020-01-03's settlement at exactly 00:00:00 -- the explicit
    # "a settlement at D+1 00:00 belongs to D" rule -- for four, not three.
    day2 = _read_parquet(lake, "funding", "BTCUSDT", date(2020, 1, 2))
    assert day2["n_settlements"] == 4
    assert day2["funding_rate_sum"] == "0.00012102"
    assert day2["funding_rate_last"] == "-0.00001664"

    # 2020-01-03 lost its own midnight settlement to 2020-01-02 above, but
    # gains 2020-01-04's exact-midnight settlement the same way -- its own
    # 08:00 and 16:00, plus 2020-01-04T00:00:00.
    day3 = _read_parquet(lake, "funding", "BTCUSDT", date(2020, 1, 3))
    assert day3["n_settlements"] == 3
    assert day3["funding_rate_sum"] == "0.00018447"
    assert day3["funding_rate_last"] == "0.00010000"

    # The funding rate columns are verbatim/computed strings; the count is
    # an integer, matching bars_backfill's own trade_count convention.
    assert isinstance(day1["n_settlements"], int)
    assert isinstance(day1["funding_rate_sum"], str)


# -- 2. the 1000-scale mapping, the price rescale, and no perpetual ----------


def test_scaled_symbol_maps_to_1000_prefix_and_rescales_the_futures_price(
    tmp_path: Path,
) -> None:
    pepe_funding_zip, pepe_funding_checksum = _verify_and_read("1000PEPEUSDT-fundingRate-2023-05.zip")
    pepe_bars_zip, pepe_bars_checksum = _verify_and_read("1000PEPEUSDT-1d-2023-05.zip")
    fetch = FakeArchive(
        listing_symbols=["BTCUSDT", "1000PEPEUSDT"],  # NOPERPUSDT deliberately absent
        files={
            _funding_url("1000PEPEUSDT", "2023-05"): pepe_funding_zip,
            _funding_url("1000PEPEUSDT", "2023-05") + ".CHECKSUM": pepe_funding_checksum,
            _futbars_url("1000PEPEUSDT", "2023-05"): pepe_bars_zip,
            _futbars_url("1000PEPEUSDT", "2023-05") + ".CHECKSUM": pepe_bars_checksum,
        },
    )
    symbols_path = tmp_path / "universe.json"
    symbols_path.write_text(
        json.dumps({"symbols": ["BTCUSDT", "PEPEUSDT", "NOPERPUSDT"]}), encoding="utf-8"
    )
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, "2023-05-05", "2023-05-05",
        symbols_from=symbols_path, streams=["funding", "futbars"],
        fetch=fetch, sleep=_no_sleep,
    )

    by_key = {(r.stream, r.symbol): r for r in results}

    # PEPEUSDT maps to 1000PEPEUSDT and backfills under the *spot* symbol name.
    assert by_key[("futbars", "PEPEUSDT")].status == "ok"
    assert by_key[("futbars", "PEPEUSDT")].rows_written == 1
    row = _read_parquet(lake, "futbars", "PEPEUSDT", date(2023, 5, 5))
    assert row["fut_close"] == "0.0000037211"  # raw close 0.0037211 / 1000
    assert row["fut_volume"] == "305546741233000"  # raw volume 305546741233 * 1000
    assert row["taker_buy_volume"] == "153171587348000"  # raw 153171587348 * 1000
    assert row["quote_volume"] == "1050677790.0751307"  # unchanged: already USDT

    # fut_close and fut_volume are exact inverse rescales of the same factor,
    # so their product is unchanged by the scale -- close * volume in
    # contract units equals close * volume in the rescaled, spot-equivalent
    # units.
    raw_product = Decimal("0.0037211") * Decimal(305546741233)
    rescaled_product = Decimal(row["fut_close"]) * Decimal(row["fut_volume"])
    assert rescaled_product == raw_product

    assert by_key[("funding", "PEPEUSDT")].status == "ok"

    # BTCUSDT has no fixture for this window but its mapping (scale 1, no
    # rescale) is still recorded -- a quiet, zero-row "ok", not an error.
    assert by_key[("futbars", "BTCUSDT")].status == "ok"
    assert by_key[("futbars", "BTCUSDT")].rows_written == 0
    assert not _partition_exists(lake, "futbars", "BTCUSDT", date(2023, 5, 5))

    # NOPERPUSDT has no UM perpetual at all: one skipped result, no rows,
    # for neither stream.
    skipped = [r for r in results if r.symbol == "NOPERPUSDT"]
    assert len(skipped) == 1
    assert skipped[0].status == "skipped"
    assert not _partition_exists(lake, "futbars", "NOPERPUSDT", date(2023, 5, 5))

    symbol_map = json.loads((lake / "staging-meta" / "um-symbol-map.json").read_text())
    assert symbol_map["PEPEUSDT"] == {"um_symbol": "1000PEPEUSDT", "scale": 1000}
    assert symbol_map["BTCUSDT"] == {"um_symbol": "BTCUSDT", "scale": 1}
    assert symbol_map["NOPERPUSDT"] == {"um_symbol": None, "scale": None}


# -- 3. the metrics last-snapshot rule ---------------------------------------


def test_metrics_builds_a_row_from_the_last_snapshot_before_midnight(tmp_path: Path) -> None:
    zip_bytes, checksum_bytes = _verify_and_read("BTCUSDT-metrics-2021-01-01.zip")
    fetch = FakeArchive(
        listing_symbols=["BTCUSDT"],
        files={
            _metrics_url("BTCUSDT", "2021-01-01"): zip_bytes,
            _metrics_url("BTCUSDT", "2021-01-01") + ".CHECKSUM": checksum_bytes,
        },
    )
    symbols_path = tmp_path / "universe.json"
    symbols_path.write_text(json.dumps({"symbols": ["BTCUSDT"]}), encoding="utf-8")
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, "2021-01-01", "2021-01-01",
        symbols_from=symbols_path, streams=["metrics"],
        fetch=fetch, sleep=_no_sleep,
    )

    [result] = results
    assert result.status == "ok"
    assert result.rows_written == 1

    row = _read_parquet(lake, "metrics", "BTCUSDT", date(2021, 1, 1))
    # The archive's own last 23:55:00 row for this (real, un-truncated) day.
    assert row["sum_open_interest"] == "36157.80900000"
    assert row["sum_open_interest_value"] == "1059723551.93661000"
    assert row["count_toptrader_long_short_ratio"] == "1.51345446"
    assert row["sum_toptrader_long_short_ratio"] == "1.18575028"
    assert row["count_long_short_ratio"] == "1.57427888"
    assert row["sum_taker_long_short_vol_ratio"] == "1.09879227"


def test_metrics_drops_a_trailing_row_stamped_the_next_midnight(tmp_path: Path) -> None:
    header = [
        "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
        "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
        "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
    ]
    rows = [
        header,
        ["2026-03-01 00:00:00", "TESTUSDT", "100", "1000", "1.1", "1.2", "1.3", "1.4"],
        ["2026-03-01 23:55:00", "TESTUSDT", "200", "2000", "2.1", "2.2", "2.3", "2.4"],
        # The trailing boundary row the venue sometimes appends -- stamped
        # exactly at the *next* day's midnight, strictly excluded.
        ["2026-03-02 00:00:00", "TESTUSDT", "999", "9999", "9.9", "9.9", "9.9", "9.9"],
    ]
    zip_bytes, checksum_bytes = _make_zip(rows)
    fetch = FakeArchive(
        listing_symbols=["TESTUSDT"],
        files={
            _metrics_url("TESTUSDT", "2026-03-01"): zip_bytes,
            _metrics_url("TESTUSDT", "2026-03-01") + ".CHECKSUM": checksum_bytes,
        },
    )
    symbols_path = tmp_path / "universe.json"
    symbols_path.write_text(json.dumps({"symbols": ["TESTUSDT"]}), encoding="utf-8")
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, "2026-03-01", "2026-03-01",
        symbols_from=symbols_path, streams=["metrics"],
        fetch=fetch, sleep=_no_sleep,
    )

    [result] = results
    assert result.status == "ok"
    assert result.rows_written == 1

    row = _read_parquet(lake, "metrics", "TESTUSDT", date(2026, 3, 1))
    assert row["sum_open_interest"] == "200"  # the 23:55:00 row, not the trailing one
    assert row["sum_open_interest_value"] == "2000"


# -- 4. ms and µs inputs -------------------------------------------------


def test_funding_and_futbars_accept_both_millisecond_and_microsecond_timestamps(
    tmp_path: Path,
) -> None:
    ms_instant = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)
    us_instant = datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC)
    calc_time_ms = str(int(ms_instant.timestamp() * 1000))
    calc_time_us = str(int(us_instant.timestamp() * 1_000_000))
    assert len(calc_time_ms) == 13  # a millisecond epoch
    assert len(calc_time_us) == 16  # a microsecond epoch

    funding_rows = [
        ["calc_time", "funding_interval_hours", "last_funding_rate"],
        [calc_time_ms, "8", "0.00010000"],
        [calc_time_us, "8", "0.00005000"],
    ]
    funding_zip, funding_checksum = _make_zip(funding_rows)

    open_instant = datetime(2026, 2, 1, tzinfo=UTC)
    open_time_us = str(int(open_instant.timestamp() * 1_000_000))
    close_time_us = str(int(open_instant.timestamp() * 1_000_000) + 86_400_000_000 - 1)
    assert len(open_time_us) == 16  # a microsecond epoch, like klines' 2025-01 switch
    futbars_rows = [
        [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "count", "taker_buy_volume",
            "taker_buy_quote_volume", "ignore",
        ],
        [
            open_time_us, "100.0", "110.0", "90.0", "105.0", "1000.0",
            close_time_us, "105000.0", "50", "400.0", "42000.0", "0",
        ],
    ]
    futbars_zip, futbars_checksum = _make_zip(futbars_rows)

    fetch = FakeArchive(
        listing_symbols=["TESTUSDT"],
        files={
            _funding_url("TESTUSDT", "2026-01"): funding_zip,
            _funding_url("TESTUSDT", "2026-01") + ".CHECKSUM": funding_checksum,
            _futbars_url("TESTUSDT", "2026-02"): futbars_zip,
            _futbars_url("TESTUSDT", "2026-02") + ".CHECKSUM": futbars_checksum,
        },
    )
    symbols_path = tmp_path / "universe.json"
    symbols_path.write_text(json.dumps({"symbols": ["TESTUSDT"]}), encoding="utf-8")
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, "2026-01-15", "2026-02-01",
        symbols_from=symbols_path, streams=["funding", "futbars"],
        fetch=fetch, sleep=_no_sleep,
    )
    assert all(r.status == "ok" for r in results)

    funding_row = _read_parquet(lake, "funding", "TESTUSDT", date(2026, 1, 15))
    assert funding_row["n_settlements"] == 2
    assert funding_row["funding_rate_sum"] == "0.00015000"
    assert funding_row["funding_rate_last"] == "0.00005000"  # the later (µs) settlement

    futbars_row = _read_parquet(lake, "futbars", "TESTUSDT", date(2026, 2, 1))
    assert futbars_row["fut_close"] == "105.0"
    assert futbars_row["fut_volume"] == "1000.0"


# -- 5. resume without refetch -------------------------------------------


def test_resume_does_not_refetch_an_already_written_month(tmp_path: Path) -> None:
    funding_zip, funding_checksum = _verify_and_read("BTCUSDT-fundingRate-2020-01.zip")
    futbars_zip, futbars_checksum = _verify_and_read("BTCUSDT-1d-2020-01.zip")
    fetch = FakeArchive(
        listing_symbols=["BTCUSDT"],
        files={
            _funding_url("BTCUSDT", "2020-01"): funding_zip,
            _funding_url("BTCUSDT", "2020-01") + ".CHECKSUM": funding_checksum,
            _futbars_url("BTCUSDT", "2020-01"): futbars_zip,
            _futbars_url("BTCUSDT", "2020-01") + ".CHECKSUM": futbars_checksum,
        },
    )
    symbols_path = tmp_path / "universe.json"
    symbols_path.write_text(json.dumps({"symbols": ["BTCUSDT"]}), encoding="utf-8")
    lake = tmp_path / "lake"

    first_results = backfill_derivs(
        lake, "2020-01-01", "2020-01-05",
        symbols_from=symbols_path, streams=["funding", "futbars"],
        fetch=fetch, sleep=_no_sleep,
    )
    assert all(r.status == "ok" and r.rows_written > 0 for r in first_results)
    calls_after_first_run = len(fetch.calls)
    assert calls_after_first_run > 0

    second_results = backfill_derivs(
        lake, "2020-01-01", "2020-01-05",
        symbols_from=symbols_path, streams=["funding", "futbars"],
        fetch=fetch, sleep=_no_sleep,
    )

    # Nothing left to fetch -- every month is already on disk -- so the
    # second run's own results report zero *new* rows, exactly as
    # bars_backfill's own fully-resumed rerun does; what matters is no call
    # was made and the first run's written rows are untouched.
    assert all(r.status == "ok" for r in second_results)
    assert len(fetch.calls) == calls_after_first_run, (
        "a resumed run must not refetch the symbol map crawl or an "
        "already-written month"
    )
    assert _read_parquet(lake, "funding", "BTCUSDT", date(2020, 1, 1))["n_settlements"] == 2


# -- 6. a checksum mismatch skips the month, reports it and exits 1 ---------


def test_checksum_mismatch_skips_the_month_reports_it_and_exits_1(tmp_path: Path) -> None:
    funding_zip, _good_checksum = _verify_and_read("BTCUSDT-fundingRate-2020-01.zip")
    wrong_checksum = (("0" * 64) + "  BTCUSDT-fundingRate-2020-01.zip\n").encode("utf-8")
    fetch = FakeArchive(
        listing_symbols=["BTCUSDT"],
        files={
            _funding_url("BTCUSDT", "2020-01"): funding_zip,
            _funding_url("BTCUSDT", "2020-01") + ".CHECKSUM": wrong_checksum,
        },
    )
    symbols_path = tmp_path / "universe.json"
    symbols_path.write_text(json.dumps({"symbols": ["BTCUSDT"]}), encoding="utf-8")
    lake = tmp_path / "lake"

    lines: list[str] = []
    exit_code = main(
        [
            "--lake", str(lake),
            "--first", "2020-01-01",
            "--last", "2020-01-03",
            "--symbols-from", str(symbols_path),
            "--streams", "funding",
        ],
        emit=lines.append,
        fetch=fetch,
        sleep=_no_sleep,
    )

    assert exit_code == 1
    error_lines = [json.loads(line) for line in lines if json.loads(line).get("phase") == "error"]
    assert len(error_lines) == 1
    assert error_lines[0]["stream"] == "funding"
    assert error_lines[0]["symbol"] == "BTCUSDT"
    assert error_lines[0]["period"] == "2020-01"
    assert "checksum mismatch" in error_lines[0]["error"]

    result_lines = [
        json.loads(line) for line in lines
        if json.loads(line).get("symbol") == "BTCUSDT" and "status" in json.loads(line)
    ]
    assert len(result_lines) == 1
    assert result_lines[0]["status"] == "error"
    assert not _partition_exists(lake, "funding", "BTCUSDT", date(2020, 1, 1))


def test_backfill_derivs_raises_for_a_missing_symbols_list(tmp_path: Path) -> None:
    symbols_path = tmp_path / "universe.json"
    symbols_path.write_text(json.dumps({"not_symbols": []}), encoding="utf-8")

    with pytest.raises(DerivsBackfillError, match="symbols"):
        backfill_derivs(
            tmp_path / "lake", "2020-01-01", "2020-01-01",
            symbols_from=symbols_path, sleep=_no_sleep,
        )


# -- 7. spot bars backfill unchanged ------------------------------------


def test_spot_bars_backfill_is_unaffected_by_the_shared_helper_refactor(tmp_path: Path) -> None:
    """bars_backfill.py's own archive mode, reusing the same low-level
    fetch_verified_archive_zip / _list_archive_keys this module now also
    calls -- parametrizing them must not change a single byte spot bars
    writes. Reuses the pre-existing pinned spot fixture from
    test_archive_timestamp_units.py's own fixtures directory."""
    zip_path = _SPOT_FIXTURES / "BTCUSDT-1d-2024-12.zip"
    checksum_path = _SPOT_FIXTURES / "BTCUSDT-1d-2024-12.zip.CHECKSUM"
    zip_bytes = zip_path.read_bytes()
    checksum_bytes = checksum_path.read_bytes()
    expected = checksum_bytes.decode("utf-8").split()[0]
    assert hashlib.sha256(zip_bytes).hexdigest() == expected

    spot_url = f"{ARCHIVE_BASE_URL}/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2024-12.zip"

    def fetch(url: str) -> HttpResponse:
        if url == spot_url:
            return HttpResponse(200, {}, zip_bytes)
        if url == f"{spot_url}.CHECKSUM":
            return HttpResponse(200, {}, checksum_bytes)
        return HttpResponse(404, {}, b"not found")

    lake = tmp_path / "lake"
    results = spot_backfill_bars(
        lake, "2024-12-01", "2024-12-01",
        source="archive", symbols=["BTCUSDT"],
        fetch=fetch, sleep=_no_sleep,
    )

    [result] = results
    assert result.status == "ok"
    assert result.rows_written == 1
    table = pq.read_table(
        lake / "staging" / "bars" / "symbol=BTCUSDT" / "date=2024-12-01" / "part-0.parquet"
    )
    [row] = table.to_pylist()
    assert row["symbol"] == "BTCUSDT"
