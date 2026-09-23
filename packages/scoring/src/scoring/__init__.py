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
penalties (features 257 through 261) will find the seam already shaped
when they land their own terms through it.

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
objective's own docstring promised the six β-terms would.

**No persistence here, by the same law that keeps the arithmetic pure.**
The ``replay_score`` row is the replay plugin's (feature 255); this
member answers the value it is written from, exactly as migration 0109
shapes it.  The features of this category that *do* own state — feature
265's scorer process holding the sidecar key, feature 267's per-campaign
``FDR_deploy`` — will take their own components beside this one when
they land, the growth pattern ``app.modules.bootstrap`` took for its
pool: a second component name, a sibling seat, this module's surface
untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.module_loader import register

from ._aggregate import (
    LAMBDA_CEILING,
    LAMBDA_DEFAULT,
    LAMBDA_FLOOR,
    AggregatedObjective,
    aggregate_objective,
)
from ._objective import IR_DATES_MINIMUM, WorldScore, world_objective
from ._orthogonality import BETA_SIX_DEFAULT, orthogonality_bonus
from ._regime_index import PLAIN_MEAN_CODE, regime_aggregate, regime_strata
from ._switches import BETA_FIVE_DEFAULT, switch_penalty
from .errors import (
    AggregationError,
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
    "BETA_SIX_DEFAULT",
    "COMPONENT_NAME",
    "IR_DATES_MINIMUM",
    "LAMBDA_CEILING",
    "LAMBDA_DEFAULT",
    "LAMBDA_FLOOR",
    "PLAIN_MEAN_CODE",
    "AggregatedObjective",
    "AggregationError",
    "OrthogonalityError",
    "RegimeIndexError",
    "ScoringError",
    "SwitchPenaltyError",
    "WorldObjectiveError",
    "WorldScore",
    "aggregate_objective",
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
#: apart.  A later feature of this category that owns its own deployment
#: state (265's scorer process, 267's FDR store) registers its own name
#: beside this one rather than widening this one, the way
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
