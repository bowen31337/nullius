"""Persistence for monthly universe builds.

The monthly universe is not an ephemeral computation: it is a fact about
what was knowable at each month boundary, and everything downstream — the
point-in-time membership table, the survivorship audit, the snapshot's
``universe_definition`` — is derived from these persisted builds. A
universe that exists only in memory is a universe a replay cannot trust.

Storage is the relational store addressed by ``DATABASE_URL`` (SQLite on a
single machine, per the spec's dev allowance; Postgres 16 in production).
This member owns four tables and creates them idempotently. Three hold the
raw material: one row per month vouching for the exact window and config
used (including the liquidity floor), one row per admitted symbol with its
rank and its median dollar volume, and one row per floor-refused symbol
with the rejected median and the persisted exclusion reason — the
difference between "out-ranked" and "not liquid enough" is exactly what an
audit later needs to read off the store, and neither fact may be recomputed
from today's data.

The fourth is ``universe_membership`` — the point-in-time
``(symbol, valid_from, valid_to, delist_reason)`` table of architecture
§4.3, whose shape the spec's schema block fixes and whose versioned
migration (feature 108) creates. It is *derived* here, never authored:
every persist re-derives the whole table from the builds inside the same
transaction, so the interval form and the monthly builds can never
disagree, and a corrected or backfilled month is reflected in membership
the moment it lands — the append-only alternative would let a restated
month leave a stale interval behind for a later replay to trust. The
derivation itself lives in :mod:`universe.membership` and is a pure
function of the builds, so the same month is reachable by re-running it.

Rebuilding a month is an atomic replace: the build row is upserted and the
member and exclusion rows are deleted and re-inserted in one transaction,
so a reader never observes half of a rebuild. Two builds of the same month
from the same bars leave the tables byte-identical apart from
``computed_at``, which records when the build ran — provenance, not a
score, so wall-clock reading here does not touch the replay determinism
contract.

Feature 45's survivorship gate rides this persist path: after the
membership table is re-derived, the build's own trailing window is checked
against what the store knows — a window the membership table says
contained names that left, whose price history is populated, and whose
delisted count is therefore 0 is a window on pruned history, and the
persist raises :class:`~universe.gate.UniverseBuildRejected` inside the
transaction so nothing lands. The two honest zeros pass untouched: a
clean period counts 0, and a window with no bars at all is an absence of
evidence, not proof of pruning. See :mod:`universe.gate` for the
definitions.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import unquote, urlparse

from .config import UniverseConfig
from .membership import MembershipInterval, membership_intervals
from .monthly import MonthlyUniverse, UniverseExclusion, UniverseMember, month_key

__all__ = [
    "DATABASE_URL_ENV",
    "connect",
    "persist_monthly_universe",
    "persist_universe_membership",
    "load_monthly_universe",
    "load_all_monthly_universes",
    "load_universe_membership",
    "persist_price_history",
    "load_survivorship_audit",
    "persist_survivorship_audit",
]

DATABASE_URL_ENV = "DATABASE_URL"

# The build row's columns, in the order _build_from_rows unpacks them. Kept
# as one string so the single-month reader and the all-builds reader cannot
# drift apart in column order — the failure that would silently swap a
# window bound for a config knob.
_BUILD_COLUMNS = (
    "month, effective_from, window_start, window_end, "
    "top_n, window_days, min_observations, min_dollar_volume"
)

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

-- The point-in-time membership table of architecture §4.3, in the shape the
-- spec's schema block fixes: (symbol, valid_from, valid_to, delist_reason).
-- Derived from the monthly builds on every persist; see module docstring.
CREATE TABLE IF NOT EXISTS universe_membership (
    symbol        TEXT NOT NULL,
    valid_from    DATE NOT NULL,  -- inclusive: first day of the first admitted month
    valid_to      DATE,           -- exclusive; NULL while the interval is open
    delist_reason TEXT,           -- NULL exactly while the interval is open
    PRIMARY KEY (symbol, valid_from)
);
CREATE INDEX IF NOT EXISTS universe_membership_symbol_valid_from
    ON universe_membership (symbol, valid_from);

-- Feature 43: the retained price history. One row per (symbol, date) — every
-- symbol that ever had a bar, members and delisted names alike, so a window
-- covering a symbol's listed period returns it whether or not it is still a
-- member. Survivorship bias is pruned histories; this table is not pruned.
CREATE TABLE IF NOT EXISTS universe_price_history (
    symbol  TEXT NOT NULL,
    date    DATE NOT NULL,  -- ISO date, the calendar day the bar covers
    close   REAL NOT NULL,  -- the day's closing price in the quote asset
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS universe_price_history_symbol_date
    ON universe_price_history (symbol, date);

-- Feature 44: the survivorship audit, derived from the builds and the price
-- history. One row per month: how many (and which) symbols the universe has
-- since dropped are still present in that month's window. Re-derived on ingest
-- so it can never lag the history it summarises.
CREATE TABLE IF NOT EXISTS universe_survivorship_audit (
    month              TEXT PRIMARY KEY,  -- 'YYYY-MM'
    window_start       DATE NOT NULL,     -- inclusive start of the build's trailing window
    window_end         DATE NOT NULL,     -- inclusive end (day before the month starts)
    delisted_present   INTEGER NOT NULL,  -- count of delisted symbols present in the window
    delisted_symbols   JSON NOT NULL      -- JSON array of those symbols, sorted
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

    The point-in-time ``universe_membership`` table (feature 41) is
    re-derived from the builds inside that same transaction, so a persist
    never leaves the interval form lagging behind the monthly facts it is
    derived from. A symbol admitted by this build gains its interval here;
    a symbol this build dropped has its interval closed, with the reason
    this build supplies.

    The re-derived table then feeds the survivorship gate (feature 45):
    if this build's own trailing window is known — from that membership —
    to contain delistings, is populated in the retained price history, and
    yet would count ``delisted=0``, :class:`~universe.gate.UniverseBuildRejected`
    is raised inside the transaction and the whole persist rolls back, so
    a rejected build leaves the store exactly as it was. Ingest the
    missing names' price history and re-present the build.
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
        intervals = _recompute_membership(connection)
        _reject_survivorship_gap(connection, universe, intervals)
    return len(universe.members)


def _build_from_rows(
    build_row: tuple,
    member_rows: list[tuple],
    exclusion_rows: list[tuple],
) -> MonthlyUniverse:
    """Map one build's persisted rows back to a :class:`MonthlyUniverse`.

    The single row-to-value mapping in this module: both readers go through
    it, so a column added to the build table is decoded in exactly one
    place. ``build_row`` is in ``_BUILD_COLUMNS`` order.
    """
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
            f"SELECT {_BUILD_COLUMNS} FROM universe_monthly_build WHERE month = ?",
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
    return _build_from_rows(build_row, member_rows, exclusion_rows)


def load_all_monthly_universes(
    database_url: Optional[str] = None,
) -> tuple[MonthlyUniverse, ...]:
    """Every persisted build, oldest month first.

    The membership derivation is a function of the whole build history, so
    it needs the whole history in hand; this is the reader that supplies
    it. Loading each build through :func:`load_monthly_universe` keeps one
    row-to-value mapping in the codebase rather than two that could drift.
    """
    with closing(connect(database_url)) as connection:
        months = [
            row[0]
            for row in connection.execute(
                "SELECT month FROM universe_monthly_build ORDER BY month"
            ).fetchall()
        ]
    return tuple(
        universe
        for universe in (
            load_monthly_universe(month, database_url) for month in months
        )
        if universe is not None
    )


def _recompute_membership(connection: sqlite3.Connection) -> tuple[MembershipInterval, ...]:
    """Re-derive ``universe_membership`` from the builds on ``connection``.

    Called inside the persist transaction, after the month's own rows are
    written, so the derivation always sees the build it was just handed.
    The table is replaced wholesale (delete then insert) rather than
    patched: an interval's end can move when a later month is built or an
    earlier one is restated, and a wholesale replace is the one operation
    that cannot leave a stale interval behind. Returns the intervals
    written, so the caller can hand them to the survivorship gate without
    re-deriving — the rows and the gate must see one membership.

    Ordering is the derivation's own — ``(valid_from, symbol)`` — so the
    rows land identically for identical builds.
    """
    connection.execute("DELETE FROM universe_membership")
    intervals = membership_intervals(_load_builds_on(connection))
    connection.executemany(
        """
        INSERT INTO universe_membership (
            symbol, valid_from, valid_to, delist_reason
        ) VALUES (?, ?, ?, ?)
        """,
        [
            (
                interval.symbol,
                interval.valid_from.isoformat(),
                interval.valid_to.isoformat() if interval.valid_to else None,
                interval.delist_reason,
            )
            for interval in intervals
        ],
    )
    return intervals


def _reject_survivorship_gap(
    connection: sqlite3.Connection,
    universe: MonthlyUniverse,
    intervals: tuple[MembershipInterval, ...],
) -> None:
    """Refuse to persist a build whose own window under-reports (feature 45).

    The gate sees the membership this transaction just re-derived — so the
    names *this* build drops are in scope — and reads the build's window
    on the same connection, so the verdict matches the store it would
    leave behind. Raising inside the persist transaction rolls back every
    write above: the build row, members, exclusions and membership rows
    all stay unwritten, and the caller is told which names to ingest.
    """
    # Imported here, not at module top: gate imports history, and history
    # imports store — the same cycle _recompute_survivorship_audit dodges.
    from .gate import reject_survivorship_gaps, survivorship_gaps_on_connection

    reject_survivorship_gaps(
        survivorship_gaps_on_connection(connection, intervals, (universe,))
    )


def _load_builds_on(connection: sqlite3.Connection) -> tuple[MonthlyUniverse, ...]:
    """Read every build on an open ``connection``, oldest month first.

    The in-transaction twin of :func:`load_all_monthly_universes` — it must
    see the uncommitted row the caller just wrote, so it cannot open its
    own connection.
    """
    months = [
        row[0]
        for row in connection.execute(
            "SELECT month FROM universe_monthly_build ORDER BY month"
        ).fetchall()
    ]
    builds: list[MonthlyUniverse] = []
    for month in months:
        build_row = connection.execute(
            f"SELECT {_BUILD_COLUMNS} FROM universe_monthly_build WHERE month = ?",
            (month,),
        ).fetchone()
        if build_row is None:  # pragma: no cover - read back inside one txn
            continue
        builds.append(
            _build_from_rows(
                build_row,
                connection.execute(
                    """
                    SELECT symbol, rank, median_dollar_volume
                    FROM universe_monthly_member WHERE month = ? ORDER BY rank
                    """,
                    (month,),
                ).fetchall(),
                connection.execute(
                    """
                    SELECT symbol, median_dollar_volume, reason
                    FROM universe_monthly_exclusion WHERE month = ? ORDER BY symbol
                    """,
                    (month,),
                ).fetchall(),
            )
        )
    return tuple(builds)


def persist_universe_membership(database_url: Optional[str] = None) -> int:
    """Re-derive and replace the membership table; returns the rows written.

    :func:`persist_monthly_universe` already does this on every build, so
    this exists for the two cases that have no build to hand: repairing a
    store whose membership table was dropped or written by an older
    version, and the tests that assert the derivation is reproducible.
    """
    with closing(connect(database_url)) as connection, connection:
        return len(_recompute_membership(connection))


def load_universe_membership(
    database_url: Optional[str] = None,
) -> tuple[MembershipInterval, ...]:
    """Read the persisted point-in-time membership table, ordered by date.

    Rows come back ordered by ``(valid_from, symbol)`` — the derivation's
    own order — so a caller comparing a loaded table against a freshly
    derived one compares like with like.
    """
    with closing(connect(database_url)) as connection:
        rows = connection.execute(
            """
            SELECT symbol, valid_from, valid_to, delist_reason
            FROM universe_membership
            ORDER BY valid_from, symbol
            """
        ).fetchall()
    return tuple(
        MembershipInterval(
            symbol=row[0],
            valid_from=date.fromisoformat(row[1]),
            valid_to=date.fromisoformat(row[2]) if row[2] else None,
            delist_reason=row[3],
        )
        for row in rows
    )


def persist_price_history(
    bars: Iterable,
    database_url: Optional[str] = None,
) -> int:
    """Upsert daily price bars into ``universe_price_history``; returns the count.

    Feature 43's retention path: every bar is keyed by ``(symbol, date)`` and
    upserted, so re-ingesting a restated day replaces its close in place rather
    than duplicating it. The bars may be this member's :class:`~universe.history.PriceBar`
    or anything with ``symbol``/``date``/``close`` attributes; they are read
    positionally, so the store does not import the dataclass (the dataclass
    validates; this writes).
    """
    rows = [(bar.symbol, bar.date.isoformat(), bar.close) for bar in bars]
    with closing(connect(database_url)) as connection, connection:
        connection.executemany(
            """
            INSERT INTO universe_price_history (symbol, date, close)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol, date) DO UPDATE SET close = excluded.close
            """,
            rows,
        )
    return len(rows)


def _recompute_survivorship_audit(
    connection: sqlite3.Connection,
    universes: Iterable,
    intervals: Iterable[MembershipInterval],
) -> int:
    """Re-derive ``universe_survivorship_audit`` on an open ``connection``.

    Called inside the ingest transaction, after the prices it summarises are
    written, so the audit always sees the bars it was just handed. The table is
    replaced wholesale (delete then insert), the same operation that cannot
    leave a stale window behind that :func:`_recompute_membership` uses. The
    per-window symbols come from the shared window query, so the audit and the
    reader agree on what "present in a window" means. Returns the row count.
    """
    # Imported here, not at module top: history imports store, so a top-level
    # import would be a cycle. Both are plain functions over a connection.
    from .audit import survivorship_audit_on_connection

    connection.execute("DELETE FROM universe_survivorship_audit")
    audits = survivorship_audit_on_connection(connection, intervals, universes)
    connection.executemany(
        """
        INSERT INTO universe_survivorship_audit
            (month, window_start, window_end, delisted_present, delisted_symbols)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                audit.month,
                audit.window_start.isoformat(),
                audit.window_end.isoformat(),
                audit.delisted_count,
                json.dumps(audit.delisted_present),
            )
            for audit in audits
        ],
    )
    return len(audits)


def persist_survivorship_audit(
    universes: Iterable,
    intervals: Iterable[MembershipInterval],
    database_url: Optional[str] = None,
) -> int:
    """Re-derive and replace the survivorship audit; returns the rows written.

    Ingest re-derives the audit alongside the prices it summarises, so this
    exists for the case with no ingest to hand: repairing a store whose audit
    table was dropped, or a tool that restates prices or membership out of band.
    Idempotent — running it twice leaves the same rows.
    """
    from .audit import survivorship_audit

    with closing(connect(database_url)) as connection, connection:
        return _recompute_survivorship_audit(connection, universes, intervals)


def load_survivorship_audit(
    database_url: Optional[str] = None,
) -> tuple:
    """Read the persisted survivorship audit, one :class:`~universe.audit.WindowAudit`
    per month, oldest first.

    Rows come back ordered by month — the derivation's own order — so a caller
    comparing a loaded audit against a freshly derived one compares like with
    like.
    """
    from .audit import WindowAudit

    with closing(connect(database_url)) as connection:
        rows = connection.execute(
            """
            SELECT month, window_start, window_end, delisted_present, delisted_symbols
            FROM universe_survivorship_audit
            ORDER BY month
            """
        ).fetchall()
    return tuple(
        WindowAudit(
            month=row[0],
            window_start=date.fromisoformat(row[1]),
            window_end=date.fromisoformat(row[2]),
            delisted_present=tuple(json.loads(row[4])),
        )
        for row in rows
    )
