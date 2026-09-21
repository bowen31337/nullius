"""Feature 217, the question seam — the write side of the observed accessor.

app_spec.xml, "Exploration Policy Runtime", feature 217: the read-side question
is the surface an exploration policy is handed during replay, and the identical
``question.*`` interface docs/nullius-tech-architecture.md §11 names.  This file
pins the write side of that interface — the reveal bookkeeping the question owns
— and the invariants that keep the observed accessor prefix-only:

* **reveal is a record of what the policy did, not a grant of access** — the
  question records a node id the policy revealed, and refuses one the tree does
  not hold, naming it (docs §10.2, cq-16);
* **the reveal set is the whole of the question's private state** — the tree
  owns the answer surface, the question owns only the reveal set, so a policy
  cannot read a cell it has not revealed, and the observed mapping is a pure
  function of the reveal set (feature 184 precedent);
* **the question fronts a tree, and refuses what is not one** — duck-typed
  construction checks the tree answers the surface the question calls, and
  refuses an object that does not, before it can answer differently from the
  tree it claims to front.
"""

from __future__ import annotations

import pytest

from policy_runtime import (
    CampaignTree,
    PolicyAddressError,
    PolicyQuestion,
    PolicyTreeError,
    policy_question,
)


def test_reveal_records_a_node(question: PolicyQuestion) -> None:
    # A reveal records the node id the policy revealed, and the observed mapping
    # answers it — the reveal is a record of what the policy did, and the
    # accessor renders exactly that set.
    question.reveal("n1")
    assert "n1" in question.revealed
    assert set(question.observed()) == {"n1"}


def test_reveal_refuses_a_node_outside_the_tree(question: PolicyQuestion) -> None:
    # A reveal that named a cell the tree does not hold would let the policy
    # think it had seen one, so the reveal refuses it — naming the node and the
    # tree — and records nothing, so the observed mapping stays the honest
    # prefix.
    with pytest.raises(PolicyAddressError):
        question.reveal("ghost")
    assert question.revealed == frozenset()


def test_reveal_many_returns_only_new_nodes(question: PolicyQuestion) -> None:
    # reveal_many returns the nodes newly revealed — the ones a policy had not
    # seen — so a policy can render only what it just earned, and re-revealing a
    # cell it holds returns nothing new.
    newly = question.reveal_many(["n1", "n2"])
    assert set(newly) == {"n1", "n2"}


def test_reveal_many_is_idempotent(question: PolicyQuestion) -> None:
    # Re-revealing cells the question already holds returns nothing — the call is
    # idempotent on the revealed set, so a policy that re-reveals a cell it holds
    # does not see it as new, and the reveal set does not grow on a repeat.
    question.reveal_many(["n1", "n2"])
    again = question.reveal_many(["n1", "n2"])
    assert again == {}
    assert question.revealed == frozenset({"n1", "n2"})


def test_reveal_many_refuses_a_node_outside_the_tree(question: PolicyQuestion) -> None:
    # A reveal that named a cell the tree does not hold is refused even among
    # valid cells — the whole call refuses, naming the node, so a policy cannot
    # slip one invalid reveal past a batch of valid ones.
    with pytest.raises(PolicyAddressError):
        question.reveal_many(["n1", "ghost"])
    assert question.revealed == frozenset()


def test_revealed_is_immutable(question: PolicyQuestion) -> None:
    # The reveal set is the question's private state, and the accessor hands back
    # an immutable view — so a policy holding it cannot grow the prefix by
    # mutating the view, and a mapping that grew on a read would be a prefix the
    # policy could extend without a reveal.
    question.reveal("n1")
    with pytest.raises(AttributeError):
        question.revealed.add("n2")  # type: ignore[attr-defined]
    assert question.revealed == frozenset({"n1"})


def test_question_refuses_a_non_tree() -> None:
    # A question fronts a tree, and an object that is not a tree names no surface
    # a policy can be handed — so the question refuses it at construction,
    # naming what was wrong, before it can answer differently from the tree it
    # claims to front.
    with pytest.raises(PolicyTreeError):
        PolicyQuestion("not a tree")  # type: ignore[arg-type]


def test_question_refuses_an_object_without_the_surface() -> None:
    # Duck-typed construction checks the tree answers the surface the question
    # calls — ``nodes`` and ``node`` — and refuses an object that does not,
    # before it can answer differently from the tree it claims to front.  A
    # policy handed a question over such an object would be handed a surface that
    # could not answer a reveal.
    class NotATree:
        nodes = ()

    with pytest.raises(PolicyTreeError):
        PolicyQuestion(NotATree())  # type: ignore[arg-type]


def test_question_refuses_an_empty_tree() -> None:
    # A tree with no nodes is a surface the policy could not walk, so a question
    # over it is refused at construction — the one reading the read-side question
    # must never front a policy over nothing.
    with pytest.raises(PolicyTreeError):
        PolicyQuestion(CampaignTree(nodes=tuple()))  # type: ignore[arg-type]


def test_question_exposes_the_tree(question: PolicyQuestion, tree: CampaignTree) -> None:
    # The question fronts the tree it was built over — the honest surface the
    # observed accessor reads — so a policy reading the question's tree reads the
    # tree it was shown, and the accessor answers over it.
    assert question.tree is tree


def test_policy_question_factory_builds_a_question(tree: CampaignTree) -> None:
    # The factory builds a question over the tree — the seam the replay scorer
    # and the evaluation harness use — so a policy handed the factory's answer is
    # handed the read-side question, and the observed accessor answers over the
    # tree.
    question = policy_question(tree)
    assert isinstance(question, PolicyQuestion)
    assert question.tree is tree
