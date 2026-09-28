# J8 — Read the three observability metrics over HTTP

**Actor:** Operator  
**Goal:** Fetch the top-line figure, the instrument lamps and regime coverage as JSON, e.g. for alerting or a notebook.  
**Source:** `<api_endpoints_summary>` Observability; features 341, 342, 343

## Preconditions

- The API server is running against a seeded metrics store.

## Steps

1. `GET /metrics/fdr-deploy`
2. `GET /metrics/instrument-status`
3. `GET /metrics/regime-coverage`

## Expected result

- `200` JSON for each. FDR: newest `fdr_deploy`, `campaign_id`, `computed_at`, and the `history`.
- Instrument status: `canary`, `ks_guard`, `ingest` booleans (or `null` when absent) plus the readings.
- Regime coverage: `{stratum: count}`.
- An empty store answers `200` with nulls/empty — never a fabricated `0.0`. A broken store answers `503` with a code word.

## Validation

Browser: open each URL, read the JSON body, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
