# Result: M2 re-measurement after cost-aware selection

Pre-registration: `2026-10-11-m2-cost-aware.md` (sha256 `7eac8bea216e2655b5032ea2d9cb39ed16a20402655bb3995dabfc96889778ae`). Scored 2026-10-12 by the pre-registered rule; nothing was re-scored.

**Verdict: FAIL.** 10 campaigns (archC01–10), $23.47.

| Campaign | Verdict | Post-cost discoveries | IC-rule discoveries | Committed pick OOS IR | OOS IC t |
|---|---|---|---|---|---|
| archC01 | ok | 1 | 12 | +0.00007 | −0.81 |
| archC02 | VOID | 0 | 8 | miss | – |
| archC03 | VOID | 0 | 9 | miss | – |
| archC04 | ok | 0 | 13 | miss | – |
| archC05 | ok | 1 | 11 | −0.00068 | −2.62 |
| archC06 | VOID | 0 | 12 | miss | – |
| archC07 | VOID | 0 | 14 | miss | – |
| archC08 | VOID | 0 | 12 | miss | – |
| archC09 | ok | 1 | 12 | −0.00070 | −1.63 |
| archC10 | VOID | 0 | 14 | miss | – |

Non-VOID: 4. Positive: 1 of 4. Median `oos_ir` with misses counted as 0: −0.00034. The bar was median > 0 and at least 6 positive.

**Reading:**
1. At weekly cadence, in this hypothesis space, almost no node survives costs (0–1 post-cost discoveries per campaign, against 8–14 by IC), and the survivors fail out of sample. §2.3's named next pivot is rebalance cadence.
2. The VOID rate rose from 0/25 to 6/10 with nulls unchanged (root IC sd 0.0098 → 0.0095) and real roots stronger (mean IC +0.020 → +0.030). The root-nonsig KS gate therefore penalises genuine weak edge. Fixed for future campaigns by `bug_spec_ks_null_calibration_gate.xml`: gate on null self-calibration (null t ~ N(0,1)) and on agent behaviour. VOID verdicts here stand.
