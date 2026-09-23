"""Feature 260, the beta-four divergence penalty — the formula's fourth
term, one charge for how far the backtest flattered the signal.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 260: *System
subtracts a beta-four term proportional to absolute divergence between
forward and backtest information coefficient, which returns the adjusted
score* — the fourth line of the block docs/alpha-engine-prd.md §7.1 states
(line 318) and docs/nullius-tech-architecture.md §10.3 restates (line 495):

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged               # five penalties, each its own feature
            − β₄ · | IC_forward − IC_backtest |   # ← this module's line (§7.1 line 322)
            …

Five of the six β-terms take away, and this one takes away for the
formula's one *comparison*: the gap between what a signal promised in
simulation and what it delivered forward.  prd §7.1's paragraph under the
block is the feature's whole reason (line 329): *"β₄ is computable only
for nodes that have been through the forward-test queue.  It teaches the
meta-policy to prefer signal families whose backtests are **honest**, not
merely high"* — and docs §6.2 states the mechanism that makes the gap
measurable in the first place (line 259): the evaluator and the live
engine share one cost model, *"because divergence between the two is
exactly the quantity β₄ penalizes, so they must be the same code, not two
implementations of the same document"*.  A pick whose forward IC matches
its backtest IC is charged
nothing however large either figure is; a pick whose backtest flattered it
is charged in proportion to the flattery.
:func:`divergence_penalty` lands that charge — negated, visible and
arguable — through :meth:`WorldScore.adjusted`, exactly the seam the
objective's own docstring promised the six β-terms would ride, and answers
the moved :class:`~scoring.WorldScore`: the *adjusted score* of the
feature's second clause.

**The divergence is the absolute difference, and the absolute value is
the law.**  ``|IC_forward − IC_backtest|`` is the sentence's own
arithmetic, spelled once here and the same quantity the deployment's
live/sim divergence monitor watches (docs §15's ``β₄ monitor``, whose
response is auto-demote plus reconcile-the-cost-model — prd §C10 puts the
line at live IC below 40% of backtest IC, line 475).  The absolute value is the half of
the definition that is a decision rather than a convention, and prd §7.1's
sibling sentence makes the reason plain: it is a **divergence**, not a
retention ratio.  prd §11's *secondary* scorecard line is exactly that
different measurement of the same pair — *"Forward-test IC retention: live
IC ÷ backtest IC at 90 days"* (line 541, targeted above 0.5) — and it is
deliberately **not** what this term charges on: it is undefined at zero
backtest IC for a start, and it reads a forward IC *twice* the backtest as
a number above one rather than as the same-sized gap it is.  A signal that
over-delivers is as badly calibrated as one that under-delivers; both
taught the meta-policy to trust a backtest that does not forecast.  So the
handicap is symmetric in the two figures and this module refuses to
pretend otherwise.

**Both figures are information coefficients, and both are correlations.**
The two inputs are read off the forward-test record (feature 333's
``forward_record``, docs §13.4's *"live IC tracked forward"*, line 729)
and the node's own measurement — prd §6.1's ``metrics.ic_mean``, the mean
IC feature 81's decay profile measures at each horizon.  Both are named for
the mean information coefficient, which is a **correlation**: it is
bounded in ``[−1, 1]`` by construction, whatever the underlying estimator
(feature 74's Spearman rank transform, computed by feature 81's decay
profile in the evaluator's one spelling).  That bound is not a convention
this module invents — it is
what an information coefficient *is* — so both figures are held to it, and
a figure outside it is refused rather than clamped.  The refusal is
sharper than the objective's finiteness gate one feature earlier, and for
the same reason the objective refuses a short panel rather than
zero-filling it: a reading of ``2.5`` is not a large IC, it is a number
that has stopped being an IC, and its presence says the caller handed over
something else — a sign-flipped z-score, a hit rate, an IR — under the
right field name.  Clamping it to one would silently charge the *maximum*
divergence for what may well be an honest pair, which is a fabrication in
the other direction.

**The charge is one product of three non-negative factors, so the term can
only subtract.**  The divergence is an absolute value, and therefore
non-negative; the coefficient is refused when negative (below); so the
delta is ``− β₄ · |ΔIC|`` with no path by which a float could flip the
sign — there is no summation and no cancellation in it, only one negated
product.  Zero is admitted for the coefficient and for both figures: a
zeroed β₄ is an ablation the documents leave to the deployment, and two
equal figures — including two *zero* figures, a signal that measured
nothing forward and nothing in backtest — are a pick the forward test
vindicated, not a pick it exposed.  That last case is worth stating
because it is the one a naive implementation gets wrong: a divergence
expressed as a ratio would divide by that backtest, and a penalty
expressed as a relative gap would blow up on it; the absolute difference
answers zero, which is the honest reading of *"the backtest did not
flatter it"*.

**A figure whose measurement does not exist is refused, not read as
zero.**  prd §7.1 says β₄ *"is computable only for nodes that have been
through the forward-test queue"*, and that sentence is load-bearing here.
A pick with no forward record has no forward IC — the field is absent, not
``0.0`` — and the two cheap readings of that absence are both wrong: an
absent figure read as zero charges the pick its entire backtest IC (the
backtest flattered it by everything, on no evidence whatever), and an
absent figure read as "no divergence" pays it in full.  Neither is a
measurement.  So the seam takes the *figures*, not a pre-computed
divergence, and refuses a figure that is not a number: the caller that has
no forward IC must not call this term at all — the pick is not yet
scorable on β₄, and prd §7.1's own sentence says so.  The same reasoning
:mod:`scoring._switches` applies to an unlabelled horizon, whose switch
count is unknown rather than zero, and :mod:`scoring._orthogonality` to a
book that misses a sequestered date.

**Why the figures and not the divergence.**  The term takes the two
information coefficients rather than their difference for the reason every
measurement in this member takes the readings rather than a pre-computed
figure: the divergence is a fact about the *pair*, only the pair carries
it, and deriving it here keeps the spelling from drifting between a caller
that subtracted one way and a member that assumed another — the same
reason :mod:`scoring._objective` owns the ratio's spelling and
:mod:`scoring._orthogonality` owns the correlation's.  A scalar handed
over could not be checked against anything (there is no arithmetic on a
divergence that could notice a sign error, a ratio smuggled in where a
difference belongs, or two figures swapped), while two correlations are
readable, boundable and arguable.  It also makes the refusal above
*possible*: an absent figure cannot be represented in a difference at all,
so a scalar interface would have to invent a value for it — and there is
no value to invent.

**β₄ is the caller's knob, carried with a stated default.**  Neither
document sizes the coefficient — §7.1 spells the term and moves on — so
:data:`BETA_FOUR_DEFAULT` states a parameterization rather than hiding a
constant, the stance feature 263's :data:`~scoring.LAMBDA_DEFAULT` takes
for λ, feature 262's :data:`~scoring.BETA_SIX_DEFAULT` for β₆ and feature
261's :data:`~scoring.BETA_FIVE_DEFAULT` for β₅: the dreaming loop's
offline tuning is expected to set it per cycle, and every finite
non-negative value composes identically.  The default is ``0.5`` — a
**steeper** coefficient than its two siblings, and deliberately so: β₅
charges for a horizon's churn and β₆ pays for diversification, both of
them facts about one world, while β₄ charges for the credibility of the
backtest the whole meta-policy learns from.  §7.1's line 329 is that this
is the term which teaches the loop to prefer honest signal families, prd
§C10 makes live IC below 40% of backtest IC an automatic demotion
(line 475), and the outer loop's entire Loop 3 exists to recalibrate this
one coefficient (line 231) — a gap of a tenth of an IC charging a
twentieth of a ratio unit is a nudge, not a lesson.  At a half, the
largest divergence the bound admits charges a full ratio unit: visible
beside a leading term of order one, and never so large that a pick with an
honest backtest is beaten by one that measured nothing.  The coefficient a
deployment actually ran is its own state, persisted beside the score it
moved (``replay_score.beta``, feature 255).

**What this law deliberately does not do.**  It does not touch the leading
term — the charge lands beside the measurement or not at all, and a pick's
:attr:`~scoring.WorldScore.ir_oos` is the same number with the penalty
applied and without.  It does not read the forward record from anywhere:
reaching it is the forward-tracking member's data access, and the term is
a function of the two figures it is handed — a caller with no forward
record has not been refused, it has not yet asked (the same division of
labour :mod:`scoring.errors` states for the sequestered epoch).  It does
not reconstruct the forward IC from a *retention ratio*, however that
figure is stored — feature 337's *"live IC ÷ backtest IC"* is a different
measurement of the same pair, and dividing a backtest IC by it to
manufacture a forward one would be this member inventing a reading the
store did not hold.  And it does not aggregate (263/264), does not
calibrate (265-269), and persists nothing — the ``replay_score`` row is
the replay plugin's (feature 255), and it already carries the score and
the β.  It takes no component and no seat: like the blend, the index, the
bonus and the switch penalty it is pure arithmetic — no store, no clock,
no environment — so the composed ``scoring`` component stays the per-world
objective and this term is reached through the member's own namespace, the
growth pattern every free seam in this workspace takes.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers` and the
member's own objective and error — no third-party import at module scope,
so the factory's scan (which imports this package to fire its
``@register`` builder) pays nothing for the law.
"""

from __future__ import annotations

import math
from numbers import Real

from ._objective import WorldScore
from .errors import DivergencePenaltyError

__all__ = [
    "BETA_FOUR_DEFAULT",
    "IC_BOUND",
    "divergence_penalty",
]

#: The β₄ a caller that names none gets.  Neither prd §7.1 nor docs §10.3
#: sizes the coefficient — the formula spells ``− β₄ · |IC_forward −
#: IC_backtest|`` and moves on — so this is a stated parameterization
#: rather than a hidden constant, the stance feature 263's
#: ``LAMBDA_DEFAULT`` takes for λ, feature 262's ``BETA_SIX_DEFAULT`` for
#: β₆ and feature 261's ``BETA_FIVE_DEFAULT`` for β₅.
#:
#: Twice its siblings' quarter, on the feature's own sentence: §7.1 line
#: 329 gives this term the job of teaching the meta-policy to prefer
#: *honest* backtests, §C10 makes a live IC below 40% of backtest an
#: automatic demotion (line 475), and the whole outer loop exists to
#: recalibrate this one number (line 231) — so a tenth of an IC has to
#: cost more than a nudge.  A half charges a full ratio unit at the
#: largest divergence :data:`IC_BOUND` admits, which is visible beside a
#: leading term of order one and still never enough that a pick with an
#: honest backtest loses to one that measured nothing.  Dyadic, so the
#: fixtures that pin the law are exact in binary.
BETA_FOUR_DEFAULT: float = 0.5

#: The bounds an information coefficient lives in, as a half-open pair of
#: the largest magnitude one can reach.
#:
#: An information coefficient is a **correlation** — prd §6.1's
#: ``metrics.ic_mean`` is the mean of the per-date coefficients feature
#: 82's decay profile measures, and those are Spearman rank correlations
#: (the evaluator's one spelling) — so it is bounded in ``[−1, 1]`` by
#: construction, whatever the estimator.  This constant is that fact
#: spelled once, not a tolerance: a figure of ``2.5`` is not a large IC,
#: it is a number that has stopped being an IC, and its presence means the
#: caller handed over something else — a z-score, a hit rate, an IR —
#: under the right field name.  Both figures are checked against it and
#: refused rather than clamped, because clamping would charge the maximum
#: divergence for what may be an honest pair.
IC_BOUND: float = 1.0


def divergence_penalty(
    score: object,
    *,
    ic_forward: float,
    ic_backtest: float,
    beta: float = BETA_FOUR_DEFAULT,
) -> WorldScore:
    """Subtract the beta-four divergence penalty from a world score —
    §7.1's fourth term, one charge for sim-reality divergence.

    The feature's verb.  ``score`` is the world score the charge lands on
    — feature 256's :class:`~scoring.WorldScore`, read duck-typed by the
    one attribute this law needs (``adjusted``, the seam every β-term
    rides) and never by ``isinstance``, because the module loader imports
    this member under a synthetic name and re-executes it, so a score this
    process composed may be a second ``WorldScore`` class object.  The
    answer is that carrier's own ``adjusted`` return: the same world,
    pick, epoch and frozen measurement, with
    :attr:`WorldScore.score` moved *down* by ``beta · |ic_forward −
    ic_backtest|`` — never up, by the law above.

    ``ic_forward`` is the pick's **forward** information coefficient — the
    live figure the forward-test record holds, prd §11's *"live IC"* —
    and ``ic_backtest`` is the **backtest** figure the node was measured
    at in simulation (prd §6.1's ``metrics.ic_mean``).  Both are
    keyword-only and required, and both are correlations: each must be a
    finite real in ``[−1, 1]``, refused rather than clamped when it is
    not.  The divergence is this module's own spelling over the pair —
    ``|ic_forward − ic_backtest|`` — and never a figure handed over, for
    the reasons the module docstring states.  ``beta`` is the β₄ the
    charge is weighted by, keyword-only, :data:`BETA_FOUR_DEFAULT` when
    unnamed.

    Refuses, with :class:`~scoring.DivergencePenaltyError` and nothing
    partial:

    * a ``beta`` that is not a finite real, or is negative — the spec's
      verb is *subtracts*, and a negative coefficient would counterfeit a
      bonus through the penalty seam, teaching the loop to prefer
      flattering backtests;
    * a carrier that exposes no callable ``adjusted`` to ride;
    * an ``ic_forward`` or ``ic_backtest`` that is not a finite real, or
      that lies outside ``[−1, 1]`` — a figure the forward-test queue has
      not produced is *absent*, and this seam must not be called with a
      stand-in for it rather than have one read as a measurement.

    Deterministic and pure: no store, no clock, no environment, and the
    same pair answers the same charge to the last bit — one absolute
    difference of two validated reals and one negated product, with no
    summation whose order could matter and no float path by which the
    subtraction could dress as an addition.
    """
    weight = _require_beta(beta)
    forward = _require_information_coefficient(ic_forward, "ic_forward", "forward")
    backtest = _require_information_coefficient(
        ic_backtest, "ic_backtest", "backtest"
    )
    adjusted = _require_adjusted_seam(score)
    return adjusted(-(weight * abs(forward - backtest)))


# -- the seam's private vocabulary ----------------------------------------------


def _require_beta(beta: object) -> float:
    """Narrow β₄ to a finite non-negative ``float``, refusing the rest.

    ``bool`` is refused before the real check (a ``bool`` is an ``int`` in
    Python's hierarchy and not a coefficient); NaN and ±inf are refused
    with it — a NaN weight would make the delta a NaN the ranking silently
    drops, and an infinite one is not a coefficient anyone tuned.
    Negative is refused on the feature's own sentence: the spec's verb is
    *subtracts*, and a negative β₄ would counterfeit a bonus through the
    penalty seam, teaching the loop to prefer the signal families whose
    backtests flattered them most — the exact inversion of §7.1's
    *"honest, not merely high"*.  Zero is admitted — an ablation the
    documents leave to the deployment, not a contradiction of the term.
    """
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise DivergencePenaltyError(
            f"beta must be the beta-four coefficient as a real number, got "
            f"{beta!r} ({type(beta).__name__}): the divergence penalty is "
            f"weighted by a coefficient the deployment chose and the "
            f"replay_score row persists (feature 255), and a value that is "
            f"not a real has no place in either (feature 260, prd §7.1)"
        )
    weight = float(beta)
    if not math.isfinite(weight):
        raise DivergencePenaltyError(
            f"beta must be finite, got {weight!r}: a NaN weight would turn "
            f"the charge into a NaN the dreaming loop's argmax silently "
            f"drops, and an infinite one is not a coefficient anyone tuned "
            f"(feature 260, prd §7.1)"
        )
    if weight < 0.0:
        raise DivergencePenaltyError(
            f"beta must not be negative, got {weight!r}: the spec's verb is "
            f"subtracts — beta-four charges the score for the gap between "
            f"what the backtest promised and what the forward test delivered "
            f"— and a negative coefficient would counterfeit a bonus through "
            f"the penalty seam, teaching the loop to prefer the families "
            f"whose backtests flattered them most, the inversion of prd "
            f"§7.1's 'honest, not merely high' (line 329); an added term is "
            f"feature 262's business, the formula's one and only "
            f"(feature 260, prd §7.1)"
        )
    return weight


def _require_information_coefficient(value: object, field: str, side: str) -> float:
    """Narrow one IC to a finite ``float`` inside ``[−1, 1]``.

    The same discipline the coefficient gets, in this module's own
    vocabulary because the two figures are this feature's other inputs:
    ``int`` admitted and narrowed (a whole-number IC is still an IC),
    ``bool`` refused before it, a non-real refused as a type fault rather
    than escaping as a ``TypeError`` from inside the arithmetic, and NaN
    and ±inf refused because a figure that is not a measurement cannot be
    one side of a divergence.

    Then the bound, which is the refusal this module adds to the member's
    finiteness gate: an information coefficient is a correlation and lives
    in :data:`IC_BOUND`'s ``[−1, 1]``, so a figure outside it is *not* a
    large IC — it is a number that has stopped being one, and the caller
    has handed something else (a z-score, a hit rate, an IR) over under
    this field name.  Refused rather than clamped: clamping to the bound
    would charge the maximum divergence for a pair that may well be
    honest, which is a fabrication in the other direction.  The message
    names the side, because the repair differs — a ``forward_record`` the
    forward-tracking member wrote wrongly against a node metric the
    evaluator wrote wrongly.

    An *absent* figure cannot reach here at all: ``None`` is refused by
    the type gate above, and prd §7.1's sentence that β₄ *"is computable
    only for nodes that have been through the forward-test queue"* is the
    reason — a pick with no forward record has no forward IC to hand over,
    and a caller with none must not call this term rather than watch a
    stand-in be read as a zero.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise DivergencePenaltyError(
            f"{field} must be the {side} information coefficient as a real "
            f"number, got {value!r} ({type(value).__name__}): the penalty is "
            f"proportional to the absolute divergence between the forward "
            f"and the backtest IC, and a value that is not a real is neither "
            f"side of that divergence — a pick with no forward record has no "
            f"forward IC to hand over, and prd §7.1 makes this term "
            f"computable only for nodes that have been through the "
            f"forward-test queue (feature 260, prd §7.1)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise DivergencePenaltyError(
            f"{field} must be finite, got {narrowed!r}: a NaN would make the "
            f"divergence a NaN the dreaming loop's argmax silently drops, and "
            f"an infinity is not an information coefficient — the term "
            f"subtracts the gap between two readings of the same signal, and "
            f"a figure that is not a measurement is not one of them "
            f"(feature 260, prd §7.1)"
        )
    if not -IC_BOUND <= narrowed <= IC_BOUND:
        raise DivergencePenaltyError(
            f"{field} must be an information coefficient in "
            f"[{-IC_BOUND!r}, {IC_BOUND!r}], got {narrowed!r}: an information "
            f"coefficient is a correlation — prd §6.1's ic_mean is the mean "
            f"of the per-date coefficients the decay profile measures, and "
            f"those are rank correlations, so the figure is bounded by "
            f"construction whatever the estimator. A value outside the bound "
            f"is not a large IC; it is a number that has stopped being one, "
            f"and its presence says the caller handed over something else — "
            f"a z-score, a hit rate, an information ratio — under this field "
            f"name. Clamping it to the bound would charge the maximum "
            f"divergence for a pair that may well be honest, so the figure "
            f"is refused instead, on the {side} side of the pair "
            f"(feature 260, prd §7.1)"
        )
    return narrowed


def _require_adjusted_seam(score: object) -> object:
    """The carrier's ``adjusted`` seam, read duck-typed and checked.

    The charge reaches the score through :meth:`WorldScore.adjusted` — the
    one seam the objective ships for the six β-terms — so the callable is
    read up front, before either figure is validated: a carrier that lacks
    it is refused naming the seam, because the repair is at the caller's
    wiring and not in any figure the caller might also have got wrong.
    This is the *only* attribute this law reads — the term measures nothing
    off the pick's panel, so unlike the bonus it has no measurement to pin
    against and asks the carrier for nothing but the seam every β-term
    rides.
    """
    seam = getattr(score, "adjusted", None)
    if not callable(seam):
        raise DivergencePenaltyError(
            f"the beta-four penalty rides WorldScore.adjusted — the one seam "
            f"the objective ships for the six beta-terms — and this carrier "
            f"exposes no callable adjusted (got {seam!r} on a "
            f"{type(score).__name__}): hand feature 256's WorldScore, or any "
            f"object exposing the adjusted its terms ride, and the charge "
            f"composes onto it (feature 260, prd §7.1)"
        )
    return seam
