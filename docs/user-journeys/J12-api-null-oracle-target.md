---
id: J12-api-null-oracle-target
title: Ask the null oracle for a target series
persona: Evaluator
source: api_endpoints_summary Null Oracle; features 111-121; P2
status: pass
last_checked: run 5
evidence: screenshots/run-5/J12-api-null-oracle-target.png
---

# J12 — Ask the null oracle for a target series

## Preconditions

- API running with a sealed demo sidecar configured; an `evaluator` token.

## Steps

1. `POST /target` for an unknown node.
   Expect: `404` with detail, no payload.
2. `POST /target` for a known null node and a known real node (no series supply wired).
   Expect: Two `503` refusals, **byte-identical** apart from nothing the caller did not send.
3. Start without a sidecar and ask again.
   Expect: `503` naming the missing configuration.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
