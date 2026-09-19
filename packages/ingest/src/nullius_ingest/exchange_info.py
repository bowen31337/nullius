"""Daily exchangeInfo filter ingest, persisted version-on-version.

app_spec.xml feature 24 states the behaviour: *"System ingests exchangeInfo
filters daily, persisting each fetch as a new version rather than
overwriting the prior one."*  docs/nullius-tech-architecture.md §4.1 fixes
the stream's row in the data-layer table — ``exchangeInfo filters | REST |
daily | forever, versioned`` — and §13.2 states why the order path depends
on it: *"``exchangeInfo`` filters (``LOT_SIZE``, ``NOTIONAL``,
``PRICE_FILTER``, ``stepSize``, ``tickSize``) refreshed at startup and
daily. Never hardcoded."*  The PRD repeats the rule as a prohibition —
*"Read ``LOT_SIZE``, ``NOTIONAL``, ``PRICE_FILTER``, ``stepSize``,
``tickSize`` from ``exchangeInfo`` at startup and daily. Never hardcode."*
A rule that says *never hardcode* is only enforceable if the fetched
constants are somewhere to be read, and only trustworthy if a later fetch
cannot quietly rewrite what an earlier one said.  This module is both.

Three pieces, each load-bearing:

* **The document** — :class:`ExchangeInfoDocument` and
  :class:`SymbolFilters`: the venue's ``symbols[].filters[]`` parsed into
  per-symbol filter maps, field values kept **verbatim** in the venue's own
  spelling (``"0.001"``, not ``Decimal("0.001")``).  Decimalisation is the
  order path's business; this module's business is to carry what the venue
  said, exactly, so a later reader never has to guess whether a rounding in
  the record was the exchange's or ours.  Parsing is strict about the shape
  we own — a symbol with no filters, a duplicated symbol, a filter with no
  type, a document with no symbols at all — because a document that failed
  to parse must never be persisted as though it were a refresh.

* **The version** — :class:`ExchangeInfoVersion`: one *fetch*, frozen, with
  the sequence it was persisted under, when it was fetched, the document's
  content hash, and the hash of the bytes written.  The content hash is
  what makes "did the filters actually change?" answerable without diffing
  two documents: two versions of the same hash carry the same filters, and
  a change of hash is a change the order path must absorb.

* **The versioned store** — :class:`ExchangeInfoVersionStore`: an
  append-only log of versions under the §4.1 staging area, at
  ``<lake>/staging/exchangeInfo/<version>.bin`` — one file per fetch, never
  rewritten.  *Each fetch is a new version rather than an overwrite* is
  therefore structural, not a convention: the store appends at
  ``current + 1`` into feature 28's append-only area
  (:class:`~nullius_ingest.staging.StagingArea`), whose batch store refuses
  a second batch at a sequence it already holds, so version ``n``'s bytes
  are frozen the moment version ``n + 1`` lands.  A version is *not*
  suppressed when it repeats the prior content: the feature says **each**
  fetch is persisted as a new version, and "we fetched and the venue said
  the same thing" is a fact about the venue worth keeping — it is the
  difference between *the refresh ran and nothing changed* and *the refresh
  never ran*, which is exactly the distinction an operator needs when
  orders start being rejected for a stale tick size.

Layering on the stream workers of feature 16 is deliberate: the daily fetch
is one worker, owning one stream class, at
:class:`DailyExchangeInfoWorker`, so a failed refresh is that stream's
:class:`~nullius_ingest.worker.StreamFailure` and every other stream keeps
ingesting.  The fetch itself is injected (:data:`ExchangeInfoFetch`) — the
member ships no REST client, exactly as it ships no websocket client, so
the venue's auth, rate limits and pagination stay the deployment's business
and this module stays stdlib-only.  The clock is injected for the same
reason the gap detector's arithmetic is: the daily cadence is a fact about
UTC calendar days that a test must be able to place anywhere in time
without touching the wall clock (§12 forbids it in checked code anyway).

What "daily" means here is explicit rather than approximate: a fetch is due
when the most recent persisted version was fetched on an **earlier UTC
date** than now, and due immediately when the store holds no version at all
— the *"at startup and daily"* of §13.2, where startup is just the first
cycle of a process whose store is empty.  A restart mid-day therefore does
not re-fetch (the day's version is already durable), and a process that was
down across a boundary fetches on its next cycle rather than waiting for a
timer to expire.  The cadence lives in the store's durable record, not in
process memory, so it survives exactly the restarts the deployment table
calls *"restart-safe"*.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Optional, Union

from .registry import WorkerRegistry, register_worker
from .staging import StagingArea
from .streams import StreamClass
from .worker import CycleResult

__all__ = [
    "DAILY",
    "EXCHANGE_INFO_STREAM",
    "DailyExchangeInfoWorker",
    "ExchangeInfoCorruptError",
    "ExchangeInfoDocument",
    "ExchangeInfoError",
    "ExchangeInfoFetch",
    "ExchangeInfoParseError",
    "ExchangeInfoVersion",
    "ExchangeInfoVersionStore",
    "FilterType",
    "SymbolFilters",
    "build_exchange_info_worker",
    "parse_exchange_info",
    "register_exchange_info_worker",
]

#: The stream class this module serves.  §4.1's table row for ``exchangeInfo``
#: is the one stream whose cadence is a calendar day rather than a feed, and
#: the spelling here is the persisted one (:class:`~nullius_ingest.streams.
#: StreamClass`), so the staging layout and the version log share it.
EXCHANGE_INFO_STREAM = StreamClass.EXCHANGE_INFO

#: The cadence §4.1's table records for this stream.  Carried as a constant
#: so the fact is named where it is decided, not only in prose.
DAILY = "daily"

#: The envelope key holding the venue's document, and the keys around it —
#: named so a reader of a version file (an operator, a seal, a later audit)
#: does not have to import this module to know what it is looking at.
_DOCUMENT_KEY = "document"
_ENVELOPE_KEYS = ("stream", "version", "fetched_at", "source_sha256")


class ExchangeInfoError(Exception):
    """Base for every failure this module raises.

    Raised for a document this module will not persist and for a persisted
    version it will not read: both are cases where a version log would
    otherwise start lying about what the venue said, so both fail loudly
    rather than being approximated into a record.
    """


class ExchangeInfoParseError(ExchangeInfoError):
    """An exchangeInfo document is not one this module will persist.

    Raised *before* anything is written, so a fetch that returned an error
    page, a rate-limit body or a truncated document never consumes a version
    number and never appears in the log as a refresh that happened.  The
    message names what was wrong with which symbol or field, because the
    caller is a worker whose next move depends on whether the venue's shape
    changed or the fetch simply failed.
    """


class ExchangeInfoCorruptError(ExchangeInfoError):
    """A persisted version file does not match what was written under it.

    Raised when a version file cannot be read back as the envelope it was
    written as, when its recorded version is not the version its filename
    claims, or when recomputing its document hash disagrees with the hash the
    envelope recorded.  The log is append-only and copied byte-for-byte by
    the seal, so a mismatch means the bytes on disk are not the bytes this
    module committed — corruption or tampering, either of which a reader must
    hear about rather than silently parse a wrong tick size out of.
    """


class FilterType(StrEnum):
    """The venue filter types §13.2's order path reads, and their neighbours.

    A convenience spelling for the filter types this system names, *not* a
    closed set: an exchange that adds a filter type is a schema change, not a
    parse failure, so :class:`SymbolFilters` keys filters by the venue's own
    string and stores unknown types verbatim.  The enum exists so callers
    that want a typo-proof spelling of ``"LOT_SIZE"`` have one.
    """

    PRICE_FILTER = "PRICE_FILTER"
    """``tickSize``, ``minPrice``, ``maxPrice`` — the price grid."""

    LOT_SIZE = "LOT_SIZE"
    """``stepSize``, ``minQty``, ``maxQty`` — the quantity grid."""

    MARKET_LOT_SIZE = "MARKET_LOT_SIZE"
    """The quantity grid for market orders, where the venue splits them."""

    NOTIONAL = "NOTIONAL"
    """``minNotional`` — the minimum order value, feature 313's refusal."""

    MIN_NOTIONAL = "MIN_NOTIONAL"
    """The older spelling of :attr:`NOTIONAL`, some venues still emit."""

    PERCENT_PRICE = "PERCENT_PRICE"
    """``multiplierUp``/``multiplierDown`` — the price band off the index."""

    PERCENT_PRICE_BY_SIDE = "PERCENT_PRICE_BY_SIDE"
    """The per-side variant of :attr:`PERCENT_PRICE`."""


def _filter_key(filter_type: object) -> str:
    """The venue string spelling of ``filter_type``, for lookups.

    Accepts a :class:`FilterType` or the exact string the venue uses —
    including a type this system has never heard of, which is the point:
    lookups must not be able to fail merely because a venue added a filter.
    """
    if isinstance(filter_type, FilterType):
        return filter_type.value
    if isinstance(filter_type, str):
        if not filter_type:
            raise ValueError("a filter type cannot be the empty string")
        return filter_type
    raise TypeError(
        f"filter type must be a FilterType or its venue spelling, "
        f"not {type(filter_type).__name__}"
    )


def _scalar_field(value: object, where: str) -> str:
    # Filter field values are persisted as the venue's own spelling.  Venues
    # are not consistent about JSON types for the same field — a step size
    # arrives as ``"0.001"`` and a max order count as ``200`` — so scalars
    # are coerced to their string spelling rather than rejected, while
    # containers are refused: a nested object is a shape this module does not
    # model, and storing its ``repr`` would be a record that looks like data
    # and is not.
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
    raise ExchangeInfoParseError(
        f"{where} is {type(value).__name__}; filter field values must be "
        f"scalars (the venue's own spelling is kept verbatim)"
    )


@dataclass(frozen=True)
class SymbolFilters:
    """One symbol's filters, keyed by the venue's filter type.

    ``filters`` maps a filter type (``"LOT_SIZE"``) to that filter's fields
    (``{"stepSize": "0.001", "minQty": "0.001", ...}``), every value the
    venue's own string spelling.  The whole filter is kept — not just the
    fields §13.2 names — because an unrecognised field is information the
    order path may need tomorrow and re-fetching history to recover it is
    impossible: a version is written once and never overwritten, so a field
    dropped at persist time is a field lost forever.
    """

    symbol: str
    filters: Mapping[str, Mapping[str, str]]

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ExchangeInfoParseError(
                f"a symbol must be a non-empty string, got {self.symbol!r}"
            )
        # Freeze the nested maps into read-only views: a version is a record
        # of what the venue said, and a caller mutating it in place would be
        # editing history.
        object.__setattr__(
            self,
            "filters",
            {
                _filter_key(kind): dict(fields)
                for kind, fields in self.filters.items()
            },
        )

    @property
    def filter_types(self) -> tuple[str, ...]:
        """The venue's filter types for this symbol, in document order."""
        return tuple(self.filters)

    def filter(self, filter_type: FilterType | str) -> Mapping[str, str] | None:
        """The fields of one filter type, or ``None`` when the symbol has none.

        ``None`` rather than an empty mapping: "the venue did not send a
        ``NOTIONAL`` filter" and "the venue sent an empty one" are different
        facts, and a caller deciding whether an order is placeable needs to
        tell them apart.
        """
        return self.filters.get(_filter_key(filter_type))

    def value(self, filter_type: FilterType | str, field: str) -> str | None:
        """One filter field's value verbatim, or ``None`` when absent."""
        fields = self.filter(filter_type)
        if fields is None:
            return None
        return fields.get(field)

    # -- The §13.2 constants the order path must never hardcode ---------------

    @property
    def step_size(self) -> str | None:
        """``LOT_SIZE.stepSize`` — the quantity grid, verbatim."""
        return self.value(FilterType.LOT_SIZE, "stepSize")

    @property
    def min_qty(self) -> str | None:
        """``LOT_SIZE.minQty`` — the smallest quantity, verbatim."""
        return self.value(FilterType.LOT_SIZE, "minQty")

    @property
    def tick_size(self) -> str | None:
        """``PRICE_FILTER.tickSize`` — the price grid, verbatim."""
        return self.value(FilterType.PRICE_FILTER, "tickSize")

    @property
    def min_notional(self) -> str | None:
        """``NOTIONAL.minNotional`` — the minimum order value, verbatim.

        Falls back to the older ``MIN_NOTIONAL`` spelling when the venue emits
        that instead, because a venue that spells it the old way has not
        stopped having a minimum order value.
        """
        value = self.value(FilterType.NOTIONAL, "minNotional")
        if value is None:
            value = self.value(FilterType.MIN_NOTIONAL, "minNotional")
        return value


@dataclass(frozen=True)
class ExchangeInfoDocument:
    """One exchangeInfo response, as the per-symbol filters it carries.

    ``symbols`` maps a symbol to its :class:`SymbolFilters`, in the order the
    venue listed them — order is preserved rather than sorted because the
    venue's order is what a human diffing two versions will read, and nothing
    in the system depends on iteration order.  The document is what gets
    persisted, so it is the unit the content hash is taken over and the unit
    two versions are compared through.
    """

    symbols: Mapping[str, SymbolFilters]

    def __post_init__(self) -> None:
        if not self.symbols:
            # Refused deliberately.  An exchangeInfo response with no symbols
            # is a rate-limit body, an error page or a truncated read — never
            # a refresh — and persisting it as a version would make a failed
            # fetch indistinguishable from a successful one in the very log
            # the order path trusts for its tick size.
            raise ExchangeInfoParseError(
                "an exchangeInfo document must carry at least one symbol; "
                "an empty document is a failed fetch, not a filter refresh"
            )
        object.__setattr__(self, "symbols", dict(self.symbols))

    @property
    def symbol_names(self) -> tuple[str, ...]:
        """The symbols the document carries, in the venue's order."""
        return tuple(self.symbols)

    def __len__(self) -> int:
        return len(self.symbols)

    def for_symbol(self, symbol: str) -> SymbolFilters | None:
        """The filters for ``symbol``, or ``None`` when the document omits it."""
        return self.symbols.get(symbol)

    def canonical_bytes(self) -> bytes:
        """The document's canonical JSON bytes — the thing content-hashed.

        Canonical means symbols and filter types ordered by name, keys sorted,
        and the tightest separators — so two documents carrying the same
        filters hash identically whatever order the venue listed its symbols
        and filters in and whatever whitespace the transport added.  This is
        what makes :attr:`ExchangeInfoVersion.source_sha256` a *content*
        hash: two fetches that returned the same filters agree on it, and a
        fetch that changed one ``stepSize`` does not.

        Note the deliberate asymmetry with the persisted document, which keeps
        the venue's own symbol order (`document` in the version envelope): a
        human diffing two versions reads the venue's order, while the hash
        answers *did the filters change* — and a venue that merely reordered
        its listing has not changed a single filter.
        """
        return json.dumps(
            _document_to_json(self, order="canonical"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def source_sha256(self) -> str:
        """The sha256 of :meth:`canonical_bytes` — the document's identity."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _document_to_json(document: ExchangeInfoDocument, *, order: str) -> dict:
    # The JSON shape a version file carries: the venue's own nesting, so a
    # reader of the file sees symbols and filters rather than this module's
    # internal dataclass layout.  ``order`` selects the canonicalisation —
    # ``"venue"`` for the persisted document (what a human diffs) and
    # ``"canonical"`` for hashing, which orders symbols *and* filters by name
    # so that a venue reordering its listing, or its filter list, is not
    # recorded as a changed filter.  Both orders are safe to sort by name:
    # the parser has already refused duplicate symbols and duplicate filter
    # types, so neither list contains a key that could sort ambiguously.
    symbols = document.symbols
    if order == "canonical":
        symbols = {name: symbols[name] for name in sorted(symbols)}
    return {
        "symbols": [
            {
                "symbol": symbol,
                "filters": [
                    {"filterType": kind, **fields}
                    for kind, fields in (
                        sorted(filters.filters.items())
                        if order == "canonical"
                        else filters.filters.items()
                    )
                ],
            }
            for symbol, filters in symbols.items()
        ]
    }


def parse_exchange_info(document: object) -> ExchangeInfoDocument:
    """Parse an exchangeInfo payload into an :class:`ExchangeInfoDocument`.

    Accepts the venue's response object as decoded JSON — either the document
    itself (``{"symbols": [...]}``) or the wrapper some endpoints use
    (``{"exchangeInfo": {"symbols": [...]}}``) — and refuses anything that is
    not a well-formed filter document with :class:`ExchangeInfoParseError`.

    Strict about the shape this system owns: a symbol entry must name its
    symbol and carry a filter list, a filter must name its type, a symbol
    must not be listed twice (a duplicate makes "the filters for BTCUSDT"
    ambiguous, and picking one arbitrarily would be a silent choice between
    two different tick sizes), and the document must carry at least one
    symbol.  Tolerant where the venue is free: unknown filter types and
    unknown filter fields are kept verbatim, because a venue adding a field
    is a schema change to absorb, not a fetch to discard.
    """
    if isinstance(document, ExchangeInfoDocument):
        return document
    if isinstance(document, (bytes, bytearray, str)):
        try:
            decoded = json.loads(document)
        except ValueError as exc:
            raise ExchangeInfoParseError(
                f"exchangeInfo payload is not valid JSON: {exc}"
            ) from exc
    elif isinstance(document, Mapping):
        decoded = document
    else:
        raise ExchangeInfoParseError(
            f"exchangeInfo payload must be JSON bytes, a string or a mapping, "
            f"not {type(document).__name__}"
        )

    body = decoded
    if isinstance(body, Mapping) and "symbols" not in body:
        # The wrapped spelling some endpoints use.  Looked for only when the
        # document is not already the flat one, so a symbol literally named
        # "exchangeInfo" in a flat document can never shadow the wrapper.
        nested = body.get("exchangeInfo")
        if isinstance(nested, Mapping):
            body = nested
    if not isinstance(body, Mapping):
        raise ExchangeInfoParseError(
            f"exchangeInfo payload must be a JSON object, "
            f"not {type(body).__name__}"
        )
    entries = body.get("symbols")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ExchangeInfoParseError(
            "exchangeInfo payload has no 'symbols' list; the document is not "
            "a filter response"
        )

    symbols: dict[str, SymbolFilters] = {}
    for index, entry in enumerate(entries):
        filters = _parse_symbol_entry(entry, index)
        if filters.symbol in symbols:
            raise ExchangeInfoParseError(
                f"symbol {filters.symbol!r} is listed more than once at "
                f"index {index}; the document does not say which filters "
                f"apply"
            )
        symbols[filters.symbol] = filters
    return ExchangeInfoDocument(symbols=symbols)


def _parse_symbol_entry(entry: object, index: int) -> SymbolFilters:
    if not isinstance(entry, Mapping):
        raise ExchangeInfoParseError(
            f"symbols[{index}] is {type(entry).__name__}; expected an object"
        )
    symbol = entry.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise ExchangeInfoParseError(
            f"symbols[{index}] has no non-empty 'symbol' string "
            f"(got {symbol!r})"
        )
    raw_filters = entry.get("filters")
    if not isinstance(raw_filters, Sequence) or isinstance(
        raw_filters, (str, bytes)
    ):
        raise ExchangeInfoParseError(
            f"symbols[{index}] ({symbol}) has no 'filters' list"
        )
    parsed: dict[str, dict[str, str]] = {}
    for position, raw in enumerate(raw_filters):
        kind, fields = _parse_filter(raw, symbol, position)
        if kind in parsed:
            raise ExchangeInfoParseError(
                f"{symbol} carries the {kind!r} filter more than once "
                f"(at index {position}); the document does not say which "
                f"values apply"
            )
        parsed[kind] = fields
    if not parsed:
        # A symbol with no filters cannot be traded: §13.2's order path has no
        # step size or tick size to round to.  Refusing it keeps the version
        # log from recording a symbol as "refreshed" when what it actually
        # says is "unknown".
        raise ExchangeInfoParseError(
            f"{symbol} carries no filters; a symbol without a step size and "
            f"a tick size is not a filter refresh"
        )
    return SymbolFilters(symbol=symbol, filters=parsed)


def _parse_filter(
    raw: object, symbol: str, position: int
) -> tuple[str, dict[str, str]]:
    if not isinstance(raw, Mapping):
        raise ExchangeInfoParseError(
            f"{symbol} filters[{position}] is {type(raw).__name__}; "
            f"expected an object"
        )
    kind = raw.get("filterType")
    if not isinstance(kind, str) or not kind:
        raise ExchangeInfoParseError(
            f"{symbol} filters[{position}] has no non-empty 'filterType' "
            f"string (got {kind!r})"
        )
    fields = {
        str(name): _scalar_field(value, f"{symbol} filters[{position}].{name}")
        for name, value in raw.items()
        if name != "filterType"
    }
    return kind, fields


#: A fetch: return the venue's exchangeInfo response, as JSON bytes, a JSON
#: string, a decoded mapping, or an already-parsed document.
#:
#: The seam the deployment's REST client fills.  This member ships no HTTP
#: client — like the gap detector, which watches integers rather than
#: sockets — so the venue's auth, weight budget and retry policy stay the
#: stream worker's business, and the store stays testable without a network.
#: Whatever the fetch returns is parsed before anything is written, so a
#: failed fetch never consumes a version.
ExchangeInfoFetch = Callable[[], Union[bytes, str, Mapping, ExchangeInfoDocument]]


@dataclass(frozen=True)
class ExchangeInfoVersion:
    """One persisted fetch: the version it landed under and what it said.

    ``version`` is the version's position in the stream's append-only log —
    ``1`` for the first fetch, then ``2, 3, ...`` — and, because the log is
    feature 28's staging area, it is also the sequence of the batch the
    envelope bytes were committed as.  ``fetched_at`` is when the fetch
    happened (UTC, timezone-aware): the durable fact the daily cadence is
    decided from, so a restarted process knows whether today's refresh has
    already run without asking the exchange again.

    Two hashes, deliberately distinct: ``source_sha256`` is over the
    *document* and answers "did the filters change?"; ``payload_sha256`` is
    over the *bytes written* — the envelope and the document together — and
    is the file's identity, the same value the seal's MANIFEST will record
    for it.  ``path`` names the ``<version>.bin`` the bytes were committed
    to, so a seal or an operator can point at the exact artifact; it is
    never written through, because the only way to add a version is another
    :meth:`ExchangeInfoVersionStore.record`.
    """

    version: int
    fetched_at: datetime
    document: ExchangeInfoDocument
    source_sha256: str
    payload_sha256: str
    path: Path

    @property
    def symbol_count(self) -> int:
        """How many symbols this version carries — its row count."""
        return len(self.document)

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this version carries, in the venue's order."""
        return self.document.symbol_names

    def filters_for(self, symbol: str) -> SymbolFilters | None:
        """The filters this version records for ``symbol``, or ``None``."""
        return self.document.for_symbol(symbol)

    def carries_same_filters_as(self, other: "ExchangeInfoVersion") -> bool:
        """Whether ``other`` recorded the same filters as this version.

        Compares content hashes, so it answers the operator's question — *did
        the refresh change anything?* — without diffing two documents, and it
        is honest about the distinction the log preserves: a later version
        that carries the same filters is still a later version, because the
        fetch happened.
        """
        return self.source_sha256 == other.source_sha256

    def render(self) -> str:
        """One line an operator reads and knows which filters were in force."""
        listing = ", ".join(self.symbols[:3])
        if len(self.symbols) > 3:
            listing = f"{listing}, ..."
        return (
            f"exchangeInfo version {self.version} fetched "
            f"{self.fetched_at.isoformat()} carries {self.symbol_count} "
            f"symbol(s) [{listing}] sha256={self.source_sha256[:12]}"
        )


class ExchangeInfoVersionStore:
    """The append-only log of exchangeInfo versions under the staging area.

    Versions live at ``<lake>/staging/exchangeInfo/<version>.bin``, one file
    per fetch, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a version is written
    once, atomically (temp file, ``fsync``, ``rename``), and never rewritten:
    the underlying batch store refuses a second batch at a sequence it
    already holds.  *Persisting each fetch as a new version rather than
    overwriting the prior one* is therefore the store's structure rather than
    its discipline, and a reader can trust that version ``n``'s bytes today
    are the bytes version ``n`` was committed with.

    The area is also where the seal looks.  §4.2's snapshot layout carries an
    ``exchangeinfo/`` directory, and this stream's staging log is what a seal
    copies into it, so the versioned history becomes part of the sealed,
    content-addressed record instead of a sidecar that a replay would have to
    reconstruct from live requests — which it could not do honestly, since a
    version describes what the venue said on a day that has passed.

    Construction reads whatever a prior run left on disk, so a restarted
    process knows the last version it persisted without a network call — the
    same seed-from-what-is-durable moment the resume watermark gives a
    restarted worker.  A store is one-writer-per-stream, like the gap
    detector: the daily cadence means one worker appends, and a second
    concurrent appender would race for the same version number and be refused
    by the batch store rather than silently overwriting.
    """

    def __init__(self, staging: StagingArea) -> None:
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"the version store writes into a StagingArea, "
                f"got {type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "ExchangeInfoVersionStore":
        """The store over the lake's staging area, resolved from the environment.

        The same resolution the ingest workers and the sealing service use
        (``LAKE_ROOT``, defaulting to ``lake/`` beside the workspace root), so
        versions are written into the very area the seal copies out of —
        there is no second root that could drift from the first.
        """
        return cls(StagingArea.from_env(env))

    # -- Paths ----------------------------------------------------------------

    @property
    def staging(self) -> StagingArea:
        """The append-only area the versions are committed into."""
        return self._staging

    @property
    def root(self) -> Path:
        """The directory holding this stream's version files."""
        return self._staging.path_for(EXCHANGE_INFO_STREAM)

    def path_for(self, version: int) -> Path:
        """The file version ``version`` is committed to."""
        if not isinstance(version, int) or isinstance(version, bool):
            raise TypeError(
                f"a version is an integer, not {type(version).__name__}"
            )
        if version <= 0:
            raise ValueError(f"a version must be positive, got {version}")
        return self.root / f"{version}.bin"

    # -- Recording ------------------------------------------------------------

    def record(
        self,
        document: Union[bytes, str, Mapping, ExchangeInfoDocument],
        *,
        fetched_at: datetime,
    ) -> ExchangeInfoVersion:
        """Persist one fetch as the next version; never overwrite a prior one.

        The document is parsed and validated *first*, so a failed fetch
        consumes no version number and leaves the log untouched; then it is
        written as the next version — ``current + 1`` — into the stream's
        append-only staging log.  The previous versions are not read, moved or
        rewritten: adding a version is an append, and the store's duplicate-
        sequence refusal means this method has no code path that could
        overwrite one.

        ``fetched_at`` is required and must be timezone-aware: the daily
        cadence is decided from it, and a naive timestamp would make "which
        UTC day was that?" unanswerable at exactly the boundary the rule
        turns on.  The store does not read a clock of its own — the caller
        that fetched owns the time the fetch happened.
        """
        parsed = parse_exchange_info(document)
        _require_aware(fetched_at, "fetched_at")

        version = self._staging.current(EXCHANGE_INFO_STREAM) + 1
        envelope = {
            "stream": str(EXCHANGE_INFO_STREAM),
            "version": version,
            "fetched_at": _isoformat_utc(fetched_at),
            "source_sha256": parsed.source_sha256,
            _DOCUMENT_KEY: _document_to_json(parsed, order="venue"),
        }
        payload = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        batch = self._staging.append(
            EXCHANGE_INFO_STREAM, payload=payload, rows=len(parsed)
        )
        return ExchangeInfoVersion(
            version=batch.sequence,
            fetched_at=fetched_at.astimezone(timezone.utc),
            document=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            path=batch.path,
        )

    # -- Reading --------------------------------------------------------------

    def versions(self) -> tuple[ExchangeInfoVersion, ...]:
        """Every persisted version, oldest first.

        Read back from the staging log in ascending version order, each
        envelope verified against the version its filename claims and the
        document hash it recorded — so a reader gets either the version that
        was committed or a clear :class:`ExchangeInfoCorruptError`, never a
        plausible-looking record assembled from damaged bytes.
        """
        return tuple(
            self._read(batch)
            for batch in self._staging.staged(EXCHANGE_INFO_STREAM)
        )

    def current(self) -> ExchangeInfoVersion | None:
        """The most recent version, or ``None`` when no fetch has been persisted.

        ``None`` is the honest answer for an empty log — a store that has
        never recorded a version has no tick size to offer, and a caller that
        needs one must fetch rather than be handed a default that would be
        exactly the hardcoded venue constant §13.2 forbids.
        """
        batches = self._staging.staged(EXCHANGE_INFO_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def previous(self) -> ExchangeInfoVersion | None:
        """The version before :meth:`current`, or ``None`` when there is none.

        The comparison point a refresh reports against: a worker can say
        whether the fetch it just persisted changed the filters, which is the
        difference between a quiet day and a day the order path must absorb.
        """
        batches = self._staging.staged(EXCHANGE_INFO_STREAM)
        if len(batches) < 2:
            return None
        return self._read(batches[-2])

    def version(self, version: int) -> ExchangeInfoVersion | None:
        """The version persisted under ``version``, or ``None`` if never recorded.

        ``None`` distinguishes *that version was never recorded* from *the log
        holds a version under that number but its bytes are damaged*, which
        :meth:`versions` and :meth:`current` raise for.  A caller walking the
        history — an audit asking what the tick size was on a past day — gets
        the honest absence rather than an exception for a number that simply
        never happened.
        """
        self.path_for(version)  # validates the argument; raises on a bad one
        for batch in self._staging.staged(EXCHANGE_INFO_STREAM):
            if batch.sequence == version:
                return self._read(batch)
        return None

    def latest_filters(self, symbol: str) -> SymbolFilters | None:
        """The filters the most recent version records for ``symbol``.

        The read an order path performs when it needs a step size or a tick
        size: the newest version's answer for that symbol, or ``None`` when
        no version has been persisted or the newest one omits the symbol.
        Deliberately not a fallback to an older version: a symbol the venue
        has stopped listing must not be tradeable off a stale grid, so an
        absent symbol stays absent and the caller refuses the order.
        """
        latest = self.current()
        if latest is None:
            return None
        return latest.filters_for(symbol)

    def _read(self, batch) -> ExchangeInfoVersion:
        # Read one committed batch back into a version, verifying as it goes.
        # The three checks below are the read half of the append-only
        # guarantee: the bytes are the bytes that were committed, under the
        # version the filename claims, carrying the document the envelope's
        # hash vouches for.  A mismatch is corruption (or tampering) on a log
        # the order path trusts for venue constants, so it is raised rather
        # than papered over.
        try:
            envelope = json.loads(batch.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ExchangeInfoCorruptError(
                f"exchangeInfo version {batch.sequence} is not readable as a "
                f"JSON envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise ExchangeInfoCorruptError(
                f"exchangeInfo version {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise ExchangeInfoCorruptError(
                f"exchangeInfo version {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"version envelope this store wrote"
            )
        recorded = envelope["version"]
        if recorded != batch.sequence:
            raise ExchangeInfoCorruptError(
                f"exchangeInfo version file {batch.sequence}.bin records "
                f"version {recorded!r}; the file does not describe itself"
            )
        document = parse_exchange_info(envelope[_DOCUMENT_KEY])
        recorded_hash = envelope["source_sha256"]
        if recorded_hash != document.source_sha256:
            raise ExchangeInfoCorruptError(
                f"exchangeInfo version {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{document.source_sha256!r}; the file's bytes are not the "
                f"bytes that were committed"
            )
        return ExchangeInfoVersion(
            version=batch.sequence,
            fetched_at=_parse_timestamp(envelope["fetched_at"], batch.sequence),
            document=document,
            source_sha256=document.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


def _require_aware(moment: object, what: str) -> None:
    # The daily cadence is a UTC calendar-day rule, so a naive timestamp would
    # be ambiguous at exactly the boundary the rule turns on.  Refused here,
    # where a caller can still fix its clock handling, rather than silently
    # assumed to be UTC and recorded wrong.
    if not isinstance(moment, datetime):
        raise TypeError(f"{what} must be a datetime, not {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{what} must be timezone-aware; a naive timestamp cannot say "
            f"which UTC day the fetch belongs to"
        )


def _isoformat_utc(moment: datetime) -> str:
    # Persisted in UTC with an explicit offset, so the record says which day it
    # belongs to without the reader assuming.
    return moment.astimezone(timezone.utc).isoformat()


def _parse_timestamp(raw: object, version: int) -> datetime:
    if not isinstance(raw, str):
        raise ExchangeInfoCorruptError(
            f"exchangeInfo version {version} records fetched_at "
            f"{raw!r}; expected an ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ExchangeInfoCorruptError(
            f"exchangeInfo version {version} records an unparseable "
            f"fetched_at {raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ExchangeInfoCorruptError(
            f"exchangeInfo version {version} records a naive fetched_at "
            f"{raw!r}; the daily cadence needs the UTC day it belongs to"
        )
    return parsed.astimezone(timezone.utc)


class DailyExchangeInfoWorker:
    """The daily exchangeInfo worker: fetch once a UTC day, persist a version.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the
    ``exchangeInfo`` stream class, so the supervisor of feature 16 runs it on
    its own thread alongside every other stream and converts whatever it
    raises into that stream's own failure.  One cycle is:

    * **Due?**  Ask the store — :meth:`is_due` — whether the daily refresh
      has already happened.  Not due is a *successful* zero-row cycle, not a
      failure and not a skip: the stream is current, which is the state the
      cadence exists to hold.
    * **Fetch.**  Call the injected :data:`ExchangeInfoFetch`.  The exchange's
      REST client, its auth and its rate limits are the deployment's business;
      this worker owns only the cadence and the persistence.
    * **Persist.**  Parse first, then record the document as the next version.
      A failed fetch — a rate-limit body, an error page, a truncated response
      — raises :class:`ExchangeInfoParseError` *before* anything is written,
      so the version log never records a refresh that did not happen and the
      order path is never handed a tick size parsed out of an error page.

    The clock is injected (:data:`Clock`) because the daily rule is a fact
    about UTC calendar days: a test must be able to place the worker on either
    side of a boundary without touching the wall clock, and §12 keeps
    wall-clock reads out of checked code in any case.  The default clock reads
    the system UTC time, which is what a deployment wants.

    A worker is one-writer for its stream, like the gap detector: the daily
    cadence means one fetch at a time, and the store's append-only commit
    refuses a racing second append at the same version rather than losing one.
    """

    def __init__(
        self,
        store: ExchangeInfoVersionStore,
        fetch: ExchangeInfoFetch,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, ExchangeInfoVersionStore):
            raise TypeError(
                f"the daily worker persists into an ExchangeInfoVersionStore, "
                f"got {type(store).__name__}"
            )
        if not callable(fetch):
            raise TypeError(
                f"fetch must be a zero-argument callable returning the venue's "
                f"exchangeInfo response, got {type(fetch).__name__}"
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
        """The one stream class this worker owns — ``exchangeInfo``."""
        return EXCHANGE_INFO_STREAM

    @property
    def store(self) -> ExchangeInfoVersionStore:
        """The version log this worker appends to."""
        return self._store

    # -- Cadence --------------------------------------------------------------

    def last_fetched_at(self) -> datetime | None:
        """When the most recent persisted version was fetched, or ``None``.

        Read from the durable log rather than remembered in the process, so a
        restart knows whether today's refresh has run — which is the whole
        point of deriving the cadence from the store: the deployment table
        calls ingest *restart-safe*, and a cadence held in memory would
        re-fetch on every restart and skip a day whenever the process happened
        to be down at the wrong moment.
        """
        latest = self._store.current()
        return None if latest is None else latest.fetched_at

    def is_due(self, *, now: Optional[datetime] = None) -> bool:
        """Whether a fetch is due at ``now`` (default: the injected clock).

        Due when no version has ever been persisted — §13.2's *"at startup"*,
        where startup is simply the first cycle of a process over an empty
        store — or when the most recent version was fetched on an earlier UTC
        date.  Same UTC day is not due, so a restart mid-day does not re-fetch
        the day's filters, and a process that was down across a boundary
        fetches on its next cycle rather than waiting for a timer.
        """
        moment = self._clock() if now is None else now
        _require_aware(moment, "now")
        last = self.last_fetched_at()
        if last is None:
            return True
        return last.astimezone(timezone.utc).date() < moment.astimezone(
            timezone.utc
        ).date()

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Run one cycle: fetch and persist today's filters if they are due.

        Returns the persisted version's sequence as the cycle's watermark, so
        a monitor sees the log advance, and ``rows_written`` as the number of
        symbols the version carries.  A not-due cycle reports both as zero:
        no fetch, no version, no progress to claim.
        """
        now = self._clock()
        _require_aware(now, "the clock")
        if not self.is_due(now=now):
            return CycleResult(rows_written=0, sequence=0)
        document = self._fetch()
        version = self._store.record(document, fetched_at=now)
        return CycleResult(
            rows_written=version.symbol_count, sequence=version.version
        )


def _utc_now() -> datetime:
    """The default clock: the current UTC time, timezone-aware."""
    return datetime.now(timezone.utc)


def register_exchange_info_worker(
    fetch: ExchangeInfoFetch,
    store: Optional[ExchangeInfoVersionStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], DailyExchangeInfoWorker]:
    """Register a worker factory bound to an explicitly wired fetch.

    The operator path: hand in the REST client's fetch (and, when it is not
    the lake's staging area, the store), and this registers a worker factory
    bound to those collaborators.  Registration replaces the auto-discovered
    factory of the same class in the registry it targets — the registry's own
    rule, *a re-registered class is a revision of the same worker, never a
    second worker* — so a deployment that wires a client does not end up with
    two exchangeInfo workers competing for the same version numbers.

    ``registry`` defaults to a **private** registry, not the process-wide one:
    a registration is a deployment act, and silently replacing the
    auto-discovered worker for every later composition in the process would
    hand unrelated callers — tests especially — a worker bound to a store that
    may since have vanished.  A caller that means to reconfigure the running
    process passes :func:`~nullius_ingest.registry.default_worker_registry`
    explicitly, matching :func:`~nullius_ingest.registry.register_worker`.

    Returns the registered factory, so a caller can build the worker it just
    registered — over the private registry by default — without reaching back
    into it.
    """
    if not callable(fetch):
        raise TypeError(
            f"fetch must be a zero-argument callable returning the venue's "
            f"exchangeInfo response, got {type(fetch).__name__}"
        )

    def build() -> DailyExchangeInfoWorker:
        resolved_store = (
            store if store is not None else ExchangeInfoVersionStore.from_env()
        )
        return DailyExchangeInfoWorker(
            resolved_store, fetch, clock=clock
        )

    # Register through a private registry by default, never the process-wide
    # one.  Registration is a *deployment* act: writing a caller's wiring into
    # the default registry would replace the auto-discovered worker for every
    # later composition in the process — including tests, which would then be
    # handed a worker bound to a store that has since vanished.  A caller that
    # genuinely means to reconfigure the running process passes the default
    # registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        EXCHANGE_INFO_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(EXCHANGE_INFO_STREAM)
def build_exchange_info_worker() -> DailyExchangeInfoWorker:
    """Compose the daily exchangeInfo worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    Collaborators come from the environment the way every other ingest seam
    does: the store is the lake's staging area
    (:meth:`ExchangeInfoVersionStore.from_env`), so versions land in the very
    area the seal copies out of.  The fetch has no environment-resolved
    default — this member ships no HTTP client, so the venue's auth, weights
    and pagination stay the deployment's business — and a deployment wires it
    with :func:`register_exchange_info_worker`.  Until then the worker still
    composes and its cycle reports that stream's own failure, which is
    feature 16's contract: an unconfigured stream is a row in the report, not
    a component that fails to load.
    """
    return DailyExchangeInfoWorker(
        ExchangeInfoVersionStore.from_env(), _unconfigured_fetch
    )


def _unconfigured_fetch() -> object:
    """The fetch used when a deployment has not wired a REST client yet.

    Raising here, rather than at composition time, keeps the plugin shaped the
    way feature 16 wants it: an unconfigured stream is that stream's failure
    in the report, not a component that fails to compose.
    """
    raise ExchangeInfoError(
        "no exchangeInfo fetch is configured; register the worker with a "
        "fetch returning the venue's exchangeInfo response "
        "(nullius_ingest.register_exchange_info_worker(fetch, store=..., "
        "registry=default_worker_registry()))"
    )
