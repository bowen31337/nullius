---
id: J09-api-pre-register
title: Pre-register promotion criteria before the deciding evaluation
persona: Researcher
source: api_endpoints_summary Promotion; features 290-293
status: pass
last_checked: run 7
evidence: screenshots/run-7/J09-api-pre-register.png
---

# J09 — Pre-register promotion criteria before the deciding evaluation

## Preconditions

- API running on the demo store; a `research` token.

## Steps

1. `POST /promotion/pre-register` for a node and epoch that exist.
   Expect: `201` with `criteria_hash` and `pre_registered_at` (or `200` retry if already registered identically).
2. Repeat the identical request.
   Expect: `200`, the same record.
3. Repeat with different criteria.
   Expect: `409` naming both hashes.
4. Send it for an unknown node.
   Expect: `422`, not a store failure.
5. Send a malformed body.
   Expect: `400`.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
