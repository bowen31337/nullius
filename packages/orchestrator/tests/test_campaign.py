"""Feature 6, the campaign loop — plant, seal, evaluate the roots, then loop.

additions_spec_campaign_driver.xml, "Campaign Loop" category, feature 6:
*System runs one campaign with orchestrator._campaign.run_campaign(*,
campaign_type, workspaces, rounds, width, allowance, author, evaluator,
policy, context, sidecar_selection, emit), and it creates a
CampaignResult(campaign_id, roots, nodes, rounds_run, stop_reason,
manifest).*  Every collaborator this spec names is either real (discovery's
campaign, batching and retry seams; the real
:func:`~orchestrator._roots.plant_root`, the real
:class:`~orchestrator._worker.NodeWorker`, a real
``signal_agent.ProposalHistoryStore``) or a fake the spec names explicitly
(the author, the evaluator, the policy and the sidecar selection) — so this
suite runs the real seams against a throwaway, fully migrated SQLite
database and fakes only the four collaborators the feature says to fake.

One test per claim the feature sentence makes:

* **plant, seal, evaluate, then expand across rounds** — the roots land as
  depth-0 rows before the sidecar is sealed, every root is evaluated and its
  proposal persisted beside its score, and the round loop expands the tree
  two more levels before the round cap stops it.
* **the policy answering an empty batch stops the campaign** — ``no_batch``.
* **an already-exhausted statistical budget stops the campaign before a
  batch is even selected** — ``budget_exhausted``, and the policy is never
  asked.
* **a token-budget error on a round's result stops the campaign** —
  ``token_budget``, read off the batch's own result rather than caught
  directly.
* **an authoring refusal inside the round loop is a failed attempt, not a
  crash** — the round continues, the refused child counts as a node but
  contributes no depth record.
* **an interruption that never recovers costs no outcome, and the round
  still completes** — ``discovery.WorkerInterrupted`` exhausting its
  retries stands interrupted, which is not a token-budget error.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Each test takes a fresh SQLite file
(never ``sqlite://`` in-memory), the same reason the sibling orchestrator
suites give.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import discovery
import providers
import pytest
import signal_agent
from orchestrator._campaign import (
    STOP_BUDGET_EXHAUSTED,
    STOP_NO_BATCH,
    STOP_ROUND_CAP,
    STOP_TOKEN_BUDGET,
    CampaignResult,
    run_campaign,
)
from policy_runtime import UNBOUNDED_BUDGET

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, and the migrations live beside it
# under migrations/versions — the same resolution test_worker.py and
# test_roots.py use.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"

#: The assembled chain the tree's columns fill, in the order the chain
#: actually widens it — ``0118`` creates ``node`` empty, and only then do
#: ``0117``-``0114`` add their ``NOT NULL`` columns.
NODE_TABLE_MIGRATIONS = (
    "0118_node_table",
    "0117_identity_trio",
    "0116_provenance_trio",
    "0115_agent_model_trio",
    "0114_node_metrics",
)

SOURCE = "def signal(ctx):\n    return ctx.close.pct_change(20)\n"
PROPOSAL = "Mechanism: fades crowded carry.\n```python\n" + SOURCE + "```\n"

#: Real, well-formed pins — the same literals
#: packages/orchestrator/tests/test_roots.py and test_worker.py already
#: exercise, reused here rather than invented.
ROOT_PIN = providers.ModelPin("deepseek", "deepseek-v4-flash", "20260910")
DEPTH_PIN = providers.ModelPin("anthropic", "claude-opus-5", "20260401")
SAMPLING = providers.AgentSampling(temperature=0.4, seed=7)
USAGE = providers.Usage(input_tokens=1_000, output_tokens=200)

#: A single-member frontier tier naming exactly :data:`ROOT_PIN`'s own
#: family.  ``providers.record_authoring``'s root path checks the serving
#: family the record reports against the family the rotation assigned, and
#: a tier of one member is always assigned to itself — the only shape that
#: lets every root in this suite record cleanly regardless of the hash
#: ``rotation_index`` draws.
ROOT_TIER = providers.FrontierTier(
    providers=(providers.FrontierProvider(ROOT_PIN.provider, ROOT_PIN.model),)
)


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner."""
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the campaign and "
            "node tables' own migrations rather than hand-writing their DDL"
        )
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_campaign_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'campaign-loop-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


class _Context:
    """The subset of ``orchestrator._context.EvaluationContext`` this spec reads.

    Rather than the full record — which also demands a mounted snapshot and
    a loaded cost model neither ``run_campaign`` nor anything it calls ever
    touches — this fake carries only the six attributes actually read: the
    provenance trio, the database URL, the artifact directory and the
    evaluation grid's length (``evaluation_periods``, for
    :func:`~orchestrator._live_tree.live_question`).
    """

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


# -- The fakes the feature names explicitly --------------------------------------


class SequenceAuthor:
    """``author.author_root`` for planting, ``author(workspace)`` for expansion.

    One fixed source and proposal text throughout: conflicts in
    ``signal_agent.ProposalHistoryStore`` are keyed by node id, and every
    node this suite plants or expands has a distinct one, so identical text
    across them is never a conflict.
    """

    def __init__(self) -> None:
        self.root_calls: list[tuple[str, str, str]] = []
        self.expand_calls: list[Any] = []

    def author_root(self, campaign_id: str, theme_root: str, *, root_id: Any) -> Any:
        self.root_calls.append((campaign_id, theme_root, str(root_id)))
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
            code=SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=PROPOSAL,
            record=record,
        )

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
            usage=USAGE,
            served_model=DEPTH_PIN.model,
        )
        return SimpleNamespace(
            code=SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=PROPOSAL,
            record=record,
        )

    @property
    def first_root_id(self) -> str:
        return self.root_calls[0][2]


class RefusingRootAuthor(SequenceAuthor):
    """Every root authoring call is refused; round-loop expansion is unused."""

    def author_root(self, campaign_id: str, theme_root: str, *, root_id: Any) -> Any:
        self.root_calls.append((campaign_id, theme_root, str(root_id)))
        raise signal_agent.AuthoringRefusedError(
            "authoring_refused: the model's answer was shown the defect and "
            "refused again each time"
        )


class TokenBudgetRoundAuthor(SequenceAuthor):
    """Plants roots normally; every round-loop expansion spends the pin's budget."""

    def __call__(self, workspace: Any) -> Any:
        self.expand_calls.append(workspace)
        raise providers.BudgetExhaustedError(
            "budget_exhausted: the pin's running total has met its ceiling"
        )


class RefusingRoundAuthor(SequenceAuthor):
    """Plants roots normally; every round-loop expansion is refused."""

    def __call__(self, workspace: Any) -> Any:
        self.expand_calls.append(workspace)
        raise signal_agent.AuthoringRefusedError(
            "authoring_refused: the model's answer was shown the defect and "
            "refused again each time"
        )


class InterruptedRoundAuthor(SequenceAuthor):
    """Plants roots normally; every round-loop expansion is reclaimed."""

    def __call__(self, workspace: Any) -> Any:
        self.expand_calls.append(workspace)
        raise discovery.WorkerInterrupted(
            "the sandbox child died to the provider's reclaim signal"
        )


class FakeEvaluator:
    """A fake evaluator answering one fixed evaluation.

    ``score`` is a real ``signal_agent.ScoreRecord`` rather than a bare
    value: ``ProposalHistoryStore.persist`` validates it is one (or
    ``None``) before it ever reaches this module, the same way a live
    evaluator's own answer always is.
    """

    def __init__(
        self,
        *,
        fail_class: str | None = None,
        score: Any = None,
        charges_budget: bool = True,
    ) -> None:
        self.calls: list[tuple[Any, Any, Any, Any]] = []
        self._fail_class = fail_class
        self._score = (
            signal_agent.ScoreRecord(ic_mean=0.1, ic_tstat=2.0, fail_class=fail_class)
            if score is None
            else score
        )
        self._charges_budget = charges_budget

    def evaluate(self, node_id: Any, campaign_id: Any, depth: Any, code: Any) -> Any:
        self.calls.append((node_id, campaign_id, depth, code))
        return SimpleNamespace(
            node_id=node_id,
            fail_class=self._fail_class,
            score=self._score,
            charges_budget=self._charges_budget,
        )


class FakeSidecarSelection:
    """Records every ``persist`` call — the Type-R seal this spec never reads."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def persist(self, campaign_id: str) -> None:
        self.calls.append(campaign_id)


class StagedPolicy:
    """Answers one pre-programmed batch per round, built lazily from live state.

    Each stage is a zero-argument callable rather than a literal list,
    because a root's id is minted by ``run_campaign`` itself
    (``uuid.uuid4()``) and is not known until after planting — by which
    time the first round's ``select`` is the first thing that reads it, so
    a stage reads it off the author's own recorded calls at call time.
    Every call past the configured stages answers ``[]``.
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


class NeverCalledPolicy:
    """Proves the round loop never asks the policy once the budget is spent."""

    def select(self, prefix_view: Any) -> list[str]:
        raise AssertionError(
            "policy.select was called although the statistical budget was "
            "already exhausted before this round built a batch"
        )


def _recording_emit() -> tuple[list[dict[str, Any]], Callable[[dict[str, Any]], None]]:
    events: list[dict[str, Any]] = []
    return events, events.append


def _cache_rate_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Wrap ``providers.record_campaign_cache_rate`` with a call-recording spy.

    ``_campaign.py`` calls it as ``providers.record_campaign_cache_rate(...)``
    (an attribute read at call time, never imported by name), so patching the
    attribute on the live ``providers`` module is what this seam's call site
    actually sees.
    """
    calls: list[tuple[str, int]] = []
    original = providers.record_campaign_cache_rate

    def spy(campaign_id: Any, records: Any, *, database_url: Any = None, env: Any = None) -> Any:
        materialized = list(records)
        calls.append((campaign_id, len(materialized)))
        return original(campaign_id, materialized, database_url=database_url, env=env)

    monkeypatch.setattr(providers, "record_campaign_cache_rate", spy)
    return calls


# -- Plant, seal, evaluate, then expand across the round cap --------------------


def test_run_campaign_plants_seals_evaluates_and_expands_to_the_round_cap(
    context: _Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    author = SequenceAuthor()
    evaluator = FakeEvaluator(fail_class=None, charges_budget=True)
    sidecar = FakeSidecarSelection()
    events, emit = _recording_emit()
    cache_rate_calls = _cache_rate_spy(monkeypatch)

    policy = StagedPolicy(
        [
            lambda: [author.first_root_id],
            lambda: [discovery.refined_node_id(author.first_root_id)],
        ]
    )

    result = run_campaign(
        campaign_type="Type-D",
        workspaces=1,
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

    root_id = author.first_root_id
    child_1 = discovery.refined_node_id(root_id)
    child_2 = discovery.refined_node_id(child_1)

    assert isinstance(result, CampaignResult)
    assert result.campaign_id
    assert result.roots == (root_id,)
    assert result.nodes == (child_1, child_2)
    assert result.rounds_run == 2
    assert result.stop_reason == STOP_ROUND_CAP

    # The seal ran after the one root was planted and before the first
    # evaluate call — a single root and a single seal leave no ordering to
    # infer except "the seal happened", which this assertion and the
    # evaluator's own three calls (root, child 1, child 2) together pin.
    assert sidecar.calls == [result.campaign_id]
    assert len(evaluator.calls) == 3
    assert evaluator.calls[0] == (root_id, result.campaign_id, 0, SOURCE)
    assert evaluator.calls[1][1:] == (result.campaign_id, 1, SOURCE)
    assert evaluator.calls[2][1:] == (result.campaign_id, 2, SOURCE)

    # The manifest is the real discovery.finish_campaign answer, read back
    # from the table it wrote: three nodes (the root and its two
    # descendants), one theme, depth 2.
    assert result.manifest.campaign_id == result.campaign_id
    assert result.manifest.calibration_status == "ok"
    assert result.manifest.node_count == 3
    assert result.manifest.depth_max == 2
    assert result.manifest.theme_roots == 1

    # The depth tier's cache rate was measured over the two round-loop
    # records (the root's own record is role "root" and is never part of
    # this count).
    assert cache_rate_calls == [(result.campaign_id, 2)]

    assert [e["event"] for e in events] == [
        "root_planted",
        "node_evaluated",
        "node_evaluated",
        "round",
        "node_evaluated",
        "round",
        "summary",
    ]
    assert events[0]["node_id"] == root_id
    assert events[0]["theme_root"]
    assert events[-1]["stop_reason"] == STOP_ROUND_CAP
    assert events[-1]["manifest"]["node_count"] == 3

    # Every emitted event is JSON-ready, the feature's own word for it —
    # not merely "looks like a dict", but something json.dumps actually
    # accepts without a custom encoder.
    for event in events:
        json.dumps(event)


# -- The policy answering no batch -----------------------------------------------


def test_an_empty_batch_stops_the_campaign_with_no_batch(context: _Context) -> None:
    author = SequenceAuthor()
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    events, emit = _recording_emit()

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
    assert result.nodes == ()
    assert len(author.expand_calls) == 0
    assert [e["event"] for e in events][-2:] == ["round", "summary"]
    assert events[-2]["stop_reason"] == STOP_NO_BATCH
    assert events[-2]["batch_size"] == 0


# -- The statistical budget, already spent ---------------------------------------


def test_an_exhausted_statistical_budget_stops_before_a_batch_is_selected(
    context: _Context,
) -> None:
    author = SequenceAuthor()
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    events, emit = _recording_emit()

    result = run_campaign(
        campaign_type="Type-D",
        workspaces=1,
        rounds=3,
        width=1,
        allowance=0,
        author=author,
        evaluator=evaluator,
        policy=NeverCalledPolicy(),
        context=context,
        sidecar_selection=sidecar,
        emit=emit,
    )

    assert result.stop_reason == STOP_BUDGET_EXHAUSTED
    assert result.rounds_run == 0
    assert result.nodes == ()
    assert [e["event"] for e in events][-2:] == ["round", "summary"]
    assert events[-2]["stop_reason"] == STOP_BUDGET_EXHAUSTED


# -- A token-budget error on a round's result ------------------------------------


def test_a_token_budget_error_stops_the_round_loop(context: _Context) -> None:
    author = TokenBudgetRoundAuthor()
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    events, emit = _recording_emit()
    policy = StagedPolicy([lambda: [author.first_root_id]])

    result = run_campaign(
        campaign_type="Type-D",
        workspaces=1,
        rounds=3,
        width=1,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=policy,
        context=context,
        sidecar_selection=sidecar,
        emit=emit,
    )

    assert result.stop_reason == STOP_TOKEN_BUDGET
    assert result.rounds_run == 1
    # The worker's call raised before it ever answered a ChildOutcome, so
    # there is no node id this round could report.
    assert result.nodes == ()
    assert len(author.expand_calls) == 1
    round_events = [e for e in events if e["event"] == "round"]
    assert round_events[-1]["stop_reason"] == STOP_TOKEN_BUDGET


# -- An authoring refusal inside the round loop ----------------------------------


def test_an_authoring_refusal_in_the_round_loop_is_a_failed_attempt_not_a_crash(
    context: _Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    author = RefusingRoundAuthor()
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    events, emit = _recording_emit()
    cache_rate_calls = _cache_rate_spy(monkeypatch)
    policy = StagedPolicy([lambda: [author.first_root_id]])

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

    refused_child = discovery.refined_node_id(author.first_root_id)
    assert result.stop_reason == STOP_ROUND_CAP
    assert result.rounds_run == 1
    assert result.nodes == (refused_child,)

    node_events = [e for e in events if e["event"] == "node_evaluated"]
    assert node_events[-1]["node_id"] == refused_child
    assert node_events[-1]["fail_class"] == "authoring_refused"

    # No depth record exists (the refusal carries none), so the depth
    # tier's cache rate is never measured.
    assert cache_rate_calls == []


def test_a_root_authoring_refusal_propagates_uncaught(context: _Context) -> None:
    """Feature 1: root refusals are "unchanged" — unlike a round-loop expansion
    (which ``NodeWorker`` catches and records as a failed attempt), a root has
    no tree row and no derived id to record a failure against until
    ``author.author_root`` has actually answered one, so the refusal is this
    module's to let through rather than to launder into a partial root.
    """
    author = RefusingRootAuthor()
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    _events, emit = _recording_emit()

    with pytest.raises(signal_agent.AuthoringRefusedError):
        run_campaign(
            campaign_type="Type-D",
            workspaces=1,
            rounds=1,
            width=1,
            allowance=UNBOUNDED_BUDGET,
            author=author,
            evaluator=evaluator,
            policy=EmptyBatchPolicy(),
            context=context,
            sidecar_selection=sidecar,
            emit=emit,
        )

    # Nothing was planted or evaluated before the refusal.
    assert evaluator.calls == []
    assert sidecar.calls == []


# -- An interruption that never recovers -----------------------------------------


def test_an_exhausted_interruption_costs_no_outcome_and_the_round_still_completes(
    context: _Context,
) -> None:
    author = InterruptedRoundAuthor()
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    _events, emit = _recording_emit()
    policy = StagedPolicy([lambda: [author.first_root_id]])

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

    # Every re-run (the original attempt plus _RETRIES retries) raised the
    # same interruption, so the job stands interrupted and answers no
    # ChildOutcome — but the round itself completed (the loop reached its
    # own cap rather than crashing), and nothing claims a token-budget stop.
    assert result.stop_reason == STOP_ROUND_CAP
    assert result.rounds_run == 1
    assert result.nodes == ()
    assert len(author.expand_calls) == 3


# -- The module's surface ---------------------------------------------------------


def test_the_module_exports_the_result_the_verb_and_the_four_stop_reasons() -> None:
    from orchestrator import _campaign

    assert set(_campaign.__all__) == {
        "STOP_BUDGET_EXHAUSTED",
        "STOP_NO_BATCH",
        "STOP_ROUND_CAP",
        "STOP_TOKEN_BUDGET",
        "CampaignResult",
        "run_campaign",
    }
    assert callable(_campaign.run_campaign)
    assert {
        _campaign.STOP_NO_BATCH,
        _campaign.STOP_BUDGET_EXHAUSTED,
        _campaign.STOP_TOKEN_BUDGET,
        _campaign.STOP_ROUND_CAP,
    } == {"no_batch", "budget_exhausted", "token_budget", "round_cap"}


# -- The score-rendering helper, directly ----------------------------------------


def test_json_score_renders_a_real_score_record_a_dataclass_and_a_plain_value() -> None:
    from orchestrator._campaign import _json_score

    assert _json_score(None) is None
    assert _json_score("already-json-ready") == "already-json-ready"

    score = signal_agent.ScoreRecord(ic_mean=0.1, fail_class=None)
    rendered = _json_score(score)
    assert rendered["ic_mean"] == 0.1
    assert rendered["fail_class"] is None
