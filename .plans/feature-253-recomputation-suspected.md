# Feature 253 — `recomputation_suspected` when a replay exceeds 200 ms

app_spec.xml, "Replay Engine", **feature 253** (`plugin="replay"`, `depends_on=252`):
*"System emits a recomputation_suspected alert when a replay exceeds 200
milliseconds, because the cost model has then broken"*.

## What already exists (and must not be disturbed)

Feature **252** (`packages/replay/src/replay/duration.py`) is the parent and is
already written against this feature's arrival. Its docstring says so three
times, in the exact words I have to honour:

- *"feature 253 — … — **compares a measured duration against the broken-cost-model
  point**, reading the flag this module derives"*;
- *"It does not **alert** — feature 253 emits the `recomputation_suspected`
  alert, reading the flag this module derives"*;
- *"feature 253 explicitly **permits** a replay to reach 200 ms and only **alerts**
  there"* — i.e. **253 does not refuse the replay.**

So the two numbers are already spelled once, in `duration.py`:
`REPLAY_DURATION_TARGET = 0.05` and `REPLAY_DURATION_ALERT_THRESHOLD = 0.2`, and
`ReplayDuration.exceeds_alert_threshold` is the flag 253 reads. **253 must quote
those and never restate a literal.**

Feature **254** (`metrics.py`) is the sibling and is also explicit: *"It does not
**alert** — the `recomputation_suspected` emission past 200 ms is feature 253's,
reading a flag 252 derives; this module is the report the alert is read
against, not a second place the threshold could live."* 254 raises only on a
broken *report*, never on a slow population — so **253 is the one place a slow
replay produces a loud thing.**

## Design decisions

**The reading is 252's flag, never a second comparison.** `emit_*` reads
`carrier.exceeds_alert_threshold` (duck-typed) and quotes
`REPLAY_DURATION_ALERT_THRESHOLD` only for the record's `threshold_seconds` and
for a *self-consistency* check. That check is exactly `DreamHalt.__post_init__`'s
in-repo precedent — a duck-typed record is refused when it disagrees with its own
arithmetic (`flag != (duration >= threshold)`) — because a foreign carrier owes
the proof a constructor no longer stands behind, and a contradictory carrier would
either alert on a fast replay or stay silent on a slow one.

**The emission is a typed raise; the `if` not taken returns `None`.** The
workspace's alert convention is build-a-record-then-raise
(`canary._halt.halt_dreaming` → `CanaryDeterminismBrokenError`,
`nulloracle.keyalert.emit_unrecoverable_state` → `UnrecoverableStateError`,
`snapshot.corruption_error` → `SnapshotCorruptionError`). `halt_dreaming` is the
closest analogue — a conditional emission that returns `None` when the condition
was not met — and it raises, *after* the record exists, so catching the alert to
keep reporting still leaves the emission observed by type.

**It does not refuse the replay, and it structurally cannot fire early.** The
record only exists once the interval closed: `_ReplayTimer.duration` refuses
before the `with measure_replay(...)` block exits, so there is no way to emit
inside the measured region. The alert is *post-hoc* — it refuses the **silence**
about a broken cost model, never the replay. `252`'s law (*measures and persists;
never refuses*) is untouched, and so is 254's store.

**No store, and that is a decision.** 253's sentence names no store, unlike 254's
(*"into the observability metrics store"*), 143's (a halt that must outlive the
nightly run) and 111's (*"all FDR history becomes uninterpretable"*). The slow
replay's duration already lands in 254's `samples` (the source of truth of that
population), so a second table would be a second spelling of one fact and a
second `DATABASE_URL` reader in a member that has exactly one — the drift 254's
own docstring warns about. `snapshot`'s corruption alert is the in-repo precedent
for a record + typed raise with no table of its own; `emit_unrecoverable_state`
works with `journal=None` by design. The alert's durability is the caller's
logger/monitor, and the emission is loud by construction.

**It does not halt dreaming.** §15's recovery row for a broken cost model
(*"revert to stored-float artifacts"*) is not §12's `halt_dreaming`; conflating
the two would stop the pool for a timing observation. The alert is the emission,
full stop.

**The clock split.** The alert's `detected_at` is a wall-clock **label** (ISO-8601
UTC, second resolution), the same split 254 makes for its row key. The only clock
a *duration* is ever read from remains 252's `time.perf_counter` — nothing here
subtracts two wall-clock readings.

**Duck-typed seam.** The loader imports a member under a synthetic name and
re-executes it, so the record a *composed* path produced is a second class object
of the same name — the read is structural (`duration_seconds`,
`exceeds_alert_threshold`, `policy_version`, `world_id`), never `isinstance`.

**No component, no seat change.** 252 and 254 both register nothing ("the
member's one `@register` contribution stays feature 245's stateless facade"), and
253 is the same shape: no store, no deployment state. `src/app/modules/replay/__init__.py`
is therefore **not edited** — a seat that decided anything about an alert would be
a second place for the law to hold.

## Files

### New — `packages/replay/src/replay/alert.py`

- `RECOMPUTATION_SUSPECTED = "recomputation_suspected"` — the spec's spelling,
  verbatim (the word an operator greps and a monitor dispatches on).
- `RecomputationSuspected` — frozen `__slots__` record: `alert_kind`,
  `policy_version`, `world_id`, `duration_seconds`, `threshold_seconds`,
  `detected_at`; `alert_kind` validated in `__init__`; `summary()`.
- `RecomputationSuspectedError(ReplayError)` — the alert, catchable by type,
  carrying `.alert`.
- `recomputation_suspected_error(alert)` — the one spelling of the message
  (spec's kind + the record's summary + §10.4's consequence), so the page an
  operator reads and the record cannot drift.
- `suspected_recomputation(duration, *, detected_at=None) -> RecomputationSuspected | None`
  — the reading: `None` when the replay was fine, the record when it was not.
- `emit_recomputation_suspected(duration, *, detected_at=None) -> None` — the
  feature's verb: return `None` when nothing is suspected, else raise.

Each refusal is `ReplayError` in this member's vocabulary: a carrier that is not
a measured duration (a bare number names no replay), a non-finite/negative
`duration_seconds`, a non-bool flag, a carrier disagreeing with its own
arithmetic, a malformed instant. Stdlib only: `datetime`, `math`.

### Edited — `errors.py`
- Add `RecomputationSuspectedError`, the **sixth** subclass, with the argument for
  why it is a direct child of `ReplayError` and **not** of
  `ReplayMetricsError` (a caller skipping a bad *report* must not silently skip
  the alert — the non-nesting law this file already states twice).
- Update the module docstring's "five subclasses" narrative and `__all__`.

### Edited — `__init__.py`
- Import + alphabetical `__all__` entries.
- A **Feature 253** docstring paragraph in the form 251/252/254 already take,
  including the forward-reference fix-up: 252's and 254's text already points at
  this feature, so the paragraph says 253 has arrived where it pointed.

### New — `packages/replay/tests/test_alert.py`
The feature's law, in the order a replay meets it: the kind is the spec's
spelling; the threshold and target are quoted from 252, not restated; a fast
replay emits nothing; exactly 200 ms emits; the record carries the pair, the
duration and the threshold; frozen; the flag is the reading and a self-contradicting
carrier is refused; a bare number / NaN / negative duration is refused; the
`if`-not-taken returns `None` while a suspected replay raises; the emission is
**post-hoc** (unreachable inside the measured block); a foreign carrier is
accepted duck-typed; the error is `ReplayError` and *not* `ReplayMetricsError`;
the feature registers no component; the public surface.

### New — `tests/replay/test_recomputation_alert.py`
The assembled-system chain (the acceptance gate collects **only** `tests/`, so
this is the file the gate grades): the composed application still carries the
replay path and the member still registers exactly one component; a duration
measured off the **real** `measure_replay` timer emits the alert; the alert's
record is the same fact 254's report carries on its tail (253 and 254 composed in
a *test*, never in the packages — the feature-244 precedent); the emission's class
is compared **by name**, because the loader's synthetic import makes
`pytest.raises(<canonical>)` false across the seam.

### Not touched
`duration.py`, `metrics.py`, `returns.py`, `transition.py`,
`src/app/modules/replay/__init__.py`, and every shared file
(`module_loader.py`, `settings.py`, `middleware.py`, migrations, other members).

## Verification

```
export UV_CACHE_DIR=$PWD/.claw-forge/tmp/uv-cache
uv run pytest packages/replay/tests tests/replay -q     # both: gate grades tests/ only
uv run ruff check <the three new/edited files>          # scoped; repo baseline is red
```

Baselines already measured on this worktree: `packages/replay/tests` →
125 passed / 4 skipped; `tests/replay` → 14 passed. Both must stay green plus the
new tests.
