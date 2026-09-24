"""Feature 257, the beta-one trials penalty — the formula's first term, one
charge per unit of statistical budget consumed.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 257: *System
subtracts a beta-one term proportional to trials charged, which returns a
score penalized for consumed statistical budget* — the first line of the
block docs/alpha-engine-prd.md §7.1 states (line 318) and
docs/nullius-tech-architecture.md §10.3 restates (line 496):

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged               # ← this module's line (§7.1 line 320)
            − β₃ · deflation(K_eff)             # … and four more terms, §7.1

Five of the six β-terms take away, and this one takes away for the
formula's first and most direct cost: the **statistical budget the search
consumed**.  The paper's Equation 1 wrote this term as ``β₁ N`` and counted
``N`` in *agent calls* — a compute quantity, embarrassingly parallel and
cheap — and prd §7.1's Change B is the reason the term was rewritten:
*"Backtests are embarrassingly parallel and cheap. Parallelism is not the
bottleneck. Data is."*  ``trials_charged`` counts the binding resource
(docs §10.3, prd §705: ``β₁ N (agent calls)`` → ``β₁ · trials charged
(statistical budget)``), the same degrees-of-freedom meter feature 221's
``budget_remaining()`` reports and §8's ``charges_budget`` column stamps a
trial with.  :func:`trials_penalty` lands the charge — negated, visible and
arguable — through :meth:`WorldScore.adjusted`, exactly the seam the
objective's own docstring promised the six β-terms would ride, and answers
the moved :class:`~scoring.WorldScore`: the *penalized score* of the
feature's second clause.

**The figure is ``trials_charged``, and it is a count, not a derivation.**
The seam takes the number of budget-charging trials the campaign consumed —
feature 221's ``BudgetAccount.charged``, the ``trials_charged`` column the
node record carries (prd §6.1 line 279), the count a deployment hands over
as the statistical spend — and charges one ``β₁`` per unit, linearly: the
delta is ``− β₁ · trials_charged`` with no square root and no logarithm to
soften it.  This is the term's whole shape, and it is *deliberately* the
shape β₃ refuses: the two terms sit beside each other in §7.1's formula and
price the *same* resource two different ways — β₁ the raw spend, β₃ the
multiple-testing bar over the honest count — and conflating them would
either double-count the charge or drop it.  The distinction is the feature:

* **β₁ (this term) is the raw spend.**  Every budget-charging trial costs
  one unit, and the charge is proportional to the count — the linear price
  of having drawn down the statistical budget at all.  It is ``trials_charged``
  in the plain sense: the number of trials that consumed a degree of
  freedom, which is feature 93's *row count* (``KEffective.total`` equals
  ``trials_charged`` exactly when no null node was ever charged) and which
  is why the seam takes the figure as a plain count.
* **β₃ (feature 259) is the haircut.**  It takes ``K_effective`` — feature
  93's *derived view* that filters the same rows on ``charges_budget`` and
  reports ``0`` for an all-null epoch — and prices them at ``√(2·ln K)``,
  the expected maximum null Sharpe of §7.3.  It refuses a bare count on
  purpose, because a number cannot say whether it was counted honestly.

The two terms are therefore not two spellings of one thing but two facts
about one resource: β₁ prices *that budget was spent*, β₃ prices *how much
the spending should make you doubt*.  A caller that has ``K_effective`` for
β₃ and ``trials_charged`` for β₁ hands both; a caller that hands the same
derivation to both is charging β₁ on a filtered count and β₃ on a raw one,
and neither is what §7.1 states — which is why this seam takes the count
*directly* and never reaches for a ``total`` or a ``by_epoch``: the figure
β₁ reads and the figure β₃ reads are spelled differently on purpose, and
this module reads only the one its own term names.

**A count, validated as a count.**  ``trials_charged`` must be a
non-negative integer — the shape feature 221's ``BudgetAccount.charged``
answers, the shape §6.1's ``trials_charged: int`` column holds, and the
shape feature 93's honest counter counts in.  A ``bool`` is refused (it is
an ``int`` in Python's hierarchy and a count that arrived as a truth value
is a flag wearing a number); a negative count is refused (it is not a
number of trials anyone charged — the one direction that would *pay* the
policy for having searched, the mirror of the refusal β₃ makes for a
negative ``total``); a float is refused as the shape fault it is (``53.0``
is a measurement, not a count of trials — a count of hypotheses is an
integer or it is not a count, the same discipline the ledger's derivation
applies to its own ``total``).  Zero is admitted and charged nothing: a
campaign that consumed no statistical budget — the bootstrap pool's
zero-cost worlds (docs §10.6), an epoch of nothing but uncharged
evaluations — pays no trials penalty, and refusing the ``0`` would make a
measured figure no consumer may state.

**The charge is one negated product, so the term can only subtract.**  The
count is non-negative by construction; the coefficient is refused when
negative (below); so the delta is ``− β₁ · trials_charged`` with no path by
which a float could flip the sign — one product, one negation, no summation
and no cancellation.  Zero is admitted for the coefficient (an ablation the
documents leave to the deployment) and answered by the count itself for a
zero spend, the two ways a campaign can be charged nothing without the term
declining to run.

**β₁ is the caller's knob, carried with a stated default.**  Neither
document sizes the coefficient — §7.1 spells the term and moves on — so
:data:`BETA_ONE_DEFAULT` states a parameterization rather than hiding a
constant, the stance feature 263's :data:`~scoring.LAMBDA_DEFAULT` takes
for λ and every landed β-sibling for its own coefficient: the dreaming
loop's offline tuning is expected to set it per cycle (*"default chosen per
cycle from live evidence and prior sweeps"*, prd §7.4), and every finite
non-negative value composes identically.  The default is ``0.25`` — the
base the β₃, β₅ and β₆ siblings set — because this term's own factor is a
raw count of order the campaign's trial count, so a quarter keeps a hundred
charged trials at 25 ratio units of *headline* charge, visible beside and
compounding with β₃'s ~0.76 haircut at the same count: the two penalties
are meant to *stack*, not to cancel, and the shared base keeps their ratio
legible across the sweep.  The coefficient a deployment actually ran is its
own state, persisted beside the score it moved (``replay_score.beta``,
feature 255).

**What this law deliberately does not do.**  It does not touch the leading
term — the charge lands beside the measurement or not at all, and a pick's
:attr:`~scoring.WorldScore.ir_oos` is the same number with the penalty
applied and without.  It does not *derive* the count from rows handed over:
that is feature 93's verb in the ledger member, and restating the
``charges_budget`` filter here would be a second spelling of one derivation
that could drift — the same division of labour :mod:`scoring._deflation`
holds the other way for ``K_effective``.  It does not read the trial ledger
— reaching the rows is the ledger member's data access, and a caller with
no count has not been refused — it has not yet asked (the same division of
labour :mod:`scoring.errors` states for the sequestered epoch).  It does not
aggregate (263/264), does not calibrate (265-269), and persists nothing —
the ``replay_score`` row is the replay plugin's (feature 255), and it
already carries the score and the β.  It takes no component and no seat:
like the blend, the index, the bonus and the four landed penalties it is
pure arithmetic — no store, no clock, no environment — so the composed
``scoring`` component stays the per-world objective and this term is reached
through the member's own namespace, the growth pattern every free seam in
this workspace takes.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers` and the member's
own objective and error — no third-party import at module scope, so the
factory's scan (which imports this package to fire its ``@register``
builder) pays nothing for the law.
"""

from __future__ import annotations

import math
from numbers import Real

from ._objective import WorldScore
from .errors import TrialsPenaltyError

__all__ = [
    "BETA_ONE_DEFAULT",
    "trials_penalty",
]

#: The β₁ a caller that names none gets.  Neither prd §7.1 nor docs §10.3
#: sizes the coefficient — the formula spells ``− β₁ · trials_charged`` and
#: moves on — so this is a stated parameterization rather than a hidden
#: constant, the stance feature 263's ``LAMBDA_DEFAULT`` takes for λ and
#: each landed β-sibling for its own coefficient.
#:
#: The base quarter, shared with β₃, β₅ and β₆, on the term's own
#: arithmetic: the factor this coefficient scales is the *raw* count of
#: budget-charging trials, so a quarter keeps a hundred charged trials at 25
#: ratio units of headline charge — visible beside a leading term of order
#: one, and meant to *compound* with β₃'s ~0.76 multiple-testing haircut at
#: the same count rather than cancel it, the two penalties stacking as §7.1
#: states them.  Dyadic like its siblings, so the coefficient's own
#: arithmetic is exact in binary.  The coefficient a deployment actually ran
#: is its own state, persisted beside the score it moved (``replay_score.beta``,
#: feature 255).
BETA_ONE_DEFAULT: float = 0.25


def trials_penalty(
    score: object,
    trials_charged: object,
    *,
    beta: float = BETA_ONE_DEFAULT,
) -> WorldScore:
    """Subtract the beta-one trials penalty from a world score — §7.1's first
    term, one charge per unit of statistical budget consumed.

    The feature's verb.  ``score`` is the world score the charge lands on —
    feature 256's :class:`~scoring.WorldScore`, read duck-typed by the one
    attribute this law needs (``adjusted``, the seam every β-term rides) and
    never by ``isinstance``, because the module loader imports this member
    under a synthetic name and re-executes it, so a score this process
    composed may be a second ``WorldScore`` class object.  The answer is that
    carrier's own ``adjusted`` return: the same world, pick, epoch and frozen
    measurement, with :attr:`WorldScore.score` moved *down* by
    ``beta · trials_charged`` — never up, by the law above.

    ``trials_charged`` is the statistical budget the campaign consumed — the
    count of budget-charging trials, keyword-only, required, a non-negative
    integer: feature 221's ``BudgetAccount.charged``, §6.1's
    ``trials_charged`` column, the plain count of degrees of freedom drawn
    down.  It is taken **directly, not derived**: this module reads the one
    figure its own term names and never reaches for a ``total`` or a
    ``by_epoch`` breakdown, because the count β₁ charges and the honest count
    β₃ charges (feature 259's ``K_effective``) are two facts about one
    resource, spelled differently on purpose.  ``beta`` is the β₁ the charge
    is weighted by, keyword-only, :data:`BETA_ONE_DEFAULT` when unnamed.

    Refuses, with :class:`~scoring.TrialsPenaltyError` and nothing partial:

    * a ``beta`` that is not a finite real, or is negative — the spec's verb
      is *subtracts*, and a negative coefficient would counterfeit a bonus
      through the penalty seam, teaching the loop that spending statistical
      budget pays;
    * a ``trials_charged`` that is not a non-negative integer count — a
      ``bool`` (an ``int`` wearing a truth value), a negative count (which
      would pay the policy for having searched), or a float (a measurement
      where a count belongs);
    * a carrier that exposes no callable ``adjusted`` to ride.

    Deterministic and pure: no store, no clock, no environment, and the same
    count answers the same charge to the last bit — the delta is one negated
    product of the count with a validated coefficient, so there is no
    summation whose order could matter and no float path by which the
    subtraction could dress as an addition.
    """
    weight = _require_beta(beta)
    charged = _require_trials_charged(trials_charged)
    adjusted = _require_adjusted_seam(score)
    return adjusted(-(weight * charged))


# -- the seam's private vocabulary ----------------------------------------------


def _require_beta(beta: object) -> float:
    """Narrow β₁ to a finite non-negative ``float``, refusing the rest.

    ``bool`` is refused before the real check (a ``bool`` is an ``int`` in
    Python's hierarchy and not a coefficient); NaN and ±inf are refused with
    it — a NaN weight would make the delta a NaN the ranking silently drops,
    and an infinite one is not a coefficient anyone tuned.  Negative is
    refused on the feature's own sentence: the spec's verb is *subtracts*,
    and a negative β₁ would counterfeit a bonus through the penalty seam,
    teaching the loop that drawing down the statistical budget is a payment
    rather than a cost.  Zero is admitted — an ablation the documents leave
    to the deployment, not a contradiction of the term.
    """
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise TrialsPenaltyError(
            f"beta must be the beta-one coefficient as a real number, got "
            f"{beta!r} ({type(beta).__name__}): the trials penalty is weighted "
            f"by a coefficient the deployment chose and the replay_score row "
            f"persists (feature 255), and a value that is not a real has no "
            f"place in either (feature 257, prd §7.1)"
        )
    weight = float(beta)
    if not math.isfinite(weight):
        raise TrialsPenaltyError(
            f"beta must be finite, got {weight!r}: a NaN weight would turn the "
            f"charge into a NaN the dreaming loop's argmax silently drops, and "
            f"an infinite one is not a coefficient anyone tuned (feature 257, "
            f"prd §7.1)"
        )
    if weight < 0.0:
        raise TrialsPenaltyError(
            f"beta must not be negative, got {weight!r}: the spec's verb is "
            f"subtracts — beta-one charges the score for every unit of "
            f"statistical budget the search consumed — and a negative "
            f"coefficient would counterfeit a bonus through the penalty seam, "
            f"teaching the loop that drawing down the budget pays; an added "
            f"term is feature 262's business, the formula's one and only "
            f"(feature 257, prd §7.1)"
        )
    return weight


def _require_trials_charged(trials_charged: object) -> int:
    """The one figure this law reads: the count of budget-charging trials.

    A non-negative integer, and not a ``bool`` — ``True`` is an ``int`` in
    Python's hierarchy and a count that arrived as a truth value is a flag
    wearing a number, the same discipline feature 93's honest counter applies
    to its own ``total``.  A negative count is refused because it is not a
    number of trials anyone charged — the one direction that would *pay* the
    policy for having searched, the mirror of the refusal β₃ makes for a
    negative ``K_effective`` total.  A float is refused as the shape fault it
    is: ``53.0`` is a measurement, and a count of hypotheses is an integer or
    it is not a count.  Zero is admitted — the bootstrap pool's zero-cost
    worlds and an epoch of nothing but uncharged evaluations both charge
    nothing, and refusing the ``0`` would make a measured figure no consumer
    may state.

    The figure is taken directly, never derived from rows: this is β₁'s own
    count, the raw statistical spend, and it is deliberately *not* the
    ``K_effective`` derivation β₃ consumes (feature 259) — the two terms
    price the same resource two different ways, and reaching for a ``total``
    here would be charging β₁ on a filtered count.
    """
    if isinstance(trials_charged, bool) or not isinstance(trials_charged, int):
        raise TrialsPenaltyError(
            f"trials_charged must be the count of budget-charging trials as a "
            f"non-negative integer — feature 221's BudgetAccount.charged, the "
            f"trials_charged column the node record carries (§6.1 line 279), "
            f"the raw statistical spend this term charges one β₁ per unit of — "
            f"got {trials_charged!r} ({type(trials_charged).__name__}): a bool "
            f"is a flag wearing a number, a float is a measurement where a "
            f"count belongs, and this is the raw spend β₁ prices — not the "
            f"honest count β₃ prices (feature 259's K_effective), which is a "
            f"different figure over the same trials, spelled differently on "
            f"purpose (feature 257, prd §7.1)"
        )
    if trials_charged < 0:
        raise TrialsPenaltyError(
            f"trials_charged must be a non-negative count of trials, got "
            f"{trials_charged!r}: the figure is the statistical budget the "
            f"search consumed, and a negative count is not a number of trials "
            f"anyone charged — the one direction that would pay the policy for "
            f"having drawn down the budget, which is the bonus feature 262 "
            f"counterfeits from the penalty's side of the formula (feature 257, "
            f"prd §7.1)"
        )
    return trials_charged


def _require_adjusted_seam(score: object) -> object:
    """The carrier's ``adjusted`` seam, read duck-typed and checked.

    The charge reaches the score through :meth:`WorldScore.adjusted` — the
    one seam the objective ships for the six β-terms — so the callable is
    read up front, before the count is consumed: a carrier that lacks it is
    refused naming the seam, because the repair is at the caller's wiring and
    not in any input the caller might also have got wrong.  This is the
    *only* attribute this law reads off the score — the term measures nothing
    off the pick's panel and deliberately does not read the score's epoch,
    for the reason the module docstring states: the epoch is where the panel
    was measured, not the scope of the hunt the caller's count covers.
    """
    seam = getattr(score, "adjusted", None)
    if not callable(seam):
        raise TrialsPenaltyError(
            f"the beta-one penalty rides WorldScore.adjusted — the one seam "
            f"the objective ships for the six beta-terms — and this carrier "
            f"exposes no callable adjusted (got {seam!r} on a "
            f"{type(score).__name__}): hand feature 256's WorldScore, or any "
            f"object exposing the adjusted its terms ride, and the charge "
            f"composes onto it (feature 257, prd §7.1)"
        )
    return seam
