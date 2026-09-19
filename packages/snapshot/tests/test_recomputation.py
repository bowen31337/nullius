"""Feature 39 — a recomputation flag on every score a snapshot change affects,
while the discovery tree structure survives intact.

These are the acceptance tests for app_spec.xml feature 39 — *"System
persists a recomputation flag on every score affected by a snapshot change,
while the discovery tree structure survives intact"* — the mechanism that
turns feature 38's new hash into a durable, visible recomputation signal.
Each clause of the sentence is pinned below:

* *persists a recomputation flag* — the flag is written to
  ``<lake>/recomputation.json`` and read back by a fresh registry: a flag
  that vanished on restart would silently reuse the stale score it was
  meant to replace, so persistence is the whole point.
* *on every score affected by a snapshot change* — ``record_snapshot_change``
  flags every score the lake persisted under the old hash, and only those;
  a score under another hash keeps its flag, and the change records a
  supersession in the audit carrying how many it reached.
* *while the discovery tree structure survives intact* — the tree's nodes
  and edges are not rewritten by a snapshot change; only the scores' flags
  move. The edge list is identical before and after.

The registry holds only the addressing (which score, which node, which
hash) and the flag — never a score's value or a node's meaning. It is the
invalidation signal; the derived zone owns the recomputation the signal
points at. The score cache and tree here are the registry's own nouns,
reduced to what this feature pins: that a snapshot change genuinely flags
the scores a snapshot held, durably, and leaves the tree alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import (
    RECOMPUTATION_NAME,
    RecomputationRegistry,
    SnapshotRecomputationError,
    SnapshotService,
)

UTC = timezone.utc
AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
AT_LATER = datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC)

BTC_PART_0 = b"BTCUSDT-2026-09-01-part-0"
BTC_PART_1 = b"BTCUSDT-2026-09-01-part-1"
ETH_PART_0 = b"ETHUSDT-2026-09-01-part-0"
SOL_PART_0 = b"SOLUSDT-2026-09-02-part-0"

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64


def _extend_with_a_new_partition(staged: Path) -> None:
    """Append one new symbol/date partition — §4.1's append-only growth."""
    partition = staged / "bars" / "symbol=SOLUSDT" / "date=2026-09-02"
    partition.mkdir(parents=True)
    (partition / "part-0.parquet").write_bytes(SOL_PART_0)


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------


class TestRegistryPersistence:
    def test_the_registry_persists_to_the_lake_root(
        self, lake_root: Path
    ) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("score-1", H1, node_id="node-a")
        # The flag is written to the lake, beside snapshots/ and staging/.
        assert registry.path == lake_root / RECOMPUTATION_NAME
        assert registry.path.is_file()

    def test_a_flag_survives_a_fresh_registry(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("score-1", H1, node_id="node-a")
        registry.record_snapshot_change(H1, H2)
        # A new registry — a new process — reads back the flag it set.
        reread = RecomputationRegistry(lake_root)
        assert reread.needs_recomputation("score-1")
        assert reread.score("score-1").recompute
        assert reread.score("score-1").superseded_by == H2

    def test_a_missing_registry_is_an_empty_registry(self, tmp_path: Path) -> None:
        registry = RecomputationRegistry(tmp_path)
        assert registry.scores_for_snapshot(H1) == []
        assert registry.flagged_scores() == []
        assert registry.tree_nodes() == []
        assert registry.supersessions() == []


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------


class TestScores:
    def test_registering_a_score_anchors_it_to_node_and_hash(
        self, lake_root: Path
    ) -> None:
        registry = RecomputationRegistry(lake_root)
        record = registry.register_score("score-1", H1, node_id="node-a")
        assert record.score_id == "score-1"
        assert record.snapshot_hash == H1
        assert record.node_id == "node-a"
        assert record.recompute is False
        assert registry.score("score-1") is record

    def test_a_score_without_a_node_is_allowed(self, lake_root: Path) -> None:
        # A campaign-level aggregate decorates no tree node.
        registry = RecomputationRegistry(lake_root)
        record = registry.register_score("campaign-score", H1)
        assert record.node_id is None

    def test_scores_for_a_hash_are_found(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("s1", H1, node_id="a")
        registry.register_score("s2", H1, node_id="b")
        registry.register_score("s3", H2, node_id="c")
        by_hash = {r.score_id for r in registry.scores_for_snapshot(H1)}
        assert by_hash == {"s1", "s2"}

    def test_re_registering_a_score_clears_its_flag(self, lake_root: Path) -> None:
        # The derived zone recomputes a flagged score and re-registers it:
        # a fresh computation returns it to recompute=False.
        registry = RecomputationRegistry(lake_root)
        registry.register_score("s1", H1, node_id="a")
        registry.record_snapshot_change(H1, H2)
        assert registry.needs_recomputation("s1")
        registry.register_score("s1", H1, node_id="a")
        assert not registry.needs_recomputation("s1")

    def test_an_unknown_score_does_not_need_recomputation(
        self, lake_root: Path
    ) -> None:
        registry = RecomputationRegistry(lake_root)
        assert registry.needs_recomputation("never-registered") is False

    def test_a_blank_score_id_is_refused(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        with pytest.raises(SnapshotRecomputationError):
            registry.register_score("", H1)


# ---------------------------------------------------------------------------
# The discovery tree
# ---------------------------------------------------------------------------


class TestDiscoveryTree:
    def test_registering_a_node_records_its_edges(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_node("root", node_type="campaign")
        registry.register_node("child", parents=["root"], node_type="trial")
        assert registry.node("child").parents == ("root",)
        assert registry.edges() == [("root", "child")]

    def test_edges_are_de_duplicated_and_sorted(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_node("n", parents=["b", "a", "a", "b"])
        assert registry.node("n").parents == ("a", "b")

    def test_re_registering_a_node_does_not_duplicate_edges(
        self, lake_root: Path
    ) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_node("child", parents=["root"], node_type="trial")
        registry.register_node("child", parents=["root"], node_type="trial")
        assert registry.edges() == [("root", "child")]

    def test_tree_structure_view(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_node("root")
        registry.register_node("child", parents=["root"])
        assert registry.tree_structure() == {"root": [], "child": ["root"]}


# ---------------------------------------------------------------------------
# The snapshot change
# ---------------------------------------------------------------------------


class TestSnapshotChange:
    def test_a_change_flags_every_score_under_the_old_hash(
        self, lake_root: Path
    ) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("s1", H1, node_id="a")
        registry.register_score("s2", H1, node_id="b")
        registry.register_score("s3", H2, node_id="c")

        supersession = registry.record_snapshot_change(H1, H2)

        assert registry.needs_recomputation("s1")
        assert registry.needs_recomputation("s2")
        # A score under another hash keeps its flag — untouched.
        assert not registry.needs_recomputation("s3")
        assert supersession.flagged_scores == 2

    def test_a_flagged_score_carries_the_hash_that_superseded_it(
        self, lake_root: Path
    ) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("s1", H1, node_id="a")
        registry.record_snapshot_change(H1, H2)
        assert registry.score("s1").superseded_by == H2

    def test_the_change_is_recorded_in_the_audit(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("s1", H1, node_id="a")
        registry.record_snapshot_change(H1, H2, recorded_at=AT)
        audit = registry.supersessions()
        assert len(audit) == 1
        assert audit[0].old_hash == H1
        assert audit[0].new_hash == H2
        assert audit[0].flagged_scores == 1
        assert audit[0].recorded_at == AT

    def test_the_audit_accumulates_changes(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("s1", H1, node_id="a")
        registry.register_score("s2", H2, node_id="b")
        registry.record_snapshot_change(H1, H2)
        registry.record_snapshot_change(H2, H3)
        assert [s.new_hash for s in registry.supersessions()] == [H2, H3]
        assert registry.needs_recomputation("s1")
        assert registry.needs_recomputation("s2")

    def test_a_change_against_a_hash_with_no_scores_is_refused(
        self, lake_root: Path
    ) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("s1", H1, node_id="a")
        with pytest.raises(SnapshotRecomputationError, match="no scores"):
            registry.record_snapshot_change(H2, H3)
        # The registry is untouched: no supersession recorded.
        assert registry.supersessions() == []

    def test_a_change_between_identical_hashes_is_refused(
        self, lake_root: Path
    ) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_score("s1", H1, node_id="a")
        with pytest.raises(SnapshotRecomputationError, match="different hashes"):
            registry.record_snapshot_change(H1, H1)

    def test_the_tree_survives_the_change_intact(self, lake_root: Path) -> None:
        registry = RecomputationRegistry(lake_root)
        registry.register_node("root", node_type="campaign")
        registry.register_node("child", parents=["root"], node_type="trial")
        registry.register_score("s1", H1, node_id="child")

        before_edges = registry.edges()
        before_structure = registry.tree_structure()
        registry.record_snapshot_change(H1, H2)
        after_edges = registry.edges()
        after_structure = registry.tree_structure()

        # The tree structure survives: no edge added, removed, or rewritten.
        assert after_edges == before_edges
        assert after_structure == before_structure
        # Only the score's flag moved.
        assert registry.score("s1").recompute is True


# ---------------------------------------------------------------------------
# The service grounds the change in the lake (feature 39 + feature 38)
# ---------------------------------------------------------------------------


class TestServiceRecordSnapshotChange:
    def test_a_change_between_two_sealed_snapshots_flags_their_scores(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # Feature 38 produces the two hashes; feature 39 flags the scores.
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        registry = service.recomputation
        registry.register_score("score-btc", first.snapshot_hash, node_id="node-a")
        registry.register_score("score-eth", first.snapshot_hash, node_id="node-b")

        supersession = service.record_snapshot_change(
            first.snapshot_hash, second.snapshot_hash
        )

        assert supersession.flagged_scores == 2
        assert registry.needs_recomputation("score-btc")
        assert registry.needs_recomputation("score-eth")
        assert registry.score("score-btc").superseded_by == second.snapshot_hash

    def test_a_change_naming_an_unsealed_hash_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        registry = service.recomputation
        registry.register_score("score-btc", first.snapshot_hash, node_id="node-a")
        # A hash from another lake, or a typo: no sealed snapshot carries it.
        with pytest.raises(SnapshotRecomputationError, match="does not name"):
            service.record_snapshot_change("0" * 64, first.snapshot_hash)
        assert registry.supersessions() == []

    def test_a_change_naming_an_unsealed_new_hash_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        registry = service.recomputation
        registry.register_score("score-btc", first.snapshot_hash, node_id="node-a")
        # The old hash is real; the new one is not. The change is refused
        # whole — a supersession must relate two snapshots the lake holds.
        with pytest.raises(SnapshotRecomputationError, match="does not name"):
            service.record_snapshot_change(first.snapshot_hash, "f" * 64)
        assert registry.supersessions() == []

    def test_a_change_naming_a_wrong_full_hash_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # A hash sharing a sealed snapshot's six-character prefix but not its
        # full hash: the manifest records the full hash in full, and a change
        # must match it, not merely its shorthand.
        first = service.seal(staged, sealed_at=AT)
        registry = service.recomputation
        registry.register_score("score-btc", first.snapshot_hash, node_id="node-a")
        prefix = first.snapshot_hash[:6]
        wrong_full = prefix + "0" * 58
        with pytest.raises(SnapshotRecomputationError, match="does not match"):
            service.record_snapshot_change(wrong_full, first.snapshot_hash)

    def test_the_registry_persists_beside_the_snapshots(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        registry = service.recomputation
        registry.register_score("score-btc", first.snapshot_hash, node_id="node-a")
        # The registry file lives at the lake root, beside snapshots/ and
        # staging/ (§4.2) — a lake-level record, not inside any snapshot.
        assert registry.path == lake_root / RECOMPUTATION_NAME
        assert registry.path.parent == lake_root
        for snapshot in service.mounted():
            assert snapshot.path / RECOMPUTATION_NAME != registry.path

    def test_a_flag_set_by_the_service_is_read_back_after_restart(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        service.recomputation.register_score(
            "score-btc", first.snapshot_hash, node_id="node-a"
        )
        service.record_snapshot_change(first.snapshot_hash, second.snapshot_hash)

        # A fresh service — a fresh registry over the same lake — sees the flag.
        fresh_service = SnapshotService.from_env()
        assert fresh_service.recomputation.needs_recomputation("score-btc")

    def test_a_change_leaves_the_sealed_bytes_untouched(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # Feature 39 flags scores; it does not move or rewrite the snapshots
        # the scores were computed over. The old snapshot's bytes are still
        # exactly what they were.
        first = service.seal(staged, sealed_at=AT)
        _extend_with_a_new_partition(staged)
        second = service.seal(staged, sealed_at=AT_LATER)

        service.recomputation.register_score(
            "score-btc", first.snapshot_hash, node_id="node-a"
        )
        service.record_snapshot_change(first.snapshot_hash, second.snapshot_hash)

        sealed_btc = (
            first.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        )
        assert sealed_btc.read_bytes() == BTC_PART_0
        assert service.sealed() == sorted([first.name, second.name])
