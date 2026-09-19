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

## Layout

- distribution: `nullius-feature-store` (this directory, `packages/feature-store/`)
- import package: `feature_store` (under `src/`)
- registered component: `"feature-store"` (via `@register`, discovered by
  `app.module_loader`’s workspace scan)

Stdlib-only by design — the identity contract stays import-safe in any
environment, deterministic replay included. Parquet materialisation
(feature 49), caching (50) and point-in-time row filters (51/52) layer on
top of this seam.
