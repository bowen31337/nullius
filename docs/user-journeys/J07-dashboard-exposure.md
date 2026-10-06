---
id: J07-dashboard-exposure
title: Run the dashboard safely: local only, no third-party links
persona: Operator
source: architecture §2; security hygiene
status: pass
last_checked: run 8
evidence: screenshots/run-8/J2-J4-J5-J6-dashboard-populated.png, screenshots/run-8/J3-dashboard-no-database-url.png
---

# J07 — Run the dashboard safely: local only, no third-party links

## Preconditions

- Streamlit launched the documented way, from the repository root, with no extra flags.

## Steps

1. Check the listening socket.
   Expect: `127.0.0.1:8501` only; the launch log prints no *External URL*.
2. Look at the toolbar.
   Expect: No **Deploy** (publish to Streamlit Cloud) button.
3. Trigger a refusal (J3).
   Expect: No error details or third-party links reach the browser.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
