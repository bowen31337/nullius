"""The per-campaign root provider rotation — feature 197's record and decision.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 197: *System
persists a per-campaign root provider rotation, so different model families
propose structurally different mechanisms.*  docs/nullius-tech-architecture.md
§14.1 states the law this sentence implements, in the paragraph under the role
table:

    **Rotating providers at roots is the cheapest mitigation available** for
    the convergence failure mode.  Different model families carry different
    priors and propose structurally different mechanisms, at zero incremental
    token cost, and it hedges outages.

and §14.2's roots row states the instruction the rotation carries out —
``claude-opus-5``, ``gpt-5.6-sol``, ``gemini-3.1-pro``, *"Rotate all three.
Different families, different priors, different mechanisms proposed."*

The other half of the sentence is feature 196's
-------------------------------------------------------------------

This feature is one of a pair, and :mod:`providers._root` draws the seam from
its own side in as many words: *"It does not choose the rotation.  Which of the
declared providers serves this root call is feature 197's question … 196
persists* **what served** *, 197 persists* **what was assigned** *, and a store
that did both would be deciding an assignment on the way to writing it down."*
So this module is the other half, and the two facts are kept apart at every
level:

* **196's subject is one call, after it was placed.**  Its
  :class:`~providers.RootProviderRotation` records the provider read off feature
  192's completion against the node that call authored, in
  :data:`~providers.ROOT_SERVING_PROVIDER_TABLE`.
* **197's subject is one campaign, before and between its calls.**  This
  module's :class:`RootRotation` computes which declared family each root is
  assigned to, persists that assignment in its own table, and *then* — through
  :meth:`RootRotation.record_root_provider` — asks 196's gate to write the
  provenance row for the call that carried the assignment out.

There is deliberately **no second provenance column here**.  The row that says
which family served a root is 196's, written by 196's gate, with 196's
checking; a store that wrote its own would be a second spelling of a fact with
one owner.  What this feature adds is the decision 196's gate cannot make — the
gate takes the serving provider as an argument, because *"which of the declared
providers serves this root call"* is not its question — and the per-campaign
record that decision belongs to.

Feature 202's module supplies the third precedent that fixes the shape: its
store persists its **premise** (the pricing card the window was chosen against)
beside its decision, *"so a decision can be audited against the card that was
current"*.  196's docstring declined to copy the tier onto its own rows for a
specific reason — *"the tier is* **feature 197's per-campaign record** *, and a
copy of it on every root row would be a second spelling of 197's fact, written
by a different feature, kept in sync by nobody"* — and this table is that
record.  So the premise lands here: every row carries the declared member set it
was assigned under, and the campaign's rotation is readable row by row, with the
one drift check (D5 below) made against those already-stored rows.

The decision: one family per root, a pure function of the root's identity
-------------------------------------------------------------------------

§14.1 asks that a campaign's roots be *spread* across the declared families, and
the property that makes a spread meaningful is that **each root's family is
decided by the root** rather than by the order the loop happened to visit it in.
:func:`rotation_index` is therefore a hash of the two ids the root already has:

    index = H(campaign_id ‖ node_id) mod len(tier)

Three consequences, each of which is the reason the alternative was rejected:

* **Exactly one family per root, and the same one on every path.**  A retry, a
  resumed campaign, a re-derivation by an auditor and a second process holding
  the same tree all compute the same index, so the rotation is a fact about the
  campaign rather than about a process's history — the same stance
  :class:`providers.RootProviderRotation` states when it refuses to memoize
  *which family proposed this node?*.
* **Stable under reordering.**  Positional round-robin (`i mod n` over the roots
  in expansion order) would make the assignment a property of an enumeration:
  two runs that place the same roots in a different order would write different
  families for the same node, the tree would stop being reproducible, and a
  re-derived audit would disagree with the stored rows for a reason no operator
  could see.
* **Family-invariant.**  The arithmetic reads two ids and the *size* of the
  declared set; the families' names enter only through the canonical member
  order :class:`providers.FrontierTier` imposes, and
  :func:`rotation_digest` is blind to them altogether (D6).

What the hash deliberately does **not** promise is a count.  §14.1's goal is
that a campaign's roots *span* families; a hash draws a multinomial over the
slots, not a 1:1 allocation, so a campaign of three roots can draw one family
twice.  That is a stated limit rather than an oversight.  The workspace reaches
for exact allocation where a **count** has to be right — feature 236's
largest-remainder allocator over :class:`fractions.Fraction`, in the discovery
member, for the depth budget — and this feature's fact is not a count: it is one
root's family.  The realized diversity is what feature 215's ``tree_diversity``
measures, per authoring model, and this module announces no figure; a rotation
that guaranteed a count would be *measuring* the thing §14.1 asks to be
*persisted and then measured*.

The persistence: a member-owned table, keyed by (campaign, root)
-----------------------------------------------------------------

The rows land in ``root_provider_rotation``, one row per ``(campaign_id,
node_id)``, created lazily by the store's first :meth:`RootRotation.assign`
(``CREATE TABLE IF NOT EXISTS``) — the ``bootstrap_world`` (feature 188),
``depth_run_window`` (202), ``depth_cache_rate`` (200) and
``root_serving_provider`` (196) precedent: a member-owned table for a
member-owned fact, and no edit to the shared migration chain.  The campaign id
is the key's left half, so *one campaign's rotation* is one indexed read and the
row-set **is** the rotation.  The store is append-only per `(campaign, root)`,
which is where the idempotence story lives: the identical assignment answers the
stored row (``recorded=False``, the original ``assigned_at``, which a retry does
not move), and a *different* family against the same root is
:class:`~providers.RotationConflictError`, naming both.

Two tables beside it are **probed, never created**.  ``node`` is feature 97's
(``migrations/versions/0118_node_table.py``) and is read here through feature
196's gate, not directly; ``root_serving_provider`` is feature 196's and is this
feature's own store's neighbour — this module *writes* it, through 196's
:class:`~providers.RootProviderRotation`, and never creates it or reads it
behind the store's back.  A member that composed another feature's gate is
allowed to call it; it is not allowed to write its table.

The refusals, and whose they are
--------------------------------

Three are this module's, and every one of them is about the **assignment**:

* :class:`~providers.RootRotationError` — a malformed description (an id that is
  not a UUID, a tier that is not a tier, a blank member name), or a campaign
  whose stored rows carry a different declared set than the one being declared
  now.  The base, on the ground the module docstring of
  :mod:`providers._rotation_errors` states.
* :class:`~providers.UnassignedRootProviderError` — a serving family the
  campaign's rotation does not cover for that root, raised **before** any row is
  written.  This is the gate that keeps the sentence's purpose clause honest.
* :class:`~providers.RotationConflictError` — one root assigned two families.

And the rest are **feature 196's, left to propagate unwrapped**: a node the tree
does not hold, a call below the root tier, a declaration the tree contradicts, a
serving family the declared set does not name, a provenance row that already
names another family.  Each of those already names the fact precisely — the
node, the depth, the tree, the tier — and re-wrapping them in this feature's
vocabulary would put a second, vaguer sentence in front of the one an operator
needs.  The suite pins the propagation rather than a translation.

Stdlib-only, like the rest of this tree: this module hashes two ids, holds a
declared set of named families, and writes rows.  Which provider actually
answered is feature 192's completion, read by the caller that placed the call;
which one served a root is feature 196's row.

This module's name is ``_rotation`` and its component is
``root-rotation`` in deliberate contrast to 196's ``root-serving-provider``:
feature 196 named its own component with this distinction in mind — *"The name
is* root-serving-provider *rather than* root-rotation *or* root-calls *because
that is the fact: the provider that served a root call, not the set of providers
a campaign may rotate across (feature 197's ``root-rotation``, a different
component under the same category).  A reader scanning the composed
application's keys should be able to tell which of the three it is looking at
without opening a docstring."*  This is that third name.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ._root import (
    ROOT_TIER_MAX_DEPTH,
    FrontierProvider,
    FrontierTier,
    RootCall,
    RootCallProvider,
    RootProviderRotation,
    _member_from_parts,
    _tier_from_parts,
)
from ._root_errors import RootProviderError
from ._rotation_errors import (
    RootRotationError,
    RotationConflictError,
    UnassignedRootProviderError,
)

__all__ = [
    "ASSIGNED_AT_COLUMN",
    "DATABASE_URL_ENV",
    "DECLARED_PROVIDERS_COLUMN",
    "NODE_ID_COLUMN",
    "ROOT_PROVIDER_ROTATION_TABLE",
    "ROTATION_DIGEST_COLUMN",
    "RootAssignment",
    "RootRotation",
    "assign_root_provider",
    "rotation_digest",
    "rotation_index",
]

#: The environment variable naming the relational store — the one spelling every
#: store in this workspace already uses, restated here (not imported from
#: :mod:`providers._root`) so this store states its own contract, the discipline
#: every module in this member follows even where a sibling declares the same
#: name.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the assigned rotation lands in — **this member's own**, created
#: lazily by the store's first :meth:`RootRotation.assign` and by nobody else,
#: on the ``bootstrap_world`` / ``depth_run_window`` / ``depth_cache_rate`` /
#: ``root_serving_provider`` precedent.  Named for the **rotation** rather than
#: for the campaign, so a reader looking for *what was this campaign's root
#: rotation, and by which feature* does not have to know which of ``campaign``'s
#: columns are whose — the reason feature 214 names its own table
#: ``campaign_discrimination``.
ROOT_PROVIDER_ROTATION_TABLE = "root_provider_rotation"

#: The campaign the rotation belongs to — feature 104's ``campaign.id``, the
#: value every tree query in the system is already scoped by.  **The left half
#: of this table's key**, which is what makes *one campaign's rotation* a single
#: indexed read rather than a scan of every campaign's rows.
CAMPAIGN_ID_COLUMN = "campaign_id"

#: The root the assignment is about — feature 97's ``node.id``.  One root call
#: is one node, so ``(campaign_id, node_id)`` is the assignment's identity and
#: the whole idempotence story hangs off it.
#:
#: Spelled here rather than imported from :mod:`providers._root` for the reason
#: every store in this member restates its column names: each store owns its own
#: spellings, and a shared constant would be one module's private vocabulary
#: leaking into another's column list.
NODE_ID_COLUMN = "node_id"

#: The family the rotation assigned this root — the fact this feature exists to
#: record.  It is the **assigned** family and not the serving one: the serving
#: family is feature 196's column, written by 196's gate from feature 192's
#: completion, and this row is the decision that gate is handed.
PROVIDER_COLUMN = "provider"

#: The model of that family's line the assignment names — carried beside the
#: provider rather than in place of it, exactly as feature 196 carries it: a
#: ``FrontierProvider`` is a pair, the assignment names a full member, and a row
#: that carried only the provider could not be compared with the tier it was
#: drawn from.
MODEL_COLUMN = "model"

#: The declared member set the assignment was drawn from, as canonical JSON —
#: this feature's **premise**, persisted on every row for the reason feature
#: 202's store persists its card: *"so a decision can be audited against the
#: card that was current"*.  Feature 196's docstring declined to copy the tier
#: onto *its* rows because the tier is this feature's per-campaign record; this
#: is that record, and carrying the premise here is what makes the one drift
#: check (does a later assignment for this campaign declare a different set?)
#: a comparison against rows this feature already wrote rather than a second
#: table nobody keeps in sync.
DECLARED_PROVIDERS_COLUMN = "declared_providers"

#: The rotation as one identifier: :func:`rotation_digest`'s sha256 hex over the
#: campaign id and the declared set's canonical text.  Carried on every row so
#: the campaign's rotation has **one name** — the value feature 214's
#: ``campaign_discrimination`` is keyed by, where *"two campaigns per candidate
#: model"* means a model is pinned to a campaign by reproducing the rotation and
#: a reader can tell *the rotation was the same* from *the rotation differed*
#: without re-deriving the arithmetic.
ROTATION_DIGEST_COLUMN = "rotation_digest"

#: The depth feature 97's tree places the assigned root at, re-derived here by
#: feature 196's probe and carried on the row.  It is the **third** tree fact
#: :class:`providers.RootCall` is made of, and it is stored rather than assumed
#: for the reason every column here is: the assignment is read back by callers
#: that do not hold the tree — feature 196's
#: :meth:`~providers.RootProviderRotation.record` takes a call, and a bridge
#: that rebuilt one from two ids and a constant depth would be *asserting* a
#: depth the tree owns.  The constant is only the fallback for a row written
#: before this column existed; the writer always stores what the probe answered,
#: so a root the tree places at depth 1 is recorded as depth 1 and read back as
#: depth 1.
#:
#: (The probe refuses a node below :data:`providers.ROOT_TIER_MAX_DEPTH` before
#: any row is written, so the stored value is always a root depth — the column
#: cannot hold a depth call's node, and :class:`RootAssignment` re-states that
#: law on construction the way :class:`providers.RootCallProvider` does.)
DEPTH_COLUMN = "depth"

#: The instant the assignment was written — writer-stamped, no engine
#: ``DEFAULT`` (a caller-stamped column never meets SQLite's ``DEFAULT``
#: grammar, so there is no dialect split to carry).
ASSIGNED_AT_COLUMN = "assigned_at"

#: The parts a declared tier is recognised by: the members it rotates across.
#: Feature 196's own tuple, spelled again here for the reason this module
#: restates every name it reads — a private constant of a sibling module is not
#: a promise, and the recognition is the same act whether the two modules share
#: the spelling or not.  It is asserted equal to ``_root._TIER_PARTS`` by the
#: suite, which is where two spellings that must not drift are held together.
_TIER_PARTS: tuple[str, ...] = ("providers",)

#: The parts a root call is recognised by — feature 196's three tree facts.
#: Restated for the same reason as :data:`_TIER_PARTS`, and pinned the same way.
_CALL_PARTS: tuple[str, ...] = ("node_id", "campaign_id", "depth")

#: The read-only probe that answers *does this database hold this table?* —
#: ``sqlite_master`` is read (never the rows), which makes the check safe on a
#: database this process has no business writing to; the idiom every store in
#: this member uses, and the reason :meth:`RootRotation.get` on a store that has
#: never assigned answers ``None`` instead of bringing a schema into being.
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"

#: The member-owned table, in one idempotent statement.  Every column is
#: ``NOT NULL`` — an assignment is written whole or not at all, and a row with a
#: root but no family, or a family but no premise, is half a decision no auditor
#: could act on.  The two key columns carry ``NOT NULL`` explicitly beside the
#: composite ``PRIMARY KEY`` for the reason ``0111``'s docstring spells: SQLite
#: accepts NULL in a key column, and a NULL-keyed row would split one root's
#: assignment from the campaign it belongs to — and would be, unlike a complete
#: row, carveable out of the rotation by an ``IS NOT NULL`` a reader never
#: intended to write.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {ROOT_PROVIDER_ROTATION_TABLE} (
    {CAMPAIGN_ID_COLUMN}          TEXT NOT NULL,
    {NODE_ID_COLUMN}              TEXT NOT NULL,
    {PROVIDER_COLUMN}             TEXT NOT NULL,
    {MODEL_COLUMN}                TEXT NOT NULL,
    {DEPTH_COLUMN}                INTEGER NOT NULL,
    {DECLARED_PROVIDERS_COLUMN}   TEXT NOT NULL,
    {ROTATION_DIGEST_COLUMN}      TEXT NOT NULL,
    {ASSIGNED_AT_COLUMN}          TEXT NOT NULL,
    PRIMARY KEY ({CAMPAIGN_ID_COLUMN}, {NODE_ID_COLUMN})
)
"""

#: The separator between the two ids fed to the hash, and between the campaign
#: id and the set text fed to the digest.  A unit separator (``\x1f``) rather
#: than the ``:`` the arrangement arithmetic of :mod:`providers._depth` uses,
#: because this input is raw **UUID text** whose own spelling already contains
#: hyphens: a ``-`` or ``:`` join would let two different pairs of ids spell one
#: pre-image, and a collision in an assignment function is two roots silently
#: sharing a family for a reason nobody could see.
_SEPARATOR = "\x1f"


# ── The decision ──────────────────────────────────────────────────────────────


def rotation_index(campaign_id: Any, node_id: Any, tier: object) -> int:
    """Which declared family a campaign's root is assigned — the rotation's index.

    The whole of the decision, as a pure function of the two ids and the
    **size** of the declared set::

        index = H(campaign_id ‖ node_id) mod len(tier)

    over ``sha256`` of the two canonical ids joined by
    :data:`_SEPARATOR`, reduced modulo the number of declared members.  §14.1
    asks that a campaign's roots be *spread* across the declared families, and
    the property that makes the spread meaningful is that each root's family is
    decided **by the root** rather than by the order the loop happened to visit
    it in — see the module docstring for the three consequences, and for what
    this deliberately does not promise (a count).

    The two ids are canonicalized through :class:`uuid.UUID` first, so a
    mixed-case spelling of one campaign's root is not two different families —
    the discipline every store in this member applies to the keys it joins by,
    applied here to the keys it *hashes*, where a drift would be invisible: the
    id would still resolve, and the assignment would still be stable, but it
    would be stable about a different value than the row it keys.

    The tier is recognised **by its parts** and re-made from
    :class:`providers.FrontierTier`, so a tier built from the workspace's other
    copy of this member assigns through this module's arithmetic — the
    double-import remedy every seam in this package makes.  A bare string or a
    mapping is refused by the tier's own collection guard; an empty tier cannot
    be constructed at all (its constructor refuses it), so the modulo here is
    never a division by zero.

    ``sha256`` rather than :func:`hash`: the builtin is salted per process
    (``PYTHONHASHSEED``), so an assignment derived from it would differ between
    two processes holding the same tree — which is precisely the property this
    function exists to have.
    """
    campaign = _validated_uuid(campaign_id, "campaign_id")
    node = _validated_uuid(node_id, "node_id")
    declared = _tier_from_parts(tier)
    pre_image = f"{campaign}{_SEPARATOR}{node}".encode()
    return int.from_bytes(hashlib.sha256(pre_image).digest(), "big") % len(
        declared.providers
    )


def rotation_digest(campaign_id: Any, tier: object) -> str:
    """The campaign's rotation as one identifier — sha256 hex of premise and scope.

    ``sha256(campaign_id ‖ tier.text())``, hex-encoded, over the campaign's
    canonical UUID text and the tier's canonical spelling
    (:meth:`providers.FrontierTier.text`, which construction already sorted).
    It answers *is this the same rotation?* as a string comparison, and it is
    carried on every row so the campaign's rotation has one name.

    **It is deliberately blind to the family names.**  The arithmetic of
    :func:`rotation_index` reads two ids and the size of the set; the names
    enter only through the *order* they are sorted into, and a rotation whose
    declared set differs in what a family is called is a different rotation only
    because the order changed — which the digest reflects.  There is no marker
    distinguishing one family from another anywhere in this module, because the
    assignment function has none: a deployment that swapped the family a slot
    holds would keep every root's index and change every root's family, which is
    a *different* rotation under the same arithmetic.

    The campaign is part of the pre-image because the digest names a
    **campaign's** rotation: two campaigns declared identically are not one
    rotation, they are two campaigns that happened to declare the same set, and
    a digest that could not tell them apart would key feature 214's
    per-campaign figure to the wrong campaign.
    """
    campaign = _validated_uuid(campaign_id, "campaign_id")
    declared = _tier_from_parts(tier)
    pre_image = f"{campaign}{_SEPARATOR}{declared.text()}".encode()
    return hashlib.sha256(pre_image).hexdigest()


# ── The answer ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RootAssignment:
    """One root's assigned family, and the row it was written to.

    The row's facts as one value: the ``campaign_id`` the rotation belongs to
    and the ``node_id`` of the root it assigned (together, the key), the
    ``provider`` and ``model`` of the assigned family, the ``declared`` set the
    assignment was drawn from, the ``digest`` of the campaign's rotation, the
    ``assigned_at`` instant the row was written, and ``recorded`` — this call's
    answer state, the same field :class:`providers.RootCallProvider`,
    :class:`providers.MeasuredCacheRate` and :class:`providers.ScheduledRun`
    carry: ``True`` when the call that returned this record wrote the row,
    ``False`` when it answered a row already there (an idempotent retry, or any
    read from :meth:`RootRotation.get`, which never writes).

    The ``declared`` set is carried **and** re-verified on construction: it is
    the premise this feature persists, and the store refuses a row whose
    recorded digest is not the digest of *that* pair — so a record cannot be
    read back as the premise of a rotation it does not describe.

    :attr:`assigned_provider` is derived, never stored: the same two names as a
    :class:`providers.FrontierProvider`, built fresh on each read, so a caller
    can offer the assigned member to a tier's membership check or hand it to
    feature 196's gate without re-assembling it — the
    :attr:`providers.RootCallProvider.serving_provider` move, for the same
    reason and now across the seam between the two features.

    Frozen, so a record that has been read back cannot be edited into a
    different assignment by a caller who kept a reference.
    """

    campaign_id: str
    node_id: str
    provider: str
    model: str
    depth: int
    declared: FrontierTier
    digest: str
    assigned_at: datetime
    recorded: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _validated_uuid(self.campaign_id, "campaign_id")
        )
        object.__setattr__(
            self, "node_id", _validated_uuid(self.node_id, "node_id")
        )
        object.__setattr__(
            self, "provider", _require_name(self.provider, "provider")
        )
        object.__setattr__(self, "model", _require_name(self.model, "model"))
        object.__setattr__(
            self, "depth", _require_root_depth(self.depth, self.node_id)
        )
        object.__setattr__(self, "declared", _tier_from_parts(self.declared))
        object.__setattr__(
            self,
            "digest",
            _require_digest(self.digest),
        )
        object.__setattr__(
            self,
            "assigned_at",
            _require_instant(self.assigned_at, "an assigned instant"),
        )
        object.__setattr__(self, "recorded", _require_recorded(self.recorded))
        # The premise and the digest are one fact stated twice, so they are
        # checked against each other rather than trusted in parallel: a record
        # whose digest is not the digest of the set beside it describes a
        # rotation it does not carry, which is the state this feature persists
        # the premise to make impossible.
        expected = rotation_digest(self.campaign_id, self.declared)
        if self.digest != expected:
            raise RootRotationError(
                f"the rotation row for node {self.node_id!r} in campaign "
                f"{self.campaign_id!r} carries digest {self.digest!r}, which is "
                f"not the digest of the declared set beside it "
                f"({expected!r} for {self.declared.text()!r}). The digest names "
                "the campaign's rotation and the declared set is its premise — "
                "two spellings of one fact — so a row where they disagree "
                "describes a rotation it does not carry, and feature 214's "
                "per-campaign figure keyed by that digest would be a figure "
                "about a rotation this row does not state."
            )

    @property
    def assigned_provider(self) -> FrontierProvider:
        """The assigned member as the tier's own value type.

        Derived from the two names the row carries and never stored beside
        them: the row is a provider and a model, and this is that pair offered
        back in the shape a tier's membership check and feature 196's gate both
        read.  A caller that wants to hand this assignment to
        :meth:`providers.RootProviderRotation.record` therefore assembles
        nothing.
        """
        return FrontierProvider(provider=self.provider, model=self.model)

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline
        :meth:`providers.ScheduledRun.row` states: a rendered mapping names the
        same things the same way the store does.  ``declared`` is rendered
        through the same canonical JSON the column holds, so a caller comparing
        this mapping to a row reads one spelling.  ``recorded`` is deliberately
        absent — it is this call's answer state, not a fact of the row.
        """
        return {
            CAMPAIGN_ID_COLUMN: self.campaign_id,
            NODE_ID_COLUMN: self.node_id,
            PROVIDER_COLUMN: self.provider,
            MODEL_COLUMN: self.model,
            DEPTH_COLUMN: self.depth,
            DECLARED_PROVIDERS_COLUMN: _tier_json(self.declared),
            ROTATION_DIGEST_COLUMN: self.digest,
            ASSIGNED_AT_COLUMN: _format_instant(self.assigned_at),
        }

    @property
    def root_call(self) -> RootCall:
        """The root call this assignment was made against — feature 196's seam.

        The bridge between this feature's record and feature 196's gate: 196
        takes a :class:`providers.RootCall`, and the call an assignment is about
        is the two ids it carries plus **the depth the tree placed the root
        at**, which this record carries because feature 196's probe derived it.
        Nothing is assumed here — the value is the one the probe answered when
        the row was written — so a caller re-recording a root call from a stored
        assignment cannot be told its depth disagrees with the tree over a
        constant this module invented.
        """
        return RootCall(
            node_id=self.node_id,
            campaign_id=self.campaign_id,
            depth=self.depth,
        )


# ── The persistence ───────────────────────────────────────────────────────────


def _validated_uuid(value: Any, field: str) -> str:
    """Validate an id, returning canonical UUID text.

    One guard for the two ids this module handles — the campaign's and the
    node's — because they fail the same way and owe the caller the same
    explanation.  Both join stored keys, and here both are also *hashed*, which
    raises the stakes: a mixed-case id that reached the hash uncanonicalised
    would assign one root two families depending on which spelling a caller
    happened to hold, and the row would look perfectly well-formed.
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
    raise RootRotationError(
        f"{field} {value!r} is not a UUID; a campaign's root rotation is "
        "recorded per campaign and per root, keyed by the ids feature 104's "
        "campaign table and feature 97's node table hold — and the assignment "
        "this feature computes is a hash of these two values, so an id that "
        "cannot be canonicalised would assign one root two families depending "
        "on which spelling the caller held. Supply the value the tree stores."
    )


def _require_name(value: object, field: str) -> str:
    """Return ``value`` as a non-empty stripped name, refusing anything else.

    One guard for the two names a family is made of — its provider's and its
    model's — because they fail the same way and owe the caller the same
    explanation.  Whitespace is stripped rather than preserved, the rule
    :func:`providers._root._require_name` states: the name is a **lookup key**
    (here, matched against the declared set's members), so ``' anthropic '`` and
    ``'anthropic'`` must be one family.
    """
    if not isinstance(value, str):
        raise RootRotationError(
            f"an assigned family's {field} must be a string, got {value!r} "
            f"({type(value).__name__}). A rotation assigns one declared member "
            "per root, and a member is a pair of names — a value that is not a "
            "name cannot be compared with the set the assignment was drawn from."
        )
    text = value.strip()
    if not text:
        raise RootRotationError(
            f"an assigned family's {field} must be a non-empty name, got "
            f"{value!r}. A blank name is not a provider and not a model: it "
            "would match no member of the declared set, so the root it "
            "describes has no family — and a rotation row reading 'assigned to "
            "\"\"' is a row that names no family at all, which is the state "
            "§14.1's rotation exists to prevent."
        )
    return text


def _require_digest(value: object) -> str:
    """Return ``value`` as a sha256 hex digest, refusing anything else.

    Length and alphabet are checked rather than merely the type, because the
    digest is a column this feature *compares* — across one campaign's rows and
    against a freshly computed value — and a column that could hold ``'x'`` or a
    truncated hash would compare unequal for a reason no operator could see. A
    value that is not a sha256 hex string is a row this feature did not write.
    """
    if not isinstance(value, str) or len(value) != 64:
        raise RootRotationError(
            f"a rotation's digest must be a 64-character sha256 hex string, got "
            f"{value!r} ({type(value).__name__}). The digest names the "
            "campaign's rotation — campaign and declared set together — and a "
            "value that is not one cannot be compared with anything, which is "
            "the only thing the column is for."
        )
    if any(character not in "0123456789abcdef" for character in value):
        raise RootRotationError(
            f"a rotation's digest {value!r} carries a character outside "
            "lowercase hex. The digest is sha256's hexadecimal spelling as "
            "``hexdigest`` renders it, and a value in another alphabet would "
            "compare unequal against the same rotation written by this feature."
        )
    return value


def _require_instant(value: object, what: str) -> datetime:
    """Return ``value`` as an aware UTC ``datetime``, refusing the rest.

    The same split every store in this member makes: aware datetimes of any
    offset are accepted and converted — an instant is an instant — while naive
    ones are refused by name, because a naive value names no instant and a row
    stamped with it could not be placed on the timeline the campaign's other
    records keep time on.
    """
    if not isinstance(value, datetime):
        raise RootRotationError(
            f"{what} must be a datetime, got {value!r} "
            f"({type(value).__name__}). An assignment is written at an instant, "
            "and a value that is not an instant cannot be one."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise RootRotationError(
            f"{what} must be timezone-aware, got {value!r}: a naive datetime "
            "names no instant, and stamping a rotation row with one would leave "
            "an assignment that cannot be placed on the timeline the campaign's "
            "own records keep time on."
        )
    return value.astimezone(UTC)


def _require_root_depth(value: object, node: str) -> int:
    """Return ``value`` as a root depth, refusing anything else.

    ``bool`` is refused by identity beside ``int`` for the reason
    :func:`providers._root._require_depth` refuses it: ``bool`` is a subclass of
    ``int``, so ``True`` would otherwise be admitted as depth 1 — a root depth —
    and a row whose depth came from a flag would be read back as a tree fact.

    A depth above :data:`providers.ROOT_TIER_MAX_DEPTH` is refused **on the read
    path**, and that is the point of restating the boundary here rather than
    trusting the writer: the probe refuses such a node before any row is
    written, so a row carrying one was not written by this feature — and
    reading it back as a root's assignment would launder a depth call's node
    into the table a rotation's per-family strata are read from.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RootRotationError(
            f"the rotation row for node {node!r} carries a depth {value!r} "
            f"({type(value).__name__}), which is not the integer depth feature "
            "97's tree stores. The row was not written by this feature — its "
            "depth column is the value feature 196's probe read off the tree — "
            "and a depth that is not a depth is a record this feature cannot "
            "report."
        )
    if value < 0 or value > ROOT_TIER_MAX_DEPTH:
        raise RootRotationError(
            f"the rotation row for node {node!r} carries depth {value}, and a "
            f"root call is at depth 0–{ROOT_TIER_MAX_DEPTH} (architecture §14.1: "
            "'Signal agent, roots (depth 0–1)'). Feature 197 assigns root calls "
            "only — the probe refuses a deeper node before any row is written — "
            "so this row was not produced by the gate, and reading it back as a "
            "root's assignment would put a depth call's node into the strata a "
            "campaign's rotation is read by."
        )
    return value


def _require_recorded(value: object) -> bool:
    """Return ``value`` as the answer-state flag, refusing anything else.

    A strict ``bool`` by identity, for the reason
    :func:`providers._root._require_recorded` checks it that way: a record whose
    state flag is ``0`` or ``None`` would read as falsy in a caller's branch
    while asserting nothing, and *did this call write the row?* is a question
    whose answer must be stated rather than coerced.
    """
    if value is not True and value is not False:
        raise RootRotationError(
            f"a rotation record's recorded must be True or False, got "
            f"{value!r} ({type(value).__name__}). The flag says whether the "
            "call that returned the record wrote the row or answered one "
            "already there, and a value that is neither is a state no caller "
            "could branch on."
        )
    return value


def _format_instant(moment: datetime) -> str:
    """An instant as the spine's ISO-8601 UTC text — ``0111``'s own spelling.

    ``%Y-%m-%dT%H:%M:%S`` plus a three-digit millisecond field and a ``Z``,
    byte-for-byte the form SQLite's
    ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` writes for the campaign table's
    ``created_at`` — restated here (not imported from :mod:`providers._root`)
    on the ground every store in this member states: each store owns its own
    column spellings.  The milliseconds are written by hand because
    ``strftime``'s ``%f`` is six digits and the spine's is three.
    """
    utc = moment.astimezone(UTC)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"


def _parse_instant(text: object, where: str, column: str) -> datetime:
    """Read back a row's instant, refusing a value that is not one.

    The read path's one instant parser, so :meth:`RootRotation.assign`'s
    read-back and :meth:`RootRotation.get` cannot disagree about the form.
    Anything the spine's spelling round-trips is accepted; anything else — text
    another dialect wrote, a truncated column, an editing accident — is refused
    naming the row and the column, because a row whose instant does not parse is
    one this feature cannot report.
    """
    if not isinstance(text, str) or not text.strip():
        raise RootRotationError(
            f"the rotation row for {where} carries {column} {text!r}, which is "
            "not an ISO-8601 UTC instant. The row was not written by this "
            "feature — its instant column is the spine's own timestamp text, "
            "and one that does not parse is a row this record cannot report."
        )
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise RootRotationError(
            f"the rotation row for {where} carries {column} {text!r}, which "
            "does not parse as an ISO-8601 instant. The row was not written by "
            "this feature, and an instant that cannot be read is a record this "
            "feature cannot report."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RootRotationError(
            f"the rotation row for {where} carries {column} {text!r} without a "
            "UTC offset: it names no instant, and a row that names no instant "
            "cannot be placed beside the campaign's own records on any timeline."
        )
    return parsed.astimezone(UTC)


def _parse_text(value: object, where: str, column: str) -> str:
    """Read back one of the row's name columns, refusing a value that is not one.

    The read path's one text parser, for the provider and the model column
    (SQLite answers ``TEXT`` affinity for a well-formed column and an integer or
    a float for one that was not written by this feature).  A name that is not a
    string is refused naming the row and the column rather than coerced: a row's
    family is the fact this feature exists for, and ``str(row[2])`` would
    launder a column an editing accident turned into a number into a family
    nobody declared.
    """
    if not isinstance(value, str):
        raise RootRotationError(
            f"the rotation row for {where} carries {column} {value!r} "
            f"({type(value).__name__}), which is not the text this feature "
            "writes. The row was not written by this feature — its name columns "
            "are strings — and a family that is not a name is a record this "
            "feature cannot report."
        )
    return _require_name(value, column)


def _tier_json(tier: FrontierTier) -> str:
    """The declared set's canonical column text.

    An array of ``["provider", "model"]`` pairs in the tier's own canonical
    order, rendered compact — one spelling of one declaration, so two sets
    stated in different orders write the same column and a retry's read-back
    compares equal.  The sorted-compact-JSON discipline
    :func:`providers._schedule._pricing_json` and
    :class:`providers.AgentSampling` bring to their own columns, restated here
    for a set that arrives already canonicalised by its constructor.

    The order is **not** re-sorted here: :class:`providers.FrontierTier` sorted
    its members on construction, and a second sort in the renderer would be a
    second statement of the canonical order — the drift the one-owner rule
    exists to prevent.  The pairs are emitted in the order the tier holds.
    """
    pairs = [[member.provider, member.model] for member in tier.providers]
    return json.dumps(pairs, separators=(",", ":"))


def _tier_from_json(text: object, where: str) -> FrontierTier:
    """Read back the row's declared set, refusing a value that is not one.

    The premise is read back as it was written — every pair re-made through
    :class:`providers.FrontierTier`'s constructor, so the stored text and a
    freshly configured set answer equal values — and anything else is refused
    naming the row: a premise that does not parse is a row this feature cannot
    re-verify its assignment against, which is the whole reason the column
    exists.  The constructor's own refusals (an empty set, a member stated
    twice) propagate rather than being restated, so a stored premise is held to
    exactly the law a configured one is.
    """
    if not isinstance(text, str) or not text.strip():
        raise RootRotationError(
            f"the rotation row for {where} carries {DECLARED_PROVIDERS_COLUMN} "
            f"{text!r}, which is not the canonical JSON this feature writes. The "
            "row was not written by this feature, and an assignment without a "
            "readable premise is a decision that cannot be audited."
        )
    try:
        pairs = json.loads(text)
    except ValueError as exc:
        raise RootRotationError(
            f"the rotation row for {where} carries {DECLARED_PROVIDERS_COLUMN} "
            f"{text!r}, which does not parse as JSON. The row was not written by "
            "this feature, and a premise that cannot be read is an assignment "
            "that cannot be re-derived."
        ) from exc
    if not isinstance(pairs, list):
        raise RootRotationError(
            f"the rotation row for {where} carries "
            f"{DECLARED_PROVIDERS_COLUMN} {text!r}, which is not an array of "
            "``[provider, model]`` pairs. The column holds the declared set the "
            "assignment was drawn from, in this feature's own canonical shape, "
            "and a value in another shape is a row this feature cannot read."
        )
    if not pairs or not all(
        isinstance(pair, list)
        and len(pair) == 2
        and all(isinstance(name, str) for name in pair)
        for pair in pairs
    ):
        raise RootRotationError(
            f"the rotation row for {where} carries "
            f"{DECLARED_PROVIDERS_COLUMN} {text!r}, which is not the non-empty "
            "array of ``[\"provider\", \"model\"]`` string pairs this feature "
            "writes. The column holds the declared set the assignment was drawn "
            "from, and a value in another shape — a bare string where a pair is, "
            "a number where a name is, an empty set — is a row this feature "
            "cannot re-derive the assignment from."
        )
    try:
        return FrontierTier(
            providers=tuple(
                FrontierProvider(provider=pair[0], model=pair[1])
                for pair in pairs
            )
        )
    except RootProviderError as exc:
        # The constructor's own refusals (a member stated twice) are re-made as
        # this feature's error: they are raised *about a stored row*, and a
        # caller reading a rotation cannot be asked to import feature 196's
        # vocabulary to catch a malformed premise — the same translation
        # feature 202's read-back applies to its own window values.
        raise RootRotationError(
            f"the rotation row for {where} carries "
            f"{DECLARED_PROVIDERS_COLUMN} {text!r}, which is not a set feature "
            f"196's tier accepts: {exc}"
        ) from exc


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The convention every store in this workspace uses, restated here so this
    store states its own contract and the refusal is this module's own error
    class.  A non-SQLite scheme is refused by name (the spec's single-machine
    allowance is what a stdlib store can speak), and an in-memory URL is refused
    too: a campaign's rotation must outlive the assigning call — the discovery
    loop that places the roots, the loader that re-derives the assignment, and
    the auditor that reads the rotation all run in other processes.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RootRotationError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the tree already "
            "lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RootRotationError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RootRotationError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and a "
            "campaign's root rotation must outlive the call that decided it — "
            "the discovery loop places roots in one process and the loader "
            "re-derives the assignment in another"
        )
    return Path(path)


def _call_from_parts(value: object, what: str) -> RootCall:
    """Re-make a root call from its parts, refusing anything else.

    Recognition **by its parts** — the three attributes :data:`_CALL_PARTS`
    names, read on ``object.__getattribute__`` — rather than by class, because
    the module loader gives every member two class objects over one source file
    (see :mod:`providers._root`'s docstring): an ``isinstance`` gate would
    refuse the very call a caller legitimately built from the member.  The
    answer is re-made from :class:`providers.RootCall`, so what this module
    hands feature 196's gate is this module's class.
    """
    try:
        node, campaign, depth = (
            object.__getattribute__(value, part) for part in _CALL_PARTS
        )
    except AttributeError:
        raise RootRotationError(
            f"{what} must be a root call ({', '.join(_CALL_PARTS)}), got "
            f"{value!r} ({type(value).__name__}). A rotation assigns a family to "
            "one root call, and a call is identified by the node it authored, "
            "the campaign that node belongs to and the depth the tree placed it "
            "at — a value carrying none of those names no root, and padding the "
            "missing parts with guesses would assign a family to nobody."
        ) from None
    return RootCall(node_id=node, campaign_id=campaign, depth=depth)


class RootRotation:
    """The store that decides and records a campaign's root provider rotation.

    Constructed with the database URL it writes to.  :meth:`assign` is feature
    197's sentence as one call — validate the ask, compute the root's family
    from the root's identity, prove the tree holds the node, reconcile against
    the campaign's stored rows, insert, read back — and
    :meth:`record_root_provider` is the pair: the same decision, then feature
    196's gate writing the provenance row for the call that carried it out.
    :meth:`get` reads one root's assignment and :meth:`rotation` reads a whole
    campaign's.

    The class resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store in
    this workspace states.  The table
    (:data:`ROOT_PROVIDER_ROTATION_TABLE`) is this member's own, created lazily
    on the store's **first write** — :meth:`get` and :meth:`rotation` on a store
    that has never assigned read ``sqlite_master``, find no table and answer
    ``None`` / ``{}``, so a read never brings a schema into being.

    The store holds no cache of the assignments it wrote, for the reason
    :class:`providers.RootProviderRotation` states on its own behalf: *which
    family was this root assigned?* must be a question about the campaign, not
    about this process's history — §14.1's rotation is recorded precisely so the
    answer survives the process that made the decision.

    **Feature 196's store is composed, not replaced.**  :meth:`assign` and
    :meth:`record_root_provider` construct a
    :class:`~providers.RootProviderRotation` over the same URL for the
    provenance half, so the serving-provider row has one writer and one gate:
    196's.  This class does not read that table, write it directly, or restate
    its rules.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RootRotationError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> RootRotation | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        rotation component — a discoverable state, not an exception — while the
        caller that must decide a campaign's rotation is the caller that must
        not find itself in it, for the reason
        :func:`providers.build_root_provider_rotation` states on its own
        ``None``: the caller that needs this row treats it as a refusal to
        proceed rather than as a store that happened to find nothing.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an operation
        needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    @property
    def provider_rotation(self) -> RootProviderRotation:
        """Feature 196's store over the same deployment — the provenance half.

        Constructed fresh on each read (it is a stateless handle onto a URL, and
        its own construction performs no I/O), so this feature never holds a
        second copy of another feature's store that could drift from the one
        the application composes.
        """
        return RootProviderRotation(self._database_url)

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The caller owns the connection; use it as a context manager to commit,
        which is what :meth:`assign` does — the node probe, the campaign's
        stored rows and the ``INSERT`` are one unit of work, so a node expanded
        by a concurrent process between the probe and the insert is seen, and
        two assigners of one root cannot interleave a read and a write.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        """Create this member's own table, idempotently.

        The one act that separates this store from
        :class:`providers.AgentModelPins`: that store writes a column a core
        migration owns and refuses to invent the table; this one's table is its
        own feature's record, on the ``bootstrap_world`` / ``depth_run_window``
        / ``depth_cache_rate`` / ``root_serving_provider`` precedent, and
        creating it lazily is the store's business.  ``IF NOT EXISTS``, so a
        database that already holds it — a second campaign's roots, a restarted
        process — passes through untouched.
        """
        connection.execute(_SCHEMA)

    # -- Feature 197: the assignment ----------------------------------------

    def assign(
        self,
        call: object,
        tier: object,
        *,
        now: datetime | None = None,
    ) -> RootAssignment:
        """Assign one root to a family in a campaign's rotation, and persist it.

        Feature 197's sentence as one call: the root, the campaign's declared
        frontier tier and the moment in, the stored assignment out — the
        decision and its persistence as one act, because a rotation decided and
        not recorded is the sentence with its second half missing.  The steps,
        and why each is where it is:

        1. **Validate the ask** — the call's three tree facts and the tier —
           *before anything is opened*, so a malformed ask is refused without
           touching a database.
        2. **Compute the family** (:func:`rotation_index`) — the assignment
           itself, a pure function of the campaign's id, the root's id and the
           size of the declared set.  It is computed before the probe because it
           needs nothing the database holds, and computing it is what makes the
           next two steps checkable: the node's existence and the campaign's
           stored rows are checked *against a decision already made*, rather
           than the decision being made out of whatever the probe found.
        3. **Create the table**, lazily and idempotently — the row's first write
           brings its schema into being, and nothing else ever does.
        4. **Prove the tree holds the node, through feature 196's gate** — the
           probe is 196's ``_require_node``, not a second reading of feature
           97's ``node`` table, so an unexpanded node is 196's
           :class:`~providers.RootNotRecordedError` naming the expansion and a
           node below the root tier is 196's
           :class:`~providers.UnrotatedCampaignError` naming the boundary.  One
           store checks the tree for both features; a second spelling of that
           probe is how two features come to disagree about what the tree says.
        5. **Reconcile against the campaign's stored rotation** — every row this
           campaign already holds must carry the same declared set (the drift
           check, :class:`~providers.RootRotationError` naming both sets), and
           this root must not already be assigned a *different* family
           (:class:`~providers.RotationConflictError`, naming both).  The
           identical assignment answers the stored row (``recorded=False``, the
           original ``assigned_at``, which a retry does not move).
        6. **Insert, then read back**, and return what the table holds: every
           column is the row's, re-parsed through the same readers :meth:`get`
           uses, so a caller holds one record shape from one source of truth.

        Refuses, in this order, each naming what it is about: a malformed call,
        tier or id (the base :class:`~providers.RootRotationError`, or
        :class:`providers.FrontierTier`'s own refusals for an empty or
        duplicated set); a node feature 97's tree does not hold
        (:class:`~providers.RootNotRecordedError`, feature 196's); a call the
        tree places below the root tier
        (:class:`~providers.UnrotatedCampaignError`, feature 196's); a campaign
        whose stored rotation declares another set (the base, naming both); a
        root already assigned another family
        (:class:`~providers.RotationConflictError`).
        """
        validated = _call_from_parts(call, "a root call")
        declared = _tier_from_parts(tier)
        # The decision, made before the probe: it needs nothing the database
        # holds, and the steps below check the tree and the campaign *against* a
        # decision rather than deriving one from what they find.
        assigned = declared.providers[
            rotation_index(validated.campaign_id, validated.node_id, declared)
        ]
        # One instant for the row's stamp, computed once so the stored value and
        # any retry's comparison read the same moment — the same "two clocks
        # narrating one decision" guard :meth:`providers.RootProviderRotation.record`
        # states.
        assigned_at = (
            _require_instant(datetime.now(UTC), "the assigning instant")
            if now is None
            else _require_instant(now, "the assigning instant")
        )
        digest = rotation_digest(validated.campaign_id, declared)
        with closing(self._connect()) as connection, connection:
            self._ensure_schema(connection)
            # The tree's own facts, asked of feature 196's probe rather than
            # read a second time here: one store checks the tree for both
            # features, so the two cannot come to disagree about what it says —
            # and the depth it returns is the value this row stores, so the
            # assignment carries what the tree placed the root at rather than
            # what the caller claimed.
            _, tree_depth = self.provider_rotation.require_root_node(
                connection, validated
            )
            self._require_rotation(connection, validated, declared, digest)
            stored = self._read_row(
                connection, validated.campaign_id, validated.node_id
            )
            if stored is not None:
                return self._reissued(stored, assigned, validated, recorded=False)
            connection.execute(
                f"INSERT INTO {ROOT_PROVIDER_ROTATION_TABLE} "
                f"({CAMPAIGN_ID_COLUMN}, {NODE_ID_COLUMN}, {PROVIDER_COLUMN}, "
                f"{MODEL_COLUMN}, {DEPTH_COLUMN}, "
                f"{DECLARED_PROVIDERS_COLUMN}, {ROTATION_DIGEST_COLUMN}, "
                f"{ASSIGNED_AT_COLUMN}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    validated.campaign_id,
                    validated.node_id,
                    assigned.provider,
                    assigned.model,
                    tree_depth,
                    _tier_json(declared),
                    digest,
                    _format_instant(assigned_at),
                ),
            )
            row = self._read_row(
                connection, validated.campaign_id, validated.node_id
            )
        if row is None:
            raise RootRotationError(
                f"the rotation assignment for node {validated.node_id!r} in "
                f"campaign {validated.campaign_id!r} could not be read back "
                "after the insert; the row is the decision, and a decision that "
                "cannot be re-read is one this store cannot vouch for"
            )
        return self._record_from_row(row, recorded=True)

    def record_root_provider(
        self,
        call: object,
        serving: object,
        tier: object,
        *,
        now: datetime | None = None,
    ) -> tuple[RootAssignment, RootCallProvider]:
        """Assign a root, then record which family actually served its call.

        Feature 197's sentence and feature 196's joined: the root, the family
        the caller read off feature 192's completion, and the campaign's
        declared tier in; the assignment and the provenance row out.  This is
        the call a discovery loop makes, and it is the pair the two features'
        docstrings describe — 197 decides *what was assigned*, 196 records *what
        served*, and a store that did both would be deciding an assignment on
        the way to writing it down.

        The order is load-bearing.  :meth:`assign` runs **first**, so the
        rotation covers the root before any provenance row is written; then the
        serving family is checked against it — the assignment must name it, or
        the call is :class:`~providers.UnassignedRootProviderError` and
        **nothing has been written**; and only then is feature 196's gate asked
        to record the row, which means 196's own refusals (a serving family the
        declared set does not name, a provenance row that already names another
        family) are raised *after* a rotation row this call legitimately wrote.
        That is correct and it is worth stating: the assignment is this feature's
        fact and it was decided; what failed is the provenance of a call that
        disagrees with it, and the rotation row is exactly the record that makes
        the disagreement legible.  A caller that wants the two as one atomic act
        wraps the pair in its own transaction, which it cannot get from two
        stores with two tables in any case.

        The serving family is recognised **by its parts** and compared on the
        pair, so a member built from the workspace's other copy of this member
        is admitted — the double-import remedy, applied to the value that
        crosses from feature 192's completion into this feature's gate.

        Feature 196's refusals propagate **untranslated**: a node the tree does
        not hold, a depth call, a declaration the tree contradicts, a serving
        family the declared set does not name, a provenance conflict.  Each
        already names the fact precisely, and re-wrapping one in this feature's
        vocabulary would put a second, vaguer sentence in front of the one an
        operator needs.
        """
        assignment = self.assign(call, tier, now=now)
        observed = _member_from_parts(serving, "a root call's serving provider")
        if (
            observed.provider != assignment.provider
            or observed.model != assignment.model
        ):
            raise UnassignedRootProviderError(
                f"the root call for node {assignment.node_id!r} in campaign "
                f"{assignment.campaign_id!r} reports "
                f"{observed.text()!r} as the family that served it, and the "
                f"campaign's rotation assigned that root "
                f"{assignment.assigned_provider.text()!r}. Feature 197 exists so "
                "that different model families propose structurally different "
                "mechanisms (architecture §14.1: 'Rotating providers at roots is "
                "the cheapest mitigation available'), and that only holds if the "
                "family that served a root is the one the rotation assigned it — "
                "a record that accepted any family the completion reported would "
                "write a silent re-route into the rotation as though a human had "
                "chosen it, which is the §14.1 provenance failure verbatim "
                "(deepseek-v4-flash, retired 2026-09-10 while continuing to "
                "accept the ID). Nothing has been written for this call. Either "
                "the call belongs to another root (assign it and record it "
                "against the node it authored), or the rotation intended this "
                "family — in which case the declared set or the assignment is "
                "what to change, before the call is recorded."
            )
        provenance = self.provider_rotation.record(
            assignment.root_call,
            _tier_from_parts(tier),
            assignment.assigned_provider,
            now=now,
        )
        return assignment, provenance

    def get(
        self, campaign_id: Any, node_id: Any
    ) -> RootAssignment | None:
        """One root's assignment, or ``None`` when the rotation holds none.

        ``None`` means *this campaign's rotation never assigned this root* —
        nothing has assigned it — which is the honest answer for a root no row
        holds, and the answer on a database whose ``root_provider_rotation``
        table does not exist yet (a store that has never assigned created
        nothing, and a read does not create it).  It does **not** mean the read
        failed: an unreachable database raises, so a caller can never mistake a
        broken store for an unassigned root — the same distinction
        :meth:`providers.RootProviderRotation.get` draws.

        The record is **re-verified, not merely re-parsed**: the two ids are
        UUIDs, the two names are names, the declared set parses and its members
        are pairs, the digest is sha256 hex **and is the digest of the row's own
        premise**, the instant parses — each refusal names the row, on the
        ground the read side is where corruption would otherwise be laundered.
        ``recorded`` is always ``False`` here: a read wrote nothing.
        """
        campaign = _validated_uuid(campaign_id, "campaign_id")
        node = _validated_uuid(node_id, "node_id")
        with closing(self._connect()) as connection:
            if (
                connection.execute(
                    _TABLE_EXISTS_SQL, (ROOT_PROVIDER_ROTATION_TABLE,)
                ).fetchone()
                is None
            ):
                return None
            row = self._read_row(connection, campaign, node)
        if row is None:
            return None
        return self._record_from_row(row, recorded=False)

    def rotation(self, campaign_id: Any) -> dict[str, RootAssignment]:
        """One campaign's whole rotation, as ``{node_id: RootAssignment}``.

        The row-set **is** the rotation, so this is the read the table's
        ``(campaign_id, node_id)`` key exists for: one indexed lookup answers
        *what did this campaign rotate its roots across*, which is the fact
        feature 214 keys a campaign by and feature 215 reads per authoring
        model.  The mapping is keyed by the root's canonical node id, so a
        caller reads *which family was this root assigned?* without scanning,
        and the values are the same records :meth:`get` answers with.

        An empty mapping means *this campaign holds no rotation* — nothing has
        assigned one, or the table does not exist yet — and is returned in that
        case rather than refused, on the ground :meth:`get` states for its own
        ``None``: absent is a discoverable state, and the caller that must have
        a rotation is the caller that must not find itself in this one.

        A row-set whose rows disagree about the declared set cannot be *read*
        into a mapping at all — every row is re-verified through the same
        readers :meth:`get` uses, and a row describing a rotation this feature
        did not write is refused naming the row.  That is deliberate: a caller
        comparing two families' strata must not be handed a rotation assembled
        from rows that were never one decision.
        """
        campaign = _validated_uuid(campaign_id, "campaign_id")
        with closing(self._connect()) as connection:
            if (
                connection.execute(
                    _TABLE_EXISTS_SQL, (ROOT_PROVIDER_ROTATION_TABLE,)
                ).fetchone()
                is None
            ):
                return {}
            cursor = connection.execute(
                f"SELECT {CAMPAIGN_ID_COLUMN}, {NODE_ID_COLUMN}, "
                f"{PROVIDER_COLUMN}, {MODEL_COLUMN}, {DEPTH_COLUMN}, "
                f"{DECLARED_PROVIDERS_COLUMN}, {ROTATION_DIGEST_COLUMN}, "
                f"{ASSIGNED_AT_COLUMN} FROM {ROOT_PROVIDER_ROTATION_TABLE} "
                f"WHERE {CAMPAIGN_ID_COLUMN} = ? "
                f"ORDER BY {NODE_ID_COLUMN}",
                (campaign,),
            )
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return {
            _validated_uuid(row[1], "node_id"): self._record_from_row(
                row, recorded=False
            )
            for row in rows
        }

    # -- The words ----------------------------------------------------------

    def _read_row(
        self, connection: sqlite3.Connection, campaign: str, node: str
    ) -> tuple[Any, ...] | None:
        """One root's row as the table holds it, or ``None`` when absent.

        Selected column by column rather than with ``SELECT *``, the discipline
        :meth:`providers.RootProviderRotation._read_row` states: the order
        :meth:`_record_from_row` reads must be the order this names, and a
        column appended later must not silently shift the fields.
        """
        cursor = connection.execute(
            f"SELECT {CAMPAIGN_ID_COLUMN}, {NODE_ID_COLUMN}, "
            f"{PROVIDER_COLUMN}, {MODEL_COLUMN}, {DEPTH_COLUMN}, "
            f"{DECLARED_PROVIDERS_COLUMN}, {ROTATION_DIGEST_COLUMN}, "
            f"{ASSIGNED_AT_COLUMN} FROM {ROOT_PROVIDER_ROTATION_TABLE} "
            f"WHERE {CAMPAIGN_ID_COLUMN} = ? AND {NODE_ID_COLUMN} = ?",
            (campaign, node),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _record_from_row(
        self, row: tuple[Any, ...], *, recorded: bool
    ) -> RootAssignment:
        """Build a :class:`RootAssignment` from a row, re-verified.

        The read path's one constructor, so :meth:`assign`'s read-back,
        :meth:`get` and :meth:`rotation` cannot disagree about which column is
        which.  Every value is re-parsed through the row-shaped readers rather
        than trusted — and the record's own constructor then checks the digest
        against the premise beside it, so a row whose two spellings of the
        rotation disagree is refused here, naming the row, which is the
        difference between an operator learning *this campaign's rotation is
        corrupt* and learning that some value somewhere does not parse.
        """
        campaign = _validated_uuid(row[0], "campaign_id")
        node = _validated_uuid(row[1], "node_id")
        where = f"node {node!r} in campaign {campaign!r}"
        return RootAssignment(
            campaign_id=campaign,
            node_id=node,
            provider=_parse_text(row[2], where, PROVIDER_COLUMN),
            model=_parse_text(row[3], where, MODEL_COLUMN),
            depth=_require_root_depth(row[4], node),
            declared=_tier_from_json(row[5], where),
            digest=_require_digest(row[6]),
            assigned_at=_parse_instant(row[7], where, ASSIGNED_AT_COLUMN),
            recorded=recorded,
        )

    def _reissued(
        self,
        row: tuple[Any, ...],
        assigned: FrontierProvider,
        call: RootCall,
        *,
        recorded: bool,
    ) -> RootAssignment:
        """Answer a re-issued assignment: the stored row, or a conflict.

        The identical assignment — the same root, and the arithmetic naming the
        same family — returns the row the table holds, **including its original
        ``assigned_at``**.  A retry is the same decision arriving twice, and the
        row *is* the decision: the retry did not move the instant the rotation
        was decided, and §14.1's rotation assigns each root to one family.

        ``recorded`` is passed through rather than fixed here, for the reason
        :meth:`providers.RootProviderRotation._reissued` gives on its own copy:
        this method answers situations that differ only in that flag, and fixing
        it here would make them indistinguishable to a caller.

        A stored row naming a **different** family is refused, and the refusal
        names both, because that is the difference between an actionable
        refusal and a complaint: the caller learns which family is stored
        against this root and which the arithmetic now proposes.  The comparison
        is on the pair alone — the two names are the assignment, and the
        campaign, the premise and the instant beside them are facts the
        arithmetic cannot change without the declared set having changed, which
        :meth:`_require_rotation` has already checked.
        """
        stored = self._record_from_row(row, recorded=recorded)
        if (
            stored.provider == assigned.provider
            and stored.model == assigned.model
        ):
            return stored
        raise RotationConflictError(
            f"node {call.node_id!r} in campaign {call.campaign_id!r} is already "
            f"assigned {stored.provider}:{stored.model} in the campaign's root "
            f"rotation, and this assignment would name {assigned.text()}. One "
            "root is one call and one mechanism, and the family a rotation "
            "assigns it is what it is: architecture §14.1 spreads a campaign's "
            "roots across the declared providers so that different families "
            "propose structurally different mechanisms, and a rotation naming "
            "two families for one root would put that mechanism in both strata "
            "— the figure a per-family reading is drawn from would double-count "
            "it. The stored row is the decision. Read it with get(), or, if the "
            "root really was proposed a second time under another family, "
            "expand it as its own node so each assignment names one call."
        )

    def _require_rotation(
        self,
        connection: sqlite3.Connection,
        call: RootCall,
        declared: FrontierTier,
        digest: str,
    ) -> None:
        """Refuse an assignment that would contradict the campaign's stored rotation.

        The premise's own guard, and the reason the declared set is persisted on
        every row: a campaign's rotation is **one decision**, so every root of
        that campaign must be assigned out of the same declared set.  A second
        assignment naming a different set — a redeployment that added or dropped
        a family between two roots, a caller that configured the tier per call
        rather than per campaign — would make the row-set a mixture, and the
        digest feature 214 keys the campaign by would name a rotation that only
        part of the campaign was assigned under.

        Only the **distinct** stored spines are compared, so a campaign with five
        roots costs one ``GROUP BY`` and not five comparisons, and the refusal
        names both sets (the stored one and the offered one) and the count of
        rows carrying each — the three facts a repair needs, which are *this
        campaign was declared another way, here is how, and here is how much of
        it*.

        A campaign with no rows passes through: the first assignment *is* the
        declaration, and there is nothing to contradict.
        """
        cursor = connection.execute(
            f"SELECT {DECLARED_PROVIDERS_COLUMN}, {ROTATION_DIGEST_COLUMN}, "
            f"COUNT(*) FROM {ROOT_PROVIDER_ROTATION_TABLE} "
            f"WHERE {CAMPAIGN_ID_COLUMN} = ? "
            f"GROUP BY {DECLARED_PROVIDERS_COLUMN}, {ROTATION_DIGEST_COLUMN}",
            (call.campaign_id,),
        )
        try:
            stored = cursor.fetchall()
        finally:
            cursor.close()
        for text, stored_digest, count in stored:
            if stored_digest == digest:
                # The same declared set, whichever spelling the row carries —
                # and the digest is the comparison rather than the text, so a
                # row written by an older canonicaliser that rendered the same
                # set differently is not read as a different rotation.
                continue
            raise RootRotationError(
                f"campaign {call.campaign_id!r} already rotates its roots "
                f"across {_tier_from_json(text, 'a stored rotation row').text()!r}"
                f" ({count} root{'s' if count != 1 else ''} assigned), and this "
                f"assignment declares {declared.text()!r} instead. A campaign's "
                "root rotation is one decision — architecture §14.1 spreads a "
                "campaign's roots across the declared providers so that "
                "different families propose structurally different mechanisms, "
                "and the stratum that reading is drawn from is *this campaign's "
                "declared set*. Assigning some of a campaign's roots out of a "
                "different set would make the row-set a mixture and the rotation "
                "digest a name for a decision only part of the campaign was "
                "assigned under — and feature 214, which keys a campaign by that "
                "digest to reproduce the model that wrote it, would read a "
                "campaign whose rotation half the tree never used. Decide the "
                "campaign's rotation once, before its roots are placed, or "
                "re-derive it (a new campaign) if the families genuinely "
                "changed."
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def assign_root_provider(
    call: object,
    tier: object,
    *,
    now: datetime | None = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RootAssignment:
    """Assign one root to a family in its campaign's rotation — the module-level spelling.

    Feature 197's sentence as one call, for the caller that wants the decision
    without holding a store: the root call and the campaign's declared frontier
    tier in, the stored assignment out.  The store is resolved from
    ``database_url``, else from ``DATABASE_URL``; a deployment that names
    neither is refused *by name* rather than silently doing nothing, because a
    rotation that quietly skipped its write would leave the campaign's roots
    unassigned — and the next reader asking *which families did this campaign
    rotate across?* would be reading a rotation nobody recorded.

    A :class:`~providers.RootRotationError` from the store is left to propagate
    unwrapped, and so is any refusal feature 196's gate raises inside it: each
    already names the call, the campaign and the fact, and re-wrapping one here
    would put a second message in front of the one an operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise RootRotationError(
            "assign_root_provider assigns a campaign's roots to the families "
            f"its rotation declares and nothing names a store: {DATABASE_URL_ENV} "
            "is unset (and no database_url was supplied), so the rotation could "
            "not be recorded. Feature 197's rotation is a fact that must "
            "actually land in the table — architecture §14.1 rotates providers "
            "at roots precisely so that different families propose structurally "
            "different mechanisms, and a rotation nobody wrote down is a "
            "rotation neither the discovery loop nor the next campaign's reader "
            "can recover."
        )
    return RootRotation(url).assign(call, tier, now=now)
