"""Backfill daily bars from Binance's public REST API -- ``python -m nullius_ingest.bars_backfill``.

``additions_spec_real_campaign_path.xml``, "Market Data to Sealed Snapshot"
category, feature 1: *System backfills daily bars from Binance's public REST
API into the evaluator's bars Parquet layout with* ``python -m
nullius_ingest.bars_backfill --lake LAKE --first YYYY-MM-DD --last YYYY-MM-DD
(--symbols S,S,... | --top N)`` *and displays one JSON line per symbol and a
summary line, with no API key.*  This is the first producer into the §4.2
layout :mod:`snapshot.seal` later seals: nothing before this module wrote a
``bars/`` partition any sealed snapshot could serve.

**The write shape is the evaluator's, not this module's own.**  Every bar
lands at ``<lake>/staging/bars/symbol=<S>/date=<D>/part-0.parquet``, one row
per symbol and day, because that is exactly the layout
``orchestrator._context._closes`` and ``evaluator._align`` read: a ``symbol``
column, an ``open_time`` timestamp (the candle's day), and a ``close`` carried
in the venue's own string spelling — the same verbatim-string convention
:mod:`nullius_ingest.klines` keeps for every other OHLCV field, so a backfilled
bar and a tail-ingested kline are indistinguishable once sealed.  Candle
parsing is not re-implemented here: each page of Binance's raw kline array is
handed to :func:`nullius_ingest.klines.parse_klines`, so this module and the
websocket tail share one definition of what a candle is — including the
index-8 trade-count fix this feature also lands (see ``klines.py``).

**Positive closes only.**  A non-positive close cannot be divided by for a
forward return (``evaluator._align``'s own refusal), so a candle whose close
is zero, negative or unparseable is skipped before it is written, and the
skip is counted rather than silently dropped — the per-symbol JSON line
reports exactly how many a run left out.

**Symbol selection.**  ``--symbols`` names an explicit, caller-ordered list.
``--top N`` instead asks Binance which pairs to backfill: every ``TRADING``
spot symbol quoted in USDT, with ``isSpotTradingAllowed``, excluding a
stablecoin base (a stablecoin-to-stablecoin pair carries no price signal) and
a leveraged-token base (``UP``/``DOWN``/``BULL``/``BEAR`` tokens track a
multiple of an index, not a tradable spot pair in the sense a momentum or
mean-reversion signal reasons about) — ranked by the 24-hour quote volume
Binance's own ticker reports, descending, and truncated to the top ``N``.
This is a REST-only snapshot of *today's* listing: a symbol delisted before
today never appears, which is exactly why ``universe.json`` records
``survivorship_free: false`` for this source (feature 2's archive mode is the
survivorship-free counterpart, out of this feature's scope).

**Universe provenance, beside staging, never inside it.**  ``universe.json``
is written at ``<lake>/universe.json`` — a sibling of ``staging/``, the same
place :mod:`snapshot.seal` already knows to read it from and never walks into
the sealed tree.  It records: ``source`` (``"binance-rest"``), the
``selection_rule`` prose (explicit list or the top-N rule actually applied),
``fetched_at`` (when this run asked Binance, UTC), ``first``/``last`` (the
requested date range), ``symbols`` (every symbol this run resolved, in
selection order), and ``survivorship_free`` (always ``false`` here).

**Paging, pacing and backing off.**  One request never asks for more than
:data:`PAGE_SIZE` (1000) daily candles — Binance's own per-request cap — so a
wide ``--first``/``--last`` range is split into contiguous day-chunks, each
its own request.  A small delay (:data:`DEFAULT_DELAY_SECONDS`) follows every
request, successful or not, so a backfill over many symbols does not lean on
the venue.  HTTP 418 ("I'm a teapot", Binance's hard ban signal) and 429
(rate limited) are retried after the delay the venue's own ``Retry-After``
header names, up to :data:`MAX_RETRIES` attempts; past the bound the symbol
is refused by name, in that symbol's own JSON line, rather than silently
losing its data or taking the whole run down with it — one symbol's refusal
is reported and the next symbol still runs.

**Idempotent by construction.**  Every byte this module writes is a pure
function of what Binance returned for a ``(symbol, date)``: there is no
run-local nonce, no embedded wall-clock read inside a bar's bytes, so
re-running with the same arguments against the same venue content rewrites
the identical ``part-0.parquet`` files.  ``universe.json`` is the one
exception by design — ``fetched_at`` is when *that run* asked, which is the
provenance fact an operator wants to know about each run, not a value a
rerun should launder away.

**The fetch is injected, exactly as every other ingest stream takes its
collaborators.**  :data:`BinanceFetch` is a ``(path, params) -> HttpResponse``
callable; :func:`urllib_fetch` is the default, speaking to
``https://data-api.binance.vision/api/v3`` with the standard library's
``urllib`` and no API key (every endpoint this module calls is public market
data).  A test hands in a recorded fixture and never touches a socket.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .klines import KlineParseError, KlineRow, parse_klines

__all__ = [
    "BARS_STREAM",
    "DEFAULT_BASE_URL",
    "DEFAULT_DELAY_SECONDS",
    "EXIT_OK",
    "EXIT_REFUSED",
    "LEVERAGED_SUFFIXES",
    "MAX_RETRIES",
    "PAGE_SIZE",
    "STABLECOIN_BASES",
    "UNIVERSE_FILENAME",
    "BarsBackfillError",
    "BinanceFetch",
    "HttpResponse",
    "SymbolResult",
    "backfill_bars",
    "main",
    "select_top_symbols",
    "urllib_fetch",
]

#: The partition directory name the evaluator reads bars from (§4.2).
BARS_STREAM = "bars"

#: Binance's public market-data mirror; every endpoint this module calls is
#: public (klines, exchangeInfo, ticker/24hr) and needs no API key.
DEFAULT_BASE_URL = "https://data-api.binance.vision/api/v3"

#: Binance's own per-request cap on candles — the module never asks for more.
PAGE_SIZE = 1000

#: A small pause after every request, successful or not, so a backfill over
#: many symbols and many pages does not lean on the venue.
DEFAULT_DELAY_SECONDS = 0.2

#: How many times a 418/429 is retried (after its own Retry-After delay)
#: before the symbol is refused.
MAX_RETRIES = 5

#: Stablecoin bases excluded from ``--top N``: a stablecoin-to-USDT pair
#: carries no price signal a momentum or mean-reversion study would want.
STABLECOIN_BASES = frozenset(
    {
        "USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD", "USDD", "PAX",
        "GUSD", "SUSD", "EURI", "AEUR", "USTC", "UST",
    }
)

#: Leveraged-token base suffixes excluded from ``--top N`` (e.g. ``BTCUP``,
#: ``ETHBEAR``): these track a multiple of an index, not a spot position.
LEVERAGED_SUFFIXES: tuple[str, ...] = ("UP", "DOWN", "BULL", "BEAR")

#: The file this module writes beside ``staging/``, never inside it.
UNIVERSE_FILENAME = "universe.json"

EXIT_OK = 0
EXIT_REFUSED = 1

_UTC = UTC
_INTERVAL = "1d"


class BarsBackfillError(Exception):
    """A backfill request could not be honoured.

    Raised for a malformed argument (a bad date, neither or both of
    ``--symbols``/``--top`` given), an unparseable venue response, an HTTP
    failure that is not a retryable rate limit, or a 418/429 that persisted
    past :data:`MAX_RETRIES`.  The message always names what failed and, for
    a per-symbol failure, the symbol — the operational signal an operator or
    the per-symbol JSON line reads, not a debugging aid.
    """


# -- The injectable fetch -----------------------------------------------------


@dataclass(frozen=True)
class HttpResponse:
    """One HTTP response, reduced to what the retry logic needs.

    ``status`` drives the retry decision, ``headers`` carries ``Retry-After``
    on a 418/429, and ``body`` is the raw bytes to decode as JSON on success.
    A plain value, so a test can build one by hand with no real request.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


#: The seam every Binance call goes through: a path (e.g. ``"/klines"``) and
#: its query parameters, returning the response.  :func:`urllib_fetch` is the
#: default; a test hands in a callable that returns recorded JSON and touches
#: no socket.
BinanceFetch = Callable[[str, Mapping[str, str]], HttpResponse]


def urllib_fetch(
    path: str, params: Mapping[str, str], *, base_url: str = DEFAULT_BASE_URL
) -> HttpResponse:
    """The default fetch: ``urllib`` against Binance's public data mirror.

    No API key is sent or needed — every endpoint this module calls
    (``/klines``, ``/exchangeInfo``, ``/ticker/24hr``) is public market data.
    An HTTP error status (418, 429, or anything else the venue returns) comes
    back as an :class:`HttpResponse` rather than an exception, so the retry
    logic in :func:`_request_json` is the single place that decides what an
    error status means.
    """
    query = urllib.parse.urlencode(sorted(params.items()))
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "nullius-ingest/bars_backfill"}
    )
    try:
        with urllib.request.urlopen(request) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status=exc.code, headers=dict(exc.headers or {}), body=exc.read()
        )


def _default_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _retry_after_seconds(headers: Mapping[str, str]) -> float:
    # Case-insensitive by hand: HttpResponse carries whatever casing the
    # transport handed it (urllib's HTTPMessage is already case-insensitive,
    # but a test's plain dict is not), and Retry-After is the one header this
    # module reads.
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return max(float(value), 0.0)
            except (TypeError, ValueError):
                return 1.0
    return 1.0


def _request_json(
    fetch: BinanceFetch,
    path: str,
    params: Mapping[str, str],
    *,
    sleep: Callable[[float], None],
    what: str,
) -> object:
    """Call ``fetch``, retrying a 418/429 up to :data:`MAX_RETRIES` times.

    Parses and returns the JSON body on a 200.  Every other status raises
    :class:`BarsBackfillError` naming ``what`` (the caller's own description
    of the request, e.g. ``"klines for BTCUSDT"``) — a 418/429 past the retry
    bound, or any other non-200 status, immediately.
    """
    attempt = 0
    while True:
        response = fetch(path, params)
        sleep(DEFAULT_DELAY_SECONDS)
        if response.status == 200:
            try:
                return json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise BarsBackfillError(
                    f"{what}: response body is not valid JSON: {exc}"
                ) from exc
        if response.status in (418, 429):
            attempt += 1
            if attempt > MAX_RETRIES:
                raise BarsBackfillError(
                    f"{what} refused: HTTP {response.status} persisted past "
                    f"{MAX_RETRIES} retries"
                )
            sleep(_retry_after_seconds(response.headers))
            continue
        raise BarsBackfillError(
            f"{what} failed: HTTP {response.status}: {response.body[:200]!r}"
        )


# -- Symbol selection ----------------------------------------------------------


def _is_leveraged_base(base: str) -> bool:
    return any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES)


def select_top_symbols(
    fetch: BinanceFetch, top: int, *, sleep: Callable[[float], None]
) -> tuple[str, ...]:
    """The top ``top`` TRADING USDT spot pairs by 24h quote volume.

    Two calls: ``exchangeInfo`` names which symbols are eligible (``TRADING``,
    quoted in USDT, spot-tradable, no stablecoin or leveraged-token base), and
    ``ticker/24hr`` names their volumes.  Ranked by quote volume descending,
    symbol name ascending to break a tie deterministically, then truncated.
    A symbol ``exchangeInfo`` lists but ``ticker/24hr`` omits is ranked at
    zero volume rather than dropped — an absent ticker is not an argument for
    silently shrinking the eligible set.
    """
    if not isinstance(top, int) or isinstance(top, bool) or top <= 0:
        raise BarsBackfillError(f"--top must be a positive integer, got {top!r}")

    info = _request_json(fetch, "/exchangeInfo", {}, sleep=sleep, what="exchangeInfo")
    symbols_info = info.get("symbols") if isinstance(info, Mapping) else None
    if not isinstance(symbols_info, list):
        raise BarsBackfillError(
            "exchangeInfo response carries no 'symbols' list; the document is "
            "not an exchangeInfo response"
        )

    eligible: dict[str, None] = {}
    for entry in symbols_info:
        if not isinstance(entry, Mapping):
            continue
        symbol = entry.get("symbol")
        base = entry.get("baseAsset")
        quote = entry.get("quoteAsset")
        status = entry.get("status")
        spot_allowed = entry.get("isSpotTradingAllowed", True)
        if not (isinstance(symbol, str) and isinstance(base, str) and isinstance(quote, str)):
            continue
        if quote != "USDT" or status != "TRADING" or not spot_allowed:
            continue
        if base in STABLECOIN_BASES or _is_leveraged_base(base):
            continue
        eligible.setdefault(symbol, None)

    if not eligible:
        raise BarsBackfillError(
            "no eligible TRADING USDT spot pairs were found in exchangeInfo "
            "after excluding stablecoin bases and leveraged tokens"
        )

    tickers = _request_json(
        fetch, "/ticker/24hr", {}, sleep=sleep, what="ticker/24hr"
    )
    if not isinstance(tickers, list):
        raise BarsBackfillError(
            "ticker/24hr response is not a list; the document is not a "
            "24hr ticker response"
        )
    volumes: dict[str, float] = dict.fromkeys(eligible, 0.0)
    for entry in tickers:
        if not isinstance(entry, Mapping):
            continue
        symbol = entry.get("symbol")
        if symbol not in eligible:
            continue
        try:
            volumes[symbol] = float(entry.get("quoteVolume", 0.0))
        except (TypeError, ValueError):
            volumes[symbol] = 0.0

    ranked = sorted(volumes.items(), key=lambda pair: (-pair[1], pair[0]))
    return tuple(symbol for symbol, _ in ranked[:top])


# -- Fetching and writing one symbol's candles --------------------------------


def _coerce_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise BarsBackfillError(
                f"{value!r} is not an ISO-8601 date (YYYY-MM-DD)"
            ) from exc
    raise BarsBackfillError(
        f"a date must be a date or an ISO-8601 string, got {type(value).__name__}"
    )


def _date_to_ms(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=_UTC).timestamp() * 1000)


def _date_chunks(first: date, last: date, size: int) -> Iterator[tuple[date, date]]:
    """Split ``[first, last]`` into contiguous, non-overlapping day-chunks.

    Each chunk spans at most ``size`` days — Binance's own per-request page
    cap — so a backfill over a range wider than one page never asks for more
    candles than the venue will return from a single request.
    """
    current = first
    while current <= last:
        chunk_end = min(current + timedelta(days=size - 1), last)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def _fetch_symbol_rows(
    fetch: BinanceFetch,
    symbol: str,
    first: date,
    last: date,
    *,
    sleep: Callable[[float], None],
) -> tuple[KlineRow, ...]:
    rows: list[KlineRow] = []
    for chunk_start, chunk_end in _date_chunks(first, last, PAGE_SIZE):
        params = {
            "symbol": symbol,
            "interval": _INTERVAL,
            "startTime": str(_date_to_ms(chunk_start)),
            "endTime": str(_date_to_ms(chunk_end + timedelta(days=1)) - 1),
            "limit": str(PAGE_SIZE),
        }
        document = _request_json(
            fetch, "/klines", params, sleep=sleep, what=f"klines for {symbol}"
        )
        if isinstance(document, list) and not document:
            # An honestly empty page (the symbol has no candles in this
            # chunk, e.g. it listed partway through the range) — not a
            # parse failure, just nothing to add.
            continue
        try:
            batch = parse_klines(document, _INTERVAL, symbol=symbol)
        except KlineParseError as exc:
            raise BarsBackfillError(
                f"{symbol}: could not parse the klines response: {exc}"
            ) from exc
        rows.extend(batch.candles)
    return tuple(rows)


def _close_as_float(raw: str) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _row_table(row: KlineRow) -> pa.Table:
    # The evaluator's own required columns (symbol, open_time, close) plus
    # the rest of the candle, all in the venue's verbatim string spelling —
    # the same convention klines.py keeps for the tail-ingested series, so a
    # backfilled bar and a tail-ingested kline are indistinguishable once
    # sealed.
    timestamp = pa.timestamp("us", tz="UTC")
    return pa.table(
        {
            "symbol": [row.symbol],
            "open_time": pa.array([row.open_time], type=timestamp),
            "close_time": pa.array([row.close_time], type=timestamp),
            "open": [row.open],
            "high": [row.high_price],
            "low": [row.low_price],
            "close": [row.close],
            "volume": [row.volume],
            "trade_count": pa.array([row.trade_count], type=pa.int64()),
        }
    )


def _write_bars(lake: Path, symbol: str, rows: Sequence[KlineRow]) -> tuple[int, int]:
    """Write one part-0.parquet per day; return (rows_written, skipped)."""
    written = 0
    skipped = 0
    bars_root = lake / "staging" / BARS_STREAM
    for row in rows:
        close_value = _close_as_float(row.close)
        if close_value is None or close_value <= 0.0:
            skipped += 1
            continue
        day = row.open_time.astimezone(_UTC).date()
        partition = bars_root / f"symbol={symbol}" / f"date={day.isoformat()}"
        partition.mkdir(parents=True, exist_ok=True)
        pq.write_table(_row_table(row), partition / "part-0.parquet")
        written += 1
    return written, skipped


# -- universe.json -------------------------------------------------------------


def _write_universe(
    lake: Path,
    *,
    source: str,
    selection_rule: str,
    fetched_at: datetime,
    first: date,
    last: date,
    symbols: Sequence[str],
    survivorship_free: bool,
) -> None:
    payload = {
        "source": source,
        "selection_rule": selection_rule,
        "fetched_at": fetched_at.astimezone(_UTC).isoformat(),
        "first": first.isoformat(),
        "last": last.isoformat(),
        "symbols": list(symbols),
        "survivorship_free": survivorship_free,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    (lake / UNIVERSE_FILENAME).write_text(text, encoding="utf-8")


def _utc_now() -> datetime:
    return datetime.now(_UTC)


# -- The result and the orchestration -----------------------------------------


@dataclass(frozen=True)
class SymbolResult:
    """One symbol's outcome — the unit the per-symbol JSON line reports."""

    symbol: str
    status: str  # "ok" or "error"
    rows_written: int = 0
    skipped_non_positive_close: int = 0
    error: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"symbol": self.symbol, "status": self.status}
        if self.status == "ok":
            payload["rows_written"] = self.rows_written
            payload["skipped_non_positive_close"] = self.skipped_non_positive_close
        else:
            payload["error"] = self.error
        return payload


def _dedupe_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for symbol in symbols:
        symbol = symbol.strip()
        if symbol:
            seen.setdefault(symbol, None)
    if not seen:
        raise BarsBackfillError("--symbols must name at least one non-empty symbol")
    return tuple(seen)


def backfill_bars(
    lake: str | Path,
    first: str | date,
    last: str | date,
    *,
    symbols: Sequence[str] | None = None,
    top: int | None = None,
    fetch: BinanceFetch | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[SymbolResult, ...]:
    """Backfill daily bars for every resolved symbol; return each one's result.

    Exactly one of ``symbols`` or ``top`` must be given.  Writes
    ``<lake>/staging/bars/symbol=<S>/date=<D>/part-0.parquet`` for every
    positive-close candle found in ``[first, last]`` and
    ``<lake>/universe.json`` recording the run's provenance — written even
    when one or more symbols failed, because the universe definition names
    what was *asked for*, not only what happened to succeed.

    A symbol whose fetch fails (an unparseable response, a non-retryable HTTP
    status, or a 418/429 past :data:`MAX_RETRIES`) is reported as that
    symbol's own error result rather than aborting the run — every other
    symbol still backfills.
    """
    lake_path = Path(lake).expanduser()
    lake_path.mkdir(parents=True, exist_ok=True)
    first_date = _coerce_date(first)
    last_date = _coerce_date(last)
    if first_date > last_date:
        raise BarsBackfillError(
            f"--first {first_date.isoformat()} is after --last "
            f"{last_date.isoformat()}"
        )
    if (symbols is None) == (top is None):
        raise BarsBackfillError(
            "exactly one of --symbols or --top must be given"
        )

    resolved_fetch = fetch if fetch is not None else urllib_fetch
    resolved_sleep = sleep if sleep is not None else _default_sleep
    resolved_clock = clock if clock is not None else _utc_now

    if symbols is not None:
        resolved_symbols = _dedupe_symbols(symbols)
        selection_rule = f"explicit symbols: {', '.join(resolved_symbols)}"
    else:
        resolved_symbols = select_top_symbols(resolved_fetch, top, sleep=resolved_sleep)
        selection_rule = (
            f"top {top} TRADING USDT spot pairs by 24h quote volume, "
            "excluding stablecoin bases and leveraged tokens"
        )

    results: list[SymbolResult] = []
    for symbol in resolved_symbols:
        try:
            rows = _fetch_symbol_rows(
                resolved_fetch, symbol, first_date, last_date, sleep=resolved_sleep
            )
            written, skipped = _write_bars(lake_path, symbol, rows)
            results.append(
                SymbolResult(
                    symbol=symbol,
                    status="ok",
                    rows_written=written,
                    skipped_non_positive_close=skipped,
                )
            )
        except BarsBackfillError as exc:
            results.append(SymbolResult(symbol=symbol, status="error", error=str(exc)))

    _write_universe(
        lake_path,
        source="binance-rest",
        selection_rule=selection_rule,
        fetched_at=resolved_clock(),
        first=first_date,
        last=last_date,
        symbols=resolved_symbols,
        survivorship_free=False,
    )
    return tuple(results)


# -- The command line ----------------------------------------------------------


def _parse_symbols_arg(raw: str) -> tuple[str, ...]:
    return _dedupe_symbols(raw.split(","))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m nullius_ingest.bars_backfill",
        description=(
            "Backfill daily bars from Binance's public REST API into the "
            "evaluator's bars Parquet layout, with no API key."
        ),
    )
    parser.add_argument("--lake", required=True, metavar="LAKE", help="the lake root")
    parser.add_argument(
        "--first", required=True, metavar="YYYY-MM-DD", help="first day, inclusive"
    )
    parser.add_argument(
        "--last", required=True, metavar="YYYY-MM-DD", help="last day, inclusive"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbols", metavar="S,S,...", help="an explicit symbol list")
    group.add_argument(
        "--top", type=int, metavar="N", help="the top N symbols by 24h quote volume"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    emit: Callable[[str], object] = print,
    fetch: BinanceFetch | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """``python -m nullius_ingest.bars_backfill --lake LAKE --first D --last D (--symbols S,S,... | --top N)``.

    Prints one JSON line per symbol (its rows written and skipped, or its
    error) and one summary JSON line, through ``emit``.  Returns
    :data:`EXIT_OK` when every symbol backfilled; :data:`EXIT_REFUSED` when an
    argument was invalid (nothing is written) or at least one symbol's own
    result carries an error (every other symbol's data is still written).
    """
    arguments = _build_parser().parse_args(argv)
    symbols = _parse_symbols_arg(arguments.symbols) if arguments.symbols else None

    try:
        results = backfill_bars(
            arguments.lake,
            arguments.first,
            arguments.last,
            symbols=symbols,
            top=arguments.top,
            fetch=fetch,
            sleep=sleep,
            clock=clock,
        )
    except BarsBackfillError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    had_error = False
    total_written = 0
    total_skipped = 0
    for result in results:
        emit(json.dumps(result.to_payload()))
        if result.status == "error":
            had_error = True
        else:
            total_written += result.rows_written
            total_skipped += result.skipped_non_positive_close

    emit(
        json.dumps(
            {
                "symbols": len(results),
                "failed": sum(1 for r in results if r.status == "error"),
                "rows_written": total_written,
                "skipped_non_positive_close": total_skipped,
            }
        )
    )
    return EXIT_REFUSED if had_error else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
