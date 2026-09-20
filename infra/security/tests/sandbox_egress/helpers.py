"""The suite's shared vocabulary: the lake, the attempts, and drift.

Imported directly, the way a sibling suite imports a sibling module
(``infra/security/tests/provider_boundary/helpers.py``), so a test file
names the destination it dials and the fixtures in ``conftest.py`` build
their policies from the same place. Nothing here dials anything: the
destinations are the spellings an *attempt* can carry, and every one of
them is answered, never performed.
"""

from __future__ import annotations

from typing import Any

from infra.security.sandbox_egress import POLICY_KIND

#: The lake's name as the committed policy writes it — the spelling an
#: attempt reaches for when it names its destination.
DATA_LAKE_NAME: str = "data-lake"

#: The network the committed policy says the lake lives on — the range
#: an address-shaped attempt is recognized by containment within.
DATA_LAKE_NETWORK: str = "10.8.0.0/24"

#: An address inside the lake's network: the attempt that never says the
#: lake's name but reaches for it all the same, the way a resolver would.
DATA_LAKE_ADDRESS: str = "10.8.0.7"

#: A destination outside the lake — the attempt the default answers.
#: TEST-NET-3, so the suite's example dial-out belongs to nobody.
EXTERNAL_ADDRESS: str = "203.0.113.7"

#: An external destination in name form — the other spelling the default
#: catches.
EXTERNAL_NAME: str = "exchange-api"

#: The destination the live trading zone dials freely (its session
#: broker, feature 156). The contrast the suite leans on: an allowance
#: the trusted zone earns is still a rejection on the sandbox's side.
SESSION_BROKER: str = "session-broker"

#: The Z1 sandboxes the committed policy carries — §3's component map
#: draws both: the signal sandbox and the policy runtime.
SIGNAL_SANDBOX: str = "signal-sandbox"
POLICY_RUNTIME: str = "policy-runtime"

#: The drift every "refuses any allowance" test can start from: one
#: rule, to the lake, on the port a lake-granting edit would reach for
#: first. The grammar is the zone policy's (``destinations``, because
#: the rule dials out), shared with ``network_policy``'s egress half.
LAKE_RULE: dict[str, Any] = {
    "port": 443,
    "protocol": "tcp",
    "destinations": [DATA_LAKE_NAME],
}

#: The drift with nothing narrowed: every port, to everywhere. If any
#: allowance could be granted, this one could; the law refuses it like
#: the rest.
EVERYWHERE_RULE: dict[str, Any] = {
    "port_range": [1, 65535],
    "protocol": "tcp",
    "destinations": ["0.0.0.0/0"],
}


def sandbox_policy_document() -> dict[str, Any]:
    """A well-formed policy document: the lake named, both Z1 sandboxes
    listed, every egress half written and empty — the committed
    artifact's shape, built fresh so a test can drift it without
    touching its siblings' copies."""
    return {
        "policy": POLICY_KIND,
        "data_lake": {
            "name": DATA_LAKE_NAME,
            "addresses": [DATA_LAKE_NETWORK],
        },
        "sandboxes": [
            {"name": SIGNAL_SANDBOX, "egress": []},
            {"name": POLICY_RUNTIME, "egress": []},
        ],
    }


def document_with_egress_rule(
    rule: dict[str, Any], *, sandbox: str = SIGNAL_SANDBOX
) -> dict[str, Any]:
    """A drift document: one sandbox granted one egress rule.

    The whole document is otherwise well-formed, because the law under
    test is not "bad documents are refused" but "a granting document is
    refused *as* a granting document" — the refusal must fire on drift
    that would parse, apply and read as policy if the law were not
    there.
    """
    document = sandbox_policy_document()
    for block in document["sandboxes"]:
        if block["name"] == sandbox:
            block["egress"] = [dict(rule)]
    return document
