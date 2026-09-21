"""The bootstrap replay pool — feature 188's authoring and persistence.

app_spec.xml, "Bootstrap Worlds", feature 188: *System persists 40 to 50
generated bootstrap worlds into the replay pool on demand.*  §10.6 states
what that converts the pool-size precondition into:

    This converts the §10.3.1 pool-size precondition from a calendar
    problem into a compute problem.  Target 40–50 bootstrap worlds before
    the first financial dreaming cycle, then fine-tune on financial
    worlds.

Feature 181 built the world this pool is made of; this module builds the
*pool* — the thing that turns one world into the forty-something the
first dreaming cycle needs before it may run (§12.1's ladder blocks
dreaming below 20 worlds and caps it at 8-10 revisions between 20 and 50,
so the band this feature persists is the band that unlocks the target).

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
that state.

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
:meth:`~bootstrap.BootstrapPool.world_count`) but does not tally it
*against* the financial pool — feature 186's independent count and
feature 187's headline refusal are statements about both pools, made
where both are visible.  It draws only hyperparameter worlds (the
``hpo`` domain §10.6's tree names first); the feature-selection and
symbolic-regression domains (features 182-183) and the ported adapter
(190-191) join the same table through the same ``domain`` column when
they exist, which is why the column is part of the row rather than a
fact about the table.  And it charges no budget, decrements nothing and
consults no clock beyond the authoring stamp — feature 185's
``charges_budget`` is a fact about the *trial*, and §10.6's *"no
dependence on market time"* is a fact about the worlds.

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
from urllib.parse import unquote, urlparse

from ._stream import GOLDEN_GAMMA, MASK64, mix64
from ._world import HyperparameterWorld
from .errors import BootstrapPoolError

__all__ = [
    "DATABASE_URL_ENV",
    "DEFAULT_POOL_SIZE",
    "MAX_POOL_SIZE",
    "MIN_POOL_SIZE",
    "POOL_COMPONENT_NAME",
    "POOL_DOMAIN",
    "POOL_SEED",
    "POOL_TABLE",
    "BootstrapPool",
    "PersistedPool",
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
#: tree has four branches and the other three — ``featsel``, ``symreg``,
#: ``ported`` — are later features of this category that join this pool
#: through this column without widening it.
POOL_DOMAIN = "hpo"

#: The row's column names, in declaration order — the one spelling of
#: what a pool row is made of, shared by the DDL, the insert and the
#: read-back so the three cannot disagree on a column order, the failure
#: a positional ``SELECT *`` invites and the one the poison store's own
#: ``_COLUMNS`` constant exists to prevent.
_ROW_COLUMNS = ("world_id", "seed", "domain", "pool_seed", "created_at")

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
CREATE TABLE IF NOT EXISTS {POOL_TABLE} (
    world_id    TEXT    NOT NULL PRIMARY KEY,
    seed        INTEGER NOT NULL UNIQUE,
    domain      TEXT    NOT NULL,
    pool_seed   INTEGER NOT NULL,
    created_at  TEXT    NOT NULL
)
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


class BootstrapPool:
    """Feature 188's store: the bootstrap half of the replay pool.

    Constructed with the database URL it persists into;
    :meth:`persist_worlds` authors 40-50 generated worlds into the table
    on demand; :meth:`worlds` and :meth:`world_count` read what the pool
    holds; :meth:`world` builds the :class:`~bootstrap.HyperparameterWorld`
    a persisted row names, which is the read the replay engine makes —
    the pool is the thing that turns a world id in a ``replay_score`` row
    back into the world that score was earned on.

    The class resolves its path lazily, so constructing one performs no
    I/O — composition-time work must not touch the disk, the contract
    every store in this workspace states — and authoring happens only
    when a caller asks for it, which is the "on demand" of the feature's
    sentence: a composed application carries the pool *for* the
    deployment the process is running in, and writes nothing until the
    operator's call does.
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
        take the same path and leave the same schema — and there is no
        ``ALTER TABLE`` half to guard, because the table is this
        member's own and no migration can be ahead of it.

        It opens its own connection and commits it, and it does **not**
        go through :meth:`_connect`: that method calls this one, and a
        public entry point that reached back through it would be a pair
        of methods that recurse into each other until the stack ran out.
        """
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript(_SCHEMA)

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

    # -- The reads ------------------------------------------------------------

    def worlds(self) -> tuple[WorldRecord, ...]:
        """Every world the pool holds, ascending by world id.

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
                f"ORDER BY world_id"
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def world_count(self) -> int:
        """How many worlds the pool holds — the bootstrap half of feature 186's tally.

        A count of rows rather than ``len(self.worlds())``, because the
        question the dreaming loop asks of the pool is a number (§12.1's
        ladder reads "below 20 worlds", "between 20 and 50"), and a
        number that built every record to answer would pay for 50
        identities to return one integer.
        """
        with closing(self._connect()) as connection:
            (held,) = connection.execute(
                f"SELECT COUNT(*) FROM {POOL_TABLE}"
            ).fetchone()
        return int(held)

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
        applies to a node the tree does not hold.
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
        record = _record_from_row(row)
        return HyperparameterWorld(record.world_id, seed=record.seed)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"BootstrapPool(database_url={self._database_url!r})"
