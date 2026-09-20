"""The seven ``node`` metric columns, in one versioned migration (feature 101).

app_spec.xml feature 101: "System creates the ic_mean, ic_tstat,
ir_standalone, ir_marginal, turnover, cost_adjusted_ir and perturb_stability
columns on the node table." Seven columns, one migration, and no table: this
file adds columns to a table a sibling feature (97) creates, so it is the
smallest kind of schema change — seven ``ALTER TABLE ... ADD COLUMN``
statements and nothing else — and it is argued here as carefully as the table
creators, because ``ADD COLUMN`` carries a default-value question the creators
never face and the columns' nullability is the whole contract.

Why the columns are the feature and the table is not
----------------------------------------------------

Feature 97 owns the ``node`` *table*: the key and the structural columns
(``parent_id``, ``campaign_id``, ``theme_root``, ``depth``), and by the spec's
schema block the identity, provenance and authoring-model triples and the
artifact URI as well. This feature owns only the seven metrics that sit at the
bottom of that block, in the order the block lists them. Those two run in
separate queues by spec order, with no dependency edge between them either way,
so this file must not decide anything the table's owner decides: it names the
seven columns a database engine must add and leaves their types, key and
constraints to the migration that creates ``node``. The types are the spec's
own (``REAL`` for every one of the seven) and this file repeats them verbatim
rather than re-deriving them, because the type is the one thing a column's
owner and this file must agree on and the spec has already said it.

**This file lands ahead of the table it alters, on purpose and by the
dispatcher's own ordering.** The six migration tasks in this run were queued
with descending priorities — 107 down to 101 — and the run dispatches a queue in
descending priority order; this feature's 101 is dispatched before feature 97,
the file that creates ``node``. So the assembled chain will read
``0113_node_indexes`` → the four column features → the table feature, and a
straightforward run of that chain on a *fresh* database stops at ``0113`` with
``no such table: node`` — the ordering fact 0113's docstring names for whoever
assembles the chain, and the reason :data:`REQUIRES_TABLES` below says ``node``.
Once the table exists, running this revision adds the seven columns and touches
nothing else; every statement is guarded by a column probe, so the repair is a
re-run and not a rebuild.

That is also why :data:`TABLES` is **empty** and :data:`REQUIRES_TABLES` is
``("node",)``. This migration creates no table, so a statement list that starts
with ``ALTER TABLE node`` is complete and correct on its own; the table it
alters either already exists (feature 97 landed first, or a store created it
with its own ``CREATE TABLE IF NOT EXISTS``) or the ``ALTER`` fails loudly
rather than silently altering nothing. The ``node`` dependency is the honest
statement of the ordering fact, recorded in the same constant 0108 and 0113 use
for the tables they reference.

The default question, and why the answer is NULL
------------------------------------------------

A ``CREATE TABLE`` column may carry whatever default the spec spells; an
``ALTER TABLE ... ADD COLUMN`` may not invent one, and this feature's seven
columns are the case where that constraint bites. SQLite refuses ``ADD COLUMN
... NOT NULL`` outright unless the column also carries a non-NULL ``DEFAULT``
— so the only two honest spellings are ``ADD COLUMN x REAL`` (nullable, no
default) or ``ADD COLUMN x REAL NOT NULL DEFAULT <v>`` (a default that must be
true of every row that predates the column). The second spelling would be a
fabrication: ``ic_mean``, ``ir_standalone``, ``turnover`` and their siblings are
*measured* quantities, computed by the discovery loop over a node's stored
series, and a node row that predates this column has no such measurement — no
value a default could assert would be true of it. A default of ``0`` would lie
("this candidate had zero information content"), and ``0`` is exactly the kind
of invented baseline the tree is written against. NULL is the only honest
statement a pre-metric row can make — *no metric was computed yet* — and it is
the spelling the read path already understands, since every metric column is
nullable in the spec's schema block and a reader that sees ``NULL`` reads "not
yet measured" rather than a number. So all seven are ``ADD COLUMN ... REAL``
with no default and no ``NOT NULL``: the honesty and the constraint agree, and
the nullable spelling is the only one SQLite's grammar permits here anyway.

Why these seven, in this order
------------------------------

Each column serves a named metric rather than an imagined one, and the listing
is the spec's and not this file's: the seven below are exactly the seven feature
101 names, in the order the spec's schema block lists them, and no eighth column
is added on this file's authority. They are the terminal block of the ``node``
schema — the metrics sit below the structural, identity, provenance and
authoring-model columns — and the order this file adds them in is the block's
own (``ic_mean``, ``ic_tstat``, ``ir_standalone``, ``ir_marginal``,
``turnover``, ``cost_adjusted_ir``, ``perturb_stability``), so a brought-forward
table's physical column order is the spec's declaration order and a reader that
names its columns explicitly cannot drift from it.

Idempotency and re-runnability
------------------------------

Every statement is guarded by a column probe (:func:`statements` emits an
``ALTER TABLE`` only for a column the table does not already hold), so
:func:`upgrade` is a no-op against a database that already carries the seven
columns — including a dev or test database a shipped store created them in
first. :func:`downgrade` drops exactly the columns this migration added, in
reverse creation order, and never drops the ``node`` table or deletes a single
row; a database downgraded here keeps every node the system recorded and loses
only the seven metrics, which the next :func:`upgrade` puts back. An
upgrade→downgrade→upgrade cycle round-trips. The drops are reversed so a reader
comparing the two lists sees one order in :func:`statements` and its mirror in
:func:`_drop_statements`, the way every other member of this tree is written.
SQLite 3.35.0 and later support ``DROP COLUMN``; the workspace's SQLite is
newer, and a Postgres downgrade uses the same statement form.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

__all__ = [
    "COLUMNS",
    "DATABASE_URL_ENV",
    "DOWN_REVISION",
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

#: This migration's revision id. The number is this file's position in the
#: assembled chain (eighth), not its spec feature index (101) — see 0113's
#: module docstring for the convention and why the chain position wins. The
#: chain this file was written against is ``0107`` → ``0108`` → ``0109`` →
#: ``0110`` → ``0111`` → ``0112`` → ``0113``, which is committed and is this
#: branch's head; ``0114`` is the eighth position.
REVISION = "0114_node_metrics"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0113 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0113_node_indexes"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: The table this migration alters. Feature 97 owns it; this file adds the
#: seven metric columns to it and nothing else. :data:`REQUIRES_TABLES` records
#: the dependency for a dialect that validates at DDL time and for whoever
#: assembles the chain — the table must exist before this revision runs, and on
#: both dialects an ``ALTER`` against a missing table fails loudly rather than
#: silently altering nothing.
NODE_TABLE = "node"

#: Tables that must already exist for this migration to be valid. ``node`` is
#: the one, and it is created by a sibling feature (97) this file does not own;
#: the constant is what makes that dependency legible to whoever assembles the
#: chain, exactly as 0108 and 0113 record the tables they reference.
REQUIRES_TABLES: tuple[str, ...] = (NODE_TABLE,)

#: The tables this migration creates — none. It alters a table a sibling feature
#: creates, and the constant is kept (rather than the attribute being omitted)
#: so ``TABLES + COLUMNS`` stays the uniform shape a reader can iterate over
#: every migration in this tree.
TABLES: tuple[str, ...] = ()

#: The columns this migration adds to ``node``, in creation order — exactly the
#: seven feature 101 names, in the order the spec's schema block lists them. No
#: eighth column is added on this file's authority, and every one is a bare
#: ``REAL`` (nullable, no default): see the module docstring's "The default
#: question" for why a measured quantity cannot carry an invented baseline.
COLUMNS: tuple[str, ...] = (
    "ic_mean",
    "ic_tstat",
    "ir_standalone",
    "ir_marginal",
    "turnover",
    "cost_adjusted_ir",
    "perturb_stability",
)

#: The column type every one of the seven carries — the spec's own ``REAL``,
#: repeated verbatim rather than re-derived, because it is the one thing this
#: file and the table's owner must agree on and the spec has already said it.
COLUMN_TYPE = "REAL"

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── The statements ───────────────────────────────────────────────────────────


def _add_statement(column: str) -> str:
    """The ``ALTER TABLE ... ADD COLUMN`` statement for ``column``.

    The one statement form this migration emits, seven times — kept as a
    function so the type (:data:`COLUMN_TYPE`) is decided in exactly one place,
    and a column's type cannot drift from the others. Every column is a bare
    ``REAL``: nullable with no default, because the metrics are measured and a
    pre-metric row has no honest value to assert, so NULL — the only value such
    a row can carry — is the spelling both the honesty and SQLite's ``ADD
    COLUMN`` grammar require (see the module docstring).
    """
    return (
        f"ALTER TABLE {NODE_TABLE} "
        f"ADD COLUMN {column} {COLUMN_TYPE}"
    )


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    ``dialect`` is part of the tree's uniform interface and selects nothing:
    this migration mints no id, defaults no timestamp and grants no role, so
    there is no ``gen_random_uuid()``, no ``NOW()`` and no Postgres-only branch
    to translate, and ``ALTER TABLE ... ADD COLUMN ... REAL`` is valid on SQLite
    and Postgres alike. See the module docstring's default question for why the
    columns carry no dialect-specific default.
    """
    _ = dialect  # accepted for the uniform interface; selects nothing today
    return tuple(_add_statement(column) for column in COLUMNS)


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    Seven column drops and nothing else: the ``node`` table and every row in it
    belong to the features that create and write it, and a downgrade of *this*
    revision must leave them exactly as it found them. The columns are dropped
    in reverse creation order so a reader comparing the two lists sees one order
    in :func:`statements` and its mirror here. ``DROP COLUMN`` is supported by
    the workspace's SQLite and by Postgres, so no dialect branch is needed.
    """
    return tuple(
        f"ALTER TABLE {NODE_TABLE} DROP COLUMN {column}"
        for column in reversed(COLUMNS)
    )


# ── Running it ───────────────────────────────────────────────────────────────


def _present_columns(connection: object) -> set[str]:
    """The set of column names ``node`` already carries on ``connection``.

    The probe :func:`upgrade` uses to decide which ``ALTER`` statements to run:
    a column already present is left untouched, so a database that already holds
    the seven metrics — a shipped store that created them first, or a prior run
    of this migration — is a no-op rather than a duplicate ``ADD COLUMN`` (which
    SQLite and Postgres both refuse). Reads columns through ``PRAGMA
    table_info`` — the same seam the write path's own legacy upgrade reads
    through — so the probe and the read agree on what the table holds.
    """
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")  # type: ignore[attr-defined]
    }


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Add the seven metric columns to ``node`` on ``connection``.

    Returns the statements executed. Takes any DBAPI connection; the caller
    owns the transaction — this function neither commits nor rolls back, so a
    caller already inside a transaction (a migration runner, a test) does not
    have its unit of work split by an implicit commit. Use a context manager, or
    call :func:`apply`, which opens and commits its own SQLite connection.

    Only columns the table does not already hold are added: the probe
    (:func:`_present_columns`) makes :func:`upgrade` idempotent, so a database
    that already carries some or all of the seven — a brought-forward table
    written between this feature and feature 97, or a store that created the
    metrics first — is brought forward correctly rather than failing on a
    duplicate ``ADD COLUMN``.
    """
    _ = dialect  # accepted for the uniform interface; dialect selects nothing
    present = _present_columns(connection)
    ddl = tuple(
        _add_statement(column) for column in COLUMNS if column not in present
    )
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


def downgrade(connection: object) -> tuple[str, ...]:
    """Drop the seven metric columns this migration added; returns them run.

    Destructive only to what this revision added. It is idempotent, it never
    drops the ``node`` table, and it never deletes a row — a database downgraded
    here keeps every node the system recorded and loses only the seven metrics,
    which the next :func:`upgrade` puts back. The columns are dropped in reverse
    creation order; see :func:`_drop_statements`.
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
    so a caller reading back what this migration altered sees the same
    constraint enforcement the rest of the spine sees — including the
    self-referencing ``node.parent_id`` the tree walk is built on.
    """
    url = database_url if database_url is not None else os.environ[DATABASE_URL_ENV]
    path = _sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def apply(database_url: Optional[str] = None) -> tuple[str, ...]:
    """Add the seven metric columns to ``node`` in a SQLite database.

    The standalone entry point: opens the database named by ``database_url`` (or
    ``DATABASE_URL``) and commits the migration in one transaction, so a caller
    with no migration runner can still bring a database to this revision. Safe
    to call repeatedly, and safe on a database whose stores already created the
    columns — the column probe skips any column already present, so a second run
    is a no-op.

    The ``node`` table must already exist: this migration creates no table, and
    SQLite refuses an ``ALTER`` against a missing one by name rather than
    skipping it.
    """
    with closing(connect(database_url)) as connection, connection:
        return upgrade(connection)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """``python <this file> [upgrade|downgrade]`` against ``DATABASE_URL``.

    A runner's escape hatch, not a replacement for one: it exists so the
    statements in this file can be exercised against a real database without
    Alembic being installed, which is the state of this workspace today.

    ``argv`` reads the command line, and no argument means ``upgrade``. Reading
    ``sys.argv`` is deliberate: the escape hatches of the earlier files ignore
    it, which makes those files' advertised ``[downgrade]`` word unreachable
    from the shell — a defect this file does not repeat.
    """
    args = list(sys.argv[1:]) if argv is None else list(argv)
    action = args[0] if args else "upgrade"
    if action not in ("upgrade", "downgrade"):
        raise ValueError(f"unknown action {action!r}: expected upgrade or downgrade")
    fn = upgrade if action == "upgrade" else downgrade
    with closing(connect()) as connection, connection:
        statements_run = fn(connection)
    for statement in statements_run:
        print(statement)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
