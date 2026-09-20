# Feature 144 — persist a void marker on every score produced after a determinism break

## What the spec asks for

app_spec.xml, "Determinism Guarantees & Nightly Canary":

> **144** (depends_on 143) — System persists a void marker on every score
> produced after a detected determinism break, **rather than letting bad data
> age into good data**

§12 (docs/nullius-tech-architecture.md) supplies the break and its instant:
the nightly canary replays the frozen pair, and `abs(score - CANARY_EXPECTED) > 1e-12`
halts dreaming. Key interaction #5 spells the second half:

> A frozen policy replays a frozen tree nightly; a deviation beyond 1e-12 halts
> dreaming and **marks scores produced in the affected window as void**.

Feature 143 (`canary._halt`) has landed: it persists the break and halts, and
its `DreamHalt.detected_at` is explicitly documented as "the datum feature 144's
void markers key on". This task is the consumer of that datum.

## Footprint

`.claw-forge/worktrees/…/.claw-forge` claims `src/app/modules/canary/**` and
`packages/canary/**`. Everything below lands inside those two trees. No
central registry, no migration, no `pyproject.toml` edit (the member already
joins the workspace by convention).

## The one real design fork — and the call

**What is "a score"?** Feature 144 wants to void scores that already exist.
Two readings:

* **(A) The void store reads the replay pool.** Restate the pool's shape
  (`replay_score`, 0109) the way `tripwires.layout` already restates it, sweep
  it for rows written after the break, and refuse those rows.
* **(B) The void store is caller-driven.** Expose `mark(score_id, produced_at)`
  over a member-owned table, and let whoever holds the scores drive it.

**Going with (A)**, on the strength of the nearest precedent in the workspace:
feature 132 (`tripwires.excise`) answers *"every score that branch
contributed"* by reading `replay_score` from a member that owns it not, and it
states the rule verbatim — a shared vocabulary **spelled twice with one
provenance comment** beats an import that couples two packages. Members here
may not import each other (the canary is imported on every factory scan
including §1's replay path), so restating is the only available reach.

(B) would leave the feature hollow: a mechanism no driver calls, voiding scores
nobody enumerated. §12's thesis is that the canary *catches* things, so the
store must actually find the bad rows.

Nothing in (A) writes to a foreign table. `replay_score` is read-only from
here, exactly as feature 132 leaves it; the marker table is this member's own,
created idempotently beside the code that reads it (§143's stance for
`canary_dream_halt`).

## Design

### `packages/canary/src/canary/_void.py` — the new module

Stdlib only (`sqlite3`, `datetime`, `os`, `uuid`, `urllib.parse`), no I/O at
construction, path resolved on first use — the contract every store in this
workspace states, and load-bearing here because the factory imports this
package on every `create_app()`.

**The break instant is read, never decided.** The module holds a
`CanaryHaltStore` and asks it for the window's edge — the same stance
`ReplayPool._poison_store()` takes toward feature 131. A second reader of
`canary_dream_halt` would be a second opinion about when the deployment broke.

**The window's edge is the *earliest* break on record, not the latest.** Two
pairs breaking on two nights give two halt rows. A score produced between them
was produced after the deployment's determinism broke (pair A measured it), so
the honest boundary is the earliest `detected_at` — and it is monotone: more
breaks can only move the edge earlier, never later. This is "rather than
letting bad data age into good data" as a rule: the affected window only ever
widens.

Adds one small read to the already-shipped `CanaryHaltStore`:

* `first_halt()` — the earliest halt by `detected_at` (`ORDER BY detected_at,
  code_hash LIMIT 1`). Additive; `current_halt()` keeps meaning "the latest",
  which is right for the operator page and wrong for this window.

**The boundary is strict.** `produced_at > detected_at` — §12's *"produced
after"*, matching line 677's strict `>`. A score written at the same second the
break was detected is not after it. Second-resolution stamps make this
reachable, so it is a decision worth pinning rather than an accident.

**What persists.** One row per voided score in `canary_void_marker`, keyed by
the score's id:

```
score_id     TEXT NOT NULL PRIMARY KEY   -- replay_score.id, canonical UUID text
produced_at  TEXT NOT NULL               -- replay_score.created_at
detected_at  TEXT NOT NULL               -- the window's edge (the first break)
code_hash    TEXT NOT NULL               -- which pair measured the break
tree_hash    TEXT NOT NULL
alert_kind   TEXT NOT NULL               -- 'determinism_broken' (feature 143's word)
status       TEXT NOT NULL               -- 'VOID'
marked_at    TEXT NOT NULL               -- when this row was written
```

The break's hashes and instant ride on every marker so a marker is
self-describing — the same discipline `DreamHalt` follows by carrying its own
arithmetic. `changed` is not a column: it is a property of the *call*, supplied
by the caller, exactly as in `DreamHalt`.

`"VOID"` is spelled once, matching `nulloracle.verdict.CALIBRATION_STATUS_VOID`
— the workspace's one spelling of void.

### Values

* **`VoidWindow`** — frozen: the edge (`detected_at`), the pair's hashes, the
  alert kind, `status`. What `window()` returns; `None` when nothing is halted.
  `contains(produced_at)` is the strict comparison, spelled once.
* **`VoidMarker`** — frozen dataclass, validated in `__post_init__` against its
  own arithmetic and against the window (a marker whose `produced_at` is not
  inside `window` fails to reconstruct rather than loading as a plausible
  taint). Carries `changed`, `to_payload()`, `summary`.
* **`VoidSweep`** — the account of one sweep: the window, the markers written,
  the scores already marked, the pool size. Mirrors `ExcisedBranch` carrying
  *what the act cost* so a caller need not re-query.
* **`CanaryVoidMarkerError(CanaryError)`** — this member's one refusal for the
  void feature, defined beside its value types (`_halt.py` / `_replay.py`
  precedent), noted in `_errors.py`'s trailing comment.

### The store: `CanaryVoidMarkerStore`

* `resolve(env)` / `database_url` / `path` — the workspace's store shape.
* `ensure_schema()` — `CREATE TABLE IF NOT EXISTS` for the marker table, plus
  the pool's own bootstrap DDL (0109's eight columns, verbatim, including the
  two dialect splits) so the sweep works against a database the orchestrator
  has not migrated — `tripwires.layout.replay_pool_bootstrap_schema`'s exact
  argument, restated here with its provenance.
* **`window()`** → `Optional[VoidWindow]` — `None` when no break is on record.
* **`mark(score_id, produced_at)`** → `VoidMarker`. Refuses, in order:
  1. an id that is not UUID text;
  2. a `produced_at` that is not timezone-aware;
  3. **no break on record** — "a void marker citing no break would taint a
     score against a canary that held";
  4. **`produced_at` not strictly after the edge** — "the score predates the
     break, and a marker outside the window would void *good* data".
  Re-marking an already-marked score writes nothing and returns the stored
  marker with `changed=False` — first write wins, as the halt does.
* **`sweep()`** → `VoidSweep`. Reads `replay_score`, selects rows whose
  `created_at` is in the window, and marks every one not already marked.
  Returns `None` when nothing is halted (no break, nothing to void) — the
  counterpart of `halt_dreaming`'s quiet untaken branch.
* **`unvoided_scores()`** → the pool rows the system may still use: every row
  **not** in the window and **not** marked. This is the read the
  dreaming/replay path makes — feature 132's `survivors()` in this member's
  vocabulary — and it is *derived* from the window, so a row written after the
  break is refused whether or not a sweep has run yet. No lag hole.
* **`markers()`** → the persisted audit, oldest first.
* **`voided(score_id)`** → bool, answered from the markers.
* **`require_score_usable(score_id)`** → the guard; raises carrying the stored
  marker, the shape `require_dreaming_allowed` takes.

### Module-level spellings

`void_scores_after_break(...)`, `unvoided_scores(...)`,
`require_score_usable(...)`, `build_void_marker_store(env)` — resolving the
store from `database_url`, else `DATABASE_URL`, refusing **by name** when
neither is set (`halt_dreaming`'s precedent: a void that silently went nowhere
is worse than none).

### Wiring — auto-discovery only

* `packages/canary/src/canary/__init__.py`: import/re-export the new surface,
  add to `__all__`, and add a fourth builder
  `@register(VOID_MARKER_COMPONENT_NAME)` → `build_void_marker_store()`.
  Fourth name, fourth question: the sweep asserts the pins, the reference store
  holds the frozen pair, the halt store answers *is dreaming halted?*, this one
  answers *is this score still usable?*. Resolves rather than raises, so an
  unconfigured deployment composes `None` and never takes composition down.
* `src/app/modules/canary/void.py`: the seat — `__all__ == ["COMPONENT_NAME",
  "void_marker_component"]`, matching the two existing seats exactly.
* No `CanaryService` facade: this is a persistence step, not a pure function —
  the same reason feature 143 took a component rather than a service property.

## Tests (`packages/canary/tests/`)

* **`test_void.py`** — the module. The refusals (no break, before the window,
  bad id, naive instant); the strict boundary; the window being the *earliest*
  break across two pairs; markers never removed and the window never narrowing
  (the "does not age into good data" property, tested by sweeping, adding a
  later break, sweeping again); `unvoided_scores()` deriving without a sweep;
  sweep idempotence; a `VoidMarker` failing to reconstruct from a tampered row.
* **`test_void_component.py`** — composition: the factory composes the store
  for a deployment with `DATABASE_URL`; the seat reaches the same component;
  composition creates no file; feature 143 through 144 end to end (break →
  halt row → sweep → the pool row is refused).
* **`test_app_module.py`** — extend with the void-seat block, mirroring the
  halt-seat tests.

Copies of the member are handled the way `test_halt_component.py` documents
(the loader imports under `_nullius_scanned_canary`, so pairs/results are built
from the composed store's own package root) — the helper is reused verbatim.

## Verification

```
UV_CACHE_DIR=.claw-forge/tmp/uvcache uv run --all-packages pytest packages/canary -q
```

Baseline is **302 passed**. Also run the repository tree the acceptance gate
collects (`uv run pytest -q`) to confirm nothing outside the footprint moved.

## Out of scope

* Feature 132's poison refusal (different member, different reason for refusal).
* Any write to `replay_score`, any migration, any change to `CanaryService`,
  `_reference*`, `_replay`, `_image`, `_containers`, `_reproducibility`.
* The only edit to shipped code is the additive `first_halt()` on
  `CanaryHaltStore` in `_halt.py`.
