"""The three ``node`` authoring-model columns, in one versioned migration (feature 100).

app_spec.xml feature 100: "System creates the agent_model_id, agent_ckpt_hash
and agent_sampling columns on the node table so a pool can be stratified by
authoring model." Three columns, one migration, and no table: this file adds
columns to a table a sibling feature (97) creates, so it is the smallest kind
of schema change — three ``ALTER TABLE ... ADD COLUMN`` statements and nothing
else. It is argued here as carefully as the table creators because this trio
carries the two questions the tree had met separately but never together: a
``NOT NULL`` constraint on an *added* column (0114's seven metrics are all
nullable, so its "default question" only had to be refused, never answered)
and a ``JSONB`` type on a dialect that has no such type.

Why the columns are the feature and the table is not
----------------------------------------------------

Feature 97 owns the ``node`` *table*: the key and the structural columns
(``parent_id``, ``campaign_id``, ``theme_root``, ``depth``), and by the spec's
schema block the identity, provenance and authoring-model triples and the
artifact URI as well. This feature owns only the authoring-model trio — 0113's
own name for these three — sitting in the middle of that block between feature
99's provenance triple and feature 98's ``artifact_uri``. Those two run in
separate queues by spec order, with no dependency edge between them either
way, so this file must not decide anything the table's owner decides: it names
the three columns a database engine must add and leaves the key, the foreign
keys and the physical ``CREATE TABLE`` to the migration that creates ``node``.
The types and constraints are the spec's own schema block, repeated verbatim
rather than re-derived, because they are the one thing the column's owner and
this file must agree on and the spec has already said them.

**This file lands ahead of the table it alters, on purpose and by the
dispatcher's own ordering** — the situation 0113 and 0114 document from inside
and this file inherits rather than re-argues. The run's ``node`` tasks are
dispatched in descending priority order with feature 97, the file that creates
``node``, last, so the assembled chain reads ``0113_node_indexes`` → the column
features → the table feature, and a straightforward run of that chain on a
*fresh* database stops at ``0113`` with ``no such table: node`` — the ordering
fact 0113's docstring names for whoever assembles the chain, and the reason
:data:`REQUIRES_TABLES` below says ``node``. This file adds one more member to
the column features between them and the table; once the table exists, running
this revision adds the three columns and touches nothing else, and every
statement is guarded by a column probe, so the repair is a re-run and not a
rebuild.

That is also why :data:`TABLES` is **empty** and :data:`REQUIRES_TABLES` is
``("node",)``. This migration creates no table, so a statement list that starts
with ``ALTER TABLE node`` is complete and correct on its own; the table it
alters either already exists (feature 97 landed first, or a store created it
with its own ``CREATE TABLE IF NOT EXISTS``) or the ``ALTER`` fails loudly
rather than silently altering nothing. The ``node`` dependency is the honest
statement of the ordering fact, recorded in the same constant 0108, 0113 and
0114 use for the tables they reference.

The stratification the trio exists for
--------------------------------------

"So a pool can be stratified by authoring model" is not decoration; it names
the reader. The architecture doc §14.1's provenance failure — DeepSeek retiring
``deepseek-v4-flash`` in September 2026 while continuing to accept the ID,
silently serving V4.1-Flash — is the case the trio exists to make visible:
``evaluator_hash``, ``snapshot_hash`` and ``cost_model_hash`` pin everything
except the thing that wrote the code, so a pool whose nodes were authored
under one model string by two different models is heterogeneous in an
uncontrolled variable, and that variable sits inside the M3 paired comparison.
§14.1's third mitigation says it plainly — "Record and stratify.
``agent_model_id`` is indexed for exactly this; report M3 results per model
stratum as well as pooled" — and the PRD's §5a: "Every node records
``agent_model_id``. Provider aliases re-route silently; a pinned snapshot or a
self-hosted checkpoint hash is the only real guarantee."

The index that stratification reads is 0113's ``node_agent_model_id``, already
landed — this file adds the column it indexes and no index of its own. A second
index on the same column would be this file legislating a query plan 0113
already declared, and the grouping predicate the stratification report runs
(``GROUP BY agent_model_id`` over a campaign's pool) is exactly what 0113's
index makes cheap; the hashes and scalars the report aggregates are not in its
``WHERE``.

The three columns, and what each one pins
-----------------------------------------

The trio is one record — the authoring provenance the PRD lists as a block
(model, checkpoint, sampling) — and each column pins one axis of *which model,
which weights, which dice*:

* ``agent_model_id TEXT NOT NULL`` — the model as a provider/model/version
  triple, "pinned, not a rolling alias" (feature 203's own words; §14.1's
  mitigation 2). NOT NULL because every node is authored by exactly one model:
  a node with no model string is a node the stratification cannot place, which
  is precisely why feature 358 rejects the merge "when a node record carries no
  ``agent_model_id`` value" — the write path refuses what the column cannot
  represent, and the column's constraint says the same thing ahead of the
  write.

* ``agent_ckpt_hash CHAR(64)`` — nullable, deliberately, and unlike 0114's
  NULLs this one is not an absence but a positive fact: "non-null for
  self-hosted weights" is the architecture doc's comment on this very line, so
  NULL records "hosted-API weights, no local checkpoint to hash" — §14.1's
  mitigation 1 (self-hosting the open weights that feed M3) is what makes the
  column ever non-trivially populated. The 64-hex shape is sha256, the same
  shape feature 98's ``code_hash`` and feature 99's provenance triple take.

* ``agent_sampling JSONB NOT NULL`` — temperature, top_p, thinking and seed,
  feature 204's own list. NOT NULL because the sampling parameters are known at
  authoring time even when they are defaults: there is no node whose dice are
  unknown, only unrecorded ones. The word that makes the constraint
  load-bearing is *seed* — a replay that re-issues the authoring call without
  these four cannot reproduce the node, and determinism under replay is the
  property §14 demands of every recorded decision.

The NOT NULL question, answered where it is true
------------------------------------------------

0114 answered the ``ADD COLUMN`` default question by refusing it: a measured
quantity has no honest default, so all seven metrics are nullable and the
question of *expressing* a constraint never arose. This trio faces it from the
other side — the spec's schema block spells ``NOT NULL`` on two of the three —
and the question is whether an added column may carry the constraint at all.

The verified answer is that both dialects agree on exactly where it may, and
the line is the honesty line. SQLite 3.45.1 — the workspace's own — refuses
``ADD COLUMN ... NOT NULL`` with "Cannot add a NOT NULL column with default
value NULL" when the table holds rows, and accepts it on an empty table;
Postgres behaves the same way for its own reasons ("column ... contains null
values" on a populated table, plain success on an empty one). A row that
predates the column has no recorded authoring model, and no default could
assert one truthfully — ``DEFAULT ''`` is not a model stratum, ``DEFAULT
'unknown'`` fabricates one, and an empty string is exactly what feature 358's
no-value check reads as absent — so the refusal is the correct failure and the
repair is a backfill, not a spell. The constraint is therefore emitted for
both dialects, with no fabricated default anywhere: it lands exactly where it
is true (an empty or freshly created table — which is every ``node`` this
chain can build today, since feature 97 has not landed and no shipped store
creates the table) and fails loudly where it would be false.

JSONB, and the one dialect split
--------------------------------

The one place the dialects genuinely differ is a type SQLite does not have.
``JSONB`` is the spec's own spelling and stays on Postgres — the type that
makes temperature, top_p, thinking and seed addressable keys rather than an
opaque string. SQLite has no ``JSONB``: the declared type would fall through
SQLite's affinity rules to NUMERIC — a lie about what the column holds — while
``TEXT`` is what SQLite's own JSON functions read and what the rest of the
spine already does on SQLite (0112 stores its ``TIMESTAMPTZ`` as ISO-8601
``TEXT`` "the way the rest of the spine stores its timestamps").
``agent_sampling`` is therefore ``TEXT`` on SQLite and ``JSONB`` on Postgres —
the same translate-what-the-dialect-lacks move the tree's dialect mechanism
exists for (``gen_random_uuid()`` → ``randomblob``, ``NOW()`` → ``strftime``,
``BIGSERIAL`` → ``AUTOINCREMENT``, roles → nothing) — and the only split this
file makes: the two ``NOT NULL`` constraints and ``CHAR(64)`` need no
translation, because ``CHAR(64)`` carries TEXT affinity on SQLite and the
constraint is spellable on both.

Why these three, in this order
------------------------------

The listing is the spec's and not this file's: the three below are exactly the
three feature 100 names, in the order the spec's schema block lists them, and
no fourth column is added on this file's authority. The order is the trio's
own logic — the model, then the weights, then the dice — and adding them in
the block's order keeps a brought-forward table's physical column order the
spec's declaration order, so a reader that names its columns explicitly cannot
drift from it.

Idempotency and re-runnability
------------------------------

Every statement is guarded by a column probe (:func:`statements` names the
columns; :func:`upgrade` emits an ``ALTER`` only for a column the table does
not already hold), so :func:`upgrade` is a no-op against a database that
already carries the trio — including a fresh database built by the assembled
chain in its repaired order, where feature 97's ``CREATE TABLE`` writes all
three with their constraints and this revision's probe finds nothing to do.
:func:`downgrade` drops exactly the three columns this migration names, in
reverse creation order, guarded by the same probe because ``DROP COLUMN`` has
no ``IF EXISTS`` spelling on either dialect (an unguarded second downgrade run
is the "no such column" ``OperationalError`` — verified), so a repeated
downgrade is a no-op. It never drops the ``node`` table and never deletes a
row: a database downgraded here keeps every node the system recorded and loses
only the authoring record, which the next :func:`upgrade` puts back — **on an
empty table**, where the round-trip is exact. On a table holding rows the
re-upgrade is refused, and the refusal is the same one and for the same reason
as a first add against a populated table: the downgrade destroyed the
authoring record, so every surviving row predates the columns again, and no
truthful default exists to put back what was destroyed (verified — SQLite's
"Cannot add a NOT NULL column with default value NULL"). A downgrade of this
revision is therefore a decision to lose the trio for the rows that carry it;
this file does not soften that, and Postgres would refuse the same re-add for
its own reasons. SQLite 3.35.0 and later support ``DROP COLUMN``; the
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
#: assembled chain (ninth), not its spec feature index (100) — see 0113's
#: module docstring for the convention and why the chain position wins. The
#: chain this file was written against is ``0107`` → ``0108`` → ``0109`` →
#: ``0110`` → ``0111`` → ``0112`` → ``0113`` → ``0114``, which is committed
#: and is this branch's head; ``0115`` is the ninth position.
REVISION = "0115_agent_model_trio"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0114 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0114_node_metrics"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: The table this migration alters. Feature 97 owns it; this file adds the
#: authoring-model trio to it and nothing else. :data:`REQUIRES_TABLES` records
#: the dependency for a dialect that validates at DDL time and for whoever
#: assembles the chain — the table must exist before this revision runs, and on
#: both dialects an ``ALTER`` against a missing table fails loudly rather than
#: silently altering nothing.
NODE_TABLE = "node"

#: Tables that must already exist for this migration to be valid. ``node`` is
#: the one, and it is created by a sibling feature (97) this file does not own;
#: the constant is what makes that dependency legible to whoever assembles the
#: chain, exactly as 0108, 0113 and 0114 record the tables they reference.
REQUIRES_TABLES: tuple[str, ...] = (NODE_TABLE,)

#: The tables this migration creates — none. It alters a table a sibling
#: feature creates, and the constant is kept (rather than the attribute being
#: omitted) so ``TABLES + COLUMNS`` stays the uniform shape a reader can
#: iterate over every migration in this tree.
TABLES: tuple[str, ...] = ()

#: The columns this migration adds to ``node``, in creation order — exactly the
#: three feature 100 names, in the order the spec's schema block lists them. No
#: fourth column is added on this file's authority; see the module docstring
#: for what each of the three pins.
COLUMNS: tuple[str, ...] = (
    "agent_model_id",
    "agent_ckpt_hash",
    "agent_sampling",
)

#: The type each column carries on each dialect, as ``(postgres, sqlite)``. The
#: Postgres member is the spec's own schema-block type, verbatim; the SQLite
#: member differs only where SQLite lacks the type, which is the one column
#: this tree has met so far where that is true — ``JSONB`` (see the module
#: docstring's dialect section). This mapping — not the DDL — is where the
#: types live, so "does this migration add the columns in the spec's types" is
#: answerable by a reader or a test without parsing SQL.
COLUMN_TYPES: dict[str, tuple[str, str]] = {
    "agent_model_id": ("TEXT", "TEXT"),
    "agent_ckpt_hash": ("CHAR(64)", "CHAR(64)"),
    "agent_sampling": ("JSONB", "TEXT"),
}

#: The columns the spec's schema block spells ``NOT NULL`` — the two facts
#: known at authoring time (the model, the dice), against the one whose NULL
#: is itself a recorded fact (hosted-API weights). Named as data, separately
#: from the DDL, because the constraint is a fact of the spec that feature
#: 358's write-path check keys on too; an ``ALTER`` against a *populated*
#: table fails on both dialects rather than filling the rows with a lie, and
#: that failure is the correct one (see the module docstring's NOT NULL
#: section).
NOT_NULL_COLUMNS: tuple[str, ...] = ("agent_model_id", "agent_sampling")

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── Dialect ──────────────────────────────────────────────────────────────────


def _dialect_of(connection: object) -> str:
    """Name the dialect of a DBAPI connection, conservatively.

    Only ``sqlite`` is recognised positively. Everything else is reported as
    ``other`` and receives the Postgres spelling — the spec's own — including
    the ``JSONB`` type and the ``NOT NULL`` constraints, because the production
    target is Postgres and an unrecognised driver is far likelier to share
    Postgres's types and its ``ADD COLUMN`` grammar than SQLite's, which has no
    ``JSONB`` and refuses the constraint on a populated table.
    """
    module = type(connection).__module__ or ""
    if module.split(".")[0] == "sqlite3":
        return "sqlite"
    return "other"


def _column_type(column: str, dialect: str) -> str:
    """The declared type :data:`COLUMN_TYPES` gives ``column`` on ``dialect``.

    The one place this migration's DDL differs between dialects: the Postgres
    member of the pair is the spec's own type, and the SQLite member replaces
    it only where SQLite lacks the type (``JSONB``). An unknown dialect gets
    the Postgres spelling, the spec's own; see :func:`_dialect_of` for why an
    unrecognised driver is treated as Postgres.
    """
    postgres_type, sqlite_type = COLUMN_TYPES[column]
    return sqlite_type if dialect == "sqlite" else postgres_type


# ── The statements ───────────────────────────────────────────────────────────


def _add_statement(column: str, dialect: str = "other") -> str:
    """The ``ALTER TABLE ... ADD COLUMN`` statement for ``column`` on ``dialect``.

    The one statement form this migration emits, three times — kept as a
    function so the type (:func:`_column_type`) and the constraint
    (:data:`NOT_NULL_COLUMNS`) are decided in exactly one place, and a fourth
    column, if the spec ever names one, cannot be added with its type or its
    constraint drifting from the data above. No ``DEFAULT`` appears anywhere:
    a default would have to be true of every row that predates the column, and
    no value is true of a row whose authoring model was never recorded — the
    refusal 0114's "default question" names, and the reason the ``NOT NULL``
    constraints are emitted bare for both dialects (spellable wherever they
    are true; see the module docstring).
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

    ``dialect`` selects exactly one thing here — the ``agent_sampling`` type
    (``JSONB`` on Postgres, the spec's own; ``TEXT`` on SQLite, which has no
    ``JSONB`` and whose JSON functions read ``TEXT``). Everything else is
    dialect-invariant: this migration mints no id, defaults no timestamp and
    grants no role, and the two ``NOT NULL`` constraints and ``CHAR(64)`` are
    spellable on both dialects alike.
    """
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
    revision must leave them exactly as it found them. The drops are reversed
    so a reader comparing the two lists sees one order in :func:`statements`
    and its mirror here, the way every other member of this tree is written.
    """
    return tuple(_drop_statement(column) for column in reversed(COLUMNS))


# ── Running it ───────────────────────────────────────────────────────────────


def _present_columns(connection: object) -> set[str]:
    """The set of column names ``node`` already carries on ``connection``.

    The probe :func:`upgrade` and :func:`downgrade` both use: a column already
    present is left untouched by the one and already gone for the other, so a
    re-run is a no-op in either direction rather than the duplicate ``ADD
    COLUMN`` or missing-column ``DROP COLUMN`` both dialects refuse (neither
    has an ``IF EXISTS`` spelling for columns). Reads columns through ``PRAGMA
    table_info`` — the same seam the write path's own legacy upgrade reads
    through — so the probe and the read agree on what the table holds.
    """
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")  # type: ignore[attr-defined]
    }


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Add the authoring-model trio to ``node`` on ``connection``.

    Returns the statements executed. Takes any DBAPI connection; the caller
    owns the transaction — this function neither commits nor rolls back, so a
    caller already inside a transaction (a migration runner, a test) does not
    have its unit of work split by an implicit commit. Use a context manager,
    or call :func:`apply`, which opens and commits its own SQLite connection.

    Only columns the table does not already hold are added: the probe
    (:func:`_present_columns`) makes this idempotent, so a database that
    already carries some or all of the trio — a brought-forward table written
    between this feature and feature 97, or a fresh database the repaired
    chain built with the columns already in its ``CREATE TABLE`` — is brought
    forward correctly rather than failing on a duplicate ``ADD COLUMN``.
    ``dialect`` overrides the detected dialect; see :func:`_dialect_of`.
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
    """Drop the authoring-model trio this migration added; returns them run.

    Destructive only to what this revision names. It never drops the ``node``
    table and never deletes a row — a database downgraded here keeps every node
    the system recorded and loses only the authoring record, which the next
    :func:`upgrade` puts back on an empty table; on a table holding rows the
    re-upgrade is the honest refusal, because the downgrade destroyed the
    record and no truthful default can restore it (see the module docstring's
    idempotency section). The columns are dropped in reverse creation order,
    and only the ones still present: ``DROP COLUMN`` has no ``IF EXISTS``
    spelling on either dialect, so the probe that makes :func:`upgrade`
    re-runnable makes the downgrade re-runnable too — a second run is a no-op,
    not the "no such column" refusal an unguarded drop list would raise.
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
    """Add the authoring-model trio to ``node`` in a SQLite database.

    The standalone entry point: opens the database named by ``database_url``
    (or ``DATABASE_URL``) and commits the migration in one transaction, so a
    caller with no migration runner can still bring a database to this
    revision. Safe to call repeatedly, and safe on a database whose stores
    created the columns — the column probe skips any column already present,
    so a second run is a no-op.

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
