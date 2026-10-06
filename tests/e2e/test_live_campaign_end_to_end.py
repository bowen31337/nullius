"""A small live campaign, end to end, with no network.

additions_spec_campaign_driver.xml's whole point is that feature 6's
``orchestrator._campaign.run_campaign`` is not a new pipeline — it is the
order the campaign driver calls collaborators every other e2e journey has
already proven real: feature 1's :class:`signal_agent.LLMSignalAuthor`
(``tests/e2e/test_llm_authoring_end_to_end.py``), spec A's live evaluator
(``tests/e2e/test_live_evaluation_end_to_end.py``), and the baseline
exploration policy (``orchestrator._policy``).  This journey is the one that
wires all three into ``run_campaign`` itself and watches a genuinely small
campaign — two roots, two rounds of width two — plant, seal, evaluate and
expand with every seam real.

**No network, anywhere.**  The model calls are answered twice over the same
script, the ``tests/e2e/test_llm_authoring_end_to_end.py`` discipline: a
*capture* pass runs the real choreography against a scripted ``Provider``
wrapped in ``RecordingProvider``, and a *replay* pass — the one every
assertion below reads from — runs the identical choreography with the
resolver answering ``RecordedProvider``, which has no transport to fall back
to at all.

**Why a campaign can be captured and replayed when ``run_campaign`` itself
mints the campaign id and the two root ids.**  ``discovery.create_campaign``
accepts an explicit ``campaign_id`` (the module's own "re-issue the identical
plan" door), so this module calls the real function through a thin wrapper
that always supplies one fixed id — a real code path, not a stand-in.  A
root's own id never enters an authoring prompt at all (``build_authoring_prompt``
reads only ``campaign_id``, ``theme_root`` and ``depth`` off the workspace), so
the two roots' ids need not match between the two passes for the *prompt text*
to agree — but they must match for the *measured scores* to agree, because
§7.3's Type-R draw and feature 115's permutation seed are hashes of
``(campaign_id, root_id)``.  So ``uuid.uuid4`` is patched too, for the two
calls ``run_campaign`` makes while planting roots, and the campaign's prior
history (persisted proposals and their measured scores) is then byte-identical
between the two passes, which is what lets a fixture answer the replay at all.

**One root fails on purpose, and that is what keeps two concurrent round-loop
slots from racing the fixtures.**  ``root_fail``'s signal always raises, so it
is never revealed and never selected — every round this journey runs
dispatches exactly one real job, never two, so there is no thread race between
two workers reading the campaign's history at two different moments (the
other root's own idempotent re-selection in round two — see below — reads an
already-settled history too, for the same reason).  ``root_ok`` instead
expands two full rounds deep: root -> child (round 1) -> grandchild (round 2).

**The baseline policy re-selects an already-expanded root, and that is a real,
idempotent fact about it, not a test artifact.** ``orchestrator._policy.
BaselinePolicy`` ranks every *revealed* node and takes up to ``width``, with no
notion of "already expanded" — so once ``root_ok`` and its child are both
revealed (round 2), a width-two batch contains both, and ``root_ok`` is
re-expanded.  Re-expansion derives the *same* child id
(``discovery.refined_node_id`` is a pure function of the parent) whose own
proposal is now part of the campaign's history, so the anti-convergence gate
correctly refuses this second authoring as a duplicate structure — a quiet,
documented ``authoring_refused`` outcome for a node whose row and ledger debit
were already written in round one, and not a failure any assertion below
should be surprised by.

Every node's authoring prompt is matched for the fixture not by its content
hash but by ``(the resumed workspace's own depth, its theme_root, whether its
history is empty)`` — the triple a scripted ``Provider`` can read straight off
the rendered prompt without caring which thread asked or how many retries
preceded it, which is what the capture pass answers deterministically with.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import random
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import discovery
import providers
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import signal_agent
from cost_model import FeeSchedule, load_cost_model
from ledger import TrialLedger
from nulloracle import (
    NullSidecar,
    SidecarKey,
    TargetEndpoint,
    TypeRSelection,
    block_indices,
)
from orchestrator._campaign import (
    STOP_NO_BATCH,
    STOP_ROUND_CAP,
    CampaignResult,
    run_campaign,
)
from orchestrator._context import EvaluationContext
from orchestrator._evaluate import evaluate_node
from orchestrator._oracle import SubtreeOracle
from orchestrator._policy import load_exploration_policy
from policy_runtime import UNBOUNDED_BUDGET
from snapshot import SnapshotService

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = (
    "0118_node_table",
    "0117_identity_trio",
    "0116_provenance_trio",
    "0115_agent_model_trio",
    "0114_node_metrics",
)

# -- The fixed identities: campaign_id and the two root ids, minted by the ---
# -- real discovery.create_campaign / uuid.uuid4, pinned so capture and     --
# -- replay agree about which prompts were ever asked.                      --

FIXED_CAMPAIGN_ID = "c0ffee00-0000-4000-8000-000000000c01"
ROOT_OK_ID = "c0ffee00-0000-4000-8000-0000000000a1"
ROOT_FAIL_ID = "c0ffee00-0000-4000-8000-0000000000b1"
CHILD_OK_ID = discovery.refined_node_id(ROOT_OK_ID)
GRANDCHILD_OK_ID = discovery.refined_node_id(CHILD_OK_ID)

#: The deployment's legal theme set, read the same unconfigured way
#: run_campaign's own ``_themes_for`` reads it — the default six, canonical
#: order — so the two themes this module answers fixtures for are the two
#: ``run_campaign`` actually assigns its two roots.
_LEGAL_THEMES = discovery.legal_themes_from_env()
THEME_OK = _LEGAL_THEMES.themes[0]
THEME_FAIL = _LEGAL_THEMES.themes[1]

#: The real uuid4, captured before anything patches the name, so the patched
#: generator can fall back to a genuine random id if it is ever asked for a
#: third one.
_REAL_UUID4 = uuid.uuid4

SIDECAR_KEY_HEX = "aa" * 32
EVALUATOR_HASH = "11" * 32
SNAPSHOT_HASH = "22" * 32
COST_MODEL_HASH = "33" * 32
EPOCH_ID = "epoch-2026-10-06-live-campaign-e2e"

SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
LOOKBACK = 3
EVALUATION_SPAN = 5
BAR_DAYS = tuple(
    FIRST_DAY + dt.timedelta(days=offset) for offset in range(LOOKBACK + EVALUATION_SPAN + 1)
)
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + EVALUATION_SPAN]
WORLD_SEED = 20261006
AUTOCORRELATION = 0.5
HORIZON = 1


# ── Valid signal sources, each with exactly one Mechanism line ──────────────

ROOT_OK_CODE = f"""\
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

ROOT_OK_ANSWER = (
    "Short-horizon drift continuation off the sealed daily bars.\n\n"
    "```python\n" + ROOT_OK_CODE + "```\n\n"
    "Mechanism: Short-term order-flow imbalance persists for a few sessions "
    "before mean-reverting, so the simple close-to-close drift over the "
    "lookback window is the edge.\n"
)

ROOT_FAIL_CODE = """\
def signal(ctx, seed):
    raise ValueError("this signal always crashes")
"""

ROOT_FAIL_ANSWER = (
    "A deliberately unworkable control branch.\n\n"
    "```python\n" + ROOT_FAIL_CODE + "```\n\n"
    "Mechanism: No mechanism is claimed; this branch exists to exercise the "
    "failure path and is not expected to score.\n"
)

CHILD_OK_CODE = f"""\
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
    if len(bars) <= 0:
        raise ValueError("the window carries no bars to score against")
    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    spreads = []
    for symbol in ctx.universe:
        series = frame.filter(pl.col("symbol") == symbol).sort("open_time")["c"]
        if len(series) < {LOOKBACK}:
            spreads.append(0.0)
            continue
        spreads.append(float(series.max()) - float(series.min()))
    return pl.Series(spreads)
"""

CHILD_OK_ANSWER = (
    "Realised-range widening as a volatility-state signal.\n\n"
    "```python\n" + CHILD_OK_CODE + "```\n\n"
    "Mechanism: A widening high-low range over the lookback window marks a "
    "regime shift that the next session's cross-section continues to price.\n"
)

GRANDCHILD_OK_CODE = f"""\
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
    if len(bars) <= 0:
        raise ValueError("the window carries no bars to score against")
    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    scores = {{}}
    for symbol in ctx.universe:
        values = frame.filter(pl.col("symbol") == symbol).sort("open_time")["c"].to_list()
        window = values[-({LOOKBACK} + 1):]
        total = 0.0
        index = 0
        while index < len(window) - 1:
            total += window[index + 1] - window[index]
            index += 1
        scores[symbol] = total
    return pl.Series([scores[symbol] for symbol in ctx.universe])
"""

GRANDCHILD_OK_ANSWER = (
    "Accumulated bar-over-bar drift, seed-free, as a robustness refinement.\n\n"
    "```python\n" + GRANDCHILD_OK_CODE + "```\n\n"
    "Mechanism: Summing consecutive close changes over the lookback window "
    "is a smoother reading of the same short-horizon drift the parent found.\n"
)

#: Each distinct authoring prompt this campaign ever asks, keyed by the
#: resumed workspace's own depth, its theme_root, and whether its history is
#: empty — the one triple that distinguishes "author this root" from
#: "expand this root's child" without depending on which concurrent thread
#: asked or how many retries preceded it (see the module docstring).
_ANSWERS: dict[tuple[int, str, bool], tuple[str, dict[str, int]]] = {
    (0, THEME_OK, True): (ROOT_OK_ANSWER, {"input_tokens": 500, "output_tokens": 120, "cache_read_tokens": 0}),
    (0, THEME_FAIL, True): (ROOT_FAIL_ANSWER, {"input_tokens": 480, "output_tokens": 90, "cache_read_tokens": 0}),
    (0, THEME_OK, False): (CHILD_OK_ANSWER, {"input_tokens": 700, "output_tokens": 140, "cache_read_tokens": 50}),
    (1, THEME_OK, False): (GRANDCHILD_OK_ANSWER, {"input_tokens": 750, "output_tokens": 150, "cache_read_tokens": 80}),
}

ROOT_PIN = providers.ModelPin("deepseek", "deepseek-v4-flash", "20260910")
# claude-haiku-4-5, not claude-opus-5: this campaign states a CONFIG
# temperature below, and providers._anthropic's per-model sampling table
# (additions_spec_real_campaign_path.xml feature 5) now refuses an
# AuthoringConfig that states one for a depth/policy pin whose model
# rejects it outright — claude-opus-5 is one of those, claude-haiku-4-5
# is not. The scripted provider below never inspects the model string's
# real-world sampling behaviour, so the swap changes nothing this test
# exercises.
DEPTH_PIN = providers.ModelPin("anthropic", "claude-haiku-4-5", "20260401")
POLICY_PIN = providers.ModelPin("self-hosted", "llama-3", "local")

CONFIG = providers.AuthoringConfig(
    root_tier=(ROOT_PIN,),
    depth=DEPTH_PIN,
    policy=POLICY_PIN,
    temperature=0.2,
    max_tokens=1024,
    max_input_tokens=200_000,
    max_output_tokens=200_000,
)


# ── The scripted provider: content-matched, not sequence-matched ────────────


class _ScriptedProvider(providers.Provider):
    """Answers every call from :data:`_ANSWERS`, matched by prompt content.

    A real :class:`providers.Provider` subclass with no transport anywhere in
    it, used only by the capture pass.  Matching by content rather than call
    order is what lets this run unmodified under a width-two round whose two
    jobs are real concurrent threads.
    """

    def __init__(self, answers: dict[tuple[int, str, bool], tuple[str, dict[str, int]]]) -> None:
        self._answers = answers
        self.requests: list[providers.Request] = []

    def _complete(self, request: providers.Request) -> providers.Completion:
        self.requests.append(request)
        system = request.messages[0].content
        assert system.startswith("## Task\n"), system
        task_text, _, _ = system[len("## Task\n") :].partition(
            "\n\n## Anti-convergence clause\n"
        )
        task = json.loads(task_text)
        history_is_empty = "No prior proposals exist yet" in request.messages[1].content
        key = (task["depth"], task["theme_root"], history_is_empty)
        content, usage = self._answers[key]
        return providers.Completion(
            content=content, model=request.model, usage=providers.Usage(**usage)
        )


def _build_author(resolve: Callable[[providers.ModelPin], providers.Provider], history_store: Any) -> signal_agent.LLMSignalAuthor:
    session = providers.AuthoringSession(CONFIG, resolve)
    return signal_agent.LLMSignalAuthor(
        session,
        history_store=history_store,
        contract=signal_agent.signal_contract(),
        anti_convergence=signal_agent.anti_convergence_gate(),
        guidance=signal_agent.prompt_guidance_gate(),
        config=CONFIG,
    )


# ── Migrations, the sealed world, and the null oracle's real seams ─────────


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(f"_live_campaign_e2e_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrate(database_url: str) -> None:
    _load_migration(CAMPAIGN_MIGRATION).apply(database_url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)


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
            return_ = AUTOCORRELATION * previous_return + (1.0 - AUTOCORRELATION) * shock
            price = max(1.0, price * (1.0 + return_))
            path[day] = round(price, 2)
            previous_return = return_
        closes[symbol] = path

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
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    mount = service.mount(sealed.name)
    return mount, closes


def _targets_seam(request: Any) -> dict[dt.date, dict[str, float]]:
    first, last = request.date_range
    days: list[dt.date] = []
    day = first
    while day <= last:
        days.append(day)
        day += dt.timedelta(days=1)
    symbols = sorted(request.symbols)
    return {
        day: {
            symbol: 0.001 * (index + 1) * (1.0 + 0.05 * (day - first).days)
            for index, symbol in enumerate(symbols)
        }
        for day in days
    }


def _permute_seam(
    series: dict[dt.date, dict[str, float]], *, seed: Any, block_days: Any
) -> dict[dt.date, dict[str, float]]:
    days = list(series)
    rows = [series[day] for day in days]
    order = block_indices(range(len(days)), seed=seed, block_days=block_days)
    return {days[position]: dict(rows[order[position]]) for position in range(len(days))}


class _RecordingEndpoint:
    """Wraps the real :class:`TargetEndpoint`, recording every call's answer."""

    def __init__(self, endpoint: TargetEndpoint) -> None:
        self._endpoint = endpoint
        self.calls: list[tuple[Any, Any]] = []

    def post(self, request: Any) -> Any:
        response = self._endpoint.post(request)
        self.calls.append((request, response))
        return response


@dataclass
class _World:
    mount: Any
    closes: dict[str, dict[dt.date, float]]
    cost_model: Any
    cost_schedule: Any


def _build_context(world: _World, *, database_url: str, artifact_dir: Path) -> EvaluationContext:
    return EvaluationContext(
        snapshot=world.mount,
        closes=world.closes,
        cost_model=world.cost_model,
        cost_schedule=world.cost_schedule,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        epoch_id=EPOCH_ID,
        database_url=database_url,
        artifact_dir=artifact_dir,
        seed=WORLD_SEED,
        horizon=HORIZON,
        evaluation_dates=EVALUATION_DATES,
        sandbox_runtime="unisolated",
    )


class _LiveEvaluatorAdapter:
    """The real ``evaluate_node``, bound to one context/oracle/ledger — the
    ``evaluator.evaluate(node_id, campaign_id, depth, code)`` shape
    ``run_campaign`` and ``NodeWorker`` both call."""

    def __init__(self, context: EvaluationContext, oracle: Any, ledger_: Any) -> None:
        self._context = context
        self._oracle = oracle
        self._ledger = ledger_

    def evaluate(self, node_id: str, campaign_id: str, depth: int, code: str) -> Any:
        return evaluate_node(
            node_id, campaign_id, depth, code,
            context=self._context, oracle=self._oracle, ledger=self._ledger,
        )


class _OrderTrackingSelection:
    """Records when the Type-R seal ran, beside the real draw it delegates to."""

    def __init__(self, inner: TypeRSelection, order: list[tuple[str, str]]) -> None:
        self._inner = inner
        self._order = order

    def persist(self, campaign_id: str) -> Any:
        self._order.append(("seal", campaign_id))
        return self._inner.persist(campaign_id)


class _OrderTrackingEvaluator:
    """Records when each evaluation ran (and its own answer), beside the real
    evaluator it wraps."""

    def __init__(
        self,
        inner: _LiveEvaluatorAdapter,
        order: list[tuple[str, str]],
        evaluations: dict[str, Any],
    ) -> None:
        self._inner = inner
        self._order = order
        self._evaluations = evaluations

    def evaluate(self, node_id: str, campaign_id: str, depth: int, code: str) -> Any:
        self._order.append(("evaluate", node_id))
        answer = self._inner.evaluate(node_id, campaign_id, depth, code)
        self._evaluations[node_id] = answer
        return answer


class _EmptyBatchPolicy:
    """A policy that always answers no batch — the second run's own stand-in."""

    def select(self, prefix_view: Any) -> list[str]:
        return []


# ── Fixed ids: a real discovery.create_campaign, a real uuid.uuid4 ─────────


def _patch_fixed_campaign_id(mp: pytest.MonkeyPatch) -> None:
    """Make every ``discovery.create_campaign`` call in this module plant
    under :data:`FIXED_CAMPAIGN_ID` — the real function, called with the
    id explicit rather than left to the table's own mint, so capture and
    replay agree about which campaign's history a prompt was built over."""
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
            campaign_type, workspace_count,
            campaign_id=FIXED_CAMPAIGN_ID, database_url=database_url, env=env,
        )

    mp.setattr(discovery, "create_campaign", fixed)


def _reset_root_ids(mp: pytest.MonkeyPatch) -> None:
    """Make the next two ``uuid.uuid4()`` calls answer the two fixed root
    ids, in planting order — reset before every ``run_campaign`` call so
    capture and replay (and the second run) all plant the same two roots."""
    sequence = iter((ROOT_OK_ID, ROOT_FAIL_ID))

    def fake_uuid4() -> Any:
        try:
            return next(sequence)
        except StopIteration:
            return _REAL_UUID4()

    mp.setattr(uuid, "uuid4", fake_uuid4)


# ── Running one campaign over one throwaway database ───────────────────────


@dataclass
class _RunOutcome:
    result: CampaignResult
    events: list[dict[str, Any]]
    database_url: str
    ledger: TrialLedger
    recording: _RecordingEndpoint
    order: list[tuple[str, str]] = field(default_factory=list)
    evaluations: dict[str, Any] = field(default_factory=dict)


def _run_campaign_once(
    *,
    world: _World,
    tmp: Path,
    resolve: Callable[[providers.ModelPin], providers.Provider],
    policy: Any,
) -> _RunOutcome:
    database_url = f"sqlite:///{tmp / 'campaign.db'}"
    _migrate(database_url)
    context = _build_context(world, database_url=database_url, artifact_dir=tmp / "artifacts")

    sidecar = NullSidecar(tmp / "null" / "sidecar.enc", SidecarKey.from_hex(SIDECAR_KEY_HEX))
    endpoint = TargetEndpoint(sidecar, targets=_targets_seam, permute=_permute_seam)
    recording = _RecordingEndpoint(endpoint)
    oracle = SubtreeOracle(recording, database_url=database_url)
    ledger_ = TrialLedger(database_url)

    order: list[tuple[str, str]] = []
    evaluations: dict[str, Any] = {}
    evaluator: Any = _OrderTrackingEvaluator(
        _LiveEvaluatorAdapter(context, oracle, ledger_), order, evaluations
    )
    selection: Any = _OrderTrackingSelection(TypeRSelection(database_url, sidecar), order)

    history_store = signal_agent.ProposalHistoryStore(signal_agent.ProposalStore(database_url))
    author = _build_author(resolve, history_store)

    events: list[dict[str, Any]] = []
    result = run_campaign(
        campaign_type="Type-R",
        workspaces=2,
        rounds=2,
        width=2,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=policy,
        context=context,
        sidecar_selection=selection,
        emit=events.append,
    )
    return _RunOutcome(
        result=result, events=events, database_url=database_url,
        ledger=ledger_, recording=recording, order=order, evaluations=evaluations,
    )


# ── sqlite readers over a run's own database ────────────────────────────────


def _node_row(database_url: str, node_id: str) -> sqlite3.Row:
    path = database_url.removeprefix("sqlite:///")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        # fail_class is not selected here: 0118-0114 never declare it, and
        # discovery.AttemptLog only ADD COLUMNs it at runtime for an
        # *expanded* node — a root planted straight through plant_root may
        # leave a fresh database without the column at all.
        row = connection.execute(
            "SELECT depth, code_hash, agent_model_id, evaluator_hash, snapshot_hash, "
            "cost_model_hash, ic_mean FROM node WHERE id = ?",
            (node_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None, f"no node row for {node_id}"
    return row


def _proposal_count(database_url: str, node_id: str) -> int:
    path = database_url.removeprefix("sqlite:///")
    connection = sqlite3.connect(path)
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM node_proposal WHERE node_id = ?", (node_id,)
        ).fetchone()[0]
    finally:
        connection.close()


# ── Fixtures: the sealed world, and the fixtures captured against it ───────


@pytest.fixture(scope="module")
def _world(tmp_path_factory: pytest.TempPathFactory) -> _World:
    workdir = tmp_path_factory.mktemp("live-campaign-e2e-world")
    mount, closes = _seal_the_world(workdir)
    cost_model = load_cost_model()
    cost_schedule = FeeSchedule(venue=cost_model.venue, taker_bps=10.0, maker_bps=10.0)
    return _World(mount=mount, closes=closes, cost_model=cost_model, cost_schedule=cost_schedule)


@pytest.fixture(scope="module")
def _ids_patch() -> Any:
    mp = pytest.MonkeyPatch()
    _patch_fixed_campaign_id(mp)
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def _captured_responses(
    _world: _World, _ids_patch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Any:
    """Capture every exchange a real campaign makes, against a scripted
    provider matched by prompt content — then hand back the responses a
    :class:`providers.RecordedProvider` answers from, with no transport."""
    _reset_root_ids(_ids_patch)
    tmp = tmp_path_factory.mktemp("live-campaign-e2e-capture")
    scripted = _ScriptedProvider(_ANSWERS)
    recorder = providers.RecordingProvider(scripted)
    _run_campaign_once(
        world=_world, tmp=tmp,
        resolve=lambda pin: recorder,
        policy=load_exploration_policy(env={}),
    )
    store = providers.FixtureStore(tmp / "fixtures")
    store.record_all(recorder.exchanges())
    return store.responses()


@pytest.fixture(scope="module")
def journey(
    _world: _World,
    _ids_patch: pytest.MonkeyPatch,
    _captured_responses: Any,
    tmp_path_factory: pytest.TempPathFactory,
) -> _RunOutcome:
    """The one replayed campaign every assertion below reads — no network,
    no transport, every exchange answered from :func:`_captured_responses`."""
    _reset_root_ids(_ids_patch)
    tmp = tmp_path_factory.mktemp("live-campaign-e2e-replay")
    return _run_campaign_once(
        world=_world, tmp=tmp,
        resolve=lambda pin: providers.RecordedProvider(_captured_responses),
        policy=load_exploration_policy(env={}),
    )


# ── Both roots: depth-0 rows with identity, agent and provenance columns ───


def test_both_roots_are_depth_zero_rows_with_identity_agent_and_provenance(
    journey: _RunOutcome,
) -> None:
    assert journey.result.roots == (ROOT_OK_ID, ROOT_FAIL_ID)
    for node_id in (ROOT_OK_ID, ROOT_FAIL_ID):
        row = _node_row(journey.database_url, node_id)
        assert row["depth"] == 0
        assert isinstance(row["code_hash"], str) and len(row["code_hash"]) == 64
        assert isinstance(row["agent_model_id"], str) and row["agent_model_id"]
        assert row["evaluator_hash"] == EVALUATOR_HASH
        assert row["snapshot_hash"] == SNAPSHOT_HASH
        assert row["cost_model_hash"] == COST_MODEL_HASH


# ── The roots were sealed before the first evaluation ───────────────────────


def test_the_roots_were_sealed_before_the_first_evaluation(journey: _RunOutcome) -> None:
    assert journey.order, "no evaluation or seal was ever recorded"
    assert journey.order[0] == ("seal", journey.result.campaign_id)
    # Exactly one seal, and it is this first entry: every later entry is an
    # evaluation, never a second seal.
    assert all(tag == "evaluate" for tag, _ in journey.order[1:])


# ── Every node row has metrics or a fail_class ──────────────────────────────


def test_every_node_row_has_metrics_or_a_fail_class(journey: _RunOutcome) -> None:
    # A root is planted (plant_root) rather than expanded (AttemptLog), so the
    # tree's own fail_class column — a runtime ADD COLUMN only AttemptLog
    # probes for — is never the root's to carry; the live evaluator's own
    # NodeEvaluation is the one place every evaluated node answers either
    # metrics or a fail_class, win or fail (orchestrator._evaluate's own
    # docstring: "every evaluated node, failed ones included, is charged
    # exactly once").
    for node_id in (ROOT_OK_ID, ROOT_FAIL_ID, CHILD_OK_ID, GRANDCHILD_OK_ID):
        answer = journey.evaluations[node_id]
        assert answer.metrics is not None or answer.fail_class is not None, node_id
        assert answer.score.fail_class == answer.fail_class

    assert journey.evaluations[ROOT_FAIL_ID].fail_class is not None
    assert journey.evaluations[ROOT_FAIL_ID].metrics is None
    for node_id in (ROOT_OK_ID, CHILD_OK_ID, GRANDCHILD_OK_ID):
        assert journey.evaluations[node_id].fail_class is None
        assert journey.evaluations[node_id].metrics is not None
    # The row the metrics landed on carries them too — the write
    # orchestrator._evaluate.evaluate_node makes on every success.
    for node_id in (ROOT_OK_ID, CHILD_OK_ID, GRANDCHILD_OK_ID):
        assert _node_row(journey.database_url, node_id)["ic_mean"] is not None


# ── The ledger holds exactly one debit per node, at the oracle's own bit ───


def test_the_ledger_holds_one_debit_per_node_at_the_oracles_charges_budget(
    journey: _RunOutcome,
) -> None:
    for node_id in (ROOT_OK_ID, ROOT_FAIL_ID, CHILD_OK_ID, GRANDCHILD_OK_ID):
        rows = [row for row in journey.ledger.rows() if row.node_id == node_id]
        assert len(rows) == 1, f"node {node_id} must be debited exactly once, got {len(rows)}"

    # root_fail crashes before the oracle is ever asked, so its charge is the
    # documented conservative default rather than a directive to compare.
    fail_rows = [row for row in journey.ledger.rows() if row.node_id == ROOT_FAIL_ID]
    assert fail_rows[0].charges_budget is True
    assert fail_rows[0].outcome == "error"

    # root_ok, child_ok and grandchild_ok are all in root_ok's own subtree, so
    # the oracle's directive for all three is the one it answered for root_ok.
    served = [
        response
        for _, response in journey.recording.calls
        if response.node_id == ROOT_OK_ID
    ]
    assert served, "the oracle must have been asked for root_ok's subtree"
    directive = served[0].charges_budget
    assert all(response.charges_budget == directive for response in served)

    for node_id in (ROOT_OK_ID, CHILD_OK_ID, GRANDCHILD_OK_ID):
        rows = [row for row in journey.ledger.rows() if row.node_id == node_id]
        assert rows[0].charges_budget is directive
        assert rows[0].outcome == "ok"


# ── Each node's proposal and score are persisted ────────────────────────────


def test_each_nodes_proposal_and_score_are_persisted(journey: _RunOutcome) -> None:
    for node_id in (ROOT_OK_ID, ROOT_FAIL_ID, CHILD_OK_ID, GRANDCHILD_OK_ID):
        assert _proposal_count(journey.database_url, node_id) == 1, node_id


# ── The manifest is finished, and the round loop stopped as the spec allows ─


def test_the_manifest_is_finished_and_the_stop_reason_is_round_cap_or_no_batch(
    journey: _RunOutcome,
) -> None:
    manifest = journey.result.manifest
    assert manifest.campaign_id == journey.result.campaign_id
    assert manifest.node_count == 4
    assert manifest.theme_roots == 2
    assert manifest.depth_max == 2
    assert manifest.calibration_status == "ok"

    assert journey.result.stop_reason in (STOP_ROUND_CAP, STOP_NO_BATCH)
    assert {CHILD_OK_ID, GRANDCHILD_OK_ID} <= set(journey.result.nodes)

    for event in journey.events:
        json.dumps(event)


# ── A second run, whose policy answers no batch at once ─────────────────────


def test_a_second_run_with_a_policy_that_answers_no_batch_stops_after_the_roots(
    _world: _World,
    _ids_patch: pytest.MonkeyPatch,
    _captured_responses: Any,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    _reset_root_ids(_ids_patch)
    tmp = tmp_path_factory.mktemp("live-campaign-e2e-no-batch")
    outcome = _run_campaign_once(
        world=_world, tmp=tmp,
        resolve=lambda pin: providers.RecordedProvider(_captured_responses),
        policy=_EmptyBatchPolicy(),
    )

    assert outcome.result.roots == (ROOT_OK_ID, ROOT_FAIL_ID)
    assert outcome.result.stop_reason == STOP_NO_BATCH
    assert outcome.result.rounds_run == 0
    assert outcome.result.nodes == ()

    for node_id in (ROOT_OK_ID, ROOT_FAIL_ID):
        answer = outcome.evaluations[node_id]
        assert answer.metrics is not None or answer.fail_class is not None
        rows = [r for r in outcome.ledger.rows() if r.node_id == node_id]
        assert len(rows) == 1

