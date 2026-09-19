"""The ingest supervisor: one worker per stream class, failures isolated.

The supervisor is the concrete implementation of app_spec.xml feature 16:
*"System isolates each stream class in its own ingest worker, which
returns a per-stream failure rather than halting all ingest"* — and of
the §4.1 rule it restates, *"separate worker per stream class."*

Isolation here is mechanical, not aspirational:

* **One worker per class, enforced.**  Two workers for the same stream
  class is a wiring bug; :meth:`IngestSupervisor.add_worker` rejects it
  at construction time.
* **One thread per worker, per cycle.**  Every cycle of every worker runs
  on a thread dedicated to that stream class, so a slow or hung worker
  delays only its own stream — the other workers' cycles proceed and
  complete regardless.
* **Failures converted at the boundary.**  Whatever a worker raises (or
  returns instead of a :class:`~nullius_ingest.worker.CycleResult`)
  becomes a :class:`~nullius_ingest.worker.StreamFailure` naming that
  stream and only that stream.  :meth:`IngestSupervisor.run_cycle`
  *returns* an :class:`IngestReport`; it never re-raises a worker's
  failure, so one stream can never halt the others.
* **A cycle budget, optional.**  ``run_cycle(timeout=...)`` bounds how
  long the supervisor will wait for laggard workers.  A worker that
  exceeds the budget gets a per-stream timeout failure and the report
  comes back anyway; without a budget the supervisor waits for its
  workers (a klines REST backfill may legitimately run for minutes, and
  no default would be honest).

The worker threads are daemons: a worker wedged past its budget never
prevents the process from exiting.  Python cannot kill a running thread,
so a timed-out worker's late result is discarded, not delivered —
recording a belated success after the stream was reported failed would
be a lie.  Restarting a failed worker is deliberately out of scope here;
crash-safe restart is feature 29's contract, built on this one.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import Future
from dataclasses import dataclass

from .streams import StreamClass, coerce_stream_class
from .worker import (
    CycleResult,
    IngestWorker,
    StreamFailure,
    StreamOutcome,
)

__all__ = ["IngestReport", "IngestSupervisor", "WORKER_TIMEOUT_ERROR_TYPE"]

#: The ``error_type`` recorded for a worker that exceeded the cycle
#: budget — deliberately not ``"TimeoutError"``, which is reserved for
#: workers whose own code raised a timeout.
WORKER_TIMEOUT_ERROR_TYPE = "WorkerTimeout"


@dataclass(frozen=True)
class IngestReport:
    """What one supervisor cycle produced, per stream class.

    Outcomes are always sorted by stream class, so two runs over the
    same workers report in the same order regardless of which worker
    finished first.  ``ok`` answers "did every stream's cycle succeed?";
    :attr:`failures` carries the per-stream failure records for logging
    and alerting.  An empty report (no workers registered) is
    well-formed and ``ok`` — an idle ingest layer is not an error state,
    exactly as an empty workspace is not one for the module loader.
    """

    outcomes: tuple[StreamOutcome, ...] = ()

    def outcome_for(self, stream: StreamClass | str) -> StreamOutcome | None:
        """The outcome recorded for ``stream``, or ``None`` if it has no worker."""
        wanted = coerce_stream_class(stream)
        for outcome in self.outcomes:
            if outcome.stream == wanted:
                return outcome
        return None

    @property
    def failures(self) -> tuple[StreamOutcome, ...]:
        """The outcomes whose stream failed, in report order."""
        return tuple(o for o in self.outcomes if not o.ok)

    @property
    def ok(self) -> bool:
        """``True`` when every stream's cycle succeeded (or none ran)."""
        return not self.failures

    @property
    def rows_written(self) -> int:
        """Total rows appended this cycle across succeeded streams."""
        return sum(o.rows_written for o in self.outcomes if o.ok)

    def __iter__(self) -> Iterator[StreamOutcome]:
        return iter(self.outcomes)

    def __len__(self) -> int:
        return len(self.outcomes)


class IngestSupervisor:
    """Owns one ingest worker per stream class and runs them in isolation."""

    def __init__(self, workers: Iterable[IngestWorker] = ()) -> None:
        self._workers: dict[StreamClass, IngestWorker] = {}
        for worker in workers:
            self.add_worker(worker)

    # -- wiring -----------------------------------------------------------

    def add_worker(self, worker: IngestWorker) -> IngestWorker:
        """Attach ``worker`` as the sole worker for its stream class.

        Returns the worker so constructors can pass it through.  Raises
        :class:`ValueError` if the stream class already has a worker —
        one class, one worker is the invariant the isolation guarantee
        stands on, and a violation is a wiring bug to fix now, not an
        ingest-time surprise.
        """
        try:
            stream = coerce_stream_class(worker.stream_class)
        except (TypeError, AttributeError) as exc:
            raise TypeError(
                f"worker {worker!r} does not expose a valid stream_class "
                f"(got {getattr(worker, 'stream_class', None)!r})"
            ) from exc
        if stream in self._workers:
            raise ValueError(
                f"stream class {stream} already has a worker; the ingest "
                f"contract is one worker per stream class"
            )
        if not callable(getattr(worker, "run_cycle", None)):
            raise TypeError(
                f"worker for {stream} has no callable run_cycle"
            )
        self._workers[stream] = worker
        return worker

    @property
    def stream_classes(self) -> tuple[StreamClass, ...]:
        """The supervised stream classes, in deterministic report order."""
        return tuple(sorted(self._workers, key=str))

    def worker_for(self, stream: StreamClass | str) -> IngestWorker | None:
        """The worker owning ``stream``, or ``None`` if the class is unsupervised."""
        return self._workers.get(coerce_stream_class(stream))

    def __contains__(self, stream: object) -> bool:
        try:
            return coerce_stream_class(stream) in self._workers
        except TypeError:
            return False

    def __len__(self) -> int:
        return len(self._workers)

    def __iter__(self) -> Iterator[IngestWorker]:
        """The workers, in deterministic report order."""
        return iter(self._workers[stream] for stream in self.stream_classes)

    # -- running ----------------------------------------------------------

    def run_cycle(self, timeout: float | None = None) -> IngestReport:
        """Run exactly one cycle of every worker and report per stream.

        Each worker runs on its own thread for the cycle; failures and
        deadline overruns become per-stream records in the returned
        report and never propagate as exceptions (the single exception:
        a ``KeyboardInterrupt`` raised in *this* thread while waiting —
        an operator signal is not a stream failure).

        ``timeout``, when given, is a budget in seconds for the whole
        cycle: workers that finish within it report normally, workers
        that do not get a ``WorkerTimeout`` failure for their stream and
        their late results are discarded.  Without a budget the call
        waits for every worker; pass a budget wherever a hung feed must
        not hold up the report.
        """
        if timeout is not None:
            timeout = max(float(timeout), 0.0)
        streams = self.stream_classes
        if not streams:
            return IngestReport(outcomes=())

        futures: dict[Future[CycleResult], StreamClass] = {}
        for stream in streams:
            future: Future[CycleResult] = Future()
            futures[future] = stream
            # One dedicated thread per stream worker: the "separate
            # worker per stream class" of §4.1.  Daemon, so a worker
            # wedged past the budget cannot keep the process alive.
            threading.Thread(
                target=_run_worker_cycle,
                args=(self._workers[stream], future),
                name=f"ingest-worker-{stream}",
                daemon=True,
            ).start()

        deadline = None if timeout is None else time.monotonic() + timeout
        outcomes: list[StreamOutcome] = []
        for future, stream in futures.items():
            remaining = (
                None if deadline is None else max(deadline - time.monotonic(), 0.0)
            )
            try:
                result = future.result(timeout=remaining)
            except TimeoutError:
                worker_exc = future.exception() if future.done() else None
                if worker_exc is not None:
                    # The worker itself raised a timeout — that is an
                    # ordinary per-stream failure, not a budget overrun.
                    outcomes.append(_failed(stream, worker_exc))
                else:
                    outcomes.append(_timed_out(stream, timeout))
            except Exception as exc:
                outcomes.append(_failed(stream, exc))
            except BaseException as exc:
                # Either the worker itself raised a BaseException, or the
                # wait was interrupted by an operator signal.  These are
                # told apart by identity: result() re-raises the very
                # object the worker's future stored, while a signal
                # arrives as a fresh exception the future never held (a
                # signal can even surface only when a *successful* future
                # posts the lock the caller waits on — in which case the
                # future carries a result, not an exception).  Only the
                # worker's own failure becomes stream data; an operator
                # signal always propagates.
                worker_exc = future.exception() if future.done() else None
                if worker_exc is exc:
                    outcomes.append(_failed(stream, exc))
                else:
                    raise
            else:
                outcomes.append(
                    StreamOutcome(stream=stream, rows_written=result.rows_written)
                )
        return IngestReport(outcomes=tuple(outcomes))


def _run_worker_cycle(worker: IngestWorker, future: Future[CycleResult]) -> None:
    """Run one worker cycle on its own thread, channelling the outcome.

    This is the isolation boundary.  Anything the worker raises — up to
    and including ``SystemExit`` — is captured into ``future`` instead of
    taking the thread down noisily or the supervisor down at all.  A
    return value that violates the contract (not a ``CycleResult``) is
    converted to a :class:`TypeError` here, so a misbehaving worker
    becomes a per-stream failure rather than an :class:`AttributeError`
    in the reporting loop.
    """
    try:
        produced = worker.run_cycle()
        if not isinstance(produced, CycleResult):
            raise TypeError(
                f"run_cycle for {worker.stream_class} returned "
                f"{type(produced).__name__}; the contract is CycleResult "
                f"(int rows and None are accepted by FunctionWorker)"
            )
        future.set_result(produced)
    except BaseException as exc:  # noqa: BLE001 - the boundary captures everything
        future.set_exception(exc)


def _failed(stream: StreamClass, exc: BaseException) -> StreamOutcome:
    """A per-stream failure outcome for ``stream`` from exception ``exc``."""
    return StreamOutcome(
        stream=stream, failure=StreamFailure.from_exception(stream, exc)
    )


def _timed_out(stream: StreamClass, budget: float | None) -> StreamOutcome:
    """A per-stream timeout outcome; the report returns without this worker."""
    return StreamOutcome(
        stream=stream,
        failure=StreamFailure(
            stream=stream,
            error_type=WORKER_TIMEOUT_ERROR_TYPE,
            message=(
                f"run_cycle for {stream} did not finish within the cycle "
                f"budget of {budget}s; its late result was discarded"
            ),
        ),
    )
