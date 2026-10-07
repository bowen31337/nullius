"""bug_spec_smoke_campaign_hang.xml, bug 2: the lazy, memoized closes.

``load_evaluation_context`` used to call ``_closes``, which opened every
``bars/symbol=*/date=*`` partition of the sealed snapshot with pyarrow at
load time — 33.6 s alone on a 40-symbol x 735-day snapshot, and again on
every composed ``EvaluationContext``, since ``build_live_evaluator`` calls
the loader on every ``create_app()``.  This module is the regression test
for the fix: the load validates the config and the sealed manifest
without reading a single bars partition, and ``context.closes`` reads and
memoizes one symbol-day at a time, the first time something actually
indexes it.

One test per claim the fix makes:

* **zero Parquet reads at load** — ``load_evaluation_context`` opens no
  bars partition, no matter how many the snapshot carries.
* **reads limited to the requested symbols and dates** — indexing
  ``context.closes`` for one symbol-day opens exactly that partition,
  never another symbol's or another day's.
* **memoized second access** — the same symbol-day, read again (through
  the same context or a second one loaded over the same snapshot in the
  same process), opens no partition a second time.
* **the refusals still raise** — a duplicate bar is still caught (now via
  the manifest's own row counts, at load, before any partition opens); a
  poisoned close is still caught, but at first use, when the one
  partition it lives in is actually read.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from orchestrator import _context
from orchestrator._context import EvaluationConfigError, load_evaluation_context
from snapshot import SnapshotService

#: A pinned, distinct evaluator image — this suite never resolves the
#: evaluator's own identity beyond "does it parse", so one fixed digest
#: spelling is all any test here needs.
IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ef" * 32


def _close(symbol_index: int, day_index: int) -> float:
    """One pinned, gently rising close per (symbol, day) — never zero,
    never shared between two (symbol, day) pairs."""
    return round(200.0 + 10.0 * symbol_index + 0.5 * day_index, 2)


def _bars(
    symbols: Sequence[str], days: Sequence[dt.date]
) -> dict[str, dict[dt.date, list[float]]]:
    """One candle a day per symbol — the staged, pre-seal shape."""
    return {
        symbol: {day: [_close(i, j)] for j, day in enumerate(days)}
        for i, symbol in enumerate(symbols)
    }


def _stage_and_seal(
    lake_root: Path, bars: Mapping[str, Mapping[dt.date, Sequence[Any]]]
) -> tuple[SnapshotService, Any]:
    """Stage §4.2's bars layout and seal it through the shipped service.

    Mirrors ``test_context.py``'s own helper (kept local rather than
    imported, so this file stays a self-contained regression test): one
    partition per (symbol, day), a real Parquet part, the venue's own
    string spelling of a close.
    """
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol, series in bars.items():
        for day, closes in series.items():
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol] * len(closes),
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ]
                        * len(closes),
                        "close": [str(close) for close in closes],
                        "volume": ["1.0"] * len(closes),
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 2, tzinfo=dt.UTC))
    return service, sealed


def _document(
    snapshot_path: Path, tmp_path: Path, evaluation_dates: Sequence[str]
) -> dict[str, Any]:
    return {
        "snapshot_mount": str(snapshot_path),
        "evaluation_dates": list(evaluation_dates),
        "horizon": 1,
        "seed": 7,
        "epoch_id": "epoch-lazy-closes",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }


def _environment(tmp_path: Path, document: Mapping[str, Any]) -> dict[str, str]:
    """An environment naming a fresh configuration file for ``document``."""
    config_path = tmp_path / f"evaluation-{abs(id(document))}.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    bwrap_dir = tmp_path / "bwrap-path"
    bwrap_dir.mkdir(exist_ok=True)
    bwrap = bwrap_dir / "bwrap"
    if not bwrap.exists():
        bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
        bwrap.chmod(0o755)
    return {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'lazy-closes.db'}",
        "NULLIUS_EVALUATOR_IMAGE": IMAGE,
        "PATH": str(bwrap_dir),
    }


class _ReadCounter:
    """Counts and records every partition :func:`_context._read_part` opens.

    Wraps the module's own reference (not pyarrow itself), so a count of
    zero means ``load_evaluation_context`` never reached the one function
    that calls ``pyarrow.parquet.read_table`` — the exact call the
    original eager ``_closes`` made once per partition.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[str, str]] = []
        original = _context._read_part

        def counting(part: object, symbol: str) -> Any:
            self.calls.append((symbol, str(part)))
            return original(part, symbol)

        monkeypatch.setattr(_context, "_read_part", counting)

    @property
    def count(self) -> int:
        return len(self.calls)


# -- Zero reads at load --------------------------------------------------------


def test_load_reads_zero_bars_partitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The symptom this bug reports: 33.6 s on a 40x735 snapshot, all of it
    # pyarrow reads nothing at load needs. A smaller snapshot here (five
    # symbols, twenty days — a hundred partitions) still proves the claim
    # that matters: the count is zero regardless of how many partitions
    # exist, not merely "fewer than before".
    monkeypatch.delenv("DATABASE_URL", raising=False)
    symbols = [f"SYM{i:02d}" for i in range(5)]
    days = tuple(dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(20))
    _service, sealed = _stage_and_seal(tmp_path / "lake", _bars(symbols, days))
    document = _document(
        sealed.path, tmp_path, [day.isoformat() for day in days[5:9]]
    )
    counter = _ReadCounter(monkeypatch)

    context = load_evaluation_context(_environment(tmp_path, document))

    assert context is not None
    assert counter.count == 0


# -- Reads limited to the requested symbols and dates --------------------------


def test_reads_are_limited_to_the_symbols_and_dates_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    symbols = [f"SYM{i:02d}" for i in range(4)]
    days = tuple(dt.date(2026, 2, 1) + dt.timedelta(days=i) for i in range(10))
    _service, sealed = _stage_and_seal(tmp_path / "lake", _bars(symbols, days))
    document = _document(sealed.path, tmp_path, [days[0].isoformat()])
    environment = _environment(tmp_path, document)

    counter = _ReadCounter(monkeypatch)
    context = load_evaluation_context(environment)
    assert context is not None
    assert counter.count == 0  # still true after construction, before any use

    first_price = context.closes[symbols[0]][days[3]]
    assert first_price == _close(0, 3)
    assert counter.count == 1

    second_price = context.closes[symbols[2]][days[7]]
    assert second_price == _close(2, 7)
    assert counter.count == 2

    # Only the two (symbol, day) pairs actually indexed were read — not
    # the other 38 partitions this snapshot carries.
    touched_symbols = {symbol for symbol, _part in counter.calls}
    assert touched_symbols == {symbols[0], symbols[2]}
    for symbol, part in counter.calls:
        if symbol == symbols[0]:
            assert f"date={days[3].isoformat()}" in part
        else:
            assert f"date={days[7].isoformat()}" in part


# -- Memoized second access ------------------------------------------------------


def test_the_same_symbol_day_is_read_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    symbols = ["SYM00", "SYM01"]
    days = tuple(dt.date(2026, 3, 1) + dt.timedelta(days=i) for i in range(5))
    _service, sealed = _stage_and_seal(tmp_path / "lake", _bars(symbols, days))
    document = _document(sealed.path, tmp_path, [days[0].isoformat()])
    environment = _environment(tmp_path, document)

    counter = _ReadCounter(monkeypatch)
    context = load_evaluation_context(environment)
    assert context is not None

    assert context.closes["SYM00"][days[2]] == _close(0, 2)
    assert counter.count == 1

    # The same context, the same key, again: the per-process cache
    # answers it without a second read.
    assert context.closes["SYM00"][days[2]] == _close(0, 2)
    assert counter.count == 1

    # A second evaluation over the same snapshot, in the same process —
    # exactly what feature 8 does on every create_app() — still reads
    # this partition zero more times.
    second_context = load_evaluation_context(environment)
    assert second_context is not None
    assert second_context.closes["SYM00"][days[2]] == _close(0, 2)
    assert counter.count == 1


# -- The refusals still raise ---------------------------------------------------


def test_a_duplicate_bar_is_refused_at_load_from_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "One bar, one close" is now checked for free, from the manifest's
    # own row counts — the duplicate is caught before any bars partition
    # opens, which the zero read-count proves.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    days = (dt.date(2026, 4, 1), dt.date(2026, 4, 2))
    bars = _bars(["SYM00"], days)
    bars["SYM00"][days[0]] = [_close(0, 0), _close(0, 0) + 1.0]
    _service, sealed = _stage_and_seal(tmp_path / "lake", bars)
    document = _document(sealed.path, tmp_path, [days[1].isoformat()])
    environment = _environment(tmp_path, document)

    counter = _ReadCounter(monkeypatch)
    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(environment)

    message = str(record.value)
    assert message.startswith("evaluation_config:")
    assert "SYM00" in message
    assert "twice" in message
    assert counter.count == 0


def test_a_poisoned_close_is_refused_at_first_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The content check a manifest's row count cannot do for free: a
    # non-positive close is only discovered once its own partition is
    # actually read, which is first use, not load — load succeeds.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    symbols = ["SYM00", "SYM01"]
    days = tuple(dt.date(2026, 5, 1) + dt.timedelta(days=i) for i in range(4))
    bars = _bars(symbols, days)
    bars["SYM00"][days[1]] = [0.0]
    _service, sealed = _stage_and_seal(tmp_path / "lake", bars)
    document = _document(sealed.path, tmp_path, [days[-1].isoformat()])
    environment = _environment(tmp_path, document)

    counter = _ReadCounter(monkeypatch)
    context = load_evaluation_context(environment)
    assert context is not None  # the poison does not stop the load
    assert counter.count == 0

    # A date the poison never touches still reads cleanly.
    assert context.closes["SYM01"][days[1]] == _close(1, 1)

    with pytest.raises(EvaluationConfigError) as record:
        context.closes["SYM00"][days[1]]

    message = str(record.value)
    assert message.startswith("evaluation_config:")
    assert "SYM00" in message
    assert days[1].isoformat() in message


def test_a_snapshot_without_bars_is_still_refused_at_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The structural check that was always free (a directory listing):
    # still fires at load, naming the missing stream.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    lake = tmp_path / "lake"
    (lake / "snapshots").mkdir(parents=True)
    partition = lake / "staging" / "trades" / "symbol=SYM00"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table({"symbol": ["SYM00"], "price": ["1.0"]}),
        partition / "part-0.parquet",
    )
    service = SnapshotService(lake)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 3, tzinfo=dt.UTC))
    document = _document(sealed.path, tmp_path, ["2026-11-01"])

    counter = _ReadCounter(monkeypatch)
    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(_environment(tmp_path, document))

    assert "bars" in str(record.value)
    assert counter.count == 0
