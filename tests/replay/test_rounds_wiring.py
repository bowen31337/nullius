"""Feature 248 in the assembled system — the round loop over the real tree and question.

app_spec.xml, "Replay Engine", feature 248: *System loops policy selection
until no batch is selected or the round cap is reached, which returns the
revealed set.*  The member's own suite (``packages/replay/tests/test_rounds.py``)
pins the loop and its refusals over a hand-rolled double; this suite pins the
**duck-typed seam and the reveal-set reconciliation** over the two objects the
composed application actually produces — the policy-runtime member's real
:class:`~policy_runtime.CampaignTree` and its real
:class:`~policy_runtime.PolicyQuestion` — which is what a member's suite
structurally cannot do:

* **the loop drives the composed transition** — the component's ``run``
  resolves the deployment's tree through the policy-runtime seat and opens
  feature 245's transition over the real ``CampaignTree``, the only test in the
  workspace where this member's restatement of the node model is checked
  against the class that actually carries it;
* **the duck-typed seam matches the document** — the loop is handed the real
  ``PolicyQuestion`` and a ``select`` closure over ``prefix_view(question)``;
  neither is ``isinstance``-ed, because the module loader imports each member
  under a synthetic name and re-executes it, so the ``PolicyQuestion`` and
  ``CampaignTree`` ``create_app()`` hands out are *second* class objects with
  the same names and the same source — an ``isinstance`` would refuse the very
  objects composition produces;
* **the reveal-set reconciliation holds end to end** — the loop keeps the
  question's reveal set equal to the transition's revealed set at every
  ``select``, so the policy is always shown the frontier the walk is standing
  on; over the real question this is the difference between a walk that
  terminates and one that drifts.

The component's ``run`` resolves the tree through the policy-runtime seat
(``app.modules.policy-runtime``'s ``campaign_tree_component``), not from a
passed argument — the call-time resolution feature 245 argues.  This
environment names no committed campaign, so the seat is substituted with the
fixture's tree, the way ``packages/replay/tests/test_component.py`` does; the
question here is the seam between two members, not the store's.

**Nothing here asserts ``isinstance`` or ``pytest.raises(<canonical class>)``
across the composition seam.**  The composed ``ReplayRoundError`` and
``ReplayTreeError`` are second class objects with the same names; the checks
below name the behaviour and compare ``type(exc).__name__``, the same answer
``tests/nulloracle/conftest.py`` and ``tests/feature-store/test_registration.py``
give for the same wrinkle.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

policy_runtime = pytest.importorskip("policy_runtime")
CampaignTree = policy_runtime.CampaignTree
PolicyQuestion = policy_runtime.PolicyQuestion

REPO_ROOT = Path(__file__).resolve().parents[2]

seat = importlib.import_module("app.modules.policy-runtime")


@pytest.fixture(scope="module")
def campaign_tree() -> CampaignTree:
    """The real campaign tree a deployment would hold — two themes, one branch.

    Built through the policy-runtime member's *public* constructor
    (``CampaignTree.freeze``, the seam feature 217 ships), never by hand-rolling
    a node model here: the point of the walk below is that this member's
    duck-typed restatement matches the class that actually carries it.
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
def run_over_tree(campaign_tree, monkeypatch):
    """Drive the composed component's ``run`` over the real campaign tree.

    The component's ``run`` resolves the deployment's tree through the
    policy-runtime seat; this environment names no committed campaign, so the
    seat's ``campaign_tree_component`` is substituted with the fixture's tree —
    the way ``packages/replay/tests/test_component.py`` pins the resolution.
    The returned helper runs a stub policy over a fresh real ``PolicyQuestion``,
    so each call starts from a clean reveal set.
    """
    monkeypatch.setattr(seat, "campaign_tree_component", lambda app=None: campaign_tree)
    component = create_app().get("replay")

    def run(select, round_cap):
        return component.run(select, PolicyQuestion(campaign_tree), round_cap=round_cap)

    return run


def create_app():
    from app.module_loader import create_app

    return create_app()


def _frontier_select(question: PolicyQuestion) -> list[str]:
    """A stub policy over the real question — select the open frontier.

    The caller's half of the loop, exactly as a deployment wires it: a closure
    over ``prefix_view(question)`` and the policy's decision.  It reads the
    question's ``observed()`` as the prefix (the one thing ``prefix_view``
    exposes), and selects the revealed nodes whose recorded child the tree holds
    and which the walk has not yet revealed — the open frontier.  Reading the
    question's reveal set (not the tree) is what makes this a *policy* decision
    over the prefix, and it is the seam the loop is handed: ``select(question)``
    where the loop never names ``prefix_view`` or a policy.
    """
    revealed = sorted(question.observed())
    edges = {"r-mom": "m1", "m1": "m1x"}
    return [
        node_id
        for node_id in revealed
        if node_id in edges and edges[node_id] not in revealed
    ]


def test_the_composed_component_loops_over_the_real_tree_and_question(
    run_over_tree,
) -> None:
    # The whole chain, over the objects the composed application produces: the
    # component's ``run`` resolves the deployment's tree through the seat, opens
    # feature 245's transition over the real CampaignTree, and drives it with a
    # stub policy closing over prefix_view(the real PolicyQuestion).  The walk is
    # the conftest campaign's: r-mom -> m1 -> m1x (a leaf), r-event an
    # unexpanded root — so the frontier empties and the walk stops on "no batch
    # selected", returning the revealed set.
    result = run_over_tree(_frontier_select, round_cap=10)
    assert result == ("m1", "m1x", "r-event", "r-mom")


def test_the_reveal_set_is_kept_equal_to_the_prefix_at_every_select(
    run_over_tree,
) -> None:
    # The reconciliation, over the real question: the loop keeps the question's
    # reveal set (what prefix_view(question) exposes) equal to the transition's
    # revealed set (the walk's true frontier) at every select, so the policy is
    # always shown the frontier the walk is standing on.  A select that records
    # the question's observed() each round pins it against the walk's known
    # trajectory — the seeded roots, then plus m1, then plus m1x.  If the loop
    # failed to sync, the recorded sequence would differ and the policy would
    # have been shown a frontier the walk was not standing on.
    observed: list[tuple[str, ...]] = []

    def select(q: PolicyQuestion) -> list[str]:
        # Snapshot the prefix the policy is shown *at this select* — reading it
        # later would show the final reveal set for every round, since the
        # question is one object the loop mutates in place.
        observed.append(tuple(sorted(q.observed())))
        return _frontier_select(q)

    result = run_over_tree(select, round_cap=10)
    assert result == ("m1", "m1x", "r-event", "r-mom")
    # The question's reveal set grows exactly along the walk's frontier: seeded
    # roots, then plus m1, then plus m1x — one entry per round the policy
    # selected a batch.  This is the reconciliation pinned end to end: the
    # prefix the policy is shown each round is the frontier the walk is standing
    # on, never ahead of it.
    assert observed == [
        ("r-event", "r-mom"),
        ("m1", "r-event", "r-mom"),
        ("m1", "m1x", "r-event", "r-mom"),
    ]


def test_terminates_when_no_batch_is_selected_over_the_real_question(
    run_over_tree,
) -> None:
    # Termination arm one, over the real question: a policy that selects no
    # batch stops the walk immediately and returns the seeded prefix — the two
    # roots, since nothing was advanced.  A loop that honored only the round cap
    # would run all ten rounds here.
    calls = 0

    def select(q: PolicyQuestion) -> list[str]:
        nonlocal calls
        calls += 1
        return []

    result = run_over_tree(select, round_cap=10)
    assert result == ("r-event", "r-mom")
    assert calls == 1, "the loop did not stop on the empty batch"


def test_terminates_at_the_round_cap_over_the_real_question(
    run_over_tree,
) -> None:
    # Termination arm two, over the real question: a policy that always selects
    # a batch would run forever on the "no batch" arm alone; only the round cap
    # stops it, at exactly `round_cap` rounds, with a frontier still selected.
    rounds = 0

    def select(q: PolicyQuestion) -> list[str]:
        nonlocal rounds
        rounds += 1
        # Always select r-mom: always truthy, always a node the tree holds.  The
        # transition reveals m1 the first round and answers None (already
        # revealed) thereafter, but the selection never empties, so the cap is
        # the only thing that bounds the walk.
        return ["r-mom"]

    result = run_over_tree(select, round_cap=3)
    assert rounds == 3, "the loop did not stop at exactly the round cap"
    assert result == ("m1", "r-event", "r-mom")


def test_a_non_positive_round_cap_is_refused_through_the_composed_component(
    run_over_tree,
) -> None:
    # Feature 248's round cap, reached the way a runtime reaches it — through
    # the composed component, not the member's free functions — so a driver
    # cannot find a non-refused spelling by holding the module instead of the
    # application.  A non-positive cap (zero, negative, a bool) is refused
    # before the tree is resolved, naming the value, as `ReplayRoundError` and
    # not `ReplayTreeError`.  The class is compared *by name*: the composed
    # component was defined in a synthetic module, so its error is not the one
    # `import replay` yields.
    for bad in (0, -1, True):
        with pytest.raises(Exception) as raised:
            run_over_tree(_frontier_select, round_cap=bad)
        assert type(raised.value).__name__ == "ReplayRoundError"
        assert "round_cap" in str(raised.value)


def test_a_malformed_tree_surfaces_as_a_tree_error_through_the_loop(
    campaign_tree, monkeypatch
) -> None:
    # A malformed tree is feature 245's `ReplayTreeError`, not the loop's
    # `ReplayRoundError`: the loop opens the transition and lets its refusal
    # propagate, because the tree's unfitness is a statement about the tree,
    # repaired at the store, not about the loop's arguments.  Reached through
    # the composed component, which resolves the tree via the seat — and in this
    # environment no campaign is committed, so `resolve_tree()` refuses.  The
    # seat is *not* substituted here, so the resolution itself refuses: a
    # deployment with nothing to replay.
    component = create_app().get("replay")
    question = PolicyQuestion(campaign_tree)
    with pytest.raises(Exception) as raised:
        component.run(_frontier_select, question, round_cap=10)
    assert type(raised.value).__name__ == "ReplayTreeError"


def test_a_replay_over_the_real_tree_is_deterministic(run_over_tree) -> None:
    # §12's determinism contract (cq-15) over the real tree and question: two
    # replays of one policy on one stored tree produce one revealed set.  The
    # order the policy selected nodes in does not change the answer — the
    # transition is a function of the tree and the selected nodes, never of the
    # order.
    left = run_over_tree(_frontier_select, round_cap=10)
    right = run_over_tree(_frontier_select, round_cap=10)
    assert left == right == ("m1", "m1x", "r-event", "r-mom")
