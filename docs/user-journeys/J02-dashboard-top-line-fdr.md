# J2 — Read the top-line FDR_deploy and its trend

**Actor:** Operator  
**Goal:** Read the newest campaign's base-rate-reweighted false discovery rate as the primary figure, and see how it moved across campaigns.  
**Source:** app_spec.xml features 341, 351; prd §4.1.3, §11

## Preconditions

- The metrics store holds FDR_deploy rows for three closed campaigns (demo seed: 0.9, ≈0.61, 0.5).

## Steps

1. Open the dashboard.

## Expected result

- The metric shows the **newest** campaign's figure (`50.0%`).
- The caption names that campaign and when it was computed.
- A trend chart shows every campaign's figure oldest → newest, and its axis says which campaign/when each point is (not a bare 0, 1, 2 index).

## Validation

Browser: seeded store, open the dashboard, assert the numeral and caption text, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
