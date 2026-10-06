---
id: J04-dashboard-instrument-lamps
title: See the three instrument lamps in permanent chrome
persona: Operator
source: app_spec.xml feature 342; ui_layout; M5 ux
status: pass
last_checked: run 7
evidence: screenshots/run-7/J2-J4-J5-J6-dashboard-populated.png, screenshots/run-7/J4-lamps-with-threshold.png
---

# J04 — See the three instrument lamps in permanent chrome

## Preconditions

- A store populated by `python -m nullius_api.demo` (canary healthy, a KS-guard reading, a feed-staleness reading).

## Steps

1. Open the dashboard.
   Expect: Three lamps — **canary**, **KS guard**, **ingest** — appear in the chrome above the epoch count.
2. Read each lamp.
   Expect: Each is lit (ok) or dark (failing) from its reading; a lamp with genuinely no reading says *no reading*.
3. Start without `NULLIUS_FEED_STALENESS_THRESHOLD_S` while a staleness reading exists.
   Expect: The ingest lamp names the missing threshold (unconfigured), not *no reading* — a reading exists.
4. Reload.
   Expect: The lamps render on every page load.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
