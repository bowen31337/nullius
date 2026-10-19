# Result: M2 on research book v2 (USD-M perpetuals, beta-neutral legs)

Pre-registration: `2026-10-14-m2-perp-beta-neutral.md` (sha256 verified unchanged), with its two addenda (`.ADDENDUM.md`):
- **Addendum 1:** the authoring input ceiling went from 600k to 1.5M tokens, and the spend cap from $100 to $150.
- **Addendum 2:** a harness defect meant no refined child was evaluated, so archP01–03 were set aside, and the series became archP11–20. It ran on `main` at 70fe6ef.

Scored 2026-10-15 by the pre-registered rule.

**Verdict: FAIL.**
- 10 campaigns (archP11–20), $54.77. None were VOID; every calibration was `ok`, with KS p from 0.22 to 0.95.
- Post-cost discoveries: 0 in nine campaigns, and 2 in archP19.
- One committed pick, from archP19: `00458616` (funding-crowding, depth 3, in-sample net IR t +2.10, IC t +2.19, turnover 0.29). Its OOS figures were **`oos_ir` −0.0007 and OOS IC t −2.34**, so the ranking reversed out of sample.
- Median `oos_ir`, with misses counted as 0, is 0.0, and 0 picks are positive. The rule needed a median above 0 and at least 6 positive picks.
- This was the seventh look at the 2025-08 to 2026-09 OOS window, as disclosed in the pre-registration. It spent one OOS evaluation, on archP19's pick.

Other spend: the set-aside archP01–03 cost $12.08, and four smoke campaigns cost $1.57. Total for this test: $68.42.

## Secondary (in-sample, evaluation dates only)
| Nodes | n | Median IC t | IC > 0 | IC t ≥ 2 | Median gross IR t | Max gross | Median net IR t | Max net | Median cost drag (IR t) | Median turnover |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 389 | +0.91 | 79% | 41 | +0.26 | +2.45 | −0.04 | +2.10 | 0.39 | 0.31 |
| roots (depth 0) | 270 | +0.60 | 73% | 29 | −0.14 | +1.99 | −0.36 | +1.47 | 0.37 | 0.31 |
| refined (depth 1–3) | 119 | +1.43 | 92% | 12 | +1.10 | +2.45 | +0.66 | +2.10 | 0.41 | 0.32 |

The table counts 389 of 390 nodes; one archP19 node failed with `disallowed_import`. "Gross" is before the turnover charge, but already net of funding carry. On the composite test's spot book (archK, the previous RESULT), the same rows were:
- roots: gross −0.42, net −1.19
- refined: gross +0.29, net −0.55
- cost drag 0.77, turnover 0.42

The correlation of IC t with gross IR t across nodes is 0.47, against 0.63 in archK.

**By depth** (median net IR t): depth 0 −0.36, depth 1 +0.59, depth 2 +0.58, depth 3 +0.85.

**By theme** (median net IR t, best node, n):

| Theme | n | Median IC t | Median net IR t | Best net IR t |
|---|---|---|---|---|
| funding-crowding | 108 | +1.52 | **+0.72** | **+2.10** |
| attention-volume | 53 | +2.02 | +0.18 | +0.90 |
| positioning-contrarian | 40 | −0.07 | +0.03 | +1.75 |
| low-volatility | 31 | +1.36 | −0.23 | +0.29 |
| intermediate-momentum | 31 | +0.91 | −0.44 | +0.43 |
| taker-flow-persistence | 30 | −1.24 | −0.98 | −0.47 |
| beta-to-btc | 31 | +0.44 | −1.23 | +0.91 |
| oi-price-divergence | 30 | +1.18 | −1.69 | −0.02 |
| basis-premium | 35 | +0.24 | −1.72 | +1.29 |

Not measured separately:
- the funding contribution by itself (gross includes it)
- each node's realised book beta (it is not persisted; the shadow CLI reports it)
- the number of symbols dropped for having no perpetual

## Reading
1. **Book v2 did what the diagnostic predicted.** Moving from the spot book to the beta-neutral perp book, median root net IR t rose from −1.19 to −0.36, and refined nodes rose from −0.55 to +0.66. The cost drag halved, from 0.77 to 0.39, because turnover fell from 0.42 to 0.31.
2. **Fixing refinement mattered as much as the book.** Each depth adds about 0.2–0.3 IR t. With the harness defect, archP01 and archP02 never evaluated a child, and the composite test was short of children too (Addendum 2).
3. **Funding-crowding is the one theme that is consistently positive after costs.** It is also the theme the perp book most naturally pays: shorting persistently high-funding coins collects the funding as carry. The policy put 28% of all nodes there.
4. **The bar was cleared once, and that pick did not generalise.** archP19's deepest funding-crowding refinement, which uses funding persistence plus OI intensity orthogonalised to the run-up, cleared net IR t 2 in-sample. Its OOS IC t was −2.34. With about 390 nodes and a seventh reuse of the window, a single in-sample pass is roughly what selection alone would produce. One pick is too few to say more.
5. **The OOS window is exhausted as evidence.** Seven looks at it, and every recent design choice informed by in-sample work, mean a further pass there would carry little weight.

## Next (author's decision, per the standing order and PRD §2.3)
1. **The forward VST shadow** (additions_spec_forward_shadow.xml and additions_spec_derivs_rest.xml, merged and verified end to end on 2026-10-15). The best in-sample candidates from this series trade on the BingX VST perp venue on fresh data. That is the one test the reused window cannot contaminate, and no capital is at risk. Its own pre-registration (nodes, horizon and criteria) is committed before its first book is traded.
2. A **paid-data trial**, pre-registered and time-boxed. It is deferred until the shadow is running.

**Erratum (2026-10-20):** every in-sample and out-of-sample metric in this file is a horizon-1 (one-day-forward) figure, not the horizon-5 or horizon-10 figure its labels say; the engine scores the shortest aligned horizon regardless of the config (`2026-10-19-m2-wide-h5.ADDENDUM.md`, Addendum 2; `bug_spec_metrics_horizon.xml`). The numbers stand; the horizon labels do not.
