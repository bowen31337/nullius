"""Feature 245 — the replay transition reveals only recorded children.

app_spec.xml, "Replay Engine", feature 245: *System rejects any attempt to
generate a new child during replay, because a stored tree reveals only recorded
children.*  docs/nullius-tech-architecture.md §10.1 is the code it names::

    child = tree.child_of(v)   # DETERMINISTIC
    if child:
        revealed.add(child)

and the sentence under it is why the feature exists: *"Online transition is
stochastic (the agent may generate a different child from the same workspace).
Replay transition is deterministic: it reveals the child already recorded. That
asymmetry is the source of the cost advantage."*

This file pins the claims the feature is made of, in the order a replay meets
them:

* **the refusal** — a replay handed a generator is refused *before the tree is
  read and before the generator is called*, because a child generated inside a
  replay would already be the drift the refusal exists to prevent. This is the
  feature's whole sentence and the first thing pinned here;
* **the transition reveals the recorded child** — one recorded edge, read off
  the tree, `revealed.add(child)`;
* **a leaf reveals nothing** — §10.1's ``if child:`` falling through, the
  honest answer at a node whose expansion recorded nothing;
* **the prefix is seeded at the roots** — ``{tree.root}`` on a campaign, which
  is the tree's parentless nodes;
* **the transition is idempotent** — a re-walked tree lands in the same prefix,
  which is what makes §12's "a replay of a fixed policy on a fixed tree" one
  answer rather than a family of them;
* **exactly one recorded child, or none** — the cardinality feature 239's
  ``CONTINUE(v)`` writes, and the refusal when a tree records several;
* **the reads are the tree's edges, never its bytes** — the transition reads
  ``node_id``/``parent_id`` and never a payload, which is what lets 246's and
  247's dependency refusals stand on top of it;
* **the refusals** — a malformed tree, a dangling edge, a self-edge, a value
  that is not a node id, a node the tree does not hold, and a tree with no
  root, each in this member's own vocabulary so a caller's single
  ``except ReplayError`` catches every way a transition can fail.
"""

from __future__ import annotations

import pytest
from conftest import StoredNode, StoredTree
from replay import (
    ChildGenerationRefused,
    ReplayError,
    ReplayTransition,
    ReplayTreeError,
    child_map,
    recorded_child,
    replay_roots,
    replay_transition,
)

# ---------------------------------------------------------------------------
# The refusal — feature 245's own sentence
# ---------------------------------------------------------------------------


def test_a_generator_is_refused(transition: ReplayTransition) -> None:
    # app_spec.xml feature 245: "System rejects any attempt to generate a new
    # child during replay".  The transition's one verb is where a generation
    # could enter — a `generator` is the callable shape of the online act
    # (feature 239's agent seam, which resumes a workspace and asks for a
    # refined signal) — and handing one in is that attempt.
    with pytest.raises(ChildGenerationRefused):
        transition.transition("r-mom", generator=lambda workspace: "m1")


def test_the_refusal_fires_before_the_generator_is_called(
    stored_tree: StoredTree,
) -> None:
    # The order is the feature, and it is feature 146's ordering for the same
    # reason: a child generated inside a replay would already be the drift the
    # refusal exists to prevent — the prefix would carry a node no stored
    # campaign contributed — so a refusal that generated first and raised
    # afterwards would have spent the thing it was refusing to spend.
    calls: list[str] = []

    def generator(workspace: object) -> str:
        calls.append(repr(workspace))
        return "m1"

    transition = replay_transition(stored_tree)
    with pytest.raises(ChildGenerationRefused):
        transition.transition("r-mom", generator=generator)
    assert calls == [], "the generator ran before the refusal"


def test_the_refusal_fires_before_the_tree_is_read() -> None:
    # And before the tree is read at all: the check is the *first* statement of
    # the verb, so a call that carried a generator touches neither the tree's
    # edges nor its address seam.  A refusal that read the tree first would
    # raise a ReplayTreeError at a caller whose actual mistake was the
    # generator, and the caller would go and repair the wrong thing.
    class Watched:
        __slots__ = ("addresses", "nodes")

        def __init__(self) -> None:
            self.nodes = (StoredNode("r-mom", None), StoredNode("m1", "r-mom"))
            self.addresses: list[str] = []

        def node(self, node_id: str) -> StoredNode:  # pragma: no cover - unread
            self.addresses.append(node_id)
            return StoredNode(node_id, None)

    tree = Watched()
    transition = ReplayTransition(tree=tree, revealed=set())
    assert "r-mom" in transition  # the seed did read the tree, once
    with pytest.raises(ChildGenerationRefused):
        transition.transition("r-mom", generator=lambda w: "m1")
    assert tree.addresses == [], "the tree was addressed before the refusal"


def test_the_generator_is_refused_however_the_tree_looks(
    transition: ReplayTransition,
) -> None:
    # The refusal is not a fact about the tree — a perfectly stored campaign
    # raises it — and it is not satisfied by the node being a leaf either.  A
    # leaf with a generator handed in is still "an attempt to generate a new
    # child during replay": the caller is asking for a child that the stored
    # tree did not record, which at a leaf is exactly the case the refusal is
    # for.  Anything gentler would let a caller generate children at leaves and
    # call the resulting prefix a replay.
    with pytest.raises(ChildGenerationRefused):
        transition.transition("m1x", generator=lambda w: "invented")


def test_the_refusal_names_the_replay_transition_and_the_repair(
    transition: ReplayTransition,
) -> None:
    # The message is read by the caller that has to move the act rather than
    # retry it, so it names §10.1's asymmetry (the recorded child versus the
    # generated one) and the repair (run the expansion online and replay the
    # tree it wrote) rather than merely reporting a bad argument.
    with pytest.raises(ChildGenerationRefused) as raised:
        transition.transition("r-mom", generator=lambda w: "m1")
    message = str(raised.value)
    assert "r-mom" in message
    assert "recorded" in message
    assert "CONTINUE" in message or "online" in message
    assert "feature 245" in message


def test_the_refusal_is_a_replay_error_and_not_a_tree_error(
    transition: ReplayTransition,
) -> None:
    # The two have one repair each and the repairs are in different places: a
    # broken tree is repaired at the store, a handed-in generator at the
    # caller.  A caller that catches the tree's failures in order to skip a bad
    # world must not silently skip the refusal that says the replay path has no
    # generative transition at all — so the refusal is a sibling of
    # ReplayTreeError, never a child of it.
    assert issubclass(ChildGenerationRefused, ReplayError)
    assert not issubclass(ChildGenerationRefused, ReplayTreeError)


def test_the_generator_is_optional_and_absent_is_the_ordinary_call(
    transition: ReplayTransition,
) -> None:
    # The whole design point of the parameter: a replay driver never passes
    # one, so the refusal's *shape* is what a caller meets — writing
    # `generator=...` at a call site whose keyword is the refusal's name.
    # `None` means "no generation was asked for" and the walk proceeds.
    assert transition.transition("r-mom") == "m1"


# ---------------------------------------------------------------------------
# The transition reveals the recorded child
# ---------------------------------------------------------------------------


def test_the_transition_reveals_the_recorded_child(
    transition: ReplayTransition,
) -> None:
    # §10.1's `child = tree.child_of(v)` then `revealed.add(child)`, the two
    # lines this module is.
    assert transition.transition("r-mom") == "m1"
    assert "m1" in transition.revealed


def test_the_child_is_read_off_the_trees_own_edge(
    stored_tree: StoredTree,
) -> None:
    # The child is *the node that names the selected node as its parent* — one
    # recorded edge, no invention.  This is the same derivation feature 218's
    # legal_actions performs for the policy's view of the same document, so the
    # two halves cannot disagree about which positions exist.
    assert recorded_child(stored_tree, "r-mom") == "m1"
    assert recorded_child(stored_tree, "m1") == "m1x"


def test_one_step_at_a_time(stored_tree: StoredTree) -> None:
    # A transition is one recorded edge, not reachability: `m1x` is a child of
    # `m1` and *not* of `r-mom`, so a replay standing at the root cannot reach
    # a grandchild in one step.  A transitive implementation would pass a
    # two-level tree and diverge from §10.1's loop on any deeper one.
    assert recorded_child(stored_tree, "r-mom") == "m1"
    assert recorded_child(stored_tree, "r-mom") != "m1x"


def test_the_transition_does_not_advance_past_the_child(
    transition: ReplayTransition,
) -> None:
    # Reading a node's recorded child reveals *that* node and nothing beyond
    # it: the walk is the policy's, one step per selected batch element.
    transition.transition("r-mom")
    assert transition.revealed == {"r-mom", "r-event", "m1"}


def test_the_prefix_seeds_at_the_roots(transition: ReplayTransition) -> None:
    # §10.1's `revealed = {tree.root}`, read on a themed campaign as the tree's
    # parentless nodes — one root per planted theme (prd §215), not the single
    # canonical root a bootstrap lattice has.
    assert transition.prefix() == ("r-event", "r-mom")


def test_the_prefix_is_a_plurality(stored_tree: StoredTree) -> None:
    # Two roots in two themes.  A `{tree.root}` implemented as "the tree's
    # first node" would pass a single-root fixture while answering one place a
    # walk may begin when the campaign planted several.
    assert replay_roots(stored_tree) == ("r-event", "r-mom")


def test_the_prefix_ascending_is_the_ordering_rule(
    stored_tree: StoredTree,
) -> None:
    # §12's ordering rule — an explicit sort before every reduction — restated
    # for a search frontier: a replay that enumerates without sorting still
    # walks deterministically, and two replays of one tree hand the policy the
    # same sequence however the reveals arrived.
    transition = replay_transition(stored_tree)
    transition.transition("m1")
    transition.transition("r-mom")
    assert list(transition.prefix()) == sorted(transition.revealed)


def test_a_leaf_reveals_nothing(transition: ReplayTransition) -> None:
    # §10.1's `if child:` falling through.  "A stored tree reveals only
    # recorded children" read at a node whose expansion recorded none: the
    # answer is *no child*, not an error — a termination the walk decides on,
    # not a refusal.
    prefix_before = transition.prefix()
    assert transition.transition("m1x") is None
    # `if child:` falls through: nothing was added.  A step that revealed the
    # leaf *itself* would be a transition advancing by the node it was handed,
    # which §10.1 never does — the revealed node is the *child's*.
    assert transition.prefix() == prefix_before


def test_an_unexpanded_root_reveals_nothing(
    transition: ReplayTransition,
) -> None:
    # The same fact at a root: `r-event` was planted and never expanded, so its
    # expansion recorded no child.  A verb that refused here would leave the
    # caller unable to tell *this theme has not been explored* from *you asked
    # wrongly*.
    assert transition.transition("r-event") is None


def test_the_transition_is_idempotent(transition: ReplayTransition) -> None:
    # `revealed.add` is a set add, so transitioning over a node whose child is
    # already revealed reveals nothing new and the answer is still the child's
    # id.  A replay re-walked over one tree lands in the same prefix — §12's
    # determinism, read on the walk itself (cq-15).
    first = transition.transition("r-mom")
    prefix_after_first = transition.prefix()
    second = transition.transition("r-mom")
    assert first == second == "m1"
    assert transition.prefix() == prefix_after_first


def test_two_transitions_over_one_tree_agree(stored_tree: StoredTree) -> None:
    # Two walks of one stored tree, taken in different orders, land in the same
    # prefix: the transition is a function of the tree and the set of nodes
    # selected, never of the order they were selected in.
    left = replay_transition(stored_tree)
    right = replay_transition(stored_tree)
    left.transition("r-mom")
    left.transition("m1")
    right.transition("m1")
    right.transition("r-mom")
    assert left.prefix() == right.prefix()


def test_the_walk_can_only_reach_recorded_nodes(
    stored_tree: StoredTree,
) -> None:
    # The load-bearing negative of the whole feature: every node a replay can
    # put in its prefix is a node the stored tree holds, because the only way
    # into the prefix is a recorded edge.  A generated child would appear here
    # as a node the tree does not hold — which is why the refusal, not this
    # assertion, is what makes the claim true for a caller that tries.
    transition = replay_transition(stored_tree)
    known = {node.node_id for node in stored_tree.nodes}
    for selected in list(transition.prefix()):
        transition.transition(selected)
    assert transition.revealed <= known


# ---------------------------------------------------------------------------
# The tree's edges are read; its bytes are not
# ---------------------------------------------------------------------------


def test_a_payload_the_transition_never_reads(
    stored_tree: StoredTree,
) -> None:
    # The transition derives the walk from `node_id` and `parent_id` alone —
    # no score, no `is_null` (prd §4.2, cq-8), no absolute target.  Pinned by
    # construction: the fixture's payloads are replaced with values no
    # arithmetic could use, and every answer is unchanged.
    for node in stored_tree.nodes:
        node.payload = {"poison": object()}  # type: ignore[assignment]
    assert replay_roots(stored_tree) == ("r-event", "r-mom")
    assert recorded_child(stored_tree, "r-mom") == "m1"
    assert recorded_child(stored_tree, "m1") == "m1x"
    assert recorded_child(stored_tree, "m1x") is None


def test_the_payload_is_not_consulted_for_children() -> None:
    # The same claim from the other side: a node whose payload *claims* a child
    # it does not record is not a child.  What a node says about itself is not
    # what the tree recorded, and only the tree's edges are the walk.
    tree = StoredTree(
        [
            StoredNode("r", None),
            StoredNode("claims", None, payload={"child_of": "r", "child": "invented"}),
        ]
    )
    assert recorded_child(tree, "r") is None


# ---------------------------------------------------------------------------
# Exactly one recorded child, or none
# ---------------------------------------------------------------------------


def test_a_node_recording_two_children_is_refused() -> None:
    # §10.1's `child = tree.child_of(v)` is singular because the act that
    # writes these edges creates exactly one (feature 239: "creates exactly one
    # refined signal for evaluation").  A node recording several is a tree no
    # deterministic transition can walk, and resolving it by picking one would
    # be an undeclared tie-break two replays could disagree about (§12, cq-15).
    tree = StoredTree(
        [StoredNode("r", None), StoredNode("a", "r"), StoredNode("b", "r")]
    )
    with pytest.raises(ReplayTreeError) as raised:
        recorded_child(tree, "r")
    message = str(raised.value)
    assert "r" in message
    assert "a" in message and "b" in message


def test_the_cardinality_refusal_fires_at_construction() -> None:
    # The refusal is the transition's too, not only the free function's, and it
    # fires when the transition is *opened* rather than part-way through a walk.
    # The ambiguity is a property of the stored tree, not of the selection that
    # happens to reach it: a replay that refused only when the policy chose the
    # ambiguous node would walk a tree it can never finish, spend rounds doing
    # it, and report a prefix whose incompleteness nothing in the answer
    # explained.  Refusing at construction makes the tree's unfitness a
    # statement about the tree — which is also what the derived parent -> child
    # map (:func:`replay.child_map`) requires, since it cannot be built at all
    # when a node records several children.
    tree = StoredTree(
        [
            StoredNode("r", None),
            StoredNode("a", "r"),
            StoredNode("b", "r"),
            StoredNode("z", None),
        ]
    )
    with pytest.raises(ReplayTreeError) as raised:
        replay_transition(tree)
    assert "r" in str(raised.value)


def test_an_ambiguous_node_the_walk_never_selects_is_still_refused() -> None:
    # The corollary, and the reason construction is the right moment: `z` is an
    # unambiguous root and a replay that only ever selected `z` would take no
    # ambiguous step — yet the tree still records two children for `r`, so it is
    # not a tree any replay can be *shown* to be correct over.  A refusal
    # deferred to the offending step would let this walk run to completion and
    # report a prefix as if the tree were sound.
    tree = StoredTree(
        [
            StoredNode("r", None),
            StoredNode("a", "r"),
            StoredNode("b", "r"),
            StoredNode("z", None),
        ]
    )
    with pytest.raises(ReplayTreeError):
        replay_transition(tree)


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_a_dangling_edge_is_refused() -> None:
    # A node naming a parent the tree does not hold is neither a root nor any
    # position's child, so every verb here would omit it in silence — and a
    # replay that quietly left a node out is one nothing could tell from a node
    # whose expansion recorded no child.  Refused naming the node.
    tree = StoredTree([StoredNode("r", None), StoredNode("a", "ghost")])
    with pytest.raises(ReplayTreeError) as raised:
        replay_roots(tree)
    assert "a" in str(raised.value) and "ghost" in str(raised.value)


def test_a_self_edge_is_refused() -> None:
    # A node naming its own id as its parent: its parent *is* in the tree, so
    # the dangling check does not catch it, and it would make the node its own
    # recorded child — a transition that "revealed" the position it started
    # from, which advances nothing and would loop a replay forever while its
    # prefix still read as growing.
    tree = StoredTree([StoredNode("r", None), StoredNode("a", "a")])
    with pytest.raises(ReplayTreeError) as raised:
        recorded_child(tree, "a")
    assert "a" in str(raised.value)


def test_a_blank_parent_reference_is_refused() -> None:
    # A blank string is neither absent (a root) nor a node, so a node wearing
    # one would sit at a root it does not sit at and be handed to the walk as a
    # place to begin.
    tree = StoredTree([StoredNode("r", None), StoredNode("a", "   ")])
    with pytest.raises(ReplayTreeError):
        replay_roots(tree)


def test_a_value_that_is_not_a_node_id_is_refused(
    transition: ReplayTransition,
) -> None:
    # A value that is not an id names no position to read edges from.  Answered
    # as a leaf it would report a malformed call as a node whose expansion
    # recorded nothing — the one confusion this module refuses everywhere.
    for value in (7, "", "  ", None, object()):
        with pytest.raises(ReplayTreeError):
            transition.transition(value)


def test_a_node_the_tree_does_not_hold_is_refused(
    transition: ReplayTransition,
) -> None:
    # A position the replay cannot stand at names no transition.  The tree's
    # own refusal is translated into this member's vocabulary, because a caller
    # catching ReplayError must catch a node outside the stored campaign — and
    # a replay that walked past it would report a malformed call as a leaf.
    with pytest.raises(ReplayTreeError) as raised:
        transition.transition("never-recorded")
    assert "never-recorded" in str(raised.value)


def test_a_tree_with_no_root_is_refused() -> None:
    # Every node names a parent, so no node is parentless and no walk could
    # begin anywhere.  A prefix seeded empty would hand the replay a campaign
    # it silently cannot walk.
    tree = StoredTree([StoredNode("a", "b"), StoredNode("b", "a")])
    with pytest.raises(ReplayTreeError) as raised:
        replay_roots(tree)
    assert "root" in str(raised.value)


def test_a_tree_whose_nodes_cannot_be_read_is_refused() -> None:
    # The seam validates what it reads rather than trusting the carrier: a
    # value that is not a tree names the read it failed rather than escaping as
    # an AttributeError a caller catching ReplayError would miss.
    for value in (object(), "not a tree", None, 7):
        with pytest.raises(ReplayTreeError):
            replay_roots(value)


def test_a_tree_with_no_address_verb_is_refused() -> None:
    # A tree that cannot address a node names no position to read the edges of.
    # Refused at the address seam rather than walking on, because the
    # alternative is answering a malformed call as a leaf.
    class Bare:
        #: A sequence of nodes and no ``node()`` — the tree that can be walked
        #: for its edges but cannot be asked what a node id addresses.
        nodes = (StoredNode("r", None),)

    transition = ReplayTransition(tree=Bare(), revealed=set())
    with pytest.raises(ReplayTreeError):
        transition.transition("r")


def test_a_prefix_naming_an_unknown_node_is_refused(
    stored_tree: StoredTree,
) -> None:
    # A prefix is the set of nodes a replay has revealed *out of the tree it
    # walks*, so a node the tree does not hold is one the policy would be shown
    # a reading for that no stored campaign can answer.  Same class of failure
    # feature 218 refuses as a dangling edge, here on the seed a caller handed
    # in.
    with pytest.raises(ReplayTreeError) as raised:
        ReplayTransition(tree=stored_tree, revealed={"r-mom", "ghost"})
    assert "ghost" in str(raised.value)


def test_a_malformed_revealed_node_is_refused(
    stored_tree: StoredTree,
) -> None:
    # The same validation on the prefix's spelling: a revealed value that is
    # not a node id names no node the walk revealed.
    with pytest.raises(ReplayTreeError):
        ReplayTransition(tree=stored_tree, revealed={7})  # type: ignore[arg-type]


def test_every_refusal_is_a_replay_error() -> None:
    # The property a dreaming loop that replays a policy across two hundred
    # stored worlds depends on: one malformed tree is a catchable value, not an
    # escape that ends the cycle.
    assert issubclass(ReplayTreeError, ReplayError)
    assert issubclass(ChildGenerationRefused, ReplayError)


# ---------------------------------------------------------------------------
# The prefix, the seed and the free functions
# ---------------------------------------------------------------------------


def test_a_caller_may_seed_a_prefix_it_already_holds(
    stored_tree: StoredTree,
) -> None:
    # A resumed replay, or a report over a walk taken elsewhere: the direct
    # constructor takes the prefix rather than re-seeding at the roots, and
    # validates it the same way.
    transition = ReplayTransition(tree=stored_tree, revealed={"m1"})
    assert transition.prefix() == ("m1",)


def test_an_empty_seed_falls_back_to_the_roots(
    stored_tree: StoredTree,
) -> None:
    # `revealed=set()` is the honest spelling of "I hold no prefix yet", which
    # is what §10.1's `{tree.root}` answers.  An explicit empty set and an
    # omitted one are one state, so a caller cannot accidentally walk a tree
    # from nowhere.
    transition = ReplayTransition(tree=stored_tree, revealed=set())
    assert transition.prefix() == ("r-event", "r-mom")


def test_the_child_map_is_the_derivation_the_verbs_read(
    stored_tree: StoredTree,
) -> None:
    # `child_map` is the one pass over the tree's edges that both
    # `recorded_child` and every transition step read, so the free function, the
    # object and the map cannot disagree about what a node's recorded child is.
    assert child_map(stored_tree) == {"r-mom": "m1", "m1": "m1x"}
    for parent, child in child_map(stored_tree).items():
        assert recorded_child(stored_tree, parent) == child


def test_the_child_map_holds_only_recorded_edges(stored_tree: StoredTree) -> None:
    # A leaf and an unexpanded root appear as *no* key rather than as a key
    # mapping to None: the map is the tree's recorded edges, and a node with no
    # child has no edge.  `.get` then answers `None` for both, which is §10.1's
    # `if child:` falling through — one spelling of "no recorded child" rather
    # than two that could drift.
    children = child_map(stored_tree)
    assert "m1x" not in children  # a leaf
    assert "r-event" not in children  # an unexpanded root
    assert children.get("m1x") is None


def test_a_transition_derives_the_tree_once_not_per_step(
    stored_tree: StoredTree,
) -> None:
    # The cost property the sibling feature 252's 50 ms-per-replay budget
    # depends on.  Pinned by *construction* rather than by timing, because a
    # wall-clock assertion is flaky on a loaded machine and would not say why:
    # the transition holds the map it derived, so a step is a dict read.  A
    # regression to per-step derivation shows up here as a missing attribute —
    # and as a quadratic walk, the measurement `child_map`'s docstring records.
    transition = replay_transition(stored_tree)
    assert transition.children == child_map(stored_tree)
    before = dict(transition.children)
    transition.transition("r-mom")
    assert transition.children == before, "the map was re-derived by a step"


def test_the_recorded_edges_cannot_be_written_through(
    stored_tree: StoredTree,
) -> None:
    # `children` is *the tree's own recorded edges*, so it is exposed read-only:
    # a caller that could edit it would have a second, unvalidated statement of
    # the tree's edges sitting beside the tree — and could put a node the tree
    # never recorded into the prefix, which is minting a child by hand.  The
    # obvious route is closed; the object's deliberate mutability elsewhere
    # (`revealed`, §10.1's own `add`) is documented on the class rather than
    # papered over.
    transition = replay_transition(stored_tree)
    with pytest.raises(TypeError):
        transition.children["r-mom"] = "invented"  # type: ignore[index]


def test_the_map_is_derived_and_not_accepted(
    stored_tree: StoredTree,
) -> None:
    # `children` is not a constructor argument: a caller cannot hand a
    # transition a map that disagrees with the tree it walks, which would be a
    # second, unvalidated statement of the tree's edges sitting beside the tree.
    with pytest.raises(TypeError):
        ReplayTransition(tree=stored_tree, revealed={"m1"}, children={"m1": "x"})


def test_the_free_functions_are_the_ones_the_object_uses(
    stored_tree: StoredTree,
) -> None:
    # `replay_roots` and `recorded_child` are the derivations; the object's
    # methods are readings of them.  One implementation, two spellings — the
    # split the policy-runtime member keeps for cell_meta and legal_actions.
    assert tuple(replay_roots(stored_tree)) == ReplayTransition.over(stored_tree).prefix()


def test_the_member_spelling_and_the_object_spelling_agree(
    stored_tree: StoredTree,
) -> None:
    # `replay_transition` is the member's entry point and `ReplayTransition.over`
    # is the constructor behind it: a test that pins the seed pins one call
    # site, and a driver reaching either gets the same walk.
    assert replay_transition(stored_tree).prefix() == ReplayTransition.over(
        stored_tree
    ).prefix()


def test_len_and_contains_read_the_prefix(transition: ReplayTransition) -> None:
    # The two conveniences a driver's loop wants, and the two that must not
    # grow a second notion of what the prefix holds.
    assert len(transition) == 2
    assert "r-mom" in transition
    transition.transition("r-mom")
    assert len(transition) == 3
    assert "m1" in transition


def test_the_repr_reads_no_tree(stored_tree: StoredTree) -> None:
    # A repr is a debugging aid; one that re-walked the nodes would raise a
    # second refusal while an operator was already looking at the first, which
    # is the worst moment for it.  Pinned by construction with a tree this
    # module cannot read at all: if the repr touched it, it would raise.
    class Unreadable:
        __slots__ = ()
        #: No ``nodes`` and no ``node()`` — every read this module makes fails.

    transition = ReplayTransition.over(stored_tree)
    transition.tree = Unreadable()  # the tree it was opened over is gone
    assert repr(transition) == "ReplayTransition(revealed=2)"
