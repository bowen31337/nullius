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
* :class:`SnapshotReadOnlyError` — the read-only mount contract. A write
  attempt through a mounted snapshot is refused with a permission error
  *message*, and this is that message made catchable by type.

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

__all__ = [
    "SnapshotAlreadySealedError",
    "SnapshotContentError",
    "SnapshotError",
    "SnapshotNameError",
    "SnapshotNotFoundError",
    "SnapshotReadOnlyError",
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
