"""The durable sequence store: last-persisted sequence, atomic commit.

These tests are the feature statement for app_spec.xml feature 29's
durability half — *"resuming from the last persisted sequence with no
duplicate rows"* — read as behaviour of the store that makes resume safe:

* a committed batch advances the watermark to its sequence;
* a crash mid-commit leaves the batch absent, so the watermark does not
  advance and the batch is re-fetched, never duplicated;
* a restart reconstructs the watermark from disk, so a fresh worker over
  the same store resumes from exactly the last persisted sequence.
"""

from __future__ import annotations

import pytest

from nullius_ingest import (
    Batch,
    InMemorySequenceStore,
    SequenceStore,
    StreamClass,
)


# -- current / watermark --------------------------------------------------


def test_current_is_zero_for_an_uncommitted_stream() -> None:
    # A stream with no committed batch starts at 0 — the honest "no
    # progress" watermark a fresh worker resumes from.
    store = InMemorySequenceStore()
    assert store.current(StreamClass.KLINES) == 0


def test_current_is_the_highest_committed_sequence() -> None:
    store = InMemorySequenceStore()
    store.commit(StreamClass.KLINES, Batch(sequence=1, payload=b"a", rows=3))
    store.commit(StreamClass.KLINES, Batch(sequence=2, payload=b"b", rows=5))
    assert store.current(StreamClass.KLINES) == 2


def test_each_stream_has_its_own_watermark() -> None:
    # Watermarks are per stream class: committing one stream never moves
    # another, exactly as one worker's progress must not leak into another.
    store = InMemorySequenceStore()
    store.commit(StreamClass.KLINES, Batch(sequence=4, payload=b"k"))
    assert store.current(StreamClass.KLINES) == 4
    assert store.current(StreamClass.AGG_TRADES) == 0


def test_batches_are_returned_in_ascending_sequence_order() -> None:
    store = InMemorySequenceStore()
    store.commit(StreamClass.KLINES, Batch(sequence=3, payload=b"c"))
    store.commit(StreamClass.KLINES, Batch(sequence=1, payload=b"a"))
    store.commit(StreamClass.KLINES, Batch(sequence=2, payload=b"b"))
    assert [b.sequence for b in store.batches(StreamClass.KLINES)] == [1, 2, 3]
    assert store.batches(StreamClass.KLINES)[0].payload == b"a"


# -- commit invariants ----------------------------------------------------


def test_commit_rejects_a_non_positive_sequence() -> None:
    store = InMemorySequenceStore()
    with pytest.raises(ValueError, match="positive"):
        store.commit(StreamClass.KLINES, Batch(sequence=0, payload=b"x"))
    with pytest.raises(ValueError, match="positive"):
        store.commit(StreamClass.KLINES, Batch(sequence=-1, payload=b"x"))


def test_commit_rejects_a_duplicate_sequence() -> None:
    # The store's half of "no duplicate rows": a second batch at one
    # sequence is an error, not a silent overwrite.
    store = InMemorySequenceStore()
    store.commit(StreamClass.KLINES, Batch(sequence=1, payload=b"first"))
    with pytest.raises(ValueError, match="already has a batch"):
        store.commit(StreamClass.KLINES, Batch(sequence=1, payload=b"second"))
    # The original batch is untouched by the rejected commit.
    assert store.batches(StreamClass.KLINES)[0].payload == b"first"


def test_commit_accepts_string_stream_value() -> None:
    store = InMemorySequenceStore()
    store.commit("klines", Batch(sequence=1, payload=b"a"))
    assert store.current(StreamClass.KLINES) == 1


# -- on-disk durability ---------------------------------------------------


def test_disk_store_persists_and_reports_the_watermark(tmp_path) -> None:
    root = tmp_path / "staging"
    store = SequenceStore(root)
    store.commit(StreamClass.KLINES, Batch(sequence=1, payload=b"a", rows=2))
    store.commit(StreamClass.KLINES, Batch(sequence=2, payload=b"b", rows=4))
    assert store.current(StreamClass.KLINES) == 2


def test_a_restart_reconstructs_the_last_persisted_sequence(tmp_path) -> None:
    # The defining behaviour of feature 29: a fresh store over the same
    # directory reports the sequence a prior run left durably committed —
    # the point a restarted worker resumes from.
    root = tmp_path / "staging"
    SequenceStore(root).commit(StreamClass.KLINES, Batch(sequence=7, payload=b"x"))

    restarted = SequenceStore(root)
    assert restarted.current(StreamClass.KLINES) == 7


def test_load_reflects_a_prior_run_without_recommitting(tmp_path) -> None:
    # load() reads what is on disk; committing the same sequence again is
    # refused, proving the prior batch really is committed, not merely
    # observed.
    root = tmp_path / "staging"
    SequenceStore(root).commit(StreamClass.FUNDING, Batch(sequence=3, payload=b"f"))

    restarted = SequenceStore(root)
    with pytest.raises(ValueError, match="already has a batch"):
        restarted.commit(StreamClass.FUNDING, Batch(sequence=3, payload=b"again"))


def test_each_stream_writes_to_its_own_directory(tmp_path) -> None:
    root = tmp_path / "staging"
    store = SequenceStore(root)
    store.commit(StreamClass.KLINES, Batch(sequence=1, payload=b"k"))
    store.commit(StreamClass.AGG_TRADES, Batch(sequence=1, payload=b"a"))
    assert (root / "klines" / "1.bin").is_file()
    assert (root / "aggTrades" / "1.bin").is_file()


def test_payload_round_trips_through_disk(tmp_path) -> None:
    # The durable artifact is sequence + payload; ``rows`` is a reporting
    # annotation the worker carries, not part of the persisted batch, so a
    # reload recovers the payload verbatim and the sequence, and ``rows``
    # comes back at its durable default.
    root = tmp_path / "staging"
    SequenceStore(root).commit(
        StreamClass.BOOK_DIFFS, Batch(sequence=1, payload=b"\x00\x01\x02", rows=9)
    )
    batches = SequenceStore(root).batches(StreamClass.BOOK_DIFFS)
    assert batches == (Batch(sequence=1, payload=b"\x00\x01\x02"),)


# -- crash safety ---------------------------------------------------------


def test_a_crash_mid_commit_leaves_the_batch_absent(tmp_path) -> None:
    # Simulate a crash before the atomic rename: only a ``.tmp-*`` file
    # exists, never a ``<seq>.bin``.  A restarted store must ignore it —
    # the batch was never committed — so the watermark stays unadvanced
    # and the batch is re-fetched, never duplicated.
    root = tmp_path / "staging"
    directory = root / "klines"
    directory.mkdir(parents=True)
    (directory / ".tmp-abc.tmp").write_bytes(b"half-written")

    store = SequenceStore(root)
    assert store.current(StreamClass.KLINES) == 0
    assert store.batches(StreamClass.KLINES) == ()


def test_stray_non_integer_files_are_ignored(tmp_path) -> None:
    # The stream directory is a pure function of committed batches: a
    # stray file that is not an integer-named ``.bin`` contributes nothing
    # to the watermark.
    root = tmp_path / "staging"
    directory = root / "klines"
    directory.mkdir(parents=True)
    (directory / "README").write_text("not a batch")
    (directory / "notanumber.bin").write_bytes(b"junk")

    store = SequenceStore(root)
    assert store.current(StreamClass.KLINES) == 0


def test_a_committed_batch_survives_a_restart_intact(tmp_path) -> None:
    # The other half of crash safety: a batch committed before the crash
    # is still there after the restart, at its sequence, with its payload.
    root = tmp_path / "staging"
    SequenceStore(root).commit(
        StreamClass.KLINES, Batch(sequence=5, payload=b"committed", rows=11)
    )
    restarted = SequenceStore(root)
    assert restarted.current(StreamClass.KLINES) == 5
    assert restarted.batches(StreamClass.KLINES)[0].payload == b"committed"


def test_commit_is_atomic_no_torn_files(tmp_path) -> None:
    # A committed batch is a whole ``<seq>.bin`` with the exact payload —
    # never a truncated or partial file — because the write is fsynced and
    # atomically renamed into place.
    root = tmp_path / "staging"
    store = SequenceStore(root)
    store.commit(StreamClass.KLINES, Batch(sequence=1, payload=b"whole-payload"))
    assert (root / "klines" / "1.bin").read_bytes() == b"whole-payload"
