"""L2 book diffs at 100 millisecond resolution, under a rolling 90 day window.

app_spec.xml feature 19 states the behaviour: *"System ingests L2 book diffs at
100 millisecond resolution, persisting raw diffs under a rolling 90 day
retention window."*  docs/nullius-tech-architecture.md §4.1 fixes the stream's
row in the data-layer table — ``L2 book diffs | WS @100ms | continuous |
rolling 90 days only`` — and then states why the retention column is the
load-bearing one:

    **The L2 retention decision is load-bearing.**  Raw diff streams for a
    100-symbol universe run roughly 50–200 GB/month uncompressed.  Storing them
    forever is a self-inflicted infrastructure problem.  Instead: keep raw diffs
    for a rolling 90 days so feature definitions can be revised and backfilled
    recently, and permanently persist derived book features at 1s resolution.

So this module owns two things no earlier stream module had to, and one thing
every stream module owns:

* **The 100 millisecond grid** is a fact about *rows*, not about files.  A raw
  diff carries the venue's own event time, and that instant is floored onto an
  exact 100 ms lattice to give the row its ``window_start``.  Resolution is
  therefore something a reader can rely on (feature 20 recomputes 1 s book
  features from these rows and needs to know which window each diff fell in)
  while the *persistence* unit stays a batch of many slices — one file per
  100 ms slice would be ~864,000 files a day, and ~77 million over the window,
  which is the infrastructure problem §4.1 just finished describing.

* **The rolling window is a deletion**, and this is the first thing in the
  system that removes data.  Feature 28's staging area is append-only and
  :mod:`nullius_ingest.funding` says so explicitly, quoting this very stream as
  its contrast.  Nothing about that contrast changes here: the funding log is
  never retired, and what this stream retires it retires *whole* — a batch whose
  newest slice has fallen outside the window has all of its files unlinked
  through :meth:`~nullius_ingest.staging.StagingArea.retire`, so every byte that
  survives is still a byte that was committed.  A batch straddling the cutoff is
  kept entire, which over-keeps by at most one batch and never splits one.

* **The raw rows are kept raw.**  Prices and quantities are persisted in the
  venue's own spelling, exactly as funding and exchangeInfo persist their
  scalars: whether the venue said ``"0.00010"`` or ``"0.0001"`` is a fact about
  the venue, and this is *raw* data, so re-rendering it would be the one thing
  the raw tier must never do.  A ``quantity`` of ``"0"`` is a level *removal* and
  is kept as such rather than filtered out — the diff stream's whole content is
  the difference, and dropping a removal row would silently delete the
  information that a level went away.

Three pieces, mirroring the landed stream modules:

* **The row and the batch** — :class:`BookDiffRow` (one symbol's diff in one
  100 ms window: the venue's update-id range and the two level lists) and
  :class:`BookDiffBatch` (one cycle's rows).  A batch makes no completeness
  claim about any window: it records what arrived, and a reader unions by
  ``window_start`` across batches.

* **The record** — :class:`BookDiffRecord`: one *commit*, frozen, carrying the
  sequence it was persisted under, the instant it was written, its span on the
  grid, the document's content hash and the hash of the bytes written.

* **The store** — :class:`BookDiffStore`: an append-only log of records under
  the §4.1 staging area, at ``<lake>/staging/bookDiffs/<seq>.bin``, plus
  :meth:`BookDiffStore.prune`, which is the rolling 90 day window made
  structural.

Layering on the stream workers of feature 16 is deliberate, as it is for every
other stream: this is one worker owning one stream class, so a failed flush is
that stream's :class:`~nullius_ingest.worker.StreamFailure` and every other
stream keeps ingesting.  The fetch is injected (:data:`BookDiffFetch`) — the
member ships no websocket client, exactly as it ships no REST client, so the
venue's auth, rate limits and reconnect policy stay the deployment's business
(§15's *"WS gap / reconnect"* row is features 25 and 26, which
:class:`~nullius_ingest.gaps.GapDetector` and
:class:`~nullius_ingest.backfill.GapBackfiller` already serve) — and the clock
is injected because both the worker's retention pass and nothing else about this
module may read the wall clock (§12 keeps wall-clock reads out of checked code).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, Optional, Union

from .registry import WorkerRegistry, register_worker
from .staging import StagingArea
from .streams import StreamClass
from .worker import CycleResult

__all__ = [
    "ASKS",
    "BIDS",
    "BOOK_DIFFS_STREAM",
    "BookDiffBatch",
    "BookDiffCorruptError",
    "BookDiffError",
    "BookDiffFetch",
    "BookDiffParseError",
    "BookDiffRecord",
    "BookDiffRow",
    "BookDiffStore",
    "BookDiffWorker",
    "PriceLevel",
    "RETENTION",
    "RETENTION_DAYS",
    "RetentionReport",
    "SLICE",
    "SLICE_MILLISECONDS",
    "Side",
    "align_to_window",
    "build_book_diff_worker",
    "parse_book_diffs",
    "register_book_diff_worker",
    "window_start_for",
]

#: The stream class this module serves.  §4.1's table row for L2 book diffs is
#: the stream whose resolution is 100 ms and whose retention is a rolling
#: window, and the spelling here is the persisted one
#: (:class:`~nullius_ingest.streams.StreamClass`), so the staging layout and the
#: record log share it.
BOOK_DIFFS_STREAM = StreamClass.BOOK_DIFFS

#: The resolution §4.1's table records for this stream, as both a count of
#: milliseconds and an interval.  Carried as constants so the fact is named
#: where it is decided rather than re-derived as a literal at each call site,
#: and so the grid arithmetic and the record's span cannot drift apart.
SLICE_MILLISECONDS: Final[int] = 100
SLICE: Final[timedelta] = timedelta(milliseconds=SLICE_MILLISECONDS)

#: The retention window §4.1's table records for this stream: *"rolling 90 days
#: only"*.  Unlike every other stream in the table, which is kept *forever*, this
#: one is a window — and the number is load-bearing rather than tidy, because
#: §4.1 says a new microstructure feature can only be backfilled 90 days and
#: that the derived book features exist precisely so this window can close
#: without losing the derived history (features 20–22).
RETENTION_DAYS: Final[int] = 90
RETENTION: Final[timedelta] = timedelta(days=RETENTION_DAYS)

#: The envelope keys a record file carries around its rows — named so a reader
#: of a record file (an operator, a seal, a later audit) does not have to import
#: this module to know what it is looking at.  ``rows`` is the document.
_ENVELOPE_KEYS = (
    "stream",
    "sequence",
    "written_at",
    "source_sha256",
    "window_start",
    "window_end",
)

#: Wrapper keys under which a venue endpoint may nest its diff list — the flat
#: list and the single-diff object are also accepted (see
#: :func:`parse_book_diffs`), so this is a convenience, not a closed set.
_WRAPPER_KEYS = ("diffs", "data", "events", "bookDiffs")

#: The envelope key holding the rows, named beside the keys around it so a
#: reader of a record file does not have to hunt for it.
_DOCUMENT_KEY = "rows"

_UTC = timezone.utc

#: The epoch and the slice width in microseconds: the two constants the grid is
#: computed from.  Every instant is measured as an exact integer count of
#: microseconds from the epoch and floored there — no float ever touches an
#: instant, so a window boundary is a boundary rather than a rounding, and
#: ``...1299ms`` floors to ``...1200ms`` on every platform.
_EPOCH = datetime(1970, 1, 1, tzinfo=_UTC)
_SLICE_MICROS: Final[int] = SLICE_MILLISECONDS * 1000


class BookDiffError(Exception):
    """Base for every failure this module raises.

    Raised for a payload this module will not persist and for a persisted record
    it will not read: both are cases where the raw-diff log would otherwise
    start lying about what the venue's book did, so both fail loudly rather than
    being approximated into a row.
    """


class BookDiffParseError(BookDiffError):
    """A diff payload is not one this module will persist.

    Raised *before* anything is written, so a rate-limit body, a truncated
    frame or an error page never consumes a sequence number and never appears in
    the log as a flush that happened.  The message names what was wrong with
    which diff, because the caller is a worker whose next move depends on
    whether the venue's shape changed or the feed simply hiccuped.
    """


class BookDiffCorruptError(BookDiffError):
    """A persisted record file does not match what was written under it.

    Raised when a record file cannot be read back as the envelope it was written
    as, when its recorded sequence is not the sequence its filename claims, or
    when recomputing its document hash disagrees with the hash the envelope
    recorded.  A mismatch means the bytes on disk are not the bytes this module
    committed — corruption or tampering — and a reader that reconstructed a book
    from them would be reconstructing a market that never existed.
    """


class Side(str):
    """A book side, as the venue spells it, in the two values a book has.

    A :class:`str` subclass rather than an enum, deliberately: the side is
    persisted verbatim alongside the levels, and a caller comparing against
    ``"bids"`` keeps working — the same loose-typing stance the venues' own
    payloads take.  The two spellings are :data:`BIDS` and :data:`ASKS`; a
    payload naming anything else is refused rather than guessed onto a side,
    because a mis-sided level is a book that looks plausible and is wrong.
    """


#: The two ven-agnostic side spellings this module persists.
BIDS: Final[Side] = Side("bids")
ASKS: Final[Side] = Side("asks")

_SIDES = (BIDS, ASKS)


def _coerce_side(value: object, where: str) -> Side:
    # The venue may spell a side 'bids'/'asks' (Binance), 'bid'/'ask',
    # 'buy'/'sell' or 'B'/'S' (OKX), or as a snake-case variant.  Mapped to the
    # two canonical sides; anything else is refused rather than defaulted,
    # because a level on the wrong side is a book that is silently wrong.
    if isinstance(value, Side):
        return value
    if isinstance(value, str):
        spelled = value.strip().lower()
    elif isinstance(value, bool):
        # ``bool`` before ``int``: it is a subclass, and a boolean side is not
        # a side index.
        raise BookDiffParseError(f"{where} is a boolean; expected a book side")
    elif isinstance(value, int):
        # Some feeds index sides 0/1.  Mapped in the conventional order
        # (bids first, asks second), which is the order every venue's own
        # book snapshot uses.
        if value in (0, 1):
            return _SIDES[value]
        raise BookDiffParseError(
            f"{where} is the integer {value}; a side index is 0 or 1"
        )
    else:
        raise BookDiffParseError(
            f"{where} is {type(value).__name__}; expected a book side "
            f"(one of {', '.join(_SIDES)})"
        )
    aliases = {
        "bids": BIDS,
        "bid": BIDS,
        "b": BIDS,
        "buy": BIDS,
        "buys": BIDS,
        "asks": ASKS,
        "ask": ASKS,
        "a": ASKS,
        "s": ASKS,
        "sell": ASKS,
        "sells": ASKS,
    }
    found = aliases.get(spelled)
    if found is None:
        raise BookDiffParseError(
            f"{where} is {value!r}; expected a book side "
            f"(one of {', '.join(_SIDES)})"
        )
    return found


def _scalar_field(value: object, where: str) -> str:
    # Price and quantity values are persisted as the venue's own spelling, for
    # the same reason funding persists its rates verbatim: whether the venue
    # said "0.00010" or "0.0001" is a fact about the venue, and this is the raw
    # tier, so re-rendering it would destroy the one thing raw data is for.
    # Venues are inconsistent about JSON types for the same field — a quantity
    # arrives as a string on one feed and a bare number on another — so scalars
    # are spelled rather than rejected, while containers are refused: a nested
    # object is a shape this module does not model, and storing its ``repr``
    # would be a record that looks like data and is not.
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        # ``bool`` first: it is an ``int`` subclass, and ``True`` must not be
        # persisted as the number 1.
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    raise BookDiffParseError(
        f"{where} is {type(value).__name__}; price and quantity values must be "
        f"scalars (the venue's own spelling is kept verbatim)"
    )


def _update_id_field(value: object, where: str) -> int:
    # Update ids are persisted as integers, not as the venue's spelling: unlike
    # a price they are compared and ordered (the gap detector's whole job is
    # sequence continuity), and ordering two spellings of the same number is
    # not a thing this system should ever have to reason about.
    if isinstance(value, bool):
        raise BookDiffParseError(f"{where} is a boolean; expected an update id")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise BookDiffParseError(
                f"{where} is {value!r}; expected an integer update id: {exc}"
            ) from exc
    raise BookDiffParseError(
        f"{where} is {type(value).__name__}; expected an integer update id"
    )


def _as_epoch_millis(value: object, where: str) -> int:
    # Turn a *venue-supplied* value into an exact integer count of epoch
    # milliseconds.  Venues are inconsistent about JSON types for the same
    # field — an event time arrives as a bare number on one feed and a string
    # on another — so a float or a numeric string is coerced here, at the
    # boundary where that sloppiness is a fact about the venue.  Refusals are
    # the module's own error, not whatever ``int()`` happened to raise, because
    # the caller is a worker deciding whether the venue's shape changed.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise BookDiffParseError(
            f"{where} is {type(value).__name__}; expected an epoch-millisecond "
            f"instant"
        )
    try:
        millis = int(value)
    except (TypeError, ValueError) as exc:
        raise BookDiffParseError(
            f"{where} is {value!r}; expected an epoch-millisecond instant: {exc}"
        ) from exc
    if millis <= 0:
        raise BookDiffParseError(
            f"{where} is {millis}; an epoch-millisecond instant is positive"
        )
    return millis


def _event_time_field(value: object, where: str) -> datetime:
    # Two spellings mean the same thing here, and both must parse because both
    # are written by something in this system:
    #
    # * the venue's epoch milliseconds, which is what a feed sends;
    # * an ISO-8601 instant, which is what *our own record envelope* writes
    #   (``window_start``, already floored onto the grid).  A store that could
    #   not read back its own spelling would fail its own round trip.
    #
    # A venue that sent an ISO string would land in the second branch, which is
    # the right reading of it anyway.  Either way the result is an aware
    # instant; the row floors it, and flooring an already-floored instant is a
    # no-op — which is what makes the envelope's spelling lossless.
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
                raise BookDiffParseError(
                    f"{where} is the naive instant {value!r}; the 100ms grid "
                    f"needs an offset to floor against"
                )
            return parsed
    return _millis_to_utc(_as_epoch_millis(value, where))


def _millis_to_utc(millis: int) -> datetime:
    # Exact: an integer count of milliseconds becomes an integer count of
    # microseconds from the epoch, and the datetime is built from that.  No
    # float and no timestamp()/fromtimestamp() round trip, either of which
    # would put a rounding between the venue's instant and the grid.
    return _EPOCH + timedelta(microseconds=millis * 1000)


def align_to_window(moment: datetime) -> datetime:
    """Floor ``moment`` onto the 100 millisecond grid, as an aware UTC instant.

    The lattice is exact: the instant's epoch microseconds are integer-divided
    by the slice width, so ``...1200ms`` stays put and ``...1299ms`` floors to
    ``...1200ms`` — on every platform, because the arithmetic is over whole
    microseconds and no float is involved.  Two diffs in the same window
    therefore always land on the same value, which is the whole of "100
    millisecond resolution" as a reader will rely on it.

    A naive datetime is refused.  The grid is a lattice over honest instants and
    a naive one has no offset to floor against; assuming UTC here would silently
    place a diff in a window that is wrong by the offset, which is exactly the
    kind of quiet error the raw tier cannot afford.
    """
    _require_aware(moment, "moment")
    since_epoch = moment.astimezone(_UTC) - _EPOCH
    micros = (
        since_epoch.days * 86_400_000_000
        + since_epoch.seconds * 1_000_000
        + since_epoch.microseconds
    )
    return _EPOCH + timedelta(microseconds=(micros // _SLICE_MICROS) * _SLICE_MICROS)


def window_start_for(event_time_ms: int) -> datetime:
    """The 100 ms window a venue event time falls in.

    The convenience a fetch implementation and a test share: epoch milliseconds
    in, the window's inclusive start out, on the same exact lattice
    :func:`align_to_window` defines.  Kept as its own function rather than left
    to the caller because the venue's event time is the *only* instant a raw row
    is placed by, and it should take one call to place one.

    Strict about its argument, unlike the parser: a venue's payload may spell a
    time as a float or a string and is coerced where it arrives
    (:func:`parse_book_diffs`), but this is *our* grid API and a fractional
    millisecond is not an instant at this resolution.  Refusing it here keeps
    the coercion at the boundary where the venue's sloppiness is a fact, rather
    than letting it leak into the arithmetic the grid is computed with.
    """
    if isinstance(event_time_ms, bool) or not isinstance(event_time_ms, int):
        raise TypeError(
            f"event_time_ms must be an integer, not {type(event_time_ms).__name__}"
        )
    return align_to_window(_millis_to_utc(event_time_ms))


@dataclass(frozen=True)
class PriceLevel:
    """One level of the book: a side, a price and a quantity, all as spelled.

    ``price`` and ``quantity`` are the venue's own string spellings, kept
    verbatim.  ``quantity`` of ``"0"`` is not special-cased here — it is a level
    *removal*, and the raw tier keeps it as the venue sent it, because a reader
    that had to infer removals from absent price levels would be reconstructing
    the venue's intent rather than reading it.

    The level is frozen and its values are spelled at construction, so a caller
    cannot build a level whose persisted form differs from what it read.
    """

    side: Side
    price: str
    quantity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_side(self.side, "a level's side"))
        object.__setattr__(self, "price", str(self.price))
        object.__setattr__(self, "quantity", str(self.quantity))
        if not self.price:
            raise BookDiffParseError("a price level must carry a non-empty price")
        if not self.quantity:
            raise BookDiffParseError(
                f"a price level for {self.price!r} must carry a non-empty "
                f"quantity; a removal spells its quantity as \"0\""
            )

    @property
    def is_removal(self) -> bool:
        """Whether this level removes ``price`` from its side of the book.

        True for a quantity that is numerically zero, whatever the venue's
        spelling — ``"0"``, ``"0.0"``, ``"0.000"``.  Offered as a read-side
        convenience only: the persisted row keeps the venue's spelling, and
        nothing in this module filters on this property, because dropping a
        removal row would delete the fact that a level went away.
        """
        try:
            return float(self.quantity) == 0.0
        except ValueError:
            return False


@dataclass(frozen=True)
class BookDiffRow:
    """One symbol's raw book diff, placed on the 100 millisecond grid.

    Five facts, each load-bearing:

    * ``symbol`` — which book changed.
    * ``window_start`` — the 100 ms window the venue's event time fell in, from
      :func:`window_start_for`.  This is the row's resolution: several diffs may
      share it (a busy symbol genuinely receives more than one inside 100 ms)
      and a reader unions by it, so a window is a *set* of diffs rather than a
      slot one diff occupies.
    * ``first_update_id`` / ``last_update_id`` — the venue's update-id range.
      Kept as its own pair rather than collapsed to one number because the range
      is what a continuity check reads: §15's *"WS gap / reconnect"* row is
      detected by an update id arriving past the one expected, and the detector
      (feature 25) needs both ends to name the hole.
    * ``levels`` — the price levels the diff carries, in the venue's order, each
      tagged with the side it belongs to.  One flat tuple rather than two fields
      because a diff may legitimately carry only one side, and a reader walking
      the diff reads the venue's order.

    The row is frozen: a record is what the venue sent, and a caller mutating it
    in place would be editing history.
    """

    symbol: str
    window_start: datetime
    first_update_id: int
    last_update_id: int
    levels: Sequence[PriceLevel] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise BookDiffParseError(
                f"a book diff must carry a non-empty symbol, got {self.symbol!r}"
            )
        _require_aware(self.window_start, "window_start")
        object.__setattr__(
            self, "window_start", align_to_window(self.window_start)
        )
        for value, name in (
            (self.first_update_id, "first_update_id"),
            (self.last_update_id, "last_update_id"),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise BookDiffParseError(
                    f"{name} must be an integer, got {type(value).__name__}"
                )
        if self.last_update_id < self.first_update_id:
            # A range that ends before it begins is not a diff this module can
            # record: the pair is the continuity evidence feature 25's detector
            # reads, and a reversed one would make a gap appear to run backwards.
            raise BookDiffParseError(
                f"{self.symbol} carries update ids "
                f"{self.first_update_id}..{self.last_update_id}; a diff's range "
                f"does not end before it begins"
            )
        levels = tuple(self.levels)
        for index, level in enumerate(levels):
            if not isinstance(level, PriceLevel):
                raise BookDiffParseError(
                    f"{self.symbol} levels[{index}] is "
                    f"{type(level).__name__}; expected a PriceLevel"
                )
        for side in _SIDES:
            seen: set[str] = set()
            for level in levels:
                if level.side != side:
                    continue
                if level.price in seen:
                    # Two levels for one (side, price) make "the quantity at
                    # this price" ambiguous, and picking one arbitrarily is a
                    # silent choice between two different books.
                    raise BookDiffParseError(
                        f"{self.symbol} lists price {level.price!r} more than "
                        f"once on the {side} side of one diff; the diff does "
                        f"not say which quantity applies"
                    )
                seen.add(level.price)
        object.__setattr__(self, "levels", levels)

    @property
    def window_end(self) -> datetime:
        """The exclusive end of this row's window — ``window_start`` + 100 ms."""
        return self.window_start + SLICE

    def on_side(self, side: Side | str) -> tuple[PriceLevel, ...]:
        """This diff's levels on ``side``, in the venue's order."""
        wanted = _coerce_side(side, "side")
        return tuple(level for level in self.levels if level.side == wanted)

    @property
    def bids(self) -> tuple[PriceLevel, ...]:
        """This diff's bid levels, in the venue's order."""
        return self.on_side(BIDS)

    @property
    def asks(self) -> tuple[PriceLevel, ...]:
        """This diff's ask levels, in the venue's order."""
        return self.on_side(ASKS)

    @property
    def is_removal_only(self) -> bool:
        """Whether every level this diff carries is a removal."""
        return bool(self.levels) and all(l.is_removal for l in self.levels)

    def canonical(self) -> dict[str, object]:
        """This row's canonical mapping — the form the content hash is taken over.

        Levels are ordered by side then by price, so two rows carrying the same
        book agree on their hash whatever order the venue listed its levels in:
        a venue that merely reordered a diff has not changed a single price.
        The venue's own order is what is *persisted*, because that is what a
        human diffing two records reads; the canonical form answers *did the
        book change?*, which is a different question.
        """
        return {
            "symbol": self.symbol,
            "window_start": self.window_start.isoformat(),
            "first_update_id": self.first_update_id,
            "last_update_id": self.last_update_id,
            "levels": [
                {"side": str(level.side), "price": level.price, "quantity": level.quantity}
                for level in sorted(
                    self.levels, key=lambda l: (str(l.side), l.price)
                )
            ],
        }


def _parse_level(entry: object, side: Side, where: str) -> PriceLevel:
    # Two spellings are in the wild and both are accepted: the array form
    # (``["price", "qty"]``, which is what the delta feeds send) and the object
    # form (``{"price": ..., "quantity": ...}``).  A venue that sends anything
    # else is refused rather than guessed at.
    if isinstance(entry, Mapping):
        if "price" not in entry:
            raise BookDiffParseError(f"{where} is an object with no 'price' field")
        if "quantity" not in entry and "qty" not in entry:
            raise BookDiffParseError(
                f"{where} is an object with neither a 'quantity' nor a 'qty' field"
            )
        raw_quantity = entry["quantity"] if "quantity" in entry else entry["qty"]
        return PriceLevel(
            side=side,
            price=_scalar_field(entry["price"], f"{where}.price"),
            quantity=_scalar_field(raw_quantity, f"{where}.quantity"),
        )
    if isinstance(entry, (list, tuple)):
        if len(entry) < 2:
            raise BookDiffParseError(
                f"{where} is a sequence of {len(entry)}; a level is "
                f"[price, quantity]"
            )
        return PriceLevel(
            side=side,
            price=_scalar_field(entry[0], f"{where}[0]"),
            quantity=_scalar_field(entry[1], f"{where}[1]"),
        )
    raise BookDiffParseError(
        f"{where} is {type(entry).__name__}; a level is [price, quantity] or "
        f"an object with 'price' and 'quantity'"
    )


def _parse_side_levels(
    entries: object, side: Side, where: str
) -> list[PriceLevel]:
    if entries is None:
        # A diff may legitimately carry one side only — Binance's depth delta
        # sends ``b`` and ``a`` as separate lists, and a touched-side-only
        # message is ordinary.  An absent side is an empty side, not a
        # malformed diff.
        return []
    if isinstance(entries, (str, bytes, Mapping)) or not isinstance(
        entries, Iterable
    ):
        raise BookDiffParseError(
            f"{where} is {type(entries).__name__}; expected a list of levels"
        )
    return [
        _parse_level(entry, side, f"{where}[{index}]")
        for index, entry in enumerate(entries)
    ]


def _row_from_mapping(entry: Mapping, index: int) -> BookDiffRow:
    where = f"diffs[{index}]"
    symbol = entry.get("symbol", entry.get("s"))
    if not isinstance(symbol, str) or not symbol:
        raise BookDiffParseError(
            f"{where} has no non-empty 'symbol' string (got {symbol!r})"
        )

    # The event time wears several spellings across venues; all of them are
    # epoch milliseconds, except ``window_start`` — which is this module's own
    # spelling, written by _row_to_envelope, and is an ISO instant already on
    # the grid.  It is required, and required loudly: without it the diff cannot
    # be placed on the 100 ms grid, and reaching for our own clock instead would
    # invent a fact about when the venue saw the book — a raw row whose window
    # is a guess is worse than no row, because nothing downstream can tell the
    # guess from the truth.
    raw_time = None
    for key in (
        "event_time",
        "eventTime",
        "E",
        "timestamp",
        "time",
        "ts",
        "window_start",
    ):
        if key in entry:
            raw_time = entry[key]
            break
    if raw_time is None:
        raise BookDiffParseError(
            f"{where} ({symbol}) carries no event time; a raw diff cannot be "
            f"placed on the 100ms grid without the venue's own instant, and "
            f"substituting ours would invent one"
        )
    event_time = _event_time_field(raw_time, f"{where}.event_time")

    # The update-id range: Binance spells it ``U``/``u``, others spell it out.
    raw_first = None
    for key in ("first_update_id", "firstUpdateId", "U"):
        if key in entry:
            raw_first = entry[key]
            break
    raw_last = None
    for key in ("last_update_id", "lastUpdateId", "final_update_id", "u"):
        if key in entry:
            raw_last = entry[key]
            break
    if raw_first is None or raw_last is None:
        missing = "first" if raw_first is None else "last"
        raise BookDiffParseError(
            f"{where} ({symbol}) carries no {missing} update id; the range is "
            f"what a continuity check reads"
        )

    levels: list[PriceLevel] = []
    # Bids and asks, in whichever spelling the venue used.  Checked in a fixed
    # order so a payload carrying both never depends on dict iteration order.
    for side, keys in (
        (BIDS, ("bids", "b")),
        (ASKS, ("asks", "a")),
    ):
        for key in keys:
            if key in entry:
                levels.extend(
                    _parse_side_levels(entry[key], side, f"{where}.{key}")
                )
                break

    return BookDiffRow(
        symbol=symbol,
        window_start=event_time,
        first_update_id=_update_id_field(raw_first, f"{where}.first_update_id"),
        last_update_id=_update_id_field(raw_last, f"{where}.last_update_id"),
        levels=levels,
    )


def _as_diff_list(body: object) -> Sequence[object]:
    # The diffs may arrive as a bare list, nested under one of the common
    # wrapper keys, or as a single-diff object (a caller that flushed one diff
    # is as legitimate as one that flushed a batch).  Looked for in this order
    # so a bare list is never mistaken for a wrapper, and a single-diff object
    # is never mistaken for a wrapper: the wrapper keys are checked only when
    # the object is not already a diff.
    if isinstance(body, list):
        return body
    if isinstance(body, Mapping):
        for key in _WRAPPER_KEYS:
            nested = body.get(key)
            if isinstance(nested, list):
                return nested
        if "symbol" in body or "s" in body:
            return [body]
    raise BookDiffParseError(
        "book-diff payload has no diffs list; the document is not a depth "
        "delta response"
    )


@dataclass(frozen=True)
class BookDiffBatch:
    """One flush's raw diffs — the unit this stream persists.

    A batch is what a worker cycle writes: whatever diffs the feed delivered
    since the last cycle, across as many symbols and as many 100 ms windows as
    that flush happened to carry.  It deliberately makes **no completeness claim
    about any window**.  A window is complete when the feed says it is, not when
    a file ends, and a reader therefore unions by ``window_start`` across
    batches (see :meth:`BookDiffStore.rows_in_window`) rather than reading one
    file as one window.  That is what keeps 100 ms resolution from costing one
    file per 100 ms: the resolution is a fact about the rows, and the file count
    is a fact about the deployment's cycle pacing.

    ``rows`` keeps the venue's order, because that is the order a human reading
    the record will read — the same asymmetry funding draws between its
    persisted document and its canonical hash.  A batch with no rows is refused:
    an empty flush is a rate-limit body, a truncated frame or a reconnect
    with nothing behind it, never a diff.
    """

    rows: Sequence[BookDiffRow]

    def __post_init__(self) -> None:
        rows = list(self.rows)
        if not rows:
            # Refused deliberately.  An empty diff response is a failed or
            # truncated flush — never data — and persisting it would make a
            # failed cycle indistinguishable from a quiet one in the very log
            # the derived-feature recompute reads as the book's history.
            raise BookDiffParseError(
                "a book-diff batch must carry at least one row; an empty batch "
                "is a failed flush, not a quiet book"
            )
        for row in rows:
            if not isinstance(row, BookDiffRow):
                raise BookDiffParseError(
                    "a book-diff batch's rows must be BookDiffRow instances, "
                    f"got {type(row).__name__}"
                )
        object.__setattr__(self, "rows", tuple(rows))

    def __len__(self) -> int:
        """How many raw diffs this batch carries — its row count."""
        return len(self.rows)

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this batch carries, in the venue's order, deduplicated."""
        seen: dict[str, None] = {}
        for row in self.rows:
            seen.setdefault(row.symbol, None)
        return tuple(seen)

    @property
    def window_start(self) -> datetime:
        """The earliest window this batch touches — its span's inclusive start."""
        return min(row.window_start for row in self.rows)

    @property
    def window_end(self) -> datetime:
        """One slice past the latest window this batch touches.

        The batch's exclusive span end, and the value retention is decided from:
        a batch is expired only when *this* instant has fallen out of the
        window, so a batch whose newest slice is still inside the window is
        retained whole.
        """
        return max(row.window_start for row in self.rows) + SLICE

    def level_count(self) -> int:
        """How many price levels this batch's rows carry in total."""
        return sum(len(row.levels) for row in self.rows)

    def for_symbol(self, symbol: str) -> tuple[BookDiffRow, ...]:
        """This batch's rows for ``symbol``, in the venue's order."""
        return tuple(row for row in self.rows if row.symbol == symbol)

    def canonical_bytes(self) -> bytes:
        """The batch's canonical JSON bytes — the thing content-hashed.

        Canonical means rows in a deterministic order (window, then symbol, then
        update-id range), keys sorted, and the tightest separators — so two
        flushes carrying the same book hash identically whatever order the venue
        delivered its symbols in and whatever whitespace the transport added.
        This is what makes :attr:`BookDiffRecord.source_sha256` a *content*
        hash: a flush that changed one quantity does not agree on it, and one
        that merely reordered its diffs does.  Note the deliberate asymmetry
        with the persisted document, which keeps the venue's own order.
        """
        ordered = sorted(
            self.rows,
            key=lambda r: (r.window_start, r.symbol, r.first_update_id, r.last_update_id),
        )
        return json.dumps(
            {"rows": [row.canonical() for row in ordered]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def source_sha256(self) -> str:
        """The sha256 of :meth:`canonical_bytes` — the batch's identity."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def parse_book_diffs(document: object) -> BookDiffBatch:
    """Parse a depth-delta payload into a :class:`BookDiffBatch`.

    Accepts the venue's response as decoded JSON — a single diff mapping, a list
    of diffs, a wrapper some endpoints use (``{"diffs": [...]}``), a JSON bytes
    or string body, or an already-parsed :class:`BookDiffBatch` — and refuses
    anything that is not a well-formed set of diffs with
    :class:`BookDiffParseError`.

    Strict about the shape this system owns: each diff must name its symbol and
    carry both an update-id range whose first id does not exceed its last and an
    event time (without which it cannot be placed on the 100 ms grid), a level
    must be a ``[price, quantity]`` pair or an object carrying the same, price
    and quantity must be scalars, and a diff must not list one price twice on
    one side.  Tolerant where the venue is free: either side may be absent (a
    touched-side-only diff is ordinary), a diff may carry a sequence number, a
    transact time or a symbol code alongside the fields this module reads, and
    they are ignored — this module persists exactly the fields a raw diff is.
    """
    if isinstance(document, BookDiffBatch):
        return document
    if isinstance(document, (bytes, bytearray, str)):
        try:
            decoded = json.loads(document)
        except ValueError as exc:
            raise BookDiffParseError(
                f"book-diff payload is not valid JSON: {exc}"
            ) from exc
    else:
        decoded = document

    entries = _as_diff_list(decoded)
    rows: list[BookDiffRow] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise BookDiffParseError(
                f"diffs[{index}] is {type(entry).__name__}; expected an object"
            )
        rows.append(_row_from_mapping(entry, index))
    return BookDiffBatch(rows=rows)


#: A fetch: return the venue's depth-delta response, as JSON bytes, a JSON
#: string, a decoded mapping/list, or an already-parsed batch.
#:
#: The seam the deployment's websocket client fills.  This member ships no
#: websocket client — like the funding worker, which is handed its REST fetch
#: rather than owning one — so the venue's auth, rate limits and reconnect
#: policy stay the stream worker's business, and the store stays testable
#: without a network.  Whatever the fetch returns is parsed before anything is
#: written, so a failed flush never consumes a sequence.
BookDiffFetch = Callable[[], Union[bytes, str, Sequence, Mapping, BookDiffBatch]]


@dataclass(frozen=True)
class BookDiffRecord:
    """One persisted flush: the sequence it landed under and the diffs it carried.

    ``sequence`` is the record's position in the stream's append-only log —
    ``1`` for the first flush, then ``2, 3, ...`` — and, because the log is
    feature 28's staging area, it is also the sequence of the batch the envelope
    bytes were committed as.  ``written_at`` is when *we* persisted the flush
    (UTC, timezone-aware) and is deliberately kept apart from the rows'
    ``window_start``, which is when *the venue* saw the book: retention is
    decided from the former and the 100 ms grid from the latter, and conflating
    them would let our own ingest lag decide which window a diff belongs to.

    Two hashes, deliberately distinct, exactly as funding's record carries them:
    ``source_sha256`` is over the *document* and answers "did the book change?";
    ``payload_sha256`` is over the *bytes written* — envelope and rows together —
    and is the file's identity, the same value the seal's MANIFEST will record
    for it.  ``path`` names the ``<sequence>.bin`` the bytes were committed to,
    so a seal or an operator can point at the exact artifact; it is never
    written through, because the only way to add a record is another
    :meth:`BookDiffStore.record`.
    """

    sequence: int
    written_at: datetime
    batch: BookDiffBatch
    source_sha256: str
    payload_sha256: str
    path: Path

    @property
    def row_count(self) -> int:
        """How many raw diffs this record carries."""
        return len(self.batch)

    @property
    def window_start(self) -> datetime:
        """The earliest 100 ms window this record covers."""
        return self.batch.window_start

    @property
    def window_end(self) -> datetime:
        """One slice past the latest 100 ms window this record covers.

        The instant retention compares against the cutoff: a record expires
        when this has fallen out of the window, so a record touching the cutoff
        is retained whole.
        """
        return self.batch.window_end

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this record carries, in the venue's order."""
        return self.batch.symbols

    def rows_in_window(
        self, symbol: str, window_start: datetime
    ) -> tuple[BookDiffRow, ...]:
        """This record's rows for ``symbol`` in one 100 ms window.

        Matched on the *aligned* window, so a caller may pass any instant inside
        the window it means rather than having to floor it first.
        """
        wanted = align_to_window(window_start)
        return tuple(
            row
            for row in self.batch.for_symbol(symbol)
            if row.window_start == wanted
        )


class BookDiffStore:
    """The append-only log of raw book diffs, and its rolling 90 day window.

    Records live at ``<lake>/staging/bookDiffs/<sequence>.bin``, one file per
    flush, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a record is written once,
    atomically (temp file, ``fsync``, ``rename``), and never rewritten: the
    underlying batch store refuses a second batch at a sequence it already
    holds.

    The retention window is the other half, and it is the half no earlier stream
    has: :meth:`prune` retires whole records whose newest slice has fallen
    outside :data:`RETENTION`, through :meth:`StagingArea.retire`.  The window
    is therefore *rolling* in the ordinary sense — data leaves at the far end as
    data arrives at the near end — while what is retained stays byte-identical
    to what was committed, because retirement takes a whole batch and never
    edits one.

    Construction reads whatever a prior run left on disk, so a restarted process
    knows where the log reached and which records survived the last prune,
    without a network call — the same seed-from-what-is-durable moment the
    resume watermark gives a restarted worker.  A store is one-writer-per-stream,
    like the funding and exchangeInfo stores: a second concurrent appender would
    race for the same sequence and be refused by the batch store rather than
    silently overwriting.

    The store reads no clock.  ``now`` is a parameter everywhere it is needed
    (:meth:`prune`, :meth:`expired_sequences`, :meth:`retained`), because the
    window is a fact about elapsed time and §12 keeps wall-clock reads out of
    checked code; the worker that owns the cadence passes its injected clock in.
    """

    def __init__(self, staging: StagingArea) -> None:
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"the book-diff store writes into a StagingArea, "
                f"got {type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "BookDiffStore":
        """The store over the lake's staging area, resolved from the environment.

        The same resolution the ingest workers and the sealing service use
        (``LAKE_ROOT``, defaulting to ``lake/`` beside the workspace root), so
        records are written into the very area the seal copies out of — there is
        no second root that could drift from the first, and no second retention
        policy that could contradict this one.
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
        return self._staging.path_for(BOOK_DIFFS_STREAM)

    def path_for(self, sequence: int) -> Path:
        """The file sequence ``sequence`` is committed to."""
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise TypeError(f"a sequence is an integer, not {type(sequence).__name__}")
        if sequence <= 0:
            raise ValueError(f"a sequence must be positive, got {sequence}")
        return self.root / f"{sequence}.bin"

    # -- Recording ------------------------------------------------------------

    def record(
        self,
        document: Union[bytes, str, Sequence, Mapping, BookDiffBatch],
        *,
        written_at: datetime,
    ) -> BookDiffRecord:
        """Persist one flush as the next record; never overwrite a prior one.

        The document is parsed and validated *first*, so a failed flush consumes
        no sequence number and leaves the log untouched; then it is written as
        the next record — ``current + 1`` — into the stream's append-only
        staging log.  The previous records are not read, moved or rewritten:
        adding a record is an append, and the store's duplicate-sequence refusal
        means this method has no code path that could overwrite one.

        ``written_at`` is required and must be timezone-aware: it is the instant
        retention is later decided from, and a naive timestamp would make "has
        this record fallen out of the window?" unanswerable at exactly the
        boundary the rule turns on.  The store does not read a clock of its own
        — the caller that flushed owns the time the flush happened.
        """
        parsed = parse_book_diffs(document)
        _require_aware(written_at, "written_at")

        sequence = self._staging.current(BOOK_DIFFS_STREAM) + 1
        envelope = {
            "stream": str(BOOK_DIFFS_STREAM),
            "sequence": sequence,
            "written_at": _isoformat_utc(written_at),
            "source_sha256": parsed.source_sha256,
            "window_start": _isoformat_utc(parsed.window_start),
            "window_end": _isoformat_utc(parsed.window_end),
            _DOCUMENT_KEY: [_row_to_envelope(row) for row in parsed.rows],
        }
        payload = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        batch = self._staging.append(
            BOOK_DIFFS_STREAM, payload=payload, rows=len(parsed)
        )
        return BookDiffRecord(
            sequence=batch.sequence,
            written_at=written_at.astimezone(_UTC),
            batch=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            path=batch.path,
        )

    # -- Reading --------------------------------------------------------------

    def records(self) -> tuple[BookDiffRecord, ...]:
        """Every retained record, oldest first.

        Read back from the staging log in ascending sequence order, each
        envelope verified against the sequence its filename claims and the
        document hash it recorded — so a reader gets either the record that was
        committed or a clear :class:`BookDiffCorruptError`, never a
        plausible-looking book assembled from damaged bytes.
        """
        return tuple(
            self._read(batch) for batch in self._staging.staged(BOOK_DIFFS_STREAM)
        )

    def current(self) -> BookDiffRecord | None:
        """The most recent record, or ``None`` when nothing has been persisted."""
        batches = self._staging.staged(BOOK_DIFFS_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def previous(self) -> BookDiffRecord | None:
        """The record before :meth:`current`, or ``None`` when there is none.

        The comparison point a flush reports against: a worker can say whether
        the flush it just persisted carried a different book than the last one,
        which is the difference between a quiet cycle and a cycle the derived
        features must absorb.
        """
        batches = self._staging.staged(BOOK_DIFFS_STREAM)
        if len(batches) < 2:
            return None
        return self._read(batches[-2])

    def record_at(self, sequence: int) -> BookDiffRecord | None:
        """The record persisted under ``sequence``, or ``None`` if never recorded.

        ``None`` distinguishes *that sequence was never recorded — or has since
        been retired* from *the log holds a record under that number but its
        bytes are damaged*, which :meth:`records` and :meth:`current` raise for.
        A caller walking the retained history gets the honest absence rather
        than an exception for a number the window has already given back.
        """
        self.path_for(sequence)  # validates the argument; raises on a bad one
        for batch in self._staging.staged(BOOK_DIFFS_STREAM):
            if batch.sequence == sequence:
                return self._read(batch)
        return None

    def row_count(self) -> int:
        """How many raw diffs the retained records hold in total."""
        return sum(record.row_count for record in self.records())

    def windows(self) -> tuple[datetime, ...]:
        """The 100 ms windows the retained records touch, ascending.

        The distinct windows across every retained record — the reader seam the
        derived book features (feature 20) walk, because a window's diffs are
        spread across however many flushes happened to carry them and the
        window, not the file, is the unit a 1 s feature is computed over.
        """
        seen: dict[datetime, None] = {}
        for record in self.records():
            for row in record.batch.rows:
                seen.setdefault(row.window_start, None)
        return tuple(sorted(seen))

    def rows_in_window(
        self, symbol: str, window_start: datetime
    ) -> tuple[BookDiffRow, ...]:
        """Every retained raw diff for ``symbol`` in one 100 ms window.

        Unioned across *all* records, in window order, and matched on the
        aligned window so a caller may pass any instant inside the window it
        means.  This is the read the derived features stand on: a batch makes no
        completeness claim about a window, so the honest way to ask what the
        book did in a window is to ask the log, not to open one file.
        """
        wanted = align_to_window(window_start)
        found: list[BookDiffRow] = []
        for record in self.records():
            found.extend(record.rows_in_window(symbol, wanted))
        return tuple(found)

    # -- The rolling 90 day window --------------------------------------------

    def cutoff(self, now: datetime) -> datetime:
        """The instant a record must have outlived to be expired: ``now - RETENTION``."""
        _require_aware(now, "now")
        return now.astimezone(_UTC) - RETENTION

    def is_expired(self, record: BookDiffRecord, now: datetime) -> bool:
        """Whether ``record`` has fallen wholly outside the retention window.

        Expired when the record's *newest* slice is at or before the cutoff, so
        a record that still touches the window — even by one slice — is retained
        whole.  Retention over-keeps by at most a single record and never splits
        one, which is what lets the window close without rewriting a byte.
        """
        return record.window_end <= self.cutoff(now)

    def expired_sequences(self, now: datetime) -> tuple[int, ...]:
        """The sequences the window has passed, ascending; deletes nothing.

        The observability half of retention: an operator (or a test) can see
        what is due to go without anything leaving the lake, and the answer is
        what :meth:`prune` will retire.  Never includes the newest committed
        sequence — the watermark anchor a stream keeps so its numbering stays
        monotonic across a restart.
        """
        return tuple(
            record.sequence for record in self._expired_records(now)
        )

    def retained(self, now: datetime) -> tuple[BookDiffRecord, ...]:
        """The records still inside the retention window, oldest first.

        The complement of :meth:`expired_sequences` computed without pruning, so
        a caller can ask what the window will leave behind before anything is
        deleted.
        """
        expired = {record.sequence for record in self._expired_records(now)}
        return tuple(
            record for record in self.records() if record.sequence not in expired
        )

    def prune(self, now: datetime) -> RetentionReport:
        """Retire every record that has fallen out of the window; report what went.

        The rolling 90 day window, made structural.  Records are time-ordered
        (each flush's window is at or after the last one's, because the feed
        delivers diffs in time order and the log is append-only), so this reads
        from the oldest and **stops at the first record still inside the
        window**: in steady state a prune walks one or two records rather than
        the whole retained window, so the cost of the policy does not grow with
        the size of the data the policy is keeping.

        The newest committed record is never retired, whatever the clock says.
        The staging watermark is derived from the files on disk, so retiring
        every file would let the next append reuse a sequence this log has
        already spent and :meth:`record_at` would begin answering with a
        different record than it used to.  A stream whose entire window has
        lapsed therefore keeps its last record as the anchor and keeps counting
        upward — which is also the honest report, since ``retained`` names it.

        Returns a :class:`RetentionReport` naming the cutoff, what was retired,
        how many raw diffs went with it, and what the window retains now — the
        numbers an operator needs to see that the policy ran and what it cost.
        """
        _require_aware(now, "now")
        cutoff = self.cutoff(now)
        # Count the rows off the records before they go: after the retire their
        # bytes are gone and the count would be unrecoverable, and the number is
        # the whole point of reporting the window in §4.1's units.
        expiring = self._expired_records(now)
        retired = self._staging.retire(
            BOOK_DIFFS_STREAM, [record.sequence for record in expiring]
        )
        # ``retire`` returns what it actually removed, which is the same set
        # unless a file had already gone missing; trust its answer, not the
        # request, and count the rows of the records it confirms.
        removed = set(retired)
        return RetentionReport(
            now=now.astimezone(_UTC),
            cutoff=cutoff,
            retired=retired,
            rows_retired=sum(
                record.row_count
                for record in expiring
                if record.sequence in removed
            ),
            retained_sequences=tuple(
                batch.sequence for batch in self._staging.staged(BOOK_DIFFS_STREAM)
            ),
        )

    def _expired_records(self, now: datetime) -> tuple[BookDiffRecord, ...]:
        # Walk oldest-first and stop at the first record still inside the
        # window, so this reads a prefix of the log rather than all of it: in
        # steady state that is one or two records, and the cost of the policy
        # does not grow with the size of the data the policy is keeping.
        #
        # The stop is what makes the walk cheap, and it is deliberately the
        # *safe* direction when the log is not perfectly ordered.  Appends are
        # normally time-ordered — the feed delivers diffs in time order — but
        # feature 26's backfill can append an older window to a stream after a
        # newer one has landed, and this walk would then stop before reaching
        # it.  That leaves an expired record in the lake, which is over-keeping:
        # the window's promise is a guarantee about what has *left*, and
        # erring toward keeping is the only direction that cannot lose data a
        # caller still expects.  What it can never do is retire a record that
        # still touches the window, because that is checked per record.
        #
        # The newest committed sequence is excluded unconditionally — see prune.
        _require_aware(now, "now")
        batches = self._staging.staged(BOOK_DIFFS_STREAM)
        if not batches:
            return ()
        anchor = batches[-1].sequence
        expired: list[BookDiffRecord] = []
        for batch in batches:
            if batch.sequence == anchor:
                break
            record = self._read(batch)
            # The stop condition is :meth:`is_expired` — the one definition of
            # what leaves the window — negated.  Asking the same question the
            # rest of the class answers keeps "which records are due to go" and
            # "what will prune take" from ever being two rules that can drift
            # apart; the walk just adds the observation that in sorted order,
            # the first record to keep means every later one is kept too.
            if not self.is_expired(record, now):
                break
            expired.append(record)
        return tuple(expired)

    def _read(self, batch) -> BookDiffRecord:
        # Read one committed batch back into a record, verifying as it goes.
        # The three checks below are the read half of the append-only guarantee:
        # the bytes are the bytes that were committed, under the sequence the
        # filename claims, carrying the document the envelope's hash vouches
        # for.  A mismatch is corruption (or tampering) on a log the derived
        # features rebuild the book from, so it is raised rather than papered
        # over — a plausible-looking book assembled from damaged bytes is a
        # market that never existed.
        try:
            envelope = json.loads(batch.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise BookDiffCorruptError(
                f"book-diff record {batch.sequence} is not readable as a JSON "
                f"envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise BookDiffCorruptError(
                f"book-diff record {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise BookDiffCorruptError(
                f"book-diff record {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"record envelope this store wrote"
            )
        recorded = envelope["sequence"]
        if recorded != batch.sequence:
            raise BookDiffCorruptError(
                f"book-diff record file {batch.sequence}.bin records sequence "
                f"{recorded!r}; the file does not describe itself"
            )
        document = parse_book_diffs(envelope[_DOCUMENT_KEY])
        recorded_hash = envelope["source_sha256"]
        if recorded_hash != document.source_sha256:
            raise BookDiffCorruptError(
                f"book-diff record {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{document.source_sha256!r}; the file's bytes are not the "
                f"bytes that were committed"
            )
        return BookDiffRecord(
            sequence=batch.sequence,
            written_at=_parse_timestamp(envelope["written_at"], batch.sequence),
            batch=document,
            source_sha256=document.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


@dataclass(frozen=True)
class RetentionReport:
    """What one prune did: the cutoff, what left, and what the window now holds.

    The report a monitor logs and an operator reads to answer *is the 90 day
    window actually rolling?* — a question that is otherwise unanswerable from
    outside, because a window that quietly stopped pruning and a window that is
    simply full look identical from the lake.  ``rows_retired`` is carried as
    well as the sequence range so the cost of the policy is visible in the units
    §4.1 states it in (raw diffs, and the 50–200 GB/month they add up to).
    """

    now: datetime
    """The instant the prune ran at, UTC."""
    cutoff: datetime
    """``now - RETENTION``: a record must have outlived this to be retired."""
    retired: tuple[int, ...]
    """The sequences retired, ascending — empty when the window was already closed."""
    rows_retired: int
    """How many raw diffs went with the retired records."""
    retained_sequences: tuple[int, ...]
    """The sequences still in the log after the prune, ascending."""

    @property
    def retired_count(self) -> int:
        """How many records were retired by this prune."""
        return len(self.retired)

    def render(self) -> str:
        """One line an operator reads and knows the window moved."""
        if not self.retired:
            return (
                f"bookDiffs retention: nothing expired at {self.now.isoformat()} "
                f"(cutoff {self.cutoff.isoformat()}, "
                f"{len(self.retained_sequences)} records retained)"
            )
        return (
            f"bookDiffs retention: retired {self.retired_count} records "
            f"({self.rows_retired} raw diffs, sequences "
            f"{self.retired[0]}..{self.retired[-1]}) at "
            f"{self.now.isoformat()}; {len(self.retained_sequences)} records "
            f"retained"
        )


def _row_to_envelope(row: BookDiffRow) -> dict[str, object]:
    # Persisted in the venue's own order, with the two sides kept distinct so a
    # reader (and a human diffing two records) sees the diff as the feed sent
    # it.  The canonical form used for hashing is a different thing and is not
    # written to disk.
    return {
        "symbol": row.symbol,
        "window_start": _isoformat_utc(row.window_start),
        "first_update_id": row.first_update_id,
        "last_update_id": row.last_update_id,
        "bids": [
            {"price": level.price, "quantity": level.quantity} for level in row.bids
        ],
        "asks": [
            {"price": level.price, "quantity": level.quantity} for level in row.asks
        ],
    }


def _require_aware(moment: object, what: str) -> None:
    # Both the 100 ms grid and the retention window are decided by arithmetic on
    # instants, so a naive timestamp would be unsubtractable from an aware one at
    # exactly the boundary each rule turns on.  Refused here, where a caller can
    # still fix its clock handling, rather than silently assumed to be UTC and
    # recorded wrong.
    if not isinstance(moment, datetime):
        raise TypeError(f"{what} must be a datetime, not {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{what} must be timezone-aware; a naive timestamp cannot place a "
            f"diff on the 100ms grid or date a retention cutoff"
        )


def _isoformat_utc(moment: datetime) -> str:
    # Persisted in UTC with an explicit offset, so the record says when the
    # flush happened without the reader assuming.
    return moment.astimezone(_UTC).isoformat()


def _parse_timestamp(raw: object, sequence: int) -> datetime:
    if not isinstance(raw, str):
        raise BookDiffCorruptError(
            f"book-diff record {sequence} records written_at {raw!r}; expected "
            f"an ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise BookDiffCorruptError(
            f"book-diff record {sequence} records an unparseable written_at "
            f"{raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise BookDiffCorruptError(
            f"book-diff record {sequence} records a naive written_at {raw!r}; "
            f"the retention window needs a comparable instant"
        )
    return parsed.astimezone(_UTC)


class BookDiffWorker:
    """The 100 ms book-diff worker: flush raw diffs, then roll the window.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the ``bookDiffs``
    stream class, so the supervisor of feature 16 runs it on its own thread
    alongside every other stream and converts whatever it raises into that
    stream's own failure.  One cycle is three steps, in this order:

    * **Prune.**  Retention is a property of elapsed time, not of ingest health,
      so the window advances *first* — a cycle whose fetch then fails has still
      honoured the 90 day promise, and a feed that has been down for a week
      still gives back the data that has left the window.  Doing it here rather
      than in a second scheduled job is what makes "rolling" true without a
      second process to keep alive.
    * **Flush.**  Call the injected :data:`BookDiffFetch`.  The websocket
      client, its auth, its rate limits and its reconnect policy are the
      deployment's business (§15's *"WS gap / reconnect"* row belongs to
      features 25 and 26); this worker owns only the persistence and the window.
    * **Record.**  Parse first, then record the batch.  A failed flush — a
      truncated frame, an error page, an empty response — raises
      :class:`BookDiffParseError` *before* anything is written, so the log never
      records a flush that did not happen.

    One cycle writes **one record**, holding however many 100 ms slices the
    flush carried.  Resolution is a fact about the rows — each row sits on the
    grid — so pacing cycles at a second rather than at 100 ms costs nothing in
    fidelity and saves three orders of magnitude of files.

    The clock is injected because the retention window is a fact about elapsed
    wall-clock time: a test must be able to place the worker on either side of
    the 90 day boundary without touching the wall clock, and §12 keeps
    wall-clock reads out of checked code in any case.  The default clock reads
    the system UTC time, which is what a deployment wants.
    """

    def __init__(
        self,
        store: BookDiffStore,
        fetch: BookDiffFetch,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, BookDiffStore):
            raise TypeError(
                f"the book-diff worker persists into a BookDiffStore, "
                f"got {type(store).__name__}"
            )
        if not callable(fetch):
            raise TypeError(
                f"fetch must be a zero-argument callable returning the venue's "
                f"depth-delta response, got {type(fetch).__name__}"
            )
        if clock is not None and not callable(clock):
            raise TypeError(
                f"clock must be a callable returning a datetime, "
                f"got {type(clock).__name__}"
            )
        self._store = store
        self._fetch = fetch
        self._clock = clock if clock is not None else _utc_now
        self._last_retention: RetentionReport | None = None

    # -- IngestWorker ---------------------------------------------------------

    @property
    def stream_class(self) -> StreamClass:
        """The one stream class this worker owns — ``bookDiffs``."""
        return BOOK_DIFFS_STREAM

    @property
    def store(self) -> BookDiffStore:
        """The record log this worker appends to and prunes."""
        return self._store

    def last_retention(self) -> RetentionReport | None:
        """The report from this worker's most recent prune, or ``None``.

        ``None`` means no cycle has run yet — distinct from a cycle that ran and
        expired nothing, which is a report with an empty ``retired``.  A monitor
        reads this to see the window move without reaching into the store.
        """
        return self._last_retention

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Run one cycle: roll the window, flush, persist.

        Returns the persisted record's sequence as the cycle's watermark, so a
        monitor sees the log advance, and ``rows_written`` as the number of raw
        diffs the record carries — the unit §4.1 states this stream's size in.
        """
        now = self._clock()
        _require_aware(now, "the clock")
        # Retention first: the window is a property of elapsed time, so it moves
        # on this cycle whether or not the flush that follows succeeds.
        self._last_retention = self._store.prune(now)
        document = self._fetch()
        record = self._store.record(document, written_at=now)
        return CycleResult(
            rows_written=record.row_count, sequence=record.sequence
        )


def _utc_now() -> datetime:
    """The default clock: the current UTC time, timezone-aware."""
    return datetime.now(_UTC)


def register_book_diff_worker(
    fetch: BookDiffFetch,
    store: Optional[BookDiffStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], BookDiffWorker]:
    """Register a worker factory bound to an explicitly wired fetch.

    The operator path: hand in the websocket client's fetch (and, when it is not
    the lake's staging area, the store), and this registers a worker factory
    bound to those collaborators.  Registration replaces the auto-discovered
    factory of the same class in the registry it targets — the registry's own
    rule, *a re-registered class is a revision of the same worker, never a
    second worker* — so a deployment that wires a client does not end up with
    two book-diff workers competing for the same sequence numbers.

    ``registry`` defaults to a **private** registry, not the process-wide one:
    a registration is a deployment act, and silently replacing the
    auto-discovered worker for every later composition in the process would hand
    unrelated callers — tests especially — a worker bound to a store that may
    since have vanished.  A caller that means to reconfigure the running process
    passes :func:`~nullius_ingest.registry.default_worker_registry` explicitly,
    matching :func:`~nullius_ingest.registry.register_worker`.

    Returns the registered factory, so a caller can build the worker it just
    registered — over the private registry by default — without reaching back
    into it.
    """
    if not callable(fetch):
        raise TypeError(
            f"fetch must be a zero-argument callable returning the venue's "
            f"depth-delta response, got {type(fetch).__name__}"
        )

    def build() -> BookDiffWorker:
        resolved_store = store if store is not None else BookDiffStore.from_env()
        return BookDiffWorker(resolved_store, fetch, clock=clock)

    # Register through a private registry by default, never the process-wide
    # one.  Registration is a *deployment* act: writing a caller's wiring into
    # the default registry would replace the auto-discovered worker for every
    # later composition in the process — including tests, which would then be
    # handed a worker bound to a store that has since been deleted.  A caller
    # that genuinely means to reconfigure the running process passes the default
    # registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        BOOK_DIFFS_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(BOOK_DIFFS_STREAM)
def build_book_diff_worker() -> BookDiffWorker:
    """Compose the book-diff worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    Collaborators come from the environment the way every other ingest seam
    does: the store is the lake's staging area (:meth:`BookDiffStore.from_env`),
    so records land in the very area the seal copies out of.  The fetch has no
    environment-resolved default — this member ships no websocket client, so the
    venue's auth, rate limits and reconnect policy stay the deployment's
    business — and a deployment wires it with :func:`register_book_diff_worker`.
    Until then the worker still composes and its cycle reports that stream's own
    failure, which is feature 16's contract: an unconfigured stream is a row in
    the report, not a component that fails to load.
    """
    return BookDiffWorker(BookDiffStore.from_env(), _unconfigured_fetch)


def _unconfigured_fetch() -> object:
    """The fetch used when a deployment has not wired a websocket client yet.

    Raising here, rather than at composition time, keeps the plugin shaped the
    way feature 16 wants it: an unconfigured stream is that stream's failure in
    the report, not a component that fails to compose.
    """
    raise BookDiffError(
        "no book-diff fetch is configured; register the worker with a fetch "
        "returning the venue's depth-delta response "
        "(nullius_ingest.register_book_diff_worker(fetch, store=..., "
        "registry=default_worker_registry()))"
    )
