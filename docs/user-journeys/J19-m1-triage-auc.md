---
id: J19-m1-triage-auc
title: Run the M1 one-day triage and read the perturbation-stability AUC
persona: Researcher
source: PRD §12 M1 ("gates the entire M2–M3 investment"), §15.1 unknown 1; architecture §11.2, §20
status: pass
last_checked: run 8
evidence: screenshots/run-8/J19-step1-triage-help.txt, screenshots/run-8/J19-step2-triage.txt, screenshots/run-8/J19-step3-triage-bad-count.txt
---

# J19 — The M1 triage experiment

The PRD's cheapest decision: measure how well perturbation stability alone
separates planted nulls from real signals. An AUC near 0.85 means hard-code
the filter and delete the dreaming apparatus. An AUC near 0.6 means M3 is
worth building, and a §4.5 classifier becomes admissible. The researcher
must be able to run the triage and read the number.

## Preconditions

- None. The triage (`python -m tripwires.triage`) builds its own synthetic
  planted panel from `--seed`/`--count`; it reads no store and makes no
  network call.

## Steps

1. Look for the operator surface that runs the triage, in `run.sh`,
   `python -m` entry points, the API routes (J14's index) and the dashboard.
   Expect: one documented command or route.
2. Run it.
   Expect: one AUC with its interval and the count of nulls and reals,
   measured over the member's own planted panel (a synthetic population
   sized by `--count`, not a stored campaign) — the triage reads no store
   and makes no network call, so there is no sidecar read and no per-node
   `is_null` label printed (PRD §4.2).
3. Run it with a bad seed, or a count below 2.
   Expect: a refusal naming what's wrong (`TripwirePanelError`), never
   `AUC = 0.5`.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
