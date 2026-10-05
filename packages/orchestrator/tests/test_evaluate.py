"""Feature 7, the one-call evaluation — a live node, scored and persisted.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 7:
*System evaluates one live node with
orchestrator._evaluate.evaluate_node(node_id, campaign_id, depth, code, *,
context, oracle, ledger), and it answers a NodeEvaluation with node_id,
metrics, score (a signal_agent.ScoreRecord), charges_budget, fail_class,
persistence and debit.*  The member is wiring over Z0 and over this
member's own features 2 through 6, so this suite runs the *real* chain end
to end: a sealed snapshot staged and sealed through
:class:`snapshot.SnapshotService` (the momentum e2e journey's own fixture
approach, scaled down — a pinned AR(1) world and a hand-written momentum
signal, scored by the real :class:`evaluator.SignalSandbox`), a real
:class:`~orchestrator._oracle.SubtreeOracle` over a fake ``TargetEndpoint``
that records every request, a real ``node`` table migrated with features
97 and 101's own migrations, and a real :class:`ledger.TrialLedger`.

One test per claim the feature sentence makes:

* **the import screen runs first, and the code is never executed** — a
  disallowed import is charged with ``fail_class="disallowed_import"``
  before any sandbox spawns, and the node's metric columns stay ``NULL``.

* **the unisolated warning** — one ``WARNING`` line naming the node, every
  evaluation, when ``context.sandbox_runtime`` is ``"unisolated"``.

* **the chain lands a measured node** — the metrics, the score, the
  charged row and the persisted artifact set, all stamped with the
  oracle's own ``charges_budget``.

* **the empty-book marginal IR** — ``ir_marginal`` on a fresh node's score
  equals its ``ir_standalone``, the evaluator's own stand-in for "nothing
  to be marginal against yet".

* **a failing signal is charged under its class** — a conforming-shaped
  but crashing signal is charged with ``fail_class="SandboxExecutionError"``,
  carries no metrics, and leaves the node's row untouched.

* **idempotent re-evaluation** — a second call for the same node answers
  the same metrics, writes no second row (``persistence.tree_written`` is
  ``False``) and appends no second debit.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import logging
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
from orchestrator._evaluate import (
    NodeEvaluation,
    NodePersistence,
    SandboxExecutionError,
    evaluate_node,
)
from orchestrator._oracle import SubtreeOracle
from sandbox import DISALLOWED_IMPORT_CODE
from snapshot import SnapshotService

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The two migrations that make the tree this feature writes onto: ``0118``
#: creates the ``node`` table, ``0114`` adds the seven metric columns.
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

#: The world's cross-section and bar span — smaller than the momentum
#: journey's own (eight symbols, forty-eight bars) because this suite's
#: claim is about the orchestration, not the coefficient; four symbols and
#: twenty bars still give every per-date rank correlation real variation
#: (the thing ``compute_node_metrics`` needs to not divide by a zero
#: standard error) at a fraction of the sandbox spawns.
SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(20))
LOOKBACK = 6
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + 8]
WORLD_SEED = 424242
AUTOCORRELATION = 0.5
HORIZON = 1
EPOCH_ID = "epoch-2026-10-05-a"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: A hand-written momentum signal, in the shape a node's source arrives —
#: the trailing price change over the window's own lookback bars.  Written
#: the way the momentum e2e journey's own signal is, so a genuine sandbox
#: spawn produces a real, varying cross-section every rebalance date.
#: Imports polars explicitly: unlike the evaluator's own embedded
#: SignalSandbox (which pre-seeds "pl" in the signal's namespace),
#: orchestrator._sandbox_child's bootstrap (feature 7's own executor) gives
#: the signal nothing it did not import itself — "polars" is on the
#: committed allowlist precisely so a signal can do this.
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
            first = float(series[0]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""

#: A signal with no disallowed import, but one that raises at run time — the
#: sandbox's own "crash" resource failure, never a raised exception that
#: escapes the box.
CRASHING_SIGNAL_CODE = """
def signal(ctx, seed):
    raise ValueError("this signal always crashes")
"""

#: A signal importing a module outside the committed allowlist — refused by
#: the import screen before anything executes.
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
    """Insert one root node row — the state a live evaluation writes onto.

    A live evaluation never creates nodes (feature 3's own law); this suite
    plants the row the discovery loop or the root planter would have
    written first, with every metric column left ``NULL``.
    """
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


# -- The sealed world, the momentum journey's own approach, scaled down --------


def _seal_the_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    """Stage an AR(1) momentum world and seal it — the momentum journey's own
    recipe, scaled down to four symbols and twenty bars.
    """
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


# -- The oracle: SubtreeOracle over a fake TargetEndpoint -----------------------


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering the real-branch targets.

    Mirrors ``tests/e2e/test_momentum_signal_positive_ic.py``'s own stand-in
    oracle — the real alignment's own series, so the gate's support check
    certifies honestly — but shaped as the §7.2 route feature 2 adapts,
    recording every request it was asked.
    """

    def __init__(self, *, charges_budget: bool = True) -> None:
        self.charges_budget = charges_budget
        self.requests: list[Any] = []

    def post(self, request: Any) -> TargetResponse:
        self.requests.append(request)
        # The gate certifies the answer lives on *exactly* the aligned
        # support, per date and per symbol — no wider, no narrower.  This
        # suite's world is dense and gapless (every symbol scored and
        # priced every bar day), so the covered support for any horizon is
        # exactly every calendar day in the request's own date_range, for
        # exactly the symbols it named — reconstructed here rather than
        # hand-pinned, so the answer is honestly the support that was asked
        # for at whichever horizon the gate covered.
        first, last = request.date_range
        days: list[dt.date] = []
        day = first
        while day <= last:
            days.append(day)
            day += dt.timedelta(days=1)
        symbols = sorted(request.symbols)
        # Varies by symbol (so the cross-sectional rank correlation is
        # defined) and by date (so the per-date coefficients and the
        # equal-weight book's return both have real variance) — a fixed
        # deterministic target, never read from a null bit, and never
        # compared to the aligned values by the gate (the thing under test
        # is the gate's exact-support certification, not its arithmetic).
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
    workdir = tmp_path_factory.mktemp("evaluate-world")
    return _seal_the_world(workdir)


@pytest.fixture
def context(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> EvaluationContext:
    """One evaluation context, built directly — feature 5's loader is not
    under test here, so the dataclass is constructed with real inputs
    rather than loaded from a JSON file and an environment.
    """
    mount, closes = sealed_world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'evaluate-test.db'}"
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
    """The real trial ledger, over the context's own database."""
    return TrialLedger(context.database_url)


def _new_node(context: EvaluationContext) -> str:
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    return node_id


# -- The import screen -----------------------------------------------------------


def test_a_disallowed_import_is_charged_and_the_code_never_executes(
    context: EvaluationContext, ledger: TrialLedger
) -> None:
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

    assert isinstance(answer, NodeEvaluation)
    assert answer.metrics is None
    assert answer.persistence is None
    assert answer.fail_class == DISALLOWED_IMPORT_CODE == "disallowed_import"
    assert answer.score.fail_class == DISALLOWED_IMPORT_CODE
    assert answer.score.ic_mean is None
    assert answer.charges_budget is True
    # The code never ran: the oracle was never asked, because the chain
    # never reached gate_targets.
    assert endpoint.requests == []
    # The node's row is untouched — still unmeasured.
    columns = _metric_columns(context.database_url, node_id)
    assert all(value is None for value in columns.values())
    # The node was still charged — a refused import still consumed a
    # hypothesis.
    assert answer.debit.appended is True
    assert answer.debit.charge.outcome == "error"


# -- The unisolated warning -------------------------------------------------------


def test_unisolated_sandbox_logs_one_warning_naming_the_node(
    context: EvaluationContext, ledger: TrialLedger, caplog: pytest.LogCaptureFixture
) -> None:
    node_id = _new_node(context)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    assert context.sandbox_runtime == "unisolated"

    with caplog.at_level(logging.WARNING, logger="orchestrator._evaluate"):
        evaluate_node(
            node_id,
            CAMPAIGN_ID,
            0,
            DISALLOWED_SIGNAL_CODE,
            context=context,
            oracle=oracle,
            ledger=ledger,
        )

    warnings = [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "unisolated sandbox" in warnings[0].getMessage()
    assert node_id in warnings[0].getMessage()


# -- The successful chain ---------------------------------------------------------


def test_the_chain_lands_a_measured_node_charged_once(
    context: EvaluationContext, ledger: TrialLedger
) -> None:
    node_id = _new_node(context)
    endpoint = RecordingEndpoint(charges_budget=True)
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        depth=0,
        code=MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.node_id == node_id
    assert answer.fail_class is None
    assert answer.metrics is not None
    assert answer.metrics.dates == len(EVALUATION_DATES)
    assert answer.charges_budget is True
    assert endpoint.requests, "the oracle must have been asked"

    # The score carries the same six scalars the metrics measured, with no
    # failure.
    assert answer.score.fail_class is None
    assert answer.score.ic_mean == pytest.approx(answer.metrics.ic_mean)
    assert answer.score.ir_standalone == pytest.approx(answer.metrics.ir_standalone)
    assert answer.score.turnover == pytest.approx(answer.metrics.turnover)
    # Spec A has no resident book: compute_marginal_ir(priced, {}) always
    # refuses, and the empty-book stand-in is the candidate's own
    # standalone IR (the evaluator's own refusal names this fallback).
    assert answer.score.ir_marginal == pytest.approx(answer.metrics.ir_standalone)

    # The node row landed the same six scalars.
    columns = _metric_columns(context.database_url, node_id)
    assert columns["ic_mean"] == pytest.approx(answer.metrics.ic_mean)
    assert columns["ir_marginal"] == pytest.approx(answer.score.ir_marginal)
    assert columns["cost_adjusted_ir"] == pytest.approx(answer.score.cost_adjusted_ir)

    # The artifact set this spec measures landed on disk.
    node_dir = context.artifact_dir / CAMPAIGN_ID / node_id
    assert (node_dir / "signal_returns.parquet").exists()
    assert (node_dir / "ic_series.parquet").exists()
    assert (node_dir / "turnover_series.parquet").exists()
    assert (node_dir / "exec_trace.json").exists()
    assert (node_dir / "code.py").exists()
    assert (node_dir / "code.py").read_text(encoding="utf-8") == MOMENTUM_SIGNAL_CODE

    # Persistence and the debit both say "first write".
    assert isinstance(answer.persistence, NodePersistence)
    assert answer.persistence.tree_written is True
    assert answer.persistence.artifact_written is True
    assert answer.debit.appended is True
    assert answer.debit.charge.outcome == "ok"
    assert answer.debit.charge.charges_budget is True


def test_charges_budget_is_the_oracle_s_own_bit(
    context: EvaluationContext, ledger: TrialLedger
) -> None:
    # The null direction: a False directive from the oracle must arrive on
    # the answer and the charge exactly as answered, never "corrected".
    node_id = _new_node(context)
    endpoint = RecordingEndpoint(charges_budget=False)
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

    assert answer.charges_budget is False
    assert answer.debit.charge.charges_budget is False


# -- A failing signal --------------------------------------------------------------


def test_a_crashing_signal_is_charged_under_its_own_class(
    context: EvaluationContext, ledger: TrialLedger
) -> None:
    node_id = _new_node(context)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        CRASHING_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.metrics is None
    assert answer.persistence is None
    assert answer.fail_class == SandboxExecutionError.__name__
    assert answer.score.fail_class == SandboxExecutionError.__name__
    assert answer.score.ic_mean is None
    # The failure happened before the oracle was ever reached (the signal
    # fails at step 2, long before step 5's gate), so the conservative
    # directive is charged.
    assert endpoint.requests == []
    assert answer.charges_budget is True
    columns = _metric_columns(context.database_url, node_id)
    assert all(value is None for value in columns.values())
    assert answer.debit.appended is True
    assert answer.debit.charge.outcome == "error"


# -- Idempotency -------------------------------------------------------------------


def test_evaluating_the_same_node_twice_is_idempotent(
    context: EvaluationContext, ledger: TrialLedger
) -> None:
    node_id = _new_node(context)
    endpoint = RecordingEndpoint(charges_budget=True)
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    first = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )
    second = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert first.metrics is not None and second.metrics is not None
    assert second.metrics.ic_mean == pytest.approx(first.metrics.ic_mean)
    assert second.score.ir_marginal == pytest.approx(first.score.ir_marginal)

    # No second row, no second debit.
    assert first.persistence.tree_written is True
    assert second.persistence.tree_written is False
    assert first.debit.appended is True
    assert second.debit.appended is False
    assert second.debit.seq == first.debit.seq

    with closing(
        sqlite3.connect(_path_of(context.database_url))
    ) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM node WHERE id = ?", (node_id,)
        ).fetchone()[0]
    assert count == 1

    # The ledger holds exactly one row for this node — a second evaluation
    # appends no second debit, read off the ledger itself rather than off
    # the answer alone.
    landed = [row for row in ledger.rows() if row.node_id == node_id]
    assert len(landed) == 1
