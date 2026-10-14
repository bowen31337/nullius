# Addendum: M2 on research book v2 (operational deviations)

Recorded 2026-10-14, before any archP campaign committed a pick or produced an OOS figure. The primary rule, the hypothesis space, the book and the instrument are unchanged.

1. **Authoring input ceiling raised from 600k to 1.5M tokens, from archP02 on.** archP01 (c7694b12) stopped on `token_budget` after its 27 roots. It had used 640,502 input tokens against the 600k ceiling, so none of its 4 refinements were evaluated. That makes the registered `--rounds 3 --width 4` design roots-only. The v2 prompt (theme brief plus the book and instrument facts) is longer than the composite test's, and the prompt cache barely hit (21k read against 164k written). Output use was 113k of 300k, so that ceiling is unchanged. archP01 stays in the series as run: calibrated, 0 post-cost discoveries, no committed pick, so it counts as a miss (0) under the primary rule. archP02's first launch was stopped while authoring its roots, before any node was evaluated, and was relaunched under the new ceiling.
2. **The queue's spend cap was raised from $100 to $150**, so all ten campaigns can finish at the higher ceiling. The owner has pre-approved budgets.
3. **Commit 0ce48fe is part of `main` as registered.** It is the listing-cache performance fix: values are unchanged, and only the speed differs.

## Addendum 2: harness defect; archP01–03 set aside (2026-10-14)

Recorded before any campaign of this series committed a pick or produced an OOS figure.

4. **No refined child was ever evaluated in archP01 or archP02.** Every round-loop child raised, and `_continue_campaign` dropped it with no event and no log. There were two causes, both fixed on `main` before the series restarts:
   - **0b10262:** the pool-worker fix (POOL-1) set `PR_SET_PDEATHSIG`. That signal fires when the parent *thread* exits, and the pool's workers were spawned from a root-evaluation thread that ends with the root phase. So every worker was SIGTERMed after the roots, and each child raised `BrokenProcessPool`.
   - **70fe6ef:** the baseline policy re-selected parents it had already expanded. A parent has exactly one child, so this re-authored the same child id, and the tree refused it (`NodeMetricsConflictError`). This probably predates the series. archK05 landed only 6 of its 12 refinement slots. The composite RESULT's refined-node figures are therefore drawn from fewer nodes than the design allowed.
   - **f1b23e6:** a dropped child is now logged.
   - A refinement smoke (2 roots, 3 rounds, width 1, no close-out) evaluated a child at depths 1, 2 and 3, with nothing raised.
5. **archP01 (c7694b12), archP02 (c0105a64) and the stopped archP03 are set aside as harness-defective.** They ran roots-only, so they did not carry out the registered `--rounds 3 --width 4` design. Neither archP01 nor archP02 committed a pick (0 post-cost discoveries each), so neither produced an OOS figure, and setting them aside reveals nothing about the primary outcome. Their in-sample root figures are reported as secondary data.
6. **The registered series is now ten fresh campaigns, archP11–archP20,** on `main` at 70fe6ef. The design, ceilings (1.5M input / 300k output), themes, config, cost model and primary rule are otherwise unchanged. The spend cap for the ten is $150.
