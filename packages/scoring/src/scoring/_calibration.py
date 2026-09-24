"""Feature 266, the calibration figures — sensitivity and specificity
over the planted nulls, answered as the base-rate independent pair that
``FDR_deploy`` is reweighted from.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 266: *System
computes sensitivity and specificity on planted nulls, which returns both
as base-rate independent figures.*  docs/alpha-engine-prd.md §4.1.3 states
why the pair and not the raw rate (line 144): *"Sensitivity and
specificity are base-rate independent, so measure them where you have
power for both, then reweight"*, with the reweighting named three lines
later — ``FDR_deploy = π₀(1 − specificity) / [π₀(1 − specificity) +
(1 − π₀)·sensitivity]``, π₀ ≈ 0.9 — and prd §11's scorecard names the
pair's station (line 539): *"Sensitivity / specificity on planted nulls
(base-rate independent)"* — tracked, not targeted.  prd §12's M2 exit is
the pair's first consumer (line 590: *"a measured baseline on planted
nulls — sensitivity, specificity, and per-commit OOS IR"*).  docs
§10.3 places the computation inside the process this member already
holds (lines 509-515): the scorer that answers the raw rate *"also
emits ``FDR_deploy``, reweighted to the deployment base rate, because
sensitivity and specificity are base-rate independent while the raw
in-campaign rate is an artifact of ``φ``"*.  This module is the figures
half of that sentence.  The reweighting is feature 267's arithmetic, the
rejection of the raw rate as a dashboard number is feature 268's own
sentence, and neither is restated here.

**One confusion over the planted bit, and never a third number.**  The
planted population and the picks the policy committed to it form the
2×2 every figure in this family reads off — the same four cells the
bootstrap member's ground-truth reference spells for the non-financial
worlds (feature 189's confusion matrix, a sibling shape reached through
this member's own held bit and never imported, because a member never
imports a member): true positives (real and committed), false positives
(null and committed), false negatives (real and left uncommitted) and
true negatives (null and left uncommitted).  :attr:`CalibrationFigures.
sensitivity` is ``TP / (TP + FN)`` — *of the planted reals, the fraction
the policy found* — and :attr:`CalibrationFigures.specificity` is
``TN / (TN + FP)`` — *of the planted nulls, the fraction the policy
correctly left alone*, the class whose complement a false discovery
rides on.  The picks are a *declaration*, the set of nodes the campaign
claimed as discoveries: two replays committing to one node are two picks
for the rate (feature 265's multiset law) and one discovery for these
figures, because a node is either found or not and the population, not
the pick collection, carries both denominators.  An ask that committed
to nothing is therefore *answered* — sensitivity ``0.0``, specificity
``1.0``, the corner where nothing was found and nothing was wrongly
declared — where feature 265's empty ask is refused, because a rate over
zero picks is ``0/0`` and a class over a planted population is not: the
two stances are different facts about different denominators, and each
is the honest one for its own figure.

**The verb lands on the process, and the feature graph left it no other
door.**  app_spec.xml gives this feature ``depends_on="265"``, and 265's
own module docstring reserved the growth explicitly: the calibration
figures that follow it *"are further answers off the same held labels
and will land as their own verbs on this process or beside it."*
Feature 269 took the door beside the process — its Type-A metric is the
rate the process already answers, so its seam duck-reads the one public
verb and asks nothing else.  This feature cannot: its denominators are
the *planted classes* — how many of the population's nodes are real,
how many null — and no number the rate lets out carries either count
(a rate over the picks says nothing about the nodes nobody picked, and
deriving a class size means reading ``is_null``, the bit prd §4.2
grants to exactly one component).  So the verb is
:meth:`scoring.NullPickScorer.calibration_figures` — feature 266's own
verb on the process feature 265 built, reading each planted node's
label inside through the same held sidecar and the same canonical join,
and answering this module's value.  The class's barrier law survives
the growth untouched: no accessor for the sidecar, no label cache, no
count of nulls beside the figures (a bare float is 265's whole answer,
and two bare floats are this one's), a ``repr`` that still names the
class and nothing it holds.

**Base-rate independence is the answer's shape, not a footnote.**  Both
figures are conditional *within* a ground-truth class, so the campaign's
null fraction ``φ`` — a design constant §4.1.1 fixes by a floor rule —
cancels: plant twice as many nulls and let the policy declare the same
fraction of each class, and the raw rate moves while both figures stay
bit-identical.  The value makes that structural by what it refuses to
carry: no third field, no figure that divides by the declaration's size
(precision, accuracy, the in-campaign rate — every one of them a
function of ``φ``), and no ``π₀`` anywhere, because a base rate handed
to this verb would let the caller fold feature 267's projection into
the measurement 267 exists to project *from*.  §4.1.3 buys exactly this
separation — measure where there is power for both, reweight once, at
the end, in one place — and docs §10.3's line that the raw rate *"is an
artifact of ``φ``"* is the same law from the other side.

**The floor problem is a refusal, never a default.**  prd §4.1.1 states
the plant's own requirement (line 121): *"A tree needs at least two null
roots and two real roots or it contributes almost nothing to either
sensitivity or specificity."*  A population whose labels hold no reals
has no sensitivity to measure — there is nothing for a discovery to
find — and one whose labels hold no nulls has no specificity — a
campaign of nothing but reals cannot be wrongly declared against.  Both
are refused rather than answered ``0.0`` or ``1.0``, the stance the
bootstrap member's reference takes toward an empty class and this
member's :mod:`scoring._switches` takes toward an unlabelled horizon:
unknown is not zero, and a stand-in figure would be the calibration
§4.1.3 says to buy, bought without the class it was priced on.  The
same family refuses the rest of the malformed asks: a population that
is not the planted nodes themselves, one planted twice, an empty plant,
and a pick the population does not hold — a discovery claimed outside
the measured whole would count on neither side of either fraction,
which is a fraction over a whole nobody chose.

**What this law deliberately does not do.**  It computes no
``FDR_deploy`` — the π₀ reweighting is feature 267's arithmetic over
exactly the pair this value carries, and 268's headline rejection stands
over that figure, not these.  It prices nothing: β₂ charges the raw
rate (feature 258) and no β-term reads these figures — §11's scorecard
tracks them, and a term that charged on a class-conditional figure
would steer the loop on a number the campaign's design constant cannot
move.  It persists nothing: the per-campaign row docs §16 lists among
the research metrics (line 909) is the ops member's feature (344's),
which reads these figures and stores them — the same division 269's
Type-B trend takes toward feature 345.  It enumerates no population:
which nodes a campaign planted is the caller's declaration of the whole
(the sidecar labels whatever the oracle wrote, and this verb refuses a
node it holds no entry for rather than guessing a class for it), the
same caller-declared stance every cohort-shaped seam in this workspace
takes.  And it takes no component and no seat: it rides the process
feature 265 already registered, reached through the member's own
namespace — the growth that docstring reserved and this feature is.

Stdlib only, and import-cheap: :mod:`math` for the finiteness gate and
:mod:`dataclasses` for the value, the member's own rate bound for the
narrowing, and the member's own error — no third-party import at module
scope, so the factory's scan (which imports this package to fire its
``@register`` builders) pays nothing for the law.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real

from ._nullpicks import RATE_BOUND
from .errors import CalibrationFiguresError

__all__ = [
    "CalibrationFigures",
]


@dataclass(frozen=True)
class CalibrationFigures:
    """The calibration figures' answer — sensitivity and specificity,
    each its own field and nothing besides.

    A frozen value, for the same reason :class:`~scoring.WorldScore`,
    :class:`~scoring.AggregatedObjective` and
    :class:`~scoring.ErrorAccounting` are frozen: these are the two
    figures feature 267's ``FDR_deploy`` will be reweighted from and
    feature 344's metrics row will persist, and a value that could be
    edited after the fact would be a mutable handle to a measurement
    already made.  The fields:

    * :attr:`sensitivity` — ``TP / (TP + FN)``: *of the planted reals,
      the fraction the policy's committed picks found*, a finite real
      in ``[0, 1]``.  Both ends are measurements and both are honored:
      ``0.0`` is a campaign that found none of its reals (the honest
      answer for a policy that committed to nothing at all), ``1.0``
      one that found every one.
    * :attr:`specificity` — ``TN / (TN + FP)``: *of the planted nulls,
      the fraction the policy correctly left uncommitted*, a finite
      real in ``[0, 1]`` — the class ``1 − specificity`` a false
      discovery rides on, and the figure prd §4.1.3's reweighting leans
      on hardest.

    Every field is validated at construction — the stance the world
    score takes and every value after it inherits — so a value built by
    the verb and one built by hand answer identically to the law.  There
    is deliberately no third field: no confusion counts (the process's
    law lets figures out, never a census of the classes), no figure
    that divides by the declaration's size, and no base rate — the
    three shapes a base-rate dependent number could wear, and the ones
    §4.1.3's *"base-rate independent"* exists to keep out of the pair.
    """

    #: Sensitivity — of the planted real nodes, the fraction the
    #: campaign's committed picks found.  ``TP / (TP + FN)`` over the
    #: planted population, one correctly-rounded division of two
    #: integers, so the number is exact and order-independent (§12).
    sensitivity: float

    #: Specificity — of the planted null nodes, the fraction the
    #: campaign left uncommitted.  ``TN / (TN + FP)``, the twin of
    #: :attr:`sensitivity` on the other class, and the figure whose
    #: complement ``FDR_deploy``'s reweighting leans on hardest.
    specificity: float

    def __post_init__(self) -> None:
        # Each figure narrowed by the same bound, stated once for the
        # member by feature 258's RATE_BOUND — a fraction of a class is
        # a number between none and all of it — so the value and the
        # terms that will consume it cannot disagree about what a
        # figure is.
        object.__setattr__(
            self, "sensitivity", _require_figure(self.sensitivity, "sensitivity")
        )
        object.__setattr__(
            self, "specificity", _require_figure(self.specificity, "specificity")
        )


# -- the seam's private vocabulary ------------------------------------------


def _require_figure(value: object, field: str) -> float:
    """Narrow one calibration figure to a finite ``float`` in ``[0, 1]``.

    The same quantity, the same bound, one spelling:
    :data:`~scoring.RATE_BOUND` is the fact feature 258's seam states
    for the rate it charges, :mod:`scoring._accounting` restates for
    Type-A's metric, and this module states for the class-conditional
    pair — a fraction of a class is a number between none and all of
    it.  ``int`` admitted and narrowed (``0`` and ``1`` are
    measurements), ``bool`` refused before it (a ``bool`` is an ``int``
    in Python's hierarchy and not a fraction of a class), NaN and ±inf
    refused because a figure that is not a measurement cannot condition
    on a class, and an out-of-bound figure refused rather than clamped
    — the likeliest thing wearing either name being a *count* of found
    reals or of clean nulls handed where the fraction belongs, which
    clamped to an endpoint would charge a calibration nobody measured.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise CalibrationFiguresError(
            f"{field} must be a base-rate independent figure — a fraction "
            f"of a planted class — as a real number, got {value!r} "
            f"({type(value).__name__}): the pair is what prd §4.1.3 "
            f"reweights into FDR_deploy and what its formula consumes, "
            f"and a value that is not a real is not a fraction (feature "
            f"266, prd §4.1.3)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise CalibrationFiguresError(
            f"{field} must be finite, got {narrowed!r}: a NaN would make "
            f"one of the calibration figures a NaN the reweighting "
            f"silently drops, and an infinity is not a fraction of a "
            f"planted class (feature 266, prd §4.1.3)"
        )
    if not 0.0 <= narrowed <= RATE_BOUND:
        raise CalibrationFiguresError(
            f"{field} must be a figure in [0.0, {RATE_BOUND!r}], got "
            f"{narrowed!r}: the figure is a fraction of one planted class "
            f"— the reals it found, or the nulls it left alone — so it is "
            f"bounded by construction. A value outside the bound is not a "
            f"high figure; it is a number that has stopped being one, and "
            f"the likeliest thing wearing its name is a *count* of nodes, "
            f"which the verb refuses to let out and this value refuses to "
            f"receive (feature 266, prd §4.1.3)"
        )
    return narrowed
