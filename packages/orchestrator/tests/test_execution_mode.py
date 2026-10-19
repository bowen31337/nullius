"""The evaluation config's execution mode — "taker" (default) or "maker".

additions_spec: *System lets the evaluation config choose execution "taker"
(today's default) or "maker", where maker charges the venue's maker fee plus
the cost model's passive queue-position penalty on every unit traded, so
that a signal is priced at the fee it would pay when executed passively,
with its adverse-selection cost stated rather than ignored ... and a maker
config whose cost model has no passive fill model is refused at load with
an error message naming the document.*

Two halves, two scaffolds:

* **the config key** (``orchestrator._context.load_evaluation_context``) —
  a small one-symbol sealed world, exercised the way ``test_context.py``'s
  own ``live`` fixture is: the key defaults to ``"taker"``, a third
  spelling is refused, and a ``"maker"`` configuration whose cost model
  resolves no passive fill model is refused at load, naming the cost
  model's own document.

* **the two cost seams** (``orchestrator._evaluate._turnover_fee_from_context``
  and ``_cost_schedule_from_context``) — ``test_evaluate_turnover_cost.py``'s
  own sealed-world recipe, over the real shipped ``binance_usdm.yaml``
  document (taker 5 bps, maker 2 bps, passive queue-position penalty 1.5
  bps): under ``"taker"`` both seams quote exactly the taker fraction,
  unchanged from every evaluation before this key existed; under
  ``"maker"`` both quote the maker fraction plus the passive penalty
  fraction (``0.0002 + 0.00015 == 0.00035``), and a full node evaluation's
  ``book_returns`` move, date by date, by exactly that fee difference times
  the date's own traded notional (``turnover_series``) — the same formula
  ``evaluator.compute_node_metrics`` already charges turnover through.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Runs under pytest-xdist: every
fixture builds a fresh temporary database over its own sealed world, with
no shared module-level mutable state across tests.
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

import cost_model
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import MAKER, TAKER, CostModelService, FeeSchedule
from evaluator import CostRequest
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import (
    EXECUTION_KEY,
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from orchestrator._evaluate import (
    _cost_schedule_from_context,
    _turnover_fee_from_context,
    evaluate_node,
)
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

CODE_WORD = "evaluation_config"
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

USDM_PATH = Path(cost_model.__file__).with_name("binance_usdm.yaml")
#: binance_usdm.yaml's own rates: taker 5 bps, maker 2 bps, passive penalty
#: 1.5 bps — see packages/cost-model/src/cost_model/binance_usdm.yaml.
USDM_TAKER_FRACTION = 0.0005
USDM_MAKER_FRACTION = 0.0002
USDM_PASSIVE_PENALTY_FRACTION = 0.00015
USDM_MAKER_TOTAL_FRACTION = USDM_MAKER_FRACTION + USDM_PASSIVE_PENALTY_FRACTION


# ===========================================================================
# Part A — the config key, through load_evaluation_context
# ===========================================================================


class LiveWorld:
    """A loadable live-evaluation environment — the smallest shape
    ``load_evaluation_context`` accepts, the same scale-down
    ``test_live_evaluator_component.py``'s own ``LiveWorld`` takes of
    ``test_context.py``'s recipe.  This suite never evaluates a node
    through it; its only job is a document that loads.
    """

    def __init__(
        self, environment: Mapping[str, str], document: Mapping[str, Any], tmp_path: Path
    ) -> None:
        self.environment = dict(environment)
        self.document = dict(document)
        self.tmp_path = tmp_path


SYMBOLS = ("SYM00",)
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(8))
LOOKBACK = 4
EVALUATION_DAYS = tuple(day.isoformat() for day in BAR_DAYS[LOOKBACK : LOOKBACK + 2])
HORIZON = 1
SEED = 20261019
EPOCH = "epoch-2026-10-19-execution-mode"
ARTIFACT_DIR_NAME = "artifacts"
IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32

#: A cost model document (§6.2's shape) with its own fee rates and *no*
#: ``fill_model`` section at all — a venue whose schedule prices both fee
#: sides but carries no passive fill model, the same shape a "maker"
#: configuration must refuse to load against.
NO_PASSIVE_VENUE = "testnet_execution_mode_no_passive"
NO_PASSIVE_TAKER_BPS = 12.5
NO_PASSIVE_MAKER_BPS = 8.0


def _close(day_index: int) -> float:
    return round(100.0 + 0.25 * day_index, 2)


def _stage_and_seal(lake_root: Path) -> Any:
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol in SYMBOLS:
        for offset, day in enumerate(BAR_DAYS):
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
                        "close": [str(_close(offset))],
                        "volume": ["1.0"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LiveWorld:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sealed = _stage_and_seal(tmp_path / "lake")

    cost_model_path = tmp_path / "cost_model_no_passive.yaml"
    cost_model_path.write_text(
        "cost_model:\n"
        '  version: "2026.10.19"\n'
        f"  venue: {NO_PASSIVE_VENUE}\n"
        "  fees:\n"
        f"    taker_bps: {NO_PASSIVE_TAKER_BPS}\n"
        f"    maker_bps: {NO_PASSIVE_MAKER_BPS}\n",
        encoding="utf-8",
    )

    document = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(EVALUATION_DAYS),
        "horizon": HORIZON,
        "seed": SEED,
        "epoch_id": EPOCH,
        "artifact_dir": str(tmp_path / ARTIFACT_DIR_NAME),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    config_path = tmp_path / "evaluation.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")

    bare_path = tmp_path / "bare-path"
    bare_path.mkdir()
    bwrap = bare_path / "bwrap"
    bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)

    database_url = f"sqlite:///{tmp_path / 'execution-mode-test.db'}"
    environment = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": database_url,
        "NULLIUS_EVALUATOR_IMAGE": IMAGE,
        "NULLIUS_COST_MODEL_PATH": str(cost_model_path),
        "PATH": str(bare_path),
    }
    return LiveWorld(environment, document, tmp_path)


def _set_document(live: LiveWorld, **overrides: Any) -> None:
    """Rewrite ``live``'s configuration document with the overrides applied.

    A value of ``None`` under :data:`EXECUTION_KEY` removes the key — the
    same "absent means the default" state every other test leaves it in.
    """
    document = dict(live.document)
    for key, value in overrides.items():
        if value is None:
            document.pop(key, None)
        else:
            document[key] = value
    config_path = Path(live.environment["NULLIUS_EVALUATION_CONFIG"])
    config_path.write_text(json.dumps(document), encoding="utf-8")


def _set_environment(live: LiveWorld, **overrides: str) -> dict[str, str]:
    environment = dict(live.environment)
    environment.update(overrides)
    return environment


def test_the_key_is_absent_and_execution_defaults_to_taker(live: LiveWorld) -> None:
    assert EXECUTION_KEY not in live.document
    context = load_evaluation_context(live.environment)
    assert context is not None
    assert context.execution == TAKER


def test_an_explicit_taker_is_honoured(live: LiveWorld) -> None:
    _set_document(live, execution="taker")
    context = load_evaluation_context(live.environment)
    assert context is not None
    assert context.execution == TAKER


def test_a_third_spelling_is_refused(live: LiveWorld) -> None:
    _set_document(live, execution="limit")
    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(live.environment)
    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:")
    assert EXECUTION_KEY in message
    assert "'taker'" in message and "'maker'" in message


def test_a_non_string_value_is_refused(live: LiveWorld) -> None:
    _set_document(live, execution=7)
    with pytest.raises(EvaluationConfigError):
        load_evaluation_context(live.environment)


def test_maker_with_no_passive_fill_model_is_refused_naming_the_document(
    live: LiveWorld,
) -> None:
    _set_document(live, execution="maker")
    cost_model_path = live.environment["NULLIUS_COST_MODEL_PATH"]
    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(live.environment)
    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:")
    assert EXECUTION_KEY in message
    assert cost_model_path in message


def test_maker_with_a_passive_fill_model_loads(live: LiveWorld) -> None:
    _set_document(live, execution="maker")
    environment = _set_environment(live, NULLIUS_COST_MODEL_PATH=str(USDM_PATH))
    context = load_evaluation_context(environment)
    assert context is not None
    assert context.execution == MAKER
    assert context.cost_schedule.passive_penalty_fraction is not None


def test_execution_is_an_unknown_key_elsewhere_is_still_refused(
    live: LiveWorld,
) -> None:
    # The closed-vocabulary refusal (_refuse_unknown_keys) still names any
    # key this loader does not define — execution's own addition to that
    # allowlist must not have widened it to accept an unrelated typo.
    _set_document(live, exceution="taker")
    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(live.environment)
    assert "'exceution'" in str(record.value)


# ===========================================================================
# Part B — the two cost seams, over the real binance_usdm.yaml document
# ===========================================================================


SEAM_SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
SEAM_FIRST_DAY = dt.date(2026, 9, 1)
SEAM_BAR_DAYS = tuple(
    SEAM_FIRST_DAY + dt.timedelta(days=offset) for offset in range(71)
)
SEAM_LOOKBACK = 10
SEAM_EVALUATION_DATES = SEAM_BAR_DAYS[SEAM_LOOKBACK : SEAM_LOOKBACK + 60]
SEAM_WORLD_SEED = 20261019
SEAM_AUTOCORRELATION = 0.5
SEAM_HORIZON = 1
SEAM_EPOCH_ID = "epoch-2026-10-19-execution-mode-seams"
SEAM_EVALUATOR_HASH = "ab" * 32
SEAM_SNAPSHOT_HASH_FALLBACK = "cd" * 32
SEAM_COST_MODEL_HASH = "ef" * 32
SEAM_CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeef"

#: test_evaluate_turnover_cost.py's own momentum signal, which re-ranks
#: symbols by trailing return every rebalance date, so its book's weights
#: (and therefore its turnover) move date to date and are never zero.
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
        if len(series) < {SEAM_LOOKBACK}:
            momentum[symbol] = 0.0
        else:
            first = float(series[-{SEAM_LOOKBACK}]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_execution_mode_{revision}", path
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


def _seal_the_seam_world(
    workdir: Path,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(SEAM_WORLD_SEED)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol in SEAM_SYMBOLS:
        price = 100.0 + generator.uniform(-20.0, 20.0)
        previous_return = 0.0
        path: dict[dt.date, float] = {}
        for day in SEAM_BAR_DAYS:
            shock = generator.gauss(0.0, 0.02)
            return_ = (
                SEAM_AUTOCORRELATION * previous_return
                + (1.0 - SEAM_AUTOCORRELATION) * shock
            )
            price = max(1.0, price * (1.0 + return_))
            path[day] = round(price, 2)
            previous_return = return_
        closes[symbol] = path

    for symbol in SEAM_SYMBOLS:
        for day in SEAM_BAR_DAYS:
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
def seam_world(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    workdir = tmp_path_factory.mktemp("execution-mode-seams-world")
    return _seal_the_seam_world(workdir)


def _usdm_service(tmp_path: Path, name: str) -> CostModelService:
    return CostModelService(
        config_path=str(USDM_PATH), database_url=f"sqlite:///{tmp_path / name}.db"
    )


def _build_seam_context(
    tmp_path: Path,
    seam_world: tuple[Any, dict[str, dict[dt.date, float]]],
    *,
    execution: str | None,
    name: str,
) -> EvaluationContext:
    mount, closes = seam_world
    service = _usdm_service(tmp_path, name)
    cost_model_config = service.config
    cost_schedule = service.fees()
    database_url = f"sqlite:///{tmp_path / name}-tree.db"
    _migrate_tree(database_url)
    kwargs: dict[str, Any] = {
        "snapshot": mount,
        "closes": closes,
        "cost_model": cost_model_config,
        "cost_schedule": cost_schedule,
        "evaluator_hash": SEAM_EVALUATOR_HASH,
        "snapshot_hash": SEAM_SNAPSHOT_HASH_FALLBACK,
        "cost_model_hash": SEAM_COST_MODEL_HASH,
        "epoch_id": SEAM_EPOCH_ID,
        "database_url": database_url,
        "artifact_dir": tmp_path / f"artifacts-{name}",
        "seed": SEAM_WORLD_SEED,
        "horizon": SEAM_HORIZON,
        "evaluation_dates": SEAM_EVALUATION_DATES,
        "sandbox_runtime": "unisolated",
    }
    if execution is not None:
        kwargs["execution"] = execution
    return EvaluationContext(**kwargs)


@pytest.fixture
def taker_context(
    tmp_path: Path, seam_world: tuple[Any, dict[str, dict[dt.date, float]]]
) -> EvaluationContext:
    return _build_seam_context(tmp_path, seam_world, execution="taker", name="taker")


@pytest.fixture
def default_context(
    tmp_path: Path, seam_world: tuple[Any, dict[str, dict[dt.date, float]]]
) -> EvaluationContext:
    # No execution= passed at all: EvaluationContext's own default
    # (DEFAULT_EXECUTION == TAKER) is what every pre-existing call site
    # that never heard of this key still gets.
    return _build_seam_context(tmp_path, seam_world, execution=None, name="default")


@pytest.fixture
def maker_context(
    tmp_path: Path, seam_world: tuple[Any, dict[str, dict[dt.date, float]]]
) -> EvaluationContext:
    return _build_seam_context(tmp_path, seam_world, execution="maker", name="maker")


@pytest.fixture
def zero_fee_context(
    tmp_path: Path, seam_world: tuple[Any, dict[str, dict[dt.date, float]]]
) -> EvaluationContext:
    """The same world and signal, at a 0 bps schedule on both sides.

    ``compute_node_metrics`` skips its whole turnover-charge block when
    ``cost_per_unit_traded == 0.0`` (see ``evaluator._metrics``), so this
    context's own ``book_returns`` are the *pre-cost* book returns for every
    date — the ground truth :func:`test_book_returns_move_by_the_fee_difference_times_traded_notional`
    recovers each date's traded notional from, the same way
    ``test_evaluate_turnover_cost.py``'s own ``zero_fee_context`` is the
    reference a configured-fee reading is compared against.
    """
    mount, closes = seam_world
    service = _usdm_service(tmp_path, "zero-fee")
    cost_model_config = service.config
    schedule = FeeSchedule(
        venue=cost_model_config.venue, taker_bps=0.0, maker_bps=0.0
    )
    database_url = f"sqlite:///{tmp_path / 'zero-fee-tree.db'}"
    _migrate_tree(database_url)
    return EvaluationContext(
        snapshot=mount,
        closes=closes,
        cost_model=cost_model_config,
        cost_schedule=schedule,
        evaluator_hash=SEAM_EVALUATOR_HASH,
        snapshot_hash=SEAM_SNAPSHOT_HASH_FALLBACK,
        cost_model_hash=SEAM_COST_MODEL_HASH,
        epoch_id=SEAM_EPOCH_ID,
        database_url=database_url,
        artifact_dir=tmp_path / "artifacts-zero-fee",
        seed=SEAM_WORLD_SEED,
        horizon=SEAM_HORIZON,
        evaluation_dates=SEAM_EVALUATION_DATES,
        sandbox_runtime="unisolated",
    )


def _evaluate(context: EvaluationContext, campaign_id: str = SEAM_CAMPAIGN_ID) -> Any:
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=campaign_id)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    ledger = TrialLedger(context.database_url)
    return evaluate_node(
        node_id,
        campaign_id,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )


# -- Both seams quote exactly the taker fraction, unchanged -------------------


def test_taker_fee_per_unit_is_the_schedule_s_own_taker_fraction(
    taker_context: EvaluationContext,
) -> None:
    assert _turnover_fee_from_context(taker_context) == pytest.approx(
        USDM_TAKER_FRACTION
    )


def test_taker_cost_schedule_quotes_the_taker_fraction(
    taker_context: EvaluationContext,
) -> None:
    charges = _cost_schedule_from_context(taker_context)
    request = _build_request({SEAM_FIRST_DAY: {"AAA": 0.0, "BBB": 0.0}})
    quote = charges(request)
    for symbol_costs in quote.costs.values():
        for cost in symbol_costs.values():
            assert cost == pytest.approx(USDM_TAKER_FRACTION)


def test_the_default_context_matches_explicit_taker_to_1e_minus_12(
    default_context: EvaluationContext, taker_context: EvaluationContext
) -> None:
    assert default_context.execution == TAKER
    assert _turnover_fee_from_context(default_context) == pytest.approx(
        _turnover_fee_from_context(taker_context), abs=1e-12
    )

    default_answer = _evaluate(default_context)
    taker_answer = _evaluate(taker_context)
    assert default_answer.fail_class is None
    assert taker_answer.fail_class is None
    assert default_answer.score.ir_tstat == pytest.approx(
        taker_answer.score.ir_tstat, abs=1e-12
    )
    assert default_answer.score.cost_adjusted_ir == pytest.approx(
        taker_answer.score.cost_adjusted_ir, abs=1e-12
    )
    for day, value in default_answer.metrics.book_returns.items():
        assert value == pytest.approx(
            taker_answer.metrics.book_returns[day], abs=1e-12
        )


# -- Maker quotes the maker fraction plus the passive penalty -----------------


def test_maker_fee_per_unit_is_maker_plus_passive_penalty(
    maker_context: EvaluationContext,
) -> None:
    assert maker_context.cost_schedule.passive_penalty_fraction == pytest.approx(
        USDM_PASSIVE_PENALTY_FRACTION
    )
    assert _turnover_fee_from_context(maker_context) == pytest.approx(
        USDM_MAKER_TOTAL_FRACTION
    )
    assert _turnover_fee_from_context(maker_context) == pytest.approx(0.00035)


def test_maker_cost_schedule_quotes_maker_plus_passive_penalty(
    maker_context: EvaluationContext,
) -> None:
    charges = _cost_schedule_from_context(maker_context)
    request = _build_request({SEAM_FIRST_DAY: {"AAA": 0.0, "BBB": 0.0}})
    quote = charges(request)
    for symbol_costs in quote.costs.values():
        for cost in symbol_costs.values():
            assert cost == pytest.approx(0.00035)


# -- A full node evaluation: book_returns move by exactly the fee delta -------


def test_book_returns_move_by_the_fee_difference_times_traded_notional(
    zero_fee_context: EvaluationContext,
    taker_context: EvaluationContext,
    maker_context: EvaluationContext,
) -> None:
    zero_answer = _evaluate(zero_fee_context)
    taker_answer = _evaluate(taker_context)
    maker_answer = _evaluate(maker_context)
    assert zero_answer.fail_class is None
    assert taker_answer.fail_class is None
    assert maker_answer.fail_class is None

    fee_delta = USDM_MAKER_TOTAL_FRACTION - USDM_TAKER_FRACTION
    zero_returns = zero_answer.metrics.book_returns
    taker_returns = taker_answer.metrics.book_returns
    maker_returns = maker_answer.metrics.book_returns
    assert set(zero_returns) == set(taker_returns) == set(maker_returns)

    # evaluator.compute_node_metrics skips its whole cost_per_unit_traded
    # block at a 0.0 rate, so zero_returns[day] is the pre-cost book return
    # for that date — the ground truth each date's own traded notional
    # ("traded" in evaluator._metrics's own formula,
    # per_date_return[day] -= cost_per_unit_traded * traded) is recovered
    # from, rather than re-derived from evaluator._metrics's own
    # turnover_series (which halves it and excludes the first date's entry
    # cost, a different figure from the one actually charged).
    saw_nonzero_turnover = False
    for day, raw_return in zero_returns.items():
        traded = (raw_return - taker_returns[day]) / USDM_TAKER_FRACTION
        assert maker_returns[day] - taker_returns[day] == pytest.approx(
            -fee_delta * traded, abs=1e-9
        )
        if traded > 1e-9:
            saw_nonzero_turnover = True
    assert saw_nonzero_turnover


def _build_request(gross_returns: Mapping[dt.date, Mapping[str, float]]) -> CostRequest:
    symbols = tuple(sorted({symbol for row in gross_returns.values() for symbol in row}))
    dates = sorted(gross_returns)
    return CostRequest(
        node_id="execution-mode-test-node",
        venue="binance_usdm",
        version="2026.10.1",
        horizon=SEAM_HORIZON,
        symbols=symbols,
        date_range=(dates[0], dates[-1]),
        gross_returns=gross_returns,
    )
