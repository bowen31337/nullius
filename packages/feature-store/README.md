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

## Layout

- distribution: `nullius-feature-store` (this directory, `packages/feature-store/`)
- import package: `feature_store` (under `src/`)
- registered components: `"feature-store"` (feature 48), `"regime-metrics"`
  (feature 57) and `"dispersion-metrics"` (feature 56), all via `@register`,
  discovered by `app.module_loader`’s workspace scan
- app-package seat: `app.modules.feature-store` (`src/app/modules/feature-store/`),
  which exposes `feature_store_component()`, `regime_metrics_component()` and
  `dispersion_metrics_component()` without the `app` package depending on any
  member at import time

Stdlib-only by design — the identity contract stays import-safe in any
environment, deterministic replay included. Parquet materialisation
(feature 49), caching (50) and point-in-time row filters (51/52) layer on
top of this seam.
