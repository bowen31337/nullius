"""Persistence for monthly universe builds.

The monthly universe is not an ephemeral computation: it is a fact about
what was knowable at each month boundary, and everything downstream — the
point-in-time membership table, the survivorship audit, the snapshot's
``universe_definition`` — is derived from these persisted builds. A
universe that exists only in memory is a universe a replay cannot trust.

Storage is the relational store addressed by ``DATABASE_URL`` (SQLite on a
single machine, per the spec's dev allowance; Postgres 16 in production).
This member owns two tables and creates them idempotently — deliberately
*not* the spec's ``universe_membership`` table, which the versioned
migration owns and which carries the derived interval form ``(symbol,
valid_from, valid_to, delist_reason)``. The builds here are the raw
material: one row per month vouching for the exact window and config used,
plus one row per admitted symbol with its rank and its median dollar
volume.

Rebuilding a month is an atomic replace: the build row is upserted and the
member rows are deleted and re-inserted in one transaction, so a reader
never observes half of a rebuild. Two builds of the same month from the
same bars leave the tables byte-identical apart from ``computed_at``,
which records when the build ran — provenance, not a score, so wall-clock
reading here does not touch the replay determinism contract.
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
from .monthly import MonthlyUniverse, UniverseMember, month_key

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


def connect(database_url: Optional[str] = None) -> sqlite3.Connection:
    """Open the store named by ``DATABASE_URL`` (or the given URL).

    Creates the schema if absent and enables foreign keys, so every caller
    gets the same database contract without a migration step. The caller
    owns the connection; use it as a context manager to commit.
    """
    url = database_url if database_url is not None else os.environ[DATABASE_URL_ENV]
    path = _sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.executescript(_SCHEMA)
    return connection


def persist_monthly_universe(
    universe: MonthlyUniverse,
    database_url: Optional[str] = None,
) -> int:
    """Persist one monthly universe build; returns the member count written.

    Idempotent per month: building April twice leaves one build row and one
    row per member, and rebuilding April after its bars were restated
    replaces the membership atomically (upsert the build, delete then
    re-insert the members, all inside one transaction).
    """
    cfg = universe.config
    computed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(connect(database_url)) as connection, connection:
        connection.execute(
            """
            INSERT INTO universe_monthly_build (
                month, effective_from, window_start, window_end,
                top_n, window_days, min_observations, member_count, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(month) DO UPDATE SET
                effective_from    = excluded.effective_from,
                window_start      = excluded.window_start,
                window_end        = excluded.window_end,
                top_n             = excluded.top_n,
                window_days       = excluded.window_days,
                min_observations  = excluded.min_observations,
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
    return len(universe.members)


def load_monthly_universe(
    month: "str | date | datetime",
    database_url: Optional[str] = None,
) -> Optional[MonthlyUniverse]:
    """Rebuild the persisted universe for ``month``, or ``None`` if absent.

    The round trip is lossless: window bounds, config and every member with
    its rank and median come back exactly as persisted, so a loaded
    universe equals the freshly built one it came from.
    """
    month_text = month_key(month)
    with closing(connect(database_url)) as connection:
        build_row = connection.execute(
            """
            SELECT month, effective_from, window_start, window_end,
                   top_n, window_days, min_observations, member_count
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
    return MonthlyUniverse(
        month=build_row[0],
        effective_from=date.fromisoformat(build_row[1]),
        window_start=date.fromisoformat(build_row[2]),
        window_end=date.fromisoformat(build_row[3]),
        config=UniverseConfig(
            top_n=build_row[4],
            window_days=build_row[5],
            min_observations=build_row[6],
        ),
        members=tuple(
            UniverseMember(symbol=row[0], rank=row[1], median_dollar_volume=row[2])
            for row in member_rows
        ),
    )
