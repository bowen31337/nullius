"""Feature 249 — the committed pick at termination — in the member's own suite.

app_spec.xml, "Replay Engine", feature 249: *System requires the committed pick
from the policy at termination, which returns negative infinity when none is
emitted.*  The member's suite pins the requirement and its refusals over a
hand-rolled double; the repository-level wiring suite
(``tests/replay/test_pick_wiring.py``) pins the duck-typed seam against the
policy-runtime member's real :class:`~policy_runtime.EpisodeCommit` — the door
the requirement reads — because a member never imports another member.

The doubles below are deliberately *duck-typed and minimal*, because the
requirement reads each collaborator through exactly one surface and nothing
else — the shape the module promises:

* a **stub commit record** — the episode's door: one ``commit(node_id)`` write
  (restating feature 222's one-act cardinality only as far as the tests need
  it), and the one verb the requirement reads, ``terminate()``, which freezes
  and snapshots exactly as the real record does — idempotent, answering a
  frozen read that carries the pick;
* an **emitted pick** — the value the policy emitted, carrying a node id and
  nothing else, so a test can pin that the requirement hands the scorer the
  pick *whole* rather than unwrapping or re-validating it (the node id's
  validity is feature 222's law, and a second statement here would be a
  second place it could drift);
* a **scorer** — the replay's own arithmetic curried to the pick, handed in
  as a callable exactly as the driver wires it.  Several tests need a scorer
  that *would betray itself if called on a miss*, so the miss-path scorer
  below raises ``AssertionError`` the moment it is called.
"""

from __future__ import annotations

from typing import Any

import pytest
from replay import (
    NON_COMMITTING_SCORE,
    ReplayEngine,
    ReplayPickError,
    TerminalPick,
    committed_pick,
)

# ---------------------------------------------------------------------------
# The doubles
# ---------------------------------------------------------------------------


class EmittedPick:
    """The pick a policy emitted — a node id, and nothing else.

    The requirement hands this to the scorer *whole*: it does not unwrap the
    node id, does not validate it, and does not read it at all.  Carrying
    only the id keeps that testable — there is nothing else here to read —
    and ``identity`` lets a test assert the scorer received this very object.
    """

    __slots__ = ("identity", "node_id")

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.identity = object()  # an identity marker no equal-looking pick shares


class FrozenRead:
    """The termination read — the frozen value the record's ``terminate()``
    answers.

    Carries ``pick`` and nothing else: the one attribute the requirement
    reads off the read, ``None`` for the miss and the emitted pick for the
    commit.  A read with *no* ``pick`` at all is the malformed carrier a
    test below refuses, so this double always carries the attribute — the
    shape the real termination always answers.
    """

    __slots__ = ("pick",)

    def __init__(self, pick: Any) -> None:
        self.pick = pick


class CommitDoor:
    """The episode's commit record — the door the requirement reads at
    termination.

    Restates feature 222's protocol only as far as these tests need it: one
    commit naming one node, a refusal for a second, and the idempotent
    ``terminate()`` that freezes the door and snapshots the pick into a
    frozen read.  ``terminated`` and ``terminate_calls`` are observable so a
    test can pin both halves of the act's contract — that the requirement
    *does* terminate (the read is the requirement's own moment) and that a
    *refused* ask terminates nothing (the door is still open afterwards).
    """

    def __init__(self) -> None:
        self._pick: Any = None
        self.terminated = False
        self.terminate_calls = 0

    def commit(self, node_id: str) -> EmittedPick:
        if self.terminated:
            raise AssertionError("a commit landed after termination")
        if self._pick is not None:
            raise AssertionError("an episode commits once")
        self._pick = EmittedPick(node_id)
        return self._pick

    def terminate(self) -> FrozenRead:
        self.terminated = True
        self.terminate_calls += 1
        return FrozenRead(pick=self._pick)


def ir_scorer(pick: Any) -> float:
    """A scorer standing in for the replay's own arithmetic — §10.3's
    ``score(pick, book, epoch, revealed, rounds)`` curried to the pick.

    Returns a number derived from the pick's node id so a test can see *which*
    pick reached it, and nothing else: the currying (the book, the epoch, the
    revealed set) is the caller's business, which is the point of taking a
    callable rather than a number.
    """
    return {"m1": 0.5, "m1x": 1.25}.get(getattr(pick, "node_id", None), 0.0)


def betraying_scorer(pick: Any) -> float:
    """A scorer that betrays the miss path the moment it is called.

    The miss must answer ``-inf`` **with the scorer never called at all** —
    no value to pass, no call to make, no seam through which a fabricated
    pick could reach the arithmetic.  A scorer that raises when called is
    the loudest possible pin of that property.
    """
    raise AssertionError("the scorer was called on a pick that was never emitted")


# ---------------------------------------------------------------------------
# The made pick
# ---------------------------------------------------------------------------


def test_a_made_pick_is_handed_to_the_scorer_whole() -> None:
    # The requirement's happy path: the policy emitted one pick, the
    # termination read carries it, and the scorer is called once — with the
    # pick *whole*, the very object the record emitted (not an unwrapped node
    # id, not a copy).  The answer carries the pick beside the score it
    # earned, which is the pair the store's row is shaped around.
    door = CommitDoor()
    emitted = door.commit("m1x")
    seen: list[Any] = []

    def scorer(pick: Any) -> float:
        seen.append(pick)
        return 1.25

    answer = committed_pick(door, scorer)
    assert seen == [emitted], "the scorer was not handed the emitted pick whole"
    assert answer.pick is emitted
    assert answer.score == 1.25
    assert answer.committed is True


def test_the_requirement_performs_the_termination_read() -> None:
    # *At termination* is the requirement's own moment: it does not read the
    # record's live state, it performs the termination read through the one
    # verb the record exposes — so the door is closed by the act, exactly as
    # docs §10.1's ``pick = policy.commit()`` is the replay loop's last act.
    # Afterwards the door refuses a commit (feature 222's one-way door, read
    # from this side), and requiring again answers an equal value.
    door = CommitDoor()
    door.commit("m1")
    answer = committed_pick(door, ir_scorer)
    assert door.terminated is True
    assert door.terminate_calls == 1
    # The read is idempotent: a second requirement of the same terminated
    # episode answers an equal TerminalPick — two reads of one frozen
    # decision, not a re-decision.
    again = committed_pick(door, ir_scorer)
    assert again == answer
    with pytest.raises(AssertionError):
        door.commit("m1x")


def test_the_requirement_reads_one_verb_off_the_record() -> None:
    # The one-verb stance: the record is read through ``terminate()`` and the
    # read through ``pick``, and nothing else.  A record whose every other
    # attribute explodes if touched pins that — the requirement cannot be
    # reading the live pick, the question, the tree or anything but the two
    # surfaces it names.
    class TouchyDoor(CommitDoor):
        def __getattr__(self, name: str) -> Any:
            if name.startswith("_") or name in ("commit", "terminate"):
                raise AttributeError(name)
            raise AssertionError(f"the requirement read {name!r} off the record")

    door = TouchyDoor()
    door.commit("m1")
    answer = committed_pick(door, ir_scorer)
    assert answer.score == 0.5


def test_the_pick_need_not_be_revealed() -> None:
    # Feature 222's deliberate non-law, read on the replay's side: a commit
    # names a node, it does not read one, and this requirement consults no
    # prefix at all — a pick naming a node no walk has revealed (or no tree
    # holds) is routed to the scorer exactly as any other.  The out-of-sample
    # score will punish a blind pick; that is the honest outcome, not a
    # refusal this module invented.  The revealed set is the scorer's
    # business, curried by the caller.
    door = CommitDoor()
    door.commit("never-revealed-anywhere")
    answer = committed_pick(door, lambda pick: -3.0)
    assert answer.committed is True
    assert answer.score == -3.0


def test_the_answer_is_frozen() -> None:
    # An answer that could move would be a score that changed after it was
    # read — the replay writes one row and one log record from one answer,
    # and the row, the record and the value must not drift.
    door = CommitDoor()
    door.commit("m1")
    answer = committed_pick(door, ir_scorer)
    with pytest.raises(Exception) as raised:
        answer.score = 99.0  # type: ignore[misc]
    assert type(raised.value).__name__ == "FrozenInstanceError"


# ---------------------------------------------------------------------------
# The miss
# ---------------------------------------------------------------------------


def test_the_miss_is_a_score_not_a_refusal() -> None:
    # The feature's second clause and its whole point: a policy that emitted
    # no pick is *scored* — the total order's floor — never rejected.  The
    # answer carries the pick absent (not fabricated: a decision never made
    # stays distinguishable from one that was) and the score present, so the
    # row this value shapes is always a completed scoring.
    door = CommitDoor()
    answer = committed_pick(door, ir_scorer)
    assert answer.pick is None
    assert answer.committed is False
    assert answer.score == float("-inf")
    assert answer.score == NON_COMMITTING_SCORE


def test_the_scorer_is_never_called_on_the_miss() -> None:
    # Taking a callable rather than a number is the design point: on the miss
    # there is no value to pass and no call to make — no seam through which a
    # fabricated pick could reach the arithmetic.  A scorer that raises the
    # moment it is called is the loudest pin of "never called at all".
    door = CommitDoor()
    answer = committed_pick(door, betraying_scorer)
    assert answer.score == NON_COMMITTING_SCORE


def test_the_miss_ranks_below_every_committing_score_and_ties_with_every_miss() -> None:
    # Why −∞ rather than a refusal or a null: the miss stays *in* the
    # comparison — deterministically below every committing policy's score
    # however bad that pick was (a revision that commits badly still beats
    # one that never commits), and equal to every other miss (the argmax
    # reads two non-committers as equally last rather than ordering them by
    # accident).  An exception would take the policy out of the comparison
    # into the crashed slot; None or NaN is not a score at all.
    door = CommitDoor()
    miss = committed_pick(door, ir_scorer)
    worst = CommitDoor()
    worst.commit("m1")
    terribly = committed_pick(worst, lambda pick: -1.0e308)
    assert miss.score < terribly.score
    other = CommitDoor()
    assert miss.score == committed_pick(other, ir_scorer).score


def test_the_floor_is_the_one_the_documents_spell() -> None:
    # The named constant is the floor itself: IEEE negative infinity, the
    # value that compares below every real score and ties with itself.  The
    # policy-runtime member spells the same value under the same name
    # (feature 222); the wiring suite pins the two spellings equal, and this
    # test pins the member's own.
    assert NON_COMMITTING_SCORE == float("-inf")
    import math

    assert math.isinf(NON_COMMITTING_SCORE) and NON_COMMITTING_SCORE < 0


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_a_non_callable_scorer_is_refused_and_terminates_nothing() -> None:
    # The ask's wiring is refused first, before the record is touched: a
    # requirement that terminated the episode and then discovered it had no
    # scorer to route would have spent the one-way door on an ask it could
    # not answer.  A refused ask terminates nothing — pinned by committing
    # *after* the refusal: the door was never closed, and a caller that fixes
    # its wiring can still ask.
    door = CommitDoor()
    with pytest.raises(ReplayPickError) as raised:
        committed_pick(door, "not callable")
    assert "scorer" in str(raised.value)
    assert door.terminated is False, "a refused ask terminated the episode"
    # The door is still open: the one commit lands, and a re-require with the
    # wiring fixed answers the made pick.
    door.commit("m1x")
    answer = committed_pick(door, ir_scorer)
    assert answer.score == 1.25
    assert answer.committed is True


def test_a_carrier_with_no_termination_read_is_refused() -> None:
    # The requirement performs the termination read through exactly one verb,
    # and a carrier with no such verb is not an episode's commit record —
    # there is no act to take through it.  The repair is the argument: hand
    # the record, not something else.
    class NotARecord:
        pass

    with pytest.raises(ReplayPickError) as raised:
        committed_pick(NotARecord(), ir_scorer)
    assert "terminate" in str(raised.value)


def test_a_frozen_read_handed_where_the_record_belongs_is_refused() -> None:
    # The one-seam law: the requirement is the *act* that takes the
    # termination read, and a frozen read someone else already took answers
    # itself — handing it in where the record belongs is refused as what it
    # is, never silently scored.  A second spelling that accepted the frozen
    # value would be a second place the terminal act could be skipped.
    door = CommitDoor()
    door.commit("m1")
    frozen = door.terminate()
    with pytest.raises(ReplayPickError) as raised:
        committed_pick(frozen, ir_scorer)  # type: ignore[arg-type]
    assert "terminate" in str(raised.value)


def test_a_read_that_cannot_say_is_refused_not_scored_as_a_miss() -> None:
    # The dangerous case: a termination read carrying no ``pick`` at all is a
    # different fact from ``pick is None`` (the miss), and the two have
    # different repairs.  Scoring the first as the second would hand broken
    # wiring −∞ — and a caller skipping "the non-committing policy" would be
    # silently skipping every record it failed to read.
    class CannotSay:
        def terminate(self) -> CannotSay:
            return self  # a read with no `pick` attribute at all

    with pytest.raises(ReplayPickError) as raised:
        committed_pick(CannotSay(), ir_scorer)
    assert "pick" in str(raised.value)
    # A read answering nothing at all is the same refusal, not a miss.
    class AnswersNothing:
        def terminate(self) -> None:
            return None

    with pytest.raises(ReplayPickError):
        committed_pick(AnswersNothing(), ir_scorer)


def test_a_raising_termination_read_is_translated_at_the_seam() -> None:
    # A record whose ``terminate()`` raises is translated into this member's
    # vocabulary and chained to the carrier's own refusal — whatever class
    # the record raised belongs to the record's member, and a caller catching
    # the replay's base class must still catch an episode whose termination
    # could not be read.
    class ExplodingRecord:
        def terminate(self) -> Any:
            raise RuntimeError("the record's own refusal")

    with pytest.raises(ReplayPickError) as raised:
        committed_pick(ExplodingRecord(), ir_scorer)
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_a_raising_scorer_propagates_unchanged() -> None:
    # The scorer is the replay's own arithmetic (features 250/256's), and its
    # failure is not this seam's to translate: a scorer that raises speaks
    # for itself, the same stance feature 222 takes on its side of the seam.
    # The ask was well formed, so the record *was* terminated — the read
    # happened; the arithmetic failed after it.
    door = CommitDoor()
    door.commit("m1")

    def exploding(pick: Any) -> float:
        raise ValueError("the arithmetic's own failure")

    with pytest.raises(ValueError):
        committed_pick(door, exploding)
    assert door.terminated is True


def test_every_refusal_is_a_pick_error_and_not_a_round_error() -> None:
    # The sibling split: the terminal requirement's malformed ask is
    # `ReplayPickError`, deliberately not `ReplayRoundError` — the loop's ask
    # and the terminal ask are different repairs, and a caller catching the
    # loop's failures must not silently skip the refusal that says the
    # terminal seam was handed no scorer.
    from replay import ReplayRoundError

    with pytest.raises(ReplayPickError) as raised:
        committed_pick(CommitDoor(), None)
    assert not isinstance(raised.value, ReplayRoundError)
    with pytest.raises(ReplayPickError) as raised:
        committed_pick(object(), ir_scorer)
    assert not isinstance(raised.value, ReplayRoundError)


# ---------------------------------------------------------------------------
# The composed spelling
# ---------------------------------------------------------------------------


def test_the_facade_delegates_to_the_requirement() -> None:
    # The composed spelling is a verb on 245's stateless facade, the law the
    # package states (one component per member name; the feature adds a verb,
    # not a component): a caller holding the component and a caller holding
    # the free function get the same answer over the same record.
    door = CommitDoor()
    door.commit("m1x")
    through_component = ReplayEngine().pick(door, ir_scorer)
    direct = committed_pick(door, ir_scorer)
    assert through_component == direct
    assert through_component.score == 1.25


def test_the_facade_refuses_what_the_requirement_refuses() -> None:
    # There is no route around the refusals by holding the composed
    # component: the facade's verb is a spelling of the member's act, not a
    # second implementation, so a non-callable scorer is refused through the
    # component exactly as it is refused directly — and, the same load-bearing
    # property, before the record is touched.
    door = CommitDoor()
    with pytest.raises(ReplayPickError):
        ReplayEngine().pick(door, "not callable")
    assert door.terminated is False
    with pytest.raises(ReplayPickError):
        ReplayEngine().pick("not a record either", ir_scorer)


def test_the_answer_type_is_the_pairs_the_store_shapes() -> None:
    # The answer is the pair migration 0109 legislates for the replay_score
    # row — the pick absent-able, the score always present — as one frozen
    # value, so feature 255's writer and the §913 log record consume this
    # object rather than re-deriving the pair.  Both halves constructible as
    # a value: the miss and the made pick are first-class answers, and the
    # `committed` flag is derived, never stored.
    miss = TerminalPick(pick=None, score=NON_COMMITTING_SCORE)
    assert miss.committed is False
    made = TerminalPick(pick=EmittedPick("m1"), score=0.5)
    assert made.committed is True
    assert made != miss
