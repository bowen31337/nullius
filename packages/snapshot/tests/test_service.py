"""Lake-root resolution and the one-shot sealing entry point."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import SnapshotError, SnapshotService, seal_snapshot

from app.module_loader import find_workspace_root

AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class TestFromEnv:
    def test_lake_root_env_var_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LAKE_ROOT", "/data/lake")
        service = SnapshotService.from_env()
        assert service.lake_root == Path("/data/lake")
        assert service.snapshots_root == Path("/data/lake/snapshots")
        assert service.staging_root == Path("/data/lake/staging")

    def test_blank_env_var_counts_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LAKE_ROOT", "   ")
        service = SnapshotService.from_env()
        assert service.lake_root == find_workspace_root() / "lake"

    def test_unset_env_var_defaults_to_the_workspace_lake(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LAKE_ROOT", raising=False)
        service = SnapshotService.from_env()
        assert service.lake_root == find_workspace_root() / "lake"

    def test_explicit_env_mapping_is_honoured_without_process_state(self) -> None:
        service = SnapshotService.from_env({"LAKE_ROOT": "/elsewhere/lake"})
        assert service.lake_root == Path("/elsewhere/lake")

    def test_no_env_and_no_workspace_root_refuses_to_guess(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("LAKE_ROOT", raising=False)
        monkeypatch.setattr(
            "snapshot._service.find_workspace_root", lambda *a, **k: None
        )
        with pytest.raises(SnapshotError, match="LAKE_ROOT"):
            SnapshotService.from_env()

    def test_construction_touches_nothing_on_disk(self, tmp_path: Path) -> None:
        # Building the service must be side-effect free: composition in a
        # barren environment cannot spray lake directories around.
        service = SnapshotService(tmp_path / "not-created")
        assert not service.lake_root.exists()

    def test_blank_lake_root_is_rejected(self) -> None:
        # Path("") would become "." and silently seal into the current
        # directory; the constructor refuses instead.
        with pytest.raises(SnapshotError, match="non-empty"):
            SnapshotService("   ")


class TestSealSnapshotOneShot:
    def test_seals_via_the_environment(
        self, lake_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LAKE_ROOT", str(lake_root))
        staging = lake_root / "staging"
        (staging / "bars").mkdir()
        (staging / "bars" / "part-0.parquet").write_bytes(b"one-shot")

        record = seal_snapshot(staging, sealed_at=AT)

        expected = lake_root / "snapshots" / f"2026-09-01T00:00:00Z_{record.hash_prefix}"
        assert record.path == expected
        assert (record.path / "bars" / "part-0.parquet").read_bytes() == b"one-shot"

    def test_explicit_lake_root_overrides_the_environment(
        self, lake_root: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other-lake"
        (other / "snapshots").mkdir(parents=True)
        source = tmp_path / "source"
        source.mkdir()
        (source / "a.parquet").write_bytes(b"a")

        record = seal_snapshot(source, sealed_at=AT, lake_root=other)

        assert record.path.parent == other / "snapshots"
