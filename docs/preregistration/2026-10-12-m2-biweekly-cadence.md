# Pre-registration: M2 at 2-weekly cadence (the PRD §2.3 cadence pivot)

- **Registered:** 2026-10-12, before any campaign below runs. `main` at `0a6083e` (cost-aware selection plus the null-calibration KS gate).
- **Why:** the cost-aware weekly test failed (`2026-10-11-m2-cost-aware.RESULT.md`): almost no node survives costs at weekly cadence. §2.3 names rebalance cadence as the next lever.
- **Data reuse, disclosed:** this is the third look at the 2025-08 to 2026-09 OOS window. Its 2-weekly grid, horizon and success rule are fixed here before running. Every campaign is charged to the trial ledger.

## Design
- 10 Type-R campaigns, `--workspaces 32 --rounds 1 --width 1`, named `archB01`–`archB10`.
- Config `evaluation-config-archive-biweekly.json`: 92 in-sample dates every 14 days (2022-01-03 to 2025-06-30), horizon 10, 30 OOS dates every 14 days (2025-08-04 to 2026-09-14), 4 evaluation workers, 400-day history cap.
- Close-out selects and commits on the post-cost rule. The KS gate is null self-calibration (`ks_variant` "null-calibration").
- Pre-checked on this grid before registering (2026-10-12): the null IC t of 20d momentum, 5d reversal and 20d vol is ~N(0,1) (sd 1.04–1.09, P(|t|>1.96) 0.055–0.06), with no tripwire false positives.

## Primary outcome (decided in advance; same rule as the weekly test)
Over non-VOID campaigns, using the committed pick's cost-adjusted OOS IR (`oos_ir`), with a miss (no post-cost discovery) counted as `oos_ir` 0:
- **Pass:** the median `oos_ir` > 0 **and** at least 6 committed picks with `oos_ir` > 0.
- **Fail:** otherwise. Per §2.3, the next pivot is inputs: the free data streams (funding history, perp–spot basis, intraday klines, aggTrade order flow).

## Secondary (reported, not decisive)
- post-cost discoveries per campaign
- committed picks' OOS IC t and in-sample turnover
- the VOID rate under the new gate, with gate A and gate B p-values
- sensitivity and specificity
