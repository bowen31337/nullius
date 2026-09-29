---
id: J02-dashboard-top-line-fdr
title: Read the top-line FDR_deploy and its trend
persona: Operator
source: app_spec.xml features 341, 351; prd §4.1.3, §11
status: pass
last_checked: run 4
evidence: screenshots/run-4/J2-J4-J5-J6-dashboard-populated.png
---

# J02 — Read the top-line FDR_deploy and its trend

## Preconditions

- A metrics store populated by the shipped seeder `python -m nullius_api.demo` (three closed campaigns).

## Steps

1. Open the dashboard.
   Expect: The metric shows the **newest** campaign's figure (`50.0%`) and the caption names that campaign and when it was computed.
2. Read the trend chart.
   Expect: Every campaign's figure is plotted oldest → newest, the y-axis is labelled FDR_deploy, and each x label legibly says when (date including the year), not a bare 0, 1, 2 index.
3. Reload the page.
   Expect: The same figure and trend render again.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
