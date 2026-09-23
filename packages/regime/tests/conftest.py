"""Fixtures for the regime member's own suite.

This suite lives inside the workspace member (``packages/regime/tests``)
rather than under the repository-level ``tests/`` tree, because the member
— including its tests — is this feature's file-claim scope, and the
placement is the one the discovery, artifacts, sandbox, canary, nulloracle
and bootstrap members take for the same reason: same-basename files
collide under one pytest run, so each member's suite is collected under
its own conftest.

The path bootstrap puts both import roots on ``sys.path`` regardless of
how pytest was invoked — the workspace's ``src/`` (for
``app.module_loader``, which the component registration imports) and this
member's ``src/`` (for ``regime`` itself) — the same bootstrap every
member suite in this workspace performs, so the suite is identical under
``uv run pytest`` (where the venv also provides both) and under a bare
``pytest``.

**One fixture earns its place, and it is about the *other* creator.**
Feature 283's store creates the ``regime_coverage`` table itself,
idempotently, on first use — the convergence ``0107``'s own docstring
sets up (*"whichever ran first is the winner and the statements agree"*)
— so a test that wants a *fresh* database needs no fixture at all: the
plain :func:`database_url` is a file nothing has touched, and the store's
first persist is what brings the table to it.  That is the difference
from the discovery member's suite, whose store refuses to create its
table and therefore needs the migration run for every test that writes.

:func:`migrated_database` exists for the *convergence* half of the law:
the deployment shape where the migration got there first, which a store
that helped itself to a different spelling would corrupt or duplicate.
It imports ``migrations/versions/0107_regime_coverage.py`` **by file
path** and calls its ``apply`` — by path rather than by module name
because ``migrations/`` is not a package, and *as the schema's owner*
because a suite that hand-wrote its own ``CREATE TABLE regime_coverage``
would be pinning this store's behaviour against a schema the suite made
up, when the whole point of the convergence is that ``0107``'s spelling
is the one that counts.  Should the file move, the import fails loudly
and says so, which is a better failure than a silent green against a
fictional table.

The database URL fixture is deliberately **not** autouse.  The
repository-level conftest points ``DATABASE_URL`` at a per-test SQLite
file for every suite under ``tests/``; this suite is not under
``tests/``, so the isolation is restated rather than inherited — and
restated as a fixture asked for by name, the same stance the discovery
member's conftest takes for its campaign file.  A test of the *refusals*
must not acquire a database by accident.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

# conftest.py -> packages/regime/tests -> packages/regime -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "regime" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from regime import RegimeCoverage

#: The versioned migration that owns this table's schema, by revision id —
#: feature 107's, whose docstring delegates the idempotent creation to this
#: plugin and whose convergence clause the cross-member suite pins.  A
#: constant so a reader can see which table the suite is about without
#: reading the fixtures, and so a rename is one edit.
REGIME_COVERAGE_MIGRATION = "0107_regime_coverage"

VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner.

    ``migrations/`` is not a package and is not on ``sys.path``; a migration
    is loaded by its runner the same way — by path — so loading it by path
    here is the shape a migration is *built* to be used in rather than a
    workaround.  A missing file fails with the path in the message, because
    the one failure a test should never have to guess at is "the schema
    owner moved".
    """
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the coverage "
            "table's own migration rather than hand-writing its DDL, so it "
            "needs the schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_regime_test_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a ledger file only this test can see.

    Nothing is created: the file does not exist until the store's first
    persist brings the table to it (the store is the table's second,
    idempotent creator) or a fixture runs the migration — which is what
    lets both creators' orders be tested as a *first* act on a fresh
    database.
    """
    return f"sqlite:///{tmp_path / 'regime-test.db'}"


@pytest.fixture
def coverage_migration() -> ModuleType:
    """The schema's owner, loaded by path.

    For the tests that need the migration itself rather than a database
    it has run on — the convergence tests drive its ``apply`` in the
    order the test chooses, and the downgrade test drives its
    ``downgrade`` to produce the state 0107's own docstring promises the
    plugin refills.
    """
    return _load_migration(REGIME_COVERAGE_MIGRATION)


@pytest.fixture
def migrated_database(database_url: str, coverage_migration: ModuleType) -> str:
    """A database holding the ``regime_coverage`` table by migration.

    The deployment shape where feature 107's migration got there first:
    the schema is the migration's, and what this fixture lets a test ask
    is whether the plugin's writer serves it — the convergence
    ``0107``'s own docstring promises, pinned from the other direction.
    """
    coverage_migration.apply(database_url)
    return database_url


@pytest.fixture
def migrate_at(coverage_migration: ModuleType):
    """Bring a database URL the *test* chooses to the coverage revision.

    For the convergence tests, where the two creators' orders are the
    subject and the URL must be one the test names itself.  Returns a
    callable so there is one spelling in this suite of "bring this
    database to ``0107``".
    """

    def _migrate(database_url: str) -> None:
        coverage_migration.apply(database_url)

    return _migrate


@pytest.fixture
def store(database_url: str) -> RegimeCoverage:
    """The store, pointed at this test's own fresh database.

    No migration has run: the store's first persist is what creates the
    table, which is the contract ``0107``'s downgrade path delegates and
    the reason this fixture does not ask for :func:`migrated_database`.
    """
    return RegimeCoverage(database_url)
