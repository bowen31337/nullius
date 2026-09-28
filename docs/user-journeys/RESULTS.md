# Validation results

## Run 1 — 2026-09-28, baseline (`main` at `ffe915e`)

- **Browser:** headless Chromium 151, driven through browser-harness over CDP.
- **Dashboard:** `streamlit run packages/ops/src/ops/dashboard.py` with Streamlit 1.64, run under `uv run --with streamlit`.
- **Data:** a SQLite metrics store seeded through the members' public stores: three FDR_deploy campaigns, three sealed epochs (one partly spent), regime coverage and one feed-staleness reading.

| # | Journey | Result | Evidence |
|---|---|---|---|
| J1 | Dashboard, fresh install | ✅ **Pass.** Shows `—` and *no campaign has closed…*, with no fabricated `0.0`. | [J1-dashboard-empty-db.png](screenshots/run-1/J1-dashboard-empty-db.png) |
| J2 | Top-line FDR_deploy + trend | ⚠️ **Partial.** Shows the newest figure `50.0%` and the campaign caption. The trend's x-axis is a bare `0, 1, 2` index with no campaign or date. | [J2-dashboard-populated.png](screenshots/run-1/J2-dashboard-populated.png) |
| J3 | Dashboard misconfigured | ❌ **Gap.** It refuses correctly (`DashboardRenderError`, with the repair named), but as a raw Python traceback with absolute filesystem paths and Streamlit's *Ask Google / Ask ChatGPT* buttons. | [J3-dashboard-no-database-url.png](screenshots/run-1/J3-dashboard-no-database-url.png) |
| J4 | Instrument lamps in chrome | ❌ **Gap.** No lamps are rendered. The chrome is only the epoch count, although `<ui_layout>` and the M5 `<ux>` line require three lamps. | [J2-dashboard-populated.png](screenshots/run-1/J2-dashboard-populated.png) |
| J5 | Remaining clean epochs | ✅ **Pass.** Shows `3` with one epoch partly spent, and `0` on an empty ledger, which is the documented behaviour. | [J2](screenshots/run-1/J2-dashboard-populated.png), [J1](screenshots/run-1/J1-dashboard-empty-db.png) |
| J6 | Provenance triple on panel | ❌ **Gap.** No triple is shown, although `<ui_layout>` and the M5 `<ux>` line require it. | [J2-dashboard-populated.png](screenshots/run-1/J2-dashboard-populated.png) |
| J7 | Dashboard exposure | ❌ **Gap.** The documented launch binds `*:8501` and prints a public *External URL*. The toolbar shows **Deploy**. No Streamlit config ships with the repo. | [J7-dashboard-default-launch.png](screenshots/run-1/J7-dashboard-default-launch.png) |
| J8 | Metrics over HTTP | ❌ **Gap.** Nothing serves HTTP: `ERR_CONNECTION_REFUSED`. | [api-metrics-fdr-deploy.png](screenshots/baseline/api-metrics-fdr-deploy.png) |
| J9 | Pre-register over HTTP | ❌ **Gap.** No HTTP server exists. Separately, the endpoint's errors can't be mapped to statuses: a criteria conflict raises the same `PromotionError` as a malformed body, and a missing node or epoch raises the same `PromotionStoreError` as an unreachable store. | same |
| J10 | Forward test over HTTP | ❌ **Gap.** No HTTP server exists. `/forward/decay` raises `ForwardStoreError` both for "no record / no observations yet" and for a broken store, so a `404` can't be told from a `503`. | same |
| J11 | Trial ledger over HTTP | ❌ **Gap.** No HTTP server exists. | same |
| J12 | Null-oracle target over HTTP | ❌ **Gap.** No HTTP server exists. The composed route refusing known nodes without a series supply is deliberate (see `build_target_route`), so the HTTP layer only needs to report it honestly. | same |
| J13 | Risk halt over HTTP | ❌ **Gap.** No HTTP server exists, and no way to bind an execution engine to the route from outside the process. | same |
| J14 | API discoverability | ❌ **Gap.** No HTTP server exists. | same |

### Root causes

1. **There is no HTTP transport at all.** All ten routes in `<api_endpoints_summary>` exist only as in-process endpoint objects with a `.get()`/`.post()` method and a `route` constant (`FdrDeployEndpoint`, `DebitEndpoint`, `HaltEndpoint`, …). No module imports an HTTP server, and nothing converts requests or responses to JSON. `run.sh app` is a leftover template from another project: it launches `uvicorn main:app`, and there is no `main.py`.
2. **The dashboard is missing two of its specified elements**: the instrument lamps and the provenance triple.
3. **The dashboard's refusal and deployment behaviour is Streamlit's default**: raw tracebacks, bound to every interface, with the Deploy button.
4. **Three endpoints' error classes don't say which HTTP status applies.** Pre-register and the forward decay curve are described above. Forward promote also raises `ForwardStoreError` for a missing node row.

These are specified for claw-forge in [`additions_spec_journeys.xml`](../../additions_spec_journeys.xml).
