"""Fixtures for the router member's own suite.

This suite lives inside the package (``packages/router/tests``) rather than
under the repository-level ``tests/`` tree, because the package — including
its tests — is this feature's file-claim scope, the same placement the
cost-model and signal-agent members' suites take for the same reason:
same-basename files collide under one pytest run, so each member's suite is
collected under its own conftest.

The path bootstrap puts every declared workspace member's scan root on
``sys.path`` — not just this member's own ``src/`` — because this member
depends on ``nullius-ingest`` (:mod:`router.exchange_info` parses every
fetch through :mod:`nullius_ingest.exchange_info` rather than a second
parser of the same document) and needs both importable regardless of how
pytest was invoked.  Resolved from the root ``pyproject.toml``'s own
``[tool.uv.workspace]`` through
:func:`app.module_loader.workspace_scan_roots` rather than hard-coded, the
same convention ``packages/signal-agent/tests/conftest.py`` follows and for
the same reason: a hard-coded path here could quietly disagree with the
declaration that decides whether the ingest member is on the path at all.

Every test gets a ``DATABASE_URL`` pointing at a test-only database
(``TEST_DATABASE_URL`` when provided, else a throwaway per-test SQLite
file), mirroring the repository-level conftest and the cost-model member's
own: no test can write into the real store, even by accident.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# conftest.py -> packages/router/tests -> packages/router -> packages -> repo root
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

    Mirrors the repository-level conftest and the cost-model member's own:
    ``TEST_DATABASE_URL`` wins when set and non-empty, else a per-test
    SQLite file under pytest's temporary directory.  An empty
    ``TEST_DATABASE_URL`` counts as unset.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV) or (
        f"sqlite:///{tmp_path / 'router-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test, as the code sees it."""
    return _database_url_isolation


@pytest.fixture
def exchange_info_document() -> dict:
    """A minimal, well-formed exchangeInfo document carrying two symbols.

    Shaped exactly as the venue's own wire format
    (``nullius_ingest.exchange_info.parse_exchange_info`` accepts a decoded
    mapping directly), so tests can mutate a copy to explore one specific
    defect rather than hand-writing JSON per test.
    """
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": "0.00001000",
                        "minQty": "0.00001000",
                        "maxQty": "9000.00000000",
                    },
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": "0.01000000",
                        "minPrice": "0.01000000",
                        "maxPrice": "1000000.00000000",
                    },
                    {
                        "filterType": "NOTIONAL",
                        "minNotional": "5.00000000",
                    },
                ],
            },
            {
                "symbol": "ETHUSDT",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": "0.00010000",
                        "minQty": "0.00010000",
                        "maxQty": "9000.00000000",
                    },
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": "0.01000000",
                        "minPrice": "0.01000000",
                        "maxPrice": "1000000.00000000",
                    },
                    {
                        "filterType": "MIN_NOTIONAL",
                        "minNotional": "10.00000000",
                    },
                ],
            },
        ]
    }
