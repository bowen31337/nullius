"""Bootstrap for feature 152's suite.

``infra/security/`` is deliberately outside the uv workspace's import
graph (policy that guards the zones must not be composition code — see
``infra/security/__init__.py``), so this suite bootstraps its own path the
way feature 153's suite does
(``infra/security/tests/credential_isolation/conftest.py``): the
repository root goes on ``sys.path`` and ``infra`` resolves as the PEP 420
namespace package it is — no ``infra/__init__.py`` exists, and none may be
created without leaving the ``infra/security/**`` claim.

The suite holds no key material. Feature 152 validates the permission
*set* an exchange stamped onto a key and the account-side withdrawal
state, never the key's bytes, so the fixtures here are permission names and
a boolean — the two facts the control reads. A deployment's real keys are
secrets managed out of band (§17, feature 151).
"""

from __future__ import annotations

import sys
from pathlib import Path

# infra/security/tests/exchange_keys/conftest.py -> .../tests ->
# .../security -> infra -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infra.security.exchange_keys import (  # noqa: E402
    PROVISIONED_PERMISSIONS,
    READ_PERMISSION,
    TRADE_PERMISSION,
    WITHDRAW_PERMISSION,
)

#: The set the exchange stamps onto a correctly provisioned key, as an
#: ordered tuple so a test can spell it the way an operator would.
READ_AND_TRADE: tuple[str, ...] = (READ_PERMISSION, TRADE_PERMISSION)

#: The same set with the permission §17 forbids — the key an operator
#: would get by asking the exchange for everything the console offers.
READ_TRADE_AND_WITHDRAW: tuple[str, ...] = (
    READ_PERMISSION,
    TRADE_PERMISSION,
    WITHDRAW_PERMISSION,
)

#: The account-side switch as the exchange stamps it: off (compliant) and
#: on (the feature's "otherwise").
WITHDRAWAL_OFF: bool = True
WITHDRAWAL_ON: bool = False

#: The label a provisioning script would use for the execution path's key.
EXECUTION_KEY_LABEL: str = "live-execution"

__all__ = [
    "EXECUTION_KEY_LABEL",
    "PROVISIONED_PERMISSIONS",
    "READ_AND_TRADE",
    "READ_PERMISSION",
    "READ_TRADE_AND_WITHDRAW",
    "TRADE_PERMISSION",
    "WITHDRAWAL_OFF",
    "WITHDRAWAL_ON",
    "WITHDRAW_PERMISSION",
]
