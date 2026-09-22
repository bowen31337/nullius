# Feature 235 — A grid plan derived from prior manifests

**app_spec.xml, "Discovery Orchestrator & Campaigns", feature 235**
(`plugin="discovery"`, `depends_on=233`): *System returns a grid plan carrying a
branch count plus a refine count derived from prior manifests.*

Authoritative spec, PRD §426:

> Plus `plan_grid(context) -> GridPlan(branch_count=W, refine_count=R)`, run
> **before** a campaign, using only prior-campaign manifests. **Never inspects the
> current episode.**

and PRD §428, which says which half of the derivation this feature owns:

> **Frontier-difficulty depth allocation.** `plan_grid` as originally specified
> chooses width versus depth from prior manifests but has no notion of difficulty
> targeting […] Borrow the mechanism from self-improving-model training: target a
> per-branch success rate near `p* ≈ 0.2`.

The width-versus-depth derivation is **235**; the difficulty targeting that sits on
top of it is 236/237. docs §605–§606 is the boundary the derivation runs inside,
and §5's *one campaign = one discovery tree* is why it must be a decision made from
history: a plan is what a campaign is *opened with*, so §4.1.1's fraction is fixed
at planning time rather than learned from the run.

## Where it lands, and why it is not 233's seam

233 (already at HEAD) owns **what a planning hook may read** — `PlanContext`, the
aperture holding the prior manifests and the two ceilings and nothing else, and
`plan_grid(hook, ...)`, which runs a caller's hook inside it and refuses one that
reaches past it. 235 owns the **system's own planner**: the derivation that runs
*inside* that aperture.

So `derive_grid_plan(ctx)` is deliberately written as a hook 233's seam admits
unchanged — one positional parameter, reading only the three permitted names. That
is the load-bearing shape decision: the boundary then holds **by construction**
rather than by a check. `plan_grid(derive_grid_plan, prior_campaigns=history)` is a
complete planning step, and the inspection record 233 keeps stays empty because
there is no name outside the three the derivation ever asks for. The member suite
asserts exactly that (`test_the_derivation_is_a_hook_feature_233_admits_unchanged`).

It is **not** "the" planner: §5 gives width, depth and themes to the policy, and
229's law requires every policy to author its own `plan_grid`. This is what the
*system* plans with when asked to plan from the record alone — the seeding plan a
fresh deployment opens, and the baseline a policy's plan is read against.

## The derivation

The history's measured refinement budget `B` (the mean `refine_count` of the prior
manifests) and `side = ceil(sqrt(B))`:

```
branch_count = side
refine_count = side      # per branch, §11.1's R
```

**The rebalance is the anti-convergence clause.** PRD §407: *"Without [the explicit
anti-convergence clause], a discovery tree collapses into 400 parameter tweaks of
one indicator."* A converged tree is an *aspect* — few branches, each refined very
deep — so the history's own aspect is the shape the next campaign must not
reproduce. Two properties are the argument, and both are asserted as arithmetic in
the suite:

- **the refinement budget is conserved** — the plan spends `side² ≈ B`, so the next
  campaign walks the depth budget this deployment has *demonstrated* it can walk;
- **the aspect is not conserved** — the history's refinements-per-branch ratio is
  replaced by one, the geometric midpoint between that ratio and its inverse. That
  is the split furthest from the convergence signature that still does not overshoot
  into the mirror-image failure (all breadth, nothing worth refining).

Note what is explicitly **not** conserved, because the first draft of this docstring
claimed it and the suite caught the overstatement: the history's **width**. The
plan's width is the *square root of the budget*, because the width is how the budget
is distributed rather than a second quantity to carry over. A history of 40 branches
is therefore rebalanced to *fewer* (4), not to at least 40.

**The budget is measured, never declared.** `B` is read off feature 242's completed
manifests, which are a census of the `node` rows each tree actually holds —
`discovery.manifest`: *"the summary reflects the tree that was walked, not a claim
about it."* A plan cannot be talked into a shape by a loop's own tally.

**All arithmetic is exact integer.** `-(-total // count)` for the ceiling-of-mean,
`math.isqrt(B - 1) + 1` for `ceil(sqrt(B))`. No float is constructed anywhere — a
census is a count and the plan derived from it is a count, so no plan can differ
between two machines by a rounding mode. `test_the_derivation_constructs_no_float`
pins this by AST (there must be no float literal and no `math.sqrt` call), not by
substring, because the docstrings discuss the arithmetic at length.

## The evidence's edges

| history | grid | why |
|---|---|---|
| empty | `W=16, R=30` | §606's *"including empty history"* — no evidence at all, so the grid is the architecture's own reference shape. docs §14.2 costs a campaign at `W=16, R=30` (~500 nodes at ~1.2k tokens each), so the empty-history path returns a campaign the docs already recognise rather than a default this module invented. |
| exists, refined nothing | `W=mean branches, R=0` | Evidence about **width alone**. The record says how wide this deployment's campaigns actually open and *nothing* about depth, so spending the reference's 30 would write a campaign nobody planned. `R=0` is the explore-only grid 229's law admits. |
| any other | `W=R=ceil(sqrt(B))` | The rebalance. |

The empty-vs-refined-nothing asymmetry is deliberate, and the suite pins both sides.

Two named constants carry docs §14.2's citation — `REFERENCE_BRANCH_COUNT = 16` and
`REFERENCE_REFINE_COUNT = 30` — and the suite transcribes `16`/`30` independently
rather than reading the constants, so a constant cannot agree with its own test.

## The ceilings

`max_branches` and `max_refinements` **cap** the derivation and never raise it.
The policy-runtime member's `GridPlanningContext` already says the bound is *"checked
by the caller (features 235/237), not here"* — this is that check, at the one place
a plan is authored. A plan that always equalled the ceiling would be a configuration
read wearing a derivation's name, and the reason the bound exists (a runtime cannot
run more slots than it has) only ever argues downward. `0` means *unset* — the
reading both 229's context and 233's state for the same two fields — so a generous
ceiling leaves the derivation exactly where the evidence put it.

**A ceiling may cap the width below the three theme roots PRD §9.3 and feature 234
require.** That refusal is deliberately left to feature 234, which names the themes
— the repair a caller needs is about the deployment's configuration and the policy's
declared themes, not about the grid. Clipping here *instead of refusing* would be
this module silently authoring a one-theme campaign.

## Judgment calls flagged for review

- **No themes in the value.** A manifest carries the *number* of distinct theme roots
  a tree spanned and never *which* ones, so a plan that filled a theme field would be
  inventing them. Features 234 (diversity of the policy's plan) and 241 (the
  configured legal set) own the themes. Consequence: this `GridPlan` has two fields
  where 229's has three — they are *not* the same class, and the cross-member test
  drives 229's value *constructor* over 235's counts rather than asserting type
  identity.
- **No new error class.** Every refusal here is a fact about the *request* — a context
  missing the three reads, a history that is not a batch of manifests, a count below
  its floor — so all of them are the member's existing `CampaignPlanningError`. A new
  class would be a second vocabulary for one sentence, which is the drift
  `tests/test_cross_member.py` exists to prevent. Consequence: `except
  CampaignPlanningError` catches a plan-value error as well as an ask error.
- **The adapters are restated, not imported.** 233's `_validated_history` and
  `_validated_ceiling` judge exactly the two reads this function judges and are
  private to their module — and `discovery.planner` itself states that rule (*"that
  helper is private to its module and no member reaches across one"*). The refusals
  here belong to a different act (*plan from this history*, vs *judge a hook that
  reached past it*). If a reviewer prefers the import, it is a small local change;
  the restatement is pinned by tests that drive both spellings over the same inputs.
- **`side` branches from a measured budget** rather than a configured width. The
  alternative reading — carry `W` over from history and derive only `R` — was
  rejected because it imports the history's aspect into the plan, which is the one
  thing the anti-convergence clause exists to break.
- **Duck-typed read of the context.** The three reads are taken by name, so a hook's
  author can hand over the policy-runtime member's `GridPlanningContext` directly.
  The suite pins the sibling's *real* context at the foot of the file.

## Files

| file | change |
|---|---|
| `packages/discovery/src/discovery/grid.py` | **new** — `GridPlan`, `derive_grid_plan`, the two reference constants, the rebalance and the ask validators. Stdlib only (`math.isqrt`, `dataclasses`); no third-party import at module scope, so the factory's scan pays nothing. |
| `packages/discovery/tests/test_grid_plan.py` | **new** — 35 tests, no basename collision (`test_grid*.py` is unused across the workspace). |
| `packages/discovery/src/discovery/__init__.py` | re-export the new surface (no new `@register`); narrative paragraph on 235's module and on why it adds no component |
| `src/app/modules/discovery/__init__.py` | docstring only — the seat notes the second seam with no seat, and why a plan is exactly the thing a builder must not be given |
| `.plans/feature-235-grid-plan-from-prior-manifests.md` | this plan |

No shared or order-sensitive file is edited: no `migrations/**`, no
`src/app/middleware.py`, no `src/app/settings.py`, no app factory, no module
registry, no `additions_spec.xml` (a sibling task edits it), and **no sibling
member** — 229's context and plan value are restated, not imported.

## Verification

```bash
export UV_CACHE_DIR="$(pwd)/.claw-forge/tmp/uv-cache"
uv sync --all-packages                              # the graded tree needs polars/pyarrow

uv run pytest packages/discovery/tests -q           # 606 passed
                                                    #   = 570 pre-existing + 1 previously-skipped
                                                    #     (now runs: the evaluator member is
                                                    #      installed after the full sync) + 35 new
uv run pytest tests -q                              # 1060 passed, unmoved
uv run ruff check packages/discovery/src/discovery/grid.py \
                  packages/discovery/tests/test_grid_plan.py
                                                    # All checks passed
```

Lint on the two touched shared-ish files is **byte-identical to HEAD**: 4 × F811 +
1 × I001, the I001 being the pre-existing `THEME_ROOT_COLUMN` / `THEME_ROOTS_COLUMN`
swap that feature 233's own notes record as pre-existing. Verified by running ruff
over `git show HEAD:<file>`. (Repo lint is red on main generally — mypy absent, 163
pre-existing ruff errors — so only the changed files were compared to a sibling.)

Composition is untouched: `create_app().order` still contains `"discovery"`, the
component is still feature 232's single `CampaignRecords`, and no `build_*grid*`
appears in the member namespace.

## What this feature does not do

- **No difficulty targeting.** PRD §428's `D(branch) = exp(−(p_branch − p*)²/2σ²)`
  and the saturation response are features 236 and 237; this module deliberately
  produces a *flat* base grid so their per-branch skew is a correction of the
  evidence rather than of this module's opinion.
- **No theme diversity check.** Feature 234's.
- **No store, no I/O, no component.** The prior manifests reach the derivation
  through feature 242's `CampaignManifests.completed()`, read by the caller. This is
  why the entire suite runs with no fixture.
