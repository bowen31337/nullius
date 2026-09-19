"""The append-only ingest staging area — the write side of the seal boundary.

docs/nullius-tech-architecture.md §4.1-§4.2 fix the data-layer flow this
package implements: ingest workers append their output into a writable
*staging* area ``<lake>/staging``, and on a schedule that content is sealed
into an immutable snapshot directory under ``<lake>/snapshots``. The
evaluator only ever opens sealed snapshots; **staging never appears on its
mount path at all.**

This module owns the *write* side of that boundary — app_spec.xml feature 28,
*"System persists all ingest output append-only into a staging area that
never appears on the evaluator mount path."* Three properties, each
load-bearing:

* **Append-only.** A :class:`StagingArea` writes each worker cycle's output
  as the next batch in a per-stream ``1, 2, 3, ...`` log under
  ``staging/<stream>/<seq>.bin``. A batch is never rewritten: the shared
  batch-store mechanics (:class:`~nullius_ingest.watermark.SequenceStoreBase`)
  refuse a second batch at a sequence the store already holds, so an append
  either lands past the high-water mark or is refused — never an overwrite.

* **Staging is a sibling of snapshots, never inside it.** The area is rooted
  at ``<lake>/staging`` — beside ``snapshots/``, not under it. That layout is
  the whole of "never on the evaluator mount path": the evaluator mounts
  ``snapshots/*`` and staging is not among them. The layout is enforced, not
  hoped for — :class:`StagingRootError` refuses to construct a staging area at
  a path that *is*, or is *contained within*, a ``snapshots/`` directory, so
  a mis-wired ``LAKE_ROOT`` can never put ingest output where the evaluator
  reads.

* **Durable, atomic appends.** Each batch is written to a temporary file,
  ``fsync``ed, then ``rename(2)``d into place — the same commit the resumable
  worker uses (feature 29) — so a crash leaves a batch either fully appended
  or absent, never torn, and staging is always a clean append-only log a seal
  can copy byte-for-byte.

Staging is *written* here and *copied* by the sealing service (feature 30);
this module never moves, empties, or edits what it writes, exactly as §4.1
keeps staging append-only and owned by the ingest workers. It reuses the
durable batch-store mechanics rather than re-deriving them: the append-only
log and the resume watermark are the same artifact — one file per committed
batch — distinguished only by where it lives (``staging/``) and who reads it
(the seal, not the evaluator).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Union

from app.module_loader import find_workspace_root

from .streams import StreamClass, coerce_stream_class
from .watermark import Batch, SequenceStoreBase

__all__ = [
    "DEFAULT_LAKE",
    "LAKE_ROOT_ENV",
    "SNAPSHOTS_DIRNAME",
    "STAGING_DIRNAME",
    "StagedBatch",
    "StagingArea",
    "StagingRootError",
]

#: Environment variable naming the lake root; staging is resolved as
#: ``<lake_root>/staging``.  Shared with the snapshot sealing service
#: (docs/nullius-tech-architecture.md §4.2), so ingest and seal agree on
#: where the lake lives without either importing the other.
LAKE_ROOT_ENV = "LAKE_ROOT"

#: The lake root used when ``LAKE_ROOT`` is unset: ``lake/`` beside the
#: workspace root, the location §4.2 draws.
DEFAULT_LAKE = "lake"

#: The staging directory name — a sibling of :data:`SNAPSHOTS_DIRNAME`
#: under the lake root, never inside it.
STAGING_DIRNAME = "staging"

#: The directory the evaluator mounts.  Staging must never sit here or
#: beneath it; that single rule is feature 28's mount-path guarantee made
#: structural on the write side.
SNAPSHOTS_DIRNAME = "snapshots"

#: Temp files wear this prefix so a scan can ignore a batch a crash left
#: half-written — it never became a ``<seq>.bin`` and so was never committed.
TMP_PREFIX = ".tmp-"


class StagingRootError(Exception):
    """A staging area was rooted where the evaluator could see it.

    Raised when a :class:`StagingArea` is constructed at a path that is, or
    is contained within, a ``snapshots/`` directory. That would put ingest's
    append-only output on the very tree the evaluator mounts — the one layout
    feature 28 exists to forbid — so the area refuses to exist rather than
    write into it. The message names the offending root and the contract it
    broke, because this is an operational signal for whoever set
    ``LAKE_ROOT``, not a debugging aid.
    """


@dataclass(frozen=True)
class StagedBatch:
    """One appended worker cycle in staging: a sequence, its bytes, its path.

    ``sequence`` is the batch's position in its stream's append-only log —
    the value the next append advances past. ``payload`` is the opaque bytes
    the cycle wrote; ``rows`` is how many rows it held, for reporting.
    ``path`` is the durable ``staging/<stream>/<seq>.bin`` file the bytes
    were committed to — exposed so a seal or an operator can point at the
    exact artifact, but never written through: staging is append-only, so
    the only way to add a batch is another :meth:`StagingArea.append`.
    """

    sequence: int
    payload: bytes
    rows: int
    path: Path


class StagingArea(SequenceStoreBase):
    """The append-only ingest staging area, rooted at ``<lake>/staging``.

    A :class:`StagingArea` is a durable per-stream batch store (it is a
    :class:`~nullius_ingest.watermark.SequenceStoreBase`) whose root is the
    lake's staging directory. Each stream's output forms a gap-free
    ``<stream>/<seq>.bin`` log, appended one batch per worker cycle. It is
    the write half of the §4.1 seal boundary: what the ingest workers append
    here, the sealing service later copies into an immutable snapshot — and
    what the evaluator never reads, because staging is not on its mount path.

    Construction reads whatever a prior run left on disk, so a freshly
    constructed area over an existing staging tree resumes appending past the
    high-water mark a prior run reached — the same "seed from what is durably
    persisted" moment a restarted worker gets from the resume watermark. The
    root is validated eagerly, because a staging area on the wrong path is a
    wiring bug to fail now, not an append to misplace.
    """

    def __init__(self, root: Union[str, os.PathLike[str]]) -> None:
        self._root = Path(root).expanduser()
        self._validate_root(self._root)
        self._stream_dirs: Mapping[StreamClass, Path] = {
            stream: self._root / str(stream) for stream in StreamClass
        }
        super().__init__()
        self.load()

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "StagingArea":
        """Resolve the staging root the way the sealing service resolves its lake.

        ``LAKE_ROOT`` wins when set (an empty or whitespace-only value counts
        as unset, mirroring the shared fixtures' treatment of the same
        variable). Otherwise the lake defaults to ``lake/`` beside the
        workspace root — located via the factory's workspace discovery rather
        than a hard-coded guess — and staging is its ``staging/`` child. With
        neither available the area refuses to guess where the lake is: raising
        a clear error beats appending ingest output into an arbitrary path.
        """
        source = os.environ if env is None else env
        raw = source.get(LAKE_ROOT_ENV, "").strip()
        if raw:
            lake_root = Path(raw)
        else:
            workspace_root = find_workspace_root()
            if workspace_root is not None:
                lake_root = workspace_root / DEFAULT_LAKE
            else:
                raise StagingRootError(
                    f"{LAKE_ROOT_ENV} is not set and no uv workspace root was "
                    f"found above this package; set {LAKE_ROOT_ENV} to the "
                    f"lake root (§4.2)"
                )
        return cls(lake_root / STAGING_DIRNAME)

    @staticmethod
    def _validate_root(root: Path) -> None:
        # Staging must never be at, or beneath, a snapshots directory — that
        # is the mount-path guarantee enforced structurally. Checking the
        # resolved path's parts catches ``.../snapshots`` itself and any
        # ``.../snapshots/...`` descendant, whatever the spelling, without
        # touching the filesystem.
        parts = root.resolve(strict=False).parts
        if SNAPSHOTS_DIRNAME in parts:
            raise StagingRootError(
                f"staging root {root} sits on a {SNAPSHOTS_DIRNAME!r} "
                f"directory; staging is the ingest workers' writable area and "
                f"is never on the evaluator mount path — it must be a sibling "
                f"of {SNAPSHOTS_DIRNAME!r} under the lake root, as "
                f"<lake>/{STAGING_DIRNAME}"
            )

    # -- Paths --------------------------------------------------------------

    @property
    def root(self) -> Path:
        """The staging root; a sibling of the lake's ``snapshots/`` tree."""
        return self._root

    def _stream_dir(self, stream: StreamClass) -> Path:
        return self._stream_dirs[stream]

    def path_for(self, stream: StreamClass | str) -> Path:
        """The staging directory this area appends ``stream`` into."""
        return self._stream_dir(coerce_stream_class(stream))

    # -- Discovery ----------------------------------------------------------

    def load(self) -> None:
        """(Re)read committed batches from disk, recomputing each watermark.

        Called from ``__init__`` — so a freshly constructed area already
        knows where a prior run's appends reached — and exposed so an
        operator or a re-seal can force a fresh read of what is durably on
        disk rather than trust a stale in-memory watermark. Only whole
        ``<seq>.bin`` files count; a crash mid-append leaves a ``.tmp-*``
        file the store ignores, so the batch is absent and re-appended, never
        duplicated.
        """
        for stream, directory in self._stream_dirs.items():
            committed: dict[int, Batch] = {}
            if directory.is_dir():
                for entry in directory.iterdir():
                    batch = self._read_committed(entry)
                    if batch is not None:
                        committed[batch.sequence] = batch
            self._committed[stream] = committed

    def _read_committed(self, entry: Path) -> Batch | None:
        # Only fully-renamed ``<seq>.bin`` files count as committed. A crash
        # mid-append leaves a ``.tmp-*`` file (ignored), and stray files that
        # are not integer-named are ignored too — so the directory stays a
        # pure function of committed batches and the watermark stays honest.
        if entry.suffix != ".bin" or entry.name.startswith(TMP_PREFIX):
            return None
        try:
            sequence = int(entry.stem)
        except ValueError:
            return None
        return Batch(sequence=sequence, payload=entry.read_bytes())

    # -- Appending ----------------------------------------------------------

    def append(
        self, stream: StreamClass | str, payload: bytes, rows: int = 0
    ) -> StagedBatch:
        """Append one worker cycle's output to ``stream``'s log and return it.

        The batch is written under one past the stream's current high-water
        sequence, so appends form a gap-free ``1, 2, 3, ...`` log and the
        returned :class:`StagedBatch` names the exact ``<seq>.bin`` the bytes
        landed in. This is the append-only guarantee: the underlying store
        refuses a second batch at a sequence it already holds, so an append
        past a committed batch is refused rather than overwriting it —
        staging is written once and copied by the seal, never rewritten.
        """
        stream = coerce_stream_class(stream)
        sequence = self.current(stream) + 1
        batch = Batch(sequence=sequence, payload=bytes(payload), rows=rows)
        self.commit(stream, batch)
        return StagedBatch(
            sequence=sequence,
            payload=batch.payload,
            rows=rows,
            path=self._stream_dir(stream) / f"{sequence}.bin",
        )

    def staged(self, stream: StreamClass | str) -> tuple[Batch, ...]:
        """The committed batches for ``stream``, in ascending sequence order."""
        return self.batches(stream)

    # -- Persistence --------------------------------------------------------

    def _persist(self, stream: StreamClass, batch: Batch) -> None:
        # Write the payload to a temp file in the stream's staging directory,
        # fsync it, then atomically rename it to ``<seq>.bin`` — the single
        # commit point, and the same durable write the resume watermark uses.
        # A crash before the rename leaves only a ``.tmp-*`` file the store
        # ignores, so the batch is absent and re-appended, never duplicated.
        directory = self._stream_dir(stream)
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / f"{batch.sequence}.bin"
        fd, tmp_name = tempfile.mkstemp(
            dir=directory, prefix=TMP_PREFIX, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(batch.payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, final)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        # fsync the directory so the rename is durable, not just the file's
        # bytes: without it a crash can drop the new directory entry even
        # though the payload was fsynced, losing a committed batch.
        self._fsync_dir(directory)

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        try:
            dir_fd = os.open(str(directory), os.O_DIRECTORY)
        except (OSError, AttributeError):  # pragma: no cover - platform guard
            return
        try:
            os.fsync(dir_fd)
        except OSError:  # pragma: no cover - best effort on odd filesystems
            pass
        finally:
            os.close(dir_fd)
