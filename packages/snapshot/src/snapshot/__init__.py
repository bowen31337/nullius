"""Snapshot sealing and content addressing for the nullius lake.

Implements app_spec.xml feature 30, "System persists a sealed snapshot into
an immutable directory named by sealed_at plus a hash prefix", feature
31, "System persists a MANIFEST.json per snapshot recording per-file
sha256, row counts and the universe definition", feature 32, "System
persists snapshot_hash computed as a sha256 over sorted file hashes plus
the universe definition plus the schema version", feature 38, "System
assigns a new snapshot_hash when the lake is extended, which invalidates
previously cached scores rather than silently reusing them", and feature
39, "System persists a recomputation flag on every score affected by a
snapshot change, while the discovery tree structure survives intact", on
the layout of docs/nullius-tech-architecture.md §4.1-§4.2: ingest workers append into
``<lake>/staging``, and sealing copies that content into an immutable
directory ``<lake>/snapshots/<sealed_at>_<snapshot_hash[:6]>`` — for
example ``2026-09-01T00:00:00Z_a3f91c`` — carrying its ``MANIFEST.json``,
published atomically, frozen read-only on the filesystem, and never
overwritten (see ``_service`` for the three layers the immutability claim
rests on, and ``_manifest`` for the record every seal persists inside the
directory it publishes).

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
these seams: every seal persists a :data:`MANIFEST_NAME` inside the
snapshot — per-file sha256, row counts and the universe definition
(app_spec.xml feature 31, §4.2's layout) — read back through
:meth:`SnapshotService.read_manifest`; and every seal's default identity is
the full §4.2 hash formula (feature 32, :func:`snapshot_digest`): a sha256
over the sorted per-file hashes plus the universe definition plus the lake
schema version, so the same bytes under a different definition or schema
are a different snapshot. That identity is also assign-once (feature 38):
extending the lake changes the content and therefore the hash, so a seal
of the extended lake lands under a *new* snapshot_hash — the lever that
invalidates scores cached under the old one (they key on the old hash and
no longer match) — and a hash some sealed snapshot already carries over
different bytes is refused with :class:`SnapshotHashReusedError` rather
than published. The read-only mount and staging-rejection checks
lean on the frozen modes and the strict name parser.

The invalidation that new hash triggers is made durable by feature 39:
:attr:`SnapshotService.recomputation` returns the
:class:`RecomputationRegistry` that anchors every score to the
discovery-tree node it decorates and the ``snapshot_hash`` it was computed
over, and :meth:`SnapshotService.record_snapshot_change` — verified against
the lake so both hashes name snapshots it actually seals — flips the
``recompute`` flag on every score the old hash held and records the
supersession in an append-only audit, leaving the tree's nodes and edges
untouched. The registry persists to ``<lake>/recomputation.json`` beside
the sealed snapshots, so the flag one process sets is the flag another
reads: a recomputation flag that vanished on restart would silently reuse
the stale score it was meant to replace.

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

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from app.module_loader import register

from ._content import content_digest, sha256_file, walk_content
from ._errors import (
    SnapshotAlreadySealedError,
    SnapshotContentError,
    SnapshotError,
    SnapshotHashReusedError,
    SnapshotManifestError,
    SnapshotNameError,
    SnapshotNotFoundError,
    SnapshotReadOnlyError,
    SnapshotRecomputationError,
    SnapshotStagingRequestError,
)
from ._identity import SCHEMA_VERSION, canonical_universe, snapshot_digest
from ._manifest import (
    MANIFEST_NAME,
    MANIFEST_VERSION,
    ManifestFileEntry,
    SnapshotManifest,
    count_rows,
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
from ._recomputation import (
    RECOMPUTATION_NAME,
    NodeRecord,
    RecomputationRegistry,
    ScoreRecord,
    SupersessionRecord,
)
from ._records import SealedSnapshot, SnapshotRef
from ._service import LAKE_ROOT_ENV, SnapshotService

__all__ = [
    "LAKE_ROOT_ENV",
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "ManifestFileEntry",
    "READ_ONLY_OPERATIONS",
    "ReadOnlyPath",
    "RECOMPUTATION_NAME",
    "NodeRecord",
    "RecomputationRegistry",
    "SCHEMA_VERSION",
    "ScoreRecord",
    "SealedSnapshot",
    "SnapshotAlreadySealedError",
    "SnapshotContentError",
    "SnapshotError",
    "SnapshotHashReusedError",
    "SnapshotManifest",
    "SnapshotManifestError",
    "SnapshotMount",
    "SnapshotNameError",
    "SnapshotNotFoundError",
    "SnapshotReadOnlyError",
    "SnapshotRecomputationError",
    "SnapshotRef",
    "SnapshotService",
    "SnapshotStagingRequestError",
    "SupersessionRecord",
    "canonical_universe",
    "content_digest",
    "count_rows",
    "format_sealed_at",
    "manifest_snapshot",
    "materialize_read_only",
    "mount_snapshot",
    "normalize_snapshot_hash",
    "parse_snapshot_name",
    "permission_denied",
    "recomputation_registry",
    "resolve_sealed_at",
    "seal_snapshot",
    "sha256_file",
    "snapshot_digest",
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
    universe: Optional[Mapping[str, object]] = None,
    lake_root: Optional[Union[str, Path]] = None,
) -> SealedSnapshot:
    """One-shot convenience around :class:`SnapshotService`.

    Seals ``source`` (default: the lake's staging area) into the lake at
    ``lake_root`` (default: resolved from ``LAKE_ROOT`` as above) and returns
    the seal record; ``universe`` is the universe definition the persisted
    MANIFEST.json records and the §4.2 hash folds (see
    :meth:`SnapshotService.seal`). Intended for
    scripts and the sealing cron of §4.1; the composed application and the
    tests use the service directly, since a long-lived process should
    resolve its lake once.
    """
    service = (
        SnapshotService(lake_root)
        if lake_root is not None
        else SnapshotService.from_env()
    )
    return service.seal(
        source, sealed_at=sealed_at, snapshot_hash=snapshot_hash, universe=universe
    )


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


def manifest_snapshot(
    name: str, *, lake_root: Optional[Union[str, Path]] = None
) -> SnapshotManifest:
    """One-shot convenience around :meth:`SnapshotService.read_manifest`.

    Reads the MANIFEST.json of the sealed snapshot called ``name`` from the
    lake at ``lake_root`` (default: resolved from ``LAKE_ROOT`` as above).
    For a script that wants one snapshot's identity — the full hash, the
    per-file entries, the universe definition — without holding a service;
    a long-lived consumer should hold the service instead.
    """
    service = (
        SnapshotService(lake_root)
        if lake_root is not None
        else SnapshotService.from_env()
    )
    return service.read_manifest(name)


def recomputation_registry(
    lake_root: Optional[Union[str, Path]] = None
) -> RecomputationRegistry:
    """One-shot convenience around :attr:`SnapshotService.recomputation`.

    Returns the recomputation registry (feature 39) persisted at the lake
    ``lake_root`` (default: resolved from ``LAKE_ROOT`` as above) — the store
    that carries every score's ``recompute`` flag and the supersession audit.
    For a script or an audit that wants the flags without holding a service;
    a long-lived consumer should hold the service and use its
    ``recomputation`` instead.
    """
    service = (
        SnapshotService(lake_root)
        if lake_root is not None
        else SnapshotService.from_env()
    )
    return service.recomputation
