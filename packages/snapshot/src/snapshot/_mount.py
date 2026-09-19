"""Read-only mounts over sealed snapshots — writes fail, and say why.

docs/nullius-tech-architecture.md §4.2 states the contract this module
implements in one sentence: *"A snapshot is sealed, hashed, and mounted
read-only. **The evaluator can only open sealed snapshots.** Staging is not
on its mount path at all."* Feature 30 (``_service``) built the write side
of the boundary — the immutable directory. This is the read side: the mount
the evaluator opens, which refuses every write attempted against a sealed
path with a permission error *message* (app_spec.xml feature 34).

**Where the refusal comes from.** Sealing already persists every file
``0444`` and every directory ``0555``, so a write attempt — ``open(path,
"w")``, ``path.write_bytes``, ``shutil.copyfile``, ``os.remove``, creating a
new file in a sealed directory — hits the filesystem and raises a genuine
``PermissionError``. That holds whether or not anyone uses this module: it
is a property of the bytes on disk, not of an API.

So why a mount object? Because "open the file and hope the OS refuses" is
not an interface. It answers no question a caller has — *what is on this
mount? does this snapshot contain that symbol?* — and it fails in the wrong
register: a caller cannot tell a sealed path from a staging path from a
typo, because all three raise the same ``FileNotFoundError``/``EACCES``
with no statement of contract. The mount is that interface, and it is
**defence in depth over the same invariant, in three layers**:

1. *The name is parsed before it becomes a path.* A mount can only be built
   for a canonical ``<sealed_at>_<hash prefix>`` name that resolves to a
   real directory under the lake's ``snapshots/`` root (``_naming``,
   ``SnapshotService.open``). There is no way to mount ``../staging``.
2. *Writes are refused structurally, before any syscall.* Every mutating
   verb on the mount — and on every path it hands out — raises
   :class:`~snapshot.SnapshotReadOnlyError` naming the sealed path, the
   operation, and the seal that covers it. Nothing is attempted first and
   denied second; there is no code path from ``write_bytes`` to ``open(2)``.
3. *Reads carry no write permission even if the modes are lost.* The file
   handles handed out are opened ``O_RDONLY`` and carry no write intent;
   and mounting runs :func:`materialize_read_only` over the tree, so a
   snapshot whose bits were loosened (a copy that dropped them, a restore
   that ignored them — both real failure modes) is tightened back to the
   sealed contract each time it is mounted. That re-assertion is a
   *tightening only*: it clears write bits and never grants one.

**What layer 1 does not cover, stated exactly.** The ``0444``/``0555`` modes
stop every operation that would *change or destroy the sealed bytes* —
verified against raw paths, not just this API. They do not stop three
operations, and no file mode can, because each is governed by ownership or
by the *parent* directory's mode rather than by the mode of the node itself:

* ``chmod`` by the file's owner. A process running as the sealing user can
  widen ``0444`` to ``0666`` and then write. This is the real crack, and it
  is why layer 3 exists: the widening is detected and undone by the next
  mount (``modes_corrected`` counts it), so the exposure lasts only until
  the snapshot is next mounted. A tighter loop is feature 36's corruption
  check, which compares bytes against the recorded hashes rather than
  trusting modes at all.
* ``touch`` / ``os.utime`` by the owner, which change timestamps but cannot
  change content.
* ``rename``/``unlink`` of the snapshot *directory*, which needs write
  permission on ``snapshots/`` — and that parent must stay writable, since
  it is where new seals are published. Removing a snapshot this way affects
  availability, not integrity: the bytes of a *named* snapshot are never
  rewritten in place.

Closing those three completely means mounting the filesystem read-only at
the kernel level (``mount -o ro``, a read-only bind mount, a container
volume) and giving the sealed tree its own ownership — which is exactly what
the trust-zone feature (app_spec.xml feature 147, ``infra/security/**``)
owns, and what §2's table means by *"enforced with filesystem permissions
and network policy, never with prompt instructions"*. That is deliberately
not attempted here: a stdlib package cannot mount anything, and a simulated
read-only mount that merely resembled one would be worse than an honest
boundary. What this module guarantees is that **every write attempt through
the mount is rejected with a permission error message** (feature 34's
words), and that the underlying bytes resist every content-changing write
from any direction.

**Symlinks are refused on read as well as on write.** Sealing refuses
symlinks outright (``_content.walk_content`` — a sealed snapshot addresses
its own bytes, never somebody else's), so a *sealed* tree has none by
construction. But the mount is a security boundary in the direction the seal
cannot reach: a link planted inside a snapshot *after* sealing — reachable
through the owner-``chmod`` crack described above — would, if followed, put
``staging`` or anything else on the host onto the mount path, exactly what
§4.2 says must never happen. So every read refuses a symlink instead of
following it, for a final component (``is_symlink``) and for an intermediate
one (``resolve`` containment, which ``is_symlink`` on the full path cannot
see). Reads that bypass Python-level resolution — :meth:`SnapshotMount.open_at`
— pass ``O_NOFOLLOW`` so the *kernel* enforces it atomically rather than
leaving a check-then-open race. Write refusals deliberately keep their
permission-error wording regardless of a path's shape: feature 34's contract
is about writes, and a symlink guard must not change what a write reports.

**Read-only is not read-nothing.** A read-only mount is still a mount: it
reads files, lists them, and answers partition queries (§4.2's
``bars/symbol=BTCUSDT/date=.../`` layout, feature 37's partition pruning).
Refusing those would be a different, and useless, feature.
"""

from __future__ import annotations

import errno
import hashlib
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional, Union

from ._content import CHUNK_SIZE, sha256_file, walk_content
from ._errors import SnapshotContentError, SnapshotReadOnlyError
from ._naming import parse_snapshot_name

__all__ = [
    "READ_ONLY_OPERATIONS",
    "ReadOnlyPath",
    "SnapshotMount",
    "materialize_read_only",
    "permission_denied",
]

#: Modes a mounted snapshot carries, matching what sealing persists: files
#: readable by all and writable by none, directories traversable and
#: listable and modifiable by no one (see ``_service``).
_FILE_MODE = 0o444
_DIRECTORY_MODE = 0o555

#: Mode bits that, if set anywhere under a sealed tree, are wrong. The mount
#: clears exactly these and nothing else — a tightening, never a grant.
_UNSEALED_BITS = 0o222

#: The mutating verbs this module refuses by name, used to build one
#: consistent refusal message per operation. Kept as a tuple so the
#: message and the guard cannot drift apart.
READ_ONLY_OPERATIONS = (
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


def permission_denied(
    path: Union[str, os.PathLike[str]], operation: str, mount_name: str
) -> SnapshotReadOnlyError:
    """Build the refusal for a write against a sealed path.

    The message states the operation, the sealed path, and the mount the
    path came from — the three facts an operator needs to tell a *sealed*
    refusal from an ordinary permissions accident:

        [Errno 13] Permission denied: write to
        /lake/snapshots/2026-09-01T00:00:00Z_a3f91c/bars/part-0.parquet
        refused: sealed snapshot 2026-09-01T00:00:00Z_a3f91c is mounted
        read-only (§4.2); staging is the writable area, not a sealed snapshot
    """
    location = os.fspath(path)
    message = (
        f"Permission denied: {operation} to {location} refused: sealed "
        f"snapshot {mount_name} is mounted read-only "
        "(docs/nullius-tech-architecture.md §4.2); staging is the writable "
        "area, not a sealed snapshot"
    )
    return SnapshotReadOnlyError(errno.EACCES, message, location)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _resolve_relative(relation: str) -> Optional[str]:
    """Canonicalise a POSIX relative path, or ``None`` if it escapes.

    Returns the cleaned relative path (``"bars/./part"`` -> ``"bars/part"``,
    ``"."`` -> ``""``) when it stays inside the mount, and ``None`` when it
    would resolve outside it — an absolute path, a ``..`` segment, or a
    path that walks off the top. Callers turn ``None`` into a refusal; the
    traversal never reaches a ``Path``.
    """
    parts: list[str] = []
    for part in PurePosixPath(relation).parts:
        if part == "/" or part == "..":
            return None
        if part in (".", ""):
            continue
        parts.append(part)
    return "/".join(parts)


@dataclass(frozen=True)
class ReadOnlyPath:
    """A path inside a mounted snapshot. Immutable, and read-only by type.

    Every mutating verb ``Path`` offers is rewritten here to raise
    :class:`~snapshot.SnapshotReadOnlyError` instead of touching the disk:
    ``write_bytes``, ``write_text``, ``unlink``, ``rmdir``, ``mkdir``,
    ``rename``, ``replace``, ``chmod``, ``touch``, ``symlink_to``,
    ``link_to``, and ``open`` for any write mode. So the standard operations
    fail *with an explanation* rather than at the kernel — and a caller who
    converts the path with ``Path(ro_path)`` lands back on layer 0, where the
    ``0444``/``0555`` modes stop the write anyway.

    Reading is fully supported: :meth:`read_bytes`, :meth:`read_text`,
    :meth:`open("rb")`, :meth:`stat`, :meth:`exists`, :meth:`glob`,
    :meth:`sha256` and the rest, handed to the underlying path. This is a
    *read-only* mount, not a read-nothing one.
    """

    #: Absolute resolved location of this path inside the sealed tree.
    path: Path
    #: The mount's canonical snapshot name, for refusal messages.
    mount_name: str
    #: POSIX path relative to the snapshot root (``""`` for the root).
    relative: str

    # -- Refusal ------------------------------------------------------------

    def _refuse_write(self, operation: str) -> SnapshotReadOnlyError:
        return permission_denied(self.path, operation, self.mount_name)

    def _refuse_symlink(self) -> SnapshotReadOnlyError:
        return SnapshotContentError(
            f"{self.path} is a symlink; a sealed snapshot addresses its own "
            "bytes, so the mount neither follows it nor reads through it — "
            "following one would put whatever it points at (staging, another "
            "snapshot, anywhere on the host) on the mount path"
        )

    def _checked(self, path: Path) -> Path:
        """Return ``path`` if it is a real node inside the snapshot, else refuse.

        Nothing that reaches the filesystem through this class passes
        unchecked. Two escapes are possible, and they need different checks:

        * *A symlinked final component* — ``escape`` pointing at
          ``/lake/staging/secret.parquet``. Caught by the ``is_symlink`` call,
          which refuses the link instead of following it.
        * *A symlinked intermediate component* — ``linked -> /lake/staging/bars``,
          so ``linked/part.parquet`` contains no ``..`` at all and yet resolves
          outside the snapshot. ``is_symlink`` on the *full* path cannot see
          this — the final component is an ordinary file. Containment of the
          fully-resolved path is what answers it, and it is the check that
          makes the class robust against a *chain* of links too.

        Neither check may preempt a write refusal: :meth:`write_bytes` and
        friends raise before calling this, so a write to a sealed path always
        reports the permission error feature 34 specifies, whatever the path's
        shape. ``resolve(strict=False)`` is used because a path may legitimately
        not exist yet (a caller probing for a file), and non-existence is not an
        escape. The comparison is for containment only — the returned path is
        the caller's own, so a snapshot stays addressed by its name rather than
        by its physical location.
        """
        if path.is_symlink():
            raise self._refuse_symlink()
        if not _is_within(path.resolve(strict=False), self.root().resolve(strict=False)):
            raise self._refuse_symlink()
        return path

    def root(self) -> Path:
        """The snapshot directory this path lives under.

        Derived from ``relative`` rather than re-parsed from the name: the
        root is simply ``path`` with as many trailing components removed as
        ``relative`` has. That keeps the containment check independent of the
        naming contract and correct for the root itself (``relative == ""``).
        """
        depth = len([part for part in self.relative.split("/") if part])
        root = self.path
        for _ in range(depth):
            root = root.parent
        return root

    def _relative_to(self, relation: Union[str, os.PathLike[str]]) -> str:
        """Return ``relation`` as a relative POSIX path, refusing escapes.

        A caller reaching for an absolute path or a ``..`` walk is refused
        as a write would be — the mount has no outside, and "outside" is
        where staging lives. The refusal is a read-only refusal, so a
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
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        newline: Optional[str] = None,
    ):
        """``Path.open`` with every write mode refused up front.

        ``"r"``/``"rb"`` behave exactly as ``Path.open`` does. Any mode
        carrying write intent — ``w``, ``a``, ``x``, ``+`` — raises
        :class:`~snapshot.SnapshotReadOnlyError` *before* the underlying
        ``open`` is called, so the refusal is the mount's decision, not the
        kernel's, and it names the operation (``write``/``append``).

        A read is checked first, so a symlink planted inside the snapshot is
        refused here rather than followed to whatever it points at.

        A mode that is neither an obvious read nor an obvious write falls
        through to ``Path.open``, which rejects it with its usual
        ``ValueError``. Guessing at an unrecognised mode would be worse than
        passing it on: the one mode that matters is ``"+"``, and that is
        already refused.
        """
        operation = _write_intent(mode)
        if operation is not None:
            raise self._refuse_write(f"{operation} to {self.path}")
        self._checked(self.path)
        return self.path.open(mode, buffering, encoding, errors, newline)

    def write_bytes(self, data: bytes) -> int:
        """Refused: sealed snapshots are immutable."""
        raise self._refuse_write("write")

    def write_text(
        self, data: str, encoding: Optional[str] = None, errors: Optional[str] = None
    ) -> int:
        """Refused: sealed snapshots are immutable."""
        raise self._refuse_write("write")

    def unlink(self, missing_ok: bool = False) -> None:
        """Refused: a sealed snapshot's bytes are never removed."""
        raise self._refuse_write("unlink")

    def rmdir(self) -> None:
        """Refused: a sealed snapshot's directories are never removed."""
        raise self._refuse_write("rmdir")

    def mkdir(
        self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """Refused: a sealed snapshot's shape is fixed when it is sealed."""
        raise self._refuse_write("mkdir")

    def rename(self, target: Union[str, os.PathLike[str]]) -> None:
        """Refused: sealed paths are never renamed or moved."""
        raise self._refuse_write("rename")

    def replace(self, target: Union[str, os.PathLike[str]]) -> None:
        """Refused: sealed paths are never replaced."""
        raise self._refuse_write("rename")

    def chmod(self, mode: int, **kwargs: object) -> None:
        """Refused: the mount's modes are the sealed contract, not a choice.

        The mount re-asserts these modes itself (see
        :func:`materialize_read_only`); a caller loosening them through the
        mount would be the one way to defeat layer 3, so it is closed here.
        """
        raise self._refuse_write("chmod")

    def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:
        """Refused: touching a sealed file would still be metadata mutation."""
        raise self._refuse_write("write")

    def symlink_to(self, target: Union[str, os.PathLike[str]]) -> None:
        """Refused: a sealed snapshot addresses its own bytes, never another's."""
        raise self._refuse_write("write")

    def link_to(self, target: Union[str, os.PathLike[str]]) -> None:
        """Refused: a second name for a sealed byte is still a write."""
        raise self._refuse_write("write")

    # -- Navigation: read-only, and never escaping the snapshot -------------

    def __truediv__(self, relation: Union[str, os.PathLike[str]]) -> "ReadOnlyPath":
        """Join a relative path, keeping the mount's guarantees.

        ``/`` is the only way to derive a new :class:`ReadOnlyPath`, so
        every path a caller holds came from the mount and carries its
        refusals. Escaping joins (``"../../staging"``, an absolute path)
        are refused rather than followed, and the joined path is re-checked
        to be inside the snapshot's own resolved directory.
        """
        cleaned = self._relative_to(relation)
        # The joined relative path is the *accumulation* of this join onto the
        # parent's, not the appended fragment alone. Getting this wrong is not
        # cosmetic: `root()` derives the containment root by stripping as many
        # components as `relative` has, so a truncated relative makes the root
        # walk too far up and the escape check compare against the wrong
        # directory.
        relative = f"{self.relative}/{cleaned}" if self.relative else cleaned
        candidate = (self.path / cleaned) if cleaned else self.path
        return ReadOnlyPath(
            path=candidate,
            mount_name=self.mount_name,
            relative=relative,
        )

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ReadOnlyPath({self.relative!r} inside {self.mount_name})"

    # -- Reads: the actual point of a read-only mount -----------------------

    @property
    def name(self) -> str:
        """The final path component (``""`` for the mount root)."""
        return self.path.name

    @property
    def suffix(self) -> str:
        return self.path.suffix

    def exists(self) -> bool:
        """Whether the node exists. A symlink is reported as absent.

        "Absent" is the honest answer for a node the mount refuses to follow:
        reporting ``True`` for something every read will then reject would
        make ``exists()`` a promise this class does not keep.
        """
        if self.path.is_symlink():
            return False
        try:
            self._checked(self.path)
        except SnapshotContentError:
            return False
        return self.path.exists()

    def is_file(self) -> bool:
        """Whether this is a regular file — false for a symlink or an escape."""
        if self.path.is_symlink():
            return False
        return self.path.is_file() and not self.path.is_symlink()

    def is_dir(self) -> bool:
        """Whether this is a directory — false for a symlink or an escape."""
        if self.path.is_symlink():
            return False
        return self.path.is_dir()

    def stat(self, **kwargs: object):
        """The underlying ``stat`` result, including the frozen mode bits.

        ``follow_symlinks`` is forced off: a caller asking about the mode of a
        sealed path wants the mode of *that* entry, and following a link out
        of the snapshot is exactly what this class refuses.
        """
        self._checked(self.path)
        kwargs.setdefault("follow_symlinks", False)
        return self.path.stat(**kwargs)

    def read_bytes(self) -> bytes:
        """Read the sealed bytes. Reading a sealed file is always allowed.

        Refused for a symlink or anything resolving outside the snapshot: a
        sealed snapshot addresses its own bytes, and following a planted link
        would put staging — or anywhere else on the host — on the mount path.
        """
        self._checked(self.path)
        return self.path.read_bytes()

    def read_text(self, encoding: Optional[str] = None, errors: Optional[str] = None) -> str:
        """Read the sealed bytes as text (UTF-8 by default)."""
        self._checked(self.path)
        return self.path.read_text(encoding=encoding, errors=errors)

    def iterdir(self) -> Iterator["ReadOnlyPath"]:
        """List this directory's entries as read-only paths, sorted."""
        return iter(sorted(self.children(), key=lambda entry: entry.relative))

    def children(self) -> tuple["ReadOnlyPath", ...]:
        """The entries of this directory as read-only paths, sorted by name.

        Entries are re-derived through :meth:`__truediv__`, so a listed
        entry is a :class:`ReadOnlyPath` with the same refusals as a path
        the caller built by hand. A symlink is listed — hiding it would make
        the mount's view of the tree a lie — but every read of it is refused,
        so listing one is all a caller can do with it.
        """
        if self.path.is_symlink():
            raise self._refuse_symlink()
        if not self.path.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, "not a directory", str(self.path))
        return tuple(
            self / entry.name
            for entry in sorted(self.path.iterdir(), key=_by_name)
        )

    def glob(self, pattern: str) -> tuple["ReadOnlyPath", ...]:
        """Match ``pattern`` under this directory, returning read-only paths.

        Where §4.2's partition layout is queried (``glob("symbol=*/date=*/*.parquet")``),
        the results are read-only paths like every other path the mount
        hands out.

        Matches are filtered to sealed nodes: a glob is a query for sealed
        files, and a symlink is not one — not as a final component, and not
        as a component *within* the match either (``glob("linked/*")`` must
        not report ``linked/part.parquet`` when ``linked`` is itself a link).
        The containment check in :meth:`_checked` is what catches the second
        case, so every match is put through it rather than only tested for
        being a link.
        """
        self._checked(self.path)
        matches: list[ReadOnlyPath] = []
        for match in sorted(self.path.glob(pattern), key=_by_name):
            candidate = ReadOnlyPath(
                path=match,
                mount_name=self.mount_name,
                relative=_relative_of(match, self),
            )
            if match.is_symlink():
                continue
            if not _is_within(match.resolve(strict=False), self.root().resolve(strict=False)):
                continue
            matches.append(candidate)
        return tuple(matches)

    def sha256(self, chunk_size: int = CHUNK_SIZE) -> str:
        """The sha256 of this file's sealed bytes, streamed.

        Same function the seal hashes with (``_content.sha256_file``), so a
        mount-side digest is directly comparable to a recorded manifest
        entry — which is what makes the corruption check of feature 36 a
        comparison rather than a re-implementation. ``chunk_size`` is
        exposed for callers hashing under a tighter memory budget; the
        default matches the seal's, which is what keeps digests identical.
        """
        self._checked(self.path)
        if chunk_size == CHUNK_SIZE:
            return sha256_file(self.path)
        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
        return digest.hexdigest()


def _write_intent(mode: str) -> Optional[str]:
    """Classify a ``Path.open`` mode string as a write, or ``None`` for read.

    ``"r"``/``"rb"`` and the extension modes Python allows alongside them
    (``"rt"``, ``"rU"``) are reads. ``"w"``, ``"x"`` and ``"a"`` are the
    three writing modes; ``"+"`` upgrades any of them to read-write and is
    treated as the write it is. An unrecognised mode is left to
    ``Path.open`` to reject.
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


def _by_name(entry: Path) -> str:
    return entry.name


def _relative_of(match: Path, base: "ReadOnlyPath") -> str:
    """The POSIX path of ``match`` relative to ``base``, for reporting."""
    try:
        return match.relative_to(base.path).as_posix()
    except ValueError:  # pragma: no cover - glob cannot leave its own base
        return match.name


# ---------------------------------------------------------------------------
# The mount
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotMount:
    """A sealed snapshot mounted read-only.

    Built only by :meth:`snapshot.SnapshotService.mount` (or
    :meth:`for_directory`), which validates the canonical name against the
    lake and resolves it to a real sealed directory. From then on the mount
    is the only handle a caller needs: the root is a
    :class:`ReadOnlyPath`, and every path derived from it inherits the same
    refusals.

    The mount is deliberately *not* a context manager that unmounts. There
    is nothing to release — it holds no file descriptor, no temporary
    directory, no OS mount — and a lifecycle that pretended otherwise would
    invite the belief that a snapshot stops being read-only after the
    ``with`` block. It is read-only because of the bytes on disk, forever.
    """

    #: Canonical snapshot directory name, ``<sealed_at>_<hash prefix>``.
    name: str
    #: The snapshot's directory under the lake's ``snapshots/`` root.
    path: Path
    #: Whether mounting re-applied the sealed modes (see
    #: :func:`materialize_read_only`). Reported for observability; it is
    #: never a permission the mount *rely* on — the refusals are structural.
    modes_reasserted: bool = False
    #: How many entries had their mode corrected by the re-assertion.
    modes_corrected: int = field(default=0)

    def __post_init__(self) -> None:
        # A mount that is not a directory is not a mount. Checked here so a
        # mount built by hand (tests, future readers) fails as loudly as one
        # built by the service.
        if not self.path.is_dir():
            raise SnapshotContentError(
                f"cannot mount {self.path}: not a sealed snapshot directory"
            )

    @classmethod
    def for_directory(
        cls, path: Union[str, os.PathLike[str]], *, reassert_modes: bool = True
    ) -> "SnapshotMount":
        """Mount a sealed directory the caller already resolved.

        The seam for callers that hold a path rather than a name — a
        scheduler that remembered the directory it sealed, a restore tool,
        a test. Refusing anything that is not a directory is the only
        precondition, so this can mount a snapshot from a lake whose
        service is not to hand.

        Unlike :meth:`snapshot.SnapshotService.mount` it has no lake to
        check the name against, so the name is taken from the directory
        itself and a directory that does not parse as a canonical snapshot
        name is refused: every path the mount hands out names a snapshot,
        and a mount whose name is a lie would break that.
        """
        directory = Path(path)
        if not directory.is_dir():
            raise SnapshotContentError(
                f"cannot mount {directory}: not a directory"
            )
        parse_snapshot_name(directory.name)  # a mount always has a real name
        corrections = (
            materialize_read_only(directory) if reassert_modes else 0
        )
        return cls(
            name=directory.name,
            path=directory,
            modes_reasserted=reassert_modes,
            modes_corrected=corrections,
        )

    # -- Identity -----------------------------------------------------------

    @property
    def sealed_at(self):
        """The sealing instant, parsed from the name (timezone-aware UTC)."""
        return parse_snapshot_name(self.name)[0]

    @property
    def hash_prefix(self) -> str:
        """The first six characters of the snapshot hash, from the name."""
        return parse_snapshot_name(self.name)[1]

    @property
    def root(self) -> ReadOnlyPath:
        """The mount's root as a read-only path.

        This is the handle everything else is derived from: ``mount.root /
        "bars" / "symbol=BTCUSDT"`` is a :class:`ReadOnlyPath`, never a
        plain ``Path``.
        """
        return ReadOnlyPath(path=self.path, mount_name=self.name, relative="")

    # -- Refusal, at the mount itself ---------------------------------------

    def _refuse_write(self, operation: str) -> SnapshotReadOnlyError:
        return permission_denied(self.path, operation, self.name)

    def _refuse_symlink(self, relative: str = "") -> SnapshotContentError:
        where = f"{self.path / relative}" if relative else str(self.path)
        return SnapshotContentError(
            f"{where} is a symlink; a sealed snapshot addresses its own bytes, "
            "so the mount neither follows it nor reads through it — following "
            "one would put whatever it points at (staging, another snapshot, "
            "anywhere on the host) on the mount path"
        )

    def write_bytes(self, data: bytes, relative: str = "") -> int:
        """Refused: writing into a mounted snapshot is never allowed."""
        raise self._refuse_write(f"write to {relative!r}" if relative else "write")

    def write_text(self, data: str, relative: str = "") -> int:
        """Refused: writing into a mounted snapshot is never allowed."""
        raise self._refuse_write(f"write to {relative!r}" if relative else "write")

    def mkdir(self, relative: str) -> None:
        """Refused: a mounted snapshot's shape is fixed when it is sealed."""
        raise self._refuse_write(f"mkdir {relative!r}")

    def unlink(self, relative: str) -> None:
        """Refused: nothing under a mounted snapshot is removed."""
        raise self._refuse_write(f"unlink {relative!r}")

    def rmdir(self, relative: str = "") -> None:
        """Refused: nothing under a mounted snapshot is removed."""
        raise self._refuse_write(f"rmdir {relative!r}")

    def rename(self, source: str, target: str) -> None:
        """Refused: a mounted snapshot is neither rearranged nor moved."""
        raise self._refuse_write(f"rename {source!r} -> {target!r}")

    def chmod(self, mode: int, relative: str = "") -> None:
        """Refused: the mount's modes are the sealed contract."""
        raise self._refuse_write("chmod")

    def copy_into(self, source: Union[str, os.PathLike[str]], relative: str = "") -> None:
        """Refused: no outside bytes enter a sealed snapshot."""
        raise self._refuse_write(f"copy-into {relative!r}" if relative else "copy-into")

    def _dir_fd(self) -> int:
        """A read-only descriptor for the mount root.

        Kept private and read-only on purpose: :meth:`open_at` is the only
        thing that uses it, and it opens ``O_RDONLY``, so the descriptor
        itself carries no write intent that a caller could inherit. (A
        descriptor opened ``O_RDONLY`` on a directory still *permits*
        ``openat`` writes, which is precisely why the guard is
        :meth:`open_at` refusing the mode rather than the descriptor's flags.)
        """
        return os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)

    def open_at(self, relative: str, mode: str = "rb", **kwargs: object):
        """Open a file inside the snapshot relative to the *root descriptor*.

        The descriptor form of :meth:`ReadOnlyPath.open`: the path is
        resolved by the kernel relative to the mount root's own descriptor,
        so no renamed parent can redirect it between the check and the open.
        Write modes are refused before the descriptor is even obtained, and
        the descriptor itself is opened ``O_RDONLY``, so a caller who reaches
        for ``os.write`` on the handle gets ``EBADF`` and not a silent
        mutation.

        ``O_NOFOLLOW`` is the load-bearing flag: it is this method's whole
        reason to exist alongside :meth:`ReadOnlyPath.read_bytes`. Because
        the *kernel* resolves the final component here, a Python-level
        ``is_symlink()`` check would be a time-of-check/time-of-use race — so
        the refusal is expressed as a flag the kernel honours atomically
        instead. Opening a symlink raises ``ELOOP``, which is translated to
        the same refusal the rest of the class raises.

        Directory entries are streams too (``os.scandir`` reads a directory
        through exactly this kind of descriptor), but this opens *files*;
        :meth:`SnapshotMount.root` and :meth:`children` are how the sealed
        tree is listed.
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
                raise self._refuse_symlink() from exc
            raise
        finally:
            os.close(root_fd)
        return os.fdopen(handle_fd, mode, **kwargs)

    # -- Reads --------------------------------------------------------------

    def read_bytes(self, relative: str) -> bytes:
        """Read a sealed file's bytes by snapshot-relative path."""
        return (self.root / relative).read_bytes()

    def read_text(
        self, relative: str, encoding: Optional[str] = None, errors: Optional[str] = None
    ) -> str:
        """Read a sealed file as text by snapshot-relative path."""
        return (self.root / relative).read_text(encoding=encoding, errors=errors)

    def files(self) -> Mapping[str, str]:
        """The sealed tree as ``{relative POSIX path: sha256}``.

        Exactly the mapping the seal computed and persisted, re-walked on
        the mount side, so a reader can compare the bytes it is about to
        consume against the identity the snapshot was sealed under (the
        corruption check of feature 36) without opening files itself.
        """
        return walk_content(self.path)

    def paths(self) -> tuple[ReadOnlyPath, ...]:
        """Every file in the snapshot as a read-only path, sorted by path."""
        return tuple(
            ReadOnlyPath(path=self.path / relative, mount_name=self.name, relative=relative)
            for relative in sorted(self.files())
        )

    def file_count(self) -> int:
        """How many regular files the mount holds."""
        return len(self.files())

    def total_bytes(self) -> int:
        """The total size of the sealed bytes, for operator visibility."""
        return sum(entry.stat().st_size for entry in self.root.glob("**/*") if entry.is_file())

    # -- Partition queries (§4.2 layout, feature 37's pruning) --------------

    def partitions(self, stream: str) -> tuple[str, ...]:
        """The ``symbol=…`` partition keys present under a stream directory.

        Sealed bars live at ``bars/symbol=BTCUSDT/date=…/part-*.parquet``
        (§4.2), so the mount can answer *which symbols are in this snapshot*
        from the directory names alone — the point of partitioning a
        snapshot by symbol and date is that this question is answerable
        without opening a single Parquet file.
        """
        return _partition_keys(self.root / stream, "symbol")

    def dates(self, stream: str, symbol: str) -> tuple[str, ...]:
        """The ``date=…`` partition keys for one symbol under a stream."""
        return _partition_keys(self.root / stream / f"symbol={symbol}", "date")

    def select(self, stream: str, symbol: str, date: str) -> tuple[ReadOnlyPath, ...]:
        """The Parquet parts for one symbol on one date, as read-only paths.

        The pruned query of §4.2: a request at one date returns that
        partition's files and nothing else, so a symbol's whole history
        never has to cross the mount boundary.
        """
        return tuple(self.root.glob(f"{stream}/symbol={symbol}/date={date}/*.parquet"))

    # -- Observability ------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"SnapshotMount(name={self.name!r}, read_only=True)"


def _partition_keys(base: ReadOnlyPath, key: str) -> tuple[str, ...]:
    """Read ``key=value`` directory names under ``base``, sorted by value.

    A missing base is an empty result, not an error: a snapshot that holds
    no ``borrow/`` stream has no borrow partitions, and saying so plainly is
    more useful than raising. Values are compared as strings, which is
    correct for the symbols and ISO dates the layout carries.
    """
    if not base.is_dir():
        return ()
    prefix = f"{key}="
    return tuple(
        sorted(
            entry.name[len(prefix) :]
            for entry in base.children()
            if entry.is_dir() and entry.name.startswith(prefix)
        )
    )


def materialize_read_only(
    root: Union[str, os.PathLike[str]], *, fix: bool = True
) -> int:
    """Re-apply the sealed modes across a snapshot tree; return corrections.

    Sealing persists files ``0444`` and directories ``0555``, and that is
    the primary enforcement of the read-only contract. But modes travel
    badly: a copy that did not preserve permissions, a restore from an
    archive that ignored them, or a build pipeline that untarred with a
    permissive umask can all leave a sealed tree writable by its owner —
    after which §4.2's guarantee is a comment rather than a property.

    Mounting therefore re-asserts the contract, and this is the function
    that does it: it walks the tree and **clears every write bit it finds**
    — ``current & ~0o222``, nothing more. That mask is the whole policy, and
    it is why this can only ever tighten: clearing bits cannot add one, so
    an entry that already denies writes is left exactly as it was, and a
    tree that an operator sealed *stricter* than the contract (a ``0400``
    file, say) is not quietly widened back to ``0444``. A snapshot whose
    read bits were stripped is the operator's to repair, not this walk's to
    guess at.

    It reports how many entries it corrected, so a caller — an operator, a
    monitor — can see a snapshot that had drifted rather than taking silence
    for health. With ``fix=False`` it changes nothing and only counts drift,
    which is what a verification sweep wants. A missing directory is
    return-zero: nothing to tighten is not an error.
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
            # Already at the contract, or stricter than it. Either way there
            # is no write to remove and nothing to report.
            continue
        corrections += 1
        if fix:
            os.chmod(candidate, current & ~_UNSEALED_BITS)
    return corrections
