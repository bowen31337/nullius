"""The per-snapshot MANIFEST.json — identity, row counts, universe.

docs/nullius-tech-architecture.md §4.2 draws the manifest into the sealed
directory itself::

    snapshots/2026-09-01T00:00:00Z_a3f91c/
      MANIFEST.json                     # per-file sha256, row counts, universe
      bars/symbol=BTCUSDT/date=…/…

and app_spec.xml feature 31 makes each noun a persisted fact: a seal does
not merely hash staged content into a name, it *writes down* what it
hashed. Three things the manifest records, and why each is the manifest's
to hold:

* **The per-file sha256 mapping** — the seal already computes it
  (``_content.walk_content``); the manifest persists it inside the
  snapshot, so the lake — not the sealer's memory — can later answer
  *"which exact bytes does this snapshot contain?* (the corruption check
  of feature 36, ``_verification``, compares against exactly these
  entries).
* **A row count per file** — read from the file's own format: the
  Parquet footer's ``num_rows`` (``_parquet``), or the line count of a
  line-oriented text file. A file whose format carries no row concept
  (opaque binary) is recorded as ``null``, never guessed: a manifest
  entry that guessed would be worse than one that admitted ignorance,
  because consumers would then sum fiction into totals.
* **The universe definition** — the parameters of the universe the
  snapshot was sealed against, asserted by the caller as a JSON object.
  The universe member's :class:`~universe.UniverseConfig` is the intended
  producer (its ``dataclasses.asdict`` form); this package deliberately
  does not depend on it, so the manifest accepts any JSON object — and the
  §4.2 hash formula (feature 32) folds the same value into the snapshot's
  identity (the validation and canonical spelling live in ``_identity``,
  imported here so the manifest records exactly what the hash folded).

**The manifest describes content, so it is not content.** The manifest is
written *inside* the published snapshot (frozen ``0444`` with everything
else), but it is excluded from the seal's file mapping and from the
content digest: a manifest cannot honestly hash itself, and the §4.2
formula hashes the *lake's* files. Two consequences are enforced rather
than hoped for. Staging that already contains a root ``MANIFEST.json`` is
refused — the seal writes the snapshot's manifest, and overwriting a
staged file of the same name would break both the copy and the identity.
And a read of a sealed tree that wants *content* (the idempotent re-seal
comparison, the mount's file mapping) walks the tree minus its manifest
(:func:`walk_sealed_content`).

The bytes are deterministic: ``json.dumps(..., indent=2, sort_keys=True)``
plus a trailing newline. The same content, instant, hash and universe
produce byte-identical manifests on every machine — which is what makes
"re-seal and compare" a valid check rather than a lottery.
"""

from __future__ import annotations

import codecs
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Optional, Union

from ._content import CHUNK_SIZE, files_digest, walk_content
from ._errors import SnapshotManifestError, SnapshotNameError
from ._identity import canonical_universe, validate_universe
from ._naming import (
    format_sealed_at,
    normalize_snapshot_hash,
    resolve_sealed_at,
    snapshot_name,
)
from ._parquet import is_complete_parquet, parquet_num_rows

__all__ = [
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "ManifestFileEntry",
    "SnapshotManifest",
    "build_manifest",
    "count_rows",
    "walk_sealed_content",
]

#: The manifest's file name inside every sealed snapshot (§4.2 layout).
MANIFEST_NAME = "MANIFEST.json"

#: The version of the manifest format this package writes and reads. The
#: version is the manifest's own (does the reader understand these keys?),
#: distinct from the lake schema version feature 32 folds into the
#: snapshot hash. A manifest whose version is not this one is refused.
MANIFEST_VERSION = 1

_SEALED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# -- Row counting ----------------------------------------------------------


def count_rows(path: Path) -> Optional[int]:
    """Count the rows a file carries *in its own format*, or admit unknown.

    A row is a format concept, so the counter dispatches on the bytes:

    * a complete ``PAR1`` frame → the Parquet footer's ``num_rows``
      (raising :class:`~snapshot.SnapshotContentError` if the footer does
      not parse — see ``_parquet`` for where that line is drawn);
    * anything that decodes cleanly as UTF-8 → the number of lines, where
      a final line without its newline still counts (``b"a\\nb"`` is 2
      rows, ``b"a\\nb\\n"`` is 2, ``b""`` is 0);
    * anything else → ``None``: no format, no row count, no guess.
    """
    if not isinstance(path, Path):
        path = Path(path)
    if is_complete_parquet(path):
        return parquet_num_rows(path)
    return _line_count(path)


def _line_count(path: Path) -> Optional[int]:
    """Count UTF-8 lines in ``path``; ``None`` if it is not UTF-8 text.

    Streams through a fixed-size buffer with an incremental decoder, so a
    multi-byte character split across a chunk boundary is decoded, not
    miscounted, and memory stays flat on large text files.
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    lines = 0
    saw_bytes = False
    ends_with_newline = True
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            saw_bytes = True
            try:
                text = decoder.decode(chunk)
            except UnicodeDecodeError:
                return None
            lines += text.count("\n")
            ends_with_newline = chunk.endswith(b"\n")
    try:
        decoder.decode(b"", True)  # flush: refuses a truncated final sequence
    except UnicodeDecodeError:
        return None
    if not saw_bytes:
        return 0
    return lines if ends_with_newline else lines + 1


# -- The universe definition ------------------------------------------------
#
# validate_universe — the acceptance door every asserted definition passes
# before the manifest records it — lives in ``_identity`` now: feature 32
# folds the same value into the snapshot hash, so the validation and the
# canonical spelling it hashes by are the identity module's to own, and the
# manifest imports them from there (recording exactly what the hash folded).


# -- The records -------------------------------------------------------------


@dataclass(frozen=True)
class ManifestFileEntry:
    """What the manifest knows about one file: its hash, and its rows."""

    #: The file's sha256, 64 lowercase hex characters.
    sha256: str
    #: How many rows the file carries in its own format — ``None`` when
    #: the format carries no row count (opaque binary). Never a guess.
    row_count: Optional[int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", normalize_snapshot_hash(self.sha256))
        rows = self.row_count
        if rows is not None and (
            isinstance(rows, bool) or not isinstance(rows, int) or rows < 0
        ):
            raise SnapshotManifestError(
                f"manifest row count must be a non-negative integer or "
                f"null, got {rows!r}"
            )


@dataclass(frozen=True)
class SnapshotManifest:
    """The persisted record of one snapshot: identity, rows, universe.

    Built at seal time by :func:`build_manifest`, serialised to
    deterministic JSON bytes (:meth:`to_json_bytes`) and written into the
    snapshot directory as ``MANIFEST.json``; read back with
    :meth:`from_json_bytes` (via :meth:`SnapshotService.read_manifest`).
    Both directions validate, so a manifest that round-trips is a
    manifest that can be believed — and one that does not is refused
    with :class:`SnapshotManifestError` rather than re-read loosely.
    """

    #: The manifest format version; equals :data:`MANIFEST_VERSION`.
    manifest_version: int
    #: The full 64-hex snapshot hash — what the directory name abbreviates.
    snapshot_hash: str
    #: The sealing instant, timezone-aware UTC at second resolution.
    sealed_at: datetime
    #: The universe definition asserted at seal time — a JSON object, or
    #: ``None`` when none was asserted (recorded as JSON ``null``).
    universe: Optional[Mapping[str, Any]]
    #: Read-only mapping of POSIX relative path to per-file entry.
    files: Mapping[str, ManifestFileEntry]
    #: The sum of the per-file row counts, or ``None`` if any file's rows
    #: are unknown — a total over fiction is not a total.
    total_rows: Optional[int]

    def __post_init__(self) -> None:
        if (
            isinstance(self.manifest_version, bool)
            or not isinstance(self.manifest_version, int)
            or self.manifest_version < 1
        ):
            raise SnapshotManifestError(
                f"manifest version must be a positive integer, got "
                f"{self.manifest_version!r}"
            )
        object.__setattr__(
            self, "snapshot_hash", normalize_snapshot_hash(self.snapshot_hash)
        )
        object.__setattr__(self, "sealed_at", resolve_sealed_at(self.sealed_at))
        object.__setattr__(
            self, "universe", validate_universe(self.universe)
        )
        entries = {
            path: (
                entry
                if isinstance(entry, ManifestFileEntry)
                else ManifestFileEntry(**entry)
            )
            for path, entry in self.files.items()
        }
        object.__setattr__(self, "files", MappingProxyType(entries))

    # -- Derived identity ---------------------------------------------------

    @property
    def name(self) -> str:
        """The canonical directory name this manifest belongs to."""
        return snapshot_name(self.sealed_at, self.snapshot_hash)

    @property
    def hash_prefix(self) -> str:
        """The first six characters of the snapshot hash."""
        return self.snapshot_hash[:6]

    @property
    def file_count(self) -> int:
        """How many content files the manifest describes."""
        return len(self.files)

    @property
    def content_digest(self) -> str:
        """A digest over this manifest's entries, *including their paths*.

        The manifest's own identity, distinct from :attr:`snapshot_hash` on
        purpose (see ``_content.files_digest``). The §4.2 hash folds the
        file hashes as a multiset, so it is blind to which path holds which
        bytes; this digest folds each ``(path, sha256)`` pair, so it moves
        when a manifest's entries are rearranged. Recomputed from the
        entries rather than stored — it is a property of the record, and a
        stored copy would be one more field that could drift from them.
        """
        return files_digest(
            (path, entry.sha256) for path, entry in self.files.items()
        )

    @property
    def universe_spelling(self) -> Optional[str]:
        """The canonical JSON spelling of the recorded universe definition.

        ``None`` when none was asserted (the column records SQL ``NULL``),
        else key-sorted compact JSON — the same spelling the §4.2 formula
        hashes (``_identity.canonical_universe``), so the persisted record
        and the identity cannot disagree about what "the same definition"
        means. This is what the ``universe_definition`` column of the
        ``snapshot_manifest`` table carries: the JSON *text*, not a
        language binding to it.
        """
        return canonical_universe(self.universe)

    # -- Serialisation ------------------------------------------------------

    def to_json_bytes(self) -> bytes:
        """Serialise to the deterministic MANIFEST.json byte string.

        ``indent=2`` for the operator who reads one by hand;
        ``sort_keys=True`` for byte-identical output regardless of
        construction order; a trailing newline for the POSIX tooling that
        expects one. These choices are the format: changing any of them
        changes every manifest's identity at once, so they do not change.
        """
        payload = {
            "manifest_version": self.manifest_version,
            "sealed_at": format_sealed_at(self.sealed_at),
            "snapshot_hash": self.snapshot_hash,
            "content_digest": self.content_digest,
            "universe": dict(self.universe) if self.universe is not None else None,
            "files": {
                path: {"sha256": entry.sha256, "row_count": entry.row_count}
                for path, entry in sorted(self.files.items())
            },
            "totals": {"files": self.file_count, "rows": self.total_rows},
        }
        return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, data: Union[bytes, str]) -> "SnapshotManifest":
        """Parse and validate MANIFEST.json bytes into a record.

        Strict by design: the exact key set of this manifest version, the
        exact entry shapes, and totals that agree with the entries. A
        manifest that drifts from the format is a manifest the lake can
        no longer reason about, so drift is an error, not a warning.

        ``content_digest`` is the one key a manifest may carry or omit —
        it arrived with feature 33's persisted record and snapshots sealed
        under it are all this version, while trees sealed in the same
        version before it are still on disk and must still open. When it
        is present it is *checked*, not taken on trust: a recorded digest
        that does not match the entries it claims to summarise is refused,
        because such a manifest is a record of one thing attached to
        another's bytes and every reader downstream would inherit the lie.
        """
        try:
            payload = json.loads(data)
        except ValueError as exc:
            raise SnapshotManifestError(
                f"MANIFEST.json is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise SnapshotManifestError(
                "MANIFEST.json must be a JSON object at the top level, got "
                f"{type(payload).__name__}"
            )
        required_keys = {
            "manifest_version",
            "sealed_at",
            "snapshot_hash",
            "universe",
            "files",
            "totals",
        }
        allowed_keys = required_keys | {"content_digest"}
        if not required_keys <= set(payload) or not set(payload) <= allowed_keys:
            missing = sorted(required_keys - set(payload))
            unexpected = sorted(set(payload) - allowed_keys)
            raise SnapshotManifestError(
                f"MANIFEST.json key set does not match manifest version "
                f"{MANIFEST_VERSION} (missing {missing}, unexpected "
                f"{unexpected}); a manifest the reader cannot fully "
                "understand is refused, not partially applied"
            )
        version = payload["manifest_version"]
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != MANIFEST_VERSION
        ):
            raise SnapshotManifestError(
                f"MANIFEST.json declares version {version!r}; this package "
                f"reads and writes version {MANIFEST_VERSION}"
            )
        try:
            sealed_at = datetime.strptime(
                payload["sealed_at"], _SEALED_AT_FORMAT
            ).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise SnapshotManifestError(
                f"MANIFEST.json sealed_at {payload['sealed_at']!r} is not "
                "the canonical YYYY-MM-DDTHH:MM:SSZ form"
            ) from exc
        files = _parse_files(payload["files"])
        universe = payload["universe"]
        if universe is not None and not isinstance(universe, Mapping):
            raise SnapshotManifestError(
                "MANIFEST.json universe must be a JSON object or null, got "
                f"{type(universe).__name__}"
            )
        manifest = cls(
            manifest_version=version,
            snapshot_hash=_hash_or_refuse(payload["snapshot_hash"]),
            sealed_at=sealed_at,
            universe=universe,
            files=files,
            total_rows=_parse_totals(payload["totals"], files),
        )
        _check_recorded_digest(payload.get("content_digest", _ABSENT), manifest)
        return manifest

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"SnapshotManifest(name={self.name!r}, "
            f"files={self.file_count}, rows={self.total_rows})"
        )


#: Sentinel for "this key was not in the document at all", distinct from a
#: key that is present and ``null`` (which is a malformed digest, not an
#: absent one).
_ABSENT = object()


def _check_recorded_digest(recorded: object, manifest: "SnapshotManifest") -> None:
    """Refuse a recorded ``content_digest`` that contradicts the entries.

    The digest is the record's own integrity claim about itself (feature
    33): what makes a persisted row — or a manifest file — detectably
    *this* manifest and not a rewrite that kept the §4.2 hash. A recorded
    value that disagrees with the entries proves the document was edited
    after the fact, so it is refused here rather than handed out.

    An absent key is the older spelling of the same manifest version and
    is accepted — those trees must keep opening. There is no compatibility
    cost to that: the check is a self-consistency claim inside one
    document, and a document that makes no claim cannot be caught by it.
    """
    if recorded is _ABSENT:
        return
    try:
        expected = manifest.content_digest
        value = normalize_snapshot_hash(recorded)  # type: ignore[arg-type]
    except SnapshotNameError as exc:
        raise SnapshotManifestError(
            f"MANIFEST.json content_digest is not a 64-hex digest: {exc}"
        ) from exc
    if value != expected:
        raise SnapshotManifestError(
            f"MANIFEST.json records content_digest {value} but its entries "
            f"digest to {expected}; the manifest disagrees with itself — "
            "the document was edited after it was written, and a record "
            "that describes bytes other than its own is refused"
        )


def _hash_or_refuse(value: object) -> str:
    try:
        return normalize_snapshot_hash(value)  # type: ignore[arg-type]
    except (SnapshotNameError, TypeError) as exc:
        raise SnapshotManifestError(
            f"MANIFEST.json snapshot_hash is not a 64-hex digest: {exc}"
        ) from exc


def _parse_files(value: object) -> dict[str, ManifestFileEntry]:
    if not isinstance(value, dict):
        raise SnapshotManifestError(
            f"MANIFEST.json files must be a JSON object, got {type(value).__name__}"
        )
    entries: dict[str, ManifestFileEntry] = {}
    for path, raw in value.items():
        if not isinstance(path, str) or not path:
            raise SnapshotManifestError(
                f"MANIFEST.json has a file key that is not a path: {path!r}"
            )
        if not isinstance(raw, dict) or set(raw) != {"sha256", "row_count"}:
            raise SnapshotManifestError(
                f"MANIFEST.json entry for {path!r} is not exactly "
                "{sha256, row_count}"
            )
        try:
            entries[path] = ManifestFileEntry(
                sha256=raw["sha256"], row_count=raw["row_count"]
            )
        except SnapshotManifestError as exc:
            raise SnapshotManifestError(f"MANIFEST.json entry {path!r}: {exc}") from exc
    return entries


def _parse_totals(value: object, files: Mapping[str, ManifestFileEntry]) -> Optional[int]:
    if not isinstance(value, dict) or set(value) != {"files", "rows"}:
        raise SnapshotManifestError(
            "MANIFEST.json totals must be exactly {files, rows}"
        )
    declared_files = value["files"]
    declared_rows = value["rows"]
    if isinstance(declared_files, bool) or not isinstance(declared_files, int):
        raise SnapshotManifestError(
            f"MANIFEST.json totals.files must be an integer, got {declared_files!r}"
        )
    if declared_files != len(files):
        raise SnapshotManifestError(
            f"MANIFEST.json totals.files says {declared_files} but the "
            f"manifest lists {len(files)} files"
        )
    known = [entry.row_count for entry in files.values() if entry.row_count is not None]
    computed = sum(known) if len(known) == len(files) else None
    if declared_rows != computed:
        raise SnapshotManifestError(
            f"MANIFEST.json totals.rows says {declared_rows!r} but the "
            f"entries sum to {computed!r}; the manifest disagrees with itself"
        )
    return declared_rows


# -- Building and walking ----------------------------------------------------


def build_manifest(
    *,
    files: Mapping[str, str],
    source: Path,
    snapshot_hash: str,
    sealed_at: datetime,
    universe: Optional[Mapping[str, Any]],
) -> SnapshotManifest:
    """Assemble the manifest for a seal, from what the seal already walked.

    ``files`` is the seal's content mapping (``{path: sha256}``, from
    ``walk_content``); row counts are read from the staged files at
    ``source`` before anything is published, so a file whose format
    cannot be read fails the seal *before* a directory exists. The
    universe definition is validated here for the same reason.
    """
    entries = {
        path: ManifestFileEntry(
            sha256=file_hash, row_count=count_rows(source / path)
        )
        for path, file_hash in sorted(files.items())
    }
    known = [entry.row_count for entry in entries.values() if entry.row_count is not None]
    return SnapshotManifest(
        manifest_version=MANIFEST_VERSION,
        snapshot_hash=snapshot_hash,
        sealed_at=sealed_at,
        universe=universe,
        files=entries,
        total_rows=sum(known) if len(known) == len(entries) else None,
    )


def walk_sealed_content(root: Path) -> dict[str, str]:
    """Walk a *sealed* snapshot tree, excluding its manifest.

    The one walk-direction difference between staging and a sealed
    directory: the sealed tree contains the derived ``MANIFEST.json``,
    which describes the content and is therefore not part of it. Every
    content-level read of a sealed tree — the idempotent re-seal
    comparison, the mount's file mapping — goes through here so the
    manifest never appears in a content identity by accident.
    """
    return {
        path: file_hash
        for path, file_hash in walk_content(root).items()
        if path != MANIFEST_NAME
    }
