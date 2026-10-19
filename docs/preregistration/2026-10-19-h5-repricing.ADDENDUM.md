# Addendum 1 to the horizon-5 re-pricing pre-registration (preconditions, before any arm ran)

- **Filed:** 2026-10-19, about 03:35 UTC. No pick has been scored under any of the three configurations; the portfolio scorer (feature 6 of `additions_spec_engine_edge_recovery.xml`) had not yet merged. `2026-10-19-h5-repricing.md` and its pick list are unchanged, and their `.sha256` still verifies.
- **What it records:** the two preconditions the pre-registration names, both met, and one in-sample observation made by the check itself.

## Null validity on the wide snapshot, horizon 5, 183 weekly dates
`deploy/campaign/null_power_check.py` over 300 seeds against the live block-permuted target (snapshot `86b4c2`, grid of `evaluation-config-archive-m3.json`): the planted-null IC t-statistics of its three reference signals are

| signal | null t mean | null t sd | P(\|t\| > 1.96) |
|---|---|---|---|
| 20-day momentum | +0.11 | 1.01 | 0.047 |
| 5-day reversal | −0.03 | 1.02 | 0.067 |
| 20-day volatility | +0.02 | 1.04 | 0.077 |

N(0, 1) to within sampling error at 300 seeds (standard error of P about 0.013). The null is valid on this grid. The same run reports the **real** signals' in-sample IC t over the 183 dates on 239 names: momentum −3.72, **5-day reversal +4.24**, volatility −3.31. These are the check's fixed reference signals, not nodes, so no selection acts on them; they are in-sample facts and no part of any outcome here.

## Tripwire false positives
`deploy/campaign/tripwire_fp_check.py` on the same configuration: momentum passes every probe; 5-day reversal fails only the seed-jitter probe (perturbation 0.047); volatility fails the universe-subsample probe (0.895). These are the probes already recorded as advisory at discovery and gating only at promotion (`tripwire-time-shuffle-false-positives`); they do not bear on this test, which runs no tripwire.

## Evaluation canary after the engine changes
`nullius-canary.service` at 2026-10-19 03:25:48 UTC, the first scheduled run after features 1–5 merged (`66b7a98e`, `dac39c48`, `2d2f9c48`, `a5c5a7bf`, `388dd0af`): the re-evaluated node and the replayed incumbent both matched their frozen constants (deviation 0.0, `evaluation_canary: true`). The default evaluation path is unchanged to 1e-12.

## Store state
Migration 0120 applied; the campaign grid backfill filled 107 campaigns from their artifacts (36 at horizon 5 on the 183-date grid, 55 at horizon 10, 8 at horizon 1 to 2026-09-30, 8 at horizon 5 on the 235-date grid to 2026-06-29) and left 17 NULL (14 without IC series, 2 on an unmapped 180-date weekly grid, 1 without artifacts). The 28 picks are the `m2-fixed` commits on the 36 horizon-5 campaigns, as the rule states.

# Addendum 2 (a scorer refusal before the verdict; the rule is unchanged)

- **Filed:** 2026-10-19, about 05:00 UTC. Arm A has produced no score. Nothing in `2026-10-19-h5-repricing.md` changes.
- **What happened:** the four arms were launched concurrently at 04:03 UTC. Arms A (primary) and A-gross were **refused** by the evaluator on the first out-of-sample date: `the vol for 'FTTUSDT' on 2025-08-04 is not positive (0.0)`. FTTUSDT's archived perpetual price is frozen (delisted in place), so its 60-day realised volatility is 0 and the inverse-volatility book refuses to divide by it, exactly as feature 1 of `additions_spec_engine_edge_recovery.xml` specified. At least eight names in the wide universe are flat through the whole OOS window (BNXUSDT, DARUSDT, FTMUSDT, FTTUSDT, LINAUSDT, OCEANUSDT, OMGUSDT, RAYUSDT). Arm C (narrow universe, taker, z) completed and arm B (wide, taker, z) is still running; neither uses volatilities. Arm C's headline figure was seen while diagnosing the refusal; the primary rule was fixed before any arm ran and is not altered by it.
- **The defect and its fix:** a symbol whose window is flat is untradeable and belongs outside that date's cross-section, by the same missing-input rule that neutralises a symbol without a stream. The fix (filed through `claw-forge fix`) makes `compute_vols` emit no vol for a non-finite or non-positive volatility and makes `compute_node_metrics` drop a name with no vol from that date's inverse-volatility book, renormalising the rest to gross 1 and counting the drops per date; `book_weights` keeps refusing a non-positive vol when called directly. The z-weighted book (arms B and C, and every historical figure) is untouched: it keeps such names at a zero return, as it always has.
- **Then:** arms A and A-gross are rerun from scratch under their unchanged configs. The first complete run of arm A after this fix is the verdict.
