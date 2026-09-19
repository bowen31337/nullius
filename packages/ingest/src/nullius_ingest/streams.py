"""The stream classes the ingest layer serves, one worker each.

docs/nullius-tech-architecture.md §4.1 fixes the data-layer stream table
and opens it with the rule this whole package implements: *"Separate
worker per stream class."*  The enum below is that table made executable —
each value is one stream class, and a stream class is the unit of
isolation: it names the worker that owns it, the failure that comes back
when that worker fails, and nothing else.  A failure of one value never
mentions, blocks, or halts any other value.

The values are deliberately a closed set taken verbatim from §4.1 — the
later ingest features (klines, aggTrades, L2 diffs, derived book
features, funding, exchangeInfo) each attach one worker to one value
here.  A stream class nobody has implemented yet simply has no worker;
it is not an error state, exactly like an empty workspace is not an
error state for the module loader.

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

    BOOK_FEATURES = "bookFeatures"
    """Derived 1s book features computed from the L2 diffs."""

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
