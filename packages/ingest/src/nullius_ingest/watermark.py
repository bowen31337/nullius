"""Durable per-stream sequence watermarks for crash-safe resume.

app_spec.xml feature 29 states: *"System restarts an ingest worker safely
after a crash, resuming from the last persisted sequence with no duplicate
rows."*  This module is the durability half of that contract.

The unit of persistence is a :class:`Batch`: one worker cycle's output for
one stream, carrying the ``sequence`` it was written under and the opaque
``payload`` of rows it committed.  A :class:`SequenceStore` persists batches
into a directory named for the stream, one file per batch, and reports the
high-water ``sequence`` it has durably committed — *the last persisted
sequence* a restarted worker resumes from.

Two properties make resume safe:

* **Atomic commit.**  A batch is written to a temporary file, ``fsync``ed,
  then ``rename(2)``d into place as ``<seq>.bin``.  ``rename`` is atomic on
  POSIX, so a reader — including a freshly restarted worker — sees either
  the whole batch or none of it, never a torn file.  The batch's presence
  in the directory *is* its commit; there is no separate watermark to fall
  out of step with the data.

* **Crash leaves the batch absent, not half-written.**  A crash before the
  rename leaves only a ``.tmp-*`` file, which the store ignores when it
  scans for committed batches.  The batch is therefore absent, its
  ``sequence`` not yet the high-water mark, so a restarted worker resumes
  *from* that sequence and re-fetches that batch — writing it once, under
  its sequence, with no duplicate.  A crash after the rename leaves the
  batch committed; the worker resumes *past* it and never rewrites it.

The store is deliberately agnostic to payload shape and to how batches are
produced: it persists bytes and reports a sequence, and the resumable
worker in :mod:`nullius_ingest.worker` decides what a batch means.  It is
also the single place the durability contract lives, so feature 29's "no
duplicate rows" is one module's behaviour, not a hope spread across many.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .streams import StreamClass, coerce_stream_class

__all__ = ["Batch", "InMemorySequenceStore", "SequenceStore", "SequenceStoreBase"]


@dataclass(frozen=True)
class Batch:
    """One committed worker cycle: a sequence, its rows, and its payload.

    ``sequence`` is the batch's position in the stream's append-only log —
    the value the store watermarks and a restarted worker resumes past.
    ``rows`` is how many rows this batch holds, for reporting; it is not
    part of the durable artifact (only ``sequence`` and ``payload`` are
    written to disk), so it carries no durability weight.  ``payload`` is
    the opaque bytes the worker committed under this sequence; the store
    persists and returns it verbatim and never interprets it.
    """

    sequence: int
    payload: bytes
    rows: int = 0


class SequenceStoreBase:
    """Shared watermark logic; subclasses supply the persistence layer.

    The working state both stores reason from is ``_committed`` —
    ``stream -> {sequence -> Batch}`` — holding whole :class:`Batch`
    objects so nothing about a committed batch (its payload, its row
    count) is reconstructed on read.  ``current`` reports the highest
    committed sequence and ``commit`` enforces the two rules that keep
    resume safe — positive, non-duplicate sequences — before delegating
    the actual persistence to :meth:`_persist`.  Splitting the rules from
    the transport lets the on-disk and in-memory stores share one contract
    rather than each re-derive it.
    """

    def __init__(self) -> None:
        self._committed: dict[StreamClass, dict[int, Batch]] = {
            stream: {} for stream in StreamClass
        }

    def current(self, stream: StreamClass | str) -> int:
        """The highest committed sequence for ``stream``; ``0`` if none.

        ``0`` is the honest watermark for a stream with no committed
        batches: a fresh stream starts at 0 and a restarted worker resumes
        from 0, re-fetching from the very first batch.
        """
        return max(self._committed[coerce_stream_class(stream)], default=0)

    def batches(self, stream: StreamClass | str) -> tuple[Batch, ...]:
        """The committed batches for ``stream``, in ascending sequence order."""
        committed = self._committed[coerce_stream_class(stream)]
        return tuple(committed[seq] for seq in sorted(committed))

    def commit(self, stream: StreamClass | str, batch: Batch) -> None:
        """Record ``batch`` for ``stream`` under its sequence.

        Enforces the two invariants that make the watermark trustworthy —
        the sequence is positive, and no committed batch already holds it —
        then hands the durable write to :meth:`_persist`.  Refusing a
        second batch at one sequence is the store's half of "no duplicate
        rows": a duplicate commit is an error, not a silent overwrite.
        """
        stream = coerce_stream_class(stream)
        if batch.sequence <= 0:
            raise ValueError(
                f"batch sequence must be positive, got {batch.sequence}"
            )
        if batch.sequence in self._committed[stream]:
            raise ValueError(
                f"stream {stream} already has a batch at sequence "
                f"{batch.sequence}; refusing a duplicate commit"
            )
        self._persist(stream, batch)
        self._committed[stream][batch.sequence] = batch

    def _persist(self, stream: StreamClass, batch: Batch) -> None:
        """Make ``batch`` durable for ``stream``; the subclass's contract."""
        raise NotImplementedError


class InMemorySequenceStore(SequenceStoreBase):
    """An in-memory :class:`SequenceStore` stand-in for tests.

    Same interface — ``current``, ``batches``, ``commit`` — but nothing is
    written to disk: it models the durability contract's *logic* (positive
    sequences, no duplicate commit, watermark equals the highest committed
    sequence) without the I/O, so worker tests exercise resume behaviour
    without a filesystem.  It is not crash-safe by construction — that is
    exactly what :class:`SequenceStore` exists to prove — so it is the
    wrong choice anywhere a restart must recover real progress.
    """

    def _persist(self, stream: StreamClass, batch: Batch) -> None:
        # Nothing to make durable: the in-memory map updated by the base
        # commit is the whole store.
        return None


class SequenceStore(SequenceStoreBase):
    """A durable per-stream batch store reporting the last persisted sequence.

    Batches live under ``root/<stream>/<seq>.bin``, one file per committed
    batch.  The store is written once and then read: :meth:`current`
    answers "where did we get to?" and a restarted worker seeds its resume
    point from it.  Constructing the store reads whatever a prior run left
    on disk, so the very first thing a restarted worker knows is the last
    sequence it durably committed.
    """

    #: Temp files wear this prefix so a scan can ignore a batch a crash left
    #: half-written — it never became a ``<seq>.bin`` and so was never
    #: committed.
    TMP_PREFIX = ".tmp-"

    def __init__(self, root: os.PathLike[str] | str) -> None:
        self._root = Path(root)
        self._stream_dir = {
            stream: self._root / str(stream) for stream in StreamClass
        }
        super().__init__()
        self.load()

    def load(self) -> None:
        """(Re)read committed batches from disk, recomputing each watermark.

        Called from ``__init__`` — so a freshly constructed store already
        reflects what a prior run persisted — and exposed so a restart can
        force a fresh read of what is durably on disk rather than trust a
        stale in-memory cache.  This is the moment "the last persisted
        sequence" becomes known to a restarted worker.
        """
        for stream, directory in self._stream_dir.items():
            committed: dict[int, Batch] = {}
            if directory.is_dir():
                for entry in directory.iterdir():
                    batch = self._read_committed(entry)
                    if batch is not None:
                        committed[batch.sequence] = batch
            self._committed[stream] = committed

    def _read_committed(self, entry: Path) -> Batch | None:
        # Only fully-renamed ``<seq>.bin`` files count as committed.  A
        # crash mid-commit leaves a ``.tmp-*`` file (wrong suffix), which
        # is ignored — the batch is absent and will be re-fetched, never
        # duplicated.  Stray files that are not integer-named are ignored
        # too, so the directory stays a pure function of committed batches.
        if entry.suffix != ".bin" or entry.name.startswith(self.TMP_PREFIX):
            return None
        try:
            sequence = int(entry.stem)
        except ValueError:
            return None
        return Batch(sequence=sequence, payload=entry.read_bytes())

    def _persist(self, stream: StreamClass, batch: Batch) -> None:
        # Write the payload to a temp file in the stream's directory, fsync
        # it, then atomically rename it to ``<seq>.bin``.  The rename is
        # the single commit point: until it succeeds the batch is invisible
        # to current(), so a crash before it leaves the sequence
        # unadvanced and the batch re-fetched.
        directory = self._stream_dir[stream]
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / f"{batch.sequence}.bin"
        fd, tmp_name = tempfile.mkstemp(
            dir=directory, prefix=self.TMP_PREFIX, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(batch.payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, final)
        except BaseException:
            # Best-effort cleanup of the temp file.  The rename either
            # happened (batch committed) or not (batch absent) — either way
            # the next load() reconstructs a consistent watermark, so a
            # leftover temp file is harmless.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        # fsync the directory itself so the rename is durable, not just the
        # file's bytes: without it a crash can drop the new directory entry
        # even though the payload was fsynced, losing a committed batch.
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
