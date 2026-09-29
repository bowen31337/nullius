---
id: J13-api-risk-halt
title: Trigger the emergency halt
persona: Risk supervisor
source: api_endpoints_summary Risk; features 322-331
status: pass
last_checked: run 2
evidence: screenshots/run-2/J13-api-risk-halt.png, screenshots/run-2/J13-halt-no-engine.png
---

# J13 — Trigger the emergency halt

## Preconditions

- API running with `NULLIUS_EXECUTION_ENGINE=nullius_api.demo:PAPER_ENGINE`; a `risk` token.

## Steps

1. `POST /risk/halt`.
   Expect: `200`: the kill instruction (`changed: true`) and the flatten result.
2. Repeat it.
   Expect: `200`, `changed: false` — first-write-wins; the kill stands.
3. Start without an engine and halt.
   Expect: `503 execution_engine_unbound`.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
