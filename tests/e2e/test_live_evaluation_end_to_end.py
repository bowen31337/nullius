"""Live evaluation, end to end, with no network: two roots, one child each.

additions_spec_live_evaluation.xml's campaign driver rests on one claim this
journey is the first to exercise with every seam real: a child node's
evaluation is debited exactly once, under the budget directive the *real*
null oracle route answered for its root — never a bit this suite forces in
by hand, and never one the orchestrator reads off a sidecar key it has no
business touching (``orchestrator._oracle.SubtreeOracle`` and
``orchestrator._evaluate.evaluate_node`` hold no ``import nulloracle`` of
their own at module scope; see ``test_oracle.py``'s own barrier test for that
half).

**Setup.** A throwaway SQLite database is migrated to the node table (0118 +
0114, so the metric columns exist) and the campaign table (0111).  A
Type-R campaign with exactly two roots (``workspace_count=2``,
``null_fraction=0.5``, so ``round(0.5 * 2) == 1``) is planted, each root with
one child.  :meth:`nulloracle.TypeRSelection.persist` draws the selection
against a throwaway sidecar (a fresh key and path, never the deployment's
own) — §7.3's ``without replacement`` draw over exactly two wells always
seals one null and one real root, and *which* physical root wins the draw is
whatever the selection's own seed (a hash of the fixed campaign and root ids
this module pins) resolves to; this suite reads the answer off
``RootSelection.null_roots``/``real_roots`` rather than assuming either
root.

**The oracle.** ``evaluate_node`` runs each child through a real
:class:`orchestrator._oracle.SubtreeOracle` over a real
:class:`nulloracle.TargetEndpoint` — the actual route, not a stand-in —
backed by the same throwaway sidecar, with a ``targets`` seam answering the
real forward-return panel and a ``permute`` seam that is feature 115's own
:func:`nulloracle.block_indices` at the panel's grain (test_target.py's own
reconciliation).  The endpoint is wrapped only to *record* the
:class:`~nulloracle.TargetResponse` it serves for each request — the
assertions below read the branch off that recorded response (its
``target_series`` and ``charges_budget``), never off an ``is_null`` bit
inside the orchestrator, because there is no such bit to read: the
orchestrator's own modules hold none.

**The one scenario, several claims.** A single module-scoped journey plants
the tree and runs every evaluation once; the twenty-one-date rebalance grid
below is sized so the null branch's block permutation (feature 115's default
twenty-day blocks) visibly reorders more than one block for the real roots
this module pins — a span of exactly twenty would degenerate to a single,
unshuffled block, which would make "the null child was served something
*different* from the real series" true only by luck of the seed. Each
``test_*`` function below asserts one clause against that one run:

* each child's measured metrics land on its own node row;
* each child is debited exactly once, under the oracle's own
  ``charges_budget``;
* the null root's child is served the real series' block permutation and
  the real root's child is served the untouched series — read off the
  endpoint's own recorded responses;
* a second ``evaluate_node`` on an already-evaluated child appends no second
  debit;
* a child whose signal raises is charged as a failure, under the raised
  class's own name.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import random
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import FeeSchedule, load_cost_model
from ledger import TrialLedger
from nulloracle import (
    NullSidecar,
    RootSelection,
    SidecarKey,
    TargetEndpoint,
    TargetResponse,
    TypeRSelection,
    block_indices,
)
from orchestrator._context import EvaluationContext
from orchestrator._evaluate import NodeEvaluation, SandboxExecutionError, evaluate_node
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

# This file is under tests/e2e, so the repository root is two parents up —
# tests -> e2e -> repo root — matching the other e2e journeys' own
# convention for reaching migrations/versions by path.
REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The three migrations the tree and the campaign row need: the node table's
#: five structural columns (0118), the seven metric columns feature 7's
#: writer lands on it (0114), and the campaign row Type-R selection reads φ
#: and W from (0111).
TREE_MIGRATIONS = ("0118_node_table", "0114_node_metrics", "0111_campaign_table")

#: The world's cross-section — four symbols, the same scale
#: ``test_evaluate.py`` uses: enough for a real cross-sectional rank
#: correlation, small enough that twenty-one sandbox spawns per evaluation
#: stay fast.
SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
LOOKBACK = 6

#: Twenty-one *contiguous* rebalance dates — every bar day is scored, the
#: same dense, gapless world ``test_momentum_signal_positive_ic.py`` and
#: ``test_evaluate.py`` both build, so the null oracle's served support
#: (every calendar day in the asked span) is exactly the aligned support at
#: every horizon the gate covers (§7.2's own exact-match rule,
#: ``evaluator._gate._check_support``). Twenty-one, not twenty: feature
#: 115's block permutation cuts a series into runs of its stored
#: ``block_days`` (default twenty), so a twenty-element series is one
#: block — permuted into itself — and a twenty-*one*-element one is two,
#: which is what lets this suite tell a permuted answer from the real one
#: by content rather than merely by the oracle's own directive.
EVALUATION_SPAN = 21
BAR_DAYS = tuple(
    FIRST_DAY + dt.timedelta(days=offset) for offset in range(LOOKBACK + EVALUATION_SPAN + 1)
)
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + EVALUATION_SPAN]
WORLD_SEED = 20261005
AUTOCORRELATION = 0.5
HORIZON = 1
EPOCH_ID = "epoch-2026-10-05-live-eval-e2e"
EVALUATOR_HASH = "a1" * 32
SNAPSHOT_HASH_FALLBACK = "b2" * 32
COST_MODEL_HASH = "c3" * 32

#: Fixed, canonical UUIDs rather than freshly minted ones: §7.3's draw (and
#: feature 115's permutation seed) is a deterministic function of the
#: campaign and root ids, and this suite needs that function's answer
#: pinned — both *which* root is drawn null and *whether* its permutation
#: visibly reorders this suite's twenty-one-date series — to hold on every
#: run rather than on whichever ids a random UUID happened to mint.
CAMPAIGN_ID = "c0ffee00-0000-4000-8000-000000000001"
ROOT_A = "c0ffee00-0000-4000-8000-00000000000a"
ROOT_B = "c0ffee00-0000-4000-8000-00000000000b"
CHILD_OF_ROOT_A = "c0ffee00-0000-4000-8000-0000000000a1"
CHILD_OF_ROOT_B = "c0ffee00-0000-4000-8000-0000000000b1"
FAILING_CHILD_OF_ROOT_A = "c0ffee00-0000-4000-8000-0000000000af"

#: The sidecar's test-only key — never a deployment's, never read from an
#: environment reference.
TEST_KEY_HEX = "11" * 32

#: A hand-written momentum signal, the same shape ``test_evaluate.py``'s own
#: ``MOMENTUM_SIGNAL_CODE`` is: a real sandbox spawn per rebalance date,
#: scoring the sealed bars rather than a stand-in. Imports polars
#: explicitly: orchestrator._sandbox_child's bootstrap (the executor
#: additions_spec_gvisor_executor.xml's "Executor Selection" feature wires
#: evaluate_node through) gives the signal nothing it did not import
#: itself, unlike the evaluator's own embedded SignalSandbox.
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

#: A signal with no disallowed import that always raises at run time — the
#: sandbox's own "crash" resource failure, which ``evaluate_node`` charges
#: under :class:`~orchestrator._evaluate.SandboxExecutionError`.
CRASHING_SIGNAL_CODE = """
def signal(ctx, seed):
    raise ValueError("this signal always crashes")
"""


# -- Migrations and raw-SQL planting --------------------------------------------


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_live_eval_e2e_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _migrate(database_url: str) -> None:
    for revision in TREE_MIGRATIONS:
        _load_migration(revision).apply(database_url)


def _plant_campaign(
    database_url: str,
    campaign_id: str,
    *,
    campaign_type: str,
    workspace_count: int,
    null_fraction: float,
) -> None:
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO campaign (id, campaign_type, workspace_count, null_fraction) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, campaign_type, workspace_count, null_fraction),
        )


def _plant_node(
    database_url: str,
    *,
    node_id: str,
    parent_id: str | None,
    campaign_id: str,
    depth: int,
    theme_root: str = "macro",
) -> None:
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, parent_id, campaign_id, theme_root, depth),
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


# -- The sealed world, scaled for one block-boundary-crossing horizon ----------


def _seal_the_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    """Stage an AR(1) momentum world over :data:`BAR_DAYS` and seal it."""
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


# -- The null oracle's real seams: a dense real series, and feature 115's own shuffle --


def _targets_seam(request: Any) -> dict[dt.date, dict[str, float]]:
    """The ``targets`` seam: the real forward-return panel for one request.

    Dense and gapless over the request's own ``date_range`` — every
    calendar day between its ends, for every symbol it named — which is
    exactly the aligned support at every horizon this suite's rebalance
    grid covers, because the grid itself is dense and gapless (see the
    module docstring). A deterministic, varying-by-symbol-and-date value
    (never read from any null bit), so the content comparisons below are
    comparisons of real numbers, not placeholders.
    """
    first, last = request.date_range
    days: list[dt.date] = []
    day = first
    while day <= last:
        days.append(day)
        day += dt.timedelta(days=1)
    symbols = sorted(request.symbols)
    return {
        day: {
            symbol: 0.001 * (index + 1) * (1.0 + 0.15 * (day - first).days)
            for index, symbol in enumerate(symbols)
        }
        for day in days
    }


def _permute_seam(
    series: Mapping[dt.date, Mapping[str, float]], *, seed: Any, block_days: Any
) -> dict[dt.date, dict[str, float]]:
    """Feature 115's mechanism at the panel's grain — the dates are the blocks.

    The same reconciliation ``nulloracle/tests/test_target.py``'s own
    ``_permute`` makes, over the real member's own :func:`block_indices`:
    the blocks are runs of consecutive *dates*, each date's whole
    cross-section travelling with it.
    """
    days = list(series)
    rows = [series[day] for day in days]
    order = block_indices(range(len(days)), seed=seed, block_days=block_days)
    return {
        days[position]: dict(rows[order[position]]) for position in range(len(days))
    }


class _RecordingEndpoint:
    """Wraps the *real* :class:`TargetEndpoint`, recording every call.

    The oracle under test is exercised against the genuine route — this
    wraps it only to capture ``(request, response)`` pairs for the
    assertions below to read the served branch off, never to answer in its
    own stead.
    """

    def __init__(self, endpoint: TargetEndpoint) -> None:
        self._endpoint = endpoint
        self.calls: list[tuple[Any, TargetResponse]] = []

    def post(self, request: Any) -> TargetResponse:
        response = self._endpoint.post(request)
        self.calls.append((request, response))
        return response


# -- The one journey -------------------------------------------------------------


@dataclass(frozen=True)
class _Journey:
    context: EvaluationContext
    ledger: TrialLedger
    sidecar: NullSidecar
    selection: RootSelection
    null_root: str
    real_root: str
    child_of_null_root: str
    child_of_real_root: str
    failing_child: str
    recording: _RecordingEndpoint
    answer_null: NodeEvaluation
    answer_real: NodeEvaluation
    answer_real_again: NodeEvaluation
    answer_failing: NodeEvaluation


def _run_the_journey(tmp_path: Path, mount: Any, closes: dict) -> _Journey:
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'live-eval.db'}"
    _migrate(database_url)

    context = EvaluationContext(
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
    ledger = TrialLedger(database_url)

    sidecar = NullSidecar(
        tmp_path / "null" / "sidecar.enc", SidecarKey.from_hex(TEST_KEY_HEX)
    )

    _plant_campaign(
        database_url,
        CAMPAIGN_ID,
        campaign_type="Type-R",
        workspace_count=2,
        null_fraction=0.5,
    )
    _plant_node(database_url, node_id=ROOT_A, parent_id=None, campaign_id=CAMPAIGN_ID, depth=0)
    _plant_node(database_url, node_id=ROOT_B, parent_id=None, campaign_id=CAMPAIGN_ID, depth=0)

    selection = TypeRSelection(database_url, sidecar).persist(CAMPAIGN_ID)
    assert len(selection.null_roots) == 1
    assert len(selection.real_roots) == 1
    (null_root,) = selection.null_roots
    (real_root,) = selection.real_roots

    child_of_null_root = CHILD_OF_ROOT_A if null_root == ROOT_A else CHILD_OF_ROOT_B
    child_of_real_root = CHILD_OF_ROOT_B if null_root == ROOT_A else CHILD_OF_ROOT_A
    _plant_node(
        database_url,
        node_id=child_of_null_root,
        parent_id=null_root,
        campaign_id=CAMPAIGN_ID,
        depth=1,
    )
    _plant_node(
        database_url,
        node_id=child_of_real_root,
        parent_id=real_root,
        campaign_id=CAMPAIGN_ID,
        depth=1,
    )
    _plant_node(
        database_url,
        node_id=FAILING_CHILD_OF_ROOT_A,
        parent_id=real_root,
        campaign_id=CAMPAIGN_ID,
        depth=1,
    )

    endpoint = TargetEndpoint(sidecar, targets=_targets_seam, permute=_permute_seam)
    recording = _RecordingEndpoint(endpoint)
    oracle = SubtreeOracle(recording, database_url=database_url)

    answer_null = evaluate_node(
        child_of_null_root,
        CAMPAIGN_ID,
        1,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )
    answer_real = evaluate_node(
        child_of_real_root,
        CAMPAIGN_ID,
        1,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )
    answer_real_again = evaluate_node(
        child_of_real_root,
        CAMPAIGN_ID,
        1,
        MOMENTUM_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )
    answer_failing = evaluate_node(
        FAILING_CHILD_OF_ROOT_A,
        CAMPAIGN_ID,
        1,
        CRASHING_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    return _Journey(
        context=context,
        ledger=ledger,
        sidecar=sidecar,
        selection=selection,
        null_root=null_root,
        real_root=real_root,
        child_of_null_root=child_of_null_root,
        child_of_real_root=child_of_real_root,
        failing_child=FAILING_CHILD_OF_ROOT_A,
        recording=recording,
        answer_null=answer_null,
        answer_real=answer_real,
        answer_real_again=answer_real_again,
        answer_failing=answer_failing,
    )


@pytest.fixture(scope="module")
def journey(tmp_path_factory: pytest.TempPathFactory) -> _Journey:
    workdir = tmp_path_factory.mktemp("live-eval-e2e-world")
    mount, closes = _seal_the_world(workdir)
    run_dir = tmp_path_factory.mktemp("live-eval-e2e-run")
    return _run_the_journey(run_dir, mount, closes)


# -- Each child's metrics land on its own node row ------------------------------


def test_each_childs_metrics_land_on_its_own_node_row(journey: _Journey) -> None:
    for answer, child_id in (
        (journey.answer_null, journey.child_of_null_root),
        (journey.answer_real, journey.child_of_real_root),
    ):
        assert answer.fail_class is None
        assert answer.metrics is not None
        columns = _metric_columns(journey.context.database_url, child_id)
        assert columns["ic_mean"] == pytest.approx(answer.metrics.ic_mean)
        assert columns["ic_tstat"] == pytest.approx(answer.metrics.ic_tstat)
        assert columns["ir_standalone"] == pytest.approx(answer.metrics.ir_standalone)
        assert columns["turnover"] == pytest.approx(answer.metrics.turnover)
        assert columns["ir_marginal"] == pytest.approx(answer.score.ir_marginal)
        assert columns["cost_adjusted_ir"] == pytest.approx(answer.score.cost_adjusted_ir)


# -- Each child is debited once, under the oracle's own charges_budget ----------


def test_each_child_is_debited_once_under_the_oracles_own_charges_budget(
    journey: _Journey,
) -> None:
    for answer, child_id, root_id in (
        (journey.answer_null, journey.child_of_null_root, journey.null_root),
        (journey.answer_real, journey.child_of_real_root, journey.real_root),
    ):
        rows = [row for row in journey.ledger.rows() if row.node_id == child_id]
        assert len(rows) == 1, f"node {child_id} must be debited exactly once"
        landed = rows[0]
        assert landed.outcome == "ok"

        # The oracle's own answer for this node's root — read off the
        # endpoint's recorded response, never off a bit the orchestrator
        # could have read internally (it reads none).
        served = [
            response
            for request, response in journey.recording.calls
            if response.node_id == root_id
        ]
        assert served, f"the oracle must have been asked for root {root_id}"
        directive = served[0].charges_budget
        assert all(response.charges_budget == directive for response in served)

        assert answer.charges_budget is directive
        assert answer.debit.charge.charges_budget is directive
        assert landed.charges_budget is directive


def test_the_null_roots_child_got_a_false_directive_and_the_real_roots_got_true(
    journey: _Journey,
) -> None:
    # The spec's own column comment: FALSE for null nodes. Pinned here from
    # the recorded responses, which is the only place this suite ever reads
    # the directive from.
    null_served = [
        response
        for _, response in journey.recording.calls
        if response.node_id == journey.null_root
    ]
    real_served = [
        response
        for _, response in journey.recording.calls
        if response.node_id == journey.real_root
    ]
    assert null_served and all(r.charges_budget is False for r in null_served)
    assert real_served and all(r.charges_budget is True for r in real_served)


# -- The served content: the null root's child got the block permutation --------


def test_the_null_roots_child_was_served_the_block_permutation(journey: _Journey) -> None:
    assignment = journey.sidecar.assignment(journey.null_root)
    assert assignment is not None
    assert assignment.is_null is True

    horizon_one_calls = [
        (request, response)
        for request, response in journey.recording.calls
        if response.node_id == journey.null_root and request.horizon == HORIZON
    ]
    assert horizon_one_calls, "the null root must have been asked at horizon 1"

    found_a_difference = False
    for request, response in horizon_one_calls:
        expected_real = _targets_seam(request)
        expected_permuted = _permute_seam(
            expected_real, seed=assignment.perm_seed, block_days=assignment.block_days
        )
        served = {day: dict(row) for day, row in response.target_series.items()}
        assert served == expected_permuted
        if served != expected_real:
            found_a_difference = True

    # Not a tautology: the twenty-one-date grid (see the module docstring)
    # is sized so this horizon's permutation visibly reorders more than one
    # block, so at least one covered request must actually differ from the
    # real series — proving the null child was served *something else*, not
    # merely something this test happens to call "permuted".
    assert found_a_difference


def test_the_real_roots_child_was_served_the_real_series_unchanged(
    journey: _Journey,
) -> None:
    real_calls = [
        (request, response)
        for request, response in journey.recording.calls
        if response.node_id == journey.real_root and request.horizon == HORIZON
    ]
    assert real_calls, "the real root must have been asked at horizon 1"

    for request, response in real_calls:
        expected_real = _targets_seam(request)
        served = {day: dict(row) for day, row in response.target_series.items()}
        assert served == expected_real


# -- Idempotency: a second evaluation appends no second debit -------------------


def test_a_second_evaluation_of_the_same_child_appends_no_second_debit(
    journey: _Journey,
) -> None:
    assert journey.answer_real.metrics is not None
    assert journey.answer_real_again.metrics is not None
    assert journey.answer_real_again.metrics.ic_mean == pytest.approx(
        journey.answer_real.metrics.ic_mean
    )

    assert journey.answer_real.persistence.tree_written is True
    assert journey.answer_real_again.persistence.tree_written is False
    assert journey.answer_real.debit.appended is True
    assert journey.answer_real_again.debit.appended is False
    assert journey.answer_real_again.debit.seq == journey.answer_real.debit.seq

    rows = [
        row
        for row in journey.ledger.rows()
        if row.node_id == journey.child_of_real_root
    ]
    assert len(rows) == 1


# -- A crashing signal is charged as a failure, under its own class name -------


def test_a_crashing_signals_child_is_charged_as_a_failure_with_its_fail_class(
    journey: _Journey,
) -> None:
    answer = journey.answer_failing
    assert answer.metrics is None
    assert answer.persistence is None
    assert answer.fail_class == SandboxExecutionError.__name__
    assert answer.score.fail_class == SandboxExecutionError.__name__

    columns = _metric_columns(journey.context.database_url, journey.failing_child)
    assert all(value is None for value in columns.values())

    rows = [row for row in journey.ledger.rows() if row.node_id == journey.failing_child]
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert answer.debit.appended is True
    assert answer.debit.charge.outcome == "error"
