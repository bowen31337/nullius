# Feature 276 — The middle rung's ceiling

**app_spec.xml, "Dreaming Loop & Meta-Selection", feature 276**
(`shape="plugin"`, `plugin="dreaming"`, `depends_on="275"`): *System rejects a
revision count above 10 while the pool holds between 20 and 50 worlds, so the
selection bar stays low.*

A fourth sentence in the existing dreaming member (`packages/dreaming/`), not a
new member: the row between the floor (feature 275) and the raise (feature 277).

## The sentence, and the rung it completes

§12.1's ladder table now has all three of its rows carried by this member:

| Pool size | Operating regime | carried by |
|---|---|---|
| < 20 worlds | **Do not run dreaming.** Fixed exploration | feature 275, `ladder.py` |
| 20–50 | Dreaming with `M` capped at 8–10 so the selection bar stays low | **feature 276, `ceiling.py`** |
| 50+ | Full dreaming, `M = 30–40` | feature 277, `cap.py` |

Features 275 and 277 are the *other* two rows and this one sits between them.
It is also the only one of the three that is a **ceiling** — a refusal of a
count the caller asked for — rather than a figure the system answers with. The
band is not merely admissible; it is admissible **at a bounded `M`**, and a
cycle that runs a wider sweep on it is stopped before it runs rather than
warned after it has selected.

## Why the ceiling exists — the selection bar

§12.1's warning is that the dreaming loop *"overfits its own replay pool"*: the
paper's `V^{m★} ≥ V^0` guarantee holds on the *fixed history*, and selecting
the max over `M` revisions scored on a handful of worlds is the same
multiple-testing problem one level up. Appendix B's bar is exactly the width of
that problem —

```
true_advantage  >  √(2 ln M) · σ_V / √n_worlds
```

— and `M` enters it, so a wider sweep widens the bar the *selected* revision is
later judged against. §12.1's own arithmetic is the whole argument: at `M = 40`
with `σ_V ≈ 0.8` and a target advantage of 0.3 it needs **n > 53 worlds**, and a
pool of 20–50 is short of that by construction. Nor is the `M` dependence the
small term: a bar at `M = 40` is `√(ln 40 / ln 10) ≈ 1.27×` the bar at `M = 10`,
so an uncapped sweep on the thin rung judges its winner against a bar ~27%
wider than the rung can afford — while the `n > 53` it needs is precisely what
the *next* rung waits for. That is what "so the selection bar stays low" means,
and §12.1's "cap policy complexity" is the same sentence from the other side.

## The design decision: the band's figures are consumed, not respelled

The temptation — and what a naive implementation does — is to write the band's
`20`, `50` and `10` into the new module. Three features spelling the same ladder
is three things to keep in sync at the one place a disagreement costs a cycle
its statistical honesty, and feature 277's own module already refused that
split in prose: *"this module only answers what a cycle on that rung runs
under"*, with `CAPPED_SWEEP_CAP = 10` stated there as the band's cap.

So `ceiling.py` spells **no ladder figure of its own**:

- `ceiling` defaults to `dreaming.cap.CAPPED_SWEEP_CAP`;
- `full_dreaming` defaults to `dreaming.cap.FULL_DREAMING_WORLDS`;
- `floor` defaults to `dreaming.ladder.LADDER_FLOOR_WORLDS`.

The consequence is the property worth having: **the number a cycle is entitled
to and the number it is refused above are one object.** The default judgment
admits exactly what `revision_cap(world_count)` answers, at every pool size, by
construction rather than by agreement — pinned two ways in the suite (over
`range(20, 200)`, and the `is`-identity of the constants). Note this is *not* a
`depends_on` on 277: the two features are siblings under 275 in the spec and
neither is declared to depend on the other; the sharing is of a PRD figure, read
from the module that states it, which is the same discipline `errors.py` already
records for the 10.

## The judgment: a verdict over counts the caller already has

`rejects_uncapped_sweep(revision_count, world_count, *, floor=20,
full_dreaming=50, ceiling=10)` — the same shape feature 275's
`rejects_thin_pool` takes, and for the reason that module gives: a verdict is
not a count, and the count is the caller's to supply. It **raises** on refusal
so a caller that calls it on its last line is stopped before the sweep begins,
and it opens no database, reads no pool row, resolves no path.

Both figures are already in hand at that point in the loop: the pool's size is
what the hold the cycle opened recorded (`FreezeRecord.world_count`), and the
revision count is the caller's own intent.

**Three regions, and the ceiling applies to exactly one:**

| pool | verdict |
|---|---|
| `>= 50` | **admitted, whatever the count** — the raise has fired; `M` is feature 277's to answer at 40 |
| `20 .. 49` | `count <= 10` admitted; `count > 10` **refused** |
| `< 20` | **refused by the ladder** — `pool_too_thin`, feature 275's, delegated |

The top region is load-bearing: refusing a wide sweep above the band would
leave the top rung refusing the very figure §12.1's bar calculation is written
at. The bottom region is load-bearing for the opposite reason — a pool that may
not dream at all needs no cap on its sweep — and the delegation is what
`depends_on="275"` means in code, restated from feature 277's schedule.

## The vocabulary: one sibling, and deliberately no code word

`RevisionCeilingError(DreamingError)`, whose repair is its own: *lower `M` to
the band's cap, or grow the pool until the raise applies*. The two classes a
caller could otherwise catch it as both name repairs that are wrong here —
`PoolTooThinError` means *do not dream at all, grow the pool first* (this pool
may dream, just not that widely), and `CapRequestError` means *the ask was
malformed* (a count of 40 is well formed, and legal one rung up where feature
277 answers it).

No code word: feature 275's `pool_too_thin` is mandated by its own sentence
(*"which returns a `pool_too_thin` error message"*) and feature 276's mandates
none — it names its subject in prose. So every message opens with its subject
(the count, the ceiling, the pool's size, both band edges), states the repair,
names §12.1, and cites Appendix B's `sqrt(2 ln M)` bar and the section's
`n > 53` at `M = 40`. The refusal order is documented and tested: malformed
counts and edges, then the ladder's floor, then the boundary-below-floor case,
then the malformed ceiling, then the thin pool, then the ceiling itself.

## Files

| file | what |
|---|---|
| `packages/dreaming/src/dreaming/ceiling.py` | `rejects_uncapped_sweep` + the three input validators |
| `packages/dreaming/src/dreaming/errors.py` | `RevisionCeilingError`; docstring's third-rung paragraph |
| `packages/dreaming/src/dreaming/__init__.py` | re-exports; the member docstring's fourth sentence; removed a duplicated "not the evaluator" paragraph feature 277 left behind |
| `packages/dreaming/tests/test_ceiling.py` | feature 276's claims, 39 tests |
| `packages/dreaming/tests/test_errors.py` | the ceiling class's sibling test |
| `.plans/feature-276-revision-ceiling.md` | this document |
| `additions_spec_276.xml` | the additions spec |

## Verification

- `uv run pytest packages/dreaming/tests` — **220 passed** (was 180; +39 ceiling, +1 errors).
- `uv run pytest tests/` — **1074 passed** (after `uv sync --all-packages`; the bare `uv sync` venv lacks polars/pyarrow and fails collection in `tests/contract` and `tests/feature-store`).
- `uv run ruff check packages/dreaming/` — **All checks passed!** (the member was clean on main; it stays clean).
- `claw-forge validate-spec --json additions_spec_276.xml` — 17 errors / 6 warnings, **byte-identical in profile** to sibling `additions_spec_277.xml` (17 Layer-6 cq-traceability errors by construction, plus the 3 LLM-layer warnings that are 403 key failures). No Layer-8 Gap-8 finding: the description carries no literal DDL token.
