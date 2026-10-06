"""Backfill daily bars from Binance's public REST API into the lake's bars layout.

``additions_spec_real_campaign_path.xml``, "Market Data to Sealed Snapshot"
category, feature 1 — these tests are the feature's statement, read as
behaviour of :mod:`nullius_ingest.bars_backfill`:

* a backfilled bar lands at exactly
  ``<lake>/staging/bars/symbol=<S>/date=<D>/part-0.parquet``, with the
  columns the evaluator's own read path (``orchestrator._context._closes``)
  requires — ``symbol``, ``open_time``, ``close`` — one row per symbol and
  day;
* ``<lake>/universe.json`` is written beside ``staging/``, never inside it,
  and carries ``source``, ``selection_rule``, ``fetched_at``, ``first``,
  ``last``, ``symbols`` and ``survivorship_free`` (always ``false`` for this
  REST source);
* a non-positive close is skipped, not written, and the skip is counted;
* a 418/429 is retried after its own ``Retry-After`` delay and the backfill
  still succeeds;
* re-running with the same arguments rewrites byte-identical files;
* ``--top N`` ranks by 24h quote volume, excluding stablecoin bases and
  leveraged tokens.

No test here makes a network call: every fetch is a recorded, in-memory
callable.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from nullius_ingest.bars_backfill import (
    MAX_RETRIES,
    UNIVERSE_FILENAME,
    BarsBackfillError,
    HttpResponse,
    backfill_bars,
    main,
)

UTC = dt.UTC


# -- Fixture building ----------------------------------------------------------


def _binance_row(day: dt.date, close: str, *, trades: int = 10) -> list:
    """One Binance kline array, positional, at Binance's own field order."""
    open_ms = int(dt.datetime.combine(day, dt.time(0), tzinfo=UTC).timestamp() * 1000)
    close_ms = open_ms + 86_400_000 - 1
    return [
        open_ms,
        "100.00000000",
        "110.00000000",
        "90.00000000",
        close,
        "1000.50000000",
        close_ms,
        "87654.321",
        trades,
        "400.00000000",
        "40000.00",
        "0",
    ]


def _recording_fetch(
    klines_by_symbol: Mapping[str, list],
    *,
    exchange_info: object = None,
    tickers: object = None,
):
    """A fetch over recorded JSON: no network, ever."""
    calls: list[tuple[str, dict]] = []

    def fetch(path: str, params: Mapping[str, str]) -> HttpResponse:
        calls.append((path, dict(params)))
        if path == "/klines":
            rows = klines_by_symbol.get(params["symbol"], [])
            return HttpResponse(200, {}, json.dumps(rows).encode("utf-8"))
        if path == "/exchangeInfo":
            body = exchange_info if exchange_info is not None else {"symbols": []}
            return HttpResponse(200, {}, json.dumps(body).encode("utf-8"))
        if path == "/ticker/24hr":
            body = tickers if tickers is not None else []
            return HttpResponse(200, {}, json.dumps(body).encode("utf-8"))
        raise AssertionError(f"unexpected path {path!r}")

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _no_sleep(_seconds: float) -> None:
    return None


# -- Layout and schema ---------------------------------------------------------


def test_writes_bars_in_the_evaluators_layout_and_schema(tmp_path: Path) -> None:
    day1 = dt.date(2026, 1, 1)
    day2 = dt.date(2026, 1, 2)
    fetch = _recording_fetch(
        {"BTCUSDT": [_binance_row(day1, "61234.50"), _binance_row(day2, "61500.00")]}
    )

    results = backfill_bars(
        tmp_path,
        "2026-01-01",
        "2026-01-02",
        symbols=["BTCUSDT"],
        fetch=fetch,
        sleep=_no_sleep,
    )

    assert len(results) == 1
    assert results[0].symbol == "BTCUSDT"
    assert results[0].status == "ok"
    assert results[0].rows_written == 2
    assert results[0].skipped_non_positive_close == 0

    for day, close in ((day1, "61234.50"), (day2, "61500.00")):
        part = (
            tmp_path
            / "staging"
            / "bars"
            / "symbol=BTCUSDT"
            / f"date={day.isoformat()}"
            / "part-0.parquet"
        )
        assert part.is_file()
        table = pq.read_table(part)
        assert table.num_rows == 1
        assert set(table.column_names) >= {"symbol", "open_time", "close"}
        row = table.to_pylist()[0]
        assert row["symbol"] == "BTCUSDT"
        assert row["close"] == close
        assert row["open_time"].date() == day
        assert row["open_time"].tzinfo is not None


def test_creates_the_lake_root_when_it_does_not_yet_exist(tmp_path: Path) -> None:
    lake = tmp_path / "fresh-lake"
    assert not lake.exists()
    fetch = _recording_fetch({"BTCUSDT": [_binance_row(dt.date(2026, 1, 1), "61234.50")]})

    backfill_bars(lake, "2026-01-01", "2026-01-01", symbols=["BTCUSDT"], fetch=fetch, sleep=_no_sleep)

    assert (
        lake / "staging" / "bars" / "symbol=BTCUSDT" / "date=2026-01-01" / "part-0.parquet"
    ).is_file()
    assert (lake / UNIVERSE_FILENAME).is_file()


def test_no_stray_files_outside_the_bars_partition(tmp_path: Path) -> None:
    fetch = _recording_fetch({"ETHUSDT": [_binance_row(dt.date(2026, 2, 1), "1800.0")]})
    backfill_bars(
        tmp_path, "2026-02-01", "2026-02-01", symbols=["ETHUSDT"], fetch=fetch, sleep=_no_sleep
    )
    staging = tmp_path / "staging"
    files = sorted(p.relative_to(staging) for p in staging.rglob("*") if p.is_file())
    assert files == [
        Path("bars/symbol=ETHUSDT/date=2026-02-01/part-0.parquet"),
    ]


def test_paging_splits_a_range_wider_than_one_page_into_chunks(tmp_path: Path) -> None:
    first = dt.date(2020, 1, 1)
    last = dt.date(2023, 1, 1)
    total_days = (last - first).days + 1
    assert total_days > 1000  # the range this test exists to exercise

    calls: list[dict] = []

    def fetch(path: str, params: Mapping[str, str]) -> HttpResponse:
        assert path == "/klines"
        calls.append(dict(params))
        start_ms = int(params["startTime"])
        end_ms = int(params["endTime"])
        rows = []
        ms = start_ms
        while ms <= end_ms:
            day = dt.datetime.fromtimestamp(ms / 1000, tz=UTC).date()
            rows.append(_binance_row(day, "100.00"))
            ms += 86_400_000
        return HttpResponse(200, {}, json.dumps(rows).encode("utf-8"))

    results = backfill_bars(
        tmp_path,
        first.isoformat(),
        last.isoformat(),
        symbols=["BTCUSDT"],
        fetch=fetch,
        sleep=_no_sleep,
    )

    # No single request ever asks for more than Binance's 1000-candle page.
    assert len(calls) == 2
    for call in calls:
        span_days = (int(call["endTime"]) - int(call["startTime"]) + 1) / 86_400_000
        assert span_days <= 1000
    # The chunks are contiguous and non-overlapping: every day in the range
    # got exactly one candle, so the total written equals the whole range.
    assert results[0].rows_written == total_days
    assert results[0].skipped_non_positive_close == 0


# -- universe.json ---------------------------------------------------------------


def test_universe_json_carries_the_required_fields_beside_staging(tmp_path: Path) -> None:
    fetch = _recording_fetch(
        {
            "BTCUSDT": [_binance_row(dt.date(2026, 1, 1), "61234.50")],
            "ETHUSDT": [_binance_row(dt.date(2026, 1, 1), "1800.00")],
        }
    )
    fixed_clock = lambda: dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

    backfill_bars(
        tmp_path,
        "2026-01-01",
        "2026-01-01",
        symbols=["BTCUSDT", "ETHUSDT"],
        fetch=fetch,
        sleep=_no_sleep,
        clock=fixed_clock,
    )

    universe_path = tmp_path / UNIVERSE_FILENAME
    assert universe_path.is_file()
    # Beside staging, never inside it.
    assert not (tmp_path / "staging" / UNIVERSE_FILENAME).exists()

    payload = json.loads(universe_path.read_text(encoding="utf-8"))
    assert payload["source"] == "binance-rest"
    assert "explicit symbols" in payload["selection_rule"]
    assert payload["fetched_at"] == "2026-03-01T12:00:00+00:00"
    assert payload["first"] == "2026-01-01"
    assert payload["last"] == "2026-01-01"
    assert payload["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["survivorship_free"] is False


# -- A non-positive close is skipped and counted --------------------------------


@pytest.mark.parametrize("bad_close", ["0", "0.0", "-1.5"])
def test_a_non_positive_close_is_skipped_and_counted(tmp_path: Path, bad_close: str) -> None:
    good_day = dt.date(2026, 1, 1)
    bad_day = dt.date(2026, 1, 2)
    fetch = _recording_fetch(
        {"BTCUSDT": [_binance_row(good_day, "61234.50"), _binance_row(bad_day, bad_close)]}
    )

    results = backfill_bars(
        tmp_path,
        "2026-01-01",
        "2026-01-02",
        symbols=["BTCUSDT"],
        fetch=fetch,
        sleep=_no_sleep,
    )

    assert results[0].rows_written == 1
    assert results[0].skipped_non_positive_close == 1
    assert (
        tmp_path
        / "staging"
        / "bars"
        / "symbol=BTCUSDT"
        / f"date={good_day.isoformat()}"
        / "part-0.parquet"
    ).is_file()
    assert not (
        tmp_path
        / "staging"
        / "bars"
        / "symbol=BTCUSDT"
        / f"date={bad_day.isoformat()}"
    ).exists()


# -- A 429 then success ----------------------------------------------------------


def test_a_429_then_success_retries_and_succeeds(tmp_path: Path) -> None:
    day = dt.date(2026, 1, 1)
    rows = [_binance_row(day, "61234.50")]
    attempts = {"n": 0}
    sleeps: list[float] = []

    def fetch(path: str, params: Mapping[str, str]) -> HttpResponse:
        if path == "/klines":
            attempts["n"] += 1
            if attempts["n"] == 1:
                return HttpResponse(429, {"Retry-After": "2"}, b"rate limited")
            return HttpResponse(200, {}, json.dumps(rows).encode("utf-8"))
        raise AssertionError(f"unexpected path {path!r}")

    results = backfill_bars(
        tmp_path,
        "2026-01-01",
        "2026-01-01",
        symbols=["BTCUSDT"],
        fetch=fetch,
        sleep=sleeps.append,
    )

    assert attempts["n"] == 2
    assert results[0].status == "ok"
    assert results[0].rows_written == 1
    # The retry-after delay was honoured before the retry.
    assert 2.0 in sleeps


def test_a_418_or_429_past_the_bound_refuses_naming_the_symbol(tmp_path: Path) -> None:
    def always_429(path: str, params: Mapping[str, str]) -> HttpResponse:
        return HttpResponse(429, {"Retry-After": "0"}, b"rate limited")

    results = backfill_bars(
        tmp_path,
        "2026-01-01",
        "2026-01-01",
        symbols=["BTCUSDT"],
        fetch=always_429,
        sleep=_no_sleep,
    )

    assert results[0].status == "error"
    assert "BTCUSDT" in results[0].error
    assert str(MAX_RETRIES) in results[0].error
    # The run still writes universe.json even though the symbol was refused.
    assert (tmp_path / UNIVERSE_FILENAME).is_file()


# -- Idempotent rerun ------------------------------------------------------------


def test_rerunning_with_the_same_arguments_rewrites_identical_files(tmp_path: Path) -> None:
    fetch = _recording_fetch(
        {"BTCUSDT": [_binance_row(dt.date(2026, 1, 1), "61234.50")]}
    )
    fixed_clock = lambda: dt.datetime(2026, 3, 1, tzinfo=UTC)
    part = (
        tmp_path
        / "staging"
        / "bars"
        / "symbol=BTCUSDT"
        / "date=2026-01-01"
        / "part-0.parquet"
    )

    backfill_bars(
        tmp_path, "2026-01-01", "2026-01-01", symbols=["BTCUSDT"],
        fetch=fetch, sleep=_no_sleep, clock=fixed_clock,
    )
    first_bytes = part.read_bytes()
    first_universe = (tmp_path / UNIVERSE_FILENAME).read_bytes()

    backfill_bars(
        tmp_path, "2026-01-01", "2026-01-01", symbols=["BTCUSDT"],
        fetch=fetch, sleep=_no_sleep, clock=fixed_clock,
    )
    second_bytes = part.read_bytes()
    second_universe = (tmp_path / UNIVERSE_FILENAME).read_bytes()

    assert first_bytes == second_bytes
    assert first_universe == second_universe


# -- --top N selection -----------------------------------------------------------


def _exchange_symbol(symbol, base, quote, *, status="TRADING", spot=True):
    return {
        "symbol": symbol,
        "baseAsset": base,
        "quoteAsset": quote,
        "status": status,
        "isSpotTradingAllowed": spot,
    }


def test_top_n_ranks_by_volume_excluding_stablecoins_and_leveraged_tokens(
    tmp_path: Path,
) -> None:
    exchange_info = {
        "symbols": [
            _exchange_symbol("BTCUSDT", "BTC", "USDT"),
            _exchange_symbol("ETHUSDT", "ETH", "USDT"),
            _exchange_symbol("BNBUSDT", "BNB", "USDT"),
            _exchange_symbol("USDCUSDT", "USDC", "USDT"),  # stablecoin base
            _exchange_symbol("BTCUPUSDT", "BTCUP", "USDT"),  # leveraged token
            _exchange_symbol("ADAUSDT", "ADA", "USDT", status="BREAK"),  # not trading
            _exchange_symbol("SOLUSDT", "SOL", "USDT", spot=False),  # no spot
            _exchange_symbol("ETHBTC", "ETH", "BTC"),  # not USDT-quoted
        ]
    }
    tickers = [
        {"symbol": "BTCUSDT", "quoteVolume": "500000"},
        {"symbol": "ETHUSDT", "quoteVolume": "900000"},
        {"symbol": "BNBUSDT", "quoteVolume": "100000"},
        {"symbol": "USDCUSDT", "quoteVolume": "999999999"},
        {"symbol": "BTCUPUSDT", "quoteVolume": "999999999"},
    ]
    klines_by_symbol = {
        "ETHUSDT": [_binance_row(dt.date(2026, 1, 1), "1800.0")],
        "BTCUSDT": [_binance_row(dt.date(2026, 1, 1), "61234.5")],
    }
    fetch = _recording_fetch(
        klines_by_symbol, exchange_info=exchange_info, tickers=tickers
    )

    results = backfill_bars(
        tmp_path, "2026-01-01", "2026-01-01", top=2, fetch=fetch, sleep=_no_sleep
    )

    assert [r.symbol for r in results] == ["ETHUSDT", "BTCUSDT"]
    payload = json.loads((tmp_path / UNIVERSE_FILENAME).read_text(encoding="utf-8"))
    assert payload["symbols"] == ["ETHUSDT", "BTCUSDT"]
    assert "top 2" in payload["selection_rule"]
    assert "stablecoin" in payload["selection_rule"]
    assert "leveraged" in payload["selection_rule"]


# -- The command line -------------------------------------------------------------


def test_main_prints_one_json_line_per_symbol_and_a_summary(tmp_path: Path) -> None:
    fetch = _recording_fetch(
        {"BTCUSDT": [_binance_row(dt.date(2026, 1, 1), "61234.50")]}
    )
    lines: list[str] = []

    exit_code = main(
        [
            "--lake", str(tmp_path),
            "--first", "2026-01-01",
            "--last", "2026-01-01",
            "--symbols", "BTCUSDT",
        ],
        emit=lines.append,
        fetch=fetch,
        sleep=_no_sleep,
    )

    assert exit_code == 0
    assert len(lines) == 2
    symbol_line = json.loads(lines[0])
    assert symbol_line == {
        "symbol": "BTCUSDT",
        "status": "ok",
        "rows_written": 1,
        "skipped_non_positive_close": 0,
    }
    summary = json.loads(lines[1])
    assert summary == {
        "symbols": 1,
        "failed": 0,
        "rows_written": 1,
        "skipped_non_positive_close": 0,
    }


def test_main_requires_exactly_one_of_symbols_or_top(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--lake", str(tmp_path), "--first", "2026-01-01", "--last", "2026-01-01"])


def test_main_exits_refused_when_a_symbol_errors(tmp_path: Path) -> None:
    def always_429(path: str, params: Mapping[str, str]) -> HttpResponse:
        return HttpResponse(429, {"Retry-After": "0"}, b"rate limited")

    lines: list[str] = []
    exit_code = main(
        [
            "--lake", str(tmp_path),
            "--first", "2026-01-01",
            "--last", "2026-01-01",
            "--symbols", "BTCUSDT",
        ],
        emit=lines.append,
        fetch=always_429,
        sleep=_no_sleep,
    )
    assert exit_code == 1
    symbol_line = json.loads(lines[0])
    assert symbol_line["status"] == "error"


def test_backfill_bars_refuses_neither_or_both_of_symbols_and_top(tmp_path: Path) -> None:
    with pytest.raises(BarsBackfillError):
        backfill_bars(tmp_path, "2026-01-01", "2026-01-01")
    with pytest.raises(BarsBackfillError):
        backfill_bars(
            tmp_path, "2026-01-01", "2026-01-01", symbols=["BTCUSDT"], top=1
        )


def test_backfill_bars_refuses_first_after_last(tmp_path: Path) -> None:
    with pytest.raises(BarsBackfillError, match="after"):
        backfill_bars(
            tmp_path, "2026-01-02", "2026-01-01", symbols=["BTCUSDT"]
        )
