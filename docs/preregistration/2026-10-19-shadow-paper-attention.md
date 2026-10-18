# Pre-registration: paper-only forward shadow of the attention-volume construct (five nodes, not traded)

- **Registered:** 2026-10-19 (AEDT), before any book inside the window exists. `main` is at `86138394` plus this file, `deploy/shadow/shadow_paper.sh` and the two `nullius-shadow-paper.*` units.
- **Why:** `docs/research/2026-10-19-alpha-diagnosis.md` finds that on the clean perpetuals snapshot (`75d0a1`, 92 biweekly in-sample dates ending 2025-06-30, horizon 10) exactly one construct has in-sample IC that planted nulls do not share: **attention-volume** (IC t ≥ 2 in 63 of 95 real implementations against 2 of 13 planted nulls). Its five committed implementations scored out of sample at +11 to +16 bp per 10-day period, a per-construct t of about 1.0 on one 30-date window. That window has now been read eight times and is exhausted as evidence. A forward test on untouched data is the only test left that reuse cannot contaminate.
- **Data reuse, disclosed in full:** the *construct* was chosen after seeing its archive OOS figure. The five *nodes* below were not: they are fixed by an in-sample rule stated here. The forward window has no data yet. A pass here is one untouched look, and must be read beside shadow v1 (funding-crowding), which runs on the same days.
- **What this is not:** no capital, no VST order, no change to `active_book.json` or to shadow v1, no dreaming, no LLM spend. It is a second book computed from the same daily snapshot and scored by the same formula.

## The nodes
Rule, fixed before any forward data: the top 5 `attention-volume` nodes on snapshot `75d0a1` by in-sample net `ir_tstat`, over campaigns whose in-sample grid ends 2025-06-30 (the 86 clean financial worlds), one node per campaign, deduplicated by `code_hash` and by identical (`ic_mean`, `ir_tstat`), **excluding every node whose root is a planted null** (resolved through `parent_id` to the root's sidecar label). The exclusion removes the two highest-ranked candidates, `d7bb84d9` (campaign c6990362, the M2 pick there and the canary's node) and `d889957f` (27321474): their in-sample statistics were computed against a permuted target and carry no evidence.

| # | campaign / node | depth | IS IC t | IS net IR t | turnover | IS net bp/period | code_hash |
|---|---|---|---|---|---|---|---|
| 1 | c6990362-aba1-4786-aeeb-142f17a92d88 / 0c54c52c-0a99-4d0f-80df-0a284d57c8e8 | 0 | 1.96 | 1.11 | 0.44 | +10.9 | b396c4a0…fdbb |
| 2 | e5fe11c1-6230-4567-88fc-f9c3400eb0ff / 9cb898e7-2f8f-4142-9718-1ff2aa95497f | 0 | 2.36 | 1.05 | 0.45 | +9.7 | 8653b909…4983 |
| 3 | 4e90d346-2fa1-458e-8811-e613849ed596 / 3c137f1b-f9b7-467c-a40a-0f940f22c700 | 0 | 2.19 | 1.01 | 0.46 | +9.7 | cdf994f1…210d |
| 4 | e5e33caa-2227-494c-8312-d2e541b93293 / 6b524eaa-b70b-4b8c-9643-e92b3fe66c31 | 0 | 2.37 | 1.00 | 0.46 | +9.4 | f8fed770…72d5 |
| 5 | 50899b45-42c7-4bf9-929e-ce20aad5ad99 / fd826eb6-855a-487e-89fb-cb43d5a547e1 | 0 | 2.34 | 0.96 | 0.44 | +9.0 | ca89b217…2c23 |

All five implement the same mechanism (7-day volume and trade-count against a 90-day baseline; fade the spike), so this is one construct replicated five ways, not five bets. Node 2 and node 5 are among the five whose archive OOS figures were seen; nodes 1, 3 and 4 have no OOS figure. The list is `~/.config/nullius/shadow/nodes-paper.txt`; `shadow-book` verifies each node's code against its stored `code_hash` on every run.

## The book
Identical to shadow v1's construction, through the same `run.sh shadow-book`: each node's z-scores become `evaluator.book_weights` with dollar-neutral, gross-1 legs rescaled to equal 60-day BTC beta; the five books are combined by equal-weight mean and renormalised to gross 1.0; symbols are restricted to live BingX VST contracts whose price is within 2× of the lake's perp close; `equity_usdt` 10000; config `evaluation-config-archive-perp-bn.json` (sha256 `6adc9a93…6425`), cost model `binance_usdm.yaml`. The book is written to `~/.local/share/nullius/shadow-paper/book.json` and every book to `…/shadow-paper/history/<book_id>.json`.

## Cadence and window
Same 14-day decision grid as v1 (anchor 2022-01-03). `nullius-shadow-paper.timer` fires at 09:50 UTC daily, after the 09:30 UTC lake refresh, and rebuilds the book from that run's sealed snapshot; between decision dates the hold rule keeps the book fixed, as for v1. The window is v1's: decision dates from **2026-10-19** (book built 2026-10-20) through **2027-01-18**, scored on daily data to 2027-01-18 12:05 UTC. Any book built before 2026-10-19 is a smoke test and is excluded.

## Primary outcome (decided now; v1's formula, unchanged)
**P (paper, research accounting).** For each day d in the window: r_d = Σ_i w_{i,d}·(fut_close_{i,d}/fut_close_{i,d−1} − 1) − Σ_i w_{i,d}·funding_rate_sum_{i,d} − 0.0005·Σ_i |w_{i,d} − w_{i,d−1}|, with w the book in force on day d from the paper history, closes and funding from the shadow lake, computed by `./run.sh shadow-eval --history ~/.local/share/nullius/shadow-paper/history` (no `--vst-db`).

**Pass** requires both: cumulative Σ r_d > 0, and the daily IR t-stat mean(r)/sd(r)·√n of at least 1.0. Otherwise **fail**. The bar is low and the power is small (about 90 days, 7 rebalances), exactly as for v1; this test guards against a clearly negative forward result and cannot establish a strong edge on its own.

**Execution validity.** A day with no book (the paper unit failed, the lake run failed) is recorded in an ADDENDUM and the window is extended by the lost days; it is never scored as a pass. There are no VST legs, so v1's placement clause does not apply.

## Secondary (reported, not decisive)
- P_paper − P_v1 over the same days: the attention construct against the funding construct, on identical data and accounting
- per-rebalance turnover and the fee term's share of P
- book beta (about 0 by construction) and the count of symbols dropped for having no BingX contract
- realised IC of the combined score against the forward 10-day fut_close return, by decision date

## What follows
- **Pass:** attention-volume is the construct the breadth pivot (`docs/research/2026-10-19-alpha-diagnosis.md`, "What to do") builds its first wide-universe campaign series on; a VST shadow of it is pre-registered separately before any capital question arises.
- **Fail:** the construct is recorded as not surviving forward at this cadence, and the breadth pivot proceeds without it.
- Either way, nothing here reopens dreaming (M3 is FAIL, final for its space).
