"""Feature 219, the meta accessor — the structural read of the question.* surface.

app_spec.xml, "Exploration Policy Runtime", feature 219: *System exposes a meta
accessor which returns structural cell metadata including branch, depth, parent
and theme_root.*  docs/nullius-tech-architecture.md §595 spells the accessor as
``question.meta(node_id) -> CellMeta`` and names the four fields in its own
comment; §11.1 says *why* ``theme_root`` is among them (the overfit signature is
only partly family-invariant, so family-conditional thresholds need the slug);
and §634 makes this accessor the *only* road to it — ``theme_root`` used only
via ``meta()`` is one of the static checks a policy must pass before it is
admitted (feature 230's gate).

The invariants these tests pin are the ones the accessor's contract depends on:

* **the four fields, derived not stored** — ``parent`` is the tree's own
  validated edge, ``depth`` the number of parent steps to the origin of the
  cell's branch, ``branch`` that origin's id (``None`` when the cell *is* the
  origin), and ``theme_root`` the family the node's own record states.  A meta
  is a pure function of ``(tree, node_id)``: two reads answer equal frozen
  values, and no reveal moves either one;
* **structure is not the reading** — §10.2's barrier withholds *scores*, and cq-8
  withholds ``is_null`` altogether; the tree's *shape* is the thing §11.1
  requires exposed so that family-conditional thresholds can be authored at all.
  So the accessor answers for an unrevealed node the tree holds, and a payload
  full of metrics yields exactly four structural fields and no reading;
* **the refusals are the member's own** — a node the tree does not hold is
  :class:`PolicyAddressError` (the address seam ``reveal`` and ``probe_batch``
  route through), and a corrupt structural record or a parent chain with no
  origin is :class:`PolicyTreeError`.  All three are caught by
  :class:`PolicyRuntimeError`, so a caller's own ``except`` catches every way a
  structural read can fail;
* **the surface is not widened** — ``meta`` is a *question* verb and stays off
  the prefix view (feature 223, docs §10.2 cq-16), which is asserted in
  ``test_prefix.py``; the accessor here adds no name a policy could reach the
  withheld answers through.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from typing import ClassVar

import pytest

from policy_runtime import (
    THEME_ROOT_KEY,
    CampaignNode,
    CampaignTree,
    CellMeta,
    PolicyAddressError,
    PolicyAnswerSurfaceError,
    PolicyQuestion,
    PolicyRuntimeError,
    PolicyTreeError,
    cell_meta,
    policy_question,
    policy_surface,
)


def _meta_tree() -> CampaignTree:
    """A tree with a branch to be structurally described.

    ``r0`` is a root in family ``momentum`` with two children; ``r1`` is a
    second root in ``value``; ``r0a`` has a child of its own, so the tree
    carries depth 2 and a cell whose parent is not the origin — the shapes the
    four fields are pinned over.  The leaves carry metrics *and* ``is_null``, so
    the tests can assert the accessor reads structure and never a reading.
    """
    return CampaignTree.freeze(
        {
            "r0": (None, 0, {THEME_ROOT_KEY: "momentum"}),
            "r0a": ("r0", 1, {THEME_ROOT_KEY: "momentum", "depth": 1}),
            "r0a1": (
                "r0a",
                2,
                {
                    THEME_ROOT_KEY: "momentum",
                    "parent_id": "r0a",
                    "depth": 2,
                    "r2_insample": 0.41,
                    "ic_insample": 0.11,
                    "n_periods": 500,
                    "n_features": 12,
                    "is_null": True,
                },
            ),
            "r0b": ("r0", 1, {THEME_ROOT_KEY: "momentum"}),
            "r1": (None, 0, {THEME_ROOT_KEY: "value", "depth": 0}),
        }
    )


@pytest.fixture
def meta_question() -> PolicyQuestion:
    """The read-side question over the branch-shaped tree."""
    return policy_question(_meta_tree())


# --- the four fields -------------------------------------------------------


def test_meta_reports_the_four_structural_fields(meta_question: PolicyQuestion) -> None:
    # docs §595's comment names exactly four: branch, depth, parent, theme_root.
    # A CellMeta is those four and nothing else — the accessor reads four keys
    # of the tree, so a payload full of metrics and is_null yields structure and
    # never a reading (prd §4.2, cq-8).
    meta = meta_question.meta("r0a1")
    assert isinstance(meta, CellMeta)
    assert (
        meta.branch,
        meta.depth,
        meta.parent,
        meta.theme_root,
    ) == ("r0", 2, "r0a", "momentum")


def test_meta_of_a_root_is_its_own_branch_origin(meta_question: PolicyQuestion) -> None:
    # A root has no parent and sits at the origin of its own branch, so its
    # structure is the empty one: no parent, no origin above it, depth zero.
    # ``branch is None`` — rather than the root's own id — is the sibling pool's
    # answer for its root too, so "this cell is a branch origin" reads the same
    # on both pools and one policy runs unmodified against either (feature 184).
    meta = meta_question.meta("r0")
    assert (meta.branch, meta.depth, meta.parent) == (None, 0, None)
    assert meta.theme_root == "momentum"


def test_meta_depth_is_counted_along_the_parent_chain(
    meta_question: PolicyQuestion,
) -> None:
    # Depth is the number of parent steps to the origin, not the node's declared
    # ``depth`` field: r0a carries no depth key at all and still answers 1, and
    # r0a1 answers 2 from its edges.  Deriving it is what makes a meta and the
    # tree it describes unable to drift when a writer recorded no depth.
    assert meta_question.meta("r0a").depth == 1
    assert meta_question.meta("r0a1").depth == 2
    assert meta_question.meta("r1").depth == 0


def test_meta_branch_groups_a_whole_subtree(meta_question: PolicyQuestion) -> None:
    # ``branch`` is the origin of the branch a cell sits in, so every cell below
    # one root names that root — the grouping feature 236's per-branch census is
    # taken over.  A cell in the *other* root's branch names that one instead,
    # so the field discriminates between branches rather than merely reporting a
    # depth.
    branches = {
        node_id: meta_question.meta(node_id).branch
        for node_id in ("r0", "r0a", "r0a1", "r0b", "r1")
    }
    assert branches == {
        "r0": None,
        "r0a": "r0",
        "r0a1": "r0",
        "r0b": "r0",
        "r1": None,
    }


def test_meta_parent_is_the_trees_own_edge(meta_question: PolicyQuestion) -> None:
    # The parent is read from the tree's node, whose reference the tree validated
    # when it was built — so a parent named by a meta is always a node the tree
    # holds, and one read of ``meta`` and one of ``parent_id`` cannot disagree.
    for node_id in ("r0", "r0a", "r0a1", "r0b", "r1"):
        assert meta_question.meta(node_id).parent == meta_question.tree.node(node_id).parent_id


def test_meta_answers_for_an_unrevealed_cell(meta_question: PolicyQuestion) -> None:
    # Structure is the tree's shape, not the reading §10.2's barrier withholds:
    # §11.1 exposes theme_root here precisely so family-conditional thresholds can
    # be authored before the cells they condition are revealed.  So a fresh
    # question — nothing revealed at all — still answers structure, and the read
    # does not grow the reveal set.
    assert meta_question.revealed == frozenset()
    assert meta_question.meta("r0a1").theme_root == "momentum"
    assert meta_question.revealed == frozenset()


def test_meta_carries_no_reading_from_the_payload(meta_question: PolicyQuestion) -> None:
    # The leaf's payload carries r2_insample, ic_insample, n_periods,
    # n_features and is_null; the meta carries four structural fields and never
    # a scored one.  is_null is the sharp case: cq-8 confines it to exactly one
    # component, the replay scorer, so an accessor that leaked it would be a
    # back door through a structural read.
    meta = meta_question.meta("r0a1")
    fields = set(meta.row())
    assert fields == {"branch", "depth", "parent", "theme_root"}
    assert "is_null" not in fields
    assert not hasattr(meta, "r2_insample")
    assert "is_null" not in json.dumps(meta.row())


def test_meta_is_a_pure_function_of_tree_and_node(
    meta_question: PolicyQuestion,
) -> None:
    # Two reads answer equal frozen values, whatever happened in between — a
    # node's structure is a fact about where it sits and not something a reveal
    # can move, so a policy comparing two cells cannot move either one's
    # structure.  A second question over the same nodes answers identically.
    before = meta_question.meta("r0a1")
    meta_question.probe_batch(["r0a1", "r0b"])
    assert meta_question.meta("r0a1") == before
    assert policy_question(_meta_tree()).meta("r0a1") == before


def test_cell_meta_row_is_a_fresh_mapping(meta_question: PolicyQuestion) -> None:
    # A store-shaped row, and a fresh dict per call: a caller that scribbles on
    # what it read moves its own copy rather than the meta's — the guarantee the
    # observation beside it states for the same reason.
    meta = CellMeta(branch="r0", depth=2, parent="r0a", theme_root="momentum")
    row = meta.row()
    assert row == {
        "branch": "r0",
        "depth": 2,
        "parent": "r0a",
        "theme_root": "momentum",
    }
    row["depth"] = 99
    assert meta.row()["depth"] == 2


# --- absence, and the corrupt record ---------------------------------------


def test_meta_reports_no_family_when_the_record_states_none(
    meta_question: PolicyQuestion,
) -> None:
    # A payload that carries no theme_root answers None — the honest null this
    # member states for a structural node, one field over from an observation
    # that carries no in-sample reading.  The accessor never invents a family.
    tree = CampaignTree.freeze({"plain": (None, 0, {"depth": 0})})
    assert cell_meta(tree, "plain").theme_root is None


def test_meta_reports_no_family_when_the_record_states_null(
    meta_question: PolicyQuestion,
) -> None:
    # The key present and None is the same statement as the key absent: the
    # record states no family.  Absence is not corruption.
    tree = CampaignTree.freeze({"plain": (None, 0, {THEME_ROOT_KEY: None})})
    assert cell_meta(tree, "plain").theme_root is None


def test_meta_refuses_a_family_that_cannot_be_named() -> None:
    # A record that *does* state the field but states something that is not a
    # name — a blank string, a number, a nested object — is a corrupt structural
    # record rather than a silent absence, and is refused naming the node: the
    # member's never-coerce stance (families._theme_key).  A family that cannot
    # be named cannot be conditioned.
    for broken in ("", "   ", 7, {"slug": "momentum"}):
        tree = CampaignTree.freeze({"bad": (None, 0, {THEME_ROOT_KEY: broken})})
        with pytest.raises(PolicyTreeError) as excinfo:
            cell_meta(tree, "bad")
        assert "bad" in str(excinfo.value)
        assert isinstance(excinfo.value, PolicyRuntimeError)


def test_meta_does_not_normalise_a_family_slug() -> None:
    # Which themes may exist is feature 241's committed config, not this
    # accessor's — restating that ceiling here would be a second spelling of a
    # config-bound law.  So a slug is carried verbatim: the accessor reports the
    # record's own family rather than approving or rewriting it.
    tree = CampaignTree.freeze({"odd": (None, 0, {THEME_ROOT_KEY: "Momentum "})})
    assert cell_meta(tree, "odd").theme_root == "Momentum "


def test_cell_meta_refuses_a_negative_depth() -> None:
    # The value type validates its own fields, the stance every value type in
    # this member takes: a negative depth is a level no walk could reach.
    with pytest.raises(PolicyTreeError):
        CellMeta(branch=None, depth=-1, parent=None, theme_root="momentum")


def test_cell_meta_refuses_a_bool_depth() -> None:
    # A bool is not a level — ``True`` is not one parent step — and the member's
    # integer checks refuse it everywhere rather than letting it pass as 1.
    with pytest.raises(PolicyTreeError):
        CellMeta(branch=None, depth=True, parent=None, theme_root="momentum")  # type: ignore[arg-type]


def test_cell_meta_refuses_a_blank_structural_name() -> None:
    # A branch, a parent and a family are each None or a name: an empty string
    # is a hole where a name should be rather than a fact, and the refusal names
    # the field.
    for kwargs in (
        {"branch": "  "},
        {"parent": ""},
        {"theme_root": ""},
    ):
        fields = {"branch": None, "depth": 0, "parent": None, "theme_root": "value"}
        fields.update(kwargs)
        with pytest.raises(PolicyTreeError) as excinfo:
            CellMeta(**fields)  # type: ignore[arg-type]
        assert next(iter(kwargs)) in str(excinfo.value)


def test_cell_meta_is_frozen() -> None:
    # A node's structure is a fact about where it sits and not something a
    # reveal changes, so the value carrying it cannot be moved in place.
    meta = CellMeta(branch=None, depth=0, parent=None, theme_root="momentum")
    with pytest.raises(FrozenInstanceError):
        meta.depth = 4  # type: ignore[misc]


# --- the refusals ----------------------------------------------------------


def test_meta_refuses_a_node_outside_the_tree(meta_question: PolicyQuestion) -> None:
    # A node id a policy hands to meta is one it was shown, and structure
    # computed for a cell outside the tree would let a policy reason about a
    # campaign it never saw.  The refusal is the tree's own address seam —
    # PolicyAddressError, the same class reveal and probe_batch refuse through —
    # so the specific sentence naming the node and the tree survives.
    with pytest.raises(PolicyAddressError) as excinfo:
        meta_question.meta("nope")
    assert "nope" in str(excinfo.value)
    assert isinstance(excinfo.value, PolicyRuntimeError)


def test_meta_refuses_a_node_id_that_is_not_a_name(meta_question: PolicyQuestion) -> None:
    # An id that is not a string names no cell at all, and is refused in this
    # member's own vocabulary rather than escaping as a bare TypeError from a
    # comparison — so a caller's ``except PolicyRuntimeError`` catches it.
    for bogus in ("", "   ", 7, None, ["r0"]):
        with pytest.raises(PolicyAddressError):
            meta_question.meta(bogus)  # type: ignore[arg-type]


def test_meta_refuses_a_tree_with_no_address_verb() -> None:
    # The seam is duck-typed — the loader's double-import makes the composed
    # tree a second CampaignTree class object — so what the seam *reads* is
    # validated: an object with no node() names no structure to report, and an
    # object whose node() fails is refused in this module's vocabulary rather
    # than letting an AttributeError escape.
    with pytest.raises(PolicyTreeError):
        cell_meta("not a tree", "r0")

    class _Broken:
        nodes: tuple[object, ...] = ()

        def node(self, node_id: str) -> object:
            raise ValueError("no")

    with pytest.raises(PolicyTreeError):
        cell_meta(_Broken(), "r0")


def test_meta_refuses_a_parent_chain_that_revisits_a_node() -> None:
    # Feature 217's constructor refuses a *dangling* parent reference but has no
    # reason to walk, so a closed chain reaches the accessor — and a cell on a
    # cycle has no branch origin and no depth.  Refused, rather than followed
    # forever or answered with an invented root.
    a = CampaignNode.freeze("a", {THEME_ROOT_KEY: "momentum"}, parent_id="b", depth=1)
    b = CampaignNode.freeze("b", {THEME_ROOT_KEY: "momentum"}, parent_id="a", depth=1)
    tree = CampaignTree(nodes=(a, b))
    with pytest.raises(PolicyTreeError) as excinfo:
        cell_meta(tree, "a")
    assert "a" in str(excinfo.value)


def test_meta_refuses_a_parent_chain_with_a_missing_link() -> None:
    # The same walk, one link short: a parent the tree's own index does not hold
    # reaches no origin, so the cell has no structure to report rather than a
    # depth guessed at.
    #
    # CampaignTree refuses a dangling parent reference by construction, so the
    # missing link cannot be built through the constructor.  It is expressed on
    # a carrier that eludes that check instead — the shape a tree mutated past
    # its constructor, or built by another implementation, has — because the
    # accessor must refuse the malformed tree rather than trust the check that
    # was supposed to make it impossible.
    node = CampaignNode.freeze("solo", {THEME_ROOT_KEY: "value"}, parent_id="ghost", depth=1)

    class _Leaky:
        def node(self, node_id: str) -> CampaignNode:
            return node

    # Assigned after the class body, not inside it: a class body does not close
    # over an enclosing function's locals (an unbound name there resolves to the
    # globals), which is a trap rather than a statement about this feature.
    _Leaky.nodes = (node,)  # type: ignore[attr-defined]

    with pytest.raises(PolicyTreeError) as excinfo:
        cell_meta(_Leaky(), "solo")
    assert "solo" in str(excinfo.value)
    assert "ghost" in str(excinfo.value)


def test_meta_refuses_a_payload_that_is_not_a_record() -> None:
    # theme_root is read *by name* from the record the node froze — §9.1's own
    # column — so a payload that is not a mapping of fields names no family and
    # no structure, and is refused naming the node.
    class _NotARecord:
        node_id = "flat"
        parent_id = None
        payload = "[1, 2, 3]"

    class _Leaky:
        nodes = (_NotARecord(),)

        def node(self, node_id: str) -> object:
            return _NotARecord()

    with pytest.raises(PolicyTreeError) as excinfo:
        cell_meta(_Leaky(), "flat")
    assert "flat" in str(excinfo.value)


def test_meta_reads_a_foreign_nodes_frozen_payload() -> None:
    # A node that is not this member's CampaignNode still carries the same node
    # model — the one fact the store and the tree share — so the accessor reads
    # its content mapping rather than demanding a class it cannot isinstance.
    class _Foreign:
        node_id = "f0"
        parent_id = None
        content: ClassVar[dict[str, str]] = {THEME_ROOT_KEY: "value"}
        payload = '{"theme_root": "value"}'

    class _Tree:
        nodes = (_Foreign(),)

        def node(self, node_id: str) -> object:
            return _Foreign()

    assert cell_meta(_Tree(), "f0").theme_root == "value"


def test_meta_refuses_a_tree_whose_nodes_cannot_be_walked() -> None:
    # The parent walk is keyed by node id, so a node carrying none cannot be
    # placed in the tree it belongs to — refused in this module's vocabulary,
    # naming what arrived rather than letting an AttributeError escape.
    class _NoId:
        parent_id = None
        payload = '{"theme_root": "value"}'

    class _Leaky:
        nodes = (_NoId(),)

        def node(self, node_id: str) -> object:
            return _NoId()

    with pytest.raises(PolicyTreeError):
        cell_meta(_Leaky(), "whatever")


# --- the surface -----------------------------------------------------------


def test_meta_is_the_same_call_on_both_pools(meta_question: PolicyQuestion) -> None:
    # docs §11's interface is *identical* on both pools, and this is the fourth
    # line of it: the sibling pool answers meta(node_id) -> CellMeta with the
    # same four fields and the same None-at-the-origin answer, which is what
    # makes "one policy, both pools" a fact about the seam.  The shape asserted
    # here is the shape feature 184's accessor answers.
    meta = meta_question.meta("r0")
    assert {field: getattr(meta, field) for field in meta.row()} == {
        "branch": None,
        "depth": 0,
        "parent": None,
        "theme_root": "momentum",
    }


def test_meta_takes_an_argument_so_it_is_not_a_surface_answer(
    meta_question: PolicyQuestion,
) -> None:
    # §11's surface answers are the *zero-argument* reads a deployment may
    # configure (observed, budget_remaining), and feature 224's surface copies
    # such an answer's *value* out at construction.  ``meta`` is a verb needing
    # a node id, so it is refused as an answer name rather than guessed at —
    # which matters here: a surface that admitted it would hand a policy the
    # whole tree's structure as a callable, a door to structural metadata that
    # named no cell, beside the prefix-only readings the surface exists to hold.
    #
    # The accessor's own signature is the first half of that, and it is what the
    # surface's refusal turns on — the question is the episode a surface fronts,
    # so this is the same construction test_surface.py:618 exercises, pinned
    # here because feature 219 is what introduces the verb into that answer set.
    assert callable(meta_question.meta)
    with pytest.raises(TypeError):
        meta_question.meta()  # type: ignore[call-arg]

    with pytest.raises(PolicyAnswerSurfaceError) as refusal:
        policy_surface(meta_question, answers=("meta",))
    assert "meta" in str(refusal.value)
