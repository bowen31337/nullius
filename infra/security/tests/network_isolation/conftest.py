"""Bootstrap and fixtures for feature 156's suite.

``infra/security/`` is deliberately outside the uv workspace's import
graph (policy that guards the zones must not be composition code —
see ``infra/security/__init__.py``), so this suite bootstraps its own
path the way the plugin suites do (``tests/feature-store/conftest.py``):
the repository root goes on ``sys.path`` and ``infra`` resolves as the
PEP 420 namespace package it is — no ``infra/__init__.py`` exists, and
none may be created without leaving the ``infra/security/**`` claim.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from infra.security import (  # noqa: E402  (path bootstrap must precede it)
    SessionBroker,
    committed_zone_policy,
)


@pytest.fixture()
def live_zone():
    """The committed live-trading zone, compiled through the law.

    Every test that wants "the zone as shipped" compiles the committed
    document exactly as
    :func:`infra.security.network_policy.committed_zone_policy` does —
    no test hand-builds the zone it then certifies.
    """
    return committed_zone_policy()


@pytest.fixture()
def broker_with_live_session():
    """A broker holding one live session to ``live-trading-1``.

    The establishment order the mechanism dictates: the host dials out
    and registers its channel, then the operator attaches to what was
    registered.  Returns ``(broker, session)``.
    """
    broker = SessionBroker()
    channel = broker.register_host_channel("live-trading-1")
    session = broker.attach(channel, operator="on-call")
    return broker, session
