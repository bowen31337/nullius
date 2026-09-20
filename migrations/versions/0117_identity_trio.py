"""The three ``node`` identity columns, in one versioned migration (feature 98).

app_spec.xml feature 98: *"System creates the code_hash, stated_mechanism and
artifact_uri columns on the node table in a versioned migration."* Three
columns, one migration, and no table: this file adds columns to a table a
sibling feature (97) creates, so it is the smallest kind of schema change —
three ``ALTER TABLE ... ADD COLUMN`` statements and nothing else. It is argued
here as carefully as the table creators anyway, because it is the migration
that carries the *first* copy of the identity triple and the artifact URI into
the tree, and because it is the first column migration in the tree to mix a
nullable column with two ``NOT NULL`` ones — the shape 0115 later meets from
the other side.

Why the columns are the feature and the table is not
----------------------------------------------------

Feature 97 owns the ``node`` *table*: the key and the structural columns
(``parent_id``, ``campaign_id``, ``theme_root``, ``depth``), and by the spec's
schema block the identity, provenance and authoring-model triples and the
artifact URI as well. This feature owns only the identity triple — the first
of that block, sitting ahead of feature 99's provenance triple and feature
100's authoring-model trio, with the artifact URI closing the block. Those run
in separate queues by spec order, with no dependency edge between them either
way, so this file must not decide anything the table's owner decides: it names
the three columns a database engine must add and leaves the key, the foreign
keys and the physical ``CREATE TABLE`` to the migration that creates ``node``.
The types and constraints are the spec's own schema block, repeated verbatim
rather than re-derived, because they are the one thing the column's owner and
this file must agree on and the spec has already said them.

**This file lands ahead of the table it alters, on purpose and by the
dispatcher's own ordering** — the situation 0113, 0114, 0115 and 0116 document
from inside and this file inherits rather than re-argues. The run's ``node``
tasks are dispatched in descending priority order with feature 97, the file
that creates ``node``, last, so the assembled chain reads ``0113_node_indexes``
→ the column features → the table feature, and a straightforward run of that
chain on a *fresh* database stops at ``0113`` with ``no such table: node`` —
the ordering fact 0113's docstring names for whoever assembles the chain, and
the reason :data:`REQUIRES_TABLES` below says ``node``. This file adds one more
member to the column features between them and the table; once the table
exists, running this revision adds the three columns and touches nothing else,
and every statement is guarded by a column probe, so the repair is a re-run and
not a rebuild.

That is also why :data:`TABLES` is **empty** and :data:`REQUIRES_TABLES` is
``("node",)``. This migration creates no table, so a statement list that starts
with ``ALTER TABLE node`` is complete and correct on its own; the table it
alters either already exists (feature 97 landed first, or a store created it
with its own ``CREATE TABLE IF NOT EXISTS``) or the ``ALTER`` fails loudly
rather than silently altering nothing. The ``node`` dependency is the honest
statement of the ordering fact, recorded in the same constant 0108, 0113, 0114,
0115 and 0116 use for the tables they reference.

The identity the trio exists for
--------------------------------

"So a pool can be stratified by authoring model" is feature 100's reader; this
trio's reader is *which node is which*. The three columns are the node's
identity as a piece of authored research — the code that was written, the
rationale the agent gave for it, and the artifact that lets the whole thing be
replayed — and each pins one axis of *what this node is*:

* ``code_hash CHAR(64) NOT NULL`` — feature 98's own column, the sha256 of the
  pure signal function (the PRD's ``construction.code``), and the one the
  identity triple hangs on. NOT NULL because every node *is* its code: a node
  with no code hash is not a node at all but an empty attempt, which is
  precisely why feature 356 rejects the merge "when a proposed node carries no
  ``code_hash``" — the write path refuses what the column cannot represent, and
  the column's constraint says the same thing ahead of the write. It is also
  the column 0113's ``node_code_hash`` index serves: feature 102's "index on
  ``code_hash`` for deduplication" is a *content* index, not a uniqueness one,
  because two distinct nodes may hash to the same code only by being the same
  code — the dedup gate (feature 101) refuses that pair before either charges a
  trial, so the index has no duplicate rows to find and needs no ``UNIQUE``.

* ``stated_mechanism TEXT`` — nullable, deliberately. The PRD's own words on
  this line — "agent's economic rationale; used for dedup and human review
  ONLY. Never scored" — are the whole of the column's meaning, and the NULL is
  a positive fact, not an absence: an agent that states no mechanism has left
  nothing to review, and a NULL records that rather than fabricating a rationale
  no one wrote. §9.1's annotation repeats the discipline — "dedup + human
  review ONLY, never scored" — which is why the column is nullable while the
  two beside it are not: the mechanism is the one member of the identity triple
  a node can truthfully lack, and a fabricated default would put words in the
  agent's mouth that no review could trust.

* ``artifact_uri TEXT NOT NULL`` — the pointer to the node's artifact
  directory, the full time series §9.2 stores so replay can recompute every
  scalar rather than trusting it. NOT NULL because the artifact is the last
  pipeline step (feature 96: "persist the full artifact to the artifact store
  plus the scalar metrics to the tree store as the final pipeline step"), and a
  node with no artifact URI is a node whose numbers cannot be re-derived — the
  exact failure §9.2 exists to prevent. The URI closes the identity block: the
  code that was written, the rationale the agent gave, and the artifact that
  lets the whole thing be replayed.

The NOT NULL question, answered where it is true
------------------------------------------------

0114 answered the ``ADD COLUMN`` default question by refusing it: a measured
quantity has no honest default, so all seven metrics are nullable and the
question of *expressing* a constraint never arose. This trio faces it from
both sides at once — the spec's schema block spells ``NOT NULL`` on two of the
three, while ``stated_mechanism`` is nullable by design — and the question is
whether an added column may carry the constraint at all.

The verified answer — the one 0115 settles for its own two-of-three trio, which
this file meets from the same side — is that both dialects agree on exactly
where the constraint may be added, and the line is the honesty line: SQLite
3.45.1 accepts ``ADD COLUMN ... NOT NULL`` without a ``DEFAULT`` on an *empty*
table and refuses it on a populated one ("Cannot add a NOT NULL column with
default value NULL"), and Postgres mirrors that behaviour for its own reasons
("column ... contains null values" on a populated table, plain success on an
empty one). A row that predates these columns has no recorded identity, and no
default could assert one truthfully — a fabricated ``DEFAULT`` would have to
name a code hash, an artifact URI no feature ever computed for that row — which
is precisely the error direction this category exists to make impossible: a
node wearing identity that belongs to a different one. ``NULL`` is not
available for the two either, because the spec's own schema block spells them
``NOT NULL`` and feature 356's completeness gate rejects the merge "when a
proposed node carries no ``code_hash``"; a nullable column would let an
identity-less node be written and only refuse it later at the merge gate. So
the two constraints are emitted bare for both dialects, with no ``DEFAULT``
anywhere, and ``stated_mechanism`` is emitted bare-nullable: the ``ALTER``
lands exactly where it is true — an empty or freshly created table, which is
every ``node`` this chain can build today, since feature 97 has not landed and
no shipped store creates the table — and fails loudly where it would be false.
The repair for a populated database is a backfill, not a spell.

Dialect, and the one type that needed no translation
----------------------------------------------------

None needed. This is the fifth dialect-invariant column migration in the tree
after 0110, 0113, 0114 and 0116, and the one that carries a nullable column
alongside two constrained ones without a type split: every column here is
either ``CHAR(64)`` — which carries TEXT affinity on SQLite and is a
fixed-width character type on Postgres — or ``TEXT``, and neither needs
translation. No id is minted and no timestamp is defaulted, so there is no
``gen_random_uuid()`` and no ``NOW()`` to translate, and
``ALTER TABLE node ADD COLUMN <name> CHAR(64) NOT NULL`` /
``ALTER TABLE node ADD COLUMN <name> TEXT`` — the two statement forms here,
three times across the two types — are valid on SQLite 3.45.1 and on Postgres
alike. ``statements()`` therefore keeps the tree's uniform ``dialect``
parameter and selects nothing with it, as 0110's, 0113's, 0114's and 0116's do.
Unlike 0115, there is no ``JSONB`` to split: the one type the tree has met that
SQLite lacks is feature 100's ``agent_sampling``, which this feature does not
touch.

Why these three, in this order
------------------------------

The listing is the spec's and not this file's: the three below are exactly the
three feature 98 names, in the order the spec's schema block (§9.1 and the
``database_schema`` block alike) lists them, and no fourth column is added on
this file's authority. The order is the identity triple's own logic — the code
that was written, the rationale the agent gave, the artifact that lets it be
replayed — and adding them in the block's order keeps a brought-forward table's
physical column order the spec's declaration order, so a reader that names its
columns explicitly cannot drift from it. It also keeps this file's list in step
with §9.1's ``CREATE TABLE`` and with the schema block's own three terms, which
are validated in this same order.

No index is created here, and that is a decision rather than an omission.
Feature 102's three indexes (landed as 0113) are the spec's complete listing
for ``node`` and one of them — ``node_code_hash`` — covers this feature's
``code_hash``. That index is 0113's, not this file's: it was requested there by
feature 102 ("an index on ``code_hash`` for deduplication") and lands in the
migration that serves that reader, which is exactly the discipline the tree
holds to — a column feature adds the column and names the index it will be
read by, and the index feature creates the index. ``stated_mechanism`` and
``artifact_uri`` have no index and none is warranted: the mechanism is read for
human review, not queried, and the artifact URI is fetched by the node's key,
which the primary key already serves.

The constraint on the constraint
--------------------------------

Postgres refuses an ``ALTER TABLE`` whose ``NOT NULL`` is not honoured by the
existing rows, and it does so *inside the transaction*: a migration that adds
one column per statement leaves the database partly migrated when the second
statement fails. That is stated here rather than worked around, because the
workaround is the dishonest one: this file must not emit only the columns it
can prove a database can take, since which columns the spec's schema block
names is not a function of how full the table happens to be. A runner re-runs
the revision for the surviving columns — the probe makes each statement
independent — which is exactly the repair the ordering section above describes.

Idempotency and re-runnability
------------------------------

Every statement is guarded by a column probe (:func:`upgrade` emits an
``ALTER`` only for a column the table does not already hold), so :func:`upgrade`
is a no-op against a database that already carries the trio — including a fresh
database built by the assembled chain in its repaired order, where feature 97's
``CREATE TABLE`` writes all three with their constraints and this revision's
probe finds nothing to do. :func:`downgrade` drops exactly the three columns
this migration names, in reverse creation order, guarded by the same probe
because ``DROP COLUMN`` has no ``IF EXISTS`` spelling on either dialect (an
unguarded second downgrade run is the "no such column" ``OperationalError`` —
verified, and the defect 0114's unguarded downgrade carries). It never drops
the ``node`` table and never deletes a row: a database downgraded here keeps
every node the system recorded and loses only the identity triple and the
artifact pointer, which the next :func:`upgrade` puts back — **on an empty
table**, where the round-trip is exact (verified). On a table holding rows the
re-upgrade is refused, and the refusal is the same one and for the same reason
as a first add against a populated table: the downgrade destroyed the record,
so every surviving row predates the columns again, and no truthful default
exists to put back what was destroyed. A downgrade of this revision is
therefore a decision to lose the identity triple for every node that carries
it — the loss 0112's ledger would still be able to name for the code that was
run, since the charge row holds its own copy of the same hashes, and the one
reason that fact is worth writing down is that it makes the loss auditable
rather than silent. SQLite 3.35.0 and later support ``DROP COLUMN``; the
workspace's SQLite is newer, and a Postgres downgrade uses the same statement
form.
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
    "COLUMN_TYPES",
    "DATABASE_URL_ENV",
    "DOWN_REVISION",
    "NODE_TABLE",
    "NOT_NULL_COLUMNS",
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
#: assembled chain (eleventh), not its spec feature index (98) — see 0113's
#: module docstring for the convention and why the chain position wins. The
#: chain this file was written against is ``0107`` → ``0108`` → ``0109`` →
#: ``0110`` → ``0111`` → ``0112`` → ``0113`` → ``0114`` → ``0115`` →
#: ``0116``, which is committed and is this branch's head; ``0117`` is the
#: eleventh position.
REVISION = "0117_identity_trio"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0116 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0116_provenance_trio"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: The table this migration alters. Feature 97 owns it; this file adds the
#: identity triple and the artifact URI to it and nothing else.
#: :data:`REQUIRES_TABLES` records the dependency for a dialect that validates
#: at DDL time and for whoever assembles the chain — the table must exist before
#: this revision runs, and on both dialects an ``ALTER`` against a missing table
#: fails loudly rather than silently altering nothing.
NODE_TABLE = "node"

#: Tables that must already exist for this migration to be valid. ``node`` is
#: the one, and it is created by a sibling feature (97) this file does not own;
#: the constant is what makes that dependency legible to whoever assembles the
#: chain, exactly as 0108, 0113, 0114, 0115 and 0116 record the tables they
#: reference.
REQUIRES_TABLES: tuple[str, ...] = (NODE_TABLE,)

#: The tables this migration creates — none. It alters a table a sibling feature
#: creates, and the constant is kept (rather than the attribute being omitted) so
#: ``TABLES + COLUMNS`` stays the uniform shape a reader can iterate over every
#: migration in this tree.
TABLES: tuple[str, ...] = ()

#: The columns this migration adds to ``node``, in creation order — exactly the
#: three feature 98 names, in the order the spec's schema block lists them (and
#: the order §9.1's ``CREATE TABLE`` and the schema block list them too). No
#: fourth column is added on this file's authority; see the module docstring for
#: what each of the three pins.
COLUMNS: tuple[str, ...] = (
    "code_hash",
    "stated_mechanism",
    "artifact_uri",
)

#: The type each column carries on each dialect, as ``(postgres, sqlite)``. The
#: Postgres member is the spec's own schema-block type, verbatim; the SQLite
#: member is identical, because ``CHAR(64)`` carries TEXT affinity on SQLite and
#: ``TEXT`` is native to it — neither needs the translate-what-the-dialect-lacks
#: move the tree's dialect mechanism exists for. This mapping — not the DDL — is
#: where the types live, so "does this migration add the columns in the spec's
#: types" is answerable by a reader or a test without parsing SQL.
COLUMN_TYPES: dict[str, tuple[str, str]] = {
    "code_hash": ("CHAR(64)", "CHAR(64)"),
    "stated_mechanism": ("TEXT", "TEXT"),
    "artifact_uri": ("TEXT", "TEXT"),
}

#: The columns the spec's schema block spells ``NOT NULL`` — the two facts known
#: at authoring time and carried by every node (the code, the artifact), against
#: the one whose NULL is itself a recorded fact (an unstated mechanism). Named as
#: data, separately from the DDL, because the constraint is a fact of the spec
#: that feature 356's write-path check keys on too; an ``ALTER`` against a
#: *populated* table fails on both dialects rather than filling the rows with a
#: fabricated identity, and that failure is the correct one (see the module
#: docstring's NOT NULL section).
NOT_NULL_COLUMNS: tuple[str, ...] = (
    "code_hash",
    "artifact_uri",
)

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── Dialect ──────────────────────────────────────────────────────────────────


def _dialect_of(connection: object) -> str:
    """Name the dialect of a DBAPI connection, conservatively.

    Only ``sqlite`` is recognised positively. Everything else is reported as
    ``other`` and receives the Postgres spelling — the spec's own — including
    the ``CHAR(64)`` and ``TEXT`` types and the ``NOT NULL`` constraints,
    because the production target is Postgres and an unrecognised driver is far
    likelier to share Postgres's types and its ``ADD COLUMN`` grammar than
    SQLite's, which refuses the constraint on a populated table.
    """
    module = type(connection).__module__ or ""
    if module.split(".")[0] == "sqlite3":
        return "sqlite"
    return "other"


def _column_type(column: str, dialect: str) -> str:
    """The declared type :data:`COLUMN_TYPES` gives ``column`` on ``dialect``.

    Both members of every pair are identical here — this feature carries no type
    SQLite lacks — so the function is a projection of :data:`COLUMN_TYPES` and
    not a translation. An unknown dialect gets the Postgres spelling, the spec's
    own; see :func:`_dialect_of` for why an unrecognised driver is treated as
    Postgres.
    """
    postgres_type, sqlite_type = COLUMN_TYPES[column]
    return sqlite_type if dialect == "sqlite" else postgres_type


# ── The statements ───────────────────────────────────────────────────────────


def _add_statement(column: str, dialect: str = "other") -> str:
    """The ``ALTER TABLE ... ADD COLUMN`` statement for ``column`` on ``dialect``.

    The one statement form this migration emits, three times across two types —
    kept as a function so the type (:func:`_column_type`) and the constraint
    (:data:`NOT_NULL_COLUMNS`) are decided in exactly one place, and a fourth
    column, if the spec ever names one, cannot be added with its type or its
    constraint drifting from the data above. No ``DEFAULT`` appears anywhere:
    a default would have to be true of every row that predates the column, and
    no identity is true of a row whose code and artifact were never recorded —
    the fabrication the module docstring refuses, and the reason the ``NOT NULL``
    constraints are emitted bare for both dialects (spellable wherever they are
    true; see the module docstring).
    """
    definition = _column_type(column, dialect)
    if column in NOT_NULL_COLUMNS:
        definition += " NOT NULL"
    return f"ALTER TABLE {NODE_TABLE} ADD COLUMN {column} {definition}"


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    ``dialect`` is part of the tree's uniform interface and selects nothing:
    this migration mints no id, defaults no timestamp, grants no role and
    carries no ``JSONB``, and ``CHAR(64)`` and ``TEXT`` are spellable on both
    dialects alike.
    """
    _ = dialect  # accepted for the uniform interface; selects nothing today
    return tuple(_add_statement(column, dialect) for column in COLUMNS)


def _drop_statement(column: str) -> str:
    """The ``ALTER TABLE ... DROP COLUMN`` statement for ``column``.

    Dialect-invariant: ``DROP COLUMN`` is the same statement form on SQLite
    (3.35.0 and later) and Postgres. Unlike the index migrations' ``DROP INDEX
    IF EXISTS`` there is no ``IF EXISTS`` spelling for a column, which is why
    :func:`downgrade` guards these with the same probe :func:`upgrade` uses
    rather than running them blind.
    """
    return f"ALTER TABLE {NODE_TABLE} DROP COLUMN {column}"


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    Three column drops and nothing else: the ``node`` table and every row in it
    belong to the features that create and write it, and a downgrade of *this*
    revision must leave them exactly as it found them. The drops are reversed so
    a reader comparing the two lists sees one order in :func:`statements` and
    its mirror here, the way every other member of this tree is written.
    """
    return tuple(_drop_statement(column) for column in reversed(COLUMNS))


# ── Running it ───────────────────────────────────────────────────────────────


def _present_columns(connection: object) -> set[str]:
    """The set of column names ``node`` already carries on ``connection``.

    The probe :func:`upgrade` and :func:`downgrade` both use: a column already
    present is left untouched by the one and already gone for the other, so a
    re-run is a no-op in either direction rather than the duplicate ``ADD
    COLUMN`` or missing-column ``DROP COLUMN`` both dialects refuse (neither has
    an ``IF EXISTS`` spelling for columns). Reads columns through ``PRAGMA
    table_info`` — the same seam the write path's own legacy upgrade reads
    through — so the probe and the read agree on what the table holds.
    """
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")  # type: ignore[attr-defined]
    }


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Add the identity triple and artifact URI to ``node`` on ``connection``.

    Returns the statements executed. Takes any DBAPI connection; the caller owns
    the transaction — this function neither commits nor rolls back, so a caller
    already inside a transaction (a migration runner, a test) does not have its
    unit of work split by an implicit commit. Use a context manager, or call
    :func:`apply`, which opens and commits its own SQLite connection.

    Only columns the table does not already hold are added: the probe
    (:func:`_present_columns`) makes this idempotent, so a database that already
    carries some or all of the trio — a brought-forward table written between
    this feature and feature 97, or a fresh database the repaired chain built
    with the columns already in its ``CREATE TABLE`` — is brought forward
    correctly rather than failing on a duplicate ``ADD COLUMN``. ``dialect``
    overrides the detected dialect; see :func:`_dialect_of`.
    """
    resolved = dialect if dialect is not None else _dialect_of(connection)
    present = _present_columns(connection)
    ddl = tuple(
        _add_statement(column, resolved) for column in COLUMNS if column not in present
    )
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


def downgrade(connection: object) -> tuple[str, ...]:
    """Drop the identity triple this migration added; returns them run.

    Destructive only to what this revision names. It never drops the ``node``
    table and never deletes a row — a database downgraded here keeps every node
    the system recorded and loses only the identity triple and the artifact
    pointer, which the next :func:`upgrade` puts back on an empty table; on a
    table holding rows the re-upgrade is the honest refusal, because the
    downgrade destroyed the record and no truthful default can restore it (see
    the module docstring's idempotency section). The columns are dropped in
    reverse creation order, and only the ones still present: ``DROP COLUMN`` has
    no ``IF EXISTS`` spelling on either dialect, so the probe that makes
    :func:`upgrade` re-runnable makes the downgrade re-runnable too — a second
    run is a no-op, not the "no such column" refusal an unguarded drop list would
    raise.
    """
    present = _present_columns(connection)
    ddl = tuple(
        _drop_statement(column) for column in reversed(COLUMNS) if column in present
    )
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
    """Add the identity triple and artifact URI to ``node`` in a SQLite database.

    The standalone entry point: opens the database named by ``database_url`` (or
    ``DATABASE_URL``) and commits the migration in one transaction, so a caller
    with no migration runner can still bring a database to this revision. Safe
    to call repeatedly, and safe on a database whose stores created the columns
    — the column probe skips any column already present, so a second run is a
    no-op.

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
    from the shell — a defect 0114 does not repeat and neither does this one.
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
