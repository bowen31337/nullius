---
id: J20-read-research-and-live-metrics
title: Read the research and live metrics behind the headline
persona: Operator
source: PRD §11 (primary + secondary metrics); architecture §16 research and live metrics; app_spec.xml features persisting sensitivity/specificity, Type-B depth, discoveries per 1000, train-vs-holdout gap, replay latency
status: fail
last_checked: run 7
evidence: screenshots/run-7/J2-J4-J5-J6-dashboard-populated.png, screenshots/run-7/J14-index-rendered.png, screenshots/run-7/J17-J20-entry-point-search.txt
---

# J20 — The metrics behind FDR_deploy

FDR_deploy is the headline (J02). PRD §11 and architecture §16 also name
the figures an operator needs in order to trust it and to judge the gate:

- sensitivity and specificity on planted nulls
- Type-B depth past the flip
- discoveries per 1,000 charged trials
- leave-one-family-out ΔIR
- the train-vs-holdout world gap
- regime coverage
- replay latency p50/p99
- canary drift

On the live side the same sections name the live-vs-backtest IC ratio,
realised vs. modelled fill cost, the order reject rate and WS staleness.
`app_spec.xml` persists these figures. This journey asks whether an
operator can **read** them anywhere.

Note on scope: `app_spec.xml` `<ui_layout>` limits the dashboard to
FDR_deploy, its provenance, the lamps and the epoch count, and defers "the
full operator console". Reading these metrics may therefore be deliberately
out of scope. A `fail` here is a scope question for the owner, not
automatically a bug.

## Preconditions

- The shipped dashboard and API over the demo store (as in J02/J08).

## Steps

1. On the dashboard, look for sensitivity/specificity, Type-B depth,
   discoveries per 1,000 trials and the train-vs-holdout gap.
   Expect: each one is visible, with its campaign and provenance.
2. On the API index (J14), look for routes that serve the same figures.
   Expect: a `metrics:read` route for each figure, or the dashboard view
   from step 1.
3. Look for the live metrics (IC ratio, fill-cost bps, reject rate).
   Expect: a recorded decision that they wait for M4/M5.

**Owner's decision (2026-10-06):** the research figures in steps 1–2 are
needed to judge the M3 gate. They get `metrics:read` routes and one
gate-evidence section on the dashboard **below** FDR_deploy, which stays the
only headline (architecture §16). The live metrics in step 3 are deferred to
M4/M5, because only the VST paper bot trades today. Step 3 therefore passes
on this recorded decision.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
