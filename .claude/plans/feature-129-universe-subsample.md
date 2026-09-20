# Feature 129 — the universe-subsample re-run

app_spec.xml: *"System re-runs a candidate against a 20 percent universe
subsample, persisting the subsample stability figure."*

Sibling: feature 127 (`packages/tripwires/src/tripwires/seed_rerun.py`), the
family's first axis. Feature 129 is the same probe along a *different knob*
(`PERTURBATION_AXES[2]`, `universe-subsample`).

## The perturbation, and why it is a different test

Feature 127 re-draws the **derangement**, holding the universe fixed. Feature
129 holds the derangement fixed (same seed) and **thins the universe** to a
20 percent subsample of symbols.

Verified discrimination (Monte Carlo, 120 dates x 30 symbols):

| candidate | axis 127 (seed) | axis 129 (subsample) |
|---|---|---|
| whole-panel leak (feature 133's 4 kinds) | 0.0000 (invariant) | mean figure 1.01–1.71, never 0 |
| symbol-concentrated candidate | collapses across seeds (carries **no** per-date book dispersion -> `surviving_sharpe` ~ 0 both seeds) | figure moves, range [-1.25, +0.79] |
| clean candidate | noise | noise |

So the two axes are not restatements: a whole-panel leak is invisible to 129
(and caught by 125/126), while a symbol-concentrated candidate is invisible to
125/127 and moves under 129.

## The figure — *stability*, not *degradation*

`subsample_stability = |rerun_sharpe − reference_sharpe| / reference_threshold`

A **magnitude**, unlike 127's signed degradation: 127's sentence names a
*direction* ("degradation") and its rule is one-sided; 129's sentence names
reproducibility, and the subsample may move the statistic either way.

## The threshold's derivation (verified)

Under the null, `rerun − reference` is a difference of two near-independent
draws. The subsample has `n` names, the panel `T` dates, so each draw's
standard error is `1/√T`; their difference has sd `√2/√T` in Sharpe units.
Expressing that in the *reference run's own* threshold units
(`z/√T`, `z = Φ⁻¹(1 − level/2)`) gives

    σ_Δ = √2 / z        ≈ 0.3882   at level 0.01

The figure is `|Δ|`, a folded normal, so the two-sided level-test bar over it is
`z · σ_Δ = √2` — **the z cancels**, because the same two-sided quantile both
standardizes the figure and sets the bar. Hence

    DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD = √2 ≈ 1.4142

Measured false-alarm against this bar, 400 draws each: 0.010, 0.013, 0.010,
0.012, 0.014 — nominal 0.01. Measured σ_Δ 0.396–0.413 against the derived
0.388 (≈ 5%). **Unlike 127's bar, this one is level-free and grid-free**: it
depends on neither `level` nor `T`. That contrast is asserted in the tests.

## Persistence

"Persisting the subsample stability figure" — 127's sentence has no such clause;
this one does, so 129 grows the persistence half. Precedent: feature 131 made
its own table (`tripwire_poison`) rather than widening `node`, because the
column features are another feature's. Same here:

- `tripwire_stability`, PK `(node_id, axis)` — one row per node per
  perturbation axis, so 128 and 130 can write their own axes beside this one
  and the four figures are comparable side by side.
- Accepts **passing** verdicts too (unlike the poison store): a stability
  figure is persisted whether or not the bar was exceeded. That is the point.

## Files

1. `packages/tripwires/src/tripwires/subsample.py` — the pure feature
2. `packages/tripwires/src/tripwires/stability.py` — the persistence half
3. `packages/tripwires/src/tripwires/layout.py` — the table's shape + DDL
4. `packages/tripwires/src/tripwires/__init__.py` — exports, probe method
   `subsample(...)`, stability builder registration
5. `src/app/modules/tripwires/stability.py` — the app seat
6. `packages/tripwires/tests/test_subsample.py` — the suite
7. `packages/tripwires/tests/conftest.py`, `test_component.py` — fixture + the
   pinned component list

## Seams kept

- The record must **not** carry `surviving_sharpe`/`threshold`: feature 131's
  `_validate_failure` checks structurally by those ten names, and a record that
  passed that check would be judged on 125's comparison over 125's statistic
  while 129 rejected on the *stability* bar. Same naming discipline as 127.
- The re-run is a **method on the probe component**, not a new component name —
  it is the probe taken twice.
