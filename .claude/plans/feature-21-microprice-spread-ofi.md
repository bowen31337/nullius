# Feature 21 — microprice, spread and windowed OFI

## What the spec asks for

app_spec.xml feature 21 (category "Market Data Ingest Workers", plugin
`ingest`, depends_on 20):

> System computes microprice, spread and order-flow imbalance over several
> windows, persisting each as a permanently retained book feature.

docs/nullius-tech-architecture.md §4.1 places it inside the derived-tier
sentence the L2 retention decision exists to make permanent:

> … permanently persist derived book features at 1s resolution (depth at
> 5/10/25/50 bps each side, **microprice, spread, OFI over several windows**,
> cancel/replace rate, trade-size distribution moments).

docs/alpha-engine-prd.md names the family as the point of the compute:
*"OFI, queue dynamics, trade-size distribution, cancel/replace rates …
Information advantage manufactured by compute."*

## What exists today

* Feature 19 (`book_diffs.py`) persists the raw L2 diffs on the 100ms grid
  under a rolling 90-day window, and exposes `BookDiffStore` as the reader
  seam.
* Feature 20 (`book_features.py`) owns the derived tier's first family: the
  depth ladder at 1s, `BookState` (the reconstruction), `FEATURE_SLICE`, and
  the persistence shape every derived family reuses (record, envelope,
  content hash, closing book, frontier, resume).
* Feature 22 (`trade_flow.py`) owns the third family and set the pattern for
  adding one: its own `StreamClass` value, its own module mirroring the
  persistence shape, `BookState.has_price` added as its read seam into
  feature 20.

## The design forks (no answer expected → recommended option taken)

### Fork 1 — what does "over several windows" attach to?

§4.1's punctuation attaches it to the OFI (*"microprice, spread, OFI over
several windows"*), and the semantics agree: microprice and spread are
*states* — a fact about the book at an instant, and the instant is the 1s
boundary; OFI is a *flow* — an amount of order activity integrated over an
interval, and an interval is what a window names.  **Taken:** a row carries
one microprice and one spread (measured at the closed boundary) and one OFI
per window in `OFI_WINDOWS = (1, 5, 10, 60)` — the slice, a near-term pair,
and the klines minute, so the ladder spans slice to bar; four windows,
mirroring feature 20's four-band depth ladder.  A windowed microprice (a
mean over the window) was rejected: it would average away exactly the
imbalance the microprice exists to catch.

### Fork 2 — which OFI?

The **best-level (top-of-book) Cont–Kukanov–Stoikov** OFI, computed event by
event off the reconstruction: on the bid side a best price that improves or
holds adds its new size and one that worsens subtracts its old size; the ask
side enters with the opposite sign.  An empty side is the price sent to its
sentinel, so sides appearing and vanishing measure rather than default —
including the stream's opening diff, which reads as the arrival imbalance
`bid_qty - ask_qty`.  The multi-level OFI was rejected for this tier: the
best level is where the literature's price impact lives, and the deeper
ladder is feature 20's depth bands, already persisted.

### Fork 3 — when is a second snapshotted?

Feature 20 snapshots a second at its **first** diff — a state feature only
needs the book to exist.  A flow feature must carry the whole window it
names, so feature 21 snapshots a second when it **closes**: the first diff of
a *later* second, or the end of the consumption pass.  Consequence: the
windows on a row compose exactly — the 60s window at `S` is the sum of the
sixty 1s windows it spans — and a late diff for a committed second folds into
the going-forward book and ledger without ever amending the committed row
(the log is append-only; a committed window is never re-opened).

### Fork 4 — how do windows survive restarts and the 90-day expiry?

A 60s window reaches 59s back, across cycle boundaries and across restarts,
and the raw diffs it would be re-summed from are 90-day-retained and then
gone.  **Taken:** each record carries, per symbol, an `OfiTrail` beside the
closing book — the per-second increments the trail still needs plus
`first_window`, the first second the symbol was ever observed — persisted as
`closing_flows` in the envelope and pruned each cycle to
`to_window - MAX_OFI_WINDOW + FEATURE_SLICE`.  `first_window` survives the
pruning, because coverage is a fact about where the observations began.  This
is the feature's permanence clause made mechanical: a restart after the raw
window has slid sums its windows from the derived log alone.

### Fork 5 — new stream class or piggyback on `bookFeatures`?

The supervisor's contract is one worker per stream class; a second
registration under `bookFeatures` would *replace* feature 20's worker.
**Taken:** `StreamClass.MICROSTRUCTURE = "microstructure"`, mirroring feature
22's `tradeFlow` precedent.

## Design

### `microstructure.py` — the new stream module

Mirrors `trade_flow.py`'s persistence shape one-for-one
(`MicrostructureError`/`ParseError`/`CorruptError`, `MicrostructureRow`,
`MicrostructureBatch`, `MicrostructureStore`, `MicrostructureRecord`,
`MicrostructureWorker`, `parse_microstructure`,
`register_microstructure_worker` with the private-registry default,
`@register_worker(MICROSTRUCTURE_STREAM) build_microstructure_worker`).
New machinery:

* `TopOfBook` — the four top-of-book facts, `None` per component for an
  empty side, price/size None-ness paired; `from_book` reads feature 20's
  seams.
* `ofi_increment(before, after)` — the CKS increment, exact `Decimal`.
* `OfiTrail` — `observe` (floors, accumulates, moves `first_window` back on
  late buckets), `sum_over` (`(S-W, S]`; `None` unless
  `first_window <= S-W`; covered-and-silent is exact `Decimal(0)`),
  `prune`, `snapshot`/`from_snapshot` (both keys required — a missing
  `first_window` would silently un-cover every window).
* `MicrostructureRow` — microprice/spread plus the four facts they were
  computed from (feature 20's reference-price precedent) and the OFI map
  with exact-window-key validation and the microprice existence rule
  (`None` ⟺ best sizes total zero).
* Worker cycle — seed (closing books *and* trails), consume raw records past
  `to_raw_sequence` folding each diff's increment around the book change,
  close each symbol's open second when a later second arrives or the pass
  ends, then prune and append one record.  No fetch seam: the input is the
  internal raw store, so the stream composes fully configured.

### `book_features.py` — two read seams

`BookState.best_bid_quantity()` / `best_ask_quantity()`, mirroring feature
22's `has_price` precedent: `None` exactly when the matching best price is
`None`.

### Wiring — no shared file touched

`streams.py` gains the enum value (and its derived-family docstring now lists
all three); `nullius_ingest/__init__.py` gains the import block, `__all__`
names and module-list entry — all inside the member, all auto-discovered.

## Tests

`test_microstructure.py` (102 tests): grid/constants; `TopOfBook` pairing;
twelve hand-computed increment cases; trail accumulation, tiling
`(S-W, S]`, uncovered-`None` vs covered-silent-`0`, prune, snapshot round
trip and refusals; row validation, canonical null-vs-zero rendering,
microprice recomputability and both lean directions; batch canonical
hashing; store append-only, round trips (rows, closing book, closing trail),
paths, corruption refusals incl. a damaged trail; worker cycles — deferred
close, the 61-second alternating-size window composition
(OFI(60) = Σ OFI(1) = 0), the coverage ladder (5s covered from T0+5, 60s
from T0+60), one-sided absence, sentinel-measured second side, late diffs
folding without re-emission and entering only later windows, frontier/restart
behaviour, cross-restart window sums from the persisted trail, prune
survival, and the restart-after-prune window answered from the derived log
alone; registration, supervisor composition, the composed app, and the
needs-no-venue-fetch property.

Also: two `BookState` seam tests in `test_book_features.py`; the derived
sets in `test_streams.py`; the default-registry set in `test_registry.py`.

## Verification

* `UV_CACHE_DIR=.uv-cache uv run pytest packages/ingest/tests -q`
  → 651 passed (549 baseline + 102 new).
* Whole-workspace `uv run pytest -q` — see the session log; nothing outside
  the member is touched by the change set.

## Decisions taken without an answer

1. Windows attach to OFI (Fork 1); `OFI_WINDOWS = (1, 5, 10, 60)`.
2. Best-level CKS OFI with empty-side sentinels (Fork 2).
3. Close-of-second snapshotting, so windows compose (Fork 3).
4. `closing_flows` trail persisted and pruned per record (Fork 4).
5. New stream class value `microstructure` (Fork 5).
6. Coverage is conservative by one bucket — `first_window <= S-W` — because
   the first observed second's increments were measured against an unseeded
   book, so a window is only vouched for when the ledger saw the book before
   the window's first event.
