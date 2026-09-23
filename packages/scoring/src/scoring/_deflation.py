"""Feature 259, the beta-three deflation penalty — the formula's third
term, one haircut for the hypotheses the search implicitly tested.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 259: *System
rejects a deflation input taken from raw trial counts, computing the
beta-three term from K_effective instead* — the third line of the block
docs/alpha-engine-prd.md §7.1 states (line 321) and docs/nullius-tech-
architecture.md §10.3 restates (line 496):

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged               # five penalties, each its own feature
            − β₃ · deflation(K_eff)             # ← this module's line (§7.1 line 321)
            …

Five of the six β-terms take away, and this one takes away for the
formula's one *count*: how many hypotheses the campaign implicitly
tested while finding the pick.  prd §7.3 is the section the line points
at (line 321's own comment — *"multiple-testing haircut, §7.3"*) and its
first table is the law's whole arithmetic: the expected maximum Sharpe
under the null across ``K`` trials *"grows like ``√(2 ln K)``, in units
of ``SE(Sharpe)``"* (line 343).  The section also states why the term
is the one whose feature sentence is a *rejection*: *"It only wins if
``K`` is counted honestly"* (line 355) — search pays because the bar
the log sets is far cheaper than the shots it buys, and only an honest
``K`` keeps that bargain either way.
:func:`deflation_penalty` lands the haircut — negated, visible and
arguable — through :meth:`WorldScore.adjusted`, exactly the seam the
objective's own docstring promised the six β-terms would ride.

**The spec's verb is *rejects*, and the rejection is of a shape rather
than a value.**  A deflation input "taken from raw trial counts" is a
bare number: the ledger's plain row count
(:meth:`ledger.store.TrialLedger.count`, every row, null nodes included)
or the ``len(rows)`` a caller computes over them.  No arithmetic on an
integer can say whether it was counted honestly — there is nothing in a
``47`` that could notice the null nodes hiding inside it — so the seam
refuses the shape: ``k_effective`` must be the *derivation* (feature
93's ``KEffective`` view or feature 94's ``KEffectiveResponse`, either
satisfies the read), and a bare number is refused whatever its value,
*even one that happens to equal the honest count* — provenance is not
checkable at a seam, and admitting the lucky numbers is how the
inflated ones slip through.  The same reasoning
:mod:`scoring._divergence` states for a pre-computed divergence (*"a
scalar handed over could not be checked against anything"*), held here
for a count; and it is the mirror of the ledger's own stance, whose
derivation refuses an unreadable directive rather than skipping it
because silently skipping can only understate ``K``.

**Why the derivation and not the rows.**  β₄ derives its figure from
the pair it is handed because the divergence is a fact about two
figures only the caller's pair carries.  The honest count is the
opposite shape of fact: it is not a fact about this ask's figures at
all, but a **derived view the ledger member already owns** — feature
93's filter over the trial rows, named in docs §8's derived views
(line 385: *"``K_effective`` per epoch (filtered on
``charges_budget``) … deflation inputs for ``β₃``"*) and exposed
through feature 94's route as *the deflation input*.  Restating the
filter here — counting ``(epoch, charges_budget)`` pairs a second time,
in a second member — would be a second spelling of one derivation that
could drift, and the drift directions are both §7.3's failure (a
directive misread inflates, a charged row dropped understates).  So
this term takes the one derivation and refuses everything else, the
same division of labour :mod:`scoring._regime_index` takes toward the
census's labels: the view is the ledger's, the haircut is this
member's, and neither reaches into the other's half.

**The one figure the term asks the view for is ``total``.**  The view
is per-epoch because the ledger reports per epoch (features 93 and 94
both say so); the term asks it for the pooled one — *"the number the
deflation term consumes when it is asked for one figure rather than a
breakdown"*, the ledger's own stated contract for this feature —
because §7.3's ``K`` is the count of hypotheses *the search* tested,
the hunt the pick came out of, and the caller is the one who knows that
scope: it hands the view over the trials that were that hunt (a
campaign's ledger, one epoch's slice of it) and the term reads the
figure they sum to.  A term that reached for ``of(epoch)`` instead
would silently re-scope the haircut to whichever epoch the carrier
happened to name, and a score whose epoch went unnamed would reach for
the un-named bucket without saying so — the score's epoch is where its
panel was *measured* (feature 256's own law), not the scope of the
hunt that earned it.  One figure, one spelling, the scoping stated by
the caller.

**Null nodes never move this number, and over-counting them is not
harmless.**  prd §4 (line 123) is the fact the filter encodes: a null
node's signal *"was never compared to real forward returns, so it
consumed agent calls and CPU but* **no statistical degrees of
freedom***.  It must not count toward ``K`` in the deflation term"* —
and the same paragraph states the economics the raw count would break:
*"the true price of ``φ = 0.25`` is a quarter of the LLM bill, not a
quarter of the research power.  Buy more calibration than feels
comfortable."*  A deflation input taken from raw counts prices every
planted null at research power it never spent, teaching the policy to
plant fewer nulls the more it searched — the exact inversion of §4's
instruction.  Understating ``K`` fails the other way (a haircut too
small to stop a false discovery, the direction the ledger's derivation
refuses to move by accident).  It only wins if ``K`` is counted
honestly, both ways — which is why the term refuses to guess.

**``K`` of zero or one pays no haircut, and the zero is a fact rather
than an absence.**  ``ln 1 = 0``: one honest trial tests one
hypothesis, there is no selection among many to correct, and the growth
law says so in arithmetic — the expected maximum of a single null
Sharpe is ``0`` in SE units.  ``K = 0`` is the all-null epoch feature
93 deliberately reports at ``0`` rather than omitting (*"the deflation
term must be told this epoch contributed no degrees of freedom"*), so
the haircut for zero tested hypotheses is nothing, the same figure
``K = 1`` answers — and refusing the ``0`` would make the ledger's
reporting a fact no consumer may state.  Neither is an absent
measurement read as a stand-in, the stance :mod:`scoring._divergence`
takes toward a missing forward IC: here the figure is measured,
reported and honored.

**The charge is one negated product, so the term can only subtract.**
The bar is a square root and therefore non-negative; the coefficient is
refused when negative (below); so the delta is ``− β₃ · √(2·ln K_eff)``
with no path by which a float could flip the sign — one product, one
negation, no summation and no cancellation.  Zero is admitted for the
coefficient (an ablation the documents leave to the deployment) and
answered by the count itself for ``K ∈ {0, 1}``, the two ways a
campaign can be charged nothing without the term declining to run.

**β₃ is the caller's knob, carried with a stated default.**  Neither
document sizes the coefficient — §7.1 spells the term and moves on — so
:data:`BETA_THREE_DEFAULT` states a parameterization rather than hiding
a constant, the stance feature 263's :data:`~scoring.LAMBDA_DEFAULT`
takes for λ and each landed β-sibling for its own coefficient: the
dreaming loop's offline tuning is expected to set it per cycle
(*"default chosen per cycle from live evidence and prior sweeps"*, prd
§7.4), and every finite non-negative value composes identically.  The
default is ``0.25`` — the base its β₅ and β₆ siblings set, not β₄'s
deliberate half — because this term's own factor already carries the
steepest magnitudes in the formula: the bar crosses ``3.0`` at a
hundred honest trials and ``4.8`` at a hundred thousand, where β₄'s
bound caps at ``2.0`` and β₆'s payment at ``1.0``, so the coefficient
takes the base quarter and lets §7.3's log do the scaling.  At a
quarter, a hundred honest trials charge ~0.76 of a ratio unit — visible
beside a leading term of order one — and the hundredfold search from
1,000 to 100,000 trials costs 29% more charge rather than 100× more,
which is the log being on search's side: the property §7.3 exists to
claim, priced so the search that found the pick is still worth running.
The coefficient a deployment actually ran is its own state, persisted
beside the score it moved (``replay_score.beta``, feature 255).

**What this law deliberately does not do.**  It does not touch the
leading term — the haircut lands beside the measurement or not at all,
and a pick's :attr:`~scoring.WorldScore.ir_oos` is the same number with
the penalty applied and without.  It does not read the trial ledger:
reaching the rows is the ledger member's data access, and a caller with
no view has not been refused — it has not yet asked (the same division
of labour :mod:`scoring.errors` states for the sequestered epoch).  It
does not re-derive ``K_effective`` from rows handed over, for the
reason the module docstring states: one derivation, one spelling, in
the member that owns the filter.  It does not aggregate (263/264), does
not calibrate (265-269), and persists nothing — the ``replay_score``
row is the replay plugin's (feature 255), and it already carries the
score and the β.  It takes no component and no seat: like the blend,
the index, the bonus and the two landed penalties it is pure
arithmetic — no store, no clock, no environment — so the composed
``scoring`` component stays the per-world objective and this term is
reached through the member's own namespace, the growth pattern every
free seam in this workspace takes.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers` and the
member's own objective and error — no third-party import at module scope,
so the factory's scan (which imports this package to fire its
``@register`` builder) pays nothing for the law.
"""

from __future__ import annotations

import math
from numbers import Real

from ._objective import WorldScore
from .errors import DeflationPenaltyError

__all__ = [
    "BETA_THREE_DEFAULT",
    "deflation_penalty",
]

#: The β₃ a caller that names none gets.  Neither prd §7.1 nor docs §10.3
#: sizes the coefficient — the formula spells ``− β₃ · deflation(K_eff)``
#: and moves on — so this is a stated parameterization rather than a
#: hidden constant, the stance feature 263's ``LAMBDA_DEFAULT`` takes for
#: λ, feature 262's ``BETA_SIX_DEFAULT`` for β₆ and feature 261's
#: ``BETA_FIVE_DEFAULT`` for β₅.
#:
#: The base quarter rather than β₄'s deliberate half, on the term's own
#: arithmetic: the factor this coefficient scales is already the largest
#: in the formula at realistic counts — §7.3's bar crosses 3.0 at a
#: hundred honest trials and 4.8 at a hundred thousand, where β₄'s bound
#: caps at 2.0 and β₆'s payment at 1.0 — so the quarter keeps a hundred
#: honest trials at ~0.76 of a ratio unit (visible beside a leading term
#: of order one) while the hundredfold search from 1,000 to 100,000
#: trials costs 29% more charge, not 100× more: the log on search's
#: side, which is the property §7.3 exists to claim.  Dyadic like its
#: siblings, so the coefficient's own arithmetic is exact in binary.
#: The coefficient a deployment actually ran is its own state, persisted
#: beside the score it moved (``replay_score.beta``, feature 255).
BETA_THREE_DEFAULT: float = 0.25


def deflation_penalty(
    score: object,
    *,
    k_effective: object,
    beta: float = BETA_THREE_DEFAULT,
) -> WorldScore:
    """Subtract the beta-three deflation penalty from a world score —
    §7.1's third term, §7.3's multiple-testing haircut over the honest
    count.

    The feature's verb.  ``score`` is the world score the charge lands on
    — feature 256's :class:`~scoring.WorldScore`, read duck-typed by the
    one attribute this law needs (``adjusted``, the seam every β-term
    rides) and never by ``isinstance``, because the module loader imports
    this member under a synthetic name and re-executes it, so a score this
    process composed may be a second ``WorldScore`` class object.  The
    answer is that carrier's own ``adjusted`` return: the same world,
    pick, epoch and frozen measurement, with :attr:`WorldScore.score`
    moved *down* by ``beta · √(2·ln K_effective)`` — never up, by the law
    above, and by nothing at all when the honest count is zero or one.

    ``k_effective`` is the honest count of hypotheses the search tested —
    keyword-only, required, and a **derivation rather than a number**:
    feature 93's :class:`~ledger.keffective.KEffective` view or feature
    94's :class:`~ledger.keffective_route.KEffectiveResponse` (either
    satisfies the read, and neither imports anything here — the seam is
    duck-typed like every carrier this member reads), consumed by the one
    figure the ledger states this term takes: ``total``, the pooled count
    of budget-charging trials.  ``beta`` is the β₃ the charge is weighted
    by, keyword-only, :data:`BETA_THREE_DEFAULT` when unnamed.

    Refuses, with :class:`~scoring.DeflationPenaltyError` and nothing
    partial:

    * a ``beta`` that is not a finite real, or is negative — the spec's
      verb is *subtracts*, and a negative coefficient would counterfeit a
      bonus through the penalty seam, teaching the loop that searching
      profligately pays;
    * a ``k_effective`` that is a bare number (``int``, ``float``, a
      ``bool`` wearing an int's type) — the shape a deflation input taken
      from raw trial counts takes, refused whatever its value: a count
      cannot say whether it was counted honestly, and prd §4 (line 123)
      is why it must — a null node consumed no degrees of freedom and
      must not inflate the haircut;
    * a ``k_effective`` carrier that exposes no ``total`` that is a
      non-negative integer count of trials;
    * a carrier that exposes no callable ``adjusted`` to ride.

    Deterministic and pure: no store, no clock, no environment, and the
    same view answers the same charge to the last bit — the bar is one
    square root of one logarithm over the pooled count and the delta one
    negated product of it, with no summation whose order could matter and
    no float path by which the subtraction could dress as an addition.
    """
    weight = _require_beta(beta)
    honest = _require_k_effective(k_effective)
    adjusted = _require_adjusted_seam(score)
    return adjusted(-(weight * _null_bar(honest)))


# -- the seam's private vocabulary ----------------------------------------------


def _null_bar(trials: int) -> float:
    """§7.3's growth law over the honest count: ``√(2·ln K)``, in SE units.

    The expected maximum Sharpe under the null across ``K`` trials (prd
    §7.3, line 343), which is the bar a pick's leading term must clear
    before it means anything — the leading term is a mean over a standard
    deviation and therefore already speaks in SE units, so the bar lands
    beside it in the same units with no rescaling this module would have
    to invent.  Spelled once, ``sqrt(2·log(K))``, and spelled identically
    wherever the suite pins it against §7.3's own table (10 → 2.15, 100 →
    3.03, 1,000 → 3.72, 10,000 → 4.29, 100,000 → 4.80).

    ``K`` below two answers ``0.0`` and takes no logarithm at all:
    ``ln 1 = 0`` is the law's own arithmetic (one honest trial tests one
    hypothesis, and the expected maximum of a single null Sharpe is 0),
    and ``K = 0`` is the all-null epoch feature 93 reports at zero —
    zero hypotheses charged budget, so zero selection to correct.  Both
    are measured figures honored as no haircut, never an absence read as
    a stand-in.
    """
    if trials < 2:
        return 0.0
    return math.sqrt(2.0 * math.log(trials))


def _require_beta(beta: object) -> float:
    """Narrow β₃ to a finite non-negative ``float``, refusing the rest.

    ``bool`` is refused before the real check (a ``bool`` is an ``int``
    in Python's hierarchy and not a coefficient); NaN and ±inf are refused
    with it — a NaN weight would make the delta a NaN the ranking silently
    drops, and an infinite one is not a coefficient anyone tuned.
    Negative is refused on the feature's own sentence: the spec's verb is
    *subtracts*, and a negative β₃ would counterfeit a bonus through the
    penalty seam, teaching the loop that the way to pay for a profligate
    search is to run one.  Zero is admitted — an ablation the documents
    leave to the deployment, not a contradiction of the term.
    """
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise DeflationPenaltyError(
            f"beta must be the beta-three coefficient as a real number, got "
            f"{beta!r} ({type(beta).__name__}): the deflation penalty is "
            f"weighted by a coefficient the deployment chose and the "
            f"replay_score row persists (feature 255), and a value that is "
            f"not a real has no place in either (feature 259, prd §7.3)"
        )
    weight = float(beta)
    if not math.isfinite(weight):
        raise DeflationPenaltyError(
            f"beta must be finite, got {weight!r}: a NaN weight would turn "
            f"the charge into a NaN the dreaming loop's argmax silently "
            f"drops, and an infinite one is not a coefficient anyone tuned "
            f"(feature 259, prd §7.3)"
        )
    if weight < 0.0:
        raise DeflationPenaltyError(
            f"beta must not be negative, got {weight!r}: the spec's verb is "
            f"subtracts — beta-three charges the score for the hypotheses "
            f"the search implicitly tested — and a negative coefficient "
            f"would counterfeit a bonus through the penalty seam, teaching "
            f"the loop that searching profligately pays; an added term is "
            f"feature 262's business, the formula's one and only "
            f"(feature 259, prd §7.3)"
        )
    return weight


def _require_k_effective(k_effective: object) -> int:
    """The one figure this law reads off the derivation: its pooled total.

    A bare number is refused first, on the feature's own verb: the shape
    a deflation input taken from raw trial counts takes — the ledger's
    plain row count (``TrialLedger.count()``, null nodes included) or the
    ``len(rows)`` a caller computes over them — and no arithmetic on a
    number can say whether it was counted honestly.  A ``bool`` is an
    ``int`` in Python's hierarchy and arrives here as the count 0 or 1,
    so it is refused in the same breath rather than one branch earlier.

    Then the duck-read, ``total``, validated as what the ledger's
    derivation answers: a non-negative ``int``, and not a ``bool`` — the
    same discipline the ledger's own view applies to its counts, restated
    at the seam that consumes them.  A float total (``53.0``) is refused
    as the shape fault it is: the derivation counts rows, and a count of
    trials is an integer or it is not a count.  Zero passes — the all-null
    epoch's measured figure, honored by :func:`_null_bar` as no haircut —
    and a negative count is refused because it is not a number of
    hypotheses anyone tested, the direction the honest counter must not
    move in any more than it may understate.
    """
    if isinstance(k_effective, (bool, Real)):
        raise DeflationPenaltyError(
            f"k_effective must be the K_effective derivation — feature 93's "
            f"view or feature 94's response, something exposing total, the "
            f"pooled count of budget-charging trials — got {k_effective!r} "
            f"({type(k_effective).__name__}): a bare count is a deflation "
            f"input taken from raw trial counts, and feature 259 rejects it "
            f"— the ledger's plain row count includes every null node a "
            f"campaign ran, and a null node consumed agent calls and CPU "
            f"but no statistical degrees of freedom, so it must not inflate "
            f"the haircut (prd §4 line 123); a number cannot say whether it "
            f"was counted honestly, and this seam refuses the shape rather "
            f"than guess at the value, whatever the value happens to be "
            f"(feature 259, prd §7.3)"
        )
    total = getattr(k_effective, "total", None)
    if isinstance(total, bool) or not isinstance(total, int):
        raise DeflationPenaltyError(
            f"k_effective must speak K_effective — feature 93's view or "
            f"feature 94's response, whose total is the pooled honest count "
            f"the deflation term consumes — and this carrier exposes no "
            f"total that is one (got {total!r} on a "
            f"{type(k_effective).__name__}): the deflation input is a "
            f"derived view over the rows whose charges_budget is true, read "
            f"by the one figure it sums to, and a carrier that cannot state "
            f"that figure has no haircut to land (feature 259, prd §7.3)"
        )
    if total < 0:
        raise DeflationPenaltyError(
            f"a K_effective total must be a non-negative count of trials, "
            f"got {total!r}: the derivation counts rows whose charges_budget "
            f"is true, and a negative count is not a number of hypotheses "
            f"anyone tested — the honest counter cannot move in that "
            f"direction any more than it may understate, the one direction "
            f"that lets a false discovery through (feature 259, prd §7.3)"
        )
    return total


def _require_adjusted_seam(score: object) -> object:
    """The carrier's ``adjusted`` seam, read duck-typed and checked.

    The charge reaches the score through :meth:`WorldScore.adjusted` — the
    one seam the objective ships for the six β-terms — so the callable is
    read up front, before the count is consumed: a carrier that lacks it
    is refused naming the seam, because the repair is at the caller's
    wiring and not in any input the caller might also have got wrong.
    This is the *only* attribute this law reads off the score — the term
    measures nothing off the pick's panel and deliberately does not read
    the score's epoch, for the reason the module docstring states: the
    epoch is where the panel was measured, not the scope of the hunt the
    caller's view covers.
    """
    seam = getattr(score, "adjusted", None)
    if not callable(seam):
        raise DeflationPenaltyError(
            f"the beta-three penalty rides WorldScore.adjusted — the one seam "
            f"the objective ships for the six beta-terms — and this carrier "
            f"exposes no callable adjusted (got {seam!r} on a "
            f"{type(score).__name__}): hand feature 256's WorldScore, or any "
            f"object exposing the adjusted its terms ride, and the charge "
            f"composes onto it (feature 259, prd §7.3)"
        )
    return seam
