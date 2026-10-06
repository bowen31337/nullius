"""Feature 4 of additions_spec_operator_surfaces.xml — scoring one (candidate,
bootstrap world) pair.

*System scores one (candidate policy, bootstrap world) pair with
orchestrator._bootstrap_eval.score_on_world(candidate_source, world, *,
round_cap) and returns a carrier with .pick and .score, the shape
dreaming.sweep_candidates expects of its evaluator.*

One test per claim the feature sentence makes:

* **a committing candidate** — a tiny source that reveals the root, then the
  root's neighbours, then commits whichever of the observed cells carries
  the highest held-out R², scores that node's own ``world.label(...)
  .r2_holdout`` and carries it as the pick.
* **a non-committing candidate** — a tiny source that keeps answering the
  root forever and never calls ``question.commit``: the pick is ``None``
  and the score is :data:`replay.NON_COMMITTING_SCORE`.
* **a candidate that fails screening** — a source with no ``commit()`` call
  at all, refused by :func:`policy_runtime.screen_policy` before anything
  runs, raising :class:`~orchestrator._policy.PolicyLoadError` naming the
  admission reason.
* **determinism** — the same source, world and round cap score the same
  pick and the same score twice.

Every candidate source's ``select`` routes its return value through a
``.commit(...)`` call on a throwaway sink — the same decoy
``orchestrator/tests/test_policy.py`` uses — purely so
:func:`policy_runtime.screen_policy`'s commit-reachability check (which
looks for the attribute name ``commit``, not for the object it is called
on) finds one on every path; only the committing candidate's real
``question.commit(...)`` call is semantically a commit.

Tests persist one bootstrap world into a tmp SQLite store through the real
:class:`bootstrap.BootstrapPool`, run real source text through the real
:func:`policy_runtime.screen_policy` gate and :func:`policy_runtime.guard_policy`
guard, and read the real :class:`bootstrap.HyperparameterWorld`'s ``label``
for the expected score — no mock stands in for either. No test opens a
network connection or reads a real credential, and no state is kept at
module scope across tests, so the suite passes under pytest-xdist.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bootstrap import BootstrapPool, HyperparameterWorld
from orchestrator._bootstrap_eval import score_on_world
from orchestrator._policy import POLICY_LOAD_CODE, PolicyLoadError
from policy_runtime import CommittedPick
from replay import NON_COMMITTING_SCORE, TerminalPick

ROUND_CAP = 5

#: Every return routes through ``sink.commit(...)`` so the source carries at
#: least one ``.commit(...)`` call on every path (see the module docstring).
#: Round 1 reveals the root; round 2 reveals the root's neighbours; round 3
#: commits whichever observed cell has the highest held-out R² and
#: terminates. The two booleans are module state, re-initialised fresh on
#: every import (:func:`orchestrator._bootstrap_eval.score_on_world` execs a
#: brand-new module per call), so two calls over one source are independent.
COMMITS_BEST_SOURCE = """
class _Sink:
    def commit(self, value):
        return value


sink = _Sink()
_state = {"revealed_root": False, "revealed_neighbours": False}


def select(question):
    if not _state["revealed_root"]:
        _state["revealed_root"] = True
        return sink.commit(question.legal_roots())
    if not _state["revealed_neighbours"]:
        _state["revealed_neighbours"] = True
        root_id = question.legal_roots()[0]
        return sink.commit(question.legal_actions(root_id))
    observed = question.observed()
    ranked = sorted(observed, key=lambda node_id: -observed[node_id].r2_holdout)
    question.commit(ranked[0])
    return sink.commit([])
"""

#: Always answers the root, forever — a non-empty batch every round, so the
#: loop runs to the round cap rather than stopping on an empty answer, and
#: ``question.commit`` is never reached: the sink's own ``.commit(...)`` call
#: satisfies the static gate's reachability check without ever naming the
#: question's real commit door.
NEVER_COMMITS_SOURCE = """
class _Sink:
    def commit(self, value):
        return value


sink = _Sink()


def select(question):
    return sink.commit(question.legal_roots())
"""

#: No ``.commit(...)`` call anywhere in the source — refused by
#: policy_runtime.screen_policy's mandatory-commit check before anything is
#: imported or run (the same shape as test_policy.py's own NO_COMMIT_SOURCE).
FAILS_SCREENING_SOURCE = "def select(question):\n    return question.legal_roots()\n"


def _persisted_world(tmp_path: Path) -> HyperparameterWorld:
    """One bootstrap world, persisted into a tmp SQLite store and read back."""
    database_url = f"sqlite:///{tmp_path / 'pool.db'}"
    pool = BootstrapPool(database_url)
    persisted = pool.persist_worlds(count=40, pool_seed=20991231)
    return pool.world(persisted.worlds[0].world_id)


def test_committing_candidate_scores_the_ground_truth_of_its_pick(tmp_path: Path) -> None:
    world = _persisted_world(tmp_path)

    result = score_on_world(COMMITS_BEST_SOURCE, world, round_cap=ROUND_CAP)

    assert isinstance(result, TerminalPick)
    assert isinstance(result.pick, CommittedPick)
    root = world.canonical_node()
    candidates = {root, *world.legal_moves(root)}
    expected_pick = min(
        candidates, key=lambda node_id: (-world.label(node_id).r2_holdout, node_id)
    )
    assert result.pick.node_id == expected_pick
    assert result.score == world.label(expected_pick).r2_holdout


def test_never_committing_candidate_scores_non_committing_score(tmp_path: Path) -> None:
    world = _persisted_world(tmp_path)

    result = score_on_world(NEVER_COMMITS_SOURCE, world, round_cap=ROUND_CAP)

    assert result.pick is None
    assert result.score == NON_COMMITTING_SCORE
    assert result.score == float("-inf")


def test_candidate_that_fails_screening_raises_policy_load_error(tmp_path: Path) -> None:
    world = _persisted_world(tmp_path)

    with pytest.raises(PolicyLoadError) as excinfo:
        score_on_world(FAILS_SCREENING_SOURCE, world, round_cap=ROUND_CAP)

    message = str(excinfo.value)
    assert POLICY_LOAD_CODE in message
    assert "unreachable-commit" in message


def test_same_source_world_and_round_cap_score_the_same_pick_and_score_twice(
    tmp_path: Path,
) -> None:
    world = _persisted_world(tmp_path)

    first = score_on_world(COMMITS_BEST_SOURCE, world, round_cap=ROUND_CAP)
    second = score_on_world(COMMITS_BEST_SOURCE, world, round_cap=ROUND_CAP)

    assert first.pick.node_id == second.pick.node_id
    assert first.score == second.score
