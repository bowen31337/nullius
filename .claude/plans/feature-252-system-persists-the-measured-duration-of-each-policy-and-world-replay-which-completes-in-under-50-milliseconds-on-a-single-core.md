# Feature 252 — System persists the measured duration of each policy and world replay

## Context

**app_spec.xml, "Replay Engine", feature 252** (`plugin="replay"`, `depends_on=251`):

> *System persists the measured duration of each policy and world replay, which completes in under 50 milliseconds on a single core.*

This feature is the **measurement half** of the Replay Engine's cost argument. Its parent, feature 251, makes a replay cheap (reads campaign returns from a pinned resident array instead of re-sweeping Parquet per replay). Its two children — feature 253 (`recomputation_suspected` alert when a replay exceeds 200 ms) and feature 254 (persists replay latency at p50/p99 into the observability metrics store) — are both *consumers of 252's measurement*: 253 compares a measured duration against a threshold, and 254 aggregates a population of measured durations into percentiles. **Neither child can exist without a duration being measured and carried by the replay first.**

The whole cost argument rests on this seam. docs §10.4:

> *A replay is pure array arithmetic over cached Parquet. Target: **under 50 ms per (policy, world)** on a single core. … If a replay exceeds ~200 ms, something is recomputing rather than reading, and the cost model of the architecture has broken.*

and docs §10.1's `replay()` skeleton returns a `ReplayResult` that **no code owns yet**:

```python
def replay(policy, tree, book, epoch) -> ReplayResult:
    …
    return score(pick, book, epoch, revealed, rounds)
```

Feature 252 is the part of that `ReplayResult` that is *this member's* to own: **the measured duration of the (policy, world) replay, and the record that carries it.** It is the timing primitive the category's cost model is stated against — the thing that makes "under 50 ms" an observable rather than a claim, and the thing 253's alert and 254's percentiles read.

### What this feature is NOT

- It does **not** refuse. A feature that *refused* a slow replay would contradict its two children: 253 explicitly *permits* a replay to reach 200 ms (it only *alerts* there), and 254 persists the whole latency distribution including the slow tail. So 252 **measures and persists**; it never blocks. (The refusal-shaped half of "under 50 ms" is not in the spec — the spec's enforcement is 253's alert, which is a later feature.)
- It does **not** widen `replay_score` (migration 0109). That table carries `policy_version, world_id, beta, score, committed_pick, is_holdout` and belongs to **feature 255**, a *separate lineage* (`depends_on=250`, not 252). Adding a `duration` column there would couple 252 to 255's migration and to scoring's value, and would force a migration into a chain this feature does not own. 252 keeps its own record.
- It does **not** score, aggregate, or persist to any observability store. Scoring is feature 256+ (separate member). The p50/p99 percentiles are feature 254 (a later feature that consumes the records this one produces). This feature produces the per-replay record; it does not aggregate a population of them.
- It does **not** time anything downstream of the replay (the evaluator, the sandbox, the agent). Those are exactly what feature 246/247 forbid the replay path from reaching. 252 times *the replay's own acts* — the walk, the read, the scoring arithmetic — and nothing outside them.

### Design decision: what "persists" means here

"System persists the measured duration" is satisfied by **the record carrying the measured duration as a first-class, immutable field** — the same sense in which feature 240 "persists" the committed pick by carrying it, and feature 256's `WorldScore` "persists" its score. There is no observability member in this workspace yet (254 would be the first to write one), so 252's persistence is the *per-replay record*: a value object that holds the measured duration and the identity of the replay it measured (the policy version and the world id — the two keys of a dreaming cycle's `(policy, world)` pair), and answers them for the record's whole lifetime. The *aggregation of many such records into p50/p99* is 254; the *alert on one such record* is 253. This feature is the record they both read.

The measurement is taken over **the whole replay** — from the moment the replay opens its transition over the tree to the moment it produces its result — with `time.perf_counter()`, the stdlib monotonic clock suited to measuring elapsed durations (never wall-clock `time.time`, which is not monotonic and would mis-measure a sub-50ms interval). The record is the thing that *carries* that measured duration; the caller that owns the loop is the thing that *reads the clock* and hands the record its number, exactly as the caller that owns the scoring is the thing that hands the score.

## Scope

**In scope (this feature's files):**

- `packages/replay/src/replay/duration.py` — new module: the measurement primitive and the record.
  - `REPLAY_DURATION_TARGET: float` — the 50 ms-per-(policy, world) target, spelled once (0.05 s), the constant 253's alert threshold and 254's percentiles are stated against.
  - `REPLAY_DURATION_ALERT_THRESHOLD: float` — the 200 ms point at which the cost model has broken (docs §10.4), carried here so 253's alert quotes the same spelling.
  - `class ReplayDuration` — the per-replay record: `policy_version`, `world_id`, `duration_seconds`, `within_target`, `exceeds_alert_threshold`; immutable (`__slots__`, read-only properties), stdlib only. Constructed directly by a caller that holds a measured duration (the same stance `ReplayReturns` takes — the constructor trusts its already-validated inputs); the flags are derived read-only properties, never stored.
  - `def measure_replay(policy_version, world_id)` — the measurement primitive. Validates the two identity keys (non-empty strings) **before** the timer arms, then returns a `_ReplayTimer` context manager. `__enter__` reads `perf_counter()` (arming the timer, touching nothing else); `__exit__` reads it again, subtracts, and builds the `ReplayDuration` record carrying that measured duration and the two identity keys — answered via the timer's `.duration` property once the body completes. It never suppresses (returns `None`): a replay that raised still consumed a measurable interval, and 253's alert is about *a replay that ran*.
- `packages/replay/src/replay/__init__.py` — export the new surface (add `ReplayDuration`, `measure_replay`, `REPLAY_DURATION_TARGET`, `REPLAY_DURATION_ALERT_THRESHOLD` to `__all__` and imports).
- `packages/replay/tests/test_duration.py` — new test file pinning the feature.
- `packages/replay/pyproject.toml` — no dependency change (stdlib `time` only).

**Out of scope:**

- No migration. `replay_score` is feature 255's and is left untouched.
- No app factory / registry / router / seat edits (registration-by-convention only).
- No observability store, no percentile aggregation (254), no alert emission (253).
- No change to `ReplayEngine`, `ReplayTransition`, `ReplayReturns`, `resident_returns`, or the errors module.

## Implementation

### 1. `packages/replay/src/replay/duration.py`

A new module, stdlib only (`time`, `dataclasses`, `typing`), mirroring the member's "import-cheap, no numerics, no clock but `time`" stance. The docstring states the feature's sentence, the docs §10.4 numbers (50 ms target, 200 ms broken-cost-model point), the parent/child relationship (251 makes it cheap, 253/254 consume the measurement), and the "measures and persists, never refuses" law.

Key design points, each pinned in a test:

- **`time.perf_counter()` is the only clock.** The measurement reads `perf_counter()` at scope entry and at scope exit and subtracts; the difference is the replay's measured duration. `perf_counter` is monotonic and high-resolution, so it is the correct clock for a sub-50ms interval; `time.time()` (wall clock, non-monotonic) is deliberately not used, and a test asserts the module imports `perf_counter` (the "one spelling of the clock" rule, the same way 256 pins "one spelling of the information ratio").

- **The record is immutable and carries identity + duration.** `ReplayDuration` holds `policy_version` (non-empty string), `world_id` (non-empty string), and `duration_seconds` (a non-negative, finite float). It derives `within_target` (`duration_seconds <= REPLAY_DURATION_TARGET`) and `exceeds_alert_threshold` (`duration_seconds >= REPLAY_DURATION_ALERT_THRESHOLD`) as read-only properties — never stored, always derived from the one measured number, so the record cannot carry a duration and a contradictory flag. `__slots__` and no setter keep it frozen: a record is the *measurement*, and a measurement that could be reassigned would be a duration no alert or percentile could trust. The constructor **trusts** its inputs (it does not re-validate the identity keys or re-check the duration) — the same stance `ReplayReturns.__init__` takes — because the caller that constructs one directly has already measured; the validation lives at the seam that *measures*.

- **The context manager is the measurement primitive.** `measure_replay(policy_version, world_id)` validates the two identity keys (non-empty strings) **before** the timer arms, then returns a `_ReplayTimer`. `__enter__` reads `perf_counter()` once (arming the timer) and touches nothing else — no tree, no store, no arena, no evaluator, no sandbox. `__exit__` reads `perf_counter()` again, subtracts the start, and builds the `ReplayDuration` record carrying that measured duration and the two identity keys; the record is answered via the timer's `.duration` property once the body completes. `__exit__` never suppresses (returns `None`), because the timing wraps a replay, not an error boundary — an exception in the replay is still a replay that took a measurable amount of time, and the record must answer even then. (This is the honest reading: a replay that raised at round 40 still consumed wall time, and 253's alert is about *a replay that ran*, whatever it returned.) The record is answered **on exit**, not on entry: a duration is a completed-interval quantity, and a record answered before the body ran would carry no measurement.

- **Validation fires before the timer arms.** `policy_version` and `world_id` are validated as non-empty strings in `measure_replay` *before* `perf_counter()` is read — a malformed identity names no `(policy, world)` pair, and the refusal belongs to the caller's ask, not to a measured replay. Refused in this member's vocabulary (`ReplayError`), the same law the transition and returns read state.

- **`duration_seconds` is never negative and never NaN.** `perf_counter` is monotonic so the measured difference cannot go negative, but the record refuses a negative or non-finite duration at construction (a duration that is negative or NaN is not a measurement — it is a broken clock or a mis-read, and 253/254 must never aggregate one). Refused in this member's vocabulary.

- **The target and threshold are spelled once.** `REPLAY_DURATION_TARGET = 0.05` and `REPLAY_DURATION_ALERT_THRESHOLD = 0.2`, each with a docstring quoting docs §10.4 and naming the child feature that reads it (253 for the threshold, 254 for the target's role in "under 50 ms"). A later feature that changes either quotes this one spelling.

### 2. `packages/replay/src/replay/__init__.py`

Add the four new names to the imports and `__all__`, with a short docstring paragraph stating that feature 252 is the measurement half — the per-replay duration record the cost model is stated against, the primitive 253's alert and 254's percentiles consume — and that it measures the replay's own acts and never reaches the evaluator or sandbox (246/247). No `@register` change: the record is per-replay state, not a component (the same stance `ReplayTransition` and `ReplayReturns` take), so the `replay` component is untouched.

### 3. `packages/replay/tests/test_duration.py`

New test file, stdlib + pytest only, mirroring the returns/transition suites' structure (module docstring stating the feature, fixtures minimal, tests in feature-order). Tests pin:

- the target and threshold are spelled once, and the threshold is above the target (0.2 > 0.05) — the ordering 253's "alert only past 200ms, target is 50ms" depends on;
- `measure_replay` times a body and the returned record carries the measured duration and both identity keys;
- the record's `within_target` / `exceeds_alert_threshold` are derived from the one duration (a fast replay is within target and below alert; a slow replay exceeds alert and is not within target); a mid-range replay (e.g. 80 ms) is not within target but below alert — proving the two flags are independent, not one negation of the other;
- the record is immutable (no attribute reassignment; `__slots__`);
- the measurement uses `perf_counter` (the module's clock is `perf_counter`, asserted by inspecting the module attribute / or by a body that sleeps a known interval and asserting the measured duration is at least that long and monotonic);
- the timer does not touch the tree/store/evaluator/sandbox (the body is a bare `pass` / a no-op, and the record still answers — proving the measurement wraps the replay's own acts, not an external call);
- the record answers even when the body raises (the context manager does not suppress, and the duration is still measured);
- a malformed `policy_version` / `world_id` is refused before the timer arms (assert the refusal is `ReplayError` and that no record is produced);
- a negative/NaN duration is refused at construction (constructing `ReplayDuration` directly with a bad number refuses) — the defensive clamp 253/254 rely on;
- the record answers one object for its lifetime (same object on repeated property access), mirroring 251's "one resident object" test.

## Verification

Run the replay member's own suite (the acceptance gate ignores member suites, so both the repo `tests/` and the member suite must be run explicitly):

```bash
cd /home/dell/projects/nullius/.claw-forge/worktrees/replay-engine-system-persists-the-measured-durat-12a4b3
PYTHONPATH=src:packages/replay/src uv run python -m pytest packages/replay/tests/ -q
```

Expected: `test_duration.py` green, `test_returns.py` / `test_transition.py` / `test_component.py` still green (unchanged), and the cross-member `artifacts`/`pyarrow` tests in `test_returns.py` skip (artifacts not installed in this workspace — expected, not a failure).

Also run the member's lint against a sibling (per the memory note that repo lint is red on main — only lint my own files, compare to a sibling, never baseline via `--stdin-filename`):

```bash
PYTHONPATH=src:packages/replay/src uv run ruff check packages/replay/src/replay/duration.py packages/replay/tests/test_duration.py
```

And a targeted import/type sanity check that the member still composes:

```bash
PYTHONPATH=src:packages/replay/src uv run python -c "import replay; print(replay.ReplayDuration, replay.measure_replay, replay.REPLAY_DURATION_TARGET, replay.REPLAY_DURATION_ALERT_THRESHOLD)"
```

## Notes for the reviewer

- **Why no migration / no `replay_score` widening.** `replay_score` (0109) is feature 255's table and a separate lineage (`depends_on=250`). Feature 252's "persists the duration" is the per-replay record carrying the measured duration — the same sense in which 240 "persists" the committed pick by carrying it. The aggregation of many records into a store (p50/p99, feature 254) and the alert on one record (feature 253) are the consumers, and they land later. This feature is the record they read.
- **Why `perf_counter` and not `time.time`.** A sub-50ms interval measured on a non-monotonic wall clock can read negative or jitter; `perf_counter` is the stdlib clock for elapsed-time measurement. One spelling, pinned in a test.
- **Why the feature does not refuse a slow replay.** Its children require it not to: 253 permits a replay to reach 200ms (alerting, not blocking), and 254 persists the whole distribution. 252 measures; enforcement is 253's later job.
- **Precedent for the "record carries the measured value" shape:** feature 256's `WorldScore` (carries the score), feature 240's committed pick, feature 251's `ReplayReturns` (carries the resident array). Feature 252 is the timing member of that family.
