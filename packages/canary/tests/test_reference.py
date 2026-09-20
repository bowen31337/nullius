"""Feature 141, the reference pair: the frozen policy and the frozen tree.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 141: *System
persists a frozen canary policy together with a frozen canary tree as the
determinism reference pair.*

This feature is the persistence half of the canary's determinism contract.
Features 142-144 replay the frozen policy over the frozen tree and halt the
system when the replayed score drifts from a recorded constant; this feature
is what makes that comparison *a comparison against a fixed thing* rather than
against whatever the policy and tree happen to be on the night the canary
runs. A canary that froze a policy and a tree that could still change under it
would be asserting the score against a moving target and calling it stable.

The freeze is the whole point, and it is carried by three value types:

* :class:`canary.CanaryPolicy` — a policy document, frozen by hashing the
  *canonical* JSON of its source, so two policies that differ only in key
  order or whitespace are the same policy and hash to the same id;
* :class:`canary.CanaryTree` — a tree of nodes, frozen by hashing the nodes
  in sorted order, so two trees that differ only in the order they were
  walked in are the same tree and hash to the same id;
* :class:`canary.CanaryReferencePair` — the two frozen together, plus the
  recorded score and identity that let the store hold one and hand it back.

The invariants these tests pin are the ones feature 142-144's replay depends
on: that the freeze is *content*-addressed (the hash is a function of what the
policy and tree *are*, not of how they were spelled), that a frozen thing
cannot be unfrozen by editing it in place (the dataclasses are frozen), and
that the pair refuses to freeze a policy that does not parse, a tree that does
not close, or a hash that does not match its source — because a canary that
froze garbage would be replaying garbage and calling it the reference.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from canary import (
    CanaryPolicy,
    CanaryReferencePair,
    CanaryTree,
    CanaryTreeNode,
    canonical_json,
    content_hash,
    tree_hash,
)
from canary._reference import CanaryError

# -- Canonicalisation & hashing --------------------------------------------------


def test_canonical_json_is_invariant_under_key_order() -> None:
    # The freeze is content-addressed, so the canonical form a policy is
    # hashed from must not depend on the order a caller happened to write its
    # keys in — {a:1,b:2} and {b:2,a:1} are the same object and must hash the
    # same, or a policy re-serialised by a different tool would be a different
    # policy.
    a = canonical_json({"a": 1, "b": 2, "nested": {"x": 1, "y": 2}})
    b = canonical_json({"nested": {"y": 2, "x": 1}, "b": 2, "a": 1})
    assert a == b


def test_canonical_json_is_compact_and_stable() -> None:
    # No incidental whitespace and no key reordering: the canonical form is a
    # deterministic function of the object, which is what makes the hash a
    # stable identity.
    assert canonical_json({"a": 1, "b": [1, 2, 3]}) == '{"a":1,"b":[1,2,3]}'


def test_canonical_json_refuses_what_cannot_serialize() -> None:
    # A policy whose source cannot be canonicalised cannot be frozen to a
    # stable hash, so the freeze refuses it rather than hashing a
    # half-serialization.
    with pytest.raises(CanaryError, match="JSON-canonicalisable"):
        canonical_json({"a": object()})


def test_content_hash_is_a_sha256_hex_digest() -> None:
    digest = content_hash("hello")
    assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert len(digest) == 64
    assert digest == digest.lower()


def test_tree_hash_is_invariant_under_node_order() -> None:
    # The tree is hashed over its sorted nodes, so a tree built in one walk
    # order and the same tree built in another are the same tree — feature
    # 142's replay compares against *the tree*, not against an ordering.
    nodes_a = {
        "root": (None, 0, {"label": "root"}),
        "a": ("root", 1, {"label": "a"}),
        "b": ("root", 1, {"label": "b"}),
    }
    nodes_b = {
        "b": ("root", 1, {"label": "b"}),
        "root": (None, 0, {"label": "root"}),
        "a": ("root", 1, {"label": "a"}),
    }
    assert tree_hash(nodes_a) == tree_hash(nodes_b)


def test_tree_hash_changes_when_a_payload_changes() -> None:
    nodes_a = {"root": (None, 0, {"label": "root"})}
    nodes_b = {"root": (None, 0, {"label": "changed"})}
    assert tree_hash(nodes_a) != tree_hash(nodes_b)


# -- CanaryPolicy ----------------------------------------------------------------


def test_a_policy_freezes_to_its_source_hash() -> None:
    source = {"scoring": {"weights": {"a": 0.5, "b": 0.5}}, "version": 1}
    policy = CanaryPolicy.freeze(version="1", policy=source)
    assert policy.code_hash == content_hash(canonical_json(source))
    assert policy.source == canonical_json(source)
    # The frozen source round-trips back to the object it was frozen from.
    assert policy.policy == source


def test_a_policy_freeze_is_stamped_with_an_aware_timestamp() -> None:
    policy = CanaryPolicy.freeze(version="1", policy={"a": 1})
    assert policy.created_at.tzinfo is not None


def test_a_policy_can_be_frozen_with_an_explicit_timestamp() -> None:
    when = datetime(2025, 1, 1, tzinfo=timezone.utc)
    policy = CanaryPolicy.freeze(version="1", policy={"a": 1}, created_at=when)
    assert policy.created_at == when


def test_a_policy_freeze_is_immutable() -> None:
    # A frozen reference that could be mutated after the fact would be a
    # reference that drifted, so the dataclass is frozen: the policy a canary
    # replays next month is byte-for-byte the policy it froze this month.
    policy = CanaryPolicy.freeze(version="1", policy={"a": 1})
    with pytest.raises(Exception):
        policy.version = 2  # type: ignore[misc]


def test_a_policy_freeze_accepts_an_empty_object() -> None:
    # A policy is a JSON object; an empty one is a (degenerate) policy, not an
    # error. The freeze refuses a non-object source, not an empty one.
    policy = CanaryPolicy.freeze(version="1", policy={})
    assert policy.policy == {}
    assert policy.code_hash == content_hash("{}")


def test_a_policy_freeze_refuses_a_non_object_source() -> None:
    # A policy is a document, not a list or a scalar: the replay reads named
    # keys out of it, so a source that is not a JSON object cannot be one.
    with pytest.raises(CanaryError, match="JSON object"):
        CanaryPolicy.freeze(version="1", policy=[1, 2, 3])


def test_a_policy_refuses_a_hash_that_does_not_name_its_source() -> None:
    # The code_hash is the policy's identity — the thing feature 142 replays
    # against — so a policy that claimed a hash other than the hash of its
    # own source would be lying about what it froze. Construction refuses it.
    with pytest.raises(CanaryError, match="code_hash"):
        CanaryPolicy(
            version="1",
            source=canonical_json({"a": 1}),
            code_hash="0" * 64,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )


def test_a_policy_refuses_a_malformed_hash() -> None:
    with pytest.raises(CanaryError, match="code_hash"):
        CanaryPolicy(
            version="1",
            source=canonical_json({"a": 1}),
            code_hash="not-a-valid-hash",
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )


def test_two_policies_with_the_same_content_share_a_hash() -> None:
    # Content-addressing, stated directly: two policies that differ only in
    # how their source was spelled are the same policy.
    a = CanaryPolicy.freeze(version="1", policy={"a": 1, "b": 2})
    b = CanaryPolicy.freeze(version="1", policy={"b": 2, "a": 1})
    assert a.code_hash == b.code_hash


# -- CanaryTree ------------------------------------------------------------------


def test_a_tree_freezes_its_nodes_and_hashes_them() -> None:
    tree = CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root"}),
            "child": ("root", 1, {"label": "child"}),
        }
    )
    assert len(tree.nodes) == 2
    assert tree.tree_hash is not None
    assert len(tree.tree_hash) == 64
    # Nodes are stored sorted by node_id, so the freeze is order-stable.
    assert [node.node_id for node in tree.nodes] == ["child", "root"]


def test_a_tree_node_exposes_its_frozen_payload() -> None:
    tree = CanaryTree.freeze({"n": (None, 0, {"a": 1})})
    assert tree.nodes[0].content == {"a": 1}


def test_a_tree_freeze_refuses_an_empty_tree() -> None:
    with pytest.raises(CanaryError, match="at least one node"):
        CanaryTree.freeze({})


def test_a_tree_freeze_refuses_a_dangling_parent() -> None:
    # A node whose parent does not exist is not a tree — feature 142's replay
    # walks parents, so a node pointing at a parent that was never frozen
    # would send the replay off a cliff. The freeze refuses the open tree.
    with pytest.raises(CanaryError, match="parent"):
        CanaryTree.freeze({"a": ("ghost", 1, {})})


def test_a_tree_freeze_refuses_a_negative_depth() -> None:
    with pytest.raises(CanaryError, match="depth"):
        CanaryTree.freeze({"a": (None, -1, {})})


def test_a_tree_freeze_refuses_a_boolean_depth() -> None:
    # A bool is an int in Python, but it is not a depth: accepting ``True``
    # as depth 1 would be the kind of silent coercion a determinism contract
    # exists to refuse.
    with pytest.raises(CanaryError, match="depth"):
        CanaryTree.freeze({"a": (None, True, {})})


def test_a_tree_freeze_refuses_two_nodes_sharing_an_id() -> None:
    # A dict literal would silently collapse two ``"a"`` keys into one, so the
    # duplicate is built as two nodes and handed to the constructor directly —
    # the seam that actually walks the id set. A node id names one node; two
    # nodes wearing one id is a tree the replay could not walk.
    nodes = (
        CanaryTreeNode.freeze("a", {"x": 1}, depth=0),
        CanaryTreeNode.freeze("a", {"x": 2}, depth=1),
    )
    with pytest.raises(CanaryError, match="appears twice"):
        CanaryTree(nodes=nodes)


def test_a_tree_freeze_refuses_a_node_with_an_empty_id() -> None:
    with pytest.raises(CanaryError, match="node_id"):
        CanaryTreeNode.freeze("", {"x": 1}, depth=0)


def test_a_node_refuses_a_payload_that_is_not_json() -> None:
    # A node carries canonical bytes — the ones the replay reads back — so a
    # payload that is not canonical JSON cannot be frozen into one. The refusal
    # is at the node, the unit that holds the bytes.
    with pytest.raises(CanaryError, match="canonical JSON"):
        CanaryTreeNode(node_id="a", parent_id=None, depth=0, payload="not json")


# -- CanaryTreeNode --------------------------------------------------------------


def test_a_tree_node_freezes_with_a_none_parent_default() -> None:
    node = CanaryTreeNode.freeze("a", {"x": 1}, depth=0)
    # A node built alone is a root until joined: ``parent_id`` defaults to
    # ``None`` (absent), and the tree decides whether that is a valid root.
    assert node.parent_id is None
    assert node.depth == 0
    assert node.payload == canonical_json({"x": 1})


def test_a_tree_node_alone_does_not_know_its_parent_is_dangling() -> None:
    # A node by itself cannot see its siblings, so a dangling parent is the
    # tree's to refuse (and is, below) — not the node's. This keeps the node
    # constructible in isolation, which is what lets the tree validate the
    # whole set at once.
    node = CanaryTreeNode.freeze("a", {}, parent_id="ghost", depth=1)
    assert node.parent_id == "ghost"


# -- CanaryReferencePair ---------------------------------------------------------


def _policy(version: str = "1") -> CanaryPolicy:
    return CanaryPolicy.freeze(version=version, policy={"scoring": {"a": 1.0}})


def _tree() -> CanaryTree:
    return CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root"}),
            "leaf": ("root", 1, {"label": "leaf"}),
        }
    )


def _pair(**overrides) -> CanaryReferencePair:
    """A reference pair with sensible defaults, overridable per test.

    The constructor takes every field — a pair is the policy, the tree, the
    recorded score, the row id, the active flag and the freeze instant — so a
    helper keeps the pair tests from restating the plumbing in each one.
    """
    fields = {
        "policy": _policy(),
        "tree": _tree(),
        "recorded_score": None,
        "id": None,
        "is_active": True,
        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    fields.update(overrides)
    return CanaryReferencePair(**fields)


def test_a_pair_binds_a_policy_a_tree_and_a_recorded_score() -> None:
    pair = _pair(recorded_score=0.9876)
    assert pair.recorded_score == 0.9876
    assert pair.is_active is True


def test_a_pair_is_constructed_without_an_id_until_persisted() -> None:
    # A pair not yet frozen into the store carries no row id — the id is the
    # store's, minted on write, not the pair's.
    assert _pair().id is None


def test_a_pair_can_carry_an_explicit_uuid() -> None:
    given = str(uuid.uuid4())
    assert _pair(id=given).id == given


def test_a_pair_refuses_a_non_policy() -> None:
    with pytest.raises(CanaryError, match="policy"):
        _pair(policy="not a policy")  # type: ignore[arg-type]


def test_a_pair_refuses_a_non_tree() -> None:
    with pytest.raises(CanaryError, match="tree"):
        _pair(tree="not a tree")  # type: ignore[arg-type]


def test_a_pair_refuses_a_non_uuid_identity() -> None:
    with pytest.raises(CanaryError, match="UUID"):
        _pair(id="not-a-uuid")


def test_a_pair_accepts_a_null_recorded_score() -> None:
    # Feature 141 freezes the pair; the recorded score is filled in when the
    # canary first runs (feature 142). A pair with no score yet is a valid
    # frozen pair, not an error — the score is Nullable by design.
    assert _pair(recorded_score=None).recorded_score is None


def test_a_pair_refuses_a_non_number_recorded_score() -> None:
    # The recorded score is the constant the nightly replay compares against,
    # so a value that is not a number cannot be one. A string score is refused.
    with pytest.raises(CanaryError, match="recorded_score"):
        _pair(recorded_score="0.99")


def test_a_pair_refuses_a_boolean_recorded_score() -> None:
    # A bool is an int in Python, but it is not a score — the same coercion
    # the tree's depth refuses, for the same determinism-contract reason.
    with pytest.raises(CanaryError, match="recorded_score"):
        _pair(recorded_score=True)


def test_the_content_fingerprint_addresses_the_pair_by_what_it_froze() -> None:
    # The fingerprint is (policy hash, tree hash): the two things feature
    # 142's replay will reproduce. Two pairs over the same content share it;
    # two pairs over different content do not.
    a = _pair()
    b = _pair()
    c = _pair(
        policy=CanaryPolicy.freeze(version="1", policy={"scoring": {"b": 2.0}})
    )
    assert a.content_fingerprint == b.content_fingerprint
    assert a.content_fingerprint != c.content_fingerprint


def test_has_same_content_as_compares_what_was_frozen_not_the_identity() -> None:
    # Two pairs over the same policy and tree are the same reference however
    # they were built — which is what the store's write-back check relies on
    # to confirm a freeze landed the thing it meant to.
    a = _pair(id=str(uuid.uuid4()))
    b = _pair(id=str(uuid.uuid4()))
    assert a.id != b.id
    assert a.has_same_content_as(b)


def test_has_same_content_as_distinguishes_a_changed_tree() -> None:
    a = _pair()
    b = _pair(tree=CanaryTree.freeze({"solo": (None, 0, {"label": "solo"})}))
    assert not a.has_same_content_as(b)
