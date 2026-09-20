"""Bootstrap and fixtures for feature 150's suite.

``infra/security/`` is deliberately outside the uv workspace's import graph
(policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path the way
its siblings do (``infra/security/tests/credential_isolation/conftest.py``):
the repository root goes on ``sys.path`` and ``infra`` resolves as the PEP 420
namespace package it is — no ``infra/__init__.py`` exists, and none may be
created without leaving the ``infra/security/**`` claim.

The suite holds no provider credential and dials nothing. Feature 150 fixes
*where* the provider call happens, so the "provider" here is
:class:`~infra.security.provider_boundary.RecordingProviderClient` — scripted
answers, a record of what reached it, and no transport at all. A deployment's
real client subclasses the same seam with its HTTP transport, and the law it
inherits is the one this suite asserts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from helpers import scripted_provider

from infra.security.provider_boundary import (
    CodeChannel,
    Orchestrator,
    RecordingProviderClient,
)


@pytest.fixture()
def recording_provider() -> RecordingProviderClient:
    """A provider client with scripted answers and no transport."""
    return scripted_provider()


@pytest.fixture()
def channel() -> CodeChannel:
    """A fresh conduit: nothing sent in, nothing returned out."""
    return CodeChannel()


@pytest.fixture()
def orchestrator(recording_provider: RecordingProviderClient) -> Orchestrator:
    """The trusted side, holding the recording client and its own conduit."""
    return Orchestrator(recording_provider)
