"""Feature 38 — a lake extension is sealed under a new snapshot_hash.

These are the acceptance tests for app_spec.xml feature 38 — *"System
assigns a new snapshot_hash when the lake is extended, which invalidates
previously cached scores rather than silently reusing them"* — the
invalidation trigger docs/nullius-tech-architecture.md §15 states as its
failure-mode row *"Snapshot extended → new snapshot_hash … Tree structure
survives; scores do not"*. Each clause of the sentence is pinned below:

* *assigns a new snapshot_hash when the lake is extended* — every axis the
  §4.2 formula folds is an extension axis: a new partition appended, more
  bytes inside an existing staged file, a file whose bytes duplicate
  another's (the fold is a multiset), a universe that turned over a month.
  Each moves the seal onto a hash no other snapshot in this lake carries,
  and that hash is the formula over the new content, independently
  spelled here so the test fails when the implementation and the spec
  disagree rather than when they agree with each other.
* *invalidates previously cached scores* — scores are keyed by
  ``snapshot_hash`` (§4.4, feature 48), so the new identity is a
  guaranteed cache miss: an entry cached under the old hash is not
  returned for the new one, and the old snapshot keeps answering under
  its old hash with its old bytes. Invalidation happens by re-keying,
  never by mutating what the old identity names — that is why it cannot
  be silent.
* *rather than silently reusing them* — the one reachable path to reuse
  was a caller-supplied ``snapshot_hash=`` pinning an already-assigned
  hash over extended content under a fresh name; that seal is refused
  (:class:`~snapshot.SnapshotHashReusedError`) with the lake left exactly
  as it was. The same hash over the *same* bytes stays legal at any
  instant — that is the idempotent re-assertion a schedule performs on a
  quiet lake, not a reuse.
* *when the lake is extended* — the trigger is the lake, not the
  calendar: re-sealing unchanged staging re-asserts one identity, and a
  score cached under it stays addressed. Invalidation tracks content.

The score cache in these tests is a plain dict keyed by snapshot hash —
§4.4's key, reduced to the addressing that matters here — because the
invalidation contract being pinned is the snapshot side of it: that the
identity genuinely changes when the content does, and that an assigned
identity is never re-published over other bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

import pytest
from snapshot import (
    SCHEMA_VERSION,
    SnapshotAlreadySealedError,
    SnapshotHashReusedError,
    SnapshotService,
)

UTC = timezone.utc
AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
AT_LATER = datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC)

BTC_PART_0 = b"BTCUSDT-2026-09-01-part-0"
BTC_PART_1 = b"BTCUSDT-2026-09-01-part-1"
ETH_PART_0 = b"ETHUSDT-2026-09-01-part-0"
SOL_PART_0 = b"SOLUSDT-2026-09-02-part-0"

# One universe month and the next: the same lake, the world turned over.
UNIVERSE_AUGUST = {"top_n": 2, "effective_from": "2026-08-01"}
UNIVERSE_SEPTEMBER = {"top_n": 3, "effective_from": "2026-09-01"}


def _hashes(*payloads: bytes) -> list[str]:
    return [hashlib.sha256(payload).hexdigest() for payload in payloads]


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


def _extend_with_a_new_partition(staged: Path) -> None:
    """Append one new symbol/date partition — §4.1's append-only growth."""
    partition = staged / "bars" / "symbol=SOLUSDT" / "date=2026-09-02"
    partition.mkdir(parents=True)
    (partition / "part-0.parquet").write_bytes(SOL_PART_0)


def _working_dirs(lake_root: Path) -> list[str]:
    root = lake_root / "snapshots"
    if not root.is_dir():
        return []
    return [e.name for e in root.iterdir() if e.name.startswith(".sealing-")]


# ---------------------------------------------------------------------------
# Extension assigns a new snapshot_hash
# ---------------------------------------------------------------------------


class TestExtensionAssignsANewHash:
    def test_an_appended_partition_seals_under_a_new_hash(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        assert second.snapshot_hash != first.snapshot_hash
        assert second.path != first.path
        assert first.path.is_dir() and second.path.is_dir()
        # Each manifest carries its own identity: the lake answers the new
        # bytes with the new hash only, never the old one.
        assert service.read_manifest(first.name).snapshot_hash == (
            first.snapshot_hash
        )
        assert service.read_manifest(second.name).snapshot_hash == (
            second.snapshot_hash
        )

    def test_the_new_hash_is_the_formula_over_the_extended_content(
        self, service: SnapshotService, staged: Path
    ) -> None:
        service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        expected = _formula(_hashes(BTC_PART_0, BTC_PART_1, ETH_PART_0, SOL_PART_0))
        assert second.snapshot_hash == expected

    def test_more_bytes_in_an_existing_file_re_keys(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        part = staged / "bars" / "symbol=ETHUSDT" / "date=2026-09-01" / "part-0.parquet"
        part.write_bytes(ETH_PART_0 + b"-appended-row")

        second = service.seal(staged, sealed_at=AT_LATER)
        assert second.snapshot_hash != first.snapshot_hash

    def test_a_file_duplicating_anothers_bytes_re_keys(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The fold is over a multiset of hashes: adding a file whose bytes
        # are an exact copy of an existing one still grows the lake, and a
        # grown lake is a new identity — identical bytes at two paths and
        # one path are different states of the world.
        first = service.seal(staged, sealed_at=AT)
        (staged / "bars" / "symbol=ETHUSDT" / "date=2026-09-01" / "part-1.parquet").write_bytes(
            ETH_PART_0
        )

        second = service.seal(staged, sealed_at=AT_LATER)
        assert second.snapshot_hash != first.snapshot_hash

    def test_a_universe_turnover_re_keys_the_same_bytes(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The lake's *definition* extends too: the month turns over, the
        # universe changes, and the same bars sealed against the new world
        # are a new snapshot whose scores must be recomputed.
        august = service.seal(staged, sealed_at=AT, universe=UNIVERSE_AUGUST)
        september = service.seal(
            staged, sealed_at=AT_LATER, universe=UNIVERSE_SEPTEMBER
        )
        assert september.snapshot_hash != august.snapshot_hash
        assert september.files == august.files  # bytes unchanged, identity moved

    def test_an_append_only_extension_keeps_the_old_paths_hashing_identically(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # §15: "Tree structure survives; scores do not." An append-only
        # extension leaves every previously sealed path at its previously
        # sealed hash inside the new identity — the old bytes are still
        # there, still addressable, still exactly what the old snapshot
        # says they are.
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        assert set(first.files) < set(second.files)
        for path, file_hash in first.files.items():
            assert second.files[path] == file_hash


# ---------------------------------------------------------------------------
# Cached scores are invalidated
# ---------------------------------------------------------------------------


class TestCachedScoresAreInvalidated:
    def test_a_score_cached_under_the_old_hash_misses_under_the_new(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        # §4.4's addressing reduced to the component that matters here: a
        # score is cached under the snapshot_hash it was computed over.
        cached_scores = {first.snapshot_hash: {"BTCUSDT": 0.42}}

        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        # The miss is the invalidation: nothing cached under the old hash
        # can be returned for the extended lake's identity, so the score
        # is recomputed rather than handed back.
        assert second.snapshot_hash not in cached_scores
        # …and the entry that does exist still names the old identity —
        # it was invalidated for the new lake, not deleted for the old one.
        assert first.snapshot_hash in cached_scores

    def test_the_old_identity_keeps_naming_the_old_bytes(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        old = service.read_manifest(first.name)
        assert old.snapshot_hash == first.snapshot_hash
        assert set(old.files) == set(first.files)
        new = service.read_manifest(second.name)
        assert new.snapshot_hash == second.snapshot_hash
        assert "bars/symbol=SOLUSDT/date=2026-09-02/part-0.parquet" in new.files
        assert "bars/symbol=SOLUSDT/date=2026-09-02/part-0.parquet" not in old.files

    def test_both_snapshots_answer_after_the_extension(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        assert service.sealed() == sorted([first.name, second.name])
        # The old snapshot's bytes did not move or change under it.
        sealed_btc = (
            first.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        )
        assert sealed_btc.read_bytes() == BTC_PART_0


# ---------------------------------------------------------------------------
# Hash reuse is refused, not silent
# ---------------------------------------------------------------------------


class TestHashReuseIsRefused:
    def test_an_assigned_hash_over_extended_content_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The reachable path to silent reuse: a schedule replaying a stale
        # decision — pinning the hash the first seal was assigned — over a
        # lake that has since grown, under a fresh name so no directory
        # collision ever fires. Publishing it would make every score
        # cached under that hash stand for bytes it was never computed
        # over; the seal refuses instead.
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)

        with pytest.raises(SnapshotHashReusedError) as refusal:
            service.seal(staged, sealed_at=AT_LATER, snapshot_hash=first.snapshot_hash)

        message = str(refusal.value)
        assert first.snapshot_hash in message
        assert first.name in message
        assert "new snapshot_hash" in message

    def test_the_refusal_is_catchable_as_an_immutability_violation(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # One vocabulary for one contract: a reassigned identity is the
        # immutability refusal one granularity up from a taken name.
        assert issubclass(SnapshotHashReusedError, SnapshotAlreadySealedError)
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        with pytest.raises(SnapshotAlreadySealedError, match="already assigned"):
            service.seal(staged, sealed_at=AT_LATER, snapshot_hash=first.snapshot_hash)

    def test_the_refusal_leaves_the_lake_untouched(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)

        with pytest.raises(SnapshotHashReusedError):
            service.seal(staged, sealed_at=AT_LATER, snapshot_hash=first.snapshot_hash)

        assert service.sealed() == [first.name]
        assert _working_dirs(lake_root) == []

    def test_a_pinned_hash_meets_the_same_refusal(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The first seal pinned its identity explicitly; the replay pins
        # it again over grown content. However the assignment was made, it
        # stands.
        pinned = "b7d2e4" + "0" * 58
        service.seal(staged, sealed_at=AT, snapshot_hash=pinned)
        _extend_with_a_new_partition(staged)

        with pytest.raises(SnapshotHashReusedError):
            service.seal(staged, sealed_at=AT_LATER, snapshot_hash=pinned)

    def test_the_same_hash_over_the_same_bytes_is_not_a_reuse(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The idempotent re-assertion: a schedule sealing an unchanged
        # lake at a later instant publishes under the same identity — the
        # hash names the same bytes, so the scores cached under it are
        # exactly as valid as they were. The guard's line is content, not
        # the calendar.
        first = service.seal(staged, sealed_at=AT)
        second = service.seal(staged, sealed_at=AT_LATER)

        assert second.snapshot_hash == first.snapshot_hash
        assert second.path != first.path
        for name in (first.name, second.name):
            assert service.read_manifest(name).snapshot_hash == first.snapshot_hash

    def test_the_extended_lake_still_seals_once_the_hash_is_left_to_the_system(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The refusal points the caller at the cure: drop the stale pin
        # and the system assigns the extended lake its own new identity.
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)

        with pytest.raises(SnapshotHashReusedError):
            service.seal(staged, sealed_at=AT_LATER, snapshot_hash=first.snapshot_hash)

        second = service.seal(staged, sealed_at=AT_LATER)
        assert second.snapshot_hash != first.snapshot_hash
        assert service.sealed() == sorted([first.name, second.name])


# ---------------------------------------------------------------------------
# Only when the lake is extended
# ---------------------------------------------------------------------------


class TestOnlyWhenTheLakeIsExtended:
    def test_unchanged_staging_reasserts_one_identity(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        cached_scores = {first.snapshot_hash: {"BTCUSDT": 0.42}}

        second = service.seal(staged, sealed_at=AT_LATER)

        # No extension, no re-key: the cached score stays addressed, and
        # the quiet-lake seal does not invalidate anything.
        assert second.snapshot_hash == first.snapshot_hash
        assert second.snapshot_hash in cached_scores

    def test_identical_content_at_one_instant_is_still_idempotent(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        second = service.seal(staged, sealed_at=AT)
        assert second.path == first.path
        assert second.path.stat().st_ino == first.path.stat().st_ino


# ---------------------------------------------------------------------------
# The guard reads the lake, and only what the lake can prove
# ---------------------------------------------------------------------------


class TestTheGuardReadsTheLake:
    def test_a_corrupt_manifest_elsewhere_does_not_block_an_unrelated_seal(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        # The assignments come from manifests, and a manifest that cannot
        # be parsed proves no binding. One corrupt neighbour must not
        # brick the write path — the name-level checks still own that
        # directory for seals that name it.
        first = service.seal(staged, sealed_at=AT)
        manifest_file = first.path / "MANIFEST.json"
        os.chmod(first.path, 0o755)
        os.chmod(manifest_file, 0o644)
        manifest_file.write_bytes(b"corrupted")
        os.chmod(manifest_file, 0o444)
        os.chmod(first.path, 0o555)

        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)
        assert second.snapshot_hash != first.snapshot_hash
        assert service.sealed() == sorted([first.name, second.name])

    def test_a_manifest_free_neighbour_does_not_block_an_unrelated_seal(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # A snapshot sealed before manifests existed persists no full hash,
        # so it cannot prove an assignment; the guard skips it rather than
        # guessing, and the name-level checks still protect its name.
        first = service.seal(staged, sealed_at=AT)
        os.chmod(first.path, 0o755)
        (first.path / "MANIFEST.json").unlink()
        os.chmod(first.path, 0o555)

        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)
        assert second.snapshot_hash != first.snapshot_hash
        assert service.sealed() == sorted([first.name, second.name])
