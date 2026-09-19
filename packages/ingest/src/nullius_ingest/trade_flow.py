"""Cancel-replace rate and trade-size distribution moments, persisted permanently.

app_spec.xml feature 22 states the behaviour: *"System computes cancel-replace
rate plus trade-size distribution moments, persisting them so a 90 day
raw-diff expiry does not lose the derived history."*  docs/nullius-tech-
architecture.md §4.1 lists both among the derived book features the L2
retention decision exists to make permanent, and then states the trade that
makes this tier load-bearing:

    **The L2 retention decision is load-bearing.**  Raw diff streams for a
    100-symbol universe run roughly 50–200 GB/month uncompressed.  Storing them
    forever is a self-inflicted infrastructure problem.  Instead: keep raw diffs
    for a rolling 90 days so feature definitions can be revised and backfilled
    recently, and permanently persist derived book features at 1s resolution
    (depth at 5/10/25/50 bps each side, microprice, spread, OFI over several
    windows, **cancel/replace rate, trade-size distribution moments**).

docs/alpha-engine-prd.md names the same pair as the reason this tier is worth
computing at all: *"OFI, queue dynamics, trade-size distribution, cancel/replace
rates, iceberg detection. Information advantage manufactured by compute."*  The
data is public; the *features* are not.

This module is feature 22's half of that derived tier, beside feature 20's
depth ladder (:mod:`nullius_ingest.book_features`) and feature 21's
microprice/spread/OFI.  It reads the same raw-diff log feature 19 persists —
through feature 20's reconstruction, via the
:meth:`~nullius_ingest.book_features.BookState.has_price` seam — and turns it
into a permanent 1s trade-flow log.

Four things make this different from every stream module before it:

* **A cancel-replace is a removal plus an add on one side within one diff.**
  This is the classification the whole feature rests on, so it is stated once
  and used everywhere.  Each level a raw diff carries is classified against the
  reconstructed book *before* the level is folded in: a removal (a ``"0"``
  quantity) is a ``REMOVE``; a positive quantity for a price already standing
  is an ``UPDATE``; a positive quantity for a price that is not is an ``ADD``.
  A side that both lost a price and gained one inside the same diff is a
  cancel-replace — the order left the book and re-entered elsewhere — and the
  rate is ``cancel_replace_events / level_events`` for that (symbol, second).

  The alternative reading — counting every removal and every size reduction —
  was rejected: it conflates a genuine order modification with ordinary
  liquidity withdrawal, which is the distinction the feature exists to measure.

* **Trade sizes arrive through an injected tape seam, because the L2 diffs do
  not carry them.**  A book diff says the book changed; it never says which
  change was a trade.  Feature 18 (the ``aggTrades`` stream) owns the venue's
  trade tape but has not landed, and guessing its wire format here would
  collide with the module that owns it.  So this module defines
  :data:`TradeTape` — a zero-argument callable returning the venue's trade
  prints — exactly as :data:`~nullius_ingest.book_diffs.BookDiffFetch` and
  :data:`~nullius_ingest.funding.FundingFetch` already do, and ships no client:
  the venue's auth, rate limits and pagination stay the deployment's business.
  A deployment that has feature 18's store hands over its rows; until then the
  auto-discovered worker's tape raises, and an unconfigured stream is that
  stream's own row in the supervisor's report rather than a component that
  fails to load (feature 16's contract).

* **The reconstructed book and the frontier are persisted with each record.**
  This is the same permanence argument feature 20 makes, and it is why the
  derived store — not the 90-day raw store — is the permanent home of the
  history.  Each record carries its closing :class:`~nullius_ingest.book_
  features.BookState` per symbol and its ``to_window`` / ``to_raw_sequence``
  frontier, so the next cycle — or a restart after the raw window has slid —
  resumes without re-deriving from diffs that may since have been pruned away.
  A test asserts exactly that: prune the raw diffs, and the derived row is
  still readable from this log.

* **An absence is not a zero.**  A second with no trade prints has no
  size *distribution*: its moments are ``None`` rather than ``0``, because a
  mean of zero would be a claim about a trade that never happened.  A second
  with no level events has no cancel-replace *rate* either — ``None``, not
  ``0``, because "no order activity" and "activity with no cancels" are
  different facts about the book.  Counts and volumes, by contrast, are real
  zeros: zero trades genuinely is zero trades.  Feature 20 draws the same line
  when it emits no row for a one-sided book.

Layering on feature 19 and feature 20 is deliberate and total: this module
reconstructs through feature 20's :class:`~nullius_ingest.book_features.
BookState` (it does not re-implement the book), reads the raw records feature
19 persisted through feature 19's store, and persists into the same append-only
staging area as every other stream — ``<lake>/staging/tradeFlow/`` — so the
seal copies it the same way and, like the funding and exchangeInfo logs,
nothing in the system ever expires it.

The member stays stdlib-only: the moment arithmetic is exact
:class:`~decimal.Decimal` over the venue's own quantity spellings, and the
worker's inputs are the *internal* raw-diff store and an injected tape, so
there is no unconfigured-fetch path beyond the tape itself.  The clock is
injected for the same reason every other worker injects theirs: ``computed_at``
is a fact about elapsed wall-clock time and §12 keeps wall-clock reads out of
checked code.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Optional, Union

from .book_diffs import BookDiffRow, BookDiffStore
from .book_features import BookState, FEATURE_SLICE, FEATURE_SLICE_MILLISECONDS
from .registry import WorkerRegistry, register_worker
from .staging import StagingArea
from .streams import StreamClass
from .worker import CycleResult

__all__ = [
    "CANCEL_REPLACE",
    "LevelAction",
    "TRADE_FLOW_STREAM",
    "TradeFlowBatch",
    "TradeFlowCorruptError",
    "TradeFlowError",
    "TradeFlowParseError",
    "TradeFlowRecord",
    "TradeFlowRow",
    "TradeFlowStore",
    "TradeFlowWorker",
    "TradePrint",
    "TradeTape",
    "build_trade_flow_worker",
    "cancel_replace_events",
    "classify_levels",
    "parse_trade_prints",
    "register_trade_flow_worker",
    "size_moments",
]

#: The stream class this module serves — feature 22's derived stream.  §4.1
#: gives the derived tier one row ("Book features (derived) | computed from
#: diffs | 1s | forever") and feature 20 already owns the ``bookFeatures``
#: spelling of it, so this family takes its own value rather than sharing one:
#: the supervisor's contract is one worker per stream class, and two derived
#: families under one class would mean the second registration *replacing* the
#: first rather than joining it.
TRADE_FLOW_STREAM = StreamClass.TRADE_FLOW

#: The resolution these features are computed at, carried over from feature 20
#: rather than re-declared: the two derived families are snapshotted at the same
#: 1s boundary off the same reconstruction, so a second means the same instant
#: in both logs.  Aliased so the fact is named where it is used and cannot
#: drift from the tier it belongs to.
TRADE_FLOW_SLICE: Final[timedelta] = FEATURE_SLICE
TRADE_FLOW_SLICE_MILLISECONDS: Final[int] = FEATURE_SLICE_MILLISECONDS

#: The class name of the removal action, kept as a plain string so it persists
#: and compares without importing an enum.
REMOVE: Final[str] = "remove"

#: The two actions a non-removal level can take, as persisted spellings.
ADD: Final[str] = "add"
UPDATE: Final[str] = "update"

#: The action a level takes when it is a genuine cancel-replace *event*: the
#: per-side marker the rate is counted from.  A side that both removed and added
#: inside one diff produces one of these — see :func:`classify_levels`.
CANCEL_REPLACE: Final[str] = "cancel_replace"

#: The epoch, as the exact-integer lattice the 1s grid is floored against — the
#: same arithmetic feature 20 uses, repeated here rather than imported because
#: its helper is private to that module.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SLICE_MICROS: Final[int] = TRADE_FLOW_SLICE_MILLISECONDS * 1000

#: The envelope keys a record file carries around its rows.  ``rows`` is the
#: document; ``closing_books`` is the resume seed, carried for the same reason
#: feature 20 carries it — the derived log must outlive the raw diffs it was
#: derived from.
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

#: The closing book is carried as a full
#: :class:`~nullius_ingest.book_features.BookState` snapshot rather than as the
#: depth ladder feature 20 emits, so a restart resumes from the book itself and
#: needs no threshold to reconstruct it.
_ZERO: Final[Decimal] = Decimal(0)
_ONE: Final[Decimal] = Decimal(1)
_THREE: Final[Decimal] = Decimal(3)


class TradeFlowError(Exception):
    """Base for every failure this module raises.

    Raised for a batch this module will not persist and for a persisted record
    it will not read: both are cases where the derived trade-flow log would
    otherwise start lying about what the book and the tape did, so both fail
    loudly rather than being approximated into a row.
    """


class TradeFlowParseError(TradeFlowError):
    """A batch, a row or a trade print is not one this module will accept.

    Raised *before* anything is written, so a malformed row never consumes a
    sequence number and never appears in the log as a snapshot that happened.
    The message names what was wrong with which row, because the caller is a
    worker deciding whether the reduction it produced is sound.
    """


class TradeFlowCorruptError(TradeFlowError):
    """A persisted record file does not match what was written under it.

    Raised when a record file cannot be read back as the envelope it was written
    as, when its recorded sequence is not the sequence its filename claims, or
    when recomputing its document hash disagrees with the hash the envelope
    recorded.  A mismatch means the bytes on disk are not the bytes this module
    committed — corruption or tampering — and a reader that rebuilt a feature
    from them would be rebuilding a market that never existed.  The closing book
    a record carries makes this matter twice over: a damaged closing book would
    seed a restarted worker's reconstruction from a book the market never had.
    """


def _floor_to_second(moment: datetime) -> datetime:
    # Floor an aware instant onto the exact 1s lattice: epoch microseconds
    # integer-divided by the slice width, so ``...1200ms`` stays put and
    # ``...1999ms`` floors to ``...1000ms`` — on every platform, because the
    # arithmetic is over whole microseconds and no float is involved.  This is
    # the same lattice feature 20 snapshots on; the two derived logs place a
    # second at the same instant, which is what lets a reader join them.
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
    # A computed value is rendered in fixed-point, with no exponent notation, so
    # a rate of ``0.5`` and a size of ``100.50`` are stable across Python
    # versions and JSON round-trips.  Trailing zeros are preserved, so two rows
    # that agree on a number agree on its string — the same convention feature
    # 20 persists its depths under.
    return format(value, "f")


class LevelAction:
    """One raw level's place in its diff, and the side it belongs to.

    What :func:`classify_levels` returns per level: the ``side`` (the venue's
    ``"bids"`` / ``"asks"`` spelling), the ``price`` as the venue spelled it,
    and the ``action`` — one of :data:`ADD`, :data:`UPDATE`, :data:`REMOVE`.

    A tiny value type rather than three parallel tuples so a caller walking a
    classification reads the action off the level it belongs to, and so a
    cancel-replace count can be asserted against the exact levels that produced
    it rather than against a number.
    """

    __slots__ = ("side", "price", "action")

    def __init__(self, side: str, price: str, action: str) -> None:
        if action not in (ADD, UPDATE, REMOVE):
            raise TradeFlowParseError(
                f"a level action is one of {ADD!r}, {UPDATE!r} or {REMOVE!r}, "
                f"got {action!r}"
            )
        self.side = side
        self.price = price
        self.action = action

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"LevelAction(side={self.side!r}, price={self.price!r}, action={self.action!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LevelAction):
            return NotImplemented
        return (
            self.side == other.side
            and self.price == other.price
            and self.action == other.action
        )

    def __hash__(self) -> int:
        return hash((self.side, self.price, self.action))


def classify_levels(
    row: BookDiffRow, book: BookState
) -> tuple[LevelAction, ...]:
    """Classify one raw diff's levels against the book *before* it is folded in.

    The classification feature 22's cancel-replace count is built from, so the
    ordering is the whole of it: each level is asked about the book as it stood
    *before* this diff, which is what makes "was this price already standing?" a
    question with an answer.  A caller must therefore classify and only then
    :meth:`~nullius_ingest.book_features.BookState.apply` — the reverse order
    would classify every add as an update.

    A removal is a level the venue spelled with a zero quantity.  Everything
    else is an add when its price is not currently on that side and an update
    when it is.
    """
    actions: list[LevelAction] = []
    for level in row.levels:
        side = str(level.side)
        if level.is_removal:
            actions.append(LevelAction(side, level.price, REMOVE))
        elif book.has_price(side, level.price):
            actions.append(LevelAction(side, level.price, UPDATE))
        else:
            actions.append(LevelAction(side, level.price, ADD))
    return tuple(actions)


def cancel_replace_events(actions: Sequence[LevelAction]) -> int:
    """How many cancel-replace events ``actions`` describe, per side.

    A cancel-replace is a side that both *lost* a price and *gained* one inside
    one diff: the order left the book and re-entered somewhere else.  Counted
    per side as the smaller of the two counts — one removal matched against one
    add — so a diff that removes two levels and adds one is one cancel-replace
    and a genuine net withdrawal, not two events.  A removal on the bid side and
    an add on the ask side is emphatically *not* a cancel-replace: it is
    liquidity changing direction, and the two sides never pair up.
    """
    per_side: dict[str, list[int]] = {}
    for level in actions:
        bucket = per_side.setdefault(level.side, [0, 0])
        if level.action == REMOVE:
            bucket[0] += 1
        elif level.action == ADD:
            bucket[1] += 1
    return sum(min(removals, adds) for removals, adds in per_side.values())


@dataclass(frozen=True)
class TradePrint:
    """One trade off the venue's tape: a price, a size, and when it happened.

    Three facts, each load-bearing:

    * ``price`` / ``quantity`` — kept as the venue's own string spelling, the
      same rule the raw tier follows and for the same reason: whether the venue
      said ``"0.001"`` or ``"0.0010"`` is a fact about the venue.  The *moment*
      computed downstream is a :class:`~decimal.Decimal`; only the source
      spelling is verbatim.
    * ``window_start`` — the 1s window the trade's event time fell in, floored
      onto the exact lattice.  This is the resolution the moments are computed
      at, and it is the *venue's* time that decides it, never ours: our own
      ingest lag must not decide which second a trade belongs to.
    * ``is_buyer_maker`` — the aggressor's side, as the venue reports it (a
      maker buyer means the *seller* aggressed).  Carried because it is the one
      trade fact a consumer cannot re-derive, and dropping it at the parse would
      destroy it for every later feature that wants signed flow.
    """

    symbol: str
    window_start: datetime
    price: str
    quantity: str
    is_buyer_maker: bool

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise TradeFlowParseError(
                f"a trade print must carry a non-empty symbol, got {self.symbol!r}"
            )
        if not isinstance(self.window_start, datetime):
            raise TradeFlowParseError(
                f"a trade print's window_start must be a datetime, got "
                f"{type(self.window_start).__name__}"
            )
        if self.window_start.tzinfo is None or self.window_start.tzinfo.utcoffset(
            self.window_start
        ) is None:
            raise TradeFlowParseError(
                f"a trade print's window_start must be timezone-aware; the 1s "
                f"grid needs an offset to floor against"
            )
        object.__setattr__(self, "window_start", _floor_to_second(self.window_start))
        for name, value in (("price", self.price), ("quantity", self.quantity)):
            if not isinstance(value, str) or not value:
                raise TradeFlowParseError(
                    f"a trade print's {name} must be a non-empty string in the "
                    f"venue's spelling, got {value!r}"
                )
            try:
                parsed = Decimal(value)
            except (InvalidOperation, ValueError) as exc:
                raise TradeFlowParseError(
                    f"a trade print's {name} is {value!r}, which is not a "
                    f"decimal: {exc}"
                ) from exc
            if not parsed.is_finite():
                raise TradeFlowParseError(
                    f"a trade print's {name} is {value!r}, which is not a "
                    f"finite number"
                )
        if self.size <= 0:
            # A print with no size is not a trade: the venue printed nothing, so
            # counting it would inflate ``trade_count`` and drag the size mean
            # toward zero on evidence that does not exist.  Refused here rather
            # than at the row, so the invariant holds for every print this module
            # ever measures.
            raise TradeFlowParseError(
                f"a trade print's quantity is {self.quantity!r}; a trade of no "
                f"size is not a trade this module will measure"
            )
        if not isinstance(self.is_buyer_maker, bool):
            raise TradeFlowParseError(
                f"a trade print's is_buyer_maker must be a bool, got "
                f"{type(self.is_buyer_maker).__name__}"
            )

    @property
    def size(self) -> Decimal:
        """This trade's size as an exact :class:`~decimal.Decimal`."""
        return Decimal(self.quantity)

    def canonical(self) -> dict[str, object]:
        """This trade's canonical mapping — the form the content hash is over."""
        return {
            "symbol": self.symbol,
            "window_start": self.window_start.isoformat(),
            "price": self.price,
            "quantity": self.quantity,
            "is_buyer_maker": self.is_buyer_maker,
        }


def parse_trade_prints(document: object) -> tuple[TradePrint, ...]:
    """Parse a venue trade-tape response into :class:`TradePrint` rows.

    Accepts the venue's response as decoded JSON — a single print, a list of
    prints, a wrapper some endpoints use (``{"trades": [...]}`` or
    ``{"data": [...]}``), a JSON bytes or string body, or an already-built
    sequence of :class:`TradePrint` — and refuses anything else with
    :class:`TradeFlowParseError`.

    Strict about the shape this system owns: a print must name its symbol and
    carry a price, a size and an event time (without which it cannot be placed
    on the 1s grid).  Tolerant where the venue is free: the trade's id, the
    commission, the order id and any other field are ignored, and either naming
    convention for the aggressor flag is accepted.

    A print with **no** event time is refused rather than stamped with our own
    clock: using ours would invent a fact about when the venue saw the trade,
    and the moments would then be computed over a second the trade never landed
    in — the failure mode feature 20's grid discipline exists to prevent.
    """
    if isinstance(document, (bytes, bytearray, str)):
        try:
            decoded = json.loads(document)
        except ValueError as exc:
            raise TradeFlowParseError(
                f"trade-tape payload is not valid JSON: {exc}"
            ) from exc
    else:
        decoded = document

    if isinstance(decoded, Mapping):
        for key in ("trades", "data", "result"):
            if key in decoded:
                decoded = decoded[key]
                break
        else:
            decoded = [decoded]

    if isinstance(decoded, TradePrint):
        return (decoded,)
    if not isinstance(decoded, Sequence) or isinstance(decoded, (str, bytes, bytearray)):
        raise TradeFlowParseError(
            f"a trade-tape payload is a list of prints, got "
            f"{type(decoded).__name__}"
        )

    prints: list[TradePrint] = []
    for index, entry in enumerate(decoded):
        if isinstance(entry, TradePrint):
            prints.append(entry)
            continue
        if not isinstance(entry, Mapping):
            raise TradeFlowParseError(
                f"trades[{index}] is {type(entry).__name__}; expected an object"
            )
        prints.append(_print_from_mapping(entry, index))
    return tuple(prints)


def _print_from_mapping(entry: Mapping, index: int) -> TradePrint:
    # Read one venue trade object.  Two spellings are accepted per field
    # (Binance's short keys and the long ones a normalising gateway uses),
    # matching the raw tier's tolerance about venue spelling; anything missing
    # or unusable is refused with the index that named it.
    def field(*names: str) -> object:
        for name in names:
            if name in entry:
                return entry[name]
        raise TradeFlowParseError(
            f"trades[{index}] carries none of {names}; a trade print needs a "
            f"symbol, a price, a size and an event time"
        )

    symbol = field("s", "symbol")
    price = field("p", "price")
    quantity = field("q", "quantity", "qty")
    # The trade's own time, preferred over the envelope's: ``T`` is when the trade
    # happened and ``E`` is when the venue emitted the message, and the 1s bucket
    # must be decided by the former.  ``E`` is the fallback for a gateway that
    # sends only one, and either is the *venue's* time — never ours.
    event_time = field("T", "trade_time", "tradeTime", "time", "timestamp", "ts", "E")
    aggressor = entry.get("m", entry.get("is_buyer_maker"))

    if not isinstance(symbol, str) or not symbol:
        raise TradeFlowParseError(
            f"trades[{index}] has symbol {symbol!r}; expected a non-empty string"
        )
    if not isinstance(event_time, int) or isinstance(event_time, bool):
        raise TradeFlowParseError(
            f"trades[{index}] has event time {event_time!r}; a trade cannot be "
            f"placed on the 1s grid without the venue's event time in epoch "
            f"milliseconds"
        )
    if aggressor is None:
        raise TradeFlowParseError(
            f"trades[{index}] carries no aggressor flag ('m' or "
            f"'is_buyer_maker'); the side that aggressed is a trade fact this "
            f"module persists rather than guesses"
        )
    if not isinstance(aggressor, bool):
        raise TradeFlowParseError(
            f"trades[{index}] has is_buyer_maker {aggressor!r}; expected a bool"
        )
    return TradePrint(
        symbol=symbol,
        window_start=_EPOCH + timedelta(milliseconds=event_time),
        price=str(price),
        quantity=str(quantity),
        is_buyer_maker=aggressor,
    )


#: A tape: return the venue's trade prints, as JSON bytes, a JSON string, a
#: decoded mapping/list, or an already-parsed sequence of prints.
#:
#: The seam feature 18's ``aggTrades`` stream owns and this feature consumes.
#: This member ships no websocket client — like the funding and exchangeInfo
#: workers, which are handed their REST fetch rather than owning one — so the
#: venue's auth, rate limits and pagination stay the stream worker's business
#: and the module stays testable without a network.  A deployment that has
#: feature 18's store hands over its rows through this seam; until then the
#: auto-discovered worker's tape raises, which is feature 16's contract.
TradeTape = Callable[[], Union[bytes, str, Sequence, Mapping, TradePrint]]


@dataclass(frozen=True)
class TradeFlowRow:
    """One symbol's trade-flow features for one 1 second window.

    The derived facts feature 22 names, plus the counts that make each one
    checkable rather than a number whose denominator is lost:

    * ``symbol`` / ``window_start`` — which market, and which second on the 1s
      lattice (:func:`_floor_to_second`).
    * ``cancel_replace_rate`` — :data:`CANCEL_REPLACE` events over level events
      for the second, or ``None`` when the second carried **no level events at
      all**.  An absent rate is not a zero rate: a second in which nothing
      changed is silent, not proven cancel-free.
    * ``level_events`` / ``cancel_replace_events`` — the rate's denominator and
      numerator, kept so a reader can recompute the rate and so a rate of
      exactly ``0`` (activity, no cancels) is distinguishable from ``None`` (no
      activity) without re-reading the raw diffs.
    * ``trade_count`` / ``trade_volume`` — how many prints landed in the second
      and the sum of their sizes.  These are real zeros when nothing traded:
      zero trades genuinely is zero trades.
    * ``mean_size`` / ``stddev_size`` / ``skew_size`` / ``kurtosis_size`` — the
      **population** moments of the second's trade sizes, or all ``None`` when
      the second carried fewer than two prints.  A single trade has no
      distribution to describe, and a mean over one print would be a
      distribution claim the data does not support; feature 20 draws the same
      line when it emits no row for a one-sided book.  ``kurtosis_size`` is the
      **excess** kurtosis (a normal distribution reads ``0``), which is the
      convention a reader expects from a skew/kurtosis pair.

    Every computed value is a :class:`~decimal.Decimal` in memory, so a
    consumer sums and compares them without re-parsing and a test asserts on the
    number rather than a spelling.  They are rendered as canonical strings only
    in :meth:`canonical` — the persisted form the content hash is taken over —
    so the persisted row is the feature value, not a float that could drift on a
    re-render.
    """

    symbol: str
    window_start: datetime
    cancel_replace_rate: Decimal | None
    level_events: int
    cancel_replace_events: int
    trade_count: int
    trade_volume: Decimal
    mean_size: Decimal | None
    stddev_size: Decimal | None
    skew_size: Decimal | None
    kurtosis_size: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise TradeFlowParseError(
                f"a trade-flow row must carry a non-empty symbol, got "
                f"{self.symbol!r}"
            )
        if not isinstance(self.window_start, datetime):
            raise TradeFlowParseError(
                f"a trade-flow row's window_start must be a datetime, got "
                f"{type(self.window_start).__name__}"
            )
        if self.window_start.tzinfo is None or self.window_start.tzinfo.utcoffset(
            self.window_start
        ) is None:
            raise TradeFlowParseError(
                f"a trade-flow row's window_start must be timezone-aware; the "
                f"1s grid needs an offset to floor against"
            )
        object.__setattr__(self, "window_start", _floor_to_second(self.window_start))
        for name, count in (
            ("level_events", self.level_events),
            ("cancel_replace_events", self.cancel_replace_events),
            ("trade_count", self.trade_count),
        ):
            if isinstance(count, bool) or not isinstance(count, int):
                raise TradeFlowParseError(
                    f"{self.symbol} {name} must be an integer, got "
                    f"{type(count).__name__}"
                )
            if count < 0:
                raise TradeFlowParseError(
                    f"{self.symbol} {name} is negative; a count of events is "
                    f"never below zero"
                )
        if self.cancel_replace_events > self.level_events:
            # The rate's numerator cannot exceed its denominator: more
            # cancel-replaces than level events would describe a book that
            # cancelled orders it never received, and a reader recomputing a
            # rate above 1 would rightly distrust the whole row.
            raise TradeFlowParseError(
                f"{self.symbol} records {self.cancel_replace_events} "
                f"cancel-replace events over only {self.level_events} level "
                f"events; the numerator cannot exceed the denominator"
            )
        if not isinstance(self.trade_volume, Decimal):
            raise TradeFlowParseError(
                f"{self.symbol} trade_volume must be a Decimal, got "
                f"{type(self.trade_volume).__name__}"
            )
        if not self.trade_volume.is_finite():
            raise TradeFlowParseError(
                f"{self.symbol} trade_volume is {self.trade_volume!r}; a "
                f"non-finite volume is not a measurement of the market"
            )
        if self.trade_volume < 0:
            raise TradeFlowParseError(
                f"{self.symbol} trade_volume is negative; a summed size is "
                f"never below zero"
            )
        if (self.trade_count == 0) != (self.trade_volume == 0):
            # A second that reports sizes summing to zero without a print, or
            # prints summing to zero, is internally inconsistent: the moments
            # and the volume would disagree about whether the market traded.
            raise TradeFlowParseError(
                f"{self.symbol} records trade_count={self.trade_count} with "
                f"trade_volume={_canonical_decimal(self.trade_volume)}; a second "
                f"either carried prints or it did not"
            )
        for name, value in (
            ("cancel_replace_rate", self.cancel_replace_rate),
            ("mean_size", self.mean_size),
            ("stddev_size", self.stddev_size),
            ("skew_size", self.skew_size),
            ("kurtosis_size", self.kurtosis_size),
        ):
            if value is not None and not isinstance(value, Decimal):
                raise TradeFlowParseError(
                    f"{self.symbol} {name} must be a Decimal or None, got "
                    f"{type(value).__name__}"
                )
        if self.level_events == 0 and self.cancel_replace_rate is not None:
            raise TradeFlowParseError(
                f"{self.symbol} carries a cancel-replace rate over zero level "
                f"events; a rate with no denominator is not a rate"
            )
        if self.level_events > 0 and self.cancel_replace_rate is None:
            raise TradeFlowParseError(
                f"{self.symbol} carries {self.level_events} level events and no "
                f"cancel-replace rate; a second with activity has a rate"
            )
        # The four moments stand or fall together: they describe one
        # distribution, so a row carrying a mean but no dispersion (or the
        # reverse) is a partially-filled distribution claim.
        moments = (
            self.mean_size,
            self.stddev_size,
            self.skew_size,
            self.kurtosis_size,
        )
        present = [value is not None for value in moments]
        if any(present) and not all(present):
            raise TradeFlowParseError(
                f"{self.symbol} carries only some of the size moments "
                f"{[name for name, ok in zip(('mean', 'stddev', 'skew', 'kurtosis'), present) if ok]}; "
                f"the moments describe one distribution and are carried together"
            )
        if present[0] and self.trade_count < 2:
            raise TradeFlowParseError(
                f"{self.symbol} carries size moments over {self.trade_count} "
                f"trade(s); a distribution needs at least two observations"
            )

    def rate(self) -> Decimal | None:
        """This row's cancel-replace rate, recomputed from its own counts.

        Offered so a reader can check the stored rate rather than trust it: the
        counts are the evidence and the rate is their ratio, and recomputing
        must agree with what was persisted or the row is not self-consistent.
        ``None`` exactly when the second carried no level events.
        """
        if self.level_events == 0:
            return None
        return Decimal(self.cancel_replace_events) / Decimal(self.level_events)

    def canonical(self) -> dict[str, object]:
        """This row's canonical mapping — the form the content hash is over.

        Keys are sorted by the serialiser, the counts are plain integers and the
        computed values are canonical decimal strings, so two rows describing
        the same second agree on their hash and a row that changed one size does
        not.  ``None`` is persisted as JSON ``null`` rather than as a sentinel
        string, so an absent rate and an absent moment are unmistakable for the
        value zero.
        """
        return {
            "symbol": self.symbol,
            "window_start": self.window_start.isoformat(),
            "cancel_replace_rate": (
                None
                if self.cancel_replace_rate is None
                else _canonical_decimal(self.cancel_replace_rate)
            ),
            "level_events": self.level_events,
            "cancel_replace_events": self.cancel_replace_events,
            "trade_count": self.trade_count,
            "trade_volume": _canonical_decimal(self.trade_volume),
            "mean_size": (
                None if self.mean_size is None else _canonical_decimal(self.mean_size)
            ),
            "stddev_size": (
                None
                if self.stddev_size is None
                else _canonical_decimal(self.stddev_size)
            ),
            "skew_size": (
                None if self.skew_size is None else _canonical_decimal(self.skew_size)
            ),
            "kurtosis_size": (
                None
                if self.kurtosis_size is None
                else _canonical_decimal(self.kurtosis_size)
            ),
        }


def size_moments(sizes: Sequence[Decimal]) -> tuple[
    Decimal | None, Decimal | None, Decimal | None, Decimal | None
]:
    """The population size moments of ``sizes``: mean, sd, skew, excess kurtosis.

    Population moments, not sample moments: the second's prints are the whole
    population of trades that landed in that second, not a sample drawn from
    one, so dividing by ``n`` rather than ``n - 1`` is the honest reading.
    Returns four ``None``s for fewer than two observations — a distribution
    needs at least two points — which is the caller's signal to persist an
    absence rather than a fabricated ``0``.

    Skewness is the standardized third central moment and kurtosis is the
    standardized fourth minus three, so a symmetric distribution reads ``0``
    skew and a normal one reads ``0`` excess kurtosis.  The arithmetic is exact
    :class:`~decimal.Decimal` throughout except for the square root in the
    dispersion, which :mod:`decimal` computes at the context's precision — one
    documented approximation, taken because a standard deviation that is a
    rational function of its inputs is not a standard deviation.
    """
    n = len(sizes)
    if n < 2:
        return (None, None, None, None)
    count = Decimal(n)
    total = sum(sizes, _ZERO)
    mean = total / count
    deviations = [size - mean for size in sizes]
    m2 = sum((d * d for d in deviations), _ZERO) / count
    if m2 == 0:
        # Every print in the second was the same size: the distribution has a
        # point mass, so it has a mean and no dispersion, and its higher
        # standardized moments are genuinely undefined (0/0) rather than zero.
        # Reported as three absences beside a real mean, which is the honest
        # description of a degenerate distribution.
        return (mean, _ZERO, None, None)
    sd = m2.sqrt()
    m3 = sum((d * d * d for d in deviations), _ZERO) / count
    m4 = sum((d * d * d * d for d in deviations), _ZERO) / count
    return (mean, sd, m3 / (sd**3), (m4 / (m2 * m2)) - _THREE)


@dataclass(frozen=True)
class TradeFlowBatch:
    """One cycle's derived output: the rows, the closing state, the frontier.

    A batch is what a worker cycle produces and persists.  It carries four
    things, each of which makes the reduction resumable:

    * ``rows`` — the derived 1s rows this cycle emitted, one per (symbol,
      second) that carried a diff or a trade.
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

    rows: Sequence[TradeFlowRow]
    closing_books: Mapping[str, BookState]
    from_window: datetime | None
    to_window: datetime | None
    from_raw_sequence: int
    to_raw_sequence: int

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        for row in rows:
            if not isinstance(row, TradeFlowRow):
                raise TradeFlowParseError(
                    "a trade-flow batch's rows must be TradeFlowRow instances, "
                    f"got {type(row).__name__}"
                )
        object.__setattr__(self, "rows", rows)
        closing = dict(self.closing_books)
        for symbol, state in closing.items():
            if not isinstance(state, BookState):
                raise TradeFlowParseError(
                    f"closing_books[{symbol!r}] must be a BookState, got "
                    f"{type(state).__name__}"
                )
        object.__setattr__(self, "closing_books", closing)
        if not rows and self.to_raw_sequence <= self.from_raw_sequence:
            # No new rows and no advance through the raw log: nothing changed,
            # so there is nothing to persist.  An empty cycle is not a record —
            # the honest no-progress state reports ``sequence=0`` and appends
            # nothing, exactly as a not-due funding cycle does.
            raise TradeFlowParseError(
                "a trade-flow batch must carry at least one row or advance the "
                "raw-log frontier; an empty batch is a no-progress cycle, not a "
                "snapshot"
            )
        if self.from_raw_sequence < 0 or self.to_raw_sequence < self.from_raw_sequence:
            raise TradeFlowParseError(
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

    def rows_for(self, symbol: str) -> tuple[TradeFlowRow, ...]:
        """This batch's rows for ``symbol``, in the batch's order."""
        return tuple(row for row in self.rows if row.symbol == symbol)

    def canonical_bytes(self) -> bytes:
        """The batch's canonical JSON bytes — the thing content-hashed.

        Canonical means rows in a deterministic order (window, then symbol),
        closing books in symbol order, keys sorted and the tightest separators —
        so two cycles producing the same features and closing book hash
        identically whatever order the symbols were folded in.  This is what
        makes :attr:`TradeFlowRecord.source_sha256` a *content* hash.
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


def _row_sort(row: TradeFlowRow) -> tuple[datetime, str]:
    return (row.window_start, row.symbol)


def parse_trade_flow(batch: object) -> TradeFlowBatch:
    """Validate an already-built :class:`TradeFlowBatch`.

    This module's rows are computed, not parsed from a venue payload, so the
    "parse" here is the gate a persisted record's rows pass back through on read:
    a :class:`TradeFlowBatch` is returned unchanged, and anything else is
    refused, so a damaged document never rebuilds into a feature.
    """
    if not isinstance(batch, TradeFlowBatch):
        raise TradeFlowParseError(
            f"a trade-flow batch must be a TradeFlowBatch, got "
            f"{type(batch).__name__}"
        )
    return batch


class TradeFlowStore:
    """The append-only log of derived 1s trade-flow features, under staging.

    Records live at ``<lake>/staging/tradeFlow/<sequence>.bin``, one file per
    cycle, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a record is written once,
    atomically (temp file, ``fsync``, ``rename``), and never rewritten: the
    underlying batch store refuses a second batch at a sequence it already
    holds.  This is §4.1's derived-feature tier, in the same append-only area as
    every other stream, so the seal copies it the same way and — like the
    funding and exchangeInfo logs — nothing in the system ever expires it.
    That permanence is the point: the raw diffs these rows are derived from are
    90-day-retained and then gone, so the derived log must outlive them, and it
    does because each record carries its own closing book rather than depending
    on the raw store.

    Construction reads whatever a prior run left on disk, so a restarted process
    knows the last closing book and the frontier it reached without a network
    call — the same seed-from-what-is-durable moment the resume watermark gives
    a restarted worker.  The store reads no clock: ``computed_at`` is a
    parameter, driven by the worker's injected clock (§12).
    """

    def __init__(self, staging: StagingArea) -> None:
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"the trade-flow store writes into a StagingArea, got "
                f"{type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "TradeFlowStore":
        """The store over the lake's staging area, resolved from the environment.

        The same resolution every ingest store uses (``LAKE_ROOT``, defaulting
        to ``lake/`` beside the workspace root), so records are written into the
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
        return self._staging.path_for(TRADE_FLOW_STREAM)

    def path_for(self, sequence: int) -> Path:
        """The file sequence ``sequence`` is committed to."""
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise TypeError(f"a sequence is an integer, not {type(sequence).__name__}")
        if sequence <= 0:
            raise ValueError(f"a sequence must be positive, got {sequence}")
        return self.root / f"{sequence}.bin"

    # -- Recording ------------------------------------------------------------

    def record(
        self, batch: TradeFlowBatch, *, computed_at: datetime
    ) -> "TradeFlowRecord":
        """Persist one cycle as the next record; never overwrite a prior one.

        The batch is validated *first*, so a malformed batch consumes no
        sequence number and leaves the log untouched; then it is written as the
        next record — ``current + 1`` — into the stream's append-only staging
        log.  The previous records are not read, moved or rewritten: adding a
        record is an append, and the store's duplicate-sequence refusal means
        this method has no code path that could overwrite one.

        ``computed_at`` is required and must be timezone-aware: it is the instant
        the cycle ran, stamped on the record, and a naive timestamp would make
        the record's own provenance unanswerable.  The store does not read a
        clock of its own — the worker that ran the cycle owns the time.
        """
        parsed = parse_trade_flow(batch)
        if not isinstance(computed_at, datetime) or computed_at.tzinfo is None or (
            computed_at.tzinfo.utcoffset(computed_at) is None
        ):
            raise ValueError(
                "computed_at must be a timezone-aware datetime; the record's "
                "provenance needs a comparable instant"
            )

        sequence = self._staging.current(TRADE_FLOW_STREAM) + 1
        envelope = {
            "stream": str(TRADE_FLOW_STREAM),
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
            TRADE_FLOW_STREAM, payload=payload, rows=len(parsed)
        )
        return TradeFlowRecord(
            sequence=batch_.sequence,
            computed_at=computed_at.astimezone(timezone.utc),
            batch=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            path=batch_.path,
        )

    # -- Reading --------------------------------------------------------------

    def records(self) -> tuple["TradeFlowRecord", ...]:
        """Every persisted record, oldest first.

        Read back from the staging log in ascending sequence order, each
        envelope verified against the sequence its filename claims and the
        document hash it recorded — so a reader gets either the record that was
        committed or a clear :class:`TradeFlowCorruptError`, never a
        plausible-looking feature assembled from damaged bytes.
        """
        return tuple(
            self._read(batch) for batch in self._staging.staged(TRADE_FLOW_STREAM)
        )

    def current(self) -> "TradeFlowRecord | None":
        """The most recent record, or ``None`` when nothing has been persisted."""
        batches = self._staging.staged(TRADE_FLOW_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def last_record(self) -> "TradeFlowRecord | None":
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

    def rows_for(self, symbol: str, window_start: datetime) -> tuple[TradeFlowRow, ...]:
        """Every retained trade-flow row for ``symbol`` at one 1s window.

        Unioned across all records and matched on the aligned window, so a
        caller may pass any instant inside the window it means — the same reader
        seam shape feature 20 offers for its depth rows.
        """
        wanted = _floor_to_second(window_start)
        found: list[TradeFlowRow] = []
        for record in self.records():
            found.extend(
                row
                for row in record.batch.rows
                if row.symbol == symbol and row.window_start == wanted
            )
        return tuple(found)

    def _read(self, batch) -> "TradeFlowRecord":
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
            raise TradeFlowCorruptError(
                f"trade-flow record {batch.sequence} is not readable as a JSON "
                f"envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise TradeFlowCorruptError(
                f"trade-flow record {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise TradeFlowCorruptError(
                f"trade-flow record {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"record envelope this store wrote"
            )
        recorded = envelope["sequence"]
        if recorded != batch.sequence:
            raise TradeFlowCorruptError(
                f"trade-flow record file {batch.sequence}.bin records sequence "
                f"{recorded!r}; the file does not describe itself"
            )
        document = _read_document(envelope[_DOCUMENT_KEY], batch.sequence)
        closing = _read_closing(envelope.get(_CLOSING_KEY, {}), batch.sequence)
        recorded_hash = envelope["source_sha256"]
        rebuilt = TradeFlowBatch(
            rows=document,
            closing_books=closing,
            from_window=_parse_optional_timestamp(envelope.get("from_window"), batch.sequence),
            to_window=_parse_optional_timestamp(envelope.get("to_window"), batch.sequence),
            from_raw_sequence=int(envelope["from_raw_sequence"]),
            to_raw_sequence=int(envelope["to_raw_sequence"]),
        )
        if recorded_hash != rebuilt.source_sha256:
            raise TradeFlowCorruptError(
                f"trade-flow record {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{rebuilt.source_sha256!r}; the file's bytes are not the bytes "
                f"that were committed"
            )
        return TradeFlowRecord(
            sequence=batch.sequence,
            computed_at=_parse_timestamp(envelope["computed_at"], batch.sequence),
            batch=rebuilt,
            source_sha256=rebuilt.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


@dataclass(frozen=True)
class TradeFlowRecord:
    """One persisted cycle: the sequence it landed under and the rows it carried.

    ``sequence`` is the record's position in the stream's append-only log and,
    because the log is feature 28's staging area, the sequence of the batch the
    envelope bytes were committed as.  ``computed_at`` is when *we* ran the cycle
    (UTC, timezone-aware), kept apart from the rows' ``window_start``, which is
    when the book and the tape were observed: conflating them would let our own
    ingest lag decide which second a feature belongs to.

    Two hashes, deliberately distinct, exactly as funding's and feature 20's
    records carry them: ``source_sha256`` is over the *document* and answers
    "did the features change?"; ``payload_sha256`` is over the *bytes written*
    and is the file's identity, the same value the seal's MANIFEST will record
    for it.  ``path`` names the ``<sequence>.bin`` the bytes were committed to.
    """

    sequence: int
    computed_at: datetime
    batch: TradeFlowBatch
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


def _read_document(entries: object, sequence: int) -> tuple[TradeFlowRow, ...]:
    # Read a persisted document back into rows, restoring ``None`` where the
    # envelope wrote JSON ``null``.  A document that is not a list of well-formed
    # rows is corruption, not data.
    if not isinstance(entries, list):
        raise TradeFlowCorruptError(
            f"trade-flow record {sequence} has a document that is not a list of "
            f"rows"
        )
    rows: list[TradeFlowRow] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise TradeFlowCorruptError(
                f"trade-flow record {sequence} has a row that is not an object"
            )
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise TradeFlowCorruptError(
                f"trade-flow record {sequence} has a row with no non-empty symbol"
            )
        try:
            rows.append(
                TradeFlowRow(
                    symbol=symbol,
                    window_start=_parse_timestamp(entry.get("window_start"), sequence),
                    cancel_replace_rate=_optional_decimal(
                        entry.get("cancel_replace_rate"), symbol, "cancel_replace_rate", sequence
                    ),
                    level_events=int(entry["level_events"]),
                    cancel_replace_events=int(entry["cancel_replace_events"]),
                    trade_count=int(entry["trade_count"]),
                    trade_volume=Decimal(entry["trade_volume"]),
                    mean_size=_optional_decimal(
                        entry.get("mean_size"), symbol, "mean_size", sequence
                    ),
                    stddev_size=_optional_decimal(
                        entry.get("stddev_size"), symbol, "stddev_size", sequence
                    ),
                    skew_size=_optional_decimal(
                        entry.get("skew_size"), symbol, "skew_size", sequence
                    ),
                    kurtosis_size=_optional_decimal(
                        entry.get("kurtosis_size"), symbol, "kurtosis_size", sequence
                    ),
                )
            )
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise TradeFlowCorruptError(
                f"trade-flow record {sequence} carries a row this module cannot "
                f"read back: {exc}"
            ) from exc
    return tuple(rows)


def _optional_decimal(raw: object, symbol: str, name: str, sequence: int) -> Decimal | None:
    # ``null`` in the envelope means the feature was honestly absent, not zero —
    # the distinction feature 22's moments stand on, so it is restored as
    # ``None`` rather than defaulted into a number.
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TradeFlowCorruptError(
            f"trade-flow record {sequence} records {symbol} {name}={raw!r}, "
            f"which is neither null nor a decimal: {exc}"
        ) from exc


def _read_closing(entries: object, sequence: int) -> dict[str, BookState]:
    # Read the persisted closing books back into BookState objects — the resume
    # seed.  A closing book that is not a well-formed snapshot is corruption: a
    # damaged seed would reconstruct a book the market never had.
    if not isinstance(entries, Mapping):
        raise TradeFlowCorruptError(
            f"trade-flow record {sequence} has closing books that are not an object"
        )
    closing: dict[str, BookState] = {}
    for symbol, snap in entries.items():
        if not isinstance(snap, Mapping) or "bids" not in snap or "asks" not in snap:
            raise TradeFlowCorruptError(
                f"trade-flow record {sequence} has a closing book for {symbol!r} "
                f"that is not a snapshot"
            )
        closing[symbol] = BookState.from_snapshot(snap)
    return closing


def _parse_optional_timestamp(raw: object, sequence: int) -> datetime | None:
    if raw is None:
        return None
    return _parse_timestamp(raw, sequence)


def _parse_timestamp(raw: object, sequence: int) -> datetime:
    if not isinstance(raw, str):
        raise TradeFlowCorruptError(
            f"trade-flow record {sequence} records a timestamp {raw!r}; expected "
            f"an ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TradeFlowCorruptError(
            f"trade-flow record {sequence} records an unparseable timestamp "
            f"{raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise TradeFlowCorruptError(
            f"trade-flow record {sequence} records a naive timestamp; the grid "
            f"and the provenance need a comparable instant"
        )
    return parsed.astimezone(timezone.utc)


class TradeFlowWorker:
    """The trade-flow worker: classify the diffs, measure the tape, snapshot 1s.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the ``tradeFlow``
    stream class, so the supervisor of feature 16 runs it on its own thread
    alongside every other stream and converts whatever it raises into that
    stream's own failure.  Its inputs are the *internal* raw-diff store feature
    19 persisted and an injected :data:`TradeTape` — never a venue endpoint
    directly — so the only unconfigured path is the tape, and an empty raw store
    simply yields empty cycles.

    One cycle is a stateful reduction over the raw-diff log and the tape, in
    four steps:

    * **Seed.**  Read the last trade-flow record.  Its closing books are the
      running book; its ``to_window`` and ``to_raw_sequence`` are the frontier.
      On the first cycle the book is empty and the frontier is zero.
    * **Consume.**  Read the raw records feature 19 persisted past the frontier,
      classifying each row's levels against the running book *before* folding
      the row in — the ordering :func:`classify_levels` documents — and
      bucketing the counts onto the 1s grid.  Only raw records past
      ``to_raw_sequence`` are consumed, so no diff is folded twice.
    * **Measure.**  Take the tape, bucket its prints onto the same grid, and
      compute each second's size moments.  A print whose second is at or before
      the frontier is dropped: that snapshot is already committed.
    * **Snapshot.**  For each (symbol, second) past the frontier that carried a
      diff *or* a trade, emit one row.  A second that carried neither is silent,
      so the log stays paced by genuine market activity rather than by the
      worker's cycle cadence.

    A cycle that consumes no new raw records appends nothing and reports
    ``sequence=0, rows_written=0`` — the honest no-progress cycle, matching a
    not-due funding cycle.  A cycle that consumes new data but crosses no new
    second still persists (the book moved), with ``rows_written`` counting the
    new rows, which may be zero.

    The clock is injected because ``computed_at`` is a fact about elapsed
    wall-clock time: a test must be able to place the worker without touching the
    wall clock, and §12 keeps wall-clock reads out of checked code.  The default
    clock reads the system UTC time.
    """

    def __init__(
        self,
        store: TradeFlowStore,
        diff_store: BookDiffStore,
        tape: TradeTape,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, TradeFlowStore):
            raise TypeError(
                f"the trade-flow worker persists into a TradeFlowStore, got "
                f"{type(store).__name__}"
            )
        if not isinstance(diff_store, BookDiffStore):
            raise TypeError(
                f"the trade-flow worker reads from a BookDiffStore, got "
                f"{type(diff_store).__name__}"
            )
        if not callable(tape):
            raise TypeError(
                f"tape must be a zero-argument callable returning the venue's "
                f"trade prints, got {type(tape).__name__}"
            )
        if clock is not None and not callable(clock):
            raise TypeError(
                f"clock must be a callable returning a datetime, got "
                f"{type(clock).__name__}"
            )
        self._store = store
        self._diff_store = diff_store
        self._tape = tape
        self._clock = clock if clock is not None else _utc_now

    # -- IngestWorker ---------------------------------------------------------

    @property
    def stream_class(self) -> StreamClass:
        """The one stream class this worker owns — ``tradeFlow``."""
        return TRADE_FLOW_STREAM

    @property
    def store(self) -> TradeFlowStore:
        """The derived-feature log this worker appends to."""
        return self._store

    @property
    def diff_store(self) -> BookDiffStore:
        """The raw-diff store this worker reconstructs the book from."""
        return self._diff_store

    @property
    def tape(self) -> TradeTape:
        """The trade-print seam this worker measures sizes from."""
        return self._tape

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Classify the new raw diffs, measure the tape, persist the 1s rows.

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

        # Consume the raw records past the frontier in one pass.  For each row
        # the classification runs *before* the fold — the order
        # :func:`classify_levels` documents — because "was this price already
        # standing?" is only answerable about the book as it was.
        level_events: dict[tuple[str, datetime], int] = {}
        cancel_events: dict[tuple[str, datetime], int] = {}
        touched: dict[tuple[str, datetime], None] = {}
        from_raw_sequence = frontier_seq
        to_window = frontier_window
        for record in self._diff_store.records():
            if record.sequence <= frontier_seq:
                continue
            for row in record.batch.rows:
                book = books.setdefault(row.symbol, BookState())
                actions = classify_levels(row, book)
                bucket = _floor_to_second(row.window_start)
                if to_window is None or bucket > to_window:
                    to_window = bucket
                if frontier_window is not None and bucket <= frontier_window:
                    book.apply(row)  # still folded: it seeds the going-forward book
                    continue  # already emitted before the frontier
                key = (row.symbol, bucket)
                touched[key] = None
                level_events[key] = level_events.get(key, 0) + len(actions)
                cancel_events[key] = cancel_events.get(key, 0) + cancel_replace_events(actions)
                book.apply(row)
            frontier_seq = record.sequence

        # Measure the tape onto the same grid.  Prints at or before the frontier
        # belong to an already-committed snapshot and are dropped, so a restart
        # never re-measures a second it already measured.
        sizes: dict[tuple[str, datetime], list[Decimal]] = {}
        for print_ in parse_trade_prints(self._tape()):
            bucket = print_.window_start
            if frontier_window is not None and bucket <= frontier_window:
                continue
            # A trade advances the frontier's window too: the tape is the other
            # half of this stream's input, and a second that traded but saw no
            # diff still has its moments committed — so the next cycle must know
            # this second is done, or a re-sent tape would measure it twice.
            if to_window is None or bucket > to_window:
                to_window = bucket
            key = (print_.symbol, bucket)
            touched[key] = None
            sizes.setdefault(key, []).append(print_.size)

        rows: list[TradeFlowRow] = []
        for symbol, bucket in sorted(touched, key=lambda item: (item[1], item[0])):
            bucket_sizes = sizes.get((symbol, bucket), [])
            count = len(bucket_sizes)
            volume = sum(bucket_sizes, _ZERO)
            levels = level_events.get((symbol, bucket), 0)
            cancels = cancel_events.get((symbol, bucket), 0)
            mean, sd, skew, kurtosis = size_moments(bucket_sizes)
            rows.append(
                TradeFlowRow(
                    symbol=symbol,
                    window_start=bucket,
                    cancel_replace_rate=(
                        None if levels == 0 else Decimal(cancels) / Decimal(levels)
                    ),
                    level_events=levels,
                    cancel_replace_events=cancels,
                    trade_count=count,
                    trade_volume=volume,
                    mean_size=mean,
                    stddev_size=sd,
                    skew_size=skew,
                    kurtosis_size=kurtosis,
                )
            )

        if frontier_seq == from_raw_sequence and to_window == frontier_window:
            # Nothing was consumed and no new second was crossed, so there is
            # nothing to persist: the frontier and the closing book are exactly
            # what the last record already carries.  The honest no-progress
            # cycle reports both zero and appends nothing — the same shape a
            # not-due funding cycle has.  This covers the first cycle over
            # entirely empty inputs too, where ``frontier_seq`` is ``0`` and
            # ``to_window`` is ``None`` by definition.
            return CycleResult(rows_written=0, sequence=0)

        batch = TradeFlowBatch(
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


def register_trade_flow_worker(
    tape: TradeTape,
    store: Optional[TradeFlowStore] = None,
    diff_store: Optional[BookDiffStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], TradeFlowWorker]:
    """Register a worker factory bound to explicitly wired collaborators.

    The operator path: hand in the venue's trade tape — feature 18's
    ``aggTrades`` rows once that stream has landed, or any callable returning
    prints — and, when they are not the lake's staging area, the stores; this
    registers a worker factory bound to those collaborators.  Registration
    replaces the auto-discovered factory of the same class in the registry it
    targets — the registry's own rule, *a re-registered class is a revision of
    the same worker, never a second worker* — so a deployment that wires a tape
    does not end up with two trade-flow workers competing for the same sequence
    numbers.

    ``registry`` defaults to a **private** registry, not the process-wide one:
    a registration is a deployment act, and silently replacing the
    auto-discovered worker for every later composition in the process would hand
    unrelated callers — tests especially — a worker bound to stores that may
    since have vanished.  A caller that means to reconfigure the running process
    passes :func:`~nullius_ingest.registry.default_worker_registry` explicitly,
    matching :func:`~nullius_ingest.registry.register_worker`.

    Returns the registered factory, so a caller can build the worker it just
    registered — over the private registry by default — without reaching back
    into it.
    """
    if not callable(tape):
        raise TypeError(
            f"tape must be a zero-argument callable returning the venue's trade "
            f"prints, got {type(tape).__name__}"
        )
    if clock is not None and not callable(clock):
        raise TypeError(
            f"clock must be a callable returning a datetime, got "
            f"{type(clock).__name__}"
        )

    def build() -> TradeFlowWorker:
        resolved_store = store if store is not None else TradeFlowStore.from_env()
        resolved_diff = diff_store if diff_store is not None else BookDiffStore.from_env()
        return TradeFlowWorker(resolved_store, resolved_diff, tape, clock=clock)

    # Register through a private registry by default, never the process-wide
    # one.  Registration is a *deployment* act: writing a caller's wiring into
    # the default registry would replace the auto-discovered worker for every
    # later composition in the process — including tests, which would then be
    # handed a worker bound to stores that have since been deleted.  A caller
    # that genuinely means to reconfigure the running process passes the default
    # registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        TRADE_FLOW_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(TRADE_FLOW_STREAM)
def build_trade_flow_worker() -> TradeFlowWorker:
    """Compose the trade-flow worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    The stores come from the environment the way every other ingest store does
    (:meth:`TradeFlowStore.from_env`, :meth:`BookDiffStore.from_env`), so the
    derived features land in the very area the seal copies out of and the book
    is reconstructed from the raw diffs feature 19 persisted into that same
    area.  The tape has no environment-resolved default — this member ships no
    websocket client, and the venue's ``aggTrades`` stream belongs to feature 18
    — so a deployment wires it with :func:`register_trade_flow_worker`.  Until
    then the worker still composes and its cycle reports that stream's own
    failure, which is feature 16's contract: an unconfigured stream is a row in
    the report, not a component that fails to load.
    """
    return TradeFlowWorker(
        TradeFlowStore.from_env(), BookDiffStore.from_env(), _unconfigured_tape
    )


def _unconfigured_tape() -> object:
    """The tape used when a deployment has not wired a trade feed yet.

    Raising here, rather than at composition time, keeps the plugin shaped the
    way feature 16 wants it: an unconfigured stream is that stream's failure in
    the report, not a component that fails to compose.  The message names the
    feature that owns the venue stream, so an operator reading the report knows
    which module to wait for or wire.
    """
    raise TradeFlowError(
        "no trade tape is configured; the venue's aggTrades stream belongs to "
        "feature 18, and until it lands register this worker with a tape "
        "returning the venue's trade prints "
        "(nullius_ingest.register_trade_flow_worker(tape, "
        "registry=default_worker_registry()))"
    )
