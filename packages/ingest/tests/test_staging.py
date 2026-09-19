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
  write side.
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
