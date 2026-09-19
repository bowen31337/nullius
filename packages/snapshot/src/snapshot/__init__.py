"""Snapshot sealing and content addressing for the nullius lake.

Implements app_spec.xml feature 30, "System persists a sealed snapshot into
an immutable directory named by sealed_at plus a hash prefix", on the layout
of docs/nullius-tech-architecture.md §4.1-§4.2: ingest workers append into
``<lake>/staging``, and sealing copies that content into an immutable
directory ``<lake>/snapshots/<sealed_at>_<snapshot_hash[:6]>`` — for
example ``2026-09-01T00:00:00Z_a3f91c`` — published atomically, frozen
read-only on the filesystem, and never overwritten (see ``_service`` for the
three layers the immutability claim rests on).

This package is a workspace member discovered by convention. The module
loader (``app.module_loader``) scans the members the root ``pyproject.toml``
declares, imports each package, and composes whatever the package's
``@register`` builder contributes — so the registration below is the entire
wiring story. Nothing edits a registry, router or factory to make the
snapshot plugin exist; importing this module *is* joining the application.

The contributed component is a :class:`SnapshotService` bound to the lake
root named by ``LAKE_ROOT`` (defaulting to ``lake/`` beside the workspace
root). Everything else in the public API is importable directly for
scripts, tests and the sibling features of this category, which build on
these seams: the manifest persists the seal record's file mapping; the full
§4.2 hash formula folds the same per-file hashes; the read-only mount and
staging-rejection checks lean on the frozen modes and the strict name
parser.

The read side of the same boundary is :class:`SnapshotMount` (feature 34):
``service.mount(name)`` opens a sealed snapshot read-only, handing out
:class:`ReadOnlyPath` handles that read freely and refuse every write with a
permission error naming the operation and the sealed path. It is enforced
twice over — by the ``0444``/``0555`` modes sealing writes into the
filesystem, and by the mount's own structural refusals — so a write through
the mount fails as a ``PermissionError`` whether or not the kernel would
have agreed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from app.module_loader import register

from ._content import content_digest, sha256_file, walk_content
from ._errors import (
    SnapshotAlreadySealedError,
    SnapshotContentError,
    SnapshotError,
    SnapshotNameError,
    SnapshotNotFoundError,
    SnapshotReadOnlyError,
)
from ._mount import (
    READ_ONLY_OPERATIONS,
    ReadOnlyPath,
    SnapshotMount,
    materialize_read_only,
    permission_denied,
)
from ._naming import (
    format_sealed_at,
    normalize_snapshot_hash,
    parse_snapshot_name,
    resolve_sealed_at,
    snapshot_name,
)
from ._records import SealedSnapshot, SnapshotRef
from ._service import LAKE_ROOT_ENV, SnapshotService

__all__ = [
    "LAKE_ROOT_ENV",
    "READ_ONLY_OPERATIONS",
    "ReadOnlyPath",
    "SealedSnapshot",
    "SnapshotAlreadySealedError",
    "SnapshotContentError",
    "SnapshotError",
    "SnapshotMount",
    "SnapshotNameError",
    "SnapshotNotFoundError",
    "SnapshotReadOnlyError",
    "SnapshotRef",
    "SnapshotService",
    "content_digest",
    "format_sealed_at",
    "materialize_read_only",
    "mount_snapshot",
    "normalize_snapshot_hash",
    "parse_snapshot_name",
    "permission_denied",
    "resolve_sealed_at",
    "seal_snapshot",
    "sha256_file",
    "snapshot_name",
    "walk_content",
]


@register("snapshot")
def snapshot_service() -> SnapshotService:
    """Component builder: the sealing service bound to the configured lake.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its configuration from the environment at build time, so a
    composed application always carries a service for the lake the process
    is actually pointed at (``LAKE_ROOT``, set per test by the shared
    fixtures in ``tests/conftest.py``).
    """
    return SnapshotService.from_env()


def seal_snapshot(
    source: Optional[Union[str, Path]] = None,
    *,
    sealed_at: Optional[Union[datetime, str]] = None,
    snapshot_hash: Optional[str] = None,
    lake_root: Optional[Union[str, Path]] = None,
) -> SealedSnapshot:
    """One-shot convenience around :class:`SnapshotService`.

    Seals ``source`` (default: the lake's staging area) into the lake at
    ``lake_root`` (default: resolved from ``LAKE_ROOT`` as above) and returns
    the seal record. Intended for scripts and the sealing cron of §4.1; the
    composed application and the tests use the service directly, since a
    long-lived process should resolve its lake once.
    """
    service = (
        SnapshotService(lake_root)
        if lake_root is not None
        else SnapshotService.from_env()
    )
    return service.seal(source, sealed_at=sealed_at, snapshot_hash=snapshot_hash)


def mount_snapshot(
    name: str, *, lake_root: Optional[Union[str, Path]] = None
) -> SnapshotMount:
    """One-shot convenience around :meth:`SnapshotService.mount`.

    Mounts the sealed snapshot called ``name`` from the lake at ``lake_root``
    (default: resolved from ``LAKE_ROOT`` as above) and returns the
    read-only mount. The mirror of :func:`seal_snapshot` on the read side,
    for a script or a health sweep that wants one snapshot and not a
    service; a long-lived evaluator host should hold a service and call
    :meth:`SnapshotService.mount` per request instead.
    """
    service = (
        SnapshotService(lake_root)
        if lake_root is not None
        else SnapshotService.from_env()
    )
    return service.mount(name)
