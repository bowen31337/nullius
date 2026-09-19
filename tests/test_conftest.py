"""Acceptance tests for the shared fixtures in tests/conftest.py.

These pin the isolation contract every workspace suite relies on: a
temporary lake root per test, and a DATABASE_URL that never points at the
real tree store or trial ledger.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_seen: dict[str, str] = {}


def test_lake_root_layout_and_env(lake_root: Path) -> None:
    # §4.2 layout: sealed snapshots plus a writable staging area.
    assert (lake_root / "snapshots").is_dir()
    assert (lake_root / "staging").is_dir()
    assert os.environ["LAKE_ROOT"] == str(lake_root)


def test_database_url_fixture_matches_env(test_database_url: str) -> None:
    assert os.environ["DATABASE_URL"] == test_database_url


def test_default_database_is_throwaway_sqlite(test_database_url: str) -> None:
    # Without TEST_DATABASE_URL the suite still runs isolated.
    assert test_database_url.startswith("sqlite:///")


def test_isolation_applies_without_requesting_fixtures() -> None:
    # The autouse guards protect even tests that ask for nothing.
    lake = Path(os.environ["LAKE_ROOT"])
    assert lake.name == "lake"
    assert (lake / "snapshots").is_dir()
    assert os.environ["DATABASE_URL"].startswith("sqlite:///")


def test_fresh_lake_and_database_per_test_first(
    lake_root: Path, test_database_url: str
) -> None:
    (lake_root / "staging" / "marker.txt").write_text("first")
    _seen["lake"] = str(lake_root)
    _seen["db"] = test_database_url


def test_fresh_lake_and_database_per_test_second(
    lake_root: Path, test_database_url: str
) -> None:
    assert not (lake_root / "staging" / "marker.txt").exists()
    assert str(lake_root) != _seen["lake"]
    assert test_database_url != _seen["db"]


def test_test_database_url_override_is_honored() -> None:
    # TEST_DATABASE_URL must reach the code under test as DATABASE_URL.
    # It is resolved at setup time, so prove it through a child pytest run.
    override = "postgresql://ci:5432/scratch_db"
    probe = REPO_ROOT / "tests" / "test__override_probe_tmp.py"
    probe.write_text(
        "import os\n"
        "\n"
        "\n"
        "def test_override():\n"
        "    assert os.environ['DATABASE_URL'] == "
        f"{override!r}\n"
        "    assert os.environ.get('TEST_DATABASE_URL') == "
        f"{override!r}\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(probe)],
            cwd=REPO_ROOT,
            env={**os.environ, "TEST_DATABASE_URL": override},
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert result.returncode == 0, result.stdout + result.stderr
