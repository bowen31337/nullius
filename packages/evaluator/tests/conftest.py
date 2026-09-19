"""Suite-local fixtures for the evaluator package's tests.

This suite lives inside the workspace member (``packages/evaluator/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures in
``tests/conftest.py`` do not reach it — conftest scope follows directories.
The isolation those shared fixtures guarantee is reproduced here: a fresh
SQLite database per test with ``DATABASE_URL`` pointed at it, so no test can
write an ``evaluator_identity`` row into a real database, and adjacent tests
never share one.

The path bootstrap below puts the member's ``src/`` on ``sys.path`` — the
same mechanism the module loader uses when it scans members — because the
root project does not depend on this member and the venv therefore does not
install it; this suite runs with the repository's pytest
(``uv run --all-packages pytest packages/evaluator``).

The environment fixtures are deliberately *explicit* rather than autouse:
the evaluator member's whole point is that it refuses to invent a pinned
image, so a suite that silently supplied one would hide the refusal it
exists to pin. Tests that want a working service ask for
:func:`evaluator_env`, and the tests that assert the refusal ask for nothing
and get the bare environment.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

#: A digest-pinned reference, spelled out rather than computed so the tests
#: that assert on it are readable. ``ab`` repeated 32 times is a valid sha256
#: hex digest of the right width; nothing here needs it to be a real image.
PINNED_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32
PINNED_DIGEST = "sha256:" + "ab" * 32

#: A second, different digest — the "the image moved" case of §15's failure
#: table, which is what a cross-hash comparison refusal exists to catch.
OTHER_PINNED_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "cd" * 32
OTHER_PINNED_DIGEST = "sha256:" + "cd" * 32


@pytest.fixture(autouse=True)
def _database_url_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Point ``DATABASE_URL`` at a test-only database for every test.

    A per-test SQLite file rather than ``sqlite://`` (in-memory): an
    in-memory database is per-*connection*, so a row written by one
    connection is invisible to the next — which would make an idempotency
    assertion pass or fail depending on how the store happened to pool, not
    on whether the store is correct.
    """
    url = os.environ.get("TEST_DATABASE_URL") or (
        f"sqlite:///{tmp_path / 'evaluator-test.db'}"
    )
    monkeypatch.setenv("DATABASE_URL", url)
    return url


@pytest.fixture(autouse=True)
def _image_env_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the evaluator environment before every test.

    The member reads ``NULLIUS_EVALUATOR_IMAGE`` (the pinned image) and
    ``NULLIUS_EVALUATOR_CONFIG`` (the operator's override) from the process,
    so a developer shell that carries either would leak into every assertion
    below. Clearing them makes each test state the environment it needs, and
    makes the "unset image is refused" tests honest rather than dependent on
    the shell not having one.
    """
    monkeypatch.delenv("NULLIUS_EVALUATOR_IMAGE", raising=False)
    monkeypatch.delenv("NULLIUS_EVALUATOR_CONFIG", raising=False)


@pytest.fixture
def evaluator_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A complete, working evaluator environment.

    ``NULLIUS_EVALUATOR_IMAGE`` pinned to :data:`PINNED_IMAGE`, with
    ``DATABASE_URL`` already isolated by the autouse fixture. Returned as a
    mapping so a test can assert against the exact values it configured, and
    so a test can pass the same mapping to a service instead of relying on
    the process — the two spellings must agree, which is what the service's
    ``env`` parameter is for.
    """
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", PINNED_IMAGE)
    return {
        "NULLIUS_EVALUATOR_IMAGE": PINNED_IMAGE,
        "DATABASE_URL": os.environ["DATABASE_URL"],
    }
