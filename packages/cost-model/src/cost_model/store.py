"""Persistence for the resolved cost model (feature 59).

Feature 59's second half: *"…and persists the resolved cost model version
string with its venue name after loading the YAML configuration."*  Loading
resolves the pair (:mod:`cost_model.config`); this module writes it down.

The row is deliberately small, and its smallness is the design.  Two
columns matter — ``venue`` and ``version`` — because those are the two
values the feature names, and they are persisted *together* for the reason
:attr:`~cost_model.config.CostModelConfig.reference` spells out: a version
string with no venue does not say whose fee schedule it is.  A cost model
is only identified by the pair, so the pair is the primary key.  That has a
useful consequence: re-loading the same signed artifact is an upsert onto
one row and leaves one row behind, so the table converges on the set of
distinct cost models this store has ever been asked to price against,
however many times each was loaded.

The third column, ``source``, is provenance rather than identity.  It
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
release (docs/nullius-tech-architecture.md §2) are that boundary, and the
hash that pins the loaded bytes is feature 60's.  This module's job ends at
writing down the identity that was resolved.

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

_SCHEMA = f"""
-- Feature 59: the resolved cost model, one row per (venue, version).
--
-- The pair is the primary key because a version string alone does not
-- identify a fee schedule — see the module docstring.  `source` is
-- provenance, deliberately outside the key so a relocated artifact does not
-- read as a second schedule.
CREATE TABLE IF NOT EXISTS {COST_MODEL_TABLE} (
    venue        TEXT NOT NULL,  -- the venue whose schedule this is
    version      TEXT NOT NULL,  -- the version string, verbatim as loaded
    source       TEXT,           -- where the document was read from (provenance)
    resolved_at  TEXT NOT NULL,  -- ISO 8601 UTC: when the load resolved it
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


def connect(database_url: Optional[str] = None) -> sqlite3.Connection:
    """Open the store named by ``DATABASE_URL`` (or the given URL).

    Creates the schema if absent, so every caller gets the same database
    contract without a migration step.  The caller owns the connection; use
    it as a context manager to commit.

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
    load read the document from, and ``resolved_at`` when it resolved —
    provenance that is allowed to move, unlike the identity it describes.

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
            connection.execute(
                f"""
                INSERT INTO {COST_MODEL_TABLE} (
                    venue, version, source, resolved_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(venue, version) DO UPDATE SET
                    source      = excluded.source,
                    resolved_at = excluded.resolved_at
                """,
                (config.venue, config.version, config.source, resolved_at),
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

    The round trip is lossless for the pair: a config written by
    :func:`persist_cost_model` comes back with the same ``version``,
    ``venue`` and ``source``.  A miss is ``None`` — a cost model this store
    has never been asked to price against is a discoverable state, not an
    exception, on the same stance the universe member's readers take.

    ``venue`` and ``version`` are looked up as given: the store holds the
    text the document carried, and a caller resolving a score's fee
    assumptions is looking up exactly the strings that score names.

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
                SELECT venue, version, source
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
    return CostModelConfig(version=row[1], venue=row[0], source=row[2])
