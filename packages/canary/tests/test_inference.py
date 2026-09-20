"""No inference in the replay path — feature 146.

These tests pin :mod:`canary._inference` — the guard that marks the replay
path's dynamic extent, the seam a model inference call goes through, and the
refusal that keeps the replay a *reader of materialized values* rather than
a computer of new ones — together with the wiring that puts feature 142's
replay under it. The properties under test are the ones the module docstring
argues:

* the refusal is of the call, not of the model — off the replay path the
  seam delegates, arguments and result untouched, because the evaluation
  path is where §11.2 computes learned outputs once and persists them;
* the replay path is a dynamic extent — the mark is set on entry, restored
  on exit however the extent ends, and nested extents unwind to the outer
  one's state rather than clearing it;
* the call is refused before it is made — the model never runs, whatever it
  would have computed;
* feature 142's replay runs under the guard, so a call attempted anywhere
  inside the replay is rejected, while a clean replay still replays to the
  score its frozen bytes sum to — the guard refuses, it does not perturb.

The models below are real callables, not mocks: the point of the seam is
that a caller's model *is* called off the replay path and *is not* called on
it, so the passing cases use a scorer that records its own calls, and the
"un-materialized learned component" case is a canary tree node that tries to
compute its score through the seam mid-replay — §15's "Learned component
reached the replay path un-materialized" row, held out of the pool before it
can drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from canary import (
    CanaryDeviceError,
    CanaryError,
    CanaryImageError,
    CanaryInferenceError,
    CanaryReferencePair,
    CanaryReplayScoreError,
    CanaryReproducibilityError,
    CanaryService,
    CanaryTree,
    CanaryTreeNode,
    ModelInference,
    canonical_json,
    is_replaying,
    model_inference,
    replay_pair,
    replaying,
)
from canary._reference import CanaryPolicy

POLICY_VERSION = "canary-v1"


# -- Fixtures ------------------------------------------------------------------


class _Scorer:
    """A learned component's scorer — callable, deterministic, recording.

    The "model" every test below calls through the seam: it returns one
    fixed float (the value a materialization would have persisted) and
    records every call it receives, so a test can assert not just what the
    seam returned or refused but *whether the model ran at all* — which is
    the feature's own order of operations, the refusal firing before the
    call.
    """

    def __init__(self, value: float = 0.25) -> None:
        self.value = value
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> float:
        self.calls.append((args, kwargs))
        return self.value


def _policy(version: str = POLICY_VERSION) -> CanaryPolicy:
    return CanaryPolicy.freeze(
        version=version,
        policy={"scoring": {"weights": {"a": 0.5, "b": 0.5}}, "threshold": 0.7},
    )


def _tree() -> CanaryTree:
    # Each node carries a canonical ``score`` and, for the leaves, a
    # ``weight`` — the stored floats a materialization would have persisted,
    # which is all the replay is ever allowed to read.
    return CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root", "kind": "decision", "score": 0.0}),
            "left": ("root", 1, {"label": "left", "weight": 0.3, "score": 0.8}),
            "right": ("root", 1, {"label": "right", "weight": 0.7, "score": 0.6}),
        }
    )


def _pair(*, score: float | None = None) -> CanaryReferencePair:
    return CanaryReferencePair(
        policy=_policy(version=POLICY_VERSION),
        tree=_tree(),
        recorded_score=score,
        id=None,
        is_active=True,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


#: The score the fixture tree replays to: ``0.8 * 0.3 + 0.6 * 0.7`` (the
#: root's own score is ``0.0``).  Named so the guard-does-not-perturb tests
#: assert against the number the frozen bytes sum to, not a recomputation.
EXPECTED_SCORE = 0.8 * 0.3 + 0.6 * 0.7


def _unmaterialized_node(
    model: _Scorer, observed: list[bool]
) -> CanaryTreeNode:
    """A tree node that tries to compute its score — §15's un-materialized
    learned component, reaching the replay path.

    No learned component exists to test with (§11.2 defers them all), so the
    test stands one up at exactly the seam the feature names: the node's
    ``content`` — the value :func:`replay_pair` reads back as a stored float —
    instead attempts to compute it through :func:`model_inference` mid-replay.
    The node first records whether it finds itself on the replay path, so one
    run shows both that the guard spans the walk and that the call it attempts
    is refused.  A real ``CanaryTreeNode`` subclass (not a mock), so the
    replay's own node handling runs unchanged around it.
    """

    class _Unmaterialized(CanaryTreeNode):
        @property
        def content(self) -> Any:
            observed.append(is_replaying())
            return model_inference(model, {"features": {"left": 0.8}})

    return _Unmaterialized(
        node_id="left",
        parent_id="root",
        depth=1,
        payload=canonical_json({"label": "left", "weight": 0.3, "score": 0.8}),
    )


def _pair_with_unmaterialized_node(
    model: _Scorer, observed: list[bool]
) -> CanaryReferencePair:
    return CanaryReferencePair(
        policy=_policy(version=POLICY_VERSION),
        tree=CanaryTree(
            nodes=(
                CanaryTreeNode.freeze(
                    "root", {"label": "root", "kind": "decision", "score": 0.0}, depth=0
                ),
                _unmaterialized_node(model, observed),
                CanaryTreeNode.freeze(
                    "right",
                    {"label": "right", "weight": 0.7, "score": 0.6},
                    parent_id="root",
                    depth=1,
                ),
            )
        ),
        recorded_score=None,
        id=None,
        is_active=True,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


# -- The guard: the replay path is a dynamic extent -----------------------------


def test_the_guard_is_off_outside_any_replay() -> None:
    # The honest default: code is on the replay path only while a replay is
    # running, and everything else — the evaluation path included, where
    # §11.2 computes learned outputs once and persists them — is not.
    assert is_replaying() is False


def test_the_guard_marks_the_dynamic_extent() -> None:
    # Set on entry, restored on exit: the mark says "this extent is the
    # replay path", not "this process once replayed".
    with replaying():
        assert is_replaying() is True
    assert is_replaying() is False


def test_the_guard_is_restored_when_the_extent_raises() -> None:
    # However the extent ends. A replay that raised and left the path
    # marked would refuse inference for every later caller of the process —
    # a module flag's failure mode, which is why the mark is a context
    # value restored by the exit, not a global set and cleared.
    with pytest.raises(RuntimeError, match="boom"), replaying():
        raise RuntimeError("boom")
    assert is_replaying() is False


def test_nested_extents_unwind_to_the_outer_state() -> None:
    # An extent entered from inside another one unwinds to *still
    # replaying*, because both extents are the replay path — restoring
    # rather than clearing is what keeps nesting honest.
    with replaying():
        with replaying():
            assert is_replaying() is True
        assert is_replaying() is True
    assert is_replaying() is False


def test_sequential_extents_do_not_leak_into_each_other() -> None:
    with replaying():
        pass
    with replaying():
        assert is_replaying() is True
    assert is_replaying() is False


# -- The seam, off the replay path: it delegates --------------------------------


def test_off_the_replay_path_the_seam_calls_the_model() -> None:
    # The evaluation path's ordinary business: a model called where §11.2
    # computes learned outputs once and persists them is the contract
    # working, not breaking, so the seam hands back the model's own result.
    scorer = _Scorer(value=0.75)
    assert model_inference(scorer) == 0.75
    assert len(scorer.calls) == 1


def test_off_the_replay_path_arguments_pass_through_untouched() -> None:
    # The delegation is thin: no caching, no counting, no rewriting — the
    # model sees exactly the arguments the caller handed, and the caller
    # sees exactly what the model returned.
    scorer = _Scorer(value=0.5)
    result = model_inference(scorer, "features", {"a": 1}, scale=2)
    assert result == 0.5
    assert scorer.calls == [(("features", {"a": 1}), {"scale": 2})]


def test_off_the_replay_path_a_non_callable_is_the_calls_own_failure() -> None:
    # The seam validates nothing about the model: a caller that hands it a
    # non-callable off the replay path gets the call's own TypeError, not a
    # canary-branded one — the refusal is about where the call was made
    # from, and this call was made from the wrong place to be refused.
    with pytest.raises(TypeError, match="not callable"):
        model_inference(42)


# -- The seam, on the replay path: the refusal ---------------------------------


def test_a_call_from_the_replay_path_is_refused() -> None:
    # Feature 146's sentence: the call is rejected because it was made from
    # the replay path, and the message carries both halves — where the call
    # came from and the §11.2 repair, because §15's recovery is an
    # operator's decision and an operator reads the message.
    scorer = _Scorer()
    with replaying(), pytest.raises(CanaryInferenceError) as raised:
        model_inference(scorer, {"features": {}})
    message = str(raised.value)
    assert "replay path" in message
    assert "materialized" in message
    assert "_Scorer" in message


def test_the_model_never_runs_when_the_call_is_refused() -> None:
    # The order of operations is the feature: the refusal fires *before*
    # the model runs. A guard that called the model and then raised would
    # have spent exactly the non-determinism it existed to refuse.
    scorer = _Scorer()
    with replaying(), pytest.raises(CanaryInferenceError):
        model_inference(scorer, {"features": {}})
    assert scorer.calls == []


def test_a_non_callable_on_the_replay_path_is_refused_as_a_call() -> None:
    # The refusal is of the call, not of the model: whatever the "model"
    # turns out to be, the call was made from the replay path, and that is
    # the one fact the refusal needs — so it is the inference refusal that
    # raises, not a TypeError about callability the replay never reached.
    with replaying(), pytest.raises(CanaryInferenceError, match="replay path"):
        model_inference(42)


def test_the_guard_covers_a_function_model_too() -> None:
    # A model that names itself (a function, a class) is named by its own
    # name in the refusal — the message points at the thing the operator
    # must materialize, not at an opaque repr.
    def _learned_scorer(features: object) -> float:  # pragma: no cover - never runs
        raise AssertionError("the model must not run on the replay path")

    with replaying(), pytest.raises(CanaryInferenceError, match="_learned_scorer"):
        model_inference(_learned_scorer, {})


# -- The taxonomy ---------------------------------------------------------------


def test_the_refusal_is_its_own_line_of_the_contract() -> None:
    # A deployment can be perfectly pinned, GPU-free and bit-reproducible
    # and still let a learned component reach the replay un-materialized,
    # and the repairs differ — so a caller halting dreaming must be able to
    # tell this break from the others at the ``except``.
    assert issubclass(CanaryInferenceError, CanaryError)
    for other in (
        CanaryImageError,
        CanaryDeviceError,
        CanaryReproducibilityError,
        CanaryReplayScoreError,
    ):
        assert not issubclass(CanaryInferenceError, other)
        assert not issubclass(other, CanaryInferenceError)


# -- The wiring: the replay runs under the guard --------------------------------


def test_a_model_inference_call_made_during_the_replay_is_rejected() -> None:
    # The end-to-end refusal: a tree node that tries to compute its score
    # through the seam mid-replay — §15's un-materialized learned component
    # — is rejected out of :func:`replay_pair` itself, and the guard was
    # observed on (the node found itself on the replay path).
    scorer = _Scorer()
    observed: list[bool] = []
    pair = _pair_with_unmaterialized_node(scorer, observed)
    with pytest.raises(CanaryInferenceError, match="replay path"):
        replay_pair(pair)
    assert observed == [True]
    assert scorer.calls == []


def test_the_composed_replay_is_guarded_too() -> None:
    # The composed spelling delegates to the same function, so a caller
    # holding the service gets the same refusal by construction — no
    # nightly runner can reach an unguarded replay through this package.
    scorer = _Scorer()
    observed: list[bool] = []
    pair = _pair_with_unmaterialized_node(scorer, observed)
    service = CanaryService()
    with pytest.raises(CanaryInferenceError, match="replay path"):
        service.replay.pair(pair)
    assert scorer.calls == []


def test_a_clean_replay_still_replays_to_its_frozen_score() -> None:
    # The guard is an assertion channel, not a data flow: it reads no value
    # into the score and contributes none to it, so a pair of pure stored
    # floats replays to exactly the score its bytes sum to, and the mark is
    # gone once the replay has returned — the guard refuses, it does not
    # perturb.
    result = replay_pair(_pair(score=EXPECTED_SCORE))
    assert result.score == EXPECTED_SCORE
    assert result.within_tolerance is True
    assert is_replaying() is False


# -- The composed component carries the refusal ---------------------------------


def test_the_composed_service_carries_the_refusal_beside_the_replay(
    canary_env: dict[str, str],
) -> None:
    # Feature 146 through the composed component: one value carries the
    # category's guard beside the replay it guards, so a caller holding the
    # composed canary reaches the seam without importing submodules by name
    # — a refusal reachable only by import is a refusal the factory's scan
    # cannot discover.
    service = CanaryService(env=canary_env)
    assert isinstance(service.inference, ModelInference)
    # ... and the replay is still its own verb, unchanged.
    assert service.replay.pair(_pair()).score == EXPECTED_SCORE


def test_the_facade_delegates_off_the_replay_path() -> None:
    scorer = _Scorer(value=0.9)
    service = CanaryService()
    assert service.inference.call(scorer, {"features": 1}) == 0.9
    assert scorer.calls == [(({"features": 1},), {})]


def test_the_facade_refuses_on_the_replay_path() -> None:
    scorer = _Scorer()
    service = CanaryService()
    with service.inference.replaying():
        assert service.inference.is_replaying() is True
        with pytest.raises(CanaryInferenceError, match="replay path"):
            service.inference.call(scorer)
    assert service.inference.is_replaying() is False
    assert scorer.calls == []


def test_the_facade_agrees_with_the_functions() -> None:
    # One provenance: the facade is one call to the function that owns the
    # behaviour, so the composed spelling and the import spelling cannot
    # disagree about what "the replay path" means.
    service = CanaryService()
    scorer = _Scorer(value=0.125)
    assert service.inference.call(scorer) == model_inference(scorer) == 0.125
    with replaying(), pytest.raises(CanaryInferenceError):
        service.inference.call(scorer)
