"""Fixtures for the artifacts member's own suite.

This suite lives inside the workspace member (``packages/artifacts/
tests``) rather than under the repository-level ``tests/`` tree,
because the member — including its tests — is this feature's file-claim
scope.  The repository-level ``tests/conftest.py`` therefore does not
reach it (conftest scope follows directories), so the isolation its
fixtures guarantee is mirrored here, not invented:

* **no test ever writes into a real artifact store.**  ``ARTIFACT_ROOT``
  is pointed at a fresh temporary root for every test, autouse, because
  the store's configured default is ``artifacts/`` beside the workspace
  root — a suite that only *sometimes* redirected the root would leave
  every other test persisting node directories into the checkout.  The
  members with a path-configured component (the snapshot service's
  ``LAKE_ROOT``, the sidecar's ``NULL_SIDECAR_PATH``) redirect theirs
  the same way.
* **no test needs a database.**  Feature 169 is the directory half of
  §9.2 — pure filesystem work — so unlike the snapshot and evaluator
  suites this conftest isolates no ``DATABASE_URL``; when the record-
  writing features of this category (169's dependants) arrive with a
  store to write, their suites add the fixture then, mirroring the
  repository conftest rather than guessing at it now.

The path bootstrap below puts both import roots on ``sys.path``
regardless of how pytest was invoked: the workspace's ``src/`` (for
``app.module_loader``, which the component registration imports) and
this member's ``src/`` (for ``artifacts`` itself).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

# conftest.py -> packages/artifacts/tests -> packages/artifacts -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "artifacts" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from artifacts import ARTIFACT_ROOT_ENV, ArtifactStore


@pytest.fixture(autouse=True)
def _artifact_root_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point ``ARTIFACT_ROOT`` at a fresh temporary root for every test.

    Autouse and unconditional: the default root is beside the workspace
    root, so a test that never requested a fixture would otherwise be
    the one test persisting node directories into the checkout.
    """
    root = tmp_path / "artifacts"
    root.mkdir()
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(root))
    return root


@pytest.fixture
def artifact_root(_artifact_root_isolation: Path) -> Path:
    """The temporary artifact root for this test."""
    return _artifact_root_isolation


@pytest.fixture
def store(artifact_root: Path) -> ArtifactStore:
    """A store bound to this test's isolated root, as the environment names it.

    Resolved through :meth:`ArtifactStore.from_env` — the same path the
    composed application's builder takes — rather than constructed
    directly, so every test also exercises the environment binding the
    deployment actually uses.
    """
    return ArtifactStore.from_env()


@pytest.fixture
def campaign_id() -> str:
    """A fresh canonical UUID for a campaign under test."""
    return str(uuid.uuid4())


@pytest.fixture
def node_id() -> str:
    """A fresh canonical UUID for a node under test."""
    return str(uuid.uuid4())


@pytest.fixture
def other_node_id() -> str:
    """A second, equally fresh node of the same campaign."""
    return str(uuid.uuid4())


@pytest.fixture
def other_campaign_id() -> str:
    """A second campaign, for the tests that key the two levels apart."""
    return str(uuid.uuid4())
