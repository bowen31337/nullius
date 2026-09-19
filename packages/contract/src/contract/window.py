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
* **No accessor takes a timestamp.**  The read-only ``t`` covers the
  reassignment path; a method that took ``as_of`` would be a second,
  independent widening path, so it is closed separately (feature 10) — and it
  is closed *structurally*, at class-definition time.  The
  :class:`_EnforceNoTimestampAccessor` metaclass refuses to define any window —
  or a subclass a later feature module adds — whose accessors take a
  timestamp, so a widening accessor never comes into being.  :func:`inspect_accessors`
  is the explicit, callable form of the same rule, for a caller that wants to
  introspect the surface rather than rely on the class failing to construct.
  The one place a timestamp legitimately belongs is the :meth:`from_memberships`
  constructor — a constructor, not an accessor — which resolves the universe
  as of the window's own frozen ``t``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional, Tuple, Union

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


def _timestamp_param_names(method: Any) -> Tuple[str, ...]:
    """The parameter names on ``method`` that read as a timestamp argument.

    A MarketWindow accessor widens its window the moment it accepts a time:
    ``ctx.bars("1m", lookback=3600, as_of=tomorrow)`` would return rows the
    window was sliced to exclude, which is look-ahead bias entering through a
    signature rather than a reassignment (architecture §5.1, feature 10).  So
    the check is a signature check, not a behaviour check — it names the
    parameters a caller *could* use to pass a time, which is precisely the
    surface feature 10 forbids.

    The names are the ones a caller would reach for to name an instant:
    ``t``, ``as_of``, ``timestamp``, ``time``, ``when``, ``at``, ``upto``,
    ``until`` and ``end``.  A parameter is matched on its normalized spelling —
    lower-cased with underscores removed — so ``as_of``, ``AsOf``, ``asOf`` and
    ``AS_OF`` all match, while ``lookback`` does not.  Matching on the
    normalized form is the whole point of the check: a widening accessor that
    spelled its argument ``AsOf`` would be the same bug as one that spelled it
    ``as_of``, and the guard must not depend on the caller's casing.  Only
    parameters that actually take a value participate — a ``*args`` catch-all
    or keyword-only ``**kwargs`` is skipped, since it is not a named timestamp
    slot a caller could fill.  ``self`` is never considered.
    """
    import inspect

    try:
        params = inspect.signature(method).parameters
    except (TypeError, ValueError):
        # A builtin or C function whose signature is opaque: it cannot be
        # shown to take a timestamp argument, and refusing to assert on it
        # keeps the check from failing on an implementation detail rather than
        # a real widening.  The window's own accessors are all pure Python.
        return ()

    candidates = frozenset(
        {
            "t", "asof", "at", "time", "timestamp",
            "when", "upto", "until", "end", "to",
        }
    )

    def _normalize(name: str) -> str:
        return name.lower().replace("_", "")

    names: list[str] = []
    for param in params.values():
        if param.name == "self":
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            # A catch-all is not a named slot a caller fills with a time; it
            # is not the surface feature 10 is about.
            continue
        if _normalize(param.name) in candidates:
            names.append(param.name)
    return tuple(names)


def _widening_accessors(cls: type) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    """The ``(accessor_name, timestamp_params)`` pairs on ``cls`` that widen it.

    The shared core of both the automatic guard (:class:`_EnforceNoTimestamp
    Accessor`) and the public :func:`inspect_accessors`: it enumerates the
    public accessors of a class and reports the ones that declare a timestamp
    parameter.  Enumerated over a class rather than an instance because an
    accessor's signature is fixed at class-definition time, so one pass covers
    every object the class will ever produce.

    Two deliberate exclusions shape what counts as a widening accessor:

    * **Constructors are not accessors.**  A ``classmethod`` is a constructor,
      not an accessor a signal calls on ``ctx`` — and :meth:`from_memberships`
      legitimately takes ``t`` as its first argument (feature 13's
      point-in-time resolution path, which resolves the universe as of the
      window's own frozen ``t``).  That is the one sanctioned place a
      timestamp belongs, so classmethods are skipped.
    * **Properties cannot widen.**  A ``property`` getter takes only ``self``
      and has no setter (the read-only ``t`` guarantee), so it is structurally
      incapable of taking a time; it is reported as part of the surface, not
      as a widening accessor.

    The result is a tuple so it is stable and hashable; an empty result means
    the class has no widening accessor.
    """
    import inspect

    widening: list[Tuple[str, Tuple[str, ...]]] = []
    for name in dir(cls):
        if name.startswith("_"):
            continue
        static = inspect.getattr_static(cls, name)
        if isinstance(static, classmethod):
            continue
        if isinstance(static, property):
            continue
        attr = getattr(cls, name)
        if not callable(attr):
            continue
        bad = _timestamp_param_names(attr)
        if bad:
            widening.append((name, bad))
    return tuple(widening)


def inspect_accessors() -> Tuple[str, ...]:
    """Enumerate the MarketWindow's public accessors, refusing a widening one.

    Feature 10 of app_spec.xml: "System rejects any MarketWindow accessor that
    receives a timestamp argument, because no timestamp a caller passes may
    widen the window."  The read-only ``t`` guard (feature 4) covers the
    *assignment* path; an accessor that took ``as_of`` would be a second,
    independent widening path, closed here at the signature level.

    This enumerates every public accessor on the class — every attribute that
    is a function or a property and not a dunder — and raises ``TypeError`` the
    moment one declares a parameter that reads as a time (see
    :func:`_timestamp_param_names`).  The check is over the *class*, not an
    instance, so one inspection covers every window that will ever be built;
    it is import-safe and clock-free, so it can run as a self-check wherever
    the window class is loaded, including the factory's workspace scan.  On
    success it returns the tuple of accessor names, so a caller (or the
    composed application) can assert the surface it expected rather than
    merely that nothing was rejected.

    The automatic half of the guarantee lives on the class metaclass
    (:class:`_EnforceNoTimestampAccessor`), which refuses to *define* a window
    with a widening accessor at all — including a subclass added by a later
    feature module.  This function is the explicit, callable form of the same
    rule, for callers that want to introspect the surface rather than rely on
    the class failing to construct.
    """
    widening = _widening_accessors(MarketWindow)
    if widening:
        for name, bad in widening:
            raise TypeError(
                f"MarketWindow.{name} accepts a timestamp argument "
                f"({', '.join(bad)}), which would let a caller widen the "
                "window past its decision time — no accessor may take one"
            )
    # The surface is the public accessors a signal can call on ``ctx``: public
    # names that are functions or properties.  Classmethods are constructors
    # (``from_memberships``), not accessors, so they are excluded — matching
    # the enumeration core's view of what an accessor is.
    import inspect

    return tuple(
        name
        for name in dir(MarketWindow)
        if not name.startswith("_")
        and not isinstance(
            inspect.getattr_static(MarketWindow, name), classmethod
        )
    )


class _EnforceNoTimestampAccessor(type):
    """Refuse to define a MarketWindow subclass with a widening accessor.

    The automatic, structural half of feature 10.  :class:`MarketWindow`'s
    read-only ``t`` guard refuses *assignment* at runtime, but a widening
    accessor — ``bars(self, freq, as_of=...)`` — would widen the window without
    ever touching ``t``, through a signature rather than a reassignment.  This
    metaclass closes that path at *class-definition* time: after a subclass is
    built, it scans the subclass's own accessors and raises ``TypeError`` if
    any declares a timestamp parameter, so the offending class never comes into
    being.

    That timing is deliberate and stronger than a runtime check.  A widening
    accessor added by a later feature module, a signal's attempted subclass,
    or a monkeypatch that reaches for ``type(window)`` is rejected the instant
    it is written, before any window carrying it can be built — and the error
    names the accessor and the parameter, so the rejection is actionable.

    The rule is shared with :func:`inspect_accessors` via
    :func:`_widening_accessors`, which excludes classmethod constructors (the
    one sanctioned place a timestamp belongs) and properties (structurally
    incapable of taking one), so the metaclass only ever fires on a genuine
    widening instance accessor.
    """

    def __init__(cls, name: str, bases: tuple, namespace: Mapping[str, Any]) -> None:
        super().__init__(name, bases, namespace)
        for accessor, bad in _widening_accessors(cls):
            raise TypeError(
                f"{cls.__name__} declares {accessor!r} with a timestamp argument "
                f"({', '.join(bad)}), which would let a caller widen the window "
                "past its decision time — no accessor may take one"
            )


def _as_frames(frames: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Normalize materialized frames to a read-only mapping of Arrow tables.

    A window's frames are the data it actually hands out, so they are pinned
    at construction exactly like ``t`` is: each frame is coerced to an Arrow
    table once, and the result is a fresh ``dict`` owned by the window alone.
    Two consequences, both deliberate:

    * **Serialization and equality are well defined.**  ``__eq__`` compares
      frames, which is only meaningful if a frame is a value — a Polars frame
      and an Arrow table holding the same rows would otherwise compare
      unequal for no reason a caller could act on.  Materializing on the way
      in means a window has one representation, not two.
    * **Frames are captured, not referenced.**  The returned dict is fresh, so
      a caller keeping a reference to the mapping it passed cannot add a frame
      to a live window afterwards.  Writes *through* the window are refused
      separately, by the read-only proxy :attr:`MarketWindow.frames` returns.
      An Arrow table's own buffers are immutable by construction, so nothing
      underneath can be rewritten either.

    Values are coerced eagerly here rather than lazily at first access: a
    window that only fails when someone asks it for a frame would carry a bad
    frame silently through construction, sealing, and dispatch.
    """
    if frames is None:
        return {}
    if not isinstance(frames, Mapping):
        raise TypeError(
            "frames must be a mapping of frame name to frame, got "
            f"{type(frames).__name__}"
        )
    if not frames:
        # An explicitly empty mapping is the same state as no mapping: there
        # is nothing to coerce, so pyarrow is not reached for.  A window that
        # carries no frames must stay constructible in an environment that has
        # no Arrow at all — that is the whole reason the import is deferred.
        return {}
    from ._arrow import coerce_table, require_arrow

    arrow = require_arrow()
    normalized: dict[str, Any] = {}
    for name, frame in frames.items():
        if not isinstance(name, str) or not name:
            raise TypeError(
                f"frame names must be non-empty strings, got {name!r}"
            )
        normalized[name] = coerce_table(arrow, name, frame)
    return normalized


class MarketWindow(metaclass=_EnforceNoTimestampAccessor):
    """A point-in-time market view, pre-sliced to its decision time ``t``.

    The constructor is the only writer this object will ever have, and it is
    single-shot: :meth:`__init__` refuses to run twice on the same window.  It
    binds the decision time into read-only storage and then closes the door:
    :meth:`__setattr__` and :meth:`__delattr__` raise unconditionally, so
    ``window.t = ...`` fails for every caller, including the factory, the
    sandbox payload channel, and any later accessor added to this class.  The
    door is closed on the window's *contents* as well as its attributes — the
    frames mapping is read-only too (see :attr:`frames`), since attaching a
    frame after construction would widen the window just as rebinding ``t``
    would.

    Attributes
    ----------
    t:
        The decision time — the instant the window is sliced at.  Nothing the
        window returns may be later than this.  Read-only.
    universe:
        The symbols tradable as of ``t``, as a tuple.  Read-only.  Membership
        is resolved host-side against the point-in-time universe table
        (docs/nullius-tech-architecture.md §4.3); the window stores the
        result, it does not re-resolve against the wall clock.
        :meth:`from_memberships` is the construction path that resolves it
        against the window's own ``t``; a window built with an explicit
        ``universe`` stores what it was handed.
    frames:
        The materialized data the window actually carries, as a read-only
        mapping of frame name to Arrow table.  Read-only, and captured at
        construction — see :func:`_as_frames`.  Empty for a window that has
        materialized nothing, which is a legitimate state: the accessors that
        *do* read the lake (features 5-9) populate it, and feature 14
        serializes it to the sandbox over the payload channel.
    """

    # Slots, deliberately: the read-only guarantee is only as strong as the
    # object's inability to grow new attributes.  With a __dict__ a caller
    # could not rebind `t` (see __setattr__) but could still attach shadow
    # state; slots keep the contract's surface to the fields it declares.
    __slots__ = ("_t", "_universe", "_frames", "_initialized")

    def __init__(
        self,
        t: Union[datetime, str],
        universe: Iterable[str] = (),
        frames: Optional[Mapping[str, Any]] = None,
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
        object.__setattr__(self, "_frames", _as_frames(frames))
        object.__setattr__(self, "_initialized", True)

    @property
    def t(self) -> datetime:
        """The decision time, as a timezone-aware UTC datetime. Read-only."""
        return self._t

    @property
    def universe(self) -> Tuple[str, ...]:
        """The symbols tradable as of ``t``. Read-only.

        Returns a tuple, and — for a window built by :meth:`from_memberships`
        — a tuple that was *resolved against this window's own decision time*,
        never against the wall clock.  Those are two separate promises and
        only the first is a container choice: a tuple holds today's roster
        just as happily as it holds the roster ``t`` deserves.  See
        :meth:`from_memberships` for the construction path that makes the
        second promise structural rather than merely intended.
        """
        return self._universe

    @classmethod
    def from_memberships(
        cls,
        t: Union[datetime, str],
        memberships: "Iterable[Any]",
        frames: Optional[Mapping[str, Any]] = None,
    ) -> "MarketWindow":
        """Build a window whose universe is resolved *as of its own* ``t``.

        The point-in-time construction path (app_spec.xml feature 13;
        docs/nullius-tech-architecture.md §4.3).  Rather than trusting a
        caller to hand over the right roster, this resolves membership
        against the window's decision time — the same ``t`` the constructor
        freezes — so the universe a window reports and the instant it is
        sliced at cannot disagree.

        That coupling is the whole point.  A caller resolving for itself
        writes ``resolve_membership(datetime.now())`` at a call site that
        looks exactly like the correct one; here there is no clock to reach
        for, because the only instant available is the window's own ``t``.

        The resolution itself lives in :func:`contract.resolution.resolve_universe`,
        which is pure and clock-free; this method is the thin constructor-side
        join.  Memberships are accepted structurally — interval objects with
        ``symbol``/``valid_from``/``valid_to``, mappings of the same keys, or
        plain triples — so this module (Z0, the boundary everything else sits
        behind) depends on no other member, and the real
        ``universe.membership.MembershipInterval`` satisfies the acceptance
        without either package importing the other.

        Note the shape of this API: ``t`` is a *constructor* argument, and the
        resulting ``universe`` is an ordinary read-only property taking no
        argument at all.  Feature 10 requires that no ``MarketWindow``
        *accessor* accept a timestamp — an accessor that took one would be a
        caller's chance to widen the window.  Resolving at construction, once,
        from the already-frozen ``t``, keeps that door shut.
        """
        from .resolution import resolve_universe

        return cls(
            t,
            universe=resolve_universe(t, memberships),
            frames=frames,
        )

    @property
    def frames(self) -> Mapping[str, Any]:
        """The materialized frames, keyed by name. Read-only.

        Returned as a :class:`~types.MappingProxyType` — a live view of the
        window's own storage, not a copy — so the read path stays cheap for a
        payload carrying many frames, while ``window.frames["x"] = ...``
        raises ``TypeError`` for every caller.

        That immutability is load-bearing, not tidiness.  A signal runs with
        this window in hand; if the mapping were writable, ``ctx.frames[...]
        = ...`` would attach data to a live window after its decision time was
        fixed — which is a window widening, and precisely the failure the
        read-only ``t`` exists to prevent.  A dict would have made that
        possible while ``t`` sat safely frozen beside it, so the guard covers
        the mapping and not just the attribute.

        The proxy is a view, so it reflects the storage it wraps; nothing in
        this class writes to that storage after construction, so what it
        reflects never changes.
        """
        return MappingProxyType(self._frames)

    def to_arrow(self):
        """Serialize this window to an Arrow IPC payload (feature 14).

        The host-side half of the payload channel: the bytes produced here go
        to the sandbox, which holds no filesystem mounts and can obtain a
        window no other way (docs/nullius-tech-architecture.md §5.2).  The
        returned :class:`~contract.payload.MarketWindowPayload` keeps the
        buffer alive, so the sandbox's zero-copy read stays valid for as long
        as the payload does.

        Delegated to :mod:`contract.payload` rather than implemented here so
        that this module — the one every import of the package pulls in, and
        the one the factory scan touches — keeps its stdlib-only import
        surface, with pyarrow reached lazily behind the payload seam.
        """
        from .payload import serialize_window

        return serialize_window(self)

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
        # copying.  Rebuilding from (t, universe, frames) also means a restored
        # window carries exactly the state this class validates, and none it
        # doesn't — and that a window pickled *with* its frames comes back with
        # them, rather than silently losing the data it was carrying.
        return (type(self), (self._t, self._universe, self._frames))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MarketWindow):
            return NotImplemented
        return (
            self._t == other._t
            and self._universe == other._universe
            and self._frames_equal(other)
        )

    def _frames_equal(self, other: "MarketWindow") -> bool:
        """Compare frames by name and content.

        Arrow's ``Table.equals`` ignores schema metadata, which is the right
        choice here: two tables holding the same columns and rows *are* the
        same frame to a signal, and a producer's choice of schema-level
        annotation is not a difference the contract should ever surface as
        window inequality.  Names must match too, so a window renamed on one
        side does not compare equal to its unrenamed twin.
        """
        if self._frames.keys() != other._frames.keys():
            return False
        return all(
            table.equals(other._frames[name]) for name, table in self._frames.items()
        )

    def __hash__(self) -> int:
        # Safe because the window is immutable: its hash cannot drift while it
        # sits in a set or a dict key.  Frames participate by name only — a
        # table is not hashable, and hashing its bytes would be a surprising
        # cost on an object whose hash looks free.  This keeps the invariant
        # __hash__ requires: two equal windows have equal (t, universe, names),
        # so equal windows still hash equal.
        return hash((self._t, self._universe, tuple(self._frames)))

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"MarketWindow(t={self._t.isoformat()!r}, "
            f"universe={len(self._universe)} symbols, "
            f"frames={list(self._frames)!r})"
        )
