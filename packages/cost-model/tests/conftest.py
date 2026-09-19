"""Fixtures for the cost-model member's own suite.

This suite lives inside the package (``packages/cost-model/tests``) rather
than under the repository-level ``tests/`` tree, because the package —
including its tests — is this feature's file-claim scope.  The
repository-level ``tests/conftest.py`` therefore does not apply here
(pytest loads conftests along the collected path only), so the one
workspace isolation guarantee this member needs is mirrored, not invented:
every test gets a ``DATABASE_URL`` pointing at a test-only database
(``TEST_DATABASE_URL`` when provided, else a throwaway per-test SQLite
file).  No test can write into the real store, even by accident.

The lake-root isolation the repository conftest also enforces is
deliberately not mirrored: the cost model has no lake footprint.  It reads
one YAML document and speaks to the relational store, so those are the only
environments its suite pins.

The path bootstrap makes both import roots visible regardless of how pytest
was invoked: the workspace's ``src/`` (for ``app.module_loader``, which the
component registration imports) and this member's ``src/`` (for
``cost_model`` itself).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# tests/conftest.py -> packages/cost-model/tests -> packages/cost-model -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "cost-model" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"


@pytest.fixture(autouse=True)
def _database_url_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Point ``DATABASE_URL`` at a test-only database for every test.

    Mirrors the repository-level conftest: ``TEST_DATABASE_URL`` wins when
    set and non-empty, else a per-test SQLite file under pytest's temporary
    directory.  An empty ``TEST_DATABASE_URL`` counts as unset.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV) or (
        f"sqlite:///{tmp_path / 'cost-model-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test, as the code sees it."""
    return _database_url_isolation


@pytest.fixture
def document(tmp_path: Path):
    """Write a cost model YAML document and return its path.

    A helper rather than a fixed file: most tests here are about a document
    that is wrong in one specific way, and the shortest honest way to say
    "wrong in this way" is to write the bytes and load them.
    """

    def _write(text: str, name: str = "cost_model.yaml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write
