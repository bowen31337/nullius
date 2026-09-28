---
id: J06-dashboard-provenance
title: See the provenance triple beside the top-line figure
persona: Operator
source: ui_layout; M5 ux; features 99, 348
status: pass
last_checked: run 2
evidence: screenshots/run-2/J2-J4-J5-J6-dashboard-populated.png
---

# J06 — See the provenance triple beside the top-line figure

## Preconditions

- A store populated by `python -m nullius_api.demo` (the newest campaign's node carries the triple).

## Steps

1. Open the dashboard.
   Expect: Under the figure: `provenance: evaluator …, snapshot …, cost model …` for the newest campaign.
2. Compare against the store.
   Expect: The three short hashes are prefixes of that campaign's node `evaluator_hash`, `snapshot_hash`, `cost_model_hash`.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
