"""Feature 258, the beta-two null-pick penalty — the formula's second term,
one charge for the false discoveries the policy actually committed.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 258: *System
subtracts a beta-two term proportional to null pick rate, which returns the
planted-null penalty that calibration depends on* — the second line of the
block docs/alpha-engine-prd.md §7.1 states (line 318) and
docs/nullius-tech-architecture.md §10.3 restates (line 495):

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged               # statistical budget consumed
            − β₂ · null_pick_rate               # ← this module's line (§7.1 line 320)
            …

Five of the six β-terms take away, and this one takes away for the one
thing the whole of prd §4 was built to measure: **how often the policy
committed to a planted null**.  §4.4 states the quantity the rate is, in
the campaign's own terms — *"**False discovery rate** — fraction of
committed picks that are planted nulls"* (line 173) — and that is the
figure this term charges on: a null node's true out-of-sample edge is
*"exactly zero by construction"* (§4.1, line 111), so a committed pick
that landed on one is not a pick that underperformed, it is a pick whose
edge was never there.  Every other term of the formula prices something
that could in principle be worth paying (depth explored, a haircut for
the search, a rebalance, a backtest's flattery); this one prices the
error §4 exists to make visible.  :func:`null_pick_penalty` lands that
charge — negated, visible and arguable — through
:meth:`WorldScore.adjusted`, exactly the seam the objective's own
docstring promised the six β-terms would ride.

**The clause *"that calibration depends on"* is the feature's own reason,
and it is not decoration.**  prd §7.1's paragraph under the block puts
this term apart from its five siblings in one sentence (line 327):
*"``β₂`` is the term that does not exist in the paper and without which
none of this works."*  The mechanism §4 describes measures a great deal —
§4.3's mandatory KS guard, §4.4's FDR and wasted depth, §4.1.3's base-rate
reweighting into ``FDR_deploy`` — and **every one of those figures is
instrumentation until the objective prices it**.  A loop whose score is
indifferent to how many nulls its picks landed on learns exactly one
thing from a campaign full of them: that committing is free.  β₂ is what
turns the measurement into a gradient, and it is the only term of the six
whose removal leaves §4's entire apparatus reporting a number nothing
acts on.  That is why the sentence names calibration as the *dependent*
party rather than the term.

**Two errors, two terms, two features — never one.**  prd §4.1.2's
closing paragraph is a design instruction (line 140): *"Separate the error
accounting.  Type-A error is committing to a null; Type-B is continuing to
deepen past the flip.  ``β₂`` penalizes the first, ``β₁`` finally earns its
keep on the second."*  docs §7.3.1 states the same split as a table
(line 342), giving each error its own row, its own term and its own
dominant world type — Type-A on ``β₂`` (``null_pick_rate``) in Type-R
worlds, where a null's *selection* was the failure; Type-B on ``β₁``
(``trials_charged``) in Type-D worlds, where the depth spent past a silent
flip *is* the measurement.  So this term is feature 257's **sibling**
rather than its variant, and the two are told apart by what they read: a
budget the search consumed against a rate the picks were wrong.  A single
term priced over both would be the conflation §4.1.2 was written to
forbid, and the policy would get a muddled gradient between revisions
exactly where §4.1.2 says it must not.

**The rate is a figure handed over, and this member is its *consumer* —
the direction is the feature graph's, not a preference.**  app_spec.xml
gives feature 258 ``depends_on="256"`` and gives feature **265**
``depends_on="258"``, and 265's sentence says what it contributes:
*"System computes null pick rate inside a scorer process holding the
sidecar key, which returns the rate while labels stay in."*  docs §10.3
states the same division in one line (line 507): *"``null_pick_rate`` is
computed by a scorer process holding the sidecar key.  The number flows
out; the labels do not."*  The dependency arrow therefore runs from the
computation to this term and never back: 258 **cannot** derive the rate
itself, because deriving it means reading ``is_null`` — §4.2 gives that
bit to exactly one component (the replay scorer), §1's law is that
*"there is no ``is_null`` column anywhere in the tree store"*, and a term
that reached for the labels would be a second place the barrier leaks.
So the seam takes the *rate*: the one number §7.2's interface lets out of
the sidecar-holding process, handed to an arithmetic that has never seen a
label and could not use one.  This is the same division of labour
:mod:`scoring.errors` states for the sequestered epoch (reaching the
readings is the replay engine's data access; the objective is a function
of what it is handed) — a caller with no rate has not been refused, it has
not yet asked, and the answer to *how* it asks is feature 265's.

**The rate is the campaign's own realized rate, and deliberately not
``FDR_deploy``.**  docs §10.3 draws the distinction in the paragraph
immediately after the formula (lines 509-515): sensitivity and specificity
are base-rate independent, the raw in-campaign rate is *"an artifact of
``φ``"*, and ``FDR_deploy`` — the π₀ ≈ 0.9 reweighting of §4.1.3 — is the
dashboard number while the raw rate never is.  Feature 268 owns that
rejection, and this term agrees with it: nothing here reweights, because
``FDR_deploy`` is an *estimate of what the policy would do* in a 90%-null
deployment while ``null_pick_rate`` is *what it did* in the campaign it
was scored in.  The objective charges for the error that was made.  A term
that charged on the reweighted figure would fold §4.1.3's base-rate
projection into the score, making β₂ a function of a design constant
(``π₀``) rather than of the world just replayed — and would price the same
campaign differently two features after the fact, for a reason
(``φ``) that has nothing to do with the pick.  So the seam takes the rate
it is handed and applies **no** reweighting of its own; the charge is one
negated product of two numbers, and every one of them is a fact about this
campaign.

**A rate is a fraction, and the bound is the refusal this module adds.**
``null_pick_rate`` counts the committed picks that were nulls over all the
committed picks, so it lives in ``[0, 1]`` by construction — the same way
an information coefficient lives in ``[−1, 1]`` because it is a
correlation, which is the fact :data:`~scoring.IC_BOUND` spells for
feature 260.  :data:`RATE_BOUND` is that fact spelled once for this term.
Both ends of the interval are *measurements* and both are honored: ``0.0``
is a campaign that committed to no null at all — a clean run, charged
nothing — and ``1.0`` is every committed pick a null, the worst campaign
the mechanism can produce, charged the whole coefficient.  A figure
outside the interval is refused rather than clamped, for the reason
:mod:`scoring._divergence` refuses an out-of-bound IC: clamping ``1.4`` to
one would charge the *maximum* penalty for what may be an honest (if
gross) figure, and clamping ``47`` — a **count** of null picks handed
where a rate belongs, the likeliest confusion at this seam — would charge
a full ratio unit for a campaign whose actual rate nobody computed.  The
presence of such a number says the caller handed over something else under
the right field name, and the repair is at the caller's seam.

**The charge is one negated product of two non-negative factors, so the
term can only subtract.**  The rate is non-negative by the bound above,
the coefficient is refused when negative (below), so the delta is
``− β₂ · r`` with no path by which a float could flip the sign — no
summation, no cancellation, no last-ulp surprise, just one negated
product.  ``r = 0`` is the identity: adding negative zero to a float
leaves it, so a clean campaign's score comes back field for field.

**β₂ is the caller's knob, carried with a stated default.**
:data:`BETA_TWO_DEFAULT` states a parameterization rather than hiding a
constant — neither prd §7.1 nor docs §10.3 sizes the coefficient, the
formula spells ``− β₂ · null_pick_rate`` and moves on, and the stance is
feature 263's :data:`~scoring.LAMBDA_DEFAULT` for λ, feature 262's
:data:`~scoring.BETA_SIX_DEFAULT` for β₆, feature 261's
:data:`~scoring.BETA_FIVE_DEFAULT` for β₅, feature 260's
:data:`~scoring.BETA_FOUR_DEFAULT` for β₄ and feature 259's
:data:`~scoring.BETA_THREE_DEFAULT` for β₃.  The default is ``0.5`` — a
**steep** coefficient, twinned with β₄'s and twice its three siblings'
quarter — and the reason is this term's own factor rather than a taste for
severity.  β₆'s factor is bounded in ``[0, 1]`` too, but β₆ *pays* for
diversification, a nicety the book may already hold; β₂ charges for an
error §4.1 says is exactly zero-edge by construction, so *any* non-zero
rate is a real failure and the coefficient is the whole lesson — there is
no second chance to price it later the way §7.1 gives β₄ a forward-test
queue and the outer loop (line 231).  At a half, a campaign that committed
to a null in one world of eight charges 0.0625 of a ratio unit, one in
four charges 0.125 — visible beside a leading term of order one, and
beside β₁'s, β₃'s and β₅'s charges at realistic counts — while a campaign
that committed to nulls *everywhere* is charged a full ratio unit, so
committing freely can never beat an honest pick.  Dyadic, like every
sibling's, so the fixtures that pin the law are exact in binary.  The
coefficient a deployment actually ran is its own state, persisted beside
the score it moved (``replay_score.beta``, feature 255).

**What this law deliberately does not do.**  It does not touch the leading
term — the charge lands beside the measurement or not at all, and a pick's
:attr:`~scoring.WorldScore.ir_oos` is the same number with the penalty
applied and without.  It does not *compute* the rate: reading ``is_null``
is feature 265's scorer process, holding the sidecar key §4.2 grants to
exactly one component, and this term is a function of the number that
process answers — a caller with no rate has not been refused, it has not
yet asked.  It does not *reweight* the rate to a deployment base rate:
that is §4.1.3's arithmetic, computed and persisted by feature 267 and
reported as the headline by feature 268, and folding it in here would make
this term a projection rather than a measurement.  It does not calibrate
in any other sense — sensitivity, specificity and the Type-A/Type-B split
are features 266 and 269 — and it does not *stop* anything: the term is
arithmetic on a score, and §7.4's ``halt_dreaming()`` is the verdict
module's.  It does not aggregate (263/264) and persists nothing — the
``replay_score`` row is the replay plugin's (feature 255), and it already
carries the score and the β.  It takes no component and no seat: like the
blend, the index, the bonus and the four β-terms already landed it is pure
arithmetic — no store, no clock, no environment — so the composed
``scoring`` component stays the per-world objective and this term is
reached through the member's own namespace, the growth pattern every free
seam in this workspace takes.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers` and the
member's own objective and error — no third-party import at module scope,
so the factory's scan (which imports this package to fire its
``@register`` builder) pays nothing for the law.
"""

from __future__ import annotations

import math
from numbers import Real

from ._objective import WorldScore
from .errors import NullPickPenaltyError

__all__ = [
    "BETA_TWO_DEFAULT",
    "RATE_BOUND",
    "null_pick_penalty",
]

#: The β₂ a caller that names none gets.  Neither prd §7.1 nor docs §10.3
#: sizes the coefficient — the formula spells ``− β₂ · null_pick_rate`` and
#: moves on — so this is a stated parameterization rather than a hidden
#: constant, the stance feature 263's ``LAMBDA_DEFAULT`` takes for λ and
#: every landed β-sibling takes for its own coefficient: the dreaming
#: loop's offline tuning is expected to set it per cycle, and every finite
#: non-negative value composes identically.
#:
#: A half — the steep end, twinned with β₄'s and twice the quarter its
#: three other siblings set — on this term's own arithmetic rather than a
#: taste for severity.  β₆'s factor is bounded in ``[0, 1]`` like this
#: one, but β₆ pays for diversification, a nicety the committed book may
#: already hold; β₂ charges for an error prd §4.1 says is exactly
#: zero-edge by construction, so any non-zero rate is a real failure, and
#: prd §7.1 line 327 gives this coefficient no second chance to be priced
#: later the way the forward-test queue prices β₄.  At a half, one null in
#: eight worlds charges 0.0625 of a ratio unit and one in four charges
#: 0.125 — visible beside a leading term of order one — while a campaign
#: that committed to nulls everywhere is charged a full ratio unit, so
#: committing freely can never beat an honest pick.  Dyadic, so the
#: fixtures that pin the law are exact in binary.  The coefficient a
#: deployment actually ran is its own state, persisted beside the score it
#: moved (``replay_score.beta``, feature 255).
BETA_TWO_DEFAULT: float = 0.5

#: The bounds a null pick rate lives in — it is a fraction of committed
#: picks, and a fraction of a whole is a number between none and all of it.
#:
#: ``null_pick_rate`` is prd §4.4's false discovery rate (line 173): the
#: committed picks that were planted nulls over all the committed picks.
#: That quotient is what makes the interval a *fact about the quantity*
#: rather than a tolerance this module invents — the same stance
#: :data:`~scoring.IC_BOUND` takes toward an information coefficient, which
#: is bounded because it is a correlation.  Both ends are measurements and
#: both are honored: ``0.0`` is a campaign that committed to no null at
#: all, ``1.0`` is every committed pick a null.  A figure outside the
#: interval is refused rather than clamped — ``1.4`` may be an honest
#: (gross) rate nobody should have, and ``47`` is a **count** of null picks
#: handed where a rate belongs, the likeliest confusion at this seam — so
#: the figure is refused instead of being pinned to an endpoint that would
#: charge a penalty nobody measured.
RATE_BOUND: float = 1.0


def null_pick_penalty(
    score: object,
    *,
    null_pick_rate: float,
    beta: float = BETA_TWO_DEFAULT,
) -> WorldScore:
    """Subtract the beta-two null-pick penalty from a world score — §7.1's
    second term, one charge for the planted nulls the policy committed to.

    The feature's verb.  ``score`` is the world score the charge lands on —
    feature 256's :class:`~scoring.WorldScore`, read duck-typed by the one
    attribute this law needs (``adjusted``, the seam every β-term rides)
    and never by ``isinstance``, because the module loader imports this
    member under a synthetic name and re-executes it, so a score this
    process composed may be a second ``WorldScore`` class object.  The
    answer is that carrier's own ``adjusted`` return: the same world, pick,
    epoch and frozen measurement, with :attr:`WorldScore.score` moved
    *down* by ``beta · null_pick_rate`` — never up, by the law above, and
    by nothing at all when the rate is zero.  The value answered is the
    feature's *"planted-null penalty that calibration depends on"*: the
    moved score, whose moved scalar is the charge made visible and arguable
    on the frozen measurement rather than a silent rescaling of it.

    ``null_pick_rate`` is the campaign's realized false discovery rate —
    prd §4.4's *"fraction of committed picks that are planted nulls"*
    (line 173) — as a finite real in ``[0, 1]``
    (:data:`RATE_BOUND`), keyword-only and required.  It is **the figure
    feature 265's scorer process answers**, not something this term may
    compute: reading ``is_null`` is §4.2's single-component privilege and
    this arithmetic never sees a label (see the module docstring for the
    dependency arrow that fixes the direction).  ``beta`` is the β₂ the
    charge is weighted by, keyword-only, :data:`BETA_TWO_DEFAULT` when
    unnamed.

    Refuses, with :class:`~scoring.NullPickPenaltyError` and nothing
    partial:

    * a ``beta`` that is not a finite real, or is negative — the spec's
      verb is *subtracts*, and a negative coefficient would counterfeit a
      bonus through the penalty seam, teaching the loop that landing on
      planted nulls pays;
    * a carrier that exposes no callable ``adjusted`` to ride;
    * a ``null_pick_rate`` that is not a finite real, or that lies outside
      ``[0, 1]`` — a figure that is not a fraction of committed picks has
      stopped being a rate, and the likeliest thing wearing its name is a
      *count* of null picks, which clamped to an endpoint would charge a
      penalty nobody measured.

    Deterministic and pure: no store, no clock, no environment, and the
    same rate answers the same charge to the last bit — one product of two
    validated reals and one negation, with no summation whose order could
    matter, no reweighting of any kind, and no float path by which the
    subtraction could dress as an addition.
    """
    weight = _require_beta(beta)
    rate = _require_null_pick_rate(null_pick_rate)
    adjusted = _require_adjusted_seam(score)
    return adjusted(-(weight * rate))


# -- the seam's private vocabulary ----------------------------------------------


def _require_beta(beta: object) -> float:
    """Narrow β₂ to a finite non-negative ``float``, refusing the rest.

    ``bool`` is refused before the real check (a ``bool`` is an ``int`` in
    Python's hierarchy and not a coefficient); NaN and ±inf are refused
    with it — a NaN weight would make the delta a NaN the ranking silently
    drops, and an infinite one is not a coefficient anyone tuned.  Negative
    is refused on the feature's own sentence: the spec's verb is
    *subtracts*, and a negative β₂ would counterfeit a bonus through the
    penalty seam, teaching the loop that the way to profit from §4's
    mechanism is to land on its nulls — the exact inversion of prd §7.1's
    *"without which none of this works"* (line 327).  Zero is admitted —
    an ablation the documents leave to the deployment, not a contradiction
    of the term.
    """
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise NullPickPenaltyError(
            f"beta must be the beta-two coefficient as a real number, got "
            f"{beta!r} ({type(beta).__name__}): the null-pick penalty is "
            f"weighted by a coefficient the deployment chose and the "
            f"replay_score row persists (feature 255), and a value that is "
            f"not a real has no place in either (feature 258, prd §7.1)"
        )
    weight = float(beta)
    if not math.isfinite(weight):
        raise NullPickPenaltyError(
            f"beta must be finite, got {weight!r}: a NaN weight would turn "
            f"the charge into a NaN the dreaming loop's argmax silently "
            f"drops, and an infinite one is not a coefficient anyone tuned "
            f"(feature 258, prd §7.1)"
        )
    if weight < 0.0:
        raise NullPickPenaltyError(
            f"beta must not be negative, got {weight!r}: the spec's verb is "
            f"subtracts — beta-two charges the score for the planted nulls "
            f"the policy committed to — and a negative coefficient would "
            f"counterfeit a bonus through the penalty seam, teaching the "
            f"loop that landing on the nulls §4 planted is profitable, when "
            f"prd §7.1 line 327 makes this the term without which none of "
            f"the calibration works; an added term is feature 262's "
            f"business, the formula's one and only (feature 258, prd §7.1)"
        )
    return weight


def _require_null_pick_rate(value: object) -> float:
    """Narrow the rate to a finite ``float`` inside ``[0, 1]``.

    The same discipline the coefficient gets, in this module's own
    vocabulary because the rate is this feature's other input: ``int``
    admitted and narrowed (a whole-number rate is still a rate — ``0`` and
    ``1`` are measurements, a campaign that committed to no null and one
    that committed to nothing else), ``bool`` refused before it, a non-real
    refused as a type fault rather than escaping as a ``TypeError`` from
    inside the arithmetic, and NaN and ±inf refused because a figure that
    is not a measurement cannot be a fraction of anything.

    Then the bound, which is the refusal this module adds to the member's
    finiteness gate: the rate is prd §4.4's fraction of committed picks
    that were planted nulls, so a figure outside :data:`RATE_BOUND`'s
    ``[0, 1]`` has stopped being a rate.  Refused rather than clamped,
    because the two directions of clamping are both fabrications: ``1.4``
    pinned to one charges the maximum penalty for what may be an honest
    figure, and ``47`` — a count of null picks handed where a rate belongs,
    the likeliest confusion at this seam — pinned to one charges a full
    ratio unit for a campaign whose actual rate nobody computed, which is
    the one reading prd §4.1.2 forbids arrived at from the penalty's side.

    No reweighting happens here or downstream: ``FDR_deploy`` is feature
    267's arithmetic over the same pair of figures at π₀ ≈ 0.9, and this
    term charges the campaign's own realized rate, a fact about what the
    policy did rather than a projection of what it would do (prd §4.1.3,
    docs §10.3 lines 509-515) — so the figure is returned as handed, and
    the charge is exactly ``beta · rate``.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise NullPickPenaltyError(
            f"null_pick_rate must be the campaign's realized null pick rate "
            f"as a real number, got {value!r} ({type(value).__name__}): the "
            f"penalty is proportional to the fraction of committed picks "
            f"that were planted nulls (prd §4.4), and a value that is not a "
            f"real is not a fraction — the rate is the figure feature 265's "
            f"scorer process answers while the labels stay in, and this "
            f"arithmetic consumes the number it returns (feature 258, "
            f"prd §7.1)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise NullPickPenaltyError(
            f"null_pick_rate must be finite, got {narrowed!r}: a NaN would "
            f"make the charge a NaN the dreaming loop's argmax silently "
            f"drops, and an infinity is not a fraction of committed picks — "
            f"the term subtracts beta-two times the rate the policy earned, "
            f"and a figure that is not a measurement is not one "
            f"(feature 258, prd §7.1)"
        )
    if not 0.0 <= narrowed <= RATE_BOUND:
        raise NullPickPenaltyError(
            f"null_pick_rate must be a rate in [0.0, {RATE_BOUND!r}], got "
            f"{narrowed!r}: the rate is prd §4.4's false discovery rate — "
            f"the committed picks that were planted nulls over all the "
            f"committed picks — so it is a fraction of a whole and bounded "
            f"by construction. A value outside the bound is not a high "
            f"rate; it is a number that has stopped being one, and its "
            f"presence says the caller handed over something else under this "
            f"field name — most likely a *count* of null picks where the "
            f"rate belongs. Clamping it to an endpoint would charge a "
            f"penalty nobody measured, so the figure is refused instead "
            f"(feature 258, prd §7.1)"
        )
    return narrowed


def _require_adjusted_seam(score: object) -> object:
    """The carrier's ``adjusted`` seam, read duck-typed and checked.

    The charge reaches the score through :meth:`WorldScore.adjusted` — the
    one seam the objective ships for the six β-terms — so the callable is
    read up front, before the rate is consumed: a carrier that lacks it is
    refused naming the seam, because the repair is at the caller's wiring
    and not in any figure the caller might also have got wrong.  This is
    the *only* attribute this law reads — the term measures nothing off the
    pick's panel, so unlike the bonus it has no measurement to pin against
    and asks the carrier for nothing but the seam every β-term rides.
    """
    seam = getattr(score, "adjusted", None)
    if not callable(seam):
        raise NullPickPenaltyError(
            f"the beta-two penalty rides WorldScore.adjusted — the one seam "
            f"the objective ships for the six beta-terms — and this carrier "
            f"exposes no callable adjusted (got {seam!r} on a "
            f"{type(score).__name__}): hand feature 256's WorldScore, or any "
            f"object exposing the adjusted its terms ride, and the charge "
            f"composes onto it (feature 258, prd §7.1)"
        )
    return seam
