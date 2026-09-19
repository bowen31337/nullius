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
| `nullius_ingest/backfill.py` | `GapBackfiller`, `SealGate` — the feature 26 REST backfill and seal gate |
| `nullius_ingest/exchange_info.py` | `ExchangeInfoVersionStore`, `DailyExchangeInfoWorker`, `parse_exchange_info` — the feature 24 versioned daily refresh |

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

## Gap backfill over REST and the seal gate (feature 26)

§15's failure table names the feed-side failure this member must recover —
*"WS gap / reconnect | Sequence-number gap | REST backfill the gap before
sealing the next snapshot"* — and feature 26 states the recovery:
*"System backfills a detected websocket gap over REST before the next
snapshot seals, which rejects a seal attempt while any gap stays open."*
Feature 25's detector has already named the hole (a `GapDetected` event in
a `GapEventLog`); feature 26 fills it and refuses to seal over one that
stays open. Two pieces, both seams:

- **The backfiller.** `GapBackfiller` reads the gaps the log holds, and for
  each still-open one fetches the missing rows over an injected REST call
  (`fetch(stream, first, last) -> rows`) and appends them to the stream's
  staging log — the same append-only area a live-feed cycle writes into.
  The row serialisation is injected too (`serialize(stream, rows, first,
  last) -> bytes`), so the member stays stdlib-only: the exchange's REST
  client and wire format are the stream workers' business, not this
  module's. A gap is filled by *exactly* the sequences it named: a short
  fetch (fewer rows than the hole) or an out-of-range row raises
  `GapNotFilledError` and leaves the gap open, so the seal is never gated
  on a fill that did not fill. A filled gap is not re-filled, so a retry
  over the same log does not re-fetch.

- **The seal gate.** `SealGate` wraps the sealing service (the `snapshot`
  member's `SnapshotService`) and forwards its `seal` — but refuses, with
  the service's own `SnapshotError` naming the stream and the hole, while
  the backfiller reports an open gap. Fill the gaps and the same gate lets
  the seal through. The gate reads the backfiller's open gaps, so backfill
  then seal is one flow: the §4.1 seal-on-schedule loop backfills, then
  seals. A gate wired without a backfiller forwards unconditionally — the
  honest "no gap tracking yet" default.

```python
from nullius_ingest import GapDetector, GapEventLog, GapBackfiller, SealGate
from nullius_ingest import StagingArea
from snapshot import SnapshotService

log = GapEventLog()
detector = GapDetector(on_event=log.record)

detector.observe("aggTrades", 1)
detector.reconnect("aggTrades")
detector.observe("aggTrades", 6)   # gap 2..5 detected into the log

staging = StagingArea.from_env()
backfiller = GapBackfiller(
    log=log,
    staging=staging,
    fetch=lambda stream, first, last: rest_client.fetch_range(stream, first, last),
    serialize=lambda stream, rows, first, last: parquet.encode(rows),
)
gate = SealGate(service=SnapshotService.from_env(), backfiller=backfiller)

gate.seal()                        # refuses: aggTrades 2..5 still open
backfiller.fill_stream("aggTrades")  # fetches 2..5, appends to staging
gate.seal()                        # seals: the hole is filled
```

The member stays stdlib-only: the arithmetic of "which holes are open and
are they covered" needs no REST client and no Parquet writer. The fetch,
the serialisation and the staging area are handed in; the seal gate is
handed the service. What this module adds is the glue the feature names
and no other module owns.

## Daily exchangeInfo filters, versioned (feature 24)

§4.1's table gives this stream the row *"`exchangeInfo` filters | REST |
daily | forever, versioned"*, and §13.2 states why the order path depends
on it — *"`exchangeInfo` filters (`LOT_SIZE`, `NOTIONAL`, `PRICE_FILTER`,
`stepSize`, `tickSize`) refreshed at startup and daily. Never hardcoded."*
A rule that says *never hardcode* is only enforceable if the fetched
constants are somewhere to be read, and only trustworthy if a later fetch
cannot quietly rewrite what an earlier one said. Feature 24 states both:

> System ingests exchangeInfo filters daily, persisting each fetch as a
> new version rather than overwriting the prior one.

- **Each fetch is a new version, structurally.** `ExchangeInfoVersionStore`
  appends `<lake>/staging/exchangeInfo/<version>.bin` via feature 28's
  `StagingArea`, so version `n`'s bytes are frozen the moment `n + 1`
  lands — the batch store refuses a second batch at a sequence it already
  holds. There is no code path that could overwrite a prior version.
- **A repeated fetch is still a new version.** The feature says *each*
  fetch is persisted, and suppressing an unchanged one would erase the
  difference between *the refresh ran and nothing changed* and *the
  refresh never ran* — exactly the distinction an operator needs when
  orders start being rejected for a stale tick size. `source_sha256` (over
  the filters) answers "did anything change?"; `carries_same_filters_as`
  answers it without diffing two documents.
- **Values are kept verbatim in the venue's spelling.** `"0.001"` stays
  `"0.001"`, never a `Decimal`: whether the venue said `"0.001"` or
  `"0.0010"` is a fact about the venue, and re-rendering it would make an
  audit unable to tell a venue change from our own lossy parse. The
  §13.2 constants read back off a version via `step_size`, `tick_size`,
  `min_qty`, `min_notional`.
- **Daily means a UTC calendar day, decided from the durable log.** A fetch
  is due when the last persisted version was fetched on an earlier UTC date,
  and immediately when the log is empty — §13.2's *"at startup and daily"*,
  where startup is just the first cycle over an empty store. A restart
  mid-day does not re-fetch; a process that was down across a boundary
  fetches on its next cycle rather than waiting for a timer. The cadence
  lives in the store, not in process memory, which is what makes it
  survive the restarts the deployment table calls *restart-safe*.
- **A failed fetch consumes no version.** The document is parsed and
  validated *before* anything is written, so a rate-limit body, an error
  page or a truncated response never appears in the log as a refresh that
  happened — and the next honest fetch still claims the same version
  number, leaving no hole.
- **Damaged bytes are refused, not parsed around.** A version file whose
  recorded hash disagrees with its document, or that is not readable as an
  envelope at all, raises `ExchangeInfoCorruptError`. A log the order path
  trusts for venue constants must not hand back a plausible-looking tick
  size assembled from bytes that changed.

The fetch is injected (`ExchangeInfoFetch`) — this member ships no HTTP
client, so the venue's auth, weight budget and pagination stay the
deployment's business and the module stays stdlib-only. It registers
itself as the `exchangeInfo` stream's worker, so importing the package is
the whole wiring, and a deployment wires its REST client with
`register_exchange_info_worker(fetch, registry=default_worker_registry())`
— passing the default registry explicitly, because the function defaults to
a *private* one so that wiring a fetch never silently replaces the
auto-discovered worker for every later composition in the process. Until
then the worker still composes and its cycle reports that stream's own
failure — feature 16's contract, where an unconfigured stream is a row in
the report rather than a component that fails to load.

```python
from datetime import datetime, timezone
from nullius_ingest import (
    DailyExchangeInfoWorker, ExchangeInfoVersionStore, parse_exchange_info,
)

store = ExchangeInfoVersionStore.from_env()      # <lake>/staging/exchangeInfo
worker = DailyExchangeInfoWorker(
    store, lambda: rest_client.get("/fapi/v1/exchangeInfo")
)

worker.is_due()                # True: empty log, startup fetch owed
result = worker.run_cycle()    # fetches, persists version 1
result.sequence                # 1 — the version, i.e. the log's watermark

store.current().render()
# 'exchangeInfo version 1 fetched 2026-03-01T06:30:00+00:00 carries 1
#  symbol(s) [BTCUSDT] sha256=...'

btc = store.latest_filters("BTCUSDT")
btc.step_size                  # '0.001'  — the venue's own spelling
btc.tick_size                  # '0.10'
btc.min_notional               # '10.00000000'

worker.is_due()                # False: today's version is already durable
```

The `versions()` log is what a seal copies into §4.2's `exchangeinfo/`
snapshot directory, so the history becomes part of the sealed,
content-addressed record rather than a sidecar a replay would have to
reconstruct from live requests — which it could not do honestly, since a
version describes what the venue said on a day that has passed.

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
