---
id: J10-api-forward-test
title: Promote a signal to forward test and read its decay curve
persona: Researcher
source: api_endpoints_summary Forward Test; features 332-334
status: pass
last_checked: run 5
evidence: screenshots/run-5/J10-api-forward-test.png
---

# J10 — Promote a signal to forward test and read its decay curve

## Preconditions

- API running on the demo store (a pre-registered, decided node with observations); a `research` token.

## Steps

1. `POST /forward/promote` `{node_id, forward_days}`.
   Expect: `201`, or `200` retry for the already-open record; `409` for a conflicting open record.
2. `GET /forward/decay?node_id=<node>`.
   Expect: `200` with `points[{observed_on, days, live_ic}]`.
3. `GET /forward/decay?node_id=<unknown>`.
   Expect: `404` — distinguishable from a `503` store failure.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
