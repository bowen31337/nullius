"""Acceptance tests for the shared fixtures in tests/conftest.py.

These pin the isolation contract every workspace suite relies on: a
temporary lake root per test, and a DATABASE_URL that never points at the
real tree store or trial ledger.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def test_fresh_lake_and_database_per_test() -> None:
    # Two tests in one child process: the second must not see the first's
    # lake, marker or database. Run in a child so the pair shares a process
    # even when this suite runs under pytest-xdist.
    probe = REPO_ROOT / "tests" / f"test__fresh_probe_{uuid.uuid4().hex}_tmp.py"
    probe.write_text(
        "from pathlib import Path\n"
        "\n"
        "_seen = {}\n"
        "\n"
        "\n"
        "def test_first(lake_root, test_database_url):\n"
        "    (lake_root / 'staging' / 'marker.txt').write_text('first')\n"
        "    _seen['lake'] = str(lake_root)\n"
        "    _seen['db'] = test_database_url\n"
        "\n"
        "\n"
        "def test_second(lake_root, test_database_url):\n"
        "    assert _seen, 'test_first must run first, in this process'\n"
        "    assert not (lake_root / 'staging' / 'marker.txt').exists()\n"
        "    assert str(lake_root) != _seen['lake']\n"
        "    assert test_database_url != _seen['db']\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(probe)],
            check=False,
            cwd=REPO_ROOT,
            env={k: v for k, v in os.environ.items() if k != "PYTEST_XDIST_WORKER"},
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout, result.stdout


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
