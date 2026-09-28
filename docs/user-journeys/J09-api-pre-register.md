# J9 — Pre-register promotion criteria before the deciding evaluation

**Actor:** Researcher  
**Goal:** Commit, and hash, the promotion criteria for a node before the evaluation that decides it.  
**Source:** `<api_endpoints_summary>` Promotion; features 290-293

## Preconditions

- The API server is running; the node and a sealed epoch exist.

## Steps

1. `POST /promotion/pre-register` with `{node_id, epoch_id, criteria}`.
2. Repeat the identical request.
3. Repeat with different criteria.

## Expected result

- First call: `201`, the record with its `criteria_hash` and `pre_registered_at`.
- Identical retry: `200`, the same record (idempotent).
- Different criteria: `409` conflict naming both hashes.
- Malformed body: `400`. Unknown node/epoch: `404`/`422`, not a store failure.

## Validation

Browser: drive `fetch()` from the API's own origin and render the responses, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
