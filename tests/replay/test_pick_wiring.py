"""Feature 249 in the assembled system — the terminal requirement over the
real commit record.

app_spec.xml, "Replay Engine", feature 249: *System requires the committed
pick from the policy at termination, which returns negative infinity when
none is emitted.*  The member's own suite (``packages/replay/tests/test_pick.py``)
pins the requirement and its refusals over a hand-rolled double; this suite
pins the **duck-typed seam** against the two objects the composed system
actually produces — the policy-runtime member's real
:class:`~policy_runtime.EpisodeCommit` (the door the requirement reads,
opened through feature 222's own factory over a real
:class:`~policy_runtime.PolicyQuestion`) and the composed component's
``pick`` verb — which is what a member's suite structurally cannot do:

* **the requirement reads the real record** — feature 222's door, with its
  one-way commit, its idempotent ``terminate()`` and its frozen
  :class:`~policy_runtime.Termination` read; this is the only place the two
  members' halves of one terminal act are checked against each other, the
  replay's requirement against the policy runtime's protocol;
* **the two floors are one value** — the miss is ``-inf`` in both members'
  spellings (``replay.NON_COMMITTING_SCORE`` and
  ``policy_runtime.NON_COMMITTING_SCORE``), pinned equal here because only a
  suite that may import both members can say so;
* **the full §10.1 shape runs end to end** — feature 248's loop returns the
  revealed set, and the requirement's scorer is curried over it, which is
  the currying the loop's return exists for.

**Nothing here asserts ``isinstance`` or ``pytest.raises(<canonical class>)``
across the composition seam.**  The module loader imports each workspace
member under a synthetic name (``_nullius_scanned_<name>``) and re-executes
it, so the ``ReplayPickError`` the composed component raises and the
``EpisodeCommit`` the wiring builds are *second* class objects with the same
names — an ``isinstance`` across that seam is False even though nothing is
wrong.  The checks below name the behaviour and compare ``type(exc).__name__``,
the same answer ``tests/replay/test_rounds_wiring.py`` gives for the same
wrinkle.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

policy_runtime = pytest.importorskip("policy_runtime")
CampaignTree = policy_runtime.CampaignTree
PolicyQuestion = policy_runtime.PolicyQuestion
episode_commit = policy_runtime.episode_commit

REPO_ROOT = Path(__file__).resolve().parents[2]

seat = importlib.import_module("app.modules.policy-runtime")


def create_app():
    from app.module_loader import create_app

    return create_app()


@pytest.fixture(scope="module")
def campaign_tree() -> CampaignTree:
    """The real campaign tree a deployment would hold — two themes, one branch.

    Built through the policy-runtime member's *public* constructor, the same
    fixture shape ``tests/replay/test_rounds_wiring.py`` walks: the point of
    the requirement below is that this member's duck-typed read matches the
    record the policy-runtime member actually fronts over that tree.
    """
    return CampaignTree.freeze(
        {
            "r-mom": (None, 0, {"depth": 0, "r2_insample": None}),
            "m1": ("r-mom", 1, {"parent_id": "r-mom", "depth": 1, "r2_insample": 0.20}),
            "m1x": ("m1", 2, {"parent_id": "m1", "depth": 2, "r2_insample": 0.51}),
            "r-event": (None, 0, {"depth": 0, "r2_insample": None}),
        }
    )


@pytest.fixture
def component():
    """The composed replay component, reached the way a runtime reaches it.

    Through the factory, never by importing the member: the component is the
    application's object, and the verb under test is the composed spelling of
    the terminal requirement.
    """
    return create_app().get("replay")


def _frontier_select(question: PolicyQuestion) -> list[str]:
    """A stub policy over the real question — the open-frontier selector.

    The same closure ``tests/replay/test_rounds_wiring.py`` drives the loop
    with, restated here so the end-to-end test below runs §10.1's whole
    shape: the loop over the real tree and question, then the terminal
    requirement over the real commit record.
    """
    revealed = sorted(question.observed())
    edges = {"r-mom": "m1", "m1": "m1x"}
    return [
        node_id
        for node_id in revealed
        if node_id in edges and edges[node_id] not in revealed
    ]


# ---------------------------------------------------------------------------
# The seam against the real record
# ---------------------------------------------------------------------------


def test_the_composed_component_requires_the_real_records_pick(
    campaign_tree, component
) -> None:
    # The whole seam: feature 222's door opened over a real PolicyQuestion,
    # the policy's one commit landed through it, and the composed component's
    # `pick` performs the termination read and answers the pair — the real
    # CommittedPick beside the score the handed-in scorer computed from it.
    # The scorer receives the pick the record emitted whole, node id and all,
    # which is what features 250/256's arithmetic will read off it.
    record = episode_commit(PolicyQuestion(campaign_tree))
    record.commit("m1x")
    seen: list[str] = []

    def scorer(pick) -> float:
        seen.append(pick.node_id)
        return 1.25

    answer = component.pick(record, scorer)
    assert seen == ["m1x"]
    assert answer.pick.node_id == "m1x"
    assert answer.score == 1.25
    assert answer.committed is True


def test_the_real_non_committing_policy_scores_negative_infinity(
    campaign_tree, component
) -> None:
    # The feature's second clause over the real door: a policy that emitted
    # no pick — the record never committed — is *scored*, not refused, and
    # the score is the total order's floor.  The scorer would betray itself
    # if called (it raises), so this also pins the never-called property over
    # the real miss path: no fabricated pick reaches the arithmetic.
    record = episode_commit(PolicyQuestion(campaign_tree))

    def betraying(pick) -> float:
        raise AssertionError("the scorer was called on a pick that was never emitted")

    answer = component.pick(record, betraying)
    assert answer.pick is None
    assert answer.committed is False
    assert answer.score == float("-inf")
    assert answer.score == policy_runtime.NON_COMMITTING_SCORE


def test_the_two_members_floors_are_one_value() -> None:
    # One fact, two members, one value: the policy-runtime member spells the
    # floor feature 222's sentence demands ("omitting scores −inf") and the
    # replay member spells it again for its own answer (a member never
    # imports another member), so the wiring suite — the only place both may
    # be imported — pins the two spellings equal.  A drift here would be two
    # different misses in one comparison.
    replay = importlib.import_module("replay")
    assert replay.NON_COMMITTING_SCORE == policy_runtime.NON_COMMITTING_SCORE
    assert replay.NON_COMMITTING_SCORE == float("-inf")


def test_the_full_replay_shape_loop_then_terminal_pick(
    campaign_tree, component, monkeypatch
) -> None:
    # §10.1 end to end over the real objects: the loop (feature 248) walks
    # the tree until the frontier empties and returns the revealed set; the
    # terminal requirement (249) takes the pick the policy committed through
    # the real door; and the scorer is curried over the revealed set — the
    # currying the loop's return exists for.  The scorer reads both the pick
    # it was handed and the revealed set it closed over, which is the whole
    # shape of `score(pick, book, epoch, revealed, rounds)` minus the pieces
    # later features own.
    monkeypatch.setattr(seat, "campaign_tree_component", lambda app=None: campaign_tree)
    question = PolicyQuestion(campaign_tree)
    record = episode_commit(question)
    record.commit("m1x")
    revealed = component.run(_frontier_select, question, round_cap=10)
    assert revealed == ("m1", "m1x", "r-event", "r-mom")

    def score(pick) -> float:
        # The replay's arithmetic, curried: the pick's node is in the prefix
        # this walk revealed (it is — m1x was revealed before the commit),
        # and the score is a function of both, never of anything the
        # requirement handed besides the pick.
        assert pick.node_id in revealed
        return {"m1": 0.5, "m1x": 1.25}[pick.node_id]

    answer = component.pick(record, score)
    assert answer.score == 1.25
    assert answer.pick.node_id == "m1x"


# ---------------------------------------------------------------------------
# The refusals, over the real door
# ---------------------------------------------------------------------------


def test_a_refused_ask_leaves_the_real_door_open(campaign_tree, component) -> None:
    # The load-bearing order, pinned over feature 222's real one-way door: a
    # malformed ask (a scorer that is not callable) is refused *before the
    # record is touched*, so the episode is not terminated by a call that
    # never scored it — the commit still lands afterwards, and a re-require
    # with the wiring fixed answers the made pick.  A refusal that had spent
    # the door would freeze the episode with no score and no retry.
    record = episode_commit(PolicyQuestion(campaign_tree))
    with pytest.raises(Exception) as raised:
        component.pick(record, "not callable")
    assert type(raised.value).__name__ == "ReplayPickError"
    assert "scorer" in str(raised.value)
    # The door never closed: the policy's one commit still lands through it.
    record.commit("m1")
    answer = component.pick(record, lambda pick: 0.5)
    assert answer.pick.node_id == "m1"
    assert answer.score == 0.5


def test_a_frozen_read_handed_where_the_record_belongs_is_refused(
    campaign_tree, component
) -> None:
    # One seam, over the real objects: the requirement is the act that takes
    # the termination read, and feature 222's frozen
    # :class:`~policy_runtime.Termination` — a value that already answers
    # itself, with its own ``score`` routing — handed in where the record
    # belongs is refused as what it is.  There is no second spelling of the
    # terminal act that skips the door.
    record = episode_commit(PolicyQuestion(campaign_tree))
    frozen = record.terminate()
    with pytest.raises(Exception) as raised:
        component.pick(frozen, lambda pick: 0.5)
    assert type(raised.value).__name__ == "ReplayPickError"
    assert "terminate" in str(raised.value)


def test_a_read_that_cannot_say_is_refused_not_scored_as_a_miss(component) -> None:
    # The dangerous case over the composed component: a carrier whose
    # termination read carries no ``pick`` at all cannot say whether a pick
    # was emitted, and scoring it as the miss would hand broken wiring −∞ —
    # hiding a broken caller from every world in the pool.  Refused, in the
    # member's vocabulary, naming the read.
    class CannotSay:
        def terminate(self) -> CannotSay:
            return self  # a read with no `pick` attribute at all

    with pytest.raises(Exception) as raised:
        component.pick(CannotSay(), lambda pick: 0.5)
    assert type(raised.value).__name__ == "ReplayPickError"
    assert "pick" in str(raised.value)


def test_a_raising_termination_read_is_translated_at_the_seam(component) -> None:
    # A record whose ``terminate()`` raises is translated into the replay
    # member's vocabulary and chained to the carrier's own refusal, so a
    # caller catching the replay path's base class still catches an episode
    # whose termination could not be read — whatever class the record raised
    # belongs to the record's member.
    class ExplodingRecord:
        def terminate(self):
            raise RuntimeError("the record's own refusal")

    with pytest.raises(Exception) as raised:
        component.pick(ExplodingRecord(), lambda pick: 0.5)
    assert type(raised.value).__name__ == "ReplayPickError"
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_a_raising_scorer_propagates_unchanged(campaign_tree, component) -> None:
    # The scorer is the replay's own arithmetic and its failure is not the
    # terminal seam's to translate: over the real record, a scorer that
    # raises speaks for itself — the same stance the policy-runtime member
    # takes for a raising scorer on its side of the seam (feature 222).
    record = episode_commit(PolicyQuestion(campaign_tree))
    record.commit("m1x")

    def exploding(pick) -> float:
        raise ValueError("the arithmetic's own failure")

    with pytest.raises(ValueError):
        component.pick(record, exploding)


def test_the_real_door_closes_behind_the_requirement(campaign_tree, component) -> None:
    # The other half of the act's contract, over the real one-way door: a
    # requirement that *did* run terminated the episode, and feature 222's
    # door then refuses a commit landing after it — the read is the
    # requirement's own moment (docs §10.1's ``pick = policy.commit()`` is
    # the replay's last act), and a pick landing after it would be a pick the
    # score never saw.  The exception is the record's own class, unchanged.
    record = episode_commit(PolicyQuestion(campaign_tree))
    record.commit("m1x")
    answer = component.pick(record, lambda pick: 1.25)
    assert answer.score == 1.25
    with pytest.raises(Exception) as raised:
        record.commit("m1")
    assert type(raised.value).__name__ == "PolicyCommitError"
