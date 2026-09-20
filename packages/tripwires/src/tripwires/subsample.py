"""The universe-subsample re-run — the perturbation-stability probe's third axis, feature 129.

app_spec.xml, "Leakage Tripwires", feature 129: *"System re-runs a candidate
against a 20 percent universe subsample, persisting the subsample stability
figure."*  docs/alpha-engine-prd.md §C6 names it in the sentence that gives the
family its rule — *"Re-run with a different seed, a different start offset, a
different universe subsample.  Degradation beyond threshold is a reject."* — and
§4.5 names the property it measures in the robustness family's own list:
*"Universe-subsample stability"*, one of the features architecture §11.1 records
as **transferring across theme roots**.  Feature 127 is the family's first axis
(the seed); this is the third, and the axis the perturbation-stability probe's
name is most easily mistaken for a restatement of.

**This is not feature 127 with a different knob, and the difference is the whole
feature.**  Feature 127 re-draws the *derangement*, holding the universe fixed:
its perturbation is a different random pairing of the same cross-sections.
This module holds the derangement fixed — the same seed, so the same pairing —
and **thins the universe**, scoring the candidate against a cross-section that
keeps only a fraction of its symbols.  The two axes therefore perturb
orthogonal things, and the evidence that they are different tests is measured
rather than asserted.  Over a 120-date, 30-symbol panel:

* **A whole-panel leak is *not* invariant to this axis — and the bar is set
  with that in mind.**  This is the one place a reader's intuition is likely to
  lead them wrong, so it is stated with the measurement rather than with an
  argument.  The corpus feature 133 maintains carries its statistic in *every*
  symbol of every cross-section, so the temptation is to say the thinning
  cannot disturb it.  It does disturb it: dropping four fifths of the symbols
  drops four fifths of the statistic's *dispersion* as well as its level, and
  the surviving Sharpe is a ratio of the two.  Over a 120-date, 30-symbol panel
  every one of the corpus's four planted leaks reports a subsample figure of
  ≈ 1.71 against ≈ 0.25 for a clean candidate — a clean three-and-a-half-fold
  separation, and a rejection.  This axis therefore *does* catch leakage, by a
  different route from feature 125's: not "the surviving Sharpe is too large"
  but "the surviving Sharpe moved when the universe changed".  Feature 125
  catches these candidates too, at the reference universe, which is why the
  verdict's ``rejected`` is a disjunction and why the leak tests below assert
  *which* cause fired rather than only that one did.
* **Every one of those leaks is invisible to feature 127.**  The same four
  panels through :func:`~tripwires.seed_rerun.run_seed_rerun` report a
  degradation of exactly ``0.0`` — not merely under its bar, but structurally
  zero — because a whole-sample statistic does not depend on *which date* a
  cross-section is joined against, so re-drawing the derangement leaves it
  untouched.  The two axes are therefore not two measurements of one thing:
  every candidate in the maintained corpus is caught by this axis at ≈ 1.71 and
  by the seed axis at 0.00.  That is the sharpest form of the family's
  four-features argument, and it is *asserted* in the suite (both figures, on
  the whole corpus) rather than described here.

  The asymmetry runs the other way too, and the suite states it as the limit of
  what this axis can claim: the figure separates a planted leak from a clean
  candidate about as sharply as feature 125's own comparison does (≈ 1.71
  against ≈ 0.34), so this axis is a *second route to the same verdicts on the
  corpus* rather than a detector of a different population.  Its value is that
  the route is a different one — "the statistic moved when the universe
  changed", not "the statistic was too large in the first place" — so a
  candidate that is stable across universes is evidence the first probe did not
  provide.

That asymmetry is why the family is four features and not one parameterized
one, and it is the same argument feature 127 makes for itself from the other
side: each axis is a different question about the *measurement*, and the union
of the answers is what the rejection §C6 applies is licensed by.

**The figure is a *stability*, not a degradation, and the spec's two words are
not synonyms.**  Feature 129's sentence says *"persisting the subsample
stability figure"* where feature 127's says *"degradation exceeds the
configured threshold"*, and the vocabulary differs because the quantities do.
A degradation names a **direction** — 127's module docstring derives its signed
`(|reference| − |re-run|)` at length — and its rule is one-sided: the re-run
collapsing is the failure, the re-run improving is not.  Stability names
**reproducibility**, and it is two-sided by construction: a subsample that
makes the statistic move *either way* has failed to reproduce it, and a
candidate whose surviving Sharpe happens to *rise* on a thinner universe is no
more stable than one whose Sharpe falls.  So the figure is the magnitude::

    stability = |rerun Sharpe − reference Sharpe| / reference threshold

which is zero exactly when the axis' perturbation changed nothing, and positive
in both directions when it did.  A reader looking for feature 127's
`degradation` on this record will not find it, and that is deliberate — see the
seam note on the record below.

**The threshold's derivation, and the mistake it is easiest to make here.**
The configured bar is *derived* from feature 125's own arithmetic rather than
tuned, and the derivation is short enough to check — but only if the right
fact about the two runs is used, and the wrong fact is the tempting one.

The tempting derivation writes the two surviving Sharpes as **independent**.
Under feature 125's null a surviving Sharpe has standard error `1/√T` over `T`
dates, so a difference of two independent draws has standard deviation `√2/√T`;
in units of feature 125's own threshold `z/√T` — with `z = Φ⁻¹(1 − level/2)`,
the *two-sided* quantile — that is `√2/z`, and the folded figure's bar at level
`level` is `z` of it, so `z` cancels and the bar comes out `√2 ≈ 1.4142`.

**That derivation is wrong, and the module was written with it before the
measurement contradicted it.**  The two runs are not independent: the subsample
is a *subset of the reference universe*, so every symbol it keeps contributes
the *same* noise term to both statistics.  The shared part is proportional to
the kept names and the unshared part to the whole panel, so

    corr(reference, re-run) = √f

— measured at 0.39–0.48 for `f = 0.2` and 0.68–0.72 for `f = 0.5` across
`T ∈ {60, 120, 240, 480}` and 30–60 symbols, against `√0.2 = 0.4472` and
`√0.5 = 0.7071`.  With that correlation the difference of two draws each of
standard deviation `1/√T` has standard deviation `√(2(1 − √f))/√T`, and
expressing it in the same bar's units gives

    σ_stability = √(2(1 − √f)) / z,

so the folded figure's bar at level `level` is `z · σ_stability` and **the `z`
cancels** —

    DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD = √(2(1 − √fraction)) ≈ 1.0515

at the pinned fifth.  The cancellation is the same one the tempting derivation
found; what changes is the factor, from `√2` (the no-shared-names limit,
`f → 0`) to `√(2(1 − √f))`.  Both absences — no `level` term, no `dates` term —
are real properties and are *asserted* in the suite rather than described,
because they are what a reader has most reason to doubt: the figure is measured
in units of a threshold that already carries a `z` and a `√T`, so a bar derived
as "`z` standard deviations of the null" cancels both and is a pure function of
how much of the universe the two runs share.

**The calibration, measured rather than asserted.**  500 null re-runs at each
of ten configurations (`T` ∈ {60, 120, 240, 480}, 30–60 symbols, `f` ∈ {0.10,
0.20, 0.30, 0.50}): the realized `sd/√(2(1−√f))/z` ratio is
0.96–1.03 of prediction — agreement to a few percent, the same order the
`ρ = √f` model holds to — and the derived bar is exceeded at
0.006–0.016 against the nominal 0.01 at every one of them, while `√2` is
exceeded at 0.000–0.002.  So the wrong derivation is not merely unaesthetic: it
is a bar roughly 35% too wide, which passes every candidate the correct one
rejects on this axis.  The suite pins the closed form *and* the rate, and
asserts the `√2` shortcut as **wrong** rather than as close enough — the same
treatment feature 127's own suite gives its `√2` shortcut, for the same reason.

There is a second, structural reason the tempting derivation cannot be right:
`√2` does not depend on the fraction at all, so a fraction of 1.0 would carry a
positive bar, and a fraction of 1.0 is the unperturbed panel whose figure is
identically zero for *every* candidate.  `√(2(1 − √f))` vanishes there, which
is the behaviour the arithmetic has to have; the fraction is refused by name
before the constant is ever consulted, but a derivation that disagreed with
that limit would have been the warning sign.

**A 20 percent subsample is the *count*, not a rounding of it.**  The spec's
sentence names the fraction, so it is a parameter — :data:`DEFAULT_SUBSAMPLE_
FRACTION` is ``0.20`` — and the count drawn from a universe of ``L`` symbols is
``round(fraction · L)`` clamped into ``[2, L]``.  The clamp is not defensive
padding: below two symbols there is no cross-section to average and no
statistic to state, and a fraction of 1.0 is the *unperturbed* panel, whose
figure is a structural zero — the same "a re-run that re-runs nothing" failure
feature 127 refuses by name when its two seeds are equal.  A fraction that
clamps to either end is refused by name for that reason, rather than silently
returned as a perfectly stable candidate that was never thinned.

**Which symbols, and the one thing this module does not model.**  The subsample
is drawn from ``random.Random(seed)`` by the member's own established
primitive — ``sample``, the same stdlib draw feature 133's corpus and this
member's own tests use — from the *sorted* symbol names, so the draw is a pure
function of ``(symbols, fraction, seed)`` and two calls return the same
subsample bit-for-bit.  What this module deliberately does **not** model is
*why* the universe would be thinned: §4.5's "drop 20% of the universe" is a
robustness probe, not a liquidity or capacity model, and a subsample drawn to
respect a PIT membership rule would be a second implementation of the universe
member's own resolution (features 41–44) — the second spelling this member's
one-provenance rule forbids.  The symbols arrive from the panel and the fraction
is drawn from them; a caller wanting a *themed* subsample passes the panels it
means, which is also what makes this axis testable without a membership table.

**What this module does not do.**  It does not perturb the seed (feature 127),
a window offset (128) or a lookback (130 — the same probe's fourth axis, and the
one that persists its figure as ``perturb_stability`` on the node); it does not
permute labels (126), poison a subtree (131), excise a pool (132), maintain the
corpus (133) or decide the triage figure (134).  It does not re-implement the
statistic, the shuffle or the threshold either: the reference run is
:func:`~tripwires.time_shuffle.run_time_shuffle_tripwire` over the panels as
handed in, the re-run is the same function over the *narrowed* panels, and the
figure is one subtraction, one ``abs`` and one division over their results.  The
persistence half is :mod:`tripwires.stability`, which is a different kind of
module on a different lifecycle — this one is a pure function of mappings and
carries no store, no environment and no import of a driver.

**The layering note.**  Stdlib-only, like the rest of the member — arithmetic,
``random`` for the one deterministic draw, mappings, and the two calls below;
no polars, no pyarrow, no lake, no environment, no HTTP, and no import of any
other workspace member.  The panels arrive as plain mappings and leave as one
frozen record, so the frozen evaluator image keeps a probe whose determinism
story (§12) has no moving part: the verdict carries **no wall-clock field at
all**, because a timestamp would make two runs of the same re-run differ and
this record's whole value is that it does not.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import TripwirePanelError
from .seed_rerun import PERTURBATION_AXES, PERTURBATION_STABILITY_NAME
from .time_shuffle import (
    DEFAULT_SHUFFLE_LEVEL,
    DEFAULT_SHUFFLE_SEED,
    HORIZONS,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    run_time_shuffle_tripwire,
    time_shuffle_threshold,
)

__all__ = [
    "DEFAULT_SUBSAMPLE_FRACTION",
    "DEFAULT_SUBSAMPLE_SEED",
    "DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD",
    "SUBSAMPLE_AXIS",
    "SubsampleRerunVerdict",
    "run_subsample_rerun",
    "subsample_figure",
    "subsample_symbols",
]

#: The axis this feature perturbs — the third of
#: :data:`~tripwires.seed_rerun.PERTURBATION_AXES`, in §C6's declaration order
#: (``a different seed, a different start offset, a different universe
#: subsample``).  Spelled by indexing that tuple rather than by a literal here,
#: for the reason :data:`~tripwires.seed_rerun.SEED_AXIS` is: the family's four
#: features must not be able to drift apart on what the shared vocabulary is,
#: and a reader holding one axis has a name to hold this one to.
SUBSAMPLE_AXIS: str = PERTURBATION_AXES[2]

#: The fraction of the universe the re-run keeps — the spec's own ``20 percent``
#: (app_spec.xml feature 129) and §4.5's *"drop 20% of the universe"*, which are
#: the same move read from opposite ends (keep a fifth, drop four fifths: this
#: feature is the *keep*).  A parameter, not a constant, for the reason every
#: knob in this member is: the module pins the spec's value, and a deployment
#: that wants a harsher thinning passes a different one rather than
#: reconfiguring a shared object out from under a replay.  It is deliberately
#: **not** an environment lookup — see the module docstring's layering note.
DEFAULT_SUBSAMPLE_FRACTION: float = 0.20

#: The default seed the subsample is *drawn* under.  Pinned to a fixed integer
#: for the same repeatability reason feature 125 pins its shuffle seed and
#: feature 127 pins its second draw: a stability figure has to be the same
#: figure twice, and a subsample that moved between calls would make every
#: candidate look unstable.  It is deliberately **not**
#: :data:`~tripwires.time_shuffle.DEFAULT_SHUFFLE_SEED`: the two knobs perturb
#: different things (the pairing and the universe) and sharing one integer
#: would make this axis' draw a function of feature 125's, which is the
#: coupling the family's four-features-not-one argument exists to avoid.  There
#: is nothing special about the value beyond being this axis' pinned draw; a
#: deployment that wants a different subsample passes ``subsample_seed``.
DEFAULT_SUBSAMPLE_SEED: int = 20260129

#: The configured stability threshold, in units of the reference run's own
#: rejection threshold — see the module docstring for the derivation.  It is
#: ``√(2(1 − √fraction))``, which for the pinned fifth is ``√(2 − 2/√5)`` ≈
#: 1.0515.  Written as the expression rather than as a literal so the constant
#: *is* its derivation, and asserted in the suite against both the closed form
#: and the measured false-alarm rate — the same treatment feature 127's bar
#: gets, for the same reason.
#:
#: Three things about it are worth naming, because each is a place a reader
#: could reasonably expect something else:
#:
#: * **It carries no ``level`` term.**  The figure is already measured in units
#:   of the reference run's own threshold, which is
#:   ``Φ⁻¹(1 − level/2)/√T``; the bar is that same threshold taken ``z``
#:   standard deviations out, so ``z`` appears in both the numerator and the
#:   denominator and cancels.  The number is a property of the *thinning* — how
#:   much of the two runs' noise is shared — and not of the significance the
#:   probe was calibrated at, which is why the identical constant serves every
#:   level.  (Contrast feature 127, whose ``level`` does **not** cancel: its
#:   figure is a *drop* in a signed statistic, not a distance in units of a
#:   threshold, so its quantile survives.)
#: * **It carries no ``dates`` term.**  ``√T`` cancels for the same reason and
#:   by the same move.  A bar derived as "``z`` standard deviations of the null"
#:   would have to be recomputed whenever the grid widened; this one is a
#:   constant the module pins, and a deployment comparing a 60-date campaign's
#:   figure against a 480-date one is comparing two numbers on one scale.
#: * **It is a function of the fraction.**  That is the honest shape: the bar
#:   is one ``z`` of *the null this re-run actually has*, and the null's spread
#:   depends on how much of the universe both runs share.  It is *not* ``√2``,
#:   which is the answer only in the limit of two runs with **no** names in
#:   common (``f → 0``) — and a reader who assumed independence of the two
#:   statistics would write exactly that, and would be wrong, because the
#:   subsample's names are a *subset* of the reference's and their noise is
#:   shared.  At ``f = 1`` the bar would be zero (the re-run is the panel), which
#:   is why :func:`subsample_symbols` refuses that fraction rather than this
#:   constant having to special-case it.
DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD: float = math.sqrt(
    2.0 * (1.0 - math.sqrt(DEFAULT_SUBSAMPLE_FRACTION))
)


def subsample_symbols(
    symbols: object,
    *,
    fraction: float = DEFAULT_SUBSAMPLE_FRACTION,
    seed: int = DEFAULT_SUBSAMPLE_SEED,
) -> tuple[str, ...]:
    """The subsample of ``symbols`` the re-run is scored against — deterministic.

    ``round(fraction · len(symbols))`` names drawn from ``random.Random(seed)``
    over the *sorted* names, returned sorted.  Sorted twice over, deliberately:
    the draw reads a canonical order so the chosen *set* does not depend on the
    order the caller's mapping happened to iterate in (mapping order is
    insertion order, and the determinism contract §12 does not trust it), and
    the result is sorted again so a reader comparing two subsamples is not
    comparing two spellings of one set.

    The count is clamped into ``[2, len(symbols)]``, and a fraction that clamps
    is refused rather than clamped silently.  Below two symbols there is no
    cross-section to average and no statistic to state; at the full count the
    "subsample" *is* the panel, so the figure it would produce is a structural
    zero — a perfectly stable candidate that was never thinned, which is
    precisely the failure feature 127 refuses by name when both its seeds are
    equal.  A refusal that names it is the honest answer; a clamped draw that
    returned it as a stability figure is not.

    Refuses by :class:`~tripwires.TripwirePanelError` for a non-sequence of
    names, a fraction that is not a finite number strictly inside ``(0, 1)``, a
    seed that is not an integer (a ``bool`` included, since ``True`` is an
    ``int`` and would silently draw seed 1), and a universe too small to hold
    the two names the clamp's floor requires.
    """
    if isinstance(symbols, (str, bytes)) or not hasattr(symbols, "__iter__"):
        raise TripwirePanelError(
            "a universe subsample is drawn from an iterable of symbol "
            f"names, got {type(symbols).__name__}; a string would be "
            "iterated character by character"
        )
    names: list[str] = []
    for symbol in symbols:
        if not isinstance(symbol, str) or not symbol:
            raise TripwirePanelError(
                f"a universe is a set of non-empty symbol names, got "
                f"{symbol!r} ({type(symbol).__name__})"
            )
        names.append(symbol)
    if len(set(names)) != len(names):
        raise TripwirePanelError(
            "the universe carries a symbol name twice; a subsample is a "
            "*subset* of the universe, and a universe with a repeated name "
            "has no subset to be — the draw would over- or under-weight that "
            "name by luck of the iteration order"
        )
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the subsample seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); the subsample is a pure function of "
            "the sorted names, the fraction and the seed, and a non-integer "
            "seed names no stream to draw from"
        )
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
        raise TripwirePanelError(
            f"the subsample fraction must be a number strictly inside (0, 1), "
            f"got {fraction!r} ({type(fraction).__name__})"
        )
    proportion = float(fraction)
    if not math.isfinite(proportion) or not 0.0 < proportion < 1.0:
        raise TripwirePanelError(
            f"the subsample fraction must be a finite number strictly inside "
            f"(0, 1), got {fraction!r}; a fraction of 1 is the unperturbed "
            "panel and its figure is a structural zero, and 0 names a "
            "cross-section with nothing in it"
        )
    ordered = sorted(names)
    if len(ordered) < 2:
        raise TripwirePanelError(
            f"a universe subsample needs at least two symbols to draw from "
            f"and leave one behind, got {len(ordered)}; a one-name universe "
            "has no proper subset and no cross-section to average"
        )
    count = round(proportion * len(ordered))
    if count >= len(ordered) or count < 2:
        raise TripwirePanelError(
            f"a {proportion:.4f} fraction of {len(ordered)} symbols names "
            f"{count}, which is not a proper subsample of at least two names; "
            "a fraction that rounds to the whole universe re-runs the panel "
            "it re-runs — a structural zero — and one that rounds below two "
            "leaves no cross-section to measure. Both are refused by name "
            "rather than returned as a candidate this axis never perturbed"
        )
    return tuple(sorted(random.Random(seed).sample(ordered, count)))


def subsample_figure(
    reference_sharpe: float, rerun_sharpe: float, *, threshold: float
) -> float:
    """The subsample stability figure between two surviving Sharpes.

    ``|rerun Sharpe − reference Sharpe| / threshold`` — the arithmetic of the
    feature, stated once so the verdict below and any reader auditing it cannot
    disagree about what the number is.  Zero exactly when thinning the universe
    changed nothing; positive in *both* directions when it did, because
    stability is two-sided (see the module docstring).

    ``threshold`` is the reference run's own rejection threshold, so the result
    is dimensionless and comparable across grids; it must be a finite positive
    number, because dividing by a zero bar names an infinite figure and dividing
    by a negative one would invert the comparison.

    Pure, and exact: the verdict recomputes this function's result from its own
    terms and refuses a record that disagrees with it, so a persisted stability
    figure is auditable to the last bit rather than to a tolerance.
    """
    for name, value in (
        ("reference_sharpe", reference_sharpe),
        ("rerun_sharpe", rerun_sharpe),
        ("threshold", threshold),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TripwirePanelError(
                f"a subsample stability is taken between two measured Sharpes "
                f"and the bar between them, and {name} is {value!r} "
                f"({type(value).__name__}) — not a number. A figure computed "
                "from a term that is not a measurement would be a stability "
                "figure about nothing"
            )
        if not math.isfinite(float(value)):
            raise TripwirePanelError(
                f"a subsample stability is taken between finite numbers, and "
                f"{name} is {value!r}; the run's own arithmetic refuses a NaN "
                "or ±inf statistic before it reaches this comparison, so one "
                "arriving here came from somewhere other than the probe"
            )
    if float(threshold) <= 0.0:
        raise TripwirePanelError(
            f"a subsample stability is standardized by the reference run's own "
            f"rejection threshold, which is positive, got {threshold!r}; a "
            "zero bar names an infinite figure and a negative one inverts the "
            "very comparison the record states"
        )
    return abs(float(rerun_sharpe) - float(reference_sharpe)) / float(threshold)


@dataclass(frozen=True)
class SubsampleRerunVerdict:
    """Feature 129's answer — a subsample re-run's terms, and the decision on them.

    The record this feature states: feature 125's probe run over the panel as
    handed in and again over the *thinned* panel, the stability figure between
    them, the configured bar it was judged against, the subsample that produced
    it, and the decision.  Every term the comparison was made from is carried —
    the seed rebuilds the pairing both runs scored against, the level and the
    date count rebuild the bar the figure is measured in, the subsample's names
    say exactly which universe the re-run saw, and both statistics sit beside
    the figure they compose — because a rejection that poisons a subtree is an
    irreversible act and must be auditable from the record alone, the same
    reason feature 125's and feature 127's verdicts carry their own terms.

    The invariants are enforced at construction, so a record built by hand — or
    by a later feature whose producer drifted — fails loudly rather than
    carrying a lying stability figure: ``stability`` must recompute from the two
    statistics and the reference threshold, ``stability_rejected`` must equal
    the comparison the figure and the configured bar actually make, ``rejected``
    must be the disjunction of the three named causes, the reference threshold
    must recompute from the level and the date count, the subsample must be a
    proper subset of the symbols the two runs scored, and the outcome word must
    be the decision's own translation into §8's vocabulary.

    **The field names are deliberately not feature 125's, and not feature
    127's either.**  This record has no ``surviving_sharpe`` and no
    ``threshold``; it has ``reference_sharpe``, ``rerun_sharpe`` and
    ``reference_threshold``.  That is a seam and not a style: feature 131 checks
    a verdict *structurally* — by the ten field names a poisoning reads —
    because the factory's scan gives one source file two class objects and
    ``isinstance`` cannot hold across them
    (:func:`~tripwires.poison._validate_failure` states the argument). A record
    shaped like a time-shuffle verdict would pass that check and then be judged
    on ``|surviving_sharpe| > threshold``, which is **feature 125's** comparison
    over **feature 125's** statistic — and for a node this feature rejects
    because the *stability* exceeded its bar, the candidate was typically clean
    at the reference universe, so that comparison is false and the store would
    refuse a poisoning on a mismatched reason.  The names keep the verdicts
    apart so the refusal, when it comes, names the right thing.

    **``stability`` is not feature 127's ``degradation``, and the two do not
    share a name or a sign.**  That record's figure is signed and one-sided
    (a collapse is the failure); this one is a magnitude and two-sided (any
    move is). A record exposing ``degradation`` here would invite a reader to
    apply feature 127's bar to feature 129's number, which is a comparison of
    two different quantities in two different units — this module's bar is
    ``1.05``, and 127's is ``0.77``, and neither means anything against the
    other's figure.
    """

    #: The node whose candidate was re-run.
    node_id: str
    #: The probe that fired — always :data:`~tripwires.seed_rerun.
    #: PERTURBATION_STABILITY_NAME`; carried so a persisted failure names which
    #: of §6.1 step 10's probes it was.
    tripwire: str
    #: The axis that was perturbed — always :data:`SUBSAMPLE_AXIS` here.
    axis: str
    #: The horizon both runs probed — the shortest covered, feature 125's
    #: pinned policy, and necessarily the same for both.
    horizon: int
    #: How many rebalance dates both runs measured — the ``T`` behind the bar.
    dates: int
    #: The probe's two-sided level, restated from the reference run.
    level: float
    #: The seed both runs drew their derangement from.  **The same on both
    #: sides**, and that is this axis' definition rather than an oversight: the
    #: perturbation here is the *universe*, so the pairing is held fixed — which
    #: is exactly the knob feature 127 moves and this one must not.
    seed: int
    #: The seed the subsample was drawn under.
    subsample_seed: int
    #: The fraction of the universe the re-run kept.
    subsample_fraction: float
    #: The universe the reference run scored — every symbol the panel's
    #: cross-sections carried on the measured dates, sorted.  Carried so the
    #: thinning is reconstructible from the record: :attr:`subsample` alone
    #: says what the re-run saw, and without the whole universe a reader cannot
    #: tell a *deliberate* subsample from a complete one.
    symbols: tuple[str, ...]
    #: The symbols the re-run was scored against — the perturbation's own
    #: evidence, so a reader can see *which* universe produced the figure.
    subsample: tuple[str, ...]
    #: The reference run's surviving Sharpe — the number under test.
    reference_sharpe: float
    #: The re-run's surviving Sharpe — the same measurement, thinner universe.
    rerun_sharpe: float
    #: The reference run's rejection threshold — ``Φ⁻¹(1 − level/2)/√dates``.
    #: Read off the reference verdict rather than recomputed, so the bar the
    #: figure is standardized by is provably the one that run was judged
    #: against.
    reference_threshold: float
    #: ``|rerun_sharpe − reference_sharpe| / reference_threshold`` — the
    #: subsample stability figure the spec's sentence says is persisted.
    stability: float
    #: The configured threshold the figure was judged against, in the same
    #: units — ``√(2(1 − √fraction))`` by default, and level- and grid-free
    #: (see the module docstring).
    stability_threshold: float
    #: ``True`` when the figure exceeded the configured threshold — the spec's
    #: own cause on this axis, and the cause the configured bar governs.
    stability_rejected: bool
    #: ``True`` when the run being re-run stated a failure, under its own
    #: comparison.  Feature 125 found leakage, and this record must not launder
    #: that into a pass.
    reference_rejected: bool
    #: ``True`` when the thinner universe's own probe found leakage the
    #: reference draw did not.
    rerun_rejected: bool
    #: The decision: any of the three named causes above.
    rejected: bool
    #: The decision in §8's trial vocabulary — ``tripwire_fail`` when rejected,
    #: ``ok`` when the re-run states no failure.
    outcome: str

    def __post_init__(self) -> None:
        # Validates only, like the records it sits beside; the constructor of
        # a value this module builds normalizes nothing.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TripwirePanelError(
                "a subsample re-run verdict must name the node whose candidate "
                f"it re-ran, got {self.node_id!r}"
            )
        if self.tripwire != PERTURBATION_STABILITY_NAME:
            raise TripwirePanelError(
                f"a subsample re-run verdict's tripwire is "
                f"{PERTURBATION_STABILITY_NAME!r}, got {self.tripwire!r}; both "
                "runs of this feature are time-shuffle probes and this record "
                "is not one of them, so naming it "
                f"{TIME_SHUFFLE_NAME!r} would make a re-run indistinguishable "
                "from the run it re-runs"
            )
        if self.axis != SUBSAMPLE_AXIS:
            raise TripwirePanelError(
                f"a subsample re-run verdict's axis is {SUBSAMPLE_AXIS!r}, got "
                f"{self.axis!r}; this feature thins the universe, and a record "
                "naming another axis would be a stability figure about a knob "
                "this module never moved"
            )
        if self.axis not in PERTURBATION_AXES:
            raise TripwirePanelError(
                f"a perturbation axis is one of "
                f"{', '.join(PERTURBATION_AXES)}, got {self.axis!r}"
            )
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise TripwirePanelError(
                f"a subsample re-run verdict's horizon must be an integer "
                f"period count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise TripwirePanelError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)})"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise TripwirePanelError(
                f"a subsample re-run verdict's date count must be an integer, "
                f"got {self.dates!r}"
            )
        if self.dates < 2:
            raise TripwirePanelError(
                f"a subsample re-run measures at least two dates, got "
                f"{self.dates}; below that there is no shuffle, no dispersion "
                "and no bar, and a stability figure over one date states a "
                "re-run that never ran"
            )
        for field in ("seed", "subsample_seed"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TripwirePanelError(
                    f"a subsample re-run verdict's {field} must be an integer, "
                    f"got {value!r}"
                )
        for field in (
            "level",
            "subsample_fraction",
            "reference_sharpe",
            "rerun_sharpe",
            "reference_threshold",
            "stability",
            "stability_threshold",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwirePanelError(
                    f"a subsample re-run verdict's {field} must be a number, "
                    f"got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwirePanelError(
                    f"a subsample re-run verdict's {field} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the node record "
                    "dressed as a stability figure"
                )
            object.__setattr__(self, field, float(value))
        if not 0.0 < self.level < 1.0:
            raise TripwirePanelError(
                f"a subsample re-run verdict's level is a false-alarm rate "
                f"strictly inside (0, 1), got {self.level!r}"
            )
        if not 0.0 < self.subsample_fraction < 1.0:
            raise TripwirePanelError(
                f"a subsample re-run verdict's fraction is strictly inside "
                f"(0, 1), got {self.subsample_fraction!r}; a fraction of 1 is "
                "the unperturbed panel and its figure is a structural zero"
            )
        if not isinstance(self.symbols, tuple) or len(self.symbols) < 2:
            raise TripwirePanelError(
                "a subsample re-run verdict carries the universe it thinned, "
                f"and a universe holds at least two symbols, got {self.symbols!r}"
            )
        if not isinstance(self.subsample, tuple) or not self.subsample:
            raise TripwirePanelError(
                "a subsample re-run verdict carries the symbols its re-run was "
                f"scored against, got {self.subsample!r}; the figure is about "
                "*which* universe the candidate saw, and a record that could "
                "not say would be unauditable"
            )
        for field in ("symbols", "subsample"):
            names = getattr(self, field)
            for symbol in names:
                if not isinstance(symbol, str) or not symbol:
                    raise TripwirePanelError(
                        f"a subsample re-run verdict's {field} names non-empty "
                        f"symbol names, got {symbol!r}"
                    )
            if len(set(names)) != len(names):
                raise TripwirePanelError(
                    f"a subsample re-run verdict's {field} are distinct; a "
                    "repeated name would over-weight that symbol's "
                    "contribution to the cross-section the figure was measured "
                    "over"
                )
        if not set(self.subsample) < set(self.symbols):
            raise TripwirePanelError(
                f"the subsample re-run verdict's subsample "
                f"({len(self.subsample)} of {len(self.symbols)} symbols) is "
                "not a *proper* subset of the universe it claims to have "
                "thinned; the whole point of this axis is that the re-run saw "
                "strictly fewer symbols than the run it re-runs, and a record "
                "whose two universes are equal states a perturbation that "
                "never happened — a stability figure of exact zero"
            )
        if self.reference_threshold <= 0.0:
            raise TripwirePanelError(
                f"a subsample re-run verdict's reference threshold is positive, "
                f"got {self.reference_threshold!r}; the figure is standardized "
                "by it, and a bar of zero names an infinite stability"
            )
        expected_threshold = time_shuffle_threshold(self.dates, level=self.level)
        if self.reference_threshold != expected_threshold:
            raise TripwirePanelError(
                f"the subsample re-run verdict says its reference threshold is "
                f"{self.reference_threshold!r} but level {self.level!r} over "
                f"{self.dates} dates standardizes to {expected_threshold!r}; "
                "the record disagrees with its own arithmetic, and a figure "
                "measured in a bar no reader can recompute is a stability "
                "figure no reader can size"
            )
        if self.stability_threshold <= 0.0:
            raise TripwirePanelError(
                f"a subsample re-run verdict's configured stability threshold "
                f"is positive, got {self.stability_threshold!r}; a threshold of "
                "zero rejects every candidate the thinning moved at all — "
                "which is every candidate — and a negative one rejects none"
            )
        expected_stability = subsample_figure(
            self.reference_sharpe,
            self.rerun_sharpe,
            threshold=self.reference_threshold,
        )
        if self.stability != expected_stability:
            raise TripwirePanelError(
                f"the subsample re-run verdict says its stability is "
                f"{self.stability!r} but its own two statistics against the "
                f"reference threshold standardize to {expected_stability!r} "
                f"(|{self.rerun_sharpe!r} − {self.reference_sharpe!r}| over "
                f"{self.reference_threshold!r}); the record disagrees with the "
                "arithmetic it reports, so it was built somewhere other than "
                "this module's comparison"
            )
        for field in (
            "stability_rejected",
            "reference_rejected",
            "rerun_rejected",
            "rejected",
        ):
            if not isinstance(getattr(self, field), bool):
                raise TripwirePanelError(
                    f"a subsample re-run verdict's {field} is a boolean, got "
                    f"{getattr(self, field)!r}"
                )
        expected_stability_rejected = self.stability > self.stability_threshold
        if self.stability_rejected != expected_stability_rejected:
            raise TripwirePanelError(
                f"the subsample re-run verdict says stability_rejected="
                f"{self.stability_rejected!r} but its own terms decide "
                f"otherwise ({self.stability!r} against the configured "
                f"{self.stability_threshold!r}); the record states a rule it "
                "does not apply, and a rejection nothing can re-derive is a "
                "rejection nothing can audit"
            )
        expected_rejected = (
            self.stability_rejected
            or self.reference_rejected
            or self.rerun_rejected
        )
        if self.rejected != expected_rejected:
            raise TripwirePanelError(
                f"the subsample re-run verdict says rejected={self.rejected!r} "
                f"while its own causes are stability_rejected="
                f"{self.stability_rejected!r}, reference_rejected="
                f"{self.reference_rejected!r} and rerun_rejected="
                f"{self.rerun_rejected!r}; the decision is their disjunction, "
                "and a record whose bit is not the disjunction of the causes it "
                "carries states a failure nothing produced"
            )
        if self.outcome not in TRIPWIRE_OUTCOMES:
            raise TripwirePanelError(
                f"a subsample re-run verdict's outcome is one of "
                f"{', '.join(TRIPWIRE_OUTCOMES)} (§8's vocabulary), got "
                f"{self.outcome!r}"
            )
        expected_outcome = "tripwire_fail" if self.rejected else "ok"
        if self.outcome != expected_outcome:
            raise TripwirePanelError(
                f"the subsample re-run verdict says rejected={self.rejected!r} "
                f"but carries outcome {self.outcome!r}; the outcome word is the "
                "decision's own translation into the trial vocabulary, and the "
                "two spellings of one fact cannot disagree"
            )

    @property
    def symbols_dropped(self) -> tuple[str, ...]:
        """The complement — what the thinning took away.

        Not persisted and not a second statistic: it exists so a reader asking
        *what did this axis actually remove?* does not have to know that the
        answer is the panel's symbols minus :attr:`subsample`, and so that a
        report of an unstable candidate can name the names whose absence moved
        it.  Empty is impossible — the entry point refuses a fraction that
        would leave the whole universe — so a caller may read this as a real
        subtraction rather than as a may-be-empty case.
        """
        return tuple(
            symbol for symbol in self.symbols if symbol not in set(self.subsample)
        )

    def __hash__(self) -> int:
        # Consistent with __eq__, as every record in this workspace is; the
        # fields are all hashable, so no fold is needed.
        return hash(
            (
                self.node_id,
                self.tripwire,
                self.axis,
                self.horizon,
                self.dates,
                self.level,
                self.seed,
                self.subsample_seed,
                self.subsample_fraction,
                self.symbols,
                self.subsample,
                self.reference_sharpe,
                self.rerun_sharpe,
                self.reference_threshold,
                self.stability,
                self.stability_threshold,
                self.stability_rejected,
                self.reference_rejected,
                self.rerun_rejected,
                self.rejected,
                self.outcome,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"SubsampleRerunVerdict(node={self.node_id!r}, "
            f"{self.dates} dates, {len(self.subsample)} symbols, "
            f"{self.reference_sharpe:+.4f}→{self.rerun_sharpe:+.4f}, "
            f"stability={self.stability:.4f} against "
            f"{self.stability_threshold:.4f}, outcome={self.outcome!r})"
        )


def _narrowed(
    panel: Mapping[dt.date | str, Mapping[str, float]], kept: frozenset[str]
) -> dict[dt.date | str, dict[str, float]]:
    """One panel, restricted to ``kept`` — dates the thinning empties are dropped.

    Feature 75's absence rule read from the other side: a date whose cross-
    section shares no symbol with the subsample is not in that date's
    cross-section.  Dropping such a date rather than passing it through empty is
    what the rule says, and it matters here because the probe refuses a panel
    whose date carries nothing — an empty cross-section would surface as a
    malformed-panel refusal a long way from this line.
    """
    narrowed: dict[dt.date | str, dict[str, float]] = {}
    for day, row in panel.items():
        cells = {symbol: value for symbol, value in row.items() if symbol in kept}
        if cells:
            narrowed[day] = cells
    return narrowed


def run_subsample_rerun(
    scores: Mapping[dt.date | str, Mapping[str, float]],
    targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
    *,
    node_id: str,
    fraction: float = DEFAULT_SUBSAMPLE_FRACTION,
    subsample_seed: int = DEFAULT_SUBSAMPLE_SEED,
    seed: int = DEFAULT_SHUFFLE_SEED,
    level: float = DEFAULT_SHUFFLE_LEVEL,
    threshold: float = DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD,
) -> SubsampleRerunVerdict:
    """Re-run the probe against a universe subsample and state the verdict — feature 129.

    The feature, in order: run feature 125's probe on ``(scores, targets)``
    under ``seed``; draw a ``fraction`` subsample of the universe the reference
    run actually scored; run the same probe under the **same seed** over the
    panels restricted to that subsample; measure the stability between the two
    surviving Sharpes in units of the *reference* run's own rejection threshold;
    and reject when that figure exceeds the configured ``threshold``, or when
    either run's own probe found leakage.

    The seed is deliberately **shared** by both runs and is a single parameter
    here, where feature 127 takes two.  That is this axis' definition: the
    perturbation is the *universe*, so the derangement — the knob feature 127
    moves — is held fixed, and a caller who wanted both axes moved at once would
    be running two features' perturbations in one measurement and would learn
    which of them caused the figure.

    Deterministic in ``(scores, targets, node_id, fraction, subsample_seed,
    seed, level, threshold)`` — the same re-run taken twice returns the same
    verdict bit-for-bit, which is what a stability figure has to be if a
    deployment is to compare one campaign's against another's.

    Raises :class:`~tripwires.TripwirePanelError` for a malformed panel, a
    bundle sharing no horizon with the scores, or fewer than two shared
    rebalance dates — the refusals the probe itself makes, propagated from the
    reference run so a caller sees one cause rather than two frames of the same
    one; and for a ``fraction`` or a universe the thinning cannot make a proper
    subsample of, which is this feature's own refusal because it is this
    feature's own way of measuring nothing.  Raises
    :class:`~tripwires.TripwireStatisticError` when either run's per-date series
    never varied.  A *detected failure is not an exception*: the causes are
    values on the verdict, because a re-run that raised on detection would be
    indistinguishable at the ledger from one that crashed.
    """
    if not isinstance(node_id, str) or not node_id.strip():
        raise TripwirePanelError(
            f"the subsample re-run must name the node whose candidate it "
            f"re-runs, got {node_id!r}; a verdict that rejects a node it cannot "
            "name is a rejection nothing downstream can attribute"
        )
    if isinstance(subsample_seed, bool) or not isinstance(subsample_seed, int):
        raise TripwirePanelError(
            f"the subsample seed must be an integer, got {subsample_seed!r} "
            f"({type(subsample_seed).__name__}); the subsample is a pure "
            "function of the sorted symbols, the fraction and the seed, and a "
            "non-integer seed names no stream to draw from"
        )
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the shuffle seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); both runs draw their derangement from it "
            "and a non-integer one names no stream"
        )
    # The reference run first, so a panel the probe cannot measure refuses once,
    # from the run whose terms the record reports.
    reference = run_time_shuffle_tripwire(
        scores, targets, node_id=node_id, seed=seed, level=level
    )
    # The universe is read off the reference run's *own* measured dates and
    # horizon rather than off the caller's mappings: the probe resolves both
    # (shortest covered horizon, dates with a non-empty join), and a subsample
    # drawn from a wider grid would thin symbols the reference run never scored.
    series = targets[reference.horizon]
    measured = [
        day for day in series if set(series[day]) & set(scores.get(day, {}))
    ]
    universe: set[str] = set()
    for day in measured:
        universe |= set(series[day]) & set(scores[day])
    if not universe:
        raise TripwirePanelError(
            "the reference run measured no symbol at all, so there is no "
            "universe to thin; a re-run against a subsample of nothing would "
            "state a stability figure about a panel that was never scored"
        )
    subsample = subsample_symbols(
        sorted(universe), fraction=fraction, seed=subsample_seed
    )
    kept = frozenset(subsample)
    narrowed_scores = _narrowed(scores, kept)
    narrowed_targets = {
        horizon: _narrowed(target_series, kept)
        for horizon, target_series in targets.items()
    }
    rerun = run_time_shuffle_tripwire(
        narrowed_scores,
        narrowed_targets,
        node_id=node_id,
        seed=seed,
        level=level,
    )
    if rerun.horizon != reference.horizon or rerun.dates != reference.dates:
        raise TripwirePanelError(
            f"the two runs of one subsample re-run disagree about what they "
            f"measured (horizon {reference.horizon}/{rerun.horizon}, "
            f"{reference.dates}/{rerun.dates} dates); both runs contain every "
            "symbol of the subsample on every date the reference run measured, "
            "so thinning the universe can move the statistic and nothing else "
            "— a disagreement means the two runs were not the same probe"
        )
    stability = subsample_figure(
        reference.surviving_sharpe,
        rerun.surviving_sharpe,
        threshold=reference.threshold,
    )
    stability_rejected = stability > threshold
    rejected = stability_rejected or reference.rejected or rerun.rejected
    return SubsampleRerunVerdict(
        node_id=reference.node_id,
        tripwire=PERTURBATION_STABILITY_NAME,
        axis=SUBSAMPLE_AXIS,
        horizon=reference.horizon,
        dates=reference.dates,
        level=reference.level,
        seed=reference.seed,
        subsample_seed=subsample_seed,
        subsample_fraction=float(fraction),
        symbols=tuple(sorted(universe)),
        subsample=subsample,
        reference_sharpe=reference.surviving_sharpe,
        rerun_sharpe=rerun.surviving_sharpe,
        reference_threshold=reference.threshold,
        stability=stability,
        stability_threshold=threshold,
        stability_rejected=stability_rejected,
        reference_rejected=reference.rejected,
        rerun_rejected=rerun.rejected,
        rejected=rejected,
        outcome="tripwire_fail" if rejected else "ok",
    )
