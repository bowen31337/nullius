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
* :class:`SnapshotNotFoundError` — the addressing contract on read: a name
  that parses but names no sealed snapshot in this lake.

Every message names the offending value and the contract it broke, because
these errors are operational signals for a seal-on-schedule pipeline
(docs/nullius-tech-architecture.md §4.1), not debugging aids.
"""

from __future__ import annotations

__all__ = [
    "SnapshotAlreadySealedError",
    "SnapshotContentError",
    "SnapshotError",
    "SnapshotNameError",
    "SnapshotNotFoundError",
]


class SnapshotError(Exception):
    """Base class for every failure of the snapshot sealing path."""


class SnapshotNameError(SnapshotError):
    """The ``<sealed_at>_<hash prefix>`` naming contract was violated."""


class SnapshotContentError(SnapshotError):
    """Staged content cannot be addressed byte-for-byte."""


class SnapshotAlreadySealedError(SnapshotError):
    """An immutable snapshot already exists under this name with other bytes."""


class SnapshotNotFoundError(SnapshotError):
    """A well-formed name that names no sealed snapshot in this lake."""
