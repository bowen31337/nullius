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

## Implementation note (not a browser run): the bearer-token gate, feature 18, 2026-09-29

- **Branch:** `feat/http-api-transp-system-requires-a-bearer-token-o-08d2ad`.
- **Checker:** `packages/api/tests/test_auth.py` (the token file's contract)
  and `packages/api/tests/test_token_gate.py` (the two refusals over the
  wire), 94 cases, run with the whole api member suite.
- **Token file:** a JSON object mapping each scope to the tokens carrying
  it — `{"metrics:read": ["…"], "research": ["…"], "evaluator": ["…"],
  "risk": ["…"]}` — named by `NULLIUS_API_TOKENS_FILE`.

The J14 steps that feature 18 covers are pinned as tests rather than
browser runs: `GET /healthz` answers 200 with no token and 405 for a
wrong verb; every other path — the index and unknown paths included —
answers 401 without one; an unknown token answers 401; a token outside
the route's scope answers 403; and a server started with no token file
configured exits 2 with one plain sentence and no traceback. Every one
of the ten routes is swept against its own scope and against the other
three, so a row that accepted a scope it should not cannot hide behind
a hand-picked pair.

Feature 18's two consequences are worth an operator knowing, because
both are deliberate. An unauthenticated caller cannot map the surface:
`GET /no-such-route` answers 401 like any other path, so the 404s do
not enumerate the routes. And a wrong-scoped caller cannot learn
whether a store is configured: the 403 precedes the unconfigured-
component check, so this deployment's `metrics:read` token gets the same
403 from `POST /risk/halt` whether or not `DATABASE_URL` is set.

J14's steps 1 and 3 (the index's content, the 404/405 statuses) remain
browser journeys and are not claimed by this run.

**Suites:** the api member suite is 388 passed (14:17), the root suite
1579 passed (10:23), both with `-p no:randomly`. `ruff check` is clean
over the member's `src`, its `tests` and `src/app/modules/api`.

## Implementation note (not a browser run): HTTPS on a non-loopback bind, feature 21, 2026-09-29

- **Branch:** `feat/http-api-transp-system-refuses-to-bind-a-non-loo-d9228d`.
- **Checker:** `packages/api/tests/test_tls.py`, 48 cases, run with the
  whole api member suite.
- **Certificate:** a self-signed PEM pair the suite *generates* through the
  `cryptography` package the *nulloracle* member already brings into the
  workspace — never a new dependency of the api member, and never a
  checked-in file that could be mistaken for a deployment secret. The
  client in these tests verifies the server against that exact
  certificate, so *serves HTTPS* is proven by a handshake that would fail
  against any other one.

J14's steps 5 and 6 (the refusal and the upgrade) are pinned as tests
rather than browser runs. What the cases establish:

- **The classification is fail-closed.** `127.0.0.1`, `127.0.0.2`, `::1`,
  `[::1]`, `localhost` (any case, trailing dot, surrounding whitespace)
  and glibc's `ip6-*` aliases are loopback; `0.0.0.0`, `::`, a private
  literal and a DNS name — *including* one that resolves to 127.0.0.1 on
  this machine — are not. Nothing is resolved: no startup waits on a
  resolver, and the safety of a bind does not depend on a record somebody
  else controls.
- **The loopback default is untouched.** `127.0.0.1` resolves to a
  disabled posture, reads neither variable, and the server hands back the
  very socket it was given — feature 4's cleartext server, bit for bit.
  A loopback bind that *was* given a pair stays cleartext rather than
  being silently upgraded.
- **The refusal names the file.** Unset, empty, half-configured, a path
  that does not exist, a directory, a file that is not PEM, and a key
  that does not match its certificate all refuse by name, with exit
  status 2 through the real `python -m nullius_api` as a subprocess, one
  plain sentence on standard error and no traceback. The posture is
  resolved *before* `super().__init__` binds, so a refused bind leaves no
  socket behind — pinned by counting the process's file descriptors. The
  sentence also agrees with what was in fact configured: both variables
  unset reads "`NULLIUS_API_TLS_CERT` and `NULLIUS_API_TLS_KEY` name no
  certificate and key", one of them set reads "`NULLIUS_API_TLS_CERT`
  names no certificate" and names the half that *was* given beside it,
  so the operator is never sent to look at a file they already set.
- **HTTPS is the ssl module.** With the pair configured, `--host 0.0.0.0`
  serves a real TLS handshake that the same test's verifying client
  completes; a cleartext `http://` request to that port gets no answer at
  all; the token gate answers 401 inside the tunnel exactly as outside.

One deliberate change to the operator's console: a *failed* handshake is
logged as one line rather than the base class's traceback, and there are
two shapes of it. A cleartext probe fails during `accept`, where the base
class's loop swallowed the `ssl.SSLError` entirely — without a line the
event left no trace at all. A TLS 1.3 client that does not trust this
certificate only says so *after* completing its handshake, so its abort
arrives while the handler is reading the request line and the base class
would print a stack naming this module and a thread for a fault entirely
the caller's. That second shape was found by re-running the suite, not by
reading it: it reproduced roughly one run in three. Every other fault
keeps the base class's own reporting.

**Suites:** the api member suite is 433 passed (14:18), the root suite
1579 passed (10:25), both with `-p no:randomly`. `ruff check` reports
only the two findings `__init__.py` and `__main__.py` already carried
before this feature (`RUF022` on the deliberately grouped `__all__` and
`RUF059` on the now-unused host unpack); the files this feature adds and
the other lines it touches are clean.

## Implementation note (not a browser run): the structured access log, feature 20, 2026-09-29

- **Branch:** `feat/http-api-transp-system-emits-one-structured-acce-9ebfcc`.
- **Checker:** `packages/api/tests/test_access_log.py`, 40 cases, run
  with the whole api member suite.
- **Logger:** `nullius_api.access`, at INFO — dotted under `nullius_api`
  so a deployment's one handler on the parent captures the access stream
  and the server's own startup and fault lines together, one knob.

The constraint this feature carries (*tokens and request bodies are
never written to a log*) is pinned as tests rather than a browser run.
What the cases establish:

- **One record per request, whatever the outcome.** The emission sits in
  `handle_one_request`'s `finally`, so an adapter's success, every
  refusal (401, 403, 404, 405, 413), a 501 for an unsupported verb, a
  414 for a request line over 64 KiB, the belt's own 500 and a socket
  that broke before any response was written are each exactly one
  record — and a connection that closes without sending a request line
  emits none, because that is a caller leaving, not an ask.
- **The five fields ride the record as attributes.** `scope`, `verb`,
  `route`, `status` and `latency_ms` are passed as `extra`, so a
  structured formatter reads them without parsing anything — `status` is
  an `int`, so a pipeline's `status >= 500` is a comparison rather than
  a substring match. The message is the derived `key=value` line, and
  the base class's own unstructured line is *retired* rather than
  doubled: still one line per request, now the structured one.
- **The two absences are spelled `None`.** A request that presented no
  credential this deployment accepted — `GET /healthz`, which needs
  none, and every 401 — carries `scope=None`; a request no response
  reached carries `status=None`. Never `""`, never a fabricated `0` or
  `200`: an operator counting the log by scope can tell *nobody
  identified themselves* from *somebody identified themselves as ""*.
- **The latency is the request's, not the connection's.** The clock
  starts when the request line arrives (`parse_request` refines a coarse
  fallback whose only survivor is the 414 the framer refuses before
  parsing), so a caller that opens a connection and idles half a second
  before sending does not inflate the record; `latency_ms` is bounded
  above by loopback reality in the cases, and a negative, NaN or
  infinite interval is refused by the record's own construction — before
  the logger is asked, so a refused ask puts nothing on the stream.
- **`route` is the path, not the query.** A query string is
  caller-authored text and is dropped — feature 9's `?node_id=` traffic
  is the shape this is pinned against.
- **Both prohibitions are tested the hard way.** The suite's real tokens
  are presented in real headers on every branch that reads one —
  admitted, wrong scope, unknown — and the *entire* stream, every
  message **and** every structured field, is searched for each
  credential, for the `Bearer` scheme and for a canary planted in a
  body. The canary case is load-bearing: the adapter is swapped for one
  that *keeps* what it was handed, so the prohibition is proven over a
  dispatch the body provably travelled (read, parsed, delivered), not
  over one that refused it unread.


## Run 2 (API half): 2026-09-29, after tasks 4-12 and 17-21 of `additions_spec_journeys.xml`

- **Server:** `python -m nullius_api` on `127.0.0.1:8765` (`main` at `2b6e407`).
- **Data and configuration:** a store from the shipped seeder `python -m nullius_api.demo`; a `NULLIUS_API_TOKENS_FILE` with one token per scope; `NULLIUS_EXECUTION_ENGINE=nullius_api.demo:PAPER_ENGINE`.
- **J12:** an operator-sealed null sidecar (`NULL_SIDECAR_PATH` and `NULL_SIDECAR_KEY_REF=hex:…`, written through `NullSidecar.write`) with one null node and one real node.
- **Browser:** each call is driven with `fetch()` from the API's own origin in headless Chromium via browser-harness ([`validate_api_journeys.py`](validate_api_journeys.py)). No response body contained a traceback or a filesystem path.

| # | Journey | Verdict | Failing step, expected vs observed | Evidence |
|---|---|---|---|---|
| J8 | Metrics over HTTP | ❌ fail | **Step 1.** Expected the newest `fdr_deploy`, `campaign_id` and `computed_at` beside the `history`. Observed only `{"history": [[id, value, ts], …]}`. **Step 3.** Expected `{stratum: count}`. Observed `{"strata": [["crash", 0], …]}`, a list of pairs. Steps 2 and 4 pass (lamps JSON; `401` without a token). | [J08-api-metrics.png](screenshots/run-2/J08-api-metrics.png) |
| J9 | Pre-register | ✅ pass | The seeded node was already registered identically, so step 1 took its documented `200`-retry branch. Then `200` retry, `409 promotion_criteria_conflict`, `422 promotion_parent_absent` and `400 malformed_body`. | [J09-api-pre-register.png](screenshots/run-2/J09-api-pre-register.png) |
| J10 | Forward test | ✅ pass (with a filed defect) | Promote gives `200` (the seeded record was already open), the decay curve gives `200` with points, and an unknown node gives `404 forward_record_absent`. **Defect:** that `404`'s message reads `forward_record_absent: forward_record_unwritable: …`, which tells the caller the store is unwritable when the record simply does not exist. | [J10-api-forward-test.png](screenshots/run-2/J10-api-forward-test.png) |
| J11 | Trial ledger | ❌ fail | **Step 4.** Expected per-epoch counts and a `total`. Observed `{"view": {"counts": [[epoch, n], …]}}` with no `total`. Steps 1-3 pass on a fresh node: `201` with `appended: true` and `seq 3`, then `200` with the same `seq 3`, then `400`. (The first attempt reused the seeded node, and the ledger is idempotent per node, so it returned that node's `seq 1`.) | [J11-api-trial-ledger-fresh-node.png](screenshots/run-2/J11-api-trial-ledger-fresh-node.png) |
| J12 | Null-oracle target | ✅ pass | An unknown node gives `404 unknown_node`. A sealed null node and a sealed real node both give `503` with identical headers (excluding Date), and their bodies differ only in the node id the caller sent. Without a sidecar the route gives `503 component_unconfigured`. | [with sidecar](screenshots/run-2/J12-api-null-oracle-target-sidecar.png), [without sidecar](screenshots/run-2/J12-api-null-oracle-target.png) |
| J13 | Risk halt | ✅ pass | `200` with `changed: true`, then `200` with `changed: false` (first write wins). With no engine bound: `503 execution_engine_unbound`. | [J13-api-risk-halt.png](screenshots/run-2/J13-api-risk-halt.png), [no engine](screenshots/run-2/J13-halt-no-engine.png) |
| J14 | Discoverability | ✅ pass | With a token, `GET /` renders the index: 10 routes, all configured. Also observed: `/healthz` gives `200` without a token, an unknown path `404`, a wrong verb `405` with `Allow: POST`, and `401`, `401`, `403` for no token, an unknown token and a wrong scope. | [J14-api-discoverability.png](screenshots/run-2/J14-api-discoverability.png), [rendered index](screenshots/run-2/J14-index-rendered.png) |

**Open decision (not filed):** the HTML index at `/` is aimed at browsers, but it requires a bearer token, and a browser cannot send one by navigating to the URL. A person who types the URL gets `401` ([screenshot](screenshots/run-2/J14-index-plain-navigation-401.png)). The auth feature gated it on purpose, because the index reveals which components are configured. Whether `/` should be public, perhaps with the configured column hidden, is a product decision for the owner.

**Also seen:** the shipped demo seeder seals no null sidecar, so J12 needed operator configuration by hand to exercise the barrier.

## Run 3 (full sweep): 2026-09-29, after the five fixes of `bug_spec_journeys_run2.xml`

- **`main`:** `901b996` plus lint fix `f8f2aec`.
- **Setup:** every precondition came from shipped commands. The store came from `python -m nullius_api.demo`, and the sidecar came from the `export NULL_SIDECAR_…` lines that the seeder now prints. Tokens came from `NULLIUS_API_TOKENS_FILE`, the paper engine from `NULLIUS_EXECUTION_ENGINE`, and the dashboard was launched from the repository root, so `.streamlit/config.toml` applied.

| # | Journey | Verdict | Notes | Evidence |
|---|---|---|---|---|
| J1 | Fresh install | ✅ pass | Shows `—` and *no campaign has closed…*. The KS-guard and ingest lamps read `no reading`. | [J1](screenshots/run-3/J1-dashboard-empty-db.png) |
| J2 | Top-line FDR_deploy + trend | ✅ pass (was fail) | The x labels read `2026-01-01`, `2026-02-01`, `2026-03-01` under a `computed_at` axis title. The default capture crops at the viewport edge, so the chart was also captured with a taller viewport. | [tall viewport](screenshots/run-3/J2-trend-labels-tall-viewport.png) |
| J3 | Misconfigured | ✅ pass | Shows `dashboard_refusal: …` with the repair, no traceback, no path and no third-party links. | [J3](screenshots/run-3/J3-dashboard-no-database-url.png) |
| J4 | Instrument lamps | ✅ pass (was fail) | With the threshold unset the lamp reads `ingest: unconfigured (set NULLIUS_FEED_STALENESS_THRESHOLD_S)`. With the threshold set it reads `ingest: ok`. With no reading at all it reads `no reading`. | [unset](screenshots/run-3/J2-J4-J5-J6-dashboard-populated.png), [set](screenshots/run-3/J4-lamps-with-threshold.png) |
| J5 | Clean epochs | ✅ pass | Shows `3` on the demo store and `0` on an empty one. | same |
| J6 | Provenance triple | ✅ pass | Shows `provenance: evaluator 608a1ae37855…, snapshot 433368139601…, cost model 1cec44e2f806…`. | same |
| J7 | Exposure | ✅ pass | Binds `127.0.0.1` only, with no Deploy button and no error details. | same |
| J8 | Metrics over HTTP | ✅ pass (was fail) | `/metrics/fdr-deploy` now returns `fdr_deploy: 0.5`, `campaign_id: …0003` and `computed_at` next to `history`. `/metrics/regime-coverage` now returns a `counts` map. A request with no token gets `401`. | [J8](screenshots/run-3/J08-api-metrics.png) |
| J9 | Pre-register | ✅ pass | `200` retry, `409`, `422` and `400`. | [J9](screenshots/run-3/J09-api-pre-register.png) |
| J10 | Forward test | ✅ pass | Unknown node gives `404` with the message `forward_record_absent: forward_record holds no row…`. The word "unwritable" is gone. | [J10](screenshots/run-3/J10-api-forward-test.png) |
| J11 | Trial ledger | ✅ pass (was fail) | With a fresh node: `201` with `appended: true` and `seq 3`, then `200` with the same `seq 3`, then `400`. k-effective now carries `total`. | [J11](screenshots/run-3/J11-api-trial-ledger-fresh-node.png) |
| J12 | Null-oracle target | ✅ pass | Now reachable from the shipped demo with no hand-sealed sidecar. Unknown node gives `404 unknown_node`. The seeded null and real nodes both give `503`, identical apart from the node id the caller sent (computed barrier check: `true`). | [J12](screenshots/run-3/J12-api-null-oracle-target.png) |
| J13 | Risk halt | ✅ pass | `changed: true`, then `changed: false`. With no engine bound: `503 execution_engine_unbound`. | [J13](screenshots/run-3/J13-api-risk-halt.png), [no engine](screenshots/run-3/J13-halt-no-engine.png) |
| J14 | Discoverability | ✅ pass | The index reads "10 routes declared, 10 configured". `/healthz` gives `200`, then `404`, `405` (with `Allow`), `401`, `401` and `403`. | [J14](screenshots/run-3/J14-api-discoverability.png), [index](screenshots/run-3/J14-index-rendered.png) |

**Result: 14 of 14 pass, none blocked.** Every Run 2 finding is fixed and verified in the browser.

**Still open, a decision for the owner and not a defect:** the browser-oriented HTML index at `/` requires a bearer token, and a person who simply navigates to the URL gets `401` (see Run 2).

## Run 4 (full sweep, regression check): 2026-09-29, after removing the `src/app/modules` seats

- **Code under test:** the working tree that removed all 61 seat modules. Components are now read with `create_app().get("<name>")`. The operator dashboard is the one surface whose code changed: it now reads `ops-fdr-deploy` and `ops-instrument-status` straight from the composed application.
- **How it was run:** [`run_sweep.sh`](run_sweep.sh)` run-4 <scratch>` repeats Run 3's setup and checks in one step, using the shipped seeder and its printed sidecar exports, a token file, the paper engine, and the dashboard launched from the repository root. The x labels were read from the chart's SVG and captured with a 1440x1300 viewport.

| # | Journey | Verdict | Observed |
|---|---|---|---|
| J1 | Fresh install | ✅ pass | Shows `—` and *no campaign has closed…*. The KS-guard and ingest lamps read `no reading`, and the epoch count is `0`. |
| J2 | Top-line FDR_deploy + trend | ✅ pass | Shows `50.0%` for campaign `…003`. The x labels read `2026-01-01`, `2026-02-01`, `2026-03-01` under a `computed_at` axis title. |
| J3 | Misconfigured | ✅ pass | Shows `dashboard_refusal: …` with the repair, no traceback and no third-party links. |
| J4 | Instrument lamps | ✅ pass | Reads `ingest: unconfigured (set NULLIUS_FEED_STALENESS_THRESHOLD_S)`, then `ingest: ok` once the threshold is set. |
| J5 | Clean epochs | ✅ pass | Shows `3` on the demo store and `0` on an empty one. |
| J6 | Provenance triple | ✅ pass | Shows `provenance: evaluator 608a1ae37855…, snapshot 433368139601…, cost model 1cec44e2f806…`. |
| J7 | Exposure | ✅ pass | All dashboards listen on `127.0.0.1`. No toolbar buttons appear, so there is no Deploy. |
| J8 | Metrics over HTTP | ✅ pass | FDR returns `fdr_deploy: 0.5` with `campaign_id` and `computed_at`, coverage returns a `counts` map, instrument status returns `200`, and a request with no token gets `401`. |
| J9 | Pre-register | ✅ pass | `200` retry, `409`, `422` and `400`. |
| J10 | Forward test | ✅ pass | Promote gives `200` (retry) and the decay curve gives `200`. An unknown node gives `404 forward_record_absent` ("…holds no row…"). |
| J11 | Trial ledger | ✅ pass | With a fresh node: `201` with `appended: true` and `seq 3`, then `200` with the same `seq`, then `400`. k-effective carries `total`. |
| J12 | Null-oracle target | ✅ pass | Unknown node gives `404`. The seeded null and real nodes both give `503` and are identical apart from the node id (barrier check `true`). |
| J13 | Risk halt | ✅ pass | `changed: true`, then `changed: false`. With no engine bound: `503 execution_engine_unbound`. |
| J14 | Discoverability | ✅ pass | The index reads "10 routes declared, 10 configured". Also observed: `200`, `404`, `405`, `401`, `401` and `403`. |

**Result: 14 of 14 pass, none blocked, no response carried a traceback.** Every verdict and status code is the same as Run 3, so the seat removal introduced no user-visible regression. Screenshots are in [`screenshots/run-4/`](screenshots/run-4/).

## Decision: 2026-09-30, the HTML index stays token-gated

The owner chose to keep `GET /` behind a bearer token. A plain browser visit answering `401` ([Run 2](screenshots/run-2/J14-index-plain-navigation-401.png)) is the intended behaviour, not a defect. J14's preconditions now state that step 1 uses a client that sends the header. The open decision recorded in Runs 2 and 3 is closed.

## Run 5 (full sweep + J15): 2026-10-02, after the BingX Stage 0 dry run and two bug fixes

- **Code under test:** `main` at `199c542`. It adds the BingX Stage 0 router modules (`5f7ff86`, `4681c66`, `fa90cd9`, `490d3a8`), the evaluator debit fix (`fb70c90`, which changes the path behind J11), the deterministic signal-agent test (`37c2aa1`) and the `UV_CACHE_DIR` settings fix.
- **How it was run:** [`run_sweep.sh`](run_sweep.sh)` run-5 <scratch>` for J1–J14. Four Streamlit dashboards left over from Run 4 still held ports 8501–8504 and served stale code, so they were stopped first. Otherwise the sweep's readiness check would have accepted them. J15 is a shell command: its steps were run from the repository root, with each transcript saved as a `.txt` beside the screenshots and then rendered in headless Chromium for `J15-cli-bingx-dry-run.png`.

| # | Journey | Verdict | Observed |
|---|---|---|---|
| J1 | Fresh install | ✅ pass | Shows `—` and *no campaign has closed…*. The KS-guard and ingest lamps read `no reading`, and the epoch count is `0`. |
| J2 | Top-line FDR_deploy + trend | ✅ pass | Shows `50.0%` for campaign `…003`. The x labels read `2026-01-01`, `2026-02-01`, `2026-03-01` under `computed_at`. |
| J3 | Misconfigured | ✅ pass | Shows `dashboard_refusal: …` with the repair and no traceback. |
| J4 | Instrument lamps | ✅ pass | Reads `ingest: unconfigured (set NULLIUS_FEED_STALENESS_THRESHOLD_S)`, then `ingest: ok` once the threshold is set. |
| J5 | Clean epochs | ✅ pass | Shows `3` on the demo store and `0` on an empty one. |
| J6 | Provenance triple | ✅ pass | Shows `provenance: evaluator 608a1ae37855…, snapshot 433368139601…, cost model 1cec44e2f806…`. |
| J7 | Exposure | ✅ pass | All six servers listen on `127.0.0.1`. No toolbar buttons appear. |
| J8 | Metrics over HTTP | ✅ pass | `200` ×3, and a request with no token gets `401`. |
| J9 | Pre-register | ✅ pass | `200`, `200` retry, `409`, `422`, `400`. |
| J10 | Forward test | ✅ pass | `200`, `200` decay curve, `404 forward_record_absent`. |
| J11 | Trial ledger | ✅ pass | With a fresh node: `201` with `appended: true` and `seq 3`, then `200` with the same `seq` and `retry: true`, then `400`. k-effective has `total: 2`. This is unchanged by the `fb70c90` debit fix. |
| J12 | Null-oracle target | ✅ pass | `404` for an unknown node. The null and real nodes both give `503` and are identical apart from the node id (barrier check `true`). |
| J13 | Risk halt | ✅ pass | `changed: true`, then `changed: false`. With no engine bound: `503 execution_engine_unbound`. |
| J14 | Discoverability | ✅ pass | The index reads "10 routes declared, 10 configured". Also observed: `200`, `404`, `405`, `401`, `401`, `403`. |
| J15 | BingX VST dry run | ✅ pass | Exit `0` with five orders (BTC BUY 0.0140 @ 83137.3, ETH SELL 0.558 @ 2685.87, SOL BUY 8.44 @ 118.392, DOGE SELL 5329 MARKET, 1000PEPE BUY 69446 @ 0.0043199, all LIMIT PostOnly except DOGE) and two refusals (`below_min_notional` AGLD, `not_tradable` NCFXUSD2ARS). Every `clientOrderID` is 40 hex characters and a prefix of the router's 64-hex identifier. A second run gives byte-identical output. With sockets patched to raise, the output is the same and exits `0`. A missing `--book` gives exit `1` with one line naming the file and no traceback. |

**Result: 15 of 15 pass, none blocked, no response carried a traceback.** J1–J14 match Run 4 exactly. Screenshots and the J15 transcripts are in [`screenshots/run-5/`](screenshots/run-5/).

**Observation, not a failure:** J15 step 5's refusal begins `bingx_dry_run: bingx_dry_run: the book document …`, with the program name printed twice. It is cosmetic, and the step's expectation still holds.

*Follow-up, 2026-10-02:* the doubled `bingx_dry_run: bingx_dry_run:` prefix is fixed. The command now names itself once, whichever module refused, and `test_bingx_dry_run.py` pins this for both cases. J15 step 5 now reads `bingx_dry_run: the book document at '/nonexistent/book.json' cannot be read: …`.

## Run 6 (full sweep): 2026-10-06, after the orchestrator/campaign-driver work (`main` at `3e8a82f`)

- **How it was run:** [`run_sweep.sh`](run_sweep.sh)` run-6 <scratch>` — the same shipped setup (demo seeder + printed sidecar exports, a generated token file, the paper engine, and the dashboard launched from the repository root), driven through browser-harness over headless Chromium. All six servers came up on `127.0.0.1` and the API composed 10 routes over 100 components (the new `providers` live backends and the `orchestrator` member registered their components without disturbing the existing routes).
- **Scope:** J1–J14 (the browser sweep) plus J15 (the BingX CLI dry run), run as a shell command afterward.

**J15: 5 of 5 steps pass.** Exit 0 with the five orders and two refusals (`below_min_notional` AGLD, `not_tradable` NCFXUSD2ARS); every `clientOrderID` is 40 lowercase hex; a second run is byte-identical; with `socket.socket` patched to raise the plan is identical at exit 0 with no connection and no traceback; a missing `--book` exits 1 with one line naming the file and no traceback (`bingx_dry_run: the book document at '/nonexistent/book.json' cannot be read: …`, the program named once). Transcripts in `screenshots/run-6/J15-step*.txt`.

**Result: 14 of 14 pass, none blocked, no response carried a traceback.** Every verdict and status code matches Run 5's J1–J14: the dashboards render the populated FDR_deploy view (x labels `2026-01-01`, `2026-02-01`, `2026-03-01`), the empty-store state, and the misconfigured refusal; the API journeys return their designed `200/401/403/404/409/422/400/503/201`; the index reads "10 routes declared, 10 configured". So the live-providers, authoring, evaluation, gVisor-executor and campaign-driver work introduced no user-visible regression to the dashboard or HTTP surfaces. Screenshots are in [`screenshots/run-6/`](screenshots/run-6/).

## Run 7 (full sweep + six new journeys from the PRD and architecture): 2026-10-06, `main` at `ad9ffcd`

- **Why:** J1–J15 were sourced from `app_spec.xml` and architecture §16 only. Run 7 re-reads `docs/alpha-engine-prd.md` and `docs/nullius-tech-architecture.md` end to end, and adds a journey for every operator goal they name that no journey covered: J16 (campaign, Loop 1), J17 (dreaming, Loop 2 / M3), J18 (nightly canary), J19 (M1 triage), J20 (research and live metrics), J21 (BingX Stage 1–2 commands).
- **How it was run:** [`run_sweep.sh`](run_sweep.sh)` run-7 <scratch>` for J1–J14 (headless Chromium on :9222, all six servers on `127.0.0.1`). J15, J16 and J21 were run as shell commands with every `BINGX_VST_*`, `TELEGRAM_*` and `NULLIUS_*` value unset, a scratch `DATABASE_URL`, and a `sitecustomize` that makes `socket.connect`, `create_connection` and `getaddrinfo` raise, so even a faulty refusal could not reach a venue, a bot or a model provider. J17–J20 begin by searching for an operator entry point; that search is saved as [`J17-J20-entry-point-search.txt`](screenshots/run-7/J17-J20-entry-point-search.txt).
- **Owner's choice for this run:** no step that spends money or uses real credentials (live campaign, live provider check, VST placement). Those steps are recorded as **blocked (by choice)**, never as pass.

| # | Journey | Verdict | Observed |
|---|---|---|---|
| J1–J14 | Dashboard + HTTP API | ✅ pass ×14 | Every verdict and status code matches Run 6. Index reads "10 routes declared, 10 configured". No traceback in any body. |
| J15 | BingX VST dry run | ✅ pass | Seven lines, byte-identical to Run 6. Every `clientOrderID` is 40 lowercase hex. A rerun is identical. With sockets refused, the output is identical at exit 0. A missing `--book` exits 1 with one line. |
| J16 | Run a campaign | ⛔ blocked (by choice) | Steps 1–3 pass: help exits 0. `live_check` without a key exits 1 with one line naming `NULLIUS_ANTHROPIC_API_KEY`. An unconfigured campaign exits 2 with `campaign_cli: create_app() answers no 'signal-author' component …`, with no traceback and no call. Steps 4–5 (live) were not run. |
| J17 | Run a dreaming cycle | ❌ fail at step 1 | **No operator entry point.** `dreaming` registers `CycleFreeze` and the LLM reviser, but there is no `python -m`, no `run.sh` verb and no unit. The bootstrap pool (M1.5) has no fill command either. Steps 3–4 are blocked behind step 1. |
| J18 | Nightly canary | ❌ fail at steps 1–2 | Step 1: `deploy/systemd/` holds only the VST units, and no command runs the canary, although README line 31 says "a nightly determinism canary checks all of it". Step 2: on a fresh install where no canary has ever run, the dashboard reads **`canary: ok`** beside `KS guard: no reading` ([J1 screenshot](screenshots/run-7/J1-dashboard-empty-db.png)). The lamp is "not halted", and "never ran" is indistinguishable from "passed". |
| J19 | M1 triage AUC | ❌ fail at step 1 | `tripwires/triage.py` exists, but no command, route or panel runs it or shows the AUC. |
| J20 | Research + live metrics | ❌ fail (scope question) | The `ops` stores for null calibration (sens/spec), Type-B depth, discovery rate, meta-overfit gap and live metrics are registered, but the dashboard imports only the FDR route and the lamps, and the API serves only regime coverage among them. `app_spec.xml` `<ui_layout>` defers "the full operator console", so this may be intended. It is for the owner to decide. |
| J21 | Operate the VST bot | ⛔ blocked (by choice) | Steps 1–4 pass: five `--help` pages exit 0. Mirror, rebalance and flatten without keys exit 1 with `vst_credentials_missing` naming both variables. Heartbeat on an empty store and `alert --test` exit 1 with one line each. Step 5 (live VST) was not run. |

**Result: 15 of 21 pass. 4 fail (J17, J18, J19, J20). 2 blocked by the owner's no-spend choice (J16, J21), with all of their no-cost steps passing. No traceback anywhere.**

**Observation, not a failure (J21 step 4):** with Telegram unconfigured, `bingx_heartbeat` against a store with no slot completions exits 1, but its only line is `bingx_alert: TELEGRAM_BOT_TOKEN is not set, so no alert was sent`. The stale/absent verdict itself is not printed. This matches the alerts spec (the alert *is* the report, and the exit code is the verdict), but someone running it by hand learns nothing about the bot.

## Run 8 (full re-verification after the operator-surfaces run): 2026-10-06, `main` at `98824e6`

- **Code under test:** the 14 features of [`additions_spec_operator_surfaces.xml`](../../additions_spec_operator_surfaces.xml), merged `74f899d`…`98824e6`. All 14 passed the acceptance gate. Member suites: bootstrap 517, tripwires 420, router 1380, ops 819, api 526 and orchestrator 407 (+5 runsc skips) all pass. Canary has 787 passing and **2 failing** (`test_threads.py`, order-dependent under `-n 4`). Those 2 were already failing at `e4bd380`, before the run.
- **How it was run:**
  - J1–J14: [`run_sweep.sh`](run_sweep.sh)` run-8`, headless Chromium.
  - J15–J21: the shipped `./run.sh` verbs and `python -m` commands, against fresh scratch stores, with sockets patched to raise and every venue, bot and sidecar secret unset.
  - J20 was also checked on the store J17's operator built (after `dream` and `canary`), read through the dashboard (browser text plus screenshot) and through the five `metrics:read` routes on a local API server.

| # | Journey | Verdict | Observed |
|---|---|---|---|
| J1–J14 | Dashboard + HTTP API | ✅ pass ×14 | Every status code matches Run 7. The index now reads **"14 routes declared, 14 configured"**. The dashboard shows a **Gate evidence** section *below* the FDR_deploy panel and chart. **The canary lamp reads `no reading` on a fresh install and on the demo store** (J04's precondition is updated: the demo seeds no canary run). |
| J15 | BingX dry run | ✅ pass | Byte-identical to Run 7, also with sockets refused. A missing `--book` exits 1. |
| J16 | Run a campaign | ⛔ blocked (by choice) | Every no-cost step passes. The campaign help lists `--no-closeout`. `closeout --help` exits 0. Close-out without a sidecar exits 2: `closeout: NULL_SIDECAR_PATH must name the sealed null sidecar …`. The close-out success path needs a real campaign, which is not run without spend. |
| J17 | Dreaming cycle | ❌ **fail at step 1b** | `./run.sh migrate` exits 2: `error: Failed to spawn: alembic` (there is no `alembic.ini`). Applying each migration file's own `apply()` in order then crashes at `0113_node_indexes`: `no such table: main.node`, because `node` is created by `0118`, later in the chain. With no migrated store, `dream` refuses with "holds no replay_score table" instead of reaching `pool_too_thin`. **With the tables present (workaround, a diagnostic), every later step passes:** `pool_too_thin: the pool holds 0 world(s)…`; the fill writes 45 worlds and a rerun is idempotent; another seed is refused with `bootstrap_pool_populated`; the cycle exits 0 with `revision_cap` 10, a 31/14 train/holdout split, 355 `replay_score` rows and a gap printed; the same seed on a new iteration selects the same `code_hash`; `--write-selected` writes the policy and refuses to overwrite it; `--reviser llm` gives `policy_isolation_required`. |
| J18 | Nightly canary | ✅ pass | `nullius-canary.timer` and `.service` exist. `no reading` on a fresh install. Run before freeze: `canary_reference_absent`. Freeze exits 0. A second freeze: `canary_reference_exists`. Run: exit 0, deviation 0.0, lamp `true` with `canary_last_run_at`. With a tampered constant (diagnostic): exit 3, lamp `false`. |
| J19 | M1 triage | ✅ pass | AUC 0.4548 over the member's planted panel, `"reading": "learned_signature_warranted"`. `--count 1` exits 1 with one line. |
| J20 | Gate evidence | ✅ pass | Operator store: `canary: ok` and `train-vs-holdout gap: -0.144 (iteration run8-b)`. The other three lines read `no reading` (they fill at campaign close-out). All five routes answer 200. Live metrics stay deferred (owner's decision). |
| J21 | VST bot | ⛔ blocked (by choice) | Steps 1–4 pass. **The heartbeat now prints `{"verdict": "absent", …}`**, which resolves the Run 7 observation. Step 5 (live VST) was not run. |

**Result: 18 of 21 pass, 1 fail (J17), 2 blocked by the no-spend choice. No traceback anywhere.**

**Findings for the next fix round:**
1. `./run.sh migrate` is broken (Alembic absent), and the migration tree cannot build a fresh database in its declared order (`0113`/`0114` touch `node` before `0118` creates it; base `0106` is absent from the tree). This blocks J17 for a real operator.
2. No example incumbent policy is shipped for `dream --incumbent`. The only admissible one lives in a test file.
3. `orchestrator.closeout` answers a store whose `node` rows carry no metric columns with a raw `no such column: ic_mean`, not a named refusal.
4. `python -m canary.run` and `python -m tripwires.triage` print `RuntimeWarning: '…' found in sys.modules …` on every invocation.
5. `packages/canary/tests/test_threads.py`: two tests fail under `-n 4` and pass alone. This was already failing before the run, and it breaks the repo's order-independence rule.

## Run 9 (re-verification after the Run 8 bug fixes): 2026-10-06, `main` at `3442f72`

- **Code under test:** [`bug_spec_run8_operator_findings.xml`](../../bug_spec_run8_operator_findings.xml), all six merged (`f98802e`…`dd94ec0`) with 100% footprint conformance. Member suites: canary **790 passed** (the two order-dependent thread tests are fixed), tripwires 421, orchestrator 412 (+5 runsc skips).
- **How it was run:** as in Run 8. J17 starts from an **empty** store and uses only shipped commands and files, with no workaround.

| # | Journey | Verdict | Observed |
|---|---|---|---|
| J1–J14 | Dashboard + HTTP API | ✅ pass ×14 | 35 calls, status codes identical to Run 8, no traceback. 14 routes. Gate evidence below FDR_deploy. Canary `no reading` on the demo. |
| J15 | BingX dry run | ✅ pass | Byte-identical to Run 8 with sockets refused. A missing `--book` exits 1. |
| J16 | Run a campaign | ⛔ blocked (by choice) | No-cost steps pass. A metric-less store now gives `closeout_unevaluated: campaign '…003' has not been evaluated …`, not a raw SQLite error. |
| J17 | Dreaming cycle | ✅ **pass** | `./run.sh migrate` on an empty store reaches head `0119_canary_reference_pair`, and a rerun is idempotent. `pool_too_thin` with 0 worlds. The fill writes 45 worlds, a rerun is idempotent, and another seed is refused. A cycle with the **shipped `deploy/dreaming/incumbent.example.py`** exits 0 (`revision_cap` 10, 355 `replay_score` rows). The same seed on a new iteration selects the same `code_hash`. `--reviser llm` and an overwrite are both refused. |
| J18 | Nightly canary | ✅ pass | On a migrated fresh store: `canary_reference_absent`, then freeze, then `canary_reference_exists`, then run (deviation 0.0), and the lamp reads `true`. **No `RuntimeWarning` on stderr.** |
| J19 | M1 triage | ✅ pass | AUC 0.4548, `learned_signature_warranted`. Bad count gives exit 1. No `RuntimeWarning`. |
| J20 | Gate evidence | ✅ pass | On J17's operator store after `canary`: `canary: ok` and `train-vs-holdout gap: -0.048 (iteration run9-b)`. |
| J21 | VST bot | ⛔ blocked (by choice) | Steps 1–4 pass. The heartbeat prints `{"verdict": "absent", …}`. Live VST was not run. |

**Result: 19 of 21 pass, 0 fail. The 2 blocked journeys are blocked only by the owner's no-spend choice, and every no-cost step in them passes. No traceback or `RuntimeWarning` anywhere. All five Run 8 findings are resolved.**

**To close J16 and J21:** run `./run.sh campaign … --allowance <small>` (real LLM spend; the campaign now closes itself out, so the Gate evidence rows fill) and `./run.sh vst --status` / `vst-rebalance` (VST, simulated funds) when the owner authorises them.

## Run 10 (J16 with real spend; M1 measured): 2026-10-08 to 2026-10-09, `main` at `4e95b9a`

- **What ran:** live Type-R campaigns under `./run.sh campaign`, with the owner's approval. They used gVisor sandboxing (root re-provisioned at `63157c3` and again for `8ffff75`), Opus 5.5 root authoring, and automatic close-out. The last five ran on the survivorship-free archive snapshot `2026-10-08T03:33:28Z_540e93`: 100 symbols, 2019–2026, delistings included. They used `evaluation-config-archive.json`: 235 weekly dates from 2022-01 to 2026-06, horizon 5, 400-day history cap, 8 evaluation workers.
- **Spend:** $28.70 recorded in total across all campaigns. The five archive triage campaigns cost $10.51.

| # | Journey | Verdict | Observed |
|---|---|---|---|
| J16 | Run a campaign | ✅ **pass** | `archT1`–`archT5`: 33/33 nodes scored each, 0 sandbox failures, automatic close-out every time. Exit 0 ×4, plus one exit 3 (VOID, KS p 0.013), which is the documented VOID code. |

**M1 results (pooled over the five archive campaigns, 165 nodes, 25 planted nulls):**

| Measure | Value |
|---|---|
| KS guard | ok in 4 of 5 (p 0.08, 0.013 VOID, 0.42, 0.21, 0.12) |
| Discoveries (t ≥ 2) | 59 |
| Sensitivity | 0.41 (56 of 135 real roots) |
| Specificity | 0.96 (24 of 25 nulls; 95% CI about 0.80–1.00) |
| FDR_deploy at π₀ = 0.9 | about 0.46 (wide, set by the specificity CI) |
| Triage AUC, perturbation stability (`deploy/campaign/pooled_triage.py`) | **0.43 ± 0.06** |

**Verdict:** the PRD's "single robustness statistic" branch (AUC ≈ 0.85) is ruled out. Perturbation stability does not separate planted nulls from real signals, so the learned-signature branch, and M3, is the one worth building.

**Defects found and fixed during the run:**
- the time-leaking null permutation
- tripwire false positives on persistent signals (made advisory, with a promotion gate)
- `ctx.bars` lookback counted across the frame
- a stale gVisor root, now guarded
- the sandbox import allowlist preload
- target-route grid, horizon and symbol support
- close-out root mapping, NULL fail_class and the no-discovery case
- the triage orientation
- evaluation throughput (per-symbol panels, mount.select without glob, close-cache lock)

On the 92-day window, the same pipeline gave FDR_deploy 0.98. The longer window is what gives discoveries power.

**Open for the next round:**
- register the closed-out campaigns as replay worlds (the pool is 45 bootstrap, 0 financial)
- per-commit out-of-sample IR (M2)
- process-based node evaluation (GIL-bound at 8 threads)
- the KS guard reading genuine real-node dispersion as detectability
- the migration 0118 statements/upgrade index mismatch
