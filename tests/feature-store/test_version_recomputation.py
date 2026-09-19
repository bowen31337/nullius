"""Feature 54 — a feature_version bump flags the dependent scores the old
version held, emitting the same recomputation signal a snapshot change (feature
39) produces, while the prior-version rows survive intact.

These are the acceptance tests for app_spec.xml feature 54 — *"System treats a
feature_version bump as invalidating dependent scores, which emits the same
recomputation signal an evaluator change produces"* — the feature-store
counterpart of feature 39's recomputation registry.  Each clause of the
sentence is pinned below:

* *treats a feature_version bump as invalidating dependent scores* —
  ``record_version_change`` flags every dependent score anchored to the old
  version, and only those; a dependent under another version keeps its flag,
  and the change records a version-change in the audit carrying how many it
  reached.
* *emits the same recomputation signal an evaluator change produces* — the
  signal is feature 39's shape transposed from snapshot to version: a persisted
  per-score ``recompute`` flag, a ``superseded_by`` reason, an append-only audit
  of the changes, and a ``needs_recomputation(score_id)`` query the derived zone
  polls.  A dependent re-registered against the new version (the derived zone
  recomputed it) clears its flag, exactly as feature 39's re-registration does.
* *the prior-version rows survive* — feature 54's half of feature 53's contract
  is that a changed definition writes *beside* the old rows; this module's
  change only moves the dependents' flags, never the rows.  The rows a version
  bump leaves untouched are not this registry's nouns — it holds only the
  addressing and the flag.

The registry holds only the addressing (which score, which feature, which
version) and the flag — never a dependent score's value or a feature's rows.  It
is the invalidation signal; the derived zone owns the recomputation the signal
points at.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from feature_store import (
    DEPENDENT_RECOMPUTATION_NAME,
    VersionRecomputationError,
    VersionRecomputationRegistry,
    version_recomputation_registry,
)

UTC = timezone.utc
AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
AT_LATER = datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC)

FEATURE = "realized_volatility"
V1 = "1"
V2 = "2"
V3 = "3"


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------


class TestRegistryPersistence:
    def test_the_registry_persists_to_the_lake_root(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("sig-1", FEATURE, V1)
        # The flag is written to the lake, beside feature 39's recomputation.json.
        assert registry.path == lake_root / DEPENDENT_RECOMPUTATION_NAME
        assert registry.path.is_file()

    def test_a_flag_survives_a_fresh_registry(self, lake_root: Path) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("sig-1", FEATURE, V1)
        registry.record_version_change(FEATURE, V1, V2)
        # A new registry — a new process — reads back the flag it set.
        reread = VersionRecomputationRegistry(lake_root)
        assert reread.needs_recomputation("sig-1")
        assert reread.score("sig-1").recompute
        assert reread.score("sig-1").superseded_by == V2

    def test_a_missing_registry_is_an_empty_registry(self, tmp_path: Path) -> None:
        registry = VersionRecomputationRegistry(tmp_path)
        assert registry.scores_for(FEATURE, V1) == []
        assert registry.flagged_scores() == []
        assert registry.version_changes() == []


# ---------------------------------------------------------------------------
# Dependent scores
# ---------------------------------------------------------------------------


class TestDependentScores:
    def test_registering_a_dependent_anchors_it_to_feature_and_version(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        record = registry.register_dependent_score("sig-1", FEATURE, V1)
        assert record.score_id == "sig-1"
        assert record.feature_name == FEATURE
        assert record.feature_version == V1
        assert record.recompute is False
        assert registry.score("sig-1") is record

    def test_scores_for_a_version_are_found(self, lake_root: Path) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        registry.register_dependent_score("s2", FEATURE, V1)
        registry.register_dependent_score("s3", FEATURE, V2)
        by_version = {r.score_id for r in registry.scores_for(FEATURE, V1)}
        assert by_version == {"s1", "s2"}

    def test_re_registering_a_dependent_clears_its_flag(self, lake_root: Path) -> None:
        # The derived zone recomputes a flagged dependent and re-registers it
        # against the new version: a fresh computation returns it to
        # recompute=False, exactly as feature 39's re-registration does.
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        registry.record_version_change(FEATURE, V1, V2)
        assert registry.needs_recomputation("s1")
        registry.register_dependent_score("s1", FEATURE, V2)
        assert not registry.needs_recomputation("s1")

    def test_an_unknown_score_does_not_need_recomputation(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        assert registry.needs_recomputation("never-registered") is False

    def test_a_blank_score_id_is_refused(self, lake_root: Path) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        with pytest.raises(VersionRecomputationError, match="score_id"):
            registry.register_dependent_score("", FEATURE, V1)

    def test_an_impossible_feature_name_is_refused(self, lake_root: Path) -> None:
        # feature_name is a key component; a value that could never be part of a
        # key (empty, padded, path-unsafe) is a caller bug, raised as the
        # version-recomputation error, not the key layer's FeatureKeyError.
        registry = VersionRecomputationRegistry(lake_root)
        with pytest.raises(VersionRecomputationError, match="feature_name"):
            registry.register_dependent_score("s1", "bad/name", V1)
        with pytest.raises(VersionRecomputationError, match="feature_name"):
            registry.register_dependent_score("s1", "  padded  ", V1)


# ---------------------------------------------------------------------------
# The version change
# ---------------------------------------------------------------------------


class TestVersionChange:
    def test_a_bump_flags_every_dependent_under_the_old_version(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        registry.register_dependent_score("s2", FEATURE, V1)
        registry.register_dependent_score("s3", FEATURE, V2)

        change = registry.record_version_change(FEATURE, V1, V2)

        assert registry.needs_recomputation("s1")
        assert registry.needs_recomputation("s2")
        # A dependent under another version keeps its flag — untouched.
        assert not registry.needs_recomputation("s3")
        assert change.flagged_scores == 2

    def test_a_flagged_dependent_carries_the_version_that_superseded_it(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        registry.record_version_change(FEATURE, V1, V2)
        assert registry.score("s1").superseded_by == V2

    def test_the_change_is_recorded_in_the_audit(self, lake_root: Path) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        registry.record_version_change(FEATURE, V1, V2, recorded_at=AT)
        audit = registry.version_changes()
        assert len(audit) == 1
        assert audit[0].feature_name == FEATURE
        assert audit[0].old_version == V1
        assert audit[0].new_version == V2
        assert audit[0].flagged_scores == 1
        assert audit[0].recorded_at == AT

    def test_the_audit_accumulates_changes(self, lake_root: Path) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        registry.register_dependent_score("s2", FEATURE, V2)
        registry.record_version_change(FEATURE, V1, V2)
        registry.record_version_change(FEATURE, V2, V3)
        assert [c.new_version for c in registry.version_changes()] == [V2, V3]
        assert registry.needs_recomputation("s1")
        assert registry.needs_recomputation("s2")

    def test_a_bump_against_a_version_with_no_dependents_is_refused(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        with pytest.raises(VersionRecomputationError, match="no dependent scores"):
            registry.record_version_change(FEATURE, V2, V3)
        # The registry is untouched: no version change recorded.
        assert registry.version_changes() == []

    def test_a_bump_between_identical_versions_is_refused(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        with pytest.raises(VersionRecomputationError, match="different versions"):
            registry.record_version_change(FEATURE, V1, V1)
        assert registry.version_changes() == []

    def test_a_bump_leaves_dependents_under_other_versions_untouched(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("s1", FEATURE, V1)
        registry.register_dependent_score("s2", "breadth", V1)
        registry.record_version_change(FEATURE, V1, V2)
        # A dependent on a different feature at the same old version is not
        # flagged: the bump is scoped to one feature_name.
        assert not registry.needs_recomputation("s2")

    def test_a_flag_set_by_a_bump_is_read_back_after_restart(
        self, lake_root: Path
    ) -> None:
        registry = VersionRecomputationRegistry(lake_root)
        registry.register_dependent_score("sig-1", FEATURE, V1)
        registry.record_version_change(FEATURE, V1, V2)
        # A fresh registry over the same lake sees the flag.
        fresh = VersionRecomputationRegistry(lake_root)
        assert fresh.needs_recomputation("sig-1")


# ---------------------------------------------------------------------------
# The helper resolves the lake root the way the services do (feature 54)
# ---------------------------------------------------------------------------


class TestVersionRecomputationRegistryHelper:
    def test_the_helper_defaults_from_the_lake_root_env(
        self, lake_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LAKE_ROOT", str(lake_root))
        registry = version_recomputation_registry()
        assert registry.path == lake_root / DEPENDENT_RECOMPUTATION_NAME

    def test_the_helper_takes_an_explicit_lake_root(
        self, lake_root: Path
    ) -> None:
        registry = version_recomputation_registry(lake_root)
        assert registry.path == lake_root / DEPENDENT_RECOMPUTATION_NAME

    def test_end_to_end_signal_through_the_helper(
        self, lake_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The whole of feature 54, observed through the one-shot helper: a
        # dependent is registered against version 1, a version bump invalidates
        # it, and the derived zone's query reports it needs recomputation.
        monkeypatch.setenv("LAKE_ROOT", str(lake_root))
        registry = version_recomputation_registry()
        registry.register_dependent_score("signal-node-1", FEATURE, V1)
        assert not registry.needs_recomputation("signal-node-1")

        registry.record_version_change(FEATURE, V1, V2)
        assert registry.needs_recomputation("signal-node-1")
        assert registry.score("signal-node-1").superseded_by == V2

        # The derived zone recomputes the dependent against version 2 and
        # re-registers it: the flag clears, so the signal is not sticky.
        registry.register_dependent_score("signal-node-1", FEATURE, V2)
        assert not registry.needs_recomputation("signal-node-1")
