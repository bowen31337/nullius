# snapshot

Seals staged lake content into **immutable, content-addressed snapshot
directories**, each carrying its own **`MANIFEST.json`** — app_spec.xml
features 30–32, 38 and 39, on the layout of `docs/nullius-tech-architecture.md`
§4.1–§4.2.

## What it does

Ingest workers append into a writable staging area; this package is the
write side of the boundary that follows:

```
<lake>/staging/…                              writable, append-only (ingest)
        └─ seal() ─────────────────────────────────────────────┐
                                                              ▼
<lake>/snapshots/2026-09-01T00:00:00Z_a3f91c/   immutable: <sealed_at>_<snapshot_hash[:6]>
          MANIFEST.json                        # per-file sha256, row counts, universe
          bars/symbol=…/date=…/*.parquet
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

## The per-snapshot manifest

Every seal persists a `MANIFEST.json` *inside* the snapshot it publishes
(feature 31), so the record travels with the bytes it describes:

```python
record = service.seal(staging, sealed_at=at, universe=asdict(config))
manifest = service.read_manifest(record.name)

manifest.snapshot_hash        # the full 64-char hash — not just the name's prefix
manifest.files                # {path: ManifestFileEntry(sha256, row_count)}
manifest.total_rows           # sum of per-file rows; None if any file's are unknown
manifest.universe             # the definition asserted at seal time (JSON object)
```

Row counts come from each file's own format: the Parquet footer's
`num_rows` (parsed from its Thrift metadata, stdlib-only) for the lake's
data files, a line count for line-oriented text, and an explicit `null`
for opaque binary — never a guess, and a `total_rows` over any unknown is
`null` rather than a partial sum. The manifest describes content and is
therefore not content: it is excluded from the seal's file mapping and
digest, and staging that already contains a root `MANIFEST.json` is
refused rather than overwritten.

The manifest's bytes are deterministic (sorted keys, fixed indentation),
so the same content, instant, hash and universe produce byte-identical
manifests on any machine. Its presence also pins identity on re-seal: the
recorded full hash must match, which closes the gap where two different
hashes sharing the directory name's six-character prefix could alias.

## When the lake is extended

App_spec feature 38: *the lake grows, the identity moves* — and that is
the whole cache-invalidation mechanism. Scores and features are keyed by
`snapshot_hash` (§4.4), so an extension that seals under a genuinely new
hash is a guaranteed cache miss: the scores cached under the old one are
recomputed rather than handed back for bytes they never saw.

```python
first = service.seal(staging, sealed_at=at_1)          # hash H1
# ingest appends a partition…
second = service.seal(staging, sealed_at=at_2)         # hash H2 ≠ H1

second.snapshot_hash != first.snapshot_hash            # a new identity
first.path.is_dir() and second.path.is_dir()           # both answer, each its own
```

Every extension axis re-keys: a new file, more bytes in an existing file,
a file duplicating another's bytes (the fold is a multiset), a universe
that turned over a month. And an extension that is append-only leaves
every previously sealed path hashing identically inside the new identity —
the tree structure survives; the scores do not (§15).

The identity is **assigned once, to one set of bytes**, and the seal
enforces it against the lake itself: every sealed snapshot's manifest is
its persisted assignment of a full hash to a file mapping, and a seal
that would publish an already-assigned hash over *different* bytes is
refused — whatever name it would land under:

```python
service.seal(staging, sealed_at=at_2, snapshot_hash=first.snapshot_hash)
# SnapshotHashReusedError: snapshot_hash H1 is already assigned to sealed
# snapshot <name> (3 files); refusing to bind it to different staged
# content (4 files). When the lake is extended the seal is assigned a new
# snapshot_hash — the formula over the extended content — so scores cached
# under the old one are invalidated rather than silently reused; drop
# snapshot_hash= and let the seal compute the extended lake's own identity
```

`SnapshotHashReusedError` subclasses `SnapshotAlreadySealedError`: a
reassigned identity is the immutability refusal one granularity up from a
taken name. The same hash over the *same* bytes stays legal at any
instant — a schedule that re-seals an unchanged lake re-asserts one
identity, and cached scores under it remain exactly as valid as they
were. Invalidation tracks the lake's content, not the calendar. A
snapshot whose manifest is missing or unreadable proves no assignment and
does not block unrelated seals; the name-level checks still own that
directory for seals that name it.

## Recomputation flags

App-spec feature 39: *the lake grows, the identity moves, and every score
the old identity held is flagged for recomputation* — while the discovery
tree that those scores decorate is left untouched. Feature 38's new hash is
the invalidation *trigger*; this is the durable, visible *signal*.

The lake holds a `RecomputationRegistry` at `<lake>/recomputation.json`,
beside `snapshots/` and `staging/` (§4.2). It anchors every score to the
discovery-tree node it decorates and the `snapshot_hash` it was computed
over, and carries the `recompute` flag a snapshot change flips:

```python
registry = service.recomputation

# The derived zone registers a score against the snapshot it was computed over.
registry.register_score("score-42", first.snapshot_hash, node_id="node-a")

# The lake is extended (feature 38): a new snapshot seals under a new hash.
second = service.seal(staging, sealed_at=at_2)

# The snapshot change flags every score the old hash held, and records the
# supersession in the audit — the tree's nodes and edges are untouched.
supersession = service.record_snapshot_change(
    first.snapshot_hash, second.snapshot_hash
)
supersession.flagged_scores        # how many scores it reached

registry.needs_recomputation("score-42")   # True — flagged
registry.score("score-42").superseded_by   # second.snapshot_hash
registry.edges()                           # the tree structure, intact
```

The registry is **persisted**, so a flag one process sets is the flag
another reads — a recomputation flag that vanished on restart would silently
reuse the stale score it was meant to replace. It holds only the addressing
and the flag, never a score's value or a node's meaning: it is the
invalidation signal, and the derived zone owns the recomputation it points at.

A snapshot change is **verified against the lake**: both hashes must name
snapshots this lake actually seals (the manifest records the full hash in
full, so a hash sharing only a prefix is refused), and the old hash must hold
scores the registry was told about. A change naming a hash the lake does not
hold is refused with `SnapshotRecomputationError`, leaving the registry
untouched — a recomputation flag anchored to a hash the lake does not hold
would flag scores that do not exist.

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

## Refusing a request for staging

`service.open(name)` — the seam every read path goes through — refuses a
request that names the staging area (feature 35). Staging is the ingest
workers' writable area and is never on the evaluator's mount path, so an
evaluator that asks for it is told so, and pointed at the sealed snapshots it
*may* open:

```python
service.open("staging")
# SnapshotStagingRequestError: request 'staging' names the staging area
# /lake/staging, which is never on the evaluator mount path; staging is the
# ingest workers' writable area, not a sealed snapshot — open one of the
# sealed snapshots instead (SnapshotService.sealed)
```

`SnapshotStagingRequestError` is a `SnapshotNotFoundError`, so a caller
catching either vocabulary handles it. A request that merely *contains*
"staging" but resolves elsewhere — `../staging`, an absolute path — is
refused as a malformed name by the strict parser, not as a staging request;
only a request that resolves *onto* the staging area is a staging request.

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
