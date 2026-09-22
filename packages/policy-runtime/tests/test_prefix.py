"""Feature 223, the prefix view — the fresh object a policy is handed, holding
only the cells it has revealed.

app_spec.xml, "Exploration Policy Runtime", feature 223 (``covers="cq-16"``,
``depends_on=217``): *System constructs the prefix view as a fresh object,
which returns only revealed nodes so unrevealed nodes are absent rather than
filtered.*  docs/nullius-tech-architecture.md §10.2 states the law the tests
below pin:

* **fresh object** — every :func:`prefix_view` call constructs a new view,
  and a view already held is a snapshot: it does not grow when the question
  reveals more, because a live view would let a policy read the prefix
  extending without revealing — a reveal by other means;
* **absent rather than filtered** — an unrevealed node is not present in
  the returned structure at all.  Not a key, not a value, not behind an
  attribute, not in a ``__dict__`` (the view has none), not anywhere in the
  object graph a policy can walk from the view: there is no tree behind the
  view to filter *over*, which is the distinction the sentence turns on;
* **no address seam** — where the question *refuses* a node outside the
  tree, the view has no verb for asking at all: no ``node``, no ``meta``,
  no ``reveal``.  The barrier is structural, one seam weaker than a guard.
"""

from __future__ import annotations

import gc
from typing import Any

import pytest
from policy_runtime import (
    CampaignNode,
    CampaignTree,
    PolicyObservation,
    PolicyQuestion,
    PolicyTreeError,
    PrefixView,
    prefix_view,
)


def _data_graph(root: Any, seen: set[int]) -> Any:
    """Yield every object reachable from ``root`` through *data* only.

    The walk a policy could write from the object it holds: attribute
    values, slot values, container elements — never crossing into a class,
    function or method, which are code rather than episode data and hold no
    node of any campaign.  That boundary is the honest one: introspection
    reaching ``PrefixView`` *the class* reaches a type, not a cell.
    """
    for candidate in (root,) if not isinstance(root, (list, tuple)) else root:
        if id(candidate) in seen:
            continue
        if isinstance(candidate, (type, BaseException)) or callable(candidate):
            continue
        seen.add(id(candidate))
        yield candidate
        if isinstance(candidate, dict):
            children: tuple[Any, ...] = tuple(candidate.keys()) + tuple(candidate.values())
        elif isinstance(candidate, (list, tuple, set, frozenset)):
            children = tuple(candidate)
        else:
            children = tuple(getattr(candidate, "__dict__", {}).values()) + tuple(
                getattr(candidate, slot)
                for slot in getattr(type(candidate), "__slots__", ())
                if hasattr(candidate, slot)
            )
        if children:  # an empty container recursed into mints fresh empties forever
            yield from _data_graph(children, seen)


def test_prefix_view_is_a_fresh_object_per_call(question: PolicyQuestion) -> None:
    # §10.2's first clause: ``prefix_view()`` *constructs* a fresh object —
    # not a cached one, not a singleton over the question.  Two calls over
    # one reveal set are equal but distinct, so freshness is a fact about
    # identity, not content, and no two rounds of a replay share an object.
    question.reveal("n1")
    first = prefix_view(question)
    second = prefix_view(question)
    assert first is not second
    assert first == second


def test_prefix_view_returns_only_revealed_nodes(
    tree: CampaignTree, question: PolicyQuestion, leaf_node: str
) -> None:
    # The feature's own verb: the view returns only revealed nodes — the
    # observations of the cells the policy has revealed, keyed by their ids,
    # exactly the reading the question's own accessor gives.  The tree holds
    # three nodes; one reveal makes a view of one.
    question.reveal(leaf_node)
    view = prefix_view(question)
    assert set(view.observed()) == {leaf_node}
    assert view.observed()[leaf_node].r2_insample == 0.20
    assert len(view) == 1


def test_prefix_view_starts_empty(question: PolicyQuestion) -> None:
    # A question that has revealed nothing hands a policy an empty prefix —
    # a statement about what the policy has seen, not about the tree.  The
    # empty view is legal for the same reason 217's empty observed mapping
    # is, and a policy handed it holds exactly what it started with.
    view = prefix_view(question)
    assert view.observed() == {}
    assert len(view) == 0


def test_unrevealed_nodes_are_absent_not_filtered(
    tree: CampaignTree, question: PolicyQuestion, root_node: str
) -> None:
    # cq-16's core, spelled once plainly: the root ``n0`` is a node the tree
    # holds but the policy has not revealed, so it is absent from the view —
    # never a key, never a value, never an answer to a membership ask.  The
    # ``False`` is absence, not a filter's verdict: the view holds no tree
    # to filter over, nowhere the node could be.
    question.reveal("n1")
    view = prefix_view(question)
    assert root_node not in view.observed()
    assert view.observed().get(root_node) is None
    assert root_node not in view
    assert "n1" in view


def test_view_has_no_dict_at_all(question: PolicyQuestion) -> None:
    # §10.2's "stray ``__dict__`` access": the class carries slots and no
    # dictionary, so the stray access does not find filtered state — it
    # finds nothing, raising before it can read a thing.  A view with a
    # ``__dict__`` would at best hold prefix data; this one cannot even be
    # asked, which is the stronger half of the law.
    question.reveal("n1")
    view = prefix_view(question)
    assert not hasattr(view, "__dict__")
    with pytest.raises(AttributeError):
        view.__dict__  # noqa: B018 - the stray access itself, asserted to fail


def test_attribute_walking_reaches_no_unrevealed_node(
    tree: CampaignTree, question: PolicyQuestion, root_node: str
) -> None:
    # §10.2's "attribute walking": every attribute the view answers with —
    # and every object reachable from it through data — is prefix data.  No
    # attribute is the tree or the question, and the walk finds neither an
    # unrevealed node id nor any object of the campaign the policy has not
    # earned.  The barrier is a fact about the object graph, not a promise
    # about which methods a policy chose to call.
    question.reveal("n1")
    view = prefix_view(question)
    for name in dir(view):
        value = getattr(view, name)
        assert value is not tree
        assert value is not question
    reached = list(_data_graph(view, set()))
    assert root_node not in reached
    assert "n1" in reached  # the revealed id is data the policy may read
    assert not any(isinstance(item, (CampaignTree, CampaignNode)) for item in reached)
    assert not any(isinstance(item, PolicyQuestion) for item in reached)


def test_gc_referents_hold_no_tree_or_question(
    tree: CampaignTree, question: PolicyQuestion
) -> None:
    # The collector's own view of what the object holds: the view's direct
    # referents are its cells (and its class, which is code, not data) —
    # never the tree, never the question.  A view that held either, even
    # under a private name, would be a filtered view over them, the design
    # §10.2 refuses.
    question.reveal("n1")
    view = prefix_view(question)
    referents = [item for item in gc.get_referents(view) if not isinstance(item, type)]
    assert referents == [view.cells]
    assert tree not in referents
    assert question not in referents


def test_view_holds_no_tree_or_question_attributes(question: PolicyQuestion) -> None:
    # The view does not *refuse* to hand over the tree or the question — it
    # has no such attribute to ask for.  No private escape hatch either: the
    # projection copied the values out and kept nothing that could answer a
    # node the policy has not revealed, however the policy spells the ask.
    question.reveal("n1")
    view = prefix_view(question)
    for name in ("tree", "question", "_tree", "_question", "_revealed"):
        assert not hasattr(view, name)


def test_view_has_no_address_seam(question: PolicyQuestion) -> None:
    # The question *refuses* a node outside the tree (feature 217's
    # :class:`PolicyAddressError`); the view is one seam weaker — it has no
    # verb for addressing at all.  No ``node``, no ``meta``, no ``reveal``:
    # a policy holding the view cannot ask about a cell, only read the cells
    # it holds, which is the whole of the prefix-only surface it is handed.
    question.reveal("n1")
    view = prefix_view(question)
    for verb in ("node", "meta", "reveal", "reveal_many", "legal_actions", "commit"):
        assert not hasattr(view, verb)


def test_view_is_a_snapshot_not_a_live_filter(question: PolicyQuestion) -> None:
    # The other half of "fresh": the observations were copied out at
    # construction, not aliased to the question's live state, so a held view
    # does not grow when the question reveals more.  The contrary design
    # would let a policy read the prefix extending without revealing — a
    # reveal by other means, the exact leak §10.2 exists to close.
    question.reveal("n1")
    held = prefix_view(question)
    question.reveal("n2")
    assert set(held.observed()) == {"n1"}
    assert set(prefix_view(question).observed()) == {"n1", "n2"}


def test_view_is_bound_to_the_round_it_was_built_for(tree: CampaignTree) -> None:
    # The replay's rounds in miniature: a view per ``select`` call, each
    # answering the prefix as it stood, so a policy's decision in one round
    # is legible against exactly the world it was shown — docs §10.1's
    # ``policy.select(prefix_view(...))`` read as a law about object
    # identity, not just call shape.
    question = PolicyQuestion(tree)
    first_round = prefix_view(question)
    question.reveal("n1")
    second_round = prefix_view(question)
    question.reveal("n2")
    third_round = prefix_view(question)
    assert len(first_round) == 0
    assert len(second_round) == 1
    assert len(third_round) == 2


def test_view_readings_agree_with_the_question(question: PolicyQuestion) -> None:
    # One implementation of the reading: the factory reads the question's
    # own ``observed()`` and copies its values out, so the view's mapping is
    # the question's mapping — the same observations, to the last field, in
    # the same ascending order.  A second derivation would be a second
    # thing to keep in sync; there is none.
    question.reveal_many(["n2", "n1"])
    assert prefix_view(question).observed() == question.observed()
    assert list(prefix_view(question).observed()) == ["n1", "n2"]


def test_observed_is_ascending_and_a_fresh_dict_per_call(question: PolicyQuestion) -> None:
    # The shape 217 fixed, kept: ascending by node id whatever order the
    # reveals came in, and a fresh dict per call — so a policy that writes
    # into the mapping it read moves its own copy and not the prefix, and
    # two reads of one view agree.
    question.reveal_many(["n2", "n1"])
    view = prefix_view(question)
    assert list(view.observed()) == ["n1", "n2"]
    first, second = view.observed(), view.observed()
    assert first is not second and first == second
    first["ghost"] = first["n1"]  # a policy may scribble on its own copy
    assert "ghost" not in view.observed()


def test_cells_is_prefix_data_and_cannot_be_moved(question: PolicyQuestion) -> None:
    # ``cells`` is public on purpose — the way ``CampaignTree.nodes`` is —
    # because a policy that walks it finds revealed cells, which is exactly
    # what it is allowed to find.  But it cannot be rebound: the view is
    # frozen, so a policy cannot hand itself a longer prefix it did not
    # earn, and the stored tuple is the view's own, sorted ascending.
    question.reveal_many(["n2", "n1"])
    view = prefix_view(question)
    assert [cell.node_id for cell in view.cells] == ["n1", "n2"]
    with pytest.raises(AttributeError):
        view.cells = view.cells[:1]  # type: ignore[misc]
    with pytest.raises(AttributeError):
        view.anything = 1  # type: ignore[attr-defined]
    assert len(view) == 2


def test_constructor_sorts_and_refuses_duplicate_ids(
    question: PolicyQuestion, leaf_node: str
) -> None:
    # The constructor normalises what it is handed — sorted ascending, like
    # the tree sorts its nodes — and refuses two cells wearing one node id:
    # the mapping the view is built from keys one observation by an id, and
    # a prefix with two names for one cell is a prefix the policy could not
    # read.  The tree's own refusal of a duplicated node, restated one
    # level up.
    observation = PolicyObservation.from_node(CampaignNode.freeze(
        leaf_node, {"r2_insample": 0.20}, parent_id="n0", depth=1
    ))
    assert [cell.node_id for cell in PrefixView(cells=(observation,)).cells] == [leaf_node]
    with pytest.raises(PolicyTreeError, match="twice"):
        PrefixView(cells=(observation, observation))


def test_constructor_refuses_a_value_that_is_not_an_observation() -> None:
    # The cells a view is built of are observations — the read side 217
    # froze — checked *by name*, not by ``isinstance``, because the module
    # loader re-executes this member under a synthetic name and the
    # composed member's observations are a second class object the view
    # must front.  A bare float or string carries no node id and no
    # metrics; it is refused, naming what arrived.
    with pytest.raises(PolicyTreeError, match="built of observations"):
        PrefixView(cells=(0.20,))  # type: ignore[arg-type]
    with pytest.raises(PolicyTreeError, match="non-empty node_id"):
        PrefixView(cells=(PolicyObservation(node_id="  ", r2_insample=None, ic_insample=None, n_periods=None, n_features=None),))  # type: ignore[arg-type]


def test_prefix_view_refuses_a_non_question() -> None:
    # The seam duck-types what it is handed, and a string, a mapping or a
    # bare object has no ``observed()`` — it names no prefix a policy could
    # be shown, and is refused here, naming what was wrong, before any
    # object is constructed.  The same voice the question's own constructor
    # refusal takes over a non-tree.
    for not_a_question in ("not a question", {"n1": None}, None, object()):
        with pytest.raises(PolicyTreeError, match="fronts a question"):
            prefix_view(not_a_question)


def test_prefix_view_refuses_a_non_callable_observed() -> None:
    # An attribute named ``observed`` that is not the read-side accessor —
    # data wearing the accessor's name — is still not a question.  The
    # demand is the *read side*, and the refusal keeps a caller from
    # smuggling a foreign object through a field that happens to be spelled
    # right.
    class WearingTheName:
        observed = 3  # data, not the accessor

    with pytest.raises(PolicyTreeError, match="fronts a question"):
        prefix_view(WearingTheName())


def test_prefix_view_refuses_a_non_mapping_answer() -> None:
    # The accessor must answer the mapping 217 fixed.  A list of cells
    # cannot be walked by key, names no prefix, and — importantly — would
    # raise a bare ``TypeError`` further in if the seam trusted it; the
    # refusal translates that failure into this member's own vocabulary
    # before it escapes ([[error-vocabulary-at-member-seams]]).
    class FrontingAList:
        def observed(self) -> list[Any]:
            return []

    with pytest.raises(PolicyTreeError, match="returns a mapping"):
        prefix_view(FrontingAList())


def test_prefix_view_refuses_keys_that_disagree_with_cells(
    question: PolicyQuestion, leaf_node: str
) -> None:
    # The mapping is keyed by the id each observation was *earned on*; a
    # mapping that keys ``n1`` against ``n2``'s observation is two names
    # for one cell, and the view refuses to pick one — the tree's refusal
    # of an ambiguous identity, restated at the projection seam.
    other = PolicyObservation.from_node(CampaignNode.freeze(
        "n2", {"r2_insample": 0.33}, parent_id="n0", depth=1
    ))

    class Disagreeing:
        def observed(self) -> dict[str, PolicyObservation]:
            return {leaf_node: other}

    with pytest.raises(PolicyTreeError, match="two names for one"):
        prefix_view(Disagreeing())


def test_duck_typed_question_fronts_a_view(tree: CampaignTree) -> None:
    # The composition seam: the module loader imports this member under a
    # synthetic name and re-executes it, so the question a caller hands may
    # be a *second* ``PolicyQuestion`` class object no ``isinstance`` in
    # this module can match.  The seam demands the read side and nothing
    # else, so a foreign carrier with an honest ``observed()`` fronts a
    # view carrying the same cells — one policy, both pools, and neither
    # pool's classes refused.
    class ForeignQuestion:
        def __init__(self, mapping: dict[str, PolicyObservation]) -> None:
            self._mapping = mapping

        def observed(self) -> dict[str, PolicyObservation]:
            return dict(self._mapping)

    honest = PolicyQuestion(tree)
    honest.reveal("n1")
    view = prefix_view(ForeignQuestion(honest.observed()))
    assert set(view.observed()) == {"n1"}
    assert view.observed()["n1"] == honest.observed()["n1"]
    assert len(view) == 1


def test_two_views_of_one_reveal_set_are_equal_and_hashable(
    question: PolicyQuestion,
) -> None:
    # A frozen value over frozen cells: equality is content, so two views
    # of one reveal set are one prefix however their rounds were built; and
    # the value hashes, so a replay can key a ledger by the object it handed
    # a policy without a wrapper.
    question.reveal_many(["n1", "n2"])
    first = prefix_view(question)
    second = prefix_view(question)
    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1


def test_repr_names_the_count_not_the_cells(question: PolicyQuestion) -> None:
    # The debugging aid says how big the prefix is and nothing else — the
    # same shape the question's own repr takes, so a log line carries the
    # size of what a policy saw without echoing its contents.
    question.reveal("n1")
    assert repr(prefix_view(question)) == "PrefixView(cells=1)"
