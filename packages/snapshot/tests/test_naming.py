"""The naming contract: ``<sealed_at>_<snapshot_hash[:6]>``, both directions.

These tests pin the exact bytes of a snapshot directory name. The name is
the lake's only persisted address for a snapshot, so a change to any value
asserted here is a change to a public contract — nothing downstream may
drift it casually.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from snapshot import (
    SnapshotNameError,
    format_sealed_at,
    normalize_snapshot_hash,
    parse_snapshot_name,
    resolve_sealed_at,
    snapshot_name,
)

UTC = timezone.utc

HASH_A = "a" * 64
HASH_MIXED = "a3f91c" + "0" * 58


class TestFormatSealedAt:
    def test_canonical_utc_instant(self) -> None:
        at = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
        assert format_sealed_at(at) == "2026-09-01T00:00:00Z"

    def test_offsets_convert_to_utc(self) -> None:
        # 2026-09-01T05:30+05:30 is 2026-09-01T00:00Z — the name is UTC.
        at = datetime(2026, 9, 1, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        assert format_sealed_at(resolve_sealed_at(at)) == "2026-09-01T00:00:00Z"

    def test_microseconds_truncate_not_round(self) -> None:
        at = datetime(2026, 9, 1, 12, 0, 0, 999_999, tzinfo=UTC)
        assert format_sealed_at(resolve_sealed_at(at)) == "2026-09-01T12:00:00Z"


class TestResolveSealedAt:
    def test_none_means_now_in_utc(self) -> None:
        before = datetime.now(UTC).replace(microsecond=0)
        resolved = resolve_sealed_at(None)
        after = datetime.now(UTC)
        assert resolved.tzinfo is not None
        assert before <= resolved <= after

    def test_iso_string_with_offset_converts_to_utc(self) -> None:
        assert resolve_sealed_at("2026-09-01T05:30:00+05:30") == datetime(
            2026, 9, 1, 0, 0, 0, tzinfo=UTC
        )

    def test_naive_string_is_rejected(self) -> None:
        with pytest.raises(SnapshotNameError, match="UTC offset"):
            resolve_sealed_at("2026-09-01T00:00:00")

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(SnapshotNameError, match="UTC offset"):
            resolve_sealed_at(datetime(2026, 9, 1))

    def test_garbage_string_is_rejected(self) -> None:
        with pytest.raises(SnapshotNameError, match="ISO 8601"):
            resolve_sealed_at("not-a-timestamp")

    def test_wrong_type_is_rejected(self) -> None:
        with pytest.raises(SnapshotNameError, match="datetime or ISO 8601"):
            resolve_sealed_at(20260901)  # type: ignore[arg-type]


class TestNormalizeSnapshotHash:
    def test_full_hex_passes_through_lowercased(self) -> None:
        assert normalize_snapshot_hash(HASH_MIXED) == HASH_MIXED
        assert normalize_snapshot_hash(HASH_MIXED.upper()) == HASH_MIXED

    @pytest.mark.parametrize(
        "bad",
        [
            "a3f91c",                       # short hash
            HASH_A[:63],                    # one character short
            HASH_A + "a",                   # one character long
            "g" * 64,                       # not hexadecimal
            "",
        ],
    )
    def test_malformed_hashes_are_rejected(self, bad: str) -> None:
        with pytest.raises(SnapshotNameError, match="64 hexadecimal"):
            normalize_snapshot_hash(bad)

    def test_non_string_is_rejected(self) -> None:
        with pytest.raises(SnapshotNameError, match="hex string"):
            normalize_snapshot_hash(1234)  # type: ignore[arg-type]


class TestSnapshotName:
    def test_name_is_sealed_at_and_six_character_prefix(self) -> None:
        at = datetime(2026, 9, 1, tzinfo=UTC)
        assert snapshot_name(at, HASH_MIXED) == "2026-09-01T00:00:00Z_a3f91c"

    def test_uppercase_hash_normalises_before_prefixing(self) -> None:
        at = datetime(2026, 9, 1, tzinfo=UTC)
        assert (
            snapshot_name(at, "A3F91C" + "0" * 58)
            == "2026-09-01T00:00:00Z_a3f91c"
        )

    def test_bad_hash_cannot_name_a_directory(self) -> None:
        with pytest.raises(SnapshotNameError):
            snapshot_name(datetime(2026, 9, 1, tzinfo=UTC), "short")


class TestParseSnapshotName:
    def test_roundtrip_through_parse(self) -> None:
        at = datetime(2026, 9, 1, 13, 45, 9, tzinfo=UTC)
        name = snapshot_name(at, HASH_MIXED)
        parsed_at, prefix = parse_snapshot_name(name)
        assert parsed_at == at
        assert prefix == "a3f91c"

    def test_parsed_sealed_at_is_timezone_aware_utc(self) -> None:
        _, prefix = parse_snapshot_name("2026-09-01T00:00:00Z_a3f91c")
        assert prefix == "a3f91c"

    @pytest.mark.parametrize(
        "bad",
        [
            "",                                    # empty
            "2026-09-01T00:00:00Z",                # no prefix
            "2026-09-01T00:00:00Z_",               # empty prefix
            "2026-09-01T00:00:00Z_a3f91",          # five characters
            "2026-09-01T00:00:00Z_a3f91cd",        # seven characters
            "2026-09-01T00:00:00Z_A3F91C",         # uppercase
            "2026-09-01T00:00:00_a3f91c",          # missing Z
            "2026-13-01T00:00:00Z_a3f91c",         # impossible month
            "2026-02-30T00:00:00Z_a3f91c",         # impossible day
            "2026-09-01 00:00:00Z_a3f91c",         # space, not T
            "../2026-09-01T00:00:00Z_a3f91c",      # traversal prefix
            "2026-09-01T00:00:00Z_a3f91c/..",      # traversal suffix
            "2026-09-01T00:00:00Z_a3f91c/x",       # extra path segment
            "/2026-09-01T00:00:00Z_a3f91c",        # absolute path
        ],
    )
    def test_malformed_names_are_rejected(self, bad: str) -> None:
        with pytest.raises(SnapshotNameError):
            parse_snapshot_name(bad)

    def test_non_string_is_rejected(self) -> None:
        with pytest.raises(SnapshotNameError, match="string"):
            parse_snapshot_name(None)  # type: ignore[arg-type]
