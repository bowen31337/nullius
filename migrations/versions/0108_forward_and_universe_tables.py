"""The forward-test and universe tables, in one versioned migration (feature 108).

app_spec.xml feature 108: "System creates the forward_record,
promotion_registry, universe_membership, universe_price_history and
universe_survivorship_audit tables in one versioned migration." The task that
lands this file also names ``snapshot_manifest``, so that table is created here
too — see "Why snapshot_manifest is in this migration" below.

Why these tables belong together
--------------------------------

They are the *outcome* end of the system. Everything upstream — the tree, the
trial ledger, the replay pool — is machinery for deciding what to believe.
These six tables are what the system believes *afterwards*, and each one is a
promise made to a later reader who cannot re-derive it:

* ``forward_record`` (§13.4) is the one record in the system computed on data
  that **did not exist when the hypothesis was formed**. Its ``promoted_at`` /
  ``observed_on`` pair is the boundary between backtest and out-of-sample; a
  row that lost its promotion timestamp would be an observation with no
  vintage, which is exactly the thing forward testing exists to prevent.
* ``promotion_registry`` is the pre-registration record (feature 96's
  neighbourhood): ``criteria_hash`` and ``pre_registered_at`` are written
  *before* the deciding evaluation, and ``decided_at`` after. The two-timestamp
  shape is the whole point — an auditor reads the row and sees that the
  criteria preceded the decision, which is the claim a promotion has to make
  to be more than a fitted number.
* ``universe_membership`` is §4.3's point-in-time table,
  ``(symbol, valid_from, valid_to, delist_reason)``, resolved as of ``t`` and
  never as of now.
* ``universe_price_history`` is §4.3's "including delisted symbols with their
  full history" — the retained closes, delistings included.
* ``universe_survivorship_audit`` is the monthly proof that the retention
  actually happened: how many (and which) delisted names are present in a
  window that the membership table says they left.
* ``snapshot_manifest`` is feature 33's record naming the exact bytes a score
  was computed over.

Why one migration rather than six
---------------------------------

Because they are read together. A replay that resolves membership, reads the
retained price history and checks the survivorship audit must see one schema
version, not a window where half of the group exists. Splitting them would let
a reader observe a database where membership resolves but the price history it
is joined against is absent — a query that returns *empty* rather than failing,
which is the failure mode this whole group is written against.

This is also the honest grouping of the spec: features 97-107 each own a slice
of the tree/ledger schema, and the spec put all five of these in one feature.

Convergence with the code that already creates them
---------------------------------------------------

Four of these tables are *already created* by shipped, green code, with
``CREATE TABLE IF NOT EXISTS``, and more than one module creates the same table
(``universe_price_history`` is created by both :mod:`universe.store` and
:mod:`universe.history`). Those docstrings say what should happen when this
file arrives:

    "when the full versioned migration tree lands, this ``CREATE TABLE IF
    NOT EXISTS`` is the statement it adopts" (``snapshot/_manifest_store.py``)

So this migration does not invent a schema — it **adopts** the shipped one, and
every statement below is ``IF NOT EXISTS``, so applying it to a dev or test
database that the stores already populated is a no-op rather than an error.
Every column *type*, key and index here is the one the shipped writers and
readers actually use; the only differences are two ``NOT NULL`` flags the
migration adds to primary-key columns, argued in "Every primary key is spelled
NOT NULL PRIMARY KEY" below and verified to be additive-only (no writer supplies
a null key, and where a store created the table first the migration's
``IF NOT EXISTS`` cannot tighten it — so a pre-existing database is untouched).

Two places below depart from the spec's schema block on the shipped code's
authority rather than the spec's text: ``snapshot_manifest``'s column count and
its nullable ``row_count``, and ``universe_membership``'s composite key (detail
5). Each is called out where it occurs and justified by the code it adopts from,
because a reader comparing this file against the spec should find the
divergence explained at the site rather than discover it.

Five details are load-bearing and were checked against the code rather than
against the spec's summary, because a summary cannot carry them:

1. ``snapshot_manifest`` carries **nine** columns, not the six in the spec's
   schema block. The store's ``INSERT OR REPLACE`` names all nine, so a
   six-column table here would break every seal. The three additions and their
   justification live in ``snapshot/_manifest_store.py``; this migration adopts
   the result rather than restating the argument.
2. ``row_count`` is **nullable** — one manifest state carries no row concept,
   and a fabricated ``0`` is the fiction feature 33 refuses.
3. ``universe_price_history`` is keyed ``(symbol, date)``. The key is not
   decoration: ``universe/history.py`` and ``universe.store`` both ingest with
   ``ON CONFLICT(symbol, date) DO UPDATE``, which SQLite rejects outright if no
   matching unique constraint exists. ``universe_survivorship_audit`` is keyed
   by ``month`` because the spec says so and one row per month is the table's
   meaning; note that unlike the price history it does *not* upsert — its
   writer deletes and re-inserts the whole table
   (``universe.store._recompute_survivorship_audit``), so the key is what makes
   a duplicate month impossible rather than what an upsert resolves against.
4. ``snapshot_manifest.row_count`` is nullable while the spec's block declares
   it ``NOT NULL``. This is not a slackening introduced here: it is the shipped
   store's documented, deliberate deviation, carrying a test that asserts
   ``row_count IS NULL`` is readable — see the paragraph beginning "So
   ``row_count`` is nullable *for this one state only*" in
   ``snapshot/_manifest_store.py``.
5. ``universe_membership`` is keyed ``(symbol, valid_from)``, which the spec's
   schema block does *not* declare — it lists four columns and no key at all.
   The key comes from the shipped store's ``CREATE`` statement, and it is kept
   because the table is meaningless without it: ``universe.membership`` derives
   one row per *run* of consecutive admitted months, and a symbol that left and
   later returned is two runs of the same symbol, so ``(symbol, valid_from)``
   is the only pair that identifies a row. It is load-bearing rather than
   conventional: the key admits the two-row leave-and-return case (verified —
   three builds, BTC admitted/absent/readmitted, produce BTC at ``2026-01-01``
   closed and BTC at ``2026-03-01`` open) while refusing a duplicate key, which
   is the one state the derivation must never produce. The writer
   (``universe.store._recompute_membership``) replaces the table wholesale
   inside the persist transaction, so the key does not resolve an upsert; it
   makes the invariant checkable by the database instead of by convention.

   The spec's own §4.3 prose is what settles this. It says membership "is
   stored as a point-in-time table: ``(symbol, valid_from, valid_to,
   delist_reason)``" — a table whose rows are intervals is keyed by the start
   of the interval, and the schema block's omission reads as a summary that did
   not restate the key rather than as a deliberate keyless table, since a
   keyless SQL table cannot express "resolve membership as of ``t``" in the
   first place.

Why ``snapshot_manifest`` is in this migration
----------------------------------------------

Feature 108's table list does not include it, but the task does, and feature
33's store is the one table in this group that already has a writer and no
versioned home. Creating it here is the adoption its docstring anticipates, and
it costs nothing where it is already created. It is deliberately *not* given a
new shape — see point 1 above.

Dialect
-------

The repository runs SQLite on a single machine (the app spec's dev allowance,
and what ``tests/conftest.py`` points ``DATABASE_URL`` at) and Postgres 16 in
production (§9.1). The spec's DDL is Postgres spelling, and exactly one
construct in it does not survive the trip: ``DEFAULT gen_random_uuid()`` is a
syntax error in SQLite, whose grammar allows no function call in a ``DEFAULT``
clause unless it is parenthesised. ``DEFAULT NOW()`` fails the same way, but no
table here needs a defaulted timestamp, so the split is one expression wide.
``UUID``, ``TIMESTAMPTZ``, ``JSON``/``JSONB``, ``CHAR(64)`` and ``REAL`` are
all accepted by SQLite as column types (it applies its own affinity), so the
column lists are otherwise identical between dialects and there is no second
schema to keep in step.

The SQLite default is a genuine RFC 4122 version-4 UUID built from
``randomblob`` — not a hex string that merely looks like one — so an id minted
by the default is the same *kind* of value as ``gen_random_uuid()`` returns,
and a row is readable by the same code on either dialect. A caller that needs a
specific id still supplies one; the default exists so that
``INSERT ... (node_id, promoted_at, observed_on)`` is a complete statement.

Every primary key is spelled ``NOT NULL PRIMARY KEY``
-----------------------------------------------------

Three columns below are declared by the spec as a bare
``<type> PRIMARY KEY`` — ``forward_record.id``, ``promotion_registry.id`` and
``snapshot_manifest.snapshot_hash`` — and all three are written here with an
explicit ``NOT NULL``. That is a deliberate correction, not fussiness, and it
is worth stating because the opposite choice looks harmless.

Postgres makes a primary key's columns ``NOT NULL`` implicitly, so on
production the two spellings are the same table. SQLite does **not**: on a
rowid table a bare ``PRIMARY KEY`` permits NULL, and because NULLs compare
distinct from one another it permits *several* NULL-keyed rows. So the bare
spelling would let a SQLite database hold two rows with a null
``snapshot_hash`` — a state the table exists to make impossible, since the
column is what a score keys on (feature 33's "name the exact bytes"). A
uniqueness guarantee that holds in production and silently lapses in the
database every test runs against is worse than either failure on its own.

Anything that writes these tables supplies a real key, so nothing that works
against a bare-key table is refused here; and because the statement is
``IF NOT EXISTS``, a database whose store created the table first is left
exactly as it was — the tightening can only apply where this migration is the
thing that creates the table. ``universe_survivorship_audit.month`` carries it
for the same reason, with the store's own ``CREATE`` statement cited at the
site.

Foreign keys and ordering
-------------------------

``forward_record.node_id`` and ``promotion_registry.node_id`` reference
``node(id)``; ``promotion_registry.epoch_id`` references
``epoch_ledger(epoch_id)``. Both parents are created by *sibling* features
(97 and 105), so this migration is not a root: it chains after them and
declares them in :data:`REQUIRES_TABLES`. Postgres validates a foreign key's
parent at ``CREATE TABLE`` time, so on production this file must run after
those two — which is what the revision chain expresses, and why
``down_revision`` is set rather than left ``None``.

SQLite does not resolve the parent until a row is written, so the statements
below are accepted in either order there. That is a tolerance, not a licence:
the dependency is real and is stated twice, in the chain and in
:data:`REQUIRES_TABLES`, so neither can be read without meeting it.

Revision chaining, and the one fact this file cannot verify
-----------------------------------------------------------

No migration tree existed in this repository when this file landed — no
``alembic.ini``, no ``env.py``, and features 97-107 are being written by other
agents in parallel, each with its own file claim. So the revision ids are
declared by a convention rather than read off an existing chain: the id is
``<feature index, zero-padded to four>_<slug>``, and ``down_revision`` is the
predecessor's id under the same convention. Feature 107 is this file's
predecessor in the spec's own ordering.

:data:`DOWN_REVISION` is therefore the single string that may need reconciling
when the tree is assembled. It is set to the deterministic sibling id rather
than to ``None`` because the dependency above is real and because eleven
independent root revisions would fail ``alembic upgrade head`` with multiple
heads, whereas one id to reconcile is a one-line edit.

Two consequences follow, stated so they are not discovered later:

* This module imports nothing from Alembic. Alembic is not a dependency of
  this workspace and is not in ``uv.lock``; importing it would make this file
  unimportable and untestable, and would make the module's own runtime path
  depend on a tool that is not installed. The module-level ``revision`` /
  ``down_revision`` / ``upgrade`` / ``downgrade`` names are the surface Alembic
  looks for, so it is a drop-in revision when the tooling lands — but the
  module runs today, standalone and stdlib-only, through :func:`apply`.
* Postgres is not spoken here without a driver. :func:`apply` opens SQLite
  itself, because the stdlib can; a Postgres caller passes its own DBAPI
  connection to :func:`upgrade` and this module never pretends to have one.

Idempotency and re-runnability
------------------------------

Every statement is ``IF NOT EXISTS`` and ``downgrade`` is ``DROP TABLE IF
EXISTS`` in reverse dependency order, so upgrade is re-runnable against a
database that already holds the tables, and a downgrade followed by an upgrade
round-trips to the same schema. Neither direction drops data it did not create:
``downgrade`` is destructive by definition, but the stores recreate their own
tables idempotently, so a downgraded database is one the next persist refills
rather than one left broken.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

__all__ = [
    "DATABASE_URL_ENV",
    "DOWN_REVISION",
    "INDEXES",
    "REQUIRES_TABLES",
    "REVISION",
    "TABLES",
    "apply",
    "connect",
    "downgrade",
    "statements",
    "upgrade",
]

# ── Version identity ─────────────────────────────────────────────────────────

#: This migration's revision id (feature 108). See the module docstring for
#: the naming convention and why it is not read off an existing chain.
REVISION = "0108_forward_and_universe_tables"

#: The revision this one chains after — feature 107's, under the same
#: convention. The one string to reconcile when the tree is assembled; see the
#: module docstring.
DOWN_REVISION = "0107_regime_coverage"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: Tables that must already exist for this migration to be valid on a dialect
#: that validates foreign keys at DDL time (Postgres). Created by sibling
#: features 97 and 105. Declared here as well as in the revision chain so the
#: dependency cannot be read past.
REQUIRES_TABLES = ("node", "epoch_ledger")

#: The tables this migration creates, in creation order (referencing tables
#: first is harmless; the parents are asserted above).
TABLES = (
    "forward_record",
    "promotion_registry",
    "universe_membership",
    "universe_price_history",
    "universe_survivorship_audit",
    "snapshot_manifest",
)

#: The indexes this migration creates. These three are exactly the ones the
#: shipped stores already create — no more — because a migration is the wrong
#: place to invent a query plan for readers that do not exist yet. What the
#: spec fixes for these tables is the column list; the indexes here keep the
#: migration convergent with the code that reads them today.
INDEXES = (
    "universe_membership_symbol_valid_from",
    "universe_price_history_symbol_date",
    "snapshot_manifest_sealed_at",
)

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── Dialect ──────────────────────────────────────────────────────────────────

#: The Postgres default: the spec's own spelling, and the reason a Postgres
#: ``id`` column needs no value supplied.
_POSTGRES_UUID_DEFAULT = "gen_random_uuid()"

#: The SQLite equivalent: an RFC 4122 version-4 UUID, built from ``randomblob``
#: so the variant and version nibbles are the ones a v4 UUID must carry rather
#: than whatever the random source happened to produce. The surrounding
#: parentheses are required — SQLite's ``DEFAULT`` grammar accepts a function
#: call only when it is parenthesised, which is precisely why the spec's
#: ``gen_random_uuid()`` is a syntax error there.
_SQLITE_UUID_DEFAULT = (
    "(lower("
    "hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || "
    "substr(hex(randomblob(2)), 2) || '-' || "
    "substr('89ab', abs(random()) % 4 + 1, 1) || "
    "substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6))"
    "))"
)


def _uuid_default(dialect: str) -> str:
    """The ``id`` column default for ``dialect``.

    The only construct in this migration that differs between dialects; see
    the module docstring. An unknown dialect gets the Postgres spelling, which
    is the spec's — a caller running something else is off the documented
    path, and silently handing it a SQLite expression would hide that.
    """
    return _SQLITE_UUID_DEFAULT if dialect == "sqlite" else _POSTGRES_UUID_DEFAULT


def _dialect_of(connection: object) -> str:
    """Name the dialect of a DBAPI connection, conservatively.

    Only ``sqlite`` is recognised positively. Everything else is reported as
    ``other`` and receives the spec's Postgres spelling, because the production
    target is Postgres and an unrecognised driver is far likelier to be
    Postgres-compatible than to share SQLite's ``DEFAULT`` grammar.
    """
    module = type(connection).__module__ or ""
    if module.split(".")[0] == "sqlite3":
        return "sqlite"
    return "other"


# ── The statements ───────────────────────────────────────────────────────────


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    Every statement is idempotent. Column lists, keys and indexes are the ones
    the shipped stores use; see the module docstring for the three details the
    spec's schema block cannot carry.
    """
    uuid_default = _uuid_default(dialect)
    return (
        # Feature 108 / §13.4. One row per promoted signal per observation
        # date: `promoted_at` is when the hypothesis was frozen, `observed_on`
        # the day the live IC was read, and the pair is the vintage a forward
        # record exists to carry. The three REAL columns are nullable because
        # a freshly promoted signal has no observation yet — a NOT NULL here
        # would force a fabricated zero on the day of promotion, which would
        # read as "measured, and it was zero".
        f"""
        CREATE TABLE IF NOT EXISTS forward_record (
            id                UUID NOT NULL PRIMARY KEY DEFAULT {uuid_default},
            node_id           UUID NOT NULL REFERENCES node(id),
            promoted_at       TIMESTAMPTZ NOT NULL,
            observed_on       DATE NOT NULL,
            live_ic           REAL,
            backtest_ic       REAL,
            realized_cost_bps REAL
        )
        """,
        # Feature 108 / feature 96. The pre-registration row. `criteria_hash`
        # is the hash of the criteria as they were written *before* the
        # deciding evaluation, and `pre_registered_at` / `decided_at` are the
        # two timestamps an auditor compares; `decided_at` is nullable because
        # the row is written while the decision is still open, which is the
        # only ordering under which pre-registration means anything.
        f"""
        CREATE TABLE IF NOT EXISTS promotion_registry (
            id                UUID NOT NULL PRIMARY KEY DEFAULT {uuid_default},
            node_id           UUID NOT NULL REFERENCES node(id),
            epoch_id          TEXT NOT NULL REFERENCES epoch_ledger(epoch_id),
            criteria_hash     CHAR(64) NOT NULL,
            pre_registered_at TIMESTAMPTZ NOT NULL,
            decided_at        TIMESTAMPTZ
        )
        """,
        # Feature 41 / §4.3, adopted from `universe.store` (identical here —
        # this table's key columns already carry NOT NULL). The composite key
        # is the interval identity: a symbol's membership is keyed by its
        # start, so a symbol that left and later returned holds two rows rather
        # than one rewrite — the history §4.3 requires. Note the spec's schema
        # block lists this table's four columns and no key; the key is kept on
        # the shipped statement's authority and §4.3's prose. See detail 5 in
        # the module docstring.
        # `valid_to` and `delist_reason` are NULL together, exactly while the
        # interval is open; the derivation in `universe.membership` maintains
        # that pairing.
        """
        CREATE TABLE IF NOT EXISTS universe_membership (
            symbol        TEXT NOT NULL,
            valid_from    DATE NOT NULL,
            valid_to      DATE,
            delist_reason TEXT,
            PRIMARY KEY (symbol, valid_from)
        )
        """,
        # Feature 43, adopted from `universe.store` and `universe.history`
        # (identical here — this table's key columns already carry NOT NULL).
        # The composite key is load-bearing, not
        # decorative: history.py upserts with ON CONFLICT(symbol, date), which
        # SQLite refuses outright when no matching unique constraint exists.
        """
        CREATE TABLE IF NOT EXISTS universe_price_history (
            symbol TEXT NOT NULL,
            date   DATE NOT NULL,
            close  REAL NOT NULL,
            PRIMARY KEY (symbol, date)
        )
        """,
        # Feature 44. One row per month, re-derived from the builds: how many
        # delisted names, and which, are still present in a window the
        # membership table says they left. `delisted_symbols` is JSON text
        # rather than a child table because it is read whole, as evidence.
        #
        # `month` carries NOT NULL explicitly, where the store's own DDL writes
        # a bare `TEXT PRIMARY KEY`. That is not decoration: SQLite's PRIMARY
        # KEY does *not* imply NOT NULL on a rowid table — it accepts a NULL
        # month, and NULLs compare distinct, so a bare key would admit several
        # null-month rows where the spec declares one NOT NULL key. The spec
        # says `month TEXT NOT NULL` and this is the spelling that means it on
        # both dialects. Every writer supplies a real month, so nothing that
        # works against the store's table is refused here.
        """
        CREATE TABLE IF NOT EXISTS universe_survivorship_audit (
            month            TEXT NOT NULL PRIMARY KEY,
            window_start     DATE NOT NULL,
            window_end       DATE NOT NULL,
            delisted_present INTEGER NOT NULL,
            delisted_symbols JSON NOT NULL
        )
        """,
        # Feature 33, adopted from `snapshot._manifest_store` — the spec's six
        # columns in the spec's order, plus the three that store adds
        # (`content_digest` pins the byte-level identity the phrase "exact
        # bytes" needs and the six cannot express; `manifest_digest` stores the
        # canonical manifest text under the same version; `manifest_version`
        # records the manifest format version the row describes). The store
        # INSERTs nine columns, so the nine-column shape is the one that works.
        # `row_count` is nullable for exactly one state — a manifest whose own
        # total_rows is null, because some file format carries no row concept.
        # `snapshot_hash` carries NOT NULL where the store's own CREATE leaves
        # it bare; on SQLite that is the difference between one row per hash
        # and several, since a bare key accepts repeated NULLs. See the module
        # docstring.
        """
        CREATE TABLE IF NOT EXISTS snapshot_manifest (
            snapshot_hash       CHAR(64) NOT NULL PRIMARY KEY,
            sealed_at           TIMESTAMPTZ NOT NULL,
            file_count          INT NOT NULL,
            row_count           BIGINT,
            universe_definition JSONB NOT NULL,
            schema_version      TEXT NOT NULL,
            content_digest      CHAR(64) NOT NULL,
            manifest_digest     CHAR(64) NOT NULL,
            manifest_version    INT NOT NULL
        )
        """,
        # The three indexes the shipped stores already create. Kept identical
        # so the migration and the code converge rather than duplicate.
        """
        CREATE INDEX IF NOT EXISTS universe_membership_symbol_valid_from
            ON universe_membership (symbol, valid_from)
        """,
        """
        CREATE INDEX IF NOT EXISTS universe_price_history_symbol_date
            ON universe_price_history (symbol, date)
        """,
        """
        CREATE INDEX IF NOT EXISTS snapshot_manifest_sealed_at
            ON snapshot_manifest (sealed_at)
        """,
    )


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    Referencing tables are dropped before what they reference, so the sequence
    is valid on a dialect that checks a drop's dependents.
    """
    drops = [f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)]
    drops += [f"DROP INDEX IF EXISTS {index}" for index in reversed(INDEXES)]
    return tuple(drops)


# ── Running it ───────────────────────────────────────────────────────────────


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Create the tables on ``connection``; returns the statements executed.

    Takes any DBAPI connection. The caller owns the transaction — this
    function neither commits nor rolls back, so a caller that is already inside
    a transaction (a migration runner, a test) does not have its unit of work
    split by an implicit commit. Use a context manager, or call
    :func:`apply`, which opens and commits its own SQLite connection.

    ``dialect`` overrides detection. Detection exists so the common case needs
    no argument; see :func:`_dialect_of` for what it recognises and why an
    unrecognised connection gets the spec's Postgres spelling.
    """
    resolved = dialect if dialect is not None else _dialect_of(connection)
    ddl = statements(resolved)
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


def downgrade(connection: object) -> tuple[str, ...]:
    """Drop the tables this migration created; returns the statements executed.

    Destructive by definition. It is idempotent, and it drops only the objects
    this migration creates — a database downgraded here is refilled by the next
    persist of each store, which creates its own table idempotently.
    """
    ddl = _drop_statements()
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The same convention ``universe.store`` uses, and deliberately re-stated
    rather than imported: a migration is loaded by path by its runner and must
    not depend on a workspace package being importable in order to run. A
    non-SQLite scheme is refused by name, because :func:`apply` cannot speak it
    and pretending otherwise would hide a misrouted URL behind a mysterious
    file.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError(
            f"unsupported DATABASE_URL scheme {parsed.scheme!r}: apply() opens "
            "sqlite:/// only; pass a DBAPI connection to upgrade() for another "
            "dialect"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ValueError(
            f"sqlite DATABASE_URL must not carry a host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path)
    if path.startswith("/"):
        path = path[1:]
    if not path:
        raise ValueError("sqlite DATABASE_URL carries no database path")
    return Path(path)


def connect(database_url: Optional[str] = None) -> sqlite3.Connection:
    """Open the SQLite store named by ``database_url`` (or ``DATABASE_URL``).

    Foreign keys are enabled, as in every other SQLite store in the workspace,
    so a caller reading back what this migration created sees the same
    constraint enforcement the rest of the spine sees.
    """
    url = database_url if database_url is not None else os.environ[DATABASE_URL_ENV]
    path = _sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def apply(database_url: Optional[str] = None) -> tuple[str, ...]:
    """Create the tables in a SQLite database; returns the statements executed.

    The standalone entry point: opens the database named by ``database_url`` (or
    ``DATABASE_URL``) and commits the migration in one transaction, so a caller
    with no migration runner can still bring a database to this revision. Safe
    to call repeatedly and on a database whose stores already created the
    tables.
    """
    with closing(connect(database_url)) as connection, connection:
        return upgrade(connection)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """``python <this file> [upgrade|downgrade]`` against ``DATABASE_URL``.

    A runner's escape hatch, not a replacement for one: it exists so the
    statements in this file can be exercised against a real database without
    Alembic being installed, which is the state of this workspace today.
    """
    args = list(argv if argv is not None else ("upgrade",))
    action = args[0] if args else "upgrade"
    if action not in ("upgrade", "downgrade"):
        print(f"usage: {Path(__file__).name} [upgrade|downgrade]")
        return 2
    with closing(connect()) as connection, connection:
        executed = upgrade(connection) if action == "upgrade" else downgrade(connection)
    for statement in executed:
        print(" ".join(statement.split()).rstrip(";") + ";")
    return 0


if __name__ == "__main__":  # pragma: no cover - a runner's escape hatch
    raise SystemExit(_main())
