# Feature 237 — The saturation response

**app_spec.xml, "Discovery Orchestrator & Campaigns", feature 237**
(`plugin="discovery"`, `depends_on=236`): *System reduces allocation for a
saturated branch where nearly every refinement succeeds, which returns a
lowered depth budget.*

Authoritative spec, PRD §434, the same sentence feature 236 is built on:

> A branch where nearly every refinement succeeds is saturated and loses
> allocation; one where nothing succeeds is beyond the agent's frontier and also
> loses it. Depth flows to branches sitting at the edge of what the discovery
> agent can actually do, which is where the informative trials are. Computable
> entirely from prefix information, and it drops into the same `_schedule(beta)`
> dict as every other threshold.

236 owns the relative skew (`D(branch) = exp(−(p−p*)²/2σ²)`, `p* = 0.2`) and
says 237's *budget-level* response is *"built on top of"* it and *"not stated
here"*. This feature is that response.

## The gap it fills — stated in arithmetic, not in prose

236's apportionment is **proportional**, hence scale-free: multiplying every
weight in a census by any positive constant leaves the allocation identical. So
236 **cannot lower a budget it ranked uniformly**. Two branches each at `p = 1.0`
weigh `exp(−8) ≈ 0.00034` apiece and 236 hands them the even split — the whole
campaign budget — having ranked them correctly and with no way to spend less.
"Nearly every refinement succeeds" is a fact about *one branch*, not about a
comparison between branches, and 236 has only the latter vocabulary.

The window where 237 actually bites is narrow and worth naming: 236's kernel is
steep, so a saturated branch beside a **frontier** one is already floored to
zero by 236 alone (three orders of magnitude in weight). What 237 lowers is a
census whose branches are **all** far from the target — the split is
non-degenerate, every branch keeps a real share, and only this rule can reduce
the total. That is precisely the campaign §428's complaint describes.

## Where it lands

`packages/discovery/src/discovery/saturation.py` — a new module, reached
directly from `discovery` exactly as 235's and 236's are. Four public names:

| name | what it is |
|---|---|
| `SATURATION_RATE` | `0.8` — the rate at or above which a branch is saturated (named default) |
| `SATURATION_RETENTION` | `0.5` — what a saturated branch keeps (named default) |
| `is_saturated(branch)` | the judgment over one `BranchDifficulty` |
| `reduce_saturated(allocation, branches)` | the verb: a lowered `DepthAllocation` |

## The shape decisions

**A level, where 236 is proportional.** `is_saturated` judges one branch's
measured rate against a threshold; `reduce_saturated` applies that judgment to
the split 236 apportioned. This is why the reduction lowers the total *even when
every branch is saturated* — the property 236 provably cannot deliver.

**The freed depth is not re-spent.** Redistribution is 236's mechanism and its
whole purpose; 237's contribution is the statement that a campaign with a
saturated branch has *less* worth spending than the plan assumed. A plan is the
most a campaign may spend, not a quantity it owes the tree. Handing the freed
units to a frontier branch here would also make 237 a second apportionment rule
competing with 236's about the same units.

**Both knobs are named defaults; no document states either.** PRD's entire
vocabulary is *"nearly every refinement succeeds"* — no rate, no fraction. So
`0.8` and `0.5` are stated as constants with their consequences in their own
comments, the stance 236 takes for `DIFFICULTY_BAND` and 228 for
`PRIOR_STRENGTH`. Both are read **at call time**, so replacing either moves
every verb together, and `_validated_knobs` refuses a value outside `[0, 1]`
rather than letting a retention above 1 silently turn the reduction into an
inflation. The threshold comparison is **inclusive** (four in five is the least
"nearly every refinement" describes).

**A retention, not a reduction amount, and the reason is structural.**
`floor(depth × retention)` is at most `depth` for every retention in `[0, 1]`,
so the verb lowers and can never raise — the bound holds by the multiplication
rather than by a check a rewrite could drop. `1.0` is the knob's boundary and is
inside the range: at that value the verb is the identity, which is the value a
deployment reaches by saying the response is wrong for its campaigns.

**The multiplication is exact.** `Fraction(depth) × retention` (the retention
held as a `Fraction` of the constant's exact value), floored from the numerator
and denominator — 236's stated rational discipline applied to one
multiplication. `floor(20 × 0.3)` is `6` as a float and `5` as the exact
product; only the second is a reduction a campaign is reproducible under.

**The census law is 236's, reused rather than restated.** `reduce_saturated`
validates through `discovery.difficulty._validated_census` — *the same function
object* `allocate_depth` uses. A second validator would be a second law for one
batch, and the drift would show as two seams disagreeing about what a census is.

**The allocation and the census must name the same branches** — the one check
this module adds. A branch with depth but no evidence has its saturation
unjudged (and judging absent evidence unsaturated understates the response,
while judging it saturated invents the measurement); a branch with evidence but
no depth is one campaign's allocation lowered by another's evidence. Both
directions are named in one refusal.

**The unmeasured branch is not saturated; neither is a barren one.**
`success_rate` is `None` for a branch that has refined nothing, and `None` is
not a number above any threshold — so the one branch 236 assumes sits *at* the
target (its kernel maximum) is the one a reduction must not reach. A barren
branch has a rate (`0.0`) and §434 gives it to the kernel, which penalises and
does not eliminate.

## Judgment calls flagged for review

- **No new error class.** A value that is not an allocation, a batch 236 cannot
  read, a split and census that disagree, a knob outside its range — every one
  is a fact about the *request*, so all wear `CampaignPlanningError`. A single
  `except DiscoveryError` still catches the whole pipeline.
- **Not duck-typed, unlike 236's plan reads.** A `GridPlan` has a second
  spelling in the policy-runtime member that no member may import, so 236 reads
  by name. A `DepthAllocation` is *this member's own value* with no sibling
  spelling — so it is checked as one, and a wrong value is a caller's mistake
  rather than another vocabulary.
- **A census with nothing saturated returns the split unchanged.** A response is
  not an obligation; refusing because "this is not a saturated campaign" would
  turn a rule that fires sometimes into a precondition every campaign must meet.
- **No redistribution, no re-application detection.** See above; a
  `DepthAllocation` is a split and carries no record of how it was arrived at,
  which is why the correspondence check earns its place instead. The
  orchestrator applies this once per campaign, in the order 235 → 236 → 237.
- **No component.** The feature with two tunable knobs is where a component
  looks most tempting, so the reason is stated at length: a builder takes no
  arguments (so a threshold would have to be read from the environment — a
  second configured surface beside 241's) and is built on every `create_app()`
  call (while this verb is a function of an allocation and a census the factory
  holds neither of, the census being current-episode evidence — 236's own
  disqualification).

## Files

| file | change |
|---|---|
| `packages/discovery/src/discovery/saturation.py` | **new** — the two named defaults, the predicate, the verb, the reduction arithmetic and the ask validators. Stdlib only (`math`, `numbers`, `fractions`); no third-party import at module scope. |
| `packages/discovery/tests/test_saturation.py` | **new** — 22 tests, no basename collision (`test_saturation*.py` unused across the workspace). |
| `packages/discovery/src/discovery/__init__.py` | re-export the new surface, 236/237 module lines in the enumeration, and the "237 adds no component" paragraph |
| `src/app/modules/discovery/__init__.py` | docstring only — the seat notes the fourth seam with no seat |
| `.plans/feature-237-saturation-response.md` | this plan |

No shared or order-sensitive file is edited: no `migrations/**`, no
`src/app/middleware.py`, no `src/app/settings.py`, no app factory, no module
registry, no `additions_spec*.xml`, and no sibling member.

## Verification

```bash
export UV_CACHE_DIR="$(pwd)/.claw-forge/tmp/uv-cache"
uv sync --all-packages                              # the graded tree needs polars/pyarrow

uv run pytest packages/discovery/tests -q           # 680 passed
                                                    #   = 658 (236's baseline) + 22 new
uv run pytest tests -q                              # 1060 passed, unmoved
uv run ruff check packages/discovery/src/discovery/saturation.py \
                  packages/discovery/tests/test_saturation.py
                                                    # All checks passed
```

`__init__.py` lint is byte-identical to HEAD: 4 × F811 + 1 × I001, compared by
`--statistics` against `git show HEAD:<file>`.

Composition is untouched: `create_app().order` still contains `"discovery"`, the
component is still feature 232's single `CampaignRecords`, and no
`build_*saturat*` appears in the member namespace.

## What this feature does not do

- **No `_schedule(beta)` entry.** §434 says the band *"drops into the same
  `_schedule(beta)` dict"* — that dict is feature 227's, in the policy-runtime
  member, and wiring it is the policy's authoring.
- **No store, no I/O, no component.** The split arrives from 236; the census
  from the caller's prefix. The entire suite runs with no fixture.
- **No second apportionment.** The freed depth is not redistributed; see above.

## What the probes found

Two things the tests corrected, both recorded rather than papered over:

1. **The mixed census is a no-op.** The first draft asserted a lowering on
   `[p=1.0, p=0.2]`. 236 already floors the saturated branch to zero there — the
   weights differ by ~3000×, and no budget recovers a whole refinement from that
   ratio. The tests were rewritten onto the window that is actually 237's, and
   `test_the_reduction_bites_where_236_cannot_make_it` now pins **both** windows
   side by side so a reader does not have to discover the first by trying it.
2. **The exact-arithmetic test needed a depth where the two spellings differ.**
   At retention `0.5` no such depth exists, so the test drives `0.3` and asserts
   the float and exact floors *disagree* at the depth it uses (`20`) before
   asserting which one the module answers — otherwise the passing assertion
   could be a coincidence. Finding that depth needed a search over censuses and
   budgets (`p=0.8` against `p=0.7` on a `2 × 50` plan).
