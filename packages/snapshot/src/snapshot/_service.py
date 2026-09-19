"""The sealing service: staging in, immutable snapshot directory out.

docs/nullius-tech-architecture.md §4.1-§4.2 describe the flow this module
implements: ingest workers append into a writable staging area, and on a
schedule that content is sealed into an immutable snapshot directory named
``<sealed_at>_<snapshot_hash[:6]>`` under the lake's ``snapshots/`` root.
The evaluator only ever opens sealed snapshots; staging never appears on its
mount path. This service owns the *write* side of that boundary.

**Immutability is enforced at three layers**, because a property announced
once and enforced nowhere is a comment, not a guarantee:

1. *Publication is atomic.* A seal builds its tree under a hidden
   ``.sealing-<random>`` working directory inside ``snapshots/`` and then
   renames it into place. ``rename(2)`` of a directory is atomic on POSIX,
   so no reader — and no crash — ever observes a half-written directory
   under a sealed name. An interrupted seal leaves at worst a stray working
   directory, never a corrupt snapshot.
2. *The published bytes are read-only.* Every file is persisted mode
   ``0444`` and every directory ``0555`` before the rename, so an ordinary
   write through a sealed path fails with ``PermissionError`` at the
   filesystem itself. (An owner can chmod this away; this layer is tripwire
   and contract, with the API layer doing the structural work.)
3. *The API has no mutating surface and refuses overwrites.* Sealing a name
   that already exists re-reads what the directory persists — its manifest,
   or for a pre-manifest snapshot its bytes — and either returns the
   identical record (an idempotent re-seal — the schedule crashed after the
   rename, say) or raises :class:`SnapshotAlreadySealedError` when the
   identity differs. There is no code path that edits, extends, or replaces
   a sealed directory, and the returned record is frozen with a read-only
   file mapping (see ``_records``). The refusal reaches one granularity
   further than names: an *identity* already assigned to other bytes is
   refused under any name (:class:`SnapshotHashReusedError`, feature 38 —
   see the paragraph below).

Staging is *copied*, never moved or emptied: the §4.1 contract keeps staging
append-only and owned by the ingest workers, so a seal is a pure read from
their side. And staging is refused on the read side too: :meth:`open` rejects
a request that names the staging area with a :class:`SnapshotStagingRequestError`
(feature 35 — *"staging is never on the evaluator mount path"*), stating the
contract and pointing the evaluator at the sealed snapshots it may open. That
refusal is the read-side twin of feature 28's layout guarantee, and it is the
mount's door: ``mount`` goes through ``open``, so a request for staging never
reaches a mount either.

**Opening is verifying (feature 36).** The immutability above is enforced
against every *API* surface, but the frozen modes are ownership-governed —
the sealing user can ``chmod`` them away and write, the documented crack
``_mount`` states. :meth:`open` is where that crack is detected rather
than merely repaired: it recomputes the sha256 of every file the
snapshot's ``MANIFEST.json`` records and refuses — with
:class:`SnapshotCorruptionError` carrying the full
:class:`CorruptionAlert` — when any recorded hash fails to match, when a
recorded file is missing, or when the tree holds a node the manifest never
recorded (see ``_verification``). Every door built on ``open`` inherits
the check: a corrupt snapshot cannot be mounted, and its manifest is not
believed. :meth:`verify` returns the same alert as data instead of a
refusal, and :meth:`verify_all` sweeps the lake with it.

**The manifest is the snapshot's on-disk identity (feature 31).** Every seal
writes a ``MANIFEST.json`` into the published tree — the per-file sha256
mapping this service already computes, each file's row count read from its
own format (Parquet footers; line counts; explicit ``null`` where a format
carries no rows), and the universe definition the caller asserts via
``universe=`` — so the lake itself, not any caller's memory, holds the full
64-character snapshot hash and everything it covers
(:meth:`read_manifest` reads it back, through the same strict door as
``open``). The manifest *describes* content and therefore is not content:
it never enters the seal's file mapping or the content digest, and staging
that already contains a root ``MANIFEST.json`` is refused rather than
overwritten (see ``_manifest``). Its persistence also closes the prefix
gap the re-seal check used to have — an existing directory's manifest
pins its full hash, so the same bytes can no longer be re-sealed under a
different identity that happens to share six characters.

**The record is what a score names (feature 33).** A snapshot's own
``MANIFEST.json`` travels with its bytes and is reachable only by opening
that one directory; feature 33 asks for the *record* — the same facts,
written to the relational store under the snapshot's full hash, so a score
that stamps a ``snapshot_hash`` (§4.4) can be joined to the exact bytes it
was computed over. Every seal writes that row (:meth:`persisted` reads it
back, :meth:`manifest_records` sweeps them, :meth:`unrecorded` names the
sealed snapshots the store does not carry). The row is written *after*
publication, never before, so a crash can leave a snapshot without a
record but never a record without a snapshot. *Every* seal is recorded,
including one whose files carry no row concept: the feature says "each", and
a snapshot skipped to protect the ``row_count`` column would be one whose
bytes no score could name — so an unknown total is stored as ``NULL`` and
mirrors the manifest's own ``None`` field for field (the deviation, and why
it beats the alternatives, is stated in ``_manifest_store``). The one
remaining limit is a lake with no ``DATABASE_URL``, which records nothing
and is supported rather than broken. The second copy is also what
:meth:`record_findings`
compares against: a manifest rewritten *wholesale* is undetectable from
inside its own directory, and detectable against a row written once at seal
time and never edited.

The default snapshot hash is the full §4.2 formula (feature 32,
``_identity.snapshot_digest``): a sha256 over the staged files' sorted
hashes, the asserted universe definition, and the lake's schema version.
The universe and schema terms are not decoration — the same bytes sealed
against a different definition of the world, or under a different data
schema, are a different snapshot by construction and seal under their own
name rather than colliding with the old one. A caller who has already
decided the identity — a seal retry replaying it, a test pinning a name —
supplies the full hash via ``snapshot_hash=`` and the seal honours it,
deriving the directory's prefix from it. The hash is the identity and
identity is the caller's to assert — *within what the lake has not already
assigned* (see the paragraph below): a supplied hash is not verified
against the staged content (a caller replaying a decision pins exactly the
hash it decided, formula or no), but it is verified against the lake's
prior assignments.

**A snapshot_hash is assigned once, to one set of bytes (feature 38).**
Extending the lake — ingest appends more bars, a symbol is added, the
universe turns over a month — changes the staged content, and the formula
over the changed content is a different hash: the extension is sealed under
its own new identity, beside the snapshot it grew from. That new hash is
the whole invalidation mechanism: scores and features are keyed by
``snapshot_hash`` (§4.4, feature 48), so a new hash is a guaranteed cache
miss — the scores cached under the old hash are invalidated (recomputed on
demand) rather than silently reused for bytes they never saw. The seal
enforces the assign-once half explicitly: before publishing, it reads the
assignments the lake itself persists — every sealed snapshot's manifest
binds its full hash to its file mapping — and refuses, with
:class:`SnapshotHashReusedError`, to publish a hash already bound to
different bytes under any name (``_assert_identity_is_fresh``). The same
hash over the *same* bytes is the idempotent case and stays legal: a
schedule that re-seals unchanged staging re-asserts one identity, and the
scores cached under it remain exactly as valid as they were — invalidation
tracks the lake's content, not the calendar.
"""

from __future__ import annotations

import errno
import os
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional, Union

from app.module_loader import find_workspace_root

from ._content import walk_content
from ._errors import (
    SnapshotAlreadySealedError,
    SnapshotContentError,
    SnapshotError,
    SnapshotHashReusedError,
    SnapshotManifestError,
    SnapshotNotFoundError,
    SnapshotRecomputationError,
    SnapshotStagingRequestError,
    SnapshotStoreError,
)
from ._identity import canonical_universe, snapshot_digest, validate_universe
from ._manifest import (
    MANIFEST_NAME,
    SnapshotManifest,
    build_manifest,
    walk_sealed_content,
)
from ._manifest_store import (
    SnapshotManifestRecord,
    SnapshotManifestStore,
    verify_persisted,
)
from ._mount import SnapshotMount, materialize_read_only
from ._naming import (
    normalize_snapshot_hash,
    parse_snapshot_name,
    resolve_sealed_at,
    snapshot_name,
)
from ._recomputation import RecomputationRegistry, SupersessionRecord
from ._records import SealedSnapshot, SnapshotRef
from ._verification import CorruptionAlert, corruption_error, verify_tree

__all__ = ["LAKE_ROOT_ENV", "SnapshotService"]

#: Environment variable naming the lake root (documented in app_spec.xml
#: prerequisites; the shared fixtures in tests/conftest.py set it per test).
LAKE_ROOT_ENV = "LAKE_ROOT"

# Modes applied to a published snapshot: files readable by all, writable by
# no one; directories traversable and listable, modifiable by no one.
_FILE_MODE = 0o444
_DIRECTORY_MODE = 0o555

# rename(2) onto an existing non-empty directory reports one of these.
_COLLISION_ERRNOS = frozenset({errno.EEXIST, errno.ENOTEMPTY})


class SnapshotService:
    """Seals staged content into the lake's immutable ``snapshots/`` tree.

    Bound to a lake root at construction (see :meth:`from_env`). All paths
    the service touches live under that root: ``snapshots/`` for sealed
    output, ``staging/`` as the default seal source. Construction performs
    no I/O — the service is safe to build at composition time in any
    environment; directories are created on demand by the operations that
    need them.
    """

    def __init__(
        self,
        lake_root: Union[str, os.PathLike[str]],
        *,
        manifest_store: Optional[SnapshotManifestStore] = None,
    ) -> None:
        if isinstance(lake_root, str) and not lake_root.strip():
            # Path("") would silently become "." — sealing into the current
            # directory is never what a caller meant.
            raise SnapshotError("lake root must be a non-empty path")
        self._lake_root = Path(lake_root).expanduser()
        self._recomputation: Optional[RecomputationRegistry] = None
        # The persisted-record store of feature 33. Explicit wins over the
        # environment, so a test or an operator can hand a service the store
        # it wants; otherwise the environment decides at construction, the
        # same way the lake root is resolved by ``from_env``. ``None``
        # (nothing configured) is a supported state, not a broken one.
        self._manifest_store = (
            manifest_store
            if manifest_store is not None
            else SnapshotManifestStore.resolve()
        )

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "SnapshotService":
        """Resolve the lake root the way the rest of the system states it.

        ``LAKE_ROOT`` wins when set (an empty or whitespace-only value
        counts as unset, mirroring the shared fixtures' treatment of
        ``TEST_DATABASE_URL``). Otherwise the root defaults to ``lake/``
        beside the workspace root — the location §4.2 draws — located via
        the factory's workspace discovery rather than a hard-coded guess,
        so the default can never silently point somewhere the declaration
        does not cover. With neither available the service refuses to
        guess: raising a clear error beats sealing into ``/``.

        The ``snapshot_manifest`` store (feature 33) is resolved from
        ``DATABASE_URL`` at the same moment, so a composed application
        carries the lake *and* the record store the process is actually
        pointed at; ``env`` overrides both, which is how the shared test
        fixtures redirect them together.
        """
        source = os.environ if env is None else env
        raw = source.get(LAKE_ROOT_ENV, "").strip()
        store = SnapshotManifestStore.resolve(source)
        if raw:
            return cls(Path(raw), manifest_store=store)
        workspace_root = find_workspace_root()
        if workspace_root is not None:
            return cls(workspace_root / "lake", manifest_store=store)
        raise SnapshotError(
            f"{LAKE_ROOT_ENV} is not set and no uv workspace root was found "
            "above this package; set LAKE_ROOT to the lake root (§4.2)"
        )

    # -- Paths --------------------------------------------------------------

    @property
    def lake_root(self) -> Path:
        """The lake root this service writes under."""
        return self._lake_root

    @property
    def snapshots_root(self) -> Path:
        """Where sealed, immutable snapshots live (§4.2)."""
        return self._lake_root / "snapshots"

    @property
    def staging_root(self) -> Path:
        """The writable staging area; the default seal source (§4.2)."""
        return self._lake_root / "staging"

    @property
    def manifest_store(self) -> Optional[SnapshotManifestStore]:
        """The ``snapshot_manifest`` store this service persists rows into.

        ``None`` when no ``DATABASE_URL`` names one — a lake without a
        relational store, in which case a seal publishes and records
        nothing beyond its own ``MANIFEST.json``. Not an error state: the
        filesystem records are complete on their own, and this property is
        how a caller tells "no record was asked for" from "the record is
        missing" (:meth:`unrecorded`).
        """
        return self._manifest_store

    # -- Sealing ------------------------------------------------------------

    def seal(
        self,
        source: Optional[Union[str, os.PathLike[str]]] = None,
        *,
        sealed_at: Optional[Union[datetime, str]] = None,
        snapshot_hash: Optional[str] = None,
        universe: Optional[Mapping[str, object]] = None,
    ) -> SealedSnapshot:
        """Persist ``source`` as a sealed snapshot and return its record.

        ``source`` defaults to the lake's staging area — the §4.1
        seal-on-schedule flow. ``sealed_at`` defaults to now (UTC, second
        resolution); a caller driving the schedule supplies the instant.
        ``snapshot_hash`` defaults to the §4.2 formula over the staged
        content — the sorted per-file hashes plus the universe definition
        plus the lake schema version (``_identity``), so the definition the
        caller asserts is part of the identity the directory is named by
        (feature 32); supply the full 64-hex hash instead to seal under an
        identity decided elsewhere, such as a retry replaying a prior
        decision — but only an identity this lake has not yet assigned:
        a hash some sealed snapshot already carries over *different*
        bytes is refused with :class:`SnapshotHashReusedError` (feature 38),
        because publishing it would make scores cached under that hash
        silently stand for the extended content. ``universe`` is the
        universe definition the manifest records (feature 31) and the
        default hash folds: a JSON object — for the universe member's
        config, ``dataclasses.asdict(config)`` — or ``None`` to record that
        none was asserted; the identity docstring (``_identity``) states
        the exact treatment.

        The seal publishes a ``MANIFEST.json`` beside the content (per-file
        sha256, row counts, the universe definition and the full snapshot
        hash); :meth:`read_manifest` reads it back. Everything a bad
        argument can break — an unserialisable universe, a staged file
        whose rows cannot be read — is validated *before* any directory is
        created, so a refused seal leaves the lake exactly as it was.

        Re-sealing the *same* content under the same name is idempotent and
        returns the existing record; re-sealing *different* content under a
        name that exists raises :class:`SnapshotAlreadySealedError` and
        leaves the existing directory untouched. And when the lake has been
        *extended* — the staged content grew since a prior seal — the
        default identity is a new hash by construction, so the scores
        cached under the prior snapshot's hash are invalidated (they key on
        the old hash and no longer match) rather than silently reused
        (feature 38). The source is copied, not consumed.
        """
        source_path = (
            self.staging_root if source is None else Path(source).expanduser()
        )
        files = walk_content(source_path)
        if MANIFEST_NAME in files:
            # The published tree gets exactly one manifest: the one this
            # seal writes. Copying a staged manifest would either overwrite
            # staged bytes or publish a file the identity does not cover.
            raise SnapshotContentError(
                f"staged content already contains a {MANIFEST_NAME} at its "
                "root; a seal writes the snapshot's manifest itself — move "
                "or rename the staged file before sealing"
            )
        # Validated before the hash and the name: the definition is an
        # input to the identity (feature 32), so a bad one is refused
        # before any identity is computed with it — and before the
        # exists-check, which would otherwise compare raw unvalidated input.
        validated_universe = validate_universe(universe)
        full_hash = (
            snapshot_digest(files, universe=validated_universe)
            if snapshot_hash is None
            else normalize_snapshot_hash(snapshot_hash)
        )
        instant = resolve_sealed_at(sealed_at)
        name = snapshot_name(instant, full_hash)
        final = self.snapshots_root / name

        if final.exists():
            # The name is taken: identical bytes make this an idempotent
            # re-seal, different bytes an immutability violation.
            return self._existing_or_conflict(
                final, instant, full_hash, files, validated_universe
            )

        # The name is fresh; the identity must be too (feature 38). This is
        # the check that makes "assigns a new snapshot_hash when the lake is
        # extended" enforced rather than hoped for: a hash this lake has
        # already bound to other bytes cannot be published over this
        # content, under this name or any other.
        self._assert_identity_is_fresh(full_hash, files, name)

        manifest = build_manifest(
            files=files,
            source=source_path,
            snapshot_hash=full_hash,
            sealed_at=instant,
            universe=validated_universe,
        )
        manifest_bytes = manifest.to_json_bytes()
        self.snapshots_root.mkdir(parents=True, exist_ok=True)
        working = self.snapshots_root / f".sealing-{uuid.uuid4().hex}"
        try:
            _publish_tree(source_path, files, working, manifest_bytes)
            try:
                os.rename(working, final)
            except OSError as exc:
                if exc.errno not in _COLLISION_ERRNOS:
                    raise
                # Lost a race for the name: fall through to the same
                # identity check the pre-flight path performs.
                return self._existing_or_conflict(
                    final, instant, full_hash, files, validated_universe
                )
        finally:
            _discard_working_tree(working)
        record = SealedSnapshot(
            sealed_at=instant, snapshot_hash=full_hash, path=final, files=files
        )
        self._persist_manifest(manifest, manifest_bytes, record)
        return record

    def _persist_manifest(
        self,
        manifest: SnapshotManifest,
        manifest_bytes: bytes,
        record: SealedSnapshot,
    ) -> None:
        """Write the sealed snapshot into the ``snapshot_manifest`` record.

        Feature 33: *"System persists each sealed snapshot into the
        snapshot_manifest record so a score can name the exact bytes it was
        computed over."* Called once per seal, *after* the rename — the row
        describes a snapshot that exists, never one that might.

        Ordering is the point. A crash between the rename and this write
        leaves a sealed, verifiable snapshot with no row: recoverable by
        re-sealing (idempotent) or by a backfill sweep, and honest — the
        lake holds bytes nothing claims. The reverse order would leave a
        row pointing at a directory that does not exist, which is the state
        feature 33 exists to prevent, so the write follows the publish and
        never precedes it.

        A store that was never configured is not a failure: the seal
        publishes, and :meth:`persisted` reports that no record was asked
        for. A store that *is* configured and fails raises
        :class:`~snapshot.SnapshotStoreError` carrying the published
        ``record`` — the snapshot is real, its record is missing, and the
        caller is told both rather than left with a silent gap.
        """
        if self._manifest_store is None:
            return
        try:
            self._manifest_store.persist(manifest, manifest_bytes=manifest_bytes)
        except SnapshotStoreError as exc:
            # The store does not know which snapshot it failed to record —
            # it was handed a manifest, not a seal — so the published record
            # is attached here, where it is in hand. The caller then has
            # both halves: the snapshot exists and is verifiable, and its
            # record is what failed.
            raise SnapshotStoreError(str(exc), record=record) from exc

    def _reassert_record(
        self, manifest_file: Path, record: SealedSnapshot
    ) -> None:
        """Re-persist the row for a sealed snapshot that already exists.

        Called on the idempotent re-seal path so a missing row is repaired
        by the very call that is already a no-op for the directory (see
        :meth:`_existing_or_conflict` for why that matters). The manifest
        is read back from disk rather than rebuilt, so the row is written
        from exactly the bytes the snapshot carries — the same source the
        read side would consult, which is what makes the two comparable.

        The manifest's own content digest is *checked* on the way through
        (``SnapshotManifest.from_json_bytes``), so a tree whose manifest
        contradicts its entries cannot have a row written over it: the
        parse refuses first, and the seal reports a manifest error rather
        than persisting a record built from a document it could not believe.
        """
        if self._manifest_store is None:
            return
        manifest_bytes = manifest_file.read_bytes()
        manifest = SnapshotManifest.from_json_bytes(manifest_bytes)
        self._persist_manifest(manifest, manifest_bytes, record)

    def persisted(self, name: str) -> tuple[SnapshotManifestRecord, ...]:
        """The ``snapshot_manifest`` rows the store persists for ``name``.

        Feature 33's read side, and deliberately a *tuple* rather than a
        record or ``None``, because the interesting answers are several and
        the empty ones are real:

        * one row — the seal recorded this snapshot, and the row names the
          exact bytes it was computed over (``record.exact_bytes``). This
          is the answer for *every* snapshot sealed against a configured
          store, including one whose ``row_count`` is ``None`` because its
          files carry no row concept: the feature persists "each", so an
          unknown total costs the total, never the row;
        * an empty tuple *with a store configured* — this snapshot was not
          recorded, because it was sealed before the store was pointed at
          this lake or its row write failed. Re-sealing repairs either
          (see :meth:`_reassert_record`), and :meth:`unrecorded` is the
          report that names it;
        * an empty tuple *with no store configured at all* — no record was
          ever asked for. :attr:`manifest_store` tells the two apart;
        * an empty tuple for a snapshot that carries no manifest — sealed
          before feature 31, or built by hand. The row is keyed by a full
          hash only the manifest states, so such a snapshot can never have
          one; this is an absence, and :meth:`unrecorded` names it.

        The snapshot is opened first, so the request goes through the same
        verified door as every other read: staging requests are refused as
        staging requests, malformed names by the strict parser, misses as
        misses, and corrupt bytes are refused rather than resolved to a
        row. A caller that only wants the row and not the rehash uses
        :meth:`manifest_store` directly — the store is a plain table, and
        this method exists to make the common case go through the door.
        """
        ref = self.open(name)
        if self._manifest_store is None:
            return ()
        # The row is keyed by the full hash, which is the manifest's to
        # state (the directory name carries only its prefix). Going through
        # ``read_manifest`` would re-open and re-verify the tree a second
        # time; ``open`` has already done that, so the manifest is read here
        # from the path the verified door returned.
        manifest_file = ref.path / MANIFEST_NAME
        if not manifest_file.is_file():
            # A snapshot sealed before feature 31 has no manifest, so it has
            # no full hash and therefore no row, now or ever. The empty
            # answer is the honest one; letting the read raise a bare
            # ``FileNotFoundError`` would be a crash wearing another error's
            # clothes, and ``read_manifest`` is the door that refuses this
            # loudly for a caller who needs the manifest itself.
            return ()
        manifest = SnapshotManifest.from_json_bytes(manifest_file.read_bytes())
        return self._manifest_store.rows_for(manifest.snapshot_hash)

    def manifest_records(self) -> tuple[SnapshotManifestRecord, ...]:
        """Every ``snapshot_manifest`` row this lake's store persists.

        The sweep form: the whole record set as data, which is what an
        operator, a dashboard or a backfill job wants — the store-side twin
        of :meth:`sealed`. An empty tuple is either an empty store or no
        configured store; :attr:`manifest_store` says which, and neither is
        an error.
        """
        if self._manifest_store is None:
            return ()
        records: list[SnapshotManifestRecord] = []
        for snapshot_hash in self._manifest_store.hashes():
            records.extend(self._manifest_store.rows_for(snapshot_hash))
        return tuple(records)

    def unrecorded(self) -> tuple[str, ...]:
        """Sealed snapshot names with no ``snapshot_manifest`` row.

        The reconciliation report between the two stores: every directory
        the lake holds whose full hash the record store does not carry.
        For an operator after a crash between publish and persist, or after
        pointing ``DATABASE_URL`` at a lake that predates it — the list is
        the work a backfill has to do, named rather than described.

        Every seal writes a row, so this list is narrow and worth reading:
        a snapshot sealed before relational persistence, and one whose row
        write failed. Both are the honest statement the method exists to
        make — the lake holds bytes nothing recorded — and both are what a
        backfill repairs by re-sealing (see :meth:`_reassert_record`). A
        *pre-manifest* snapshot also appears here and cannot be repaired:
        with no manifest it states no full hash, so there is no primary key
        to write a row under. With no store configured every sealed
        snapshot is unrecorded, which is true and is not a failure.
        """
        if self._manifest_store is None:
            return tuple(self.sealed())
        recorded = set(self._manifest_store.hashes())
        return tuple(
            name
            for name in self.sealed()
            if self._full_hash_of(name) not in recorded
        )

    def _full_hash_of(self, name: str) -> Optional[str]:
        """The full hash a sealed directory's manifest records, if readable.

        ``None`` for a snapshot that carries no manifest — sealed before
        feature 31, or built by hand. Such a snapshot is not recorded and
        cannot be, since the record's primary key is a hash the tree does
        not state.
        """
        manifest_file = self.snapshots_root / name / MANIFEST_NAME
        if not manifest_file.is_file():
            return None
        try:
            manifest = SnapshotManifest.from_json_bytes(manifest_file.read_bytes())
        except (SnapshotManifestError, OSError):
            return None
        return manifest.snapshot_hash

    # -- Verifying the record (feature 33) -----------------------------------

    def record_findings(self, name: str) -> tuple[str, ...]:
        """Disagreements between a sealed manifest and its persisted row.

        Feature 33's verification half, in the non-raising form: the
        on-disk manifest (feature 31) and the row written at seal time are
        two independent records of the same snapshot, so they can be
        compared — and where they disagree, one of them was edited after
        the fact. The comparison catches what feature 36's on-disk check
        explicitly cannot: a manifest rewritten *wholesale*, every recorded
        hash edited to match tampered bytes, is internally perfect and is
        caught here against a row that was written once and never touched
        (see ``_manifest_store.verify_persisted`` for the boundary this
        still does not cross, stated rather than implied).

        Returns one line per disagreement, empty when the two agree. Three
        outcomes are *not* findings, because none of them is a mystery:

        * no store configured — no row was ever asked for;
        * a snapshot with no row — sealed before the store was pointed at
          this lake, or its row write failed. :meth:`unrecorded` is the
          report for that, and it names the snapshot rather than dressing
          an absence up as a disagreement;
        * a snapshot with no manifest — sealed before feature 31. There is
          nothing on the artifact side to compare the row against.

        A snapshot whose total rows are unknown *is* compared, like any
        other: its row is written with ``row_count IS NULL`` and its
        manifest records ``None``, so the two agree — and a row claiming an
        integer for a snapshot whose manifest says otherwise is a finding,
        which is exactly the disagreement this check is for.

        The request goes through :meth:`open` — so staging requests are
        refused as staging requests, malformed names by the strict parser,
        and misses as misses — but with ``verify=False``, deliberately and
        for a reason worth stating: the byte-level rehash of feature 36 is
        *the other check*, and it raises on exactly the tamper this one is
        meant to report. Rehashing first would make the record comparison
        unreachable in the case it exists for. The two are complements, not
        layers: :meth:`verify` answers "do the bytes match the manifest?",
        this answers "do the manifest and the record agree?", and an
        operator wants both answers, not the first one twice.
        """
        if self._manifest_store is None:
            return ()
        ref = self.open(name, verify=False)
        manifest_file = ref.path / MANIFEST_NAME
        if not manifest_file.is_file():
            return ()
        manifest_bytes = manifest_file.read_bytes()
        manifest = SnapshotManifest.from_json_bytes(manifest_bytes)
        record = self._manifest_store.record_for(manifest.snapshot_hash)
        if record is None:
            return ()
        return verify_persisted(manifest, record, manifest_bytes=manifest_bytes)

    def _existing_or_conflict(
        self,
        final: Path,
        instant: datetime,
        full_hash: str,
        files: Mapping[str, str],
        universe: Optional[Mapping[str, object]],
    ) -> SealedSnapshot:
        """Decide an already-named directory: idempotent return or refusal.

        A directory sealed since manifests landed (feature 31) carries its
        own identity on disk, and that is what decides: the persisted
        manifest's full snapshot hash must equal this call's (the manifest
        is what closed the prefix-only gap — two hashes sharing six
        characters are two identities, and the second is refused), its
        per-file mapping must match the staged content, and a caller
        asserting a *different* universe definition against a sealed one is
        refused rather than humoured. On all three counts matching, the
        retry is the very seal that already happened and the caller gets
        its record back. The manifest is trusted rather than re-walking
        the bytes here: it was written by the seal that published them,
        and the byte-level check against it is ``_verification``'s own
        contract (feature 36), enforced whenever the snapshot is opened.

        A directory *without* a manifest — sealed before feature 31, or
        built by hand — falls back to comparing the tree's content bytes
        against the staged mapping, manifest excluded. Identical mappings
        are the idempotent case; anything else is a genuine collision on
        an immutable name and is refused with the conflicting directory
        named in the error.

        The idempotent path also *re-asserts the record* (feature 33). The
        directory already exists, but the row may not: this is precisely
        the state a crash between the rename and the row write leaves, and
        it is also what a lake sealed before ``DATABASE_URL`` was pointed
        at it looks like. Re-sealing is the repair — it returns early from
        :meth:`seal` rather than reaching the publish path, so if the write
        did not happen here it would not happen at all, and the documented
        promise that a missed record is "recoverable by re-sealing" would
        be empty. The assertion is idempotent in the same way the seal is:
        a row that already exists is rewritten with the values it already
        holds.
        """
        if not final.is_dir():
            raise SnapshotAlreadySealedError(
                f"{final} exists but is not a snapshot directory; refusing "
                "to seal over it"
            )
        manifest_file = final / MANIFEST_NAME
        if manifest_file.is_file():
            replay = self._replay_or_conflict(
                final, manifest_file, full_hash, files, universe
            )
            self._reassert_record(manifest_file, replay)
            return replay
        existing = walk_sealed_content(final)
        if existing == files:
            return SealedSnapshot(
                sealed_at=instant,
                snapshot_hash=full_hash,
                path=final,
                files=files,
            )
        raise SnapshotAlreadySealedError(
            f"immutable snapshot {final.name} already exists with different "
            f"content ({len(existing)} files sealed vs {len(files)} staged); "
            "sealed directories are never overwritten"
        )

    def _replay_or_conflict(
        self,
        final: Path,
        manifest_file: Path,
        full_hash: str,
        files: Mapping[str, str],
        universe: Optional[Mapping[str, object]],
    ) -> SealedSnapshot:
        """Compare a retrying seal against the manifest already on disk."""
        try:
            persisted = SnapshotManifest.from_json_bytes(manifest_file.read_bytes())
        except SnapshotManifestError as exc:
            # Not silently re-sealable and not overwritable: both halves of
            # that sentence are the immutability contract.
            raise SnapshotAlreadySealedError(
                f"immutable snapshot {final.name} exists but its manifest "
                f"cannot be read ({exc}); sealed directories are never "
                "overwritten — verify the snapshot and deal with it "
                "deliberately, not by re-sealing over it"
            ) from exc
        if persisted.snapshot_hash != full_hash:
            raise SnapshotAlreadySealedError(
                f"immutable snapshot {final.name} is already sealed under "
                f"full hash {persisted.snapshot_hash}; refusing to seal the "
                f"same bytes as {full_hash} — the manifest pins the "
                "identity and sealed directories are never overwritten"
            )
        persisted_files = {
            path: entry.sha256 for path, entry in persisted.files.items()
        }
        if persisted_files != dict(files):
            raise SnapshotAlreadySealedError(
                f"immutable snapshot {final.name} already exists with "
                f"different content ({persisted.file_count} files sealed "
                f"vs {len(files)} staged); sealed directories are never "
                "overwritten"
            )
        # Since the formula became the default identity (feature 32), a
        # retry asserting a different universe computes a different hash and
        # lands under its own name; this refusal guards the path that pins
        # the name explicitly — one immutable identity must not be
        # re-asserted against a different definition of the world.
        if universe is not None and canonical_universe(universe) != canonical_universe(
            persisted.universe
        ):
            raise SnapshotAlreadySealedError(
                f"immutable snapshot {final.name} is already sealed with a "
                "different universe definition; sealed directories are "
                "never overwritten"
            )
        return SealedSnapshot(
            sealed_at=persisted.sealed_at,
            snapshot_hash=full_hash,
            path=final,
            files=files,
        )

    def _assert_identity_is_fresh(
        self,
        full_hash: str,
        files: Mapping[str, str],
        candidate_name: str,
    ) -> None:
        """Refuse a snapshot_hash this lake has already assigned to other bytes.

        The identity-side twin of the name check above, and feature 38's
        enforcement point. A directory name collides only with itself, but
        a snapshot_hash is *content addressing*: everything downstream keys
        on it — §4.4's feature rows, the trial ledger's provenance stamps —
        so a hash published over one set of bytes and then re-published
        over another makes every score cached under it silently describe
        data it was never computed over. That reuse is exactly what the
        feature refuses: when the lake is extended, the extension gets a
        *new* hash (the formula over the new content produces one), the old
        hash keeps naming the old bytes, and cached scores keyed by the old
        hash miss rather than match.

        The assignments are read from the lake itself — every sealed
        snapshot's ``MANIFEST.json`` *is* its persisted assignment of a
        full hash to a file mapping — so the check needs no memory or
        registry of its own and cannot drift from what the lake actually
        says. The candidate's own directory is skipped: its name was just
        found fresh, and same-name identity questions belong to the checks
        above. Three granularities of honest ignorance are skipped rather
        than guessed: a directory with no manifest (sealed before feature
        31 — the name-level checks still cover it), a manifest that cannot
        be parsed (it proves no binding, and refusing every future seal
        over one corrupt neighbour would brick the write path), and a
        manifest bound to *identical* bytes (not a reuse at all: the same
        identity over the same content is the idempotent case, however
        many directories carry it — a schedule that re-seals unchanged
        staging at a later instant legitimately re-asserts one identity).

        Only a caller-supplied ``snapshot_hash=`` can reach this refusal in
        practice — the computed digest differs whenever the content does,
        so a computed collision is a sha256 break refused on principle —
        which is precisely the reachable hole: a schedule replaying a stale
        decision over a lake that has since grown.
        """
        for name in self.sealed():
            if name == candidate_name:
                continue
            manifest_file = self.snapshots_root / name / MANIFEST_NAME
            if not manifest_file.is_file():
                continue
            try:
                persisted = SnapshotManifest.from_json_bytes(
                    manifest_file.read_bytes()
                )
            except SnapshotManifestError:
                continue
            if persisted.snapshot_hash != full_hash:
                continue
            persisted_files = {
                path: entry.sha256 for path, entry in persisted.files.items()
            }
            if persisted_files == dict(files):
                continue
            raise SnapshotHashReusedError(
                f"snapshot_hash {full_hash} is already assigned to sealed "
                f"snapshot {name} ({persisted.file_count} files); refusing "
                f"to bind it to different staged content ({len(files)} "
                "files). When the lake is extended the seal is assigned a "
                "new snapshot_hash — the formula over the extended content — "
                "so scores cached under the old one are invalidated rather "
                "than silently reused; drop snapshot_hash= and let the "
                "seal compute the extended lake's own identity"
            )

    # -- Reading ------------------------------------------------------------

    def open(self, name: str, *, verify: bool = True) -> SnapshotRef:
        """Return the sealed snapshot addressed by a canonical directory name.

        The evaluator's door (§4.2: *"the evaluator can only open sealed
        snapshots; staging is not on its mount path at all"*). Four refusals,
        in order — three about the *name*, and then one about the *bytes*:

        1. *A request that names the staging area* — ``"staging"``,
           ``"staging/bars/part-0.parquet"`` — is refused first, and
           *explicitly*, as :class:`SnapshotStagingRequestError`. This is the
           refusal feature 35 specifies: not a generic "that is not a snapshot
           name", but a statement of the contract — staging is the ingest
           workers' writable area and is never on the evaluator's mount path,
           and the sealed snapshots returned by :meth:`sealed` are what the
           evaluator may open instead. A staging request is checked before the
           strict parser, because refusing it as a malformed name would hide
           the very fact the evaluator needs to learn.
        2. *A malformed name* — anything that is not ``<sealed_at>_<prefix>``,
           including traversal such as ``../staging`` — is rejected by the
           strict parser as a :class:`SnapshotNameError`, before it ever
           becomes a path.
        3. *A name that parses but names nothing* raises
           :class:`SnapshotNotFoundError`.
        4. *A directory whose bytes no longer match its record* is refused as
           corrupt (feature 36): every sha256 the snapshot's ``MANIFEST.json``
           records is recomputed against the tree, and any disagreement — a
           file whose bytes hash differently, a recorded file that is absent,
           a node the manifest never recorded, an injected symlink — raises
           :class:`SnapshotCorruptionError` carrying the full
           :class:`CorruptionAlert` (see ``_verification``). The frozen modes
           sealing persists can be ``chmod``'d away by their owner; the
           recorded hashes cannot be argued with, so the door trusts the
           record over the modes. A snapshot sealed before manifests carries
           no record to check against and opens as before — vacuously
           verified — while :meth:`read_manifest` refuses the absent
           manifest loudly; a manifest that cannot be parsed propagates
           :class:`SnapshotManifestError` unchanged.

        ``verify=False`` skips the rehash for a caller that has verified the
        tree already and takes the consequence on itself — a performance
        seam, the read-side twin of ``mount``'s ``reassert_modes``. The
        default is the feature: an open is a claim that the bytes are the
        sealed ones.
        """
        if self._names_staging(name):
            raise SnapshotStagingRequestError(
                f"request {name!r} names the staging area {self.staging_root}, "
                "which is never on the evaluator mount path; staging is the "
                "ingest workers' writable area, not a sealed snapshot — open "
                "one of the sealed snapshots instead (SnapshotService.sealed)"
            )
        parse_snapshot_name(name)  # validation only; the ref re-parses lazily
        path = self.snapshots_root / name
        if not path.is_dir():
            raise SnapshotNotFoundError(
                f"no sealed snapshot named {name!r} under {self.snapshots_root}"
            )
        if verify:
            alert = verify_tree(path)
            if alert is not None:
                raise corruption_error(alert)
        return SnapshotRef(name=name, path=path)

    def verify(self, name: str) -> Optional[CorruptionAlert]:
        """Verify the named snapshot; return its alert, or ``None`` if clean.

        The non-raising form of :meth:`open`'s fourth refusal (feature 36):
        the same recomputation of every recorded sha256, the same comparison
        against the tree, but the result is *data* rather than a refusal —
        for a monitor, an operator sweep, or a caller that wants to report
        corruption rather than be stopped by it. ``None`` means every
        recorded hash matched and the tree holds nothing the manifest fails
        to cover; a :class:`CorruptionAlert` carries one finding per
        discrepancy, sorted by path.

        The request goes through the same door as any read — staging
        requests are refused as staging requests, malformed names by the
        strict parser, misses as misses — so a verification can never be
        pointed at anything but a sealed snapshot of this lake.
        """
        return verify_tree(self.open(name, verify=False).path)

    def verify_all(self) -> tuple[CorruptionAlert, ...]:
        """Verify every sealed snapshot in the lake, and report every alert.

        The sweep form of feature 36: one alert per corrupt snapshot, so a
        single bad tree neither hides its neighbours nor stops the audit —
        the raising door would halt at the first corruption it met, which
        is right for an evaluator and wrong for a monitor. An empty tuple
        is the healthy lake, stated as data rather than as silence.

        A snapshot whose manifest cannot be parsed propagates
        :class:`SnapshotManifestError` rather than being skipped: a sweep
        that quietly jumped over a snapshot it could not read would report
        health it never established.
        """
        alerts: list[CorruptionAlert] = []
        for name in self.sealed():
            alert = self.verify(name)
            if alert is not None:
                alerts.append(alert)
        return tuple(alerts)

    def read_manifest(self, name: str) -> SnapshotManifest:
        """Read the MANIFEST.json of the sealed snapshot called ``name``.

        The manifest is what the lake persists about a snapshot beyond its
        directory name (feature 31): the full snapshot hash, the per-file
        sha256 entries with their row counts, and the universe definition
        asserted at seal time. The request goes through :meth:`open`'s
        verified door — staging requests are refused as staging requests,
        malformed names by the strict parser, misses as misses, and the
        bytes the manifest describes are re-hashed against its entries
        before the record is believed (feature 36) — because a manifest
        read is a read of a sealed snapshot like any other, and a record
        handed out over corrupt bytes is a claim nobody checked.

        Two integrity cross-checks come free with the door: the manifest's
        recorded hash must carry the prefix the directory was named under,
        and its ``sealed_at`` must be the instant the name encodes. A
        manifest that disagrees with its own directory is refused with
        :class:`SnapshotManifestError` rather than returned half-believed.
        """
        ref = self.open(name)
        manifest_file = ref.path / MANIFEST_NAME
        if not manifest_file.is_file():
            raise SnapshotManifestError(
                f"sealed snapshot {name!r} carries no {MANIFEST_NAME}; it "
                "was sealed before manifests were persisted or its tree is "
                "incomplete"
            )
        manifest = SnapshotManifest.from_json_bytes(manifest_file.read_bytes())
        if manifest.hash_prefix != ref.hash_prefix:
            raise SnapshotManifestError(
                f"the manifest of {name!r} records full hash "
                f"{manifest.snapshot_hash}, whose prefix does not match the "
                "directory name; the manifest and the directory disagree"
            )
        if manifest.sealed_at != ref.sealed_at:
            raise SnapshotManifestError(
                f"the manifest of {name!r} records sealed_at "
                f"{manifest.sealed_at.isoformat()}, which is not the "
                "instant the directory name encodes; the manifest and the "
                "directory disagree"
            )
        return manifest

    def _names_staging(self, name: str) -> bool:
        """Whether a request resolves onto the lake's staging area.

        The one request that is a miss *for a reason*: a name whose first
        component is the lake's staging directory — ``"staging"``,
        ``"staging/bars/part-0.parquet"`` — resolves onto the writable area
        the evaluator never sees, rather than under ``snapshots/``. Detecting
        it by containment (the resolved request lands in the resolved staging
        root) rather than by string match keeps it correct for any spelling
        and independent of the naming contract it sits beside. A canonical
        ``<sealed_at>_<prefix>`` name resolves under ``snapshots/`` and never
        matches, so this check never shadows a genuine snapshot request.
        """
        candidate = (self.lake_root / name).resolve(strict=False)
        staging = self.staging_root.resolve(strict=False)
        return candidate == staging or staging in candidate.parents

    def mount(self, name: str, *, reassert_modes: bool = True, verify: bool = True) -> SnapshotMount:
        """Mount a sealed snapshot read-only, by canonical directory name.

        This is the evaluator's door (§4.2: *"a snapshot is sealed, hashed,
        and mounted read-only; the evaluator can only open sealed
        snapshots"*). The name goes through the same strict parser
        :meth:`open` uses, so a request naming a staging path — or any name
        that is not ``<sealed_at>_<hash prefix>`` — is refused as a
        malformed name rather than resolved; a canonical name that names
        nothing raises :class:`SnapshotNotFoundError`. Only then is a mount
        built.

        The mount also inherits :meth:`open`'s verification (feature 36):
        the snapshot's bytes are re-hashed against its manifest before the
        mount exists, so a corrupt snapshot cannot be mounted — serving
        tampered bytes through the read-only mount that exists to serve
        sealed ones would invert the feature this category is about.
        ``verify=False`` skips the rehash for a caller that verified the
        tree already (the same performance seam as ``reassert_modes``).

        Opening the mount re-asserts the sealed modes across the tree (see
        :func:`snapshot.materialize_read_only`), which is a tightening, never
        a grant: a snapshot whose permissions drifted — a copy, a restore —
        is put back under the contract before anyone reads through it.
        ``reassert_modes=False`` skips that pass for a read-only filesystem
        where the walk would be wasted work; the mount's own refusals are
        structural and do not depend on it.

        Writes through the returned mount — and through any path it hands
        out — raise :class:`~snapshot.SnapshotReadOnlyError`, a
        ``PermissionError`` naming the operation and the sealed path.
        """
        ref = self.open(name, verify=verify)
        corrections = materialize_read_only(ref.path) if reassert_modes else 0
        return SnapshotMount(
            name=ref.name,
            path=ref.path,
            modes_reasserted=reassert_modes,
            modes_corrected=corrections,
        )

    def mounted(self) -> list[SnapshotMount]:
        """Mount every sealed snapshot in this lake, sorted by name.

        The sweep an evaluator host performs at start-up — or an operator
        after a restore — and the moment the mode re-assertion pays for
        itself, since it visits every snapshot's tree once. The same sweep
        is now an integrity audit too: each mount verifies its snapshot's
        bytes against the manifest (feature 36), so a tree that drifted or
        was tampered with stops the sweep with
        :class:`SnapshotCorruptionError` — a host that wants the findings
        as data instead uses :meth:`verify_all`.
        """
        return [self.mount(name) for name in self.sealed()]

    def sealed(self) -> list[str]:
        """List the sealed snapshots in this lake, sorted by name.

        Only directories whose names parse as canonical snapshot names are
        reported: working directories from interrupted seals and any stray
        files under ``snapshots/`` are not snapshots and stay invisible
        here. A missing ``snapshots/`` root is simply an empty lake.
        """
        if not self.snapshots_root.is_dir():
            return []
        names = [
            entry.name
            for entry in self.snapshots_root.iterdir()
            if entry.is_dir() and _parses(entry.name)
        ]
        return sorted(names)

    # -- Recomputation (feature 39) -----------------------------------------

    @property
    def recomputation(self) -> RecomputationRegistry:
        """The recomputation registry persisted at this lake's root.

        Feature 39's store: it holds every score the lake knows, each
        anchored to the discovery-tree node it decorates and the
        ``snapshot_hash`` it was computed over, with the ``recompute`` flag a
        snapshot change flips. It lives at ``<lake>/recomputation.json``
        beside ``snapshots/`` and ``staging/`` (§4.2), so a flag one process
        sets is the flag another reads. The registry holds only the
        addressing and the flag — never a score's value or a node's meaning —
        it is the invalidation signal, and the derived zone owns the
        recomputation the signal points at.

        One instance is held for the life of the service, so registering a
        score and then recording a change over it act on the same in-memory
        state; the flag is still persisted to disk on every write, so a
        separate process reading the file sees it too.
        """
        if self._recomputation is None:
            self._recomputation = RecomputationRegistry(self._lake_root)
        return self._recomputation

    def record_snapshot_change(
        self,
        old_hash: str,
        new_hash: str,
    ) -> SupersessionRecord:
        """Flag every score under ``old_hash`` as superseded by ``new_hash``.

        The event feature 39 is about, grounded in this lake. Feature 38
        produces the new hash when the lake is extended; this turns it into a
        recomputation signal: every score the lake persisted under the old
        hash is flagged ``recompute=True`` and the supersession is written to
        the audit, while the discovery tree's nodes and edges are left exactly
        as they were — the tree structure survives; the scores under it do
        not.

        The change is verified against the lake before it is applied, because
        a recomputation flag anchored to a hash the lake does not hold would
        flag scores that do not exist: both hashes must name snapshots this
        lake actually seals (``open``), and the old hash must hold scores the
        registry was told about. A hash that names nothing, or a hash the
        registry holds no scores under, is refused with
        :class:`SnapshotRecomputationError`, leaving the registry untouched.

        Returns the :class:`~snapshot.SupersessionRecord` — the audit entry
        carrying the old and new hashes, when the change was recorded, and how
        many scores it flagged.
        """
        # Both hashes must name a snapshot this lake actually seals. A change
        # anchored to a hash the lake does not hold — a typo, a hash from
        # another lake, a superseded hash applied twice — is refused rather
        # than applied, so a recomputation flag never names a snapshot that
        # is not here.
        self._assert_sealed(old_hash, "old_hash")
        self._assert_sealed(new_hash, "new_hash")
        return self.recomputation.record_snapshot_change(old_hash, new_hash)

    def _assert_sealed(self, snapshot_hash: str, role: str) -> None:
        """Refuse a hash that does not name a snapshot this lake seals.

        The registry is agnostic to which hashes are real — it only knows the
        scores it was told about — so the lake-side check lives here: a
        snapshot change is only honest if both hashes name snapshots the lake
        actually seals. The name is the directory's six-character prefix; the
        full hash is confirmed against the directory's manifest, which records
        it in full (feature 31). A prefix that names nothing, or a manifest
        whose full hash does not match, is a hash the lake does not hold.
        """
        if not isinstance(snapshot_hash, str) or len(snapshot_hash) < 6:
            raise SnapshotRecomputationError(
                f"{role} must be a snapshot hash this lake seals, got "
                f"{snapshot_hash!r}"
            )
        prefix = snapshot_hash[:6]
        matches = [
            name
            for name in self.sealed()
            if name.endswith(f"_{prefix}")
        ]
        if not matches:
            raise SnapshotRecomputationError(
                f"{role} {snapshot_hash!r} does not name a sealed snapshot in "
                f"this lake; a snapshot change relates two snapshots the lake "
                "actually holds"
            )
        for name in matches:
            manifest_file = self.snapshots_root / name / "MANIFEST.json"
            if manifest_file.is_file():
                try:
                    persisted = SnapshotManifest.from_json_bytes(
                        manifest_file.read_bytes()
                    )
                except SnapshotManifestError:
                    continue
                if persisted.snapshot_hash == snapshot_hash:
                    return
        raise SnapshotRecomputationError(
            f"{role} {snapshot_hash!r} does not match the full hash of any "
            "sealed snapshot sharing its prefix; a snapshot change relates two "
            "snapshots the lake actually holds"
        )


def _parses(name: str) -> bool:
    try:
        parse_snapshot_name(name)
    except Exception:
        return False
    return True


def _publish_tree(
    source: Path,
    files: Mapping[str, str],
    working: Path,
    manifest_bytes: bytes,
) -> None:
    """Copy staged files into ``working``, write the manifest, freeze all.

    Copies by content (``copyfile``), not metadata: a staged file's mode is
    staging's business; a sealed file's mode is the contract (``0444``).
    The manifest is written beside the copied content — inside the working
    tree, so the rename publishes content and its record as one atomic
    unit, and frozen under the same ``0444`` contract as everything else.
    Directories are made read-only only after their contents are complete,
    and the working root itself is frozen last, so the tree that the rename
    publishes is already non-writable at every level the moment it appears
    under its sealed name.
    """
    working.mkdir(parents=True)
    for relative in files:
        destination = working / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
        os.chmod(destination, _FILE_MODE)
    manifest = working / MANIFEST_NAME
    manifest.write_bytes(manifest_bytes)
    os.chmod(manifest, _FILE_MODE)
    for directory, _subdirs, _files in os.walk(working):
        os.chmod(directory, _DIRECTORY_MODE)


def _discard_working_tree(working: Path) -> None:
    """Remove a working directory if it still exists, read-only modes and all.

    After a successful rename the working path is gone and this is a no-op;
    after a failure (or a lost race) the tree may carry the frozen modes,
    which plain ``rmtree`` cannot delete — parent directories without a
    write bit refuse entry removal. The callback re-grants the bits it
    needs and retries the failing operation.
    """
    if not working.exists():
        return

    def _writable_retry(
        operation: Callable[[str], object], path: str, _exc_info: object
    ) -> None:
        target = Path(path)
        # Deleting an entry needs write permission on its parent (and on
        # directories being emptied); grant both, then retry as asked.
        if target.is_dir():
            os.chmod(target, 0o700)
        parent = target.parent
        if parent.is_dir():
            os.chmod(parent, 0o700)
        operation(path)

    shutil.rmtree(working, onexc=_writable_retry)
