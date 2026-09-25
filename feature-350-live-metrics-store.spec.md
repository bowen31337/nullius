# Feature 350 — Live metrics store

**Feature index:** 350 (depends on 341)
**Shape:** plugin (`ops`)
**Feature sentence (app_spec.xml):** *System persists live metrics covering information coefficient ratio, fill cost in basis points, order reject rate and feed staleness.*

350. System persists live metrics covering information coefficient ratio, fill cost in basis points, order reject rate and feed staleness
Description: The ops member adds one member-owned table, `ops_live_metrics`, in the relational store `DATABASE_URL` names — the same "single Postgres metrics table" allowance docs §16 permits and the surface feature 341 already resolves. It is the persistence half of §16's live-metrics line ("live-vs-backtest IC ratio, realized vs. modeled fill costs in bps, order reject rate, WS staleness, rate-limit headroom"), narrowed to the four the sentence names. The store accepts a `(metric, value)` pair handed over already measured and validates the value against the shape the metric's name fixes; it computes none of the four, reaching none of the four source members. Delivered as one store module `ops.live_metrics` plus its app-package seat `app.modules.ops.live_metrics`, the two-file shape feature 267 takes. No route, no dashboard, no schema file: the table is brought up idempotently on first connect, so no revision is written and no shared schema is touched.
Depends on: 341

## 1. The sentence, read as a feature

The verb — *"System persists"* — is the ops member's half and the whole of what this feature adds. It is docs §16's *"single Postgres metrics table"* allowance: a relational store, `sqlite:///` on a single machine, `CREATE TABLE IF NOT EXISTS` on connect, one member-owned table. The ops member already owns that surface — feature 341's route reads feature 267's `scoring_fdr_deploy` rows through the scoring member rather than re-spelling the reweighting, and the member's own docstring reserves the research-metrics row as *"the ops member's (feature 344 …)"*. Feature 350 is the next row: the ops member holds the table the *live* metrics land in, the ones §16 lists separately from the per-campaign research figures.

The list — information coefficient ratio, fill cost in basis points, order reject rate, feed staleness — is the enforceable property, and it is the larger half. The four are not free-form numbers; each has a shape the sentence and the members that measure them fix:

- **`ic_ratio`** — the live-vs-backtest information-coefficient ratio. An information coefficient is a correlation, bounded `[-1, 1]` by construction (the evaluator's `ic_mean` is one; the scoring member's `IC_BOUND` pins the bound), so the ratio of two of them is a finite real with no sign bound — a live IC that flipped sign from backtest answers a negative ratio, and that sign is the fact.
- **`fill_cost_bps`** — realized vs. modeled fill cost, in basis points. Basis points is the unit feature 340's `forward_cost_reconciliation` already persists in, and a cost can be negative (price improvement), so this is a finite real with no sign bound — the unit is the column's own name, exactly as 340 states.
- **`reject_rate`** — the order reject rate. A rate is a fraction of submissions, bounded `[0, 1]` — the router member's `SubmissionHealth` answers `rejected / total`, and a fraction of submissions cannot exceed one.
- **`feed_staleness_s`** — feed staleness, a WS-age duration in seconds. A duration is a non-negative finite real — the risk member's staleness halt (docs §16 line 724: "Data feed staleness > threshold") measures the same quantity this row records.

### 1.1 What this feature is not, and why that is the feature rather than a gap

It is **not a reader of any of the four source members.** The IC ratio is the scoring/evaluator members' derivation (feature 337's forward IC retention, the evaluator's `ic_mean`); the fill cost is feature 340's `reconciled_fill_costs`; the reject rate is the router member's `SubmissionHealth.rejection_ratio`; the staleness is the risk member's halt quantity. A store that reached into any of those members to *compute* its metric would be a second spelling of a derivation that member already owns, and would couple the metrics table's construction to four siblings the factory scan could not promise are on `sys.path` at build time. So the store **computes none of the four**; it accepts a `(metric, value)` pair handed over already measured — the same "hand over, never derive" barrier feature 267 states for its pair and 340 states for its cost — and validates the value against the shape the metric's name fixes.

It is **not a route or a dashboard.** Feature 342's lamps and 343's coverage are the category's *expose* features (GET /metrics/…); 351's dashboard is the render. Feature 350's sentence is *persists*, not *exposes* and not *renders*, so it adds no route, no component the seat's `EXPECTED_EXPORTS` would need to grow for a route, and no screen. It is the table the expose-and-render features could later read from — the persistence half, spelled once.

It is **not rate-limit headroom.** §16's live-metrics line names five; the sentence names four. The one the sentence leaves out — rate-limit headroom — is deliberately out of scope: a feature is the sentence it lands, and a fifth metric a caller could not validate against a named source member would be a metric nobody measured. The closed set of four is the feature.

It is **not a new field on any of the four owners' tables.** The IC ratio does not land in `forward_record`, the fill cost is not a column on the reconciliation row, the reject rate is not a `SubmissionHealth` field, the staleness is not a halt-event column. Each of those tables has its own subject and its own owner; landing a live metric in one of them would need an allocation or a back-door column nobody specified. The four live metrics land in the ops member's *own* table, keyed by metric and instant — the same move feature 267 makes (`scoring_fdr_deploy` is its own table, not a `node` column) and 340 makes (`forward_cost_reconciliation` is its own table, not a `forward_record` column).

The one thing this feature *does* that nothing else does: it makes the ops member's metrics table real — a member-owned `ops_live_metrics` table, a `record` verb that validates the metric name against a closed set of four and the value against that metric's shape, and `latest`/`series` reads that answer what was written without recomputing it. The persistence is the law; the four names are its scope.

## 2. The persistence, made structural

The sentence's *persists* is the only verb, so the feature is delivered as **one store** in a new module `ops.live_metrics`, plus its seat in the app package namespace — the same two-file shape feature 267 takes (`scoring._fdr` + `app.modules.scoring.fdr`).

### 2.1 The table: `ops_live_metrics`

Member-first, in the relational store `DATABASE_URL` names, created idempotently on connect so no migration step is needed and no shared schema file is touched. Named `ops_live_metrics` — member (`ops`) first, subject (`live_metric`) second — the way `scoring_fdr_deploy` and `forward_cost_reconciliation` are named, so a reader of the store can tell whose research row it is holding.

One row per `(metric, logged_at)`. The key is that pair: `metric` is the closed-set name (TEXT), `logged_at` is an ISO 8601 UTC instant (TEXT, second resolution, string order chronological) — the same label shape feature 267's `computed_at` takes, so the trend read orders by it. The four values are four nullable `REAL` columns — `ic_ratio`, `fill_cost_bps`, `reject_rate`, `feed_staleness_s` — each NULL except the one the row records. A row records **exactly one** metric's value: the insert names the one column and leaves the other three NULL by shape, so a row is never two metrics at once and the `(metric, logged_at)` key never collides across metrics. This is the same "one metric, one column, the others NULL" discipline feature 267's store takes for its own columns and the migration-tree convention states for REAL columns written NULL by insert shape.

`logged_at` is the row's one instant — the key half and the label the series read orders by (TEXT, ISO 8601 UTC, second resolution, string order chronological), the same shape feature 267's `computed_at` takes: it defaults to now (UTC, second resolution) and a caller that measured at a known instant passes it, so the row's label matches the measurement rather than the write.

### 2.2 The verb: `record(metric, value, *, logged_at=None)`

The one write. `metric` is one of the four closed-set names; `value` is the already-measured figure handed over (the owner's number, never recomputed here); `logged_at` defaults to now (UTC, second resolution) and a caller that measured at a known instant passes it so the row's label matches the measurement.

The ask is validated whole **before a connection is opened** — a malformed ask never reaches the store, the ordering feature 267 states for every write:

- an unknown `metric` — not one of the four — is refused by name, because a value stored under a name the table does not know is a metric nobody measured and there is no column to put it in;
- a `value` that is not a finite real is refused (bool refused before real, the family's law), because none of the four is a count or a flag;
- a `value` outside the metric's own bound is refused — `ic_ratio` and `reject_rate` inside their correlation/rate bounds, `fill_cost_bps` and `feed_staleness_s` finite with the sign the unit allows — because a value that could not be the metric it claims is a corruption at the door.

The write is an upsert on `(metric, logged_at)`: a re-run of the same measurement at the same instant refreshes the value, never appends a doubled row.

### 2.3 The reads: `latest()` and `series(metric)`

- `latest()` answers the most recent value of each of the four, as a mapping `{metric: value | None}` — one row per metric, the newest `logged_at`. A metric with no row answers `None` (an absence, never `0.0` — a zero is a measurement, and a live metric that was never recorded is not a zero). This is the read a later dashboard or expose-route would draw the four tiles from.
- `series(metric)` answers one metric's rows oldest-first — `[(logged_at, value), ...]` — the trend a later reader watches the live metric across.

Neither read recomputes a figure; each answers what was written, the store stance feature 267 takes toward its own rows.

### 2.4 The store, addressed the way every member store addresses it

`DATABASE_URL`, `sqlite:///` on a single machine, schema created idempotently on connect (`CREATE TABLE IF NOT EXISTS`). The class resolves its path lazily, so constructing one performs no I/O — composition-time work must not touch the disk. The ask is validated whole before a connection is opened. The store's own failures (no configured `DATABASE_URL`, an unspeakable scheme, a locked or unwritable database) surface in the ops member's vocabulary (`OpsError` subclass) with the original chained, never swallowed — a live metric that measured but never landed is the state this feature exists to rule out, exactly as a figure that measured but never landed is feature 267's.

`resolve()` answers the store `DATABASE_URL` names, or `None` when it names none — the degrade-don't-break stance every store-bound builder here takes.

## 3. The component beside the route and the dashboard

This is the ops member's third component name and its second store-bound one — the growth the member's own registration reserved when feature 341 landed and the app-package seat reserved beside it ("344-347's and 350's persisted metrics arrive as this member's own tables"). `OPS_LIVE_METRIC_COMPONENT_NAME` (`ops-live-metric`) registers a builder that resolves `DATABASE_URL` and answers `None` when nothing names a store — the same stance the scoring member's `build_fdr_deploy_store` and the route's own builder take: the factory builds every component on every `create_app()` call, and a deployment without a relational store must still compose. *No store is configured* and *the store is broken* are different facts, and only the second may ever be quiet.

The store is reached from the app package through a sibling seat (`app.modules.ops.live_metrics`), the same accessor-per-component shape `app.modules.scoring.fdr` takes for feature 267's store.

## 4. The refusal vocabulary

One new `OpsError` subclass — `LiveMetricError` — for the store's refusals, split by *where the refusal happens* the way the member's error docstring states (a surface per subclass; the store is this feature's surface). A caller that catches `LiveMetricError` catches a metric that could not be persisted or read, with the original chained — never taken down by `sqlite3.Error` from a module the store's caller never imported, never answered around with a fabricated value.

## 5. What the feature deliberately does not touch

No edit to `app_spec.xml` (feature 350's sentence is already there). No route, no dashboard, no `EXPECTED_EXPORTS` growth for a route (the seat grows two composition accessors and the component name, as the fdr-deploy seat already does for its store). No import of the four source members at module scope or builder time — the value is handed over, and the metric name is validated against the closed set, so the store stays stdlib-only and import-cheap, and composing it performs no sibling import and no I/O. No migration: the schema is created idempotently on connect, as every member store in this workspace does.

## 6. Testing plan

A real SQLite file in a `tmp` directory — the persistence law is honestly testable only against the thing it persists into. The suite pins:

- **the round trip** — what `record` writes, `latest`/`series` read back, per metric, each value to the bit;
- **the one-metric-per-row law** — recording `ic_ratio` leaves the other three columns NULL, and a second metric at the same instant is a second row, not a widened first;
- **the key** — `(metric, logged_at)`, the upsert refresh-not-append on a re-run at the same instant;
- **the ordering of the ask** — unknown metric, non-finite value, and an out-of-bound value for each metric are all refused before a connection is opened (no database file appears);
- **each metric's shape** — `ic_ratio`/`reject_rate` refused outside `[-1, 1]` / `[0, 1]` and honoured at both ends; `fill_cost_bps`/`feed_staleness_s` honoured negative/zero and refused non-finite; bool refused before real;
- **the store's own failures** — no `DATABASE_URL` (resolve → None), an unspeakable scheme (refused at first use, not construction), a database that will not open (surfaced chained in `LiveMetricError`);
- **construction performs no I/O** — the URL is held, the path resolved lazily, the file appears at the first verb;
- **the component and the seat** — the builder resolves the store or answers None, the seat's `EXPECTED_EXPORTS` grows by exactly the new names, the three spellings of the component name agree, and composing the store touches no disk.
