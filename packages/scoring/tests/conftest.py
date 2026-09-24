"""Fixtures for the scoring member's own suite.

This suite lives inside the workspace member (``packages/scoring/tests``)
rather than under the repository-level ``tests/`` tree, because the member
— including its tests — is this feature's file-claim scope, and the
placement is the one the artifacts, sandbox, canary, bootstrap and
discovery members take for the same reason: same-basename files collide
under one pytest run, so each member's suite is collected under its own
conftest.

The objective's half of this suite has nothing to isolate, and that is a
fact about the feature rather than an omission.  The per-world objective
is pure arithmetic over the panel it is handed: it writes no file, opens
no database, reads no environment variable and consults no clock — the
same ambient-free profile the bootstrap member's suite states for its
worlds, and the reason no autouse fixture guards any of its tests.  The
member grew its first deployment-bound seam when feature 265's scorer
process landed, and with it the one autouse guard this conftest now
carries: :func:`scrub_sidecar_env` deletes the null oracle's four
environment variables (``NULL_SIDECAR_PATH``, ``LAKE_ROOT``,
``NULL_SIDECAR_KEY_REF``, ``NULL_SIDECAR_SERVICE_ACCOUNT``) from every
test in the suite, because under ``uv run`` the sibling member *is*
importable and :meth:`scoring.NullPickScorer.resolve` composes through
its resolution — an inherited ``NULL_SIDECAR_KEY_REF`` from the
operator's shell would make the composition tests answer for a deployment
this suite never configured.  The scrub keeps the member's own tests
deterministic the way the null oracle's conftest keeps its own: what the
composition tests *do* configure, they configure explicitly per test
(the cross-member suite builds a real sealed sidecar in a tmp directory);
what they leave unset is unset on purpose.

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
blend of 0.375 — every number in the chain exact in binary.  Feature
262's suite adds the committed book's panel beside those: a series
orthogonal to the pick's by construction, dyadic throughout, so the β₆
bonus it earns is the coefficient exactly and is checkable with ``==``.
Feature 265's suite adds the scorer process's own vocabulary beside all
of them: a stand-in sidecar — a plain object exposing exactly the one
``assignment(node_id)`` seam the duck-typed contract names, recording
every ask so the barrier tests can prove *which* nodes were read — and a
four-pick committed campaign over fixed UUIDs (two null, two real), so
the rate is 0.5 exactly and every subset's quotient is dyadic: ``k/4``
to the bit, the same hand-computable discipline the strata fixture
states for the blend.

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
def book(panel: dict[dt.date, float]) -> dict[dt.date, float]:
    """The committed book's panel over the pick's sequestered dates —
    orthogonal by construction, exactly.

    Feature 262's suite measures the β₆ bonus against this series.  The
    pick's readings sorted by date are (0.1, −0.1, 0.0, 0.2) — mean 0.05,
    deviations ``(a, −b, −a, b)`` with a = 0.05 and b = 3a — and the book
    below alternates ``(f, −f, f, −f)`` with f = 0.3, so its deviations
    pair against the pick's as ``(a·f, b·f, −a·f, −b·f)``: the four
    rounded products cancel as exact real values whatever the rounding of
    each, the ``fsum`` of them is a signed zero, and the correlation is
    0.0 to the bit — not merely to an epsilon — so the bonus's full
    payment is checkable with ``==``.  The book is not proportional to
    the pick (b ≠ a keeps the pick from alternating), so the zero is a
    genuine orthogonality and not a degenerate one.  Keyed in non-sorted
    order on purpose, to match the panel it is measured against.
    Variants of this series (collinear, anti-collinear, partial) are
    built inside the tests that pin those laws, because each is the
    *point* of its own test rather than shared vocabulary.
    """
    return {
        dt.date(2026, 3, 4): -0.3,
        dt.date(2026, 3, 1): 0.3,
        dt.date(2026, 3, 3): 0.3,
        dt.date(2026, 3, 2): -0.3,
    }


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


# -- Feature 265: the scorer process's vocabulary -----------------------------

#: The null oracle's four environment variables, restated by name here
#: (not imported — a member never imports another member, even in its
#: tests) so the autouse scrub below deletes exactly what
#: :meth:`scoring.NullPickScorer.resolve` composes through.  The names are
#: the sibling's own constants' values: ``SIDECAR_PATH_ENV``,
#: ``KEY_REF_ENV``, ``SERVICE_ACCOUNT_ENV`` and the lake root its path
#: fallback reads.
SIDECAR_ENV_VARS = (
    "NULL_SIDECAR_PATH",
    "LAKE_ROOT",
    "NULL_SIDECAR_KEY_REF",
    "NULL_SIDECAR_SERVICE_ACCOUNT",
)


@pytest.fixture(autouse=True)
def scrub_sidecar_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete the null oracle's environment from every test in this suite.

    Under ``uv run`` the sibling member is importable and the scorer
    process's ``resolve()`` composes through its resolution, so an
    inherited ``NULL_SIDECAR_KEY_REF`` (or a ``NULL_SIDECAR_PATH`` left in
    the operator's shell) would make the composition tests answer for a
    deployment this suite never configured — the same leak the null
    oracle's own conftest scrubs for its sidecar tests.  What a test
    *does* configure, it configures explicitly; what it leaves unset is
    unset on purpose.
    """
    for name in SIDECAR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@dataclass(frozen=True)
class StandInAssignment:
    """A stand-in for the oracle's per-node assignment value.

    The real :class:`~nulloracle.NullAssignment` carries the permuted seed
    and the block length beside the bit; this carries exactly ``is_null``,
    because that is the whole of what the scorer process reads — the
    fixture's narrowness is the assertion that the process never reaches
    for the rest.
    """

    is_null: bool


class StandInSidecar:
    """A stand-in for the oracle's sidecar, behind its one seam.

    Exposes exactly ``assignment(node_id)`` — the contract the oracle's
    own target route documents — over a plain dict of canonical node-id
    text to bits, answering ``None`` for an unheld node the way the
    sealed file's reader does.  Records every ask in ``reads`` so the
    barrier tests can prove three things at once: that the asks were the
    *canonical* spellings (the join normalized before the read), that
    only the handed picks were read (never a branch walk), and how many
    reads happened (one per pick, no caching pass, no pre-read).
    """

    def __init__(self, labels: dict[str, bool]) -> None:
        self._labels = dict(labels)
        self.reads: list[str] = []

    def assignment(self, node_id: str) -> StandInAssignment | None:
        self.reads.append(node_id)
        bit = self._labels.get(node_id)
        if bit is None:
            return None
        return StandInAssignment(bit)


#: Five fixed node addresses, canonical UUID text, planted once here so
#: every test in the scorer's suite names the same campaign: two planted
#: nulls, two planted reals, and one the sidecar holds no entry for — the
#: shape whose refusal is the fixture's own point (see ``sidecar_labels``).
NULL_ONE = "1a2b3c4d-5e6f-4778-89ab-cdef00000001"
REAL_ONE = "1a2b3c4d-5e6f-4778-89ab-cdef00000002"
NULL_TWO = "1a2b3c4d-5e6f-4778-89ab-cdef00000003"
REAL_TWO = "1a2b3c4d-5e6f-4778-89ab-cdef00000004"
UNHELD = "1a2b3c4d-5e6f-4778-89ab-cdef00000005"


@pytest.fixture
def sidecar_labels() -> dict[str, bool]:
    """The campaign's plant: two nulls, two reals, keyed by canonical id.

    The one shape every rate in this suite is a fraction over — and the
    shape whose *absence* (``UNHELD``) is deliberately outside it, so the
    refusal of an unlabelled pick is tested against a fixture that names
    it rather than against a typo.
    """
    return {
        NULL_ONE: True,
        REAL_ONE: False,
        NULL_TWO: True,
        REAL_TWO: False,
    }


@pytest.fixture
def sidecar(sidecar_labels: dict[str, bool]) -> StandInSidecar:
    """The stand-in sidecar — the held carrier, with its read log empty."""
    return StandInSidecar(sidecar_labels)


@pytest.fixture
def committed_picks() -> list[StandInPick]:
    """The campaign's four committed picks: two onto nulls, two onto reals.

    The values, not the addresses — the shape the runtime hands across a
    seam — with the rate therefore 0.5 exactly (2/4, dyadic, checkable
    with ``==``) and every subset's quotient ``k/4`` to the bit, the same
    hand-computable discipline the ``strata`` fixture states for the
    blend.
    """
    return [
        StandInPick(NULL_ONE),
        StandInPick(REAL_ONE),
        StandInPick(NULL_TWO),
        StandInPick(REAL_TWO),
    ]
