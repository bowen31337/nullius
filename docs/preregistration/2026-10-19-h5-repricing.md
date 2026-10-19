# Pre-registration: re-pricing the horizon-5 committed picks (universe, fees, weights; no new hypotheses)

- **Registered:** 2026-10-19 (AEDT), before any pick below has been scored under any of the three configurations. `main` is at `388dd0af` (features 1–5 of `additions_spec_engine_edge_recovery.xml` merged; feature 6, the portfolio scorer this test runs on, was still in its worktree).
- **Why:** `docs/research/2026-10-19-alpha-diagnosis.md` (f8d562fe). The strongest in-sample signal the system has produced is the horizon-5, weekly cross-sectional reversal/divergence construct on the spot archive (IC t ≥ 2 in 84% of real nodes against 2.5% of planted nulls, positive in each of 2022, 2023, 2024 and 2025H1). Its committed picks were then scored out of sample at horizon 10, at 5 bp taker fees, with z-weights, on 85 names, and lost 11.5 bp per period, of which 6.6 bp was fees and the gross had t ≈ −0.5. The engine, not the signal, is the suspect. This test changes **only the engine**: the horizon the picks were selected at, the universe, the fee mode and the weighting. The picks and their code do not change.
- **What this is not:** no campaign, no LLM call, no new node, no dreaming, no capital. It is a re-pricing of 28 stored picks over the same out-of-sample dates under three evaluation configurations.
- **Data reuse, disclosed in full:** the 2025-08 to 2026-09 archive window has now been read **eight** times; this is the ninth, and the construct was chosen because of what the eighth showed. A pass here is evidence about the engine's pricing, not a discovery, and leads to a forward paper test (below), never to capital.

## The picks (fixed by rule, listed in `2026-10-19-h5-repricing.picks.json`, hashed beside this file)
Every `replay_score` row with `policy_version = 'm2-fixed'` and a non-null `committed_pick`, on a campaign whose `campaign.horizon` is 5 and whose `grid_last_date` is 2025-06-30 (the 183-date weekly grid, `evaluation-config-archive-m3.json`): **28 picks** from 28 campaigns (36 such campaigns exist; 7 have no close-out row and 1 abstained). By theme: cross-asset-divergence 22, borrow-rate-conditioning 2, calendar-events 2, volatility-dispersion 1, order-flow-imbalance 1. All are roots. Median in-sample IC t 3.74, median turnover 0.66. The M2 rule committed them in-sample on snapshot 540e93 (spot, 100 names) at horizon 5; close-out's `m2-fixed` rows are their only prior out-of-sample scores, and those were computed under each campaign's own (spot) config. Picks whose root is a planted null are **included** (the rule committed them) and their count is reported.

## The arms
Each arm scores the 28 picks with `./run.sh portfolio-oos --picks docs/preregistration/2026-10-19-h5-repricing.picks.json` under one evaluation config, which fixes: the sealed snapshot, the 60 weekly out-of-sample Mondays 2025-08-04 to 2026-09-21 (`evaluation-config-archive-m3.json`'s grid), horizon 5 (the campaigns' own, also the config's), instrument perp with returns net of funding, the beta-neutral book (60-day BTC beta), the cost model `binance_usdm.yaml`. Fees and weights are per arm:

| Arm | Config (sha256) | Snapshot | Names | Execution (per unit traded) | Weighting |
|---|---|---|---|---|---|
| **A, primary** | `evaluation-config-wide-h5-maker-iv.json` (`8b1fa2d96d0396f9364f4c1dcc8cc2b7108f6136b87b466dd8404f139bc32c83`) | `2026-10-19T02:33:08Z_86b4c2` (hash `86b4c2b7…`) | 239 perps | maker: 2 bp + 1.5 bp queue penalty = 3.5 bp | inverse 60-day volatility |
| B, control (fees and weights) | `evaluation-config-wide-h5-taker-z.json` (`f140a78bee2d6169a1cfdf5e2f375c9af5cd176285a06dc31bc18c67b07731ca`) | same | 239 perps | taker: 5 bp | z |
| C, control (universe) | `evaluation-config-narrow-h5-taker-z.json` (`4fc587d2ada19ef7fa3a0b9e38b93389b7698f093cea8fb3dba2a86631bfd0ef`) | `2026-10-12T03:50:56Z_75d0a1` | 85 perps | taker: 5 bp | z |

A − B isolates fees and weights on the wide universe; B − C isolates the universe. The wide snapshot's `metrics` stream is partial (89 of 239 names at seal); none of the 28 picks reads it (they are bars-only signals), and a symbol without a stream is neutral by the missing-input rule.

## Primary outcome (decided now)
Arm A's **equal-weight portfolio of the 28 picks**, per-date net return over the 60 out-of-sample dates: **pass** iff its mean is > 0 **and** its t-statistic mean/sd·√60 is ≥ 2.0. Otherwise **fail**. One computation per arm; the first complete run of arm A is the verdict. A refusal by the scorer (missing artifact, admission failure) is recorded in an ADDENDUM and fixed before the verdict; it is never scored.

## Secondary (reported, not decisive)
- Arms B and C on the same statistic; A − B and B − C per date.
- The portfolio's effective number of independent bets (N_eff) and mean pairwise correlation; per-pick mean, sd, t, and out-of-sample IC t; the per-theme breakdown.
- Gross versus fees (arm A at zero fees, via a fourth config identical to A with a zero-fee cost model, reported only).
- The count of picks whose root is a planted null, and the primary statistic with them excluded.

## What follows
- **Pass:** the reversal construct is promoted to a **paper-only forward book** (a sibling of `2026-10-19-shadow-paper-attention.md`, same window if it can still start by 2026-10-26, otherwise a new window), pre-registered separately before any forward data exists; and the first wide-universe campaign series (`M2-wide-h5`, new hypotheses, planted nulls, tripwires at horizon 5) is pre-registered on arm A's configuration.
- **Fail:** the horizon-5 reversal construct is recorded as not surviving out of sample even at maker fees with risk weights on 239 names. The wide-universe campaign series may still be pre-registered on arm A's configuration, with no priority for reversal.
- Either way, nothing here reopens dreaming (M3 is FAIL and final for its space).

## Preconditions (before arm A runs)
- `deploy/campaign/null_power_check.py` and `deploy/campaign/tripwire_fp_check.py` on the horizon-5 weekly grid of the wide snapshot: the planted-null t-statistics must be ≈ N(0,1) with P(|t| > 1.96) near 0.05. A failure is an engine defect to fix first; it is recorded here as an ADDENDUM.
- The nightly evaluation canary passes after features 1–5 merged (the default path must still reproduce the frozen score to 1e-12).

## Trial ledger
One hypothesis ("the horizon-5 committed picks are net-positive out of sample under maker execution and inverse-volatility weights on the wide universe"), charged once, whatever the three arms show.
