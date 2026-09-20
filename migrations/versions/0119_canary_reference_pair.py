"""The canary reference pair tables, in one versioned migration (feature 141).

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 141: *System
persists a frozen canary policy together with a frozen canary tree as the
determinism reference pair.*  docs/nullius-tech-architecture.md §12 closes its
determinism table with the nightly canary — *"replay a frozen policy*
``π_canary`` *over a frozen tree* ``T_canary`` *and assert the score matches a
recorded constant to* ``1e-12``" — and this migration creates the four tables
that hold that frozen pair so the nightly replay (feature 142) can read it back
and compare against it.

Four tables, one migration, joined by a shared ``reference_id``
---------------------------------------------------------------

They are the two ends of one act — ``canary_reference`` names the pair and
whether it is the active one, ``canary_reference_policy`` is the frozen policy
``π_canary``, ``canary_reference_tree`` is the frozen tree ``T_canary``'s
identity, and ``canary_reference_tree_node`` is the tree's nodes — and none is
meaningful without the others:

* ``canary_reference`` is the *join* — one row per frozen pair, carrying the
  ``recorded_score`` the nightly replay compares against (Nullable — a freshly
  frozen pair has not been replayed, so it has no constant yet, and feature
  143's ``1e-12`` comparison must stay distinguishable from "not yet replayed")
  and the ``is_active`` flag marking the one pair the nightly canary replays.
* ``canary_reference_policy`` is the *policy half* — its ``version`` (UNIQUE —
  two policies may not share one, or the store's own key would be unreadable,
  exactly as ``policy_revision.policy_version`` is), its canonical ``source``
  bytes and its ``code_hash``, the identity the nightly replay checks the
  replayed policy against.
* ``canary_reference_tree`` is the *tree half's identity* — its ``tree_hash``,
  the identity the nightly replay checks the replayed tree against, and the
  ``node_count`` (a convenience a human reads; the hash is the thing a replay
  keys on).
* ``canary_reference_tree_node`` is the *tree's nodes* — one row per node, keyed
  by ``(reference_id, node_id)``, carrying the parent, the depth and the
  canonical payload.  The tree hash is on the tree row, not the nodes: the hash
  is the identity of the whole tree, and a per-node column would repeat it on
  every row and could drift from it.

Why the policy and tree are separate tables, not columns on the join
--------------------------------------------------------------------

The same reason ``policy_revision`` and ``replay_score`` are separate from any
single row: each half is a thing in its own right, with its own identity (the
``code_hash``, the ``tree_hash``) that the nightly replay checks the replayed
bytes against, and a reader looking for *what the frozen policy is* or *what the
frozen tree is* must not have to know which columns of the join are whose.  The
join carries only what joins them — the active flag and the recorded score.

Dialect
-------

The repository runs SQLite on a single machine (the app spec's dev allowance,
and what ``tests/conftest.py`` points ``DATABASE_URL`` at) and Postgres 16 in
production (§9.1).  The spec's DDL is Postgres spelling, and the constructs that
do not survive the trip are the ones the rest of the tree already translates:

* ``DEFAULT gen_random_uuid()`` is a syntax error in SQLite; the ``reference_id``
  here is supplied by the store rather than defaulted, so this migration declares
  no defaulted UUID at all — the store mints the id, the same way
  :mod:`nulloracle.ksguard` and the rest of the spine do.
* ``JSONB`` is the spec's own spelling and stays on Postgres — the type that
  makes the policy ``source`` and the node ``payload`` addressable rather than an
  opaque string.  SQLite has no ``JSONB``: the declared type would fall through
  SQLite's affinity rules to NUMERIC — a lie about what the column holds — while
  ``TEXT`` is what SQLite's own JSON functions read and what the rest of the
  spine already does on SQLite.  ``source`` and ``payload`` are therefore ``TEXT``
  on SQLite and ``JSONB`` on Postgres — the same translate-what-the-dialect-lacks
  move the tree's dialect mechanism exists for.

``UUID``, ``TIMESTAMPTZ``, ``REAL``, ``TEXT``, ``CHAR(64)`` and ``BOOLEAN`` are
all accepted by SQLite as column types (it applies its own affinity), so the
column lists are otherwise identical between dialects and there is no second
schema to keep in step.

Every primary key is spelled ``NOT NULL PRIMARY KEY``
-----------------------------------------------------

``reference_id`` on every table is declared ``TEXT NOT NULL PRIMARY KEY``.  On
SQLite a bare ``PRIMARY KEY`` permits NULL, and because NULLs compare distinct
from one another it permits *several* NULL-keyed rows — a state these tables
exist to make impossible, since every row must be addressable by a real key
(``canary_reference`` is the identity of a frozen pair; the halves are keyed to
it).  A uniqueness guarantee that holds in production and silently lapses in the
database every test runs against is worse than either failure on its own.

``recorded_score`` is nullable
------------------------------

``recorded_score REAL`` carries no ``NOT NULL`` — a freshly frozen pair has not
been replayed, so it has no recorded constant yet, and a fabricated ``0.0`` would
read as a replay that never happened.  The column is the nightly replay's
constant (feature 142), and a constant that was never measured must stay
distinguishable from one that was.  This feature *freezes*; the next one *replays
and records*; and a store that also decided the comparison would be a threshold
nobody could audit.

``is_active`` defaults to FALSE
-------------------------------

For the same reason ``selected`` defaults to FALSE in ``0109`` and
``is_holdout`` in ``0109``: the flag is written by an insert that need not name
it, and the default keeps that insert a one-column-shorter statement.  Exactly
one pair is active at a time — the one the nightly canary replays — and the
default keeps an unflagged freeze from reading as active.

Idempotency and re-runnability
------------------------------

Every statement is ``IF NOT EXISTS`` and ``downgrade`` is ``DROP TABLE IF
EXISTS`` in reverse dependency order, so upgrade is re-runnable against a
database that already holds the tables, and a downgrade followed by an upgrade
round-trips to the same schema.  The store (:mod:`canary._reference_store`)
creates the same tables with the same ``IF NOT EXISTS`` on first use, so a
database this migration builds and one the store builds are the same database —
running the migration over a store-created database, or the store over a
migration-created one, changes nothing.

Revision identity
-----------------

This migration chains after ``0118_node_table`` under the repository's
convention — the id is ``<feature index, zero-padded to four>_<slug>`` and
``down_revision`` is the predecessor's id.  Feature 141 is this file's
predecessor's successor in the spec's own ordering: the node table (feature 97)
is the tree the discovery loop walks, and the canary tree (feature 141) is the
frozen tree the nightly replay replays — a different tree, but the one that
follows in the assembled chain.
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
    "REVISION",
    "TABLES",
    "apply",
    "connect",
    "downgrade",
    "statements",
    "upgrade",
]

# ── Version identity ─────────────────────────────────────────────────────────

#: This migration's revision id.  See the module docstring for the naming
#: convention — ``0119`` because it follows ``0118`` in the assembled chain.
REVISION = "0119_canary_reference_pair"

#: The revision this one chains after — feature 97's node table, the predecessor
#: in the chain.
DOWN_REVISION = "0118_node_table"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: The tables this migration creates, in creation order — the join first, then
#: the two halves, then the nodes, so a reader building the schema sees the
#: identity before what hangs off it.
TABLES = (
    "canary_reference",
    "canary_reference_policy",
    "canary_reference_tree",
    "canary_reference_tree_node",
)

#: This migration creates no indexes.  Every table is keyed by its ``reference_id``
#: primary key (and ``canary_reference_policy.version`` is UNIQUE, which carries
#: its own implicit index); a query plan for readers that do not exist yet is the
#: wrong thing for a migration to invent.
INDEXES = ()

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store, ledger).
DATABASE_URL_ENV = "DATABASE_URL"

# ── Dialect ──────────────────────────────────────────────────────────────────

#: The Postgres spelling of the frozen-bytes column type: the spec's own
#: ``JSONB``, the type that makes ``source`` and ``payload`` addressable rather
#: than an opaque string.
_POSTGRES_JSON_TYPE = "JSONB"

#: The SQLite equivalent: ``TEXT`` — what SQLite's own JSON functions read and
#: what the rest of the spine already does on SQLite.  SQLite has no ``JSONB``,
#: and the declared type would otherwise fall through affinity to NUMERIC, a lie
#: about what the column holds.
_SQLITE_JSON_TYPE = "TEXT"


def _json_type(dialect: str) -> str:
    """The frozen-bytes column type for ``dialect``.

    The only type construct that differs between dialects; see the module
    docstring.  An unknown dialect gets the Postgres spelling, which is the
    spec's — a caller running something else is off the documented path, and
    silently handing it a SQLite ``TEXT`` would hide that.
    """
    return _SQLITE_JSON_TYPE if dialect == "sqlite" else _POSTGRES_JSON_TYPE


def _dialect_of(connection: object) -> str:
    """Name the dialect of a DBAPI connection, conservatively.

    Only ``sqlite`` is recognised positively.  Everything else is reported as
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

    Every statement is idempotent.  Column lists, keys and constraints are the
    spec's, with the one dialect-only split (the frozen-bytes JSON type)
    translated.
    """
    json_type = _json_type(dialect)
    return (
        # Feature 141 / §12.  The join: one row per frozen reference pair.
        # `reference_id` is the pair's identity, the key the two halves hang off;
        # `recorded_score` is the constant the nightly replay (feature 142)
        # compares its score against — Nullable, so a freshly frozen pair that
        # has not been replayed stays distinguishable from a replayed one;
        # `is_active` marks the one pair the nightly canary replays.
        f"""
        CREATE TABLE IF NOT EXISTS canary_reference (
            reference_id   TEXT NOT NULL PRIMARY KEY,
            recorded_score REAL,
            is_active      BOOLEAN NOT NULL DEFAULT FALSE,
            created_at     TEXT NOT NULL
        )
        """,
        # Feature 141 / §12.  The policy half — the frozen ``π_canary``.
        # `version` is the policy's name (UNIQUE — two policies may not share
        # one, or the store's own key would be unreadable); `source` is the
        # canonical JSON bytes the policy froze to; `code_hash` is the sha256
        # over those bytes, the identity the nightly replay checks the replayed
        # policy against.
        f"""
        CREATE TABLE IF NOT EXISTS canary_reference_policy (
            reference_id TEXT NOT NULL PRIMARY KEY,
            version      TEXT NOT NULL UNIQUE,
            source       {json_type} NOT NULL,
            code_hash    CHAR(64) NOT NULL,
            created_at   TEXT NOT NULL
        )
        """,
        # Feature 141 / §12.  The tree half's identity — the frozen ``T_canary``.
        # `tree_hash` is the identity the nightly replay checks the replayed tree
        # against — sha256 over the sorted nodes, so a tree and the same tree
        # walked in another order are one hash; `node_count` is a convenience a
        # human reads.
        f"""
        CREATE TABLE IF NOT EXISTS canary_reference_tree (
            reference_id TEXT NOT NULL PRIMARY KEY,
            tree_hash    CHAR(64) NOT NULL,
            node_count   INT  NOT NULL,
            created_at   TEXT NOT NULL
        )
        """,
        # Feature 141 / §12.  The tree's nodes — one row per node, keyed by
        # (reference_id, node_id) so a re-freeze refreshes rather than appends.
        # `node_id` names the node; `parent_id` its parent (NULL for a root);
        # `depth` its level; `payload` the canonical JSON bytes the node froze to.
        f"""
        CREATE TABLE IF NOT EXISTS canary_reference_tree_node (
            reference_id TEXT NOT NULL,
            node_id      TEXT NOT NULL,
            parent_id    TEXT,
            depth        INT  NOT NULL,
            payload      {json_type} NOT NULL,
            PRIMARY KEY (reference_id, node_id)
        )
        """,
    )


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    Referencing tables are dropped before what they reference, so the sequence
    is valid on a dialect that checks a drop's dependents.  The nodes and halves
    hang off the join, so they are dropped before it.
    """
    drops = [f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)]
    drops += [f"DROP INDEX IF EXISTS {index}" for index in reversed(INDEXES)]
    return tuple(drops)


# ── Running it ───────────────────────────────────────────────────────────────


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Create the tables on ``connection``; returns the statements executed.

    Takes any DBAPI connection.  The caller owns the transaction — this
    function neither commits nor rolls back, so a caller that is already inside
    a transaction (a migration runner, a test) does not have its unit of work
    split by an implicit commit.  Use a context manager, or call
    :func:`apply`, which opens and commits its own SQLite connection.

    ``dialect`` overrides detection.  Detection exists so the common case needs
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

    Destructive by definition.  It is idempotent, and it drops only the objects
    this migration creates — a database downgraded here is refilled by the next
    freeze of each store, which creates its own tables idempotently.
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

    The same convention the rest of the spine uses, and deliberately re-stated
    rather than imported: a migration is loaded by path by its runner and must
    not depend on a workspace package being importable in order to run.  A
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
    with no migration runner can still bring a database to this revision.  Safe
    to call repeatedly and on a database whose stores already created the tables.
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
