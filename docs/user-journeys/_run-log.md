# Run log

Verdicts: `pass`, `fail` (failing step, expected vs observed), `blocked` (a real user cannot reach the journey). Seeding a store directly to reach a screen is a diagnostic, never a pass.

## Run 1 — 2026-09-28, baseline (`main` at `ffe915e`)

- **Browser:** headless Chromium 151, driven through browser-harness over CDP.
- **Dashboard:** `streamlit run packages/ops/src/ops/dashboard.py` with Streamlit 1.64, run under `uv run --with streamlit`.
- **Data:** a SQLite metrics store seeded by a scratch script (raw epoch-ledger inserts plus the members' public stores), so the populated-dashboard verdicts in this run are **diagnostics**, not passes: three FDR_deploy campaigns, three sealed epochs (one partly spent), regime coverage and one feed-staleness reading.

| # | Journey | Result | Evidence |
|---|---|---|---|
| J1 | Dashboard, fresh install | ✅ **Pass.** Shows `—` and *no campaign has closed…*, with no fabricated `0.0`. | [J1-dashboard-empty-db.png](screenshots/run-1/J1-dashboard-empty-db.png) |
| J2 | Top-line FDR_deploy + trend | ⚠️ **Partial.** Shows the newest figure `50.0%` and the campaign caption. The trend's x-axis is a bare `0, 1, 2` index with no campaign or date. | [J2-dashboard-populated.png](screenshots/run-1/J2-dashboard-populated.png) |
| J3 | Dashboard misconfigured | ❌ **Gap.** It refuses correctly (`DashboardRenderError`, with the repair named), but as a raw Python traceback with absolute filesystem paths and Streamlit's *Ask Google / Ask ChatGPT* buttons. | [J3-dashboard-no-database-url.png](screenshots/run-1/J3-dashboard-no-database-url.png) |
| J4 | Instrument lamps in chrome | ❌ **Gap.** No lamps are rendered. The chrome is only the epoch count, although `<ui_layout>` and the M5 `<ux>` line require three lamps. | [J2-dashboard-populated.png](screenshots/run-1/J2-dashboard-populated.png) |
| J5 | Remaining clean epochs | ✅ **Pass.** Shows `3` with one epoch partly spent, and `0` on an empty ledger, which is the documented behaviour. | [J2](screenshots/run-1/J2-dashboard-populated.png), [J1](screenshots/run-1/J1-dashboard-empty-db.png) |
| J6 | Provenance triple on panel | ❌ **Gap.** No triple is shown, although `<ui_layout>` and the M5 `<ux>` line require it. | [J2-dashboard-populated.png](screenshots/run-1/J2-dashboard-populated.png) |
| J7 | Dashboard exposure | ❌ **Gap.** The documented launch binds `*:8501` and prints a public *External URL*. The toolbar shows **Deploy**. No Streamlit config ships with the repo. | [J7-dashboard-default-launch.png](screenshots/run-1/J7-dashboard-default-launch.png) |
| J8 | Metrics over HTTP | ⛔ **Blocked.** Nothing serves HTTP: `ERR_CONNECTION_REFUSED`. | [api-metrics-fdr-deploy.png](screenshots/baseline/api-metrics-fdr-deploy.png) |
| J9 | Pre-register over HTTP | ⛔ **Blocked.** No HTTP server exists. Separately, the endpoint's errors can't be mapped to statuses: a criteria conflict raises the same `PromotionError` as a malformed body, and a missing node or epoch raises the same `PromotionStoreError` as an unreachable store. | same |
| J10 | Forward test over HTTP | ⛔ **Blocked.** No HTTP server exists. `/forward/decay` raises `ForwardStoreError` both for "no record / no observations yet" and for a broken store, so a `404` can't be told from a `503`. | same |
| J11 | Trial ledger over HTTP | ⛔ **Blocked.** No HTTP server exists. | same |
| J12 | Null-oracle target over HTTP | ⛔ **Blocked.** No HTTP server exists. The composed route refusing known nodes without a series supply is deliberate (see `build_target_route`), so the HTTP layer only needs to report it honestly. | same |
| J13 | Risk halt over HTTP | ⛔ **Blocked.** No HTTP server exists, and no way to bind an execution engine to the route from outside the process. | same |
| J14 | API discoverability | ⛔ **Blocked.** No HTTP server exists. | same |

### Root causes

1. **There is no HTTP transport at all.** All ten routes in `<api_endpoints_summary>` exist only as in-process endpoint objects with a `.get()`/`.post()` method and a `route` constant (`FdrDeployEndpoint`, `DebitEndpoint`, `HaltEndpoint`, …). No module imports an HTTP server, and nothing converts requests or responses to JSON. `run.sh app` is a leftover template from another project: it launches `uvicorn main:app`, and there is no `main.py`.
2. **The dashboard is missing two of its specified elements**: the instrument lamps and the provenance triple.
3. **The dashboard's refusal and deployment behaviour is Streamlit's default**: raw tracebacks, bound to every interface, with the Deploy button.
4. **Three endpoints' error classes don't say which HTTP status applies.** Pre-register and the forward decay curve are described above. Forward promote also raises `ForwardStoreError` for a missing node row.

These are specified for claw-forge in [`additions_spec_journeys.xml`](../../additions_spec_journeys.xml).

## Run 2 (dashboard half): 2026-09-28, after tasks 1-3 and 13-16 of `additions_spec_journeys.xml`

- **`main`:** `33c7bb0`.
- **Launch:** the dashboard was started from the repository root with no flags, so `.streamlit/config.toml` applies.
- **Data:** produced by the shipped seeder `python -m nullius_api.demo`, a real operator command rather than raw inserts.

| # | Journey | Verdict | Failing step, expected vs observed | Evidence |
|---|---|---|---|---|
| J1 | Fresh install | ✅ pass | — | [J1-dashboard-empty-db.png](screenshots/run-2/J1-dashboard-empty-db.png) |
| J2 | Top-line FDR_deploy + trend | ❌ fail | **Step 2.** Expected x labels that legibly say when each point is, with the year. Observed: the rotated labels are clipped to `-01-01T00:00…`, so the year is lost. | [J2-J4-J5-J6-dashboard-populated.png](screenshots/run-2/J2-J4-J5-J6-dashboard-populated.png) |
| J3 | Misconfigured | ✅ pass | Shows `dashboard_refusal: …` with the repair named, no traceback, no path, no third-party links. | [J3-dashboard-no-database-url.png](screenshots/run-2/J3-dashboard-no-database-url.png) |
| J4 | Instrument lamps | ❌ fail | **Step 3.** A feed-staleness reading exists (`ops_live_metrics`: `feed_staleness_s = 1.2`), but `NULLIUS_FEED_STALENESS_THRESHOLD_S` is unset. Expected the ingest lamp to name the missing threshold. Observed: `ingest: no reading`, which is the wrong fact and points the operator at the wrong repair. With the threshold set, it reads `ingest: ok`. | [populated](screenshots/run-2/J2-J4-J5-J6-dashboard-populated.png), [with threshold](screenshots/run-2/J4-lamps-with-threshold.png) |
| J5 | Clean epochs | ✅ pass | Shows `3` on the demo store and `0` on an empty one, as documented. | same as J2, J1 |
| J6 | Provenance triple | ✅ pass | Shows `provenance: evaluator 608a1ae37855…, snapshot 433368139601…, cost model 1cec44e2f806…`. | same as J2 |
| J7 | Exposure | ✅ pass | Binds `127.0.0.1:8501` only, no External URL, no Deploy button, no error details. | same as J2, J3 |

Note: on an empty store the canary lamp reads `ok`. That is by design: feature 342's canary lamp is never absent, and "no halt recorded" means healthy. It is not a finding.

## Run 3 (API discoverability): 2026-09-28, after feature 12 of `additions_spec_journeys.xml`

- **`main`:** `4496a19`.
- **Surface:** the two meta-routes `GET /` and `GET /healthz`, served by the transport directly from its resolved route table — not rows in the ten-route table, not adapter entries.

| # | Journey | Verdict | Failing step, expected vs observed | Evidence |
|---|---|---|---|---|
| J14 | API discoverability | ✅ pass | `GET /` answers an HTML index of every route, its verb and its configured/unconfigured state; `GET /healthz` answers `200` with no token; both are GET-only. Unit-tested in [`test_discoverability.py`](../../packages/api/tests/test_discoverability.py). | [packages/api/tests/test_discoverability.py](../../packages/api/tests/test_discoverability.py) |

Note: J14 step 1 opens `/` *with a token*, and step 4 (the token gate, feature 18) is not yet wired. The probe is already served token-free and the dispatch keys the future gate off `path == HEALTHZ_PATH`, so feature 18 gates `/` and the table routes without touching the probe.
