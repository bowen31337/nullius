"""The four laws of the expansion — pinned as behaviour.

app_spec.xml feature 239: *System expands a selected node by resuming
its workspace, which creates exactly one refined signal for
evaluation.*  PRD §5's loop 1 spells the same act as ``CONTINUE(v)``,
and the sentence carries four claims, each pinned here as an observable
behaviour rather than a shape to trust:

**The resumption law — the workspace resumed is the selected node's,
and the tree is its only source.**  The agent seam is handed a
:class:`~discovery.expansion.NodeWorkspace` built from the node row's
five structural facts, an ask that is not a node id / a tree with no
``node`` table / an id no row carries each refuse naming the node
*before the agent is consulted*, and a corrupt row (a blank theme, a
negative depth, a non-UUID campaign) refuses rather than inherits.  A
root's workspace is resumable exactly like any other node's — its
refined signal is the root's first child.

**The identity law — the refined signal's node id is derived, never
minted.**  ``uuid5(EXPANSION_NAMESPACE, parent_id)``, so the same ask
is the same attempt on every run: this is the structural fact
:mod:`discovery.retry`'s identity law stands on (*"a re-run that
minted a fresh node id would post a charge the ledger dutifully
appends"*), and the suite proves it end to end — through the pool and
through the retry — because that is the path a reclamation actually
takes.  The pin lives inside the value: a signal whose id is not its
parent's derivation cannot be built, by constructor or by
``dataclasses.replace``.

**The cardinality law — exactly one.**  An answer of several
candidates is refused as loudly as an answer of none (several
refinements are several dispatches, each its own debited ``node_id``);
a bare string is refused rather than read as a code-only construction;
blank code, a missing ``code``, a blank stated mechanism — each
refused.  One candidate, whatever collection it arrived in, is
adopted, and its code is answered verbatim.

**The passthrough law — the expansion wraps nothing it did not
refuse.**  An agent's :class:`~discovery.errors.WorkerInterrupted`
must reach the pool as itself for
:func:`~discovery.retry.is_interruption` to classify it, and an
agent's failure must reach it as itself for §6.1's step 11 to have
charged a real attempt — while the expansion's own refusals are
values on the pool's results like any failure, never the death of the
batch (feature 240's *"including failures"*).

The agent throughout is a stand-in, not the signal agent: a
deployment's driver closes over the artifact-side of the workspace
(the source, every prior proposal, the scores), and what this feature
owns is the resumption, the identity, the count and the hand-off.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

import pytest
from discovery import (
    EXPANSION_NAMESPACE,
    DiscoveryError,
    ExpansionError,
    NodeExpansion,
    NodeWorkspace,
    RefinedSignal,
    WorkerInterrupted,
    expand_node,
    refined_node_id,
)
from discovery.retry import is_interruption, retry_interrupted
from discovery.workers import WorkerResult, run_batch

#: Source text with the imperfections a tidying implementation would
#: "fix" — a blank line, a comment, a trailing expression — so the
#: verbatim law is pinned against something worth editing.
ADOPTED_CODE = (
    "def signal(ctx, seed):\n"
    "\n"
    "    # a refinement of the parent's mechanism\n"
    "    return ctx.close / ctx.close.shift(1) - 1\n"
)

#: The sha256 of :data:`ADOPTED_CODE`, spelled by the test so the
#: adoption's hash is compared against the arithmetic, not against
#: itself.
ADOPTED_HASH = hashlib.sha256(ADOPTED_CODE.encode("utf-8")).hexdigest()

#: The mechanism the default stub states — a real rationale's shape,
#: so the honest-absent case is a distinct fact rather than a default.
ADOPTED_MECHANISM = "reversal is the momentum of the impatient"


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test.

    This suite's own four lines rather than a call into the member or the
    conftest: the store's ``_sqlite_path`` is private, and a test reaching
    into it would be pinning an implementation detail it should be free to
    change — the same discipline :mod:`tests.test_campaign` states for its
    own copy of these lines.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


class StubRefinement:
    """The agent's answer, carrying a construction.

    The duck-typed seam the expansion reads: ``code`` as an attribute,
    ``stated_mechanism`` optionally beside it.  A class rather than a
    ``SimpleNamespace`` so the *absent* mechanism is genuinely absent
    (the attribute is simply never set), which is the honest ``None``
    0117 permits the agent to state.
    """

    def __init__(self, code: Any, stated_mechanism: Any = None) -> None:
        self.code = code
        if stated_mechanism is not None:
            self.stated_mechanism = stated_mechanism


class RecordingAgent:
    """An agent seam that records every workspace it is handed.

    The resumption law's witness: what this object recorded *is* what
    the agent resumed, and what it did not record is what the expansion
    refused before consulting it.
    """

    def __init__(self, answer: Any = None) -> None:
        self.answer = (
            StubRefinement(ADOPTED_CODE, ADOPTED_MECHANISM)
            if answer is None
            else answer
        )
        self.calls: list[NodeWorkspace] = []

    def __call__(self, workspace: NodeWorkspace) -> Any:
        self.calls.append(workspace)
        return self.answer


class InterruptedOnceAgent:
    """An agent reclaimed once, answering on the re-run.

    Feature 244's story in one seam: the first call for a node is
    §14's spot-instance reclamation arriving as data, and the second
    is the retry's re-run of the same ask.
    """

    def __init__(self, interrupted_for: set[str]) -> None:
        self.interrupted_for = interrupted_for
        self.calls: list[str] = []

    def __call__(self, workspace: NodeWorkspace) -> Any:
        self.calls.append(workspace.node_id)
        if workspace.node_id in self.interrupted_for:
            self.interrupted_for.discard(workspace.node_id)
            raise WorkerInterrupted(
                f"the provider reclaimed the slot evaluating a child of "
                f"{workspace.node_id}"
            )
        return StubRefinement(ADOPTED_CODE, "the retry's refinement")


@pytest.fixture
def tree(migrated_with_tree: str, campaign_id: str, plant_root):
    """A planted root and one child under it, in a migrated tree.

    Returns ``(url, root_id, child_id)`` — the root is the depth-0
    workspace whose refinement is a first child, and the child is a
    depth-1 workspace whose refinement is a second, so the parentage
    law is pinned at both depths the conftest's planter can reach.
    """
    root = plant_root(campaign_id)
    child = plant_root(campaign_id, parent_id=root, depth=1)
    return migrated_with_tree, root, child


@pytest.fixture
def worker(tree) -> tuple[NodeExpansion, RecordingAgent, str, str]:
    """The expansion wired over the planted tree, with its recording agent.

    Returns ``(expansion, agent, root, child)`` so a test reaches all
    four without re-deriving any of them.
    """
    url, root, child = tree
    agent = RecordingAgent()
    return NodeExpansion(agent, url), agent, root, child


# -- The resumption law ------------------------------------------------------------


class TestTheResumptionLaw:
    def test_the_agent_is_handed_the_selected_nodes_workspace(self, worker):
        expansion, agent, root, _ = worker
        expansion(root)
        assert len(agent.calls) == 1
        resumed = agent.calls[0]
        assert isinstance(resumed, NodeWorkspace)
        assert resumed.node_id == root
        assert resumed.parent_id is None
        assert resumed.theme_root == "macro"
        assert resumed.depth == 0
        assert resumed.is_root

    def test_a_deeper_nodes_workspace_is_read_at_its_depth(self, worker):
        expansion, _agent, root, child = worker
        resumed = expansion.workspace(child)
        assert resumed.parent_id == root
        assert resumed.depth == 1
        assert not resumed.is_root
        assert resumed.node_id == child

    def test_an_uppercase_ask_resolves_the_row_it_names(self, worker):
        expansion, agent, root, _ = worker
        signal = expansion(root.upper())
        assert agent.calls[0].node_id == root
        assert signal.parent_id == root

    def test_an_ask_that_is_not_a_node_id_is_refused_before_the_agent(
        self, tree
    ):
        url, root, _ = tree
        agent = RecordingAgent()
        expansion = NodeExpansion(agent, url)
        for bad in (None, "", "not-a-uuid", 123, True, root[:-1]):
            with pytest.raises(ExpansionError, match="not a node id"):
                expansion(bad)
        assert agent.calls == []

    def test_an_unknown_node_is_refused_naming_the_node(self, worker):
        expansion, agent, _, _ = worker
        stranger = str(uuid.uuid4())
        with pytest.raises(ExpansionError, match=stranger) as exc:
            expansion(stranger)
        assert "not in the tree" in str(exc.value)
        assert agent.calls == []

    def test_a_tree_with_no_node_table_is_refused_by_name(
        self, migrated_database
    ):
        agent = RecordingAgent()
        expansion = NodeExpansion(agent, migrated_database)
        with pytest.raises(ExpansionError, match="no node table"):
            expansion(str(uuid.uuid4()))
        assert agent.calls == []

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("theme_root", ""),
            ("theme_root", "   "),
            ("depth", -1),
            ("depth", "two"),
            ("campaign_id", "not-a-uuid"),
        ],
    )
    def test_a_corrupt_row_refuses_rather_than_inherits(
        self, tree, campaign_id, column, value
    ):
        url, root, _ = tree
        identifier = str(uuid.uuid4())
        row = {
            "id": identifier,
            "parent_id": root,
            "campaign_id": campaign_id,
            "theme_root": "macro",
            "depth": 1,
        }
        row[column] = value
        with closing(sqlite3.connect(_path_of(url))) as c, c:
            c.execute(
                "INSERT INTO node (id, parent_id, campaign_id, theme_root, "
                "depth) VALUES (?, ?, ?, ?, ?)",
                (
                    row["id"],
                    row["parent_id"],
                    row["campaign_id"],
                    row["theme_root"],
                    row["depth"],
                ),
            )
        agent = RecordingAgent()
        with pytest.raises(ExpansionError, match=identifier) as exc:
            NodeExpansion(agent, url)(identifier)
        assert column in str(exc.value)
        assert agent.calls == []

    def test_the_row_is_the_workspace_read_fresh_every_call(self, worker):
        expansion, _, root, _ = worker
        first = expansion(root)
        assert first.theme_root == "macro"
        with closing(
            sqlite3.connect(_path_of(expansion.database_url))
        ) as c, c:
            c.execute(
                "UPDATE node SET theme_root = 'volatility-dispersion' "
                "WHERE id = ?",
                (root,),
            )
        assert expansion(root).theme_root == "volatility-dispersion"


# -- The parentage and identity laws -----------------------------------------------


class TestTheParentageLaw:
    def test_the_signal_carries_the_parentage_unchanged(
        self, worker, campaign_id
    ):
        expansion, _, root, _ = worker
        signal = expansion(root)
        assert signal.parent_id == root
        assert signal.campaign_id == campaign_id
        assert signal.theme_root == "macro"
        assert signal.depth == 1

    def test_a_deeper_nodes_refinement_sits_one_below_it(self, worker):
        expansion, _, _, child = worker
        assert expansion(child).depth == 2

    def test_the_node_id_is_the_derivation_of_the_parent(self, worker):
        expansion, _, root, _ = worker
        signal = expansion(root)
        assert signal.node_id == refined_node_id(root)
        assert signal.node_id == str(uuid.uuid5(EXPANSION_NAMESPACE, root))

    def test_two_parents_derive_two_identities(self, worker):
        expansion, _, root, child = worker
        assert expansion(root).node_id != expansion(child).node_id

    def test_derivation_is_stable_across_calls_and_workers(self, worker):
        expansion, _, root, _ = worker
        again = NodeExpansion(
            RecordingAgent(), expansion.database_url
        )
        first = expansion(root)
        second = again(root)
        # The same ask is the same attempt: the derivation is a SHA-1
        # over two fixed inputs, not a draw from an entropy source.
        assert first.node_id == second.node_id
        assert first.node_id == str(uuid.uuid5(EXPANSION_NAMESPACE, root))


class TestTheIdentityPin:
    """The identity law pinned inside the value itself."""

    @pytest.fixture
    def signal(self, worker) -> RefinedSignal:
        expansion, _, root, _ = worker
        return expansion(root)

    def test_a_mismatched_node_id_cannot_be_built(self, signal):
        forged = str(uuid.uuid4())
        with pytest.raises(ExpansionError, match="derived from the parent"):
            replace(signal, node_id=forged)

    def test_a_depth_zero_signal_cannot_be_built(self, signal):
        with pytest.raises(ExpansionError, match="at least 1"):
            replace(signal, depth=0)

    def test_a_hash_that_disagrees_with_the_code_cannot_be_built(self, signal):
        with pytest.raises(ExpansionError, match="sha256"):
            replace(signal, code_hash="0" * 64)

    def test_blank_code_cannot_be_built(self, signal):
        with pytest.raises(ExpansionError, match="no source"):
            replace(signal, code="   ")

    def test_a_blank_mechanism_cannot_be_built(self, signal):
        with pytest.raises(ExpansionError, match="stated_mechanism"):
            replace(signal, stated_mechanism="   ")

    def test_the_signal_is_frozen(self, signal):
        with pytest.raises(FrozenInstanceError):
            signal.depth = 3  # type: ignore[misc]

    def test_the_workspace_is_frozen(self, worker):
        expansion, _, root, _ = worker
        resumed = expansion.workspace(root)
        with pytest.raises(FrozenInstanceError):
            resumed.depth = 7  # type: ignore[misc]

    def test_the_workspace_canonicalizes_ids(self, worker):
        expansion, _, root, _ = worker
        resumed = expansion.workspace(root)
        assert resumed.node_id == root.lower()
        assert NodeWorkspace(
            node_id=root.upper(),
            parent_id=None,
            campaign_id=resumed.campaign_id.upper(),
            theme_root="macro",
            depth=0,
        ).campaign_id == resumed.campaign_id


# -- The cardinality law ------------------------------------------------------------


class TestTheCardinalityLaw:
    def test_one_candidate_is_adopted_verbatim(self, worker):
        expansion, _, root, _ = worker
        signal = expansion(root)
        assert signal.code == ADOPTED_CODE
        assert signal.code_hash == ADOPTED_HASH
        assert signal.stated_mechanism == ADOPTED_MECHANISM

    @pytest.mark.parametrize("wrap", [list, tuple, set, frozenset])
    def test_a_collection_of_exactly_one_is_unwrapped(self, tree, wrap):
        url, root, _ = tree
        expansion = NodeExpansion(
            RecordingAgent(wrap([StubRefinement(ADOPTED_CODE)])), url
        )
        assert expansion(root).code == ADOPTED_CODE

    def test_no_signal_is_refused(self, tree):
        url, root, _ = tree
        for empty in ([], (), set(), frozenset()):
            expansion = NodeExpansion(RecordingAgent(empty), url)
            with pytest.raises(ExpansionError, match="no refined signal"):
                expansion(root)

    def test_several_candidates_are_refused(self, tree):
        url, root, _ = tree
        answer = [StubRefinement(ADOPTED_CODE), StubRefinement("def x(): pass")]
        expansion = NodeExpansion(RecordingAgent(answer), url)
        with pytest.raises(ExpansionError) as exc:
            expansion(root)
        message = str(exc.value)
        assert "2 refined signals" in message
        assert "exactly one" in message

    def test_a_candidate_with_no_code_is_refused(self, tree):
        url, root, _ = tree
        for bare in (object(), SimpleNamespace(other="no code here"), 42):
            expansion = NodeExpansion(RecordingAgent(bare), url)
            with pytest.raises(ExpansionError, match="no code"):
                expansion(root)

    def test_a_bare_string_is_refused_rather_than_read_as_code(self, tree):
        url, root, _ = tree
        for bare in (ADOPTED_CODE, b"def signal(ctx, seed): ..."):
            expansion = NodeExpansion(RecordingAgent(bare), url)
            with pytest.raises(ExpansionError, match="construction"):
                expansion(root)

    @pytest.mark.parametrize("code", [None, "", "   ", 3.14])
    def test_code_that_is_not_source_is_refused(self, tree, code):
        url, root, _ = tree
        expansion = NodeExpansion(RecordingAgent(StubRefinement(code)), url)
        with pytest.raises(ExpansionError, match="code"):
            expansion(root)

    def test_an_absent_mechanism_is_the_honest_none(self, tree):
        url, root, _ = tree
        expansion = NodeExpansion(
            RecordingAgent(StubRefinement(ADOPTED_CODE)), url
        )
        assert expansion(root).stated_mechanism is None

    @pytest.mark.parametrize("mechanism", ["", "   ", 7])
    def test_a_blank_mechanism_is_refused(self, tree, mechanism):
        url, root, _ = tree
        expansion = NodeExpansion(
            RecordingAgent(StubRefinement(ADOPTED_CODE, mechanism)), url
        )
        with pytest.raises(ExpansionError, match="stated_mechanism"):
            expansion(root)


# -- The passthrough law ------------------------------------------------------------


class TestThePassthroughLaw:
    def test_an_interruption_arrives_as_itself(self, tree):
        url, root, _ = tree
        expansion = NodeExpansion(InterruptedOnceAgent({root}), url)
        with pytest.raises(WorkerInterrupted, match="reclaimed") as excinfo:
            expansion(root)
        # And it classifies: the retry's predicate is a class check,
        # and a re-wrapped interruption would quietly stop retrying.
        assert is_interruption(WorkerResult(slot=0, job=root, error=excinfo.value))

    def test_an_agent_failure_arrives_as_itself(self, tree):
        url, root, _ = tree

        def boom(workspace: NodeWorkspace) -> Any:
            raise RuntimeError("the driver lost its artifact store")

        with pytest.raises(RuntimeError, match="artifact store"):
            NodeExpansion(boom, url)(root)

    def test_the_refusal_is_a_discovery_error(self, tree):
        url, root, _ = tree
        expansion = NodeExpansion(RecordingAgent([]), url)
        with pytest.raises(DiscoveryError):
            expansion(root)


# -- The worker of record: composition with the pool and the retry -------------------


class TestTheWorkerOfRecord:
    def test_the_pool_runs_the_expansion_once_per_selected_node(
        self, tree, campaign_id, plant_root
    ):
        url, root, child = tree
        # Two more workspaces, so the batch is wider than two and the
        # W the campaign planned with is genuinely plural.
        others = [
            plant_root(campaign_id, parent_id=root, depth=2 + i)
            for i in range(2)
        ]
        expansion = NodeExpansion(RecordingAgent(), url)
        batch = [root, child, *others]
        results = list(run_batch(expansion, batch, width=4))
        assert len(results) == len(batch)
        by_job = {result.job: result for result in results}
        for node in batch:
            result = by_job[node]
            assert result.ok, result.error
            assert isinstance(result.value, RefinedSignal)
            assert result.value.parent_id == node
            assert result.value.node_id == refined_node_id(node)

    def test_a_refused_expansion_is_a_value_on_the_result(self, worker):
        expansion, _, root, _ = worker
        refusing = NodeExpansion(
            RecordingAgent([]), expansion.database_url
        )
        results = list(run_batch(refusing, [root], width=1))
        assert len(results) == 1
        assert not results[0].ok
        assert isinstance(results[0].error, ExpansionError)
        assert not is_interruption(results[0])

    def test_the_retry_reruns_the_same_ask_into_the_same_identity(self, worker):
        expansion, _, root, _ = worker
        reclaimed = NodeExpansion(
            InterruptedOnceAgent({root}), expansion.database_url
        )
        first = list(run_batch(reclaimed, [root], width=1))
        assert len(first) == 1 and is_interruption(first[0])
        outcomes = list(
            retry_interrupted(reclaimed, first, retries=1, width=1)
        )
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.ok
        assert outcome.job == root
        # The identity law, end to end: the re-run's refined signal
        # derives the node_id the interrupted attempt's debit would
        # have keyed on — the same ask is the same attempt, so §14's
        # ledger idempotence has one row to be idempotent over.
        assert outcome.result.value.node_id == refined_node_id(root)
        assert outcome.attempts == 2


# -- The hand-off -------------------------------------------------------------------


class TestTheHandOff:
    def test_row_is_the_node_row_the_attempt_lands_in(self, worker):
        expansion, _, root, _ = worker
        signal = expansion(root)
        assert signal.row() == {
            "id": signal.node_id,
            "parent_id": root,
            "campaign_id": signal.campaign_id,
            "theme_root": "macro",
            "depth": 1,
            "code_hash": ADOPTED_HASH,
            "stated_mechanism": ADOPTED_MECHANISM,
        }
        # The source text travels as the attribute: §9.1 stores the
        # hash and §9.2's artifact directory stores the text.
        assert "code" not in signal.row()
        assert signal.code == ADOPTED_CODE

    def test_row_is_a_fresh_mapping(self, worker):
        expansion, _, root, _ = worker
        signal = expansion(root)
        first = signal.row()
        first["depth"] = 99
        assert signal.row()["depth"] == 1


# -- The worker's own wiring ---------------------------------------------------------


class TestTheWiring:
    def test_a_non_callable_agent_is_refused_at_construction(self, tree):
        url, _, _ = tree
        with pytest.raises(ExpansionError, match="callable"):
            NodeExpansion("an agent, allegedly", url)

    def test_a_blank_url_is_refused_at_construction(self):
        for blank in ("", "   ", None, 5):
            with pytest.raises(ExpansionError, match="database URL"):
                NodeExpansion(RecordingAgent(), blank)

    def test_a_url_this_member_cannot_speak_is_refused_by_name(self, tree):
        _, root, _ = tree
        expansion = NodeExpansion(
            RecordingAgent(), "postgres://orchestrator/tree"
        )
        with pytest.raises(ExpansionError, match="postgres"):
            expansion(root)

    def test_construction_touches_no_disk(self, tmp_path: Path):
        absent = tmp_path / "nowhere" / "tree.db"
        NodeExpansion(RecordingAgent(), f"sqlite:///{absent}")
        assert not absent.exists()

    def test_expand_node_resolves_the_store_from_the_environment(
        self, tree, monkeypatch
    ):
        url, root, _ = tree
        monkeypatch.setenv("DATABASE_URL", url)
        assert expand_node(RecordingAgent(), root).parent_id == root

    def test_expand_node_prefers_an_explicit_url_over_the_environment(
        self, tree, monkeypatch
    ):
        url, root, _ = tree
        monkeypatch.setenv("DATABASE_URL", "sqlite:///nowhere-at-all.db")
        signal = expand_node(RecordingAgent(), root, database_url=url)
        assert signal.parent_id == root

    def test_expand_node_refuses_when_nothing_names_a_store(
        self, tree, monkeypatch
    ):
        _, root, _ = tree
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ExpansionError, match="nothing names a store"):
            expand_node(RecordingAgent(), root)


# -- The module surface --------------------------------------------------------------


class TestTheModuleSurface:
    def test_the_error_is_exported_beside_its_siblings(self):
        import discovery

        for name in (
            "EXPANSION_NAMESPACE",
            "ExpansionError",
            "NodeExpansion",
            "NodeWorkspace",
            "RefinedSignal",
            "expand_node",
            "refined_node_id",
        ):
            assert name in discovery.__all__
        assert issubclass(ExpansionError, DiscoveryError)

    def test_the_derivation_refuses_a_non_uuid_parent(self):
        for bad in (None, "root", 0):
            with pytest.raises(ExpansionError, match="not a node id"):
                refined_node_id(bad)

    def test_the_derivation_canonicalizes_before_deriving(self, worker):
        expansion, _, root, _ = worker
        expansion(root)
        assert refined_node_id(root.upper()) == refined_node_id(root)

    def test_a_derived_id_is_a_valid_uuid(self, worker):
        expansion, _, root, _ = worker
        derived = expansion(root).node_id
        assert str(uuid.UUID(derived)) == derived
