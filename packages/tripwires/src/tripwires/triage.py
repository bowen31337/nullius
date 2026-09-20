"""The perturbation-stability triage figure — feature 134.

app_spec.xml, "Leakage Tripwires", feature 134: *"System computes the area
under the curve for perturbation stability separating planted nulls from
real signals, which emits the triage figure."*  The sentence's two halves
are this module's two halves: a labelled experiment — two planted
populations, the nulls the family must clear and the real signals it must
separate them from — and a reduction of the family's figures over both
populations to one area under one curve per axis and one macro-mean
across the axes.  The verb is *emits*: the figure is a value, stated with
its own evidence, and nothing here rejects, persists or decides.

**The experiment, and why it is worth one module.**  docs/alpha-engine-prd.md
§4.5 names this measurement as the M1 triage gate — *perturbation-stability
AUC on planted nulls* — with a decision rule on its answer (an AUC near
0.85 says hard-code the filter and delete the dreaming apparatus; near 0.6
says the learned signature is worth building).  A rule with two branches
is only as good as the number it reads, so the number is computed rather
than estimated: the populations are planted from a pinned seed, the axes
are the family's own runners, and the AUC is exact under ties.  The whole
experiment is a pure function of (``seed``, ``count``) that runs in
seconds — the "one-day triage experiment" the PRD sketches, shipped as
the one function that can re-answer the question any day it is asked
again.

**What "planted" buys, and the two populations' design.**  The classes
differ in exactly one thing — the presence of a date-aligned relationship
between scores and targets — and share everything else, so any AUC away
from one half is attributable to that one thing and to nothing about
panel shape, universe width or horizon coverage.

*Planted nulls* (:func:`planted_nulls`) are honest books: score panels
drawn fresh from the standard normal, over *market-like* targets — each
horizon a persistent per-symbol profile plus fresh per-date noise, with
the persistence pinned as the profile's variance share.  The persistent
dispersion is load-bearing: the derangement re-dates whole
cross-sections, so cross-sectional structure is exactly what survives a
shuffle, and a targets panel without any (iid in every cell) would plant
a world where stability could never matter.  *Real signals*
(:func:`real_signals`) are the same market-like targets with scores
loaded on the alignment the evaluator is supposed to find:
``ic × target + √(1 − ic²) × fresh noise``, on the shortest horizon —
the probe's own horizon policy, the horizon with the most rebalance
dates.  The information coefficient is pinned at 0.05, and the pin is a
calibration rather than a taste: measured over the pinned seed, 7 of 32
signals are reference-rejected by the probe's own bar at 0.05 (the
honest boundary — a fifth of the class brushes the leak bar, which is
the regime the triage exists to sit on), while at 0.10 a third and at
0.20 all 32 of them are (leak territory: candidates feature 125 catches
before any triage could, planted as the class the triage is asked to
separate — the experiment would measure the leak bar, not the family).

**The AUC's arithmetic.**  Mann-Whitney with midranks: the probability a
null's figure exceeds a signal's, plus half the probability of a tie —
``(R_null − n(n+1)/2) / (n·m)`` over midranks, exact under any tie
pattern, summed with :func:`math.fsum` so the result is independent of
the order the figures arrived in.  The orientation is pinned as part of
the statistic's meaning: **above one half means the nulls are the less
stable class** — the direction the family is hoped to separate in — and
below one half means the axis separates with the other sign, which is a
finding the figure reports rather than an error to flip.

**The measured answer at the pin, and the shape of its honesty.**  At
:data:`TRIAGE_SEED`, 32 candidates a side: family AUC 0.4548 — seed axis
0.3750, universe-subsample 0.4932, lookback-jitter 0.4961.  The family
sits at chance, and the reason is structural rather than sampled.  Every
figure this family measures is the stability of the **surviving** Sharpe
— the candidate's book scored against *shuffled* returns — and the
shuffle destroys the date-aligned edge that is the only difference
between the two classes, so both classes' figures are the noise of a
re-measurement.  The one thing that can move a surviving Sharpe is
structure that persists across dates — a full-sample fit, a symbol-level
statistic — and a candidate carrying that is not a "real signal" waiting
to be separated but a leak the probe's own bar rejects.  The positive
control pins the claim behaviourally: with feature 133's planted leaks as
the signal class, the seed axis scores 1.0000 *exactly* (a whole-sample
statistic does not degrade under a second derangement — degradation
exactly 0.0), the lookback axis 0.7812, and the universe-subsample axis
0.0000 — inverted, because dropping a fifth of the universe moves a
full-sample fit's book further than any honest noise.  The one direction
the family separates in is a direction the leak bar already owns.

**The seed axis' honest inversion.**  Feature 127's figure folds
magnitudes — ``(|reference| − |rerun|) / bar`` — and the fold of two
noise magnitudes is tighter than the noise itself (for independent
standard normals, ``Var(|a| − |b|) = 2(1 − 2/π)σ² < 2σ²``), so a null's
two folded Sharpes land closer together than a signal's two unfolded
loadings let its: measured 0.375, below one half, robust across
information coefficients and populations.  It is kept and reported
rather than re-oriented, for the reason the orientation paragraph gives:
an AUC whose sign was flipped after seeing the answer is an AUC whose
number means whatever the flipper wanted, and the macro-mean carrying
the inversion is the honest cost of averaging a family whose axes do not
all point the same way.

**The decision-rule reading, stated as a reading.**  Neither branch of
§4.5's rule: 0.4548 is not the 0.85 that says hard-code a filter, and it
is not read as the 0.6 that says build the signature either — it is
chance, and the positive control says the family's one discriminative
direction is feature 125's.  The module emits the figure and its
evidence; the decision the docs hang on the number stays in the docs.

**The naming seam: planted nulls vs the corpus's planted signals.**
Feature 133 plants *leaks* — :func:`~tripwires.corpus.planted_signals`,
the adversary the whole suite must catch — while this module plants
*nulls* and *real signals*, the two classes whose separation is the
question.  The vocabulary is the spec sentence's own ("separating planted
nulls from real signals"), and the asymmetry (``planted_nulls`` vs
``real_signals``) is the sentence's own too: both populations are
planted, and the reader the naming serves is the one about to hand a
*leak* to the wrong function.

**What this module does not do.**  It does not persist anything — the
stability ledger (feature 129) and the node column (feature 130) own the
figures' persistence, and a deployment wanting the AUC of *its own*
books re-reads their figures and hands the two samples to
:func:`triage_auc`, the pure seam, rather than re-running anything.  It
does not run the probe (feature 125's), re-derive any axis' figure
(127/129/130's runners are called, not reimplemented), or measure the
window-offset axis (feature 128 is not in this member;
:data:`TRIAGE_AXES` names the axes that exist, and the figure moves when
the fourth lands).  And it does not state a verdict: an AUC is a
measurement, not a rejection — the member has no verdict word for it and
needs none, for the reason :mod:`tripwires.errors` gives for having no
verdict error at all.

**Determinism.**  The same (``seed``, ``count``) produce the same figure
bit-for-bit.  Each candidate draws from
``random.Random(f"{seed}:{kind}:{index}")`` — string seeds are hashed
through sha512, which Python guarantees stable across versions (unlike
:meth:`str.__hash__`, which is salted per process) — and every draw is a
``gauss``, the corpus's own primitive.  The panels are built in one
fixed order, the AUC sorts before it sums, and no wall clock, hash
iteration or environment variable enters the record.

**The layering note.**  This module is stdlib-only — dates, mappings,
sorting, square roots and one random stream per candidate — and it
imports only its sibling modules for the runners and the vocabulary they
pin.  No polars, no pyarrow, no lake, no environment, no HTTP, no
database: the M1 experiment is a pure function, runnable in a bare test
process, which is the shape a one-day triage question deserves.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .corpus import CORPUS_GRID, CORPUS_SYMBOLS
from .errors import TripwirePanelError, TripwireStatisticError
from .lookback import LOOKBACK_AXIS, run_lookback_rerun
from .seed_rerun import (
    PERTURBATION_STABILITY_NAME,
    SEED_AXIS,
    run_seed_rerun,
)
from .subsample import SUBSAMPLE_AXIS, run_subsample_rerun
from .time_shuffle import HORIZONS

__all__ = [
    "TRIAGE_AXES",
    "TRIAGE_KINDS",
    "TRIAGE_PERSISTENCE",
    "TRIAGE_POPULATION",
    "TRIAGE_SEED",
    "TRIAGE_SIGNAL_HORIZON",
    "TRIAGE_TRUE_IC",
    "TriageCandidate",
    "TriageFigure",
    "instability_of",
    "planted_nulls",
    "real_signals",
    "run_triage",
    "triage_auc",
]

#: The axes the triage measures — every axis of the perturbation family
#: this member implements, in :data:`~tripwires.seed_rerun.PERTURBATION_AXES`'
#: own order.  The window-offset axis (feature 128) is named as absent
#: rather than skipped quietly: a family figure over axes that were
#: never run is a figure nobody measured, and when the fourth axis lands
#: it joins this tuple and the figure moves — which is the honest
#: behaviour for a family macro-mean, not a compatibility break.
TRIAGE_AXES: tuple[str, ...] = (SEED_AXIS, SUBSAMPLE_AXIS, LOOKBACK_AXIS)

#: The two classes a triage candidate belongs to — the spec sentence's
#: own nouns, closed.  A third kind would be a class the AUC has no
#: branch for, and a misspelling of one of these is a class the figure
#: would silently average over.
TRIAGE_KINDS: tuple[str, ...] = ("planted-null", "real-signal")

#: The seed the two populations are planted from — dated the way
#: :data:`~tripwires.corpus.CORPUS_SEED` is dated, one feature on.  Fixed
#: for the same repeatability reason the corpus's is: the suite asserts
#: the figure in bands against *these* populations, so the measurement
#: the docstring states and the measurement the tests check are the same
#: one, every run, on any machine.
TRIAGE_SEED: int = 20260134

#: Candidates per class.  32 a side makes the AUC's null standard error
#: √((n+m+1)/(12·n·m)) ≈ 0.073 — small enough that the 0.85 branch of
#: the PRD's rule would clear four sigmas, large enough that the whole
#: experiment (three axes, both classes, every candidate) runs in
#: seconds.  A population of one a side is refused by :func:`run_triage`
#: for the reason given there.
TRIAGE_POPULATION: int = 32

#: The information coefficient the real signals carry — the correlation
#: between a signal's score cell and the target cell it was scored
#: against.  Pinned by calibration, not taste: measured over the pinned
#: seed, 0.05 leaves 7 of 32 signals under feature 125's own leak bar on
#: the reference run (the honest boundary the triage exists to sit on),
#: while 0.10 rejects a third and 0.20 all 32 — classes the probe
#: catches before any triage could, at which point the experiment
#: measures the leak bar and not the family.
TRIAGE_TRUE_IC: float = 0.05

#: The persistence of the market-like targets — the variance share each
#: horizon's per-symbol profile carries, the remainder being fresh
#: per-date noise.  A half is a coin split: persistent enough that
#: cross-sectional structure survives the derangement (the world where
#: stability could in principle matter), noisy enough that no honest
#: book's surviving Sharpe is anything but a re-measurement.  Measured
#: over the pinned seed, 0.25 leaves 1 of 32 signals brushing the probe's
#: bar and 0.75 lifts that to 14 of 32 — the signals' own class drifting
#: into leak territory, which is the class the triage must keep honest.
#: The nulls are insensitive across the whole band (1-2 of 32 rejected at
#: 0.25, 0.5, 0.75 and 0.95), so the pin is chosen by the signals' side:
#: 0.5 is the band where the signals' brush stays the honest boundary
#: rather than a leak.
TRIAGE_PERSISTENCE: float = 0.5

#: The horizon the real signals load on — the shortest the spec names,
#: the probe's own horizon policy.  The nulls load on nothing by
#: construction, so the constant is a fact about one class only, and it
#: is carried as a constant rather than a parameter because the triage
#: question is about the *family*, not about one horizon's edge.
TRIAGE_SIGNAL_HORIZON: int = HORIZONS[0]


# -- The populations -------------------------------------------------------------


@dataclass(frozen=True)
class TriageCandidate:
    """One labelled candidate — a score panel, a target bundle, a class.

    The triage's unit of replication.  Built by :func:`planted_nulls` and
    :func:`real_signals`, never by hand: the panels are drawn in one
    fixed order from one per-candidate stream, and a candidate's value to
    the experiment is that its panels are reproducible from the record's
    own terms (``seed``, ``kind``, ``index`` — the last encoded in the
    node id, the first two pinned by the builders).

    Validated shallowly — the node id, the kind, and the two mappings'
    shape — because everything downstream validates panels deeply at its
    own seam: the three axis runners each refuse a malformed panel by
    name, and a second deep validation here would be a second place the
    panel vocabulary lives, the drift the member's one-provenance rule
    exists to prevent.
    """

    #: The candidate's node id — ``triage-null-00`` / ``triage-signal-00``
    #: onward, carrying the class and the index so a verdict a runner
    #: states over this candidate is attributable without a side table.
    node_id: str
    #: The class — one of :data:`TRIAGE_KINDS`.
    kind: str
    #: The score panel, ``{rebalance date: {symbol: score}}``.
    scores: Mapping[dt.date, Mapping[str, float]]
    #: The target bundle, ``{horizon: {rebalance date: {symbol: return}}}``.
    targets: Mapping[int, Mapping[dt.date, Mapping[str, float]]]

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TripwirePanelError(
                f"a triage candidate must name its node, got {self.node_id!r}; "
                "a figure the runners state over an unnamed candidate is a "
                "figure nothing downstream can attribute"
            )
        if self.kind not in TRIAGE_KINDS:
            raise TripwirePanelError(
                f"a triage candidate's kind is one of {', '.join(TRIAGE_KINDS)} "
                f"(the spec sentence's own nouns), got {self.kind!r}; a third "
                "kind is a class the AUC has no branch for"
            )
        for field in ("scores", "targets"):
            if not isinstance(getattr(self, field), Mapping):
                raise TripwirePanelError(
                    f"a triage candidate's {field} must be a mapping, got "
                    f"{type(getattr(self, field)).__name__}; the builders "
                    "hand plain mappings and the runners read nothing else"
                )

    def __hash__(self) -> int:
        # The mappings are not hashable until they collapse to tuples; the
        # fold is order-pinned (dates, then horizons, sorted), so two calls
        # of one builder hash equal, as every record in this workspace does.
        return hash(
            (
                self.node_id,
                self.kind,
                tuple(
                    (day, tuple(sorted(row.items())))
                    for day, row in sorted(self.scores.items())
                ),
                tuple(
                    (
                        horizon,
                        tuple(
                            (day, tuple(sorted(row.items())))
                            for day, row in sorted(series.items())
                        ),
                    )
                    for horizon, series in sorted(self.targets.items())
                ),
            )
        )


def _grid() -> list[dt.date]:
    """The experiment's rebalance grid — the corpus's own width."""
    return [
        dt.date(2024, 1, 1) + dt.timedelta(days=offset)
        for offset in range(CORPUS_GRID)
    ]


def _symbol_names() -> list[str]:
    """The experiment's symbol names — the corpus's own width and shape."""
    return [f"S{index:02d}" for index in range(CORPUS_SYMBOLS)]


def _market_targets(
    rng: random.Random, persistence: float
) -> dict[int, dict[dt.date, dict[str, float]]]:
    """The market-like target bundle — profile plus noise, per horizon.

    Each horizon independently: every symbol draws one persistent profile
    value at standard deviation ``√persistence``, and every date's cell is
    that profile plus fresh noise at ``√(1 − persistence)`` — so the
    profile's share of any cell's variance is exactly the persistence.
    The horizons are drawn independently of each other (the corpus's own
    bundle policy), because the triage's signals load on one horizon and
    must not inherit help from another.  Draw order is fixed — horizon,
    then profile over symbols, then dates, then symbols — and is part of
    the experiment's determinism, not an implementation detail.
    """
    grid = _grid()
    names = _symbol_names()
    profile_scale = math.sqrt(persistence)
    fresh_scale = math.sqrt(1.0 - persistence)
    bundle: dict[int, dict[dt.date, dict[str, float]]] = {}
    for horizon in HORIZONS:
        profile = {
            symbol: rng.gauss(0.0, profile_scale) for symbol in names
        }
        series: dict[dt.date, dict[str, float]] = {}
        for day in grid:
            series[day] = {
                symbol: profile[symbol] + rng.gauss(0.0, fresh_scale)
                for symbol in names
            }
        bundle[horizon] = series
    return bundle


def planted_nulls(
    *, seed: int = TRIAGE_SEED, count: int = TRIAGE_POPULATION
) -> tuple[TriageCandidate, ...]:
    """The honest books — scores with no relationship to their targets.

    ``count`` candidates, the *i*-th drawn from
    ``random.Random(f"{seed}:null:{i}")``: the market-like target bundle
    first, then a score panel of fresh standard normals — a different
    variable from the bundle's noise, so the class carries no alignment,
    no panel-level statistic and no symbol-level structure.  This is the
    class the family must clear; its figures are the noise of a
    re-measurement, and the AUC's denominator is their spread.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the planting seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); the populations are a pure function "
            "of (seed, count), and a non-integer seed names no stream to "
            "draw from"
        )
    if isinstance(count, bool) or not isinstance(count, int):
        raise TripwirePanelError(
            f"a population is a count of candidates, got {count!r} "
            f"({type(count).__name__})"
        )
    grid = _grid()
    names = _symbol_names()
    candidates: list[TriageCandidate] = []
    for index in range(count):
        rng = random.Random(f"{seed}:null:{index}")
        targets = _market_targets(rng, TRIAGE_PERSISTENCE)
        scores = {
            day: {symbol: rng.gauss(0.0, 1.0) for symbol in names}
            for day in grid
        }
        candidates.append(
            TriageCandidate(
                node_id=f"triage-null-{index:02d}",
                kind="planted-null",
                scores=scores,
                targets=targets,
            )
        )
    return tuple(candidates)


def real_signals(
    *, seed: int = TRIAGE_SEED, count: int = TRIAGE_POPULATION
) -> tuple[TriageCandidate, ...]:
    """The aligned books — scores loaded on the shortest horizon's targets.

    The same market-like bundles as :func:`planted_nulls` (drawn from the
    ``signal`` streams, so the two classes' targets are exchangeable
    worlds), with scores ``ic × target + √(1 − ic²) × fresh noise`` on
    :data:`TRIAGE_SIGNAL_HORIZON` — the alignment the evaluator is
    supposed to find, at an information coefficient the probe's own bar
    mostly lets through (see :data:`TRIAGE_TRUE_IC`).  This is the class
    the family is asked to separate from the nulls; that it fails to, at
    honest strength, is the finding the figure carries.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the planting seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); the populations are a pure function "
            "of (seed, count), and a non-integer seed names no stream to "
            "draw from"
        )
    if isinstance(count, bool) or not isinstance(count, int):
        raise TripwirePanelError(
            f"a population is a count of candidates, got {count!r} "
            f"({type(count).__name__})"
        )
    grid = _grid()
    names = _symbol_names()
    loading = TRIAGE_TRUE_IC
    residual = math.sqrt(1.0 - loading * loading)
    candidates: list[TriageCandidate] = []
    for index in range(count):
        rng = random.Random(f"{seed}:signal:{index}")
        targets = _market_targets(rng, TRIAGE_PERSISTENCE)
        series = targets[TRIAGE_SIGNAL_HORIZON]
        scores = {
            day: {
                symbol: loading * series[day][symbol]
                + residual * rng.gauss(0.0, 1.0)
                for symbol in names
            }
            for day in grid
        }
        candidates.append(
            TriageCandidate(
                node_id=f"triage-signal-{index:02d}",
                kind="real-signal",
                scores=scores,
                targets=targets,
            )
        )
    return tuple(candidates)


# -- The statistic ---------------------------------------------------------------


def _figure_number(value: object, where: str) -> float:
    """One instability figure, as a finite float — the AUC's input cell."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TripwireStatisticError(
            f"{where} must be a number, got {value!r} ({type(value).__name__})"
        )
    number = float(value)
    if not math.isfinite(number):
        raise TripwireStatisticError(
            f"{where} is not finite ({value!r}); a NaN or ±inf would reach "
            "the triage figure dressed as a measurement"
        )
    return number


def triage_auc(nulls: Sequence[float], signals: Sequence[float]) -> float:
    """The area under the nulls-vs-signals curve — Mann-Whitney with midranks.

    ``P(null figure > signal figure) + ½ P(tie)``, computed exactly:
    both samples are pooled and sorted, tied values share their midrank,
    and the nulls' rank sum becomes the AUC through
    ``(R_null − n(n+1)/2) / (n·m)`` — exact under any tie pattern, so the
    all-ties case (a class against itself) is exactly one half rather
    than approximately it.  Sums are :func:`math.fsum`, so the result
    does not depend on the order the figures arrived in.  The
    orientation is part of the statistic's meaning: above one half means
    the nulls are the less stable class, below it the axis separates
    with the other sign — a finding, not an error.

    This is the seam a ledger-driven caller reaches: the populations'
    builders are one way to produce two samples, and re-reading feature
    129's rows (or feature 130's columns) for two labelled groups of
    nodes and handing the figure lists here is the other — same
    arithmetic, same orientation, no re-running of anything.

    Raises :class:`~tripwires.TripwireStatisticError` for an empty class
    (an AUC over nothing is not zero, it is undefined) or a non-finite
    or non-numeric figure.
    """
    if not isinstance(nulls, Sequence) or not isinstance(signals, Sequence):
        raise TripwireStatisticError(
            "the AUC is taken over two sequences of figures, got "
            f"{type(nulls).__name__} and {type(signals).__name__}"
        )
    n, m = len(nulls), len(signals)
    if n == 0 or m == 0:
        raise TripwireStatisticError(
            f"the AUC is taken over two non-empty classes, got {n} null and "
            f"{m} signal figures; an AUC over an empty class is not zero — "
            "it is a statistic with nothing under its curve"
        )
    pooled: list[tuple[float, bool]] = [
        (_figure_number(value, "a null figure"), True) for value in nulls
    ] + [(_figure_number(value, "a signal figure"), False) for value in signals]
    pooled.sort(key=lambda pair: pair[0])
    null_rank_sum = 0.0
    index = 0
    total = n + m
    while index < total:
        stop = index
        while stop < total and pooled[stop][0] == pooled[index][0]:
            stop += 1
        # Midrank of pooled[index:stop]: the average of their 1-based
        # ranks, (index + 1 + stop)/2, awarded to every member of the tie.
        midrank = (index + stop) / 2.0 + 0.5
        nulls_in_tie = math.fsum(
            1.0 if is_null else 0.0 for _, is_null in pooled[index:stop]
        )
        null_rank_sum += midrank * nulls_in_tie
        index = stop
    return (null_rank_sum - n * (n + 1) / 2.0) / (n * m)


def instability_of(axis: str, verdict: object) -> float:
    """One verdict's instability figure, read in its own axis' vocabulary.

    The triage ranks magnitudes, and each axis' magnitude is the one its
    own record carries: the seed axis' ``degradation`` **folded** (the
    absolute value — feature 127's figure is signed, one-sided against
    degradation, and a signal that *improved* under the re-run is as
    unstable as one that degraded), the universe-subsample and
    lookback-jitter axes' ``stability`` (already magnitudes).  The read
    is structural — a field-name check, not an ``isinstance``, for the
    same two-copies reason every seam in this member checks structurally
    — and the fold of the seed axis is where this function's one piece
    of arithmetic lives, stated rather than implied.

    Raises :class:`~tripwires.TripwirePanelError` for an axis outside
    :data:`TRIAGE_AXES` (the window-offset axis is refused by name, as
    not implemented), a verdict carrying none of the fields the axis
    ranks, or a figure that is not a finite number.
    """
    if axis not in TRIAGE_AXES:
        raise TripwirePanelError(
            f"the triage ranks the axes it runs ({', '.join(TRIAGE_AXES)}), "
            f"got {axis!r}; the window-offset axis (feature 128) is not in "
            "this member, and a figure over an axis nobody ran is a figure "
            "nobody measured"
        )
    if axis == SEED_AXIS:
        if not hasattr(verdict, "degradation"):
            raise TripwirePanelError(
                f"a {axis} verdict carries a `degradation` figure, and "
                f"{type(verdict).__name__} carries none; the triage reads "
                "each axis' own vocabulary, and a verdict without it is a "
                "verdict from some other feature"
            )
        figure = abs(float(verdict.degradation))  # type: ignore[attr-defined]
    else:
        if not hasattr(verdict, "stability"):
            raise TripwirePanelError(
                f"a {axis} verdict carries a `stability` figure, and "
                f"{type(verdict).__name__} carries none; the triage reads "
                "each axis' own vocabulary, and a verdict without it is a "
                "verdict from some other feature"
            )
        figure = float(verdict.stability)  # type: ignore[attr-defined]
    if not math.isfinite(figure):
        raise TripwirePanelError(
            f"the {axis} figure is not finite ({figure!r}); a NaN or ±inf "
            "would reach the triage figure dressed as a measurement"
        )
    return figure


# -- The figure ------------------------------------------------------------------

#: The axis runners, in :data:`TRIAGE_AXES`' own order — the family's
#: three implementations, called and never reimplemented.  A mapping
#: rather than a dispatch chain so a fourth axis lands as one entry and
#: :data:`TRIAGE_AXES` grows beside it, the one place the family's shape
#: is declared.
_RUNNERS: Mapping[str, Any] = MappingProxyType(
    {
        SEED_AXIS: run_seed_rerun,
        SUBSAMPLE_AXIS: run_subsample_rerun,
        LOOKBACK_AXIS: run_lookback_rerun,
    }
)


@dataclass(frozen=True)
class TriageFigure:
    """The emitted triage figure — per-axis AUCs, their macro-mean, and
    the evidence both were measured from.

    Every term the figure was computed from is carried on it: the two
    populations' sizes, their per-axis mean figures (where the classes
    actually sat — the means are what make an AUC of 0.37 a finding
    about the seed axis rather than a sampling wobble), the
    reference-run rejection counts (the measured boundary with feature
    125's leak bar, the fact the figure's honesty turns on), and the
    planting terms.  The invariants are enforced at construction, so a
    hand-built record that disagrees with its own arithmetic fails
    loudly rather than emitting a triage figure nobody measured — the
    same construction-time discipline the family's verdicts keep.
    """

    #: The family's own name — always
    #: :data:`~tripwires.seed_rerun.PERTURBATION_STABILITY_NAME`; the
    #: figure is the family's, not one axis'.
    tripwire: str
    #: The axes measured, in :data:`TRIAGE_AXES`' own order.
    axes: tuple[str, ...]
    #: Per-axis AUC — ``P(null figure > signal figure) + ½ P(tie)``.
    aucs: Mapping[str, float]
    #: The family figure: the macro-mean of ``aucs`` over ``axes``.
    auc: float
    #: How many planted nulls the figure was measured over.
    null_count: int
    #: How many real signals the figure was measured over.
    signal_count: int
    #: Per-axis mean instability figure of the null class.
    null_means: Mapping[str, float]
    #: Per-axis mean instability figure of the signal class.
    signal_means: Mapping[str, float]
    #: Nulls whose *reference* run the probe's own bar rejected — the
    #: measured false-alarm rate over the planted population.
    null_reference_rejections: int
    #: Signals the probe's own bar rejected on the reference run — the
    #: class' measured brush with leak territory.
    signal_reference_rejections: int
    #: The seed the populations were planted from.
    seed: int
    #: The information coefficient the signals were planted at.
    true_ic: float
    #: The persistence the targets were planted with.
    persistence: float
    #: The rebalance-grid width the populations were planted on.
    grid: int
    #: The universe width the populations were planted on.
    symbols: int

    def __post_init__(self) -> None:
        if self.tripwire != PERTURBATION_STABILITY_NAME:
            raise TripwirePanelError(
                f"a triage figure's tripwire is "
                f"{PERTURBATION_STABILITY_NAME!r}, got {self.tripwire!r}; the "
                "figure is the family's, and a second spelling is a second "
                "tripwire"
            )
        if (
            not isinstance(self.axes, tuple)
            or not all(isinstance(axis, str) for axis in self.axes)
        ):
            raise TripwirePanelError(
                f"a triage figure's axes are a tuple of axis names, got "
                f"{self.axes!r}"
            )
        declared = set(TRIAGE_AXES)
        if not self.axes or len(set(self.axes)) != len(self.axes):
            raise TripwirePanelError(
                f"a triage figure's axes are non-empty and unrepeated, got "
                f"{self.axes!r}"
            )
        if not set(self.axes) <= declared:
            raise TripwirePanelError(
                f"a triage figure's axes come from {', '.join(TRIAGE_AXES)}, "
                f"got {', '.join(self.axes)}; an axis the family does not "
                "run is a figure nobody measured"
            )
        if self.axes != tuple(
            axis for axis in TRIAGE_AXES if axis in set(self.axes)
        ):
            raise TripwirePanelError(
                f"a triage figure's axes are declared in the family's own "
                f"order, got {', '.join(self.axes)}"
            )
        mappings: dict[str, Mapping[str, float]] = {}
        for field, lower, upper in (
            ("aucs", 0.0, 1.0),
            ("null_means", 0.0, math.inf),
            ("signal_means", 0.0, math.inf),
        ):
            raw = getattr(self, field)
            if not isinstance(raw, Mapping):
                raise TripwirePanelError(
                    f"a triage figure's {field} map axis to number, got "
                    f"{type(raw).__name__}"
                )
            if set(raw) != set(self.axes):
                raise TripwirePanelError(
                    f"a triage figure's {field} carry exactly the measured "
                    f"axes ({', '.join(self.axes)}), got "
                    f"{', '.join(map(str, raw)) or 'nothing'}"
                )
            checked: dict[str, float] = {}
            for axis, value in raw.items():
                if isinstance(value, bool) or not isinstance(
                    value, (int, float)
                ):
                    raise TripwirePanelError(
                        f"a triage figure's {field}[{axis!r}] must be a "
                        f"number, got {value!r}"
                    )
                number = float(value)
                if not math.isfinite(number):
                    raise TripwirePanelError(
                        f"a triage figure's {field}[{axis!r}] is not finite "
                        f"({value!r}); a NaN or ±inf would be emitted as a "
                        "measurement"
                    )
                if not lower <= number <= upper:
                    raise TripwirePanelError(
                        f"a triage figure's {field}[{axis!r}] is a "
                        f"{field[:-1] if field != 'aucs' else 'probability'}, "
                        f"in [{lower}, {upper}], got {number!r}"
                        + (
                            "; a mean is a magnitude, and a negative one is "
                            "a signed figure reaching the record"
                            if field != "aucs" and number < 0.0
                            else ""
                        )
                    )
                checked[axis] = number
            mappings[field] = checked
            object.__setattr__(self, field, MappingProxyType(checked))
        if isinstance(self.auc, bool) or not isinstance(self.auc, (int, float)):
            raise TripwirePanelError(
                f"a triage figure's family AUC must be a number, got "
                f"{self.auc!r}"
            )
        family = float(self.auc)
        if not math.isfinite(family) or not 0.0 <= family <= 1.0:
            raise TripwirePanelError(
                f"a triage figure's family AUC is a probability, got "
                f"{self.auc!r}"
            )
        expected = math.fsum(mappings["aucs"].values()) / len(self.axes)
        if family != expected:
            raise TripwirePanelError(
                f"the triage figure says its family AUC is {family!r} but "
                f"the macro-mean of its own per-axis AUCs is {expected!r}; "
                "the record disagrees with its own arithmetic — a figure no "
                "reader can recompute is a figure no decision can hang on"
            )
        object.__setattr__(self, "auc", family)
        for field in ("null_count", "signal_count"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TripwirePanelError(
                    f"a triage figure's {field} is a count of candidates, "
                    f"got {value!r}"
                )
            if value < 2:
                raise TripwirePanelError(
                    f"a triage figure is measured over at least two "
                    f"candidates a class, got {field}={value}; one a side "
                    "is a coin flip the record would carry as a curve"
                )
        for field, count_field in (
            ("null_reference_rejections", "null_count"),
            ("signal_reference_rejections", "signal_count"),
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TripwirePanelError(
                    f"a triage figure's {field} is a count of candidates, "
                    f"got {value!r}"
                )
            if not 0 <= value <= getattr(self, count_field):
                raise TripwirePanelError(
                    f"a triage figure's {field} is a count within its class "
                    f"(0..{getattr(self, count_field)}), got {value}"
                )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TripwirePanelError(
                f"a triage figure's planting seed is an integer, got "
                f"{self.seed!r}"
            )
        for field in ("true_ic", "persistence"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwirePanelError(
                    f"a triage figure's {field} is a number, got {value!r}"
                )
            if not math.isfinite(float(value)) or not 0.0 < float(value) < 1.0:
                raise TripwirePanelError(
                    f"a triage figure's {field} is a share strictly inside "
                    f"(0, 1), got {value!r}"
                )
            object.__setattr__(self, field, float(value))
        for field in ("grid", "symbols"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TripwirePanelError(
                    f"a triage figure's {field} is a count, got {value!r}"
                )
            if value < 2:
                raise TripwirePanelError(
                    f"a triage figure's {field} is at least two, got "
                    f"{value}; below that there is no shuffle and no "
                    "statistic for any candidate to be measured on"
                )

    def __hash__(self) -> int:
        # The mappings collapse to sorted tuples; fsum-verified floats hash
        # as stored, keeping __hash__ consistent with __eq__.
        return hash(
            (
                self.tripwire,
                self.axes,
                tuple(sorted(self.aucs.items())),
                self.auc,
                self.null_count,
                self.signal_count,
                tuple(sorted(self.null_means.items())),
                tuple(sorted(self.signal_means.items())),
                self.null_reference_rejections,
                self.signal_reference_rejections,
                self.seed,
                self.true_ic,
                self.persistence,
                self.grid,
                self.symbols,
            )
        )

    def to_payload(self) -> dict[str, Any]:
        """The figure as a plain mapping — the emitted form of the emitted
        figure, for a log line, a report row or a docs table.

        Mappings collapse to sorted lists of pairs so the payload of one
        run equals the payload of the same run again, byte for byte, in
        any serializer that preserves list order.
        """
        return {
            "tripwire": self.tripwire,
            "axes": list(self.axes),
            "aucs": dict(sorted(self.aucs.items())),
            "auc": self.auc,
            "null_count": self.null_count,
            "signal_count": self.signal_count,
            "null_means": dict(sorted(self.null_means.items())),
            "signal_means": dict(sorted(self.signal_means.items())),
            "null_reference_rejections": self.null_reference_rejections,
            "signal_reference_rejections": self.signal_reference_rejections,
            "seed": self.seed,
            "true_ic": self.true_ic,
            "persistence": self.persistence,
            "grid": self.grid,
            "symbols": self.symbols,
        }


def run_triage(
    *, seed: int = TRIAGE_SEED, count: int = TRIAGE_POPULATION
) -> TriageFigure:
    """Plant the two populations, run every axis over every candidate,
    and emit the triage figure — feature 134's whole answer.

    For each axis in :data:`TRIAGE_AXES`, every candidate of both
    populations goes through that axis' own runner with its pinned
    defaults, and the verdict's figure is read in the axis' own
    vocabulary (:func:`instability_of`); the two classes' figure samples
    become one AUC per axis (:func:`triage_auc`), and the macro-mean
    across the axes is the family figure.  Reference-run rejections are
    counted from the first axis' verdicts — every axis' runner re-runs
    the same full-span reference, so the count is a fact about the
    candidate, counted once.

    Rejected candidates' figures count.  The triage ranks *figures*, not
    verdicts — a candidate whose reference run the probe rejected is
    still a member of its class, and dropping it would silently turn the
    AUC into a figure over the survivors only, which is a different
    (and flattering) experiment.  This is the same reason feature 129's
    ledger persists passing figures: an AUC needs both classes, whole.

    Deterministic in (``seed``, ``count``), bit-for-bit; at the pinned
    32 a side it runs in roughly fifteen seconds — three axes, both
    classes, 192 full re-runs, no I/O of any kind.

    Raises :class:`~tripwires.TripwirePanelError` for a non-integer seed
    or a population under two a side — one candidate per class is an AUC
    of 0, ½ or 1: a coin flip the record would carry as a curve.
    """
    for name, value in (("seed", seed), ("count", count)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TripwirePanelError(
                f"the triage's {name} is an integer, got {value!r} "
                f"({type(value).__name__}); the experiment is a pure "
                "function of (seed, count), and a non-integer names no "
                "stream and no population"
            )
    if count < 2:
        raise TripwirePanelError(
            f"the triage is run over at least two candidates a side, got "
            f"count={count}; one a side is an AUC of 0, ½ or 1 — a coin "
            "flip the record would carry as a curve"
        )
    nulls = planted_nulls(seed=seed, count=count)
    signals = real_signals(seed=seed, count=count)
    null_figures: dict[str, list[float]] = {axis: [] for axis in TRIAGE_AXES}
    signal_figures: dict[str, list[float]] = {axis: [] for axis in TRIAGE_AXES}
    rejections = {"planted-null": 0, "real-signal": 0}
    for axis in TRIAGE_AXES:
        runner = _RUNNERS[axis]
        for candidate in nulls:
            verdict = runner(
                candidate.scores, candidate.targets, node_id=candidate.node_id
            )
            if axis == TRIAGE_AXES[0] and verdict.reference_rejected:
                rejections["planted-null"] += 1
            null_figures[axis].append(instability_of(axis, verdict))
        for candidate in signals:
            verdict = runner(
                candidate.scores, candidate.targets, node_id=candidate.node_id
            )
            if axis == TRIAGE_AXES[0] and verdict.reference_rejected:
                rejections["real-signal"] += 1
            signal_figures[axis].append(instability_of(axis, verdict))
    aucs = {
        axis: triage_auc(null_figures[axis], signal_figures[axis])
        for axis in TRIAGE_AXES
    }
    return TriageFigure(
        tripwire=PERTURBATION_STABILITY_NAME,
        axes=TRIAGE_AXES,
        aucs=aucs,
        auc=math.fsum(aucs[axis] for axis in TRIAGE_AXES) / len(TRIAGE_AXES),
        null_count=len(nulls),
        signal_count=len(signals),
        null_means={
            axis: math.fsum(null_figures[axis]) / len(nulls)
            for axis in TRIAGE_AXES
        },
        signal_means={
            axis: math.fsum(signal_figures[axis]) / len(signals)
            for axis in TRIAGE_AXES
        },
        null_reference_rejections=rejections["planted-null"],
        signal_reference_rejections=rejections["real-signal"],
        seed=seed,
        true_ic=TRIAGE_TRUE_IC,
        persistence=TRIAGE_PERSISTENCE,
        grid=CORPUS_GRID,
        symbols=CORPUS_SYMBOLS,
    )
