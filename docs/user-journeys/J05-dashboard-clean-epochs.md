---
id: J05-dashboard-clean-epochs
title: Watch the remaining clean-epoch count
persona: Operator
source: app_spec.xml features 297, 352
status: pass
last_checked: run 3
evidence: screenshots/run-3/J2-J4-J5-J6-dashboard-populated.png, screenshots/run-3/J1-dashboard-empty-db.png
---

# J05 — Watch the remaining clean-epoch count

## Preconditions

- A store populated by `python -m nullius_api.demo` (three sealed epochs).

## Steps

1. Open the dashboard.
   Expect: The chrome reads `remaining clean epochs: 3` (clean = served < budget).
2. Open it on an empty store.
   Expect: It reads `0` — by design: an empty ledger is visible exhaustion (`promotion/remaining.py`); the gauge never raises.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
