# NULLIUS

> *Nullius in verba*: take nobody's word for it.

**A recursively self-improving research system that discovers predictive signals in crypto markets and measures its own false discovery rate.**

NULLIUS adapts the core mechanism of *Dream-RSI* (recursive self-improvement through evolving worlds) to quantitative research. A finished discovery tree already records every outcome needed to replay alternative search orders at zero execution cost. NULLIUS replays those trees offline ("dreaming") to improve its *exploration policy*, meaning the strategy it uses to decide which hypotheses to try next.

Trading adds a problem the original paper does not have: a backtest score is noisy, biased and easy to game. A naive port would build the most compute-efficient overfitting machine ever assembled. NULLIUS closes that gap by **planting hidden null hypotheses at the evaluation layer**. Because the system knows which nodes are nulls and the search does not, it recovers supervised labels. The research process then carries a *measured* false discovery rate, not an assumed one.

The main product is not a strategy. It is a calibrated search-and-select policy with a known false discovery rate that improves over time.

---

## Why it is different

| Conventional backtest research | NULLIUS |
|---|---|
| The scarce resource is compute or agent calls | The scarce resource is **statistical degrees of freedom** |
| Treats the node score as ground truth | Treats the node score as **corruptible, and measures the corruption rate with planted nulls** |
| Counts multiple tests by hand, if at all | Records every trial automatically in an **append-only ledger** so deflation is exact |
| Searches strategies (entries, exits, sizing) | Searches **signals only**. Portfolio construction is fixed and human-authored |
| Look-ahead is "forbidden" | Look-ahead is **physically impossible**: the sandbox only ever receives data at or before `t` |

## Design principles

Each principle is enforced by architecture. None relies on a prompt or a convention.

1. **The loop cannot weaken its own validator.** The evaluator, cost model and data snapshots sit in a read-only trust zone. LLM-authored code has no write credential for it and no network path to it.
2. **`is_null` is physically unreachable.** Null assignments live in an AES-GCM-encrypted sidecar whose key belongs to a single service account.
3. **Replay is bit-reproducible.** Images, seeds and BLAS threading are pinned, searched code cannot read the wall clock, and a nightly determinism canary checks all of it.
4. **Future data is absent, not merely forbidden.** The signal sandbox never mounts the data lake.
5. **Replay never invokes the evaluator.** This is what keeps dreaming free.
6. **Research compute and trading compute are separate systems.** They share libraries and never share infrastructure.

### Trust zones

| Zone | Contents | Writable by |
|---|---|---|
| **Z0: Immutable** | Data snapshots, evaluator, cost model, null oracle, trial ledger | Humans, through a signed release only |
| **Z1: Loop-mutated** | Signal code, exploration-policy code | LLM agents, inside a gVisor sandbox with no network or filesystem access |
| **Z2: Human-authored** | Portfolio construction, execution, risk supervisor | Humans, through reviewed PRs |
| **Z3: Derived** | Discovery trees, artifacts, replay scores, forward-test records | Services, content-addressed |

Agents write to Z1 only, and Z1 holds no credential for Z0.

## Three nested loops

- **Inner (minutes): online exploration.** Agents propose and refine signal hypotheses as nodes in a discovery tree. The frozen evaluator scores each node against a pinned data snapshot, and every trial is appended to the ledger.
- **Middle (hours): dreaming.** Candidate exploration policies are replayed deterministically over stored trees. Scoring uses a CVaR aggregate across worlds, penalized by the planted-null pick rate. The winning policy becomes the next policy.
- **Outer (months): forward-test recalibration.** Promoted signals are tracked out of sample. The measured decay and error rates recalibrate the priors and the null fraction.

## Repository layout

```
.
├── src/app/              # Application factory and module loader (discovers members)
├── packages/             # uv workspace members, one per bounded component
│   ├── api/              #   HTTP transport over the composed application (bearer-token gated)
│   ├── contract/         #   Z0 MarketWindow contract and signal ABI
│   ├── ingest/           #   Market-data ingest workers
│   ├── snapshot/         #   Content-addressed, immutable lake snapshots
│   ├── feature-store/    #   Point-in-time feature store
│   ├── evaluator/        #   Frozen, digest-pinned evaluator identity
│   ├── cost-model/       #   Hash-pinned fee schedule, fill model and latency
│   ├── nulloracle/       #   Encrypted planted-null sidecar
│   ├── ledger/           #   Append-only trial ledger
│   ├── sandbox/          #   gVisor-isolated execution of agent-authored code
│   ├── signal-agent/     #   Hypothesis-authoring agent contract
│   ├── discovery/        #   Campaign planning and planted-null fractions
│   ├── tripwires/        #   Leakage tripwires (time-shuffle probe)
│   ├── replay/           #   Deterministic tree replay
│   ├── dreaming/         #   Fixed replay pools for policy iteration
│   ├── policy-runtime/   #   question.* interface handed to exploration policies
│   ├── scoring/          #   Per-world objective and FDR scoring
│   ├── bootstrap/        #   Non-financial ground-truth worlds for calibration
│   ├── regime/           #   Regime coverage ledger
│   ├── canary/           #   Determinism canary
│   ├── promotion/        #   Pre-registered promotion criteria
│   ├── forward/          #   Forward-test records and decay
│   ├── universe/         #   Monthly point-in-time tradable universe
│   ├── book/             #   Fixed portfolio construction (IR-weighted composite)
│   ├── router/           #   Order routing, venue filters, rate limiting and the BingX VST bot
│   ├── risk/             #   Risk supervisor and kill switches
│   ├── ops/              #   Metrics API and Streamlit dashboard
│   ├── artifacts/        #   Per-node artifact store
│   ├── providers/        #   One model-call interface + live Anthropic/OpenAI-compatible backends
│   └── orchestrator/     #   The campaign driver: live node evaluation, gVisor/bwrap sandbox, the loop
├── migrations/           # Relational schema migrations
├── deploy/systemd/       # Timers and services for the scheduled BingX VST bot
├── deploy/gvisor/        # Provisions the read-only runtime root the signal sandbox runs in
├── deploy/campaign/      # Example research-loop configs (authoring + evaluation)
├── infra/security/       # Credential isolation, secrets management and policies
├── tests/                # Workspace-level contract, invariant and end-to-end suites
└── docs/                 # PRD, technical architecture, design notes and user journeys
```

## Paper trading on BingX VST

The `router` member takes the fixed book to a real venue in stages. All of them run against BingX's **VST** venue (simulated funds), and the client refuses any other host.

| Stage | Command | What it does |
|---|---|---|
| 0: Dry run | `python -m router.bingx_dry_run --book B --contracts C --marks M` | Builds the order plan from recorded documents and prints one JSON line per order or refused leg. No network, no keys |
| 1: Mirror | `./run.sh vst --book B [--place \| --status \| --cancel]` | Fetches live contracts, marks and positions, runs a preflight, and places idempotently by client order ID |
| 2: Scheduled | `./run.sh vst-rebalance --book B` | Runs one 4-hour slot: daily-loss guard, cancel stale orders, reconcile the previous slot's fill costs, place, then record the slot |
| 2: Flatten | `./run.sh vst-flatten --confirm` | Cancels every order and closes every position. Without `--confirm` it only prints what it would do |
| Alerting | `./run.sh vst-alert` / `vst-heartbeat` | Sends Telegram alerts for slot outcomes, failed units and a bot that has gone quiet |

The `vst*` commands inject only the VST sub-account key and the Telegram credentials, through 1Password (`op run --env-file=.env.vst.tpl`). They keep their store at `~/.local/share/nullius/vst.db` unless `DATABASE_URL` says otherwise. `deploy/systemd/` schedules a rebalance at 00/04/08/12/16/20:05 UTC and a heartbeat check every hour, and a failed slot triggers an alert unit.

## Running a research campaign

The `orchestrator` member is the inner exploration loop: it plants root signals, lets the exploration policy pick a node, has the signal agent author a child, evaluates it against the frozen evaluator (which debits the trial ledger and applies the planted nulls), persists the attempt, and stops on budget or saturation. Agent-authored signal code runs under a real OS sandbox — gVisor (`runsc`), or a bubblewrap fallback — never in the host process. The Python import guard is defence-in-depth, not the boundary.

A first real campaign needs the market data, the sealed snapshot and the evaluator image in place before it can evaluate anything. Run the whole path once, in order:

```bash
./run.sh migrate                                                       # apply pending schema migrations
./run.sh lake-backfill --first YYYY-MM-DD --last YYYY-MM-DD --top N    # archive source for M3-feeding work; LAKE defaults to ~/.local/share/nullius/lake
./run.sh lake-seal                                                     # seal $LAKE/staging into an immutable snapshot
./run.sh evaluator-image                                               # build the evaluator image; copy its digest-pinned reference into NULLIUS_EVALUATOR_IMAGE
./run.sh canary --freeze-reference                                     # one-time: freeze the determinism canary's reference pair
./run.sh bootstrap-fill                                                # fill the non-financial calibration pool
./run.sh campaign --type discovery --workspaces 16 --rounds 30         # run the research loop
```

The `campaign` verb injects only the `NULLIUS_*` research keys through 1Password (`op run --env-file=.env.campaign.tpl`), keeps its store at `~/.local/share/nullius/research.db` unless `DATABASE_URL` says otherwise, and reads two JSON configs named by the template: the authoring config (the per-role model pins and token budgets) and the evaluation config (the snapshot, dates, seed and sandbox runtime). Copy the checked-in starting points to begin:

```bash
cp .env.campaign.tpl.example .env.campaign.tpl                 # then set your 1Password op:// paths
cp deploy/campaign/authoring-config.example.json   deploy/campaign/authoring-config.json
cp deploy/campaign/evaluation-config.example.json  deploy/campaign/evaluation-config.json
```

For gVisor isolation, `deploy/gvisor/provision_runtime.sh` builds the read-only runtime root the sandbox runs in (pinned Python, polars and pyarrow, the baked signal-child bootstrap), and the orchestrator verifies that root against its manifest digest before running any agent code. A campaign interrupted part-way is resumable with `orchestrator.resume_campaign`.

### Canary, the middle loop, the M1 triage and close-out

| Command | `run.sh` verb | Exit codes |
|---|---|---|
| `python -m canary.run [--freeze-reference]` | `canary` | 0 replayed and recorded; 1 refused (no active reference, more than one, or one already frozen); 2 no `DATABASE_URL`; 3 the replay broke tolerance, which halts dreaming |
| `python -m bootstrap.fill [--count N] [--pool-seed S] [--census]` | `bootstrap-fill` | 0 filled, or census printed with `--census`; 1 refused (the pool already holds a different seed, or count is outside [40, 50]); 2 no `DATABASE_URL` |
| `python -m orchestrator.dream --incumbent PATH [...]` | `dream` | 0 cycle committed, prints the selected revision and its train-vs-holdout gap; 1 refused (canary halt, pool too thin, incumbent fails screening, or `--reviser llm`); 2 no `DATABASE_URL` |
| `python -m tripwires.triage [--seed S] [--count N]` | `triage` | 0 prints the perturbation-stability AUC and its PRD §12 reading, measured over the member's own planted panel; 1 refused (bad seed or count) |
| `python -m orchestrator.closeout --campaign-id ID` | `closeout` | 0 campaign calibrated; 1 refused (unknown campaign or a one-sided plant); 2 missing the null sidecar or `DATABASE_URL`; 3 the verdict is VOID |

`canary`, `bootstrap-fill`, `dream` and `triage` need no secret and default `DATABASE_URL` the way `campaign` does. `closeout` also needs the null sidecar (`NULL_SIDECAR_PATH`, `NULL_SIDECAR_KEY_REF`), so it runs under `op run --env-file=.env.campaign.tpl` like `campaign` does.

`./run.sh campaign` now closes itself out: after its summary line it runs `closeout` on the `campaign_id` it just finished and prints that JSON line, so `FDR_deploy`, the KS guard, sensitivity/specificity, Type-B depth and the discovery rate are measured for every real campaign, not only the demo seeder (`nullius_api.demo`). A close-out refusal exits the campaign command 1 without losing the campaign — rerun `./run.sh closeout --campaign-id ID` once the cause is fixed. A VOID verdict exits 3. `--no-closeout` skips the step when no sidecar is configured.

A nightly determinism canary runs on its own schedule: `deploy/systemd/nullius-canary.timer` fires `nullius-canary.service` (`run.sh canary`) daily at 03:15 UTC (`Persistent=true`), alerting through the existing VST alert unit on failure. Neither unit is installed or enabled by the repository.

## Stack

Python 3.12 · [uv](https://docs.astral.sh/uv/) workspace · Polars · DuckDB over Parquet · Pydantic Settings · SQLite / PostgreSQL · asyncio + websockets · gVisor · Streamlit

## Getting started

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/bowen31337/nullius.git
cd nullius

# Install every workspace member and the dev tooling
uv sync --all-packages

# Configure the environment (fill in your own values; never commit .env)
cp .env.example .env
```

### Running the tests

The workspace-level suites and the per-member suites are separate trees, so run both:

```bash
# Workspace contract, invariant and end-to-end suites
uv run --all-packages pytest -n 4 --dist loadfile

# One member's suite; put every member it imports on PYTHONPATH
PYTHONPATH=src:packages/router/src:packages/book/src:packages/ingest/src:packages/risk/src \
  uv run --no-sync pytest -q -n 4 packages/router/tests
```

Each test gets a temporary lake root and a throwaway SQLite database. Set `TEST_DATABASE_URL` to run against PostgreSQL instead.

## Documentation

- [`docs/alpha-engine-prd.md`](docs/alpha-engine-prd.md): product requirements, planted-null mechanism, replay objective and success metrics
- [`docs/nullius-tech-architecture.md`](docs/nullius-tech-architecture.md): trust zones, component map, data model, determinism contract and failure modes
- [`docs/design.md`](docs/design.md): design notes
- [`docs/user-journeys/`](docs/user-journeys/README.md): every external surface (dashboard, HTTP API and CLI) as a journey, with a browser-driven sweep

## How it was built

NULLIUS was built feature by feature, with each feature specified up front and implemented by parallel coding agents. Claims on files, an acceptance gate and merge gating kept those agents from colliding. The per-feature specs (`additions_spec_*.xml`, `feature-*.spec.md`) and plans (`.plans/`, `.claude/plans/`) are kept in the repository as the record of each design decision.

## Status

**Research build: not production trading software.** Most components and their end-to-end tests are in place. Execution runs on a schedule against BingX's simulated-funds VST venue only. The system has not been validated with capital, and nothing here is financial advice. Trading carries a substantial risk of loss.

## Security

The repository contains no credentials. Configuration comes from environment variables (see `.env.example`), and local secret files (`.env`, `.env.tpl`, `.env.vst.tpl`, `claw-forge.local.yaml`) are git-ignored. Exchange credentials belong in a secrets manager and are injected per command. The exchange key is kept apart from the template the coding agents run under. Any key-like strings under `infra/security/tests/` are fake fixtures that exercise the secrets-management code.

If you find a security issue, please open a private security advisory on GitHub rather than a public issue.

## License

Released under the [MIT License](LICENSE).
