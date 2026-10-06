"""Feature 1 of spec D, campaign resume — continuing, never replanting.

additions_spec_campaign_gaps.xml, "Campaign Driver Gaps" category, feature
1: *System resumes an interrupted campaign with
orchestrator._campaign.resume_campaign(campaign_id, *, rounds, width,
allowance, author, evaluator, policy, context, emit), and it answers the
same CampaignResult run_campaign answers, continuing the existing campaign
rather than planting a new one.*  This suite runs the real seams
(``orchestrator._roots.plant_root``, ``discovery.create_campaign``,
``discovery.finish_campaign``, a real migrated SQLite tree) and fakes only
the collaborators ``run_campaign``'s own suite already fakes (the author,
the evaluator, the policy) — ``resume_campaign`` takes no
``sidecar_selection`` at all, since it never reseals Type-R's null draw.

One test per claim the feature sentence makes:

* **a root planted but not yet evaluated is evaluated on resume** — its row
  gains a metric, the step a campaign interrupted between planting and
  evaluating its roots never got to finish.
* **a campaign resumed mid-run grows its node count** — the round loop
  expands the existing frontier exactly as ``run_campaign``'s own would.
* **an unknown campaign_id raises CampaignResumeError** — naming the id,
  before anything is read any further or emitted.
* **a finished campaign resumes to no new node and a stop reason** —
  nothing is replanted, and the round loop's own stop conditions still
  answer one of the four words.
* **resume never creates a campaign and never reseals nulls** — zero calls
  to ``discovery.create_campaign`` and zero calls to a sidecar selection's
  ``persist`` (there being no such parameter to call it through at all).

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Each test takes its own fresh SQLite
file (never ``sqlite://`` in-memory) and mints its own campaign id, so the
suite carries no state across tests and passes under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

import discovery
import providers
import pytest
import signal_agent
from artifacts import ArtifactStore
from orchestrator._campaign import (
    STOP_BUDGET_EXHAUSTED,
    STOP_NO_BATCH,
    STOP_ROUND_CAP,
    STOP_TOKEN_BUDGET,
    CampaignResumeError,
    resume_campaign,
    run_campaign,
)
from orchestrator._roots import plant_root
from policy_runtime import UNBOUNDED_BUDGET

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, and the migrations live beside it
# under migrations/versions — the same resolution test_campaign.py uses.
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
USAGE = providers.Usage(input_tokens=1_000, output_tokens=200)

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
        f"_orchestrator_test_campaign_resume_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'campaign-resume-test.db'}"
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


# -- Raw SQL probes on the tree, for assertions only ------------------------------


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test."""
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _node_row(database_url: str, node_id: str) -> sqlite3.Row | None:
    """Read one node's row back, or ``None`` when the tree holds no such id."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM node WHERE id = ?", (node_id,)
        ).fetchone()


def _node_ids(database_url: str, campaign_id: str) -> frozenset[str]:
    """Every node id a campaign's tree holds, as a set."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        rows = connection.execute(
            "SELECT id FROM node WHERE campaign_id = ?", (campaign_id,)
        ).fetchall()
    return frozenset(row[0] for row in rows)


# -- The fakes run_campaign's own suite already names -----------------------------


class SequenceAuthor:
    """``author.author_root`` for planting, ``author(workspace)`` for expansion.

    Identical shape to ``test_campaign.py``'s own fake: one fixed source and
    proposal text, reused across every root and expansion this suite plants,
    because ``ProposalHistoryStore`` conflicts are keyed by node id and every
    node here has a distinct one.
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


class FakeEvaluator:
    """A fake evaluator answering one fixed evaluation, touching no store.

    Identical to ``test_campaign.py``'s own fake — it never writes a metric
    or a ``fail_class`` onto the ``node`` row, which is exactly why a root
    it evaluated still reads as "unevaluated" to :func:`resume_campaign` on
    a later call: that is the honest state a real evaluator's own *failure*
    path leaves behind too (see ``_campaign.py``'s ``_existing_nodes``
    docstring), so re-evaluating it again is the correct, idempotent answer
    rather than a test artifact to work around.
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


class MetricWritingEvaluator:
    """A fake evaluator that writes ``ic_mean`` onto the node row it evaluates.

    Enough of a real evaluator's own success path (:mod:`orchestrator._evaluate`'s
    ``_persist``, which writes the seven metric columns through one call) to
    let a test observe "this root gained a metric" by reading the row back,
    without standing up the whole evaluation pipeline.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self.calls: list[tuple[Any, Any, Any, Any]] = []

    def evaluate(self, node_id: Any, campaign_id: Any, depth: Any, code: Any) -> Any:
        self.calls.append((node_id, campaign_id, depth, code))
        with closing(sqlite3.connect(_path_of(self._database_url))) as connection, connection:
            connection.execute("UPDATE node SET ic_mean = ? WHERE id = ?", (0.1, node_id))
        return SimpleNamespace(
            node_id=node_id,
            fail_class=None,
            score=signal_agent.ScoreRecord(ic_mean=0.1, ic_tstat=2.0, fail_class=None),
            charges_budget=True,
        )


class FakeSidecarSelection:
    """Records every ``persist`` call — unreachable from ``resume_campaign``,
    which carries no such parameter to call it through.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def persist(self, campaign_id: str) -> None:
        self.calls.append(campaign_id)


class EmptyBatchPolicy:
    def select(self, prefix_view: Any) -> list[str]:
        return []


class StagedPolicy:
    """Answers one pre-programmed batch per round. See test_campaign.py's own."""

    def __init__(self, stages: list[Any]) -> None:
        self._stages = list(stages)
        self.calls = 0

    def select(self, prefix_view: Any) -> list[str]:
        batch = self._stages[self.calls]() if self.calls < len(self._stages) else []
        self.calls += 1
        return list(batch)


def _recording_emit() -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = []
    return events, events.append


# -- Planting a root directly, bypassing run_campaign -----------------------------


def _plant_one_root(context: _Context, author: SequenceAuthor, campaign_id: str) -> str:
    """Plant one root directly, the state a process interrupted right after
    planting — before ``providers.record_authoring`` or any evaluation ever
    ran — would leave the tree in. ``resume_campaign`` is the call that
    picks up from exactly here.
    """
    artifact_store = ArtifactStore(context.artifact_dir)
    authored = author.author_root(campaign_id, "macro", root_id=str(uuid.uuid4()))
    return plant_root(
        campaign_id, "macro", authored, context=context, artifact_store=artifact_store
    )


# -- A root planted but not yet evaluated -----------------------------------------


def test_resume_evaluates_an_unevaluated_root_and_it_gains_a_metric(
    context: _Context,
) -> None:
    record = discovery.create_campaign("Type-D", 1, database_url=context.database_url)
    campaign_id = record.campaign_id
    author = SequenceAuthor()
    root_id = _plant_one_root(context, author, campaign_id)

    # Interrupted between planting and evaluating: the row carries no
    # metric and no fail_class yet.
    before = _node_row(context.database_url, root_id)
    assert before["ic_mean"] is None

    evaluator = MetricWritingEvaluator(context.database_url)
    events, emit = _recording_emit()

    result = resume_campaign(
        campaign_id,
        rounds=0,
        width=1,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=EmptyBatchPolicy(),
        context=context,
        emit=emit,
    )

    assert evaluator.calls == [(root_id, campaign_id, 0, SOURCE)]
    after = _node_row(context.database_url, root_id)
    assert after["ic_mean"] == 0.1
    assert result.roots == (root_id,)
    assert result.campaign_id == campaign_id

    assert events[0] == {
        "event": "campaign_resumed",
        "campaign_id": campaign_id,
        "nodes_present": 1,
    }
    assert [e["event"] for e in events[1:3]] == ["node_evaluated", "summary"]
    assert events[1]["node_id"] == root_id
    assert events[1]["fail_class"] is None


# -- Resuming mid-campaign grows the tree -----------------------------------------


def test_resume_mid_campaign_grows_the_node_count(context: _Context) -> None:
    author = SequenceAuthor()
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    _, emit = _recording_emit()
    policy = StagedPolicy([lambda: [author.first_root_id]])

    initial = run_campaign(
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
    campaign_id = initial.campaign_id
    root_id = author.first_root_id
    child_1 = discovery.refined_node_id(root_id)
    assert initial.nodes == (child_1,)

    before = _node_ids(context.database_url, campaign_id)
    assert before == {root_id, child_1}

    _, resume_emit = _recording_emit()
    resume_policy = StagedPolicy([lambda: [child_1]])

    resumed = resume_campaign(
        campaign_id,
        rounds=1,
        width=1,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=resume_policy,
        context=context,
        emit=resume_emit,
    )

    child_2 = discovery.refined_node_id(child_1)
    after = _node_ids(context.database_url, campaign_id)
    assert after == before | {child_2}
    assert resumed.nodes == (child_2,)
    assert resumed.roots == (root_id,)
    assert resumed.stop_reason == STOP_ROUND_CAP


# -- An unknown campaign_id --------------------------------------------------------


def test_resume_an_unknown_campaign_id_raises_campaign_resume_error(
    context: _Context,
) -> None:
    unknown = str(uuid.uuid4())
    events, emit = _recording_emit()

    with pytest.raises(CampaignResumeError) as excinfo:
        resume_campaign(
            unknown,
            rounds=1,
            width=1,
            allowance=UNBOUNDED_BUDGET,
            author=SequenceAuthor(),
            evaluator=FakeEvaluator(),
            policy=EmptyBatchPolicy(),
            context=context,
            emit=emit,
        )

    assert "campaign_resume" in str(excinfo.value)
    assert unknown in str(excinfo.value)
    assert events == []


# -- A finished campaign ------------------------------------------------------------


def test_resume_a_finished_campaign_creates_no_node_and_returns_a_stop_reason(
    context: _Context,
) -> None:
    author = SequenceAuthor()
    evaluator = FakeEvaluator()
    sidecar = FakeSidecarSelection()
    _, emit = _recording_emit()

    finished = run_campaign(
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
    assert finished.stop_reason == STOP_NO_BATCH
    before = _node_ids(context.database_url, finished.campaign_id)

    _, resume_emit = _recording_emit()
    resumed = resume_campaign(
        finished.campaign_id,
        rounds=3,
        width=1,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=EmptyBatchPolicy(),
        context=context,
        emit=resume_emit,
    )

    after = _node_ids(context.database_url, finished.campaign_id)
    assert after == before
    assert resumed.nodes == ()
    assert resumed.stop_reason in {
        STOP_NO_BATCH,
        STOP_BUDGET_EXHAUSTED,
        STOP_TOKEN_BUDGET,
        STOP_ROUND_CAP,
    }


# -- No fresh campaign, no reseal ---------------------------------------------------


def test_resume_calls_create_campaign_zero_times_and_reseals_zero_times(
    context: _Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = discovery.create_campaign("Type-D", 1, database_url=context.database_url)
    campaign_id = record.campaign_id
    author = SequenceAuthor()
    _plant_one_root(context, author, campaign_id)

    create_campaign_calls: list[tuple[Any, ...]] = []
    original_create_campaign = discovery.create_campaign

    def _spy(*args: Any, **kwargs: Any) -> Any:
        create_campaign_calls.append((args, kwargs))
        return original_create_campaign(*args, **kwargs)

    monkeypatch.setattr(discovery, "create_campaign", _spy)

    sidecar = FakeSidecarSelection()
    evaluator = FakeEvaluator()
    _, emit = _recording_emit()

    resume_campaign(
        campaign_id,
        rounds=0,
        width=1,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=EmptyBatchPolicy(),
        context=context,
        emit=emit,
    )

    assert create_campaign_calls == []
    # resume_campaign has no sidecar_selection parameter at all, so a
    # sidecar never passed to it cannot have been resealed — this asserts
    # the fact rather than merely relying on the signature to enforce it.
    assert sidecar.calls == []
