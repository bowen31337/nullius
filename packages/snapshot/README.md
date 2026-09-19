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

## The read-only mount

`service.mount(name)` is the evaluator's door — app_spec.xml feature 34,
§4.2's *"a snapshot is sealed, hashed, and mounted read-only"*. It returns a
`SnapshotMount` whose every path is a `ReadOnlyPath`:

```python
mount = service.mount("2026-09-01T00:00:00Z_a3f91c")

mount.read_bytes("bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet")
mount.partitions("bars")                       # ('BTCUSDT', 'ETHUSDT') — from names, no Parquet opened
mount.select("bars", "BTCUSDT", "2026-09-01")  # this symbol, this date, nothing else

(mount.root / "bars" / "…" / "part-0.parquet").write_bytes(b"x")
# SnapshotReadOnlyError: [Errno 13] Permission denied: write to
# /lake/snapshots/2026-09-01T00:00:00Z_a3f91c/bars/…/part-0.parquet refused:
# sealed snapshot 2026-09-01T00:00:00Z_a3f91c is mounted read-only
# (docs/nullius-tech-architecture.md §4.2); staging is the writable area,
# not a sealed snapshot
```

Writes are refused in three independent layers:

1. **The filesystem.** Sealing persists `0444`/`0555`, so a write through a
   raw `Path` fails at the kernel regardless of this API. That is the
   guarantee; the mount sits on top of it.
2. **The mount.** Every mutating verb — `write_bytes`, `open("w")`,
   `unlink`, `mkdir`, `rename`, `chmod`, `touch`, … — raises before any
   syscall, so the refusal explains itself instead of arriving as a bare
   `EACCES`. `SnapshotReadOnlyError` inherits from *both* `SnapshotError`
   and `PermissionError`: either `except` clause catches it.
3. **Re-assertion on mount.** Modes travel badly (an archive restore, a
   copy that drops permissions), so mounting clears any write bit it finds.
   That is a tightening only — it never grants a permission, and an
   operator's stricter-than-contract mode is left alone. `modes_corrected`
   reports what the walk repaired, so drift is visible rather than silent.

Enforced by the mount, not by convention: a `ReadOnlyPath` has no mutating
verb to call in the first place, and `Path(ro_path)` lands back on layer 1.

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
