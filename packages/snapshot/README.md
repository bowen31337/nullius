# snapshot

Seals staged lake content into **immutable, content-addressed snapshot
directories** — app_spec.xml feature 30, on the layout of
`docs/nullius-tech-architecture.md` §4.1–§4.2.

## What it does

Ingest workers append into a writable staging area; this package is the
write side of the boundary that follows:

```
<lake>/staging/…                              writable, append-only (ingest)
        └─ seal() ─────────────────────────────────────────────┐
                                                              ▼
<lake>/snapshots/2026-09-01T00:00:00Z_a3f91c/   immutable: <sealed_at>_<snapshot_hash[:6]>
```

A seal copies the staged tree into a hidden working directory, freezes
every file `0444` and every directory `0555`, and renames the result into
place — `rename(2)` is atomic, so a sealed name never refers to a
half-written directory. Re-sealing identical content is idempotent;
re-sealing different bytes under an existing name raises
`SnapshotAlreadySealedError` and leaves the sealed tree untouched.

The default snapshot hash is the content digest of the staged files — the
`sorted(file_hashes)` term of the §4.2 formula
`sha256(sorted(file_hashes) + universe_definition + schema_version)`. The
universe and schema terms are the manifest/hash features of this category;
they fold the same per-file hashes this seal computes.

## Wiring

None required. This is a uv workspace member under `packages/`, and
`src/snapshot/__init__.py` carries the component builder:

```python
from app.module_loader import create_app

service = create_app().get("snapshot")   # a SnapshotService bound to LAKE_ROOT
```

The module loader discovers the member by scan, as the root
`pyproject.toml` declares; no registry, router or factory is edited to
make the plugin exist.

## Lake root resolution

`SnapshotService.from_env()`: `LAKE_ROOT` when set (blank counts as
unset), else `lake/` beside the workspace root, else a raised
`SnapshotError` — never a guess.

## Tests

The suite lives inside the member (the repository-level `tests/` conftest
does not reach package-local suites, so `packages/snapshot/tests/conftest.py`
reproduces its per-test lake isolation):

```
uv run pytest packages/snapshot      # this member's suite
uv run pytest                        # the repository-level suites
```
