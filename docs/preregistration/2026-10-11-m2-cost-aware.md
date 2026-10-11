# Pre-registration: M2 re-measurement after cost-aware selection

- **Registered:** 2026-10-11, before any campaign below runs. `main` at `5f4c824` (run21: cost-aware discovery, commit and exploration).
- **Rule:** PRD §2.3. This is the second look at the 2025-08 to 2026-09 OOS window, which the first M2 batch (archM01–25) already used. The comparison is recorded here so the second look cannot be tuned after the fact.

## Design
- 10 Type-R campaigns, `--workspaces 32 --rounds 1 --width 1`, on `evaluation-config-archive-m3.json`: 183 in-sample weekly dates (2022-01 to 2025-06), 60 OOS weekly dates (2025-08 to 2026-09), horizon 5, 4 evaluation workers. Named `archC01`–`archC10`.
- The committed pick is chosen by close-out's post-cost rule (`selection_rule` "post-cost-ir").

## Primary outcome (decided in advance)
The committed picks' cost-adjusted OOS IR (`oos_ir`), across non-VOID campaigns with a commit:

- **Pass:** the median `oos_ir` > 0 **and** at least 6 of 10 committed picks have `oos_ir` > 0.
- **Fail:** otherwise. Per §2.3 the next pivot is rebalance cadence (2- or 4-weekly) against the cost model, then the free data streams (funding, basis, intraday, order flow).
- **Miss handling:** a campaign with no post-cost discovery counts as a miss with `oos_ir` treated as ≤ 0 (no pick is not a winning pick).

## Secondary (reported, not decisive)
- the OOS IC t of the committed picks
- in-sample turnover of the committed picks against the first batch's 0.66
- the share of campaigns with a post-cost discovery at all
- the sensitivity and specificity under the new discovery rule
- the triage AUC (pooled)

## Baseline being compared against
archM01–25 under the IC rule: median OOS `oos_ir` < 0, with 2 of 25 positive.
