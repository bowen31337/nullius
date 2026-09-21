"""Fixtures for the artifacts member's own suite.

This suite lives inside the workspace member (``packages/artifacts/
tests``) rather than under the repository-level ``tests/`` tree,
because the member — including its tests — is this feature's file-claim
scope.  The repository-level ``tests/conftest.py`` therefore does not
reach it (conftest scope follows directories), so the isolation its
fixtures guarantee is mirrored here, not invented:

* **no test ever writes into a real artifact store.**  ``ARTIFACT_ROOT``
  is pointed at a fresh temporary root for every test, autouse, because
  the store's configured default is ``artifacts/`` beside the workspace
  root — a suite that only *sometimes* redirected the root would leave
  every other test persisting node directories into the checkout.  The
  members with a path-configured component (the snapshot service's
  ``LAKE_ROOT``, the sidecar's ``NULL_SIDECAR_PATH``) redirect theirs
  the same way.
* **no test ever writes into a real tree store.**  ``DATABASE_URL`` is
  pointed at a throwaway per-test SQLite file, autouse, for the reason
  the repository-level conftest does the same thing: feature 169 is the
  directory half of §9.2 and needs no database, but feature 179's dedup
  gate is bound to the ``node`` table and *writes* to it under
  :meth:`~artifacts.CodeHashIndex.probe` — so a suite that only sometimes
  redirected the URL would be the one that deduplicated against, or
  reserved rows in, a deployment's real tree.  ``TEST_DATABASE_URL``
  (a CI scratch Postgres, say) is honoured when it is set and non-empty,
  mirroring the shared fixtures' treatment of it.

The path bootstrap below puts both import roots on ``sys.path``
regardless of how pytest was invoked: the workspace's ``src/`` (for
``app.module_loader``, which the component registration imports) and
this member's ``src/`` (for ``artifacts`` itself).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

# conftest.py -> packages/artifacts/tests -> packages/artifacts -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "artifacts" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from artifacts import (
    ARTIFACT_ROOT_ENV,
    DATABASE_URL_ENV,
    NODE_TABLE,
    ArtifactStore,
)

TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"


@pytest.fixture(autouse=True)
def _artifact_root_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point ``ARTIFACT_ROOT`` at a fresh temporary root for every test.

    Autouse and unconditional: the default root is beside the workspace
    root, so a test that never requested a fixture would otherwise be
    the one test persisting node directories into the checkout.
    """
    root = tmp_path / "artifacts"
    root.mkdir()
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(root))
    return root


@pytest.fixture
def artifact_root(_artifact_root_isolation: Path) -> Path:
    """The temporary artifact root for this test."""
    return _artifact_root_isolation


@pytest.fixture
def store(artifact_root: Path) -> ArtifactStore:
    """A store bound to this test's isolated root, as the environment names it.

    Resolved through :meth:`ArtifactStore.from_env` — the same path the
    composed application's builder takes — rather than constructed
    directly, so every test also exercises the environment binding the
    deployment actually uses.
    """
    return ArtifactStore.from_env()


@pytest.fixture
def campaign_id() -> str:
    """A fresh canonical UUID for a campaign under test."""
    return str(uuid.uuid4())


@pytest.fixture
def node_id() -> str:
    """A fresh canonical UUID for a node under test."""
    return str(uuid.uuid4())


@pytest.fixture
def other_node_id() -> str:
    """A second, equally fresh node of the same campaign."""
    return str(uuid.uuid4())


@pytest.fixture
def other_campaign_id() -> str:
    """A second campaign, for the tests that key the two levels apart."""
    return str(uuid.uuid4())


# -- The tree store (feature 179) --------------------------------------------------


@pytest.fixture(autouse=True)
def _database_url_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Point ``DATABASE_URL`` at a throwaway database for every test.

    Autouse and unconditional, like ``_artifact_root_isolation``: feature
    179's gate writes to the ``node`` table under ``probe``, so a test that
    never requested a fixture would otherwise be the one reserving rows in,
    or deduplicating against, whatever ``DATABASE_URL`` the process
    inherited.  Derived from ``TEST_DATABASE_URL`` when that is set and
    non-empty, else a per-test SQLite file — the repository conftest's own
    rule, so a CI scratch Postgres is honoured here too.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV) or (
        f"sqlite:///{tmp_path / 'nullius-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test, as the gate sees it."""
    return _database_url_isolation


#: The ``node`` table as §9.1 and migrations 0113/0117 describe it, reduced
#: to the columns this category's features speak: the key and the structural
#: columns feature 97 owns, and feature 98's ``code_hash`` — the column
#: feature 179 deduplicates on, ``CHAR(64) NOT NULL``.
#:
#: The tests create it themselves rather than importing a migration, the
#: same way the null oracle's suites do: the tree member owns the DDL
#: (features 97-102) and this member owns the check that *reads* it, so a
#: suite that imported the migration would be asserting this member against
#: another feature's file rather than against the schema §9.1 states.
NODE_TABLE_DDL = (
    f"CREATE TABLE {NODE_TABLE} ("
    "id TEXT NOT NULL PRIMARY KEY, "
    "parent_id TEXT, "
    "campaign_id TEXT NOT NULL, "
    "theme_root TEXT, "
    "depth INT, "
    "code_hash CHAR(64) NOT NULL)"
)


class NodeTable:
    """A connection factory over one test's throwaway tree store.

    A helper rather than a connection, because the gate opens and closes its
    own connections (that is the contract under test) and a test that held
    one open would be holding the lock the gate needs.  Each call to
    :meth:`connect` opens a fresh connection to the same throwaway file, so a
    test can read back what the gate wrote.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        """A fresh connection to the tree store, for a test to read with."""
        return sqlite3.connect(self.path)

    def rows(self, campaign_id: str) -> list[tuple[str, str]]:
        """This campaign's nodes as ``(id, code_hash)``, sorted by id."""
        with self.connect() as connection:
            return [
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    f"SELECT id, code_hash FROM {NODE_TABLE} "
                    "WHERE campaign_id = ? ORDER BY id",
                    (campaign_id,),
                ).fetchall()
            ]


@pytest.fixture
def tree_store(test_database_url: str) -> NodeTable:
    """Create the ``node`` table in this test's database."""
    store = NodeTable(Path(test_database_url.removeprefix("sqlite:///")))
    with store.connect() as connection:
        connection.execute(NODE_TABLE_DDL)
    return store
