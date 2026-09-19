"""Feature 49's laziness: materialise on first request, then reuse.

app_spec.xml, "Point-in-Time Feature Store", feature 49: *System materializes
a feature to Parquet lazily on first request, persisting the result for later
reuse.*  docs/nullius-tech-architecture.md §4.4 states the contract in six
words — "Materialized as Parquet, lazily on first request, then cached" — and
gives the reason in the sentence before it: base features *"are expensive and
shared across thousands of signal nodes.  Recomputing them per node is the
dominant avoidable cost."*

This module is the "lazily on first request" and the "persisting the result for
later reuse" halves of that; :mod:`feature_store.parquet` is the "Parquet", and
this module is also feature 50's ``cache_hit`` counter — it rises by one on the
reuse path, so the laziness feature 49 provides is measurable rather than
inferred from timing.  :attr:`MaterialisedFeature.materialised` is the fact it
counts, and :attr:`MaterialisedFeature.cache_hit` snapshots the running count
onto each result so a caller can log it per request.

**Lazy means: nothing is computed until something asks.**  There is no
constructor that walks a manifest, no eager pass that materialises a feature
list at start-up, and :meth:`FeatureMaterialiser.__init__` performs no I/O at
all — so a composed application carries a materialiser for free and pays only
when a request actually arrives.  A feature that is never requested is never
materialised, which is the whole point of not computing eagerly: §4.4's
thousands of signal nodes share a feature set far smaller than the number of
nodes that might want each one, and the ones nobody wants should cost nothing.

**First request means: compute once, then never again.**  :meth:`materialise`
takes the key and a ``compute`` callable.  It checks the lake for the key's
Parquet file first; finding one, it reads that file and returns it **without
calling ``compute``** — the reused result, which is the "later reuse" clause.
Only on a miss does it call ``compute``, encode the rows, and write the file
before returning.  A second call for the same key therefore does no feature
computation at all, and the returned
:class:`~feature_store.materialise.MaterialisedFeature` says which of the two
happened rather than making the caller guess.

**Where the bytes live is the key's own business.**  :meth:`FeatureKey.to_path`
already spells a feature's identity as five relative POSIX path segments, and
:mod:`feature_store.keys` keeps that method for exactly this reason — "keeping
it on the key means *what* is stored and *where* it is stored can never
disagree" (its own docstring).  So the materialisation's path is that path,
under the lake's ``features/`` area, with ``.parquet`` appended to the final
segment::

    <LAKE_ROOT>/features/<feature_name>/<feature_version>/<snapshot_hash>/<symbol>/<frequency>.parquet

The suffix is appended to the last segment rather than becoming a sixth one, so
:meth:`FeatureKey.to_path` stays a five-segment path that
:meth:`FeatureKey.from_path` can still parse — the file name is a property of
the *file*, and letting it into the path's segment count would break the
round-trip the key module promises.

Two features can therefore never collide on disk unless their five components
collide, at which point they *are* the same stored feature (feature 48) — and
because every component is validated path-safe when the key is built (no
separators, no ``..``, no control characters), the join cannot escape its
segment.  That is checked anyway in :meth:`path_for`, against the resolved
features root: a validated key should make the check unreachable, and a check
that can never fire is cheap insurance against the one bug that would matter.

**The write is atomic, and determinism makes a race harmless.**  The Parquet
bytes are written to a uniquely-named temporary file in the destination
directory and ``os.replace``\\ d into place — atomic on POSIX — so a reader
never sees a half-written file, and a crash mid-write leaves the lake exactly
as it was rather than a truncated Parquet file that would later read as
corruption.  Two processes materialising the same key concurrently both compute
it, both encode it, and both replace the file; because
:func:`feature_store.parquet.encode_parquet` is deterministic, the bytes they
write are identical, so the race wastes work but cannot produce a wrong file.
(This is feature 50's ground to improve on — the counter is where that waste
becomes visible.  Feature 49 does not lock.)

**Recomputation is explicit, never implicit.**  A changed definition gets a new
``feature_version`` and therefore a new key and a new file (features 48/53), so
the ordinary path never needs to overwrite.  ``replace=True`` exists for the
case where the same key must deliberately be recomputed — the same discipline
:meth:`~feature_store.store.FeatureStore.put` applies to a duplicate key, and
for the same reason: replacing a stored feature is a decision, not a default.

**A file that is not a materialised feature is refused, not recomputed.**  If
the key's path holds bytes that
:func:`~feature_store.parquet.decode_parquet` cannot read — truncated, foreign,
mistyped — that is a corrupt lake, and silently recomputing over it would
destroy the evidence and quietly change an answer a replay may have depended
on.  The refusal names the path and says how to override deliberately.

**The lake root is resolved the way the rest of the system resolves it.**
``LAKE_ROOT`` wins when set (empty or whitespace-only counts as unset, the same
treatment ``FeatureMaterialiser``'s peer :class:`~snapshot.SnapshotService`
gives it and the shared test fixtures rely on); otherwise the root defaults to
``lake/`` beside the workspace root, located through the factory's workspace
discovery rather than a hard-coded guess.  With neither available this refuses
to guess, because materialising into ``/`` is never what a caller meant.

**`compute` is a callable, not a registry.**  This module never learns what any
feature *is*: it takes a zero-argument callable returning the rows to
materialise, so the definition stays in Z0 where §4.4 puts it ("Feature
definitions live in Z0 and are versioned") and this module stays a cache.  The
callable may return :class:`~feature_store.rows.FeatureRow` objects — already
stamped by feature 51, the normal case for a definition that stamps as it
computes — or plain mappings, which this module stamps through
:func:`~feature_store.rows.stamp_rows` with the clock it was given, so one
write still carries one instant.

Exposes to the application factory as the ``"feature-materialiser"`` component,
on the same terms as the store and the metric services: a zero-argument builder
that resolves its configuration from the environment at composition time while
doing no I/O there.  The registration itself lives in the package's
``__init__`` — see the note at the foot of this module — because that is the
only import path the factory's scan re-runs on every composition.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from app.module_loader import find_workspace_root

from .keys import FeatureKey
from .parquet import (
    ParquetMaterialisationError,
    decode_parquet,
    encode_parquet,
)
from .rows import FeatureRow, stamp_rows, utc_now

__all__ = [
    "FEATURES_DIRECTORY",
    "LAKE_ROOT_ENV",
    "MATERIALISED_SUFFIX",
    "FeatureMaterialiser",
    "MaterialisedFeature",
    "MaterialisationError",
]


#: Environment variable naming the lake root — the same one the snapshot
#: member reads and the shared fixtures in ``tests/conftest.py`` set per test.
#: Spelled again here rather than imported from ``snapshot``: the two members
#: are peers, and a workspace member does not depend on another member's module
#: for a string the architecture doc pins (§4.2).
LAKE_ROOT_ENV = "LAKE_ROOT"

#: The lake area materialised features live under, beside §4.2's ``snapshots/``
#: and ``staging/``.  A feature materialisation is *derived* data — a cache over
#: a sealed snapshot's bytes — so it does not belong inside the immutable
#: ``snapshots/`` tree, and it is not write-then-seal input, so it does not
#: belong in ``staging/`` either.
FEATURES_DIRECTORY = "features"

#: Appended to the final path segment of :meth:`FeatureKey.to_path`.  Kept as a
#: constant so a reader asking "is this a materialised feature?" and a writer
#: naming the file cannot disagree about the spelling.
MATERIALISED_SUFFIX = ".parquet"


class MaterialisationError(ValueError):
    """A feature could not be materialised, or a materialisation was corrupt.

    Subclasses :class:`ValueError` because both causes are caller bugs or a
    damaged lake, never a condition to retry: a lake root that cannot be
    resolved, a ``compute`` callable that is not callable, and bytes under a
    key's path that are not the Parquet file this module wrote.  A *missing*
    dependency is deliberately not this type — :mod:`feature_store.parquet`
    raises :class:`ModuleNotFoundError` for that, because an environment
    problem is not a malformed feature.
    """


@dataclass(frozen=True, slots=True)
class MaterialisedFeature:
    """One feature's materialisation: where it is, what it holds, how it came.

    ``materialised`` is the fact this feature's contract turns on, and it is
    spelled as a boolean rather than inferred: ``True`` when *this call*
    computed the feature and wrote the file, ``False`` when the call found an
    existing file and reused it without computing.  Feature 50's ``cache_hit``
    is the materialiser's running reuse count *as it stood after this call*,
    snapshotted onto the result so a caller can log the counter per request
    without reaching back into the materialiser — the reuse, measured, rather
    than guessed from timing or from comparing payloads.

    ``rows`` are the decoded rows, identical in content either way — a reused
    materialisation and a fresh one return the same feature, which is what
    makes the reuse safe to do silently.  ``path`` is where the bytes live, so
    a caller that wants them (a DuckDB scan in place, §4.1) does not have to
    re-derive the path from the key.
    """

    key: FeatureKey
    path: Path
    rows: tuple[FeatureRow, ...]
    materialised: bool
    cache_hit: int = 0

    def __len__(self) -> int:
        """The number of rows materialised — the file's row count."""
        return len(self.rows)


class FeatureMaterialiser:
    """Materialises features to Parquet lazily, and reuses what it wrote.

    Bound to a lake root at construction, like its peer
    :class:`~snapshot.SnapshotService`.  Construction performs no I/O and
    reads no clock — it only records where the lake is and how to stamp rows
    that arrive unstamped — so a materialiser is safe to build at composition
    time in any environment, and directories are created on demand by the
    operation that needs one.

    Feature 50 is the measurement half that feature 49 deliberately leaves out
    (see the module docstring): the materialiser keeps a ``cache_hit`` counter
    that rises by one every time a request reuses an already-materialised
    feature instead of recomputing it, and a ``cache_miss`` counter for the
    calls that compute.  Both are process-memory only — never written to the
    lake, so a fresh materialiser over the same lake starts from zero, matching
    feature 49's disk-only persistence — and are exposed with :meth:`cache_hit`,
    :meth:`cache_miss`, :meth:`cache_hit_rate` and :meth:`reset_cache_stats`.
    """

    def __init__(
        self,
        lake_root: Union[str, os.PathLike[str]],
        *,
        clock: Optional[Callable[[], Any]] = None,
    ) -> None:
        if isinstance(lake_root, str) and not lake_root.strip():
            # Path("") would silently become "." — materialising into the
            # current directory is never what a caller meant.
            raise MaterialisationError("lake root must be a non-empty path")
        self._lake_root = Path(lake_root).expanduser()
        # The clock is injected, never reached for (feature 51's discipline):
        # a replay stamps the instant it is reproducing, and a test pins one.
        # ``None`` means ``utc_now`` at the moment a write needs it, so the
        # default stays a call at use rather than an instant frozen at build.
        self._clock = clock
        # Feature 50's measurement.  Two counters, not one: the hit rate is
        # hits / (hits + misses), and a single counter cannot yield both the
        # numerator and the denominator.  Plain ints, not itertools.count —
        # the counters are read by the accessors and reset wholesale.
        self._cache_hit = 0
        self._cache_miss = 0

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        clock: Optional[Callable[[], Any]] = None,
    ) -> "FeatureMaterialiser":
        """Resolve the lake root the way the rest of the system states it.

        ``LAKE_ROOT`` wins when set (an empty or whitespace-only value counts
        as unset, mirroring the shared fixtures' treatment of
        ``TEST_DATABASE_URL`` and :meth:`snapshot.SnapshotService.from_env`).
        Otherwise the root defaults to ``lake/`` beside the workspace root —
        the location §4.2 draws — located via the factory's workspace
        discovery rather than a hard-coded guess, so the default can never
        silently point somewhere the declaration does not cover.  With neither
        available this refuses to guess: raising a clear error beats
        materialising into ``/``.
        """
        source = os.environ if env is None else env
        raw = source.get(LAKE_ROOT_ENV, "").strip()
        if raw:
            return cls(Path(raw), clock=clock)
        workspace_root = find_workspace_root()
        if workspace_root is not None:
            return cls(workspace_root / "lake", clock=clock)
        raise MaterialisationError(
            f"{LAKE_ROOT_ENV} is not set and no uv workspace root was found "
            "above this package; set LAKE_ROOT to the lake root (§4.2)"
        )

    # -- Paths --------------------------------------------------------------

    @property
    def lake_root(self) -> Path:
        """The lake root materialisations are written under."""
        return self._lake_root

    @property
    def features_root(self) -> Path:
        """Where materialised features live (§4.4, beside ``snapshots/``)."""
        return self._lake_root / FEATURES_DIRECTORY

    # -- Feature 50: measuring the reuse -----------------------------------

    @property
    def cache_hit(self) -> int:
        """How many requests so far reused a stored feature (feature 50).

        Rises by one on every :meth:`materialise` call that finds an existing
        file and returns it without calling ``compute`` — the reuse path.  A
        miss (a compute) or a deliberate ``replace=True`` does not move it, so
        the counter counts *silent* reuse only, never the recomputations the
        ordinary path never performs.  Process-memory only: a fresh
        materialiser over the same lake starts at zero, exactly as feature 49's
        persistence is disk-only.
        """
        return self._cache_hit

    @property
    def cache_miss(self) -> int:
        """How many requests so far computed a feature that was not stored.

        The denominator's other half: one per :meth:`materialise` call that
        called ``compute`` and wrote a file.  A ``replace=True`` recompute
        counts as a miss, because it did the work a miss does.  Exposed
        alongside :attr:`cache_hit` so :attr:`cache_hit_rate` has both terms.
        """
        return self._cache_miss

    @property
    def cache_hit_rate(self) -> float:
        """The fraction of requests that reused a stored feature.

        ``cache_hit / (cache_hit + cache_miss)`` — the reuse depth of the lake
        as a ratio in ``[0, 1]`` rather than a raw count, so two lakes of
        different sizes can be compared.  Returns ``0.0`` before any request,
        when there is no reuse to measure, rather than dividing by zero.
        """
        total = self._cache_hit + self._cache_miss
        return self._cache_hit / total if total else 0.0

    def reset_cache_stats(self) -> None:
        """Return both counters to zero, bounding the measurement window.

        A replay that must reproduce one window's hit rate, or a test that
        measures a single scenario in isolation, resets before it begins so an
        earlier scenario's counts cannot bleed in.  Deliberate and explicit —
        the counters otherwise accumulate for the life of the materialiser,
        which is what makes a long-running process's rate meaningful.
        """
        self._cache_hit = 0
        self._cache_miss = 0

    def path_for(self, key: FeatureKey) -> Path:
        """The Parquet path ``key``'s materialisation lives at.

        The key's own five-segment path — ``feature_name``, ``feature_version``,
        ``snapshot_hash``, ``symbol``, ``frequency`` — under
        :attr:`features_root`, with :data:`MATERIALISED_SUFFIX` on the last
        segment.  Deterministic, and derived from the key alone, so two callers
        asking where a feature lives never disagree and no separate index has
        to be kept in step with the files.

        The result is checked to resolve under :attr:`features_root` before it
        is returned.  Feature 48 validates every key component path-safe at
        construction — no separators, no ``..``, no control characters — so
        this check cannot fire for a real :class:`FeatureKey`; it is here
        because "cannot fire" and "must not fire" are different claims, and the
        consequence of being wrong is a write outside the lake.
        """
        relative = key.to_path()
        candidate = self.features_root.joinpath(
            *relative.parts[:-1], relative.parts[-1] + MATERIALISED_SUFFIX
        )
        root = self.features_root.resolve(strict=False)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise MaterialisationError(
                f"the materialisation path for {key} resolves to {resolved}, "
                f"which is outside the lake's features area ({root}); a key "
                "component escaped its path segment, which feature 48's "
                "validation exists to prevent"
            )
        return candidate

    def is_materialised(self, key: FeatureKey) -> bool:
        """Whether ``key`` already has a materialisation on disk.

        The cheap half of the lazy check — a ``stat``, no read and no compute —
        for a caller that wants to know whether a request would compute
        anything before making it.  A *file* is the question; whether its bytes
        are readable Parquet is :meth:`load`'s to answer, because a corrupt
        materialisation is a different fact from a missing one.
        """
        return self.path_for(key).is_file()

    # -- Materialising ------------------------------------------------------

    def materialise(
        self,
        key: FeatureKey,
        compute: Callable[[], Union[Iterable[Mapping[str, Any]], Iterable[FeatureRow]]],
        *,
        replace: bool = False,
    ) -> MaterialisedFeature:
        """Return ``key``'s feature, computing it only if nothing is stored.

        The whole of feature 49 at its seam.  On a hit — a Parquet file already
        at :meth:`path_for` — the file is read and returned and ``compute`` is
        **never called**: that is the "persisting the result for later reuse"
        clause, and the returned
        :class:`MaterialisedFeature` reports it as ``materialised=False``.  On
        a miss, ``compute`` is called for the rows, the rows are encoded to
        Zstd Parquet, the file is written atomically, and the result comes back
        as ``materialised=True``.  Either way the rows returned describe the
        same feature, which is what makes reusing the stored one safe.

        ``compute`` takes no arguments and returns the feature's rows — as
        :class:`~feature_store.rows.FeatureRow` objects already stamped by
        feature 51, or as plain mappings this module stamps with its clock
        (see the module docstring for why the definition is the caller's and
        the cache is this module's).  It is called at most once per call.

        ``replace=True`` recomputes and overwrites even on a hit, for the case
        where the same key must deliberately be recomputed — the same explicit
        decision :meth:`~feature_store.store.FeatureStore.put` requires before
        it overwrites.  The ordinary path never needs it: a changed definition
        gets a new ``feature_version``, hence a new key and a new file
        (features 48/53), so it lands beside this one rather than over it.
        """
        path = self.path_for(key)
        if not replace and path.is_file():
            # Feature 50's reuse path: a stored file is found and returned
            # without calling compute (feature 49's "later reuse"), and the
            # hit counter rises to record that this request was served from
            # the cache rather than recomputed.  The count is snapshotted onto
            # the result so the caller can log the counter at this request
            # without reaching back into the materialiser.
            self._cache_hit += 1
            return MaterialisedFeature(
                key=key,
                path=path,
                rows=self._read(path),
                materialised=False,
                cache_hit=self._cache_hit,
            )
        if not callable(compute):
            raise MaterialisationError(
                "materialise needs a zero-argument callable returning the "
                f"feature's rows; got {type(compute).__name__}"
            )
        # A miss: compute did the work the cache could not spare.  Counted
        # separately from a hit so the hit rate has both terms; a
        # replace=True recompute lands here too, because it did the work a
        # miss does rather than reusing a stored result.
        self._cache_miss += 1
        rows = self._stamped(compute())
        self._write(path, encode_parquet(rows))
        return MaterialisedFeature(
            key=key, path=path, rows=rows, materialised=True,
            cache_hit=self._cache_hit,
        )

    def load(self, key: FeatureKey) -> Optional[tuple[FeatureRow, ...]]:
        """The rows of ``key``'s materialisation, or ``None`` if none exists.

        The read half without the compute half: never calls anything to produce
        the feature, so a caller that wants "what is materialised" rather than
        "materialise this" can ask without supplying a definition.  ``None`` is
        a normal miss — nothing has been materialised under this key yet — and
        is exactly the state :meth:`materialise` acts on.  Bytes that exist but
        are not a readable materialisation are refused rather than reported as
        absent: a corrupt lake is not an unmaterialised feature, and a reader
        that cannot tell them apart would recompute over the evidence.
        """
        path = self.path_for(key)
        if not path.is_file():
            return None
        return self._read(path)

    # -- Internals ----------------------------------------------------------

    def _stamped(
        self, produced: Union[Iterable[Mapping[str, Any]], Iterable[FeatureRow]]
    ) -> tuple[FeatureRow, ...]:
        """The rows ``compute`` produced, stamped if they arrived unstamped.

        A definition that stamps as it computes (the normal case for feature
        51's row layer) hands :class:`FeatureRow` objects back and they are
        used as they are — re-stamping would restate a write-time fact, which
        is the one thing a stamp must never do.  Plain mappings are stamped
        here, through :func:`~feature_store.rows.stamp_rows`, so the batch
        still carries one instant for one write.  The two shapes are told apart
        by their elements rather than by a flag, so a caller does not have to
        declare which it is producing.
        """
        if isinstance(produced, (str, bytes)) or produced is None:
            raise MaterialisationError(
                "compute must return the feature's rows as a sequence of "
                "mappings or FeatureRows; got "
                f"{type(produced).__name__}. A materialisation is a batch of "
                "rows — return an empty sequence for a feature with no rows"
            )
        batch = list(produced)
        if not batch:
            return ()
        if isinstance(batch[0], FeatureRow):
            for index, row in enumerate(batch):
                if not isinstance(row, FeatureRow):
                    raise MaterialisationError(
                        f"compute returned a mix of rows and other values: "
                        f"element {index} is {type(row).__name__}, but "
                        "element 0 is a FeatureRow. Return one shape or the "
                        "other — mappings to be stamped here, or FeatureRows "
                        "stamped by the definition"
                    )
            return tuple(batch)
        # Not rows: hand the batch to the row layer, which validates the shape
        # and stamps the whole batch with one instant (feature 51).  Its own
        # error is re-raised as this layer's so a caller catching "the
        # materialisation failed" catches one type.
        try:
            return stamp_rows(batch, clock=self._clock or utc_now)
        except (TypeError, ValueError) as exc:
            raise MaterialisationError(
                f"compute returned rows this materialiser cannot stamp: {exc}"
            ) from exc

    @staticmethod
    def _read(path: Path) -> tuple[FeatureRow, ...]:
        """Decode a materialisation, refusing a corrupt one by name.

        The file is the cache, so bytes that do not decode are a damaged lake
        rather than an absent feature — reported with the path, so the operator
        can find the file, and with the remedy (``replace=True``), so the
        deliberate override is one keyword away.  Silently falling back to a
        recompute would be worse than either: it would destroy the corrupt
        bytes and hand back a different answer than the one a replay may have
        already read from this path.
        """
        try:
            return decode_parquet(path.read_bytes())
        except ParquetMaterialisationError as exc:
            raise MaterialisationError(
                f"the materialisation at {path} is not a readable Parquet "
                f"feature: {exc}. The lake is damaged rather than the feature "
                "unmaterialised; re-materialise deliberately with "
                "replace=True once the cause is understood"
            ) from exc

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        """Write ``payload`` to ``path`` atomically, creating parents.

        A uniquely-named temporary file in the destination directory, then
        ``os.replace`` — atomic on POSIX, so a reader sees the old file or the
        new one and never a partial write, and a crash mid-write leaves the
        lake as it was rather than a truncated file that would later read as
        corruption.  The temporary lives in the same directory rather than in
        ``tempfile``'s default location so the rename is within one filesystem,
        which is what makes ``os.replace`` atomic instead of a copy.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        finally:
            # A failed write or a lost race leaves at most a stray dotfile;
            # cleaning it here keeps the features area free of debris without
            # masking the error that caused it.
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


# The composed component that exposes this seam to the application factory —
# ``feature-materialiser`` — is registered by the package's ``__init__``
# rather than here, and deliberately so.  The factory's scan re-executes a
# package's top-level code on every ``create_app`` call but leaves submodules
# already cached in ``sys.modules`` alone, so a ``@register`` living in a
# submodule fires only on the *first* scan in a process and silently vanishes
# from every later composed application.  Registration belongs on the
# package's own import path, which is the one code path the scan always runs;
# see :func:`feature_store.build_feature_materialiser`.
