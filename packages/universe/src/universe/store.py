"""Persistence for monthly universe builds.

The monthly universe is not an ephemeral computation: it is a fact about
what was knowable at each month boundary, and everything downstream — the
point-in-time membership table, the survivorship audit, the snapshot's
``universe_definition`` — is derived from these persisted builds. A
universe that exists only in memory is a universe a replay cannot trust.

Storage is the relational store addressed by ``DATABASE_URL`` (SQLite on a
single machine, per the spec's dev allowance; Postgres 16 in production).
This member owns three tables and creates them idempotently — deliberately
*not* the spec's ``universe_membership`` table, which the versioned
migration owns and which carries the derived interval form ``(symbol,
valid_from, valid_to, delist_reason)``. The builds here are the raw
material: one row per month vouching for the exact window and config used
(including the liquidity floor), one row per admitted symbol with its rank
and its median dollar volume, and one row per floor-refused symbol with
the rejected median and the persisted exclusion reason — the difference
between "out-ranked" and "not liquid enough" is exactly what an audit
later needs to read off the store, and neither fact may be recomputed
from today's data.

Rebuilding a month is an atomic replace: the build row is upserted and the
member and exclusion rows are deleted and re-inserted in one transaction,
so a reader never observes half of a rebuild. Two builds of the same month
from the same bars leave the tables byte-identical apart from
``computed_at``, which records when the build ran — provenance, not a
score, so wall-clock reading here does not touch the replay determinism
contract.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from .config import UniverseConfig
from .monthly import MonthlyUniverse, UniverseExclusion, UniverseMember, month_key

__all__ = [
    "DATABASE_URL_ENV",
    "connect",
    "persist_monthly_universe",
    "load_monthly_universe",
]

DATABASE_URL_ENV = "DATABASE_URL"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS universe_monthly_build (
    month             TEXT PRIMARY KEY,  -- 'YYYY-MM': the month this universe is effective for
    effective_from    TEXT NOT NULL,     -- ISO date, first day of the month
    window_start      TEXT NOT NULL,     -- ISO date, inclusive start of the trailing window
    window_end        TEXT NOT NULL,     -- ISO date, inclusive end (day before the month starts)
    top_n             INTEGER NOT NULL,
    window_days       INTEGER NOT NULL,
    min_observations  INTEGER NOT NULL,
    min_dollar_volume REAL NOT NULL,     -- the configured liquidity floor (0 = no floor)
    member_count      INTEGER NOT NULL,
    computed_at       TEXT NOT NULL      -- ISO 8601 UTC build timestamp (provenance)
);

CREATE TABLE IF NOT EXISTS universe_monthly_member (
    month                TEXT NOT NULL REFERENCES universe_monthly_build(month),
    symbol               TEXT NOT NULL,
    rank                 INTEGER NOT NULL,
    median_dollar_volume REAL NOT NULL,
    PRIMARY KEY (month, symbol),
    UNIQUE (month, rank)
);
CREATE INDEX IF NOT EXISTS universe_monthly_member_month_rank
    ON universe_monthly_member (month, rank);

CREATE TABLE IF NOT EXISTS universe_monthly_exclusion (
    month                TEXT NOT NULL REFERENCES universe_monthly_build(month),
    symbol               TEXT NOT NULL,
    median_dollar_volume REAL NOT NULL,  -- the trailing-window median the floor rejected
    reason               TEXT NOT NULL,  -- the persisted exclusion reason (canonical text)
    PRIMARY KEY (month, symbol)
);
"""


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    Follows the SQLAlchemy convention the workspace's ``DATABASE_URL``
    already uses: ``sqlite:///foo.db`` is a relative path, and an absolute
    path carries its leading slash after the triple (yielding four slashes
    in total). Any other scheme is refused loudly rather than silently
    mis-parsed — the Postgres store arrives with the migration member, and
    pretending to speak it here would hide a misrouted URL behind a
    mysterious file.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError(
            f"unsupported DATABASE_URL scheme {parsed.scheme!r}: this store "
            "speaks sqlite:///, and the Postgres tree store arrives with the "
            "versioned migration"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ValueError(
            f"sqlite DATABASE_URL must not carry a host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path)
    if path.startswith("/"):
        path = path[1:]
    if not path:
        raise ValueError("sqlite DATABASE_URL carries no database path")
    return Path(path)


def _upgrade_legacy_build_table(connection: sqlite3.Connection) -> None:
    """Bring a pre-floor build table up to the current schema, in place.

    ``CREATE TABLE IF NOT EXISTS`` cannot evolve a table that already
    exists, so a database written before the liquidity floor landed would
    otherwise reject every persist with "no column named
    min_dollar_volume". The upgrade adds the missing column with the
    no-floor default of 0 — which is exactly what those builds meant: no
    symbol was excluded, because no floor was configured.
    """
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(universe_monthly_build)")
    }
    if "min_dollar_volume" not in columns:
        connection.execute(
            "ALTER TABLE universe_monthly_build "
            "ADD COLUMN min_dollar_volume REAL NOT NULL DEFAULT 0"
        )


def connect(database_url: Optional[str] = None) -> sqlite3.Connection:
    """Open the store named by ``DATABASE_URL`` (or the given URL).

    Creates the schema if absent — upgrading a pre-floor database in place
    — and enables foreign keys, so every caller gets the same database
    contract without a migration step. The caller owns the connection; use
    it as a context manager to commit.
    """
    url = database_url if database_url is not None else os.environ[DATABASE_URL_ENV]
    path = _sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.executescript(_SCHEMA)
        _upgrade_legacy_build_table(connection)
    return connection


def persist_monthly_universe(
    universe: MonthlyUniverse,
    database_url: Optional[str] = None,
) -> int:
    """Persist one monthly universe build; returns the member count written.

    Idempotent per month: building April twice leaves one build row, one
    row per member and one row per exclusion, and rebuilding April after
    its bars were restated replaces the membership *and* the exclusions
    atomically (upsert the build, delete then re-insert the members and
    the exclusions, all inside one transaction) — a symbol that rose above
    the floor leaves no stale exclusion behind, and one that fell below
    gains its exclusion in the same rebuild.
    """
    cfg = universe.config
    computed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(connect(database_url)) as connection, connection:
        connection.execute(
            """
            INSERT INTO universe_monthly_build (
                month, effective_from, window_start, window_end,
                top_n, window_days, min_observations, min_dollar_volume,
                member_count, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(month) DO UPDATE SET
                effective_from    = excluded.effective_from,
                window_start      = excluded.window_start,
                window_end        = excluded.window_end,
                top_n             = excluded.top_n,
                window_days       = excluded.window_days,
                min_observations  = excluded.min_observations,
                min_dollar_volume = excluded.min_dollar_volume,
                member_count      = excluded.member_count,
                computed_at       = excluded.computed_at
            """,
            (
                universe.month,
                universe.effective_from.isoformat(),
                universe.window_start.isoformat(),
                universe.window_end.isoformat(),
                cfg.top_n,
                cfg.window_days,
                cfg.min_observations,
                cfg.min_dollar_volume,
                len(universe.members),
                computed_at,
            ),
        )
        connection.execute(
            "DELETE FROM universe_monthly_member WHERE month = ?",
            (universe.month,),
        )
        connection.executemany(
            """
            INSERT INTO universe_monthly_member (
                month, symbol, rank, median_dollar_volume
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (universe.month, member.symbol, member.rank, member.median_dollar_volume)
                for member in universe.members
            ],
        )
        connection.execute(
            "DELETE FROM universe_monthly_exclusion WHERE month = ?",
            (universe.month,),
        )
        connection.executemany(
            """
            INSERT INTO universe_monthly_exclusion (
                month, symbol, median_dollar_volume, reason
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (
                    universe.month,
                    exclusion.symbol,
                    exclusion.median_dollar_volume,
                    exclusion.reason,
                )
                for exclusion in universe.exclusions
            ],
        )
    return len(universe.members)


def load_monthly_universe(
    month: "str | date | datetime",
    database_url: Optional[str] = None,
) -> Optional[MonthlyUniverse]:
    """Rebuild the persisted universe for ``month``, or ``None`` if absent.

    The round trip is lossless: window bounds, config (floor included) and
    every member with its rank and median — plus every exclusion with its
    rejected median and reason — come back exactly as persisted, so a
    loaded universe equals the freshly built one it came from.
    """
    month_text = month_key(month)
    with closing(connect(database_url)) as connection:
        build_row = connection.execute(
            """
            SELECT month, effective_from, window_start, window_end,
                   top_n, window_days, min_observations, min_dollar_volume
            FROM universe_monthly_build WHERE month = ?
            """,
            (month_text,),
        ).fetchone()
        if build_row is None:
            return None
        member_rows = connection.execute(
            """
            SELECT symbol, rank, median_dollar_volume
            FROM universe_monthly_member WHERE month = ?
            ORDER BY rank
            """,
            (month_text,),
        ).fetchall()
        exclusion_rows = connection.execute(
            """
            SELECT symbol, median_dollar_volume, reason
            FROM universe_monthly_exclusion WHERE month = ?
            ORDER BY symbol
            """,
            (month_text,),
        ).fetchall()
    return MonthlyUniverse(
        month=build_row[0],
        effective_from=date.fromisoformat(build_row[1]),
        window_start=date.fromisoformat(build_row[2]),
        window_end=date.fromisoformat(build_row[3]),
        config=UniverseConfig(
            top_n=build_row[4],
            window_days=build_row[5],
            min_observations=build_row[6],
            min_dollar_volume=build_row[7],
        ),
        members=tuple(
            UniverseMember(symbol=row[0], rank=row[1], median_dollar_volume=row[2])
            for row in member_rows
        ),
        exclusions=tuple(
            UniverseExclusion(symbol=row[0], median_dollar_volume=row[1], reason=row[2])
            for row in exclusion_rows
        ),
    )
