"""The suite's shared vocabulary: the zone, the grant, and the drift.

Imported by its full namespace path, the way every sibling suite imports
its own (``infra/security/tests/sandbox_egress/helpers.py``) — see the
collision note in this suite's ``conftest.py``.  The constants below are
the spellings the tests aim attempts and write drift in: the zone's
members as the committed policy pins them, the places the grant really
holds, and the hostile shapes a write attempt can arrive in.  Nothing
here opens a file; every path is a string the gate answers, never a
place a test touches.
"""

from __future__ import annotations

import copy
from typing import Any

from infra.security.loop_credentials import POLICY_KIND

#: The immutable zone's name, as the committed policy writes it.
ZONE_NAME: str = "z0-immutable"

#: The zone's member roots in document order — the deployment's
#: spelling of §2's Z0 contents: the snapshots, the evaluator, the cost
#: model, the contract, the null oracle, the trial ledger.
ZONE_SNAPSHOTS: str = "/zones/z0/snapshots"
ZONE_EVALUATOR: str = "/zones/z0/evaluator"
ZONE_COST_MODEL: str = "/zones/z0/cost-model"
ZONE_CONTRACT: str = "/zones/z0/contract"
ZONE_NULLORACLE: str = "/zones/z0/nulloracle"
ZONE_TRIAL_LEDGER: str = "/zones/z0/trial-ledger"
ZONE_PATHS: tuple[str, ...] = (
    ZONE_SNAPSHOTS,
    ZONE_EVALUATOR,
    ZONE_COST_MODEL,
    ZONE_CONTRACT,
    ZONE_NULLORACLE,
    ZONE_TRIAL_LEDGER,
)

#: The zone's parent directory — the covering grant the law refuses: a
#: capability on the parent reaches every child.
ZONE_PARENT: str = "/zones/z0"

#: The zones' shared parent — a wider covering grant, same refusal.
ZONES_ROOT: str = "/zones"

#: The filesystem root — the widest covering grant the path vocabulary
#: can even name.
FILESYSTEM_ROOT: str = "/"

#: A place whose spelling begins like the zone's but is a neighbour,
#: not a member: segment-wise containment must say outside.
ZONE_NEIGHBOUR: str = "/zones/z0-sidecar"

#: Deep places inside zone members — the shapes real attempts aim at.
SNAPSHOT_FILE: str = "/zones/z0/snapshots/2024/w42.parquet"
EVALUATOR_IMAGE: str = "/zones/z0/evaluator/image@sha256:deadbeef"
SIDECAR_KEY: str = "/zones/z0/nulloracle/sidecar.key"
TRIAL_LEDGER_DB: str = "/zones/z0/trial-ledger/trials.db"

#: The traversal-shaped spelling of a zone place: resolves into the
#: null oracle's member whatever order the segments were typed in.
TRAVERSAL_SIDECAR: str = "/zones/z0/../z0/nulloracle/sidecar.key"

#: The trailing-slash spelling of a member root — the same place.
TRAILING_SLASH_LEDGER: str = "/zones/z0/trial-ledger/"

#: The loop-mutated components — §3's component map draws exactly these
#: two Z1 boxes, the same membership feature 149's committed egress
#: policy carries.
SIGNAL_SANDBOX: str = "signal-sandbox"
POLICY_RUNTIME: str = "policy-runtime"

#: The credential names the baseline grant issues.
SIGNAL_ROLE: str = "signal-sandbox-role"
POLICY_ROLE: str = "policy-runtime-role"

#: The Z1 work areas the grant really holds — its genuine write
#: capabilities, the contrast that makes the law a law.
WORK_AREA_SIGNAL: str = "/zones/z1/signal-sandbox/work"
WORK_AREA_POLICY: str = "/zones/z1/policy-runtime/work"

#: The Z3 artifact drops where proposed code lands.
ARTIFACT_DROP_SIGNAL: str = "/zones/z3/artifacts/signal"
ARTIFACT_DROP_POLICY: str = "/zones/z3/artifacts/policy"

#: A place outside both the zone and the grant — the attempt that falls
#: to the consultation's floor.
UNGRANTED_PLACE: str = "/etc/passwd"

#: An operation name the closed vocabulary does not carry.  The gate
#: answers attempts that spell it — the zone answers nothing it cannot
#: name as a read — and the compile refuses documents that do.
UNKNOWN_OPERATION: str = "frobnicate"

#: An origin the grant does not list — not a wider grant, a component
#: the policy vouches for nothing.
UNKNOWN_ORIGIN: str = "rogue-component"


def grant_document() -> dict[str, Any]:
    """The baseline grant, in the committed document's shape.

    In memory, so every drift test below starts from a document that
    compiles and mutates its own copy — the suite never edits the
    committed artifact, and the artifact has its own file
    (``test_committed.py``).
    """
    return {
        "policy": POLICY_KIND,
        "immutable_zone": {
            "name": ZONE_NAME,
            "paths": list(ZONE_PATHS),
        },
        "components": [
            {
                "name": SIGNAL_SANDBOX,
                "credentials": [
                    {
                        "name": SIGNAL_ROLE,
                        "permissions": [
                            {
                                "path": WORK_AREA_SIGNAL,
                                "operations": [
                                    "create",
                                    "write",
                                    "append",
                                    "delete",
                                ],
                            },
                            {
                                "path": ARTIFACT_DROP_SIGNAL,
                                "operations": ["create", "write"],
                            },
                        ],
                    }
                ],
            },
            {
                "name": POLICY_RUNTIME,
                "credentials": [
                    {
                        "name": POLICY_ROLE,
                        "permissions": [
                            {
                                "path": ZONE_CONTRACT,
                                "operations": ["read", "list"],
                            },
                            {
                                "path": WORK_AREA_POLICY,
                                "operations": ["create", "write"],
                            },
                        ],
                    }
                ],
            },
        ],
    }


def _mutated(document: dict[str, Any]) -> dict[str, Any]:
    """A deep copy of ``document``, private to the drift builders."""
    return copy.deepcopy(document)


def document_with_extra_permission(
    permission: dict[str, Any],
    *,
    component: str = SIGNAL_SANDBOX,
    credential: str = SIGNAL_ROLE,
) -> dict[str, Any]:
    """The baseline grant plus one more permission on one credential.

    The drift builder: every law test hands in the permission it wants
    refused (or, for the contrasts, compiled) and gets back a document
    that is otherwise the lawful baseline.
    """
    document = _mutated(grant_document())
    for raw_component in document["components"]:
        if raw_component["name"] == component:
            for raw_credential in raw_component["credentials"]:
                if raw_credential["name"] == credential:
                    raw_credential["permissions"].append(permission)
                    return document
    raise AssertionError(  # pragma: no cover - test-shape guard
        f"baseline grant carries no credential {credential!r} on "
        f"component {component!r}"
    )


def document_with_zone_write(
    path: str,
    operations: list[str],
    *,
    component: str = SIGNAL_SANDBOX,
    credential: str = SIGNAL_ROLE,
) -> dict[str, Any]:
    """The baseline grant plus a write-carrying permission on ``path``."""
    return document_with_extra_permission(
        {"path": path, "operations": operations},
        component=component,
        credential=credential,
    )


def document_without_zone() -> dict[str, Any]:
    """The baseline grant with the zone block removed entirely."""
    document = _mutated(grant_document())
    del document["immutable_zone"]
    return document
