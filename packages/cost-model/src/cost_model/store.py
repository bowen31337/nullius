"""Persistence for the resolved cost model (features 59-60).

Feature 59's second half: *"…and persists the resolved cost model version
string with its venue name after loading the YAML configuration."*  Loading
resolves the pair (:mod:`cost_model.config`); this module writes it down.
Feature 60 adds the column that makes the row *mean* something: *"System
persists ``cost_model_hash`` computed over the loaded configuration, so
every score names its fee assumptions."*  Loading computes the hash over the
very mapping it resolved the pair from; this module records it beside the
pair.

The row is deliberately small, and its smallness is the design.  Two
columns matter — ``venue`` and ``version`` — because those are the two
values feature 59 names, and they are persisted *together* for the reason
:attr:`~cost_model.config.CostModelConfig.reference` spells out: a version
string with no venue does not say whose fee schedule it is.  A cost model
is only identified by the pair, so the pair is the primary key.  That has a
useful consequence: re-loading the same signed artifact is an upsert onto
one row and leaves one row behind, so the table converges on the set of
distinct cost models this store has ever been asked to price against,
however many times each was loaded.

**The third column is the hash, and it is identity rather than provenance.**
``cost_model_hash`` (feature 60) is what a *score* carries, so a later
reader resolves a score's fee assumptions by looking up the hash that score
names — §14.1's provenance triple, and ``docs/alpha-engine-prd.md`` §13.5's
"mismatched scores are never compared".  It is deliberately outside the
key, exactly like ``source``: the key stays the ``(venue, version)`` pair
feature 59 chose, so a document edited *without* a version bump does not
silently create a second row beside the one scores already reference — it
upserts onto that row and the hash moves, which is a fact an operator can
see rather than a divergence the key would hide.

**The fourth column, ``source``, is provenance rather than identity.**  It
records *where* the configuration was read from — the operator's signed
artifact path, or the packaged default — so an audit can tell which
document produced a row.  It is deliberately outside the key: the same
document loaded from two deployments is one cost model, and a key that
included the path would let a relocated artifact masquerade as a second
schedule.

**A row is written under a load, and re-loading adds nothing.**  There is
no update-in-place API surface here beyond the upsert a re-load performs,
and no delete: the row a load wrote is the record a later reader resolves
fee assumptions against.  What this module cannot do is prove the *document*
was not tampered with — the Z0 trust zone's read-only mount and signed
release (docs/nullius-tech-architecture.md §2) are that boundary — but the
hash does let a *reader* notice that the configuration behind a row is no
longer the one a score was stamped with, which is the divergence the triple
is for.

**A database written before feature 60 is upgraded in place, and reads
honestly.**  ``CREATE TABLE IF NOT EXISTS`` cannot evolve a table that
already exists, so a database written by feature 59's three-column schema
would otherwise reject every write with "no column named cost_model_hash".
The store brings such a table forward the way the ledger member's store
brings a pre-stamp ledger forward: ``PRAGMA table_info`` names the columns
it holds and a missing ``cost_model_hash`` is added by ``ALTER TABLE``.  It
is added *nullable*, with no default, because the one true statement a row
that predates feature 60 can make is *no hash was recorded* — every other
column's legacy default could assert something true of every legacy row
(``source`` is provenance, ``resolved_at`` is a timestamp), while a hash
invented here would name fee assumptions nobody measured.  Such a row is
served by :func:`load_persisted_cost_model` as a pair with no hash, and a
caller that needs the hash is told exactly that rather than handed a
fabricated one.  The recovery is one load: the upsert is keyed on the pair,
so re-loading the signed artifact stamps the existing row in place.

**Storage is the workspace's relational store**, addressed by
``DATABASE_URL`` exactly as the universe member's tables and the snapshot
member's ``snapshot_manifest`` are: ``sqlite:///`` on a single machine (the
spec's allowance, and what the shared test fixtures point at), Postgres in
production.  The schema is created idempotently on connect, so a fresh
store's first load brings the table into being and no migration step is
needed for this member; when the full versioned migration tree lands, this
``CREATE TABLE IF NOT EXISTS`` is the statement it adopts.  A URL whose
scheme is not ``sqlite`` is refused by name rather than spoken with a SQL
dialect this member has never been run against — the same refusal the
universe member's store documents.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from .config import CostModelConfig
from .errors import CostModelStoreError

__all__ = [
    "COST_MODEL_HASH_COLUMN",
    "COST_MODEL_TABLE",
    "DATABASE_URL_ENV",
    "connect",
    "load_persisted_cost_model",
    "persist_cost_model",
    "sqlite_path",
]

#: The workspace-wide environment variable naming the relational store.
#:
#: The same spelling the universe and snapshot members read, so one
#: ``DATABASE_URL`` addresses every store in a deployment rather than each
#: member inventing a variable of its own.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the resolved cost models live in.
COST_MODEL_TABLE = "cost_model"

#: The feature-60 column: the hash over the loaded configuration.
#:
#: Named here rather than inline so the schema, the upgrade probe and the
#: read path cannot disagree about the spelling — the ledger member's store
#: makes the same argument for its ``_EPOCH_COLUMN``.
COST_MODEL_HASH_COLUMN = "cost_model_hash"

_SCHEMA = f"""
-- Features 59-60: the resolved cost model, one row per (venue, version).
--
-- The pair is the primary key because a version string alone does not
-- identify a fee schedule — see the module docstring.  `cost_model_hash` is
-- the identity a score carries (feature 60), and `source` is provenance;
-- both sit deliberately outside the key so a relocated or hand-edited
-- artifact cannot masquerade as a second schedule.
--
-- `cost_model_hash` is NULLable for one reason only: a row written by
-- feature 59's three-column schema predates the stamp, and leaving it NULL
-- is the honest record that no hash was taken.  Every row this store writes
-- carries one — the write seam refuses a row that tries to leave it out.
CREATE TABLE IF NOT EXISTS {COST_MODEL_TABLE} (
    venue            TEXT NOT NULL,  -- the venue whose schedule this is
    version          TEXT NOT NULL,  -- the version string, verbatim as loaded
    source           TEXT,           -- where the document was read from (provenance)
    resolved_at      TEXT NOT NULL,  -- ISO 8601 UTC: when the load resolved it
    {COST_MODEL_HASH_COLUMN} CHAR(64),  -- feature 60: hash over the loaded configuration
    PRIMARY KEY (venue, version)
);
"""


def sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    Follows the SQLAlchemy convention the workspace's ``DATABASE_URL``
    already uses and the universe member's store documents:
    ``sqlite:///foo.db`` is a relative path, and an absolute path carries
    its leading slash after the triple (yielding four slashes in total).
    Any other scheme is refused loudly rather than silently mis-parsed —
    the Postgres store arrives with the migration member, and pretending to
    speak it here would hide a misrouted URL behind a mysterious file.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CostModelStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance), "
            "and the Postgres tree store arrives with the versioned migration"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CostModelStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path)
    if path.startswith("/"):
        path = path[1:]
    if not path:
        raise CostModelStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path"
        )
    return Path(path)


def _upgrade_legacy_cost_model_table(connection: sqlite3.Connection) -> None:
    """Bring a pre-feature-60 cost model table up to the current schema.

    ``CREATE TABLE IF NOT EXISTS`` cannot evolve a table that already
    exists, so a database written by feature 59's schema would otherwise
    reject every write with "no column named cost_model_hash".  The upgrade
    adds the column for the reason the module docstring gives: it is added
    *nullable*, with no default, because a hash invented for a pre-stamp row
    would name fee assumptions nobody measured.

    Idempotent by construction — a table that already holds the column is
    left untouched, so every connect after the first takes the same cheap
    path — and an ``ALTER TABLE … ADD COLUMN`` is a schema change, not a
    rewrite of any recorded value: no row's pair, provenance or timestamp is
    touched by it.  The column is appended after whatever the table already
    held, so a brought-forward table's physical order reflects its own
    history — which is why the read path names its columns explicitly and
    never relies on ``SELECT *``.
    """
    columns = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({COST_MODEL_TABLE})")
    }
    if COST_MODEL_HASH_COLUMN not in columns:
        connection.execute(
            f"ALTER TABLE {COST_MODEL_TABLE} "
            f"ADD COLUMN {COST_MODEL_HASH_COLUMN} CHAR(64)"
        )


def connect(database_url: Optional[str] = None) -> sqlite3.Connection:
    """Open the store named by ``DATABASE_URL`` (or the given URL).

    Creates the schema if absent — upgrading a pre-feature-60 database in
    place, see :func:`_upgrade_legacy_cost_model_table` — so every caller
    gets the same database contract without a migration step.  The caller
    owns the connection; use it as a context manager to commit.

    A missing ``DATABASE_URL`` — and no explicit URL — is refused by name
    rather than by a bare :class:`KeyError`: the caller asked for a store it
    did not configure, and the message says which variable would have
    named one.
    """
    url = database_url if database_url is not None else os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise CostModelStoreError(
            f"no relational store configured: pass a database URL or set "
            f"{DATABASE_URL_ENV} to one (sqlite:///path/to/store.db on a "
            "single machine)"
        )
    path = sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    with connection:
        connection.executescript(_SCHEMA)
        _upgrade_legacy_cost_model_table(connection)
    return connection


def persist_cost_model(
    config: CostModelConfig,
    database_url: Optional[str] = None,
) -> CostModelConfig:
    """Persist a resolved cost model; return the config that was written.

    One upsert on the ``(venue, version)`` key, so loading the same signed
    artifact twice leaves one row and a store accumulates exactly the
    distinct cost models it has been asked to price against.  The remaining
    columns are refreshed on every write: ``source`` records where *this*
    load read the document from, ``resolved_at`` when it resolved, and
    ``cost_model_hash`` (feature 60) the configuration this load priced
    against — provenance and identity that are allowed to move *together*,
    unlike the key they describe.  A document edited without a version bump
    therefore updates its own row rather than creating a second one beside
    it, and the hash column is how a reader sees that the fee assumptions
    moved under a label that did not.

    The hash written is the config's own (:attr:`~cost_model.config.
    CostModelConfig.hash`), which :class:`~cost_model.config.CostModelConfig`
    derived from the document it was loaded from or verified against one —
    so this module never computes a hash of its own and cannot drift from
    the loader's formula.

    **A config that names no fee assumptions is refused, not written.**  A
    bare ``(venue, version)`` pair is a legitimate *value* — feature 59's
    own, and what a caller hands
    :class:`~cost_model.service.CostModelService` for a config it resolved
    elsewhere — but it is not a legitimate *row*: feature 60's sentence is
    that every score names its fee assumptions, and a row whose hash is
    absent is a row a later reader could resolve a score against and learn
    nothing.  So the refusal is here, at the write that would put it in the
    store, rather than at the construction that merely held it.  The error
    names the pair and the fix (load the document, whose hash rides along).

    That refusal is checked *after* the store is opened, and the order is
    deliberate: a caller who handed over both a hashless config and an
    unusable store address is told about the address, because "there is no
    store here" is the more fundamental fact — the write could not have
    happened whatever the config said — and reporting the config instead
    would send an operator to fix a document while the real fault, a
    misrouted ``DATABASE_URL``, went unnamed.

    Any failure of the write — an unconfigured store, an unsupported URL
    scheme, a locked or unwritable database — surfaces as
    :class:`~cost_model.errors.CostModelStoreError`.  It is deliberately
    *not* swallowed: a cost model that resolved but never landed is the
    state feature 59 exists to rule out.

    Both failure layers are folded into that one type on purpose.
    :class:`sqlite3.Error` covers the database refusing the statement, and
    :class:`OSError` covers the filesystem refusing the store's own path —
    the parent directory's ``mkdir``, the socket file's creation.  They are
    the same fact from the caller's side ("the store I configured did not
    take the row"), and a caller that had to catch two unrelated exception
    families to learn it would eventually catch one and miss the other.
    """
    resolved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with closing(connect(database_url)) as connection, connection:
            if not config.hash:
                raise CostModelStoreError(
                    f"the cost model {config.reference!r} carries no "
                    "cost_model_hash, so it cannot be persisted: feature 60 "
                    "records the hash computed over the loaded "
                    "configuration, and a row without one names no fee "
                    "assumptions for a score to resolve. Load the document "
                    "through cost_model.load_cost_model() — the hash is "
                    "folded from the same parse as the pair — and persist "
                    "that."
                )
            connection.execute(
                f"""
                INSERT INTO {COST_MODEL_TABLE} (
                    venue, version, source, resolved_at, {COST_MODEL_HASH_COLUMN}
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(venue, version) DO UPDATE SET
                    source                = excluded.source,
                    resolved_at           = excluded.resolved_at,
                    {COST_MODEL_HASH_COLUMN} = excluded.{COST_MODEL_HASH_COLUMN}
                """,
                (
                    config.venue,
                    config.version,
                    config.source,
                    resolved_at,
                    config.hash,
                ),
            )
    except (sqlite3.Error, OSError) as exc:
        raise CostModelStoreError(
            f"could not persist the resolved cost model "
            f"{config.reference!r}: {exc}"
        ) from exc
    return config


def load_persisted_cost_model(
    venue: str,
    version: str,
    database_url: Optional[str] = None,
) -> Optional[CostModelConfig]:
    """Read one persisted cost model back, or ``None`` when it is absent.

    The round trip is lossless for everything the row holds: a config
    written by :func:`persist_cost_model` comes back with the same
    ``version``, ``venue``, ``source`` and (feature 60) ``hash`` — the hash
    being the point of the read, since it is what a score names and a
    comparison ranks against.  A miss is ``None`` — a cost model this store
    has never been asked to price against is a discoverable state, not an
    exception, on the same stance the universe member's readers take.

    ``venue`` and ``version`` are looked up as given: the store holds the
    text the document carried, and a caller resolving a score's fee
    assumptions is looking up exactly the strings that score names.

    **A row that predates feature 60 reads back without a hash**, because
    the row itself is refused rather than served with an invented one.  Such
    a row's ``cost_model_hash`` is NULL — the store's schema leaves it
    nullable for exactly this case — and rather than construct a config that
    would have to fabricate a stamp, this function raises
    :class:`~cost_model.errors.CostModelStoreError` naming the row and the
    one-step recovery (re-load the signed artifact, whose upsert stamps the
    existing row in place).  Reading a legacy row is not a *miss* — the cost
    model is there — so ``None`` would be a lie, and a plausible-looking
    hash would be a worse one.

    Note the asymmetry with :func:`connect`: the *schema* upgrade runs on
    every connection, including this one, so a legacy database is brought
    forward even by a reader.  What the upgrade cannot do is invent the hash
    for the rows already in it, which is why this refusal exists.

    A store that cannot be reached at all surfaces as
    :class:`~cost_model.errors.CostModelStoreError`, the same type a failed
    write raises — the caller asked a question of a store it configured, and
    "the store is not there" is an answer it must hear rather than a
    :class:`sqlite3.Error` or :class:`OSError` it must happen to catch.
    """
    try:
        with closing(connect(database_url)) as connection:
            row = connection.execute(
                f"""
                SELECT venue, version, source, {COST_MODEL_HASH_COLUMN}
                FROM {COST_MODEL_TABLE}
                WHERE venue = ? AND version = ?
                """,
                (venue, version),
            ).fetchone()
    except (sqlite3.Error, OSError) as exc:
        raise CostModelStoreError(
            f"could not read the cost model {venue!r}/{version!r} from the "
            f"store: {exc}"
        ) from exc
    if row is None:
        return None
    if row[3] is None:
        raise CostModelStoreError(
            f"the persisted cost model {venue!r}/{version!r} carries no "
            f"{COST_MODEL_HASH_COLUMN}: the row predates feature 60, which is "
            "the only way a row this store writes can lack one. Re-load the "
            f"signed artifact for {venue!r}/{version!r} — the upsert is keyed "
            "on the pair, so the load stamps this row in place."
        )
    return CostModelConfig(
        version=row[1], venue=row[0], source=row[2], hash=row[3]
    )
