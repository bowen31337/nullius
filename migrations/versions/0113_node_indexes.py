"""The three ``node`` indexes the tree is walked, deduplicated and stratified by.

app_spec.xml feature 102: *"System creates an index on node campaign_id with
parent_id, plus an index on code_hash for deduplication and one on
agent_model_id."* One migration, three indexes, no table, and no constraint:
each is a plain ``CREATE INDEX``, because that is the statement the feature
names — see "Why none of the three is UNIQUE" below for what the spec's silence
on the word means.

Why the indexes are the feature and the table is not
----------------------------------------------------

Features 97-101 own the ``node`` *table*: 97 the key and the structural columns
(``parent_id``, ``campaign_id``, ``theme_root``, ``depth``), 98 the identity
trio (``code_hash``, ``stated_mechanism``, ``artifact_uri``), 99 the provenance
trio, 100 the authoring-model trio, 101 the seven metric columns. Those five run
in one queue by spec order and this feature in another, with no dependency edge
between them either way, so this file must not decide anything the table's owner
decides beyond the one exception below: it names the ``columns`` a database
engine needs indexed and leaves the columns' types, keys and constraints to the
migration that creates them.

**This file lands ahead of the table it indexes, by the dispatcher's own
ordering, and that makes it the first file in the assembled chain to touch
``node``.** The six migration tasks in this run were queued with descending
priorities — 107 down to 102 — and the run dispatches a queue in descending
priority order (the completed five started in exactly that order: 107, 106,
105, 104, 103, and this feature's 102). This feature is priority 101 and is
dispatched before the five column/table features, which carry 100 down to 96;
feature 97, the file that creates ``node``, is priority 96 and is dispatched
last of the six. So the assembled chain reads ``0113_node_indexes`` (this
file) → the four column features → ``0118_node_table``, and a straightforward
run of that chain against a *fresh* database used to stop here with
``no such table: node`` — a real bug (no revision may be renumbered to repair
it; see "The repair" below), not the dispatcher's fault to carry forever.

**The repair kept inside this file and 0118, rather than a renumbering**:
because this revision is the first one in the fixed chain order to reference
``node``, :func:`upgrade` creates the same five-column skeleton
:mod:`0118_node_table` creates — loaded from that very file by path (see
:func:`_node_table_statement`), so the two can never drift apart — before it
attempts the three indexes. On a fresh database this migration is now the one
that creates ``node``; on a database where the table already exists (0118
landed first in some other chain, or a store created it with its own
``CREATE TABLE IF NOT EXISTS``), the ``IF NOT EXISTS`` makes table creation a
silent no-op and only the indexes are new. 0118, reached later in the same
chain, then finds the table already there and is itself a no-op for the table
— see its docstring for that side of the repair.

The skeleton only carries ``campaign_id``, ``parent_id``, ``theme_root`` and
``depth``, so one of the three indexes — ``node_campaign_id_parent_id`` — can
always be created the moment the skeleton exists. The other two name columns
features 98 and 100 add later in this same chain (``code_hash`` at 0117,
``agent_model_id`` at 0115), so on a *fresh* chain this revision's own
:func:`upgrade` cannot yet create them: it catches exactly the
``OperationalError`` SQLite raises for a missing column, skips that one
statement, and lets 0118 finish the job once every node column has landed.
:func:`upgrade` is otherwise fully idempotent, so 0118 finishing the job is
nothing more than calling this same function again against a connection
where the remaining columns now exist — see 0118's docstring for the call. A
database where ``node`` already carried every column before 0113 ran (a store
that creates the fully-featured table directly, as production does) needs no
deferral: all three indexes succeed on this revision's own first call, and
0118's later retry finds nothing left to do.

That is also why :data:`TABLES` now names ``node`` alongside :data:`INDEXES`
being this file's own three: this migration creates the table when it is
absent, so its DDL, taken together with 0118's retry, is complete and correct
on a fresh run with no missing-table or missing-column failure surviving to
the caller. ``CREATE INDEX IF NOT EXISTS`` was always idempotent on both
dialects; the table statement borrows the same idempotent form from 0118, and
the column-missing skip is what makes the *order in which columns arrive*
survivable too.

Why these three, and what each one is for
-----------------------------------------

Each index serves a named reader rather than an imagined one — the rule 0108
states ("a migration is the wrong place to invent a query plan for readers that
do not exist yet") is what makes the *listing* the spec's and not this file's:
the three below are exactly the three feature 102 names, in the order it names
them, and no fourth index is added on this file's authority.

1. ``node_campaign_id_parent_id`` on ``(campaign_id, parent_id)``. The tree
   walk. A campaign is expanded node by node — feature 239 "expands a selected
   node by resuming its workspace" and feature 218 hands the policy the open
   frontier — so the query this serves is "the children of this parent within
   this campaign". ``campaign_id`` leading is load-bearing: a campaign's tree is
   the unit of work (feature 232 writes the campaign record "before any node is
   expanded"), every tree query in the system is already scoped to one campaign
   (feature 112's ``POST /target`` takes ``campaign_id`` alongside ``node_id``;
   feature 169 keys the artifact directory by ``campaign_id`` then ``node_id``),
   and the column order is the spec's and the architecture doc's own
   (§9.1: ``CREATE INDEX ON node (campaign_id, parent_id)``). The doc adds no
   parenthetical for this one, which is itself the argument that the order is
   the point rather than an accident of the column list.

2. ``node_code_hash`` on ``(code_hash)`` — a plain index, deliberately **not**
   ``UNIQUE``. Feature 102 calls it "an index on ``code_hash`` for
   deduplication", and the temptation is to read ``UNIQUE`` into that fourth
   word: ``code_hash`` is a content hash (feature 98's column, the pair feature
   15 keeps the ABI stamp beside), so two rows carrying the same one *are* the
   same node, and a unique index would move feature 179's "rejects an exact
   duplicate before it charges a trial" into the database rather than leaving it
   to whichever writer reads first. It is not what the spec asks for, and the
   spec is unusually clear on the point: its vocabulary for database-level
   enforcement is exact and it uses it three times in this same feature
   category — feature 97 says "a self-referencing ``parent_id`` **foreign
   key**", feature 103 says "a bigserial **primary key** and **role grants**",
   feature 105 says "with a **unique constraint** on ``epoch_id``". Feature 102
   says only "an index". The authors had the word and chose not to use it here.

   So the deduplication guarantee this index *serves* is feature 179's, checked
   by the writer before the trial is charged, and the index's job is to make
   that check cheap — which is exactly what an index is for. Making it unique
   would be this file legislating a constraint the table's own features would
   have to live with, and constraints are spelled where the column is: feature
   97's key and foreign key, 105's unique constraint on ``epoch_id`` and 0108's
   ``REFERENCES`` clauses are all written beside the column they constrain, in
   the migration that creates it. If a later feature genuinely needs
   unique-ness (feature 15's ABI stamp and the ``stated_mechanism`` review path
   both point at ``code_hash``, and the architecture doc annotates this same
   index ``-- dedup``), the honest form is a ``UNIQUE`` clause in the migration
   that *creates* the column (feature 97/98), not an out-of-band constraint
   arriving from a seventh revision.

   What is given up is real and worth naming: with a plain index, two writers
   racing feature 179's check can both pass it and both charge a trial, and only
   the application's reject-then-charge ordering stands between that and a
   double charge. That exposure is feature 179's to close — it is the feature
   that owns the check, and closing it there (a serialized probe, or a unique
   index requested by its own migration) keeps the constraint with the behaviour
   that depends on it. This file does not close it by inventing a constraint the
   spec withheld.

3. ``node_agent_model_id`` on ``agent_model_id``. The model stratum. Feature
   100 creates the column "so a pool can be stratified by authoring model",
   feature 203 records it per node "as a provider, model and version triple
   rather than a rolling alias", and the architecture doc's comment on this very
   index (``-- stratify the M3 paired test``) names the reader: a report that
   groups a pool of nodes by the model that authored them and compares the two
   strata. The index stops at the one column because that is what a grouping
   predicate reads — the hashes the report aggregates are not in its ``WHERE``.

Dialect
-------

The three index statements are dialect-invariant, as before: no ``id`` is
minted and no timestamp is defaulted by *them*, so there is no
``gen_random_uuid()`` and no ``NOW()`` to translate for ``CREATE INDEX IF NOT
EXISTS ... ON node (...)``. The node-table statement this file now also runs is
not — it carries the same ``id UUID ... DEFAULT`` 0118 needs, so it needs the
same per-dialect translation 0118 performs. Rather than a second copy of that
translation, :func:`_node_table_statement` reads it from 0118's own
:func:`statements`, so ``dialect`` here selects exactly what it selects there.
:func:`upgrade` resolves the dialect from the connection the same way 0118's
``_dialect_of`` does, loaded from 0118 alongside its statement.

The one platform fact worth restating: on SQLite a ``CREATE INDEX`` against a
missing table or a missing *column* is an error, not a silent no-op (verified —
``no such table`` / ``no such column``, both ``OperationalError``). The
node-table statement running first means the table is never missing when the
index statements run; a missing *column* still is, for two of the three
indexes, on a fresh chain — :func:`upgrade` catches exactly that error and
skips the one statement rather than letting it fail the whole revision; see
"The repair" above and 0118's docstring for who finishes the skipped index.

Revision chaining
-----------------

This file's spec feature index is 102, but its revision id is ``0113``: the
tree's convention (stated by 0108, reaffirmed by 0109-0112) pads the feature's
*position in the assembled chain*, not its spec index, because the spec's
feature order and the landing order have diverged — feature 104's campaign
landed as 0111 while feature 105's epoch_ledger landed as 0110. The chain this
file was written against is ``0107`` → ``0108`` → ``0109`` → ``0110`` →
``0111`` → ``0112_trial_ledger``, which is committed and is this branch's head;
``0113`` is the seventh position. :data:`DOWN_REVISION` names that head as a
fact read from ``git log`` rather than a convention guess. No revision id,
``DOWN_REVISION`` or filename in the tree changes for this fix — the ids are
chain positions, not a thing a bug fix gets to renumber — so the repair is
entirely inside this file's :func:`upgrade`.

:data:`REQUIRES_TABLES` is now empty rather than naming ``node``: this
migration no longer merely requires the table to pre-exist, it ensures it.
:data:`TABLES` names ``node`` for the same reason — this is, on a fresh
database, the file that creates it — alongside the three indexes it always
created.

Idempotency and re-runnability
------------------------------

Every statement is ``IF NOT EXISTS`` — the node-table ``CREATE TABLE`` borrowed
from 0118 and the three ``CREATE INDEX`` statements alike — so :func:`upgrade`
is a no-op against a database that already holds all four objects, including
one a shipped store or an earlier revision created first. Calling
:func:`upgrade` again when two of the three indexes were previously skipped
for a missing column (the fresh-chain case) is exactly how those two get
created once the columns exist: nothing about a second call is special-cased,
it is the same statement list meeting a database that has moved on.
:func:`downgrade` is unchanged: it drops only the three indexes this migration
has always owned, in reverse creation order, and never touches the ``node``
table or a row of it — the table this revision may have created is 0118's to
drop on its own downgrade, the same table either file leaves behind. An
upgrade→downgrade→upgrade cycle round-trips for the indexes; ``node`` persists
throughout, as it does across a downgrade of 0118 followed by a re-upgrade of
this file alone.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from collections.abc import Iterable
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Optional
from urllib.parse import unquote, urlparse

__all__ = [
    "DATABASE_URL_ENV",
    "DOWN_REVISION",
    "INDEXES",
    "INDEX_COLUMNS",
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
#: assembled chain (seventh), not its spec feature index (102) — see the module
#: docstring for the convention and why the chain position wins.
REVISION = "0113_node_indexes"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0112 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0112_trial_ledger"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: Tables that must already exist for this migration to be valid — none.
#: This migration used to require ``node`` to pre-exist; it now ensures the
#: table itself (see :func:`_node_table_statement`), so nothing else in the
#: chain needs to land first.
REQUIRES_TABLES: tuple[str, ...] = ()

#: The tables this migration creates, in creation order — ``node`` when this
#: is the first revision in the chain to touch it (the fresh-database case),
#: alongside the three indexes it has always created. The ``CREATE TABLE IF
#: NOT EXISTS`` is a no-op when the table already exists (0118 landed first,
#: or a store created it); see the module docstring's repair section.
TABLES: tuple[str, ...] = ("node",)

#: The indexes this migration creates, in creation order — exactly the three
#: feature 102 names, in the order it names them: the campaign tree walk, the
#: deduplication lookup, the model stratum. No fourth index is added on this
#: file's authority, and none of the three is ``UNIQUE``; see the module
#: docstring for what each one serves and why the spec's "an index" is taken at
#: its word.
INDEXES: tuple[str, ...] = (
    "node_campaign_id_parent_id",
    "node_code_hash",
    "node_agent_model_id",
)

#: Which columns each index covers, keyed by the index name. This mapping — not
#: the DDL — is where the column lists live: :func:`_index_statement` renders
#: exactly these, so the three declarations below and the three statements
#: :func:`statements` returns cannot drift apart. It is separated from
#: :data:`INDEXES` so "does this migration index what feature 102 says it
#: indexes" is answerable by a reader or a test without parsing SQL.
INDEX_COLUMNS: dict[str, tuple[str, ...]] = {
    "node_campaign_id_parent_id": ("campaign_id", "parent_id"),
    "node_code_hash": ("code_hash",),
    "node_agent_model_id": ("agent_model_id",),
}

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── The statements ───────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _node_table_module() -> ModuleType:
    """Load ``0118_node_table.py`` from its file, not by package import.

    Loaded by path for the same reason every migration's own ``_sqlite_path``
    docstring gives: a migration must not depend on a workspace package being
    importable to run, and ``0118_node_table`` is not a valid dotted module
    name a plain ``import`` statement could spell anyway (it starts with a
    digit). ``lru_cache`` means the file is read and executed once per
    process rather than once per call to :func:`_node_table_statement` or
    :func:`upgrade`.
    """
    path = Path(__file__).with_name("0118_node_table.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node_table_statement(dialect: str) -> str:
    """The ``CREATE TABLE IF NOT EXISTS node (...)`` statement, from 0118.

    Read from 0118's own :func:`statements` rather than duplicated here, so
    the two migrations can never drift: whichever of them runs first against
    a given database creates exactly the same five-column skeleton, and the
    DDL identity the bug fix requires is structural rather than a copy a
    future edit to one file could silently break.
    """
    (statement,) = _node_table_module().statements(dialect)
    return statement


def _index_statement(name: str, columns: tuple[str, ...]) -> str:
    """The ``CREATE INDEX`` statement for ``name`` over ``columns``.

    The one statement form this migration emits, three times — kept as a
    function so the column lists (:data:`INDEX_COLUMNS`) are decided in exactly
    one place, and a fourth index, if the spec ever names one, cannot be added
    with its columns drifting from :data:`INDEXES`. Every index is plain: none
    is ``UNIQUE``, because the spec asks for three indexes and spells no
    constraint here (see the module docstring's second index). ``IF NOT EXISTS``
    makes it re-runnable on both dialects, which is why :func:`upgrade` needs no
    existence probe.
    """
    return (
        f"CREATE INDEX IF NOT EXISTS {name}\n"
        f"    ON node ({', '.join(columns)})"
    )


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    The first statement creates ``node`` if it is absent, identical to
    0118's own (:func:`_node_table_statement`) — this is the fix for the
    fresh-database bug this file's docstring describes: without it, the three
    ``CREATE INDEX`` statements below would run against a table that does not
    exist yet on a fresh chain. ``dialect`` selects the node-table statement's
    ``id`` default the same way it does in 0118; the three index statements
    remain dialect-invariant, as before. See the module docstring's Dialect
    section.

    Every statement is idempotent, but not every one is safe to run on a fresh
    chain the moment the table exists: ``node_code_hash`` and
    ``node_agent_model_id`` name columns features 98 and 100 add later in this
    same chain (0117 and 0115), so :func:`upgrade` tolerates the
    ``OperationalError`` SQLite raises for those two until a later call finds
    the columns present — see the module docstring's "Why these three" and
    "The repair" sections.
    """
    return (_node_table_statement(dialect),) + tuple(
        _index_statement(name, INDEX_COLUMNS[name]) for name in INDEXES
    )


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    Three index drops and nothing else: the ``node`` table and every row in it
    belong to the features that create and write it, and a downgrade of *this*
    revision must leave them exactly as it found them. ``DROP INDEX IF EXISTS``
    is idempotent on both dialects, so a database already downgraded is
    unchanged by a second run.
    """
    return tuple(f"DROP INDEX IF EXISTS {index}" for index in reversed(INDEXES))


# ── Running it ───────────────────────────────────────────────────────────────


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Create ``node`` (if absent) and whichever indexes it can; returns the
    statements actually run.

    Takes any DBAPI connection. The caller owns the transaction — this function
    neither commits nor rolls back, so a caller already inside a transaction (a
    migration runner, a test) does not have its unit of work split by an
    implicit commit. Use a context manager, or call :func:`apply`, which opens
    and commits its own SQLite connection.

    The three index statements are dialect-invariant, as before; the
    node-table statement is not (it carries 0118's ``id`` default), so unlike
    the previous, indexes-only version of this function, ``dialect`` is
    resolved from the connection — via 0118's own detection, loaded alongside
    its statement — when the caller does not supply one. A caller running
    something other than SQLite still gets the spec's Postgres spelling, the
    same conservative default 0118's own detection falls back to.

    Two of the three index statements name a column (``code_hash``,
    ``agent_model_id``) a later revision adds in a fresh chain; this function
    catches the ``OperationalError`` SQLite raises for exactly that case
    (``"no such column"`` — any other ``OperationalError`` propagates) and
    skips that one statement rather than failing the whole call. It is not
    special-cased for a second call: 0118 calling this same function again
    once every node column exists is how the skipped statements get created —
    see the module docstring's "The repair".
    """
    resolved = (
        dialect if dialect is not None else _node_table_module()._dialect_of(connection)
    )
    ddl = statements(resolved)
    cursor = connection.cursor()  # type: ignore[attr-defined]
    executed = []
    try:
        for statement in ddl:
            try:
                cursor.execute(statement)
            except sqlite3.OperationalError as exc:
                if "no such column" not in str(exc):
                    raise
                continue
            executed.append(statement)
    finally:
        cursor.close()
    return tuple(executed)


def downgrade(connection: object) -> tuple[str, ...]:
    """Drop the three indexes this migration created; returns the statements run.

    Destructive only to what this revision added. It is idempotent, it never
    drops the ``node`` table, and it never deletes a row — a database
    downgraded here keeps every node the system recorded and loses only the
    lookup structures, which the next :func:`upgrade` puts back.
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
    so a caller reading back what this migration indexed sees the same
    constraint enforcement the rest of the spine sees — including the
    self-referencing ``node.parent_id`` the tree walk this migration's first
    index serves is built on.
    """
    url = database_url if database_url is not None else os.environ[DATABASE_URL_ENV]
    path = _sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def apply(database_url: Optional[str] = None) -> tuple[str, ...]:
    """Create the indexes in a SQLite database; returns the statements executed.

    The standalone entry point: opens the database named by ``database_url`` (or
    ``DATABASE_URL``) and commits the migration in one transaction, so a caller
    with no migration runner can still bring a database to this revision. Safe
    to call repeatedly, and safe on a database whose stores already created the
    indexes — every statement is ``IF NOT EXISTS``.

    The ``node`` table must already exist: this migration creates no table, and
    SQLite refuses an index against a missing one by name rather than skipping
    it.
    """
    with closing(connect(database_url)) as connection, connection:
        return upgrade(connection)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """``python <this file> [upgrade|downgrade]`` against ``DATABASE_URL``.

    A runner's escape hatch, not a replacement for one: it exists so the
    statements in this file can be exercised against a real database without
    Alembic being installed, which is the state of this workspace today.

    ``argv`` reads the command line, and no argument means ``upgrade`` — the
    same spelling 0107, 0110 and 0112 use, and deliberately not 0108's and
    0109's, whose escape hatches ignore ``sys.argv`` and so make their own
    advertised ``[downgrade]`` word unreachable from the shell.
    """
    args = list(sys.argv[1:]) if argv is None else list(argv)
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
