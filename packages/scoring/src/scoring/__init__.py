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
objective's own docstring promised the six β-terms would — and feature
257's β₁ has since taken the same path: one charge per unit of the
statistical budget the search consumed, ``− β₁ · trials_charged`` (prd
§7.1's first line, the paper's ``β₁ N`` rewritten by §7.1's Change B to
count degrees of freedom rather than agent calls), reached as
:func:`~scoring.trials_penalty` from the member's own namespace with no
component and no second seat either — the penalties' first by feature
number, and the one whose count is the raw spend, not feature 259's
honest ``K_effective`` derivation.

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
docstring promised the six β-terms would — and feature 257's β₁ has since
taken the same path: one charge per unit of the statistical budget the
search consumed, reached as :func:`~scoring.trials_penalty` from the
member's own namespace, the raw spend rather than feature 259's honest
count, with no component and no second seat either.

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
docstring promised the six β-terms would — and feature 257's β₁ has since
taken the same path: one charge per unit of the statistical budget the
search consumed, reached as :func:`~scoring.trials_penalty` from the
member's own namespace, the raw spend rather than feature 259's honest
count, with no component and no second seat either.

**The β₁ trials penalty is the member's thirteenth law (feature 257).**
*"System subtracts a beta-one term proportional to trials charged, which
returns a score penalized for consumed statistical budget"* — prd §7.1's
first line and the paper's original ``β₁ N``, rewritten by §7.1's Change
B (docs §10.3, prd §705: ``β₁ N (agent calls)`` → ``β₁ · trials charged
(statistical budget)``) to count the binding resource rather than the
embarrassingly-parallel compute the paper priced.  It lives in
:mod:`scoring._trials` as :func:`~scoring.trials_penalty` (the verb) and
:data:`~scoring.BETA_ONE_DEFAULT` (the coefficient's stated default —
neither document sizes it, the base quarter its β₃, β₅ and β₆ siblings
set), with its own refusal :class:`~scoring.TrialsPenaltyError`.  The
charge is one product of two non-negative factors — the coefficient, and
the raw count of budget-charging trials, the statistical spend feature
221's ``BudgetAccount.charged`` answers and §6.1's ``trials_charged``
column holds, taken **directly, not derived**: this is the term's whole
shape, one ``β₁`` per unit with no square root and no logarithm to soften
it.  It is deliberately **not** feature 259's ``K_effective``: β₁ and β₃
are two terms over the *same* resource, priced two different ways — β₁
the raw spend, β₃ the multiple-testing bar over the honest count — and
conflating them would either double-count the charge or drop it, so the
seam reads the one figure its own term names and never reaches for a
``total`` or a ``by_epoch`` breakdown.  Like every other term of the
formula it is pure arithmetic — no store, no clock, no environment — so
it adds no component and no seat: the composed ``scoring`` component
stays the per-world objective, and the term is reached through this
namespace, landing its visible, signed, arguable delta through
:meth:`~scoring.WorldScore.adjusted` exactly as the objective's own
docstring promised the six β-terms would.

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

**The calibration figures are the member's eleventh law (feature 266).**
*"System computes sensitivity and specificity on planted nulls, which
returns both as base-rate independent figures"* — prd §4.1.3's pair
(line 144: *"Sensitivity and specificity are base-rate independent, so
measure them where you have power for both, then reweight"*) and §11's
tracked-not-targeted secondary (line 539), the two figures docs §10.3
lines 509-515 name as the base-rate independent ground the raw rate's
``FDR_deploy`` reweighting stands on.  It lives in
:mod:`scoring._calibration` as :class:`~scoring.CalibrationFigures`
(the value — two fields, one per figure, and deliberately no third) and
:meth:`~scoring.NullPickScorer.calibration_figures` (the verb — *on
the process* feature 265 built, the door 265's own docstring reserved:
the calibration figures that follow it *"will land as their own verbs
on this process or beside it"*, and this one could only land on the
process, because its denominators are the planted *classes* and only
the held labels can count a class — feature 269's seam could ride the
rate verb unchanged, and this one cannot), with its own refusal
:class:`~scoring.CalibrationFiguresError`.  The figures classify the
planted population a caller declares against the picks the campaign
committed: sensitivity is the fraction of the planted reals the picks
found, specificity the fraction of the planted nulls left uncommitted
— both conditional within a ground-truth class, so the campaign's φ
cancels, and the value makes that structural by carrying no figure
that divides by the declaration's size and by taking no π₀ (the
reweighting is 267's, over exactly this pair, and 268's headline
rejection stands over that figure and not these).  The empty-class
refusals hold §4.1.1's floor — a plant with no reals has no sensitivity
to measure and one with no nulls no specificity — while the empty
*declaration* is answered (``0.0`` and ``1.0``, the corner where
nothing was found and nothing wrongly declared), and the barrier holds
for the wider answer exactly as 265 stated it: figures out, counts and
labels in.  It adds no component and no seat — it rides the process
265 already registered — and it persists nothing: the per-campaign row
docs §16 line 909 lists among the research metrics is the ops member's
(feature 344's), which reads this pair.

**The deployed false discovery rate is the member's twelfth law and its
second state-bound component (feature 267).**  *"System persists
FDR_deploy per campaign, computed by reweighting sensitivity and
specificity to a deployment base rate of 0.9"* — prd §4.1.3's own
arithmetic (line 147): ``FDR_deploy = π₀(1 − specificity) /
[π₀(1 − specificity) + (1 − π₀)·sensitivity]`` at π₀ ≈ 0.9, the
projection of feature 266's pair onto the population the policy deploys
into — *"roughly 90-95%"* zero-edge, §4.1.3 line 141, against the ~0.25
the campaign plants at — and the figure the PRD makes the system's
primary metric (§11 line 536, target *"< 25% at π₀ = 0.9"*) and docs
§16's first research metric (line 909, *"per campaign: FDR_deploy at
π₀ = 0.9"*).  It lives in :mod:`scoring._fdr` as
:func:`~scoring.fdr_deploy` (the free verb — pure, deterministic, no
store), :data:`~scoring.DEPLOYMENT_BASE_RATE` (π₀, spelled once: a
constant, not a parameter, because a caller able to pick the base rate
could pick the figure the target is judged on) and
:class:`~scoring.FdrDeployStore` (the per-campaign rows, in the
relational store ``DATABASE_URL`` names, keyed by the campaign id and
refreshed-not-appended on a re-run with the first ``computed_at`` kept),
with its own refusal :class:`~scoring.FdrDeployError`.  The pair is
**handed over, never derived** — the barrier the β₂ term states for the
rate and 266 for its population, held here at the store: nothing in the
law holds a sidecar key or reads a label; the campaign's close-out asks
266's verb on the process for the pair and hands it here.  The one
corner refused is the pair 266 answers for *a campaign that committed
to nothing* (sensitivity ``0.0``, specificity ``1.0``), whose projection
is ``0/0`` at every base rate: a fraction of declarations is undefined
for a campaign that made none, and unknown is not zero.  Unlike the
eleven laws before it this one owns state — one row per campaign — so
it takes the component the objective never needed:
:data:`~scoring.FDR_COMPONENT_NAME` (``scoring-fdr-deploy``), composing
to the store or ``None`` (no ``DATABASE_URL`` named), reached from the
app package through the sibling seat :mod:`app.modules.scoring.fdr`.
It charges nothing — no β-term reads a base-rate projection, for the
reason 258's docstring states: a term over a projection would steer the
loop on what the policy *would* do rather than the error it made — and
it renders no verdict and no dashboard: M3's *"`FDR_deploy` improves"*
is a reader's comparison across the rows
:meth:`~scoring.FdrDeployStore.history` answers, and feature 268's
rejection (*"the raw in-campaign rate must never be the figure on the
dashboard"*) stands over the figure this store persists.

**What persists and what does not, closed out.**  The ``replay_score``
row is the replay plugin's (feature 255); the research-metrics row that
carries 266's pair is the ops member's (feature 344); the eleven free
laws persist nothing and never will — that is the law that keeps the
arithmetic pure.  The category's two state-bound features have each
landed their own component beside :data:`COMPONENT_NAME` — 265's scorer
process, 267's FDR store — the growth pattern ``app.modules.bootstrap``
took for its pool: another component name, another sibling seat, this
module's surface otherwise untouched.
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
from ._calibration import CalibrationFigures
from ._deflation import BETA_THREE_DEFAULT, deflation_penalty
from ._divergence import BETA_FOUR_DEFAULT, IC_BOUND, divergence_penalty
from ._fdr import (
    DATABASE_URL_ENV,
    DEPLOYMENT_BASE_RATE,
    FDR_COMPONENT_NAME,
    FDR_DEPLOY_TABLE,
    FdrDeployStore,
    fdr_deploy,
)
from ._nullpicks import BETA_TWO_DEFAULT, RATE_BOUND, null_pick_penalty
from ._objective import IR_DATES_MINIMUM, WorldScore, world_objective
from ._orthogonality import BETA_SIX_DEFAULT, orthogonality_bonus
from ._regime_index import PLAIN_MEAN_CODE, regime_aggregate, regime_strata
from ._scorer import NullPickScorer
from ._switches import BETA_FIVE_DEFAULT, switch_penalty
from ._trials import BETA_ONE_DEFAULT, trials_penalty
from .errors import (
    AggregationError,
    CalibrationFiguresError,
    DeflationPenaltyError,
    DivergencePenaltyError,
    ErrorAccountingError,
    FdrDeployError,
    NullPickPenaltyError,
    NullPickRateError,
    OrthogonalityError,
    RegimeIndexError,
    ScoringError,
    SwitchPenaltyError,
    TrialsPenaltyError,
    WorldObjectiveError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; the annotation is lazy
    from collections.abc import Callable

__all__ = [
    "BETA_FIVE_DEFAULT",
    "BETA_FOUR_DEFAULT",
    "BETA_ONE_DEFAULT",
    "BETA_SIX_DEFAULT",
    "BETA_THREE_DEFAULT",
    "BETA_TWO_DEFAULT",
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "DEPLOYMENT_BASE_RATE",
    "FDR_COMPONENT_NAME",
    "FDR_DEPLOY_TABLE",
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
    "CalibrationFigures",
    "CalibrationFiguresError",
    "DeflationPenaltyError",
    "DivergencePenaltyError",
    "ErrorAccounting",
    "ErrorAccountingError",
    "FdrDeployError",
    "FdrDeployStore",
    "NullPickPenaltyError",
    "NullPickRateError",
    "NullPickScorer",
    "OrthogonalityError",
    "RegimeIndexError",
    "ScoringError",
    "SwitchPenaltyError",
    "TrialsPenaltyError",
    "WorldObjectiveError",
    "WorldScore",
    "account_errors",
    "aggregate_objective",
    "deflation_penalty",
    "divergence_penalty",
    "fdr_deploy",
    "null_pick_penalty",
    "orthogonality_bonus",
    "regime_aggregate",
    "regime_strata",
    "switch_penalty",
    "trials_penalty",
    "world_objective",
]

__version__ = "0.1.0"

#: The component name this member registers under — the plugin name the
#: spec's features carry (``plugin="scoring"``), so the component key, this
#: member's seat (:mod:`app.modules.scoring`) and the spec cannot drift
#: apart.  The features of this category that own their own deployment
#: state (265's scorer process and 267's FDR store, below) register their
#: own names beside this one rather than widening this one, the way
#: ``bootstrap-pool`` sits beside ``bootstrap``.
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


# The component name the FDR_deploy store registers under — feature
# 267's own, beside :data:`COMPONENT_NAME` and
# :data:`SCORER_COMPONENT_NAME` the way ``bootstrap-pool`` sits beside
# ``bootstrap``.  Spelled once, in the law module and imported above
# (:data:`scoring._fdr.FDR_COMPONENT_NAME`) rather than restated here,
# so the member's surface and its law cannot drift apart the way two
# literals could — and spelled a second time, independently, in the
# sibling seat (:data:`app.modules.scoring.fdr.COMPONENT_NAME`, for a
# caller reaching through the app package), which the member's suite
# asserts agrees.  Prefixed with the member's own name because a
# composed application's ``order`` is name-sorted and the store must
# sort beside — never inside — the member's other components.
@register(FDR_COMPONENT_NAME)
def build_fdr_deploy_store() -> FdrDeployStore | None:
    """Component builder: the FDR_deploy store this environment composes
    (feature 267).

    Takes no arguments — the factory's protocol — and contributes the
    :class:`~scoring.FdrDeployStore` the deployment's ``DATABASE_URL``
    names, by delegating the whole question to the store's own
    resolution (:meth:`FdrDeployStore.resolve`: an absent, empty or
    whitespace-only value is unset).

    Answers ``None`` — contributing no store, never failing composition
    — where no ``DATABASE_URL`` is configured: a deployment that names
    no relational store has no per-campaign FDR_deploy rows to hold, and
    the "degrade, don't break" stance every store-bound builder here
    takes is the only honest answer.  The consequence is the one
    :meth:`bootstrap.BootstrapPool.resolve`-shaped builders all state:
    *no store is configured* and *the store is broken* are different
    facts, and only the second may ever be quiet.  A caller that reaches
    the app package for the store and finds ``None`` must refuse to
    proceed rather than persist nowhere — the figure is prd §11's
    primary target, read across campaigns, and a trend with a hole in it
    where a campaign's row should be is exactly the quietly-defaulted
    number this feature exists to rule out.

    Composing an application never opens the database: construction
    holds the URL and the schema is created on the first connect, so
    asking is always safe — the same promise the objective's builder
    above makes for the arithmetic and the scorer's makes for its
    sidecar.  A URL the store cannot speak is refused at first use, not
    at composition, because the repair (a misrouted ``DATABASE_URL``)
    is an operator's fact, not a composition fact.
    """
    return FdrDeployStore.resolve()
