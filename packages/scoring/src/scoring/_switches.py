"""Feature 261, the beta-five switch penalty — the formula's fifth term,
one charge per regime crossing of the scored horizon.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 261: *System
subtracts a beta-five term proportional to switch cost times regime switch
count, which returns the adjusted score* — the fifth line of the block
docs/alpha-engine-prd.md §7.1 states (line 318) and
docs/nullius-tech-architecture.md §10.3 restates (line 495):

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged               # five penalties, each its own feature
            …
            − β₅ · switch_cost · n_regime_switches   # ← this module's line (§7.1 line 323)

Five of the six β-terms take away, and this one takes away for the one
thing none of the others can see: the horizon's own churn.  Every regime
switch inside the scored epoch is a boundary the measurement crossed and
a rebalance the deployment would pay for — the committed pick's reading
spans windows that did not all hold the same market, and the objective
prices each crossing at the deployment's own switch cost rather than
pretending the pick rides a stationary regime.  The term is also the
only one of the six whose magnitude is **two caller-named factors**, and
that is its whole shape: the price of one switch and the number of
switches the horizon held, multiplied under a coefficient.
:func:`switch_penalty` lands their product — negated, visible and
arguable — through :meth:`WorldScore.adjusted`, exactly the seam the
objective's own docstring promised the six β-terms would ride, and
answers the moved :class:`~scoring.WorldScore`: the *adjusted score* of
the feature's second clause.

**The count is spelled once, here.**  ``n_regime_switches`` is the
number of adjacent pairs of consecutive windows whose regime labels
differ: windows that hold one label are one regime *held*, not a switch,
and every boundary crossed is exactly one switch — a path reading
``(trend, trend, chop)`` crossed once, and ``(trend, chop, trend, chop)``
three times.  The seam takes the regime path, not the count, for the
reason every measurement in this member takes the readings rather than a
pre-computed figure: the count is a fact about the *order* of the
labels, only the path carries that order, and deriving it here keeps the
spelling from drifting between a caller that counted one way and a
member that assumed another — the same reason :mod:`scoring._objective`
owns the ratio's spelling and :mod:`scoring._orthogonality` owns the
correlation's.  A bare count handed over could not be checked against
anything (there is no arithmetic on an integer that could notice half a
switch, a switch counted per window, or a path counted backwards), while
a path is what the labeler produces and the count above is its only
reading.

**A path, not a collection — order is information.**  The input is an
ordered :class:`~collections.abc.Sequence` of regime names, one per
consecutive window of the scored horizon, because ``(trend, trend, chop,
chop)`` holds one switch and ``(trend, chop, trend, chop)`` holds three
over the *same labels*: a path re-ordered is a different horizon, not
the same ask twice, which is why a set or a mapping cannot express what
this term reads and is refused as such.  A bare string is refused with
its own message — a string is one name, one window's label, not the
horizon's path — because accepting it would silently count the switches
between its characters, a number nobody meant.

**Labels are names, and whose vocabulary they come from is not this
member's to say.**  Each label must be a non-empty string; a blank names
no regime to switch from or to.  Nothing is normalised — near-miss
regime spellings are the census's business, feature 283's
``DEFAULT_STRATA`` is an open set, and a regime name is not feature
241's legal theme: the member reads whatever names arrive, checks each
is a name, and never enumerates the set — the same open-vocabulary
stance :mod:`scoring._regime_index` holds one feature later in the
formula.

**Which windows the path covers is the caller's discipline.**  The
arithmetically identical stance :mod:`scoring._objective` takes for
which dates the panel covers: nothing in a switch count can see the
sequestration boundary, and a seam that re-derived it would be a second
place the barrier could leak.  A path that holds no windows at all is
refused rather than read as zero switches — an unlabelled horizon is a
census that has not run (the count is unknown), not a horizon that
never switched (the count is zero), and the two readings send the
operator to different repairs.  This is also why the carrier is read by
the **one** attribute this law needs — ``adjusted`` — and nothing else:
unlike β₆ the term measures nothing off the pick's panel, so there is no
panel to pin and no measurement to recompute; the charge is a fact
about the horizon, landed beside the score it moves.

**The term can only subtract.**  All three factors are non-negative by
construction — the count is, as an integer count of boundaries; the
coefficient and the cost are refused when negative, each on the feature's
own verb: a negative β₅ would counterfeit a *bonus* through the penalty
seam (teaching the loop to prefer churn), and a negative switch cost
would pay the policy for every crossing it makes.  Zero is admitted for
both — a cost model that prices a switch at nothing has declined to
charge, and a zeroed coefficient is an ablation the documents leave to
the deployment — and with the delta computed as one negated product
there is no float path by which the subtraction could dress as an
addition: no sum, no cancellation, no last-ulp sign flip, just
``− β₅ · cost · count``.

**The two factors are deliberately asymmetric in their defaults.**
:data:`BETA_FIVE_DEFAULT` states a parameterization rather than hiding a
constant — neither prd §7.1 nor docs §10.3 sizes the coefficient, the
formula spells the term and moves on, and the stance is feature 263's
:data:`~scoring.LAMBDA_DEFAULT` for λ, feature 262's
:data:`~scoring.BETA_SIX_DEFAULT` for β₆ and feature 228's
``PRIOR_STRENGTH`` for its shrinkage prior.  ``switch_cost`` carries no
default and never will: it is a *price*, deployment state the cost model
owns (the venue-fee neighbour in spirit of features 59 and 69), denominated
in the deployment's units, and a member that invented one would have
priced a rebalance no venue quoted.  So the coefficient is keyword-only
with a default and the cost is keyword-only without — the knob is
tunable by a cycle, the price is stated by a deployment, and the seam
keeps the difference visible at every call site.

**The vocabulary of the refusals.**  This module's rejections are
:class:`~scoring.SwitchPenaltyError` — a coefficient or a cost that is
not a finite non-negative real, a carrier exposing no ``adjusted`` seam
to ride, a regime path that is not an ordered sequence of names, a label
that names no regime, a path that holds no windows at all.  It sits
**beside** :class:`~scoring.WorldObjectiveError` and
:class:`~scoring.OrthogonalityError`, never under either, for the
reason the aggregation's sibling classes are kept apart: 256 refuses an
ask that cannot be *scored*, 262 refuses one whose *bonus* cannot be
measured, this module refuses one whose *charge* cannot be counted — and
the repairs differ (a sequestration fault, a resident-array hole, a
census that has not run or a cost model that mis-set its price), so
folding them would put several different next steps behind one
``except``.  All three share the :class:`~scoring.ScoringError` base a
replay loop's single handler catches.

**What this law deliberately does not do.**  It does not touch the
leading term — the charge lands beside the measurement or not at all,
and a pick's :attr:`~scoring.WorldScore.ir_oos` is the same number with
the penalty applied and without.  It does not aggregate (263/264, whose
strata are regime *labels* across worlds, a different fact about regimes
than a horizon's crossings), does not calibrate (265-269), and persists
nothing — the ``replay_score`` row is the replay plugin's (feature 255),
and it already carries the score and the β.  It takes no component and
no seat: like the blend, the index and the bonus it is pure arithmetic —
no store, no clock, no environment — so the composed ``scoring``
component stays the per-world objective and this term is reached through
the member's own namespace, the growth pattern every free seam in this
workspace takes.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers`,
:func:`itertools.pairwise`, the :class:`~collections.abc.Sequence`
protocol, and the member's own error — no third-party import at module
scope, so the factory's scan (which imports this package to fire its
``@register`` builder) pays nothing for the law.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise
from numbers import Real

from ._objective import WorldScore
from .errors import SwitchPenaltyError

__all__ = [
    "BETA_FIVE_DEFAULT",
    "switch_penalty",
]

#: The β₅ a caller that names none gets.  Neither prd §7.1 nor docs §10.3
#: sizes the coefficient — the formula spells ``− β₅ · switch_cost ·
#: n_regime_switches`` and moves on — so this is a stated parameterization
#: rather than a hidden constant, the stance feature 263's
#: ``LAMBDA_DEFAULT`` takes for λ, feature 262's ``BETA_SIX_DEFAULT`` for
#: β₆ and feature 228's ``PRIOR_STRENGTH`` for its prior: the dreaming
#: loop's offline tuning is expected to set it per cycle, and every finite
#: non-negative value composes identically.  A quarter of the deployment's
#: own switch price charged per crossing — visible beside a leading term
#: of order one, never so large that sitting still beats being right —
#: and dyadic, so the fixtures that pin the law are exact in binary.  The
#: coefficient a deployment actually ran is its own state, persisted
#: beside the score it moved (``replay_score.beta``, feature 255).
BETA_FIVE_DEFAULT: float = 0.25


def switch_penalty(
    score: object,
    regime_labels: Sequence[str],
    *,
    switch_cost: float,
    beta: float = BETA_FIVE_DEFAULT,
) -> WorldScore:
    """Subtract the beta-five switch penalty from a world score — §7.1's
    fifth term, one charge per regime crossing of the scored horizon.

    The feature's verb.  ``score`` is the world score the charge lands on
    — feature 256's :class:`~scoring.WorldScore`, read duck-typed by the
    one attribute this law needs (``adjusted``, the seam every β-term
    rides) and never by ``isinstance``, because the module loader imports
    this member under a synthetic name and re-executes it, so a score
    this process composed may be a second ``WorldScore`` class object.
    The answer is that carrier's own ``adjusted`` return: the same
    world, pick, epoch and frozen measurement, with
    :attr:`WorldScore.score` moved *down* by ``beta · switch_cost ·
    n_switches`` — never up, by the law above.

    ``regime_labels`` is the scored horizon's regime path — one regime
    name per consecutive window, in window order — and the switch count
    is this module's own spelling over it: one switch per adjacent pair
    of windows whose labels differ, consecutive windows holding one
    label being one regime held rather than a switch.  ``switch_cost``
    is the price of one switch, keyword-only and required: a price is
    deployment state the cost model owns, and the member refuses to
    invent one.  ``beta`` is the β₅ the charge is weighted by,
    keyword-only, :data:`BETA_FIVE_DEFAULT` when unnamed.

    Refuses, with :class:`~scoring.SwitchPenaltyError` and nothing
    partial:

    * a ``beta`` or a ``switch_cost`` that is not a finite real, or is
      negative — the spec's verb is *subtracts*, and a negative
      coefficient would counterfeit a bonus through the penalty seam
      while a negative cost would pay the policy for every crossing;
    * a carrier that exposes no callable ``adjusted`` to ride;
    * a ``regime_labels`` path that is not an ordered sequence of names
      (a bare string included — one name is one window's label, not the
      horizon's path), a label that is not a non-empty string, or a
      path that holds no windows at all (an unlabelled horizon's count
      is unknown, not zero).

    Deterministic and pure: no store, no clock, no environment, and the
    same path answers the same charge to the last bit — the count is
    exact integer arithmetic over the sequence's own order and the
    delta is one product of three non-negative reals, so there is no
    summation whose order could matter and no float path by which the
    subtraction could dress as an addition.
    """
    weight = _require_beta(beta)
    cost = _require_switch_cost(switch_cost)
    adjusted = _require_adjusted_seam(score)
    count = _regime_switch_count(regime_labels)
    return adjusted(-(weight * cost * count))


# -- the seam's private vocabulary ----------------------------------------------


def _require_beta(beta: object) -> float:
    """Narrow β₅ to a finite non-negative ``float``, refusing the rest.

    ``bool`` is refused before the real check (a ``bool`` is an ``int``
    in Python's hierarchy and not a coefficient); NaN and ±inf are
    refused with it — a NaN weight would make the delta a NaN the
    ranking silently drops, and an infinite one is not a coefficient
    anyone tuned.  Negative is refused on the feature's own sentence:
    the spec's verb is *subtracts*, and a negative β₅ would counterfeit
    a bonus through the penalty seam, teaching the loop to prefer
    churn — the mirror image of the refusal feature 262 makes for a
    negative β₆.  Zero is admitted — an ablation the documents leave to
    the deployment, not a contradiction of the term.
    """
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise SwitchPenaltyError(
            f"beta must be the beta-five coefficient as a real number, got "
            f"{beta!r} ({type(beta).__name__}): the switch penalty is "
            f"weighted by a coefficient the deployment chose and the "
            f"replay_score row persists (feature 255), and a value that is "
            f"not a real has no place in either (feature 261, prd §7.1)"
        )
    weight = float(beta)
    if not math.isfinite(weight):
        raise SwitchPenaltyError(
            f"beta must be finite, got {weight!r}: a NaN weight would turn "
            f"the charge into a NaN the dreaming loop's argmax silently "
            f"drops, and an infinite one is not a coefficient anyone tuned "
            f"(feature 261, prd §7.1)"
        )
    if weight < 0.0:
        raise SwitchPenaltyError(
            f"beta must not be negative, got {weight!r}: the spec's verb is "
            f"subtracts — beta-five charges the score for every regime "
            f"crossing of the scored horizon — and a negative coefficient "
            f"would counterfeit a bonus through the penalty seam, teaching "
            f"the loop to prefer churn; an added term is feature 262's "
            f"business, the formula's one and only (feature 261, prd §7.1)"
        )
    return weight


def _require_switch_cost(cost: object) -> float:
    """Narrow the switch cost to a finite non-negative ``float``.

    The same discipline the coefficient gets, in this module's own
    vocabulary because the price is this feature's other input: ``int``
    admitted and narrowed (a whole-number price is still a price),
    ``bool`` refused before it, NaN and ±inf refused because a price
    that is not a real cannot be charged, and negative refused because
    the term subtracts — a cost that paid the policy for every crossing
    it makes would counterfeit feature 262's bonus from the penalty's
    side of the formula.  Zero is admitted: a cost model that prices a
    switch at nothing has declined to charge, and that is a deployment's
    ablation to make, not a contradiction of the term.
    """
    if isinstance(cost, bool) or not isinstance(cost, Real):
        raise SwitchPenaltyError(
            f"switch_cost must be the price of one switch as a real number, "
            f"got {cost!r} ({type(cost).__name__}): the penalty is "
            f"proportional to the deployment's own switch cost times the "
            f"regime switch count, and a value that is not a real has no "
            f"place in a price (feature 261, prd §7.1)"
        )
    price = float(cost)
    if not math.isfinite(price):
        raise SwitchPenaltyError(
            f"switch_cost must be finite, got {price!r}: a NaN or infinite "
            f"price would reach the score dressed as a charge nobody "
            f"quoted — the cost model prices a switch, and this term "
            f"subtracts what it prices (feature 261, prd §7.1)"
        )
    if price < 0.0:
        raise SwitchPenaltyError(
            f"switch_cost must not be negative, got {price!r}: the term "
            f"subtracts switch cost times regime switch count, and a "
            f"negative price would pay the policy for every crossing it "
            f"makes — counterfeiting a bonus through the penalty seam, "
            f"which is feature 262's business and this one's refusal "
            f"(feature 261, prd §7.1)"
        )
    return price


def _require_adjusted_seam(score: object) -> object:
    """The carrier's ``adjusted`` seam, read duck-typed and checked.

    The charge reaches the score through :meth:`WorldScore.adjusted` —
    the one seam the objective ships for the six β-terms — so the
    callable is read up front, before any factor of the term is: a
    carrier that lacks it is refused naming the seam, because the repair
    is at the caller's wiring and not in any path the caller might also
    have got wrong.  This is the *only* attribute this law reads — the
    term measures nothing off the pick's panel, so unlike the bonus it
    has no measurement to pin against and asks the carrier for nothing
    but the seam every β-term rides.
    """
    seam = getattr(score, "adjusted", None)
    if not callable(seam):
        raise SwitchPenaltyError(
            f"the beta-five penalty rides WorldScore.adjusted — the one seam "
            f"the objective ships for the six beta-terms — and this carrier "
            f"exposes no callable adjusted (got {seam!r} on a "
            f"{type(score).__name__}): hand feature 256's WorldScore, or "
            f"any object exposing the adjusted its terms ride, and the "
            f"charge composes onto it (feature 261, prd §7.1)"
        )
    return seam


def _regime_switch_count(regime_labels: object) -> int:
    """Count the horizon's regime switches: adjacent unequal labels.

    The path must be an ordered :class:`~collections.abc.Sequence` of
    regime names — order is information, because ``(trend, trend, chop,
    chop)`` crosses once and ``(trend, chop, trend, chop)`` three times
    over the same labels, so a set or a mapping cannot express what this
    term reads and a bare string is one name rather than a path of them.
    Each label must name a regime (a non-empty string; nothing is
    normalised, the vocabulary is the caller's), and a path that holds
    no windows at all is refused rather than read as zero switches:
    an unlabelled horizon is a census that has not run, and the count
    of an unknown horizon is unknown, not zero.
    """
    if isinstance(regime_labels, (str, bytes)) or not isinstance(
        regime_labels, Sequence
    ):
        raise SwitchPenaltyError(
            f"the scored horizon's regime path must be an ordered sequence "
            f"of regime names, one per consecutive window, got "
            f"{regime_labels!r} ({type(regime_labels).__name__}): the switch "
            f"count is a fact about the *order* of the labels — a path "
            f"re-ordered is a different horizon — so a collection that "
            f"cannot say which window followed which cannot express it, and "
            f"a bare string is one window's label, not the path "
            f"(feature 261, prd §7.1)"
        )
    labels = tuple(_require_label(label) for label in regime_labels)
    if not labels:
        raise SwitchPenaltyError(
            "the scored horizon's regime path holds no windows at all, so "
            "its regime switch count is unknown rather than zero — reading "
            "an empty path as zero switches would price a horizon nobody "
            "labelled as one that never switched, and the two send the "
            "operator to different repairs: run the labeler over the "
            "scored epoch, or hand the path it answered (feature 261, "
            "prd §7.1)"
        )
    return sum(1 for before, after in pairwise(labels) if before != after)


def _require_label(label: object) -> str:
    """Refuse a label that is not a name, answering it unchanged when it is.

    A ``bool`` is refused before the string check because ``True`` would
    otherwise be one character of payload away from passing; a blank is
    refused because a label that names no regime cannot be switched from
    or to.  Nothing is normalised — near-miss spellings are the census's
    business, and the vocabulary is the caller's to declare (feature
    283's set is open; a regime name is not feature 241's legal theme).
    """
    if isinstance(label, bool) or not isinstance(label, str) or not label.strip():
        raise SwitchPenaltyError(
            f"each window of the scored horizon's regime path must name its "
            f"regime by a non-empty string, got {label!r} "
            f"({type(label).__name__}): the count turns on which adjacent "
            f"windows hold different regimes, and a label that names "
            f"nothing cannot be switched from or to — the vocabulary is "
            f"the caller's, the name is not optional (feature 261, prd §7.1)"
        )
    return label
