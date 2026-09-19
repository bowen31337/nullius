"""Shared pytest fixtures for every suite in the nullius workspace.

All workspace suites live under the repository-level ``tests/`` tree
(``tests/invariants/**``, ``tests/e2e/**``, ...), so this single conftest
applies to every one of them.

Two guarantees hold for every test, by construction:

* ``LAKE_ROOT`` is redirected to a temporary lake root laid out per
  docs/nullius-tech-architecture.md §4.2 (``snapshots/`` for sealed,
  content-addressed snapshots; ``staging/`` for writable ingest). No test
  can write into the real 1–3 TB lake, even one it never requested the
  fixture for.
* ``DATABASE_URL`` is isolated to a test-only database. The URL is taken
  from ``TEST_DATABASE_URL`` when the environment provides one (a CI
  scratch Postgres, say) and otherwise falls back to a throwaway per-test
  SQLite file, per the app spec's "SQLite acceptable single-machine"
  allowance. An empty ``TEST_DATABASE_URL`` counts as unset.

The ``lake_root`` and ``test_database_url`` fixtures expose the isolated
values; the underscore-prefixed autouse fixtures enforce them. Both are
function-scoped: adjacent tests never share a lake or a database.
"""

import os
from pathlib import Path

import pytest

DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"
LAKE_ROOT_ENV = "LAKE_ROOT"


@pytest.fixture(autouse=True)
def _lake_root_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``LAKE_ROOT`` at a fresh temporary lake for every test."""
    root = tmp_path / "lake"
    (root / "snapshots").mkdir(parents=True)
    (root / "staging").mkdir()
    monkeypatch.setenv(LAKE_ROOT_ENV, str(root))
    return root


@pytest.fixture
def lake_root(_lake_root_isolation: Path) -> Path:
    """The temporary lake root for this test.

    The directory exists and already contains the standard ``snapshots/``
    and ``staging/`` subdirectories; ``LAKE_ROOT`` is set to it for the
    duration of the test.
    """
    return _lake_root_isolation


@pytest.fixture(autouse=True)
def _database_url_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Point ``DATABASE_URL`` at a test-only database for every test."""
    url = os.environ.get(TEST_DATABASE_URL_ENV) or (
        f"sqlite:///{tmp_path / 'nullius-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test.

    Equals ``DATABASE_URL`` as the code under test sees it. Derived from
    ``TEST_DATABASE_URL`` when that is set and non-empty, else a per-test
    SQLite file under pytest's temporary directory.
    """
    return _database_url_isolation
