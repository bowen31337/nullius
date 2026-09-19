"""Derived book features at 1 second resolution, computed from the L2 diffs.

app_spec.xml feature 20 states the behaviour: *"System computes derived book
features at 1 second resolution from L2 diffs, persisting depth at 5, 10, 25
and 50 bps per side."*  docs/nullius-tech-architecture.md §4.1 fixes why this
tier exists at all, in the L2 retention row — raw diffs are kept for a rolling
90 days *"…and permanently persist derived book features at 1s resolution"* —
and then states the trade that makes the derived tier load-bearing:

    **The L2 retention decision is load-bearing.**  Raw diff streams for a
    100-symbol universe run roughly 50–200 GB/month uncompressed.  Storing them
    forever is a self-inflicted infrastructure problem.  Instead: keep raw diffs
    for a rolling 90 days so feature definitions can be revised and backfilled
    recently, and permanently persist derived book features at 1s resolution.

Feature 19 built the raw-diff stream and its 90-day window; this module is the
*derived* tier that window exists to enable.  It reads the raw rows feature 19
persisted — through the very reader seam that module's plan built for this one,
:meth:`~nullius_ingest.book_diffs.BookDiffStore.rows_in_window` and, more
directly, :meth:`~nullius_ingest.book_diffs.BookDiffStore.records` — and turns
them into a permanent 1s book-feature log.

Three pieces make this different from every stream module before it, and the
difference is the whole point of the feature:

* **Raw diffs are deltas, so the book must be reconstructed.**  A diff carries
  only the levels that changed.  The book at second ``S`` is the cumulative
  effect of *every* diff up to ``S`` — so "depth at 1s resolution" cannot be
  read off one window, it must fold the diffs into a running book and snapshot
  that book at each 1s boundary.  :class:`BookState` is that reconstruction:
  one symbol's price→quantity maps, folded one raw row at a time, where a
  ``quantity`` of ``"0"`` is a level *removal* that deletes the level.  The book
  is carried *across* seconds — a level set in one second and untouched the next
  is still standing — because a snapshot is a state, not a diff.

* **The reconstructed book is persisted, not re-derived.**  This is the
  load-bearing reason the derived tier exists.  Raw diffs are 90-day-retained
  and then gone; a restart after the window has slid could never rebuild the
  current book from the raw store alone.  So each record carries its *closing
  book* — the book state at the end of the span — and the next cycle, or a
  restarted worker, seeds from it.  The derived store is the permanent home of
  the book; the raw diffs are disposable within their window.  This is exactly
  the promise §4.1 makes when it says the derived features let the raw window
  "close without losing the derived history."

* **Depth at N bps is measured off the mid.**  For each 1s snapshot the book's
  mid — ``(best_bid + best_ask) / 2`` off the reconstructed book — is the
  reference, and the quantity resting inside each of the 5/10/25/50 bps bands is
  summed per side.  A second whose book has an empty side has no mid and emits
  no row: an honest absence rather than a defaulted feature.  A second is
  emitted only when at least one raw diff landed in it, so the feature log is
  paced by genuine book changes, not by the worker's cycle cadence.

Layering on feature 19 is deliberate and total: this module reads the raw rows
feature 19 persisted, through feature 19's store, and persists its own output
into the same append-only staging area — ``<lake>/staging/bookFeatures/`` — so
the seal copies it the same way and, like the funding and exchangeInfo logs,
nothing in the system ever expires it.  The persistence shape (record, envelope,
content hash, bytes hash, corrupt-bytes refusal) mirrors
:mod:`nullius_ingest.funding` and :mod:`nullius_ingest.book_diffs` one-for-one;
the genuinely new machinery is the reconstruction and the depth computation, and
both are here rather than in the raw module so feature 19's "raw rows are kept
raw" promise stays intact — the derived tier *derives*, the raw tier does not.

The member stays stdlib-only: the reconstruction and the bps arithmetic are
exact :class:`~decimal.Decimal` maths over the venue's own spellings, and the
worker's input is the *internal* raw-diff store rather than a venue endpoint, so
there is no injected fetch and no unconfigured-fetch path — an empty raw store
simply yields empty cycles.  The clock is injected for the same reason the other
workers inject theirs: ``computed_at`` is a fact about elapsed wall-clock time
and §12 keeps wall-clock reads out of checked code.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Final, Optional, Union

from .book_diffs import BookDiffRecord, BookDiffRow, BookDiffStore
from .registry import WorkerRegistry, register_worker
from .staging import StagingArea
from .streams import StreamClass
from .worker import CycleResult

__all__ = [
    "BPS_THRESHOLDS",
    "BOOK_FEATURES_STREAM",
    "FEATURE_SLICE",
    "FEATURE_SLICE_MILLISECONDS",
    "BookFeatureBatch",
    "BookFeatureCorruptError",
    "BookFeatureError",
    "BookFeatureParseError",
    "BookFeatureRecord",
    "BookFeatureRow",
    "BookFeatureStore",
    "BookFeatureWorker",
    "BookState",
    "build_book_feature_worker",
    "register_book_feature_worker",
]

#: The stream class this module serves.  §4.1's table row for the derived book
#: features is the stream computed from the L2 diffs at 1s resolution, and the
#: spelling here is the persisted one
#: (:class:`~nullius_ingest.streams.StreamClass`), so the staging layout and the
#: record log share it.
BOOK_FEATURES_STREAM = StreamClass.BOOK_FEATURES

#: The resolution this feature is computed at: one derived snapshot per second.
#: Feature 19's raw grid is 100 ms; ten raw windows fall into one feature
#: window.  Carried as constants so the fact is named where it is decided and
#: the grid arithmetic cannot drift from the spec.
FEATURE_SLICE_MILLISECONDS: Final[int] = 1000
FEATURE_SLICE: Final[timedelta] = timedelta(milliseconds=FEATURE_SLICE_MILLISECONDS)

#: The bps bands depth is summed over, per side — the four thresholds feature 20
#: names.  ``t`` bps is ``t / 10000`` as a fraction of the reference price, so a
#: 5 bps band is the levels within 0.05% of the mid.  Kept as an ordered tuple
#: so the row's depth map carries them in a stable, named order.
BPS_THRESHOLDS: Final[tuple[int, ...]] = (5, 10, 25, 50)

#: The epoch, as the exact-integer lattice the 1s grid is floored against.  No
#: float ever touches an instant, so a second boundary is a boundary rather than
#: a rounding.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SLICE_MICROS: Final[int] = FEATURE_SLICE_MILLISECONDS * 1000

#: The envelope keys a record file carries around its rows — named so a reader
#: of a record file (an operator, a seal, a later audit) does not have to import
#: this module to know what it is looking at.  ``rows`` is the document.
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

_ZERO: Final[Decimal] = Decimal(0)
_ONE: Final[Decimal] = Decimal(1)
_TEN_THOUSAND: Final[Decimal] = Decimal(10000)


class BookFeatureError(Exception):
    """Base for every failure this module raises.

    Raised for a batch this module will not persist and for a persisted record
    it will not read: both are cases where the derived book-feature log would
    otherwise start lying about what the book did, so both fail loudly rather
    than being approximated into a row.
    """


class BookFeatureParseError(BookFeatureError):
    """A batch is not one this module will persist.

    Raised *before* anything is written, so a malformed row never consumes a
    sequence number and never appears in the log as a snapshot that happened.
    The message names what was wrong with which row, because the caller is a
    worker deciding whether the reconstruction it produced is sound.
    """


class BookFeatureCorruptError(BookFeatureError):
    """A persisted record file does not match what was written under it.

    Raised when a record file cannot be read back as the envelope it was written
    as, when its recorded sequence is not the sequence its filename claims, or
    when recomputing its document hash disagrees with the hash the envelope
    recorded.  A mismatch means the bytes on disk are not the bytes this module
    committed — corruption or tampering — and a reader that reconstructed a
    feature from them would be reconstructing a book that never existed.  The
    closing book a record carries makes this matter twice over: a damaged
    closing book would seed a restarted worker's reconstruction from a book the
    market never had.
    """


def _floor_to_second(moment: datetime) -> datetime:
    # Floor an aware instant onto the exact 1s lattice: epoch microseconds
    # integer-divided by the slice width, so ``...1200ms`` stays put and
    # ``...1999ms`` floors to ``...1000ms`` — on every platform, because the
    # arithmetic is over whole microseconds and no float is involved.  This is
    # the 1s-resolution lattice a snapshot is placed on, the feature-tier twin
    # of feature 19's 100 ms :func:`~nullius_ingest.book_diffs.align_to_window`.
    if not isinstance(moment, datetime):
        raise TypeError(f"moment must be a datetime, not {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"moment must be timezone-aware; a naive timestamp cannot be "
            f"placed on the 1s grid"
        )
    since_epoch = moment.astimezone(timezone.utc) - _EPOCH
    micros = (
        since_epoch.days * 86_400_000_000
        + since_epoch.seconds * 1_000_000
        + since_epoch.microseconds
    )
    return _EPOCH + timedelta(microseconds=(micros // _SLICE_MICROS) * _SLICE_MICROS)


def _canonical_decimal(value: Decimal) -> str:
    # A derived feature value is rendered in fixed-point, with no exponent
    # notation, so a depth of ``100`` and a reference price of ``100.50`` are
    # stable across Python versions and JSON round-trips — the same reason the
    # raw tier keeps a canonical spelling for its content hash.  Trailing zeros
    # are preserved, so two snapshots that agree on a price agree on its string.
    return format(value, "f")


class BookState:
    """One symbol's reconstructed L2 book: a price→quantity map per side.

    The load-bearing state feature 20 persists.  A book is built empty and
    :meth:`apply`-ed one raw :class:`~nullius_ingest.book_diffs.BookDiffRow` at a
    time — each level sets its price's quantity, and a removal (a ``quantity``
    of ``"0"``) deletes the level — so after a stream of diffs the maps hold the
    book the venue's book is in.  A level set in one second and untouched the
    next is still standing, because the book is a *state* carried across seconds,
    not a diff re-sent each second.

    Prices are kept as the venue's own string spelling (the map key) so a level
    is looked up and compared by the price the venue used; quantities are kept as
    exact :class:`~decimal.Decimal` so the depth sums are exact.  The book is
    reconstructed *from* raw data, so it keeps the raw tier's verbatim-price
    rule; only the accumulated quantity is a computed value, and it is rendered
    canonically when the book is serialized.

    A :class:`BookState` is mutable while it is being folded and is turned into a
    serialisable snapshot with :meth:`snapshot` / :meth:`from_snapshot` — the
    frozen form that travels in a record and seeds a resume.
    """

    def __init__(self) -> None:
        self._bids: dict[str, Decimal] = {}
        self._asks: dict[str, Decimal] = {}

    def apply(self, row: BookDiffRow) -> None:
        """Fold one raw diff row into this book, in the venue's order.

        Each level sets its price's quantity; a removal deletes the price.  The
        fold is order-sensitive within a second (the venue's time order) and the
        book it leaves is the book the venue's diffs describe — which is the
        state a snapshot is taken from.
        """
        for level in row.bids:
            if level.is_removal:
                self._bids.pop(level.price, None)
            else:
                self._bids[level.price] = Decimal(level.quantity)
        for level in row.asks:
            if level.is_removal:
                self._asks.pop(level.price, None)
            else:
                self._asks[level.price] = Decimal(level.quantity)

    def has_both_sides(self) -> bool:
        """Whether the book has at least one level on each side — a mid exists."""
        return bool(self._bids) and bool(self._asks)

    def has_price(self, side: str, price: str) -> bool:
        """Whether ``price`` has a live level on ``side`` right now.

        The read seam feature 22 stands on: classifying a raw level as an *add*
        or an *update* means asking whether the price was already standing
        before the level was folded in, and only the reconstructed book knows.
        Asked by the venue's own string spelling, exactly as the levels are
        keyed, so the question is the one :meth:`apply` answers.

        ``side`` is ``"bids"`` or ``"asks"``; anything else is a wiring bug and
        is refused rather than silently answering about the wrong side.
        """
        if side == "bids":
            return price in self._bids
        if side == "asks":
            return price in self._asks
        raise ValueError(f"a book side is 'bids' or 'asks', got {side!r}")

    def copy(self) -> "BookState":
        """A fresh book with the same levels — the seed a resume starts from.

        The reconstruction seeds from the closing book a prior cycle persisted,
        so the persisted snapshot must become a live, foldable book; a copy keeps
        the seed immutable and the running book free to mutate.
        """
        return BookState.from_snapshot(self.snapshot())

    def best_bid(self) -> Decimal | None:
        """The highest bid price, or ``None`` for an empty bid side."""
        return max((Decimal(price) for price in self._bids), default=None)

    def best_ask(self) -> Decimal | None:
        """The lowest ask price, or ``None`` for an empty ask side."""
        return min((Decimal(price) for price in self._asks), default=None)

    def best_bid_quantity(self) -> Decimal | None:
        """The size resting at the best bid, or ``None`` for an empty bid side.

        The read seam feature 21 stands on: the microprice weights each side's
        price by the *other* side's resting size and the best-level OFI measures
        the change in the best level's size, so the derived tier needs the size
        at the top as a fact, not just the price.  ``None`` exactly when
        :meth:`best_bid` is ``None`` — the pair describes one side, and an empty
        side has neither its price nor its size.
        """
        price = max(self._bids, key=Decimal, default=None)
        return None if price is None else self._bids[price]

    def best_ask_quantity(self) -> Decimal | None:
        """The size resting at the best ask, or ``None`` for an empty ask side.

        The ask-side twin of :meth:`best_bid_quantity` — the weight the bid's
        price carries in the microprice, and the level the ask-side OFI counts.
        ``None`` exactly when :meth:`best_ask` is ``None``.
        """
        price = min(self._asks, key=Decimal, default=None)
        return None if price is None else self._asks[price]

    def mid(self) -> Decimal | None:
        """The mid ``(best_bid + best_ask) / 2``, or ``None`` if a side is empty.

        The reference the depth bands are measured from.  ``None`` when a side is
        empty: a one-sided book has no mid, and a depth measured off a guessed
        reference would be a feature the market never had.
        """
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2

    def depth_within(self, side: str, reference: Decimal, bps: int) -> Decimal:
        """The quantity resting within ``bps`` of ``reference`` on ``side``.

        ``side`` is ``"bids"`` or ``"asks"``.  A bid counts when its price is at
        least ``reference * (1 - bps/10000)``; an ask when its price is at most
        ``reference * (1 + bps/10000)``.  The bands are nested — widening ``bps``
        only ever adds levels — so a 50 bps depth is never below a 25 bps one on
        the same side.  Quantities are summed as exact :class:`~decimal.Decimal`.

        The accumulator is seeded with ``Decimal(0)`` rather than left to
        :func:`sum`'s default: an empty band is the normal state of a wide
        market — a book whose spread exceeds 10 bps has nothing inside its 5 bps
        bands — and a bare ``sum`` over an empty generator returns builtin
        ``int`` 0, which :class:`BookFeatureRow` rightly refuses as a depth.
        The seeding keeps an empty band an exact ``Decimal("0")``, which is a
        measurement ("nothing rests this close"), not an absence.
        """
        if side == "bids":
            levels = self._bids
            threshold = reference * (_TEN_THOUSAND - Decimal(bps)) / _TEN_THOUSAND
            return sum(
                (qty for price, qty in levels.items() if Decimal(price) >= threshold),
                _ZERO,
            )
        if side == "asks":
            levels = self._asks
            threshold = reference * (_TEN_THOUSAND + Decimal(bps)) / _TEN_THOUSAND
            return sum(
                (qty for price, qty in levels.items() if Decimal(price) <= threshold),
                _ZERO,
            )
        raise ValueError(f"a book side is 'bids' or 'asks', got {side!r}")

    def snapshot(self) -> dict[str, list[list[str]]]:
        """This book as a serialisable snapshot: sorted ``[price, quantity]`` pairs.

        Each side is a list of ``[price, quantity]`` pairs sorted by price —
        bids ascending, asks ascending — with the price kept in the venue's
        spelling and the quantity rendered canonically.  The sorted order is the
        human-readable book order and, being deterministic, is what the content
        hash is stable over.
        """
        return {
            "bids": [
                [price, _canonical_decimal(self._bids[price])]
                for price in sorted(self._bids, key=Decimal)
            ],
            "asks": [
                [price, _canonical_decimal(self._asks[price])]
                for price in sorted(self._asks, key=Decimal)
            ],
        }

    @classmethod
    def from_snapshot(cls, snap: Mapping[str, Iterable[Sequence[str]]]) -> "BookState":
        """Rebuild a book from a :meth:`snapshot` — the resume path.

        The inverse of :meth:`snapshot`: the price→quantity pairs are read back
        into the maps, so a restarted worker seeds its reconstruction from the
        closing book a prior run persisted rather than re-deriving it from raw
        diffs that may since have left the 90-day window.
        """
        state = cls()
        for price, quantity in snap.get("bids", ()):
            state._bids[price] = Decimal(quantity)
        for price, quantity in snap.get("asks", ()):
            state._asks[price] = Decimal(quantity)
        return state


def _depth_row(
    symbol: str,
    window_start: datetime,
    book: BookState,
) -> BookFeatureRow | None:
    # Take a snapshot of one book at one 1s boundary: the mid is the reference,
    # each of the four bps bands is summed per side, and the row is the feature.
    # ``None`` when the book has an empty side — a one-sided book has no mid and
    # emits no row, an honest absence rather than a defaulted feature.
    reference = book.mid()
    if reference is None:
        return None
    best_bid = book.best_bid()
    best_ask = book.best_ask()
    assert best_bid is not None and best_ask is not None  # mid() guarded this
    return BookFeatureRow(
        symbol=symbol,
        window_start=window_start,
        reference_price=reference,
        best_bid=best_bid,
        best_ask=best_ask,
        bid_depth={bps: book.depth_within("bids", reference, bps) for bps in BPS_THRESHOLDS},
        ask_depth={bps: book.depth_within("asks", reference, bps) for bps in BPS_THRESHOLDS},
    )


@dataclass(frozen=True)
class BookFeatureRow:
    """One symbol's derived book features for one 1 second window.

    Six facts, each load-bearing:

    * ``symbol`` — which book the features describe.
    * ``window_start`` — the 1s window the snapshot was taken at, floored onto
      the exact 1s lattice by :func:`_floor_to_second`.  This is the row's
      resolution: the book's state at that second's boundary.
    * ``reference_price`` — the mid the depth bands were measured from.  Kept so
      a reader can recompute or sanity-check a band rather than trusting a
      number whose reference is lost.
    * ``best_bid`` / ``best_ask`` — the top of the reconstructed book at the
      snapshot, the two prices the mid was formed from.
    * ``bid_depth`` / ``ask_depth`` — the quantity resting within each of the
      5/10/25/50 bps bands, per side, as ``{bps: canonical-decimal}`` maps.  The
      bands are nested, so each map carries exactly :data:`BPS_THRESHOLDS`.

    The computed values — ``reference_price``, ``best_bid``, ``best_ask`` and the
    two depth maps — are :class:`~decimal.Decimal` in memory, so a downstream
    consumer sums and compares them without re-parsing, and a test can assert on
    the number rather than a spelling.  They are rendered as canonical strings
    only in :meth:`canonical`, the persisted form the content hash is taken over
    — so the persisted row is the feature value, not a float that could drift on
    a re-render, while the in-memory row stays a number.
    """

    symbol: str
    window_start: datetime
    reference_price: Decimal
    best_bid: Decimal
    best_ask: Decimal
    bid_depth: Mapping[int, Decimal]
    ask_depth: Mapping[int, Decimal]

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise BookFeatureParseError(
                f"a book feature must carry a non-empty symbol, got {self.symbol!r}"
            )
        if not isinstance(self.window_start, datetime):
            raise BookFeatureParseError(
                f"a book feature's window_start must be a datetime, "
                f"got {type(self.window_start).__name__}"
            )
        if self.window_start.tzinfo is None or self.window_start.tzinfo.utcoffset(
            self.window_start
        ) is None:
            raise BookFeatureParseError(
                f"a book feature's window_start must be timezone-aware; the 1s "
                f"grid needs an offset to floor against"
            )
        object.__setattr__(self, "window_start", _floor_to_second(self.window_start))
        for name, depths in (
            ("bid_depth", self.bid_depth),
            ("ask_depth", self.ask_depth),
        ):
            keys = tuple(depths)
            if keys != BPS_THRESHOLDS:
                raise BookFeatureParseError(
                    f"{self.symbol} {name} must carry exactly the thresholds "
                    f"{BPS_THRESHOLDS}, got {keys}"
                )
            for bps, value in depths.items():
                if not isinstance(value, Decimal):
                    raise BookFeatureParseError(
                        f"{self.symbol} depth at {bps} bps must be a Decimal, "
                        f"got {type(value).__name__}"
                    )
                if value < 0:
                    raise BookFeatureParseError(
                        f"{self.symbol} depth at {bps} bps is negative; a summed "
                        f"quantity is never below zero"
                    )
        for name, price in (
            ("reference_price", self.reference_price),
            ("best_bid", self.best_bid),
            ("best_ask", self.best_ask),
        ):
            if not isinstance(price, Decimal):
                raise BookFeatureParseError(
                    f"{self.symbol} {name} must be a Decimal, got {type(price).__name__}"
                )

    def depth(self, side: str, bps: int) -> str:
        """This row's canonical depth string for ``side`` at ``bps`` bps."""
        field = self.bid_depth if side == "bids" else self.ask_depth
        if bps not in field:
            raise KeyError(f"{bps} bps is not one of {BPS_THRESHOLDS}")
        return field[bps]

    def canonical(self) -> dict[str, object]:
        """This row's canonical mapping — the form the content hash is taken over.

        Depths are ordered by threshold and keys sorted, so two snapshots
        carrying the same book agree on their hash.  The depth values are the
        canonical decimal strings, so a snapshot that changed one level's
        quantity disagrees on the hash while one that merely reordered a level
        does not.  The computed values are strings here — the persisted form —
        even though they are Decimals in memory, so the row serialises to the
        feature value rather than a float that could drift on a re-render.
        """
        return {
            "symbol": self.symbol,
            "window_start": self.window_start.isoformat(),
            "reference_price": _canonical_decimal(self.reference_price),
            "best_bid": _canonical_decimal(self.best_bid),
            "best_ask": _canonical_decimal(self.best_ask),
            "bid_depth": {
                str(bps): _canonical_decimal(self.bid_depth[bps]) for bps in BPS_THRESHOLDS
            },
            "ask_depth": {
                str(bps): _canonical_decimal(self.ask_depth[bps]) for bps in BPS_THRESHOLDS
            },
        }


@dataclass(frozen=True)
class BookFeatureBatch:
    """One cycle's derived output: the rows, the closing book, and the frontier.

    A batch is what a worker cycle produces and persists.  It carries four
    things, each of which makes the reduction resumable:

    * ``rows`` — the derived 1s rows this cycle emitted, one per (symbol, second)
      that carried a diff and had a two-sided book.
    * ``closing_books`` — the reconstructed book per symbol at the *end* of the
      span.  This is the state the next cycle seeds from and a restart resumes
      from; it is why the derived store, not the 90-day raw store, is the
      permanent home of the book.
    * ``from_window`` / ``to_window`` — the 1s bounds this cycle covered;
      ``to_window`` is the resume point a reader skips snapshots up to.
    * ``from_raw_sequence`` / ``to_raw_sequence`` — the raw-log bounds; the next
      cycle consumes only raw records past ``to_raw_sequence``, so no diff is
      folded twice.

    A batch with no rows but an advanced frontier is still a batch — the book
    moved even if no new second was crossed — and is persisted so the frontier
    and the closing book advance.  A batch that neither emits a row nor advances
    the frontier is refused: an empty cycle is not a record.
    """

    rows: Sequence[BookFeatureRow]
    closing_books: Mapping[str, BookState]
    from_window: datetime | None
    to_window: datetime | None
    from_raw_sequence: int
    to_raw_sequence: int

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        for row in rows:
            if not isinstance(row, BookFeatureRow):
                raise BookFeatureParseError(
                    "a book-feature batch's rows must be BookFeatureRow "
                    f"instances, got {type(row).__name__}"
                )
        object.__setattr__(self, "rows", rows)
        closing = dict(self.closing_books)
        for symbol, state in closing.items():
            if not isinstance(state, BookState):
                raise BookFeatureParseError(
                    f"closing_books[{symbol!r}] must be a BookState, "
                    f"got {type(state).__name__}"
                )
        object.__setattr__(self, "closing_books", closing)
        if not rows and self.to_raw_sequence <= self.from_raw_sequence:
            # No new rows and no advance through the raw log: nothing changed,
            # so there is nothing to persist.  An empty cycle is not a record —
            # the honest no-progress state reports ``sequence=0`` and appends
            # nothing, exactly as a not-due funding cycle does.
            raise BookFeatureParseError(
                "a book-feature batch must carry at least one row or advance the "
                "raw-log frontier; an empty batch is a no-progress cycle, not a "
                "snapshot"
            )
        if self.from_raw_sequence < 0 or self.to_raw_sequence < self.from_raw_sequence:
            raise BookFeatureParseError(
                f"raw-sequence bounds {self.from_raw_sequence}..{self.to_raw_sequence} "
                f"are not a valid span"
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

    def rows_for(self, symbol: str) -> tuple[BookFeatureRow, ...]:
        """This batch's rows for ``symbol``, in the batch's order."""
        return tuple(row for row in self.rows if row.symbol == symbol)

    def canonical_bytes(self) -> bytes:
        """The batch's canonical JSON bytes — the thing content-hashed.

        Canonical means rows in a deterministic order (window, then symbol),
        closing books in symbol order, keys sorted and the tightest separators —
        so two cycles producing the same features and closing book hash
        identically whatever order the symbols were folded in.  This is what
        makes :attr:`BookFeatureRecord.source_sha256` a *content* hash.
        """
        document = {
            _DOCUMENT_KEY: [row.canonical() for row in sorted(self.rows, key=_row_sort)],
            _CLOSING_KEY: {
                symbol: self.closing_books[symbol].snapshot()
                for symbol in sorted(self.closing_books)
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


def _row_sort(row: BookFeatureRow) -> tuple[datetime, str]:
    return (row.window_start, row.symbol)


def parse_book_features(batch: object) -> BookFeatureBatch:
    """Validate an already-built :class:`BookFeatureBatch`.

    This module's rows are computed, not parsed from a venue payload, so the
    "parse" here is the gate a persisted record's rows pass back through on read:
    a :class:`BookFeatureBatch` is returned unchanged, and anything else is
    refused, so a damaged document never reconstructs into a feature.
    """
    if not isinstance(batch, BookFeatureBatch):
        raise BookFeatureParseError(
            "a book-feature batch must be a BookFeatureBatch, "
            f"got {type(batch).__name__}"
        )
    return batch


class BookFeatureStore:
    """The append-only log of derived 1s book features, under the staging area.

    Records live at ``<lake>/staging/bookFeatures/<sequence>.bin``, one file per
    cycle, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a record is written once,
    atomically (temp file, ``fsync``, ``rename``), and never rewritten: the
    underlying batch store refuses a second batch at a sequence it already holds.
    This is §4.1's derived-feature stream, in the same append-only area as every
    other stream, so the seal copies it the same way and — like the funding and
    exchangeInfo logs — nothing in the system ever expires it.  That permanence
    is the point: the raw diffs this log is derived from are 90-day-retained and
    then gone, so the derived log must outlive them, and it does because each
    record carries its own closing book rather than depending on the raw store.

    Construction reads whatever a prior run left on disk, so a restarted process
    knows the last closing book and the frontier it reached without a network
    call — the same seed-from-what-is-durable moment the resume watermark gives a
    restarted worker.  The store reads no clock: ``computed_at`` is a parameter,
    driven by the worker's injected clock (§12).
    """

    def __init__(self, staging: StagingArea) -> None:
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"the book-feature store writes into a StagingArea, "
                f"got {type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "BookFeatureStore":
        """The store over the lake's staging area, resolved from the environment.

        The same resolution every ingest store uses (``LAKE_ROOT``, defaulting to
        ``lake/`` beside the workspace root), so records are written into the
        very area the seal copies out of — there is no second root that could
        drift from the first.
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
        return self._staging.path_for(BOOK_FEATURES_STREAM)

    def path_for(self, sequence: int) -> Path:
        """The file sequence ``sequence`` is committed to."""
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise TypeError(f"a sequence is an integer, not {type(sequence).__name__}")
        if sequence <= 0:
            raise ValueError(f"a sequence must be positive, got {sequence}")
        return self.root / f"{sequence}.bin"

    # -- Recording ------------------------------------------------------------

    def record(
        self, batch: BookFeatureBatch, *, computed_at: datetime
    ) -> BookFeatureRecord:
        """Persist one cycle as the next record; never overwrite a prior one.

        The batch is validated *first*, so a malformed batch consumes no sequence
        number and leaves the log untouched; then it is written as the next
        record — ``current + 1`` — into the stream's append-only staging log.
        The previous records are not read, moved or rewritten: adding a record is
        an append, and the store's duplicate-sequence refusal means this method
        has no code path that could overwrite one.

        ``computed_at`` is required and must be timezone-aware: it is the instant
        the cycle ran, stamped on the record, and a naive timestamp would make
        the record's own provenance unanswerable.  The store does not read a
        clock of its own — the worker that ran the cycle owns the time.
        """
        parsed = parse_book_features(batch)
        if not isinstance(computed_at, datetime) or computed_at.tzinfo is None or (
            computed_at.tzinfo.utcoffset(computed_at) is None
        ):
            raise ValueError(
                "computed_at must be a timezone-aware datetime; the record's "
                "provenance needs a comparable instant"
            )

        sequence = self._staging.current(BOOK_FEATURES_STREAM) + 1
        envelope = {
            "stream": str(BOOK_FEATURES_STREAM),
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
            _DOCUMENT_KEY: [row.canonical() for row in sorted(parsed.rows, key=_row_sort)],
        }
        payload = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        batch_ = self._staging.append(
            BOOK_FEATURES_STREAM, payload=payload, rows=len(parsed)
        )
        return BookFeatureRecord(
            sequence=batch_.sequence,
            computed_at=computed_at.astimezone(timezone.utc),
            batch=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            path=batch_.path,
        )

    # -- Reading --------------------------------------------------------------

    def records(self) -> tuple[BookFeatureRecord, ...]:
        """Every persisted record, oldest first.

        Read back from the staging log in ascending sequence order, each envelope
        verified against the sequence its filename claims and the document hash
        it recorded — so a reader gets either the record that was committed or a
        clear :class:`BookFeatureCorruptError`, never a plausible-looking feature
        assembled from damaged bytes.
        """
        return tuple(
            self._read(batch) for batch in self._staging.staged(BOOK_FEATURES_STREAM)
        )

    def current(self) -> BookFeatureRecord | None:
        """The most recent record, or ``None`` when nothing has been persisted."""
        batches = self._staging.staged(BOOK_FEATURES_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def last_record(self) -> BookFeatureRecord | None:
        """The most recent record — the seed a resumed worker starts from.

        A convenience over :meth:`current` for the worker, which needs the whole
        record (its closing books and its frontier) rather than just knowing one
        exists.  ``None`` on the first cycle, when the worker seeds from an empty
        book.
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
    ) -> tuple[BookFeatureRow, ...]:
        """Every retained feature row for ``symbol`` at one 1s window.

        Unioned across all records and matched on the aligned window, so a caller
        may pass any instant inside the window it means.  This is the reader seam
        features 21/22 stand on: the derived rows for a symbol at a second.
        """
        wanted = _floor_to_second(window_start)
        found: list[BookFeatureRow] = []
        for record in self.records():
            found.extend(
                row
                for row in record.batch.rows
                if row.symbol == symbol and row.window_start == wanted
            )
        return tuple(found)

    def _read(self, batch) -> BookFeatureRecord:
        # Read one committed batch back into a record, verifying as it goes.  The
        # checks are the read half of the append-only guarantee: the bytes are
        # the bytes that were committed, under the sequence the filename claims,
        # carrying the document the envelope's hash vouches for.  A mismatch is
        # corruption (or tampering) on a log the derived features are rebuilt
        # from — and whose closing book a restart seeds from — so it is raised
        # rather than papered over.
        try:
            envelope = json.loads(batch.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise BookFeatureCorruptError(
                f"book-feature record {batch.sequence} is not readable as a JSON "
                f"envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise BookFeatureCorruptError(
                f"book-feature record {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise BookFeatureCorruptError(
                f"book-feature record {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"record envelope this store wrote"
            )
        recorded = envelope["sequence"]
        if recorded != batch.sequence:
            raise BookFeatureCorruptError(
                f"book-feature record file {batch.sequence}.bin records sequence "
                f"{recorded!r}; the file does not describe itself"
            )
        document = _read_document(envelope[_DOCUMENT_KEY], batch.sequence)
        closing = _read_closing(envelope.get(_CLOSING_KEY, {}), batch.sequence)
        recorded_hash = envelope["source_sha256"]
        rebuilt = BookFeatureBatch(
            rows=document,
            closing_books=closing,
            from_window=_parse_optional_timestamp(envelope.get("from_window"), batch.sequence),
            to_window=_parse_optional_timestamp(envelope.get("to_window"), batch.sequence),
            from_raw_sequence=int(envelope["from_raw_sequence"]),
            to_raw_sequence=int(envelope["to_raw_sequence"]),
        )
        if recorded_hash != rebuilt.source_sha256:
            raise BookFeatureCorruptError(
                f"book-feature record {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{rebuilt.source_sha256!r}; the file's bytes are not the "
                f"bytes that were committed"
            )
        return BookFeatureRecord(
            sequence=batch.sequence,
            computed_at=_parse_timestamp(envelope["computed_at"], batch.sequence),
            batch=rebuilt,
            source_sha256=rebuilt.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


@dataclass(frozen=True)
class BookFeatureRecord:
    """One persisted cycle: the sequence it landed under and the features it carried.

    ``sequence`` is the record's position in the stream's append-only log and,
    because the log is feature 28's staging area, the sequence of the batch the
    envelope bytes were committed as.  ``computed_at`` is when *we* ran the cycle
    (UTC, timezone-aware), kept apart from the rows' ``window_start``, which is
    when the book was snapshotted: conflating them would let our own ingest lag
    decide which second a feature belongs to.

    Two hashes, deliberately distinct, exactly as funding's and book-diff records
    carry them: ``source_sha256`` is over the *document* and answers "did the
    features change?"; ``payload_sha256`` is over the *bytes written* and is the
    file's identity, the same value the seal's MANIFEST will record for it.
    ``path`` names the ``<sequence>.bin`` the bytes were committed to.
    """

    sequence: int
    computed_at: datetime
    batch: BookFeatureBatch
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

        The state a restarted worker seeds from: the book after every diff this
        record consumed, so the reconstruction resumes without re-deriving from
        raw diffs that may since have left the 90-day window.  ``None`` when the
        record never saw the symbol.
        """
        return self.batch.closing_books.get(symbol)


def _read_document(entries: object, sequence: int) -> tuple[BookFeatureRow, ...]:
    # Read a persisted document back into rows, rebuilding each depth map from its
    # canonical strings.  A document that is not a list of well-formed rows is
    # corruption, not data.
    if not isinstance(entries, list):
        raise BookFeatureCorruptError(
            f"book-feature record {sequence} has a document that is not a list "
            f"of rows"
        )
    rows: list[BookFeatureRow] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise BookFeatureCorruptError(
                f"book-feature record {sequence} has a row that is not an object"
            )
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise BookFeatureCorruptError(
                f"book-feature record {sequence} has a row with no non-empty "
                f"symbol"
            )
        window = _parse_timestamp(entry.get("window_start"), sequence)
        rows.append(
            BookFeatureRow(
                symbol=symbol,
                window_start=window,
                reference_price=Decimal(entry["reference_price"]),
                best_bid=Decimal(entry["best_bid"]),
                best_ask=Decimal(entry["best_ask"]),
                bid_depth={bps: Decimal(entry["bid_depth"][str(bps)]) for bps in BPS_THRESHOLDS},
                ask_depth={bps: Decimal(entry["ask_depth"][str(bps)]) for bps in BPS_THRESHOLDS},
            )
        )
    return tuple(rows)


def _read_closing(entries: object, sequence: int) -> dict[str, BookState]:
    # Read the persisted closing books back into BookState objects — the resume
    # seed.  A closing book that is not a well-formed snapshot is corruption: a
    # damaged seed would reconstruct a book the market never had.
    if not isinstance(entries, Mapping):
        raise BookFeatureCorruptError(
            f"book-feature record {sequence} has closing books that are not an "
            f"object"
        )
    closing: dict[str, BookState] = {}
    for symbol, snap in entries.items():
        if not isinstance(snap, Mapping) or "bids" not in snap or "asks" not in snap:
            raise BookFeatureCorruptError(
                f"book-feature record {sequence} has a closing book for "
                f"{symbol!r} that is not a snapshot"
            )
        closing[symbol] = BookState.from_snapshot(snap)
    return closing


def _parse_optional_timestamp(raw: object, sequence: int) -> datetime | None:
    if raw is None:
        return None
    return _parse_timestamp(raw, sequence)


def _parse_timestamp(raw: object, sequence: int) -> datetime:
    if not isinstance(raw, str):
        raise BookFeatureCorruptError(
            f"book-feature record {sequence} records a timestamp {raw!r}; "
            f"expected an ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise BookFeatureCorruptError(
            f"book-feature record {sequence} records an unparseable timestamp "
            f"{raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise BookFeatureCorruptError(
            f"book-feature record {sequence} records a naive timestamp; the "
            f"grid and the provenance need a comparable instant"
        )
    return parsed.astimezone(timezone.utc)


class BookFeatureWorker:
    """The derived book-feature worker: reconstruct the book, snapshot each second.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the
    ``bookFeatures`` stream class, so the supervisor of feature 16 runs it on its
    own thread alongside every other stream and converts whatever it raises into
    that stream's own failure.  Unlike every earlier stream worker it owns no
    venue fetch: its input is the *internal* raw-diff store feature 19 persisted,
    so there is no unconfigured-fetch path — an empty raw store simply yields
    empty cycles.

    One cycle is a stateful reduction over the raw-diff log, in four steps:

    * **Seed.**  Read the last feature record.  Its closing books are the running
      book; its ``to_window`` and ``to_raw_sequence`` are the frontier.  On the
      first cycle the book is empty and the frontier is zero.
    * **Consume.**  Read the raw records feature 19 persisted past the frontier,
      folding their rows into the running book in time order and bucketing them
      onto the 1s grid.  Only raw records past ``to_raw_sequence`` are consumed,
      so no diff is folded twice; a record that straddles the frontier folds its
      whole self (a late diff for an already-snapshotted second updates the
      going-forward book) but does not re-emit that second.
    * **Snapshot.**  For each (symbol, 1s window) that carried a diff and whose
      window is past the frontier, snapshot the depth features off the
      reconstructed book — but only when the book has two sides, so a one-sided
      book emits no row.
    * **Persist.**  Append one record carrying the derived rows and the closing
      book, advancing the frontier.  The closing book is the permanent home of
      the reconstruction, so the next cycle — or a restart after the raw window
      has slid — resumes from it rather than re-deriving from raw diffs.

    A cycle that consumes no new raw records appends nothing and reports
    ``sequence=0, rows_written=0`` — the honest no-progress cycle, matching a
    not-due funding cycle.  A cycle that consumes new raw records but crosses no
    new second still persists (its book moved), with ``rows_written`` counting
    the new rows, which may be zero.

    The clock is injected because ``computed_at`` is a fact about elapsed
    wall-clock time: a test must be able to place the worker without touching the
    wall clock, and §12 keeps wall-clock reads out of checked code.  The default
    clock reads the system UTC time.
    """

    def __init__(
        self,
        store: BookFeatureStore,
        diff_store: BookDiffStore,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, BookFeatureStore):
            raise TypeError(
                f"the book-feature worker persists into a BookFeatureStore, "
                f"got {type(store).__name__}"
            )
        if not isinstance(diff_store, BookDiffStore):
            raise TypeError(
                f"the book-feature worker reads from a BookDiffStore, "
                f"got {type(diff_store).__name__}"
            )
        if clock is not None and not callable(clock):
            raise TypeError(
                f"clock must be a callable returning a datetime, "
                f"got {type(clock).__name__}"
            )
        self._store = store
        self._diff_store = diff_store
        self._clock = clock if clock is not None else _utc_now

    # -- IngestWorker ---------------------------------------------------------

    @property
    def stream_class(self) -> StreamClass:
        """The one stream class this worker owns — ``bookFeatures``."""
        return BOOK_FEATURES_STREAM

    @property
    def store(self) -> BookFeatureStore:
        """The derived-feature log this worker appends to."""
        return self._store

    @property
    def diff_store(self) -> BookDiffStore:
        """The raw-diff store this worker reconstructs the book from."""
        return self._diff_store

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Reconstruct the book from new raw diffs and persist the 1s snapshots.

        Returns the persisted record's sequence as the cycle's watermark — the
        frontier a restarted worker resumes past — and ``rows_written`` as the
        number of derived rows the record carries.  A no-new-data cycle reports
        both as zero and appends nothing.
        """
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
            raise ValueError("the clock must return a timezone-aware datetime")

        last = self._store.last_record()
        books: dict[str, BookState]
        frontier_window: datetime | None
        frontier_seq: int
        if last is None:
            books = {}
            frontier_window = None
            frontier_seq = 0
        else:
            books = dict(last.batch.closing_books)
            frontier_window = last.to_window
            frontier_seq = last.to_raw_sequence

        # Consume raw records past the frontier in one pass, folding each row
        # into the running book and bucketing it onto the 1s grid.  Only records
        # past the frontier are read, so the reduction never folds a diff twice;
        # the book is seeded from the closing books, so it never has to be
        # re-derived from raw diffs that may since have left the 90-day window.
        #
        # A (symbol, second) is snapshotted the moment its book is complete —
        # after the last diff for that second has been folded — off the
        # reconstructed book, keeping only two-sided books.  A second is emitted
        # only when a diff landed in it and it is past the frontier window, so
        # the feature log is paced by genuine book changes, not by the cycle's
        # cadence, and a restart never re-emits a second it already emitted.
        from_raw_sequence = frontier_seq
        rows: list[BookFeatureRow] = []
        snapshotted: set[tuple[str, datetime]] = set()
        to_window = frontier_window
        for record in self._diff_store.records():
            if record.sequence <= frontier_seq:
                continue
            for row in record.batch.rows:
                books.setdefault(row.symbol, BookState()).apply(row)
                bucket = _floor_to_second(row.window_start)
                if to_window is None or bucket > to_window:
                    to_window = bucket
                if frontier_window is not None and bucket <= frontier_window:
                    continue  # already emitted before the frontier
                key = (row.symbol, bucket)
                if key in snapshotted:
                    continue  # this second already snapshotted
                snapshotted.add(key)
                feature = _depth_row(row.symbol, bucket, books[row.symbol])
                if feature is not None:
                    rows.append(feature)
            frontier_seq = record.sequence

        if from_raw_sequence == 0 and to_window is None:
            # No raw diffs have ever been seen: nothing to reconstruct.
            return CycleResult(rows_written=0, sequence=0)
        if frontier_seq == from_raw_sequence and to_window == frontier_window:
            # No new raw records were consumed and no new second was crossed: a
            # no-progress cycle.  Nothing changed, so nothing is persisted.
            return CycleResult(rows_written=0, sequence=0)

        batch = BookFeatureBatch(
            rows=rows,
            closing_books=books,
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


def register_book_feature_worker(
    store: Optional[BookFeatureStore] = None,
    diff_store: Optional[BookDiffStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], BookFeatureWorker]:
    """Register a worker factory bound to explicitly wired stores.

    The operator path: hand in the derived-feature store and the raw-diff store
    (when they are not the lake's staging area), and this registers a worker
    factory bound to those collaborators.  Registration replaces the
    auto-discovered factory of the same class in the registry it targets — the
    registry's own rule, *a re-registered class is a revision of the same worker,
    never a second worker* — so a deployment that wires stores does not end up
    with two book-feature workers competing for the same sequence numbers.

    ``registry`` defaults to a **private** registry, not the process-wide one: a
    registration is a deployment act, and silently replacing the auto-discovered
    worker for every later composition in the process would hand unrelated
    callers — tests especially — a worker bound to stores that may since have
    vanished.  A caller that means to reconfigure the running process passes
    :func:`~nullius_ingest.registry.default_worker_registry` explicitly, matching
    :func:`~nullius_ingest.registry.register_worker`.

    Returns the registered factory, so a caller can build the worker it just
    registered — over the private registry by default — without reaching back
    into it.
    """
    if clock is not None and not callable(clock):
        raise TypeError(
            f"clock must be a callable returning a datetime, "
            f"got {type(clock).__name__}"
        )

    def build() -> BookFeatureWorker:
        resolved_store = store if store is not None else BookFeatureStore.from_env()
        resolved_diff = diff_store if diff_store is not None else BookDiffStore.from_env()
        return BookFeatureWorker(resolved_store, resolved_diff, clock=clock)

    # Register through a private registry by default, never the process-wide one.
    # Registration is a *deployment* act: writing a caller's wiring into the
    # default registry would replace the auto-discovered worker for every later
    # composition in the process — including tests, which would then be handed a
    # worker bound to stores that have since been deleted.  A caller that
    # genuinely means to reconfigure the running process passes the default
    # registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        BOOK_FEATURES_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(BOOK_FEATURES_STREAM)
def build_book_feature_worker() -> BookFeatureWorker:
    """Compose the book-feature worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    Collaborators come from the environment the way every other ingest store
    does: both stores are the lake's staging area (:meth:`from_env`), so the
    derived features land in the very area the seal copies out of, and the book
    is reconstructed from the raw diffs feature 19 persisted into that same area.
    The worker needs no injected fetch — its input is the internal raw-diff
    store — so it composes fully configured and its cycle reports that stream's
    own failure only if the stores themselves are mis-wired, which is feature
    16's contract: an unconfigured stream is a row in the report, not a component
    that fails to load.
    """
    return BookFeatureWorker(BookFeatureStore.from_env(), BookDiffStore.from_env())
