---
id: J01-dashboard-first-run
title: Open the dashboard on a fresh install
persona: Operator
source: app_spec.xml feature 351; ui_layout; docs §16
status: pass
last_checked: run 3
evidence: screenshots/run-3/J1-dashboard-empty-db.png
---

# J01 — Open the dashboard on a fresh install

## Preconditions

- `DATABASE_URL` names an empty SQLite metrics store (no campaign has ever closed).
- Dashboard started from the repository root: `uv run --all-packages --with streamlit streamlit run packages/ops/src/ops/dashboard.py`.

## Steps

1. Open `http://127.0.0.1:8501/`.
   Expect: Title **Nullius**, three lamps and `remaining clean epochs: 0` in the chrome, header `FDR_deploy at π₀ = 0.9`.
2. Read the FDR_deploy metric.
   Expect: It shows **—** (never `0.0`/`0%`) with *no campaign has closed, so no figure was measured*; no equity curve anywhere.
3. Reload the page.
   Expect: The same absence page renders again (nothing was fabricated or cached).

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
