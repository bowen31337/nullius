"""The scoring plugin: the per-world objective and the aggregation over
worlds.

Implements app_spec.xml, "Objective Scoring & CVaR Aggregation" — feature
256, *"System computes the per-world objective starting from out-of-sample
information ratio of the committed pick, which returns a scalar world
score"* — on the formula docs/alpha-engine-prd.md §7.1 states (line 318)
and docs/nullius-tech-architecture.md §10.3 restates (line 495):

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged               # statistical budget consumed
            − β₂ · null_pick_rate               # … five more terms, §7.1

app_spec.xml's M3 phase note names what the category as a whole is for:
*"Build deterministic replay, the full objective with regime-stratified
aggregation"*.  This member is the objective's half of that sentence, and
feature 256 is its head: the leading term and the scalar it starts.  The
six β-adjustments (features 257 through 262), the cross-world CVaR
aggregation (263-264), the scorer-process calibration figures (265-269)
are this member's later features — the β-terms arriving as their own
signed deltas through the :meth:`~scoring.WorldScore.adjusted` seam, the
aggregation consuming the scores whole, and none of them rewriting the
measurement underneath.

This package is a workspace member discovered by convention.  The module
loader (``app.module_loader``) scans the members the root
``pyproject.toml`` declares, imports each package, and composes whatever
the package's ``@register`` builder contributes — so the registration at
the foot of this module is the entire wiring story.  Nothing edits a
registry, router or factory to make the scoring plugin exist; importing
this module *is* joining the application.  All intra-package imports are
relative so the package imports identically under its own name and under
the loader's scan-time name.

**What composes, and why the objective is a component at all.**  The
builder contributes :func:`~scoring.world_objective` itself — the
callable — under the plugin name the spec's features carry
(``plugin="scoring"``).  A pure function is an unusual component in a
workspace whose members mostly contribute deployment state, and the
choice is deliberate on both of its sides:

* the objective never degrades.  Every store-bound builder in this
  workspace must answer ``None`` for a deployment that names nothing
  (``DATABASE_URL`` absent, ``ARTIFACT_ROOT`` unset), because its
  contribution *is* deployment state; the objective's whole
  configuration is the arithmetic, so its builder cannot fail, needs no
  environment, and composes to the same callable in every process — the
  property :func:`bootstrap.hyperparameter_world` makes for a generated
  world, held here for a formula;
* the cross-member seam is composition.  A workspace member never
  imports another workspace member and reaches shared shapes through
  ``app.*`` — and the member that will need this one is easy to name:
  the replay engine's scoring step (docs §10.1's
  ``score(pick, book, epoch, revealed, rounds)`` and §478's
  ``score = ...`` beside it) routes every world's leading term through
  this objective, and feature 222's
  :meth:`~policy_runtime.Termination.score` hands a scorer per
  termination.  The composed callable under ``"scoring"`` is how those
  callers reach the law without importing the member — the same reason
  the contract member contributes its ABI and not a service.

**The member's own surfaces.**  Feature 256's law is
:mod:`scoring._objective` — :func:`~scoring.world_objective` (the verb),
:class:`~scoring.WorldScore` (the value), :data:`~scoring.IR_DATES_MINIMUM`
(the floor beneath the ratio), and the one error
:class:`~scoring.WorldObjectiveError` from :mod:`scoring.errors`.  The
information ratio's spelling (mean over population standard deviation,
feature 80's) is restated there rather than imported from the evaluator
member — a member never imports a member — so a world score's leading
term and the node metrics a policy read in-sample are one axis by
construction, which is prd §7.1's Change A whole: scored on a sequestered
epoch, on the same ruler the diagnostics spoke.

**The aggregation over worlds is the member's second law (feature 263).**
*"System aggregates across worlds as a blend of the stratum mean and the
stratum minimum, which returns a score with lambda between 0.5 and
0.7"* — prd §7.2's and docs §10.3's ``V^m = (1 − λ) · mean_g(V_g^m) +
λ · min_g(V_g^m)``, the two lines the PRD calls *"larger impact than
anything else in this section"*.  It lives in :mod:`scoring._aggregate`
as :func:`~scoring.aggregate_objective` (the verb),
:class:`~scoring.AggregatedObjective` (the value, carrying the score,
the λ that blended it, the two terms, and every stratum's figure), the
band constants :data:`~scoring.LAMBDA_FLOOR` /
:data:`~scoring.LAMBDA_CEILING` / :data:`~scoring.LAMBDA_DEFAULT`, and
its own refusal :class:`~scoring.AggregationError`.  Like the objective
it is pure arithmetic — no store, no clock, no environment — so it adds
no component and no seat: the composed ``scoring`` component stays the
per-world objective (the callable the replay's scoring step routes
through), and the dreaming loop that will rank candidates on this
scalar (feature 274, persisting ``policy_revision.aggregate_score``)
reaches the verb the way sibling features reach this member's value
types — through the member's own namespace, the growth pattern the
policy-runtime member's free seams set.  The strata it blends over are
names, not yet regimes: *which* strata exist and the rejection of a
plain mean across them is feature 264's law over this seam — and that law
has since landed, in :mod:`scoring._regime_index`.

**The regime index is the member's third law (feature 264).**  *"System
rejects a plain mean across regimes, indexing aggregation strata by regime
instead"* — the feature whose dependency is 263 and whose sentence is the
other half of the same thought.  The regime a world belongs to is not
readable off a world score, so the strata the blend is taken over are a
*join*: feature 290's census assigns each stored world a stratum with the
causal rolling-window labeler, and :func:`~scoring.regime_strata` keys the
scores by those labels — the sentence's second clause — while refusing the
four shapes that would quietly average across regimes instead, all opening
with :data:`~scoring.PLAIN_MEAN_CODE` (``plain_mean``).  It lives in
:mod:`scoring._regime_index` beside the other two laws, with its own
refusal :class:`~scoring.RegimeIndexError` — a **sibling** of
:class:`~scoring.AggregationError`, never a child, because 263 refuses an
ask that cannot be blended and 264 refuses one that cannot be partitioned,
and the two repairs must stay distinguishable.
:func:`~scoring.regime_aggregate` composes the two so the aggregation this
category actually performs is one call whose strata are regimes by
construction.  It is pure
arithmetic like both, so the member still adds no component: the composed
``scoring`` component remains the per-world objective, and the index and
the blend are reached through this namespace.  Like 263's blend it
deliberately closes no vocabulary — feature 283's ``DEFAULT_STRATA`` is an
open set and a stratum name is not feature 241's legal theme, so the
regime set is the caller's to *declare* (and this module's to check when
declared), never this member's to enumerate.

**The β₆ orthogonality bonus is the member's fourth law (feature 262).**
*"System adds a beta-six orthogonality bonus measured against the
committed book, which returns the final world score"* — prd §7.1's last
line and its only addition, ``+ β₆ · orthogonality(committed book)``
(docs §10.3 agrees, line 498): five of the six β-terms take away and
this one *pays*, for the one thing a committed pick can offer that the
book it joins does not already hold.  It lives in
:mod:`scoring._orthogonality` as :func:`~scoring.orthogonality_bonus`
(the verb) and :data:`~scoring.BETA_SIX_DEFAULT` (the coefficient's
stated default — neither document sizes it), with its own refusal
:class:`~scoring.OrthogonalityError`.  The figure it pays on is
``1 − |ρ|``, ρ the population correlation of the pick's and the
committed book's panels over the sequestered epoch — pinned to the very
panel that earned the score, which the seam verifies by recomputing the
leading term's ratio in this member's one spelling.  Like the blend and
the index it is pure arithmetic — no store, no clock, no environment —
so it adds no component and no seat: the bonus rides
:meth:`~scoring.WorldScore.adjusted` exactly as :mod:`scoring._objective`
promised the six β-terms would, visible, signed and arguable, and the
penalties (features 257 and 258) were promised it — and feature 258's β₂
null-pick penalty has since landed there, charging for the planted nulls
the policy committed to, computed from the rate feature 265's scorer
process answers (:func:`scoring.null_pick_penalty`, reached from the
member's own namespace), with no component and no second seat either.

**The β₅ switch penalty is the member's fifth law (feature 261).**
*"System subtracts a beta-five term proportional to switch cost times
regime switch count, which returns the adjusted score"* — prd §7.1's
fifth line and one of its five subtractions,
``− β₅ · switch_cost · n_regime_switches`` (docs §10.3 agrees, line
497).  It lives in :mod:`scoring._switches` as
:func:`~scoring.switch_penalty` (the verb) and
:data:`~scoring.BETA_FIVE_DEFAULT` (the coefficient's stated default —
neither document sizes it), with its own refusal
:class:`~scoring.SwitchPenaltyError`, the penalties' first.  The
charge is one product of three non-negative factors — the coefficient,
the deployment's own switch cost (keyword-only and required: a price
is cost-model state, not a knob the member may default), and the
horizon's regime switch count, counted *here* off the ordered path of
regime labels the caller hands over, because the count is a fact about
the labels' order and only the path carries it.  Like every other term
of the formula it is pure arithmetic — no store, no clock, no
environment — so it adds no component and no seat: the composed
``scoring`` component stays the per-world objective, and the term is
reached through this namespace, landing its visible, signed, arguable
delta through :meth:`~scoring.WorldScore.adjusted` exactly as the
objective's own docstring promised the six β-terms would — and the
remaining penalty (feature 257) will find the seam already shaped when
it lands its own term through it.

**The β₄ divergence penalty is the member's sixth law (feature 260).**
*"System subtracts a beta-four term proportional to absolute divergence
between forward and backtest information coefficient, which returns the
adjusted score"* — prd §7.1's fourth line and one of its five
subtractions, ``− β₄ · |IC_forward − IC_backtest|`` (docs §10.3 agrees,
line 497).  It lives in :mod:`scoring._divergence` as
:func:`~scoring.divergence_penalty` (the verb),
:data:`~scoring.BETA_FOUR_DEFAULT` (the coefficient's stated default —
neither document sizes it, and this one is deliberately steeper than its
siblings'), :data:`~scoring.IC_BOUND` (the ``[−1, 1]`` an information
coefficient is bounded by as a correlation, which both figures are held
to), and its own refusal :class:`~scoring.DivergencePenaltyError`.  The
charge is one product of three non-negative factors — the coefficient,
and the two figures' absolute difference, derived *here* off the pair
rather than taken as a pre-computed divergence, because the divergence is
a fact about the pair and only the pair carries it.  prd §7.1's own
sentence that β₄ *"is computable only for nodes that have been through
the forward-test queue"* (line 329) is what makes the two figures
required rather than defaulted: a pick with no forward record has no
forward IC to hand over, and neither an absent figure read as zero (which
charges the pick its whole backtest on no evidence) nor one read as "no
divergence" (which pays it in full) is a measurement.  Like every other
term of the formula it is pure arithmetic — no store, no clock, no
environment — so it adds no component and no seat: the composed
``scoring`` component stays the per-world objective, and the term is
reached through this namespace.  It deliberately does **not** read the
figure feature 337 stores as a *ratio* (``live IC ÷ backtest IC``, prd
§8.2's secondary scorecard line): that is a different measurement of the
same pair, and dividing a backtest IC by it to manufacture a forward one
would be this member inventing a reading the forward-test record did not
hold.

**The β₃ deflation penalty is the member's seventh law (feature 259).**
*"System rejects a deflation input taken from raw trial counts,
computing the beta-three term from K_effective instead"* — prd §7.1's
third line, ``− β₃ · deflation(K_eff)`` (docs §10.3 agrees, line 496),
and the one β-term whose feature sentence is a *rejection*.  The
haircut is §7.3's growth law — the expected maximum null Sharpe across
``K`` trials, ``√(2·ln K)`` — and ``K`` is the *honest* count: the seam
takes the ledger member's ``K_effective`` derivation (feature 93's view
or feature 94's response, duck-read by its pooled ``total``) and
refuses a bare number — the shape a raw trial count takes, the ledger's
row count with null nodes included — because a number cannot say
whether it was counted honestly, and prd §4 (line 123) is why it must:
a null node consumed no degrees of freedom, so counting it would price
the calibration §4 tells the system to buy in research power it never
spent.  It lives in :mod:`scoring._deflation` as
:func:`~scoring.deflation_penalty` (the verb) and
:data:`~scoring.BETA_THREE_DEFAULT` (the coefficient's stated default —
neither document sizes it), with its own refusal
:class:`~scoring.DeflationPenaltyError`.  Like every other term of the
formula it is pure arithmetic — no store, no clock, no environment —
so it adds no component and no seat: the composed ``scoring`` component
stays the per-world objective, and the term is reached through this
namespace, landing its visible, signed, arguable delta through
:meth:`~scoring.WorldScore.adjusted` exactly as the objective's own
docstring promised the six β-terms would — and the remaining penalty
(feature 257) will find the seam already shaped when it lands its own
term through it.

**The β₂ null-pick penalty is the member's eighth law (feature 258).**
*"System subtracts a beta-two term proportional to null pick rate, which
returns the planted-null penalty that calibration depends on"* — prd
§7.1's second line, ``− β₂ · null_pick_rate`` (docs §10.3 agrees, line
496), and the term the PRD singles out as *"the term that does not exist
in the paper and without which none of this works"* (line 327).  It lives
in :mod:`scoring._nullpicks` as :func:`~scoring.null_pick_penalty` (the
verb), :data:`~scoring.BETA_TWO_DEFAULT` (the coefficient's stated
default — neither document sizes it) and :data:`~scoring.RATE_BOUND` (the
``[0, 1]`` a fraction of committed picks lives in, the fact feature 260's
:data:`~scoring.IC_BOUND` spells for its own input), with its own refusal
:class:`~scoring.NullPickPenaltyError`.  The charge is one product of two
non-negative factors — the coefficient, and the campaign's own realized
false discovery rate, prd §4.4's *"fraction of committed picks that are
planted nulls"*.  The rate is **handed over, never derived here**: app_spec
gives feature 265 ``depends_on="258"``, and 265's own sentence is that a
scorer process holding the sidecar key computes it *"while labels stay
in"* — so the dependency arrow runs from the computation to this term and
never back, because deriving the rate means reading ``is_null``, the bit
§4.2 grants to exactly one component.  It deliberately does **not**
reweight to a deployment base rate: ``FDR_deploy`` at π₀ ≈ 0.9 is feature
267's arithmetic over the same pair of figures and feature 268's headline,
and folding it in would make β₂ a projection of what the policy *would*
do rather than the error it made.  Like every other term of the formula it
is pure arithmetic — no store, no clock, no environment — so it adds no
component and no seat: the composed ``scoring`` component stays the
per-world objective, and the term is reached through this namespace,
landing its visible, signed, arguable delta through
:meth:`~scoring.WorldScore.adjusted` exactly as the objective's own
docstring promised the six β-terms would — and the last of them (feature
257's β₁) will find the seam already shaped when it lands its own term
through it.

**The scorer process is the member's ninth law and its first component
beside the objective (feature 265).**  *"System computes null pick rate
inside a scorer process holding the sidecar key, which returns the rate
while labels stay in"* — docs §10.3's own line (507): the number flows
out, the labels do not.  It lives in :mod:`scoring._scorer` as
:class:`~scoring.NullPickScorer` (the process — it holds the sidecar,
duck-read by the one ``assignment(node_id)`` seam the null oracle's own
target route documents) and :meth:`~scoring.NullPickScorer.null_pick_rate`
(the verb, answering prd §4.4's *"fraction of committed picks that are
planted nulls"* as one bare ``float``), with its own refusal
:class:`~scoring.NullPickRateError`.  Unlike the eight laws before it
this one is *not* pure arithmetic: the labels it counts live in the
oracle's sealed sidecar, so the verb reads, and the reading is why the
feature exists — the rate the β₂ term charges on (feature 258) cannot be
derived anywhere else, because deriving it means reading ``is_null``, the
bit prd §4.2 grants to exactly one component.  It therefore takes the
component the eight β-laws never needed: :data:`~scoring.SCORER_COMPONENT_NAME`
(``scoring-null-pick-rate``), composing to the process or ``None``
(deployment state — where no sidecar is configured there is no rate to
compute, and the caller that needs one refuses to proceed rather than
scoring rateless), reached from the app package through the sibling seat
:mod:`app.modules.scoring.scorer`.  The barrier is the answer's type, not
a promise: no accessor for the held sidecar, no label cache, a ``repr``
that names the class and nothing it holds, and refusals that name the
*pick* and never the *branch* — which nodes are null is the one fact this
process exists to keep inside.

**The error accounting is the member's tenth law (feature 269).**
*"System accounts Type-A commitment errors separately from Type-B
depth-past-flip errors, which returns each as its own metric"* — prd
§4.1.2's instruction (line 140: *"Separate the error accounting"*) and
docs §7.3.1's table, which names conflating the two *"the original
design's blind spot."*  It lives in :mod:`scoring._accounting` as
:func:`~scoring.account_errors` (the verb) and
:class:`~scoring.ErrorAccounting` (the value — one field per metric, no
total, no blend), with its own refusal
:class:`~scoring.ErrorAccountingError`.  Type-A's metric is the rate
feature 265's process answers, asked through its one public verb — the
process hands back no count of nulls and this member does not ask for
one — and Type-B's metric is a count of the explored nodes sitting at
or beyond their branch's flip (§7.2's inclusive boundary), over depth
facts the caller hands over already joined, because the ancestor walk
that joins them is the null oracle's verb and 265's docstring already
declines to restate it.  Like the eight free laws it is arithmetic
over figures another law owns plus the one composed ask, so it adds no
component and no seat: the composed ``scoring`` component stays the
per-world objective, and the accounting is reached through this
namespace.  It prices nothing — β₂ is feature 258's term and β₁ feature
257's; the accounting measures the two errors, the terms charge for
them — and it persists nothing: the per-campaign Type-B trend docs line
909 lists is the ops member's (feature 345), which reads this figure.

**No persistence here, by the same law that keeps the arithmetic pure.**
The ``replay_score`` row is the replay plugin's (feature 255); this
member answers the value it is written from, exactly as migration 0109
shapes it.  The one feature of this category that still owns state after
265 — feature 267's per-campaign ``FDR_deploy`` — will take its own
component beside these two when it lands, the growth pattern
``app.modules.bootstrap`` took for its pool: another component name,
another sibling seat, this module's surface untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.module_loader import register

from ._accounting import ErrorAccounting, account_errors
from ._aggregate import (
    LAMBDA_CEILING,
    LAMBDA_DEFAULT,
    LAMBDA_FLOOR,
    AggregatedObjective,
    aggregate_objective,
)
from ._deflation import BETA_THREE_DEFAULT, deflation_penalty
from ._divergence import BETA_FOUR_DEFAULT, IC_BOUND, divergence_penalty
from ._nullpicks import BETA_TWO_DEFAULT, RATE_BOUND, null_pick_penalty
from ._objective import IR_DATES_MINIMUM, WorldScore, world_objective
from ._orthogonality import BETA_SIX_DEFAULT, orthogonality_bonus
from ._regime_index import PLAIN_MEAN_CODE, regime_aggregate, regime_strata
from ._scorer import NullPickScorer
from ._switches import BETA_FIVE_DEFAULT, switch_penalty
from .errors import (
    AggregationError,
    DeflationPenaltyError,
    DivergencePenaltyError,
    ErrorAccountingError,
    NullPickPenaltyError,
    NullPickRateError,
    OrthogonalityError,
    RegimeIndexError,
    ScoringError,
    SwitchPenaltyError,
    WorldObjectiveError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; the annotation is lazy
    from collections.abc import Callable

__all__ = [
    "BETA_FIVE_DEFAULT",
    "BETA_FOUR_DEFAULT",
    "BETA_SIX_DEFAULT",
    "BETA_THREE_DEFAULT",
    "BETA_TWO_DEFAULT",
    "COMPONENT_NAME",
    "IC_BOUND",
    "IR_DATES_MINIMUM",
    "LAMBDA_CEILING",
    "LAMBDA_DEFAULT",
    "LAMBDA_FLOOR",
    "PLAIN_MEAN_CODE",
    "RATE_BOUND",
    "SCORER_COMPONENT_NAME",
    "AggregatedObjective",
    "AggregationError",
    "DeflationPenaltyError",
    "DivergencePenaltyError",
    "ErrorAccounting",
    "ErrorAccountingError",
    "NullPickPenaltyError",
    "NullPickRateError",
    "NullPickScorer",
    "OrthogonalityError",
    "RegimeIndexError",
    "ScoringError",
    "SwitchPenaltyError",
    "WorldObjectiveError",
    "WorldScore",
    "account_errors",
    "aggregate_objective",
    "deflation_penalty",
    "divergence_penalty",
    "null_pick_penalty",
    "orthogonality_bonus",
    "regime_aggregate",
    "regime_strata",
    "switch_penalty",
    "world_objective",
]

__version__ = "0.1.0"

#: The component name this member registers under — the plugin name the
#: spec's features carry (``plugin="scoring"``), so the component key, this
#: member's seat (:mod:`app.modules.scoring`) and the spec cannot drift
#: apart.  The features of this category that own their own deployment
#: state (265's scorer process, below; 267's FDR store when it lands)
#: register their own names beside this one rather than widening this one,
#: the way ``bootstrap-pool`` sits beside ``bootstrap``.
COMPONENT_NAME = "scoring"


@register(COMPONENT_NAME)
def build_world_objective() -> Callable[..., WorldScore]:
    """Component builder: the per-world objective itself (feature 256).

    Takes no arguments — that is the factory's registration protocol — and
    contributes :func:`~scoring.world_objective` unchanged, so a composed
    application carries the one callable every world's leading term is
    computed through (prd §7.1, docs §10.3) and the members that need it
    reach it through the app package rather than importing this member.

    Never raises and reads no environment — there is nothing to read.  The
    objective's whole configuration is the arithmetic; a deployment cannot
    misconfigure it, an empty workspace cannot degrade it, and the factory
    building this component on every ``create_app()`` call costs one
    attribute lookup.  That is not a boast about this feature but the
    property the objective must have to be the ranking's floor: a score
    that could fail to compose would be a ranking that silently drops the
    worlds it was asked to compare.

    A second spelling of the builder — the sibling members' "ordinary
    function a script calls directly" — is deliberately *not* shipped
    here, because the builder's contribution already is one: the callable
    a direct caller wants is :func:`~scoring.world_objective` itself,
    reached from this member's own namespace.
    """
    return world_objective


#: The component name the scorer process registers under — feature 265's
#: own, beside :data:`COMPONENT_NAME` the way ``bootstrap-pool`` sits
#: beside ``bootstrap``.  Spelled here, in the law module
#: (:data:`scoring._scorer.SCORER_COMPONENT_NAME`, for a caller importing
#: the process without the package surface) and in the sibling seat
#: (:data:`app.modules.scoring.scorer.COMPONENT_NAME`, for a caller
#: reaching through the app package) — three spellings of one name, and
#: the member's suite asserts they agree so they cannot drift apart
#: silently.  Prefixed with the member's own name because a composed
#: application's ``order`` is name-sorted and the process must sort
#: beside — never inside — the member's other component.
SCORER_COMPONENT_NAME = "scoring-null-pick-rate"


@register(SCORER_COMPONENT_NAME)
def build_null_pick_scorer() -> NullPickScorer | None:
    """Component builder: the scorer process this environment composes
    (feature 265).

    Takes no arguments — the factory's protocol — and contributes the
    :class:`~scoring.NullPickScorer` the deployment's environment names,
    by delegating the whole question to the null oracle's own sidecar
    resolution (see :meth:`NullPickScorer.resolve` for the seam's laws:
    reached through ``importlib`` at call time because a member never
    imports another member, trusted never to raise because the factory
    builds this component in every process, sidecar or not).

    Answers ``None`` — contributing no process, never failing composition
    — where no sidecar is configured: a deployment that names no location
    and key has no labels to hold, and the "degrade, don't break" stance
    every store-bound builder here takes is the only honest answer.  The
    consequence is the one :meth:`bootstrap.BootstrapPool.resolve`-shaped
    builders all state: *no sidecar is configured* and *the sidecar is
    broken* are different facts, and only the second may ever be quiet.
    A caller that reaches the app package for the process and finds
    ``None`` must refuse to proceed rather than score rateless — the rate
    is the term prd §7.1 line 327 calls *"without which none of this
    works"*, and a loop that charged β₂ on an invented ``0.0`` would be
    a calibration that never ran.

    Composing an application never opens the sidecar: construction holds
    the carrier, the sealed file is read per ask, so asking is always
    safe — the same promise the objective's builder above makes for the
    arithmetic and the pool's makes for its database.
    """
    return NullPickScorer.resolve()
