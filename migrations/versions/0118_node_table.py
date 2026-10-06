"""The ``node`` table, in one versioned migration (feature 97).

app_spec.xml feature 97: "System creates the node table with a primary key
``id``, a self-referencing ``parent_id`` foreign key, ``campaign_id``,
``theme_root`` and ``depth`` columns." One table, five columns, and the one the
whole discovery tree is built on: every node the system ever records is a row
here, and every node is a child of another node (or a root) by way of the
self-referencing ``parent_id``.

What the table is for
---------------------

A node is a single point in a campaign's discovery tree — one signal the
discovery loop proposed, evaluated and, if it survived, expanded. The tree is
the unit of work: a campaign is a tree of ``W`` wells (feature 104's
``workspace_count``), walked root to leaf, each node's children reached by
``parent_id``. The five columns feature 97 names are exactly the structural
skeleton that walk needs:

* ``id`` — the node's own identity, a minted UUID, separate from every other id
  in the tree. It is the value ``parent_id`` points at, the value feature 102's
  ``node_code_hash`` index and the write path's dedup gate key off, and the
  value ``node_id`` in every downstream request (feature 109's ``POST /target``,
  feature 396's ``POST /ledger/debit``) resolves back to this row.
* ``parent_id`` — the self-referencing foreign key to ``node(id)``. A root node
  carries ``NULL``; every other node names its parent. This is the edge the tree
  walk follows — feature 239 "expands a selected node by resuming its
  workspace", feature 218 hands the policy the open frontier — and the column
  feature 102 indexes beside ``campaign_id`` (``node_campaign_id_parent_id``) so
  "the children of this parent within this campaign" is a single indexed lookup.
  It is ``REFERENCES node(id)`` with no ``NOT NULL``: a root has no parent, and
  the self-reference is the one foreign key the spec spells on this table (the
  architecture doc §9.1 writes ``parent_id UUID REFERENCES node(id)`` verbatim).
* ``campaign_id`` — the campaign that spawned this node, a reference *to* the
  ``campaign`` row feature 104's migration (0111) creates. It scopes every tree
  query to one campaign (§9.1: "every tree query in the system is already scoped
  to one campaign"). It is ``NOT NULL`` — a node with no campaign is not a node
  the loop created — and deliberately carries **no** foreign key: the spec names
  a foreign key only for ``parent_id``, and feature 97's description lists
  ``campaign_id`` without one. The reference is enforced by the writer, not by a
  database constraint this feature was not asked to spell.
* ``theme_root`` — the research theme this node's root was planted in, the axis
  the overfit signature is measured against (§4.5, feature 801's ``meta()``
  returns it, feature 828 keys family-conditional thresholds on it). ``TEXT NOT
  NULL`` — every node belongs to a theme, and a node with no theme root is not a
  node the planner seeded.
* ``depth`` — how deep this node sits in its tree, zero at a root and
  incrementing down each branch. ``INT NOT NULL`` — the depth is fixed when the
  node is created (feature 474's Type-D flip is drawn against it, feature 732's
  depth-model context check reads it) and a node with no depth is not a node the
  walk placed.

Why these five, and no more
---------------------------

The listing is the spec's and not this file's: the five below are exactly the
five feature 97 names, in the order it names them, and no sixth column is added
on this file's authority. That restraint is load-bearing, because feature 97 is
the *table* owner and features 98–101 are the *column* owners, and the two run
in separate queues by spec order:

* feature 98 (0117) adds the identity triple — ``code_hash``,
  ``stated_mechanism``, ``artifact_uri``;
* feature 99 (0116) adds the provenance triple — ``evaluator_hash``,
  ``snapshot_hash``, ``cost_model_hash``;
* feature 100 (0115) adds the authoring-model trio — ``agent_model_id``,
  ``agent_ckpt_hash``, ``agent_sampling``;
* feature 101 (0114) adds the seven metrics — ``ic_mean`` through
  ``perturb_stability``.

This file owns none of those. It creates the table's skeleton — the key and the
four structural columns — and leaves every other column's type, key and
constraint to the migration that creates it. The types here are the
architecture doc §9.1's own (``UUID``, ``TEXT``, ``INT``), repeated verbatim
rather than re-derived, because the type is the one thing the table's owner and
the column owners must agree on and the doc has already said it.

``created_at`` is deliberately **absent**. The architecture doc §9.1 shows a
``created_at TIMESTAMPTZ NOT NULL`` on the fully assembled ``node`` table, but
feature 97's description names five columns and ``created_at`` is not among
them, and no feature 98–101 owns it either. A defaulted timestamp is a fact the
table could mint honestly (it is the one construct 0111 adds to ``campaign`` for
exactly that reason), but minting it here would be this file legislating a
column the spec withheld from feature 97's list; if the assembled table needs
``created_at``, the honest form is a feature that names it, not a sixth column
added on this file's authority. So this migration creates the five the feature
names and nothing else.

Why the table is the feature and the columns are not
----------------------------------------------------

This is the mirror image of 0114–0117. Those four each add columns to a table a
sibling feature creates; this file creates the table those four alter. Feature
97 owns the *table*: the key, the self-referencing foreign key and the four
structural columns. Those columns are the smallest kind of schema change to add
once the table exists, and this file leaves their types and constraints to the
migrations that create them — it names the five columns a database engine needs
in a ``node`` table and nothing a column owner decides. The one constraint this
file does decide — the self-referencing ``parent_id`` foreign key — is the one
the spec spells on the table itself ("a self-referencing ``parent_id`` foreign
key"), written beside the column it constrains, the way 0108's ``REFERENCES``
clauses and 0111's primary key are.

The ordering fact, stated plainly
---------------------------------

**This file lands *last* in the dispatched chain, after the column and index
migrations, by the dispatcher's own ordering.** The run's ``node`` tasks were
queued with descending priorities — feature 102 (the indexes) down to feature
97 (this table) — and the run dispatches a queue in descending priority order,
so feature 97, carrying the lowest priority, is dispatched last. The assembled
chain therefore reads ``0113_node_indexes`` → ``0114`` → ``0115`` → ``0116`` →
``0117`` → ``0118_node_table`` (this file), and a straightforward run of that
chain on a *fresh* database used to stop at ``0113`` with ``no such table:
node`` — a real bug, not a fact to defend, and not one any revision in this
tree may be renumbered to fix (the ids are chain positions).

**The fix is carried by 0113, not by reordering**: 0113's own :func:`upgrade`
now creates this table's skeleton the moment it is absent — the same
``CREATE TABLE IF NOT EXISTS`` below, read from this file by path rather than
duplicated, so the two definitions cannot drift apart (see 0113's module
docstring, "The repair"). By the time the chain reaches *this* file, ``node``
already exists on every path: 0113 created it on a fresh chain, or it was
already there (a store, or an older chain). Either way, the statement below is
a silent ``IF NOT EXISTS`` no-op here. What this file still does that is not a
no-op is call 0113's :func:`upgrade` a second time (:func:`_node_indexes_module`,
below) — 0113 could not create two of its three indexes at its own turn,
because ``code_hash`` and ``agent_model_id`` are added later in the chain
(0117 and 0115); by *this* file's turn every node column exists, so that
second call finishes them.

That is also why :data:`REQUIRES_TABLES` is **empty** and :data:`TABLES` is
``("node",)``. This migration creates the table; it references only itself (the
self-referencing ``parent_id``), so it imposes no ordering constraint on the
chain beyond its own creation — exactly as 0111's ``campaign`` references
nothing and is free to land in either order. :data:`INDEXES` stays empty too:
the three indexes remain 0113's own declared creations (:data:`INDEXES` there
is unchanged), and this file only finishes applying them, the way its
:func:`upgrade` would if 0113 were simply called twice by any other caller.

The self-referencing foreign key
--------------------------------

``parent_id UUID REFERENCES node(id)`` is the one foreign key on this table and
the one constraint feature 97 spells. It is written as a column constraint
beside ``parent_id``, the standard form both dialects accept inline, and it
points at the table being defined — a self-reference SQLite and Postgres both
permit in a ``CREATE TABLE`` (the referenced table is the one under creation, so
there is no forward-reference problem). Foreign keys are enabled on the SQLite
connection (:func:`connect` runs ``PRAGMA foreign_keys = ON``, as every store in
the spine does), so a caller writing a node whose ``parent_id`` names a
non-existent node sees the same constraint enforcement production does —
including the tree walk, which reaches a node's children by this very edge. A
root's ``parent_id`` is ``NULL`` and so is exempt: ``NULL`` never violates a
foreign key, which is why roots need no special casing.

Every primary key is spelled ``NOT NULL PRIMARY KEY``
-----------------------------------------------------

``node.id`` is declared by the spec as a bare ``UUID PRIMARY KEY`` (the
architecture doc §9.1: ``id UUID PRIMARY KEY``), and is written here with an
explicit ``NOT NULL``. That is a deliberate correction, not fussiness, and it is
the same one 0111 makes for ``campaign.id``: Postgres makes a primary key's
columns ``NOT NULL`` implicitly, but SQLite does **not** — on a rowid table a
bare ``PRIMARY KEY`` permits NULL, and because NULLs compare distinct it permits
*several* NULL-keyed rows. A second node row with a NULL id would split the
node's identity: the children referencing it by ``parent_id`` would be orphaned
from the row the discovery loop actually created, and the tree walk would follow
an edge to a node that was never placed. A uniqueness guarantee that holds in
production and silently lapses in the database every test runs against is worse
than either failure on its own. The ``id`` default never yields NULL, so nothing
that would have worked against a bare-key table is refused.

Dialect
-------

The repository runs SQLite on a single machine (the app spec's dev allowance,
and what ``tests/conftest.py`` points ``DATABASE_URL`` at) and Postgres 16 in
production (§9.1). One construct in the spec's DDL does not survive the trip to
SQLite's ``DEFAULT`` grammar:

* ``DEFAULT gen_random_uuid()`` is a syntax error in SQLite, whose grammar
  allows no function call in a ``DEFAULT`` clause unless it is parenthesised.

``UUID``, ``TEXT`` and ``INT`` are all accepted by SQLite as column types (it
applies its own affinity), so the column list is otherwise identical between
dialects and there is no second schema to keep in step. The one expression is
translated per dialect: the UUID default is an RFC 4122 version-4 UUID built
from ``randomblob`` (see :data:`_SQLITE_UUID_DEFAULT`), so an id minted by the
default is the same *kind* of value as ``gen_random_uuid()`` returns — the
variant and version nibbles are the ones a v4 UUID must carry rather than
whatever the random source produced. A caller that needs a specific id still
supplies one; the default exists so that ``INSERT ... (parent_id, campaign_id,
theme_root, depth)`` is a complete statement. There is no ``NOW()`` split,
because this table carries no defaulted timestamp — see "Why these five, and no
more" for why ``created_at`` is absent.

Idempotency and re-runnability
------------------------------

The statement is ``CREATE TABLE IF NOT EXISTS`` and ``downgrade`` is ``DROP
TABLE IF EXISTS``, so upgrade is re-runnable against a database that already
holds the table, and a downgrade followed by an upgrade round-trips to the same
schema. ``downgrade`` drops only this table — but note the ordering fact above:
in the dispatched chain the column migrations 0114–0117 run *before* this one,
so a downgrade that reaches this revision has already dropped nothing they
added (they are later in the chain and are not reversed here); the drop is the
table and its five columns, and the next :func:`upgrade` refills it. Nothing in
the shipped chain references ``node`` by a database foreign key (the
``parent_id`` self-reference is the only FK, and dropping the table removes it),
so the drop is never refused by a dependent.

The second call :func:`upgrade` makes, into 0113's own :func:`upgrade`, is
idempotent for the same reason 0113's module docstring gives: every statement
it runs is ``IF NOT EXISTS``, and the two index statements it could not run on
a fresh chain's first pass are not special-cased on this, later call — they
are the same statements, now finding their column present.

Revision chaining
-----------------

This file's spec feature index is 97, but its revision id is ``0118``: the
tree's convention (stated by 0108, reaffirmed by 0109–0117) pads the feature's
*position in the assembled chain*, not its spec feature index, because the
spec's feature order and the landing order have diverged — feature 97, the table
owner, is dispatched *last* of the ``node`` tasks, after the column features
98–101 and the index feature 102. This migration is the twelfth in the
assembled chain — ``0107`` → ``0108`` → ``0109`` → ``0110`` → ``0111`` →
``0112`` → ``0113`` → ``0114`` → ``0115`` → ``0116`` → ``0117`` → this one —
hence ``0118``.

:data:`DOWN_REVISION` names ``0117_identity_trio`` — the head this branch
actually holds, a committed file. The one string to reconcile if the chain is
ever renumbered (as the ordering fact above says it must be) is this constant.
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
#: assembled chain (twelfth), not its spec feature index (97) — see the module
#: docstring for the convention and why the chain position wins, and why this
#: table-owning feature lands last of the ``node`` tasks.
REVISION = "0118_node_table"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0117 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0117_identity_trio"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: Tables that must already exist for this migration to be valid. Empty: this
#: migration *creates* ``node`` and references only itself (the self-referencing
#: ``parent_id``), so it imposes no ordering constraint beyond its own creation
#: — the mirror of 0111's ``campaign``, which references nothing. The ``node``
#: that 0113–0117 name in their :data:`REQUIRES_TABLES` is this table.
REQUIRES_TABLES: tuple[str, ...] = ()

#: The tables this migration creates, in creation order. Just ``node`` — the
#: skeleton of the discovery tree: the minted-UUID key, the self-referencing
#: ``parent_id`` foreign key, and the four structural columns feature 97 names.
#: Every other ``node`` column is added by a sibling feature (98–101), not
#: created here; see the module docstring's "Why these five, and no more".
TABLES = ("node",)

#: The indexes this migration creates — none. Feature 102 owns ``node``'s three
#: indexes (landed as 0113): the campaign-tree-walk index on
#: ``(campaign_id, parent_id)``, the deduplication index on ``code_hash`` and
#: the model-stratum index on ``agent_model_id``. This file creates the table
#: only; the rule is the one 0108 states — a migration is the wrong place to
#: invent a query plan for readers that do not exist yet — and the readers here
#: are 0113's.
INDEXES: tuple[str, ...] = ()

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── Dialect ──────────────────────────────────────────────────────────────────

#: The Postgres default for an ``id`` column: the spec's own spelling, and the
#: reason a Postgres ``id`` needs no value supplied.
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

    The one dialect split this migration needs; see the module docstring. An
    unknown dialect gets the Postgres spelling, which is the spec's — a caller
    running something else is off the documented path, and silently handing it a
    SQLite expression would hide that.
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

    The column list, key and foreign key are the spec's (feature 97) and the
    architecture doc §9.1's, with the one dialect-only split (the UUID default)
    translated and the bare primary key tightened to ``NOT NULL``. The five
    columns are exactly the five feature 97 names, in the order it names them;
    no sixth column is added on this file's authority — see the module
    docstring's "Why these five, and no more" for why ``created_at`` is absent.
    """
    uuid_default = _uuid_default(dialect)
    return (
        # Feature 97. One row per node in a campaign's discovery tree. `id` is
        # the node's own minted-UUID identity, the value parent_id and every
        # downstream node_id resolve to. `parent_id` is the self-referencing
        # foreign key to node(id) — NULL for a root, the edge the tree walk
        # follows — and the only foreign key feature 97 spells. `campaign_id`
        # scopes every node to the campaign that spawned it (NOT NULL, no FK:
        # the spec names a foreign key only for parent_id). `theme_root` is the
        # research theme the node's root was planted in; `depth` is its depth in
        # the tree, zero at a root. `id` carries NOT NULL explicitly where the
        # spec's block writes a bare `UUID PRIMARY KEY`: on SQLite a bare key
        # accepts NULL and several of them, and a second NULL-id node row would
        # orphan the children referencing it. The other four columns — the
        # identity, provenance and authoring-model triples and the seven
        # metrics — are added by the sibling features 98–101, not created here.
        f"""
        CREATE TABLE IF NOT EXISTS node (
            id           UUID NOT NULL PRIMARY KEY DEFAULT {uuid_default},
            parent_id    UUID REFERENCES node(id),
            campaign_id  UUID NOT NULL,
            theme_root   TEXT NOT NULL,
            depth        INT  NOT NULL
        )
        """,
    )


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    One table and no indexes, so the sequence is a single statement; it is kept
    as a function rather than inlined so the shape matches the rest of the tree.
    """
    drops = [f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)]
    drops += [f"DROP INDEX IF EXISTS {index}" for index in reversed(INDEXES)]
    return tuple(drops)


# ── Running it ───────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _node_indexes_module() -> ModuleType:
    """Load ``0113_node_indexes.py`` from its file, not by package import.

    Loaded by path for the same reason :func:`_sqlite_path`'s docstring
    gives for this file: a migration must not depend on a workspace package
    being importable to run, and ``0113_node_indexes`` is not a name a plain
    ``import`` statement could spell anyway (it starts with a digit).
    """
    path = Path(__file__).with_name("0113_node_indexes.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Create the table on ``connection`` and finish 0113's indexes; returns
    every statement executed.

    Takes any DBAPI connection. The caller owns the transaction — this function
    neither commits nor rolls back, so a caller that is already inside a
    transaction (a migration runner, a test) does not have its unit of work
    split by an implicit commit. Use a context manager, or call
    :func:`apply`, which opens and commits its own SQLite connection.

    ``dialect`` overrides detection. Detection exists so the common case needs
    no argument; see :func:`_dialect_of` for what it recognises and why an
    unrecognised connection gets the spec's Postgres spelling.

    After the table statement, this also calls 0113's own :func:`upgrade`
    again (loaded by path, :func:`_node_indexes_module`). By this point in the
    chain every node column 0113's three indexes could need (97-101) has
    landed, so whichever of them 0113 could not yet create on a fresh chain —
    because its column had not been added at 0113's turn — succeeds now; any
    already created are a ``CREATE INDEX IF NOT EXISTS`` no-op. See
    0113_node_indexes's module docstring, "The repair", for the other half of
    this.
    """
    resolved = dialect if dialect is not None else _dialect_of(connection)
    ddl = statements(resolved)
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl + _node_indexes_module().upgrade(connection, resolved)


def downgrade(connection: object) -> tuple[str, ...]:
    """Drop the table this migration created; returns the statements executed.

    Destructive by definition. It is idempotent, and it drops only the object
    this migration creates — the ``node`` table and its five structural columns.
    The other ``node`` columns (the identity, provenance and authoring-model
    triples and the seven metrics) belong to the sibling features 98–101; see
    the module docstring's note on downgrade ordering in the dispatched chain.
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
    so a caller reading back what this migration created sees the same
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
    """Create the table in a SQLite database; returns the statements executed.

    The standalone entry point: opens the database named by ``database_url`` (or
    ``DATABASE_URL``) and commits the migration in one transaction, so a caller
    with no migration runner can still bring a database to this revision. Safe
    to call repeatedly and on a database whose stores already created the table.
    """
    with closing(connect(database_url)) as connection, connection:
        return upgrade(connection)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """``python <this file> [upgrade|downgrade]`` against ``DATABASE_URL``.

    A runner's escape hatch, not a replacement for one: it exists so the
    statements in this file can be exercised against a real database without
    Alembic being installed, which is the state of this workspace today.

    ``argv`` reads the command line, and no argument means ``upgrade``. Reading
    ``sys.argv`` is deliberate: 0108's and 0109's escape hatches ignore it,
    which makes those files' advertised ``[downgrade]`` word unreachable from
    the shell — a defect this file does not repeat.
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
