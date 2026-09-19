"""Snapshot sealing and content addressing for the nullius lake.

Implements app_spec.xml feature 30, "System persists a sealed snapshot into
an immutable directory named by sealed_at plus a hash prefix", feature
31, "System persists a MANIFEST.json per snapshot recording per-file
sha256, row counts and the universe definition", feature 32, "System
persists snapshot_hash computed as a sha256 over sorted file hashes plus
the universe definition plus the schema version", feature 33, "System
persists each sealed snapshot into the snapshot_manifest record so a
score can name the exact bytes it was computed over", feature 36, "System
verifies a snapshot on open by recomputing file hashes, which emits a
corruption alert when any recorded sha256 fails to match", feature 38,
"System assigns a new snapshot_hash when the lake is extended, which
invalidates previously cached scores rather than silently reusing them",
and feature 39, "System persists a recomputation flag on every score
affected by a snapshot change, while the discovery tree structure
survives intact", on
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

The manifest is the snapshot's identity *inside its own directory*; the
record of feature 33 is the same facts written where they can be **joined**
to. Every seal also persists a row of the spec's ``snapshot_manifest``
table — ``snapshot_hash``, ``sealed_at``, ``file_count``, ``row_count``,
``universe_definition`` and ``schema_version``, plus the ``content_digest``
that actually names the bytes — into the relational store ``DATABASE_URL``
addresses (:class:`SnapshotManifestStore`), so a score holding a
``snapshot_hash`` (§4.4's key) can be resolved to the exact bytes it was
computed over without opening a directory. The row is written once, after
the snapshot is published, and never edited: :meth:`SnapshotService.persisted`
reads it back, :meth:`SnapshotService.manifest_records` sweeps the record
set, :meth:`SnapshotService.unrecorded` names the sealed snapshots the
store does not carry, and :meth:`SnapshotService.record_findings` compares
the artifact against the row — which is what catches the one tamper the
on-disk check of feature 36 admits it cannot, a manifest rewritten
*wholesale*. Every seal is recorded — the feature says "each" — including
one whose files carry no row concept, whose unknown total is stored as
``NULL`` rather than skipped or fabricated (the one narrow deviation from
the table's declared ``NOT NULL``, argued in ``_manifest_store``). The one
limit stated rather than hidden is that a lake with no ``DATABASE_URL``
records nothing, which is supported, not broken.

The read side of the same boundary is :class:`SnapshotMount` (feature 34):
``service.mount(name)`` opens a sealed snapshot read-only, handing out
:class:`ReadOnlyPath` handles that read freely and refuse every write with a
permission error naming the operation and the sealed path. It is enforced
twice over — by the ``0444``/``0555`` modes sealing writes into the
filesystem, and by the mount's own structural refusals — so a write through
the mount fails as a ``PermissionError`` whether or not the kernel would
have agreed.

Opening is also verifying (feature 36): :meth:`SnapshotService.open` — and
every door built on it, from :meth:`SnapshotService.mount` to
:meth:`SnapshotService.read_manifest` — recomputes the sha256 of every
file the snapshot's MANIFEST.json records and compares it against the
recorded entry, so a snapshot whose bytes were touched after sealing is
refused with :class:`SnapshotCorruptionError` carrying the full
:class:`CorruptionAlert` (every mismatched digest, every recorded file
gone missing, every planted node the manifest never covered) rather than
silently served. The frozen modes can be chmod'd away by their owner —
the documented crack ``_mount`` states — but a recorded hash cannot be
argued with. The non-raising form of the same check is
:meth:`SnapshotService.verify` (and the :meth:`SnapshotService.verify_all`
sweep), for operators and monitors that want the alert as a record instead
of a refusal.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from app.module_loader import register

from ._content import content_digest, files_digest, sha256_file, walk_content
from ._errors import (
    SnapshotAlreadySealedError,
    SnapshotContentError,
    SnapshotCorruptionError,
    SnapshotError,
    SnapshotHashReusedError,
    SnapshotManifestError,
    SnapshotNameError,
    SnapshotNotFoundError,
    SnapshotReadOnlyError,
    SnapshotRecomputationError,
    SnapshotStagingRequestError,
    SnapshotStoreError,
)
from ._identity import SCHEMA_VERSION, canonical_universe, snapshot_digest
from ._manifest import (
    MANIFEST_NAME,
    MANIFEST_VERSION,
    ManifestFileEntry,
    SnapshotManifest,
    count_rows,
)
from ._manifest_store import (
    DATABASE_URL_ENV,
    MANIFEST_TABLE,
    SnapshotManifestRecord,
    SnapshotManifestStore,
    verify_persisted,
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
from ._verification import (
    HASH_MISMATCH,
    MISSING_FILE,
    UNRECORDED_NODE,
    CorruptionAlert,
    CorruptionFinding,
    corruption_error,
    verify_tree,
)

__all__ = [
    "CorruptionAlert",
    "CorruptionFinding",
    "DATABASE_URL_ENV",
    "HASH_MISMATCH",
    "LAKE_ROOT_ENV",
    "MANIFEST_NAME",
    "MANIFEST_TABLE",
    "MANIFEST_VERSION",
    "ManifestFileEntry",
    "MISSING_FILE",
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
    "SnapshotCorruptionError",
    "SnapshotError",
    "SnapshotHashReusedError",
    "SnapshotManifest",
    "SnapshotManifestError",
    "SnapshotManifestRecord",
    "SnapshotManifestStore",
    "SnapshotMount",
    "SnapshotNameError",
    "SnapshotNotFoundError",
    "SnapshotReadOnlyError",
    "SnapshotRecomputationError",
    "SnapshotRef",
    "SnapshotService",
    "SnapshotStagingRequestError",
    "SnapshotStoreError",
    "SupersessionRecord",
    "UNRECORDED_NODE",
    "canonical_universe",
    "content_digest",
    "corruption_error",
    "count_rows",
    "files_digest",
    "format_sealed_at",
    "manifest_records",
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
    "verify_persisted",
    "verify_snapshot",
    "verify_tree",
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


def verify_snapshot(
    name: str, *, lake_root: Optional[Union[str, Path]] = None
) -> Optional[CorruptionAlert]:
    """One-shot convenience around :meth:`SnapshotService.verify`.

    Verifies the sealed snapshot called ``name`` from the lake at
    ``lake_root`` (default: resolved from ``LAKE_ROOT`` as above) and
    returns its :class:`CorruptionAlert`, or ``None`` when every recorded
    sha256 matches the bytes on disk — feature 36's check in the
    non-raising form, for a health sweep or a monitoring cron that wants
    the alert as a record. The door still refuses staging requests,
    malformed names and misses exactly as :meth:`SnapshotService.open`
    does; only the corruption finding comes back instead of raising.
    """
    service = (
        SnapshotService(lake_root)
        if lake_root is not None
        else SnapshotService.from_env()
    )
    return service.verify(name)


def manifest_records(
    lake_root: Optional[Union[str, Path]] = None
) -> tuple[SnapshotManifestRecord, ...]:
    """One-shot convenience around :meth:`SnapshotService.manifest_records`.

    Returns every ``snapshot_manifest`` row the store holds for the lake at
    ``lake_root`` (default: resolved from ``LAKE_ROOT`` and ``DATABASE_URL``
    as above). Feature 33's record set as data, for a script, an audit or a
    reconciliation against :meth:`SnapshotService.sealed`; an empty tuple is
    an empty store or no configured store, and
    :attr:`SnapshotService.manifest_store` tells the two apart.
    """
    service = (
        SnapshotService(lake_root)
        if lake_root is not None
        else SnapshotService.from_env()
    )
    return service.manifest_records()


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
