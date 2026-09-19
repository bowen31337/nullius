"""Funding rate and margin borrow rate ingest, polled every 60 seconds and retained permanently.

app_spec.xml feature 23 states the behaviour: *"System ingests funding rate
and margin borrow rate every 60 seconds, persisting rows retained
permanently."*  docs/nullius-tech-architecture.md §4.1 fixes the stream's row
in the data-layer table — ``Funding / borrow rate | REST | 1m | forever`` — and
the retention column is the load-bearing one: unlike the L2 book diffs, which
§4.1 keeps for a rolling 90 days, the funding and borrow series are kept
*forever*, because a borrow-cost adjustment (feature 309) and a funding-based
crowding proxy (feature 30) reach back across the whole history, and a row
dropped at ingest time is a row no replay can ever recover.  This module is
that "forever" made structural: it appends each poll into the append-only
staging area, which is written once and copied by the seal, never rewritten and
never expired.

Three pieces, each load-bearing:

* **The reading** — :class:`FundingReading`: one symbol's two rates at one
  instant, the funding rate and the margin borrow rate, each kept **verbatim**
  in the venue's own spelling (``"0.0001"``, not ``Decimal("0.0001")``).
  Decimalisation is the cost path's business; this module's business is to
  carry what the venue said, exactly, so a later reader never has to guess
  whether a rounding in the record was the exchange's or ours.  Parsing is
  strict about the shape we own — a symbol with no funding rate, a symbol with
  no borrow rate, a duplicated symbol, a document with no readings at all —
  because a payload that failed to parse must never be persisted as though it
  were a poll that happened.

* **The record** — :class:`FundingRecord`: one *poll*, frozen, with the
  sequence it was persisted under, when it was fetched, the document's content
  hash and the hash of the bytes written.  The content hash is what makes "did
  the rates actually change?" answerable without diffing two documents, and the
  bytes hash is the file's identity — the same value the seal's MANIFEST will
  record for it.

* **The store** — :class:`FundingRateStore`: an append-only log of records
  under the §4.1 staging area, at ``<lake>/staging/funding/<seq>.bin`` — one
  file per poll, never rewritten.  *Persisting each poll's rows, retained
  permanently* is therefore structural, not a convention: the store appends at
  ``current + 1`` into feature 28's append-only area
  (:class:`~nullius_ingest.staging.StagingArea`), whose batch store refuses a
  second batch at a sequence it already holds and which nothing in the system
  ever expires, so a poll's bytes are frozen the moment the next poll lands and
  no poll is ever dropped by a retention window.  This is the deliberate
  contrast with the book-diff stream: both append into the same staging area,
  but only the funding log is read by a reader that reaches back forever.

Layering on the stream workers of feature 16 is deliberate: the 60-second poll
is one worker, owning one stream class, at :class:`FundingRateWorker`, so a
failed poll is that stream's :class:`~nullius_ingest.worker.StreamFailure` and
every other stream keeps ingesting.  The fetch itself is injected
(:data:`FundingFetch`) — the member ships no REST client, exactly as it ships
no websocket client, so the venue's auth, rate limits and pagination stay the
deployment's business and this module stays stdlib-only.  The clock is injected
for the same reason the exchangeInfo worker's clock is: the 60-second cadence
is a fact about elapsed wall-clock time that a test must be able to place on
either side of a boundary without touching the wall clock (§12 forbids it in
checked code anyway).

What "every 60 seconds" means here is explicit rather than approximate: a poll
is due when no poll has ever been persisted — startup is simply the first
cycle of a process whose store is empty — or when the most recent persisted
poll was fetched **at least 60 seconds** before now.  Same poll inside the
window is not due, so a worker driven faster than the cadence does not spam the
exchange, and a process that was down across a boundary polls on its next cycle
rather than waiting for a timer.  The cadence lives in the store's durable
record, not in process memory, so it survives exactly the restarts the
deployment table calls *"restart-safe"*.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

from .registry import WorkerRegistry, register_worker
from .staging import StagingArea
from .streams import StreamClass
from .worker import CycleResult

__all__ = [
    "CADENCE",
    "FUNDING_STREAM",
    "FundingDocument",
    "FundingError",
    "FundingFetch",
    "FundingParseError",
    "FundingRateStore",
    "FundingRateWorker",
    "FundingReading",
    "FundingRecord",
    "SIXTY_SECONDS",
    "StampedReading",
    "parse_funding",
    "register_funding_worker",
]

#: The stream class this module serves.  §4.1's table row for funding/borrow
#: rate is the stream whose cadence is a 60-second poll rather than a feed, and
#: the spelling here is the persisted one (:class:`~nullius_ingest.streams.
#: StreamClass`), so the staging layout and the record log share it.
FUNDING_STREAM = StreamClass.FUNDING

#: The cadence §4.1's table records for this stream: one poll every 60 seconds.
#: Carried as a constant so the fact is named where it is decided, not only in
#: prose, and so the due-check turns on a named interval rather than a literal.
SIXTY_SECONDS = 60
CADENCE = "1m"

#: The envelope key holding the readings, and the keys around it — named so a
#: reader of a record file (an operator, a seal, a later audit) does not have
#: to import this module to know what it is looking at.
_DOCUMENT_KEY = "document"
_ENVELOPE_KEYS = ("stream", "sequence", "fetched_at", "source_sha256")

#: Wrapper keys under which a venue endpoint may nest its readings list — the
#: flat list and the single-object response are also accepted (see
#: :func:`parse_funding`), so this is a convenience, not a closed set.
_WRAPPER_KEYS = ("symbols", "data", "funding", "rates")

#: The due interval, as a :class:`timedelta`, so the cadence check is a single
#: comparison rather than a re-derived constant at the call site.
_DUE_INTERVAL = timedelta(seconds=SIXTY_SECONDS)

_UTC = timezone.utc


class FundingError(Exception):
    """Base for every failure this module raises.

    Raised for a document this module will not persist and for a persisted
    record it will not read: both are cases where the funding log would
    otherwise start lying about what the venue said, so both fail loudly rather
    than being approximated into a record.
    """


class FundingParseError(FundingError):
    """A funding payload is not one this module will persist.

    Raised *before* anything is written, so a poll that returned an error page,
    a rate-limit body or a truncated document never consumes a sequence number
    and never appears in the log as a poll that happened.  The message names
    what was wrong with which symbol or field, because the caller is a worker
    whose next move depends on whether the venue's shape changed or the poll
    simply failed.
    """


class FundingCorruptError(FundingError):
    """A persisted record file does not match what was written under it.

    Raised when a record file cannot be read back as the envelope it was written
    as, when its recorded sequence is not the sequence its filename claims, or
    when recomputing its document hash disagrees with the hash the envelope
    recorded.  The log is append-only and copied byte-for-byte by the seal, so a
    mismatch means the bytes on disk are not the bytes this module committed —
    corruption or tampering, either of which a reader must hear about rather
    than silently parse a wrong borrow rate out of.
    """


def _scalar_field(value: object, where: str) -> str:
    # Rate field values are persisted as the venue's own spelling.  Venues are
    # not consistent about JSON types for the same field — a funding rate
    # arrives as ``"0.0001"`` and a borrow rate as a bare ``0.00003`` — so
    # scalars are coerced to their string spelling rather than rejected, while
    # containers are refused: a nested object is a shape this module does not
    # model, and storing its ``repr`` would be a record that looks like data and
    # is not.
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
    raise FundingParseError(
        f"{where} is {type(value).__name__}; rate field values must be "
        f"scalars (the venue's own spelling is kept verbatim)"
    )


@dataclass(frozen=True)
class FundingReading:
    """One symbol's two rates at one instant: the funding rate and the borrow rate.

    ``funding_rate`` and ``borrow_rate`` are the venue's own string spellings,
    kept verbatim for the same reason exchangeInfo keeps its filter values
    verbatim — whether the venue said ``"0.0001"`` or ``"0.00010"`` is a fact
    about the venue, and re-rendering it would make an audit unable to tell a
    venue change from our own lossy parse.  The whole reading is kept — not
    just the two rates §4.1 names — is a deliberate narrowing: a funding poll
    carries a mark price, an index price and a next funding time alongside the
    two rates, but this module persists exactly the two rates the downstream
    cost and crowding paths read, so the record says precisely what it is for.
    """

    symbol: str
    funding_rate: str
    borrow_rate: str

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise FundingParseError(
                f"a funding reading must carry a non-empty symbol, "
                f"got {self.symbol!r}"
            )
        # Freeze the rates into their string spellings — a record is what the
        # venue said, and a caller mutating it in place would be editing
        # history.  They are already strings by construction; this guards a
        # caller constructing a reading directly.
        object.__setattr__(self, "funding_rate", str(self.funding_rate))
        object.__setattr__(self, "borrow_rate", str(self.borrow_rate))


@dataclass(frozen=True)
class FundingDocument:
    """One funding poll, as the per-symbol readings it carries.

    ``readings`` is the poll's readings in the venue's order — order is
    preserved rather than sorted because the venue's order is what a human
    diffing two polls will read, and nothing in the system depends on
    iteration order.  The document is what gets persisted, so it is the unit
    the content hash is taken over and the unit two polls are compared through.
    A poll with no readings is refused: an empty funding response is a
    rate-limit body, an error page or a truncated read, never a poll.
    """

    readings: Sequence[FundingReading]

    def __post_init__(self) -> None:
        readings = list(self.readings)
        if not readings:
            # Refused deliberately.  A funding response with no readings is a
            # rate-limit body, an error page or a truncated read — never a poll
            # — and persisting it would make a failed poll indistinguishable
            # from a successful one in the very log the cost path trusts for its
            # borrow rate.
            raise FundingParseError(
                "a funding document must carry at least one reading; "
                "an empty document is a failed poll, not a rate refresh"
            )
        seen: set[str] = set()
        for reading in readings:
            if not isinstance(reading, FundingReading):
                raise FundingParseError(
                    "a funding document's readings must be FundingReading "
                    f"instances, got {type(reading).__name__}"
                )
            if reading.symbol in seen:
                raise FundingParseError(
                    f"symbol {reading.symbol!r} is listed more than once; the "
                    f"document does not say which funding and borrow rate apply"
                )
            seen.add(reading.symbol)
        object.__setattr__(self, "readings", tuple(readings))

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this poll carries, in the venue's order."""
        return tuple(reading.symbol for reading in self.readings)

    def __len__(self) -> int:
        """How many readings this poll carries — its row count."""
        return len(self.readings)

    def for_symbol(self, symbol: str) -> FundingReading | None:
        """The reading for ``symbol``, or ``None`` when the poll omits it."""
        for reading in self.readings:
            if reading.symbol == symbol:
                return reading
        return None

    def canonical_bytes(self) -> bytes:
        """The document's canonical JSON bytes — the thing content-hashed.

        Canonical means readings ordered by symbol, keys sorted, and the
        tightest separators — so two polls carrying the same rates hash
        identically whatever order the venue listed its symbols in and whatever
        whitespace the transport added.  This is what makes
        :attr:`FundingRecord.source_sha256` a *content* hash: two polls that
        returned the same rates agree on it, and a poll that changed one
        ``borrow_rate`` does not.  Note the deliberate asymmetry with the
        persisted document, which keeps the venue's own order: a human diffing
        two polls reads the venue's order, while the hash answers *did the rates
        change* — and a venue that merely reordered its listing has not changed
        a single rate.
        """
        readings = [
            {
                "symbol": reading.symbol,
                "funding_rate": reading.funding_rate,
                "borrow_rate": reading.borrow_rate,
            }
            for reading in sorted(self.readings, key=lambda r: r.symbol)
        ]
        return json.dumps(
            {"document": readings},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def source_sha256(self) -> str:
        """The sha256 of :meth:`canonical_bytes` — the document's identity."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _parse_reading(entry: object, index: int) -> FundingReading:
    if not isinstance(entry, Mapping):
        raise FundingParseError(
            f"readings[{index}] is {type(entry).__name__}; expected an object"
        )
    symbol = entry.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise FundingParseError(
            f"readings[{index}] has no non-empty 'symbol' string "
            f"(got {symbol!r})"
        )
    if "funding_rate" not in entry:
        raise FundingParseError(
            f"{symbol} readings[{index}] has no 'funding_rate' field"
        )
    if "borrow_rate" not in entry:
        raise FundingParseError(
            f"{symbol} readings[{index}] has no 'borrow_rate' field"
        )
    return FundingReading(
        symbol=symbol,
        funding_rate=_scalar_field(
            entry["funding_rate"], f"{symbol} readings[{index}].funding_rate"
        ),
        borrow_rate=_scalar_field(
            entry["borrow_rate"], f"{symbol} readings[{index}].borrow_rate"
        ),
    )


def _as_reading_list(body: object) -> Sequence[object]:
    # The readings may arrive as a bare list, nested under one of the common
    # wrapper keys, or as a single-symbol response (a mapping that is itself one
    # reading).  Looked for in this order so a bare list is never mistaken for a
    # wrapper, and a single-object response is never mistaken for a wrapper: the
    # wrapper keys are checked only when the object is not already a reading.
    if isinstance(body, list):
        return body
    if isinstance(body, Mapping):
        for key in _WRAPPER_KEYS:
            nested = body.get(key)
            if isinstance(nested, list):
                return nested
        if "symbol" in body:
            # The single-object spelling some endpoints use
            # (``/fapi/v1/premiumIndex?symbol=BTCUSDT``).
            return [body]
    raise FundingParseError(
        "funding payload has no readings list; the document is not a rate "
        "response"
    )


def parse_funding(document: object) -> FundingDocument:
    """Parse a funding payload into a :class:`FundingDocument`.

    Accepts the venue's response object as decoded JSON — either the readings
    list itself (``[{...}, {...}]``), a wrapper some endpoints use
    (``{"symbols": [...]}``), a single-symbol response
    (``{"symbol": "BTCUSDT", "funding_rate": ..., "borrow_rate": ...}``), or an
    already-parsed :class:`FundingDocument` — and refuses anything that is not a
    well-formed set of readings with :class:`FundingParseError`.

    Strict about the shape this system owns: each reading must name its symbol
    and carry both a funding rate and a borrow rate, a symbol must not be listed
    twice (a duplicate makes "the borrow rate for BTCUSDT" ambiguous, and
    picking one arbitrarily would be a silent choice between two different
    carry adjustments), and the poll must carry at least one reading.  Tolerant
    where the venue is free: a reading may carry a mark price, an index price or
    a next funding time alongside the two rates, and they are ignored — this
    module persists exactly the two rates the downstream paths read.
    """
    if isinstance(document, FundingDocument):
        return document
    if isinstance(document, (bytes, bytearray, str)):
        try:
            decoded = json.loads(document)
        except ValueError as exc:
            raise FundingParseError(
                f"funding payload is not valid JSON: {exc}"
            ) from exc
    else:
        decoded = document

    entries = _as_reading_list(decoded)
    readings = [_parse_reading(entry, index) for index, entry in enumerate(entries)]
    return FundingDocument(readings=readings)


#: A fetch: return the venue's funding response, as JSON bytes, a JSON string, a
#: decoded mapping/list, or an already-parsed document.
#:
#: The seam the deployment's REST client fills.  This member ships no HTTP
#: client — like the exchangeInfo worker, which is handed its fetch rather than
#: owning one — so the venue's auth, rate limits and retry policy stay the
#: stream worker's business, and the store stays testable without a network.
#: Whatever the fetch returns is parsed before anything is written, so a failed
#: poll never consumes a sequence.
FundingFetch = Callable[[], Union[bytes, str, Sequence, Mapping, FundingDocument]]


@dataclass(frozen=True)
class StampedReading:
    """A :class:`FundingReading` pinned to the instant its poll was fetched.

    The reading carries only the two rates and the symbol; the instant is the
    poll's :attr:`FundingRecord.fetched_at`.  Split so the in-document reading
    (:class:`FundingReading`) stays a pure rate record while the time-series
    reader — the borrow-cost path, the crowding proxy — gets the rate *and* the
    as-of time it keys the series on.  ``reading_time`` is timezone-aware, the
    honest instant the poll happened.
    """

    symbol: str
    funding_rate: str
    borrow_rate: str
    reading_time: datetime

    @classmethod
    def stamp(cls, reading: FundingReading, when: datetime) -> "StampedReading":
        """Pin ``reading`` to ``when`` — the poll instant the record carries."""
        return cls(
            symbol=reading.symbol,
            funding_rate=reading.funding_rate,
            borrow_rate=reading.borrow_rate,
            reading_time=when,
        )


@dataclass(frozen=True)
class FundingRecord:
    """One persisted poll: the sequence it landed under and the rates it carried.

    ``sequence`` is the record's position in the stream's append-only log —
    ``1`` for the first poll, then ``2, 3, ...`` — and, because the log is
    feature 28's staging area, it is also the sequence of the batch the envelope
    bytes were committed as.  ``fetched_at`` is when the poll happened (UTC,
    timezone-aware): the durable fact the 60-second cadence is decided from, so
    a restarted process knows whether it is owed a poll without asking the
    exchange again, and the instant every reading in the record is stamped with.

    Two hashes, deliberately distinct: ``source_sha256`` is over the *document*
    and answers "did the rates change?"; ``payload_sha256`` is over the *bytes
    written* — the envelope and the document together — and is the file's
    identity, the same value the seal's MANIFEST will record for it.  ``path``
    names the ``<sequence>.bin`` the bytes were committed to, so a seal or an
    operator can point at the exact artifact; it is never written through,
    because the only way to add a record is another
    :meth:`FundingRateStore.record`.
    """

    sequence: int
    fetched_at: datetime
    document: FundingDocument
    source_sha256: str
    payload_sha256: str
    path: Path

    @property
    def reading_count(self) -> int:
        """How many readings this record carries — its row count."""
        return len(self.document)

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols this record carries, in the venue's order."""
        return self.document.symbols

    def reading(self, symbol: str) -> StampedReading | None:
        """The reading for ``symbol``, stamped with this poll's instant, or ``None``."""
        found = self.document.for_symbol(symbol)
        return None if found is None else StampedReading.stamp(found, self.fetched_at)

    def rates(self, symbol: str) -> tuple[str, str] | None:
        """This record's ``(funding_rate, borrow_rate)`` for ``symbol``, or ``None``.

        ``None`` when the record omits the symbol: "the venue did not list this
        symbol in this poll" is a fact the reader needs, distinct from any
        default the cost path must never be handed.
        """
        found = self.document.for_symbol(symbol)
        return None if found is None else (found.funding_rate, found.borrow_rate)

    def stamped_readings(self) -> tuple[StampedReading, ...]:
        """Every reading in this record, pinned to this poll's instant."""
        return tuple(StampedReading.stamp(r, self.fetched_at) for r in self.document.readings)


class FundingRateStore:
    """The append-only log of funding polls under the staging area.

    Records live at ``<lake>/staging/funding/<sequence>.bin``, one file per
    poll, committed through feature 28's
    :class:`~nullius_ingest.staging.StagingArea` — so a record is written once,
    atomically (temp file, ``fsync``, ``rename``), and never rewritten: the
    underlying batch store refuses a second batch at a sequence it already
    holds.  *Persisting each poll's rows, retained permanently* is therefore the
    store's structure rather than its discipline, and a reader can trust that
    sequence ``n``'s bytes today are the bytes sequence ``n`` was committed with
    — and that no earlier record is ever dropped, because the staging area is
    written once and copied by the seal, never expired by a retention window.

    The area is also where the seal looks.  §4.2's snapshot layout carries a
    ``borrow/`` directory, and this stream's staging log is what a seal copies
    into it, so the permanent history becomes part of the sealed,
    content-addressed record instead of a sidecar that a replay would have to
    reconstruct from live requests — which it could not do honestly, since a
    record describes rates the venue quoted at an instant that has passed.

    Construction reads whatever a prior run left on disk, so a restarted process
    knows the last poll it persisted without a network call — the same
    seed-from-what-is-durable moment the resume watermark gives a restarted
    worker.  A store is one-writer-per-stream, like the exchangeInfo store: the
    60-second cadence means one poll at a time, and a second concurrent appender
    would race for the same sequence and be refused by the batch store rather
    than silently overwriting.
    """

    def __init__(self, staging: StagingArea) -> None:
        if not isinstance(staging, StagingArea):
            raise TypeError(
                f"the funding store writes into a StagingArea, "
                f"got {type(staging).__name__}"
            )
        self._staging = staging

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "FundingRateStore":
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
        return self._staging.path_for(FUNDING_STREAM)

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
        document: Union[bytes, str, Sequence, Mapping, FundingDocument],
        *,
        fetched_at: datetime,
    ) -> FundingRecord:
        """Persist one poll as the next record; never overwrite a prior one.

        The document is parsed and validated *first*, so a failed poll consumes
        no sequence number and leaves the log untouched; then it is written as
        the next record — ``current + 1`` — into the stream's append-only
        staging log.  The previous records are not read, moved or rewritten:
        adding a record is an append, and the store's duplicate-sequence refusal
        means this method has no code path that could overwrite one.

        ``fetched_at`` is required and must be timezone-aware: the 60-second
        cadence is decided from it, and a naive timestamp would make "how long
        ago was that poll?" unanswerable at exactly the boundary the rule turns
        on.  The store does not read a clock of its own — the caller that polled
        owns the time the poll happened.
        """
        parsed = parse_funding(document)
        _require_aware(fetched_at, "fetched_at")

        sequence = self._staging.current(FUNDING_STREAM) + 1
        envelope = {
            "stream": str(FUNDING_STREAM),
            "sequence": sequence,
            "fetched_at": _isoformat_utc(fetched_at),
            "source_sha256": parsed.source_sha256,
            _DOCUMENT_KEY: [
                {
                    "symbol": reading.symbol,
                    "funding_rate": reading.funding_rate,
                    "borrow_rate": reading.borrow_rate,
                }
                for reading in parsed.readings
            ],
        }
        payload = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        batch = self._staging.append(
            FUNDING_STREAM, payload=payload, rows=len(parsed)
        )
        return FundingRecord(
            sequence=batch.sequence,
            fetched_at=fetched_at.astimezone(_UTC),
            document=parsed,
            source_sha256=parsed.source_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            path=batch.path,
        )

    # -- Reading --------------------------------------------------------------

    def records(self) -> tuple[FundingRecord, ...]:
        """Every persisted record, oldest first.

        Read back from the staging log in ascending sequence order, each
        envelope verified against the sequence its filename claims and the
        document hash it recorded — so a reader gets either the record that was
        committed or a clear :class:`FundingCorruptError`, never a
        plausible-looking record assembled from damaged bytes.
        """
        return tuple(
            self._read(batch)
            for batch in self._staging.staged(FUNDING_STREAM)
        )

    def current(self) -> FundingRecord | None:
        """The most recent record, or ``None`` when no poll has been persisted.

        ``None`` is the honest answer for an empty log — a store that has never
        recorded a poll has no borrow rate to offer, and a caller that needs one
        must poll rather than be handed a default that would be exactly the
        hardcoded venue constant §4.1's "never hardcoded" rule forbids.
        """
        batches = self._staging.staged(FUNDING_STREAM)
        if not batches:
            return None
        return self._read(batches[-1])

    def previous(self) -> FundingRecord | None:
        """The record before :meth:`current`, or ``None`` when there is none.

        The comparison point a poll reports against: a worker can say whether the
        poll it just persisted changed the rates, which is the difference
        between a quiet cycle and a cycle the cost path must absorb.
        """
        batches = self._staging.staged(FUNDING_STREAM)
        if len(batches) < 2:
            return None
        return self._read(batches[-2])

    def record_at(self, sequence: int) -> FundingRecord | None:
        """The record persisted under ``sequence``, or ``None`` if never recorded.

        ``None`` distinguishes *that sequence was never recorded* from *the log
        holds a record under that number but its bytes are damaged*, which
        :meth:`records` and :meth:`current` raise for.  A caller walking the
        history — an audit asking what the borrow rate was at a past poll — gets
        the honest absence rather than an exception for a number that simply
        never happened.
        """
        self.path_for(sequence)  # validates the argument; raises on a bad one
        for batch in self._staging.staged(FUNDING_STREAM):
            if batch.sequence == sequence:
                return self._read(batch)
        return None

    def latest_reading(self, symbol: str) -> StampedReading | None:
        """The most recent record's reading for ``symbol``, stamped with its instant.

        The read a cost or crowding path performs when it needs the latest
        funding and borrow rate for that symbol: the newest record's answer for
        that symbol, or ``None`` when no record has been persisted or the newest
        one omits the symbol.  Deliberately not a fallback to an older record: a
        symbol the venue has stopped listing must not be tradeable off a stale
        rate, so an absent symbol stays absent and the caller refuses the order.
        """
        latest = self.current()
        if latest is None:
            return None
        return latest.reading(symbol)

    def latest_rates(self, symbol: str) -> tuple[str, str] | None:
        """The most recent record's ``(funding_rate, borrow_rate)`` for ``symbol``.

        The two-rate form of :meth:`latest_reading`, for a caller that wants the
        pair without unpacking a :class:`StampedReading`.  ``None`` when no
        record has been persisted or the newest record omits the symbol.
        """
        latest = self.current()
        if latest is None:
            return None
        return latest.rates(symbol)

    def _read(self, batch) -> FundingRecord:
        # Read one committed batch back into a record, verifying as it goes.
        # The three checks below are the read half of the append-only guarantee:
        # the bytes are the bytes that were committed, under the sequence the
        # filename claims, carrying the document the envelope's hash vouches for.
        # A mismatch is corruption (or tampering) on a log the cost path trusts
        # for its borrow rate, so it is raised rather than papered over.
        try:
            envelope = json.loads(batch.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FundingCorruptError(
                f"funding record {batch.sequence} is not readable as a JSON "
                f"envelope: {exc}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise FundingCorruptError(
                f"funding record {batch.sequence} is a "
                f"{type(envelope).__name__}; expected a JSON object"
            )
        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing or _DOCUMENT_KEY not in envelope:
            raise FundingCorruptError(
                f"funding record {batch.sequence} is missing "
                f"{', '.join(missing + [_DOCUMENT_KEY])}; the file is not a "
                f"record envelope this store wrote"
            )
        recorded = envelope["sequence"]
        if recorded != batch.sequence:
            raise FundingCorruptError(
                f"funding record file {batch.sequence}.bin records sequence "
                f"{recorded!r}; the file does not describe itself"
            )
        document = parse_funding(envelope[_DOCUMENT_KEY])
        recorded_hash = envelope["source_sha256"]
        if recorded_hash != document.source_sha256:
            raise FundingCorruptError(
                f"funding record {batch.sequence} records source hash "
                f"{recorded_hash!r} but its document hashes to "
                f"{document.source_sha256!r}; the file's bytes are not the "
                f"bytes that were committed"
            )
        return FundingRecord(
            sequence=batch.sequence,
            fetched_at=_parse_timestamp(envelope["fetched_at"], batch.sequence),
            document=document,
            source_sha256=document.source_sha256,
            payload_sha256=hashlib.sha256(batch.payload).hexdigest(),
            path=self.path_for(batch.sequence),
        )


def _require_aware(moment: object, what: str) -> None:
    # The 60-second cadence is decided from elapsed wall-clock time, so a naive
    # timestamp would be unsubtractable from an aware one at exactly the
    # boundary the rule turns on.  Refused here, where a caller can still fix its
    # clock handling, rather than silently assumed to be UTC and recorded wrong.
    if not isinstance(moment, datetime):
        raise TypeError(f"{what} must be a datetime, not {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{what} must be timezone-aware; a naive timestamp cannot say how "
            f"long ago a poll happened"
        )


def _isoformat_utc(moment: datetime) -> str:
    # Persisted in UTC with an explicit offset, so the record says when the poll
    # happened without the reader assuming.
    return moment.astimezone(_UTC).isoformat()


def _parse_timestamp(raw: object, sequence: int) -> datetime:
    if not isinstance(raw, str):
        raise FundingCorruptError(
            f"funding record {sequence} records fetched_at {raw!r}; expected an "
            f"ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise FundingCorruptError(
            f"funding record {sequence} records an unparseable fetched_at "
            f"{raw!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise FundingCorruptError(
            f"funding record {sequence} records a naive fetched_at {raw!r}; the "
            f"60-second cadence needs a comparable instant"
        )
    return parsed.astimezone(_UTC)


class FundingRateWorker:
    """The 60-second funding/borrow worker: poll once a minute, persist a record.

    Satisfies :class:`~nullius_ingest.worker.IngestWorker` for the ``funding``
    stream class, so the supervisor of feature 16 runs it on its own thread
    alongside every other stream and converts whatever it raises into that
    stream's own failure.  One cycle is:

    * **Due?**  Ask the store — :meth:`is_due` — whether a poll is owed.  Not
      due is a *successful* zero-row cycle, not a failure and not a skip: the
      stream is current within its window, which is the state the cadence exists
      to hold.
    * **Poll.**  Call the injected :data:`FundingFetch`.  The exchange's REST
      client, its auth and its rate limits are the deployment's business; this
      worker owns only the cadence and the persistence.
    * **Persist.**  Parse first, then record the document as the next record.  A
      failed poll — a rate-limit body, an error page, a truncated response —
      raises :class:`FundingParseError` *before* anything is written, so the
      record log never records a poll that did not happen and the cost path is
      never handed a borrow rate parsed out of an error page.

    The clock is injected (:data:`Clock`) because the 60-second rule is a fact
    about elapsed wall-clock time: a test must be able to place the worker on
    either side of a boundary without touching the wall clock, and §12 keeps
    wall-clock reads out of checked code in any case.  The default clock reads
    the system UTC time, which is what a deployment wants.

    A worker is one-writer for its stream, like the exchangeInfo worker: the
    cadence means one poll at a time, and the store's append-only commit refuses
    a racing second append at the same sequence rather than losing one.
    """

    def __init__(
        self,
        store: FundingRateStore,
        fetch: FundingFetch,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(store, FundingRateStore):
            raise TypeError(
                f"the funding worker persists into a FundingRateStore, "
                f"got {type(store).__name__}"
            )
        if not callable(fetch):
            raise TypeError(
                f"fetch must be a zero-argument callable returning the venue's "
                f"funding response, got {type(fetch).__name__}"
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
        """The one stream class this worker owns — ``funding``."""
        return FUNDING_STREAM

    @property
    def store(self) -> FundingRateStore:
        """The record log this worker appends to."""
        return self._store

    # -- Cadence --------------------------------------------------------------

    def last_fetched_at(self) -> datetime | None:
        """When the most recent persisted record was fetched, or ``None``.

        Read from the durable log rather than remembered in the process, so a
        restart knows whether it is owed a poll — which is the whole point of
        deriving the cadence from the store: the deployment table calls ingest
        restart-safe, and a cadence held in memory would poll on every restart
        and skip a cycle whenever the process happened to be down at the wrong
        moment.
        """
        latest = self._store.current()
        return None if latest is None else latest.fetched_at

    def is_due(self, *, now: Optional[datetime] = None) -> bool:
        """Whether a poll is due at ``now`` (default: the injected clock).

        Due when no record has ever been persisted — startup is simply the first
        cycle of a process over an empty store — or when the most recent record
        was fetched at least :data:`SIXTY_SECONDS` before ``now``.  Inside the
        window is not due, so a worker driven faster than the cadence does not
        spam the exchange, and a process that was down across a boundary polls on
        its next cycle rather than waiting for a timer.
        """
        moment = self._clock() if now is None else now
        _require_aware(moment, "now")
        last = self.last_fetched_at()
        if last is None:
            return True
        return (moment.astimezone(_UTC) - last.astimezone(_UTC)) >= _DUE_INTERVAL

    # -- One cycle ------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        """Run one cycle: poll and persist the rates if a poll is due.

        Returns the persisted record's sequence as the cycle's watermark, so a
        monitor sees the log advance, and ``rows_written`` as the number of
        readings the record carries.  A not-due cycle reports both as zero: no
        poll, no record, no progress to claim.
        """
        now = self._clock()
        _require_aware(now, "the clock")
        if not self.is_due(now=now):
            return CycleResult(rows_written=0, sequence=0)
        document = self._fetch()
        record = self._store.record(document, fetched_at=now)
        return CycleResult(
            rows_written=record.reading_count, sequence=record.sequence
        )


def _utc_now() -> datetime:
    """The default clock: the current UTC time, timezone-aware."""
    return datetime.now(_UTC)


def register_funding_worker(
    fetch: FundingFetch,
    store: Optional[FundingRateStore] = None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[], FundingRateWorker]:
    """Register a worker factory bound to an explicitly wired fetch.

    The operator path: hand in the REST client's fetch (and, when it is not the
    lake's staging area, the store), and this registers a worker factory bound
    to those collaborators.  Registration replaces the auto-discovered factory
    of the same class in the registry it targets — the registry's own rule, *a
    re-registered class is a revision of the same worker, never a second
    worker* — so a deployment that wires a client does not end up with two
    funding workers competing for the same sequence numbers.

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
            f"funding response, got {type(fetch).__name__}"
        )

    def build() -> FundingRateWorker:
        resolved_store = (
            store if store is not None else FundingRateStore.from_env()
        )
        return FundingRateWorker(resolved_store, fetch, clock=clock)

    # Register through a private registry by default, never the process-wide
    # one.  Registration is a *deployment* act: writing a caller's wiring into
    # the default registry would replace the auto-discovered worker for every
    # later composition in the process — including tests, which would then be
    # handed a worker bound to a store that has since vanished.  A caller that
    # genuinely means to reconfigure the running process passes the default
    # registry explicitly, which is the same opt-in
    # :func:`~nullius_ingest.registry.register_worker` already asks for.
    register_worker(
        FUNDING_STREAM,
        build,
        registry=registry if registry is not None else WorkerRegistry(),
    )
    return build


@register_worker(FUNDING_STREAM)
def build_funding_worker() -> FundingRateWorker:
    """Compose the funding worker from the environment.

    The auto-discovery path, and the one the plugin convention wants: this
    module is imported by :mod:`nullius_ingest`, the decorator fires, and
    :func:`~nullius_ingest.registry.build_default_workers` builds this worker
    into the supervisor the application factory composes.  No shared file is
    edited to make the stream exist — importing the module *is* joining the
    ingest component.

    Collaborators come from the environment the way every other ingest seam
    does: the store is the lake's staging area (:meth:`FundingRateStore.from_env`),
    so records land in the very area the seal copies out of.  The fetch has no
    environment-resolved default — this member ships no HTTP client, so the
    venue's auth, rate limits and pagination stay the deployment's business —
    and a deployment wires it with :func:`register_funding_worker`.  Until then
    the worker still composes and its cycle reports that stream's own failure,
    which is feature 16's contract: an unconfigured stream is a row in the
    report, not a component that fails to load.
    """
    return FundingRateWorker(FundingRateStore.from_env(), _unconfigured_fetch)


def _unconfigured_fetch() -> object:
    """The fetch used when a deployment has not wired a REST client yet.

    Raising here, rather than at composition time, keeps the plugin shaped the
    way feature 16 wants it: an unconfigured stream is that stream's failure in
    the report, not a component that fails to compose.
    """
    raise FundingError(
        "no funding fetch is configured; register the worker with a fetch "
        "returning the venue's funding response "
        "(nullius_ingest.register_funding_worker(fetch, store=..., "
        "registry=default_worker_registry()))"
    )
