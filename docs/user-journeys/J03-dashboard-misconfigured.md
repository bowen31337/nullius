# J3 — Start the dashboard with no metrics store configured

**Actor:** Operator  
**Goal:** Get told, plainly, that the dashboard cannot show a figure and what to fix — instead of a quiet default.  
**Source:** app_spec.xml feature 351 (`DashboardRenderError`); ops `degrade, don't break` stance

## Preconditions

- `DATABASE_URL` is unset.

## Steps

1. Start the dashboard.
2. Open it in a browser.

## Expected result

- The page **refuses** — no numeral is rendered.
- The refusal is presented as an operator-facing message: what is wrong, the code word, and the one repair (`point DATABASE_URL at the metrics store`).
- No Python traceback, no filesystem paths, and no buttons that send the error text to a third-party service ("Ask Google" / "Ask ChatGPT").

## Validation

Browser: start with `DATABASE_URL` unset, read the page text, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
