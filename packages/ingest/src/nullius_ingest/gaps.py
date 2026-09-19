"""Websocket sequence-number gap detection, on reconnect and within a feed.

app_spec.xml feature 25 states the behaviour: *"System detects a
websocket sequence-number gap on reconnect, which emits a gap_detected
event naming the affected stream."*  docs/nullius-tech-architecture.md
§15 names the failure being watched for — the row *"WS gap / reconnect |
Sequence-number gap | REST backfill the gap before sealing the next
snapshot"* — and the deployment table repeats the chain as a property
ingest must have: *restart-safe, gap-backfill on reconnect*.

The vocabulary the module builds on is §4.1's: one worker per stream
class, and each websocket feed numbers its messages with a
monotonically increasing sequence (an aggregation ID, a diff range
bound — the exchange's spelling is the stream worker's business, not
this module's).  Continuity is therefore checkable: after sequence
``n``, a live feed delivers ``n + 1``.  A message arriving with a
sequence *past* the expected one means the feed skipped everything in
between — that hole is the gap, and §15's answer to it (REST backfill,
feature 26) cannot start until the hole is *named*.

Three pieces, each load-bearing:

* **The detector** — :class:`GapDetector`, a per-stream sequence
  watermark.  :meth:`GapDetector.observe` is called once per message
  sequence the stream worker receives; :meth:`GapDetector.reconnect`
  marks the reconnect boundary the worker crosses when its websocket
  drops and re-establishes.  A jump over the expected sequence emits a
  :class:`GapDetected` event; anything else (a first-ever message, a
  contiguous tail, a duplicate) emits nothing.

* **The event** — :class:`GapDetected`, frozen and JSON-friendly like a
  :class:`~nullius_ingest.worker.StreamFailure`, naming the affected
  stream, the inclusive range of missing sequences, and whether the gap
  opened across a reconnect.  Its kind is carried as data
  (:attr:`GapDetected.event`, always :data:`GAP_DETECTED_EVENT`) so a
  sink that receives several event kinds can route on it without
  importing this class.

* **The log** — :class:`GapEventLog`, an append-only record of emitted
  events.  An event nobody can observe is a return value, not an event:
  the detector hands every event to the sink wired at construction *and*
  returns it to the immediate caller, and the log is the standard sink —
  the seam feature 26's backfill and seal gate read to learn which gaps
  stay open.

Two stances worth stating plainly, because they are decisions rather
than accidents:

*Detection is not failure.*  §15's recovery for a gap is *REST backfill
the gap*, not halt — the feed's tail after the hole is real data and
keeps flowing, so the detector advances the watermark past the hole
(the messages after it are ingested, never re-fetched as duplicates)
and records the hole in the event for the backfiller to fill.  A cycle
that detected a gap is a *successful* cycle; the event is data, the
same conversion :mod:`nullius_ingest.worker` performs for failures,
arriving on a different channel.  Contrast the schema gate
(:mod:`nullius_ingest.schema`), whose §15 row ends in *halt*: there the
raise is the response, here the record is.

*A hole is a hole, wherever it opened.*  The check runs on every
observation, not only the first after a reconnect: a feed that skips
mid-connection lost exactly the messages a reconnect skip lost, and the
backfill does not care where the hole opened.  ``reconnect`` exists so
the event can say *where* — :attr:`GapDetected.on_reconnect` — and so a
worker has one honest place to declare the boundary it crossed.  The
messages that could have been lost while disconnected are precisely the
ones the first post-reconnect sequence is compared against.

What is deliberately *not* a gap:

* a stream's **first-ever** observed sequence — there is no baseline to
  gap against; whatever came before the worker started is backfill
  territory, not a detected hole;
* a **duplicate, replayed or out-of-order** message — a sequence at or
  below the watermark carries no new information about the forward
  tail, and inventing a "negative gap" from it would be noise the
  backfiller cannot act on.  The watermark never regresses.

The module is stdlib-only, like the rest of the isolation framework:
watching integers go up needs no websocket client.  The stream workers
of features 17–24 own the connections and call ``observe``/``reconnect``
from their own readers; this module owns only the arithmetic of
continuity.
"""

from __future__ import annotations

import operator
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final, SupportsIndex

from .streams import StreamClass, coerce_stream_class

__all__ = [
    "GAP_DETECTED_EVENT",
    "GapDetected",
    "GapDetector",
    "GapEventLog",
]

#: The kind of event a gap detection emits — the spelling the feature
#: statement fixes, and the one logs, alerts and feature 26's backfill
#: match on.
GAP_DETECTED_EVENT: Final[str] = "gap_detected"


def _coerce_sequence(value: object, what: str) -> int:
    # Sequences are integers.  ``SupportsIndex`` is exactly the
    # capability being asked for — any honest integer, including the
    # fixed-width kinds a reader library may return — while the
    # look-alikes (floats, numeric strings) are refused: they would
    # compare equal to a sequence while being none.
    if not isinstance(value, SupportsIndex):
        raise TypeError(
            f"{what} must be an integer sequence number, "
            f"not {type(value).__name__}"
        )
    return operator.index(value)


@dataclass(frozen=True)
class GapDetected:
    """The event emitted when a stream's sequence jumps past a hole.

    Names the affected stream (and only that stream — the per-stream
    isolation of feature 16 applies to events exactly as it applies to
    failures), the inclusive range of missing sequences, and whether the
    hole opened across a reconnect or within an open connection.  The
    kind is carried as data in :attr:`event` so a sink routing several
    event kinds can dispatch on the string without importing this class.

    Frozen and JSON-friendly on purpose, like a
    :class:`~nullius_ingest.worker.StreamFailure`: the event is logged,
    counted and queued for backfill — never raised — so a detected gap is
    always a row in a log rather than a stoppage of the stream.
    """

    stream: StreamClass
    """The stream class whose sequence jumped — never any other stream."""

    first_missing: int
    """The first sequence in the hole, inclusive."""

    last_missing: int
    """The last sequence in the hole, inclusive."""

    on_reconnect: bool = False
    """``True`` when the hole opened across a reconnect, ``False`` when
    the feed skipped within an open connection."""

    event: str = GAP_DETECTED_EVENT
    """The event kind — always :data:`GAP_DETECTED_EVENT`."""

    def __post_init__(self) -> None:
        # The record is ours, so it must be well-formed before anything
        # logs or routes it: the stream must coerce and the missing range
        # must be a range.  An inverted range would be a lie a backfiller
        # cannot even name, so it is refused here, never emitted.
        object.__setattr__(self, "stream", coerce_stream_class(self.stream))
        object.__setattr__(
            self,
            "first_missing",
            _coerce_sequence(self.first_missing, "first_missing"),
        )
        object.__setattr__(
            self,
            "last_missing",
            _coerce_sequence(self.last_missing, "last_missing"),
        )
        if self.first_missing > self.last_missing:
            raise ValueError(
                f"a gap's missing range cannot be inverted: first_missing "
                f"{self.first_missing} > last_missing {self.last_missing}"
            )

    @property
    def missing_count(self) -> int:
        """How many sequences the hole spans (its inclusive size)."""
        return self.last_missing - self.first_missing + 1

    def render(self) -> str:
        """One line an operator reads and knows what was lost, and where.

        The stream, the hole, its size, and whether it opened across a
        reconnect — the facts §15's row pairs with a recovery action, so
        the recovery's owner can start without re-deriving any of them.
        """
        where = "on reconnect" if self.on_reconnect else "within an open connection"
        return (
            f"{self.event}: {self.stream} is missing sequences "
            f"{self.first_missing}..{self.last_missing} "
            f"({self.missing_count} messages) detected {where}"
        )


class GapDetector:
    """Watches per-stream sequence numbers and emits an event per hole.

    One detector can watch every stream class — its state is keyed by
    stream, exactly as a :class:`~nullius_ingest.watermark.SequenceStore`
    keys its watermarks, so one stream's sequences never influence
    another's continuity — and the stream workers of features 17–24 drive
    it with two calls:

    * :meth:`observe`, once per message sequence the feed delivers;
    * :meth:`reconnect`, when the worker's websocket drops and
      re-establishes, marking the boundary the next observation continues
      across.

    Detection is the arithmetic of continuity: the watermark holds the
    highest sequence observed, the feed owes ``watermark + 1`` next, and a
    message arriving past that owes a :class:`GapDetected` naming
    everything skipped.  The watermark then advances to the observed
    sequence — the messages after the hole are real data, and the hole
    lives on in the event, not in a stalled tail.

    Every event is handed to the ``on_event`` sink wired at construction
    (when one is wired) *and* returned to the immediate caller: the sink
    is how the system emits — a :class:`GapEventLog`, an alert, whatever
    feature 26 wires — and the return is how the calling worker learns
    the same fact without a second observation.  The sink's return value
    is ignored, so the parameter takes any callable receiving one event
    — including :meth:`GapEventLog.record`, whose pass-through return is
    there for composition, not for the detector.  A detector is a
    state machine, not a thread-safe service: like the stores, it expects
    one caller per stream (the supervisor's one-thread-per-worker), and a
    sink shared across workers must do its own guarding — which is why
    :class:`GapEventLog` locks.
    """

    def __init__(
        self, on_event: Callable[[GapDetected], object] | None = None
    ) -> None:
        if on_event is not None and not callable(on_event):
            raise TypeError(
                f"on_event must be callable receiving one GapDetected, "
                f"got {type(on_event).__name__}"
            )
        self._on_event = on_event
        self._last: dict[StreamClass, int] = {}
        self._reconnected: set[StreamClass] = set()

    # -- observation ------------------------------------------------------

    def observe(self, stream: StreamClass | str, sequence: int) -> GapDetected | None:
        """Record one observed sequence; emit an event if it jumped a hole.

        Returns the :class:`GapDetected` naming the stream and the
        missing range when ``sequence`` passes over the expected one,
        else ``None`` — the three ``None`` cases being the stream's first
        observation (no baseline to gap against), a contiguous tail, and
        a duplicate or replayed message (no forward hole to name).
        """
        stream = coerce_stream_class(stream)
        sequence = _coerce_sequence(sequence, "sequence")
        last = self._last.get(stream)

        if last is None:
            # The stream's first observed sequence: everything before it
            # predates the worker, which is backfill territory, not a
            # detected hole.  It still consumes a reconnect mark — the
            # boundary was crossed, there was simply nothing to lose.
            self._last[stream] = sequence
            self._reconnected.discard(stream)
            return None

        if sequence <= last:
            # A duplicate, replayed or out-of-order message.  It carries
            # no information about the forward tail, so it neither gaps
            # nor consumes the reconnect boundary: only a sequence that
            # advances the feed decides continuity.
            return None

        self._last[stream] = sequence
        on_reconnect = stream in self._reconnected
        self._reconnected.discard(stream)
        if sequence == last + 1:
            # Exactly what continuity owed: nothing was lost.
            return None

        event = GapDetected(
            stream=stream,
            first_missing=last + 1,
            last_missing=sequence - 1,
            on_reconnect=on_reconnect,
        )
        if self._on_event is not None:
            self._on_event(event)
        return event

    def reconnect(self, stream: StreamClass | str) -> None:
        """Mark that ``stream``'s websocket reconnected.

        The messages the feed advanced while the worker was disconnected
        are exactly the ones the *next* observation is compared against,
        so this records the boundary the next sequence continues across:
        if that observation jumps, its event carries
        ``on_reconnect=True``; if it lands contiguous, nothing was lost
        and the boundary is consumed silently.  A reconnect for a stream
        never yet observed is allowed and harmless — the first-ever
        observation has no baseline to gap against either way.
        """
        self._reconnected.add(coerce_stream_class(stream))

    # -- introspection ------------------------------------------------------

    def last_sequence(self, stream: StreamClass | str) -> int | None:
        """The highest sequence observed for ``stream``; ``None`` if none.

        The watermark gap detection compares against — advanced past a
        detected hole, never regressed by a duplicate.
        """
        return self._last.get(coerce_stream_class(stream))

    def expected_next(self, stream: StreamClass | str) -> int | None:
        """The sequence continuity owes next for ``stream``.

        ``last_sequence + 1`` — the value whose absence the next
        observation names — or ``None`` when the stream has never been
        observed (no baseline, no debt).
        """
        last = self.last_sequence(stream)
        return None if last is None else last + 1


class GapEventLog:
    """An append-only record of gap events, safe to share across workers.

    The standard ``on_event`` sink: every :class:`GapDetected` a
    :class:`GapDetector` emits is recorded here in emission order and
    replayed by stream or in full.  This is the seam feature 26 reads —
    the backfill fills the holes these events name, and the seal gate
    rejects while any stays open — so the record is the system's memory
    of what the feeds skipped.

    Locked, deliberately: the supervisor runs one thread per worker per
    cycle, so a log wired as several detectors' sink receives events from
    several threads.  The detector itself stays lock-free (one caller per
    stream, like the stores); the log is the shared object, so the log
    carries the guard.  Reads snapshot under the same lock — an
    :meth:`events` result is an immutable tuple, never a live view a
    concurrent append could tear.
    """

    def __init__(self) -> None:
        self._events: list[GapDetected] = []
        self._lock = threading.Lock()

    def record(self, event: GapDetected) -> GapDetected:
        """Append ``event`` to the log, returning it for pass-through wiring.

        The natural sink is ``GapDetector(on_event=log.record)``: the
        record returns its argument so composition keeps flowing, the
        same pass-through :meth:`~nullius_ingest.supervisor.IngestSupervisor.add_worker`
        and :func:`~nullius_ingest.registry.register_worker` use.  A
        non-event is a wiring bug and fails loudly, not a silent row a
        backfiller would later trip over.
        """
        if not isinstance(event, GapDetected):
            raise TypeError(
                f"a gap event log records GapDetected events, "
                f"got {type(event).__name__}"
            )
        with self._lock:
            self._events.append(event)
        return event

    def events(
        self, stream: StreamClass | str | None = None
    ) -> tuple[GapDetected, ...]:
        """The recorded events, in emission order.

        With ``stream`` given, only that stream's events — a gap on one
        stream is never reported under another's name.  Without it, every
        recorded event, still in the order they were emitted.
        """
        if stream is None:
            with self._lock:
                return tuple(self._events)
        wanted = coerce_stream_class(stream)
        with self._lock:
            return tuple(event for event in self._events if event.stream == wanted)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def __iter__(self) -> Iterator[GapDetected]:
        return iter(self.events())
