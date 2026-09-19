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
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .streams import StreamClass, coerce_stream_class

__all__ = [
    "CycleResult",
    "FunctionWorker",
    "IngestWorker",
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
    stream.  Later features extend this record (sequence watermarks for
    crash-safe resume, gap counters) rather than widening the worker
    signature.
    """

    rows_written: int = 0


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
