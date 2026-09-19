"""The per-snapshot MANIFEST.json: identity, row counts, universe.

These are the acceptance tests for app_spec.xml feature 31 — "System
persists a MANIFEST.json per snapshot recording per-file sha256, row
counts and the universe definition". The §4.2 layout puts the manifest
*inside* the sealed directory, so the record travels with the bytes it
describes; each block below pins one clause of the feature:

* *persists a MANIFEST.json per snapshot* — every seal publishes one,
  frozen read-only, deterministic in its bytes, and excluded from the
  content identity it describes (a manifest cannot hash itself).
* *per-file sha256* — the manifest's entries are exactly the seal's file
  mapping, verified against the staged bytes independently.
* *row counts* — read from each file's own format: the Parquet footer's
  ``num_rows`` (the lake's data format, parsed from its Thrift metadata
  with no dependency), a line count for line-oriented text, and an
  explicit ``null`` — never a guess — where a format carries no rows.
* *the universe definition* — asserted by the caller as a JSON object,
  recorded verbatim, and pinned: re-sealing against a *different*
  definition on an immutable name is refused.

And because a manifest is identity, the suite also pins what the manifest
does to the re-seal contract: an existing directory's manifest carries
its full 64-character hash, closing the six-character-prefix gap the
pre-manifest check documented.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import (
    MANIFEST_NAME,
    MANIFEST_VERSION,
    ManifestFileEntry,
    SnapshotAlreadySealedError,
    SnapshotContentError,
    SnapshotManifest,
    SnapshotManifestError,
    SnapshotNameError,
    SnapshotNotFoundError,
    SnapshotService,
    SnapshotStagingRequestError,
    count_rows,
    manifest_snapshot,
    seal_snapshot,
)

UTC = timezone.utc
AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
HASH = "a3f91c" + "0" * 58

BTC_PART_0 = b"BTCUSDT-2026-09-01-part-0"
BTC_PART_1 = b"BTCUSDT-2026-09-01-part-1"
ETH_PART_0 = b"ETHUSDT-2026-09-01-part-0"

# The universe definition a seal asserts: the mapping form the universe
# member's UniverseConfig produces (dataclasses.asdict), enriched with the
# values a manifest consumer needs — the definition *and* what it selected.
UNIVERSE = {
    "definition": "top_n_by_median_dollar_volume",
    "top_n": 2,
    "window_days": 30,
    "effective_from": "2026-09-01",
    "symbols": ["BTCUSDT", "ETHUSDT"],
}
UNIVERSE_2 = dict(UNIVERSE, top_n=3, symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])


# ---------------------------------------------------------------------------
# Parquet fixtures: a hand-encoded Thrift compact footer
# ---------------------------------------------------------------------------

# The footer reader (snapshot._parquet) decodes the Thrift compact
# protocol; these helpers *encode* just enough of it to stand up a
# well-formed Parquet frame. They live in the test module on purpose: the
# wire format is spelled out here, field by field, independently of the
# reader's implementation, so a fixture documents the format rather than
# echoing the parser. Only the pieces a footer needs are implemented.
_CT_TRUE = 0x01
_CT_FALSE = 0x02
_CT_BYTE = 0x03
_CT_I32 = 0x05
_CT_I64 = 0x06
_CT_DOUBLE = 0x07
_CT_BINARY = 0x08
_CT_LIST = 0x09
_CT_SET = 0x0A
_CT_MAP = 0x0B
_CT_STRUCT = 0x0C
_STOP = b"\x00"


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _zigzag(value: int) -> int:
    return (value << 1) if value >= 0 else (-value << 1) - 1


def _field_header(field_id: int, value_type: int, last_id: int) -> bytes:
    delta = field_id - last_id
    if 0 < delta <= 15:
        return bytes([(delta << 4) | value_type])
    return bytes([value_type]) + _varint(_zigzag(field_id))  # long-form id


def _binary_value(data: bytes) -> bytes:
    return _varint(len(data)) + data


def _bool_field(field_id: int, last_id: int, value: bool) -> bytes:
    return _field_header(field_id, _CT_TRUE if value else _CT_FALSE, last_id)


def _i32_field(field_id: int, last_id: int, value: int) -> bytes:
    return _field_header(field_id, _CT_I32, last_id) + _varint(_zigzag(value))


def _i64_field(field_id: int, last_id: int, value: int) -> bytes:
    return _field_header(field_id, _CT_I64, last_id) + _varint(_zigzag(value))


def _binary_field(field_id: int, last_id: int, data: bytes) -> bytes:
    return _field_header(field_id, _CT_BINARY, last_id) + _binary_value(data)


def _double_field(field_id: int, last_id: int, value: float) -> bytes:
    return _field_header(field_id, _CT_DOUBLE, last_id) + struct.pack("<d", value)


def _collection_header(size: int, element_type: int) -> bytes:
    if size < 15:
        return bytes([(size << 4) | element_type])
    return bytes([0xF0 | element_type]) + _varint(size)


def _parquet_file(num_rows: int, *, row_group_rows: int | None = None) -> bytes:
    """A complete Parquet frame whose footer records ``num_rows``.

    The row-group data is a stand-in (the reader never opens it); the
    footer is a structurally faithful FileMetaData: version, a root
    schema element, num_rows (field 3 — the value under test), a row
    group whose own num_rows agrees, and created_by.
    """
    schema_element = _binary_field(1, 0, b"schema") + _i32_field(5, 1, 1) + _STOP
    column_chunk = _i64_field(2, 0, 4) + _STOP  # file_offset past the magic
    rows_here = num_rows if row_group_rows is None else row_group_rows
    row_group = (
        _field_header(1, _CT_LIST, 0)
        + _collection_header(1, _CT_STRUCT)
        + column_chunk
        + _i64_field(2, 1, 3)  # total_byte_size
        + _i64_field(3, 2, rows_here)
        + _STOP
    )
    metadata = (
        _i32_field(1, 0, 1)  # version
        + _field_header(2, _CT_LIST, 1)
        + _collection_header(1, _CT_STRUCT)
        + schema_element
        + _i64_field(3, 2, num_rows)  # FileMetaData.num_rows
        + _i32_field(4, 3, 1)  # num_row_groups
        + _field_header(5, _CT_LIST, 4)
        + _collection_header(1, _CT_STRUCT)
        + row_group
        + _binary_field(7, 5, b"nullius test fixture")
        + _STOP
    )
    data = b"\x01\x02\x03"  # stand-in column bytes
    return b"PAR1" + data + metadata + struct.pack("<I", len(metadata)) + b"PAR1"


def _write_parquet(directory: Path, name: str, num_rows: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(_parquet_file(num_rows))
    return path


def _reseat_writable(directory: Path) -> None:
    """Grant write bits back to a sealed directory (the owner's crack)."""
    os.chmod(directory, 0o755)


def _reseal_frozen(directory: Path) -> None:
    """Put a sealed directory back under the 0555 contract."""
    os.chmod(directory, 0o555)


# ---------------------------------------------------------------------------
# The manifest is persisted, per snapshot
# ---------------------------------------------------------------------------


class TestManifestPersisted:
    def test_every_seal_publishes_a_manifest(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        manifest_file = record.path / MANIFEST_NAME
        assert manifest_file.is_file()
        payload = json.loads(manifest_file.read_text())
        assert payload["manifest_version"] == MANIFEST_VERSION == 1
        assert payload["sealed_at"] == "2026-09-01T00:00:00Z"
        assert payload["snapshot_hash"] == record.snapshot_hash

    def test_the_manifest_is_frozen_read_only(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        mode = stat.S_IMODE((record.path / MANIFEST_NAME).stat().st_mode)
        assert mode == 0o444

    def test_the_manifest_records_per_file_sha256(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        payload = json.loads((record.path / MANIFEST_NAME).read_text())
        # The entries are the seal's file mapping, checked against the
        # staged bytes independently of the seal's own computation.
        assert payload["files"] == {
            "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet": {
                "sha256": hashlib.sha256(BTC_PART_0).hexdigest(),
                "row_count": 1,
            },
            "bars/symbol=BTCUSDT/date=2026-09-01/part-1.parquet": {
                "sha256": hashlib.sha256(BTC_PART_1).hexdigest(),
                "row_count": 1,
            },
            "bars/symbol=ETHUSDT/date=2026-09-01/part-0.parquet": {
                "sha256": hashlib.sha256(ETH_PART_0).hexdigest(),
                "row_count": 1,
            },
        }
        assert payload["totals"] == {"files": 3, "rows": 3}

    def test_the_manifest_is_not_content(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The manifest describes the content and therefore never appears
        # in the content identity: not in the record's file mapping, and
        # not in the digest the snapshot is named by.
        record = service.seal(staged, sealed_at=AT)
        assert MANIFEST_NAME not in record.files
        import snapshot as snapshot_package

        assert record.snapshot_hash == snapshot_package.content_digest(
            {
                path: hashlib.sha256(data).hexdigest()
                for path, data in [
                    ("a", BTC_PART_0),
                    ("b", BTC_PART_1),
                    ("c", ETH_PART_0),
                ]
            }
        )

    def test_the_manifest_records_the_universe_definition(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT, universe=UNIVERSE)
        payload = json.loads((record.path / MANIFEST_NAME).read_text())
        assert payload["universe"] == UNIVERSE

    def test_no_asserted_universe_is_recorded_as_null_not_empty(
        self, service: SnapshotService, staged: Path
    ) -> None:
        service.seal(staged, sealed_at=AT)
        [name] = service.sealed()
        payload = json.loads(
            (service.snapshots_root / name / MANIFEST_NAME).read_text()
        )
        assert payload["universe"] is None  # distinct from {} — an asserted empty definition

    def test_manifest_bytes_are_deterministic(
        self, staged: Path, tmp_path: Path
    ) -> None:
        # Same content, instant, hash and universe: byte-identical
        # manifests in two different lakes, so "re-seal and compare" is a
        # valid operation and the manifest's identity is its bytes.
        from snapshot import SnapshotService as Service

        first = Service(tmp_path / "lake-a").seal(
            staged, sealed_at=AT, universe=UNIVERSE
        )
        second = Service(tmp_path / "lake-b").seal(
            staged, sealed_at=AT, universe=UNIVERSE
        )
        assert first.snapshot_hash == second.snapshot_hash
        assert (first.path / MANIFEST_NAME).read_bytes() == (
            second.path / MANIFEST_NAME
        ).read_bytes()

    def test_an_empty_snapshot_carries_an_empty_manifest(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        record = service.seal(lake_root / "staging", sealed_at=AT)
        payload = json.loads((record.path / MANIFEST_NAME).read_text())
        assert payload["files"] == {}
        assert payload["totals"] == {"files": 0, "rows": 0}
        manifest = service.read_manifest(record.name)
        assert manifest.file_count == 0
        assert manifest.total_rows == 0

    def test_the_supplied_full_hash_is_the_persisted_one(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        payload = json.loads((record.path / MANIFEST_NAME).read_text())
        assert payload["snapshot_hash"] == HASH


# ---------------------------------------------------------------------------
# Row counts, per file, in the file's own format
# ---------------------------------------------------------------------------


class TestRowCountsFromParquetMetadata:
    def test_a_parquet_file_counts_its_metadata_rows(
        self, tmp_path: Path
    ) -> None:
        path = _write_parquet(tmp_path, "bars.parquet", 5)
        # The frame's data bytes contain no newline: a line count would
        # say 1. Only the footer's num_rows can say 5.
        assert count_rows(path) == 5

    def test_zero_row_parquet_counts_zero(self, tmp_path: Path) -> None:
        assert count_rows(_write_parquet(tmp_path, "empty.parquet", 0)) == 0

    def test_large_row_counts_use_multibyte_varints(
        self, tmp_path: Path
    ) -> None:
        rows = 1 << 33  # zigzag encoding spans six varint bytes
        assert count_rows(_write_parquet(tmp_path, "big.parquet", rows)) == rows

    def test_the_seal_records_parquet_row_counts(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        _write_parquet(
            lake_root / "staging" / "bars" / "symbol=BTCUSDT" / "date=2026-09-01",
            "part-0.parquet",
            42,
        )
        record = service.seal(service.staging_root, sealed_at=AT)
        manifest = service.read_manifest(record.name)
        entry = manifest.files["bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet"]
        assert entry.row_count == 42
        assert manifest.total_rows == 42

    def test_exotic_thrift_fields_do_not_derail_the_read(
        self, tmp_path: Path
    ) -> None:
        # A footer exercising every compact-protocol shape the reader
        # must skip: bools (field and element forms), a map, a set, a
        # double, a nested struct, a long-form field id, and a list long
        # enough to need the extended size header.
        footer = (
            _bool_field(1, 0, True)
            + _field_header(2, _CT_LIST, 1)
            + _collection_header(3, _CT_TRUE)
            + bytes([_CT_TRUE, _CT_FALSE, _CT_TRUE])
            + _i64_field(3, 2, 7)  # num_rows — the target, mid-struct
            + _field_header(4, _CT_MAP, 3)
            + _varint(2)
            + bytes([(_CT_BINARY << 4) | _CT_I32])
            + _binary_value(b"a")
            + _varint(_zigzag(1))
            + _binary_value(b"b")
            + _varint(_zigzag(2))
            + _field_header(5, _CT_SET, 4)
            + _collection_header(2, _CT_I32)
            + _varint(_zigzag(10))
            + _varint(_zigzag(20))
            + _double_field(6, 5, 3.5)
            + _field_header(7, _CT_STRUCT, 6)
            + _i32_field(1, 0, 9)
            + _STOP
            + _binary_field(25, 7, b"far away")  # delta > 15: long-form id
            + _field_header(26, _CT_LIST, 25)
            + bytes([0xF0 | _CT_I32])
            + _varint(20)
            + b"".join(_varint(_zigzag(i)) for i in range(20))
            + _STOP
        )
        path = tmp_path / "exotic.parquet"
        path.write_bytes(
            b"PAR1"
            + b"\x00"
            + footer
            + struct.pack("<I", len(footer))
            + b"PAR1"
        )
        assert count_rows(path) == 7

    def test_a_negative_num_rows_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "negative.parquet"
        path.write_bytes(_parquet_file(-5))
        with pytest.raises(SnapshotContentError, match="negative"):
            count_rows(path)

    def test_a_corrupt_footer_is_refused_loudly(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.parquet"
        garbage = b"\x7f" * 8  # type nibble 0xF is no compact-protocol type
        path.write_bytes(
            b"PAR1" + b"\x00" + garbage + struct.pack("<I", len(garbage)) + b"PAR1"
        )
        with pytest.raises(SnapshotContentError, match="malformed"):
            count_rows(path)

    def test_a_footer_without_num_rows_is_refused(self, tmp_path: Path) -> None:
        footer = _i32_field(1, 0, 1) + _STOP  # version only
        path = tmp_path / "norows.parquet"
        path.write_bytes(
            b"PAR1" + b"\x00" + footer + struct.pack("<I", len(footer)) + b"PAR1"
        )
        with pytest.raises(SnapshotContentError, match="no num_rows"):
            count_rows(path)

    def test_a_footer_length_that_overruns_the_file_is_refused(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "overrun.parquet"
        footer = _i64_field(3, 0, 1) + _STOP
        body = footer + struct.pack("<I", 1_000_000_000) + b"PAR1"
        path.write_bytes(b"PAR1" + b"\x00" + body)
        with pytest.raises(SnapshotContentError, match="does not fit"):
            count_rows(path)

    def test_a_truncated_varint_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "half.parquet"
        footer = b"\x36\x80\x80"  # i64 field header, varint that never ends
        path.write_bytes(
            b"PAR1" + b"\x00" + footer + struct.pack("<I", len(footer)) + b"PAR1"
        )
        with pytest.raises(SnapshotContentError, match="malformed"):
            count_rows(path)

    def test_a_half_written_frame_is_not_parquet_yet(
        self, tmp_path: Path
    ) -> None:
        # Leading magic, no trailing magic: a worker was mid-append when
        # the seal walked past. Not a Parquet frame, not an error — the
        # bytes are ASCII here, so the line counter answers instead.
        path = tmp_path / "midappend.parquet"
        path.write_bytes(b"PAR1 still streaming")
        assert count_rows(path) == 1


class TestRowCountsFromText:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (b"", 0),
            (b"single line", 1),
            (b"two\nlines", 2),
            (b"trailing\nnewline\n", 2),
            (b"header,close\nBTCUSDT,1\nETHUSDT,2\n", 3),
            (b"\n\n\n", 3),
        ],
    )
    def test_line_oriented_text_counts_lines(
        self, tmp_path: Path, data: bytes, expected: int
    ) -> None:
        path = tmp_path / "rows.csv"
        path.write_bytes(data)
        assert count_rows(path) == expected

    def test_a_multibyte_character_split_across_the_read_buffer(
        self, tmp_path: Path
    ) -> None:
        # "心" is three bytes; 2**20 is not divisible by three, so the
        # 1 MiB read boundary lands mid-character. The incremental
        # decoder must decode it, not discard or miscount it.
        path = tmp_path / "wide.txt"
        path.write_bytes("心".encode("utf-8") * 400_000)
        assert count_rows(path) == 1  # one line, no trailing newline

    def test_opaque_binary_is_recorded_as_unknown(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(bytes([0xFF, 0xFE, 0x00, 0x81]))
        with pytest.raises(UnicodeDecodeError):
            path.read_text(encoding="utf-8")  # the premise: not text
        assert count_rows(path) is None

    def test_unknown_rows_make_the_total_null_not_a_partial_sum(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        staging = lake_root / "staging"
        (staging / "bars").mkdir(parents=True)
        _write_parquet(staging / "bars", "day.parquet", 5)
        (staging / "bars" / "notes.csv").write_bytes(b"a\nb\nc\n")
        (staging / "bars" / "blob.bin").write_bytes(bytes([0xFF, 0x00]))
        record = service.seal(staging, sealed_at=AT)
        manifest = service.read_manifest(record.name)
        assert manifest.files["bars/day.parquet"].row_count == 5
        assert manifest.files["bars/notes.csv"].row_count == 3
        assert manifest.files["bars/blob.bin"].row_count is None
        # A total over fiction is not a total.
        assert manifest.total_rows is None
        payload = json.loads((record.path / MANIFEST_NAME).read_text())
        assert payload["totals"] == {"files": 3, "rows": None}
        assert payload["files"]["bars/blob.bin"]["row_count"] is None


# ---------------------------------------------------------------------------
# The universe definition
# ---------------------------------------------------------------------------


class TestUniverseDefinition:
    def test_the_universe_member_config_dict_form_is_accepted(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The intended producer: the universe member's config, as a dict.
        # The snapshot package never imports the universe member (the
        # manifest takes any JSON object by design) — this test does, to
        # pin that the two members' shapes actually meet.
        import sys

        universe_src = (
            Path(__file__).resolve().parents[2] / "universe" / "src"
        )
        if str(universe_src) not in sys.path:
            sys.path.insert(0, str(universe_src))
        from universe import UniverseConfig

        definition = asdict(UniverseConfig(top_n=2, window_days=30))
        record = service.seal(staged, sealed_at=AT, universe=definition)
        manifest = service.read_manifest(record.name)
        assert manifest.universe == definition

    def test_a_non_mapping_universe_is_refused_before_anything_is_written(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        with pytest.raises(SnapshotManifestError, match="JSON object"):
            service.seal(staged, sealed_at=AT, universe=["BTCUSDT"])  # type: ignore[arg-type]
        assert service.sealed() == []
        assert not (lake_root / "snapshots" / ".sealing-x").exists()

    def test_an_unserialisable_universe_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        with pytest.raises(SnapshotManifestError, match="JSON-serializable"):
            service.seal(
                staged, sealed_at=AT, universe={"symbols": {"BTCUSDT"}}  # type: ignore[dict-item]
            )
        assert service.sealed() == []

    def test_the_empty_definition_is_not_the_missing_definition(
        self, service: SnapshotService, staged: Path
    ) -> None:
        sealed_empty = service.seal(staged, sealed_at=AT, universe={})
        manifest = service.read_manifest(sealed_empty.name)
        assert manifest.universe == {}  # asserted: an empty definition
        assert manifest.universe is not None  # …which is not "none asserted"


# ---------------------------------------------------------------------------
# Reading the manifest back
# ---------------------------------------------------------------------------


class TestReadManifest:
    def test_read_manifest_returns_the_persisted_record(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT, universe=UNIVERSE)
        manifest = service.read_manifest(record.name)
        assert isinstance(manifest, SnapshotManifest)
        assert manifest.manifest_version == MANIFEST_VERSION
        assert manifest.name == record.name
        assert manifest.snapshot_hash == record.snapshot_hash
        assert manifest.sealed_at == AT
        assert manifest.universe == UNIVERSE
        assert manifest.file_count == 3
        assert manifest.total_rows == 3
        entry = manifest.files["bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet"]
        assert isinstance(entry, ManifestFileEntry)
        assert entry.sha256 == hashlib.sha256(BTC_PART_0).hexdigest()

    def test_the_manifest_round_trips_through_its_own_bytes(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT, universe=UNIVERSE)
        original = service.read_manifest(record.name)
        rebuilt = SnapshotManifest.from_json_bytes(original.to_json_bytes())
        assert rebuilt == original

    def test_a_staging_request_is_refused_as_a_staging_request(
        self, service: SnapshotService
    ) -> None:
        with pytest.raises(SnapshotStagingRequestError, match="staging area"):
            service.read_manifest("staging")

    def test_a_malformed_name_is_refused_by_the_strict_parser(
        self, service: SnapshotService
    ) -> None:
        with pytest.raises(SnapshotNameError):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91")

    def test_a_well_formed_miss_raises_not_found(
        self, service: SnapshotService
    ) -> None:
        with pytest.raises(SnapshotNotFoundError):
            service.read_manifest("2026-09-01T00:00:00Z_000000")

    def test_a_snapshot_without_a_manifest_says_so(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        (lake_root / "snapshots" / "2026-09-01T00:00:00Z_a3f91c").mkdir()
        with pytest.raises(SnapshotManifestError, match="carries no"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")

    def _hand_sealed_manifest(
        self, lake_root: Path, name: str, manifest: SnapshotManifest
    ) -> str:
        # Writes a manifest into a directory the *test* names, so the
        # manifest and the name can be made to disagree on purpose.
        directory = lake_root / "snapshots" / name
        directory.mkdir(parents=True)
        (directory / MANIFEST_NAME).write_bytes(manifest.to_json_bytes())
        return name

    def test_a_manifest_hash_that_contradicts_the_directory_is_refused(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        manifest = SnapshotManifest(
            manifest_version=MANIFEST_VERSION,
            snapshot_hash="b7d2e4" + "0" * 58,  # not the name's prefix
            sealed_at=AT,
            universe=None,
            files={},
            total_rows=0,
        )
        name = self._hand_sealed_manifest(
            lake_root, "2026-09-01T00:00:00Z_a3f91c", manifest
        )
        with pytest.raises(SnapshotManifestError, match="prefix does not match"):
            service.read_manifest(name)

    def test_a_manifest_sealed_at_that_contradicts_the_directory_is_refused(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        manifest = SnapshotManifest(
            manifest_version=MANIFEST_VERSION,
            snapshot_hash=HASH,
            sealed_at=datetime(2026, 9, 2, tzinfo=UTC),  # the name says the 1st
            universe=None,
            files={},
            total_rows=0,
        )
        name = self._hand_sealed_manifest(
            lake_root, "2026-09-01T00:00:00Z_a3f91c", manifest
        )
        with pytest.raises(SnapshotManifestError, match="sealed_at"):
            service.read_manifest(name)

    def test_corrupt_json_is_refused(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        directory = lake_root / "snapshots" / "2026-09-01T00:00:00Z_a3f91c"
        directory.mkdir(parents=True)
        (directory / MANIFEST_NAME).write_bytes(b"this is not json")
        with pytest.raises(SnapshotManifestError, match="not valid JSON"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")


class TestManifestParsingIsStrict:
    """A manifest the reader cannot fully believe is refused in full."""

    @staticmethod
    def _payload(service: SnapshotService, staged: Path) -> dict:
        record = service.seal(staged, sealed_at=AT)
        return json.loads((record.path / MANIFEST_NAME).read_text())

    @staticmethod
    def _install(lake_root: Path, name: str, payload: object) -> None:
        directory = lake_root / "snapshots" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / MANIFEST_NAME).write_text(
            payload if isinstance(payload, str) else json.dumps(payload)
        )

    def test_an_unknown_manifest_version_is_refused(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        payload = self._payload(service, staged)
        payload["manifest_version"] = 2
        self._install(lake_root, "2026-09-01T00:00:00Z_a3f91c", payload)
        with pytest.raises(SnapshotManifestError, match="version"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")

    def test_a_missing_key_is_refused(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        payload = self._payload(service, staged)
        del payload["totals"]
        self._install(lake_root, "2026-09-01T00:00:00Z_a3f91c", payload)
        with pytest.raises(SnapshotManifestError, match="key set"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")

    def test_an_extra_key_is_refused(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        payload = self._payload(service, staged)
        payload["surprise"] = True
        self._install(lake_root, "2026-09-01T00:00:00Z_a3f91c", payload)
        with pytest.raises(SnapshotManifestError, match="key set"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")

    def test_a_wrongly_typed_row_count_is_refused(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        payload = self._payload(service, staged)
        entry = next(iter(payload["files"].values()))
        entry["row_count"] = "3"
        self._install(lake_root, "2026-09-01T00:00:00Z_a3f91c", payload)
        with pytest.raises(SnapshotManifestError, match="row count"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")

    def test_totals_that_disagree_with_the_entries_are_refused(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        payload = self._payload(service, staged)
        payload["totals"]["rows"] = 99
        self._install(lake_root, "2026-09-01T00:00:00Z_a3f91c", payload)
        with pytest.raises(SnapshotManifestError, match="disagrees with itself"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")

    def test_a_bad_snapshot_hash_is_refused(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        payload = self._payload(service, staged)
        payload["snapshot_hash"] = "a3f91c"  # a prefix, not a digest
        self._install(lake_root, "2026-09-01T00:00:00Z_a3f91c", payload)
        with pytest.raises(SnapshotManifestError, match="64-hex"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")

    def test_an_entry_with_extra_fields_is_refused(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        payload = self._payload(service, staged)
        entry = next(iter(payload["files"].values()))
        entry["bytes"] = 4096
        self._install(lake_root, "2026-09-01T00:00:00Z_a3f91c", payload)
        with pytest.raises(SnapshotManifestError, match="exactly"):
            service.read_manifest("2026-09-01T00:00:00Z_a3f91c")


# ---------------------------------------------------------------------------
# What the manifest does to the re-seal contract
# ---------------------------------------------------------------------------


class TestManifestPinsIdentity:
    def test_the_full_hash_on_disk_closes_the_prefix_gap(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # Two full hashes sharing the six-character prefix the directory
        # name carries: before manifests, the second seal rode the first
        # directory's prefix. The manifest pins the full identity, so the
        # same bytes cannot be re-sealed under a different one.
        service.seal(staged, sealed_at=AT, snapshot_hash=HASH)
        same_prefix_different_digest = "a3f91c" + "9" * 58
        with pytest.raises(
            SnapshotAlreadySealedError, match="already sealed under full hash"
        ):
            service.seal(
                staged, sealed_at=AT, snapshot_hash=same_prefix_different_digest
            )

    def test_an_idempotent_reseal_returns_the_persisted_truth(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT, universe=UNIVERSE)
        # The retry asserts no universe: the seal already happened, and
        # the manifest on disk is what stands.
        second = service.seal(staged, sealed_at=AT)
        assert second.path == first.path
        assert service.read_manifest(second.name).universe == UNIVERSE

    def test_a_reseal_asserting_a_different_universe_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        service.seal(staged, sealed_at=AT, universe=UNIVERSE)
        with pytest.raises(
            SnapshotAlreadySealedError, match="different universe definition"
        ):
            service.seal(staged, sealed_at=AT, universe=UNIVERSE_2)

    def test_a_reseal_with_the_same_universe_is_idempotent(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT, universe=UNIVERSE)
        second = service.seal(staged, sealed_at=AT, universe=dict(UNIVERSE))
        assert second.path == first.path
        assert second.path.stat().st_ino == first.path.stat().st_ino

    def test_an_unreadable_manifest_blocks_the_reseal(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        manifest_file = record.path / MANIFEST_NAME
        _reseat_writable(record.path)
        os.chmod(manifest_file, 0o644)  # the documented owner crack, both bits
        manifest_file.write_bytes(b"corrupted")
        os.chmod(manifest_file, 0o444)
        _reseal_frozen(record.path)
        with pytest.raises(
            SnapshotAlreadySealedError, match="manifest cannot be read"
        ):
            service.seal(staged, sealed_at=AT)
        assert service.sealed() == [record.name]  # nothing new, nothing gone

    def test_a_manifest_free_directory_falls_back_to_bytes(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # A snapshot sealed before manifests existed (or stripped of one)
        # still decides re-seals by content bytes, the old contract.
        record = service.seal(staged, sealed_at=AT)
        _reseat_writable(record.path)
        (record.path / MANIFEST_NAME).unlink()
        _reseal_frozen(record.path)

        replay = service.seal(staged, sealed_at=AT)
        assert replay.path == record.path

        (staged / "bars" / "extra.parquet").write_bytes(b"late arrival")
        with pytest.raises(SnapshotAlreadySealedError, match="different content"):
            service.seal(staged, sealed_at=AT, snapshot_hash=record.snapshot_hash)


# ---------------------------------------------------------------------------
# Staging cannot smuggle a manifest in
# ---------------------------------------------------------------------------


class TestStagedManifestIsRefused:
    def test_staging_carrying_a_manifest_is_refused(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        (staged / MANIFEST_NAME).write_text("{}")
        with pytest.raises(SnapshotContentError, match="writes the snapshot's manifest"):
            service.seal(staged, sealed_at=AT)
        assert service.sealed() == []
        assert [
            entry.name
            for entry in (lake_root / "snapshots").iterdir()
            if entry.name.startswith(".sealing-")
        ] == []

    def test_a_nested_manifest_is_staged_content_and_seals_fine(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # Only the *root* manifest is the derived record; one that is
        # staged content like any other file seals and is hashed as such.
        nested = staged / "bars" / MANIFEST_NAME
        nested.write_text('{"note": "staged, not derived"}')
        record = service.seal(staged, sealed_at=AT)
        assert f"bars/{MANIFEST_NAME}" in record.files
        # The published manifest describes it like any other file.
        manifest = service.read_manifest(record.name)
        assert manifest.files[f"bars/{MANIFEST_NAME}"].sha256 == hashlib.sha256(
            nested.read_bytes()
        ).hexdigest()


# ---------------------------------------------------------------------------
# The conveniences
# ---------------------------------------------------------------------------


class TestConveniences:
    def test_seal_snapshot_records_the_universe(
        self, staged: Path, tmp_path: Path
    ) -> None:
        record = seal_snapshot(
            staged, sealed_at=AT, universe=UNIVERSE, lake_root=tmp_path / "lake"
        )
        assert record.manifest_path.is_file()
        payload = json.loads(record.manifest_path.read_text())
        assert payload["universe"] == UNIVERSE

    def test_manifest_snapshot_reads_one_back(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT, universe=UNIVERSE)
        manifest = manifest_snapshot(record.name, lake_root=lake_root)
        assert manifest.universe == UNIVERSE
        assert manifest.file_count == 3
