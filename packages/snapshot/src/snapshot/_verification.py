"""Verification on open: the bytes are re-hashed against the record.

app_spec.xml feature 36 — *"System verifies a snapshot on open by
recomputing file hashes, which emits a corruption alert when any recorded
sha256 fails to match"* — is the read-side answer to a question the rest
of this category leaves open. Sealing makes a snapshot immutable three
ways over (``_service``: atomic publication, frozen ``0444``/``0555``
modes, no mutating API), and the manifest persists exactly what those
guarantees protect: a sha256 per file (feature 31). But ``_mount`` states
the crack plainly: the modes are ownership-governed, so the sealing user
can ``chmod`` them away and write. Every layer before this one detects
*nothing* after that — the modes are repaired on the next mount, but the
bytes they would have protected are already changed, and a reader handed
the tampered file has no way to know.

This module is the detection. Verification recomputes the sha256 of every
file under the snapshot directory — the same :func:`~snapshot.sha256_file`,
the same chunk size, the same walk order the seal used, so the comparison
is a comparison and not a re-implementation — and diffs it against the
mapping the snapshot's own ``MANIFEST.json`` records. The modes can be
argued with by their owner; a sha256 cannot.

**Three ways a record and a tree can disagree**, and each is a finding:

* **A hash mismatch** — the path is recorded and present, but the bytes on
  disk hash to something else. The named trigger of the feature: *a
  recorded sha256 fails to match*. The same kind covers a recorded path
  that has been replaced by a symlink or special file: what is there is
  not bytes the seal addressed, so there is no honest recomputed digest to
  compare (the finding's ``recomputed`` is ``None``), and the recorded
  hash has still failed to match.
* **A missing file** — the manifest records a path the tree no longer
  holds. The evaluator would read fewer bytes than the identity promises;
  a hash that matches nothing has failed to match.
* **An unrecorded node** — the tree holds a path the manifest never
  recorded: an injected file, or a planted symlink (``recomputed`` is
  ``None`` for the unhashable ones). This is the finding that keeps
  tampered-*in* content from riding under an honest identity — the mount
  serves paths, so a file the manifest does not cover would be read as if
  it were sealed, and only the record comparison catches it.

**The alert is a record before it is an error.** :class:`CorruptionAlert`
carries every finding, sorted by path, with the recorded and recomputed
digests side by side; :meth:`~snapshot.SnapshotService.verify` returns it
without raising, and the :meth:`~snapshot.SnapshotService.verify_all`
sweep returns one per corrupt snapshot in the lake, so a monitor gets the
whole picture as data. The door itself (:meth:`~snapshot.SnapshotService.open`,
and everything built on it — ``mount``, ``read_manifest``) *raises* the
same alert as :class:`~snapshot.SnapshotCorruptionError` (carried on the
exception's ``alert`` attribute), because an evaluator opening corrupt
bytes is the failure the feature exists to stop, not to log. Raising is
the emission; the record is the payload.

**The boundaries, stated as boundaries.** The comparison is against the
snapshot's own manifest, so it inherits two honest limits rather than
papering over them. A snapshot sealed before manifests (feature 31) carries
no record, so verification is vacuously clean — :meth:`open` keeps its
pre-manifest compatibility and ``read_manifest`` refuses the absent
manifest loudly instead. A manifest that cannot be parsed proves nothing
either way and propagates :class:`~snapshot.SnapshotManifestError`
unchanged, the same error the same bytes raise through
``read_manifest``. And a manifest rewritten *wholesale* — every recorded
hash edited to match tampered bytes — cannot be caught by any on-disk
check against itself; that is what the persisted ``snapshot_manifest``
row of feature 33 is for, and pretending this comparison caught it would
be a worse lie than admitting the seam. What verification does pin, with
no external record at all, is that the bytes an evaluator is about to
read are the bytes the seal recorded — or that they are not, naming each
one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from ._content import sha256_file
from ._errors import SnapshotContentError, SnapshotCorruptionError
from ._manifest import MANIFEST_NAME, SnapshotManifest

__all__ = [
    "CorruptionAlert",
    "CorruptionFinding",
    "HASH_MISMATCH",
    "MISSING_FILE",
    "UNRECORDED_NODE",
    "corruption_error",
    "verify_tree",
]

#: A recorded sha256 that fails to match the node at its path — the bytes
#: hash differently, or the path holds a symlink/special file whose bytes
#: cannot honestly be recomputed at all (``recomputed is None``).
HASH_MISMATCH = "sha256-mismatch"

#: A path the manifest records that the tree no longer holds.
MISSING_FILE = "missing-file"

#: A node present in the tree that the manifest never recorded — bytes (or
#: a planted link) riding under an identity that does not cover them.
UNRECORDED_NODE = "unrecorded-node"


# -- The records -------------------------------------------------------------


@dataclass(frozen=True)
class CorruptionFinding:
    """One discrepancy between what the manifest records and what is on disk.

    ``path`` is the POSIX relative path inside the snapshot, the same key
    the manifest's ``files`` mapping uses. ``recorded`` is the sha256 the
    manifest holds for that path (``None`` when the path is unrecorded);
    ``recomputed`` is the sha256 of the bytes found there (``None`` when
    the node is absent, or is a symlink/special file no honest digest can
    describe). ``kind`` is one of :data:`HASH_MISMATCH`,
    :data:`MISSING_FILE`, :data:`UNRECORDED_NODE` — which side of the
    comparison failed, in the vocabulary an operator dispatches on.
    """

    #: POSIX path relative to the snapshot root, the manifest's own key.
    path: str
    #: Which way the record and the tree disagree.
    kind: str
    #: The sha256 the manifest records for this path, if it records one.
    recorded: Optional[str] = None
    #: The sha256 of the bytes on disk, if honest bytes are there to hash.
    recomputed: Optional[str] = None

    def describe(self) -> str:
        """Render the finding as the clause an operator reads.

        One clause per finding, appended to the path in the alert's
        summary: the two digests side by side for a mismatch, and a plain
        statement of shape for the structural findings. An unrecognised
        kind is rendered as itself rather than guessed at — the record is
        data, and the text must not paraphrase it into something it is not.
        """
        if self.kind == HASH_MISMATCH:
            if self.recomputed is None:
                return (
                    "the recorded sha256 has no bytes to match — the path "
                    "holds a planted symlink or special file, not the "
                    f"sealed bytes ({self.kind})"
                )
            return (
                f"recorded sha256 {self.recorded} but the bytes on disk "
                f"hash to {self.recomputed} ({self.kind})"
            )
        if self.kind == MISSING_FILE:
            return (
                f"recorded with sha256 {self.recorded} but absent from the "
                f"tree ({self.kind})"
            )
        if self.kind == UNRECORDED_NODE:
            if self.recomputed is None:
                return (
                    "a planted symlink or special file the manifest never "
                    f"recorded ({self.kind})"
                )
            return (
                f"present with sha256 {self.recomputed} but never recorded "
                f"by the manifest — bytes riding under an identity that "
                f"does not cover them ({self.kind})"
            )
        return f"{self.kind} (recorded {self.recorded}, recomputed {self.recomputed})"


@dataclass(frozen=True)
class CorruptionAlert:
    """What feature 36 emits: every way one snapshot fails to be its record.

    Built only by :func:`verify_tree`; carried by
    :attr:`SnapshotCorruptionError.alert` when the door raises, and
    returned as-is by :meth:`~snapshot.SnapshotService.verify` when a
    caller wants the alert as data instead of a refusal. The findings are
    sorted by path at construction, so two verifications of the same tree
    produce byte-identical summaries regardless of directory iteration
    order.
    """

    #: The canonical directory name of the snapshot that failed.
    snapshot: str
    #: How many recorded sha256 entries were compared against the tree.
    files_checked: int
    #: Every discrepancy found, sorted by path.
    findings: tuple[CorruptionFinding, ...]

    def __post_init__(self) -> None:
        # Sorted here rather than trusted from the walker, so an alert
        # built by hand (a monitor replaying a record, a test) renders as
        # deterministically as one built by verify_tree.
        object.__setattr__(
            self,
            "findings",
            tuple(sorted(self.findings, key=lambda finding: (finding.path, finding.kind))),
        )

    @property
    def mismatches(self) -> tuple[CorruptionFinding, ...]:
        """The findings whose recorded sha256 failed to match."""
        return tuple(f for f in self.findings if f.kind == HASH_MISMATCH)

    @property
    def missing(self) -> tuple[CorruptionFinding, ...]:
        """The findings for recorded paths the tree no longer holds."""
        return tuple(f for f in self.findings if f.kind == MISSING_FILE)

    @property
    def unrecorded(self) -> tuple[CorruptionFinding, ...]:
        """The findings for tree nodes the manifest never recorded."""
        return tuple(f for f in self.findings if f.kind == UNRECORDED_NODE)

    def summary(self) -> str:
        """Render the alert as the message an operator acts on.

        A header naming the snapshot and counting each kind of
        discrepancy, then one line per finding — path, then the finding's
        own clause — so the full alert survives a copy into a log or a
        ticket without losing a path or a digest.
        """
        header = (
            f"sealed snapshot {self.snapshot} is corrupt: "
            f"{len(self.mismatches)} of {self.files_checked} recorded "
            f"sha256 entries fail to match the bytes on disk"
        )
        counts = []
        if self.missing:
            counts.append(f"{len(self.missing)} recorded file(s) missing")
        if self.unrecorded:
            counts.append(
                f"{len(self.unrecorded)} node(s) present that the manifest "
                "never recorded"
            )
        lines = [header + (f", {', '.join(counts)}" if counts else "") + ":"]
        lines.extend(f"  {finding.path}: {finding.describe()}" for finding in self.findings)
        return "\n".join(lines)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"CorruptionAlert(snapshot={self.snapshot!r}, "
            f"findings={len(self.findings)})"
        )


def corruption_error(alert: CorruptionAlert) -> SnapshotCorruptionError:
    """Build the refusal the open door raises for a corrupt snapshot.

    The message is the alert's own summary plus the consequence and the
    remedy: the snapshot is not opened, and corrupt bytes are dealt with
    deliberately — restored from a known-good copy or retired — never read
    past and never overwritten (immutability outranks repair;
    :class:`~snapshot.SnapshotAlreadySealedError` guards the write side of
    that sentence). The alert itself rides on the error's ``alert``
    attribute, so a monitor catching the exception keeps the structured
    record.
    """
    return SnapshotCorruptionError(
        f"{alert.summary()} — the corrupt snapshot is not opened; restore it "
        "from a known-good copy or retire it deliberately, sealed "
        "directories are never overwritten",
        alert,
    )


# -- The walk ----------------------------------------------------------------


def _walk_for_verification(root: Path) -> dict[str, Optional[str]]:
    """Map every node under ``root`` to its sha256, or ``None`` if unhashable.

    The sealing walk (``_content.walk_content``) *refuses* what it cannot
    address — a symlink or special file is an error, because a seal must
    not publish it. This walk *reports* instead: the very nodes that would
    abort the sealing walk are the evidence verification exists to collect,
    so they are recorded as ``None`` (no honest digest exists) and the
    comparison turns them into findings. Regular files hash with the same
    :func:`~snapshot.sha256_file` and the same chunking the seal used, and
    directories recurse in sorted order, so a clean tree yields exactly
    the mapping the seal computed.
    """
    files: dict[str, Optional[str]] = {}

    def visit(directory: Path, prefix: str) -> None:
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            location = f"{prefix}{entry.name}"
            if entry.is_symlink():
                files[location] = None
            elif entry.is_dir():
                visit(entry, f"{location}/")
            elif entry.is_file():
                files[location] = sha256_file(entry)
            else:  # a fifo, socket or device: addressable by nothing honest
                files[location] = None

    visit(root, "")
    # The manifest describes the content and is therefore not part of it —
    # the same exclusion ``_manifest.walk_sealed_content`` applies, kept
    # here so a clean tree compares clean against its own record.
    files.pop(MANIFEST_NAME, None)
    return files


# -- The comparison -----------------------------------------------------------


def verify_tree(root: Union[str, os.PathLike[str]]) -> Optional[CorruptionAlert]:
    """Verify a sealed directory against its own MANIFEST.json.

    The primitive under :meth:`~snapshot.SnapshotService.verify`: recompute
    the sha256 of every file under ``root`` and diff the result against the
    manifest's recorded entries. Returns ``None`` when every recorded hash
    matches and the tree holds nothing the manifest fails to cover, and a
    :class:`CorruptionAlert` — one finding per discrepancy, sorted by path
    — when it does not. Takes a path rather than a name, the same seam
    :meth:`~snapshot.SnapshotMount.for_directory` offers, so a restore
    tool or a test can verify a directory it resolved itself.

    Boundaries, each the honest one rather than the loud one: a ``root``
    that is not a directory is refused as :class:`SnapshotContentError`
    (there is no tree to verify); a tree with no manifest is vacuously
    clean (sealed before feature 31 — there is no record to fail to
    match, and ``read_manifest`` says so loudly); a manifest that cannot
    be parsed propagates :class:`SnapshotManifestError` unchanged (it
    proves nothing either way, and the same bytes raise the same error
    through ``read_manifest``). Verification reads and never writes: no
    mode is repaired, no byte is touched.
    """
    directory = Path(root)
    if not directory.is_dir():
        raise SnapshotContentError(
            f"cannot verify {directory}: not a snapshot directory"
        )
    manifest_file = directory / MANIFEST_NAME
    if not manifest_file.is_file():
        return None
    # Parse errors propagate as themselves: a manifest that cannot be read
    # is the manifest contract's failure, whichever door trips over it.
    manifest = SnapshotManifest.from_json_bytes(manifest_file.read_bytes())
    recorded = {path: entry.sha256 for path, entry in manifest.files.items()}
    actual = _walk_for_verification(directory)

    findings: list[CorruptionFinding] = []
    for path in sorted(set(recorded) | set(actual)):
        recorded_hash = recorded.get(path)
        actual_hash = actual.get(path)
        if path not in actual:
            findings.append(
                CorruptionFinding(
                    path=path, kind=MISSING_FILE, recorded=recorded_hash
                )
            )
        elif path not in recorded:
            findings.append(
                CorruptionFinding(
                    path=path, kind=UNRECORDED_NODE, recomputed=actual_hash
                )
            )
        elif actual_hash != recorded_hash:
            # Covers both a genuine digest difference and actual_hash being
            # None — a symlink/special file sitting where recorded bytes
            # should be. Either way the recorded sha256 failed to match.
            findings.append(
                CorruptionFinding(
                    path=path,
                    kind=HASH_MISMATCH,
                    recorded=recorded_hash,
                    recomputed=actual_hash,
                )
            )
    if not findings:
        return None
    return CorruptionAlert(
        snapshot=directory.name,
        files_checked=len(recorded),
        findings=tuple(findings),
    )
