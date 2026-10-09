"""Feature 1, out-of-sample evaluation — a stored node's signal, off the clock.

additions_spec_m2_baseline_financial_worlds.xml, "Out-of-Sample Evaluation",
feature 1: *System evaluates a stored node's signal on a configured
out-of-sample date window without charging the ledger or touching its node
row, so that an operator returns any node's OOS IR from the same pipeline the
in-sample score came from.*  Two things are under test:

* ``orchestrator._context``'s optional ``oos_dates`` key — validated like
  ``evaluation_dates`` plus two rules of its own (sorted, de-duplicated, and
  strictly after the in-sample window's own embargo) — and
  ``EvaluationContext.oos_dates``, which is an empty tuple when the key is
  absent.
* ``orchestrator._evaluate.evaluate_on_dates`` — the same chain
  ``evaluate_node`` runs (execute, score, align, gate through the caller's
  oracle, cost, measure), over a caller-supplied date grid, charging nothing
  and writing nothing.

This suite runs the real chain, the momentum e2e journey's own recipe scaled
down (an AR(1) world, a hand-written momentum signal, a real
:class:`~orchestrator._oracle.SubtreeOracle` over a fake endpoint), for the
tests that evaluate a node; and the real loader, the way
``test_context.py`` exercises it, for the two tests that are about the
configuration key rather than the pipeline.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.  It passes under pytest-xdist: no
state lives outside a fixture, and every sqlite file is per-test.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import FeeSchedule, load_cost_model
from evaluator import DEFAULT_CONFIG
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import (
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from orchestrator._evaluate import evaluate_on_dates
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

CODE_WORD = "evaluation_config"


# == Part 1: evaluate_on_dates, over the real chain =============================


SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(80))
LOOKBACK = 10
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + 30]
OOS_DATES = BAR_DAYS[LOOKBACK + 30 : LOOKBACK + 60]
WORLD_SEED = 729301
AUTOCORRELATION = 0.5
HORIZON = 1
EPOCH_ID = "epoch-2026-10-09-oos"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: The same trailing-momentum signal test_evaluate.py's own suite uses — see
#: that module's own comment for why it reads ``series[-LOOKBACK]`` rather
#: than ``series[0]``.
MOMENTUM_SIGNAL_CODE = f"""
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
        f"_orchestrator_test_oos_{revision}", path
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


def _metric_columns(database_url: str, node_id: str) -> dict[str, Any]:
    columns = (
        "ic_mean",
        "ic_tstat",
        "ir_standalone",
        "ir_marginal",
        "turnover",
        "cost_adjusted_ir",
    )
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        row = connection.execute(
            f"SELECT {', '.join(columns)} FROM node WHERE id = ?", (node_id,)
        ).fetchone()
    assert row is not None, f"the tree lost its row for {node_id!r}"
    return dict(zip(columns, row))


def _seal_the_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    import random

    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(WORLD_SEED)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol in SYMBOLS:
        price = 100.0 + generator.uniform(-20.0, 20.0)
        previous_return = 0.0
        path: dict[dt.date, float] = {}
        for day in BAR_DAYS:
            shock = generator.gauss(0.0, 0.02)
            return_ = (
                AUTOCORRELATION * previous_return + (1.0 - AUTOCORRELATION) * shock
            )
            price = max(1.0, price * (1.0 + return_))
            path[day] = round(price, 2)
            previous_return = return_
        closes[symbol] = path

    for symbol in SYMBOLS:
        for day in BAR_DAYS:
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
                        "close": [f"{closes[symbol][day]:.2f}"],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 12, 1, tzinfo=dt.UTC))
    mount = service.mount(sealed.name)
    return mount, closes


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering the real-branch targets.

    Mirrors ``test_evaluate.py``'s own stand-in: the series lives on exactly
    the support the request asks for (any date range, any symbol tuple), so
    it serves the in-sample grid and the OOS grid alike.
    """

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


class PermutingEndpoint:
    """A fake ``TargetEndpoint`` answering a different, deterministic series.

    Lives on exactly the same support :class:`RecordingEndpoint` does (so
    the gate's exact-support certification passes identically), but with
    different values — the stand-in for a null assignment's permuted branch,
    which this suite cannot actually produce (nobody on this side of the
    sidecar key can) but can certainly *differ from the real branch by*, to
    prove ``evaluate_on_dates`` measures whatever the oracle answered rather
    than inventing its own series.
    """

    def __init__(self) -> None:
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
                symbol: -0.004 * (index + 1) * (1.0 + 0.3 * (day - first).days)
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
def sealed_world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("oos-evaluate-world")
    return _seal_the_world(workdir)


@pytest.fixture
def context(tmp_path: Path, sealed_world: tuple[Any, dict]) -> EvaluationContext:
    mount, closes = sealed_world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'oos-evaluate-test.db'}"
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
        artifact_dir=tmp_path / "artifacts",
        seed=WORLD_SEED,
        horizon=HORIZON,
        evaluation_dates=EVALUATION_DATES,
        sandbox_runtime="unisolated",
    )


@pytest.fixture
def ledger(context: EvaluationContext) -> TrialLedger:
    return TrialLedger(context.database_url)


def _new_node(context: EvaluationContext) -> str:
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    return node_id


def test_oos_metrics_differ_from_in_sample_ones(context: EvaluationContext) -> None:
    node_id = _new_node(context)
    oracle = SubtreeOracle(RecordingEndpoint(), database_url=context.database_url)

    in_sample_metrics, in_sample_ir = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        dates=EVALUATION_DATES,
    )
    oos_metrics, oos_ir = evaluate_on_dates(
        node_id, MOMENTUM_SIGNAL_CODE, context=context, oracle=oracle, dates=OOS_DATES
    )

    assert in_sample_metrics.dates == len(EVALUATION_DATES)
    assert oos_metrics.dates == len(OOS_DATES)
    # Two different windows of an AR(1) world score two different books —
    # "from the same pipeline the in-sample score came from" (the feature's
    # own words), not the same number read twice.
    assert in_sample_metrics.ic_mean != oos_metrics.ic_mean
    assert in_sample_metrics.ic_tstat != oos_metrics.ic_tstat
    assert in_sample_ir != oos_ir


def test_nothing_is_written(context: EvaluationContext, ledger: TrialLedger) -> None:
    node_id = _new_node(context)
    oracle = SubtreeOracle(RecordingEndpoint(), database_url=context.database_url)

    before_columns = _metric_columns(context.database_url, node_id)
    assert all(value is None for value in before_columns.values())
    before_ledger_rows = len(ledger.rows())
    with closing(sqlite3.connect(_path_of(context.database_url))) as connection:
        before_node_count = connection.execute(
            "SELECT COUNT(*) FROM node"
        ).fetchone()[0]
    artifact_node_dir = context.artifact_dir / CAMPAIGN_ID / node_id

    metrics, cost_adjusted_ir = evaluate_on_dates(
        node_id, MOMENTUM_SIGNAL_CODE, context=context, oracle=oracle, dates=OOS_DATES
    )

    assert metrics.dates == len(OOS_DATES)
    assert isinstance(cost_adjusted_ir, float)
    # The ledger, the node row and the artifact tree are exactly as they
    # were — an OOS read measures a node, it does not re-evaluate one.
    assert len(ledger.rows()) == before_ledger_rows
    assert _metric_columns(context.database_url, node_id) == before_columns
    with closing(sqlite3.connect(_path_of(context.database_url))) as connection:
        after_node_count = connection.execute("SELECT COUNT(*) FROM node").fetchone()[
            0
        ]
    assert after_node_count == before_node_count
    assert not artifact_node_dir.exists()


def test_a_null_node_gets_permuted_targets_out_of_sample_through_the_same_oracle(
    context: EvaluationContext,
) -> None:
    node_id = _new_node(context)
    real_endpoint = RecordingEndpoint()
    real_oracle = SubtreeOracle(real_endpoint, database_url=context.database_url)
    null_endpoint = PermutingEndpoint()
    null_oracle = SubtreeOracle(null_endpoint, database_url=context.database_url)

    real_metrics, real_ir = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=real_oracle,
        dates=OOS_DATES,
    )
    null_metrics, null_ir = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=null_oracle,
        dates=OOS_DATES,
    )

    # Both oracles were asked for exactly this node, out of sample — the
    # same gate_targets ask an in-sample evaluation makes, never skipped.
    assert real_endpoint.requests, "the real oracle must have been asked"
    assert null_endpoint.requests, "the null oracle must have been asked too"
    assert real_endpoint.requests[0].node_id == null_endpoint.requests[0].node_id
    # evaluate_on_dates measures whatever the oracle supplied — real or
    # permuted — never a series it derives on its own.
    assert real_metrics.ic_mean != null_metrics.ic_mean
    assert real_ir != null_ir


# == Part 2: the oos_dates key, through the real loader ==========================


LOAD_SYMBOLS = ("SYM00", "SYM01", "SYM02")
LOAD_FIRST_DAY = dt.date(2026, 9, 1)
LOAD_BAR_DAYS = tuple(
    LOAD_FIRST_DAY + dt.timedelta(days=offset) for offset in range(12)
)
LOAD_LOOKBACK = 6
LOAD_EVALUATION_DAYS = tuple(
    day.isoformat() for day in LOAD_BAR_DAYS[LOAD_LOOKBACK : LOAD_LOOKBACK + 4]
)
LOAD_HORIZON = 1
LOAD_SEED = 20261009
LOAD_EPOCH = "epoch-2026-10-09-oos-load"
LOAD_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32
LOAD_VENUE = "testnet_spot_oos"
LOAD_VERSION = "2026.10.9"


def _load_close(symbol_index: int, day_index: int) -> float:
    return round(100.0 + 10.0 * symbol_index + 0.25 * day_index, 2)


def _stage_and_seal_minimal(lake_root: Path) -> Any:
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, symbol in enumerate(LOAD_SYMBOLS):
        for offset, day in enumerate(LOAD_BAR_DAYS):
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
                        "close": [str(_load_close(index, offset))],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


@pytest.fixture
def load_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, str]]:
    """A minimal, fully configured document and environment for the loader.

    Scaled down from ``test_context.py``'s own ``live`` fixture — this
    suite is not re-testing every key, only ``oos_dates``, so three symbols
    over twelve days is enough to seal a real snapshot the loader can mount.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sealed = _stage_and_seal_minimal(tmp_path / "lake")

    cost_model_path = tmp_path / "cost_model.yaml"
    cost_model_path.write_text(
        "cost_model:\n"
        f'  version: "{LOAD_VERSION}"\n'
        f"  venue: {LOAD_VENUE}\n"
        "  fees:\n"
        "    taker_bps: 12.5\n"
        "    maker_bps: 8.0\n",
        encoding="utf-8",
    )

    document: dict[str, Any] = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(LOAD_EVALUATION_DAYS),
        "horizon": LOAD_HORIZON,
        "seed": LOAD_SEED,
        "epoch_id": LOAD_EPOCH,
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }

    bwrap_dir = tmp_path / "bwrap-path"
    bwrap_dir.mkdir()
    bwrap = bwrap_dir / "bwrap"
    bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)

    environment = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'oos-load-test.db'}",
        "NULLIUS_EVALUATOR_IMAGE": LOAD_IMAGE,
        "NULLIUS_COST_MODEL_PATH": str(cost_model_path),
        "PATH": str(bwrap_dir),
    }
    return document, environment


def _config_path(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / f"evaluation-{abs(id(document))}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_absent_oos_dates_key_leaves_context_oos_dates_an_empty_tuple(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    document, environment = load_world
    assert "oos_dates" not in document
    config_path = _config_path(tmp_path, document)
    environment = dict(environment, NULLIUS_EVALUATION_CONFIG=str(config_path))

    context = load_evaluation_context(environment)

    assert context is not None
    assert context.oos_dates == ()


def test_an_oos_date_inside_the_embargo_is_refused_at_load(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    document, environment = load_world
    evaluation_dates = tuple(dt.date.fromisoformat(s) for s in LOAD_EVALUATION_DAYS)
    embargo_days = DEFAULT_CONFIG["embargo_periods"]
    earliest_allowed = max(evaluation_dates) + dt.timedelta(
        days=LOAD_HORIZON + embargo_days
    )
    # Exactly the boundary: "strictly after" refuses a date equal to it too.
    document = dict(document, oos_dates=[earliest_allowed.isoformat()])
    config_path = _config_path(tmp_path, document)
    environment = dict(environment, NULLIUS_EVALUATION_CONFIG=str(config_path))

    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(environment)

    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:")
    assert "oos_dates" in message
    assert earliest_allowed.isoformat() in message
