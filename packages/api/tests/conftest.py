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

import json
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

from nullius_api.auth import API_SCOPES, ApiTokens

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


# -- The token every request now needs (feature 18) -------------------------------
#
# Feature 18 puts a bearer token in front of every route but ``GET
# /healthz``, which means the suites written before it — every one of
# which asked without a header and asserted on the *route's* answer —
# now need a credential to reach the behaviour they are actually about.
# The helpers below are that credential, in one place, so the suites
# share one spelling of a test token rather than ten.
#
# ``TEST_TOKENS`` carries a token for each of the four scopes and is
# built with :meth:`ApiTokens.from_scope_tokens` rather than by hand, so
# the thing the suites authenticate with is the thing the loader
# produces — a fixture that spelled the entries itself could pass while
# the loader's own shape was wrong.

#: The token this suite presents for a given scope, when nothing more
#: specific is wanted.  Deliberately obvious strings: a test token that
#: looked like a real credential would be one more thing to grep for.
TEST_TOKENS = ApiTokens.from_scope_tokens(
    {
        "metrics:read": "test-metrics-token",
        "research": "test-research-token",
        "evaluator": "test-evaluator-token",
        "risk": "test-risk-token",
    },
    source="<the test suite's own token set>",
)


def token_for(scope: str) -> str:
    """The test token carrying ``scope`` — the credential a route needs."""
    for token, carried in TEST_TOKENS.entries:
        if carried == scope:
            return token
    raise AssertionError(f"no test token carries {scope!r}")  # pragma: no cover


#: :data:`TEST_TOKENS` written as the *file* feature 18 reads — scope →
#: list of tokens.  Derived from the token set rather than spelled a
#: second time, so the document a subprocess reads configures exactly
#: the credentials the in-process fixtures present; a second literal
#: could drift from the first and turn a boot test green for the wrong
#: reason.
TOKEN_FILE_DOCUMENT: dict[str, list[str]] = {
    scope: [token_for(scope)] for scope in API_SCOPES
}


def write_token_file(path: Path) -> str:
    """Write :data:`TOKEN_FILE_DOCUMENT` to ``path``; return it as text.

    The file's contents are the suite's own obvious fixture tokens, so
    writing them is safe — the constraint's *tokens are never written to
    a log* is a rule about the server, and a test fixture's credentials
    in a test's temporary directory are not a deployment's secret.
    """
    path.write_text(json.dumps(TOKEN_FILE_DOCUMENT), encoding="utf-8")
    return str(path)


@pytest.fixture
def tokens() -> ApiTokens:
    """The suite's token set, for a server built by hand."""
    return TEST_TOKENS


@pytest.fixture
def token_file(tmp_path: Path) -> str:
    """A token file on disk, as :data:`TOKENS_FILE_ENV` would name it."""
    return write_token_file(tmp_path / "api-tokens.json")


@pytest.fixture
def authorized() -> dict[str, str]:
    """An ``Authorization`` header for every scope, keyed by scope.

    ``authorized["risk"]`` is the header ``POST /risk/halt`` needs, and
    so on — so a test states *which* credential it means rather than
    repeating the ``Bearer`` framing, and a test that wants the wrong
    scope for a route writes ``authorized[OTHER_SCOPE]`` and reads as
    what it is.
    """
    return {
        scope: {"Authorization": f"Bearer {token_for(scope)}"} for scope in API_SCOPES
    }
