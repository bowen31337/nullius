"""Fixtures for the nulloracle member's own suite.

This suite lives inside the package (``packages/nulloracle/tests``) rather
than under the repository-level ``tests/`` tree, because the package —
including its tests — is this feature's file-claim scope.  The
repository-level ``tests/conftest.py`` therefore does not apply here (pytest
loads conftests along the collected path only), so the workspace isolation
guarantees this member needs are mirrored, not invented.

Two of them matter, and they are the two the sidecar's own contracts are
about:

* **the key is never a real one.**  ``NULL_SIDECAR_KEY_REF`` is set per test
  to a freshly generated ``hex:`` reference, so no test can seal anything
  under a deployment's key.  The variable is *unset* by default and set only
  where a test wants a working sidecar, because "the environment names no
  key" is itself a state several tests below are about.
* **the sidecar is never in the real lake.**  ``NULL_SIDECAR_PATH`` points
  into pytest's temporary directory, and ``LAKE_ROOT`` is redirected the way
  the repository conftest redirects it.  §7.1's file holds the null labels;
  a suite that wrote one into a real ``/z0/null/`` would be the exact
  accident this whole member exists to make impossible.

The path bootstrap makes both import roots visible regardless of how pytest
was invoked: the workspace's ``src/`` (for ``app.module_loader``, which the
component registration imports) and this member's ``src/`` (for
``nulloracle`` itself).
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

# tests/conftest.py -> packages/nulloracle/tests -> packages/nulloracle -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "nulloracle" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from nulloracle import (  # noqa: E402
    KEY_REF_ENV,
    SIDECAR_PATH_ENV,
    SERVICE_ACCOUNT_ENV,
    NullSidecar,
    SidecarKey,
)

LAKE_ROOT_ENV = "LAKE_ROOT"

#: A fixed 32-byte key for the tests that need one to be *the same* across
#: two constructions.  Not a secret and not derived from anything: it is the
#: test suite's own key, and every assertion about "the right key opens it"
#: is really an assertion that the same bytes were used twice.
TEST_KEY_HEX = "0f" * 32


@pytest.fixture(autouse=True)
def _clean_key_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no sidecar configuration at all.

    Autouse and unconditional, so the default state of a test is the state a
    deployment has before anyone configures it.  Tests that want a working
    sidecar opt in through ``sidecar_path``/``key_ref``/``test_sidecar``;
    tests that want to assert on the *unconfigured* behaviour (composing no
    component, resolving nothing) then do not have to fight a fixture that
    helpfully configured one behind their back.
    """
    for name in (KEY_REF_ENV, SIDECAR_PATH_ENV, SERVICE_ACCOUNT_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _lake_root_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point ``LAKE_ROOT`` at a fresh temporary lake for every test.

    Mirrors the repository-level conftest: the lake exists with its standard
    ``snapshots/`` and ``staging/`` subdirectories, so a test asserting on
    the sidecar's *default* location (``<lake>/null/sidecar.enc``) has a real
    root to resolve against and never reaches the project's own lake.
    """
    root = tmp_path / "lake"
    (root / "snapshots").mkdir(parents=True)
    (root / "staging").mkdir()
    monkeypatch.setenv(LAKE_ROOT_ENV, str(root))
    return root


@pytest.fixture
def lake_root(_lake_root_isolation: Path) -> Path:
    """The temporary lake root for this test."""
    return _lake_root_isolation


@pytest.fixture
def key_ref(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure a ``hex:`` key reference for this test."""
    reference = f"hex:{TEST_KEY_HEX}"
    monkeypatch.setenv(KEY_REF_ENV, reference)
    return reference


@pytest.fixture
def sidecar_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure ``NULL_SIDECAR_PATH`` at a path under this test's tmpdir."""
    path = tmp_path / "z0" / "null" / "sidecar.enc"
    monkeypatch.setenv(SIDECAR_PATH_ENV, str(path))
    return path


@pytest.fixture
def test_key() -> SidecarKey:
    """The :class:`SidecarKey` behind :data:`TEST_KEY_HEX`."""
    return SidecarKey.from_hex(TEST_KEY_HEX)


@pytest.fixture
def other_key() -> SidecarKey:
    """A different, equally valid key — the "wrong key" of the refusal tests."""
    return SidecarKey.from_hex("1e" * 32)


@pytest.fixture
def test_sidecar(
    sidecar_path: Path, key_ref: str, test_key: SidecarKey
) -> NullSidecar:
    """A sidecar bound to this test's isolated path and key.

    Constructed directly rather than through :meth:`NullSidecar.resolve`, so
    a test can hold the path and the key without the resolution path under
    test also being involved.  Construction performs no I/O — the directory
    appears on the first write — so requesting this fixture is safe in a test
    that never writes anything.
    """
    return NullSidecar(sidecar_path, test_key)


@pytest.fixture
def node_id() -> str:
    """A fresh canonical UUID for a node under test."""
    return str(uuid.uuid4())


@pytest.fixture
def node_ids() -> "callable":
    """A factory for ``n`` distinct canonical UUIDs."""

    def _make(count: int) -> list[str]:
        return [str(uuid.uuid4()) for _ in range(count)]

    return _make


@pytest.fixture
def uid_named() -> "callable":
    """Whether this host can resolve a uid to a login name.

    The ownership check in :meth:`NullSidecar._assert_readable` is skipped
    when a uid has no passwd entry (a container running under a bare numeric
    uid), so the one test that pins that check must know whether the check
    can run at all here — otherwise it would be a test that passes for the
    wrong reason on some hosts and fails on others.
    """
    import pwd

    def _can(uid: int) -> bool:
        try:
            pwd.getpwuid(uid)
        except (KeyError, OSError):
            return False
        return True

    return _can


@pytest.fixture
def env_snapshot() -> dict[str, str]:
    """A dict of the environment variables this member reads, as the code sees them."""
    names = (KEY_REF_ENV, SIDECAR_PATH_ENV, SERVICE_ACCOUNT_ENV, LAKE_ROOT_ENV)
    return {name: os.environ[name] for name in names if name in os.environ}
