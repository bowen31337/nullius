# J1 — Open the dashboard on a fresh install

**Actor:** Operator  
**Goal:** See, on a system that has never closed a campaign, that no figure exists yet — rather than a made-up one.  
**Source:** app_spec.xml feature 351; `<ui_layout>`; docs §16 ("The top-line dashboard number is FDR_deploy, not Sharpe")

## Preconditions

- `DATABASE_URL` points at an empty SQLite metrics store.

## Steps

1. Start the dashboard.
2. Open it in a browser.

## Expected result

- Title **Nullius**, the chrome line `remaining clean epochs: 0`, the header `FDR_deploy at π₀ = 0.9`.
- The FDR_deploy metric shows **—** (never `0.0` or `0%`) with the caption *no campaign has closed, so no figure was measured*.
- No equity curve anywhere.

## Validation

Browser: open `http://127.0.0.1:8501/`, wait for the header, read `document.body.innerText`, full-page screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
