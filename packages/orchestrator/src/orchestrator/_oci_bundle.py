"""The OCI runtime bundle for one gVisor signal run.

additions_spec_gvisor_executor.xml, "gVisor Executor", feature 4:
*System creates an OCI runtime bundle for one signal run with
orchestrator._oci_bundle.build_bundle(directory, *, runtime_root,
child_path, limits, lake_roots). It writes config.json and answers its
path.*  docs/nullius-tech-architecture.md §5.2's isolation row is "gVisor
(runsc)"; this module is the config.json a `runsc run --bundle` call
reads, built fresh for one run and torn down after it (feature 5's job).

The bundle this module writes is deliberately small: one process
(feature 2's hardened child bootstrap, invoked the same way), one
read-only root (the provisioned runtime, never the host filesystem a
signal might read from), five mounts and nothing else — ``/proc``, the
source-less ``/dev`` and ``/sys`` gVisor needs to boot its sandbox at
all, a tmpfs ``/tmp``, and the child bind. There is no caller-supplied
mount list and no caller-supplied process — every field is derived from
``runtime_root``, ``child_path`` and ``limits``, so the one thing left
to police is whether those three arguments themselves name a path under
the data lake, which is :func:`build_bundle`'s own refusal.

The JSON is deterministic for equal inputs: nothing here reads a clock,
a random source or an environment variable, so two bundles built from
the same arguments (even in two different directories) are byte-for-byte
identical, which is what lets a test compare them without running
``runsc`` at all.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Union

__all__ = [
    "BUNDLE_ERROR_CODE",
    "CONFIG_FILENAME",
    "FEATURE_2_ENV",
    "NAMESPACES",
    "BundleError",
    "BundleLimits",
    "build_bundle",
]

#: The greppable code every refusal of this module opens with — the
#: discipline the sandbox member's own laws take for theirs (feature 157's
#: ``gvisor_isolation_required``, feature 162's ``cgroup_budget_exceeded``),
#: restated here because this module owns no dependency on that member.
BUNDLE_ERROR_CODE: Final[str] = "oci_bundle"

#: The file a bundle directory holds — the OCI spec's own name, and the
#: file ``runsc run --bundle DIR`` reads.
CONFIG_FILENAME: Final[str] = "config.json"

_OCI_VERSION: Final[str] = "1.0.2"
_UID: Final[int] = 65534
_GID: Final[int] = 65534
_PYTHON: Final[str] = "/usr/bin/python3"
_CWD: Final[str] = "/tmp"
_TMPFS_SIZE_OPTION: Final[str] = "size=64m"  # a 64 MiB tmpfs at /tmp

#: Feature 2's environment, exactly, minus ``NULLIUS_SIGNAL_SEED``: a
#: bundle is one static file, built once per run and reused as the
#: container's whole configuration, while the seed is the one value in
#: feature 2's list that varies per run and cannot be baked into it. It
#: reaches the child the way feature 1's bootstrap already accepts input
#: — framed on stdin, alongside the signal source and the window payload
#: — so the environment this bundle carries is the part of feature 2's
#: list that is the same for every run.
FEATURE_2_ENV: Final[tuple[str, ...]] = (
    "PATH=/usr/bin:/bin",
    "OMP_NUM_THREADS=1",
    "MKL_NUM_THREADS=1",
    "POLARS_MAX_THREADS=1",
    "PYTHONHASHSEED=0",
)

#: The five namespaces every bundle carries, in the order the feature's
#: own sentence lists them. The network namespace is empty — no
#: interfaces are added to it anywhere in this module — which is what
#: leaves it loopback-only and gives a signal no egress.
NAMESPACES: Final[tuple[str, ...]] = ("pid", "ipc", "uts", "mount", "network")

_MOUNT_DESTINATION_PROC: Final[str] = "/proc"
_MOUNT_DESTINATION_DEV: Final[str] = "/dev"
_MOUNT_DESTINATION_SYS: Final[str] = "/sys"
_MOUNT_DESTINATION_TMP: Final[str] = "/tmp"

#: gVisor's own device tmpfs is sized in kilobytes, not the megabytes
#: ``/tmp`` gets — it holds device nodes, not a signal's working files.
_DEV_SIZE_OPTION: Final[str] = "size=64k"

#: A cgroup v2 ``cpu.max`` of one full core: quota equals period. Not a
#: field of ``limits`` — the sandbox member's policies measure a cpu
#: *budget* in seconds (``cpu_s``), never a core count, so "1 CPU" is a
#: fixed shape this module writes rather than a number it reads.
_CPU_QUOTA: Final[int] = 100_000
_CPU_PERIOD: Final[int] = 100_000

_BYTES_PER_MIB: Final[int] = 1024 * 1024

PathLike = Union[str, "os.PathLike[str]"]


class BundleError(Exception):
    """A bundle configuration this module refuses to write.

    Raised, with :data:`BUNDLE_ERROR_CODE`, for exactly two shapes of
    drift the feature names: a root or a mount source that lies under one
    of ``lake_roots`` (the data lake reaches a signal only as the IPC
    window, never a bind mount), and a mount set that is not precisely
    the five the feature lists. Also raised for a ``limits`` object that
    cannot be read as the two counts this bundle needs — a configuration
    this module cannot write is refused rather than written with a
    guessed number.
    """


@dataclass(frozen=True)
class BundleLimits:
    """The two cgroup numbers a bundle's ``linux.resources`` needs.

    Both are the sandbox member's own published values
    (``sandbox.budget.RUNNER_MEM_MB`` and its committed ``pids``) —
    carried here as plain data rather than imported, because the
    orchestrator member adds no dependency on the sandbox member. A
    caller may hand :func:`build_bundle` an instance of this class, or
    any other object exposing the same two attributes (or a mapping with
    the same two keys): the reader is structural, not a type check.
    """

    runner_mem_mb: int
    pids: int


def _as_path(value: PathLike, *, what: str) -> Path:
    try:
        return Path(value).resolve()
    except TypeError as exc:
        raise BundleError(
            f"{BUNDLE_ERROR_CODE}: {what} must be a path, got {value!r}"
        ) from exc


def _lake_violation(path: Path, lake_roots: Sequence[Path]) -> Path | None:
    """The lake root ``path`` lies under, or ``None`` if it lies under none."""
    for root in lake_roots:
        if path == root or path.is_relative_to(root):
            return root
    return None


def _require_outside_lake(
    path: Path, lake_roots: Sequence[Path], *, what: str
) -> None:
    hit = _lake_violation(path, lake_roots)
    if hit is not None:
        raise BundleError(
            f"{BUNDLE_ERROR_CODE}: {what} ({path}) lies under the data lake "
            f"root {hit} — no gVisor bundle mounts a host data directory; "
            "the data lake reaches a signal only as the IPC window"
        )


def _read_count(value: Any, *, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BundleError(
            f"{BUNDLE_ERROR_CODE}: {what} must be a non-negative int, got "
            f"{value!r} ({type(value).__name__})"
        )
    return value


def _limit(limits: Any, name: str) -> int:
    if isinstance(limits, Mapping):
        value = limits.get(name)
    else:
        value = getattr(limits, name, None)
    if value is None:
        raise BundleError(
            f"{BUNDLE_ERROR_CODE}: limits carries no {name!r}; a bundle's "
            "linux.resources needs both runner_mem_mb and pids from the "
            "sandbox member's policies"
        )
    return _read_count(value, what=f"limits.{name}")


def _mounts(child_path: Path) -> list[dict[str, Any]]:
    """The exactly-five mounts every bundle carries, in document order.

    ``/dev`` and ``/sys`` are gVisor's own virtual filesystems — neither
    carries a host path as its source, so the "no host data mount"
    guarantee is unchanged. Without them, ``runsc`` cannot boot its
    sandbox at all: it exits before the child ever runs.
    """
    return [
        {
            "destination": _MOUNT_DESTINATION_PROC,
            "type": "proc",
            "source": "proc",
            "options": [],
        },
        {
            "destination": _MOUNT_DESTINATION_DEV,
            "type": "tmpfs",
            "source": "tmpfs",
            "options": ["nosuid", "strictatime", "mode=0755", _DEV_SIZE_OPTION],
        },
        {
            "destination": _MOUNT_DESTINATION_SYS,
            "type": "sysfs",
            "source": "sysfs",
            "options": ["nosuid", "noexec", "nodev", "ro"],
        },
        {
            "destination": _MOUNT_DESTINATION_TMP,
            "type": "tmpfs",
            "source": "tmpfs",
            "options": ["nosuid", "nodev", "mode=1777", _TMPFS_SIZE_OPTION],
        },
        {
            "destination": str(child_path),
            "type": "bind",
            "source": str(child_path),
            "options": ["bind", "ro"],
        },
    ]


def _validate_mounts(
    mounts: Sequence[Mapping[str, Any]],
    child_path: Path,
    lake_roots: Sequence[Path],
) -> None:
    """Refuse anything but the five mounts the feature names.

    Checked as its own step — reachable with a hand-built ``mounts`` list
    as well as through :func:`build_bundle` — because the feature's own
    sentence names this as a refusal in its own right: a bundle "adds a
    mount beyond the five listed" is refused the same way one whose root
    lies under the lake is, not merely prevented by this module never
    constructing a sixth.
    """
    if len(mounts) != 5:
        raise BundleError(
            f"{BUNDLE_ERROR_CODE}: a signal's bundle carries exactly five "
            "mounts (proc, dev, sys, a 64 MiB tmpfs at /tmp, and the child "
            f"bootstrap bound read-only) — got {len(mounts)}"
        )
    expected = {
        _MOUNT_DESTINATION_PROC,
        _MOUNT_DESTINATION_DEV,
        _MOUNT_DESTINATION_SYS,
        _MOUNT_DESTINATION_TMP,
        str(child_path),
    }
    destinations = {mount.get("destination") for mount in mounts}
    if destinations != expected:
        raise BundleError(
            f"{BUNDLE_ERROR_CODE}: a bundle's mounts must land at exactly "
            f"{sorted(expected)!r} — got {sorted(d for d in destinations if d is not None)!r}"
        )
    for mount in mounts:
        if mount.get("type") == "bind":
            _require_outside_lake(
                Path(mount["source"]), lake_roots, what="a mount source"
            )


def _process(child_path: Path) -> dict[str, Any]:
    return {
        "terminal": False,
        "user": {"uid": _UID, "gid": _GID},
        "args": [_PYTHON, "-I", str(child_path)],
        "env": list(FEATURE_2_ENV),
        "cwd": _CWD,
        "noNewPrivileges": True,
    }


def _root(runtime_root: Path) -> dict[str, Any]:
    return {"path": str(runtime_root), "readonly": True}


def _linux(limits: Any) -> dict[str, Any]:
    mem_mib = _limit(limits, "runner_mem_mb")
    pids = _limit(limits, "pids")
    return {
        "namespaces": [{"type": kind} for kind in NAMESPACES],
        "resources": {
            "memory": {"limit": mem_mib * _BYTES_PER_MIB},
            "pids": {"limit": pids},
            "cpu": {"quota": _CPU_QUOTA, "period": _CPU_PERIOD},
        },
    }


def build_bundle(
    directory: PathLike,
    *,
    runtime_root: PathLike,
    child_path: PathLike,
    limits: Any,
    lake_roots: Sequence[PathLike] = (),
) -> Path:
    """Write one OCI bundle's ``config.json`` and answer its path.

    ``directory`` is created if it does not already exist. ``runtime_root``
    and ``child_path`` are resolved and checked against ``lake_roots``
    before anything is written: a root or a bind-mount source that lies
    under one of them is refused with :class:`BundleError`, never
    written. ``limits`` supplies the two counts ``linux.resources`` needs
    (``runner_mem_mb``, ``pids``) — see :class:`BundleLimits`.

    The write is a single ``json.dumps`` with sorted keys, so two calls
    with equal arguments (even into two different directories) produce
    byte-identical files: nothing in this function reads a clock, a
    random source or ``os.environ``.
    """
    out_dir = Path(directory)
    root = _as_path(runtime_root, what="runtime_root")
    child = _as_path(child_path, what="child_path")
    lakes = tuple(_as_path(p, what="a lake root") for p in lake_roots)

    _require_outside_lake(root, lakes, what="the runtime root")
    _require_outside_lake(child, lakes, what="the child bootstrap path")

    mounts = _mounts(child)
    _validate_mounts(mounts, child, lakes)

    config: dict[str, Any] = {
        "ociVersion": _OCI_VERSION,
        "process": _process(child),
        "root": _root(root),
        "mounts": mounts,
        "linux": _linux(limits),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = out_dir / CONFIG_FILENAME
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return config_path
