# Feature 280 — The meta-level selection bar

**app_spec.xml, "Dreaming Loop & Meta-Selection", feature 280**
(`shape="plugin"`, `plugin="dreaming"`, `depends_on="278"`):
*System rejects a winning revision whose advantage falls below the square
root of twice the log of M scaled by score deviation.*

An eighth sentence in the existing dreaming member (`packages/dreaming/`),
not a new member: the verdict §C5's loop ends on. The loop's last clause is
*"select the argmax under §7"*, and this feature is the refusal that answers
*what if the argmax is noise?*

## Where the documents state it

Three places, one bar:

* **PRD §7.3** states the statistic itself, for the level below:
  *"Expected maximum Sharpe under the null across `K` trials grows like
  `√(2 ln K)`, in units of `SE(Sharpe)`"* — K=10 → 2.15, 100 → 3.03,
  1,000 → 3.72, 10,000 → 4.29.
* **PRD §12.1** lifts it to the meta level: *"Applying the `√(2 ln M)` bar at
  the meta level, with `SE(V) ≈ σ_V/√n_worlds`, the selected policy's true
  advantage survives selection noise only when `true_advantage >
  √(2 ln M) · σ_V / √n_worlds`."* Its worked check: at `M = 40`
  (bar ≈ 2.72), `σ_V ≈ 0.8`, target advantage 0.3 → **n > 53 worlds**,
  *"independently reproducing the ~56 from the paired-power calculation in
  §11.0"*.
* **Architecture §10.3.1** ("Meta-level selection discipline") states the
  enforcement stance: *"The orchestrator enforces this as a hard precondition,
  not a guideline."* Appendix B carries the formula line.

## Why the winner needs a bar at all

The winner is a **max**, and a max is biased. Selecting the argmax over `M`
revisions scored on a fixed pool selects upward noise: the expected maximum
of `M` scores that carry *no* advantage at all is `√(2 ln M)` standard
errors. So a winner whose advantage sits below that many standard errors is
indistinguishable from the best of `M` nulls — §12.1's *"the dreaming loop
overfits its own replay pool"*, stated as arithmetic. Persisting it (feature
274's `policy_revision`) would enshrine selection noise as improvement.

**The repair is the incumbent, and that is why the refusal is safe.** The
paper's guarantee `V^{m★} ≥ V^0` holds *by construction* when the incumbent
is in the candidate set (feature 273): when nothing clears the bar, the
incumbent *is* the argmax. A refused winner is not a lost cycle; it is the
guarantee holding.

## Design decisions

1. **The bar is Appendix B's whole line, not the compressed one.** The
   feature's sentence says *"scaled by score deviation"*; the PRD's formula
   scales by `σ_V / √n_worlds` — the standard error of the mean score. The
   member's own existing narrative (features 276/277, written before this
   one) already attributes the full line to feature 280, so the module
   implements `√(2 ln M) · σ_V / √n_worlds`.
2. **The figures are feature 281's, carried not respelled.** §12.1's
   `σ_V ≈ 0.8` and §11.0's `σ_diff ≈ 0.8` are one figure (the two sections'
   `n > 53` and `~56` are two derivations of the same pool), so the store
   seam judges a whole `PairedDifference`: advantage = `mean_difference`,
   σ_V = `spread`, n_worlds = `paired_worlds`.
3. **M is read back from feature 277's record** — additions_spec_277's own
   integration promise (*"Feature 280's bar … read[s] M back from the record
   via `cycle_caps()`"*), and cap.py's stated reason for persisting at all:
   *"a bar computed over an M nobody recorded is a bar over a number nobody
   ran."* A retried cycle is re-decided, so the record in force is the
   **newest** for the iteration. Judging at the recorded cap (the bound, not
   a hand-counted actual) is the conservative direction: the bar grows in
   `M`, so a cycle that ran fewer revisions than its cap is judged against a
   bar at least as wide as the one its sweep earned.
4. **The edge is strict.** §12.1: *"survives selection noise **only when**
   `true_advantage > …`"* — equality does not clear, the same edge
   `PairedDifference.clears` states for the gate's own criterion.
5. **`M = 1` answers a bar of 0.** `ln 1 = 0`: the expected maximum of one
   null score is that score. Multiple-testing width begins with the second
   candidate. Not refused — it is the arithmetic's own value.

## Surface

| spelling | act |
|---|---|
| `selection_bar(m, *, spread, worlds) -> float` | Appendix B's arithmetic, over figures |
| `rejects_unbarred_winner(advantage, *, m, spread, worlds) -> None` | the verdict — the ladder's verdict-over-figures shape |
| `cycle_bar(iteration_id, difference, *, database_url, env) -> float` | the store seam — M read back from `cycle_caps()`, the `PairedDifference` judged at it; answers the bar cleared |
| `SELECTION_BAR_CODE = "advantage_below_bar"` | the verdict's greppable code |

Three new error siblings under `DreamingError`, split by **repair**:
`BarRequestError` (re-send the ask: malformed figures, iteration,
difference, or no database named), `BarRecordError` (the store holds no M:
no pool, or no recorded cap for the iteration), `SelectionBarError`
(`advantage_below_bar`: the figures are honest and the verdict is *no* —
keep the incumbent). The cap's request/record refusals are **translated at
the seam**, never propagated; the verdict carries the one code, minted on
the `pool_frozen` / `pool_too_thin` / `proportion_comparison` convention —
it is the one refusal an operator greps a deployment log for (*why did this
cycle keep the incumbent?*). The ask/store faces open with their subjects,
the stance `cap` and `split` state.

No `@register` component (feature 270's single `"dreaming"` component is
the member's whole composition), no seat change, no migration, no table:
the module reads `cycle_cap` and writes nothing. Stdlib `math` only, so the
factory's scan pays nothing for it.

## Files

| file | change |
|---|---|
| `packages/dreaming/src/dreaming/bar.py` | new — the arithmetic, the verdict, the store seam |
| `packages/dreaming/src/dreaming/errors.py` | three classes + `__all__` + the split's rationale |
| `packages/dreaming/src/dreaming/__init__.py` | the eighth sentence; the surface re-exported; the "not the selector" paragraph corrected |
| `packages/dreaming/tests/test_bar.py` | new — the feature's own suite |
| `packages/dreaming/tests/test_errors.py` | the sibling pin against the member's vocabulary |
