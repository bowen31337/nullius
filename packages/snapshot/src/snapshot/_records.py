"""Immutable value records describing sealed snapshots.

Two shapes, because the lake persists two levels of knowledge:

* :class:`SealedSnapshot` — everything a *sealing* knows. The seal computes
  every file's hash to build the snapshot's identity, so the record carries
  the full snapshot hash, the ``sealed_at`` instant, the directory path, and
  the read-only ``{relative path: sha256}`` mapping. The per-file mapping is
  groundwork, not gold-plating: the MANIFEST feature of this category
  (app_spec.xml feature 31) persists exactly these entries, and the full
  hash formula (feature 32) folds exactly these values — no re-walk needed.
* :class:`SnapshotRef` — everything a *directory name* knows. Once a seal
  has finished, the only thing the lake persists is the name
  ``<sealed_at>_<hash prefix>``; until manifests land, that is all any
  reader can recover. The ref exposes exactly that, parsed: name, path,
  ``sealed_at``, ``hash_prefix``. It is honest about what the filesystem
  knows rather than guessing a full hash from six characters.

Both are frozen dataclasses with no mutating surface — not because a
determined process cannot violate that (it can violate anything), but
because immutability here is the *API contract* matching the medium: a
sealed snapshot directory cannot be edited, so the record describing it
cannot be either. ``files`` is additionally wrapped in a read-only mapping
proxy, so even attribute discipline cannot smuggle a mutation in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from ._naming import normalize_snapshot_hash, parse_snapshot_name, snapshot_name

__all__ = ["SealedSnapshot", "SnapshotRef"]


@dataclass(frozen=True)
class SnapshotRef:
    """A sealed snapshot addressed by its directory name alone."""

    #: The canonical directory name, ``<sealed_at>_<hash prefix>``.
    name: str
    #: The snapshot directory under the lake's ``snapshots/`` root.
    path: Path

    @property
    def sealed_at(self) -> datetime:
        """The sealing instant, parsed from the name as timezone-aware UTC."""
        return parse_snapshot_name(self.name)[0]

    @property
    def hash_prefix(self) -> str:
        """The first six characters of the snapshot hash, from the name."""
        return parse_snapshot_name(self.name)[1]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"SnapshotRef(name={self.name!r})"


@dataclass(frozen=True)
class SealedSnapshot:
    """The full record of one completed seal.

    Constructed by :meth:`snapshot.SnapshotService.seal`; the ``files``
    mapping is defensively copied into a read-only proxy so the record can
    never be edited after the fact, mirroring the directory it describes.
    """

    #: When the snapshot was sealed, timezone-aware UTC, second resolution.
    sealed_at: datetime
    #: The full 64-character lowercase-hex snapshot hash.
    snapshot_hash: str
    #: The immutable snapshot directory this seal produced.
    path: Path
    #: Read-only mapping of POSIX relative path to per-file sha256.
    files: Mapping[str, str]

    def __post_init__(self) -> None:
        # Normalize rather than trust: a record built by hand (tests, future
        # manifest readers) gets the same canonicalisation a seal applies.
        object.__setattr__(
            self, "snapshot_hash", normalize_snapshot_hash(self.snapshot_hash)
        )
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))

    @property
    def name(self) -> str:
        """The canonical directory name for this snapshot."""
        return snapshot_name(self.sealed_at, self.snapshot_hash)

    @property
    def hash_prefix(self) -> str:
        """The first six characters of the snapshot hash."""
        return self.snapshot_hash[:6]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"SealedSnapshot(name={self.name!r}, files={len(self.files)})"
