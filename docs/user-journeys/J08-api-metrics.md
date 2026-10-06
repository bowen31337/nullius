---
id: J08-api-metrics
title: Read the three observability metrics over HTTP
persona: Operator
source: api_endpoints_summary Observability; features 341-343
status: pass
last_checked: run 9
evidence: screenshots/run-9/J08-api-metrics.png
---

# J08 — Read the three observability metrics over HTTP

## Preconditions

- `python -m nullius_api` running against a store populated by `python -m nullius_api.demo`; a `metrics:read` token.

## Steps

1. `GET /metrics/fdr-deploy` with the token.
   Expect: `200` JSON: newest `fdr_deploy`, `campaign_id`, `computed_at` and the `history`.
2. `GET /metrics/instrument-status`.
   Expect: `200` JSON: `canary`, `ks_guard`, `ingest` (true/false, or null when absent) plus the readings.
3. `GET /metrics/regime-coverage`.
   Expect: `200` JSON `{stratum: count}`.
4. Repeat without a token.
   Expect: `401`.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
