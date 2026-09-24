"""Fixtures for the promotion member's own suite.

This suite lives inside the workspace member (``packages/promotion/tests``)
rather than under the repository-level ``tests/`` tree, because the member —
including its tests — is this feature's file-claim scope, and the placement is
the one the discovery, artifacts, sandbox, canary, nulloracle, bootstrap,
regime and replay members take for the same reason: same-basename files
collide under one pytest run, so each member's suite is collected under its
own conftest.

The path bootstrap puts both import roots on ``sys.path`` regardless of how
pytest was invoked — the workspace's ``src/`` (for ``app.module_loader``,
which the component registration imports) and this member's ``src/`` (for
``promotion`` itself) — the same bootstrap every member suite in this
workspace performs, so the suite is identical under ``uv run pytest`` (where
the venv also provides both) and under a bare ``pytest``.

**Two fixtures earn their place, and both are about the *other* creator.**
Feature 291's store brings the database to the revision the row needs itself,
on first use — it runs the *owning migrations'* own ``statements("sqlite")``
for ``node``, ``epoch_ledger`` and ``promotion_registry`` — so a test that
wants a fresh database needs no fixture at all: the plain
:func:`database_url` is a file nothing has touched, and the store's first
:meth:`~promotion.pre_register.PreRegistrations.pre_register` is what brings
the three tables to it.  That is the same stance the regime member's suite
takes toward its own store.

:func:`migrated_database` exists for the *convergence* half of that law: the
deployment shape where the migrations got there first, which a store that
helped itself to a different spelling would corrupt or duplicate.  It loads
``migrations/versions/0118_node_table.py``, ``0110_epoch_ledger.py`` and
``0108_forward_and_universe_tables.py`` **by file path** and calls their
``apply`` — by path rather than by module name because ``migrations/`` is not
a package, and *in the order the store itself uses* because the dependency is
real even where SQLite is tolerant: SQLite does not resolve a foreign key's
parent until a row is written, so a registry-only database is *declared*
happily and then refuses every ``INSERT`` with ``no such table: main.node``
(the parent it names is its own business; that it names one this member does
not own is the point).  The order is the chain's, and ``0108``'s own words keep
it: *"a tolerance, not a licence."*  A suite that hand-wrote its own ``CREATE
TABLE
promotion_registry`` would be pinning this store's behaviour against a schema
the suite made up, when the whole point is that ``0108``'s spelling is the
one that counts.  Should a file move, the import fails loudly and says so,
which is a better failure than a silent green against a fictional table.

**The parent rows are a fixture because they are not the store's job.**
``promotion_registry``'s two foreign keys are real, and the store *checks*
them rather than manufacturing them: a node's row is feature 232's campaign
record and the discovery loop's write, and an epoch's row is the sealing
process's.  So the suite states them by hand, in the columns the migrations
declare, which is also what makes the absent-parent refusals testable — the
probe has to be able to fail.

The database URL fixture is deliberately **not** autouse.  The
repository-level conftest points ``DATABASE_URL`` at a per-test SQLite file
for every suite under ``tests/``; this suite is not under ``tests/``, so the
isolation is restated rather than inherited — and restated as a fixture asked
for by name, the same stance the regime and discovery members' conftests take.
A test of the *refusals* must not acquire a database by accident.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# conftest.py -> packages/promotion/tests -> packages/promotion -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "promotion" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from promotion import PreRegistrations, PromotionCriteria

VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The three tables feature 291's one ``INSERT`` needs, and the revision that
#: owns each — the same order :data:`promotion.schema.MIGRATION_ORDER` states,
#: restated as data here so the suite asserts *that* order rather than
#: importing it (a suite that imported the constant would agree with the
#: member by construction and pin nothing).
MIGRATION_REVISIONS: tuple[str, ...] = (
    "0118_node_table",
    "0110_epoch_ledger",
    "0108_forward_and_universe_tables",
)

#: A node identity and an epoch name the suite reuses, so every test's rows
#: join to the same two parents and a failure names a constant rather than a
#: literal buried in an assertion.
NODE_ID = "11111111-1111-4111-8111-111111111111"
CAMPAIGN_ID = "22222222-2222-4222-8222-222222222222"
EPOCH_ID = "epoch-2026-01"

#: The criteria every test starts from — the six terms as the PRD's own
#: milestones read them, and the document the endpoint's body is written in.
DEFAULT_CRITERIA_DOCUMENT: dict[str, Any] = {
    "theta": 0.3,
    "alpha": 0.05,
    "max_fdr_deploy": 0.25,
    "min_worlds": 50,
    "min_coverage_strata": 3,
    "min_forward_days": 90,
}


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    ``migrations/`` is not a package and is not on ``sys.path``; a migration
    is loaded by its runner the same way — by path — so loading it by path
    here is the shape a migration is *built* to be used in rather than a
    workaround.  A missing file fails with the path in the message, because
    the one failure a test should never have to guess at is "the schema owner
    moved".
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the promotion "
            "registry's own migrations rather than hand-writing its DDL, so "
            "it needs the schema's owners to be where the tree keeps them"
        )
    spec = importlib.util.spec_from_file_location(
        f"_promotion_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def code_of(module: Any) -> str:
    """A module's *code* as unparsed text, with every docstring stripped.

    For the assertions that a claim is true of what a module **does** rather
    than of what it **says**.  ``promotion.schema`` has to be able to write
    the sentence *no ``CREATE TABLE`` is authored here* in its own docstring
    while authoring none, and ``promotion.pre_register`` has to be able to
    name feature 292's ``criteria_mismatch`` in order to say it is not that —
    so a test that scanned the raw file for those words would fail on the
    very prose that makes the claim, and would tempt a later author to delete
    the explanation to keep the suite green.

    Docstrings are removed by position: for every module, class and function
    in the tree, a first statement that is a bare string constant is dropped
    before unparsing.  Everything else — including the f-strings a migration
    builds its DDL out of, which is exactly what the DDL claim needs to see —
    survives.
    """
    import ast

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    holders = [tree]
    holders += [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for holder in holders:
        body = holder.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            holder.body = body[1:]
    return ast.unparse(tree)


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a registry file only this test can see.

    Nothing is created: the file does not exist until the store's first
    pre-registration brings the three tables to it (the store runs the owning
    migrations' own statements) or a fixture runs the migrations — which is
    what lets both creators' orders be tested as a *first* act on a fresh
    database.
    """
    return f"sqlite:///{tmp_path / 'promotion-test.db'}"


@pytest.fixture
def migrations() -> tuple[ModuleType, ...]:
    """The three schema owners, loaded by path, in dependency order."""
    return tuple(_load_migration(revision) for revision in MIGRATION_REVISIONS)


@pytest.fixture
def migrated_database(database_url: str, migrations: tuple[ModuleType, ...]) -> str:
    """A database holding all three tables *by migration*.

    The deployment shape where the versioned tree got there first: the schema
    is the migrations', and what this fixture lets a test ask is whether the
    plugin's writer serves it — the convergence pinned from the other
    direction.  The order is the chain's rather than SQLite's demand: SQLite
    would accept ``promotion_registry`` declared first and fail at the first
    row instead, which is a tolerance and not a licence to reorder.
    """
    for migration in migrations:
        migration.apply(database_url)
    return database_url


@pytest.fixture
def store(database_url: str) -> PreRegistrations:
    """The store, pointed at this test's own fresh database.

    No migration has run: the store's first pre-registration is what brings
    the three tables to it.  That is the contract the member's schema adapter
    states — it authors no DDL and runs the owners' own statements — and the
    reason this fixture does not ask for :func:`migrated_database`.
    """
    return PreRegistrations(database_url)


@pytest.fixture
def criteria() -> PromotionCriteria:
    """The criteria every test starts from, as the member's own value."""
    return PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT)


@pytest.fixture
def seeded_database(store: PreRegistrations) -> PreRegistrations:
    """The store's database brought up *and* given the two parent rows.

    ``promotion_registry``'s foreign keys are real and the store checks them
    rather than manufacturing them: a node's row is the discovery loop's
    write and an epoch's row is the sealing process's, neither of which is
    this member's to invent.  So the suite supplies them — in the columns the
    migrations declare, through the store's own connection — and every test
    that writes a registration asks for this fixture.  The tests that check
    the *absent* parent refusals deliberately do not.
    """
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, ?)",
                (NODE_ID, CAMPAIGN_ID, "macro", 1),
            )
            connection.execute(
                "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
                (EPOCH_ID, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        connection.close()
    return store


@pytest.fixture
def registry_rows(seeded_database: PreRegistrations):
    """Read ``promotion_registry`` raw, so a test can see what actually landed.

    Returns a callable rather than a list because most tests read *after* the
    act under test.  Deliberately a raw ``SELECT`` rather than a store verb:
    the point of most of these assertions is what the *table* holds — including
    ``decided_at``'s NULL, which no store read here is shaped to return as a
    bare fact — and a test that asked the store would be asking the code under
    test to confirm itself.
    """

    def _rows() -> list[sqlite3.Row]:
        connection = seeded_database._connect()
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                "SELECT id, node_id, epoch_id, criteria_hash, "
                "pre_registered_at, decided_at FROM promotion_registry"
            )
            try:
                return list(cursor.fetchall())
            finally:
                cursor.close()
        finally:
            connection.close()

    return _rows
