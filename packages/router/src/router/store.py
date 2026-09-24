"""Persistence for the fetched exchangeInfo version (feature 310).

app_spec.xml, "Order Routing & Venue Filters", feature 310: *System persists
the fetched exchangeInfo version carrying lot size, notional, price filter,
step size and tick size.*  :mod:`router.exchange_info` narrows a fetch down
to the per-symbol values that sentence names; this module writes that
narrowed value down and reads it back.

**Two tables, because a version and its symbols are two different shapes.**
``router_exchange_info_version`` is one row per fetch — the version number
and when it was fetched — and ``router_exchange_info_filter`` is one row per
symbol *within* a version.  Collapsing them into one denormalised table
would mean either repeating ``fetched_at`` on every symbol row (letting two
rows of the same version silently disagree about when their version was
fetched) or losing a version that carried zero symbols entirely — and the
ingest member's own parser already refuses that document before it reaches
here, so the version table is what still lets a reader ask "when was
version 7 fetched?" without scanning its filter rows.

**Each fetch is a new version; none is ever overwritten.**  The version
column is ``INTEGER PRIMARY KEY AUTOINCREMENT``, the same mechanism
:mod:`ledger.store` uses for the trial sequence and for the identical
reason: the monotonic high-water mark is a property of the table itself,
persisted beside the rows, so two processes recording a fetch at once still
each land a distinct, never-reused version number rather than racing to
compute one.  There is no update-in-place API surface here and no delete —
the row a fetch wrote is the record a later reader resolves filters
against, exactly the discipline the ingest member's own version log keeps
for the research lake, applied here to the router's own log for the live
order path.

**A version's filter values are read exactly as recorded.**  Every column
is ``TEXT`` and every value is the venue's own string spelling — never
coerced to a number here, so a step size the order path rounds by
(feature 312) or a minimum notional it refuses below (feature 313) is
whatever the venue actually said, not a re-render of it.

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as the cost model's, the universe member's and the snapshot
member's tables are: ``sqlite:///`` on a single machine, Postgres in
production.  The schema is created idempotently on connect, so no
migration step is needed for this member; a URL whose scheme is not
``sqlite`` is refused by name rather than spoken with a SQL dialect this
member has never been run against.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from .errors import RouterStoreError
from .exchange_info import RouterSymbolFilters, resolve_router_filters

__all__ = [
    "DATABASE_URL_ENV",
    "ROUTER_EXCHANGE_INFO_FILTER_TABLE",
    "ROUTER_EXCHANGE_INFO_VERSION_TABLE",
    "RouterExchangeInfoStore",
    "RouterExchangeInfoVersion",
]

#: The workspace-wide environment variable naming the relational store.
DATABASE_URL_ENV = "DATABASE_URL"

#: One row per fetch: the version number and when it was fetched.
ROUTER_EXCHANGE_INFO_VERSION_TABLE = "router_exchange_info_version"

#: One row per symbol within a version: the five feature-310 fields.
ROUTER_EXCHANGE_INFO_FILTER_TABLE = "router_exchange_info_filter"

_SCHEMA = f"""
-- Feature 310: the fetched exchangeInfo version, one row per fetch.
--
-- AUTOINCREMENT makes the version number a durable high-water mark the
-- table itself tracks, never reused and never computed by a racing
-- SELECT MAX() + 1 -- see the module docstring.
CREATE TABLE IF NOT EXISTS {ROUTER_EXCHANGE_INFO_VERSION_TABLE} (
    version     INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at  TEXT NOT NULL,  -- ISO 8601 UTC: when the fetch happened
    source      TEXT            -- where the fetch came from (provenance)
);

-- Feature 310: one symbol's narrowed filters within one version.
--
-- Every value is TEXT, the venue's own spelling, never coerced here -- see
-- the module docstring.  NULL means the venue's document did not carry
-- that filter (or field) for this symbol, distinct from the string "0".
CREATE TABLE IF NOT EXISTS {ROUTER_EXCHANGE_INFO_FILTER_TABLE} (
    version       INTEGER NOT NULL,
    symbol        TEXT NOT NULL,
    step_size     TEXT,  -- LOT_SIZE.stepSize
    min_qty       TEXT,  -- LOT_SIZE.minQty
    max_qty       TEXT,  -- LOT_SIZE.maxQty
    tick_size     TEXT,  -- PRICE_FILTER.tickSize
    min_price     TEXT,  -- PRICE_FILTER.minPrice
    max_price     TEXT,  -- PRICE_FILTER.maxPrice
    min_notional  TEXT,  -- NOTIONAL.minNotional (or MIN_NOTIONAL.minNotional)
    PRIMARY KEY (version, symbol)
);
"""


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    Follows the same SQLAlchemy convention and refusal
    :mod:`cost_model.store` documents: ``sqlite:///foo.db`` is relative,
    ``sqlite:////foo.db`` is absolute, and any other scheme is refused
    loudly rather than silently mis-parsed.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "router's exchangeInfo store speaks sqlite:/// (the spec's "
            "single-machine allowance), and the Postgres tree store arrives "
            "with the versioned migration"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise RouterStoreError(f"sqlite {DATABASE_URL_ENV} carries no database path")
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> None:
    if not isinstance(moment, datetime):
        raise TypeError(f"{what} must be a datetime, not {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{what} must be timezone-aware; a persisted fetch must say "
            f"unambiguously when it happened"
        )


@dataclass(frozen=True)
class RouterExchangeInfoVersion:
    """One persisted fetch: its version, when it was fetched, and its symbols.

    ``symbols`` maps a symbol to its :class:`~router.exchange_info.
    RouterSymbolFilters` — feature 310's narrowed lot size, notional, price
    filter, step size and tick size for that symbol, within this version.
    """

    version: int
    fetched_at: datetime
    source: str | None
    symbols: Mapping[str, RouterSymbolFilters]

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", dict(self.symbols))

    @property
    def symbol_count(self) -> int:
        """How many symbols this version carries."""
        return len(self.symbols)

    def filters_for(self, symbol: str) -> RouterSymbolFilters | None:
        """This version's filters for ``symbol``, or ``None`` when absent."""
        return self.symbols.get(symbol)


class RouterExchangeInfoStore:
    """Reads and appends the router's own exchangeInfo version log.

    Bound to a database URL at construction; construction performs no I/O,
    so composing an application never touches the database.  Each
    operation opens its own connection (creating the schema idempotently if
    absent), the same discipline :class:`ledger.store.TrialLedger` and
    :mod:`cost_model.store` follow, so the database file — not any
    process's memory — is the coordination point for the version sequence.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RouterStoreError(f"{DATABASE_URL_ENV} must be a non-empty database URL")
        self._database_url = database_url.strip()

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RouterExchangeInfoStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the same
        deployment-without-a-store stance :class:`ledger.store.TrialLedger`
        and the snapshot member's manifest store take: absent is a
        discoverable state, not an exception, and composes no ``router``
        component at all.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store reads and writes."""
        return self._database_url

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    # -- Writing ----------------------------------------------------------------

    def record(
        self,
        document,
        *,
        fetched_at: datetime,
        source: str | None = None,
    ) -> RouterExchangeInfoVersion:
        """Persist one fetch as the next version; never overwrite a prior one.

        ``document`` is parsed and narrowed first (via
        :func:`~router.exchange_info.resolve_router_filters`), so a fetch
        that is not a well-formed exchangeInfo document raises
        :class:`~router.errors.RouterFilterError` *before* anything is
        written and consumes no version number.

        ``fetched_at`` is required and must be timezone-aware, the same
        discipline the ingest member's own version store holds its callers
        to — a naive timestamp cannot say unambiguously when a version was
        fetched.
        """
        _require_aware(fetched_at, "fetched_at")
        symbols = resolve_router_filters(document)
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    f"""
                    INSERT INTO {ROUTER_EXCHANGE_INFO_VERSION_TABLE}
                        (fetched_at, source)
                    VALUES (?, ?)
                    """,
                    (_isoformat_utc(fetched_at), source),
                )
                version = cursor.lastrowid
                connection.executemany(
                    f"""
                    INSERT INTO {ROUTER_EXCHANGE_INFO_FILTER_TABLE} (
                        version, symbol, step_size, min_qty, max_qty,
                        tick_size, min_price, max_price, min_notional
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            version,
                            filters.symbol,
                            filters.step_size,
                            filters.min_qty,
                            filters.max_qty,
                            filters.tick_size,
                            filters.min_price,
                            filters.max_price,
                            filters.min_notional,
                        )
                        for filters in symbols.values()
                    ],
                )
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not persist the fetched exchangeInfo version: {exc}"
            ) from exc
        return RouterExchangeInfoVersion(
            version=version,
            fetched_at=fetched_at.astimezone(UTC),
            source=source,
            symbols=symbols,
        )

    # -- Reading ------------------------------------------------------------

    def current(self) -> RouterExchangeInfoVersion | None:
        """The most recently persisted version, or ``None`` when none exists.

        ``None`` is the honest answer for an empty log: a store that has
        never recorded a fetch has no tick size to offer, and the order
        path must never be handed a default here — that would be exactly
        the hardcoded venue constant feature 311 forbids.
        """
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT version, fetched_at, source
                    FROM {ROUTER_EXCHANGE_INFO_VERSION_TABLE}
                    ORDER BY version DESC
                    LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    return None
                return self._read(connection, row)
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read the current exchangeInfo version: {exc}"
            ) from exc

    def version(self, version: int) -> RouterExchangeInfoVersion | None:
        """The version persisted under ``version``, or ``None`` if never recorded."""
        if not isinstance(version, int) or isinstance(version, bool):
            raise TypeError(f"a version is an integer, not {type(version).__name__}")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT version, fetched_at, source
                    FROM {ROUTER_EXCHANGE_INFO_VERSION_TABLE}
                    WHERE version = ?
                    """,
                    (version,),
                ).fetchone()
                if row is None:
                    return None
                return self._read(connection, row)
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read exchangeInfo version {version}: {exc}"
            ) from exc

    def filters_for(self, symbol: str) -> RouterSymbolFilters | None:
        """The current version's filters for ``symbol``, the order path's read.

        Reads only the one symbol's row rather than the whole version, the
        fast synchronous lookup the order path needs immediately before
        submitting an order.  ``None`` when no version has ever been
        recorded, or the current version's document omitted the symbol —
        deliberately not a fallback to an older version's value, since a
        symbol the venue has stopped listing must not be tradeable off a
        stale grid.
        """
        if not isinstance(symbol, str) or not symbol:
            raise TypeError(f"symbol must be a non-empty string, got {symbol!r}")
        try:
            with closing(self._connect()) as connection:
                current_version = connection.execute(
                    f"SELECT MAX(version) FROM {ROUTER_EXCHANGE_INFO_VERSION_TABLE}"
                ).fetchone()[0]
                if current_version is None:
                    return None
                row = connection.execute(
                    f"""
                    SELECT symbol, step_size, min_qty, max_qty, tick_size,
                           min_price, max_price, min_notional
                    FROM {ROUTER_EXCHANGE_INFO_FILTER_TABLE}
                    WHERE version = ? AND symbol = ?
                    """,
                    (current_version, symbol),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read filters for {symbol!r}: {exc}"
            ) from exc
        if row is None:
            return None
        return RouterSymbolFilters(
            symbol=row[0],
            step_size=row[1],
            min_qty=row[2],
            max_qty=row[3],
            tick_size=row[4],
            min_price=row[5],
            max_price=row[6],
            min_notional=row[7],
        )

    def _read(
        self, connection: sqlite3.Connection, row: tuple
    ) -> RouterExchangeInfoVersion:
        version, fetched_at_raw, source = row
        rows = connection.execute(
            f"""
            SELECT symbol, step_size, min_qty, max_qty, tick_size,
                   min_price, max_price, min_notional
            FROM {ROUTER_EXCHANGE_INFO_FILTER_TABLE}
            WHERE version = ?
            """,
            (version,),
        ).fetchall()
        symbols = {
            entry[0]: RouterSymbolFilters(
                symbol=entry[0],
                step_size=entry[1],
                min_qty=entry[2],
                max_qty=entry[3],
                tick_size=entry[4],
                min_price=entry[5],
                max_price=entry[6],
                min_notional=entry[7],
            )
            for entry in rows
        }
        return RouterExchangeInfoVersion(
            version=version,
            fetched_at=datetime.fromisoformat(fetched_at_raw),
            source=source,
            symbols=symbols,
        )
