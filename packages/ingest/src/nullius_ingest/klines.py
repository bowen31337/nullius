"""Klines (1m/1h/1d) off a REST backfill and a websocket tail, retained permanently.

app_spec.xml feature 17 states the behaviour: *"System ingests 1m, 1h and 1d
klines from REST backfill plus a websocket tail, persisting rows into the
staging area."*  docs/nullius-tech-architecture.md §4.1 fixes the stream's row
in the data-layer table — ``Klines 1m/1h/1d | REST backfill + WS | continuous |
forever`` — and two columns of that row are load-bearing and, taken together,
set this stream apart from every other in the table:

* **The source is *REST backfill plus a websocket tail*.**  This is the one
  stream §4.1 gives a dual source: a REST backfill fills a historical range of
  already-closed candles, and a websocket tail keeps the newest interval open
  until the next one closes.  The two are the same kind of object to the ingest
  layer — a candle, parsed and placed in an append-only log — so they share one
  :class:`KlineRow`, one :class:`KlineStore` and one content hash, and differ
  only in who drives them: the backfill is a paged range fetch, the tail is one
  flush per cycle.  This is the deliberate contrast with the WS-only streams
  (:mod:`nullius_ingest.agg_trades`, :mod:`nullius_ingest.book_diffs`): those
  never reach back, whereas a kline reader reaches back across the whole
  *forever* history and the backfill is how that history is first filled.

* **The retention is *forever*.**  Like aggTrades, funding and exchangeInfo,
  and unlike the L2 book diffs §4.1 keeps for a rolling 90 days, the kline
  series is kept permanently: a closed candle is an irreversible fact of the
  market, and a row dropped at ingest time is a row no replay can ever recover —
  the venue's kline history endpoints age out, so the candles captured here are
  the only honest copy.  This module is that "forever" made structural: it
  appends each flush and each backfill page into the append-only staging area,
  which is written once and copied by the seal, never rewritten and never
  expired.  There is deliberately no ``prune`` here, unlike
  :mod:`nullius_ingest.book_diffs`: a retention window that removes data would
  contradict the §4.1 row this stream exists to serve.

Two properties no other stream claims fall out of the dual source and are
enforced rather than hoped for:

* **The interval is one of 1m, 1h or 1d.**  A kline is a candle over a fixed
  interval, and §4.1 names exactly three.  The interval is carried as a named
  member of :data:`INTERVALS` and validated at the row boundary, so a candle of
  any other interval is refused rather than persisted — the reader that walks
  the log by interval must be able to trust that a "1m" candle is a 1m candle
  and not a typo the venue sent.

* **A backfill page is verified against the range it was asked for.**  The REST
  backfill names an inclusive range of candle open times; after a page the
  backfiller checks that the candles it got cover that range — the fetch was
  asked for ``first..last`` and must return that range, no less.  A short page
  leaves the backfill open and raises :class:`KlineBackfillError`, so a reader
  is not told a range is filled when a hole in it is still open.

The rest of the module follows the landed ingest streams — :mod:`nullius_ingest.funding`
and :mod:`nullius_ingest.agg_trades` — because a kline is the same kind of
object to the ingest layer: a payload, parsed, placed in an append-only log,
retained.  Three pieces, mirroring them:

* **The row** — :class:`KlineRow`: one candle, with the venue's OHLCV fields
  kept **verbatim** in their native string spelling (``"61234.50"``, not
  ``Decimal``), exactly as funding keeps its rates and book diffs keep their
  levels: whether the venue said ``"0.00010"`` or ``"0.0001"`` is a fact about
  the venue, and re-rendering it would make an audit unable to tell a venue
  change from our own lossy parse.  The candle's open and close instants are
  kept as aware :class:`~datetime.datetime`, exact on the epoch lattice, and
  the trade count as an integer.

* **The record** — :class:`KlineRecord`: one *flush or page*, frozen, with the
  sequence it was persisted under, when it was written, the span of candle open
  times it covers, the document's content hash and the hash of the bytes
  written.  The two hashes are deliberately distinct, as funding's and
  book diffs' records carry them: ``source_sha256`` is over the *uncompressed*
  canonical document and answers "did the candles change?"; ``payload_sha256``
  is over the bytes actually committed — the file's identity, the same value
  the seal's MANIFEST will record for it.

* **The store** — :class:`KlineStore`: an append-only log of records under the
  §4.1 staging area, at ``<lake>/staging/klines/<seq>.bin``, whose every write
  is the same durable append the other streams use.  *Persisting each flush's
  or page's candles, retained permanently* is therefore structural, not a
  convention: the store appends at ``current + 1`` into feature 28's
  append-only area (:class:`~nullius_ingest.staging.StagingArea`), whose batch
  store refuses a second batch at a sequence it already holds and which nothing
  in the system ever expires, so a candle's bytes are frozen the moment the
  next flush lands and no candle is ever dropped.

The module owns two entry points on top of that shared store, as the dual
source requires:

* **The tail** — :class:`KlineWorker`: flush each cycle's candles into the log.
  Layering on the stream workers of feature 16 is deliberate, as it is for
  every other stream: this is one worker owning one stream class, so a failed
  flush is that stream's :class:`~nullius_ingest.worker.StreamFailure` and every
  other stream keeps ingesting.  The fetch is injected (:data:`KlineFetch`) —
  the member ships no websocket client, exactly as it ships no REST client, so
  the venue's auth, rate limits and reconnect policy stay the deployment's
  business.

* **The backfill** — :class:`KlineBackfiller`: page a historical range into the
  log over an injected REST fetch.  The fetch is a :data:`KlineBackfillFetch`
  the caller supplies — the stream worker of feature 17 owns the exchange's
  REST client and its auth, rate limits and pagination, none of which this
  module knows.  The backfiller owns only the *orchestration*: which range is
  open, how to page it, and when a page counts as covering it.

The clock is injected because ``written_at`` is a fact about elapsed wall-clock
time and §12 keeps wall-clock reads out of checked code.  The member stays
stdlib-only: there is no compression here (§4.1 marks only aggTrades
"compressed"), so a record's bytes are the plain envelope, exactly as funding
and exchangeInfo write them.
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
    "INTERVALS",
    "KLINES_STREAM",
    "KlineBackfillError",
    "KlineBackfiller",
    "KlineBackfillFetch",
    "KlineBatch",
    "KlineCorruptError",
    "KlineError",
    "KlineFetch",
    "KlineInterval",
    "KlineParseError",
    "KlineRecord",
    "KlineRow",
    "KlineStore",
    "KlineTimestampUnitError",
    "KlineWorker",
    "build_kline_worker",
    "parse_klines",
    "register_kline_worker",
]

#: The stream class this module serves.  §4.1's table row for klines is the
#: stream whose source is a REST backfill plus a websocket tail, and the
#: spelling here is the persisted one (:class:`~nullius_ingest.streams.
#: StreamClass`), so the staging layout and the record log share it.
KLINES_STREAM = StreamClass.KLINES

#: The three intervals §4.1's table records for this stream: 1m, 1h and 1d.
#: Carried as a closed set so the fact is named where it is decided — a candle
#: of any other interval is refused at the row boundary rather than persisted
#: under a spelling the reader that walks the log by interval cannot trust.
INTERVALS: Final[tuple[str, ...]] = ("1m", "1h", "1d")

#: The interval, as one of the three :data:`INTERVALS` spellings.  Kept as a
#: distinct type alias so the row's validation reads as "a KlineInterval" rather
#: than "a str that happens to be one of three values".
KlineInterval = str

#: The envelope keys a record file carries around its candles — named so a
#: reader of a record file (an operator, a seal, a later audit) does not have
#: to import this module to know what it is looking at.  ``candles`` is the
#: document.  The two time bounds name the span of candle *open* times the
#: flush or page covers — distinct from ``written_at``, which is when *we*
#: persisted it — because a reader walking the series wants to know which
#: candles a record holds without opening it.
_ENVELOPE_KEYS = (
    "stream",
    "sequence",
    "interval",
    "written_at",
    "source_sha256",
    "first_open",
    "last_open",
)

#: Wrapper keys under which a venue endpoint may nest its candle list — the
#: flat list is also accepted (see :func:`parse_klines`), so this is a
#: convenience, not a closed set.
_WRAPPER_KEYS = ("klines", "klines_data", "data", "results")

#: The envelope key holding the candles, named beside the keys around it so a
#: reader of a record file does not have to hunt for it.
_DOCUMENT_KEY = "candles"

#: The number of milliseconds in the units the three intervals span, used to
#: turn a venue event time into an aware instant exact on the epoch lattice.
_MILLIS_PER_SECOND = 1000
_MICROS_PER_MILLI = 1000

#: The epoch-magnitude bands :func:`_epoch_value_to_micros` reads a venue
#: instant's unit from.  Binance's own archive carried millisecond epochs
#: (13 digits, e.g. ``1733011200000`` for 2024-12-01T00:00Z) through its
#: 2024-12 file and switched to microsecond epochs (16 digits, e.g.
#: ``1735689600000000`` for the same instant a month later) from its 2025-01
#: file on, with no flag distinguishing the two — the live REST and websocket
#: paths stay millisecond-only throughout.  The unit is read from the value's
#: own magnitude rather than guessed from a date or a feed, so a value of
#: neither shape is refused rather than silently misinterpreted into a candle
#: decades off or, worse, overflowing :class:`~datetime.datetime` outright.
_EPOCH_MILLIS_CEILING: Final[int] = 10**14  # below this: milliseconds
_EPOCH_MICROS_FLOOR: Final[int] = 10**15  # from this (inclusive): microseconds...
_EPOCH_MICROS_CEILING: Final[int] = 10**17  # ...up to (not including) this

_UTC = timezone.utc

#: The epoch, in UTC: the instant every venue event time is measured from.  A
#: candle's open and close instants are exact integer counts of microseconds
#: from here, so no float ever touches an instant and a boundary is a boundary
#: rather than a rounding, on every platform.
_EPOCH = datetime(1970, 1, 1, tzinfo=_UTC)


class KlineError(Exception):
    """Base for every failure this module raises.

    Raised for a payload this module will not persist and for a persisted record
    it will not read: both are cases where the kline series would otherwise
    start lying about what the venue's candles did, so both fail loudly rather
    than being approximated into a row.
    """


class KlineParseError(KlineError):
    """A kline payload is not one this module will persist.

    Raised *before* anything is written, so a rate-limit body, a truncated
    frame or a wrong-interval candle never consumes a sequence number and never
    appears in the log as a candle that happened.  The message names what was
    wrong with which candle, because the caller is a worker or a backfiller
    whose next move depends on whether the venue's shape changed or the feed
    simply hiccuped.
    """


class KlineTimestampUnitError(KlineParseError):
    """A venue epoch instant's magnitude is neither milliseconds nor microseconds.

    Binance's own archive carries millisecond epochs through its 2024-12 file
    and microsecond epochs from its 2025-01 file on, with no flag
    distinguishing the two — see :func:`_epoch_value_to_micros`, which reads
    the unit from the value's magnitude rather than from the file's date or
    the feed's identity.  Raised when a value falls in neither recognized
    band, so an instant of an unrecognized shape is refused here rather than
    guessed or left to overflow :class:`~datetime.datetime` downstream.  A
    subclass of :class:`KlineParseError`, so existing callers that catch the
    base class still catch this.
    """


class KlineCorruptError(KlineError):
    """A persisted record file does not match what was written under it.

    Raised when a record file cannot be read back as the JSON envelope it was
    written as, when its recorded sequence is not the sequence its filename
    claims, or when recomputing its document hash disagrees with the hash the
    envelope recorded.  The log is append-only and copied byte-for-byte by the
    seal, so a mismatch means the bytes on disk are not the bytes this module
    committed — corruption or tampering — and a reader reconstructing the kline
    series from them would be reconstructing candles that never happened.
    """


class KlineBackfillError(KlineError):
    """A backfill page did not cover the range it was asked to fill.

    Raised when the candles a :data:`KlineBackfillFetch` returned for a range do
    not span that range — too few candles, or a candle outside the range.  The
    refusal is the backfill's load-bearing half: a range is only marked covered
    when the page provably covered it, so a reader is not told a hole is filled
    when a short page left it open.  The error carries the range and the span
    the page actually covered, so the alert can state precisely what is still
    missing.
    """

    def __init__(
        self,
        symbol: str,
        interval: KlineInterval,
        requested_first: int,
        requested_last: int,
        covered_first: int,
        covered_last: int,
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.requested_first = requested_first
        self.requested_last = requested_last
        self.covered_first = covered_first
        self.covered_last = covered_last
        super().__init__(
            f"{symbol} {interval} backfill for {requested_first}..{requested_last} "
            f"covered {covered_first}..{covered_last}; the page did not fill the "
            f"requested range"
        )


def _scalar_field(value: object, where: str) -> str:
    # OHLCV field values are persisted as the venue's own spelling.  Venues are
    # inconsistent about JSON types for the same field — a price arrives as a
    # string on one feed and a bare number on another — so scalars are spelled
    # rather than rejected, while containers are refused: a nested object is a
    # shape this module does not model, and storing its ``repr`` would be a
    # record that looks like data and is not.
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
    raise KlineParseError(
        f"{where} is {type(value).__name__}; price and volume values must be "
        f"scalars (the venue's own spelling is kept verbatim)"
    )


def _int_field(value: object, where: str) -> int:
    # The trade count is persisted as an integer: unlike a price it is compared
    # and ordered, and ordering two spellings of the same number is not a thing
    # this system should ever have to reason about.  A fractional count is
    # refused rather than truncated: a count is a count, and a non-integer is
    # not one.
    if isinstance(value, bool):
        raise KlineParseError(f"{where} is a boolean; expected an integer count")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise KlineParseError(
                f"{where} is {value!r}; expected an integer count: {exc}"
            ) from exc
    raise KlineParseError(
        f"{where} is {type(value).__name__}; expected an integer count"
    )


def _as_epoch_value(value: object, where: str) -> int:
    # Turn a *venue-supplied* instant into an exact integer epoch value — its
    # unit (milliseconds or microseconds) is not yet decided here.  Venues are
    # inconsistent about JSON types for the same field — an open time arrives
    # as a bare number on one feed and a string on another — so a float or a
    # numeric string is coerced here, at the boundary where that sloppiness is
    # a fact about the venue.  Refusals are the module's own error, not
    # whatever ``int()`` happened to raise, because the caller is a worker or
    # a backfiller deciding whether the venue's shape changed.  The unit is
    # read from the resulting value's magnitude by
    # :func:`_epoch_value_to_micros`, not here.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise KlineParseError(
            f"{where} is {type(value).__name__}; expected an epoch-millisecond "
            f"instant"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise KlineParseError(
            f"{where} is {value!r}; expected an epoch-millisecond instant: {exc}"
        ) from exc
    if parsed < 0:
        raise KlineParseError(
            f"{where} is {parsed}; an epoch instant is non-negative"
        )
    return parsed


def _epoch_value_to_micros(value: int, where: str) -> int:
    # Read ``value``'s unit from its magnitude and return epoch microseconds,
    # exact.  Below _EPOCH_MILLIS_CEILING (a 13-digit value, e.g. the
    # archive's 2024-12 file) the value is milliseconds and is scaled up;
    # from _EPOCH_MICROS_FLOOR up to (not including) _EPOCH_MICROS_CEILING (a
    # 16-digit value, e.g. the archive's 2025-01 file on) the value is
    # already microseconds and is returned unchanged — converted exactly to
    # the same instant, never through a millisecond intermediate, which would
    # be a lossy round trip the other way.  Anything in the gap between the
    # two bands, or at or above the top of the microsecond band, is a
    # magnitude this module does not recognize: refused rather than guessed.
    if value < _EPOCH_MILLIS_CEILING:
        return value * _MICROS_PER_MILLI
    if _EPOCH_MICROS_FLOOR <= value < _EPOCH_MICROS_CEILING:
        return value
    raise KlineTimestampUnitError(
        f"{where} is {value}; its magnitude is neither a millisecond epoch "
        f"(below {_EPOCH_MILLIS_CEILING}) nor a microsecond epoch "
        f"({_EPOCH_MICROS_FLOOR} to {_EPOCH_MICROS_CEILING}); refusing rather "
        f"than guessing the unit"
    )


def _micros_to_utc(micros: int) -> datetime:
    # Exact: the epoch plus an integer count of microseconds.  No float and
    # no ``timestamp()`` round trip, either of which would put a rounding
    # between the venue's instant and the series.
    return _EPOCH + timedelta(microseconds=micros)


def _interval_field(value: object, where: str) -> KlineInterval:
    # The interval is one of the three :data:`INTERVALS` §4.1 names.  Refused
    # rather than coerced when it is not: a candle of any other interval is a
    # candle the reader that walks the log by interval cannot trust, and
    # persisting it would let an unknown cadence masquerade as a 1m, 1h or 1d
    # candle on the series the downstream paths read.
    if not isinstance(value, str):
        raise KlineParseError(
            f"{where} is {type(value).__name__}; the interval must be a string"
        )
    if value not in INTERVALS:
        raise KlineParseError(
            f"{where} is {value!r}; the interval must be one of "
            f"{', '.join(INTERVALS)}"
        )
    return value


@dataclass(frozen=True)
class KlineRow:
    """One candle, as the venue reported it.

    Seven facts, each load-bearing:

    * ``symbol`` — which book the candle printed in.
    * ``interval`` — the candle's cadence, one of ``1m``/``1h``/``1d``.  Kept as
      a validated :data:`KlineInterval` because the series is walked by it, and
      a wrong interval would put a candle on the wrong cadence.
    * ``open`` / ``high_price`` / ``low_price`` / ``close`` — the venue's own
      string spellings, kept verbatim.  Decimalisation is the cost path's
      business; this is the raw tape, so re-rendering a price would destroy the
      one thing raw data is for.  The high and low are named ``high_price`` and
      ``low_price`` after the §4.1 row's price fields, so a reader reaching for
      the candle's price ladder finds it under the name the spec gives it.
    * ``volume`` — the venue's own string spelling of the traded base volume
      over the candle.  Kept verbatim for the same reason as the prices.
    * ``open_time`` / ``close_time`` — the venue's instants the candle opened
      and closed, timezone-aware and exact on the epoch lattice.  The series is
      ordered by ``open_time`` and a reader walks it in open-time order.
    * ``trade_count`` — how many trades printed inside the candle, as an
      integer.  Kept as an integer because it is compared and ordered.

    The row is frozen: a record is what the venue sent, and a caller mutating it
    in place would be editing the permanent series.
    """

    symbol: str
    interval: KlineInterval
    open: str
    high_price: str
    low_price: str
    close: str
    volume: str
    open_time: datetime
    close_time: datetime
    trade_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise KlineParseError(
                f"a kline must carry a non-empty symbol, got {self.symbol!r}"
            )
        _interval_field(self.interval, "interval")
        if not self.open:
            raise KlineParseError(f"{self.symbol} carries an empty open")
        if not self.high_price:
            raise KlineParseError(f"{self.symbol} carries an empty high_price")
        if not self.low_price:
            raise KlineParseError(f"{self.symbol} carries an empty low_price")
        if not self.close:
            raise KlineParseError(f"{self.symbol} carries an empty close")
        if not self.volume:
            raise KlineParseError(f"{self.symbol} carries an empty volume")
        if not isinstance(self.trade_count, int) or isinstance(self.trade_count, bool):
            raise KlineParseError(
                f"{self.symbol} trade_count must be an integer, got "
                f"{type(self.trade_count).__name__}"
            )
        if self.trade_count < 0:
            raise KlineParseError(
                f"{self.symbol} carries trade_count {self.trade_count}; a trade "
                f"count is non-negative"
            )
        _require_aware(self.open_time, "open_time")
        _require_aware(self.close_time, "close_time")
        object.__setattr__(self, "open_time", self.open_time.astimezone(_UTC))
        object.__setattr__(self, "close_time", self.close_time.astimezone(_UTC))
        if self.close_time < self.open_time:
            # A candle that closes before it opens is not a candle this module
            # can record: the pair is the candle's span, and a reversed one
            # would make the series appear to run backwards.
            raise KlineParseError(
                f"{self.symbol} closes at {self.close_time} before it opens at "
                f"{self.open_time}; a candle does not close before it opens"
            )

    @property
    def open_millis(self) -> int:
        """The candle's open instant, as epoch milliseconds — its place in the series."""
        return _millis_from_utc(self.open_time)

    @property
    def close_millis(self) -> int:
        """The candle's close instant, as epoch milliseconds — its span's end."""
        return _millis_from_utc(self.close_time)


def _millis_from_utc(moment: datetime) -> int:
    # The inverse of :func:`_micros_to_utc`, pinned to milliseconds: an aware
    # instant becomes an exact integer count of epoch milliseconds, so a
    # candle's open time round-trips between the datetime and the integer the
    # live REST path and the envelope both carry — milliseconds throughout,
    # unaffected by the archive's microsecond epochs, which this module
    # converts to an exact instant on read rather than ever re-deriving from.
    delta = moment.astimezone(_UTC) - _EPOCH
    return int(delta.total_seconds()) * _MILLIS_PER_SECOND + delta.microseconds // _MICROS_PER_MILLI


def _parse_candle(
    entry: object, index: int, interval: KlineInterval, fallback_symbol: str | None
) -> KlineRow:
    if not isinstance(entry, (Mapping, Sequence)) or isinstance(entry, (str, bytes)):
        raise KlineParseError(
            f"candles[{index}] is {type(entry).__name__}; expected an object"
        )
    where = f"candles[{index}]"
    # A candle may be a mapping (``{"s": ..., "o": ...}``) or a positional list
    # (the venue's klines endpoint returns each candle as a fixed-length array).
    # Looked for by key when the payload is a mapping, by position when it is a
    # list, so both spellings parse.
    if isinstance(entry, Mapping):
        symbol = entry.get("symbol", entry.get("s"))
        raw_open = entry.get("open", entry.get("o"))
        raw_high = entry.get("high", entry.get("h"))
        raw_low = entry.get("low", entry.get("l"))
        raw_close = entry.get("close", entry.get("c"))
        raw_volume = entry.get("volume", entry.get("v"))
        raw_open_time = entry.get("open_time", entry.get("openTime", entry.get("O")))
        raw_close_time = entry.get("close_time", entry.get("closeTime", entry.get("C")))
        raw_trades = entry.get("trades", entry.get("trade_count", entry.get("n")))
    else:
        # Positional kline: [open_time, open, high, low, close, volume,
        # close_time, quote_volume, trade_count, ...].  Binance's own array is
        # longer than this (taker-buy volumes and an ignored trailing field
        # follow), but these are the fields the ingest layer persists.  Index 7
        # is the *quote asset volume* (a decimal string), not the trade count —
        # index 8 is the trade count, and the two are easy to swap by one.
        if len(entry) < 9:
            raise KlineParseError(
                f"{where} carries {len(entry)} fields; a positional kline needs "
                f"at least open_time, open, high, low, close, volume, close_time, "
                f"quote_volume and trade_count"
            )
        raw_open_time = entry[0]
        raw_open = entry[1]
        raw_high = entry[2]
        raw_low = entry[3]
        raw_close = entry[4]
        raw_volume = entry[5]
        raw_close_time = entry[6]
        raw_trades = entry[8]
        symbol = fallback_symbol

    if not isinstance(symbol, str) or not symbol:
        raise KlineParseError(
            f"{where} has no non-empty 'symbol' string (got {symbol!r}); "
            f"a positional kline carries the symbol as the request parameter"
        )

    if raw_open is None or raw_high is None or raw_low is None:
        raise KlineParseError(f"{where} ({symbol}) is missing open, high or low")
    if raw_close is None or raw_volume is None:
        raise KlineParseError(f"{where} ({symbol}) is missing close or volume")
    if raw_open_time is None:
        raise KlineParseError(
            f"{where} ({symbol}) carries no open time; a candle with no instant "
            f"cannot be placed on the series"
        )
    if raw_close_time is None:
        # A candle's close time is the next candle's open time; when the venue
        # omits it (an open candle on the tail), the close is unknown and the
        # candle is refused rather than guessed — a closed candle is what this
        # module persists, and an open one belongs to the tail's next flush.
        raise KlineParseError(
            f"{where} ({symbol}) carries no close time; a persisted kline is a "
            f"closed candle"
        )

    return KlineRow(
        symbol=symbol,
        interval=interval,
        open=_scalar_field(raw_open, f"{where}.open"),
        high_price=_scalar_field(raw_high, f"{where}.high"),
        low_price=_scalar_field(raw_low, f"{where}.low"),
        close=_scalar_field(raw_close, f"{where}.close"),
        volume=_scalar_field(raw_volume, f"{where}.volume"),
        open_time=_micros_to_utc(
            _epoch_value_to_micros(
                _as_epoch_value(raw_open_time, f"{where}.open_time"),
                f"{where}.open_time",
            )
        ),
        close_time=_micros_to_utc(
            _epoch_value_to_micros(
                _as_epoch_value(raw_close_time, f"{where}.close_time"),
                f"{where}.close_time",
            )
        ),
        trade_count=_int_field(raw_trades, f"{where}.trades"),
    )


def _as_candle_list(body: object, interval: KlineInterval) -> Sequence[object]:
    # The candles may arrive as a bare list or nested under one of the common
    # wrapper keys.  Looked for in this order so a bare list is never mistaken
    # for a wrapper.
    if isinstance(body, list):
        return body
    if isinstance(body, Mapping):
        for key in _WRAPPER_KEYS:
            nested = body.get(key)
            if isinstance(nested, list):
                return nested
    raise KlineParseError(
        "kline payload has no candle list; the document is not a kline response"
    )


@dataclass(frozen=True)
class KlineBatch:
    """One flush's or page's candles — the unit this stream persists.

    A batch is what a worker cycle or a backfill page writes: whatever candles
    the fetch delivered, across as many symbols as that flush or page happened
    to carry, all at one :attr:`interval`.  It makes **no completeness claim
    about any instant**: a reader walks the series by ``open_time`` across
    batches, exactly as it would walk a single batch, because a websocket flush
    is a deployment-paced slice and a backfill page is a deployment-paced chunk,
    neither a market boundary.  ``candles`` keeps the venue's order, because
    that is the order a human reading the record will read — the same
    asymmetry funding and book diffs draw between their persisted document and
    their canonical hash.  A batch with no candles is refused: an empty kline
    response is a rate-limit body, a truncated frame or a page past the end,
    never a candle.
    """

    interval: KlineInterval
    candles: Sequence[KlineRow]

    def __post_init__(self) -> None:
        interval = _interval_field(self.interval, "interval")
        candles = list(self.candles)
        if not candles:
            # Refused deliberately.  An empty kline response is a failed or
            # truncated flush, a rate-limit body or a page past the end — never
            # data — and persisting it would make a failed cycle indistinguishable
            # from a quiet one in the very series a reader walks as the market's
            # history.
            raise KlineParseError(
                "a kline batch must carry at least one candle; an empty batch "
                "is a failed flush or a page past the end, not a quiet book"
            )
        for candle in candles:
            if not isinstance(candle, KlineRow):
                raise KlineParseError(
                    "a kline batch's candles must be KlineRow instances, "
                    f"got {type(candle).__name__}"
                )
            if candle.interval != interval:
                raise KlineParseError(
                    f"a kline batch at {interval} carries a {candle.interval} "
                    f"candle; a batch is one interval"
                )
        object.__setattr__(self, "interval", interval)
        object.__setattr__(self, "candles", tuple(candles))

    def __len__(self) -> int:
        """How many candles this batch carries — its row count."""
        return len(self.candles)

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this batch carries, in the venue's order, deduplicated."""
        seen: dict[str, None] = {}
        for candle in self.candles:
            seen.setdefault(candle.symbol, None)
        return tuple(seen)

    @property
    def first_open(self) -> datetime:
        """The earliest candle open time this batch carries — its span's start."""
        return min(candle.open_time for candle in self.candles)

    @property
    def last_open(self) -> datetime:
        """The latest candle open time this batch carries — its span's end."""
        return max(candle.open_time for candle in self.candles)

    def for_symbol(self, symbol: str) -> tuple[KlineRow, ...]:
        """This batch's candles for ``symbol``, in the venue's order."""
        return tuple(candle for candle in self.candles if candle.symbol == symbol)

    def canonical_bytes(self) -> bytes:
        """The batch's canonical JSON bytes — the thing content-hashed.

        Canonical means candles in a deterministic order (open time, then
        symbol), keys sorted, and the tightest separators — so two flushes or
        pages carrying the same candles hash identically whatever order the
        venue delivered its symbols in and whatever whitespace the transport
        added.  This is what makes :attr:`KlineRecord.source_sha256` a *content*
        hash: a batch that changed one price does not agree on it, and one that
        merely reordered its candles does.  Note the deliberate asymmetry with
        the persisted document, which keeps the venue's own order.
        """
        ordered = sorted(
            self.candles,
            key=lambda c: (c.open_time, c.symbol),
        )
        return json.dumps(
            {"candles": [_row_to_canonical(candle) for candle in ordered]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def source_sha256(self) -> str:
        """The sha256 of :meth:`canonical_bytes` — the batch's identity."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def parse_klines(
    document: object, interval: KlineInterval, *, symbol: str | None = None
) -> KlineBatch:
    """Parse a kline payload at a fixed interval into a :class:`KlineBatch`.

    Accepts the venue's response as decoded JSON — a list of candles, a wrapper
    some endpoints use (``{"klines": [...]}``), a JSON bytes or string body, or
    an already-parsed :class:`KlineBatch` — and refuses anything that is not a
    well-formed set of candles with :class:`KlineParseError`.

    Strict about the shape this system owns: each candle must name its symbol
    and carry an open, high, low, close and volume (kept verbatim), an open
    time and a close time (without which it cannot be placed on the series), a
    trade count, and an interval that is one of 1m, 1h or 1d.  Tolerant where
    the venue is free: a candle may be a mapping or a positional array, and the
    field names may be the venue's short spellings or the long ones — this
    module persists exactly the fields a kline is.

    ``symbol`` is a fallback for the positional-array form: the venue's per-symbol
    klines REST (``GET /klines?symbol=BTCUSDT``) returns each candle as a bare
    array with no symbol of its own — the symbol is the request parameter — so a
    backfill over that endpoint passes the symbol it requested and the array
    candles inherit it.  The mapping form, which carries its own symbol, ignores
    the fallback.
    """
    if isinstance(document, KlineBatch):
        return document
    if isinstance(document, (bytes, bytearray, str)):
        try:
            decoded = json.loads(document)
        except ValueError as exc:
            raise KlineParseError(
                f"kline payload is not valid JSON: {exc}"
            ) from exc
    else:
        decoded = document

    entries = _as_candle_list(decoded, interval)
    rows = [
        _parse_candle(entry, index, interval, symbol)
        for index, entry in enumerate(entries)
    ]
    return KlineBatch(interval=interval, candles=rows)


#: A tail fetch: return the venue's kline response, as JSON bytes, a JSON
#: string, a decoded mapping/list, or an already-parsed batch.
#:
#: The seam the deployment's websocket client fills.  This member ships no
#: websocket client — like the book-diff worker, which is handed its fetch
#: rather than owning one — so the venue's auth, rate limits and reconnect
#: policy stay the stream worker's business, and the store stays testable
#: without a network.  Whatever the fetch returns is parsed before anything is
#: written, so a failed flush never consumes a sequence.
KlineFetch = Callable[[], Union[bytes, str, Sequence, Mapping, KlineBatch, None]]

#: A backfill fetch: given the symbol, the interval and the inclusive first and
#: last open times (epoch milliseconds) of the range still to fill, return the
#: candles that cover that range, as JSON bytes, a JSON string, a decoded
#: mapping/list, or an already-parsed batch.
#:
#: The seam the deployment's REST client fills.  This member ships no REST
#: client, exactly as it ships no websocket client, so the venue's auth, rate
#: limits and pagination stay the deployment's business.  The backfiller asks
#: for exactly ``first`` and ``last``; the fetch returns the candles, which the
#: backfiller then checks span that range before it trusts the fill.
KlineBackfillFetch = Callable[
    [str, KlineInterval, int, int], Union[bytes, str, Sequence, Mapping, KlineBatch]
]


@dataclass(frozen=True)
class KlineRecord:
    """One persisted flush or page: the sequence it landed under and the candles it carried.

    ``sequence`` is the record's position in the stream's append-only log —
    ``1`` for the first flush or page, then ``2, 3, ...`` — and, because the log
    is feature 28's staging area, it is also the sequence of the batch the
    envelope bytes were committed as.  ``written_at`` is when *we* persisted the
    flush or page (UTC, timezone-aware) and is deliberately kept apart from the
    candles' ``open_time``, which is when *the venue* saw the candle open: the
    series is ordered by the latter, and conflating the two would let our own
    ingest lag decide a candle's place in the market's history.

    Two hashes, deliberately distinct, exactly as funding's and book diffs'
    records carry them: ``source_sha256`` is over the *uncompressed* canonical
    document and answers "did the candles change?"; ``payload_sha256`` is over
    the bytes actually written — the file's identity, the same value the seal's
    MANIFEST will record for it.  ``path`` names the ``<sequence>.bin`` the
    bytes were committed to, so a seal or an operator can point at the exact
    artifact; it is never written through, because the only way to add a record
    is another :meth:`KlineStore.record`.
    """

    sequence: int
    written_at: datetime
    batch: KlineBatch
    source_sha256: str
    payload_sha256: str
    path: Path

    @property
    def row_count(self) -> int:
        """How many candles this record carries."""
        return len(self.batch)

    @property
    def interval(self) -> KlineInterval:
        """The interval every candle in this record carries."""
        return self.batch.interval

    @property
    def first_open(self) -> datetime:
        """The earliest candle open time this record covers."""
        return self.batch.first_open

    @property
    def last_open(self) -> datetime:
        """The latest candle open time this record covers."""
        return self.batch.last_open

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this record carries, in the venue's order."""
        return self.batch.symbols


class KlineStore:
    """The append-only log of klines, retained permanently.

    Records live at ``<lake>/staging/klines/<sequence>.bin``, one file per flush
    or page, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a record is written once,
    atomically (temp file, ``fsync``, ``rename``), and never rewritten: the
    underlying batch store refuses a second batch at a sequence it already
    holds.  Every record is the plain envelope — there is no compression here,
    as §4.1 marks only aggTrades compressed — exactly as funding and
    exchangeInfo write their envelopes.  *Persisting each flush's or page's
    candles, retained permanently* is therefore the store's structure rather
    than its discipline: it appends at ``current + 1`` into an area nothing in
    the system ever expires, so a candle's bytes are frozen the moment the next
    flush lands and no candle is ever dropped by a retention window — there is
    deliberately no ``prune`` here, because the §4.1 row this store serves is
    *forever*.

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
                f"the kline store writes into a StagingArea, "
                f"got {type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "KlineStore":
        """The store over the lake's staging area, resolved from the environment.

        The same resolution the ingest workers and the sealing service use
        (``LAKE_ROOT``, defaulting to ``lake/`` beside the workspace root), so
        records land in the very area the seal copies out of — there is no
        second root that could drift from the first.
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
        return self._staging.path_for(KLINES_STREAM)

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
        document: Union[bytes, str, Sequence, Mapping, KlineBatch],
        interval: KlineInterval,
        *,
        written_at: datetime,
    ) -> KlineRecord:
        """Persist one flush or page as the next record; never overwrite a prior one.

        The document is parsed and validated *first*, so a failed flush consumes
        no sequence number and leaves the log untouched; then it is written as
        the next record — ``current + 1`` — into the stream's append-only
        staging log.  The previous records are not read, moved or rewritten:
        adding a record is an append, and the store's duplicate-sequence refusal
        means this method has no code path that could overwrite one.

        ``written_at`` is required and must be timezone-aware: it is the instant
        the flush or page was persisted, kept apart from the candles' own open
        times, and a naive timestamp would make the record's place in the
        series' write history unanswerable.  The store does not read a clock of
        its own — the caller that flushed owns the time the flush happened.
        """
        parsed = parse_klines(document, interval)
        _require_aware(written_at, "written_at")

        sequence = self._staging.current(KLINES_STREAM) + 1
        envelope = {
            "stream": str(KLINES_STREAM),
            "sequence": sequence,
            "interval": interval,
            "written_at": _isoformat_utc(written_at),
            "source_sha256": parsed.source_sha256,
            "first_open": _isoformat_utc(parsed.first_open),
            "last_open": _isoformat_utc(parsed.last_open),
            _DOCUMENT_KEY: [_row_to_envelope(candle) for candle in parsed.candles],
        }
        payload = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        batch = self._staging.append(
            KLINES_STREAM, payload=payload, rows=len(parsed)
        )
        return KlineRecord(
            sequence=batch.sequence,
            written_at=written_at.astimezone(_UTC),
            batch=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            path=batch.path,
        )

    # -- Reading --------------------------------------------------------------

    def records(self) -> tuple[KlineRecord, ...]:
        """Every persisted record, oldest first.

        Read back from the staging log in ascending sequence order, each
        record's bytes decompressed and its envelope verified against the
        sequence its filename claims and the document hash it recorded — so a
        reader gets either the record that was committed or a clear
        :class:`KlineCorruptError`, never a plausible-looking series assembled
        from damaged bytes.
        """
        return tuple(
            self._read(batch) for batch in self._staging.staged(KLINES_STREAM)
        )

    def current(self) -> KlineRecord | None:
        """The most recent record, or ``None`` when nothing has been persisted."""
        batches = self._staging.staged(KLINES_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def previous(self) -> KlineRecord | None:
        """The record before :meth:`current`, or ``None`` when there is none.

        The comparison point a flush reports against: a worker can say whether
        the flush it just persisted carried different candles than the last one,
        which is the difference between a quiet cycle and a cycle the series
        must absorb.
        """
        batches = self._staging.staged(KLINES_STREAM)
        if len(batches) < 2:
            return None
        return self._read(batches[-2])

    def record_at(self, sequence: int) -> KlineRecord | None:
        """The record persisted under ``sequence``, or ``None`` if never recorded.

        ``None`` distinguishes *that sequence was never recorded* from *the log
        holds a record under that number but its bytes are damaged*, which
        :meth:`records` and :meth:`current` raise for.  A caller walking the
        history — an audit asking what candles printed at a past flush — gets
        the honest absence rather than an exception for a number that simply
        never happened.
        """
        self.path_for(sequence)  # validates the argument; raises on a bad one
        for batch in self._staging.staged(KLINES_STREAM):
            if batch.sequence == sequence:
                return self._read(batch)
        return None

    def row_count(self) -> int:
        """How many candles the retained records hold in total."""
        return sum(record.row_count for record in self.records())

    def _read(self, batch) -> KlineRecord:
        # Read one committed batch back into a record, verifying as it goes.
        # The three checks below are the read half of the append-only guarantee:
        # the bytes are the bytes that were committed, under the sequence the
        # filename claims, carrying the document the envelope's hash vouches for.
        # A mismatch is corruption (or tampering) on a series a reader walks as
        # the market's history, so it is raised rather than papered over.
        raw = batch.payload
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise KlineCorruptError(
                f"kline record {batch.sequence} is not readable as a JSON "
                f"envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise KlineCorruptError(
                f"kline record {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise KlineCorruptError(
                f"kline record {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"record envelope this store wrote"
            )
        recorded = envelope["sequence"]
        if recorded != batch.sequence:
            raise KlineCorruptError(
                f"kline record file {batch.sequence}.bin records sequence "
                f"{recorded!r}; the file does not describe itself"
            )
        document = parse_klines(envelope[_DOCUMENT_KEY], envelope["interval"])
        recorded_hash = envelope["source_sha256"]
        if recorded_hash != document.source_sha256:
            raise KlineCorruptError(
                f"kline record {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{document.source_sha256!r}; the file's bytes are not the "
                f"bytes that were committed"
            )
        return KlineRecord(
            sequence=batch.sequence,
            written_at=_parse_timestamp(envelope["written_at"], batch.sequence),
            batch=document,
            source_sha256=document.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


def _row_to_envelope(row: KlineRow) -> dict[str, object]:
    # Persisted in the venue's own order, with the values in their native kinds
    # — strings for OHLCV (verbatim), an epoch-millisecond integer for the
    # instants, an integer for the trade count — so a reader (and a human
    # diffing two records) sees the candle as the feed sent it, and so the
    # envelope round-trips back through :func:`parse_klines`, which is what the
    # read path rebuilds the candles from.  The venue's kline wire format spells
    # an instant as an epoch-millisecond integer (``1772366400000``), so that
    # is the native kind here, not an ISO string.  The canonical form used for
    # hashing is the same rendering, so the two never drift.
    return {
        "symbol": row.symbol,
        "interval": row.interval,
        "open": row.open,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close,
        "volume": row.volume,
        "open_time": _millis_from_utc(row.open_time),
        "close_time": _millis_from_utc(row.close_time),
        "trade_count": row.trade_count,
    }


def _row_to_canonical(row: KlineRow) -> dict[str, object]:
    # The canonical form the content hash is taken over: the same fields as the
    # envelope, rendered so two flushes or pages carrying the same candle agree
    # on their hash whatever order the venue delivered its candles in.  It is
    # the same rendering as :func:`_row_to_envelope` — the instants as
    # epoch-millisecond integers, the OHLCV verbatim, the trade count as an
    # integer — so the one builder serves both and the envelope a reader rebuilds
    # from hashes to exactly the ``source_sha256`` the writer recorded.
    return _row_to_envelope(row)


def _require_aware(moment: object, what: str) -> None:
    # A candle's open and close instants and a flush's write time are all
    # placed by arithmetic on instants, so a naive timestamp would be
    # unsubtractable from an aware one at exactly the boundary each rule turns
    # on.  Refused here, where a caller can still fix its clock handling, rather
    # than silently assumed to be UTC and recorded wrong.
    if not isinstance(moment, datetime):
        raise TypeError(f"{what} must be a datetime, not {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{what} must be timezone-aware; a naive timestamp cannot place a "
            f"candle on the series or date a flush's write"
        )


def _isoformat_utc(moment: datetime) -> str:
    # Persisted in UTC with an explicit offset, so the record says when a candle
    # opened — or when the flush was written — without the reader assuming.
    return moment.astimezone(_UTC).isoformat()


def _parse_timestamp(raw: object, sequence: int) -> datetime:
    if not isinstance(raw, str):
        raise KlineCorruptError(
            f"kline record {sequence} records a timestamp {raw!r}; expected "
            f"an ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise KlineCorruptError(
            f"kline record {sequence} records an unparseable timestamp "
            f"{raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise KlineCorruptError(
            f"kline record {sequence} records a naive timestamp {raw!r}; the "
            f"series needs a comparable instant"
        )
    return parsed.astimezone(_UTC)


class KlineWorker:
    """The klines worker: flush each cycle's candles into the log.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the ``klines``
    stream class, so the supervisor of feature 16 runs it on its own thread
    alongside every other stream and converts whatever it raises into that
    stream's own failure.  One cycle is:

    * **Flush.**  Call the injected :data:`KlineFetch`.  The websocket client,
      its auth, its rate limits and its reconnect policy are the deployment's
      business; this worker owns only the persistence.  A fetch returning
      ``None`` is a *quiet* cycle — the feed delivered no new candles this
      slice — reported as zero rows, not a failure: a candle closes on its
      interval boundary, and a quiet cycle between boundaries is legitimate.
    * **Record.**  Parse first, then record the batch.  A failed flush — a
      truncated frame, an error page, an empty response — raises
      :class:`KlineParseError` *before* anything is written, so the log never
      records a flush that did not happen.

    Unlike the book-diff worker there is no retention pass: this stream's §4.1
    row is *forever*, so nothing is ever retired, and the permanent series is
    the append-only area's own property rather than anything this worker
    enforces.  The clock is injected because ``written_at`` is a fact about
    elapsed wall-clock time: a test must be able to place the worker's writes
    without touching the wall clock, and §12 keeps wall-clock reads out of
    checked code in any case.  The default clock reads the system UTC time,
    which is what a deployment wants.
    """

    def __init__(
        self,
        store: KlineStore,
        fetch: KlineFetch,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, KlineStore):
            raise TypeError(
                f"the kline worker persists into a KlineStore, "
                f"got {type(store).__name__}"
            )
        if not callable(fetch):
            raise TypeError(
                f"fetch must be a zero-argument callable returning the venue's "
                f"kline response, got {type(fetch).__name__}"
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
        """The one stream class this worker owns — ``klines``."""
        return KLINES_STREAM

    @property
    def store(self) -> KlineStore:
        """The record log this worker appends to."""
        return self._store

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Run one cycle: flush the candles and persist them.

        Returns the persisted record's sequence as the cycle's watermark, so a
        monitor sees the log advance, and ``rows_written`` as the number of
        candles the record carries.  A quiet cycle — a fetch that returned
        ``None`` — reports both as zero: no flush, no record, no progress to
        claim.
        """
        now = self._clock()
        _require_aware(now, "the clock")
        document = self._fetch()
        if document is None:
            return CycleResult(rows_written=0, sequence=0)
        record = self._store.record(
            document, self._interval, written_at=now
        )
        return CycleResult(
            rows_written=record.row_count, sequence=record.sequence
        )

    @property
    def _interval(self) -> KlineInterval:
        # The tail worker owns one interval — the websocket ``@kline_<interval>`
        # subscription it is wired to.  Kept as a property rather than a
        # constructor field so the worker stays a thin tail over the store; the
        # interval is the deployment's subscription, not the store's concern.
        return "1m"


def _utc_now() -> datetime:
    """The default clock: the current UTC time, timezone-aware."""
    return datetime.now(_UTC)


def register_kline_worker(
    fetch: KlineFetch,
    store: Optional[KlineStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], KlineWorker]:
    """Register a worker factory bound to an explicitly wired fetch.

    The operator path: hand in the websocket client's fetch (and, when it is not
    the lake's staging area, the store), and this registers a worker factory
    bound to those collaborators.  Registration replaces the auto-discovered
    factory of the same class in the registry it targets — the registry's own
    rule, *a re-registered class is a revision of the same worker, never a
    second worker* — so a deployment that wires a client does not end up with
    two kline workers competing for the same sequence numbers.

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
            f"kline response, got {type(fetch).__name__}"
        )

    def build() -> KlineWorker:
        resolved_store = store if store is not None else KlineStore.from_env()
        return KlineWorker(resolved_store, fetch, clock=clock)

    # Register through a private registry by default, never the process-wide
    # one.  Registration is a *deployment* act: writing a caller's wiring into
    # the default registry would replace the auto-discovered worker for every
    # later composition in the process — including tests, which would then be
    # handed a worker bound to a store that has since been deleted.  A caller
    # that genuinely means to reconfigure the running process passes the default
    # registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        KLINES_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(KLINES_STREAM)
def build_kline_worker() -> KlineWorker:
    """Compose the klines worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    Collaborators come from the environment the way every other ingest seam
    does: the store is the lake's staging area (:meth:`KlineStore.from_env`),
    so records land in the very area the seal copies out of.  The fetch has no
    environment-resolved default — this member ships no websocket client, so
    the venue's auth, rate limits and reconnect policy stay the deployment's
    business — and a deployment wires it with
    :func:`register_kline_worker`.  Until then the worker still composes and its
    cycle reports that stream's own failure, which is feature 16's contract: an
    unconfigured stream is a row in the report, not a component that fails to
    load.
    """
    return KlineWorker(KlineStore.from_env(), _unconfigured_fetch)


def _unconfigured_fetch() -> object:
    """The fetch used when a deployment has not wired a websocket client yet.

    Raising here, rather than at composition time, keeps the plugin shaped the
    way feature 16 wants it: an unconfigured stream is that stream's failure in
    the report, not a component that fails to compose.
    """
    raise KlineError(
        "no kline fetch is configured; register the worker with a fetch "
        "returning the venue's kline response "
        "(nullius_ingest.register_kline_worker(fetch, store=..., "
        "registry=default_worker_registry()))"
    )


class KlineBackfiller:
    """Page historical 1m/1h/1d klines for a symbol into the log, over REST.

    The REST half of feature 17's dual source: given a symbol, an interval and
    an inclusive range of candle open times (epoch milliseconds), it pages the
    venue's kline history and appends each page into the stream's staging log.
    The fetch and the interval are injected (:data:`KlineBackfillFetch`, a
    :data:`KlineInterval`); the staging area is handed in; the backfiller owns
    only the *orchestration* the feature names: which range is open, how to page
    it, and when a page counts as covering it.

    A backfiller is one-stream-per-call in its fill loop (the supervisor's
    one-thread-per-worker), but its shared staging area is safe under
    concurrency: the staging area guards its own appends.  Pages are appended in
    ascending open-time order, so a symbol's backfill batches land in the order
    the candles opened — the honest order, and the one a seal copies them in.

    Each page is verified against the range it was asked for — :meth:`page`
    checks the candles covered the range and raises :class:`KlineBackfillError`
    otherwise — so a seal is not told a range is filled when a short page left a
    hole in it.
    """

    def __init__(
        self,
        staging: StagingArea,
        fetch: KlineBackfillFetch,
        interval: KlineInterval,
    ) -> None:
        if not callable(fetch):
            raise TypeError(
                f"fetch must be a callable receiving (symbol, interval, first, "
                f"last), got {type(fetch).__name__}"
            )
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"backfiller writes to a StagingArea, got {type(staging).__name__}"
            )
        _interval_field(interval, "interval")
        self._staging = staging
        self._fetch = fetch
        self._interval = interval

    # -- The fill -------------------------------------------------------------

    def page(
        self,
        symbol: str,
        first_open: int,
        last_open: int,
    ) -> KlineRecord:
        """Fill one inclusive range of candle open times; return the record.

        The fetch is asked for exactly the range's first and last open times
        (epoch milliseconds, inclusive); the candles it returns must span that
        range, or the range stays open and :class:`KlineBackfillError` is raised
        before any batch is appended — so the append only ever lands candles
        that provably filled the range.  The covered range reported is the span
        the page actually returned, so the error can state precisely what is
        still missing.  The batch claims ``current + 1`` in the stream's staging
        log (feature 28's append-only area), exactly as a live-feed cycle would.
        """
        if not isinstance(symbol, str) or not symbol:
            raise TypeError("symbol must be a non-empty string")
        if first_open > last_open:
            raise ValueError(
                f"backfill range is reversed: first_open {first_open} is after "
                f"last_open {last_open}"
            )

        candles = parse_klines(
            self._fetch(symbol, self._interval, first_open, last_open),
            self._interval,
            symbol=symbol,
        ).candles
        # The fetch was asked for exactly the range's open times and must return
        # candles spanning it: a short page (fewer candles than the range,
        # including an empty one) or an out-of-range one leaves the range still
        # open, so a reader is not told the range is filled.  The covered span
        # reported is the open times the page actually returned.
        covered_first = min(candle.open_millis for candle in candles)
        covered_last = max(candle.open_millis for candle in candles)
        if covered_first != first_open or covered_last != last_open:
            raise KlineBackfillError(
                symbol,
                self._interval,
                first_open,
                last_open,
                covered_first,
                covered_last,
            )

        # Compute the sequence before building the payload, exactly as the
        # store's :meth:`KlineStore.record` does: the envelope records the
        # sequence the file is committed under, and the read path verifies the
        # two agree.  A page that hard-coded a placeholder sequence would read
        # back as corrupt, so the sequence is decided here, written into the
        # bytes, and then appended under that same number.
        sequence = self._staging.current(KLINES_STREAM) + 1
        batch = self._staging.append(
            KLINES_STREAM,
            payload=_batch_to_payload(
                KlineBatch(interval=self._interval, candles=candles), sequence
            ),
            rows=len(candles),
        )
        return KlineRecord(
            sequence=batch.sequence,
            written_at=_utc_now(),
            batch=KlineBatch(interval=self._interval, candles=candles),
            source_sha256=KlineBatch(
                interval=self._interval, candles=candles
            ).source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=batch.path,
        )


def _batch_to_payload(batch: KlineBatch, sequence: int) -> bytes:
    # The bytes a backfill page appends: the plain JSON envelope, exactly as the
    # store's :meth:`KlineStore.record` writes it, so a backfilled page and a
    # live flush are byte-identical records in the same append-only log — the
    # dual source shares one wire format, and the seal copies both the same way.
    # The sequence is the one the file is committed under, decided by the caller
    # before these bytes are built, so the envelope and the filename agree.
    envelope = {
        "stream": str(KLINES_STREAM),
        "sequence": sequence,
        "written_at": _isoformat_utc(_utc_now()),
        "source_sha256": batch.source_sha256,
        "first_open": _isoformat_utc(batch.first_open),
        "last_open": _isoformat_utc(batch.last_open),
        "interval": batch.interval,
        _DOCUMENT_KEY: [_row_to_envelope(candle) for candle in batch.candles],
    }
    return json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
