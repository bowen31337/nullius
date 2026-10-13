"""bug_spec_turnover_cost_charge, bug 2 — the venue fee reaches the book.

``evaluate_node`` and ``evaluate_on_dates`` priced the per-symbol fee through
``apply_costs`` but never handed ``compute_node_metrics`` a
``cost_per_unit_traded`` — and that per-symbol charge cancels in the node's
own dollar-neutral book (``Σ w_i f = f Σ w_i = 0``), so ``ir_tstat``,
``cost_adjusted_ir`` and the node row were gross of turnover regardless of
the configured fee. Both call sites now pass
``context.cost_schedule.fee_fraction(TAKER)`` through, the same rate
``_cost_schedule_from_context`` quotes.

One test per claim bug 2's own sentence makes:

* **the reproduction** — evaluating the same node twice over the same
  world, once at the configured fee and once at a 0 bps schedule, no longer
  gives identical ``ir_tstat``/``cost_adjusted_ir``; the configured-fee
  reading is strictly lower for a turnover-bearing signal.
* **the diagnostic** — ``evaluate_node``'s own answer carries
  ``ir_tstat_gross``, the same figure recomputed with no turnover charge,
  and the configured-fee reading is below it.
* **a 0 bps schedule gives equal figures** — net and gross agree exactly
  when there is nothing to charge.
* **``evaluate_on_dates``' result is net and carries the gross figure** —
  the same diagnostic rides on the out-of-sample call's own answer, which
  still destructures as the two-element ``(metrics, cost_adjusted_ir)``
  pair ``closeout.py`` and ``_financial_eval.py`` unpack.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Runs under pytest-xdist: every
fixture builds a fresh temporary database over one shared, read-only sealed
world, with no shared module-level mutable state across tests.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
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
from orchestrator._evaluate import NodeEvaluation, evaluate_node, evaluate_on_dates
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The two migrations that make the tree this feature writes onto — the same
#: pair test_evaluate.py and test_post_cost_tstat.py both migrate through.
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

#: test_post_cost_tstat.py's own world recipe, at the same seed: four
#: symbols and sixty rebalance dates, already pinned clean against step 10's
#: leakage probes at this width.
SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(71))
LOOKBACK = 10
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + 60]
WORLD_SEED = 424243
AUTOCORRELATION = 0.5
HORIZON = 1
EPOCH_ID = "epoch-2026-10-13-turnover-cost"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: A fee large enough that a dollar-neutral book's ordinary daily turnover
#: prices a charge comparable to the book's own daily return, so the net
#: figure is reliably — not just theoretically — below the gross one for an
#: everyday momentum signal, rather than hoping a 10 bps venue fee happens
#: to bite hard enough on one particular seed.
TAKER_BPS = 75.0

#: The same hand-written momentum signal test_evaluate.py and
#: test_post_cost_tstat.py score their own chain with — it re-ranks symbols
#: by trailing return every rebalance date, so its book's weights move date
#: to date and its turnover is never zero.
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


# -- Migrations and raw-SQL planting --------------------------------------------


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_turnover_cost_{revision}", path
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


# -- The sealed world, test_post_cost_tstat.py's own recipe --------------------


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


# -- Fixtures --------------------------------------------------------------------


@pytest.fixture(scope="module")
def sealed_world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("turnover-cost-world")
    return _seal_the_world(workdir)


def _build_context(
    tmp_path: Path, sealed_world: tuple[Any, dict], *, taker_bps: float, name: str
) -> EvaluationContext:
    mount, closes = sealed_world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=taker_bps, maker_bps=taker_bps)
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
    )


@pytest.fixture
def context(tmp_path: Path, sealed_world: tuple[Any, dict]) -> EvaluationContext:
    return _build_context(
        tmp_path, sealed_world, taker_bps=TAKER_BPS, name="configured-fee"
    )


@pytest.fixture
def zero_fee_context(tmp_path: Path, sealed_world: tuple[Any, dict]) -> EvaluationContext:
    return _build_context(tmp_path, sealed_world, taker_bps=0.0, name="zero-fee")


def _ledger_for(context: EvaluationContext) -> TrialLedger:
    return TrialLedger(context.database_url)


def _new_node(context: EvaluationContext) -> str:
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    return node_id


def _evaluate(context: EvaluationContext) -> NodeEvaluation:
    node_id = _new_node(context)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    ledger = _ledger_for(context)
    return evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )


# -- The reproduction: the same node, the configured fee vs. 0 bps --------------


def test_configured_fee_and_zero_fee_no_longer_give_identical_figures(
    context: EvaluationContext, zero_fee_context: EvaluationContext
) -> None:
    configured = _evaluate(context)
    zero_fee = _evaluate(zero_fee_context)

    assert configured.fail_class is None
    assert zero_fee.fail_class is None

    # Before bug 2's fix, compute_node_metrics never saw a cost, so these
    # two evaluations of the identical signal over the identical world
    # measured identical ir_tstat and cost_adjusted_ir regardless of the
    # fee schedule. They must now differ, and the configured fee's own
    # reading must be the lower one — turnover can only cost a book, never
    # pay it.
    assert configured.score.ir_tstat != pytest.approx(zero_fee.score.ir_tstat)
    assert configured.score.ir_tstat < zero_fee.score.ir_tstat
    assert configured.score.cost_adjusted_ir < zero_fee.score.cost_adjusted_ir


# -- The diagnostic: evaluate_node's own answer carries the gross figure -------


def test_ir_tstat_is_below_ir_tstat_gross_for_a_turnover_bearing_signal(
    context: EvaluationContext,
) -> None:
    answer = _evaluate(context)

    assert answer.fail_class is None
    assert answer.metrics is not None
    assert answer.ir_tstat_gross is not None
    # answer.score.ir_tstat is metrics.ir_standalone * sqrt(dates) over the
    # fee-costed book (test_post_cost_tstat.py's own claim); the gross
    # figure is the same formula with no turnover charge, so it is always
    # the larger of the two for a book that actually traded.
    assert answer.score.ir_tstat < answer.ir_tstat_gross


# -- A 0 bps schedule gives equal figures ---------------------------------------


def test_zero_fee_schedule_gives_equal_net_and_gross_ir_tstat(
    zero_fee_context: EvaluationContext,
) -> None:
    answer = _evaluate(zero_fee_context)

    assert answer.fail_class is None
    assert answer.ir_tstat_gross is not None
    assert answer.score.ir_tstat == pytest.approx(answer.ir_tstat_gross)


# -- evaluate_on_dates' result is net and carries the gross figure --------------


def test_evaluate_on_dates_result_is_net_and_carries_the_gross_figure(
    context: EvaluationContext,
) -> None:
    node_id = _new_node(context)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    result = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        dates=EVALUATION_DATES,
    )

    # The existing two-element contract closeout.py and _financial_eval.py
    # both destructure survives: unpacking still answers exactly two names.
    metrics, cost_adjusted_ir = result
    assert isinstance(cost_adjusted_ir, float)
    net_ir_tstat = metrics.ir_standalone * math.sqrt(metrics.dates)

    # The diagnostic rides beside the tuple as an attribute, never a third
    # unpacked element.
    assert result.ir_tstat_gross is not None
    assert net_ir_tstat < result.ir_tstat_gross
