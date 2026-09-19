"""The sealing service: staging in, immutable snapshot directory out.

docs/nullius-tech-architecture.md §4.1-§4.2 describe the flow this module
implements: ingest workers append into a writable staging area, and on a
schedule that content is sealed into an immutable snapshot directory named
``<sealed_at>_<snapshot_hash[:6]>`` under the lake's ``snapshots/`` root.
The evaluator only ever opens sealed snapshots; staging never appears on its
mount path. This service owns the *write* side of that boundary.

**Immutability is enforced at three layers**, because a property announced
once and enforced nowhere is a comment, not a guarantee:

1. *Publication is atomic.* A seal builds its tree under a hidden
   ``.sealing-<random>`` working directory inside ``snapshots/`` and then
   renames it into place. ``rename(2)`` of a directory is atomic on POSIX,
   so no reader — and no crash — ever observes a half-written directory
   under a sealed name. An interrupted seal leaves at worst a stray working
   directory, never a corrupt snapshot.
2. *The published bytes are read-only.* Every file is persisted mode
   ``0444`` and every directory ``0555`` before the rename, so an ordinary
   write through a sealed path fails with ``PermissionError`` at the
   filesystem itself. (An owner can chmod this away; this layer is tripwire
   and contract, with the API layer doing the structural work.)
3. *The API has no mutating surface and refuses overwrites.* Sealing a name
   that already exists re-reads the existing tree and either returns the
   identical record (an idempotent re-seal — the schedule crashed after the
   rename, say) or raises :class:`SnapshotAlreadySealedError` when the bytes
   differ. There is no code path that edits, extends, or replaces a sealed
   directory, and the returned record is frozen with a read-only file
   mapping (see ``_records``).

Staging is *copied*, never moved or emptied: the §4.1 contract keeps staging
append-only and owned by the ingest workers, so a seal is a pure read from
their side.

The default snapshot hash is the content digest of the staged files (the
``sorted(file_hashes)`` term of the §4.2 formula — see ``_content``); a
caller who already knows the full hash — the manifest feature, or a seal
retry replaying a decided identity — supplies it via ``snapshot_hash=`` and
the seal honours it, deriving the directory's prefix from it. Whatever hash
names the directory, the seal verifies it against nothing else: the hash is
the identity, and identity is the caller's to assert.
"""

from __future__ import annotations

import errno
import os
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional, Union

from app.module_loader import find_workspace_root

from ._content import content_digest, walk_content
from ._errors import (
    SnapshotAlreadySealedError,
    SnapshotError,
    SnapshotNotFoundError,
)
from ._mount import SnapshotMount, materialize_read_only
from ._naming import (
    normalize_snapshot_hash,
    parse_snapshot_name,
    resolve_sealed_at,
    snapshot_name,
)
from ._records import SealedSnapshot, SnapshotRef

__all__ = ["LAKE_ROOT_ENV", "SnapshotService"]

#: Environment variable naming the lake root (documented in app_spec.xml
#: prerequisites; the shared fixtures in tests/conftest.py set it per test).
LAKE_ROOT_ENV = "LAKE_ROOT"

# Modes applied to a published snapshot: files readable by all, writable by
# no one; directories traversable and listable, modifiable by no one.
_FILE_MODE = 0o444
_DIRECTORY_MODE = 0o555

# rename(2) onto an existing non-empty directory reports one of these.
_COLLISION_ERRNOS = frozenset({errno.EEXIST, errno.ENOTEMPTY})


class SnapshotService:
    """Seals staged content into the lake's immutable ``snapshots/`` tree.

    Bound to a lake root at construction (see :meth:`from_env`). All paths
    the service touches live under that root: ``snapshots/`` for sealed
    output, ``staging/`` as the default seal source. Construction performs
    no I/O — the service is safe to build at composition time in any
    environment; directories are created on demand by the operations that
    need them.
    """

    def __init__(self, lake_root: Union[str, os.PathLike[str]]) -> None:
        if isinstance(lake_root, str) and not lake_root.strip():
            # Path("") would silently become "." — sealing into the current
            # directory is never what a caller meant.
            raise SnapshotError("lake root must be a non-empty path")
        self._lake_root = Path(lake_root).expanduser()

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "SnapshotService":
        """Resolve the lake root the way the rest of the system states it.

        ``LAKE_ROOT`` wins when set (an empty or whitespace-only value
        counts as unset, mirroring the shared fixtures' treatment of
        ``TEST_DATABASE_URL``). Otherwise the root defaults to ``lake/``
        beside the workspace root — the location §4.2 draws — located via
        the factory's workspace discovery rather than a hard-coded guess,
        so the default can never silently point somewhere the declaration
        does not cover. With neither available the service refuses to
        guess: raising a clear error beats sealing into ``/``.
        """
        source = os.environ if env is None else env
        raw = source.get(LAKE_ROOT_ENV, "").strip()
        if raw:
            return cls(Path(raw))
        workspace_root = find_workspace_root()
        if workspace_root is not None:
            return cls(workspace_root / "lake")
        raise SnapshotError(
            f"{LAKE_ROOT_ENV} is not set and no uv workspace root was found "
            "above this package; set LAKE_ROOT to the lake root (§4.2)"
        )

    # -- Paths --------------------------------------------------------------

    @property
    def lake_root(self) -> Path:
        """The lake root this service writes under."""
        return self._lake_root

    @property
    def snapshots_root(self) -> Path:
        """Where sealed, immutable snapshots live (§4.2)."""
        return self._lake_root / "snapshots"

    @property
    def staging_root(self) -> Path:
        """The writable staging area; the default seal source (§4.2)."""
        return self._lake_root / "staging"

    # -- Sealing ------------------------------------------------------------

    def seal(
        self,
        source: Optional[Union[str, os.PathLike[str]]] = None,
        *,
        sealed_at: Optional[Union[datetime, str]] = None,
        snapshot_hash: Optional[str] = None,
    ) -> SealedSnapshot:
        """Persist ``source`` as a sealed snapshot and return its record.

        ``source`` defaults to the lake's staging area — the §4.1
        seal-on-schedule flow. ``sealed_at`` defaults to now (UTC, second
        resolution); a caller driving the schedule supplies the instant.
        ``snapshot_hash`` defaults to the content digest of the staged
        files; supply the full 64-hex hash to seal under an identity decided
        elsewhere (the manifest feature's formula, or a retry replaying a
        prior decision).

        Re-sealing the *same* content under the same name is idempotent and
        returns the existing record; re-sealing *different* content under a
        name that exists raises :class:`SnapshotAlreadySealedError` and
        leaves the existing directory untouched. The source is copied, not
        consumed.
        """
        source_path = (
            self.staging_root if source is None else Path(source).expanduser()
        )
        files = walk_content(source_path)
        full_hash = (
            content_digest(files)
            if snapshot_hash is None
            else normalize_snapshot_hash(snapshot_hash)
        )
        instant = resolve_sealed_at(sealed_at)
        name = snapshot_name(instant, full_hash)
        final = self.snapshots_root / name

        if final.exists():
            # The name is taken: identical bytes make this an idempotent
            # re-seal, different bytes an immutability violation.
            return self._existing_or_conflict(final, instant, full_hash, files)

        self.snapshots_root.mkdir(parents=True, exist_ok=True)
        working = self.snapshots_root / f".sealing-{uuid.uuid4().hex}"
        try:
            _publish_tree(source_path, files, working)
            try:
                os.rename(working, final)
            except OSError as exc:
                if exc.errno not in _COLLISION_ERRNOS:
                    raise
                # Lost a race for the name: fall through to the same
                # identity check the pre-flight path performs.
                return self._existing_or_conflict(
                    final, instant, full_hash, files
                )
        finally:
            _discard_working_tree(working)
        return SealedSnapshot(
            sealed_at=instant, snapshot_hash=full_hash, path=final, files=files
        )

    def _existing_or_conflict(
        self,
        final: Path,
        instant: datetime,
        full_hash: str,
        files: Mapping[str, str],
    ) -> SealedSnapshot:
        """Decide an already-named directory: idempotent return or refusal.

        The existing tree is re-read and compared file-for-file. Identical
        mappings mean the very seal the caller is retrying already happened,
        so the caller gets its record back. Anything else — different bytes,
        different file set — is a genuine collision on an immutable name and
        is refused with the conflicting directory named in the error.

        One documented limit: until manifests persist the full hash, an
        existing directory only proves its *prefix* through its name. Two
        calls supplying different full hashes that share six characters and
        identical bytes are therefore treated as the same snapshot, and the
        current call's hash is the one recorded. The manifest feature pins
        identity to bytes on disk and closes this gap.
        """
        if not final.is_dir():
            raise SnapshotAlreadySealedError(
                f"{final} exists but is not a snapshot directory; refusing "
                "to seal over it"
            )
        existing = walk_content(final)
        if existing == files:
            return SealedSnapshot(
                sealed_at=instant,
                snapshot_hash=full_hash,
                path=final,
                files=files,
            )
        raise SnapshotAlreadySealedError(
            f"immutable snapshot {final.name} already exists with different "
            f"content ({len(existing)} files sealed vs {len(files)} staged); "
            "sealed directories are never overwritten"
        )

    # -- Reading ------------------------------------------------------------

    def open(self, name: str) -> SnapshotRef:
        """Return the sealed snapshot addressed by a canonical directory name.

        The name is validated against the strict naming contract before it
        ever becomes a path, so traversal such as ``../staging`` is rejected
        as a malformed name rather than resolved. A name that parses but
        names nothing raises :class:`SnapshotNotFoundError`.
        """
        parse_snapshot_name(name)  # validation only; the ref re-parses lazily
        path = self.snapshots_root / name
        if not path.is_dir():
            raise SnapshotNotFoundError(
                f"no sealed snapshot named {name!r} under {self.snapshots_root}"
            )
        return SnapshotRef(name=name, path=path)

    def mount(self, name: str, *, reassert_modes: bool = True) -> SnapshotMount:
        """Mount a sealed snapshot read-only, by canonical directory name.

        This is the evaluator's door (§4.2: *"a snapshot is sealed, hashed,
        and mounted read-only; the evaluator can only open sealed
        snapshots"*). The name goes through the same strict parser
        :meth:`open` uses, so a request naming a staging path — or any name
        that is not ``<sealed_at>_<hash prefix>`` — is refused as a
        malformed name rather than resolved; a canonical name that names
        nothing raises :class:`SnapshotNotFoundError`. Only then is a mount
        built.

        Opening the mount re-asserts the sealed modes across the tree (see
        :func:`snapshot.materialize_read_only`), which is a tightening, never
        a grant: a snapshot whose permissions drifted — a copy, a restore —
        is put back under the contract before anyone reads through it.
        ``reassert_modes=False`` skips that pass for a read-only filesystem
        where the walk would be wasted work; the mount's own refusals are
        structural and do not depend on it.

        Writes through the returned mount — and through any path it hands
        out — raise :class:`~snapshot.SnapshotReadOnlyError`, a
        ``PermissionError`` naming the operation and the sealed path.
        """
        ref = self.open(name)
        corrections = materialize_read_only(ref.path) if reassert_modes else 0
        return SnapshotMount(
            name=ref.name,
            path=ref.path,
            modes_reasserted=reassert_modes,
            modes_corrected=corrections,
        )

    def mounted(self) -> list[SnapshotMount]:
        """Mount every sealed snapshot in this lake, sorted by name.

        The sweep an evaluator host performs at start-up — or an operator
        after a restore — and the moment the mode re-assertion pays for
        itself, since it visits every snapshot's tree once.
        """
        return [self.mount(name) for name in self.sealed()]

    def sealed(self) -> list[str]:
        """List the sealed snapshots in this lake, sorted by name.

        Only directories whose names parse as canonical snapshot names are
        reported: working directories from interrupted seals and any stray
        files under ``snapshots/`` are not snapshots and stay invisible
        here. A missing ``snapshots/`` root is simply an empty lake.
        """
        if not self.snapshots_root.is_dir():
            return []
        names = [
            entry.name
            for entry in self.snapshots_root.iterdir()
            if entry.is_dir() and _parses(entry.name)
        ]
        return sorted(names)


def _parses(name: str) -> bool:
    try:
        parse_snapshot_name(name)
    except Exception:
        return False
    return True


def _publish_tree(
    source: Path, files: Mapping[str, str], working: Path
) -> None:
    """Copy staged files into ``working`` and freeze them read-only.

    Copies by content (``copyfile``), not metadata: a staged file's mode is
    staging's business; a sealed file's mode is the contract (``0444``).
    Directories are made read-only only after their contents are complete,
    and the working root itself is frozen last, so the tree that the rename
    publishes is already non-writable at every level the moment it appears
    under its sealed name.
    """
    working.mkdir(parents=True)
    for relative in files:
        destination = working / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
        os.chmod(destination, _FILE_MODE)
    for directory, _subdirs, _files in os.walk(working):
        os.chmod(directory, _DIRECTORY_MODE)


def _discard_working_tree(working: Path) -> None:
    """Remove a working directory if it still exists, read-only modes and all.

    After a successful rename the working path is gone and this is a no-op;
    after a failure (or a lost race) the tree may carry the frozen modes,
    which plain ``rmtree`` cannot delete — parent directories without a
    write bit refuse entry removal. The callback re-grants the bits it
    needs and retries the failing operation.
    """
    if not working.exists():
        return

    def _writable_retry(
        operation: Callable[[str], object], path: str, _exc_info: object
    ) -> None:
        target = Path(path)
        # Deleting an entry needs write permission on its parent (and on
        # directories being emptied); grant both, then retry as asked.
        if target.is_dir():
            os.chmod(target, 0o700)
        parent = target.parent
        if parent.is_dir():
            os.chmod(parent, 0o700)
        operation(path)

    shutil.rmtree(working, onexc=_writable_retry)
