"""The survivorship audit — feature 44.

Feature 44 (app_spec.xml, "Universe & Survivorship Integrity"): the system
emits a survivorship audit report counting the delisted symbols present in each
historical window. The membership table (feature 41) records who was tradable
and when each symbol left; the price history (feature 43) retains every
symbol's closes, delisted names included. This module crosses the two: for each
monthly window it counts the symbols the universe has *since dropped* that still
have price bars inside that window — the names a current-universe-only view
would silently lose — and renders one line per window.

The definitions are stated once, so the audit and any reader agree:

*Delisted.* A symbol is delisted, for this audit, when its membership interval
has **closed** — ``valid_to is not None`` in the point-in-time table. That is
the store's own record of "left the universe"; it does not guess at the exchange
reason. Whether the departure was an exchange delisting is the price history's
question (features 43 and 44), settled by whether the symbol's closes continue
or stop, not by a reason column here. This matches how
:mod:`universe.membership` already frames the boundary: it records that a symbol
stopped being admitted and defers the delisting-vs-exchange distinction to these
features.

*Present in a window.* A delisted symbol is present in a window when the
retained price history has at least one bar for it inside the window's bounds.
Counting those per window is the survivorship number: it is how many names the
universe has dropped that a naive "current members only" reduction over that
window would still have available — and would therefore silently keep or drop
depending on whether the reduction pruned to membership.

*The windows are the universe's own.* Each audit window's bounds are the
trailing window of the month's build (the same ``window_start``/``window_end``
the build carried), so the audit walks the exact windows the universe was
computed for, not a re-derived grid. A month with no persisted build is absent
from the audit rather than invented — an absence of evidence is reported by the
membership derivation's "unobserved" reason, not papered over here.

Everything here is a pure function of the price history and the membership
intervals, so the same inputs always yield the same report in the same order
(month ascending), and the persisted audit table can be re-derived and compared
byte for byte.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Iterable, Optional

from .bars import coerce_date
from .history import PriceHistoryStore, symbols_on_connection
from .membership import MembershipInterval
from .monthly import MonthlyUniverse

__all__ = [
    "WindowAudit",
    "delisted_symbols",
    "audit_window",
    "survivorship_audit",
    "survivorship_audit_on_connection",
    "render_report",
]


@dataclass(frozen=True)
class WindowAudit:
    """One window's survivorship count: the delisted symbols present in it.

    ``delisted_present`` is the sorted tuple of closed-interval symbols that
    have a price bar inside the window — the names the universe dropped but the
    history still holds for that period. ``delisted_count`` is its length; the
    number feature 44 reports and feature 45 trips on.
    """

    month: str
    window_start: dt.date
    window_end: dt.date
    delisted_present: tuple[str, ...]

    @property
    def delisted_count(self) -> int:
        """How many delisted symbols are present in this window."""
        return len(self.delisted_present)

    def __post_init__(self) -> None:
        if self.delisted_present != tuple(sorted(self.delisted_present)):
            raise ValueError(
                f"WindowAudit {self.month} delisted_present must be sorted, "
                "so the audit is stable across runs and re-derivable"
            )


def delisted_symbols(intervals: Iterable[MembershipInterval]) -> frozenset[str]:
    """The symbols whose membership interval has closed — the delisted set.

    An interval is closed when ``valid_to is not None``: a later build stopped
    admitting the symbol, which is the store's record of departure. Open
    intervals — admitted by the newest build, with no later build to close them
    — are current members, not delistings, so they are excluded.
    """
    return frozenset(
        interval.symbol for interval in intervals if interval.valid_to is not None
    )


def _audit_window(
    symbols_in_window: "Callable[[str | dt.date | dt.datetime, str | dt.date | dt.datetime], tuple[str, ...]]",
    delisted: frozenset[str],
    month: str,
    window_start: "str | dt.date | dt.datetime",
    window_end: "str | dt.date | dt.datetime",
) -> WindowAudit:
    """The delisted symbols with a price bar inside one window.

    ``symbols_in_window`` reads the window's symbols out of the retained
    history — either the store's public query or the in-transaction derivation
    — and this intersects them with the delisted set, so the count is exactly
    the dropped names still present for that period. The intersection is
    sorted, matching the window's own stable ordering.
    """
    start = coerce_date(window_start)
    end = coerce_date(window_end)
    present = symbols_in_window(start, end)
    dropped = tuple(symbol for symbol in present if symbol in delisted)
    return WindowAudit(
        month=month,
        window_start=start,
        window_end=end,
        delisted_present=dropped,
    )


def audit_window(
    store: PriceHistoryStore,
    delisted: frozenset[str],
    month: str,
    window_start: "str | dt.date | dt.datetime",
    window_end: "str | dt.date | dt.datetime",
    database_url: Optional[str] = None,
) -> WindowAudit:
    """The delisted symbols with a price bar inside one window (store-backed).

    Convenience over :func:`survivorship_audit` for a single window: it reads
    the window out of ``store`` and intersects with ``delisted``.
    """
    return _audit_window(
        lambda start, end: store.symbols_in_window(start, end, database_url),
        delisted,
        month,
        window_start,
        window_end,
    )


def survivorship_audit(
    store: PriceHistoryStore,
    intervals: Iterable[MembershipInterval],
    universes: Iterable[MonthlyUniverse],
    database_url: Optional[str] = None,
) -> tuple[WindowAudit, ...]:
    """One :class:`WindowAudit` per monthly build, in month order.

    ``universes`` supplies the windows — each build's own trailing window — and
    ``intervals`` supplies the delisted set. A month with no build is absent
    from the result, so the audit never invents a window the universe did not
    compute. The result is ordered by month, so the report reads chronologically
    and re-derives identically.
    """
    delisted = delisted_symbols(intervals)
    audits: list[WindowAudit] = []
    for universe in sorted(universes, key=lambda build: build.month):
        audits.append(
            _audit_window(
                lambda start, end: store.symbols_in_window(start, end, database_url),
                delisted,
                universe.month,
                universe.window_start,
                universe.window_end,
            )
        )
    return tuple(audits)


def survivorship_audit_on_connection(
    connection: sqlite3.Connection,
    intervals: Iterable[MembershipInterval],
    universes: Iterable[MonthlyUniverse],
) -> tuple[WindowAudit, ...]:
    """One :class:`WindowAudit` per monthly build, derived on an open connection.

    The in-transaction twin of :func:`survivorship_audit`: it reads each
    window's symbols out of ``connection`` via the shared
    :func:`~universe.history.symbols_on_connection` query, so the audit a persist
    writes in its own transaction sees exactly the prices that transaction
    ingested — not a snapshot from a second connection. Called by the store's
    ingest path, which owns the connection; the result is what
    :func:`persist_survivorship_audit` then writes.
    """
    delisted = delisted_symbols(intervals)
    audits: list[WindowAudit] = []
    for universe in sorted(universes, key=lambda build: build.month):
        audits.append(
            _audit_window(
                lambda start, end: symbols_on_connection(connection, start, end),
                delisted,
                universe.month,
                universe.window_start,
                universe.window_end,
            )
        )
    return tuple(audits)


def render_report(audits: Iterable[WindowAudit]) -> tuple[str, ...]:
    """One line per window, in the order given.

    ``"2026-05 [2026-04-01, 2026-04-30] delisted=2: BBBUSDT, CCCUSDT"`` — the
    window bounds and the delisted count, with the names when there are any. A
    clean window reads ``delisted=0`` with no name list, so a reader scanning
    the report sees at a glance which periods held dropped names.
    """
    lines: list[str] = []
    for audit in audits:
        head = (
            f"{audit.month} [{audit.window_start.isoformat()}, "
            f"{audit.window_end.isoformat()}] delisted={audit.delisted_count}"
        )
        if audit.delisted_present:
            lines.append(head + ": " + ", ".join(audit.delisted_present))
        else:
            lines.append(head)
    return tuple(lines)
