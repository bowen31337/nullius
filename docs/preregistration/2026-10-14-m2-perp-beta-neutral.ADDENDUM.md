# Addendum: M2 on research book v2 (operational deviations)

Recorded 2026-10-14, before any archP campaign committed a pick or produced an OOS figure. The primary rule, the hypothesis space, the book and the instrument are unchanged.

1. **Authoring input ceiling raised from 600k to 1.5M tokens, from archP02 on.** archP01 (c7694b12) stopped on `token_budget` after its 27 roots. It had used 640,502 input tokens against the 600k ceiling, so none of its 4 refinements were evaluated. That makes the registered `--rounds 3 --width 4` design roots-only. The v2 prompt (theme brief plus the book and instrument facts) is longer than the composite test's, and the prompt cache barely hit (21k read against 164k written). Output use was 113k of 300k, so that ceiling is unchanged. archP01 stays in the series as run: calibrated, 0 post-cost discoveries, no committed pick, so it counts as a miss (0) under the primary rule. archP02's first launch was stopped while authoring its roots, before any node was evaluated, and was relaunched under the new ceiling.
2. **The queue's spend cap was raised from $100 to $150**, so all ten campaigns can finish at the higher ceiling. The owner has pre-approved budgets.
3. **Commit 0ce48fe is part of `main` as registered.** It is the listing-cache performance fix: values are unchanged, and only the speed differs.
