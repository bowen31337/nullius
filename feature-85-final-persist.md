# Feature 85 — System persists the full artifact to the artifact store plus the scalar metrics to the tree store as the final pipeline step

## Context

`app_spec.xml`, "Frozen Evaluator Pipeline", feature 85 (depends on 84):

> *System persists the full artifact to the artifact store plus the scalar
> metrics to the tree store as the final pipeline step.*

`docs/nullius-tech-architecture.md` §6.1 names this as the last line of the
pipeline:

```
12. persist           artifact → ART, scalars → TREE
```

and §9 lays out the two destinations this step feeds:

* **§9.2 — the artifact store** (object storage / local Parquet): one directory
  per node, `/artifacts/<campaign_id>/<node_id>/`, holding the things replay
  needs and scalars cannot provide — `signal_returns.parquet`, `ic_series.parquet`,
  `turnover_series.parquet`, `decay_profile.json`, `regime_attribution.json`,
  `exec_trace.json`, `code.py`.
* **§9.1 — the tree store** (Postgres): the `node` table, whose scalar columns
  (`ic_mean`, `ic_tstat`, `ir_standalone`, `turnover`, `ir_marginal`,
  `cost_adjusted_ir`, `perturb_stability`) are the node's headline numbers.

Steps 7–11 already produce everything this step writes down: step 7's
`PostCostReturns` (feature 79), step 8's `NodeMetrics` / `DecayProfile` /
`CapacityEstimate` + `RegimeAttribution` (features 80, 81, 82), step 9's
`MarginalIR` (feature 83), and step 11's `DebitedTrial` (feature 84). Each of
those steps has *already* written its own half into the workspace's relational
store (`DATABASE_URL`), in the store module that pairs with its compute module —
`_cost_store`, `_metrics_store`, `_decay_store`, `_capacity_store`,
`_marginal_store`. Those stores are the evaluator's durable copy; the artifacts
member (feature 169/170/172) and the tree member (feature 85's counterpart) read
them back to write the Parquet directory and the `node` row.

**What feature 85 adds is the *final pipeline step* that ties those two halves
together into one node-scoped, one-shot, idempotent write.** It is not a new
metric and not a new store. It is the orchestration the other steps deliberately
do not do: gather the node's persisted pieces, render each into its §9.2
artifact file, and copy the scalar metrics onto the §9.1 `node` row — under one
contract that says the write is keyed by the node, refuses a half-written node,
and can be retried safely.

### Why this is the evaluator's feature, not the artifacts' or tree member's

The artifacts member owns *how* a Parquet file is encoded and *where* a JSON file
sits; the tree member owns the `node` table's DDL and its non-metric columns
(`code_hash`, `agent_model_id`, `parent_id`, `created_at`). Neither owns the
question feature 85 answers: *which set of measured values is one node's
artifact, and what makes the write of that set atomic and idempotent?* That is a
question about the *evaluator's own outputs* — the records steps 7–9 produced and
steps 79–83 persisted — and the evaluator is the only member that holds them as
values. So feature 85 is the evaluator's: it reads the evaluator's own stores
back and hands each half to the boundary that writes it, carrying the contract
that keeps the two halves from diverging.

### The two halves, and the seams they cross

This step is deliberately thin over two seams it does not own:

* **The artifact store** is written through an injected `ArtifactWriter` — an
  object exposing `write_artifact(node_id, campaign_id, filename, payload)` and
  `flush(node_id)`, the shape the artifacts member will speak. The evaluator
  imports no sibling (the workspace contract), so the writer is injected, the
  same way feature 73's sandbox, feature 76's oracle and feature 84's ledger are.
  This member renders the *content* of each §9.2 file from the measured records;
  the writer owns the encoding (Parquet bytes, JSON bytes) and the path
  (`<campaign_id>/<node_id>/<filename>`).
* **The tree store** is written through an injected `TreeNodeWriter` — an object
  exposing `write_node(node_row)` that answers `(node_id, appended)`. The
  evaluator owns the *scalar metrics*; the tree member owns the *table* and its
  non-metric columns. This member assembles the `node` row's metric columns from
  the measured records and hands it across; the tree writer owns the DDL, the
  identity column and the non-metric fields.

Both seams are structural: satisfied by duck typing, read back where the answer
matters, and their own failures propagate unwrapped.

## Design

Two new modules in `packages/evaluator/src/evaluator/`, following the
compute/store split this package already uses six times:

* **`_artifact.py`** — the *content* half. Turns the measured records into the
  exact payload of each §9.2 artifact file, and defines the injected
  `ArtifactWriter` seam. Stdlib-only (JSON assembly; the Parquet *bytes* are the
  writer's to produce, so no polars/pyarrow here — the Polars boundary stays at
  the edge of the package, exactly as every other member keeps it).
* **`_persist_store.py`** — the *orchestration* half. The `NodePersistence`
  record, the `NodeArtifactStore` that reads the evaluator's own stores back and
  drives the two seams in one idempotent transaction, and the module-level
  `persist_node` the pipeline calls.

Registered spellings are exported from `__init__.py`; `@register` stays in
`__init__.py` only (a submodule's registration fires once and drops out — see
memory). No central file names this member; the factory discovers the package by
scanning.

### The records gathered (all already persisted by earlier steps)

`NodeArtifactStore.persist` takes the node's identity plus the records steps 7–9
produced — the same objects the pipeline already holds, not a re-fetch:

* `returns: PostCostReturns` (step 7) — the priced panel; the source of
  `signal_returns.parquet`, `ic_series.parquet`, `turnover_series.parquet`, and
  the `charges_budget` bit.
* `metrics: NodeMetrics` (step 8) — `ic_mean`, `ic_tstat`, `ir_standalone`,
  `turnover` → the tree `node` row.
* `profile: DecayProfile` (step 8) — `decay_profile.json`.
* `estimate: CapacityEstimate`, `attribution: RegimeAttribution` (step 8) —
  `regime_attribution.json`.
* `marginal: MarginalIR` (step 9) — `ir_marginal` → the tree `node` row.

Each is validated to name the *same* node and the *same* cost model as the
persistence (one node, one fee schedule — the same agreement check
`_capacity_store._check_pair_agreement` enforces, extended to the whole set).
The records are the values; the store re-reads the canonical rows from
`DATABASE_URL` to render the artifacts, so the artifact and the row cannot
disagree about what was computed (the precedent every store module states: "the
caller holding a campaign and a node artifact directory is what later writes the
file, reading this store through `X.load`").

### The artifact files (§9.2)

Rendered from the records, written through the `ArtifactWriter` seam. Each file
is one the artifacts member owns the encoding of; this member owns the content:

* System renders `signal_returns.parquet` from `returns.series` — the writer's
  Parquet encoding of the per-symbol, per-period, post-cost grid, the key
  artifact §9.2 says "enables ir_marginal".
* System renders `ic_series.parquet` from `metrics.ic_series` — the per-date IC
  series the writer encodes.
* System renders `turnover_series.parquet` from `returns` and `metrics` — the
  per-date equal-weight book fractional turnover, one entry per rebalance with a
  predecessor.
* System renders `decay_profile.json` from `profile.as_array()` — the
  five-position array, positional over `DECAY_HORIZONS`, `null` per un-measured
  horizon.
* System renders `regime_attribution.json` from `attribution` —
  `{stratum: {horizon: {dates, mean_post_cost_return}}}`, plus
  `unattributed_dates`.
* System renders `exec_trace.json` from the run's provenance —
  `{node_id, campaign_id, snapshot_name, evaluator_hash, cost_model, horizons,
  charges_budget, steps_completed: [7,8,9,11]}` — the deterministic fingerprint
  replay needs.

`code.py` is *not* rendered here: the signal's source is the node's to carry and
arrives from the caller (the evaluator executes `code`, it does not retain it —
§1 forbids replay from reaching the evaluator, and the code the agent wrote is
the tree member's `code_hash` territory). The caller passes it as an optional
`code` payload; when present it is written as `code.py`, when absent the
directory is still complete without it.

### The scalar metrics (§9.1 node row)

Assembled from the records into the `node` row's metric columns and handed to the
`TreeNodeWriter` seam. The evaluator supplies exactly the columns its records
measure; the tree member supplies the rest:

* `ic_mean`, `ic_tstat`, `ir_standalone`, `turnover` ← `metrics`
* `ir_marginal` ← `marginal`
* `cost_adjusted_ir` ← `returns` (the mean post-cost edge of the equal-weight
  book — `metrics`' panel mean, restated as the node's cost-adjusted IR axis)
* `perturb_stability` ← **absent** — this is step 10's tripwire metric, and step
  10 is not this step's input. It is carried as `None`, not defaulted, so the
  tree member writes the honest "not measured by this step" rather than a zero.

### The contract (the feature, not plumbing)

* **One node, one write, one transaction.** The artifact files and the `node` row
  are written under one call; a failure in either half leaves nothing half-written
  (the artifact writer's `flush` is the commit point, and the tree write precedes
  it; on a tree failure the artifacts are rolled back — the store refuses a node
  whose directory and row cannot both be accounted for).
* **Idempotent by `node_id`.** Re-persisting the same node refreshes the artifact
  files and the row's metric columns rather than appending a second node — the
  same assign-once-in-effect the stores use, and the same idempotency §14 demands
  of the workers this runs on. The `TreeNodeWriter` answers `(node_id, appended)`
  so a retry is distinguishable from a first write.
* **Refuses a half.** A node whose artifact directory exists but whose tree row
  does not (or vice versa) is refused on read-back — the two halves are one
  artifact's content, and a reader must never see one without the other (the
  defence `_capacity_store` applies to a capacity row without its attribution).
* **Stdlib-only, import-cheap.** No polars/pyarrow/lake/HTTP at import; the
  records arrive as values, the Parquet boundary is the injected writer's, and
  the replay path §1 forbids from reaching the evaluator.

## Implementation

### 1. `packages/evaluator/src/evaluator/_artifact.py`

* `ArtifactWriter` protocol (structural): `write_artifact(node_id, campaign_id,
  filename, payload) -> None` and `flush(node_id) -> None`.
* `render_decay_profile(profile) -> list[Optional[float]]` — the five-position
  array (delegates to `profile.as_array()`; kept here so the artifact spelling is
  the evaluator's, not the record's).
* `render_regime_attribution(attribution) -> dict` — `{stratum: {horizon:
  {dates, mean_post_cost_return}}}` plus `unattributed_dates`; strata sorted,
  horizons sorted, floats as reprs.
* `render_turnover_series(returns, metrics) -> dict[ISO date, float]` — the
  per-date equal-weight book fractional turnover, one entry per rebalance with a
  predecessor (the same arithmetic `compute_node_metrics` uses, restated for the
  artifact the PRD keeps in full).
* `render_exec_trace(...)` — the run's deterministic fingerprint.
* `ArtifactPayload` dataclass: `{filename, kind: "json"|"parquet"|"code",
  json_text?, code_text?}` — the content half, encoding-agnostic; the writer
  turns `json`/`code` text and the parquet source into bytes.

### 2. `packages/evaluator/src/evaluator/_persist_store.py`

* `NODE_PERSIST_TABLE` — a one-row-per-node bookkeeping table (`node_id`,
  `campaign_id`, `snapshot_name`, `artifact_dir`, `tree_written`, `artifact_
  written`, `created_at`) created idempotently on connect. This is the
  *orchestration* ledger: it records that feature 85's one-shot write happened for
  a node, so a retry is a refresh and a half-written node is discoverable. It is
  **not** the tree `node` table (the tree member's) and **not** the artifact
  files (the artifacts member's) — it is this step's own record that it did its
  job, the way `evaluator_identity` is feature 70's record that the hash landed.
* `NodePersistence` dataclass — `{node_id, campaign_id, snapshot_name,
  evaluator_hash, cost_model, metrics, marginal, profile, capacity, attribution,
  returns, artifact_paths, tree_appended, artifact_written}`.
* `NodeArtifactStore` — `resolve(env)`, `database_url`, `persist(...)`,
  `load(node_id)`, `_connect`. `persist`:
  1. checks the whole record set agrees on node + cost model;
  2. reads the canonical rows back from the evaluator's own stores
     (`load_signal_returns`, `load_node_metrics`, `load_decay_profile`,
     `load_capacity`, `load_marginal_ir`) — refusing a record the store does not
     hold, so the artifact is rendered from what actually persisted;
  3. renders each §9.2 file via `_artifact` and writes it through the
     `ArtifactWriter`;
  4. assembles the `node` row's metric columns and writes it through the
     `TreeNodeWriter`;
  5. records the orchestration row, in one transaction;
  6. refuses a half (directory without row, or row without directory).
* `persist_node(...)` — module-level spelling; `database_url` falls back to
  `DATABASE_URL`, a missing store refused by name.

### 3. `packages/evaluator/src/evaluator/__init__.py`

* Import and re-export the new public names (`_artifact`: `ArtifactWriter`,
  `render_decay_profile`, `render_regime_attribution`, `render_turnover_series`,
  `ArtifactPayload`; `_persist_store`: `NODE_PERSIST_TABLE`, `NodePersistence`,
  `NodeArtifactStore`, `persist_node`).
* Add them to `__all__` under a "Feature 85" comment block.
* No `@register` here — the service component registration is unchanged; this is
  a pipeline step, not a component.

### 4. Tests — `packages/evaluator/tests/test_persist.py`

* Happy path: `persist_node` writes the artifact files (via a fake in-memory
  `ArtifactWriter`) and the `node` row (via a fake `TreeNodeWriter`), and the
  rendered `decay_profile.json` / `regime_attribution.json` match the records.
* Idempotency: a second `persist_node` for the same node refreshes, does not
  duplicate; `tree_appended` is `False` on the retry.
* Agreement: a `metrics` naming a different node (or a `returns` under a different
  cost model) than the persistence is refused before any write.
* Half-written refusal: a store holding the records but an `ArtifactWriter` that
  fails on one file leaves no partial node; a `TreeNodeWriter` that reports no row
  is refused.
* `exec_trace` content and the `code.py` optional-write path.
* Missing-store refusal, unsupported-scheme refusal (the store contract).

The suite runs via `uv run --all-packages pytest packages/evaluator` (the
member's own suite — the repository-level gate collects only `tests/`; see
memory), against a per-test SQLite file with `DATABASE_URL` isolated (conftest).

## Out of scope (deliberately)

* The Parquet *encoding* and the artifact directory's on-disk path — the
  artifacts member's (features 170, 172), reached through the injected
  `ArtifactWriter`.
* The `node` table DDL, the identity/provenance columns, `code_hash`,
  `agent_model_id`, `created_at` — the tree member's.
* `perturb_stability` and the other tripwire metrics — step 10's (features 125+).
* `code.py` content — the caller's signal source, passed in optionally.
* Any migration — the orchestration table is `CREATE TABLE IF NOT EXISTS` on
  connect, the contract every store in this package states.

## Acceptance

- [ ] System renders all six §9.2 artifact files from one node's records and
      writes the §9.1 `node` row's scalar metrics, in one `persist_node` call.
- [ ] System renders `decay_profile.json` as the positional five-horizon array
      and `regime_attribution.json` as the per-stratum, per-horizon split.
- [ ] System makes the write idempotent by `node_id` — a retry refreshes, reports
      `appended=False`, and never duplicates the node row or an artifact file.
- [ ] System refuses a record set that disagrees on node or cost model before any
      write, and refuses a half-written node (directory without row, or row
      without directory) on read-back.
- [ ] System writes `code.py` only when the caller supplies the signal source.
- [ ] System keeps the new modules stdlib-only (no polars/pyarrow/lake/HTTP at
      import).
- [ ] Tests pass under `uv run --all-packages pytest packages/evaluator`.
- [ ] System exposes the new component spelling from
      `src/app/modules/evaluator/__init__.py`.
- [ ] The change edits no shared/order-sensitive files (module_loader,
      middleware, settings, migrations); `@register` stays only in `__init__.py`.
