"""Suite-local fixtures for the snapshot package's tests.

This suite lives inside the workspace member (``packages/snapshot/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures in
``tests/conftest.py`` do not reach it — conftest scope follows directories.
The isolation those shared fixtures guarantee for every repository-level
suite is reproduced here deliberately: a fresh lake root per test, laid out
per docs/nullius-tech-architecture.md §4.2, with ``LAKE_ROOT`` pointed at
it. No test in this package can write into a real lake, and adjacent tests
never share one. ``DATABASE_URL`` is isolated in the same breath, because
the ``snapshot_manifest`` record feature 33 persists is written on every
seal — a suite that redirected only the lake would still drop rows into
whatever database the developer's shell names.

The path bootstrap below puts the member's ``src/`` on ``sys.path`` — the
same mechanism the module loader uses when it scans members — because the
root project does not depend on this member and the venv therefore does not
install it; this suite runs with the repository's pytest (``uv run pytest
packages/snapshot`` from the workspace root).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from snapshot import SnapshotService

DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"


@pytest.fixture
def lake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh §4.2 lake root, with ``LAKE_ROOT`` pointed at it."""
    root = tmp_path / "lake"
    (root / "snapshots").mkdir(parents=True)
    (root / "staging").mkdir()
    monkeypatch.setenv("LAKE_ROOT", str(root))
    return root


@pytest.fixture(autouse=True)
def _database_url_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point ``DATABASE_URL`` at a test-only database for every test.

    Mirrors the repository-level conftest (and the universe member's), so
    the ``snapshot_manifest`` record feature 33 persists can never land in
    a real database. Without this a test that seals would write into
    whatever ``DATABASE_URL`` the developer's shell happens to carry.

    A per-test SQLite file rather than ``sqlite://`` (in-memory): an
    in-memory database is per-connection, so a row written by one
    connection would not be visible to the next — which would make every
    read-path test vacuously empty instead of exercising the store.

    ``TEST_DATABASE_URL`` wins when set and non-empty, exactly as at the
    repository level.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV) or (
        f"sqlite:///{tmp_path / 'nullius-snapshot-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test, as the code sees it."""
    return _database_url_isolation


@pytest.fixture
def service(lake_root: Path) -> SnapshotService:
    """A sealing service bound to this test's isolated lake."""
    return SnapshotService.from_env()


@pytest.fixture
def staged(lake_root: Path) -> Path:
    """A staging area holding a small but structurally real tree.

    Mirrors the §4.2 partitioning shape (``bars/symbol=…/date=…/part``) so
    the tests exercise nested relative paths, not flat filenames.
    """
    bars = lake_root / "staging" / "bars" / "symbol=BTCUSDT" / "date=2026-09-01"
    bars.mkdir(parents=True)
    (bars / "part-0.parquet").write_bytes(b"BTCUSDT-2026-09-01-part-0")
    (bars / "part-1.parquet").write_bytes(b"BTCUSDT-2026-09-01-part-1")
    other = lake_root / "staging" / "bars" / "symbol=ETHUSDT" / "date=2026-09-01"
    other.mkdir(parents=True)
    (other / "part-0.parquet").write_bytes(b"ETHUSDT-2026-09-01-part-0")
    return lake_root / "staging"
