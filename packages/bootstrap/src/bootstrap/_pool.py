"""The bootstrap replay pool — feature 188's authoring, feature 191's ported seating.

app_spec.xml, "Bootstrap Worlds", feature 188: *System persists 40 to 50
generated bootstrap worlds into the replay pool on demand*; feature 191:
*System persists source commit and dataset manifest hash for every ported
world, which rejects a world whose recorded values no longer match its
upstream.*  §10.6 states what the first of those converts the pool-size
precondition into:

    This converts the §10.3.1 pool-size precondition from a calendar
    problem into a compute problem.  Target 40–50 bootstrap worlds before
    the first financial dreaming cycle, then fine-tune on financial
    worlds.

Feature 181 built the world this pool is made of; this module builds the
*pool* — the thing that turns one world into the forty-something the
first dreaming cycle needs before it may run (§12.1's ladder blocks
dreaming below 20 worlds and caps it at 8-10 revisions between 20 and 50,
so the band this feature persists is the band that unlocks the target).
Feature 190 built the adapter a ported world is; this module gives it the
other half of its seat — the row its provenance is recorded in and the
check that row is checked by — so *"every world carries its source commit
and dataset manifest hash"* (§10.6's phase brief, §10.6.1's requirement)
is a fact about the pool rather than a promise in the adapter.

**A pool entry is an identity, not a dataset.**  §10.6.1's provenance rule
— *"An upstream that changes is a different world, not an updated one"* —
has nothing to check for an authored world, because the world has no
upstream: :func:`~bootstrap.generate_dataset` is a pure function of the
seed, so a world *is* its seed and a row that records ``(world_id, seed,
domain)`` records the whole world.  Persisting the observations themselves
would be persisting a cache of a pure function — 40-50 copies of 96 rows
that any process can regenerate to the last bit — and would create
exactly the drift the rule forbids: a stored dataset that disagreed with
its seed would be a different world wearing an old world's name.  The
committed world's laziness carries over to every world in the pool: a row
is one allocation until the first label is asked of it, which is why
holding 40-50 of them costs nothing (the property
:meth:`~bootstrap.HyperparameterWorld.dataset` states for one world,
restated for the pool that holds many).

**The ported half of the row (feature 191).**  A ported world is the one
kind of pool entry that *does* have an upstream, so its identity is not a
seed but the pair of digests that pinned its labels — the
``source_commit`` of the upstream code and the ``dataset_manifest`` of
the label-bearing data, the two fields §10.6.1's provenance block names
and :class:`~bootstrap.Provenance` holds.  :meth:`BootstrapPool.\
persist_ported_world` seats that pair beside the authored rows, under the
``ported`` domain §10.6's tree names fourth, with no seed and no draw —
the row is either the authored half or the ported half, a shape the
table's own CHECK states so a row that was neither could not be written
even by hand.  And :meth:`BootstrapPool.verify_ported_world` is the check
the feature's sentence turns on: the digests the row *recorded*, against
the digests the upstream *now shows*, presented by the one caller who can
see the upstream.  They match and it is the same world — admitted, its
record answered.  They differ and the world is *refused*, not re-hashed
under the name it no longer describes: §10.6.1's rule and the failure
table's own instruction (*"Refuse the world.  A changed upstream is a
different world, not an updated one"*), which is why the refusal raises
:class:`~bootstrap.BootstrapWorldError` — the world's recorded identity
no longer describes it — rather than the pool's own vocabulary, which is
for asks that were never about a world at all.  The re-port that *is* a
new upstream belongs under a new world id, and seating it there is the
caller's one legal move.

**The draw is a stream, and the worlds are its states.**  Every number a
*world* contains is a content-addressed hash draw — indexed, not
sequenced, because a label must not depend on the order cells were
revealed in (:mod:`bootstrap._stream`'s whole argument).  The *pool* is
the opposite shape: it is authored once, as a batch, and what it needs is
exactly a sequence of independent seeds — so the draw is the SplitMix64
stream construction, ``mix64(pool_seed + (index + 1)·γ)``, which is the
one place a *generator-shaped* use of the hash is idiomatic.  Two
properties follow from the construction rather than from luck: the draw
is a pure function of ``(pool_seed, index)``, so re-running the authoring
reproduces the identical pool (a re-run is a refresh, not a re-draw), and
:func:`~bootstrap._stream.mix64` is a bijection over the 64-bit words, so
two indices of one pool can never draw one seed — the pool cannot
accidentally seat one world under two names.

**The band is a refusal, not a clamp.**  ``count`` outside 40-50 is
refused, in both directions, and both are §10.6's own reasoning.  Below
40 the pool undercuts the target the first dreaming cycle is gated on —
a short draw would let the cycle run on a pool §12.1 explicitly rates as
weaker — and a store that silently rounded a short ask up would be
reporting a coverage the operator never asked for.  Above 50 the pool
would let bootstrap worlds dominate the replay pool's composition, which
is the failure feature 187 exists to reject on the reporting side (*"a
headline dreaming claim resting on bootstrap worlds alone"*): §10.6's
instruction is 40-50 *before the first financial dreaming cycle, then
fine-tune on financial worlds*, and a pool builder that accepted any size
would let the "then" be skipped.  The default is 45, the band's midpoint:
an operator who names nothing gets a pool squarely inside the target
rather than at either edge of it.

**Persistence is the database the replay already reads.**  The pool
persists into ``bootstrap_world``, a table this member owns and creates
lazily (``CREATE TABLE IF NOT EXISTS`` — the contract every store in this
workspace states), resolved from ``DATABASE_URL`` exactly as the poison
store and the nulloracle's stores resolve theirs.  The worlds of the
replay pool and the scores of ``replay_score`` (migration ``0109``'s
table, whose ``world_id`` column is the whole join) live in one database,
which is what makes *"persists into the replay pool"* a statement about
the same pool the dreaming loop reads rather than about a side file.  A
deployment that names no database composes no pool component — the
degrade-don't-break stance every store here takes — while the operator
who means to author worlds is the caller that must not find itself in
that state.  Feature 191 widened the table — ``seed`` and ``pool_seed``
lost the ``NOT NULL`` they carried as the authored half's whole identity,
because a ported row holds neither, and the two digest columns joined —
and a database feature 188 already prepared is *evolved* to the widened
shape rather than stranded by it: a guarded rebuild the member performs
inside its own lazy schema work (check the columns, copy the rows, swap
the tables), still no edit to the shared migration chain, because the
table's shape remains a fact about this feature and its history, not
about the database's.

**On demand, and only on demand.**  Nothing here runs at composition:
the builder resolves a URL and holds it (no I/O — the path is resolved
on first use), and the worlds are authored when a caller asks for them
with :meth:`~bootstrap.BootstrapPool.persist_worlds`.  That is the "on
demand" of the feature's sentence read as a contract: composing an
application must not write forty-five rows into a database an operator
pointed the process at for an unrelated reason, exactly as composing one
must not open the database at all.  The re-run story is a refresh — the
same ``pool_seed`` re-draws the same worlds, the upsert rewrites the same
rows, ``created_at`` keeps the world's first authoring instant — because
an authoring operation that appended on re-run would double the pool it
was re-asserting.

**What this module deliberately does not ship.**  The pool reports what
it holds (:meth:`~bootstrap.BootstrapPool.worlds`,
:meth:`~bootstrap.BootstrapPool.ported_worlds`,
:meth:`~bootstrap.BootstrapPool.world_count`) but does not tally it
*against* the financial pool — feature 186's independent count and
feature 187's headline refusal are statements about both pools, made
where both are visible.  It draws only hyperparameter worlds (the
``hpo`` domain §10.6's tree names first) and seats only their ported
counterparts; the feature-selection and symbolic-regression domains
(features 182-183) join the same table through the same ``domain``
column when they exist, which is why the column is part of the row
rather than a fact about the table.  And it charges no budget,
decrements nothing and consults no clock beyond the authoring stamp —
feature 185's ``charges_budget`` is a fact about the *trial*, and
§10.6's *"no dependence on market time"* is a fact about the worlds.

Stdlib only, and import-cheap: ``sqlite3``, ``datetime``, ``os`` and
``urllib.parse``; no third-party import at module scope, so the factory's
scan — which imports this package to fire its ``@register`` — pays
nothing for the pool (the discipline :mod:`tripwires.poison` states for
its own import).
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ._ported import Provenance
from ._stream import GOLDEN_GAMMA, MASK64, mix64
from ._world import HyperparameterWorld
from .errors import BootstrapPoolError, BootstrapWorldError

__all__ = [
    "DATABASE_URL_ENV",
    "DEFAULT_POOL_SIZE",
    "MAX_POOL_SIZE",
    "MIN_POOL_SIZE",
    "POOL_COMPONENT_NAME",
    "POOL_DOMAIN",
    "POOL_SEED",
    "POOL_TABLE",
    "PORTED_DOMAIN",
    "BootstrapPool",
    "PersistedPool",
    "PortedWorldRecord",
    "WorldRecord",
    "draw_world_seed",
    "parsed_instant",
    "validated_instant",
    "world_id_for",
]

#: The environment variable that names the database the pool persists into.
#: The one spelling every relational store in this workspace reads — the
#: poison store, the nulloracle's stores and the replay pool's own seat
#: all resolve it — so the bootstrap pool reads the same variable rather
#: than growing a second one a deployment could set to a different
#: database than the one ``replay_score`` lives in.
DATABASE_URL_ENV = "DATABASE_URL"

#: The component name the pool registers under — a second name rather
#: than a second component under ``"bootstrap"``, the convention
#: :mod:`tripwires` states for its own seats: the world component answers
#: *what is the composed bootstrap world?* while this one answers *what
#: is the composed bootstrap pool?*, and a caller asking for one must not
#: be handed the other.  The names are not interchangeable and the
#: registry must not pretend they are.
POOL_COMPONENT_NAME = "bootstrap-pool"

#: The table the pool persists into — this member's own, created lazily
#: and never migrated here (a migration would be an edit to the shared
#: chain this member does not need: the table has one writer, this pool,
#: and the shape is a fact about the feature rather than about the
#: database's history).
POOL_TABLE = "bootstrap_world"

#: The smallest pool this feature persists — the low edge of §10.6's
#: *"Target 40–50 bootstrap worlds before the first financial dreaming
#: cycle"*, and the floor of the band the authoring refuses below.
MIN_POOL_SIZE = 40

#: The largest pool this feature persists — the high edge of the same
#: sentence, and the ceiling of the band: beyond it the bootstrap worlds
#: would dominate the replay pool's composition, the imbalance feature
#: 187's headline refusal exists to reject on the reporting side.
MAX_POOL_SIZE = 50

#: The size an authoring call that names none gets: the band's midpoint,
#: squarely inside the target rather than at either edge of it.  An
#: operator who wants an edge asks for it by name.
DEFAULT_POOL_SIZE = 45

#: The seed of the committed draw — the pool a bare
#: ``persist_worlds()`` authors.  A stable integer in the committed
#: world's own convention (:data:`~bootstrap.PRICED_SEED` is the date the
#: world was authored, and this is the date the pool was), because the
#: pool is *reported* per §10.6 and a re-run of the committed draw must
#: re-draw the committed worlds — which a fixed seed guarantees and a
#: wall-clock seed would silently break.
POOL_SEED = 20260922

#: The domain every world of this pool belongs to, in §10.6's own tree
#: vocabulary (``hpo/  # hyperparameter search over a fixed model+dataset``).
#: A column on the row rather than a fact about the table because the
#: tree has four branches and no one row holds them all: ``featsel`` and
#: ``symreg`` are later features of this category that will join this
#: pool through this column, and ``ported`` (:data:`PORTED_DOMAIN`,
#: feature 191) already has.
POOL_DOMAIN = "hpo"

#: The domain a *ported* world belongs to — §10.6's fourth branch
#: (``ported/  # external ground-truth environments, manifest-hashed —
#: §10.6.1``), the half of the pool feature 191 seats.  Spelled by the
#: tree rather than invented here for the same reason ``POOL_DOMAIN`` is:
#: the pool is reported per §10.6 and the domain is how a report tells
#: the authored half from the ported one.
PORTED_DOMAIN = "ported"

#: The row's column names, in declaration order — the one spelling of
#: what a pool row is made of, shared by the DDL, the insert and the
#: read-back so the three cannot disagree on a column order, the failure
#: a positional ``SELECT *`` invites and the one the poison store's own
#: ``_COLUMNS`` constant exists to prevent.
_ROW_COLUMNS = ("world_id", "seed", "domain", "pool_seed", "created_at")

#: The two columns feature 191 added — the digests a ported world's
#: provenance is recorded under, keyed exactly the way
#: :meth:`Provenance.row` keys them so the value and the row cannot
#: drift apart (a test pins that equality; the insert spreads the row).
_PROVENANCE_COLUMNS = ("source_commit", "dataset_manifest")

#: Every column of the widened row — the authored half's identity five,
#: then the ported half's digest two.  One row carries one half or the
#: other, never both, which is the table's own CHECK to state.
_ALL_COLUMNS = _ROW_COLUMNS + _PROVENANCE_COLUMNS

#: The table the guarded rebuild stages the widened shape in, while the
#: 188-shaped table it replaces is still the one the copy reads.
_STAGING_TABLE = f"{POOL_TABLE}_191_seating"

#: The shape of one row, both halves of it.  Authored (feature 188's
#: rows, and 182-183's when they exist): a seed, the draw that drew it,
#: and no digests — the world has no upstream to name.  Ported (feature
#: 191's): both digests, the ``ported`` domain, and neither a seed nor a
#: draw — the world's identity is its upstream, not a draw this member
#: made.  The CHECK is the shape's own voice: a row that was neither
#: half (a seed *and* a provenance, or neither) is refused by the table
#: itself, which is what makes the either-or a fact about the store
#: rather than a convention of this module's writers — and what makes a
#: hand-edited row that would corrupt the pool refuse itself on insert.
_TABLE_BODY = f"""
(
    world_id         TEXT    NOT NULL PRIMARY KEY,
    seed             INTEGER UNIQUE,
    domain           TEXT    NOT NULL,
    pool_seed        INTEGER,
    created_at       TEXT    NOT NULL,
    source_commit    TEXT,
    dataset_manifest TEXT,
    CHECK (
        (
            seed IS NOT NULL
            AND pool_seed IS NOT NULL
            AND source_commit IS NULL
            AND dataset_manifest IS NULL
            AND domain <> {PORTED_DOMAIN!r}
        )
        OR (
            seed IS NULL
            AND pool_seed IS NULL
            AND source_commit IS NOT NULL
            AND source_commit <> ''
            AND dataset_manifest IS NOT NULL
            AND dataset_manifest <> ''
            AND domain = {PORTED_DOMAIN!r}
        )
    )
)
"""

_SCHEMA = f"""
-- Feature 188: the bootstrap half of the replay pool.  One row per
-- persisted world, and the row is the world's *identity* rather than its
-- dataset -- (world_id, seed, domain) records a pure function of the seed
-- completely, so the observations are never stored beside the world they
-- would only cache (a cached dataset that disagreed with its seed would
-- be a different world wearing an old world's name, the exact drift
-- §10.6.1's provenance rule refuses).
--
-- `world_id` is the row's key: the name a replay score attributes a
-- world by, and the upsert target that makes re-authoring a refresh
-- rather than an append.  `seed` is UNIQUE because two rows sharing a
-- seed would be one world under two names -- a pool that over-reported
-- its own size, which is the one number §10.3.1's precondition turns
-- on.  `pool_seed` records which draw authored the world, so a pool
-- re-drawn from a different seed adds worlds it can name rather than
-- silently mutating rows it cannot.  `created_at` carries no engine
-- DEFAULT -- the writer stamps it, which is why there is no 0109-style
-- dialect split here (SQLite's DEFAULT grammar accepts a function call
-- only parenthesised, and a caller-stamped column never meets it).
--
-- Feature 191: the ported half joins the same table, and `seed` and
-- `pool_seed` lose the NOT NULL they wore as the authored half's whole
-- identity, because a ported world's identity is the pair of digests its
-- upstream pinned -- `source_commit` (§10.6.1: "not a tag, not a
-- branch") and `dataset_manifest` -- and neither a draw nor a seed
-- names it.  The CHECK keeps the halves exclusive: one row is one half
-- or the other, and `ported` on the domain means the digest half (so an
-- authored row cannot wear the ported domain, and a ported row cannot
-- shed it).  UNIQUE on a nullable seed holds in SQLite (NULLs are
-- distinct), so the ported rows cannot trip the one-seed-one-world
-- constraint they have no seed to answer.
CREATE TABLE IF NOT EXISTS {POOL_TABLE} {_TABLE_BODY}
"""

#: The authoring write: an upsert on the world's own key.  The ``DO
#: UPDATE`` arm deliberately does **not** touch ``created_at`` — a
#: re-authoring of the same world is the same world (§10.6.1: an upstream
#: that changes is a *different* world, so one that did not change is not
#: an updated one either), and the first instant it was authored is a
#: fact about the pool's history that a refresh must keep.
_UPSERT = f"""
INSERT INTO {POOL_TABLE} ({", ".join(_ROW_COLUMNS)})
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(world_id) DO UPDATE SET
    seed      = excluded.seed,
    domain    = excluded.domain,
    pool_seed = excluded.pool_seed
"""

#: The ported seating (feature 191): a plain INSERT, deliberately with no
#: ``ON CONFLICT`` arm.  The authored upsert may refresh because a re-draw
#: of the same draw is the same world; a re-port of the same *name* is
#: not the same world until the digests say so, and a conflict arm that
#: rewrote the digests would be the exact "re-hash it into the existing
#: pool" §10.6.1 forbids.  The collision is reconciled in Python instead:
#: the seated row is read and compared (:func:`_reconcile_ported_row`),
#: so the only write this statement ever performs is a world's *first*
#: seating.
_PORTED_INSERT = f"""
INSERT INTO {POOL_TABLE} ({", ".join(_ALL_COLUMNS)})
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

#: One row by name, every column of it — the read both the seating and
#: the upstream check reconcile against, and the read the ported half of
#: the pool is enumerated by.
_SELECT_ROW = f"SELECT {', '.join(_ALL_COLUMNS)} FROM {POOL_TABLE} WHERE world_id = ?"


def _pool_columns(connection: sqlite3.Connection) -> tuple[str, ...]:
    """The table's column names, in declaration order.

    ``PRAGMA table_info`` rather than a guess, because the whole point of
    the read is to learn which *shape* of this member's own table the
    database holds — the fresh seven-column shape feature 191 creates, or
    the five-column one feature 188 did.
    """
    return tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({POOL_TABLE})"))


def _evolve_pool_schema(connection: sqlite3.Connection) -> None:
    """Bring a feature-188-shaped table to the shape feature 191 reads and writes.

    A no-op against every database this member prepared after the
    widening (the provenance columns are already there) and a one-time,
    all-rows-kept rebuild against one it prepared before: stage the
    widened shape beside the old table, copy the authored rows across
    (their five columns unchanged, their digests honestly ``NULL`` — an
    authored world has no upstream to name), then swap the tables.  The
    statements run inside the caller's transaction, so a failure leaves
    the 188 shape exactly as it was — SQLite rolls uncommitted DDL back
    with everything else.

    Spelled here rather than as a migration in the shared chain for the
    reason :data:`POOL_TABLE`'s own comment states: the table has one
    writer, this pool, so its shape is this member's to evolve — and a
    chain edit would be an order-sensitive change to files this member
    does not own.  A ``CHECK``-guarded evolution could not invent rows
    the old table never held: the copy seats authored rows only, and the
    widened shape's CHECK admits them unchanged.
    """
    if set(_PROVENANCE_COLUMNS) <= set(_pool_columns(connection)):
        return
    connection.execute(f"DROP TABLE IF EXISTS {_STAGING_TABLE}")
    connection.execute(f"CREATE TABLE {_STAGING_TABLE} {_TABLE_BODY}")
    connection.execute(
        f"INSERT INTO {_STAGING_TABLE} ({', '.join(_ROW_COLUMNS)}) "
        f"SELECT {', '.join(_ROW_COLUMNS)} FROM {POOL_TABLE}"
    )
    connection.execute(f"DROP TABLE {POOL_TABLE}")
    connection.execute(f"ALTER TABLE {_STAGING_TABLE} RENAME TO {POOL_TABLE}")


def draw_world_seed(pool_seed: int, index: int) -> int:
    """The seed of the ``index``-th world of the draw ``pool_seed`` names.

    The SplitMix64 stream construction — the golden-ratio increment added
    once per step, then the finalizer — which is the hash's one
    *generator-shaped* use and is idiomatic exactly here: a pool is
    authored once as a batch, so what it needs from randomness is a
    sequence of independent seeds rather than the content-addressed draws
    a world's cells need (:mod:`bootstrap._stream`'s split).  Pure
    function of ``(pool_seed, index)``: re-authoring re-draws the same
    worlds, and :func:`~bootstrap._stream.mix64` is a bijection over the
    64-bit words while ``γ`` is odd, so two indices of one draw can never
    collide onto one seed.

    The drawn word is returned in its **signed** spelling — ``w - 2⁶⁴``
    when the unsigned word's top bit is set — because SQLite's ``INTEGER``
    is a signed 64-bit and a Python int above ``2⁶³ - 1`` cannot cross it.
    The spelling changes nothing about the world it names:
    :func:`~bootstrap._stream.mix64` folds any integer into the ring by
    its mask, so the signed seed and the unsigned word address the same
    dataset, to the last bit, in any process.
    """
    word = mix64((pool_seed + (index + 1) * GOLDEN_GAMMA) & MASK64)
    return word - (1 << 64) if word >= (1 << 63) else word


def world_id_for(pool_seed: int, index: int) -> str:
    """The world id the ``index``-th world of a draw is named by.

    ``bootstrap-hpo-20260922-07`` — the domain, the pool seed and the
    index, joined the way the committed world's own id
    (:data:`~bootstrap.HYPERPARAMETER_WORLD_ID`) joins its domain and its
    authoring date.  Text and readable for the reason the committed id is
    (§10.6's pool is reported, and an operator reading a replay score
    wants to see which world it came from), and deterministic for the
    reason the seed is: the id is a function of the draw, so a re-run
    upserts the same rows rather than appending a second generation under
    new names.  Two digits of index carry the whole band — 50 worlds,
    indices 0-49 — so the ids sort lexicographically in draw order and
    ``ORDER BY world_id`` is the pool's own order.
    """
    return f"bootstrap-{POOL_DOMAIN}-{pool_seed}-{index:02d}"


def validated_instant(value: dt.datetime) -> dt.datetime:
    """Check that ``value`` is a timezone-aware instant, or refuse it.

    The stamp a row carries must be an aware datetime: a naive one would
    place a world's authoring hours away from the process that authored
    it (in whatever zone the host happens to keep) and nothing would look
    wrong — the same reason the poison store validates the instant it is
    handed rather than trusting the caller's clock discipline.
    """
    if not isinstance(value, dt.datetime):
        raise BootstrapPoolError(
            f"an authoring instant is a datetime — got {value!r} "
            f"({type(value).__name__}); the stamp records when a world "
            "entered the pool, and a value that cannot name an instant "
            "records nothing"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise BootstrapPoolError(
            f"an authoring instant must carry its timezone — got {value!r}; "
            "a naive datetime would place a world's authoring hours away "
            "from the process that authored it, in whatever zone the host "
            "happens to keep, and nothing in the row would look wrong"
        )
    return value


def _stamp(instant: dt.datetime) -> str:
    """Render an aware instant as the row's ISO-8601 UTC, to the second.

    The textual twin of Postgres's ``timestamptz`` and the spelling the
    poison store's own stamps take: UTC, second-truncated, ``Z``-suffixed,
    so two rows written in the same second of the same run carry the same
    text and a report ordering by ``created_at`` orders by time rather
    than by string accident.
    """
    return validated_instant(instant).astimezone(dt.UTC).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def parsed_instant(value: str) -> dt.datetime:
    """Read a row's stamp back into the aware instant it encodes.

    The inverse of :func:`_stamp`, and as strict: 3.12's ``fromisoformat``
    reads the ``Z`` suffix this member's stamps carry natively, and a
    value that does not parse at all is refused by name — a stamp the
    reader cannot reconstruct is a stamp the row should never have
    carried.
    """
    try:
        return dt.datetime.fromisoformat(value)
    except (AttributeError, ValueError) as refusal:
        raise BootstrapPoolError(
            f"a created_at stamp must be ISO-8601 with a timezone — got "
            f"{value!r}; the stamp is part of the pool's history and a "
            "value that cannot be read back is one that was never written"
        ) from refusal


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    Spelled here rather than imported from the member that also spells
    one, for the reason every store in this workspace spells its own: the
    refusal vocabulary is this member's (:class:`BootstrapPoolError`, not
    another feature's), and a URL this pool cannot speak must be refused
    *by name* here rather than translated through a helper that raises
    someone else's error — the seam discipline the whole workspace states
    for error vocabularies.

    Non-``sqlite`` schemes are refused (the spec's single-machine
    allowance is what a stdlib store can speak), as is a URL carrying a
    host, and — load-bearing for this feature specifically — an in-memory
    database: a pool authored into memory dies with the connection that
    opened it, so forty-five worlds would be *persisted* and none of them
    readable by the replay that needs them, which is the failure this
    feature exists to make impossible.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise BootstrapPoolError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "bootstrap pool speaks sqlite:/// (the spec's single-machine "
            f"allowance); point {DATABASE_URL_ENV} at the sqlite database "
            "the replay pool already lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise BootstrapPoolError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise BootstrapPoolError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a pool of worlds authored there is unheld the moment "
            "the caller looks — persistence that does not survive its own "
            "process is the one state this feature refuses outright"
        )
    return Path(path)


class WorldRecord:
    """One persisted world, as the pool reads it back.

    The identity half of a world — its id, its seed, its domain, the draw
    that authored it and the instant it entered the pool — held as an
    immutable value because it is what every report of the pool is made
    of.  The world itself is built on demand from the record
    (:meth:`BootstrapPool.world`), which is the laziness the committed
    world states for one world, restated for the row that names it: a
    record is one object, and the dataset exists only when someone asks
    the world for a label.
    """

    __slots__ = ("created_at", "domain", "pool_seed", "seed", "world_id")

    def __init__(
        self,
        *,
        world_id: str,
        seed: int,
        domain: str,
        pool_seed: int,
        created_at: dt.datetime,
    ) -> None:
        self.world_id = world_id
        self.seed = seed
        self.domain = domain
        self.pool_seed = pool_seed
        self.created_at = created_at

    def row(self) -> dict[str, object]:
        """The record as a store-shaped mapping — a fresh dict per call."""
        return {
            "world_id": self.world_id,
            "seed": self.seed,
            "domain": self.domain,
            "pool_seed": self.pool_seed,
            "created_at": _stamp(self.created_at),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WorldRecord):
            return NotImplemented
        return (self.world_id, self.seed, self.domain, self.pool_seed) == (
            other.world_id,
            other.seed,
            other.domain,
            other.pool_seed,
        )

    def __hash__(self) -> int:
        return hash((self.world_id, self.seed, self.domain, self.pool_seed))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"WorldRecord(world_id={self.world_id!r}, seed={self.seed!r}, "
            f"domain={self.domain!r}, pool_seed={self.pool_seed!r})"
        )


class PortedWorldRecord:
    """One persisted ported world, as the pool reads it back — feature 191's row.

    The identity half of a ported world: its id, its domain (``ported``,
    §10.6's fourth branch) and the pair of digests that pinned its labels
    — the source commit of the upstream code and the dataset manifest of
    the label-bearing data — held as an immutable value for the same
    reason :class:`WorldRecord` holds a seed: it is what every report of
    the pool is made of, and the two digests are the whole of what
    §10.6.1 asks a ported world to carry.

    The world itself cannot be rebuilt from the record the way an
    authored one can, and that is a fact about the ported half rather
    than an omission: an authored row *is* its world (the dataset is a
    pure function of the seed the row holds), while the labels a ported
    row names live in an environment this member cannot call — the label
    function is the caller's to bring, the way the digests are the
    pool's to hold.  So the replay engine's read is the record, and the
    caller that re-ports supplies the labels through
    :func:`~bootstrap.ported_world` and asks
    :meth:`~bootstrap.BootstrapPool.verify_ported_world` whether the
    upstream it can see is still the one the row recorded.

    The digests are validated at construction the way
    :class:`~bootstrap.Provenance` validates its own — a record a caller
    built by hand, or read back from a row a hand had been to, is refused
    if either digest is blank, because a blank digest names no upstream
    a check could be checked against.
    """

    __slots__ = (
        "created_at",
        "dataset_manifest",
        "domain",
        "source_commit",
        "world_id",
    )

    def __init__(
        self,
        *,
        world_id: str,
        source_commit: str,
        dataset_manifest: str,
        domain: str = PORTED_DOMAIN,
        created_at: dt.datetime,
    ) -> None:
        if not isinstance(world_id, str) or not world_id.strip():
            raise BootstrapPoolError(
                f"a ported world id is a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the id is how the row is "
                "named and a re-port checked, and a record that cannot "
                "name its world records nothing the pool could verify"
            )
        for field, value in (
            ("source_commit", source_commit),
            ("dataset_manifest", dataset_manifest),
        ):
            if not isinstance(value, str) or not value.strip():
                raise BootstrapWorldError(
                    f"a ported world's {field} is a non-empty digest — got "
                    f"{value!r} ({type(value).__name__}); the digest pins "
                    "the labels to an upstream this member does not "
                    "generate, and a record holding a blank one could not "
                    "be checked against the upstream it claims (§10.6.1: "
                    "an upstream that changes is a different world)"
                )
        self.world_id = world_id
        self.source_commit = source_commit
        self.dataset_manifest = dataset_manifest
        self.domain = domain
        self.created_at = created_at

    @property
    def provenance(self) -> Provenance:
        """The digests as the value feature 190 made of them.

        The record's two text columns, back as the frozen
        :class:`~bootstrap.Provenance` a ported world is identified by —
        so a caller that holds a record and a caller that holds a world
        compare the same value, and the row and the adapter cannot drift
        apart in what they mean by "the upstream".
        """
        return Provenance(
            source_commit=self.source_commit,
            dataset_manifest=self.dataset_manifest,
        )

    def row(self) -> dict[str, object]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The full widened row, both halves' spelling: the ported half's
        digests (spread from :meth:`provenance`'s own row, so the column
        names cannot drift from the ones the value keys) and the authored
        half's seed and draw as ``None`` — not omitted, but honestly
        empty, the way the table's CHECK reads them.
        """
        return {
            "world_id": self.world_id,
            "seed": None,
            "domain": self.domain,
            "pool_seed": None,
            "created_at": _stamp(self.created_at),
            **self.provenance.row(),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PortedWorldRecord):
            return NotImplemented
        return (self.world_id, self.source_commit, self.dataset_manifest) == (
            other.world_id,
            other.source_commit,
            other.dataset_manifest,
        )

    def __hash__(self) -> int:
        return hash((self.world_id, self.source_commit, self.dataset_manifest))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PortedWorldRecord(world_id={self.world_id!r}, "
            f"source_commit={self.source_commit!r}, "
            f"dataset_manifest={self.dataset_manifest!r})"
        )


class PersistedPool:
    """What an authoring call persisted — the report, not the pool.

    The worlds the call seated (as :class:`WorldRecord` values, in draw
    order), whether the call *refreshed* worlds the pool already held
    (``replayed`` — a re-run of the same draw, which rewrites the same
    rows rather than appending a second generation), and the draw's own
    seed, so a caller logging the report can name the pool it just
    authored or re-asserted.  Carries the worlds rather than only their
    count because the interesting audit of an authoring is *which* worlds
    entered the pool — the ids a replay score will be attributed by — and
    a report that could not say would be a count with none of the
    provenance.
    """

    __slots__ = ("_worlds", "pool_seed", "replayed")

    def __init__(
        self, *, worlds: tuple[WorldRecord, ...], pool_seed: int, replayed: bool
    ) -> None:
        self._worlds = worlds
        self.pool_seed = pool_seed
        self.replayed = replayed

    @property
    def worlds(self) -> tuple[WorldRecord, ...]:
        """The records this call seated, in draw order — read-only."""
        return self._worlds

    @property
    def count(self) -> int:
        """How many worlds this call seated."""
        return len(self._worlds)

    def __len__(self) -> int:
        return len(self._worlds)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PersistedPool(count={len(self._worlds)}, "
            f"pool_seed={self.pool_seed!r}, replayed={self.replayed!r})"
        )


def _record_from_row(row: tuple) -> WorldRecord:
    """Unpack one pool row into the record it holds, in column order."""
    world_id, seed, domain, pool_seed, created_at = row
    return WorldRecord(
        world_id=world_id,
        seed=seed,
        domain=domain,
        pool_seed=pool_seed,
        created_at=parsed_instant(created_at),
    )


def _ported_record_from_row(row: tuple) -> PortedWorldRecord:
    """Unpack one widened row's ported half into the record it holds.

    The inverse of :meth:`PortedWorldRecord.row`, read against a row the
    table's CHECK already kept honest (a ported row's digests are
    non-blank and its seed is ``NULL``, or the table refused to hold it),
    so the unpack validates the digests only for the record's own
    constructor's sake — a hand-corrupted row is refused here by name
    rather than read into a record that could not be checked.
    """
    world_id, _, domain, _, created_at, source_commit, dataset_manifest = row
    return PortedWorldRecord(
        world_id=world_id,
        source_commit=source_commit,
        dataset_manifest=dataset_manifest,
        domain=domain,
        created_at=parsed_instant(created_at),
    )


def _reconcile_ported_row(row: tuple, provenance: Provenance) -> PortedWorldRecord:
    """Compare a seated ported row against the upstream a caller presents.

    The whole of the feature's second clause, applied to one row: the
    digests the row *recorded* are the upstream the labels were pinned
    to, the :class:`~bootstrap.Provenance` is the upstream the caller can
    *see now*, and the two either name the same upstream — the same
    world, whose record this answers, down to the first instant it was
    seated — or they do not, and the world is refused.  Refused, not
    updated: the caller's one legal move is to seat the changed upstream
    under its own world id, which is §10.6.1's *"a different world, not
    an updated one"* and the failure table's own instruction (*"Refuse
    the world"*), and it is a :class:`~bootstrap.BootstrapWorldError`
    because the ask was well-formed — the world's recorded identity is
    simply no longer the world's.

    A row that is not the ported half at all is a pool refusal instead:
    an authored world's row answering a ported ask would be one name
    seating two worlds, the exact confusion the world id exists to
    prevent.
    """
    world_id, seed, _, _, _, source_commit, dataset_manifest = row
    if seed is not None:
        raise BootstrapPoolError(
            f"the world {world_id!r} is an authored world of the pool, "
            "seated by a draw rather than a port — one name is one world "
            "(§10.6.1), and a ported world seated under an authored "
            "world's name would answer labels the row never recorded; "
            "name the ported world by its own id"
        )
    if (source_commit, dataset_manifest) != (
        provenance.source_commit,
        provenance.dataset_manifest,
    ):
        raise BootstrapWorldError(
            f"the ported world {world_id!r} is recorded against a "
            "different upstream — recorded source_commit "
            f"{source_commit!r} and dataset_manifest {dataset_manifest!r}, "
            f"presented source_commit {provenance.source_commit!r} and "
            f"dataset_manifest {provenance.dataset_manifest!r}; an "
            "upstream that changes is a different world, not an updated "
            "one (§10.6.1), so the pool refuses the world rather than "
            "re-hashing it under the name it no longer describes — seat "
            "the re-port under its own world id"
        )
    return _ported_record_from_row(row)


class BootstrapPool:
    """The bootstrap half of the replay pool — features 188 and 191's store.

    Constructed with the database URL it persists into;
    :meth:`persist_worlds` authors 40-50 generated worlds into the table
    on demand; :meth:`persist_ported_world` seats a ported world's
    provenance beside them; :meth:`worlds` and :meth:`ported_worlds` read
    the two halves the pool holds, :meth:`world_count` the count of both;
    :meth:`verify_ported_world` is the upstream check feature 191's
    sentence turns on; :meth:`world` builds the
    :class:`~bootstrap.HyperparameterWorld` a persisted *authored* row
    names, which is the read the replay engine makes — the pool is the
    thing that turns a world id in a ``replay_score`` row back into the
    world that score was earned on.

    The class resolves its path lazily, so constructing one performs no
    I/O — composition-time work must not touch the disk, the contract
    every store in this workspace states — and authoring happens only
    when a caller asks for it, which is the "on demand" of feature 188's
    sentence: a composed application carries the pool *for* the
    deployment the process is running in, and writes nothing until the
    operator's call does.  Feature 191's seating is on the same terms:
    nothing is recorded for a ported world until the caller that holds
    one asks the pool to record it.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise BootstrapPoolError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # pool is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> BootstrapPool | None:
        """The pool ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not
        an error: it is a deployment without a relational store, which
        composes no pool component — a discoverable state, not an
        exception — while the operator who means to author the 40-50
        worlds §10.6 targets is the caller that must not find itself in
        it.  The split is the one the poison store's builder states: this
        method answers *what is composed*, and the caller who needs a
        pool and resolves ``None`` refuses to proceed rather than
        silently authoring nothing.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this pool persists into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this pool, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time
        an operation needs it, so a pool built from a mistyped URL fails
        at the authoring call that could report it, not at the
        composition that could not.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The store's shape ----------------------------------------------------

    def ensure_schema(self) -> None:
        """Bring the database to the shape this pool reads and writes, idempotently.

        Public because it is a real operation and not an implementation
        detail: an operator pointing this member at a fresh database runs
        it once, and a test seeds a pool into exactly the schema the
        store will read.  One ``CREATE TABLE IF NOT EXISTS``, so running
        it against a fresh database and one this pool already prepared
        take the same path and leave the same schema — and a database
        feature 188's shape is still in is *evolved* here rather than
        stranded (:func:`_evolve_pool_schema`, a guarded rebuild that
        keeps every authored row), because the table is this member's
        own and no migration can be ahead of it.

        It opens its own connection and commits it, and it does **not**
        go through :meth:`_connect`: that method calls this one, and a
        public entry point that reached back through it would be a pair
        of methods that recurse into each other until the stack ran out.
        """
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript(_SCHEMA)
            _evolve_pool_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        """Open the database, bringing it to this pool's shape first.

        The caller owns the connection; use it as a context manager to
        commit.  The schema work is delegated to :meth:`ensure_schema`
        rather than inlined, so a caller that only wants the schema does
        not have to open a connection it will not use.
        """
        self.ensure_schema()
        return sqlite3.connect(self.path)

    # -- Feature 188: the authoring -------------------------------------------

    def persist_worlds(
        self,
        count: int = DEFAULT_POOL_SIZE,
        *,
        pool_seed: int = POOL_SEED,
        persisted_at: dt.datetime | None = None,
    ) -> PersistedPool:
        """Persist ``count`` generated worlds into the pool — the feature's whole call.

        Draws ``count`` seeds from ``pool_seed`` (the SplitMix stream of
        :func:`draw_world_seed`), names each world
        (:func:`world_id_for`), constructs it — the self-check that a
        row is written only for a world this member can build, which is
        the identity level of the pool's honesty; the *label* level
        needs no gate because the committed lattice's ridge floor keeps
        every cell answerable, and a draw of a world that cannot answer
        is not a draw this pool can make — and upserts the rows in one
        transaction.  Returns the :class:`PersistedPool` report.

        Refuses, in this order, and each refusal names what it is about:

        1. a ``count`` that is not an integer in ``[40, 50]`` — the band
           of the feature's own sentence, load-bearing in both directions
           (below it the first dreaming cycle runs on a pool §12.1 rates
           as weaker; above it bootstrap worlds dominate the pool's
           composition, the imbalance feature 187 rejects on the
           reporting side);
        2. a ``pool_seed`` that is not an integer;
        3. a database this store cannot speak, or a draw that would seat
           one world under two names (a seed another row already holds) —
           the UNIQUE constraint speaking, translated here so the refusal
           names the world rather than the constraint.

        ``persisted_at`` defaults to the current UTC instant truncated to
        the second.  It is a parameter at all so a re-authoring can keep
        the instant the pool already holds rather than stamping a new
        one: on rows the draw has seated before, the upsert deliberately
        leaves ``created_at`` alone — the same world re-asserted is the
        same world (§10.6.1), not an updated one.
        """
        if isinstance(count, bool) or not isinstance(count, int):
            raise BootstrapPoolError(
                f"a pool size is an integer — got {count!r} "
                f"({type(count).__name__}); §10.6's target is a count of "
                "worlds, and a value that is not one names no pool this "
                "feature can author"
            )
        if not MIN_POOL_SIZE <= count <= MAX_POOL_SIZE:
            raise BootstrapPoolError(
                f"the replay pool persists {MIN_POOL_SIZE} to "
                f"{MAX_POOL_SIZE} bootstrap worlds — got {count!r}; "
                f"docs/nullius-tech-architecture.md §10.6 targets that "
                "band before the first financial dreaming cycle (below "
                "it, §12.1 rates the pool too thin to dream on; above "
                "it, bootstrap worlds would dominate the pool §10.6 "
                "says to then fine-tune on financial worlds against), "
                "and a size outside it is a decision the operator must "
                "make visible rather than one this store rounds away"
            )
        if isinstance(pool_seed, bool) or not isinstance(pool_seed, int):
            raise BootstrapPoolError(
                f"a pool seed is an integer — got {pool_seed!r} "
                f"({type(pool_seed).__name__}); the seed is the whole of "
                "the draw's identity, and a value that is not one names "
                "no pool this member can re-draw"
            )
        stamp = _stamp(
            persisted_at if persisted_at is not None else dt.datetime.now(dt.UTC)
        )
        records: list[WorldRecord] = []
        for index in range(count):
            world_id = world_id_for(pool_seed, index)
            seed = draw_world_seed(pool_seed, index)
            # Constructed before it is written: the constructor validates
            # the id and the seed, so a row reaches the table only for a
            # world this member can build back from it — and construction
            # performs no arithmetic (the dataset is first-label lazy), so
            # the check costs nothing.
            HyperparameterWorld(world_id, seed=seed)
            records.append(
                WorldRecord(
                    world_id=world_id,
                    seed=seed,
                    domain=POOL_DOMAIN,
                    pool_seed=pool_seed,
                    created_at=parsed_instant(stamp),
                )
            )
        with closing(self._connect()) as connection, connection:
            seated = {
                row[0]
                for row in connection.execute(
                    f"SELECT world_id FROM {POOL_TABLE}"
                )
            }
            for record in records:
                try:
                    connection.execute(
                        _UPSERT,
                        (
                            record.world_id,
                            record.seed,
                            record.domain,
                            record.pool_seed,
                            stamp,
                        ),
                    )
                except sqlite3.IntegrityError as refusal:
                    # The seed's UNIQUE constraint: another row already
                    # holds this seed under a different name.  Translated
                    # here rather than leaked, so the refusal names the
                    # world it is about — a caller reading a log should
                    # not have to know which constraint index 1 is.
                    raise BootstrapPoolError(
                        f"the world {record.world_id!r} draws seed "
                        f"{record.seed!r}, which the pool already holds "
                        "under another world_id — one seed is one world "
                        "(§10.6.1: an upstream that changes is a "
                        "different world, not a second copy of the first), "
                        "and a pool that seated it twice would over-report "
                        "the size §10.3.1's precondition turns on"
                    ) from refusal
        return PersistedPool(
            worlds=tuple(records),
            pool_seed=pool_seed,
            replayed=bool(seated.intersection(record.world_id for record in records)),
        )

    # -- Feature 191: the ported seating ---------------------------------------

    def persist_ported_world(
        self,
        world: Any,
        *,
        persisted_at: dt.datetime | None = None,
    ) -> PortedWorldRecord:
        """Persist a ported world's provenance — feature 191's whole write.

        Takes the :class:`~bootstrap.PortedWorld` a caller ported — read
        duck-typed, for its ``world_id`` and its ``provenance``, the two
        facts a row can hold; the label function is the environment's and
        is deliberately *not* recorded, for the reason no dataset is: a
        ported row is an identity, not a cache — and seats the two
        digests, the ``ported`` domain and the stamp into the same
        ``bootstrap_world`` table the authored draw writes.  Returns the
        :class:`PortedWorldRecord` the row now holds.

        The reconciliation is the feature's own clause.  A world id the
        pool does not hold seats a new row.  A world id the pool holds
        *with the same digests* is the same world re-asserted — the
        record answers with the row's own ``created_at``, the first
        instant the upstream was seated, exactly as a re-run of the
        authored draw keeps its first authoring.  A world id the pool
        holds *with different digests* is an upstream that changed
        wearing an old world's name, and the call refuses with
        :class:`~bootstrap.BootstrapWorldError` rather than re-hashing
        the row — §10.6.1's rule, which is why there is no ``ON
        CONFLICT`` arm on the ported insert to silently do the forbidden
        thing.  The changed upstream's one legal move is a world id of
        its own, and seating it there is exactly what this method is for.

        Refuses, in this order, each naming what it is about:

        1. a world that cannot name itself (no usable ``world_id``), or
           that carries no :class:`~bootstrap.Provenance` — the two
           things the row is made of, refused before the database opens;
        2. a world id that already names an *authored* world of the pool
           — one name is one world, and an authored row answering a
           ported ask would answer labels it never recorded;
        3. a world id recorded against a different upstream — the
           refusal above, with both digest pairs in the message so an
           operator reading it can see *which* half of the upstream
           moved.

        ``persisted_at`` defaults to the current UTC instant truncated to
        the second, and is a parameter for the same reason the draw's is.
        """
        world_id = getattr(world, "world_id", None)
        if not isinstance(world_id, str) or not world_id.strip():
            raise BootstrapPoolError(
                f"a ported world is persisted under its id — got {world!r}; "
                "the id is how the row is named and a re-port checked, and "
                "a world that cannot name itself records nothing the pool "
                "could verify against an upstream"
            )
        provenance = getattr(world, "provenance", None)
        if not isinstance(provenance, Provenance):
            raise BootstrapWorldError(
                f"a ported world carries its provenance — got {provenance!r}; "
                "the digests are the whole of what this store records for "
                "a ported world, and a world that carries none has no "
                "upstream a re-port could be checked against (§10.6.1: an "
                "upstream that changes is a different world)"
            )
        stamp = _stamp(
            persisted_at if persisted_at is not None else dt.datetime.now(dt.UTC)
        )
        with closing(self._connect()) as connection, connection:
            row = connection.execute(_SELECT_ROW, (world_id,)).fetchone()
            if row is not None:
                # Seated already: same digests answer the held record
                # (and keep its first instant); different ones are the
                # refusal this feature exists to make.
                return _reconcile_ported_row(row, provenance)
            try:
                connection.execute(
                    _PORTED_INSERT,
                    (
                        world_id,
                        None,
                        PORTED_DOMAIN,
                        None,
                        stamp,
                        provenance.source_commit,
                        provenance.dataset_manifest,
                    ),
                )
            except sqlite3.IntegrityError as refusal:
                # Another writer seated this id between the read and the
                # insert.  Translated through the reconciliation rather
                # than leaked, so the refusal — if it is one — names the
                # world and both upstreams instead of the constraint.
                row = connection.execute(_SELECT_ROW, (world_id,)).fetchone()
                if row is None:  # pragma: no cover - the insert's own subject
                    raise BootstrapPoolError(
                        f"the ported world {world_id!r} could not be "
                        f"seated — the table refused the row ({refusal}); "
                        "an operator reading this should not have to work "
                        "out which constraint spoke"
                    ) from refusal
                return _reconcile_ported_row(row, provenance)
            return PortedWorldRecord(
                world_id=world_id,
                source_commit=provenance.source_commit,
                dataset_manifest=provenance.dataset_manifest,
                created_at=parsed_instant(stamp),
            )

    # -- The reads ------------------------------------------------------------

    def worlds(self) -> tuple[WorldRecord, ...]:
        """Every authored world the pool holds, ascending by world id.

        The authored half of the pool — rows with a seed, drawn by
        :meth:`persist_worlds` — because a :class:`WorldRecord` is a seed
        identity and a ported row has none; the ported half is read by
        :meth:`ported_worlds`, and :meth:`world_count` counts both.

        Explicitly ordered (§12's ordering rule, restated for a store):
        two reads of one pool return the same sequence whatever the
        storage engine's accident, and a report rendered from the tuple
        is reproducible.  Empty when nothing has been authored — an
        *empty pool* is a statement about what has been authored, not
        about composition, and it is feature 186's count that reports it
        against the financial half.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(_ROW_COLUMNS)} FROM {POOL_TABLE} "
                f"WHERE seed IS NOT NULL ORDER BY world_id"
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def ported_worlds(self) -> tuple[PortedWorldRecord, ...]:
        """Every ported world the pool holds, ascending by world id.

        The ported half — rows with provenance and no seed, seated by
        :meth:`persist_ported_world` — read as
        :class:`PortedWorldRecord` values because the pool cannot
        rebuild what it never generated: the labels live in the
        environment they were ported from, so the record (the two
        digests, the domain, the instant) is the whole of what the pool
        can answer for, and the caller that needs the *world* re-ports
        it through :func:`~bootstrap.ported_world` and checks it with
        :meth:`verify_ported_world`.

        Ordered by world id under the same §12 rule as :meth:`worlds`,
        so a report naming both halves of one pool reads them in one
        order.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(_ALL_COLUMNS)} FROM {POOL_TABLE} "
                f"WHERE seed IS NULL ORDER BY world_id"
            ).fetchall()
        return tuple(_ported_record_from_row(row) for row in rows)

    def world_count(self) -> int:
        """How many worlds the pool holds — the bootstrap half of feature 186's tally.

        Both halves, authored and ported: §10.6's target counts *worlds*
        ("Authored worlds and ported external worlds both qualify"), and
        §12.1's ladder reads the total — "below 20 worlds", "between 20
        and 50" — not one half of it.  A count of rows rather than
        ``len(self.worlds()) + len(self.ported_worlds())``, because the
        question the dreaming loop asks of the pool is a number, and a
        number that built every record of both halves to answer would
        pay for a hundred identities to return one integer.
        """
        with closing(self._connect()) as connection:
            (held,) = connection.execute(
                f"SELECT COUNT(*) FROM {POOL_TABLE}"
            ).fetchone()
        return int(held)

    def verify_ported_world(
        self, world_id: str, upstream: Provenance
    ) -> PortedWorldRecord:
        """Check a seated ported world against the upstream a caller can see.

        The refusal half of feature 191's sentence, as a read: the row's
        *recorded* digests against the ``upstream`` the caller presents —
        the pair the source repo and its dataset manifest *now* hash to,
        which only a caller positioned at the upstream can know.  They
        match and the world is the one it claims to be: the record
        answers, and a replay may attribute scores to it.  They differ
        and the world is refused with
        :class:`~bootstrap.BootstrapWorldError` — *"Refuse the world.  A
        changed upstream is a different world, not an updated one"*
        (§10.6.1, and the failure table's row for exactly this state) —
        naming the world and both digest pairs, so an operator reading
        the refusal can see which half of the upstream moved.

        Refuses a world id that is not a usable identifier, an
        ``upstream`` that is not a :class:`~bootstrap.Provenance`
        (nothing else names an upstream this check could read), a world
        id the pool does not hold (naming it and the count it does), and
        a world id that names an *authored* world (the ask was never
        about a ported one) — the last two as
        :class:`~bootstrap.BootstrapPoolError`, because they are the
        pool's own refusals rather than the world's.
        """
        if not isinstance(world_id, str) or not world_id.strip():
            raise BootstrapPoolError(
                f"a world id is a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the id is how a pool row "
                "is named and an upstream checked against it, and an id "
                "that is not one addresses no world this pool holds"
            )
        if not isinstance(upstream, Provenance):
            raise BootstrapWorldError(
                f"an upstream is named by its digests — got {upstream!r} "
                f"({type(upstream).__name__}); the check compares the "
                "two digests the row recorded against the two the "
                "upstream now shows, and a value that is not a "
                "Provenance names no upstream either side of that "
                "comparison"
            )
        with closing(self._connect()) as connection:
            row = connection.execute(_SELECT_ROW, (world_id,)).fetchone()
        if row is None:
            held = self.world_count()
            raise BootstrapPoolError(
                f"the replay pool holds no world {world_id!r} — it holds "
                f"{held} world(s); a world id is either one a seating "
                "call seated or it is nothing, and a check that answered "
                "for a neighbouring row would admit a world the pool "
                "never recorded"
            )
        return _reconcile_ported_row(row, upstream)

    def world(self, world_id: str) -> HyperparameterWorld:
        """The world a persisted row names — the replay engine's read.

        Builds the :class:`~bootstrap.HyperparameterWorld` from the row's
        own seed, so the world the caller labels against is the world
        the row recorded — bit for bit, in any process, because the
        dataset is a pure function of that seed.  Construction stays
        lazy: this method returns the world holding no dataset, and the
        first ``label()`` is where the arithmetic begins.

        Refuses a world id the pool does not hold, naming it and the
        count it does: a caller that misspells an id wants a refusal it
        can read, not a world silently served from a neighbouring row —
        the same "refused, not created" discipline the poison store
        applies to a node the tree does not hold.  Refuses a world id
        that names a *ported* world for the plainer reason that this
        read has no seed to build from — the ported half is read by
        :meth:`ported_worlds`, and a ported world's labels are the
        environment's to answer, not a draw's.
        """
        if not isinstance(world_id, str) or not world_id.strip():
            raise BootstrapPoolError(
                f"a world id is a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the id is how a pool row "
                "is named and a label attributed, and an id that is not "
                "one addresses no world this pool holds"
            )
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {', '.join(_ROW_COLUMNS)} FROM {POOL_TABLE} "
                f"WHERE world_id = ?",
                (world_id,),
            ).fetchone()
        if row is None:
            held = self.world_count()
            raise BootstrapPoolError(
                f"the replay pool holds no world {world_id!r} — it holds "
                f"{held} world(s); a world id is either one a "
                "persist_worlds call seated or it is nothing, and a pool "
                "that answered from a neighbouring row would attribute a "
                "score to a world that never earned it"
            )
        if row[1] is None:
            raise BootstrapPoolError(
                f"the world {world_id!r} is a ported world of the pool — "
                "the authored read builds a HyperparameterWorld from a "
                "seed, and a ported row holds none; its record is read "
                "by ported_worlds() and its upstream checked by "
                "verify_ported_world(), because its labels are the "
                "environment's to answer, not a draw's"
            )
        record = _record_from_row(row)
        return HyperparameterWorld(record.world_id, seed=record.seed)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"BootstrapPool(database_url={self._database_url!r})"
