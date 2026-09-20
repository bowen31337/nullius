"""Bootstrap for feature 153's suite.

``infra/security/`` is deliberately outside the uv workspace's import
graph (policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path the
way feature 156's suite does (``infra/security/tests/network_isolation/
conftest.py``): the repository root goes on ``sys.path`` and ``infra``
resolves as the PEP 420 namespace package it is — no ``infra/__init__.py``
exists, and none may be created without leaving the ``infra/security/**``
claim.

The suite holds no real key.  Feature 153 classifies a credential by the
environment the exchange stamped into it, never by its material, so the
"keys" here are the environment markers themselves — ``"live"`` and
``"shadow"`` — standing in for the field the exchange issues a key with.
A deployment's real keys are secrets managed out of band (feature 151);
this suite only ever holds the marker a key carries, which is all the
control reads.
"""

from __future__ import annotations

import sys
from pathlib import Path

# infra/security/tests/credential_isolation/conftest.py -> .../tests ->
# .../security -> infra -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infra.security.credential_isolation import (
    LIVE_SCOPE,
    SHADOW_SCOPE,
    UNAUTHORIZED,
)

#: The shadow sub-account's key, as the exchange stamped it — the marker
#: "shadow", standing in for the field the exchange issues a shadow key
#: with.  Not a real key: feature 153 reads the environment a key carries,
#: never its material, so the suite holds only the marker.
SHADOW_KEY: str = SHADOW_SCOPE

#: The live account's key — the marker "live".  The "other environment" of
#: the refusal tests, and the environment the live execution path
#: authenticates with.
LIVE_KEY: str = LIVE_SCOPE

#: The HTTP status the exchange answers a cross-environment presentation
#: with — feature 153's "401" verbatim.  The suite asserts the policy-side
#: double of this (:class:`ScopeMismatch`) is what a caller raises before
#: the request reaches the wire.
STATUS_UNAUTHORIZED: int = UNAUTHORIZED
