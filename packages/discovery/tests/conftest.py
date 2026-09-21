"""Fixtures for the discovery member's own suite.

This suite lives inside the workspace member (``packages/discovery/tests``)
rather than under the repository-level ``tests/`` tree, because the member —
including its tests — is this feature's file-claim scope, and the placement is
the one the artifacts, sandbox, canary, nulloracle and bootstrap members take
for the same reason: same-basename files collide under one pytest run, so each
member's suite is collected under its own conftest.

The path bootstrap puts both import roots on ``sys.path`` regardless of how
pytest was invoked — the workspace's ``src/`` (for ``app.module_loader``,
which the component registration imports) and this member's ``src/`` (for
``discovery`` itself) — the same bootstrap every member suite in this
workspace performs, so the suite is identical under ``uv run pytest`` (where
the venv also provides both) and under a bare ``pytest``.

**Two fixtures earn their place, and both are about *schema*.**  Feature 232
writes the campaign row, and it deliberately does not create the ``campaign``
table (see :meth:`discovery.campaign.CampaignRecords._connect`: ``0111`` is
the authority on those columns, and a member that invented them would be
improvising a schema it does not own).  So a test that wants a campaign must
bring the table the way a deployment does, and there is exactly one honest way
to do that here: run the migration.  :func:`migrated_database` imports
``migrations/versions/0111_campaign_table.py`` **by file path** and calls its
``apply``.

That import is by path rather than by module name on purpose, and it is not
incidental.  ``migrations/`` is not a package, is not importable as one, and
is deliberately outside this member's file-claim scope — this suite must not
require anything of it beyond the two functions its docstring advertises.  It
loads the file *because it is the schema's owner*: a suite that hand-wrote its
own ``CREATE TABLE campaign`` would be pinning this store's behaviour against
a schema this suite made up, and the whole point of refusing to create the
table is that ``0111``'s spelling is the one that counts.  Should feature 104's
file move, this import fails loudly and says so, which is a better failure than
a silent green against a fictional table.

:func:`node_table` is the same discipline for feature 97's tree: created
through ``0118_node_table.py`` when a test needs to prove the ordering law, and
never created at all when it does not — the absent table is itself a case the
feature has to answer, and the tests that pin it simply do not ask for this
fixture.

The database URL fixture is deliberately **not** autouse.  The repository-level
conftest points ``DATABASE_URL`` at a per-test SQLite file for every suite
under ``tests/``; this suite is not under ``tests/``, so the isolation is
restated rather than inherited — and restated as a fixture asked for by name,
the same stance the bootstrap member's conftest takes for its pool.  A test of
the *clip* must not acquire a database by accident.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest

# conftest.py -> packages/discovery/tests -> packages/discovery -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "discovery" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from discovery import CampaignRecords

#: The versioned migrations this suite runs, by revision id.  Spelled as
#: constants so a reader can see which two tables the suite is about without
#: reading the fixtures, and so a rename is one edit.
CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_MIGRATION = "0118_node_table"

VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"


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
            f"{revision} is not at {path}; this suite runs the campaign table's "
            "own migration rather than hand-writing its DDL, so it needs the "
            "schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_discovery_test_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_schema(database_url: str, *revisions: str) -> None:
    """Bring ``database_url`` to ``revisions``, in the order given.

    Through each migration's own ``apply``, which opens, runs and commits on
    the named database — the standalone entry point those files advertise for
    a caller with no migration runner, which is the state of this workspace.
    """
    for revision in revisions:
        _load_migration(revision).apply(database_url)


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a campaign file only this test can see.

    Nothing is created: the file does not exist until a fixture or a test
    brings a schema to it, which is what lets the "no such table" case be
    tested as the *first* thing that happens to a fresh database.
    """
    return f"sqlite:///{tmp_path / 'campaign-test.db'}"


@pytest.fixture
def migrated_database(database_url: str) -> str:
    """A database holding the ``campaign`` table, and nothing else.

    The deployment-shaped starting point for feature 232: the migration has
    run (so the row can land) and no node exists (so the ordering law is
    satisfied).  The ``node`` table is deliberately absent — that is its own
    state, with its own fixture.
    """
    _create_schema(database_url, CAMPAIGN_MIGRATION)
    return database_url


@pytest.fixture
def migrated_with_tree(database_url: str) -> str:
    """A database holding both the ``campaign`` and the ``node`` tables.

    For the ordering law's one live question — *has anything been expanded?* —
    which cannot be asked of a database whose tree table does not exist.  The
    migration is feature 97's, run the same way and for the same reason.
    """
    _create_schema(database_url, CAMPAIGN_MIGRATION, NODE_MIGRATION)
    return database_url


@pytest.fixture
def migrate_at():
    """Bring a database URL the *test* chooses to a revision set.

    For the tests that need the schema at a path they name themselves — the
    composition tests, where the URL must be the one ``DATABASE_URL`` carries
    and therefore must be chosen before the environment is pointed at it.
    Returns the same ``_create_schema`` the fixtures use, so there is one
    spelling of "bring this database to these revisions" in the suite.
    """
    return _create_schema


@pytest.fixture
def records(migrated_database: str) -> CampaignRecords:
    """The store, pointed at this test's own migrated database.

    ``CampaignRecords`` is imported at module scope rather than inside the
    fixture, unlike the bootstrap member's pool: this whole suite is about the
    one store, so there is no world half for a lazy import to keep clean.
    """
    return CampaignRecords(migrated_database)


@pytest.fixture
def tree_records(migrated_with_tree: str) -> CampaignRecords:
    """The store, over a database that also holds the tree's node table."""
    return CampaignRecords(migrated_with_tree)


@pytest.fixture
def campaign_id() -> str:
    """A fresh canonical campaign UUID — an id the caller supplies.

    Distinct per test, and a real UUID, because the store canonicalizes ids
    through :class:`uuid.UUID` and a hand-rolled string would be exercising
    the refusal rather than the feature.
    """
    return str(uuid.uuid4())


@pytest.fixture
def plant_root(migrated_with_tree: str):
    """Insert one node under a campaign — the act feature 232 forbids first.

    Deliberately raw SQL against the migrated tree table rather than a call
    into any node-planting feature: this suite must not acquire a dependency
    on how nodes are normally created (there is no such feature in this
    member, and the point is to produce the *state* the law is about, not to
    reproduce the authoring path).  ``parent_id`` stays ``NULL``, which is
    what makes the row a root, and ``theme_root``/``depth`` take the values
    ``0118`` declares — the five columns feature 97 names and no sixth.

    Returns a callable so a test can plant more than one node, or plant under
    a campaign other than its own.
    """

    def _plant(campaign: str, *, parent_id: str | None = None, depth: int = 0) -> str:
        identifier = str(uuid.uuid4())
        with closing(sqlite3.connect(_path_of(migrated_with_tree))) as connection, connection:
            connection.execute(
                "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, 'macro', ?)",
                (identifier, parent_id, campaign, depth),
            )
        return identifier

    return _plant


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test.

    This suite's own four lines rather than a call into the member: the store's
    ``_sqlite_path`` is private, and a test reaching into it would be pinning
    an implementation detail it should be free to change.  A migration's URL
    grammar is what :func:`discovery.campaign._sqlite_path` mirrors, so the
    translation is the same three steps by design.
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))
