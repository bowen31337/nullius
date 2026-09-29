---
id: J11-api-trial-ledger
title: Debit the trial ledger and read K-effective
persona: Evaluator
source: api_endpoints_summary Trial Ledger; features 84-95
status: pass
last_checked: run 3
evidence: screenshots/run-3/J11-api-trial-ledger-fresh-node.png
---

# J11 — Debit the trial ledger and read K-effective

## Preconditions

- API running on the demo store; an `evaluator` token.

## Steps

1. `POST /ledger/debit` with a full charge document.
   Expect: `201` with the appended `seq`.
2. Repeat it.
   Expect: `200` and the **same** `seq`.
3. Send an invalid outcome.
   Expect: `400`.
4. `GET /ledger/k-effective`.
   Expect: `200` with per-epoch counts and `total`.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
