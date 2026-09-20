"""The three ``node`` provenance columns, in one versioned migration (feature 99).

app_spec.xml feature 99: *"System creates the evaluator_hash, snapshot_hash and
cost_model_hash columns on the node table as the stored provenance triple."*
Three columns, one migration, and no table: this file adds columns to a table a
sibling feature (97) creates, so it is the smallest kind of schema change —
three ``ALTER TABLE ... ADD COLUMN`` statements and nothing else. It is argued
here as carefully as the table creators anyway, because it is the migration that
carries the *third* copy of the triple into the tree and the only one that must
not invent a single one of its values.

Why the columns are the feature and the table is not
----------------------------------------------------

Feature 97 owns the ``node`` *table*: the key and the structural columns
(``parent_id``, ``campaign_id``, ``theme_root``, ``depth``), and by the spec's
schema block the identity, provenance and authoring-model triples and the
artifact URI as well. This feature owns only the provenance triple — the middle
of that block, sitting between feature 98's ``stated_mechanism`` and feature
100's ``agent_model_id``. Those two run in separate queues by spec order, with
no dependency edge between them either way, so this file must not decide
anything the table's owner decides: it names the three columns a database
engine must add and leaves the key, the foreign keys and the physical ``CREATE
TABLE`` to the migration that creates ``node``. The types and constraints are
the spec's own schema block, repeated verbatim rather than re-derived, because
they are the one thing the column's owner and this file must agree on and the
spec has already said them.

**This file lands ahead of the table it alters, on purpose and by the
dispatcher's own ordering** — the situation 0113, 0114 and 0115 document from
inside and this file inherits rather than re-argues. The run's ``node`` tasks
are dispatched in descending priority order with feature 97, the file that
creates ``node``, last, so the assembled chain reads ``0113_node_indexes`` →
the column features → the table feature, and a straightforward run of that
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
statement of the ordering fact, recorded in the same constant 0108, 0113, 0114
and 0115 use for the tables they reference.

The triple, and what each hash names
------------------------------------

"This is the stored provenance triple" is not a label; it names the reader.
docs/nullius-tech-architecture.md §9.1 declares the same three columns on this
same table, in this same order, and the triple is *one fact stated twice*
across the spine: the node that was evaluated and the trial row that was
charged for it must be able to name the same three terms without drift. Feature
87 stamps the identical triple on every ``trial_ledger`` row (landed as 0112),
and ``ledger.provenance`` is the member that holds both copies to one shape —
its own words are the clearest statement of why the duplication is deliberate:
"the row that was charged and the node that was evaluated must be able to name
the same three terms without drift". Each column pins one axis of the
evaluation:

* ``evaluator_hash CHAR(64) NOT NULL`` — feature 70's sha256 over the container
  image digest plus the resolved configuration: *which frozen evaluator scored
  the node*. §14.1's infrastructure note states the discipline behind the
  column — docker containers, "digest-pinned, because ``evaluator_hash``
  requires digests not tags" — and feature 71's refusal to compare two scores
  whose evaluator hashes differ can only mean what it says when every stored
  score names its hash. A tag is a moving pointer; the hash is the only spelling
  of "this exact evaluator" the column can carry.

* ``snapshot_hash CHAR(64) NOT NULL`` — §4.2's
  ``sha256(sorted(file_hashes) + universe_definition + schema_version)``:
  *which sealed snapshot the node was scored against*. The seal computes it
  (§4.1), the point-in-time slice feature 72 serves is cut from the snapshot
  this hash names, and replay (§15) re-cuts it by the same name. §15.1's
  failure-mode table makes the stakes explicit — "snapshot extended → new
  ``snapshot_hash`` → tree *structure* survives; scores do not" — which is a
  rule a reader can only apply to a node that recorded its snapshot.

* ``cost_model_hash CHAR(64) NOT NULL`` — feature 60's sha256 over the loaded
  §6.2 cost-model document: *which fee-and-fill regime priced the node*.
  ``cost_model_hash`` is "part of every score's provenance triple" (§6.2), and
  the score a node carries is post-cost, so a node that could not name its cost
  model is a number nobody could recompute under the regime that produced it.

Why all three are NOT NULL, and why no default can exist
--------------------------------------------------------

The spec's schema block spells ``NOT NULL`` on all three, and unlike 0114's
seven metrics (measured quantities, all nullable, where the question of
*expressing* a constraint never arose) this trio faces the ``ADD COLUMN``
constraint question head-on. The verified answer — settled by 0115, which is
the file this one immediately follows — is that both dialects agree on exactly
where the constraint may be added, and the line is the honesty line: SQLite
3.45.1 accepts ``ADD COLUMN ... NOT NULL`` without a ``DEFAULT`` on an *empty*
table and refuses it on a populated one ("Cannot add a NOT NULL column with
default value NULL"), and Postgres mirrors that behaviour for its own reasons
("column ... contains null values" on a populated table, plain success on an
empty one).

A row that predates these columns has no recorded provenance, and no default
could assert one truthfully. A fabricated ``DEFAULT`` would have to name an
evaluator, a snapshot and a cost model — three hashes no feature ever computed
for that row — which is precisely the error direction this category exists to
make impossible: a score wearing provenance that belongs to a different
evaluation. ``NULL`` is not available either, because the spec's own sentence
is "the stored provenance triple" and feature 357 rejects the merge "when a
stored score lacks any member of the provenance triple"; a nullable column
would let a provenance-less node be written and only refuse it later at the
merge gate. So the constraints are emitted bare for both dialects, with no
``DEFAULT`` anywhere: the ``ALTER`` lands exactly where it is true — an empty
or freshly created table, which is every ``node`` this chain can build today,
since feature 97 has not landed and no shipped store creates the table — and
fails loudly where it would be false. The repair for a populated database is a
backfill, not a spell.

Why these three, in this order
------------------------------

The listing is the spec's and not this file's: the three below are exactly the
three feature 99 names, in the order the spec's schema block (§9.1 and the
``database_schema`` block alike) lists them, and no fourth column is added on
this file's authority. The order is the triple's own logic — the evaluator that
ran, the snapshot it sliced, the cost model that priced it — and adding them in
the block's order keeps a brought-forward table's physical column order the
spec's declaration order, so a reader that names its columns explicitly cannot
drift from it. It also keeps this file's list in step with 0112's
``trial_ledger`` triple and with ``ledger.provenance``'s own three terms, which
are validated in this same order.

No index is created here, and that is a decision rather than an omission.
Feature 102's three indexes (landed as 0113) are the spec's complete listing for
``node`` and none of them covers these columns; the readers this triple serves —
§14.1's provenance audit, feature 71's cross-hash refusal, feature 357's
completeness gate — read a node it has already located by key. A replay that
walks every node of a snapshot (``WHERE snapshot_hash = ?``) would scan today,
and if that reader is ever built, the index belongs to the migration that serves
it, requested there rather than pre-emptively legislated here.

The constraint on the constraint
--------------------------------

Postgres refuses an ``ALTER TABLE`` whose ``NOT NULL`` is not honoured by the
existing rows, and it does so *inside the transaction*: a migration that adds
one column per statement leaves the database partly migrated when the second
statement fails. That is stated here rather than worked around, because the
workaround is the dishonest one: this file must not emit only the columns it
can prove a database can take, since which columns the spec's schema block names
is not a function of how full the table happens to be. A runner re-runs the
revision for the surviving columns — the probe makes each statement independent
— which is exactly the repair the ordering section above describes.

Dialect, and the one type that needed no translation
----------------------------------------------------

None needed. This is the fourth dialect-invariant column migration in the tree
after 0110, 0113 and 0114, and the one that arrives at invariance from the
opposite direction to 0115: 0115 had to split ``agent_sampling`` because SQLite
has no ``JSONB``, while every column here is ``CHAR(64)`` — which carries TEXT
affinity on SQLite and is a fixed-width character type on Postgres — and the
``NOT NULL`` constraint is spellable on both. No id is minted and no timestamp
is defaulted, so there is no ``gen_random_uuid()`` and no ``NOW()`` to
translate, and ``ALTER TABLE node ADD COLUMN <name> CHAR(64) NOT NULL`` — the
one statement form here, three times — is valid on SQLite 3.45.1 and on
Postgres alike. ``statements()`` therefore keeps the tree's uniform ``dialect``
parameter and selects nothing with it, as 0110's, 0113's and 0114's do.

The shape the three columns carry is the hexdigest's own spelling, and the tree
already holds it to that: ``evaluator.normalize_evaluator_hash``,
``snapshot.normalize_snapshot_hash`` and
``ledger.provenance.validated_provenance_hash`` each fold case, strip
whitespace and refuse a short, non-hex or ``sha256:``-prefixed token. ``CHAR(64)``
records the width the digest has rather than enforcing anything — neither
dialect truncates or pads a ``CHAR`` on SQLite, and Postgres's padding applies
to comparison, not storage of a 64-character value — so the validation stays
where the writers are, which is where a caller with something to fix can be
told about it.

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
every node the system recorded and loses only the provenance, which the next
:func:`upgrade` puts back — **on an empty table**, where the round-trip is
exact (verified). On a table holding rows the re-upgrade is refused, and the
refusal is the same one and for the same reason as a first add against a
populated table: the downgrade destroyed the record, so every surviving row
predates the columns again, and no truthful default exists to put back what was
destroyed. A downgrade of this revision is therefore a decision to lose the
triple for every node that carries it — the loss 0112's ledger would still be
able to name, since the charge row holds its own copy of the same three hashes,
and the one reason that fact is worth writing down is that it makes the loss
auditable rather than silent. SQLite 3.35.0 and later support ``DROP COLUMN``;
the workspace's SQLite is newer, and a Postgres downgrade uses the same
statement form.
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
    "COLUMN_TYPE",
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
#: assembled chain (tenth), not its spec feature index (99) — see 0113's module
#: docstring for the convention and why the chain position wins. The chain this
#: file was written against is ``0107`` → ``0108`` → ``0109`` → ``0110`` →
#: ``0111`` → ``0112`` → ``0113`` → ``0114`` → ``0115``, which is committed and
#: is this branch's head; ``0116`` is the tenth position.
REVISION = "0116_provenance_trio"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0115 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0115_agent_model_trio"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: The table this migration alters. Feature 97 owns it; this file adds the
#: provenance triple to it and nothing else. :data:`REQUIRES_TABLES` records the
#: dependency for a dialect that validates at DDL time and for whoever assembles
#: the chain — the table must exist before this revision runs, and on both
#: dialects an ``ALTER`` against a missing table fails loudly rather than
#: silently altering nothing.
NODE_TABLE = "node"

#: Tables that must already exist for this migration to be valid. ``node`` is
#: the one, and it is created by a sibling feature (97) this file does not own;
#: the constant is what makes that dependency legible to whoever assembles the
#: chain, exactly as 0108, 0113, 0114 and 0115 record the tables they reference.
REQUIRES_TABLES: tuple[str, ...] = (NODE_TABLE,)

#: The tables this migration creates — none. It alters a table a sibling feature
#: creates, and the constant is kept (rather than the attribute being omitted) so
#: ``TABLES + COLUMNS`` stays the uniform shape a reader can iterate over every
#: migration in this tree.
TABLES: tuple[str, ...] = ()

#: The columns this migration adds to ``node``, in creation order — exactly the
#: three feature 99 names, in the order the spec's schema block lists them (and
#: the order §9.1 and 0112's ``trial_ledger`` block list them too). No fourth
#: column is added on this file's authority; see the module docstring for what
#: each of the three names.
COLUMNS: tuple[str, ...] = (
    "evaluator_hash",
    "snapshot_hash",
    "cost_model_hash",
)

#: The type every one of the three carries — the spec's own ``CHAR(64)``, the
#: sha256 hexdigest's width, repeated verbatim rather than re-derived. It is the
#: one thing this file and the table's owner must agree on, and the one thing
#: that would silently drift if the triple were spelled three times by hand; a
#: single constant is why :func:`_add_statement` cannot emit a trio whose members
#: disagree. ``CHAR(64)`` needs no dialect translation (TEXT affinity on SQLite,
#: a fixed-width character type on Postgres) and neither does the constraint
#: below, which is the whole of this migration's dialect story.
COLUMN_TYPE = "CHAR(64)"

#: The columns the spec's schema block spells ``NOT NULL`` — all three, because
#: a score that cannot name its evaluator, its snapshot and its cost model is a
#: score no replay can reproduce. Named as data, separately from the DDL, because
#: the constraint is a fact of the spec that feature 357's completeness gate and
#: feature 71's cross-hash refusal key on too; an ``ALTER`` against a *populated*
#: table fails on both dialects rather than filling the rows with a fabricated
#: hash, and that failure is the correct one (see the module docstring).
NOT_NULL_COLUMNS: tuple[str, ...] = (
    "evaluator_hash",
    "snapshot_hash",
    "cost_model_hash",
)

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── The statements ───────────────────────────────────────────────────────────


def _add_statement(column: str) -> str:
    """The ``ALTER TABLE ... ADD COLUMN`` statement for ``column``.

    The one statement form this migration emits, three times — kept as a
    function so the type (:data:`COLUMN_TYPE`) and the constraint
    (:data:`NOT_NULL_COLUMNS`) are decided in exactly one place, and a fourth
    column, if the spec ever names one, cannot be added with its type or its
    constraint drifting from the data above. No ``DEFAULT`` appears anywhere:
    a default would have to be true of every row that predates the column, and
    no hash is true of a row whose provenance was never recorded — the
    fabrication the module docstring refuses, and the reason the ``NOT NULL``
    constraints are emitted bare for both dialects (spellable wherever they are
    true; see the module docstring).
    """
    definition = COLUMN_TYPE
    if column in NOT_NULL_COLUMNS:
        definition += " NOT NULL"
    return f"ALTER TABLE {NODE_TABLE} ADD COLUMN {column} {definition}"


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    ``dialect`` is part of the tree's uniform interface and selects nothing:
    this migration mints no id, defaults no timestamp and grants no role, and
    ``ALTER TABLE ... ADD COLUMN ... CHAR(64) NOT NULL`` is valid on SQLite
    3.45.1 and on Postgres alike — see the module docstring's dialect section
    for why this trio, unlike 0115's ``agent_sampling``, needs no translation.
    """
    _ = dialect  # accepted for the uniform interface; selects nothing today
    return tuple(_add_statement(column) for column in COLUMNS)


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
    """Add the provenance triple to ``node`` on ``connection``.

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
    correctly rather than failing on a duplicate ``ADD COLUMN``. ``dialect`` is
    accepted for the tree's uniform interface and selects nothing; see
    :func:`statements`.
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
    """Drop the provenance triple this migration added; returns them run.

    Destructive only to what this revision names. It never drops the ``node``
    table and never deletes a row — a database downgraded here keeps every node
    the system recorded and loses only the provenance, which the next
    :func:`upgrade` puts back on an empty table; on a table holding rows the
    re-upgrade is the honest refusal, because the downgrade destroyed the record
    and no truthful default can restore it (see the module docstring's
    idempotency section). The columns are dropped in reverse creation order, and
    only the ones still present: ``DROP COLUMN`` has no ``IF EXISTS`` spelling on
    either dialect, so the probe that makes :func:`upgrade` re-runnable makes the
    downgrade re-runnable too — a second run is a no-op, not the "no such column"
    refusal an unguarded drop list would raise.
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
    """Add the provenance triple to ``node`` in a SQLite database.

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
