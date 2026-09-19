"""The survivorship gate — feature 45.

Feature 45 (app_spec.xml, "Universe & Survivorship Integrity"): the system
rejects a universe build whose delisted-symbol count is 0 across a period
known to contain delistings. Feature 44 counts, for each historical
window, the delisted names the retained price history still holds; this
module is the tripwire on that number. A window the store's own records
place a since-departed name inside, and whose history is populated, must
count at least one delisted symbol. A zero there is not a clean period —
it is the signature of a history pruned to the survivors, and a universe
persisted on pruned history is the survivorship bias architecture §4.3 is
written against, promoted to a fact every downstream reduction would
inherit. The gate declines to make it one.

The definitions are stated once, so the gate and any reader agree:

*Known to contain delistings.* A window is known to contain delistings
when the point-in-time membership table (feature 41) vouches that a name
which has since left was a member during it: some closed interval —
``valid_to`` is set, the same definition of delisted the audit
(:mod:`universe.audit`) already uses — overlaps the window's bounds
(``valid_from <= window_end`` and ``valid_to > window_start``). A symbol
whose membership covered part of a window was tradable in that part, so
its closes belong in the window's history; the knowledge is the store's
own record, not an inference about the exchange. Departures that ended at
or before the window began, and memberships that started after it ended,
are delistings the period does not contain.

*A populated window.* The retained price history (feature 43) holds at
least one bar inside the window. This control keeps the two honest zeros
honest. A period with no delistings counts zero, and a period whose
history is not populated counts zero because there is nothing to count —
an absence of evidence, the same stance the monthly sweep's skip reasons
and the audit's clean-window line already take. The gate fires only on
the third zero, the one no honest store produces: bars present, delisted
names absent — a history that held current members and dropped the names
that left.

*Rejected.* The build is refused, not flagged. On the persist path the
gate runs inside the persist transaction (:mod:`universe.store`), after
the membership table is re-derived from the build about to land, so the
build's own delistings — the names it drops — are in scope; raising rolls
the whole transaction back, and a rejected build leaves the store exactly
as it was. The operator's recourse is the message's own instruction:
ingest the missing names' price history and re-present the build. The
gate never deletes and never repairs; it only declines to persist a
universe whose own provenance window disproves its history.

Everything here is a pure function of the membership intervals, the
builds' windows and the retained history, and it reads windows through
the same query the audit reads (:func:`universe.history.symbols_on_connection`),
so "present in a window" cannot mean one thing to the report and another
to the gate that rejects builds on it. Gaps are derived in month order
and carry sorted names, so the same store always yields the same
rejection, message included, every time.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Iterable, Optional

from .audit import delisted_symbols
from .bars import coerce_date
from .history import PriceHistoryStore, symbols_on_connection
from .membership import MembershipInterval
from .monthly import MonthlyUniverse
from .ordering import canonical_symbol_order

__all__ = [
    "SurvivorshipGap",
    "UniverseBuildRejected",
    "known_delistings",
    "survivorship_gaps",
    "survivorship_gaps_on_connection",
    "reject_survivorship_gaps",
]


@dataclass(frozen=True)
class SurvivorshipGap:
    """One window the audit under-reports: delisted names it should hold.

    ``missing`` is the sorted tuple of delisted symbols the membership
    table places inside this window and the retained price history does
    not — the names a current-members-only store would have silently
    dropped, which is exactly the store this gate refuses to build on.
    """

    month: str
    window_start: dt.date
    window_end: dt.date
    missing: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.missing != tuple(sorted(self.missing)):
            raise ValueError(
                f"SurvivorshipGap {self.month} missing must be sorted, "
                "so a rejection is stable across runs and re-derivable"
            )


class UniverseBuildRejected(ValueError):
    """A build refused by the survivorship gate (feature 45).

    Subclasses :class:`ValueError` because a rejected build is a refusal
    of bad input, the same way a malformed bar or a mistyped knob is —
    but named, so an operator catching it can tell "the history is
    missing the delisted names" apart from any other loud failure. The
    message names every offending window with its bounds and the delisted
    symbols the retained history does not hold.
    """


def known_delistings(
    intervals: Iterable[MembershipInterval],
    window_start: "str | dt.date | dt.datetime",
    window_end: "str | dt.date | dt.datetime",
) -> tuple[str, ...]:
    """The delisted symbols the membership table places inside one window.

    A name belongs here when some *closed* interval of it overlaps the
    window — the symbol was a member during part of the period, and a
    later build has closed the interval, which is the store's record that
    the period contained a name that left. Open intervals are current
    members, not delistings; a closed interval that ended at or before the
    window began is a departure the period does not contain, as is a
    membership that started after it ended. In the canonical order
    (:func:`universe.ordering.canonical_symbol_order`, feature 46), so the
    knowledge is stated the same way every time.
    """
    start = coerce_date(window_start)
    end = coerce_date(window_end)
    return canonical_symbol_order(
        interval.symbol
        for interval in intervals
        if interval.valid_to is not None
        and interval.valid_from <= end
        and interval.valid_to > start
    )


def _gap_for(
    symbols_in_window: "Callable[[str | dt.date | dt.datetime, str | dt.date | dt.datetime], tuple[str, ...]]",
    intervals: tuple[MembershipInterval, ...],
    delisted: frozenset[str],
    universe: MonthlyUniverse,
) -> Optional[SurvivorshipGap]:
    """One build's gap, or ``None`` when its window's zero is honest.

    ``symbols_in_window`` reads the window's symbols out of the retained
    history — the store's public query or the in-transaction derivation —
    so the gate and the audit (:mod:`universe.audit`) see one history.
    The three honest outs are checked cheapest-first: no delisting known
    for the period (a clean window), no bars at all in it (an unpopulated
    window — absence of evidence, not proof of pruning), and a delisted
    name present (the count is non-zero already). What remains is the one
    zero the store must not persist: the period held members, the
    membership table says names left during it, and none of those names
    is in the history.
    """
    known = known_delistings(intervals, universe.window_start, universe.window_end)
    if not known:
        return None
    present = symbols_in_window(universe.window_start, universe.window_end)
    if not present:
        return None
    if any(symbol in delisted for symbol in present):
        return None
    return SurvivorshipGap(
        month=universe.month,
        window_start=universe.window_start,
        window_end=universe.window_end,
        missing=tuple(symbol for symbol in known if symbol not in present),
    )


def survivorship_gaps(
    store: PriceHistoryStore,
    intervals: Iterable[MembershipInterval],
    universes: Iterable[MonthlyUniverse],
    database_url: Optional[str] = None,
) -> tuple[SurvivorshipGap, ...]:
    """Every build whose window under-reports the delistings it contains.

    ``universes`` supplies the windows — each build's own trailing window,
    the same bounds the audit walks — and ``intervals`` supplies both the
    delisted set and the per-window knowledge. Months are visited in
    order, so the gaps come back oldest-first and a rejection derived
    from them reads chronologically. Windows absent from ``universes``
    are not invented: a month with no persisted build has no window to
    under-report.
    """
    materialized = tuple(intervals)
    delisted = delisted_symbols(materialized)
    gaps: list[SurvivorshipGap] = []
    for universe in sorted(universes, key=lambda build: build.month):
        gap = _gap_for(
            lambda start, end: store.symbols_in_window(start, end, database_url),
            materialized,
            delisted,
            universe,
        )
        if gap is not None:
            gaps.append(gap)
    return tuple(gaps)


def survivorship_gaps_on_connection(
    connection: sqlite3.Connection,
    intervals: Iterable[MembershipInterval],
    universes: Iterable[MonthlyUniverse],
) -> tuple[SurvivorshipGap, ...]:
    """Every under-reporting window, derived on an open connection.

    The in-transaction twin of :func:`survivorship_gaps`: it reads each
    window through the shared :func:`~universe.history.symbols_on_connection`
    query, so the gate a persist runs inside its own transaction sees
    exactly the prices that transaction's store holds — including the
    membership rows the same transaction just re-derived — and not a
    snapshot from a second connection.
    """
    materialized = tuple(intervals)
    delisted = delisted_symbols(materialized)
    gaps: list[SurvivorshipGap] = []
    for universe in sorted(universes, key=lambda build: build.month):
        gap = _gap_for(
            lambda start, end: symbols_on_connection(connection, start, end),
            materialized,
            delisted,
            universe,
        )
        if gap is not None:
            gaps.append(gap)
    return tuple(gaps)


def reject_survivorship_gaps(gaps: Iterable[SurvivorshipGap]) -> None:
    """Raise for every gap given, or return quietly when there are none.

    One :class:`UniverseBuildRejected` names all the offending windows —
    month, bounds and the delisted symbols missing from each — followed
    by the one instruction that clears it. The caller has already derived
    the gaps (from the store, or on its connection); this function is the
    verdict, kept separate so a tool can inspect the gaps without
    tripping and the persist path can trip with them in hand.
    """
    materialized = tuple(gaps)
    if not materialized:
        return
    details = "; ".join(
        f"{gap.month} window [{gap.window_start.isoformat()}, "
        f"{gap.window_end.isoformat()}] is known to contain delistings "
        f"({', '.join(gap.missing)}) but the survivorship audit counts "
        "delisted=0 across it"
        for gap in materialized
    )
    raise UniverseBuildRejected(
        f"universe build rejected: {details} — a populated window that "
        "holds none of the names the membership table says left during it "
        "is a pruned history, and a universe persisted on it would bake "
        "survivorship bias in; ingest the missing symbols' price history "
        "and rebuild"
    )
