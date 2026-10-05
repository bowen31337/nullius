"""Feature 5, the worker — one parent, expanded, recorded and evaluated.

additions_spec_campaign_driver.xml, "Campaign Loop" category, feature 5:
*System expands and evaluates one parent node with
orchestrator._worker.NodeWorker(author, evaluator, *, context,
artifact_directory, history_store), and it creates the child's
ChildOutcome(node_id, depth, fail_class, score, charges_budget, record).*
The worker is wiring over three real members this spec may not edit
(discovery's expansion and attempt log, providers' authoring door) and two
fakes the spec names explicitly (the author and the evaluator), so this
suite runs the real seams end to end — a throwaway SQLite tree, brought to
the full chain of migrations an attempt's columns fill, and the real
``artifacts.ArtifactStore`` — and fakes only the two collaborators the
feature says to fake.

One test per claim the feature sentence makes:

* **the happy path** — the parent is expanded into the derived child,
  the attempt lands in the tree with the authoring provenance, the
  authoring record is filed through ``providers.record_authoring``, the
  evaluator is called with the child's id, campaign, depth and code, and
  the proposal is persisted beside its score.
* **an authoring refusal is a failed attempt, never evaluated** — a
  ``signal_agent.AuthoringRefusedError`` lands as a
  ``ChildOutcome(fail_class="authoring_refused", score=None, record=None)``
  naming the derived child, and neither the evaluator nor the history
  store is ever called, and the tree holds no row for it.
* **a budget exhaustion propagates and stops the campaign** —
  ``providers.BudgetExhaustedError`` is not caught here.
* **a worker interruption propagates for retry_interrupted** —
  ``discovery.WorkerInterrupted`` is not caught here either.
* **running the same parent twice is idempotent** — the second call
  answers the same child id, the tree still holds exactly one row for
  it, and the second call's outcome agrees with the first.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Each test takes a fresh SQLite file
(never ``sqlite://`` in-memory), the same reason the sibling orchestrator
suites give: an in-memory database is per-connection, so a row this
test's own setup wrote would be invisible to the module under test.
"""

from __future__ import annotations

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
from artifacts import ArtifactStore
from orchestrator._worker import (
    AUTHORING_REFUSED_FAIL_CLASS,
    ChildOutcome,
    NodeWorker,
)
from signal_agent import AuthoringRefusedError

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up — tests -> orchestrator -> packages ->
# repo root — and the migrations live beside it under migrations/versions,
# exactly as the sibling orchestrator suites (test_live_tree.py,
# test_tree_writer.py) resolve it.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The assembled chain an attempt's columns fill, in the order the chain
#: actually widens the tree — ``0118`` creates ``node`` empty, and only then
#: do ``0117``-``0114`` add their NOT NULL columns, which is legal only on an
#: empty table (the same ordering discovery's own
#: ``packages/discovery/tests/conftest.py`` runs for its
#: ``migrated_with_attempt_columns`` fixture).
NODE_TABLE_MIGRATIONS = (
    "0118_node_table",
    "0117_identity_trio",
    "0116_provenance_trio",
    "0115_agent_model_trio",
    "0114_node_metrics",
)

SOURCE = "def signal(ctx):\n    return ctx.close.pct_change(20)\n"
PROPOSAL = "Mechanism: fades crowded carry.\n```python\n" + SOURCE + "```\n"

#: A real, well-formed pin, sampling and usage — the exact pin string already
#: proven to construct in packages/providers/tests/test_authoring_store.py,
#: reused here rather than invented so this suite is not the first place it
#: is exercised.
PIN = providers.ModelPin("anthropic", "claude-opus-5", "20260401")
SAMPLING = providers.AgentSampling(temperature=0.4)
USAGE = providers.Usage(input_tokens=1_000, output_tokens=200, cache_read_tokens=0)


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner."""
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the node table's "
            "own migrations rather than hand-writing its DDL, so it needs "
            "the schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated.

    Through each migration's own ``apply`` — nothing hand-written — brought
    to exactly the shape ``discovery.AttemptLog`` and
    ``providers.record_authoring`` both write into: the five structural
    columns, the identity/provenance/authoring trios and the seven nullable
    metrics.
    """
    url = f"sqlite:///{tmp_path / 'worker-test.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test."""
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _plant_parent(database_url: str, *, campaign_id: str, theme_root: str = "macro") -> str:
    """Insert one root node (``parent_id`` NULL, ``depth`` 0) directly.

    Raw SQL against the migrated tree rather than any authoring or
    expansion path, because this suite must not acquire a dependency on how
    a root is normally planted (that is feature 2's, not this one's) — the
    point is to produce the *state* a worker resumes, not to reproduce the
    path that makes one. Every ``NOT NULL`` column the migrated table
    actually carries is filled with a placeholder, discovered through
    ``PRAGMA table_info`` so this helper tracks the schema rather than a
    second, hand-maintained list of it — the same discipline
    ``packages/discovery/tests/conftest.py``'s own ``plant_root`` fixture
    follows.
    """
    identifier = str(uuid.uuid4())
    digest = hashlib.sha256(identifier.encode()).hexdigest()
    columns = ["id", "parent_id", "campaign_id", "theme_root", "depth"]
    values: list[object] = [identifier, None, campaign_id, theme_root, 0]
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        shape = {
            str(row[1]): (bool(row[3]), row[4] is not None)
            for row in connection.execute("PRAGMA table_info(node)")
        }
        for name, (not_null, has_default) in shape.items():
            if name in columns or not not_null or has_default:
                continue
            columns.append(name)
            if name.endswith("_hash"):
                values.append(digest)
            else:
                values.append(f"planted-{name}")
        connection.execute(
            f"INSERT INTO node ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
    return identifier


def _node_row(database_url: str, node_id: str) -> sqlite3.Row | None:
    """Read one node's row back, or ``None`` when the tree holds no such id."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute("SELECT * FROM node WHERE id = ?", (node_id,))
        return cursor.fetchone()


# -- The fakes the feature names explicitly ------------------------------------


class FakeAuthor:
    """A fake author answering one fixed, duck-typed ``AuthoredSignal``.

    Fixed per instance (never varying call to call) so a test exercising
    idempotence does not also have to reason about a model's own
    stochastic answer (§10.1) — identity is pinned by the parent, content
    is this fake's to hold constant.
    """

    def __init__(self, *, child_id: str, campaign_id: str, depth: int) -> None:
        self.calls: list[Any] = []
        self.answer = SimpleNamespace(
            code=SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=PROPOSAL,
            record=providers.AuthoringRecord(
                node_id=child_id,
                campaign_id=campaign_id,
                depth=depth,
                role="depth",
                pin=PIN,
                sampling=SAMPLING,
                usage=USAGE,
                served_model=PIN.model,
                tier=None,
            ),
        )

    def __call__(self, workspace: Any) -> Any:
        self.calls.append(workspace)
        return self.answer


class RefusingAuthor:
    """A fake author whose whole retry budget was spent on nothing admissible."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, workspace: Any) -> Any:
        self.calls.append(workspace)
        raise AuthoringRefusedError(
            "authoring_refused: the model's answer was shown the defect "
            "and refused again each time"
        )


class BudgetExhaustedAuthor:
    """A fake author whose pin's token budget is already spent."""

    def __call__(self, workspace: Any) -> Any:
        raise providers.BudgetExhaustedError(
            "budget_exhausted: the pin's running total has met its ceiling"
        )


class InterruptedAuthor:
    """A fake author standing in for a reclaimed spot instance."""

    def __call__(self, workspace: Any) -> Any:
        raise discovery.WorkerInterrupted(
            "the sandbox child died to the provider's reclaim signal"
        )


class FakeEvaluator:
    """A fake evaluator answering one fixed, duck-typed ``NodeEvaluation``."""

    def __init__(
        self, *, fail_class: str | None = None, score: Any = "scored", charges_budget: bool = True
    ) -> None:
        self.calls: list[tuple[Any, Any, Any, Any]] = []
        self._fail_class = fail_class
        self._score = score
        self._charges_budget = charges_budget

    def evaluate(self, node_id: Any, campaign_id: Any, depth: Any, code: Any) -> Any:
        self.calls.append((node_id, campaign_id, depth, code))
        return SimpleNamespace(
            node_id=node_id,
            fail_class=self._fail_class,
            score=self._score,
            charges_budget=self._charges_budget,
        )


class FakeHistoryStore:
    """A fake ``ProposalHistoryStore`` recording every ``persist`` call."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, Any]] = []

    def persist(self, node_id: Any, proposal: Any, *, score: Any = None) -> None:
        self.calls.append((node_id, proposal, score))


# -- Fixtures -------------------------------------------------------------------


@pytest.fixture
def campaign_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def parent_id(tree_database: str, campaign_id: str) -> str:
    return _plant_parent(tree_database, campaign_id=campaign_id)


@pytest.fixture
def context(tree_database: str) -> Any:
    """The four facts ``NodeWorker`` reads off ``context`` — nothing else.

    A plain namespace rather than a real
    ``orchestrator._context.EvaluationContext``: that record also demands a
    mounted snapshot, a loaded cost model and a resolved evaluator identity,
    none of which this feature's worker ever touches — it reads exactly
    ``database_url``, ``evaluator_hash``, ``snapshot_hash`` and
    ``cost_model_hash``, so a fake naming only those four is the honest
    double for this seam.
    """
    return SimpleNamespace(
        database_url=tree_database,
        evaluator_hash=hashlib.sha256(b"evaluator").hexdigest(),
        snapshot_hash=hashlib.sha256(b"snapshot").hexdigest(),
        cost_model_hash=hashlib.sha256(b"cost-model").hexdigest(),
    )


@pytest.fixture
def artifact_directory(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def history_store() -> FakeHistoryStore:
    return FakeHistoryStore()


# -- The happy path ---------------------------------------------------------------


def test_worker_expands_records_authors_and_evaluates_a_child(
    tree_database: str,
    campaign_id: str,
    parent_id: str,
    context: Any,
    artifact_directory: ArtifactStore,
    history_store: FakeHistoryStore,
) -> None:
    child_id = discovery.refined_node_id(parent_id)
    author = FakeAuthor(child_id=child_id, campaign_id=campaign_id, depth=1)
    evaluator = FakeEvaluator(fail_class=None, score="good-score", charges_budget=False)
    worker = NodeWorker(
        author,
        evaluator,
        context=context,
        artifact_directory=artifact_directory,
        history_store=history_store,
    )

    outcome = worker(parent_id)

    # The answer: the feature's own six fields, read straight off the fake
    # evaluator and the derived child, never recomputed by this worker.
    assert isinstance(outcome, ChildOutcome)
    assert outcome.node_id == child_id
    assert outcome.depth == 1
    assert outcome.fail_class is None
    assert outcome.score == "good-score"
    assert outcome.charges_budget is False
    assert outcome.record == author.answer.record

    # The attempt landed in the tree, under the derived child, carrying the
    # adopted source, the authoring and the provenance the context supplied.
    row = _node_row(tree_database, child_id)
    assert row is not None
    assert row["parent_id"] == parent_id
    assert row["campaign_id"] == campaign_id
    assert row["depth"] == 1
    assert row["code_hash"] == hashlib.sha256(SOURCE.encode("utf-8")).hexdigest()
    assert row["stated_mechanism"] == "Fades crowded carry."
    assert row["evaluator_hash"] == context.evaluator_hash
    assert row["snapshot_hash"] == context.snapshot_hash
    assert row["cost_model_hash"] == context.cost_model_hash
    assert row["fail_class"] == "ok"

    # providers.record_authoring landed the author's own trio on the same row
    # — the node row the attempt log wrote moments before, per the feature's
    # own ordering.
    assert row["agent_model_id"] == PIN.agent_model_id
    assert row["agent_ckpt_hash"] is None

    # The evaluator was called with exactly the child's identity and the
    # adopted code — never the parent's.
    assert evaluator.calls == [(child_id, campaign_id, 1, SOURCE)]

    # The proposal and its score were persisted under the child's id.
    assert history_store.calls == [(child_id, PROPOSAL, "good-score")]


def test_worker_evaluates_under_the_oracles_directive_and_names_a_failure(
    tree_database: str,
    campaign_id: str,
    parent_id: str,
    context: Any,
    artifact_directory: ArtifactStore,
    history_store: FakeHistoryStore,
) -> None:
    # An evaluation that itself failed still names its own class — this
    # worker invents no vocabulary of its own for it, and still never
    # touches the evaluator's own charges_budget directive.
    child_id = discovery.refined_node_id(parent_id)
    author = FakeAuthor(child_id=child_id, campaign_id=campaign_id, depth=1)
    evaluator = FakeEvaluator(
        fail_class="SandboxExecutionError", score=None, charges_budget=True
    )
    worker = NodeWorker(
        author,
        evaluator,
        context=context,
        artifact_directory=artifact_directory,
        history_store=history_store,
    )

    outcome = worker(parent_id)

    assert outcome.fail_class == "SandboxExecutionError"
    assert outcome.score is None
    assert outcome.charges_budget is True
    # The attempt itself still answered — authoring succeeded — so the
    # node's own fail_class (discovery's vocabulary) stays 'ok': this
    # worker never writes an evaluation failure into the discovery tree.
    row = _node_row(tree_database, child_id)
    assert row is not None
    assert row["fail_class"] == "ok"


# -- The authoring refusal --------------------------------------------------------


def test_authoring_refused_is_a_failed_attempt_and_is_not_evaluated(
    tree_database: str,
    campaign_id: str,
    parent_id: str,
    context: Any,
    artifact_directory: ArtifactStore,
    history_store: FakeHistoryStore,
) -> None:
    child_id = discovery.refined_node_id(parent_id)
    author = RefusingAuthor()
    evaluator = FakeEvaluator()
    worker = NodeWorker(
        author,
        evaluator,
        context=context,
        artifact_directory=artifact_directory,
        history_store=history_store,
    )

    outcome = worker(parent_id)

    assert outcome.node_id == child_id
    assert outcome.depth == 1
    assert outcome.fail_class == AUTHORING_REFUSED_FAIL_CLASS
    assert outcome.fail_class == "authoring_refused"
    assert outcome.score is None
    assert outcome.charges_budget is True
    assert outcome.record is None

    # Never evaluated, and nothing was persisted to the history store.
    assert evaluator.calls == []
    assert history_store.calls == []

    # Nothing landed in the discovery tree for a child that was never
    # authored: there is no code, so there is no node_id a row could carry.
    assert _node_row(tree_database, child_id) is None


# -- The two propagating failures -------------------------------------------------


def test_budget_exhausted_propagates_and_is_not_recorded(
    tree_database: str,
    campaign_id: str,
    parent_id: str,
    context: Any,
    artifact_directory: ArtifactStore,
    history_store: FakeHistoryStore,
) -> None:
    child_id = discovery.refined_node_id(parent_id)
    worker = NodeWorker(
        BudgetExhaustedAuthor(),
        FakeEvaluator(),
        context=context,
        artifact_directory=artifact_directory,
        history_store=history_store,
    )

    with pytest.raises(providers.BudgetExhaustedError):
        worker(parent_id)

    assert _node_row(tree_database, child_id) is None
    assert history_store.calls == []


def test_worker_interrupted_propagates_for_retry_interrupted(
    tree_database: str,
    campaign_id: str,
    parent_id: str,
    context: Any,
    artifact_directory: ArtifactStore,
    history_store: FakeHistoryStore,
) -> None:
    child_id = discovery.refined_node_id(parent_id)
    worker = NodeWorker(
        InterruptedAuthor(),
        FakeEvaluator(),
        context=context,
        artifact_directory=artifact_directory,
        history_store=history_store,
    )

    with pytest.raises(discovery.WorkerInterrupted):
        worker(parent_id)

    assert _node_row(tree_database, child_id) is None
    assert history_store.calls == []


# -- Idempotence --------------------------------------------------------------------


def test_running_the_same_parent_twice_is_idempotent(
    tree_database: str,
    campaign_id: str,
    parent_id: str,
    context: Any,
    artifact_directory: ArtifactStore,
    history_store: FakeHistoryStore,
) -> None:
    child_id = discovery.refined_node_id(parent_id)
    author = FakeAuthor(child_id=child_id, campaign_id=campaign_id, depth=1)
    evaluator = FakeEvaluator(fail_class=None, score="good-score", charges_budget=False)
    worker = NodeWorker(
        author,
        evaluator,
        context=context,
        artifact_directory=artifact_directory,
        history_store=history_store,
    )

    first = worker(parent_id)
    second = worker(parent_id)

    # The derived child id is one value on both runs, and the two outcomes
    # agree on everything the fakes answer deterministically.
    assert first.node_id == second.node_id == child_id
    assert first.fail_class == second.fail_class
    assert first.score == second.score
    assert first.charges_budget == second.charges_budget
    assert first.record == second.record

    # The author and the evaluator were each asked twice (this worker does
    # not memoize a prior call), but the tree holds exactly one row for the
    # one child id both runs derived — a retry refreshes, it never
    # duplicates.
    assert len(author.calls) == 2
    assert len(evaluator.calls) == 2
    with closing(sqlite3.connect(_path_of(tree_database))) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM node WHERE id = ?", (child_id,)
        ).fetchone()[0]
    assert count == 1


def test_the_module_exports_exactly_its_two_names() -> None:
    from orchestrator import _worker

    assert set(_worker.__all__) == {"ChildOutcome", "NodeWorker"}
    assert callable(_worker.NodeWorker)
