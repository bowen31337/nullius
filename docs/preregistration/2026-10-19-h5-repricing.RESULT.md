# Result: re-pricing the horizon-5 committed picks (universe, fees, weights)

Pre-registration: `2026-10-19-h5-repricing.md` (sha256 verified unchanged, with its pick list), two addenda (`.ADDENDUM.md`): Addendum 1 recorded the preconditions (null validity on the wide horizon-5 grid, tripwire advisories, the post-change canary pass); Addendum 2 recorded that the inverse-volatility arms were refused on a frozen delisted perpetual (FTTUSDT, realised volatility 0.0), the fix (`0cf60fc1`: a name with no positive volatility drops out of that date's inverse-volatility book), and the rerun of arms A and A-gross from scratch.

Scored 2026-10-19 by the pre-registered rule. Arm A, the verdict run, ran 05:59–07:26 UTC from `main` at `0cf60fc1`; arms B and C ran 04:03 UTC from `388dd0af` (they use no volatilities and were unaffected by the fix); A-gross ran beside A.

**Verdict: FAIL.** Arm A's equal-weight portfolio of the 28 picks has a mean net return of **−3.15 bp per 5-day period** over the 60 out-of-sample weekly dates (sd 17.7 bp, t **−1.37**). The rule needed a mean above zero and t ≥ 2.0.

| Arm | Snapshot, names | Execution | Weighting | Net mean bp | per-date sd bp | t | N_eff | Cumulative, 60 dates |
|---|---|---|---|---|---|---|---|---|
| **A, primary** | wide `86b4c2`, 239 | maker 3.5 bp | inverse 60-day vol | **−3.15** | 17.7 | **−1.37** | 1.35 | −189 bp |
| A-gross (reported) | wide, 239 | zero fees | inverse vol | **+0.38** | 17.7 | +0.16 | 1.35 | +23 bp |
| B, control | wide, 239 | taker 5 bp | z | −5.33 | 44.9 | −0.92 | 1.35 | −320 bp |
| C, control | narrow `75d0a1`, 85 | taker 5 bp | z | −10.46 | 44.1 | −1.84 | 1.44 | −628 bp |

Per-date differences: A − B = +2.18 bp (t +0.57); B − C = +5.13 bp (t +1.01). Without the 2 picks whose root is a planted null (`95c0d64d`, `6aa2af74`): K = 26, −3.21 bp, t −1.31. By theme in arm A: cross-asset-divergence (22 picks) −3.8 bp, t −1.48; calendar-events (2) −2.1 bp; borrow-rate-conditioning (2) −0.4 bp; volatility-dispersion (1) −0.1 bp; order-flow-imbalance (1) +1.1 bp.

## What the arms say
1. **Breadth works on the ranking.** Moving the same 28 picks from 85 to 239 names (C → B) raises the median per-pick out-of-sample IC t from +0.45 to **+1.92** (27 of 28 picks positive in both wide arms) and improves the book by +5.1 bp per period. The arm-A portfolio's mean out-of-sample rank IC is +0.034 with **t +2.45** over 60 dates: the reversal construct ranks the cross-section at its own horizon, out of sample, significantly.
2. **The ranking does not become return.** At zero fees the inverse-volatility book earns +0.4 bp per period (t 0.16): nothing. Every basis point of arm A's loss is the 3.5 bp maker fee on turnover 0.66. Inverse-volatility weighting did what risk weights do, cutting per-date volatility 2.5× (45 → 18 bp) and the loss from −5.3 to −3.2 bp, but it did not create return either.
3. So the horizon-5 reversal construct, as these 28 nodes implement it, has a real, replicated, out-of-sample **rank** signal and **no monetisable spread** under either dollar-neutral book tried here: a long-short over all names weighted by score (z) or by score over volatility. A rank correlation of 0.03 can be carried by the middle of the distribution while the tails, where a proportional book concentrates its exposure, carry none or reverse. Which it is, and whether any construction (a tail-only book, rank weights, a different holding period) converts this IC into return, is a question about construction, not about the signal, and it is answerable in-sample before any new campaign.

## Consequences (as pre-registered)
- The horizon-5 reversal construct is recorded as **not surviving out of sample even at maker fees with risk weights on 239 names**. It gets no paper forward book and no priority in the wide-universe campaign series.
- The wide-universe campaign series (`M2-wide-h5`) may still be pre-registered on arm A's configuration. Before it is, the construction question above is answered in-sample (score-decile forward-return spreads for these picks), because a campaign that discovers rankings the book cannot monetise would fail for the reason this test just found, at a cost.
- One hypothesis charged to the trial ledger, as registered.
- Nothing here reopens dreaming.

## Disclosures
- **Ninth look at the 2025-08 to 2026-09 archive window.** The construct was chosen from the eighth. The forward paper track of the attention-volume construct (`2026-10-19-shadow-paper-attention.md`) is the uncontaminated test in flight.
- The picks were selected in-sample on snapshot `540e93` (spot, 100 names) at horizon 5 by the IC-t rule of their day; the arms change universe, instrument, fees and weights, never the code or the picks.
- The wide snapshot's `metrics` stream was partial at seal (89 of 239 names); no pick reads it.
- At least eight wide-universe perpetuals carry a frozen last price through the window (delisted in place: BNX, DAR, FTM, FTT, LINA, OCEAN, OMG, RAY). Arm A drops them from each date's book (Addendum 2); arms B and C keep them at a zero return, as every historical z-weighted figure did.
- The first launch of arms A and A-gross was refused and never scored; arm C's headline and arm B's were seen before arm A ran. The primary rule was fixed before any arm ran and was not changed.
- Compute only; no LLM call. Per-process cost on the wide snapshot: ~2 minutes to mount (after `8c66a862`), ~3.5 minutes per pick for 60 dates; a fix for the per-date file re-reads (1.39 M parquet reads per pick) was in a claw-forge worktree when this was scored and did not touch any arm.

**Erratum (2026-10-20):** every in-sample and out-of-sample metric in this file is a horizon-1 (one-day-forward) figure, not the horizon-5 or horizon-10 figure its labels say; the engine scores the shortest aligned horizon regardless of the config (`2026-10-19-m2-wide-h5.ADDENDUM.md`, Addendum 2; `bug_spec_metrics_horizon.xml`). The numbers stand; the horizon labels do not.
