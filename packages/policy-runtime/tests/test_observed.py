"""Feature 217, the observed accessor — the read side of the question.* interface.

app_spec.xml, "Exploration Policy Runtime", feature 217: *System exposes an
observed accessor which returns a mapping of revealed node ids to
observations.*  This is the read side of the identical ``question.*`` interface
docs/nullius-tech-architecture.md §11 names — the surface an exploration policy
is handed during replay — and §10.2 makes *prefix-only*: a policy sees only the
cells it has already revealed, never an unrevealed node by any path.

The observed accessor is the whole of feature 217, and the invariants these
tests pin are the ones the information barrier depends on:

* **prefix-only by construction** — an unrevealed node is *absent* from the
  returned mapping, never filtered into it, and never reachable by
  introspection, attribute walking, or a stray ``__dict__`` access (docs §10.2,
  cq-16).  The accessor iterates the question's own reveal set and builds one
  observation per revealed node, so a node the policy has not revealed is never
  a key, never a value;
* **the honest reading, unchanged** — each observation is the tree's honest
  payload-derived reading of the cell, so the map is a pure function of the
  revealed set: the same cells revealed in any order return the same
  observations;
* **the barrier holds** — an observation carries the in-sample metrics the
  node's payload carries, and never ``is_null`` (readable by exactly one
  component, the replay scorer — prd §4.2, cq-8), never an absolute score
  target, never a hardcoded node id, never an unrevealed node's score.
"""

from __future__ import annotations

import pytest

from policy_runtime import (
    CampaignTree,
    PolicyAddressError,
    PolicyObservation,
    PolicyQuestion,
    PolicyTreeError,
    policy_question,
)


def test_observed_starts_empty(question: PolicyQuestion) -> None:
    # A fresh question has revealed nothing, so its observed mapping is empty —
    # an empty prefix is a statement about what the policy has seen (nothing),
    # not about the tree it fronts, and a policy handed an empty mapping holds
    # exactly what it started with.
    assert question.observed() == {}


def test_observed_returns_only_revealed_nodes(question: PolicyQuestion, leaf_node: str) -> None:
    # Revealing a cell adds it to the observed mapping, keyed by its node id —
    # the accessor builds one observation per revealed node, so the mapping is
    # the revealed set rendered, and nothing more.
    question.reveal(leaf_node)
    observed = question.observed()
    assert set(observed) == {leaf_node}
    assert isinstance(observed[leaf_node], PolicyObservation)


def test_observed_is_prefix_only(tree: CampaignTree, question: PolicyQuestion) -> None:
    # The whole of "prefix-only": the root ``n0`` is a node the tree holds but
    # the policy has not revealed, so it is *absent* from the observed mapping —
    # never a key, never a value, never reachable through the mapping.  A policy
    # holding the mapping holds only what it has already seen, and an unrevealed
    # node is not present in the returned structure at all (docs §10.2, cq-16).
    question.reveal("n1")
    question.reveal("n2")
    observed = question.observed()
    assert "n0" not in observed
    assert set(observed) == {"n1", "n2"}


def test_observed_is_ascending_by_node_id(question: PolicyQuestion) -> None:
    # The accessor sorts the revealed set before the reduction — the ordering
    # rule docs §12 states for a search frontier — so two reads of one question
    # agree whatever order the reveals came in, and a report rendered from the
    # mapping is reproducible.
    question.reveal("n2")
    question.reveal("n1")
    assert list(question.observed()) == ["n1", "n2"]


def test_observed_is_a_pure_function_of_the_revealed_set(question: PolicyQuestion) -> None:
    # The same cells revealed in any order return the same observations, because
    # each observation is a pure function of ``(tree, node_id)`` — the honest
    # payload-derived reading of the cell, computed afresh each call.  A policy
    # comparing two cells must not be able to move either, and two reads of one
    # question must agree to the last field.
    question.reveal("n1")
    first = question.observed()
    again = policy_question(question.tree)
    again.reveal("n1")
    assert again.observed() == first


def test_observed_carries_the_honest_reading(question: PolicyQuestion, leaf_node: str) -> None:
    # The observation carries the in-sample metrics the node's payload carries —
    # the honest reading the tree exists to give — attributed to the node id it
    # was earned on.  Nothing is rescored or narrowed, so a policy comparing a
    # revealed cell against a financial one reads the cell's own honest number.
    question.reveal(leaf_node)
    observation = question.observed()[leaf_node]
    assert observation.r2_insample == 0.20
    assert observation.ic_insample == 0.05
    assert observation.node_id == leaf_node


def test_observed_never_carries_is_null(tree: CampaignTree) -> None:
    # ``is_null`` is readable by exactly one component, the replay scorer (prd
    # §4.2, cq-8), so a node whose payload carries it must not leak it through
    # the observed accessor.  The observation reads the payload by the metric
    # names it knows — ``r2_insample``, ``ic_insample``, ``n_periods``,
    # ``n_features`` — and ``is_null`` is not one of them, so a node that carries
    # it answers an observation that carries only the honest in-sample reading.
    tree = CampaignTree.freeze(
        {
            "n0": (None, 0, {"depth": 0}),
            "n1": (
                "n0",
                1,
                {"parent_id": "n0", "depth": 1, "r2_insample": 0.20, "is_null": True},
            ),
        }
    )
    question = policy_question(tree)
    question.reveal("n1")
    assert "is_null" not in question.observed()["n1"].row()
    assert question.observed()["n1"].r2_insample == 0.20


def test_observed_never_carries_an_absolute_score_target(question: PolicyQuestion) -> None:
    # The barrier forbids a policy seeing an absolute score target — a policy
    # that could read a fixed target would be reading past the prefix, aiming at
    # a number the barrier never froze.  The observation carries only the
    # in-sample metrics the node's payload carries, so a node with no such
    # metric answers ``None`` rather than a target the barrier never set.
    question.reveal("n1")
    row = question.observed()["n1"].row()
    assert "target" not in row
    assert "absolute_score" not in row


def test_observed_does_not_mutate_when_the_policy_reads_it(question: PolicyQuestion) -> None:
    # The reveal set is the question's private state, and the accessor reads it
    # read-only — so a policy that reads the observed mapping twice, or holds it,
    # cannot grow the reveal set by the act of reading.  Reading is not
    # revealing, and a mapping that grew on a read would be a prefix the policy
    # could extend without a reveal.
    question.reveal("n1")
    _ = question.observed()
    _ = question.observed()
    assert question.revealed == frozenset({"n1"})


def test_observed_refuses_a_non_tree() -> None:
    # A question fronts a tree, and an object that is not a tree names no
    # surface a policy can be handed — so the question refuses it at
    # construction, naming what was wrong, before it can answer differently
    # from the tree it claims to front.
    with pytest.raises(PolicyTreeError):
        PolicyQuestion("not a tree")  # type: ignore[arg-type]


def test_observed_refuses_an_empty_tree() -> None:
    # A tree with no nodes is a surface the policy could not walk, so a question
    # over it is refused at construction — the one reading the read-side
    # question must never front a policy over nothing.
    with pytest.raises(PolicyTreeError):
        PolicyQuestion(CampaignTree(nodes=tuple()))  # type: ignore[arg-type]


def test_two_questions_of_one_tree_answer_identically(tree: CampaignTree) -> None:
    # Two adapters of one tree answer identical observations to the last field —
    # the property that makes "one policy, both pools" a fact about the adapter
    # rather than a promise in a docstring.  A policy scored on each is scored
    # on the same surface.
    q1 = policy_question(tree)
    q2 = policy_question(tree)
    q1.reveal("n1")
    q2.reveal("n1")
    assert q1.observed() == q2.observed()


def test_reveal_refuses_a_node_outside_the_tree(question: PolicyQuestion) -> None:
    # A policy reveals only cells it was shown, and a reveal that named a cell
    # the tree does not hold would let the policy think it had seen one — so the
    # reveal refuses it, naming the node and the tree, and records nothing.
    with pytest.raises(PolicyAddressError):
        question.reveal("ghost")
    assert question.observed() == {}


def test_reveal_many_is_idempotent_on_the_revealed_set(question: PolicyQuestion) -> None:
    # Re-revealing a cell the question already holds does not re-return it — the
    # call is idempotent on the revealed set, so a policy that re-reveals a cell
    # it holds does not see it as new, and the reveal set does not grow on a
    # repeat.
    first = question.reveal_many(["n1", "n2"])
    second = question.reveal_many(["n1", "n2"])
    assert set(first) == {"n1", "n2"}
    assert second == {}
    assert question.revealed == frozenset({"n1", "n2"})


def test_observation_row_is_store_shaped(question: PolicyQuestion, leaf_node: str) -> None:
    # The observation renders as a store-shaped mapping — the payload a replay
    # writes down — with the node id and the in-sample metrics, and a fresh dict
    # per call, so a policy reading it twice gets two mappings and cannot move
    # the frozen observation through one.
    question.reveal(leaf_node)
    row = question.observed()[leaf_node].row()
    assert row == {
        "node_id": leaf_node,
        "r2_insample": 0.20,
        "ic_insample": 0.05,
        "n_periods": 500,
        "n_features": 12,
    }


def test_observation_of_a_structural_node_answers_none(question: PolicyQuestion, root_node: str) -> None:
    # A node that carries no in-sample reading is a structural node, not a
    # scored leaf, and its observation says so — ``None`` for each metric —
    # rather than inventing a number the barrier never froze.  A stand-in score
    # where the payload had no reading would be a reading that is not ground
    # truth.
    question.reveal(root_node)
    observation = question.observed()[root_node]
    assert observation.r2_insample is None
    assert observation.ic_insample is None
