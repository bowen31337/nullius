"""The frozen determinism reference pair — a policy and the tree it replays over.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 141: *System
persists a frozen canary policy together with a frozen canary tree as the
determinism reference pair.*  docs/nullius-tech-architecture.md §12 closes its
determinism table with the nightly canary — *"replay a frozen policy*
``π_canary`` *over a frozen tree* ``T_canary`` *and assert the score matches a
recorded constant to* ``1e-12``" — and line 677 spells the same test as code.
:mod:`canary._reference` is the *frozen pair* that test replays; the store that
writes it down is :mod:`canary._reference_store`, and the migration that creates
the two tables is ``migrations/versions/0119_canary_reference_pair.py``.

Three decisions shape this module, and each is a reading of one word in the
feature: *frozen*.

**Frozen means byte-identical, and byte-identical means canonical.**  A policy
or a tree node is a structured value — a mapping of parameters, a payload — and
two mappings that differ only in key order are the *same* policy rendered two
ways.  A determinism reference that stored "whichever rendering arrived" would
let the bytes under test drift with nothing to show for it: the very drift the
canary exists to catch.  So every value is reduced to one canonical rendering
before it is hashed or stored — :func:`canonical_json`, a key-sorted,
whitespace-stripped encoding — and the content hash is taken over *that*
rendering, not over whatever the caller happened to hold.  A policy and the
same policy with its keys reordered therefore produce one hash, and a policy
that differs in one parameter produces a different one.  The hash is the
identity; the canonical bytes are what the hash is the hash *of*; both are
carried, so a stored pair is checkable rather than merely present — the same
discipline :mod:`nulloracle.ksguard` applies to a stored p-value, and the same
reason it exists: the stored reference is what the nightly replay compares
against, and a store that could hand back bytes disagreeing with their own hash
would launder a tamper.

**The hash is the identity, and the identity is checked on the read path.**
:func:`content_hash` is ``sha256`` over the canonical bytes — the algorithm the
rest of the determinism spine uses for its provenance columns
(:data:`canary.DIGEST_ALGORITHM`, the ``CHAR(64)`` columns beside it), so a
policy's ``code_hash`` and a tree's ``tree_hash`` are the same *kind* of value
as ``evaluator_hash`` and ``code_hash`` elsewhere.  A :class:`CanaryPolicy`
built from a row re-derives its hash from the stored bytes and refuses to
reconstruct when the stored hash names different bytes — a row edited in place
is a reference that is no longer what was frozen, and the nightly canary must
fail loudly on it, not replay against a silently-moved target.

**The tree is a set, rendered in a stable order.**  A tree is its nodes; the
order a walk happens to visit them in is not part of the tree.  So
:class:`CanaryTree` sorts its nodes by ``node_id`` before it hashes or stores
them, and :func:`tree_hash` is taken over that sorted order — a tree and the
same tree walked root-first versus leaf-first are one hash.  A parent reference
that names no node in the tree is refused at construction: a frozen tree with a
dangling edge is not a tree the replay path could walk, and the refusal belongs
at the moment the pair is frozen, where it names the pair, rather than at the
nightly replay, where it would name a night.

What this module deliberately does **not** do is resolve, compare, or write
anything down.  It is a set of pure value types over bytes a caller already
holds — the same stance :mod:`canary._reproducibility` takes for its
comparisons, and the one feature 145's module states for the same reason: there
is nothing to configure and no environment to read, so a freshly-built pair and
a stored one reconstruct through the same code.  The store owns the writing
(feature 141's verb, *persists*); feature 142's nightly replay owns the
comparison against the recorded constant and the ``1e-12`` tolerance; this
module only makes the pair a thing that can be frozen, hashed and told apart
from a pair that is not the same pair.  A canary that could not say *which*
policy and *which* tree it froze could not honestly say its replay reproduced
them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from ._errors import CanaryError

__all__ = [
    "CanaryPolicy",
    "CanaryReferencePair",
    "CanaryTree",
    "CanaryTreeNode",
    "canonical_json",
    "content_hash",
    "tree_hash",
]

#: The digest the reference pair's identities are spelled with.  Not a
#: preference: it is :data:`canary.DIGEST_ALGORITHM`, the sha256 the pin sweep
#: and the determinism spine's ``CHAR(64)`` provenance columns already use, so a
#: policy's ``code_hash`` and a tree's ``tree_hash`` order beside ``evaluator_hash``
#: and ``code_hash`` as the same kind of value — one sha256 over the bytes that
#: produced a score.
_HASH_ALGORITHM = "sha256"

#: Width of a sha256 hex digest — the width every ``CHAR(64)`` provenance column
#: in the tree declares, so a stored ``code_hash`` or ``tree_hash`` is the same
#: width a reader already expects of a content hash.
_HASH_HEX_LENGTH = 64


def canonical_json(obj: Any) -> str:
    """Render ``obj`` to its one canonical JSON string.

    Key-sorted and whitespace-stripped, so two mappings or sequences that differ
    only in rendering — key order, indentation — produce one string, and the
    hash taken over that string is the hash of the *value* rather than of
    whichever rendering happened to arrive.  This is the seam the "frozen"
    guarantee hangs on: the stored bytes and their hash are both derived from
    this one rendering, so a value and its re-rendering are one identity.  A
    value that is not JSON-serialisable is refused by name — a policy that
    cannot be canonicalised cannot be frozen, and a frozen reference to it would
    be a reference the nightly replay could not reconstruct.
    """
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise CanaryError(
            f"a canary reference must be JSON-canonicalisable so its bytes are "
            f"frozen and checkable, got a value that is not: {exc}"
        ) from exc


def content_hash(text: str) -> str:
    """The :func:`canonical_json` rendering's identity — ``sha256`` hex.

    The same spelling the determinism spine uses for every content hash: the
    digest of the canonical bytes, lowercased hex, ``64`` wide.  A policy's
    ``code_hash`` and a tree's ``tree_hash`` are both this function applied to
    their canonical bytes, so one function is the whole of "which bytes".  A
    caller comparing two references compares these; a caller storing one stores
    these; and a caller reading one back re-derives these and refuses a row
    whose stored hash names different bytes.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_hash(nodes: Mapping[str, tuple[Optional[str], int, str]]) -> str:
    """The identity of a tree as a *set* of nodes, in a stable order.

    ``nodes`` maps ``node_id`` to ``(parent_id, depth, canonical_payload)``.
    The hash is taken over the nodes sorted by ``node_id`` — a tree is its
    nodes, not the order a walk visits them — and over each node's id, depth,
    parent and canonical payload, so two trees holding the same nodes are one
    hash and two trees differing in one node are two.  A walk order is not part
    of the tree; the sorted rendering is.
    """
    rendered = "\n".join(
        f"{node_id}\x1f{depth}\x1f{parent_id or ''}\x1f{payload}"
        for node_id, (parent_id, depth, payload) in sorted(nodes.items())
    )
    return content_hash(rendered)


def _validated_hash(name: str, value: Any) -> str:
    """A content hash in canonical ``sha256`` hex — refused otherwise.

    The identity of a frozen value is load-bearing: the nightly replay compares
    the bytes it replays against this hash, so a hash that is not ``64`` lowercase
    hex would let a reference claim an identity it cannot hold.  Refused here, at
    construction, where the pair that carries it is the one named.
    """
    if not isinstance(value, str) or len(value) != _HASH_HEX_LENGTH:
        raise CanaryError(
            f"{name} must be a {_HASH_HEX_LENGTH}-character hex digest, got "
            f"{value!r}; it is the identity the nightly replay checks the frozen "
            "bytes against, and a hash of the wrong width names no bytes"
        )
    if value != value.lower() or any(c not in "0123456789abcdef" for c in value):
        raise CanaryError(
            f"{name} must be lowercase hex, got {value!r}; a hash is compared "
            "byte-for-byte against the frozen reference, and a hash rendered two "
            "ways would never match its own bytes"
        )
    return value


def _utc_now() -> datetime:
    """The current instant, timezone-aware UTC — the freeze instant.

    Second resolution with microseconds dropped rather than rounded, the same
    spelling :func:`ledger.record.utc_now` and :mod:`nulloracle.ksguard` use: the
    stamp orders freezes against one another, and dropping — not rounding — keeps
    it never *after* the instant observed.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass(frozen=True)
class CanaryPolicy:
    """A frozen canary policy — one version, one canonical rendering, one hash.

    Built by :meth:`freeze` from a policy mapping, or reconstructed by the store
    from a stored row.  Frozen and validated in :meth:`__post_init__` rather than
    only where it is built, because the read path reconstructs one from a stored
    row: a row whose stored ``code_hash`` names different bytes than the stored
    ``policy`` fails to reconstruct rather than loading as a plausible-looking
    reference — the same defence :func:`content_hash` provides for a stored
    p-value, and the same reason it exists: the stored policy is what the nightly
    replay replays, and a store that could hand back bytes disagreeing with their
    own hash would launder a tamper.
    """

    #: The policy's version — its name.  UNIQUE in the store: two policies may
    #: not answer to one version, or a replay could not say which bytes a
    #: version froze.
    version: str
    #: The canonical JSON rendering of the policy content — the frozen bytes.
    source: str
    #: ``sha256`` over :attr:`source` — the policy's identity.
    code_hash: str
    #: When the policy was frozen (the row's ``created_at``).
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise CanaryError(
                "a canary policy must carry a non-empty version: it is the name "
                "the store keys the frozen pair by and the nightly replay names, "
                "and a policy with no version is a reference nobody can point at"
            )
        if not isinstance(self.source, str) or not self.source.strip():
            raise CanaryError(
                "a canary policy must carry a non-empty canonical source: the "
                "frozen bytes the nightly replay replays, and a policy with none "
                "is a reference that froze nothing"
            )
        try:
            parsed = json.loads(self.source)
        except (TypeError, ValueError) as exc:
            raise CanaryError(
                f"a canary policy source must be canonical JSON, got bytes that "
                f"do not parse: {exc}"
            ) from exc
        if not isinstance(parsed, Mapping):
            raise CanaryError(
                f"a canary policy must be a JSON object, got a {type(parsed).__name__}; "
                "a policy is a mapping of parameters, and a non-object source is "
                "not a policy the replay path could run"
            )
        expected = content_hash(self.source)
        if self.code_hash != expected:
            raise CanaryError(
                f"a canary policy's code_hash {self.code_hash!r} does not name its "
                f"own source (which hashes to {expected!r}); the hash is the "
                "identity the nightly replay checks the frozen bytes against, and "
                "a hash that names different bytes is a reference that is no "
                "longer what was frozen — a tamper, or a version frozen twice to "
                "different bytes"
            )
        _validated_hash("code_hash", self.code_hash)
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise CanaryError(
                "a canary policy must carry a timezone-aware created_at: the freeze "
                "instant orders reference pairs against one another, and a naive "
                "stamp would raise far from the freeze that set it"
            )

    @property
    def policy(self) -> dict[str, Any]:
        """The frozen policy content, rebuilt as the mapping it came from.

        A property rather than a stored field: :attr:`source` is the frozen
        bytes and this is their rendering, and re-deriving is what keeps the two
        from ever being two copies of a policy that could disagree.
        """
        return json.loads(self.source)

    @classmethod
    def freeze(
        cls,
        version: str,
        policy: Mapping[str, Any],
        *,
        created_at: Optional[datetime] = None,
    ) -> "CanaryPolicy":
        """Freeze a policy mapping into a :class:`CanaryPolicy`.

        Canonicalises the mapping (:func:`canonical_json`) and takes its identity
        (:func:`content_hash`) before constructing, so the caller hands over a
        value and gets back the value *plus* the one canonical rendering and hash
        it is frozen to — the two can never be two copies that disagree.  A
        replay of a recorded run supplies its own ``created_at`` so the restored
        pair stamps the instant the original froze.
        """
        instant = _utc_now() if created_at is None else created_at
        return cls(
            version=version,
            source=canonical_json(policy),
            code_hash=content_hash(canonical_json(policy)),
            created_at=instant,
        )


@dataclass(frozen=True)
class CanaryTreeNode:
    """One frozen node of the canary tree.

    Built by :meth:`freeze` from a payload mapping, or reconstructed by the store
    from a stored row.  Frozen and validated in :meth:`__post_init__`: a stored
    node whose ``depth`` is negative, or whose payload hash does not name its
    bytes, fails to reconstruct rather than loading as a plausible-looking node —
    the same defence a :class:`CanaryPolicy` applies to its own hash, for the
    same reason.
    """

    #: The node's identity within the tree.  A parent reference names one of
    #: these; a dangling reference is refused by :class:`CanaryTree`.
    node_id: str
    #: The parent node's id, or ``None`` for a root.  Validated against the tree
    #: by :class:`CanaryTree`, not here — a node alone cannot know its siblings.
    parent_id: Optional[str]
    #: How deep the node sits in the tree, zero at a root.
    depth: int
    #: The canonical JSON rendering of the node's payload — the frozen bytes.
    payload: str

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise CanaryError(
                "a canary tree node must carry a non-empty node_id: it is the id a "
                "parent reference and the store's uniqueness key on, and a node with "
                "none cannot be addressed or joined"
            )
        if self.parent_id is not None and (
            not isinstance(self.parent_id, str) or not self.parent_id.strip()
        ):
            raise CanaryError(
                f"canary tree node {self.node_id!r} carries an empty parent_id: a "
                "parent reference is either absent (a root) or names a node, and an "
                "empty string is neither"
            )
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or self.depth < 0:
            raise CanaryError(
                f"canary tree node {self.node_id!r} carries a depth of {self.depth!r}: "
                "depth is a non-negative integer, zero at a root, and a negative one "
                "is a level no walk could reach"
            )
        if not isinstance(self.payload, str) or not self.payload.strip():
            raise CanaryError(
                f"canary tree node {self.node_id!r} carries no payload: the frozen "
                "bytes the nightly replay reads back, and a node with none froze "
                "nothing"
            )
        try:
            parsed = json.loads(self.payload)
        except (TypeError, ValueError) as exc:
            raise CanaryError(
                f"canary tree node {self.node_id!r} carries a payload that is not "
                f"canonical JSON: {exc}"
            ) from exc
        expected = content_hash(self.payload)
        # The node's payload hash is not stored separately (the tree hash covers
        # it), but validating it here keeps a node and its bytes bound the same
        # way a policy is — a node whose payload does not parse as it claims is
        # refused at the seam that reconstructs it.

    @property
    def content(self) -> dict[str, Any]:
        """The frozen payload, rebuilt as the mapping it came from."""
        return json.loads(self.payload)

    @classmethod
    def freeze(
        cls,
        node_id: str,
        payload: Mapping[str, Any],
        *,
        parent_id: Optional[str] = None,
        depth: int,
    ) -> "CanaryTreeNode":
        """Freeze a node's payload mapping into a :class:`CanaryTreeNode`.

        Canonicalises the payload before constructing, so the node carries the
        one rendering it is frozen to — the same move :meth:`CanaryPolicy.freeze`
        makes, for the same reason.
        """
        return cls(
            node_id=node_id,
            parent_id=parent_id,
            depth=depth,
            payload=canonical_json(payload),
        )


@dataclass(frozen=True)
class CanaryTree:
    """A frozen canary tree — a set of nodes in a stable order, one hash.

    Built from :class:`CanaryTreeNode` values, sorted by ``node_id`` in
    :meth:`__post_init__` before anything is hashed or stored — a tree is its
    nodes, not the order a walk visits them.  :attr:`tree_hash` is the tree's
    identity: :func:`tree_hash` over the sorted nodes, so two trees holding the
    same nodes are one hash and two differing in one node are two.
    """

    #: The nodes, sorted by ``node_id``.  Normalised in :meth:`__post_init__`.
    nodes: tuple[CanaryTreeNode, ...]
    #: The tree's identity — :func:`tree_hash` over the sorted nodes.  Optional
    #: in the constructor and always derived in :meth:`__post_init__` from the
    #: nodes, so a tree's hash is never trusted from input — it is the hash of
    #: exactly the nodes it holds, and a caller cannot hand one that disagrees.
    tree_hash: Optional[str] = None

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        if not nodes:
            raise CanaryError(
                "a canary tree must carry at least one node: the nightly replay "
                "replays a policy *over a tree*, and a tree with no nodes is a "
                "reference the replay could not run — vacuous, the one reading the "
                "nightly canary must never allow"
            )
        seen: set[str] = set()
        for node in nodes:
            if not isinstance(node, CanaryTreeNode):
                raise CanaryError(
                    f"a canary tree is built of CanaryTreeNode values, got {node!r}; "
                    "the tree hash is taken over node ids and payloads, and a bare "
                    "value carries neither"
                )
            if node.node_id in seen:
                raise CanaryError(
                    f"the canary tree node {node.node_id!r} appears twice: a node id "
                    "names one node, and two nodes wearing one id is a tree the "
                    "replay could not walk"
                )
            seen.add(node.node_id)
        nodes = tuple(sorted(nodes, key=lambda node: node.node_id))
        ids = {node.node_id for node in nodes}
        for node in nodes:
            if node.parent_id is not None and node.parent_id not in ids:
                raise CanaryError(
                    f"canary tree node {node.node_id!r} names a parent {node.parent_id!r} "
                    "that is not a node in the tree: a frozen tree with a dangling "
                    "edge is not a tree the replay path could walk, and the refusal "
                    "belongs at the moment the pair is frozen, where it names the "
                    "pair"
                )
        rendered = {
            node.node_id: (node.parent_id, node.depth, node.payload) for node in nodes
        }
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "tree_hash", tree_hash(rendered))

    @classmethod
    def freeze(cls, node_specs: Mapping[str, tuple[Optional[str], int, Mapping[str, Any]]]) -> "CanaryTree":
        """Freeze a mapping of ``node_id → (parent_id, depth, payload)`` into a tree.

        Builds each node through :meth:`CanaryTreeNode.freeze` — canonicalising
        each payload — then lets :meth:`__post_init__` sort, validate the parent
        references and take the tree hash, so the caller hands over raw specs and
        gets back a tree whose every node is already frozen and whose hash is the
        hash of exactly those bytes.
        """
        nodes = tuple(
            CanaryTreeNode.freeze(
                node_id, payload, parent_id=parent_id, depth=depth
            )
            for node_id, (parent_id, depth, payload) in node_specs.items()
        )
        return cls(nodes=nodes)


@dataclass(frozen=True)
class CanaryReferencePair:
    """The frozen determinism reference pair — a policy and the tree it replays over.

    The unit feature 141 persists: one :class:`CanaryPolicy` and one
    :class:`CanaryTree`, plus the metadata the store rows carry.  Frozen and
    validated in :meth:`__post_init__`, because the read path reconstructs one
    from stored rows and a pair whose policy or tree does not reconstruct is a
    row edited outside this package — refused rather than loaded as a
    plausible-looking reference.  What downstream trusts is the stored bytes and
    their hash, and a store that could hand back a pair disagreeing with its own
    rows would launder a tamper.
    """

    #: The frozen policy — ``π_canary``.
    policy: CanaryPolicy
    #: The frozen tree — ``T_canary``.
    tree: CanaryTree
    #: The recorded constant the nightly replay (feature 142) compares its score
    #: against.  ``None`` until the first replay writes it — a freshly frozen pair
    #: has not yet been replayed, so it has no constant yet, and feature 143's
    #: ``1e-12`` comparison must stay distinguishable from "not yet replayed".
    recorded_score: Optional[float]
    #: The store row's id, once persisted; ``None`` for a pair not yet frozen.
    id: Optional[str]
    #: Whether this pair is the deployment's active reference.  Exactly one pair
    #: is active at a time — the one the nightly canary replays.
    is_active: bool
    #: The freeze instant, mirrored from the policy row's ``created_at``.
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.policy, CanaryPolicy):
            raise CanaryError(
                f"a canary reference pair carries a CanaryPolicy, got {self.policy!r}; "
                "the pair is the policy and the tree together, and a pair without a "
                "policy froze only half of the reference"
            )
        if not isinstance(self.tree, CanaryTree):
            raise CanaryError(
                f"a canary reference pair carries a CanaryTree, got {self.tree!r}; the "
                "pair is the policy and the tree together, and a pair without a tree "
                "froze only half of the reference"
            )
        if self.recorded_score is not None:
            if isinstance(self.recorded_score, bool) or not isinstance(
                self.recorded_score, (int, float)
            ):
                raise CanaryError(
                    f"recorded_score must be a real number or None, got "
                    f"{self.recorded_score!r}; it is the constant the nightly replay "
                    "compares its score against, and a non-number is not a score a "
                    "comparison could reach"
                )
        if self.id is not None:
            try:
                str(uuid.UUID(self.id))
            except (TypeError, ValueError) as exc:
                raise CanaryError(
                    f"a persisted canary reference pair carries a UUID id, got "
                    f"{self.id!r}: {exc}"
                ) from exc

    @property
    def content_fingerprint(self) -> tuple[str, str]:
        """The pair's identity — ``(code_hash, tree_hash)``.

        The two hashes the nightly replay checks its replayed bytes against.  Two
        pairs with the same fingerprint froze the same policy and the same tree;
        comparing these is how a replay proves it is replaying the frozen pair and
        not a moved one — without carrying the bytes themselves, which for a tree
        are far larger than a hash line.
        """
        return (self.policy.code_hash, self.tree.tree_hash)

    def has_same_content_as(self, other: "CanaryReferencePair") -> bool:
        """Whether ``other`` froze the same policy and the same tree.

        Compares :attr:`content_fingerprint` — the two hashes — rather than the
        rendered bytes, so a freshly-built pair and the stored pair it came from
        compare equal however they were rendered, and a pair that differs in one
        policy parameter or one tree node does not.  This is the comparison the
        nightly replay (feature 142) makes against the frozen reference: the
        bytes it replays must carry the same fingerprint, or the determinism the
        canary guards has already broken.
        """
        return self.content_fingerprint == other.content_fingerprint
