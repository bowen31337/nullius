"""Feature 222, the terminal commit — one call naming one node, and −∞ for
the policy that never makes it.

app_spec.xml, "Exploration Policy Runtime", feature 222: *System requires a
commit call naming one node at termination, which returns negative infinity
for a non-committing policy.*  docs/nullius-tech-architecture.md §598 spells
the law in the API listing (``question.commit(node_id)  # REQUIRED; omitting
scores −inf``), §478 shows the call site (the replay loop's last act after the
rounds have run), and docs/alpha-engine-prd.md §438 gives the sentence the
feature hangs on: *"``commit()`` is mandatory. A policy that terminates
without committing scores ``−∞``."*

The invariants these tests pin are the ones the guarantee depends on:

* **the commit names exactly one node** — a call carrying no node, several
  nodes, or a value that is not a name is refused
  (:class:`~policy_runtime.PolicyCommitError`), naming what it carried;
* **the address seam is the tree's** — a node the tree does not hold is
  refused by the same :class:`~policy_runtime.PolicyAddressError` ``reveal``
  raises, from the same seam, and a refused attempt commits nothing (the one
  call a policy has is still there to make after a fumble);
* **the terminal act is one act** — a second commit is refused naming the
  pick already made, and the door is closed after ``terminate()`` has read
  the episode;
* **the miss is a score, not an error** — an episode that terminates
  uncommitted is a :class:`~policy_runtime.Termination` with no pick whose
  :meth:`~policy_runtime.Termination.score` answers
  :data:`~policy_runtime.NON_COMMITTING_SCORE` *without the scorer being
  called at all*, which is what keeps a non-committing revision inside the
  dreaming loop's comparison, ranked last, instead of dropping out of it
  the way a raised exception or a NaN would.

The headline case is the one the feature names: a policy that terminates
without committing scores −∞ — below a committing policy's disaster, never
refused.
"""

from __future__ import annotations

import dataclasses
import math

import pytest
from policy_runtime import (
    NON_COMMITTING_SCORE,
    CampaignTree,
    CommittedPick,
    PolicyAddressError,
    PolicyCommitError,
    PolicyQuestion,
    PolicyRuntimeError,
    episode_commit,
)

# ---------------------------------------------------------------------------
# CommittedPick — the one node the episode named, as a value
# ---------------------------------------------------------------------------


def test_committed_pick_names_its_node() -> None:
    # The pick is the node the commit call named — the one address the
    # out-of-sample score is computed on and the one field the store's
    # committed_pick column persists.  It carries nothing else: not the
    # node's in-sample reading (the score is sequestered-epoch by
    # construction), not the round, not the reveal set.
    pick = CommittedPick(node_id="n1")
    assert pick.node_id == "n1"


def test_committed_pick_refuses_a_blank_node_id() -> None:
    # The id is the one address a pick carries, and a pick without one names
    # nothing to score — refused at construction, naming the field, the same
    # validation CampaignNode applies to its own id.
    with pytest.raises(PolicyCommitError, match="node_id"):
        CommittedPick(node_id="   ")


def test_committed_pick_refuses_a_non_string_node_id() -> None:
    # ``bool`` is not a name, and neither is a count or a None — a node id is
    # text, and a pick carrying anything else is an address no tree holds.
    with pytest.raises(PolicyCommitError, match="node_id"):
        CommittedPick(node_id=True)  # type: ignore[arg-type]


def test_committed_pick_is_frozen() -> None:
    # A pick is a decision made once at termination, and a pick a caller could
    # move after the fact would not be the pick the score was earned under.
    pick = CommittedPick(node_id="n1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        pick.node_id = "n2"  # type: ignore[misc]


def test_committed_picks_compare_by_their_node() -> None:
    # Two picks naming one node are one pick — the value semantics a replay
    # needs when it keys a ledger or a log by the committed decision.
    assert CommittedPick(node_id="n1") == CommittedPick(node_id="n1")
    assert CommittedPick(node_id="n1") != CommittedPick(node_id="n2")


# ---------------------------------------------------------------------------
# episode_commit — the seam fronts a question, duck-typed
# ---------------------------------------------------------------------------


def test_the_record_fronts_the_canonical_question(question: PolicyQuestion) -> None:
    # The factory over the canonical question of the conftest: the record
    # accepts the episode's one commit through the question's address seam.
    record = episode_commit(question)
    pick = record.commit("n1")
    assert pick == CommittedPick(node_id="n1")
    assert record.pick == pick
    assert record.committed


def test_the_record_fronts_a_duck_typed_question(tree: CampaignTree) -> None:
    # Duck-typed, not ``isinstance``: the module loader imports the member
    # under a synthetic name and re-executes it, so a question this process
    # composed may be a second PolicyQuestion class object, and the record
    # must front it as readily as the member's own.  The demand is the
    # address seam — a public ``tree`` carrying a callable ``node``.
    class _ComposedQuestion:
        def __init__(self, fronted: CampaignTree) -> None:
            self.tree = fronted

    record = episode_commit(_ComposedQuestion(tree))
    assert record.commit("n0") == CommittedPick(node_id="n0")


def test_the_record_refuses_the_bare_tree(tree: CampaignTree) -> None:
    # The tree has ``node`` but no ``tree`` of its own, so handing it where
    # the question belongs is refused as what it is: the commit is an
    # episode's act and the question is where an episode's tree lives.
    with pytest.raises(PolicyCommitError, match="fronts a question"):
        episode_commit(tree)


@pytest.mark.parametrize("not_a_question", ["n1", 7, {"tree": None}, None])
def test_the_record_refuses_a_non_question(not_a_question) -> None:
    # A string, a number, a mapping or a None exposes no address seam, so it
    # names no node a policy could commit to — refused in this module's own
    # vocabulary rather than escaping as an AttributeError.
    with pytest.raises(PolicyCommitError, match="fronts a question"):
        episode_commit(not_a_question)


# ---------------------------------------------------------------------------
# commit — a call naming exactly one node
# ---------------------------------------------------------------------------


def test_commit_names_one_node(question: PolicyQuestion) -> None:
    # The feature's own words: *a commit call naming one node*.  The call
    # returns the pick it made, and the record reads committed from then on.
    record = episode_commit(question)
    pick = record.commit("n1")
    assert pick.node_id == "n1"
    assert record.pick == CommittedPick(node_id="n1")
    assert record.committed is True


def test_commit_refuses_a_call_that_names_no_node(question: PolicyQuestion) -> None:
    # None, a blank string and an empty sequence all name no node — the
    # call's one argument is the node's id, and an argument that is not one
    # names nothing to score.
    for carried in (None, "", "   ", []):
        with pytest.raises(PolicyCommitError, match="exactly one node"):
            episode_commit(question).commit(carried)


def test_commit_refuses_a_call_that_names_several_nodes(question: PolicyQuestion) -> None:
    # A batch is probe_batch's shape, not commit's: a call carrying two ids
    # names no one node, and the refusal says how many it carried.
    with pytest.raises(PolicyCommitError, match="2 node ids"):
        episode_commit(question).commit(["n1", "n2"])


def test_commit_refuses_a_one_element_sequence(question: PolicyQuestion) -> None:
    # A sequence holding one id is still not the id: the call is spelled
    # commit(node_id), and a caller wrapping the id in a list is told the
    # spelling rather than silently unwrapped — coercion is how a batch
    # becomes a pick.
    with pytest.raises(PolicyCommitError, match=r"commit\(node_id\)"):
        episode_commit(question).commit(("n1",))


def test_commit_refuses_a_value_that_is_not_a_name(question: PolicyQuestion) -> None:
    # ``True`` is an int and not a node's name — the bool/int affinity trap
    # the workspace guards everywhere — and an unsized object names nothing.
    with pytest.raises(PolicyCommitError, match="not a node's name"):
        episode_commit(question).commit(True)


def test_commit_does_not_require_the_node_be_revealed(question: PolicyQuestion) -> None:
    # Deliberate scope, pinned: a commit names a node, it does not read one.
    # "n2" is in the tree but nothing has revealed it, and the commit stands
    # — the barrier governs reads (observed, the view, the surface), and a
    # policy committing blind gains no information and only costs score.
    record = episode_commit(question)
    question.reveal("n1")
    pick = record.commit("n2")
    assert pick.node_id == "n2"
    assert "n2" not in question.observed()


# ---------------------------------------------------------------------------
# commit — the address seam is the tree's own
# ---------------------------------------------------------------------------


def test_commit_refuses_a_node_outside_the_tree(question: PolicyQuestion) -> None:
    # A node id the tree does not hold is the tree's contract, refused by the
    # same PolicyAddressError ``reveal`` raises, from the same seam
    # (tree.node) — one contract read at two verbs, one class.
    record = episode_commit(question)
    with pytest.raises(PolicyAddressError, match="zz9"):
        record.commit("zz9")


def test_a_refused_commit_does_not_count(question: PolicyQuestion) -> None:
    # A refused attempt commits nothing: the record is left exactly as it
    # stood, so a policy that fumbles its one call — a misspelled id, a
    # batch — may still make it.  The door is closed by a *successful*
    # commit, not by an attempt.
    record = episode_commit(question)
    with pytest.raises(PolicyAddressError):
        record.commit("zz9")
    with pytest.raises(PolicyCommitError):
        record.commit(["n1", "n2"])
    assert record.committed is False
    assert record.commit("n1") == CommittedPick(node_id="n1")


def test_the_address_refusal_is_catchable_as_the_member_base(question: PolicyQuestion) -> None:
    # Both of the record's refusals — the protocol's own and the tree's,
    # propagated — are PolicyRuntimeError, so a caller catching the member's
    # one base class is never left holding an unnamed failure at this seam.
    record = episode_commit(question)
    with pytest.raises(PolicyRuntimeError):
        record.commit("zz9")
    with pytest.raises(PolicyRuntimeError):
        record.commit(None)


# ---------------------------------------------------------------------------
# commit — the terminal act is one act
# ---------------------------------------------------------------------------


def test_a_second_commit_is_refused_naming_the_pick(question: PolicyQuestion) -> None:
    # The score is earned under the pick as it stood at termination, and a
    # policy that could re-commit would be re-deciding after the fact — the
    # one-way door EpisodeBeta draws around the scalar, drawn around the
    # pick.  The refusal names the pick already made.
    record = episode_commit(question)
    record.commit("n1")
    with pytest.raises(PolicyCommitError, match="'n1'"):
        record.commit("n2")
    assert record.pick == CommittedPick(node_id="n1")


def test_a_commit_after_termination_is_refused(question: PolicyQuestion) -> None:
    # Termination is the moment the requirement is read: after terminate()
    # has snapshotted the episode, the door is closed, because a pick landing
    # then would be a pick the score never saw.
    record = episode_commit(question)
    record.terminate()
    with pytest.raises(PolicyCommitError, match="terminated"):
        record.commit("n1")
    assert record.pick is None


def test_the_one_act_law_holds_without_termination(question: PolicyQuestion) -> None:
    # The second-commit refusal is not conditional on termination: a runtime
    # that never calls terminate() has still enforced every law the commit
    # itself carries.  (terminate() freezes the door; it does not create it.)
    record = episode_commit(question)
    record.commit("n1")
    with pytest.raises(PolicyCommitError):
        record.commit("n1")


# ---------------------------------------------------------------------------
# terminate — the frozen read at termination
# ---------------------------------------------------------------------------


def test_terminate_snapshots_the_pick(question: PolicyQuestion) -> None:
    # The frozen read carries the pick the episode made — the value the
    # scorer consumes and the replay persists.
    record = episode_commit(question)
    record.commit("n2")
    termination = record.terminate()
    assert termination.pick == CommittedPick(node_id="n2")
    assert termination.committed is True


def test_terminate_without_a_commit_answers_the_miss(question: PolicyQuestion) -> None:
    # An episode that reaches termination uncommitted is a Termination with
    # no pick — the miss, as a value: a decision that was never made, kept
    # distinguishable from one that was (migration 0109's nullable
    # committed_pick).
    termination = episode_commit(question).terminate()
    assert termination.pick is None
    assert termination.committed is False


def test_terminate_is_idempotent_and_pure(question: PolicyQuestion) -> None:
    # Two calls answer equal values, because the snapshot is taken from state
    # the closed door can no longer change — the replay reads one
    # termination however many times it looks.
    record = episode_commit(question)
    record.commit("n1")
    first = record.terminate()
    second = record.terminate()
    assert first == second


def test_termination_is_frozen(question: PolicyQuestion) -> None:
    # A termination that could move would be a score that changed after it
    # was read — the replay writes one row from one termination, and the row
    # and the value must not drift.
    termination = episode_commit(question).terminate()
    with pytest.raises(dataclasses.FrozenInstanceError):
        termination.pick = CommittedPick(node_id="n1")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# score — −∞ for the non-committing policy, never a refusal
# ---------------------------------------------------------------------------


def _spy_scorer(calls: list[CommittedPick], answer: float = 1.5):
    """A scorer that records the picks it is handed — never called on a
    miss, called once with the pick on a hit."""

    def score(pick: CommittedPick) -> float:
        calls.append(pick)
        return answer

    return score


def test_a_non_committing_policy_scores_negative_infinity(question: PolicyQuestion) -> None:
    # The headline case, in the feature's own words: *returns negative
    # infinity for a non-committing policy*.  The score is −∞ — not None,
    # not NaN, not an exception — and the scorer is never called, because
    # there is no pick to hand it and no value to pass.
    calls: list[CommittedPick] = []
    termination = episode_commit(question).terminate()
    assert termination.score(_spy_scorer(calls)) == float("-inf")
    assert calls == []


def test_the_miss_is_below_every_committing_disaster(question: PolicyQuestion) -> None:
    # −∞ is the total order's floor: a non-committing policy scores below a
    # committing policy whose pick scored appallingly, so the dreaming loop's
    # argmax ranks the miss last rather than dropping it from the comparison
    # the way an exception (the crash slot) or a NaN (compares false against
    # everything) would.
    calls: list[CommittedPick] = []
    miss = episode_commit(question).terminate().score(_spy_scorer(calls))
    record = episode_commit(question)
    record.commit("n1")
    hit = record.terminate().score(_spy_scorer(calls, answer=-1e300))
    assert miss < hit
    assert math.isinf(miss) and miss < 0


def test_non_committing_score_is_the_module_constant(question: PolicyQuestion) -> None:
    # The one spelling: the termination's answer, the replay's row and a
    # caller's comparison all read NON_COMMITTING_SCORE, so the miss is one
    # value everywhere — a real minus infinity, finite-orderable, never a
    # NaN (which would compare false against everything).
    termination = episode_commit(question).terminate()
    assert termination.score(_spy_scorer([])) is NON_COMMITTING_SCORE
    assert NON_COMMITTING_SCORE == float("-inf")
    assert not math.isnan(NON_COMMITTING_SCORE)
    assert NON_COMMITTING_SCORE < -1e308


def test_score_hands_the_pick_to_the_scorer(question: PolicyQuestion) -> None:
    # On a hit, the scorer is called exactly once, with the pick, and its
    # answer is the score: the IR arithmetic is the replay engine's (docs
    # §10.3) and this seam only routes it — curried to the pick a
    # termination carries.
    calls: list[CommittedPick] = []
    record = episode_commit(question)
    record.commit("n2")
    value = record.terminate().score(_spy_scorer(calls, answer=0.25))
    assert calls == [CommittedPick(node_id="n2")]
    assert value == 0.25


def test_score_refuses_a_scorer_that_is_not_callable(question: PolicyQuestion) -> None:
    # A non-callable scorer is a wiring fault, refused in this member's own
    # vocabulary on every path — the miss included — rather than escaping as
    # a bare TypeError the member's one base class does not catch.
    termination = episode_commit(question).terminate()
    with pytest.raises(PolicyCommitError, match="not callable"):
        termination.score(1.5)  # type: ignore[arg-type]


def test_the_miss_is_a_score_and_a_pick_absent_together(question: PolicyQuestion) -> None:
    # The store's shape, as a value: the score is always answerable (the row
    # is the record of a completed scoring) and the pick is absent rather
    # than fabricated — "a decision that was never made must stay
    # distinguishable from one that was" (migration 0109).
    calls: list[CommittedPick] = []
    termination = episode_commit(question).terminate()
    assert termination.committed is False
    assert termination.pick is None
    assert termination.score(_spy_scorer(calls)) == NON_COMMITTING_SCORE
    assert calls == []
