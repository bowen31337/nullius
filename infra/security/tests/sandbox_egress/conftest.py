"""Bootstrap and fixtures for feature 149's suite.

``infra/security/`` is deliberately outside the uv workspace's import graph
(policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path the
way its siblings do (``infra/security/tests/provider_boundary/conftest.py``):
the repository root goes on ``sys.path`` and ``infra`` resolves as the PEP 420
namespace package it is — no ``infra/__init__.py`` exists, and none may be
created without leaving the ``infra/security/**`` claim.

The suite holds no network and dials nothing. Feature 149 fixes the posture
of every dial-out a sandbox could make, so the "attempts" here are the gate's
input vocabulary — answered as decisions, never performed — and the policy
documents are dicts compiled in memory or read from the committed artifact.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# `helpers` is imported by its full path, the way the secrets_manager suite
# imports its own (`infra/security/tests/secrets_manager/conftest.py`):
# every sibling suite ships a `helpers.py`, and a bare `from helpers
# import ...` resolves to whichever suite's module was imported first —
# fine alone, wrong the moment two suites run under one pytest.
from infra.security.sandbox_egress import (
    SandboxEgressPolicy,
    committed_sandbox_egress_policy,
    compile_sandbox_egress_policy,
)
from infra.security.tests.sandbox_egress.helpers import (
    sandbox_policy_document,
)


@pytest.fixture()
def policy() -> SandboxEgressPolicy:
    """A compiled policy in the committed document's shape: the lake
    named, both Z1 sandboxes listed, every egress surface empty."""
    return compile_sandbox_egress_policy(sandbox_policy_document())


@pytest.fixture()
def committed() -> SandboxEgressPolicy:
    """The committed artifact, compiled through the same law as any change
    to it would be."""
    return committed_sandbox_egress_policy()
