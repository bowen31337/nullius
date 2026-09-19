"""The append-only ingest staging area — the write side of the seal boundary.

These tests are the feature statement for app_spec.xml feature 28 —
*"System persists all ingest output append-only into a staging area that
never appears on the evaluator mount path"* — read as behaviour of
:class:`StagingArea`:

* appends land in a gap-free ``<stream>/<seq>.bin`` log under ``staging/``;
* a second append at a sequence the store already holds is refused, so
  staging is append-only, never overwrite;
* a restart — a fresh area over the same staging tree — resumes appending
  past whatever a prior run left;
* staging is a *sibling* of snapshots, never inside one: a staging area
  rooted at, or beneath, a ``snapshots/`` directory is refused, which is
  feature 28's "never on the evaluator mount path" made structural on the
  write side;
* a batch may be *retired* — taken away whole, never rewritten — which is the
  seam feature 19's rolling 90 day book-diff window needs and which leaves
  append-only intact: every byte that survives is still a byte that was
  committed.
"""

from __future__ import annotations

import pytest

from nullius_ingest import (
    StagedBatch,
    StagingArea,
    StagingRootError,
    StreamClass,
)
from nullius_ingest.watermark import Batch


# -- Append-only log --------------------------------------------------------


def test_append_writes_the_first_batch_at_sequence_one(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")

    batch = area.append(StreamClass.KLINES, payload=b"row-a", rows=5)

    assert isinstance(batch, StagedBatch)
    assert batch.sequence == 1
    assert batch.rows == 5
    assert batch.payload == b"row-a"
    assert batch.path == tmp_path / "staging" / "klines" / "1.bin"
    assert (tmp_path / "staging" / "klines" / "1.bin").read_bytes() == b"row-a"


def test_appends_form_a_gap_free_sequence(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")

    first = area.append(StreamClass.KLINES, b"a", rows=1)
    second = area.append(StreamClass.KLINES, b"b", rows=2)
    third = area.append(StreamClass.KLINES, b"c", rows=3)

    assert (first.sequence, second.sequence, third.sequence) == (1, 2, 3)
    assert area.current(StreamClass.KLINES) == 3
    assert [b.sequence for b in area.staged(StreamClass.KLINES)] == [1, 2, 3]


def test_staging_is_per_stream(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")

    k = area.append(StreamClass.KLINES, b"k", rows=1)
    t = area.append(StreamClass.AGG_TRADES, b"t", rows=1)

    # Each stream owns its own log and its own directory.
    assert k.sequence == 1
    assert t.sequence == 1
    assert area.current(StreamClass.KLINES) == 1
    assert area.current(StreamClass.AGG_TRADES) == 1
    assert k.path.parent != t.path.parent


def test_committing_a_second_batch_at_a_sequence_is_refused(tmp_path) -> None:
    # The append-only guard: once a batch holds a sequence, committing
    # another batch at that same sequence is refused, not written over.
    # (``append`` always claims ``current + 1``, so it can never reach this
    # path on its own; this exercises the guard it stands on.)
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.KLINES, b"first", rows=1)

    with pytest.raises(ValueError, match="duplicate commit"):
        area.commit(StreamClass.KLINES, Batch(sequence=1, payload=b"overwrite"))

    # The original batch is intact — never overwritten.
    assert (tmp_path / "staging" / "klines" / "1.bin").read_bytes() == b"first"


def test_append_is_idempotent_only_in_return_not_in_write(tmp_path) -> None:
    # Two appends in a row advance the log; append-only means each gets a
    # new sequence, never the same file.
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.KLINES, b"a", rows=1)
    area.append(StreamClass.KLINES, b"b", rows=1)

    files = sorted(p.name for p in (tmp_path / "staging" / "klines").iterdir())
    assert files == ["1.bin", "2.bin"]


# -- Restart over an existing tree -----------------------------------------


def test_restart_resumes_appending_past_the_high_water_mark(tmp_path) -> None:
    # A prior run left two batches; a fresh area over the same tree resumes
    # at sequence 3 — the "last persisted sequence" feature 28 shares with
    # feature 29's resume contract.
    StagingArea(tmp_path / "staging").append(StreamClass.KLINES, b"a", rows=1)
    StagingArea(tmp_path / "staging").append(StreamClass.KLINES, b"b", rows=1)

    restarted = StagingArea(tmp_path / "staging")
    assert restarted.current(StreamClass.KLINES) == 2
    batch = restarted.append(StreamClass.KLINES, b"c", rows=1)
    assert batch.sequence == 3


def test_staged_batches_survive_across_a_restart(tmp_path) -> None:
    StagingArea(tmp_path / "staging").append(StreamClass.KLINES, b"a", rows=1)
    StagingArea(tmp_path / "staging").append(StreamClass.KLINES, b"b", rows=1)

    restarted = StagingArea(tmp_path / "staging")
    assert [b.payload for b in restarted.staged(StreamClass.KLINES)] == [b"a", b"b"]


# -- The never-on-mount-path guarantee --------------------------------------


def test_staging_root_refused_when_it_is_a_snapshots_dir(tmp_path) -> None:
    # Rooting staging *at* a snapshots directory would put ingest output on
    # the evaluator's mount — feature 28 forbids it, structurally.
    snapshots = tmp_path / "lake" / "snapshots"
    snapshots.mkdir(parents=True)

    with pytest.raises(StagingRootError, match="snapshots"):
        StagingArea(snapshots)


def test_staging_root_refused_when_it_is_inside_a_snapshots_dir(tmp_path) -> None:
    # A staging area *beneath* snapshots/ is refused too: it would still
    # appear on the evaluator mount path.
    nested = tmp_path / "lake" / "snapshots" / "staging"
    nested.mkdir(parents=True)

    with pytest.raises(StagingRootError, match="snapshots"):
        StagingArea(nested)


def test_sibling_of_snapshots_is_allowed(tmp_path) -> None:
    # The correct layout: staging beside snapshots, not inside it.
    lake = tmp_path / "lake"
    (lake / "snapshots").mkdir(parents=True)

    area = StagingArea(lake / "staging")
    assert area.root == lake / "staging"


def test_from_env_points_staging_next_to_the_sealed_snapshots(tmp_path, monkeypatch) -> None:
    # §4.2 layout: staging is a sibling of snapshots under the lake root the
    # sealing service resolves from the same LAKE_ROOT.
    lake = tmp_path / "lake"
    (lake / "snapshots").mkdir(parents=True)
    monkeypatch.setenv("LAKE_ROOT", str(lake))

    area = StagingArea.from_env()
    assert area.root == lake / "staging"
    # And it is usable: an append lands under staging, never snapshots.
    batch = area.append(StreamClass.KLINES, b"a", rows=1)
    assert batch.path == lake / "staging" / "klines" / "1.bin"
    assert list((lake / "snapshots").iterdir()) == []  # nothing written to snapshots


def test_from_env_rejects_a_snapshots_lake_root(tmp_path, monkeypatch) -> None:
    # A LAKE_ROOT that is itself a snapshots directory would make staging a
    # snapshots tree; from_env refuses it rather than misplacing output.
    snapshots = tmp_path / "lake" / "snapshots"
    snapshots.mkdir(parents=True)
    monkeypatch.setenv("LAKE_ROOT", str(snapshots))

    with pytest.raises(StagingRootError, match="snapshots"):
        StagingArea.from_env()


# -- Durability of an append ------------------------------------------------


def test_a_crash_mid_append_leaves_no_committed_batch(tmp_path) -> None:
    # A crash before the atomic rename leaves only a .tmp-* file, which the
    # store ignores: the batch is absent, so a restart re-appends it, never
    # duplicating. This is the same property feature 29's resume relies on.
    area = StagingArea(tmp_path / "staging")
    directory = tmp_path / "staging" / "klines"
    directory.mkdir(parents=True)
    # Simulate a torn append: a temp file, no committed <seq>.bin.
    (directory / ".tmp-abc.tmp").write_bytes(b"half-written")

    fresh = StagingArea(tmp_path / "staging")
    assert fresh.current(StreamClass.KLINES) == 0
    batch = fresh.append(StreamClass.KLINES, b"whole", rows=1)
    assert batch.sequence == 1  # the temp file did not claim sequence 1
    assert (directory / "1.bin").read_bytes() == b"whole"


def test_append_reports_sequence_zero_rows_without_a_batch(tmp_path) -> None:
    # rows is a reporting hint carried on the batch, not part of the durable
    # artifact; a zero-row append is a valid, honest append.
    area = StagingArea(tmp_path / "staging")
    batch = area.append(StreamClass.FUNDING, b"", rows=0)
    assert batch.rows == 0
    assert batch.sequence == 1


# -- Retiring a whole batch -------------------------------------------------
#
# Feature 19's L2 book diffs are the one §4.1 stream kept under a *rolling 90
# day* window, so a staging area that could only ever grow would make that
# policy a lie.  ``retire`` is the narrow removal that lets a retention window
# exist without weakening append-only: a batch is taken away whole, so every
# byte that survives is still a byte that was committed.


def test_retire_removes_a_whole_batch(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)
    second = area.append(StreamClass.BOOK_DIFFS, b"b", rows=1)
    third = area.append(StreamClass.BOOK_DIFFS, b"c", rows=1)

    removed = area.retire(StreamClass.BOOK_DIFFS, [1])

    assert removed == (1,)
    assert not (tmp_path / "staging" / "bookDiffs" / "1.bin").exists()
    # The survivors are untouched, byte for byte — retirement takes a batch
    # away, it never edits one.
    assert second.path.read_bytes() == b"b"
    assert third.path.read_bytes() == b"c"
    assert [b.sequence for b in area.staged(StreamClass.BOOK_DIFFS)] == [2, 3]


def test_retire_drops_the_batch_from_the_watermark_view(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"b", rows=1)

    area.retire(StreamClass.BOOK_DIFFS, [1])

    assert area.current(StreamClass.BOOK_DIFFS) == 2
    assert [b.payload for b in area.staged(StreamClass.BOOK_DIFFS)] == [b"b"]


def test_retire_never_lets_a_retired_sequence_be_reused(tmp_path) -> None:
    # The watermark is derived from the files on disk, so the newest batch is
    # kept as the anchor: retiring every file would let the next append reuse a
    # sequence this log has already spent.
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"b", rows=1)

    area.retire(StreamClass.BOOK_DIFFS, [1])

    assert area.append(StreamClass.BOOK_DIFFS, b"c", rows=1).sequence == 3


def test_retire_refuses_the_newest_batch(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"b", rows=1)

    with pytest.raises(ValueError, match="newest committed batch"):
        area.retire(StreamClass.BOOK_DIFFS, [2])

    # Refused before anything was unlinked.
    assert (tmp_path / "staging" / "bookDiffs" / "2.bin").exists()


def test_retire_refuses_a_sequence_that_was_never_committed(tmp_path) -> None:
    # Silently ignoring it would let a caller believe it expired something that
    # was never there — and the caller is a retention policy deciding what a
    # lake still holds.
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"b", rows=1)

    with pytest.raises(ValueError, match="never committed"):
        area.retire(StreamClass.BOOK_DIFFS, [9])

    with pytest.raises(ValueError, match="must be positive"):
        area.retire(StreamClass.BOOK_DIFFS, [0])


def test_a_mixed_retirement_request_is_refused_wholesale(tmp_path) -> None:
    # Validate the whole request before touching any file, so a bad sequence
    # cannot half-retire a log into a state no report describes.
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"b", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"c", rows=1)

    with pytest.raises(ValueError, match="never committed"):
        area.retire(StreamClass.BOOK_DIFFS, [1, 9])

    # Sequence 1 is still there: the refusal happened before any unlink.
    assert (tmp_path / "staging" / "bookDiffs" / "1.bin").exists()


def test_retiring_several_batches_removes_them_all(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")
    for payload in (b"a", b"b", b"c", b"d"):
        area.append(StreamClass.BOOK_DIFFS, payload, rows=1)

    removed = area.retire(StreamClass.BOOK_DIFFS, [1, 2, 3])

    assert removed == (1, 2, 3)
    assert [b.sequence for b in area.staged(StreamClass.BOOK_DIFFS)] == [4]


def test_retiring_nothing_is_a_no_op(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)

    assert area.retire(StreamClass.BOOK_DIFFS, []) == ()
    assert area.current(StreamClass.BOOK_DIFFS) == 1


def test_a_retirement_survives_a_restart(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"b", rows=1)
    area.retire(StreamClass.BOOK_DIFFS, [1])

    restarted = StagingArea(tmp_path / "staging")

    assert [b.sequence for b in restarted.staged(StreamClass.BOOK_DIFFS)] == [2]
    assert restarted.current(StreamClass.BOOK_DIFFS) == 2


def test_retire_touches_only_the_named_stream(tmp_path) -> None:
    # §4.1's retention column is per-stream: retiring one stream's log must
    # never reach into another's.
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"diff-1", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"diff-2", rows=1)
    area.append(StreamClass.FUNDING, b"poll-1", rows=1)

    area.retire(StreamClass.BOOK_DIFFS, [1])

    assert [b.payload for b in area.staged(StreamClass.FUNDING)] == [b"poll-1"]
    assert area.current(StreamClass.FUNDING) == 1


def test_retire_accepts_a_streams_string_spelling(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")
    area.append(StreamClass.BOOK_DIFFS, b"a", rows=1)
    area.append(StreamClass.BOOK_DIFFS, b"b", rows=1)

    assert area.retire("bookDiffs", [1]) == (1,)


def test_retire_rejects_an_unknown_stream(tmp_path) -> None:
    area = StagingArea(tmp_path / "staging")

    with pytest.raises(TypeError, match="unknown stream class"):
        area.retire("notAStream", [1])
