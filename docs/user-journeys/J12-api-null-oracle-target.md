# J12 — Ask the null oracle for a target series

**Actor:** Evaluator  
**Goal:** Obtain a node's target series plus an opaque budget directive, without learning whether the node is a planted null.  
**Source:** `<api_endpoints_summary>` Null Oracle; features 111-121; P2 information barrier

## Preconditions

- The API server is running with a sealed sidecar configured.

## Steps

1. `POST /target` for an unknown node.
2. `POST /target` for a known node on a deployment without the evaluator's aligned-series supply wired.

## Expected result

- Unknown node: `404` with detail, no payload.
- Known node, no series supply: `503` with a code word — **identical for null and real nodes** (a refusal that differed would be the branch oracle §7.2 forbids).
- No sidecar configured: `503` naming the missing configuration.

## Validation

Browser: drive the calls, render responses, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
