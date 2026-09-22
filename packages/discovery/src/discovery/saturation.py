"""The saturation response — feature 237.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 237: *System reduces
allocation for a saturated branch where nearly every refinement succeeds, which
returns a lowered depth budget.*  PRD §434 states the fact this rule answers, in
the same sentence :mod:`discovery.difficulty` is built on:

    A branch where nearly every refinement succeeds is saturated and loses
    allocation; one where nothing succeeds is beyond the agent's frontier and
    also loses it.

**237 is a level, and that is the whole of why it needs to exist beside 236.**
Feature 236's kernel is *relative*: it ranks the branches against one another
and apportions the plan's budget in proportion to the weights they earned.  A
proportional split is scale-free — multiplying every weight in a census by any
positive constant leaves the allocation identical — and that is deliberate,
because §428's complaint is about telling *an exhausted theme from an
unexplored one*, which is a comparison between branches.  The consequence this
module exists for is one line of arithmetic away and worth stating plainly:
**236 cannot lower a budget it ranked uniformly.**  A census of two branches
that both succeeded at every refinement of ten weighs ``exp(−8) ≈ 0.00034``
each, so 236 hands them the even split — half the campaign's refinements each —
and a campaign that has already seen everything those two branches can show
spends all of its depth on them.  The kernel ranked them correctly and had no
way to spend less, because "nearly every refinement succeeds" is a fact about
*one branch* rather than about a comparison between branches.

So this module's rule is absolute where 236's is proportional:
:func:`is_saturated` judges a single branch's measured rate against
:data:`SATURATION_RATE`, and :func:`reduce_saturated` lowers the depth
:class:`~discovery.difficulty.DepthAllocation` gave every branch that answers
yes, by the stated retention :data:`SATURATION_RETENTION`.  The two seams
compose in one direction — 236's allocation in, a lowered one out — and the
orchestrator's order is the order feature 235's own docstring names: derive the
flat grid, skew it per branch by difficulty, then respond to what is saturated.

**The window where this rule bites is narrow, and it is worth naming exactly.**
Feature 236's kernel is not merely relative, it is steep: at the stated band a
saturated branch weighs three orders of magnitude below a frontier one, so a
census mixing the two hands the saturated branch a quota that floors to zero on
236's own arithmetic — ``p = 1.0`` beside ``p = 0.2`` weighs
``exp(−8) ≈ 0.00034`` against ``1.0``, and no budget a campaign is planned at
recovers a whole refinement from that ratio.  So a caller should not expect this
module to be the thing that lowers a saturated branch sitting beside a healthy
one; 236 already did.  What this module lowers is the case 236 provably cannot
reach: a census whose branches are **all** far from the target, where the
proportional split is non-degenerate and every branch keeps a real share of the
budget.  That is not a corner — it is exactly the campaign PRD §428's complaint
describes, where a theme has been driven to exhaustion and the history can no
longer tell it from a fresh one — and it is the one shape where the feature's
*"returns a lowered depth budget"* is a statement only this rule can make.  The
suite drives both windows, and asserts the second one explicitly rather than
leaving it as the accident of a chosen census.

**"A lowered depth budget" is the return value, and the depth freed is not
re-spent.**  The feature's sentence names what comes back: an allocation whose
:attr:`~discovery.difficulty.DepthAllocation.total` is *smaller* than the split
it was made from.  This module deliberately does not hand the reduction to the
frontier branches, and the reason is a division of labour rather than an
omission: redistributing the freed depth is precisely what 236's proportional
apportionment is for — it is the mechanism that spends a budget where the
evidence says the informative trials are — while 237's contribution is the
statement that a campaign with a saturated branch has *less* worth spending
than the plan assumed.  A plan is the grid a campaign is opened with, and its
budget is the most a campaign may spend rather than a quantity it owes the
tree.  Handing the freed units to a frontier branch here would also make this
module a second apportionment rule, competing with 236's about the same units.

**The threshold and the retention are named defaults, and no document states
either.**  PRD §428's whole vocabulary for this rule is *"nearly every
refinement succeeds"* — no rate and no fraction — so
:data:`SATURATION_RATE` and :data:`SATURATION_RETENTION` are stated as named
constants with their consequences written out in their own comments, the stance
feature 236 takes for ``DIFFICULTY_BAND``, feature 228 for ``PRIOR_STRENGTH``
and feature 227 for its bands: a knob the dreaming loop's own tuning replaces,
presented as a knob rather than as an invented law.  Both are read *at call
time*, so a deployment that replaces either — or a test that pins the
arithmetic at another value — moves every verb in this module together, and
:func:`_validated_knobs` refuses a replacement outside ``[0, 1]`` rather than
letting a mis-set knob silently turn the reduction into an inflation.

**The reduction is a step in the rate, and that is forced rather than chosen.**
A smooth response — a second multiplier fading in as the rate climbs — would
lower the allocation of a branch at *every* rate, which contradicts the
feature's sentence: the reduction is *for a saturated branch*, and §434's
*"loses allocation"* is what the kernel already does to a branch that is merely
far from the target.  So the response is a threshold, and the discontinuity at
it is bounded by one branch's retention rather than by the campaign's budget.
What that costs at the stated knobs is written down here rather than left to be
derived: a branch at ``p = 0.8`` sits at ``exp(−4.5) ≈ 0.0111`` of the
kernel's maximum, so the threshold is the rate below which 236 has stopped
being able to say much about a branch in its own vocabulary either; and a
branch allocated a single refinement keeps ``floor(1 × 0.5) = 0`` of it, which
is the floor-to-zero 236's own docstring already names as saturation's
reading.

**The census law is feature 236's, reused rather than restated.**
:func:`reduce_saturated` validates the batch it is handed through
:func:`discovery.difficulty._validated_census` — the *same* function 236's
allocation is made through — because the census here is not *like* 236's
census, it is the very evidence the split was apportioned from: a second
validator would be a second law for one batch, and the drift would show up as
two seams disagreeing about what a branch census is.  The refusals therefore
carry 236's vocabulary, which is the right vocabulary: a malformed census is
malformed before it reaches either verb.

**The allocation and the census must name the same branches.**  This is the one
check this module adds, and it is the reason it takes an allocation rather than
re-deriving one.  A reduction is applied to *a* split by *the* evidence that
justifies it, and the two ways of getting that wrong are both silent if
unchecked: a branch the split gave depth to but the census does not measure
would keep an allocation whose saturation nothing judged (which is *not* the
same as judging it unsaturated — the unmeasured case is a statement about
evidence, and inventing one here is what feature 236's ``TARGET_WEIGHT``
refuses), and a branch the census measured but the split does not carry would
be a reduction with no depth to reduce, which means the two came from different
campaigns.  Both are refused, and every disagreeing theme root is named at once.

**The unmeasured branch is not a saturated one, and neither is a barren one.**
:func:`is_saturated` answers ``False`` for a branch that has refined nothing —
its :attr:`~discovery.difficulty.BranchDifficulty.success_rate` is ``None``,
and ``None`` is not a rate above any threshold — which is 236's asymmetry read
from this feature's side: no evidence is not evidence of exhaustion, and the
one place the frontier might be is the one place a reduction must not reach.
A *barren* branch is not saturated either: it has a rate, it is ``0.0``, and
§434 gives it to the kernel, which penalises it and does not eliminate it.

**No component, no I/O, and no new error class.**  :func:`reduce_saturated` is
feature 236's reason one level further down: it closes over no deployment
state, opens no table, writes no row, and — like 236 and unlike 235 — reads the
*current episode's* revealed refinements, which is the one thing feature 233's
prior-manifests-only boundary forbids a planning step from reaching.  A
registered component pointed at that would be a builder for an episode
composition cannot supply.  Every refusal is a fact about the request — a
threshold or a retention outside ``[0, 1]``, a value that is not an allocation,
a malformed census, an allocation and a census that disagree — so all of them
are :class:`~discovery.errors.CampaignPlanningError`, the member's *"the
request cannot be planned"* class, and the same split-by-repair decision 236
states for the allocation it hands this module.  Stdlib only, and import-cheap:
:mod:`numbers`, :mod:`fractions` and this member's own two modules, with no
third-party import at module scope.

**What this module is not.**  It is a step in a pipeline rather than a
fixpoint: :func:`reduce_saturated` lowers the split it is handed, and a caller
that hands it the *result* of a previous call lowers that again.  Nothing here
detects re-application, because a
:class:`~discovery.difficulty.DepthAllocation` is a split and carries no record
of how it was arrived at — which is why the correspondence check above earns
its place instead: the mis-application that is worth catching is one split
lowered by another campaign's evidence, and that one is caught by name.  The
orchestrator applies this step once per campaign, in the order 235 → 236 → 237.
"""

from __future__ import annotations

import math
import numbers
from fractions import Fraction
from typing import Any

from .difficulty import BranchDifficulty, DepthAllocation, _validated_census
from .errors import CampaignPlanningError

__all__ = [
    "SATURATION_RATE",
    "SATURATION_RETENTION",
    "is_saturated",
    "reduce_saturated",
]

#: The per-branch success rate at or above which a branch is *saturated* — the
#: "nearly every refinement succeeds" PRD §434 names in words and fixes with no
#: number, so this is a **named default** in the sense
#: :data:`~discovery.difficulty.DIFFICULTY_BAND` is one: a knob the dreaming
#: loop's own tuning replaces rather than a law, because no document states it.
#:
#: ``0.8`` is where the kernel has already stopped saying much about a branch in
#: its own vocabulary: under 236's stated band a branch at this rate weighs
#: ``exp(−(0.8 − 0.2)² / 2(0.2)²) = exp(−4.5) ≈ 0.0111`` against a weight of
#: ``1.0`` at the target, so a saturated branch keeps about one percent of the
#: frontier's share before this module touches it.  What this constant adds is
#: not the ranking — 236 owns that — but the fact that the threshold is a
#: statement about *one* branch, so it lowers the budget even when every branch
#: in the census sits above it.
#:
#: The comparison is **inclusive**: a branch at exactly this rate is saturated.
#: The boundary has to belong to one side or the other, and "nearly every
#: refinement succeeds" reads as a floor on the rate rather than as a strict one
#: — four successes in five is the least that phrase describes.
SATURATION_RATE = 0.8

#: What a saturated branch **keeps** of the depth feature 236 allocated it.  A
#: retention rather than a reduction because that is the form which cannot
#: invent depth: ``floor(depth × retention)`` is at most ``depth`` for every
#: retention in ``[0, 1]``, so the verb lowers and can never raise, and the
#: bound holds by the multiplication rather than by a check that could be
#: forgotten.
#:
#: ``0.5`` because the feature's word is *reduces* and halving is the plainest
#: reading of a reduction that keeps the branch in the campaign; PRD states no
#: number, so — like :data:`SATURATION_RATE` and like 236's band — this is a
#: named default a deployment replaces rather than a transcription.  What it
#: costs is worth writing down: a saturated branch allotted a single refinement
#: keeps ``floor(0.5) = 0`` of it and so is dropped to zero depth, while one
#: allotted ten keeps five.  A deployment that wants saturation *eliminated*
#: rather than reduced sets this to ``0.0`` and meets exactly that; one that
#: wants a gentler response raises it towards ``1.0``, at which point this
#: module's verb is the identity — the retention's own boundary, and the point
#: at which a deployment has said that saturation earns no response at all.
SATURATION_RETENTION = 0.5


def is_saturated(branch: Any) -> bool:
    """Whether *branch* is the branch this feature lowers.

    The feature's sentence read at one branch: *"a saturated branch where nearly
    every refinement succeeds"* — a branch whose measured
    :attr:`~discovery.difficulty.BranchDifficulty.success_rate` is at or above
    :data:`SATURATION_RATE`, judged against the threshold as it stands when the
    call is made, so a deployment's replacement moves this verb and
    :func:`reduce_saturated` together.  The *pair* of knobs is read and
    validated together — :func:`_validated_knobs` answers both — and that is
    deliberate rather than an unused read: the two constants are one
    parameterization of one rule, so a retention outside its range is as much a
    mis-set deployment here as a threshold is, and catching it at the predicate
    as well as at the verb means the mistake is refused wherever a caller first
    touches this feature.

    Takes a :class:`~discovery.difficulty.BranchDifficulty` and **not** a bare
    rate, and the reason is the case the two answers differ on: a branch that
    has refined nothing has no rate at all — 236's
    :attr:`~discovery.difficulty.BranchDifficulty.success_rate` is ``None`` for
    it — and ``None`` is not a number above any threshold.  A verb over rates
    could not express that branch, so it would have to be handed one, and every
    choice for it (``0.0``, the target, a raise) is a claim about evidence
    nobody counted.  Answering ``False`` here is the claim 236 already makes
    from the other side: an unmeasured branch is *assumed to sit at* the
    target, which is the kernel's maximum, and the one branch this feature
    must not reduce is the one that has not yet shown whether it is the
    frontier.

    A *barren* branch answers ``False`` too, and it is not an oversight: it has
    a rate, that rate is ``0.0``, and §434 gives a branch where nothing
    succeeds to the kernel — which penalises it to a little over half its
    weight and does not eliminate it.  This module lowers one dead end, and it
    is the settled one.

    A value that is not a branch is refused rather than answered ``False``: a
    predicate that quietly called an arbitrary object unsaturated would be this
    seam reporting a caller's mistake as a judgment about evidence.  The
    refusal is :class:`~discovery.errors.CampaignPlanningError`, the class
    :func:`~discovery.difficulty._validated_census` refuses the same kind of
    value in — a value that is not a branch measures no rate, whether it
    arrives here or in a batch.
    """
    threshold, _retention = _validated_knobs()
    if not isinstance(branch, BranchDifficulty):
        raise CampaignPlanningError(
            f"a saturated branch is one of this member's branches, got "
            f"{branch!r} ({type(branch).__name__}); feature 237 reduces the depth "
            "a branch earns when nearly every refinement it attempted succeeded, "
            "and that judgement needs the theme root and the two counts a "
            "BranchDifficulty carries — a value that is not one has measured no "
            "rate to compare against the saturation threshold"
        )
    return _is_saturated_at(branch, threshold)


def reduce_saturated(allocation: Any, branches: Any) -> DepthAllocation:
    """Lower the depth a saturated branch was allocated — the feature's verb.

    Handed the :class:`~discovery.difficulty.DepthAllocation` feature 236
    apportioned and the per-branch census that allocation was made from, it
    returns an allocation in which every branch :func:`is_saturated` names keeps
    :data:`SATURATION_RETENTION` of its depth — floored, so the result is a
    whole number of refinements and never more than was allocated — and every
    other branch's depth is **unchanged, to the unit**.  The returned value's
    :attr:`~discovery.difficulty.DepthAllocation.total` is therefore the
    feature's *lowered depth budget*: the plan's budget less exactly what the
    saturated branches gave up, which is depth the campaign does not spend.

    The steps, in order, each refusal in the member's malformed-ask vocabulary:

    1. **the split is a depth allocation** — this member's own value, checked as
       one.  It is deliberately *not* duck-typed the way a plan is: feature 236
       reads ``branch_count`` and ``refine_count`` by name because the
       policy-runtime member spells a ``GridPlan`` of its own that no member may
       import, while a :class:`~discovery.difficulty.DepthAllocation` is this
       member's value alone — so there is no second spelling to admit, and a
       value that is not one is a caller's mistake rather than a sibling's
       vocabulary.
    2. **the census is feature 236's census** — validated by
       :func:`~discovery.difficulty._validated_census`, the *same* function the
       allocation was apportioned through, so the two seams cannot disagree
       about what a batch of branches is and both answer a malformed one with
       one vocabulary.
    3. **the two name the same branches** — see the module docstring; every
       theme root that appears in one and not the other is named, in both
       directions.
    4. **the reduction is applied** — ``floor(depth × retention)`` for each
       saturated branch, in exact rational arithmetic (``Fraction(depth) ×
       Fraction(retention)`` is the exact product of the two values, and the
       floor is taken from the numerator and denominator rather than from a
       floating-point rounding mode), so a retention whose binary value is not
       the decimal it was written as cannot move a refinement.
    5. **the counts law is applied once, at the value** — the result is
       constructed as a :class:`~discovery.difficulty.DepthAllocation`, which
       validates that every depth is a genuine non-negative integer.

    Three things this deliberately does **not** do.  It does not redistribute
    the freed depth onto the other branches — see the module docstring for why
    that is 236's mechanism and not this one's.  It does not require the census
    to name a saturated branch at all: a census with none returns a split equal
    to the one it was handed, because a response is not an obligation, and the
    common campaign is one where nothing has saturated.  And it does not refuse
    a branch that is already at zero depth — a branch 236 floored away is still
    a branch of the census, its entry is still present, and the arithmetic of
    ``floor(0 × retention) = 0`` says so without a special case.

    It reads no store and opens no file: the split arrives from feature 236's
    apportionment and the census from the caller's prefix walk.
    """
    threshold, retention = _validated_knobs()
    split = _validated_allocation(allocation)
    census = _validated_census(branches)
    _validated_correspondence(split, census)
    saturated = {
        branch.theme_root
        for branch in census
        if _is_saturated_at(branch, threshold)
    }
    return DepthAllocation(
        depths={
            theme_root: _reduced_depth(depth, theme_root in saturated, retention)
            for theme_root, depth in split.depths.items()
        }
    )


def _is_saturated_at(branch: BranchDifficulty, threshold: float) -> bool:
    """The saturation judgment at a threshold already read and validated.

    The one place the comparison is spelled, so that :func:`is_saturated` and
    :func:`reduce_saturated` cannot come to disagree about which branches this
    feature is about — the public predicate delegates here rather than restating
    it, the way a branch's weight delegates to 236's kernel.  It takes the
    threshold rather than reading the constant, because the verb judges a whole
    census and reads both knobs once: a batch judged while a replaced global
    changed underneath it would be a census half-judged by one threshold and
    half by another.
    """
    rate = branch.success_rate
    return rate is not None and rate >= threshold


def _reduced_depth(depth: int, saturated: bool, retention: Fraction) -> int:
    """What a branch keeps: all of it, or the retention floored, exactly.

    ``floor(depth × retention)`` in exact rational arithmetic for a saturated
    branch, and ``depth`` itself for every other branch — spelled as one
    expression so the *fact* that the reduction is a no-op off the saturated
    set is in the arithmetic rather than in a guard a rewrite could drop.

    ``Fraction(depth) × retention`` is exact: the retention arrives as the exact
    value of the constant the module was written with, so the product is the
    exact value of the two numbers rather than a rounded approximation of it,
    and the floor taken from ``numerator // denominator`` is the true floor for
    the non-negative rational the product is (both operands are non-negative,
    since a depth is and the retention is validated into ``[0, 1]``).  That is
    the discipline feature 236 states for its own apportionment, applied to a
    single multiplication: ``floor(10 × 0.3)`` is ``3`` in binary floating point
    and ``2`` as the exact number the constant was written as, and only the
    second is a reduction a campaign can be reproduced under.
    """
    if not saturated:
        return depth
    quota = Fraction(depth) * retention
    return quota.numerator // quota.denominator


def _validated_allocation(allocation: Any) -> DepthAllocation:
    """Refuse anything that is not the split feature 236 apportioned.

    Structural, and deliberately not duck-typed: see
    :func:`reduce_saturated` for why this member's own value is checked as one
    where a plan is read by name.  The refusal names the value, and it says
    which of the two things a caller reaching this seam holds is the wrong one
    — the allocation is what a reduction is applied *to*, and the census is
    what justifies it.
    """
    if not isinstance(allocation, DepthAllocation):
        raise CampaignPlanningError(
            f"a saturation response reduces a depth allocation, got "
            f"{allocation!r} ({type(allocation).__name__}); feature 237 lowers "
            "the depth a saturated branch earned out of the split feature 236 "
            "apportioned, and a value that is not one carries no per-branch "
            "depth to lower"
        )
    return allocation


def _validated_correspondence(
    allocation: DepthAllocation, census: tuple[BranchDifficulty, ...]
) -> None:
    """Refuse a split and a census that do not name the same branches.

    The check that makes the reduction a statement about *this* campaign.  A
    branch the split allocated depth to but the census does not measure would
    have its saturation unjudged, and the value would still come back looking
    like a decision — which is the silent failure mode: 236's
    ``TARGET_WEIGHT`` says an unmeasured branch sits *at* the target, so
    treating absent evidence as unsaturation understates what the response
    should have done, while treating it as saturation would be this module
    inventing the measurement.  A branch the census measures but the split does
    not carry is the mirror and is worse: there is nothing to reduce, so the
    caller is holding one campaign's allocation and another's evidence.

    **Every disagreeing theme root is named, in both directions**, so a caller
    that mixed two campaigns learns both halves of the difference in one
    refusal rather than one resubmission at a time — the discipline
    :func:`discovery.grid.derive_grid_plan` and
    :meth:`discovery.themes.ThemeSet.assign_all` both state.
    """
    allocated = set(allocation.depths)
    measured = {branch.theme_root for branch in census}
    unmeasured = sorted(allocated - measured)
    unallocated = sorted(measured - allocated)
    if not unmeasured and not unallocated:
        return
    complaints: list[str] = []
    if unmeasured:
        complaints.append(
            f"the allocation gives depth to {_listed(unmeasured)}, which the "
            "census does not measure"
        )
    if unallocated:
        complaints.append(
            f"the census measures {_listed(unallocated)}, which the allocation "
            "gives no depth to"
        )
    raise CampaignPlanningError(
        "; and ".join(complaints)
        + ". Feature 237 lowers a split by the evidence that justifies it, so "
        "the two must name the same branches: a branch with depth and no "
        "evidence has its saturation unjudged — which is not the same as "
        "judging it unsaturated — and a branch with evidence and no depth is a "
        "response to a campaign the split does not describe (feature 236 "
        "apportions the allocation across exactly the branches the census names)"
    )


def _listed(theme_roots: list[str]) -> str:
    """The theme roots of a complaint, each quoted once.

    Spelled out rather than inlined twice, so the two directions of
    :func:`_validated_correspondence` phrase their lists the same way — the
    habit :func:`discovery.difficulty._validated_census` states for its own
    repeated-theme refusal.
    """
    return ", ".join(repr(theme_root) for theme_root in theme_roots)


def _validated_knobs() -> tuple[float, Fraction]:
    """Read the two stated defaults, and refuse a pair outside ``[0, 1]``.

    Both constants are read here at **call time** rather than bound at import,
    so replacing either moves every verb in this module together; and both are
    checked, because either can be replaced.  The guard is this module's
    equivalent of the weight-sum guard feature 236 keeps in ``_apportioned``:
    unreachable through the stated defaults — ``0.8`` and ``0.5`` are both in
    range — but reachable by the deployment the constants' own comments invite
    to retune them, and a retention above ``1`` would make this module *raise* a
    budget where its sentence says it lowers one.

    The retention comes back as a :class:`~fractions.Fraction` because that is
    how :func:`_reduced_depth` multiplies with it; the rate comes back as a
    float because that is what a branch's ``success_rate`` is and what it is
    compared against.
    """
    rate = _validated_proportion(
        SATURATION_RATE,
        "SATURATION_RATE",
        "feature 237 marks a branch saturated when its success rate reaches this "
        "threshold, so a value outside [0, 1] is not a rate a branch could have "
        "measured",
    )
    retention = _validated_proportion(
        SATURATION_RETENTION,
        "SATURATION_RETENTION",
        "feature 237 lowers a saturated branch's depth by this retention, so a "
        "value outside [0, 1] would raise a budget rather than reduce it",
    )
    return rate, Fraction(retention)


def _validated_proportion(value: Any, name: str, why: str) -> float:
    """Refuse a knob that is not a proportion in ``[0, 1]``.

    The same shape as feature 236's :func:`~discovery.difficulty._validated_rate`
    — a ``bool`` is refused although it is an ``int`` (the SQLite affinity trap
    this workspace guards elsewhere: ``True`` would read as a threshold of one),
    a non-real is refused, and ``NaN`` is refused explicitly because every
    comparison against it is false, which would make a threshold nothing ever
    reaches or a retention nothing ever applies — only here the value being
    judged is the module's own constant rather than a caller's measurement, so
    the complaint names the constant and says what it is for.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise CampaignPlanningError(
            f"{name} must be a number, got {value!r} ({type(value).__name__}); "
            f"{why}"
        )
    proportion = float(value)
    if math.isnan(proportion) or not 0.0 <= proportion <= 1.0:
        raise CampaignPlanningError(
            f"{name} must lie in [0, 1], got {value!r}; {why}"
        )
    return proportion
