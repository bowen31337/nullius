"""Bootstrap and fixtures for feature 148's suite.

``infra/security/`` is deliberately outside the uv workspace's import graph
(policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path the
way its siblings do (``infra/security/tests/sandbox_egress/conftest.py``):
the repository root goes on ``sys.path`` and ``infra`` resolves as the PEP 420
namespace package it is — no ``infra/__init__.py`` exists, and none may be
created without leaving the ``infra/security/**`` claim.

The suite opens no file and issues no credential.  Feature 148 is the grant
the loop's components run under, so the "attempts" here are the gate's
input vocabulary — answered as decisions, never performed — and the grant
documents are dicts compiled in memory or read from the committed artifact.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# `helpers` is imported by its full namespace path, the way every sibling
# suite imports its own (`infra/security/tests/sandbox_egress/helpers.py`):
# each suite ships a `helpers.py`, and a bare `from helpers import ...`
# resolves to whichever suite's module was imported first — fine alone,
# wrong the moment two suites run under one pytest.
from infra.security.loop_credentials import (
    LoopCredentialPolicy,
    committed_loop_credential_policy,
    compile_loop_credential_policy,
)
from infra.security.tests.loop_credentials.helpers import grant_document


@pytest.fixture()
def policy() -> LoopCredentialPolicy:
    """A compiled grant in the committed document's shape: the zone
    pinned by its six members, both Z1 components listed, every write
    capability outside the zone."""
    return compile_loop_credential_policy(grant_document())


@pytest.fixture()
def committed() -> LoopCredentialPolicy:
    """The committed artifact, compiled through the same law as any
    change to it would be."""
    return committed_loop_credential_policy()
