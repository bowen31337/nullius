"""The serving provider of every root call — feature 196's record.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 196: *System
persists the serving provider on every root-depth call routed to the rotated
frontier model tier.*  This module is feature 192's interface put to work: the
seam gives every call one normalized answer, and this one writes down **who
answered it** for the calls where that fact is not a constant.

Why roots, and why the provider rather than the model
-----------------------------------------------------

The sentence has a conditional in it — *every **root-depth** call routed to
the **rotated frontier** model tier* — and both halves of that conditional are
architecture §14.1's, not this module's invention.  §14.1's role table puts
the frontier tier on the roots row and names what it does there:

    | Signal agent, roots (depth 0–1) | ~50 | Frontier, **rotated across
    2–3 providers** | 200K | $17 |

and the paragraph under the table spends the reason:

    **Rotating providers at roots is the cheapest mitigation available**
    for the convergence failure mode.  Different model families carry
    different priors and propose structurally different mechanisms, at
    zero incremental token cost, and it hedges outages.

Two things follow from that paragraph, and together they are the whole design.

**At roots, the provider is the fact.**  Everywhere else in the system the
model is the interesting identity — feature 203 pins ``node.agent_model_id``
for exactly that reason.  At roots the tiering deliberately *does not* hold
the model fixed: it holds the **rotation** fixed, across families, because the
failure mode being hedged is a *converged tree* — *"at roots, a weak model's
failure mode is proposing the 400th variant of one indicator.  … Root
generation demands novelty under a negative constraint, which is the weakest
axis of cheap models."*  A campaign whose roots rotate across three providers
writes three different families' calls into one campaign, and the stratum the
M3 comparison is keyed on is *which family proposed this mechanism*, not
which snapshot of which line.  So the fact this module persists is the
``provider``, with the ``model`` beside it rather than in place of it: the
provider is what the rotation varies, and the model is what a reader needs to
name the family precisely.

**And the fact is a property of the call, not of the deployment.**
:mod:`providers._batch` states this hand-off from feature 201's own side, in
as many words: its routing *"does not **persist**.  Feature 196 records the
serving provider, feature 200 the measured cache-hit rate, feature 202 the
chosen run window; this feature's decision is a property of a single call, and
**the call's own record is where it would belong**."*  That is what this
module is: the call's own record.  One root call, one row, keyed by the node
that call authored — which is also why the row lives on a **member-owned
table** rather than as a column on the tree, the ``depth_run_window`` /
``depth_cache_rate`` precedent.  The row's identity is the call's, and a call
is not a node's field.

What this feature deliberately does not do
------------------------------------------

**It does not choose the rotation.**  *Which* of the declared providers serves
*this* root call is feature 197's question — *"System persists a per-campaign
root provider rotation, so different model families propose structurally
different mechanisms"* — and §14.1's rotation is a per-campaign decision made
before the calls are placed.  This module takes the **declared tier** as an
argument (:class:`FrontierTier`, the set the rotation draws from) and records
the outcome.  Sitting between them is exactly where the two sentences meet:
196 persists *what served*, 197 persists *what was assigned*, and a store that
did both would be deciding an assignment on the way to writing it down.

**It does not persist the declared tier.**  Feature 202's store persists its
premise (the pricing card the window was chosen against, so a decision can be
audited against the card that was current).  The temptation here is the same
and is refused for a specific reason: the tier is **feature 197's per-campaign
record**, and a copy of it on every root row would be a second spelling of
197's fact, written by a different feature, kept in sync by nobody.  The row
records the outcome — which provider served — and the outcome is this
feature's fact.  A reader that wants the premise asks 197 for it, by campaign
id, and gets the one record that owns it.

**It does not decide the root boundary.**  §14.1's tiering is what
*root-depth* means — roots are depth 0–1, and everything from
:data:`providers.LARGE_HISTORY_FROM_DEPTH` down is the cheap single-model tier
(FEATURE 198's).  This module declares that boundary as data
(:data:`ROOT_TIER_MAX_DEPTH`) and refuses outside it as
:class:`~providers.UnrotatedCampaignError`; it does not merely record whatever
depth it is handed, because the conditional in the sentence is what makes the
record mean something.  A store that recorded every call's provider would fill
the column with rows that all say the same thing — depth calls carry one
provider by construction — and the stratum the rotation exists to expose would
be buried among them.

The declaration, and the fact that it is *checked*
--------------------------------------------------

:class:`RootCall` carries the call's three tree facts — its node, its campaign
and its depth — and **the store verifies all three against the tree** before
it writes anything.  This is where this feature is deliberately stronger than
its neighbour: feature 199's gate had to read a *stated* served context limit
because *"the honest limit of that comparison is stated plainly rather than
papered over: **a caller can hand this gate a fabricated measurement**"* — no
independent recomputation of a remote deployment's window was available.  Here
one is: the depth and the campaign of a root call are rows of feature 97's
``node`` table, and a store that recorded a caller's *claim* about them would
be writing provenance nobody checked, which is the §14.1 failure in miniature.
So a declaration that disagrees with the tree is refused naming both values,
and a call whose node the tree does not hold is refused outright
(:class:`~providers.RootNotRecordedError`) rather than written as a row for a
mechanism nobody authored.

The three refusals and the one conflict are :mod:`providers._root_errors`'
("a **seventh** base", for the question none of the other six answers), and
the order they are raised in is the order the facts become checkable:

1. **shape** — the call's parts, the tier's parts, the serving provider's
   parts, each re-made from this module's classes.  A malformed description is
   the base :class:`~providers.RootProviderError`, on the grounds
   :mod:`providers._root_errors` states for its own trivia.
2. **is the declared call a root call?** — the caller's own description, the
   cheapest refusal and the first one that can be made
   (:class:`~providers.UnrotatedCampaignError`).
3. **does the tier declare the serving provider?** — the membership question,
   answered **before any database is opened**, so a call the rotation does not
   cover is refused without touching a file
   (:class:`~providers.UnknownRootProviderError`).
4. **does the tree hold the node, and does it agree?** — the probe, read-only,
   then the campaign and the depth compared against the declaration; a root
   boundary the tree itself places the node outside of is
   :class:`~providers.UnrotatedCampaignError` again, this time from the fact rather
   than from the claim.
5. **has this root call already been recorded?** — the identical record
   answers the stored row (``recorded=False``, the original ``recorded_at``,
   which a retry does not move); a *different* provider against the same root
   is :class:`~providers.RootProviderConflictError`, naming both.

The answer is :class:`RootCallProvider` — the call, the provider, the model,
the instant, and ``recorded``, the this-call's-answer-state flag
:class:`providers.MeasuredCacheRate` and :class:`providers.ScheduledRun` carry
for the same reason.

Why the record is recognised by parts, and not by class
------------------------------------------------------

Everything crossing this module's seam — the call, the tier, the serving
provider — is recognised **by its parts** and **re-made from this module's
classes**.  The workspace's module loader imports every member twice (once by
file path under ``_nullius_scanned_<dir>``, once as the importable member), so
two ``RootCall`` classes exist over one source file and a dataclass's
generated ``__eq__`` answers ``False`` between them for every value.  An
``isinstance`` gate would refuse the very record the caller legitimately built
from the member, and a pass-through would return a value still carrying the
other class — silently unequal to every record this module's answer is
compared against.  Recognition by shape, answers in one class: the move
:func:`providers.require_agent_model_id`, :func:`providers.require_depth_model`
and :func:`providers.require_served_context` each make for their own seam, for
the same reason.

Stdlib-only, like the rest of this tree: this module holds a declared set of
providers, a node's three tree facts and the instant a row was written, and it
dials nothing.  Which provider actually answered is feature 192's completion,
read by the caller that placed the call.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ._root_errors import (
    RootNotRecordedError,
    RootProviderConflictError,
    RootProviderError,
    UnknownRootProviderError,
    UnrotatedCampaignError,
)

__all__ = [
    "CAMPAIGN_ID_COLUMN",
    "DATABASE_URL_ENV",
    "DEPTH_COLUMN",
    "MODEL_COLUMN",
    "NODE_TABLE",
    "NODE_TABLE_ID_COLUMN",
    "NODE_TABLE_REVISION",
    "RECORDED_AT_COLUMN",
    "ROOT_SERVING_PROVIDER_TABLE",
    "ROOT_TIER_MAX_DEPTH",
    "SERVING_PROVIDER_COLUMN",
    "FrontierProvider",
    "FrontierTier",
    "RootCall",
    "RootCallProvider",
    "RootProviderRotation",
    "record_root_provider",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the null oracle's
#: seven, the bootstrap pool's, the campaign planner's, the pin store's, the
#: run-window store's, the cache-rate store's), restated here so this store
#: states its own contract and imports nobody else's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the recorded serving providers land in — **this member's own**,
#: created lazily by the store and by nobody else, on the ``bootstrap_world`` /
#: ``depth_run_window`` / ``depth_cache_rate`` precedent (a member-owned table
#: for a member-owned fact, no edit to the shared migration chain).  Contrast
#: :data:`NODE_TABLE` below, which is a core migration's and is probed
#: read-only.
ROOT_SERVING_PROVIDER_TABLE = "root_serving_provider"

#: The discovery tree's node table — feature 97's, created by
#: ``migrations/versions/0118_node_table.py``, its rows written by the
#: discovery loop (feature 239 expands a selected node).  Probed **read-only**
#: here for two questions — *was this root authored?* and *what campaign and
#: depth does the tree place it at?* — through ``sqlite_master`` and one
#: ``SELECT``, and never created: the probe-not-create discipline
#: :mod:`providers._pin_store` follows from this same table's other side, and
#: :mod:`providers._schedule` and :mod:`providers._cache` follow for the
#: campaign table's.
NODE_TABLE = "node"

#: The column the node table's rows are keyed by — ``0118``'s ``id``, the
#: identity feature 102's dedup index and every ``node_id`` in every
#: downstream request resolve back to.  Spelled here so the probe's ``SELECT``
#: and its refusal name the column the migration owns, not a local invention.
NODE_TABLE_ID_COLUMN = "id"

#: The revision that creates the node table, named in
#: :class:`~providers.RootNotRecordedError`'s message so an operator reading it
#: learns which repair applies — the same role
#: :data:`providers.MODEL_PIN_REVISION` plays for the authoring-model trio.
NODE_TABLE_REVISION = "0118_node_table"

#: The recorded row's key: the node the root call authored, as canonical UUID
#: text.  **One root call is one node**, so one row per node — the whole
#: idempotence story of :class:`RootProviderRotation` hangs off this key.
NODE_ID_COLUMN = "node_id"

#: The campaign the call belongs to — feature 104's ``campaign.id``, the value
#: every tree query in the system is already scoped by.  Carried on the row as
#: well as derivable from the node because the record is meant to be readable
#: **without** the tree: the row is the fact this feature vouches for, and a
#: reader that had to join feature 97's table to learn which campaign a
#: provenance row belongs to would be reading two stores to answer one
#: question.  ``NOT NULL``, no foreign key: the reference is enforced by the
#: writer, the same way ``0118``'s own ``campaign_id`` states it.
CAMPAIGN_ID_COLUMN = "campaign_id"

#: The depth the call was placed at, carried for the same
#: readable-without-the-tree reason and because it is the fact the sentence's
#: conditional turns on: a row at depth 0 or 1 is a root call, and a row whose
#: depth is anything else would be a record this feature's gate does not
#: produce.  :class:`RootCallProvider` re-states that law on the record, so a
#: row that contradicts it cannot be read back as a root call's provenance.
DEPTH_COLUMN = "depth"

#: The provider that **served** the call — the fact this feature exists for.
#: It is the *serving* provider and not the asked-for one: §14.1's rotation may
#: have changed it from what the caller requested, which is why feature 192's
#: completion reports its own author — *"It is the model that **served** the
#: answer, which a tiering or rotation layer may change from what the caller
#: asked for — so it is reported, not assumed."*
SERVING_PROVIDER_COLUMN = "provider"

#: The model of that provider's line that served the call — the second half of
#: naming the family precisely.  It is not the fact the rotation varies (the
#: provider is), so it is carried beside it rather than in place of it.
MODEL_COLUMN = "model"

#: The instant the record was written — writer-stamped, no engine ``DEFAULT``
#: (the bootstrap pool's ground: a caller-stamped column never meets SQLite's
#: ``DEFAULT`` grammar, so there is no dialect split to carry).
RECORDED_AT_COLUMN = "recorded_at"

#: The deepest node §14.1 still calls a **root** — the boundary the sentence's
#: *root-depth* conditional is read off.  §14.1's role table writes it as the
#: frontier row's own size (*"Signal agent, roots (depth 0–1)"*) and puts
#: everything deeper on one cheap model, which is why
#: :data:`providers.LARGE_HISTORY_FROM_DEPTH` is ``2``: the two constants are
#: one boundary written from each side, exactly as §14.1's table writes both
#: rows.  Declared as data because the refusals quote it — a caller told *root
#: depth* is told which calls the record is for — and pinned against
#: ``LARGE_HISTORY_FROM_DEPTH`` **by the suite** rather than by an import, the
#: seat's own device for two spellings that must not drift and must not be one
#: constant shared across features.
ROOT_TIER_MAX_DEPTH = 1

#: The parts a frontier-tier member is recognised by, in declaration order —
#: duck typing across the module loader's double import (see the module
#: docstring), the same tuple :mod:`providers._cache` declares for its card
#: entries and :mod:`providers._pinning` for its triple.
_PROVIDER_PARTS: tuple[str, ...] = ("provider", "model")

#: The one part a declared tier is recognised by: the members it rotates
#: across.  A single part rather than ``_PROVIDER_PARTS`` because the tier *is*
#: its collection — the same shape :mod:`providers._cache` gives
#: :class:`providers.CachePricing` (``("prices",)``).
_TIER_PARTS: tuple[str, ...] = ("providers",)

#: The parts a root call is recognised by — exactly the three tree facts the
#: record carries: which node the call authored, which campaign it belongs to
#: and how deep it was placed.  A caller holding the node row itself satisfies
#: this tuple, which is the point: the seam reads what it needs and does not
#: ask a caller to re-wrap a node it already has (the duck-typed discipline
#: feature 184's policy question seam uses for its cells).
_CALL_PARTS: tuple[str, ...] = ("node_id", "campaign_id", "depth")

#: The read-only probe that answers *does this database hold this table?* —
#: ``sqlite_master`` is read (never the rows), which makes the check safe on a
#: database this process has no business writing to; the idiom
#: :mod:`providers._pin_store`, :mod:`providers._schedule` and
#: :mod:`providers._cache` all use.  Parameterised, so the table name is a
#: bound value rather than interpolated text.
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"

#: The member-owned table, in one idempotent statement.  Every column is
#: ``NOT NULL`` — a record is written whole or not at all, and a row with a
#: node but no provider, or a provider but no instant, is half a record no
#: auditor could act on.  The key carries ``NOT NULL`` explicitly beside
#: ``PRIMARY KEY`` for the reason ``0111``'s docstring spells: SQLite accepts
#: NULL — and several — in a bare ``PRIMARY KEY``, and a second NULL-keyed row
#: would split one root call's provenance from the node it authored.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {ROOT_SERVING_PROVIDER_TABLE} (
    {NODE_ID_COLUMN}          TEXT NOT NULL PRIMARY KEY,
    {CAMPAIGN_ID_COLUMN}      TEXT NOT NULL,
    {DEPTH_COLUMN}            INTEGER NOT NULL,
    {SERVING_PROVIDER_COLUMN} TEXT NOT NULL,
    {MODEL_COLUMN}            TEXT NOT NULL,
    {RECORDED_AT_COLUMN}      TEXT NOT NULL
)
"""


# ── The configuration: the declared frontier tier ─────────────────────────────


@dataclass(frozen=True)
class FrontierProvider:
    """One member of the rotated frontier tier — a provider and a model.

    The unit §14.1's rotation draws from: ``provider`` — *whose* service — and
    ``model`` — which of that provider's line is in the frontier tier.  Only
    two fields, because those are the two facts a rate card's roots row states
    and a rotation has to name; the window, the price and the batch offering
    all belong to the roles that read them, and a card entry that carried them
    would be a fourth spelling of §14.2's table.

    The same record is offered both as a **declaration** (a member of
    :class:`FrontierTier`) and as an **observation** (what the caller read off
    feature 192's completion).  That is deliberate and is the
    :class:`providers.DepthModel` / :class:`providers.CachePrice` arrangement
    seen from the other side: a selection's candidates and its answer are the
    same type, because *the set of things that could be chosen* and *the thing
    that was chosen* are described by the same facts.  Here it is stronger
    still — the serving provider of a frontier-tier call is *by the tier's own
    definition* one of its members, so the gate between them is membership
    rather than a comparison, and offering one record for both makes that gate
    a single ``in``.

    Construction validates shape only — two non-empty names — and **does not**
    check membership in any tier: describing a provider is not serving a call
    with it, the same split :class:`providers.DepthModel` states for a 262K
    window (*"a 262K-window candidate constructs happily and only feature 198's
    gate refuses it"*).  This module records a lot of frontier tiers; a record
    that refused a provider outside one deployment's declaration would be
    refusing a fact about another's.

    Frozen and value-equal, so a tier a suite built compares equal to the tier
    a caller holds — the same testability every record in this package gets
    from being a value type.
    """

    provider: str
    model: str

    def __post_init__(self) -> None:
        # Field by field in declaration order, so an entry malformed in two
        # places is refused for the first one a reader would meet — the same
        # ordering :class:`providers.ModelPin` uses for its own parts.
        object.__setattr__(
            self, "provider", _require_name(self.provider, "provider")
        )
        object.__setattr__(self, "model", _require_name(self.model, "model"))

    def text(self) -> str:
        """The member's canonical ``"provider:model"`` spelling.

        The form refusals quote and humans read; the same role
        :meth:`providers.BatchEndpoint.text` and
        :meth:`providers.PeakWindow.text` play for their own records.  A
        colon, not feature 203's ``/``: a slash-joined pair is that feature's
        two-part *rolling alias* — *"worse, not better: it names a model line
        without the snapshot"* — and a rendering that read like one would
        invite a reader to take a tier member for a pin.  The two records are
        different questions about the same call (who served it, versus which
        authoring triple wrote the node) and their spellings must not blur.
        """
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class FrontierTier:
    """The frontier tier a campaign's roots rotate across — the configuration.

    *"Frontier, rotated across 2–3 providers"*, spelled as the set the rotation
    draws from.  §14.2's own roots row names three — ``claude-opus-5``,
    ``gpt-5.6-sol``, ``gemini-3.1-pro``, *"Rotate all three.  Different
    families, different priors, different mechanisms proposed"* — and **none of
    those names appears in this module**, for the reason §14.2's preamble
    states about its own numbers: *"rates move monthly … the selection logic is
    stable, the numbers are not."*  A model that was frontier in September is
    not the one that is frontier in December, so the tier is stated by whoever
    configures the deployment and this module holds only its shape.

    **A tier of one is a legitimate statement and is admitted.**  §14.1's target
    is two to three families, and a deployment that has added only its first
    one is a real state — a store that refused to record that deployment's root
    calls would leave its first campaign with no provenance at all, which is
    the opposite of what this feature is for.  The tier *describes*; whether a
    rotation is diverse enough is judged by the metric §14.1 names for it
    (``tree_diversity``, feature 215), not by a constructor.

    **An empty tier is refused**, and it is the one configuration this module
    will not hold: a tier with no members declares that the campaign rotates
    across nobody, so *every* call's membership check fails and the record this
    feature exists to write can never be written for it.  That is not a
    configuration with an unusual shape — it is a contradiction between the
    tier and the sentence, and it is refused where it is stated rather than
    once per call.

    Entries are canonicalised into sorted order on construction (by
    ``(provider, model)``), so two tiers configured with the same members in
    different orders are **equal values** — the discipline
    :class:`providers.CachePricing` and :class:`providers.PeakPricing` keep,
    and what makes a membership check and a suite's comparison of two cards
    meaningful.  A duplicate member is refused: the same provider's same model
    twice is one family stated twice, and a tier that held it would report a
    rotation where there is none.

    Frozen and value-equal for the reasons this package's other records are:
    a tier is a fact about a deployment's configuration, not a field a caller
    tunes.
    """

    providers: tuple[FrontierProvider, ...]

    def __post_init__(self) -> None:
        entries = _require_members(self.providers)
        member = tuple(
            sorted(entries, key=lambda entry: (entry.provider, entry.model))
        )
        seen: set[tuple[str, str]] = set()
        for entry in member:
            key = (entry.provider, entry.model)
            if key in seen:
                raise RootProviderError(
                    f"the frontier tier declares {entry.text()!r} twice: one "
                    "provider's one model is one family, and a tier that held "
                    "it twice would report a rotation across two members where "
                    "there is one — which is the contrast feature 197's "
                    "sentence spends and the stratum §14.1's root rotation is "
                    "read for. State each member once."
                )
            seen.add(key)
        if not member:
            raise RootProviderError(
                "a frontier tier must declare at least one provider: the "
                "tier is the set feature 196 checks a root call's serving "
                "provider against, and a tier with no members declares that "
                "the campaign rotates across nobody — every call would be "
                "refused by the membership check, so no root call's provider "
                "could ever be recorded for it. Configure the tier the "
                "campaign's roots actually rotate across (architecture §14.1: "
                "'Frontier, rotated across 2–3 providers'), or do not record "
                "root provenance for this campaign at all."
            )
        object.__setattr__(self, "providers", member)

    def text(self) -> str:
        """The tier's canonical spelling — its members, comma-separated.

        The form the refusals quote and a card's rendering reads, in the
        sorted canonical order construction imposed so one tier has one
        spelling.
        """
        return ",".join(entry.text() for entry in self.providers)

    def __contains__(self, item: object) -> bool:
        """Whether the tier declares ``item`` — membership, across both copies.

        Spelled as ``in`` so the gate reads as the sentence does (*is this
        serving provider one the tier declares?*), and asking it here rather
        than in the store keeps the one place a tier's contents are read.

        The comparison goes through :func:`_member_from_parts` rather than
        through the tuple's own ``in``, which would compare with the generated
        ``__eq__``: a member built from the workspace's *other* copy of this
        module is a different class with an ``__eq__`` that answers ``False``
        for every value, so a plain ``in`` would refuse a provider this tier
        plainly declares — and the caller would be told its serving provider is
        undeclared by a tier that names it.  Recognising by parts and comparing
        the parts is the same remedy every seam in this package makes; here it
        is what makes the gate's answer independent of *which* import a caller
        reached the member through.
        """
        try:
            observed = _member_from_parts(item, "a tier's membership check")
        except RootProviderError:
            # A value that is not a member at all is not in the tier: asking
            # *is this declared?* about something that declares no provider is
            # answered by the question rather than by a refusal, and the
            # membership test is used in a caller's ``if`` where raising would
            # be the wrong shape.
            return False
        return any(
            member.provider == observed.provider
            and member.model == observed.model
            for member in self.providers
        )


# ── The call ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RootCall:
    """One root call's three tree facts — which call a record is about.

    The identity of the call and the two facts the sentence's conditional
    turns on: ``node_id`` — the node the call authored, which is the recorded
    row's key — ``campaign_id`` — the campaign the node belongs to — and
    ``depth`` — how deep the tree placed it, root depth being 0 or 1.

    All three are the **caller's declaration**, and all three are **verified
    against the tree** before :meth:`RootProviderRotation.record` writes
    anything.  That is deliberate and it is where this feature is stronger than
    its nearest neighbour: :mod:`providers._served` had to accept a *stated*
    measurement because no independent recomputation of a remote deployment's
    served window existed (*"a caller can hand this gate a fabricated
    measurement"*), while here the tree holds the campaign and the depth of
    every node.  A store that recorded the claim without checking it would be
    writing provenance nobody verified, which is the §14.1 failure in
    miniature — a row whose two fields a reader has to take on faith is not a
    provenance record at all.

    Construction validates **shape only** — two UUIDs and a non-negative
    integer — and deliberately does **not** apply the root boundary to
    ``depth``.  The split is feature 198's: a 262K-window candidate constructs
    happily and only the gate refuses it, because *describing* a thing is not
    *serving* a call with it.  A depth-5 call is a perfectly real call and a
    caller may describe it; what it is not is a call this feature's record
    covers, and that refusal belongs to the gate.

    Frozen and value-equal, so a call a suite builds compares equal to the one
    the recorder was handed.
    """

    node_id: str
    campaign_id: str
    depth: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _validated_node_id(self.node_id)
        )
        object.__setattr__(
            self, "campaign_id", _validated_campaign_id(self.campaign_id)
        )
        object.__setattr__(self, "depth", _require_depth(self.depth, "a call's depth"))

    def row(self) -> dict[str, Any]:
        """The call as a store-shaped mapping — a fresh dict per call.

        The column names are this module's own, the discipline
        :meth:`providers.ScheduledRun.row` states.  Offered so a caller
        recording a call's provenance has one spelling of the three tree
        facts, rather than for a store in this package — the store writes its
        own row.
        """
        return {
            NODE_ID_COLUMN: self.node_id,
            CAMPAIGN_ID_COLUMN: self.campaign_id,
            DEPTH_COLUMN: self.depth,
        }


# ── The answer ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RootCallProvider:
    """The provider that served one root call, and the row it was written to.

    The row's facts as one value: the ``node_id`` the call authored (the key),
    the ``campaign_id`` and ``depth`` the tree placed it at, the
    ``provider`` that served it and the ``model`` of that provider's line, the
    ``recorded_at`` instant the row was written, and ``recorded`` — this call's
    answer state, the same field :class:`providers.MeasuredCacheRate` and
    :class:`providers.ScheduledRun` carry: ``True`` when the call that returned
    this record wrote the row, ``False`` when it answered the row that was
    already there (an idempotent retry, or any read from
    :meth:`RootProviderRotation.get`, which never writes).

    The depth is carried here **and** re-verified on construction: this record
    only exists past feature 196's gate, so a depth above
    :data:`ROOT_TIER_MAX_DEPTH` names a row the gate does not produce, and
    reading it back as a root call's provenance would launder a depth call's
    record into the table a rotation's stratification is read from — the
    derived-not-stored discipline :class:`providers.VerifiedServedContext`
    keeps for its own gate, applied to the boundary rather than to a margin.

    :attr:`serving_provider` is derived, never stored: the same two names as a
    :class:`FrontierProvider`, built fresh on each read, so a caller can offer
    the observed member back to a tier's membership check without re-assembling
    it — the :attr:`providers.NodePin.pin` move, for the same reason.

    Frozen, so a record that has been read back cannot be edited into a
    different provenance by a caller who kept a reference.
    """

    node_id: str
    campaign_id: str
    depth: int
    provider: str
    model: str
    recorded_at: datetime
    recorded: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _validated_node_id(self.node_id))
        object.__setattr__(
            self, "campaign_id", _validated_campaign_id(self.campaign_id)
        )
        object.__setattr__(
            self, "depth", _require_depth(self.depth, "a root call's depth")
        )
        object.__setattr__(
            self, "provider", _require_name(self.provider, "provider")
        )
        object.__setattr__(self, "model", _require_name(self.model, "model"))
        object.__setattr__(
            self,
            "recorded_at",
            _require_instant(self.recorded_at, "a recorded instant"),
        )
        object.__setattr__(
            self, "recorded", _require_recorded(self.recorded)
        )
        if self.depth > ROOT_TIER_MAX_DEPTH:
            raise RootProviderError(
                f"the root-call record for node {self.node_id!r} carries depth "
                f"{self.depth}, and a root call is at depth "
                f"{ROOT_TIER_MAX_DEPTH} or above (architecture §14.1: 'Signal "
                f"agent, roots (depth 0–1)'). This record only exists past "
                "feature 196's gate, so the row was not produced by it — and "
                "reading it back as a root call's provenance would launder a "
                "depth call's record into the table the rotation's "
                "stratification is read from, where every row is supposed to "
                "name a family that was chosen for novelty rather than a model "
                "that was chosen for price."
            )

    @property
    def serving_provider(self) -> FrontierProvider:
        """The observed member as the tier's own value type.

        Derived from the two names the row carries and never stored beside
        them: the row is a provider and a model, and this is that pair offered
        back in the shape a tier's membership check reads.  A caller that wants
        to ask *is the family that served this root still declared?* therefore
        assembles nothing.
        """
        return FrontierProvider(provider=self.provider, model=self.model)

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline
        :meth:`providers.ScheduledRun.row` states: a rendered mapping names the
        same things the same way the store does.  ``recorded`` is deliberately
        absent — it is this call's answer state, not a fact of the row.
        """
        return {
            NODE_ID_COLUMN: self.node_id,
            CAMPAIGN_ID_COLUMN: self.campaign_id,
            DEPTH_COLUMN: self.depth,
            SERVING_PROVIDER_COLUMN: self.provider,
            MODEL_COLUMN: self.model,
            RECORDED_AT_COLUMN: _format_instant(self.recorded_at),
        }


# ── The persistence ───────────────────────────────────────────────────────────


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning canonical UUID text.

    The same canonicalization :func:`providers._pin_store._validated_node_id`
    and :func:`providers._schedule._validated_campaign_id` apply, restated
    rather than imported (each store states its own contract): the value joins
    feature 97's ``node.id`` primary key, so a mixed-case key would make one
    root call look like two and the row would be written beside the node it
    belongs to rather than on it.  There is no ``None`` case here to let a
    table mint — a record of a call with no node names no mechanism whose
    author could be named.
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
    raise RootProviderError(
        f"node_id {value!r} is not a UUID; a serving provider is recorded for "
        "the root call that authored a node, and the node's id is the value "
        f"{NODE_TABLE}.{NODE_TABLE_ID_COLUMN} holds and every reader of this "
        "row joins by — an id that cannot join it names no call whose provider "
        "could be recorded"
    )


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning canonical UUID text.

    The same canonicalization every store in this member applies, restated for
    the same reason as :func:`_validated_node_id`.  The campaign is carried on
    the row so a reader can fetch one campaign's root provenance without
    joining the tree, and a mixed-case key would split that read in two.
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
    raise RootProviderError(
        f"campaign_id {value!r} is not a UUID; a root call's provider is "
        "recorded within the campaign whose tree the call belongs to, and the "
        f"campaign's id is the value {NODE_TABLE}.{CAMPAIGN_ID_COLUMN} holds "
        "and every reader of this row joins by — an id that cannot join it "
        "names no campaign whose roots could be stratified"
    )


def _require_name(value: object, field: str) -> str:
    """Return ``value`` as a non-empty stripped name, refusing anything else.

    One guard for the two names this module handles — a provider's and a
    model's — because they fail the same way and owe the caller the same
    explanation.  Whitespace is stripped rather than preserved, the rule
    :func:`providers._batch._require_provider_name` states for its own names:
    the name is a **lookup key** — it is matched against a tier's declarations
    — so ``' anthropic '`` and ``'anthropic'`` must be one provider, and a
    value that kept its padding would be refused by a membership check it
    should have passed.
    """
    if not isinstance(value, str):
        raise RootProviderError(
            f"a frontier member's {field} must be a string, got {value!r} "
            f"({type(value).__name__}). The tier is a set of named providers "
            "and a call's serving provider is matched against it by name, so a "
            "value that is not a name cannot be looked up in one."
        )
    text = value.strip()
    if not text:
        raise RootProviderError(
            f"a frontier member's {field} must be a non-empty name, got "
            f"{value!r}. A blank name is not a provider and not a model: it "
            "would match nothing in a declared tier, so the root call it "
            "describes could never be admitted — and a provenance row reading "
            "'served by \"\"' is a row that names no author at all, which is "
            "the state this feature exists to end."
        )
    return text


def _require_depth(value: object, what: str) -> int:
    """Return ``value`` as a non-negative depth, refusing anything else.

    ``bool`` is refused by identity beside ``int`` for the reason
    :func:`providers._batch._require_availability` refuses it: ``bool`` is a
    subclass of ``int``, so ``True`` would otherwise be admitted as depth 1 —
    a root depth — and a caller that passed a flag where a depth belongs would
    have it recorded as a fact about the tree.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RootProviderError(
            f"{what} must be an int, got {value!r} ({type(value).__name__}). "
            "The depth is the number feature 97's node table stores and "
            "architecture §14.1's tiering is read off — a value that is not a "
            "depth cannot be compared with the root boundary, and guessing an "
            "interpretation would be placing a call in a tier nobody checked."
        )
    if value < 0:
        raise RootProviderError(
            f"{what} must be non-negative, got {value:,}. Depth zero is a "
            "root; there is no shallower node for a negative depth to name, so "
            "the value is a malformed description rather than a call placed "
            "above the boundary."
        )
    return value


def _require_recorded(value: object) -> bool:
    """Return ``value`` as the answer-state flag, refusing anything else.

    A strict ``bool`` by identity, for the reason
    :func:`providers._batch._require_availability` and
    :func:`providers._served._require_verified` check it that way: a record
    whose state flag is ``0`` or ``None`` would read as falsy in a caller's
    branch while asserting nothing, and *did this call write the row?* is a
    question whose answer must be stated rather than coerced.
    """
    if value is not True and value is not False:
        raise RootProviderError(
            f"a root-call record's recorded must be True or False, got "
            f"{value!r} ({type(value).__name__}). The flag says whether the "
            "call that returned the record wrote the row or answered one "
            "already there, and a value that is neither is a state no caller "
            "could branch on."
        )
    return value


def _require_instant(value: object, what: str) -> datetime:
    """Return ``value`` as an aware UTC ``datetime``, refusing the rest.

    The same split every store in this member makes: aware datetimes of any
    offset are accepted and converted — an instant is an instant — while naive
    ones are refused by name, because a naive value names no instant and a
    record stamped with it could not be placed on any timeline an auditor
    reads beside the campaign's other records.
    """
    if not isinstance(value, datetime):
        raise RootProviderError(
            f"{what} must be a datetime, got {value!r} "
            f"({type(value).__name__}). A record is written at an instant, and "
            "a value that is not an instant cannot be one."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise RootProviderError(
            f"{what} must be timezone-aware, got {value!r}: a naive datetime "
            "names no instant, and stamping a record with one would leave a "
            "root call's provenance that cannot be placed on the timeline the "
            "campaign's own records keep time on."
        )
    return value.astimezone(UTC)


def _format_instant(moment: datetime) -> str:
    """An instant as the spine's ISO-8601 UTC text — ``0111``'s own spelling.

    ``%Y-%m-%dT%H:%M:%S`` plus a three-digit millisecond field and a ``Z``,
    byte-for-byte the form SQLite's
    ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` writes for the campaign table's
    ``created_at`` — restated here (not imported from :mod:`providers._schedule`
    or :mod:`providers._cache`) on the ground those modules state themselves:
    each store owns its own column spellings.  The milliseconds are written by
    hand because ``strftime``'s ``%f`` is six digits and the spine's is three.
    """
    utc = moment.astimezone(UTC)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"


def _parse_instant(text: object, node: str, column: str) -> datetime:
    """Read back the row's instant, refusing a value that is not one.

    The read path's one instant parser, so ``record``'s read-back and ``get``
    cannot disagree about the form.  Anything the spine's spelling round-trips
    is accepted; anything else — text another dialect wrote, a truncated
    column, an editing accident — is refused naming the node and the column,
    because a row whose instant does not parse is one this feature cannot
    report.
    """
    if not isinstance(text, str) or not text.strip():
        raise RootProviderError(
            f"the root-call record for node {node!r} carries {column} "
            f"{text!r}, which is not an ISO-8601 UTC instant. The row was not "
            "written by this feature — its instant column is the spine's own "
            "timestamp text, and one that does not parse is a row this record "
            "cannot report."
        )
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise RootProviderError(
            f"the root-call record for node {node!r} carries {column} "
            f"{text!r}, which does not parse as an ISO-8601 instant. The row "
            "was not written by this feature, and an instant that cannot be "
            "read is a record this feature cannot report."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RootProviderError(
            f"the root-call record for node {node!r} carries {column} "
            f"{text!r} without a UTC offset: it names no instant, and a record "
            "that names no instant cannot be placed beside the campaign's own "
            "records on any timeline."
        )
    return parsed.astimezone(UTC)


def _parse_text(value: object, node: str, column: str) -> str:
    """Read back one of the row's name columns, refusing a value that is not one.

    The read path's one text parser, for both the provider and the model
    column (SQLite answers ``TEXT`` affinity for a well-formed column and an
    integer or a float for one that was not written by this feature).  A
    name that is not a string is refused naming the node and the column rather
    than coerced: a row's provider is the fact this feature exists for, and
    ``str(row[3])`` would launder a column an editing accident turned into a
    number into a provider nobody served from.
    """
    if not isinstance(value, str):
        raise RootProviderError(
            f"the root-call record for node {node!r} carries {column} "
            f"{value!r} ({type(value).__name__}), which is not the text this "
            "feature writes. The row was not written by this feature — its "
            "name columns are strings — and a provider that is not a name is a "
            "record this feature cannot report."
        )
    return _require_name(value, column)


def _parse_depth(value: object, node: str, column: str) -> int:
    """Read back the row's depth, refusing a value that is not one.

    The read path's one depth parser.  SQLite's ``INTEGER`` affinity answers an
    integer for a well-formed column and a float or text for one that was not
    written by this feature, and either is refused naming the node and the
    column rather than coerced — the discipline
    :func:`providers._cache._parse_count` keeps for its own counts.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RootProviderError(
            f"the root-call record for node {node!r} carries {column} "
            f"{value!r} ({type(value).__name__}), which is not the integer "
            "depth this feature writes. The row was not written by this "
            "feature — its depth column is an integer — and a depth that is "
            "not a depth is a record this feature cannot report."
        )
    return _require_depth(value, f"the {column} recorded for node {node!r}")


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The convention every store in this workspace uses, restated here so this
    store states its own contract and the refusal is this module's own error
    class.  A non-SQLite scheme is refused by name (the spec's single-machine
    allowance is what a stdlib store can speak), and an in-memory URL is
    refused too: a root call's provenance must outlive the recording call — the
    stratification that reads it and the auditor that re-derives it run in
    another process entirely.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RootProviderError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the tree already "
            "lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RootProviderError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RootProviderError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened it, "
            "and a root call's serving provider must outlive the recording "
            "call — the stratification §14.1's rotation is read for and the "
            "auditor that re-derives it both read it in another process"
        )
    return Path(path)


def _member_from_parts(value: object, what: str) -> FrontierProvider:
    """Re-make one frontier member from its parts, refusing anything else.

    Recognition is structural — the two attributes :data:`_PROVIDER_PARTS`
    names, read on ``object.__getattribute__`` — rather than by class, because
    the module loader gives every member two class objects over one source
    file (see the module docstring).  ``object.__getattribute__`` rather than
    ``getattr`` so an arbitrary object's ``__getattr__`` cannot fabricate a
    member: this function decides what may be matched against a declared tier,
    and a hook that answered two names would be a hook that offered a serving
    provider.

    The parts are read whatever their types and handed to the constructor,
    which refuses a malformed one precisely — a stub carrying ``provider=7`` is
    told its provider is not a string, not that it is "not a frontier member" —
    so recognition stays cheap and the validation stays single-sourced.
    """
    if isinstance(value, FrontierProvider):
        # Fast path and the same answer either way: re-made below, so the
        # returned value is always this module's class.
        parts = (value.provider, value.model)
    else:
        try:
            parts = tuple(
                object.__getattribute__(value, part) for part in _PROVIDER_PARTS
            )
        except AttributeError:
            raise RootProviderError(
                f"{what} must be a FrontierProvider "
                f"({', '.join(_PROVIDER_PARTS)}), got {value!r} "
                f"({type(value).__name__}). A root call's serving provider is "
                "the pair architecture §14.1's rotation varies — whose service "
                "answered, and which model of that provider's line — and a "
                "value that is not the record carries neither half, so there "
                "is no membership for the tier to check."
            ) from None
    return FrontierProvider(provider=parts[0], model=parts[1])


def _require_members(value: object) -> tuple[FrontierProvider, ...]:
    """Return ``value`` as the tier's members, refusing anything else.

    The tier's one collection guard.  A bare string is refused **before** the
    iteration, because a ``str`` is iterable and would otherwise be read as one
    member per character — a failure mode that produces a tier of nonsense
    rather than a refusal, and the one case where "it iterates" is the wrong
    question.  A mapping is refused too: the keys of a provider-to-something
    dict are a plausible mis-spelling of a tier, and reading them would be
    guessing which half of the caller's structure was meant.
    """
    if isinstance(value, (str, bytes, Mapping)):
        raise RootProviderError(
            f"a frontier tier's providers must be a collection of "
            f"FrontierProvider entries, got {value!r} "
            f"({type(value).__name__}). Feature 196 checks a root call's "
            "serving provider against the tier's declarations, and a value "
            "that is itself a single string or a mapping is not a collection "
            "of them — reading it as one would build a tier nobody declared."
        )
    if not isinstance(value, Iterable):
        raise RootProviderError(
            f"a frontier tier's providers must be a collection of "
            f"FrontierProvider entries, got {value!r} "
            f"({type(value).__name__}), which is not iterable. The tier is the "
            "set of families a campaign's roots rotate across, and a value "
            "that holds no members holds no tier."
        )
    return tuple(
        _member_from_parts(entry, f"a frontier tier's member {entry!r}")
        for entry in value
    )


def _tier_from_parts(value: object) -> FrontierTier:
    """Re-make the declared tier from its parts, refusing anything else.

    Recognition by parts for the reason :func:`_member_from_parts` gives.
    Unlike a member, a bare :class:`FrontierTier` is *not* short-circuited:
    re-making it re-runs the collection guard over entries that are already
    this module's class, which costs one pass and keeps the answer always
    built here — and the pass is what makes a tier assembled from the
    workspace's other copy normalise into this one.
    """
    try:
        members = object.__getattribute__(value, _TIER_PARTS[0])
    except AttributeError:
        raise RootProviderError(
            f"the frontier tier must be a FrontierTier "
            f"({', '.join(_TIER_PARTS)}), got {value!r} "
            f"({type(value).__name__}). Feature 196 records the serving "
            "provider of every root call *routed to the rotated frontier model "
            "tier*, so the tier is the set the recorded provider is checked "
            "against — a value that is not the configuration declares no "
            "members, and a membership check against nothing would either "
            "admit every provider or refuse every call."
        ) from None
    return FrontierTier(providers=members)


def _call_from_parts(value: object) -> RootCall:
    """Re-make the call from its parts, refusing anything else.

    Recognition by parts for the reason :func:`_member_from_parts` gives, and
    here the duck typing does real work at the call site: a caller holding the
    node row itself — a record from the tree store, or any object carrying
    ``node_id``, ``campaign_id`` and ``depth`` — satisfies this tuple without
    wrapping anything, which is the seam feature 184's policy question draws
    for its own cells.
    """
    try:
        parts = tuple(
            object.__getattribute__(value, part) for part in _CALL_PARTS
        )
    except AttributeError:
        raise RootProviderError(
            f"a root call must be a RootCall ({', '.join(_CALL_PARTS)}), got "
            f"{value!r} ({type(value).__name__}). Feature 196 records the "
            "serving provider of a root call, and a call is identified by the "
            "node it authored, the campaign that node belongs to and the depth "
            "the tree placed it at — a value carrying none of those names no "
            "call, and padding the missing parts with guesses would be "
            "recording provenance for a node nobody authored."
        ) from None
    return RootCall(node_id=parts[0], campaign_id=parts[1], depth=parts[2])


def _require_root_depth(depth: int, where: str) -> None:
    """Refuse a call the tree (or the caller) places below the root tier.

    One guard for the boundary's two readers — the caller's declaration and the
    tree's own fact — because they fail the same way and owe the caller the
    same explanation.  ``where`` says which of the two is speaking, so a
    refusal tells the operator whether it is the description to repair or the
    tree to look at.
    """
    if depth > ROOT_TIER_MAX_DEPTH:
        raise UnrotatedCampaignError(
            f"{where} is depth {depth}, and feature 196 records the serving "
            f"provider of **root-depth** calls only — architecture §14.1 puts "
            f"the frontier rotation on roots (depth 0–{ROOT_TIER_MAX_DEPTH}) "
            f"and everything from depth "
            f"{ROOT_TIER_MAX_DEPTH + 1} down on one cheap model with a 1M "
            "context, because the read-everything requirement makes context a "
            "hard selection criterion there. A depth call has one serving "
            "provider and no rotation to record: its model is chosen by "
            "feature 198's gate, and its node's author belongs in feature "
            "203's agent_model_id triple. Recording it here would fill this "
            "feature's column with rows that all say the same thing and bury "
            "the rotation's stratum among them."
        )


class RootProviderRotation:
    """The store that records which provider served each root call.

    Constructed with the database URL it writes to; :meth:`record` is feature
    196's sentence as one call — validate the ask, check the tier declares the
    provider, prove the tree holds the node the call authored, insert the row,
    read it back — and :meth:`get` reads one node's recorded provider.  The
    class resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store in
    this workspace states.  The table
    (:data:`ROOT_SERVING_PROVIDER_TABLE`) is this member's own, created lazily
    on the store's **first write** — :meth:`get` on a store that has never
    recorded reads ``sqlite_master``, finds no table, and answers ``None``, so
    a read never brings a schema into being.

    The store holds no cache of the records it wrote: the row is the only
    record of which provider served a root call, so it is the only thing an
    answer is drawn from — the same stance :class:`providers.DepthRunWindows`
    and :class:`providers.DepthCacheRates` state, for the same reason.  A memo
    of root calls would make *which family proposed this node?* a question
    about this process's history rather than about the world — and §14.1's
    whole reason for recording the provider is that the answer must survive the
    process that placed the call.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RootProviderError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RootProviderRotation | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        root-provenance component — a discoverable state, not an exception —
        while the caller that must record a root call's provider is the caller
        that must not find itself in it, for the reason
        :func:`providers.build_depth_cache_rates` states on its own ``None``:
        the caller that needs this row treats it as a refusal to proceed rather
        than as a store that happened to find nothing.
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
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The caller owns the connection; use it as a context manager to commit,
        which is what :meth:`record` does — the node probe, the row read and
        the ``INSERT`` are one unit of work, so a node expanded by a concurrent
        process between the probe and the insert is seen, and two recorders of
        one root call cannot interleave a read and a write.
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
        / ``depth_cache_rate`` precedent, and creating it lazily is the store's
        business.  ``IF NOT EXISTS``, so a database that already holds it — a
        second root call, a restarted process — passes through untouched.
        """
        connection.execute(_SCHEMA)

    # -- Feature 196: the record ---------------------------------------------

    def record(
        self,
        call: object,
        tier: object,
        serving: object,
        *,
        now: datetime | None = None,
    ) -> RootCallProvider:
        """Record the provider that served one root call and persist it.

        Feature 196's sentence as one call: the call, the campaign's declared
        frontier tier and the serving provider read off feature 192's
        completion in, the stored record out — the observation and its
        persistence as one act, because a provider observed and not recorded is
        the sentence with its first half missing.  The steps, and why each is
        where it is:

        1. **Validate the ask** — the call's three tree facts, the tier and the
           serving provider — *before anything is opened*, so a malformed ask
           is refused without touching a database.
        2. **Check the declared call is a root call** — the cheapest refusal
           available and the one the sentence's conditional turns on.  A call
           at depth 2 or greater is :class:`~providers.UnrotatedCampaignError`.
        3. **Check the tier declares the serving provider** — §14.1's rotation
           is a set of families, and a provider outside it is
           :class:`~providers.UnknownRootProviderError`, raised before any row
           is written because a record that accepted an undeclared provider
           would let a silent re-route write itself into the provenance.
        4. **Create the table**, lazily and idempotently — the row's first
           write brings its schema into being, and nothing else ever does.
        5. **Prove the tree holds the node, and agrees** — feature 97's table,
           probed read-only: the node must exist
           (:class:`~providers.RootNotRecordedError`), the depth the tree
           places it at must also be a root depth
           (:class:`~providers.UnrotatedCampaignError`, this time from the fact
           rather than the claim), and the campaign and the depth the tree
           holds must **equal** the caller's declaration, because the record's
           two fields are read by an auditor who cannot tell a checked value
           from a claimed one.
        6. **Return the stored row if this root call is already recorded** —
           an identical record answers the row it finds (``recorded=False``,
           the original ``recorded_at``, which a retry does not move) — or
           **refuse** when the fresh record names a different provider
           (:class:`~providers.RootProviderConflictError`, naming both).
        7. **Insert, then read back**, and return what the table holds: every
           column is the row's, re-parsed through the same readers ``get``
           uses, so a caller holds one record shape from one source of truth.

        Refuses, in this order, each naming what it is about: a malformed call,
        tier or member (the base
        :class:`~providers.RootProviderError`); a call below the root tier
        (:class:`~providers.UnrotatedCampaignError`); a serving provider the tier
        does not declare (:class:`~providers.UnknownRootProviderError`); a node
        the tree does not hold (:class:`~providers.RootNotRecordedError`); a
        declaration the tree contradicts (the base, naming both values); a
        second record naming a different provider
        (:class:`~providers.RootProviderConflictError`).
        """
        validated = _call_from_parts(call)
        declared = _tier_from_parts(tier)
        served = _member_from_parts(serving, "a root call's serving provider")
        _require_root_depth(
            validated.depth, f"the call for node {validated.node_id!r}"
        )
        if served not in declared:
            raise UnknownRootProviderError(
                f"{served.provider!r} served the root call for node "
                f"{validated.node_id!r} in campaign "
                f"{validated.campaign_id!r}, and the campaign's frontier tier "
                f"does not declare it: the tier declares {declared.text()!r}. "
                "Feature 196 records which family answered a root call so that "
                "the tree's roots can be stratified by it (architecture §14.1: "
                "'Rotating providers at roots is the cheapest mitigation "
                "available'), and that reading is only worth making if the "
                "declared set is the closed vocabulary the recorded value comes "
                "from — a record that accepted any provider the completion "
                "reported would write a silent re-route into the provenance as "
                "though a human had chosen it, which is the §14.1 failure this "
                "whole category exists to end (deepseek-v4-flash, retired "
                "2026-09-10 while continuing to accept the ID). Add the "
                "provider to the campaign's declared tier if it genuinely "
                "belongs in the rotation (feature 197), or serve the call from "
                "one that is already declared."
            )
        # One instant for the row's stamp, computed once so the stored value
        # and any retry's comparison read the same moment — the same "two
        # clocks narrating one decision" guard
        # :meth:`providers.DepthCacheRates.measure` states.
        recorded_at = (
            _require_instant(datetime.now(UTC), "the recording instant")
            if now is None
            else _require_instant(now, "the recording instant")
        )
        with closing(self._connect()) as connection, connection:
            self._ensure_schema(connection)
            # The tree's own facts are re-derived inside ``_require_node``
            # (which refuses a declaration they contradict), so the returned
            # pair is not needed here: ``record`` writes the *validated* call's
            # values, and ``_require_node`` has already proved they are the
            # tree's.
            self._require_node(connection, validated)
            stored = self._read_row(connection, validated.node_id)
            if stored is not None:
                return self._reissued(stored, served, validated, recorded=False)
            connection.execute(
                f"INSERT INTO {ROOT_SERVING_PROVIDER_TABLE} "
                f"({NODE_ID_COLUMN}, {CAMPAIGN_ID_COLUMN}, {DEPTH_COLUMN}, "
                f"{SERVING_PROVIDER_COLUMN}, {MODEL_COLUMN}, "
                f"{RECORDED_AT_COLUMN}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    validated.node_id,
                    validated.campaign_id,
                    validated.depth,
                    served.provider,
                    served.model,
                    _format_instant(recorded_at),
                ),
            )
            row = self._read_row(connection, validated.node_id)
        if row is None:
            raise RootProviderError(
                f"the serving provider recorded for node "
                f"{validated.node_id!r} could not be read back after the "
                "insert; the row is the record, and a record that cannot be "
                "re-read is one this store cannot vouch for"
            )
        return self._record_from_row(row, recorded=True)

    def get(self, node_id: Any) -> RootCallProvider | None:
        """One root call's recorded provider, or ``None`` when it holds none.

        ``None`` means *this node's root call was never recorded here* —
        nothing has recorded it — which is the honest answer for a node no row
        holds, and the answer on a database whose ``root_serving_provider``
        table does not exist yet (a store that has never recorded created
        nothing, and a read does not create it).  It does **not** mean the read
        failed: an unreachable database raises, so a caller can never mistake a
        broken store for an unrecorded call — the same distinction
        :meth:`providers.DepthCacheRates.get` draws.

        The record is **re-verified, not merely re-parsed**: the ids are UUIDs,
        the depth is a non-negative integer at or above the root boundary, the
        provider and the model are names, the instant parses — each refusal
        names the node, on the ground the read side is where corruption would
        otherwise be laundered, and a row placing a depth-5 call in the root
        stratum would be a rotation's contrast read off a call the rotation
        never made.  ``recorded`` is always ``False`` here: a read wrote
        nothing.
        """
        node = _validated_node_id(node_id)
        with closing(self._connect()) as connection:
            if (
                connection.execute(
                    _TABLE_EXISTS_SQL, (ROOT_SERVING_PROVIDER_TABLE,)
                ).fetchone()
                is None
            ):
                return None
            row = self._read_row(connection, node)
        if row is None:
            return None
        return self._record_from_row(row, recorded=False)

    # -- The words ----------------------------------------------------------

    def _read_row(
        self, connection: sqlite3.Connection, node: str
    ) -> tuple[Any, ...] | None:
        """One node's row as the table holds it, or ``None`` when absent.

        Selected column by column rather than with ``SELECT *``, the discipline
        :meth:`providers.DepthCacheRates._read_row` states: the order
        :meth:`_record_from_row` reads must be the order this names, and a
        column appended later must not silently shift the fields.
        """
        cursor = connection.execute(
            f"SELECT {NODE_ID_COLUMN}, {CAMPAIGN_ID_COLUMN}, {DEPTH_COLUMN}, "
            f"{SERVING_PROVIDER_COLUMN}, {MODEL_COLUMN}, "
            f"{RECORDED_AT_COLUMN} FROM {ROOT_SERVING_PROVIDER_TABLE} "
            f"WHERE {NODE_ID_COLUMN} = ?",
            (node,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _record_from_row(
        self, row: tuple[Any, ...], *, recorded: bool
    ) -> RootCallProvider:
        """Build a :class:`RootCallProvider` from a row, re-verified.

        The read path's one constructor, so :meth:`get` and :meth:`record`'s
        read-back cannot disagree about which column is which.  Every value is
        re-parsed through the row-shaped readers rather than trusted — the
        record's own constructor then re-states the boundary law, so a row that
        contradicts it is refused here, naming the node, which is the
        difference between an operator learning *this root's provenance is
        corrupt* and learning that some value somewhere does not parse.
        """
        node = _validated_node_id(row[0])
        return RootCallProvider(
            node_id=node,
            campaign_id=_validated_campaign_id(row[1]),
            depth=_parse_depth(row[2], node, DEPTH_COLUMN),
            provider=_parse_text(row[3], node, SERVING_PROVIDER_COLUMN),
            model=_parse_text(row[4], node, MODEL_COLUMN),
            recorded_at=_parse_instant(row[5], node, RECORDED_AT_COLUMN),
            recorded=recorded,
        )

    def _reissued(
        self,
        row: tuple[Any, ...],
        served: FrontierProvider,
        call: RootCall,
        *,
        recorded: bool,
    ) -> RootCallProvider:
        """Answer a re-issued record: the stored row, or a conflict.

        The identical record — a fresh observation that names the same provider
        and model — returns the row the table holds, **including its original
        ``recorded_at``**.  A retry is the same record arriving twice, and the
        row *is* the record: the retry did not move the instant the call was
        recorded, and §14.1's rotation assigns each root call to one family.

        ``recorded`` is passed through rather than fixed here, because this
        method answers two situations that differ only in that flag: a re-issued
        record (``False`` — this call wrote nothing) and the read-back after an
        insert that a concurrent recorder won (``True`` — the row is now the
        one this call's ``record`` returns, though the insert itself may have
        been a no-op).  Fixing it here would make the two indistinguishable to
        a caller, which is the whole point of carrying it.

        A fresh record naming a **different** provider or model is refused, and
        the refusal names both, because that is the difference between an
        actionable refusal and a complaint: the caller learns which family is
        stored against this root and which its own call read off the
        completion.  The comparison is on the pair alone — the two names are
        the record, and the campaign, the depth and the instant beside them are
        facts about the call that a second record cannot change without the
        tree having changed underneath it.
        """
        stored = self._record_from_row(row, recorded=recorded)
        if (
            stored.provider == served.provider
            and stored.model == served.model
        ):
            return stored
        raise RootProviderConflictError(
            f"node {call.node_id!r} in campaign {call.campaign_id!r} already "
            f"records {stored.provider}:{stored.model} as the provider that "
            f"served its root call, and this record would name "
            f"{served.text()}. One root call is one call, and the family that "
            "answered it is what it is: architecture §14.1's rotation assigns "
            "each root call to one provider, and that assignment is the fact "
            "the tree's roots are stratified by — the same root cannot have "
            "been proposed by two families. The stored row is the fact. Read it "
            "with get(), or, if the root really was proposed a second time "
            "under another family, record that proposal as its own node so each "
            "record names one call."
        )

    def _require_node(
        self, connection: sqlite3.Connection, call: RootCall
    ) -> tuple[str, int]:
        """Prove the tree holds the node, and return the facts it states.

        The probe is read-only — ``sqlite_master`` for the table, then one
        ``SELECT`` by the table's own key — and feature 97's ``node`` table is
        **never created** here: it is ``0118``'s, and a store that invented it
        would be writing a schema it does not own.

        Four outcomes, in the order they become knowable, each with its own
        repair:

        * no ``node`` table at all, or no row for this id — the node was never
          expanded (:class:`~providers.RootNotRecordedError`, the two wordings
          telling an operator whether to run the migrations or to place the
          call).  Both are the same fact about the id rather than two: a
          database with no node table has never held a node.
        * the tree places the node below the root tier — the *fact* refuses the
          call, whatever the caller declared
          (:class:`~providers.UnrotatedCampaignError`).
        * the tree's campaign or depth disagrees with the declaration — the
          base :class:`~providers.RootProviderError`, naming both values,
          because the description is what is wrong.

        The returned pair is the tree's own campaign and depth, so
        :meth:`record` never writes a value it did not read.
        """
        if (
            connection.execute(_TABLE_EXISTS_SQL, (NODE_TABLE,)).fetchone()
            is None
        ):
            raise RootNotRecordedError(
                f"the store at {self.path} holds no {NODE_TABLE} table, so no "
                f"node has ever been expanded in it and node {call.node_id!r} "
                "cannot have been either: a root call's serving provider is "
                "recorded against the node the call authored, and that node is "
                f"a row of feature 97's tree (revision {NODE_TABLE_REVISION}), "
                "written when the node is expanded. Run the migration chain, "
                "expand the root (feature 239), then record the provider that "
                "proposed it."
            )
        cursor = connection.execute(
            f"SELECT {CAMPAIGN_ID_COLUMN}, {DEPTH_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_TABLE_ID_COLUMN} = ?",
            (call.node_id,),
        )
        try:
            found = cursor.fetchone()
        finally:
            cursor.close()
        if found is None:
            raise RootNotRecordedError(
                f"there is no node {call.node_id!r} in the tree store at "
                f"{self.path}: a serving provider is recorded for the root call "
                "that authored a node, so an id the tree does not hold names a "
                f"call whose mechanism nobody wrote — the {NODE_TABLE} table is "
                "feature 97's and its rows are the discovery tree's, and "
                "writing one here would be writing a row this member does not "
                "own. Expand the root first (feature 239), then record the "
                "provider that proposed it."
            )
        tree_campaign = _validated_campaign_id(found[0])
        tree_depth = _parse_depth(found[1], call.node_id, DEPTH_COLUMN)
        _require_root_depth(
            tree_depth, f"the node {call.node_id!r} the tree holds"
        )
        if tree_campaign != call.campaign_id:
            raise RootProviderError(
                f"the call names campaign {call.campaign_id!r} and the tree "
                f"places node {call.node_id!r} in campaign {tree_campaign!r}. "
                "The campaign a root call belongs to is a column of feature "
                "97's node table, not a field a caller supplies freely, and a "
                "record whose campaign disagrees with the tree would be filed "
                "under a campaign whose roots never included this call — which "
                "is a provenance row an auditor would have to take on faith, "
                "the state this feature exists to end. Record the call under "
                "the campaign the tree holds the node in."
            )
        if tree_depth != call.depth:
            raise RootProviderError(
                f"the call for node {call.node_id!r} declares depth "
                f"{call.depth} and the tree places it at depth {tree_depth}. "
                "The depth is a column of feature 97's node table, fixed when "
                "the node is created, and it is the fact architecture §14.1's "
                "tiering is read off — a record carrying a depth the tree "
                "contradicts would place a call in a tier nobody checked. Both "
                f"depths are root depths (0–{ROOT_TIER_MAX_DEPTH}); record the "
                "call with the depth the tree holds."
            )
        return tree_campaign, tree_depth

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def record_root_provider(
    call: object,
    tier: object,
    serving: object,
    *,
    now: datetime | None = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RootCallProvider:
    """Record one root call's serving provider — the module-level spelling.

    Feature 196's sentence as one call, for the caller that wants the act
    without holding a store: the call, the campaign's declared frontier tier
    and the serving provider read off feature 192's completion in, the stored
    record out.  The store is resolved from ``database_url``, else from
    ``DATABASE_URL``; a deployment that names neither is refused *by name*
    rather than silently doing nothing, because a record that quietly skipped
    its write would leave the campaign's root stratum unaudited — and the next
    deployment reading which families proposed which mechanisms would be
    reading a tree whose provenance was never written.

    A :class:`~providers.RootProviderError` from the store is left to propagate
    unwrapped: the refusal already names the call, the campaign and the fact,
    and re-wrapping it here would put a second message in front of the one an
    operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise RootProviderError(
            "record_root_provider records the provider that served a root call "
            f"and nothing names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so the serving provider could not be "
            "recorded. Feature 196's record is a fact that must actually land "
            "in the table — architecture §14.1 rotates providers at roots "
            "precisely so the tree's roots can be stratified by family "
            "afterwards, and a rotation nobody wrote down is a rotation the "
            "next campaign cannot learn from."
        )
    return RootProviderRotation(url).record(call, tier, serving, now=now)
