"""The nightly canary replay — feature 142.

These tests pin :mod:`canary._replay` — the verb feature 142's sentence is, and
the refusals that keep the replay a *measurement* rather than a verdict.  The
properties under test are the ones the module docstring argues:

* the score is a pure function of the frozen pair — the same pair replays to the
  same score however it arrived, by hand or read back from the store;
* the replay reports the comparison (score, recorded constant, deviation, the
  ``1e-12`` band) but does not decide it — the halt-dreaming is feature 143's;
* a pair not yet replayed — ``recorded_score`` is ``None`` — replays to a result
  with no deviation and nothing broken, so the first night records the constant;
* the tree is replayed in a stable order, so a tree and the same tree walked in
  another order are one score;
* a tree that carries a non-number ``score`` or ``weight`` is refused by name —
  a reference that has drifted into something the canary can no longer measure.

The pairs below are real frozen pairs, not mocks: the point of the feature is
that the score is a function of the frozen bytes, so the passing cases use a
genuinely frozen policy and tree, and the divergent cases use a pair whose
recorded constant the replayed score does not reach.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from canary import (
    DEFAULT_TOLERANCE,
    CanaryError,
    CanaryReferencePair,
    CanaryReplay,
    CanaryReplayResult,
    CanaryReplayScoreError,
    CanaryService,
    CanaryTree,
    replay_pair,
)
from canary._reference import CanaryPolicy

POLICY_VERSION = "canary-v1"


# -- Fixtures ------------------------------------------------------------------


def _policy(version: str = POLICY_VERSION) -> CanaryPolicy:
    return CanaryPolicy.freeze(
        version=version,
        policy={"scoring": {"weights": {"a": 0.5, "b": 0.5}}, "threshold": 0.7},
    )


def _tree() -> CanaryTree:
    # Each node carries a canonical ``score`` and, for the leaves, a ``weight``.
    # The frozen tree sorts its nodes by node_id, so the walk the score is
    # computed from is the walk the tree's identity is the identity of.
    return CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root", "kind": "decision", "score": 0.0}),
            "left": ("root", 1, {"label": "left", "weight": 0.3, "score": 0.8}),
            "right": ("root", 1, {"label": "right", "weight": 0.7, "score": 0.6}),
        }
    )


def _pair(*, score=None, created_at: datetime | None = None) -> CanaryReferencePair:
    return CanaryReferencePair(
        policy=_policy(version=POLICY_VERSION),
        tree=_tree(),
        recorded_score=score,
        id=None,
        is_active=True,
        created_at=created_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


#: The score the fixture tree replays to: ``0.8 * 0.3 + 0.6 * 0.7`` (the root's
#: own score is ``0.0``).  Named rather than recomputed at each call site so the
#: tests assert against one spelling of the expected value.
EXPECTED_SCORE = 0.8 * 0.3 + 0.6 * 0.7


# -- The feature's verb: a frozen pair replays to a score ----------------------


class TestTheReplayScoresTheFrozenPair:
    def test_a_frozen_pair_replays_to_a_score(self) -> None:
        # Feature 142's whole sentence: the frozen policy over the frozen tree,
        # once, to a single float.
        result = replay_pair(_pair())
        assert isinstance(result, CanaryReplayResult)
        assert result.score == EXPECTED_SCORE

    def test_the_score_is_a_plain_float(self) -> None:
        # The score is the same kind of value the store's ``recorded_score``
        # REAL column holds and §12's 1e-12 compares — not a wrapped or rounded
        # thing.  A replay that rounded its own score would be editing the
        # number the comparison is about.
        result = replay_pair(_pair())
        assert isinstance(result.score, float)

    def test_the_replay_is_a_pure_function_of_the_pair(self) -> None:
        # The only thing allowed to change between the night the constant was
        # recorded and the night it is checked is the machine — so the same pair
        # replays to the same score, twice.
        assert replay_pair(_pair()).score == replay_pair(_pair()).score

    def test_the_replay_ignores_the_policy_parameters_it_does_not_read(self) -> None:
        # The score is ``sum(node.score * node.weight)`` over the tree; the
        # policy's own parameters (threshold, weights) are not read by this
        # replay, so changing them does not move the score.  The replay is a
        # pure function of the tree's node scores and weights, and nothing else.
        other = CanaryReferencePair(
            policy=CanaryPolicy.freeze(
                version=POLICY_VERSION,
                policy={"scoring": {"weights": {"x": 0.1}}, "threshold": 0.99},
            ),
            tree=_tree(),
            recorded_score=None,
            id=None,
            is_active=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert replay_pair(other).score == EXPECTED_SCORE

    def test_a_leaf_with_no_score_contributes_zero(self) -> None:
        # A node with no ``score`` key is a structural node, not a scored leaf:
        # it defaults to ``0.0`` rather than breaking the sum.
        tree = CanaryTree.freeze(
            {
                "root": (None, 0, {"label": "root", "score": 0.5}),
                "leaf": ("root", 1, {"label": "leaf"}),
            }
        )
        pair = CanaryReferencePair(
            policy=_policy(),
            tree=tree,
            recorded_score=None,
            id=None,
            is_active=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert replay_pair(pair).score == 0.5

    def test_a_leaf_with_no_weight_is_weighted_one(self) -> None:
        # A node with no ``weight`` key defaults to a weight of ``1.0`` — a
        # leaf's own contribution, unscaled.
        tree = CanaryTree.freeze(
            {"root": (None, 0, {"label": "root", "score": 0.4})}
        )
        pair = CanaryReferencePair(
            policy=_policy(),
            tree=tree,
            recorded_score=None,
            id=None,
            is_active=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert replay_pair(pair).score == 0.4


# -- The comparison is reported, not decided -----------------------------------


class TestTheReplayReportsTheComparison:
    def test_within_tolerance_when_the_score_matches(self) -> None:
        # A recorded constant the replayed score reaches: deviation within
        # 1e-12, nothing broken.  The replay reports; feature 143 decides.
        result = replay_pair(_pair(score=EXPECTED_SCORE))
        assert result.recorded_score == EXPECTED_SCORE
        assert result.deviation == 0.0
        assert result.within_tolerance is True
        assert result.broken is False

    def test_broken_when_the_score_has_drifted(self) -> None:
        # The "the world moved" case: a recorded constant the replayed score no
        # longer reaches, past the 1e-12 band.  The result reports the break;
        # the halt is the caller's.
        drifted = EXPECTED_SCORE + 1e-6
        result = replay_pair(_pair(score=drifted))
        assert result.deviation == pytest.approx(1e-6)
        assert result.within_tolerance is False
        assert result.broken is True

    def test_exactly_at_the_tolerance_is_within(self) -> None:
        # §12's comparison is ``> 1e-12`` — a deviation *equal* to the tolerance
        # is still within it (the ``<=``), while one past it breaks.  The
        # boundary the nightly canary turns on.  A zero-scoring tree and a
        # recorded constant of exactly the tolerance make the deviation exactly
        # the tolerance — ``abs(0.0 - 1e-12) == 1e-12`` is exact, so this tests
        # the ``<=`` boundary without floating-point rounding hiding it.
        zero_tree = CanaryTree.freeze({"root": (None, 0, {"score": 0.0})})
        pair = CanaryReferencePair(
            policy=_policy(),
            tree=zero_tree,
            recorded_score=DEFAULT_TOLERANCE,
            id=None,
            is_active=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        result = replay_pair(pair)
        assert result.score == 0.0
        assert result.deviation == DEFAULT_TOLERANCE
        assert result.within_tolerance is True
        # One past the band breaks: double the tolerance, clearly ``> 1e-12``.
        broken = CanaryReferencePair(
            policy=_policy(),
            tree=zero_tree,
            recorded_score=DEFAULT_TOLERANCE * 2,
            id=None,
            is_active=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert replay_pair(broken).within_tolerance is False
        assert replay_pair(broken).broken is True

    def test_just_past_the_tolerance_is_broken(self) -> None:
        # One epsilon past the band: the deviation the ``>`` catches.
        past = EXPECTED_SCORE + DEFAULT_TOLERANCE * 2
        result = replay_pair(_pair(score=past))
        assert result.within_tolerance is False
        assert result.broken is True

    def test_the_result_carries_the_tolerance_it_was_measured_against(self) -> None:
        # So a report can show which threshold a within_tolerance was measured
        # against, rather than a reader having to find it in the code.
        result = replay_pair(_pair(score=EXPECTED_SCORE))
        assert result.tolerance == DEFAULT_TOLERANCE


# -- Not yet replayed: no recorded constant ------------------------------------


class TestTheReplayOfAPairNotYetReplayed:
    def test_a_pair_not_yet_replayed_has_no_deviation(self) -> None:
        # ``recorded_score`` is None — the store's Nullable, so a freshly-frozen
        # pair is "not yet replayed", not "replayed to zero".  The first night
        # records the constant rather than breaking against one that does not
        # exist.
        result = replay_pair(_pair(score=None))
        assert result.recorded_score is None
        assert result.deviation is None

    def test_a_pair_not_yet_replayed_is_not_broken(self) -> None:
        # There is nothing to deviate from, so there is nothing to break.  A
        # freshly-frozen pair must never be reported as a determinism break.
        result = replay_pair(_pair(score=None))
        assert result.within_tolerance is True
        assert result.broken is False


# -- The replay is invariant to walk order -------------------------------------


class TestTheReplayIsInvariantToNodeOrder:
    def test_a_tree_replays_the_same_score_walked_any_way(self) -> None:
        # The tree is its nodes as a set — that is what tree_hash hashes — so the
        # score must not depend on the order the nodes were handed in.  Two trees
        # built from the same nodes in a different insertion order replay to one
        # score.
        forward = CanaryTree.freeze(
            {
                "root": (None, 0, {"score": 0.0}),
                "left": ("root", 1, {"weight": 0.3, "score": 0.8}),
                "right": ("root", 1, {"weight": 0.7, "score": 0.6}),
            }
        )
        backward = CanaryTree.freeze(
            {
                "right": ("root", 1, {"weight": 0.7, "score": 0.6}),
                "left": ("root", 1, {"weight": 0.3, "score": 0.8}),
                "root": (None, 0, {"score": 0.0}),
            }
        )
        assert forward.tree_hash == backward.tree_hash
        assert replay_pair(_pair()).score == EXPECTED_SCORE
        pair_f = CanaryReferencePair(
            policy=_policy(), tree=forward, recorded_score=None,
            id=None, is_active=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        pair_b = CanaryReferencePair(
            policy=_policy(), tree=backward, recorded_score=None,
            id=None, is_active=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert replay_pair(pair_f).score == replay_pair(pair_b).score


# -- The read-back pair replays through the same code ----------------------------


class TestTheReadBackPairReplays:
    def test_a_pair_read_back_from_the_store_replays_to_the_same_score(
        self, test_database_url: str
    ) -> None:
        # The nightly replay reads back the pair it froze and replays *that* — so
        # a pair read back from the store must replay through the same code to
        # the same score a hand-built pair does.  This is the production path:
        # freeze (feature 141), read back, replay (feature 142).
        from canary import CanaryReferenceStore

        store = CanaryReferenceStore(test_database_url)
        frozen = _pair(score=EXPECTED_SCORE)
        record = store.freeze(frozen)
        loaded = store.load(record.reference_id)
        assert replay_pair(loaded.pair).score == replay_pair(frozen).score
        assert replay_pair(loaded.pair).score == EXPECTED_SCORE


# -- A broken reference is refused, not reported as a divergence -----------------


class TestTheReplayRefusesAnUnscorableTree:
    def test_a_non_number_score_is_refused_by_name(self) -> None:
        # A frozen tree that has drifted into carrying a score that is not a
        # real number: the replay could not place it on the number line, so
        # there is no score to compare.  Refused by name, naming the node — a
        # broken reference, not a broken determinism.
        tree = CanaryTree.freeze(
            {"root": (None, 0, {"label": "root", "score": "high"})}
        )
        pair = CanaryReferencePair(
            policy=_policy(), tree=tree, recorded_score=None, id=None,
            is_active=True, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(CanaryReplayScoreError, match="score"):
            replay_pair(pair)

    def test_a_non_number_weight_is_refused_by_name(self) -> None:
        tree = CanaryTree.freeze(
            {"root": (None, 0, {"label": "root", "score": 0.5, "weight": "all"})}
        )
        pair = CanaryReferencePair(
            policy=_policy(), tree=tree, recorded_score=None, id=None,
            is_active=True, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(CanaryReplayScoreError, match="weight"):
            replay_pair(pair)

    def test_a_boolean_score_is_refused(self) -> None:
        # ``isinstance(True, int)``: a score of ``True`` is a broken reference,
        # not a score of 1.0.
        tree = CanaryTree.freeze({"root": (None, 0, {"score": True})})
        pair = CanaryReferencePair(
            policy=_policy(), tree=tree, recorded_score=None, id=None,
            is_active=True, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(CanaryReplayScoreError):
            replay_pair(pair)

    def test_the_refusal_is_a_canary_error_but_not_an_image_error(self) -> None:
        # The three breaks of §12's contract have three different repairs.  A
        # tree that cannot be scored is refused as a CanaryError — catchable with
        # the whole family — but it is not a moved pin (CanaryImageError) or a
        # divergent byte (CanaryReproducibilityError): the repair is to re-freeze
        # the pair.
        tree = CanaryTree.freeze({"root": (None, 0, {"score": "high"})})
        pair = CanaryReferencePair(
            policy=_policy(), tree=tree, recorded_score=None, id=None,
            is_active=True, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(CanaryError) as raised:
            replay_pair(pair)
        # A CanaryError, but not the image subclass (a moved pin) — the repair
        # for an unscorable tree is to re-freeze the pair, not to re-pin.
        from canary import CanaryImageError

        assert not isinstance(raised.value, CanaryImageError)
        assert type(raised.value).__name__ == "CanaryReplayScoreError"


# -- replay_pair takes a pair, not half of one ---------------------------------


class TestTheReplayTakesAPair:
    def test_replay_pair_takes_a_pair_not_half_of_one(self) -> None:
        with pytest.raises(CanaryError, match="CanaryReferencePair"):
            replay_pair("not a pair")  # type: ignore[arg-type]

    def test_replay_pair_refuses_a_negative_tolerance(self) -> None:
        with pytest.raises(CanaryError, match="tolerance"):
            replay_pair(_pair(score=EXPECTED_SCORE), tolerance=-1.0)

    def test_replay_pair_refuses_a_non_number_tolerance(self) -> None:
        with pytest.raises(CanaryError, match="tolerance"):
            replay_pair(_pair(score=EXPECTED_SCORE), tolerance="1e-12")  # type: ignore[arg-type]


# -- The result record is self-consistent --------------------------------------


class TestTheReplayResultIsSelfConsistent:
    def test_the_result_reports_the_terms_of_the_comparison(self) -> None:
        # The four fields are exactly the four terms of §12's
        # ``abs(score - CANARY_EXPECTED) > 1e-12``.  A deviation of ``1e-13`` is
        # well inside the ``1e-12`` band, so the score is within tolerance.
        result = replay_pair(_pair(score=EXPECTED_SCORE + 1e-13))
        assert result.score == EXPECTED_SCORE
        assert result.recorded_score == pytest.approx(EXPECTED_SCORE + 1e-13)
        assert result.deviation == pytest.approx(1e-13, abs=1e-13)
        assert result.within_tolerance is True
        assert result.broken is False

    def test_a_result_cannot_report_within_tolerance_with_a_large_deviation(self) -> None:
        # The constructor refuses a self-contradicting record: "within
        # tolerance" while carrying a deviation past the tolerance is a report
        # nobody can act on.
        with pytest.raises(CanaryError):
            CanaryReplayResult(
                score=1.0,
                recorded_score=0.0,
                deviation=1.0,
                within_tolerance=True,
                tolerance=1e-12,
            )

    def test_a_result_cannot_report_a_deviation_without_a_recorded_score(self) -> None:
        with pytest.raises(CanaryError):
            CanaryReplayResult(
                score=1.0,
                recorded_score=None,
                deviation=0.5,
                within_tolerance=True,
                tolerance=1e-12,
            )

    def test_a_result_cannot_report_a_wrong_width_hash_is_not_required(self) -> None:
        # The result carries no hash — the deviation is the distance, not a
        # digest — so a score comparison and a byte comparison stay in their own
        # vocabularies.
        result = replay_pair(_pair(score=EXPECTED_SCORE))
        assert not hasattr(result, "digest")


# -- The composed component carries the replay ---------------------------------


class TestTheServiceCarriesTheReplay:
    def test_the_service_exposes_the_replay(self) -> None:
        # Feature 142's replay is discoverable through the composed component,
        # not only through an import — the same stance the pin sweep and feature
        # 145's check take.
        service = CanaryService()
        assert isinstance(service.replay, CanaryReplay)

    def test_the_service_replay_delegates_to_the_module_function(self) -> None:
        # One answer to "what does the pair replay to": the composed facade and
        # the module function agree by construction.
        service = CanaryService()
        assert service.replay.pair(_pair()).score == replay_pair(_pair()).score

    def test_the_service_replay_reads_no_environment(self) -> None:
        # The replay is a pure function of the pair it is handed — no pins, no
        # database, no environment — so it works on a bare service with an unset
        # deployment.
        service = CanaryService()
        result = service.replay.pair(_pair(score=EXPECTED_SCORE))
        assert result.within_tolerance is True
