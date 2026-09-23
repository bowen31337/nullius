# Feature 277 — The revision cap's raise, and the record of its use

**app_spec.xml, "Dreaming Loop & Meta-Selection", feature 277**
(`shape="plugin"`, `plugin="dreaming"`, `depends_on="275"`): *System persists
the revision cap used per cycle, raising M to 40 once the pool holds 50 or
more worlds.*

A third sentence in the existing dreaming member (`packages/dreaming/`), not
a new member: the top rung of §12.1's ladder, and the per-cycle account of
it.

## The sentence, and the ladder it completes

§C5 puts `M` inside the loop this whole member serves — *"Per outer
iteration: hold the replay pool fixed, run `M` code revisions of `π`,
evaluate each on every stored tree, select the argmax under §7"* — and
§12.1's ladder table caps `M` by the pool's size:

| Pool size | Operating regime |
|---|---|
| < 20 worlds | **Do not run dreaming.** (feature 275) |
| 20–50 | Dreaming with `M` capped at 8–10 (feature 276's ceiling) |
| 50+ | Full dreaming, `M = 30–40`, 70/30 train/holdout split |

Feature 277's sentence takes the top rung — *raising M to 40 once the pool
holds 50 or more worlds* — and 40 is the figure §12.1 itself computes the bar
with (*"At `M = 40` (bar ≈ 2.72), `σ_V ≈ 0.8` and a target advantage of 0.3,
this gives `n > 53` worlds"*), which is why the raise lands on 40 and not
somewhere else inside the section's `30–40`: the bar the ladder is calibrated
against is the bar at 40, the M3 precondition's own threshold is the boundary
(*"≥ 50 worlds in the pool (§12.1)"*), and the raise, the bar and the `n >
53` are one calculation that would be split across two figures if the cap
were 30-something.

**Three rungs, three features, no cross-imports.** The schedule delegates
the bottom rung to feature 275 — `revision_cap` calls
`dreaming.ladder.rejects_thin_pool`, so a figure below the floor is refused
in the floor's own word (`pool_too_thin`), by the floor's own one spelling of
the rule, which is what `depends_on="275"` means in code. The middle rung's
ceiling is feature 276's sentence (a *refusal* above 10); this feature
spells the same 10 as the band's *cap* (`CAPPED_SWEEP_CAP = 10`, §12.1's
"capped at 8–10" at the count 276's refusal fixes), because a schedule that
answered no number below 50 would be a ladder with a missing rung. The two
siblings do not import each other and neither is imported across: the 10 is
the PRD's number, stated once here as the band's cap and enforced there as
its ceiling.

## Why the cap is persisted — the half of the sentence a constant cannot answer

Appendix B's meta-level selection bar is `advantage > √(2 ln M) · σ_V /
√n_worlds`, and feature 280 applies exactly that to the winning revision.
The bar reads `M` back; a cycle that ran 40 revisions and was then judged at
a bar computed over 10 — or over an `M` nobody could name — would have its
multiple-testing width mis-stated by exactly the factor the bar exists to
control, and §12.1's whole warning (*"selecting the max over `M` revisions …
is the same multiple-testing problem one level up"*) is a warning about `M`
growing unobserved. So the cap a cycle used is a **fact about the store**:
`cycle_cap` is this member's own table — one row per cycle, append-only, the
same member-owned stance `pool_freeze` takes — and the operator (or feature
280) asks the database, not the log.

## The design decision that shapes everything: the schedule judges, the record takes the figure

`revision_cap(world_count, *, floor=20, full_dreaming=50)` is a *judgment
over a count the caller already has* — the same verdict-gate shape the
ladder floor takes, and for the same reason: a verdict is not a count, and
the count is the caller's to supply. The figure is the one this member
already computes (`pool_commitment` returns it; a feature-270 hold records
it as `world_count` at the moment it opened), so in the loop the count is
already in the caller's hand when it asks for the cap.

`record_cycle_cap(iteration_id, world_count, ...)` takes the figure exactly
as the floor does — the record never counts the pool, never reads a pool
row. What it *does* do is decide: **the caller cannot hand in a cap of its
own**; the row's `revision_cap` is always the schedule's answer over the
row's `world_count`, so the record cannot disagree with the ladder, and the
row carries the figure beside the cap so it names its own rung. The one
pool-fact the record refuses is *presence*: a database with no
`replay_score` and no `bootstrap_world` has no pool to cap, and the probe
(`pool_tables_present`) comes **before** the DDL, so a refused record leaves
no trace — not even the table.

Refusal order, each naming what it is about: (1) the ask's own facts — an
iteration id that is not non-empty text, a figure or rung that is not a
world count, a boundary below the floor (`CapRequestError`; the floor itself
in the ladder's `PoolTooThinError`); (2) a figure below the floor — feature
275's refusal, delegated, in its own word, before any database is opened;
(3) an instant that is not timezone-aware or a URL that names no store
(`CapRequestError`); (4) a database that holds no pool (`CapRecordError`).

## One row per cycle-occurrence, not per iteration name

§12.1's cycle may legitimately retry — release the hold, let the pool grow,
open again — and the retried cycle is *re-decided*: the pool may have moved
a rung between attempts, so the retry's cap is a new fact with its own row,
exactly as each hold window is its own row in `pool_freeze`. Ids are minted
per occurrence (`_cap_id` = sha256 over iteration, instant and a draw,
`cap-<hex32>`), so a retry recorded inside the same second never collides on
the primary key — the lesson `_hold_id` states for holds, restated for caps
before it can happen. The table is append-only with **no unique index and no
triggers**: a cap is a judgment, not a hold — there is no pool write to
refuse and no window to close, only history to keep, ordered by
`(recorded, id)` per the §12 ordering rule. `cycle_caps()` is the audit read:
every record, oldest first, with a retried cycle's re-decision standing
beside the attempt it replaced, because both were true.

## The vocabulary: the cap's own pair, translated at the seam

Two new siblings under `DreamingError`:

- `CapRequestError` — the *ask* face: a malformed id, figure, rung, instant
  or URL, refused before anything is read or written. Same repair stance as
  `FreezeRequestError` (*re-consider the ask*).
- `CapRecordError` — the *store* face: a database that holds no pool to cap,
  or a recorded row whose stamp will not read back. Repair: point at the
  pool's database, never re-send the same ask.

What the module does **not** do is respell the rules it shares with feature
270 — `validated_iteration_id`, `sqlite_path` and the stamp pair
`_stamp`/`_parsed_instant` are the member's one spellings of what an
iteration id is, what a `sqlite:///` URL names and what a row's instant looks
like, and a vocabulary spelled twice says two different things. Their
refusals are *translated at this seam* into the cap's classes (the same
discipline the workspace states for error vocabularies across member
boundaries, applied inside the member), so a caller of the cap never meets a
`FreezeRequestError` for an act that held nothing. Neither class carries a
code word: feature 275's `pool_too_thin` is mandated by its own sentence and
feature 270's codes name pool-facts; the one thin-pool refusal this feature
mints is feature 275's, delegated, in feature 275's word.

## No new component, no seat edit, no migration

Feature 277 adds no `@register` component — feature 270's single
`"dreaming"` component is the member's whole composition, and the cap is
reached the way the floor is, as free functions beside the store. The seat
(`src/app/modules/dreaming`) still exports exactly `{COMPONENT_NAME,
cycle_freeze_component}`, and its `test_component.py` suite is untouched.
`cycle_cap` is member-owned and created lazily beside the only module that
writes it, never in the shared migration chain. Stdlib only: `hashlib`,
`secrets`, `sqlite3`, `datetime`, `os`.

## Files

| file | what |
|---|---|
| `packages/dreaming/src/dreaming/cap.py` | `FULL_DREAMING_WORLDS`, `FULL_DREAMING_CAP`, `CAPPED_SWEEP_CAP`, `CYCLE_CAP_TABLE`, `revision_cap`, `CapRecord`, `cycle_cap_schema`, `record_cycle_cap`, `cycle_caps` |
| `packages/dreaming/src/dreaming/errors.py` | `CapRequestError`, `CapRecordError` |
| `packages/dreaming/src/dreaming/__init__.py` | re-exports, the member docstring's third sentence |
| `packages/dreaming/tests/test_cap.py` | feature 277's claims, 48 tests |
| `packages/dreaming/tests/test_errors.py` | the cap pair's sibling test |
| `.plans/feature-277-revision-cap.md` | this document |
| `additions_spec_277.xml` | the additions spec |
