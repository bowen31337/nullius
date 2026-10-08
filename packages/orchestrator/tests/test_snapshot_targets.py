"""Feature 4, the forward-return supply over a sealed snapshot.

additions_spec_real_campaign_path.xml, "Campaign Evaluation Path", feature 4:
*orchestrator._targets.snapshot_forward_returns(context) returns a callable
(request) -> {date: {symbol: return}}.  Each value is the close-to-close
simple return over context.horizon trading days, read only from
context.snapshot_mount through the existing closes reader.  Symbols or dates
without a close h days ahead are omitted, never zero-filled.*

Every test here loads a *real* :class:`~orchestrator._context.EvaluationContext`
off a genuine sealed snapshot through
:func:`orchestrator._context.load_evaluation_context` — the same seam
``test_context.py`` and ``test_live_evaluator_component.py`` exercise for
their own fixtures — so ``context.closes`` is exactly what the existing
closes reader produced from the staged bars, and the forward returns under
test are computed over bytes nothing in this file faked.

One test per claim the feature sentence makes:

* **matches hand-computed values** — a tiny two-symbol, six-day snapshot's
  forward returns, by hand, at ``horizon=2``.
* **a missing forward close is omitted** — a symbol with fewer trading days
  than another sees its own entries omitted at the dates its series cannot
  reach two days ahead from, never a zero.
* **narrows to the request's symbols and date range** — the callable
  defers to a ``TargetRequest``-shaped ask the way
  :class:`nulloracle.TargetEndpoint` depends on it to.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from orchestrator._context import load_evaluation_context
from orchestrator._targets import snapshot_forward_returns
from snapshot import SnapshotService

#: The world's two symbols, over six consecutive bar days — enough span for
#: a horizon-2 forward return to land mid-series and to run off its tail.
SYMBOLS = ("AAA", "BBB")
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(6))
HORIZON = 2
SEED = 20261006
EPOCH = "epoch-test-snapshot-targets"
ARTIFACT_DIR_NAME = "artifacts"
IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "cd" * 32


def _close(symbol_index: int, day_index: int) -> float:
    """A gently rising, symbol-distinct close — never shared across symbols."""
    return round(100.0 + 10.0 * symbol_index + float(day_index), 2)


def _stage_and_seal(
    lake_root: Path, bars: Mapping[str, Sequence[dt.date]]
) -> Any:
    """Stage §4.2's layout for the days each symbol in ``bars`` names, and seal it.

    ``bars`` maps a symbol to the subset of :data:`BAR_DAYS` it carries a
    candle on — a symbol missing a trailing day is exactly how this suite
    builds "a symbol with fewer trading days than another" without any
    gap-filling logic of its own.
    """
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol_index, symbol in enumerate(SYMBOLS):
        for day in bars.get(symbol, ()):
            offset = BAR_DAYS.index(day)
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ],
                        "close": [str(_close(symbol_index, offset))],
                        "volume": ["1.0"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


def _load_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bars: Mapping[str, Sequence[dt.date]],
) -> Any:
    """A real :class:`~orchestrator._context.EvaluationContext` over ``bars``.

    Mirrors ``test_live_evaluator_component.py``'s own ``live`` fixture: a
    genuine sealed snapshot, a configuration document naming it, and the
    process environment the loader reads from — nothing here is a stand-in
    for the context, because the feature's own claim is that the forward
    returns are read off exactly what that context's own ``closes`` reader
    produced.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sealed = _stage_and_seal(tmp_path / "lake", bars)

    document = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": [BAR_DAYS[0].isoformat()],
        "horizon": HORIZON,
        "seed": SEED,
        "epoch_id": EPOCH,
        "artifact_dir": str(tmp_path / ARTIFACT_DIR_NAME),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    config_path = tmp_path / "evaluation.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")

    database_url = f"sqlite:///{tmp_path / 'snapshot-targets-test.db'}"
    monkeypatch.setenv("NULLIUS_EVALUATION_CONFIG", str(config_path))
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", IMAGE)

    context = load_evaluation_context()
    assert context is not None
    return context


def _request(
    symbols: Sequence[str] | None = None,
    date_range: tuple[dt.date, dt.date] | None = None,
) -> Any:
    """A ``TargetRequest``-shaped ask: the two fields this seam reads."""
    return SimpleNamespace(symbols=symbols, date_range=date_range)


# -- Matches hand-computed values ------------------------------------------


def test_matches_hand_computed_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = {symbol: BAR_DAYS for symbol in SYMBOLS}
    context = _load_context(tmp_path, monkeypatch, bars)

    supply = snapshot_forward_returns(context)
    series = supply(_request())

    expected: dict[dt.date, dict[str, float]] = {}
    for symbol_index, symbol in enumerate(SYMBOLS):
        for offset in range(len(BAR_DAYS) - HORIZON):
            entry = _close(symbol_index, offset)
            exit_ = _close(symbol_index, offset + HORIZON)
            expected.setdefault(BAR_DAYS[offset], {})[symbol] = exit_ / entry - 1.0

    assert series.keys() == expected.keys()
    for day, row in expected.items():
        assert series[day].keys() == row.keys()
        for symbol, value in row.items():
            assert series[day][symbol] == pytest.approx(value)

    # The tail: the last HORIZON days have no close two trading days ahead
    # for either symbol, so they carry no entry at all — never a zero.
    for day in BAR_DAYS[-HORIZON:]:
        assert day not in series


# -- A missing forward close is omitted -------------------------------------


def test_a_missing_forward_close_is_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AAA carries every bar day; BBB's history ends four days in — fewer
    # trading days than AAA, entirely by its own staged bars, not a gap
    # this test manufactures inside a longer series.
    bars = {"AAA": BAR_DAYS, "BBB": BAR_DAYS[:4]}
    context = _load_context(tmp_path, monkeypatch, bars)

    supply = snapshot_forward_returns(context)
    series = supply(_request())

    # BBB has four trading days (indices 0-3); index + HORIZON(2) stays in
    # range only for indices 0 and 1, so BBB's own entries at BAR_DAYS[2]
    # and BAR_DAYS[3] are omitted outright — never a zeroed forward return.
    assert "BBB" in series[BAR_DAYS[0]]
    assert "BBB" in series[BAR_DAYS[1]]
    assert "BBB" not in series[BAR_DAYS[2]]
    assert "BBB" not in series[BAR_DAYS[3]]

    # AAA's own six days still reach two trading days ahead from both of
    # those dates, so AAA is untouched by BBB's shorter history.
    assert "AAA" in series[BAR_DAYS[2]]
    assert "AAA" in series[BAR_DAYS[3]]

    # Neither symbol appears at a date it has no entry for at all.
    assert BAR_DAYS[4] not in series
    assert BAR_DAYS[5] not in series

    for row in series.values():
        for value in row.values():
            assert value != 0.0


# -- Narrows to the request's symbols and date range ------------------------


def test_narrows_to_the_requests_symbols_and_date_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = {symbol: BAR_DAYS for symbol in SYMBOLS}
    context = _load_context(tmp_path, monkeypatch, bars)

    supply = snapshot_forward_returns(context)
    narrowed = supply(
        _request(symbols=("AAA",), date_range=(BAR_DAYS[1], BAR_DAYS[2]))
    )

    assert set(narrowed) <= {BAR_DAYS[1], BAR_DAYS[2]}
    for row in narrowed.values():
        assert set(row) == {"AAA"}
    assert narrowed[BAR_DAYS[1]]["AAA"] == pytest.approx(
        _close(0, 3) / _close(0, 1) - 1.0
    )



def test_the_sidecar_backed_endpoint_permutes_per_symbol_not_per_row() -> None:
    # Regression: orchestrator._sidecar_backed_endpoint carried its own copy of
    # the old whole-row permutation, so the live null oracle placed a symbol
    # listed late in the window onto earlier dates and the gate refused every
    # null node (smoke campaign a9656ef3). It must use nulloracle's per-symbol
    # permutation.
    import datetime as _dt
    import inspect

    import orchestrator

    source = inspect.getsource(orchestrator._sidecar_backed_endpoint)
    assert "block_permute_cross_section" in source
    assert "block_indices" not in source
    from nulloracle.blockpermute import block_permute_cross_section

    days = [_dt.date(2026, 7, 1) + _dt.timedelta(days=i) for i in range(60)]
    panel = {
        day: {"AAA": 0.01 * i, **({"LATE": 0.5} if i >= 50 else {})}
        for i, day in enumerate(days)
    }
    permuted = block_permute_cross_section(panel, seed=7, block_days=20)
    assert all(set(row) <= set(panel[day]) for day, row in permuted.items())


def test_the_live_route_serves_only_the_rebalance_grid() -> None:
    """Archive campaign 1 (2026-10-08) scored a weekly grid, but the route
    served every trading day in the span, and the gate refused every node.
    grid_forward_returns serves exactly context.evaluation_dates; a dense
    grid is unchanged."""
    import datetime as dt

    from orchestrator._targets import grid_forward_returns, snapshot_forward_returns

    days = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(30)]
    closes = {
        sym: {d: 100.0 + i * (k + 1) for i, d in enumerate(days)}
        for k, sym in enumerate(("AAA", "BBB"))
    }
    weekly = tuple(days[0:28:7])
    request = SimpleNamespace(symbols=None, date_range=(days[0], days[-1]))

    sparse = SimpleNamespace(closes=closes, horizon=1, evaluation_dates=weekly)
    served = grid_forward_returns(sparse)(request)
    assert sorted(served) == list(weekly)
    full = snapshot_forward_returns(sparse)(request)
    assert all(served[d] == full[d] for d in weekly)

    dense = SimpleNamespace(closes=closes, horizon=1, evaluation_dates=tuple(days[:-1]))
    assert grid_forward_returns(dense)(request) == snapshot_forward_returns(dense)(request)
