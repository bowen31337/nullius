# J10 — Promote a signal to forward test and read its decay curve

**Actor:** Researcher  
**Goal:** Start a promoted signal's forward window, then watch its live IC decay.  
**Source:** `<api_endpoints_summary>` Forward Test; features 332-334

## Preconditions

- A pre-registered, decided node; observations recorded after promotion.

## Steps

1. `POST /forward/promote` `{node_id, forward_days}`.
2. `GET /forward/decay?node_id=…`.

## Expected result

- Promote: `201` with `promoted_at`/`observed_on`; repeat → `200` retry; already-open conflict → `409`; not pre-registered/decided → `409`/`422`.
- Decay: `200` with `points[{observed_on, days, live_ic}]`; unknown node or no observations yet → `404`, distinguishable from a `503` store failure.

## Validation

Browser: drive both calls, render responses, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
