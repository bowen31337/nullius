# Result: M2 with the guided theme roots v2

Pre-registration: `2026-10-13-m2-guided-themes.md` (sha256 `e1f1d5822021a7c3529b7a11c2e24a46943e879abd8028a227d7a121ccc40838`, verified unchanged). Scored 2026-10-13 by the pre-registered rule.

**Verdict: FAIL.**
- 10 campaigns (archG01–10), $29.20, 0 VOID. Gate A p ranged from 0.13 to 0.84.
- Post-cost discoveries: **0** in nine campaigns and 2 in archG10. IC-rule discoveries: 3–4 per campaign.
- One commit, archG10's `d7bb84d9`: a depth-1 refinement of an `attention-volume` root, in-sample IC t 2.79, post-cost IR t 2.57, turnover 0.47. Out of sample: `oos_ir` −0.0001, OOS IC t −0.58.
- Median `oos_ir`, with misses counted as 0: **0.0**. Positive picks: **0 of 6 required**.

## Per theme (roots, archG01–09; planted nulls are mixed in, so these are aggregates only)

| Theme | n | Median IC t | Share with IC in the expected direction | IC t ≥ 2 | Median post-cost IR t | Max IR t | Median turnover |
|---|---|---|---|---|---|---|---|
| attention-volume | 35 | **+2.07** | 91% | 27 | 0.87 | 1.43 | 0.45 |
| oi-price-divergence | 27 | +1.13 | 96% | 0 | −0.81 | 1.68 | 0.60 |
| low-volatility | 27 | +1.05 | 89% | 0 | 0.00 | 1.70 | 0.14 |
| funding-crowding | 36 | +1.01 | 94% | 0 | 0.75 | 1.12 | 0.27 |
| intermediate-momentum | 36 | +0.57 | 94% | 0 | −0.10 | 1.02 | 0.25 |
| beta-to-btc | 36 | +0.42 | 89% | 0 | −0.61 | 1.21 | 0.13 |
| positioning-contrarian | 27 | +0.13 | 70% | 0 | 0.17 | 0.73 | 0.20 |
| basis-premium | 36 | −0.43 | 17% | 0 | −1.43 | 1.21 | 0.51 |
| taker-flow-persistence | 27 | −1.51 | 4% | 0 | −0.75 | −0.31 | 0.57 |
| **all roots** | 287 | **+0.54** | | 27 | | 1.70 | **0.27** |

## Reading
- **The briefs changed what the agent builds.** The median root IC t is +0.54, against −0.20 for the archD feature signals. Median turnover is 0.27, against 0.66 in the M2 baseline. Seven of nine themes have IC in the stated direction in most roots.
- **The effects are real in-sample but too small to survive costs as single standalone signals.** attention-volume clears the IC bar in 27 of its 35 roots, and costs take its median IR t to 0.87. The one node that cleared the post-cost bar was the batch's in-sample maximum after refinement. It did not hold out of sample, which is the winner's curse the M2 baseline already showed.
- **Two stated directions are wrong on this data:** basis-premium and taker-flow-persistence. Under rule 4 a flipped direction is a new hypothesis; it is recorded here and not tested.
- **These campaigns barely refine** (`--rounds 1 --width 1`: 32 roots plus one child each), the same as the three earlier tests. So this measures the briefs, not refinement around them.
- **Data reuse:** this is the fifth failed look at one OOS window. Any further test on this window must count all five looks.

## Next, per §2.3 (method falsified, not mission)
The pre-registered order is the perp instrument (funding and basis as carry), then a paid-data trial, then the forward VST shadow. The data here suggests one cheaper step to pre-register first. It is a **composite**: one node that combines the in-direction themes (attention-volume, funding-crowding, low-volatility, oi-price-divergence, intermediate-momentum) by equal-weighted ranks. The point is breadth: IR ≈ IC·√breadth, and these themes are only partly correlated. It would run with real refinement depth, and the expectation is set before the run.

## Correction, 2026-10-13 (after scoring): the "post-cost" figures were gross
`bug_spec_turnover_cost_charge.xml` (COST-1) found that the evaluator never charged turnover. The per-symbol taker fee cancels in a centered dollar-neutral book (Σw = 0). So `ir_tstat`, `cost_adjusted_ir` and `oos_ir` in this test, and in all three earlier M2 RESULTs, are **gross** book figures.
- **The verdict stands.** The rule's figures were gross, and costs can only lower them, so a FAIL on gross is a FAIL on net.
- **The reading "costs erase standalone signals" above is wrong.** The gap between IC t and IR t is a gap between rank IC and the z-weighted book return, measured before any cost. The likely causes are fat-tailed single-coin moves dominating the book, and rank correlation not translating into return. Costs have not yet been measured at all.
- The next test (the multi-theme composite) is held until COST-1 lands, so that its pre-registered figure is net.
