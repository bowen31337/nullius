"""The per-stream ingest worker contract and its result types.

app_spec.xml feature 16 (*"Market Data Ingest Workers"*) states the
isolation rule this module vocabularises: *each stream class lives in its
own ingest worker, which returns a per-stream failure rather than halting
all ingest*.  Two halves, both load-bearing:

* **Its own worker.**  An :class:`IngestWorker` owns exactly one
  :class:`~nullius_ingest.streams.StreamClass`.  The supervisor enforces
  one-worker-per-class and runs every worker independently, so "worker"
  is a real boundary, not a loop body.
* **A per-stream failure.**  A worker is free to fail however it likes —
  any exception out of :meth:`IngestWorker.run_cycle` is *caught at the
  boundary* and converted into a :class:`StreamFailure`: an immutable
  record naming the stream, the error type, the message and the
  traceback.  Failures travel back as data inside a
  :class:`~nullius_ingest.supervisor.IngestReport`; they are never
  re-raised across the supervisor, so no stream's failure can become
  another stream's halt.

Workers therefore need no error handling of their own to keep the system
up: raise, and the boundary does the rest.  What a worker *must not* do
is mutate shared state belonging to another stream class — the class
boundary only isolates failures, not badly written workers.

Feature 29 — *"System restarts an ingest worker safely after a crash,
resuming from the last persisted sequence with no duplicate rows"* —
adds a second worker shape on top of this one: a :class:`ResumableWorker`
is an :class:`IngestWorker` that also owns a durable
:class:`~nullius_ingest.watermark.SequenceStore` and commits each batch to
it before returning.  The store's atomic commit is what makes the worker
resumable, and it is layered on the same boundary — a resumable worker
still raises on failure and is still caught per stream — so crash-safety
and failure-isolation compose rather than compete.  The two worker shapes
share one stream-class boundary and one ``run_cycle`` signature, so the
supervisor runs either without change.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .streams import StreamClass, coerce_stream_class
from .watermark import Batch, SequenceStore, SequenceStoreBase

__all__ = [
    "CycleResult",
    "FunctionWorker",
    "IngestWorker",
    "ResumableFunctionWorker",
    "ResumableWorker",
    "StreamFailure",
    "StreamOutcome",
]


@dataclass(frozen=True)
class CycleResult:
    """What one successful worker cycle produced.

    A cycle is one unit of ingest work for the worker's stream — one
    websocket flush, one REST poll, one batch write.  ``rows_written``
    is the honest count of rows that cycle appended; the supervisor
    sums it into the report so ingest progress stays observable per
    stream.

    ``sequence`` is the batch's position in the stream's append-only log
    — the value a crash-safe worker persists before returning, and the
    point a restarted worker resumes from (feature 29).  It is ``0`` for
    a cycle that wrote no batch: the honest "no progress" watermark, and
    the value a stream with no committed batch starts from.
    """

    rows_written: int = 0
    sequence: int = 0


@dataclass(frozen=True)
class StreamFailure:
    """A single stream's failure, as data.

    Built by the supervisor (never by workers themselves) from whatever
    exception a worker's cycle raised.  The record is frozen and
    JSON-friendly on purpose: it is logged, counted and reported — not
    raised — so one stream's failure is always a row in the report
    rather than a stoppage of the report.
    """

    stream: StreamClass
    """The stream class whose worker failed — never any other stream."""

    error_type: str
    """The exception's class name (e.g. ``"ValueError"``)."""

    message: str
    """The exception's ``str()``."""

    traceback: str = ""
    """The full formatted traceback, for operators, not for control flow."""

    @classmethod
    def from_exception(
        cls, stream: StreamClass | str, exc: BaseException
    ) -> StreamFailure:
        """Capture ``exc`` as this stream's failure record."""
        formatted = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        return cls(
            stream=coerce_stream_class(stream),
            error_type=type(exc).__name__,
            message=str(exc),
            traceback=formatted,
        )


@dataclass(frozen=True)
class StreamOutcome:
    """One stream's result for one supervisor cycle: success or failure.

    The two states are distinguishable only through :attr:`ok` and
    :attr:`failure`; a failed cycle reports zero rows (whatever it wrote
    before dying is unknowable and unclaimed, which is the honest
    answer for an append-only staging area).
    """

    stream: StreamClass
    """The stream class this outcome belongs to."""

    rows_written: int = 0
    """Rows appended this cycle; ``0`` when the cycle failed."""

    failure: StreamFailure | None = None
    """The per-stream failure, or ``None`` when the cycle succeeded."""

    @property
    def ok(self) -> bool:
        """``True`` when the cycle succeeded."""
        return self.failure is None


@runtime_checkable
class IngestWorker(Protocol):
    """The contract every ingest worker satisfies.

    Structural on purpose: a worker is anything with a ``stream_class``
    and a ``run_cycle`` — the supervisor accepts hand-rolled workers,
    test doubles, and the concrete adapters later features will add,
    without asking any of them to subclass anything.

    ``run_cycle`` performs one unit of ingest work for *its* stream and
    returns what it produced.  It may raise anything; raising is the
    worker's failure mode, and the supervisor's job is to convert it.
    """

    @property
    def stream_class(self) -> StreamClass:
        """The one stream class this worker owns."""
        ...

    def run_cycle(self) -> CycleResult:
        """Run one ingest cycle for this worker's stream."""
        ...


@dataclass(frozen=True)
class FunctionWorker:
    """Wrap a zero-argument callable as an :class:`IngestWorker`.

    The simplest way to own a stream class: hand in a callable and the
    stream it serves.  The callable returns the rows it wrote (an
    ``int``), a :class:`CycleResult`, or nothing at all — ``None``
    counts as a zero-row cycle.  Exceptions propagate untouched; the
    supervisor's boundary, not the adapter, owns failure conversion.
    """

    stream_class: StreamClass
    fn: Callable[[], "CycleResult | int | None"]

    def __post_init__(self) -> None:
        # Validate at construction: a mis-wired worker must fail here,
        # not three layers deep inside a supervisor cycle.
        object.__setattr__(
            self, "stream_class", coerce_stream_class(self.stream_class)
        )
        if not callable(self.fn):
            raise TypeError(
                f"worker for {self.stream_class} needs a callable cycle, "
                f"got {type(self.fn).__name__}"
            )

    def run_cycle(self) -> CycleResult:
        """Run the wrapped callable and normalise what it returned."""
        produced = self.fn()
        if isinstance(produced, CycleResult):
            return produced
        if produced is None:
            return CycleResult()
        return CycleResult(rows_written=int(produced))


@runtime_checkable
class ResumableWorker(Protocol):
    """The crash-safe worker contract: one batch per cycle, committed durably.

    A :class:`ResumableWorker` is an :class:`IngestWorker` that owns a
    :class:`~nullius_ingest.watermark.SequenceStore` and, each cycle,
    fetches the next batch of rows *after* its last committed sequence and
    commits it to the store before returning.  The store's atomic commit is
    what makes the worker resumable (feature 29): the batch's presence in
    the store *is* its commit, so a crash either leaves the batch fully
    committed — and the worker resumes past it, never rewriting it — or
    leaves it absent — and the worker resumes from that sequence and
    re-fetches it, writing it once with no duplicate rows.

    ``sequence`` on the returned :class:`CycleResult` is the batch's
    sequence: the point the next cycle — or a restarted worker — resumes
    from.  A zero-row cycle reports ``sequence=0``: no batch, no progress.
    """

    @property
    def stream_class(self) -> StreamClass:
        """The one stream class this worker owns."""
        ...

    @property
    def sequence_store(self) -> SequenceStore:
        """The durable store this worker commits batches into."""
        ...

    def run_cycle(self) -> CycleResult:
        """Fetch the next batch after the last committed sequence and commit it."""
        ...


@dataclass(frozen=True)
class ResumableFunctionWorker:
    """A resumable worker built from a factory, one stream class, one store.

    The crash-safe analogue of :class:`FunctionWorker`: hand in the stream
    it serves, a :class:`~nullius_ingest.watermark.SequenceStore` to commit
    into, and a factory that, given the sequence to resume from, returns
    the next :class:`~nullius_ingest.watermark.Batch` (or ``None`` for an
    empty cycle).  Each cycle the worker asks the store for its current
    watermark, calls the factory with the next sequence, and commits the
    returned batch — so the store's durable watermark is the single source
    of truth for where the stream has reached, and a restart resumes from
    exactly there.

    The factory takes the resume sequence rather than holding one, so the
    same worker, reconstructed after a crash over the same store, resumes
    from the sequence the store reports — not from a value frozen at
    construction.  This is why the factory, not a prebuilt batch, is the
    unit of composition: a fresh worker over a durable store is a restart.
    """

    stream_class: StreamClass
    store: SequenceStore
    build_batch: "Callable[[int], Batch | None]"

    def __post_init__(self) -> None:
        # Validate at construction, exactly as FunctionWorker does: a
        # mis-wired worker must fail here, not inside a cycle.
        object.__setattr__(
            self, "stream_class", coerce_stream_class(self.stream_class)
        )
        if not isinstance(self.store, SequenceStoreBase):
            raise TypeError(
                f"resumable worker for {self.stream_class} needs a "
                f"SequenceStore, got {type(self.store).__name__}"
            )
        if not callable(self.build_batch):
            raise TypeError(
                f"resumable worker for {self.stream_class} needs a callable "
                f"batch factory, got {type(self.build_batch).__name__}"
            )

    @property
    def sequence_store(self) -> SequenceStore:
        """The durable store this worker commits batches into."""
        return self.store

    def run_cycle(self) -> CycleResult:
        """Resume from the store's watermark, fetch the next batch, commit it.

        The sequence the batch is committed under is one past the store's
        current watermark, so batches form a gap-free ``1, 2, 3, ...`` log
        and a restart — which reads the watermark from the store — resumes
        at exactly the next uncommitted sequence.  This is what makes the
        resume safe: because the store commits a batch atomically (its
        file is either fully present or fully absent), a crash leaves the
        watermark either advanced past the batch — so the worker resumes
        after it and never rewrites it — or unadvanced — so the worker
        resumes at that sequence and re-fetches it, writing it once.  The
        store's ``commit`` refusing a duplicate sequence is the belt-and-
        braces guard for the same-sequence case within one process; across
        a restart the atomic commit alone guarantees no batch is written
        twice.
        """
        stream = self.stream_class
        sequence = self.store.current(stream) + 1
        produced = self.build_batch(sequence)
        if produced is None:
            return CycleResult(sequence=0)
        if not isinstance(produced, Batch):
            raise TypeError(
                f"build_batch for {stream} returned {type(produced).__name__}; "
                f"the contract is a Batch or None"
            )
        self.store.commit(stream, produced)
        return CycleResult(
            rows_written=produced.rows,
            sequence=produced.sequence,
        )
