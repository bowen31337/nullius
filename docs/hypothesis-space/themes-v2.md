# Hypothesis space v2: guided themes

**Status:** approved by the owner, 2026-10-13. Under PRD §9 and NG4, the hypothesis space is the owner's decision; this is that decision.

**Why:** three pre-registered M2 pivots failed (`docs/preregistration/*RESULT.md`). The binding constraint is breadth: open-ended themes, of which the prompt shows only the slug, rarely yield cost-surviving signals. The agent's own derivative signals had median IC t −0.20, often with the wrong sign. v2 tells the agent the mechanism, the inputs, the expected sign and how to build a slow, cost-surviving version. Refinement then explores around a known effect instead of guessing one.

**The data each theme may use** (snapshot `75d0a1`, daily, point-in-time):
- `bars:1d`: open, high, low, close, volume, trade_count (100 symbols)
- `funding_1d`: funding_rate_sum, funding_rate_last (85 symbols)
- `basis_1d`: perpetual/spot − 1
- `taker_flow_1d`: taker_buy_ratio
- `metrics_1d`: open interest and value, top-trader and global long/short ratios, taker long/short volume ratio

**Evaluation:**
- 2-weekly rebalance, horizon 10
- a dollar-neutral spot book
- selection on the post-cost IR t-statistic

## Shared construction rules (rendered for every theme)

1. Score cross-sectionally. Rank or z-score within the date's universe; never raw levels.
2. **Slow down.** Use lookback windows of 7 days or more, smooth inputs (rolling means or EMAs), and aim for turnover below about 0.3 per rebalance. Weekly turnover of 0.66 erased the IC in the M2 baseline.
3. Missing inputs: symbols without a perpetual (15 of 100) or without enough history get the cross-sectional median score (neutral), never 0 by accident and never NaN.
4. **State the expected sign in the mechanism, and test the stated sign.** Do not flip the sign after seeing results; a flipped hypothesis is a new node.
5. Cast every string column to Float64. `ctx.feature(..., lookback=None)` and filter by symbol.

## Themes

| # | Slug | Mechanism (what to test) | Inputs | Expected sign | Notes and risks |
|---|---|---|---|---|---|
| 1 | `funding-crowding` | Persistently high positive funding means crowded leveraged longs paying to hold. Crowded coins underperform over the next 1–4 weeks | `funding_1d` 7–30d sum or mean; its rank | **Negative** (short high funding) | The best-documented crypto derivatives effect. Low turnover if smoothed. Spot-only book: we exploit the information, not the carry |
| 2 | `basis-premium` | A wide perpetual premium over spot signals speculative excess, and the premium and price mean-revert. A falling basis signals unwinding | `basis_1d` level (7d mean) and 7–14d change | **Negative** on level | Correlated with theme 1; let the tree discover which carries more |
| 3 | `oi-price-divergence` | Rising open interest into a falling price means shorts are piling in, so a squeeze or reversal follows. Rising OI with a rising price is late leverage, which is fragile | `metrics_1d` sum_open_interest_value 7–14d % change against the 7–14d price return; OI scaled by quote volume | Long OI-up/price-down; short OI-up/price-up | Normalise OI by the coin's traded value, so large caps do not dominate |
| 4 | `positioning-contrarian` | Retail long/short ratio extremes are contrarian. Divergence between top traders and the global ratio means smart money disagrees with the crowd | `metrics_1d` count_long_short_ratio, sum_toptrader_long_short_ratio; 7d means; top-trader minus global | **Negative** on the retail ratio; **positive** on the top-trader-minus-retail gap | Ratios are venue-specific (Binance only) |
| 5 | `taker-flow-persistence` | Sustained aggressive buying (the taker-buy share) reflects informed demand that keeps moving price | `taker_flow_1d` taker_buy_ratio 7–14d mean, against its own 60d baseline | **Positive** | At short windows this is order-flow reversal; keep windows long for continuation |
| 6 | `low-volatility` | Low-volatility coins outperform on a risk-adjusted basis: lottery-seeking investors overpay for volatile ones | bars: 30–90d realised volatility of daily returns; optionally idiosyncratic vol after removing a BTC beta | **Negative** on volatility | The slowest theme, so naturally low turnover. An honest 20d vol signal passed all tripwire probes on the archive snapshot 540e93 (it failed only on the short 92-day window) |
| 7 | `beta-to-btc` | Betting against beta: high-BTC-beta coins underperform after adjusting for risk | bars: 60–90d rolling beta of each coin's daily return on BTC's | **Negative** on beta | Needs BTCUSDT in the window, which it always is |
| 8 | `attention-volume` | Abnormal volume or trade-count spikes mark attention-driven overpricing, which unwinds over the next weeks | bars: volume and trade_count over 7d against 90d (log ratio); optionally conditioned on the return over the spike | **Negative** on the abnormal-volume rank | Liquidity proxy; keep only the persistent part (7d) |
| 9 | `intermediate-momentum` | 30–90d momentum that skips the most recent 7 days, avoiding short-term reversal | bars: return from t−90 to t−7 (or t−30 to t−7) | **Positive** | Historically weak and crash-prone in crypto. Keep it as the control the others must beat |

## Dropped from v1, with reasons
- `order-flow-imbalance` (as L2 microstructure): there is no order-book data. The free-data version is theme 5.
- `borrow-rate-conditioning`: there are no borrow rates. Funding (theme 1) is the observable cost-of-leverage proxy.
- `calendar-events`: there is no event calendar or unlock data in the lake.
- `cross-asset-divergence` (generic): replaced by the concrete divergences in themes 2, 3 and 4.

## Proposed implementation (after approval)
1. One committed theme file, the existing `signal-agent/legal_themes.json` extended with a `brief` per theme (mechanism, inputs, expected sign, notes). Discovery's legal set reads the same file, which removes today's two drifting lists.
2. The authoring prompt renders the node's theme brief and the shared construction rules.
3. A pre-registered M2 test as before: 10 campaigns, the same rule, 2-weekly cadence. Roots are planted round-robin over the 9 themes.
4. The theme change is recorded as a §2.3 pivot of the hypothesis space and charged to the ledger.
