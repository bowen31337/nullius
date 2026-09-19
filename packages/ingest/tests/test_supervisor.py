"""The supervisor: per-stream isolation of both success and failure.

These tests are the feature statement for app_spec.xml feature 16 —
*"System isolates each stream class in its own ingest worker, which
returns a per-stream failure rather than halting all ingest"* — read as
behaviour: every stream class gets its own worker, a failing worker
produces a failure record naming its stream and only its stream, the
supervisor returns rather than raises, and every other stream keeps
ingesting.
"""

from __future__ import annotations

import threading
import time

import pytest

from nullius_ingest import (
    FunctionWorker,
    IngestReport,
    IngestSupervisor,
    StreamClass,
)
from nullius_ingest.supervisor import WORKER_TIMEOUT_ERROR_TYPE


def all_six_streams(sleep_klines: float | None = None) -> list[FunctionWorker]:
    """One healthy worker per §4.1 stream class; klines optional sleeps."""
    def klines() -> int:
        if sleep_klines is not None:
            time.sleep(sleep_klines)
        return 10

    return [
        FunctionWorker(StreamClass.KLINES, klines),
        FunctionWorker(StreamClass.AGG_TRADES, lambda: 20),
        FunctionWorker(StreamClass.BOOK_DIFFS, lambda: 30),
        FunctionWorker(StreamClass.BOOK_FEATURES, lambda: 40),
        FunctionWorker(StreamClass.FUNDING, lambda: 50),
        FunctionWorker(StreamClass.EXCHANGE_INFO, lambda: 60),
    ]


def test_every_stream_class_runs_in_its_own_worker() -> None:
    # The happy path: one worker per class, each cycle runs, each result
    # is reported under its own stream.
    supervisor = IngestSupervisor(all_six_streams())
    assert len(supervisor) == 6

    report = supervisor.run_cycle()

    assert report.ok
    assert len(report) == 6
    assert report.rows_written == 210
    for worker in supervisor:  # every registered worker has an outcome
        outcome = report.outcome_for(worker.stream_class)
        assert outcome is not None and outcome.ok


def test_a_failing_stream_returns_a_per_stream_failure() -> None:
    # The core guarantee. The klines worker dies; run_cycle returns
    # (never raises) a report whose klines outcome carries the failure,
    # naming klines and klines alone.
    def broken_klines() -> int:
        raise ValueError("REST endpoint returned 429")

    supervisor = IngestSupervisor(
        [
            FunctionWorker(StreamClass.KLINES, broken_klines),
            FunctionWorker(StreamClass.AGG_TRADES, lambda: 20),
            FunctionWorker(StreamClass.BOOK_DIFFS, lambda: 30),
            FunctionWorker(StreamClass.FUNDING, lambda: 50),
        ]
    )

    report = supervisor.run_cycle()  # must not raise

    assert not report.ok
    assert len(report.failures) == 1
    failed = report.failures[0]
    assert failed.stream is StreamClass.KLINES
    assert failed.failure is not None
    assert failed.failure.stream is StreamClass.KLINES
    assert failed.failure.error_type == "ValueError"
    assert "429" in failed.failure.message
    assert "broken_klines" in failed.failure.traceback


def test_a_failing_stream_does_not_halt_the_others() -> None:
    # The other half of the guarantee: with one stream down, every other
    # stream still completed its cycle, wrote its rows, and reports ok.
    def broken_funding() -> int:
        raise ConnectionError("funding feed unreachable")

    supervisor = IngestSupervisor(
        [
            FunctionWorker(StreamClass.KLINES, lambda: 10),
            FunctionWorker(StreamClass.AGG_TRADES, lambda: 20),
            FunctionWorker(StreamClass.FUNDING, broken_funding),
            FunctionWorker(StreamClass.EXCHANGE_INFO, lambda: 60),
        ]
    )

    report = supervisor.run_cycle()

    assert report.outcome_for(StreamClass.FUNDING) is not None
    assert not report.outcome_for(StreamClass.FUNDING).ok
    for stream in (StreamClass.KLINES, StreamClass.AGG_TRADES, StreamClass.EXCHANGE_INFO):
        outcome = report.outcome_for(stream)
        assert outcome is not None and outcome.ok
        assert outcome.rows_written > 0
    # The failed stream claims no rows — honest for an append-only area.
    assert report.rows_written == 90


def test_ingest_continues_after_a_failure() -> None:
    # A dead stream stays dead, but the supervisor keeps running cycles
    # for everyone: "per-stream failure", not "halted ingest".
    attempts = {"funding": 0}

    def flaky_funding() -> int:
        attempts["funding"] += 1
        raise RuntimeError("still down")

    supervisor = IngestSupervisor(
        [
            FunctionWorker(StreamClass.FUNDING, flaky_funding),
            FunctionWorker(StreamClass.KLINES, lambda: 1),
        ]
    )

    first = supervisor.run_cycle()
    second = supervisor.run_cycle()

    assert attempts["funding"] == 2  # the failing worker keeps being run
    for report in (first, second):
        assert len(report.failures) == 1
        assert report.failures[0].stream is StreamClass.FUNDING
        assert report.outcome_for(StreamClass.KLINES).ok


def test_each_stream_runs_on_its_own_thread_concurrently() -> None:
    # "Own worker" is real isolation, not a loop body: four workers meet
    # at a barrier inside their cycles. Sequential execution could never
    # pass it — the first waiter would time out alone — so every worker
    # must be running at the same time, each on its own thread.
    workers_count = 4
    barrier = threading.Barrier(workers_count)
    seen_threads: list[str] = []
    lock = threading.Lock()

    def meet_at_barrier() -> int:
        with lock:
            seen_threads.append(threading.current_thread().name)
        barrier.wait(timeout=5.0)
        return 1

    supervisor = IngestSupervisor(
        [
            FunctionWorker(StreamClass.KLINES, meet_at_barrier),
            FunctionWorker(StreamClass.AGG_TRADES, meet_at_barrier),
            FunctionWorker(StreamClass.BOOK_DIFFS, meet_at_barrier),
            FunctionWorker(StreamClass.BOOK_FEATURES, meet_at_barrier),
        ]
    )

    report = supervisor.run_cycle(timeout=15.0)

    assert report.ok, report.failures
    # Off the caller's thread, on distinct ingest worker threads.
    assert threading.current_thread().name not in seen_threads
    assert len(set(seen_threads)) == workers_count
    assert all(name.startswith("ingest-worker-") for name in seen_threads)


def test_hung_worker_times_out_into_a_per_stream_failure() -> None:
    # A wedged feed must not hold the report hostage: past the budget it
    # becomes a per-stream timeout failure and run_cycle returns anyway.
    supervisor = IngestSupervisor(
        [
            FunctionWorker(StreamClass.AGG_TRADES, lambda: 20),
            FunctionWorker(StreamClass.KLINES, lambda: (time.sleep(5), 10)[1]),
            FunctionWorker(StreamClass.FUNDING, lambda: 50),
        ]
    )

    started = time.monotonic()
    report = supervisor.run_cycle(timeout=0.25)
    elapsed = time.monotonic() - started

    assert elapsed < 4.0  # returned promptly, well inside the hung sleep
    assert not report.ok
    assert len(report.failures) == 1
    timed_out = report.failures[0]
    assert timed_out.stream is StreamClass.KLINES
    assert timed_out.failure.error_type == WORKER_TIMEOUT_ERROR_TYPE
    assert "budget" in timed_out.failure.message
    # The streams that finished inside the budget report normally.
    for stream in (StreamClass.AGG_TRADES, StreamClass.FUNDING):
        outcome = report.outcome_for(stream)
        assert outcome is not None and outcome.ok


def test_worker_raising_timeout_is_a_failure_not_a_deadline_miss() -> None:
    # A worker whose own code raises TimeoutError failed for its own
    # reasons; the report must say so instead of blaming the budget.
    def impatient() -> int:
        raise TimeoutError("exchange read timed out")

    supervisor = IngestSupervisor(
        [
            FunctionWorker(StreamClass.BOOK_DIFFS, impatient),
            FunctionWorker(StreamClass.KLINES, lambda: 1),
        ]
    )

    report = supervisor.run_cycle(timeout=10.0)

    assert len(report.failures) == 1
    assert report.failures[0].stream is StreamClass.BOOK_DIFFS
    assert report.failures[0].failure.error_type == "TimeoutError"
    assert report.outcome_for(StreamClass.KLINES).ok


def test_bad_worker_return_value_becomes_a_per_stream_failure() -> None:
    # A worker that breaks the contract (returns junk) is a failing
    # stream, not an exception escaping the reporting loop.
    class JunkWorker:
        stream_class = StreamClass.EXCHANGE_INFO

        def run_cycle(self) -> object:  # type: ignore[override]
            return "not a CycleResult"

    supervisor = IngestSupervisor(
        [JunkWorker(), FunctionWorker(StreamClass.KLINES, lambda: 1)]
    )

    report = supervisor.run_cycle()

    assert len(report.failures) == 1
    failure = report.failures[0]
    assert failure.stream is StreamClass.EXCHANGE_INFO
    assert failure.failure.error_type == "TypeError"
    assert "CycleResult" in failure.failure.message
    assert report.outcome_for(StreamClass.KLINES).ok


def test_worker_system_exit_is_contained_to_its_stream() -> None:
    # Even a worker calling sys.exit stays inside its stream's outcome;
    # nothing the worker does takes the supervisor down.
    def quitter() -> int:
        raise SystemExit(1)

    supervisor = IngestSupervisor(
        [
            FunctionWorker(StreamClass.AGG_TRADES, quitter),
            FunctionWorker(StreamClass.KLINES, lambda: 1),
        ]
    )

    report = supervisor.run_cycle()

    assert len(report.failures) == 1
    assert report.failures[0].stream is StreamClass.AGG_TRADES
    assert report.failures[0].failure.error_type == "SystemExit"
    assert report.outcome_for(StreamClass.KLINES).ok


def test_duplicate_worker_for_a_stream_class_is_rejected() -> None:
    # One worker per stream class is the invariant isolation stands on;
    # violating it is a wiring error raised at construction.
    supervisor = IngestSupervisor([FunctionWorker(StreamClass.KLINES, lambda: 1)])
    with pytest.raises(ValueError, match="one worker per stream class"):
        supervisor.add_worker(FunctionWorker("klines", lambda: 2))
    assert len(supervisor) == 1  # unchanged by the rejected add


def test_worker_without_a_cycle_is_rejected() -> None:
    class NotAWorker:
        stream_class = StreamClass.KLINES

    with pytest.raises(TypeError, match="no callable run_cycle"):
        IngestSupervisor([NotAWorker()])  # type: ignore[list-item]


def test_worker_with_bogus_stream_class_is_rejected() -> None:
    class BogusStreamWorker:
        stream_class = "notAStream"

        def run_cycle(self) -> object:
            return None

    with pytest.raises(TypeError, match="does not expose a valid stream_class"):
        IngestSupervisor([BogusStreamWorker()])


def test_empty_supervisor_reports_an_ok_empty_cycle() -> None:
    # No streams yet is a valid, running state — not an error.
    report = IngestSupervisor().run_cycle()
    assert isinstance(report, IngestReport)
    assert report.ok
    assert len(report) == 0
    assert report.outcomes == ()
    assert report.failures == ()


def test_reports_are_ordered_by_stream_class_deterministically() -> None:
    # Completion order must not leak into the report: two runs over the
    # same workers, with a staggered sleeper, report identically.
    def make_supervisor(sleep_first: bool) -> IngestSupervisor:
        def slow() -> int:
            time.sleep(0.05 if sleep_first else 0.0)
            return 1

        return IngestSupervisor(
            [
                FunctionWorker(StreamClass.EXCHANGE_INFO, lambda: 1),
                FunctionWorker(StreamClass.KLINES, slow),
                FunctionWorker(StreamClass.AGG_TRADES, lambda: 1),
            ]
        )

    first = make_supervisor(sleep_first=True).run_cycle()
    second = make_supervisor(sleep_first=False).run_cycle()

    expected = [StreamClass.AGG_TRADES, StreamClass.EXCHANGE_INFO, StreamClass.KLINES]
    assert [outcome.stream for outcome in first] == expected
    assert [outcome.stream for outcome in second] == expected


def test_supervisor_introspection() -> None:
    supervisor = IngestSupervisor(
        [
            FunctionWorker(StreamClass.FUNDING, lambda: 1),
            FunctionWorker(StreamClass.KLINES, lambda: 1),
        ]
    )
    assert supervisor.stream_classes == (
        StreamClass.FUNDING,
        StreamClass.KLINES,
    )
    assert supervisor.worker_for("klines") is not None
    assert supervisor.worker_for(StreamClass.BOOK_DIFFS) is None
    assert StreamClass.FUNDING in supervisor
    assert "aggTrades" not in supervisor
    assert [w.stream_class for w in supervisor] == [
        StreamClass.FUNDING,
        StreamClass.KLINES,
    ]


def test_worker_accepted_via_add_worker_return() -> None:
    supervisor = IngestSupervisor()
    worker = supervisor.add_worker(FunctionWorker(StreamClass.KLINES, lambda: 1))
    assert supervisor.worker_for(StreamClass.KLINES) is worker


def test_outcome_for_a_stream_without_a_worker_is_none() -> None:
    report = IngestSupervisor(
        [FunctionWorker(StreamClass.KLINES, lambda: 1)]
    ).run_cycle()
    assert report.outcome_for(StreamClass.AGG_TRADES) is None


def test_membership_check_rejects_junk_as_absent() -> None:
    supervisor = IngestSupervisor([FunctionWorker(StreamClass.KLINES, lambda: 1)])
    assert 7 not in supervisor  # junk is simply not a member
    assert ["nonsense"] not in supervisor


def test_operator_interrupt_is_not_disguised_as_a_stream_failure() -> None:
    # A KeyboardInterrupt in the supervisor's own thread while it waits
    # is an operator signal, not a stream failure: it must propagate out
    # of run_cycle rather than be converted into a per-stream record.
    import signal

    def interrupt_then_stall() -> int:
        signal.raise_signal(signal.SIGINT)  # delivered to the main thread
        time.sleep(1.5)  # the daemon thread is dropped on exit either way
        return 1

    supervisor = IngestSupervisor(
        [FunctionWorker(StreamClass.KLINES, interrupt_then_stall)]
    )

    with pytest.raises(KeyboardInterrupt):
        supervisor.run_cycle(timeout=8.0)
