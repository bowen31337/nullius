"""L1 best bid/ask snapshots off the websocket feed, at 1 second resolution, retained permanently.

app_spec.xml feature 19 states the behaviour: *"System ingests L1 best
bid/ask snapshots at 1 second resolution, persisting rows retained
permanently."*  docs/nullius-tech-architecture.md §4.1 fixes the stream's row
in the data-layer table — the L1 best bid/ask is the venue's own top-of-book
stream, the one a websocket feed delivers directly rather than one computed
from the L2 diffs — and two columns of that row are load-bearing and, taken
together, set this stream apart from every other in the table:

* **The retention is *forever*.**  Like aggTrades, funding and exchangeInfo,
  and unlike the L2 book diffs §4.1 keeps for a rolling 90 days, the L1
  top-of-book series is kept permanently: a best bid or ask is an irreversible
  fact of the market at an instant, and a row dropped at ingest time is a row
  no replay can ever recover — the venue's book-ticker stream is live only, so
  the snapshot captured here is the only honest copy.  This module is that
  "forever" made structural: it appends each flush into the append-only staging
  area, which is written once and copied by the seal, never rewritten and never
  expired.  There is deliberately no ``prune`` here, unlike
  :mod:`nullius_ingest.book_diffs`: a retention window that removes data would
  contradict the §4.1 row this stream exists to serve.

* **The resolution is *1 second*.**  Unlike the raw L2 diffs, which §4.1 keeps
  at their native 100 ms cadence, and unlike aggTrades, which keeps every
  trade, this stream is a *resolution* stream: the venue's book-ticker feed
  fires on every quote change, which for a liquid book is many times a second,
  and this module floors each snapshot onto the 1 second grid — the feature
  tier's shared lattice — so the persisted series is one best bid/ask per
  second per symbol, whatever the venue's tick rate.  This is the deliberate
  contrast with the L2 stream: the raw tier keeps the market at full fidelity
  for the 90 days a feature can be revised against it, and this stream keeps the
  same information at a fixed, permanent, replayable cadence.

The rest of the module follows the landed websocket stream —
:mod:`nullius_ingest.agg_trades` — because an L1 book-ticker snapshot and an
aggTrade are the same kind of object to the ingest layer: a websocket flush,
parsed, placed on a grid, appended into an append-only log, retained forever.
Three pieces, mirroring it:

* **The row** — :class:`L1BookRow`: one symbol's best bid and best ask at one
  second, with the venue's fields kept in their native kinds.  The bid and ask
  prices and quantities are kept **verbatim** in the venue's own string
  spelling (``"61234.50"``, not ``Decimal``), exactly as the book diffs,
  aggTrades and funding keep their scalars: whether the venue said ``"0.00010"``
  or ``"0.0001"`` is a fact about the venue, and re-rendering it would make an
  audit unable to tell a venue change from our own lossy parse.  ``window_start``
  is the 1 second window the snapshot's event time fell in, an aware
  :class:`~datetime.datetime` — the row's resolution, and what a reader unions
  by.

* **The record** — :class:`L1BookRecord`: one *flush*, frozen, with the
  sequence it was persisted under, when it was written, the span of window
  starts it covers, the document's content hash and the hash of the bytes
  written.  The two hashes are deliberately distinct, as aggTrades', funding's
  and book diffs' records carry them: ``source_sha256`` is over the canonical
  document and answers "did the quotes change?"; ``payload_sha256`` is over the
  bytes actually committed — the file's identity, the same value the seal's
  MANIFEST will record for it.

* **The store** — :class:`L1BookStore`: an append-only log of records under the
  §4.1 staging area, at ``<lake>/staging/bookTicker/<seq>.bin``, whose every
  write is the flush's envelope.  *Persisting each flush's rows, retained
  permanently* is therefore structural, not a convention: the store appends at
  ``current + 1`` into feature 28's append-only area
  (:class:`~nullius_ingest.staging.StagingArea`), whose batch store refuses a
  second batch at a sequence it already holds and which nothing in the system
  ever expires, so a flush's bytes are frozen the moment the next flush lands
  and no flush is ever dropped by a retention window.

Layering on the stream workers of feature 16 is deliberate, as it is for every
other stream: this is one worker owning one stream class, so a failed flush is
that stream's :class:`~nullius_ingest.worker.StreamFailure` and every other
stream keeps ingesting.  The fetch is injected (:data:`L1BookFetch`) — the
member ships no websocket client, exactly as it ships no REST client, so the
venue's auth, rate limits and reconnect policy stay the deployment's business —
and the clock is injected because ``written_at`` is a fact about elapsed
wall-clock time and §12 keeps wall-clock reads out of checked code.  The member
stays stdlib-only: the moment arithmetic that floors a snapshot onto the 1
second grid is exact integer microseconds from the epoch, so no float ever
touches an instant.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, Optional, Union

from .book_features import (
    FEATURE_SLICE,
    FEATURE_SLICE_MILLISECONDS,
    _floor_to_second,
)
from .registry import WorkerRegistry, register_worker
from .staging import StagingArea
from .streams import StreamClass
from .worker import CycleResult

__all__ = [
    "L1_BOOK_STREAM",
    "L1_SLICE",
    "L1_SLICE_MILLISECONDS",
    "L1BookBatch",
    "L1BookCorruptError",
    "L1BookError",
    "L1BookFetch",
    "L1BookParseError",
    "L1BookRecord",
    "L1BookRow",
    "L1BookStore",
    "L1BookWorker",
    "build_l1_book_worker",
    "parse_l1_book",
    "register_l1_book_worker",
]

#: The stream class this module serves.  §4.1's table row for the L1 best
#: bid/ask is the stream whose resolution is *1 second* and whose retention is
#: *forever*, and the spelling here is the persisted one
#: (:class:`~nullius_ingest.streams.StreamClass`), so the staging layout and the
#: record log share it.
L1_BOOK_STREAM = StreamClass.L1_BOOK

#: The resolution §4.1's table records for this stream: one snapshot every
#: second.  This is the feature tier's 1 second lattice — the same one
#: :func:`~nullius_ingest.book_features._floor_to_second` floors the derived
#: book features onto — carried under this module's own name so the fact is
#: named where it is decided, and so the grid the snapshots are floored onto
#: cannot drift from the shared lattice.
L1_SLICE_MILLISECONDS: Final[int] = FEATURE_SLICE_MILLISECONDS
L1_SLICE: Final[timedelta] = FEATURE_SLICE

#: The envelope keys a record file carries around its rows — named so a reader
#: of a record file (an operator, a seal, a later audit) does not have to import
#: this module to know what it is looking at.  ``rows`` is the document.  The
#: two time bounds name the span of *window* starts the flush covers — distinct
#: from ``written_at``, which is when *we* persisted it — because a reader
#: walking the series wants to know which seconds a record holds without opening
#: it.
_ENVELOPE_KEYS = (
    "stream",
    "sequence",
    "written_at",
    "source_sha256",
    "first_time",
    "last_time",
)

#: Wrapper keys under which a venue endpoint may nest its snapshots — the flat
#: list and the single-object response are also accepted (see
#: :func:`parse_l1_book`), so this is a convenience, not a closed set.
_WRAPPER_KEYS = ("bookTickers", "bookTicker", "data", "results")

#: The envelope key holding the rows, named beside the keys around it so a
#: reader of a record file does not have to hunt for it.
_DOCUMENT_KEY = "rows"

_UTC = timezone.utc

#: The epoch, in UTC: the instant every venue event time is measured from.  A
#: snapshot's window start is an exact integer count of microseconds from here,
#: so no float ever touches an instant and a boundary is a boundary rather than
#: a rounding, on every platform.
_EPOCH = datetime(1970, 1, 1, tzinfo=_UTC)


class L1BookError(Exception):
    """Base for every failure this module raises.

    Raised for a document this module will not persist and for a persisted
    record it will not read: both are cases where the L1 series would otherwise
    start lying about what the venue quoted, so both fail loudly rather than
    being approximated into a record.
    """


class L1BookParseError(L1BookError):
    """A document failed to parse into a well-formed set of L1 snapshots.

    Raised before anything is written, so a malformed flush — a rate-limit
    body, an error page, a truncated frame, a snapshot missing a side — never
    consumes a sequence number and never enters the permanent series.
    """


class L1BookCorruptError(L1BookError):
    """A persisted record's bytes are not the bytes that were committed.

    Raised on the read path when a record file does not describe itself — the
    sequence in its envelope does not match its filename, or its document does
    not hash to the hash it recorded — so a reader gets either the record that
    was committed or a clear error, never a plausible-looking record assembled
    from damaged bytes.
    """


def _scalar_field(value: object, where: str) -> str:
    # Price and quantity values are persisted as the venue's own spelling, for
    # the same reason book diffs and aggTrades persist their scalars verbatim:
    # whether the venue said "61234.50" or "61234.5" is a fact about the venue,
    # and this is the raw series, so re-rendering it would destroy the one thing
    # raw data is for.  Venues are inconsistent about JSON types for the same
    # field — a price arrives as a string on one feed and a bare number on
    # another — so scalars are spelled rather than rejected, while containers
    # are refused: a nested object is a shape this module does not model, and
    # storing its ``repr`` would be a record that looks like data and is not.
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
    raise L1BookParseError(
        f"{where} is {type(value).__name__}; price and quantity values must be "
        f"scalars (the venue's own spelling is kept verbatim)"
    )


def _millis_to_utc(millis: int) -> datetime:
    # Exact: an integer count of milliseconds becomes an integer count of
    # microseconds from the epoch, and the datetime is built from that.  No
    # float and no ``fromtimestamp()`` round trip, either of which would put a
    # rounding between the venue's instant and the grid.
    return _EPOCH + timedelta(microseconds=millis * 1000)


def _event_time_field(value: object, where: str) -> datetime:
    # Two spellings mean the same thing here, and both must parse because both
    # are written by something in this system:
    #
    # * the venue's epoch milliseconds, which is what a feed sends;
    # * an ISO-8601 instant, which is what *our own record envelope* writes
    #   (``written_at`` / the window starts, already datetimes).  A store that
    #   could not read back its own spelling would fail its own round trip.
    #
    # Either way the result is an aware instant over the exact epoch; no float
    # and no ``timestamp()`` round trip, either of which would put a rounding
    # between the venue's instant and the grid.
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
                raise L1BookParseError(
                    f"{where} is the naive instant {value!r}; the series needs an "
                    f"offset to place a snapshot's instant"
                )
            return parsed
    return _millis_to_utc(_as_epoch_millis(value, where))


def _as_epoch_millis(value: object, where: str) -> int:
    # Turn a *venue-supplied* instant into an exact integer count of epoch
    # milliseconds.  Venues are inconsistent about JSON types for the same field
    # — an event time arrives as a bare number on one feed and a string on
    # another — so a float or a numeric string is coerced here, at the boundary
    # where that sloppiness is a fact about the venue.  Refusals are the
    # module's own error, not whatever ``int()`` happened to raise, because the
    # caller is a worker deciding whether the venue's shape changed.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise L1BookParseError(
            f"{where} is {type(value).__name__}; expected an epoch-millisecond "
            f"instant"
        )
    try:
        millis = int(value)
    except (TypeError, ValueError) as exc:
        raise L1BookParseError(
            f"{where} is {value!r}; expected an epoch-millisecond instant: {exc}"
        ) from exc
    if millis <= 0:
        raise L1BookParseError(
            f"{where} is {millis}; an epoch-millisecond instant is positive"
        )
    return millis


def _require_aware(moment: object, what: str) -> None:
    # A snapshot's window start and a flush's write time are both placed by
    # arithmetic on instants, so a naive timestamp would be unsubtractable from
    # an aware one at exactly the boundary each rule turns on.  Refused here,
    # where a caller can still fix its clock handling, rather than silently
    # assumed to be UTC and recorded wrong.
    if not isinstance(moment, datetime):
        raise TypeError(f"{what} must be a datetime, not {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{what} must be timezone-aware; a naive timestamp cannot place a "
            f"snapshot on the grid or date a flush's write"
        )


def _isoformat_utc(moment: datetime) -> str:
    # Persisted in UTC with an explicit offset, so the record says when a
    # snapshot happened — or when the flush was written — without the reader
    # assuming.
    return moment.astimezone(_UTC).isoformat()


def _parse_timestamp(raw: object, sequence: int) -> datetime:
    if not isinstance(raw, str):
        raise L1BookCorruptError(
            f"L1 book record {sequence} records a timestamp {raw!r}; expected an "
            f"ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise L1BookCorruptError(
            f"L1 book record {sequence} records an unparseable timestamp "
            f"{raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise L1BookCorruptError(
            f"L1 book record {sequence} records a naive timestamp {raw!r}; a "
            f"record's instant must be timezone-aware"
        )
    return parsed


@dataclass(frozen=True)
class L1BookRow:
    """One symbol's best bid and best ask, placed on the 1 second grid.

    Six facts, each load-bearing:

    * ``symbol`` — which book the snapshot is for.
    * ``window_start`` — the 1 second window the venue's event time fell in,
      floored onto the feature tier's shared 1 second lattice.  This is the
      row's resolution: several snapshots may share it only if the venue
      delivered more than one inside the same second, and a reader unions by it,
      so a window is a *set* of snapshots rather than a slot one occupies.
    * ``bid_price`` / ``ask_price`` — the venue's best bid and best ask, kept
      **verbatim** in the venue's own string spelling.  A reader never has to
      guess whether a rounding in the record was the exchange's or ours.
    * ``bid_quantity`` / ``ask_quantity`` — the size resting at the best bid and
      best ask, kept verbatim for the same reason.  These are genuine resting
      sizes — a book-ticker quote is a live level, never a removal — so no
      quantity is special-cased.

    The row is frozen: a record is what the venue sent, and a caller mutating it
    in place would be editing the permanent series.
    """

    symbol: str
    window_start: datetime
    bid_price: str
    ask_price: str
    bid_quantity: str
    ask_quantity: str

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise L1BookParseError(
                f"an L1 book snapshot must carry a non-empty symbol, "
                f"got {self.symbol!r}"
            )
        _require_aware(self.window_start, "window_start")
        object.__setattr__(self, "window_start", self.window_start.astimezone(_UTC))
        for field in ("bid_price", "ask_price", "bid_quantity", "ask_quantity"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise L1BookParseError(
                    f"{self.symbol} carries an empty {field}; a best bid/ask "
                    f"snapshot must carry a price and a quantity on each side"
                )
            object.__setattr__(self, field, str(value))

    @property
    def spread(self) -> str:
        """The best ask minus the best bid, in the venue's spelling — the row's spread.

        Kept as the venue's two spellings rather than a computed difference:
        subtracting two verbatim strings would re-render the result and lose the
        one thing the raw series is for.  A reader that wants a numeric spread
        computes it from :attr:`bid_price` and :attr:`ask_price`.
        """
        return f"{self.bid_price}/{self.ask_price}"


def _parse_snapshot(entry: object, index: int) -> L1BookRow:
    if not isinstance(entry, Mapping):
        raise L1BookParseError(
            f"snapshots[{index}] is {type(entry).__name__}; expected an object"
        )
    where = f"snapshots[{index}]"
    symbol = entry.get("symbol", entry.get("s"))
    if not isinstance(symbol, str) or not symbol:
        raise L1BookParseError(
            f"{where} has no non-empty 'symbol' string (got {symbol!r})"
        )

    # The best bid: Binance spells it ``b``, others spell it out.  Refused when
    # absent — a book-ticker snapshot without a bid is not a snapshot of a book.
    raw_bid = None
    for key in ("bid_price", "bid", "bidPrice", "bestBid", "b"):
        if key in entry:
            raw_bid = entry[key]
            break
    if raw_bid is None:
        raise L1BookParseError(
            f"{where} ({symbol}) carries no bid; a best bid/ask snapshot must "
            f"carry a bid"
        )

    raw_ask = None
    for key in ("ask_price", "ask", "askPrice", "bestAsk", "a"):
        if key in entry:
            raw_ask = entry[key]
            break
    if raw_ask is None:
        raise L1BookParseError(
            f"{where} ({symbol}) carries no ask; a best bid/ask snapshot must "
            f"carry an ask"
        )

    raw_bid_qty = None
    for key in ("bid_quantity", "bidQty", "bidQuantity", "bestBidQty", "B"):
        if key in entry:
            raw_bid_qty = entry[key]
            break
    if raw_bid_qty is None:
        raise L1BookParseError(
            f"{where} ({symbol}) carries no bid quantity; a best bid/ask "
            f"snapshot must carry a bid size"
        )

    raw_ask_qty = None
    for key in ("ask_quantity", "askQty", "askQuantity", "bestAskQty", "A"):
        if key in entry:
            raw_ask_qty = entry[key]
            break
    if raw_ask_qty is None:
        raise L1BookParseError(
            f"{where} ({symbol}) carries no ask quantity; a best bid/ask "
            f"snapshot must carry an ask size"
        )

    # The instant: the venue's event time ``E`` first, then the generic time.
    # One is required, because a snapshot with no instant cannot be placed on the
    # 1 second grid, and substituting ours would invent which second it was.
    raw_time = None
    for key in ("event_time", "eventTime", "E", "time", "ts", "T", "trade_time", "tradeTime"):
        if key in entry:
            raw_time = entry[key]
            break
    if raw_time is None:
        raise L1BookParseError(
            f"{where} ({symbol}) carries no event time; a snapshot with no "
            f"instant cannot be placed on the 1 second grid, and substituting "
            f"ours would invent which second it was"
        )

    return L1BookRow(
        symbol=symbol,
        window_start=_floor_to_second(_event_time_field(raw_time, f"{where}.event_time")),
        bid_price=_scalar_field(raw_bid, f"{where}.bid"),
        ask_price=_scalar_field(raw_ask, f"{where}.ask"),
        bid_quantity=_scalar_field(raw_bid_qty, f"{where}.bid_quantity"),
        ask_quantity=_scalar_field(raw_ask_qty, f"{where}.ask_quantity"),
    )


def _as_snapshot_list(body: object) -> Sequence[object]:
    # The snapshots may arrive as a bare list, nested under one of the common
    # wrapper keys, or as a single-symbol response (a caller that flushed one
    # snapshot is as legitimate as one that flushed a batch).  Looked for in this
    # order so a bare list is never mistaken for a wrapper, and a single-object
    # response is never mistaken for a wrapper: the wrapper keys are checked
    # only when the object is not already a snapshot.
    if isinstance(body, list):
        return body
    if isinstance(body, Mapping):
        for key in _WRAPPER_KEYS:
            nested = body.get(key)
            if isinstance(nested, list):
                return nested
        if "symbol" in body or "s" in body or "b" in body:
            return [body]
    raise L1BookParseError(
        "L1 book payload has no snapshots list; the document is not a "
        "book-ticker response"
    )


@dataclass(frozen=True)
class L1BookBatch:
    """One flush's L1 snapshots — the unit this stream persists.

    A batch is what a worker cycle writes: whatever snapshots the feed delivered
    since the last cycle, across as many symbols as that flush happened to carry.
    It makes **no completeness claim about any second**: a reader walks the
    series by ``window_start`` and by ``symbol`` across batches, exactly as it
    would walk a single batch, because a websocket flush is a deployment-paced
    slice, not a market boundary.  ``rows`` keeps the venue's order, because that
    is the order a human reading the record will read — the same asymmetry
    funding and book diffs draw between their persisted document and their
    canonical hash.  A batch with no rows is refused: an empty flush is a
    rate-limit body, a truncated frame or a reconnect with nothing behind it,
    never a snapshot.
    """

    rows: Sequence[L1BookRow]

    def __post_init__(self) -> None:
        rows = list(self.rows)
        if not rows:
            # Refused deliberately.  An empty snapshot response is a failed or
            # truncated flush — never data — and persisting it would make a
            # failed cycle indistinguishable from a quiet one in the very series
            # a reader walks as the market's top-of-book history.
            raise L1BookParseError(
                "an L1 book batch must carry at least one row; an empty batch "
                "is a failed flush, not a quiet book"
            )
        for row in rows:
            if not isinstance(row, L1BookRow):
                raise L1BookParseError(
                    "an L1 book batch's rows must be L1BookRow instances, "
                    f"got {type(row).__name__}"
                )
        object.__setattr__(self, "rows", tuple(rows))

    def __len__(self) -> int:
        """How many snapshots this batch carries — its row count."""
        return len(self.rows)

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this batch carries, in the venue's order, deduplicated."""
        seen: dict[str, None] = {}
        for row in self.rows:
            seen.setdefault(row.symbol, None)
        return tuple(seen)

    @property
    def first_time(self) -> datetime:
        """The earliest window start this batch carries — its span's start."""
        return min(row.window_start for row in self.rows)

    @property
    def last_time(self) -> datetime:
        """The latest window start this batch carries — its span's end."""
        return max(row.window_start for row in self.rows)

    def for_symbol(self, symbol: str) -> tuple[L1BookRow, ...]:
        """This batch's snapshots for ``symbol``, in the venue's order."""
        return tuple(row for row in self.rows if row.symbol == symbol)

    def canonical_bytes(self) -> bytes:
        """The batch's canonical JSON bytes — the thing content-hashed.

        Canonical means rows in a deterministic order (window start, then
        symbol), keys sorted, and the tightest separators — so two flushes
        carrying the same snapshots hash identically whatever order the venue
        delivered its symbols in and whatever whitespace the transport added.
        This is what makes :attr:`L1BookRecord.source_sha256` a *content* hash:
        a flush that changed one quote does not agree on it, and one that merely
        reordered its snapshots does.  Note the deliberate asymmetry with the
        persisted document, which keeps the venue's own order.
        """
        ordered = sorted(self.rows, key=lambda r: (r.window_start, r.symbol))
        return json.dumps(
            {"rows": [_row_to_canonical(row) for row in ordered]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def source_sha256(self) -> str:
        """The sha256 of :meth:`canonical_bytes` — the batch's identity."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def parse_l1_book(document: object) -> L1BookBatch:
    """Parse an L1 book-ticker payload into a :class:`L1BookBatch`.

    Accepts the venue's response as decoded JSON — a single snapshot mapping, a
    list of snapshots, a wrapper some endpoints use (``{"bookTickers": [...]}``),
    a JSON bytes or string body, or an already-parsed :class:`L1BookBatch` — and
    refuses anything that is not a well-formed set of snapshots with
    :class:`L1BookParseError`.

    Strict about the shape this system owns: each snapshot must name its symbol,
    carry a bid and an ask with a price and a quantity each (kept verbatim), and
    an event time (without which it cannot be placed on the 1 second grid).
    Tolerant where the venue is free: a snapshot may carry an update id, an
    order id or a symbol code alongside the fields this module reads, and they
    are ignored — this module persists exactly the fields an L1 snapshot is.
    """
    if isinstance(document, L1BookBatch):
        return document
    if isinstance(document, (bytes, bytearray, str)):
        try:
            decoded = json.loads(document)
        except ValueError as exc:
            raise L1BookParseError(f"L1 book payload is not valid JSON: {exc}") from exc
    else:
        decoded = document

    entries = _as_snapshot_list(decoded)
    rows = [_parse_snapshot(entry, index) for index, entry in enumerate(entries)]
    return L1BookBatch(rows=rows)


#: A fetch: return the venue's L1 book-ticker response, as JSON bytes, a JSON
#: string, a decoded mapping/list, or an already-parsed batch.
#:
#: The seam the deployment's websocket client fills.  This member ships no
#: websocket client — like the aggTrade worker, which is handed its fetch rather
#: than owning one — so the venue's auth, rate limits and reconnect policy stay
#: the stream worker's business, and the store stays testable without a network.
#: Whatever the fetch returns is parsed before anything is written, so a failed
#: flush never consumes a sequence.
L1BookFetch = Callable[[], Union[bytes, str, Sequence, Mapping, L1BookBatch]]


def _row_to_envelope(row: L1BookRow) -> dict[str, object]:
    # Persisted in the venue's own order, with the values in their native kinds
    # — strings for the prices and quantities (verbatim), a datetime for the
    # window start — so a reader (and a human diffing two records) sees the
    # snapshot as the feed sent it.  The canonical form used for hashing is a
    # different thing and is not written to disk.
    return {
        "symbol": row.symbol,
        "window_start": _isoformat_utc(row.window_start),
        "bid_price": row.bid_price,
        "ask_price": row.ask_price,
        "bid_quantity": row.bid_quantity,
        "ask_quantity": row.ask_quantity,
    }


def _row_to_canonical(row: L1BookRow) -> dict[str, object]:
    # The canonical form the content hash is taken over: the same fields as the
    # envelope, rendered so two flushes carrying the same snapshot agree on their
    # hash whatever order the venue delivered its snapshots in.  The envelope and
    # the canonical form carry the same values — the window start as an ISO
    # instant, the prices and quantities verbatim — so the one builder serves
    # both.
    return _row_to_envelope(row)


@dataclass(frozen=True)
class L1BookRecord:
    """One persisted flush: the sequence it landed under and the snapshots it carried.

    ``sequence`` is the record's position in the stream's append-only log —
    ``1`` for the first flush, then ``2, 3, ...`` — and, because the log is
    feature 28's staging area, it is also the sequence of the batch the envelope
    bytes were committed as.  ``written_at`` is when *we* persisted the flush
    (UTC, timezone-aware) and is deliberately kept apart from the rows'
    ``window_start``, which is when *the venue* saw each snapshot: the series is
    ordered by the latter, and conflating the two would let our own ingest lag
    decide a snapshot's place in the market's history.

    Two hashes, deliberately distinct, exactly as aggTrades', funding's and book
    diffs' records carry them: ``source_sha256`` is over the canonical document
    and answers "did the quotes change?"; ``payload_sha256`` is over the bytes
    actually written — the file's identity, the same value the seal's MANIFEST
    will record for it.  ``path`` names the ``<sequence>.bin`` the bytes were
    committed to, so a seal or an operator can point at the exact artifact; it is
    never written through, because the only way to add a record is another
    :meth:`L1BookStore.record`.
    """

    sequence: int
    written_at: datetime
    batch: L1BookBatch
    source_sha256: str
    payload_sha256: str
    path: Path

    @property
    def row_count(self) -> int:
        """How many snapshots this record carries."""
        return len(self.batch)

    @property
    def first_time(self) -> datetime:
        """The earliest window start this record covers."""
        return self.batch.first_time

    @property
    def last_time(self) -> datetime:
        """The latest window start this record covers."""
        return self.batch.last_time

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this record carries, in the venue's order."""
        return self.batch.symbols


class L1BookStore:
    """The append-only log of L1 book snapshots, retained permanently.

    Records live at ``<lake>/staging/bookTicker/<sequence>.bin``, one file per
    flush, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a record is written once,
    atomically (temp file, ``fsync``, ``rename``), and never rewritten: the
    underlying batch store refuses a second batch at a sequence it already holds.
    *Persisting each flush's rows, retained permanently* is therefore the store's
    structure rather than its discipline: it appends at ``current + 1`` into an
    area nothing in the system ever expires, so a flush's bytes are frozen the
    moment the next flush lands and no flush is ever dropped by a retention
    window — there is deliberately no ``prune`` here, because the §4.1 row this
    store serves is *forever*.

    Construction reads whatever a prior run left on disk, so a restarted process
    knows where the log reached without a network call — the same
    seed-from-what-is-durable moment the resume watermark gives a restarted
    worker.  A store is one-writer-per-stream, like the aggTrade, funding and
    book-diff stores: a second concurrent appender would race for the same
    sequence and be refused by the batch store rather than silently overwriting.
    """

    def __init__(self, staging: StagingArea) -> None:
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"the L1 book store writes into a StagingArea, "
                f"got {type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "L1BookStore":
        """The store over the lake's staging area, resolved from the environment.

        The same resolution the ingest workers and the sealing service use
        (``LAKE_ROOT``, defaulting to ``lake/`` beside the workspace root), so
        records are written into the very area the seal copies out of — there is
        no second root that could drift from the first.
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
        return self._staging.path_for(L1_BOOK_STREAM)

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
        document: Union[bytes, str, Sequence, Mapping, L1BookBatch],
        *,
        written_at: datetime,
    ) -> L1BookRecord:
        """Persist one flush as the next record; never overwrite a prior one.

        The document is parsed and validated *first*, so a failed flush consumes
        no sequence number and leaves the log untouched; then it is written as
        the next record — ``current + 1`` — into the stream's append-only
        staging log.  The previous records are not read, moved or rewritten:
        adding a record is an append, and the store's duplicate-sequence refusal
        means this method has no code path that could overwrite one.

        ``written_at`` is required and must be timezone-aware: it is the instant
        the flush was persisted, kept apart from the snapshots' own window
        starts, and a naive timestamp would make the record's place in the
        series' write history unanswerable.  The store does not read a clock of
        its own — the caller that flushed owns the time the flush happened.
        """
        parsed = parse_l1_book(document)
        _require_aware(written_at, "written_at")

        sequence = self._staging.current(L1_BOOK_STREAM) + 1
        envelope = {
            "stream": str(L1_BOOK_STREAM),
            "sequence": sequence,
            "written_at": _isoformat_utc(written_at),
            "source_sha256": parsed.source_sha256,
            "first_time": _isoformat_utc(parsed.first_time),
            "last_time": _isoformat_utc(parsed.last_time),
            _DOCUMENT_KEY: [_row_to_envelope(row) for row in parsed.rows],
        }
        payload = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        batch = self._staging.append(
            L1_BOOK_STREAM, payload=payload, rows=len(parsed)
        )
        return L1BookRecord(
            sequence=batch.sequence,
            written_at=written_at.astimezone(_UTC),
            batch=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            path=batch.path,
        )

    # -- Reading --------------------------------------------------------------

    def records(self) -> tuple[L1BookRecord, ...]:
        """Every persisted record, oldest first.

        Read back from the staging log in ascending sequence order, each
        envelope verified against the sequence its filename claims and the
        document hash it recorded — so a reader gets either the record that was
        committed or a clear :class:`L1BookCorruptError`, never a
        plausible-looking record assembled from damaged bytes.
        """
        return tuple(
            self._read(batch)
            for batch in self._staging.staged(L1_BOOK_STREAM)
        )

    def current(self) -> L1BookRecord | None:
        """The most recent record, or ``None`` when no flush has been persisted.

        ``None`` is the honest answer for an empty log — a store that has never
        recorded a flush has no best bid/ask to offer, and a caller that needs
        one must flush rather than be handed a default that would be exactly the
        hardcoded venue constant §4.1's "never hardcoded" rule forbids.
        """
        batches = self._staging.staged(L1_BOOK_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def previous(self) -> L1BookRecord | None:
        """The record before :meth:`current`, or ``None`` when there is none.

        The comparison point a flush reports against: a worker can say whether
        the flush it just persisted changed the quotes, which is the difference
        between a quiet cycle and a cycle a reader must absorb.
        """
        batches = self._staging.staged(L1_BOOK_STREAM)
        if len(batches) < 2:
            return None
        return self._read(batches[-2])

    def record_at(self, sequence: int) -> L1BookRecord | None:
        """The record persisted under ``sequence``, or ``None`` if never recorded.

        ``None`` distinguishes *that sequence was never recorded* from *the log
        holds a record under that number but its bytes are damaged*, which
        :meth:`records` raises on.
        """
        self.path_for(sequence)  # validates the argument; raises on a bad one
        for batch in self._staging.staged(L1_BOOK_STREAM):
            if batch.sequence == sequence:
                return self._read(batch)
        return None

    def row_count(self) -> int:
        """How many snapshots the log holds in total — the permanent series' length."""
        return sum(batch.rows for batch in self._staging.staged(L1_BOOK_STREAM))

    def _read(self, batch) -> L1BookRecord:
        # Read one committed batch back into a record, verifying as it goes.
        # The three checks below are the read half of the append-only guarantee:
        # the bytes are the bytes that were committed, under the sequence the
        # filename claims, carrying the document the envelope's hash vouches for.
        # A mismatch is corruption (or tampering) on a series a reader walks as
        # the market's top-of-book history, so it is raised rather than papered
        # over.
        try:
            raw = batch.payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise L1BookCorruptError(
                f"L1 book record {batch.sequence} is not readable as a JSON "
                f"envelope: {exc}"
            ) from exc
        try:
            envelope = json.loads(raw)
        except ValueError as exc:
            raise L1BookCorruptError(
                f"L1 book record {batch.sequence} is not readable as a JSON "
                f"envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise L1BookCorruptError(
                f"L1 book record {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise L1BookCorruptError(
                f"L1 book record {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"record envelope this store wrote"
            )
        recorded = envelope["sequence"]
        if recorded != batch.sequence:
            raise L1BookCorruptError(
                f"L1 book record file {batch.sequence}.bin records sequence "
                f"{recorded!r}; the file does not describe itself"
            )
        document = parse_l1_book(envelope[_DOCUMENT_KEY])
        recorded_hash = envelope["source_sha256"]
        if recorded_hash != document.source_sha256:
            raise L1BookCorruptError(
                f"L1 book record {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{document.source_sha256!r}; the file's bytes are not the "
                f"bytes that were committed"
            )
        return L1BookRecord(
            sequence=batch.sequence,
            written_at=_parse_timestamp(envelope["written_at"], batch.sequence),
            batch=document,
            source_sha256=document.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


class L1BookWorker:
    """The L1 book worker: flush each cycle's snapshots into the permanent log.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the ``bookTicker``
    stream class, so the supervisor of feature 16 runs it on its own thread
    alongside every other stream and converts whatever it raises into that
    stream's own failure.  One cycle is:

    * **Flush.**  Call the injected :data:`L1BookFetch`.  The websocket client,
      its auth, its rate limits and its reconnect policy are the deployment's
      business; this worker owns only the persistence and the 1 second grid.  A
      fetch returning ``None`` is a *quiet* cycle — the feed delivered no
      snapshot this slice — reported as zero rows, not a failure: a liquid book
      ticks continuously but a quiet one can legitimately go a cycle without a
      quote, and treating that as an error would fail an honest stream.
    * **Record.**  Parse first, then record the batch.  A failed flush — a
      truncated frame, an error page, an empty response, a snapshot missing a
      side — raises :class:`L1BookParseError` *before* anything is written, so
      the log never records a flush that did not happen.

    Unlike the book-diff worker there is no retention pass: this stream's §4.1
    row is *forever*, so nothing is ever retired, and the permanent series is the
    append-only area's own property rather than anything this worker enforces.
    The clock is injected because ``written_at`` is a fact about elapsed
    wall-clock time: a test must be able to place the worker's writes without
    touching the wall clock, and §12 keeps wall-clock reads out of checked code
    in any case.  The default clock reads the system UTC time, which is what a
    deployment wants.
    """

    def __init__(
        self,
        store: L1BookStore,
        fetch: L1BookFetch,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, L1BookStore):
            raise TypeError(
                f"the L1 book worker persists into an L1BookStore, "
                f"got {type(store).__name__}"
            )
        if not callable(fetch):
            raise TypeError(
                f"fetch must be a zero-argument callable returning the venue's "
                f"L1 book response, got {type(fetch).__name__}"
            )
        if clock is not None and not callable(clock):
            raise TypeError(
                f"clock must be a callable returning a datetime, "
                f"got {type(clock).__name__}"
            )
        self._store = store
        self._fetch = fetch
        self._clock = clock if clock is not None else _utc_now

    # -- IngestWorker ---------------------------------------------------------

    @property
    def stream_class(self) -> StreamClass:
        """The one stream class this worker owns — ``bookTicker``."""
        return L1_BOOK_STREAM

    @property
    def store(self) -> L1BookStore:
        """The record log this worker appends to."""
        return self._store

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Run one cycle: flush the snapshots and persist them.

        Returns the persisted record's sequence as the cycle's watermark, so a
        monitor sees the log advance, and ``rows_written`` as the number of
        snapshots the record carries.  A quiet cycle — a fetch that returned
        ``None`` — reports both as zero: no flush, no record, no progress to
        claim.
        """
        now = self._clock()
        _require_aware(now, "the clock")
        document = self._fetch()
        if document is None:
            return CycleResult(rows_written=0, sequence=0)
        record = self._store.record(document, written_at=now)
        return CycleResult(
            rows_written=record.row_count, sequence=record.sequence
        )


def _utc_now() -> datetime:
    """The default clock: the current UTC time, timezone-aware."""
    return datetime.now(_UTC)


def register_l1_book_worker(
    fetch: L1BookFetch,
    store: Optional[L1BookStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], L1BookWorker]:
    """Register a worker factory bound to an explicitly wired fetch.

    The operator path: hand in the websocket client's fetch (and, when it is not
    the lake's staging area, the store), and this registers a worker factory
    bound to those collaborators.  Registration replaces the auto-discovered
    factory of the same class in the registry it targets — the registry's own
    rule, *a re-registered class is a revision of the same worker, never a
    second worker* — so a deployment that wires a client does not end up with
    two L1 book workers competing for the same sequence numbers.

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
            f"L1 book response, got {type(fetch).__name__}"
        )

    def build() -> L1BookWorker:
        resolved_store = store if store is not None else L1BookStore.from_env()
        return L1BookWorker(resolved_store, fetch, clock=clock)

    # Register through a private registry by default, never the process-wide
    # one.  Registration is a *deployment* act: writing a caller's wiring into
    # the default registry would replace the auto-discovered worker for every
    # later composition in the process — including tests, which would then be
    # handed a worker bound to a store that has since been deleted.  A caller
    # that genuinely means to reconfigure the running process passes the default
    # registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        L1_BOOK_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(L1_BOOK_STREAM)
def build_l1_book_worker() -> L1BookWorker:
    """Compose the L1 book worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    Collaborators come from the environment the way every other ingest seam
    does: the store is the lake's staging area (:meth:`L1BookStore.from_env`),
    so records land in the very area the seal copies out of.  The fetch has no
    environment-resolved default — this member ships no websocket client, so the
    venue's auth, rate limits and reconnect policy stay the deployment's
    business — and a deployment wires it with :func:`register_l1_book_worker`.
    Until then the worker still composes and its cycle reports that stream's own
    failure, which is feature 16's contract: an unconfigured stream is a row in
    the report, not a component that fails to load.
    """
    return L1BookWorker(L1BookStore.from_env(), _unconfigured_fetch)


def _unconfigured_fetch() -> object:
    """The fetch used when a deployment has not wired a websocket client yet.

    Raising here, rather than at composition time, keeps the plugin shaped the
    way feature 16 wants it: an unconfigured stream is that stream's failure in
    the report, not a component that fails to compose.
    """
    raise L1BookError(
        "no L1 book fetch is configured; register the worker with a fetch "
        "returning the venue's book-ticker response "
        "(nullius_ingest.register_l1_book_worker(fetch, store=..., "
        "registry=default_worker_registry()))"
    )
