# Pre-registration: dreaming on the valid pool, learning the commit rule, judged on a time-split (M3b)

- **Registered:** 2026-10-26 02:15:26 UTC, before any dreaming cycle on this space runs. `main` is at `33004532` (`49faf45a` the financial tree payload carries `theme_root`; `c4ea9c1d` the dreaming verdict takes its config and cost-model pins as flags).
- **Why reopen dreaming, and why this is a materially different space.** `2026-10-17-m3-dreaming.RESULT.md` was FAIL and final *for its space*: 103 financial worlds under the archive-m3 config at the shortest metrics horizon, nulls later found biased (its erratum), a jittered M3 incumbent that ranked by z-score, and a judgement on the whole archive out-of-sample window. Since then the engine has run 42 campaigns on the wide perpetual universe under valid nulls, the funded target and metrics at the configured horizon, and their RESULTs isolate one decision the fixed rule makes badly: it commits the most in-sample-fitted member of a family of near-identical constructs, and the out-of-sample book of that member is no better than its siblings'. That decision, which evaluated node to commit, is exactly what a `question.*` policy chooses in a financial world. This registration asks whether replay can learn a better commit rule than M2's, and it judges the answer on out-of-sample dates the selection never saw.
- **What this is not:** not a run of the M3 incumbent, not a change to how campaigns search, not a path to M4 or to capital. A pass earns the dreamed rule a place as the close-out variant the next series registers; nothing else.

## The space
- **Incumbent:** `deploy/dreaming/incumbent.m3b.py` (committed at `0b46318b`): the M2 fixed rule (bar 2.0 on `ic_insample`, the post-cost IR t) with two knobs the reviser can move, a `depth_penalty` (0.25 per refinement level, applied to the ranking value, not the eligibility) and a `ceiling` (4.0; readings above it tie, so the bar and the ceiling define the band the rule prefers). With `depth_penalty` 0 and an infinite ceiling it is M2 exactly. Admission: `policy_runtime.screen_policy` must adopt it; comparisons are against the schedule's values only.
- **Reviser:** the default jitter reviser (`dreaming.reviser`, band 0.1 on numeric literals), revision cap by the pool census (`FULL_DREAMING_CAP` 40 at 50+ worlds). No LLM reviser.
- **Pools.** Bootstrap arm: the 65 bootstrap worlds (hpo 45, featsel 10, symreg 10), 7/10 train split by `--iteration-id`. Financial arm: every completed non-VOID campaign whose grid ends before the first out-of-sample date of the selection config (clean-grid admission as implemented, about 114 worlds, of which 42 were run since 2026-10-19 under valid nulls; the earlier 72 are the perp-beta-neutral, M3 and narrow series whose nulls were biased, which affects which nodes exist in those trees, not the out-of-sample scoring of the real nodes a policy commits).
- **Selection config** `evaluation-config-dream-h5-iv-first.json` (sha256 `c6589d2aaf718579903d360c5a5bbbe8d2993d3f8f32ca0d4600c9922d55ccce`): the wide-h5 inverse-vol maker config with `oos_dates` cut to the **first 30** weekly dates, 2025-08-04 to 2026-02-23. Every candidate's financial score is its committed pick's cost-adjusted out-of-sample return under the inverse-vol book at the pick's own campaign horizon over those 30 dates.
- **Judgement config** `evaluation-config-dream-h5-iv-second.json` (sha256 `13b895318b28c5517f175ffbe49602e1fb3f36b32fe8163cda8864bfeb6ede00`): the same config with `oos_dates` cut to the **last 30** weekly dates, 2026-03-02 to 2026-09-21. The verdict reads the winner and the M2 baseline on these dates only. The two halves share no date; the selection half ends two weeks before the judgement half begins, so a 10-day hold from the last selection date settles before the first judgement date.

## Design
- **One cycle:** `./run.sh dream --incumbent deploy/dreaming/incumbent.m3b.py --iteration-id m3b-attempt-1 --beta 0.5 --reviser jitter --write-selected ~/.local/share/nullius/dream-logs/m3b-attempt-1.selected.py` under `NULLIUS_EVALUATION_CONFIG` = the selection config and `NULLIUS_COST_MODEL_PATH` = `binance_usdm.yaml`. The cycle selects the winner on the bootstrap train split exactly as the engine does; its financial arm scores every widened candidate and the M2 baseline on the selection half.
- **Verdict:** `python -m orchestrator.m3_verdict --iteration-id m3b-attempt-1 --prereg docs/preregistration/2026-10-24-m3b-dreaming-commit-rule.md --incumbent deploy/dreaming/incumbent.m3b.py --evaluation-config <judgement config> --pin-config-sha256 13b89531… --pin-cost-model-hash <binance_usdm hash>`: the M3 machinery unchanged in its criteria, on the judgement half.
- **Floors (as in M3):** at least 50 bootstrap worlds with 10 per domain, at least 20 financial worlds; otherwise the cycle is unscoreable and recorded as such.

## Primary outcome (decided now)
The M3 criteria, computed once on the judgement half:
- **C1:** the winner's mean paired financial score minus the M2 baseline's over the judged financial worlds is > 0.3 (the M3 delta, in the score's own units) with one-sided paired p < 0.05 and clearing the meta-level selection bar √(2 ln M)·σ/√n;
- **C2:** `FDR_deploy` at π₀ 0.9 strictly lower for the winner than for the baseline;
- **C3:** leave-one-family-out transfer mean over the three bootstrap domains > 0.
**Pass** iff all three hold. **Fail** otherwise. One cycle, one verdict; a FAIL is final for this space.

## Secondary (reported, not decisive)
- The winner's knob values against the incumbent's; how often the winner and the baseline commit the same node, a different node, or abstain, per world; the commit rate.
- The same C1 difference computed on the selection half (the in-sample analogue, expected larger).
- The winner's picks on the 42 valid-null campaigns re-scored as one portfolio on the judgement half under the inverse-vol config, beside the M2 picks' portfolio (context: the two sets share most members).

## What follows
- **Pass:** the dreamed rule becomes a `selection` variant at close-out (a feature through claw-forge, default off) and the next archive or forward series registers it.
- **Fail:** dreaming on the commit rule is closed; the lever left on the search side is root diversity (the agent's hypothesis space), which is not a replay question.

## Disclosures
- **Fourteenth look at the archive window, split.** The selection half's figures have been read as whole-window aggregates in the four RESULTs; the judgement half has never been read on its own, but it is half of a window whose whole has been read thirteen times. The forward paper book (shadow v2) is the clean test; this one is the cheap one.
- The 72 older financial worlds carry trees built under biased nulls; their real nodes' out-of-sample scores are unaffected, and their presence raises the world count the floors need. The 42 valid-null worlds are reported separately as a secondary.
- The jitter reviser explores ±10 % around the incumbent's literals, so the space of rules is small by design; a pass means the band of the rule matters, not that a new rule was discovered.
- Cost: compute only (replay of about 42 candidates over about 114 worlds with cached out-of-sample reads); no model calls.
