"""Feature 229, the planning hook — ``plan_grid`` must return a non-null plan.

app_spec.xml, "Exploration Policy Runtime", feature 229: *System requires
plan_grid to return a non-null plan on every path including empty history, which
rejects a policy that returns nothing.*  docs/nullius-tech-architecture.md §11
names ``plan_grid`` as the policy runtime's pre-campaign planning hook — it runs
before a campaign, reads only prior campaign manifests, and must return a
non-None plan on every path including empty history — and §11.1 makes it a
static check that admits a policy only if the hook is present and always yields
a plan.

Feature 229 is the *read side* of that enforcement, and the invariants these
tests pin are the ones the guarantee depends on:

* **the plan is a well-formed value** — a :class:`GridPlan` carries a positive
  branch count, a non-negative refine count, and a de-duplicated, ascending
  tuple of theme roots; a plan that opens no branch is "nothing" even when
  wrapped, and is refused at construction, the same way feature 217's
  ``CampaignTree`` refuses an empty tree;
* **the empty-history path is the one that is tested** — the law invokes the
  hook with a synthetic empty context (no prior campaigns), so a policy is
  judged on exactly the path the feature names and shown nothing a real campaign
  would carry (the prior-manifests-only boundary is feature 233's);
* **the law returns a verdict, never raises** — :func:`plan_grid` answers
  admitted or refused, why, in what words, and only :meth:`require` raises, on
  the caller's last line before it admits a policy — the gate shape
  :mod:`signal_agent._authoring` and :mod:`sandbox` take.

The headline case is the one the feature names: a ``plan_grid`` that returns
``None`` on empty history is refused — a policy that returns nothing opens no
campaign.
"""

from __future__ import annotations

import dataclasses

import pytest
from policy_runtime import (
    GridPlan,
    GridPlanningContext,
    PlanGridReason,
    PlanGridRefusal,
    plan_grid,
)

# ---------------------------------------------------------------------------
# GridPlan — the plan must be a well-formed value
# ---------------------------------------------------------------------------


def test_grid_plan_admits_a_well_formed_plan() -> None:
    # A plan with a positive branch count, a non-negative refine count, and a
    # tuple of theme roots is admitted — the smallest well-formed answer the
    # planning hook can give, and the thing feature 229 guarantees exists.
    plan = GridPlan(branch_count=4, refine_count=2, theme_roots=("momentum", "value"))
    assert plan.branch_count == 4
    assert plan.refine_count == 2
    assert plan.theme_roots == ("momentum", "value")


def test_grid_plan_admits_zero_refinements() -> None:
    # A refine count of zero is a valid "explore only, no refinement" plan — the
    # plan opens branches but refines none, which is a plan, so it is admitted.
    plan = GridPlan(branch_count=3, refine_count=0)
    assert plan.refine_count == 0


def test_grid_plan_admits_no_theme_roots() -> None:
    # An empty theme_roots is admitted — a well-formed plan can open no theme yet
    # (a fresh planner with empty history).  Theme *diversity* is feature 234's
    # check, not this one's; 229 guarantees a plan exists, not that it is diverse.
    plan = GridPlan(branch_count=3)
    assert plan.theme_roots == ()


def test_grid_plan_normalises_theme_roots() -> None:
    # theme_roots is normalised to a sorted, de-duplicated tuple, so two plans
    # opening the same themes in a different order, or with a repeat, are one
    # plan — the tree-identity discipline feature 217's CampaignTree applies to
    # its nodes, restated for a plan.
    plan = GridPlan(branch_count=3, theme_roots=("value", "momentum", "value"))
    assert plan.theme_roots == ("momentum", "value")


def test_grid_plan_refuses_zero_branches() -> None:
    # A plan with no branches opens no campaign — the planning-side mirror of
    # "returns nothing" — so branch_count <= 0 is refused at construction, naming
    # the field.
    with pytest.raises(PlanGridRefusal, match="branch_count"):
        GridPlan(branch_count=0)


def test_grid_plan_refuses_a_negative_branch_count() -> None:
    # A negative branch count is a count no campaign could open, so it is
    # refused, naming the field.
    with pytest.raises(PlanGridRefusal, match="branch_count"):
        GridPlan(branch_count=-1)


def test_grid_plan_refuses_a_negative_refine_count() -> None:
    # A negative depth budget is a budget no walk could reach, so a plan carrying
    # one refines nothing and is refused, naming the field.
    with pytest.raises(PlanGridRefusal, match="refine_count"):
        GridPlan(branch_count=3, refine_count=-1)


def test_grid_plan_refuses_a_bool_branch_count() -> None:
    # ``bool`` is an ``int`` subclass, and a ``True`` branch count is not a count
    # — the same affinity trap the workspace's SQLite layer guards — so it is
    # refused rather than silently treated as ``1``.
    with pytest.raises(PlanGridRefusal, match="branch_count"):
        GridPlan(branch_count=True)  # type: ignore[arg-type]


def test_grid_plan_refuses_an_empty_theme_root() -> None:
    # A theme a plan opens is named, and a name that is not text names no theme,
    # so an empty-string theme root is refused, naming the offending value.
    with pytest.raises(PlanGridRefusal, match="theme_roots"):
        GridPlan(branch_count=3, theme_roots=("momentum", ""))


def test_grid_plan_is_frozen() -> None:
    # A plan is a decision the policy committed to before a campaign opens, and a
    # plan a caller could move after the fact would not be the plan the policy
    # authored — so it is frozen, and a caller cannot mutate the branch count.
    plan = GridPlan(branch_count=3)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.branch_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GridPlanningContext — the read-only prior manifests; empty is valid
# ---------------------------------------------------------------------------


def test_grid_planning_context_admits_empty_history() -> None:
    # An empty prior_campaigns is a valid, admissible context — the empty-history
    # path the feature guarantees returns a plan.  A fresh planner with no
    # history is a context, not an error.
    ctx = GridPlanningContext(prior_campaigns=())
    assert ctx.prior_campaigns == ()


def test_grid_planning_context_carries_prior_campaigns() -> None:
    # The context carries the prior campaign manifests the planner may read —
    # built by the caller, never the planner, so a planner cannot read the answer
    # key.
    ctx = GridPlanningContext(
        prior_campaigns=({"campaign_id": "c1", "calibration_status": "VOID"},)
    )
    assert ctx.prior_campaigns == ({"campaign_id": "c1", "calibration_status": "VOID"},)


def test_grid_planning_context_refuses_a_negative_ceiling() -> None:
    # A negative configured ceiling admits no branch, so a context carrying one
    # bounds nothing and is refused, naming the field.
    with pytest.raises(PlanGridRefusal, match="max_branches"):
        GridPlanningContext(max_branches=-1)


# ---------------------------------------------------------------------------
# plan_grid — the law: admit only a hook that returns a non-null plan
# ---------------------------------------------------------------------------


def test_plan_grid_admits_a_hook_returning_a_plan() -> None:
    # A hook that returns a well-formed GridPlan on empty history is admitted —
    # the decision is returned, not raised, and ``adopted`` is computed from the
    # reason.
    def plan_grid_hook(ctx: GridPlanningContext) -> GridPlan:
        return GridPlan(
            branch_count=4, refine_count=2, theme_roots=("momentum", "value")
        )

    decision = plan_grid(plan_grid_hook)
    assert decision.adopted is True
    assert decision.reason is PlanGridReason.ADMITS
    assert decision.plan is not None
    assert decision.plan.branch_count == 4


def test_plan_grid_refuses_a_hook_returning_none() -> None:
    # The headline case the feature names: a hook that returns None on empty
    # history returns nothing, opens no campaign, and is refused with
    # RETURNS_NOTHING, naming the policy.
    def plan_grid_hook(ctx: GridPlanningContext) -> None:
        return None

    decision = plan_grid(plan_grid_hook)
    assert decision.adopted is False
    assert decision.reason is PlanGridReason.RETURNS_NOTHING
    assert decision.plan is None
    assert PlanGridReason.RETURNS_NOTHING.value in decision.detail


def test_plan_grid_refuses_a_hook_returning_a_non_plan() -> None:
    # A hook that returns a dict — or any non-GridPlan — returns no plan the
    # discovery orchestrator can consume, so it is refused with NOT_A_PLAN.
    def plan_grid_hook(ctx: GridPlanningContext) -> object:
        return {"branch_count": 4}

    decision = plan_grid(plan_grid_hook)
    assert decision.adopted is False
    assert decision.reason is PlanGridReason.NOT_A_PLAN
    assert "dict" in decision.detail


class _UnvalidatedPlan(GridPlan):
    # A subclass that subverts the constructor's validation — the only way a hook
    # can hand back a "GridPlan" whose branch count is not positive.  The law must
    # not blindly trust isinstance() against such a value; it re-checks the fields.
    def __post_init__(self) -> None:  # deliberately skip the parent's guards
        pass


def test_plan_grid_refuses_a_hook_returning_a_plan_with_no_branches() -> None:
    # A GridPlan with branch_count <= 0 is "nothing" even when wrapped — it opens
    # no branch, so it opens no campaign — and is refused with NOT_A_PLAN, naming
    # the field.  A genuine GridPlan can never reach this state (its constructor
    # forbids it), so it is reached here through a subclass that subverts the
    # constructor, to pin that the law does not blindly trust isinstance().
    def plan_grid_hook(ctx: GridPlanningContext) -> GridPlan:
        return _UnvalidatedPlan(branch_count=0)

    decision = plan_grid(plan_grid_hook)
    assert decision.adopted is False
    assert decision.reason is PlanGridReason.NOT_A_PLAN
    assert "branch_count" in decision.detail


def test_plan_grid_refuses_a_hook_that_raises_on_empty_history() -> None:
    # A hook that cannot run on the very path the feature names cannot be
    # admitted — a hook that raises on empty history is refused with RAISES,
    # carrying the exception type, so the retry prompt says what went wrong.
    def plan_grid_hook(ctx: GridPlanningContext) -> GridPlan:
        raise RuntimeError("no history to plan on")

    decision = plan_grid(plan_grid_hook)
    assert decision.adopted is False
    assert decision.reason is PlanGridReason.RAISES
    assert "RuntimeError" in decision.detail


def test_plan_grid_refuses_a_non_callable() -> None:
    # A policy that did not override plan_grid has no hook to run — a missing
    # attribute or a bare value is refused with NO_HOOK, the repair being at the
    # call shape.
    decision = plan_grid(42)  # type: ignore[arg-type]
    assert decision.adopted is False
    assert decision.reason is PlanGridReason.NO_HOOK


def test_plan_grid_refuses_an_async_hook() -> None:
    # The replay runs the planning hook synchronously before a campaign, so an
    # async def returns an awaitable, not a plan, and is refused with ASYNC — the
    # repair is "drop the async".
    async def plan_grid_hook(ctx: GridPlanningContext) -> GridPlan:
        return GridPlan(branch_count=4)

    decision = plan_grid(plan_grid_hook)
    assert decision.adopted is False
    assert decision.reason is PlanGridReason.ASYNC


def test_plan_grid_tests_the_empty_history_path() -> None:
    # The law invokes the hook with a synthetic empty context — no prior
    # campaigns — so a policy is judged on exactly the path the feature names and
    # shown nothing a real campaign would carry.  The hook sees an empty history
    # and still returns a plan.
    seen: list[GridPlanningContext] = []

    def plan_grid_hook(ctx: GridPlanningContext) -> GridPlan:
        seen.append(ctx)
        return GridPlan(branch_count=3)

    decision = plan_grid(plan_grid_hook)
    assert decision.adopted is True
    assert seen and seen[0].prior_campaigns == ()


def test_plan_grid_does_not_raise_on_a_refusal() -> None:
    # The law returns a verdict, never raises — so a caller auditing a history of
    # policies can read the verdict without a try/except, and only require() on
    # the caller's last line raises.
    def plan_grid_hook(ctx: GridPlanningContext) -> None:
        return None

    # No exception escapes; the verdict is returned.
    decision = plan_grid(plan_grid_hook)
    assert decision.adopted is False


# ---------------------------------------------------------------------------
# PlanGridDecision.require — the bridge that raises on the caller's last line
# ---------------------------------------------------------------------------


def test_require_returns_the_plan_on_admission() -> None:
    # On an admission, require() returns the admitted plan — the exact plan the
    # hook authored — so a caller can write ``plan = law.plan_grid(fn).require()``
    # and have feature 229 enforced there.
    def plan_grid_hook(ctx: GridPlanningContext) -> GridPlan:
        return GridPlan(branch_count=5, refine_count=1)

    decision = plan_grid(plan_grid_hook)
    plan = decision.require()
    assert plan.branch_count == 5
    assert plan.refine_count == 1


def test_require_raises_naming_the_policy_on_refusal() -> None:
    # On a refusal, require() raises PlanGridRefusal with the refusal's own
    # sentence — the bridge between the returned verdict and the exception a
    # caller wants on its last line before admitting a policy.
    def plan_grid_hook(ctx: GridPlanningContext) -> None:
        return None

    decision = plan_grid(plan_grid_hook)
    with pytest.raises(PlanGridRefusal):
        decision.require()


def test_plan_grid_refusal_is_a_policy_runtime_error() -> None:
    # PlanGridRefusal is a PolicyRuntimeError, so a caller catching the read-side
    # path's one base class catches a planning refusal too — the single-except
    # discipline bootstrap.errors and artifacts._errors state.
    assert issubclass(PlanGridRefusal, __import__("policy_runtime").PolicyRuntimeError)
