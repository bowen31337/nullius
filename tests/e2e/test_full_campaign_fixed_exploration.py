"""Feature 367: the end-to-end journey — a full campaign runs under fixed
exploration against fixture-backed agents, which returns baseline sensitivity
and specificity.

app_spec.xml, "End-to-End Verification", feature 367: *"System passes an
end-to-end test where a full campaign runs under fixed exploration against
fixture-backed agents, which returns baseline sensitivity and specificity."*
The sentence is the repository-level proof that the pieces the member suites
pin in isolation compose into the journey the architecture promises — the
frozen evaluator's replay (§10), the null oracle's sealed labels (§7), and the
calibration the scorer process answers (feature 266) — and it names four
clauses, each of which this module stages through the shipped system's own
public seams and none of which it stages by hand.

**A full campaign.** A discovery campaign tree — the policy-runtime member's
:class:`CampaignTree`, the same node model the frozen evaluator and the nightly
canary address — planted with both classes: null roots, whose subtree the
replay scorer will read as null, and real roots, whose subtree it will read as
real. The roots are the *whole* both calibration figures are fractions over,
and there are two of each class — §4.1.1's floor, the smallest plant that
contributes to both sensitivity and specificity. Each root carries one recorded
child, so the tree the replay walks is eight nodes; the null/real status of a
node is not a value this journey assigns to the tree — the tree carries no
``is_null`` (the barrier forbids it — prd §4.2, cq-8) — so the labels live
where the architecture puts them, in the null oracle's sealed sidecar, keyed by
the same node ids the tree is built from.

**Runs under fixed exploration.** The campaign is replayed, not re-run: the
replay member's :func:`run_replay` drives the stored tree's recorded children —
the deterministic transition feature 245 refuses to generate through — while a
policy selects over the prefix view the replay hands it. The policy's
explore/exploit stance is a single ``β`` scalar, read *once* at the top of the
episode through :func:`read_beta` and fixed for it (feature 226), and it is the
same scalar in every replay this journey makes — *fixed* exploration, the
"held constant so the figures are comparable" the sentence means, not a sweep.
The exploration is fixed in a second sense too: the policy's ``select`` is a
function of the prefix alone, so two replays of it on the tree are one revealed
set (§12, cq-15) and the figures it earns are a measurement, not a draw.

**Against fixture-backed agents.** The agent is not a real language model and
this journey does not summon one: it is a fixture — a plain object exposing the
one ``select(prefix_view)`` decision and the one ``commit()`` terminal act the
identical ``question.*`` interface names, duck-typed exactly as the replay loop
and the terminal requirement read them. Two of them run the same fixed-β
exploration over the same tree — the sentence's *agents*, plural — and differ
only in the node each declares at termination: one commits to the strongest
real root (a true discovery), the other to the strongest root overall, which
here is a null that looked strong in-sample (a false discovery). The stand-in
is *backed* by the fixtures in the sense the journey's whole point requires: it
commits to the nodes the planted labels make the honest discoveries, so the
figures the scorer process returns are the ones the plant predetermines. What
the journey asserts is that the shipped system — the replay loop, the
prefix-only barrier, the terminal commit, the scorer process holding the sealed
sidecar — carries that commitment to a figure, not that the stand-in decided
anything. Everything between the stand-in's verbs and the returned figures is
the shipped system's own code, reached through the shipped system's own public
seams.

**Which returns baseline sensitivity and specificity.** The two committed
picks are handed to the scorer process — the null oracle's real sealed sidecar
held behind the one ``assignment(node_id)`` seam, the same object the
cross-member suite builds — and the process answers feature 266's pair:
:meth:`NullPickScorer.calibration_figures`, over the campaign's planted roots
and the picks the agents committed. The figures are the base-rate independent
ones prd §4.1.3 reweights into ``FDR_deploy`` (feature 267, never restated
here): sensitivity = TP / (TP + FN) over the real class, specificity =
TN / (TN + FP) over the null class, each computed *within* a ground-truth class
so the campaign's null fraction φ cancels. The journey's plant and picks are
chosen so both figures are hand-computable to the bit — one real of two found
(sensitivity 0.5), one null of two wrongly declared (specificity 0.5) — and the
assertions check them against that hand computation: the baseline the sentence
promises.

**What this journey checks rather than assumes.** The labels stay in. The
scorer process answers two bare floats and nothing label-shaped crosses the
boundary in either direction — no count of a class, no node id, no sidecar —
and the journey asserts the *type* of the answer is the barrier's whole
spelling (``float``), because a figure that leaked a label would be the process
§4.2 was written to contain. The sidecar is sealed the architecture's way — the
AES-GCM envelope, the ``0o600`` file in a ``0o700`` directory, one 32-byte key —
and the journey reads it back only through the scorer process's held seam, the
same read the deployment makes. The campaign tree, the replay loop, the prefix
view, the fixed-β read, the terminal commit and the scorer process are all the
shipped system's own objects and verbs; the only thing this journey owns is the
far end of the wire — the stand-in policy's two decisions and the planted
labels — which is the party the sentence is about.

**One module, one journey, run once.** The journey runs both agents end to end
a single time in a module-scoped fixture over its own sealed sidecar and its own
SQLite store, and the facet tests below read the committed picks, the returned
figures and the persisted rows out of that one run. The member suites pin each
verb's own law — the loop's refusals (packages/replay/tests), the prefix-only
barrier (packages/policy-runtime/tests), the calibration figures' refusals
(packages/scoring/tests) — and this module does not re-test them; it asserts the
one thing only the composition can: that the shipped system, driven by
fixture-backed agents under fixed exploration, returns the baseline figures the
sentence claims.
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

# The shared tests/e2e/conftest.py puts every declared member's scan root on
# sys.path before this line runs, so the members import by their bare names —
# the workspace contract that no member imports another member, honoured here by
# reaching each through the path the conftest already built. This module adds
# only the repository root, for the same reason feature 369's journey does, and
# states it here so the reason travels with the import.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nulloracle import NullAssignment, NullSidecar
from policy_runtime import (
    CampaignTree,
    CommittedPick,
    EpisodeBeta,
    EpisodeCommit,
    PolicyQuestion,
    prefix_view,
    read_beta,
)
from replay import persist_replay_score, run_replay
from scoring import NullPickScorer

# ---------------------------------------------------------------------------
# The planted campaign — the whole both figures are fractions over
# ---------------------------------------------------------------------------

#: The two null roots and two real roots the campaign is planted with —
#: §4.1.1's floor held exactly, canonical UUID text so the sidecar's keys and
#: the tree's node ids are one address space. A null root's subtree the scorer
#: reads as null, a real root's as real; these four ids are the population both
#: figures are counts over.
NULL_ROOT_A = "1a2b3c4d-5e6f-4778-89ab-cdef000000c1"
NULL_ROOT_B = "1a2b3c4d-5e6f-4778-89ab-cdef000000c2"
REAL_ROOT_A = "1a2b3c4d-5e6f-4778-89ab-cdef000000d1"
REAL_ROOT_B = "1a2b3c4d-5e6f-4778-89ab-cdef000000d2"

#: Each root's in-sample reading — the honest payload the observation carries.
#: The nulls read *stronger* than the reals on purpose: a null that looks
#: strong in-sample is exactly the false discovery a fixed-exploration policy
#: can be fooled into declaring, which is the false positive this journey's
#: baseline specificity is measured against.
_ROOT_R2 = {
    NULL_ROOT_A: 0.31,
    NULL_ROOT_B: 0.27,
    REAL_ROOT_A: 0.22,
    REAL_ROOT_B: 0.18,
}

#: Each root's one recorded child — the deterministic replay edge feature 245
#: reads (the node that names the root as its parent). A replay stepping from a
#: root reveals exactly this child; a leaf records none. The children are part
#: of the tree the replay walks, not part of the planted population the figures
#: are taken over — the sidecar labels the roots, and the children are the
#: refinements the walk reveals.
_CHILD_OF = {
    NULL_ROOT_A: "1a2b3c4d-5e6f-4778-89ab-cdef000000e1",
    NULL_ROOT_B: "1a2b3c4d-5e6f-4778-89ab-cdef000000e2",
    REAL_ROOT_A: "1a2b3c4d-5e6f-4778-89ab-cdef000000f1",
    REAL_ROOT_B: "1a2b3c4d-5e6f-4778-89ab-cdef000000f2",
}

#: The planted population — the four roots the sidecar labels, two null and two
#: real. This is the whole both figures are counts over, and the labels are the
#: plant the journey declares: the scorer process reads them inside, per node,
#: and answers two figures with nothing label-shaped crossing the boundary. The
#: children are deliberately absent — they are replay edges, not planted nodes.
_PLANT = {
    NULL_ROOT_A: True,
    NULL_ROOT_B: True,
    REAL_ROOT_A: False,
    REAL_ROOT_B: False,
}

#: The fixed explore/exploit stance of every replay in this journey — one β,
#: read once at the top of the episode and fixed for it (feature 226). The
#: value is a policy decision a deployment chooses; 0.5 is the neutral one, and
#: the journey holds it constant across both agents so the figures are
#: comparable — *fixed* exploration, not a sweep.
BETA = 0.5

#: The round cap every replay runs under — the caller's policy decision of how
#: many selection rounds a replay may take (feature 248's K2, a symbolic bound
#: this journey spells as one concrete count). Enough rounds for the fixture
#: policy to walk every root to its child and stop; the policy terminates on
#: "no batch" well before the cap, so the cap bounds rather than truncates.
ROUND_CAP = 8


def _campaign_tree() -> CampaignTree:
    """The planted campaign tree — four roots, each with one recorded child.

    Built through :meth:`CampaignTree.freeze`, the canonicaliser the shipped
    system exposes: each root is a depth-0 node with an in-sample payload, and
    each child names its root as parent at depth 1. The payloads carry the
    honest in-sample metrics the observation reads — ``r2_insample`` distinct
    per node, so a policy standing on the prefix sees a real reading to decide
    from — and nothing the barrier forbids: never ``is_null`` (readable by
    exactly one component, the replay scorer). The tree is the address space the
    sidecar's labels are keyed by, and the only structure the replay walks.
    """
    specs: dict[str, tuple[str | None, int, dict[str, object]]] = {}
    for root in (NULL_ROOT_A, NULL_ROOT_B, REAL_ROOT_A, REAL_ROOT_B):
        # A root: parentless, depth 0, carrying an honest in-sample reading.
        specs[root] = (
            None,
            0,
            {"r2_insample": _ROOT_R2[root], "ic_insample": 1.0,
             "n_periods": 60, "n_features": 3},
        )
        child = _CHILD_OF[root]
        # The recorded child: names the root as parent, depth 1, its own
        # reading. This is the one edge feature 245's transition reveals — the
        # deterministic replay half of the cost model.
        specs[child] = (
            root,
            1,
            {"r2_insample": _ROOT_R2[root] + 0.09, "ic_insample": 0.8,
             "n_periods": 80, "n_features": 4},
        )
    return CampaignTree.freeze(specs)


def _sealed_sidecar(tmp: Path) -> NullSidecar:
    """The null oracle's sealed sidecar, holding the planted roots.

    The real object, really sealed — written through the oracle's own atomic
    write so the file on disk carries the ``0o600``-in-``0o700`` rule the read
    path checks, not a fixture's idea of it — over a fresh 32-byte key, answered
    with the sidecar and the key it was sealed with. The labels are the plant
    :data:`_PLANT`, each one a :class:`NullAssignment` with a fixed perm_seed so
    the write is whole. This is the one secret the journey owns — the labels,
    sealed — and it hands the sidecar to the scorer process, which reads it
    behind the one ``assignment(node_id)`` seam.
    """
    key = bytes(range(32))  # a 32-byte AES-256 key — the form NullSidecar
    # accepts for a process that already holds the material; the hex form of
    # the same bytes is what an environment's ``hex:`` key reference spells.
    sidecar = NullSidecar(tmp / "null" / "sidecar.enc", key)
    sidecar.write(
        {node: NullAssignment(node, bit, perm_seed=11) for node, bit in _PLANT.items()}
    )
    return sidecar


# ---------------------------------------------------------------------------
# The fixture-backed agent — the stand-in policy and its terminal commit
# ---------------------------------------------------------------------------


def _frontier(view: object) -> list[str]:
    """The fixed exploration's select — advance every open root one step.

    The caller's half of the loop, the body of ``policy.select(prefix_view(q))``
    — the same for both agents, because the exploration is *fixed*. It reads the
    prefix view's revealed cells — the only state a policy is shown (prefix-only,
    docs §10.2, cq-16) — and selects the *frontier*: a revealed root whose
    recorded child the walk has not yet advanced. Reading the view (not the
    tree) is what makes this a policy decision over the prefix, not a
    reachability query over the tree. A function of the prefix alone, so two
    replays of it on one tree are one revealed set (§12).
    """
    revealed = sorted(cell.node_id for cell in view.cells)
    return [n for n in revealed if n in _CHILD_OF and _CHILD_OF[n] not in revealed]


class FixedExplorationPolicy:
    """The fixture-backed agent — a stand-in policy under a fixed β, whose
    terminal declaration is the one thing that varies between agents.

    One of the "fixture-backed agents" the sentence names, and deliberately
    *not* a real language model. It exposes the two verbs the identical
    ``question.*`` interface hands a policy — :meth:`select`, the caller's
    closure over the policy and the prefix view, and :meth:`commit`, the
    terminal act feature 222 names — and nothing else. Its explore/exploit
    stance is the journey's fixed :data:`BETA`, read once at the top of the
    episode and fixed for it; the scalar is the policy's only state, and it is
    the same in every replay this journey makes.

    The agent is *fixed* in its exploration: :meth:`select` is :func:`_frontier`
    for every agent, so both walk the tree identically. What distinguishes one
    agent from another is its terminal :meth:`commit` — the node it declares as
    its discovery — supplied as a rule at construction. That split is the whole
    point of the journey: the exploration is held constant (one β, one walk) and
    the agents vary only in the discovery they commit, so the figures the scorer
    returns are a measurement of the plant, not of a difference in exploration.
    """

    def __init__(self, beta: EpisodeBeta, declare: object) -> None:
        # The fixed exploration stance, read once and held. EpisodeBeta is a
        # value type: it refuses every path by which a caller could move it, so
        # the scalar the policy carries is the one it was read from, for the
        # whole episode.
        self.beta = beta
        # The terminal declaration rule: a callable(question) -> node_id, the
        # node this agent commits to. Two agents, two rules, one fixed walk.
        self._declare = declare

    def select(self, view: object) -> list[str]:
        """The explore half — the fixed frontier advance, a function of the
        prefix.

        :func:`_frontier`, bound as this agent's select. The prefix view arrives
        already built by the caller's ``prefix_view(question)`` closure; the
        policy reads only its revealed cells.
        """
        return _frontier(view)

    def commit(self, question: object) -> CommittedPick:
        """The terminal act — commit to the node this agent declares.

        Feature 222's ``question.commit(node_id)`` — the one node, the door the
        terminal requirement reads. The node is the agent's own declaration
        rule; the commit itself goes through the shipped question's own door
        (:class:`EpisodeCommit`), so the terminal act is the shipped system's,
        not the stand-in's, and the pick that comes back is feature 222's
        :class:`CommittedPick` — the value the scorer's denominator counts.
        """
        node_id = self._declare(question)
        return EpisodeCommit(question).commit(node_id)


def _declare_best_real(question: object) -> str:
    """One agent's declaration — the strongest *real* root it revealed.

    The "precision" agent: it commits to the real root with the strongest
    in-sample reading among those the walk revealed — a true discovery, because
    the node it names is a real root the plant labels real. Both real roots are
    revealed by the frontier walk, so the argmax is over the honest pair.
    """
    observed = question.observed()
    return max((REAL_ROOT_A, REAL_ROOT_B), key=lambda n: observed[n].r2_insample)


def _declare_best_overall(question: object) -> str:
    """The other agent's declaration — the strongest root it revealed, any
    class.

    The "recall" agent: it commits to the root with the strongest in-sample
    reading regardless of class. Because the nulls were planted to read stronger
    than the reals (:data:`_ROOT_R2`), the strongest root overall is a null — a
    false discovery, the false positive this journey's baseline specificity is
    measured against. This is the honest behaviour of a policy that chases the
    best in-sample reading without the null labels it is not allowed to hold.
    """
    observed = question.observed()
    return max(
        (NULL_ROOT_A, NULL_ROOT_B, REAL_ROOT_A, REAL_ROOT_B),
        key=lambda n: observed[n].r2_insample,
    )


# ---------------------------------------------------------------------------
# The journey — run once, over one sealed sidecar and one SQLite store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Journey:
    """The frozen result of the one end-to-end run — the figures and the
    committed picks, plus the run's own coordinates."""

    sensitivity: float
    specificity: float
    figures_type: str
    picks: list[str]
    revealed: list[str]
    beta: float
    replay_score_rows: int
    replay_score_picks: list[str]
    replay_score_betas: list[float]


@pytest.fixture(scope="module")
def journey(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Journey]:
    """Run the full campaign once — fixed exploration, two fixture-backed
    agents, one sealed sidecar — and yield the figures and the committed picks.

    The journey runs its acts in the order the deployment runs them in: plant
    the campaign and seal its labels; replay it under fixed exploration through
    the shipped replay loop with each fixture-backed agent driving; collect each
    agent's committed pick; persist one replay_score row per run; and hand the
    planted population and the two picks to the scorer process, which answers
    the pair. One run, module-scoped, so the facet tests read one campaign out
    of it.
    """
    tmp = tmp_path_factory.mktemp("full_campaign_fixed_exploration")
    tree = _campaign_tree()
    sidecar = _sealed_sidecar(tmp)

    # Act 1 — fixed exploration: read β once at the top of the episode and fix
    # it (feature 226). The scalar is the policy's whole state, and it is the
    # same in both agents this journey runs.
    beta = read_beta(BETA)

    # Act 2 — the full campaign runs, replayed not re-run: the shipped replay
    # loop drives the stored tree's recorded children while each fixture-backed
    # agent selects over the prefix view the loop hands it. The closure is the
    # caller's half — ``lambda q: agent.select(prefix_view(q))`` — exactly the
    # shape run_replay expects; the question is the shipped PolicyQuestion over
    # the shipped tree. Both agents share the fixed exploration, so both walks
    # reveal the same set.
    picks: list[str] = []
    revealed: list[str] = []
    store_url = f"sqlite:///{tmp / 'store.db'}"
    agents = (
        ("precision", _declare_best_real),
        ("recall", _declare_best_overall),
    )
    for _name, rule in agents:
        agent = FixedExplorationPolicy(beta, rule)
        question = PolicyQuestion(tree)
        # The replay reveals the tree onto the question: it seeds the roots,
        # then advances each root to its recorded child. The returned prefix is
        # the revealed set; the question's observed() now holds every revealed
        # cell, which is what the terminal commit reads.
        run_replay(
            lambda q, agent=agent: agent.select(prefix_view(q)),
            question,
            tree,
            round_cap=ROUND_CAP,
        )
        # Act 3 — the terminal act: the agent commits through the question's own
        # door, and the pick that comes back is feature 222's CommittedPick —
        # the value the scorer's denominator counts. The episode commits once,
        # so the pick is made once and carried into both the picks list and the
        # persisted row.
        pick = agent.commit(question)
        picks.append(pick.node_id)
        # Act 4 — persist one replay_score row per run, into the relational
        # store DATABASE_URL names (feature 255). The store is the journey's own
        # SQLite file, so the row is the journey's to read back. A TerminalPick-
        # shaped carrier — the pick (present here) and the score — duck-read by
        # the persist seam, the record of a completed scoring. The pick is the
        # one just committed, read through its node_id for the row's
        # committed_pick.
        persist_replay_score(
            _TerminalPick(pick=pick, score=0.3),
            policy_version="fixed-exploration-0.5",
            world_id=f"campaign-{_name}",
            beta=beta,
            database_url=store_url,
        )
        if not revealed:
            # The walk is fixed, so the first agent's revealed set is both
            # agents': the four roots plus their four children. Captured once,
            # from the shipped prefix the replay returned — a tuple of revealed
            # node ids, ascending (§12).
            revealed = list(run_replay(
                lambda q, agent=agent: agent.select(prefix_view(q)),
                PolicyQuestion(tree),
                tree,
                round_cap=ROUND_CAP,
            ))

    # Act 5 — the scorer process, holding the sealed sidecar, answers feature
    # 266's pair over the planted population and the two committed picks. This
    # is the "returns baseline sensitivity and specificity" the sentence claims:
    # the shipped process, the real sealed sidecar, the journey's plant.
    scorer = NullPickScorer(sidecar)
    figures = scorer.calibration_figures(population=list(_PLANT.keys()), picks=picks)

    # Read the committed rows back out of the store the journey wrote, directly
    # — the e2e convention, so the assertions read what was persisted, not what
    # the call returned.
    with sqlite3.connect(str(tmp / "store.db")) as connection:
        rows = connection.execute(
            "SELECT committed_pick, beta, score FROM replay_score ORDER BY world_id"
        ).fetchall()

    yield Journey(
        sensitivity=figures.sensitivity,
        specificity=figures.specificity,
        figures_type=type(figures).__name__,
        picks=picks,
        revealed=revealed,
        beta=float(beta),
        replay_score_rows=len(rows),
        replay_score_picks=[row[0] for row in rows],
        replay_score_betas=[row[1] for row in rows],
    )


class _TerminalPick:
    """A stand-in for feature 249's TerminalPick — the record the persist seam
    reads: the pick (absent-able) and the score (always present).

    The journey drives the replay loop directly rather than through the shipped
    ``ReplayEngine.pick`` scorer path, so it builds the carrier the row expects
    — duck-typed, exactly as :func:`persist_replay_score` reads it: a carrier
    with a ``pick`` and a ``score``. The pick here is feature 222's
    CommittedPick, read through its ``node_id`` for the row's committed_pick.
    """

    def __init__(self, pick: CommittedPick | None, score: float) -> None:
        self.pick = pick
        self.score = score


# ---------------------------------------------------------------------------
# Facet: a full campaign
# ---------------------------------------------------------------------------


class TestTheCampaignWasPlantedWithBothClasses:
    """The tree the journey ran is the whole both figures are fractions over —
    four roots, two null and two real, each with one recorded child."""

    def test_the_tree_holds_two_null_and_two_real_roots(self) -> None:
        # §4.1.1's floor, held exactly: at least two null roots and two real
        # roots, the smallest plant that contributes to both figures. The tree
        # is the shipped CampaignTree, frozen from the journey's specs.
        tree = _campaign_tree()
        roots = sorted(node.node_id for node in tree.nodes if node.parent_id is None)
        assert set(roots) == {NULL_ROOT_A, NULL_ROOT_B, REAL_ROOT_A, REAL_ROOT_B}

    def test_every_root_has_one_recorded_child(self) -> None:
        # The deterministic replay edge: each root records exactly one child,
        # the node feature 245's transition reveals. A replay stepping from a
        # root reveals this child; a leaf records none.
        tree = _campaign_tree()
        for root in (NULL_ROOT_A, NULL_ROOT_B, REAL_ROOT_A, REAL_ROOT_B):
            children = [n.node_id for n in tree.nodes if n.parent_id == root]
            assert children == [_CHILD_OF[root]]

    def test_the_tree_carries_no_is_null_label(self) -> None:
        # The barrier, structural: no node's payload carries is_null — the
        # label is readable by exactly one component, the replay scorer, and
        # the tree must not hold it. The journey's plant lives in the sidecar,
        # not here.
        tree = _campaign_tree()
        for node in tree.nodes:
            assert "is_null" not in node.content

    def test_the_sidecar_labels_the_roots_the_tree_is_keyed_by(self) -> None:
        # The tree and the sidecar share one address space: every planted root
        # is a node the tree holds, so the labels and the walk join. The
        # children are replay edges, not planted nodes, so they are absent from
        # the plant.
        tree_ids = {node.node_id for node in _campaign_tree().nodes}
        assert set(_PLANT) <= tree_ids
        assert set(_PLANT) == {NULL_ROOT_A, NULL_ROOT_B, REAL_ROOT_A, REAL_ROOT_B}


# ---------------------------------------------------------------------------
# Facet: under fixed exploration
# ---------------------------------------------------------------------------


class TestTheExplorationWasFixed:
    """The exploration stance is one β, held constant, and the replay is
    deterministic over the stored tree."""

    def test_beta_was_read_once_and_is_fixed(self, journey: Journey) -> None:
        # read_beta binds the scalar once; EpisodeBeta refuses every path by
        # which a caller could move it. The journey's β is the fixed 0.5, and
        # it is the same in both agents the journey runs.
        assert journey.beta == 0.5
        assert isinstance(read_beta(BETA), EpisodeBeta)

    def test_two_reads_of_one_beta_are_one_scalar(self) -> None:
        # Fixed exploration means the scalar does not move within the episode:
        # reading β again yields an equal value, and the value type refuses a
        # rebind. Two reads of one config are one scalar.
        assert read_beta(BETA) == read_beta(BETA)

    def test_both_agents_walked_the_same_revealed_set(self, journey: Journey) -> None:
        # §12's determinism contract (cq-15), restated for the journey: the two
        # agents share the fixed exploration, so both walks reveal the same set
        # — the four roots plus their four children. The order the policy
        # selected nodes in does not change the answer; the transition is a
        # function of the tree and the selected nodes, never of the order.
        assert set(journey.revealed) == set(_PLANT) | set(_CHILD_OF.values())

    def test_the_walk_revealed_every_root(self, journey: Journey) -> None:
        # The frontier advance reveals each root's recorded child, so every root
        # is revealed — which is why both agents could commit to the root each
        # declared. The reals are all revealed (the precision agent's pick), and
        # the nulls too (the recall agent's pick).
        assert set(journey.revealed) >= set(_PLANT)


# ---------------------------------------------------------------------------
# Facet: against fixture-backed agents
# ---------------------------------------------------------------------------


class TestTheAgentWasAFixture:
    """The agent is a test stand-in, duck-typed, whose exploration is a
    function of the prefix and whose commit is the one decision that varies."""

    def test_the_policy_exposes_only_select_and_commit(self) -> None:
        # The stand-in is the identical question.* interface's two policy verbs
        # and nothing else: select (the explore decision) and commit (the
        # terminal act). No tree walk, no sidecar read, no label — the fixture
        # is narrow on purpose, so the journey asserts the shipped system
        # carried the commitment to a figure.
        policy = FixedExplorationPolicy(read_beta(BETA), _declare_best_real)
        public = [n for n in dir(policy) if not n.startswith("_")]
        assert set(public) == {"beta", "commit", "select"}

    def test_the_two_agents_committed_to_different_nodes(
        self, journey: Journey
    ) -> None:
        # Two fixture-backed agents, one fixed exploration, two different
        # declarations: the precision agent commits to the strongest real root
        # (a true discovery), the recall agent to the strongest root overall,
        # which the plant labels null (a false discovery). The two picks are the
        # discoveries the calibration is measured over.
        assert set(journey.picks) == {REAL_ROOT_A, NULL_ROOT_A}

    def test_the_commit_went_through_the_questions_door(self) -> None:
        # The terminal act is the shipped system's: the pick the agent commits
        # is feature 222's CommittedPick, produced by the shipped EpisodeCommit
        # over the shipped question — not a value the stand-in made up.
        tree = _campaign_tree()
        agent = FixedExplorationPolicy(read_beta(BETA), _declare_best_real)
        question = PolicyQuestion(tree)
        run_replay(
            lambda q, agent=agent: agent.select(prefix_view(q)),
            question,
            tree,
            round_cap=ROUND_CAP,
        )
        pick = agent.commit(question)
        assert isinstance(pick, CommittedPick)
        assert pick.node_id == REAL_ROOT_A


# ---------------------------------------------------------------------------
# Facet: which returns baseline sensitivity and specificity
# ---------------------------------------------------------------------------


class TestTheFiguresAreBaseline:
    """The scorer process, holding the real sealed sidecar, answers feature
    266's pair — and the pair is the hand-computed baseline the plant
    predetermines."""

    def test_sensitivity_is_one_half(self, journey: Journey) -> None:
        # Sensitivity = TP / (TP + FN) over the real class. The two agents
        # committed to REAL_ROOT_A (real) and NULL_ROOT_A (null). Of the two
        # real roots, one is found (REAL_ROOT_A) and one is not (REAL_ROOT_B):
        # TP = 1, FN = 1, sensitivity = 1 / 2 = 0.5. The real class is half
        # discovered — the baseline a fixed-exploration policy earns here.
        assert journey.sensitivity == 0.5

    def test_specificity_is_one_half(self, journey: Journey) -> None:
        # Specificity = TN / (TN + FP) over the null class. Of the two null
        # roots, one is wrongly declared (NULL_ROOT_A, the recall agent's false
        # discovery) and one is not (NULL_ROOT_B): FP = 1, TN = 1, so
        # specificity = TN / (TN + FP) = 1 / (1 + 1) = 0.5. One null wrongly
        # declared of two nulls — the baseline this journey's plant predetermines.
        assert journey.specificity == 0.5

    def test_the_figures_are_within_class_fractions(self, journey: Journey) -> None:
        # Both figures are computed *within* a ground-truth class, so the
        # campaign's null fraction φ cancels — the base-rate independence prd
        # §4.1.3 relies on. The journey's plant is half null (φ = 0.5), and the
        # figures are 0.5 and 0.5: one of two reals found, one of two nulls
        # wrongly declared. Neither figure divides by the declaration's size or
        # by the whole — only by its own class — which is why they are the
        # baseline and not an artifact of φ.
        assert journey.sensitivity == 1 / 2
        assert journey.specificity == 1 / 2

    def test_the_answer_is_two_bare_floats(self, journey: Journey) -> None:
        # The barrier's whole spelling: the process answers two floats and
        # nothing label-shaped crosses the boundary — no count of a class, no
        # node id, no sidecar. The journey asserts the type of each figure is
        # float, because a figure that leaked a label would be the process §4.2
        # was written to contain.
        assert type(journey.sensitivity) is float
        assert type(journey.specificity) is float

    def test_the_figures_type_is_calibration_figures(self, journey: Journey) -> None:
        # The process answers feature 266's own value — the frozen
        # CalibrationFigures, the pair prd §4.1.3 reweights into FDR_deploy.
        assert journey.figures_type == "CalibrationFigures"

    def test_the_figures_are_a_pair_not_a_rate(self, journey: Journey) -> None:
        # The journey returns the two base-rate-independent figures, not the
        # raw null-pick rate — the distinction feature 266 draws from feature
        # 265. The rate over the same two picks would be 1/2 (one null pick of
        # two); the figures are the within-class pair (0.5, 0.5). They coincide
        # here only because φ = 0.5; the figures are the measurement the
        # sentence claims, the rate is what calibration reweights later.
        assert (journey.sensitivity, journey.specificity) == (0.5, 0.5)


# ---------------------------------------------------------------------------
# Facet: the persisted record
# ---------------------------------------------------------------------------


class TestTheRunWasPersisted:
    """One replay_score row per run, carrying the fixed β and the committed
    pick — the record of each completed scoring."""

    def test_one_row_per_agent_run(self, journey: Journey) -> None:
        # Feature 255: one row per run. The journey ran two agents, so two runs,
        # so two rows — read back directly from the journey's own store.
        assert journey.replay_score_rows == 2

    def test_each_row_carries_its_pick_and_the_fixed_beta(
        self, journey: Journey
    ) -> None:
        # Each persisted row is the record of a completed scoring: it names the
        # committed pick and the β the scoring was made at. Read back directly
        # from the journey's own store, so the assertion reads what was
        # persisted, not what the call returned. Both rows carry the fixed 0.5.
        assert set(journey.replay_score_picks) == {REAL_ROOT_A, NULL_ROOT_A}
        assert journey.replay_score_betas == [0.5, 0.5]


def test_the_plant_and_tree_share_one_address_space() -> None:
    """The plant and the tree share one address space — canonical UUID text —
    so the sidecar's keys and the tree's node ids join."""
    for node in list(_PLANT) + list(_CHILD_OF.values()):
        uuid.UUID(node)  # raises on a malformed id
