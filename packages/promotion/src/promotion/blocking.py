"""Persisting the reason a promotion is blocked on regime coverage — feature 299.

app_spec.xml, "Promotion & Epoch Governance", feature 299: *System persists a
blocking reason for a promotion whose deployment regime coverage sits below
threshold.*  Its declared parent is feature 291 — the pre-registration store —
and docs/alpha-engine-prd.md §C7 is the rule the sentence serves: *"**Block
promotion** when the regime being deployed into has coverage below
threshold."*  §14's risk table files the hazard that rule answers as **High** —
*"Replay pool is regime-monotone"* — with *"§C7 coverage ledger with promotion
block"* as its stated mitigation, and this module is the half of that block
that **outlives the call that made it**.

**The finding is feature 285's; the record is this feature's.**  The judgment
itself already exists: :func:`regime.promotion.rejects_undercovered_promotion`
refuses a promotion whose target regime's count sits below the configured
threshold, raising ``PromotionCoverageError`` with a message opening
``coverage_below_threshold``.  That module's own docstring reserves *this* half
by name — *"feature 299's blocking reason is the persisted record of exactly
this finding"* — and two things follow from that.  First, this feature does
**not** re-judge: it does not read the coverage ledger, does not ask whether the
pool covers a regime, and does not re-implement 285's verdict, which is why
there is no ``sqlite3`` read of ``regime_coverage`` anywhere below.  Second,
this feature does not *import* 285 either: no member imports another, so the
code word is **restated** (:data:`~promotion.errors.PROMOTION_BLOCK_ERROR_CODE`)
the way the workspace restates every shared spelling, and ``regime.promotion``
says from its own side that the promotion plugin's features reach it this way.

**Why a persisted reason at all, when the refusal already raises.**  Because a
raised exception is a fact about *a call* and the block is a fact about *a
promotion*.  §C7's ledger exists — in the PRD's own words — so the pool's skew
is *visible*; a refusal that only raised would make the block visible to the
process that happened to ask, and the questions anyone actually asks about a
promotion arrive later and from somewhere else: why is this node not promoted,
what was the count when it was blocked, is this block still live.  A row is
readable by a process that never made the call, which is the same argument
feature 291 makes for recording a criteria hash rather than returning it.

**The reason is prose, and it is derived rather than accepted.**  The persisted
value is the canonical sentence :func:`blocking_reason` renders — *"the target
deployment regime 'crash' holds 0 stored worlds, below the configured coverage
threshold of 5"* — the shape ``universe.monthly.floor_exclusion_reason``
established for this workspace's other persisted reason, and for the same
stated reason: *prose a human can audit, not a code a human has to look up*.
The caller does **not** supply it.  A caller-supplied string would be a second
description of one finding — free to disagree with the figures stored beside it,
and free to be edited by whoever calls this — and the whole value of the column
is that a later reader can trust it.

**The sentence is derived on read, and the figures are what is stored.**  The
row carries the regime, the count and the threshold as columns;
:attr:`PromotionBlock.reason` renders the sentence from them.  That is the
opposite of the tempting shortcut of storing only the prose: a stored sentence
is unqueryable, and §C7's ledger is read by *asking it questions* — how many
promotions were blocked below a threshold of 5, which regimes are implicated. It
also means the prose can never drift from the numbers it describes, because
there is only one copy of each number and the sentence is a function of it.  The
figures are rendered with plain ``repr`` per the same precedent: integers
round-trip exactly, so identical blocks persist byte-identical reasons and two
rows for one state are *comparable* rather than merely similar.

**A record that contradicts itself is refused, and that is not a re-judgment.**
§C7's block holds exactly when the target regime's count is **below** the
threshold — count ``>=`` threshold means the pool covers the regime and the
promotion stands.  So :meth:`PromotionBlocks.record_block` refuses a call whose
own two figures do not state a below-threshold state, because the row it would
write would open with *"below the configured coverage threshold of 5"* beside a
count of 40, and a stored row that lies is worse than no row at all.  What this
is **not** is this store judging the promotion: it never reads the ledger, never
learns what the pool holds, and takes the caller's figures as *the evidence the
caller gathered*.  It checks only that the evidence is consistent with the
finding it is being persisted as — the move feature 289 makes when it refuses a
diversity claim its own reading does not support — and the repair is to the
call, not to the pool.  A caller that believes the coverage is fine does not
record a block; it re-reads the ledger (feature 284) and re-runs the gate
(feature 285).

**Why a table of this member's own rather than a column on
``promotion_registry``.**  This is the design question the feature has to
answer, and this member's own docstring records that the other answer was
available: *"299's blocking reason is one more column's worth of state on a
decision."*  Three reasons, each checkable rather than aesthetic.

1. **``promotion_registry``'s six columns are the spec's, and the spec has no
   seventh.**  ``app_spec.xml``'s ``database_schema`` block declares the table
   and the ``CHAR(64)`` hash width; the migration tree that owns the DDL stops
   at ``0108``, and this member may not edit it.  A column added by ``ALTER
   TABLE`` at runtime would be a second, dialect-dependent spelling of a shared
   table's shape added by a member that does not own it — the drift
   :mod:`promotion.schema` exists to prevent.  Feature 240's probe-plus-``ALTER``
   is the shipped convention for a column *the schema names and no migration
   creates*; here the schema names no such column at all, which is the opposite
   situation.
2. **A blocked promotion is a different noun from a pre-registered one.**  The
   registry row answers *what was expected of this promotion*; the block answers
   *why it did not happen*.  Different writers, different lifetimes (a
   pre-registration is written before the evaluation; a block only if it fails),
   different readers.  Widening the registry would make every reader of §13 item
   7's record carry a column that is null for every promotion that succeeded —
   and nullable is the only shape ``ADD COLUMN`` can give a populated table, so
   the design would be *forced* into exactly that.
3. **The store's read is a shape the registry cannot answer.**
   :meth:`PromotionBlocks.blocked` must answer *is this node blocked, and why*
   for a node that may hold no registry row, and it must refuse that case by
   name.  That is a probe over the *decision*, natural against a table keyed by
   ``node_id`` and awkward bolted onto a row that already has an identity.

What the column reading got **right**, and what is kept: a block is state about
one decision, written once and never revised, read back by node.  All three
survive in the shape below — ``node_id`` is the primary key, there is no update
path, and both reads are by node.

**Why the member's no-DDL law does not forbid this table.**  ``promotion.schema``
authors no DDL and the claim is enforced by tests; this module does author one
``CREATE TABLE IF NOT EXISTS``.  The law is *this member writes no DDL for the
tables the migration tree owns* — ``node``, ``epoch_ledger`` and
``promotion_registry`` are declared by ``0118``, ``0110`` and ``0108``, so a
second spelling here would be drift, and that is what the tests catch.  A table
the tree does not declare is the feature's own to declare: the same
``CREATE TABLE IF NOT EXISTS`` on first use that ``regime_coverage`` (feature
283), ``backfilled_world`` (288), ``bootstrap_world`` (188) and the canary halt
table (143) all ship, each in the store that is its only writer.  So
:meth:`PromotionBlocks._connect` runs :func:`promotion.schema.bootstrap_schema`
for the three shared tables and then creates this one, and neither statement
touches a table the other owns.

**One row per node, and a re-block returns the standing row untouched.**  The
table's identity is the node (``node_id`` is the primary key), the same identity
feature 291's registry row has, and the reasoning is the same: there is one
promotion per node, so there is one block per node.  A second ``record_block``
for a node the store already holds returns the standing row **byte for byte**,
``blocked_at`` included — the stance feature 288's ``record`` takes toward a
re-seated world.  That is not a convenience: the blocked instant is *when the
promotion was blocked*, and a caller that walked the gate again did not move it,
in the same way a retried pre-registration does not move ``pre_registered_at``.
The write is therefore idempotent in the *engine* (``ON CONFLICT DO NOTHING``)
rather than by a read-then-insert race, which is what keeps a raw
``sqlite3.IntegrityError`` from surfacing out of a member act.

**A block is about a decision, and that is a precondition rather than a
detail.**  The row is keyed by ``node_id`` and carries a foreign key to
``node`` — a block hangs off a hypothesis the tree holds, the structural law
every table in this workspace states.  But the *semantic* precondition is
stronger and is checked by probe: the node must already hold a
``promotion_registry`` row.  §13 item 7 fixes a promotion's criteria *before*
the evaluation that decides them, and a blocking reason is a statement about
*that* promotion, so recording one for a node that was never pre-registered
would be a reason for a decision nobody opened.  The store refuses that case by
naming the repair — pre-register first — rather than leaving it to a foreign
key, because SQLite's ``IntegrityError`` names no node and the two repairs
differ.  The probe is also why this feature's ``depends_on="291"`` is load
bearing rather than bibliographic.

**The named-empty row and the never-named absence — inherited, not re-derived.**
``0107`` detail 1 is the load-bearing distinction under every read in this
member, and feature 285 spends a paragraph on it because collapsing it *there*
would block a promotion on an unknown.  This feature inherits the distinction
rather than deciding it again: 285 refuses an un-named regime **separately**
from a low count, with a different repair, so a caller that reaches this store
at all has already been told which it is.  What this store must keep apart is
the *other* pair — a promotion that was blocked, and one that was not — and it
does so by **absence**: a node with no row here is not *blocked with a reason of
nothing*, it is *not blocked through this store*.
:meth:`PromotionBlocks.blocked` answers ``None`` for that node rather than a
record carrying a zero, and :meth:`PromotionBlocks.is_blocked` is the boolean
face of the same question.

**No component, no seat, no router, no second builder.**  The member's
registered surface stays feature 291's one store: a builder takes no arguments
and is built on every ``create_app()`` call, while this store's acts are
functions of evidence the factory does not hold — a gate's verdict, a reading, a
count.  So the store is constructed from a URL by the caller that has one,
exactly as every sibling act in this workspace is, and the member still exports
exactly one ``build_*`` name.  The seat
(``src/app/modules/promotion``) is untouched and still answers one question, and
nothing here edits a registry, router table or app factory.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime`` and
``contextlib`` at module scope and nothing else: no third-party import and no
import of another workspace member, so the factory's scan imports this package
for the near-nothing it always did and a blocked promotion costs its caller only
the connection it already had.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import (
    PROMOTION_BLOCK_ERROR_CODE,
    PromotionBlockError,
    PromotionError,
    PromotionStoreError,
)
from .pre_register import (
    DATABASE_URL_ENV,
    NODE_ID_COLUMN,
    _sqlite_path,
    _validated_instant,
    _validated_uuid,
    utc_now,
)

__all__ = [
    "BLOCKED_AT_COLUMN",
    "COVERAGE_THRESHOLD_COLUMN",
    "NODE_TABLE",
    "PROMOTION_BLOCK_TABLE",
    "REGIME_COLUMN",
    "WORLD_COUNT_COLUMN",
    "PromotionBlock",
    "PromotionBlocks",
    "blocked_promotion",
    "blocking_reason",
    "record_block",
]
from .schema import PROMOTION_REGISTRY_TABLE, bootstrap_schema

#: The database variable every store in this workspace reads.  Deliberately
#: **not** re-spelled as a second literal: this member spells it once, in
#: :mod:`promotion.pre_register`, and a second spelling would be a second thing
#: to keep in sync in a module whose whole point is that one database is named.

#: This feature's table.  Not declared by any migration and therefore this
#: feature's to declare — see the module docstring's no-DDL paragraph.  The name
#: reads *the block on a promotion*, which is what a row is, and it is spelled
#: here once so the store, the tests and an operator's ``SELECT`` agree.
PROMOTION_BLOCK_TABLE = "promotion_block"

#: The hypothesis the block is about — the row's primary key, and the same
#: identity ``promotion_registry`` keys its own rows by (one promotion per node).
#: Deliberately **not** re-spelled as a second literal: this member spells the
#: column once, in :mod:`promotion.pre_register`, and a block that named the node
#: in a second spelling would be a row feature 291's readers could not join on.

#: ``node``, feature 232's campaign tree, restated rather than imported: this
#: member's one ``REFERENCES`` clause needs the name, and a rename on the
#: discovery side would otherwise leave this table pointing at nothing.
NODE_TABLE = "node"

#: The target deployment regime — a stratum name, in feature 283's vocabulary.
#: Stored as text and never normalised beyond stripping: the vocabulary is the
#: labeler's configuration, and a store that case-folded names would be silently
#: renaming a stratum a deployment configured.
REGIME_COLUMN = "regime"

#: The count §C7's finding is *about*: how many stored worlds the target regime
#: held in the reading the gate judged.  Stored beside the threshold so the
#: block is auditable without the ledger row it came from — the ledger moves, and
#: this row is the record of what it said when the promotion was stopped.
WORLD_COUNT_COLUMN = "world_count"

#: The deployment's own threshold — feature 285's required keyword, persisted
#: because *"below threshold"* names no figure without it.
COVERAGE_THRESHOLD_COLUMN = "coverage_threshold"

#: When the promotion was blocked.  Written once; there is no update path.
BLOCKED_AT_COLUMN = "blocked_at"

#: The row's columns, in the order every statement here names them and
#: :meth:`PromotionBlock.row` renders them.  Spelled once so the write and the
#: reads cannot drift apart on a column order — the failure a positional
#: ``SELECT *`` invites, the discipline ``canary._halt._COLUMNS`` states.
_COLUMNS = (
    f"{NODE_ID_COLUMN}, {REGIME_COLUMN}, {WORLD_COUNT_COLUMN}, "
    f"{COVERAGE_THRESHOLD_COLUMN}, {BLOCKED_AT_COLUMN}"
)

#: This feature's one piece of DDL.  ``IF NOT EXISTS`` on first use, the
#: contract every store in this workspace states: a fresh database, one the
#: migrations already built and one this store created earlier all take the same
#: path, and running it twice changes nothing.
#:
#: ``node_id`` is the primary key *and* a foreign key — the structural law, a
#: block hangs off a hypothesis the tree holds — and the ``REFERENCES`` clause
#: names ``node(id)`` exactly as ``promotion_registry`` does, rather than
#: ``promotion_registry(node_id)``, which SQLite refuses: a foreign key's parent
#: columns must be unique, and the registry's node column deliberately is not
#: (its ``id`` is the key).  The decision that a block is *about* is therefore
#: established by probe, not by a constraint — see the module docstring.
#:
#: ``blocked_at`` is ``NOT NULL`` with no ``DEFAULT``: the instant is supplied by
#: the writer (or by this member's own ``utc_now``), and a row whose stamp came
#: from the engine would be a stamp the caller cannot route through a clock.  It
#: is TEXT because that is what the writer stores — an ISO-8601 aware instant,
#: the spelling feature 291's ``pre_registered_at`` uses — read back through the
#: same validator that checked it on the way in.
_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {PROMOTION_BLOCK_TABLE} (
    {NODE_ID_COLUMN}            TEXT NOT NULL PRIMARY KEY
                                 REFERENCES {NODE_TABLE}(id),
    {REGIME_COLUMN}             TEXT NOT NULL,
    {WORLD_COUNT_COLUMN}        INT NOT NULL,
    {COVERAGE_THRESHOLD_COLUMN} INT NOT NULL,
    {BLOCKED_AT_COLUMN}         TEXT NOT NULL
)
"""

#: The read-back, column by column rather than ``SELECT *``, so a later column
#: added to this table cannot silently shift the fields the record unpacks.
_READ_ROW_SQL = (
    f"SELECT {_COLUMNS} FROM {PROMOTION_BLOCK_TABLE} "
    f"WHERE {NODE_ID_COLUMN} = ?"
)

#: Every block, in the table's own total order — the listing a report reads.
#: Ordered by the key for the reason every listing in this workspace is: two
#: reads of one store must be comparable.
_LIST_ROWS_SQL = (
    f"SELECT {_COLUMNS} FROM {PROMOTION_BLOCK_TABLE} "
    f"ORDER BY {NODE_ID_COLUMN}"
)

#: The write.  ``ON CONFLICT DO NOTHING`` rather than a plain ``INSERT``, and the
#: reason is atomicity rather than convenience: a read-then-insert is a race in
#: which two processes both read no row, both write, and the loser gets a raw
#: ``sqlite3.IntegrityError`` out of a member act — a DBAPI exception where this
#: member's ``coverage_below_threshold`` vocabulary belongs.  Keeping whatever is
#: already there is also the *behaviour* the docstring promises: a re-block
#: returns the standing row rather than moving the instant.
_INSERT_ROW_SQL = (
    f"INSERT INTO {PROMOTION_BLOCK_TABLE} ({_COLUMNS}) "
    "VALUES (?, ?, ?, ?, ?) "
    f"ON CONFLICT ({NODE_ID_COLUMN}) DO NOTHING"
)

#: The probe that makes a block *about a decision*.  It reads the registry
#: rather than trusting a foreign key, because SQLite's ``IntegrityError`` names
#: no node and the repair here is specific: pre-register the promotion first
#: (feature 291), which is §13 item 7's ordering.
_DECISION_EXISTS_SQL = (
    f"SELECT 1 FROM {PROMOTION_REGISTRY_TABLE} "
    f"WHERE {NODE_ID_COLUMN} = ? LIMIT 1"
)

#: **No sentinel, and why that is not an oversight.**  Feature 285 and feature
#: 283's ledger both carry an ``_ABSENT`` object to keep *the row says zero*
#: apart from *there is no row*, because there a count of zero is a legitimate
#: value and a lookup default of ``None`` would collapse a named-empty stratum
#: into an un-named one.  Nothing here has that shape: an absent row is answered
#: by ``cursor.fetchone()`` returning ``None``, and a *present* row always yields
#: a fully-validated :class:`PromotionBlock` — a record that could be confused
#: with the absence would have to be falsy or ``None``, and it is neither.  The
#: two states are therefore already distinguishable by type, and a sentinel would
#: be a third spelling of a distinction that costs nothing to keep.


# -- The reason, as prose -----------------------------------------------------------


def blocking_reason(regime: str, world_count: int, threshold: int) -> str:
    """The one canonical reason a coverage block is persisted with.

    Names all three figures — the target deployment regime, the stored-world
    count the pool held for it, and the threshold that count fell short of — so a
    single row explains itself without the ledger read beside it.  That is the
    whole point of persisting a reason rather than a code: an operator who finds
    this row months later learns *which regime was thin* and *how thin* from the
    sentence alone, and does not have to reconstruct either from a ledger that
    has moved on since.

    Formatted with plain ``repr`` for the reason
    ``universe.monthly.floor_exclusion_reason`` states for its own persisted
    reason: the figures round-trip exactly and are stable across runs, so
    identical blocks persist byte-identical reasons and two rows for one state
    are *comparable* rather than merely similar.  The count is singularised at
    one — *"1 stored world"* — because a persisted reason is read by a human
    before it is read by anything else.

    The threshold is named as *the configured* threshold, which is the
    deployment's number and not this member's: feature 285 requires it rather
    than defaulting it, and the sentence keeps that provenance visible.  §C7 is
    named last so a reader who wants the rule rather than the figures knows
    where to look.
    """
    worlds = "world" if world_count == 1 else "worlds"
    return (
        f"the target deployment regime {regime!r} holds {world_count!r} "
        f"stored {worlds}, below the configured coverage threshold of "
        f"{threshold!r}; docs/alpha-engine-prd.md §C7 blocks a promotion "
        "when the regime being deployed into has coverage below threshold"
    )


# -- The row ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromotionBlock:
    """One ``promotion_block`` row, as the table holds it.

    The five fields are the table's five columns.  Frozen, so a row that has
    been read back cannot be edited into a different count by a caller who kept
    a reference — the discipline every record in this workspace states, and the
    one that matters here because this value is *the record of why a promotion
    did not happen*: a mutable one would let a caller retype the count in memory
    while the row said otherwise, which is the same forgery in miniature that
    §13 item 7 exists to prevent for criteria.

    Validated in :meth:`__post_init__` rather than only through the store,
    because ``dataclasses.replace`` and unpickling both rebuild instances past a
    factory's nose — and because the *read* path needs the same check the write
    path does: SQLite's columns are dynamically typed, so a hand-edited row is
    reachable here, and a block read that swallowed one would report a reason
    nobody wrote.

    :attr:`reason` is derived rather than stored, so the prose and the figures
    cannot disagree: there is one copy of each number and the sentence is a
    function of it.
    """

    #: The hypothesis whose promotion was blocked — the row's key.
    node_id: str
    #: The target deployment regime whose coverage fell short.
    regime: str
    #: How many stored worlds the pool held for it, in the reading judged.
    world_count: int
    #: The threshold the count fell short of — the deployment's own number.
    coverage_threshold: int
    #: When the promotion was blocked.
    blocked_at: Any

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the same
        # discipline feature 291's record and the criteria value follow.
        object.__setattr__(self, "node_id", _block_node_id(self.node_id))
        object.__setattr__(self, "regime", _validated_regime(self.regime))
        object.__setattr__(
            self, "world_count", _validated_count(self.world_count, WORLD_COUNT_COLUMN)
        )
        object.__setattr__(
            self,
            "coverage_threshold",
            _validated_count(self.coverage_threshold, COVERAGE_THRESHOLD_COLUMN),
        )
        # The *relation* between the two counts, not just their shapes — and it
        # belongs here for exactly the reason the fields above do: the read path
        # rebuilds this value from a row, and SQLite's dynamic typing means a
        # hand-edited or foreign-written row can carry a covered pair just as
        # easily as a malformed one.  Without this, such a row reads back as a
        # block whose reason says *"holds 999 stored worlds, below the configured
        # coverage threshold of 5"* — the stored row that lies, which is the
        # failure the write-side check exists to prevent and the one place a
        # reader cannot repair by re-reading the ledger, because a reader has no
        # ledger read to re-run.  ``record_block`` still calls it early and in
        # its own order; this is the same function, so a write refusal is
        # unchanged in class, code word, message and position.
        _validated_below_threshold(self.world_count, self.coverage_threshold)
        object.__setattr__(self, "blocked_at", _block_instant(self.blocked_at))

    @property
    def reason(self) -> str:
        """The persisted reason, rendered from this row's own figures.

        A property rather than a field, and that is the design: the sentence is
        a *view* over the three columns, so it cannot drift from them and cannot
        be edited by a caller.  :meth:`row` renders it under ``reason`` for a
        reader that wants the row and its explanation in one mapping.
        """
        return blocking_reason(
            self.regime, self.world_count, self.coverage_threshold
        )

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, plus ``reason``: the sentence has
        no column because it is derived, and it is rendered here so the dict a
        caller logs is the whole explanation, figures and prose together.
        """
        return {
            NODE_ID_COLUMN: self.node_id,
            REGIME_COLUMN: self.regime,
            WORLD_COUNT_COLUMN: self.world_count,
            COVERAGE_THRESHOLD_COLUMN: self.coverage_threshold,
            BLOCKED_AT_COLUMN: self.blocked_at,
            "reason": self.reason,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(node_id={self.node_id!r}, "
            f"regime={self.regime!r}, world_count={self.world_count!r}, "
            f"coverage_threshold={self.coverage_threshold!r}, "
            f"blocked_at={self.blocked_at!r})"
        )


# -- Validation --------------------------------------------------------------------


def _translated(exc: PromotionError, what: str) -> PromotionBlockError:
    """Re-raise a sibling's refusal in this feature's vocabulary.

    The seam rule this workspace states at every member boundary, applied
    *inside* one member: feature 291's validators raise ``PromotionError`` and
    its path translator raises ``PromotionStoreError``, and a caller whose
    ``except PromotionBlockError`` guards its promotion path must not be
    defeated by a refusal phrased for a different act — it would read *the
    registry could not be written to* where the truth is *the block could not be
    recorded*, and it would conclude the promotion is not blocked when it is.
    The inner message is carried through, so nothing an operator needs is lost;
    it is only re-framed, and the frame names which act was being performed.

    ``type(exc)(...)`` is deliberately **not** used, unlike
    :func:`promotion.pre_register._record_from_row`'s re-raise: there the class
    is already right and only the node needed adding, while here the class
    itself is the thing being corrected.

    The inner message keeps its own code word, deliberately unlike
    :meth:`PromotionBlocks._record_from_row`'s strip: there the two codes name
    the *same* finding, while here the inner one names a different *act*, and an
    operator reading a deployment fault wants to see both — that the block is
    what failed, and which of the sibling's faces said so.
    """
    return PromotionBlockError(
        f"{PROMOTION_BLOCK_ERROR_CODE}: the {what} could not be reached to "
        f"record this block: {exc}"
    )


def _block_node_id(value: Any) -> str:
    """Return ``value`` as a node identity, or refuse it in *this* vocabulary.

    Feature 291's identity validator is the one spelling of what a node column
    holds, so it is *used* rather than restated — a second UUID rule here would
    be a second answer to *is this the same hypothesis?*, and the two rows are
    joined by exactly this value.  What it raises is ``PromotionError``, the
    member's ask face, and that is the seam this wrapper exists for: a caller
    whose single ``except PromotionBlockError`` guards its promotion path must
    not be defeated by a refusal phrased for a pre-registration, because it
    would read *the body was malformed* where the truth is *this block was not
    recorded* — and would go on to deploy a promotion §C7 stopped.
    """
    try:
        return _validated_uuid(value, NODE_ID_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "node identity") from exc


def _block_instant(value: Any) -> dt.datetime:
    """Return ``value`` as an aware-UTC instant, or refuse it in this vocabulary.

    The same seam as :func:`_block_node_id`, over feature 291's stamp validator:
    the *rule* (aware, normalised to UTC, ISO-8601 text accepted so a row read
    back revalidates) is the member's one spelling and is used rather than
    restated; the *class* is translated, so a naive stamp handed to this store
    is refused as a blocking reason that could not be recorded rather than as a
    pre-registration that could not be written.
    """
    try:
        return _validated_instant(value, BLOCKED_AT_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "blocked instant") from exc


def _validated_regime(regime: Any) -> str:
    """Return ``regime`` as a stratum name, or refuse what cannot be one.

    Non-empty text, stripped — the rule feature 283's validator applies to a
    stratum, restated in this feature's vocabulary because no member imports
    another and the promotion plugin must not import the regime member to learn
    what a name is.  The near-miss a trailing newline would create is the reason
    for the strip: two spellings of one regime would persist as two regimes
    implicated in a block, and a later reader grouping by ``regime`` would see a
    stratum the labeler never configured.

    Nothing else is normalised, and that is deliberate for the reason
    ``0107``'s own words give: the stratum vocabulary is the labeler's
    configuration, so a store that case-folded or re-spelled names would be
    silently renaming a stratum a deployment configured — ``"Crash"`` and
    ``"crash"`` are two names, and the caller that wrote both is the one that
    must reconcile them, in the configuration they came from.
    """
    if not isinstance(regime, str) or not regime.strip():
        raise PromotionBlockError(
            f"{PROMOTION_BLOCK_ERROR_CODE}: the target deployment regime is a "
            f"stratum name — got {regime!r} ({type(regime).__name__}); feature "
            "299 persists the reason a promotion was blocked on the coverage of "
            "the regime it was being deployed into, and a target that is not a "
            "name names no regime whose coverage could have fallen short"
        )
    return regime.strip()


def _validated_count(value: Any, column: str) -> int:
    """Return ``value`` as a count of stored worlds, or refuse what is not one.

    A genuine non-negative integer.  ``bool`` is refused explicitly — ``True``
    is an ``int`` in Python, so a flag where a count belongs would be persisted
    as the number one — a negative number is refused because a count of stored
    worlds cannot be negative (§C6's excision empties a stratum, it never owes
    worlds), and a non-``int`` because a fractional world is not a world.  The
    rule is feature 283's count validator restated, and the *rule* is all that
    is restated: this is not where the threshold's own floor is enforced.

    **Shape, not merit, and the line is deliberate.**  This function checks that
    each figure *is a count*; it does not check that the pair of them states a
    block.  That second check is §C7's comparison, it belongs to feature 285,
    and it happens once, in :meth:`PromotionBlocks.record_block` where both
    figures are in hand — not here, where only one of them is.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PromotionBlockError(
            f"{PROMOTION_BLOCK_ERROR_CODE}: a block's {column} is a count of "
            f"stored worlds — got {value!r} ({type(value).__name__}); §C7's "
            "finding is drawn in worlds, and a number that is not a whole one "
            "is a count of nothing (a truthy flag is not a count of worlds, and "
            "a fractional world is not a world)"
        )
    if value < 0:
        raise PromotionBlockError(
            f"{PROMOTION_BLOCK_ERROR_CODE}: a block's {column} is at least 0 — "
            f"got {value!r}; §C6's tripwires excise worlds from the pool but "
            "never leave a regime owing them, so a negative count is not a "
            "number of stored worlds"
        )
    return value


def _validated_below_threshold(count: int, threshold: int) -> None:
    """Refuse a pair of figures that does not state a below-threshold block.

    §C7's comparison, performed once, on the two numbers the row will carry:
    the block holds exactly when the target regime's count is **below** the
    threshold, so ``count >= threshold`` is the pool *covering* the regime and
    the promotion standing.  A row written from such a pair would open with
    *"below the configured coverage threshold of 5"* beside a count of 40 — a
    stored row that lies, which is worse than no row at all, and the exact
    failure the reason's auditability is supposed to prevent.

    **This is not this store judging the promotion**, and the distinction is
    worth being precise about because the two look alike from outside.  The
    store never reads ``regime_coverage``, never learns what the pool holds and
    never decides whether coverage is adequate; it takes the caller's figures as
    *the evidence the caller gathered* and checks only that they are consistent
    with the finding they are being persisted as.  That is the move feature 289
    makes when it refuses a diversity claim its own reading does not support,
    and the repair differs from a gate refusal accordingly: this one is the
    *call* (re-read the ledger, re-run the gate, or do not record a block for a
    promotion the pool covers), not the pool.

    At exactly the threshold the promotion stands — feature 285's own asymmetry,
    a coverage floor rather than an upper edge — so equality is refused here too.
    """
    if count >= threshold:
        raise PromotionBlockError(
            f"{PROMOTION_BLOCK_ERROR_CODE}: the block states a regime holding "
            f"{count!r} stored worlds against a coverage threshold of "
            f"{threshold!r}, which is not below it. §C7 blocks a promotion when "
            "the regime being deployed into has coverage below threshold, so "
            "these two figures describe a regime the pool *covers* and a "
            "promotion that stands — and persisting them as a block would write "
            "a row whose own reason contradicts its own numbers. This store does "
            "not judge the promotion: it never reads the coverage ledger. "
            "Re-read the ledger (feature 284), re-run the gate (feature 285), "
            "and record a block only for a promotion that was in fact blocked"
        )


# -- The store ---------------------------------------------------------------------


class PromotionBlocks:
    """The store that records why promotions were blocked on coverage — 299's act.

    Constructed with the database URL the record lives in;
    :meth:`record_block` persists one node's blocking reason,
    :meth:`blocked` reads one node's block back, :meth:`is_blocked` answers the
    feature's own question about a node, and :meth:`blocks` enumerates every
    block the deployment has recorded.  The class resolves its path lazily, so
    constructing one performs no I/O: composition-time work must not touch the
    disk, the contract every store in this workspace states.

    The store holds no cache of the rows it wrote, for the reason
    :class:`~promotion.pre_register.PreRegistrations` states for its own: the row
    is the only record, so it is the only thing an answer is drawn from.  A memo
    of blocked nodes would make *why is this promotion not deployed?* a question
    about this process's history, and the reader asking it — an operator, a
    report, a later feature — runs somewhere else entirely.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the blocks live in.

        The URL is validated here, before any call, because it is a fact about
        the *store* rather than about any one block: a URL that is not a
        non-empty string names no table, and a store that accepted one would
        fail identically on every record — the wrong place for a deployment to
        discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise PromotionBlockError(
                f"{PROMOTION_BLOCK_ERROR_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL. The blocking reasons are rows in the "
                "database the deployment names, and a store pointed at nothing "
                "has nowhere to record why a promotion was blocked (feature 299)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> PromotionBlocks | None:
        """The block store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the way every store
        in this workspace treats its configuration.  Absent is not an error: it
        is a deployment without a relational store, and the caller that must
        record why a promotion was blocked is the caller that must not find
        itself in it — §C7's block whose reason went nowhere is a block nobody
        downstream can audit.
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
        """The SQLite file behind the blocks, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name, in *this* feature's
        vocabulary) the first time an operation needs it.
        """
        if self._path is None:
            try:
                self._path = _sqlite_path(self._database_url)
            except PromotionStoreError as exc:
                raise _translated(exc, "database address") from exc
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the store's database, bringing both schemas up.

        Two statements of intent, in the order that matters.

        **The shared schema.** :func:`promotion.schema.bootstrap_schema` runs the
        *migrations'* own ``statements("sqlite")`` for the three tables this act
        touches — ``node`` (0118), ``epoch_ledger`` (0110) and
        ``promotion_registry`` (0108) — so this store spells no column of any of
        them and cannot drift from their owners.  All three are ``CREATE TABLE IF
        NOT EXISTS``, so a fresh database, a fully migrated one and one this
        store created earlier take the same path.  The order is the chain's, not
        SQLite's demand: SQLite defers a foreign key's parent *table* to the
        first row written, so a table that referenced ``node`` is declared
        happily and then refuses at insert with ``no such table: main.node``.

        **This feature's table.** ``CREATE TABLE IF NOT EXISTS
        promotion_block`` — the one piece of DDL this member authors, and it
        authors it because no migration declares this table (the module
        docstring argues the boundary).  Running it against a database that
        already has it changes nothing, which is what lets a migrated deployment
        and a store-first one converge.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — SQLite's own default
        is off, so a store that skipped this would accept a block naming a node
        the tree does not hold.  The parent *decision* is checked by name before
        the insert regardless (see :meth:`record_block`), because the repairs
        differ by parent; the pragma is what makes the structural constraint hold
        against a hand that reaches past this store with a raw connection.

        The caller owns the connection; use it as a context manager to commit,
        which is what the write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                bootstrap_schema(connection)
                connection.executescript(_CREATE_TABLE_SQL)
        except PromotionError as exc:
            connection.close()
            raise _translated(exc, "database") from exc
        except sqlite3.Error as exc:
            connection.close()
            raise PromotionBlockError(
                f"{PROMOTION_BLOCK_ERROR_CODE}: the database at {path} could not "
                f"be brought to the revision a blocking reason needs: {exc}. The "
                f"{PROMOTION_REGISTRY_TABLE} table is created by migrations/"
                "versions/0108_forward_and_universe_tables.py and the two tables "
                "its foreign keys point at by 0118 and 0110; this store runs "
                "those files' own statements and authors none of its own, while "
                f"{PROMOTION_BLOCK_TABLE} is this feature's own table and is the "
                "only DDL this member writes (feature 299)"
            ) from exc
        return connection

    # -- Feature 299: the blocking reason ------------------------------------

    def record_block(
        self,
        node_id: Any,
        *,
        regime: Any,
        world_count: Any,
        threshold: Any,
        blocked_at: dt.datetime | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> tuple[PromotionBlock, bool]:
        """Persist why a promotion was blocked on coverage — feature 299's act.

        The steps, in the order they must happen:

        1. **Validate the finding** — the node as an identity, the regime as a
           stratum name, the count and the threshold as counts of worlds, and
           the pair of them as actually stating a below-threshold block — before
           anything is opened, so a malformed or self-contradicting finding is
           refused without touching a database, and a refused call leaves no row
           and no file behind.
        2. **Read the node's standing row.**  The table's identity is one row per
           node, so a node that already holds a block is a *re-block* rather than
           a second finding, and the standing row is returned untouched — see
           below.
        3. **Check the decision the block is about.**  The node must already hold
           a ``promotion_registry`` row, because §13 item 7 fixes a promotion's
           criteria before the evaluation that decides them and a blocking reason
           is a statement about *that* promotion.  Refused by name, with the
           repair, because SQLite's foreign key would name neither.
        4. **Write, keeping whatever is already there**, and read back inside the
           same transaction, so the answer is the table's own row rather than a
           value assembled from the arguments.

        **The idempotence is the behaviour and not an optimisation.**  A second
        ``record_block`` for a node the store already holds returns the standing
        row **byte for byte**, ``blocked_at`` included.  The blocked instant is
        *when the promotion was blocked*, and a caller that walked the gate
        again did not move it — the stance a retried pre-registration takes
        toward ``pre_registered_at`` and a re-seated backfilled world toward its
        own vintage.  A store that re-stamped would make the column a record of
        the last time somebody looked.

        **The reason is not an argument.**  There is no ``reason=`` parameter:
        the sentence is rendered by :func:`blocking_reason` from the figures
        being stored, so a caller cannot persist prose that disagrees with the
        row beside it.

        Refuses, in this order, each naming what it is about and all in
        :class:`~promotion.errors.PromotionBlockError`: a malformed node, a
        regime that is not a name, a count or threshold that is not a count of
        worlds, a pair of figures that does not state a below-threshold block,
        and then — from the store — a ``DATABASE_URL`` this member cannot speak,
        a node holding no pre-registration, and a row that did not land or could
        not be read back.

        ``blocked_at`` states the instant the promotion was blocked, and
        ``clock`` supplies the default when it is absent — tests and replays
        route their own time through it, the same seam
        :meth:`~promotion.pre_register.PreRegistrations.pre_register` offers.
        """
        node = _block_node_id(node_id)
        target = _validated_regime(regime)
        count = _validated_count(world_count, WORLD_COUNT_COLUMN)
        minimum = _validated_count(threshold, COVERAGE_THRESHOLD_COLUMN)
        _validated_below_threshold(count, minimum)
        stamped = (
            _block_instant(blocked_at)
            if blocked_at is not None
            else (clock or utc_now)()
        )
        with closing(self._connect()) as connection, connection:
            standing = _read_row(connection, node)
            if standing is not None:
                return self._record_from_row(standing), False
            self._require_decision(connection, node)
            try:
                connection.execute(
                    _INSERT_ROW_SQL,
                    (node, target, count, minimum, stamped.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise PromotionBlockError(
                    f"{PROMOTION_BLOCK_ERROR_CODE}: the blocking reason for node "
                    f"{node} could not be written: {exc}. The row names a node by "
                    "foreign key and this store checked the decision before "
                    "writing — so a constraint that refused anyway is a database "
                    "whose tables are not the ones this deployment migrated "
                    "(feature 299)"
                ) from exc
            written = _read_row(connection, node)
        if written is None:
            raise PromotionBlockError(
                f"{PROMOTION_BLOCK_ERROR_CODE}: the blocking reason for node "
                f"{node} could not be read back after the write. §C7's block has "
                "to be auditable from what was written — that is the whole of "
                "why the reason is persisted rather than only raised — and a row "
                "that cannot be re-read is a block this store cannot vouch for "
                "(feature 299)"
            )
        return self._record_from_row(written), True

    # -- Feature 299: the reads ---------------------------------------------

    def blocked(self, node_id: Any) -> PromotionBlock | None:
        """One node's block, or ``None`` when this store holds none.

        ``None`` means *this promotion was not blocked through this store* — and
        the honest scope of that phrase is worth stating rather than glossing: a
        promotion that cleared §C7's threshold has no block to record, and a
        promotion blocked in a deployment whose blocks live in another database
        is a row this store cannot see.  It does **not** mean the read failed: an
        unreachable database raises, so a caller can never mistake a broken store
        for an unblocked promotion — the distinction feature 284's
        ``read_ledger`` makes at the same seam, and the reason ``None`` is not
        spelled as an empty record carrying a zero.  A node that *was* blocked
        always answers a record, because the row is the record.

        A blank or non-text id is refused rather than answered ``None``: a name
        that states nothing is a malformed ask, not an unblocked promotion, and
        the two must not collapse into one answer.
        """
        node = _block_node_id(node_id)
        with closing(self._connect()) as connection:
            row = _read_row(connection, node)
        return None if row is None else self._record_from_row(row)

    def is_blocked(self, node_id: Any) -> bool:
        """Whether this store holds a blocking reason for the node.

        The feature's own question as a boolean, and exactly the question *was
        this promotion blocked on regime coverage?* as far as this member can
        answer it.  Deliberately a wrapper over :meth:`blocked` rather than a
        second ``SELECT``: one question has one read, and a caller that needs
        the reason asks :meth:`blocked` rather than calling this twice.

        Inherits :meth:`blocked`'s refusal of a malformed id, for the same
        reason: a name that states nothing is not an unblocked promotion, and
        answering ``False`` about it would be inventing a finding about a
        hypothesis nobody named — the mirror of the *named-empty* trap, at the
        other end.
        """
        return self.blocked(node_id) is not None

    def blocks(self) -> tuple[PromotionBlock, ...]:
        """Every block this deployment has recorded, ordered by node.

        The listing a report reads — *which promotions are blocked, and on what*
        — and the shape a later feature enumerating §C7's refusals wants.  A
        tuple rather than a live cursor, because the answer is a value the caller
        keeps rather than a view that changes under it, and ordered by the
        table's key so two reads of one store are comparable.
        """
        with closing(self._connect()) as connection:
            cursor = connection.execute(_LIST_ROWS_SQL)
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return tuple(self._record_from_row(row) for row in rows)

    # -- The words ----------------------------------------------------------

    def _require_decision(
        self, connection: sqlite3.Connection, node: str
    ) -> None:
        """Refuse a block for a node that holds no pre-registration.

        The precondition that makes a blocking reason *a reason for a
        promotion*: §13 item 7 fixes a node's criteria before the evaluation
        that decides them (feature 291), and §C7's block stops that evaluation
        from publishing.  A node nobody pre-registered has no decision for this
        reason to be the blocking reason *of*, so the row would be a block
        hanging off a hypothesis rather than off a promotion — a distinction a
        reader months later could not recover.

        Refused by probe rather than left to the foreign key for the reason
        feature 291's two parent probes exist: SQLite's ``IntegrityError`` names
        no node and no table, and the repair here is specific enough to state —
        pre-register the promotion first.  Note the probe is *stronger* than the
        primary key's own ``REFERENCES node(id)``, which only asks that the
        hypothesis exist; this asks that it was entered for promotion, and the
        key is the structural backstop beneath it.
        """
        cursor = connection.execute(_DECISION_EXISTS_SQL, (node,))
        try:
            present = cursor.fetchone() is not None
        finally:
            cursor.close()
        if not present:
            raise PromotionBlockError(
                f"{PROMOTION_BLOCK_ERROR_CODE}: {PROMOTION_REGISTRY_TABLE} holds "
                f"no row for {NODE_ID_COLUMN} {node}, so this node was never "
                "pre-registered and there is no promotion for this reason to be "
                "the blocking reason of. §13 item 7 fixes a promotion's criteria "
                "before the evaluation that decides them, and §C7's block stops "
                "that evaluation from publishing — so a block recorded first "
                "would be a reason for a decision nobody opened. Pre-register the "
                "promotion (feature 291) and record its blocking reason after the "
                "gate refuses it (feature 299)"
            )

    def _record_from_row(self, row: tuple[Any, ...]) -> PromotionBlock:
        """Build a :class:`PromotionBlock` from a row, with the node named.

        The read path's one constructor, so every read-back in the store builds
        the value the same way.  A refusal raised from the row names the node it
        came off — the difference between an operator learning *this block is
        corrupt* and learning only that some row somewhere is not a block — and
        the class is already this feature's, so the node is added to the message
        rather than the vocabulary being translated.
        """
        node = row[0]
        try:
            return PromotionBlock(
                node_id=node,
                regime=row[1],
                world_count=row[2],
                coverage_threshold=row[3],
                blocked_at=row[4],
            )
        except PromotionBlockError as exc:
            # The inner message is already prefixed with the code (every refusal
            # this module raises is), so it is stripped before re-framing: one
            # refusal carries one ``coverage_below_threshold``, not two.  The
            # code is a greppable marker for the *finding*, and a doubled one
            # would read as two blocked promotions where an operator has one row
            # to go and look at — the same treatment feature 288's read gives its
            # own code word.
            detail = str(exc).removeprefix(f"{PROMOTION_BLOCK_ERROR_CODE}: ")
            raise PromotionBlockError(
                f"{PROMOTION_BLOCK_ERROR_CODE}: the {PROMOTION_BLOCK_TABLE} row "
                f"for node {node} could not be read as a blocking reason: "
                f"{detail}"
            ) from exc

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def _read_row(
    connection: sqlite3.Connection, node: str
) -> tuple[Any, ...] | None:
    """One node's row, or ``None`` when the table holds none — the one read.

    Spelled once so :meth:`PromotionBlocks.record_block`'s read-back and
    :meth:`PromotionBlocks.blocked` cannot diverge on which columns are asked
    for or in what order.
    """
    cursor = connection.execute(_READ_ROW_SQL, (node,))
    try:
        return cursor.fetchone()
    finally:
        cursor.close()


# -- The module-level spelling -----------------------------------------------------


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The URL the module-level spellings act on, or a refusal naming the gap.

    The same seam :func:`regime.ledger.read_ledger` and
    :func:`regime.origins.record_backfilled_world` resolve, restated in this
    feature's vocabulary: an explicit URL wins, else ``DATABASE_URL``, and a
    deployment that names neither is refused *by name* rather than silently
    doing nothing.  The silence is the dangerous failure here and not the
    refusal: a block whose reason was quietly not recorded leaves a promotion
    stopped with no auditable explanation, which is the state §C7's ledger
    exists to make impossible.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise PromotionBlockError(
            f"{PROMOTION_BLOCK_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was supplied), so "
            "there is nowhere to record why a promotion was blocked. §C7's "
            "block has to be auditable from what was written, so a store "
            "resolved from nothing is a refusal rather than a silent no-op "
            "(feature 299)"
        )
    return url


def record_block(
    node_id: Any,
    *,
    regime: Any,
    world_count: Any,
    threshold: Any,
    blocked_at: dt.datetime | None = None,
    clock: Callable[[], dt.datetime] | None = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[PromotionBlock, bool]:
    """Persist one blocking reason — the module-level spelling of 299's act.

    The feature's sentence as one call, for the caller that wants the act
    without holding a store — a gate's final line after feature 285 has refused
    the promotion.  The store is resolved from ``database_url``, else from
    ``DATABASE_URL``, exactly as :func:`promotion.pre_register.PreRegistrations.
    resolve` and feature 284's ``read_ledger`` resolve theirs.

    A :class:`~promotion.errors.PromotionBlockError` from the store or the
    resolution propagates unwrapped: the refusal already names the node and the
    fact, and re-wrapping it here would put a second message in front of the one
    an operator needs.
    """
    url = _resolved_url(database_url, env)
    return PromotionBlocks(url).record_block(
        node_id,
        regime=regime,
        world_count=world_count,
        threshold=threshold,
        blocked_at=blocked_at,
        clock=clock,
    )


def blocked_promotion(
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> PromotionBlock | None:
    """Read one node's block back — the module-level spelling of the read.

    For the caller that holds a URL rather than a store: an operator checking
    why a promotion is stopped, a report enumerating §C7's refusals, a later
    feature asking after a node it did not block itself.  Resolved the same way
    :func:`record_block` resolves its store, so the caller that records through
    one spelling and reads through the other is reading the row it wrote.

    ``None`` means *this promotion was not blocked through this store*, with the
    scope :meth:`PromotionBlocks.blocked` states; an unreachable database raises
    instead, so a broken store can never be mistaken for an unblocked promotion.
    """
    url = _resolved_url(database_url, env)
    return PromotionBlocks(url).blocked(node_id)
