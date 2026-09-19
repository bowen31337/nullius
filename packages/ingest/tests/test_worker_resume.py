"""The crash-safe worker: resume from the last persisted sequence.

These tests are the feature statement for app_spec.xml feature 29's
worker half — *"restarts an ingest worker safely after a crash, resuming
from the last persisted sequence with no duplicate rows"* — read as
behaviour of :class:`ResumableFunctionWorker` over a durable
:class:`SequenceStore`:

* each cycle commits the next batch after the store's watermark and
  reports its sequence;
* an empty fetch commits nothing and reports ``sequence=0``;
* a restart — a fresh worker over the same store — resumes from the
  sequence the store reports, re-fetching an uncommitted batch and never
  rewriting a committed one, so no batch is ever written twice.
"""

from __future__ import annotations

import pytest

from nullius_ingest import (
    Batch,
    InMemorySequenceStore,
    ResumableFunctionWorker,
    SequenceStore,
    StreamClass,
)


def make_worker(store, batches):
    """A resumable worker whose batches are queued, keyed by sequence.

    ``batches`` maps a resume sequence to the :class:`Batch` the fetch
    would return, or to ``None`` for an empty fetch.  The factory takes
    the resume sequence — exactly as a real fetch takes where to resume —
    so the same worker reconstructed after a crash resumes from the
    sequence the store reports.
    """

    def build_batch(resume: int) -> Batch | None:
        if resume not in batches:
            raise KeyError(f"no batch queued for resume sequence {resume}")
        return batches[resume]

    return ResumableFunctionWorker(StreamClass.KLINES, store, build_batch)


def test_worker_commits_the_next_batch_after_the_watermark() -> None:
    store = InMemorySequenceStore()
    worker = make_worker(store, {1: Batch(sequence=1, payload=b"a", rows=10)})

    result = worker.run_cycle()

    assert result.rows_written == 10
    assert result.sequence == 1
    assert store.current(StreamClass.KLINES) == 1


def test_worker_reports_sequence_zero_on_empty_fetch() -> None:
    store = InMemorySequenceStore()
    worker = make_worker(store, {1: None})

    result = worker.run_cycle()

    assert result.rows_written == 0
    assert result.sequence == 0
    # Nothing was committed: the watermark stays at 0.
    assert store.current(StreamClass.KLINES) == 0


def test_worker_advances_the_watermark_across_cycles() -> None:
    store = InMemorySequenceStore()
    worker = make_worker(
        store,
        {1: Batch(sequence=1, payload=b"a", rows=3), 2: Batch(sequence=2, payload=b"b", rows=4)},
    )

    first = worker.run_cycle()
    second = worker.run_cycle()

    assert (first.sequence, second.sequence) == (1, 2)
    assert store.current(StreamClass.KLINES) == 2


def test_restart_resumes_from_the_last_persisted_sequence() -> None:
    # The core of feature 29: a worker that has committed two batches is
    # "restarted" — a fresh worker over the same store — and its next
    # cycle resumes at sequence 3, the sequence after the watermark.
    store = InMemorySequenceStore()
    make_worker(
        store,
        {
            1: Batch(sequence=1, payload=b"a", rows=3),
            2: Batch(sequence=2, payload=b"b", rows=4),
        },
    ).run_cycle()
    make_worker(store, {2: Batch(sequence=2, payload=b"b", rows=4)}).run_cycle()

    restarted = make_worker(store, {3: Batch(sequence=3, payload=b"c", rows=5)})
    result = restarted.run_cycle()

    assert result.sequence == 3
    assert store.current(StreamClass.KLINES) == 3


def test_a_caught_up_worker_fetches_nothing_and_reports_zero() -> None:
    # When there is nothing past the watermark, the fetch returns None:
    # the worker commits nothing, reports ``sequence=0`` (no batch, no
    # progress), and the watermark is unchanged.  This is the steady state
    # of a worker that has ingested everything currently available.
    store = InMemorySequenceStore()
    make_worker(store, {1: Batch(sequence=1, payload=b"a", rows=3)}).run_cycle()

    caught_up = make_worker(store, {2: None})
    result = caught_up.run_cycle()

    assert result.rows_written == 0
    assert result.sequence == 0
    assert store.current(StreamClass.KLINES) == 1


def test_restart_refetches_an_uncommitted_batch(tmp_path) -> None:
    # The crash-safety case on a durable store: a batch was fetched but
    # the commit never happened (crash before the atomic rename), so the
    # store's watermark is still 0.  A restart resumes at sequence 1,
    # re-fetches the batch, and commits it once — no duplicate.
    root = tmp_path / "staging"
    store = SequenceStore(root)

    # First attempt: the fetch produced a batch, but we simulate the crash
    # by never calling commit — the batch never reached the store.
    assert store.current(StreamClass.KLINES) == 0

    # Restart: a fresh worker over the same durable store resumes at 1.
    restarted = make_worker(store, {1: Batch(sequence=1, payload=b"once", rows=7)})
    result = restarted.run_cycle()

    assert result.sequence == 1
    assert store.current(StreamClass.KLINES) == 1
    assert store.batches(StreamClass.KLINES) == (
        Batch(sequence=1, payload=b"once", rows=7),
    )  # written exactly once


def test_full_resume_sequence_is_gap_free_and_deduplicated(tmp_path) -> None:
    # End to end through several simulated crashes and restarts over one
    # durable store: the committed batches form a gap-free 1, 2, 3 log and
    # each is written exactly once, regardless of where the crashes fell.
    root = tmp_path / "staging"

    # Run 1: commit batches 1 and 2, then crash before batch 3's commit.
    store = SequenceStore(root)
    make_worker(
        store,
        {1: Batch(sequence=1, payload=b"1", rows=1), 2: Batch(sequence=2, payload=b"2", rows=1)},
    ).run_cycle()
    make_worker(store, {2: Batch(sequence=2, payload=b"2", rows=1)}).run_cycle()

    # Run 2 (restart): resume at 3, commit it, then crash before 4.
    store = SequenceStore(root)
    assert store.current(StreamClass.KLINES) == 2
    make_worker(store, {3: Batch(sequence=3, payload=b"3", rows=1)}).run_cycle()

    # Run 3 (restart): resume at 4, commit it.
    store = SequenceStore(root)
    assert store.current(StreamClass.KLINES) == 3
    make_worker(store, {4: Batch(sequence=4, payload=b"4", rows=1)}).run_cycle()

    final = SequenceStore(root)
    assert [b.sequence for b in final.batches(StreamClass.KLINES)] == [1, 2, 3, 4]
    assert final.current(StreamClass.KLINES) == 4


def test_resumable_worker_satisfies_the_ingest_worker_protocol() -> None:
    from nullius_ingest import IngestWorker

    worker = ResumableFunctionWorker(
        StreamClass.KLINES, InMemorySequenceStore(), lambda seq: None
    )
    assert isinstance(worker, IngestWorker)
    assert worker.stream_class is StreamClass.KLINES


def test_resumable_worker_rejects_a_non_store() -> None:
    with pytest.raises(TypeError, match="SequenceStore"):
        ResumableFunctionWorker(StreamClass.KLINES, "not a store", lambda seq: None)  # type: ignore[arg-type]


def test_resumable_worker_rejects_a_non_callable_factory() -> None:
    with pytest.raises(TypeError, match="callable"):
        ResumableFunctionWorker(StreamClass.KLINES, InMemorySequenceStore(), object())  # type: ignore[arg-type]


def test_resumable_worker_coerces_stream_class() -> None:
    worker = ResumableFunctionWorker(
        "klines", InMemorySequenceStore(), lambda seq: None
    )
    assert worker.stream_class is StreamClass.KLINES


def test_resumable_worker_rejects_a_non_batch_return() -> None:
    store = InMemorySequenceStore()
    worker = ResumableFunctionWorker(StreamClass.KLINES, store, lambda seq: "not a batch")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Batch"):
        worker.run_cycle()


def test_resumable_worker_runs_under_the_supervisor(tmp_path) -> None:
    # A resumable worker is still an IngestWorker: the supervisor runs it
    # and reports its rows, so crash-safety and failure-isolation compose.
    from nullius_ingest import IngestSupervisor

    root = tmp_path / "staging"
    store = SequenceStore(root)
    worker = make_worker(store, {1: Batch(sequence=1, payload=b"a", rows=6)})

    report = IngestSupervisor([worker]).run_cycle()

    assert report.ok
    assert report.outcome_for(StreamClass.KLINES).rows_written == 6
    assert store.current(StreamClass.KLINES) == 1
