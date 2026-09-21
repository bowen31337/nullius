"""Feature 217, the campaign tree — the answer surface the question fronts.

app_spec.xml, "Exploration Policy Runtime", feature 217: *System exposes an
observed accessor which returns a mapping of revealed node ids to
observations.*  This feature is the read side of the identical ``question.*``
interface docs/nullius-tech-architecture.md §11 names — the surface an
exploration policy is handed during replay, and §10.2 makes *prefix-only*: a
policy sees only the cells it has already revealed.  The tree is the answer
surface that surface fronts.

The tree is a *set* of nodes in a stable order, and it deliberately carries no
reveal history — that is the question's, the one fact a replay needs and a tree
must not hold, because a tree whose answers depended on how often it had been
asked would not be a ground truth.  The invariants these tests pin are the ones
the read-side question depends on: that a tree is its nodes (the order a walk
visits them is not the tree), that a node is frozen and validated (a node that
does not parse, a depth that is negative, a parent that dangles is refused
rather than loaded as a plausible-looking node), and that the tree's identity
is a function of what the nodes *are*, not of how they were spelled — because a
tree that froze garbage would be fronting garbage and calling it the surface.
"""

from __future__ import annotations

import pytest

from policy_runtime import CampaignNode, CampaignTree, PolicyAddressError, PolicyTreeError


def test_tree_is_its_nodes_regardless_of_insertion_order() -> None:
    # A tree is a set, not the order a walk visits it, so two trees handed the
    # same nodes in a different order are one tree and one identity — or the
    # nightly canary's frozen tree would be a different tree every time the
    # walk order changed, and the read-side question would answer differently
    # for a policy that revealed the same cells in a different order.
    a = CampaignTree.freeze(
        {
            "n0": (None, 0, {"depth": 0}),
            "n1": ("n0", 1, {"parent_id": "n0", "depth": 1}),
        }
    )
    b = CampaignTree.freeze(
        {
            "n1": ("n0", 1, {"parent_id": "n0", "depth": 1}),
            "n0": (None, 0, {"depth": 0}),
        }
    )
    assert a.tree_id == b.tree_id


def test_tree_identity_changes_when_one_node_changes() -> None:
    # Two trees differing in one node are two trees, because the read-side
    # question fronts one tree and the policy's observations are a function of
    # that tree — a tree whose identity did not move when a node moved would be
    # an identity that could not prove the surface had not moved.
    a = CampaignTree.freeze(
        {
            "n0": (None, 0, {"depth": 0}),
            "n1": ("n0", 1, {"parent_id": "n0", "depth": 1, "r2_insample": 0.20}),
        }
    )
    b = CampaignTree.freeze(
        {
            "n0": (None, 0, {"depth": 0}),
            "n1": ("n0", 1, {"parent_id": "n0", "depth": 1, "r2_insample": 0.21}),
        }
    )
    assert a.tree_id != b.tree_id


def test_tree_refuses_an_empty_tree() -> None:
    # A tree with no nodes is a surface the policy could not walk — vacuous, the
    # one reading the read-side question must never allow, because a policy
    # fronted over nothing would report a gain on a pool it never saw.
    with pytest.raises(PolicyTreeError):
        CampaignTree(nodes=tuple())


def test_tree_refuses_a_duplicate_node_id() -> None:
    # A node id names one node, and two nodes wearing one id is a tree the
    # policy could not walk — the store's uniqueness key is on the node id, and
    # a tree that held one id twice would answer one reveal for two cells.
    with pytest.raises(PolicyTreeError):
        CampaignTree(
            nodes=(
                CampaignNode.freeze("n0", {"depth": 0}, depth=0),
                CampaignNode.freeze("n0", {"depth": 1}, depth=1),
            )
        )


def test_tree_refuses_a_dangling_parent_reference() -> None:
    # A parent reference names one of the tree's nodes; a dangling reference is
    # a tree with an edge the policy could not walk, and the refusal belongs at
    # the moment the tree is built, where it names the tree — not later, at the
    # first reveal of a node the policy was never shown.
    with pytest.raises(PolicyTreeError):
        CampaignTree.freeze({"n1": ("ghost", 1, {"depth": 1})})


def test_node_refuses_an_empty_id() -> None:
    # A node id is the id a parent reference and the store's uniqueness key are
    # on, and a node with none cannot be addressed or revealed — so a node that
    # cannot name itself is refused before it can name a cell the policy sees.
    with pytest.raises(PolicyTreeError):
        CampaignNode(node_id="", parent_id=None, depth=0, payload='{"depth": 0}')


def test_node_refuses_a_negative_depth() -> None:
    # Depth is a non-negative integer, zero at a root, and a negative one is a
    # level no walk could reach — so a node at a level the walk cannot reach is
    # refused rather than loaded as a plausible-looking cell.
    with pytest.raises(PolicyTreeError):
        CampaignNode(node_id="n0", parent_id=None, depth=-1, payload='{"depth": -1}')


def test_node_refuses_a_non_canonical_payload() -> None:
    # The payload is the frozen bytes the replay reads back, and a node whose
    # payload does not parse as it claims is refused at the seam that
    # reconstructs it — because a node that carries no honest reading carries a
    # reading the barrier never froze.
    with pytest.raises(PolicyTreeError):
        CampaignNode(node_id="n0", parent_id=None, depth=0, payload="{not json}")


def test_node_refuses_a_missing_payload() -> None:
    # A node with no payload froze nothing, and a node that froze nothing is a
    # cell the replay has no bytes for — refused rather than answered from a
    # neighbouring node the policy was never shown.
    with pytest.raises(PolicyTreeError):
        CampaignNode(node_id="n0", parent_id=None, depth=0, payload="")


def test_node_freeze_canonicalises_the_payload() -> None:
    # The freeze canonicalises the payload before constructing, so a node
    # handed the same metrics in a different key order is one node and one
    # payload — or two nodes the policy saw as different would be the same cell
    # spelled two ways, and the tree's identity would move on a re-spelling.
    a = CampaignNode.freeze("n0", {"b": 2, "a": 1}, depth=0)
    b = CampaignNode.freeze("n0", {"a": 1, "b": 2}, depth=0)
    assert a.payload == b.payload


def test_tree_node_returns_the_named_node() -> None:
    # The address seam is the one place a node id becomes a node, and it answers
    # the node the id names — so the question's observation is built from the
    # node the tree actually holds, and the observation and the node cannot
    # drift.
    tree = CampaignTree.freeze(
        {
            "n0": (None, 0, {"depth": 0}),
            "n1": ("n0", 1, {"parent_id": "n0", "depth": 1}),
        }
    )
    assert tree.node("n1").node_id == "n1"


def test_tree_node_refuses_a_node_outside_the_tree(tree: CampaignTree) -> None:
    # A node id a policy hands to the question is one it was shown, and a node
    # outside the tree names a cell the policy never saw — so the address seam
    # refuses it, naming the node and the tree, rather than answering a cell the
    # policy was never shown.  The refusal is a PolicyAddressError, kept apart
    # from a malformed-tree refusal because the tree was well-formed and it is
    # the node that is outside it.
    with pytest.raises(PolicyAddressError):
        tree.node("nope")
