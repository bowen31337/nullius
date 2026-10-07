"""bug_spec_first_scored_campaign.xml, bug 2: the campaign's cache-hit-rate record.

Campaign 9a955be6 ran 2 rounds and made 8 authoring calls (8 rows in
``provider_call_usage``), then exited 1: ``orchestrator._campaign`` handed
``providers.record_campaign_cache_rate`` an empty ``records`` collection and
let its refusal escape. The round loop only ever collected a depth record
for a *successful* authoring (``ChildOutcome.record``); an authoring call
that reached the provider and was billed but was then refused by
signal_agent's own validation (every retry's answer failed the gate) leaves
``ChildOutcome.record is None`` — real spend, no record of it reaching this
module's own collection.

One test per claim the bug's ``<expected>`` makes:

* a campaign whose round loop collected no depth records, but whose
  ``provider_call_usage`` rows show real depth-role calls, still persists a
  cache rate — equal to those calls' summed cache reads over summed input,
  root-role usage excluded.
* a campaign that made no depth-role calls at all is skipped with one
  logged line, and ``run_campaign`` answers normally rather than raising.
* a cache-rate store failure is logged and swallowed — the campaign's
  result and ``stop_reason`` are unchanged, and nothing escapes
  ``run_campaign``.

Fixtures are deliberately not imported from test_campaign.py — this suite is
conftest-less, like its siblings (see that module's own docstring) — so each
test takes a fresh SQLite file via ``tmp_path``, never ``sqlite://``
in-memory, and runs cleanly under pytest-xdist. Every round-loop batch in
this file is ``width=1``: the fakes below index their own call count to
decide which prepared usage to bill, and a wider, concurrently-dispatched
batch would race that count.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import logging
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import discovery
import nulloracle
import providers
import pytest
import signal_agent
from orchestrator._campaign import STOP_NO_BATCH, STOP_ROUND_CAP, run_campaign
from orchestrator.campaign import EXIT_OK as CLI_EXIT_OK
from orchestrator.campaign import LIVE_EVALUATOR_COMPONENT_NAME
from orchestrator.campaign import main as campaign_main
from policy_runtime import UNBOUNDED_BUDGET

from app.module_loader import Application

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"

#: The assembled chain the tree's columns fill, in the order the chain
#: actually widens it — the same list test_campaign.py's own fixture uses.
NODE_TABLE_MIGRATIONS = (
    "0118_node_table",
    "0117_identity_trio",
    "0116_provenance_trio",
    "0115_agent_model_trio",
    "0114_node_metrics",
)

SOURCE = "def signal(ctx):\n    return ctx.close.pct_change(20)\n"
PROPOSAL = "Mechanism: fades crowded carry.\n```python\n" + SOURCE + "```\n"

ROOT_PIN = providers.ModelPin("deepseek", "deepseek-v4-flash", "20260910")
DEPTH_PIN = providers.ModelPin("anthropic", "claude-opus-5", "20260401")
SAMPLING = providers.AgentSampling(temperature=0.4, seed=7)
ROOT_USAGE = providers.Usage(input_tokens=1_000, output_tokens=200)

ROOT_TIER = providers.FrontierTier(
    providers=(providers.FrontierProvider(ROOT_PIN.provider, ROOT_PIN.model),)
)


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the campaign and "
            "node tables' own migrations rather than hand-writing their DDL"
        )
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_cache_rate_usage_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'cache-rate-usage-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


class _Context:
    """The subset of ``orchestrator._context.EvaluationContext`` this spec reads."""

    def __init__(self, database_url: str, artifact_dir: Path) -> None:
        self.database_url = database_url
        self.evaluator_hash = hashlib.sha256(b"evaluator").hexdigest()
        self.snapshot_hash = hashlib.sha256(b"snapshot").hexdigest()
        self.cost_model_hash = hashlib.sha256(b"cost-model").hexdigest()
        self.artifact_dir = artifact_dir
        self.evaluation_dates = (dt.date(2026, 1, 2), dt.date(2026, 1, 3))


@pytest.fixture
def context(tree_database: str, tmp_path: Path) -> _Context:
    return _Context(tree_database, tmp_path / "artifacts")


# -- The fakes --------------------------------------------------------------------


class RootOnlyAuthor:
    """Plants roots normally; a subclass decides what the round loop does.

    ``author_root`` also bills a root-role ``provider_call_usage`` row for
    every root, the same side effect a live ``AuthoringSession`` wrapped in
    ``UsageRecordingProvider`` leaves — skewed hard (a large input, zero
    cache read) so a test that folded it into the depth-role measurement by
    mistake would answer a visibly wrong rate, not a coincidentally right
    one.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self.root_calls: list[tuple[str, str, str]] = []

    def author_root(self, campaign_id: str, theme_root: str, *, root_id: Any) -> Any:
        self.root_calls.append((campaign_id, theme_root, str(root_id)))
        providers.UsageStore(self._database_url).record(
            campaign_id=campaign_id,
            role="root",
            pin=ROOT_PIN,
            served_model=ROOT_PIN.model,
            input_tokens=50_000,
            cache_read_tokens=0,
            outcome="ok",
            duration_ms=5,
        )
        record = providers.AuthoringRecord(
            node_id=str(root_id),
            campaign_id=campaign_id,
            depth=0,
            role="root",
            pin=ROOT_PIN,
            sampling=SAMPLING,
            usage=ROOT_USAGE,
            served_model=ROOT_PIN.model,
            tier=ROOT_TIER,
        )
        return SimpleNamespace(
            code=SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=PROPOSAL,
            record=record,
        )

    def __call__(self, workspace: Any) -> Any:  # pragma: no cover - a trap
        raise AssertionError("the round loop is never reached in this test")

    def root_id(self, index: int) -> str:
        return self.root_calls[index][2]


class BilledThenRefusedAuthor(RootOnlyAuthor):
    """Every round-loop expansion bills a real usage row, then is refused.

    The exact shape campaign 9a955be6 hit: in a live deployment,
    ``providers.UsageRecordingProvider`` writes the ``provider_call_usage``
    row the moment the completion comes back — before signal_agent's own
    validation ever looks at what it said. A call shown its own defect and
    refused on every retry still leaves that row behind, and
    ``NodeWorker`` answers ``ChildOutcome(record=None)`` for it. This fake
    writes the row itself (standing in for the recording provider a bare
    callable author never wraps) and then raises
    ``AuthoringRefusedError``, the same two facts in the same order.
    """

    def __init__(self, database_url: str, usages: list[providers.Usage]) -> None:
        super().__init__(database_url)
        self._usages = list(usages)
        self.expand_calls: list[Any] = []

    def __call__(self, workspace: Any) -> Any:
        usage = self._usages[len(self.expand_calls)]
        self.expand_calls.append(workspace)
        providers.UsageStore(self._database_url).record(
            campaign_id=workspace.campaign_id,
            role="depth",
            pin=DEPTH_PIN,
            served_model=DEPTH_PIN.model,
            input_tokens=usage.input_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            output_tokens=usage.output_tokens,
            outcome="ok",
            duration_ms=5,
        )
        raise signal_agent.AuthoringRefusedError(
            "authoring_refused: the model's answer was shown the defect "
            "and refused again each time"
        )


class SequenceAuthor(RootOnlyAuthor):
    """A round-loop expansion that always succeeds — the pre-bug, working path."""

    def __init__(self, database_url: str) -> None:
        super().__init__(database_url)
        self.expand_calls: list[Any] = []

    def __call__(self, workspace: Any) -> Any:
        self.expand_calls.append(workspace)
        child_id = discovery.refined_node_id(workspace.node_id)
        record = providers.AuthoringRecord(
            node_id=child_id,
            campaign_id=workspace.campaign_id,
            depth=workspace.depth + 1,
            role="depth",
            pin=DEPTH_PIN,
            sampling=SAMPLING,
            usage=providers.Usage(input_tokens=500, output_tokens=50),
            served_model=DEPTH_PIN.model,
        )
        return SimpleNamespace(
            code=SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=PROPOSAL,
            record=record,
        )


class FakeEvaluator:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, Any, Any]] = []

    def evaluate(self, node_id: Any, campaign_id: Any, depth: Any, code: Any) -> Any:
        self.calls.append((node_id, campaign_id, depth, code))
        return SimpleNamespace(
            node_id=node_id,
            fail_class=None,
            score=signal_agent.ScoreRecord(ic_mean=0.1, ic_tstat=2.0, fail_class=None),
            charges_budget=True,
        )


class FakeSidecarSelection:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def persist(self, campaign_id: str) -> None:
        self.calls.append(campaign_id)


class StagedPolicy:
    """Answers one pre-programmed batch per round; ``[]`` past the last stage.

    Each stage is a zero-argument callable, the same ``test_campaign.py``
    precedent: a root's id is minted by ``run_campaign`` itself
    (``uuid.uuid4()``), not known until after planting, so a stage reads it
    off the author's own recorded calls at call time.
    """

    def __init__(self, stages: list[Callable[[], list[str]]]) -> None:
        self._stages = list(stages)
        self.calls = 0

    def select(self, prefix_view: Any) -> list[str]:
        batch = self._stages[self.calls]() if self.calls < len(self._stages) else []
        self.calls += 1
        return list(batch)


class EmptyBatchPolicy:
    def select(self, prefix_view: Any) -> list[str]:
        return []


def _recording_emit() -> tuple[list[dict[str, Any]], Callable[[dict[str, Any]], None]]:
    events: list[dict[str, Any]] = []
    return events, events.append


# -- A campaign whose depth calls were all billed, then refused -----------------


def test_a_campaign_with_billed_but_refused_calls_persists_the_honest_rate(
    context: _Context,
) -> None:
    usages = [
        providers.Usage(input_tokens=1_000, output_tokens=50, cache_read_tokens=400),
        providers.Usage(input_tokens=2_000, output_tokens=80, cache_read_tokens=1_600),
    ]
    author = BilledThenRefusedAuthor(context.database_url, usages)
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    events, emit = _recording_emit()
    # width=1: one parent expanded per round, so the fake's own call count
    # unambiguously picks which prepared usage it bills.
    policy = StagedPolicy(
        [lambda: [author.root_id(0)], lambda: [author.root_id(1)]]
    )

    result = run_campaign(
        campaign_type="Type-D",
        workspaces=2,
        rounds=2,
        width=1,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=policy,
        context=context,
        sidecar_selection=sidecar,
        emit=emit,
    )

    assert result.stop_reason == STOP_ROUND_CAP
    assert result.rounds_run == 2
    assert len(author.expand_calls) == 2

    # Both round-loop attempts were refused — the exact bug: real spend,
    # no ChildOutcome.record.
    refused = [e for e in events if e["event"] == "node_evaluated" and e["depth"] == 1]
    assert len(refused) == 2
    assert all(e["fail_class"] == "authoring_refused" for e in refused)

    measured = providers.DepthCacheRates(context.database_url).get(result.campaign_id)
    assert measured is not None
    # The two depth-role usages' sums -- the two root-role rows (50,000
    # input each, cache_read 0) are excluded, or this total would be wildly
    # larger and the rate near zero instead of 2/3.
    assert measured.input_tokens == 3_000
    assert measured.cache_read_tokens == 2_000
    assert measured.hit_rate == Fraction(2, 3)


# -- A campaign that made no depth-role calls at all -----------------------------


def test_a_zero_depth_call_campaign_is_skipped_and_run_campaign_does_not_raise(
    context: _Context, caplog: pytest.LogCaptureFixture
) -> None:
    author = RootOnlyAuthor(context.database_url)
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    _events, emit = _recording_emit()

    with caplog.at_level(logging.INFO, logger="orchestrator._campaign"):
        result = run_campaign(
            campaign_type="Type-D",
            workspaces=1,
            rounds=3,
            width=1,
            allowance=UNBOUNDED_BUDGET,
            author=author,
            evaluator=evaluator,
            policy=EmptyBatchPolicy(),
            context=context,
            sidecar_selection=sidecar,
            emit=emit,
        )

    assert result.stop_reason == STOP_NO_BATCH
    assert result.rounds_run == 0

    # The one root-role usage row RootOnlyAuthor.author_root billed is not
    # a depth-role call, so there is nothing to measure.
    assert providers.DepthCacheRates(context.database_url).get(result.campaign_id) is None
    assert any(
        "no depth-role authoring calls" in record.message
        and result.campaign_id in record.message
        for record in caplog.records
    )


class _LiveEvaluatorDouble:
    """The ``"live-evaluator"`` component's own two faces, for the CLI test below.

    Writes nothing to the node table itself (the same stance
    test_campaign_cli.py's own double takes), so the real baseline
    exploration policy ``orchestrator.campaign.main`` loads when no
    ``NULLIUS_EXPLORATION_POLICY`` is set sees no node it can rank and
    answers an empty batch — ``STOP_NO_BATCH``, the real CLI path to a
    campaign that made no depth-role calls at all.
    """

    def __init__(self, context: _Context) -> None:
        self.context = context

    def evaluate(self, node_id: Any, campaign_id: Any, depth: Any, code: Any) -> Any:
        return SimpleNamespace(
            node_id=node_id,
            fail_class=None,
            score=signal_agent.ScoreRecord(ic_mean=0.1, ic_tstat=2.0, fail_class=None),
            charges_budget=True,
        )


def _cli_app(*, author: Any, evaluator: Any, sidecar_selection: Any) -> Application:
    components = {
        signal_agent.SIGNAL_AUTHOR_COMPONENT_NAME: author,
        LIVE_EVALUATOR_COMPONENT_NAME: evaluator,
        nulloracle.TYPE_R_COMPONENT_NAME: sidecar_selection,
    }
    return Application(components=components, order=tuple(sorted(components)))


def test_the_cli_exits_0_for_a_campaign_with_no_depth_role_calls(
    context: _Context, caplog: pytest.LogCaptureFixture
) -> None:
    """The bug's own reproduction is CLI-level ("the CLI exits 1"); this is
    its mirror through the real door, ``orchestrator.campaign.main`` —
    ``--no-closeout`` so this test stands up no sidecar or scorer, the
    same seam test_campaign_cli.py's own close-out tests take.
    """
    author = RootOnlyAuthor(context.database_url)
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _cli_app(author=author, evaluator=evaluator, sidecar_selection=sidecar)
    lines: list[str] = []

    with caplog.at_level(logging.INFO, logger="orchestrator._campaign"):
        code = campaign_main(
            ["--type", "Type-D", "--workspaces", "1", "--rounds", "3", "--width", "1", "--no-closeout"],
            env={},
            app=app,
            emit=lines.append,
        )

    assert code == CLI_EXIT_OK
    events = [json.loads(line) for line in lines]
    summary = events[-1]
    assert summary["event"] == "summary"
    assert summary["stop_reason"] == STOP_NO_BATCH

    assert providers.DepthCacheRates(context.database_url).get(summary["campaign_id"]) is None
    assert any(
        "no depth-role authoring calls" in record.message
        and summary["campaign_id"] in record.message
        for record in caplog.records
    )


# -- A cache-rate store failure never escapes run_campaign -----------------------


def test_a_cache_rate_store_failure_is_logged_and_never_fails_the_campaign(
    context: _Context,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    author = SequenceAuthor(context.database_url)
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    _events, emit = _recording_emit()
    policy = StagedPolicy([lambda: [author.root_id(0)]])

    def _raise_store_failure(*args: Any, **kwargs: Any) -> Any:
        raise providers.DepthCacheError("simulated cache-rate store failure")

    monkeypatch.setattr(providers, "record_campaign_cache_rate", _raise_store_failure)

    with caplog.at_level(logging.WARNING, logger="orchestrator._campaign"):
        result = run_campaign(
            campaign_type="Type-D",
            workspaces=1,
            rounds=1,
            width=1,
            allowance=UNBOUNDED_BUDGET,
            author=author,
            evaluator=evaluator,
            policy=policy,
            context=context,
            sidecar_selection=sidecar,
            emit=emit,
        )

    # The campaign's own result and stop_reason stand, exactly as they
    # would have had the cache-rate store never been asked.
    assert result.stop_reason == STOP_ROUND_CAP
    assert result.rounds_run == 1
    assert len(result.nodes) == 1

    assert providers.DepthCacheRates(context.database_url).get(result.campaign_id) is None
    assert any(
        "could not be measured or recorded" in record.message
        and result.campaign_id in record.message
        for record in caplog.records
    )
