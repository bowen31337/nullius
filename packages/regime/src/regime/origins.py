"""The backfilled world's originating campaign, persisted — feature 288.

app_spec.xml, "Regime Coverage Strata", feature 288: *System persists a
backfilled world with its originating campaign reference, so backfill never
masquerades as fresh history.*  Its parent is feature 287 — *System backfills
coverage by replaying stored discovery trees against historical epochs, which
creates worlds those trees were never run on* — and feature 287's own spec
names this feature as the reason its synthesized world carries a campaign in
its identity at all: *"the seed feature 288 persists as the originating
campaign reference."*

**What the act is, and the failure it exists to prevent.**  docs/
alpha-engine-prd.md §C7's third bullet is the remedy this whole category
serves — *"Backfill by replaying stored discovery trees against historical
market epochs they were never actually run on"* — and a backfilled world is
exactly that: a discovery tree, found on its own campaign's data, replayed
against an epoch it never saw.  The world is *synthetic history*.  It is not
evidence that the tree ever traded that market, and it is not evidence the
pool accumulated that regime by living through it.  §C7's whole argument is
that the pool's composition must stay *countable*, and the specific danger of
a synthetic world is that it is countable **as the real thing**: a reader who
cannot tell a backfilled world from one the system actually ran would report
coverage the system never earned — §C7's own failure mode (*"the meta-policy
learns a chop-optimal search policy and you find out when the regime
breaks"*) dressed as its remedy.

**The workspace already states this law for the other world that has an
upstream.**  docs/nullius-tech-architecture.md §10.6.1's provenance rule —
*"An upstream that changes is a different world, not an updated one"* — is
what feature 191 persists for ported worlds, and §14.1's own incident is the
rule's proof: *"DeepSeek retired ``deepseek-v4-flash`` on 2026-09-10 while
continuing to accept the ID, silently serving V4.1-Flash ... this is the
provenance failure, not a hypothetical."*  A world served under a name that
no longer describes it is the corruption.  A backfilled world served as fresh
history is the same corruption one level up, and the remedy is the same one:
**the world's origin is recorded, by the writer, where a later reader reads
it from** — not promised in a docstring, and not left to the caller to
remember.

**Where the origin comes from — and why it is not a second field.**  Feature
287 spelled the synthesized world's identity as ``<campaign_id>@<epoch_id>``
precisely so the provenance *is* the identity: the world id states the
campaign the tree belongs to and the epoch it was replayed against, and
:func:`split_world_id` reads those two halves back out.  This module therefore
**derives** the persisted reference from the world id rather than accepting
it as an independent argument, and that is the load-bearing decision here.  A
store that took ``(world_id, campaign_id)`` as two separate values could be
handed a world whose id named one campaign while its stated reference named
another, and it would then have to choose which one to believe — which is the
masquerade, moved one layer down rather than removed.  There is nothing to
choose.  The id is the provenance, the columns are a materialised view of it,
and a carrier that states a campaign (or an epoch) disagreeing with its own
id is *refused* rather than reconciled — the ``no_origin`` code's second face
below.  Feature 187's headline-refusal discipline (*a judgment over the counts
already made, never a third count*) restated for provenance: the row holds a
fact the identity already carries, and no caller supplies a second one.

**The table is this member's own, and it is not a migration.**  Nothing in
app_spec.xml's ``database_schema`` block declares a backfilled-world table, and
this feature adds no versioned migration — the constraint feature 287's own
spec states, and the stance every member store in this workspace takes toward
a table it alone writes.  ``packages/bootstrap/src/bootstrap/_pool.py``
(``bootstrap_world``, features 188/191), ``packages/replay/src/replay/
metrics.py`` (``replay_latency_metrics``, feature 254) and ``packages/
cost-model``'s latency store (feature 67) all create their table idempotently
on connect — ``CREATE TABLE IF NOT EXISTS``, the contract every store here
states — so no migration step is needed and no shared schema file is touched.
The shape is argued in :data:`_SCHEMA` rather than in the shared chain,
because the table has exactly one writer, this store, and its shape is a fact
about the feature rather than about the database's history.

**Why ``bootstrap_world`` is deliberately not the table this writes.**  The
nearest candidate is obvious and worth refusing by name.  The replay pool's
world table is feature 188's, widened in place by feature 191 into a strict
either-or: one row is *authored* (a seed, the draw that drew it, no digests,
the ``hpo`` domain) or *ported* (both digests, the ``ported`` domain, no seed)
and never both — a shape the table's own ``CHECK`` states so that a
hand-edited row that would corrupt the pool refuses itself on insert.  A
backfilled world is neither half.  It has no seed, because it was not drawn;
it has no upstream digest pair, because its market came from an epoch this
system already holds; and it has something neither half carries, an
*originating campaign*.  Seating it there would mean loosening another
member's ``CHECK`` — an edit to a file this member does not own, whose whole
point is that the two halves are exclusive — and the pool would then be
holding rows whose meaning changed underneath the features that read them.
So the alignment is *by name* instead: the same ``world_id`` a
``replay_score`` row joins on, in this member's own table, exactly the way
feature 186's world census reads ``bootstrap_world`` as a set of ids without
owning it.  A caller that wants the pool's backfilled half asks this store.

**Idempotent by world, and the vintage is the first seating.**  The table's
identity is one row per world (``world_id`` is the primary key), so a
re-issued ``record`` for a world the store already holds returns the standing
row **byte for byte**, ``recorded_at`` included.  That is not a convenience:
a backfill is a batch job over stored trees and historical epochs, and
re-running it is the ordinary case (a corrected epoch list, a reclaimed spot
instance, a nightly sweep).  The instant recorded is *when this world first
entered the pool as a backfill*, and a retry did not move it — the same
argument :meth:`~regime.coverage.RegimeCoverage.record` makes for its own
idempotence, and the same ``updated_at`` law feature 0107's migration states
(*"a coverage number is only evidence while you know when it was last
true"*).  There is no update arm here at all, and its absence is the point: a
backfilled world's origin is derived from its identity, so there is no second
value an update could carry that the first write did not already have.  The
only reconciliation a re-record can need is the masquerade check, and that
refuses rather than rewrites.

**One clock, and it is the database's.**  ``recorded_at`` takes the table's
own ``DEFAULT (datetime('now'))``, the expression feature 0107's migration
uses and the convention this member's :mod:`regime.coverage` states — *"a
writer-minted vintage beside a default-minted one would be two clocks, and
two clocks can disagree about which count was true first."*  Nothing in this
module computes a timestamp in Python.  The default keeps the outer
parentheses SQLite's ``DEFAULT`` grammar demands of a function call, the trap
:data:`regime.coverage._CREATE_TABLE_SQL` documents for this exact
expression.

**The answer is read back, and the read path validates.**  Every write
answers with the row the table holds — the derived origin and the vintage the
database minted — never a value assembled from the argument, for the reason
every store in this workspace states: the row is the record.  And because
SQLite's columns are dynamically typed, a raw ``INSERT`` from another tool can
land anything in this table, including a ``campaign_id`` that disagrees with
the ``world_id`` beside it.  A read that swallowed that would hand a caller a
world whose recorded origin contradicts its own identity — the masquerade this
feature exists to prevent, arriving through the read path instead of the
write path — so :class:`BackfilledWorldRecord` re-derives the origin from the
id in ``__post_init__`` and refuses the disagreement, and
:meth:`WorldBackfill._record_from_row` re-raises naming the world it came
off.

**Error vocabulary at the seam.**  The refusal is
:class:`~regime.errors.BackfillProvenanceError`, a *sibling* of
:class:`~regime.errors.CoverageError` and
:class:`~regime.errors.StratumAssignmentError` rather than a child, for the
reason :mod:`regime.errors` states for every class in this category: a caller
catching them together would read the wrong repair — a world that states no
origin is not a malformed count and not a full-history fit.  It opens every
message with :data:`NO_ORIGIN_CODE` (``no_origin``), the greppable one word
the ``pool_frozen`` (feature 270) / ``illegal_theme`` (feature 241) /
``full_history_fit`` (feature 290) / ``unwalkable_tree`` (feature 287)
precedent establishes.  A ``DATABASE_URL`` this member cannot speak is
**not** this class: it is an *address* fault, the same fault feature 283's
store already names, with the same repair — point the deployment at the
database the pool lives in — so :func:`_sqlite_path` raises
:class:`~regime.errors.CoverageError` here exactly as it does there, and the
member keeps one vocabulary for one fault.

**No component, no seat, no registry.**  This feature adds no ``@register``
builder: a store addressed by ``DATABASE_URL`` is never composed, the stance
:mod:`regime`'s own docstring argues for every feature in this category past
the ledger, and the member's registered surface stays feature 283's single
store.  Nothing here edits a central registry, router table, app factory,
middleware, settings module or migration, and the module is reached directly
from the member (``from regime import WorldBackfill``), the way
:func:`~regime.census.census_coverage` is.

**Duck-typed, because a member never imports another.**  The world arrives as
feature 287's :class:`~regime.BackfilledWorld` — but the loader imports a
member under a synthetic name and re-executes it, so a composed application
serves a *second* class object of the same shape, and an ``isinstance`` gate
would refuse the very world the composition seam hands out.  What this module
asks of a carrier is the one attribute the act needs: ``world_id``, read
through :func:`_world_id_of`, with a bare string accepted because a world id
*is* the whole of what is being persisted.  A carrier that also states a
``campaign_id`` or an ``epoch_id`` has those read too — and checked against
the id rather than believed.  That is feature 189's *"ask the surface the act
needs"* discipline: this module reads two halves of one string and never
touches ``regime_rows``, the market, the tree or the labeler.

**This module's name is chosen away from its sibling's.**  Feature 287 is
the backfill *verb* — ``backfill_coverage(trees, epochs, labeler, store)``,
which synthesizes the worlds — and feature 288, this module, is the store
that records what one of those worlds came from.  The two acts are adjacent
enough that a caller reaching for one can easily mean the other, so the
names are deliberately not one character apart: ``regime.origins`` (this
store, ``WorldBackfill``) rather than ``regime.backfilled`` (which would be
a one-character hop from 287's ``regime.backfill``), and ``WorldBackfill``
rather than ``BackfilledWorlds`` (a letter away from 287's
``BackfilledWorld``, *the synthesized world itself*).  Both near-misses
would import cleanly and mean the wrong thing — the worst kind of mistake,
because nothing would fail.  ``backfilled_world``, the *table*, keeps its
name: it is a string the database holds rather than a Python name a caller
imports, so there is no namespace for it to collide in, and it says exactly
what the rows are.

Stdlib only, and import-cheap: ``os``, ``sqlite3``, ``dataclasses``,
``collections.abc``, ``urllib.parse``; no third-party import at module scope,
so the factory's scan — which imports this package to fire its ``@register``
— pays nothing for this module, and a composed application that never seats a
backfilled world never opens a database.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import BackfillProvenanceError, CoverageError

__all__ = [
    "BACKFILLED_WORLD_TABLE",
    "CAMPAIGN_ID_COLUMN",
    "DATABASE_URL_ENV",
    "EPOCH_ID_COLUMN",
    "NO_ORIGIN_CODE",
    "RECORDED_AT_COLUMN",
    "WORLD_ID_COLUMN",
    "WORLD_ID_SEPARATOR",
    "BackfillProvenance",
    "BackfilledWorldRecord",
    "WorldBackfill",
    "record_backfilled_world",
    "split_world_id",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the campaign
#: planner's, the bootstrap pool's, the replay latency metrics'), restated
#: here so this store states its own contract and imports nobody else's.
#: The backfilled worlds live in the *same* database the coverage ledger does,
#: because they are facts about the same pool: ``replay_score`` joins on the
#: ``world_id`` a row here records, exactly as it joins on the ledger's world
#: counts' subject.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the backfilled worlds are recorded in — this member's own, in the
#: relational store ``DATABASE_URL`` names, created idempotently on connect so
#: no migration step is needed and no shared schema file is touched.  Named for
#: what it holds (the backfilled worlds and their origins) the way feature
#: 254's ``replay_latency_metrics`` is, so a reader of the store can tell whose
#: row it is holding.  Deliberately **not** feature 188's ``bootstrap_world``:
#: the module docstring argues why seating a backfilled world in that table
#: would mean loosening another member's either-or ``CHECK``.
BACKFILLED_WORLD_TABLE = "backfilled_world"

#: The separator feature 287 spelled the synthesized world's identity with —
#: ``<campaign_id>@<epoch_id>``.  It is the member's own, and it is *never*
#: normalised away: a world id states its origin or it states none, and
#: rewriting the spelling would silently rename the provenance it carries.
WORLD_ID_SEPARATOR = "@"

#: The one word that opens every refusal this store raises, so the rejection is
#: greppable by the fact the feature's own sentence names — the convention
#: ``pool_frozen`` (feature 270), ``illegal_theme`` (feature 241),
#: ``full_history_fit`` (feature 290) and ``unwalkable_tree`` (feature 287)
#: already follow in this workspace.  Its two faces are the id that states no
#: origin and the carrier that states an origin disagreeing with its own id —
#: the masquerade, refused rather than reconciled.
NO_ORIGIN_CODE = "no_origin"

#: The world's identity — feature 287's ``<campaign_id>@<epoch_id>``, and this
#: table's primary key.  The row is keyed by it for the reason the pool's own
#: world tables are: it is the name a ``replay_score`` row attributes a score
#: to, so a store of origins must be answerable by that name alone.
WORLD_ID_COLUMN = "world_id"

#: The originating campaign reference — the tree's campaign, read back out of
#: the world id rather than supplied beside it.  ``NOT NULL`` because a
#: backfilled world without an origin is precisely the masquerade this feature
#: refuses; the column exists so a reader that knows only the table can tell a
#: synthetic world from a fresh one without re-deriving the spelling.
CAMPAIGN_ID_COLUMN = "campaign_id"

#: The epoch the tree was replayed against — the other half of the identity,
#: recorded beside its campaign so a reader can ask *which* historical market
#: this world is synthetic for.  Feature 88's sequestered-epoch ledger charges
#: an ``epoch_id``; this column names the same thing where a backfilled world
#: is what spent it.
EPOCH_ID_COLUMN = "epoch_id"

#: When the world first entered the pool as a backfill.  ``NOT NULL`` with the
#: table's own default, because a recorded origin without an instant is not
#: evidence of when the pool grew, and the default is what leaves the single
#: clock the database's — the convention :mod:`regime.coverage` states for the
#: same expression, and why nothing here reads a Python clock.
RECORDED_AT_COLUMN = "recorded_at"

#: The table's DDL, in the SQLite spelling this store speaks.  The default
#: keeps the outer parentheses SQLite's ``DEFAULT`` grammar demands of a
#: function call: without them the whole ``CREATE TABLE`` is a syntax error,
#: the trap feature 0107's migration and :mod:`regime.coverage` both document
#: for this exact expression.  There is no update arm to pair with it — a
#: backfilled world's origin is derived from its identity and cannot change —
#: so the writer contract feature 283 owns has no second half here.
_SCHEMA = f"""
-- Feature 288: the backfilled world's originating campaign reference.
--
-- A backfilled world is synthetic history: a discovery tree replayed against
-- a historical epoch it was never actually run on (§C7's third bullet).  It
-- must never be countable as a world the system really traded, so its origin
-- is recorded here by the writer, where a later reader reads it from.
--
-- `world_id` is the row's key and the whole join: it is the name a
-- `replay_score` row attributes a score to, and feature 287 spelled it
-- `<campaign_id>@<epoch_id>` so that the provenance *is* the identity.  The
-- two columns beside it are a materialised view of that one string, never an
-- independent second opinion -- which is why this store derives them and
-- refuses a carrier whose stated origin disagrees with its own id.
--
-- `world_id` is TEXT, and deliberately not UUID: the spec's
-- `replay_score.world_id` is declared UUID, but a *backfilled* world's id is
-- `<campaign_id>@<epoch_id>` -- feature 287 chose that spelling precisely so
-- the origin would be readable off the identity -- and that string is not a
-- UUID.  The two tables are still joined by the same name, because
-- `replay_score.world_id`'s declared type is the *engine's* business (SQLite
-- is dynamically typed and stores what it is given); this column's type is
-- this table's own statement about what the value IS.  Widening a typed
-- column to match another table's would be the wrong repair: the value is
-- text, and a reader that parsed it as a UUID would be reading a backfilled
-- world as a fresh one -- the masquerade, arriving through the type.
--
-- `recorded_at` carries the engine DEFAULT, so a row's vintage comes from the
-- database's clock and never from a writer that could disagree with it.  The
-- default fires at insert only, and there is deliberately no update path: a
-- backfilled world's origin cannot change, so a re-record is the standing row
-- returned untouched and never a re-stamp.
CREATE TABLE IF NOT EXISTS {BACKFILLED_WORLD_TABLE} (
    {WORLD_ID_COLUMN}    TEXT NOT NULL PRIMARY KEY,
    {CAMPAIGN_ID_COLUMN} TEXT NOT NULL,
    {EPOCH_ID_COLUMN}    TEXT NOT NULL,
    {RECORDED_AT_COLUMN} TIMESTAMPTZ NOT NULL DEFAULT (datetime('now'))
)
"""

#: One world's row, column by column rather than ``SELECT *``: the order
#: :meth:`WorldBackfill._record_from_row` reads must be the order this
#: names, and a future shape change that appends a column must not silently
#: shift the fields — the failure a positional ``SELECT *`` invites.
_READ_ROW_SQL = (
    f"SELECT {WORLD_ID_COLUMN}, {CAMPAIGN_ID_COLUMN}, {EPOCH_ID_COLUMN}, "
    f"{RECORDED_AT_COLUMN} FROM {BACKFILLED_WORLD_TABLE} "
    f"WHERE {WORLD_ID_COLUMN} = ?"
)

#: Every recorded world's row, in the pool's own total order — the listing the
#: backfilled half of the pool is read through.  Ordered by ``world_id`` for
#: the reason every listing in this workspace is ordered by its key: two reads
#: of one store must be comparable.
_LIST_ROWS_SQL = (
    f"SELECT {WORLD_ID_COLUMN}, {CAMPAIGN_ID_COLUMN}, {EPOCH_ID_COLUMN}, "
    f"{RECORDED_AT_COLUMN} FROM {BACKFILLED_WORLD_TABLE} "
    f"ORDER BY {WORLD_ID_COLUMN}"
)

#: The seating itself: an insert that *keeps whatever is already there*.
#:
#: ``ON CONFLICT DO NOTHING`` rather than a plain ``INSERT``, and the reason is
#: atomicity rather than convenience.  A read-then-insert is a race: two
#: processes seating the same world both read no row, both write, and the
#: loser gets a raw ``sqlite3.IntegrityError`` out of a member act — a DBAPI
#: exception where this member's ``no_origin`` vocabulary belongs.  That race
#: is not hypothetical here: feature 287's backfill is a *batch* job over
#: stored trees crossed with historical epochs, and a re-run against a
#: partially-seated pool is exactly the ordinary case that two workers can
#: collide on.  ``DO NOTHING`` makes the seating idempotent *in the engine*, so
#: the standing row survives whatever the write ordering was and the caller
#: reads it back either way.
#:
#: This is stronger than a Python-side reconciliation, not weaker: the
#: "first seating wins" law is enforced by the primary key rather than by a
#: read that another process can invalidate between the two statements.  It
#: is also the *whole* of the writer contract, because there is no update arm
#: — a world's origin is derived from its identity, so there is no second
#: value an update could carry, and the one conflict worth refusing (a stated
#: origin disagreeing with the id) is refused before this statement is ever
#: reached.
_INSERT_ROW_SQL = (
    f"INSERT INTO {BACKFILLED_WORLD_TABLE} "
    f"({WORLD_ID_COLUMN}, {CAMPAIGN_ID_COLUMN}, {EPOCH_ID_COLUMN}) "
    "VALUES (?, ?, ?) "
    f"ON CONFLICT ({WORLD_ID_COLUMN}) DO NOTHING"
)


# -- Validation -------------------------------------------------------------------


def _validated_text(value: Any, what: str) -> str:
    """Return ``value`` as non-empty text, stripped, or refuse it.

    The shape feature 287's spec states for both halves of a world id —
    *"both halves are non-empty text, stripped"* — restated here because this
    module reads the halves off a string it did not build and off rows another
    tool could have written.  Nothing else is normalised: the separator is the
    member's own and is never folded away, and a half is not case-folded or
    re-spelled, because a caller that wrote two spellings of one campaign is
    the one that must reconcile them, in the campaign table that mints them.
    """
    if not isinstance(value, str) or not value.strip():
        raise BackfillProvenanceError(
            f"{NO_ORIGIN_CODE}: a backfilled world's {what} must be non-empty "
            f"text — got {value!r} ({type(value).__name__}); the world's "
            "identity is what its origin is read out of, and a half that "
            "states nothing names no campaign and no epoch a reader could "
            "resolve (feature 288)"
        )
    return value.strip()


def _validated_world_id(value: Any) -> str:
    """Return ``value`` as a world id, or refuse what cannot be one.

    Non-empty text, stripped — the pool's own key (``replay_score``'s join
    column, ``bootstrap_world``'s primary key), and the same near-miss rule
    :func:`regime.census._validated_world_id` takes: an id with a trailing
    newline would be a *second* identity for one world against a table keyed by
    the name a score is attributed to.  Note what this check deliberately does
    **not** do: it does not require the separator.  A world id that is merely
    not a world id is this function's refusal; a world id that states no
    *origin* is :func:`split_world_id`'s, and the two repairs differ — one is
    re-send the name, the other is re-derive where the world came from.
    """
    if not isinstance(value, str) or not value.strip():
        raise BackfillProvenanceError(
            f"{NO_ORIGIN_CODE}: a backfilled world's {WORLD_ID_COLUMN} must be "
            f"non-empty text — got {value!r} ({type(value).__name__}); a "
            "world's id is the name its scores are attributed to and the "
            "string its originating campaign is read out of, and an id that "
            "states nothing names no world to record an origin for "
            "(feature 288)"
        )
    return value.strip()


def split_world_id(world_id: Any) -> BackfillProvenance:
    """Read a world id's originating campaign and epoch back out of it.

    Feature 287's spelling made the provenance *be* the identity —
    ``<campaign_id>@<epoch_id>`` — and this function is the one place the
    member reads it back, so the writer and any later reader cannot disagree
    about which half is which.  The id is split on its **first** separator:
    campaign ids are UUIDs (the value ``node.campaign_id`` and every reader of
    the campaign row resolves, feature 232's minted key), and a UUID contains
    no ``@``, so everything after the first separator is the epoch's id taken
    as given — the epoch ledger's key is text (feature 105) and this store has
    no business re-spelling it.

    Refuses, with the ``no_origin`` code, a world id that states no origin:
    one carrying no separator at all, or one whose campaign half or epoch half
    is blank.  Each is a world whose provenance a reader could not resolve, and
    the repair in all three cases is the same — re-derive the world from the
    tree and the epoch it was really synthesized from, rather than recording a
    name that hides its origin.  This is the feature's whole sentence in one
    check: *backfill never masquerades as fresh history* because a backfilled
    world that cannot say where it came from is never seated at all.
    """
    name = _validated_world_id(world_id)
    if WORLD_ID_SEPARATOR not in name:
        raise BackfillProvenanceError(
            f"{NO_ORIGIN_CODE}: the world id {name!r} states no originating "
            "campaign; a backfilled world's identity is spelled "
            f"<campaign_id>{WORLD_ID_SEPARATOR}<epoch_id> so that the "
            "provenance is the identity, and a world whose id names no tree "
            "is a synthetic world that could be counted as fresh history — "
            "the exact masquerade this feature exists to refuse. Re-derive "
            "the world from the stored tree and the epoch it was replayed "
            "against (feature 288)"
        )
    campaign, _, epoch = name.partition(WORLD_ID_SEPARATOR)
    return BackfillProvenance(
        campaign_id=_validated_text(campaign, "originating campaign"),
        epoch_id=_validated_text(epoch, "epoch"),
    )


def _world_id_of(world: Any) -> str:
    """The world id a carrier states, or refuse a carrier that states none.

    The duck-typed seam, read through the one attribute the act needs
    (:func:`getattr` rather than an ``isinstance`` gate, because the module
    loader serves a composed application a second class object of the same
    shape — :mod:`regime.census`'s argument for its own seam, restated).  A
    bare string is accepted: a world id *is* the whole of what is being
    persisted here, so a caller that holds only the name is not made to invent
    a wrapper around it.
    """
    if isinstance(world, str):
        return _validated_world_id(world)
    stated = getattr(world, WORLD_ID_COLUMN, None)
    if stated is None:
        raise BackfillProvenanceError(
            f"{NO_ORIGIN_CODE}: a backfilled world is read through its "
            f"{WORLD_ID_COLUMN} — got {world!r} ({type(world).__name__}), "
            "which states none; the world's id is the string its originating "
            "campaign is read out of, so an object that cannot name itself "
            "cannot have an origin recorded for it (feature 288)"
        )
    return _validated_world_id(stated)


def _checked_against_id(world: Any, provenance: BackfillProvenance) -> None:
    """Refuse a carrier whose stated origin disagrees with its own world id.

    The masquerade check, and the reason the last paragraph of the module
    docstring calls deriving rather than accepting load-bearing.  Feature 287's
    world carries only ``world_id`` and ``regime_rows``, so nothing here
    *requires* a stated campaign — but a carrier that volunteers one is
    checked, because a world whose id names one campaign while its own field
    names another is a world whose provenance is ambiguous, and the one thing
    this store must never do is pick a half to believe.  A disagreement is
    refused naming both values, so the operator sees the *two* spellings that
    must be reconciled in the configuration they came from.
    """
    for attribute, derived in (
        (CAMPAIGN_ID_COLUMN, provenance.campaign_id),
        (EPOCH_ID_COLUMN, provenance.epoch_id),
    ):
        stated = getattr(world, attribute, None)
        if stated is None:
            continue
        if not isinstance(stated, str) or stated.strip() != derived:
            raise BackfillProvenanceError(
                f"{NO_ORIGIN_CODE}: the world {provenance.campaign_id!r}"
                f"{WORLD_ID_SEPARATOR}{provenance.epoch_id!r} states "
                f"{attribute}={stated!r}, which disagrees with the "
                f"{attribute} its own id carries ({derived!r}); a backfilled "
                "world's origin is read out of its identity, and a world that "
                "states two origins has none a reader could rely on — the "
                "spelling that must be corrected is the one the caller "
                "assembled the world with (feature 288)"
            )


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation every store in this workspace restates — feature
    :func:`regime.coverage._sqlite_path`'s, in this module's own words, because
    every store here restates it rather than reaching into a sibling's private
    helper.  A non-SQLite scheme and a pathless URL are refused by name; an
    in-memory database is refused because the record must outlive the call that
    wrote it — the dreaming loop reads the pool's worlds from another process
    entirely, between this process's calls.

    Raises :class:`~regime.errors.CoverageError`, **not** this feature's own
    class, and the choice is deliberate: an address this member cannot speak is
    an *address* fault with an address repair (point the deployment at the
    database the pool lives in), which is the face :class:`~regime.errors.
    CoverageError` already carries for the same variable.  The member keeps one
    vocabulary for one fault.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CoverageError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the backfilled "
            "worlds are recorded in (feature 288)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CoverageError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 288)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CoverageError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory store would die with the connection that opened it, and "
            "a backfilled world's origin must outlive the call that recorded "
            "it — the dreaming loop and the coverage endpoint read the pool's "
            "worlds from another process (feature 288)"
        )
    return Path(path)


# -- The records ------------------------------------------------------------------


@dataclass(frozen=True)
class BackfillProvenance:
    """Where a backfilled world came from — the two halves of its identity.

    The campaign the discovery tree belongs to, and the historical epoch the
    tree was replayed against: the pair feature 287 spelled into the world id
    and the whole of what makes a backfilled world distinguishable from a fresh
    one.  Frozen, for the same reason :class:`~regime.coverage.CoverageCount`
    and :class:`~regime.census.StratumAssignment` are — this value is the
    record of where a synthetic world came from, and a caller who could edit it
    in memory could re-type the pool's provenance without touching the row the
    dreaming loop reads.

    Validated in :meth:`__post_init__` rather than only through
    :func:`split_world_id`, because ``dataclasses.replace`` and unpickling both
    rebuild instances past a factory's nose — the argument
    :class:`~regime.coverage.CoverageCount` states for its own fields.
    """

    #: The campaign the stored discovery tree belongs to — the value every
    #: reader of the campaign row resolves (feature 232's minted key), and the
    #: originating campaign reference this feature persists.
    campaign_id: str
    #: The historical epoch the tree was replayed against — feature 88's
    #: sequestered-epoch key, taken as given.
    epoch_id: str

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the strips
        # below are normalization of the value into the record, the only write
        # this object ever takes.
        object.__setattr__(
            self, "campaign_id", _validated_text(self.campaign_id, "originating campaign")
        )
        object.__setattr__(
            self, "epoch_id", _validated_text(self.epoch_id, "epoch")
        )

    @property
    def originating_campaign(self) -> str:
        """The originating campaign reference — the feature's own words.

        An alias for :attr:`campaign_id` rather than a second field, so a
        caller reading the feature's sentence (``... with its originating
        campaign reference``) finds the name it was promised while the row
        keeps the column name feature 287's spelling and the campaign table
        both use.  One fact, two spellings a reader might reach for, and no
        second place for it to drift.
        """
        return self.campaign_id

    def row(self) -> dict[str, Any]:
        """The provenance as a store-shaped mapping — a fresh dict per call.

        Keyed by the column names the table records them under, so the value
        and the row cannot drift apart, and a fresh dict per call because a
        frozen value's rendered mapping is always fresh.
        """
        return {
            CAMPAIGN_ID_COLUMN: self.campaign_id,
            EPOCH_ID_COLUMN: self.epoch_id,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(campaign_id={self.campaign_id!r}, "
            f"epoch_id={self.epoch_id!r})"
        )


@dataclass(frozen=True)
class BackfilledWorldRecord:
    """One backfilled world's row, as the table holds it — feature 288's noun.

    The world's identity, the originating campaign reference derived from it,
    the epoch beside it, and the instant the world first entered the pool as a
    backfill.  Frozen and validated for the reasons the sibling records state,
    plus one this feature owns: the read path needs the *same* check the write
    path does, and here that check is sharper than a type test.  SQLite's
    columns are dynamically typed, so a raw ``INSERT`` from another tool can
    land a ``campaign_id`` that contradicts the ``world_id`` beside it, and a
    record that carried both without comparing them would hand a caller exactly
    the ambiguous provenance this feature exists to refuse.  So
    :meth:`__post_init__` re-derives the origin from the id and refuses a row
    whose stated half disagrees — :meth:`WorldBackfill._record_from_row`
    re-raises that refusal naming the world it came off.
    """

    #: The world's identity — feature 287's ``<campaign_id>@<epoch_id>``, and
    #: the name a ``replay_score`` row attributes its score to.
    world_id: str
    #: The originating campaign reference, read back out of the id.
    campaign_id: str
    #: The epoch the tree was replayed against, read back out of the id.
    epoch_id: str
    #: When the world first entered the pool as a backfill — the database's own
    #: stamp, read back rather than parsed.
    recorded_at: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "world_id", _validated_world_id(self.world_id))
        provenance = split_world_id(self.world_id)
        for field, derived in (
            ("campaign_id", provenance.campaign_id),
            ("epoch_id", provenance.epoch_id),
        ):
            stated = getattr(self, field)
            if stated != derived:
                raise BackfillProvenanceError(
                    f"{NO_ORIGIN_CODE}: the row for world {self.world_id!r} "
                    f"carries {field}={stated!r}, which disagrees with the "
                    f"{field} its own id spells ({derived!r}); a backfilled "
                    "world's origin is read out of its identity, so a row "
                    "stating two origins records none — and a reader that "
                    "believed either half would be counting a synthetic world "
                    "as something it is not (feature 288)"
                )
            object.__setattr__(self, field, derived)
        # The vintage is read back rather than parsed: the table stamps it with
        # ``datetime('now')`` (SQLite text, second resolution) and the honest
        # check on this side is only that the NOT NULL column carried
        # *something* — a NULL vintage is a row this member could not have
        # written, whatever wrote it.
        if self.recorded_at is None:
            raise BackfillProvenanceError(
                f"{NO_ORIGIN_CODE}: world {self.world_id!r} carries no "
                f"{RECORDED_AT_COLUMN}; the "
                "table declares the column NOT NULL because a recorded origin "
                "without an instant is not evidence of when the pool grew, so "
                "a row without one is not a record this store can report "
                "(feature 288)"
            )

    @property
    def provenance(self) -> BackfillProvenance:
        """The world's origin as its own value — the two halves, together."""
        return BackfillProvenance(
            campaign_id=self.campaign_id, epoch_id=self.epoch_id
        )

    @property
    def originating_campaign(self) -> str:
        """The originating campaign reference — the feature's own words."""
        return self.campaign_id

    def row(self) -> dict[str, Any]:
        """The record as a mapping — a fresh dict per call.

        The column names are the table's own, the discipline
        :meth:`regime.coverage.CoverageCount.row` states: a rendered mapping
        names the same things the same way the row does.
        """
        return {
            WORLD_ID_COLUMN: self.world_id,
            CAMPAIGN_ID_COLUMN: self.campaign_id,
            EPOCH_ID_COLUMN: self.epoch_id,
            RECORDED_AT_COLUMN: self.recorded_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(world_id={self.world_id!r}, "
            f"campaign_id={self.campaign_id!r}, epoch_id={self.epoch_id!r})"
        )


# -- The store --------------------------------------------------------------------


class WorldBackfill:
    """The store that records backfilled worlds with their origins — 288's act.

    Constructed with the database URL the record lives in;
    :meth:`record` seats one synthesized world, :meth:`get` reads one world's
    row back, :meth:`worlds` lists the backfilled half of the pool, and
    :meth:`is_backfilled` answers the feature's own question about a world id —
    *was this world written by a backfill, or is it fresh history?*  The class
    resolves its path lazily, so constructing one performs no I/O: composition-
    time work must not touch the disk, the contract every store here states.

    The store holds no cache of the rows it wrote, for the reason
    :class:`~regime.coverage.RegimeCoverage` states for its own: the row is the
    only record, so it is the only thing an answer is drawn from.  A memo of
    seated worlds would make *"is this world backfilled?"* a question about this
    process's history rather than about the pool, and the reader asking it — the
    dreaming loop, the coverage endpoint — runs in another process entirely.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the records live in.

        The URL is validated here, before any call, because it is a fact about
        the *store* rather than about any one world: a URL that is not a
        non-empty string names no table, and a store that accepted one would
        fail identically on every record — the wrong place for a deployment to
        discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise CoverageError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL; the "
                "backfilled worlds are rows in the database the deployment "
                "names, and a store pointed at nothing has nowhere to record "
                "an origin (feature 288)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> WorldBackfill | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which records no
        backfilled world — a discoverable state, not an exception — while the
        caller that must seat a world before anything counts it is the caller
        that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store records into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the records, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the store's database, ensuring the table exists.

        ``CREATE TABLE IF NOT EXISTS`` on first use — the contract every store
        in this workspace states, and the reason this feature needs no
        migration in the shared chain: a fresh database, one the coverage
        ledger already lives in, and one a migration built all take the same
        write path, and the statement is idempotent against a table this store
        has already created.  The caller owns the connection; use it as a
        context manager to commit, which is what every write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    # -- Feature 288: the record --------------------------------------------

    def record(self, world: Any) -> BackfilledWorldRecord:
        """Record one backfilled world with its originating campaign — 288's act.

        The steps, in the order they must happen:

        1. **Read the world's identity** off the carrier (or take a bare world
           id as itself) and derive its origin by splitting the id — before
           anything is opened, so a malformed ask is refused without touching a
           database.
        2. **Check a volunteered origin against the id.**  A carrier that also
           states ``campaign_id`` or ``epoch_id`` has those compared rather
           than believed; a disagreement is the masquerade and is refused.
        3. **Write, keeping whatever is already there.**  An insert that
           conflicts on the world id does nothing, so the first seating stands
           and a later one is a no-op.  This is idempotent in the *engine*
           rather than by a read-then-write, because a batch backfill re-run
           is exactly the case two workers can race on, and the loser of that
           race must not see a raw ``sqlite3.IntegrityError`` out of a member
           act.  There is no update arm — the origin is derived from the
           identity, so there is no second value an update could carry.
        4. **Read back and answer with the row**, inside the same transaction
           as the write, so the origin and the vintage in the answer are the
           table's own.  A world already seated returns its standing row,
           vintage included: the instant is when the world first entered the
           pool as a backfill, which a retry did not move.

        Refuses, in this order, each naming what it is about: a world that
        states no origin, or states one disagreeing with its own id
        (:class:`~regime.errors.BackfillProvenanceError`, opening the
        ``no_origin`` code); a ``DATABASE_URL`` this member cannot speak (the
        same class, by name); and a stored row whose halves contradict each
        other or whose vintage is absent (the first class, naming the world it
        came off).
        """
        world_id = _world_id_of(world)
        provenance = split_world_id(world_id)
        _checked_against_id(world, provenance)
        with closing(self._connect()) as connection, connection:
            # The write is a no-op when the world is already seated, and the
            # read below is what answers either way.  No branch on a prior
            # read: a re-issued record is reconciled by the primary key rather
            # than by a read another process can invalidate between the two
            # statements, so a re-run of the backfill — the ordinary case —
            # returns the standing row, vintage included, whether or not a
            # concurrent worker seated it a moment earlier.
            connection.execute(
                _INSERT_ROW_SQL,
                (world_id, provenance.campaign_id, provenance.epoch_id),
            )
            row = _read_row(connection, world_id)
        if row is None:
            raise BackfillProvenanceError(
                f"{NO_ORIGIN_CODE}: world {world_id!r} could not be read back "
                "after recording it; a recorded origin must be accounted for, "
                "and a row that cannot be re-read is a seating this store "
                "cannot vouch for (feature 288)"
            )
        return self._record_from_row(row)

    def get(self, world_id: Any) -> BackfilledWorldRecord | None:
        """One world's row, or ``None`` when the store holds none.

        ``None`` means *this world was not recorded by a backfill through this
        store* — the honest answer for a name the table does not hold, and the
        fact that keeps a fresh world distinguishable from a synthetic one.  It
        does **not** mean the read failed: an unreachable database raises, so a
        caller can never mistake a broken store for a fresh world.  Reading
        validates what it reads — a row whose stated origin contradicts its own
        id is refused naming the world, and a row with no vintage is refused —
        because a read that swallowed a corrupt row would hand a caller a
        provenance nobody recorded.

        Deliberately a *one-world* read.  The backfilled half of the pool as a
        whole is :meth:`worlds`, and the question the feature's sentence turns
        on is :meth:`is_backfilled`.
        """
        name = _validated_world_id(world_id)
        with closing(self._connect()) as connection:
            row = _read_row(connection, name)
        if row is None:
            return None
        return self._record_from_row(row)

    def is_backfilled(self, world_id: Any) -> bool:
        """Whether a backfill recorded this world — the feature's own question.

        ``True`` iff the store holds a row for the id, which is exactly the
        question *"did a backfill write this world, or is it fresh history?"*
        as far as this member can answer it.  The honest scope is worth stating
        rather than glossing: this store is the only place a backfill's output
        is recorded, so a world it does not hold was not written by a backfill
        *through this store* — which for a world that exists at all in this
        deployment is the fresh case, because this member is the only writer of
        synthetic worlds.  It does not read feature 188's ``bootstrap_world``
        and does not claim to: an id that names no world anywhere answers
        ``False``, because nothing recorded it as backfilled.

        A blank or non-text id is refused rather than answered ``False`` — a
        name that states nothing is a malformed ask, not a fresh world, and the
        two must not collapse into one answer.
        """
        return self.get(world_id) is not None

    def worlds(self) -> tuple[BackfilledWorldRecord, ...]:
        """Every recorded backfilled world, ordered by ``world_id``.

        The pool's backfilled half, enumerated — the listing feature 191's
        ``ported_worlds()`` is for the ported half, and the one a report of the
        pool's composition reads.  Ordered by the table's key, so two reads of
        one store are comparable, and a tuple rather than a live cursor because
        the answer is a value the caller keeps rather than a view that changes
        under it.
        """
        with closing(self._connect()) as connection:
            cursor = connection.execute(_LIST_ROWS_SQL)
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return tuple(self._record_from_row(row) for row in rows)

    # -- The words ----------------------------------------------------------

    def _record_from_row(self, row: tuple[Any, ...]) -> BackfilledWorldRecord:
        """Build a record from a row, with the world named on refusal.

        The read path's one constructor, so every read-back in the store builds
        the value the same way.  A validation refusal raised from the row names
        the world it came off — the difference between an operator learning
        *this world's row is corrupt* and learning only that some row somewhere
        is.
        """
        world_id = row[0]
        try:
            return BackfilledWorldRecord(
                world_id=world_id,
                campaign_id=row[1],
                epoch_id=row[2],
                recorded_at=row[3],
            )
        except BackfillProvenanceError as exc:
            # The inner message is already prefixed with the code (every
            # refusal in this module is), so it is stripped before re-framing:
            # one refusal carries one ``no_origin``, not two.  The code is a
            # greppable marker for the *fact*, and a doubled one would read as
            # two failures where an operator has one row to go and look at.
            detail = str(exc)
            prefix = f"{NO_ORIGIN_CODE}: "
            detail = detail.removeprefix(prefix)
            raise BackfillProvenanceError(
                f"{NO_ORIGIN_CODE}: the backfilled-world row for {world_id!r} "
                f"could not be read as a recorded origin: {detail}"
            ) from exc

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def _read_row(
    connection: sqlite3.Connection, world_id: str
) -> tuple[Any, ...] | None:
    """One world's row as the table holds it, or ``None`` when absent."""
    cursor = connection.execute(_READ_ROW_SQL, (world_id,))
    try:
        return cursor.fetchone()
    finally:
        cursor.close()


# -- The module-level spelling -----------------------------------------------------


def record_backfilled_world(
    world: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> BackfilledWorldRecord:
    """Record one backfilled world — the module-level spelling of 288's act.

    The feature's sentence as one call, for the caller that wants the act
    without holding a store: the synthesized world in, the stored row out.  The
    store is resolved from ``database_url``, else from ``DATABASE_URL``; a
    deployment that names neither is refused *by name* rather than silently
    doing nothing, because a record that quietly skipped its write would leave
    the pool holding synthetic worlds indistinguishable from fresh history —
    §C7's coverage number inflated by worlds the system never ran, discovered
    at the promotion gate that reads it.

    A :class:`~regime.errors.BackfillProvenanceError` from the store propagates
    unwrapped: the refusal already names the world and the fact, and re-wrapping
    it here would put a second message in front of the one an operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise CoverageError(
            "record_backfilled_world records a synthesized world's origin and "
            f"nothing names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so the world could not be recorded. "
            "A backfilled world that is not recorded is a synthetic world the "
            "pool counts as fresh history — the masquerade this feature exists "
            "to prevent (feature 288)"
        )
    return WorldBackfill(url).record(world)
