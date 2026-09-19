"""The snapshot plugin's error taxonomy.

One base class (:class:`SnapshotError`) so callers — and the ingest workers
and evaluators that will grow on top of this package — can catch every
failure of the sealing path with a single ``except``. The subclasses split by
*which contract* was violated, not by which line of code failed:

* :class:`SnapshotNameError` — the naming contract. A ``sealed_at`` that
  cannot be canonicalised, a snapshot hash that is not 64 hex characters, or
  a directory name that does not parse (including deliberate path-traversal
  attempts, which must never reach the filesystem as a path).
* :class:`SnapshotContentError` — the content contract. Staged content that
  cannot be addressed byte-for-byte: a missing source directory, a symlink
  or a special file where only regular files may live.
* :class:`SnapshotAlreadySealedError` — the immutability contract. A sealed
  directory is forever; re-sealing different bytes under a name that already
  exists is refused, not overwritten.
* :class:`SnapshotHashReusedError` — the assign-once contract on identities
  (app_spec.xml feature 38). A ``snapshot_hash`` this lake has already
  assigned to one set of bytes is never assigned to another: when the lake
  is extended, the extension is sealed under a *new* hash, so scores cached
  under the old one are invalidated rather than silently reused. A subclass
  of :class:`SnapshotAlreadySealedError`, because a reassigned identity is
  the same contract violated one directory over — an immutable thing is
  being asked to stand for different bytes.
* :class:`SnapshotManifestError` — the manifest contract. The
  ``MANIFEST.json`` a seal persists inside every snapshot is the snapshot's
  on-disk identity (feature 31), so a manifest that cannot be built, parsed
  or believed — an unserialisable universe definition, a corrupt JSON
  document, a recorded hash that contradicts the directory name — is an
  error, not a warning: a manifest nobody can trust addresses nothing.
* :class:`SnapshotNotFoundError` — the addressing contract on read: a name
  that parses but names no sealed snapshot in this lake.
* :class:`SnapshotStagingRequestError` — the mount-path contract: a request
  that names a staging path (or anything outside the sealed ``snapshots/``
  tree) rather than a sealed snapshot. It is a :class:`SnapshotNotFoundError`
  — a well-formed-syntax request that names nothing the evaluator may open —
  specialised to say *why*: staging is never on the evaluator mount path.
* :class:`SnapshotReadOnlyError` — the read-only mount contract. A write
  attempt through a mounted snapshot is refused with a permission error
  *message*, and this is that message made catchable by type.
* :class:`SnapshotRecomputationError` — the recomputation contract (app_spec.xml
  feature 39). A snapshot change is recorded against the snapshot hashes the
  lake actually persists: a change naming a hash that is not currently sealed
  is refused rather than applied, because a recomputation flag anchored to a
  hash the lake does not hold would flag scores that do not exist.
* :class:`SnapshotCorruptionError` — the verification contract (app_spec.xml
  feature 36). A snapshot opened whose bytes no longer match the sha256 its
  ``MANIFEST.json`` records is refused rather than served: the recomputed
  digest of some file failed to match the recorded one (or a recorded file
  is gone, or the tree holds nodes the manifest never recorded), and the
  open door emits the corruption alert instead of handing out the tampered
  bytes. Carries the full :class:`~snapshot.CorruptionAlert` on its
  ``alert`` attribute, so the exception is the emission and the record is
  the payload.

Every message names the offending value and the contract it broke, because
these errors are operational signals for a seal-on-schedule pipeline
(docs/nullius-tech-architecture.md §4.1), not debugging aids.

One class here is deliberately shaped differently from the rest.
:class:`SnapshotReadOnlyError` inherits from PermissionError as well as
:class:`SnapshotError`, because §4.2's contract is stated in filesystem
terms — *"a snapshot is sealed, hashed, and mounted read-only"*, and a write
through the mount fails the way a write to a read-only medium fails. A
caller written against either vocabulary therefore catches it: ``except
PermissionError`` (what a write to a ``0444`` file already raises) and
``except SnapshotError`` (what every other failure of this package raises)
both work, and ``isinstance(..., OSError)`` stays true, so code that
dispatches on filesystem error types does not have to special-case the
mount.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only; the record lives in _verification
    from ._verification import CorruptionAlert

__all__ = [
    "SnapshotAlreadySealedError",
    "SnapshotContentError",
    "SnapshotCorruptionError",
    "SnapshotError",
    "SnapshotHashReusedError",
    "SnapshotManifestError",
    "SnapshotNameError",
    "SnapshotNotFoundError",
    "SnapshotReadOnlyError",
    "SnapshotRecomputationError",
    "SnapshotStagingRequestError",
]


class SnapshotError(Exception):
    """Base class for every failure of the snapshot sealing path."""


class SnapshotNameError(SnapshotError):
    """The ``<sealed_at>_<hash prefix>`` naming contract was violated."""


class SnapshotContentError(SnapshotError):
    """Staged content cannot be addressed byte-for-byte."""


class SnapshotAlreadySealedError(SnapshotError):
    """An immutable snapshot already exists under this name with other bytes."""


class SnapshotHashReusedError(SnapshotAlreadySealedError):
    """A snapshot_hash already assigned in this lake was asserted over other bytes.

    app_spec.xml feature 38: *"System assigns a new snapshot_hash when the
    lake is extended, which invalidates previously cached scores rather
    than silently reusing them."* The invalidation half of that sentence is
    a consequence of the addressing: scores and features are keyed by
    ``snapshot_hash`` (§4.4), so a genuinely new hash is a guaranteed cache
    miss and the scores are recomputed. This error is what keeps the
    "genuinely" honest — the lake treats every ``snapshot_hash`` it has
    ever published as *assigned* to exactly the bytes that snapshot sealed
    (its ``MANIFEST.json`` is the persisted assignment), and refuses to
    publish the same hash over different bytes, however the caller came by
    it: computed (a digest collision — refused on principle) or supplied
    via ``snapshot_hash=`` (a retry or a schedule replaying a stale
    decision over a lake that has since grown — the reachable case).

    A subclass of :class:`SnapshotAlreadySealedError` on purpose: the name
    check refuses different bytes under an existing *directory name*, and
    this refuses different bytes under an existing *identity* — one
    contract (immutability), two granularities, so a caller catching the
    parent catches both refusals.
    """


class SnapshotNotFoundError(SnapshotError):
    """A well-formed name that names no sealed snapshot in this lake."""


class SnapshotManifestError(SnapshotError):
    """The MANIFEST.json contract of a snapshot was violated.

    Raised on both sides of the manifest's life: *writing* (a universe
    definition that is not a JSON object, or holds values JSON cannot
    carry) and *reading* (a manifest that is not valid JSON for this
    manifest version, whose entries do not type-check, or whose recorded
    snapshot hash contradicts the sealed directory it lives in). The
    manifest is what lets the lake — not any caller's memory — answer
    *"which exact bytes is this snapshot?"*, so a manifest that cannot be
    built or believed is refused loudly rather than recorded loosely.
    """


class SnapshotStagingRequestError(SnapshotNotFoundError):
    """A request named a staging path, which is never on the evaluator mount path.

    A subclass of :class:`SnapshotNotFoundError` on purpose: a request for
    ``staging`` (or any path outside the sealed ``snapshots/`` tree) is a
    request that names nothing the evaluator may open, so ``except
    SnapshotNotFoundError`` — and the broader ``except SnapshotError`` — both
    catch it. It is specialised only in its message, which states the
    contract the plain miss cannot: staging is the ingest workers' writable
    area and is never on the evaluator's mount path, so the evaluator must
    open one of the sealed snapshots instead (``SnapshotService.sealed``).

    Raised only for a request that *reaches* the staging area — i.e. the
    strict name parser has already refused the malformed names, so this is
    the deliberate, named refusal for the shape that got through: a
    canonical-looking request whose first component is the lake's staging
    directory. It names the offending request and the staging path it
    resolves to, so an operator can tell a staging request from a typo.
    """


class SnapshotReadOnlyError(SnapshotError, PermissionError):
    """A write was attempted against a sealed snapshot's read-only mount.

    Dual-inherited on purpose (see the module docstring): this is
    simultaneously the package's read-only-mount failure and the
    ``PermissionError`` a read-only medium raises, so either ``except``
    clause catches it.

    Instances are built with the standard OSError signature
    ``(errno, strerror, filename)`` so they behave like the permission
    errors the filesystem raises rather than merely resembling them:
    ``errno`` is ``EACCES``, ``filename`` names the path that was refused,
    and ``str()`` leads with ``[Errno 13] Permission denied:`` exactly as
    a real ``PermissionError`` does. Use :func:`permission_denied` rather
    than constructing one directly.
    """


class SnapshotRecomputationError(SnapshotError):
    """A snapshot change was recorded against a hash the lake does not hold.

    app_spec.xml feature 39: *"System persists a recomputation flag on every
    score affected by a snapshot change, while the discovery tree structure
    survives intact."* A snapshot change is the event that turns feature 38's
    new hash into a recomputation signal: it flags every score the lake
    persisted under the old hash and records the supersession in the audit,
    leaving the discovery tree's nodes and edges untouched. The flag is only
    honest if both hashes name snapshots the lake actually seals — a change
    naming a hash that is not currently sealed (a typo, a hash from another
    lake, a superseded hash applied twice) is refused rather than recorded,
    because a recomputation flag anchored to a hash the lake does not hold
    would flag scores that do not exist. A subclass of :class:`SnapshotError`
    so callers catching the sealing path's single vocabulary catch it too.
    """


class SnapshotCorruptionError(SnapshotError):
    """A snapshot was opened whose bytes do not match its recorded sha256.

    app_spec.xml feature 36: *"System verifies a snapshot on open by
    recomputing file hashes, which emits a corruption alert when any
    recorded sha256 fails to match."* This is that alert made catchable by
    type. The immutability layers of features 30-34 stop writes through
    every API surface, but the modes are ownership-governed — the sealing
    user can ``chmod`` them away and write — so verification is the
    detection that answers the crack: the open door (and every door built
    on it — ``mount``, ``read_manifest``) recomputes the sha256 of every
    file the snapshot's ``MANIFEST.json`` records and refuses to serve a
    snapshot whose bytes disagree with its record, in any of three ways: a
    recorded hash that fails to match, a recorded file that is missing, or
    a tree node the manifest never recorded.

    The exception carries the structured record of what was found:
    :attr:`alert` is the :class:`~snapshot.CorruptionAlert` (one
    :class:`~snapshot.CorruptionFinding` per discrepancy, recorded and
    recomputed digests side by side), and the message is the alert's own
    summary plus the consequence — the snapshot is not opened. Build one
    with :func:`snapshot.corruption_error` rather than by hand, so the
    record and the message cannot drift apart. A subclass of
    :class:`SnapshotError`, so the package's single ``except`` catches a
    corrupt snapshot along with every other failure of the sealing path.
    """

    #: The structured findings the verification produced. Present on every
    #: error this package raises through the open door; ``None`` only on a
    #: hand-built error with no record behind it.
    alert: Optional["CorruptionAlert"]

    def __init__(
        self, message: str, alert: Optional["CorruptionAlert"] = None
    ) -> None:
        super().__init__(message)
        self.alert = alert
