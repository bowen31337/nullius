# Where the edge is, and is not: a diagnosis after the M3 FAIL

**Written 2026-10-19 (AEDT) from `main` at `6499cbe7`.** Every figure below comes from the research store, the stored node artifacts, and one re-evaluation sweep of the 90 nodes that hold an out-of-sample score (re-run under the pinned config and cost model, once at the real fee schedule and once at zero fees; all 90 reproduced their stored scores to 1e-12). Nothing here is a new look at the archive OOS window beyond scores that already existed; the decomposition and correlations are read from those same 90 picks. The window has now been read eight times and is treated as exhausted.

## 1. The question
Seven pre-registered tests failed by their own rules: six M2 tests of the fixed selection rule, then M3, the test of whether dreaming (offline revision of the selection policy) beats it. The PRD is explicit that dreaming "improves search efficiency within a space; it cannot create edge in a space that has none" (§9). So the question is not how to dream harder. It is whether this system's signal population contains edge at all, where, and what stands between that edge and a positive out-of-sample return.

## 2. Units first
`cost_adjusted_ir`, the score every verdict was computed on, is the **mean per-date post-cost return of the node's own dollar-neutral, gross-1 book** (`w_i = z_i / Σ|z_j|`), in return units: −0.0004 means −4 basis points per 10-day period, about −1%/yr. It is not an information ratio. The PRD's M3 threshold ("ΔIR > 0.3") was written for a ratio and could never bind on this field; M3 failed on its significance test and selection bar regardless. Out of sample the per-date standard deviation of a single node's book is **about 42 bp**, so on the 30-date OOS grid a node needs a mean of about 15 bp per period for t = 2.

## 3. What the out-of-sample picks say (86 clean worlds, 79 picks)
Seventeen of the 103 "financial worlds" M3 judged were not out of sample: their in-sample grids ran to 2026-06-29 or 2026-09-30 (recorded in the M3 RESULT erratum). On the 86 clean worlds the committed picks of every policy, M2's and the dreamed ones alike, average −3 to −4 bp per period with 34% positive. Decomposed by construct (one row per theme and authoring snapshot, re-evaluated at the real and at zero fees):

| Construct (snapshot) | n | gross bp | fees bp | net bp | OOS IC t (median node) | per-node net t | turnover |
|---|---|---|---|---|---|---|---|
| attention-volume (75d0a1) | 5 | **+17.9** | −4.7 | **+13.2** | **+1.72** | **+1.59** | 0.48 |
| multi-theme-composite (75d0a1) | 9 | +7.4 | −4.1 | +3.3 | +1.62 | +0.19 | 0.36 |
| funding-crowding (75d0a1) | 10 | +4.4 | −2.9 | +1.5 | +0.31 | +0.23 | 0.28 |
| cross-asset-divergence (540e93) | 26 | −4.9 | −6.6 | −11.5 | −0.04 | −1.26 | 0.67 |
| calendar-events (both) | 10 | +0.3 | −3.8 | −3.5 | +0.15 | −0.3 | 0.38 |
| everything else | 19 | mixed | −2 to −8 | mixed | see §5 | | |

Three facts follow.

**No construct is significant on its own.** The best, attention-volume, is five independently written implementations of one mechanism (fade 7-day volume and trade-count spikes against a 90-day baseline). Their OOS book returns correlate at 0.97, so they are one draw, not five: one construct, t ≈ 1.6 on 30 dates. Every other construct's picks correlate at 0.5–0.9 within theme for the same reason. The 90 picks are roughly 14 constructs on one window.

**Fees are most of the bleed.** The old-snapshot reversal construct (cross-asset-divergence, 26 picks) loses 11.5 bp per period, of which 6.6 bp is the 5 bp taker fee on turnover 0.67 and 4.9 bp is gross (t ≈ −0.5). Across all 90 picks fees run 3–7 bp per period. A maker fee (2 bp on BingX and Binance USD-M alike) would cut that by 60%.

**The reversal construct was scored out of sample at the wrong horizon.** Its campaigns selected on the 183-date weekly grid at horizon 5 (`evaluation-config-archive-m3.json`); M3 scored every world at the pinned config's horizon 10. Its OOS IC at horizon 10 is exactly zero (−0.002). Short-horizon reversal has not had a fair out-of-sample test at its own horizon.

## 4. What the in-sample record says, construct by construct
Planted-null labels, resolved to each node's root (children inherit the root's label; the sidecar stores roots), separate real signal from multiplicity. Pass rate at IC t ≥ 2 over the in-sample grid:

| Construct | snapshot, grid, horizon | real | planted null | per-year IC t (median node) |
|---|---|---|---|---|
| cross-asset-divergence | 540e93, 183 weekly, h=5 | **197/235 = 84%** | 1/40 = 2.5% | 2022 +3.0, 2023 +1.8, 2024 +2.0, 2025H1 +0.4 |
| volatility-dispersion | 540e93, 183 weekly, h=5 | **163/226 = 72%** | 0/32 | +3.2, +0.4, +2.3, +2.2 |
| borrow-rate-conditioning | 540e93, 183 weekly, h=5 | 113/259 = 44% | 1/56 = 1.8% | +2.8, +1.3, +2.4, +0.1 |
| attention-volume | 75d0a1, 92 biweekly, h=10 | **63/95 = 66%** | 2/13 = 15% | +2.8, +1.3, −0.2, +1.1 |
| funding-crowding | 75d0a1, 92 biweekly, h=10 | 8/142 = 6% | 5/19 = 26% | +0.7, +0.7, +1.7, +0.2 |
| multi-theme-composite | 75d0a1, 92 biweekly, h=10 | 1/243 = 0.4% | 4/60 = 7% | +1.3, +0.5, +0.9, +0.5 |
| basis, OI, positioning, taker-flow, low-vol, beta, momentum | 75d0a1, h=10 | 0–2% | 0–3% | — |
| cross-asset-divergence, vol, borrow | 75d0a1, h=10 | 0–2% | 0% | — |

So the system has produced genuine, year-after-year in-sample cross-sectional IC in exactly four constructs, and the three strongest live at **horizon 5 on weekly dates** and vanish at horizon 10 on biweekly dates (the same themes on the perp snapshot pass at 0–2%). The perp and spot closes are date-aligned to within 11 bp, and the spot bars are identical in both snapshots, so this is horizon and cadence, not data. The fourth, attention-volume, survives at horizon 10. None of the derivatives themes (funding, basis, OI, positioning, taker flow) shows in-sample IC that planted nulls do not match.

The fast constructs' in-sample **net** return was already about zero (cross-asset-divergence median −1.8 bp per period at turnover 0.65): real IC, eaten by 10 bp round-trip taker fees at weekly rebalancing. That is the whole history of the cost-aware and cadence tests in one line.

## 5. Two defects that convert IC into losses
**Weighting.** Out of sample, the slow risk constructs show *positive and sizeable rank IC* while their books lose money: low-volatility IC +0.10 (t 2.2) with gross −9 bp; volatility-dispersion (75d0a1) IC +0.08 (t 2.1) with gross −6 bp; beta-to-btc IC +0.12 (t 2.2) with gross **−22.5 bp**. Rank correlation measures how often the ranking is right; the z-weighted book's return is dominated by the few names with the most extreme z and the highest volatility, which in a crypto cross-section (volatility dispersion of 3–5× across names) is the short leg of every "low-risk" signal. The signal is right and the book is wrong. Inverse-volatility or rank weights, with the beta-neutral rescale already in place, is a construction change testable entirely in-sample on stored scores; it does not touch the signals.

**Fees.** 3–7 bp per period at 5 bp taker. At 2 bp maker the diversified perp-era book below goes from net zero to net positive. Passive execution has an adverse-selection cost the evaluator must model (PRD §10); today it charges a single bps constant and has no maker mode.

## 6. The one portfolio-shaped result
Equal-weighting the OOS book returns of in-sample-chosen picks (no OOS information used in the choice):

| Portfolio | K | OOS mean | per-date sd | t | N_eff |
|---|---|---|---|---|---|
| all picks, both snapshots | 78–90 | −4.0 bp | 16 bp | −1.4 | 7–8 |
| 75d0a1-authored picks only, **gross** | 41 | **+4.3 bp** | 17 bp | **+1.39** | 6.2 |
| 75d0a1-authored picks only, net of 5 bp taker | 41 | +0.4 bp | 17 bp | +0.14 | 6.2 |

Combining across constructs cuts the per-date volatility from ~42 bp to ~17 bp (about 6–8 independent bets), and the perp-era population's combined gross edge is +4.3 bp per period, t 1.4 on 30 dates, which fees take to zero. In Sharpe terms that is roughly 1.3 gross, 0 net at taker, about 0.8 net at maker, from a book whose annualised volatility at gross 1 is under 1% (it would be levered to a vol target in practice; fees scale with it, Sharpe does not). This is weak evidence, but it is the only edge-shaped evidence in the record, and it is a property of the **population combined**, not of any pick. The evaluation unit that matters is the book of committed signals, not one committed signal.

## 7. What this says about dreaming
A selection policy chooses one node per tree from in-sample statistics whose true effect sizes give t ≈ 1 over 92 dates. No such policy can be revised into alpha, because the information it selects on is at the noise floor: M3's planted nulls were picked as often as real nodes (FDR_deploy 0.96 against a 0.9 prior), and within the bootstrap pool dreaming genuinely generalised (holdout 0.18 vs 0.08) while moving the financial arm by 0.0000164. The pre-registration's ruling stands and is right: dreaming is closed in this space. The only space in which a learned policy could matter is one where selection has something to learn, which the record says is portfolio construction over many weak signals on an engine with power. That engine does not exist yet. M3b, if ever, comes after §8, not before.

## 8. What to do, in order
1. **Forward test the one positive construct, untouched.** Done today: `docs/preregistration/2026-10-19-shadow-paper-attention.md`, a paper-only book of five attention-volume nodes chosen by in-sample rule (planted-null roots excluded, which removes the two top-ranked candidates including the M2 pick and the canary node), built daily from the same snapshot shadow v1 uses and scored by v1's formula over v1's window (2026-10-19 to 2027-01-18). Zero capital, zero spend.
2. **Fix the engine where the record shows it loses edge it already has**, all in-sample-testable and none touching the signals: (a) inverse-volatility or rank weights for the research book, beside the existing beta-neutral rescale; (b) a maker-fee pricing mode with an explicit adverse-selection charge; (c) score a stored node out of sample at *its own* horizon, and admit as a financial world only a campaign whose last in-sample date precedes the first OOS date; (d) a portfolio OOS score for a committed *set*, so the thing the record says carries edge is the thing that gets measured.
3. **Breadth.** The Binance USD-M archive holds 900 perpetual symbols; of the archive's top 300 spot symbols by median volume, 239 have a perpetual history and 174 are live BingX USDT perpetuals (390 and 273 at top 500). The research universe is 85. `IR ≈ IC·√breadth` (PRD §9.2) is the cheapest multiplier left, and the capacity argument (§9.1) says the names between rank 100 and 300, at $2–8M daily volume, are where a $50k book is invisible.
4. **Horizon, fairly tested.** Pre-register one test of the reversal construct at horizon 2–5 on daily or weekly dates, on the wide perp universe, priced at maker with adverse selection, with the planted-null and tripwire checks re-run at that horizon first. It is the strongest IC the system has ever produced and it has never been scored out of sample at its own horizon or at a fee it could survive.
5. **Then M2 again**, on the wide snapshot with the fixed engine, scored as a portfolio of committed picks, with the forward shadow as the uncontaminated check and the archive window disclosed as exhausted.

Each of 2–5 is charged to the trial ledger and pre-registered before its data is seen, as §2.3 requires. None reopens dreaming.

## Appendix: evidence trail
- Sweep: `scratchpad/reeval/` (reeval.py, analyze.py, 180 JSON outputs; net and zero-fee runs; all 90 net scores matched the store to 1e-12).
- Clean-world classification: 56 worlds on the 92-date biweekly grid and 30 on 183/180-date weekly grids, all ending 2025-06-30; 7 on a daily grid to 2026-09-30; 6 on the 235-date weekly grid to 2026-06-29; 4 smoke campaigns without artifacts.
- Null labels: `~/.local/share/nullius/lake/null/sidecar.enc`, 3,086 roots; 3,376 of 3,415 nodes resolve through `parent_id`; the 39 unresolved are depth-0 nodes of smoke campaigns.
- Universe: `lake-archive/staging-meta/um-archive-symbols.json` (900 UM symbols, listed 2026-10-19), `rank-2019-01-01_2026-09-30.json`, `lake-shadow/contracts.json` (848 live BingX USDT perpetuals, taker 5 bp, maker 2 bp).
