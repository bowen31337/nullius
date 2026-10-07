"""The archive backfill's rank phase is cached, checkpointed and concurrent.

``bug_spec_backfill_rank_throughput.xml``: a ``--top N`` archive run used to
rank every candidate sequentially, fetching each one's zip and ``.CHECKSUM``
over the network, discarding the rows once ranked, and writing its checkpoint
only after the very last candidate -- so an 8-hour timeout mid-rank lost all
of it, and the write phase then re-fetched the same top-N symbols' files all
over again. This file covers the fix, all against an injected, in-memory
:mod:`nullius_ingest.bars_backfill` archive fetch -- never a socket -- so it
passes under pytest-xdist like the rest of the member's suite:

* each month is fetched once across ranking and writing (the verified file
  cache);
* an interrupted rank resumes without refetching the candidates and the
  listing it already checkpointed (the rank partial file, the listing
  cache);
* ``--restart`` clears and refetches all three caches;
* a corrupted cached zip is detected, deleted and refetched;
* a 429 on an archive fetch is retried, honouring its own Retry-After, the
  same as the REST source already does;
* ``--workers 1`` and ``--workers 8`` produce identical output;
* ``--workers 8`` ranks a wide candidate pool at least 4x faster than
  ``--workers 1``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import threading
import time
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from nullius_ingest.bars_backfill import (
    ARCHIVE_LISTING_URL,
    RANK_CACHE_DIRNAME,
    UNIVERSE_FILENAME,
    BarsBackfillError,
    HttpResponse,
    _cached_month_paths,
    backfill_bars,
)

UTC = dt.UTC


# -- Fixture building (mirrors test_lake_backfill.py's archive helpers) -------


def _archive_csv_row(day: dt.date, close: str, *, quote_volume: str = "40000.00") -> list[str]:
    open_ms = int(dt.datetime.combine(day, dt.time(0), tzinfo=UTC).timestamp() * 1000)
    close_ms = open_ms + 86_400_000 - 1
    return [
        str(open_ms), "100.00000000", "110.00000000", "90.00000000", close,
        "1000.50000000", str(close_ms), quote_volume, "10",
        "400.00000000", "40000.00", "0",
    ]


def _days_in_month(year: int, month: int) -> list[dt.date]:
    start = dt.date(year, month, 1)
    end = (
        dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    ) - dt.timedelta(days=1)
    days = []
    day = start
    while day <= end:
        days.append(day)
        day += dt.timedelta(days=1)
    return days


def _month_rows(month: str, close: str, *, quote_volume: str = "40000.00") -> list[list[str]]:
    year, month_num = (int(part) for part in month.split("-"))
    return [_archive_csv_row(day, close, quote_volume=quote_volume) for day in _days_in_month(year, month_num)]


def _zip_bytes(symbol: str, month: str, rows: list[list[str]]) -> bytes:
    buffer = io.BytesIO()
    text = "\n".join(",".join(row) for row in rows) + "\n"
    info = zipfile.ZipInfo(f"{symbol}-1d-{month}.csv", date_time=(2026, 1, 1, 0, 0, 0))
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(info, text)
    return buffer.getvalue()


def _checksum_bytes(zip_bytes: bytes, filename: str) -> bytes:
    digest = hashlib.sha256(zip_bytes).hexdigest()
    return f"{digest}  {filename}\n".encode()


def _listing_xml(keys: Sequence[str]) -> bytes:
    entries = "".join(f"<Contents><Key>{key}</Key></Contents>" for key in keys)
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<ListBucketResult xmlns='http://s3.amazonaws.com/doc/2006-03-01/'>"
        f"{entries}"
        "<IsTruncated>false</IsTruncated>"
        "</ListBucketResult>"
    ).encode()


def _archive_fetch(
    rows_by_symbol_month: Mapping[tuple[str, str], list[list[str]]],
    *,
    bad_checksum: frozenset[tuple[str, str]] = frozenset(),
    listing_keys: Sequence[str] = (),
    latency: float = 0.0,
):
    """A recorded archive fetch: one URL in, one response out, no socket.

    Thread-safe (``calls`` is appended under a lock), since every test here
    may hand this fetch to a worker pool of more than one thread. ``latency``,
    when given, is a real ``time.sleep`` inside the fetch itself -- the
    simulated network cost the throughput tests measure a worker-count
    speedup against.
    """
    zip_cache = {
        key: _zip_bytes(key[0], key[1], rows) for key, rows in rows_by_symbol_month.items()
    }
    calls: list[str] = []
    lock = threading.Lock()

    def fetch(url: str) -> HttpResponse:
        if latency:
            time.sleep(latency)
        with lock:
            calls.append(url)
        if url.startswith(ARCHIVE_LISTING_URL):
            return HttpResponse(200, {}, _listing_xml(listing_keys))
        is_checksum = url.endswith(".CHECKSUM")
        zip_url = url[: -len(".CHECKSUM")] if is_checksum else url
        filename = zip_url.rsplit("/", 1)[-1]
        stem = filename[: -len(".zip")]
        symbol, _, month = stem.rpartition("-1d-")
        zip_bytes = zip_cache.get((symbol, month))
        if zip_bytes is None:
            return HttpResponse(404, {}, b"not found")
        if is_checksum:
            if (symbol, month) in bad_checksum:
                return HttpResponse(200, {}, f"{'0' * 64}  {filename}\n".encode())
            return HttpResponse(200, {}, _checksum_bytes(zip_bytes, filename))
        return HttpResponse(200, {}, zip_bytes)

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _fail_for_symbol(fetch, symbol: str):
    """Wrap ``fetch`` so every call naming ``symbol`` raises instead of
    delegating -- every other symbol's calls succeed normally. A persistently
    broken candidate is deterministic under any worker count, unlike a
    "raise after N calls" counter, whose Nth call is not a fixed candidate
    once more than one candidate is fetched at a time."""

    def wrapped(url: str) -> HttpResponse:
        if symbol in url:
            raise RuntimeError(f"simulated network drop fetching {symbol}")
        return fetch(url)

    wrapped.calls = fetch.calls  # type: ignore[attr-defined]
    return wrapped


def _no_sleep(_seconds: float) -> None:
    return None


def _part_path(lake: Path, symbol: str, day: dt.date) -> Path:
    return lake / "staging" / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}" / "part-0.parquet"


def _listing_keys_for(symbols: Sequence[str], months: Sequence[str]) -> list[str]:
    return [
        f"data/spot/monthly/klines/{symbol}/1d/{symbol}-1d-{month}.zip"
        for symbol in symbols
        for month in months
    ]


# -- Each month is fetched once across ranking and writing --------------------


def test_each_month_is_fetched_once_across_ranking_and_writing(tmp_path: Path) -> None:
    symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    fetch = _archive_fetch(
        {
            ("AAAUSDT", "2026-01"): _month_rows("2026-01", "1.00", quote_volume="300"),
            ("BBBUSDT", "2026-01"): _month_rows("2026-01", "2.00", quote_volume="200"),
            ("CCCUSDT", "2026-01"): _month_rows("2026-01", "3.00", quote_volume="100"),
        },
        listing_keys=_listing_keys_for(symbols, ["2026-01"]),
    )

    results = backfill_bars(
        tmp_path, "2026-01-01", "2026-01-31",
        source="archive", top=2, fetch=fetch, sleep=_no_sleep,
    )
    assert [r.symbol for r in results] == ["AAAUSDT", "BBBUSDT"]
    assert all(r.status == "ok" for r in results)

    # listing(1) + 3 candidates x (zip + checksum) = 7. If the write phase
    # re-fetched the two winners' already-ranked months, this would be 11.
    assert len(fetch.calls) == 7
    for symbol in symbols:
        zip_calls = [
            c for c in fetch.calls if f"{symbol}-1d-2026-01.zip" in c and not c.endswith(".CHECKSUM")
        ]
        checksum_calls = [c for c in fetch.calls if f"{symbol}-1d-2026-01.zip.CHECKSUM" in c]
        assert len(zip_calls) == 1, symbol
        assert len(checksum_calls) == 1, symbol

    # The cached pair for every candidate -- including the one that lost --
    # is on disk, verified, outside staging/.
    for symbol in symbols:
        zip_path, checksum_path = _cached_month_paths(tmp_path, symbol, "2026-01")
        assert zip_path.is_file()
        assert checksum_path.is_file()
    assert not (tmp_path / "staging" / RANK_CACHE_DIRNAME).exists()


# -- An interrupted rank resumes without refetching ----------------------------


def test_an_interrupted_rank_resumes_without_refetching_ranked_symbols_or_the_listing(
    tmp_path: Path,
) -> None:
    symbols = ["SYM0USDT", "SYM1USDT", "SYM2USDT", "SYM3USDT"]
    rows_by_symbol_month = {
        (symbol, "2026-01"): _month_rows("2026-01", f"{i}.00", quote_volume=str(400 - i))
        for i, symbol in enumerate(symbols)
    }
    listing_keys = _listing_keys_for(symbols, ["2026-01"])

    base_fetch = _archive_fetch(rows_by_symbol_month, listing_keys=listing_keys)
    flaky_fetch = _fail_for_symbol(base_fetch, "SYM1USDT")

    with pytest.raises(RuntimeError, match="SYM1USDT"):
        backfill_bars(
            tmp_path, "2026-01-01", "2026-01-31",
            source="archive", top=4, fetch=flaky_fetch, sleep=_no_sleep, workers=1,
        )

    partial_path = tmp_path / RANK_CACHE_DIRNAME / "rank-2026-01-01_2026-01-31.partial.jsonl"
    final_cache_path = tmp_path / RANK_CACHE_DIRNAME / "rank-2026-01-01_2026-01-31.json"
    assert partial_path.is_file()
    assert not final_cache_path.is_file()
    checkpointed = {json.loads(line)["symbol"] for line in partial_path.read_text().splitlines()}
    assert checkpointed == {"SYM0USDT", "SYM2USDT", "SYM3USDT"}
    # The listing itself was cached on its own first call, before any
    # candidate was ranked.
    assert (tmp_path / RANK_CACHE_DIRNAME / "archive-listing.json").is_file()

    resume_fetch = _archive_fetch(rows_by_symbol_month, listing_keys=listing_keys)
    results = backfill_bars(
        tmp_path, "2026-01-01", "2026-01-31",
        source="archive", top=4, fetch=resume_fetch, sleep=_no_sleep, workers=1,
    )
    assert [r.symbol for r in results] == symbols
    assert all(r.status == "ok" for r in results)

    # The resume never touches the listing or the three already-checkpointed
    # candidates -- only SYM1USDT, the one that never got ranked.
    assert not any(url.startswith(ARCHIVE_LISTING_URL) for url in resume_fetch.calls)
    assert not any("SYM0USDT" in url for url in resume_fetch.calls)
    assert not any("SYM2USDT" in url for url in resume_fetch.calls)
    assert not any("SYM3USDT" in url for url in resume_fetch.calls)
    assert any("SYM1USDT" in url for url in resume_fetch.calls)

    assert final_cache_path.is_file()
    assert not partial_path.is_file()


# -- --restart clears and refetches all three caches ---------------------------


def test_restart_clears_and_refetches_listing_partial_and_file_cache(tmp_path: Path) -> None:
    listing_keys = _listing_keys_for(["AAAUSDT"], ["2026-01"])
    day = dt.date(2026, 1, 1)

    first_fetch = _archive_fetch(
        {("AAAUSDT", "2026-01"): _month_rows("2026-01", "100.00")}, listing_keys=listing_keys,
    )
    backfill_bars(
        tmp_path, "2026-01-01", "2026-01-03",
        source="archive", top=1, fetch=first_fetch, sleep=_no_sleep,
    )
    assert pq.read_table(_part_path(tmp_path, "AAAUSDT", day)).to_pylist()[0]["close"] == "100.00"
    listing_cache = tmp_path / RANK_CACHE_DIRNAME / "archive-listing.json"
    zip_path, _checksum_path = _cached_month_paths(tmp_path, "AAAUSDT", "2026-01")
    assert listing_cache.is_file()
    assert zip_path.is_file()

    # No --restart: every cache hits, zero network calls, even with data that
    # would differ if fetched.
    second_fetch = _archive_fetch(
        {("AAAUSDT", "2026-01"): _month_rows("2026-01", "200.00")}, listing_keys=listing_keys,
    )
    backfill_bars(
        tmp_path, "2026-01-01", "2026-01-03",
        source="archive", top=1, fetch=second_fetch, sleep=_no_sleep,
    )
    assert second_fetch.calls == []
    assert pq.read_table(_part_path(tmp_path, "AAAUSDT", day)).to_pylist()[0]["close"] == "100.00"

    # --restart: the listing, the cached zip and the rank cache are all
    # cleared and refetched; the new data wins.
    third_fetch = _archive_fetch(
        {("AAAUSDT", "2026-01"): _month_rows("2026-01", "200.00")}, listing_keys=listing_keys,
    )
    backfill_bars(
        tmp_path, "2026-01-01", "2026-01-03",
        source="archive", top=1, fetch=third_fetch, sleep=_no_sleep, restart=True,
    )
    assert third_fetch.calls != []
    assert any(url.startswith(ARCHIVE_LISTING_URL) for url in third_fetch.calls)
    assert pq.read_table(_part_path(tmp_path, "AAAUSDT", day)).to_pylist()[0]["close"] == "200.00"
    # The cache now holds the new data, re-verified against its own checksum.
    assert hashlib.sha256(zip_path.read_bytes()).hexdigest() == hashlib.sha256(
        _zip_bytes("AAAUSDT", "2026-01", _month_rows("2026-01", "200.00"))
    ).hexdigest()


# -- A corrupted cached zip is detected, deleted and refetched -----------------


def test_a_corrupted_cached_zip_is_detected_deleted_and_refetched(tmp_path: Path) -> None:
    """A corrupted cache entry is exercised through the public API, not by
    calling ``_fetch_month`` directly: a second run over a *wider* window
    (Jan-Feb rather than Jan alone) gets its own rank cache key, so ranking
    genuinely re-executes and re-reads January's file cache entry, even
    though January's partitions are already written and the file cache
    itself (keyed by symbol and month alone, not by window) is untouched
    between the two runs."""
    jan_rows = _month_rows("2026-01", "61234.50")
    feb_rows = _month_rows("2026-02", "62000.00")
    listing_keys = _listing_keys_for(["AAAUSDT"], ["2026-01", "2026-02"])

    first_fetch = _archive_fetch({("AAAUSDT", "2026-01"): jan_rows}, listing_keys=listing_keys)
    backfill_bars(
        tmp_path, "2026-01-01", "2026-01-31",
        source="archive", top=1, fetch=first_fetch, sleep=_no_sleep,
    )
    day = dt.date(2026, 1, 1)
    assert pq.read_table(_part_path(tmp_path, "AAAUSDT", day)).to_pylist()[0]["close"] == "61234.50"

    zip_path, checksum_path = _cached_month_paths(tmp_path, "AAAUSDT", "2026-01")
    assert zip_path.is_file()
    assert checksum_path.is_file()
    good_bytes = zip_path.read_bytes()
    corrupted = bytearray(good_bytes)
    corrupted[0] ^= 0xFF
    zip_path.write_bytes(bytes(corrupted))

    # A wider window: a fresh rank cache key, so ranking re-executes and
    # re-reads January's (corrupted) cache entry -- even though January's
    # partitions already exist from the first run.
    second_fetch = _archive_fetch(
        {("AAAUSDT", "2026-01"): jan_rows, ("AAAUSDT", "2026-02"): feb_rows},
        listing_keys=listing_keys,
    )
    results = backfill_bars(
        tmp_path, "2026-01-01", "2026-02-28",
        source="archive", top=1, fetch=second_fetch, sleep=_no_sleep,
    )
    assert [r.symbol for r in results] == ["AAAUSDT"]
    assert results[0].status == "ok"

    # January's corrupted zip was refetched over the network (both its zip
    # and its .CHECKSUM); February, a genuine cache miss, was fetched too.
    assert sum(1 for c in second_fetch.calls if "AAAUSDT-1d-2026-01.zip" in c and not c.endswith(".CHECKSUM")) == 1
    assert sum(1 for c in second_fetch.calls if "AAAUSDT-1d-2026-01.zip.CHECKSUM" in c) == 1
    assert sum(1 for c in second_fetch.calls if "AAAUSDT-1d-2026-02.zip" in c and not c.endswith(".CHECKSUM")) == 1

    # The cache now holds the good bytes again, and both months' data is
    # correct on disk.
    assert zip_path.read_bytes() == good_bytes
    assert pq.read_table(_part_path(tmp_path, "AAAUSDT", day)).to_pylist()[0]["close"] == "61234.50"
    assert pq.read_table(
        _part_path(tmp_path, "AAAUSDT", dt.date(2026, 2, 1))
    ).to_pylist()[0]["close"] == "62000.00"


# -- A 418/429 on an archive fetch honours Retry-After, same as REST mode -----


def test_a_429_on_the_archive_zip_fetch_is_retried_and_succeeds(tmp_path: Path) -> None:
    """Archive-mode fetches (the zip, its .CHECKSUM, the S3 listing) carried
    no retry logic at all before this fix -- ``--workers`` makes that a real
    gap, since a rate limit under concurrency must not take down a whole
    worker's candidate. One fetch exercises the shared retry path for all
    three archive URL kinds."""
    rows = _month_rows("2026-01", "61234.50")
    base_fetch = _archive_fetch({("AAAUSDT", "2026-01"): rows})
    attempts = {"n": 0}
    sleeps: list[float] = []

    def flaky(url: str) -> HttpResponse:
        if url.endswith(".zip"):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return HttpResponse(429, {"Retry-After": "3"}, b"rate limited")
        return base_fetch(url)

    results = backfill_bars(
        tmp_path, "2026-01-01", "2026-01-31",
        source="archive", symbols=["AAAUSDT"], fetch=flaky, sleep=sleeps.append,
    )

    assert attempts["n"] == 2
    assert results[0].status == "ok"
    assert results[0].rows_written == len(_days_in_month(2026, 1))
    # The retry-after delay was honoured before the retry succeeded.
    assert 3.0 in sleeps


# -- --workers 1 and --workers 8 produce identical output ----------------------


def test_workers_one_and_eight_produce_identical_output(tmp_path: Path) -> None:
    symbols = [f"SYM{i}USDT" for i in range(6)]
    months = ["2026-01", "2026-02"]
    rows_by_symbol_month = {
        (symbol, month): _month_rows(month, f"{100 + i}.00", quote_volume=str(1000 - i * 7 + m))
        for i, symbol in enumerate(symbols)
        for m, month in enumerate(months)
    }
    listing_keys = _listing_keys_for(symbols, months)

    lake_one = tmp_path / "workers-1"
    lake_eight = tmp_path / "workers-8"
    # A fixed clock, so universe.json's own fetched_at -- the one field that
    # is legitimately about wall-clock time, not about the worker count --
    # does not stand between this test and a literal byte comparison.
    def fixed_clock() -> dt.datetime:
        return dt.datetime(2026, 3, 1, tzinfo=UTC)

    results = {}
    for lake, workers in ((lake_one, 1), (lake_eight, 8)):
        fetch = _archive_fetch(rows_by_symbol_month, listing_keys=listing_keys)
        results[workers] = backfill_bars(
            lake, "2026-01-01", "2026-02-28",
            source="archive", top=3, fetch=fetch, sleep=_no_sleep, workers=workers,
            clock=fixed_clock,
        )

    assert [r.symbol for r in results[1]] == [r.symbol for r in results[8]]
    assert [r.to_payload() for r in results[1]] == [r.to_payload() for r in results[8]]

    # Byte-identical, not just logically equal: same bytes on disk, whatever
    # the worker count.
    assert (lake_one / UNIVERSE_FILENAME).read_bytes() == (lake_eight / UNIVERSE_FILENAME).read_bytes()
    rank_name = "rank-2026-01-01_2026-02-28.json"
    assert (
        (lake_one / RANK_CACHE_DIRNAME / rank_name).read_bytes()
        == (lake_eight / RANK_CACHE_DIRNAME / rank_name).read_bytes()
    )

    compared_partitions = 0
    for symbol in [r.symbol for r in results[1]]:
        for month in months:
            for day in _days_in_month(*(int(p) for p in month.split("-"))):
                path_one = _part_path(lake_one, symbol, day)
                path_eight = _part_path(lake_eight, symbol, day)
                assert path_one.is_file() and path_eight.is_file()
                assert path_one.read_bytes() == path_eight.read_bytes()
                compared_partitions += 1
    assert compared_partitions == 3 * (len(_days_in_month(2026, 1)) + len(_days_in_month(2026, 2)))


def test_workers_out_of_range_is_refused(tmp_path: Path) -> None:
    fetch = _archive_fetch({("AAAUSDT", "2026-01"): _month_rows("2026-01", "1.00")})
    for bad in (0, 33, -1):
        with pytest.raises(BarsBackfillError, match="--workers"):
            backfill_bars(
                tmp_path, "2026-01-01", "2026-01-31",
                source="archive", top=1, fetch=fetch, sleep=_no_sleep, workers=bad,
            )


# -- --workers 8 ranks a wide candidate pool at least 4x faster ----------------


def test_eight_workers_rank_a_wide_candidate_pool_at_least_four_times_faster(
    tmp_path: Path,
) -> None:
    months = [f"2026-{m:02d}" for m in range(1, 13)]
    symbols = [f"SYM{i:02d}USDT" for i in range(30)]
    rows_by_symbol_month = {
        (symbol, month): _month_rows(month, "1.00", quote_volume=str(1000 - i))
        for i, symbol in enumerate(symbols)
        for month in months
    }
    listing_keys = _listing_keys_for(symbols, months)

    def run(workers: int, lake: Path) -> float:
        fetch = _archive_fetch(rows_by_symbol_month, listing_keys=listing_keys, latency=0.01)
        started = time.perf_counter()
        backfill_bars(
            # top=1: the write phase (parquet, not network-bound, and not
            # parallelized by --workers) stays a small, fixed cost next to
            # the 30-candidate rank pass this test actually measures.
            lake, "2026-01-01", "2026-12-31",
            source="archive", top=1, fetch=fetch, sleep=_no_sleep, workers=workers,
        )
        return time.perf_counter() - started

    serial_elapsed = run(1, tmp_path / "serial")
    parallel_elapsed = run(8, tmp_path / "parallel")

    assert parallel_elapsed * 4 < serial_elapsed
