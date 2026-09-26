"""The stream classes the ingest layer serves, one worker each.

docs/nullius-tech-architecture.md §4.1 fixes the data-layer stream table
and opens it with the rule this whole package implements: *"Separate
worker per stream class."*  The enum below is that table made executable —
each value is one stream class, and a stream class is the unit of
isolation: it names the worker that owns it, the failure that comes back
when that worker fails, and nothing else.  A failure of one value never
mentions, blocks, or halts any other value.

The values are a closed set drawn from §4.1 — the later ingest features
(klines, aggTrades, L2 diffs, derived book features, funding,
exchangeInfo) each attach one worker to one value here.  A stream class
nobody has implemented yet simply has no worker; it is not an error
state, exactly like an empty workspace is not an error state for the
module loader.

One deliberate departure from a literal one-value-per-table-row reading:
§4.1 gives the data layer **one** "Book features (derived)" row, but that
row is a *family* of derived features (depth, microprice, OFI,
cancel-replace rate, trade-size moments) rather than a single stream, and
this enum is the unit of isolation rather than the unit of documentation
— one class, one worker, enforced by the supervisor.  So each derived
family that lands takes its own value (``bookFeatures`` for feature 20's
depth ladder, ``microstructure`` for feature 21's microprice, spread and
windowed OFI, ``tradeFlow`` for feature 22's cancel-replace rate and
trade-size moments) instead of sharing one and having the second
registration silently *replace* the first.  Splitting a derived family
into its own worker is also the isolation §4.1 asks for one level up: a
failure in the trade-size reduction does not take the depth ladder down
with it.

The string values are persisted identifiers (log lines, failure records,
staging layouts), so they use the exchange-facing spellings from §4.1
(``aggTrades``, ``exchangeInfo``) and are stable for the life of the
system.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["StreamClass"]


class StreamClass(StrEnum):
    """One §4.1 stream class — the isolation unit of the ingest layer."""

    KLINES = "klines"
    """1m/1h/1d klines: REST backfill plus a websocket tail."""

    AGG_TRADES = "aggTrades"
    """Aggregated trades off the websocket feed, retained forever."""

    BOOK_DIFFS = "bookDiffs"
    """L2 book diffs at 100ms, kept under a rolling 90-day window."""

    L1_BOOK = "bookTicker"
    """L1 best bid/ask snapshots at 1s, retained forever."""

    BOOK_FEATURES = "bookFeatures"
    """Derived 1s book features computed from the L2 diffs."""

    MICROSTRUCTURE = "microstructure"
    """Derived 1s microprice, spread and windowed OFI (§4.1, feature 21)."""

    TRADE_FLOW = "tradeFlow"
    """Derived 1s cancel-replace rate and trade-size moments (§4.1, feature 22)."""

    FUNDING = "funding"
    """Funding rate and margin borrow rate, polled every 60s."""

    EXCHANGE_INFO = "exchangeInfo"
    """exchangeInfo filters, fetched daily and persisted versioned."""


def coerce_stream_class(value: object) -> StreamClass:
    """Coerce ``value`` to a :class:`StreamClass`.

    Accepts a :class:`StreamClass` (returned unchanged) or its string
    value, so callers wiring workers from configuration can pass either
    spelling.  Anything else raises :class:`TypeError` — an unknown
    stream class is a wiring bug, and wiring bugs should fail loudly at
    construction time, not quietly at ingest time.
    """
    if isinstance(value, StreamClass):
        return value
    if isinstance(value, str):
        try:
            return StreamClass(value)
        except ValueError:
            known = ", ".join(member.value for member in StreamClass)
            raise TypeError(
                f"unknown stream class {value!r}; expected one of: {known}"
            ) from None
    raise TypeError(
        f"stream class must be a StreamClass or its string value, "
        f"not {type(value).__name__}"
    )
