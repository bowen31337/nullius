"""Feature 147's enforcement: the immutable zone is mounted read-only, for every service.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 147: *System
mounts the immutable zone read-only for every service, which rejects a
write attempt with a permission error message.*  docs/nullius-tech-
architecture.md §2 fixes the posture in the layout table's own line for
Z0 — *"Read-only mounts; separate IAM role; append-only ledger; CI hash
check"* — and §1 P1 keeps the zone's contents ones "LLM-authored code has
no write credential for, and no network path to".  The sentence
decomposes into three claims, each owned here as a seam rather than a
comment:

* **mounts the immutable zone read-only** — the posture, and the reason
  this module is a *mount* rather than a check.  §2's Z0 is a union of
  rooted places — the snapshots, the evaluator, the cost model, the
  contract, the null oracle with its sidecar key, the trial ledger — and
  the mount is the read-only handle over that union: it reads, lists, and
  answers partition queries, and refuses every write attempted against a
  path inside it.  The refusal is *structural*, not a hope that the
  filesystem will deny it: every mutating verb on the mount — and on every
  path it hands out — raises :class:`ZoneWriteRefused` naming the sealed
  path, the operation, and the zone that covers it, before any syscall is
  made.  That is defence in depth over the same invariant the credential
  law holds (§2's "enforce with filesystem permissions"): the zone's
  on-disk bits are persisted read-only (feature 30's ``0444`` files and
  ``0555`` directories), and :func:`materialize_read_only` re-tightens them
  on every mount, so a copy that dropped the bits is tightened back before
  it is served.

* **for every service** — the mount is service-agnostic, and that is the
  point.  It is not one service's privilege but the posture every service
  runs the zone under: the same mount, the same refusal, whatever the
  caller.  The gate (:func:`authorize_zone_access`) carries the caller's
  claimed service in its attempt only for the audit line, and does not
  widen the zone for any of them — a read-only mount that answered
  differently per service would be a credential grant, and that is
  feature 148's half, not this one.  What holds is that every service
  meets the same emptiness: the zone answers a write from none of them.

* **which rejects a write attempt with a permission error message** — the
  consequent, and the refusal's register.  The message is a *permission*
  error — :class:`ZoneWriteRefused` is a :class:`PermissionError` as well
  as a zone error, built on the standard OSError signature ``(errno,
  strerror, filename)`` with ``errno`` ``EACCES`` and the refused path as
  ``filename``, so ``except PermissionError`` and ``except OSError`` catch
  it exactly as a write to a read-only medium would.  And it *says why*:
  it names the operation, the sealed path, and the immutable zone, so an
  operator can tell a sealed refusal from an ordinary permissions
  accident — the same contract feature 34's per-snapshot mount holds
  (:func:`snapshot.permission_denied`), held here at the zone's scale.

**Writes are refused; reads are served.**  A read-only mount is still a
mount — it reads files, lists them, and answers partition queries — and
refusing those would be a different, and useless, feature (§2's Z0 is
"read-only", not unreadable).  So the mount serves every read and refuses
every write, and the split *is* the feature: the write side of the closed
vocabulary (:data:`WRITE_OPERATIONS`, the same verbs feature 148's
credential law refuses onto the zone) is refused, and everything else is a
read.  An operation the vocabulary cannot name is not a read, and the zone
answers nothing it cannot name — the unnamed verb aimed at the zone earns
the same refusal, because a mount that cannot say what an attempt is
certifies nothing about it.

**The mount is not the only control, and it does not pretend to be.**  A
read-only mount in userspace cannot stop three operations, and no file
mode can, because each is governed by ownership or by the *parent*
directory's mode rather than by the mode of the node itself: a ``chmod``
by the file's owner (the real crack, which :func:`materialize_read_only`
detects and undoes on the next mount — ``modes_corrected`` counts it);
``touch``/``os.utime`` by the owner, which changes timestamps but not
content; and ``rename``/``unlink`` of the zone directory itself, which
needs write permission on the parent that must stay writable to publish
new seals.  Closing those completely means a kernel-level read-only mount
(``mount -o ro``, a read-only bind mount, a container volume) and giving
the sealed tree its own ownership — the deployment's job, and what §2's
table means by the mount row.  What this module guarantees is that every
write attempt *through the mount* is rejected with a permission error
message, and that the underlying bits resist every content-changing write
from any direction.  Symlinks are refused on read as well as on write, for
the reason feature 34's mount gives: a link planted inside the zone after
sealing would, if followed, put staging or anything else on the host onto
the zone path, exactly what §2's "no write credential and no network path"
must never become.

**Honest limits, stated exactly.**  This module is the runtime enforcement
the credential law and the egress law both cite as their floor
(:mod:`infra.security.loop_credentials` §"Honest limits": "at runtime the
zone is mounted read-only for every service"; :mod:`infra.security.
sandbox_egress`: "at runtime the sandbox runs in a network namespace").  It
is not the kernel mount: a stdlib package cannot ``mount(2)``, and a
simulated read-only mount that merely resembled one would be worse than an
honest boundary.  What holds is that the mount refuses every write through
it with a permission error message, re-asserts the sealed bits on every
mount, and answers every attempt — well-formed and hostile alike — with a
decision rather than an exception, the way this category's other gates do.
Enforce with filesystem permissions, never with prompt instructions (§2):
"a prompt is not a security boundary", and this module is the filesystem
permission.

Stdlib-only, like the rest of this tree.  Nothing here opens a write
handle; this module is the mount the runtime enforcement is written
against, and the artifact it serves is the sealed zone on disk.
"""

from __future__ import annotations

import enum
import errno
import hashlib
import os
import posixpath
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

__all__ = [
    "CHUNK_SIZE",
    "MOUNT_POINT",
    "READ_ONLY_OPERATIONS",
    "READ_OPERATIONS",
    "WRITE_OPERATIONS",
    "ReadOnlyZonePath",
    "ReadonlyZoneMount",
    "ZoneAccessAttempt",
    "ZoneAccessDecision",
    "ZoneAccessReason",
    "ZoneGeometry",
    "ZoneMountError",
    "ZoneWriteRefused",
    "authorize_zone_access",
    "committed_immutable_zone_mount",
    "materialize_read_only",
    "mount_geometry",
    "zone_write_refused",
]

#: The streaming chunk size for digesting sealed files.  Matches
#: :data:`snapshot._content.CHUNK_SIZE` so a mount-side digest is directly
#: comparable to a seal-side one — the same reason feature 36's corruption
#: check can compare rather than re-implement.
CHUNK_SIZE: Final[int] = 65536

#: The POSIX prefix the immutable zone lives under — the deployment's
#: spelling of §2's Z0.  Every path the mount serves and every member root
#: is expressed under it, the way feature 148's committed grant pins the
#: zone's roots under ``/zones/z0``.
MOUNT_POINT: Final[str] = "/zones"

#: The immutable zone's name, as the committed policy writes it — the same
#: name feature 148's grant carries, so the two features cite one zone.
ZONE_NAME: Final[str] = "z0-immutable"

#: The immutable zone's member roots, in document order — the deployment's
#: spelling of §2's Z0 contents: the snapshots, the evaluator, the cost
#: model, the contract, the null oracle, the trial ledger.  The same six
#: roots feature 148's committed grant pins, so the mount and the
#: credential law protect exactly one geometry.
ZONE_SNAPSHOTS: Final[str] = "/zones/z0/snapshots"
ZONE_EVALUATOR: Final[str] = "/zones/z0/evaluator"
ZONE_COST_MODEL: Final[str] = "/zones/z0/cost-model"
ZONE_CONTRACT: Final[str] = "/zones/z0/contract"
ZONE_NULLORACLE: Final[str] = "/zones/z0/nulloracle"
ZONE_TRIAL_LEDGER: Final[str] = "/zones/z0/trial-ledger"
ZONE_PATHS: Final[tuple[str, ...]] = (
    ZONE_SNAPSHOTS,
    ZONE_EVALUATOR,
    ZONE_COST_MODEL,
    ZONE_CONTRACT,
    ZONE_NULLORACLE,
    ZONE_TRIAL_LEDGER,
)

#: The read side of the vocabulary — the operations a read-only mount
#: serves.  The zone is readable, only its writes are refused.
READ_OPERATIONS: Final[tuple[str, ...]] = ("read", "list", "stat")

#: The mutating verbs this module refuses by name, used to build one
#: consistent refusal message per operation.  The write side of the closed
#: vocabulary — the same verbs feature 148's credential law refuses onto
#: the zone — so the mount and the grant cannot disagree about what a write
#: is.
WRITE_OPERATIONS: Final[tuple[str, ...]] = (
    "write",
    "append",
    "truncate",
    "unlink",
    "rmdir",
    "mkdir",
    "rename",
    "copy-into",
    "chmod",
    "chown",
)

#: The read-only mount's refusal names the operation it stopped; the
#: message and the guard are one tuple, so they cannot drift apart.
READ_ONLY_OPERATIONS: Final[tuple[str, ...]] = WRITE_OPERATIONS

#: Mode bits that, if set anywhere under a sealed tree, are wrong.  The
#: mount clears exactly these and nothing else — a tightening, never a
#: grant (see :func:`materialize_read_only`).
_UNSEALED_BITS: Final[int] = 0o222
_FILE_MODE: Final[int] = 0o444
_DIRECTORY_MODE: Final[int] = 0o555


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ImmutableZoneError(Exception):
    """Base of the read-only-mount taxonomy.

    One base class so a caller — a service opening the zone, an operator
    script, a CI check that recompiles the committed geometry — can catch
    every failure of the mount path with a single ``except``.  The
    subclasses split by *which contract* was violated, never by which line
    of code failed, in the same discipline as the rest of this tree.
    """


class ZoneMountError(ImmutableZoneError):
    """A read-only mount over the immutable zone could not be built.

    A mount point that is not a directory, a member root that does not
    parse or does not live under the mount point, a geometry that names no
    member — the mount fails closed on all of them, because a mount that
    guessed at a geometry it could not read would be enforcing a boundary
    it cannot recognize.  Refused rather than mounted loosely.
    """


class ZoneWriteRefused(ImmutableZoneError, PermissionError):
    """A write was attempted against the immutable zone's read-only mount.

    Dual-inherited on purpose (see the module docstring): this is
    simultaneously the zone's read-only-mount failure and the
    ``PermissionError`` a read-only medium raises, so either ``except``
    clause catches it.  Instances are built with the standard OSError
    signature ``(errno, strerror, filename)`` so they behave like the
    permission errors the filesystem raises rather than merely resembling
    them: ``errno`` is ``EACCES``, ``filename`` names the path that was
    refused, and ``str()`` leads with ``[Errno 13] Permission denied:``
    exactly as a real ``PermissionError`` does.  Use :func:`zone_write_refused`
    rather than constructing one directly.
    """


def zone_write_refused(
    path: str | os.PathLike[str], operation: str, mount_name: str
) -> ZoneWriteRefused:
    """Build the refusal for a write against a path inside the immutable zone.

    The message states the operation, the sealed path, and the zone the
    path came from — the three facts an operator needs to tell a *sealed*
    refusal from an ordinary permissions accident:

        [Errno 13] Permission denied: write to
        /zones/z0/trial-ledger/trials.db refused: the immutable zone
        z0-immutable is mounted read-only for every service
        (docs/nullius-tech-architecture.md §2); the signed release process
        is the only writer of the zone
    """
    location = os.fspath(path)
    message = (
        f"Permission denied: {operation} to {location} refused: the "
        f"immutable zone {mount_name} is mounted read-only for every "
        f"service (docs/nullius-tech-architecture.md §2); the signed "
        f"release process is the only writer of the zone"
    )
    return ZoneWriteRefused(errno.EACCES, message, location)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _at_or_under(outer: str, inner: str) -> bool:
    """Whether canonical absolute ``inner`` is ``outer`` or lies under it.

    Segment-wise, so ``/zones/z0-sidecar`` is a neighbour, not a child of
    ``/zones/z0`` — and the filesystem root is handled for what it is, the
    one prefix whose separator-appended form (``//``) matches nothing.  The
    same containment feature 148's :class:`~infra.security.loop_credentials.
    ImmutableZone` matches by, so the mount and the grant cannot disagree
    about where the zone is.
    """
    if inner == outer:
        return True
    if outer == "/":
        return inner.startswith("/")
    return inner.startswith(outer + "/")


def _normalize_path(path: Any) -> str | None:
    """Return ``path`` as a canonical absolute POSIX path, or ``None``.

    Absolute, because a relative place is wherever a hostile reader's
    working directory left it — a permission that moves with the reader is
    not a permission, it is an accident.  Normalized, so ``..`` and ``.``
    and a trailing slash collapse before the path is trusted.  A path that
    will not canonicalize — the POSIX ``//`` prefix the normalization
    preserves, or anything not absolute — resolves nowhere the zone pinned,
    so it is ``None``: not inside, and the mount answers it by refusing.
    """
    if not isinstance(path, (str, os.PathLike)):
        return None
    raw = os.fspath(path).replace(os.sep, "/")
    if not raw.startswith("/"):
        return None
    normalized = posixpath.normpath(raw)
    if normalized.startswith("//"):
        return None
    return normalized


class ZoneGeometry:
    """The immutable zone's geometry: its name and its member roots.

    The place the feature's law protects, held as the union of rooted
    paths — the deployment's spelling of §2's Z0 contents.  Recognition is
    the whole job: the mount cannot refuse a write onto the zone and the
    gate cannot answer one with the zone's own words unless the geometry
    said which paths are the zone.  Roots are canonicalized once and never
    re-examined: every containment question below is a segment-wise
    comparison against a pinned spelling, so no attempt's shape can move
    the boundary.
    """

    __slots__ = ("name", "paths")

    def __init__(self, *, name: str, paths: Sequence[str]) -> None:
        normalized: list[str] = []
        for root in paths:
            canonical = _normalize_path(root)
            if canonical is None:
                raise ZoneMountError(
                    f"the immutable zone's member root {root!r} is not an "
                    f"absolute POSIX path. The zone is a place, named by the "
                    f"roots that make it up (§2's Z0 contents), and a root "
                    f"that resolves nowhere the mount pinned is one the law "
                    f"protects nowhere — refused, fail closed (feature 147)."
                )
            if canonical == "/":
                raise ZoneMountError(
                    "the immutable zone's '/' root makes the whole "
                    "filesystem the zone. The zone is a bounded place — §2 "
                    "lists its contents — and a zone whose root is "
                    "everything has confused the zone's geometry with the "
                    "posture the law already holds for every path. Refused "
                    "so the geometry keeps saying which place is immutable "
                    "(feature 147)."
                )
            for pinned in normalized:
                if canonical == pinned or _at_or_under(pinned, canonical) or (
                    _at_or_under(canonical, pinned)
                ):
                    raise ZoneMountError(
                        f"the immutable zone's roots pin {canonical!r} and "
                        f"{pinned!r}, one inside the other. The zone is a "
                        f"union of roots, and a member inside a member adds "
                        f"no place while suggesting the smaller one is "
                        f"separately negotiable — the zone is not à la "
                        f"carte. Refused (feature 147)."
                    )
            normalized.append(canonical)
        if not normalized:
            raise ZoneMountError(
                "the immutable zone names no member roots. A zone with no "
                "paths is one the law protects nowhere — §2 lists its "
                "contents (the snapshots, the evaluator, the cost model, "
                "the contract, the null oracle, the trial ledger) — so a "
                "geometry that cannot recognize the zone cannot refuse a "
                "write onto it. Refused, fail closed (feature 147)."
            )
        self.name = name
        self.paths = tuple(normalized)

    def covers(self, path: Any) -> bool:
        """Whether ``path`` lies inside the immutable zone.

        The attempt's spelling is normalized before it is compared — a
        traversal-shaped ``/zones/z0/../z0/ledger`` is the ledger, and a
        trailing slash is the same place — so containment is decided on
        where the path *resolves*, not on how it was typed.  A path that is
        not absolute resolves nowhere the zone pinned, so it is not inside.
        Containment is segment-wise: ``/zones/z0-sidecar`` is a neighbour,
        not a member.
        """
        candidate = _normalize_path(path)
        if candidate is None:
            return False
        return any(_at_or_under(root, candidate) for root in self.paths)

    def covering(self, path: Any) -> str | None:
        """The first member root that contains ``path``, or ``None``.

        The mount's naming helper: a refusal cites the zone member the
        stopped write touched, in document order, so the drift is findable.
        """
        candidate = _normalize_path(path)
        if candidate is None:
            return None
        for root in self.paths:
            if _at_or_under(root, candidate):
                return root
        return None

    def under_mount_point(self, posix_path: Any) -> bool:
        """Whether ``posix_path`` lives under the mount point at all.

        The mount serves only paths under :data:`MOUNT_POINT`; a path
        outside it is not the zone's to serve and is refused as an escape
        rather than resolved to a disk location that could be anywhere.
        """
        candidate = _normalize_path(posix_path)
        if candidate is None:
            return False
        return _at_or_under(MOUNT_POINT, candidate) or candidate == MOUNT_POINT

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ZoneGeometry(name={self.name!r}, paths={self.paths!r})"


def mount_geometry(
    *, name: str = ZONE_NAME, paths: Sequence[str] = ZONE_PATHS
) -> ZoneGeometry:
    """The immutable zone's geometry as this module pins it.

    The committed geometry — the six §2 roots under :data:`MOUNT_POINT` —
    built fresh so a caller (or a test) can mount over a geometry without
    touching the committed artifact.  The same roots feature 148's
    committed grant pins, so the mount and the credential law protect one
    zone.
    """
    return ZoneGeometry(name=name, paths=paths)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _resolve_relative(relation: str) -> str | None:
    """Canonicalise a POSIX relative path, or ``None`` if it escapes.

    Returns the cleaned relative path (``"bars/./part"`` -> ``"bars/part"``,
    ``"."`` -> ``""``) when it stays inside the mount, and ``None`` when it
    would resolve outside it — an absolute path, a ``..`` segment, or a
    path that walks off the top.  Callers turn ``None`` into a refusal; the
    traversal never reaches a ``Path``.  The mount has no outside, and
    "outside" is where staging lives.
    """
    parts: list[str] = []
    for part in PurePosixPath(relation).parts:
        if part == "/" or part == "..":
            return None
        if part in (".", ""):
            continue
        parts.append(part)
    return "/".join(parts)


def _write_intent(mode: str) -> str | None:
    """Classify a ``Path.open`` mode string as a write, or ``None`` for read.

    ``"r"``/``"rb"`` and the extension modes Python allows alongside them
    (``"rt"``) are reads.  ``"w"``, ``"x"`` and ``"a"`` are the three
    writing modes; ``"+"`` upgrades any of them to read-write and is
    treated as the write it is.  An unrecognised mode is left to
    ``Path.open`` to reject — the one mode that matters is ``"+"``, and
    that is already refused.
    """
    if not isinstance(mode, str):
        return None
    if "+" in mode:
        return "write"
    for character in mode:
        if character == "a":
            return "append"
        if character in ("w", "x"):
            return "write"
        if character == "r":
            return None
    return None


def _is_within(candidate: Path, root: Path) -> bool:
    """Whether ``candidate`` resolves to ``root`` itself or a node beneath it."""
    if candidate == root:
        return True
    return root in candidate.parents


def _sha256_file(path: Path) -> str:
    """The sha256 of a file's bytes, streamed.  Matches the seal's digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ReadOnlyZonePath:
    """A path inside the immutable zone.  Immutable, and read-only by type.

    Every mutating verb ``Path`` offers is rewritten here to raise
    :class:`ZoneWriteRefused` instead of touching the disk: ``write_bytes``,
    ``write_text``, ``unlink``, ``rmdir``, ``mkdir``, ``rename``,
    ``replace``, ``chmod``, ``touch``, ``symlink_to``, ``link_to``, and
    ``open`` for any write mode.  So the standard operations fail *with an
    explanation* rather than at the kernel — and a caller who converts the
    path with ``Path(ro_path)`` lands back on the raw filesystem, where the
    ``0444``/``0555`` modes stop the write anyway.

    Reading is fully supported: :meth:`read_bytes`, :meth:`read_text`,
    :meth:`open("rb")`, :meth:`stat`, :meth:`exists`, :meth:`glob`,
    :meth:`sha256` and the rest, handed to the underlying path.  This is a
    *read-only* mount, not a read-nothing one.
    """

    #: Absolute resolved location of this path on disk, inside the zone.
    path: Path
    #: The zone's name, for refusal messages.
    mount_name: str
    #: Absolute POSIX path under the mount point (``/zones/...``).
    posix: str
    #: The member roots this path is contained against, for escape checks.
    roots: tuple[str, ...]

    # -- Refusal ------------------------------------------------------------

    def _refuse_write(self, operation: str) -> ZoneWriteRefused:
        return zone_write_refused(self.path, operation, self.mount_name)

    def _refuse_symlink(self) -> ZoneMountError:
        return ZoneMountError(
            f"{self.path} is a symlink; the immutable zone addresses its "
            f"own bytes, so the mount neither follows it nor reads through "
            f"it — following one would put whatever it points at (staging, "
            f"another zone, anywhere on the host) onto the zone path"
        )

    def root(self) -> Path:
        """The member directory on disk this path lives under.

        Derived from :attr:`posix` and :attr:`roots` rather than re-parsed
        from the name: the root is the on-disk mapping of the member root
        that covers this path.  That keeps the containment check
        independent of the naming contract and correct for a path at a
        member root itself.
        """
        for member in self.roots:
            if _at_or_under(member, self.posix):
                relative = self.posix[len(member):].lstrip("/")
                depth = len([p for p in relative.split("/") if p])
                disk = self.path
                for _ in range(depth):
                    disk = disk.parent
                return disk
        return self.path

    def _checked(self, path: Path) -> Path:
        """Return ``path`` if it is a real node inside the zone, else refuse.

        Nothing that reaches the filesystem through this class passes
        unchecked.  Two escapes are possible, and they need different
        checks: a symlinked final component (caught by ``is_symlink``), and
        a symlinked intermediate component (caught by containment of the
        fully-resolved path, which sees a chain of links ``is_symlink`` on
        the full path cannot).  Neither check may preempt a write refusal:
        :meth:`write_bytes` and friends raise before calling this, so a
        write to a sealed path always reports the permission error feature
        147 specifies, whatever the path's shape.  ``resolve(strict=False)``
        is used because a path may legitimately not exist yet (a caller
        probing for a file), and non-existence is not an escape.
        """
        if path.is_symlink():
            raise self._refuse_symlink()
        member_root = self.root().resolve(strict=False)
        if not _is_within(path.resolve(strict=False), member_root):
            raise self._refuse_symlink()
        return path

    def _relative_to(self, relation: str | os.PathLike[str]) -> str:
        """Return ``relation`` as a relative POSIX path, refusing escapes.

        A caller reaching for an absolute path or a ``..`` walk is refused
        as a write would be — the mount has no outside, and "outside" is
        where staging lives.  The refusal is a read-only refusal, so a
        traversal is stopped by the same message every other refusal uses
        rather than by a separate vocabulary.
        """
        raw = os.fspath(relation).replace(os.sep, "/")
        if PurePosixPath(raw).is_absolute():
            raise self._refuse_write(f"escape to {raw!r}")
        cleaned = _resolve_relative(raw)
        if cleaned is None:
            raise self._refuse_write(f"escape to {raw!r}")
        return cleaned

    # -- Mutating verbs: none of them reach the filesystem ------------------

    def open(  # type: ignore[override]
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ):
        """``Path.open`` with every write mode refused up front.

        ``"r"``/``"rb"`` behave exactly as ``Path.open`` does.  Any mode
        carrying write intent — ``w``, ``a``, ``x``, ``+`` — raises
        :class:`ZoneWriteRefused` *before* the underlying ``open`` is
        called, so the refusal is the mount's decision, not the kernel's,
        and it names the operation (``write``/``append``).  A read is
        checked first, so a symlink planted inside the zone is refused here
        rather than followed.
        """
        operation = _write_intent(mode)
        if operation is not None:
            raise self._refuse_write(f"{operation} to {self.posix}")
        self._checked(self.path)
        return self.path.open(mode, buffering, encoding, errors, newline)

    def write_bytes(self, data: bytes) -> int:
        """Refused: the immutable zone is never written."""
        raise self._refuse_write("write")

    def write_text(
        self, data: str, encoding: str | None = None, errors: str | None = None
    ) -> int:
        """Refused: the immutable zone is never written."""
        raise self._refuse_write("write")

    def unlink(self, missing_ok: bool = False) -> None:
        """Refused: the zone's bytes are never removed."""
        raise self._refuse_write("unlink")

    def rmdir(self) -> None:
        """Refused: the zone's directories are never removed."""
        raise self._refuse_write("rmdir")

    def mkdir(
        self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """Refused: the zone's shape is fixed when it is sealed."""
        raise self._refuse_write("mkdir")

    def rename(self, target: str | os.PathLike[str]) -> None:
        """Refused: the zone is neither rearranged nor moved."""
        raise self._refuse_write("rename")

    def replace(self, target: str | os.PathLike[str]) -> None:
        """Refused: the zone's bytes are never replaced."""
        raise self._refuse_write("rename")

    def chmod(self, mode: int, **kwargs: object) -> None:
        """Refused: the mount's modes are the sealed contract, not a choice.

        The mount re-asserts these modes itself (see
        :func:`materialize_read_only`); a caller loosening them through the
        mount would be the one way to defeat the re-assertion, so it is
        closed here.
        """
        raise self._refuse_write("chmod")

    def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:
        """Refused: touching a sealed file would still be metadata mutation."""
        raise self._refuse_write("write")

    def symlink_to(self, target: str | os.PathLike[str]) -> None:
        """Refused: the zone addresses its own bytes, never another's."""
        raise self._refuse_write("write")

    def link_to(self, target: str | os.PathLike[str]) -> None:
        """Refused: a second name for a sealed byte is still a write."""
        raise self._refuse_write("write")

    # -- Navigation: read-only, and never escaping the zone -----------------

    def __truediv__(self, relation: str | os.PathLike[str]) -> ReadOnlyZonePath:
        """Join a relative path, keeping the mount's guarantees.

        ``/`` is the only way to derive a new :class:`ReadOnlyZonePath`, so
        every path a caller holds came from the mount and carries its
        refusals.  Escaping joins (``"../../staging"``, an absolute path)
        are refused rather than followed.
        """
        cleaned = self._relative_to(relation)
        relative = f"{self.posix}/{cleaned}" if self.posix else f"/{cleaned}"
        candidate = (self.path / cleaned) if cleaned else self.path
        return ReadOnlyZonePath(
            path=candidate,
            mount_name=self.mount_name,
            posix=relative,
            roots=self.roots,
        )

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ReadOnlyZonePath({self.posix!r} inside {self.mount_name})"

    # -- Reads: the actual point of a read-only mount -----------------------

    @property
    def name(self) -> str:
        """The final path component (``""`` for the mount root)."""
        return self.path.name

    @property
    def suffix(self) -> str:
        return self.path.suffix

    def exists(self) -> bool:
        """Whether the node exists.  A symlink is reported as absent.

        "Absent" is the honest answer for a node the mount refuses to
        follow: reporting ``True`` for something every read will then
        reject would make ``exists()`` a promise this class does not keep.
        """
        if self.path.is_symlink():
            return False
        try:
            self._checked(self.path)
        except ZoneMountError:
            return False
        return self.path.exists()

    def is_file(self) -> bool:
        """Whether this is a regular file — false for a symlink or an escape."""
        if self.path.is_symlink():
            return False
        return self.path.is_file()

    def is_dir(self) -> bool:
        """Whether this is a directory — false for a symlink or an escape."""
        if self.path.is_symlink():
            return False
        return self.path.is_dir()

    def stat(self, **kwargs: object):
        """The underlying ``stat`` result, including the frozen mode bits.

        ``follow_symlinks`` is forced off: a caller asking about the mode
        of a sealed path wants the mode of *that* entry, and following a
        link out of the zone is exactly what this class refuses.
        """
        self._checked(self.path)
        kwargs.setdefault("follow_symlinks", False)
        return self.path.stat(**kwargs)

    def read_bytes(self) -> bytes:
        """Read the sealed bytes.  Reading a sealed path is always allowed.

        Refused for a symlink or anything resolving outside the zone: the
        zone addresses its own bytes, and following a planted link would
        put staging — or anywhere else on the host — onto the zone path.
        """
        self._checked(self.path)
        return self.path.read_bytes()

    def read_text(self, encoding: str | None = None, errors: str | None = None) -> str:
        """Read the sealed bytes as text (UTF-8 by default)."""
        self._checked(self.path)
        return self.path.read_text(encoding=encoding, errors=errors)

    def iterdir(self) -> Iterator[ReadOnlyZonePath]:
        """List this directory's entries as read-only paths, sorted."""
        return iter(sorted(self.children(), key=lambda entry: entry.name))

    def children(self) -> tuple[ReadOnlyZonePath, ...]:
        """The entries of this directory as read-only paths, sorted by name.

        Entries are re-derived through :meth:`__truediv__`, so a listed
        entry is a :class:`ReadOnlyZonePath` with the same refusals as a
        path the caller built by hand.  A symlink is listed — hiding it
        would make the mount's view of the tree a lie — but every read of
        it is refused, so listing one is all a caller can do with it.
        """
        if self.path.is_symlink():
            raise self._refuse_symlink()
        if not self.path.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, "not a directory", str(self.path))
        return tuple(
            self / entry.name
            for entry in sorted(self.path.iterdir(), key=lambda e: e.name)
        )

    def glob(self, pattern: str) -> tuple[ReadOnlyZonePath, ...]:
        """Match ``pattern`` under this directory, returning read-only paths.

        Where §2's partition layout is queried, the results are read-only
        paths like every other path the mount hands out.  Matches are
        filtered to sealed nodes: a glob is a query for sealed files, and a
        symlink is not one — not as a final component, and not as a
        component *within* the match either.  Containment of the
        fully-resolved path is what catches the second case.
        """
        self._checked(self.path)
        member_root = self.root().resolve(strict=False)
        matches: list[ReadOnlyZonePath] = []
        for match in sorted(self.path.glob(pattern), key=lambda m: m.name):
            if match.is_symlink():
                continue
            if not _is_within(match.resolve(strict=False), member_root):
                continue
            relative = f"{self.posix}/{match.name}" if self.posix else f"/{match.name}"
            matches.append(
                ReadOnlyZonePath(
                    path=match,
                    mount_name=self.mount_name,
                    posix=relative,
                    roots=self.roots,
                )
            )
        return tuple(matches)

    def sha256(self) -> str:
        """The sha256 of this file's sealed bytes, streamed.

        Same streaming digest the seal computes, so a mount-side digest is
        directly comparable to a recorded one — which is what makes a
        corruption check a comparison rather than a re-implementation.
        """
        self._checked(self.path)
        return _sha256_file(self.path)


# ---------------------------------------------------------------------------
# The mount
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadonlyZoneMount:
    """The immutable zone mounted read-only, over an on-disk directory.

    Built by :meth:`for_directory`, which validates that the on-disk
    ``root`` is a directory and maps it to :data:`MOUNT_POINT`, and by
    :func:`committed_immutable_zone_mount`, which serves the sealed zone as
    committed.  From then on the mount is the only handle a caller needs:
    the root is a :class:`ReadOnlyZonePath`, and every path derived from it
    inherits the same refusals.

    The mount is deliberately *not* a context manager that unmounts.  There
    is nothing to release — it holds no file descriptor, no temporary
    directory, no OS mount — and a lifecycle that pretended otherwise would
    invite the belief that the zone stops being read-only after the ``with``
    block.  It is read-only because of the bytes on disk, and because this
    mount refuses every write through it, forever.
    """

    #: The zone's name, for refusal messages.
    name: str
    #: The on-disk directory the zone is served from — the deployment's
    #: spelling of :data:`MOUNT_POINT`.
    root: Path
    #: The immutable zone's geometry — its name and its member roots.
    geometry: ZoneGeometry
    #: How many entries had their mode corrected by the re-assertion on
    #: this mount (see :func:`materialize_read_only`).  Reported for
    #: observability; it is never a permission the mount relies on.
    modes_corrected: int = field(default=0)

    def __post_init__(self) -> None:
        # A mount that is not a directory is not a mount.  Checked here so a
        # mount built by hand (tests, future readers) fails as loudly as one
        # built by the service.
        if not self.root.is_dir():
            raise ZoneMountError(
                f"cannot mount the immutable zone at {self.root}: not a "
                f"directory. The zone is served from an on-disk tree mapped "
                f"to {MOUNT_POINT!r}, and a mount that is not a directory "
                f"serves nothing — refused, fail closed (feature 147)."
            )

    @classmethod
    def for_directory(
        cls,
        path: str | os.PathLike[str],
        *,
        name: str = ZONE_NAME,
        geometry: ZoneGeometry | None = None,
        reassert_modes: bool = True,
    ) -> ReadonlyZoneMount:
        """Mount a sealed on-disk tree the caller already resolved.

        The seam for callers that hold a directory rather than a name — a
        restore tool, a scheduler that remembered where it sealed the zone,
        a test.  The directory is mapped to :data:`MOUNT_POINT`, so the
        mount's POSIX spellings (``/zones/z0/snapshots/...``) resolve to
        this directory's children (``<root>/z0/snapshots/...``).  Refusing
        anything that is not a directory is the only precondition.

        Unlike :func:`committed_immutable_zone_mount` it has no committed
        geometry to serve, so one is taken from ``geometry`` (or the module
        default): every path the mount hands out names a zone, and a mount
        whose geometry is a lie would break that.
        """
        directory = Path(path)
        if not directory.is_dir():
            raise ZoneMountError(
                f"cannot mount the immutable zone at {directory}: not a "
                f"directory (feature 147)."
            )
        zone = geometry if geometry is not None else mount_geometry()
        corrections = (
            materialize_read_only(directory) if reassert_modes else 0
        )
        return cls(
            name=name,
            root=directory,
            geometry=zone,
            modes_corrected=corrections,
        )

    def _disk(self, posix_path: str) -> Path:
        """Map a POSIX path to its on-disk location under the served tree.

        A path already under the mount point — ``/zones/z0/snapshots/x`` —
        has the prefix stripped and the remainder joined onto the served
        directory, giving ``<root>/z0/snapshots/x``.  A path already
        relative to the mount root — a mount-level verb's ``z0/snapshots/x``
        — is joined directly.  Either way the result is under ``root``; the
        caller has already established the place, so this is a mapping,
        never a trust.
        """
        prefix = MOUNT_POINT.rstrip("/")
        remainder = posix_path
        if remainder.startswith(prefix + "/"):
            remainder = remainder[len(prefix) + 1:]
        elif remainder.startswith(prefix):
            remainder = remainder[len(prefix):].lstrip("/")
        return self.root / remainder

    # -- Identity -----------------------------------------------------------

    @property
    def mount_point(self) -> str:
        """The POSIX prefix this mount serves — always :data:`MOUNT_POINT`."""
        return MOUNT_POINT

    @property
    def root_path(self) -> ReadOnlyZonePath:
        """The mount's root as a read-only path.

        This is the handle everything else is derived from: ``mount.root /
        "z0/snapshots" / "bars/symbol=BTCUSDT"`` is a
        :class:`ReadOnlyZonePath`, never a plain ``Path``.
        """
        return ReadOnlyZonePath(
            path=self.root,
            mount_name=self.name,
            posix=MOUNT_POINT,
            roots=self.geometry.paths,
        )

    # -- Refusal, at the mount itself ---------------------------------------

    def _refuse_write(self, operation: str, relative: str = "") -> ZoneWriteRefused:
        where = self._disk(relative) if relative else self.root
        return zone_write_refused(where, operation, self.name)

    def write_bytes(self, data: bytes, relative: str = "") -> int:
        """Refused: writing into the immutable zone is never allowed."""
        raise self._refuse_write("write", relative)

    def write_text(self, data: str, relative: str = "") -> int:
        """Refused: writing into the immutable zone is never allowed."""
        raise self._refuse_write("write", relative)

    def mkdir(self, relative: str) -> None:
        """Refused: the zone's shape is fixed when it is sealed."""
        raise self._refuse_write("mkdir", relative)

    def unlink(self, relative: str) -> None:
        """Refused: nothing under the immutable zone is removed."""
        raise self._refuse_write("unlink", relative)

    def rmdir(self, relative: str = "") -> None:
        """Refused: nothing under the immutable zone is removed."""
        raise self._refuse_write("rmdir", relative)

    def rename(self, source: str, target: str) -> None:
        """Refused: the immutable zone is neither rearranged nor moved."""
        raise self._refuse_write("rename", f"{source} -> {target}")

    def chmod(self, mode: int, relative: str = "") -> None:
        """Refused: the mount's modes are the sealed contract."""
        raise self._refuse_write("chmod", relative)

    def copy_into(self, source: str | os.PathLike[str], relative: str = "") -> None:
        """Refused: no outside bytes enter the immutable zone."""
        raise self._refuse_write("copy-into", relative)

    def _dir_fd(self) -> int:
        """A read-only descriptor for the mount root.

        Kept private and read-only on purpose: :meth:`open_at` is the only
        thing that uses it, and it opens ``O_RDONLY``, so the descriptor
        itself carries no write intent that a caller could inherit.
        """
        return os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)

    def open_at(self, relative: str, mode: str = "rb", **kwargs: object):
        """Open a file inside the zone relative to the *root descriptor*.

        The descriptor form of :meth:`ReadOnlyZonePath.open`: the path is
        resolved by the kernel relative to the mount root's own descriptor,
        so no renamed parent can redirect it between the check and the open.
        Write modes are refused before the descriptor is even obtained, and
        the descriptor itself is opened ``O_RDONLY``.

        ``O_NOFOLLOW`` is the load-bearing flag: it is this method's whole
        reason to exist alongside :meth:`ReadOnlyZonePath.read_bytes`.
        Because the *kernel* resolves the final component here, a
        Python-level ``is_symlink()`` check would be a time-of-check/
        time-of-use race — so the refusal is expressed as a flag the kernel
        honours atomically instead.  Opening a symlink raises ``ELOOP``,
        which is translated to the same refusal the rest of the mount
        raises.
        """
        operation = _write_intent(mode)
        if operation is not None:
            raise self._refuse_write(f"{operation} to {relative!r}")
        cleaned = _resolve_relative(relative)
        if cleaned is None:
            raise self._refuse_write(f"escape to {relative!r}")
        root_fd = self._dir_fd()
        try:
            handle_fd = os.open(cleaned, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise ZoneMountError(
                    f"{relative} is a symlink; the immutable zone addresses "
                    "its own bytes, so the mount neither follows it nor "
                    "reads through it"
                ) from exc
            raise
        finally:
            os.close(root_fd)
        return os.fdopen(handle_fd, mode, **kwargs)

    # -- Reads --------------------------------------------------------------

    def read_bytes(self, relative: str) -> bytes:
        """Read a sealed file's bytes by zone-relative path."""
        return (self.root_path / relative).read_bytes()

    def read_text(
        self, relative: str, encoding: str | None = None, errors: str | None = None
    ) -> str:
        """Read a sealed file as text by zone-relative path."""
        return (self.root_path / relative).read_text(encoding=encoding, errors=errors)

    def files(self) -> Mapping[str, str]:
        """The sealed tree's content as ``{relative POSIX path: sha256}``.

        Re-walked on the mount side, so a reader can compare the bytes it
        is about to consume against the identity the zone was sealed under
        without opening files itself.
        """
        result: dict[str, str] = {}
        for candidate in sorted(self.root.rglob("*")):
            if candidate.is_file() and not candidate.is_symlink():
                relative = candidate.relative_to(self.root).as_posix()
                result[relative] = _sha256_file(candidate)
        return result

    def paths(self) -> tuple[ReadOnlyZonePath, ...]:
        """Every file in the zone as a read-only path, sorted by path."""
        return tuple(
            ReadOnlyZonePath(
                path=self.root / relative,
                mount_name=self.name,
                posix=f"{MOUNT_POINT.rstrip('/')}/{relative}",
                roots=self.geometry.paths,
            )
            for relative in sorted(self.files())
        )

    def file_count(self) -> int:
        """How many regular files the mount holds."""
        return len(self.files())

    def total_bytes(self) -> int:
        """The total size of the sealed content, for operator visibility."""
        return sum(
            (self.root / relative).stat().st_size for relative in self.files()
        )

    # -- Observability ------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ReadonlyZoneMount(name={self.name!r}, read_only=True)"


def committed_immutable_zone_mount(
    root: str | os.PathLike[str] | None = None,
    *,
    reassert_modes: bool = True,
) -> ReadonlyZoneMount:
    """The immutable zone as committed, served read-only from ``root``.

    The mount this feature stands up: the sealed zone on disk, served from
    the deployment's ``root`` (defaulting to ``/zones``) and mapped to
    :data:`MOUNT_POINT`, through the same :func:`materialize_read_only`
    re-assertion every mount runs.  What a service opens and what the
    operator sealed are provably the same geometry — the six §2 roots this
    module pins, the same roots feature 148's committed grant protects.
    """
    served = Path(root) if root is not None else Path(MOUNT_POINT)
    return ReadonlyZoneMount.for_directory(
        served, name=ZONE_NAME, geometry=mount_geometry(), reassert_modes=reassert_modes
    )


def materialize_read_only(
    root: str | os.PathLike[str], *, fix: bool = True
) -> int:
    """Re-apply the sealed modes across a zone tree; return corrections.

    Sealing persists files ``0444`` and directories ``0555``, and that is
    the primary enforcement of the read-only contract.  But modes travel
    badly: a copy that did not preserve permissions, a restore from an
    archive that ignored them, or a build pipeline that untarred with a
    permissive umask can all leave a sealed tree writable by its owner —
    after which the read-only contract is a comment rather than a property.

    Mounting therefore re-asserts the contract, and this is the function
    that does it: it walks the tree and **clears every write bit it finds**
    — ``current & ~0o222``, nothing more.  That mask is the whole policy,
    and it is why this can only ever tighten: clearing bits cannot add one,
    so an entry that already denies writes is left exactly as it was, and a
    tree that an operator sealed *stricter* than the contract (a ``0400``
    file, say) is not quietly widened back to ``0444``.  A tree whose read
    bits were stripped is the operator's to repair, not this walk's to
    guess at.

    It reports how many entries it corrected, so a caller — an operator, a
    monitor — can see a tree that had drifted rather than taking silence
    for health.  With ``fix=False`` it changes nothing and only counts
    drift, which is what a verification sweep wants.  A missing directory
    is return-zero: nothing to tighten is not an error.
    """
    target = Path(root)
    if not target.is_dir():
        return 0
    corrections = 0
    for candidate in (target, *sorted(target.rglob("*"))):
        try:
            current = os.stat(candidate, follow_symlinks=False).st_mode & 0o7777
        except OSError:  # pragma: no cover - racing deletion, not our concern
            continue
        sealed = _DIRECTORY_MODE if candidate.is_dir() else _FILE_MODE
        if current == sealed or not current & _UNSEALED_BITS:
            # Already at the contract, or stricter than it.  Either way there
            # is no write to remove and nothing to report.
            continue
        corrections += 1
        if fix:
            os.chmod(candidate, current & ~_UNSEALED_BITS)
    return corrections


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class ZoneAccessReason(enum.StrEnum):
    """Why a zone-access decision came out the way it did — the audit
    vocabulary.

    One enumeration carries the acceptance and the rejection reasons,
    because a decision's reason is one fact with two polarities, and the
    audit line should read the same either way: ``inside-immutable-zone``
    is §2's own claim — the zone is read-only for every service — not a
    rule this gate invented.
    """

    #: Rejected: the attempt is a write at the immutable zone, inside a
    #: member or covering one — §2's "read-only mounts", the feature's own
    #: sentence.  Checked before anything else, so it outranks everything.
    INSIDE_IMMUTABLE_ZONE = "inside-immutable-zone"

    #: Rejected: the attempt's path is not a place the mount can serve —
    #: not under the mount point, or not absolute.  The mount has no
    #: outside, and "outside" is where staging lives; the attempt is
    #: refused rather than resolved to a disk location that could be
    #: anywhere.
    OUTSIDE_MOUNT_POINT = "outside-mount-point"

    #: Rejected: the attempt carries an operation the closed vocabulary
    #: cannot name.  The zone answers nothing it cannot name — an unnamed
    #: verb is not a read, and the mount certifies nothing about it.
    UNNAMED_OPERATION = "unnamed-operation"

    #: Admitted: the attempt is a read (an operation of the read side) at a
    #: place the mount serves.  A read-only mount is not a read-nothing one
    #: — §2's Z0 is readable — and this is the reachable branch for every
    #: legitimate read.
    BY_READ = "by-read"

    #: Admitted: the attempt is a write at a place outside the immutable
    #: zone.  The mount governs only the zone; a write elsewhere is not the
    #: zone's to refuse.  No compiled geometry can produce this reason for
    #: a path inside the zone, by the zone check that stands in front of
    #: it — so an allowed write on an audit line is proof the place was
    #: outside the zone.
    BY_LOCATION = "by-location"


class ZoneAccessAttempt:
    """One access attempt against the immutable zone, as presented.

    Deliberately unvalidated beyond assignment: the gate models what
    agent-authored code reached for, hostile shapes included, and *answers*
    them rather than refusing to parse them — the same stance this
    category's other gates take.  ``path`` is the place it aimed at in
    whatever spelling it used, ``operation`` is the operation it asked for
    by name, and ``service`` names the caller that made the attempt —
    carried for the audit line only, never to widen the zone, because the
    mount is the same for every service.
    """

    __slots__ = ("operation", "path", "service")

    def __init__(self, *, path: str, operation: str, service: str = "") -> None:
        self.path = path
        self.operation = operation
        self.service = service

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ZoneAccessAttempt(path={self.path!r}, "
            f"operation={self.operation!r}, service={self.service!r})"
        )


class ZoneAccessDecision:
    """The gate's whole answer: allowed, why, and in what words.

    ``allowed`` is typed as a bool because the decision is the audit record
    a caller reads, and "was it allowed" is the question an auditor asks of
    any gate; under this law a write at the zone is always ``False``.
    ``detail`` carries the operator-facing sentence — the one place the
    mechanism explains itself at answer time, naming the path, the
    operation, the service, and the zone or the place that decided.
    """

    __slots__ = ("allowed", "detail", "reason")

    def __init__(self, *, allowed: bool, reason: ZoneAccessReason, detail: str) -> None:
        self.allowed = allowed
        self.reason = reason
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ZoneAccessDecision(allowed={self.allowed}, reason={self.reason!r})"


def _is_zone_write_target(candidate: str | None, zone: ZoneGeometry) -> tuple[bool, bool]:
    """Whether ``candidate`` is inside the zone, and whether it covers it.

    Returns ``(inside, covers)``: ``inside`` is whether the path lies at or
    under a member root (a write to the zone's content), and ``covers`` is
    whether the path is a member root or an ancestor of one (a write on the
    parent, which reaches every child).  ``None`` — a path that resolves
    nowhere the zone pinned — is neither.
    """
    if candidate is None:
        return False, False
    inside = any(_at_or_under(member, candidate) for member in zone.paths)
    covers = any(_at_or_under(candidate, member) for member in zone.paths)
    return inside, covers


def authorize_zone_access(
    attempt: ZoneAccessAttempt, geometry: ZoneGeometry | None = None
) -> ZoneAccessDecision:
    """Answer one access attempt against the immutable zone.

    The order of the checks is the order of the feature's sentence.  The
    zone is settled first, *before* anything is served: the rejection named
    for the immutable zone is the feature's own headline, and §2's
    "read-only for every service" outranks everything — even a rogue,
    hand-assembled path can never read as permission to write the zone.  A
    write inside a member or covering one is refused.  The mount point is
    settled second — the mount has no outside.  The operation is settled
    third — the zone answers nothing it cannot name.  Everything else is a
    read, and reads are served.

    ``geometry`` defaults to the committed zone (:func:`mount_geometry`),
    the same six roots feature 148's committed grant pins, so the gate and
    the credential law protect exactly one geometry.
    """
    zone = geometry if geometry is not None else mount_geometry()
    candidate = _normalize_path(attempt.path)
    inside, covers = _is_zone_write_target(candidate, zone)
    is_write = attempt.operation in WRITE_OPERATIONS

    if is_write and (inside or covers):
        member = zone.covering(attempt.path)
        if covers and not inside:
            direction = (
                f"covering the immutable zone ({zone.name!r}) — a write on "
                f"the parent reaches every child"
            )
        elif member is not None:
            direction = (
                f"inside the immutable zone ({zone.name!r}), member {member!r}"
            )
        else:
            direction = f"inside the immutable zone ({zone.name!r})"
        operation = (
            repr(attempt.operation)
            if attempt.operation in WRITE_OPERATIONS
            else f"{attempt.operation!r}, not of the read-only vocabulary"
        )
        return ZoneAccessDecision(
            allowed=False,
            reason=ZoneAccessReason.INSIDE_IMMUTABLE_ZONE,
            detail=(
                f"access attempt from service {attempt.service!r} to "
                f"{attempt.path!r} (operation {operation}) is rejected: the "
                f"place is {direction}. §2 fixes the posture absolutely — "
                f"the immutable zone is mounted read-only for every service; "
                f"enforce with filesystem permissions, never with prompt "
                f"instructions — and §1 P1 keeps the zone one LLM-authored "
                f"code has no write credential for, so there is no spelling "
                f"this attempt could have used instead: not append, not the "
                f"trial ledger's own verb, whose appends are the release "
                f"process's to make; not chmod, which would be reaching for "
                f"the read-only mount itself (feature 147)."
            ),
        )

    if candidate is None or not zone.under_mount_point(candidate):
        # Not a place the mount can serve: not absolute, or not under the
        # mount point.  The mount has no outside.
        return ZoneAccessDecision(
            allowed=False,
            reason=ZoneAccessReason.OUTSIDE_MOUNT_POINT,
            detail=(
                f"access attempt from service {attempt.service!r} to "
                f"{attempt.path!r} (operation {attempt.operation!r}) is "
                f"rejected: the place is not under the immutable zone's "
                f"mount point ({MOUNT_POINT!r}). The mount serves only the "
                f"zone, and a path outside it is refused rather than "
                f"resolved to a disk location that could be anywhere — "
                f"outside is where staging lives (feature 147)."
            ),
        )

    if (
        attempt.operation != ""
        and attempt.operation not in WRITE_OPERATIONS
        and attempt.operation not in READ_OPERATIONS
    ):
        # An operation the closed vocabulary cannot name.  The zone answers
        # nothing it cannot name — an unnamed verb is not a read, and the
        # mount certifies nothing about it.
        return ZoneAccessDecision(
            allowed=False,
            reason=ZoneAccessReason.UNNAMED_OPERATION,
            detail=(
                f"access attempt from service {attempt.service!r} to "
                f"{attempt.path!r} (operation {attempt.operation!r}) is "
                f"rejected: the operation is not of the read-only "
                f"vocabulary ({', '.join(READ_OPERATIONS + WRITE_OPERATIONS)}). "
                f"The zone answers nothing it cannot name — an unnamed verb "
                f"is not a read — so the attempt holds no capability the "
                f"mount can serve (feature 147)."
            ),
        )

    # Everything else is served.  A read at a place the mount serves is the
    # reachable branch for every legitimate read — a read-only mount is not
    # a read-nothing one (§2's Z0 is readable).  A write at a place outside
    # the zone is not the zone's to refuse — the mount governs only the
    # zone, and a write elsewhere is feature 148's half, not this one.
    if is_write:
        return ZoneAccessDecision(
            allowed=True,
            reason=ZoneAccessReason.BY_LOCATION,
            detail=(
                f"access attempt from service {attempt.service!r} to "
                f"{attempt.path!r} (operation {attempt.operation!r}) is "
                f"allowed: the place is outside the immutable zone "
                f"({zone.name!r}), and the read-only mount governs only the "
                f"zone — a write elsewhere is not the zone's to refuse "
                f"(feature 147)."
            ),
        )
    return ZoneAccessDecision(
        allowed=True,
        reason=ZoneAccessReason.BY_READ,
        detail=(
            f"access attempt from service {attempt.service!r} to "
            f"{attempt.path!r} (operation {attempt.operation!r}) is allowed: "
            f"it is a read, and a read-only mount is not a read-nothing one "
            f"— §2's immutable zone is readable, only its writes are refused "
            f"(feature 147)."
        ),
    )
