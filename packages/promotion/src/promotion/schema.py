"""The tables this member's statements lean on — created idempotently, per act.

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

**One set per act, and there are three of them.**  Feature 298's calibration
gate reads two tables — ``node`` and the ``campaign`` row its ``campaign_id``
names — so it needs a bootstrap of its own, for the same structural reason
from the other direction: this member's acts do not all lean on the same
tables, and a bootstrap is a claim about *what one act's statements name*.
:data:`MIGRATION_ORDER` therefore stays exactly what it always was — feature
291's three, and the member's suite pins it as that claim — and
:data:`CALIBRATION_MIGRATION_ORDER` is added beside it rather than widened
into it.  The alternative (one four-table set both callers run) would work,
since every statement is ``IF NOT EXISTS``, and is deliberately not taken: it
would make the pre-registration write create ``campaign`` for an ``INSERT``
that never reads it, and the calibration read create ``epoch_ledger`` and
``promotion_registry`` for two ``SELECT``s that never name them, so a reader
could no longer tell a dependency from a habit.

Feature 293's decision act takes the rule to its other end: its two
statements — the read and the one-column ``UPDATE`` — name
``promotion_registry`` and **nothing else**, so :data:
`DECISION_MIGRATION_ORDER` is *one* owner where the insert's set was three.
The difference is not tidiness; it is the SQLite fact this module's other
order states from the insert's side.  The pre-registration needs the two
parents because SQLite resolves a foreign key's parent **when a row is
written through the child table**; the decision never writes one — its
``UPDATE`` touches ``decided_at``, a non-key column, and SQLite does not
resolve a parent for that (verified against SQLite 3.45.1, the workspace's
own, on a database holding the registry and neither parent).  A decision
store that ran the three-table set would be creating ``node`` and
``epoch_ledger`` for statements that name neither — the habit this module
exists to keep distinguishable from a dependency.  Three orders, three
bootstraps, one runner (:func:`_run_statements`) and one rule — *the set is
the tables this act's own statements name*.

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
    "CALIBRATION_MIGRATION_ORDER",
    "DECISION_MIGRATION_ORDER",
    "MIGRATION_ORDER",
    "PROMOTION_REGISTRY_TABLE",
    "bootstrap_calibration_schema",
    "bootstrap_decision_schema",
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

#: The two tables feature 298's calibration judgement *reads*, and the
#: migrations that create them, in the order they must run.
#:
#: Deliberately **not** a widening of :data:`MIGRATION_ORDER`, and the reason is
#: the same one this module's docstring states for the three: a constant that
#: lists the tables *one act* needs is a claim about that act, and the member's
#: suite pins :data:`MIGRATION_ORDER` as *"the three tables feature 291's one
#: ``INSERT`` needs"*.  Adding a fourth and a fifth there would silently widen
#: that claim — every pre-registration would create ``campaign`` as well, for a
#: write that reads nothing from it — while the calibration gate would still be
#: pulling the pre-registration's two unrelated tables into a read that names
#: neither.  Two acts, two sets, each the smallest set its own statement needs.
#:
#: ``node`` is shared with :data:`MIGRATION_ORDER` and that is not duplication:
#: both acts genuinely read it, each names its own dependency, and neither
#: reaches for the other's list.  ``campaign`` is the calibration gate's alone —
#: ``0111`` is the fourth position in the assembled chain, after ``0110`` and
#: before ``0112``, and it declares ``REQUIRES_TABLES = ()`` because the campaign
#: row references nothing: it is the tree's root, not a leaf of it.
CALIBRATION_MIGRATION_ORDER: tuple[tuple[str, str], ...] = (
    ("node", "0118_node_table"),
    ("campaign", "0111_campaign_table"),
)

#: The one table feature 293's two statements name — the read and the
#: one-column ``UPDATE`` — beside the migration that owns it.
#:
#: Deliberately **one** owner where :data:`MIGRATION_ORDER` is three, and the
#: reason is the SQLite fact that makes the insert's set three: SQLite
#: resolves a foreign key's parent **when a row is written through the child
#: table**, so the pre-registration's ``INSERT`` needs ``node`` and
#: ``epoch_ledger`` to exist — while the decision's ``UPDATE`` sets
#: ``decided_at``, a non-key column, and SQLite resolves no parent for it
#: (verified against SQLite 3.45.1, the workspace's own, on a registry-only
#: database).  A decision store that ran the three-table set would create two
#: tables no statement of its act names, which is the habit this module's
#: whole law exists to keep distinguishable from a dependency.
#:
#: ``0108``'s whole statement tuple runs, as it does inside the insert's set:
#: the file creates five tables besides ``promotion_registry``, taking one
#: statement out would be this member editing another's schema, and every
#: statement is ``IF NOT EXISTS`` so nothing is over-created.
DECISION_MIGRATION_ORDER: tuple[tuple[str, str], ...] = (
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


def _statements_for(
    order: tuple[tuple[str, str], ...], dialect: str
) -> tuple[str, ...]:
    """Every statement the migrations in ``order`` return for ``dialect``.

    The one loop both bootstraps run, so the two orders cannot diverge on *how*
    a revision's statements are collected — a second spelling of this would be a
    second place to get the "the migration is the author" discipline wrong.

    Each revision contributes all of its statements or none of them.  ``0108``
    creates five tables besides ``promotion_registry`` and ``0118`` creates
    three besides ``node``; taking one statement out of a tuple would be this
    member editing another's schema, where running the tuple is what "the
    migration is the author" means.  Nothing is over-created by doing so: every
    statement is ``IF NOT EXISTS``, so a database that already holds them is left
    exactly as it was, and the tables the other features of this domain will
    need — ``forward_record`` among them — are already where their own writers
    expect them.
    """
    collected: list[str] = []
    for _table, revision in order:
        collected.extend(_load_migration(revision).statements(dialect))
    return tuple(collected)


def _statements(dialect: str = "sqlite") -> tuple[str, ...]:
    """Every statement the three pre-registration migrations return, in order.

    The set feature 291's one ``INSERT`` needs — :data:`MIGRATION_ORDER`,
    unchanged and unwidened.
    """
    return _statements_for(MIGRATION_ORDER, dialect)


def _calibration_statements(dialect: str = "sqlite") -> tuple[str, ...]:
    """Every statement feature 298's read needs, in order.

    :data:`CALIBRATION_MIGRATION_ORDER` — ``node`` and ``campaign``, the two
    tables the traversal and the status read name.
    """
    return _statements_for(CALIBRATION_MIGRATION_ORDER, dialect)


def _decision_statements(dialect: str = "sqlite") -> tuple[str, ...]:
    """Every statement feature 293's act needs, in order.

    :data:`DECISION_MIGRATION_ORDER` — ``promotion_registry`` alone, the one
    table the read and the one-column ``UPDATE`` name.
    """
    return _statements_for(DECISION_MIGRATION_ORDER, dialect)


def _run_statements(
    connection: sqlite3.Connection, ddl: tuple[str, ...]
) -> tuple[str, ...]:
    """Execute ``ddl`` on ``connection`` and return it — the one runner.

    Spelled once so both bootstraps execute a statement tuple the same way, and
    so a caller that needs a *different* set of owners goes through the same
    door rather than growing a second copy of this loop.
    """
    cursor = connection.cursor()
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


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
    return _run_statements(connection, _statements(dialect))


def bootstrap_calibration_schema(
    connection: sqlite3.Connection, *, dialect: str = "sqlite"
) -> tuple[str, ...]:
    """Create the two tables feature 298's read needs; returns the DDL run.

    The calibration gate's half of the same contract
    :func:`bootstrap_schema` states, over a *different* set of owners: ``node``
    (``0118``) and ``campaign`` (``0111``), the only two tables the traversal and
    the status read name.  Same discipline in every other respect — no statement
    is authored here, each comes from ``statements(dialect)`` on the migration
    that owns the table, loaded by file path and run whole — and the same
    reasoning about idempotence: every statement is ``IF NOT EXISTS``, so a
    database the chain has already migrated is left exactly as it was.

    **Why this is a second set and not an argument to the first.**  A bootstrapping
    caller could be handed the wider three-table set and it would work, because
    every statement is ``IF NOT EXISTS``.  It is deliberately not offered, for
    the reason this module is *a claim about authorship*: the set a store runs
    should be the set its own statements name, or a reader cannot tell a
    dependency from a habit.  Feature 291's ``INSERT`` names ``promotion_registry``
    and its two ``REFERENCES`` parents; feature 298's two ``SELECT``s name
    ``node`` and ``campaign``.  A gate that ran the pre-registration's three
    would be creating ``epoch_ledger`` and ``promotion_registry`` — tables its
    read never touches — which is precisely the *"every write fails, naming a
    table this member has no business creating"* failure
    :func:`bootstrap_schema` was built to avoid, approached from the other side.

    ``node`` appears in both sets because both acts genuinely read it: the
    registry's row references it by foreign key and the traversal starts at it.
    That is a shared *dependency*, stated twice, and not a shared statement — the
    two callers each name the file that owns it, so a rename cannot leave one of
    them probing a table nobody writes.
    """
    return _run_statements(connection, _calibration_statements(dialect))


def bootstrap_decision_schema(
    connection: sqlite3.Connection, *, dialect: str = "sqlite"
) -> tuple[str, ...]:
    """Create the one table feature 293's act names; returns the DDL run.

    The decision's half of the contract :func:`bootstrap_schema` and
    :func:`bootstrap_calibration_schema` state, over the smallest set of the
    three: ``promotion_registry`` (``0108``) is the only table the act's read
    and one-column ``UPDATE`` name.  Same discipline in every other respect —
    no statement is authored here, each comes from ``statements(dialect)`` on
    the migration that owns the table, loaded by file path and run whole —
    and the same idempotence: every statement is ``IF NOT EXISTS``, so a
    database the chain has already migrated is left exactly as it was.

    **Why one owner and not the pre-registration's three.**  The insert's set
    is three because SQLite resolves a foreign key's parent when a row is
    written through the child table — the failure this module's order argues
    about.  The decision's ``UPDATE`` sets ``decided_at`` and writes through
    no child key, so SQLite resolves no parent for it (verified against
    SQLite 3.45.1 on a database holding the registry and neither parent),
    which makes ``node`` and ``epoch_ledger`` tables no statement of this act
    names.  Handing this caller the wider set would work — every statement is
    ``IF NOT EXISTS`` — and is deliberately not offered, for the reason the
    calibration's bootstrap refuses the same offer: the set a store runs
    should be the set its own statements name, or a reader cannot tell a
    dependency from a habit.
    """
    return _run_statements(connection, _decision_statements(dialect))
