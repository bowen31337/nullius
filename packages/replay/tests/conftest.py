"""Fixtures for the replay member's own suite.

This suite lives inside the workspace member (``packages/replay/tests``) rather
than under the repository-level ``tests/`` tree, because the member — including
its tests — is this feature's file-claim scope, and the placement is the one
the policy-runtime, artifacts and discovery members take for the same reason:
same-basename files collide under one pytest run, so each member's suite is
collected under its own conftest.

There is very little to isolate here, and that is a fact about the feature
rather than an omission.  A replay is *pure arithmetic over bytes that were
already computed and stored* (docs/nullius-tech-architecture.md §10.1), so a
transition writes no file, opens no database, reads no environment variable and
consults no clock — §12's determinism contract is precisely the rule that it
must not.  There is therefore no ambient state for a transition test to leak
into and no autouse fixture guarding one.

What the fixtures below are, then, is the *vocabulary* the tests are written
in — a stored tree shaped the way a completed campaign actually is: several
themed roots, a branch of depth two, a leaf, and the singular child-per-node
cardinality feature 239's expansion writes.  The real campaign tree is the
policy-runtime member's :class:`~policy_runtime.CampaignTree`; this member never
imports it (a member never imports another member), so the fixtures build the
node model here and the repository-level wiring suite exercises the composed
``CampaignTree`` end to end.

The path bootstrap below puts both import roots on ``sys.path`` regardless of
how pytest was invoked — the workspace's ``src/`` (for ``app.module_loader``,
which the component registration imports) and this member's ``src/`` (for
``replay`` itself) — the same bootstrap every member suite in this workspace
performs, so the suite is identical under ``uv run pytest`` (where the venv
also provides both) and under a bare ``pytest``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# conftest.py -> packages/replay/tests -> packages/replay -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "replay" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from replay import ReplayTransition, replay_roots, replay_transition


class StoredNode:
    """One node of a stored tree — the ``(node_id, parent_id, ...)`` model.

    The node model every member in this workspace restates rather than imports
    (the campaign tree's, the canary's): an id, a parent reference (``None`` at
    a root), and whatever else the carrier chooses to hold.  The transition
    reads only the first two — it derives a walk from the tree's recorded edges
    — so the fixture nodes deliberately carry a payload that the transition
    must never look at, which is how the "reads the edges, not the bytes" claim
    is testable.
    """

    __slots__ = ("depth", "node_id", "parent_id", "payload")

    def __init__(
        self,
        node_id: str,
        parent_id: str | None,
        *,
        depth: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.node_id = node_id
        self.parent_id = parent_id
        self.depth = depth
        self.payload = payload if payload is not None else {}


class StoredTree:
    """A stored discovery tree — a set of nodes with the address seam.

    Duck-typed deliberately, and not a copy of the campaign tree: the
    transition validates what it *reads* (``nodes``, ``node_id``,
    ``parent_id``, ``node``) rather than ``isinstance``-ing the carrier,
    because the module loader imports a member under a synthetic name and
    re-executes it — so the tree ``create_app()`` hands out may be a *second*
    class object and an ``isinstance`` would refuse the very tree composition
    produces.  This fixture is the shape the seam promises: a ``nodes``
    sequence and a ``node(node_id)`` address verb, and nothing else.
    """

    def __init__(self, nodes: list[StoredNode]) -> None:
        self.nodes = tuple(nodes)

    def node(self, node_id: str) -> StoredNode:
        for candidate in self.nodes:
            if candidate.node_id == node_id:
                return candidate
        raise KeyError(f"no node {node_id!r} in this stored tree")


@pytest.fixture
def campaign_nodes() -> list[StoredNode]:
    """A completed campaign's nodes — two themes, a depth-2 branch, a leaf.

    The shape feature 239's expansion actually writes and the singular
    cardinality it writes it with — **exactly one child per expanded node**,
    because ``CONTINUE(v)`` creates *"exactly one refined signal"*.  The
    canonical tree is one root and two children, which is enough to pin that a
    frontier is a set but not enough to pin the *feature*: the rows below give

    * **two roots in two themes** (``r-mom``, ``r-event``) — so the prefix's
      seed is a plurality, the reading docs §10.1's ``{tree.root}`` takes on a
      themed campaign, and ``{tree.root}`` implemented as "the first root"
      would pass a single-root tree while failing this one;
    * **a branch expanded twice** (``r-mom`` → ``m1`` → ``m1x``) — so a
      transition one step on is a legal move and a transition *two* steps on
      from ``r-mom`` is not: the walk takes one recorded edge at a time, which
      is the difference between a transition and a reachability query;
    * **an unexpanded root** (``r-event``, no child) — so a root whose
      expansion recorded nothing answers ``None`` rather than refusing, which
      is docs §10.1's ``if child:`` falling through;
    * **a leaf** (``m1x``) — the same fact one level down, so ``None`` is not
      an artefact of a node that happens to be a root.
    """
    return [
        StoredNode("r-mom", None, payload={"depth": 0, "theme_root": "cross-sectional-momentum"}),
        StoredNode("m1", "r-mom", depth=1, payload={"r2_insample": 0.20}),
        StoredNode("m1x", "m1", depth=2, payload={"r2_insample": 0.51}),
        StoredNode("r-event", None, payload={"depth": 0, "theme_root": "event-driven"}),
    ]


@pytest.fixture
def stored_tree(campaign_nodes: list[StoredNode]) -> StoredTree:
    """The stored campaign tree the transition walks."""
    return StoredTree(list(campaign_nodes))


@pytest.fixture
def transition(stored_tree: StoredTree) -> ReplayTransition:
    """A replay's transition over the stored tree, seeded at its roots."""
    return replay_transition(stored_tree)


__all__ = [
    "StoredNode",
    "StoredTree",
    "replay_roots",
    "replay_transition",
]
