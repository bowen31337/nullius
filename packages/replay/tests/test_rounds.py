"""Feature 248 — the replay round loop — in the member's own suite.

app_spec.xml, "Replay Engine", feature 248: *System loops policy selection
until no batch is selected or the round cap is reached, which returns the
revealed set.*  The member's suite pins the loop and its refusals; the
repository-level wiring suite (``tests/replay/``) pins the duck-typed seam and
the reveal-set reconciliation over the real ``CampaignTree``.

The doubles below are deliberately *duck-typed and minimal*, because the loop
reads each collaborator through exactly one verb and nothing else — the shape
the module promises:

* a **stub ``select``** — the callable shape of ``policy.select(prefix_view(...))``
  the caller wires; the loop never names a policy or a prefix view, so the
  stub *is* the policy's decision, handed in as a closure;
* a **stub question** — exposing only ``probe_batch`` over a reveal set, the
  one verb the loop reads off feature 217's question; a carrier with no such
  verb is the refusal the loop raises;
* the **StoredTree of conftest** — the same recorded-tree vocabulary the
  transition tests use, so the loop drives 245's transition over the tree the
  member already pins.

**Nothing here re-derives a recorded child.**  The loop's whole cost claim is
that it drives 245's transition rather than computing ``child = tree.child_of(v)``
itself, so the stub ``select`` asserts the transition — not the tree — advanced,
and a test watches that the transition, not a hand-rolled lookup, is what grew
the prefix.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import StoredTree
from replay import ReplayRoundError, ReplayTreeError, run_replay

# ---------------------------------------------------------------------------
# The doubles
# ---------------------------------------------------------------------------


class QuestionStub:
    """The read-side question, duck-typed to the one verb the loop reads.

    Exposes only ``probe_batch`` over a reveal set — the whole of what
    :func:`run_replay` demands of feature 217's question.  ``probe_batch``
    mirrors the real contract the loop relies on: idempotent (an
    already-revealed cell is not re-returned), all-or-nothing (a cell the tree
    does not hold reveals none of the batch — the tree's ``node()`` raises
    ``KeyError`` and the batch is refused), ascending, and returning only the
    cells newly revealed.  ``probe_calls`` records every batch the loop hands
    in, so a test can assert no node is re-probed.
    """

    def __init__(self, tree: StoredTree) -> None:
        self._tree = tree
        self._revealed: set[str] = set()
        self.probe_calls: list[tuple[str, ...]] = []
        self.probe_count = 0

    def probe_batch(self, cells: Any, on_reveal: Any = None) -> dict[str, Any]:
        ordered = sorted(set(cells))
        self.probe_calls.append(tuple(ordered))
        self.probe_count += 1
        # All-or-nothing: a cell the tree does not hold refuses the whole batch,
        # revealing none of them — the real verb's contract, restated so the
        # loop's "a node the transition revealed is a node the tree holds"
        # guarantee is the second statement of a fact the stub also enforces.
        for node_id in ordered:
            self._tree.node(node_id)  # KeyError here = the batch is refused
        newly = [n for n in ordered if n not in self._revealed]
        for node_id in newly:
            self._revealed.add(node_id)
        return {node_id: node_id for node_id in newly}

    def revealed(self) -> frozenset[str]:
        return frozenset(self._revealed)


def frontier_select(question: QuestionStub) -> list[str]:
    """A stub policy: select the frontier — revealed nodes whose recorded child
    the tree holds and which the walk has not yet advanced.

    The caller's half of the loop — the closure over the policy and the prefix
    view — handed in as ``select``.  It reads the question's revealed set as the
    prefix (the one thing ``prefix_view(question)`` exposes), and selects the
    *frontier*: a revealed node that has a recorded child not yet revealed.
    Reading the revealed set (not the tree) is what makes this a *policy*
    decision over the prefix, not a reachability query over the tree — the
    loop's "select is the policy's" stance.

    The tree's recorded edges are the conftest campaign's:
    ``r-mom -> m1 -> m1x``, and ``r-event`` is an unexpanded root.  So the
    frontier is, in order: ``r-mom`` (child ``m1``), then ``m1`` (child
    ``m1x``), then ``m1x`` (a leaf) and ``r-event`` (an unexpanded root) — at
    which point no frontier node has a recorded child and the policy selects no
    batch, terminating the walk.
    """
    revealed = sorted(question.revealed())
    edges = {"r-mom": "m1", "m1": "m1x"}
    return [node_id for node_id in revealed if node_id in edges and edges[node_id] not in revealed]


def always_select(question: QuestionStub) -> list[str]:
    """A stub policy that always selects a batch — to pin termination on the cap.

    Selects ``r-mom`` every round, regardless of frontier, so the walk would run
    forever on the loop's "no batch" arm alone; only the round cap stops it.
    ``r-mom`` is always revealed and always one the tree holds, so the batch is
    always truthy — the transition reveals ``m1`` the first round and answers
    ``None`` (already revealed) thereafter, but the *selection* never empties,
    so the cap is the only thing that bounds the walk.
    """
    return ["r-mom"]


# ---------------------------------------------------------------------------
# The loop drives 245's transition
# ---------------------------------------------------------------------------


def test_the_loop_drives_the_transition_not_a_re_derivation(
    stored_tree: StoredTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The loop's whole cost claim: it drives feature 245's transition, one step
    # per selected node, and does not re-derive a recorded child.  The two are
    # observably different — a re-derivation would read the tree's raw edges
    # (`child_map`/`recorded_child`) directly; the loop instead calls the
    # transition's own `transition` verb.  Spy on that verb: every call the loop
    # takes is recorded, and the recorded calls are exactly the frontier nodes
    # the policy selected — r-mom, then m1 — proving the prefix grew through the
    # transition's step and not a hand-rolled lookup.
    from replay import ReplayTransition

    calls: list[str] = []
    original = ReplayTransition.transition

    def spying(self: Any, selected: Any, **kwargs: Any) -> Any:
        calls.append(selected)
        return original(self, selected, **kwargs)

    monkeypatch.setattr(ReplayTransition, "transition", spying)
    result = run_replay(frontier_select, QuestionStub(stored_tree), stored_tree, round_cap=10)
    # The full walk: both roots, then m1, then m1x.  r-event is an unexpanded
    # root and m1x is a leaf, so the frontier empties and the walk stops.
    assert result == ("m1", "m1x", "r-event", "r-mom")
    # The transition advanced by recorded edges: r-mom -> m1 and m1 -> m1x were
    # taken through the transition's own step.  m1x is never selected — it is a
    # leaf with no unrevealed child, so the frontier empties and the walk stops
    # before the policy ever selects it.  A re-derivation would not call
    # `transition.transition` at all — it would read child = tree.child_of(v).
    assert calls == ["r-mom", "m1"]


def test_the_prefix_is_seeded_at_the_roots(stored_tree: StoredTree) -> None:
    # docs §10.1's `revealed = {tree.root}` — the tree's parentless nodes,
    # plural on a themed campaign — is the policy's first view.  A select that
    # records the prefix it is handed on its first call pins that the seed is
    # the two roots, ascending, not a single root and not an empty prefix.
    seen: list[tuple[str, ...]] = []

    def select(question: QuestionStub) -> list[str]:
        seen.append(tuple(sorted(question.revealed())))
        return []  # no batch: terminate after recording the first view

    result = run_replay(select, QuestionStub(stored_tree), stored_tree, round_cap=10)
    assert seen[0] == ("r-event", "r-mom")
    assert result == ("r-event", "r-mom")


def test_the_reveal_set_is_kept_equal_to_the_prefix_at_every_select(
    stored_tree: StoredTree,
) -> None:
    # The reconciliation the loop exists for: the question's reveal set equals
    # the transition's revealed set at every `select`, so the policy is always
    # shown the frontier the walk is standing on.  A select that records the
    # question's revealed set each round pins it against the walk's known
    # trajectory — the seeded roots, then the roots plus m1, then plus m1x —
    # which is exactly what the transition's prefix is at each round.  If the
    # loop failed to sync (or synced the whole prefix each round), the recorded
    # sequence would differ.
    recorded: list[frozenset[str]] = []

    def select(question: QuestionStub) -> list[str]:
        recorded.append(question.revealed())
        return frontier_select(question)

    run_replay(select, QuestionStub(stored_tree), stored_tree, round_cap=10)
    # Round 0: the seeded roots.  Round 1: the roots plus m1 (r-mom's recorded
    # child).  Round 2: plus m1x (m1's recorded child).  At round 3 the frontier
    # is empty and the walk stops, so there are exactly three selects.
    assert recorded == [
        frozenset({"r-event", "r-mom"}),
        frozenset({"r-event", "r-mom", "m1"}),
        frozenset({"r-event", "r-mom", "m1", "m1x"}),
    ]
    # Each recorded set is the transition's revealed set at that round — the
    # reconciliation, pinned round by round, rather than a re-derivation.


def test_no_node_is_re_probed(stored_tree: StoredTree) -> None:
    # The anti-quadratic claim: the loop reveals only the children each round
    # newly revealed, never re-probing the whole prefix.  A counting
    # QuestionStub records every batch, and no node id appears in more than one
    # probe — seeding the roots once, then each newly recorded child once.
    question = QuestionStub(stored_tree)
    result = run_replay(frontier_select, question, stored_tree, round_cap=10)
    assert result == ("m1", "m1x", "r-event", "r-mom")
    # Every node id is probed exactly once across the whole walk.  The roots
    # are seeded once; m1 and m1x are revealed once each as they are recorded;
    # re-probing the whole prefix each round would put r-mom and r-event in
    # every round's batch.
    all_probed: list[str] = []
    for batch in question.probe_calls:
        all_probed.extend(batch)
    assert sorted(all_probed) == sorted(set(all_probed)), (
        "a node was re-probed: the loop revealed more than the new children"
    )
    # The roots are seeded once, then each newly recorded child once — three
    # probes for this campaign (roots, m1, m1x), not one per round over the
    # whole prefix.
    assert question.probe_calls[0] == ("r-event", "r-mom")


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------


def test_terminates_when_no_batch_is_selected(stored_tree: StoredTree) -> None:
    # Termination arm one: `if not batch: break`.  A select that returns `[]`
    # stops the walk immediately and returns the current prefix — the seeded
    # roots, since nothing was advanced.  A loop that honored only the round cap
    # would run all ten rounds here.
    calls = 0

    def select(question: QuestionStub) -> list[str]:
        nonlocal calls
        calls += 1
        return []

    result = run_replay(select, QuestionStub(stored_tree), stored_tree, round_cap=10)
    assert result == ("r-event", "r-mom")
    assert calls == 1, "the loop did not stop on the empty batch"


def test_terminates_at_the_round_cap_with_a_frontier_remaining(
    stored_tree: StoredTree,
) -> None:
    # Termination arm two: `rounds >= round_cap`.  A select that always returns
    # a batch would run forever on the "no batch" arm alone; only the cap stops
    # it, at exactly `round_cap` rounds, with a frontier still selected.  The
    # stub selects the first revealed node every round — always truthy — so the
    # walk is bounded only by the cap.
    rounds = 0

    def select(question: QuestionStub) -> list[str]:
        nonlocal rounds
        rounds += 1
        return always_select(question)

    # round_cap = 3: three rounds, then stop.  r-mom is selected every round;
    # the first round reveals m1, and rounds two and three re-select r-mom
    # (already revealed, so the transition answers None) — the selection never
    # empties, so only the cap bounds the walk, which stops at exactly three
    # rounds with the policy still willing to select.
    result = run_replay(select, QuestionStub(stored_tree), stored_tree, round_cap=3)
    assert rounds == 3, "the loop did not stop at exactly the round cap"
    assert result == ("m1", "r-event", "r-mom")
    # A cap of 1 stops after one round: only r-mom -> m1 is taken.
    rounds = 0
    result1 = run_replay(select, QuestionStub(stored_tree), stored_tree, round_cap=1)
    assert rounds == 1
    assert result1 == ("m1", "r-event", "r-mom")


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_re_selecting_a_revealed_node_reveals_nothing_new(
    stored_tree: StoredTree,
) -> None:
    # Idempotence: a select that re-selects an already-revealed node reveals
    # nothing new and does not double-count.  The transition's `transition` is a
    # set add, so transitioning over a node whose child is already revealed
    # reveals nothing new; the loop's sync reveals only the new children, so a
    # re-selected node adds nothing to the question's reveal set.
    def select(question: QuestionStub) -> list[str]:
        revealed = sorted(question.revealed())
        # Re-select the first revealed node every round (already revealed), plus
        # advance the frontier when one is open.
        frontier = {"r-mom": "m1", "m1": "m1x"}
        pick = [n for n in revealed if n in frontier]
        return [revealed[0]] + pick if revealed else []

    result = run_replay(select, QuestionStub(stored_tree), stored_tree, round_cap=10)
    # The revealed set is exactly the walk's, with no duplication from the
    # re-selected r-mom.
    assert result == ("m1", "m1x", "r-event", "r-mom")


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_a_non_callable_select_is_refused_before_the_tree_is_opened() -> None:
    # The select is refused first: a non-callable names no policy to call, and a
    # loop that opened a transition and read a tree and then found it had no
    # policy would have spent the walk it was meant to guard against spending.
    # A watched tree is never addressed — the refusal fires before `over`.  This
    # tree raises if its nodes are read, so a refusal that opened the transition
    # would surface the tree's error, not the round error.
    class NeverAddressed:
        @property
        def nodes(self) -> Any:
            raise AssertionError("the tree was addressed before the refusal")

    with pytest.raises(Exception) as raised:
        run_replay("not callable", QuestionStub(NeverAddressed()), NeverAddressed(), round_cap=10)
    assert type(raised.value).__name__ == "ReplayRoundError"
    assert "select" in str(raised.value)


def test_a_non_positive_round_cap_is_refused_before_the_tree_is_opened(
    stored_tree: StoredTree,
) -> None:
    # The round cap is refused first: a cap that is not a positive count names no
    # loop, and zero or negative would terminate before a single round — a
    # silent no-op that reads as a completed replay.  Refused before the tree is
    # opened, naming the value.
    for bad in (0, -1, -5):
        with pytest.raises(Exception) as raised:
            run_replay(frontier_select, QuestionStub(stored_tree), stored_tree, round_cap=bad)
        assert type(raised.value).__name__ == "ReplayRoundError"
        assert str(bad) in str(raised.value)


def test_a_bool_round_cap_is_refused(stored_tree: StoredTree) -> None:
    # A bool is an int in Python (True == 1, False == 0), but a boolean is not a
    # round count: it names no loop, and answering 1 or 0 for it would report a
    # malformed cap as a single-round or a completed replay.
    for bad in (True, False):
        with pytest.raises(Exception) as raised:
            run_replay(frontier_select, QuestionStub(stored_tree), stored_tree, round_cap=bad)
        assert type(raised.value).__name__ == "ReplayRoundError"


def test_a_non_int_round_cap_is_refused(stored_tree: StoredTree) -> None:
    # A non-int cap (a float, a string) breaks the `rounds < round_cap`
    # comparison and names no integer count of rounds.
    for bad in (2.5, "10", None):
        with pytest.raises(Exception) as raised:
            run_replay(frontier_select, QuestionStub(stored_tree), stored_tree, round_cap=bad)
        assert type(raised.value).__name__ == "ReplayRoundError"


def test_a_carrier_with_no_probe_batch_is_refused(stored_tree: StoredTree) -> None:
    # The question is refused before the tree is opened: a carrier with no
    # callable `probe_batch` cannot be reconciled to the walk — a mismatch the
    # policy would see as a frontier the walk is not standing on.
    class NoProbe:
        pass

    with pytest.raises(Exception) as raised:
        run_replay(frontier_select, NoProbe(), stored_tree, round_cap=10)
    assert type(raised.value).__name__ == "ReplayRoundError"
    assert "probe_batch" in str(raised.value)


def test_every_refusal_is_a_round_error_and_not_a_tree_error(
    stored_tree: StoredTree,
) -> None:
    # The loop's three refusals share one repair (fix the argument handed to
    # run_replay), so they are all `ReplayRoundError` — and deliberately not
    # `ReplayTreeError`: a caller skipping a bad tree must not silently skip the
    # refusal that says the loop was handed no callable policy.
    for bad_select in ("not callable",):
        with pytest.raises(ReplayRoundError) as raised:
            run_replay(bad_select, QuestionStub(stored_tree), stored_tree, round_cap=10)
        assert not isinstance(raised.value, ReplayTreeError)
    with pytest.raises(ReplayRoundError) as raised:
        run_replay(frontier_select, QuestionStub(stored_tree), stored_tree, round_cap=0)
    assert not isinstance(raised.value, ReplayTreeError)


def test_a_malformed_tree_surfaces_as_a_tree_error_through_the_loop(
    stored_tree: StoredTree,
) -> None:
    # A malformed tree is feature 245's `ReplayTreeError`, not the loop's
    # `ReplayRoundError`: the loop opens the transition and lets its refusal
    # propagate, because the tree's unfitness is a statement about the tree,
    # repaired at the store, not about the loop's arguments.  A tree whose nodes
    # cannot be read — a value with no `nodes` — is refused by the transition.
    class NotATree:
        pass

    with pytest.raises(Exception) as raised:
        run_replay(frontier_select, QuestionStub(stored_tree), NotATree(), round_cap=10)
    assert type(raised.value).__name__ == "ReplayTreeError"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_two_replays_of_one_policy_on_one_tree_are_one_revealed_set(
    stored_tree: StoredTree,
) -> None:
    # §12's determinism contract (cq-15), restated for the loop: two replays of
    # one policy on one tree are one revealed set.  The order the policy
    # selected nodes in does not change the answer — the transition is a
    # function of the tree and the selected nodes, never of the order.
    left = run_replay(frontier_select, QuestionStub(stored_tree), stored_tree, round_cap=10)
    right = run_replay(frontier_select, QuestionStub(stored_tree), stored_tree, round_cap=10)
    assert left == right == ("m1", "m1x", "r-event", "r-mom")
