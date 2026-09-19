"""Backfill a detected websocket gap over REST before the next snapshot seals.

app_spec.xml feature 26 states the behaviour: *"System backfills a detected
websocket gap over REST before the next snapshot seals, which rejects a seal
attempt while any gap stays open."*  docs/nullius-tech-architecture.md §15
names the failure being recovered — the row *"WS gap / reconnect |
Sequence-number gap | REST backfill the gap before sealing the next
snapshot"* — and feature 25 (:mod:`nullius_ingest.gaps`) names the hole: a
:class:`~nullius_ingest.gaps.GapDetected` event carrying the inclusive range
of missing sequences.  Feature 26 is the recovery that row promises: fill the
hole, and refuse to seal until it is filled.

The chain the feature describes has three links, and each is a seam this
module owns:

* **The hole is already named.**  Feature 25's detector has, by the time
  backfill runs, emitted a :class:`~nullius_ingest.gaps.GapDetected` into a
  :class:`~nullius_ingest.gaps.GapEventLog` — the log is the shared memory of
  what the feeds skipped.  Backfill does not re-detect; it *reads* that log.
  This is why the log, not the detector, is backfill's dependency: the
  detector is the live feed's watermark, the log is the durable record of
  holes, and a restart (which reconstructs the detector empty) still has the
  log's events to fill.

* **The fill is a REST fetch, injected.**  A gap names a stream and an
  inclusive sequence range; the backfiller turns that into a REST request and
  writes the returned rows into the stream's staging log (feature 28's
  :class:`~nullius_ingest.staging.StagingArea`), one batch per gap.  The
  fetch is a :data:`GapFetch` callable the caller supplies — the stream
  workers of features 17–24 own the exchange's REST client and its auth,
  rate limits and pagination, none of which this module knows.  The
  backfiller owns only the *orchestration*: which holes are open, in what
  order to fill them, and when a hole counts as filled.

* **The seal is gated.**  While any gap stays open the next snapshot seal is
  refused: a snapshot that sealed over an unfilled hole would carry a hole in
  the very data the evaluator reads, so the seal is rejected — with the
  stream and the hole named — rather than performed.  The gate wraps the
  sealing service (the ``snapshot`` member's
  :class:`~snapshot.SnapshotService`); the refusal is the service's own
  immutability machinery, reached through a path that states *why* — an open
  gap — rather than a bare content conflict.

Two properties of the fill are load-bearing, and both are enforced rather
than hoped for:

* **A gap is filled by exactly the sequences it named.**  After a fetch the
  backfiller checks that the rows it got cover the gap's range — the fetch
  was asked for ``first_missing..last_missing`` and must return that range,
  no less.  A short fetch (fewer rows than the hole, a row outside the range)
  leaves the gap open and raises :class:`GapNotFilledError`, so a seal is not
  gated on a fill that did not actually fill.  A fetch that returns *more*
  than the range is refused too: the extra rows are a different range than
  the event named, and silently accepting them would let a fetch rewrite the
  hole's meaning.

* **A filled gap is not re-filled.**  Filling records the gap as filled in a
  per-stream set; a gap already filled is skipped, so a retry over the same
  log does not re-fetch.  The set is in-memory by the same stance the
  detector takes — the live feed's state — because whether a gap is filled is
  decided by what this run fetched, not by a durable file; the log stays the
  durable record of what was *detected*, and the filled set the record of
  what this process *did about it*.

The module is stdlib-only, like the rest of the isolation framework: the
arithmetic of "which holes are open and are they covered" needs no REST
client and no Parquet writer.  The fetch and the staging area are handed in;
the seal gate is handed the service.  What this module adds is the glue the
feature names and no other module owns — the open-gap query, the fill loop,
and the gate that refuses to seal over a hole.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from .gaps import GapDetected, GapEventLog
from .staging import StagingArea
from .streams import StreamClass, coerce_stream_class

__all__ = [
    "GapFetch",
    "GapFilled",
    "GapNotFilledError",
    "GapBackfiller",
    "SealGate",
]

#: The kind of event a gap backfill emits when it fills a hole — the
#: complement of :data:`~nullius_ingest.gaps.GAP_DETECTED_EVENT`, so a sink
#: routing both sees a detected gap answered by its fill on a parallel channel.
GAP_FILLED_EVENT: str = "gap_filled"


class GapNotFilledError(RuntimeError):
    """A backfill fetch did not cover the gap it was asked to fill.

    Raised when the rows a :data:`GapFetch` returned for a gap do not span
    exactly that gap's sequence range — too few rows, or a row outside the
    range.  The refusal is the seal gate's load-bearing half: a gap is only
    marked filled when the fill provably covered it, so the gate never
    clears a hole a short fetch left open.  The error carries the gap and
    the range the fetch actually covered, so the alert can state precisely
    what is still missing.
    """

    def __init__(
        self,
        gap: GapDetected,
        covered_first: int,
        covered_last: int,
    ) -> None:
        self.gap = gap
        self.covered_first = covered_first
        self.covered_last = covered_last
        super().__init__(
            f"backfill for {gap.stream} did not fill the gap "
            f"{gap.first_missing}..{gap.last_missing}: the fetch covered "
            f"{covered_first}..{covered_last}"
        )


GapFetch = Callable[[StreamClass, int, int], "Sequence[object]"]
"""Fetch the rows for one gap's inclusive sequence range.

The seam the stream workers' REST clients fill: given the stream class and
the first and last sequence the gap named (inclusive), return the rows that
cover that range.  The backfiller asks for exactly ``gap.first_missing`` and
``gap.last_missing``; the fetch returns the rows, which the backfiller then
checks span that range before it trusts the fill.  The rows are opaque to
this module — the caller knows their shape and how to serialise them into a
staging payload — which is why the fetch returns them and the backfiller
hands them straight to :attr:`GapBackfiller.serialize`.
"""

Serialize = Callable[[StreamClass, "Sequence[object]", int, int], bytes]
"""Turn fetched rows into the bytes a staging append writes.

Given the stream, the rows, and the inclusive range they cover, return the
opaque payload bytes.  The caller owns this — it knows the row shape and the
staging wire format — so the backfiller never has to.
"""


@dataclass(frozen=True)
class GapFilled:
    """The record of a gap a backfill fill covered.

    Echoes the filled gap's range and the batch it produced, so a monitor
    can log the fill — and, crucially, so the caller learns the fill
    *happened* rather than inferring it.  The ``event`` kind is carried as
    data (:data:`GAP_FILLED_EVENT`) exactly as :class:`GapDetected` carries
    :data:`~nullius_ingest.gaps.GAP_DETECTED_EVENT`, so a sink routing both
    channels sees a detected gap answered by its fill.
    """

    gap: GapDetected
    batch_sequence: int
    event: str = GAP_FILLED_EVENT

    @property
    def first(self) -> int:
        """The first sequence the fill covered (the gap's ``first_missing``)."""
        return self.gap.first_missing

    @property
    def last(self) -> int:
        """The last sequence the fill covered (the gap's ``last_missing``)."""
        return self.gap.last_missing

    def render(self) -> str:
        """One line an operator reads and knows the hole was filled."""
        return (
            f"{self.event}: {self.gap.stream} backfilled sequences "
            f"{self.first}..{self.last} "
            f"({self.gap.missing_count} messages) as batch "
            f"{self.batch_sequence}"
        )


class GapBackfiller:
    """Fill the open gaps a :class:`GapEventLog` records, over REST.

    Reads the log feature 25's detector wrote — the durable record of holes —
    and, for each gap that is still open (detected and not yet filled), fetches
    the missing rows and writes them into the stream's staging log.  The fetch
    and the row serialisation are injected (:data:`GapFetch`, :data:`Serialize`),
    the staging area is handed in; the backfiller owns only the orchestration
    the feature names: which holes are open, in what order to fill them, and
    when a hole counts as filled.

    A backfiller is one-stream-per-call in its fill loop (the supervisor's
    one-thread-per-worker), but its ``filled`` set and the shared staging area
    are safe under concurrency: the filled set is guarded by its own lock, and
    the staging area guards its own appends.  Gaps are filled in ascending
    sequence order within a stream, so a stream's backfill batches land in the
    order the hole opened — the honest order, and the one a seal copies them
    in.

    ``open_gaps`` reports the holes still to fill: every detected gap whose
    range this process has not yet covered.  A gap is filled by exactly the
    sequences it named — :meth:`fill_gap` checks the fetch covered the range
    and raises :class:`GapNotFilledError` otherwise — and a filled gap is
    skipped on a retry, so the same log is not re-fetched.
    """

    def __init__(
        self,
        log: GapEventLog,
        staging: StagingArea,
        fetch: GapFetch,
        serialize: Serialize,
    ) -> None:
        if not callable(fetch):
            raise TypeError(
                f"fetch must be a callable receiving (stream, first, last), "
                f"got {type(fetch).__name__}"
            )
        if not callable(serialize):
            raise TypeError(
                f"serialize must be a callable receiving "
                f"(stream, rows, first, last), got {type(serialize).__name__}"
            )
        if not isinstance(log, GapEventLog):
            raise TypeError(
                f"backfiller reads a GapEventLog, got {type(log).__name__}"
            )
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"backfiller writes to a StagingArea, got {type(staging).__name__}"
            )
        self._log = log
        self._staging = staging
        self._fetch = fetch
        self._serialize = serialize
        # The gaps this process has filled, by (stream, first_missing,
        # last_missing): a filled gap is not re-filled, so a retry over the
        # same log does not re-fetch.  In-memory, like the detector's
        # watermark — whether a gap is filled is decided by what this run
        # fetched, not by a durable file.
        self._filled: set[tuple[StreamClass, int, int]] = set()

    # -- The open-gap query ---------------------------------------------------

    def open_gaps(self) -> tuple[GapDetected, ...]:
        """The gaps still to fill: detected, and not yet filled by this process.

        Every event the log holds whose range this process has not covered,
        in emission order.  A gap filled by an earlier call in this process is
        excluded, so ``open_gaps`` after a fill reflects the fill — the query
        the seal gate reads to decide whether a seal may proceed.
        """
        return tuple(
            event
            for event in self._log.events()
            if (event.stream, event.first_missing, event.last_missing)
            not in self._filled
        )

    def is_open(self, gap: GapDetected) -> bool:
        """Whether ``gap`` is still open — detected and not yet filled here."""
        return (gap.stream, gap.first_missing, gap.last_missing) not in self._filled

    # -- The fill -------------------------------------------------------------

    def fill_stream(self, stream: StreamClass | str) -> tuple[GapFilled, ...]:
        """Fill every open gap on ``stream``; return the fills, in range order.

        Gaps are filled in ascending ``first_missing`` order, so a stream's
        backfill batches land in the order the holes opened.  A gap already
        filled by this process is skipped.  Each fill fetches the gap's range,
        checks the fetch covered it (raising :class:`GapNotFilledError` on a
        short or out-of-range fetch), and appends the serialised rows to the
        stream's staging log as the next batch.
        """
        stream = coerce_stream_class(stream)
        gaps = sorted(
            (g for g in self.open_gaps() if g.stream == stream),
            key=lambda g: (g.first_missing, g.last_missing),
        )
        filled: list[GapFilled] = []
        for gap in gaps:
            filled.append(self.fill_gap(gap))
        return tuple(filled)

    def fill_gap(self, gap: GapDetected) -> GapFilled:
        """Fill one gap: fetch its range, verify coverage, append to staging.

        The fetch is asked for exactly the gap's inclusive range; the rows it
        returns must span that range, or the gap stays open and
        :class:`GapNotFilledError` is raised before any batch is appended — so
        the append only ever lands rows that provably filled the hole.  A gap
        this process already filled is skipped and its prior fill returned, so
        a retry is idempotent.  The batch claims ``current + 1`` in the
        stream's staging log (feature 28's append-only area), exactly as a
        live-feed cycle would.
        """
        stream = coerce_stream_class(gap.stream)
        key = (stream, gap.first_missing, gap.last_missing)
        # Idempotent: a gap filled by this process is not re-fetched, so a
        # retry over the same log returns the same fill rather than a second
        # batch at a new sequence.
        if key in self._filled:
            raise ValueError(
                f"gap {stream} {gap.first_missing}..{gap.last_missing} is "
                f"already filled this process; not re-filling"
            )

        rows = list(self._fetch(stream, gap.first_missing, gap.last_missing))
        # The fetch was asked for exactly the gap's range and must return
        # exactly that many rows: a short fetch (fewer rows than the hole,
        # including an empty one) or an over-range one leaves the hole still
        # open, so the seal gate keeps it open rather than trusting a fill
        # that did not fill.  The covered range reported is the count the
        # fetch actually returned, starting at the hole's first sequence.
        covered_first = gap.first_missing
        covered_last = covered_first + len(rows) - 1
        if len(rows) != gap.missing_count:
            raise GapNotFilledError(gap, covered_first, covered_last)

        payload = self._serialize(stream, rows, gap.first_missing, gap.last_missing)
        batch = self._staging.append(stream, payload=payload, rows=len(rows))
        self._filled.add(key)
        return GapFilled(gap=gap, batch_sequence=batch.sequence)

    # -- Introspection --------------------------------------------------------

    @property
    def filled_count(self) -> int:
        """How many gaps this process has filled."""
        return len(self._filled)

    def filled_gaps(self) -> tuple[GapDetected, ...]:
        """The gaps this process has filled, in fill order."""
        # A set has no order; report in the log's emission order so the record
        # reads the way the holes were detected.
        return tuple(
            event
            for event in self._log.events()
            if (event.stream, event.first_missing, event.last_missing)
            in self._filled
        )


class SealGate:
    """Refuse a snapshot seal while any ingest gap stays open.

    Wraps a :class:`~snapshot.SnapshotService` and forwards its ``seal`` — but
    first checks the :class:`GapBackfiller`'s open gaps, and when any are open
    refuses the seal with a :class:`~snapshot.SnapshotError` naming the stream
    and the hole.  This is feature 26's second half: the backfill fills the
    hole, and the seal is gated on the fill being complete, so a snapshot is
    never sealed over data with a hole in it.

    The refusal goes through the sealing service's own error type, so a caller
    catching seal failures catches an open-gap refusal the same way it catches
    every other seal refusal — the gate does not invent a new failure channel,
    it states a reason the service's machinery already understands.  The gate
    is a thin seam over the service: it owns the *why* (an open gap) and the
    service owns the *how* (the actual seal), so the seal's immutability and
    content-addressing are unchanged.

    The gate reads the backfiller's :meth:`GapBackfiller.open_gaps`, so it
    reflects fills this process performed: backfill the gaps, then the same
    gate lets the seal through.  A gate built without a backfiller (``None``)
    forwards unconditionally — the honest "no gap tracking wired" default, so
    the seal path works before feature 25's detector is in the loop.
    """

    def __init__(
        self,
        service: "SnapshotService",
        backfiller: Optional[GapBackfiller] = None,
    ) -> None:
        # Imported lazily so this module depends on the snapshot member only
        # at call time — the members are peers discovered by the loader, and
        # importing snapshot at module load would make ingest import a peer
        # it is not permitted to name.  The service is checked against the
        # very class the loader composes, so the gate wraps the real sealing
        # service and nothing masquerading as one.
        from snapshot import SnapshotError, SnapshotService

        if not isinstance(service, SnapshotService):
            raise TypeError(
                f"seal gate wraps a SnapshotService, got {type(service).__name__}"
            )
        if backfiller is not None and not isinstance(backfiller, GapBackfiller):
            raise TypeError(
                f"seal gate backfiller must be a GapBackfiller or None, "
                f"got {type(backfiller).__name__}"
            )
        self._service = service
        self._backfiller = backfiller
        self._SnapshotError = SnapshotError

    @property
    def service(self) -> "SnapshotService":
        """The sealing service this gate forwards to."""
        return self._service

    def open_gaps(self) -> tuple[GapDetected, ...]:
        """The gaps blocking a seal right now — the backfiller's open gaps.

        Empty when no backfiller is wired, so a gate without gap tracking
        never blocks.
        """
        if self._backfiller is None:
            return ()
        return self._backfiller.open_gaps()

    def seal(self, *args: object, **kwargs: object) -> object:
        """Seal via the wrapped service — unless a gap is open.

        Forwards to :meth:`~snapshot.SnapshotService.seal` with the same
        arguments.  When the backfiller reports an open gap, refuses first
        with a :class:`~snapshot.SnapshotError` naming the stream and the
        hole, and the service is never asked to seal.  Fill the gaps and the
        same call goes through.
        """
        blocking = self.open_gaps()
        if blocking:
            gaps = ", ".join(
                f"{g.stream} {g.first_missing}..{g.last_missing}"
                f" ({g.missing_count} messages)"
                for g in blocking
            )
            raise self._SnapshotError(
                f"refusing to seal while {len(blocking)} websocket gap(s) "
                f"stay open: {gaps}; backfill the gaps over REST before "
                f"sealing the next snapshot"
            )
        return self._service.seal(*args, **kwargs)

    # -- Convenience ----------------------------------------------------------

    def seal_if_sealed(
        self,
        source: Optional[Union[str, "Path"]] = None,
        **kwargs: object,
    ) -> object:
        """Seal the given source if no gap is open; the scheduled-seal path.

        The one-liner the §4.1 seal-on-schedule loop calls: backfill has run,
        the gaps are filled, this seals.  If a gap somehow stays open the seal
        is refused as in :meth:`seal`.  ``source`` defaults to the lake's
        staging area, exactly as the service's ``seal``.
        """
        return self.seal(source, **kwargs)
