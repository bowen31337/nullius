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
test what crosses it.  Feature 263's suite adds the aggregation's own
vocabulary beside them: a stand-in carrier exposing exactly the two
attributes the blend reads (``world_id`` and ``score`` — and nothing
else, which is what proves the seam validates what it reads rather than
the type it was handed), and a three-stratum pool of world scores whose
figures are dyadic so the blend is hand-computable to the bit: stratum
means 0.75, 0.5 and 0.25 over two, two and three worlds, an unweighted
stratum mean of 0.5 exactly, a minimum of 0.25, and therefore a λ = 0.5
blend of 0.375 — every number in the chain exact in binary.

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


@dataclass(frozen=True)
class StandInScore:
    """A stand-in carrier for the aggregation's duck-typed world seam.

    Feature 256's :class:`~scoring.WorldScore` is the intended carrier,
    but the module loader imports this member under a synthetic name and
    re-executes it, so a score this process composed may be a second
    ``WorldScore`` class object — the blend therefore reads the two
    attributes it needs and validates what it reads.  This is the shape
    that proves it: exactly ``world_id`` and ``score``, nothing else, so
    a test aggregating these exercises the seam the composed process
    actually depends on.
    """

    world_id: str
    score: float


def world_score(world_id: str, score: float) -> WorldScore:
    """One world score at a stated scalar, for building a pool by hand.

    The objective's own value, constructed directly (its constructor is
    public and validates), with the measurement and the objective equal
    — feature 256's birth equality — which is the state every world
    enters an aggregation in until a β-term moves it.
    """
    return WorldScore(
        world_id=world_id, node_id=f"campaign-01/{world_id}", ir_oos=score, score=score
    )


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


@pytest.fixture
def strata() -> dict[str, list[WorldScore]]:
    """A three-stratum pool whose blend is hand-computable to the bit.

    The stratum names are the default three the coverage ledger's own
    sentence names (feature 283's *"high-volatility trend",
    "low-volatility chop" and "crash"* — restated here, not imported,
    because a member never imports another member), and the scalars are
    dyadic so every figure downstream is exact:

    * trend: two worlds at 0.75 → figure 0.75
    * chop: two worlds at 0.5 → figure 0.5
    * crash: three worlds at 0.25 → figure 0.25 (three worlds on
      purpose: the strata weigh equally, not by world count)

    The unweighted stratum mean is (0.75 + 0.5 + 0.25)/3 = 0.5 exactly,
    the stratum minimum is 0.25 (crash), and the blend is therefore
    0.375 at λ = 0.5, 0.35 at the default λ = 0.6, 0.325 at λ = 0.7 —
    the first and last checkable with ``==``, the middle within one
    float of its decimal.
    """
    return {
        "high-volatility trend": [
            world_score("trend-a", 0.75),
            world_score("trend-b", 0.75),
        ],
        "low-volatility chop": [
            world_score("chop-a", 0.5),
            world_score("chop-b", 0.5),
        ],
        "crash": [
            world_score("crash-a", 0.25),
            world_score("crash-b", 0.25),
            world_score("crash-c", 0.25),
        ],
    }


@dataclass(frozen=True)
class StandInLabel:
    """A stand-in for feature 290's stratum assignment.

    The census that bins the pool lives in the regime member, and the
    scoring member never imports it, so the label seam is duck-typed —
    any object exposing non-empty ``world_id`` and ``stratum`` text —
    and this is the shape feature 264's index reads: the same two fields
    the real :class:`~regime.StratumAssignment` carries, no dependency
    on the member that owns the real value.
    """

    world_id: str
    stratum: str


#: The three regime names the fixtures label with — feature 283's own
#: sentence, restated here rather than imported for the same reason the
#: ``strata`` fixture restates them: a member never imports another
#: member, and the index reads whatever names it is given.
TREND = "high-volatility trend"
CHOP = "low-volatility chop"
CRASH = "crash"


@pytest.fixture
def labels() -> list[StandInLabel]:
    """The census's rows for the ``strata`` fixture's seven worlds.

    One label per world, matching :func:`strata` name for name, so the
    index built from the pair reproduces the fixture the blend's own
    suite aggregates — the two features are one pipeline, and this is
    the seam where 290's output becomes 263's input.
    """
    return [
        StandInLabel("trend-a", TREND),
        StandInLabel("trend-b", TREND),
        StandInLabel("chop-a", CHOP),
        StandInLabel("chop-b", CHOP),
        StandInLabel("crash-a", CRASH),
        StandInLabel("crash-b", CRASH),
        StandInLabel("crash-c", CRASH),
    ]
