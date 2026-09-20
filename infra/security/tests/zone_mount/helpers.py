"""The suite's shared vocabulary: the zone tree, the attempts, and the drift.

Imported by its full namespace path, the way every sibling suite imports
its own (``infra/security/tests/sandbox_egress/helpers.py``) — see the
collision note in this suite's ``conftest.py``.  The constants below are the
spellings the tests aim attempts and writes in: the zone's members as the
committed geometry pins them, the places a read really serves, and the
hostile shapes a write attempt can arrive in.

The on-disk tree (:func:`sealed_zone_tree`) is a stand-in for the deployment's
sealed zone: the six §2 members under the mount point, each holding a file,
plus a staging directory *outside* the zone — the writable area the mount's
refusal points at.  Nothing here opens a write handle; every path is a string
the gate answers or a place a test reads, never writes.
"""

from __future__ import annotations

import os
from typing import Any

from infra.security.zone_mount import MOUNT_POINT, ZONE_NAME

#: The immutable zone's name, as the committed geometry writes it.
ZONE_NAME_VALUE: str = ZONE_NAME

#: The zone's member roots in document order — the deployment's spelling of
#: §2's Z0 contents: the snapshots, the evaluator, the cost model, the
#: contract, the null oracle, the trial ledger.
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

#: The zone's parent directory — the covering path defense in depth refuses.
ZONE_PARENT: str = "/zones/z0"

#: The zones' shared parent — a wider covering path.
ZONES_ROOT: str = "/zones"

#: The mount point the zone is served under.
MOUNT_POINT_VALUE: str = MOUNT_POINT

#: A place whose spelling begins like the zone's but is a neighbour, not a
#: member: segment-wise containment must say outside.
ZONE_NEIGHBOUR: str = "/zones/z0-sidecar"

#: A place outside the mount point entirely — the writable area the mount's
#: refusal points at (staging lives here).
STAGING_PATH: str = "/staging/scratch.py"

#: Deep places inside zone members — the shapes real attempts aim at.
SNAPSHOT_FILE: str = "/zones/z0/snapshots/2026/w42.parquet"
EVALUATOR_IMAGE: str = "/zones/z0/evaluator/image"
SIDECAR_KEY: str = "/zones/z0/nulloracle/sidecar.key"
TRIAL_LEDGER_DB: str = "/zones/z0/trial-ledger/trials.db"

#: The traversal-shaped spelling of a zone place: resolves into the null
#: oracle's member whatever order the segments were typed in.
TRAVERSAL_SIDECAR: str = "/zones/z0/../z0/nulloracle/sidecar.key"

#: The trailing-slash spelling of a member root — the same place.
TRAILING_SLASH_LEDGER: str = "/zones/z0/trial-ledger/"

#: A zone-relative path from the mount root — the spelling a mount-level
#: write carries.
ZONE_RELATIVE_CONTRACT: str = "z0/contract/contract.py"

#: The loop-mutated components — §3's component map draws exactly these two
#: Z1 boxes, the same membership feature 148's committed grant carries.
SIGNAL_SANDBOX: str = "signal-sandbox"
POLICY_RUNTIME: str = "policy-runtime"

#: An operation name the closed vocabulary does not carry.  The gate answers
#: attempts that spell it — the zone answers nothing it cannot name.
UNKNOWN_OPERATION: str = "frobnicate"

#: An origin the mount does not widen for — carried for the audit line only.
UNKNOWN_SERVICE: str = "rogue-service"


def sealed_zone_tree() -> str:
    """A sealed on-disk tree in the committed geometry, returned by path.

    Built fresh in a temporary directory each call, so a test can mount it
    and mutate its modes without touching a sibling's copy.  The tree holds
    the six §2 members under the mount point, each with one file, and a
    staging directory *outside* the zone — the writable area the mount's
    refusal points at.  Every file is persisted ``0444`` and every
    directory ``0555``, the sealed contract :func:`materialize_read_only`
    re-asserts, so a write through the raw filesystem is already refused and
    the mount's structural refusal is defence in depth over real bytes.
    """
    import tempfile

    root = tempfile.mkdtemp(prefix="zone-mount-")
    _seed(root, "z0/snapshots/2026/w42.parquet", b"sealed-bars")
    _seed(root, "z0/evaluator/image", b"sealed-evaluator")
    _seed(root, "z0/cost-model/cost.py", b"sealed-cost")
    _seed(root, "z0/contract/contract.py", b"sealed-contract")
    _seed(root, "z0/nulloracle/sidecar.key", b"sealed-key")
    _seed(root, "z0/trial-ledger/trials.db", b"sealed-ledger")
    # Staging lives outside the zone — the writable area, never on the mount.
    _seed(root, "staging/scratch.py", b"writable")
    _apply_sealed_modes(root)
    return root


def _seed(root: str, relative: str, content: bytes) -> None:
    """Write one sealed file under ``root``, creating parents as needed."""
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)


def _apply_sealed_modes(root: str) -> None:
    """Persist files ``0444`` and directories ``0555`` across ``root``.

    The sealed contract.  A directory must be traversable (``0555``) before
    its files are readable, so directories are tightened last.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), 0o444)
        for name in dirnames:
            os.chmod(os.path.join(dirpath, name), 0o555)
    os.chmod(root, 0o555)


def zone_access_attempt(
    *,
    path: str,
    operation: str,
    service: str = SIGNAL_SANDBOX,
) -> Any:
    """A zone-access attempt in the shared vocabulary.

    The gate's input: a path in whatever spelling, an operation by name, and
    the claiming service — carried for the audit line only, never to widen
    the zone.
    """
    from infra.security.zone_mount import ZoneAccessAttempt

    return ZoneAccessAttempt(path=path, operation=operation, service=service)
