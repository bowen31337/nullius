# Feature 19 — ingest L2 book diffs at 100 ms, rolling 90-day retention

## What the spec asks for

app_spec.xml, category "Market Data Ingest Workers":

> **19** (plugin `ingest`, depends_on 16) — System ingests L2 book diffs at 100
> millisecond resolution, persisting raw diffs under a rolling 90 day retention
> window

docs/nullius-tech-architecture.md §4.1:

> | L2 book diffs | WS @100ms | continuous | **rolling 90 days only** |
>
> **The L2 retention decision is load-bearing.** Raw diff streams for a
> 100-symbol universe run roughly 50–200 GB/month uncompressed. Storing them
> forever is a self-inflicted infrastructure problem. Instead: keep raw diffs
> for a rolling 90 days … and permanently persist derived book features …

Scope is **feature 19 only**: the raw-diff stream and its retention window.
The derived 1 s book features (20/21/22) are separate tasks that build on this.
I will provide the small reader seam they need (read the raw rows of one
window) but will not compute any derived feature.

## What exists today

`StreamClass.BOOK_DIFFS = "bookDiffs"` already exists (`streams.py:40`) with
the docstring "L2 book diffs at 100ms, kept under a rolling 90-day window" —
declared by feature 16, never implemented. No module serves it.

The two landed stream modules are the template:

- `funding.py` — the closest analogue: a store over `StagingArea` at
  `<lake>/staging/funding/<seq>.bin`, one record per cycle, verbatim venue
  spellings, envelope + `source_sha256` + `payload_sha256`, corrupt bytes
  refused, a worker with an injected fetch and injected clock, `@register_worker`
  self-registration, and a `register_*_worker` deployment path that defaults to
  a *private* registry.
- `exchange_info.py` — same shape, an append-only version log.

And `staging.py` (feature 28) owns the append-only area: **append only, nothing
in the system ever expires it**. `funding.py`'s docstring leans on that
explicitly, contrasting itself with the L2 stream it names. So feature 19 is the
first thing in this system that must *remove* data — that is the genuinely new
problem here, not the ingest.

## Design

### 1. `StagingArea.retire` — the retention window's write (`staging.py`)

Retention deletes. A store cannot do that by reaching into the staging tree
itself without forking the durability mechanics and the lake-root resolution, so
the removal seam belongs on `StagingArea`, next to `append`:

```
retire(stream, sequences) -> tuple[int, ...]
```

- Unlinks the whole `<seq>.bin` for each named sequence, drops it from
  `_committed`, and fsyncs the directory (mirroring `_persist`, so the removal
  is as durable as the append was).
- **Whole batches only.** A batch is retired entirely or not at all. A byte that
  survives is never rewritten — so append-only survives retention, and the seal
  (which walks whatever is present) sees a batch present or absent, never torn.
- **Refuses a sequence that is not committed**, with `ValueError` — matching
  `SequenceStoreBase.commit`'s existing refusal of a duplicate. Silently
  ignoring would let a caller believe it expired something it did not.
- **Refuses to retire the newest committed batch**, with `ValueError`. This is
  load-bearing: the watermark is *derived from the files on disk*, so retiring
  every file would let a later `append` reuse a sequence the log has already
  spent, and `record_at(1)` would start answering with a different record.
  Keeping the newest batch pinned keeps the sequence space monotonic across
  restarts with no separate watermark file.

The module docstring's "never rewritten" claim is amended precisely: *append-only
means a committed batch is never rewritten; a batch may be **retired** whole by a
stream whose retention window has passed it.* `append` is untouched, so feature
28's behaviour is unchanged for every existing stream.

### 2. `book_diffs.py` — the stream module (new)

`packages/ingest/src/nullius_ingest/book_diffs.py`, stdlib-only, matching
`funding.py`'s structure one-for-one.

**The grid — where "100 millisecond resolution" is made exact.**

- `SLICE_MILLISECONDS = 100`, `SLICE = timedelta(milliseconds=100)`
- `align_to_window(moment) -> datetime` — floors an aware datetime onto the
  100 ms grid (exact integer arithmetic on epoch microseconds; no float).
- `window_start_for(event_time_ms) -> datetime` — the window a venue event time
  falls in, from epoch milliseconds.

Every raw diff is stamped with the window it fell in. `1234 ms → 1200`,
`1299 → 1200`, `1300 → 1300`: the grid is exact, not rounded.

**The raw row.** `BookDiffRow(symbol, window_start, first_update_id,
last_update_id, bids, asks)`, with `PriceLevel(side, price, quantity)` keeping
the venue's own string spelling verbatim — the same rule funding and
exchangeInfo follow, and here it matters twice over because this is *raw* data:
a `quantity` of `"0"` is a level *removal*, kept as the venue sent it rather
than filtered, and a price is never re-rendered through a float.

**The batch.** `BookDiffBatch(rows)` — one cycle's raw diffs. Several rows may
share a `window_start` (a symbol genuinely receives several diffs inside one
100 ms window) and the batch makes no completeness claim about a window: it
records what arrived, and a reader unions by `window_start` across batches.

**The parse.** `parse_book_diffs(document)` accepts a single venue diff mapping,
a list of them, a wrapper (`{"diffs"|"data"|"events": [...]}`), JSON bytes/str,
or an already-built batch. Tolerant about extra venue fields, strict about the
shape this system owns. Notably **a diff with no venue event time is refused**:
without it the row cannot be placed on the grid, and using our own clock would
invent a fact about when the venue saw the book — the parse fails loudly instead.
Also refused: no symbol, `last_update_id < first_update_id`, a level that is
neither `[price, qty]` nor `{"price","quantity"}`, a non-scalar level value, a
duplicate price within a side, and an empty batch.

Two hashes, as in funding: `source_sha256` over the batch's canonical bytes
(rows sorted, keys sorted, tight separators — so *did the book change?* is
answerable and a mere reordering does not move the hash), `payload_sha256` over
the bytes written (the file's identity, what the seal's MANIFEST will record).

**The store.** `BookDiffStore` over `StagingArea`, records at
`<lake>/staging/bookDiffs/<seq>.bin` — §4.1's stream, in the same append-only
area as funding and exchangeInfo, so the seal copies it the same way.

- `record(document, *, written_at)` — parse first, then append as `current + 1`.
  A failed parse consumes no sequence.
- `records()`, `current()`, `previous()`, `record_at(seq)` — verified reads;
  damaged bytes raise `BookDiffCorruptError` rather than parsing into a
  plausible-looking book.
- `row_count()`, `windows()`, `rows_in_window(symbol, window_start)` — the small
  reader seam feature 20 needs: the raw rows of one window, unioned across
  batches.

`written_at` (our persistence instant) is deliberately named and documented
apart from `window_start` (the venue's event time): the retention window is
decided from the former, the 100 ms grid from the latter, and conflating them
would let our own lag decide which window a diff belongs to.

**The retention window.**

- `RETENTION_DAYS = 90`, `RETENTION = timedelta(days=90)`
- `BookDiffRecord.window_end` = newest row's `window_start + SLICE`.
- Expired iff `window_end <= now - RETENTION` — so a record is dropped only when
  it is *wholly* outside the window. A batch straddling the cutoff is retained
  whole; retention over-keeps by at most one batch and never splits one (splitting
  would rewrite bytes and break both append-only and content addressing).
- `prune(now) -> RetentionReport{now, cutoff, retired, rows_retired, retained}` —
  records are time-ordered, so prune reads from the oldest and **stops at the
  first retained record**: in steady state it walks one or two records, not the
  window. It never asks `retire` for the newest sequence (the watermark anchor).
- `expired_sequences(now)`, `retained(now)` — the observability queries the seal
  and an operator read, without deleting anything.
- Wall-clock reading stays out of the store: `now` is a parameter, driven by the
  worker's injected clock (§12).

**The worker.** `BookDiffWorker(store, fetch, *, clock=None)`, one cycle:

1. **Prune** — retention is a property of elapsed time, not of ingest health, so
   the window advances even on a cycle whose fetch then fails.
2. **Fetch** — the injected `BookDiffFetch`; this member ships no websocket
   client, so the venue's auth, rate limits and reconnect policy stay the
   deployment's business (§15's gap/reconnect row is feature 25/26's).
3. **Record** — parse-then-append, so a truncated or erroring flush is that
   stream's failure and never a batch.

`last_retention()` exposes the report from the last cycle. One cycle = one batch
holding however many slices the flush carried, so 100 ms resolution costs rows,
not files: at a ~1 s cycle that is ~86k files/day, against ~864k for a
file-per-slice (~77M over the window) — the infrastructure problem §4.1's
retention note exists to state.

**Registration.** `register_book_diff_worker(fetch, store=None, *, clock=None,
registry=None)` (private registry by default, like funding's) plus
`@register_worker(BOOK_DIFFS_STREAM) build_book_diff_worker()` with an
`_unconfigured_fetch` that raises at cycle time — so an unwired deployment is
that stream's `StreamFailure` in the report, not a component that fails to load.

### 3. Wiring — no shared file touched

`packages/ingest/src/nullius_ingest/__init__.py` exports the new names and
imports `.book_diffs` so the `@register_worker` decorator fires. That is the
whole wiring; `src/app/modules/ingest/__init__.py` needs no change (it asks the
factory for the component by name). No registry, router, entry-points table or
app factory is edited.

### 4. Two existing tests need a mechanical update

Adding a third registered stream makes two positional assertions wrong. Both are
inside my footprint (`packages/ingest/**`):

- `test_registry.py:107` asserts the default registry is exactly
  `{EXCHANGE_INFO, FUNDING}`. Add `BOOK_DIFFS` and update the comment.
- `test_funding.py:615` and `test_exchange_info.py:698` take
  `default_worker_registry().build_workers()[0]` — sorted by stream class, so
  `[0]` is now the *book-diffs* worker. They would still pass by accident
  (every store has `.staging.root` and all resolve the same lake), which is worse
  than failing. I will select by stream class in those tests so they assert about
  their own worker, which is what they mean and what stays true when 17/18 land.

## Tests

`packages/ingest/tests/test_book_diffs.py` (new) and additions to
`test_staging.py`, in the house style — narrative docstrings citing the feature
number and §4.1, one behaviour per test:

- **the 100 ms grid**: same-window events share a `window_start`; events 100 ms
  apart are adjacent; `1234/1299/1300` ms floor exactly; an unaligned datetime is
  floored and an aligned one is not; a diff with no venue event time is refused.
- **raw fidelity**: price and quantity kept verbatim, `quantity="0"` retained as
  a removal; scalar spellings; reordering does not move the content hash;
  changing one quantity does.
- **strictness**: no symbol, `last < first`, bad level shapes, container level
  value, duplicate price per side, empty batch, non-JSON — each refused before
  anything is written, so no sequence is consumed.
- **the log**: first cycle is record 1 at `staging/bookDiffs/1.bin`; a later
  cycle never rewrites an earlier record's bytes; restart resumes past the
  durable log; damaged / unreadable / self-contradicting bytes raise rather than
  parse; `record_at` of a never-recorded sequence is `None`.
- **retention**: inside the window retained; wholly older than 90 days retired
  (file gone, `records()` shrinks); the exact boundary retained; one slice past
  it retired; a batch straddling the cutoff retained whole rather than split;
  prune twice is idempotent; the report names what went and how many rows; a
  restart sees only retained records and still appends past the high-water mark;
  a naive `now` refused.
- **the sequence anchor**: prune never retires the newest batch, so with
  everything expired the sequence still advances monotonically and no number is
  ever reused.
- **the worker**: a cycle persists and reports rows/sequence; a cycle prunes;
  retention advances even when the fetch fails; mis-wired collaborators refused;
  it satisfies `IngestWorker`, `stream_class is BOOK_DIFFS`, and runs under
  `IngestSupervisor`.
- **retire (`test_staging.py`)**: unlinks whole batches and drops them from the
  watermark view; refuses an uncommitted sequence; refuses the newest batch;
  durable across a restart; retains surviving batches' bytes untouched; empty
  input is a no-op.
- **registration**: `BOOK_DIFFS in default_worker_registry()`; the composed app
  supervises it; `register_book_diff_worker` revises the same class, does not
  pollute the default, refuses a non-callable fetch; an unconfigured fetch is
  that stream's failure while another stream keeps ingesting.

## Verification

- `uv run --no-sync pytest packages/ingest/tests -q` — the member's suite.
- `uv run --no-sync pytest -q` — the whole workspace (baseline today: 765 passed,
  2.77 s), to confirm the registry change breaks nothing outside the member.

## Decisions taken without an answer

The three shape questions below went unanswered, so I am taking the recommended
option on each; each is reversible and I will say so in the commit.

1. **Retention deletes through a new `StagingArea.retire`**, not a private tree.
2. **One batch per cycle carrying many 100 ms slices** — resolution lives in the
   rows, not the file count.
3. **The worker prunes at the top of each cycle**, so the 90-day promise holds
   without a second scheduled job.
