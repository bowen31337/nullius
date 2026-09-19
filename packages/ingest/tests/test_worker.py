"""The worker contract's data types and the FunctionWorker adapter."""

from __future__ import annotations

import pytest

from nullius_ingest import CycleResult, FunctionWorker, StreamClass
from nullius_ingest import StreamFailure, StreamOutcome
from nullius_ingest.worker import IngestWorker


def test_cycle_result_defaults_to_zero_rows() -> None:
    assert CycleResult().rows_written == 0
    assert CycleResult(rows_written=5).rows_written == 5


def test_function_worker_normalises_int_none_and_cycle_result() -> None:
    # int rows, None, and a ready CycleResult all come out as a CycleResult.
    assert (
        FunctionWorker(StreamClass.KLINES, lambda: 7).run_cycle().rows_written
        == 7
    )
    assert (
        FunctionWorker(StreamClass.KLINES, lambda: None).run_cycle().rows_written
        == 0
    )
    ready = CycleResult(rows_written=3)
    assert FunctionWorker(StreamClass.KLINES, lambda: ready).run_cycle() is ready


def test_function_worker_satisfies_the_protocol() -> None:
    worker = FunctionWorker(StreamClass.FUNDING, lambda: 1)
    assert isinstance(worker, IngestWorker)
    assert worker.stream_class is StreamClass.FUNDING


def test_function_worker_coerces_stream_class_at_construction() -> None:
    assert FunctionWorker("funding", lambda: 0).stream_class is StreamClass.FUNDING


def test_function_worker_rejects_non_callable_at_construction() -> None:
    # A mis-wired worker fails at construction, not inside a cycle.
    with pytest.raises(TypeError, match="needs a callable cycle"):
        FunctionWorker(StreamClass.KLINES, "not callable")  # type: ignore[arg-type]


def test_function_worker_does_not_swallow_exceptions() -> None:
    # The adapter must let failures through: converting them here would
    # move the isolation boundary out of the supervisor.
    def boom() -> int:
        raise RuntimeError("feed down")

    with pytest.raises(RuntimeError, match="feed down"):
        FunctionWorker(StreamClass.AGG_TRADES, boom).run_cycle()


def test_stream_failure_captures_exception_details() -> None:
    def boom() -> int:
        raise ValueError("schema drifted")

    try:
        boom()
    except ValueError as exc:
        failure = StreamFailure.from_exception(StreamClass.BOOK_DIFFS, exc)

    assert failure.stream is StreamClass.BOOK_DIFFS
    assert failure.error_type == "ValueError"
    assert failure.message == "schema drifted"
    assert "boom" in failure.traceback
    assert "ValueError: schema drifted" in failure.traceback


def test_stream_failure_accepts_string_stream() -> None:
    try:
        raise KeyError("x")
    except KeyError as exc:
        failure = StreamFailure.from_exception("klines", exc)
    assert failure.stream is StreamClass.KLINES


def test_stream_outcome_ok_semantics() -> None:
    ok = StreamOutcome(stream=StreamClass.KLINES, rows_written=4)
    assert ok.ok and ok.failure is None

    failed = StreamOutcome(
        stream=StreamClass.KLINES,
        failure=StreamFailure(
            stream=StreamClass.KLINES,
            error_type="ValueError",
            message="no",
        ),
    )
    assert not failed.ok and failed.rows_written == 0
