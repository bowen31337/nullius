---
id: J03-dashboard-misconfigured
title: Start the dashboard with no metrics store configured
persona: Operator
source: app_spec.xml feature 351 (DashboardRenderError)
status: pass
last_checked: run 4
evidence: screenshots/run-4/J3-dashboard-no-database-url.png
---

# J03 — Start the dashboard with no metrics store configured

## Preconditions

- `DATABASE_URL` is unset.

## Steps

1. Start the dashboard and open it.
   Expect: The page **refuses**: no numeral is rendered.
2. Read the refusal.
   Expect: One operator-facing message with the code word and the one repair (`point DATABASE_URL at the metrics store`).
3. Look for leaks.
   Expect: No Python traceback, no filesystem paths, no "Ask Google" / "Ask ChatGPT" buttons.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
