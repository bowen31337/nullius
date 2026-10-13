# Result: M2 with the multi-theme composite root

Pre-registration: `2026-10-13-m2-composite.md` (sha256 `f476b9fc73bd3b95aecad5262f4e90a9c03a1d7f25ae9401b3dce1c3f2936d3b`, verified unchanged), plus the operational addendum (`.ADDENDUM.md`: two aborted launches of archK01, neither of which observed an OOS figure, $4.47). Scored 2026-10-14 by the pre-registered rule.

**Verdict: FAIL.**
- 10 campaigns (archK01–10), $67.14 (plus $4.47 aborted), 0 VOID. Gate A p ranged from 0.07 to 0.98.
- Post-cost discoveries: **0 in every campaign.** On the gross IC rule there were 0–3 per campaign, 5 in total.
- No commits. Median `oos_ir` with misses counted as 0: 0.0. 0 positive picks.
- This is the first M2 test whose figures are **net of turnover costs** (COST-1).

## Secondary
| Nodes | n | Median IC t | IC > 0 | IC t ≥ 2 | Median gross IR t | Max gross | Median net IR t | Max net | Median cost drag (IR t) | Median turnover |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 297 | +0.50 | 87% | 5 | −0.33 | +2.29 | −1.13 | +1.14 | 0.77 | 0.42 |
| roots (depth 0) | 234 | +0.41 | 85% | 2 | −0.42 | +2.29 | −1.19 | +1.01 | 0.76 | 0.43 |
| refined (depth 1–3) | 63 | +1.06 | 95% | 3 | +0.29 | +2.15 | −0.55 | +1.14 | 0.95 | 0.39 |

Correlation of IC t with gross IR t across nodes: 0.63.

## Reading
1. **Combining did not add breadth.** The composite's median root IC t (+0.41) is below its strongest component's (attention-volume +2.07 in the v2 test) and close to the weakest components'. Equal-weighting diluted the one strong effect rather than adding independent ones.
2. **Costs are now measured, and they are large at this cadence.** Turnover of about 0.4 per 2-weekly rebalance costs about 0.8 IR t at 10 bps taker. To keep the drag below 0.3 IR t, turnover needs to be about 0.15 or less.
3. **The binding problem comes before costs: positive rank IC, negative book.** 87% of nodes have IC > 0, yet the median *gross* IR t is −0.33. The z-weighted book loses money while the rank correlation is positive, which points to the weighting or the return tails (for example, short-leg squeezes in fat-tailed coins dominating the book). This is the next thing to diagnose. It needs no LLM, and it can be run on in-sample dates only, which costs no OOS look.
4. **Refinement helps.** Refined nodes double the IC t and turn gross IR positive, but their turnover drag cancels the gain.
5. **Data reuse:** this is the sixth failed look at one OOS window. This test spent no OOS look, because there were no commits.

## Next (author's decision, per the standing order and §2.3)
1. An **IC→book diagnostic**, in-sample only: leg decomposition and tail attribution for the archetype signals, comparing the current z/Σ|z| book with inverse-volatility-scaled and winsorized-return books. Note that the live book member already volatility-targets (F303), while the research book does not.
2. The **perp book** spec (perp returns plus funding carry, perp fees of 2/5 bps), which also aligns research with the BingX venue. Its weighting is informed by step 1.
