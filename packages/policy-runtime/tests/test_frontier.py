"""Feature 218, the legal moves — §11's ``legal_actions`` and ``legal_roots``.

app_spec.xml, "Exploration Policy Runtime", feature 218: *System exposes
legal_actions which returns open frontier nodes plus legal_roots which returns
available research themes.*  docs/nullius-tech-architecture.md §593–594 spells
them as the third and fourth lines of the identical ``question.*`` interface::

    question.legal_actions()   -> list[node_id]
    question.legal_roots()     -> list[node_id]

and docs/alpha-engine-prd.md §419–420 repeats both, with the comment that fixes
the reading — ``# roots + open frontiers``.

This file pins the claims the feature is made of, in the order a policy meets
them:

* **where a walk may begin** — ``legal_roots()`` is the tree's parentless
  nodes, ascending, and each one is a research theme's opening node (prd §215);
* **where it may go next** — ``legal_actions(node_id)`` is the node's open
  frontier, one recorded edge on, ascending;
* **the two compose** — ``legal_actions(None)`` is where a walk begins, and a
  leaf answering ``[]`` is the fact prd §436's termination test is a test of;
* **the answer is a pure function of the tree** — the load-bearing negative of
  the whole feature: the reveal set is never consulted, so a frontier is stable
  across a probe and an unrevealed node is still a legal move.  This is what
  keeps "one policy, both pools" true *in the walk* rather than only in the
  reading (the sibling pool's ``legal_actions`` reads its lattice and never its
  reveal set), and it is the property a reveal-dependent implementation would
  pass every other test in this file while breaking;
* **neither verb grows the reveal set** — reading where you may go is not going;
* **the refusals** — a value that is not a node id, a node outside the tree, and
  a malformed tree, each in this member's own vocabulary so a caller's single
  ``except PolicyRuntimeError`` catches every way a frontier read can fail;
* **the free functions and the methods agree** — one derivation, two spellings.
"""

from __future__ import annotations

import pytest
from policy_runtime import (
    CampaignNode,
    CampaignTree,
    PolicyAddressError,
    PolicyQuestion,
    PolicyRuntimeError,
    PolicyTreeError,
    episode_commit,
    legal_actions,
    legal_roots,
    policy_question,
)

# ---------------------------------------------------------------------------
# A themed, multi-root tree — the shape a campaign actually has
# ---------------------------------------------------------------------------


@pytest.fixture
def themed_tree() -> CampaignTree:
    """A campaign tree with two roots, one branch of depth 2, and a bare root.

    The canonical conftest tree is single-rooted and two nodes wide, which is
    enough to pin a shape but not enough to pin the *feature*: ``legal_roots``
    over a one-root tree would pass even if it answered "the tree's first node"
    by accident, and a frontier of one node cannot show that the answer is a
    set.  This tree has

    * **two roots** in two different themes — so "roots" is a plurality and the
      theme claim (each root is a theme's opening node) is testable;
    * **a depth-2 branch** (``r-a`` → ``a2`` → ``a2x``) — so a node reached by
      two steps is a legal move of exactly its own parent, and ``a2x`` is *not*
      a move of ``r-a``: one edge, not reachability;
    * **a bare root** (``r-c``, no children) — so a root with nothing beneath it
      is still a place a walk may begin, and answers ``[]`` as a position.
    """
    return CampaignTree.freeze(
        {
            "r-a": (None, 0, {"depth": 0, "theme_root": "cross-sectional-momentum"}),
            "a1": ("r-a", 1, {"parent_id": "r-a", "depth": 1, "r2_insample": 0.20}),
            "a2": ("r-a", 1, {"parent_id": "r-a", "depth": 1, "r2_insample": 0.44}),
            "a2x": ("a2", 2, {"parent_id": "a2", "depth": 2, "r2_insample": 0.51}),
            "r-b": (None, 0, {"depth": 0, "theme_root": "event-driven"}),
            "b1": ("r-b", 1, {"parent_id": "r-b", "depth": 1, "r2_insample": 0.10}),
            "r-c": (None, 0, {"depth": 0, "theme_root": "microstructure"}),
        }
    )


@pytest.fixture
def themed_question(themed_tree: CampaignTree) -> PolicyQuestion:
    """The read-side question over the themed tree."""
    return policy_question(themed_tree)


# ---------------------------------------------------------------------------
# legal_roots — where a walk may begin, and what a root is
# ---------------------------------------------------------------------------


def test_legal_roots_answers_the_parentless_nodes(themed_question: PolicyQuestion) -> None:
    # The roots are the nodes whose parent is absent — the same test
    # discovery.manifest uses for a branch ("A branch is a root, parent_id IS
    # NULL") — and nothing else.  ``a1``/``a2``/``a2x``/``b1`` all name a parent,
    # so they are moves rather than places to begin.
    assert themed_question.legal_roots() == ["r-a", "r-b", "r-c"]


def test_legal_roots_is_ascending(themed_question: PolicyQuestion) -> None:
    # Ascending by node id, so a policy that enumerates without sorting sees a
    # deterministic order and two replays of one tree begin in the same
    # sequence — docs §12's ordering rule, restated for a search frontier as
    # `observed()` and the sibling pool's `legal_moves` both state it.
    roots = themed_question.legal_roots()
    assert roots == sorted(roots)


def test_legal_roots_returns_a_fresh_list_each_call(themed_question: PolicyQuestion) -> None:
    # A list the caller can sort, reverse or append to without moving the
    # question's answer: the frontier is computed per call, not held.  A shared
    # mutable list would let one caller's `reverse()` become the next caller's
    # answer, which is a frontier that depends on who read it.
    first = themed_question.legal_roots()
    first.append("tampered")
    first.reverse()
    assert themed_question.legal_roots() == ["r-a", "r-b", "r-c"]


def test_each_root_is_a_research_theme_opening(themed_question: PolicyQuestion) -> None:
    # The feature sentence's second half — "legal_roots which returns available
    # research themes" — read the way prd §215 fixes it: "Root = a fresh
    # research theme (§9)".  Each root the accessor returns is a theme's opening
    # node, which is what makes "the roots available to a walk" and "the
    # available research themes" one answer seen from two sides.  The theme
    # itself is read through feature 219's accessor, which is where docs §634
    # confines `theme_root`; 218 answers ids.
    themes = {root: themed_question.meta(root).theme_root for root in themed_question.legal_roots()}
    assert themes == {
        "r-a": "cross-sectional-momentum",
        "r-b": "event-driven",
        "r-c": "microstructure",
    }


def test_two_roots_in_one_theme_are_both_legal_roots() -> None:
    # The deliberate non-collapse: the roots are derived from `parent_id` and
    # NOT from `theme_root`, so two parentless nodes planted in one theme are
    # two places a walk may begin.  Collapsing them to one-node-per-theme would
    # answer a question about the *theme set* through an accessor whose subject
    # is *nodes*, and would silently drop a legal starting point.
    tree = CampaignTree.freeze(
        {
            "x1": (None, 0, {"depth": 0, "theme_root": "event-driven"}),
            "x2": (None, 0, {"depth": 0, "theme_root": "event-driven"}),
            "x1c": ("x1", 1, {"parent_id": "x1", "depth": 1}),
        }
    )
    question = policy_question(tree)
    assert question.legal_roots() == ["x1", "x2"]
    assert len({question.meta(root).theme_root for root in question.legal_roots()}) == 1


def test_a_root_with_no_children_is_still_a_legal_root(themed_question: PolicyQuestion) -> None:
    # `r-c` has nothing beneath it, and it is still a place a walk may begin —
    # a root is a root by its absent parent, not by its fertility.  The two
    # verbs answer different questions about it: it is a *root* (where to
    # begin) and simultaneously a *leaf* (nowhere to go from).
    assert "r-c" in themed_question.legal_roots()
    assert themed_question.legal_actions("r-c") == []


def test_legal_roots_of_the_canonical_single_rooted_tree(question: PolicyQuestion) -> None:
    # The conftest's tree has exactly one root, and the answer is a one-entry
    # list — the shape the sibling pool's `legal_roots()` returns for its single
    # canonical root, and the shape a policy unpacks: `(root,) = ...`.  A
    # campaign tree happens to have one root when the deployment planted one
    # theme; the plurality is the themed case above, not a requirement here.
    assert question.legal_roots() == ["n0"]


# ---------------------------------------------------------------------------
# legal_actions — the open frontier, one recorded edge on
# ---------------------------------------------------------------------------


def test_legal_actions_answers_the_open_frontier(themed_question: PolicyQuestion) -> None:
    # A position's legal moves are exactly the nodes that name it as their
    # parent: one recorded edge, no invention.  This is the batch a policy
    # standing at `r-a` may select next.
    assert themed_question.legal_actions("r-a") == ["a1", "a2"]


def test_legal_actions_is_one_edge_not_reachability(themed_question: PolicyQuestion) -> None:
    # `a2x` sits two steps below `r-a` and is NOT a move of `r-a`: the frontier
    # is the nodes one legal step on, so a policy walks the depth rather than
    # skipping it.  A reachability-based implementation would answer `a2x` here
    # and pass the test above.
    assert "a2x" not in themed_question.legal_actions("r-a")
    assert themed_question.legal_actions("a2") == ["a2x"]


def test_legal_actions_is_ascending(themed_question: PolicyQuestion) -> None:
    # Ascending, as `legal_roots` is and for the same reason.
    moves = themed_question.legal_actions("r-a")
    assert moves == sorted(moves)


def test_legal_actions_answers_empty_at_a_position_with_no_children(
    themed_question: PolicyQuestion,
) -> None:
    # THE load-bearing answer of the feature.  prd §436's "must terminate when
    # no batch is selected" and feature 3/242's "the policy has selected no
    # batch" are exactly this empty list: a leaf is a position with no move, and
    # a verb that refused here would leave a policy unable to tell "nowhere left
    # to go" from "you asked wrongly".  Terminating is a decision, and this verb
    # hands the policy the fact it decides on.
    assert themed_question.legal_actions("a1") == []
    assert themed_question.legal_actions("a2x") == []
    assert themed_question.legal_actions("b1") == []


def test_legal_actions_returns_a_fresh_list_each_call(themed_question: PolicyQuestion) -> None:
    # As `legal_roots`: per-call computation, so one caller's mutation is not
    # the next caller's frontier.
    first = themed_question.legal_actions("r-a")
    first.append("tampered")
    assert themed_question.legal_actions("r-a") == ["a1", "a2"]


def test_legal_actions_with_no_position_answers_the_roots(
    themed_question: PolicyQuestion,
) -> None:
    # prd §419's comment reads the no-argument call as "roots + open frontiers":
    # the roots when no position is named.  So the two verbs agree on where a
    # walk begins — one spelling of "the nodes a walk may begin from" serves
    # both, and they cannot drift.
    assert themed_question.legal_actions() == themed_question.legal_roots()
    assert themed_question.legal_actions(None) == ["r-a", "r-b", "r-c"]


def test_legal_actions_of_the_canonical_tree_is_the_frontier(question: PolicyQuestion) -> None:
    # The conftest tree, read through the verb the canonical policy calls: the
    # root's frontier is its two scored leaves.
    assert question.legal_actions("n0") == ["n1", "n2"]


def test_the_frontier_partitions_the_non_root_nodes(themed_question: PolicyQuestion) -> None:
    # Every non-root node is a legal move of exactly one position, and every
    # root is a legal move of none — so the frontiers over all positions are a
    # partition of the tree's edges.  A node appearing in two frontiers would
    # mean two parents; a node in none would be unreachable from any legal walk.
    all_nodes = sorted(node.node_id for node in themed_question.tree.nodes)
    roots = set(themed_question.legal_roots())
    covered = [
        move
        for node_id in all_nodes
        for move in themed_question.legal_actions(node_id)
    ]
    assert sorted(covered) == sorted(node for node in all_nodes if node not in roots)
    assert len(covered) == len(set(covered))


# ---------------------------------------------------------------------------
# Purity — the reveal set is never consulted (the feature's load-bearing claim)
# ---------------------------------------------------------------------------


def test_an_unrevealed_node_is_still_a_legal_move(themed_question: PolicyQuestion) -> None:
    # A node the tree holds but the policy has not revealed is a legal move.
    # This is the sibling pool's law (a node "outside the lattice" is refused;
    # an unrevealed one is not) and it is what lets a policy *find* the batch it
    # is about to reveal — a verb that named only already-revealed cells could
    # never name the next one, and no walk could take its first step.
    assert themed_question.revealed == frozenset()
    assert themed_question.legal_actions("r-a") == ["a1", "a2"]
    assert themed_question.legal_roots() == ["r-a", "r-b", "r-c"]


def test_the_frontier_is_stable_across_a_probe(themed_question: PolicyQuestion) -> None:
    # THE portability claim, and the reason this verb is a pure function of the
    # tree.  The sibling pool's `legal_actions` reads its lattice and never its
    # reveal set, so a policy that re-reads its frontier — the ordinary shape of
    # a walk loop — sees the same answer before and after probing.  A
    # reveal-dependent implementation would pass every test above and fail
    # here, and it would fail in the *walk*: the frontier would collapse to []
    # after the probe, the policy would read "nowhere left to go", and it would
    # terminate early on a campaign tree while behaving correctly on a bootstrap
    # world — "one policy, both pools" broken for the one verb that moves.
    before = themed_question.legal_actions("r-a")
    themed_question.probe_batch(["a1", "a2"])
    assert themed_question.legal_actions("r-a") == before


def test_two_questions_over_one_tree_answer_the_same_frontier(themed_tree: CampaignTree) -> None:
    # The frontier is a function of (tree, node_id) and nothing else, so two
    # questions over one tree answer identically however differently they have
    # been walked — the property that makes a frontier reproducible across
    # replays of one tree.
    walked = policy_question(themed_tree)
    walked.probe_batch(["a1", "a2", "a2x"])
    untouched = policy_question(themed_tree)
    assert walked.legal_actions("r-a") == untouched.legal_actions("r-a")
    assert walked.legal_roots() == untouched.legal_roots()


def test_reading_the_frontier_does_not_grow_the_reveal_set(
    themed_question: PolicyQuestion,
) -> None:
    # Reading where you may go is not going.  Every frontier read in this file
    # leaves the reveal set empty, so the question's private state is still
    # exactly the reveal set and a frontier read is not a reveal the policy
    # never asked for.
    themed_question.legal_roots()
    themed_question.legal_actions()
    themed_question.legal_actions("r-a")
    themed_question.legal_actions("a1")
    assert themed_question.revealed == frozenset()


# ---------------------------------------------------------------------------
# Refusals — this member's vocabulary, for every way a frontier read can fail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["ghost", "a", "r", "n0", "r-a ", " r-a"])
def test_legal_actions_refuses_a_node_outside_the_tree(
    themed_question: PolicyQuestion, bad: str
) -> None:
    # A position a policy asks its moves from is one it was shown.  The refusal
    # is the tree's own — passed through unchanged so the sentence naming the
    # node and the tree survives rather than being re-spelled — which keeps
    # `test_meta`'s "names the node and the tree" property true for 218 as well.
    with pytest.raises(PolicyAddressError) as refused:
        themed_question.legal_actions(bad)
    assert bad in str(refused.value)


@pytest.mark.parametrize("bad", [7, 3.5, "", "   ", b"r-a", True])
def test_legal_actions_refuses_a_value_that_is_not_a_node_id(
    themed_question: PolicyQuestion, bad: object
) -> None:
    # An id that is not an id is refused before the walk reaches the tree, in
    # the same vocabulary `meta()` uses: the candidate names no position, so
    # there are no moves to enumerate.  A bare `TypeError` from a tree's
    # comparison would be a failure no caller's `except PolicyRuntimeError`
    # catches.
    with pytest.raises(PolicyAddressError):
        themed_question.legal_actions(bad)  # type: ignore[arg-type]


def test_legal_actions_refusal_is_the_members_own_base_class(
    themed_question: PolicyQuestion,
) -> None:
    # The discipline every seam in this member keeps: whatever fails, a caller
    # catching `PolicyRuntimeError` catches it.  `PolicyAddressError` is a
    # `PolicyTreeError` is a `PolicyRuntimeError`.
    with pytest.raises(PolicyRuntimeError):
        themed_question.legal_actions("ghost")


def test_legal_roots_refuses_an_object_that_is_not_a_tree() -> None:
    # A frontier is read off a campaign tree.  An object that is not one names
    # no edges, so the read is refused in this member's vocabulary rather than
    # escaping as a bare AttributeError.
    with pytest.raises(PolicyTreeError):
        legal_roots("not a tree")
    with pytest.raises(PolicyTreeError):
        legal_actions("not a tree", "n0")


def test_legal_roots_refuses_a_tree_whose_nodes_cannot_be_walked() -> None:
    # A tree whose `nodes` is not a sequence of nodes names no frontier a policy
    # could select a batch from.  Both the unreadable case and the wrong-shaped
    # case are refused, naming what arrived.
    class Unreadable:
        @property
        def nodes(self) -> object:
            raise RuntimeError("no nodes here")

    class WrongShape:
        nodes = 7

    with pytest.raises(PolicyTreeError):
        legal_roots(Unreadable())
    with pytest.raises(PolicyTreeError):
        legal_roots(WrongShape())


def test_legal_roots_refuses_a_node_that_cannot_be_named() -> None:
    # A frontier is a list of node ids — the ids a policy selects a batch from
    # and reveals.  A node carrying no usable id is refused naming the node
    # rather than silently dropped: a frontier that quietly omitted a move would
    # be one a policy could not walk, and the omission would be invisible.

    class Nameless:
        node_id = None
        parent_id = None

    class NotATree:
        nodes = (Nameless(),)

    with pytest.raises(PolicyTreeError) as refused:
        legal_roots(NotATree())
    assert "node_id" in str(refused.value)


def test_legal_actions_refuses_a_corrupt_edge() -> None:
    # `parent_id` is either absent (a root) or names a node.  A blank string is
    # neither, and a node wearing one would sit at a root it does not sit at —
    # handed to a policy as a place to begin.  Refused, naming the node.

    class Node:
        node_id = "n0"
        parent_id = "   "

    class Tree:
        nodes = (Node(),)

        def node(self, node_id: str) -> object:
            return Node()

    with pytest.raises(PolicyTreeError) as refused:
        legal_roots(Tree())
    assert "parent_id" in str(refused.value)


def test_legal_actions_refuses_a_tree_without_the_address_verb() -> None:
    # A tree the module cannot address a node through is refused in this
    # member's vocabulary, naming what arrived — a string, a bare object and a
    # mapping all name no position.

    class NodesOnly:
        nodes = ()

    with pytest.raises(PolicyTreeError) as refused:
        legal_actions(NodesOnly(), "n0")
    assert "node()" in str(refused.value)


def test_legal_actions_translates_a_broken_address_verb() -> None:
    # A tree whose `node()` raises something other than the address refusal is a
    # tree this accessor cannot read — translated into this member's vocabulary
    # rather than escaping as whatever the foreign verb raised.

    class BrokenTree:
        nodes = (CampaignNode(node_id="n0", parent_id=None, depth=0, payload='{"depth": 0}'),)

        def node(self, node_id: str) -> object:
            raise KeyError(node_id)

    with pytest.raises(PolicyTreeError):
        legal_actions(BrokenTree(), "n0")


def test_a_dangling_edge_is_refused_rather_than_silently_dropped() -> None:
    # THE subtle one, and the reason the module validates edges the tree's own
    # constructor would have refused had this member built the tree.  A node
    # naming a parent the tree does not hold is neither a root (its parent is
    # not absent) nor any position's legal move (no node names *it*), so both
    # verbs would omit it and say nothing — leaving a policy unable to tell "I
    # cannot walk this tree" from "there is no move there".  A duck-typed or
    # composed tree reaches these verbs without passing feature 217's
    # validation, so the check has to live here too.
    #
    # This is also the sentence feature 219's walk writes for the same defect:
    # the two accessors of one member must not disagree about whether a tree
    # with a broken edge is readable.
    class Node:
        def __init__(self, node_id: str, parent_id: str | None) -> None:
            self.node_id = node_id
            self.parent_id = parent_id

    class Tree:
        nodes = (Node("a", "ghost"), Node("b", None))

        def node(self, node_id: str) -> object:
            for node in self.nodes:
                if node.node_id == node_id:
                    return node
            raise KeyError(node_id)

    tree = Tree()
    with pytest.raises(PolicyTreeError) as refused:
        legal_roots(tree)
    assert "ghost" in str(refused.value)
    assert "a" in str(refused.value)
    # And from the other verb, which reaches the same check through the same
    # seam rather than a second copy of it.
    with pytest.raises(PolicyTreeError):
        legal_actions(tree, "b")


def test_a_self_parenting_node_is_refused() -> None:
    # The second way an edge fails to be one, and the one that would look like
    # *success* to a policy.  A node naming its own id has a parent that IS in
    # the tree, so the dangling check does not catch it — and it is not a root
    # (its parent is not absent), so it appears in exactly one frontier: its
    # own.  Without this check `legal_actions("a")` answers `["a"]`, handing a
    # policy a legal step from a position to the same position.  That step
    # advances nothing, and a walk that took it would loop forever on one node
    # while its frontier still read as non-empty — which is the failure a
    # termination test cannot catch, because the frontier never empties.
    #
    # Feature 219's walk refuses the same shape ("its parent chain revisits
    # 'a'"), so the member's two accessors agree on whether it is readable.
    class Node:
        def __init__(self, node_id: str, parent_id: str | None) -> None:
            self.node_id = node_id
            self.parent_id = parent_id

    class Tree:
        nodes = (Node("a", "a"), Node("b", None))

        def node(self, node_id: str) -> object:
            for node in self.nodes:
                if node.node_id == node_id:
                    return node
            raise KeyError(node_id)

    tree = Tree()
    with pytest.raises(PolicyTreeError) as refused:
        legal_actions(tree, "a")
    assert "itself" in str(refused.value)
    with pytest.raises(PolicyTreeError):
        legal_roots(tree)


def test_a_two_node_cycle_is_refused() -> None:
    # The same law one shape out: `a` names `b` and `b` names `a`.  Neither is a
    # root, and each is the other's only frontier — so a walk enters the pair and
    # circulates without ever emptying a frontier to terminate on.  The check is
    # per-edge (`a` names itself? no; `b` names itself? no) so this shape is
    # caught by the *dangling* branch only in the sense that both parents exist
    # — which they do.  What makes it unwalkable is that neither has an origin,
    # and feature 219's bounded walk refuses it for exactly that reason; 218
    # reaches the same verdict through this pair's refusal to name a root.
    class Node:
        def __init__(self, node_id: str, parent_id: str | None) -> None:
            self.node_id = node_id
            self.parent_id = parent_id

    class Tree:
        nodes = (Node("a", "b"), Node("b", "a"))

        def node(self, node_id: str) -> object:
            for node in self.nodes:
                if node.node_id == node_id:
                    return node
            raise KeyError(node_id)

    tree = Tree()
    # No node is a root, so `legal_roots` answers nothing — a walk has nowhere
    # legal to begin.  That is a tree with no entrance rather than a frontier
    # that lies, and it is the caller's judgement what an empty root set means;
    # what matters here is that no *move* is offered from either position that
    # would be the position itself.
    assert legal_roots(tree) == []
    for node_id in ("a", "b"):
        assert node_id not in legal_actions(tree, node_id)


# ---------------------------------------------------------------------------
# One derivation, two spellings — the free functions and the methods agree
# ---------------------------------------------------------------------------


def test_the_free_function_and_the_method_agree_on_roots(
    themed_tree: CampaignTree, themed_question: PolicyQuestion
) -> None:
    # `legal_roots(tree)` is the derivation and `question.legal_roots()` is a
    # delegation to it — the split `.meta` keeps for `cell_meta` and `.surface`
    # for `policy_surface`.  A report, a test or a later feature that wants the
    # frontier over a tree reads one derivation rather than reconstructing the
    # walk, so the two spellings cannot drift.
    assert legal_roots(themed_tree) == themed_question.legal_roots()


def test_the_free_function_and_the_method_agree_on_actions(
    themed_tree: CampaignTree, themed_question: PolicyQuestion
) -> None:
    # As above, for the positional form.
    assert legal_actions(themed_tree, "r-a") == themed_question.legal_actions("r-a")
    assert legal_actions(themed_tree) == themed_question.legal_actions()


# ---------------------------------------------------------------------------
# Composition — the walk §11's interface exists to make possible
# ---------------------------------------------------------------------------


def test_the_frontier_and_the_root_compose_into_a_terminating_walk(
    themed_tree: CampaignTree,
) -> None:
    # The whole feature read as one act, written against `question.*` and
    # nothing else — the shape the member's own CANONICAL_POLICY takes: begin at
    # a legal root, probe it, enumerate the frontier, probe the frontier, move
    # to the best reading, and commit where the frontier is empty.  The walk
    # must terminate, which is the property that makes the empty frontier an
    # answer rather than a hole.
    question = policy_question(themed_tree)
    record = episode_commit(question)

    (root,) = question.legal_roots()[:1]
    question.probe_batch([root])
    current = root
    for _ in range(16):  # a bound: termination, not a hang, is the claim
        frontier = list(question.legal_actions(current))
        question.probe_batch(frontier)
        observed = question.observed()
        if not frontier:
            break
        best = max(frontier, key=lambda cell: observed[cell].r2_insample or float("-inf"))
        if (observed[best].r2_insample or float("-inf")) <= (
            observed[current].r2_insample or float("-inf")
        ):
            break
        current = best
    else:  # pragma: no cover - the loop is bounded above
        pytest.fail("the walk did not terminate within 16 rounds")

    # It walked the depth-2 branch to its end and committed there — `a2x` is
    # reachable only by taking `legal_actions("a2")`, so the walk could not have
    # stopped at `a2` — and it never left the legal frontier: every revealed cell
    # was named by one of the two verbs before it was probed.
    assert record.commit(current).node_id == "a2x"
    assert question.revealed == frozenset({"r-a", "a1", "a2", "a2x"})


def test_the_walk_never_probes_a_cell_the_two_verbs_did_not_name(
    themed_tree: CampaignTree,
) -> None:
    # The frontier's job is to be the policy's whole legal vocabulary: a walk
    # that only ever probes cells these two verbs named stays inside the tree by
    # construction.  Every probed cell below is either a legal root or a legal
    # move of the cell before it — nothing is named by any other road.
    question = policy_question(themed_tree)
    held = sorted(node.node_id for node in themed_tree.nodes)
    probed: list[str] = []

    # The first step: a root, named by `legal_roots()` and by nothing else.
    current = question.legal_roots()[0]
    question.probe_batch([current])
    probed.append(current)

    while True:
        named = sorted(question.legal_actions(current))
        if not named:
            break
        # The whole claim, checked at every round: what the walk is about to
        # probe is exactly what the frontier just named.
        question.probe_batch(named)
        probed.extend(named)
        current = named[0]

    # Every cell probed was named by one of the two verbs at the moment it was
    # probed — nothing was named by any other road — and the walk stayed inside
    # the tree, so a policy drawing only on these verbs walks a stored tree
    # without ever reaching for a cell it was not given.
    assert probed and set(probed) <= set(held)
    assert len(probed) == len(set(probed))


def test_a_policy_that_never_leaves_the_roots_still_terminates(
    themed_question: PolicyQuestion,
) -> None:
    # A degenerate but legal policy: open a root, find it has no children, commit
    # there.  It must be expressible — the empty frontier is the termination
    # signal, and a policy that reads it and stops is doing the one thing prd
    # §436 requires.  This is the "campaign that was planned but whose loop never
    # expanded a node" case discovery.manifest names, read from the policy's side.
    question = themed_question
    record = episode_commit(question)
    assert question.legal_actions("r-c") == []
    assert record.commit("r-c").node_id == "r-c"
