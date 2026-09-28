# J11 — Debit the trial ledger and read K-effective

**Actor:** Evaluator  
**Goal:** Record every evaluation as an irreversible, idempotent charge; read the honest trial count per epoch.  
**Source:** `<api_endpoints_summary>` Trial Ledger; features 84-95

## Preconditions

- The API server is running.

## Steps

1. `POST /ledger/debit` with the full charge document.
2. Repeat it.
3. `GET /ledger/k-effective`.

## Expected result

- Debit: `201` with the appended `seq`; the retry returns `200` and the **same** `seq`.
- K-effective: `200` with per-epoch counts and `total`; empty ledger → empty counts, total 0.
- Invalid charge (bad outcome, non-hex hash, naive timestamp): `400`.

## Validation

Browser: drive the calls, render responses, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
