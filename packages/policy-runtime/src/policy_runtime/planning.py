"""Feature 229, the planning hook — ``plan_grid`` must return a non-null plan.

app_spec.xml, "Exploration Policy Runtime", feature 229: *System requires
plan_grid to return a non-null plan on every path including empty history,
which rejects a policy that returns nothing.*  docs/nullius-tech-architecture.md
§11 names ``plan_grid`` as part of the policy runtime's API surface — a hook
that *runs BEFORE a campaign*, *may read only prior campaign manifests*, and
*must return a non-None plan on every path, including empty history* — and §11.1
makes it a static check ("``plan_grid`` overridden on every path") that admits a
policy only if the hook is present and always yields a plan.

Feature 229 is the *read side* of that enforcement, and it is deliberately
narrow: it owns the value objects a plan is made of, the "non-null on every
path" law, and the admission check a caller runs against a policy's authored
``plan_grid``.  It does **not** author a plan, run a campaign, or read a store —
those are the *discovery* member's features (233–237), which build on this one's
guarantee that a plan exists to be validated.  The split is the feature: 229
says *a plan must exist and be well-formed*; 233–237 say *the plan's contents
(theme diversity, width/depth) must be sound*.  Keeping them apart is why
233–237 ``depends_on=229`` — a caller cannot check a plan's theme diversity
against a plan that was never returned.

**A law, not a policy.**  The requirement is a property of *any* policy's
``plan_grid``: whatever it does, it must not return nothing.  That is a check
the runtime makes on the policy's authored code — the same shape
:mod:`signal_agent._authoring` (feature 205) and :mod:`sandbox` (feature 167)
take: a gate that returns a verdict, never raises, and lets the caller decide.
The policy-runtime member owns that gate for the planning hook.

**The empty-history path is the one that is tested.**  The feature is explicit
— "empty history" is the path that must return a plan — so the law invokes the
hook with a *synthetic empty context*, built by the law itself, with no prior
campaigns in it.  A policy that special-cases "no history" is therefore tested
on exactly the path the feature names, and is shown nothing: the context carries
no real campaign, so the hook cannot read past the prior-manifests-only boundary
(that boundary is feature 233's check; 229 hands the hook a context with nothing
in it and asks only "did it return a plan?").  The synthetic context is the
read-side mirror of feature 217's :class:`~policy_runtime.PolicyQuestion` being
built over a tree the question did not author.

**No I/O, no store, no campaign.**  The law invokes the hook with a value object
and inspects the return; it reads no artifact store and opens no campaign.  The
context's ``prior_campaigns`` are supplied by the caller, never by the planner —
a planner that built its own context would be reading the answer key.  This
keeps the member import-cheap and free of a hard dependency on the store, the
same reason :func:`signal_agent.require_contract` and :mod:`contract._arrow`
defer their imports: the factory's scan imports this member to fire its
``@register`` builder, and a module-scope store import would make this
component's presence depend on scan order.

Stdlib only, and import-cheap: :mod:`dataclasses`, :mod:`inspect`, :mod:`typing`
and the member's own errors — no third-party import at module scope, so the
factory's scan pays nothing for the gate.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import PolicyRuntimeError

__all__ = [
    "GridPlan",
    "GridPlanningContext",
    "PlanGridDecision",
    "PlanGridReason",
    "PlanGridRefusal",
    "plan_grid",
]


class PlanGridRefusal(PolicyRuntimeError):
    """A policy's ``plan_grid`` could not be admitted (feature 229).

    Raised by :meth:`PlanGridDecision.require` on the caller's last line before
    it admits a policy — the bridge between the law's returned verdict and the
    exception a caller wants there, the same role
    :meth:`signal_agent.SourceAdoption.require` plays for feature 205.  The law
    itself (:func:`plan_grid`) raises nothing: it returns a
    :class:`PlanGridDecision`, so a caller auditing a *history* of policies can
    read the verdict without a try/except.  Only :meth:`require` raises, and it
    names the policy that refused, so an operator reading an admission log sees
    *which* policy returned nothing.
    """


class PlanGridReason(str, Enum):
    """Why a policy's ``plan_grid`` was admitted or refused — the audit vocabulary.

    A :class:`str` enum whose *value* is the token every refusal's detail opens
    with, so the reason is greppable in an admission log without a lookup table
    and a reader never has to match a sentence to a category by eye.  The five
    are split by *repair*, not by which check happened to fail: two policies
    that both return nothing, one because it never overrode the hook and one
    because it returns ``None`` on empty history, are two different prompts to
    the retrying agent, so they are two reasons.
    """

    #: Admitted: the hook is callable, synchronous, and returns a well-formed
    #: :class:`GridPlan` on empty history.
    ADMITS = "admits"

    #: Refused: the policy did not override ``plan_grid`` at all — the attribute
    #: is missing or not callable.  Its own reason because the repair is at the
    #: *call shape*: the policy was asked to author a planning hook and authored
    #: none.
    NO_HOOK = "no-hook"

    #: Refused: the hook is an ``async def``.  The replay runs the planning hook
    #: synchronously before a campaign, so an awaitable plan is no plan the
    #: runtime can use — the repair is "drop the ``async``".
    ASYNC = "async"

    #: Refused: the hook returned ``None`` on empty history — the headline case
    #: the feature names ("rejects a policy that returns nothing").  The repair
    #: is "return a plan even when there is no prior history".
    RETURNS_NOTHING = "returns-nothing"

    #: Refused: the hook returned something that is not a :class:`GridPlan` — a
    #: dict, a bare int, a string — or a :class:`GridPlan` whose counts are
    #: empty (``branch_count <= 0``).  The repair is "return a well-formed plan".
    NOT_A_PLAN = "not-a-plan"

    #: Refused: the hook raised on empty history.  A hook that cannot run on the
    #: very path the feature names cannot be admitted; the repair is "handle the
    #: empty-history path".
    RAISES = "raises"


@dataclass(frozen=True)
class GridPlan:
    """The plan a ``plan_grid`` returns — the thing that must be non-null.

    A frozen value, because a plan is a *decision* the policy committed to before
    a campaign opens — the width, depth and themes of the search it is about to
    run — and a plan a caller could move after the fact would not be the plan the
    policy authored.  It is the smallest well-formed answer the planning hook can
    give, and the thing feature 229 guarantees exists: whatever a policy's
    ``plan_grid`` does, it returns one of these, never nothing.

    The three fields are the shape docs/nullius-tech-architecture.md §11 and the
    PRD name — ``branch_count`` (``W``), ``refine_count`` (``R``), and the theme
    roots the plan opens — so a plan rendered here is the plan the discovery
    orchestrator (features 233–237) consumes.  Feature 229 checks the plan is
    *well-formed*; it does not judge its *contents* — theme diversity is feature
    234's, the width/depth derivation is 235's — because a plan can be perfectly
    formed and still open too few themes, and those are two different refusals.
    """

    #: The number of parallel branches to open (``W``).  A **positive** integer:
    #: zero branches is a campaign that opens nothing — the planning-side mirror
    #: of "returns nothing" — so ``branch_count <= 0`` is refused at construction.
    branch_count: int
    #: The number of refinements per branch (``R``).  A **non-negative** integer:
    #: zero is a valid "explore only, no refinement" plan, so it is admitted, but
    #: negative is refused — a negative depth budget is a budget no walk reaches.
    #: Defaults to zero — the explore-only plan — so a hook can name just a width.
    refine_count: int = 0
    #: The theme roots the plan opens, ascending and de-duplicated.  The empty
    #: tuple is admitted — a well-formed plan can open no theme yet (a fresh
    #: planner with empty history) — because theme *diversity* is feature 234's
    #: check, not this one's.
    theme_roots: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        # ``bool`` is an ``int`` subclass; a ``True`` branch count is not a count.
        if isinstance(self.branch_count, bool) or not isinstance(
            self.branch_count, int
        ):
            raise PlanGridRefusal(
                f"a grid plan's branch_count must be an integer, got "
                f"{type(self.branch_count).__name__}: the number of parallel "
                f"branches a campaign opens is a count, and a count that is not an "
                f"integer opens no campaign (feature 229)."
            )
        if self.branch_count <= 0:
            raise PlanGridRefusal(
                f"a grid plan must open at least one branch, got branch_count="
                f"{self.branch_count}: a plan with no branches opens no campaign, "
                f"which is the planning-side mirror of 'returns nothing' the feature "
                f"refuses (feature 229)."
            )
        if isinstance(self.refine_count, bool) or not isinstance(
            self.refine_count, int
        ):
            raise PlanGridRefusal(
                f"a grid plan's refine_count must be an integer, got "
                f"{type(self.refine_count).__name__}: the number of refinements per "
                f"branch is a count, and a count that is not an integer refines no "
                f"branch (feature 229)."
            )
        if self.refine_count < 0:
            raise PlanGridRefusal(
                f"a grid plan's refine_count must be non-negative, got "
                f"{self.refine_count}: a negative depth budget is a budget no walk "
                f"could reach, so a plan carrying one refines nothing (feature 229)."
            )
        if not isinstance(self.theme_roots, Sequence) or isinstance(
            self.theme_roots, (str, bytes)
        ):
            raise PlanGridRefusal(
                f"a grid plan's theme_roots must be a sequence of theme ids, got "
                f"{type(self.theme_roots).__name__}: the themes a plan opens are read "
                f"one by one, and a value that is not a sequence cannot be read that "
                f"way (feature 229)."
            )
        roots = list(self.theme_roots)
        for root in roots:
            if not isinstance(root, str) or not root.strip():
                raise PlanGridRefusal(
                    f"a grid plan's theme_roots must each be a non-empty theme id, got "
                    f"{root!r}: a theme a plan opens is named, and a name that is not "
                    f"text names no theme (feature 229)."
                )
        # Normalise: ascending and de-duplicated, so two plans opening the same
        # themes in a different order are one plan — the tree-identity discipline
        # feature 217's CampaignTree applies to its nodes, restated for a plan.
        object.__setattr__(self, "theme_roots", tuple(sorted(set(roots))))


@dataclass(frozen=True)
class GridPlanningContext:
    """The read-only argument handed to ``plan_grid`` — the prior manifests.

    The "prior campaign manifests" the docs say planning *may* read, carried as
    frozen value objects so a plan and the history it was planned against are one
    statement.  It is built by the *caller* (the discovery orchestrator, in
    features 233–237), never by the planner — a planner that built its own context
    would be reading the answer key, the same way feature 217's question is built
    over a tree the question did not author.

    **The empty context is the load-bearing case.**  With ``prior_campaigns``
    empty — a fresh planner with no history — ``plan_grid`` must still return a
    plan, and that is exactly the path feature 229 tests.  The context is
    therefore the thing the law hands the hook to prove it returns a plan on the
    path the feature names, and an empty one is a valid, admissible context.
    """

    #: The prior campaign manifests, ascending by campaign id.  Empty is valid —
    #: the empty-history path the feature guarantees returns a plan.
    prior_campaigns: tuple[Mapping[str, Any], ...] = field(default=())
    #: The runtime's configured ceiling on parallel branches (``W``).  Carried so
    #: a plan can be bounded against the runtime; the bound is checked by the
    #: caller (features 235/237), not here.
    max_branches: int = 0
    #: The runtime's configured ceiling on refinements per branch (``R``).
    max_refinements: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.max_branches, bool) or not isinstance(
            self.max_branches, int
        ):
            raise PlanGridRefusal(
                f"a grid planning context's max_branches must be an integer, got "
                f"{type(self.max_branches).__name__}: a configured ceiling is a "
                f"count, and a count that is not an integer bounds nothing "
                f"(feature 229)."
            )
        if self.max_branches < 0:
            raise PlanGridRefusal(
                f"a grid planning context's max_branches must be non-negative, got "
                f"{self.max_branches}: a negative ceiling admits no branch, so a "
                f"context carrying one bounds nothing (feature 229)."
            )
        if isinstance(self.max_refinements, bool) or not isinstance(
            self.max_refinements, int
        ):
            raise PlanGridRefusal(
                f"a grid planning context's max_refinements must be an integer, got "
                f"{type(self.max_refinements).__name__}: a configured ceiling is a "
                f"count, and a count that is not an integer bounds nothing "
                f"(feature 229)."
            )
        if self.max_refinements < 0:
            raise PlanGridRefusal(
                f"a grid planning context's max_refinements must be non-negative, "
                f"got {self.max_refinements}: a negative ceiling refines no branch, "
                f"so a context carrying one bounds nothing (feature 229)."
            )


@dataclass(frozen=True)
class PlanGridDecision:
    """One policy's planning-hook verdict: admitted or refused, why, in what words.

    The shape every gate in this workspace takes (:class:`signal_agent.
    SourceAdoption`, :class:`sandbox.SeedDecision`) — a returned verdict, never a
    raised exception, so the caller diagnoses *why* a policy was not admitted.
    ``adopted`` is *computed* from the reason, never assumed — the same
    "computed, never assumed" stance those decisions take — and the object
    carries the plan (for an admission) and the detail (for either), so a caller
    that has checked ``adopted`` reads the plan rather than a sentinel.
    """

    reason: PlanGridReason
    detail: str
    #: The admitted plan, for an admission; ``None`` for every refusal.  Carried
    #: so a caller that has checked ``adopted`` reads the plan rather than
    #: re-invoking the hook.
    plan: GridPlan | None = None

    @property
    def adopted(self) -> bool:
        """Whether the policy's ``plan_grid`` may be admitted — computed from reason."""
        return self.reason is PlanGridReason.ADMITS

    def require(self) -> GridPlan:
        """Return the admitted plan, or raise :class:`PlanGridRefusal`.

        The bridge between the law's returned verdict and the exception a caller
        wants on its last line before admitting a policy: an admitted hook returns
        the plan it authored, so a caller can write ``plan = law.plan_grid(fn).
        require()`` and have feature 229 enforced there rather than remembered.  A
        refusal raises naming the policy, so the admission log and the retry
        prompt say the same thing.
        """
        if self.plan is None:
            raise PlanGridRefusal(self.detail)
        return self.plan

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"PlanGridDecision(reason={self.reason.value!r}, adopted={self.adopted})"


def plan_grid(fn: Callable[..., Any]) -> PlanGridDecision:
    """Admit one policy's ``plan_grid`` only if it returns a non-null plan.

    The feature's verb.  Takes the policy's authored ``plan_grid`` **function** —
    the ``def plan_grid(self, ctx)`` the policy wrote — and answers whether it may
    be admitted, in order, each step's own reason:

    1. **it is callable** — a missing attribute or a bare value is refused with
       :attr:`PlanGridReason.NO_HOOK`; a policy that did not override the hook has
       no hook to run, and a hook that is not callable cannot be invoked;
    2. **it is synchronous** — an ``async def`` is refused with
       :attr:`PlanGridReason.ASYNC`; the replay runs the planning hook
       synchronously before a campaign, so an awaitable plan is no plan the
       runtime can use — the same "one entrypoint, spelled out" stance
       :mod:`signal_agent._authoring` takes on the ``signal`` signature;
    3. **it returns a non-null plan on every path** — the hook is invoked with a
       *synthetic empty context* (:class:`GridPlanningContext` with no prior
       campaigns), the "empty history" the feature names, and the returned value
       is checked: ``None`` is refused with :attr:`PlanGridReason.RETURNS_NOTHING`
       (the headline case), a non-:class:`GridPlan` with
       :attr:`PlanGridReason.NOT_A_PLAN`, a :class:`GridPlan` with
       ``branch_count <= 0`` likewise (a plan that opens no branch is nothing even
       when wrapped), and a hook that raises on empty history with
       :attr:`PlanGridReason.RAISES`.  A returned :class:`GridPlan` is validated
       through its own constructor, so a malformed plan is refused naming the
       field.

    Returns a :class:`PlanGridDecision` — admitted or refused, why, in what words
    — never raising.  The empty context is built by the law, not the policy, so a
    planner is tested on exactly the path the feature names and shown nothing; the
    prior-manifests-only boundary is feature 233's check, not this one's.
    """
    if not callable(fn):
        return PlanGridDecision(
            reason=PlanGridReason.NO_HOOK,
            detail=(
                f"{PlanGridReason.NO_HOOK.value}: the policy carries no callable "
                f"plan_grid hook — feature 229 requires plan_grid overridden on "
                f"every path, and a policy that authored no hook returns no plan on "
                f"any path, so it is refused before a campaign is opened "
                f"(feature 229)."
            ),
        )

    if inspect.iscoroutinefunction(fn):
        return PlanGridDecision(
            reason=PlanGridReason.ASYNC,
            detail=(
                f"{PlanGridReason.ASYNC.value}: the policy's plan_grid is an async "
                f"function — the replay runs the planning hook synchronously before "
                f"a campaign, and an awaitable plan is no plan the runtime can use, "
                f"so the policy is refused until the hook is synchronous (feature "
                f"229)."
            ),
        )

    # The empty-history path the feature names: a synthetic context with no prior
    # campaigns, built by the law, so the hook is tested on exactly the path that
    # must return a plan and shown nothing a real campaign would carry.
    ctx = GridPlanningContext(prior_campaigns=())
    try:
        returned = fn(ctx)
    except Exception as exc:  # noqa: BLE001 - a raising hook is a refusal, by design
        return PlanGridDecision(
            reason=PlanGridReason.RAISES,
            detail=(
                f"{PlanGridReason.RAISES.value}: the policy's plan_grid raised "
                f"{type(exc).__name__} on empty history — a hook that cannot run on "
                f"the very path feature 229 names cannot be admitted, so the policy "
                f"is refused until the empty-history path returns a plan: {exc} "
                f"(feature 229)."
            ),
        )

    if returned is None:
        return PlanGridDecision(
            reason=PlanGridReason.RETURNS_NOTHING,
            detail=(
                f"{PlanGridReason.RETURNS_NOTHING.value}: the policy's plan_grid "
                f"returned None on empty history — feature 229 requires plan_grid "
                f"to return a non-null plan on every path including empty history, "
                f"and a hook that returns nothing returns no campaign to open, so "
                f"the policy is refused (feature 229)."
            ),
        )

    if not isinstance(returned, GridPlan):
        return PlanGridDecision(
            reason=PlanGridReason.NOT_A_PLAN,
            detail=(
                f"{PlanGridReason.NOT_A_PLAN.value}: the policy's plan_grid returned "
                f"{type(returned).__name__}, not a GridPlan — a plan is a "
                f"(branch_count, refine_count, theme_roots) decision the discovery "
                f"orchestrator consumes, and a value that is not one is no plan to "
                f"open, so the policy is refused (feature 229)."
            ),
        )

    # A GridPlan is validated by its own constructor, so a genuine one is always
    # well-formed — but a plan that opens no branch (or refines negatively) is
    # "nothing" even when wrapped: it opens no campaign, the planning-side mirror
    # of returning nothing.  The fields are checked directly here — not by
    # reconstruction, which would raise inside a policy that *built* such a plan
    # rather than returning one — so a returned plan that opens no campaign is
    # refused as not-a-plan, naming the field, the same way feature 217's
    # CampaignTree refuses an empty tree naming what was wrong.
    if returned.branch_count <= 0:
        return PlanGridDecision(
            reason=PlanGridReason.NOT_A_PLAN,
            detail=(
                f"{PlanGridReason.NOT_A_PLAN.value}: the policy's plan_grid returned "
                f"a plan that opens no branch (branch_count={returned.branch_count}) "
                f"— a plan with no branches opens no campaign, which is the "
                f"planning-side mirror of 'returns nothing', so the policy is "
                f"refused (feature 229)."
            ),
        )
    if returned.refine_count < 0:
        return PlanGridDecision(
            reason=PlanGridReason.NOT_A_PLAN,
            detail=(
                f"{PlanGridReason.NOT_A_PLAN.value}: the policy's plan_grid returned "
                f"a plan with a negative refine count (refine_count="
                f"{returned.refine_count}) — a negative depth budget is a budget no "
                f"walk could reach, so the plan refines nothing and the policy is "
                f"refused (feature 229)."
            ),
        )

    return PlanGridDecision(
        reason=PlanGridReason.ADMITS,
        detail=(
            f"{PlanGridReason.ADMITS.value}: the policy's plan_grid returns a "
            f"non-null plan on empty history — branch_count="
            f"{returned.branch_count}, refine_count={returned.refine_count}, "
            f"theme_roots={returned.theme_roots} — so feature 229 is satisfied and "
            f"the policy is admitted (feature 229)."
        ),
        plan=returned,
    )
