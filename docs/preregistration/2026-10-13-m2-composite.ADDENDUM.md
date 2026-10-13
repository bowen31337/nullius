# Addendum to `2026-10-13-m2-composite.md` (operational; made before any node was evaluated)

- **2026-10-13 12:30 UTC:** the first launch of archK01 (campaign `396fb0fa`, $2.14 charged to the trial ledger) stopped with `budget_exhausted`. The authoring role's per-campaign ceiling of 100k output tokens ran out after 22 of the 24 roots were authored. Composite signals are about 4.7k output tokens each, against under 3k for single-theme signals. **No node was evaluated**, so no score and no OOS figure was observed. The queue's scored-share stop halted the batch.
- **Change:** the per-campaign authoring ceilings in `authoring-config.json` go from 200k input / 100k output tokens to **600k / 300k**, and the queue's spend cap from $60 to $100. Models, effort and every element of the design and the rule are unchanged.
- The batch restarts as archK01–archK10. The aborted campaign is not one of the ten, and it is disclosed here and in the RESULT.
