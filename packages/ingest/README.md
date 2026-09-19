# nullius-ingest — Market Data Ingest Workers

The `ingest` workspace member: app_spec.xml feature 16 —

> System isolates each stream class in its own ingest worker, which
> returns a per-stream failure rather than halting all ingest.

—and the data-layer rule it implements (docs/nullius-tech-architecture.md
§4.1): *"Separate worker per stream class."*

## The isolation contract

- **One worker per stream class, enforced.** `IngestSupervisor.add_worker`
  rejects a second worker for a class it already serves — the invariant
  the guarantee stands on, violated only by a wiring bug, so it fails at
  construction.
- **One thread per worker, per cycle.** `IngestSupervisor.run_cycle()`
  starts a dedicated thread per worker, so a slow or hung feed delays
  only its own stream.
- **A failure is data, never an exception.** Whatever a worker raises —
  up to and including `SystemExit` — is caught at that worker's boundary
  and returned as a `StreamFailure` naming that stream and no other.
  `run_cycle()` always *returns* an `IngestReport`; no stream's failure
  can halt another stream or the supervisor.
- **An optional cycle budget.** `run_cycle(timeout=...)` bounds the wait:
  workers over budget get a `WorkerTimeout` failure for their stream and
  the report returns anyway; the late result is discarded (a belated
  success after a reported failure would be a lie). Without a budget the
  supervisor waits for its workers — a REST backfill may legitimately
  run for minutes, and no default would be honest.

## Layout

| Module | Contents |
|---|---|
| `nullius_ingest/streams.py` | `StreamClass` — the six §4.1 stream classes; the unit of isolation |
| `nullius_ingest/worker.py` | `IngestWorker` protocol, `CycleResult`, `StreamFailure`, `StreamOutcome`, `FunctionWorker` |
| `nullius_ingest/supervisor.py` | `IngestSupervisor`, `IngestReport` |
| `nullius_ingest/registry.py` | `WorkerRegistry`, `register_worker` — the seam for later features |
| `nullius_ingest/watermark.py` | `SequenceStore` — the durable per-stream batch store feature 29 resumes from |
| `nullius_ingest/staging.py` | `StagingArea` — the append-only staging area feature 28 writes into |
| `nullius_ingest/schema.py` | `DeclaredSchema`, `ParquetBatch`, `SchemaDrift`, `SchemaValidatingWorker` — the feature 27 gate |
| `nullius_ingest/gaps.py` | `GapDetector`, `GapDetected`, `GapEventLog` — the feature 25 gap detection |

Stdlib-only by design, except `staging` (which resolves its lake root via
the factory's `find_workspace_root`, as the snapshot member does); stream
implementations declare their own dependencies in this member's
`pyproject.toml` when they land.

## Staging — the write side of the seal boundary (feature 28)

The `StagingArea` is where every ingest worker appends its output: an
append-only per-stream log under `<lake>/staging/<stream>/<seq>.bin`, one
batch per worker cycle. It is the write half of the §4.1 seal boundary —
what workers append here, the sealing service (the `snapshot` member) later
copies into an immutable snapshot; the evaluator never reads it, because
staging is a *sibling* of `snapshots/`, never inside it.

- **Append-only.** An append always claims `current + 1`; the shared
  batch-store mechanics refuse a second batch at a sequence already held, so
  staging is written once and copied by the seal, never overwritten.
- **Never on the evaluator mount path.** Constructing a `StagingArea` at, or
  beneath, a `snapshots/` directory raises `StagingRootError` — the
  mount-path guarantee enforced structurally on the write side, not hoped
  for. A mis-wired `LAKE_ROOT` cannot put ingest output where the evaluator
  reads.
- **Durable.** Each append is written to a temp file, `fsync`ed, then
  atomically renamed into place — the same commit feature 29's resume relies
  on — so a crash leaves a batch fully appended or absent, never torn.

```python
from nullius_ingest import StagingArea, StreamClass

area = StagingArea.from_env()          # <lake>/staging, resolved from LAKE_ROOT
batch = area.append(StreamClass.KLINES, payload=rows_bytes, rows=100)
batch.sequence                          # 1, then 2, 3, ... per stream
```

## The schema gate — rejecting drifted batches (feature 27)

§15's failure table names the exchange-side failure this member must
survive — *"Exchange schema change → Parquet schema validation → Halt
ingest for that stream; alert; patch"* — and feature 27 states the
detection: *"System rejects an incoming Parquet batch whose columns
drifted from the declared schema."* The gate is
`nullius_ingest/schema.py`:

- **A declaration per stream.** `DeclaredSchema.from_mapping(stream,
  {column: dtype})` fixes the columns that stream's batches must carry —
  no more, no less. It is *ours*, so a malformed declaration (empty,
  repeated, blank) is refused at construction, never at ingest time.
- **Drift is rejected, precisely.** A batch missing a declared column,
  carrying an undeclared one (an exchange *adding* a field is a schema
  change too), typing one differently (dtypes compare verbatim — the
  declaration is the canonical spelling), or naming one twice raises
  `SchemaDrift`, which carries the missing/unexpected/retyped/duplicated
  columns as structured data so the alert names exactly what changed.
  Order is *not* drift: Parquet columns are addressed by name.
- **The rejection happens before the write.** `SchemaValidatingWorker`
  composes the gate into a cycle: fetch the next batch past the
  watermark, gate it, and only then commit — a `StagingArea` is a batch
  store, so drifted bytes never reach the append-only log and the
  watermark never advances. After the schema is patched, the re-fetched
  batch claims the very sequence the drifted one would have; the log
  keeps no hole and no drift.
- **The halt is per stream, by inheritance.** The worker raises; the
  feature 16 boundary converts the `SchemaDrift` into that stream's
  `StreamFailure` (the alert) while every other stream keeps ingesting.

The gate needs no Parquet reader — it compares column sets, which is
exactly what a footer exposes — so the member stays stdlib-only; the
stream workers of features 17–24 feed it from their own readers.

## Gap detection on reconnect (feature 25)

§15's failure table names the feed-side failure this member must watch
for — *"WS gap / reconnect | Sequence-number gap | REST backfill the
gap before sealing the next snapshot"* — and feature 25 states the
detection: *"System detects a websocket sequence-number gap on
reconnect, which emits a gap_detected event naming the affected
stream."* The watcher is `nullius_ingest/gaps.py`:

- **A per-stream sequence watermark.** `GapDetector` holds the highest
  sequence observed per stream class; each websocket feed numbers its
  messages monotonically, so continuity is checkable — after `n`, the
  feed owes `n + 1`. Workers call `observe(stream, sequence)` per
  message and `reconnect(stream)` when the socket re-establishes.
- **A jump emits one event.** A message arriving past the owed sequence
  emits a `GapDetected` event naming that stream (and only that stream)
  and the inclusive range it skipped, with `on_reconnect=True` when the
  hole opened across the reconnect boundary. A skip within an open
  connection is detected the same way, flagged `on_reconnect=False` — a
  hole is a hole wherever it opened, and the backfill does not care
  where.
- **What is not a gap stays silent.** A stream's first-ever observation
  (no baseline to gap against), a contiguous tail after reconnect
  (nothing was lost), and a duplicate or replayed message (no forward
  hole; the watermark never regresses).
- **The event is emitted, not raised.** It is returned to the caller and
  handed to the `on_event` sink wired at construction; the standard sink
  is `GapEventLog`, a thread-safe append-only record (the supervisor
  runs one thread per worker, so a shared log receives events from
  several threads). Detection is *not* failure — §15's recovery is REST
  backfill, not a halt — so the detecting cycle still succeeds, the
  watermark advances past the hole (the tail after it is real data), and
  the hole lives on in the log: the seam feature 26's backfill and seal
  gate read.

```python
from nullius_ingest import GapDetector, GapEventLog

log = GapEventLog()
detector = GapDetector(on_event=log.record)

detector.observe("aggTrades", 1)   # first ever — no baseline, no event
detector.observe("aggTrades", 2)   # contiguous
detector.reconnect("aggTrades")    # the socket dropped and returned
detector.observe("aggTrades", 7)   # jumped 3..6 → gap_detected event

log.events("aggTrades")[0].render()
# 'gap_detected: aggTrades is missing sequences 3..6 (4 messages)
#  detected on reconnect'
```

The module stays stdlib-only: watching integers go up needs no
websocket client. The stream workers of features 17–24 own the
connections and call `observe`/`reconnect` from their own readers.

## Adding a stream worker (features 17–29)

1. Create `src/nullius_ingest/streams/<name>.py` with a worker exposing
   `stream_class` and `run_cycle()` (or wrap a callable in
   `FunctionWorker`).
2. Register a zero-argument **factory**:

   ```python
   from nullius_ingest import StreamClass, register_worker
   from nullius_ingest.worker import IngestWorker

   @register_worker(StreamClass.KLINES)
   def build_klines_worker() -> IngestWorker:
       return KlinesWorker(...)
   ```

3. Import the module from `nullius_ingest/__init__.py` so a scan fires
   the registration.

That is the whole wiring: `build_ingest()` composes one supervisor with
one worker per registered class, and the application factory calls it
when `create_app()` scans the workspace. No shared file is edited.

## Composition

Scanning this member runs `@register("ingest")`, so `create_app()` (from
`app.module_loader`) composes the supervisor as the app's `ingest`
component. The app-package seat is `app.modules.ingest`
(`src/app/modules/ingest/`), which exposes `ingest_component()` without
making the `app` package depend on any member at import time.

## Tests

```sh
uv run pytest packages/ingest/tests/ -q
# or, without uv: python3 -m pytest packages/ingest/tests/ -q
```

The suite needs no network and no lake: the isolation framework has no
I/O of its own to redirect.
