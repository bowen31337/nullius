"""The grid plan derived from prior campaign manifests — feature 235.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 235: *System returns
a grid plan carrying a branch count plus a refine count derived from prior
manifests.*  PRD §426 spells the value the system returns:
``plan_grid(context) -> GridPlan(branch_count=W, refine_count=R)``, *"run
**before** a campaign, using only prior-campaign manifests"*, and PRD §428 says
which half of the derivation is which: *"as originally specified [it] chooses
width versus depth from prior manifests but has no notion of difficulty
targeting, so it cannot tell an exhausted theme from an unexplored one"* — the
width-versus-depth derivation is this feature, and the difficulty targeting
PRD §428 then borrows from self-improving-model training is features 236 and
237.  docs/nullius-tech-architecture.md §605–§606 fixes the boundary the
derivation runs inside — ``plan_grid`` *"Runs BEFORE a campaign. May read only
prior campaign manifests."* — and §5's *one campaign = one discovery tree* is
why the decision has to be made from history in the first place: a plan is what
a campaign is *opened with*, so §4.1.1's fraction is fixed at planning time
rather than learned from the run, and the plan that fixes it cannot be a
description of the tree it is about to plant.

**This is the system's own planner.**  Feature 233 owns *what a planning hook
may read* and runs the hook a caller hands it; :class:`~discovery.planner.
PlanContext` is the aperture it hands over, holding the prior manifests and the
two ceilings and nothing else.  This module owns the *default* planner that runs
inside that aperture, and it is deliberately written as a hook feature 233's seam
admits unchanged: :func:`derive_grid_plan` takes the context alone and reads only
:attr:`~discovery.planner.PlanContext.prior_campaigns`,
``max_branches`` and ``max_refinements``.  So
``plan_grid(derive_grid_plan, prior_campaigns=history)`` is a complete planning
step whose boundary holds by construction rather than by a check — the record
feature 233 keeps stays empty, because there is no name outside the three this
derivation ever asks for.  It is not *the* planner, and must not be read as one:
§5 gives the width, the depth and the themes to the policy, and 229's law
requires every policy to author its own ``plan_grid``.  This is what the *system*
plans with when it is asked to plan from the record alone — the seeding plan a
fresh deployment opens, and the baseline a policy's own plan is read against.

**The derivation is a rebalance, and the rebalance is the anti-convergence
clause.**  PRD §407 states the failure this exists to avoid: *"Without [the
explicit anti-convergence clause], a discovery tree collapses into 400 parameter
tweaks of one indicator."*  A converged tree has a signature, and it is an
*aspect* — few branches, each refined very deep.  So the history's own aspect is
exactly the shape the next campaign must not reproduce, and the derivation spends
what the history actually walked on the grid furthest from that shape: the
measured refinement budget, redistributed evenly between breadth and depth, so
the plan refines ``side`` branches ``side`` times each for ``side² ≈ B`` the
refinements the history spent.  Evenness is the geometric midpoint between the
observed aspect and its inverse — the one split that neither reproduces the
history's convergence nor overshoots into the mirror-image failure, a grid that is
all breadth with nothing worth refining.  Note which quantity is conserved and
which is not: the *budget* is the history's, because a depth budget is what the
plan is being derived from and what §11.1's ``R`` measures, while the *width* is
not carried over at all — it is the square root of that budget, because the width
is how the budget gets distributed rather than a second thing to conserve.
Features 236 and 237 then skew this base grid per branch, by difficulty and by
saturation; a base that already favoured an axis would make their allocation a
correction of this module's opinion rather than of the evidence.

**The budget is measured, never declared.**  The refinement count a plan is built
from is read off feature 242's completed manifests, which are a *census* of the
``node`` rows a campaign's tree actually holds — :mod:`discovery.manifest` states
the discipline: *"the summary reflects the tree that was walked, not a claim
about it"*, and feature 235 reads *"numbers that were measured rather than
declared"*.  So a plan cannot be talked into a shape by a loop's own tally: the
only input is what the trees did.

**Empty history is the path §606 names, and it is planned rather than refused.**
With no prior campaign at all there is no evidence to derive from and still a
plan to return — *"Must return a non-None plan on every path, including empty
history"* — so the plan is the architecture's own reference campaign shape rather
than a grid plus a refusal.  docs §14.2 costs a campaign at ``W=16, R=30`` (~500
nodes): that pair is the reference the cost model is stated against, and it is
used here as a *named constant citing its source*, not as a number this module
invented.  Note the deliberate asymmetry with a history that exists but refined
nothing: that is **not** empty history and is not given the reference depth — the
record tells us how wide the deployment's campaigns have actually opened and
nothing at all about depth, so the plan keeps the measured width and spends no
depth (``refine_count=0``, the explore-only grid 229's plan law admits) rather
than inventing a depth the evidence does not support.

**The two ceilings bound the decision; they are not the decision.**  The
policy-runtime member's ``GridPlanningContext`` says so in as many words — the
ceilings are *"carried so a plan can be bounded against the runtime; the bound is
checked by the caller (features 235/237), not here"* — and this is that check,
made at the one place a plan is authored.  A configured ceiling caps what the
derivation proposes and never raises it: a plan that always equalled the ceiling
would be a configuration read wearing a derivation's name, and the reason the
bound exists (a runtime cannot run more slots than it has, nor walk deeper than
its budget) only ever argues downward.  ``0`` means *no ceiling configured*,
which is the reading feature 233's context states for the same two fields — so a
deployment that names none gets the derivation unclipped, and a refusal here
would be this module demanding a number the deployment never promised.

**The plan carries two counts, and the third read of 229's plan value is
deliberately absent.**  PRD §426 names the two counts, and §11.1 makes the themes
a *hard constraint* at planning time — *"A single-theme campaign shows the policy
a constant, it learns a family-specific rule, and it fails on transfer"* — so it
is worth saying why this derivation does not fill them in: a manifest carries the
*number* of distinct theme roots a tree spanned
(:data:`~discovery.manifest.THEME_ROOTS_COLUMN`) and never *which* ones, so a
derivation that named themes would be inventing them, and the themes a campaign
opens are the deployment's configured legal space (feature 241's set) intersected
with what the policy chose.  Feature 234 judges the diversity of the plan a
policy authored; this module returns the grid that plan has to fit into, and
leaves the themes to the two features that own them.

**The ask's vocabulary is restated rather than imported, and that is the
member's own rule.**  Feature 233's :func:`~discovery.planner._validated_history`
and :func:`~discovery.planner._validated_ceiling` judge exactly the two reads
this function judges, and they are private to their module —
:mod:`discovery.planner` says why the same split exists one level up: *"restated
here because that helper is private to its module and no member reaches across
one"*.  The refusals here are this module's own because they are about a
different act (:func:`derive_grid_plan` *plans* from the history, where 233
*judges a hook* for reaching past it), and two refusals for two acts is the
member's split-by-repair discipline rather than duplication —
``packages/discovery/tests/test_grid_plan.py`` pins that the two spellings accept
and refuse the same inputs, which is what keeps the restatement honest without an
import.

**No component, no I/O, and no new error class.**  Every refusal here is a fact
about the request — a context that does not carry the three reads, a history that
is not a batch of manifests, a ceiling that is not a count, a plan count below
its floor — so all of them are
:class:`~discovery.errors.CampaignPlanningError`, the member's existing *"the
request cannot be planned"* class.  A new class would be a second vocabulary for
one sentence, which is the drift this member's ``tests/test_cross_member.py``
exists to prevent, and no corrected re-request is the wrong repair for any of
these.  It adds no ``@register`` for feature 241's reason (*a builder that always
answers the same value is a function wearing a component's name*) with feature
233's behind it: the derivation closes over no deployment state at all — no
``DATABASE_URL``, no store, no table, no file.  Stdlib only, and import-cheap:
:mod:`math` (``isqrt``), :mod:`dataclasses` and this member's own values and
errors, with no third-party import at module scope, so the factory's scan (which
imports this package to fire its ``@register``) pays nothing for it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .errors import CampaignPlanningError
from .manifest import CampaignManifest

__all__ = [
    "REFERENCE_BRANCH_COUNT",
    "REFERENCE_REFINE_COUNT",
    "GridPlan",
    "derive_grid_plan",
]

#: The width of the reference campaign shape docs §14.2 costs the system against
#: — ``W=16``, beside ``R=30``, for *"~500 nodes at ~1.2k tokens"*.  It is the
#: *only* number this module states rather than derives, and it is stated as a
#: reference rather than a policy: it answers the one question history cannot
#: (what grid does a deployment with no completed campaign plan?) from the
#: architecture's own costing example, so the empty-history path §606 requires
#: returns a plan the docs already recognise instead of a default this module
#: invented.  A deployment that wants a different empty-history grid states its
#: ceilings, and :func:`_bounded_grid` clips this pair to them.
REFERENCE_BRANCH_COUNT = 16

#: The depth of the reference campaign shape, docs §14.2's ``R=30`` refinements
#: per branch — see :data:`REFERENCE_BRANCH_COUNT` for why the pair is a citation
#: rather than a policy.  Note the unit: this is refinements **per branch**
#: (§11.1's ``R``), while a manifest's own ``refine_count`` is the whole tree's —
#: :func:`_rebalanced_grid` converts between the two, and says so.
REFERENCE_REFINE_COUNT = 30

#: The three names a planning context exposes, restated from the same three
#: feature 233 reads — listed once so the refusal in :func:`_planning_reads` and
#: the module docstring cannot disagree about which reads this derivation makes.
#: A hook's author written against the policy-runtime member's
#: ``GridPlanningContext`` carries the same three under the same names, which is
#: what lets this function plan under either spelling.
_PLANNING_READS = ("prior_campaigns", "max_branches", "max_refinements")

#: What a missing read is bound to while the three are collected, so that
#: :func:`_planning_reads` can name **every** read the context does not carry
#: rather than the first one — the "name every offender at once" discipline
#: :meth:`discovery.themes.ThemeSet.assign_all` and
#: :func:`discovery.manifest.admit_completed_campaigns` both state.  A private
#: sentinel rather than ``None``, because ``None`` is a value a real context field
#: could hold and a sentinel cannot be confused with one.
_ABSENT = object()


@dataclass(frozen=True)
class GridPlan:
    """The grid a campaign is opened with — a branch count and a refine count.

    PRD §426's ``GridPlan(branch_count=W, refine_count=R)``: the width a campaign
    is planted at and the depth each of its branches is refined to, and *only*
    those two, because those are the two counts a census of prior trees can speak
    to (the module docstring says why the themes are absent rather than
    unfilled).  ``refine_count`` is refinements **per branch** — the unit §11.1's
    ``R`` is stated in and the unit the policy-runtime member's
    ``max_refinements`` ceiling bounds — not the whole tree's refinement count,
    which is what a :class:`~discovery.manifest.CampaignManifest` carries and what
    :func:`_rebalanced_grid` divides before it gets here.

    Frozen, because a plan is a *decision* a campaign is opened with: a caller
    that could edit the grid afterwards would hold a different campaign than the
    one the history justified, the argument
    :class:`~discovery.manifest.CampaignManifest` makes for its own counts.  Two
    plans carrying one pair of counts are one plan — equality and hashing are the
    counts, both of which the frozen dataclass derives — so a caller can compare
    the grid it planned with the grid a record was walked at, and can key a
    campaign's provenance by the grid it was opened with.

    Validated in :meth:`__post_init__`, through ``object.__setattr__`` so a
    ``dataclasses.replace`` or an unpickle passes back through the check: both
    counts are genuine integers (a ``bool`` is not a count — ``True`` would read
    as a grid of one branch, the SQLite affinity trap this workspace guards
    elsewhere), the width is at least one because *"a plan with no branches opens
    no campaign"*, and the depth is non-negative because a negative depth budget
    is one no walk could reach.  Those are the counts law feature 229's own
    ``GridPlan`` states, restated in this member's vocabulary against this
    member's error class — two members, one law, no import between them, the
    restatement ``packages/discovery/tests/test_grid_plan.py`` keeps honest.
    """

    #: The number of parallel branches to open (``W``) — one per root the campaign
    #: plants.  At least one: a grid with no branch opens nothing.
    branch_count: int
    #: The refinements per branch (``R``) — the depth each branch is walked to.
    #: Non-negative, so ``0`` is the explore-only grid PRD §426's spelling admits
    #: and 229's plan law admits with it.
    refine_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "branch_count",
            _validated_plan_count(self.branch_count, "branch_count", minimum=1),
        )
        object.__setattr__(
            self,
            "refine_count",
            _validated_plan_count(self.refine_count, "refine_count", minimum=0),
        )


def derive_grid_plan(context: Any) -> GridPlan:
    """Derive the next campaign's grid from the campaigns already walked.

    The feature's verb, and the planning step the orchestrator runs before
    feature 232's campaign record is created: handed the planning context — the
    prior manifests and the two ceilings, and nothing else — it returns the
    :class:`GridPlan` the evidence supports.  It takes the context **alone**,
    which is the one call shape §605 gives a planning hook, so
    ``plan_grid(derive_grid_plan, prior_campaigns=history)`` is a complete planning
    step: feature 233's seam admits this function (one positional parameter binds)
    and this function cannot reach the current episode (the context carries none),
    so the boundary holds by construction and the inspection record feature 233
    keeps stays empty.

    The steps, in order, each refusal in the member's malformed-ask vocabulary:

    1. **the context carries the three reads** — ``prior_campaigns``,
       ``max_branches`` and ``max_refinements``, the surface feature 233's context
       fixes a hook's author against, and **every** missing one is named.  Refused
       with :class:`~discovery.errors.CampaignPlanningError`: an
       :class:`AttributeError` escaping here would be this seam presenting a
       malformed request as a bug in the derivation.
    2. **the history is a batch of this member's manifests** — a bare
       :class:`~discovery.manifest.CampaignManifest` is accepted and wrapped (a
       caller planning from one campaign's history is a legitimate caller), a
       ``str``/``bytes`` is refused rather than iterated into characters (the
       guard :class:`~discovery.themes.ThemeSet` states for a set of themes, and
       here it matters because a string read as a batch would hand the derivation
       a history of single characters and the refusal would arrive as a mangled
       manifest), and an entry that is not a manifest is refused with its
       position, because a value that is not one tells the derivation nothing it
       is allowed to know.
    3. **the two ceilings are counts** — a ``bool`` or a non-``int`` or a negative
       bounds nothing.  ``0`` is **not** a refusal: it is the *unset* reading (no
       ceiling configured), the reading feature 233's context and the
       policy-runtime member's both state for the same two fields.
    4. **the grid is derived** by the rebalance :func:`_rebalanced_grid` states —
       an empty history takes the architecture's reference grid; a history that
       refined nothing keeps its measured width and spends no depth; any other
       history spends its measured refinement budget on the grid furthest from its
       own aspect, so a campaign that went narrow and deep comes back wide and
       shallow.
    5. **the ceilings clip the result** (:func:`_bounded_grid`), never raise it,
       and the clipped grid is returned as a :class:`GridPlan` — constructed, so
       the counts law is applied at the value, once, and a grid that could not open
       a campaign cannot leave here even if a later edit to the arithmetic tried to
       produce one.

    It reads no store and opens no file: the prior manifests reach it the way the
    spec allows — through feature 242's
    :meth:`~discovery.manifest.CampaignManifests.completed`, the one authority on
    which campaigns are complete, read by the caller that holds the store and
    handed in here either directly or as feature 233's
    :class:`~discovery.planner.PlanContext`.
    """
    history, max_branches, max_refinements = _planning_reads(context)
    width, depth = _rebalanced_grid(history)
    return _bounded_grid(width, depth, max_branches, max_refinements)


def _planning_reads(context: Any) -> tuple[tuple[CampaignManifest, ...], int, int]:
    """Take the three reads off a planning context, validating each.

    The seam's adapter, so the derivation is handed *values* rather than
    spellings — the split feature 233's own seam states for its arguments.  The
    three are read **by name rather than by type**, so a hook's author can hand
    this function the policy-runtime member's ``GridPlanningContext`` and have it
    work; the *entries* of the history are then required to be this member's
    manifests, because feature 242 is the authority on what a prior manifest is
    and a census of counts is the only thing a plan may be derived from.

    The missing reads are collected before any of them is refused, so a context
    carrying none of the three is told about all three rather than meeting them
    one resubmission at a time.  ``getattr`` with a sentinel default is what makes
    that a single lookup per name — and it is safe over feature 233's
    :class:`~discovery.planner.PlanContext` precisely because the three permitted
    reads are properties that resolve through normal attribute lookup, so none of
    them ever reaches that class's recording ``__getattr__`` and the sentinel can
    only be returned by an object that genuinely lacks the name.
    """
    reads = {name: getattr(context, name, _ABSENT) for name in _PLANNING_READS}
    missing = [name for name, value in reads.items() if value is _ABSENT]
    if missing:
        listed = ", ".join(repr(name) for name in missing)
        raise CampaignPlanningError(
            f"a grid plan is derived from a planning context, and "
            f"{type(context).__name__} carries no {listed}; feature 235 derives "
            "the next campaign's branch and refine counts from the prior campaign "
            "manifests, so a request that does not carry them has no record to "
            "plan from (feature 233's PlanContext carries prior_campaigns, "
            "max_branches and max_refinements, which is the whole of what planning "
            "may read)"
        )
    return (
        _validated_history(reads["prior_campaigns"]),
        _validated_ceiling(reads["max_branches"], "max_branches"),
        _validated_ceiling(reads["max_refinements"], "max_refinements"),
    )


def _rebalanced_grid(history: tuple[CampaignManifest, ...]) -> tuple[int, int]:
    """The grid the history justifies, before the ceilings are applied.

    Three cases, and each is a different amount of *evidence* rather than a
    different rule:

    * **no history** — no evidence at all, so the grid is the architecture's
      reference shape (:data:`REFERENCE_BRANCH_COUNT` /
      :data:`REFERENCE_REFINE_COUNT`, docs §14.2).
    * **a history that refined nothing** — evidence about width alone, so the
      width is the mean branch count this record measured and the depth is zero
      rather than the reference.  The record says how wide this deployment's
      campaigns actually open and says nothing whatever about how deep they go;
      spending a depth no tree ever walked would be this module writing a campaign
      nobody planned.
    * **any other history** — both counts are present, and the grid is the
      rebalance: with ``B`` the mean refinement count of a prior campaign's tree
      (the budget the history actually spent, measured by feature 242's census
      rather than declared by a loop) and ``side = ceil(sqrt(B))``, the plan opens
      ``side`` branches and refines each of them ``side`` times.

    Two properties are the whole argument for the third case.  **The refinement
    budget is conserved**: the plan spends ``side²`` refinements against the
    history's measured ``B``, so the next campaign is about the depth budget this
    deployment has demonstrated it can walk rather than a budget this module
    chose — the width follows from that budget rather than being carried over with
    it, because ``side`` is how the budget is *distributed* between breadth and
    depth.  **The aspect is not conserved**: the history's refinements-per-branch
    ratio is replaced by one, which is the geometric midpoint between that ratio
    and its inverse — the split furthest from the convergence signature PRD §407
    names (few branches, each refined into the 400th parameter tweak of one
    indicator) that still does not overshoot into the mirror-image grid, all
    breadth and nothing worth refining.

    All three means are taken in exact integer arithmetic —
    ``-(-total // count)`` is ``ceil(total / count)`` — and the square root is
    :func:`math.isqrt`, with ``ceil(sqrt(B))`` spelled ``isqrt(B - 1) + 1`` for
    ``B >= 1``.  No float is constructed anywhere in the derivation, so no plan
    can differ between two machines by a rounding mode: a census is a count, and
    the plan derived from it is a count as well.
    """
    if not history:
        return REFERENCE_BRANCH_COUNT, REFERENCE_REFINE_COUNT
    campaigns = len(history)
    branch_total = sum(entry.branch_count for entry in history)
    refine_total = sum(entry.refine_count for entry in history)
    mean_branches = _ceil_div(branch_total, campaigns)
    mean_refines = _ceil_div(refine_total, campaigns)
    if mean_refines <= 0:
        # Evidence about width and none about depth.  ``max(1, ...)`` because a
        # tree whose every node names a parent has no root to open a branch at,
        # and a grid of no branch is no grid — the floor 229's plan law states.
        return max(1, mean_branches), 0
    side = math.isqrt(mean_refines - 1) + 1
    return side, side


def _bounded_grid(
    width: int, depth: int, max_branches: int, max_refinements: int
) -> GridPlan:
    """The derived grid, capped by the runtime's configured ceilings.

    A ceiling of ``0`` is *unset* — the reading feature 233's context and the
    policy-runtime member's both state — so it caps nothing; a configured ceiling
    caps the derivation and never raises it, because the reason the bound exists is
    that a runtime cannot run more slots than it has or walk deeper than its
    budget, and neither of those argues for a *larger* campaign.  The result is
    built through :class:`GridPlan`'s own constructor, so the counts law is applied
    once, at the value, rather than re-stated here.

    One consequence worth stating rather than hiding: a ceiling may cap the width
    below the three distinct theme roots PRD §9.3 and feature 234 require of a
    campaign.  That is not this derivation's refusal to make — a grid *too narrow
    for its deployment* is a fact about the deployment's configuration and about
    the themes the policy declared, and feature 234 refuses it at planning time
    naming the themes, which is the repair the caller needs.  Clipping here instead
    would be this module silently authoring a campaign of one theme.
    """
    if max_branches:
        width = min(width, max_branches)
    if max_refinements:
        depth = min(depth, max_refinements)
    return GridPlan(branch_count=width, refine_count=depth)


def _ceil_div(total: int, count: int) -> int:
    """``ceil(total / count)`` for non-negative integers, without a float.

    The two means the derivation takes are means of *counts*, so they are rounded
    up rather than to nearest: a plan is a whole number of branches and a whole
    number of refinements each, and rounding down would make the rounding — not the
    evidence — the thing that reduced the campaign.  Integer arithmetic rather
    than ``math.ceil(total / count)`` so the result cannot depend on a floating
    point representation, which for a mean of counts is a needless way to make a
    plan machine-dependent.
    """
    return -(-total // count)


def _validated_history(prior_campaigns: Any) -> tuple[CampaignManifest, ...]:
    """Materialise the prior manifests, refusing anything that is not one.

    Restated from feature 233's own adapter rather than imported: it is private to
    its module, and the member's rule — stated in :mod:`discovery.planner` for the
    same helper one level up — is that a private helper is restated where it is
    needed rather than reached across for.  The refusals here belong to this
    module's act (*plan from this history*) rather than to 233's (*judge a hook
    that reached past the history*), and the two spellings agree on every input,
    which ``packages/discovery/tests/test_grid_plan.py`` pins.

    A bare :class:`~discovery.manifest.CampaignManifest` is accepted and wrapped: a
    caller planning with exactly one prior campaign is a legitimate caller, and
    refusing it for not being a batch would be the seam making that caller's
    problem worse.  A string is **not** iterated into characters — the guard
    :class:`~discovery.themes.ThemeSet` states for a set of themes — because a
    string read as a batch would hand the derivation a history of single
    characters and the refusal would arrive as a mangled manifest rather than as
    *"that is not a batch"*.
    """
    if isinstance(prior_campaigns, CampaignManifest):
        return (prior_campaigns,)
    if isinstance(prior_campaigns, (str, bytes)) or not isinstance(
        prior_campaigns, Iterable
    ):
        raise CampaignPlanningError(
            f"planning takes a batch of prior campaign manifests, got "
            f"{type(prior_campaigns).__name__}; feature 235 derives the next "
            "campaign's grid from the campaigns already walked, and a value that "
            "is not a sequence of manifests is no history to derive one from — "
            "read them with CampaignManifests.completed()"
        )
    history = tuple(prior_campaigns)
    for position, manifest in enumerate(history):
        if not isinstance(manifest, CampaignManifest):
            raise CampaignPlanningError(
                f"the prior-campaign batch's entry at position {position} is "
                f"{type(manifest).__name__}, not a CampaignManifest; the history a "
                "grid plan is derived from is feature 242's completed-campaign "
                "manifests — the census of what each campaign's tree held — and a "
                "value that is not one is no census to plan from (feature 235)"
            )
    return history


def _validated_ceiling(value: Any, field_name: str) -> int:
    """Refuse a configured ceiling that is not a genuine non-negative integer.

    Restated from feature 233's adapter, on the same terms and for the same
    reason as :func:`_validated_history`.  The same check feature 232 applies to
    ``workspace_count`` and feature 242 to its census counts, restated for the two
    read-only bounds a planning context carries: a ``bool`` is not a count (the
    SQLite affinity trap this workspace guards elsewhere — ``True`` would read as a
    ceiling of one), a non-``int`` is not a count, and a negative ceiling is not
    one a runtime could hold.  Named with its field, so a refusal says which bound
    and why — and ``0`` is admitted, because it means *unset* rather than *zero*.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CampaignPlanningError(
            f"a planning context's {field_name} must be a genuine integer, got "
            f"{value!r} ({type(value).__name__}); the ceilings bound the grid a "
            "plan may open, and a value that is not a count bounds nothing "
            "(feature 235)"
        )
    if value < 0:
        raise CampaignPlanningError(
            f"a planning context's {field_name} must be non-negative, got {value!r}; "
            "a negative ceiling admits no branch, so a context carrying one bounds "
            "nothing (feature 235)"
        )
    return value


def _validated_plan_count(value: Any, field_name: str, *, minimum: int) -> int:
    """Refuse a grid count that is not a genuine integer at least ``minimum``.

    The same check feature 232 applies to ``workspace_count``, feature 242 to its
    census counts and feature 233 to the two ceilings, restated for the plan's own
    two counts: a ``bool`` is not a count, a non-``int`` is not a count, and a count
    below the floor is not one a grid could hold.  The floors are the ones feature
    229's plan law states — a grid opens at least one branch, and a depth budget is
    non-negative — so a plan this member derives is a plan that law would have
    admitted, which is what makes the two spellings one law rather than two
    opinions.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CampaignPlanningError(
            f"a grid plan's {field_name} must be a genuine integer, got "
            f"{value!r} ({type(value).__name__}); a grid plan carries the number of "
            "branches a campaign opens and the refinements per branch, and a value "
            "that is not a count plans no campaign (feature 235)"
        )
    if value < minimum:
        raise CampaignPlanningError(
            f"a grid plan's {field_name} must be at least {minimum}, got {value!r}; "
            "a plan that opens no branch opens no campaign, and a negative depth "
            "budget is one no walk could reach (feature 235, PRD §426)"
        )
    return value
