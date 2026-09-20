"""Panel builders for the tripwires suite — pure functions, no fixtures.

Why these live in a uniquely-named module instead of in ``conftest.py``: a
member suite's ``conftest`` is a top-level module called ``conftest``, and so
is every other member's. The sibling suites that do ``from conftest import
...`` therefore cannot be collected together — pytest imports
``packages/snapshot/tests/conftest.py`` and ``packages/tripwires/tests/
conftest.py`` under one module name, the first one to load wins, and the
second member's imports fail with an ``ImportError`` raised from a file the
reader is not looking at. That is a pre-existing sharp edge in this workspace,
not one this suite invented, but there is no reason for a *new* suite to
widen it.

The split is by kind, which is the honest one: ``conftest.py`` keeps the two
pytest fixtures (``grid``, ``symbols``), because that is what conftest is for,
and the panel builders below are ordinary deterministic functions that take
their parameters explicitly. A test that wants a panel of a different size
calls the function with that size rather than re-requesting a fixture, and
the import is a plain ``from _panels import ...`` that no other member can
shadow.

The builders are deterministic in their ``seed`` so every assertion in the
suite is a fixed fact rather than a flake, and the panels they make are
independent across dates *and* symbols — a panel built from one stream
carries no information about a panel built from another, which is what makes
:func:`gaussian_panel` a valid *null* for a probe whose whole job is to
detect information.
"""

from __future__ import annotations

import datetime as dt
import random

__all__ = ["gaussian_panel", "lookahead_panel", "monday"]

#: The default grid width — 120 dates, the size the module's own leak check
#: cites as verified for the canonical leak clearing the bar by a factor near
#: two. Named so a test can say "shorter than the probe's own verification"
#: rather than restating the number.
DEFAULT_GRID = 120

#: The default symbol count — 30, likewise the module's own verification width.
DEFAULT_SYMBOLS = 30


def monday(
    count: int, *, start: dt.date = dt.date(2024, 1, 1)
) -> list[dt.date]:
    """``count`` consecutive calendar dates from ``start`` — a rebalance grid.

    Consecutive days rather than week-aligned ones: nothing in the probe knows
    what a rebalance calendar is, and the tests should not imply it does.
    """
    return [start + dt.timedelta(days=offset) for offset in range(count)]


def symbols(count: int = DEFAULT_SYMBOLS) -> list[str]:
    """``count`` symbol names, in a fixed order.

    Fixed rather than randomized because the names are only ever used as
    dictionary keys; giving them a stable spelling keeps a failure's output
    readable ("S07" rather than an arbitrary hash).
    """
    return [f"S{index:02d}" for index in range(count)]


def gaussian_panel(
    dates: list[dt.date], names: list[str], *, seed: int
) -> dict[dt.date, dict[str, float]]:
    """A ``{date: {symbol: value}}`` panel of independent standard normals.

    Independent across dates *and* symbols, so a panel built this way carries
    no information about any other panel built from it — which is what lets a
    test pair two of these and call the result a clean candidate. Returns a
    cross-section for every date in ``dates``, including repeats if the caller
    passes them (the probe's own duplicate-bar refusal is tested with a grid
    built by hand, not here).
    """
    rng = random.Random(seed)
    return {
        day: {name: rng.gauss(0.0, 1.0) for name in names} for day in dates
    }


def lookahead_panel(
    targets: dict[int, dict[dt.date, dict[str, float]]], *, horizon: int = 1
) -> dict[dt.date, dict[str, float]]:
    """A score panel that leaks: every date carries the full-sample symbol mean.

    This is the canonical leak the module's docstring names — a full-sample
    normalization the signal was never supposed to see — and it is *constant
    across dates by construction*, which is the point: re-dating the cross-
    sections (what the time shuffle does) cannot disturb a score that does not
    depend on the date, so whatever the candidate scores after the shuffle is
    information it carried about the target panel rather than about the
    pairing. That is precisely the mechanism the probe exists to catch.

    The panel is built *from* the targets, so it is a genuine lookahead: it
    knows the whole sample's returns. Sign is preserved, so a caller can
    negate it to build the sign-flipped leak the two-sided test must also
    catch. Returns one cross-section per target date, keyed identically.
    """
    series = targets[horizon]
    days = sorted(series)
    return {
        day: {
            name: sum(series[other][name] for other in days) / len(days)
            for name in series[day]
        }
        for day in days
    }
