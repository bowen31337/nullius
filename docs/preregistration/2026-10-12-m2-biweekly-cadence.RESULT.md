# Result: M2 at 2-weekly cadence

Pre-registration: `2026-10-12-m2-biweekly-cadence.md` (sha256 `10ab32afa382cc30644602f7f5a2170ccbff478134c526306c6cc679608a4133`). Scored 2026-10-12 by the pre-registered rule.

**Verdict: FAIL.** 10 campaigns (archB01–10), $23.05.

| Campaign | Verdict (null-calibration gate) | Gate A p | Gate B p | Post-cost discoveries | IC-rule discoveries | Committed pick OOS IR | OOS IC t |
|---|---|---|---|---|---|---|---|
| archB01 | ok | 0.52 | 0.16 | 0 | 4 | miss | – |
| archB02 | ok | 0.77 | 1.00 | 0 | 6 | miss | – |
| archB03 | ok | 0.15 | 0.16 | 0 | 4 | miss | – |
| archB04 | ok | 0.24 | 0.16 | 1 | 5 | +0.00130 | +0.69 |
| archB05 | ok | 0.85 | 1.00 | 0 | 4 | miss | – |
| archB06 | ok | 0.36 | 1.00 | 0 | 3 | miss | – |
| archB07 | ok | 0.11 | 0.16 | 1 | 4 | +0.00096 | +2.05 |
| archB08 | ok | 0.45 | 1.00 | 0 | 4 | miss | – |
| archB09 | ok | 0.92 | 0.16 | 0 | 9 | miss | – |
| archB10 | ok | 0.77 | 0.16 | 0 | 6 | miss | – |

Non-VOID: 10. Commits: 2, both positive. Median `oos_ir` with misses counted as 0: 0.0. The bar was median > 0 and at least 6 positive.

**Reading:**
- The null-calibration gate works: 0/10 VOID, where the old gate on the weekly batch voided 6/10.
- At 2-weekly cadence, the rare cost-surviving nodes held up out of sample: 2 of 2 positive, one at OOS IC t +2.05. That is too few to claim anything.
- The binding constraint is breadth: 8 of 10 campaigns found no cost-surviving node at all.
- Per §2.3, the next pivot is inputs: the free data streams (funding, perp–spot basis, intraday, order flow).

**Erratum (2026-10-20):** every in-sample and out-of-sample metric in this file is a horizon-1 (one-day-forward) figure, not the horizon-5 or horizon-10 figure its labels say; the engine scores the shortest aligned horizon regardless of the config (`2026-10-19-m2-wide-h5.ADDENDUM.md`, Addendum 2; `bug_spec_metrics_horizon.xml`). The numbers stand; the horizon labels do not.
