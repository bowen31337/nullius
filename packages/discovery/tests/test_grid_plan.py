"""Feature 235: the grid plan derived from prior campaign manifests.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 235: *System returns
a grid plan carrying a branch count plus a refine count derived from prior
manifests.*  PRD §426 spells the value — ``plan_grid(context) ->
GridPlan(branch_count=W, refine_count=R)``, *"run **before** a campaign, using
only prior-campaign manifests"* — and PRD §428 fixes which half of the
derivation this feature owns (*"chooses width versus depth from prior
manifests"*, before 236/237 add difficulty targeting).

Five things are asserted here, in the order the feature's own sentence implies
them: **the value** (two counts, a grid, and no third field the evidence cannot
speak to), **the derivation** (the history's measured refinement budget, spent
on the grid furthest from the history's own aspect), **the evidence's edges**
(empty history takes the architecture's reference grid; a history that refined
nothing keeps its measured width and spends no depth), **the ceilings** (they
cap the derivation and never raise it), and **the ask** (the malformed requests,
which are this member's malformed-ask class).

**The refusals are pinned by class, not by prose.**  Like feature 233's suite and
feature 241's and 242's, this file asserts
:class:`~discovery.errors.CampaignPlanningError` rather than substring-matching a
sentence, so a message can be improved without breaking a test that was only ever
about *which* refusal occurred.  Feature 235 adds **no** error class of its own —
every refusal here is a fact about the request, so it wears the member's existing
malformed-ask class, and one test below is that claim stated as an assertion.

**The reference constants are transcribed, not read.**  The empty-history grid is
pinned against ``16`` and ``30`` written out here from docs §14.2 — ``W=16``,
``R=30`` — rather than against :data:`discovery.REFERENCE_BRANCH_COUNT` and
:data:`discovery.REFERENCE_REFINE_COUNT`.  A test that compared the constant with
itself would agree with itself whatever the constant said, which is precisely the
failure the literal exists to catch.

**The arithmetic is pinned as arithmetic, not as a formula.**  The rebalance tests
state the *properties* the derivation is argued from — the plan's size is about
the history's, the aspect is the history's inverted — and assert both against
numbers computed in the test from the manifests, so a rewrite that keeps the
argument and changes the spelling passes, while a rewrite that keeps the spelling
and loses the argument fails.

Feature 235 is pure, so this suite needs no fixture and no database: the prior
manifests reach the derivation the way the spec allows, through feature 242's
``CampaignManifests.completed``, read by a caller that holds the store.
"""

from __future__ import annotations

import ast
import math
import sys
import uuid as uuid_module
from dataclasses import FrozenInstanceError
from pathlib import Path

import discovery
import pytest
from discovery import (
    CampaignManifest,
    CampaignPlanningError,
    DiscoveryError,
    GridPlan,
    PlanContext,
    derive_grid_plan,
    plan_grid,
)

#: The reference campaign shape docs §14.2 costs the system against —
#: ``W=16, R=30``, *"~500 nodes at ~1.2k tokens"* — written out here rather than
#: read from the module's constants.  See the module docstring for why iterating
#: the constant would defeat the purpose.
SPEC_REFERENCE_WIDTH = 16
SPEC_REFERENCE_DEPTH = 30


def _manifest(
    branch_count: int = 2, refine_count: int = 400, **overrides: object
) -> CampaignManifest:
    """One completed campaign's manifest, shaped like feature 242's census.

    The defaults are a *converged* tree — two roots refined four hundred times
    over — because that is PRD §407's failure signature (few branches, deep
    refinement) and the case the derivation exists to rebalance away from.  A test
    that wants the other extreme passes its own counts; a test that wants the
    middle passes something in between.
    """
    fields: dict[str, object] = {
        "campaign_id": str(uuid_module.uuid4()),
        "calibration_status": "ok",
        "branch_count": branch_count,
        "refine_count": refine_count,
        "leaf_count": 1,
        "node_count": branch_count + refine_count + 1,
        "depth_max": 1,
        "theme_roots": 3,
    }
    fields.update(overrides)
    return CampaignManifest(**fields)  # type: ignore[arg-type]


def _context(*manifests: CampaignManifest, **ceilings: int) -> PlanContext:
    """A planning context over the given history — feature 233's own aperture.

    The real one, not a stand-in: 235 is written to run inside 233's context, so
    every test that is *about the derivation* drives it through the object a
    deployment's orchestrator would actually build.  The duck-typed stand-in below
    exists only for the cases 233's context would refuse at construction, which
    would be the wrong seam under test.
    """
    return PlanContext(manifests, **ceilings)  # type: ignore[arg-type]


# -- The value: a grid, and the two counts it carries --------------------------


def test_a_grid_plan_carries_the_two_counts_and_nothing_else() -> None:
    """PRD §426's value is ``(branch_count, refine_count)`` — a grid, no theme list.

    The two counts are the whole of what a census of prior trees can speak to, and
    the themes are deliberately absent rather than empty: a manifest carries the
    *number* of distinct theme roots a tree spanned and never *which* ones, so a
    derivation that filled a theme field would be inventing the themes, and §11.1
    gives them to the policy and to feature 241's configured legal set.  229's plan
    law judges the themes a policy declared; this value is the grid that plan has
    to fit into.
    """
    plan = derive_grid_plan(_context(_manifest()))
    assert isinstance(plan, GridPlan)
    assert (plan.branch_count, plan.refine_count) == (20, 20)
    assert not hasattr(plan, "theme_roots")
    assert [field for field in plan.__dataclass_fields__] == [
        "branch_count",
        "refine_count",
    ]


def test_two_plans_over_one_pair_of_counts_are_one_plan() -> None:
    """A plan is a decision, so it is frozen and compares by its counts.

    A caller has to be able to compare the grid it planned with the grid a record
    was walked at (and to key a campaign's provenance by it), which only works if
    equality is the *decision* rather than the object's identity.  Frozen for the
    reason feature 242's manifest is: a plan a caller could edit after the fact
    would be a different campaign than the one the history justified.
    """
    first, second = GridPlan(branch_count=4, refine_count=9), GridPlan(
        branch_count=4, refine_count=9
    )
    assert first == second
    assert hash(first) == hash(second)
    assert first != GridPlan(branch_count=4, refine_count=8)
    with pytest.raises(FrozenInstanceError):
        first.branch_count = 5  # type: ignore[misc]


@pytest.mark.parametrize(
    "counts",
    [
        {"branch_count": 0, "refine_count": 4},
        {"branch_count": -1, "refine_count": 4},
        {"branch_count": 4, "refine_count": -1},
    ],
)
def test_a_grid_that_could_not_open_a_campaign_is_refused(counts: dict) -> None:
    """229's counts law, restated at this member's value and error class.

    *"A plan with no branches opens no campaign"* — the planning-side mirror of
    returning nothing — and a negative depth budget is one no walk could reach.
    The two members state one law in two vocabularies with no import between them,
    and this is the pin that the restatements agree.
    """
    with pytest.raises(CampaignPlanningError):
        GridPlan(**counts)


@pytest.mark.parametrize(
    "counts",
    [
        {"branch_count": True, "refine_count": 4},
        {"branch_count": 4.0, "refine_count": 4},
        {"branch_count": 4, "refine_count": True},
        {"branch_count": 4, "refine_count": "9"},
    ],
)
def test_a_grid_count_that_is_not_a_count_is_refused(counts: dict) -> None:
    """``True`` is not a grid of one branch — the SQLite affinity trap.

    ``bool`` is an ``int`` subclass, so an unguarded check would read a ``True``
    width as a grid of one branch and a ``True`` depth as one refinement per
    branch, both silently.  The same guard feature 232 applies to
    ``workspace_count`` and feature 242 to its census counts, restated at the plan.
    """
    with pytest.raises(CampaignPlanningError):
        GridPlan(**counts)


# -- The derivation: the budget is measured, and the aspect is inverted --------


def test_the_rebalance_spends_the_measured_budget_and_inverts_the_aspect() -> None:
    """The argument, asserted as arithmetic rather than as a formula.

    PRD §407: *"Without [the anti-convergence clause], a discovery tree collapses
    into 400 parameter tweaks of one indicator."*  A converged tree is an *aspect*
    — few branches, refined very deep — so the history's own aspect is the shape
    the next campaign must not reproduce.  Two properties are asserted against
    numbers this test computes itself, so a rewrite that keeps the argument and
    changes its spelling passes:

    * **the refinement budget is conserved** — the plan spends about the ``B``
      refinements the history measured, so the next campaign is the depth budget
      this deployment demonstrated it could walk;
    * **the aspect is not conserved** — the history's refinements-per-branch ratio
      is replaced by one, the geometric midpoint between that ratio and its
      inverse.

    Note what is *not* claimed: the history's **width** is not carried over.  The
    plan's width is the square root of the budget, because the width is how the
    budget is distributed rather than a second quantity to conserve — which is
    why a history of 40 branches is rebalanced to fewer, not to at least 40.
    """
    history = _manifest(branch_count=2, refine_count=400)
    plan = derive_grid_plan(_context(history))

    # The budget: `side` branches refined `side` times each spend side² refinements,
    # against the history's measured 400.
    side = plan.branch_count
    assert plan.refine_count == side
    assert side * side == pytest.approx(history.refine_count, rel=0.05)

    # The aspect: ratio 1, against the history's 200 and its inverse 0.005.
    assert plan.refine_count / plan.branch_count == 1
    history_ratio = history.refine_count / history.branch_count
    assert history_ratio == pytest.approx(200)
    assert math.isclose(
        plan.refine_count / plan.branch_count,
        math.sqrt(history_ratio * (1 / history_ratio)),
    )


def test_a_converged_history_comes_back_wide_and_a_shallow_one_narrow() -> None:
    """The two extremes cross the middle — neither grid is the history's shape.

    A history that went narrow and deep is rebalanced *wide* (many branches,
    shallower than the history's 200-deep walk), and one that went wide and shallow
    is rebalanced *narrower* (fewer branches than the history's 40).  Both
    directions matter: the anti-convergence clause's failure mode is the first, and
    the mirror-image failure — a grid of pure breadth with nothing worth refining —
    is what the even split avoids on the way back.
    """
    deep = derive_grid_plan(_context(_manifest(branch_count=2, refine_count=400)))
    shallow = derive_grid_plan(_context(_manifest(branch_count=40, refine_count=10)))
    assert deep.branch_count > 2
    assert deep.refine_count < 400
    assert shallow.branch_count < 40
    assert (deep.branch_count, deep.refine_count) == (20, 20)
    assert (shallow.branch_count, shallow.refine_count) == (4, 4)


def test_the_budget_averaged_is_a_census_of_the_campaigns_walked() -> None:
    """The input is measured over the whole history, not read off the last campaign.

    Feature 242's manifests are a *census* of the node rows each tree actually
    holds — ``discovery.manifest``: *"the summary reflects the tree that was
    walked, not a claim about it"* — so a plan is derived from numbers that were
    measured rather than declared, and from all of them: a plan that read only the
    most recent campaign would be a plan driven by whichever tree happened to be
    last, which is the opposite of a plan derived from history.
    """
    history = (
        _manifest(branch_count=4, refine_count=100),
        _manifest(branch_count=4, refine_count=200),
        _manifest(branch_count=4, refine_count=300),
    )
    plan = derive_grid_plan(_context(*history))
    # The mean refinement count is 200, so the rebalance is side ~ 15.
    assert plan.branch_count == math.isqrt(200 - 1) + 1
    # Not the last campaign's 300 (side 18), and not the first's 100 (side 10).
    assert plan.branch_count not in (
        math.isqrt(300 - 1) + 1,
        math.isqrt(100 - 1) + 1,
    )
    # And the order the caller's query returned them in does not matter: feature
    # 233's context sorts by campaign id, so two histories are one history.
    assert derive_grid_plan(_context(*reversed(history))) == plan


def test_the_derivation_constructs_no_float() -> None:
    """A plan is a whole number of branches, so no plan depends on a rounding mode.

    The means and the square root are taken in exact integer arithmetic —
    ``-(-total // count)`` and :func:`math.isqrt` — and this asserts the property
    directly rather than by reading the source: a float that never appears cannot
    differ between two machines, and the *means* are of counts, so a float would be
    a needless way to make a plan machine-dependent.  The check is an AST pass over
    the module's *code* rather than a text search, because the docstrings argue at
    length about the arithmetic and a naive substring test would fail on the
    module's own honest prose.
    """
    tree = ast.parse(Path(discovery.grid.__file__).read_text())
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    }
    assert not literals, f"float literals in the derivation: {sorted(literals)}"
    # `math.sqrt` (which returns a float) must not be called; `math.isqrt` is the
    # integer spelling and is what the derivation uses.
    called = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == "math"
    }
    assert "sqrt" not in called
    assert called <= {"isqrt"}


# -- The evidence's edges: empty history, and history with no depth ------------


def test_empty_history_takes_the_architectures_reference_grid() -> None:
    """§606's *"including empty history"* is planned rather than refused.

    With no prior campaign there is no evidence and still a plan to return, so the
    grid is the reference campaign shape docs §14.2 costs the system against —
    ``W=16, R=30``, *"~500 nodes at ~1.2k tokens"*.  It is the one number the
    module states rather than derives, and it is a citation: the empty-history path
    returns a campaign the architecture already recognises rather than a default
    the module invented.  The pair is transcribed here from the docs rather than
    read from the module's constants.
    """
    plan = derive_grid_plan(_context())
    assert (plan.branch_count, plan.refine_count) == (
        SPEC_REFERENCE_WIDTH,
        SPEC_REFERENCE_DEPTH,
    )
    assert discovery.REFERENCE_BRANCH_COUNT == SPEC_REFERENCE_WIDTH
    assert discovery.REFERENCE_REFINE_COUNT == SPEC_REFERENCE_DEPTH


def test_a_history_that_refined_nothing_keeps_its_width_and_spends_no_depth() -> None:
    """A record that measured no refinement is evidence about width *alone*.

    This is deliberately **not** the empty-history case and is deliberately not
    given the reference depth: the record tells us how wide this deployment's
    campaigns have actually opened — a measured fact — and says nothing whatever
    about how deep they go.  Spending the reference's 30 refinements here would be
    the module writing a campaign nobody planned, so the plan keeps the measured
    width and spends no depth: ``refine_count=0``, the explore-only grid 229's plan
    law admits.
    """
    plan = derive_grid_plan(_context(_manifest(branch_count=7, refine_count=0)))
    assert plan.branch_count == 7
    assert plan.refine_count == 0


def test_a_history_of_unmeasurable_width_still_opens_a_branch() -> None:
    """A grid of no branch is no grid, whatever the census says.

    A tree whose every node names a parent has no root to open a branch at, so a
    census of such a campaign reports ``branch_count=0``.  The floor is one rather
    than zero because *"a plan with no branches opens no campaign"* — 229's plan
    law — and this seam may not hand a caller a grid that law would refuse.
    """
    plan = derive_grid_plan(_context(_manifest(branch_count=0, refine_count=0)))
    assert plan.branch_count == 1
    assert plan.refine_count == 0


def test_a_single_manifest_is_a_history_of_one() -> None:
    """One prior campaign is a legitimate history, and is not wrapped by the caller.

    Feature 233's adapter states the rule for a batch of manifests and this module
    restates it: refusing a caller that holds exactly one campaign would be the seam
    making that caller's problem worse.  So a **bare** manifest — handed over where
    a batch belongs, not wrapped in a list by the caller — is accepted and treated
    as a history of one, which the first assertion pins by driving the raw value
    through the duck-typed context (feature 233's own context would have normalised
    it at construction, which is the wrong seam for this claim).  The second
    assertion is that it plans *the same grid* a one-element batch does, since a
    history of one is a history of one however it was spelled.
    """
    manifest = _manifest(branch_count=3, refine_count=9)
    one = GridPlan(branch_count=3, refine_count=3)
    assert derive_grid_plan(_raw_context(manifest)) == one
    assert derive_grid_plan(_context(manifest)) == one
    assert derive_grid_plan(_context(manifest)) == derive_grid_plan(
        _raw_context(manifest)
    )


# -- The ceilings: they cap the derivation, they are not the decision ----------


def test_a_configured_ceiling_caps_the_derivation_and_never_raises_it() -> None:
    """The bound exists because a runtime cannot run more slots than it has.

    The policy-runtime member's ``GridPlanningContext`` says the *bound* is
    *"checked by the caller (features 235/237), not here"*, and this is that check.
    A ceiling is a cap and not the decision: a plan that always equalled the
    ceiling would be a configuration read wearing a derivation's name, and the
    reason the bound exists only ever argues downward — so a generous ceiling must
    leave the derivation exactly where the evidence put it.

    A ceiling *may* cap the width below the three theme roots feature 234 requires.
    That refusal is feature 234's to make, naming the themes, because the repair a
    caller needs is about the deployment's configuration and the policy's declared
    themes — not about the grid.
    """
    history = _manifest(branch_count=2, refine_count=400)
    derived = derive_grid_plan(_context(history))
    capped = derive_grid_plan(_context(history, max_branches=5, max_refinements=3))
    assert (capped.branch_count, capped.refine_count) == (5, 3)
    assert capped.branch_count < derived.branch_count
    assert capped.refine_count < derived.refine_count

    generous = derive_grid_plan(
        _context(history, max_branches=1000, max_refinements=1000)
    )
    assert generous == derived


@pytest.mark.parametrize("unset", [0])
def test_a_zero_ceiling_means_unset_rather_than_zero(unset: int) -> None:
    """``0`` is *no ceiling configured*, not a ceiling of zero.

    Feature 233's context states the reading for these two fields — *"Zero means
    no ceiling configured, which is the honest default for a caller that did not
    state one"* — and the policy-runtime member's context states it again.

    The claim is pinned against a **concrete grid** rather than against a second
    call to the same function, because ``0`` is also the constructor's default: a
    comparison of ``PlanContext(h, max_branches=0)`` with ``PlanContext(h)`` would
    hold whether or not ``0`` meant a cap, and so would prove nothing.  What makes
    the reading falsifiable is that a *cap of zero* and *no cap* are different
    grids — a cap of zero admits no branch at all, which is a refusal rather than a
    plan — and that a cap of one is different again.  So the assertions are the
    three distinct outcomes, and a seam that treated ``0`` as a cap would land on
    the refusal instead of the derived grid.
    """
    history = _manifest(branch_count=2, refine_count=400)
    derived = GridPlan(branch_count=20, refine_count=20)

    assert derive_grid_plan(_context(history, max_branches=unset)) == derived
    assert derive_grid_plan(_context(history, max_refinements=unset)) == derived
    assert derive_grid_plan(_context(history)) == derived

    # The three outcomes the reading has to keep apart: unset leaves the derivation
    # alone, a cap narrows it, and a cap of *zero* would admit no branch at all —
    # which the value refuses, so a seam that read `0` as a cap could not have
    # returned `derived` above.
    assert derive_grid_plan(_context(history, max_branches=1)) == GridPlan(
        branch_count=1, refine_count=20
    )
    with pytest.raises(CampaignPlanningError):
        GridPlan(branch_count=0, refine_count=20)


# -- The ask: malformed requests, in the member's existing class ---------------


def test_a_request_without_the_three_reads_is_refused_naming_every_one() -> None:
    """A missing read is a malformed request, not a bug in the derivation.

    The three reads are the surface feature 233's context fixes a hook's author
    against, and a derivation that let an ``AttributeError`` escape would present a
    malformed request as a defect in this module.  Every missing read is named at
    once — the "name every offender" discipline this member's theme batch and
    manifest gate both state — so an author repairs the object rather than meeting
    its fields one resubmission at a time.
    """

    class Nothing:
        pass

    with pytest.raises(CampaignPlanningError) as refusal:
        derive_grid_plan(Nothing())
    message = str(refusal.value)
    for name in ("prior_campaigns", "max_branches", "max_refinements"):
        assert name in message


def test_a_context_that_carries_the_three_reads_plans_under_either_spelling() -> None:
    """The reads are taken **by name**, so an object that is not a PlanContext plans.

    No member imports another, so this member restates the policy-runtime member's
    ``GridPlanningContext`` rather than importing it — and the restatement is only
    worth anything if a hook's author can hand the sibling's object over.  That is
    the duck-typing claim, and it is only *falsifiable* if the object driven here is
    one **feature 233's own context would have refused**: a plain object carrying
    the three names, which is not a :class:`~discovery.planner.PlanContext`, is not
    a dataclass, and did not pass through 233's constructor.  The stand-in's
    history is a **list** rather than a tuple for the same reason — 233's context
    normalises the history it is given into a sorted tuple, so a `PlanContext`
    could never hand the derivation a list, and a test that passed one through
    233's constructor would be testing the constructor's normalisation instead.

    The sibling's *real* context is driven at the foot of this file, alongside 229's
    own ``GridPlan``, where both are imported together.
    """
    history = [_manifest(branch_count=2, refine_count=400)]
    assert derive_grid_plan(_raw_context(history)) == GridPlan(
        branch_count=20, refine_count=20
    )
    # The stand-in really is a different type from 233's context, so the equality
    # above is evidence about the seam rather than about a coincidence of shape.
    assert not isinstance(_raw_context(history), PlanContext)


@pytest.mark.parametrize(
    "history",
    ["not a history", b"not a history", 7, None],
)
def test_a_history_that_is_not_a_batch_is_refused(history: object) -> None:
    """A string is refused rather than iterated into characters.

    The guard feature 241's ``ThemeSet`` states for a set of themes, and here it
    matters for a sharper reason: a string read as a batch would hand the
    derivation a history of single characters, and the refusal would arrive as a
    mangled *manifest* rather than as *"that is not a batch"* — an operator told
    the wrong thing about the wrong value.

    Driven through a duck-typed context rather than feature 233's, because 233's
    normalises what it is handed and this test is about the *history's* shape: the
    seam under test is the derivation's, not the context's constructor.
    """
    with pytest.raises(CampaignPlanningError):
        derive_grid_plan(_raw_context(history))


def test_a_batch_entry_that_is_not_a_manifest_is_refused_with_its_position() -> None:
    """A dict is not a census of a completed campaign.

    Feature 242 is the authority on what a prior manifest is, and a value that is
    not one tells the derivation nothing it is allowed to know — so the refusal
    names the position, the same way feature 233's adapter does, because a batch of
    several manifests is exactly the case where *"something in there is wrong"* is
    not a repair.
    """
    raw = _raw_context([_manifest(), {"branch_count": 2}, _manifest()])
    with pytest.raises(CampaignPlanningError) as refusal:
        derive_grid_plan(raw)
    assert "1" in str(refusal.value)


@pytest.mark.parametrize("ceiling", [True, -1, 2.5, "3"])
def test_a_ceiling_that_is_not_a_count_is_refused(ceiling: object) -> None:
    """The two ceilings are counts; ``0`` alone means *unset*.

    ``bool`` is an ``int`` subclass, so ``True`` would read as a ceiling of one —
    the SQLite affinity trap this workspace guards elsewhere — and a negative
    ceiling admits no branch.  The same check feature 233's context applies to the
    same two fields, restated here rather than imported, and pinned against the
    same inputs so the restatements cannot drift.
    """
    with pytest.raises(CampaignPlanningError):
        derive_grid_plan(_raw_context((), max_branches=ceiling))
    with pytest.raises(CampaignPlanningError):
        derive_grid_plan(_raw_context((), max_refinements=ceiling))


class _RawContext:
    """A planning context that hands its three reads over exactly as given.

    Feature 233's :class:`~discovery.planner.PlanContext` *normalises* the history
    it is constructed with — it sorts and tuples it, and validates the entries only
    downstream at the derivation — so a test of the entry-level and
    history-level refusals needs an object that passes its history through
    untouched.  This is that object: the three names feature 235 reads, no
    behaviour, and no validation.  It doubles as the pin that the derivation's seam
    is *duck-typed* — the reads are taken by name, so any object carrying them
    plans — which is what lets a hook's author hand over the policy-runtime
    member's ``GridPlanningContext``.
    """

    def __init__(
        self,
        prior_campaigns: object,
        *,
        max_branches: object = 0,
        max_refinements: object = 0,
    ) -> None:
        self.prior_campaigns = prior_campaigns
        self.max_branches = max_branches
        self.max_refinements = max_refinements


def _raw_context(history: object, **ceilings: object) -> _RawContext:
    """Build the duck-typed stand-in — one spelling, so the tests cannot drift."""
    return _RawContext(history, **ceilings)


# -- The seam: 235 runs inside 233's boundary, and adds no component ----------


def test_the_derivation_is_a_hook_feature_233_admits_unchanged() -> None:
    """``plan_grid(derive_grid_plan, ...)`` is a complete planning step.

    Feature 233 owns *what a planning hook may read*; this module owns the
    *default* planner, written as a hook that seam admits unchanged: it takes the
    context alone, and it reads only the three permitted names.  So the boundary
    holds **by construction** rather than by a check — there is no name outside the
    three this derivation ever asks for — and the inspection record the context
    keeps is empty, which is the assertion below.
    """
    history = (_manifest(branch_count=2, refine_count=400),)
    planned = plan_grid(derive_grid_plan, prior_campaigns=history)
    assert isinstance(planned, GridPlan)
    assert planned == derive_grid_plan(_context(*history))

    # The record stays empty: the derivation reached for nothing outside the three
    # permitted reads, so 233's seam had nothing to refuse.
    context = _context(*history)
    derive_grid_plan(context)
    assert context.inspections == ()


def test_no_component_is_registered_by_this_feature() -> None:
    """Feature 235 adds no ``@register`` — the member still registers one name.

    235 *does* make a decision, so it is worth being explicit about why it is not a
    component: a builder takes no arguments and is discovered by the factory, while
    a plan is a function of evidence the factory does not hold.  A registered
    planner would have to read a history on its own initiative — which is feature
    233's boundary broken by composition rather than by a hook.  A component
    appears here as a *builder* in the package namespace, which is what this
    asserts is absent.
    """
    assert isinstance(discovery.COMPONENT_NAME, str)
    builders = [
        name
        for name in dir(discovery)
        if name.startswith("build_") and "grid" in name
    ]
    assert builders == []
    assert callable(discovery.derive_grid_plan)


def test_the_seam_reads_no_store_and_opens_no_file() -> None:
    """Feature 235 is pure — the suite needs no fixture, and that is the claim.

    The prior manifests reach the derivation the only way the spec allows: through
    feature 242's ``CampaignManifests.completed``, read by the caller that holds the
    store and handed in.  So the derivation consults no ``DATABASE_URL`` and touches
    no file, which is why this whole suite runs without a fixture — and why the
    module is import-cheap for the factory's scan.

    The check reads the module's **imports and code literals by AST**, not by
    substring over the file text: the docstring argues at length about the store
    this module does *not* touch, so a naive ``"sqlite3" in source`` test would fail
    on the module's own honest prose — a test that would punish documenting the
    decision rather than testing it.
    """
    tree = ast.parse(Path(discovery.grid.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"sqlite3", "os", "pathlib", "urllib"}), imported

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    code_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }
    assert not any("DATABASE_URL" in literal for literal in code_literals)


def test_feature_235_adds_no_error_class_of_its_own() -> None:
    """Every refusal here is a fact about the *request*, so it wears the ask's class.

    A context that does not carry the three reads, a history that is not a batch of
    manifests, a count below its floor — none of these is fixed by anything but
    re-considering what was asked for, which is what
    :class:`~discovery.errors.CampaignPlanningError` is for.  So the module defines
    no new class, and every refusal is catchable by the member's one base class: a
    caller's single ``except DiscoveryError`` still catches everything this feature
    can say.
    """
    for drive in (
        lambda: derive_grid_plan(object()),
        lambda: derive_grid_plan(_raw_context("not a history")),
        lambda: derive_grid_plan(_raw_context((), max_branches=True)),
        lambda: GridPlan(branch_count=0, refine_count=0),
    ):
        with pytest.raises(CampaignPlanningError):
            drive()
        # And the same refusal is caught by the member's one base class, which is
        # the single ``except`` that class exists for.
        with pytest.raises(DiscoveryError):
            drive()


# -- The cross-member pin: 229's plan law and this grid are one law -----------


def test_the_restated_counts_law_is_the_one_feature_229_states() -> None:
    """The counts law is one law in two members, and this is the pin.

    No member imports another, so the policy-runtime member's ``GridPlan`` and this
    one are two spellings — and a workspace where they disagreed about what a plan
    is would be a workspace where a policy's admitted plan could be one this member
    then refused.  The check drives 229's own law over a plan *this* member derived:
    235's value must be a value 229's admission would have admitted, on every path
    this feature can take.

    The import is inside the test, and ``importorskip`` with it, so a workspace
    without the policy-runtime member degrades one test rather than failing the
    collection of this suite — the discipline
    ``packages/discovery/tests/test_cross_member.py`` states for its own sibling
    pins.
    """
    repo_root = Path(__file__).resolve().parents[3]
    sibling_src = repo_root / "packages" / "policy-runtime" / "src"
    if str(sibling_src) not in sys.path:
        sys.path.insert(0, str(sibling_src))
    policy_runtime = pytest.importorskip(
        "policy_runtime", reason="the policy-runtime member is not in this workspace"
    )

    for context in (
        _context(),
        _context(_manifest(branch_count=2, refine_count=400)),
        _context(_manifest(branch_count=0, refine_count=0)),
        _context(_manifest(branch_count=40, refine_count=10)),
        _context(_manifest(branch_count=2, refine_count=400), max_branches=5),
    ):
        grid = derive_grid_plan(context)
        # 229's value takes the same two counts and applies the same floors, so a
        # grid this member derived constructs there without a refusal.
        sibling = policy_runtime.GridPlan(
            branch_count=grid.branch_count, refine_count=grid.refine_count
        )
        assert sibling.branch_count == grid.branch_count
        assert sibling.refine_count == grid.refine_count

    # And the sibling's *context* is the other spelling this seam must accept: the
    # three fields are the same three, under the same names, so a hook's author
    # written against §11 plans here unmodified — which is the restatement's whole
    # purpose.  The empty-history case is the path §606 names, so the derivation is
    # the reference grid with the configured ceiling applied to its *width* —
    # ``max_branches`` bounds branches and ``max_refinements`` bounds depth, and the
    # one left unset caps nothing.
    foreign = policy_runtime.GridPlanningContext(prior_campaigns=(), max_branches=8)
    assert derive_grid_plan(foreign) == GridPlan(
        branch_count=8, refine_count=SPEC_REFERENCE_DEPTH
    )
