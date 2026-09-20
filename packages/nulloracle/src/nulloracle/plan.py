"""The planning gate: one tree, one regime — feature 122.

app_spec.xml, "Null Oracle & Planted Nulls", feature 122: *System rejects a
campaign plan that mixes Type-R and Type-D assignment within one tree, which
emits a heterogeneous_world error message.*  docs/nullius-tech-architecture.md
§7.3 states the rule the sentence enforces in the one line every writer in
this member already leans on::

    Campaigns are **homogeneous in null type**. Mixed trees make a bad FDR
    unattributable between selection failure and stopping failure, and every
    policy version is scored on every world, so worlds must measure one thing.

This module is that rule as a gate: a :class:`CampaignPlan` is one campaign's
planned null world — the campaign, its declared regime, and the nodes each
half of §7.3's assignment would land on — and a plan that mixes the two
regimes within one tree refuses to exist, raising
:class:`~nulloracle.errors.HeterogeneousWorldError` with the
``heterogeneous_world`` message the spec names.

**Why a mix is fatal rather than merely untidy.**  The two regimes keep their
null-ness in *different places*, and that is the whole of the danger.  A
Type-R node's status is a root selection sealed in §7.1's sidecar and
inherited by the whole subtree (feature 118); a Type-D node's is a flip depth
on its branch (feature 119), resolved by feature 121's depth rule.  A tree
carrying both would hold nulls **no single read path serves**: the sidecar
would answer for the selected roots' descendants, the depth rule for the
flipped branches', and a score computed over the campaign could not say which
world it was measured against.  §7.3 names the consequence exactly — *a bad
FDR unattributable between selection failure and stopping failure* — and the
second clause is the reason the refusal belongs at the *plan*: "every policy
version is scored on every world", so a world that measures two things
corrupts every comparison the pool makes, not one campaign's number.

**The gate, not a third writer.**  Features 118 and 119 plant the two halves
and each declines the regime it is not (:meth:`~nulloracle.selection.
TypeRSelection.persist` refuses a non-``'Type-R'`` campaign by name;
:meth:`~nulloracle.resolution.TypeDOracle.resolve_request` refuses a
``'Type-R'`` one), but a writer's refusal is per *call* — it sees the row in
front of it, not the tree behind it.  This module is the check that runs
above the writers, on the plan as a whole, and it has two spellings for the
two moments a plan exists:

* **before anything is planted** — a caller composes :class:`CampaignPlan`
  from what it intends (the wells a selection will be drawn over, the
  branches a flip will be drawn on), and construction is the refusal: a
  mixed plan never becomes a value a writer could act on;
* **after the writers have run** — :meth:`CampaignPlanGate.review` reads the
  plan the writers left *behind* (the flip depths on the campaign's node
  rows, the root entries in §7.1's sidecar) and constructs the same value
  from the tree, so a world that went mixed by any path — a planner bug, a
  mis-scripted loop, a store written by an older deployment — is caught by
  the one decision, not re-implemented per writer.

**The campaign's declared type is one side of the comparison.**  A mix is
not only "a root selection *and* a flip in one tree."  A ``'Type-R'``
campaign whose branches carry flip depths is mixed *even with an empty
sidecar*: the row declares the selection-test regime and the tree carries a
stopping-test assignment, and at review time that is exactly the state a
buggy loop leaves behind (feature 119's writer confirms the campaign exists
but not its type, so a flip drawn onto a Type-R campaign persists today).
The mirror holds for a ``'Type-D'`` campaign whose roots appear in the
sidecar.  So the decision :meth:`CampaignPlan._require_homogeneous` makes is
one comparison in three shapes — both halves present, a flip under a
``'Type-R'`` declaration, a selection under a ``'Type-D'`` declaration — and
each is the same refusal with the same code, because each is the same fact:
this tree would measure two things.

**Where the two halves are read from, and why the gate needs both composed.**
Type-D assignment lives on the tree store's ``node.flip_depth`` column and
Type-R assignment lives in §7.1's sidecar — the one artifact allowed to hold
the bit (feature 110: no ``is_null`` column anywhere in the tree store).  A
gate holding only the database could see flips but not selections, and a
review that read "no sidecar entries" off a store with no sidecar would
bless every mixed world as homogeneous.  So, like feature 118's selection
store, this one composes only where a relational store *and* a sidecar both
resolve, and its ``None`` means *one of the two is unconfigured* — never
*the world is homogeneous*, which is a fact about a tree and not about a
deployment.

**An absent sidecar file is not an unopenable one.**  The review runs at
planning time, when a deployment's first campaign may legitimately have no
``sidecar.enc`` yet, so :meth:`CampaignPlanGate.review` treats a file that
does not exist as *no root selections recorded anywhere* — which is simply
true, because the file is the only place a selection could be recorded.
The distinction the member's taxonomy draws is preserved on the other side:
a file that exists but will not authenticate raises
:class:`~nulloracle.errors.SidecarDecryptionError`, and one the process may
not read raises :class:`~nulloracle.errors.SidecarAccessError`, both
propagating unwrapped — never translated into a verdict — because *"null
sidecar key lost → FDR history uninterpretable"* (§7) and *"this tree mixes
two regimes"* are opposite findings, and a caller must never learn the first
as the second.

**The gate refuses mixing and nothing else.**  Not completeness: an
undrawn world — no sidecar entries, no flips — reviews to a valid,
homogeneous plan with both halves empty, because *"has this campaign been
planted yet?"* is the writers' and readers' question (feature 118's
:meth:`~nulloracle.selection.TypeRSelection.load`, feature 121's undrawn-
branch refusal), not the gate's.  Not φ, not ``W``: those are feature 117's
column and feature 104's, applied where they are written.  The one question
this module answers is §7.3's: *does this tree measure one thing?*

**The error vocabulary, and where each refusal lands.**  The mix — and only
the mix — is :class:`~nulloracle.errors.HeterogeneousWorldError`, every
message beginning with :data:`HETEROGENEOUS_WORLD` (``heterogeneous_world``),
the spec's own word, so an operator grepping a log for the rejection finds
it by the feature's spelling — the same discipline
:data:`contract.violation.CONTRACT_VIOLATION` applies to the outcome it
names.  A malformed campaign or node id, a campaign the table does not
hold, a declared type that is neither of §7.3's two regimes, and a stored
flip depth that is not a genuine positive integer are
:class:`~nulloracle.errors.KsGuardError` — store-contract failures, the
same split this member's other stores state — because a caller that catches
the gate's refusal is rejecting a *design*, and a caller that catches the
store's is investigating a *row*.  The two must not be confused: a planner
that retried a heterogeneous world as a database hiccup would plant exactly
the tree §7.3 forbids.

**Stdlib only, and import-cheap.**  ``os``, ``sqlite3``, ``dataclasses``
and ``urllib.parse`` at module scope — no third-party import, so the
factory's scan, which imports this package to fire its ``@register``, pays
nothing for this module; the sidecar's ``cryptography`` stays deferred to
first use exactly as feature 118's store defers it.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .assignment import normalize_node_id
from .errors import HeterogeneousWorldError, KsGuardError
from .resolution import TYPE_D_CAMPAIGN_TYPE
from .selection import TYPE_R_CAMPAIGN_TYPE
from .sidecar import NullSidecar

__all__ = [
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TYPE_COLUMN",
    "DATABASE_URL_ENV",
    "FLIP_DEPTH_COLUMN",
    "HETEROGENEOUS_WORLD",
    "NODE_TABLE",
    "REGIMES",
    "CampaignPlan",
    "CampaignPlanGate",
    "review_campaign_plan",
]

#: The error message feature 122 names, verbatim: the code every
#: :class:`~nulloracle.errors.HeterogeneousWorldError` message begins with.
#:
#: Spelled once, as a constant, for the same reason
#: :data:`contract.violation.CONTRACT_VIOLATION` is: the spec's own word for
#: the rejection is the one an operator greps a log for, and two writers
#: spelling it differently would persist two codes for one failure.  A prefix
#: rather than a substring so a log line cannot carry it by accident — the
#: message *begins* with the code, and everything after the colon is the
#: explanation.
HETEROGENEOUS_WORLD = "heterogeneous_world"

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the guard's, the
#: verdict's, the fraction's, the flip depth's, the selection's, the
#: repository-level conftest's), restated here so this store states its own
#: contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The campaign row's type — the column that declares which of §7.3's two
#: regimes a campaign's tree belongs to, written by the planner before any
#: node is expanded.  Read here, never written: the gate compares the
#: declaration against what the tree carries, and a gate that could edit the
#: declaration could hide the mix it exists to refuse.
CAMPAIGN_TYPE_COLUMN = "campaign_type"

#: The campaign table — feature 104's, the row that carries the declaration
#: the gate reads.  Spelled once here, and once in :mod:`nulloracle.phi`,
#: :mod:`nulloracle.flipdepth`, :mod:`nulloracle.irprob`,
#: :mod:`nulloracle.ksguard`, :mod:`nulloracle.verdict`,
#: :mod:`nulloracle.selection` and :mod:`nulloracle.resolution`, so the
#: writers and readers of the campaign row cannot drift apart on what it is
#: called.
CAMPAIGN_TABLE = "campaign"

#: The tree store's node table — feature 97's, read here for the campaign's
#: roots (the wells a Type-R selection lands on) and for the branches that
#: carry a drawn flip depth.  The same spelling every module in this member
#: that joins the tree states.
NODE_TABLE = "node"

#: The node column feature 119's draw landed on — the one place a Type-D
#: assignment lives.  Read back here rather than re-derived: the gate asks
#: what the tree *carries*, and a flip depth is only knowable by reading it.
FLIP_DEPTH_COLUMN = "flip_depth"

#: §7.3's two regimes, restated as the closed set a declared campaign type
#: must be one of.  The values are the ones ``migrations/versions/
#: 0111_campaign_table.py`` documents and the planner writes, imported from
#: the modules that own each spelling so the gate and the two writers cannot
#: drift apart on what the regimes are called.
REGIMES = (TYPE_R_CAMPAIGN_TYPE, TYPE_D_CAMPAIGN_TYPE)


# -- Validation ------------------------------------------------------------------


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's key* —
    but re-raises its refusal as :class:`~nulloracle.errors.KsGuardError`,
    the same delegation and the same re-raise the fraction's, the flip
    depth's, the selection's and the resolution's stores state.  A malformed
    id handed to the *gate* is a store-contract failure, not a sidecar-
    schema one, and a caller reading ``SidecarError`` out of a plan review
    would look in the wrong module for the cause.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise KsGuardError(f"campaign_id {value!r} is not a UUID: {exc}") from exc


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    The same delegation and the same re-raise as
    :func:`_validated_campaign_id`, with the field named as the node: the ids
    a plan's two halves carry join the same key and are refused the same way.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise KsGuardError(f"node_id {value!r} is not a UUID: {exc}") from exc


def _validated_campaign_type(value: Any) -> str:
    """Refuse a declared type that is neither of §7.3's two regimes.

    §7.3 fixes exactly two campaign types — the selection test and the
    stopping test — and the gate's comparison needs a declared side to
    compare against, so a row carrying anything else is refused by name with
    the two accepted spellings, rather than guessed at.  This is deliberately
    a :class:`~nulloracle.errors.KsGuardError` and not the heterogeneous-
    world refusal: an unknown regime is not a *mix*, it is a declaration
    §7.3 does not have, and logging it under the mix's code would send an
    operator looking for a second assignment that does not exist.
    """
    if value not in REGIMES:
        raise KsGuardError(
            f"a campaign's {CAMPAIGN_TYPE_COLUMN} must be one of §7.3's two "
            f"regimes ({TYPE_R_CAMPAIGN_TYPE!r} or {TYPE_D_CAMPAIGN_TYPE!r}), "
            f"got {value!r} ({type(value).__name__}); the planning gate "
            "compares the tree's declared regime against the assignments it "
            "carries, and a declaration that is neither regime is a row no "
            "comparison could trust"
        )
    return value


def _validated_flip_depth(value: Any, node: str) -> int:
    """Refuse a stored flip depth that is not a genuine positive integer.

    The same check :mod:`nulloracle.resolution` applies on its read, with the
    node named: feature 119's draw is a geometric whose support is
    ``{1, 2, 3, …}``, and a corrupted ``0`` or a truthy-looking ``True`` in
    the column is a row the gate cannot count as a flipped branch —
    refusing it keeps a corrupt depth from either hiding a mix (by being
    skipped) or fabricating one (by being counted where no flip was drawn).
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise KsGuardError(
            f"node {node!r} carries {FLIP_DEPTH_COLUMN} {value!r} "
            f"({type(value).__name__}); the Type-D flip depth is drawn from "
            "a geometric whose support is {1, 2, 3, …} (§7.3), and the "
            "planning gate cannot count a branch as flipped on a depth "
            "nobody drew"
        )
    return value


def _sorted_node_ids(values: Any, field: str) -> tuple[str, ...]:
    """Canonicalize and sort one half's node set, refusing what is not one.

    Sorted so a plan depends on the *set* of nodes each half covers and not
    on the order a caller happened to build its collection in — the same
    order-independence :func:`nulloracle.selection.draw_null_roots` states
    for the draw — and duplicate-refusing for the same reason
    :class:`~nulloracle.selection.RootSelection` does: a node listed twice is
    not two assignments, and a plan that counted it as two would misstate
    the world it describes.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise KsGuardError(
            f"{field} must be an iterable of node ids, got "
            f"{type(values).__name__} ({values!r}); a campaign plan names the "
            "nodes each of §7.3's halves lands on, and a value that is not a "
            "collection of nodes is not a half of a plan"
        )
    canonical: list[str] = []
    for value in values:
        try:
            canonical.append(_validated_node_id(value))
        except KsGuardError as exc:
            # The field is named on the way past, not only on the collection:
            # a refusal that says only "not a UUID" leaves a caller holding
            # two halves to guess which one held the offender.
            raise KsGuardError(f"{field}: {exc}") from exc
    if len(set(canonical)) != len(canonical):
        raise KsGuardError(
            f"{field} holds a duplicate ({canonical!r}); one node is one "
            "assignment, and a plan that named it twice would misstate the "
            "world it describes"
        )
    return tuple(sorted(canonical))


def _named(values: tuple[str, ...], limit: int = 3) -> str:
    """A short human spelling of a node set, for a refusal that names names.

    The first few ids and a count of the rest, so a heterogeneous-world
    refusal identifies the offending branches without pasting a thousand
    UUIDs into a log line — the same legibility a :class:`RootSelection`
    repr buys with its counts.
    """
    shown = ", ".join(values[:limit])
    extra = len(values) - limit
    return shown + (f" (+{extra} more)" if extra > 0 else "")


# -- Feature 122: the plan as a value ---------------------------------------------


@dataclass(frozen=True)
class CampaignPlan:
    """One campaign's planned null world: the regime, and where each half lands.

    The four fields are the whole of a plan as the gate sees it:
    ``campaign_id`` (the tree the plan is for), ``campaign_type`` (§7.3's
    declared regime — the planner's own statement of which half the world
    belongs to), ``root_selections`` (the nodes a Type-R assignment lands
    on — at review, the campaign's roots §7.1's sidecar holds entries for)
    and ``flip_branches`` (the nodes a Type-D assignment lands on — at
    review, the campaign's nodes carrying a drawn ``flip_depth``).

    Frozen, so a plan that has passed the gate can never be edited into a
    mixed one by a caller who kept a reference — the same discipline
    :class:`~nulloracle.selection.RootSelection` and
    :class:`~nulloracle.resolution.TypeDResolution` state, and for the same
    reason: the value is a record of a decision, here *this tree measures
    one thing*.

    Validated in :meth:`__post_init__` — including the homogeneity check
    :meth:`_require_homogeneous` — rather than only at construction through
    a factory, because ``dataclasses.replace`` and unpickling both rebuild
    instances past a factory's nose.  A plan that exists is therefore
    homogeneous *by construction*: the mixed ones raise
    :class:`~nulloracle.errors.HeterogeneousWorldError` and never become
    values, which is what makes the store's review and a planner's proposal
    share one decision instead of two that could disagree.
    """

    campaign_id: str
    campaign_type: str
    root_selections: tuple[str, ...] = ()
    flip_branches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the
        # canonicalization below is normalization, not mutation of the
        # caller's values, and it is the only write this object ever takes.
        object.__setattr__(self, "campaign_id", _validated_campaign_id(self.campaign_id))
        object.__setattr__(
            self, "campaign_type", _validated_campaign_type(self.campaign_type)
        )
        object.__setattr__(
            self, "root_selections", _sorted_node_ids(self.root_selections, "root_selections")
        )
        object.__setattr__(
            self, "flip_branches", _sorted_node_ids(self.flip_branches, "flip_branches")
        )
        self._require_homogeneous()

    # -- Feature 122: the one decision ---------------------------------------

    def _require_homogeneous(self) -> None:
        """Refuse a plan that mixes §7.3's two regimes within one tree.

        One comparison in three shapes, and every shape is the same fact —
        this tree would measure two things:

        * **both halves present** — a root selection *and* a flip depth in
          one tree, the mix the feature's sentence names outright;
        * **a flip under a ``'Type-R'`` declaration** — the row declares the
          selection-test regime while the plan assigns a stopping-test
          branch, which is the state a mis-scripted loop leaves behind even
          with an empty sidecar;
        * **a selection under a ``'Type-D'`` declaration** — the mirror.

        Each message begins with :data:`HETEROGENEOUS_WORLD`, names the
        campaign, states the declared regime, and names the offending nodes,
        so an operator reading the refusal learns *which* half does not
        belong — not merely that something does not.
        """
        campaign = self.campaign_id
        if self.root_selections and self.flip_branches:
            raise HeterogeneousWorldError(
                f"{HETEROGENEOUS_WORLD}: the plan for campaign {campaign!r} "
                f"assigns both a {TYPE_R_CAMPAIGN_TYPE} root selection "
                f"({len(self.root_selections)} roots: "
                f"{_named(self.root_selections)}) and a "
                f"{TYPE_D_CAMPAIGN_TYPE} flip depth "
                f"({len(self.flip_branches)} branches: "
                f"{_named(self.flip_branches)}); §7.3 keeps campaigns "
                "homogeneous in null type — mixed trees make a bad FDR "
                "unattributable between selection failure and stopping "
                "failure, and a world that plants both measures neither"
            )
        if self.campaign_type == TYPE_R_CAMPAIGN_TYPE and self.flip_branches:
            raise HeterogeneousWorldError(
                f"{HETEROGENEOUS_WORLD}: the plan for campaign {campaign!r} "
                f"declares the {TYPE_R_CAMPAIGN_TYPE!r} regime yet assigns a "
                f"{TYPE_D_CAMPAIGN_TYPE} flip depth to "
                f"{len(self.flip_branches)} branches "
                f"({_named(self.flip_branches)}); a Type-R tree's null-ness "
                "is a root selection sealed in §7.1's sidecar and inherited "
                "by the whole subtree (feature 118), and a branch flip in "
                "the same tree is the second regime §7.3 holds out of it — "
                "campaigns are homogeneous in null type, so worlds measure "
                "one thing"
            )
        if self.campaign_type == TYPE_D_CAMPAIGN_TYPE and self.root_selections:
            raise HeterogeneousWorldError(
                f"{HETEROGENEOUS_WORLD}: the plan for campaign {campaign!r} "
                f"declares the {TYPE_D_CAMPAIGN_TYPE!r} regime yet assigns a "
                f"{TYPE_R_CAMPAIGN_TYPE} root selection to "
                f"{len(self.root_selections)} roots "
                f"({_named(self.root_selections)}); a Type-D tree keeps every "
                "root real and flips a branch at its drawn depth (feature "
                "119), and a root selection in the same tree is the second "
                "regime §7.3 holds out of it — campaigns are homogeneous in "
                "null type, so worlds measure one thing"
            )

    @property
    def unplanted(self) -> bool:
        """Whether the plan carries no assignment of either kind.

        The honest shape of a campaign the loop has not planted yet: the
        declaration is there and neither half has landed.  Stated as a
        property rather than left to a caller's ``not plan.root_selections
        and not plan.flip_branches`` because the gate deliberately allows it
        — *"has this tree been planted?"* is the writers' and readers'
        question, not the gate's — and a caller deserves the same word for
        it this module uses.
        """
        return not self.root_selections and not self.flip_branches

    def to_payload(self) -> dict[str, Any]:
        """The plan as a plain mapping, for a log line or an operator's report.

        The field names are the record's own, the same discipline
        :meth:`nulloracle.assignment.NullAssignment.to_payload` and
        :meth:`nulloracle.selection.RootSelection.to_payload` state: a
        rendered mapping and a structured log record name the same things the
        same way.
        """
        return {
            "campaign_id": self.campaign_id,
            "campaign_type": self.campaign_type,
            "root_selections": list(self.root_selections),
            "flip_branches": list(self.flip_branches),
        }

    def __repr__(self) -> str:
        halves = []
        if self.root_selections:
            halves.append(f"{len(self.root_selections)} selected roots")
        if self.flip_branches:
            halves.append(f"{len(self.flip_branches)} flipped branches")
        planted = " and ".join(halves) if halves else "nothing planted"
        return (
            f"{type(self).__name__}(campaign_id={self.campaign_id!r}, "
            f"campaign_type={self.campaign_type!r}, {planted})"
        )


# -- Feature 122: the store ------------------------------------------------------


class CampaignPlanGate:
    """The store that reviews one campaign's *persisted* plan for homogeneity.

    Constructed with the database URL it reads the campaign row and the tree
    from, and the :class:`~nulloracle.sidecar.NullSidecar` it reads the root
    selections from.  :meth:`review` gathers the plan the writers left
    behind — the declared type off the campaign row, the flipped branches
    off the node rows, the selected roots off §7.1's sealed file — and hands
    them to :class:`CampaignPlan`, whose own construction is the refusal.
    The store adds no second decision: it is the reader that makes the
    tree's assignments knowable, and the value is the gate.

    Both halves are required, and that is the feature's shape rather than a
    convenience.  Type-D assignment lives on ``node.flip_depth`` and Type-R
    assignment lives in the sidecar — the one artifact allowed to hold the
    bit (feature 110) — so a gate holding only the database could see flips
    but not selections, and a review that answered "homogeneous" off a store
    with no sidecar composed would bless every mixed world it was shown.  A
    deployment carrying one half without the other composes no gate rather
    than a half-gate that could only ever refuse half the mixes.

    The class resolves its database path lazily, so constructing one
    performs no I/O — composition-time work must not touch the disk, the
    contract every store in this workspace states — and the sidecar opens
    nothing until the first ``review``.  It holds no cache of the map it
    read: §7.1's file is sealed and mode-``0600`` precisely so that reading
    it is the controlled operation, and a memo would move that operation to
    the first review and hold the plaintext labels for the process's
    lifetime — the same reasoning :class:`~nulloracle.sidecar.NullSidecar`
    states from its own side.
    """

    def __init__(self, database_url: str, sidecar: NullSidecar) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(f"{DATABASE_URL_ENV} must be a non-empty database URL")
        if not isinstance(sidecar, NullSidecar):
            raise KsGuardError(
                "the planning gate reads §7.1's sidecar for the Type-R half "
                f"of a tree's plan, got {type(sidecar).__name__} ({sidecar!r}); "
                "a gate holding only the database could see flips but not "
                "selections, and would answer 'homogeneous' for worlds it "
                "never looked at"
            )
        self._database_url = database_url.strip()
        self._sidecar = sidecar
        # Resolved on first use rather than at construction: building the
        # gate is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        material: bytes | None = None,
    ) -> CampaignPlanGate | None:
        """The planning gate this environment names, or ``None`` when it names none.

        Both halves must be resolvable: a database URL (empty or
        whitespace-only counts as unset) *and* a
        :class:`~nulloracle.sidecar.NullSidecar`, which
        :meth:`~nulloracle.sidecar.NullSidecar.resolve` answers ``None`` for
        when nothing names a location or a key.  Absent is not an error: it
        is a deployment without a relational store or without a sidecar,
        which composes no gate — a discoverable state, not an exception —
        while the campaign loop that must review §7.3's homogeneity before
        it plants is the caller that must not find itself in it.

        ``material`` is threaded through to the sidecar's own resolution for
        a process that already holds the key from its backend, the same seam
        :meth:`~nulloracle.sidecar.NullSidecar.resolve` and
        :meth:`~nulloracle.selection.TypeRSelection.resolve` offer.

        **This method never raises.**  The factory builds every registered
        component on every :func:`~app.module_loader.create_app` call, so a
        builder that raised would take composition down for every unrelated
        feature in the workspace — the stance every store in this member
        states.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        sidecar = NullSidecar.resolve(source, material=material)
        if sidecar is None:
            return None
        return cls(raw, sidecar)

    @property
    def database_url(self) -> str:
        """The database URL this gate reads from."""
        return self._database_url

    @property
    def sidecar(self) -> NullSidecar:
        """The sidecar this gate reads the Type-R half of a tree's plan from."""
        return self._sidecar

    @property
    def path(self) -> Path:
        """The SQLite file backing this gate, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the node and campaign tables exist, idempotently.

        The same ``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE`` dance
        :mod:`nulloracle.resolution` states, restated here rather than
        imported so each store owns its own contract: the node table is
        created with feature 97's five structural columns, the campaign
        table with feature 104's own, and feature 119's ``flip_depth`` column
        is added by ``ALTER TABLE`` only when absent — so a fresh database, a
        migration-created one and a store-created one all end up the same
        schema and re-opening changes nothing.  No column is added beyond
        that, and in particular no ``is_null`` column ever is (feature 110).
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {NODE_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    parent_id          UUID,
                    campaign_id        UUID NOT NULL,
                    theme_root         TEXT NOT NULL,
                    depth              INT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {CAMPAIGN_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    campaign_type      TEXT NOT NULL,
                    workspace_count    INT NOT NULL,
                    null_fraction      REAL NOT NULL,
                    calibration_status TEXT NOT NULL DEFAULT 'ok',
                    ks_pvalue          REAL,
                    created_at         TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
                """
            )
            has_column = any(
                row[1] == FLIP_DEPTH_COLUMN
                for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")
            )
            if not has_column:
                connection.execute(
                    f"ALTER TABLE {NODE_TABLE} ADD COLUMN {FLIP_DEPTH_COLUMN} INT"
                )
        return connection

    # -- Feature 122: the review ---------------------------------------------

    def review(self, campaign_id: Any) -> CampaignPlan:
        """Review the plan the writers left on ``campaign_id``'s tree.

        The whole of feature 122's store half in one call: the campaign is
        confirmed to exist and its declared regime read, the branches of its
        tree that carry a drawn ``flip_depth`` are read back, the roots of
        its tree that §7.1's sidecar holds entries for are read back, and the
        four facts are handed to :class:`CampaignPlan` — whose construction
        is the gate.  A homogeneous tree returns the plan as a value (the
        caller can read what each half holds, and ``unplanted`` for a tree
        nothing has landed on yet); a mixed tree raises
        :class:`~nulloracle.errors.HeterogeneousWorldError` with the
        ``heterogeneous_world`` message naming the campaign, the declared
        regime and the offending nodes.

        Refuses, in this order, and each refusal names what it is about:

        1. a malformed ``campaign_id`` (:class:`~nulloracle.errors.KsGuardError`);
        2. a campaign the table does not hold
           (:class:`~nulloracle.errors.KsGuardError`) — the plan is a fact
           about a campaign, and reviewing a row this store invented would
           gate a world no planner designed;
        3. a declared type that is neither of §7.3's regimes, or a stored
           flip depth that is not a genuine positive integer
           (:class:`~nulloracle.errors.KsGuardError`) — rows no comparison
           could trust;
        4. a tree that mixes the two regimes
           (:class:`~nulloracle.errors.HeterogeneousWorldError`, the
           ``heterogeneous_world`` message).

        A :class:`~nulloracle.errors.SidecarStoreError`,
        :class:`~nulloracle.errors.SidecarAccessError` or
        :class:`~nulloracle.errors.SidecarDecryptionError` from the file is
        left to propagate unwrapped — the file's failures are the file's, and
        a caller must never read *"the sidecar would not open"* as *"this
        tree is homogeneous"*.  A sidecar that does not *exist* is the one
        file state that is not a failure here: the review runs at planning
        time, a deployment's first campaign has no ``sidecar.enc`` yet, and
        absent means no root selections are recorded anywhere — which is
        true, because the file is the only place they could be.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            campaign_type = self._read_campaign_type(connection, campaign)
            roots = self._read_roots(connection, campaign)
            branches = self._read_flip_branches(connection, campaign)
        selections = self._sealed_roots(roots)
        return CampaignPlan(
            campaign_id=campaign,
            campaign_type=campaign_type,
            root_selections=selections,
            flip_branches=branches,
        )

    # -- The tree -----------------------------------------------------------

    def _read_campaign_type(
        self, connection: sqlite3.Connection, campaign: str
    ) -> Any:
        """The campaign row's declared regime, read once.

        The declaration the gate compares against.  The row is created by the
        planner *before any node is expanded*, so a campaign the table does
        not hold is refused by name: a store that inserted the missing
        campaign would be inventing the declaration it is the gate's whole
        job to check.  The value itself is validated by
        :class:`CampaignPlan` rather than here — one spelling of the
        two-regime refusal, shared by the review and a caller composing a
        plan by hand.
        """
        cursor = connection.execute(
            f"SELECT {CAMPAIGN_TYPE_COLUMN} FROM {CAMPAIGN_TABLE} WHERE id = ?",
            (campaign,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"the campaign table holds no row for {campaign!r}; §7.3's "
                "homogeneity is a fact about a planned campaign's tree, and a "
                "plan that cannot be joined to the campaign it was planned "
                "for is refused rather than reviewed against a row this "
                "store would have to invent — the campaign is created by its "
                "planner, before any node is expanded"
            )
        return row[0]

    def _read_roots(
        self, connection: sqlite3.Connection, campaign: str
    ) -> tuple[str, ...]:
        """The campaign's roots — the wells a Type-R selection lands on.

        A root is a node whose ``parent_id`` is ``NULL``, the same edge
        ``migrations/versions/0118_node_table.py`` describes, and they are
        read because §7.1's map is keyed by node: a sidecar entry for a node
        that is not one of this campaign's roots belongs to another
        campaign's world and is not this tree's to count.  ``ORDER BY id``
        is stated rather than left to the engine, the same determinism every
        reader of the tree in this member states.
        """
        cursor = connection.execute(
            f"SELECT id FROM {NODE_TABLE} WHERE campaign_id = ? AND parent_id IS NULL "
            "ORDER BY id",
            (campaign,),
        )
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return tuple(sorted(_validated_node_id(row[0]) for row in rows))

    def _read_flip_branches(
        self, connection: sqlite3.Connection, campaign: str
    ) -> tuple[str, ...]:
        """The campaign's nodes carrying a drawn flip depth — the Type-D half.

        Every row of the campaign whose ``flip_depth`` is not ``NULL``, with
        the depth validated on the way past (a geometric's support cannot
        produce anything else, and a corrupted value is refused with the
        node named rather than counted).  Read from the column rather than
        re-derived because the gate asks what the tree *carries*: a flip
        depth is only knowable by reading it, and a re-derivation would be a
        second draw masquerading as a review.
        """
        cursor = connection.execute(
            f"SELECT id, {FLIP_DEPTH_COLUMN} FROM {NODE_TABLE} "
            f"WHERE campaign_id = ? AND {FLIP_DEPTH_COLUMN} IS NOT NULL "
            "ORDER BY id",
            (campaign,),
        )
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        # Validated on the way past rather than filtered on: a depth that is
        # not a genuine draw is a corrupt row to refuse with the node named,
        # not a branch to quietly drop from the count.
        branches: list[str] = []
        for identifier, depth in rows:
            _validated_flip_depth(depth, identifier)
            branches.append(_validated_node_id(identifier))
        return tuple(sorted(branches))

    # -- The sidecar --------------------------------------------------------

    def _sealed_roots(self, roots: tuple[str, ...]) -> tuple[str, ...]:
        """The campaign's roots §7.1's sidecar holds entries for.

        A root is *selected* the moment the file holds any entry for it —
        ``is_null`` true or false — because feature 118 seals **every** root
        of a Type-R campaign (the drawn ones and the rest), so the presence
        of a campaign's roots in the file is the record that a selection
        happened.  The bit itself is deliberately not read: the gate asks
        *which regime has claimed this tree*, not *which wells are null*,
        and a review that opened the bit would be answering a question the
        writers already own.

        A sidecar that does not exist answers no roots — see
        :meth:`review` for why that is a true answer at planning time and
        not a swallowed failure.  A sidecar that exists but will not open
        raises, unwrapped, because *"no selections recorded"* must never be
        the message an unopenable file leaves behind.
        """
        assignments = self._sidecar.open() if self._sidecar.exists() else {}
        return tuple(sorted(root for root in roots if root in assignments))


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract
    — the same spelling the fraction's, the flip depth's, the selection's
    and the resolution's stores state.  A non-SQLite scheme is refused
    loudly, and a pathless (in-memory) URL is refused too: an in-memory
    database dies with the connection that opened it, and a plan reviewed
    against one would be a verdict no replay could reproduce.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise KsGuardError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and a "
            "campaign's plan reviewed against one would be a verdict no "
            "replay could reproduce"
        )
    return Path(path)


def review_campaign_plan(
    campaign_id: Any,
    sidecar: NullSidecar,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CampaignPlan:
    """Review one campaign's tree for §7.3's homogeneity — the module-level spelling.

    Feature 122's sentence as one call: the campaign in, the plan the
    writers left behind out, and the mixed tree refused with the
    ``heterogeneous_world`` message.  The store is resolved from
    ``database_url``, else from ``DATABASE_URL``; a deployment that names
    neither is refused *by name* rather than silently answering a verdict,
    because a gate that quietly skipped its review would let a mixed world
    through believing it had been checked — which is the exact failure mode
    this feature exists to rule out.

    The sidecar is an argument rather than environment-resolved, for the
    same reason :func:`nulloracle.selection.persist_type_r_selection` takes
    it as one: the process that reviews a world's plan is the process that
    holds the key, and asking the environment for a key here would let a
    process that may not hold one gate worlds it cannot read.  A caller that
    wants the environment's sidecar asks :meth:`CampaignPlanGate.resolve`,
    or :meth:`~nulloracle.sidecar.NullSidecar.resolve` directly.

    A :class:`~nulloracle.errors.HeterogeneousWorldError` from the gate is
    left to propagate unwrapped — it is the feature's own refusal, and the
    caller catching it is the planner rejecting its document — while the
    store's own failures arrive as :class:`~nulloracle.errors.KsGuardError`
    and the file's own propagate unwrapped, exactly as :meth:`CampaignPlanGate.
    review` states.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise KsGuardError(
            "review_campaign_plan reviews a campaign's tree against §7.3's "
            f"homogeneity and nothing names a store: {DATABASE_URL_ENV} is "
            "unset (and no database_url was supplied), so neither half of "
            "the tree's plan could be read. A gate that silently skipped "
            "its review would let a mixed world through believing it had "
            "been checked — the exact failure this feature exists to rule out"
        )
    return CampaignPlanGate(url, sidecar).review(campaign_id)
