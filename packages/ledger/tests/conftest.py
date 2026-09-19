"""Fixtures for the ledger member's own suite.

This suite lives inside the package (``packages/ledger/tests``) rather
than under the repository-level ``tests/`` tree, because the package —
including its tests — is this feature's file-claim scope.  The
repository-level ``tests/conftest.py`` therefore does not apply here
(pytest loads conftests along the collected path only), so the one
workspace isolation guarantee this member needs is mirrored, not
invented: every test gets a ``DATABASE_URL`` pointing at a test-only
database (``TEST_DATABASE_URL`` when provided, else a throwaway per-test
SQLite file).  No test can write into the real tree store, even by
accident — and a suite whose whole subject is the honest accounting of
charges is exactly the suite that must not spend real sequence numbers
while testing.

The lake-root isolation the repository conftest also enforces is
deliberately not mirrored: the ledger has no lake footprint.  It speaks
to the relational store only, so that is the only environment its suite
pins.

The path bootstrap makes both import roots visible regardless of how
pytest was invoked: the workspace's ``src/`` (for ``app.module_loader``,
which the component registration imports) and this member's ``src/``
(for ``ledger`` itself).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# tests/conftest.py -> packages/ledger/tests -> packages/ledger -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "ledger" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

# Imported only after the bootstrap above has made both roots visible:
# `ledger` itself, and `app.module_loader` for the component registration.
from ledger import TrialLedger  # noqa: E402

DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"


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
        f"sqlite:///{tmp_path / 'ledger-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test, as the code sees it."""
    return _database_url_isolation


@pytest.fixture
def test_ledger(test_database_url: str) -> TrialLedger:
    """A ledger bound to this test's isolated database URL.

    Construction performs no I/O (the schema appears on the first
    append or read), so this is safe to request even in tests that never
    touch the store.
    """
    return TrialLedger(test_database_url)


@pytest.fixture
def db_path(test_database_url: str) -> Path:
    """The SQLite file behind this test's URL, for raw-SQL probes.

    The monotonicity tests reach under the store on purpose — deleting
    the maximum row out from under the sequence is the one honest way to
    prove the sequence does not depend on the rows it can see.
    """
    return TrialLedger(test_database_url).path
