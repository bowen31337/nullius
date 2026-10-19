"""The configured book weighting — ``book.weighting`` in the evaluation config.

System reads a ``book.weighting`` setting from the evaluation config
(``"z"``, today's default, or ``"inverse_vol"``) and, for ``inverse_vol``,
derives each date's point-in-time realised volatilities from the sealed
closes and hands them to the metrics, so that an evaluation config can
switch the whole engine to volatility-scaled books with no other change.

Three groups of tests, over a tmp sealed snapshot throughout:

* **the config** — :data:`orchestrator._context.BOOK_KEY`'s object gains a
  ``weighting`` inner key (closed vocabulary ``{"z", "inverse_vol"}``,
  default ``"z"``) and a ``vol_window_days`` inner key (default 60, refused
  below 20); a config naming an unknown weighting is refused at load with a
  message naming the value — through
  :func:`~orchestrator._context.load_evaluation_context`, the real public
  seam, over a genuine sealed lake.
* **the vols** — :func:`orchestrator._context.compute_vols` measures the
  population standard deviation of each symbol's close-to-close returns over
  the trailing ``vol_window_days`` returns ending at the scored date, never
  uses a return after that date, and leaves a symbol with fewer than half
  the window's returns out of the day's row — which the book refuses by name
  downstream, never a defaulted vol.
* **the wiring** — :func:`orchestrator._evaluate.evaluate_node` passes the
  computed vols to every ``compute_node_metrics`` call it makes (the net
  figure and the gross diagnostic alike) when the weighting is
  ``"inverse_vol"``, so each date's book is exactly
  ``book_weights(scores, betas, vols=compute_vols(...))`` for that date;
  with ``"z"`` it passes nothing and every figure is identical (1e-12) to
  the absent-block default.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Runs under pytest-xdist: every
fixture builds a fresh temporary database and lake, with no shared
module-level mutable state across tests.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import random
import sqlite3
import statistics
import uuid
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import FeeSchedule, load_cost_model
from evaluator import EvaluatorMetricsError, book_weights
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import (
    DEFAULT_VOL_WINDOW_DAYS,
    INVERSE_VOL_WEIGHTING,
    MIN_VOL_WINDOW_DAYS,
    Z_WEIGHTING,
    BookConfig,
    EvaluationConfigError,
    EvaluationContext,
    compute_vols,
    load_evaluation_context,
)
from orchestrator._evaluate import evaluate_node
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CODE_WORD = "evaluation_config"


# == Part A: the config, through load_evaluation_context ========================

PART_A_SYMBOLS = ("SYM00", "SYM01")
PART_A_FIRST_DAY = dt.date(2026, 9, 1)
PART_A_BAR_DAYS = tuple(
    PART_A_FIRST_DAY + dt.timedelta(days=offset) for offset in range(12)
)
PART_A_EVALUATION_DAYS = tuple(
    day.isoformat() for day in PART_A_BAR_DAYS[6:10]
)


def _part_a_close(symbol_index: int, day_index: int) -> float:
    return round(100.0 + 10.0 * symbol_index + 0.25 * day_index, 2)


def _stage_and_seal_part_a(lake_root: Path) -> Any:
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, symbol in enumerate(PART_A_SYMBOLS):
        for offset, day in enumerate(PART_A_BAR_DAYS):
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
                        "close": [str(_part_a_close(index, offset))],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


@pytest.fixture
def document_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, str]]:
    """One valid base document and environment, pointing at a real sealed lake."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sealed = _stage_and_seal_part_a(tmp_path / "lake")

    cost_model_path = tmp_path / "cost_model.yaml"
    cost_model_path.write_text(
        'cost_model:\n  version: "2026.10.0"\n  venue: testnet_spot\n'
        "  fees:\n    taker_bps: 12.5\n    maker_bps: 8.0\n",
        encoding="utf-8",
    )

    bwrap_dir = tmp_path / "bin"
    bwrap_dir.mkdir()
    bwrap = bwrap_dir / "bwrap"
    bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)

    document: dict[str, Any] = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(PART_A_EVALUATION_DAYS),
        "horizon": 1,
        "seed": 20261019,
        "epoch_id": "epoch-2026-10-19-book-weighting",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    environment = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'ctx.db'}",
        "NULLIUS_EVALUATOR_IMAGE": "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32,
        "NULLIUS_COST_MODEL_PATH": str(cost_model_path),
        "PATH": str(bwrap_dir),
    }
    return document, environment


def _load(
    document: Mapping[str, Any],
    environment: Mapping[str, str],
    tmp_path: Path,
    name: str,
) -> EvaluationContext | None:
    path = tmp_path / f"evaluation-{name}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    env = dict(environment)
    env["NULLIUS_EVALUATION_CONFIG"] = str(path)
    return load_evaluation_context(env)


def _refuses(
    document: Mapping[str, Any],
    environment: Mapping[str, str],
    tmp_path: Path,
    name: str,
    *needles: str,
) -> str:
    with pytest.raises(EvaluationConfigError) as record:
        _load(document, environment, tmp_path, name)
    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:"), message
    for needle in needles:
        assert needle in message, (needle, message)
    return message


def test_book_absent_gives_the_z_weighting_default(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    context = _load(document, environment, tmp_path, "absent-book")
    assert isinstance(context, EvaluationContext)
    assert context.book == BookConfig()
    assert context.book.weighting == Z_WEIGHTING
    assert context.book.vol_window_days == DEFAULT_VOL_WINDOW_DAYS == 60


def test_book_present_without_weighting_defaults_to_z(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(document, book={"beta_neutral": True})
    context = _load(document, environment, tmp_path, "book-no-weighting")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == Z_WEIGHTING
    assert context.book.vol_window_days == 60


def test_inverse_vol_weighting_parses_with_its_own_default_window(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document, book={"beta_neutral": False, "weighting": INVERSE_VOL_WEIGHTING}
    )
    context = _load(document, environment, tmp_path, "inverse-vol-defaults")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == INVERSE_VOL_WEIGHTING
    assert context.book.vol_window_days == 60


def test_explicit_z_and_a_custom_window_are_honoured(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document,
        book={
            "beta_neutral": True,
            "weighting": Z_WEIGHTING,
            "vol_window_days": 30,
        },
    )
    context = _load(document, environment, tmp_path, "z-custom-window")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == Z_WEIGHTING
    assert context.book.vol_window_days == 30


def test_unknown_weighting_is_refused_naming_the_value(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document,
        book={"beta_neutral": False, "weighting": "equal_vol"},
    )
    _refuses(
        document,
        environment,
        tmp_path,
        "unknown-weighting",
        "equal_vol",
        "weighting",
        Z_WEIGHTING,
        INVERSE_VOL_WEIGHTING,
    )


def test_weighting_of_the_wrong_type_is_refused(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document, book={"beta_neutral": False, "weighting": True}
    )
    _refuses(document, environment, tmp_path, "weighting-bool", "weighting")


def test_vol_window_below_twenty_is_refused(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document,
        book={
            "beta_neutral": False,
            "weighting": INVERSE_VOL_WEIGHTING,
            "vol_window_days": MIN_VOL_WINDOW_DAYS - 1,
        },
    )
    _refuses(
        document,
        environment,
        tmp_path,
        "short-vol-window",
        "vol_window_days",
        "19",
    )


def test_vol_window_of_the_wrong_type_is_refused(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document,
        book={
            "beta_neutral": False,
            "weighting": INVERSE_VOL_WEIGHTING,
            "vol_window_days": 20.5,
        },
    )
    _refuses(
        document, environment, tmp_path, "float-vol-window", "vol_window_days"
    )


# == Part B: compute_vols, directly =============================================


@pytest.fixture(scope="module")
def vol_snapshot(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """A real, minimal sealed snapshot — only its mount is needed by
    :func:`compute_vols`, which never reads ``context.snapshot``, but every
    context in this suite still carries one, for real."""
    workdir = tmp_path_factory.mktemp("vol-compute-world")
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    partition = staging / "bars" / "symbol=AAA" / "date=2026-01-01"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": ["AAA"],
                "open_time": [dt.datetime(2026, 1, 1, tzinfo=dt.UTC)],
                "close": ["100.0"],
                "volume": ["1.0"],
            }
        ),
        partition / "part-0.parquet",
    )
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC))
    return service.mount(sealed.name)


def _minimal_context(
    mount: Any,
    closes: Mapping[str, Mapping[dt.date, float]],
    *,
    book: BookConfig,
    tmp_path: Path,
    name: str,
) -> EvaluationContext:
    config = load_cost_model()
    return EvaluationContext(
        snapshot=mount,
        closes=closes,
        cost_model=config,
        cost_schedule=FeeSchedule(venue=config.venue, taker_bps=0.0, maker_bps=0.0),
        evaluator_hash="ab" * 32,
        snapshot_hash="cd" * 32,
        cost_model_hash="ef" * 32,
        epoch_id="epoch-compute-vols-test",
        database_url=f"sqlite:///{tmp_path / name}.db",
        artifact_dir=tmp_path / f"artifacts-{name}",
        seed=1,
        horizon=1,
        evaluation_dates=(dt.date(2026, 1, 10),),
        sandbox_runtime="unisolated",
        book=book,
    )


#: The window Part B measures over — small, because the arithmetic under test
#: does not depend on the window's length, only on its discipline.
VOL_WINDOW_DAYS = 5
VOL_RETURNS = [0.01, -0.02, 0.015, 0.03, -0.01]


def _closes_from_returns(
    first_day: dt.date, returns: list[float], start: float
) -> dict[dt.date, float]:
    closes = {first_day: start}
    price = start
    for offset, value in enumerate(returns):
        price = price * (1.0 + value)
        closes[first_day + dt.timedelta(days=offset + 1)] = price
    return closes


def test_compute_vols_gives_the_known_standard_deviations(
    vol_snapshot: Any, tmp_path: Path
) -> None:
    window_days = VOL_WINDOW_DAYS
    days = tuple(
        dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(window_days + 1)
    )
    scored = days[-1]
    # BBB's returns are exactly 3x AAA's, so its population standard deviation
    # is exactly 3x AAA's — an independent handle on the scaling, beside the
    # known constant.
    aaa_closes = _closes_from_returns(days[0], VOL_RETURNS, 100.0)
    bbb_closes = _closes_from_returns(days[0], [3.0 * r for r in VOL_RETURNS], 50.0)
    closes = {"AAA": aaa_closes, "BBB": bbb_closes}
    book = BookConfig(
        beta_neutral=False,
        weighting=INVERSE_VOL_WEIGHTING,
        vol_window_days=window_days,
    )
    context = _minimal_context(
        vol_snapshot, closes, book=book, tmp_path=tmp_path, name="known-std"
    )

    vols = compute_vols(context, {scored: {"AAA": 1.0, "BBB": -1.0}})

    expected = statistics.pstdev(VOL_RETURNS)  # ddof=0: the population std
    assert vols[scored]["AAA"] == pytest.approx(expected, rel=1e-12)
    assert vols[scored]["AAA"] == pytest.approx(0.01788854381999832, rel=1e-9)
    assert vols[scored]["BBB"] == pytest.approx(3.0 * expected, rel=1e-12)


def test_compute_vols_is_point_in_time(vol_snapshot: Any, tmp_path: Path) -> None:
    window_days = VOL_WINDOW_DAYS
    days = tuple(
        dt.date(2026, 2, 1) + dt.timedelta(days=i) for i in range(window_days + 1)
    )
    scored = days[-1]
    future_day = scored + dt.timedelta(days=1)

    closes = {"AAA": _closes_from_returns(days[0], VOL_RETURNS, 100.0)}
    # Plant a massive shock strictly after the scored date — the only
    # difference between the two worlds.
    shocked = {
        "AAA": {**closes["AAA"], future_day: closes["AAA"][scored] * 50.0}
    }
    book = BookConfig(
        beta_neutral=False,
        weighting=INVERSE_VOL_WEIGHTING,
        vol_window_days=window_days,
    )
    before = _minimal_context(
        vol_snapshot, closes, book=book, tmp_path=tmp_path, name="pit-before"
    )
    after = _minimal_context(
        vol_snapshot, shocked, book=book, tmp_path=tmp_path, name="pit-after"
    )

    scores = {scored: {"AAA": 1.0}}
    vols_before = compute_vols(before, scores)
    vols_after = compute_vols(after, scores)

    assert vols_before[scored]["AAA"] == pytest.approx(
        vols_after[scored]["AAA"], rel=1e-12
    )


def test_compute_vols_half_coverage_and_symbol_handling(
    vol_snapshot: Any, tmp_path: Path
) -> None:
    window_days = 10
    first = dt.date(2026, 3, 1)
    days = tuple(
        first + dt.timedelta(days=i) for i in range(window_days + 1)
    )
    scored = days[-1]
    window = days[1:]  # the ten return dates ending at the scored day

    dense_returns = [0.01, -0.02, 0.015, 0.03, -0.01, 0.005, -0.025, 0.02, -0.008, 0.012]
    dense = _closes_from_returns(days[0], dense_returns, 100.0)
    # Exactly half the window's returns: closes on the window's first six
    # dates, of which the first contributes no return (its prior day is
    # absent) — five of ten.
    half = {day: 50.0 + 0.5 * index for index, day in enumerate(window[:6])}
    # Fewer than half: closes on the window's first five dates only — four
    # of ten returns.
    thin = {day: 25.0 + 0.25 * index for index, day in enumerate(window[:5])}

    closes = {"DENSE": dense, "HALF": half, "THIN": thin}
    book = BookConfig(
        beta_neutral=False,
        weighting=INVERSE_VOL_WEIGHTING,
        vol_window_days=window_days,
    )
    context = _minimal_context(
        vol_snapshot, closes, book=book, tmp_path=tmp_path, name="coverage"
    )

    scores = {
        scored: {"DENSE": 1.0, "HALF": 1.0, "THIN": 1.0, "ABSENT": 1.0},
        scored + dt.timedelta(days=1): {},  # a no-preference date: skipped
    }
    vols = compute_vols(context, scores)

    assert set(vols) == {scored}
    assert set(vols[scored]) == {"DENSE", "HALF"}
    assert vols[scored]["DENSE"] == pytest.approx(
        statistics.pstdev(dense_returns), rel=1e-12
    )
    half_returns = [
        half[window[i]] / half[window[i - 1]] - 1.0 for i in range(1, 6)
    ]
    assert vols[scored]["HALF"] == pytest.approx(
        statistics.pstdev(half_returns), rel=1e-12
    )


def test_thin_symbol_is_refused_downstream_by_name(
    vol_snapshot: Any, tmp_path: Path
) -> None:
    """A symbol compute_vols leaves out is refused *by name* by the book —
    the consumer's own law, verified here so the omission policy above is
    known to end in a refusal, never a defaulted vol."""
    window_days = 10
    first = dt.date(2026, 4, 1)
    days = tuple(
        first + dt.timedelta(days=i) for i in range(window_days + 1)
    )
    scored = days[-1]
    window = days[1:]

    # Varied, not constant: a constant return gives a zero volatility,
    # which the book refuses for its own reason (a vol is a positive scale)
    # before the missing-name refusal this test is about ever fires.
    dense = _closes_from_returns(
        days[0],
        [0.01, -0.02, 0.015, 0.03, -0.01, 0.005, -0.025, 0.02, -0.008, 0.012],
        100.0,
    )
    thin = {day: 25.0 + 0.25 * index for index, day in enumerate(window[:5])}
    closes = {"DENSE": dense, "THIN": thin}
    book = BookConfig(
        beta_neutral=False,
        weighting=INVERSE_VOL_WEIGHTING,
        vol_window_days=window_days,
    )
    context = _minimal_context(
        vol_snapshot, closes, book=book, tmp_path=tmp_path, name="refused-by-name"
    )

    scores = {scored: {"DENSE": 1.0, "THIN": -1.0}}
    vols = compute_vols(context, scores)

    assert set(vols[scored]) == {"DENSE"}
    with pytest.raises(EvaluatorMetricsError) as record:
        book_weights(scores[scored], None, vols=vols[scored])
    assert "THIN" in str(record.value)


# == Part C: the wiring, through evaluate_node ==================================

NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

BENCHMARK = "BTCUSDT"
PART_C_FIRST_DAY = dt.date(2026, 4, 1)
PART_C_BAR_DAYS = tuple(
    PART_C_FIRST_DAY + dt.timedelta(days=offset) for offset in range(100)
)
VOL_WIRING_WINDOW_DAYS = 20
EVALUATION_DATES = PART_C_BAR_DAYS[40:80]
HORIZON = 1
WORLD_SEED = 20261019
EPOCH_ID = "epoch-2026-10-19-book-weighting-wiring"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: test_book_beta_neutral.py's own momentum signal: it re-ranks symbols by
#: trailing return every rebalance date, so the per-date information
#: coefficient actually varies (a signal whose score never changes gives a
#: constant IC across every date, which compute_node_metrics itself refuses
#: as an undefined t-statistic) and the cross-section moves date to date.
LOOKBACK = 10
WEIGHTING_SIGNAL_CODE = f"""
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
    if len(bars) <= 0:
        raise ValueError("the window carries no bars to score against")
    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    momentum = {{}}
    for symbol in ctx.universe:
        series = frame.filter(pl.col("symbol") == symbol).sort("open_time")
        if len(series) < {LOOKBACK}:
            momentum[symbol] = 0.0
        else:
            first = float(series[-{LOOKBACK}]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_book_weighting_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _migrate_tree(database_url: str) -> None:
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)


def _plant_root(database_url: str, *, node_id: str, campaign_id: str) -> None:
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, NULL, ?, ?, ?)",
            (node_id, campaign_id, "macro", 0),
        )


def _seal_the_world(
    workdir: Path,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(WORLD_SEED)

    # Three vol regimes, so the inverse-vol book actually differs from the
    # z book: CCC is about five times as volatile as AAA.
    def _path(sigma: float) -> dict[dt.date, float]:
        price = 100.0
        series: dict[dt.date, float] = {}
        for day in PART_C_BAR_DAYS:
            shock = generator.gauss(0.0, sigma)
            price = max(1.0, price * (1.0 + shock))
            series[day] = round(price, 4)
        return series

    sigmas = {"AAA": 0.004, "BBB": 0.006, "CCC": 0.02, BENCHMARK: 0.01}
    closes = {symbol: _path(sigma) for symbol, sigma in sigmas.items()}

    for symbol, series in closes.items():
        for day in PART_C_BAR_DAYS:
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
                        "close": [f"{series[day]:.4f}"],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service.mount(sealed.name), closes


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering a dense, gapless real-branch series."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def post(self, request: Any) -> TargetResponse:
        self.requests.append(request)
        first, last = request.date_range
        days: list[dt.date] = []
        day = first
        while day <= last:
            days.append(day)
            day = day + dt.timedelta(days=1)
        symbols = sorted(request.symbols)
        series = {
            day: {
                symbol: 0.001 * (index + 1) * (1.0 + 0.15 * (day - first).days)
                for index, symbol in enumerate(symbols)
            }
            for day in days
        }
        return TargetResponse(
            status=OK,
            node_id=request.node_id,
            target_series=series,
            charges_budget=True,
        )


@pytest.fixture(scope="module")
def sealed_world(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    workdir = tmp_path_factory.mktemp("book-weighting-wiring-world")
    return _seal_the_world(workdir)


def _build_context(
    tmp_path: Path,
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    *,
    book: BookConfig,
    name: str,
) -> EvaluationContext:
    mount, closes = sealed_world
    config = load_cost_model()
    # Zero fees: the per-symbol charge cancels in a dollar-neutral book and
    # the turnover charge is zero, so the measured book_returns are exactly
    # the weighted forward returns the reconstruction below rebuilds.
    schedule = FeeSchedule(venue=config.venue, taker_bps=0.0, maker_bps=0.0)
    database_url = f"sqlite:///{tmp_path / name}.db"
    _migrate_tree(database_url)
    return EvaluationContext(
        snapshot=mount,
        closes=closes,
        cost_model=config,
        cost_schedule=schedule,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH_FALLBACK,
        cost_model_hash=COST_MODEL_HASH,
        epoch_id=EPOCH_ID,
        database_url=database_url,
        artifact_dir=tmp_path / f"artifacts-{name}",
        seed=WORLD_SEED,
        horizon=HORIZON,
        evaluation_dates=EVALUATION_DATES,
        sandbox_runtime="unisolated",
        book=book,
    )


def _capturing_evaluate(
    tmp_path: Path,
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    *,
    book: BookConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, EvaluationContext, list[dict[str, Any]]]:
    """Evaluate one node under ``book``, recording every compute_node_metrics
    call's ``(returns, scores, betas, vols)``."""
    from evaluator import compute_node_metrics as real_compute_node_metrics

    calls: list[dict[str, Any]] = []

    def _capture(returns: Any, scores: Any, **kwargs: Any) -> Any:
        calls.append(
            {
                "returns": returns,
                "scores": scores,
                "betas": kwargs.get("betas"),
                "vols": kwargs.get("vols"),
                "cost": kwargs.get("cost_per_unit_traded"),
            }
        )
        return real_compute_node_metrics(returns, scores, **kwargs)

    monkeypatch.setattr("orchestrator._evaluate.compute_node_metrics", _capture)

    context = _build_context(
        tmp_path,
        sealed_world,
        book=book,
        name=f"wiring-{uuid.uuid4().hex[:8]}",
    )
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    oracle = SubtreeOracle(RecordingEndpoint(), database_url=context.database_url)
    ledger = TrialLedger(context.database_url)
    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        WEIGHTING_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )
    return answer, context, calls


def test_z_weighting_is_identical_to_the_absent_block(
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``weighting: "z"`` — spelled or defaulted — passes no vols and
    reproduces the absent block's figures to 1e-12."""
    plain_answer, _, plain_calls = _capturing_evaluate(
        tmp_path, sealed_world, book=BookConfig(), monkeypatch=monkeypatch
    )
    z_answer, _, z_calls = _capturing_evaluate(
        tmp_path,
        sealed_world,
        book=BookConfig(weighting=Z_WEIGHTING, vol_window_days=60),
        monkeypatch=monkeypatch,
    )

    assert plain_answer.fail_class is None, plain_answer.fail_detail
    assert z_answer.fail_class is None, z_answer.fail_detail
    assert len(plain_calls) == 2  # the net figure, then the gross diagnostic
    assert len(z_calls) == 2
    assert all(call["vols"] is None for call in plain_calls)
    assert all(call["vols"] is None for call in z_calls)

    plain, zed = plain_answer.metrics, z_answer.metrics
    assert plain is not None and zed is not None
    for field in ("ic_mean", "ic_se", "ic_tstat", "ir_standalone", "turnover"):
        assert getattr(plain, field) == pytest.approx(
            getattr(zed, field), rel=1e-12, abs=1e-12
        ), field
    assert plain.dates == zed.dates
    assert set(plain.ic_series) == set(zed.ic_series)
    for day, value in plain.ic_series.items():
        assert value == pytest.approx(zed.ic_series[day], rel=1e-12, abs=1e-12)
    assert set(plain.book_returns) == set(zed.book_returns)
    for day, value in plain.book_returns.items():
        assert value == pytest.approx(zed.book_returns[day], rel=1e-12, abs=1e-12)
    assert plain_answer.score.cost_adjusted_ir == pytest.approx(
        z_answer.score.cost_adjusted_ir, rel=1e-12, abs=1e-12
    )
    assert plain_answer.ir_tstat_gross == pytest.approx(
        z_answer.ir_tstat_gross, rel=1e-12, abs=1e-12
    )


def test_inverse_vol_books_equal_book_weights_over_compute_vols(
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer, context, calls = _capturing_evaluate(
        tmp_path,
        sealed_world,
        book=BookConfig(
            beta_neutral=False,
            weighting=INVERSE_VOL_WEIGHTING,
            vol_window_days=VOL_WIRING_WINDOW_DAYS,
        ),
        monkeypatch=monkeypatch,
    )

    assert answer.fail_class is None, answer.fail_detail
    assert len(calls) == 2
    net_call, gross_call = calls
    assert net_call["cost"] == 0.0  # the zero-fee schedule, as built
    assert gross_call["cost"] == 0.0

    scores = net_call["scores"]
    vols = net_call["vols"]
    betas = net_call["betas"]
    assert betas is None
    assert vols is not None
    # The vols the chain handed the metrics are exactly compute_vols' own
    # answer over the same context and scores — recomputed here, blind.
    assert vols == compute_vols(context, scores)
    # The gross diagnostic is measured over the same vols, never a different
    # book from the net figure.
    assert gross_call["vols"] == vols

    metrics = answer.metrics
    assert metrics is not None
    series = net_call["returns"].series[metrics.horizon]
    checked = 0
    for day in series.dates():
        score_row = scores.get(day)
        if not score_row:
            continue
        returns_row = series.at(day)
        book_symbols = sorted(set(score_row) & set(returns_row))
        weights = book_weights(
            {symbol: score_row[symbol] for symbol in book_symbols},
            None,
            vols=vols[day],
        )
        # Gross stays 1: the vol scale renames the book, never its size.
        assert math.fsum(abs(w) for w in weights.values()) == pytest.approx(
            1.0, rel=1e-12
        )
        expected = math.fsum(
            weights[symbol] * returns_row[symbol] for symbol in book_symbols
        )
        assert metrics.book_returns[day] == pytest.approx(
            expected, rel=1e-12, abs=1e-15
        )
        checked += 1
    assert checked >= 20  # the whole grid was measured, not a lucky date


def test_inverse_vol_rescales_the_book_against_z(
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring above is not vacuous: the inverse-vol book really differs
    from the z book on the same scores — the low-vol name carries more
    weight per unit of score than the high-vol name."""
    answer, _, calls = _capturing_evaluate(
        tmp_path,
        sealed_world,
        book=BookConfig(
            beta_neutral=False,
            weighting=INVERSE_VOL_WEIGHTING,
            vol_window_days=VOL_WIRING_WINDOW_DAYS,
        ),
        monkeypatch=monkeypatch,
    )
    assert answer.fail_class is None, answer.fail_detail
    call = calls[0]
    scores, vols = call["scores"], call["vols"]

    day = next(
        day for day in sorted(scores) if scores[day] and day in vols
    )
    score_row, vol_row = scores[day], vols[day]
    symbols = sorted(score_row)
    z_weights = book_weights(score_row, None)
    vol_weights = book_weights(score_row, None, vols=vol_row)
    # Same scores, different books — the vol panel actually bit.
    assert any(
        z_weights[symbol] != pytest.approx(vol_weights[symbol], rel=1e-9)
        for symbol in symbols
    )
    # And the difference is the vol: w_i is proportional to z_i / vol_i.
    ratios = [
        vol_weights[symbol] * vol_row[symbol] / score_row[symbol]
        for symbol in symbols
        if score_row[symbol] != 0.0
    ]
    assert ratios
    assert max(ratios) == pytest.approx(min(ratios), rel=1e-9)


def test_inverse_vol_composes_with_beta_neutral(
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer, context, calls = _capturing_evaluate(
        tmp_path,
        sealed_world,
        book=BookConfig(
            beta_neutral=True,
            beta_window_days=20,
            beta_benchmark=BENCHMARK,
            weighting=INVERSE_VOL_WEIGHTING,
            vol_window_days=VOL_WIRING_WINDOW_DAYS,
        ),
        monkeypatch=monkeypatch,
    )

    assert answer.fail_class is None, answer.fail_detail
    net_call = calls[0]
    scores, betas, vols = (
        net_call["scores"],
        net_call["betas"],
        net_call["vols"],
    )
    assert betas is not None and vols is not None
    assert vols == compute_vols(context, scores)

    metrics = answer.metrics
    assert metrics is not None
    series = net_call["returns"].series[metrics.horizon]
    checked = 0
    for day in series.dates():
        score_row = scores.get(day)
        if not score_row:
            continue
        returns_row = series.at(day)
        book_symbols = sorted(set(score_row) & set(returns_row))
        # book_weights, called the way today's callers call it — betas
        # positional — with the new input keyword-only.
        weights = book_weights(
            {symbol: score_row[symbol] for symbol in book_symbols},
            betas[day],
            vols=vols[day],
        )
        expected = math.fsum(
            weights[symbol] * returns_row[symbol] for symbol in book_symbols
        )
        assert metrics.book_returns[day] == pytest.approx(
            expected, rel=1e-12, abs=1e-15
        )
        checked += 1
    assert checked >= 20
