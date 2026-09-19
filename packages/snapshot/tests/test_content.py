"""Deterministic content addressing over staged trees.

Pins the properties the sealing identity rests on: stable ordering, path
shape, streamed hashing correctness, and the documented semantics of the
``sorted(file_hashes)`` fold (order-independent, path-independent — the
universe/schema terms of the §4.2 formula are the downstream feature's to
add, not this fold's to guess).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from snapshot import SnapshotContentError, content_digest, sha256_file, walk_content

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _digest_of(payloads: list[str]) -> str:
    """The fold computed independently of the implementation under test."""
    return hashlib.sha256(
        "".join(sorted(hashlib.sha256(p.encode()).hexdigest() for p in payloads)).encode()
    ).hexdigest()


class TestWalkContent:
    def test_maps_every_regular_file_by_sorted_posix_path(self, tmp_path: Path) -> None:
        deep = tmp_path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01"
        deep.mkdir(parents=True)
        (deep / "b.parquet").write_bytes(b"two")
        (tmp_path / "a.parquet").write_bytes(b"one")

        files = walk_content(tmp_path)

        assert list(files) == [
            "a.parquet",
            "bars/symbol=BTCUSDT/date=2026-09-01/b.parquet",
        ]
        assert files["a.parquet"] == hashlib.sha256(b"one").hexdigest()

    def test_empty_tree_is_addressable(self, tmp_path: Path) -> None:
        assert walk_content(tmp_path) == {}

    def test_missing_source_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SnapshotContentError, match="does not exist"):
            walk_content(tmp_path / "absent")

    def test_file_source_is_rejected(self, tmp_path: Path) -> None:
        source = tmp_path / "not-a-dir"
        source.write_bytes(b"x")
        with pytest.raises(SnapshotContentError, match="not a directory"):
            walk_content(source)

    def test_symlinks_are_refused_wherever_they_point(self, tmp_path: Path) -> None:
        (tmp_path / "real.parquet").write_bytes(b"bytes")
        (tmp_path / "alias.parquet").symlink_to(tmp_path / "real.parquet")
        with pytest.raises(SnapshotContentError, match="symlink"):
            walk_content(tmp_path)

    def test_symlinked_directories_are_refused(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        (real / "x.parquet").write_bytes(b"bytes")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "link").symlink_to(real, target_is_directory=True)
        with pytest.raises(SnapshotContentError, match="symlink"):
            walk_content(outside)

    def test_large_file_hashes_stream_correctly(self, tmp_path: Path) -> None:
        # Several chunks' worth of data, deterministic bytes, matching a
        # single-shot hashlib computation.
        payload = bytes(range(256)) * (6 * 1024)  # ~1.5 MiB
        big = tmp_path / "big.parquet"
        big.write_bytes(payload)
        assert sha256_file(big) == hashlib.sha256(payload).hexdigest()


class TestContentDigest:
    def test_digest_is_independent_of_input_order(self) -> None:
        forward = [hashlib.sha256(p.encode()).hexdigest() for p in ("a", "b", "c")]
        backward = list(reversed(forward))
        assert content_digest(forward) == content_digest(backward)

    def test_digest_matches_an_independent_fold(self) -> None:
        hashes = [hashlib.sha256(p.encode()).hexdigest() for p in ("x", "y")]
        assert content_digest(hashes) == _digest_of(["x", "y"])

    def test_accepts_the_walk_mapping_directly(self, tmp_path: Path) -> None:
        (tmp_path / "one").write_bytes(b"one")
        (tmp_path / "two").write_bytes(b"two")
        files = walk_content(tmp_path)
        assert content_digest(files) == content_digest(files.values())

    def test_identical_bytes_under_swapped_names_digest_identically(self) -> None:
        # The §4.2 formula folds hashes, not (path, hash) pairs: a name swap
        # keeps the multiset — and therefore the digest.
        left = [hashlib.sha256(b"a").hexdigest(), hashlib.sha256(b"b").hexdigest()]
        right = [hashlib.sha256(b"b").hexdigest(), hashlib.sha256(b"a").hexdigest()]
        assert content_digest(left) == content_digest(right)

    def test_different_bytes_digest_differently(self) -> None:
        one = content_digest([hashlib.sha256(b"a").hexdigest()])
        two = content_digest([hashlib.sha256(b"b").hexdigest()])
        assert one != two

    def test_empty_content_is_the_sha256_of_nothing(self) -> None:
        assert content_digest([]) == EMPTY_SHA256
