"""``funding/``'s day-bucketing: every settlement under the ingest day whose
``(D 00:00, D+1 00:00]`` window it closes, on both the archive and the REST
source -- so that a day's ``funding_rate_sum`` holds exactly that day's
settlements, and no rerun overwrites a complete day with a partial one.

Covers, as behaviour of :mod:`nullius_ingest.derivs_backfill`:

* a millisecond-late midnight ``calc_time`` is floored to the whole second
  before bucketing, so it lands on the *earlier* day, exactly as an
  exact-midnight settlement does;
* the archive side pools every month zip the window needs -- including the
  month holding ``last + 1 day`` 00:00 -- before aggregating, so a day
  spanning a month boundary is built from its whole window in one write,
  never overwritten by a later, partial one;
* an unpublished next month (404) leaves that boundary day unwritten rather
  than writing it partial, and a later run (once the month is published)
  writes it whole;
* the REST side requests through ``last + 1 day`` 00:00 plus one hour, so a
  closing settlement reported slightly late is still fetched, and withholds
  a day whose closing instant plus that hour has not yet passed the
  injected clock's "now";
* a day built either way (archive or REST) from the same synthetic
  8-hourly settlement schedule carries the same count and preserves the
  same total.

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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
from nullius_ingest.bars_backfill import ARCHIVE_LISTING_URL, HttpResponse
from nullius_ingest.derivs_backfill import backfill_derivs

ARCHIVE_BASE_URL = "https://data.binance.vision"


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


# -- A synthetic in-memory CSV zip, pinned to its own sha256 .CHECKSUM ------


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


def _funding_rows(settlements: Sequence[tuple[datetime, str]]) -> list[list[str]]:
    rows: list[list[str]] = [["calc_time", "funding_interval_hours", "last_funding_rate"]]
    for instant, rate in settlements:
        rows.append([str(_ms(instant)), "8", rate])
    return rows


# -- The injected archive fetch, keyed by exact URL --------------------------


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

    Mirrors ``test_derivs_backfill.py``'s own fixture class, duplicated here
    so this file stands alone. ``files`` can be mutated between two
    ``backfill_derivs`` calls (e.g. to simulate a month that later gets
    published), since this class reads it by reference at call time.
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


def _url(prefix: str, symbol: str, filename: str) -> str:
    return f"{ARCHIVE_BASE_URL}/" + "/".join([prefix.strip("/"), symbol, filename])


def _funding_url(symbol: str, month: str) -> str:
    return _url("data/futures/um/monthly/fundingRate/", symbol, f"{symbol}-fundingRate-{month}.zip")


# -- The injected REST fetch, scripted per symbol ---------------------------


class FakeRest:
    """An injected :data:`~nullius_ingest.bars_backfill.BinanceFetch`.

    Mirrors ``test_derivs_rest.py``'s own fixture class, duplicated here so
    this file stands alone. ``funding_pages`` scripts one page per call to
    ``/fundingRate`` for that symbol, in order; a call past the last
    scripted page answers an empty list.
    """

    def __init__(
        self, *, exchange_info: Mapping[str, object], funding_pages: Mapping[str, Sequence[list]] | None = None
    ) -> None:
        self.exchange_info = exchange_info
        self.funding_pages = {symbol: list(pages) for symbol, pages in (funding_pages or {}).items()}
        self._funding_index: dict[str, int] = {}
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
        raise AssertionError(f"unexpected path {path!r}")


def _rest_entry(symbol: str, instant: datetime, rate: str) -> dict[str, object]:
    return {"symbol": symbol, "fundingTime": _ms(instant), "fundingRate": rate, "markPrice": "1", "rateType": ""}


# -- 1. a ms-late midnight calc_time lands on the earlier day ---------------


def test_archive_ms_late_midnight_calc_time_lands_on_the_earlier_day(tmp_path: Path) -> None:
    day = date(2026, 4, 10)
    settlements = [
        (datetime(2026, 4, 10, 8, 0, 0, tzinfo=UTC), "0.00010000"),
        (datetime(2026, 4, 10, 16, 0, 0, tzinfo=UTC), "0.00005000"),
        # The closing settlement, reported 1 ms past the exact midnight --
        # must still floor to 2026-04-11T00:00:00 and roll back to the 10th.
        (datetime(2026, 4, 11, 0, 0, 0, 1000, tzinfo=UTC), "0.00002000"),
    ]
    zip_bytes, checksum_bytes = _make_zip(_funding_rows(settlements))
    fetch = FakeArchive(
        listing_symbols=["TESTUSDT"],
        files={
            _funding_url("TESTUSDT", "2026-04"): zip_bytes,
            _funding_url("TESTUSDT", "2026-04") + ".CHECKSUM": checksum_bytes,
        },
    )
    symbols_path = _write_universe(tmp_path, ["TESTUSDT"])
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], fetch=fetch, sleep=_no_sleep,
    )

    [result] = results
    assert result.status == "ok"
    assert result.rows_written == 1

    row = _read_parquet(lake, "funding", "TESTUSDT", day)
    assert row["n_settlements"] == 3
    assert Decimal(row["funding_rate_sum"]) == Decimal("0.00017000")
    assert Decimal(row["funding_rate_last"]) == Decimal("0.00002000")


# -- 2. a month edge: June's first settlement completes May 31 --------------


def _may_31_window_files(symbol: str) -> dict[str, bytes]:
    may_rows = _funding_rows(
        [
            (datetime(2026, 5, 31, 8, 0, 0, tzinfo=UTC), "0.00010000"),
            (datetime(2026, 5, 31, 16, 0, 0, tzinfo=UTC), "0.00003000"),
        ]
    )
    june_rows = _funding_rows(
        [
            # June's first settlement -- May 31's own closing instant.
            (datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC), "0.00001000"),
            (datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC), "0.00099999"),  # June 1's own, out of window
        ]
    )
    may_zip, may_checksum = _make_zip(may_rows)
    june_zip, june_checksum = _make_zip(june_rows)
    return {
        _funding_url(symbol, "2026-05"): may_zip,
        _funding_url(symbol, "2026-05") + ".CHECKSUM": may_checksum,
        _funding_url(symbol, "2026-06"): june_zip,
        _funding_url(symbol, "2026-06") + ".CHECKSUM": june_checksum,
    }


def test_archive_month_edge_june_zips_first_settlement_completes_may_31(tmp_path: Path) -> None:
    files = _may_31_window_files("TESTUSDT")
    fetch = FakeArchive(listing_symbols=["TESTUSDT"], files=files)
    symbols_path = _write_universe(tmp_path, ["TESTUSDT"])
    lake = tmp_path / "lake"
    day = date(2026, 5, 31)

    results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], fetch=fetch, sleep=_no_sleep,
    )

    [result] = results
    assert result.status == "ok"
    assert result.rows_written == 1

    # Both the May and the June zip were read -- the window needs June's
    # own first settlement to complete May 31's closing instant.
    assert any(url.endswith("2026-05.zip") for url in fetch.calls)
    assert any(url.endswith("2026-06.zip") for url in fetch.calls)

    row = _read_parquet(lake, "funding", "TESTUSDT", day)
    # Never overwritten by the June zip's own partial, 1-settlement bucket
    # for May 31 -- the pooled total is 3, not 1.
    assert row["n_settlements"] == 3
    assert Decimal(row["funding_rate_sum"]) == Decimal("0.00014000")
    assert Decimal(row["funding_rate_last"]) == Decimal("0.00001000")


# -- 3. an unpublished next month leaves the boundary day unwritten ---------


def test_archive_unpublished_next_month_leaves_last_day_unwritten_until_present(
    tmp_path: Path,
) -> None:
    files = _may_31_window_files("TESTUSDT")
    june_zip_url = _funding_url("TESTUSDT", "2026-06")
    files_without_june = {
        key: value for key, value in files.items() if not key.startswith(june_zip_url)
    }
    fetch = FakeArchive(listing_symbols=["TESTUSDT"], files=files_without_june)
    symbols_path = _write_universe(tmp_path, ["TESTUSDT"])
    lake = tmp_path / "lake"
    day = date(2026, 5, 31)

    first_results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], fetch=fetch, sleep=_no_sleep,
    )
    [first_result] = first_results
    assert first_result.status == "ok"  # a 404 is not a failure
    assert first_result.rows_written == 0
    assert not _partition_exists(lake, "funding", "TESTUSDT", day)

    # The month is published now -- a later run, same lake, same window.
    fetch.files.update(files)
    second_results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], fetch=fetch, sleep=_no_sleep,
    )
    [second_result] = second_results
    assert second_result.status == "ok"
    assert second_result.rows_written == 1

    row = _read_parquet(lake, "funding", "TESTUSDT", day)
    assert row["n_settlements"] == 3
    assert Decimal(row["funding_rate_sum"]) == Decimal("0.00014000")


# -- 4. REST through last+1 00:00:00.001 gives the last day 3 settlements ---


def test_rest_window_through_last_plus_one_ms_gives_the_last_day_three_settlements(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 20)
    page = [
        _rest_entry("TESTUSDT", datetime(2026, 7, 20, 8, 0, 0, tzinfo=UTC), "0.00010000"),
        _rest_entry("TESTUSDT", datetime(2026, 7, 20, 16, 0, 0, tzinfo=UTC), "0.00005000"),
        # The closing settlement, 1 ms past the exact midnight -- the real
        # venue's own artifact this feature's REST window-pad is for.
        _rest_entry("TESTUSDT", datetime(2026, 7, 21, 0, 0, 0, 1000, tzinfo=UTC), "0.00002000"),
    ]
    fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "TESTUSDT"}]}, funding_pages={"TESTUSDT": [page]}
    )
    symbols_path = _write_universe(tmp_path, ["TESTUSDT"])
    lake = tmp_path / "lake"

    results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], source="rest",
        fetch=fetch, sleep=_no_sleep, clock=lambda: datetime(2026, 7, 22, tzinfo=UTC),
    )

    [result] = results
    assert result.status == "ok"
    row = _read_parquet(lake, "funding", "TESTUSDT", day)
    assert row["n_settlements"] == 3
    assert Decimal(row["funding_rate_sum"]) == Decimal("0.00017000")
    assert Decimal(row["funding_rate_last"]) == Decimal("0.00002000")

    # The request window reaches at least an hour past last+1 00:00 -- the
    # pad that lets a late-posted closing settlement still be requested.
    funding_calls = [call for call in fetch.calls if call[0] == "/fundingRate"]
    closing_instant_ms = _ms(datetime(2026, 7, 21, 0, 0, 0, tzinfo=UTC))
    assert int(funding_calls[0][1]["endTime"]) >= closing_instant_ms + 3_600_000


# -- 5. the REST clock guard -------------------------------------------------


def test_rest_clock_guard_withholds_a_not_yet_closed_day(tmp_path: Path) -> None:
    day = date(2026, 8, 5)
    closing_instant = datetime(2026, 8, 6, 0, 0, 0, tzinfo=UTC)
    page = [
        _rest_entry("TESTUSDT", datetime(2026, 8, 5, 8, 0, 0, tzinfo=UTC), "0.00010000"),
        _rest_entry("TESTUSDT", datetime(2026, 8, 5, 16, 0, 0, tzinfo=UTC), "0.00005000"),
        _rest_entry("TESTUSDT", closing_instant, "0.00002000"),
    ]
    symbols_path = _write_universe(tmp_path, ["TESTUSDT"])
    lake = tmp_path / "lake"

    # "Now" is one minute short of the pad -- the day is not yet complete
    # enough to trust, and must not be written.
    early_fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "TESTUSDT"}]}, funding_pages={"TESTUSDT": [page]}
    )
    early_results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], source="rest",
        fetch=early_fetch, sleep=_no_sleep,
        clock=lambda: closing_instant + timedelta(hours=1) - timedelta(minutes=1),
    )
    [early_result] = early_results
    assert early_result.status == "ok"
    assert early_result.rows_written == 0
    assert not _partition_exists(lake, "funding", "TESTUSDT", day)

    # "Now" has reached the pad -- the same data is now trusted and written.
    late_fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "TESTUSDT"}]}, funding_pages={"TESTUSDT": [page]}
    )
    late_results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], source="rest",
        fetch=late_fetch, sleep=_no_sleep,
        clock=lambda: closing_instant + timedelta(hours=1),
    )
    [late_result] = late_results
    assert late_result.status == "ok"
    assert late_result.rows_written == 1
    row = _read_parquet(lake, "funding", "TESTUSDT", day)
    assert row["n_settlements"] == 3


# -- 6. synthetic 8-hourly settlements over two months, built either way ----


def _eight_hourly_series(start: datetime, stop: datetime) -> list[tuple[datetime, str]]:
    """Every 8-hourly instant in ``[start, stop]`` inclusive, with a distinct,
    strictly increasing rate per settlement -- so a bucketing bug (dropping,
    duplicating, or misattributing one) changes the preserved total."""
    settlements: list[tuple[datetime, str]] = []
    instant = start
    index = 1
    while instant <= stop:
        rate = format(Decimal(index) / Decimal(10**8), "f")
        settlements.append((instant, rate))
        instant += timedelta(hours=8)
        index += 1
    return settlements


def test_eight_hourly_settlements_over_two_months_built_either_way_preserve_totals(
    tmp_path: Path,
) -> None:
    first = date(2026, 5, 1)
    last = date(2026, 6, 30)
    series = _eight_hourly_series(
        datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)
    )
    # The series' own first point (2026-05-01T00:00) is the window's day
    # before (2026-04-30)'s closing instant -- outside [first, last].
    expected_total = sum((Decimal(rate) for _instant, rate in series[1:]), Decimal(0))

    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]

    # -- archive: split the pooled series into its own calendar months -----
    by_month: dict[str, list[tuple[datetime, str]]] = {}
    for instant, rate in series:
        by_month.setdefault(f"{instant.year:04d}-{instant.month:02d}", []).append((instant, rate))
    archive_files: dict[str, bytes] = {}
    for month, rows in by_month.items():
        zip_bytes, checksum_bytes = _make_zip(_funding_rows(rows))
        archive_files[_funding_url("TESTUSDT", month)] = zip_bytes
        archive_files[_funding_url("TESTUSDT", month) + ".CHECKSUM"] = checksum_bytes
    archive_fetch = FakeArchive(listing_symbols=["TESTUSDT"], files=archive_files)
    archive_symbols_path = _write_universe(tmp_path, ["TESTUSDT"])
    archive_lake = tmp_path / "lake_archive"

    archive_results = backfill_derivs(
        archive_lake, first, last, symbols_from=archive_symbols_path, streams=["funding"],
        fetch=archive_fetch, sleep=_no_sleep,
    )
    assert archive_results[0].status == "ok"

    # -- rest: one scripted page carrying the whole pooled series ------------
    rest_page = [_rest_entry("TESTUSDT", instant, rate) for instant, rate in series]
    rest_fetch = FakeRest(
        exchange_info={"symbols": [{"symbol": "TESTUSDT"}]}, funding_pages={"TESTUSDT": [rest_page]}
    )
    rest_symbols_path = _write_universe(tmp_path, ["TESTUSDT"])
    rest_lake = tmp_path / "lake_rest"

    rest_results = backfill_derivs(
        rest_lake, first, last, symbols_from=rest_symbols_path, streams=["funding"], source="rest",
        fetch=rest_fetch, sleep=_no_sleep, clock=lambda: datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert rest_results[0].status == "ok"

    archive_total = Decimal(0)
    rest_total = Decimal(0)
    for day in days:
        archive_row = _read_parquet(archive_lake, "funding", "TESTUSDT", day)
        rest_row = _read_parquet(rest_lake, "funding", "TESTUSDT", day)
        assert archive_row["n_settlements"] == 3, day
        assert rest_row["n_settlements"] == 3, day
        assert archive_row == rest_row, day
        archive_total += Decimal(archive_row["funding_rate_sum"])
        rest_total += Decimal(rest_row["funding_rate_sum"])

    assert archive_total == expected_total
    assert rest_total == expected_total


# -- 7. per-day resume: a written day is untouched unless --restart --------


def test_archive_resume_is_per_day_and_restart_forces_a_rewrite(tmp_path: Path) -> None:
    day = date(2026, 9, 10)
    original_rows = _funding_rows(
        [
            (datetime(2026, 9, 10, 8, 0, 0, tzinfo=UTC), "0.00010000"),
            (datetime(2026, 9, 10, 16, 0, 0, tzinfo=UTC), "0.00005000"),
            (datetime(2026, 9, 11, 0, 0, 0, tzinfo=UTC), "0.00001000"),
        ]
    )
    original_zip, original_checksum = _make_zip(original_rows)
    url = _funding_url("TESTUSDT", "2026-09")
    fetch = FakeArchive(
        listing_symbols=["TESTUSDT"],
        files={url: original_zip, url + ".CHECKSUM": original_checksum},
    )
    symbols_path = _write_universe(tmp_path, ["TESTUSDT"])
    lake = tmp_path / "lake"

    first_results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], fetch=fetch, sleep=_no_sleep,
    )
    assert first_results[0].rows_written == 1
    original_sum = Decimal(_read_parquet(lake, "funding", "TESTUSDT", day)["funding_rate_sum"])
    assert original_sum == Decimal("0.00016000")

    # The archive now serves different bytes for the same month -- standing
    # in for "the data changed"; what matters is whether this run re-reads it.
    changed_rows = _funding_rows(
        [
            (datetime(2026, 9, 10, 8, 0, 0, tzinfo=UTC), "0.00099999"),
            (datetime(2026, 9, 10, 16, 0, 0, tzinfo=UTC), "0.00099999"),
            (datetime(2026, 9, 11, 0, 0, 0, tzinfo=UTC), "0.00099999"),
        ]
    )
    changed_zip, changed_checksum = _make_zip(changed_rows)
    fetch.files[url] = changed_zip
    fetch.files[url + ".CHECKSUM"] = changed_checksum
    calls_before = len(fetch.calls)

    # Without --restart: the day is already on disk -- no fetch at all, and
    # the file on disk is untouched.
    resumed_results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], fetch=fetch, sleep=_no_sleep,
    )
    assert resumed_results[0].rows_written == 0
    assert len(fetch.calls) == calls_before, "a resumed run must not refetch an already-written day"
    assert Decimal(_read_parquet(lake, "funding", "TESTUSDT", day)["funding_rate_sum"]) == original_sum

    # With --restart: the day is refetched and rewritten with the new bytes.
    restarted_results = backfill_derivs(
        lake, day, day, symbols_from=symbols_path, streams=["funding"], fetch=fetch, sleep=_no_sleep,
        restart=True,
    )
    assert restarted_results[0].rows_written == 1
    assert len(fetch.calls) > calls_before, "--restart must refetch the month"
    rewritten_sum = Decimal(_read_parquet(lake, "funding", "TESTUSDT", day)["funding_rate_sum"])
    assert rewritten_sum == Decimal("0.00299997")
    assert rewritten_sum != original_sum
