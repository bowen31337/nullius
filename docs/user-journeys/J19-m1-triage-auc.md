---
id: J19-m1-triage-auc
title: Run the M1 one-day triage and read the perturbation-stability AUC
persona: Researcher
source: PRD §12 M1 ("gates the entire M2–M3 investment"), §15.1 unknown 1; architecture §11.2, §20
status: fail
last_checked: run 7
evidence: screenshots/run-7/J17-J20-entry-point-search.txt
---

# J19 — The M1 triage experiment

The PRD's cheapest decision: measure how well perturbation stability alone
separates planted nulls from real signals. An AUC near 0.85 means hard-code
the filter and delete the dreaming apparatus. An AUC near 0.6 means M3 is
worth building, and a §4.5 classifier becomes admissible. The researcher
must be able to run the triage and read the number.

## Preconditions

- A store holding a campaign with planted nulls and perturbation-stability
  scores (from J16), or the demo seeder's campaign.

## Steps

1. Look for the operator surface that runs the triage, in `run.sh`,
   `python -m` entry points, the API routes (J14's index) and the dashboard.
   Expect: one documented command or route.
2. Run it against a campaign.
   Expect: one AUC with its interval and the count of nulls and reals. The
   number comes from the scorer process that holds the sidecar key, and no
   per-node `is_null` label is printed (PRD §4.2).
3. Run it against a campaign with no planted nulls, or no stability scores.
   Expect: a refusal naming what is missing, never `AUC = 0.5`.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
