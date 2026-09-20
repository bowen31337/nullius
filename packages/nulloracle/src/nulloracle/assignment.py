"""One node's null assignment: §7.1's sidecar schema as a value.

app_spec.xml, "Null Oracle & Planted Nulls", feature 109: *System persists
null assignments in an AES-GCM encrypted sidecar file readable by exactly
one service account.*  docs/nullius-tech-architecture.md §7.1 fixes both
the file and what is inside it::

    /z0/null/
      sidecar.enc          # AES-GCM, key in KMS/sops; readable by ONE service account
      schema: {node_id: {is_null: bool, perm_seed: int, block_days: int}}

This module is that schema — one node's entry, as a frozen value, validated
at construction and renderable to the canonical bytes the envelope seals.

**Why the schema has these four fields and no more.**  ``node_id`` is the
key, because a null assignment is a fact *about a node*: §7.1's map is
keyed by it, the tree store's ``node.id`` is a UUID, and §9.1's provenance
discipline means the assignment must join to the node it describes without
a translation step.  ``is_null`` is the bit itself — the one fact the
entire system is forbidden from writing anywhere else, and the reason the
file exists at all.  ``perm_seed`` and ``block_days`` are not decoration:
they are the parameters that make the null world *reproducible*.  Feature
115 fixes the mechanism — *"System block-permutes forward returns for a
null node using a stored permutation seed with a 20 day block length"* —
and the word doing the work there is **stored**.  A permutation drawn
fresh on every request would not be a world; it would be noise, and the
same campaign replayed would score differently against it, which §12's
determinism contract forbids outright.  So the seed that generated a null
node's permuted series is persisted *beside* the bit that says the node is
null, at the moment the assignment is made, and feature 115 reads it back
rather than drawing again.

**The bit is a genuine bool, and the refusal is the point.**  ``is_null``
is validated as ``isinstance(value, bool)`` and not as truthiness, so a
string ``"false"``, the integer ``0`` and the float ``0.0`` are all
refused rather than coerced.  That is not pedantry: the parameter that
decides whether a node reports a real target or a permuted one is the
single most consequential bit in the system, and it arrives from a YAML
document, a JSON body or a caller's keyword argument — three places where
"false" is a perfectly ordinary thing to write and means the exact
opposite of ``False``.  A coercion here would plant a null world where a
real one was intended (or the reverse) and nothing downstream would look
wrong.  The cost-model member refuses a non-finite float by name for the
same class of reason.

**Block length defaults to §7.1's 20 days.**  Feature 115 states the block
length as 20 days, and §7.2's ``block_permute(forward_returns,
seed=perm_seed, block=20d)`` spells it twice.  It is nevertheless a stored
*per-assignment* field rather than a module constant, because §7.4's
detectability guard is explicitly a knob: *"if ks_pvalue < 0.05: alert
(nulls may be detectable — investigate block length)"*.  The block length
is the parameter an operator investigates and changes, and an assignment
that recorded only "the block length we happen to use now" would become
unreproducible the first time it changed.  So the default is 20 and it is
*paid at the write* — once a node is assigned, its world's parameters are
fixed and replayable, not re-derived.

**The canonical spelling is the sealed bytes.**  :func:`canonical_assignments`
renders the whole map as JSON with sorted keys and compact separators, so
two sidecars written from the same assignments are the same bytes, and a
campaign replayed next year opens to exactly what was sealed.  That is the
same discipline :func:`cost_model.identity.canonical_cost_model` applies to
the fee schedule, and for the same reason: a hash or a ciphertext over
under-specified bytes names nothing an audit can check.  :func:`assignments_digest`
carries it one step further with a sha256 over those bytes — a value an
operator can compare across two sidecars *without the key*, which is what
makes "is this the same sidecar?" answerable by a process that is not
allowed to open it.

**What this module cannot do.**  It does not encrypt, decrypt, or touch a
file.  :mod:`nulloracle.envelope` is the AES-GCM half and
:mod:`nulloracle.sidecar` is the file half; this module is only the shape
of the thing being sealed, kept separate so the schema can be reasoned
about (and tested) without a key.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import SidecarError

__all__ = [
    "DEFAULT_BLOCK_DAYS",
    "NullAssignment",
    "assignments_digest",
    "canonical_assignments",
    "decode_assignments",
    "encode_assignments",
    "normalize_node_id",
]


#: §7.1's block length: the default a newly written assignment records.
#:
#: §7.2 spells the same number inline — ``block_permute(forward_returns,
#: seed=perm_seed, block=20d)`` — and feature 115 states it as *"a 20 day
#: block length"*.  Spelled once here so the default the writer applies and
#: the value the permutation reads cannot drift apart.
DEFAULT_BLOCK_DAYS = 20


def normalize_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    Accepts a :class:`uuid.UUID` or any text :func:`uuid.UUID` parses, and
    returns the lowercased hyphenated rendering.  Two assignments for the
    same node compare equal however the caller came by the identity — the
    same normalization (and the same reasoning) as
    :func:`ledger.record._validated_uuid`, because both columns join to the
    tree store's ``node.id UUID PRIMARY KEY`` and a mixed-case key would
    make §7.1's map look like it held two nodes.

    A malformed id is refused with :class:`~nulloracle.errors.SidecarError`
    rather than stored: an assignment whose key cannot be joined to a node
    is an assignment no scorer could ever consume.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise SidecarError(
        f"node_id {value!r} is not a UUID; a null assignment is keyed by the "
        "node it describes (docs/nullius-tech-architecture.md §7.1), so an id "
        "that cannot join the tree store's node.id names no node this "
        "sidecar could hold"
    )


def _validated_is_null(value: Any) -> bool:
    """Refuse anything but a genuine bool for the null bit.

    See the module docstring: ``"false"`` is a truthy string, ``0`` is a
    falsey int, and both would plant the wrong world silently.  Only the
    two objects the language defines as booleans are accepted.
    """
    if not isinstance(value, bool):
        raise SidecarError(
            f"is_null must be a genuine bool, got {type(value).__name__} "
            f"({value!r}); this one bit decides whether a node reports a real "
            "target or a block-permuted one (§7.2), so a value that merely "
            "looks true or false — the string 'false', the integer 0 — is "
            "refused rather than coerced"
        )
    return value


def _validated_perm_seed(value: Any) -> int:
    """Refuse a permutation seed that is not a non-negative integer.

    A seed is what makes a null node's series reproducible (feature 115),
    so it must be storable as one integer with one meaning.  ``bool`` is
    excluded deliberately even though Python's ``bool`` is an ``int``
    subclass — ``True`` is not a seed anyone meant to write.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SidecarError(
            f"perm_seed must be a non-negative integer, got "
            f"{type(value).__name__} ({value!r}); feature 115 reproduces a "
            "null node's block permutation from this stored seed, so a seed "
            "that is not a non-negative integer is a world no replay could "
            "rebuild"
        )
    return value


def _validated_block_days(value: Any) -> int:
    """Refuse a block length that is not a positive integer.

    §7.1's default is :data:`DEFAULT_BLOCK_DAYS` (20), and §7.4's
    detectability guard treats the block length as the knob an operator
    turns when nulls look detectable.  Zero is refused rather than treated
    as "no permutation": a zero-length block is not a permutation of
    anything, so an assignment carrying one would silently be a *real* node
    wearing a null's parameters.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SidecarError(
            f"block_days must be a positive integer, got "
            f"{type(value).__name__} ({value!r}); a block permutation of zero "
            "days permutes nothing, so an assignment carrying one would be a "
            "real node wearing a null's parameters"
        )
    return value


@dataclass(frozen=True)
class NullAssignment:
    """One node's entry in §7.1's sidecar schema.

    ``node_id`` is canonical UUID text, ``is_null`` a genuine bool, and
    ``perm_seed``/``block_days`` the parameters feature 115's block
    permutation is reproduced from.  Frozen, so an assignment that has been
    sealed can never be edited in place by a caller who kept a reference —
    the sidecar is a record of what was decided, and a mutable handle to it
    would be a mutable handle to a past decision.

    Validated in :meth:`__post_init__` rather than only at construction
    through a factory, because ``dataclasses.replace`` and unpickling both
    rebuild instances past a factory's nose; validating on the object
    itself means every path that produces one produces a coherent one.
    """

    node_id: str
    is_null: bool
    perm_seed: int
    block_days: int = DEFAULT_BLOCK_DAYS

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the
        # canonicalization below is normalization, not mutation of the
        # caller's value, and it is the only write this object ever takes.
        object.__setattr__(self, "node_id", normalize_node_id(self.node_id))
        object.__setattr__(self, "is_null", _validated_is_null(self.is_null))
        object.__setattr__(self, "perm_seed", _validated_perm_seed(self.perm_seed))
        object.__setattr__(self, "block_days", _validated_block_days(self.block_days))

    def to_payload(self) -> dict[str, Any]:
        """This assignment as the plain mapping §7.1's schema spells.

        The field names are the schema's own — ``is_null``, ``perm_seed``,
        ``block_days`` — and deliberately not shortened in the sealed bytes:
        the sidecar is read by a second process, an operator's audit script
        and whatever tooling §7.4's detectability guard grows, and a JSON
        document whose keys are a private shorthand is a document only this
        package can read.
        """
        return {
            "is_null": self.is_null,
            "perm_seed": self.perm_seed,
            "block_days": self.block_days,
        }

    @classmethod
    def from_payload(cls, node_id: Any, payload: Any) -> "NullAssignment":
        """Rebuild an assignment from the sealed mapping, refusing a bad one.

        The read-side twin of :meth:`to_payload`, and the reason a
        decrypted-but-corrupt sidecar surfaces as a named
        :class:`~nulloracle.errors.SidecarError` rather than a
        ``KeyError``: a sidecar whose entry is missing a field, or whose
        field holds a string where a bool belongs, is refused with the
        node and the field named.  Authentication (feature 109's AES-GCM)
        proves the bytes are the ones that were sealed; it does not prove
        they are a schema this member understands, and an older or
        hand-edited file must say so rather than half-load.
        """
        if not isinstance(payload, Mapping):
            raise SidecarError(
                f"the sidecar's entry for node {node_id!r} is a "
                f"{type(payload).__name__}, not the mapping §7.1's schema "
                "spells ({is_null, perm_seed, block_days})"
            )
        missing = [
            field
            for field in ("is_null", "perm_seed", "block_days")
            if field not in payload
        ]
        if missing:
            raise SidecarError(
                f"the sidecar's entry for node {node_id!r} is missing "
                f"{', '.join(repr(name) for name in sorted(missing))}; §7.1's "
                "schema carries is_null, perm_seed and block_days together, "
                "because a bit without its permutation parameters is a null "
                "world no replay could rebuild"
            )
        return cls(
            node_id=node_id,
            is_null=payload["is_null"],
            perm_seed=payload["perm_seed"],
            block_days=payload["block_days"],
        )


def _is_assignment(value: Any) -> bool:
    """Whether ``value`` is a :class:`NullAssignment`, structurally.

    Duck-checked rather than ``isinstance``-guarded, deliberately: the
    factory's scan imports this member under a synthetic module name
    (``app.module_loader._import_package``), so a package this suite also
    imported canonically as ``nulloracle`` exists in the process twice with
    two distinct class objects.  An ``isinstance`` here would refuse the very
    assignments the *scanned* sidecar component hands out — a caller that
    reads a node back through the composed component and writes it again
    would be told its own values are not assignments.  The ledger member's
    debit endpoint draws the same distinction for the same reason.

    The check is the four fields of §7.1's schema plus the rendering method
    the canonical spelling calls, which is the whole contract this module
    needs of a value: that it can name its node, state its bit, carry its
    permutation parameters, and render itself.  An arbitrary object that
    happens to satisfy that is, for the purposes of sealing, an assignment.
    """
    return all(
        hasattr(value, field)
        for field in ("node_id", "is_null", "perm_seed", "block_days", "to_payload")
    )


def _coerced_map(
    assignments: Mapping[Any, NullAssignment] | Iterable[NullAssignment],
) -> dict[str, NullAssignment]:
    """Return ``assignments`` as a canonical ``{node_id: assignment}`` map.

    Accepts either the mapping §7.1's schema names or a plain iterable of
    values, because the two are the same set written two ways and a caller
    that has a list in hand should not have to build a dict first.  A
    mapping whose key disagrees with the assignment's own ``node_id`` is
    refused rather than silently reconciled: the key is the schema's
    identity, so a map that says a node is keyed by one id while the value
    says another is a sidecar no reader could resolve a node in.
    """
    items = assignments.items() if isinstance(assignments, Mapping) else (
        (assignment.node_id, assignment) for assignment in assignments
    )
    by_node: dict[str, NullAssignment] = {}
    for key, assignment in items:
        if not _is_assignment(assignment):
            raise SidecarError(
                f"the assignment keyed by {key!r} is a "
                f"{type(assignment).__name__}, not a NullAssignment; the "
                "sidecar holds §7.1's schema and nothing else"
            )
        node_id = normalize_node_id(key)
        if node_id != assignment.node_id:
            raise SidecarError(
                f"the sidecar's map keys node {node_id} but its value names "
                f"node {assignment.node_id}; a sidecar whose key and value "
                "disagree resolves no node at all"
            )
        by_node[node_id] = assignment
    return by_node


def canonical_assignments(
    assignments: Mapping[Any, NullAssignment] | Iterable[NullAssignment],
) -> str:
    """The canonical JSON spelling of a whole sidecar, for the sealed bytes.

    Key-sorted and compact, with each node's fields in §7.1's order, so two
    sidecars written from the same assignments are byte-identical and a
    replayed campaign opens to exactly what was sealed.  The result is what
    :func:`encode_assignments` hands the envelope and what
    :func:`assignments_digest` hashes.

    Exposed for the same reason
    :func:`cost_model.identity.canonical_cost_model` is: a ciphertext whose
    plaintext cannot be printed is a ciphertext nobody can debug, and an
    operator asking *why do these two sidecars differ* needs to see the two
    spellings.
    """
    by_node = _coerced_map(assignments)
    rendered = {
        node_id: by_node[node_id].to_payload() for node_id in sorted(by_node)
    }
    return json.dumps(rendered, sort_keys=True, separators=(",", ":"))


def encode_assignments(
    assignments: Mapping[Any, NullAssignment] | Iterable[NullAssignment],
) -> bytes:
    """The canonical plaintext an envelope seals: UTF-8 canonical JSON.

    A thin spelling of :func:`canonical_assignments` that does the encoding
    once, at the seam where it matters — the envelope is handed bytes, and
    the claim "these are the sidecar's bytes" should be stated by one
    function rather than repeated at every call site.
    """
    return canonical_assignments(assignments).encode("utf-8")


def decode_assignments(payload: bytes | str) -> dict[str, NullAssignment]:
    """Open an envelope's plaintext back into §7.1's assignment map.

    The read-side twin of :func:`encode_assignments`: parses the JSON,
    validates every entry through :meth:`NullAssignment.from_payload`, and
    returns the map keyed by canonical node id.  A payload that is not JSON
    at all, or that is JSON but not an object, is refused with
    :class:`~nulloracle.errors.SidecarError` — deliberately *not* a
    :class:`~nulloracle.errors.SidecarDecryptionError`, because
    authentication succeeded and the failure is that the authenticated
    bytes are not a sidecar.  Conflating the two would tell an operator to
    investigate the key when the problem is the file's contents.
    """
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SidecarError(
                "the sidecar's authenticated bytes are not UTF-8; §7.1's "
                "schema is JSON, so this file is not one this member wrote"
            ) from exc
    else:
        text = payload
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise SidecarError(
            "the sidecar's authenticated bytes are not JSON; §7.1's schema is "
            "a JSON object keyed by node_id, so this file is not one this "
            "member wrote"
        ) from exc
    if not isinstance(raw, Mapping):
        raise SidecarError(
            f"the sidecar's authenticated bytes are a JSON "
            f"{type(raw).__name__}, not the object §7.1's schema spells "
            "({node_id: {is_null, perm_seed, block_days}})"
        )
    return {
        normalize_node_id(node_id): NullAssignment.from_payload(node_id, entry)
        for node_id, entry in sorted(raw.items())
    }


def assignments_digest(
    assignments: Mapping[Any, NullAssignment] | Iterable[NullAssignment],
) -> str:
    """A sha256 over the canonical sidecar bytes, checkable without the key.

    Returns 64 lowercase hex characters — the spelling the spec's
    ``*_hash CHAR(64)`` columns use.  Its purpose is narrow and worth
    stating: it lets a process that is **not** allowed to open the sidecar
    answer *"is this the same sidecar?"* — a deployment check, an audit
    comparing a backup against the live file, a test asserting that a
    re-seal of the same assignments is the same world.  It is emphatically
    **not** a substitute for the AES-GCM tag: a digest detects a *different*
    sidecar, and only the tag detects a *forged* one.  Anyone can compute a
    digest over bytes they chose; nobody without the key can produce a tag
    this member will accept.
    """
    return hashlib.sha256(encode_assignments(assignments)).hexdigest()
