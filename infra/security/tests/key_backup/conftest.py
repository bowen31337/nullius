"""Bootstrap and fixtures for feature 155's suite.

``infra/security/`` is deliberately outside the uv workspace's import
graph (policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path the
way feature 156's suite does (``infra/security/tests/network_isolation/
conftest.py``): the repository root goes on ``sys.path`` and ``infra``
resolves as the PEP 420 namespace package it is — no ``infra/__init__.py``
exists, and none may be created without leaving the ``infra/security/**``
claim.

Two fixtures matter, and they are the two the feature's contracts are about:

* **the seal secret is never a real one.**  :data:`SEAL_SECRET` is a
  fixed, obviously-test value; no test seals under a deployment's secret,
  and the tests that assert "the wrong secret will not open it" use a
  second equally-fake one.  The seal secret is a deployment secret managed
  out of band; the suite only ever holds fakes.
* **the stores are never in a real place.**  :class:`FileBackupStore`
  paths point into pytest's temporary directory, so a suite that holds the
  sealed sidecar key writes it nowhere a deployment's real backup lives —
  the exact accident this member exists to make impossible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# infra/security/tests/key_backup/conftest.py -> .../tests -> .../security -> infra -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infra.security.key_backup import (
    FileBackupStore,
    InMemoryBackupStore,
    KeyBackup,
    SealedKeyBackup,
)

#: A fixed, obviously-not-real seal secret.  The seal secret that locks a
#: backup is a deployment secret managed out of band; the suite holds only
#: fakes, and every assertion about "the right secret opens it" is really an
#: assertion that the same bytes were used twice.
SEAL_SECRET: bytes = b"test-seal-secret-do-not-use-in-prod-!"

#: A different, equally-fake seal secret — the "wrong secret" of the refusal tests.
OTHER_SEAL_SECRET: bytes = b"another-test-seal-secret-not-real-!!"

#: A fixed 32-byte key material, standing in for the AES-256 sidecar key.
KEY_MATERIAL: bytes = bytes(range(32))


@pytest.fixture
def seal_secret() -> bytes:
    """The seal secret behind :data:`SEAL_SECRET`."""
    return SEAL_SECRET


@pytest.fixture
def other_secret() -> bytes:
    """A different, equally-fake seal secret."""
    return OTHER_SEAL_SECRET


@pytest.fixture
def key_material() -> bytes:
    """The 32-byte key material standing in for the sidecar key."""
    return KEY_MATERIAL


@pytest.fixture
def backup() -> SealedKeyBackup:
    """A sealed backup of :data:`KEY_MATERIAL` under :data:`SEAL_SECRET`."""
    return SealedKeyBackup.seal(KEY_MATERIAL, SEAL_SECRET)


@pytest.fixture
def other_material() -> bytes:
    """A second, distinct 32-byte key — the "different key" of the mismatch tests."""
    return bytes(range(1, 33))


@pytest.fixture
def two_stores(tmp_path: Path):
    """Two independent file stores in two directories — the real thing.

    The establishment order the feature demands: two file stores in two
    distinct directories, so they are independent by the independence
    check (distinct ``store_id``) and a loss of one is survived by the
    other.  Returns ``(stores, key_backup)``.
    """
    stores = (
        FileBackupStore("kms", tmp_path / "kms" / "sidecar-key.bak"),
        FileBackupStore("sops", tmp_path / "sops" / "sidecar-key.age"),
    )
    return stores, KeyBackup()


@pytest.fixture
def mem_stores():
    """Two independent in-memory stores — the fast double of the real thing.

    Two :class:`InMemoryBackupStore` handles with distinct names.  They are
    independent by name (distinct ``store_id``), so the two-store rule and
    the reconciliation exercise the real logic through them; they are
    in-memory, so the suite stays hermetic and nothing touches a disk.
    """
    stores = (
        InMemoryBackupStore("store-a"),
        InMemoryBackupStore("store-b"),
    )
    return stores, KeyBackup()
