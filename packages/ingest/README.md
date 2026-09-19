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
