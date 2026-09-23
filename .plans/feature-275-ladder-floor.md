# Feature 275 — The ladder floor refusal

**app_spec.xml, "Dreaming Loop & Meta-Selection", feature 275**
(`shape="plugin"`, `plugin="dreaming"`, `depends_on="270"`): *System rejects a
dreaming run when the pool holds fewer than 20 worlds, which returns a
`pool_too_thin` error message.*

A second sentence in the existing dreaming member (`packages/dreaming/`), not a
new member: the ladder-floor precondition that feature 270 deliberately does not
carry.

## The sentence, and why it is a second sentence, not a third face of feature 270

PRD §12.1 states the rule as a precondition *on a run that has not started*,
rather than as a caveat on one that is going:

> Below 20 worlds: **do not run dreaming.** Fixed exploration; accumulate
> history.

The ladder has three rungs, and only the top one dreams. §12.1's table reads
`< 20 worlds` as *do not run dreaming at all*; `20–50` as a capped, low-bar
sweep (feature 276 caps the revision count, feature 277 raises it once the pool
clears 50); and `50+` as full dreaming with the 70/30 split. This feature is the
floor of that ladder — the refusal that keeps a cycle from starting over a pool
too small to dream on — and it is the rung feature 276 and feature 277 build on.

The refusal is the M3 gate's younger sibling: where the gate (feature 187,
§10.3.1's `n > 53`) judges whether a *financial* claim has enough worlds to
dream *honestly*, this floor judges whether there are enough worlds to dream
*at all*.

**Why the floor is a refusal rather than a recommendation.** A dreaming cycle
over a handful of worlds has no statistical power: §10.3.1's selection bar is a
*paired* continuous statistic over holdout worlds, and a pair that small cannot
clear it with any confidence, while selecting the max over `M` revisions scored
on them is the multiple-testing problem one level up with nothing to average it
out — the same overfitting §12.1 names in its *"the dreaming loop overfits its
own replay pool"* and the reason feature 270 holds the pool fixed in the first
place. A pool below the floor does not make the bar *hard to clear*; it makes
the bar *meaningless*, so the run is refused rather than advised.

**Two sentences, two repairs, two classes.** Feature 270's subject is a cycle
that is *already running* and must not have its pool moved underneath it; its
code is `pool_frozen` and its repair is *stop writing, or close the iteration*.
This feature's subject is a run that *has not begun*; its code is
`pool_too_thin` and its repair is *grow the pool, or run fixed exploration*. The
two sentences have different repairs, so the workspace's error-vocabulary
discipline — a shared helper that raises another feature's error type defeats
the caller's `except` — forbids this feature from borrowing feature 270's
`PoolFrozenError`, and the two live as siblings under the one `DreamingError`
base. Pinned by `test_the_member_carries_the_ladder_floor_as_a_sibling`:
`PoolTooThinError` is a `DreamingError`, is **not** a `PoolFrozenError`, and its
code (`pool_too_thin`) is not `pool_frozen`.

## The design decision that shapes everything: a verdict over a count, not a count

`rejects_thin_pool(world_count, *, gate=20)` is a *judgment over a count the
caller already has*, and nothing more — the shape `bootstrap.
rejects_dreaming_claim` takes for feature 187's own verdict, and for the same
reason: a verdict is not a count, and a count is not the verdict.

The count the judgment reads is the pool's size, which this member already
computes — `dreaming.cycle.pool_commitment` returns `(digest, world_count)`, and
a feature-270 hold records `world_count` at the moment it opened — so a caller
obtains the figure from the same member it asks to judge, and this module never
opens a database or reads the pool itself. A module that counted the pool would
be answering a question about a store from inside a verdict, and would couple a
judgment to a connection it does not need.

The judgment is spoken as a **refusal**: `rejects_thin_pool` raises
`PoolTooThinError` when the pool is thin and returns otherwise, so a caller that
calls it on its last line is stopped before it begins. The message opens with
`pool_too_thin`, states the figure and the floor, names §12.1, and states the
repair.

## `pool_too_thin` — the floor's code, and its class

`POOL_TOO_THIN_CODE = "pool_too_thin"` and `PoolTooThinError(DreamingError)` live
in `dreaming.errors`, alongside feature 270's `DreamingError`,
`FreezeRequestError`, and `PoolFrozenError`. Both are re-exported from the
member `__init__`.

## The floor is a parameter, validated

The precondition a dreaming run must meet is the ladder floor's own world count,
which §12.1 states as 20 but which a deployment may set differently. The floor
is therefore a keyword of the refusal, `gate=20` by default (`LADDER_FLOOR_WORLDS
= 20`), validated by `validated_floor` to be a non-negative whole number so a
floor that is not a world count cannot silently admit or block a run. A `bool`
is refused where a count belongs (`True` is `1` in Python, so a flag where a
floor belongs would name the thinnest admissible pool). The figure is validated
the same way. A run is refused when the figure is below the floor; it is
admitted when it meets the floor — there is no upper edge, because the floor is
a power precondition and more worlds only strengthen the comparison.

Refuses, in this order: (1) a malformed figure, (2) a malformed floor, (3) a
figure below the floor. A malformed input is refused rather than answered, so a
run whose inputs are wrong is never silently admitted or blocked.

## No new component, no new table, no seat edit

Feature 275 adds no `@register` component — feature 270's single `"dreaming"`
component is untouched — and no table, and edits no seat. The floor is a free
function beside feature 270's store, the way `bootstrap.rejects_dreaming_claim`
is a free function beside the census. The seat (`src/app/modules/dreaming`)
still exports exactly `{COMPONENT_NAME, cycle_freeze_component}`, and its
`test_component.py` suite is untouched.

Stdlib only, and import-cheap: no `sqlite3`, no third-party import at module
scope, so the factory's scan — which imports the package to fire its `@register`
— pays nothing for the floor.

## Files

| file | what |
|---|---|
| `packages/dreaming/src/dreaming/ladder.py` | `POOL_TOO_THIN_CODE`, `LADDER_FLOOR_WORLDS`, `validated_floor`, `rejects_thin_pool` |
| `packages/dreaming/src/dreaming/errors.py` | `PoolTooThinError`, re-export |
| `packages/dreaming/src/dreaming/__init__.py` | re-exports, `ladder_floor` alias, docstring |
| `packages/dreaming/tests/test_ladder.py` | feature 275's claims, 25 tests |
| `packages/dreaming/tests/test_errors.py` | the absence-test flipped to a presence-test |
| `.plans/feature-275-ladder-floor.md` | this document |
