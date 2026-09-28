"""Fixtures for the api member's own suite.

This suite lives inside the package (``packages/api/tests``) rather
than under the repository-level ``tests/`` tree, because the member —
including its tests — is this feature's file-claim scope, the same
placement the ops, router and cost-model members' suites take for the
same reason: same-basename files collide under one pytest run, so each
member's suite is collected under its own conftest.

The path bootstrap puts every declared workspace member's scan root on
``sys.path`` — not just this member's own ``src/`` — because the
transport serves the *composed* application: the route table resolves
components the ops, ledger, promotion, forward, nulloracle and risk
members register, and the store-wrap tests construct those members'
own endpoint classes over fake stores, so all of them must be
importable regardless of how pytest was invoked.  Resolved from the
root ``pyproject.toml``'s own ``[tool.uv.workspace]`` through
:func:`app.module_loader.workspace_scan_roots` rather than hard-coded,
the same convention ``packages/ops/tests/conftest.py`` follows and for
the same reason: a hard-coded path here could quietly disagree with
the declaration that decides whether a member is importable at all.

Every test gets a ``DATABASE_URL`` pointing at a test-only database
(``TEST_DATABASE_URL`` when provided, else a throwaway per-test SQLite
file), mirroring the repository-level conftest and the ops member's
own: the routes this transport serves write charges, registrations and
kills, exactly the rows a stray inherited ``DATABASE_URL`` would land
somewhere an operator reads.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# conftest.py -> packages/api/tests -> packages/api -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"

if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from app.module_loader import workspace_scan_roots

for _root in workspace_scan_roots():
    _entry = str(_root)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"


@pytest.fixture(autouse=True)
def _database_url_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Point ``DATABASE_URL`` at a test-only database for every test.

    Mirrors the repository-level conftest and the ops member's own:
    ``TEST_DATABASE_URL`` wins when set and non-empty, else a per-test
    SQLite file under pytest's temporary directory.  An empty
    ``TEST_DATABASE_URL`` counts as unset.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV) or (
        f"sqlite:///{tmp_path / 'api-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test, as the code sees it."""
    return _database_url_isolation
