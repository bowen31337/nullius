# Feature 309 — the persisted rebalance record, and the provenance the chain never carried

**app_spec.xml, "Portfolio Book Construction", feature 309**
(`shape="plugin"`, `plugin="book"`, `depends_on="305"`): *System persists each
rebalance target weight set with its originating promoted signal identifiers.*

Declared file-claim scope: `src/app/modules/book/**`, `packages/book/**`.

## What the sentence means, and what it does not

The chain ends at feature 305's *"final target weights as the only output
consumed by the order layer"* — §C8's last arrow, published by `_publish.py`.
Feature 309 is the sentence that says where that output is **written down**, and
what must be written down **beside** it: the identifiers of the promoted signals
the set originated from.

The construction's own records deliberately do not carry that provenance past
feature 301. `CompositeBook` holds `information_ratios` / `weights` keyed by
`signal_id` — the composite *is* the record of which signals weighted the book —
but feature 303's `TargetWeights` and feature 305's `FinalTargetWeights` are
keyed by **symbol** only. That is not an oversight: 305's docstring states that
the construction's *working* (the composite, the gross book, the scale, the
limits) stays where it was computed, and "the sentence's *only* is what keeps
them out of the order layer's instruction". So the provenance is **not on any
value the chain hands the order layer** — which is exactly why persisting it is a
feature of its own.

**What it does not add: any arithmetic.** No re-weighting, no re-normalization,
no re-bounding, no re-publication. 309 takes the published set and the signals
it originated from and writes them down. It re-opens nothing 301-308 settled.

**What it does not add: any order-path machinery.** No `client_order_id` (that is
feature 316's, in the router member), no rounding, no venue filters, no sizing.

## The decisions this feature takes

### 1. The identity is `(book_id, rebalance_ts)` — §13.2's own triple, read at its head

docs/nullius-tech-architecture.md §13.2 keys the order path on
`client_order_id = hash(book_id, rebalance_ts, symbol)`. Feature 316 (router)
owns that hash; **this member owns the three inputs it hashes**, and two of them
are the rebalance's identity. So the table's primary key is exactly that pair: one
row per rebalance per book. Nothing else in either document names a rebalance's
identity, and inventing a surrogate id would put a second identity beside the one
feature 316 hashes — free to disagree with it.

Both are **required keywords with no default**, the stance features 303, 304 and
308 take for their own figures:

- `book_id` is the deployment's (isolated margin *per book*, §13.2/§C9 — the
  system runs more than one), and a module constant would be a deployment's
  identity invented by this member;
- `rebalance_ts` is the **rebalance's** instant, not the write's. A default of
  *now* would make the row's identity the instant somebody happened to call,
  so a **retry would land under a different identity** — the one property
  idempotence rests on. The caller already holds it: it is the key the order
  path is about to submit under.

### 2. One row per rebalance, with the set as one JSON object

The alternative — a row per `(book, rebalance_ts, symbol)` — makes the set's
**symbol coverage a property of how many rows happened to be written**. A write
that failed halfway would read back as a smaller book, which is precisely the
*absence-vs-zero* trap this member refuses everywhere: a partially-written set is
not a small book, it is the absence of one. One row means the set either landed
whole or not at all.

`weights` is therefore a JSON object (symbol → weight) and `signal_ids` a JSON
array. Both are **the source of truth, rebuilt on read** — never summarised into
derived columns — the discipline `cost_model.latency_store` states for its
`samples` and `evaluator`'s metrics store for its `ic_series`.

`recorded_at` is the **database's** own clock (`DEFAULT (datetime('now'))` with
the outer parentheses SQLite's `DEFAULT` grammar demands of a function call), one
clock for the table, the writer contract `0107` states.

### 3. The provenance is **read off the promoted signals**, never retyped

The act's second argument is the promoted signals the set originated from, and it
reads each one's `signal_id` — **the same attribute feature 301's combiner reads
off the same values**, duck-typed, no `isinstance` (the loader imports members
under synthetic names, so a composed signal may be a second class object).

A bare list of identifiers would be a *claim*: nothing could check that those
signals are the ones that weighted the book, and provenance that nothing checks is
the one thing an audit table exists to avoid. Reading `signal_id` off each signal
means a caller cannot pass bare strings (`"momentum"` has no `signal_id`), so the
recorded provenance is always the identifiers of values that call themselves
promoted signals.

The identifiers are stored **sorted and distinct** — a provenance is a *set*, and
sorting makes two records of one provenance compare equal, which is what the
idempotence check below rests on (`CoverageLedger.__post_init__` sort, 305's
sorted weights). A duplicate is refused by 301's own `duplicate_signal` word read
one step further along the chain: the book was weighted by one signal, and a
provenance naming it twice is a malformed set of identifiers.

### 4. Persisted once: an identical re-issue is a retry, a differing one is refused

The sentence says *each*: one recorded set per rebalance. So the write is:

- **absent row** → insert, read back, answer the database's row;
- **standing row equal to the offered set** (weights and identifiers) → answer the
  standing row **untouched**, `recorded_at` included — a retry is the same
  persisting call arriving twice (a reclaimed spot instance, a loop that re-ran
  its rebalance step), and the set did not change, so the instant it was recorded
  did not either;
- **standing row different** → refuse with `rebalance_already_recorded`.

The refusal is the sentence's own judgment. Same shape as feature 305's
`annexed_record` one layer up: two target weight sets for one rebalance instant
leave every reader of this table **choosing between them**, and this time there is
no bound to re-run and no act to re-apply — the row is the only record, so a
silent overwrite would be a rebalance nobody decided, recorded as though somebody
had. The promotion member's pre-registration (`packages/promotion`,
`feature 291`) refuses a differing re-registration for exactly this reason; 309
states it for the rebalance.

The repair is the caller's: record the set under the instant it was actually
computed for. This member reconciles nothing and overwrites nothing.

### 5. Three faces, and the third is this member's first store

Every feature 303-308 mints a **pair** — the ask's own facts and the one judgment
the sentence mints — because none of them touches a database. 309 does, and a
store has a third face the member has never needed to name: **the write that did
not land**. Every store-bearing feature in this workspace names it in its own
class (`PromotionStoreError`, `RouterStoreError`, `CoverageError`), and
`packages/promotion/src/promotion/errors.py` argues the split at length: a
malformed ask and an unreachable database must not arrive in the same class,
because the caller's position differs — *fix what you handed me* against *your
store is unreachable*.

So 309 adds three siblings under `BookConstructionError`, carrying two codes:

- `RebalanceRequestError` — the ask. Carries `no_book` (feature 305's own word,
  imported rather than respelt: the same fact about the same `weights` surface,
  read one step further along the chain) where the value handed is not a set at
  all; carries `no_originating_signals` where the provenance is absent; carries no
  code where an element names its own subject (a blank symbol, a non-finite
  weight, a signal with no `signal_id`, a duplicate identifier) — the reason
  `LimitRequestError` and `VolatilityTargetRequestError` carry none.
- `RebalanceRewriteError` — `rebalance_already_recorded`.
- `RebalanceStoreError` — the address and the row (an unsupported scheme, a
  pathless or in-memory URL, a locked database, a corrupt stored row).

### 6. Absence is not zero, read on the provenance

Refused: a value carrying no `weights` (305's `_book_of` discipline, restated in
this module the way 303, 304 and 305 each restate it), a set covering no symbols,
a non-finite weight, an empty or non-iterable provenance, a signal with no
`signal_id`, a duplicate identifier, a blank `book_id`, a naive or non-datetime
instant.

**Answered**: a book held flat — every weight `0.0`, feature 303's zero-target
answer, admitted by feature 304 at every limit of zero or more. *Hold nothing* is
a decision a rebalance is entitled to record, and the provenance of that decision
is real: three signals placed a book at zero.

### 7. No new component, no seat edit, no migration

The member registers exactly one component (`book`, the combiner callable) and the
member's suite pins that **six times** — `len(names) == 1` — precisely so a later
edit cannot quietly add a second. A builder runs with no arguments and must not
fail composition, and this store's address is a deployment's `DATABASE_URL`;
`build_book_combiner`'s whole configuration is the arithmetic (its docstring and
the component suite both say so).

So 309 follows `cost_model.latency_store` and `discovery.persist`: a store class
plus module-level verbs beside the combiner, reached from the member
(`from book import persist_rebalance_target_weights, ...`), the way every free
function of this member is reached. The seat (`src/app/modules/book/__init__.py`)
is **untouched** — its docstring argues it answers exactly one question, and a
store accessor would be a second. No `@register`, no table in the shared
migration chain (the member-owned table is created idempotently by the only module
that writes it, per the plugin convention), no route, no settings, no middleware.

The layering bill: `_rebalance.py` imports `json`, `sqlite3`, `os`,
`datetime`, `collections.abc`, `contextlib`, `dataclasses`, `urllib.parse` — all
stdlib — and the member's own `.errors` / `._publish`. `DATABASE_URL` is read at
the **call**, never at composition, so the factory's scan still pays only the
imports it already paid. It takes no clock, imports no other member, and performs
no arithmetic.

**This is the honest change to the member's layering paragraph**: the member is no
longer environment-free. The package docstring is updated to say so plainly
rather than left claiming otherwise.

## Files

- `packages/book/src/book/_rebalance.py` (new) — the table and column constants,
  the canonical JSON spellings, `RebalanceTargetWeights`,
  `RebalanceTargetWeightsStore`, `persist_rebalance_target_weights`,
  `read_rebalance_target_weights`, `rebalance_target_weights_for`, and the
  readers (`_weight_set_of`, `_originating_signal_ids`, `_validated_book_id`,
  `_validated_instant`, `_sqlite_path`).
- `packages/book/src/book/errors.py` — `RebalanceRequestError`,
  `RebalanceRewriteError`, `RebalanceStoreError` as siblings under the base;
  `__all__`, the module docstring's feature and code lists, and the base class's
  docstring widened.
- `packages/book/src/book/__init__.py` — re-export and `__all__` widened; the
  package docstring states the member now carries eight features, describes 309,
  and stops claiming the member reads no environment.
- `packages/book/tests/test_rebalance.py` (new) — the claims below.
- `packages/book/tests/test_component.py` — the surface pin widened to the eight
  features, and 309's composition story added (no second component, reachable
  without the factory, `build_book_combiner` still takes no arguments).

## Verification

- `uv run --frozen pytest packages/book/tests` — the member's own suite (NOT
  graded by the bare gate).
- `uv run --frozen pytest tests/` — the repository-level acceptance suite.
- `uv run --frozen ruff check packages/book/`.
- `create_app()` inspected directly: still exactly one `book` component.
- `git status`: no file outside the declared footprint modified.
