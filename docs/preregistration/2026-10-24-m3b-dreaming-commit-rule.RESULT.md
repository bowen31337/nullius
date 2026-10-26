# RESULT: dreaming on the valid pool, learning the commit rule, judged on a time-split (M3b)

- **Registration:** `2026-10-24-m3b-dreaming-commit-rule.md`, committed `6fea95c4` at 2026-10-26 02:15:26 UTC (`.sha256` verified); Addendum 1 (`6af16467`) recorded the admission fix and the scale-free form of the incumbent before any cycle on it ran, and renamed the cycle `m3b-attempt-1b`.
- **Cycle:** `./run.sh dream --incumbent deploy/dreaming/incumbent.m3b.py --iteration-id m3b-attempt-1b --beta 0.5 --reviser jitter`, under the selection config `evaluation-config-dream-h5-iv-first.json` (sha256 `c6589d2a…cce`) and the `binance_usdm` cost model (hash `1e946e66…958a`), 2026-10-26 02:17 → 05:18 UTC, rc 0. 65 bootstrap worlds (hpo 45, featsel 10, symreg 10), 114 financial worlds admitted on the clean grid (13 excluded for overlap with the first out-of-sample date, 6 unknown), revision cap 40, 41 widened candidates, 1 885 replay rows.
- **Verdict:** `python -m orchestrator.m3_verdict --iteration-id m3b-attempt-1b --prereg … --incumbent deploy/dreaming/incumbent.m3b.py --evaluation-config evaluation-config-dream-h5-iv-second.json --pin-config-sha256 13b89531…e00 --pin-cost-model-hash 1e946e66…958a`, run 2026-10-26 07:58:53 UTC, exit 3. One row, prereg sha256 `ce7dac65…4948`.

## Verdict: **FAIL**

| Criterion | Registered test | Measured (judgement half, 2026-03-02 → 2026-09-21, 114 paired worlds) | Pass |
|---|---|---|---|
| C1 paired Δ, winner − `m2-incumbent`, misses at 0.0 | mean > 0.3, one-sided p < 0.05, mean > selection bar | mean **−0.000116**, one-sided p **0.957**, bar 0.000183 | no |
| C2 `FDR_deploy` at π₀ 0.9 | winner strictly lower | winner **0.954**, baseline 0.867 | no |
| C3 leave-one-family-out transfer | mean over the three domains > 0 | **+0.029** (hpo +0.086, featsel 0.0, symreg 0.0) | yes |

Commit rates on the financial worlds: winner 0.974, `m2-incumbent` 0.518. The winner commits on nearly every campaign; its extra commitments lose on the judgement half, and its deployed false-discovery rate is higher.

**Fail branch (registered):** dreaming on the commit rule is closed. The lever left on the search side is root diversity, which is not a replay question.

## What the cycle selected

The winner is `cand-385a435f980108013fd64fb7c0fda8dc` (code hash `385a435f…0e94`). Its knobs against the incumbent's, at β 0.5:

| Knob | Incumbent | Winner |
|---|---|---|
| `commit_z` | 1.000 | 0.901 |
| `depth_penalty` | 0.250 | 0.243 |
| `ceiling` | 2.500 | 2.629 |
| `min_observed` | 5 | 4.97 (same effect) |
| `frontier_cap` | 4 | 4 |

Bootstrap arm: holdout mean 0.681 (incumbent 0.585), train 0.648, gap −0.033, commit rate 0.85 (incumbent 0.75). The jitter moved every literal by under 10 %, as the registration said it would.

**On the financial worlds the winner and the unrevised incumbent commit the same node on all 114 campaigns**, on both halves. The dreamed revision changed nothing about which node is picked; every financial figure below is therefore a figure about the scale-free z-score family against the M2 fixed bar, not about dreaming's revision of it.

## Where the difference comes from (both halves)

Paired difference winner − `m2-incumbent`, misses at 0.0, by subset. Units are the evaluator's per-period post-cost return of the committed node's inverse-vol book (order 1e-4 = 1 bp per period).

| Subset | n | Selection half Δ (t) | Judgement half Δ (t) |
|---|---|---|---|
| All worlds | 114 | +0.000171 (1.97), p 0.049 | −0.000116 (−1.71) |
| Both commit the same node | 48 | 0 | 0 |
| Both commit, different nodes | 11 | +0.000083 (0.62) | +0.000198 (1.42) |
| M2 abstains, winner commits | 52 | +0.000356 (1.92) | −0.000295 (−2.09) |
| Both abstain | 3 | 0 | 0 |
| Valid-null campaigns (run since 2026-10-19, 30 admitted of 42) | 30 | +0.000080 (1.11) | +0.000094 (1.50) |
| Older campaigns (biased nulls) | 84 | +0.000203 (1.77) | −0.000190 (−2.17) |

The whole selection-half advantage was the 52 worlds where M2's bar of 2.0 abstains and the z-score rule commits: their committed picks averaged +3.6 bp per period on the first half and −3.0 bp on the second. The 11 worlds where the two rules commit different nodes favour the winner slightly on both halves but never significantly.

**The committed picks' first-half and second-half scores are negatively correlated (−0.41 over the winner's 111 picks).** Of the 65 picks positive on the selection half, 17 stayed positive on the judgement half; their judgement mean is −4.8 bp. This is the same fact the four M2 series recorded from the other side: the engine's picks carry a real in-sample ranking whose out-of-sample book return is dominated by the period, not by the pick. A commit rule learned on one half of the archive window cannot carry to the other half when the sign of the pick population flips between them.

## Secondaries registered

- **Knob values:** above. The winner's `commit_z` is lower (commits more), the ceiling higher; both move toward committing more often, which is the direction that paid on the selection half and lost on the judgement half.
- **Same / different / abstain per world:** same node 48, different node 11, winner-only commit 52, both abstain 3 (identical on both halves because the picks are identical on both halves: the rule reads in-sample figures only).
- **C1 on the selection half (the in-sample analogue):** +0.000171, p 0.049, winner commit 0.974 vs 0.518. As expected it is larger than the judgement figure; the sign flips.
- **The 42 valid-null campaigns as one portfolio:** 30 of the 42 are admitted on the clean grid (the other 12 have in-sample grids ending on or after 2025-08-04). On those 30 the winner's picks and M2's are the same node on 27 and the paired difference is +0.9 bp (t 1.5) on the judgement half; both arms are deeply negative there (winner −7.4 bp, M2 −8.4 bp per period), the alt-bear picture the h10-lowvol RESULT recorded. A separate `portfolio-oos` run was not made: 27 of the 30 picks are shared, so it would restate the series RESULTs' figures, which have been read.

## Deviations and disclosures

1. **The verdict reads rows, it does not score.** `m3_verdict`'s criterion 1 reads the `replay_score` rows filed under `financial_policy_version(module, <config sha>, <cost hash>)`; the dreaming cycle files its financial-arm rows only under the config the process holds (the selection config). A time-split judgement therefore needed the cycle's financial arm re-run under the judgement config before the verdict could pair anything. This was done with a driver (`m3b_judge_rows.py`, kept outside the repository) that rebuilds the 41 candidates exactly as the verdict rebuilds them (`m3_verdict._widened_candidates`, seeded by the iteration id over the committed incumbent source; the winner's module id and code hash were asserted equal to the cycle's), then calls the cycle's own `dream._financial_arm` with the process pointed at the judgement config and the same cost model and evaluator image. It wrote only `replay_score` rows under the judgement version strings (4 788 rows, 42 versions) and touched no selection row. Run 05:27 → 07:49 UTC. The verdict then ran exactly as registered. Nothing in the registered criteria or pins changed; a future time-split registration should name this step.
2. **Criterion 1's "> 0.3" clause cannot bind.** The score is the per-period post-cost return (order 1e-4), the same field the M3 RESULT recorded (its line on the scale of criterion 1). The registration copied the M3 clause knowingly ("the M3 delta, in the score's own units"). It did not decide this verdict: the difference is negative, its one-sided p is 0.957, and it lies below the selection bar; criterion 2 also fails on its own.
3. **The judgement half had been read as part of the whole window** (the fourteenth look, split, as registered). It had not been read on its own before the verdict. The driver's financial-arm summary (the winner's judgement figures) was read before the verdict command was run, in order to run it; nothing was changed between the two.
4. **Two refused verdict invocations** preceded the recorded one, both before any criterion was computed: the first for a missing `NULL_SIDECAR_PATH`, the second for a missing `NULL_SIDECAR_KEY_REF`; the verdict was then run under the campaign template (`op run --env-file=.env.campaign.tpl`) as `closeout` is. No verdict row was written by the refused calls (`_verify_no_prior_verdict` would otherwise have refused the third).
5. **The incumbent's first form** (absolute bar, M2 exactly) could not be selected on the bootstrap pool and was replaced by the scale-free form before any cycle completed (Addendum 1). The refused attempt `m3b-attempt-1` left cycle-cap, holdout and freeze rows and 45 zero-score rows in the store; none is read by this verdict (`--iteration-id m3b-attempt-1b`).
6. **Cost:** compute only, no model calls: the cycle 3 h 01 m, the judgement re-score 2 h 22 m, the verdict under a minute.

## What follows

- M3 (2026-10-17, FAIL) and M3b (this document, FAIL) close dreaming on the exploration policy and on the commit rule for this engine as it stands. Dreaming's levers do not reach the quantity that decides a book's forward return. No M3c is registered.
- The forward test that remains is shadow v2 (`2026-10-24-shadow-v2-multitheme.md`, paper-only, 2026-10-27 → 2027-01-25). The search-side lever that remains is root diversity, pre-registered when it is tried.
