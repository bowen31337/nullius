"""Fixtures for the policy-runtime member's own suite.

This suite lives inside the workspace member (``packages/policy-runtime/tests``)
rather than under the repository-level ``tests/`` tree, because the member —
including its tests — is this feature's file-claim scope, and the placement is
the one the artifacts, sandbox and canary members take for the same reason:
same-basename files collide under one pytest run, so each member's suite is
collected under its own conftest.

There is very little to isolate here, and that is a fact about the feature
rather than an omission.  The members that *do* need isolation are the ones
bound to a deployment — the artifact store's ``ARTIFACT_ROOT``, the null
sidecar's ``NULL_SIDECAR_PATH``, the dedup gate's ``DATABASE_URL`` — and a
policy-runtime *tree* is bound to nothing but its own nodes.  It writes no
file, opens no database, reads no environment variable and consults no clock
(docs §10.2: a policy sees only the cells it has already revealed).  So there
is no ambient state for a tree test to leak into, and no autouse fixture
guarding one.

What the fixtures below are, then, is the *vocabulary* the tests are written
in: a canonical campaign tree, a couple of named nodes, the root and a scored
leaf.  Naming them once keeps the tests reading as claims about the read-side
question rather than as constructions of it.

The path policy-runtime puts both import roots on ``sys.path`` regardless of
how pytest was invoked — the workspace's ``src/`` (for ``app.module_loader``,
which the component registration imports) and this member's ``src/`` (for
``policy_runtime`` itself) — the same bootstrap every member suite in this
workspace performs, so the suite is identical under ``uv run pytest`` (where
the venv also provides both) and under a bare ``pytest``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# conftest.py -> packages/policy-runtime/tests -> packages/policy-runtime -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "policy-runtime" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from policy_runtime import (
    CampaignNode,
    CampaignTree,
    PolicyObservation,
    PolicyQuestion,
    policy_question,
)

if TYPE_CHECKING:  # pragma: no cover - the fixture imports lazily
    pass


@pytest.fixture
def tree() -> CampaignTree:
    """The canonical campaign tree — a root and two scored leaves.

    Built through the public constructor rather than reached off the composed
    application, because a test of the *tree* should not depend on the factory
    having scanned anything; the component tests reach the composed one
    separately.  The root carries no in-sample reading (a structural node),
    and each leaf carries the metrics a reveal reads off it.
    """
    return CampaignTree.freeze(
        {
            "n0": (None, 0, {"depth": 0}),
            "n1": (
                "n0",
                1,
                {"parent_id": "n0", "depth": 1, "r2_insample": 0.20, "ic_insample": 0.05, "n_periods": 500, "n_features": 12},
            ),
            "n2": (
                "n0",
                1,
                {"parent_id": "n0", "depth": 1, "r2_insample": 0.33, "ic_insample": 0.09, "n_periods": 500, "n_features": 12},
            ),
        }
    )


@pytest.fixture
def root_node() -> str:
    """The tree's root node id — where a walk starts."""
    return "n0"


@pytest.fixture
def leaf_node() -> str:
    """A scored leaf node id — a node that carries an in-sample reading."""
    return "n1"


@pytest.fixture
def question(tree: CampaignTree) -> PolicyQuestion:
    """The read-side question over the canonical tree."""
    return policy_question(tree)
