"""bug_spec_evaluation_throughput.xml / additions_spec_process_pool_evaluation:
a campaign's nodes evaluate in worker processes, not one GIL.

``orchestrator._process_pool.ProcessEvaluator`` is the same ``.evaluate(node_id,
campaign_id, depth, code) -> NodeEvaluation`` shape as ``orchestrator.LiveEvaluator``,
but every call is dispatched to a real OS worker process instead of running on
the calling thread's own interpreter.  This suite drives it the only way that
actually proves the claim: a real ``orchestrator._campaign.run_campaign`` over a
real sealed snapshot, a real nulloracle sidecar (``hex:`` key, no KMS/sops), a
real tree and a real trial ledger — with the one thing that would otherwise
make this suite slow or flaky replaced by a stub: the *signal executor*
(``orchestrator._context.signal_sandbox``'s own test-only
``TEST_STUB_SANDBOX_ENV`` hook), so no gVisor or bwrap process is ever actually
spawned to run agent code.

**Why the sandbox itself, and not a higher seam, is what gets stubbed.**  A
higher stub (the whole ``evaluator`` object, the way ``test_concurrent_evaluation.py``
stubs it for the thread-pool bug) would never exercise
``evaluate_node``'s own pipeline at all — no ``NodeMetrics`` would ever be
built, so this suite would prove nothing about whether a ``NodeMetrics`` built
in a worker process actually survives the trip back through ``pickle``.  And a
stub one level lower (real code run through a real subprocess sandbox) would
prove nothing about *this* feature's reason to exist: the actual signal
execution already happens in a subprocess regardless of dispatch mode
(``HardenedSubprocessSandbox.run`` blocks on a child process, which releases
the GIL while it waits), so a thread-mode campaign already parallelizes that
part fine. What a thread pool cannot parallelize is the CPU-bound *Python*
around it — window materialization, alignment, cost netting, metrics,
tripwire probes — all of which stays on the GIL in thread mode and moves to a
real core in process mode. The stub sandbox's own ``run()`` does its
CPU-bound work directly, in the calling interpreter, with no subprocess at
all — the one shape that actually tells thread mode and process mode apart.

**Why the two runs being compared share one fixed campaign id.**
``nulloracle.TypeRSelection.persist`` draws which roots are null from the
roots the tree already holds, seeded from the campaign id alone (never from a
root's own uuid).  Two separately-run campaigns normally mint two different
campaign ids and so draw two different null/real splits, which would make a
"this root's position in both runs scored the same metrics" comparison
accidentally compare a real root's row against a null root's — a different
oracle-supplied target series entirely, not a measure of this feature.  Both
comparison tests therefore run under the identical
``discovery.create_campaign`` id (monkeypatched, the same technique
``tests/e2e/test_real_data_campaign_e2e.py`` already uses for its own fixture
replay), which pins an identical null/real split across both runs — the root
uuids themselves are left free to differ, since nothing this suite reads
depends on their literal value.

**Why the stub's scores are a function of ``(seed, decision_time, universe,
code)`` and nothing else.**  Those are the only inputs ``evaluator.execute_signal``
hands the sandbox's ``run()``, and they are identical across both runs for
"the root at position i" by construction — so the scores, and therefore every
downstream metric, are byte-identical between modes without needing a single
shared mutable or a real RNG seeded some other way.  Giving each planted root
its own distinguishing comment inside ``code`` (``# root=i``) is what lets
``ic_mean`` differ *across* roots within one run (proving the comparison
would actually catch a root/metric mismatch) while staying identical for the
*same* root across the two runs being compared.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.  Every test takes its own fresh SQLite
file and its own fresh sidecar, so the suite is safe under pytest-xdist.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib.util
import json
import os
import random
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import discovery
import ledger
import nulloracle
import providers
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from evaluator import SandboxResult
from orchestrator._campaign import run_campaign
from orchestrator._process_pool import ProcessEvaluator
from policy_runtime import UNBOUNDED_BUDGET
from snapshot import SnapshotService

from app.module_loader import create_app

# -- The world: migrations, symbols, dates --------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: Applied in ascending chain order — the campaign table, the trial ledger
#: (this suite's evaluations really charge it, unlike test_concurrent_evaluation.py's
#: stubbed evaluator), its indexes, and the node table's own five additions.
MIGRATIONS = (
    "0110_epoch_ledger",
    "0111_campaign_table",
    "0112_trial_ledger",
    "0113_node_indexes",
    "0114_node_metrics",
    "0115_agent_model_trio",
    "0116_provenance_trio",
    "0117_identity_trio",
    "0118_node_table",
)

SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
LOOKBACK = 2
EVALUATION_SPAN = 6
HORIZON = 1
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(LOOKBACK + EVALUATION_SPAN + 1))
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + EVALUATION_SPAN]
WORKSPACES = 8
WORLD_SEED = 20261009
EPOCH_ID = "epoch-process-pool-evaluation"
EVALUATOR_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32
FIXED_CAMPAIGN_ID = "9b00f00d-0000-4000-8000-00000000e2e1"

ROOT_PIN = providers.ModelPin("deepseek", "deepseek-v4-flash", "20260910")
SAMPLING = providers.AgentSampling(temperature=0.4, seed=7)
USAGE = providers.Usage(input_tokens=1_000, output_tokens=200)
ROOT_TIER = providers.FrontierTier(
    providers=(providers.FrontierProvider(ROOT_PIN.provider, ROOT_PIN.model),)
)

_METRIC_COLUMNS = (
    "ic_mean",
    "ic_tstat",
    "ir_standalone",
    "ir_marginal",
    "turnover",
    "cost_adjusted_ir",
)

#: A substring one root's ``code`` can carry to make the stub sandbox raise
#: for that root alone — "a node raising in a worker" without engineering a
#: malformed input that could just as easily crash *planting*, before
#: evaluation is even reached.
_RAISE_SENTINEL = "RAISE_IN_WORKER_SENTINEL"


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(
        f"_process_pool_evaluation_{revision}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrated_database(root: Path, label: str) -> str:
    url = f"sqlite:///{root / f'{label}.db'}"
    for revision in MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


# -- The sealed snapshot: every symbol, every day, no late listing --------------


#: Each symbol's own constant daily drift, spaced wide enough that the
#: cross-sectional rank survives most days' noise (the same calibration
#: tests/e2e/test_real_data_campaign_e2e.py's own module docstring explains:
#: a pure, noiseless drift clears compute_node_metrics' own zero-variance
#: refusal by clearing *everything* identically on every date).
_DRIFT_STEP = 0.02
_DRIFTS = {symbol: -0.03 + _DRIFT_STEP * index for index, symbol in enumerate(SYMBOLS)}
_DRIFT_NOISE_STD = 0.015


def _closes() -> dict[str, dict[dt.date, float]]:
    generator = random.Random(WORLD_SEED)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol_index, symbol in enumerate(SYMBOLS):
        price = 100.0 + 10.0 * symbol_index
        path: dict[dt.date, float] = {}
        for day in BAR_DAYS:
            drift = _DRIFTS[symbol] + generator.gauss(0.0, _DRIFT_NOISE_STD)
            price = max(1.0, price * (1.0 + drift))
            path[day] = round(price, 2)
        closes[symbol] = path
    return closes


def _seal_world(lake_root: Path) -> Any:
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    closes = _closes()
    for symbol in SYMBOLS:
        for day in BAR_DAYS:
            partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            partition.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)],
                        "close": [f"{closes[symbol][day]:.2f}"],
                        "volume": ["1.0"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    return service.seal(
        sealed_at=dt.datetime.combine(BAR_DAYS[-1], dt.time(23, 59), tzinfo=dt.UTC)
    )


# -- The stub signal executor: no subprocess, deterministic, CPU-bound ----------


def _busy_iterations(count: int) -> None:
    """Pure-Python CPU work for a *fixed iteration count* — never a
    wall-clock deadline.

    A ``while time.perf_counter() < deadline`` loop would be the wrong
    stand-in for GIL contention: every thread sharing the GIL still exits
    such a loop within about the same *wall-clock* window regardless of
    how many siblings are competing for CPU, because the loop's own exit
    test is wall-clock time, not work done — it would silently fail to
    reproduce the one thing this suite exists to show. A fixed iteration
    count has no such escape hatch: four threads splitting one core across
    the same number of iterations each take about four times as long in
    wall-clock terms, while four worker *processes* each keep a whole core
    and do not. Never releases the GIL (unlike ``time.sleep``).
    """
    total = 0
    for _ in range(count):
        total = (total * 1103515245 + 12345) & 0x7FFFFFFF


def _deterministic_values(universe: tuple[str, ...], seed: int, decision_time: Any, code: str) -> list[float]:
    """Scores that are a pure function of ``(seed, decision_time, universe,
    code)`` — identical for "the same root" across two separately-run
    campaigns sharing those four facts, different across roots and across
    rebalance dates within one run (see the module docstring).
    """
    key = f"{seed}|{decision_time.isoformat()}|{code}|{','.join(universe)}"
    rng = random.Random(key)
    return [rng.uniform(-1.0, 1.0) + 0.05 * index for index, _ in enumerate(universe)]


class _StubSandbox:
    """A signal executor with no subprocess — the module docstring's whole
    reason this suite exists. Loaded in a fresh worker process by file path
    (``orchestrator._context.signal_sandbox``'s ``TEST_STUB_SANDBOX_ENV``
    hook), so this exact class, zero-arg constructed, is what every worker
    (and, in "thread" mode, the parent interpreter itself) runs.
    """

    #: Overridden by :class:`_SlowStubSandbox` for the throughput test —
    #: every other test wants this fast, not slow. ``execute_signal`` calls
    #: ``run()`` once per rebalance date (``EVALUATION_SPAN`` dates), so
    #: this is the per-*call* cost, not the per-node one.
    ITERATIONS: int = 10_000

    def __init__(self) -> None:
        self.last_result: SandboxResult | None = None

    def run(self, code: str, window: Any, *, seed: int) -> SandboxResult:
        _busy_iterations(self.ITERATIONS)
        if _RAISE_SENTINEL in code:
            raise RuntimeError(f"stub sandbox raised for marked code: {code!r}")
        import polars as pl

        universe = tuple(window.universe)
        values = _deterministic_values(universe, seed, window.t, code)
        result = SandboxResult(
            scores=pl.Series(values, dtype=pl.Float64),
            problems=[],
            fail_class=None,
            detail="",
            seed=seed,
            contract_version="",
        )
        self.last_result = result
        return result


class _SlowStubSandbox(_StubSandbox):
    """The same stub, with enough iterations per call that a one-time
    worker startup cost (measured well under a second on this host) is a
    small fraction of the total — the throughput test's own stub.
    ``EVALUATION_SPAN`` calls per node at roughly 0.3s each (calibrated on
    this host at about 11-12M iterations/second single-threaded).
    """

    ITERATIONS = 3_500_000


_FAST_STUB_SPEC = f"{__file__}:_StubSandbox"
_SLOW_STUB_SPEC = f"{__file__}:_SlowStubSandbox"


# -- Planting: one author, code that both varies by position and can be marked --


def _root_code(position: int, *, raise_in_worker: bool = False) -> str:
    marker = _RAISE_SENTINEL if raise_in_worker else "ok"
    # The comment is never read by anything — its only job is to make two
    # roots' code strings differ, so the stub's deterministic scores differ
    # by root (see the module docstring).
    return f"def signal(ctx, seed):\n    return ctx.close  # root={position} marker={marker}\n"


class RootAuthor:
    """``author.author_root`` for planting — the one call ``run_campaign``'s
    root loop makes, ``rounds=0`` so no round-loop expansion ever asks
    ``author(workspace)``.
    """

    def __init__(self, *, raising_position: int | None = None) -> None:
        self.root_calls: list[tuple[str, str, str]] = []
        self._raising_position = raising_position

    def author_root(self, campaign_id: str, theme_root: str, *, root_id: Any) -> Any:
        position = len(self.root_calls)
        self.root_calls.append((campaign_id, theme_root, str(root_id)))
        code = _root_code(position, raise_in_worker=(position == self._raising_position))
        record = providers.AuthoringRecord(
            node_id=str(root_id),
            campaign_id=campaign_id,
            depth=0,
            role="root",
            pin=ROOT_PIN,
            sampling=SAMPLING,
            usage=USAGE,
            served_model=ROOT_PIN.model,
            tier=ROOT_TIER,
        )
        return SimpleNamespace(
            code=code,
            stated_mechanism=f"stub root {position}",
            proposal=f"Mechanism: stub root {position}.\n```python\n{code}```\n",
            record=record,
        )

    @property
    def root_ids(self) -> list[str]:
        return [call[2] for call in self.root_calls]


class EmptyBatchPolicy:
    """``policy.select`` is never asked when ``rounds=0`` — a shape the
    signature needs, never actually called.
    """

    def select(self, prefix_view: Any) -> list[str]:
        return []


#: Generous — ``WORKSPACES`` (8) is the actual need, padded so an
#: unexpected extra ``uuid.uuid4()`` call during planting still gets a
#: fixed, reproducible value in both runs being compared.
_FIXED_ROOT_UUID_COUNT = 64


def _patch_fixed_root_uuids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every ``uuid.uuid4()`` call in this process answers from one fixed,
    ascending sequence.

    ``nulloracle.selection.TypeRSelection`` reads a campaign's roots
    ``ORDER BY id`` (canonical UUID text) before drawing which are null —
    deliberately, so the draw never depends on storage-engine row order —
    which means *this* suite's own "root at planting position i" comparison
    only lines up with the real/null draw when both runs plant the
    identical set of root ids: a fresh ``uuid.uuid4()`` per run would let
    the same position draw a different null/real status in each run purely
    from UUID-string-sort happening to reorder them differently. Pinned
    once, here, rather than per test, because every run this suite compares
    needs it. ``uuid.UUID(int=i)`` is zero-padded hex, so ascending ``i`` is
    already ascending string order — "position i" and "the i-th root in the
    sort the draw reads" are the same root.
    """
    fixed = [uuid.UUID(int=index + 1) for index in range(_FIXED_ROOT_UUID_COUNT)]
    sequence = iter(fixed)
    real_uuid4 = uuid.uuid4
    monkeypatch.setattr(uuid, "uuid4", lambda: next(sequence, real_uuid4()))


def _patch_fixed_campaign_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every ``discovery.create_campaign`` call in this process plants under
    :data:`FIXED_CAMPAIGN_ID` — see the module docstring for why both runs
    being compared must share one campaign id.
    """
    original = discovery.create_campaign

    def fixed(
        campaign_type: Any,
        workspace_count: Any,
        *,
        campaign_id: Any = None,
        database_url: str | None = None,
        env: Any = None,
    ) -> Any:
        return original(
            campaign_type,
            workspace_count,
            campaign_id=FIXED_CAMPAIGN_ID,
            database_url=database_url,
            env=env,
        )

    monkeypatch.setattr(discovery, "create_campaign", fixed)


# -- The environment: a real sidecar (hex: key), a real evaluation config ------


def _fake_bwrap(root: Path) -> Path:
    bwrap_dir = root / "bwrap-bin"
    bwrap_dir.mkdir(exist_ok=True)
    bwrap = bwrap_dir / "bwrap"
    bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)
    return bwrap_dir


def _environment(
    root: Path,
    *,
    mode: str,
    database_url: str,
    snapshot_mount: str,
    stub_spec: str,
    workers: int = 4,
) -> dict[str, str]:
    document = {
        "snapshot_mount": snapshot_mount,
        "evaluation_dates": [day.isoformat() for day in EVALUATION_DATES],
        "horizon": HORIZON,
        "seed": WORLD_SEED,
        "epoch_id": EPOCH_ID,
        "artifact_dir": str(root / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
        "evaluation_workers": workers,
        "evaluation_mode": mode,
    }
    config_path = root / "evaluation-config.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    bwrap_dir = _fake_bwrap(root)
    return {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": database_url,
        "NULLIUS_EVALUATOR_IMAGE": EVALUATOR_IMAGE,
        "NULL_SIDECAR_PATH": str(root / "null" / "sidecar.enc"),
        "NULL_SIDECAR_KEY_REF": f"hex:{secrets.token_hex(32)}",
        "PATH": str(bwrap_dir),
        "NULLIUS_TEST_STUB_SANDBOX": stub_spec,
    }


def _apply_environment(monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]) -> None:
    for key, value in environment.items():
        monkeypatch.setenv(key, value)


# -- Running one campaign through the real composed application ----------------


def _run_one(
    root: Path,
    *,
    mode: str,
    label: str,
    snapshot_mount: str,
    monkeypatch: pytest.MonkeyPatch,
    stub_spec: str = _FAST_STUB_SPEC,
    workers: int = 4,
    raising_position: int | None = None,
) -> tuple[Any, list[dict[str, Any]], RootAuthor, str]:
    database_url = _migrated_database(root, label)
    environment = _environment(
        root,
        mode=mode,
        database_url=database_url,
        snapshot_mount=snapshot_mount,
        stub_spec=stub_spec,
        workers=workers,
    )
    _apply_environment(monkeypatch, environment)
    _patch_fixed_campaign_id(monkeypatch)
    _patch_fixed_root_uuids(monkeypatch)

    app = create_app()
    evaluator = app.get("live-evaluator")
    assert evaluator is not None, (
        "the real create_app() composed no live-evaluator; check "
        "NULLIUS_EVALUATION_CONFIG, DATABASE_URL and NULLIUS_EVALUATOR_IMAGE"
    )
    sidecar_selection = app.get(nulloracle.TYPE_R_COMPONENT_NAME)
    assert sidecar_selection is not None, (
        "the real create_app() composed no Type-R selection; check "
        "DATABASE_URL, NULL_SIDECAR_PATH and NULL_SIDECAR_KEY_REF"
    )

    author = RootAuthor(raising_position=raising_position)
    events: list[dict[str, Any]] = []
    try:
        result = run_campaign(
            campaign_type="Type-R",
            workspaces=WORKSPACES,
            rounds=0,
            width=1,
            allowance=UNBOUNDED_BUDGET,
            author=author,
            evaluator=evaluator,
            policy=EmptyBatchPolicy(),
            context=evaluator.context,
            sidecar_selection=sidecar_selection,
            emit=events.append,
        )
    finally:
        shutdown = getattr(evaluator, "shutdown", None)
        if callable(shutdown):
            shutdown()
    return result, events, author, database_url


# -- Reading back what a run persisted ------------------------------------------


def _root_metric_rows(database_url: str, campaign_id: str) -> list[tuple[Any, ...]]:
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            f"SELECT {', '.join(_METRIC_COLUMNS)} FROM node "
            "WHERE campaign_id = ? AND depth = 0 ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    return rows


def _ledger_row_set(database_url: str, campaign_id: str) -> set[tuple[Any, ...]]:
    """Every row's fields but its identifiers — ``seq``/``ts``/``node_id``/
    ``campaign_id`` — as a frozen, hashable tuple.  Set-equal, per the task's
    own words: two campaigns that charged the same outcomes under the same
    provenance, independent of row order or of which literal node id each
    landed under.
    """
    excluded = {"seq", "ts", "node_id", "campaign_id"}
    rows = ledger.TrialLedger(database_url).rows()
    result: set[tuple[Any, ...]] = set()
    for row in rows:
        if row.campaign_id != campaign_id:
            continue
        fields = tuple(
            sorted(
                (field.name, getattr(row, field.name))
                for field in dataclasses.fields(row)
                if field.name not in excluded
            )
        )
        result.add(fields)
    return result


def _node_evaluated_positions(events: list[dict[str, Any]], root_ids: list[str]) -> list[int]:
    positions = {node_id: index for index, node_id in enumerate(root_ids)}
    return [
        positions[event["node_id"]]
        for event in events
        if event.get("event") == "node_evaluated"
    ]


# -- Fixtures: one sealed snapshot, shared read-only across this file's tests ---


@pytest.fixture(scope="module")
def snapshot_mount(tmp_path_factory: pytest.TempPathFactory) -> str:
    lake_root = tmp_path_factory.mktemp("process-pool-eval-lake")
    sealed = _seal_world(lake_root)
    return str(sealed.path)


# -- modes "process" and "thread" produce identical results --------------------


def test_process_and_thread_modes_produce_identical_results(
    tmp_path_factory: pytest.TempPathFactory,
    snapshot_mount: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_result, process_events, process_author, process_db = _run_one(
        tmp_path_factory.mktemp("parity-process"),
        mode="process",
        label="parity-process",
        snapshot_mount=snapshot_mount,
        monkeypatch=monkeypatch,
    )
    thread_result, thread_events, thread_author, thread_db = _run_one(
        tmp_path_factory.mktemp("parity-thread"),
        mode="thread",
        label="parity-thread",
        snapshot_mount=snapshot_mount,
        monkeypatch=monkeypatch,
    )

    assert len(process_result.roots) == len(thread_result.roots) == WORKSPACES

    # Persisted node rows: the six metric columns, by planting position —
    # root uuids themselves differ between the two runs (never pinned).
    process_rows = _root_metric_rows(process_db, FIXED_CAMPAIGN_ID)
    thread_rows = _root_metric_rows(thread_db, FIXED_CAMPAIGN_ID)
    assert len(process_rows) == len(thread_rows) == WORKSPACES
    assert process_rows == thread_rows

    # Ledger rows: set-equal (the task's own word), identifiers excluded.
    assert _ledger_row_set(process_db, FIXED_CAMPAIGN_ID) == _ledger_row_set(
        thread_db, FIXED_CAMPAIGN_ID
    )

    # node_evaluated event order: the same sequence of planting positions.
    process_order = _node_evaluated_positions(process_events, process_author.root_ids)
    thread_order = _node_evaluated_positions(thread_events, thread_author.root_ids)
    assert process_order == thread_order == list(range(WORKSPACES))


# -- Throughput: process mode with 4 workers is at least 2.5x faster -----------


def test_process_mode_is_at_least_two_point_five_times_faster_than_thread_mode(
    tmp_path_factory: pytest.TempPathFactory,
    snapshot_mount: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = time.perf_counter()
    _run_one(
        tmp_path_factory.mktemp("perf-process"),
        mode="process",
        label="perf-process",
        snapshot_mount=snapshot_mount,
        monkeypatch=monkeypatch,
        stub_spec=_SLOW_STUB_SPEC,
        workers=4,
    )
    process_seconds = time.perf_counter() - started

    started = time.perf_counter()
    _run_one(
        tmp_path_factory.mktemp("perf-thread"),
        mode="thread",
        label="perf-thread",
        snapshot_mount=snapshot_mount,
        monkeypatch=monkeypatch,
        stub_spec=_SLOW_STUB_SPEC,
        workers=4,
    )
    thread_seconds = time.perf_counter() - started

    assert thread_seconds / process_seconds >= 2.5, (
        f"thread={thread_seconds:.2f}s process={process_seconds:.2f}s: process "
        "mode with 4 workers must be at least 2.5x faster than thread mode "
        "on 8 nodes of CPU-bound, non-GIL-releasing work"
    )


# -- A raising node surfaces as its own failure, siblings unaffected -----------


def test_a_raising_node_surfaces_as_its_own_failure_without_cancelling_siblings(
    tmp_path_factory: pytest.TempPathFactory,
    snapshot_mount: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raising_position = 3
    result, events, author, database_url = _run_one(
        tmp_path_factory.mktemp("raising"),
        mode="process",
        label="raising",
        snapshot_mount=snapshot_mount,
        monkeypatch=monkeypatch,
        raising_position=raising_position,
    )

    assert len(result.roots) == WORKSPACES

    # evaluate_node never writes fail_class onto a root's own node row (that
    # lazy column is discovery.AttemptLog's, for round-loop children only —
    # a root is planted by plant_root, not AttemptLog) — so the failure is
    # read back the one place a root's answer actually carries it: the
    # emitted node_evaluated event.

    # Every node — the raising one included — was still charged exactly
    # once: evaluate_node's own invariant, carried through the pool intact.
    ledger_rows = ledger.TrialLedger(database_url).rows()
    assert len({row.node_id for row in ledger_rows if row.campaign_id == FIXED_CAMPAIGN_ID}) == WORKSPACES

    # node_evaluated fired for every root, in planting order, the raising
    # root's own event carrying its fail_class rather than being absent.
    order = _node_evaluated_positions(events, author.root_ids)
    assert order == list(range(WORKSPACES))
    node_events = {
        event["node_id"]: event for event in events if event.get("event") == "node_evaluated"
    }
    raising_node_id = author.root_ids[raising_position]
    assert node_events[raising_node_id]["fail_class"] == "RuntimeError"
    for position, node_id in enumerate(author.root_ids):
        if position == raising_position:
            continue
        assert node_events[node_id]["fail_class"] is None


# -- Shutdown leaves no child processes ------------------------------------------


def _minimal_evaluation_config(root: Path, *, snapshot_mount: str, workers: int) -> dict[str, Any]:
    return {
        "snapshot_mount": snapshot_mount,
        "evaluation_dates": [EVALUATION_DATES[0].isoformat()],
        "horizon": HORIZON,
        "seed": WORLD_SEED,
        "epoch_id": EPOCH_ID,
        "artifact_dir": str(root / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
        "evaluation_workers": workers,
        "evaluation_mode": "process",
    }


def test_shutdown_leaves_no_child_processes(
    tmp_path: Path, snapshot_mount: str
) -> None:
    from orchestrator._context import load_evaluation_context

    document = _minimal_evaluation_config(tmp_path, snapshot_mount=snapshot_mount, workers=3)
    config_path = tmp_path / "evaluation-config.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    database_url = f"sqlite:///{tmp_path / 'shutdown.db'}"
    bwrap_dir = _fake_bwrap(tmp_path)

    env = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": database_url,
        "NULLIUS_EVALUATOR_IMAGE": EVALUATOR_IMAGE,
        "PATH": str(bwrap_dir),
    }
    context = load_evaluation_context(env)
    assert context is not None

    evaluator = ProcessEvaluator(context, env=env)
    try:
        # Force every one of the three worker processes to actually start —
        # a pool that never ran a task would leave no children trivially,
        # proving nothing about shutdown. os.getpid submitted directly
        # (bypassing .evaluate()) needs nothing from nulloracle/the ledger:
        # _init_worker runs regardless of what is submitted, and this
        # context carries no sidecar at all.
        futures = [evaluator._pool.submit(os.getpid) for _ in range(3)]
        pids = {future.result(timeout=30) for future in futures}
        assert len(pids) >= 1

        for pid in pids:
            os.kill(pid, 0)  # raises ProcessLookupError if already gone

        evaluator.shutdown(wait=True)

        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        evaluator.shutdown(wait=True)

