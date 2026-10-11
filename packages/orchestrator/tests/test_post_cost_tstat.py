"""Feature 1, the post-cost IR t-statistic — persisted beside ``ic_tstat``.

additions_spec_cost_aware_selection.xml, "Cost-Aware Selection", feature 1:
*System persists every evaluated node's post-cost IR t-statistic, so that a
node row returns ``ir_tstat = ir_standalone · √(dates)`` beside ``ic_tstat``.*
``node`` gains ``ir_tstat REAL NULL``, added by probe-then-``ALTER`` in
:mod:`orchestrator._tree_writer` rather than by a migration (``0114`` shipped
its seven metric columns before this feature existed), and
:func:`orchestrator._evaluate.evaluate_node` computes the value once from the
same ``metrics`` it already measured and carries it on the node row, the
answered :class:`~signal_agent.ScoreRecord` and — through that record's own
``to_json()``, which :mod:`orchestrator._campaign`'s ``node_evaluated`` event
renders the score through unchanged — the emitted event.

One test per claim the feature sentence makes:

* **the value** — ``ir_tstat`` on a scored node's row and answered score both
  equal ``metrics.ir_standalone * sqrt(metrics.dates)``.

* **a pre-existing node table upgrades in place** — a tree migrated through
  ``0118``/``0114`` alone (so it predates this feature) gains ``ir_tstat`` the
  first time :class:`~orchestrator._tree_writer.NodeMetricsWriter.write_node`
  is called against it, and the value lands correctly in the same call.

* **a failed node has NULL** — a node refused at the import screen (before
  ``metrics`` is ever measured) carries ``ir_tstat=None`` on its score, and
  its row's column — once the tree holds it at all — stays ``NULL``.

* **the event carries the field** — ``ScoreRecord.to_json()``, exactly what
  ``orchestrator._campaign``'s ``node_evaluated`` event nests as its own
  ``"score"`` key, carries ``ir_tstat`` under that name.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.  Runs under pytest-xdist: every
fixture builds a fresh temporary database and sealed world, with no shared
module-level mutable state across tests.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import random
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
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import EvaluationContext
from orchestrator._evaluate import NodeEvaluation, _TreeNodeRow, evaluate_node
from orchestrator._oracle import SubtreeOracle
from orchestrator._tree_writer import NodeMetricsWriter
from sandbox import DISALLOWED_IMPORT_CODE
from snapshot import SnapshotService

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The two migrations that make the tree this feature writes onto — the same
#: pair test_evaluate.py and test_tree_writer.py both migrate through.
#: Deliberately *not* joined by an ``ir_tstat`` migration: the feature adds
#: that column itself, at write time, which is exactly what this suite's
#: "upgrades in place" test holds the writer to.
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

#: A small world — the same recipe test_evaluate.py's own fixture uses, at
#: the same seed: four symbols and sixty rebalance dates are already pinned
#: clean against all six of step 10's leakage probes at this width, so this
#: suite inherits that clean pin rather than hunting for a new one.
SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(71))
LOOKBACK = 10
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + 60]
WORLD_SEED = 424243
AUTOCORRELATION = 0.5
HORIZON = 1
EPOCH_ID = "epoch-2026-10-05-cost-aware"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: The same hand-written momentum signal test_evaluate.py scores its own
#: "chain lands a measured node" claim with — this suite needs a signal that
#: actually produces metrics, not a specific coefficient.
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

#: A signal importing a module outside the committed allowlist — refused by
#: the import screen before anything executes, so ``metrics`` is never
#: measured and the node's row stays exactly as planted.  The fastest and
#: most deterministic way to get a failed node for this suite's NULL claim.
DISALLOWED_SIGNAL_CODE = """
import os

def signal(ctx, seed):
    return pl.Series([0.0 for _ in ctx.universe])
"""


# -- Migrations and raw-SQL planting --------------------------------------------


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_{revision}", path
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
    """Insert one root node row — the state a live evaluation writes onto."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, NULL, ?, ?, ?)",
            (node_id, campaign_id, "macro", 0),
        )


def _ir_tstat_column(database_url: str, node_id: str) -> float | None:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        row = connection.execute(
            "SELECT ir_tstat FROM node WHERE id = ?", (node_id,)
        ).fetchone()
    assert row is not None, f"the tree lost its row for {node_id!r}"
    return row[0]


def _table_has_ir_tstat(database_url: str) -> bool:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        columns = connection.execute("PRAGMA table_info(node)").fetchall()
    return any(column[1] == "ir_tstat" for column in columns)


# -- The sealed world, test_evaluate.py's own recipe, scaled down --------------


def _seal_the_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
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
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    mount = service.mount(sealed.name)
    return mount, closes


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering the real-branch targets.

    The same stand-in oracle test_evaluate.py uses, trimmed to this suite's
    own needs: a dense, gapless target series over whatever support the gate
    asks for.
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


# -- Fixtures --------------------------------------------------------------------


@pytest.fixture(scope="module")
def sealed_world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("post-cost-tstat-world")
    return _seal_the_world(workdir)


@pytest.fixture
def context(tmp_path: Path, sealed_world: tuple[Any, dict]) -> EvaluationContext:
    mount, closes = sealed_world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'post-cost-tstat.db'}"
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


# -- The value: ir_standalone * sqrt(dates) -------------------------------------


def test_ir_tstat_equals_ir_standalone_times_sqrt_dates_for_a_scored_node(
    context: EvaluationContext, ledger: TrialLedger
) -> None:
    node_id = _new_node(context)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert isinstance(answer, NodeEvaluation)
    assert answer.fail_class is None
    assert answer.metrics is not None
    expected = answer.metrics.ir_standalone * math.sqrt(answer.metrics.dates)

    assert answer.score.ir_tstat == pytest.approx(expected)
    assert _ir_tstat_column(context.database_url, node_id) == pytest.approx(expected)


# -- A pre-existing node table upgrades in place --------------------------------


def test_a_pre_existing_node_table_upgrades_in_place(tmp_path: Path) -> None:
    # A tree migrated through 0118/0114 alone predates this feature: it has
    # no ir_tstat column at all, the same state every deployment that ran
    # this member before this spec landed is in.
    database_url = f"sqlite:///{tmp_path / 'legacy-tree.db'}"
    _migrate_tree(database_url)
    assert _table_has_ir_tstat(database_url) is False

    node_id = str(uuid.uuid4())
    _plant_root(database_url, node_id=node_id, campaign_id=str(uuid.uuid4()))

    writer = NodeMetricsWriter(database_url)
    answered_id, written = writer.write_node(
        _TreeNodeRow(
            node_id=node_id,
            ic_mean=0.05,
            ic_tstat=2.5,
            ir_tstat=3.75,
            ir_standalone=0.8,
            ir_marginal=0.6,
            turnover=0.3,
            cost_adjusted_ir=0.55,
            perturb_stability=None,
        )
    )

    assert answered_id == node_id
    assert written is True
    # The column exists now, and the value the call offered landed on it —
    # the upgrade and the write happen in the one call, not two.
    assert _table_has_ir_tstat(database_url) is True
    assert _ir_tstat_column(database_url, node_id) == pytest.approx(3.75)


# -- A failed node has NULL ------------------------------------------------------


def test_a_failed_node_has_null_ir_tstat(
    context: EvaluationContext, ledger: TrialLedger
) -> None:
    # Force the column to exist on this test's own database first, through
    # the real writer, on a sibling node — the same way any deployment's
    # tree gains the column the first time *any* node evaluates cleanly.
    # This keeps the DB-level assertion below meaningful rather than a
    # "no such column" error about a tree nothing has upgraded yet.
    sibling_id = _new_node(context)
    NodeMetricsWriter(context.database_url).write_node(
        _TreeNodeRow(
            node_id=sibling_id,
            ic_mean=0.01,
            ic_tstat=0.5,
            ir_tstat=0.6,
            ir_standalone=0.2,
            ir_marginal=0.2,
            turnover=0.1,
            cost_adjusted_ir=0.15,
            perturb_stability=None,
        )
    )
    assert _table_has_ir_tstat(context.database_url) is True

    node_id = _new_node(context)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        DISALLOWED_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.fail_class == DISALLOWED_IMPORT_CODE
    assert answer.metrics is None
    assert answer.score.ir_tstat is None
    # _persist (and so write_node) is never reached before metrics exist, so
    # the failed node's own row is left exactly as planted: NULL.
    assert _ir_tstat_column(context.database_url, node_id) is None


# -- The event carries the field --------------------------------------------------


def test_the_scored_node_s_event_payload_carries_ir_tstat(
    context: EvaluationContext, ledger: TrialLedger
) -> None:
    # orchestrator._campaign's node_evaluated event nests
    # json.loads(score.to_json()) under its own "score" key, unchanged — so
    # this is exactly what that event carries for this node, without
    # reaching into _campaign's own machinery to prove it.
    node_id = _new_node(context)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.fail_class is None
    expected = answer.metrics.ir_standalone * math.sqrt(answer.metrics.dates)
    payload = json.loads(answer.score.to_json())
    assert "ir_tstat" in payload
    assert payload["ir_tstat"] == pytest.approx(expected)
