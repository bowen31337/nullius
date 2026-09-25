"""Feature 332's DDL adapter: the migration owns the table, this member runs it.

The forward record's schema is **not authored here**.  ``forward_record`` is
declared by ``migrations/versions/0108_forward_and_universe_tables.py`` — the
file app_spec.xml's feature 108 gave all six of the outcome-end tables to —
and the ``node`` table its ``node_id`` references is declared by
``migrations/versions/0118_node_table.py``.  This module loads those two files
**by path**, calls their own ``statements("sqlite")``, and runs the tuples
whole.  Not one ``CREATE TABLE`` is spelled in this package, and the member's
suite asserts it: a store that hand-wrote its own DDL would be pinning its
behaviour against a schema the store made up, when the whole point is that
``0108``'s spelling is the one that counts.

**Why two owners and not one.**  SQLite does not resolve a foreign key's
*parent table* when the child is declared — it resolves it when a row is
**written** through the child table.  So a database holding ``forward_record``
but not ``node`` is created happily and then refuses every ``INSERT`` with
``no such table: main.node`` (verified against SQLite 3.45.1, the workspace's
own).  A bootstrap that created only its own table would therefore leave a
database on which *every* write fails, naming a table this member has no
business creating — which is the whole reason the set is two rather than one,
and the reason :data:`MIGRATION_ORDER` pairs each table name with the file
that owns it rather than listing bare revision strings.

**Order is the chain's, and not SQLite's demand.**  ``0118`` sorts before
``0108`` in the assembled chain, and this module runs it first for that reason
— the dependency is real even where the engine is tolerant, the point
``0108``'s own docstring makes when it says its ordering is *"a tolerance, not
a licence."*

**A different set from the sibling member's, deliberately.**  The promotion
member's ``promotion_registry`` write needs ``node``, ``epoch_ledger`` and
``promotion_registry``; this member's needs ``node`` and ``forward_record``.
``node`` appears in both because both acts genuinely reference it — a shared
*dependency*, stated in each member's own words, not a shared statement.  The
two sets are not merged into one wider list, for the reason
:mod:`promotion.schema` argues at length: the set a store runs should be the
set its own statements name, or a reader cannot tell a dependency from a habit.
Handing this member the promotion's three-table set would create
``epoch_ledger`` and ``promotion_registry`` — tables no statement of feature
332 names — on behalf of features whose writers are elsewhere.

**The migration's own comment is the reason the write is shaped as it is.**
``0108`` declares the three REAL columns nullable with this note: *"The three
REAL columns are nullable because a freshly promoted signal has no observation
yet — a NOT NULL here would force a fabricated zero on the day of promotion,
which would read as 'measured, and it was zero'."*  Feature 332's ``INSERT``
names three columns and this module runs the DDL that makes that insert
*sufficient* rather than merely legal.

**Stdlib only, and import-cheap.**  ``importlib.util``, ``pathlib``, ``sys``
and ``sqlite3``; no migration is imported at module scope, so the factory's
scan pays nothing for this module and composition reads no file.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

from .errors import FORWARD_RECORD_ERROR_CODE, ForwardStoreError

__all__ = [
    "FORWARD_RECORD_TABLE",
    "MIGRATION_ORDER",
    "bootstrap_schema",
    "migrations_dir",
]

#: The table feature 332's ``INSERT`` names, spelled once here as on
#: ``0108``'s side — the value both creators agree on.  Read by
#: :mod:`forward.record` for its statements and its refusal messages, so the
#: one literal has one owner.
FORWARD_RECORD_TABLE = "forward_record"

#: The tables this member's one ``INSERT`` needs, paired with the migration
#: that owns each, in the order they must run.
#:
#: The *pair* is the point: a table name beside the file that owns it, so a
#: reader sees both that this module spells no column and which file to read to
#: learn one.  ``node`` first because the chain puts ``0118`` first and because
#: it is the parent the write resolves.
MIGRATION_ORDER: tuple[tuple[str, str], ...] = (
    ("node", "0118_node_table"),
    (FORWARD_RECORD_TABLE, "0108_forward_and_universe_tables"),
)


def migrations_dir() -> Path:
    """The directory the migration tree keeps its revisions in.

    Resolved from this file rather than from the process's working directory:
    a store is constructed from wherever the caller happens to run (a test's
    ``tmp_path``, an operator's shell), and a bootstrap that depended on the
    cwd would work in one of those and fail in the rest.
    ``packages/forward/src/forward/schema.py`` → ``parents[4]`` is the
    repository root, the same arithmetic every member's suite spells for its
    own tree.
    """
    return Path(__file__).resolve().parents[4] / "migrations" / "versions"


def _load_migration(revision: str) -> ModuleType:
    """Import one revision by file path, as its runner loads it.

    ``migrations/`` is not a package and is not on ``sys.path``, so a revision
    cannot be imported by name; a migration runner loads it by path and so does
    this.  The module is registered in ``sys.modules`` under a private name —
    what ``importlib`` expects of a caller building a spec by hand — which also
    makes the second and later reads of the same revision a dictionary lookup
    rather than a re-execution.

    A missing file is refused in this member's vocabulary rather than with a
    bare ``FileNotFoundError``: the repair is to a *checkout*, not to a
    statement, and a caller's ``except ForwardStoreError`` must not be defeated
    by a deployment that shipped the package without the migration tree.
    """
    path = migrations_dir() / f"{revision}.py"
    if not path.is_file():
        raise ForwardStoreError(
            f"{FORWARD_RECORD_ERROR_CODE}: the schema owned by "
            f"migrations/versions/{revision}.py is not at {path}. "
            f"{FORWARD_RECORD_TABLE} is created by "
            "``0108_forward_and_universe_tables.py`` (feature 108) and its "
            "parent ``node`` by ``0118_node_table.py``, and never by this "
            "member — so this deployment cannot bring a database to the "
            "revision a forward record needs. The repair is to the checkout: "
            "those files are the schema's owners, and inventing their DDL here "
            "would be this member legislating a table it does not own "
            "(feature 332)"
        )
    module_name = f"_forward_schema_{revision}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ForwardStoreError(
            f"{FORWARD_RECORD_ERROR_CODE}: migrations/versions/{revision}.py at "
            f"{path} could not be loaded as a module; without it there is no "
            f"statement this deployment may run to create "
            f"{FORWARD_RECORD_TABLE} (feature 332)"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _statements(dialect: str = "sqlite") -> tuple[str, ...]:
    """Every statement this member's two owners return for ``dialect``, in order.

    Each revision contributes **all** of its statements or none of them.
    ``0108`` creates five tables besides ``forward_record`` and ``0118``
    creates three besides ``node``; taking one statement out of a tuple would
    be this member editing another's schema, where running the tuple is what
    "the migration is the author" means.  Nothing is over-created by doing so:
    every statement is ``CREATE TABLE IF NOT EXISTS``, so a database that
    already holds them is left exactly as it was, and the tables this
    category's later features will need are already where their own writers
    expect them.
    """
    collected: list[str] = []
    for _table, revision in MIGRATION_ORDER:
        collected.extend(_load_migration(revision).statements(dialect))
    return tuple(collected)


def bootstrap_schema(
    connection: sqlite3.Connection, *, dialect: str = "sqlite"
) -> tuple[str, ...]:
    """Create the two tables a forward record needs; returns the DDL run.

    Takes a live connection rather than a URL, so the caller owns the
    transaction: the bootstrap and the ``INSERT`` that follows it can land in
    one unit of work, and a refused promotion cannot leave a database freshly
    populated with tables it did not fill.  The store opens its connections
    with ``PRAGMA foreign_keys = ON``, which is what makes the *set* of two
    mandatory — a ``forward_record`` without its parent node table is a
    database every write fails on — and the order is the chain's, as the module
    docstring argues.

    Idempotent by construction — every statement is ``IF NOT EXISTS`` — so
    calling it on a fully migrated database changes nothing.  That is the
    convergence the sibling member's bootstraps reach from the other direction:
    not *"the statements agree because both were written from the spec's
    columns"*, but *"there is only one set of statements, and this runs it."*
    """
    ddl = _statements(dialect)
    cursor = connection.cursor()
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl
