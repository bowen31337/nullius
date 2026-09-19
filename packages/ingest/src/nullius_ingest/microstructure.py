"""Microprice, spread and order-flow imbalance, persisted permanently.

app_spec.xml feature 21 states the behaviour: *"System computes microprice,
spread and order-flow imbalance over several windows, persisting each as a
permanently retained book feature."*  docs/nullius-tech-architecture.md §4.1
lists the three among the derived book features the L2 retention decision
exists to make permanent, and then states the trade that makes this tier
load-bearing:

    **The L2 retention decision is load-bearing.**  Raw diff streams for a
    100-symbol universe run roughly 50–200 GB/month uncompressed.  Storing them
    forever is a self-inflicted infrastructure problem.  Instead: keep raw diffs
    for a rolling 90 days so feature definitions can be revised and backfilled
    recently, and permanently persist derived book features at 1s resolution
    (depth at 5/10/25/50 bps each side, **microprice, spread, OFI over several
    windows**, cancel/replace rate, trade-size distribution moments).

docs/alpha-engine-prd.md names the same family as the reason the tier is worth
computing at all: *"L2 and tape are public; the* features *are not.  OFI, queue
dynamics, … Information advantage manufactured by compute"*, and again under
the build phases: *"Order-flow imbalance and microstructure features from the
free L2 feed."*

This module is feature 21's half of that derived tier, beside feature 20's
depth ladder (:mod:`nullius_ingest.book_features`) and feature 22's
cancel-replace rate and trade-size moments (:mod:`nullius_ingest.trade_flow`).
It reads the raw-diff log feature 19 persists, reconstructs the book through
feature 20's :class:`~nullius_ingest.book_features.BookState` (it does not
re-implement the book), and turns the reconstruction into a permanent 1s
microstructure log.

Five things make this different from every stream module before it:

* **"Over several windows" attaches to the OFI, and §4.1's own punctuation
  says so.**  The retention sentence lists *"microprice, spread, OFI over
  several windows"* — microprice and spread are *states*, a fact about the
  book at an instant, and an instant is the 1s boundary itself; OFI is a
  *flow*, an amount of order activity integrated over an interval, and an
  interval is what a window names.  So a row carries one microprice and one
  spread — measured at the boundary — and one OFI per window in
  :data:`OFI_WINDOWS`: the slice itself (1 s), a 5 s and a 10 s near-term
  ladder, and the 60 s minute the klines stream owns, so the ladder spans
  slice to bar.  A windowed microprice (a mean over the window) was rejected:
  it would average away exactly the imbalance the microprice exists to catch.

* **The OFI is the best-level (top-of-book) order flow of Cont–Kukanov–
  Stoikov, computed event by event off the reconstruction.**  Each raw diff
  moves the book from one top-of-book state to the next, and
  :func:`ofi_increment` is the flow between the two: a bid that improves or
  holds adds its new size and a bid that worsens subtracts its old size, and
  the ask side enters with the opposite sign — an improving ask (sellers
  aggressing) is *negative* flow, a retreating ask (sellers pulling) is
  *positive*.  An empty side is the price sent to its sentinel — a book that
  *gains* a bid side rose out of nothing, a book that *loses* its ask side had
  sellers withdraw — so the first diff of a stream and the last liquidity
  event of a crisis both measure, rather than default.  The multi-level OFI
  was rejected for this tier: the best level is where the literature's price
  impact lives, and the deeper ladder is feature 20's depth bands, already
  persisted, from which a later feature can integrate a wider flow.

* **A second is snapshotted when it closes, not when it opens.**  The depth
  ladder snapshots a second at its *first* diff — a state feature only needs
  the book to exist.  A flow feature must carry the whole window it names:
  OFI over 1 s at second ``S`` is the flow of *all* of ``S``'s events, so the
  row for ``S`` is emitted once ``S`` is complete — the moment the first diff
  of a *later* second lands, or the consumption pass ends — and the windows
  on a row compose exactly: the 60 s window at ``S`` is the sum of the 1 s
  windows of the sixty seconds it spans.  A late diff for an already-committed
  second folds into the book and the flow ledger going forward, never re-opens
  the committed second — the log is append-only, and a committed window is
  never amended.

* **The flow ledger is persisted with each record.**  A 60 s window reaches
  59 s back, across cycle boundaries and across restarts, and the raw diffs
  it would be re-summed from are 90-day-retained and then gone.  So each
  record carries, per symbol, an :class:`OfiTrail` — the per-second OFI
  increments the trail still needs, and the first second the symbol was ever
  observed — beside the closing book every derived module carries.  That
  trail is why the derived store, not the raw store, is the permanent home of
  this history: a restart after the raw window has slid sums its windows from
  the derived log alone.

* **An absence is not a zero.**  A second whose closing book has an empty
  side has no top of book and emits no row — the same honest absence feature
  20 draws for a one-sided book.  A microprice over two best sizes summing to
  zero is ``None``: a weight that divides by nothing is not a price.  An OFI
  window that reaches before the symbol's first observed second is ``None``
  — a partial window is not a measurement, and the first 60 s of a stream say
  so rather than quietly under-reporting — while a *covered* window with no
  events is an exact ``0``: the ledger was watching, and nothing flowed.
  Feature 22 draws the same line between a silent second and an active one.

Layering on feature 19 and feature 20 is deliberate and total: this module
reconstructs through feature 20's :class:`~nullius_ingest.book_features.
BookState` and the two best-size read seams this feature adds to it, reads
the raw records feature 19 persisted through feature 19's store, and
persists into the same append-only staging area as every other stream —
``<lake>/staging/microstructure/`` — so the seal copies it the same way and,
like the funding and exchangeInfo logs, nothing in the system ever expires
it.  The persistence shape (record, envelope, content hash, bytes hash,
corrupt-bytes refusal, closing state, frontier, resume) mirrors
:mod:`nullius_ingest.funding` and :mod:`nullius_ingest.trade_flow`
one-for-one; the genuinely new machinery is the increment, the trail and the
closing-second snapshot, and all three are here.

The member stays stdlib-only: the microprice and the increments are exact
:class:`~decimal.Decimal` arithmetic over the venue's own spellings, and the
worker's input is the *internal* raw-diff store rather than a venue endpoint,
so there is no injected fetch and no unconfigured-fetch path at all — an
empty raw store simply yields empty cycles.  The clock is injected for the
same reason the other workers inject theirs: ``computed_at`` is a fact about
elapsed wall-clock time and §12 keeps wall-clock reads out of checked code.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Optional

from .book_diffs import BookDiffStore
from .book_features import (
    BookState,
    FEATURE_SLICE,
    FEATURE_SLICE_MILLISECONDS,
    _floor_to_second,
)
from .registry import WorkerRegistry, register_worker
from .staging import StagingArea
from .streams import StreamClass
from .worker import CycleResult

__all__ = [
    "MAX_OFI_WINDOW",
    "MICROSTRUCTURE_SLICE",
    "MICROSTRUCTURE_SLICE_MILLISECONDS",
    "MICROSTRUCTURE_STREAM",
    "OFI_WINDOWS",
    "MicrostructureBatch",
    "MicrostructureCorruptError",
    "MicrostructureError",
    "MicrostructureParseError",
    "MicrostructureRecord",
    "MicrostructureRow",
    "MicrostructureStore",
    "MicrostructureWorker",
    "OfiTrail",
    "TopOfBook",
    "build_microstructure_worker",
    "ofi_increment",
    "parse_microstructure",
    "register_microstructure_worker",
]

#: The stream class this module serves — feature 21's derived stream.  §4.1
#: gives the derived tier one row ("Book features (derived) | computed from
#: diffs | 1s | forever") and feature 20 already owns the ``bookFeatures``
#: spelling of it, so this family takes its own value rather than sharing one:
#: the supervisor's contract is one worker per stream class, and two derived
#: families under one class would mean the second registration *replacing* the
#: first rather than joining it.
MICROSTRUCTURE_STREAM = StreamClass.MICROSTRUCTURE

#: The resolution these features are computed at, carried over from feature 20
#: rather than re-declared: the three derived families are snapshotted at the
#: same 1s boundary off the same reconstruction, so a second means the same
#: instant in all three logs.  Aliased so the fact is named where it is used
#: and cannot drift from the tier it belongs to.
MICROSTRUCTURE_SLICE: Final[timedelta] = FEATURE_SLICE
MICROSTRUCTURE_SLICE_MILLISECONDS: Final[int] = FEATURE_SLICE_MILLISECONDS

#: The windows OFI is summed over, in seconds — the "several windows" feature
#: 21 names.  The ladder runs from the slice itself (1 s) through a near-term
#: pair (5 s, 10 s) to the 60 s minute the klines stream owns, so it spans
#: slice to bar; four windows, mirroring the four-band depth ladder feature
#: 20 persists.  Kept as an ordered tuple so a row's OFI map carries them in a
#: stable, named order.  Microprice and spread are deliberately absent: they
#: are states at the boundary, and §4.1 attaches the windows to the OFI alone.
OFI_WINDOWS: Final[tuple[int, ...]] = (1, 5, 10, 60)

#: The widest OFI window, as the span the per-symbol trail must retain.  The
#: trail prunes to this past the frontier each cycle — anything older can no
#: longer enter a future window — while :attr:`OfiTrail.first_window`
#: survives the pruning, because a partial window's honesty depends on
#: knowing where the observations began, not on the increments themselves.
MAX_OFI_WINDOW: Final[timedelta] = timedelta(seconds=max(OFI_WINDOWS))

#: The envelope keys a record file carries around its rows.  ``rows`` is the
#: document; ``closing_books`` and ``closing_flows`` are the resume seed,
#: carried for the same reason feature 20 carries its closing book — the
#: derived log must outlive the raw diffs it was derived from, and a 60 s
#: window reaches further back than any single cycle.
_ENVELOPE_KEYS = (
    "stream",
    "sequence",
    "computed_at",
    "source_sha256",
    "from_window",
    "to_window",
    "from_raw_sequence",
    "to_raw_sequence",
)
_DOCUMENT_KEY = "rows"
_CLOSING_KEY = "closing_books"
_FLOWS_KEY = "closing_flows"

_ZERO: Final[Decimal] = Decimal(0)


class MicrostructureError(Exception):
    """Base for every failure this module raises.

    Raised for a batch this module will not persist and for a persisted record
    it will not read: both are cases where the derived microstructure log
    would otherwise start lying about what the book did, so both fail loudly
    rather than being approximated into a row.
    """


class MicrostructureParseError(MicrostructureError):
    """A batch, a row or a trail is not one this module will accept.

    Raised *before* anything is written, so a malformed row never consumes a
    sequence number and never appears in the log as a snapshot that happened.
    The message names what was wrong with which row, because the caller is a
    worker deciding whether the reduction it produced is sound.
    """


class MicrostructureCorruptError(MicrostructureError):
    """A persisted record file does not match what was written under it.

    Raised when a record file cannot be read back as the envelope it was
    written as, when its recorded sequence is not the sequence its filename
    claims, or when recomputing its document hash disagrees with the hash the
    envelope recorded.  A mismatch means the bytes on disk are not the bytes
    this module committed — corruption or tampering — and a reader that
    rebuilt a feature from them would be rebuilding a market that never
    existed.  The flow trail a record carries makes this matter twice over: a
    damaged trail would seed a restarted worker's windows from flow the
    market never had.
    """


def _canonical_decimal(value: Decimal) -> str:
    # A computed value is rendered in fixed-point, with no exponent notation,
    # so a microprice of ``100.75`` and an increment of ``-2`` are stable
    # across Python versions and JSON round-trips.  Trailing zeros are
    # preserved, so two rows that agree on a number agree on its string — the
    # same convention the derived tier persists its depths and moments under.
    return format(value, "f")


@dataclass(frozen=True)
class TopOfBook:
    """The top of one reconstructed book: each side's best price and size.

    Four facts, each ``None`` exactly when its side is empty: ``bid`` /
    ``bid_quantity`` are the highest bid and the size resting at it, ``ask`` /
    ``ask_quantity`` the lowest ask and its size.  A side exists or it does
    not, so a price without its size (or the reverse) is refused — a caller
    weighting a price by a size the book never had is the exact failure the
    microprice exists to avoid.

    This is the state :func:`ofi_increment` differences: OFI is defined
    between two consecutive tops, and capturing the pair as one value keeps
    the before/after discipline visible at the call site instead of hidden in
    four parallel locals.  Built from the reconstruction with
    :meth:`from_book`, through the read seams feature 21 adds to feature 20's
    :class:`~nullius_ingest.book_features.BookState`.
    """

    bid: Decimal | None
    bid_quantity: Decimal | None
    ask: Decimal | None
    ask_quantity: Decimal | None

    def __post_init__(self) -> None:
        for name, value in (
            ("bid", self.bid),
            ("bid_quantity", self.bid_quantity),
            ("ask", self.ask),
            ("ask_quantity", self.ask_quantity),
        ):
            if value is not None and not isinstance(value, Decimal):
                raise MicrostructureParseError(
                    f"a top-of-book {name} must be a Decimal or None, got "
                    f"{type(value).__name__}"
                )
        for price, quantity, side in (
            (self.bid, self.bid_quantity, "bid"),
            (self.ask, self.ask_quantity, "ask"),
        ):
            if (price is None) != (quantity is None):
                raise MicrostructureParseError(
                    f"the {side} side carries a price and a size together; an "
                    f"empty side has neither, got price={price!r}, "
                    f"size={quantity!r}"
                )

    @classmethod
    def from_book(cls, book: BookState) -> "TopOfBook":
        """The top of ``book``, off the reconstruction's own best seams.

        ``None`` per component for an empty side — the sentinel the increment
        arithmetic reads as the price sent beyond the side's edge, so a side
        appearing or vanishing is measured flow rather than a skipped event.
        """
        return cls(
            bid=book.best_bid(),
            bid_quantity=book.best_bid_quantity(),
            ask=book.best_ask(),
            ask_quantity=book.best_ask_quantity(),
        )


def ofi_increment(before: TopOfBook, after: TopOfBook) -> Decimal:
    """The best-level order flow between two consecutive top-of-book states.

    The Cont–Kukanov–Stoikov best-level OFI of one book event: on the bid
    side, a best price that improves or holds adds its *new* size and one
    that worsens subtracts its *old* size; on the ask side the same
    arithmetic enters with the opposite sign, so an improving ask (sellers
    aggressing toward the bid) is negative flow and a retreating ask (sellers
    pulling away) is positive.  With the best price unchanged both
    indicators fire and the contribution is the change in size — a deeper
    best bid is buying interest, a shallower one is its withdrawal.

    An empty side is the price at its sentinel, which is what makes the
    boundaries measure: a bid side *gained* means the price rose out of
    nothing (``+new size``), a bid side *lost* means it fell to nothing
    (``-old size``), an ask side gained means the price fell from infinity
    (``-new size``) and an ask side lost means sellers withdrew (``+old
    size``).  The very first diff of a stream — both sides appearing at once
    — therefore measures the imbalance of the arrival itself,
    ``bid_qty - ask_qty``: a heavier bid side reads as positive flow, exactly
    as the same imbalance would be read at any later instant.

    Exact :class:`~decimal.Decimal` arithmetic throughout, so an increment a
    test computes by hand is the increment the ledger accumulates.
    """
    bid_flow = _ZERO
    if before.bid is None and after.bid is not None:
        bid_flow = after.bid_quantity  # the price rose out of nothing
    elif before.bid is not None and after.bid is None:
        bid_flow = -before.bid_quantity  # the price fell to nothing
    elif before.bid is not None and after.bid is not None:
        if after.bid >= before.bid:
            bid_flow += after.bid_quantity
        if after.bid <= before.bid:
            bid_flow -= before.bid_quantity
    ask_flow = _ZERO
    if before.ask is None and after.ask is not None:
        ask_flow = after.ask_quantity  # the price fell from infinity
    elif before.ask is not None and after.ask is None:
        ask_flow = -before.ask_quantity  # sellers withdrew to infinity
    elif before.ask is not None and after.ask is not None:
        if after.ask <= before.ask:
            ask_flow += after.ask_quantity
        if after.ask >= before.ask:
            ask_flow -= before.ask_quantity
    return bid_flow - ask_flow


class OfiTrail:
    """One symbol's flow ledger: per-second OFI increments, and where it began.

    The state that makes the windows permanent.  A 60 s window at second
    ``S`` sums the increments of the sixty seconds it spans, most of which
    were folded in earlier cycles — or before a restart — and the raw diffs
    they came from are 90-day-retained and then gone.  So the trail carries
    what the next cycle's windows still need and is persisted with each
    record beside the closing book, which is why a restart (even after the
    raw window has slid) sums its windows from the derived log alone.

    Two facts, each load-bearing:

    * ``increments`` — the accumulated OFI per 1 s bucket, as an exact
      :class:`~decimal.Decimal`.  Accumulating *per second* rather than keep
      a raw event list is what bounds the trail: the widest window needs at
      most :data:`MAX_OFI_WINDOW` buckets, and :meth:`prune` retires the rest
      once the frontier has passed them.
    * ``first_window`` — the earliest second the symbol was ever observed.
      It survives the pruning, because it answers a question the increments
      cannot: is a window *covered*?  A window that reaches before the first
      observation saw only part of the flow it names, and
      :meth:`sum_over` reports ``None`` for it — a partial window is not a
      measurement — while a covered window with no events is an exact ``0``.

    Mutable while a cycle folds, turned into its persistable form with
    :meth:`snapshot` and rebuilt with :meth:`from_snapshot`.
    """

    def __init__(
        self,
        first_window: Optional[datetime] = None,
        increments: Sequence[tuple[datetime, Decimal]] = (),
    ) -> None:
        if first_window is not None and not isinstance(first_window, datetime):
            raise MicrostructureParseError(
                f"a trail's first_window must be a datetime or None, got "
                f"{type(first_window).__name__}"
            )
        self._first_window = first_window
        self._increments: dict[datetime, Decimal] = {}
        for bucket, increment in increments:
            self.observe(bucket, increment)

    # -- Folding ---------------------------------------------------------------

    def observe(self, window_start: datetime, increment: Decimal) -> None:
        """Fold one event's OFI into its 1 second bucket.

        The bucket is floored onto the lattice this module's grid defines, so
        a caller may pass the event's raw instant; the accumulation is exact
        Decimal addition within the bucket.  A bucket *earlier* than the
        first window yet seen moves ``first_window`` back — a late diff for a
        second the ledger had not begun at still proves that second was
        observed, and a window spanning it is covered after all.
        """
        if not isinstance(window_start, datetime):
            raise MicrostructureParseError(
                f"a trail bucket must be a datetime, got "
                f"{type(window_start).__name__}"
            )
        if not isinstance(increment, Decimal):
            raise MicrostructureParseError(
                f"a trail increment must be a Decimal, got "
                f"{type(increment).__name__}"
            )
        bucket = _floor_to_second(window_start)
        self._increments[bucket] = self._increments.get(bucket, _ZERO) + increment
        if self._first_window is None or bucket < self._first_window:
            self._first_window = bucket

    # -- Reading ---------------------------------------------------------------

    @property
    def first_window(self) -> datetime | None:
        """The earliest second this symbol was ever observed, or ``None``."""
        return self._first_window

    @property
    def increments(self) -> tuple[tuple[datetime, Decimal], ...]:
        """The accumulated OFI per bucket, ascending by bucket."""
        return tuple(sorted(self._increments.items()))

    def sum_over(self, window_start: datetime, seconds: int) -> Decimal | None:
        """The OFI over the ``seconds`` window ending at ``window_start``.

        The window is ``(start - seconds, start]`` — half-open on the past,
        closed on the boundary — so consecutive windows tile without overlap
        and the 60 s window at a boundary is exactly the sum of the sixty 1 s
        windows it spans.  ``None`` when the window is not covered: when
        nothing was ever observed, or when the window's start precedes the
        first observed second, because the flow before that is flow the
        ledger never saw and a partial sum would under-report as though it
        were whole.  An exact ``Decimal("0")`` for a covered window in which
        no event moved the top of the book — the ledger was watching, and
        nothing flowed.
        """
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise MicrostructureParseError(
                f"a window length is an integer number of seconds, got "
                f"{seconds!r}"
            )
        if seconds < 1:
            raise MicrostructureParseError(
                f"a window length is at least one second, got {seconds}"
            )
        if not isinstance(window_start, datetime):
            raise MicrostructureParseError(
                f"a window boundary must be a datetime, got "
                f"{type(window_start).__name__}"
            )
        end = _floor_to_second(window_start)
        begin = end - timedelta(seconds=seconds)
        if self._first_window is None or self._first_window > begin:
            return None
        return sum(
            (
                increment
                for bucket, increment in self._increments.items()
                if begin < bucket <= end
            ),
            _ZERO,
        )

    # -- Resuming --------------------------------------------------------------

    def prune(self, keep_from: datetime) -> None:
        """Retire the buckets that can no longer enter a future window.

        Called each cycle with the frontier minus :data:`MAX_OFI_WINDOW`
        (plus one slice of margin): every window a *future* row can name
        starts at or after the frontier, so a bucket older than that span is
        unreachable and carrying it forward would grow the trail without
        bound.  ``first_window`` deliberately survives — coverage is a fact
        about where the observations began, not about the increments still
        held, and pruning it would quietly turn partial windows into
        under-reported whole ones.
        """
        if not isinstance(keep_from, datetime):
            raise MicrostructureParseError(
                f"a prune boundary must be a datetime, got "
                f"{type(keep_from).__name__}"
            )
        boundary = _floor_to_second(keep_from)
        for bucket in [b for b in self._increments if b < boundary]:
            del self._increments[bucket]

    def snapshot(self) -> dict[str, object]:
        """This trail as a persistable mapping — the resume seed's flow half.

        Buckets ascending, each increment in canonical fixed-point, so the
        form is deterministic and the content hash is stable over it.
        ``first_window`` is carried even when every increment has been pruned
        away — an old symbol's coverage fact outlives its flow.
        """
        return {
            "first_window": (
                None
                if self._first_window is None
                else self._first_window.isoformat()
            ),
            "increments": [
                [bucket.isoformat(), _canonical_decimal(increment)]
                for bucket, increment in self.increments
            ],
        }

    @classmethod
    def from_snapshot(cls, snap: Mapping[str, object]) -> "OfiTrail":
        """Rebuild a trail from a :meth:`snapshot` — the resume path.

        The inverse of :meth:`snapshot`: the buckets and increments are read
        back exactly, so a restarted worker sums its windows from the flow
        the derived log holds rather than re-deriving it from raw diffs that
        may since have left the 90-day window.  A snapshot that is not a
        well-formed mapping is refused — a damaged seed would measure windows
        from flow the market never had.
        """
        if not isinstance(snap, Mapping):
            raise MicrostructureParseError(
                f"an OFI trail snapshot is a mapping, got {type(snap).__name__}"
            )
        missing = [key for key in ("first_window", "increments") if key not in snap]
        if missing:
            # A trail carries both its facts or it is not a trail: defaulting a
            # missing ``first_window`` to ``None`` would silently un-cover every
            # window the symbol has, and a missing ``increments`` would silently
            # zero them.
            raise MicrostructureParseError(
                f"a trail snapshot carries first_window and increments; missing "
                f"{', '.join(missing)}"
            )
        first = snap.get("first_window")
        if first is not None and not isinstance(first, str):
            raise MicrostructureParseError(
                f"a trail's first_window is an ISO-8601 string or null, got "
                f"{first!r}"
            )
        first_window = None
        if first is not None:
            try:
                first_window = datetime.fromisoformat(first)
            except ValueError as exc:
                raise MicrostructureParseError(
                    f"a trail's first_window {first!r} is not an ISO-8601 "
                    f"timestamp: {exc}"
                ) from exc
            if first_window.tzinfo is None or first_window.tzinfo.utcoffset(
                first_window
            ) is None:
                raise MicrostructureParseError(
                    f"a trail's first_window {first!r} is naive; coverage "
                    f"needs a comparable instant"
                )
            first_window = first_window.astimezone(timezone.utc)
        entries = snap.get("increments", [])
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise MicrostructureParseError(
                f"a trail's increments are a list of [bucket, increment] "
                f"pairs, got {type(entries).__name__}"
            )
        increments: list[tuple[datetime, Decimal]] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, Sequence) or isinstance(entry, (str, bytes)):
                raise MicrostructureParseError(
                    f"a trail's increments[{index}] is a [bucket, increment] "
                    f"pair, got {type(entry).__name__}"
                )
            if len(entry) != 2:
                raise MicrostructureParseError(
                    f"a trail's increments[{index}] carries {len(entry)} "
                    f"fields; a pair carries two"
                )
            raw_bucket, raw_increment = entry
            if not isinstance(raw_bucket, str):
                raise MicrostructureParseError(
                    f"a trail's increments[{index}] bucket is an ISO-8601 "
                    f"string, got {raw_bucket!r}"
                )
            try:
                bucket = datetime.fromisoformat(raw_bucket)
            except ValueError as exc:
                raise MicrostructureParseError(
                    f"a trail's increments[{index}] bucket {raw_bucket!r} is "
                    f"not an ISO-8601 timestamp: {exc}"
                ) from exc
            if bucket.tzinfo is None or bucket.tzinfo.utcoffset(bucket) is None:
                raise MicrostructureParseError(
                    f"a trail's increments[{index}] bucket {raw_bucket!r} is "
                    f"naive; the 1s grid needs a comparable instant"
                )
            try:
                increment = Decimal(raw_increment)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise MicrostructureParseError(
                    f"a trail's increments[{index}] increment {raw_increment!r} "
                    f"is not a decimal: {exc}"
                ) from exc
            increments.append((bucket.astimezone(timezone.utc), increment))
        return cls(first_window=first_window, increments=increments)


def _microstructure_row(
    symbol: str,
    window_start: datetime,
    book: BookState,
    trail: OfiTrail,
) -> MicrostructureRow | None:
    # Take one symbol's microstructure at one closed 1s boundary: the top of
    # the book as the second left it is the state half of the row, and the
    # trail's windows ending at that boundary are the flow half.  ``None``
    # when the closing book has an empty side — no top of book, no row, the
    # same honest absence feature 20 emits for a one-sided book.  Called only
    # on a closed second, so every increment the boundary's windows name has
    # already been folded.
    top = TopOfBook.from_book(book)
    if top.bid is None or top.ask is None:
        return None
    assert top.bid_quantity is not None and top.ask_quantity is not None
    total = top.bid_quantity + top.ask_quantity
    microprice = (
        None
        if total == 0
        else (top.bid * top.ask_quantity + top.ask * top.bid_quantity) / total
    )
    return MicrostructureRow(
        symbol=symbol,
        window_start=window_start,
        microprice=microprice,
        spread=top.ask - top.bid,
        best_bid=top.bid,
        best_ask=top.ask,
        best_bid_quantity=top.bid_quantity,
        best_ask_quantity=top.ask_quantity,
        ofi={seconds: trail.sum_over(window_start, seconds) for seconds in OFI_WINDOWS},
    )


@dataclass(frozen=True)
class MicrostructureRow:
    """One symbol's microstructure features for one closed 1 second window.

    The state half and the flow half of the row, each load-bearing:

    * ``symbol`` / ``window_start`` — which market, and which second on the 1s
      lattice (:func:`nullius_ingest.book_features._floor_to_second`).  The
      second is *closed* when the row is built: the book facts are the top of
      the book as the second left it, and the OFI windows end at it.
    * ``microprice`` — the size-weighted mid, each side's price weighted by
      the *other* side's resting size, or ``None`` over two best sizes that
      sum to zero.  A heavy ask says fair value sits lower, so the microprice
      leans toward the bid — that lean is the information the plain mid
      throws away.
    * ``spread`` — ``best_ask - best_bid``, the plain state of the top.
    * ``best_bid`` / ``best_ask`` / ``best_bid_quantity`` /
      ``best_ask_quantity`` — the four facts the two features were computed
      from, kept so a reader recomputes the microprice rather than trusting a
      number whose weights are lost — the same reason feature 20 carries its
      reference price.
    * ``ofi`` — the order-flow imbalance over each window in
      :data:`OFI_WINDOWS`, as ``{seconds: Decimal}``.  ``None`` for a window
      that reaches before the symbol's first observed second: a partial
      window is not a measurement, and the row says so rather than
      under-reporting as though it were whole.  A covered window with no
      events is an exact ``0``.

    Every computed value is a :class:`~decimal.Decimal` in memory, so a
    consumer sums and compares them without re-parsing and a test asserts on
    the number rather than a spelling.  They are rendered as canonical
    strings only in :meth:`canonical` — the persisted form the content hash
    is taken over — so the persisted row is the feature value, not a float
    that could drift on a re-render.
    """

    symbol: str
    window_start: datetime
    microprice: Decimal | None
    spread: Decimal
    best_bid: Decimal
    best_ask: Decimal
    best_bid_quantity: Decimal
    best_ask_quantity: Decimal
    ofi: Mapping[int, Decimal | None]

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise MicrostructureParseError(
                f"a microstructure row must carry a non-empty symbol, got "
                f"{self.symbol!r}"
            )
        if not isinstance(self.window_start, datetime):
            raise MicrostructureParseError(
                f"a microstructure row's window_start must be a datetime, got "
                f"{type(self.window_start).__name__}"
            )
        if self.window_start.tzinfo is None or self.window_start.tzinfo.utcoffset(
            self.window_start
        ) is None:
            raise MicrostructureParseError(
                f"a microstructure row's window_start must be timezone-aware; "
                f"the 1s grid needs an offset to floor against"
            )
        object.__setattr__(self, "window_start", _floor_to_second(self.window_start))
        for name, value in (
            ("spread", self.spread),
            ("best_bid", self.best_bid),
            ("best_ask", self.best_ask),
            ("best_bid_quantity", self.best_bid_quantity),
            ("best_ask_quantity", self.best_ask_quantity),
        ):
            if not isinstance(value, Decimal):
                raise MicrostructureParseError(
                    f"{self.symbol} {name} must be a Decimal, got "
                    f"{type(value).__name__}"
                )
        for name, quantity in (
            ("best_bid_quantity", self.best_bid_quantity),
            ("best_ask_quantity", self.best_ask_quantity),
        ):
            if quantity < 0:
                raise MicrostructureParseError(
                    f"{self.symbol} {name} is negative; a resting size is "
                    f"never below zero"
                )
        if self.microprice is not None and not isinstance(self.microprice, Decimal):
            raise MicrostructureParseError(
                f"{self.symbol} microprice must be a Decimal or None, got "
                f"{type(self.microprice).__name__}"
            )
        # The microprice's honest-absence rule, pinned on the row itself: the
        # weighted mid divides by the two best sizes' total, so a total of
        # zero has no microprice (``None``, not a defaulted price), and a
        # positive total always does.  A row carrying the reverse is a
        # partially-filled feature claim.
        total = self.best_bid_quantity + self.best_ask_quantity
        if (total == 0) != (self.microprice is None):
            raise MicrostructureParseError(
                f"{self.symbol} carries microprice={self.microprice!r} over "
                f"best sizes totalling {_canonical_decimal(total)}; the "
                f"weighted mid exists exactly when the total is not zero"
            )
        keys = tuple(self.ofi)
        if keys != OFI_WINDOWS:
            raise MicrostructureParseError(
                f"{self.symbol} ofi must carry exactly the windows "
                f"{OFI_WINDOWS}, got {keys}"
            )
        for seconds, value in self.ofi.items():
            if value is not None and not isinstance(value, Decimal):
                raise MicrostructureParseError(
                    f"{self.symbol} ofi over {seconds}s must be a Decimal or "
                    f"None, got {type(value).__name__}"
                )

    def ofi_at(self, seconds: int) -> Decimal | None:
        """This row's OFI over the ``seconds`` window.

        ``None`` for a window that reaches before the symbol's first observed
        second — the honest partial-window absence, unmistakable for the
        value zero.
        """
        if seconds not in self.ofi:
            raise KeyError(f"{seconds}s is not one of {OFI_WINDOWS}")
        return self.ofi[seconds]

    def canonical(self) -> dict[str, object]:
        """This row's canonical mapping — the form the content hash is over.

        The OFI windows are ordered by length and keys sorted, so two rows
        describing the same second agree on their hash.  Computed values are
        canonical decimal strings; ``None`` — an absent microprice, an
        uncovered window — is persisted as JSON ``null`` rather than a
        sentinel string, so an absence is unmistakable for the value zero.
        """
        return {
            "symbol": self.symbol,
            "window_start": self.window_start.isoformat(),
            "microprice": (
                None
                if self.microprice is None
                else _canonical_decimal(self.microprice)
            ),
            "spread": _canonical_decimal(self.spread),
            "best_bid": _canonical_decimal(self.best_bid),
            "best_ask": _canonical_decimal(self.best_ask),
            "best_bid_quantity": _canonical_decimal(self.best_bid_quantity),
            "best_ask_quantity": _canonical_decimal(self.best_ask_quantity),
            "ofi": {
                str(seconds): (
                    None if self.ofi[seconds] is None else _canonical_decimal(
                        self.ofi[seconds]
                    )
                )
                for seconds in OFI_WINDOWS
            },
        }


@dataclass(frozen=True)
class MicrostructureBatch:
    """One cycle's derived output: the rows, the closing state, the frontier.

    A batch is what a worker cycle produces and persists.  It carries four
    things, each of which makes the reduction resumable:

    * ``rows`` — the derived 1s rows this cycle emitted, one per (symbol,
      closed second) that carried a diff and left a two-sided book.
    * ``closing_books`` / ``closing_flows`` — the reconstructed book and the
      flow ledger per symbol at the *end* of the span.  These are the states
      the next cycle seeds from and a restart resumes from; they are why the
      derived store, not the 90-day raw store, is the permanent home of both
      the book and the windows.
    * ``from_window`` / ``to_window`` — the 1s bounds this cycle covered;
      ``to_window`` is the resume point a reader skips snapshots up to.
    * ``from_raw_sequence`` / ``to_raw_sequence`` — the raw-log bounds; the
      next cycle consumes only raw records past ``to_raw_sequence``, so no
      diff is folded twice.

    A batch with no rows but an advanced frontier is still a batch — the book
    moved even if no second closed two-sided — and is persisted so the
    frontier and the closing state advance.  A batch that neither emits a row
    nor advances the frontier is refused: an empty cycle is not a record.
    """

    rows: Sequence[MicrostructureRow]
    closing_books: Mapping[str, BookState]
    closing_flows: Mapping[str, OfiTrail]
    from_window: datetime | None
    to_window: datetime | None
    from_raw_sequence: int
    to_raw_sequence: int

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        for row in rows:
            if not isinstance(row, MicrostructureRow):
                raise MicrostructureParseError(
                    "a microstructure batch's rows must be MicrostructureRow "
                    f"instances, got {type(row).__name__}"
                )
        object.__setattr__(self, "rows", rows)
        closing = dict(self.closing_books)
        for symbol, state in closing.items():
            if not isinstance(state, BookState):
                raise MicrostructureParseError(
                    f"closing_books[{symbol!r}] must be a BookState, got "
                    f"{type(state).__name__}"
                )
        object.__setattr__(self, "closing_books", closing)
        flows = dict(self.closing_flows)
        for symbol, trail in flows.items():
            if not isinstance(trail, OfiTrail):
                raise MicrostructureParseError(
                    f"closing_flows[{symbol!r}] must be an OfiTrail, got "
                    f"{type(trail).__name__}"
                )
        object.__setattr__(self, "closing_flows", flows)
        if not rows and self.to_raw_sequence <= self.from_raw_sequence:
            # No new rows and no advance through the raw log: nothing changed,
            # so there is nothing to persist.  An empty cycle is not a record —
            # the honest no-progress state reports ``sequence=0`` and appends
            # nothing, exactly as a not-due funding cycle does.
            raise MicrostructureParseError(
                "a microstructure batch must carry at least one row or advance "
                "the raw-log frontier; an empty batch is a no-progress cycle, "
                "not a snapshot"
            )
        if self.from_raw_sequence < 0 or self.to_raw_sequence < self.from_raw_sequence:
            raise MicrostructureParseError(
                f"raw-sequence bounds {self.from_raw_sequence}.."
                f"{self.to_raw_sequence} are not a valid span"
            )

    def __len__(self) -> int:
        """How many derived rows this batch carries."""
        return len(self.rows)

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this batch emitted rows for, in the batch's order."""
        seen: dict[str, None] = {}
        for row in self.rows:
            seen.setdefault(row.symbol, None)
        return tuple(seen)

    def rows_for(self, symbol: str) -> tuple[MicrostructureRow, ...]:
        """This batch's rows for ``symbol``, in the batch's order."""
        return tuple(row for row in self.rows if row.symbol == symbol)

    def canonical_bytes(self) -> bytes:
        """The batch's canonical JSON bytes — the thing content-hashed.

        Canonical means rows in a deterministic order (window, then symbol),
        closing books and closing flows in symbol order, keys sorted and the
        tightest separators — so two cycles producing the same features and
        closing state hash identically whatever order the symbols were folded
        in.  This is what makes :attr:`MicrostructureRecord.source_sha256` a
        *content* hash.
        """
        document = {
            _DOCUMENT_KEY: [row.canonical() for row in sorted(self.rows, key=_row_sort)],
            _CLOSING_KEY: {
                symbol: self.closing_books[symbol].snapshot()
                for symbol in sorted(self.closing_books)
            },
            _FLOWS_KEY: {
                symbol: self.closing_flows[symbol].snapshot()
                for symbol in sorted(self.closing_flows)
            },
            "from_window": self.from_window.isoformat() if self.from_window else None,
            "to_window": self.to_window.isoformat() if self.to_window else None,
            "from_raw_sequence": self.from_raw_sequence,
            "to_raw_sequence": self.to_raw_sequence,
        }
        return json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    @property
    def source_sha256(self) -> str:
        """The sha256 of :meth:`canonical_bytes` — the batch's identity."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _row_sort(row: MicrostructureRow) -> tuple[datetime, str]:
    return (row.window_start, row.symbol)


def parse_microstructure(batch: object) -> MicrostructureBatch:
    """Validate an already-built :class:`MicrostructureBatch`.

    This module's rows are computed, not parsed from a venue payload, so the
    "parse" here is the gate a persisted record's rows pass back through on
    read: a :class:`MicrostructureBatch` is returned unchanged, and anything
    else is refused, so a damaged document never rebuilds into a feature.
    """
    if not isinstance(batch, MicrostructureBatch):
        raise MicrostructureParseError(
            f"a microstructure batch must be a MicrostructureBatch, got "
            f"{type(batch).__name__}"
        )
    return batch


class MicrostructureStore:
    """The append-only log of derived 1s microstructure features, under staging.

    Records live at ``<lake>/staging/microstructure/<sequence>.bin``, one file
    per cycle, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a record is written
    once, atomically (temp file, ``fsync``, ``rename``), and never rewritten:
    the underlying batch store refuses a second batch at a sequence it already
    holds.  This is §4.1's derived-feature tier, in the same append-only area
    as every other stream, so the seal copies it the same way and — like the
    funding and exchangeInfo logs — nothing in the system ever expires it.
    That permanence is the point: the raw diffs these rows are derived from
    are 90-day-retained and then gone, and the 60 s OFI windows reach further
    back than that, so the derived log must outlive them — and it does because
    each record carries its own closing book and flow trail rather than
    depending on the raw store.

    Construction reads whatever a prior run left on disk, so a restarted
    process knows the last closing state and the frontier it reached without
    a network call — the same seed-from-what-is-durable moment the resume
    watermark gives a restarted worker.  The store reads no clock:
    ``computed_at`` is a parameter, driven by the worker's injected clock
    (§12).
    """

    def __init__(self, staging: StagingArea) -> None:
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"the microstructure store writes into a StagingArea, got "
                f"{type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "MicrostructureStore":
        """The store over the lake's staging area, resolved from the environment.

        The same resolution every ingest store uses (``LAKE_ROOT``, defaulting
        to ``lake/`` beside the workspace root), so records are written into
        the very area the seal copies out of — there is no second root that
        could drift from the first.
        """
        return cls(StagingArea.from_env(env))

    # -- Paths ----------------------------------------------------------------

    @property
    def staging(self) -> StagingArea:
        """The append-only area the records are committed into."""
        return self._staging

    @property
    def root(self) -> Path:
        """The directory holding this stream's record files."""
        return self._staging.path_for(MICROSTRUCTURE_STREAM)

    def path_for(self, sequence: int) -> Path:
        """The file sequence ``sequence`` is committed to."""
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise TypeError(f"a sequence is an integer, not {type(sequence).__name__}")
        if sequence <= 0:
            raise ValueError(f"a sequence must be positive, got {sequence}")
        return self.root / f"{sequence}.bin"

    # -- Recording ------------------------------------------------------------

    def record(
        self, batch: MicrostructureBatch, *, computed_at: datetime
    ) -> "MicrostructureRecord":
        """Persist one cycle as the next record; never overwrite a prior one.

        The batch is validated *first*, so a malformed batch consumes no
        sequence number and leaves the log untouched; then it is written as
        the next record — ``current + 1`` — into the stream's append-only
        staging log.  The previous records are not read, moved or rewritten:
        adding a record is an append, and the store's duplicate-sequence
        refusal means this method has no code path that could overwrite one.

        ``computed_at`` is required and must be timezone-aware: it is the
        instant the cycle ran, stamped on the record, and a naive timestamp
        would make the record's own provenance unanswerable.  The store does
        not read a clock of its own — the worker that ran the cycle owns the
        time.
        """
        parsed = parse_microstructure(batch)
        if not isinstance(computed_at, datetime) or computed_at.tzinfo is None or (
            computed_at.tzinfo.utcoffset(computed_at) is None
        ):
            raise ValueError(
                "computed_at must be a timezone-aware datetime; the record's "
                "provenance needs a comparable instant"
            )

        sequence = self._staging.current(MICROSTRUCTURE_STREAM) + 1
        envelope = {
            "stream": str(MICROSTRUCTURE_STREAM),
            "sequence": sequence,
            "computed_at": computed_at.astimezone(timezone.utc).isoformat(),
            "source_sha256": parsed.source_sha256,
            "from_window": parsed.from_window.isoformat() if parsed.from_window else None,
            "to_window": parsed.to_window.isoformat() if parsed.to_window else None,
            "from_raw_sequence": parsed.from_raw_sequence,
            "to_raw_sequence": parsed.to_raw_sequence,
            _CLOSING_KEY: {
                symbol: parsed.closing_books[symbol].snapshot()
                for symbol in sorted(parsed.closing_books)
            },
            _FLOWS_KEY: {
                symbol: parsed.closing_flows[symbol].snapshot()
                for symbol in sorted(parsed.closing_flows)
            },
            _DOCUMENT_KEY: [
                row.canonical() for row in sorted(parsed.rows, key=_row_sort)
            ],
        }
        payload = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        batch_ = self._staging.append(
            MICROSTRUCTURE_STREAM, payload=payload, rows=len(parsed)
        )
        return MicrostructureRecord(
            sequence=batch_.sequence,
            computed_at=computed_at.astimezone(timezone.utc),
            batch=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            path=batch_.path,
        )

    # -- Reading --------------------------------------------------------------

    def records(self) -> tuple["MicrostructureRecord", ...]:
        """Every persisted record, oldest first.

        Read back from the staging log in ascending sequence order, each
        envelope verified against the sequence its filename claims and the
        document hash it recorded — so a reader gets either the record that
        was committed or a clear :class:`MicrostructureCorruptError`, never a
        plausible-looking feature assembled from damaged bytes.
        """
        return tuple(
            self._read(batch) for batch in self._staging.staged(MICROSTRUCTURE_STREAM)
        )

    def current(self) -> "MicrostructureRecord | None":
        """The most recent record, or ``None`` when nothing has been persisted."""
        batches = self._staging.staged(MICROSTRUCTURE_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def last_record(self) -> "MicrostructureRecord | None":
        """The most recent record — the seed a resumed worker starts from.

        A convenience over :meth:`current` for the worker, which needs the
        whole record (its closing state and its frontier) rather than just
        knowing one exists.  ``None`` on the first cycle, when the worker
        seeds from an empty book and an empty trail.
        """
        return self.current()

    def last_window(self) -> datetime | None:
        """The last 1s boundary this store computed, or ``None`` on an empty log.

        The resume frontier: a reader skips snapshots at or before this, so a
        restarted worker does not re-emit a second it already emitted.
        """
        record = self.current()
        return None if record is None else record.to_window

    def windows(self) -> tuple[datetime, ...]:
        """The 1s windows the retained records touch, ascending."""
        seen: dict[datetime, None] = {}
        for record in self.records():
            for row in record.batch.rows:
                seen.setdefault(row.window_start, None)
        return tuple(sorted(seen))

    def symbols(self) -> tuple[str, ...]:
        """The symbols any retained record carries, in first-seen order."""
        seen: dict[str, None] = {}
        for record in self.records():
            for row in record.batch.rows:
                seen.setdefault(row.symbol, None)
        return tuple(seen)

    def rows_for(
        self, symbol: str, window_start: datetime
    ) -> tuple[MicrostructureRow, ...]:
        """Every retained microstructure row for ``symbol`` at one 1s window.

        Unioned across all records and matched on the aligned window, so a
        caller may pass any instant inside the window it means — the same
        reader seam shape the depth ladder and the trade flow both offer,
        which is what lets a reader join the three derived logs on a second.
        """
        wanted = _floor_to_second(window_start)
        found: list[MicrostructureRow] = []
        for record in self.records():
            found.extend(
                row
                for row in record.batch.rows
                if row.symbol == symbol and row.window_start == wanted
            )
        return tuple(found)

    def _read(self, batch) -> "MicrostructureRecord":
        # Read one committed batch back into a record, verifying as it goes.  The
        # checks are the read half of the append-only guarantee: the bytes are
        # the bytes that were committed, under the sequence the filename claims,
        # carrying the document the envelope's hash vouches for.  A mismatch is
        # corruption (or tampering) on a log the derived features are rebuilt
        # from — and whose closing book and flow trail a restart seeds from — so
        # it is raised rather than papered over.
        try:
            envelope = json.loads(batch.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MicrostructureCorruptError(
                f"microstructure record {batch.sequence} is not readable as a "
                f"JSON envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise MicrostructureCorruptError(
                f"microstructure record {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise MicrostructureCorruptError(
                f"microstructure record {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"record envelope this store wrote"
            )
        recorded = envelope["sequence"]
        if recorded != batch.sequence:
            raise MicrostructureCorruptError(
                f"microstructure record file {batch.sequence}.bin records "
                f"sequence {recorded!r}; the file does not describe itself"
            )
        document = _read_document(envelope[_DOCUMENT_KEY], batch.sequence)
        closing = _read_closing(envelope.get(_CLOSING_KEY, {}), batch.sequence)
        flows = _read_flows(envelope.get(_FLOWS_KEY, {}), batch.sequence)
        recorded_hash = envelope["source_sha256"]
        rebuilt = MicrostructureBatch(
            rows=document,
            closing_books=closing,
            closing_flows=flows,
            from_window=_parse_optional_timestamp(
                envelope.get("from_window"), batch.sequence
            ),
            to_window=_parse_optional_timestamp(
                envelope.get("to_window"), batch.sequence
            ),
            from_raw_sequence=int(envelope["from_raw_sequence"]),
            to_raw_sequence=int(envelope["to_raw_sequence"]),
        )
        if recorded_hash != rebuilt.source_sha256:
            raise MicrostructureCorruptError(
                f"microstructure record {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{rebuilt.source_sha256!r}; the file's bytes are not the "
                f"bytes that were committed"
            )
        return MicrostructureRecord(
            sequence=batch.sequence,
            computed_at=_parse_timestamp(envelope["computed_at"], batch.sequence),
            batch=rebuilt,
            source_sha256=rebuilt.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


@dataclass(frozen=True)
class MicrostructureRecord:
    """One persisted cycle: the sequence it landed under and the rows it carried.

    ``sequence`` is the record's position in the stream's append-only log and,
    because the log is feature 28's staging area, the sequence of the batch the
    envelope bytes were committed as.  ``computed_at`` is when *we* ran the
    cycle (UTC, timezone-aware), kept apart from the rows' ``window_start``,
    which is when the book was observed: conflating them would let our own
    ingest lag decide which second a feature belongs to.

    Two hashes, deliberately distinct, exactly as funding's and the other
    derived records carry them: ``source_sha256`` is over the *document* and
    answers "did the features change?"; ``payload_sha256`` is over the *bytes
    written* and is the file's identity, the same value the seal's MANIFEST
    will record for it.  ``path`` names the ``<sequence>.bin`` the bytes were
    committed to.
    """

    sequence: int
    computed_at: datetime
    batch: MicrostructureBatch
    source_sha256: str
    payload_sha256: str
    path: Path

    @property
    def row_count(self) -> int:
        """How many derived rows this record carries."""
        return len(self.batch.rows)

    @property
    def to_raw_sequence(self) -> int:
        """The raw-log frontier this record reached — the resume point."""
        return self.batch.to_raw_sequence

    @property
    def to_window(self) -> datetime | None:
        """The last 1s boundary this record computed — the snapshot resume point."""
        return self.batch.to_window

    def closing_book(self, symbol: str) -> BookState | None:
        """This record's reconstructed book for ``symbol`` at the span's end.

        The state a restarted worker seeds from: the book after every diff
        this record consumed, so the reconstruction resumes without
        re-deriving from raw diffs that may since have left the 90-day
        window.  ``None`` when the record never saw the symbol.
        """
        return self.batch.closing_books.get(symbol)

    def closing_flow(self, symbol: str) -> OfiTrail | None:
        """This record's flow trail for ``symbol`` at the span's end.

        The other half of the resume seed: the per-second increments a future
        cycle's windows still need, and the first second the symbol was ever
        observed.  ``None`` when the record never saw the symbol.
        """
        return self.batch.closing_flows.get(symbol)


def _read_document(entries: object, sequence: int) -> tuple[MicrostructureRow, ...]:
    # Read a persisted document back into rows, restoring ``None`` where the
    # envelope wrote JSON ``null``.  A document that is not a list of
    # well-formed rows is corruption, not data.
    if not isinstance(entries, list):
        raise MicrostructureCorruptError(
            f"microstructure record {sequence} has a document that is not a "
            f"list of rows"
        )
    rows: list[MicrostructureRow] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise MicrostructureCorruptError(
                f"microstructure record {sequence} has a row that is not an "
                f"object"
            )
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise MicrostructureCorruptError(
                f"microstructure record {sequence} has a row with no "
                f"non-empty symbol"
            )
        try:
            rows.append(
                MicrostructureRow(
                    symbol=symbol,
                    window_start=_parse_timestamp(
                        entry.get("window_start"), sequence
                    ),
                    microprice=_optional_decimal(
                        entry.get("microprice"), symbol, "microprice", sequence
                    ),
                    spread=Decimal(entry["spread"]),
                    best_bid=Decimal(entry["best_bid"]),
                    best_ask=Decimal(entry["best_ask"]),
                    best_bid_quantity=Decimal(entry["best_bid_quantity"]),
                    best_ask_quantity=Decimal(entry["best_ask_quantity"]),
                    ofi={
                        seconds: _optional_decimal(
                            entry["ofi"][str(seconds)],
                            symbol,
                            f"ofi over {seconds}s",
                            sequence,
                        )
                        for seconds in OFI_WINDOWS
                    },
                )
            )
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise MicrostructureCorruptError(
                f"microstructure record {sequence} carries a row this module "
                f"cannot read back: {exc}"
            ) from exc
    return tuple(rows)


def _optional_decimal(
    raw: object, symbol: str, name: str, sequence: int
) -> Decimal | None:
    # ``null`` in the envelope means the feature was honestly absent, not
    # zero — the distinction the microprice's degenerate case and the
    # uncovered OFI windows stand on, so it is restored as ``None`` rather
    # than defaulted into a number.
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MicrostructureCorruptError(
            f"microstructure record {sequence} records {symbol} {name}={raw!r}, "
            f"which is neither null nor a decimal: {exc}"
        ) from exc


def _read_closing(entries: object, sequence: int) -> dict[str, BookState]:
    # Read the persisted closing books back into BookState objects — half the
    # resume seed.  A closing book that is not a well-formed snapshot is
    # corruption: a damaged seed would reconstruct a book the market never
    # had.
    if not isinstance(entries, Mapping):
        raise MicrostructureCorruptError(
            f"microstructure record {sequence} has closing books that are not "
            f"an object"
        )
    closing: dict[str, BookState] = {}
    for symbol, snap in entries.items():
        if not isinstance(snap, Mapping) or "bids" not in snap or "asks" not in snap:
            raise MicrostructureCorruptError(
                f"microstructure record {sequence} has a closing book for "
                f"{symbol!r} that is not a snapshot"
            )
        closing[symbol] = BookState.from_snapshot(snap)
    return closing


def _read_flows(entries: object, sequence: int) -> dict[str, OfiTrail]:
    # Read the persisted closing trails back into OfiTrail objects — the
    # other half of the resume seed.  A trail that is not a well-formed
    # snapshot is corruption: a damaged trail would measure a restarted
    # worker's windows from flow the market never had, which is worse than
    # the damage being visible, because the windows would still look whole.
    if not isinstance(entries, Mapping):
        raise MicrostructureCorruptError(
            f"microstructure record {sequence} has closing flows that are not "
            f"an object"
        )
    flows: dict[str, OfiTrail] = {}
    for symbol, snap in entries.items():
        try:
            flows[symbol] = OfiTrail.from_snapshot(snap)
        except MicrostructureParseError as exc:
            raise MicrostructureCorruptError(
                f"microstructure record {sequence} has a closing flow for "
                f"{symbol!r} that is not a trail snapshot: {exc}"
            ) from exc
    return flows


def _parse_optional_timestamp(raw: object, sequence: int) -> datetime | None:
    if raw is None:
        return None
    return _parse_timestamp(raw, sequence)


def _parse_timestamp(raw: object, sequence: int) -> datetime:
    if not isinstance(raw, str):
        raise MicrostructureCorruptError(
            f"microstructure record {sequence} records a timestamp {raw!r}; "
            f"expected an ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise MicrostructureCorruptError(
            f"microstructure record {sequence} records an unparseable "
            f"timestamp {raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise MicrostructureCorruptError(
            f"microstructure record {sequence} records a naive timestamp; the "
            f"grid and the provenance need a comparable instant"
        )
    return parsed.astimezone(timezone.utc)


class MicrostructureWorker:
    """The microstructure worker: reconstruct the book, close each second.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the
    ``microstructure`` stream class, so the supervisor of feature 16 runs it
    on its own thread alongside every other stream and converts whatever it
    raises into that stream's own failure.  Like feature 20's worker it owns
    no venue fetch: its input is the *internal* raw-diff store feature 19
    persisted, so there is no unconfigured-fetch path at all — an empty raw
    store simply yields empty cycles.

    One cycle is a stateful reduction over the raw-diff log, in four steps:

    * **Seed.**  Read the last microstructure record.  Its closing books and
      closing trails are the running state; its ``to_window`` and
      ``to_raw_sequence`` are the frontier.  On the first cycle the book is
      empty, the trail is empty, and the frontier is zero.
    * **Consume.**  Read the raw records feature 19 persisted past the
      frontier.  Each row moves the book from one top-of-book state to the
      next, and the increment between them is folded into the symbol's trail
      at the row's 1s bucket — classified, measured and folded in the venue's
      time order.  Only raw records past ``to_raw_sequence`` are consumed, so
      no diff is folded twice.
    * **Close.**  A symbol's open second closes the moment a *later* second's
      first row arrives, or at the end of the pass: the row is built from the
      book as the second left it and the trail's windows ending at it, so the
      windows on a row compose exactly.  A second at or before the frontier
      window never re-opens — its snapshot is committed, and a late diff for
      it folds into the going-forward book and trail without amending the
      log.
    * **Persist.**  Append one record carrying the derived rows, the closing
      books and the pruned closing trails, advancing the frontier.  The
      closing state is the permanent home of the reconstruction *and* the
      windows, so the next cycle — or a restart after the raw window has
      slid — resumes from it rather than re-deriving from raw diffs.

    A cycle that consumes no new raw records appends nothing and reports
    ``sequence=0, rows_written=0`` — the honest no-progress cycle, matching a
    not-due funding cycle.  A cycle that consumes new raw records but closes
    no two-sided second still persists (its book moved), with
    ``rows_written`` counting the new rows, which may be zero.

    The clock is injected because ``computed_at`` is a fact about elapsed
    wall-clock time: a test must be able to place the worker without touching
    the wall clock, and §12 keeps wall-clock reads out of checked code.  The
    default clock reads the system UTC time.
    """

    def __init__(
        self,
        store: MicrostructureStore,
        diff_store: BookDiffStore,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, MicrostructureStore):
            raise TypeError(
                f"the microstructure worker persists into a "
                f"MicrostructureStore, got {type(store).__name__}"
            )
        if not isinstance(diff_store, BookDiffStore):
            raise TypeError(
                f"the microstructure worker reads from a BookDiffStore, got "
                f"{type(diff_store).__name__}"
            )
        if clock is not None and not callable(clock):
            raise TypeError(
                f"clock must be a callable returning a datetime, got "
                f"{type(clock).__name__}"
            )
        self._store = store
        self._diff_store = diff_store
        self._clock = clock if clock is not None else _utc_now

    # -- IngestWorker ---------------------------------------------------------

    @property
    def stream_class(self) -> StreamClass:
        """The one stream class this worker owns — ``microstructure``."""
        return MICROSTRUCTURE_STREAM

    @property
    def store(self) -> MicrostructureStore:
        """The derived-feature log this worker appends to."""
        return self._store

    @property
    def diff_store(self) -> BookDiffStore:
        """The raw-diff store this worker reconstructs the book from."""
        return self._diff_store

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Reconstruct the book from new raw diffs and persist the closed seconds.

        Returns the persisted record's sequence as the cycle's watermark — the
        frontier a restarted worker resumes past — and ``rows_written`` as the
        number of derived rows the record carries.  A no-new-data cycle
        reports both as zero and appends nothing.
        """
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
            raise ValueError("the clock must return a timezone-aware datetime")

        last = self._store.last_record()
        books: dict[str, BookState]
        trails: dict[str, OfiTrail]
        frontier_window: datetime | None
        frontier_seq: int
        if last is None:
            books = {}
            trails = {}
            frontier_window = None
            frontier_seq = 0
        else:
            books = dict(last.batch.closing_books)
            trails = dict(last.batch.closing_flows)
            frontier_window = last.to_window
            frontier_seq = last.to_raw_sequence

        rows: list[MicrostructureRow] = []
        # The second each symbol currently has open — the one being folded and
        # not yet snapshotted — and the seconds this cycle has already closed.
        # A second closes when a later second's first row arrives or the pass
        # ends, and a closed second never re-opens: the windows a row names
        # must be whole, and a committed row is never amended.
        open_bucket: dict[str, datetime] = {}
        closed: set[tuple[str, datetime]] = set()

        def close(symbol: str, bucket: datetime) -> None:
            if frontier_window is not None and bucket <= frontier_window:
                return  # already committed by a prior record
            if (symbol, bucket) in closed:
                return  # this second already closed
            closed.add((symbol, bucket))
            row = _microstructure_row(symbol, bucket, books[symbol], trails[symbol])
            if row is not None:
                rows.append(row)

        # Consume the raw records past the frontier in one pass.  For each row
        # the increment is measured around the fold — the top of the book
        # before and after the row — because the flow between two states is
        # only answerable about the states themselves.  A late diff for an
        # already-committed second still folds: it updates the going-forward
        # book and the going-forward trail, never the committed snapshot.
        from_raw_sequence = frontier_seq
        to_window = frontier_window
        for record in self._diff_store.records():
            if record.sequence <= frontier_seq:
                continue
            for row in record.batch.rows:
                book = books.setdefault(row.symbol, BookState())
                trail = trails.setdefault(row.symbol, OfiTrail())
                bucket = _floor_to_second(row.window_start)
                current = open_bucket.get(row.symbol)
                if current is None:
                    if frontier_window is None or bucket > frontier_window:
                        # A new, uncommitted second opens and will close when a
                        # later second arrives or the pass ends.
                        open_bucket[row.symbol] = bucket
                elif bucket > current:
                    # The first row of a later second: the open second is whole.
                    close(row.symbol, current)
                    open_bucket[row.symbol] = bucket
                before = TopOfBook.from_book(book)
                book.apply(row)
                after = TopOfBook.from_book(book)
                trail.observe(bucket, ofi_increment(before, after))
                if to_window is None or bucket > to_window:
                    to_window = bucket
            frontier_seq = record.sequence

        # The pass has ended, so each symbol's trailing second is whole: close
        # it, then retire the buckets no future window can reach.
        for symbol, bucket in open_bucket.items():
            close(symbol, bucket)

        if frontier_seq == from_raw_sequence and to_window == frontier_window:
            # Nothing was consumed and no new second was crossed, so there is
            # nothing to persist: the frontier and the closing state are
            # exactly what the last record already carries.  The honest
            # no-progress cycle reports both zero and appends nothing — the
            # same shape a not-due funding cycle has.  This covers the first
            # cycle over an entirely empty raw store too, where
            # ``frontier_seq`` is ``0`` and ``to_window`` is ``None`` by
            # definition.
            return CycleResult(rows_written=0, sequence=0)

        if to_window is not None:
            # Every window a future row can name ends at a second past
            # ``to_window``, so it starts at or after ``to_window`` minus the
            # widest window; a bucket older than that (with a slice of margin)
            # is unreachable, and carrying it forward would grow the trail
            # without bound.  ``first_window`` survives in the trail itself.
            keep_from = to_window - MAX_OFI_WINDOW + FEATURE_SLICE
            for trail in trails.values():
                trail.prune(keep_from)

        batch = MicrostructureBatch(
            rows=rows,
            closing_books=books,
            closing_flows=trails,
            from_window=frontier_window,
            to_window=to_window,
            from_raw_sequence=from_raw_sequence,
            to_raw_sequence=frontier_seq,
        )
        record = self._store.record(batch, computed_at=now)
        return CycleResult(rows_written=record.row_count, sequence=record.sequence)


def _utc_now() -> datetime:
    """The default clock: the current UTC time, timezone-aware."""
    return datetime.now(timezone.utc)


def register_microstructure_worker(
    store: Optional[MicrostructureStore] = None,
    diff_store: Optional[BookDiffStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], MicrostructureWorker]:
    """Register a worker factory bound to explicitly wired stores.

    The operator path: hand in the derived-feature store and the raw-diff
    store (when they are not the lake's staging area), and this registers a
    worker factory bound to those collaborators.  Registration replaces the
    auto-discovered factory of the same class in the registry it targets —
    the registry's own rule, *a re-registered class is a revision of the same
    worker, never a second worker* — so a deployment that wires stores does
    not end up with two microstructure workers competing for the same
    sequence numbers.

    ``registry`` defaults to a **private** registry, not the process-wide one:
    a registration is a deployment act, and silently replacing the
    auto-discovered worker for every later composition in the process would
    hand unrelated callers — tests especially — a worker bound to stores that
    may since have vanished.  A caller that means to reconfigure the running
    process passes :func:`~nullius_ingest.registry.default_worker_registry`
    explicitly, matching :func:`~nullius_ingest.registry.register_worker`.

    Returns the registered factory, so a caller can build the worker it just
    registered — over the private registry by default — without reaching back
    into it.
    """
    if clock is not None and not callable(clock):
        raise TypeError(
            f"clock must be a callable returning a datetime, got "
            f"{type(clock).__name__}"
        )

    def build() -> MicrostructureWorker:
        resolved_store = (
            store if store is not None else MicrostructureStore.from_env()
        )
        resolved_diff = diff_store if diff_store is not None else BookDiffStore.from_env()
        return MicrostructureWorker(resolved_store, resolved_diff, clock=clock)

    # Register through a private registry by default, never the process-wide
    # one.  Registration is a *deployment* act: writing a caller's wiring into
    # the default registry would replace the auto-discovered worker for every
    # later composition in the process — including tests, which would then be
    # handed a worker bound to stores that have since been deleted.  A caller
    # that genuinely means to reconfigure the running process passes the
    # default registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        MICROSTRUCTURE_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(MICROSTRUCTURE_STREAM)
def build_microstructure_worker() -> MicrostructureWorker:
    """Compose the microstructure worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    Collaborators come from the environment the way every other ingest store
    does: both stores are the lake's staging area (:meth:`from_env`), so the
    derived features land in the very area the seal copies out of, and the
    book is reconstructed from the raw diffs feature 19 persisted into that
    same area.  The worker needs no injected fetch — its input is the
    internal raw-diff store, exactly like the depth ladder's worker — so it
    composes fully configured and runs its first cycle the moment the
    supervisor does.
    """
    return MicrostructureWorker(
        MicrostructureStore.from_env(), BookDiffStore.from_env()
    )
