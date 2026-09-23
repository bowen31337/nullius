# Feature 281 — The paired continuous statistic

**app_spec.xml, "Dreaming Loop & Meta-Selection", feature 281**
(`shape="plugin"`, `plugin="dreaming"`, `depends_on="278"`, `covers="cq-5"`):
*System rejects a difference-in-proportions comparison, using a paired
continuous statistic over the same worlds instead.*

A sixth sentence in the existing dreaming member (`packages/dreaming/`), not a
new member: the statistic §12's M3 gate judges with, and the refusal that keeps
the proportion comparison off the table.

## The sentence, in two halves

The feature text is one sentence with a **rejects** and an **instead**, and both
halves are the PRD's own. §11.0 states the first:

> Raw FDR is a proportion, and proportions are power-poor. Detecting
> `0.30 → 0.21` at 80% power needs ~364 independent commits per arm; replays
> clustered by world inflate that by the design effect to well over a thousand.
> **That test is not buildable at this scale.**

…and then the second, which is the fix:

> **Fix the statistic, not the ambition.** Score each commit continuously using
> the out-of-sample IR of the committed pick, which is continuous and zero in
> expectation under the null, and run the comparison **paired** — same policy
> pair, same worlds. A paired t-test detecting `ΔIR = 0.3` with `σ_diff ≈ 0.8`
> needs ~56 worlds, which is reachable.

docs/nullius-tech-architecture.md §10.3.1 restates it as the reason the M3 gate
is written the way it is: *"Policy comparison uses a **paired** continuous
statistic — OOS IR of the committed pick, same policy pair on the same worlds —
not a difference in proportions."*

## Why this is a module and not a convention

The quantity M3 reads is `FDR_deploy` — a **proportion** — and every arm of the
loop produces a binary outcome per committed pick. So the unpaired comparison is
not a mistake a caller might make; it is the one they will naturally reach for.
A convention would leave it available and merely discouraged, and its failure
mode is the one §12 names for the whole system: *it returns a number, the number
looks like a p-value, and the conclusion it supports is wrong.* Under-powering
does not announce itself. So the refusal is a **raised error** and the
replacement is a function the caller reaches instead.

## The design decision: two effect sizes, because §11.0 names two

The hardest call in the feature, and the one the first draft got wrong.

§11.0's two worked examples use **different quantities on different scales**: the
proportion pair differs by `0.30 − 0.21 = 0.09` (a shift between two *rates*),
and the paired example is `ΔIR = 0.3` (a difference between two *continuous*
readings). Both formulas take "a difference", so a signature with one `delta`
sizes one of the two tests at the other's figure — inflating the proportion
requirement by `(0.3/0.09)² ≈ 11×`, or shrinking the paired one until the M3
precondition loses its meaning. Either way the result is a plausible integer and
nothing announces the substitution.

So `rejects_proportion_comparison` takes `rate_delta` **and** `delta` as
separate required keywords, and the caller states each figure it means.
Defaulting one to the other was the tempting edit and is the same failure
spelled less visibly.

## The design decision: the refusal is grounded in the pool's capacity

The feature says *rejects*, and the tempting implementation is a refusal that
always fires — which would also be wrong: a pool genuinely large enough to fund
a proportion test is a pool where that comparison is legitimate. So the function
compares **two capacities** and refuses only where the evidence does not support
the ask:

| `arm_size` | outcome |
|---|---|
| `< ~56` (the paired requirement) | refused — the **M3 precondition**; repair is *accumulate worlds* |
| `56 … < ~1460` (the clustered proportion requirement) | refused — **the feature's own sentence**; repair is *fix the statistic* |
| `≥ ~1460` | **admitted** — nothing to refuse |

The middle band is the whole point: the size buys the paired comparison and does
not buy the proportion one, so the comparison that works is available and the one
being asked for is not. The two refusals name different repairs, which is why
they are distinguishable in the message rather than only in the class.

The precondition is asked **first** and asked of the *paired* requirement,
because that is the figure §12's M3 gate is written against — otherwise a caller
with an enormous `rate_delta` could shrink the proportion requirement below its
arm size and slip past an unfunded pool.

Asking it first is not merely tidy: **the two requirements are not ordered
relative to each other.** A large enough `spread` — a pool whose worlds
disagree wildly — makes the paired test *harder* than the proportion one, so
`paired_needs > needed` and the band between them is **empty**. An
implementation that checked `count >= needed` first would then admit an arm that
funds the proportion test and not the statistic M3 is written against: the
feature's sentence inverted, arrived at from the other side. This was a real
bug in the first draft, found by probing the edge case rather than by the tests,
which all sat in the ordinary `spread = 0.8` regime where the band is wide.

## The design decision: the pairing is the statistic

A world only one arm carries is **refused**, never dropped. Dropping is the
silent failure the whole feature is about: it converts the comparison into the
*unpaired* one §11.0 rejects — the two arms averaged over different world sets —
while the `t` figure that comes out still looks paired. The same claim appears
at three levels:

* `paired_ir_difference` requires the two world sets to be **exactly equal**,
  and requires at least two paired worlds (one difference has no spread);
* an arm that is a bare sequence of figures is refused, because without world
  ids there is nothing to pair on and accepting it would mean pairing **by
  position** — the unpaired comparison wearing the paired signature;
* `paired_pool_difference` reads both arms from **one table keyed by
  `world_id`**, so the pairing is a fact about the store rather than about the
  caller's bookkeeping.

## Arithmetic: reproduced, not quoted

Both of §11.0's figures are **derived** by the module, which is what the test
suite pins hardest — a refusal that fired on everything would pass every other
test in the file:

```
power_capacity(0.3, spread=0.8)                    →  56          (PRD: "~56 worlds")
_proportion_arm_size(0.30, delta=0.09)             → 365          (PRD: "~364 per arm")
  … × PROPORTION_DESIGN_EFFECT (4.0)               → 1460         (PRD: "well over a thousand")
```

Appendix B writes the paired figure as `n ≈ 8(σ_diff/Δ)²`; the `8` is not a
constant the module may hard-code — it is `(z_{α/2} + z_β)²` at 95%/80%, which
is what `power_capacity` computes, and the test recomputes it from the quantiles
so the agreement is a claim about the *formula*. The proportion side is the
standard two-sample sizing over §11.0's own rate pair, which is why it lands on
364.25 → 365 rather than on a quoted figure.

The clustering factor is a **named knob** (`PROPORTION_DESIGN_EFFECT`), not
modelled: §11.0 gives "well over a thousand" as an order-of-magnitude floor, and
a caller with a measured design effect passes its own.

## Surface

| name | what it is |
|---|---|
| `paired_ir_difference(candidate, baseline, *, spread, delta, power)` | the feature's call — two arms in, a `PairedDifference` out |
| `paired_pool_difference(candidate_policy, baseline_policy, *, database_url, …)` | the store seam — arms read from `replay_score` by `policy_version` |
| `rejects_proportion_comparison(proportion, *, arm_size, rate_delta, delta, spread, power)` | the **rejects** — a verdict over figures the caller holds, never a count |
| `power_capacity(delta, *, spread, power)` | Appendix B's `n`, generalised to any power |
| `PairedDifference` | the record: means, paired differences, spread, SE, `t`, two-sided `p`, `clears()`, `row()` |
| `ProportionComparisonError` / `PairedComparisonError` | the two refusals, split by **repair** |

No `@register` component, no seat change, no migration — the feature is reached
as a free function from the member, exactly as `ladder`, `ceiling`, `cap` and
`split` are. It reads `replay_score`; it writes nothing, and a comparison taken
under feature 270's hold is permitted because it is a read.

## The two error classes, split by repair

This workspace splits error vocabularies by *the repair the caller must make*,
so feature 281's two faces divide by **what is wrong**:

* `ProportionComparisonError` (`proportion_comparison`) — the **question** is
  the wrong one. Repair: *ask for the paired statistic.*
* `PairedComparisonError` (`unpaired_worlds`) — the question is right and the
  **evidence** will not pair. Repair: *compare the arms over the worlds that
  carry both.*

Neither is feature 275's `pool_too_thin`, and that is the line worth pinning
hardest: the floor's repair is *grow the pool*, and a caller catching them
together would go looking for more worlds when its statistic was the problem —
or, in the other direction, be told to switch statistics while holding 40
worlds, which funds neither test. Both are siblings of every existing
`DreamingError` subclass, and `FreezeRequestError` from the URL seam is
**translated** rather than propagated.

## Files

| file | change |
|---|---|
| `packages/dreaming/src/dreaming/paired.py` | new — the statistic, the verdict, the store seam |
| `packages/dreaming/src/dreaming/errors.py` | two classes + `__all__` + the split's rationale |
| `packages/dreaming/src/dreaming/__init__.py` | the surface, re-exported |
| `packages/dreaming/tests/test_paired.py` | new — the feature's own suite |
| `packages/dreaming/tests/test_errors.py` | the sibling pin against the member's vocabulary |
| `packages/dreaming/tests/test_cross_member.py` | the read pinned against `0109`'s own executed DDL |
