"""The suite's shared constants: code, a request, and a scripted responder.

Imported directly, the way a sibling suite imports a sibling module
(``infra/security/tests/secrets_manager/helpers.py``), so a test file names
the payload it uses and the fixtures in ``conftest.py`` build their objects
from the same place. Nothing here is a secret: feature 150 fixes *where* a
provider call happens and this suite holds no credential and dials nothing.
"""

from __future__ import annotations

from infra.security.provider_boundary import RecordingProviderClient

#: The agent-authored source the conduit carries, as the signal agent writes
#: it (§14.1): a signal function conforming to the declared contract. Not a
#: real signal — the conduit's law is a type check and never reads its
#: payload, so what crosses here is source-shaped text and nothing more.
AGENT_AUTHORED_CODE: str = (
    "def signal(window):\n"
    "    return window['close'].pct_change(24)\n"
)

#: The source the sandbox returns out: what the agent-authored code became
#: inside the run. Deliberately not textually derivable from
#: :data:`AGENT_AUTHORED_CODE` — the point of keeping the conduit's two
#: directions apart is that the code that comes out is a different payload
#: from the code that went in.
SANDBOX_RETURNED_CODE: str = (
    "def signal(window):\n"
    "    return window['close'].pct_change(24).fill_null(0.0)\n"
)

#: A stand-in for a provider request. Its shape belongs to the provider
#: interface (feature 192), not to this boundary — the placement law reads the
#: zone a call was made from and never the request — so the suite carries an
#: opaque object rather than inventing a request schema a later feature would
#: then disagree with.
PROVIDER_REQUEST: object = {"prompt": "propose a signal", "model": "frontier"}


def scripted_provider() -> RecordingProviderClient:
    """A provider client with scripted answers and no transport.

    The responder echoes a normalized-completion-shaped object, which is all
    the boundary needs a response to be: something the orchestrator receives
    and turns into code it sends in. The closure counts its calls so a test
    can assert the responder itself ran, not merely that a client recorded
    something.
    """
    calls = {"n": 0}

    def responder(request: object) -> object:
        calls["n"] += 1
        return {"text": SANDBOX_RETURNED_CODE, "index": calls["n"]}

    client = RecordingProviderClient(responder)
    return client
