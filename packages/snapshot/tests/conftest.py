"""Suite-local fixtures for the snapshot package's tests.

This suite lives inside the workspace member (``packages/snapshot/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures in
``tests/conftest.py`` do not reach it — conftest scope follows directories.
The isolation those shared fixtures guarantee for every repository-level
suite is reproduced here deliberately: a fresh lake root per test, laid out
per docs/nullius-tech-architecture.md §4.2, with ``LAKE_ROOT`` pointed at
it. No test in this package can write into a real lake, and adjacent tests
never share one.

The path bootstrap below puts the member's ``src/`` on ``sys.path`` — the
same mechanism the module loader uses when it scans members — because the
root project does not depend on this member and the venv therefore does not
install it; this suite runs with the repository's pytest (``uv run pytest
packages/snapshot`` from the workspace root).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from snapshot import SnapshotService


@pytest.fixture
def lake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh §4.2 lake root, with ``LAKE_ROOT`` pointed at it."""
    root = tmp_path / "lake"
    (root / "snapshots").mkdir(parents=True)
    (root / "staging").mkdir()
    monkeypatch.setenv("LAKE_ROOT", str(root))
    return root


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
