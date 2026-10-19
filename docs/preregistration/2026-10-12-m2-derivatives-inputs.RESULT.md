# Result: M2 with the derivatives inputs

Pre-registration: `2026-10-12-m2-derivatives-inputs.md` (sha256 `4b15973d32746c7abaa230410cac7fa3c110da94b593231d39f1087c5646168f`). Scored 2026-10-12 by the pre-registered rule.

**Verdict: FAIL.**
- 10 campaigns (archD01–10), $22.41, 0 VOID. Gate A p ranged from 0.08 to 0.89.
- Post-cost discoveries: **0** in every campaign. IC-rule discoveries: 0–1.
- No commits. Median `oos_ir` with misses counted as 0: 0.0. No positive pick.

| Node population | n | Median IC | Median IC t | Nodes with \|t\| > 2 |
|---|---|---|---|---|
| archB (2-weekly, bars only) | 325 | 0.0117 | +0.72 | 55 |
| archD, nodes reading `ctx.feature` | 166 | −0.0033 | −0.20 | 4 |
| archD, bars-only nodes | 163 | 0.0065 | +0.35 | 0 |

**Reading:**
- Every authored `ctx.feature` call used `lookback=None`, so the features were consumed correctly. The bar files are byte-identical across the two snapshots.
- The derivative-feature signals the agent authored carry no edge, and are often of the wrong sign.
- The bars-only signals in this batch were also weaker than archB's. The likely cause is the enlarged prompt (feature documentation plus a funding example) steering designs. This is not proven, and LLM variance is also possible.
- Per §2.3, the pre-registered next lever is hypothesis-space breadth. This is the fourth failed look at one OOS window. NG4 and §9 make the choice of space a human decision, so this result is brought to the owner before any paid trial.

**Erratum (2026-10-20):** every in-sample and out-of-sample metric in this file is a horizon-1 (one-day-forward) figure, not the horizon-5 or horizon-10 figure its labels say; the engine scores the shortest aligned horizon regardless of the config (`2026-10-19-m2-wide-h5.ADDENDUM.md`, Addendum 2; `bug_spec_metrics_horizon.xml`). The numbers stand; the horizon labels do not.
