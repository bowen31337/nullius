"""additions_spec_research_book_v2.xml feature 2 — the configured beta-neutral book.

System applies the configured beta-neutral book in every evaluation, so that
a campaign with ``"book": {"beta_neutral": true}`` in its evaluation config
returns node and close-out figures from the beta-neutral book.

Three groups of tests, over a tmp sealed snapshot throughout:

* **the config** — :data:`orchestrator._context.BOOK_KEY` is an optional
  object, ``{"beta_neutral": bool, "beta_window_days": int (default 60),
  "beta_benchmark": str (default "BTCUSDT")}``; absent, a context's
  ``book`` is :class:`~orchestrator._context.BookConfig`'s own defaults
  (``beta_neutral=False``); an unknown key inside the block is refused —
  through :func:`~orchestrator._context.load_evaluation_context`, the real
  public seam, over a genuine sealed lake.
* **the betas** — :func:`orchestrator._context.compute_betas` recovers the
  exact OLS slope over a noise-free linear relationship, requires at least
  80% window coverage before rating a symbol, answers no betas at all when
  the configured benchmark is absent from ``context.closes``, and is
  point-in-time: a shock planted strictly after the date being scored never
  changes the beta computed for it.
* **the wiring** — :func:`orchestrator._evaluate.evaluate_node` passes the
  computed betas to every ``compute_node_metrics`` call it makes (the net
  figure and the gross diagnostic alike), so a beta-neutral node's own book
  carries zero weighted beta, and a node evaluated under the absent block
  calls ``compute_node_metrics`` with ``betas=None`` exactly as it did
  before this feature existed.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Runs under pytest-xdist: every
fixture builds a fresh temporary database and lake, with no shared
module-level mutable state across tests.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import random
import sqlite3
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
from evaluator._metrics import _beta_neutral_weights
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import (
    BookConfig,
    EvaluationConfigError,
    EvaluationContext,
    compute_betas,
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
        "seed": 20261014,
        "epoch_id": "epoch-2026-10-14-book-beta",
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


def test_book_absent_gives_the_unchanged_default(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    context = _load(document, environment, tmp_path, "absent-book")
    assert isinstance(context, EvaluationContext)
    assert context.book == BookConfig()
    assert context.book.beta_neutral is False
    assert context.book.beta_window_days == 60
    assert context.book.beta_benchmark == "BTCUSDT"


def test_book_beta_neutral_true_takes_its_own_defaults(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(document, book={"beta_neutral": True})
    context = _load(document, environment, tmp_path, "beta-neutral-defaults")
    assert isinstance(context, EvaluationContext)
    assert context.book == BookConfig(beta_neutral=True)


def test_book_custom_window_and_benchmark_are_honoured(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document,
        book={
            "beta_neutral": True,
            "beta_window_days": 10,
            "beta_benchmark": "ETHUSDT",
        },
    )
    context = _load(document, environment, tmp_path, "beta-neutral-custom")
    assert isinstance(context, EvaluationContext)
    assert context.book == BookConfig(
        beta_neutral=True, beta_window_days=10, beta_benchmark="ETHUSDT"
    )


def test_unknown_key_inside_book_is_refused(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(document, book={"beta_neutral": True, "frobnicate": 1})
    _refuses(
        document, environment, tmp_path, "unknown-book-key", "frobnicate", "book"
    )


def test_book_missing_beta_neutral_is_refused(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(document, book={"beta_window_days": 10})
    _refuses(
        document, environment, tmp_path, "book-missing-beta-neutral", "beta_neutral"
    )


def test_book_not_an_object_is_refused(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(document, book=True)
    _refuses(document, environment, tmp_path, "book-not-object", "book")


# == Part B: compute_betas, directly ============================================

BENCHMARK = "BTCUSDT"


@pytest.fixture(scope="module")
def beta_snapshot(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """A real, minimal sealed snapshot — only its mount is needed by
    :func:`compute_betas`, which never reads ``context.snapshot``, but every
    context in this suite still carries one, for real."""
    workdir = tmp_path_factory.mktemp("beta-compute-world")
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
        epoch_id="epoch-compute-betas-test",
        database_url=f"sqlite:///{tmp_path / name}.db",
        artifact_dir=tmp_path / f"artifacts-{name}",
        seed=1,
        horizon=1,
        evaluation_dates=(dt.date(2026, 1, 10),),
        sandbox_runtime="unisolated",
        book=book,
    )


def test_compute_betas_recovers_the_exact_ols_slope(
    beta_snapshot: Any, tmp_path: Path
) -> None:
    window_days = 5
    days = tuple(dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(window_days + 1))
    bench_returns = [0.01, -0.02, 0.015, 0.03, -0.01]
    bench_closes = {days[0]: 100.0}
    for offset, r in enumerate(bench_returns):
        bench_closes[days[offset + 1]] = bench_closes[days[offset]] * (1.0 + r)

    true_beta = 1.7
    symbol_closes = {days[0]: 50.0}
    for offset, r in enumerate(bench_returns):
        symbol_closes[days[offset + 1]] = symbol_closes[days[offset]] * (
            1.0 + true_beta * r
        )

    closes = {BENCHMARK: bench_closes, "AAA": symbol_closes}
    book = BookConfig(
        beta_neutral=True, beta_window_days=window_days, beta_benchmark=BENCHMARK
    )
    context = _minimal_context(
        beta_snapshot, closes, book=book, tmp_path=tmp_path, name="exact-slope"
    )

    betas = compute_betas(context, {days[-1]: {"AAA": 1.0}})

    assert betas[days[-1]]["AAA"] == pytest.approx(true_beta, rel=1e-9)


def test_compute_betas_requires_80_percent_window_coverage(
    beta_snapshot: Any, tmp_path: Path
) -> None:
    window_days = 10
    days = tuple(
        dt.date(2026, 2, 1) + dt.timedelta(days=i) for i in range(window_days + 1)
    )
    # Varied, not constant: a constant daily return gives the benchmark zero
    # variance, and _ols_slope answers no beta at all (a degenerate
    # regression) regardless of coverage — exactly the case this test must
    # not confuse with the coverage refusal.
    bench_returns = [0.01, -0.02, 0.015, -0.01, 0.025, -0.015, 0.02, -0.005, 0.03, -0.02]
    bench_closes = {days[0]: 100.0}
    for offset, r in enumerate(bench_returns):
        bench_closes[days[offset + 1]] = bench_closes[days[offset]] * (1.0 + r)

    full_closes = {days[0]: 50.0}
    for offset, r in enumerate(bench_returns):
        full_closes[days[offset + 1]] = full_closes[days[offset]] * (1.0 + 1.3 * r)

    # Drop three widely-spaced days from the sparse symbol's series: each
    # deletion breaks up to two window returns (the day's own, and the
    # following day's, which needs it as the prior close), so three
    # deletions leave well under 80% of the ten window returns intact.
    sparse_closes = dict(full_closes)
    for day in (days[2], days[5], days[8]):
        del sparse_closes[day]

    closes = {BENCHMARK: bench_closes, "AAA": full_closes, "BBB": sparse_closes}
    book = BookConfig(
        beta_neutral=True, beta_window_days=window_days, beta_benchmark=BENCHMARK
    )
    context = _minimal_context(
        beta_snapshot, closes, book=book, tmp_path=tmp_path, name="coverage"
    )

    betas = compute_betas(context, {days[-1]: {"AAA": 1.0, "BBB": 1.0}})

    assert "AAA" in betas[days[-1]]
    assert "BBB" not in betas[days[-1]]


def test_compute_betas_absent_benchmark_gives_no_betas(
    beta_snapshot: Any, tmp_path: Path
) -> None:
    days = tuple(dt.date(2026, 3, 1) + dt.timedelta(days=i) for i in range(6))
    symbol_closes = {day: 50.0 + index for index, day in enumerate(days)}
    closes = {"AAA": symbol_closes}  # no BTCUSDT entry at all
    book = BookConfig(beta_neutral=True, beta_window_days=5, beta_benchmark=BENCHMARK)
    context = _minimal_context(
        beta_snapshot, closes, book=book, tmp_path=tmp_path, name="absent-benchmark"
    )

    betas = compute_betas(context, {days[-1]: {"AAA": 1.0}})

    assert betas[days[-1]] == {}


def test_compute_betas_is_point_in_time(beta_snapshot: Any, tmp_path: Path) -> None:
    window_days = 5
    days = tuple(
        dt.date(2026, 4, 1) + dt.timedelta(days=i) for i in range(window_days + 1)
    )
    future_day = days[-1] + dt.timedelta(days=1)

    # Varied, not constant: see the coverage test above for why a constant
    # daily return (zero variance) would leave no beta to compare at all.
    bench_returns = [0.01, -0.02, 0.015, 0.03, -0.01]
    bench_closes = {days[0]: 100.0}
    symbol_closes = {days[0]: 50.0}
    for offset, r in enumerate(bench_returns):
        bench_closes[days[offset + 1]] = bench_closes[days[offset]] * (1.0 + r)
        symbol_closes[days[offset + 1]] = symbol_closes[days[offset]] * (1.0 + 1.2 * r)

    closes_before = {BENCHMARK: dict(bench_closes), "AAA": dict(symbol_closes)}
    # Plant a massive shock strictly after D = days[-1] — this is the only
    # difference between the two worlds.
    closes_after = {
        BENCHMARK: {**bench_closes, future_day: bench_closes[days[-1]] * 50.0},
        "AAA": {**symbol_closes, future_day: symbol_closes[days[-1]] * 0.01},
    }

    book = BookConfig(
        beta_neutral=True, beta_window_days=window_days, beta_benchmark=BENCHMARK
    )
    before = _minimal_context(
        beta_snapshot, closes_before, book=book, tmp_path=tmp_path, name="pit-before"
    )
    after = _minimal_context(
        beta_snapshot, closes_after, book=book, tmp_path=tmp_path, name="pit-after"
    )

    scores = {days[-1]: {"AAA": 1.0}}
    betas_before = compute_betas(before, scores)
    betas_after = compute_betas(after, scores)

    assert betas_before[days[-1]]["AAA"] == pytest.approx(
        betas_after[days[-1]]["AAA"], rel=1e-12
    )


# == Part C: the wiring, through evaluate_node ==================================

NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

PART_C_SYMBOLS = ("AAA", "BBB", "CCC")
PART_C_FIRST_DAY = dt.date(2026, 4, 1)
PART_C_BAR_DAYS = tuple(
    PART_C_FIRST_DAY + dt.timedelta(days=offset) for offset in range(100)
)
BETA_WINDOW_DAYS = 20
EVALUATION_DATES = PART_C_BAR_DAYS[40:80]
HORIZON = 1
WORLD_SEED = 20261014
EPOCH_ID = "epoch-2026-10-14-book-beta-wiring"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: test_evaluate_turnover_cost.py's own momentum signal: it re-ranks symbols
#: by trailing return every rebalance date, so the per-date information
#: coefficient actually varies (a signal whose score never changes gives a
#: constant IC across every date, which compute_node_metrics itself refuses
#: as an undefined t-statistic) and the long/short split moves date to date.
LOOKBACK = 10
BETA_SIGNAL_CODE = f"""
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
        f"_orchestrator_test_book_beta_{revision}", path
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


def _seal_the_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(WORLD_SEED)
    benchmark_path: dict[dt.date, float] = {}
    price = 100.0
    for day in PART_C_BAR_DAYS:
        shock = generator.gauss(0.0, 0.02)
        price = max(1.0, price * (1.0 + shock))
        benchmark_path[day] = round(price, 4)

    closes: dict[str, dict[dt.date, float]] = {BENCHMARK: benchmark_path}
    for symbol in PART_C_SYMBOLS:
        price = 100.0 + generator.uniform(-10.0, 10.0)
        path: dict[dt.date, float] = {}
        previous_day: dt.date | None = None
        for day in PART_C_BAR_DAYS:
            if previous_day is None:
                path[day] = round(price, 4)
            else:
                bench_return = (
                    benchmark_path[day] / benchmark_path[previous_day] - 1.0
                )
                idiosyncratic = generator.gauss(0.0, 0.01)
                move = 0.5 * bench_return + idiosyncratic
                price = max(1.0, price * (1.0 + move))
                path[day] = round(price, 4)
            previous_day = day
        closes[symbol] = path

    for symbol in PART_C_SYMBOLS:
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
                        "close": [f"{closes[symbol][day]:.4f}"],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    mount = service.mount(sealed.name)
    return mount, closes


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering a dense, gapless real-branch series."""

    def __init__(self, *, charges_budget: bool = True) -> None:
        self.charges_budget = charges_budget
        self.requests: list[Any] = []

    def post(self, request: Any) -> TargetResponse:
        self.requests.append(request)
        first, last = request.date_range
        days: list[dt.date] = []
        day = first
        while day <= last:
            days.append(day)
            day += dt.timedelta(days=1)
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
            charges_budget=self.charges_budget,
        )


@pytest.fixture(scope="module")
def sealed_world(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    workdir = tmp_path_factory.mktemp("book-beta-wiring-world")
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
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
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


@pytest.fixture
def beta_neutral_context(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> EvaluationContext:
    return _build_context(
        tmp_path,
        sealed_world,
        book=BookConfig(
            beta_neutral=True,
            beta_window_days=BETA_WINDOW_DAYS,
            beta_benchmark=BENCHMARK,
        ),
        name="beta-neutral",
    )


@pytest.fixture
def plain_context(tmp_path: Path, sealed_world: tuple[Any, dict]) -> EvaluationContext:
    return _build_context(tmp_path, sealed_world, book=BookConfig(), name="plain")


def _evaluate(context: EvaluationContext) -> Any:
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    ledger = TrialLedger(context.database_url)
    return evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        BETA_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )


def test_beta_neutral_node_has_zero_book_beta(
    beta_neutral_context: EvaluationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evaluator import compute_node_metrics as real_compute_node_metrics

    calls: list[tuple[Mapping[Any, Any], Mapping[Any, Any] | None]] = []

    def _capture(returns: Any, scores: Any, **kwargs: Any) -> Any:
        calls.append((scores, kwargs.get("betas")))
        return real_compute_node_metrics(returns, scores, **kwargs)

    monkeypatch.setattr("orchestrator._evaluate.compute_node_metrics", _capture)

    answer = _evaluate(beta_neutral_context)

    assert answer.fail_class is None
    assert len(calls) == 2  # the net figure, then _gross_ir_tstat's diagnostic

    scores0, betas0 = calls[0]
    assert betas0 is not None

    scored_days = [day for day in scores0 if scores0[day]]
    assert scored_days
    day = scored_days[len(scored_days) // 2]
    row = scores0[day]

    # Every symbol has dense history well past the 20-day window by the
    # middle of the evaluation grid.
    assert set(betas0.get(day, {})) == set(row)

    gross = sum(abs(z) for z in row.values())
    weights = {symbol: z / gross for symbol, z in row.items()}
    rescaled = _beta_neutral_weights(weights, betas0[day])
    book_beta = sum(rescaled[symbol] * betas0[day][symbol] for symbol in rescaled)
    assert book_beta == pytest.approx(0.0, abs=1e-9)


def test_absent_book_calls_compute_node_metrics_with_betas_none(
    plain_context: EvaluationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evaluator import compute_node_metrics as real_compute_node_metrics

    calls: list[Mapping[Any, Any] | None] = []

    def _capture(returns: Any, scores: Any, **kwargs: Any) -> Any:
        calls.append(kwargs.get("betas"))
        return real_compute_node_metrics(returns, scores, **kwargs)

    monkeypatch.setattr("orchestrator._evaluate.compute_node_metrics", _capture)

    answer = _evaluate(plain_context)

    assert answer.fail_class is None
    assert len(calls) == 2
    assert all(betas is None for betas in calls)
