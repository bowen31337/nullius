# J6 — See the provenance triple beside the top-line figure

**Actor:** Operator  
**Goal:** Know exactly which evaluator, data snapshot and cost model produced the figure on screen.  
**Source:** `<ui_layout>` ("The primary panel is FDR_deploy with its provenance triple"); M5 `<ux>` ("with its provenance triple visible"); features 99, 348

## Preconditions

- A seeded store whose newest campaign's nodes carry an `evaluator_hash`, `snapshot_hash` and `cost_model_hash`.

## Steps

1. Open the dashboard.

## Expected result

- The primary panel shows the newest campaign's `evaluator_hash`, `snapshot_hash` and `cost_model_hash` (short form, full on hover/expand).
- A campaign with no recorded triple says *provenance unrecorded*; one whose nodes disagree is refused as mixed provenance, never averaged.

## Validation

Browser: seeded store, read the panel, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
