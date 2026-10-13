# Pre-registration: M2 with the guided theme roots v2 (the PRD §2.3 hypothesis-space pivot)

- **Registered:** 2026-10-13, before any campaign below runs. `main` at `bc0ed91`, which plants the v2 roots and renders their briefs (additions_spec_guided_themes.xml: 7555c12, bc0ed91, 7222900).
- **Why:** three pre-registered pivots failed by the same rule (cost-aware weekly, 2-weekly cadence, derivatives inputs). In the inputs test, the agent's own derivatives signals had a median IC t of −0.20. The binding constraint is the hypothesis space: open-ended slugs with no mechanism attached. The owner approved v2 on 2026-10-13 (`docs/hypothesis-space/themes-v2.md`, PRD §9.3 v2): nine roots, each with a mechanism, inputs, a pre-stated expected sign and notes, plus five shared construction rules.
- **Data reuse, disclosed:** this is the **fifth** look at the 2025-08 to 2026-09 OOS window. The themes were chosen from the published crypto-factor literature, not from this window's results; no v2 brief was tuned on it. The rule is fixed here, and every campaign is charged to the trial ledger. A pass is still to be read with this reuse in mind. The forward VST shadow (option D) is the uncontaminated check, and M3 itself is judged on financial holdout worlds.

## Design
- 10 Type-R campaigns, `--workspaces 32 --rounds 1 --width 1`, named `archG01`–`archG10`. Roots are planted round-robin over the nine v2 themes (3–4 roots per theme per campaign).
- Config `evaluation-config-archive-derivs.json`, unchanged from the inputs test:
  - snapshot `2026-10-12T03:50:56Z_75d0a1`
  - the 2-weekly grid: 92 in-sample dates, horizon 10, 30 OOS dates
  - 4 workers and a 400-day history cap
- Selection is post-cost (`ir_tstat`). The KS gate is null self-calibration. Neither has changed since the inputs test.

## Primary outcome (decided in advance; the same rule as all three earlier tests)
Over non-VOID campaigns, using the committed pick's cost-adjusted OOS IR (`oos_ir`), with a miss counted as 0:
- **Pass:** median `oos_ir` > 0 **and** at least 6 committed picks with `oos_ir` > 0.
- **Fail:** per §2.3 the method is falsified, not the mission. The next levers, in order:
  1. the perp instrument: trade the funding and basis effects as carry, which needs a cost model for perpetuals
  2. a pre-registered, time-boxed paid-data trial
  3. the forward VST shadow of the best v2 picks

## Secondary (reported, not decisive)
- post-cost discoveries per campaign, **per theme**
- for each theme, the median in-sample IC t of its roots, and the share whose sign matches the brief's `expected_sign`
- the committed picks' themes
- OOS IC t, turnover (against the brief's target of about 0.3), VOID rate and gate p-values, sensitivity and specificity
- spend
