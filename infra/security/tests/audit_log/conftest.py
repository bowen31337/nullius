"""Bootstrap and fixtures for feature 154's suite.

``infra/security/`` is deliberately outside the uv workspace's import
graph (policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path
the way feature 156's and feature 155's suites do
(``infra/security/tests/key_backup/conftest.py``): the repository root
goes on ``sys.path`` and ``infra`` resolves as the PEP 420 namespace
package it is — no ``infra/__init__.py`` exists, and none may be created
without leaving the ``infra/security/**`` claim.

Three fixtures matter, and they are the three the feature's contracts
are about:

* **the key is never a real one.**  :data:`KEY_MATERIAL` is a fixed,
  obviously-test 32 bytes; no test audits the read of a deployment's
  key, and every assertion about "the key came back" is really an
  assertion that the same bytes went in and came out.
* **the accounts are obviously fake.**  :data:`GRANTED_ACCOUNT` and
  :data:`FOREIGN_ACCOUNT` name a service account the suite invents, so
  a test that reads the key "as the right account" is testing the
  comparison and not a host's real identity.
* **the logs are never in a real place.**  :class:`FileAuditSink` paths
  point into pytest's temporary directory, so a suite that writes an
  audit line writes it nowhere a deployment's real log lives — the
  exact accident this member exists to make impossible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# infra/security/tests/audit_log/conftest.py -> .../tests -> .../security -> infra -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infra.security.audit_log import (
    AuditLog,
    FileAuditSink,
    InMemoryAuditSink,
    KeyReadAudit,
)

#: A fixed 32-byte key, standing in for the null sidecar key.
KEY_MATERIAL: bytes = bytes(range(32))

#: The one service account the key is granted to — unmistakably a test value.
GRANTED_ACCOUNT: str = "nulloracle-svc-test"

#: A second, equally fake account — the "foreign caller" of the refusal tests.
FOREIGN_ACCOUNT: str = "someone-else-test"

#: A reference in the spec's own ``kms:`` spelling, standing in for
#: ``NULL_SIDECAR_KEY_REF``.  Its *target* is the part that must never reach
#: the log, so it is spelled as something no assertion would accidentally
#: match for a benign reason.
KMS_REFERENCE: str = "kms:arn:aws:kms:us-east-1:000000000000:key/test-key-id"

#: A ``hex:`` reference whose target *is* the key — the leak the redaction
#: exists to prevent.  Not :data:`KEY_MATERIAL`'s hex, so a test can assert
#: the log holds neither the key bytes nor the reference's target.
HEX_REFERENCE: str = "hex:" + bytes(range(32)).hex()


@pytest.fixture
def key_material() -> bytes:
    """The 32-byte key material standing in for the sidecar key."""
    return KEY_MATERIAL


@pytest.fixture
def kms_reference() -> str:
    """A ``kms:`` reference — the spec's own spelling, target and all."""
    return KMS_REFERENCE


@pytest.fixture
def hex_reference() -> str:
    """A ``hex:`` reference whose target *is* the key — the leak to prevent."""
    return HEX_REFERENCE


@pytest.fixture
def granted_account() -> str:
    """The one service account the key is granted to."""
    return GRANTED_ACCOUNT


@pytest.fixture
def foreign_account() -> str:
    """A second account — the requester of every refusal test."""
    return FOREIGN_ACCOUNT


@pytest.fixture
def mem_sink() -> InMemoryAuditSink:
    """An in-memory audit sink — the fast double of the real thing."""
    return InMemoryAuditSink("memory")


@pytest.fixture
def mem_log(mem_sink: InMemoryAuditSink) -> AuditLog:
    """An audit log over the in-memory sink."""
    return AuditLog(mem_sink)


@pytest.fixture
def granted_audit(mem_log: AuditLog, granted_account: str) -> KeyReadAudit:
    """A chokepoint reading as the granted account — the expected case."""
    return KeyReadAudit(
        mem_log,
        granted_account=granted_account,
        account=granted_account,
        reference=KMS_REFERENCE,
    )


@pytest.fixture
def file_sink(tmp_path: Path) -> FileAuditSink:
    """A file sink in pytest's temporary directory — the real thing.

    A real newline-delimited JSON file, never a deployment's log: the suite
    that exercises the durable sink writes it where nothing real lives.
    """
    return FileAuditSink("file", tmp_path / "audit" / "sidecar-key.jsonl")
