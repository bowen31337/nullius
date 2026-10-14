"""additions_spec_shadow_eval.xml, "Forward Shadow" feature 2.

System scores the forward VST shadow against its pre-registered primary
outcome from the book history and the shadow lake, so that the test's
verdict is computed by fixed code rather than by hand:
``python -m orchestrator.shadow_eval`` reads every qualifying
``history/shadow-*.json`` book, maps its BingX-symbol weights back to lake
symbols, walks the scored window day by day pricing the pre-registered
``r_d`` formula over whichever book is in force, and (when ``--vst-db`` is
given) checks execution validity against the venue's own tables.

Follows :mod:`test_shadow_cli`'s sealed-snapshot pattern (``_write_futbars``
into staging, then ``SnapshotService(lake_root).seal(...)``) and adds a
funding writer of its own. No test opens a network connection or writes
outside a pytest temporary directory; every fixture builds its own lake,
history directory and (where needed) sqlite file, so the suite is safe
under pytest-xdist.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from orchestrator import shadow_eval
from snapshot import SnapshotService

_TS = pa.timestamp("us", tz="UTC")

#: Every multi-book test must keep this constant across its books: the
#: pre-registration pins the traded nodes, so two books with different
#: node-hash suffixes are a deviation shadow_eval refuses outright.
NODE_HASH = "abc123abc123"


def _stamp(day: dt.date) -> Any:
    return dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)


def _write_futbars(staging: Path, symbol: str, day: dt.date, close: float) -> None:
    partition = staging / "futbars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "fut_close": [str(close)],
                "fut_volume": ["1000.0"],
                "taker_buy_volume": ["400.0"],
                "quote_volume": ["100000.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_funding(
    staging: Path,
    symbol: str,
    day: dt.date,
    funding_rate_sum: float,
    *,
    funding_rate_last: float | None = None,
    n_settlements: int = 3,
) -> None:
    partition = staging / "funding" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "funding_rate_sum": [str(funding_rate_sum)],
                "funding_rate_last": [
                    str(funding_rate_last if funding_rate_last is not None else funding_rate_sum)
                ],
                "n_settlements": pa.array([n_settlements], type=pa.int64()),
            }
        ),
        partition / "part-0.parquet",
    )


def _seal_snapshot(
    tmp_path: Path,
    futbars: Mapping[str, Mapping[dt.date, float]] | None = None,
    funding: Mapping[str, Mapping[dt.date, float]] | None = None,
) -> Path:
    lake_root = tmp_path / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    for symbol, by_day in (futbars or {}).items():
        for day, close in by_day.items():
            _write_futbars(staging, symbol, day, close)
    for symbol, by_day in (funding or {}).items():
        for day, rate in by_day.items():
            _write_funding(staging, symbol, day, rate)
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2027, 1, 20, tzinfo=dt.UTC))
    return sealed.path


def _write_book(
    history_dir: Path,
    *,
    decision_date: dt.date,
    weights: Mapping[str, float],
    node_hash: str = NODE_HASH,
) -> str:
    book_id = f"shadow-{decision_date.isoformat()}-{node_hash}"
    document = {
        "book_id": book_id,
        "rebalance_ts": dt.datetime.combine(decision_date, dt.time(0), tzinfo=dt.UTC).isoformat(),
        "account": "bingx-vst",
        "margin_mode": "isolated",
        "equity_usdt": "10000.0",
        "weights": dict(weights),
        "decay_horizon_seconds": {},
        "expected_fill_seconds": 120,
        "positions": {},
        "originating_signal_ids": [],
    }
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{book_id}.json").write_text(json.dumps(document), encoding="utf-8")
    return book_id


# -- vst.db: a minimal fixture carrying only the columns shadow_eval reads --


def _init_vst_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE router_bingx_slot_completion "
            "(book_id TEXT, slot TEXT, finished_at TEXT, exit_code INTEGER)"
        )
        connection.execute("CREATE TABLE router_order_record (book_id TEXT, symbol TEXT)")
        connection.execute(
            "CREATE TABLE router_daily_opening_equity (day TEXT, opening_equity TEXT)"
        )
        connection.execute("CREATE TABLE risk_daily_loss_halt (breached_at TEXT)")
        connection.commit()


def _insert_completion(
    path: Path, book_id: str, slot: dt.datetime, finished_at: dt.datetime, exit_code: int = 0
) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "INSERT INTO router_bingx_slot_completion (book_id, slot, finished_at, exit_code) "
            "VALUES (?, ?, ?, ?)",
            (book_id, slot.isoformat(), finished_at.isoformat(), exit_code),
        )
        connection.commit()


def _insert_order(path: Path, book_id: str, symbol: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "INSERT INTO router_order_record (book_id, symbol) VALUES (?, ?)", (book_id, symbol)
        )
        connection.commit()


def _slot_starts(first_day: dt.date, last_day_exclusive: dt.date):
    cursor = dt.datetime.combine(first_day, dt.time(0), tzinfo=dt.UTC)
    end = dt.datetime.combine(last_day_exclusive, dt.time(0), tzinfo=dt.UTC)
    while cursor < end:
        yield cursor
        cursor += dt.timedelta(hours=4)


def _run_main(args: list[str], env: Mapping[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    printed: list[str] = []
    exit_code = shadow_eval.main(args, env=env or {}, emit=printed.append)
    result = json.loads(printed[0]) if printed else {}
    return exit_code, result


# -- the "1000" inverse mapping -----------------------------------------------


def test_invert_to_lake_symbol_handles_plain_and_1000_prefixed_symbols() -> None:
    assert shadow_eval._invert_to_lake_symbol("PEPE-USDT", {"PEPEUSDT"}) == "PEPEUSDT"
    # "1000X-USDT" prefers "1000XUSDT" when that partition exists.
    assert (
        shadow_eval._invert_to_lake_symbol("1000PEPE-USDT", {"1000PEPEUSDT", "PEPEUSDT"})
        == "1000PEPEUSDT"
    )
    # ... and falls back to the stripped spelling when it does not.
    assert shadow_eval._invert_to_lake_symbol("1000PEPE-USDT", {"PEPEUSDT"}) == "PEPEUSDT"


def test_invert_to_lake_symbol_refuses_a_missing_or_malformed_inverse() -> None:
    with pytest.raises(shadow_eval.ShadowEvalError):
        shadow_eval._invert_to_lake_symbol("1000PEPE-USDT", {"OTHERUSDT"})
    with pytest.raises(shadow_eval.ShadowEvalError):
        shadow_eval._invert_to_lake_symbol("not-a-bingx-symbol", {"PEPEUSDT"})


# -- the conflicting-book refusals ---------------------------------------------


def test_refuses_two_books_sharing_a_decision_date_with_different_ids(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    decision_date = dt.date(2026, 11, 1)
    # Two files naming the same decision date but different node hashes:
    # book_id differs, and so, inescapably, does the node hash.
    _write_book(history, decision_date=decision_date, weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5}, node_hash="aaaaaaaaaaaa")
    _write_book(history, decision_date=decision_date, weights={"BTC-USDT": 0.4, "ETH-USDT": -0.4}, node_hash="bbbbbbbbbbbb")
    snapshot = tmp_path / "unused-snapshot"
    snapshot.mkdir()

    exit_code = shadow_eval.main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", decision_date.isoformat(),
        ],
        env={},
        emit=lambda _line: None,
    )
    assert exit_code == shadow_eval.EXIT_REFUSED


def test_refuses_when_node_hash_suffix_differs_across_decision_dates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    _write_book(
        history,
        decision_date=dt.date(2026, 11, 1),
        weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5},
        node_hash="aaaaaaaaaaaa",
    )
    _write_book(
        history,
        decision_date=dt.date(2026, 11, 15),
        weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5},
        node_hash="bbbbbbbbbbbb",
    )
    snapshot = tmp_path / "unused-snapshot"
    snapshot.mkdir()

    exit_code = shadow_eval.main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", "2026-11-01",
        ],
        env={},
        emit=lambda _line: None,
    )
    assert exit_code == shadow_eval.EXIT_REFUSED
    err = capsys.readouterr().err
    assert err.count("\n") == 1  # one stderr line, no traceback
    assert shadow_eval.SHADOW_EVAL_CODE in err


# -- missing directories: exit 2 --------------------------------------------


def test_exits_missing_when_history_directory_is_absent(tmp_path: Path) -> None:
    exit_code = shadow_eval.main(
        ["--history", str(tmp_path / "nope"), "--snapshot", str(tmp_path)],
        env={},
        emit=lambda _line: None,
    )
    assert exit_code == shadow_eval.EXIT_MISSING


def test_exits_missing_when_snapshot_directory_is_absent(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    _write_book(history, decision_date=dt.date(2026, 11, 1), weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5})
    exit_code = shadow_eval.main(
        [
            "--history", str(history),
            "--snapshot", str(tmp_path / "nope"),
            "--first-decision", "2026-11-01",
        ],
        env={},
        emit=lambda _line: None,
    )
    assert exit_code == shadow_eval.EXIT_MISSING


# -- the hand-computed 3-day r_d series ----------------------------------------
#
# One book, two legs, dollar-neutral (BTC +0.5 / ETH -0.5). BTC rises 10% a
# day and ETH falls 10% a day, so every day's price term is exactly 0.10;
# funding is constant per leg, so the funding term is exactly -0.0015 a day;
# and the book enters cold on its first in-force day, so only that day
# charges turnover (cost = 0.0005 * gross 1.0 = 0.0005).


_DECISION_DATE = dt.date(2026, 12, 30)
_F = _DECISION_DATE + dt.timedelta(days=2)  # nominal D+2: 2027-01-01
_WEIGHTS = {"BTC-USDT": 0.5, "ETH-USDT": -0.5}
_BTC_CLOSES = {
    _F - dt.timedelta(days=1): 100.0,
    _F: 110.0,
    _F + dt.timedelta(days=1): 121.0,
    _F + dt.timedelta(days=2): 133.1,
}
_ETH_CLOSES = {
    _F - dt.timedelta(days=1): 100.0,
    _F: 90.0,
    _F + dt.timedelta(days=1): 81.0,
    _F + dt.timedelta(days=2): 72.9,
}
_BTC_FUNDING = {_F: 0.001, _F + dt.timedelta(days=1): 0.001, _F + dt.timedelta(days=2): 0.001}
_ETH_FUNDING = {_F: -0.002, _F + dt.timedelta(days=1): -0.002, _F + dt.timedelta(days=2): -0.002}


def _three_day_world(tmp_path: Path) -> tuple[Path, Path]:
    history = tmp_path / "history"
    history.mkdir()
    _write_book(history, decision_date=_DECISION_DATE, weights=_WEIGHTS)
    snapshot = _seal_snapshot(
        tmp_path,
        futbars={"BTCUSDT": _BTC_CLOSES, "ETHUSDT": _ETH_CLOSES},
        funding={"BTCUSDT": _BTC_FUNDING, "ETHUSDT": _ETH_FUNDING},
    )
    return history, snapshot


def _expected_three_day_series() -> list[dict[str, float]]:
    days = [_F, _F + dt.timedelta(days=1), _F + dt.timedelta(days=2)]
    rows = []
    cum = 0.0
    prev_weights: dict[str, float] = {}
    for day in days:
        price = 0.5 * (_BTC_CLOSES[day] / _BTC_CLOSES[day - dt.timedelta(days=1)] - 1.0) + (
            -0.5
        ) * (_ETH_CLOSES[day] / _ETH_CLOSES[day - dt.timedelta(days=1)] - 1.0)
        funding = -(0.5 * _BTC_FUNDING[day] + (-0.5) * _ETH_FUNDING[day])
        turnover = sum(
            abs(_WEIGHTS.get(symbol, 0.0) - prev_weights.get(symbol, 0.0))
            for symbol in set(_WEIGHTS) | set(prev_weights)
        )
        cost = 0.0005 * turnover
        r = price + funding - cost
        cum += r
        rows.append({"price": price, "funding": funding, "cost": cost, "r": r, "cum": cum})
        prev_weights = dict(_WEIGHTS)
    return rows


def test_hand_computed_three_day_r_series(tmp_path: Path) -> None:
    history, snapshot = _three_day_world(tmp_path)
    window_start = dt.datetime.combine(
        _DECISION_DATE + dt.timedelta(days=1), dt.time(12, 5), tzinfo=dt.UTC
    )
    window_end = dt.datetime.combine(
        _F + dt.timedelta(days=3), dt.time(0, 0, 1), tzinfo=dt.UTC
    )
    exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", _DECISION_DATE.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    assert exit_code == shadow_eval.EXIT_OK
    assert result["status"] == "final"
    assert result["n_days"] == 3

    expected = _expected_three_day_series()
    assert result["price_return"] == pytest.approx(sum(r["price"] for r in expected), abs=1e-12)
    assert result["funding_return"] == pytest.approx(sum(r["funding"] for r in expected), abs=1e-12)
    assert result["cost_return"] == pytest.approx(sum(r["cost"] for r in expected), abs=1e-12)
    assert result["cum_return"] == pytest.approx(expected[-1]["cum"], abs=1e-12)
    # Entry turnover: only the first in-force day charges a cost.
    assert expected[0]["cost"] == pytest.approx(0.0005, abs=1e-12)
    assert expected[1]["cost"] == pytest.approx(0.0, abs=1e-12)
    assert expected[2]["cost"] == pytest.approx(0.0, abs=1e-12)
    # Positive, high-IR scenario by construction (near-constant daily return).
    assert result["cum_return"] > 0.0
    assert result["ir_t"] >= 1.0
    assert result["verdict"] == "pass"
    assert result["realised_beta"] is None  # n_days (3) < 10


def test_daily_out_writes_the_pinned_columns(tmp_path: Path) -> None:
    history, snapshot = _three_day_world(tmp_path)
    window_start = dt.datetime.combine(
        _DECISION_DATE + dt.timedelta(days=1), dt.time(12, 5), tzinfo=dt.UTC
    )
    window_end = dt.datetime.combine(
        _F + dt.timedelta(days=3), dt.time(0, 0, 1), tzinfo=dt.UTC
    )
    daily_out = tmp_path / "daily.csv"
    exit_code, _result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", _DECISION_DATE.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
            "--daily-out", str(daily_out),
        ]
    )
    assert exit_code == shadow_eval.EXIT_OK

    with daily_out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["date", "book_id", "price", "funding", "cost", "r", "cum"]
    assert len(rows) == 1 + 3
    expected = _expected_three_day_series()
    book_id = f"shadow-{_DECISION_DATE.isoformat()}-{NODE_HASH}"
    for row, exp in zip(rows[1:], expected):
        assert row[1] == book_id
        assert float(row[2]) == pytest.approx(exp["price"], abs=1e-12)
        assert float(row[3]) == pytest.approx(exp["funding"], abs=1e-12)
        assert float(row[4]) == pytest.approx(exp["cost"], abs=1e-12)
        assert float(row[5]) == pytest.approx(exp["r"], abs=1e-12)
        assert float(row[6]) == pytest.approx(exp["cum"], abs=1e-12)


def test_validity_is_unchecked_without_vst_db(tmp_path: Path) -> None:
    history, snapshot = _three_day_world(tmp_path)
    window_start = dt.datetime.combine(
        _DECISION_DATE + dt.timedelta(days=1), dt.time(12, 5), tzinfo=dt.UTC
    )
    window_end = dt.datetime.combine(
        _F + dt.timedelta(days=3), dt.time(0, 0, 1), tzinfo=dt.UTC
    )
    _exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", _DECISION_DATE.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    assert result["validity"] == "unchecked"
    assert result["validity_reasons"] == []
    assert result["n_daily_loss_halts"] is None
    assert result["vst_equity_return"] is None


# -- interim vs final status, verdict pending while interim --------------------


def test_interim_status_stops_at_the_first_unscorable_day_and_verdict_is_pending(
    tmp_path: Path,
) -> None:
    history, snapshot = _three_day_world(tmp_path)
    window_start = dt.datetime.combine(
        _DECISION_DATE + dt.timedelta(days=1), dt.time(12, 5), tzinfo=dt.UTC
    )
    # One day further than the lake carries data for.
    window_end = dt.datetime.combine(
        _F + dt.timedelta(days=4), dt.time(0, 0, 1), tzinfo=dt.UTC
    )
    _exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", _DECISION_DATE.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    assert result["status"] == "interim"
    assert result["verdict"] == "pending"
    assert result["n_days"] == 3  # the three days the lake does carry


def test_fail_verdict_when_final_and_cumulative_return_is_negative(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    decision_date = dt.date(2026, 8, 1)
    f = decision_date + dt.timedelta(days=2)  # 2026-08-03
    weights = {"BTC-USDT": 0.5, "ETH-USDT": -0.5}
    _write_book(history, decision_date=decision_date, weights=weights)

    days = [f - dt.timedelta(days=1) + dt.timedelta(days=i) for i in range(4)]
    # BTC (long leg) falls 5%/day, ETH (short leg) rises 5%/day: the
    # dollar-neutral book loses money every single day by construction.
    btc = {days[0]: 100.0, days[1]: 95.0, days[2]: 90.25, days[3]: 85.7375}
    eth = {days[0]: 100.0, days[1]: 105.0, days[2]: 110.25, days[3]: 115.7625}
    funding_zero = {day: 0.0 for day in days[1:]}
    snapshot = _seal_snapshot(
        tmp_path,
        futbars={"BTCUSDT": btc, "ETHUSDT": eth},
        funding={"BTCUSDT": funding_zero, "ETHUSDT": funding_zero},
    )

    window_start = dt.datetime.combine(
        decision_date + dt.timedelta(days=1), dt.time(12, 5), tzinfo=dt.UTC
    )
    window_end = dt.datetime.combine(days[-1] + dt.timedelta(days=1), dt.time(0, 0, 1), tzinfo=dt.UTC)
    _exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", decision_date.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    assert result["status"] == "final"
    assert result["n_days"] == 3
    assert result["cum_return"] < 0.0
    assert result["verdict"] == "fail"


# -- the switch of books on F: turnover charged exactly once -------------------


def test_switch_of_books_charges_turnover_exactly_once(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    decision_1 = dt.date(2026, 11, 1)
    decision_2 = dt.date(2026, 11, 4)
    f1 = decision_1 + dt.timedelta(days=2)  # 2026-11-03
    f2 = decision_2 + dt.timedelta(days=2)  # 2026-11-06
    weights_1 = {"BTC-USDT": 0.5, "ETH-USDT": -0.5}
    weights_2 = {"BTC-USDT": 0.2, "ETH-USDT": -0.2}
    _write_book(history, decision_date=decision_1, weights=weights_1)
    _write_book(history, decision_date=decision_2, weights=weights_2)

    days = [f1 - dt.timedelta(days=1) + dt.timedelta(days=i) for i in range(7)]
    btc = {day: 100.0 for day in days}  # flat prices: isolate the cost term
    eth = {day: 50.0 for day in days}
    funding_zero = {day: 0.0 for day in days}
    snapshot = _seal_snapshot(
        tmp_path,
        futbars={"BTCUSDT": btc, "ETHUSDT": eth},
        funding={"BTCUSDT": funding_zero, "ETHUSDT": funding_zero},
    )

    window_start = dt.datetime.combine(
        decision_1 + dt.timedelta(days=1), dt.time(12, 5), tzinfo=dt.UTC
    )
    window_end = dt.datetime.combine(f2 + dt.timedelta(days=2), dt.time(0, 0, 1), tzinfo=dt.UTC)
    daily_out = tmp_path / "daily.csv"
    exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", decision_1.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
            "--daily-out", str(daily_out),
        ]
    )
    assert exit_code == shadow_eval.EXIT_OK
    assert result["status"] == "final"

    with daily_out.open(newline="", encoding="utf-8") as handle:
        rows = {row["date"]: row for row in csv.DictReader(handle)}

    assert float(rows[f1.isoformat()]["cost"]) == pytest.approx(0.0005, abs=1e-12)  # entry
    assert float(rows[(f1 + dt.timedelta(days=1)).isoformat()]["cost"]) == pytest.approx(0.0, abs=1e-12)
    assert float(rows[(f1 + dt.timedelta(days=2)).isoformat()]["cost"]) == pytest.approx(0.0, abs=1e-12)
    assert float(rows[f2.isoformat()]["cost"]) == pytest.approx(0.0005 * 0.6, abs=1e-12)  # the switch
    assert float(rows[(f2 + dt.timedelta(days=1)).isoformat()]["cost"]) == pytest.approx(0.0, abs=1e-12)
    # Price and funding are flat/zero by construction, so every r_d is -cost.
    for row in rows.values():
        assert float(row["r"]) == pytest.approx(-float(row["cost"]), abs=1e-12)
    # book_id reported for the switch day is the new book, not the old one.
    assert rows[f2.isoformat()]["book_id"] == f"shadow-{decision_2.isoformat()}-{NODE_HASH}"
    assert rows[f1.isoformat()]["book_id"] == f"shadow-{decision_1.isoformat()}-{NODE_HASH}"


# -- a missing leg close: counted, not crashed ---------------------------------


def test_missing_leg_close_is_counted_rather_than_crashing(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    decision_date = dt.date(2026, 10, 25)
    f = decision_date + dt.timedelta(days=2)  # 2026-10-27
    weights = {"BTC-USDT": 0.5, "ETH-USDT": -0.5}
    _write_book(history, decision_date=decision_date, weights=weights)

    day0, day1, day2 = f - dt.timedelta(days=1), f, f + dt.timedelta(days=1)
    btc = {day0: 100.0, day1: 105.0, day2: 110.0}
    eth = {day0: 50.0, day1: 52.0}  # ETH's close on day2 is simply absent
    funding = {day1: 0.0, day2: 0.0}
    snapshot = _seal_snapshot(
        tmp_path,
        futbars={"BTCUSDT": btc, "ETHUSDT": eth},
        funding={"BTCUSDT": funding, "ETHUSDT": funding},
    )

    window_start = dt.datetime.combine(
        decision_date + dt.timedelta(days=1), dt.time(12, 5), tzinfo=dt.UTC
    )
    window_end = dt.datetime.combine(day2 + dt.timedelta(days=1), dt.time(0, 0, 1), tzinfo=dt.UTC)
    exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", decision_date.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    assert exit_code == shadow_eval.EXIT_OK
    assert result["status"] == "final"
    assert result["n_days"] == 2
    assert result["n_missing_legdays"] == 1
    assert result["missing_legdays"] == [
        {"symbol": "ETHUSDT", "date": day2.isoformat(), "missing": ["close"]}
    ]
    # day2's price term is BTC-only (ETH contributed 0, not a crash): the
    # aggregate price_return is day1's full two-leg move plus day2's
    # BTC-only move.
    day1_price = 0.5 * (105.0 / 100.0 - 1.0) + (-0.5) * (52.0 / 50.0 - 1.0)
    day2_price = 0.5 * (110.0 / 105.0 - 1.0)
    assert result["price_return"] == pytest.approx(day1_price + day2_price, abs=1e-9)


# -- F from vst.db vs the nominal D+2 ------------------------------------------


def test_in_force_from_reads_vst_db_when_given_else_falls_back_to_nominal(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    decision_1 = dt.date(2026, 9, 1)
    decision_2 = dt.date(2026, 9, 15)
    book_1 = _write_book(history, decision_date=decision_1, weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5})
    book_2 = _write_book(history, decision_date=decision_2, weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5})

    snapshot = _seal_snapshot(tmp_path)  # no lake data needed for this check
    db_path = tmp_path / "vst.db"
    _init_vst_db(db_path)
    # book_1 traded: earliest completion finishes same day, at 06:00 UTC.
    _insert_completion(
        db_path,
        book_1,
        dt.datetime(2026, 9, 1, 4, tzinfo=dt.UTC),
        dt.datetime(2026, 9, 1, 6, tzinfo=dt.UTC),
        exit_code=0,
    )
    # book_2 has no completion row at all.

    window_start = dt.datetime(2026, 9, 1, 12, 5, tzinfo=dt.UTC)
    window_end = dt.datetime(2026, 9, 20, 0, 0, 1, tzinfo=dt.UTC)
    _exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--vst-db", str(db_path),
            "--first-decision", decision_1.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    by_id = {row["book_id"]: row for row in result["books"]}
    assert by_id[book_1]["in_force_from"] == "2026-09-02"
    assert by_id[book_1]["in_force_rule"] == "traded"
    assert by_id[book_2]["in_force_from"] == "2026-09-17"
    assert by_id[book_2]["in_force_rule"] == "nominal"


# -- leg coverage, including the carried-position rule -------------------------


def test_leg_coverage_credits_a_position_carried_from_an_earlier_book(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    book_1 = shadow_eval._HistoryBook(
        book_id="shadow-2026-09-01-" + NODE_HASH,
        decision_date=dt.date(2026, 9, 1),
        node_hash=NODE_HASH,
        weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5},
        path=Path("unused-1"),
    )
    book_2 = shadow_eval._HistoryBook(
        book_id="shadow-2026-09-15-" + NODE_HASH,
        decision_date=dt.date(2026, 9, 15),
        node_hash=NODE_HASH,
        weights={"BTC-USDT": 0.5, "ETH-USDT": -0.3, "SOL-USDT": 0.2},
        path=Path("unused-2"),
    )
    db_path = tmp_path / "vst.db"
    _init_vst_db(db_path)
    _insert_order(db_path, book_1.book_id, "BTC-USDT")
    _insert_order(db_path, book_1.book_id, "ETH-USDT")
    # book_2's BTC-USDT weight is unchanged from book_1: no fresh order was
    # needed, so only ETH-USDT (changed) and SOL-USDT (new) get rows under
    # book_2's own id.
    _insert_order(db_path, book_2.book_id, "ETH-USDT")
    _insert_order(db_path, book_2.book_id, "SOL-USDT")

    with closing(sqlite3.connect(db_path)) as connection:
        coverage, covered, total = shadow_eval._leg_coverage(connection, [book_1, book_2])

    assert total == 5
    assert covered == 5  # book_2's BTC-USDT is credited via book_1's row
    assert coverage == pytest.approx(1.0, abs=1e-12)


def test_leg_coverage_does_not_credit_a_symbol_placed_nowhere(tmp_path: Path) -> None:
    book_1 = shadow_eval._HistoryBook(
        book_id="shadow-2026-09-01-" + NODE_HASH,
        decision_date=dt.date(2026, 9, 1),
        node_hash=NODE_HASH,
        weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5},
        path=Path("unused"),
    )
    db_path = tmp_path / "vst.db"
    _init_vst_db(db_path)
    _insert_order(db_path, book_1.book_id, "BTC-USDT")
    # ETH-USDT is never recorded under any book_id.

    with closing(sqlite3.connect(db_path)) as connection:
        coverage, covered, total = shadow_eval._leg_coverage(connection, [book_1])

    assert (covered, total) == (1, 2)
    assert coverage == pytest.approx(0.5, abs=1e-12)


# -- two consecutive failed slots make the result invalid ----------------------


def test_two_consecutive_failed_slots_make_validity_invalid(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    decision_date = dt.date(2026, 12, 1)
    book_id = _write_book(
        history, decision_date=decision_date, weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5}
    )

    days = [dt.date(2026, 12, 1) + dt.timedelta(days=i) for i in range(4)]
    btc = {day: 100.0 for day in days}
    eth = {day: 50.0 for day in days}
    funding = {day: 0.0 for day in days[1:]}
    snapshot = _seal_snapshot(
        tmp_path,
        futbars={"BTCUSDT": btc, "ETHUSDT": eth},
        funding={"BTCUSDT": funding, "ETHUSDT": funding},
    )

    db_path = tmp_path / "vst.db"
    _init_vst_db(db_path)
    # The book starts trading on 2026-12-01: F = 2026-12-02.
    _insert_completion(
        db_path,
        book_id,
        dt.datetime(2026, 12, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 12, 1, 2, tzinfo=dt.UTC),
        exit_code=0,
    )
    _insert_order(db_path, book_id, "BTC-USDT")
    _insert_order(db_path, book_id, "ETH-USDT")

    failing = {dt.datetime(2026, 12, 3, 8, tzinfo=dt.UTC), dt.datetime(2026, 12, 3, 12, tzinfo=dt.UTC)}
    for slot in _slot_starts(dt.date(2026, 12, 2), dt.date(2026, 12, 5)):
        if slot in failing:
            continue
        _insert_completion(db_path, book_id, slot, slot + dt.timedelta(hours=1), exit_code=0)

    window_start = dt.datetime(2026, 12, 1, 12, 5, tzinfo=dt.UTC)
    window_end = dt.datetime(2026, 12, 5, 0, 0, 1, tzinfo=dt.UTC)
    _exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--vst-db", str(db_path),
            "--first-decision", decision_date.isoformat(),
            "--grid-anchor", decision_date.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    assert result["status"] == "final"
    assert result["n_days"] == 3
    assert result["validity"] == "invalid"
    assert any("consecutive" in reason for reason in result["validity_reasons"])


def test_low_leg_coverage_makes_validity_invalid_end_to_end(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    decision_date = dt.date(2026, 9, 1)
    _write_book(history, decision_date=decision_date, weights={"BTC-USDT": 0.5, "ETH-USDT": -0.5})
    snapshot = _seal_snapshot(tmp_path)
    db_path = tmp_path / "vst.db"
    _init_vst_db(db_path)
    # Neither leg was ever recorded as placed under any book_id.

    window_start = dt.datetime(2026, 9, 1, 12, 5, tzinfo=dt.UTC)
    window_end = dt.datetime(2026, 9, 5, 0, 0, 1, tzinfo=dt.UTC)
    _exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--vst-db", str(db_path),
            "--first-decision", decision_date.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    assert result["validity"] == "invalid"
    assert any("coverage" in reason for reason in result["validity_reasons"])


# -- forward_ic_10d: the Spearman correlation of a book's weights with its --
# -- own legs' F-1 -> F+9 returns, or null when a leg's close is missing   --


def test_forward_ic_10d_is_the_spearman_correlation_of_weights_and_forward_returns(
    tmp_path: Path,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    decision_1 = dt.date(2026, 11, 1)
    f1 = decision_1 + dt.timedelta(days=2)  # 2026-11-03 (nominal D+2)
    weights_1 = {"BTC-USDT": 0.6, "ETH-USDT": -0.4, "SOL-USDT": 0.3, "ADA-USDT": -0.2}
    book_1 = _write_book(history, decision_date=decision_1, weights=weights_1)

    decision_2 = dt.date(2026, 12, 1)
    f2 = decision_2 + dt.timedelta(days=2)  # 2026-12-03
    weights_2 = {"BTC-USDT": 0.5, "ETH-USDT": -0.5}
    book_2 = _write_book(history, decision_date=decision_2, weights=weights_2)

    f1_minus_1, f1_plus_9 = f1 - dt.timedelta(days=1), f1 + dt.timedelta(days=9)
    f2_minus_1, f2_plus_9 = f2 - dt.timedelta(days=1), f2 + dt.timedelta(days=9)
    # Book 1's weight rank order (ETH < ADA < SOL < BTC) exactly matches its
    # legs' F-1 -> F+9 return rank order, so the Spearman correlation is a
    # clean, hand-verifiable +1.0 (perfect agreement, no ties).
    futbars = {
        "BTCUSDT": {f1_minus_1: 100.0, f1_plus_9: 130.0, f2_minus_1: 200.0, f2_plus_9: 210.0},
        "ETHUSDT": {f1_minus_1: 40.0, f1_plus_9: 32.0, f2_minus_1: 60.0},  # f2_plus_9 missing
        "SOLUSDT": {f1_minus_1: 50.0, f1_plus_9: 55.0},
        "ADAUSDT": {f1_minus_1: 20.0, f1_plus_9: 19.0},
    }
    snapshot = _seal_snapshot(tmp_path, futbars=futbars)

    window_start = dt.datetime.combine(
        decision_1 + dt.timedelta(days=1), dt.time(12, 5), tzinfo=dt.UTC
    )
    window_end = dt.datetime.combine(decision_2 + dt.timedelta(days=30), dt.time(0, 0, 1), tzinfo=dt.UTC)
    _exit_code, result = _run_main(
        [
            "--history", str(history),
            "--snapshot", str(snapshot),
            "--first-decision", decision_1.isoformat(),
            "--window-start", window_start.isoformat(),
            "--window-end", window_end.isoformat(),
        ]
    )
    by_id = {row["book_id"]: row for row in result["books"]}
    assert by_id[book_1]["forward_ic_10d"] == pytest.approx(1.0, abs=1e-12)
    # book_2's ETH-USDT leg is missing its F+9 close: the whole figure is null.
    assert by_id[book_2]["forward_ic_10d"] is None
