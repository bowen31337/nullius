"""System rejects the merge when the policy interface exposes an unrevealed
score to a prefix-only caller.

app_spec.xml feature 364 — the "System Invariant CI Gates" category's policy
prefix-score barrier — is the merge-time form of the law the whole exploration
policy runtime exists to enforce. docs/nullius-tech-architecture.md §10.2 makes
the ``question.*`` surface an exploration policy is handed during replay
*prefix-only*: a policy sees only the cells it has already revealed, never an
unrevealed node by any path. docs/alpha-engine-prd.md §12 states the invariant
the barrier serves, quoted whole because every clause of it is load-bearing
here::

    The exploration policy sees prefix-only information. No unrevealed
    scores, no absolute score targets, no filesystem access, no imports
    outside an allowlist.

The sentence this gate enforces is the first clause of that invariant, taken at
its word — *"No unrevealed scores"* — and it asks the question a merge gate can
ask before any replay has run: **does this merge expose the score of a cell the
caller has not revealed, through the prefix-only interface?**

**The two terms, stated exactly.** The clause has two terms and both are judged
here, and the finding is their conjunction.

* **An unrevealed score.** A *score* is the in-sample reading a revealed cell's
  observation carries — the two metric fields feature 217 froze for
  :class:`policy_runtime.PolicyObservation`, ``r2_insample`` and
  ``ic_insample`` — the honest payload-derived reading the tree exists to give
  (docs §11, the identical ``question.*`` interface). A *score* is therefore a
  value of one of those two fields, and nothing else: the observation's other
  two fields — ``n_periods`` and ``n_features`` — are the cell's own
  diagnostics, not a score, and a cell carrying them unrevealed is not this
  sentence's finding. A cell's *meta* — feature 219's
  :class:`policy_runtime.CellMeta`, the four structural fields ``branch``,
  ``depth``, ``parent`` and ``theme_root`` — is the tree's *shape*, and the
  barrier deliberately exposes it for any node the tree holds, revealed or not
  (docs §11.1: ``theme_root`` is exposed in ``meta()`` so family-conditional
  thresholds can be authored *before* the cells they condition are revealed).
  So structure is not a score, and a merge that exposes the structure of an
  unrevealed cell is not this sentence's finding — the barrier's edge is drawn
  between *what a cell scored* and *where it sits*, and this gate names only the
  former.

* **A prefix-only caller.** The caller is the object a replay hands authored
  policy code — feature 217's :class:`policy_runtime.PolicyQuestion`, the
  wrapper that remembers which cells have been revealed and is the thing a
  policy *extends* that set through. It is prefix-only: a policy holding it
  holds only what it has already revealed, and the seam that decides whether a
  cell is revealed is the question's own reveal set. A caller that has not
  revealed a cell is a question whose reveal set does not contain that cell's
  id — and the barrier's whole promise is that such a caller reads nothing of
  that cell's score, by any path.

**Why the operative seam is the question's reveal set, and not the tree's
edges.** This matters enough to state as a proof from the shipped code, because
the other reading — *any cell whose payload carries a score is a finding* —
would refuse merges for a state the runtime is built around. The question fronts
a tree, and the tree holds every node the campaign contains — the root and both
leaves in the canonical fixture — whether or not the policy has revealed them.
The question's :meth:`~policy_runtime.PolicyQuestion.observed` accessor is
prefix-only by construction: it iterates the question's own reveal set and
builds one observation per revealed node, so an unrevealed node is *absent* from
the returned mapping rather than filtered out of it. The tree is the ground
truth; the reveal set is the policy's view of it; and the barrier is the fact
that the two are not the same object. A merge that exposed the tree's scores to
a caller that had not revealed them would be handing the policy the whole
campaign behind one walk — precisely the leak §10.2 exists to close. So the
finding is caught by asking the question what a caller that has revealed a given
cell can read, rather than by scanning the tree for scores, so a merge cannot
weaken both the reading and this audit in step.

**The one seam that deliberately reaches unrevealed cells — and the face it must
not break.** Feature 219's :meth:`~policy_runtime.PolicyQuestion.meta` answers a
cell's structure for *any* node the tree holds, revealed or not — the barrier's
edge, stated as a reachable verb. That openness is the point: structure is not
the fact the barrier withholds, scores are. But the same openness is the one
place a merge could smuggle a score past the barrier — a ``meta`` that returned
a fifth field, a ``CellMeta`` that carried ``r2_insample`` beside ``depth``, a
payload read that reached for the in-sample metrics under a structural name.
The barrier therefore has two faces over this one seam, and the audit pins both:

* the *structure* face — ``meta`` still answers the four structural fields for
  an unrevealed cell, so the merge has not *withdrawn* the structure the barrier
  permits; and
* the *score* face — ``meta`` carries no score, so the merge has not *added* the
  score the barrier forbids.

**The score fields are read by name, not by type.** A merge could rename the
observation's fields, add a field, or carry the score under a different spelling
— and a gate that pinned the field names as literals would agree with itself and
pass a merge that moved the score. So the gate reads the observation's fields
from the class the merge ships — :class:`policy_runtime.PolicyObservation`'s own
:data:`~policy_runtime.PolicyObservation` field set — and asks, per cell, whether
the question exposes a value of one of those fields for a cell the caller has
not revealed. The score fields are the observation's, read as data; the gate
names them once, from the class, and holds that spelling against every seam.

**The score fields are the observation's, and the meta's are the meta's — and
the two must not share a field.** The barrier's edge is drawn between a score
and a structure, and that edge is a fact about two disjoint field sets: the
observation's ``r2_insample`` and ``ic_insample``, and the meta's ``branch``,
``depth``, ``parent`` and ``theme_root``. A field in both would be a score that
is also a structure — a cell's ``depth`` that is also its ``r2_insample`` — and
the barrier would not know which law to apply. So the gate pins that the two
sets are disjoint, over the classes the merge ships: the finding is not merely
that a seam leaks a score, but that the score and the structure are the same
kind of thing. A merge that collapsed the two — a ``CellMeta`` carrying a score,
an observation carrying a structural field the meta owns — fails here.

**The finding is per cell, and it is exactly a cell whose score a prefix-only
caller can read.** A cell the caller has revealed is not the finding — the
caller earned that reading. A cell the tree does not hold is not the finding —
there is no score to expose. A structural field of an unrevealed cell is not the
finding — structure is exposed on purpose. The finding is a score field of an
unrevealed cell, reachable through the prefix-only interface, and the gate names
the cell and the field so the operator reads the break off the interface rather
than re-deriving it.

**Why CI, and why the harm is silent.** A policy that could read the score of a
cell it has not revealed would be reading the campaign's answer key — it would
know, before it committed, which cell scored and which did not, and the whole of
the exploration mandate — to terminate on its statistical budget rather than on
how well it is doing (feature 221's ``budget_remaining()``) — would be a
formality over a game it had already seen the end of. The harm is silent because
the leak is a *reachable value*, not a wrong one: the policy reads a number it
was promised it could not, and no assertion in the replay loop catches it,
because the replay loop is built on the promise that the interface is
prefix-only. That promise ships in merges too, so this gate holds it as data:
the observation carries the score, the question's reveal set decides what is
revealed, and the gate's own judgement needs no replay — the evaluators are pure
functions of a question and a cell, pinned statically below, because a gate that
had to run a replay to judge it would be an audit after the leak.

**What this gate is not, asserted as hard as what it is.** It is not feature
217's prefix-only ``observed`` — that accessor is the barrier's read side, and
this gate reads *through* it rather than judging it; a merge that weakened
``observed`` to include unrevealed nodes is caught here, but the gate does not
restate ``observed``'s comparison, it asks it. It is not feature 219's ``meta``
— structure is exposed on purpose, and a merge that withdrew structure from an
unrevealed cell is not this sentence's finding; the gate pins that structure is
still reachable, so it does not mistake a correct barrier for a leak. It is not
feature 223's ``prefix_view`` or feature 224's ``policy_surface`` — those close
the object and the world around it, and this gate is the score's; a view that
held the tree behind an underscore is a different leak, and a surface that
answered ``best_so_far`` is feature 224's, never this one's. It is not feature
184's sibling-pool accessor either — that pool's ``meta`` refuses only a node
*"outside the lattice"*, and the identical-interface law needs the barrier's
edge in the same place on both sides, which is why this gate judges the
campaign side's structure exposure rather than restating the sibling pool's. And
it is not the member suites' own tests — those pin the barrier from inside; this
gate reads what a merge carries, from outside it, and adds the face no
member-side test can promise: a seam that *exposes* a score of an unrevealed
cell refuses the merge whatever else it does.

**Stdlib and the member's own packages, and nothing else.** The gate reads
``policy_runtime`` — the question, the observation, the meta, the tree and the
view — and it loads nothing that opens, drives or settles a connection. Every
evaluator is a pure function of a question and a cell, and every judgement is
pinned statically, because the barrier is a fact about the interface rather than
about a replay.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect

import policy_runtime as member
from policy_runtime import (
    CampaignTree,
    CellMeta,
    PolicyObservation,
    PolicyQuestion,
    cell_meta,
    policy_question,
)

# ── The law's own spellings, restated as data ────────────────────────────────

#: The score fields — the in-sample metric fields feature 217 froze for a
#: revealed cell's observation. A value of one of these, for a cell the caller
#: has not revealed, is the finding. Read from the class the merge ships rather
#: than restated here, so a merge that renamed, added or dropped a field moves
#: every witness below with it — and this suite cannot pass by agreeing with
#: itself about which fields a score is. The observation's ``node_id`` is the
#: cell's address, and ``n_periods`` and ``n_features`` are its diagnostics;
#: neither is a score, so both are excluded.
SCORE_FIELDS: tuple[str, ...] = tuple(
    field.name
    for field in dataclasses.fields(PolicyObservation)
    if field.name in {"r2_insample", "ic_insample"}
)

#: The structural fields — feature 219's four, the shape the barrier exposes for
#: any node the tree holds. Read from the class the merge ships, for the same
#: reason the score fields are read from theirs.
STRUCTURE_FIELDS: tuple[str, ...] = tuple(
    field.name for field in dataclasses.fields(CellMeta)
)

#: The gate's tree identities: a parent, a campaign, and the three cells the
#: canonical fixture holds — a root (structural, carrying no score) and two
#: scored leaves.
GATE_PARENT = "11111111-1111-4111-8111-111111111111"
GATE_CAMPAIGN = "22222222-2222-4222-8222-222222222222"
ROOT = "n0"
LEAF_A = "n1"
LEAF_B = "n2"

#: The score a scored leaf carries — the honest in-sample reading the tree
#: exists to give. The two values are distinct, so a leak of one cell's score is
#: not mistaken for the other's.
LEAF_A_R2 = 0.20
LEAF_A_IC = 0.05
LEAF_B_R2 = 0.33
LEAF_B_IC = 0.09


def _tree() -> CampaignTree:
    """The canonical campaign tree — a root and two scored leaves.

    The root carries no in-sample reading (a structural node); each leaf carries
    the metrics a reveal reads off it. Built through the public constructor, so
    the gate judges the shipped tree rather than a fixture invented to pass it.
    """
    return CampaignTree.freeze(
        {
            ROOT: (None, 0, {"depth": 0}),
            LEAF_A: (
                ROOT,
                1,
                {
                    "parent_id": ROOT,
                    "depth": 1,
                    "r2_insample": LEAF_A_R2,
                    "ic_insample": LEAF_A_IC,
                    "n_periods": 500,
                    "n_features": 12,
                },
            ),
            LEAF_B: (
                ROOT,
                1,
                {
                    "parent_id": ROOT,
                    "depth": 1,
                    "r2_insample": LEAF_B_R2,
                    "ic_insample": LEAF_B_IC,
                    "n_periods": 500,
                    "n_features": 12,
                },
            ),
        }
    )


class _LeakingQuestion:
    """The stand-in for the merge a weakened barrier *is*: its ``observed``
    returns every cell's observation whether or not the caller revealed it.

    The merge this gate exists to catch. A policy holding it reads any cell's
    score without a reveal — the leak feature 364 refuses. It fronts the same
    tree, answers ``meta`` for any cell (structure is exposed on purpose, and a
    weakened score barrier does not withdraw it), and carries a reveal set the
    audit consults, so the finding is the *conjunction* the sentence states: the
    interface exposes the cell's score **and** the caller has not revealed it. A
    cell the stand-in reveals is earned, not a finding — so the leak is the
    unrevealed cells alone, exactly the sentence's. It is spelled as a class
    rather than monkeypatched, so the mutation is in plain sight: the argument
    for what a weakened barrier does to the interface, stated where a reader can
    check it rather than hidden in a fixture.
    """

    def __init__(self, tree: CampaignTree, revealed: frozenset[str] = frozenset()) -> None:
        self._tree = tree
        self._revealed = frozenset(revealed)

    @property
    def tree(self) -> CampaignTree:
        return self._tree

    @property
    def revealed(self) -> frozenset[str]:
        return self._revealed

    def observed(self) -> dict[str, PolicyObservation]:
        # The leak: every cell, scored or not, whether or not it was revealed —
        # the barrier's read side rewritten so an unrevealed node is *present*
        # rather than absent. A scored leaf the caller has not revealed is a
        # key here, which is the finding.
        return {
            node.node_id: PolicyObservation.from_node(node) for node in self._tree.nodes
        }

    def meta(self, node_id: str) -> CellMeta:
        return cell_meta(self._tree, node_id)


# ── The evaluators: the finding as a pure function of a question and a cell ──


def score_of(question: PolicyQuestion, node_id: str) -> tuple[str, ...]:
    """The score fields of ``node_id`` the question exposes — the reading, per cell.

    Asks the question's own :meth:`~policy_runtime.PolicyQuestion.observed`
    accessor — the barrier's read side, asked rather than restated — for the
    cell's observation, and names the score fields whose value is not ``None``.
    A score a cell does not carry is not a score the interface exposes, so a
    structural cell (the root) answers no score field, and a scored leaf answers
    both. The reveal set is not consulted: the finding is what the question
    exposes for a cell, and whether the caller has revealed it is the audit's
    question, not this reading's. The fields are returned sorted, so a cell's
    score reads the same whatever order the observation declares them — the same
    ordering ``merge_refusal`` gives its findings, so the two never disagree.
    """
    observation = question.observed().get(node_id)
    if observation is None:
        return ()
    return tuple(
        sorted(
            field
            for field in SCORE_FIELDS
            if getattr(observation, field) is not None
        )
    )


def structure_of(question: PolicyQuestion, node_id: str) -> CellMeta | None:
    """The structure ``meta`` answers for a cell — the barrier's edge, reachable.

    Asks the question's :meth:`~policy_runtime.PolicyQuestion.meta` for the cell,
    without revealing it — the one seam that deliberately reaches unrevealed
    cells. A cell the tree holds answers its structure, revealed or not; a cell
    the tree does not hold is refused by the address seam. The gate pins that
    this answer is still reachable (structure is exposed on purpose) and that it
    carries no score (the barrier holds).
    """
    return question.meta(node_id)


def merge_refusal(question: PolicyQuestion) -> tuple[tuple[str, str], ...]:
    """The gate itself: every score field of every cell the caller has *not*
    revealed, reachable through the prefix-only interface, over the question's
    tree.

    The merge-time form of feature 364's sentence. The caller is the question —
    the object a replay hands authored policy code — and the finding is a score
    field of a cell the caller has not revealed: the question exposes the cell's
    score (the reading above names it) and the caller's reveal set does not
    contain the cell. Computed by reading the interface, never by scanning the
    tree: the question is the thing being judged, and a gate that read the
    tree's scores directly would be judging the ground truth rather than the
    leak. Each finding is ``(node_id, field)``, sorted, so the operator reads the
    break off the interface rather than re-deriving it. Empty means no
    unrevealed cell's score is reachable through the interface; the merge stands.
    """
    findings: list[tuple[str, str]] = []
    for node in question.tree.nodes:
        if node.node_id in question.revealed:
            continue
        findings.extend(
            (node.node_id, field) for field in score_of(question, node.node_id)
        )
    return tuple(sorted(findings))


# ── The gate reads the interface the merge carries ───────────────────────────


class TestTheGateReadsTheInterfaceTheMergeCarries:
    """The gate judges the observation's score fields, the meta's structure
    fields, and the disjointness of the two — as data, without a replay."""

    def test_the_gate_reads_the_observation_the_merge_ships(self) -> None:
        # The score fields are the observation's, read as data from the class the
        # merge ships — never restated here. A gate that retyped them could agree
        # with itself and pass a merge that moved the score; this one fails the
        # moment the observation's fields move or change. It names exactly the
        # two in-sample metric fields the barrier withholds, and no diagnostic.
        assert SCORE_FIELDS == ("r2_insample", "ic_insample")
        assert member.PolicyObservation is PolicyObservation

    def test_the_gate_reads_the_meta_the_merge_ships(self) -> None:
        # The structure fields are the meta's, read as data from the class the
        # merge ships — never restated here, for the same reason. It names
        # exactly the four structural fields the barrier exposes, and no score.
        assert STRUCTURE_FIELDS == ("branch", "depth", "parent", "theme_root")
        assert member.CellMeta is CellMeta

    def test_the_score_and_structure_fields_are_disjoint(self) -> None:
        # The barrier's edge is a fact about two disjoint field sets: a score is
        # never a structure, and a structure is never a score. A field in both
        # would be the barrier not knowing which law to apply — a cell's depth
        # that is also its r2. The gate pins the disjointness over the classes
        # the merge ships, so a merge that collapsed the two fails here.
        assert set(SCORE_FIELDS).isdisjoint(STRUCTURE_FIELDS)

    def test_the_finding_is_a_pure_function_of_a_question_and_a_cell(self) -> None:
        # The evaluator's input is a question and a cell and nothing else — the
        # same static discipline the provenance and ledger gates apply to their
        # evaluators. None of the gate's evaluators touches anything that could
        # open, drive or settle a connection — a gate that had to run a replay to
        # judge it would be an audit after the leak.
        for evaluator in (score_of, structure_of, merge_refusal):
            tree = ast.parse(inspect.getsource(evaluator))
            database_names = [
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr
                in {
                    "connect",
                    "cursor",
                    "execute",
                    "executescript",
                    "commit",
                    "rollback",
                }
            ]
            assert database_names == [], evaluator.__name__

    def test_the_gate_reads_the_tree_through_the_question(self) -> None:
        # The gate reads the cells through the question's own tree — the thing
        # being judged — never a restatement of the tree. A question fronts a
        # tree, and the tree holds every node the campaign contains; the gate
        # walks the question's tree so the finding is what the interface exposes,
        # not what a parallel construction holds.
        question = policy_question(_tree())
        assert [node.node_id for node in question.tree.nodes] == [ROOT, LEAF_A, LEAF_B]


# ── A merge whose interface is prefix-only stands ────────────────────────────


class TestAMergeWhoseInterfaceIsPrefixOnlyStands:
    """The shipped interface, exercised once, exposes no unrevealed cell's score
    — the merge stands by construction."""

    def test_an_unrevealed_cell_is_absent_from_observed(self) -> None:
        # The barrier's read side, pinned: a caller that has revealed nothing
        # reads an empty observed mapping, and a scored leaf the tree holds is
        # absent from it — never a key, never a value. The leak would be the
        # cell present; the barrier is its absence.
        question = policy_question(_tree())
        assert question.observed() == {}
        assert LEAF_A not in question.observed()

    def test_a_revealed_cell_carries_its_score(self) -> None:
        # The stands case's positive half: a caller that *has* revealed a scored
        # leaf reads its score — the honest in-sample reading, attributed. A
        # gate that refused this would be refusing the barrier's own purpose,
        # which is to let a caller read what it has earned. The reveal is the
        # caller's act, and the reading is the reward for it.
        question = policy_question(_tree())
        question.reveal(LEAF_A)
        observation = question.observed()[LEAF_A]
        assert observation.r2_insample == LEAF_A_R2
        assert observation.ic_insample == LEAF_A_IC

    def test_meta_answers_structure_for_an_unrevealed_cell(self) -> None:
        # The barrier's edge, reachable: ``meta`` answers the four structural
        # fields for a scored leaf the caller has not revealed. The gate pins
        # that structure is still exposed — so a merge that withdrew it is not
        # mistaken for a correct barrier — and that it carries no score.
        question = policy_question(_tree())
        meta = structure_of(question, LEAF_A)
        assert meta is not None
        assert meta.depth == 1
        assert meta.theme_root is None or isinstance(meta.theme_root, str)
        for field in SCORE_FIELDS:
            assert not hasattr(meta, field)

    def test_a_prefix_only_interface_exposes_no_unrevealed_score(self) -> None:
        # The load-bearing stands case: a caller that has revealed nothing reads
        # no scored leaf's score, through the interface the merge ships. The
        # tree holds two scored leaves; the caller holds neither; the finding is
        # empty, so the merge stands.
        question = policy_question(_tree())
        assert merge_refusal(question) == ()

    def test_revealing_a_cell_earns_its_score_but_not_the_other(self) -> None:
        # The barrier is per cell: revealing one leaf earns that leaf's score and
        # leaves the other's score unrevealed — and the shipped interface is
        # prefix-only, so the unrevealed leaf stays *absent* from ``observed``,
        # not present. A caller that has revealed n1 reads n1's r2 and ic, and
        # reads nothing of n2's because n2 is not in the mapping at all. The gate
        # is sound against the venue by construction: whenever the caller has
        # earned a reading and the interface is prefix-only, the gate names
        # nothing. The finding appears only when the interface itself leaks — the
        # stand-in cases below.
        question = policy_question(_tree())
        question.reveal(LEAF_A)
        assert LEAF_A in question.observed()
        assert LEAF_B not in question.observed()
        assert merge_refusal(question) == ()

    def test_a_leaking_interface_is_refused_for_its_unrevealed_scores(self) -> None:
        # The merge a weakened barrier *is*: its ``observed`` returns every cell
        # whether or not the caller revealed it, so a scored leaf the caller has
        # not revealed is present in the mapping — the leak. The finding is the
        # *conjunction* the sentence states: the interface exposes the cell's
        # score **and** the caller has not revealed it. The stand-in reveals
        # nothing, so both scored leaves are the finding; the root carries no
        # score and is not named.
        stand_in = _LeakingQuestion(_tree())
        assert merge_refusal(stand_in) == (
            (LEAF_A, "ic_insample"),
            (LEAF_A, "r2_insample"),
            (LEAF_B, "ic_insample"),
            (LEAF_B, "r2_insample"),
        )

    def test_a_leaking_interface_still_exposes_structure(self) -> None:
        # A weakened score barrier does not withdraw the structure the barrier
        # permits: the stand-in's ``meta`` still answers a scored leaf's
        # structure for an unrevealed cell, so the finding is the score alone and
        # the gate does not mistake the permitted structure for the leak.
        stand_in = _LeakingQuestion(_tree())
        meta = structure_of(stand_in, LEAF_A)
        assert meta is not None
        assert meta.depth == 1
        assert merge_refusal(stand_in) == (
            (LEAF_A, "ic_insample"),
            (LEAF_A, "r2_insample"),
            (LEAF_B, "ic_insample"),
            (LEAF_B, "r2_insample"),
        )

    def test_a_leaking_interface_earns_a_revealed_cells_score(self) -> None:
        # The finding is the conjunction, and the stand-in's reveal set is
        # honoured: a cell the stand-in *has* revealed is earned, not a finding,
        # however leaky its ``observed`` is. Revealing n1 leaves only n2's score
        # as the finding — the leak is the unrevealed cell alone, exactly the
        # sentence's.
        stand_in = _LeakingQuestion(_tree(), revealed=frozenset({LEAF_A}))
        assert merge_refusal(stand_in) == (
            (LEAF_B, "ic_insample"),
            (LEAF_B, "r2_insample"),
        )

    def test_a_structural_cell_carries_no_score(self) -> None:
        # The root carries no in-sample reading — a structural node, not a scored
        # leaf — so its observation answers None for each score field, and the
        # gate names no score for it. A cell that carries no score has no score
        # to expose, revealed or not, and the finding is per cell, so the root is
        # never named however the caller's reveal set stands.
        question = policy_question(_tree())
        assert score_of(question, ROOT) == ()
        assert (ROOT, "r2_insample") not in merge_refusal(question)


# ── A merge whose interface exposes an unrevealed score is refused ───────────


class TestAMergeWhoseInterfaceExposesAnUnrevealedScoreIsRefused:
    """Any score of any cell a prefix-only caller has not revealed, reachable
    through the interface, refuses the merge — whatever authored the leak.

    The shipped interface is prefix-only, so the leak below is authored by a
    stand-in question — the merge a weakened barrier *is* — whose ``observed``
    returns the scored leaves whether or not they were revealed. The finding is
    then the score the interface exposes for an unrevealed cell, named with the
    cell and the field so the operator reads the break off the interface.
    """

    def test_an_unrevealed_scored_leaf_is_the_finding(self) -> None:
        # The sentence's finding, stated over data: a scored leaf the caller has
        # not revealed, whose score fields the interface exposes. The stand-in's
        # ``observed`` returns every cell whether or not it was revealed, so with
        # nothing revealed both scored leaves are the finding, each named with
        # its two score fields, in the interface's own order.
        stand_in = _LeakingQuestion(_tree())
        assert merge_refusal(stand_in) == (
            (LEAF_A, "ic_insample"),
            (LEAF_A, "r2_insample"),
            (LEAF_B, "ic_insample"),
            (LEAF_B, "r2_insample"),
        )

    def test_the_finding_names_the_cell_and_the_field(self) -> None:
        # The finding is per cell and per field, and each is named so the
        # operator reads the break off the interface: the cell that scored and
        # the score field reachable for it. A cell that carries no score is not
        # named; a field the cell does not carry is not named.
        stand_in = _LeakingQuestion(_tree())
        assert score_of(stand_in, LEAF_B) == ("ic_insample", "r2_insample")

    def test_the_finding_is_sorted_by_cell_then_field(self) -> None:
        # Every finding, in the interface's own order: a caller that can read
        # both scored leaves' scores reads them named in the tree's key order,
        # so the operator sees the whole shape of the break rather than the
        # first leak alone.
        stand_in = _LeakingQuestion(_tree())
        assert merge_refusal(stand_in) == tuple(sorted(merge_refusal(stand_in)))

    def test_a_diagnostic_field_of_an_unrevealed_cell_is_not_the_finding(self) -> None:
        # The scope is the score, not the cell's diagnostics. A scored leaf
        # carries ``n_periods`` and ``n_features`` — the cell's own diagnostics,
        # not a score — and the gate names neither. A gate that treated every
        # field of an unrevealed cell as a score would be refusing the barrier's
        # own purpose, which exposes the cell's honest reading to a caller that
        # has earned it and carries the diagnostics regardless.
        stand_in = _LeakingQuestion(_tree())
        findings = score_of(stand_in, LEAF_A)
        assert "n_periods" not in findings
        assert "n_features" not in findings

    def test_a_structural_field_of_an_unrevealed_cell_is_not_the_finding(self) -> None:
        # The scope is the score, not the structure. ``meta`` exposes the four
        # structural fields of an unrevealed cell on purpose, and the gate names
        # none of them — the barrier's edge holds between what a cell scored and
        # where it sits. A gate that treated structure as a score would be
        # refusing the one seam the barrier permits, and would name the whole
        # tree for every caller.
        stand_in = _LeakingQuestion(_tree())
        meta = structure_of(stand_in, LEAF_A)
        assert meta is not None
        assert meta.depth == 1
        assert merge_refusal(stand_in) == (
            (LEAF_A, "ic_insample"),
            (LEAF_A, "r2_insample"),
            (LEAF_B, "ic_insample"),
            (LEAF_B, "r2_insample"),
        )


# ── The finding is exactly the unrevealed score and nothing else ─────────────


class TestTheFindingIsExactlyTheUnrevealedScoreAndNothingElse:
    """The gate refuses exactly the sentence's finding: a score field of a cell
    the caller has not revealed, reachable through the prefix-only interface —
    never a revealed cell's earned reading, never a structural field, never a
    diagnostic, never a cell the tree does not hold."""

    def test_a_revealed_cells_score_is_not_the_finding(self) -> None:
        # The ordinary shape of a caller mid-walk, even for a leaking interface:
        # it has revealed a scored leaf and reads its score. Nothing on that
        # cell is the finding — the caller earned it. The gate names only the
        # cells the caller has not revealed, so a correct barrier that has handed
        # out earned readings is not refused. The stand-in leaks, but its reveal
        # set is honoured, so revealing n1 earns n1 and leaves only n2.
        stand_in = _LeakingQuestion(_tree(), revealed=frozenset({LEAF_A}))
        assert (LEAF_A, "r2_insample") not in merge_refusal(stand_in)
        assert merge_refusal(stand_in) == (
            (LEAF_B, "ic_insample"),
            (LEAF_B, "r2_insample"),
        )

    def test_a_cell_the_tree_does_not_hold_is_not_the_finding(self) -> None:
        # A cell the tree does not hold has no score to expose, and the finding
        # is per cell over the cells the tree holds, so a ghost node is never
        # named — the gate reads the question's tree, and a node outside it is
        # not on it. The stand-in leaks every cell it holds, but it holds no
        # ghost, so the ghost is absent from the finding.
        stand_in = _LeakingQuestion(_tree())
        assert score_of(stand_in, "ghost") == ()
        assert merge_refusal(stand_in) == (
            (LEAF_A, "ic_insample"),
            (LEAF_A, "r2_insample"),
            (LEAF_B, "ic_insample"),
            (LEAF_B, "r2_insample"),
        )

    def test_the_barrier_edge_holds_between_score_and_structure(self) -> None:
        # The identity the whole file rests on, stated over the leaking stand-in:
        # a scored leaf's structure is exposed (``meta`` answers it, revealed or
        # not), and its score is withheld only until the caller reveals it. For
        # every cell the tree holds, the structure is reachable; the score is the
        # finding for an unrevealed cell and earned for a revealed one. A merge
        # that moved either side of the edge fails here: a structure it
        # withholds, or a score it exposes.
        stand_in = _LeakingQuestion(_tree())
        for node_id in (LEAF_A, LEAF_B):
            assert structure_of(stand_in, node_id) is not None
            assert score_of(stand_in, node_id) == (
                "ic_insample",
                "r2_insample",
            )
        assert (LEAF_A, "depth") not in merge_refusal(stand_in)
        assert (LEAF_B, "theme_root") not in merge_refusal(stand_in)

    def test_the_gate_reads_the_score_through_the_interface(self) -> None:
        # The gate that reads the record never scans the ground truth: the
        # finding is what a prefix-only caller can read through the interface,
        # taken over the question's tree and never over a parallel construction.
        # A gate that read the tree's scores directly would be judging the
        # campaign rather than the leak, and would name a cell the interface
        # never exposed. The audit reads the question's own ``observed`` reading
        # (through ``score_of``) and filters it by the caller's ``revealed`` set
        # over ``question.tree.nodes`` — the interface, and nothing else. The
        # reading never reaches the node's raw payload: no ``content``, no
        # ``json``, no ``_observe`` — a score read from the bytes would be a
        # score read from the ground truth, not from the interface.
        source = inspect.getsource(merge_refusal)
        assert "question.revealed" in source
        assert "question.tree.nodes" in source
        assert "score_of" in source
        reading = inspect.getsource(score_of)
        assert "question.observed" in reading
        for forbidden in ("_tree", "_observe", "content", "json", "payload"):
            assert forbidden not in source, forbidden
            assert forbidden not in reading, forbidden
