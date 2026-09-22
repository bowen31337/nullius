# Feature 236 — Frontier-difficulty depth allocation

**app_spec.xml, "Discovery Orchestrator & Campaigns", feature 236**
(`plugin="discovery"`, `depends_on=235`): *System computes a per-branch
difficulty weight targeting a success rate near 0.2, which returns a depth
allocation favouring the agent frontier.*

Authoritative spec, PRD §428, which states the formula:

> **Frontier-difficulty depth allocation.** `plan_grid` as originally specified
> chooses width versus depth from prior manifests but has no notion of difficulty
> targeting, so it cannot tell an exhausted theme from an unexplored one. Borrow
> the mechanism from self-improving-model training: target a per-branch success
> rate near `p* ≈ 0.2`.
>
> ```
> D(branch) = exp( −(p_branch − p*)² / 2σ² )      p* = 0.2
> ```

and PRD §434, which states the shape the whole suite is written against:

> A branch where nearly every refinement succeeds is saturated and loses
> allocation; one where nothing succeeds is beyond the agent's frontier and also
> loses it. Depth flows to branches sitting at the edge of what the discovery
> agent can actually do, which is where the informative trials are. Computable
> entirely from prefix information, and it drops into the same `_schedule(beta)`
> dict as every other threshold.

235 owns the flat base grid; **236 is the per-branch skew 235 explicitly defers
to it** (*"Features 236 and 237 then skew this base grid per branch, by
difficulty and by saturation; a base that already favoured an axis would make
their allocation a correction of this module's opinion rather than of the
evidence"*). 237's budget-*level* reduction for a saturated branch is built on
top of this and is not stated here.

## Where it lands

`packages/discovery/src/discovery/difficulty.py` — a new module, reached
directly from `discovery` exactly as 235's derivation is. Three public values:

| name | what it is |
|---|---|
| `difficulty_weight(rate)` | PRD §431's kernel at a measured success rate |
| `BranchDifficulty` | one branch's evidence (theme root, refinements, successes) and the weight it earns |
| `DepthAllocation` / `allocate_depth(plan, branches)` | the plan's depth budget split across the census by weight |

## The shape decisions

**236 consumes 235's budget rather than re-deriving a grid.**  `allocate_depth`
takes a plan — feature 235's `GridPlan`, or any object carrying `branch_count`
and `refine_count` — and redistributes `branch_count * refine_count`
refinements. That is the seam 235's docstring names, and it is why the
allocation is a *skew* of a flat base rather than a second planner.

**The reads are duck-typed, the same way 235's are.**  The two counts are taken
*by name*, so the policy-runtime member's `GridPlan` — the value feature 229's
admission law judges, which no member may import — fills this budget without a
conversion. Pinned against the sibling's *real* value, not a stand-in.

**`p*` is a citation; `σ` is a named default.**  §431 writes `0.2` literally, so
`TARGET_SUCCESS_RATE = 0.2` cites it. **No document states `σ`**, so
`DIFFICULTY_BAND = 0.2` is a default parameterization stated as a named constant
with its consequences written out in its comment (weights at `p = 0.0`, `0.4`,
`1.0`), the stance feature 228 takes for `PRIOR_STRENGTH` and 227 for its bands.
It is deliberately *not* a transcribable number dressed as a law.

**The asymmetry between the two failures is a consequence, not a second rule.**
Because `p* = 0.2` and not `0.5`, a saturated branch sits `0.8` from the target
and a barren one only `0.2`. At the stated band: `p=0` keeps `exp(-0.5) ≈ 0.607`,
`p=1` keeps `exp(-8) ≈ 0.0003`. §434's *"saturated and loses allocation; one
where nothing succeeds is beyond the frontier and also loses it"* — both lose,
unequally, from one expression.

**The unmeasured branch is the case PRD §428's complaint turns on.**
*"it cannot tell an exhausted theme from an unexplored one"* — so the two must be
different answers, and they are:

| branch | `success_rate` | `weight` |
|---|---|---|
| refined, never succeeded | `0.0` (measured) | `exp(-0.5) ≈ 0.607` |
| refined nothing | `None` — **no rate** | `TARGET_WEIGHT = 1.0` |

An unprobed branch is *assumed to sit at the target* — feature 228's *"a new
theme starts at the prior, exactly"* on this feature's axis — so the allocation
does not score it as tried and found wanting. The assumption and the measurement
coincide only where a measurement lands on the target, which is deliberate.

**The budget is conserved exactly, in exact rational arithmetic.** Largest-
remainder apportionment, with every weight lifted by `Fraction(a_float)` (the
float's *exact* value) so quotas, floors and remainders are compared as
rationals rather than by a rounding mode. Ties break by theme root — a truth no
arithmetic can manufacture — so a split is order-insensitive. `DepthAllocation.total`
is *derived* by summing the depths, never a second field: the value cannot
disagree with itself about how much depth it spends.

**A zero-depth branch is present at zero, not absent.**  Absence is a second
statement — *this branch was not considered* — and it is exactly the wrong thing
to say about the branch the feature just indicted. It is also what lets 237 find
the saturated branch to reduce.

## Judgment calls flagged for review

- **No new error class.**  A rate that is not a proportion, a plan missing its
  counts, an empty census, a duplicated theme root — every one is a fact about
  the *request*, so all wear `CampaignPlanningError` (235's split-by-repair,
  restated). Consequence: `except CampaignPlanningError` catches a
  difficulty-kernel refusal as well as an ask error.
- **An empty census is refused** — deliberately *not* 235's empty-history path.
  There, no evidence means a deployment that never ran a campaign and still needs
  a grid; here there is a grid and nothing to spend it on.
- **A duplicated theme root is refused**, naming every repeat. The theme root is
  the branch's identity in this census; two entries under one identity would let
  one silently take the other's depth. Repair is the caller's: one branch per
  theme root.
- **The census need not have `plan.branch_count` entries.**  The plan is the base
  the caller projects onto the branches its tree actually opened, and whether a
  campaign opened as many roots as it planned is a fact about its execution, not
  about this request. A refusal here would demand a correspondence this seam
  cannot verify.
- **A rate of `0` is refused *as a rate*** — for `p = 0` the refusal is
  `bool`/non-real/out-of-range/`NaN` only. `0.0` is a perfectly good rate (a
  measured-barren branch) and is accepted; the `NaN` refusal is load-bearing
  because every comparison against `NaN` is false, so a `NaN` weight would
  apportion by sort order rather than by evidence, silently.
- **Which themes are legal is not this module's check.**  `theme_root` is
  validated structurally only (non-empty text) — a second spelling of feature
  241's configured set would be the drift both features exist to prevent. An
  unknown theme is not an error; it measures a rate and earns a weight.
- **No component.**  Third seam in the member with no seat. Both earlier reasons
  apply (a builder takes no arguments; this closes over no deployment state) plus
  a sharper one: the census is *current-episode* evidence, the one thing feature
  233's boundary keeps a planning step away from. A registered allocation would be
  a component pointed at an episode composition cannot supply.

## Files

| file | change |
|---|---|
| `packages/discovery/src/discovery/difficulty.py` | **new** — the kernel, `BranchDifficulty`, `DepthAllocation`, `allocate_depth`, the rational apportionment and the ask validators. Stdlib only (`math.exp`, `fractions`, `numbers`); no third-party import at module scope. |
| `packages/discovery/tests/test_difficulty.py` | **new** — 53 tests, no basename collision (`test_difficulty*.py` unused across the workspace). |
| `packages/discovery/src/discovery/__init__.py` | re-export the new surface (no new `@register`); narrative paragraph on 236's module and why it adds no component |
| `src/app/modules/discovery/__init__.py` | docstring only — the seat notes the third seam with no seat |
| `.plans/feature-236-frontier-difficulty-depth-allocation.md` | this plan |

No shared or order-sensitive file is edited: no `migrations/**`, no
`src/app/middleware.py`, no `src/app/settings.py`, no app factory, no module
registry, no `additions_spec*.xml`, and **no sibling member** — 229's plan value
is duck-typed, not imported.

## Verification

```bash
export UV_CACHE_DIR="$(pwd)/.claw-forge/tmp/uv-cache"
uv sync --all-packages                              # the graded tree needs polars/pyarrow

uv run pytest packages/discovery/tests -q           # 659 passed
                                                    #   = 606 (235's baseline) + 53 new
uv run pytest tests -q                              # 1060 passed, unmoved
uv run ruff check packages/discovery/src/discovery/difficulty.py \
                  packages/discovery/tests/test_difficulty.py
                                                    # All checks passed
```

`__init__.py` lint is **byte-identical to HEAD**: 4 × F811 + 1 × I001, the I001
being the pre-existing `THEME_ROOT_COLUMN` / `THEME_ROOTS_COLUMN` swap feature
233's notes record (verified by running ruff over `git show HEAD:<file>` and
comparing `--statistics`).

Composition is untouched: `create_app().order` still contains `"discovery"`, the
component is still feature 232's single `CampaignRecords`, and no
`build_*difficult*` appears in the member namespace.

## What this feature does not do

- **No saturation rule.**  PRD §428's *"reduces allocation for a saturated
  branch"* as a stated *budget-level* response is feature 237's. 236's kernel
  already ranks a saturated branch lowest and floors it to zero on its own; what
  237 adds is the reduction on top.
- **No `_schedule(beta)` entry.**  §434 says the band *"drops into the same
  `_schedule(beta)` dict as every other threshold"* — that dict is feature 227's,
  in the policy-runtime member, and wiring this band into it is the policy's
  authoring, not this member's.
- **No store, no I/O, no component.**  The census reaches the allocation from the
  caller's prefix; the plan from 235's derivation or a policy's hook.  This is why
  the entire suite runs with no fixture.

## A claim that a test corrected

The first draft of the frontier test asserted `barren < even split < frontier`.
That is **false**, and the suite caught it: a measured-barren branch weighs
`exp(-0.5) ≈ 0.607` against the frontier's `1.0`, so its share of a 30-refinement
budget over three branches is ≈ 11.3 — a shade *above* the even split of 10,
because the saturated branch has been all but eliminated from the denominator.
The assertion now states the ordering §434 actually implies (`frontier > barren
> saturated`, with the frontier above the even split) and the docstring records
why barrenness is penalised while saturation is eliminated.

A second pass found the apportionment's zero-weight-sum guard documented in
`_apportioned` but never exercised — reachable only by narrowing the band, since
the minimum weight under the stated band is nowhere near an underflow. Two tests
now drive it, using a JUnit `monkeypatch` so the narrowed band cannot leak into
the tests that follow (verified in-process: the global is restored).
