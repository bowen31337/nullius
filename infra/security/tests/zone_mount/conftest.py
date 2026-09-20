"""Bootstrap and fixtures for feature 147's suite.

``infra/security/`` is deliberately outside the uv workspace's import graph
(policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path the
way its siblings do (``infra/security/tests/sandbox_egress/conftest.py``):
the repository root goes on ``sys.path`` and ``infra`` resolves as the PEP 420
namespace package it is — no ``infra/__init__.py`` exists, and none may be
created without leaving the ``infra/security/**`` claim.

The suite holds a sealed on-disk tree and mounts it read-only, but opens no
write handle: feature 147 fixes the posture of every write a service could
attempt against the immutable zone, so the "attempts" here are the mount's
and the gate's input vocabulary — answered as refusals and decisions, never
performed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# `helpers` is imported by its full namespace path, the way every sibling
# suite imports its own (`infra/security/tests/sandbox_egress/conftest.py`):
# each suite ships a `helpers.py`, and a bare `from helpers import ...`
# resolves to whichever suite's module was imported first — fine alone,
# wrong the moment two suites run under one pytest.
from infra.security.tests.zone_mount.helpers import sealed_zone_tree
from infra.security.zone_mount import (
    ReadonlyZoneMount,
    mount_geometry,
)


@pytest.fixture()
def mount() -> ReadonlyZoneMount:
    """A read-only mount over a sealed on-disk tree in the committed
    geometry: the six zone members, both under the mount point."""
    return ReadonlyZoneMount.for_directory(sealed_zone_tree())


@pytest.fixture()
def committed_mount() -> ReadonlyZoneMount:
    """The committed mount, served from the sealed tree through the same
    geometry the deployment runs with."""
    return ReadonlyZoneMount.for_directory(
        sealed_zone_tree(), geometry=mount_geometry()
    )
