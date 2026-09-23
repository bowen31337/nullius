"""Fixtures for the scoring member's own suite.

This suite lives inside the workspace member (``packages/scoring/tests``)
rather than under the repository-level ``tests/`` tree, because the member
— including its tests — is this feature's file-claim scope, and the
placement is the one the artifacts, sandbox, canary, bootstrap and
discovery members take for the same reason: same-basename files collide
under one pytest run, so each member's suite is collected under its own
conftest.

There is nothing to isolate, and that is a fact about the feature rather
than an omission.  The per-world objective is pure arithmetic over the
panel it is handed: it writes no file, opens no database, reads no
environment variable and consults no clock — the same ambient-free
profile the bootstrap member's suite states for its worlds, and the
reason there is no autouse fixture guarding anything here.  The
sibling suites that do need isolation are the ones bound to a deployment
(``ARTIFACT_ROOT``, ``NULL_SIDECAR_PATH``, ``DATABASE_URL``), and none of
those seams exists in this member yet: the store-bound features of the
category (265's scorer process, 267's FDR store) will grow their own
fixtures when they land, the way bootstrap's conftest grew the pool's.

What the fixtures below are, then, is the *vocabulary* the tests are
written in: a sequestered panel with a hand-computed information ratio
(the same panel every "the score starts from the leading term" test
reads), the committed pick's address, and a stand-in for feature 222's
committed value — a plain object exposing ``node_id``, because a member
never imports another member and the duck-typed seam is the honest way to
test what crosses it.

The path bootstrap puts both import roots on ``sys.path`` regardless of
how pytest was invoked — the workspace's ``src/`` (for
``app.module_loader``, which the component registration imports) and this
member's ``src/`` (for ``scoring`` itself) — the same bootstrap every
member suite in this workspace performs, so the suite is identical under
``uv run pytest`` (where the venv also provides both) and under a bare
``pytest``.
"""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# conftest.py -> packages/scoring/tests -> packages/scoring -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "scoring" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from scoring import WorldScore, world_objective


@dataclass(frozen=True)
class StandInPick:
    """A stand-in for feature 222's committed pick.

    The scoring member never imports the policy-runtime member, so the
    pick seam is duck-typed — any object exposing a non-empty ``node_id``
    — and this is the shape the tests exercise it with: the same one
    field, the same validation outcome, no dependency on the member that
    owns the real value.
    """

    node_id: str


@pytest.fixture
def pick_node_id() -> str:
    """The committed pick's address — one node, named once."""
    return "campaign-01/momentum-branch/d+1"


@pytest.fixture
def pick(pick_node_id: str) -> StandInPick:
    """The committed pick as the runtime hands it across — the value, not
    the address."""
    return StandInPick(pick_node_id)


@pytest.fixture
def panel() -> dict[dt.date, float]:
    """A sequestered panel whose information ratio is 1/√5, by hand.

    Four dates reading (0.1, −0.1, 0.2, 0.0): mean 0.05, population
    variance (0.05² + 0.15² + 0.15² + 0.05²)/4 = 0.0125, population
    standard deviation 0.05·√5, ratio 1/√5 ≈ 0.4472136.  Written in
    non-sorted key order on purpose, so the order-independence test has
    something to reverse.
    """
    return {
        dt.date(2026, 3, 4): 0.2,
        dt.date(2026, 3, 1): 0.1,
        dt.date(2026, 3, 2): -0.1,
        dt.date(2026, 3, 3): 0.0,
    }


@pytest.fixture
def score(pick: StandInPick, panel: dict[dt.date, float]) -> WorldScore:
    """The objective's answer for the committed pick over the panel — the
    value every later assertion adjusts from."""
    return world_objective("financial-campaign-01", pick, panel)
