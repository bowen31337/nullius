"""The round loop never hands the policy a parent that already has its child.

A parent expands to exactly one child (a uuid5 of the parent). Re-selecting
an expanded parent re-authors the same child id, and the tree refuses its
differing metrics. archP02's rounds 2 and 3 added no node because the
baseline policy kept re-picking its best-ranked, already-expanded parents.
"""

from __future__ import annotations

from orchestrator._campaign import _unexpanded_view
from orchestrator._policy import BaselinePolicy
from policy_runtime import PolicyObservation


def _observation(node_id: str, ic: float) -> PolicyObservation:
    return PolicyObservation(
        node_id=node_id, r2_insample=ic**2, ic_insample=ic, n_periods=500, n_features=1,
    )


class _Question:
    def __init__(self, ics: dict[str, float], children: dict[str, list[str]]) -> None:
        self._ics = ics
        self._children = children

    def observed(self) -> dict[str, PolicyObservation]:
        return {node: _observation(node, ic) for node, ic in self._ics.items()}

    def legal_actions(self, node_id: str | None = None) -> list[str]:
        return list(self._children.get(node_id, [])) if node_id else []


def test_expanded_parents_are_dropped_and_their_children_kept() -> None:
    question = _Question(
        {"best": 0.9, "child": 0.1, "other": 0.5},
        {"best": ["child"]},
    )
    view = _unexpanded_view(question)
    assert sorted(view.observed()) == ["child", "other"]


def test_the_baseline_picks_the_next_open_node_not_the_expanded_best() -> None:
    question = _Question(
        {"best": 0.9, "child": 0.1, "other": 0.5},
        {"best": ["child"]},
    )
    assert BaselinePolicy(1).select(_unexpanded_view(question)) == ["other"]


def test_a_tree_of_unexpanded_roots_is_unchanged() -> None:
    question = _Question({"a": 0.2, "b": 0.3}, {})
    assert sorted(_unexpanded_view(question).observed()) == ["a", "b"]
