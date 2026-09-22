"""Frontier-difficulty depth allocation — feature 236.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 236: *System computes
a per-branch difficulty weight targeting a success rate near 0.2, which returns
a depth allocation favouring the agent frontier.*  PRD §428 states the mechanism
this borrows, and the formula is the whole of it:

    **Frontier-difficulty depth allocation.** ``plan_grid`` as originally
    specified chooses width versus depth from prior manifests but has no notion
    of difficulty targeting, so it cannot tell an exhausted theme from an
    unexplored one.  Borrow the mechanism from self-improving-model training:
    target a per-branch success rate near ``p* ≈ 0.2``.

    ``D(branch) = exp( −(p_branch − p*)² / 2σ² )      p* = 0.2``

and PRD §434 states what that shape buys, which is the property this module's
whole suite is written against:

    A branch where nearly every refinement succeeds is saturated and loses
    allocation; one where nothing succeeds is beyond the agent's frontier and
    also loses it.  Depth flows to branches sitting at the edge of what the
    discovery agent can actually do, which is where the informative trials are.
    Computable entirely from prefix information, and it drops into the same
    ``_schedule(beta)`` dict as every other threshold.

**Where this sits in the category, and why it is a third seam with no seat.**
Feature 235 authors the *flat* base grid — a branch count and a refinements-per-
branch count derived from the prior manifests — and says in as many words that
it does so deliberately: *"Features 236 and 237 then skew this base grid per
branch, by difficulty and by saturation; a base that already favoured an axis
would make their allocation a correction of this module's opinion rather than of
the evidence."*  That sentence is this feature's remit.  :func:`allocate_depth`
takes the :class:`~discovery.grid.GridPlan` 235 derived and redistributes the
depth budget it carries — ``branch_count * refine_count``, the campaign's whole
allocation of refinements — across the branches the caller's prefix has
measured, in proportion to each branch's difficulty weight.  Feature 237's own
rule (the saturated branch's *budget-level* reduction) is built on top of this
allocation and is not stated here.

It adds no ``@register``, and the reason is the member's now-familiar one rather
than a new one.  A component is *state a deployment holds* — a store, a
database, a pool — discovered by the factory and built by a builder that takes
no arguments; :func:`allocate_depth` closes over no deployment state at all: no
``DATABASE_URL``, no table, no file, no clock.  It is feature 241's *"a function
wearing a component's name"* in the form feature 235 states for the grid
derivation one level up, and the member's registered surface therefore stays
feature 232's single campaign store.

**The census is prefix information, and nothing here reads a score.**  A
branch's success rate is ``succeeded / refinements`` over the refinements the
prefix has already revealed — the caller counts them from feature 223's prefix
view and feature 218's observation surface, never from an unrevealed score
(feature 224's block and feature 235's *"no unrevealed scores"* are the same law
read from two sides).  A *failure* is as prefix-visible as a success here: the
count of refinements a branch attempted and the count that survived are both
facts about revealed nodes, so the difficulty weight is computable *before* the
campaign's depth is spent and not merely after it, which is what lets the
allocation steer a campaign rather than describe one.

**Two rates that are not the same rate, and the distinction the feature's own
sentence turns on.**  PRD §428's complaint is that the width-versus-depth
planner *"cannot tell an exhausted theme from an unexplored one"*, so those two
states must be different answers here, and they are:

* **measured and barren** — a branch that refined and succeeded at none of them
  is ``p = 0``: measured, far from the target, and it *loses* allocation.  This
  is §434's *"beyond the agent's frontier"*.
* **unmeasured** — a branch that has refined nothing at all carries no rate, and
  its weight is :data:`TARGET_WEIGHT` exactly: it sits *at* the target until
  evidence moves it.  That is feature 228's *"a new theme starts at the prior,
  exactly"* restated on this feature's axis, and it is the safe direction for an
  unknown — a branch nobody has probed is the one place the frontier might be,
  and spending nothing on it would answer §428's complaint by making every
  unexplored theme look exhausted.

Note which way the asymmetry runs: no evidence is *not* evidence of failure, and
it is not evidence of success either (a branch assumed to be at the target is
assumed, not measured).  The first refinement a branch attempts replaces the
assumption with a measurement, and one success in four is already 0.25 — near
enough to the target that the branch keeps its allocation.

**``p*`` is stated, and the band is this module's own default.**  PRD §431
writes ``p* = 0.2`` as a literal, so :data:`TARGET_SUCCESS_RATE` is a citation.
PRD states **no** number for ``σ``, so :data:`DIFFICULTY_BAND` is a *default
parameterization* stated as a named constant rather than hidden in the formula —
the stance feature 228 takes for ``PRIOR_STRENGTH`` and feature 227 for its
bands, and for the same reason: no document states a number, so the honest thing
is a named knob the dreaming loop's own tuning replaces rather than an invented
law dressed as one.  Its value and what it costs are in its own comment below,
numbers included, so a reader can judge the shape rather than take it on trust.

**The budget is conserved, exactly, and the apportionment is rational.**  The
allocation's depths sum to the plan's ``branch_count * refine_count`` on every
path — an allocation that quietly dropped a refinement would be this feature
spending less than the campaign was planned at, and one that invented a
refinement would be spending more.  The split is the largest-remainder method
over the branches' weights, and it is taken in **exact rational arithmetic**:
``fractions.Fraction(weight)`` is the exact value of whatever float the kernel
returned, so the quotients, the floors and the tie-breaking remainders are
compared as rationals rather than by a rounding mode.  The kernel's values
themselves are the module's only floats, and they are as reproducible as the
platform's ``math.exp``; what the rational apportionment buys is that a
last-bit difference in a weight can only move an allocation that was *already*
within a last bit of a tie — and there the order is total and deterministic,
because the tie is broken by the theme root (a truth no arithmetic can
manufacture) rather than by dict order.  The conservation law is asserted as
arithmetic in the suite, over a census whose quotas are deliberately fractional,
so a rewrite that kept the spelling and lost the law would fail.

**A branch allocated zero depth is present at zero, not absent.**  The
allocation carries an entry for every branch in the census, saturated ones
included.  Absence would be a second statement — *this branch was not
considered* — and it is exactly the statement the feature must not make about
the branch it just indicted: §434's saturated branch loses its allocation and is
still a branch of the campaign, and feature 237's own rule needs to find it
there to reduce anything.  This is the mirror of the *"absent rather than
filtered"* discipline feature 233's planning context states for episode facts;
here the fact is present because it is one.

**No component, no I/O, and no new error class.**  Every refusal is a fact about
the request — a rate that is not a rate, a branch that succeeded more often than
it refined, a plan that does not carry its two counts, a census that is not a
batch of branches, a theme named twice — so all of them are
:class:`~discovery.errors.CampaignPlanningError`, the member's existing *"the
request cannot be planned"* class, and the same split-by-repair decision feature
235 states for the derivation it hands this module.  A new class would be a
second vocabulary for one sentence — the drift
``packages/discovery/tests/test_cross_member.py`` exists to prevent — and no
corrected re-request is the wrong repair for any of these.  Stdlib only, and
import-cheap: :mod:`math` (``exp``), :mod:`fractions`, :mod:`dataclasses`,
:mod:`types` and this member's own errors, with no third-party import at module
scope, so the factory's scan (which imports this package to fire its
``@register``) pays nothing for it.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from .errors import CampaignPlanningError

__all__ = [
    "DIFFICULTY_BAND",
    "TARGET_SUCCESS_RATE",
    "TARGET_WEIGHT",
    "BranchDifficulty",
    "DepthAllocation",
    "allocate_depth",
    "difficulty_weight",
]

#: ``p*`` — the per-branch success rate the allocation aims at, PRD §431's
#: literal ``p* = 0.2``.  A citation rather than a policy, and the one number in
#: the kernel that a document states: §428 introduces it as *"the mechanism from
#: self-improving-model training"*, where a task at which the learner succeeds
#: about a fifth of the time is the most informative one available.
#:
#: It is deliberately **not** centred on ``0.5``, and that is the whole reason a
#: saturated branch loses so much more than a barren one: a branch where every
#: refinement succeeds sits ``0.8`` from this target, while one where nothing
#: succeeds sits ``0.2`` from it.  §434's two failures are therefore not
#: symmetric, and the asymmetry is a consequence of the cited target rather than
#: a second rule applied on top of the kernel.
TARGET_SUCCESS_RATE = 0.2

#: ``σ`` — the difficulty band, the kernel's half-width in units of success
#: rate.  **PRD states no number for this**, so it is a named default the
#: deployment's own tuning replaces rather than a law — the stance feature 228
#: states for ``PRIOR_STRENGTH`` ("*the default parameterization the dreaming
#: loop's own tuning replaces*") and feature 227 for its bands.  The value is
#: :data:`TARGET_SUCCESS_RATE` itself: a branch is "near 0.2" — §428's word — in
#: the sense that its distance from the target is comparable to the target.
#:
#: What that costs, at the three rates that matter, is worth writing down rather
#: than leaving to be derived.  Against a weight of ``1.0`` at the target:
#:
#: * ``p = 0.0`` (measured, nothing succeeds) keeps ``exp(-0.5) ≈ 0.607``;
#: * ``p = 0.4`` (twice the target) keeps ``exp(-0.5) ≈ 0.607`` as well — the
#:   band is symmetric in *distance*, which is what makes it a kernel;
#: * ``p = 1.0`` (saturated) keeps ``exp(-8) ≈ 0.00034``.
#:
#: So saturation is effectively eliminated while a barren branch retains a
#: little over half — the reading that an exhausted branch is a *settled* fact
#: about the agent's ability, while a barren one may simply not have been probed
#: in the right direction yet.  A deployment that wants the frontier picked out
#: more sharply narrows this constant; one that wants the depth spread widely
#: widens it.  Either way the *shape* PRD §434 states is unchanged, which is why
#: the suite pins the shape and not this number.
DIFFICULTY_BAND = TARGET_SUCCESS_RATE

#: The weight of a branch sitting at the target — ``D(p*) = exp(0) = 1``, so the
#: kernel's maximum is exactly one and every other weight is a fraction of it.
#: It is also the weight of a branch that has measured **nothing**, which is
#: named here rather than written as a bare ``1.0`` at that one site: an
#: unmeasured branch is not *given* the target's weight as a fallback, it is
#: *assumed to sit at* the target, and a reader should meet that as a statement
#: about evidence rather than as an arithmetic identity.
TARGET_WEIGHT = 1.0

#: The two names a plan contributes to this feature's ask, restated from the two
#: counts feature 235's :class:`~discovery.grid.GridPlan` carries — listed once
#: so the refusal in :func:`_plan_reads` and the module docstring cannot
#: disagree about which reads the allocation makes.  The reads are taken *by
#: name* for the reason feature 235's own adapter states: the policy-runtime
#: member's ``GridPlan`` carries the same two counts under the same names, so a
#: policy's admitted plan fills this allocation's budget without a conversion —
#: the restatement ``packages/discovery/tests/test_difficulty.py`` drives at the
#: sibling's real value.
_PLAN_READS = ("branch_count", "refine_count")

#: What a missing read is bound to while the two are collected, so that
#: :func:`_plan_reads` can name **every** read the plan does not carry rather
#: than the first one — the "name every offender at once" discipline
#: :func:`discovery.grid.derive_grid_plan` and
#: :meth:`discovery.themes.ThemeSet.assign_all` both state.  A private sentinel
#: rather than ``None``, because ``None`` is a value a real plan field could
#: hold and a sentinel cannot be confused with one.
_ABSENT = object()


@dataclass(frozen=True)
class BranchDifficulty:
    """One branch's measured evidence, and the difficulty weight it earns.

    The *per-branch* half of the feature's sentence, and the unit the whole
    module is written in: a research theme (the root a branch was planted in),
    the refinements that branch has attempted, and the refinements that
    succeeded — the three numbers a prefix walk can count, and the whole of what
    §434's *"Computable entirely from prefix information"* permits.  Frozen,
    because evidence is a recorded fact rather than a running tally: a caller
    that could edit a branch's counts after reading its weight would hold a
    weight that belonged to a different measurement.

    **The theme root is the branch's identity here**, and that is a decision
    worth stating.  PRD §428's complaint is phrased in themes — *"it cannot tell
    an exhausted theme from an unexplored one"* — and the sibling member happens
    to key feature 228's family-conditional thresholds on the same slug, which
    is what makes §434's *"it drops into the same ``_schedule(beta)`` dict"* a
    statement about one axis in two members rather than about one number in two
    places.  Which themes are *legal* is emphatically not this module's
    business: that is feature 241's configured set, and restating it here would
    be a second spelling of a config-bound law.  A duplicate theme in one census
    is refused by :func:`_validated_census` — see there for why two branches
    cannot share one identity in a per-branch allocation.

    Validated in :meth:`__post_init__`, through ``object.__setattr__`` so a
    ``dataclasses.replace`` or an unpickle passes back through the check: the
    slug is non-empty text, the two counts are genuine non-negative integers (a
    ``bool`` is not a count — the SQLite affinity trap this workspace guards
    elsewhere), and a branch cannot have succeeded more often than it refined,
    because a rate above one is not a rate and every weight computed from it
    would be a weight earned by a measurement that cannot exist.
    """

    #: The research theme this branch was planted in — the axis the difficulty
    #: is measured along, the key the allocation is returned under, and the slug
    #: feature 219's ``meta()`` exposes and feature 228 keys its thresholds on.
    theme_root: str
    #: The refinements this branch has attempted, as the prefix reveals them.
    #: ``0`` is the unmeasured branch, and it is a legitimate census entry — see
    #: :attr:`success_rate` for why a branch nobody has probed is not a branch
    #: that has failed.
    refinements: int
    #: The refinements that succeeded.  Never more than :attr:`refinements`.
    succeeded: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "theme_root", _validated_theme_root(self.theme_root)
        )
        object.__setattr__(
            self,
            "refinements",
            _validated_count(self.refinements, "a branch's refinements"),
        )
        object.__setattr__(
            self, "succeeded", _validated_count(self.succeeded, "a branch's successes")
        )
        if self.succeeded > self.refinements:
            raise CampaignPlanningError(
                f"the branch in {self.theme_root!r} reports {self.succeeded} "
                f"successes over {self.refinements} refinements; feature 236 "
                "weights a branch by the success rate its prefix measured, and a "
                "rate above one is no rate — a branch succeeds at most once per "
                "refinement it attempted"
            )

    @property
    def success_rate(self) -> float | None:
        """``p_branch`` — the rate the weight is taken at, or ``None`` if unmeasured.

        ``succeeded / refinements``, and ``None`` — not ``0.0`` — for a branch
        that has refined nothing at all.  The distinction is the feature's own
        headline read from the evidence side: §428's planner *"cannot tell an
        exhausted theme from an unexplored one"*, and the two states are one
        division apart.  A branch with four attempts and no success has a rate,
        and it is ``0.0``; a branch with no attempts has no rate, and saying so
        is what keeps :attr:`weight` from scoring it as if it had been tried and
        found wanting.
        """
        if not self.refinements:
            return None
        return self.succeeded / self.refinements

    @property
    def weight(self) -> float:
        """``D(branch)`` — the difficulty weight, at the branch's measured rate.

        The kernel of PRD §431 applied to :attr:`success_rate`, or
        :data:`TARGET_WEIGHT` exactly for a branch that has measured nothing:
        an unprobed branch is *assumed to sit at* the target, so it enters the
        allocation at the kernel's maximum until a measurement moves it.  The
        two are deliberately not spelled the same way — one is a call to
        :func:`difficulty_weight` and the other is a constant — because they are
        not the same claim: a measured branch at ``0.2`` is *at* the target, and
        an unmeasured one is *assumed* to be.

        Delegation rather than arithmetic: a branch's weight is the scalar verb
        applied to this branch's rate, so a rewrite of the kernel cannot leave
        the per-branch answer behind, and the suite drives both spellings over
        the same rates to pin that the two are one kernel.
        """
        rate = self.success_rate
        if rate is None:
            return TARGET_WEIGHT
        return difficulty_weight(rate)


@dataclass(frozen=True)
class DepthAllocation:
    """The depth budget, split across the branches in proportion to difficulty.

    The feature's return value: one depth per theme root, and the census's
    *whole* budget across them — no branch omitted and no refinement quietly
    dropped.  Frozen, and compared by its mapping, for the reason
    :class:`~discovery.grid.GridPlan` is frozen and compared by its counts: an
    allocation is a *decision* a campaign's depth is spent under, so a caller
    has to be able to compare the allocation it made with the depth a tree was
    actually walked at, and to key a campaign's provenance by the split it ran
    under — which is why this value is hashable as well as comparable.

    **The total is derived, never a second field.**  :attr:`total` sums
    :attr:`depths`, so an allocation whose parts disagreed with its whole cannot
    be constructed — the conservation law is a property of the value rather than
    a check that could be forgotten, and :func:`allocate_depth` is where the
    plan's budget is conserved *into* these depths.  The mirror of feature 235's
    choice to *state* its two counts as fields: there the counts are the
    decision, and here the decision is the split.

    Validated in :meth:`__post_init__`: the depths are a mapping, every key is a
    non-empty theme root, and every depth is a genuine non-negative integer — a
    ``bool`` is not a count and neither is a float, the SQLite affinity trap
    restated at the allocation.  The mapping is copied into a read-only view,
    never aliased to the dict it was built from, so a caller that keeps writing
    its own dict cannot move an allocation already made — the stance feature
    228's :class:`~policy_runtime.families.FamilySchedule` takes for its
    thresholds.
    """

    #: ``theme_root`` → refinements allocated to that branch.  Every branch of
    #: the census appears, saturated ones at ``0``; see the module docstring for
    #: why a zero is a statement and an absence would be a different one.
    depths: Mapping[str, int]

    def __post_init__(self) -> None:
        if not isinstance(self.depths, Mapping):
            raise CampaignPlanningError(
                f"a depth allocation is a theme root's share of a campaign's "
                f"refinements, keyed by theme root; a "
                f"{type(self.depths).__name__} is not a mapping from one to the "
                "other, so it names no branch and allocates nothing (feature 236)"
            )
        depths: dict[str, int] = {}
        for theme_root, depth in self.depths.items():
            key = _validated_theme_root(theme_root)
            depths[key] = _validated_count(
                depth, f"the depth allocated to {key!r}", what="depth allocation"
            )
        # Sorted so a reader comparing two allocations sees the same order, and a
        # *copy* behind a read-only view: the caller's dict is never aliased.
        object.__setattr__(
            self, "depths", MappingProxyType(dict(sorted(depths.items())))
        )

    @property
    def total(self) -> int:
        """The whole budget the depths add up to — derived, never stored.

        For an allocation :func:`allocate_depth` built from a
        :class:`~discovery.grid.GridPlan`, this is the plan's
        ``branch_count * refine_count``: the campaign's refinements, all of them
        and no more.  Derived rather than carried so the value cannot disagree
        with itself about how much depth it is spending.
        """
        return sum(self.depths.values())

    def __hash__(self) -> int:
        """The split, as a hashable value — order-insensitive by construction.

        A frozen dataclass derives ``__hash__`` from its fields, and this one's
        field is a mapping, which is unhashable — so the hash is spelled here
        over the *sorted* items.  Sorting is what makes it a hash of the split
        rather than of the order the branches happened to be appended in, which
        is the same statement :func:`_apportioned` makes when it sorts the
        remainders.
        """
        return hash((type(self), tuple(sorted(self.depths.items()))))


def difficulty_weight(success_rate: Any) -> float:
    """``D(p) = exp(−(p − p*)² / 2σ²)`` — the kernel, PRD §431.

    The feature's scalar verb, and the whole of "computes a per-branch
    difficulty weight" read at one branch: handed the success rate a branch's
    prefix measured, it returns that branch's weight — ``1.0`` exactly at
    :data:`TARGET_SUCCESS_RATE`, decaying with the *distance* from the target in
    either direction.  A rate is required to be a real in ``[0, 1]``: it is a
    proportion of refinements, so ``1.1`` is not a rate a branch could have
    measured and neither is a ``NaN``, and both are refused in this member's
    malformed-ask class rather than allowed to poison a whole allocation with a
    weight that compares false against every other weight.

    Both ends are named in PRD §434 and both are consequences of this one
    expression, not of a second rule: a *saturated* branch (``p → 1``) is a full
    ``0.8`` from a target of ``0.2`` and loses effectively all of its weight,
    while a *barren* one (``p = 0``) is ``0.2`` away and keeps a little over
    half of it.  Which is §434's *"saturated and loses allocation; one where
    nothing succeeds is beyond the agent's frontier and also loses it"*, with
    the asymmetry falling out of where ``p*`` sits.

    A branch with **no** measurement does not come through here at all — the
    kernel is a function of a rate, and an unmeasured branch has none.  That
    case is :attr:`BranchDifficulty.weight`'s, and the two spellings are
    deliberately distinct: this one answers *how far from the target is this
    measurement*, and that one answers *what do we assume about a branch we have
    not measured*.
    """
    rate = _validated_rate(success_rate)
    distance = rate - TARGET_SUCCESS_RATE
    return math.exp(-(distance * distance) / (2.0 * DIFFICULTY_BAND * DIFFICULTY_BAND))


def allocate_depth(plan: Any, branches: Any) -> DepthAllocation:
    """Split a plan's depth budget across the branches the prefix measured.

    The feature's verb, and the step the orchestrator runs once it holds both
    halves of the evidence: feature 235's :class:`~discovery.grid.GridPlan` — the
    flat base grid the history justified — and the per-branch census a prefix
    walk can count.  The plan's whole depth budget,
    ``branch_count * refine_count``, is redistributed in proportion to each
    branch's :attr:`BranchDifficulty.weight`, and the result is a
    :class:`DepthAllocation` whose depths add back up to that budget exactly.

    The steps, in order, each refusal in the member's malformed-ask vocabulary:

    1. **the plan carries its two counts** — ``branch_count`` and
       ``refine_count``, taken **by name** rather than by type, so the
       policy-runtime member's ``GridPlan`` (the value feature 229's admission
       law hands back) fills this allocation's budget without a conversion, and
       **every** missing one is named.  Refused with
       :class:`~discovery.errors.CampaignPlanningError`: an ``AttributeError``
       escaping here would be this seam presenting a malformed request as a bug
       in the allocation.
    2. **the two counts are counts** — a ``bool`` or a non-``int`` or a negative
       one carries no budget.  The same check feature 235 applies to the plan it
       authors, restated at the consumer, so a plan written by any spelling of
       the value is judged by one law.
    3. **the census is a batch of this member's branches** — a bare
       :class:`BranchDifficulty` is accepted and wrapped (a caller projecting
       one branch is a legitimate caller), a ``str``/``bytes`` is refused rather
       than iterated into characters, an entry that is not a branch is refused
       with its position, an empty batch is refused (a *per-branch* split of a
       budget across no branch is not a split), and a theme root named twice is
       refused naming every repeat.
    4. **the budget is apportioned** by :func:`_apportioned` — largest
       remainder over the weights in exact rational arithmetic — and returned as
       a :class:`DepthAllocation`, constructed, so the counts law is applied at
       the value once.

    Two things this deliberately does **not** check.  It does not require the
    census to have ``plan.branch_count`` entries: the plan is the *base* the
    caller projects onto the branches its tree actually opened, and whether a
    campaign opened as many roots as it planned is a fact about that campaign's
    execution rather than about this request — a refusal here would be this seam
    demanding a correspondence it cannot verify.  And it does not refuse a plan
    whose ``refine_count`` is ``0``: the explore-only grid feature 235 derives
    from a history that refined nothing, and that 229's plan law admits, is a
    legitimate plan, and its allocation is every branch at zero depth by
    arithmetic rather than by special case.

    It reads no store and opens no file: the census reaches it from the
    caller's prefix, and the plan from feature 235's derivation or a policy's
    own hook.
    """
    max_branches, refinements_per_branch = _plan_reads(plan)
    census = _validated_census(branches)
    budget = max_branches * refinements_per_branch
    return DepthAllocation(depths=_apportioned(budget, census))


def _plan_reads(plan: Any) -> tuple[int, int]:
    """Take the two counts off a plan, validating each.

    The reads are taken **by name rather than by type**, so the two spellings of
    the plan value this workspace holds — feature 235's
    :class:`~discovery.grid.GridPlan` and the policy-runtime member's, which
    feature 229's admission law judges — fill this allocation's budget
    identically.  Feature 235 does the same for the three reads a planning
    context carries, and for the same reason: the value is a decision authored
    in one member and consumed in another, and no member imports another.

    Both missing names are collected before either is refused, so a plan
    carrying neither is told about both rather than meeting them one
    resubmission at a time.
    """
    reads = {name: getattr(plan, name, _ABSENT) for name in _PLAN_READS}
    missing = [name for name, value in reads.items() if value is _ABSENT]
    if missing:
        listed = ", ".join(repr(name) for name in missing)
        raise CampaignPlanningError(
            f"a depth allocation is made from a grid plan's budget, and "
            f"{type(plan).__name__} carries no {listed}; feature 236 splits the "
            "refinements a plan opens a campaign with — its branch count and its "
            "refinements per branch — across the branches the prefix has "
            "measured, so a request that does not carry them names no budget to "
            "allocate (feature 235's GridPlan carries branch_count and "
            "refine_count, which is the whole of what a plan contributes here)"
        )
    return (
        _validated_count(reads["branch_count"], "a grid plan's branch_count"),
        _validated_count(reads["refine_count"], "a grid plan's refine_count"),
    )


def _validated_census(branches: Any) -> tuple[BranchDifficulty, ...]:
    """Materialise the per-branch evidence, refusing anything that is not one.

    The same adapter shape feature 235 states for the history it is handed, one
    axis over: a bare branch is accepted and wrapped, a string is refused rather
    than iterated into characters (a census read as a batch would hand the
    allocation one branch per character, and the refusal would arrive as a
    mangled branch rather than as *"that is not a batch"*), and an entry that is
    not a branch is refused with its position, because a value that is not one
    measures no rate.

    Two refusals here are this feature's own rather than restatements:

    * **An empty census is refused.**  An allocation is *per branch*: a batch
      naming none leaves the plan's whole budget with nowhere to go, and
      answering a zero-depth allocation instead would be this seam reporting a
      caller's mistake as a decision about a campaign.  This is deliberately not
      feature 235's *empty history is planned* path — there, no evidence is a
      deployment that has never run a campaign and still needs a grid; here,
      there is a grid and nothing to spend it on.
    * **A theme root named twice is refused, naming every repeat.**  The theme
      root is the branch's identity in this census, and two entries under one
      identity cannot be apportioned: the mapping would silently keep whichever
      landed second, so the allocation would report one branch's depth as
      another's — and the caller would have no way to see that it had.  Whether
      the duplicate is one branch's evidence split in two or two distinct
      branches that happen to share a theme, the repair is the same and it is
      the caller's: state one branch per theme root.
    """
    if isinstance(branches, BranchDifficulty):
        return (branches,)
    if isinstance(branches, (str, bytes)) or not isinstance(branches, Iterable):
        raise CampaignPlanningError(
            f"a depth allocation takes a batch of per-branch evidence, got "
            f"{type(branches).__name__}; feature 236 weights each branch by the "
            "success rate its refinements measured, and a value that is not a "
            "sequence of branches is no census to allocate depth across"
        )
    census = tuple(branches)
    for position, branch in enumerate(census):
        if not isinstance(branch, BranchDifficulty):
            raise CampaignPlanningError(
                f"the branch census's entry at position {position} is "
                f"{type(branch).__name__}, not a BranchDifficulty; the evidence a "
                "depth allocation is made from is a theme root and the "
                "refinements it attempted and survived, and a value that is not "
                "one measures no success rate to weight (feature 236)"
            )
    if not census:
        raise CampaignPlanningError(
            "a depth allocation is per branch, and the census names none; "
            "feature 236 splits a grid plan's refinement budget across the "
            "branches a prefix has measured, and a batch with no branch in it "
            "leaves the whole budget unallocated — hand over the branches the "
            "campaign opened, even the ones that have refined nothing yet"
        )
    counted: dict[str, int] = {}
    for branch in census:
        counted[branch.theme_root] = counted.get(branch.theme_root, 0) + 1
    repeated = sorted(theme for theme, seen in counted.items() if seen > 1)
    if repeated:
        listed = ", ".join(repr(theme) for theme in repeated)
        raise CampaignPlanningError(
            f"the branch census names {listed} more than once; the theme root is "
            "the identity a depth allocation is keyed by, and two entries under "
            "one identity cannot be split between — one of them would silently "
            "take the other's depth, and the allocation would report a branch "
            "that never had it (feature 236)"
        )
    return census


def _apportioned(budget: int, census: tuple[BranchDifficulty, ...]) -> dict[str, int]:
    """Split ``budget`` across the census by weight — largest remainder, exactly.

    The mechanism of PRD §434 read as arithmetic.  Every branch's weight is
    taken as an **exact rational** (``Fraction`` of the float the kernel
    returned), each branch's exact quota is ``budget * w_i / Σw``, every quota
    is floored, and the units the floors left over go to the largest remainders
    — the largest-remainder method, chosen over rounding or over a running
    division because it is the one that *conserves the budget exactly* on every
    input, which is the property the feature's whole return value is about.

    Three properties are worth stating rather than leaving to be read off:

    * **The leftover units are strictly fewer than the branches.**  Each quota
      minus its floor is below one, so the floors leave at most ``n - 1`` units
      unassigned and there is always something for every remaining place to take
      — no `budget` can drive this loop past the census.
    * **Ties are broken by the theme root, not by dict order.**  Two branches
      whose weights are within a last bit of each other have remainders that
      differ by less than a last bit, and the exact rational comparison decides
      them the same way on every machine and in every process; only a *genuine*
      tie reaches the sort's second key, and there the theme root is a truth no
      arithmetic can manufacture.  That is what makes an allocation a decision a
      campaign can be reproduced under.
    * **A zero weight still gets an entry.**  A weight of exactly ``0.0``
      apportions nothing, and the branch appears at ``0`` like every other
      branch the census named — see the module docstring on why the saturated
      branch is present rather than absent.

    ``total_weight`` is strictly positive for any census taken under the stated
    band, and the guard is kept anyway: the minimum weight is
    ``exp(−(1 − p*)² / 2σ²)`` at the far end of the rate range, so no census of
    rates in ``[0, 1]`` can underflow the sum to zero — but the band is a named
    constant a deployment may narrow, and a narrower band makes ``exp`` of a
    large negative number exactly ``0.0``.  Refusing there is this module saying
    that an allocation of nothing is not the same answer as an allocation of
    zero, which is the distinction the whole value is built on.
    """
    weights = {
        branch.theme_root: Fraction(branch.weight) for branch in census
    }
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise CampaignPlanningError(
            f"every branch in this census has a difficulty weight of zero "
            f"({len(census)} branches, none at or near "
            f"{TARGET_SUCCESS_RATE}); feature 236 apportions a campaign's depth "
            "in proportion to the weight each branch earned, and weights that "
            "sum to zero name no branch to give the budget to — every branch "
            "measured is as far from the target as the kernel can express"
        )
    depths: dict[str, int] = {}
    remainders: list[tuple[Fraction, str]] = []
    for theme_root, weight in weights.items():
        quota = Fraction(budget) * weight / total_weight
        floor = quota.numerator // quota.denominator
        depths[theme_root] = floor
        remainders.append((quota - floor, theme_root))
    unassigned = budget - sum(depths.values())
    for _remainder, theme_root in sorted(
        remainders, key=lambda pair: (-pair[0], pair[1])
    )[:unassigned]:
        depths[theme_root] += 1
    return depths


def _validated_rate(value: Any) -> float:
    """Refuse a success rate that is not a proportion of refinements.

    A rate is a real in ``[0, 1]`` and nothing else.  A ``bool`` is refused even
    though it is an ``int`` — the SQLite affinity trap this workspace guards
    elsewhere, and here it would read ``True`` as a branch that succeeded at
    every refinement it attempted — and ``NaN`` is refused explicitly, because
    every comparison against a ``NaN`` is false: a ``NaN`` rate would produce a
    weight that is not less than, not greater than and not equal to any other
    weight in the census, so it would apportion by whichever branch happened to
    be sorted first rather than by evidence.  The comparison through
    :func:`math.isnan` also rejects an infinity, which is outside ``[0, 1]``
    anyway.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise CampaignPlanningError(
            f"a difficulty weight is taken at a branch's success rate, and a "
            f"success rate is a number, got {value!r} ({type(value).__name__}); "
            "feature 236 targets the rate at which a branch's refinements "
            "succeed, so a value that is not a real number measures no rate"
        )
    rate = float(value)
    if math.isnan(rate) or not 0.0 <= rate <= 1.0:
        raise CampaignPlanningError(
            f"a difficulty weight is taken at a branch's success rate, and a "
            f"success rate lies in [0, 1], got {value!r}; feature 236 measures a "
            "branch by the proportion of its refinements that succeeded, so a "
            "value outside that interval is not a proportion any census could "
            "have counted"
        )
    return rate


def _validated_theme_root(value: Any) -> str:
    """Refuse a theme root that is not a non-empty slug.

    Structural only — non-empty text, stripped of nothing — because *which*
    themes may exist is feature 241's configured legal set, a deployment's
    config, and restating that ceiling here would be a second spelling of a
    config-bound law.  The same restraint feature 228 states for its own theme
    key, and it matters for the same reason: this module's refusal is about a
    census key being absent, not about a theme being illegal.
    """
    if not isinstance(value, str) or not value.strip():
        raise CampaignPlanningError(
            f"a branch's theme root must be a non-empty research theme, got "
            f"{value!r} ({type(value).__name__}); the theme root is the identity "
            "a branch is measured and allocated under, and a value that is not "
            "one names no branch (feature 236; whether a theme is *legal* is "
            "feature 241's configured set, not this module's check)"
        )
    return value


def _validated_count(value: Any, field_name: str, *, what: str = "census") -> int:
    """Refuse a count that is not a genuine non-negative integer.

    The same check feature 232 applies to ``workspace_count``, feature 242 to its
    census counts, feature 235 to its plan counts and feature 233 to the two
    ceilings, restated for this feature's three: a ``bool`` is not a count (the
    SQLite affinity trap this workspace guards elsewhere — ``True`` would read as
    one refinement), a non-``int`` is not a count, and a negative one is not a
    count a tree could hold.  Named with its field and with what it belongs to,
    so a refusal says which value and which of this feature's two vocabularies —
    the plan's budget or the branch census — the caller should be looking at.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CampaignPlanningError(
            f"{field_name} must be a genuine integer, got {value!r} "
            f"({type(value).__name__}); feature 236 apportions a campaign's "
            f"refinements from counts — the budget a grid plan carries and the "
            f"refinements each branch measured — and a value that is not one is "
            f"no quantity of refinements to allocate ({what})"
        )
    if value < 0:
        raise CampaignPlanningError(
            f"{field_name} must be non-negative, got {value!r}; a negative count "
            "of refinements is one no branch could have walked, so it measures "
            "no success rate and apportions no depth (feature 236)"
        )
    return value
