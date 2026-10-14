# Pre-registration: M2 on research book v2 (USD-M perpetuals, beta-neutral legs)

- **Registered:** 2026-10-14, before any campaign below runs. `main` is at `0ce48fe`, which adds the beta-neutral book and the perp instrument (additions_spec_research_book_v2.xml) and the pool-worker fix (bug_spec_orphaned_pool_workers.xml). Commits: 5d468ba, 276def9, e611949, 67d5fe3, 3e5cef5, 1766716, eb69668, c0e3c1b, 0ce48fe.
- **Why:** five M2 tests failed. The composite RESULT's in-sample diagnostic, run on in-sample dates only, found two problems with the research book:
  - it carried market beta (low-vol's book β was −0.38; neutralising it lifted IR t from 0.69 to 1.11)
  - it was a spot book with no funding, while the live venue trades USD-M perpetuals
  PRD §2.3 names the perp instrument (funding as carry) as the next lever.
- **What changes, and nothing else:**
  - The book has beta-neutral legs: 60-day OLS beta to BTCUSDT, point-in-time.
  - Returns are perpetual (fut_close) net of funding over the holding period. Longs pay positive funding; shorts receive it.
  - Fees: 5 bps taker × traded notional (`binance_usdm.yaml`).
  - The universe is the symbols with a perpetual (85 of 100).
- **Data reuse, disclosed:** this is the **seventh** look at the 2025-08 to 2026-09 OOS window. The book changes were chosen from an **in-sample-only** diagnostic. The hypothesis space (the nine v2 themes) is unchanged and was approved before any OOS figure existed. A pass must be read with this reuse in mind. The forward VST shadow on the same perp venue is the uncontaminated check.

## Design
- 10 Type-R campaigns, `archP01`–`archP10`, `--workspaces 27 --rounds 3 --width 4`. The roots are round-robin over the **nine** v2 themes, 3 per theme, set with `NULLIUS_LEGAL_THEMES` to the nine v2 slugs. The composite root is excluded because it diluted the strongest component in the composite test.
- Config `evaluation-config-archive-perp-bn.json`: the derivs config (snapshot 75d0a1, the 2-weekly grid with 92 in-sample dates, horizon 10, 30 OOS dates) plus `instrument: "perp"` and `book: {beta_neutral: true, beta_window_days: 60, beta_benchmark: BTCUSDT}`. Cost model: `binance_usdm.yaml`.
- Selection is on net `ir_tstat`. The KS gate is null self-calibration. Authoring ceilings are 600k input / 300k output tokens.

## Primary outcome (decided in advance; the same rule as all five earlier tests)
Over non-VOID campaigns, using the committed pick's cost-adjusted OOS IR (`oos_ir`: net of perp fees and funding, on the beta-neutral book), with a miss counted as 0:
- **Pass:** median `oos_ir` > 0 **and** at least 6 committed picks with `oos_ir` > 0.
- **Fail:** next, in order:
  1. a time-boxed paid-data trial, pre-registered
  2. the forward VST shadow of the best in-sample candidates on the perp venue, which is uncontaminated and has no capital at risk

## Secondary (reported, not decisive)
- post-cost discoveries per campaign and per theme
- net versus gross IR t (the cost drag)
- the funding contribution to book return
- book beta (it should be about 0)
- the number of symbols dropped for having no perpetual
- root versus refined figures
- OOS IC t
- turnover
- VOID or insufficient rate, and gate p-values
- spend
