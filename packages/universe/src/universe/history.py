"""The retained price history — every symbol's daily closes, delisted ones included.

Feature 43 (app_spec.xml, "Universe & Survivorship Integrity"): the system
retains delisted symbols with their full price history, so a window covering a
symbol's listed period returns it whether or not it is still a universe member.
The point-in-time membership table (feature 41, :mod:`universe.membership`)
records *who was tradable*; this member records *what the price did*, and it
records it for **every** symbol that ever had a bar — members and delistings
alike — because a price store that held only current members would silently
drop every name that later left the universe, which is exactly the survivorship
bias architecture §4.3 is written against.

This is the universe's own price record, deliberately: the ``DailyBar`` in
:mod:`feature_store.bars` also carries ``(symbol, date, close)``, but that is a
*different* package with its own boundary (feature 57's price reductions), and
reusing it here would collapse the two. The universe's ``DailyBar`` (feature 40)
carries dollar volume and no price, because ranking liquidity needs no price;
this member carries the price and no volume, because a window needs the price.
Neither record leaks the other's field, and both live where the consumer lives.

The store is stdlib-only, like the rest of the data spine: it speaks sqlite
through ``DATABASE_URL`` and creates its one table idempotently, so it imports
and runs in the factory scan, in test sandboxes and in the replay path without
resolving a third-party wheel. The survivorship audit (:mod:`universe.audit`)
reads the windows out of this store.

Two properties are enforced rather than implied:

*Retention is by symbol and date.* A bar is keyed by ``(symbol, date)`` and
upserted, so re-ingesting a restated day replaces that day's close rather than
duplicating it — the ingest layer owns exactly-once delivery; if it fails, the
history takes the freshest value, matching :func:`universe.monthly.median_dollar_volumes`'
collapse-to-last semantics. A symbol is never dropped from history because it
left the universe: its rows simply stop accruing, and the span they cover is its
listed period, queryable via :meth:`PriceHistoryStore.listed_range`.

*A window returns a stable ordering.* :meth:`symbols_in_window` returns symbols
sorted ascending, so the set a window hands back is the same set in the same
order on every run — the bit-reproducibility every downstream reduction depends
on starts with the symbols it is handed.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Iterable, Optional

from .bars import coerce_date
from .store import DATABASE_URL_ENV

__all__ = [
    "PriceBar",
    "PriceHistoryStore",
    "symbols_on_connection",
]


def symbols_on_connection(
    connection: sqlite3.Connection,
    window_start: "str | dt.date | dt.datetime",
    window_end: "str | dt.date | dt.datetime",
) -> tuple[str, ...]:
    """The sorted symbols with a bar inside the window, on an open connection.

    The single source of the window query: :meth:`PriceHistoryStore.symbols_in_window`
    and the survivorship audit's in-transaction derivation both go through it,
    so the set a window returns cannot drift between the reader and the audit.
    Inclusive on both bounds, ordered ascending.
    """
    start = coerce_date(window_start).isoformat()
    end = coerce_date(window_end).isoformat()
    rows = connection.execute(
        """
        SELECT DISTINCT symbol FROM universe_price_history
        WHERE date >= ? AND date <= ?
        ORDER BY symbol
        """,
        (start, end),
    ).fetchall()
    return tuple(row[0] for row in rows)


@dataclass(frozen=True)
class PriceBar:
    """One daily price bar: symbol, UTC calendar date, closing price.

    ``date`` is the calendar day the daily candle covers, so a window filters
    bars onto a shared date axis by calendar day. ``close`` is the day's
    closing price in the quote asset; a window returns it and any consumer
    derives returns from it. Validation happens at construction, not use — a
    non-positive or non-finite close cannot take a log return, so a corrupt
    price fails loudly at the boundary rather than silently tilting a
    reduction. The record is frozen: a bar is a fact about the past, and a
    restatement is a new bar that supersedes the old one.
    """

    symbol: str
    date: dt.date
    close: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("PriceBar symbol must be a non-empty, non-blank string")
        if not isinstance(self.date, dt.date):
            raise TypeError(
                f"PriceBar date must be a datetime.date, got {type(self.date).__name__}; "
                "use coerce_date() for strings and datetimes"
            )
        # A datetime IS a date subclass; a daily bar covers a whole day, so
        # accept a datetime but pin it to its UTC calendar date.
        if isinstance(self.date, dt.datetime):
            object.__setattr__(self, "date", self.date.date())
        if not isinstance(self.close, (int, float)):
            raise TypeError(
                "PriceBar close must be a number, got "
                f"{type(self.close).__name__}"
            )
        if math.isnan(self.close) or math.isinf(self.close):
            raise ValueError(
                f"PriceBar close must be finite, got {self.close} for {self.symbol}"
            )
        if self.close <= 0:
            raise ValueError(
                f"PriceBar close must be > 0 (a non-positive price has no "
                f"log return), got {self.close} for {self.symbol} on "
                f"{self.date.isoformat()}"
            )
        object.__setattr__(self, "close", float(self.close))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS universe_price_history (
    symbol  TEXT NOT NULL,
    date    DATE NOT NULL,  -- ISO date, the calendar day the bar covers
    close   REAL NOT NULL,  -- the day's closing price in the quote asset
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS universe_price_history_symbol_date
    ON universe_price_history (symbol, date);
"""


class PriceHistoryStore:
    """Retain daily closes for every symbol and answer window queries.

    Bound to a ``DATABASE_URL`` (captured at construction, overridable per
    call), the store keeps one row per ``(symbol, date)`` and returns, for any
    window, the symbols that have a bar inside it — members and delisted names
    alike. It is thin by design: every method is one query against the retained
    bars, and the survivorship audit is the consumer that walks those windows.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url if database_url is not None else os.environ.get(DATABASE_URL_ENV)

    def _connect(self, database_url: Optional[str] = None) -> sqlite3.Connection:
        from .store import connect

        return connect(database_url if database_url is not None else self.database_url)

    def ingest(self, bars: Iterable[PriceBar], database_url: Optional[str] = None) -> int:
        """Upsert daily price bars, keyed by ``(symbol, date)``; returns the count.

        Idempotent per bar: re-ingesting a restated ``(symbol, date)`` replaces
        its close rather than duplicating it, so a corrected price supersedes
        the stale one in place. Bars are validated at :class:`PriceBar`
        construction, so nothing that reaches the store is a corrupt price.
        """
        rows = [
            (bar.symbol, bar.date.isoformat(), bar.close)
            for bar in bars
        ]
        with closing(self._connect(database_url)) as connection, connection:
            connection.executemany(
                """
                INSERT INTO universe_price_history (symbol, date, close)
                VALUES (?, ?, ?)
                ON CONFLICT(symbol, date) DO UPDATE SET close = excluded.close
                """,
                rows,
            )
        return len(rows)

    def symbols_in_window(
        self,
        window_start: "str | dt.date | dt.datetime",
        window_end: "str | dt.date | dt.datetime",
        database_url: Optional[str] = None,
    ) -> tuple[str, ...]:
        """Every symbol with a bar inside ``[window_start, window_end]``, sorted.

        Inclusive on both bounds, and returned sorted ascending so the ordering
        is stable across runs — the set a window hands a downstream reduction is
        the same set in the same order every time. A symbol delisted after the
        window still appears whenever the window covers a day it traded, which
        is feature 43's whole point: the history is not pruned to current
        members.
        """
        start = coerce_date(window_start).isoformat()
        end = coerce_date(window_end).isoformat()
        with closing(self._connect(database_url)) as connection:
            return symbols_on_connection(connection, start, end)

    def count_symbols_in_window(
        self,
        window_start: "str | dt.date | dt.datetime",
        window_end: "str | dt.date | dt.datetime",
        database_url: Optional[str] = None,
    ) -> int:
        """How many distinct symbols have a bar inside the window."""
        start = coerce_date(window_start).isoformat()
        end = coerce_date(window_end).isoformat()
        with closing(self._connect(database_url)) as connection:
            (count,) = connection.execute(
                """
                SELECT COUNT(DISTINCT symbol) FROM universe_price_history
                WHERE date >= ? AND date <= ?
                """,
                (start, end),
            ).fetchone()
        return count

    def bars(
        self,
        symbol: str,
        window_start: "str | dt.date | dt.datetime",
        window_end: "str | dt.date | dt.datetime",
        database_url: Optional[str] = None,
    ) -> tuple[PriceBar, ...]:
        """One symbol's bars inside the window, oldest first."""
        start = coerce_date(window_start).isoformat()
        end = coerce_date(window_end).isoformat()
        with closing(self._connect(database_url)) as connection:
            rows = connection.execute(
                """
                SELECT symbol, date, close FROM universe_price_history
                WHERE symbol = ? AND date >= ? AND date <= ?
                ORDER BY date
                """,
                (symbol, start, end),
            ).fetchall()
        return tuple(
            PriceBar(symbol=row[0], date=coerce_date(row[1]), close=row[2])
            for row in rows
        )

    def listed_range(
        self, symbol: str, database_url: Optional[str] = None
    ) -> Optional[tuple[dt.date, dt.date]]:
        """The span ``[first_date, last_date]`` a symbol has a bar for, or ``None``.

        The days between these bounds are the symbol's listed period as the
        store observes it — the earliest and latest closes retained. "Any window
        covering its listed period" is checkable against this: a window overlaps
        the listed period when ``window_start <= last_date and window_end >=
        first_date``. ``None`` means the symbol has no history at all.
        """
        with closing(self._connect(database_url)) as connection:
            row = connection.execute(
                """
                SELECT MIN(date), MAX(date) FROM universe_price_history
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
        if row[0] is None:
            return None
        return dt.date.fromisoformat(row[0]), dt.date.fromisoformat(row[1])

    def all_symbols(self, database_url: Optional[str] = None) -> tuple[str, ...]:
        """Every symbol with any retained bar, sorted."""
        with closing(self._connect(database_url)) as connection:
            rows = connection.execute(
                "SELECT DISTINCT symbol FROM universe_price_history ORDER BY symbol"
            ).fetchall()
        return tuple(row[0] for row in rows)
