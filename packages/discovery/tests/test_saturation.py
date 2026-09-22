"""Feature 237: the saturation response.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 237: *System
reduces allocation for a saturated branch where nearly every refinement
succeeds, which returns a lowered depth budget.*  PRD §434 states the fact this
rule answers in the same sentence feature 236's suite is written against:

    A branch where nearly every refinement succeeds is saturated and loses
    allocation; one where nothing succeeds is beyond the agent's frontier and
    also loses it.

Six things are asserted, in the order the feature's own sentence implies them:
**the judgment** (which branches are saturated — the threshold, its boundary,
and the two branches it must *not* name), **the reduction** (a saturated
branch's depth lowered and every other branch's untouched), **the budget** (the
feature's headline: the returned total is *lowered*, and by exactly what the
saturated branches gave up), **the composition** (the rule runs on feature
236's allocation and 236 cannot make this reduction on its own — the property
this feature exists for), **the refusals** (the malformed asks, which are this
member's malformed-ask class), and **the absence of a component**.

**The property the whole feature turns on is pinned as a property.**  A test
that only asserted "a saturated branch's depth goes down" would pass against a
version of 236 that had *also* lowered every other branch, so the central tests
assert both halves at once: the saturated branch's entry is smaller, and every
other entry is **equal to the unit** — the identity of the untouched branches
being the half that says this is a response to saturation rather than a second
apportionment rule.

**The threshold and the retention are transcribed once each.**  PRD states
neither, so both are named defaults of this module's — but a test that read
:data:`discovery.SATURATION_RATE` to build the branch it expected to be
saturated would agree with whatever the constant said.  So the tests that need
a branch on either side of the threshold build it from a *transcribed* ``0.8``,
for the reason feature 236's suite transcribes ``0.2``, and the one place
either constant's value is written down outside its own comment is the test
below that exists precisely so a change to a knob has to be deliberate.

**The census reaches the verb the only way the spec allows** — counted from the
caller's prefix and handed in — so this suite needs no fixture and no database.
The allocation it is handed is feature 236's *real* value, driven through
:func:`discovery.allocate_depth`, rather than a hand-built mapping: the two
seams are one pipeline, and a stand-in would pin this module against a shape
nothing produces.
"""

from __future__ import annotations

import ast
import math
from fractions import Fraction
from pathlib import Path

import discovery
import pytest
from discovery import (
    BranchDifficulty,
    CampaignPlanningError,
    DiscoveryError,
    GridPlan,
    allocate_depth,
    is_saturated,
    reduce_saturated,
)

#: ``0.8`` — the rate PRD §434's *"nearly every refinement succeeds"* is read as
#: here, written out rather than read from :data:`discovery.SATURATION_RATE`.
#: See the module docstring.
SPEC_SATURATION_RATE = 0.8

#: ``0.5`` — the retention, transcribed for the same reason.
SPEC_SATURATION_RETENTION = 0.5


def _branch(
    theme_root: str = "momentum", refinements: int = 10, succeeded: int = 10
) -> BranchDifficulty:
    """One branch's evidence, shaped like a prefix walk counts it.

    The defaults are the branch this feature *exists* for: ten refinements, all
    ten survived — ``p = 1.0``, saturated outright.  A test that wants a branch
    on the other side of the threshold passes the two counts it wants, and the
    ratio it lands on is spelled in the call rather than hidden here.
    """
    return BranchDifficulty(
        theme_root=theme_root, refinements=refinements, succeeded=succeeded
    )


def _split(census: list[BranchDifficulty], branch_count: int = 3, refine_count: int = 40):
    """Feature 236's real allocation over this census.

    The pipeline the orchestrator runs, minus the grid derivation: 236
    apportions a grid plan's budget across the census, and the result is what
    237 is handed.  Driven through the public verb rather than hand-built, so
    the tests below are about the seam between the two features rather than
    about a mapping this file made up.
    """
    plan = GridPlan(branch_count=branch_count, refine_count=refine_count)
    return allocate_depth(plan, census)


# -- The judgment: which branch this feature is about --------------------------


def test_a_branch_where_every_refinement_succeeded_is_saturated() -> None:
    """The feature's headline case, and the boundary just below it.

    *"a saturated branch where nearly every refinement succeeds"* — so the
    branch that succeeded at every refinement it attempted is saturated, and so
    is one at exactly the stated threshold, because the comparison is inclusive:
    four successes in five is the least the phrase *"nearly every refinement"*
    describes, and a boundary has to belong to one side.  One refinement below
    it is not saturated, which is what makes the threshold a threshold rather
    than a blanket *"most branches"*.
    """
    assert is_saturated(_branch(refinements=10, succeeded=10))
    assert is_saturated(_branch(refinements=10, succeeded=8))
    assert is_saturated(_branch(refinements=100, succeeded=80))
    assert not is_saturated(_branch(refinements=10, succeeded=7))
    assert not is_saturated(_branch(refinements=100, succeeded=79))


def test_the_stated_threshold_and_retention_are_transcribed_once_each() -> None:
    """Both knobs' values, written down so a change has to be deliberate.

    PRD states neither number, so each is a named default the deployment's own
    tuning replaces — and this is the one place either value appears outside its
    own comment.  A reader who changes one meets a failing test that says which
    sentences beside the constant need re-reading, which is the stance feature
    236's suite takes for ``DIFFICULTY_BAND``.  The boundary assertion is made
    against the transcribed rate rather than the constant, so the two cannot
    agree by both having moved.
    """
    assert discovery.SATURATION_RATE == SPEC_SATURATION_RATE
    assert discovery.SATURATION_RETENTION == SPEC_SATURATION_RETENTION
    assert is_saturated(_branch(refinements=5, succeeded=4))  # exactly the rate
    assert not is_saturated(_branch(refinements=5, succeeded=3))


def test_an_unmeasured_branch_is_not_a_saturated_one() -> None:
    """The case PRD §428's complaint turns on, read from this feature's side.

    A branch that has refined nothing has **no rate** — feature 236's
    ``success_rate`` is ``None`` for it — and ``None`` is not a number above any
    threshold.  So the one branch a reduction must not reach is the one nobody
    has probed, which is exactly the branch 236 assumes sits *at* the target
    (its kernel maximum) and therefore the one the frontier might still be in.
    Answering ``True`` here would score an absence of evidence as evidence of
    exhaustion, and the two are the states feature 236 exists to tell apart.
    """
    unmeasured = _branch(theme_root="unexplored", refinements=0, succeeded=0)
    assert unmeasured.success_rate is None
    assert not is_saturated(unmeasured)
    # And a *measured* branch at the same place is judged on its measurement:
    # zero successes over ten refinements is a rate, and it is far below the
    # threshold — barrenness is 236's to penalise, not this feature's to reduce.
    barren = _branch(theme_root="barren", refinements=10, succeeded=0)
    assert barren.success_rate == 0.0
    assert not is_saturated(barren)


def test_a_value_that_is_not_a_branch_is_refused_rather_than_answered_false() -> None:
    """A predicate that called an arbitrary object unsaturated would be silent.

    The distinction matters because ``False`` is a *judgment about evidence*
    here, not merely the absence of a match: a census entry that is a string or
    a rate would come back as "not saturated" and be reduced by nothing, which
    is the caller's mistake presented as a decision about a campaign.  So the
    refusal is this member's malformed-ask class, the one
    :func:`discovery.difficulty._validated_census` refuses the same kind of
    value in.
    """
    for value in (0.9, "momentum", None, 10, {"theme_root": "momentum"}):
        with pytest.raises(CampaignPlanningError):
            is_saturated(value)
        with pytest.raises(DiscoveryError):
            is_saturated(value)


# -- The reduction: the saturated branch lowered, the rest untouched -----------


def test_a_saturated_branch_keeps_the_stated_retention_of_its_depth() -> None:
    """*"reduces allocation for a saturated branch"* — and only for that branch.

    The two halves together are the feature.  The saturated branch's depth is
    lowered to ``floor(depth × retention)``, and **every other branch's depth is
    equal to the unit** — which is what makes this a response to saturation
    rather than a second apportionment rule.  A rewrite that lowered every
    branch by the retention (or, worse, one that re-split the budget) would
    satisfy the first assertion and fail the second.

    The census is chosen so that both halves are *visible*, which is a narrower
    window than it looks and is worth stating: feature 236's kernel floors a
    saturated branch to zero on its own as soon as a frontier branch sits beside
    it (the weights differ by three orders of magnitude), so a census mixing the
    two has nothing for this feature to lower.  The reduction this module makes
    is visible exactly where 236 *cannot* make it — a census whose branches are
    all far from the target, so the proportional split is non-degenerate — which
    is the same window
    :func:`test_the_budget_is_lowered_even_when_every_branch_is_saturated`
    states from the budget side.
    """
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=8),
        _branch(theme_root="near", refinements=10, succeeded=7),
    ]
    before = _split(census)
    # The precondition this test is about: 236 gave the saturated branch depth
    # of its own, so there is something for this feature to lower.
    assert before.depths["saturated"] > 1

    after = reduce_saturated(before, census)
    for theme_root, depth in before.depths.items():
        if theme_root == "saturated":
            assert after.depths[theme_root] == math.floor(
                depth * SPEC_SATURATION_RETENTION
            )
            assert after.depths[theme_root] < depth
        else:
            assert after.depths[theme_root] == depth, theme_root


def test_the_reduction_is_the_exact_product_floored_not_a_float_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``floor(depth × retention)`` as the exact number, not as the float.

    The retention is written ``0.5`` and the arithmetic is trivial at that
    value, so the *discipline* is pinned at a retention where it is not: a
    retention of ``0.3`` is not the binary float ``0.3``, and ``floor(10 ×
    0.3)`` is ``3`` in floating point against ``2`` as the exact product.  Only
    the second is a reduction a campaign can be reproduced under, which is
    feature 236's own stated reason for apportioning in exact rational
    arithmetic — restated here at a single multiplication.

    The two floors are asserted to *disagree* at the depth this test drives,
    so the passing assertion cannot be a coincidence of the two spellings
    landing on the same integer; and then the module's answer is asserted to be
    the exact one rather than merely to be a floor.

    ``monkeypatch.setattr`` rather than a bare assignment, so the constant is
    restored even if an assertion fails; a test that changed a module global and
    did not put it back would poison every test after it.
    """
    monkeypatch.setattr(discovery.saturation, "SATURATION_RETENTION", 0.3)
    # A census and a budget chosen so the saturated branch carries a depth at
    # which the two spellings really part ways: ``p = 0.8`` against ``p = 0.7``
    # apportions the saturated branch 20 of this plan's 100 refinements, and
    # ``floor(20 × 0.3)`` is ``6`` as a float against ``5`` as the exact product.
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=8),
        _branch(theme_root="other", refinements=10, succeeded=7),
    ]
    before = _split(census, branch_count=2, refine_count=50)
    after = reduce_saturated(before, census)

    depth = before.depths["saturated"]
    exact = Fraction(depth) * Fraction(0.3)
    exact_floor = exact.numerator // exact.denominator
    # The precondition this test exists for: at this depth the two spellings
    # really do differ, so the answer below distinguishes them.
    assert math.floor(depth * 0.3) != exact_floor

    assert after.depths["saturated"] == exact_floor
    assert after.depths["other"] == before.depths["other"]


def test_a_census_with_nothing_saturated_comes_back_unchanged() -> None:
    """A response is not an obligation, and the common campaign has none.

    Every branch below the threshold means there is nothing to reduce, and the
    honest answer is the split that was handed in — equal as a value, because
    :class:`~discovery.difficulty.DepthAllocation` is compared by its mapping.
    The alternative reading, refusing because *this is not a saturated
    campaign*, would turn a rule that fires sometimes into a precondition every
    campaign must meet, which the feature's sentence does not say.
    """
    census = [
        _branch(theme_root="alpha", refinements=10, succeeded=2),
        _branch(theme_root="beta", refinements=10, succeeded=4),
        _branch(theme_root="gamma", refinements=10, succeeded=0),
    ]
    before = _split(census)
    assert reduce_saturated(before, census) == before
    assert reduce_saturated(before, census).total == before.total

    # An unmeasured census is the same statement about evidence, made harder:
    # nothing is saturated, so nothing is reduced, and the branch 236 assumed
    # sits at the target keeps every unit it was given.
    unexplored = [
        _branch(theme_root="alpha", refinements=0, succeeded=0),
        _branch(theme_root="beta", refinements=0, succeeded=0),
    ]
    untouched = _split(unexplored)
    assert reduce_saturated(untouched, unexplored) == untouched


def test_the_reduction_bites_where_236_cannot_make_it() -> None:
    """The two windows side by side, and which one this feature is *for*.

    Feature 236's kernel is steep enough that a saturated branch beside a
    *frontier* one is already floored away on 236's own arithmetic — the weights
    differ by three orders of magnitude, and no campaign budget recovers a whole
    refinement from that ratio.  So the honest statement of this module's bite
    is not "saturated branches everywhere" but the narrower case PRD §428's
    complaint actually describes: a census whose branches are **all** far from
    the target, where the split is non-degenerate and every branch keeps a real
    share.  Both are driven here, and the assertions say which does what — a
    reader should not have to discover that the mixed census is a no-op by
    trying it.
    """
    mixed = [
        _branch(theme_root="saturated", refinements=10, succeeded=10),
        _branch(theme_root="frontier", refinements=10, succeeded=2),
    ]
    mixed_before = _split(mixed)
    # 236 already dismissed it: the saturated branch holds nothing to reduce.
    assert mixed_before.depths["saturated"] == 0
    assert reduce_saturated(mixed_before, mixed) == mixed_before

    degenerate = [
        _branch(theme_root="saturated", refinements=10, succeeded=8),
        _branch(theme_root="near-threshold", refinements=10, succeeded=7),
    ]
    degenerate_before = _split(degenerate)
    # Here no branch is near the target, so the split is proportional and both
    # keep a real share — which is the window this feature exists for.
    assert all(depth > 0 for depth in degenerate_before.depths.values())
    degenerate_after = reduce_saturated(degenerate_before, degenerate)
    assert degenerate_after.total < degenerate_before.total
    # And the reduction falls on the branch over the threshold alone: the other
    # is one refinement short of saturation and keeps every unit.
    assert degenerate_after.depths["saturated"] < degenerate_before.depths["saturated"]
    assert (
        degenerate_after.depths["near-threshold"]
        == degenerate_before.depths["near-threshold"]
    )


def test_a_branch_floored_to_zero_by_236_is_reduced_without_a_special_case() -> None:
    """A saturated branch 236 already dropped to zero stays there, present.

    The arithmetic of ``floor(0 × retention) = 0`` answers this without a guard,
    which is the point: a branch at zero depth is still a branch of the census —
    feature 236's *present at zero, not absent* — and a reduction that skipped
    it, or that removed its entry, would be this seam making a second statement
    about a branch it was only asked to lower.
    """
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=10),
        _branch(theme_root="frontier", refinements=10, succeeded=2),
    ]
    before = _split(census, branch_count=2, refine_count=10)
    assert before.depths["saturated"] == 0  # 236 floored it away already

    after = reduce_saturated(before, census)
    assert "saturated" in after.depths
    assert after.depths["saturated"] == 0
    assert after.depths["frontier"] == before.depths["frontier"]


# -- The budget: the feature's headline, "a lowered depth budget" --------------


def test_the_returned_budget_is_lowered_by_exactly_what_saturation_gave_up() -> None:
    """The feature's own words: the *total* goes down, by the saturated share.

    *"which returns a lowered depth budget"* — so the headline assertion is
    about :attr:`~discovery.difficulty.DepthAllocation.total`, not about one
    branch's entry, and it is stated as an exact identity rather than as
    ``less than``: the freed depth is the sum of what the saturated branches
    gave up and nothing else.  An implementation that quietly redistributed the
    freed units onto the frontier branch would keep the total unchanged and fail
    here, which is the boundary this feature's return value draws.
    """
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=8),
        _branch(theme_root="near", refinements=10, succeeded=7),
    ]
    before = _split(census)
    after = reduce_saturated(before, census)

    given_up = sum(
        before.depths[theme_root] - after.depths[theme_root]
        for theme_root in before.depths
    )
    assert after.total == before.total - given_up
    assert after.total < before.total
    # And the freed depth really did come from the saturated branch alone: the
    # other branch gave up nothing at all.
    assert after.depths["near"] == before.depths["near"]
    assert given_up == before.depths["saturated"] - math.floor(
        before.depths["saturated"] * SPEC_SATURATION_RETENTION
    )


def test_the_budget_is_lowered_even_when_every_branch_is_saturated() -> None:
    """The reduction 236 provably cannot make — which is why this feature exists.

    Feature 236's apportionment is **proportional**, so it is scale-free: a
    census in which every branch weighs the same is split evenly, however small
    those weights are.  Two branches that each succeeded at every refinement of
    ten weigh ``exp(−8) ≈ 0.00034`` apiece, so 236 hands them half the campaign's
    refinements each — having ranked them correctly and with no way to spend
    less.  This test states the gap and then closes it: the allocation *before*
    237 is the full budget split evenly, and the allocation after is half of
    that.  A rewrite of 236 that "solved" saturation in its own kernel would
    leave this module nothing to do and fail the second assertion.
    """
    census = [
        _branch(theme_root="alpha", refinements=10, succeeded=10),
        _branch(theme_root="beta", refinements=10, succeeded=10),
    ]
    before = _split(census, branch_count=3, refine_count=40)
    # 236's even split of the whole budget — the property this feature answers.
    assert before.depths == {"alpha": 60, "beta": 60}
    assert before.total == 120

    after = reduce_saturated(before, census)
    assert after.depths == {"alpha": 30, "beta": 30}
    assert after.total == 60
    assert after.total < before.total


def test_a_saturation_response_is_never_an_inflation() -> None:
    """The verb lowers on every input, and that is a bound rather than a check.

    ``floor(depth × retention)`` is at most ``depth`` for every retention the
    module admits, so the guarantee holds by the multiplication rather than by
    a comparison a rewrite could drop.  Driven over a spread of censuses and
    budgets, including ones where the reduction is a no-op and ones where every
    branch is saturated, so the bound is asserted as a bound.
    """
    censuses = [
        [_branch(theme_root="a", refinements=10, succeeded=10)],
        [_branch(theme_root="a", refinements=10, succeeded=10), _branch(theme_root="b", refinements=3, succeeded=3)],
        [_branch(theme_root="a", refinements=10, succeeded=8), _branch(theme_root="b", refinements=9, succeeded=9)],
        [_branch(theme_root="a", refinements=10, succeeded=1), _branch(theme_root="b", refinements=0, succeeded=0)],
    ]
    for census in censuses:
        for branch_count, refine_count in ((1, 1), (2, 5), (3, 40), (5, 7)):
            before = _split(census, branch_count=branch_count, refine_count=refine_count)
            after = reduce_saturated(before, census)
            assert after.total <= before.total
            for theme_root, depth in after.depths.items():
                assert 0 <= depth <= before.depths[theme_root], (theme_root, depth)


# -- The composition: 237 runs on 236's allocation, in the stated order --------


def test_the_response_runs_on_the_grid_the_history_justified() -> None:
    """The whole pipeline, end to end: 235 derives, 236 splits, 237 lowers.

    The seam feature 235's docstring names — *"Features 236 and 237 then skew
    this base grid per branch, by difficulty and by saturation"* — driven in the
    order it names, with feature 242's manifest as the history.  Nothing is lost
    between the steps: the split conserves 235's budget exactly, and the
    response lowers that split rather than re-deriving anything.

    The census is deliberately *all saturated*, because that is the case the
    three-step pipeline is worth running at all: the derivation produces a flat
    grid, 236 splits it evenly among branches it cannot tell apart, and 237 is
    the only step that can act on what the tuple actually says.
    """
    from discovery import CampaignManifest, PlanContext, derive_grid_plan

    history = CampaignManifest(
        campaign_id="11111111-1111-1111-1111-111111111111",
        calibration_status="ok",
        branch_count=2,
        refine_count=400,
        leaf_count=1,
        node_count=403,
        depth_max=1,
        theme_roots=3,
    )
    plan = derive_grid_plan(PlanContext((history,)))
    census = [
        _branch(theme_root="alpha", refinements=10, succeeded=10),
        _branch(theme_root="beta", refinements=10, succeeded=10),
        _branch(theme_root="gamma", refinements=10, succeeded=10),
    ]

    allocation = allocate_depth(plan, census)
    assert allocation.total == plan.branch_count * plan.refine_count

    response = reduce_saturated(allocation, census)
    assert response.total < allocation.total
    for theme_root, depth in allocation.depths.items():
        assert response.depths[theme_root] == math.floor(
            depth * SPEC_SATURATION_RETENTION
        )


def test_the_split_and_the_census_must_name_the_same_branches() -> None:
    """A reduction is applied by *the* evidence that justifies it, or not at all.

    The check this module adds, and the two ways of getting it wrong are both
    silent: a branch the split allocated depth to but the census does not
    measure would keep an allocation whose saturation nothing judged — and
    judging absent evidence unsaturated understates the response, while judging
    it saturated would be this module inventing the measurement — and a branch
    the census measures but the split does not carry is one campaign's
    allocation lowered by another's evidence.  Both are refused, and **both
    directions are named in one refusal**, so a caller that mixed two campaigns
    learns the whole of the difference at once rather than one resubmission at
    a time.
    """
    measured = [
        _branch(theme_root="alpha", refinements=10, succeeded=10),
        _branch(theme_root="beta", refinements=10, succeeded=2),
    ]
    allocation = _split(measured)

    # A census that omits a branch the split carries.
    with pytest.raises(CampaignPlanningError) as omitted:
        reduce_saturated(allocation, measured[:1])
    assert "beta" in str(omitted.value)
    assert "does not measure" in str(omitted.value)

    # A census carrying a branch the split does not.
    with pytest.raises(CampaignPlanningError) as added:
        reduce_saturated(
            allocation,
            [*measured, _branch(theme_root="gamma", refinements=10, succeeded=10)],
        )
    assert "gamma" in str(added.value)
    assert "no depth" in str(added.value)

    # And both at once, so a caller sees every disagreement in one answer.
    with pytest.raises(CampaignPlanningError) as both:
        reduce_saturated(
            allocation,
            [_branch(theme_root="alpha", refinements=10, succeeded=10),
             _branch(theme_root="gamma", refinements=10, succeeded=10)],
        )
    assert "beta" in str(both.value)
    assert "gamma" in str(both.value)


# -- The ask: malformed requests, in the member's existing class ---------------


def test_an_allocation_that_is_not_a_split_is_refused() -> None:
    """The first thing a reduction is applied to, checked as this member's value.

    Deliberately **not** duck-typed, unlike the plan feature 236 reads by name:
    a :class:`~discovery.difficulty.GridPlan` has a second spelling in the
    policy-runtime member that no member may import, while a
    :class:`~discovery.difficulty.DepthAllocation` is this member's own value
    with no sibling spelling — so a value that is not one is a caller's mistake
    rather than another vocabulary, and the refusal says so.
    """
    census = [_branch()]
    for value in (object(), {"alpha": 3}, None, 10, "alpha"):
        with pytest.raises(CampaignPlanningError):
            reduce_saturated(value, census)
        with pytest.raises(DiscoveryError):
            reduce_saturated(value, census)


def test_a_census_this_feature_cannot_read_is_refused_in_236s_vocabulary() -> None:
    """The batch law is feature 236's, reused rather than restated.

    The census here is not *like* 236's — it is the very evidence the split was
    apportioned from — so it is validated by the same function, and a malformed
    one meets the same refusals: a bare string read as a batch, an entry that is
    not a branch, an empty batch, a theme root named twice.  This is the drift
    the reuse exists to prevent: two validators would be two laws for one batch.
    """
    allocation = _split([_branch(theme_root="alpha"), _branch(theme_root="beta")])
    for census in (
        "momentum",
        b"momentum",
        [[]],
        [],
        [{"theme_root": "alpha"}],
        [_branch(theme_root="alpha"), _branch(theme_root="alpha")],
    ):
        with pytest.raises(CampaignPlanningError):
            reduce_saturated(allocation, census)


def test_a_knob_outside_the_unit_interval_is_refused_rather_than_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guards on the two named defaults, and the path that reaches them.

    Unreachable through the stated values — ``0.8`` and ``0.5`` are both in
    range — but reachable by the deployment the constants' own comments invite
    to retune them, and a retention above ``1`` would make this verb *raise* a
    budget where its sentence says it lowers one.  So each knob is checked where
    it is read, and each refusal names the constant and what it is for.

    ``monkeypatch.setattr`` so the constants are restored even if an assertion
    fails — a test that left a knob mis-set would poison every test after it.
    """
    census = [_branch(theme_root="alpha")]
    allocation = _split(census, branch_count=1, refine_count=4)

    for knob, value in (
        ("SATURATION_RATE", 1.5),
        ("SATURATION_RATE", -0.1),
        ("SATURATION_RATE", float("nan")),
        ("SATURATION_RATE", True),
        ("SATURATION_RATE", "0.8"),
        ("SATURATION_RETENTION", 1.5),
        ("SATURATION_RETENTION", -0.5),
        ("SATURATION_RETENTION", float("nan")),
        ("SATURATION_RETENTION", True),
        ("SATURATION_RETENTION", None),
    ):
        monkeypatch.setattr(discovery.saturation, knob, value)
        with pytest.raises(CampaignPlanningError) as refused:
            reduce_saturated(allocation, census)
        assert knob in str(refused.value)
        monkeypatch.undo()

    # And the predicate reads the same guard, so a mis-set knob cannot quietly
    # make every branch saturated or none of them.
    monkeypatch.setattr(discovery.saturation, "SATURATION_RATE", 2.0)
    with pytest.raises(CampaignPlanningError):
        is_saturated(_branch())
    monkeypatch.undo()


def test_a_retention_at_the_top_of_its_range_is_the_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``1.0`` is the knob's boundary: saturation earns no response at all.

    Worth pinning because it is the value a deployment reaches by saying the
    response is wrong for its campaigns, and it is inside the range rather than
    refused — so the module has to answer it correctly rather than guard against
    it.  The result is a split equal to the one handed in, which is the same
    answer the *nothing saturated* case gives, from the other direction.
    """
    monkeypatch.setattr(discovery.saturation, "SATURATION_RETENTION", 1.0)
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=10),
        _branch(theme_root="frontier", refinements=10, succeeded=2),
    ]
    before = _split(census)
    assert reduce_saturated(before, census) == before


def test_feature_237_adds_no_error_class_of_its_own() -> None:
    """Every refusal is a fact about the request, so it wears the ask's class.

    A value that is not an allocation, a batch 236 cannot read, an allocation
    and a census that disagree, a knob outside its range — none is fixed by
    anything but re-considering what was asked for, which is what
    :class:`~discovery.errors.CampaignPlanningError` is for.  So this module
    defines no new class, and every refusal is catchable by the member's one
    base class: a caller's single ``except DiscoveryError`` still catches
    everything the whole pipeline can say.  A second class here would be a
    second vocabulary for one sentence, the drift
    ``packages/discovery/tests/test_cross_member.py`` exists to prevent.
    """
    census = [_branch(theme_root="alpha")]
    allocation = _split(census, branch_count=1, refine_count=4)
    for drive in (
        lambda: is_saturated("momentum"),
        lambda: reduce_saturated(object(), census),
        lambda: reduce_saturated(allocation, "momentum"),
        lambda: reduce_saturated(allocation, []),
        lambda: reduce_saturated(allocation, [_branch(theme_root="beta")]),
    ):
        with pytest.raises(CampaignPlanningError):
            drive()
        with pytest.raises(DiscoveryError):
            drive()


# -- The shape: no component, no store, no third-party import ------------------


def test_no_component_is_registered_by_this_feature() -> None:
    """Feature 237 adds no ``@register`` — the member still registers one name.

    The feature with *two tunable knobs* is the one where a component looks most
    tempting, so this is the assertion worth making explicit: a builder takes no
    arguments and is built on every ``create_app()`` call, while this verb is a
    function of an allocation and a census the factory holds neither of.  A
    component appears in the package namespace as a *builder*, which is what
    this asserts is absent — and the member's registered surface is still
    feature 232's single store.
    """
    assert isinstance(discovery.COMPONENT_NAME, str)
    builders = [
        name for name in dir(discovery) if name.startswith("build_") and "saturat" in name
    ]
    assert builders == []
    assert callable(discovery.is_saturated)
    assert callable(discovery.reduce_saturated)

    # The registration count this member's component suite pins is unchanged:
    # one unprefixed name, which is the campaign store.
    assert discovery.COMPONENT_NAME == "discovery"


def test_the_seam_reads_no_store_and_opens_no_file() -> None:
    """Feature 237 is pure — the suite needs no fixture, and that is the claim.

    The allocation reaches this module from feature 236's apportionment and the
    census from the caller's prefix walk, so the verb consults no
    ``DATABASE_URL`` and touches no file.  The check reads the module's
    **imports by AST** rather than by substring over the file text: the
    docstring argues at length about the store this module does *not* touch, so
    a naive ``"sqlite3" in source`` test would fail on the module's own honest
    prose — the discipline feature 236's suite states for its own copy of this
    check.
    """
    tree = ast.parse(Path(discovery.saturation.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"sqlite3", "os", "pathlib", "urllib", "threading"}), imported

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


def test_the_two_seams_share_one_census_law_and_one_predicate() -> None:
    """237 reuses 236's validator and spells the judgment in exactly one place.

    Two claims about the module's structure, both of which are about drift
    rather than about behaviour — which is why they are read off the module
    rather than driven through it.  The census validator is *the same function
    object* :func:`discovery.difficulty.allocate_depth` uses, so the two seams
    cannot come to disagree about what a batch of branches is; and
    :func:`discovery.is_saturated` delegates to the private comparison rather
    than restating it, so the predicate and the verb cannot come to disagree
    about which branches the feature is about.
    """
    assert discovery.saturation._validated_census is discovery.difficulty._validated_census

    # The public predicate and the verb's per-branch judgment agree on every
    # branch of a spread census — including the unmeasured one, where the two
    # could plausibly have diverged into ``False`` versus a raise.
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=10),
        _branch(theme_root="frontier", refinements=10, succeeded=2),
        _branch(theme_root="barren", refinements=10, succeeded=0),
        _branch(theme_root="unmeasured", refinements=0, succeeded=0),
    ]
    threshold, _retention = discovery.saturation._validated_knobs()
    for branch in census:
        assert discovery.saturation._is_saturated_at(branch, threshold) == (
            is_saturated(branch)
        ), branch.theme_root
