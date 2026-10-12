# Pre-registration: M2 with the derivatives inputs (the PRD §2.3 inputs pivot)

- **Registered:** 2026-10-12, before any campaign below runs. `main` at `b7ab008`, which serves the derivatives features (run23: `7977bbf`, `6043d17`, `668e874`, `fb7cc03`).
- **Why:** both earlier pivots failed by their pre-registered rules. The cost-aware weekly test found almost nothing surviving costs. At 2-weekly cadence, 2 of 10 campaigns found a cost-surviving pick; both were positive OOS, but breadth was too thin. §2.3 names inputs as the next lever.
- **Data reuse, disclosed:** this is the fourth look at the 2025-08 to 2026-09 OOS window. The feature set, grid and rule are fixed here, and every campaign is charged to the trial ledger.

## Design
- 10 Type-R campaigns, `--workspaces 32 --rounds 1 --width 1`, named `archD01`–`archD10`.
- Config `evaluation-config-archive-derivs.json`: the snapshot `2026-10-12T03:50:56Z_75d0a1` (bars plus funding, futbars and metrics; 85 of 100 symbols have a perpetual), the same 2-weekly grid as the cadence test (92 in-sample dates, horizon 10, 30 OOS dates), 4 workers, a 400-day history cap.
- The agent sees the point-in-time features `funding_1d`, `basis_1d`, `taker_flow_1d` and `metrics_1d` through `ctx.feature`.
- Selection is post-cost. The KS gate is null self-calibration.
- Pre-checked on this snapshot: the null IC t is ~N(0,1) for 20d momentum, 5d reversal and 20d vol (P(|t|>1.96) 0.055–0.06), with no tripwire false positives. Each window was checked to serve all four feature frames with no row after the decision date.

## Primary outcome (decided in advance; same rule as both earlier tests)
Over non-VOID campaigns, using the committed pick's cost-adjusted OOS IR (`oos_ir`), with a miss counted as 0:
- **Pass:** median `oos_ir` > 0 **and** at least 6 committed picks with `oos_ir` > 0.
- **Fail:** per §2.3, the next lever is hypothesis-space breadth: first the free cross-exchange liquidations and OI (Coinalyze), then a pre-registered, time-boxed paid trial.

## Secondary (reported, not decisive)
- post-cost discoveries per campaign
- the share of committed picks whose code reads a derivatives feature
- OOS IC t
- turnover
- VOID rate and gate p-values
- sensitivity and specificity
