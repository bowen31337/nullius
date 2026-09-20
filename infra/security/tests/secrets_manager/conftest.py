"""Bootstrap for feature 151's suite.

``infra/security/`` is deliberately outside the uv workspace's import graph
(policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path the
way feature 152's suite does (``infra/security/tests/exchange_keys/conftest.py``):
the repository root goes on ``sys.path`` and ``infra`` resolves as the PEP 420
namespace package it is — no ``infra/__init__.py`` exists, and none may be
created without leaving the ``infra/security/**`` claim.

The suite holds no real credential. Feature 151's subject is the *store's
contract and its one refusal* — whether a value it holds is byte-for-byte a
line a committed environment file holds — so the fixtures are placeholder
values (``"sk-live-abc123"``-style strings, never a real key) and a throwaway
git repository the committed-file check is exercised against. A deployment's
real exchange credentials live in a real secrets manager, managed out of band
(§17); what is tested here is the law, not a secret.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# infra/security/tests/secrets_manager/conftest.py -> .../tests ->
# .../security -> infra -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infra.security.secrets_manager import (
    REPO_ROOT_ENV,
    InMemorySecretsStore,
)
from infra.security.tests.secrets_manager.helpers import GitRepo

#: A placeholder exchange credential — the shape of a value a deployment
#: would put in its secrets manager, never a real key. Feature 151 compares
#: values, so the fixture is a value, and a fake one. The committed-env
#: fixture commits exactly this value, so a store holding it refuses the read.
EXCHANGE_KEY_VALUE: str = "sk-live-abc123"

#: The label a provisioning script would store the execution key under.
EXCHANGE_KEY_LABEL: str = "live-execution-key"


@pytest.fixture
def exchange_key_value() -> str:
    """A placeholder exchange credential value — the shape of a real secret,
    never a real one. Feature 151 compares values, so the fixture is a value."""
    return EXCHANGE_KEY_VALUE


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    """A throwaway git repository, committed-into and pointed-at by the store.

    Function-scoped: each test gets its own repository in its own ``tmp_path``
    directory, so a commit in one test cannot leak into another — the
    committed-file check reads the real git tree, and a shared tree would make
    one test's committed credential another test's surprise. It lives in its
    own ``tmp_path / "repo"`` directory — isolated from the test's own tree,
    which is inside the nullius repository and must not be read into the
    committed-file check.
    """
    root = tmp_path / "repo"
    root.mkdir()
    return GitRepo(root)


@pytest.fixture
def store(repo: GitRepo) -> InMemorySecretsStore:
    """An in-memory store pointed at ``repo`` — the committed check's real home."""
    return InMemorySecretsStore(repo_root=repo.root)


@pytest.fixture
def committed_env(repo: GitRepo) -> Path:
    """A committed ``.env`` holding :data:`EXCHANGE_KEY_VALUE`, plus the stored value.

    The feature's exact scenario: an exchange credential written to an env
    file and committed, then stored under :data:`EXCHANGE_KEY_LABEL`. The
    store's read of that label is the read feature 151 refuses.
    """
    env_file = repo.write(
        ".env",
        f"# exchange credentials — DO NOT COMMIT\nEXCHANGE_KEY={EXCHANGE_KEY_VALUE}\n",
    )
    repo.commit("Add env file (by mistake)")
    return env_file


__all__ = [
    "EXCHANGE_KEY_LABEL",
    "EXCHANGE_KEY_VALUE",
    "GitRepo",
    "committed_env",
    "repo",
    "store",
]
