# J7 — Run the dashboard safely: local only, no third-party links

**Actor:** Operator  
**Goal:** Start the operator console without exposing it to the network or offering to publish it.  
**Source:** architecture §2 trust zones ("Research compute and trading compute are different systems"); security hygiene

## Preconditions

- Streamlit started the documented way from the repository root.

## Steps

1. Start the dashboard with no extra flags.
2. Check the listening address and the page chrome.

## Expected result

- It listens on `127.0.0.1` only — no `External URL`.
- The toolbar has no **Deploy** (publish to Streamlit Cloud) button.
- Error details are not shown to the browser; usage stats are not sent.

## Validation

Shell: `ss -ltn` for the bind address; Browser: page chrome text, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
