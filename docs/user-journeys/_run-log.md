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
