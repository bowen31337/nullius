# J5 — Watch the remaining clean-epoch count

**Actor:** Operator  
**Goal:** See the sequestered-epoch budget deplete long before it is exhausted.  
**Source:** app_spec.xml features 297, 352

## Preconditions

- A seeded epoch ledger: three sealed epochs, one having served 2 promotion decisions (still under budget).

## Steps

1. Open the dashboard.

## Expected result

- The chrome reads `remaining clean epochs: 3` (a clean epoch is one with `served < budget`).
- On an empty ledger it reads `0` — by design (`promotion/remaining.py`: an empty ledger is visible exhaustion, the gauge never raises).

## Validation

Browser: seeded store, read the chrome line, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
