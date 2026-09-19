"""Fixtures for the universe member's own suite.

This suite lives inside the package (``packages/universe/tests``) rather
than under the repository-level ``tests/`` tree, because the package —
including its tests — is this feature's file-claim scope. The
repository-level ``tests/conftest.py`` therefore does not apply here
(pytest loads conftests along the collected path only), so the two
workspace isolation guarantees are mirrored, not invented: every test gets
a temporary ``LAKE_ROOT`` laid out per the architecture §4.2, and a
``DATABASE_URL`` pointing at a test-only database (``TEST_DATABASE_URL``
when provided, else a throwaway per-test SQLite file). No test can write
into the real lake or the real tree store, even by accident.

The path bootstrap makes both import roots visible regardless of how
pytest was invoked: the workspace's ``src/`` (for ``app.module_loader``,
which the component registration imports) and this member's ``src/`` (for
``universe`` itself).
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "universe" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

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


@pytest.fixture(autouse=True)
def _database_url_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Point ``DATABASE_URL`` at a test-only database for every test.

    Mirrors the repository-level conftest: ``TEST_DATABASE_URL`` wins when
    set and non-empty, else a per-test SQLite file under pytest's
    temporary directory.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV) or (
        f"sqlite:///{tmp_path / 'universe-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test, as the code sees it."""
    return _database_url_isolation
