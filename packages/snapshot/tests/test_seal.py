"""The seal operation: staging in, immutable named directory out.

These are the acceptance tests for app_spec.xml feature 30 — "System
persists a sealed snapshot into an immutable directory named by sealed_at
plus a hash prefix". Each block below maps to one clause of that sentence:

* *persists* — bytes land on disk under the lake's ``snapshots/`` root,
  staging is copied rather than consumed, and a crash can never leave a
  half-written directory under a sealed name (atomic publication).
* *immutable directory* — published files and directories are read-only at
  the filesystem level, and re-sealing different bytes under an existing
  name is refused.
* *named by sealed_at plus a hash prefix* — the directory name is exactly
  ``<sealed_at>_<snapshot_hash[:6]>`` for both the default §4.2 formula
  and a caller-supplied full hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional

import pytest
from snapshot import (
    SCHEMA_VERSION,
    SealedSnapshot,
    SnapshotAlreadySealedError,
    SnapshotContentError,
    SnapshotNameError,
    SnapshotService,
    content_digest,
    resolve_sealed_at,
    snapshot_name,
)

UTC = timezone.utc
AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
HASH = "a3f91c" + "0" * 58

BTC_PART_0 = b"BTCUSDT-2026-09-01-part-0"
BTC_PART_1 = b"BTCUSDT-2026-09-01-part-1"
ETH_PART_0 = b"ETHUSDT-2026-09-01-part-0"


def _formula(
    file_hashes: list[str],
    universe: Optional[Mapping[str, object]] = None,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """The §4.2 formula, spelled out independently of the implementation."""
    universe_term = (
        "null"
        if universe is None
        else json.dumps(dict(universe), sort_keys=True, separators=(",", ":"))
    )
    preimage = "\n".join(
        ("".join(sorted(file_hashes)), universe_term, schema_version)
    ).encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()


def _staged_hash(universe: Optional[Mapping[str, object]] = None) -> str:
    """The §4.2 formula over the staged fixture's bytes."""
    parts = [BTC_PART_0, BTC_PART_1, ETH_PART_0]
    return _formula([hashlib.sha256(p).hexdigest() for p in parts], universe)


def _working_dirs(lake_root: Path) -> list[str]:
    root = lake_root / "snapshots"
    if not root.is_dir():
        return []
    return [e.name for e in root.iterdir() if e.name.startswith(".sealing-")]


class TestPersistsANamedDirectory:
    def test_directory_name_is_sealed_at_and_hash_prefix(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        assert record.path.parent == lake_root / "snapshots"
        assert record.path.name == "2026-09-01T00:00:00Z_a3f91c"

    def test_default_hash_is_the_formula_over_the_staged_files(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        expected = _staged_hash()
        assert record.snapshot_hash == expected
        assert record.path.name == snapshot_name(AT, expected)
        # …and the fold is the full formula, not the bare content term: the
        # universe and schema terms are in the preimage the name abbreviates.
        assert record.snapshot_hash != content_digest(record.files)

    def test_bytes_land_on_disk_byte_for_byte(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        sealed_btc = record.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01"
        assert (sealed_btc / "part-0.parquet").read_bytes() == BTC_PART_0
        assert (sealed_btc / "part-1.parquet").read_bytes() == BTC_PART_1
        assert (
            record.path / "bars" / "symbol=ETHUSDT" / "date=2026-09-01" / "part-0.parquet"
        ).read_bytes() == ETH_PART_0

    def test_record_carries_the_per_file_hash_mapping(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        assert record.files[
            "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet"
        ] == hashlib.sha256(BTC_PART_0).hexdigest()
        assert set(record.files) == {
            "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet",
            "bars/symbol=BTCUSDT/date=2026-09-01/part-1.parquet",
            "bars/symbol=ETHUSDT/date=2026-09-01/part-0.parquet",
        }

    def test_staging_is_copied_not_consumed(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        service.seal(staged, sealed_at=AT)
        source = staged / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        assert source.read_bytes() == BTC_PART_0
        # Staging stays writable: ingest workers keep appending to it.
        (staged / "bars" / "new.parquet").write_bytes(b"more")
        assert os.access(source, os.W_OK)

    def test_source_outside_the_lake_seals_fine(
        self, service: SnapshotService, tmp_path: Path
    ) -> None:
        source = tmp_path / "elsewhere"
        source.mkdir()
        (source / "borrow.parquet").write_bytes(b"borrow-rates")
        record = service.seal(source, sealed_at=AT)
        assert (record.path / "borrow.parquet").read_bytes() == b"borrow-rates"

    def test_snapshots_root_is_created_on_demand(
        self, lake_root: Path, staged: Path
    ) -> None:
        (lake_root / "snapshots").rmdir()
        service = SnapshotService(lake_root)
        service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        assert (lake_root / "snapshots" / "2026-09-01T00:00:00Z_a3f91c").is_dir()

    def test_default_sealed_at_is_now(
        self, service: SnapshotService, staged: Path
    ) -> None:
        before = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=1)
        record = service.seal(staged)
        after = datetime.now(UTC) + timedelta(seconds=1)
        assert before <= record.sealed_at <= after

    def test_empty_staging_seals_an_empty_snapshot(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        record = service.seal(lake_root / "staging", sealed_at=AT)
        assert record.files == {}
        # An empty snapshot still carries the formula's other terms: the
        # hash folds no file hashes plus the (unasserted) universe plus the
        # schema version — not the bare sha256(b"") of the content term.
        assert record.snapshot_hash == _formula([])
        assert record.path.is_dir()

    def test_missing_source_is_rejected(
        self, service: SnapshotService, tmp_path: Path
    ) -> None:
        with pytest.raises(SnapshotContentError, match="does not exist"):
            service.seal(tmp_path / "absent", sealed_at=AT)

    def test_malformed_supplied_hash_is_rejected(
        self, service: SnapshotService, staged: Path
    ) -> None:
        with pytest.raises(SnapshotNameError, match="64 hexadecimal"):
            service.seal(staged, sealed_at=AT, snapshot_hash="a3f91c")


class TestImmutableDirectory:
    def test_published_files_are_read_only(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        for path in record.path.rglob("*"):
            if path.is_file():
                assert stat.S_IMODE(path.stat().st_mode) == 0o444, path

    def test_published_directories_are_read_only(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        assert stat.S_IMODE(record.path.stat().st_mode) == 0o555
        for path in record.path.rglob("*"):
            if path.is_dir():
                assert stat.S_IMODE(path.stat().st_mode) == 0o555, path

    def test_overwriting_a_sealed_file_fails_with_permission_error(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        sealed = record.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        with pytest.raises(PermissionError):
            sealed.write_bytes(b"tampered")
        assert sealed.read_bytes() == BTC_PART_0

    def test_creating_a_file_inside_a_sealed_tree_fails(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        with pytest.raises(PermissionError):
            (record.path / "MANIFEST.json").write_text("{}")

    def test_the_record_is_frozen(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        with pytest.raises(FrozenInstanceError):
            record.snapshot_hash = "0" * 64  # type: ignore[misc]

    def test_the_record_file_mapping_is_read_only(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        with pytest.raises(TypeError):
            record.files["forged.parquet"] = "0" * 64  # type: ignore[index]


class TestReSealing:
    def test_identical_reseal_is_idempotent(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        second = service.seal(staged, sealed_at=AT)
        assert second.path == first.path
        assert second.snapshot_hash == first.snapshot_hash
        assert second.files == first.files
        assert second.path.stat().st_ino == first.path.stat().st_ino

    def test_conflicting_reseal_is_refused_and_original_survives(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # An explicit hash pins the name: changed content under the same
        # identity is the immutability violation, not a new snapshot.
        first = service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        (staged / "bars" / "extra.parquet").write_bytes(b"late arrival")

        with pytest.raises(SnapshotAlreadySealedError, match="never overwritten"):
            service.seal(staged, sealed_at=AT, snapshot_hash=HASH)

        sealed = first.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        assert sealed.read_bytes() == BTC_PART_0
        assert not (first.path / "bars" / "extra.parquet").exists()

    def test_conflicting_reseal_with_explicit_hash_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        (staged / "bars" / "extra.parquet").write_bytes(b"late arrival")
        with pytest.raises(SnapshotAlreadySealedError):
            service.seal(staged, sealed_at=AT, snapshot_hash=HASH)

    def test_different_content_seals_beside_not_over(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        (staged / "bars" / "extra.parquet").write_bytes(b"late arrival")
        second = service.seal(staged, sealed_at=AT)
        assert second.path != first.path
        assert first.path.is_dir() and second.path.is_dir()


class TestAtomicPublication:
    def test_no_working_directories_are_left_behind(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        service.seal(staged, sealed_at=AT)
        assert _working_dirs(lake_root) == []

    def test_no_working_directories_after_a_refused_seal(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        (staged / "bars" / "extra.parquet").write_bytes(b"late arrival")
        with pytest.raises(SnapshotAlreadySealedError):
            service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        assert _working_dirs(lake_root) == []

    def test_no_working_directories_after_a_failed_seal(
        self, service: SnapshotService, lake_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A copy that dies mid-publication must leave the lake clean: the
        # working tree is removed even though it was never renamed.
        staged = lake_root / "staging"
        (staged / "a.parquet").write_bytes(b"alpha")

        real_copy = shutil.copyfile

        def dying_copy(
            src: "str | os.PathLike[str]", dst: "str | os.PathLike[str]"
        ) -> None:
            real_copy(src, dst)
            raise OSError(28, "No space left on device")

        monkeypatch.setattr("shutil.copyfile", dying_copy)
        with pytest.raises(OSError, match="No space left"):
            service.seal(staged, sealed_at=AT)
        assert _working_dirs(lake_root) == []
        assert list((lake_root / "snapshots").iterdir()) == []


class TestSealedAtInputForms:
    @pytest.mark.parametrize(
        ("sealed_at", "expected_name"),
        [
            (AT, "2026-09-01T00:00:00Z_a3f91c"),
            ("2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z_a3f91c"),
            ("2026-09-01T05:30:00+05:30", "2026-09-01T00:00:00Z_a3f91c"),
            (
                datetime(2026, 8, 31, 19, 0, tzinfo=timezone(timedelta(hours=-5))),
                "2026-09-01T00:00:00Z_a3f91c",
            ),
        ],
    )
    def test_accepted_forms_canonicalise_to_one_name(
        self,
        service: SnapshotService,
        staged: Path,
        sealed_at: object,
        expected_name: str,
    ) -> None:
        record = service.seal(staged, sealed_at=sealed_at, snapshot_hash=HASH)  # type: ignore[arg-type]
        assert record.path.name == expected_name

    def test_naive_sealed_at_is_rejected_before_anything_is_written(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        with pytest.raises(SnapshotNameError, match="UTC offset"):
            service.seal(staged, sealed_at="2026-09-01T00:00:00")
        assert _working_dirs(lake_root) == []
        assert list((lake_root / "snapshots").iterdir()) == []


class TestRecordDerivedIdentity:
    def test_record_name_and_prefix_derive_from_the_contract(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        assert isinstance(record, SealedSnapshot)
        assert record.name == "2026-09-01T00:00:00Z_a3f91c"
        assert record.hash_prefix == "a3f91c"
        assert record.sealed_at == resolve_sealed_at(AT)
