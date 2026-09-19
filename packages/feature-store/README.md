# nullius feature store

Workspace member for the **feature-store** plugin (app_spec.xml, category
"Point-in-Time Feature Store"; docs/nullius-tech-architecture.md §4.4).

## The keying contract (feature 48)

Every stored feature is keyed by exactly five components, in canonical
order:

| component          | meaning                                            |
|--------------------|----------------------------------------------------|
| `feature_name`     | which definition computed the feature               |
| `feature_version`  | which revision of that definition (feature 53)      |
| `snapshot_hash`    | which sealed snapshot's bytes it was computed over  |
| `symbol`           | which instrument (`__market__` for market-wide)     |
| `frequency`        | which bar grid: `1m`, `1h`, `1d` (§5.1 contract)    |

Change any one component and you have a different stored feature — never a
silent reuse of the old one. `FeatureKey` makes that enforceable: it is
immutable, validated, hashable, totally ordered, and doubles as a relative
POSIX path (`key.to_path()`), so what is stored and where it is stored can
never disagree.

`FeatureStore` is the read/write surface: records enter only with a
complete key, leave only under the identical key, and an exact-key
duplicate is an error (`DuplicateFeatureKeyError`), not a replacement.

## Feature 51 — row-level `computed_as_of` stamping

app_spec.xml feature 51: *System stamps every feature row with
computed_as_of at write time.* §4.4 gives the reason the stamp exists:

> **Point-in-time correct by construction:** every row carries
> `computed_as_of`, and a query at `t` may only return rows with
> `computed_as_of <= t`.

Feature 48 deliberately left a record's payload opaque `bytes` and deferred
row-level stamping to "the payload layer those features add", so
`feature_store.rows` supplies it:

- `FeatureRow` — one row of a feature's payload: a frozen, validated
  `computed_as_of` plus its named values. The stamp is a **field**, read
  back as what was written rather than restamped on access, because it
  records when the row was *computed*.
- `stamp_rows(values, *, computed_as_of=None, clock=None)` — the write-time
  seam. It reads the clock **once per write** and applies that single
  instant to every row in the batch: a batch straddling a clock tick would
  otherwise carry two stamps, and a `<= t` query landing between them would
  return *part of one write* — half a batch a reader cannot tell from a
  complete one. One write, one instant.
- `encode_rows` / `decode_rows` — the deterministic JSON envelope that
  bridges this layer to feature 48's opaque-`bytes` seam, so the stamp
  travels in the payload and survives a store round-trip.

**The stamp is timezone-aware UTC.** A naive datetime is refused at write
time rather than accepted and detonated later: feature 52 compares the stamp
with `<=`, and a naive/aware comparison raises `TypeError` — deep inside a
query, far from the write that could have named the missing offset. An aware
instant in another offset is *normalised* to UTC rather than rejected, since
it names the same moment either way.

**The clock is injected, never reached for.** `computed_as_of` may be passed
explicitly (a backfill stamps the historical instant; a replay stamps the
instant it is reproducing), and otherwise comes from a `clock` callable
supplied at the call site, defaulting to `utc_now()`. Nothing reads a global
clock, so the deterministic replay path can reproduce a write exactly.

Feature 52's read filter — the `computed_as_of <= t` query — is **not**
here: this module stamps rows and carries them. That filter is
`feature_store.point_in_time`, the next section.

## Feature 52 — the point-in-time read (`computed_as_of <= t`)

app_spec.xml feature 52: *System returns only rows whose computed_as_of is
at or before the query time, so a point-in-time read cannot see a later
computation.* This is the reading half of §4.4's rule, the half the stamp
exists for — and the half the category is named for. A row stamped after
the query instant is a computation that had not happened yet at that
instant; handing it to a caller asking *what did we know at `t`?* answers
*what is true now* instead, which is exactly the leakage §4.4 warns about
when it calls the feature store "the single most common source of subtle
leakage in real quant systems".

`feature_store.point_in_time` enforces the filter in the read path itself —
not in caller discipline — at three layers that compose and so cannot
disagree about what `<=` means:

- `rows_as_of(rows, *, as_of)` — the filter over a batch of stamped rows
  already in hand;
- `decode_rows_as_of(payload, *, as_of)` — decode one record's opaque
  `bytes` through feature 51's envelope, then filter;
- `read_rows_as_of(store, key, *, as_of)` — get under the key, decode,
  filter: the point-in-time read at the store layer.

**The boundary is inclusive.** "At or before" is `<=`: a row stamped
exactly at the query instant had been computed by then, so it is visible —
equality is the edge between known and not-yet-known, and the edge belongs
to the known side. Visibility gates on the stamp alone: a row's *values*
may describe any time (a forecast, a forward-looking label), and none of
that is consulted — `computed_as_of` says when the row was computed, and
that is the whole of the point-in-time question. No function here reads a
wall clock either, so the same question asked twice gets the same answer,
replay included. Rows come back verbatim — the same objects, in their
written order, still carrying the stamps that were written.

**A stored-but-later record reads as empty, not as missing.**
`read_rows_as_of` returns `None` only when nothing is stored under the key
(the same normal miss `store.get` returns) and `()` when a record *is*
stored but every row in it was computed after the query instant: the later
computation exists, and the read declines to see it. Collapsing the two
answers would hide the very state this feature guarantees.

**The query time is validated like a stamp.** A naive `as_of` compared
against an aware `computed_as_of` would raise `TypeError` deep inside the
loop, far from the caller who could have named the offset; it is refused
at the query as `PointInTimeError` instead. An aware instant in another
offset is normalised to UTC rather than rejected — it names the same
moment either way.

Like feature 51's row layer, this registers nothing with the application
factory: a pure function over rows and payloads, not an orchestration
service with composed state.

## Feature 57 — mean pairwise correlation + breadth

Beyond the keying contract, this member implements feature 57: *System
computes mean pairwise correlation of the top 50 symbols plus breadth above
an N-day moving average, persisting both.*

- `feature_store.bars` — `DailyBar(symbol, date, close)`: the daily price
  record the reductions consume (distinct from the universe member’s
  dollar-volume `DailyBar`, which carries no price).
- `feature_store.regime` — the pure reductions: `PricePanel` (one aligned
  close series per symbol over a shared date axis), `mean_pairwise_correlation`
  (mean off-diagonal Pearson coefficient), `breadth_above_moving_average`
  (count of symbols above their own N-day average), and `build_regime_metrics`
  bundling both into a `RegimeMetrics`.
- `feature_store.persistence` — the persisting half: encodes each metric to
  an opaque JSON payload and stores both as feature-store records under the
  market-wide (`__market__`) daily key, keyed by feature name + version +
  snapshot hash. Reads them back as a pair.
- `feature_store.service` — `RegimeService`: assembles the panel from daily
  bars + a universe membership, computes both metrics, and persists both —
  the whole feature at one seam. Registered with the application factory as
  the `"regime-metrics"` component.

Both metrics are market-wide (describing the market as a whole, not one
instrument), so both are keyed with the `__market__` sentinel symbol and the
daily frequency — feature 48 admits no four-component keys. The membership
is the universe’s top-N (feature 40); this member never ranks liquidity, it
is *given* the membership and computes what the market did across it.

## Feature 56 — dispersion + autocorrelation, version stamped

Beyond the keying contract, this member implements feature 56: *System
computes cross-sectional return dispersion plus return autocorrelation at
several lags, persisting them with feature_version stamps.*

- `feature_store.dispersion` — the pure reductions, a sibling of `regime`:
  `cross_sectional_dispersion` (the *width* of the panel’s latest
  cross-section: the population standard deviation of its members’ most
  recent log returns, with the equal-weighted mean and the scored count
  beside it), `market_return_series` (the equal-weighted cross-sectional mean
  return, one value per period), `return_autocorrelation` (the *memory*: a
  pairwise-complete Pearson of that series against its own shift, at every
  requested lag), and `build_dispersion_metrics` bundling both into a
  `DispersionMetrics`. The default lag set is `(1, 2, 3, 5, 10)` — “several
  lags” is the contract, so a single lag would not satisfy it.
- `feature_store.dispersion_persistence` — the persisting half: encodes each
  metric to a deterministic JSON envelope and stores both as feature-store
  records under the market-wide daily key. Reads them back as a pair.
- `feature_store.dispersion_service` — `DispersionService`: assembles the
  panel from daily bars + a universe membership, computes both metrics, and
  persists both. Registered with the application factory as the
  `"dispersion-metrics"` component.

**The version stamp is the point.** `feature_version` is a component of the
five-part key, so a record’s version is part of its *identity*: a changed
definition lands under a new version and leaves the prior-version rows
untouched (feature 53), rather than overwriting numbers a replay may still be
reading. Version `"1"` names a definition stated in words
(`DISPERSION_DEFINITION`, `AUTOCORRELATION_DEFINITION`) and defaulted in
`definition_parameters()`, so the stamp is checkable rather than a bare
number. `DispersionService.persist` therefore refuses
(`VersionMismatchError`) a computation whose lags, `min_symbols` or
`min_observations` disagree with the definition the stamp names — storing
different numbers under an address that promises version 1 would be a record
that is wrong by construction and undetectable from the key alone.

A thin cross-section is `nan`, never `0.0`: dispersion over one symbol is not
a cross-section, and an unscored lag reports `nan` over zero pairs rather
than a zero a reader would mistake for a measured absence of memory.

## Feature 55 — multi-horizon realized volatility + vol-of-vol, versioned

This member also implements feature 55: *System computes multi-horizon
realized volatility plus volatility-of-volatility, persisting each as a
versioned regime feature.*

- `feature_store.volatility` — the pure reductions, a sibling of `regime`
  and `dispersion`: `realized_volatility` (the *magnitude*: the annualized
  root-mean-square of the trailing `horizon` returns, computed at several
  horizons at once — 10, 21, 63 by default — so a spike inside a tranquil
  quarter reads at the short horizon instead of being averaged away),
  `rolling_realized_volatility` (that same estimate at every position, the
  base series the instability is measured over),
  `volatility_of_volatility` (the *instability*: the population standard
  deviation of a trailing window of the base series, with its mean beside
  it, so a wide-but-low vol regime reads differently from a wide-and-high
  one), and `build_volatility_metrics` bundling both into a
  `VolatilityMetrics`. Both consume the market return series — the same
  equal-weighted cross-sectional mean feature 56's autocorrelation measures —
  so the member's regime features share one definition of "the market's
  return".
- `feature_store.volatility_persistence` — the persisting half: encodes each
  metric to a deterministic JSON envelope and stores each under its **own
  `feature_name`** (`realized_volatility`, `volatility_of_volatility`) as its
  own version-stamped record under the market-wide daily key. Reads them
  back as a pair.
- `feature_store.volatility_service` — `VolatilityService`: assembles the
  panel from daily bars + a universe membership, computes both metrics, and
  persists each. Registered with the application factory as the
  `"volatility-metrics"` component.

Same versioning discipline as feature 56: the `feature_version` stamp is a
segment of each record's address, version `"1"` names a definition stated in
words (`REALIZED_VOL_DEFINITION`, `VOL_OF_VOL_DEFINITION`) and defaulted in
`definition_parameters()`, and `VolatilityService.persist` refuses
(`VersionMismatchError`) a computation whose horizons, base window, vol
window or annualization disagree with the definition the stamp names.

Estimator choices version 1 commits to: squared returns, deliberately *not*
demeaned (over daily windows the mean return is noise); the strict trailing
window (a gap is an absent observation, never a reason to reach further
back — the same rule the breadth moving average follows); and annualization
by `sqrt(365)`, because crypto quotes trade every calendar day. An
unscored horizon is `nan` over the count of slots that were present, and a
measured calm (every return zero) is `0.0` — a different fact, never
conflated.

## Layout

- distribution: `nullius-feature-store` (this directory, `packages/feature-store/`)
- import package: `feature_store` (under `src/`)
- registered components: `"feature-store"` (feature 48),
  `"feature-materialiser"` (feature 49), `"regime-metrics"` (feature 57),
  `"dispersion-metrics"` (feature 56), `"volatility-metrics"` (feature 55)
  and `"regime-labeler"` (feature 58), all via `@register`, discovered by
  `app.module_loader`’s workspace scan. Feature 51's row stamping and
  feature 52's point-in-time read register nothing: both are pure functions
  over rows and payloads — the payload layer of the store's own contract —
  not orchestration services, so neither has composed state for the factory
  to own
- app-package seat: `app.modules.feature-store` (`src/app/modules/feature-store/`),
  which exposes `feature_store_component()`, `feature_materialiser_component()`,
  `regime_metrics_component()`, `dispersion_metrics_component()` and
  `volatility_metrics_component()` without the `app` package depending on any
  member at import time

Every `@register` in this member is on the package's own import path
(`feature_store/__init__.py`), never in a submodule. The factory's scan
re-executes a package's `__init__` on every `create_app()` call but does not
re-execute a submodule already cached in `sys.modules`, so a registration in
a submodule would fire only on the first composition of a process and vanish
from every later one.

Stdlib-only by design — the identity contract stays import-safe in any
environment, deterministic replay included. Feature 49 is the one exception
that proves the rule: it is the first module here needing a third-party
dependency (pyarrow, for the Parquet format §4.1 pins), so the import is
deferred to first use (`feature_store.parquet.require_arrow`) and the package
stays import-safe for the scan. Row-level stamping (51) has landed in
`feature_store.rows`, and its `computed_as_of <= t` read filter (52) in
`feature_store.point_in_time`. Caching (50) — the `cache_hit` counter that
measures the materialiser's reuse — lives in `feature_store.materialise`
alongside feature 49, whose reuse path it counts.

### Parquet materialisation (feature 49)

`feature_store.parquet` is the format half: `encode_parquet`/`decode_parquet`
turn a batch of feature rows into Zstd-compressed Parquet bytes and back. The
`computed_as_of` stamp is a real Arrow `timestamp("us", tz="UTC")` column, not
a string, so a point-in-time filter can push down into the file; the value
columns are inferred over each whole column, so column types are a property of
the batch rather than of whichever row happened to be read first. Encoding is
deterministic: the same rows, schema and compression give byte-identical
output, which is what makes replay comparison meaningful.

`feature_store.materialise` is the "lazily on first request, persisting the
result for later reuse" half. `FeatureMaterialiser` maps a `FeatureKey` to a
file under `<lake_root>/features/` — the key's own five path-safe segments,
with `.parquet` on the last — so the address is derived from the identity
rather than assigned by a table nobody can read. `materialise(key, compute)`
reads that file when it exists and calls `compute` when it does not, reporting
which happened through `MaterialisedFeature.materialised`. The happy path is
the reuse path: a hit does not call `compute` at all, so a definition's clock
is never advanced by a read.

Writes are atomic (temp file beside the destination, then `os.replace`), so a
crash mid-write leaves the previous materialisation intact rather than a
half-file that later reads would trust. A corrupt file is refused with
`MaterialisationError` naming the path and the `replace=True` remedy — it is
never silently recomputed, because a corrupt artefact is a fact about the lake
and a recompute would hide it. An absent file and a corrupt one are different
states, and so are a file whose rows are all later than the query time and no
file at all.

### Measuring the reuse (feature 50)

The laziness feature 49 provides is measurable. `FeatureMaterialiser` keeps a
`cache_hit` counter that rises by one every time a request reuses an
already-materialised feature instead of recomputing it, and a `cache_miss`
counter for the calls that compute. Both are read with the `cache_hit`,
`cache_miss`, `cache_hit_rate` (hits over total, in `[0, 1]`) and
`reset_cache_stats` accessors. They are process-memory only — never written to
the lake, so a fresh materialiser over the same lake starts at zero, matching
feature 49's disk-only persistence. A hit is reported through
`MaterialisedFeature.materialised is False` and its `cache_hit` field, which
snapshots the running count onto the result so a caller can log the counter per
request without reaching back into the materialiser. A deliberate `replace=True`
recompute counts as a miss, because it does the work a miss does; a refused
corrupt file is neither, and moves neither counter.
