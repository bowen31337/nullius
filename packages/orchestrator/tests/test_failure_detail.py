"""bug_spec_pipeline_cross_section.xml, bug (C) — failure detail, carried.

``orchestrator._evaluate``'s catch-all recorded ``fail_class=type(exc).__name__``
and nothing else: ``str(exc)`` — the one thing that actually says *why* a
cost mismatch, a gate refusal or a normalize refusal fired — was discarded
the moment it was caught, never persisted, logged or emitted.
``orchestrator._campaign``'s ``node_evaluated`` event carried ``fail_class``
alone for the same reason. Diagnosing a smoke campaign's own failures needed
replaying each root against a copy of the store with a monkeypatched hook.

The fix: :class:`~orchestrator._evaluate.NodeEvaluation` carries
``fail_detail`` — ``str(exc)`` truncated to 2,000 characters — on every
failure path, one ``WARNING`` line names the node id and the class, and
``orchestrator._campaign._evaluated_event`` emits ``fail_detail`` beside
``fail_class``. ``fail_class`` itself is unchanged. The message is never
about a node's null status: this module reads no null bit anywhere in its
body (restated by the symmetry test below — a "null" and a "real" node
failing identically produce identical detail text, modulo their own node
id).

One test per pipeline stage this bug's companion fixes touch — a cost
failure (bug A), a gate failure (the oracle's own refusal, unrelated to
either companion fix) and a normalize failure (bug B) — plus truncation and
the null/real indistinguishability the spec names explicitly.

No test opens a network connection or writes outside a pytest temporary
directory, and none shares mutable state across tests, so the suite is safe
under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import FeeSchedule, load_cost_model
from evaluator import RawScoreVector, SignalExecution
from ledger import TrialLedger
from nulloracle.target import NOT_FOUND, OK, TargetResponse
from orchestrator._campaign import _evaluated_event
from orchestrator._context import EvaluationContext
from orchestrator._oracle import SubtreeOracle

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

_UNIVERSE = ("AAA", "BBB")
_DAYS = tuple(dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(10))


def _varying_execution(days: tuple[dt.date, ...] = _DAYS) -> SignalExecution:
    """A dense execution whose per-date scores vary — never thin, never flat
    — so every test below fails downstream of the scores loop, at the stage
    under test.
    """
    vectors = {
        day: RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(day, dt.time(tzinfo=dt.UTC)),
            universe=_UNIVERSE,
            seed=7,
            contract_version="0.1.0",
            scores=pl.Series([float(index + 1), -float(index + 1)], dtype=pl.Float64),
            problems=[],
        )
        for index, day in enumerate(days)
    }
    return SignalExecution(
        snapshot_name="snap_failure_detail_test", code_hash="ab" * 32, seed=7, vectors=vectors
    )


def _constant_execution(days: tuple[dt.date, ...] = _DAYS) -> SignalExecution:
    """Every date identical — bug B's own no-preference refusal, on every date."""
    vectors = {
        day: RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(day, dt.time(tzinfo=dt.UTC)),
            universe=_UNIVERSE,
            seed=7,
            contract_version="0.1.0",
            scores=pl.Series([1.0, 1.0], dtype=pl.Float64),
            problems=[],
        )
        for day in days
    }
    return SignalExecution(
        snapshot_name="snap_failure_detail_test", code_hash="ab" * 32, seed=7, vectors=vectors
    )


# -- Migrations and raw-SQL planting, test_evaluate.py's own recipe ------------


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_failure_detail_test_{revision}", path
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


EPOCH_ID = "epoch-2026-10-07-failure-detail"
EVALUATOR_HASH = "aa" * 32
SNAPSHOT_HASH_FALLBACK = "bb" * 32
COST_MODEL_HASH = "cc" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeefc"
WORLD_SEED = 24680


def _seal_minimal_world(workdir: Path, bar_days: tuple[dt.date, ...]) -> Any:
    from snapshot import SnapshotService

    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    for symbol_index, symbol in enumerate(_UNIVERSE):
        for day_index, day in enumerate(bar_days):
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            price = 100.0 + symbol_index * 10.0 + day_index * 0.1
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ],
                        "close": [f"{price:.2f}"],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service.mount(sealed.name)


@pytest.fixture(scope="module")
def mount(tmp_path_factory: pytest.TempPathFactory) -> Any:
    workdir = tmp_path_factory.mktemp("failure-detail-world")
    return _seal_minimal_world(workdir, _DAYS)


def _closes_for(bar_days: tuple[dt.date, ...]) -> dict[str, dict[dt.date, float]]:
    return {
        symbol: {
            day: 100.0 + index * 10.0 + day_index * 0.1
            for day_index, day in enumerate(bar_days)
        }
        for index, symbol in enumerate(_UNIVERSE)
    }


@pytest.fixture
def context(tmp_path: Path, mount: Any) -> EvaluationContext:
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'failure-detail.db'}"
    _migrate_tree(database_url)
    return EvaluationContext(
        snapshot=mount,
        closes=_closes_for(_DAYS),
        cost_model=config,
        cost_schedule=schedule,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH_FALLBACK,
        cost_model_hash=COST_MODEL_HASH,
        epoch_id=EPOCH_ID,
        database_url=database_url,
        artifact_dir=tmp_path / "artifacts",
        seed=WORLD_SEED,
        horizon=1,
        evaluation_dates=_DAYS[:-1],
        sandbox_runtime="unisolated",
    )


class DenseEndpoint:
    """A real-branch stand-in whose answer never matters: every test here
    fails before ``compute_node_metrics`` is ever reached, so the series'
    own values carry no claim under test.
    """

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def post(self, request: Any) -> TargetResponse:
        self.requests.append(request)
        first, last = request.date_range
        series: dict[dt.date, dict[str, float]] = {}
        day = first
        while day <= last:
            series[day] = {symbol: 0.001 for symbol in request.symbols}
            day += dt.timedelta(days=1)
        return TargetResponse(
            status=OK, node_id=request.node_id, target_series=series, charges_budget=True
        )


class RefusingEndpoint:
    """Always answers 404 — the gate's own refusal, ``OracleTargetError``."""

    def post(self, request: Any) -> TargetResponse:
        return TargetResponse(
            status=NOT_FOUND,
            node_id=request.node_id,
            detail="no sealed assignment for this subtree",
        )


class RaisingEndpoint:
    """Raises an arbitrary exception directly from ``post`` — the seam's own
    failure, propagated unwrapped (the same stance a cost schedule that
    raises gets, per ``evaluator._costs``' own docstring).
    """

    def __init__(self, message: str) -> None:
        self._message = message

    def post(self, request: Any) -> TargetResponse:
        raise RuntimeError(self._message)


def _evaluate_with(
    monkeypatch: pytest.MonkeyPatch,
    context: EvaluationContext,
    execution: SignalExecution,
    endpoint: Any,
    *,
    node_id: str | None = None,
) -> Any:
    import orchestrator._evaluate as evaluate_module

    monkeypatch.setattr(evaluate_module, "execute_signal", lambda *a, **k: execution)

    node_id = node_id or str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    ledger = TrialLedger(context.database_url)

    return evaluate_module.evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        "def signal(ctx, seed):\n    return None\n",
        context=context,
        oracle=oracle,
        ledger=ledger,
    )


# -- A cost failure (bug A's own stage) ----------------------------------------


def test_a_cost_failure_carries_its_message_in_the_row_and_the_event(
    monkeypatch: pytest.MonkeyPatch, context: EvaluationContext
) -> None:
    # A cost model missing its version half: apply_costs' own cost_model_ref
    # refuses before any schedule is asked.
    broken = EvaluationContext(
        snapshot=context.snapshot,
        closes=context.closes,
        cost_model={"venue": "binance_spot"},
        cost_schedule=context.cost_schedule,
        evaluator_hash=context.evaluator_hash,
        snapshot_hash=context.snapshot_hash,
        cost_model_hash=context.cost_model_hash,
        epoch_id=context.epoch_id,
        database_url=context.database_url,
        artifact_dir=context.artifact_dir,
        seed=context.seed,
        horizon=context.horizon,
        evaluation_dates=context.evaluation_dates,
        sandbox_runtime=context.sandbox_runtime,
    )

    answer = _evaluate_with(monkeypatch, broken, _varying_execution(), DenseEndpoint())

    assert answer.fail_class == "EvaluatorCostError"
    assert answer.fail_detail is not None
    assert "venue, version" in answer.fail_detail

    event = _evaluated_event(
        CAMPAIGN_ID,
        answer.node_id,
        0,
        fail_class=answer.fail_class,
        score=answer.score,
        charges_budget=answer.charges_budget,
        fail_detail=answer.fail_detail,
    )
    assert event["fail_detail"] == answer.fail_detail


# -- A gate failure (the oracle's own refusal) ---------------------------------


def test_a_gate_failure_carries_its_message_in_the_row_and_the_event(
    monkeypatch: pytest.MonkeyPatch, context: EvaluationContext
) -> None:
    answer = _evaluate_with(
        monkeypatch, context, _varying_execution(), RefusingEndpoint()
    )

    assert answer.fail_class == "OracleTargetError"
    assert answer.fail_detail is not None
    assert "no sealed assignment" in answer.fail_detail
    assert answer.node_id in answer.fail_detail

    event = _evaluated_event(
        CAMPAIGN_ID,
        answer.node_id,
        0,
        fail_class=answer.fail_class,
        score=answer.score,
        charges_budget=answer.charges_budget,
        fail_detail=answer.fail_detail,
    )
    assert event["fail_detail"] == answer.fail_detail


# -- A normalize failure (bug B's own stage) ------------------------------------


def test_a_normalize_failure_carries_its_message_in_the_row_and_the_event(
    monkeypatch: pytest.MonkeyPatch, context: EvaluationContext
) -> None:
    endpoint = DenseEndpoint()
    answer = _evaluate_with(monkeypatch, context, _constant_execution(), endpoint)

    assert answer.fail_class == "EvaluatorNormalizeError"
    assert answer.fail_detail is not None
    assert "no preference" in answer.fail_detail
    # The failure happened before the scores ever reached the gate.
    assert endpoint.requests == []

    event = _evaluated_event(
        CAMPAIGN_ID,
        answer.node_id,
        0,
        fail_class=answer.fail_class,
        score=answer.score,
        charges_budget=answer.charges_budget,
        fail_detail=answer.fail_detail,
    )
    assert event["fail_detail"] == answer.fail_detail


# -- fail_class is unchanged; fail_detail defaults to None ---------------------


def test_evaluated_event_defaults_fail_detail_to_none() -> None:
    event = _evaluated_event(
        CAMPAIGN_ID, "node-x", 0, fail_class=None, score=None, charges_budget=True
    )
    assert event["fail_detail"] is None
    assert event["fail_class"] is None


# -- Truncation -----------------------------------------------------------------


def test_fail_detail_is_truncated_to_two_thousand_characters(
    monkeypatch: pytest.MonkeyPatch, context: EvaluationContext
) -> None:
    long_message = "x" * 3_000
    answer = _evaluate_with(
        monkeypatch,
        context,
        _varying_execution(),
        RaisingEndpoint(long_message),
    )

    assert answer.fail_class == "RuntimeError"
    assert answer.fail_detail is not None
    assert len(answer.fail_detail) == 2_000
    assert answer.fail_detail == "x" * 2_000


# -- A null and a real node failing the same way are indistinguishable --------


def test_a_null_and_a_real_node_failing_the_same_way_differ_only_in_node_id(
    monkeypatch: pytest.MonkeyPatch, context: EvaluationContext
) -> None:
    # Neither node is actually null or real — this module reads no node's
    # null status anywhere in its body, which is exactly the property this
    # test holds: two different node ids, refused the identical way (the
    # gate's own OracleTargetError, which names the node id twice in its
    # message), must differ in their fail_detail text only where their own
    # id appears.
    node_a = str(uuid.uuid4())
    node_b = str(uuid.uuid4())

    answer_a = _evaluate_with(
        monkeypatch, context, _varying_execution(), RefusingEndpoint(), node_id=node_a
    )
    answer_b = _evaluate_with(
        monkeypatch, context, _varying_execution(), RefusingEndpoint(), node_id=node_b
    )

    assert answer_a.fail_class == answer_b.fail_class == "OracleTargetError"
    normalized_a = answer_a.fail_detail.replace(node_a, "<node>")
    normalized_b = answer_b.fail_detail.replace(node_b, "<node>")
    assert normalized_a == normalized_b
