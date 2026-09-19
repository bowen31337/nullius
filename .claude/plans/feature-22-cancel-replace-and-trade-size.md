# Feature 22 — cancel-replace rate + trade-size distribution moments

## What the spec asks for

app_spec.xml, category "Market Data Ingest Workers":

> **22** (plugin `ingest`, depends_on 20) — System computes cancel-replace rate
> plus trade-size distribution moments, persisting them so a 90 day raw-diff
> expiry does not lose the derived history

docs/nullius-tech-architecture.md §4.1:

> …permanently persist derived book features at 1s resolution (depth at
> 5/10/25/50 bps each side, microprice, spread, OFI over several windows,
> **cancel/replace rate, trade-size distribution moments**).
>
> **The L2 retention decision is load-bearing.** … keep raw diffs for a rolling
> 90 days … and permanently persist derived book features at 1s resolution.

docs/alpha-engine-prd.md §(undercomputed free data):

> OFI, queue dynamics, **trade-size distribution, cancel/replace rates**,
> iceberg detection. Information advantage manufactured by compute.

**Scope is feature 22 only.** Feature 21 (microprice, spread, OFI) is a
*sibling* on the same `depends_on` parent and is not landed; I will not build
it. I depend on feature 20's derived tier, which **is** landed
(`book_features.py`), and feature 19's raw store beneath it.

## What exists today

- `book_features.py` (feature 20, landed, 446 tests green) — `BookState`
  reconstruction, `BookFeatureRow`/`Batch`/`Store`/`Worker` at
  `<lake>/staging/bookFeatures/<seq>.bin`, permanent, with the `rows_for`
  reader seam docstringed as *"the reader seam features 21/22 stand on"*.
- `book_diffs.py` (feature 19) — raw diffs, 90-day rolling `prune`, and the
  reader seam `records()` / `rows_in_window()`.
- **No trade tape anywhere.** `StreamClass.AGG_TRADES = "aggTrades"` is
  declared but feature 18 is **not landed** — no module, no wire format. No
  prior art for trade sizes exists in the repo (`grep` for
  `trade_size` / `TradeSize` finds nothing).
- `test_registry.py:107` asserts the default registry is exactly
  `{BOOK_DIFFS, BOOK_FEATURES, EXCHANGE_INFO, FUNDING}` — I must add to that set
  (inside my footprint).

## The two design forks (asked, unanswered → recommended option taken)

### Fork 1 — where trade sizes come from

**Decision: an injected trade-tape seam.** Feature 22 says "trade-size
distribution moments", but trades are not in L2 book diffs, and feature 18's
tape does not exist. Inventing a wire format for `staging/aggTrades/*.bin`
would collide with feature 18's parallel agent, who owns that format.

I define a small reader seam injected into the worker on exactly the pattern
this member already uses four times (`BookDiffFetch`, `FundingFetch`,
`ExchangeInfoFetch`): a `TradeTape` callable handing back venue-shaped trade
prints (`{"p": price, "q": qty, "T": ms, "m": is_buyer_maker}`), parsed into a
frozen `TradePrint`. The module ships no client — the venue's auth, rate limits
and pagination stay the deployment's business — and the auto-discovered worker
gets an `_unconfigured_tape` that raises, so an unwired deployment is *that
stream's* `StreamFailure` in the report, never a component that fails to load
(feature 16's contract). When feature 18 lands, a deployment wires
`register_trade_flow_worker(tape, ...)` or feature 18 hands over its store —
**no shared file edited, no format guessed.**

### Fork 2 — what counts as a cancel-replace

**Decision: a removal plus an add on the same side within one diff.** Each
level in each raw diff is classified `ADD` (new price), `UPDATE` (existing
price), or `REMOVE` (quantity `"0"`, or a price that vanishes). A
cancel-replace event is a `REMOVE` and an `ADD` on one side inside one diff —
the order left the book and re-entered elsewhere. The rate is
`cancel_replace_events / total_level_events` per (symbol, second). This is
crisp, exactly testable from raw diffs, and matches the microstructure
literature's reading. The rejected alternative — counting every removal and
size reduction — conflates a genuine modification with ordinary withdrawal.

## Design

### 1. `trade_flow.py` — the new stream module

`packages/ingest/src/nullius_ingest/trade_flow.py`, stdlib-only, mirroring
`book_features.py` one-for-one (record / envelope / content hash / bytes hash /
corrupt-bytes refusal / closing state / frontier / resume).

**The row.** `TradeFlowRow(symbol, window_start, cancel_replace_rate,
level_events, cancel_replace_events, trade_count, trade_volume, mean_size,
stddev_size, skew_size, kurtosis_size)`.

- All the computed numbers are `Decimal` in memory, rendered as canonical
  fixed-point strings only in `canonical()` — feature 20's exact convention, so
  the persisted row is the value, not a float that could drift on a re-render.
- Moments are **population** moments over the second's trade sizes: mean,
  population standard deviation, population skewness and excess kurtosis.
  A second with **zero or one** trade has no distribution: the sample moments
  are `None` (an honest absence, exactly as feature 20 emits no row for a
  one-sided book) while `trade_count` and `trade_volume` are still recorded.
- A second with **no level events at all** carries no rate either — the rate is
  `None` rather than `0`, because "no order activity" and "activity with no
  cancels" are different facts.

**The closing state.** `TradeFlowState` pairs the reconstruction's closing
`BookState` (reusing feature 20's class — this module *derives from* the
reconstruction, it does not re-implement it) with the trailing trade-size
window debounce state, persisted per record so a restart resumes without
re-reading raw diffs that may have left the 90-day window. That closing state
**is** the permanence argument: the derived history survives the raw expiry
because each record carries what the next cycle needs.

**The store.** `TradeFlowStore` over `StagingArea` at
`<lake>/staging/tradeFlow/<seq>.bin` — same append-only, permanent staging area
as every other stream, so the seal copies it and nothing expires it.

**The grid.** Reuses `FEATURE_SLICE` / `_floor_to_second` semantics at 1s,
matching feature 20: feature 22's moments are a 1s-resolution derived feature.

**The worker.** `TradeFlowWorker(store, diff_store, tape, *, clock=None)`.
One cycle: seed from the last record's closing state; consume raw diff records
past `to_raw_sequence`; classify levels and accumulate the cancel-replace
counts; consume trade prints in the window for the size moments; snapshot each
completed second past the frontier; persist one record with the closing state
and the advanced frontier. A no-new-data cycle appends nothing and reports
`sequence=0`. The clock is injected (`computed_at` is elapsed wall-clock fact;
§12 keeps wall-clock reads out of checked code).

**Registration.** `register_trade_flow_worker(store=None, diff_store=None,
tape=None, *, clock=None, registry=None)` — private registry by default — plus
`@register_worker(TRADE_FLOW_STREAM) build_trade_flow_worker()` with the
unconfigured tape that raises at cycle time.

### 2. A new stream class value

`StreamClass.TRADE_FLOW = "tradeFlow"` and its `staging` directory. This is a
**new** §4.1-adjacent row, which is a real decision: feature 22 is a *derived*
feature, and §4.1 already gives the derived tier exactly one row ("Book
features (derived) | computed from diffs | 1s | forever"). Two options:

- **(a) A new `tradeFlow` stream class.** Feature 22 becomes its own worker,
  its own failure row, its own staging log. Honours feature 16's "one worker
  per stream class" literally and keeps the two derived families independently
  restartable. Cost: it invents a stream-class value beyond the six §4.1 lists,
  and `test_streams.py:12` pins that set exactly.
- **(b) Piggyback on `bookFeatures`.** No new value, no set to widen — but two
  workers for one class, which `IngestSupervisor.add_worker` **refuses** by
  construction, and a re-registration would silently *replace* feature 20's
  worker, losing depth features. Not viable.

**Decision: (a).** (b) is structurally impossible without weakening the
supervisor's one-worker-per-class invariant, which is the guarantee feature 16
is built on. (a) costs one enum value and one exact-set assertion update, both
inside my footprint. I will document the new value as *feature 22's derived
stream*, sitting beside the derived book features in §4.1's table.

### 3. Wiring — no shared file touched

`packages/ingest/src/nullius_ingest/__init__.py` gains the imports (firing the
`@register_worker` decorator) and the `__all__` names. Per the plugin rule,
`@register` stays only in the package `__init__`, never a submodule.
`src/app/modules/ingest/__init__.py` needs no change. No app factory,
middleware, settings, router, entry-points table or migration is edited. The
new staging directory needs no registration — `StagingArea` maps every
`StreamClass` member automatically.

### 4. Tests to update (both inside my footprint)

- `test_registry.py:107` — add `StreamClass.TRADE_FLOW` to the expected default
  registry set, and update the comment.
- `test_streams.py:12` — the exact-set assertion on `StreamClass`. Adding the
  value there is the honest statement; I will add it with a comment naming
  feature 22 as its owner, rather than widening the assertion to a superset
  check, so the guard keeps working for the six §4.1 rows.

## Tests

`packages/ingest/tests/test_trade_flow.py` (new), in the house style —
narrative docstrings citing feature 22 and §4.1, one behaviour per test:

- **level classification**: an add, an update, a removal, a price that
  reappears; a removal-only diff; the totals sum to the diff's level count.
- **cancel-replace**: a remove + add on one side counts once; remove + add on
  *opposite* sides does not; two removes + one add counts once; a removal with
  no add is not a cancel-replace; the rate is exact over a known count.
- **an honest zero vs. an honest absence**: no level events ⇒ rate is `None`;
  level events with no cancel-replace ⇒ rate is exactly `0`.
- **trade-size moments**: mean/stddev/skew/kurtosis on a hand-computed sample;
  one trade and zero trades give `None` moments but a real count and volume;
  the moments are population, not sample (asserted against the arithmetic).
- **the row**: canonical fixed-point strings; `Decimal` in memory; a bad
  symbol / naive window / negative count each refused.
- **the log**: record 1 at `staging/tradeFlow/1.bin`; appends never overwrite;
  a restart resumes from the persisted closing state and re-reads no diff;
  damaged / unreadable / self-contradicting bytes raise, never parse.
- **the worker**: a cycle emits one row per (symbol, second) that carried a diff
  *or* a trade; a no-new-data cycle persists nothing and reports `sequence=0`;
  it satisfies `IngestWorker`, `stream_class is TRADE_FLOW`, and runs under
  `IngestSupervisor`.
- **the tape seam**: an unconfigured tape is that stream's `StreamFailure`
  while another stream keeps ingesting; a malformed print is refused before
  anything is written, so no sequence is consumed.
- **registration**: `TRADE_FLOW in default_worker_registry()`; the composed app
  supervises it; `register_trade_flow_worker` revises the same class, does not
  pollute the default, refuses non-callable collaborators.
- **the retention promise** (the feature's own clause): after the raw diffs for
  a window are *pruned away*, the derived row for that window is still readable
  from the trade-flow log — the 90-day expiry does not lose the derived history.

## Verification

- `UV_CACHE_DIR=.uv-cache uv run pytest packages/ingest/tests -q`
  (baseline today: 446 passed, 3.10 s)
- `UV_CACHE_DIR=.uv-cache uv run pytest -q` — the whole workspace, to confirm
  the new stream class and registry change break nothing outside the member.

## Decisions taken without an answer

1. **Trade sizes arrive through an injected tape seam**, not a guessed
   `aggTrades` wire format (feature 18 owns that format and is not landed).
2. **A cancel-replace is a removal + add on one side within one diff**; the
   rate is events / level events.
3. **`tradeFlow` is a new stream class**, because piggybacking on
   `bookFeatures` is refused by the supervisor's one-worker-per-class
   invariant.

Each is reversible and each is stated in the commit message.
