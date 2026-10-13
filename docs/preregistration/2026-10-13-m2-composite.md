# Pre-registration: M2 with the multi-theme composite root (the PRD §2.3 breadth pivot)

- **Registered:** 2026-10-13, before any campaign below runs. `main` is at `99c2588`, which commits the tenth root `multi-theme-composite` with its brief (additions_spec_composite_theme.xml), and which **charges turnover on the book for the first time** (bug_spec_turnover_cost_charge.xml, COST-1). Commits since the spec: 0c567e7, 599be7d, 9d55ae7, 62c60c1, d35d498, 99c2588.
- **Why:** the v2 guided-themes test failed (`2026-10-13-m2-guided-themes.RESULT.md`). Five themes had IC in their stated direction, with median root IC t of +0.57 to +2.07, but none reached the IR bar alone: the max root IR t was 1.70, and that figure was **gross**. COST-1 found that the per-symbol fee cancels in a centered book, so no earlier M2 figure was ever net of costs. The owner approved a composite root on 2026-10-13. It equal-weights those five components, each oriented per its brief; the aim is breadth.
- **Data reuse, disclosed:** this is the **sixth** look at the 2025-08 to 2026-09 OOS window. The five components were selected using the v2 test's **in-sample** results only; the v2 test's single OOS figure (one pick) played no part. The weights are fixed in advance as equal. A pass must be read with this reuse in mind; the forward VST shadow is the uncontaminated check.

## Design
- 10 Type-R campaigns, named `archK01`–`archK10`, run with `NULLIUS_LEGAL_THEMES=multi-theme-composite`, so every root is a composite.
- Flags: `--workspaces 24 --rounds 3 --width 4`. That is 24 roots plus up to 12 refinements per campaign, so the tree actually refines; the earlier tests had one child each.
- Config `evaluation-config-archive-derivs.json`, unchanged: the 2-weekly grid with 92 in-sample dates, horizon 10 and 30 OOS dates, on snapshot 75d0a1.
- Selection is on `ir_tstat`, which is now **net**: 10 bps taker × traded notional Σ|Δw| per rebalance, entry included. The gross figure (`ir_tstat_gross`) is reported as a diagnostic. The KS gate is null self-calibration. Neither has changed since the earlier tests.

## Primary outcome (decided in advance; the same rule as all four earlier tests)
Over non-VOID campaigns, using the committed pick's cost-adjusted OOS IR (`oos_ir`, now genuinely net of turnover costs), with a miss counted as 0:
- **Pass:** median `oos_ir` > 0 **and** at least 6 committed picks with `oos_ir` > 0.
- **Fail:** the spot-book signal family is exhausted on this window. Next comes the perp instrument (funding and basis as carry, with a cost model for perpetuals), then a paid-data trial, then the forward VST shadow.

## Secondary (reported, not decisive)
- post-cost discoveries per campaign, and the gross-rule count for comparison with the earlier tests
- net versus gross IR t (the cost drag, measured for the first time)
- root versus refined (depth ≥ 1) IR t
- the share of composite roots whose code uses all five components
- OOS IC t
- turnover
- VOID or insufficient rate, and gate p-values
- spend
