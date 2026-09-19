"""Deterministic content addressing over a staged directory tree.

Sealing must be reproducible: the same staged bytes have to yield the same
snapshot identity no matter when the sealer runs, which directory order the
filesystem happens to report, or which machine executes the walk. Everything
in this module exists to make that true by construction:

* :func:`walk_content` walks a source tree in sorted order and returns a
  mapping of POSIX relative paths to the sha256 of each file's bytes, read
  in fixed-size chunks (staged Parquet runs to gigabytes; hashing streams
  rather than loading). Relative paths always use ``/`` — the lake layout of
  §4.2 (``bars/symbol=BTCUSDT/date=.../``) is a POSIX path convention, and a
  manifest entry that meant different things on different platforms would
  defeat the addressing.
* :func:`content_digest` folds the per-file hashes into the snapshot's
  content digest: the sha256 of the sorted file hashes, concatenated
  as lowercase hex. This is deliberately the ``sorted(file_hashes)`` term of
  the §4.2 formula, ``sha256(sorted(file_hashes) + universe_definition +
  schema_version)``, and nothing more — the universe and schema terms are
  layered on top of this fold by ``_identity.snapshot_digest`` (feature 32)
  rather than folded in here.

Two properties of that fold are worth stating plainly, because they are
choices, not accidents. Hashes are sorted, so the digest does not depend on
directory iteration order. And the fold is over hashes alone — not
``(path, hash)`` pairs — so two snapshots whose files swapped *names* but
kept the same bytes digest identically, exactly as the §4.2 formula reads.
The universe definition and schema version that disambiguate such cases are
the identity module's terms to add.

The walk refuses what it cannot address. A symlink — even one pointing at a
perfectly ordinary file inside staging — is an error, not a shortcut: a
sealed snapshot is the bytes it names, and a symlink's bytes are somebody
else's, possibly outside the lake entirely. Special files (sockets, FIFOs
left by a crashed worker) are refused for the same reason. Silent skips are
how data lakes lose files without anyone noticing; this walk is loud.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path

from ._errors import SnapshotContentError

__all__ = [
    "CHUNK_SIZE",
    "content_digest",
    "files_digest",
    "sha256_file",
    "sorted_hash_concat",
    "walk_content",
]

#: Bytes read per chunk when hashing; 1 MiB keeps memory flat on GB-scale
#: Parquet without punishing small files with syscall overhead.
CHUNK_SIZE = 1 << 20


def sha256_file(path: Path) -> str:
    """Return the lowercase hex sha256 of a file's bytes, streamed."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def walk_content(root: Path) -> dict[str, str]:
    """Map every regular file under ``root`` to its sha256, sorted by path.

    The mapping's keys are POSIX-style paths relative to ``root``
    (``bars/symbol=BTCUSDT/date=2026-09-01/part.parquet``). Directories
    recurse in sorted order, so the result is byte-for-byte stable across
    runs and machines.

    Raises :class:`SnapshotContentError` when ``root`` is missing, or when
    the tree contains anything other than regular files and directories —
    symlinks and special files are refused, because their bytes cannot be
    addressed honestly.
    """
    if not isinstance(root, Path):
        root = Path(root)
    if not root.is_dir():
        raise SnapshotContentError(
            f"snapshot source {root} does not exist or is not a directory"
        )
    files: dict[str, str] = {}

    def visit(directory: Path, prefix: str) -> None:
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            location = f"{prefix}{entry.name}"
            if entry.is_symlink():
                raise SnapshotContentError(
                    f"{entry} is a symlink; staged content must be regular "
                    "files and directories so a snapshot addresses its own bytes"
                )
            if entry.is_dir():
                visit(entry, f"{location}/")
            elif entry.is_file():
                files[location] = sha256_file(entry)
            else:
                raise SnapshotContentError(
                    f"{entry} is not a regular file; refusing to seal "
                    "unaddressable content"
                )

    visit(root, "")
    return files


def sorted_hash_concat(file_hashes: Iterable[str] | Mapping[str, str]) -> str:
    """Concatenate the per-file hashes, sorted, as lowercase hex.

    Accepts an iterable of hashes or a ``{path: hash}`` mapping (the values
    are used; the mapping form is a convenience for passing
    :func:`walk_content`'s result straight through). This string is the
    preimage two digest spellings share: :func:`content_digest` hashes it
    alone, and the full §4.2 formula (``_identity.snapshot_digest``) frames
    it with the universe and schema terms before hashing. It is defined
    once, here, so the two spellings cannot drift apart — a fold that
    disagreed with the formula's first term would silently re-key the lake.

    Each digest is a fixed 64 characters and the input is lowercased, so
    the concatenation is unambiguous and case-normalised. Nothing validates
    that the inputs are hashes: the walk produced them, and a caller
    folding other strings gets the fold of those strings.
    """
    hashes = file_hashes.values() if isinstance(file_hashes, Mapping) else file_hashes
    return "".join(sorted(hash_.lower() for hash_ in hashes))


def content_digest(file_hashes: Iterable[str] | Mapping[str, str]) -> str:
    """Fold per-file hashes into the snapshot's content digest.

    The sha256 of :func:`sorted_hash_concat` — the ``sorted(file_hashes)``
    term of the §4.2 ``snapshot_hash`` formula and nothing more. An empty
    input yields the sha256 of the empty string: an empty snapshot is a
    legitimate, addressable thing.
    """
    return hashlib.sha256(sorted_hash_concat(file_hashes).encode("ascii")).hexdigest()


def files_digest(files: Iterable[tuple[str, str]]) -> str:
    """Fold ``(path, sha256)`` pairs into one digest over *named* content.

    The sibling of :func:`content_digest`, differing in exactly one way:
    the *paths* are folded in, not just the hashes. That is the whole
    reason it exists. The §4.2 formula deliberately digests a multiset of
    file hashes, so two snapshots whose files swapped names but kept the
    same bytes are one identity — the right answer for content addressing,
    and the wrong one for the persisted ``snapshot_manifest`` record
    (app_spec.xml feature 33), whose job is to let a score name the exact
    bytes it was computed over and *detect* that the manifest was rewritten
    wholesale. A record keyed by the §4.2 hash alone cannot tell a
    tampered manifest from the real one when the tamper swapped two files'
    entries; one that also folds the paths can.

    The preimage is the same shape the hash formula uses — each term its
    own line, sorted, UTF-8 hashed once — so it inherits the separability
    argument: paths are newline-free by construction (``walk_content``
    builds them from directory entry names, which cannot contain ``/`` or a
    NUL, and this refuses anything newline-bearing rather than folding it),
    and each digest is fixed-width hex. Frames are not optional here: a
    fold that concatenated paths and hashes without a separator could be
    rearranged into another pair's preimage.
    """
    lines: list[str] = []
    for path, file_hash in files:
        if not isinstance(path, str) or not path:
            raise SnapshotContentError(
                f"content digest needs a non-empty path, got {path!r}"
            )
        if "\n" in path:
            raise SnapshotContentError(
                f"content path {path!r} carries a newline; the digest "
                "preimage frames one term per line and a path that spans "
                "lines would make it ambiguous"
            )
        lines.append(f"{path}\n{file_hash.lower()}")
    payload = "\n".join(sorted(lines)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
