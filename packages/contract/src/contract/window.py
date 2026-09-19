"""The :class:`MarketWindow` — a pre-sliced, point-in-time market view.

A ``MarketWindow`` is the only thing an LLM-authored signal ever sees.  It is
constructed host-side (Z0) from a sealed snapshot, already sliced to the
decision time ``t``, and handed to the sandbox over the payload channel.  The
design intent is a *physical* guarantee rather than a checked one: the window
does not contain data after ``t``, so there is no timestamp a caller could pass
that would return future data (docs/nullius-tech-architecture.md §5.1, PRD §3,
competency question cq-6).

Two properties follow, and this module enforces both at construction time:

* **The decision time is read-only.**  ``t`` is persisted once by the
  constructor and can never be reassigned.  Nothing in the system — not a
  signal, not a sandbox escape, not a later feature module — may move a
  window's decision time forward, because widening the window is precisely
  how look-ahead bias enters a backtest.  A window whose ``t`` could be
  reassigned would make every downstream point-in-time guarantee advisory.
* **The decision time is an unambiguous instant.**  Internally ``t`` is
  always timezone-aware and normalized to UTC.  Naive datetimes are accepted
  (naive in this system means UTC) and converted rather than trusted as-is, so
  no float- or zone-ambiguity can leak into point-in-time comparisons.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Tuple, Union

__all__ = ["MarketWindow"]


def _as_utc(t: Union[datetime, str]) -> datetime:
    """Coerce a decision time to a timezone-aware UTC :class:`datetime`.

    Accepts an aware ``datetime`` in any zone (converted to the equivalent UTC
    instant), a naive ``datetime`` (assumed to be UTC — the convention used
    throughout this system), or an ISO-8601 string (the representation the
    window travels as across the REST and Arrow-IPC boundaries, per
    app_spec.xml's JSON envelope).

    Raises ``TypeError`` for anything that is not a datetime or string, and
    ``ValueError`` for a string that is not a parseable ISO-8601 timestamp.
    Note that a bare ``date`` is deliberately rejected: it names a calendar day,
    not an instant, and a day is ambiguous exactly where it matters most.
    """
    if isinstance(t, str):
        raw = t
        try:
            t = datetime.fromisoformat(t)
        except ValueError as exc:
            raise ValueError(
                f"decision time {raw!r} is not an ISO-8601 timestamp"
            ) from exc
    if not isinstance(t, datetime):
        raise TypeError(
            "decision time t must be a datetime or an ISO-8601 string, "
            f"got {type(t).__name__}"
        )
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        # Naive: interpret as UTC.  Documented convention, not a guess — every
        # stored timestamp in this system is UTC, so a naive value can only
        # have come from a caller meaning UTC.
        return t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def _as_universe(universe: Iterable[str]) -> Tuple[str, ...]:
    """Normalize a symbol collection to a de-duplicated tuple of strings.

    Order is preserved on first appearance, so the tuple a caller passes in is
    the tuple they read back (minus duplicates) — the window never silently
    reorders the universe it was handed.  A tuple, not a list, because the
    window is immutable and a mutable container would hand every caller a way
    to edit the universe after construction.
    """
    if isinstance(universe, str):
        # A bare string is a common typo for a single symbol; iterating it
        # would produce one "symbol" per character, which would look plausible
        # and be silently wrong.  Refuse it instead.
        raise TypeError(
            "universe must be a collection of symbols, not a single string; "
            f"pass ({universe!r},) for one symbol"
        )
    try:
        items = list(universe)
    except TypeError as exc:
        raise TypeError(
            f"universe must be an iterable of symbols, got {type(universe).__name__}"
        ) from exc
    seen: dict[str, None] = {}
    for symbol in items:
        if not isinstance(symbol, str):
            raise TypeError(
                f"universe symbols must be strings, got {type(symbol).__name__}"
            )
        seen.setdefault(symbol, None)
    return tuple(seen)


class MarketWindow:
    """A point-in-time market view, pre-sliced to its decision time ``t``.

    The constructor is the only writer this object will ever have, and it is
    single-shot: :meth:`__init__` refuses to run twice on the same window.  It
    binds the decision time into read-only storage and then closes the door:
    :meth:`__setattr__` and :meth:`__delattr__` raise unconditionally, so
    ``window.t = ...`` fails for every caller, including the factory, the
    sandbox payload channel, and any later accessor added to this class.

    Attributes
    ----------
    t:
        The decision time — the instant the window is sliced at.  Nothing the
        window returns may be later than this.  Read-only.
    universe:
        The symbols tradable as of ``t``, as a tuple.  Read-only.  Membership
        is resolved host-side against the point-in-time universe table before
        construction (docs/nullius-tech-architecture.md §4.3); the window
        stores the result, it does not re-resolve against the wall clock.
    """

    # Slots, deliberately: the read-only guarantee is only as strong as the
    # object's inability to grow new attributes.  With a __dict__ a caller
    # could not rebind `t` (see __setattr__) but could still attach shadow
    # state; slots keep the contract's surface exactly two fields wide.
    __slots__ = ("_t", "_universe", "_initialized")

    def __init__(
        self,
        t: Union[datetime, str],
        universe: Iterable[str] = (),
    ) -> None:
        # The constructor is single-shot.  Re-invoking it on a live window
        # (`window.__init__(later_t)`) would rebind `t` through the one
        # sanctioned writer, so it is refused: "no caller can reassign"
        # includes a caller reaching for the constructor a second time.  The
        # check precedes every bind, so a refused re-initialization leaves
        # the window exactly as it was.  (copy/pickle still work — they
        # rebuild via __reduce__ through this constructor on a *fresh*
        # instance, never by re-initializing a live one.)
        if getattr(self, "_initialized", False):
            raise TypeError(
                f"{type(self).__name__} is already initialized; its decision "
                "time is fixed at construction — build a new window instead "
                "of re-initializing this one"
            )
        # Bind once, through object.__setattr__ to bypass our own guard, which
        # is the single sanctioned write in this object's lifetime.
        object.__setattr__(self, "_t", _as_utc(t))
        object.__setattr__(self, "_universe", _as_universe(universe))
        object.__setattr__(self, "_initialized", True)

    @property
    def t(self) -> datetime:
        """The decision time, as a timezone-aware UTC datetime. Read-only."""
        return self._t

    @property
    def universe(self) -> Tuple[str, ...]:
        """The symbols tradable as of ``t``. Read-only."""
        return self._universe

    def __setattr__(self, key: str, value: object) -> None:
        # The core guarantee of this contract.  A window is immutable after
        # construction: reassigning `t` would silently widen the window and
        # reintroduce look-ahead bias into every result computed from it, and
        # that failure would be invisible in the output.
        #
        # Scope, stated honestly: this closes the attribute protocol —
        # `window.t = x`, `del window.t`, `window._t = x`, and
        # `object.__setattr__(window, "t", x)` (the `t` property has no setter)
        # all raise, and re-invoking `__init__` on a live window is refused
        # too (see there).  `object.__setattr__(window, "_t", x)` does still
        # write through the backing slot, and no pure-Python guard can prevent
        # that: object.__setattr__ is by definition the primitive that skips
        # guards.  The threat this class is built against — untrusted
        # LLM-authored signal code doing `ctx.t = ...` — is fully covered; a
        # caller deliberately reaching for object.__setattr__ on a private
        # slot is not something in-process Python can stop, which is why the
        # sandbox (architecture §5.2) is a separate boundary rather than this
        # one.
        raise AttributeError(
            f"{type(self).__name__} is immutable; cannot set {key!r} "
            "(the decision time is fixed at construction)"
        )

    def __delattr__(self, key: str) -> None:
        raise AttributeError(
            f"{type(self).__name__} is immutable; cannot delete {key!r}"
        )

    def __reduce__(self) -> tuple:
        # The copy/pickle protocol: rebuild through the constructor on a fresh
        # instance — the one sanctioned writer.  Without this, the default
        # __reduce_ex__ would restore slot state with plain setattr, which the
        # immutability guard refuses: a copied window would crash instead of
        # copying.  Rebuilding from (t, universe) also means a restored window
        # carries exactly the state this class validates, and none it doesn't.
        return (type(self), (self._t, self._universe))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MarketWindow):
            return NotImplemented
        return self._t == other._t and self._universe == other._universe

    def __hash__(self) -> int:
        # Safe because the window is immutable: its hash cannot drift while it
        # sits in a set or a dict key.
        return hash((self._t, self._universe))

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"MarketWindow(t={self._t.isoformat()!r}, "
            f"universe={len(self._universe)} symbols)"
        )
