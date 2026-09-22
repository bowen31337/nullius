"""Feature 236: frontier-difficulty depth allocation.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 236: *System
computes a per-branch difficulty weight targeting a success rate near 0.2,
which returns a depth allocation favouring the agent frontier.*  PRD §428
states the mechanism and the formula — ``D(branch) = exp(−(p_branch − p*)² /
2σ²)``, ``p* = 0.2`` — and PRD §434 states the shape the two ends of the rate
range are asserted against here:

    A branch where nearly every refinement succeeds is saturated and loses
    allocation; one where nothing succeeds is beyond the agent's frontier and
    also loses it.  Depth flows to branches sitting at the edge of what the
    discovery agent can actually do, which is where the informative trials are.

Six things are asserted, in the order the feature's own sentence implies them:
**the kernel** (a weight at a measured rate, peaking at the cited target and
falling away from it in both directions), **the value** (a per-branch weight,
and what an *unmeasured* branch weighs — the case PRD §428's complaint about
*"an exhausted theme from an unexplored one"* turns on), **the allocation**
(the plan's budget, conserved exactly, spent in proportion to difficulty and
therefore favouring the frontier), **the refusals** (the malformed asks, which
are this member's malformed-ask class), **the seam** (the two plan spellings
this workspace holds both fill the budget), and **the absence of a component**.

**The facts are pinned as properties, not as a transcription of the kernel.**
PRD states the formula, so the kernel tests assert *what the formula means* —
the peak is at the target, the weight is symmetric in distance from it, and it
falls monotonically away — against numbers this file computes itself, rather
than re-writing ``exp(−x²/2σ²)`` and agreeing with the module's own spelling of
it.  A rewrite that keeps the argument and changes the constant passes; a
rewrite that keeps the constant and loses the argument fails.

**``p*`` is transcribed, ``σ`` is not.**  ``0.2`` is written out here from PRD
§431 rather than read from :data:`discovery.TARGET_SUCCESS_RATE`, for the reason
feature 235's suite transcribes ``16`` and ``30``: a test that compared the
constant with itself would agree with whatever the constant said.  ``σ`` has no
number in any document — it is a named default (see the module's own comment) —
so the tests that need a band read the constant and drive the *properties*
instead, which is the only honest thing to assert about a knob a document does
not fix.  The one place the band's value is transcribed is
``test_the_stated_band_is_the_target_itself_and_its_edges_are_as_documented``,
which exists precisely so that a change to the knob has to be made deliberately
and the comment beside it re-read.

**The conservation law is asserted as arithmetic over a fractional split.**  The
budget tests use a census whose exact quotas are deliberately not whole numbers
— five branches of unequal weight against a budget of ``1`` — so that flooring
without the largest-remainder correction would lose units and the test would
see it.  A rewrite that kept the spelling and lost the law fails here.

Feature 236 is pure, so this suite needs no fixture and no database: the census
reaches the allocation the way the spec allows — counted from feature 223's
prefix view by the caller, and handed in here.
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
    BranchDifficulty,
    CampaignPlanningError,
    DepthAllocation,
    DiscoveryError,
    GridPlan,
    allocate_depth,
    derive_grid_plan,
    difficulty_weight,
)

#: ``p*`` — PRD §431's literal ``p* = 0.2``, written out here rather than read
#: from :data:`discovery.TARGET_SUCCESS_RATE`.  See the module docstring.
SPEC_TARGET_RATE = 0.2


def _branch(
    theme_root: str = "momentum", refinements: int = 10, succeeded: int = 2
) -> BranchDifficulty:
    """One branch's evidence, shaped like a prefix walk counts it.

    The defaults are the branch the feature *wants* to spend depth on: ten
    refinements, two of them survived — ``p = 0.2``, exactly PRD §431's target,
    so the default branch sits at the kernel's peak and every other case in this
    file is read against it.
    """
    return BranchDifficulty(
        theme_root=theme_root, refinements=refinements, succeeded=succeeded
    )


# -- The kernel: a weight at a measured rate -----------------------------------


def test_the_kernel_peaks_at_the_cited_target_and_is_one_there() -> None:
    """``D(p*) = 1`` — the target is the kernel's maximum, and PRD §431's number.

    The one point of the kernel a document fixes.  ``exp(0) = 1`` is the
    arithmetic, and ``p* = 0.2`` is the citation; the assertion that the target
    is the *peak* is the neighbouring cases, which must all be strictly below.
    """
    assert difficulty_weight(SPEC_TARGET_RATE) == 1.0
    assert discovery.TARGET_SUCCESS_RATE == SPEC_TARGET_RATE
    for rate in (0.0, 0.1, 0.3, 0.5, 0.8, 1.0):
        assert difficulty_weight(rate) < 1.0, rate


def test_the_kernel_falls_away_from_the_target_in_both_directions() -> None:
    """The weight is a function of *distance* from ``p*``, not of the rate.

    ``(p − p*)²`` is symmetric, so a branch above the target by as much as
    another sits below it weighs the same — which is the whole of what makes
    this a *kernel* rather than a monotone criterion, and the reason §434's two
    failures are two failures rather than one success-criterion.  Monotonicity
    away from the target is asserted alongside, so the shape is pinned as a
    shape rather than at two sampled points.

    The symmetry is asserted to *floating-point* precision rather than to the
    bit, and that is a fact about the arithmetic rather than a weakening of the
    claim: ``0.2 + 0.1`` and ``0.2 − 0.1`` are not the same distance from ``0.2``
    in binary floating point, so the two squared distances differ in the last
    bits and ``exp`` of them differs with them.  The *shape* — equal weight at
    equal distance — is what the feature is about, and a branch's distance is
    never an exact quantity to begin with.
    """
    band = discovery.DIFFICULTY_BAND
    for offset in (0.05, 0.1, 0.25, 0.4, 0.8):
        below = SPEC_TARGET_RATE - offset
        above = SPEC_TARGET_RATE + offset
        if below < 0.0 or above > 1.0:
            continue
        # Equal distance from the target, so equal weight to within the last
        # bits the two spellings of that distance can differ by.
        assert difficulty_weight(below) == pytest.approx(
            difficulty_weight(above), rel=1e-12
        ), offset
        # And the documented decay: exp(-offset² / 2σ²) with the band read from
        # the module, because no document states it.
        assert difficulty_weight(below) == pytest.approx(
            math.exp(-(offset * offset) / (2 * band * band)), rel=1e-12
        )

    # Monotone in the distance: closer to the target is always heavier.
    ascending = [difficulty_weight(rate) for rate in (0.0, 0.05, 0.1, 0.2)]
    assert ascending == sorted(ascending)
    descending = [difficulty_weight(rate) for rate in (0.2, 0.5, 0.8, 1.0)]
    assert descending == sorted(descending, reverse=True)


def test_a_saturated_branch_loses_more_than_a_barren_one() -> None:
    """PRD §434's two ends, and the asymmetry between them.

    *"A branch where nearly every refinement succeeds is saturated and loses
    allocation; one where nothing succeeds is beyond the agent's frontier and
    also loses it."*  Both lose, and they lose **unequally** — and that is not a
    second rule but a consequence of where ``p*`` sits: a saturated branch is a
    full ``0.8`` from a target of ``0.2``, while a barren one is only ``0.2``
    away.  The direction matters for the campaign: the barren branch is the one
    that might still be probed into usefulness, and the saturated one is the
    settled fact.

    The magnitudes are read from the stated band rather than transcribed, since
    only the *shape* is in the spec.
    """
    saturated = difficulty_weight(1.0)
    barren = difficulty_weight(0.0)
    assert saturated < barren < 1.0
    # The asymmetry is the distance arithmetic, not a separate constant: the
    # saturated branch is 0.8 from the target and the barren one 0.2.
    assert barren == pytest.approx(
        math.exp(-((0.0 - SPEC_TARGET_RATE) ** 2) / (2 * discovery.DIFFICULTY_BAND**2))
    )
    # And in the units the feature's sentence is written in: a measured, barren
    # branch keeps most of its weight while a saturated one keeps almost none.
    assert barren > 0.5
    assert saturated < 0.01


def test_the_stated_band_is_the_target_itself_and_its_edges_are_as_documented() -> None:
    """The knob's value, transcribed once, so a change has to be deliberate.

    No document states ``σ``, so it is a named default the deployment's tuning
    replaces — and this is the one place its value is written down outside the
    constant's own comment.  The three weights the comment claims for the three
    rates that matter are asserted with it, so the prose and the arithmetic
    cannot drift apart: a reader who changes the band meets a failing test that
    says which sentences in the comment need re-reading.
    """
    assert discovery.DIFFICULTY_BAND == 0.2
    assert difficulty_weight(0.0) == pytest.approx(math.exp(-0.5), rel=1e-12)
    assert difficulty_weight(0.4) == pytest.approx(math.exp(-0.5), rel=1e-12)
    assert difficulty_weight(1.0) == pytest.approx(math.exp(-8.0), rel=1e-12)


@pytest.mark.parametrize("rate", [-0.001, 1.001, -1.0, 2.0, float("nan"), float("inf")])
def test_a_rate_that_is_not_a_proportion_is_refused(rate: float) -> None:
    """A rate lies in ``[0, 1]``; one outside it is not a measurement.

    ``NaN`` is refused explicitly and that is load-bearing: every comparison
    against a ``NaN`` is false, so a ``NaN`` weight would compare neither less
    than nor greater than any other weight in its census — the apportionment
    would then split by whichever branch happened to sort first rather than by
    evidence, and would do it silently.
    """
    with pytest.raises(CampaignPlanningError):
        difficulty_weight(rate)


@pytest.mark.parametrize("rate", [True, False, "0.2", None, 2j])
def test_a_rate_that_is_not_a_number_is_refused(rate: object) -> None:
    """``True`` is not a rate of one — the SQLite affinity trap, restated here.

    ``bool`` is an ``int`` subclass, so an unguarded check would read ``True``
    as a branch that succeeded at every refinement it attempted and ``False`` as
    one that succeeded at none — both silently, and both mapping to wildly
    different weights.  The same guard features 232, 233, 235 and 242 apply to
    their own counts.
    """
    with pytest.raises(CampaignPlanningError):
        difficulty_weight(rate)


# -- The value: one branch's weight, and the unmeasured case --------------------


def test_a_branch_reports_the_rate_its_refinements_measured() -> None:
    """``p_branch`` is ``succeeded / refinements`` — the prefix's own count.

    The rate is what the kernel is taken at, and it is derived rather than
    stored: two branches with the same ratio spelled over different counts
    measure the same rate.
    """
    assert _branch(refinements=10, succeeded=2).success_rate == 0.2
    assert _branch(refinements=100, succeeded=20).success_rate == 0.2
    assert _branch(refinements=4, succeeded=0).success_rate == 0.0
    assert _branch(refinements=4, succeeded=3).success_rate == 0.75


def test_an_unmeasured_branch_sits_at_the_target_rather_than_at_zero() -> None:
    """PRD §428's *"exhausted theme from an unexplored one"* — the two are different.

    This is the case the whole docstring argument turns on, so it is asserted
    from both sides:

    * a branch that **refined and never succeeded** has a *measured* rate of
      ``0.0``, and earns the barren weight (a little over half);
    * a branch that has **refined nothing** has *no* rate at all
      (:attr:`success_rate` is ``None``) and weighs the target's weight exactly
      — it is assumed to sit where the informative trials are, because §428's
      complaint is precisely that a planner which scored it as exhausted could
      not tell it from a theme that really is.

    The two are asserted to be *different* weights, not merely different
    derivations, because a seam that answered the same number for both would
    still be unable to tell them apart.
    """
    unmeasured = _branch(refinements=0, succeeded=0)
    measured_barren = _branch(refinements=4, succeeded=0)

    assert unmeasured.success_rate is None
    assert unmeasured.weight == discovery.TARGET_WEIGHT
    assert unmeasured.weight == 1.0

    assert measured_barren.success_rate == 0.0
    assert measured_barren.weight < 1.0
    assert unmeasured.weight != measured_barren.weight

    # And a branch measured *at* the target weighs the same as the unmeasured
    # one — the assumption and the measurement coincide only where the
    # measurement lands on the target, which is the point of the assumption.
    assert _branch(refinements=10, succeeded=2).weight == unmeasured.weight


def test_a_branchs_weight_is_the_scalar_verb_applied_to_its_rate() -> None:
    """One kernel, two spellings — the per-branch property cannot drift.

    :attr:`BranchDifficulty.weight` delegates to :func:`difficulty_weight`
    rather than repeating the arithmetic, and this drives both over the same
    rates so that a rewrite of the kernel cannot leave the per-branch answer
    standing on its own.
    """
    for rate in (0.0, 0.1, 0.2, 0.35, 0.5, 0.9, 1.0):
        branch = _branch(theme_root="value", refinements=20, succeeded=int(20 * rate))
        assert branch.success_rate == pytest.approx(rate)
        assert branch.weight == pytest.approx(difficulty_weight(rate))
    # A rate no whole-number census can hit is still the same one kernel: 33
    # refinements is not a multiple of ten, so this is a different rational.
    assert _branch(refinements=33, succeeded=11).weight == pytest.approx(
        difficulty_weight(1 / 3)
    )


def test_a_branch_is_a_frozen_value_and_is_validated_at_construction() -> None:
    """Evidence is a recorded fact, so the value is frozen and self-checking.

    ``succeeded > refinements`` is refused because a rate above one is not a
    rate: every weight computed from it would be a weight earned by a
    measurement that cannot exist, and the refusal is cheaper than the mystery.
    """
    branch = _branch()
    with pytest.raises(FrozenInstanceError):
        branch.succeeded = 9  # type: ignore[misc]
    assert branch == BranchDifficulty(
        theme_root="momentum", refinements=10, succeeded=2
    )

    with pytest.raises(CampaignPlanningError):
        _branch(refinements=3, succeeded=4)
    # A census with zero successes over zero refinements is *unmeasured*, not
    # impossible — the branch nobody has probed.
    assert _branch(refinements=0, succeeded=0).weight == 1.0

    for bad in (True, -1, 2.0, "10"):
        with pytest.raises(CampaignPlanningError):
            BranchDifficulty(theme_root="momentum", refinements=bad, succeeded=0)  # type: ignore[arg-type]
        with pytest.raises(CampaignPlanningError):
            BranchDifficulty(theme_root="momentum", refinements=10, succeeded=bad)  # type: ignore[arg-type]

    for bad_theme in ("", "   ", None, 7):
        with pytest.raises(CampaignPlanningError):
            BranchDifficulty(theme_root=bad_theme, refinements=1, succeeded=0)  # type: ignore[arg-type]


def test_the_theme_root_is_allowed_to_be_any_slug_including_an_unknown_one() -> None:
    """Which themes are *legal* is feature 241's, and restating it here drifts.

    The refusal on a key is structural — non-empty text — and an unknown theme
    is emphatically **not** an error: a deployment's configured legal set is a
    config law whose owner is feature 241, and a second spelling of it here
    would be the drift the two features exist to prevent.  So a theme no
    campaign has ever planted still measures a rate and earns a weight.
    """
    branch = _branch(theme_root="a-theme-no-campaign-has-used", refinements=10, succeeded=2)
    assert branch.weight == 1.0


# -- The allocation: the budget, conserved and spent by difficulty -------------


def test_the_allocation_conserves_the_plans_whole_budget_exactly() -> None:
    """The plan's ``branch_count * refine_count`` refinements, all of them.

    An allocation that quietly dropped a refinement would be this feature
    spending less than the campaign was planned at; one that invented a
    refinement would be spending more.  The census here is deliberately
    *fractional* — five branches of unequal weight against a budget of ``1``, so
    every exact quota is below one and flooring alone would assign nothing
    while the correction has to hand the single unit to the heaviest remainder.
    A rewrite that kept the largest-remainder spelling but lost the arithmetic
    fails on the total.

    The budget is also read back through :attr:`DepthAllocation.total`, which is
    *derived* from the depths rather than carried beside them — so the value
    cannot disagree with itself about how much depth it is spending.
    """
    census = [
        _branch(theme_root="alpha", refinements=10, succeeded=2),
        _branch(theme_root="beta", refinements=10, succeeded=4),
        _branch(theme_root="gamma", refinements=10, succeeded=1),
        _branch(theme_root="delta", refinements=10, succeeded=0),
        _branch(theme_root="epsilon", refinements=0, succeeded=0),
    ]
    plan = GridPlan(branch_count=5, refine_count=1)
    allocation = allocate_depth(plan, census)
    assert set(allocation.depths) == {
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
    }
    assert allocation.total == 5 * 1
    assert sum(allocation.depths.values()) == plan.branch_count * plan.refine_count

    # The same law over budgets that do not divide, and over a census whose
    # every weight differs.
    for budget in (1, 3, 7, 13, 30, 401):
        plan = GridPlan(branch_count=len(census), refine_count=budget)
        allocation = allocate_depth(plan, census)
        assert allocation.total == len(census) * budget, budget


def test_depth_flows_to_the_frontier_and_away_from_the_two_dead_ends() -> None:
    """PRD §434's whole sentence, as one allocation.

    *"Depth flows to branches sitting at the edge of what the discovery agent
    can actually do, which is where the informative trials are."*  Three
    branches, one per regime — saturated, at the frontier, and barren — under an
    even split of ``10`` each, so a feature that ignored difficulty would return
    ``(10, 10, 10)`` and a feature that favoured an axis would return something
    monotone in the rate.  Neither is what §434 asks for, and both are excluded
    by the assertions below.
    """
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=10),
        _branch(theme_root="frontier", refinements=10, succeeded=2),
        _branch(theme_root="barren", refinements=10, succeeded=0),
    ]
    depths = allocate_depth(GridPlan(branch_count=3, refine_count=10), census).depths
    # The frontier takes the most; a *measured* and barren branch sits next; the
    # saturated branch takes least of all.  Note that barren is *not* below the
    # even split: a measured-and-barren branch weighs exp(-0.5) ≈ 0.607 while a
    # saturated one weighs exp(-8) ≈ 0.00034, so the barren branch's share of
    # the two surviving weights (0.607 / 1.607 ≈ 0.378) of a 30-refinement
    # budget is about 11 — a shade *above* 10.  That is §434's asymmetry made
    # arithmetic: saturation is eliminated while barrenness is only penalised,
    # because a branch nothing has succeeded in may simply not have been probed
    # in the right direction yet.
    assert depths["frontier"] > depths["barren"] > depths["saturated"]
    assert depths["frontier"] > 10  # more than the even split
    assert depths["saturated"] < 10
    assert sum(depths.values()) == 30
    # The even split this is read against — what a feature with no notion of
    # difficulty would have returned.
    assert len({*depths.values()}) > 1


def test_a_lone_dead_end_branch_keeps_its_allocations_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two branches, neither at the target: the allocation is still a proportion.

    The case that pins the kernel's *relative* behaviour rather than its
    absolute one.  With no branch near ``p*`` the weights are small but their
    ratio is unchanged — a barren branch weighs about sixteen times a saturated
    one under the stated band — so the whole budget is split in that ratio
    rather than collapsing.  That is what makes the feature a *targeting* rule
    rather than a threshold: a deployment whose branches are all far from the
    frontier still gets a proportional split, not a refusal.
    """
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=10),
        _branch(theme_root="barren", refinements=10, succeeded=0),
    ]
    depths = allocate_depth(GridPlan(branch_count=2, refine_count=10), census).depths
    assert depths["saturated"] == 0  # ~1800× lighter, so it floors away
    assert depths["barren"] == 20
    assert sum(depths.values()) == 20  # the budget is conserved regardless


def test_weights_summing_to_zero_is_refused_rather_than_dividing_by_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The apportionment's one guard, and the path that reaches it.

    Every census taken under the *stated* band has a strictly positive weight
    sum — the minimum weight at the far end of the rate range is
    ``exp(−(1 − p*)²/2σ²)``, nowhere near an underflow — but the band is a named
    constant the module documents as the knob a deployment's tuning replaces,
    and a narrow enough band makes ``exp`` of a large negative number exactly
    ``0.0``.  So the guard is *reachable*, and this drives it: a narrowed band,
    a census with **no** branch near the target (a branch sitting at the target
    would weigh ``1.0`` under any band and keep the sum positive, which is why
    the earlier probe of this path was inconclusive), and the assertion that the
    refusal is this member's own class rather than a leaked
    :class:`ZeroDivisionError`.

    ``monkeypatch.setattr`` rather than a bare assignment, so the band is
    restored even if the assertion fails — a test that narrowed a module global
    and did not put it back would poison every test after it.
    """
    monkeypatch.setattr(discovery.difficulty, "DIFFICULTY_BAND", 1e-9)
    census = [
        _branch(theme_root="alpha", refinements=10, succeeded=5),
        _branch(theme_root="beta", refinements=10, succeeded=6),
    ]
    # The precondition this test exists for: the weights really do underflow.
    assert [branch.weight for branch in census] == [0.0, 0.0]

    with pytest.raises(CampaignPlanningError):
        allocate_depth(GridPlan(branch_count=2, refine_count=10), census)
    # And it is catchable by the member's one base class, not a ZeroDivisionError
    # escaping the seam.
    with pytest.raises(DiscoveryError):
        allocate_depth(GridPlan(branch_count=2, refine_count=10), census)


def test_the_split_is_proportional_to_the_weights_not_merely_ordered() -> None:
    """The allocation is the weights' proportions, to within one unit each.

    Ordering alone would be satisfied by any monotone rule; the feature's
    sentence says *"in proportion to difficulty"*, so the quotas are asserted
    against the weights computed here from the census.  The tolerance is one
    refinement per branch, which is exactly what the largest-remainder
    correction can move — the floors are exact, and the leftover units are
    fewer than the branches.
    """
    census = [
        _branch(theme_root="alpha", refinements=10, succeeded=2),
        _branch(theme_root="beta", refinements=10, succeeded=6),
        _branch(theme_root="gamma", refinements=10, succeeded=0),
    ]
    budget = 300
    plan = GridPlan(branch_count=3, refine_count=100)
    depths = allocate_depth(plan, census).depths

    total_weight = sum(branch.weight for branch in census)
    for branch in census:
        expected = budget * branch.weight / total_weight
        assert abs(depths[branch.theme_root] - expected) <= 1, branch.theme_root


def test_a_branch_the_allocation_gives_nothing_is_present_at_zero() -> None:
    """A saturated branch loses its allocation and stays a branch of the campaign.

    Absence would be a *second* statement — *this branch was not considered* —
    and it is exactly the statement the feature must not make about the branch
    it just indicted.  The value's mapping carries every branch the census
    named, so feature 237's own rule can find the saturated branch here to
    reduce.

    The threshold is the stated band's, not a transcribed one: with the band at
    the target, ``p = 1.0`` weighs ``exp(-8) ≈ 0.00034`` against a census whose
    other weights are near ``1``, so the saturated branch's quota floors to zero
    while its entry remains.
    """
    census = [
        _branch(theme_root="saturated", refinements=10, succeeded=10),
        _branch(theme_root="frontier", refinements=10, succeeded=2),
    ]
    allocation = allocate_depth(GridPlan(branch_count=2, refine_count=10), census)
    assert allocation.depths["saturated"] == 0
    assert "saturated" in allocation.depths
    assert allocation.total == 20


def test_an_allocation_is_a_frozen_value_compared_and_hashed_by_its_split() -> None:
    """A caller has to compare the split it made with the split a record ran under.

    Frozen, like :class:`~discovery.grid.GridPlan` and for the same reason: an
    allocation is a *decision* a campaign's depth is spent under, so a caller
    that could edit it afterwards would hold a different campaign than the
    evidence justified.  Hashable too, because keying a campaign's provenance by
    the split it ran under is the natural use — and the hash is spelled over the
    *sorted* items, so two allocations over one split hash alike whatever order
    their branches arrived in.
    """
    census = [
        _branch(theme_root="alpha", refinements=10, succeeded=2),
        _branch(theme_root="beta", refinements=10, succeeded=6),
    ]
    plan = GridPlan(branch_count=2, refine_count=15)
    first = allocate_depth(plan, census)
    second = allocate_depth(plan, list(reversed(census)))
    assert first == second
    assert hash(first) == hash(second)
    assert first != allocate_depth(GridPlan(branch_count=2, refine_count=14), census)

    with pytest.raises(FrozenInstanceError):
        first.depths = {}  # type: ignore[misc]

    # The mapping is a read-only *copy*: a caller that keeps writing its own
    # dict cannot move an allocation already made.
    authored = {"alpha": 3, "beta": 4}
    value = DepthAllocation(depths=authored)
    authored["alpha"] = 99
    assert value.depths["alpha"] == 3
    with pytest.raises(TypeError):
        value.depths["alpha"] = 99  # type: ignore[index]


@pytest.mark.parametrize(
    "counts",
    [
        {"alpha": -1},
        {"alpha": True},
        {"alpha": 2.0},
        {"alpha": "3"},
        {"": 3},
    ],
)
def test_an_allocation_that_is_not_a_split_of_counts_is_refused(counts: dict) -> None:
    """A depth is a count of refinements, and a branch needs a name to key it by.

    ``True`` is not one refinement — the SQLite affinity trap this workspace
    guards elsewhere — and a float is not a whole number of refinements a tree
    could walk.  The same checks feature 235 applies to its plan's counts,
    restated at the allocation.
    """
    with pytest.raises(CampaignPlanningError):
        DepthAllocation(depths=counts)


def test_an_allocation_that_is_not_a_mapping_is_refused() -> None:
    """A split keyed by nothing names no branch, whatever the type is called."""
    with pytest.raises(CampaignPlanningError):
        DepthAllocation(depths=[("alpha", 3)])  # type: ignore[arg-type]


# -- The ask: malformed requests, in the member's existing class ---------------


def test_a_plan_without_its_two_counts_is_refused_naming_every_one() -> None:
    """A missing read is a malformed request, not a bug in the allocation.

    The two counts are taken by name rather than by type, and a seam that let an
    ``AttributeError`` escape would present a malformed request as a defect in
    this module.  Every missing name is named at once — the "name every
    offender" discipline this member's grid derivation, theme batch and manifest
    gate all state.
    """

    class Nothing:
        pass

    with pytest.raises(CampaignPlanningError) as refusal:
        allocate_depth(Nothing(), [_branch()])
    message = str(refusal.value)
    for name in ("branch_count", "refine_count"):
        assert name in message


@pytest.mark.parametrize(
    "counts",
    [
        {"branch_count": True, "refine_count": 10},
        {"branch_count": 10, "refine_count": True},
        {"branch_count": 3.0, "refine_count": 10},
        {"branch_count": -1, "refine_count": 10},
        {"branch_count": 3, "refine_count": -4},
        {"branch_count": "3", "refine_count": 10},
    ],
)
def test_a_plan_count_that_is_not_a_count_is_refused(counts: dict) -> None:
    """A plan's two counts are counts, judged by the same law as feature 235's.

    Driven through a duck-typed stand-in rather than feature 235's real value,
    because 235's constructor would already have refused these — which is the
    wrong seam under test.  What is under test is this module's own judgement of
    a plan authored *anywhere*, including by the policy-runtime member whose
    value feature 229's law admits and this module must therefore also judge.
    """

    class Plan:
        def __init__(self, branch_count: object, refine_count: object) -> None:
            self.branch_count = branch_count
            self.refine_count = refine_count

    with pytest.raises(CampaignPlanningError):
        allocate_depth(Plan(**counts), [_branch()])


@pytest.mark.parametrize("census", ["not a census", b"not a census", 7, None])
def test_a_census_that_is_not_a_batch_is_refused(census: object) -> None:
    """A string is refused rather than iterated into characters.

    The guard features 235 and 241 state for a batch, and here it matters for
    the same sharp reason: a string read as a batch would hand the allocation
    one branch per character, and the refusal would arrive as a mangled
    *branch* rather than as *"that is not a batch"* — an operator told the wrong
    thing about the wrong value.
    """
    with pytest.raises(CampaignPlanningError):
        allocate_depth(GridPlan(branch_count=1, refine_count=1), census)


def test_a_census_entry_that_is_not_a_branch_is_refused_with_its_position() -> None:
    """A dict is not a measurement of a branch's refinements.

    The refusal names the position, the same way feature 235's adapter does,
    because a census of several branches is exactly the case where *"something
    in there is wrong"* is not a repair.  A bare branch, on the other hand, is
    accepted and wrapped: a caller projecting one branch is a legitimate caller.
    """
    raw = [_branch(theme_root="alpha"), {"refinements": 4}, _branch(theme_root="beta")]
    with pytest.raises(CampaignPlanningError) as refusal:
        allocate_depth(GridPlan(branch_count=3, refine_count=5), raw)
    assert "1" in str(refusal.value)

    wrapped = allocate_depth(GridPlan(branch_count=1, refine_count=7), _branch())
    assert wrapped.total == 7


def test_an_empty_census_is_refused_rather_than_allocated() -> None:
    """An allocation is *per branch*, and a batch of none names no branch.

    Deliberately **not** feature 235's empty-history path.  There, no evidence
    is a deployment that has never run a campaign and still needs a grid;
    here, there is a grid and nothing to spend it on, and answering a
    zero-depth allocation instead would report a caller's mistake as a decision
    about a campaign.
    """
    with pytest.raises(CampaignPlanningError) as refusal:
        allocate_depth(GridPlan(branch_count=3, refine_count=10), [])
    assert "branch" in str(refusal.value)


def test_a_theme_root_named_twice_is_refused_naming_every_repeat() -> None:
    """The theme root is the branch's identity, so two entries cannot be split.

    The mapping would silently keep whichever landed second, so the allocation
    would report one branch's depth as another's and the caller would have no
    way to see that it had.  Every repeat is named, so a caller repairs the
    whole census rather than meeting its offenders one resubmission at a time.
    """
    census = [
        _branch(theme_root="alpha", refinements=10, succeeded=2),
        _branch(theme_root="beta", refinements=10, succeeded=4),
        _branch(theme_root="alpha", refinements=6, succeeded=1),
    ]
    with pytest.raises(CampaignPlanningError) as refusal:
        allocate_depth(GridPlan(branch_count=3, refine_count=10), census)
    message = str(refusal.value)
    assert "alpha" in message
    assert "beta" not in message


def test_feature_236_adds_no_error_class_of_its_own() -> None:
    """Every refusal is a fact about the request, so it wears the ask's class.

    A rate that is not a proportion, a plan that does not carry its counts, a
    census with no branch in it — none is fixed by anything but re-considering
    what was asked for, which is what
    :class:`~discovery.errors.CampaignPlanningError` is for.  So the module
    defines no new class, and every refusal is catchable by the member's one
    base class: a caller's single ``except DiscoveryError`` still catches
    everything this feature can say.
    """
    for drive in (
        lambda: difficulty_weight(1.5),
        lambda: difficulty_weight(True),
        lambda: BranchDifficulty(theme_root="momentum", refinements=2, succeeded=3),
        lambda: allocate_depth(object(), [_branch()]),
        lambda: allocate_depth(GridPlan(branch_count=2, refine_count=3), []),
        lambda: DepthAllocation(depths={"alpha": -1}),
    ):
        with pytest.raises(CampaignPlanningError):
            drive()
        with pytest.raises(DiscoveryError):
            drive()


# -- The seam: this module takes the budget feature 235 derived ---------------


def test_the_allocation_spends_the_grid_feature_235_derived() -> None:
    """The two features compose: 235 authors the budget, 236 splits it.

    The seam feature 235's own docstring names — *"Features 236 and 237 then
    skew this base grid per branch, by difficulty and by saturation"* — driven
    end to end: a converged history is rebalanced to a flat grid by 235, and
    that grid's whole budget is then apportioned across a census by 236, with
    nothing lost in between.  That is what makes 235's *flat base* worthwhile:
    the per-branch skew is a correction of the evidence rather than of the
    derivation's opinion.
    """
    from discovery import CampaignManifest, PlanContext

    history = CampaignManifest(
        campaign_id=str(uuid_module.uuid4()),
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
        _branch(theme_root="saturated", refinements=10, succeeded=10),
        _branch(theme_root="frontier", refinements=10, succeeded=2),
        _branch(theme_root="barren", refinements=10, succeeded=0),
    ]
    allocation = allocate_depth(plan, census)
    assert allocation.total == plan.branch_count * plan.refine_count
    assert allocation.total == 20 * 20


def test_a_plan_read_by_name_lets_the_policy_runtimes_value_fill_the_budget() -> None:
    """The reads are taken **by name**, so the sibling member's plan allocates too.

    No member imports another, so the two spellings of the plan value this
    workspace holds — this member's :class:`~discovery.grid.GridPlan` and the
    policy-runtime member's, which feature 229's admission law judges — are two
    classes.  A policy's admitted plan has to fill this allocation's budget
    without a conversion, which only works if the reads are duck-typed.  The
    check is against the sibling's **real** value rather than a stand-in, so it
    is evidence about the seam rather than about a coincidence of shape.

    The import is inside the test, and ``importorskip`` with it, so a workspace
    without the policy-runtime member degrades one test rather than failing the
    collection of this suite — the discipline
    ``packages/discovery/tests/test_cross_member.py`` states for its own pins.
    """
    repo_root = Path(__file__).resolve().parents[3]
    sibling_src = repo_root / "packages" / "policy-runtime" / "src"
    if str(sibling_src) not in sys.path:
        sys.path.insert(0, str(sibling_src))
    policy_runtime = pytest.importorskip(
        "policy_runtime", reason="the policy-runtime member is not in this workspace"
    )

    foreign = policy_runtime.GridPlan(branch_count=4, refine_count=9)
    census = [_branch(theme_root=f"theme-{index}") for index in range(4)]
    allocation = allocate_depth(foreign, census)
    assert allocation.total == 4 * 9

    # And the two spellings answer the same split, since a plan is its counts.
    assert allocation == allocate_depth(GridPlan(branch_count=4, refine_count=9), census)


# -- The shape: no component, no store, no float literal in the kernel ---------


def test_no_component_is_registered_by_this_feature() -> None:
    """Feature 236 adds no ``@register`` — the member still registers one name.

    A builder takes no arguments and is discovered by the factory; this
    allocation is a function of a plan and a census the factory holds neither
    of, and the census is *current-episode* evidence — the one thing feature
    233's boundary forbids a composition-time object to reach.  A component
    appears here as a *builder* in the package namespace, which is what this
    asserts is absent.
    """
    assert isinstance(discovery.COMPONENT_NAME, str)
    builders = [
        name
        for name in dir(discovery)
        if name.startswith("build_") and "difficult" in name
    ]
    assert builders == []
    assert callable(discovery.allocate_depth)
    assert callable(discovery.difficulty_weight)


def test_the_seam_reads_no_store_and_opens_no_file() -> None:
    """Feature 236 is pure — the suite needs no fixture, and that is the claim.

    The census reaches the allocation the only way the spec allows: counted
    from the caller's prefix view and handed in.  So the allocation consults no
    ``DATABASE_URL`` and touches no file, which is why this whole suite runs
    without a fixture — and why the module is import-cheap for the factory's
    scan.

    The check reads the module's **imports and code literals by AST**, not by
    substring over the file text: the docstring argues at length about the store
    this module does *not* touch, so a naive ``"sqlite3" in source`` test would
    fail on the module's own honest prose.
    """
    tree = ast.parse(Path(discovery.difficulty.__file__).read_text())
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


def test_the_apportionment_compares_quotas_as_exact_rationals() -> None:
    """No rounding mode can move an allocated refinement.

    Every other count in this member is derived in integer arithmetic for the
    same reason feature 235 states — *"a census is a count and the plan derived
    from it is a count"* — but this module's kernel returns a float by
    definition, so the discipline is applied one layer down: the weights are
    lifted to :class:`~fractions.Fraction` *exactly* (``Fraction(a_float)`` is
    the float's exact value, not an approximation), and the quotients, floors
    and tie-breaking remainders are compared as rationals rather than by a
    rounding mode.

    Two halves, and they are about different inputs:

    * **a near-tie** — two branches whose rates differ by about a part in
      ``10⁵`` (a census of 40000 successes over 199999 refinements against one
      at exactly the target), so their weights differ in the twelfth decimal
      and only exact comparison settles which is heavier.  The heavier one is
      the *rounded-up* census, asserted rather than merely deterministic,
      because a rounding-mode-dependent comparison could plausibly have picked
      either;
    * **a genuine tie** — three branches that weigh *identically*, against a
      budget that leaves units over.  Here no arithmetic can decide, so the
      tie-break falls to the theme root, and the assertion is that the split is
      the same however the census was assembled — which is what makes an
      allocation a decision a campaign can be reproduced under.
    """
    near = [
        _branch(theme_root="above", refinements=199999, succeeded=40000),
        _branch(theme_root="at", refinements=10, succeeded=2),
    ]
    assert near[0].weight != near[1].weight
    assert near[1].weight == 1.0  # exactly at the target
    assert near[0].weight < 1.0  # the rounded-up rate sits just past it

    plan = GridPlan(branch_count=2, refine_count=1)
    first = allocate_depth(plan, near)
    assert first.total == 2
    assert first == allocate_depth(plan, list(reversed(near)))

    # The genuine tie: identical weights, so the tie-break is the only thing
    # that can decide, and it must not depend on the order of the census.
    tied = [_branch(theme_root=theme) for theme in ("gamma", "alpha", "beta")]
    for order in (tied, list(reversed(tied)), [tied[2], tied[0], tied[1]]):
        assert allocate_depth(GridPlan(branch_count=2, refine_count=1), order) == (
            allocate_depth(GridPlan(branch_count=2, refine_count=1), tied)
        )
    # The unit the tie left over lands on the theme root that sorts first, not
    # on whichever branch happened to be visited first.
    split = allocate_depth(GridPlan(branch_count=2, refine_count=1), tied).depths
    assert split["alpha"] > split["gamma"]
    assert split["alpha"] == split["beta"]
