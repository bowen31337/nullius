# J4 — See the three instrument lamps in permanent chrome

**Actor:** Operator  
**Goal:** Know at a glance whether the numbers can be trusted: the determinism canary, the KS detectability guard and ingest lag, as three binary lamps.  
**Source:** app_spec.xml feature 342; `<ui_layout>` ("instrument status lamps and the remaining clean epoch count sit in permanent chrome"); M5 `<ux>` ("sees instrument status as three binary lamps")

## Preconditions

- A seeded metrics store: canary healthy, KS guard reading present, feed staleness recorded.

## Steps

1. Open the dashboard.

## Expected result

- Three lamps — **canary**, **KS guard**, **ingest** — are visible in the chrome on every render, each lit (ok) or dark (failing).
- A lamp with no reading is shown as *no reading*, never as lit.

## Validation

Browser: seeded store, read the chrome, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
