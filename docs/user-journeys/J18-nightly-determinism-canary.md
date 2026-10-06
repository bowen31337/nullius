---
id: J18-nightly-determinism-canary
title: The nightly determinism canary runs, and its lamp tells the truth
persona: Operator
source: architecture §1 P3, §12 "Canary", §15 "Replay non-determinism"; app_spec.xml key_interaction 5 "Determinism canary", ux "instrument status as three binary lamps"
status: pass
last_checked: run 8
evidence: screenshots/run-8/J18-step1-canary-help.txt, screenshots/run-8/J18-step1b-units.txt, screenshots/run-8/J1-dashboard-empty-db.png, screenshots/run-8/J18-step3a-run-before-freeze.txt, screenshots/run-8/J18-step3b-freeze.txt, screenshots/run-8/J18-step3c-freeze-again.txt, screenshots/run-8/J18-step3d-run.txt, screenshots/run-8/J18-step3e-lamp-after-run.txt, screenshots/run-8/J18-step4b-run-broken.txt, screenshots/run-8/J18-step4c-lamp-after-break.txt
---

# J18 — The nightly determinism canary

Architecture §12: "Nightly: replay a frozen policy over a frozen tree and
assert the score matches a recorded constant to 1e-12 … Non-determinism
does not announce itself." The operator schedules the canary once, then
relies on the dashboard's canary lamp (J04) to report its outcome. A lamp
that reads green when the canary has never run is worse than no lamp.

## Preconditions

- The shipped dashboard (as in J01/J04) over a store where no canary has
  ever run, and the repository's `deploy/` units.

## Steps

1. Look for the scheduled canary in `deploy/systemd/`, `run.sh` verbs and
   `python -m` entry points.
   Expect: a nightly unit or timer, or a documented command, that replays
   `π_canary` over `T_canary`.
2. Open the dashboard on a fresh install (J01's store) and read the canary
   lamp.
   Expect: the lamp does **not** claim `replay is deterministic`. Like the KS
   lamp, it reads `no reading` (or equivalent) until a canary has run.
3. Run the canary once by hand.
   Expect: the score is recorded against the constant, and the lamp reads
   `ok`, together with when the canary last ran.
4. *(diagnostic)* Record a canary break.
   Expect: the lamp reads as halted, and the dreaming cycle (J17) refuses to
   run.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
