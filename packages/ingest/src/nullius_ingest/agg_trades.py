"""Aggregated trades off the websocket feed, compressed and retained permanently.

app_spec.xml feature 18 states the behaviour: *"System ingests aggTrades from
the websocket feed, persisting compressed rows retained permanently."*
docs/nullius-tech-architecture.md §4.1 fixes the stream's row in the data-layer
table — ``aggTrades | WS | continuous | forever, compressed`` — and two columns
of that row are load-bearing and, taken together, set this stream apart from
every other in the table:

* **The retention is *forever*.**  Like funding and exchangeInfo, and unlike
  the L2 book diffs §4.1 keeps for a rolling 90 days, the aggTrade tape is kept
  permanently: a trade is an irreversible fact of the market, and a row dropped
  at ingest time is a row no replay can ever recover — the venue's trade history
  endpoints age out, so the tape captured live is the only honest copy.  This
  module is that "forever" made structural: it appends each flush into the
  append-only staging area, which is written once and copied by the seal, never
  rewritten and never expired.  There is deliberately no ``prune`` here, unlike
  :mod:`nullius_ingest.book_diffs`: a retention window that removes data would
  contradict the §4.1 row this stream exists to serve.

* **The rows are *compressed*.**  This is the one property no other stream
  claims.  A 100-symbol aggTrade tape is the largest of the raw streams — every
  trade, of which a liquid book can print tens of thousands a second — and
  §4.1's note that the raw diff streams run *"roughly 50–200 GB/month
  uncompressed"* applies with even more force here, where there is no 90 day
  window to lean on and the history is kept forever.  Storing the tape
  uncompressed *forever* is the self-inflicted infrastructure problem §4.1
  describes; compressing it is the answer.  So this module is the first to
  compress before it writes: each flush's envelope is gzip-compressed (:func:`_compress`)
  before it reaches the staging area, and decompressed (:func:`_decompress`) on
  the read path, so the permanent tape occupies a fraction of its raw size
  while the bytes a seal copies are the compressed ones.  The codec is named by
  :data:`COMPRESSION` and carried in no envelope — it is a property of the
  store, fixed once, so a reader does not have to trust a per-record spelling of
  the thing that would corrupt the whole log if it ever drifted.

The rest of the module follows the landed websocket stream — :mod:`nullius_ingest.book_diffs`
— because an aggTrade and an L2 diff are the same kind of object to the ingest
layer: a websocket flush, parsed, placed in an append-only log, retained.  Three
pieces, mirroring it:

* **The row** — :class:`AggTradeRow`: one aggregated trade, with the venue's
  fields kept in their native kinds.  Prices and quantities are kept **verbatim**
  in the venue's own string spelling (``"61234.50"``, not ``Decimal``), exactly
  as the book diffs and funding keep their scalars: whether the venue said
  ``"0.00010"`` or ``"0.0001"`` is a fact about the venue, and re-rendering it
  would make an audit unable to tell a venue change from our own lossy parse.
  The trade's ids — the aggregated trade id and the first/last outright-trade id
  range — are kept as integers, not strings, because unlike a price they are
  compared and ordered (a gap on reconnect is a hole in the id sequence, and the
  continuity check needs integers to name it).  The trade's instant is kept as
  an aware :class:`~datetime.datetime`.  A ``quantity`` here is never a removal:
  an aggTrade is a completed trade, so every quantity is a genuine traded size.

* **The record** — :class:`AggTradeRecord`: one *flush*, frozen, with the
  sequence it was persisted under, when it was written, the span of trade times
  it covers, the document's content hash and the hash of the **compressed** bytes
  written.  The two hashes are deliberately distinct, as funding's and book
  diffs' records carry them: ``source_sha256`` is over the *uncompressed*
  canonical document and answers "did the trades change?"; ``payload_sha256`` is
  over the *compressed* bytes actually committed — the file's identity, the same
  value the seal's MANIFEST will record for it.

* **The store** — :class:`AggTradeStore`: an append-only log of records under
  the §4.1 staging area, at ``<lake>/staging/aggTrades/<seq>.bin``, whose every
  write is compressed first.  *Persisting each flush's compressed rows, retained
  permanently* is therefore structural, not a convention: the store appends at
  ``current + 1`` into feature 28's append-only area
  (:class:`~nullius_ingest.staging.StagingArea`), whose batch store refuses a
  second batch at a sequence it already holds and which nothing in the system
  ever expires, so a flush's compressed bytes are frozen the moment the next
  flush lands and no flush is ever dropped.

Layering on the stream workers of feature 16 is deliberate, as it is for every
other stream: this is one worker owning one stream class, so a failed flush is
that stream's :class:`~nullius_ingest.worker.StreamFailure` and every other
stream keeps ingesting.  The fetch is injected (:data:`AggTradeFetch`) — the
member ships no websocket client, exactly as it ships no REST client, so the
venue's auth, rate limits and reconnect policy stay the deployment's business
(§15's *"WS gap / reconnect"* row is features 25 and 26, which
:class:`~nullius_ingest.gaps.GapDetector` and
:class:`~nullius_ingest.backfill.GapBackfiller` already serve) — and the clock
is injected because ``written_at`` is a fact about elapsed wall-clock time and
§12 keeps wall-clock reads out of checked code.  The member stays stdlib-only:
the compression is :mod:`gzip`, and the moment arithmetic that places a trade's
instant is exact integer microseconds from the epoch, so no float ever touches
an instant.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, Optional, Union

from .registry import WorkerRegistry, register_worker
from .staging import StagingArea
from .streams import StreamClass
from .worker import CycleResult

__all__ = [
    "AGG_TRADES_STREAM",
    "COMPRESSION",
    "AggTradeBatch",
    "AggTradeCorruptError",
    "AggTradeError",
    "AggTradeFetch",
    "AggTradeParseError",
    "AggTradeRecord",
    "AggTradeRow",
    "AggTradeStore",
    "AggTradeWorker",
    "build_agg_trade_worker",
    "parse_agg_trades",
    "register_agg_trade_worker",
]

#: The stream class this module serves.  §4.1's table row for aggTrades is the
#: stream whose retention is *forever* and whose rows are *compressed*, and the
#: spelling here is the persisted one (:class:`~nullius_ingest.streams.StreamClass`),
#: so the staging layout and the record log share it.
AGG_TRADES_STREAM = StreamClass.AGG_TRADES

#: The compression codec applied to every record before it is written.  gzip is
#: the stdlib answer and the whole of feature 18's *"compressed"*: it is named
#: here, as a constant, so the fact that this stream compresses — and how — is
#: stated where it is decided rather than buried in a write path, and so a
#: reader that one day meets a compressed log has one spelling to check it
#: against.  It is a property of the store, fixed once, and is deliberately not
#: written into each envelope: a per-record codec field is a thing that could
#: drift and corrupt the whole log, whereas a store that always compresses the
#: same way needs no such field.
COMPRESSION: Final[str] = "gzip"

#: The envelope keys a record file carries around its rows — named so a reader
#: of a record file (an operator, a seal, a later audit) does not have to import
#: this module to know what it is looking at.  ``rows`` is the document.  The
#: two time bounds name the span of *trade* times the flush covers — distinct
#: from ``written_at``, which is when *we* persisted it — because a reader
#: walking the tape wants to know which trades a record holds without opening it.
_ENVELOPE_KEYS = (
    "stream",
    "sequence",
    "written_at",
    "source_sha256",
    "first_time",
    "last_time",
)

#: Wrapper keys under which a venue endpoint may nest its trade list — the flat
#: list and the single-trade object are also accepted (see
#: :func:`parse_agg_trades`), so this is a convenience, not a closed set.
_WRAPPER_KEYS = ("aggTrades", "trades", "data", "results")

#: The envelope key holding the rows, named beside the keys around it so a
#: reader of a record file does not have to hunt for it.
_DOCUMENT_KEY = "rows"

_UTC = timezone.utc

#: The epoch, in UTC: the instant every venue event time is measured from.  A
#: trade's instant is an exact integer count of microseconds from here, so no
#: float ever touches an instant and a boundary is a boundary rather than a
#: rounding, on every platform.
_EPOCH = datetime(1970, 1, 1, tzinfo=_UTC)


class AggTradeError(Exception):
    """Base for every failure this module raises.

    Raised for a payload this module will not persist and for a persisted record
    it will not read: both are cases where the permanent tape would otherwise
    start lying about what the venue's trades did, so both fail loudly rather
    than being approximated into a row.
    """


class AggTradeParseError(AggTradeError):
    """A trade payload is not one this module will persist.

    Raised *before* anything is written, so a rate-limit body, a truncated
    frame or an error page never consumes a sequence number and never appears in
    the log as a flush that happened.  The message names what was wrong with
    which trade, because the caller is a worker whose next move depends on
    whether the venue's shape changed or the feed simply hiccuped.
    """


class AggTradeCorruptError(AggTradeError):
    """A persisted, compressed record file does not match what was written under it.

    Raised when a record file's compressed bytes cannot be decompressed, when it
    is not readable as the JSON envelope it was written as, when its recorded
    sequence is not the sequence its filename claims, or when recomputing its
    document hash disagrees with the hash the envelope recorded.  The log is
    append-only and copied byte-for-byte by the seal, so a mismatch means the
    bytes on disk are not the bytes this module committed — corruption or
    tampering — and a reader reconstructing the trade tape from them would be
    reconstructing trades that never happened.
    """


def _compress(payload: bytes) -> bytes:
    """Compress ``payload`` with the store's codec (:data:`COMPRESSION`).

    The whole of feature 18's *"compressed"* on the write path: the envelope's
    JSON bytes go in, a gzip stream comes out.  ``mtime`` is pinned to ``0`` so
    the output is deterministic — not because the compressed bytes are ever
    re-derived on read (they are read back verbatim and hashed as-is), but
    because a store whose compression were nondeterministic could never be
    reasoned about in a test or an audit.
    """
    return gzip.compress(payload, mtime=0)


def _decompress(blob: bytes) -> bytes:
    """Undo :func:`_compress`: recover the envelope's JSON bytes from ``blob``.

    The read-path half of the codec.  A gzip magic header (``\\x1f\\x8b``) is the
    only thing that identifies a compressed record; a file that is not gzip is
    not a record this store wrote, so the caller turns a failure here into a
    :class:`AggTradeCorruptError` rather than parsing undecompressed bytes as an
    envelope.
    """
    return gzip.decompress(blob)


def _scalar_field(value: object, where: str) -> str:
    # Price and quantity values are persisted as the venue's own spelling, for
    # the same reason book diffs persists its levels verbatim: whether the venue
    # said "61234.50" or "61234.5" is a fact about the venue, and this is the
    # raw tape, so re-rendering it would destroy the one thing raw data is for.
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
    raise AggTradeParseError(
        f"{where} is {type(value).__name__}; price and quantity values must be "
        f"scalars (the venue's own spelling is kept verbatim)"
    )


def _int_field(value: object, where: str) -> int:
    # Trade ids are persisted as integers, not as the venue's spelling: unlike a
    # price they are compared and ordered (the gap detector's whole job is id
    # continuity), and ordering two spellings of the same number is not a thing
    # this system should ever have to reason about.  A fractional id is refused
    # rather than truncated: an id is a count, and a non-integer is not one.
    if isinstance(value, bool):
        raise AggTradeParseError(f"{where} is a boolean; expected an integer id")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise AggTradeParseError(
                f"{where} is {value!r}; expected an integer id: {exc}"
            ) from exc
    raise AggTradeParseError(
        f"{where} is {type(value).__name__}; expected an integer id"
    )


def _bool_field(value: object, where: str) -> bool:
    # The buyer-is-maker flag is a genuine boolean fact about the trade, so it
    # is kept as a bool rather than spelled to a string — unlike a price, a bool
    # has no venue-specific rendering to preserve, and JSON round-trips it
    # losslessly.  Refused rather than coerced when it is not a bool: a
    # truthy-string would let a malformed flag masquerade as a real one on the
    # tape the trade-side paths read.
    if isinstance(value, bool):
        return value
    raise AggTradeParseError(
        f"{where} is {type(value).__name__}; the maker flag must be a boolean"
    )


def _as_epoch_millis(value: object, where: str) -> int:
    # Turn a *venue-supplied* instant into an exact integer count of epoch
    # milliseconds.  Venues are inconsistent about JSON types for the same field
    # — an event time arrives as a bare number on one feed and a string on
    # another — so a float or a numeric string is coerced here, at the boundary
    # where that sloppiness is a fact about the venue.  Refusals are the
    # module's own error, not whatever ``int()`` happened to raise, because the
    # caller is a worker deciding whether the venue's shape changed.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AggTradeParseError(
            f"{where} is {type(value).__name__}; expected an epoch-millisecond "
            f"instant"
        )
    try:
        millis = int(value)
    except (TypeError, ValueError) as exc:
        raise AggTradeParseError(
            f"{where} is {value!r}; expected an epoch-millisecond instant: {exc}"
        ) from exc
    if millis <= 0:
        raise AggTradeParseError(
            f"{where} is {millis}; an epoch-millisecond instant is positive"
        )
    return millis


def _event_time_field(value: object, where: str) -> datetime:
    # Two spellings mean the same thing here, and both must parse because both
    # are written by something in this system:
    #
    # * the venue's epoch milliseconds, which is what a feed sends;
    # * an ISO-8601 instant, which is what *our own record envelope* writes
    #   (``event_time``, already a datetime).  A store that could not read back
    #   its own spelling would fail its own round trip.
    #
    # Either way the result is an aware instant over the exact epoch; no float
    # and no ``timestamp()`` round trip, either of which would put a rounding
    # between the venue's instant and the tape.
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
                raise AggTradeParseError(
                    f"{where} is the naive instant {value!r}; the tape needs an "
                    f"offset to place a trade's instant"
                )
            return parsed
    return _millis_to_utc(_as_epoch_millis(value, where))


def _millis_to_utc(millis: int) -> datetime:
    # Exact: an integer count of milliseconds becomes an integer count of
    # microseconds from the epoch, and the datetime is built from that.  No
    # float and no ``fromtimestamp()`` round trip, either of which would put a
    # rounding between the venue's instant and the tape.
    return _EPOCH + timedelta(microseconds=millis * 1000)


@dataclass(frozen=True)
class AggTradeRow:
    """One aggregated trade, as the venue reported it.

    Seven facts, each load-bearing:

    * ``symbol`` — which book the trade printed in.
    * ``agg_id`` — the aggregated trade id.  Kept as an integer because it is
      the sequence the tape is ordered and gap-checked by: a hole in the ids is
      a reconnect gap, and a gap is nameable only over integers.
    * ``price`` / ``quantity`` — the venue's own string spellings, kept
      verbatim.  A trade's quantity is always a genuine traded size — an
      aggTrade is a completed fill, never a level removal — so no quantity is
      special-cased.
    * ``first_trade_id`` / ``last_trade_id`` — the range of outright trades this
      aggregated trade collapsed.  Kept as its own pair rather than collapsed to
      one number because the range is what a continuity check reads across the
      outright-trade sequence, and a gap there is a different hole than one in
      the aggregated ids.
    * ``event_time`` — the venue's instant the trade was reported, timezone-aware.
      Kept exact on the epoch lattice; the tape is ordered by it and a reader
      walks it in time order.
    * ``is_buyer_maker`` — whether the buyer was the maker, as a genuine boolean.

    The row is frozen: a record is what the venue sent, and a caller mutating it
    in place would be editing the permanent tape.
    """

    symbol: str
    agg_id: int
    price: str
    quantity: str
    first_trade_id: int
    last_trade_id: int
    event_time: datetime
    is_buyer_maker: bool

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise AggTradeParseError(
                f"an aggTrade must carry a non-empty symbol, got {self.symbol!r}"
            )
        for value, name in (
            (self.agg_id, "agg_id"),
            (self.first_trade_id, "first_trade_id"),
            (self.last_trade_id, "last_trade_id"),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise AggTradeParseError(
                    f"{name} must be an integer, got {type(value).__name__}"
                )
        if self.agg_id <= 0:
            raise AggTradeParseError(
                f"{self.symbol} carries agg_id {self.agg_id}; a trade id is positive"
            )
        if self.last_trade_id < self.first_trade_id:
            # A range that ends before it begins is not a trade this module can
            # record: the pair is continuity evidence, and a reversed one would
            # make a gap appear to run backwards.
            raise AggTradeParseError(
                f"{self.symbol} carries trades {self.first_trade_id}..{self.last_trade_id}; "
                f"a trade range does not end before it begins"
            )
        if not self.price:
            raise AggTradeParseError(f"{self.symbol} carries an empty price")
        if not self.quantity:
            raise AggTradeParseError(f"{self.symbol} carries an empty quantity")
        _require_aware(self.event_time, "event_time")
        object.__setattr__(self, "event_time", self.event_time.astimezone(_UTC))

    @property
    def size(self) -> str:
        """The traded quantity, in the venue's own spelling — the row's size."""
        return self.quantity


def _parse_trade(entry: object, index: int) -> AggTradeRow:
    if not isinstance(entry, Mapping):
        raise AggTradeParseError(
            f"trades[{index}] is {type(entry).__name__}; expected an object"
        )
    where = f"trades[{index}]"
    symbol = entry.get("symbol", entry.get("s"))
    if not isinstance(symbol, str) or not symbol:
        raise AggTradeParseError(
            f"{where} has no non-empty 'symbol' string (got {symbol!r})"
        )

    # The aggregated trade id: Binance spells it ``a``, others spell it out.
    raw_agg = None
    for key in ("agg_id", "aggTradeId", "a"):
        if key in entry:
            raw_agg = entry[key]
            break
    if raw_agg is None:
        raise AggTradeParseError(
            f"{where} ({symbol}) carries no aggregated trade id; the id is the "
            f"sequence the tape is ordered and gap-checked by"
        )

    # The outright-trade range: Binance spells it ``f``/``l``, others spell out.
    raw_first = None
    for key in ("first_trade_id", "firstTradeId", "f"):
        if key in entry:
            raw_first = entry[key]
            break
    raw_last = None
    for key in ("last_trade_id", "lastTradeId", "finalTradeId", "l"):
        if key in entry:
            raw_last = entry[key]
            break
    if raw_first is None or raw_last is None:
        missing = "first" if raw_first is None else "last"
        raise AggTradeParseError(
            f"{where} ({symbol}) carries no {missing} trade id; the range is "
            f"what a continuity check reads"
        )

    # Price and quantity, kept verbatim in the venue's spelling.
    if "price" not in entry and "p" not in entry:
        raise AggTradeParseError(f"{where} ({symbol}) carries no price")
    if "quantity" not in entry and "q" not in entry:
        raise AggTradeParseError(f"{where} ({symbol}) carries no quantity")

    # The instant: the venue's event time ``E`` first (when the trade was
    # reported), falling back to the trade time ``T``.  Both are epoch
    # milliseconds; one is required, because a trade with no instant cannot be
    # placed on the tape, and substituting ours would invent when it happened.
    raw_time = None
    for key in ("event_time", "eventTime", "E", "trade_time", "tradeTime", "T", "time", "ts"):
        if key in entry:
            raw_time = entry[key]
            break
    if raw_time is None:
        raise AggTradeParseError(
            f"{where} ({symbol}) carries no event time; a trade with no instant "
            f"cannot be placed on the tape, and substituting ours would invent one"
        )

    if "is_buyer_maker" not in entry and "m" not in entry:
        raise AggTradeParseError(
            f"{where} ({symbol}) carries no maker flag; an aggTrade reports "
            f"whether the buyer was the maker"
        )

    return AggTradeRow(
        symbol=symbol,
        agg_id=_int_field(raw_agg, f"{where}.agg_id"),
        price=_scalar_field(entry["price"] if "price" in entry else entry["p"], f"{where}.price"),
        quantity=_scalar_field(
            entry["quantity"] if "quantity" in entry else entry["q"], f"{where}.quantity"
        ),
        first_trade_id=_int_field(raw_first, f"{where}.first_trade_id"),
        last_trade_id=_int_field(raw_last, f"{where}.last_trade_id"),
        event_time=_event_time_field(raw_time, f"{where}.event_time"),
        is_buyer_maker=_bool_field(
            entry["is_buyer_maker"] if "is_buyer_maker" in entry else entry["m"],
            f"{where}.is_buyer_maker",
        ),
    )


def _as_trade_list(body: object) -> Sequence[object]:
    # The trades may arrive as a bare list, nested under one of the common
    # wrapper keys, or as a single-trade object (a caller that flushed one trade
    # is as legitimate as one that flushed a batch).  Looked for in this order
    # so a bare list is never mistaken for a wrapper, and a single-trade object
    # is never mistaken for a wrapper: the wrapper keys are checked only when
    # the object is not already a trade.
    if isinstance(body, list):
        return body
    if isinstance(body, Mapping):
        for key in _WRAPPER_KEYS:
            nested = body.get(key)
            if isinstance(nested, list):
                return nested
        if "symbol" in body or "s" in body or "a" in body:
            return [body]
    raise AggTradeParseError(
        "aggTrade payload has no trades list; the document is not a trade "
        "response"
    )


@dataclass(frozen=True)
class AggTradeBatch:
    """One flush's aggregated trades — the unit this stream persists.

    A batch is what a worker cycle writes: whatever trades the feed delivered
    since the last cycle, across as many symbols as that flush happened to
    carry.  It makes **no completeness claim about any instant**: a reader walks
    the tape by ``agg_id`` and by ``event_time`` across batches, exactly as it
    would walk a single batch, because a websocket flush is a deployment-paced
    slice, not a market boundary.  ``rows`` keeps the venue's order, because
    that is the order a human reading the record will read — the same asymmetry
    funding and book diffs draw between their persisted document and their
    canonical hash.  A batch with no rows is refused: an empty flush is a
    rate-limit body, a truncated frame or a reconnect with nothing behind it,
    never a trade.
    """

    rows: Sequence[AggTradeRow]

    def __post_init__(self) -> None:
        rows = list(self.rows)
        if not rows:
            # Refused deliberately.  An empty trade response is a failed or
            # truncated flush — never data — and persisting it would make a
            # failed cycle indistinguishable from a quiet one in the very tape a
            # reader walks as the market's trade history.
            raise AggTradeParseError(
                "an aggTrade batch must carry at least one row; an empty batch "
                "is a failed flush, not a quiet book"
            )
        for row in rows:
            if not isinstance(row, AggTradeRow):
                raise AggTradeParseError(
                    "an aggTrade batch's rows must be AggTradeRow instances, "
                    f"got {type(row).__name__}"
                )
        object.__setattr__(self, "rows", tuple(rows))

    def __len__(self) -> int:
        """How many trades this batch carries — its row count."""
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
        """The earliest trade instant this batch carries — its span's start."""
        return min(row.event_time for row in self.rows)

    @property
    def last_time(self) -> datetime:
        """The latest trade instant this batch carries — its span's end."""
        return max(row.event_time for row in self.rows)

    def for_symbol(self, symbol: str) -> tuple[AggTradeRow, ...]:
        """This batch's trades for ``symbol``, in the venue's order."""
        return tuple(row for row in self.rows if row.symbol == symbol)

    def canonical_bytes(self) -> bytes:
        """The batch's canonical JSON bytes — the thing content-hashed.

        Canonical means rows in a deterministic order (event time, then symbol,
        then agg id), keys sorted, and the tightest separators — so two flushes
        carrying the same trades hash identically whatever order the venue
        delivered its symbols in and whatever whitespace the transport added.
        This is what makes :attr:`AggTradeRecord.source_sha256` a *content*
        hash: a flush that changed one price does not agree on it, and one that
        merely reordered its trades does.  Note the deliberate asymmetry with
        the persisted document, which keeps the venue's own order.
        """
        ordered = sorted(
            self.rows,
            key=lambda r: (r.event_time, r.symbol, r.agg_id),
        )
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


def parse_agg_trades(document: object) -> AggTradeBatch:
    """Parse an aggTrade payload into a :class:`AggTradeBatch`.

    Accepts the venue's response as decoded JSON — a single trade mapping, a
    list of trades, a wrapper some endpoints use (``{"aggTrades": [...]}``), a
    JSON bytes or string body, or an already-parsed :class:`AggTradeBatch` — and
    refuses anything that is not a well-formed set of trades with
    :class:`AggTradeParseError`.

    Strict about the shape this system owns: each trade must name its symbol and
    carry an aggregated trade id, a first/last trade-id range whose first id does
    not exceed its last, a price and a quantity (kept verbatim), an event time
    (without which it cannot be placed on the tape), and a maker flag.  Tolerant
    where the venue is free: a trade may carry an event type, a trade time or a
    symbol code alongside the fields this module reads, and they are ignored —
    this module persists exactly the fields an aggTrade is.
    """
    if isinstance(document, AggTradeBatch):
        return document
    if isinstance(document, (bytes, bytearray, str)):
        try:
            decoded = json.loads(document)
        except ValueError as exc:
            raise AggTradeParseError(
                f"aggTrade payload is not valid JSON: {exc}"
            ) from exc
    else:
        decoded = document

    entries = _as_trade_list(decoded)
    rows = [_parse_trade(entry, index) for index, entry in enumerate(entries)]
    return AggTradeBatch(rows=rows)


#: A fetch: return the venue's aggTrade response, as JSON bytes, a JSON string,
#: a decoded mapping/list, or an already-parsed batch.
#:
#: The seam the deployment's websocket client fills.  This member ships no
#: websocket client — like the book-diff worker, which is handed its fetch
#: rather than owning one — so the venue's auth, rate limits and reconnect
#: policy stay the stream worker's business, and the store stays testable
#: without a network.  Whatever the fetch returns is parsed before anything is
#: written, so a failed flush never consumes a sequence.
AggTradeFetch = Callable[[], Union[bytes, str, Sequence, Mapping, AggTradeBatch]]


@dataclass(frozen=True)
class AggTradeRecord:
    """One persisted, compressed flush: the sequence it landed under and the trades it carried.

    ``sequence`` is the record's position in the stream's append-only log —
    ``1`` for the first flush, then ``2, 3, ...`` — and, because the log is
    feature 28's staging area, it is also the sequence of the batch the
    compressed envelope bytes were committed as.  ``written_at`` is when *we*
    persisted the flush (UTC, timezone-aware) and is deliberately kept apart
    from the rows' ``event_time``, which is when *the venue* saw the trade: the
    tape is ordered by the latter, and conflating the two would let our own
    ingest lag decide a trade's place in the market's history.

    Two hashes, deliberately distinct, exactly as funding's and book diffs'
    records carry them, with one compression-specific twist: ``source_sha256``
    is over the *uncompressed* canonical document and answers "did the trades
    change?"; ``payload_sha256`` is over the *compressed* bytes actually written
    — the file's identity, the same value the seal's MANIFEST will record for it.
    ``path`` names the ``<sequence>.bin`` the bytes were committed to, so a seal
    or an operator can point at the exact artifact; it is never written through,
    because the only way to add a record is another :meth:`AggTradeStore.record`.
    """

    sequence: int
    written_at: datetime
    batch: AggTradeBatch
    source_sha256: str
    payload_sha256: str
    path: Path

    @property
    def row_count(self) -> int:
        """How many trades this record carries."""
        return len(self.batch)

    @property
    def first_time(self) -> datetime:
        """The earliest trade instant this record covers."""
        return self.batch.first_time

    @property
    def last_time(self) -> datetime:
        """The latest trade instant this record covers."""
        return self.batch.last_time

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this record carries, in the venue's order."""
        return self.batch.symbols


class AggTradeStore:
    """The append-only log of compressed aggTrades, retained permanently.

    Records live at ``<lake>/staging/aggTrades/<sequence>.bin``, one file per
    flush, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a record is written once,
    atomically (temp file, ``fsync``, ``rename``), and never rewritten: the
    underlying batch store refuses a second batch at a sequence it already
    holds.  Every write is **compressed** first (:func:`_compress`), so the
    permanent tape occupies a fraction of its raw size and the bytes a seal
    copies are the compressed ones; every read is decompressed (:func:`_decompress`)
    before the envelope is parsed.  *Persisting each flush's compressed rows,
    retained permanently* is therefore the store's structure rather than its
    discipline: it appends at ``current + 1`` into an area nothing in the system
    ever expires, so a flush's bytes are frozen the moment the next flush lands
    and no flush is ever dropped by a retention window — there is deliberately
    no ``prune`` here, because the §4.1 row this store serves is *forever*.

    Construction reads whatever a prior run left on disk, so a restarted process
    knows where the log reached without a network call — the same
    seed-from-what-is-durable moment the resume watermark gives a restarted
    worker.  A store is one-writer-per-stream, like the funding and book-diff
    stores: a second concurrent appender would race for the same sequence and be
    refused by the batch store rather than silently overwriting.
    """

    def __init__(self, staging: StagingArea) -> None:
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"the aggTrade store writes into a StagingArea, "
                f"got {type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "AggTradeStore":
        """The store over the lake's staging area, resolved from the environment.

        The same resolution the ingest workers and the sealing service use
        (``LAKE_ROOT``, defaulting to ``lake/`` beside the workspace root), so
        records are written into the very area the seal copies out of — there is
        no second root that could drift from the first.
        """
        return cls(StagingArea.from_env(env))

    @property
    def compression(self) -> str:
        """The codec every record is compressed with — :data:`COMPRESSION`."""
        return COMPRESSION

    # -- Paths ----------------------------------------------------------------

    @property
    def staging(self) -> StagingArea:
        """The append-only area the records are committed into."""
        return self._staging

    @property
    def root(self) -> Path:
        """The directory holding this stream's record files."""
        return self._staging.path_for(AGG_TRADES_STREAM)

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
        document: Union[bytes, str, Sequence, Mapping, AggTradeBatch],
        *,
        written_at: datetime,
    ) -> AggTradeRecord:
        """Persist one flush as the next record; never overwrite a prior one.

        The document is parsed and validated *first*, so a failed flush consumes
        no sequence number and leaves the log untouched; then it is written as
        the next record — ``current + 1`` — into the stream's append-only
        staging log, **compressed** before it touches disk.  The previous
        records are not read, moved or rewritten: adding a record is an append,
        and the store's duplicate-sequence refusal means this method has no code
        path that could overwrite one.

        ``written_at`` is required and must be timezone-aware: it is the instant
        the flush was persisted, kept apart from the trades' own instants, and a
        naive timestamp would make the record's place in the tape's write
        history unanswerable.  The store does not read a clock of its own — the
        caller that flushed owns the time the flush happened.
        """
        parsed = parse_agg_trades(document)
        _require_aware(written_at, "written_at")

        sequence = self._staging.current(AGG_TRADES_STREAM) + 1
        envelope = {
            "stream": str(AGG_TRADES_STREAM),
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
        compressed = _compress(payload)
        batch = self._staging.append(
            AGG_TRADES_STREAM, payload=compressed, rows=len(parsed)
        )
        return AggTradeRecord(
            sequence=batch.sequence,
            written_at=written_at.astimezone(_UTC),
            batch=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(compressed).hexdigest(),
            path=batch.path,
        )

    # -- Reading --------------------------------------------------------------

    def records(self) -> tuple[AggTradeRecord, ...]:
        """Every persisted record, oldest first.

        Read back from the staging log in ascending sequence order, each
        record's compressed bytes decompressed and its envelope verified against
        the sequence its filename claims and the document hash it recorded — so
        a reader gets either the record that was committed or a clear
        :class:`AggTradeCorruptError`, never a plausible-looking tape assembled
        from damaged bytes.
        """
        return tuple(
            self._read(batch) for batch in self._staging.staged(AGG_TRADES_STREAM)
        )

    def current(self) -> AggTradeRecord | None:
        """The most recent record, or ``None`` when nothing has been persisted."""
        batches = self._staging.staged(AGG_TRADES_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def previous(self) -> AggTradeRecord | None:
        """The record before :meth:`current`, or ``None`` when there is none.

        The comparison point a flush reports against: a worker can say whether
        the flush it just persisted carried different trades than the last one,
        which is the difference between a quiet cycle and a cycle the tape must
        absorb.
        """
        batches = self._staging.staged(AGG_TRADES_STREAM)
        if len(batches) < 2:
            return None
        return self._read(batches[-2])

    def record_at(self, sequence: int) -> AggTradeRecord | None:
        """The record persisted under ``sequence``, or ``None`` if never recorded.

        ``None`` distinguishes *that sequence was never recorded* from *the log
        holds a record under that number but its bytes are damaged*, which
        :meth:`records` and :meth:`current` raise for.  A caller walking the
        history — an audit asking what trades printed at a past flush — gets the
        honest absence rather than an exception for a number that simply never
        happened.
        """
        self.path_for(sequence)  # validates the argument; raises on a bad one
        for batch in self._staging.staged(AGG_TRADES_STREAM):
            if batch.sequence == sequence:
                return self._read(batch)
        return None

    def row_count(self) -> int:
        """How many trades the retained records hold in total."""
        return sum(record.row_count for record in self.records())

    def _read(self, batch) -> AggTradeRecord:
        # Read one committed batch back into a record, verifying as it goes.
        # The compressed bytes are decompressed first; then the three checks
        # below are the read half of the append-only guarantee: the bytes are
        # the bytes that were committed, under the sequence the filename claims,
        # carrying the document the envelope's hash vouches for.  A mismatch is
        # corruption (or tampering) on a tape a reader walks as the market's
        # trade history, so it is raised rather than papered over.
        try:
            raw = _decompress(batch.payload)
        except (OSError, EOFError) as exc:
            raise AggTradeCorruptError(
                f"aggTrade record {batch.sequence} is not gzip-compressed "
                f"({COMPRESSION}); the file's bytes are not a record this store "
                f"wrote: {exc}"
            ) from exc
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise AggTradeCorruptError(
                f"aggTrade record {batch.sequence} is not readable as a JSON "
                f"envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise AggTradeCorruptError(
                f"aggTrade record {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise AggTradeCorruptError(
                f"aggTrade record {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"record envelope this store wrote"
            )
        recorded = envelope["sequence"]
        if recorded != batch.sequence:
            raise AggTradeCorruptError(
                f"aggTrade record file {batch.sequence}.bin records sequence "
                f"{recorded!r}; the file does not describe itself"
            )
        document = parse_agg_trades(envelope[_DOCUMENT_KEY])
        recorded_hash = envelope["source_sha256"]
        if recorded_hash != document.source_sha256:
            raise AggTradeCorruptError(
                f"aggTrade record {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{document.source_sha256!r}; the file's bytes are not the "
                f"bytes that were committed"
            )
        return AggTradeRecord(
            sequence=batch.sequence,
            written_at=_parse_timestamp(envelope["written_at"], batch.sequence),
            batch=document,
            source_sha256=document.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


def _row_to_envelope(row: AggTradeRow) -> dict[str, object]:
    # Persisted in the venue's own order, with the values in their native kinds
    # — strings for price/quantity (verbatim), integers for the ids, a datetime
    # for the instant, a bool for the maker flag — so a reader (and a human
    # diffing two records) sees the trade as the feed sent it.  The canonical
    # form used for hashing is a different thing and is not written to disk.
    return {
        "symbol": row.symbol,
        "agg_id": row.agg_id,
        "price": row.price,
        "quantity": row.quantity,
        "first_trade_id": row.first_trade_id,
        "last_trade_id": row.last_trade_id,
        "event_time": _isoformat_utc(row.event_time),
        "is_buyer_maker": row.is_buyer_maker,
    }


def _row_to_canonical(row: AggTradeRow) -> dict[str, object]:
    # The canonical form the content hash is taken over: the same fields as the
    # envelope, rendered so two flushes carrying the same trade agree on their
    # hash whatever order the venue delivered its trades in.  The envelope and
    # the canonical form carry the same values — the instant as an ISO instant,
    # the ids as integers, price and quantity verbatim — so the one builder
    # serves both.
    return _row_to_envelope(row)


def _require_aware(moment: object, what: str) -> None:
    # A trade's instant and a flush's write time are both placed by arithmetic
    # on instants, so a naive timestamp would be unsubtractable from an aware
    # one at exactly the boundary each rule turns on.  Refused here, where a
    # caller can still fix its clock handling, rather than silently assumed to
    # be UTC and recorded wrong.
    if not isinstance(moment, datetime):
        raise TypeError(f"{what} must be a datetime, not {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{what} must be timezone-aware; a naive timestamp cannot place a "
            f"trade on the tape or date a flush's write"
        )


def _isoformat_utc(moment: datetime) -> str:
    # Persisted in UTC with an explicit offset, so the record says when a trade
    # happened — or when the flush was written — without the reader assuming.
    return moment.astimezone(_UTC).isoformat()


def _parse_timestamp(raw: object, sequence: int) -> datetime:
    if not isinstance(raw, str):
        raise AggTradeCorruptError(
            f"aggTrade record {sequence} records a timestamp {raw!r}; expected "
            f"an ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise AggTradeCorruptError(
            f"aggTrade record {sequence} records an unparseable timestamp "
            f"{raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise AggTradeCorruptError(
            f"aggTrade record {sequence} records a naive timestamp {raw!r}; the "
            f"tape needs a comparable instant"
        )
    return parsed.astimezone(_UTC)


class AggTradeWorker:
    """The aggTrades worker: flush each cycle's trades into the compressed log.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the ``aggTrades``
    stream class, so the supervisor of feature 16 runs it on its own thread
    alongside every other stream and converts whatever it raises into that
    stream's own failure.  One cycle is:

    * **Flush.**  Call the injected :data:`AggTradeFetch`.  The websocket
      client, its auth, its rate limits and its reconnect policy are the
      deployment's business (§15's *"WS gap / reconnect"* row belongs to
      features 25 and 26); this worker owns only the persistence and the
      compression.  A fetch returning ``None`` is a *quiet* cycle — the feed
      delivered no trades this slice — reported as zero rows, not a failure: a
      liquid book prints continuously but a quiet one can legitimately go a
      cycle without a trade, and treating that as an error would fail an honest
      stream.
    * **Record.**  Parse first, then record the batch, **compressing** it before
      it touches disk.  A failed flush — a truncated frame, an error page, an
      empty response — raises :class:`AggTradeParseError` *before* anything is
      written, so the log never records a flush that did not happen.

    Unlike the book-diff worker there is no retention pass: this stream's §4.1
    row is *forever*, so nothing is ever retired, and the permanent tape is the
    append-only area's own property rather than anything this worker enforces.
    The clock is injected because ``written_at`` is a fact about elapsed
    wall-clock time: a test must be able to place the worker's writes without
    touching the wall clock, and §12 keeps wall-clock reads out of checked code
    in any case.  The default clock reads the system UTC time, which is what a
    deployment wants.
    """

    def __init__(
        self,
        store: AggTradeStore,
        fetch: AggTradeFetch,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, AggTradeStore):
            raise TypeError(
                f"the aggTrade worker persists into an AggTradeStore, "
                f"got {type(store).__name__}"
            )
        if not callable(fetch):
            raise TypeError(
                f"fetch must be a zero-argument callable returning the venue's "
                f"aggTrade response, got {type(fetch).__name__}"
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
        """The one stream class this worker owns — ``aggTrades``."""
        return AGG_TRADES_STREAM

    @property
    def store(self) -> AggTradeStore:
        """The compressed record log this worker appends to."""
        return self._store

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Run one cycle: flush the trades and persist them, compressed.

        Returns the persisted record's sequence as the cycle's watermark, so a
        monitor sees the log advance, and ``rows_written`` as the number of
        trades the record carries.  A quiet cycle — a fetch that returned
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


def register_agg_trade_worker(
    fetch: AggTradeFetch,
    store: Optional[AggTradeStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], AggTradeWorker]:
    """Register a worker factory bound to an explicitly wired fetch.

    The operator path: hand in the websocket client's fetch (and, when it is not
    the lake's staging area, the store), and this registers a worker factory
    bound to those collaborators.  Registration replaces the auto-discovered
    factory of the same class in the registry it targets — the registry's own
    rule, *a re-registered class is a revision of the same worker, never a
    second worker* — so a deployment that wires a client does not end up with
    two aggTrade workers competing for the same sequence numbers.

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
            f"aggTrade response, got {type(fetch).__name__}"
        )

    def build() -> AggTradeWorker:
        resolved_store = store if store is not None else AggTradeStore.from_env()
        return AggTradeWorker(resolved_store, fetch, clock=clock)

    # Register through a private registry by default, never the process-wide
    # one.  Registration is a *deployment* act: writing a caller's wiring into
    # the default registry would replace the auto-discovered worker for every
    # later composition in the process — including tests, which would then be
    # handed a worker bound to a store that has since been deleted.  A caller
    # that genuinely means to reconfigure the running process passes the default
    # registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        AGG_TRADES_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(AGG_TRADES_STREAM)
def build_agg_trade_worker() -> AggTradeWorker:
    """Compose the aggTrade worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    Collaborators come from the environment the way every other ingest seam
    does: the store is the lake's staging area (:meth:`AggTradeStore.from_env`),
    so records land in the very area the seal copies out of — compressed, as
    feature 18 requires.  The fetch has no environment-resolved default — this
    member ships no websocket client, so the venue's auth, rate limits and
    reconnect policy stay the deployment's business — and a deployment wires it
    with :func:`register_agg_trade_worker`.  Until then the worker still
    composes and its cycle reports that stream's own failure, which is feature
    16's contract: an unconfigured stream is a row in the report, not a
    component that fails to load.
    """
    return AggTradeWorker(AggTradeStore.from_env(), _unconfigured_fetch)


def _unconfigured_fetch() -> object:
    """The fetch used when a deployment has not wired a websocket client yet.

    Raising here, rather than at composition time, keeps the plugin shaped the
    way feature 16 wants it: an unconfigured stream is that stream's failure in
    the report, not a component that fails to compose.
    """
    raise AggTradeError(
        "no aggTrade fetch is configured; register the worker with a fetch "
        "returning the venue's aggTrade response "
        "(nullius_ingest.register_agg_trade_worker(fetch, store=..., "
        "registry=default_worker_registry()))"
    )
