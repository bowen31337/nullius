"""The four tables the pre-registration row leans on — created idempotently.

``migrations/versions/0108_forward_and_universe_tables.py`` (feature 108) is
``promotion_registry``'s schema owner, and ``0118``/``0110`` own the two tables
its ``REFERENCES`` clauses name.  Those files create their tables and nothing
else here does; this module is not a second schema.

**What it is instead.**  The pre-registration write (feature 291) is one
``INSERT INTO promotion_registry``, and that one statement cannot land on a
database that does not yet hold the table it names.  This workspace already
states the answer to that situation twice, and this module takes the second:

* the campaign store (:class:`discovery.campaign.CampaignRecords`) **refuses**
  to create its table, on the ground that the migration is the authority and a
  writer that invented one would be improvising a schema it does not own;
* the regime store (:class:`regime.coverage.RegimeCoverage`) creates its table
  idempotently, on the ground that ``0107``'s own downgrade docstring delegates
  the refill to it — *"refilled by the regime plugin's next persist, which
  creates the table idempotently"*.

``0107`` delegates in so many words; ``0108`` does not, and the difference is
not decoration.  But the structural fact this module answers to is different
from both: ``promotion_registry`` is **not** a table with a nullable
neighbourhood.  It carries two ``REFERENCES`` clauses — ``node(id)`` and
``epoch_ledger(epoch_id)`` — and a fully migrated deployment holds both.  A
writer that created only its own table would leave a database on which *every*
pre-registration fails with ``no such table: main.node``, naming a table this
member has no business creating.  So the bootstrap completes the **set**: the
three tables the one ``INSERT`` genuinely needs, in the migration tree's own
dependency order, and nothing more.

**Why that is not a schema this member invents.**  Not one statement here is
authored.  Every one comes from ``statements("sqlite")`` on a migration this
member does not own, loaded **in-function** and by file path — ``migrations/``
is not a package and a member never imports another member, but reading a
migration by path is exactly how a migration's own runner loads it, the
discipline ``packages/regime/tests/conftest.py`` states for ``0107``.  The
migration is the sole author of its spelling; this module is the plumbing that
runs it, so the two cannot drift — a change to those files changes this
bootstrap, because this bootstrap *is* those files.  The one thing this module
decides is the *order*, and the migrations decide that too: ``0118`` and
``0110`` declare no ``REQUIRES_TABLES`` because each stands alone, and
``0108``'s calls both of them its prerequisites.

**The dependency order is load-bearing, not tidy — and on SQLite the failure
comes one statement later than it looks.**  ``0108`` and ``0110`` both state
the rule, and they agree: Postgres validates a foreign key's parent *at*
``CREATE TABLE``, so on production ``promotion_registry`` must be declared after
the two tables it references; SQLite *does not resolve the parent until a row
is written*, so the three statements below would be accepted in any order
there.  ``0108``'s own words for that are the ones to keep: *"That is a
tolerance, not a licence: the dependency is real and is stated twice."*

So this module runs the three in the chain's order for the reason the chain
does — the dependency is real — and not because SQLite would refuse otherwise.
What SQLite would refuse, and this is the half that bites a store rather than a
migration, is the ``INSERT``: with ``PRAGMA foreign_keys = ON`` a database
holding ``promotion_registry`` but not ``node`` fails the first
pre-registration with ``no such table: main.node`` (verified against SQLite
3.45.1, the workspace's own).  A bootstrap that created only its own table
would therefore leave a database on which *every* write fails, naming a table
this member has no business creating — which is the whole reason the set is
three rather than one, and the reason the order is asserted in the member's
suite rather than left to look like a preference.

**On production the order is the *chain's* problem and not this module's.**
``0110`` records the consequence honestly: a Postgres run of the assembled
chain stops at ``0108``, before ``0110`` exists to satisfy it, which is exactly
the dependency ``0108`` declared in its ``REQUIRES_TABLES``.  This module is
SQLite — it speaks ``sqlite3`` — and it runs the three files' *sqlite*
statements, so it neither inherits nor worsens that: a Postgres deployment
brings its own chain, and reconciling it is the assembler's fix, as ``0110``
says.

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

from .errors import PromotionError

__all__ = [
    "MIGRATION_ORDER",
    "PROMOTION_REGISTRY_TABLE",
    "bootstrap_schema",
    "migrations_dir",
]

#: The table feature 291's ``INSERT`` names, spelled once here as on
#: ``0108``'s side — the value both creators agree on.
PROMOTION_REGISTRY_TABLE = "promotion_registry"

#: The tables ``promotion_registry``'s ``INSERT`` needs, and the migrations
#: that create them, in the order they must run.
#:
#: The pair is the point: a table name beside the file that owns it, so a
#: reader sees both that this module spells no column and which file to read
#: to learn one.
MIGRATION_ORDER: tuple[tuple[str, str], ...] = (
    ("node", "0118_node_table"),
    ("epoch_ledger", "0110_epoch_ledger"),
    (PROMOTION_REGISTRY_TABLE, "0108_forward_and_universe_tables"),
)


def migrations_dir() -> Path:
    """The directory the migration tree keeps its revisions in.

    Resolved from this file rather than from the process's working directory:
    a store is constructed from wherever the caller happens to run (a test's
    ``tmp_path``, an operator's shell), and a bootstrap that depended on the
    cwd would work in one of those and fail in the rest.
    ``packages/promotion/src/promotion/schema.py`` → ``parents[4]`` is the
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
    statement, and a caller's ``except PromotionError`` must not be defeated by
    a deployment that shipped the package without the migration tree.
    """
    path = migrations_dir() / f"{revision}.py"
    if not path.is_file():
        raise PromotionError(
            f"the schema owned by migrations/versions/{revision}.py is not at "
            f"{path}. {PROMOTION_REGISTRY_TABLE} is created by that file "
            "(feature 108) and never by this member, so this deployment cannot "
            "bring a database to the revision a pre-registration row needs. "
            "The repair is to the checkout: that file is the schema's owner, "
            "and inventing its DDL here would be this member legislating a "
            "table it does not own (feature 291)"
        )
    module_name = f"_promotion_schema_{revision}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise PromotionError(
            f"migrations/versions/{revision}.py at {path} could not be loaded "
            "as a module; without it there is no statement this deployment may "
            f"run to create {PROMOTION_REGISTRY_TABLE} (feature 291)"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _statements(dialect: str = "sqlite") -> tuple[str, ...]:
    """Every statement the three migrations return for ``dialect``, in order.

    Each revision contributes all of its statements or none of them.  ``0108``
    creates five tables besides ``promotion_registry``; taking that one
    statement out of the tuple would be this member editing another's schema,
    where running the tuple is what "the migration is the author" means.
    Nothing is over-created by doing so: every statement is ``IF NOT EXISTS``,
    so a database that already holds them is left exactly as it was, and the
    tables the other features of this domain will need — ``forward_record``
    among them — are already where their own writers expect them.
    """
    collected: list[str] = []
    for _table, revision in MIGRATION_ORDER:
        collected.extend(_load_migration(revision).statements(dialect))
    return tuple(collected)


def bootstrap_schema(
    connection: sqlite3.Connection, *, dialect: str = "sqlite"
) -> tuple[str, ...]:
    """Create the three tables a pre-registration row needs; returns the DDL run.

    Takes a live connection rather than a URL, so the caller owns the
    transaction: the bootstrap and the ``INSERT`` that follows it can land in
    one unit of work, and a refused pre-registration cannot leave a database
    freshly populated with tables it did not fill.  The store opens its
    connections with ``PRAGMA foreign_keys = ON``, which is what makes the
    *set* of three mandatory — a registry table without its two parents is a
    database every write fails on — and the order is the chain's, as the
    module docstring argues.

    Idempotent by construction — every statement is ``IF NOT EXISTS`` — so
    calling it on a fully migrated database changes nothing.  That is the
    convergence the earlier bootstraps reach from the other direction: not
    *"the statements agree because both were written from the spec's columns"*,
    but *"there is only one set of statements, and this runs it"*.
    """
    ddl = _statements(dialect)
    cursor = connection.cursor()
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl
