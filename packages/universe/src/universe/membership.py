"""The point-in-time universe membership table, derived from persisted builds.

docs/nullius-tech-architecture.md §4.3 states the contract this module
implements: "Universe membership is stored as a point-in-time table:
``(symbol, valid_from, valid_to, delist_reason)``. Any ``MarketWindow`` at
time ``t`` resolves membership as of ``t``, never as of now."

The monthly builds are the raw material: each one is a fact about who was
tradable for one month, vouched for by the window and config that produced
it. This module turns that series of snapshots into intervals — the form a
decision time can be *resolved* against without walking a history of
monthly tables, and the form an auditor reads to see that a symbol which
left the universe left a row behind rather than silently vanishing from
every later window (the survivorship bias §4.3 is written against). The
resolution itself lives here too (:func:`resolve_membership`, feature 42):
the question "who was tradable at ``t``" has one answer spelled once,
next to the intervals it is answered from.

Derivation rules, stated once so every consumer agrees on them:

*Runs.* A symbol is a member from the first day of the first month it was
admitted to, through the end of the last *consecutive* month it was
admitted to. Consecutive admitted months merge into one interval; a gap —
even a one-month gap — starts a second interval, because "member in May
and July, not June" is a real history and flattening it would be a lie.

*Interval ends are exclusive.* ``valid_from`` is inclusive and ``valid_to``
is the first day *after* the interval — the first day of the month
following the last admitted month, which is also the effective date of the
build that failed to admit the symbol. So membership at time ``t`` holds
when ``valid_from <= t < valid_to``.

*An open interval means the horizon, not the future.* ``valid_to`` is
``NULL`` exactly when the symbol was admitted by the newest persisted
build. No later build exists to close the interval, so claiming the
membership has ended would assert something no build vouches for. An open
interval is therefore the explicit edge of what the store knows, and a
consumer resolving a decision time against it must decide for itself what
to do past that edge.

*Every end carries its reason.* ``delist_reason`` is ``NULL`` only while
the interval is open. Once closed it is one of three canonical sentences,
each a statement about what the persisted builds say — never an inference
about the exchange:

1. the closing month's build *excluded* the symbol by the liquidity floor
   — the persisted floor reason follows a colon, so the row explains
   itself without the build beside it;
2. the closing month's build admitted *other* symbols and not this one —
   "not among the symbols its build admitted", i.e. out-ranked or
   ineligible in that month's trailing window;
3. no build was persisted for the closing month at all — an absence of
   evidence, recorded as such, so an audit can tell a real departure from
   a hole in the build history.

Whether a departure was eventually *an exchange delisting* is settled by
the price history — features 43 and 44 retain delisted symbols and count
them per window — not by guessing here. What this module guarantees is the
part that feature 41 owns: a symbol that left the universe is still
present, with the dates it was tradable and the reason it stopped being
admitted.

Everything here is deterministic: the same builds always yield the same
rows in the same order (``valid_from``, then symbol), so the table can be
re-derived from the builds at any time and compared byte for byte.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Optional

from .bars import coerce_date
from .monthly import MonthlyUniverse, month_key, month_start, next_month_start
from .ordering import canonical_symbol_order

__all__ = [
    "MembershipInterval",
    "membership_intervals",
    "resolve_membership",
]


@dataclass(frozen=True)
class MembershipInterval:
    """One symbol's continuous stretch of universe membership.

    ``valid_from`` is inclusive, ``valid_to`` exclusive (``NULL`` while the
    interval is open at the newest persisted build), and ``delist_reason``
    explains the end of a closed interval — ``NULL`` while it is open. The
    record is frozen: an interval is a statement about a period that has
    already happened, and the way to restate it is to persist a new build
    and re-derive the table, not to edit a row.
    """

    symbol: str
    valid_from: dt.date
    valid_to: Optional[dt.date] = None
    delist_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError(
                "MembershipInterval symbol must be a non-empty, non-blank string"
            )
        # A datetime IS a date subclass; an interval bound names a day.
        if isinstance(self.valid_from, dt.datetime):
            object.__setattr__(self, "valid_from", self.valid_from.date())
        if isinstance(self.valid_to, dt.datetime):
            object.__setattr__(self, "valid_to", self.valid_to.date())
        if not isinstance(self.valid_from, dt.date):
            raise TypeError(
                "MembershipInterval valid_from must be a datetime.date, got "
                f"{type(self.valid_from).__name__}"
            )
        if self.valid_to is None:
            return
        if not isinstance(self.valid_to, dt.date):
            raise TypeError(
                "MembershipInterval valid_to must be None or a datetime.date, got "
                f"{type(self.valid_to).__name__}"
            )
        if self.valid_to <= self.valid_from:
            raise ValueError(
                f"MembershipInterval for {self.symbol} ends at "
                f"{self.valid_to.isoformat()} on or before it starts "
                f"({self.valid_from.isoformat()}); an empty or reversed "
                "interval is a derivation bug, not a membership"
            )

    @property
    def is_open(self) -> bool:
        """True when no persisted build has closed this interval yet."""
        return self.valid_to is None

    def covers(self, when: "str | dt.date | dt.datetime") -> bool:
        """Whether this interval's membership holds at ``when``.

        Inclusive at ``valid_from``, exclusive at ``valid_to``; an open
        interval covers every time at or after ``valid_from``, which is
        exactly the horizon caveat the module docstring names.
        """
        moment = coerce_date(when)
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment < self.valid_to


def membership_intervals(
    universes: Iterable[MonthlyUniverse],
) -> tuple[MembershipInterval, ...]:
    """Derive the point-in-time membership rows from persisted builds.

    ``universes`` is every build the store holds; order does not matter
    (builds are sorted by month here) and a duplicated month keeps the last
    one given. Symbols are walked in symbol order and the result is sorted
    by ``(valid_from, symbol)``, so the same builds always produce the same
    rows in the same order.

    The newest build's months stay open (``valid_to`` of ``NULL``): nothing
    has been observed to close them. Everything earlier is closed on the
    first day of the following month, with the reason the closing month's
    build — or its absence — supplies.
    """
    by_month: dict[str, MonthlyUniverse] = {}
    for universe in universes:
        by_month[universe.month] = universe
    if not by_month:
        return ()
    ordered = [by_month[key] for key in sorted(by_month)]
    newest_month = ordered[-1].month

    # symbol -> the months it was admitted to, in month order. Building the
    # map from every build means a symbol that left is never dropped from
    # the table: its months are simply a run that ends.
    admitted_months: dict[str, list[str]] = {}
    for universe in ordered:
        for member in universe.members:
            admitted_months.setdefault(member.symbol, []).append(universe.month)

    intervals: list[MembershipInterval] = []
    for symbol in sorted(admitted_months):
        months = admitted_months[symbol]
        run_start = previous = months[0]
        for month in months[1:]:
            if _is_the_following_month(previous, month):
                previous = month
                continue
            intervals.append(
                _interval(symbol, run_start, previous, by_month, newest_month)
            )
            run_start = previous = month
        intervals.append(
            _interval(symbol, run_start, previous, by_month, newest_month)
        )
    return tuple(sorted(intervals, key=lambda row: (row.valid_from, row.symbol)))


def _is_the_following_month(previous: str, month: str) -> bool:
    """Whether ``month`` is the calendar month immediately after ``previous``."""
    return month_start(month) == next_month_start(month_start(previous))


def _interval(
    symbol: str,
    first_month: str,
    last_month: str,
    by_month: Mapping[str, MonthlyUniverse],
    newest_month: str,
) -> MembershipInterval:
    """Build the interval covering ``first_month`` through ``last_month``."""
    valid_from = by_month[first_month].effective_from
    if last_month == newest_month:
        # The horizon: the newest build still admits this symbol and no
        # later build exists to say otherwise.
        return MembershipInterval(symbol=symbol, valid_from=valid_from)
    closing_start = next_month_start(month_start(last_month))
    closing_month = month_key(closing_start)
    return MembershipInterval(
        symbol=symbol,
        valid_from=valid_from,
        valid_to=closing_start,
        delist_reason=_end_reason(
            last_month, closing_month, by_month.get(closing_month), symbol
        ),
    )


def _end_reason(
    last_month: str,
    closing_month: str,
    closing_build: Optional[MonthlyUniverse],
    symbol: str,
) -> str:
    """The canonical sentence explaining why a membership interval closed.

    Reads the closing month's build — the first build that did not admit
    the symbol — and states what it says: the floor refused the symbol
    (reusing the reason persisted with that exclusion, verbatim), the build
    admitted symbols and not this one, or no build was persisted at all.
    """
    if closing_build is None:
        return (
            f"membership unobserved after {last_month}: no universe build "
            f"was persisted for {closing_month}"
        )
    for exclusion in closing_build.exclusions:
        if exclusion.symbol == symbol:
            return (
                f"not admitted to the {closing_month} universe: "
                f"{exclusion.reason}"
            )
    return (
        f"not admitted to the {closing_month} universe: not among the "
        "symbols its build admitted"
    )


def resolve_membership(
    intervals: Iterable[MembershipInterval],
    when: "str | dt.date | dt.datetime",
) -> tuple[str, ...]:
    """The symbols tradable as of ``when`` — membership resolved at a decision time.

    This is feature 42's contract, and architecture §4.3's sentence made
    executable: resolution answers *who was tradable then*, never *who is
    tradable now*. A symbol is in the answer exactly when one of
    ``intervals`` covers ``when`` — inclusive at ``valid_from``, exclusive
    at ``valid_to`` — so a name that has since left still answers for a
    decision time inside its interval, and a name that has since joined
    does not answer for a time before its interval opens. ``when`` is the
    only time consulted: nothing here reads a clock, which is the property
    a replay depends on — the same table and the same decision time give
    the same answer today and in a year, whatever the roster has since
    become.

    The decision time is coerced once, up front, so a malformed one is
    refused loudly even against an empty table: a typo quietly returning
    "nothing tradable" would be a wrong answer wearing the shape of a
    right one. The result is the sorted *distinct* symbols — the stable
    ordering feature 46 owns, spelled once in
    :func:`universe.ordering.canonical_symbol_order` and shared with every
    other resolution path — so every consumer, from a ``MarketWindow``'s
    universe tuple to a replay harness, can rely on it without sorting
    again. The derivation never emits two intervals of one
    symbol that overlap, but resolution is defined regardless: a symbol is
    in or out, never in twice.

    Walking the rows here rather than pushing the predicate into SQL is
    deliberate: :meth:`MembershipInterval.covers` is the one statement of
    what an interval means, and the store that reads a table and the
    function that resolves a decision time against it cannot disagree if
    there is only one of it. The open-interval horizon caveat in this
    module's docstring applies verbatim: past the newest build, an open
    interval answers for its symbol because nothing observed has closed
    it — the caller decides what a decision time beyond the evidence
    deserves.
    """
    moment = coerce_date(when)
    return canonical_symbol_order(
        interval.symbol for interval in intervals if interval.covers(moment)
    )
