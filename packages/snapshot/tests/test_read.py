"""The read side: addressing and listing sealed snapshots.

``open`` is the seam the evaluator-facing features of this category build
on (the read-only mount, the staging-path rejection), so its strictness is
tested as its own contract: only canonical names become paths, and a
canonical name that names nothing is a miss, not a guess.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import (
    SnapshotNameError,
    SnapshotNotFoundError,
    SnapshotRef,
    SnapshotService,
)

AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
HASH = "a3f91c" + "0" * 58


@pytest.fixture
def sealed(service: SnapshotService, lake_root: Path) -> Path:
    staging = lake_root / "staging"
    (staging / "bars").mkdir()
    (staging / "bars" / "part-0.parquet").write_bytes(b"payload")
    return service.seal(staging, sealed_at=AT, snapshot_hash=HASH).path


class TestOpen:
    def test_opens_a_sealed_snapshot_by_name(
        self, service: SnapshotService, sealed: Path
    ) -> None:
        ref = service.open("2026-09-01T00:00:00Z_a3f91c")
        assert isinstance(ref, SnapshotRef)
        assert ref.path == sealed
        assert ref.sealed_at == AT
        assert ref.hash_prefix == "a3f91c"

    def test_unknown_name_is_a_miss(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        with pytest.raises(SnapshotNotFoundError, match="no sealed snapshot"):
            service.open("2026-09-01T00:00:00Z_000000")

    @pytest.mark.parametrize(
        "attack",
        [
            "../staging",
            "2026-09-01T00:00:00Z_a3f91c/..",
            "/2026-09-01T00:00:00Z_a3f91c",
            "2026-09-01T00:00:00Z_A3F91C",
            "not-a-name",
        ],
    )
    def test_malformed_names_never_become_paths(
        self, service: SnapshotService, attack: str
    ) -> None:
        with pytest.raises(SnapshotNameError):
            service.open(attack)


class TestSealedListing:
    def test_lists_sealed_snapshots_sorted_by_name(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        staging = lake_root / "staging"
        (staging / "a.parquet").write_bytes(b"a")
        first = service.seal(staging, sealed_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        (staging / "b.parquet").write_bytes(b"b")
        second = service.seal(staging, sealed_at=datetime(2026, 9, 2, tzinfo=timezone.utc))

        assert service.sealed() == sorted([first.name, second.name])

    def test_strays_are_not_snapshots(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        snapshots = lake_root / "snapshots"
        (snapshots / "junk").mkdir()
        (snapshots / "notes.txt").write_text("operator scribble")
        (snapshots / ".sealing-interrupted").mkdir()

        assert service.sealed() == []

    def test_a_lake_without_snapshots_is_empty(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        (lake_root / "snapshots").rmdir()
        assert service.sealed() == []
