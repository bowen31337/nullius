"""The evaluation window, resolved host-side (§6.1 step 1; feature 72).

app_spec.xml feature 72: *"System resolves the evaluation window host-side
by slicing a sealed snapshot to the decision time, which returns a
point-in-time universe."*  docs/nullius-tech-architecture.md §6.1 names the
step — ``1. resolve_window (host)  slice snapshot to t, resolve PIT
universe`` — and §5.2 shows where its result goes:

    window = materialize_window(snapshot, t, lookback=L, universe=U)  # HOST side, Z0

Three claims sit in that one sentence, and this module is each of them:

* **Host-side.**  The resolution runs in the host (Z0), before any sandbox
  exists, because principle P4 makes look-ahead *physically impossible*
  rather than forbidden: "The signal sandbox never mounts the data lake.  It
  receives a pre-sliced, materialized array containing only data at or
  before ``t``."  The physical absence starts here — the resolution this
  module returns names only partitions dated at or before ``t``, so there
  is nothing after ``t`` for a downstream step to read by mistake.  The
  record itself carries no path, no file handle and no mount: what crosses
  toward the sandbox is pure data (a name, an instant, a roster, the
  surviving dates), so the sealed tree it came from stays host-side with
  the process that sliced it.
* **A sealed snapshot.**  §4.2 is explicit — "**The evaluator can only open
  sealed snapshots.**  Staging is not on its mount path at all." — so the
  input here is a *mount*, the read-only handle the snapshot member's
  ``SnapshotService.mount(name)`` returns after feature 36's open-time
  verification has already recomputed every recorded sha256.  This module
  never touches a lake, a staging area or a raw path; a caller who hands it
  one is refused with the remedy spelled (see :func:`_mount_queries`).
* **A point-in-time universe.**  §4.3: "Any ``MarketWindow`` at time ``t``
  resolves membership as of ``t``, never as of now."  The roster the slice
  returns is derived from what the *sealed content* says about ``t`` — see
  :data:`ROSTER_STREAM` for the rule — so the same sealed snapshot resolves
  the same universe on any machine, any day, which is the property the
  determinism contract (§12) and feature 46's stable symbol ordering lean
  on.  No wall clock is read anywhere in this module.

**The universe rule, stated once.**  At the partition granularity the §4.2
layout offers, a symbol is tradable as of ``t`` when the sealed bars carry
a partition on **the decision date itself** — the UTC calendar date of
``t``.  Membership is day-granular (the universe member's table bounds are
``DATE`` columns; a bound names a day, not an instant), so "current as of
``t``" at day granularity is exactly "carries data that day": a symbol
delisted *after* ``t`` still has the day's candles and is returned (the
survivorship half of §4.3 — dropping it is the pruning that flatters a
backtest), while a symbol delisted *before* ``t`` has none and is not (its
history still survives the slice, because the slice is an upper bound, not
a recent-context window), and a symbol *listed* after ``t`` cannot appear
at all.  The rule deliberately has no recency parameter: "live if its
latest partition is within k days of ``t``" would make the universe a
function of a knob the spec never names, and a live symbol whose ingest
missed one day is *dropped* — honest against the sealed content, which is
the authority here, where a tolerance would silently guess.

**What the slice keeps.**  For every symbol-partitioned stream §4.2's
layout names, every partition whose date is at or before the decision
date.  The decision date's own partition stays: its rows are within-day,
and the contract's accessors truncate rows at ``t`` on every call (features
5 and 6 put that in their own sentences), so row-level absence is enforced
at the boundary that actually reads rows.  Every *earlier* date stays too —
a delisted symbol's full history is context, which is precisely why §4.3
seals delisted symbols with their history rather than pruning them.

**The coverage refusal.**  A decision date outside the sealed bars range —
before the first partition, or after the last — is refused, in both
directions and for different reasons.  Before the first, the seal cannot
speak for the date at all and any roster would be fabrication.  After the
last, the world has moved past the seal: §4.3 leaves "past the edge" to
the consumer ("an open interval is the explicit edge of what the store
knows, and a consumer resolving a decision time against it must decide for
itself what to do past that edge"), and this consumer's decision is to
refuse — a window over data that stops before its decision time is a
window the evaluation cannot honestly score.  A date *inside* the range
that no symbol happens to have bars on (a whole-market ingest gap) is not
refused: it resolves to an empty universe, the honest reading of content
that is present but silent, distinguishable in the error's absence from a
date the snapshot never covered.

**The layering note.**  This module is stdlib-only and imports nothing
from any member — the same discipline :mod:`contract.resolution` states
for its membership rows, and for the same reason: the members describe the
same facts more than one way and none should have to import another.  The
mount is therefore accepted *structurally*: any object exposing ``name``,
``partitions(stream)`` and ``dates(stream, symbol)`` (the real
``snapshot.SnapshotMount`` does) is a sealed snapshot to this module, and
the host — the orchestrator that already holds the mount — does the
joining.  Nothing here is resolved from the environment either: window
resolution demands neither of the identity's terms (the image, the store),
because the window is what a score is computed *over* while the identity
is what it is stamped *with*, and a resolution that needed a configured
image would break the laziness composition depends on (see ``_service``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Optional, Tuple, Union

from ._errors import EvaluatorWindowError

__all__ = [
    "ROSTER_STREAM",
    "SLICED_STREAMS",
    "WindowResolution",
    "resolve_window",
]

#: The stream the point-in-time universe is resolved from (§4.3).
#:
#: Bars are the roster stream by construction: the universe is top-N by
#: trailing dollar volume over candles, so every symbol the universe member
#: ever admits has bars, while trades/bookfeat/borrow may legitimately be
#: sparser for a small or newly-listed symbol.  Resolving the roster from
#: any other stream would let a data gap in that stream read as a
#: delisting, which is the flattering direction of the survivorship bug.
ROSTER_STREAM = "bars"

#: The symbol-partitioned streams a resolution slices (§4.2's layout).
#:
#: Fixed because §4.2's directory layout is fixed: each of these lives at
#: ``<stream>/symbol=<SYM>/date=<ISO>/part-*.parquet``.  ``exchangeinfo``
#: is deliberately absent — it is versioned daily, not partitioned by
#: symbol, so there is no ``symbol=`` layer for a symbol slice to act on;
#: it becomes the host's concern at materialization (feature 73's step),
#: not the resolution's.
SLICED_STREAMS: Tuple[str, ...] = ("bars", "trades", "bookfeat", "borrow")


# -- The decision time -------------------------------------------------------


def _as_utc(t: Union[dt.datetime, str]) -> dt.datetime:
    """Coerce a decision time to a timezone-aware UTC :class:`datetime`.

    The convention this system shares with the contract member's window
    (``contract.window._as_utc``), spelled here rather than imported:
    aware datetimes convert to UTC, naive ones are *interpreted* as UTC
    (every stored timestamp in this system is UTC, so a naive value can
    only have come from a caller meaning UTC), and ISO-8601 strings parse.
    A bare ``date`` is refused — it names a calendar day, not an instant,
    and a day is ambiguous exactly where a decision time matters most:
    accepting one would silently mean "midnight UTC", a different decision
    time than the caller wrote down.
    """
    if isinstance(t, str):
        raw = t
        try:
            t = dt.datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(
                f"decision time {raw!r} is not an ISO-8601 timestamp"
            ) from exc
    if isinstance(t, dt.date) and not isinstance(t, dt.datetime):
        raise TypeError(
            "decision time t must be a datetime or an ISO-8601 timestamp, "
            f"got date {t.isoformat()!r} — a date names a day, not an instant"
        )
    if not isinstance(t, dt.datetime):
        raise TypeError(
            "decision time t must be a datetime or an ISO-8601 string, "
            f"got {type(t).__name__}"
        )
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        return t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


# -- The sealed mount, accepted structurally ---------------------------------


def _mount_queries(snapshot: Any) -> Tuple[str, Any, Any]:
    """The ``(name, partitions, dates)`` query surface of a sealed mount.

    The structural seam: this module's entire view of "a sealed snapshot"
    is the read-only mount's own partition queries — ``name`` (the
    canonical ``<sealed_at>_<hash prefix>`` spelling), ``partitions(stream)``
    (the ``symbol=…`` keys present) and ``dates(stream, symbol)`` (the
    ``date=…`` keys for one symbol).  The real
    :class:`snapshot.SnapshotMount` satisfies all three; nothing else is
    reached for, so no member is imported and no path is ever touched.

    Anything missing is refused with the remedy rather than an
    ``AttributeError`` a caller would have to decode: a raw path (the
    tempting hand-off — "just point at the directory") is exactly what §4.2
    forbids, since a path carries no sealedness at all, staging included.
    """
    # ``partitions`` and ``dates`` are the mount's query methods — callable,
    # and refused by name when absent.  ``name`` is a *property* on the real
    # :class:`snapshot.SnapshotMount` (the canonical spelling, not a method),
    # so it is checked as a value in the next block, not here: a callable
    # test would refuse the genuine mount this module exists to accept.
    for attribute in ("partitions", "dates"):
        if not callable(getattr(snapshot, attribute, None)):
            raise EvaluatorWindowError(
                f"{snapshot!r} is not a sealed snapshot mount: no "
                f"{attribute} — the evaluator opens sealed snapshots "
                "through a mount, never a path (docs §4.2); pass what "
                "snapshot.SnapshotService.mount(name) returns"
            )
    name = snapshot.name
    if not isinstance(name, str) or not name.strip():
        raise EvaluatorWindowError(
            "a sealed snapshot mount must carry a canonical non-empty "
            f"name, got {name!r}"
        )
    return name, snapshot.partitions, snapshot.dates


def _symbols(partitions: Any, stream: str) -> Tuple[str, ...]:
    """The sorted, de-duplicated symbols one stream's partitions name.

    The mount already returns them sorted (directory names); sorted again
    here anyway, because the resolution's determinism is a promise about
    the *layout*, not about whichever handle happened to enumerate it — a
    handle that changed iteration order between two calls would otherwise
    produce two different resolutions of one snapshot.
    """
    try:
        named = list(partitions(stream))
    except TypeError as exc:
        raise EvaluatorWindowError(
            f"the mount's partitions({stream!r}) is not callable with a "
            f"stream name: {exc}"
        ) from exc
    seen: dict[str, None] = {}
    for symbol in named:
        if not isinstance(symbol, str) or not symbol:
            raise EvaluatorWindowError(
                f"partition symbols under {stream!r} must be non-empty "
                f"strings, got {symbol!r}"
            )
        seen.setdefault(symbol, None)
    return tuple(sorted(seen))


def _dates(dates: Any, stream: str, symbol: str) -> Tuple[dt.date, ...]:
    """One symbol's partition dates, validated as ISO and sorted.

    The §4.2 layout promises ``date=<ISO>`` directory names, so a value
    that does not parse is refused by name rather than compared
    lexicographically on trust: a layout that drifted to ``2026-9-1`` would
    sort *before* ``2026-08-31`` as a string and after it as a date, and
    the difference is exactly a slice boundary.  (``date.fromisoformat``
    accepts the compact ``20260901`` spelling too; both name the same day
    and both are honored, because they are honest ISO dates — only a value
    that names *no* day is refused.)
    """
    try:
        values = list(dates(stream, symbol))
    except TypeError as exc:
        raise EvaluatorWindowError(
            f"the mount's dates({stream!r}, {symbol!r}) is not callable "
            f"with a stream and symbol: {exc}"
        ) from exc
    parsed: list[dt.date] = []
    for value in values:
        if not isinstance(value, str):
            raise EvaluatorWindowError(
                f"partition dates for {symbol!r} under {stream!r} must be "
                f"ISO strings, got {value!r}"
            )
        try:
            parsed.append(dt.date.fromisoformat(value))
        except ValueError as exc:
            raise EvaluatorWindowError(
                f"partition date {value!r} for {symbol!r} under {stream!r} "
                "is not an ISO date; the sealed layout docs §4.2 promises "
                "date=<ISO> partitions, and a slice over an unreadable "
                "date is a guess"
            ) from exc
    return tuple(sorted(set(parsed)))


def _stream_layout(
    partitions: Any, dates: Any, stream: str
) -> dict[str, Tuple[dt.date, ...]]:
    """One stream's full layout as ``{symbol: (dates,)}``, symbols sorted.

    A symbol with no date partitions under a stream it is named by carries
    nothing for the slice to keep or drop, so it contributes no key — the
    same rule the slice itself applies to a symbol whose every date falls
    after ``t``: presence in the resolution means *data the window may
    serve*, not a directory the walk happened to list.
    """
    layout: dict[str, Tuple[dt.date, ...]] = {}
    for symbol in _symbols(partitions, stream):
        days = _dates(dates, stream, symbol)
        if days:
            layout[symbol] = days
    return layout


# -- The resolution ----------------------------------------------------------


@dataclass(frozen=True)
class WindowResolution:
    """A sealed snapshot sliced to one decision time — pure data.

    What step 1 of §6.1's pipeline hands to every later step: the instant,
    the point-in-time universe resolved against it, and the per-stream
    partitions at or before it.  Deliberately holds no path, no file
    handle and no mount — the sealed tree stays behind the host boundary
    with the process that sliced it, and what crosses toward the sandbox
    (feature 73 materializes frames from this record, ``lookback`` rows at
    a time) is a value: nameable, comparable, and reproducible from the
    same sealed snapshot on any machine at any time.

    The invariants a resolution promises are checked at construction, so a
    record built by hand — or by a later feature whose producer drifted —
    fails loudly rather than carrying a lying window: ``t`` is normalized
    to UTC, the universe is sorted and free of duplicates, every sliced
    date is ISO and at or before ``t``'s date, and the mappings are
    captured behind read-only proxies rather than referenced (a caller
    keeping the dict it passed cannot add a partition to a live
    resolution).
    """

    #: The canonical name of the sealed snapshot this window was sliced
    #: from (``<sealed_at>_<hash prefix>``).  The mount it names stays
    #: host-side; the name travels because a score's provenance must be
    #: able to say *which* sealed world its window came from.
    snapshot_name: str

    #: The decision time, normalized to timezone-aware UTC.  Nothing the
    #: resolution carries may be later than this instant's calendar date.
    t: dt.datetime

    #: The symbols tradable as of ``t`` — resolved from the sealed bars
    #: (see :data:`ROSTER_STREAM`), sorted (feature 46's stable ordering),
    #: never from the wall clock.
    universe: Tuple[str, ...]

    #: The surviving partitions, per symbol-partitioned stream, as
    #: ``{stream: {symbol: (ISO dates at or before t, …)}}`` — streams the
    #: snapshot does not carry and symbols with no surviving date are
    #: absent.  Dates are the partition spellings the mount's own
    #: ``select`` consumes, sorted ascending.
    slices: Mapping[str, Mapping[str, Tuple[str, ...]]]

    def __post_init__(self) -> None:
        # Every bind below goes through object.__setattr__: the dataclass is
        # frozen, and these are normalizations of arguments the constructor
        # already accepted, not rewrites of a settled record.
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorWindowError(
                "a window resolution must name its sealed snapshot, got "
                f"{self.snapshot_name!r}"
            )
        moment = _as_utc(self.t)
        if moment.tzinfo is None:  # pragma: no cover - _as_utc guarantees it
            raise EvaluatorWindowError("decision time must be timezone-aware")
        object.__setattr__(self, "t", moment)
        if not isinstance(self.universe, tuple):
            raise EvaluatorWindowError(
                "the universe must be a tuple of symbols, got "
                f"{type(self.universe).__name__}"
            )
        for symbol in self.universe:
            if not isinstance(symbol, str) or not symbol:
                raise EvaluatorWindowError(
                    f"universe symbols must be non-empty strings, got {symbol!r}"
                )
        if list(self.universe) != sorted(set(self.universe)):
            # Refused rather than quietly re-sorted: sortedness is the
            # derivation's invariant (feature 46), and a producer that
            # emitted an unsorted or duplicated roster is a bug this should
            # surface, not absorb.
            raise EvaluatorWindowError(
                "the universe must arrive sorted and de-duplicated; the "
                "resolution that produced it is the one that drifted"
            )
        if not isinstance(self.slices, Mapping):
            raise EvaluatorWindowError(
                "slices must be a mapping of stream to symbol to dates, got "
                f"{type(self.slices).__name__}"
            )
        captured: dict[str, Mapping[str, Tuple[str, ...]]] = {}
        for stream, per_symbol in self.slices.items():
            if not isinstance(stream, str) or not stream:
                raise EvaluatorWindowError(
                    f"slice stream names must be non-empty strings, got {stream!r}"
                )
            if not isinstance(per_symbol, Mapping):
                raise EvaluatorWindowError(
                    f"slices under {stream!r} must map symbol to dates, got "
                    f"{type(per_symbol).__name__}"
                )
            inner: dict[str, Tuple[str, ...]] = {}
            for symbol, dates in per_symbol.items():
                if not isinstance(symbol, str) or not symbol:
                    raise EvaluatorWindowError(
                        f"slice symbols under {stream!r} must be non-empty "
                        f"strings, got {symbol!r}"
                    )
                if not isinstance(dates, tuple):
                    raise EvaluatorWindowError(
                        f"slice dates for {symbol!r} under {stream!r} must "
                        f"be tuples, got {type(dates).__name__}"
                    )
                parsed: list[dt.date] = []
                for value in dates:
                    try:
                        parsed.append(dt.date.fromisoformat(value))
                    except (TypeError, ValueError) as exc:
                        raise EvaluatorWindowError(
                            f"slice date {value!r} for {symbol!r} under "
                            f"{stream!r} is not an ISO date"
                        ) from exc
                if parsed != sorted(parsed):
                    raise EvaluatorWindowError(
                        f"slice dates for {symbol!r} under {stream!r} must "
                        "arrive sorted; the producer that emitted them drifted"
                    )
                if parsed and parsed[-1] > moment.date():
                    # The one invariant the feature exists for, checked on
                    # the record itself: a date after the decision time is
                    # future data, and P4's guarantee is that it is
                    # physically absent — a record carrying it is not a
                    # narrower window, it is a broken one.
                    raise EvaluatorWindowError(
                        f"slice for {symbol!r} under {stream!r} carries "
                        f"{parsed[-1].isoformat()}, after the decision time "
                        f"{moment.isoformat()} — a window may carry no "
                        "partition dated after its decision time"
                    )
                if dates:
                    inner[symbol] = tuple(dates)
            if inner:
                captured[stream] = MappingProxyType(inner)
        object.__setattr__(self, "slices", MappingProxyType(captured))

    @property
    def decision_date(self) -> dt.date:
        """The UTC calendar date of :attr:`t` — the slice boundary.

        The date the universe was resolved for and every sliced partition
        is dated at or before.  Exposed because the two spellings of the
        boundary (the instant and the day) mean different things to
        different steps: the sandbox's row-level truncation compares
        against ``t``, while the partition-level slice — this record —
        compares against the day.
        """
        return self.t.date()

    def dates(self, stream: str, symbol: str) -> Tuple[str, ...]:
        """One symbol's surviving partition dates under one stream.

        The accessor feature 73's materialization reads: which ``date=``
        partitions of which symbol the window may serve.  Empty for a
        stream the snapshot did not carry or a symbol with nothing at or
        before ``t`` — the miss reported as nothing, on the same principle
        as the contract's accessors: an empty answer cannot leak a
        partition the slice excluded, where a nearest-match fallback
        silently would.
        """
        return self.slices.get(stream, {}).get(symbol, ())

    def __hash__(self) -> int:
        # Hashable because the record is a value: two resolutions of the
        # same sealed snapshot at the same instant must be interchangeable
        # as dict keys (a cache of resolved windows, a replay comparing a
        # stored resolution against a fresh one).  The generated frozen-
        # dataclass hash cannot serve here — the slice mappings are not
        # hashable — so the mapping is folded into nested tuples, which
        # also keeps __hash__ consistent with __eq__.
        return hash(
            (
                self.snapshot_name,
                self.t,
                self.universe,
                tuple(
                    (
                        stream,
                        tuple(per_symbol.items()),
                    )
                    for stream, per_symbol in sorted(self.slices.items())
                ),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"WindowResolution(snapshot={self.snapshot_name!r}, "
            f"t={self.t.isoformat()}, universe={len(self.universe)} symbols, "
            f"streams={list(self.slices)!r})"
        )


def resolve_window(
    snapshot: Any,
    t: Union[dt.datetime, str],
) -> WindowResolution:
    """Slice a sealed snapshot to ``t`` and resolve its point-in-time universe.

    Step 1 of §6.1's pipeline, on the host: the sealed mount ``snapshot``
    (anything exposing the structural surface of
    ``snapshot.SnapshotService.mount(name)``'s result — see
    :func:`_mount_queries`) is sliced to the decision time ``t`` and the
    resolution returned — the universe as of ``t``, and per stream the
    partitions at or before ``t``'s UTC date.  Reads no clock, performs no
    I/O of its own (the mount's partition queries are directory listings),
    and demands neither of the identity's terms, so the composed service
    resolves windows in an environment with no pinned image and no
    database configured.

    The universe is resolved from the sealed **bars** (see
    :data:`ROSTER_STREAM`): the symbols whose bars carry a partition on
    ``t``'s date, sorted.  The slice keeps every partition dated at or
    before that date, across all four symbol-partitioned streams, so a
    delisted symbol's history rides along beneath a roster it no longer
    belongs to — history is context; membership is the cross-section.

    Refused, each with its reason (see ``_errors`` for the taxonomy): an
    object that is not a mount (a path, a service, a name — §4.2 lets the
    evaluator open sealed snapshots only), a decision time that is not an
    instant (a bare date), a snapshot with no bars partitions to resolve a
    roster from, and a decision date outside the sealed bars coverage —
    before it the seal cannot speak for the date, after it the world has
    moved past the seal, and §4.3 leaves that edge to this consumer to
    refuse.
    """
    name, partitions, dates = _mount_queries(snapshot)
    moment = _as_utc(t)
    decision = moment.date()

    roster = _stream_layout(partitions, dates, ROSTER_STREAM)
    if not roster:
        raise EvaluatorWindowError(
            f"sealed snapshot {name!r} carries no {ROSTER_STREAM} "
            "partitions, so there is no universe to resolve as of "
            f"{moment.isoformat()} — the roster is read from the bars "
            "stream (docs §4.3), and a snapshot without bars cannot say "
            "what was tradable"
        )

    # Coverage over the roster stream's dates only: the universe question
    # is a bars question, so the range that bounds it is the bars range.
    covered = sorted({day for days in roster.values() for day in days})
    first, last = covered[0], covered[-1]
    if decision < first or decision > last:
        edge = "before the first" if decision < first else "after the last"
        raise EvaluatorWindowError(
            f"decision date {decision.isoformat()} is {edge} sealed bars "
            f"partition in snapshot {name!r} (covered {first.isoformat()} "
            f"to {last.isoformat()}), so the snapshot cannot say what was "
            "tradable then — resolve a decision time inside the sealed "
            "coverage, or seal a snapshot that covers it"
        )

    universe = tuple(
        symbol for symbol, days in sorted(roster.items()) if decision in days
    )

    slices: dict[str, Mapping[str, Tuple[str, ...]]] = {}
    for stream in SLICED_STREAMS:
        layout = _stream_layout(partitions, dates, stream)
        kept: dict[str, Tuple[str, ...]] = {}
        for symbol, days in layout.items():
            surviving = tuple(
                day.isoformat() for day in days if day <= decision
            )
            if surviving:
                kept[symbol] = surviving
        if kept:
            slices[stream] = MappingProxyType(kept)

    return WindowResolution(
        snapshot_name=name,
        t=moment,
        universe=universe,
        slices=slices,
    )
