"""The persisted ``evaluator_identity`` record — feature 70's other half.

app_spec.xml feature 70: *"System persists ``evaluator_hash`` computed as a
sha256 over the container image digest plus the resolved configuration."*
The formula (``_identity``) is one half of that sentence; this module is the
other. A hash computed and dropped would satisfy "computes"; the feature
says **persists**, and the reason is in the two features that depend on it:

* Feature 71 refuses a comparison between two scores whose
  ``evaluator_hash`` values differ. That refusal is only meaningful against
  a *stored* value — a comparison against a recomputed one would agree with
  the current image by construction and could never detect that the image
  moved between the two scores (§15: "Evaluator image changed → Hash
  mismatch on score comparison").
* Feature 87 stamps every ``trial_ledger`` row with the triple, and feature
  99 puts the same column on ``node``. Both write the value this store
  holds; neither recomputes it.

**Why a table, when the hash is a pure function of its inputs?** Because the
inputs are not all present at read time and one of them is not recoverable.
A score records its ``evaluator_hash``; answering "which evaluator produced
this?" from that column alone would require the reader to still have the
image digest and the configuration *as they were*, which is exactly what
moves. The row is the record: it answers with the digest and the resolved
configuration that were current when the identity was first persisted, in
one place, addressable by the hash the score carries. (The snapshot member's
``_manifest_store`` makes the same argument for ``snapshot_hash``, and calls
the row the "second copy" that survives a wholesale rewrite of the artifact;
here there is no first copy at all, which is why *this* store refuses to
degrade to a no-op when it is unconfigured — see
:class:`~evaluator.EvaluatorStoreError`.)

**Assign-once.** The primary key is the ``evaluator_hash`` and the row is
written once: re-persisting an identity the store already holds is a no-op,
and a stored row is never updated in place. That distinction is the whole
integrity story of this table. An upsert would let a rewritable row silently
re-key an identity — the hash would keep pointing at one evaluator while the
row described another — and every score compared against it afterwards would
be wrong in the direction the system cannot detect.

Worth being precise about where the tamper defence actually fires, because
it is not the common path and a reader who expects it elsewhere will misjudge
the code. The hash is a pure function of its terms, and
:class:`~evaluator.EvaluatorIdentity` refuses to be constructed with a hash
that disagrees with them, so "same hash, different terms" is *not reachable
through this package's own API* — two calls with different terms produce
different hashes and therefore different rows. The defence that matters is
therefore on the **read** path: :meth:`persist` reads an existing row back
through :func:`identity_from_row` rather than assuming it, and
:meth:`resolve_hash` does the same, so a row edited outside this package — a
digest or configuration rewritten in place while the hash was left alone —
fails to reconstruct and surfaces as an
:class:`~evaluator.EvaluatorStoreError` instead of loading as a
plausible-looking lie. A caller that believes it just recorded an evaluator
learns that the table does not hold one this hash describes, rather than
being told the write succeeded.

**Schema.** The spec declares ``evaluator_hash CHAR(64) NOT NULL`` as a
column on ``node`` and ``trial_ledger``; it does not declare a table for the
identity itself, because a column needs no table *until* something has to
resolve it. This store creates ``evaluator_identity`` with ``CREATE TABLE IF
NOT EXISTS`` — idempotently, on every connect, the same contract the universe
and snapshot members state — so a fresh database and an existing one take one
path and no migration step is needed for this member. The spec's own
table-and-column layout lives in ``migrations/versions/**``, which is
core-task territory this member does not touch.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from ._config import canonical_config
from ._errors import EvaluatorIdentityError, EvaluatorStoreError
from ._identity import EvaluatorIdentity, normalize_evaluator_hash

__all__ = [
    "DATABASE_URL_ENV",
    "IDENTITY_TABLE",
    "EvaluatorIdentityStore",
    "identity_from_row",
]

#: The environment variable naming the relational store, shared with the rest
#: of the workspace (the universe and snapshot members read the same one; the
#: repository-level conftest points it at a per-test database).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table this store owns. Named for what it holds — an identity, of which
#: the hash is the key — rather than for the hash alone, because the row
#: carries the two terms as well and a ``evaluator_hash`` table would suggest
#: a hash is all there is to know.
IDENTITY_TABLE = "evaluator_identity"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {IDENTITY_TABLE} (
    -- The feature's value, and this table's key. CHAR(64) as the spec
    -- declares it on node and trial_ledger.
    evaluator_hash   CHAR(64) PRIMARY KEY,
    -- The first hash term, in its canonical `sha256:<64 hex>` spelling —
    -- the form ``image_digest`` refuses to be ambiguous about.
    image_digest     TEXT NOT NULL,
    -- The second term, as canonical JSON. TEXT rather than the JSONB the
    -- spec uses elsewhere: this store speaks sqlite (the spec's
    -- single-machine allowance, exactly as the universe and snapshot
    -- members do), which has no JSONB type. The value is the same
    -- canonical spelling either medium would carry, so a future Postgres
    -- migration reads it without a re-encode.
    config_canonical TEXT NOT NULL,
    -- The reference as written, when the caller had one. Diagnostics only:
    -- two spellings of one image carry different values here and the same
    -- ``evaluator_hash``, which is why this column is deliberately not
    -- part of the row's identity (it is not in the primary key, and
    -- re-persisting one hash under a different reference is not a
    -- conflict — see ``persist``).
    image_reference  TEXT
);

CREATE INDEX IF NOT EXISTS {IDENTITY_TABLE}_image_digest
    ON {IDENTITY_TABLE} (image_digest);
"""

# The record's columns, in insertion order. Kept as one string so the writer
# and the reader cannot drift apart in column order — the failure that would
# silently swap a canonical configuration for a reference.
_COLUMNS = "evaluator_hash, image_digest, config_canonical, image_reference"


def identity_from_row(row: Any) -> EvaluatorIdentity:
    """Reconstruct an :class:`~evaluator.EvaluatorIdentity` from a stored row.

    ``row`` is a ``(evaluator_hash, image_digest, config_canonical,
    image_reference)`` tuple as this store writes it. The configuration is
    parsed back from its canonical JSON and re-folded by the record's own
    ``__post_init__``, so a row that has been edited — a digest swapped for
    another while the hash was left alone — fails to reconstruct instead of
    loading as a plausible-looking lie. That check is the reason the read
    path goes through the record type rather than handing back raw columns:
    the hash is what the rest of the system trusts, and a store that could
    return a hash disagreeing with its own row would be a store that launders
    a tamper.

    Public because the ledger and node features (87, 99) write the same
    triple and will read rows back; a second decoder beside this one would be
    a second answer to "what does this row mean?".
    """
    import json

    evaluator_hash, image_digest, config_canonical, image_reference = row
    try:
        config = json.loads(config_canonical)
    except ValueError as exc:
        raise EvaluatorStoreError(
            f"stored configuration for evaluator_hash {evaluator_hash!r} is "
            f"not valid JSON: {exc}; the column is written canonically by "
            "this store, so this row was edited by something else"
        ) from exc
    try:
        return EvaluatorIdentity(
            image_digest=image_digest,
            config=config,
            evaluator_hash=evaluator_hash,
            image_reference=image_reference,
        )
    except EvaluatorIdentityError as exc:
        raise EvaluatorStoreError(
            f"stored row for evaluator_hash {evaluator_hash!r} does not "
            f"describe the evaluator it names: {exc}"
        ) from exc


class EvaluatorIdentityStore:
    """Reads and writes the ``evaluator_identity`` table for one database.

    Bound to a database URL at construction. Unlike the snapshot member's
    manifest store — where an unconfigured store is a supported state,
    because the sealed directory is a complete record on its own — there is
    no artifact here beside the row: feature 70's text is "persists", and a
    service asked to persist with nowhere to persist to would be reporting
    success for work it did not do. So :meth:`resolve` raises rather than
    returning ``None`` when ``DATABASE_URL`` names no store. A caller that
    only wants a hash computed in memory calls :func:`evaluator.evaluator_digest`
    and never builds a store at all.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved (and the schema created) on first use rather than at
        # construction: building the store is composition-time work and must
        # not touch the disk, exactly as the service's own construction
        # performs no I/O.
        self._path: Optional[Path] = None
        self._resolved = False

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "EvaluatorIdentityStore":
        """The store ``DATABASE_URL`` names, or a refusal when it names none.

        An empty or whitespace-only value counts as unset, the same way the
        shared fixtures treat an empty ``TEST_DATABASE_URL``. Absent is an
        error here rather than a degraded state — see the class docstring.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "")
        if raw is None or not raw.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} is not set, so there is no store to "
                "persist evaluator_hash into (app_spec.xml feature 70); set "
                f"{DATABASE_URL_ENV} to the system's database, or compute the "
                "hash without persisting it via evaluator_digest()"
            )
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The URL this store was bound to."""
        return self._database_url

    # -- The row ------------------------------------------------------------

    def persist(self, identity: EvaluatorIdentity) -> EvaluatorIdentity:
        """Write one evaluator's identity; return the record.

        Called once per evaluator the process meets — typically once, at the
        first evaluation after a deployment, and then idempotently on every
        later one.

        Re-persisting an identity the store already holds is a no-op and
        succeeds. Persisting a *different* digest or resolved configuration
        under a hash the store already holds is refused with an
        :class:`~evaluator.EvaluatorIdentityError`: that combination cannot
        arise from this system's own formula (the hash is a pure function of
        the terms), so it is a bug or a tamper, and quietly overwriting would
        re-key an identity every score already references. A differing
        ``image_reference`` alone is *not* a conflict — two spellings of one
        image are one evaluator — so the stored reference is left as first
        written and the write succeeds.

        Raises :class:`~evaluator.EvaluatorStoreError` when the write itself
        fails. Deliberately not swallowed: a process that believes it
        recorded its evaluator and did not is the state feature 70 exists to
        rule out.
        """
        try:
            with closing(self._connect()) as connection, connection:
                existing = connection.execute(
                    f"SELECT {_COLUMNS} FROM {IDENTITY_TABLE} "
                    "WHERE evaluator_hash = ?",
                    (identity.evaluator_hash,),
                ).fetchone()
                if existing is not None:
                    # The row is already there. It is *read back* rather than
                    # assumed, so a row edited outside this package is caught
                    # here — ``identity_from_row`` refuses a row whose terms
                    # do not fold to the hash it is filed under — instead of
                    # being left in place under a caller that believes it
                    # just recorded an evaluator the table does not describe.
                    identity_from_row(existing)
                    return identity
                connection.execute(
                    f"INSERT INTO {IDENTITY_TABLE} ({_COLUMNS}) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        identity.evaluator_hash,
                        identity.image_digest,
                        # Store the canonical spelling, not whatever
                        # key order the caller's mapping happened to have:
                        # the column is what a reader folds back, and a
                        # non-canonical spelling here would make two equal
                        # configurations two different rows.
                        canonical_config(identity.config),
                        identity.image_reference,
                    ),
                )
        except sqlite3.Error as exc:
            raise EvaluatorStoreError(
                f"could not persist the {IDENTITY_TABLE} row for "
                f"evaluator_hash {identity.evaluator_hash}: {exc}"
            ) from exc
        return identity

    # -- Reading ------------------------------------------------------------

    def resolve_hash(
        self, evaluator_hash: str
    ) -> Optional[EvaluatorIdentity]:
        """Return the identity persisted under a hash, or ``None``.

        The lookup feature 71's comparison and a ledger stamp use: given the
        ``evaluator_hash`` a score carries, answer with the evaluator that
        produced it. ``None`` means the store holds no row for that hash —
        a score whose identity was never persisted, which is a discoverable
        state rather than an exception, the same way an absent component is
        for the factory. A hash that is not 64 hex characters is refused by
        :func:`~evaluator.normalize_evaluator_hash`, because a malformed key
        would silently answer ``None`` for a row that does exist.
        """
        normalized = normalize_evaluator_hash(evaluator_hash)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM {IDENTITY_TABLE} "
                "WHERE evaluator_hash = ?",
                (normalized,),
            ).fetchone()
        return None if row is None else identity_from_row(row)

    def identities(self) -> tuple[EvaluatorIdentity, ...]:
        """Every identity this store holds, ordered by image digest.

        Ordered by a stored column rather than by insertion: the order is
        then a property of the data, so two readers listing the same table
        agree without either of them depending on rowid. A report over the
        store — "which evaluators has this system run?" — reads this.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM {IDENTITY_TABLE} "
                "ORDER BY image_digest, evaluator_hash"
            ).fetchall()
        return tuple(identity_from_row(row) for row in rows)

    # -- Connection ---------------------------------------------------------

    def _resolve_path(self) -> Optional[Path]:
        """Resolve the sqlite path once, refusing schemes this store cannot read.

        Deferred out of ``__init__`` so construction performs no I/O. An
        in-memory URL resolves to ``None``, which :meth:`_connect` reads as
        "use ``:memory:``" — per-connection, which is why the schema is
        created on every connect rather than cached.
        """
        if self._resolved:
            return self._path
        parsed = urlparse(self._database_url)
        if parsed.scheme != "sqlite":
            raise EvaluatorStoreError(
                f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: "
                "this store speaks sqlite:/// (the spec's single-machine "
                f"allowance); point {DATABASE_URL_ENV} at a sqlite database"
            )
        if parsed.netloc not in ("", "localhost"):
            raise EvaluatorStoreError(
                f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
                f"{parsed.netloc!r}"
            )
        path = unquote(parsed.path)
        self._path = None if path in ("", ":memory:") else Path(path)
        self._resolved = True
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the store and ensure its schema exists.

        Idempotent on every connect, so a fresh database and an existing one
        take the same path and no migration step is needed for this member.
        The caller owns the connection.
        """
        self._resolve_path()
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path)
        else:
            connection = sqlite3.connect(":memory:")
        with connection:
            connection.executescript(_SCHEMA)
        return connection
