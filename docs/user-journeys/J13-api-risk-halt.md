# J13 — Trigger the emergency halt

**Actor:** Risk supervisor  
**Goal:** Flatten open positions and stop new order submission, from outside the strategy process.  
**Source:** `<api_endpoints_summary>` Risk; features 322-331

## Preconditions

- The API server is running with an execution engine bound (demo: an in-memory paper engine with open orders/positions) and a `risk`-scoped token.

## Steps

1. `POST /risk/halt`.
2. Repeat it.

## Expected result

- `200` with the kill instruction (`changed: true` the first time) and the flatten result (cancelled orders, closed positions).
- Repeat: `200`, `changed: false` — the kill is first-write-wins and stands.
- No engine bound: `503` `execution_engine_unbound`, never a silent success.

## Validation

Browser: drive the call, render the response, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
