"""The archive backfill shows progress, checkpoints, and never raw-tracebacks.

``bug_spec_archive_backfill.xml`` bug 2: a multi-hour ``--source archive``
run used to rank its whole candidate pool and fetch every symbol's rows in
memory before writing a single partition, print nothing while doing it, and
let any unexpected exception escape ``main()`` as a raw traceback -- so an
interrupted run lost everything and a rerun started from zero. This file
covers the fix, all against :mod:`nullius_ingest.bars_backfill`'s archive
path, with a recorded, in-memory archive fetch -- never a socket -- so it
passes under pytest-xdist like the rest of the member's suite:

* progress lines during ``--top N`` ranking, before the per-symbol lines;
* an interrupted run (the fetch raises partway through) that resumes on
  rerun without refetching the months it already wrote;
* ``--restart`` ignoring both the rank cache and every already-written
  month;
* a checksum-mismatch month that is skipped and reported on its own JSON
  line, while the symbol's other months still write, with exit 1;
* an unexpected error (anything other than :class:`BarsBackfillError`)
  giving one stderr line and no traceback.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from nullius_ingest.bars_backfill import (
    ARCHIVE_LISTING_URL,
    RANK_CACHE_DIRNAME,
    UNIVERSE_FILENAME,
    HttpResponse,
    backfill_bars,
    main,
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
):
    """A recorded archive fetch: one URL in, one response out, no socket."""
    zip_cache = {
        key: _zip_bytes(key[0], key[1], rows) for key, rows in rows_by_symbol_month.items()
    }
    calls: list[str] = []

    def fetch(url: str) -> HttpResponse:
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


def _fail_after(fetch, n: int):
    """Wrap ``fetch`` so the ``(n + 1)``th call raises instead of delegating.

    The first ``n`` calls succeed and are logged on ``fetch.calls`` exactly
    as they would be without the wrapper; the failing call is never
    delegated, so it is never logged either -- it never completed.
    """
    state = {"count": 0}

    def wrapped(url: str) -> HttpResponse:
        state["count"] += 1
        if state["count"] > n:
            raise RuntimeError("simulated network drop")
        return fetch(url)

    wrapped.calls = fetch.calls  # type: ignore[attr-defined]
    return wrapped


def _no_sleep(_seconds: float) -> None:
    return None


def _part_path(lake: Path, symbol: str, day: dt.date) -> Path:
    return lake / "staging" / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}" / "part-0.parquet"


# -- Progress lines during --top N ranking -------------------------------------


def test_progress_lines_are_emitted_during_ranking_before_symbol_lines(tmp_path: Path) -> None:
    listing_keys = [
        "data/spot/monthly/klines/AAAUSDT/1d/AAAUSDT-1d-2026-01.zip",
        "data/spot/monthly/klines/BBBUSDT/1d/BBBUSDT-1d-2026-01.zip",
        "data/spot/monthly/klines/CCCUSDT/1d/CCCUSDT-1d-2026-01.zip",
    ]
    fetch = _archive_fetch(
        {
            ("AAAUSDT", "2026-01"): _month_rows("2026-01", "1.00", quote_volume="300"),
            ("BBBUSDT", "2026-01"): _month_rows("2026-01", "2.00", quote_volume="200"),
            ("CCCUSDT", "2026-01"): _month_rows("2026-01", "3.00", quote_volume="100"),
        },
        listing_keys=listing_keys,
    )
    lines: list[str] = []

    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-01-31",
            "--source", "archive", "--top", "2",
        ],
        emit=lines.append, fetch=fetch, sleep=_no_sleep,
    )
    assert exit_code == 0

    events = [json.loads(line) for line in lines]
    rank_events = [e for e in events if e.get("phase") == "rank"]
    symbol_events = [e for e in events if "status" in e]
    assert [event["symbols_done"] for event in rank_events] == [1, 2, 3]
    assert all(event["symbols_total"] == 3 for event in rank_events)
    # Ranking is the whole candidate pool, not just the winners.
    assert [e["symbol"] for e in symbol_events] == ["AAAUSDT", "BBBUSDT"]
    # Every progress line during ranking comes before the per-symbol lines.
    assert events.index(rank_events[-1]) < events.index(symbol_events[0])


# -- The rank cache --------------------------------------------------------------


def test_rank_cache_is_written_beside_staging_and_never_sealed(tmp_path: Path) -> None:
    listing_keys = ["data/spot/monthly/klines/AAAUSDT/1d/AAAUSDT-1d-2026-01.zip"]
    fetch = _archive_fetch(
        {("AAAUSDT", "2026-01"): _month_rows("2026-01", "1.00")},
        listing_keys=listing_keys,
    )

    backfill_bars(
        tmp_path, "2026-01-01", "2026-01-03",
        source="archive", top=1, fetch=fetch, sleep=_no_sleep,
    )

    cache_path = tmp_path / RANK_CACHE_DIRNAME / "rank-2026-01-01_2026-01-03.json"
    assert cache_path.is_file()
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["first"] == "2026-01-01"
    assert payload["last"] == "2026-01-03"
    assert payload["ranking"] == [
        {"symbol": "AAAUSDT", "median_volume": 40000.0, "last_archived_month": "2026-01"}
    ]
    # Outside staging/, so a seal of staging/ never walks into it.
    assert not (tmp_path / "staging" / RANK_CACHE_DIRNAME).exists()


# -- --restart ignores both the rank cache and already-written months ----------


def test_restart_ignores_the_rank_cache_and_already_written_months(tmp_path: Path) -> None:
    listing_keys = ["data/spot/monthly/klines/AAAUSDT/1d/AAAUSDT-1d-2026-01.zip"]
    day = dt.date(2026, 1, 1)

    first_fetch = _archive_fetch(
        {("AAAUSDT", "2026-01"): _month_rows("2026-01", "100.00")},
        listing_keys=listing_keys,
    )
    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-01-03",
            "--source", "archive", "--top", "1",
        ],
        emit=lambda _line: None, fetch=first_fetch, sleep=_no_sleep,
    )
    assert exit_code == 0
    assert pq.read_table(_part_path(tmp_path, "AAAUSDT", day)).to_pylist()[0]["close"] == "100.00"

    # A second run, no --restart, with data that *would* differ if fetched:
    # reusing the cache and the already-written month must make zero calls
    # and leave the file untouched.
    second_fetch = _archive_fetch(
        {("AAAUSDT", "2026-01"): _month_rows("2026-01", "200.00")},
        listing_keys=listing_keys,
    )
    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-01-03",
            "--source", "archive", "--top", "1",
        ],
        emit=lambda _line: None, fetch=second_fetch, sleep=_no_sleep,
    )
    assert exit_code == 0
    assert second_fetch.calls == []
    assert pq.read_table(_part_path(tmp_path, "AAAUSDT", day)).to_pylist()[0]["close"] == "100.00"

    # A third run, with --restart, over the same (new) data: the listing and
    # the zip are fetched again, and the file is rewritten.
    third_fetch = _archive_fetch(
        {("AAAUSDT", "2026-01"): _month_rows("2026-01", "200.00")},
        listing_keys=listing_keys,
    )
    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-01-03",
            "--source", "archive", "--top", "1", "--restart",
        ],
        emit=lambda _line: None, fetch=third_fetch, sleep=_no_sleep,
    )
    assert exit_code == 0
    assert third_fetch.calls != []
    assert any(ARCHIVE_LISTING_URL in call for call in third_fetch.calls)
    assert pq.read_table(_part_path(tmp_path, "AAAUSDT", day)).to_pylist()[0]["close"] == "200.00"


# -- An interrupted run resumes without refetching written months --------------


def test_an_interrupted_run_resumes_without_refetching_written_months(tmp_path: Path) -> None:
    rows_by_symbol_month = {
        ("AAAUSDT", "2026-01"): _month_rows("2026-01", "1.00"),
        ("AAAUSDT", "2026-02"): _month_rows("2026-02", "1.50"),
        ("BBBUSDT", "2026-01"): _month_rows("2026-01", "2.00"),
        ("BBBUSDT", "2026-02"): _month_rows("2026-02", "2.50"),
    }
    base_fetch = _archive_fetch(rows_by_symbol_month)
    # AAAUSDT's 2026-01 zip (call 1) and its .CHECKSUM (call 2) succeed; the
    # 3rd call -- AAAUSDT's 2026-02 zip -- raises instead of completing.
    flaky_fetch = _fail_after(base_fetch, 2)

    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-02-28",
            "--source", "archive", "--symbols", "AAAUSDT,BBBUSDT",
        ],
        emit=lambda _line: None, fetch=flaky_fetch, sleep=_no_sleep,
    )
    assert exit_code == 1

    # The month already fetched and written survives; nothing past the break
    # point was ever written.
    assert _part_path(tmp_path, "AAAUSDT", dt.date(2026, 1, 1)).is_file()
    assert _part_path(tmp_path, "AAAUSDT", dt.date(2026, 1, 31)).is_file()
    assert not (tmp_path / "staging" / "bars" / "symbol=AAAUSDT" / "date=2026-02-01").exists()
    assert not (tmp_path / "staging" / "bars" / "symbol=BBBUSDT").exists()

    # A rerun with the same arguments and a fetch that no longer fails
    # resumes: AAAUSDT's already-written January is never fetched again.
    resume_fetch = _archive_fetch(rows_by_symbol_month)
    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-02-28",
            "--source", "archive", "--symbols", "AAAUSDT,BBBUSDT",
        ],
        emit=lambda _line: None, fetch=resume_fetch, sleep=_no_sleep,
    )
    assert exit_code == 0
    assert not any("AAAUSDT-1d-2026-01" in call for call in resume_fetch.calls)
    assert any("AAAUSDT-1d-2026-02" in call for call in resume_fetch.calls)
    assert any("BBBUSDT-1d-2026-01" in call for call in resume_fetch.calls)
    assert any("BBBUSDT-1d-2026-02" in call for call in resume_fetch.calls)

    for symbol in ("AAAUSDT", "BBBUSDT"):
        jan_days = len(_days_in_month(2026, 1))
        feb_days = len(_days_in_month(2026, 2))
        written_days = sum(
            1
            for part in (tmp_path / "staging" / "bars" / f"symbol={symbol}").glob("date=*")
            if (part / "part-0.parquet").is_file()
        )
        assert written_days == jan_days + feb_days
        assert pq.read_table(_part_path(tmp_path, symbol, dt.date(2026, 1, 1))).num_rows == 1


# -- A fully-resumed rerun still names every symbol's last archived month -----


def test_a_fully_resumed_rerun_still_names_last_archived_month(tmp_path: Path) -> None:
    """Every month already on disk when a rerun starts is skipped -- so the
    rerun's own fetch never touches it -- but ``universe.json`` must still
    carry that symbol's ``last_archived_month``, not silently drop it just
    because nothing needed fetching this time."""
    rows_by_symbol_month = {
        ("AAAUSDT", "2026-01"): _month_rows("2026-01", "1.00"),
        ("AAAUSDT", "2026-02"): _month_rows("2026-02", "1.50"),
    }

    first_fetch = _archive_fetch(rows_by_symbol_month)
    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-02-28",
            "--source", "archive", "--symbols", "AAAUSDT",
        ],
        emit=lambda _line: None, fetch=first_fetch, sleep=_no_sleep,
    )
    assert exit_code == 0
    first_universe = json.loads((tmp_path / UNIVERSE_FILENAME).read_text(encoding="utf-8"))
    assert first_universe["last_archived_month"] == {"AAAUSDT": "2026-02"}

    # Nothing to fetch this time -- every month is already on disk -- yet the
    # field must survive unchanged.
    second_fetch = _archive_fetch(rows_by_symbol_month)
    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-02-28",
            "--source", "archive", "--symbols", "AAAUSDT",
        ],
        emit=lambda _line: None, fetch=second_fetch, sleep=_no_sleep,
    )
    assert exit_code == 0
    assert second_fetch.calls == []
    second_universe = json.loads((tmp_path / UNIVERSE_FILENAME).read_text(encoding="utf-8"))
    assert second_universe["last_archived_month"] == {"AAAUSDT": "2026-02"}


# -- A checksum-mismatch month is skipped and reported, with exit 1 ------------


def test_a_checksum_mismatch_month_is_skipped_and_reported_other_months_still_write(
    tmp_path: Path,
) -> None:
    fetch = _archive_fetch(
        {
            ("AAAUSDT", "2026-01"): _month_rows("2026-01", "61234.50"),
            ("AAAUSDT", "2026-02"): _month_rows("2026-02", "62000.00"),
        },
        bad_checksum=frozenset({("AAAUSDT", "2026-02")}),
    )
    lines: list[str] = []

    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-02-28",
            "--source", "archive", "--symbols", "AAAUSDT",
        ],
        emit=lines.append, fetch=fetch, sleep=_no_sleep,
    )

    assert exit_code == 1
    events = [json.loads(line) for line in lines]
    error_events = [e for e in events if e.get("phase") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["symbol"] == "AAAUSDT"
    assert error_events[0]["month"] == "2026-02"
    assert "checksum" in error_events[0]["error"].lower()
    assert "AAAUSDT-1d-2026-02.zip" in error_events[0]["error"]

    symbol_events = [e for e in events if "status" in e]
    assert len(symbol_events) == 1
    assert symbol_events[0]["status"] == "ok"
    assert symbol_events[0]["rows_written"] == len(_days_in_month(2026, 1))
    assert symbol_events[0]["failed_months"] == ["2026-02"]

    summary = next(e for e in events if "symbols" in e)
    assert summary["failed"] == 1

    assert _part_path(tmp_path, "AAAUSDT", dt.date(2026, 1, 1)).is_file()
    assert not (tmp_path / "staging" / "bars" / "symbol=AAAUSDT" / "date=2026-02-01").exists()


# -- An unexpected error gives one stderr line and no traceback ----------------


def test_an_unexpected_error_gives_one_stderr_line_and_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def raising_fetch(_url: str) -> HttpResponse:
        raise RuntimeError("the archive host reset the connection")

    exit_code = main(
        [
            "--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-01-31",
            "--source", "archive", "--symbols", "AAAUSDT",
        ],
        emit=lambda _line: None, fetch=raising_fetch, sleep=_no_sleep,
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    stderr_lines = captured.err.splitlines()
    assert len(stderr_lines) == 1
    assert "Traceback" not in captured.err
    assert "the archive host reset the connection" in stderr_lines[0]
    # Nothing was written: the very first fetch failed.
    assert not (tmp_path / "staging").exists()


def test_the_cli_flushes_each_progress_line(monkeypatch) -> None:
    """A redirected stdout is block-buffered: the 2026-10-07 archive backfill
    wrote 0 bytes to backfill.jsonl in 2.5 h of ranking. main's default emit
    flushes every line."""
    import builtins
    import inspect

    from nullius_ingest import bars_backfill

    seen: list[dict] = []
    monkeypatch.setattr(builtins, "print", lambda *args, **kwargs: seen.append(kwargs))
    inspect.signature(bars_backfill.main).parameters["emit"].default('{"phase": "rank"}')
    assert seen == [{"flush": True}]
