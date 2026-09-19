"""Point-in-time universe resolution — membership *as of* a decision time.

Feature 13 of app_spec.xml pairs two claims, and they are not the same claim:

1. ``MarketWindow.universe`` is a tuple, and
2. it returns symbols tradable **as of the decision time** rather than as of
   the current wall clock.

The first is a container choice and :mod:`contract.window` already makes it.
The second is the one that matters, and it is not a property a container can
have on its own: a tuple is equally happy to hold today's roster.  What makes
a window point-in-time correct is that its universe was resolved *against the
decision time*, from the persisted membership table, before construction —
docs/nullius-tech-architecture.md §4.3: "Any ``MarketWindow`` at time ``t``
resolves membership as of ``t``, never as of now."

So the resolution lives here, as a pure function over an explicit ``when``.
Two design consequences, both deliberate:

* **There is no default time.**  :func:`resolve_universe` requires its
  decision time as an argument.  A default of ``datetime.now()`` would make
  the wall-clock reading the *convenient* one and the correct one the extra
  typing — and a reviewer could not tell the two call sites apart, because
  they would differ by nothing at all.  Requiring the argument forces every
  caller to name the instant it is resolving for.

* **Resolution is pure and clock-free.**  This module never reads the wall
  clock.  Given the same memberships and the same ``when`` it returns the
  same tuple, on any machine, at any time of day — which is what lets a
  replay reproduce a window's universe exactly (feature 46's stable ordering,
  and the determinism contract generally).

**The layering note.**  This module is stdlib-only and imports nothing from
the ``universe`` member: ``contract`` is Z0, the boundary every other
component sits behind, so depending on a consumer of the contract would
invert the stack.  Membership rows are therefore accepted *structurally* —
anything exposing ``symbol`` plus ``covers(when)``, or a plain
``(symbol, valid_from, valid_to)`` triple — and the unmodified
:class:`universe.membership.MembershipInterval` satisfies both readings
without either package importing the other.  The host, which already holds
both, does the joining.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable, Mapping, Optional, Tuple, Union

__all__ = ["resolve_universe"]


#: Anything a membership row may look like: an interval object (``symbol`` and
#: ``covers``), or a ``(symbol, valid_from, valid_to)`` triple.  ``valid_to``
#: of ``None`` is an open interval — the horizon caveat the universe member's
#: module docstring describes.
MembershipLike = Any


def _as_date(value: Union[dt.date, dt.datetime, str]) -> dt.date:
    """Coerce a membership bound to the calendar date it names.

    Mirrors ``universe.bars.coerce_date`` deliberately, and for the same
    reason: the membership table's bounds are ``DATE`` columns, so a bound
    names a day, not an instant.  A ``datetime`` is a ``date`` subclass and
    would compare unequal to its own date at any time past midnight, which
    would silently drop a symbol on its first listed day; the conversion is
    therefore explicit rather than left to ``<``.
    """
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
        try:
            return dt.datetime.fromisoformat(value).date()
        except ValueError as exc:
            raise ValueError(
                f"membership bound {value!r} is not an ISO date or timestamp"
            ) from exc
    raise TypeError(
        f"membership bound must be a date, datetime or ISO string, got "
        f"{type(value).__name__}"
    )


def _field(row: MembershipLike, name: str) -> Any:
    """Read one field off a membership row, or ``None`` when it has none.

    A row may be an object (the universe member's ``MembershipInterval``) or
    a mapping (a row straight from a driver, before anyone wraps it).  Both
    are asked the same question the same way, so the normalization below does
    not have to branch on which it got — and a mapping is checked *before*
    the sequence path, because unpacking a mapping yields its keys, which
    would silently read ``{"symbol": ...}`` as the three-element row
    ``("symbol", "valid_from", "valid_to")`` and fail bewilderingly.
    """
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _intervals(
    memberships: Iterable[MembershipLike],
) -> list[Tuple[str, dt.date, Optional[dt.date]]]:
    """Normalize membership rows to ``(symbol, valid_from, valid_to)`` triples.

    Three shapes are accepted, because the two packages that meet here
    describe the same row more than one way and neither should have to import
    the other: an interval object or mapping carrying ``symbol``/
    ``valid_from``/``valid_to`` (the universe member's
    ``MembershipInterval``, or a row read straight from the table), or a
    plain triple.  All are normalized to the triple here, so the resolution
    below has exactly one representation to reason about.
    """
    if isinstance(memberships, (str, bytes)):
        raise TypeError(
            "memberships must be a collection of membership rows, not a single "
            f"{type(memberships).__name__}"
        )
    try:
        rows = list(memberships)
    except TypeError as exc:
        raise TypeError(
            "memberships must be an iterable of membership rows, got "
            f"{type(memberships).__name__}"
        ) from exc

    normalized: list[Tuple[str, dt.date, Optional[dt.date]]] = []
    for row in rows:
        symbol = _field(row, "symbol")
        if symbol is None and not _has_fields(row):
            # Not a named row: fall back to positional unpacking.
            try:
                symbol, valid_from, valid_to = row
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    "membership rows must be interval objects (symbol, "
                    "valid_from, valid_to), mappings with those keys, or "
                    f"three-element sequences, got {type(row).__name__}"
                ) from exc
            if not isinstance(symbol, str) or not symbol:
                raise TypeError(
                    f"membership symbol must be a non-empty string, got {symbol!r}"
                )
            normalized.append(
                (
                    symbol,
                    _as_date(valid_from),
                    None if valid_to is None else _as_date(valid_to),
                )
            )
            continue

        if not isinstance(symbol, str) or not symbol:
            raise TypeError(
                f"membership symbol must be a non-empty string, got {symbol!r}"
            )
        valid_from = _field(row, "valid_from")
        if valid_from is None:
            # A membership that starts nowhere covers every instant, which is
            # a silent point-in-time violation rather than a harmless default.
            raise TypeError(
                f"membership row for {symbol!r} has no valid_from; a "
                "membership that starts nowhere covers every instant"
            )
        valid_to = _field(row, "valid_to")
        normalized.append(
            (
                symbol,
                _as_date(valid_from),
                None if valid_to is None else _as_date(valid_to),
            )
        )
    return normalized


def _has_fields(row: MembershipLike) -> bool:
    """Whether ``row`` names its fields rather than carrying them positionally.

    True for a mapping with any of the three keys, or an object declaring any
    of them as an attribute.  Distinguishes "a row whose symbol is missing"
    (a real error worth its own message) from "a positional triple".
    """
    if isinstance(row, Mapping):
        return any(key in row for key in ("symbol", "valid_from", "valid_to"))
    return any(hasattr(row, key) for key in ("symbol", "valid_from", "valid_to"))


def resolve_universe(
    when: Union[dt.date, dt.datetime, str],
    memberships: Iterable[MembershipLike],
) -> Tuple[str, ...]:
    """The symbols tradable as of ``when`` — never as of the wall clock.

    Returns every membership interval covering ``when``, as a de-duplicated,
    sorted tuple.  ``when`` is inclusive at ``valid_from`` and exclusive at
    ``valid_to``, and an open interval (``valid_to is None``) covers every
    date at or after ``valid_from`` — the universe member's own derivation
    rules, restated here so both ends of the join agree on the boundary.

    Sorting is not cosmetic: feature 46 requires a *stable* symbol ordering
    from every resolution so downstream reductions stay bit-reproducible, and
    a window's universe participates in ``__eq__`` and ``__hash__``.  An
    ordering that followed input order would make two windows over the same
    roster compare unequal for no reason a caller could act on.

    The two failures this exists to prevent are opposite halves of the same
    survivorship bug, and both are silent:

    * a symbol **delisted after** ``when`` must still be returned — it was
      tradable then, and dropping it is the pruning that flatters a backtest;
    * a symbol **listed after** ``when`` must *not* be returned — it was not
      tradable then, and returning it is look-ahead.

    Neither test can be written against ``datetime.now()``, which is exactly
    why this function requires ``when`` explicitly.
    """
    moment = _as_date(when)
    symbols: dict[str, None] = {}
    for symbol, valid_from, valid_to in _intervals(memberships):
        if moment < valid_from:
            continue
        if valid_to is not None and moment >= valid_to:
            continue
        symbols.setdefault(symbol, None)
    return tuple(sorted(symbols))
