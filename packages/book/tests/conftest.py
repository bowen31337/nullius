"""Fixtures for the book member's own suite.

This suite lives inside the workspace member (``packages/book/tests``)
rather than under the repository-level ``tests/`` tree, because the member
— including its tests — is this feature's file-claim scope, and the
placement is the one the artifacts, sandbox, canary, bootstrap, discovery
and scoring members take for the same reason: same-basename files collide
under one pytest run, so each member's suite is collected under its own
conftest.

The path bootstrap puts both import roots on ``sys.path`` regardless of how
pytest was invoked — the workspace's ``src/`` (for ``app.module_loader``,
which the component registration imports) and this member's ``src/`` (for
``book`` itself) — the same bootstrap every member suite in this workspace
performs, so the suite is identical under ``uv run pytest`` (where the venv
also provides both) and under a bare ``pytest``.

The vocabulary below is the shape the tests are written in: three promoted
signals, each with a strictly positive information ratio and a target score
for each of a shared symbol set {BTC, ETH, SOL}, dyadic throughout so the
composite is hand-computable to the bit.  IRs (1.0, 2.0, 1.0) give a total
weight of 4.0 exactly and every weight dyadic (¼, ½, ¼); the scores are
quarters and eighths, so every composite is an exact multiple of 1/16 — the
same hand-computable discipline the scoring member's ``strata`` fixture
states for its blend.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# conftest.py -> packages/book/tests -> packages/book -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "book" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from book import PromotedSignal

#: The three symbols every fixture signal covers — the book's shared symbol
#: set, named once here so every test in the suite ranks the same three.
BTC = "BTC"
ETH = "ETH"
SOL = "SOL"


@dataclass(frozen=True)
class StandInSignal:
    """A stand-in for a promoted signal.

    Feature 301's :class:`~book.PromotedSignal` is the intended input, but
    the combiner reads the ``signal_id`` / ``information_ratio`` /
    ``target_scores`` surface duck-typed — the loader imports members under
    synthetic names and re-executes them, so a signal this process composed
    may be a second class object — and this is the shape that proves it:
    exactly those three attributes, nothing else, so a test combining these
    exercises the seam the composed combiner actually depends on.
    """

    signal_id: str
    information_ratio: float
    target_scores: dict[str, float]


#: Three fixed signal ids, continuing the fixture series so every test in
#: the suite names the same three promoted signals.
SIGNAL_ONE = "momentum"
SIGNAL_TWO = "mean-reversion"
SIGNAL_THREE = "carry"


@pytest.fixture
def signals() -> list[PromotedSignal]:
    """The three promoted signals — positive IRs, shared symbol set.

    IRs (1.0, 2.0, 1.0) — total weight 4.0 exactly, weights (1/4, 1/2,
    1/4), all dyadic — and per-symbol scores, each a multiple of 1/8 so the
    composite is a multiple of 1/16:

    * BTC: 0.25, 0.125, 0.25  → composite 0.25·¼ + 0.125·½ + 0.25·¼ = 0.1875
    * ETH: 0.125, 0.25, 0.25  → composite 0.125·¼ + 0.25·½ + 0.25·¼ = 0.21875
    * SOL: 0.25, 0.25, 0.125  → composite 0.25·¼ + 0.25·½ + 0.125·¼ = 0.21875

    Every composite checkable with ``==`` because the weights and scores
    are dyadic and the total weight is a power of two.
    """
    return [
        PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
        PromotedSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        PromotedSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
