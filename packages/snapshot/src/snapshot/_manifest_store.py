"""The persisted ``snapshot_manifest`` record — feature 33.

app_spec.xml feature 33: *"System persists each sealed snapshot into the
snapshot_manifest record so a score can name the exact bytes it was
computed over."* Feature 31 puts a ``MANIFEST.json`` inside every sealed
directory — the snapshot's own account of itself — and feature 32 derives
the identity those bytes are addressed by. This module is the third leg:
the same facts written to the **relational store**, where a score, a trial
ledger entry or an operator query can *join* against them.

Why a table at all, when MANIFEST.json already holds every field? Because
the two stores answer different questions and neither substitutes for the
other. The file lives inside the immutable directory and travels with the
bytes; it is the artifact's own label, and it is reachable only by opening
that one snapshot. The row is *addressable*: given a ``snapshot_hash`` —
the key §4.4 already stamps on every stored feature and score — the record
answers "which sealed bytes does this name, and what is in them?" without
walking the lake, and answers it alongside every other row so a query can
range over snapshots. And the row is the *second copy* feature 36's
docstring admits the on-disk check cannot be: a manifest rewritten
wholesale, every recorded hash edited to match tampered bytes, is
undetectable from inside that directory; it is detectable against a row
written at seal time and never rewritten (see :func:`verify_persisted`).

The table's shape is the spec's, column for column::

    snapshot_hash        CHAR(64) PRIMARY KEY
    sealed_at            TIMESTAMPTZ NOT NULL
    file_count           INT NOT NULL
    row_count            BIGINT NOT NULL
    universe_definition  JSONB NOT NULL
    schema_version       TEXT NOT NULL

**Every sealed snapshot gets a row — including one whose total rows are
unknown.** That sentence cost a decision, so it is written down rather than
left implicit. The table declares ``row_count BIGINT NOT NULL``, and a
manifest whose files include an opaque binary honestly records
``total_rows = None`` — *"a total over fiction is not a total"*
(``_manifest``). The two cannot both be satisfied by an integer, and the
three available answers are not equally good:

* fabricating a ``0`` is the fiction the manifest refuses, one store over;
* *omitting the row* keeps the column's constraint, and is what this module
  did first — but it defeats the feature. A score computed over a snapshot
  containing an opaque binary would have no record to name its bytes with,
  which is precisely what feature 33 exists to provide. Protecting a
  summary column by discarding the byte-level identity is the wrong trade:
  ``row_count`` is a convenience a human reads, while ``content_digest``
  is the thing a score keys on;
* storing SQL ``NULL`` for the unknown total is what the column means in
  the only case where the total is unknown, and is the choice made here.

So ``row_count`` is nullable *for this one state only* — a deliberate,
narrow deviation from the spec's declared ``NOT NULL``, taken because the
feature's own text (*"persists each sealed snapshot"*) leaves no room to
skip, and because every row the table holds still answers the question it
was built to answer. ``NULL`` reads as "not known", the same value the
manifest records for the same snapshot, so the record mirrors the artifact
field for field. An integer means exactly what it says.

Two other columns need translating on the way in:

* ``universe_definition`` is ``JSONB NOT NULL``, so the SQL ``NULL`` a
  not-asserted definition would suggest is unavailable. An asserted
  definition is stored as its canonical key-sorted JSON text (the spelling
  the §4.2 hash folds, ``_manifest.SnapshotManifest.universe_spelling``);
  a seal that asserted none stores the four characters ``null`` — the
  JSON literal, a *value* in the column that means "none asserted". That
  is not a cosmetic choice: SQL ``NULL`` is not a JSON value at all, so a
  reader of a genuine ``JSONB`` column would see a missing value rather
  than the ``null`` a reader of ``MANIFEST.json`` sees for the same
  snapshot. A definition is always a JSON object, whose canonical spelling
  always begins with ``{``, so the literal can never collide with one and
  the encoding is decodable in both directions rather than guessed at.

**The record names exact bytes, and says which.** Feature 33's phrase is
*"the exact bytes it was computed over"*, and the columns above
deliberately do not pin bytes on their own: two different file trees can
share ``file_count``, ``row_count``, ``universe_definition`` and
``schema_version``. So every row also carries a ``content_digest`` — the
fold over the manifest's ``(path, sha256)`` pairs (``_content.files_digest``,
surfaced as :attr:`~snapshot.SnapshotManifest.content_digest`) — which is
what actually makes the row name a byte-level identity rather than a
summary of one. ``file_count`` and ``row_count`` stay because the spec's
column list is the shape, and they are the two numbers a human reads off
the record.

**A row is written once, under a seal, and never edited.** No API surface
here updates or deletes: a later seal adds its own row. So the row a seal
wrote is the record a verification pass compares against, and a snapshot
whose bytes changed on disk — or whose manifest file was rewritten to
match — is caught by the *disagreement between the two*, in both
directions: bytes that no longer digest to the row's ``content_digest``,
and a manifest that no longer spells the row's other columns. What that
check still cannot catch is a tamper to both copies at once; that is a
boundary, stated in :func:`verify_persisted` rather than papered over.

**Storage is the workspace's relational store**, addressed by
``DATABASE_URL`` exactly as the universe member's tables are: ``sqlite:///``
on a single machine (the spec's allowance, and what the shared test
fixtures point at), Postgres in production. The schema is created
idempotently on connect, so a fresh lake's first seal brings the table into
being and no migration step is needed for this member; when the full
versioned migration tree lands, this ``CREATE TABLE IF NOT EXISTS`` is the
statement it adopts. One deliberate departure from the universe member's
convention: a URL whose scheme is *not* ``sqlite`` is refused by name
rather than spoken with a SQL dialect it may not match — the statement
below uses ``CHAR(80)`` for the timestamp and an unbounded ``INTEGER`` for
the total, both of which Postgres accepts and both of which are the
specified column types there.

The store is optional in the only sense that matters: a lake with no
``DATABASE_URL`` at all can still seal. :class:`SnapshotManifestStore.
resolve` returns ``None`` for "no relational store here", a seal persists
nothing and says so through :meth:`SnapshotService.persisted`, and the
filesystem records — the manifest and the directory — remain complete and
sufficient for every read path. What is *not* tolerated is a configured
store that is broken: if ``DATABASE_URL`` names something and the write
fails, :class:`SnapshotStoreError` is raised and the seal reports it
(carrying the record it already published), because a record that silently
failed to persist is exactly the state feature 33 exists to prevent.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union
from urllib.parse import unquote, urlparse

from ._errors import SnapshotManifestError, SnapshotStoreError
from ._identity import SCHEMA_VERSION
from ._manifest import SnapshotManifest
from ._naming import format_sealed_at, normalize_snapshot_hash

__all__ = [
    "DATABASE_URL_ENV",
    "MANIFEST_TABLE",
    "SnapshotManifestRecord",
    "SnapshotManifestStore",
    "verify_persisted",
]

#: The environment variable naming the relational store, shared with the
#: rest of the workspace (the universe member's tables read the same one;
#: the repository-level conftest points it at a per-test database).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table feature 33 persists into — the spec's own table name.
MANIFEST_TABLE = "snapshot_manifest"

#: Extra columns this store adds to the spec's list. ``content_digest`` is
#: the byte-level identity the feature's "exact bytes" phrase needs (the
#: spec's six columns cannot pin one); ``manifest_digest`` is the spelling
#: the table itself needs to store the canonical JSON text of the manifest
#: file under the same version — see the module docstring.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {MANIFEST_TABLE} (
    -- The spec's columns, in the spec's order.
    snapshot_hash        CHAR(64) PRIMARY KEY,
    sealed_at            TIMESTAMPTZ NOT NULL,
    file_count           INT NOT NULL,
    -- Nullable for exactly one state: the manifest's own total_rows is
    -- null (some file's format carries no row concept), and a fabricated 0
    -- would be the fiction the manifest refuses. Every other row holds an
    -- integer. See the module docstring for why this beats omitting the
    -- row, which would leave the bytes unaddressable.
    row_count            BIGINT,
    universe_definition  JSONB NOT NULL,
    schema_version       TEXT NOT NULL,
    -- This store's additions, stated as additions (see module docstring).
    content_digest       CHAR(64) NOT NULL,
    manifest_digest      CHAR(64) NOT NULL,
    manifest_version     INT NOT NULL
);

CREATE INDEX IF NOT EXISTS {MANIFEST_TABLE}_sealed_at
    ON {MANIFEST_TABLE} (sealed_at);
"""

# The record's columns, in insertion order. Kept as one string so the
# writer and the reader cannot drift apart in column order — the failure
# that would silently swap a row count for a file count.
_COLUMNS = (
    "snapshot_hash, sealed_at, file_count, row_count, universe_definition, "
    "schema_version, content_digest, manifest_digest, manifest_version"
)

_SEALED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class SnapshotManifestRecord:
    """One persisted ``snapshot_manifest`` row, as a value.

    The read side of feature 33. Every field is a column of the table; the
    derived properties spell the facts a consumer asks the record for. The
    row is written once by a seal and never edited, so a record read back
    is a statement about the bytes the lake sealed under this hash.
    """

    #: The 64-hex snapshot hash — the table's primary key, and the value
    #: §4.4 stamps on every score and stored feature.
    snapshot_hash: str
    #: The sealing instant, timezone-aware UTC, second resolution.
    sealed_at: datetime
    #: How many content files the snapshot holds.
    file_count: int
    #: The total rows across those files, or ``None`` when the manifest
    #: could not total them — it records ``None`` for the same snapshot,
    #: because some file's format carries no row concept and a partial sum
    #: would be a fiction (``_manifest``). ``None`` is *not* "no row":
    #: every sealed snapshot has a row (feature 33's "each"), and this
    #: column mirrors the artifact's own answer.
    row_count: Optional[int]
    #: The canonical JSON spelling of the universe definition, or ``None``
    #: when the seal asserted none — stored as the JSON literal ``null``,
    #: so the column is never SQL ``NULL``.
    universe_definition: Optional[str]
    #: The lake schema version the identity was computed under.
    schema_version: str
    #: The digest over the manifest's ``(path, sha256)`` pairs — the
    #: byte-level identity of the content this hash names.
    content_digest: str
    #: The sha256 of the canonical MANIFEST.json bytes this row recorded.
    manifest_digest: str
    #: The manifest format version the row describes.
    manifest_version: int

    @property
    def name(self) -> str:
        """The canonical snapshot directory name this row describes."""
        from ._naming import snapshot_name

        return snapshot_name(self.sealed_at, self.snapshot_hash)

    @property
    def hash_prefix(self) -> str:
        """The first six characters of the snapshot hash."""
        return self.snapshot_hash[:6]

    @property
    def exact_bytes(self) -> str:
        """The digest that names the exact bytes this score was computed over.

        Feature 33's phrase, made addressable: the same value lives on the
        sealed manifest as :attr:`~snapshot.SnapshotManifest.content_digest`,
        so a score holding a ``snapshot_hash`` can name the bytes by
        ``(snapshot_hash, content_digest)`` and be answered from either
        store.
        """
        return self.content_digest

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"SnapshotManifestRecord(name={self.name!r}, "
            f"files={self.file_count}, rows={self.row_count})"
        )


class SnapshotManifestStore:
    """Reads and writes the ``snapshot_manifest`` table for one database.

    Bound to a database URL at construction. :meth:`resolve` is the door
    the service uses — it returns ``None`` rather than raising when no
    store is configured, because an unconfigured store is a supported
    state (see the module docstring), while a *configured but broken* one
    is not and surfaces as :class:`~snapshot.SnapshotStoreError`.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise SnapshotStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved (and the schema created) on first use rather than at
        # construction: building the store is composition-time work and
        # must not touch the disk, exactly as the service's own
        # construction performs no I/O.
        self._path: Optional[Path] = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["SnapshotManifestStore"]:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the same way
        the shared fixtures and :meth:`SnapshotService.from_env` treat
        ``LAKE_ROOT``. Absent is not an error: it is a lake without a
        relational store, which seals, mounts, verifies and reads exactly
        as before — the persistence is an added record, never a
        precondition for the filesystem ones.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store persists to."""
        return self._database_url

    @property
    def path(self) -> Optional[Path]:
        """The SQLite file backing this store, if it is one.

        ``None`` until the first operation resolves the URL — nothing is
        created at construction — and always ``None`` for a non-SQLite
        URL. The in-memory spelling (``sqlite://``) has no path at all.
        """
        if self._path is None:
            self._resolve_path()
        return self._path

    def _resolve_path(self) -> Optional[Path]:
        """Translate the configured URL into a SQLite path, or refuse it.

        Follows the SQLAlchemy convention the workspace's ``DATABASE_URL``
        already uses and the universe member's store documents:
        ``sqlite:///foo.db`` is a path, ``sqlite://`` is the in-memory
        database. An explicit ``:memory:`` path is honoured as itself.
        Any other scheme is refused by name — the statement above is
        portable SQL, but this member cannot *guarantee* a dialect it has
        never been run against, and silently guessing is how a misrouted
        URL becomes a mysterious file.
        """
        parsed = urlparse(self._database_url)
        if parsed.scheme != "sqlite":
            raise SnapshotStoreError(
                f"unsupported {DATABASE_URL_ENV} scheme "
                f"{parsed.scheme!r}: this store speaks sqlite:/// (the "
                "spec's single-machine allowance); point "
                f"{DATABASE_URL_ENV} at a sqlite database"
            )
        if parsed.netloc not in ("", "localhost"):
            raise SnapshotStoreError(
                f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
                f"{parsed.netloc!r}"
            )
        path = unquote(parsed.path)
        if not path:
            self._path = None
            return None
        if path == ":memory:":
            self._path = None
            return None
        self._path = Path(path)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the store and ensure its schema exists.

        The schema is created idempotently on every connect, so a fresh
        database and an existing one take the same path and no migration
        step is needed for this member — the same contract the universe
        member's ``connect`` states. The caller owns the connection.
        """
        self._resolve_path()
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path)
        else:
            # An in-memory database is per-connection, so the table has to
            # be created on the connection that will use it — which is what
            # happens here, and why the schema is not cached.
            connection = sqlite3.connect(":memory:")
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    # -- Writing ------------------------------------------------------------

    def persist(
        self,
        manifest: SnapshotManifest,
        *,
        manifest_bytes: Optional[bytes] = None,
    ) -> SnapshotManifestRecord:
        """Write one sealed snapshot's row; return the record.

        The seal's call, once per published snapshot — *every* published
        snapshot, including one whose files carry no row concept: the
        feature's text is "persists each", and a snapshot skipped here is
        one whose bytes no score can name (see the module docstring for the
        ``row_count IS NULL`` decision that buys this).

        The row is keyed by the full ``snapshot_hash``, so a schedule that
        re-seals unchanged staging — the idempotent case, which re-asserts
        one identity — writes the same row twice and leaves one row behind:
        the write is an upsert on the primary key, and re-writing a row
        with the values the lake already holds changes nothing.

        ``manifest_bytes`` is the manifest as it was actually written to
        the snapshot directory, when the caller has it; it is what the
        row's ``manifest_digest`` records. Without it the digest is taken
        over a fresh canonical serialisation, which is byte-identical by
        construction (``to_json_bytes`` is deterministic), so the digest
        is the same value either way — passing the bytes is a way of
        recording what is on disk rather than what should be.

        A write that fails raises :class:`SnapshotStoreError`. It is
        deliberately *not* swallowed: the seal reports it, carrying the
        record it already published, because a snapshot whose row silently
        failed to persist is the state feature 33 exists to rule out.
        """
        record = self._record_for(manifest, manifest_bytes)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"INSERT OR REPLACE INTO {MANIFEST_TABLE} ({_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.snapshot_hash,
                        format_sealed_at(record.sealed_at),
                        record.file_count,
                        record.row_count,
                        # The column is JSON, and the canonical spelling of
                        # "no definition asserted" is the JSON literal
                        # ``null`` — a value in the column that says so,
                        # rather than SQL NULL, which the schema forbids and
                        # which no JSON reader would see. A definition is
                        # always a JSON object, so the text of one can never
                        # be the four characters ``null``; the round trip is
                        # unambiguous in both directions.
                        "null"
                        if record.universe_definition is None
                        else record.universe_definition,
                        record.schema_version,
                        record.content_digest,
                        record.manifest_digest,
                        record.manifest_version,
                    ),
                )
        except sqlite3.Error as exc:
            raise SnapshotStoreError(
                f"could not persist the {MANIFEST_TABLE} record for "
                f"snapshot {record.snapshot_hash} ({record.name}): {exc}; "
                "the snapshot itself is published and verifiable, but the "
                "record feature 33 persists is missing — the store has to "
                "be made writable rather than the failure ignored"
            ) from exc
        return record

    def _record_for(
        self, manifest: SnapshotManifest, manifest_bytes: Optional[bytes]
    ) -> SnapshotManifestRecord:
        """Build the row for a manifest, from the manifest itself.

        Every column is derived from the record — nothing is re-read from
        the lake. That matters: the row must be a statement about the seal
        that just happened, not a second opinion gathered by walking the
        filesystem afterwards, or the two could disagree for reasons that
        have nothing to do with tampering.
        """
        payload = (
            manifest.to_json_bytes()
            if manifest_bytes is None
            else bytes(manifest_bytes)
        )
        return SnapshotManifestRecord(
            snapshot_hash=manifest.snapshot_hash,
            sealed_at=manifest.sealed_at,
            file_count=manifest.file_count,
            # Mirrors the manifest field for field: an integer when the
            # manifest could total the rows, ``None`` when it honestly
            # could not. Never a fabricated 0.
            row_count=manifest.total_rows,
            universe_definition=manifest.universe_spelling,
            schema_version=SCHEMA_VERSION,
            content_digest=manifest.content_digest,
            manifest_digest=hashlib.sha256(payload).hexdigest(),
            manifest_version=manifest.manifest_version,
        )

    # -- Reading ------------------------------------------------------------

    def rows_for(self, snapshot_hash: str) -> tuple[SnapshotManifestRecord, ...]:
        """Every row this store persists for ``snapshot_hash``.

        A tuple, not a record or ``None``: the primary key makes it at
        most one row in practice, and the shape says what is true in
        general — a result *set*, which is what an empty answer looks like
        when the store has no row for this hash.

        An empty answer is legitimate and is not an error, but it is now a
        *narrow* case: every seal writes a row, including one whose total
        rows are unknown (see :meth:`persist`), so the only way to be here
        empty-handed is a snapshot sealed before this store was pointed at
        the lake, one whose row write failed, or a mere typo in the hash —
        which is the report :meth:`SnapshotService.unrecorded` exists to
        produce, and why a hash with no row is worth an operator's
        attention rather than a shrug. The caller that needs the record to
        exist — a verification pass — says so itself.
        """
        wanted = normalize_snapshot_hash(snapshot_hash)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM {MANIFEST_TABLE} "
                "WHERE snapshot_hash = ? ORDER BY sealed_at",
                (wanted,),
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def record_for(self, snapshot_hash: str) -> Optional[SnapshotManifestRecord]:
        """The row for ``snapshot_hash``, or ``None`` when there is none."""
        rows = self.rows_for(snapshot_hash)
        return rows[0] if rows else None

    def hashes(self) -> list[str]:
        """Every snapshot hash this store persists, sorted.

        The row set as a set of identities — what a sweep iterates, and
        the store-side twin of :meth:`SnapshotService.sealed`'s listing of
        the lake's directories. The two need not agree, and where they do
        not is the interesting report: a hash in the lake but not here is
        a snapshot with no record — sealed before this store was
        configured, or its write failed — and :meth:`SnapshotService.
        unrecorded` names it for the backfill that has to repair it.
        """
        with closing(self._connect()) as connection:
            return [
                row[0]
                for row in connection.execute(
                    f"SELECT snapshot_hash FROM {MANIFEST_TABLE} "
                    "ORDER BY snapshot_hash"
                )
            ]


def _universe_from_column(value: object) -> Optional[str]:
    """Decode the ``universe_definition`` column back into its spelling.

    The inverse of the encoding in :meth:`SnapshotManifestStore.persist`:
    the JSON literal ``null`` — the four characters, as stored — means "no
    definition asserted" and decodes to Python ``None``; anything else is
    the canonical JSON text of an object and is returned unchanged.

    A definition is always a JSON *object*, so its canonical spelling
    always begins with ``{`` and can never be the bare literal ``null``;
    the two cases therefore cannot collide, which is what makes this a
    decoding rather than a guess. A SQL ``NULL`` in a row written by hand
    (or by an earlier spelling of this store) is read as "none asserted"
    too — the column's contract is a JSON value, and the absence of one is
    the closest honest thing to that value.
    """
    if value is None:
        return None
    text = str(value)
    return None if text == "null" else text


def _record_from_row(row: tuple[object, ...]) -> SnapshotManifestRecord:
    """Rebuild a record from a row, validating as it goes.

    A row that does not parse is refused with
    :class:`~snapshot.SnapshotManifestError` — the same contract the
    manifest file's own reader holds — because a persisted record nobody
    can read is worse than an absent one: it claims a snapshot is
    accounted for and cannot say for what.
    """
    (
        snapshot_hash,
        sealed_at,
        file_count,
        row_count,
        universe_definition,
        schema_version,
        content_digest,
        manifest_digest,
        manifest_version,
    ) = row
    try:
        instant = datetime.strptime(str(sealed_at), _SEALED_AT_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise SnapshotManifestError(
            f"the {MANIFEST_TABLE} row for {snapshot_hash!r} carries "
            f"sealed_at {sealed_at!r}, which is not the canonical "
            "YYYY-MM-DDTHH:MM:SSZ form"
        ) from exc
    return SnapshotManifestRecord(
        snapshot_hash=normalize_snapshot_hash(str(snapshot_hash)),
        sealed_at=instant,
        file_count=int(file_count),  # type: ignore[arg-type]
        # SQL NULL is the stored form of an unknown total (the manifest's
        # own ``None``), and it decodes back to Python ``None``. A value
        # here is an integer, and ``int()`` would raise on the NULL rather
        # than reading it — which is how the two states stay distinguishable
        # instead of collapsing an unknown total into a 0.
        row_count=None if row_count is None else int(row_count),
        universe_definition=_universe_from_column(universe_definition),
        schema_version=str(schema_version),
        content_digest=normalize_snapshot_hash(str(content_digest)),
        manifest_digest=normalize_snapshot_hash(str(manifest_digest)),
        manifest_version=int(manifest_version),  # type: ignore[arg-type]
    )


def verify_persisted(
    manifest: SnapshotManifest,
    record: SnapshotManifestRecord,
    *,
    manifest_bytes: Optional[bytes] = None,
) -> tuple[str, ...]:
    """Compare a sealed manifest against the row persisted for it.

    Returns the findings as data — one line per disagreement, empty when
    the two agree — so a sweep can collect them and the raising door can
    turn them into an error. The comparison is deliberately column-wise
    rather than a digest equality: two digests that differ say *that* the
    record and the artifact disagree, and an operator needs to see *how*.

    Checked on every call: the byte-level identity (``content_digest``),
    the four columns the feature's phrase implies (files, rows, universe,
    schema version) and the manifest's own format version. ``sealed_at``
    is compared as well, because it is the other half of the directory
    name and a row that disagrees with it describes a different snapshot
    than the one on disk.

    The boundary this does *not* cross, stated rather than implied: a
    tamper that rewrites both the sealed directory and this table
    consistently is invisible here. The two copies live in different
    media with different write paths, which is the point — the cheap
    tamper (edit the tree, or edit the manifest inside it) is caught, and
    the expensive one is the residual risk the honesty of feature 36's
    docstring already describes.
    """
    findings: list[str] = []
    if manifest.snapshot_hash != record.snapshot_hash:
        findings.append(
            f"snapshot_hash: manifest {manifest.snapshot_hash} vs record "
            f"{record.snapshot_hash}"
        )
    if manifest.sealed_at != record.sealed_at:
        findings.append(
            f"sealed_at: manifest {format_sealed_at(manifest.sealed_at)} vs "
            f"record {format_sealed_at(record.sealed_at)}"
        )
    if manifest.file_count != record.file_count:
        findings.append(
            f"file_count: manifest {manifest.file_count} vs record "
            f"{record.file_count}"
        )
    if manifest.total_rows != record.row_count:
        findings.append(
            f"row_count: manifest {manifest.total_rows!r} vs record "
            f"{record.row_count}"
        )
    if manifest.universe_spelling != record.universe_definition:
        findings.append(
            f"universe_definition: manifest {manifest.universe_spelling!r} vs "
            f"record {record.universe_definition!r}"
        )
    if manifest.manifest_version != record.manifest_version:
        findings.append(
            f"manifest_version: manifest {manifest.manifest_version} vs "
            f"record {record.manifest_version}"
        )
    if manifest.content_digest != record.content_digest:
        findings.append(
            f"content_digest: manifest {manifest.content_digest} vs record "
            f"{record.content_digest}; the bytes the manifest describes are "
            "not the bytes the lake sealed under this hash"
        )
    payload = (
        manifest.to_json_bytes() if manifest_bytes is None else bytes(manifest_bytes)
    )
    if hashlib.sha256(payload).hexdigest() != record.manifest_digest:
        findings.append(
            f"manifest_digest: the MANIFEST.json on disk does not hash to "
            f"{record.manifest_digest}; the record was written by a seal and "
            "is never edited, so the document has changed since"
        )
    return tuple(findings)
