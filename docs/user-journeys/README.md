# User journeys

Every way a person, or a trusted service acting for one, reaches NULLIUS from
outside the Python process. The sources are `docs/alpha-engine-prd.md` (J16–J21), `app_spec.xml`
(`<api_endpoints_summary>`, `<ui_layout>` and the M5 `<ux>` line) and
`docs/nullius-tech-architecture.md` §16.

Each journey is checked in a real browser with
[browser-harness](https://github.com/browser-use/browser-harness) driving
headless Chromium. Screenshots are saved under `screenshots/<run>/`.

## Actors

| Actor | Who | Surface | Token scope |
|---|---|---|---|
| **Operator** | The human who watches the running system | Streamlit operator dashboard | — (the dashboard reads the store directly) |
| **Researcher** | The human who pre-registers and promotes signals | HTTP API (`/promotion`, `/forward`) | `research` |
| **Evaluator** | The frozen evaluator service (Z0) | HTTP API (`/ledger`, `/target`) | `evaluator` |
| **Risk supervisor** | The kill-switch process, or a human pressing it | HTTP API (`/risk/halt`) | `risk` |
| **Any caller reading metrics** | Monitoring, the dashboard's chrome | HTTP API (`/metrics`, the index at `/`) | `metrics:read` |

Every HTTP journey except [J14](J14-api-discoverability.md)'s `/healthz` step
presents its actor's token as `Authorization: Bearer <token>`; the four scopes
are the whole vocabulary, `GET /healthz` is the one route that answers without
one, and a server started with no token file configured refuses to start
(additions_spec_journeys.xml feature 18).

Those tokens never cross a network in cleartext (feature 21). The server binds
`127.0.0.1` unless `--host` or `NULLIUS_API_HOST` names another interface, and
any *other* interface must name a PEM certificate and key in
`NULLIUS_API_TLS_CERT` and `NULLIUS_API_TLS_KEY` — without them the server
refuses to start with one plain sentence naming the file, and with them it
serves HTTPS through the standard library's `ssl` module. A non-loopback bind
has no cleartext mode: there is no redirect from a plain port and no fallback,
so a caller reaching an `/api` route from another machine is always inside TLS.
The journeys below are run against `127.0.0.1`, which needs no certificate.

## Journeys

| # | Journey | Actor | Surface |
|---|---|---|---|
| [J1](J01-dashboard-first-run.md) | Open the dashboard on a fresh install | Operator | Dashboard |
| [J2](J02-dashboard-top-line-fdr.md) | Read the top-line FDR_deploy and its trend | Operator | Dashboard |
| [J3](J03-dashboard-misconfigured.md) | Start the dashboard with no metrics store configured | Operator | Dashboard |
| [J4](J04-dashboard-instrument-lamps.md) | See the three instrument lamps in permanent chrome | Operator | Dashboard |
| [J5](J05-dashboard-clean-epochs.md) | Watch the remaining clean-epoch count | Operator | Dashboard |
| [J6](J06-dashboard-provenance.md) | See the provenance triple beside the top-line figure | Operator | Dashboard |
| [J7](J07-dashboard-exposure.md) | Run the dashboard safely: local only, no third-party links | Operator | Dashboard |
| [J8](J08-api-metrics.md) | Read the three observability metrics over HTTP | Operator | HTTP API |
| [J9](J09-api-pre-register.md) | Pre-register promotion criteria before the deciding evaluation | Researcher | HTTP API |
| [J10](J10-api-forward-test.md) | Promote a signal to forward test and read its decay curve | Researcher | HTTP API |
| [J11](J11-api-trial-ledger.md) | Debit the trial ledger and read K-effective | Evaluator | HTTP API |
| [J12](J12-api-null-oracle-target.md) | Ask the null oracle for a target series | Evaluator | HTTP API |
| [J13](J13-api-risk-halt.md) | Trigger the emergency halt | Risk supervisor | HTTP API |
| [J14](J14-api-discoverability.md) | Discover what the API serves, and get clean errors | Any | HTTP API |
| [J15](J15-cli-bingx-dry-run.md) | Dry-run the book onto BingX VST (Stage 0, no network) | Operator | CLI |
| [J16](J16-cli-run-campaign.md) | Run one discovery campaign (Loop 1) | Operator | CLI |
| [J17](J17-run-dreaming-cycle.md) | Run one dreaming cycle and read the selected policy (Loop 2, M3) | Operator | CLI |
| [J18](J18-nightly-determinism-canary.md) | The nightly canary runs, and its lamp tells the truth | Operator | Scheduler + Dashboard |
| [J19](J19-m1-triage-auc.md) | Run the M1 triage and read the perturbation-stability AUC | Researcher | CLI |
| [J20](J20-read-research-and-live-metrics.md) | Read the research and live metrics behind the headline | Operator | Dashboard / HTTP API |
| [J21](J21-cli-bingx-vst-operate.md) | Operate the BingX VST paper bot (Stage 1–2) | Operator | CLI |

## Validation runs

Each run is appended to [`_run-log.md`](_run-log.md). [`run_sweep.sh`](run_sweep.sh) `<run-name> <scratch-dir>` drives J1–J14 (the browser sweep) in one command; J15 is a shell journey run separately, its transcripts saved beside the screenshots.

**Latest — Run 8 (2026-10-06): 18 of 21 pass, 1 fail (J17: `./run.sh migrate` cannot prepare a fresh store), 2 blocked by the owner's no-spend choice (J16, J21).** The operator-surfaces run made the dreaming cycle, the nightly canary, the M1 triage and the gate evidence reachable. The canary lamp is now honest. Details in [`_run-log.md`](_run-log.md).

## Reproducing a run

```bash
# Browser: headless Chromium with CDP on :9222. --no-sandbox is needed on
# Ubuntu 23.10+, where AppArmor blocks unprivileged user namespaces.
chrome --headless=new --no-sandbox --remote-debugging-port=9222 about:blank &

# Dashboard, against a metrics store (Streamlit is installed where it runs,
# not in the workspace lockfile).
DATABASE_URL=sqlite:////abs/path/demo.db \
  uv run --all-packages --with streamlit \
  streamlit run packages/ops/src/ops/dashboard.py --server.address 127.0.0.1

# Drive and screenshot
BU_CDP_URL=http://localhost:9222 browser-harness <<'PY'
new_tab("http://127.0.0.1:8501/"); wait_for_load()
capture_screenshot("docs/user-journeys/screenshots/<run>/<name>.png", full=True)
PY
```
