"""Backfill daily bars from Binance -- ``python -m nullius_ingest.bars_backfill``.

``additions_spec_real_campaign_path.xml``, "Market Data to Sealed Snapshot"
category, feature 1: *System backfills daily bars from Binance's public REST
API into the evaluator's bars Parquet layout with* ``python -m
nullius_ingest.bars_backfill --lake LAKE --first YYYY-MM-DD --last YYYY-MM-DD
(--symbols S,S,... | --top N)`` *and displays one JSON line per symbol and a
summary line, with no API key.*  This is the first producer into the §4.2
layout :mod:`snapshot.seal` later seals: nothing before this module wrote a
``bars/`` partition any sealed snapshot could serve.  Feature 2 adds a second
source, ``--source archive`` (see below), to the same command and the same
layout.

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

**Feature 2, ``--source archive``: the survivorship-free counterpart.**  The
REST source above only ever lists *today's* ``exchangeInfo``, so a symbol
Binance delisted before the run can never appear — exactly why its
``universe.json`` says ``survivorship_free: false``.  ``--source archive``
instead reads Binance's public data archive
(``https://data.binance.vision``, spot monthly ``1d`` klines), which keeps
every symbol's history for as long as it ever traded, dead names included.
PRD §C1's bias-free universe comes from this mode, and its ``universe.json``
records ``survivorship_free: true``.

* *Discovery (``--top N`` only).*  The archive's S3-compatible bucket lists
  its own keys; this module pages through
  ``data/spot/monthly/klines/`` with no delimiter and reads every
  ``<Contents><Key>`` entry, which names a symbol, a month and
  nothing else (:func:`_list_archive_months`).  A key whose symbol does not
  end in ``USDT`` is dropped.  What is left is, per USDT symbol, every month
  the archive has ever held for it — live or dead, because the archive never
  forgets a month it once published.  ``--symbols`` skips this discovery
  entirely: a caller naming symbols already knows what it wants, so each
  named symbol's months are probed directly (see below), and a month that
  turns out not to exist is simply not there, not an error.
* *One month, one file pair.*  A month's candles live at
  ``<symbol>/1d/<symbol>-1d-<year>-<month>.zip``, and every such zip has a
  sibling ``.CHECKSUM`` naming its sha256 in the standard ``sha256sum``
  output line.  Before a zip's rows are used, this module fetches both, hashes
  the zip's bytes, and compares — a mismatch refuses with
  :class:`BarsBackfillError`, naming the zip file, and (for ``--symbols``)
  that symbol's own result carries the refusal exactly as a REST-mode HTTP
  failure would; every other symbol still backfills.  A month's zip that
  simply is not there (HTTP 404 — before the symbol listed, or after it was
  delisted) is not a failure: it is skipped, silently, because an interval
  with no data is not an interval that failed.
* *The last month the archive holds.*  Each included symbol's last available
  month is recorded (``universe.json``'s ``last_archived_month``): the true
  archive-wide last month for a ``--top N`` candidate, since discovery
  already walked its whole history; the last month this run actually
  observed data for, in-window, for an explicit ``--symbols`` entry, since
  this mode never looks past the requested window.  A reader compares that
  month against the window's last month to tell a delisted symbol from a
  live one — this module records the fact and leaves the comparison to the
  reader.
* *``--top N`` ranks by the window's own median daily quote volume* — not a
  ticker snapshot, because the archive has no ticker, only the rows
  themselves.  Every USDT symbol discovery finds with at least one month
  overlapping ``[first, last]`` is a *candidate*; each candidate's rows over
  just those overlapping months are fetched once, and the median of its
  per-day quote volume (the archive CSV's own column, kept only for this
  ranking — :class:`~nullius_ingest.klines.KlineRow` does not carry it) over
  the days actually inside ``[first, last]`` is its rank key, descending,
  symbol ascending to break a tie.  This is a *causal* rank: it is computed
  once, from the whole window and nothing past it, and is fixed at the
  window's end rather than recomputed day by day — a backtest that asks for
  the same window twice gets the same top N both times.  A candidate whose
  fetch fails (a bad checksum, an unexpected HTTP status) cannot be ranked
  and is dropped from the candidate pool rather than reported: it was never
  selected, so it is not a selected symbol's failure.
* The write layout, the per-symbol JSON line and the summary line are
  byte-for-byte feature 1's — :func:`main` does not know which source wrote
  them.

**Progress, checkpoints and failure handling (bug fix, archive mode).** A
``--top N`` archive run ranks every USDT candidate the archive has ever
listed before any of them is selected — over a wide window this is the
run's slow part, and it used to do it silently, in memory, with nothing
checkpointed.  Three changes fix that, all archive-only:

* *Progress.* Every candidate the ranking loop finishes, whether it was
  scored or dropped, prints one ``{"phase": "rank", "symbols_done": n,
  "symbols_total": m}`` line through the same ``emit`` :func:`main` passes
  everything else through, before the existing per-symbol lines.
* *The rank cache.* Once the whole candidate pool is ranked, the result
  (every candidate's symbol, median volume and archive-wide last month —
  never its candle rows, which stay cheap to refetch for only the selected
  top ``N``) is written to ``<lake>/staging-meta/rank-<first>_<last>.json``,
  keyed on the window alone so a later run asking for a different ``--top``
  over the same dates still skips the crawl.  It sits beside ``staging/``,
  not inside it, so :mod:`snapshot.seal` never touches it.
* *Per-month writes and resume.* A symbol's months (explicit or selected)
  are now fetched and written one at a time rather than held in memory
  until every symbol is done. Before fetching a month, its partitions
  (``staging/bars/symbol=<S>/date=<that month's days>``) are checked; if
  they are already there the month is skipped with no fetch at all — the
  path an interrupted run's rerun takes, picking up only the months it
  never finished. A month that fails (bad checksum, unparseable rows, a
  non-404 HTTP status) prints its own ``{"phase": "error", "symbol":
  ..., "month": ..., "error": ...}`` line and is skipped; the symbol keeps
  going rather than losing the months that already succeeded, and its own
  per-symbol line still reads ``"status": "ok"`` with a ``failed_months``
  list when at least one month wrote. The run's exit code is still
  :data:`EXIT_REFUSED` when any month failed, even for an otherwise-``"ok"``
  symbol. ``--restart`` ignores the rank cache and every already-written
  month, exactly as if the lake were empty.  An error :func:`backfill_bars`
  itself does not already turn into a one-line refusal (not
  :class:`BarsBackfillError`) is still caught once, in :func:`main`, as one
  stderr line — never a raw traceback.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .klines import KlineParseError, KlineRow, parse_klines

__all__ = [
    "ARCHIVE_BASE_URL",
    "ARCHIVE_KLINES_PREFIX",
    "ARCHIVE_LISTING_URL",
    "BARS_STREAM",
    "DEFAULT_BASE_URL",
    "DEFAULT_DELAY_SECONDS",
    "EXIT_OK",
    "EXIT_REFUSED",
    "LEVERAGED_SUFFIXES",
    "MAX_RETRIES",
    "PAGE_SIZE",
    "RANK_CACHE_DIRNAME",
    "STABLECOIN_BASES",
    "UNIVERSE_FILENAME",
    "ArchiveFetch",
    "BarsBackfillError",
    "BinanceFetch",
    "HttpResponse",
    "SymbolResult",
    "backfill_bars",
    "main",
    "select_top_symbols",
    "urllib_archive_fetch",
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

#: The directory an archive ``--top N`` run caches its rank result in, a
#: sibling of ``staging/`` and ``universe.json`` so :mod:`snapshot.seal`
#: never sees it — a checkpoint, not published data.
RANK_CACHE_DIRNAME = "staging-meta"

#: Binance's public data archive — static monthly zips, no API key, no
#: rate-limit contract (it is a CDN-fronted bucket, not the REST API).
ARCHIVE_BASE_URL = "https://data.binance.vision"

#: The archive bucket's own S3-compatible listing endpoint, used only for
#: ``--top N`` discovery — the one call this module makes that is not a plain
#: file fetch.
ARCHIVE_LISTING_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

#: Every spot monthly ``1d`` kline lives under this key prefix, as
#: ``<prefix><symbol>/1d/<symbol>-1d-<year>-<month>.zip`` (and that path's own
#: ``.CHECKSUM`` sibling).
ARCHIVE_KLINES_PREFIX = "data/spot/monthly/klines/"

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


#: The archive seam: one URL (a listing query, a zip, or a ``.CHECKSUM``) in,
#: one response out.  Unlike :data:`BinanceFetch` the archive is plain static
#: files at distinct paths (and a separate listing host), so a single URL is
#: the whole request — there is no separate ``params`` to carry.
#: :func:`urllib_archive_fetch` is the default; a test hands in recorded zip
#: and checksum bytes and touches no socket.
ArchiveFetch = Callable[[str], HttpResponse]


def urllib_archive_fetch(url: str) -> HttpResponse:
    """The default archive fetch: ``urllib`` against a plain URL, no API key.

    Every URL this module builds — a listing query, a monthly zip, or a
    ``.CHECKSUM`` sibling — is public; this is the same no-socket-in-tests
    seam :func:`urllib_fetch` is for the REST source.
    """
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


# -- Archive mode (feature 2): discovery, checksums, monthly zips ------------


#: The S3 listing response's namespace; every element this module reads
#: (``Contents``, ``Key``, ``IsTruncated``, ``NextMarker``) is namespaced.
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

#: A monthly kline key, e.g. ``data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-01.zip``.
#: The backreference requires the folder's symbol and the filename's symbol to
#: agree — Binance's own convention — and the ``.zip`` anchor excludes every
#: ``.zip.CHECKSUM`` sibling the same listing carries.
_ARCHIVE_KEY_RE = re.compile(
    r"^data/spot/monthly/klines/(?P<symbol>[A-Z0-9]+)/1d/"
    r"(?P=symbol)-1d-(?P<month>\d{4}-\d{2})\.zip$"
)


def _s3_tag(name: str) -> str:
    return f"{_S3_NS}{name}"


def _parse_listing_page(body: bytes) -> tuple[tuple[str, ...], bool, str | None]:
    root = ET.fromstring(body)
    keys = tuple(
        key for key in (c.findtext(_s3_tag("Key")) for c in root.iter(_s3_tag("Contents"))) if key
    )
    is_truncated = (root.findtext(_s3_tag("IsTruncated")) or "false").strip().lower() == "true"
    next_marker = root.findtext(_s3_tag("NextMarker"))
    return keys, is_truncated, next_marker


def _list_archive_keys(
    fetch: ArchiveFetch, prefix: str, *, sleep: Callable[[float], None]
) -> tuple[str, ...]:
    """Every key under ``prefix``, paging the archive bucket's own listing.

    A flat listing (no delimiter): one page's ``<Contents><Key>`` entries name
    both a symbol and a month at once, so one paginated crawl is discovery's
    only cost, however many symbols or months the archive holds.
    """
    keys: list[str] = []
    marker = ""
    while True:
        params = {"prefix": prefix}
        if marker:
            params["marker"] = marker
        url = f"{ARCHIVE_LISTING_URL}?{urllib.parse.urlencode(sorted(params.items()))}"
        response = fetch(url)
        sleep(DEFAULT_DELAY_SECONDS)
        if response.status != 200:
            raise BarsBackfillError(
                f"archive listing for prefix {prefix!r} failed: HTTP {response.status}"
            )
        page_keys, is_truncated, next_marker = _parse_listing_page(response.body)
        keys.extend(page_keys)
        if not is_truncated or not page_keys:
            break
        marker = next_marker or page_keys[-1]
    return tuple(keys)


def _list_archive_months(
    fetch: ArchiveFetch, *, sleep: Callable[[float], None]
) -> dict[str, tuple[str, ...]]:
    """Every USDT symbol the archive has ever held monthly ``1d`` klines for.

    One paginated crawl of :data:`ARCHIVE_KLINES_PREFIX` names every symbol
    and month at once (:data:`_ARCHIVE_KEY_RE`); a symbol not ending in
    ``USDT`` is dropped.  Months come back sorted, so the last element of a
    symbol's tuple is the true, archive-wide last month it has ever held —
    the fact a dead symbol is identified by.
    """
    keys = _list_archive_keys(fetch, ARCHIVE_KLINES_PREFIX, sleep=sleep)
    months_by_symbol: dict[str, set[str]] = {}
    for key in keys:
        match = _ARCHIVE_KEY_RE.match(key)
        if match is None:
            continue
        symbol = match["symbol"]
        if not symbol.endswith("USDT"):
            continue
        months_by_symbol.setdefault(symbol, set()).add(match["month"])
    return {
        symbol: tuple(sorted(months)) for symbol, months in sorted(months_by_symbol.items())
    }


def _months_between(first: date, last: date) -> tuple[str, ...]:
    """Every ``YYYY-MM`` month overlapping ``[first, last]``, in order."""
    months: list[str] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return tuple(months)


def _verify_checksum(zip_bytes: bytes, checksum_body: bytes, filename: str) -> None:
    """Refuse, naming ``filename``, unless ``checksum_body`` names its sha256.

    ``checksum_body`` is the archive's own ``.CHECKSUM`` file: a standard
    ``sha256sum`` output line, ``<hex digest>  <filename>``.  Only the first
    whitespace-separated token is read — the digest — so this does not care
    whether the venue spells the rest of the line as a space or an asterisk.
    """
    try:
        text = checksum_body.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise BarsBackfillError(f"{filename}.CHECKSUM is not valid text: {exc}") from exc
    expected = text.split()[0] if text else ""
    digest = hashlib.sha256(zip_bytes).hexdigest()
    if not expected or digest.lower() != expected.lower():
        raise BarsBackfillError(
            f"{filename}: checksum mismatch (archive names "
            f"{expected or '<empty>'}, computed {digest})"
        )


def _month_zip_url(symbol: str, month: str) -> tuple[str, str]:
    filename = f"{symbol}-1d-{month}.zip"
    return f"{ARCHIVE_BASE_URL}/{ARCHIVE_KLINES_PREFIX}{symbol}/1d/{filename}", filename


def _fetch_month(
    fetch: ArchiveFetch, symbol: str, month: str, *, sleep: Callable[[float], None]
) -> tuple[tuple[KlineRow, ...], dict[date, float]] | None:
    """One month's candles and per-day quote volume for ``symbol``.

    Returns ``None`` when the archive has no zip for this month at all (HTTP
    404: before the symbol listed, or after it was delisted) — not a failure,
    just nothing to add.  Raises :class:`BarsBackfillError`, naming the zip
    file, for any other HTTP failure or a checksum mismatch.
    """
    zip_url, filename = _month_zip_url(symbol, month)
    zip_response = fetch(zip_url)
    sleep(DEFAULT_DELAY_SECONDS)
    if zip_response.status == 404:
        return None
    if zip_response.status != 200:
        raise BarsBackfillError(f"{filename}: fetch failed: HTTP {zip_response.status}")

    checksum_response = fetch(f"{zip_url}.CHECKSUM")
    sleep(DEFAULT_DELAY_SECONDS)
    if checksum_response.status != 200:
        raise BarsBackfillError(
            f"{filename}.CHECKSUM: fetch failed: HTTP {checksum_response.status}"
        )
    _verify_checksum(zip_response.body, checksum_response.body, filename)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_response.body)) as bundle:
            names = bundle.namelist()
            if not names:
                raise BarsBackfillError(f"{filename}: the zip carries no files")
            csv_bytes = bundle.read(names[0])
    except zipfile.BadZipFile as exc:
        raise BarsBackfillError(f"{filename}: not a valid zip: {exc}") from exc

    raw_rows: list[list[str]] = []
    for raw_row in csv.reader(io.StringIO(csv_bytes.decode("utf-8"))):
        if not raw_row:
            continue
        if raw_row[0].strip().lower() in ("open_time", "opentime"):
            continue  # some archive vintages carry a header row
        raw_rows.append(raw_row)
    if not raw_rows:
        return None

    try:
        batch = parse_klines(raw_rows, _INTERVAL, symbol=symbol)
    except KlineParseError as exc:
        raise BarsBackfillError(f"{filename}: could not parse rows: {exc}") from exc

    # parse_klines is strict (it raises rather than drops), so batch.candles
    # is raw_rows's own order and length — the zip is the quote-volume
    # source of truth for ranking; KlineRow itself does not carry it.
    quote_by_day: dict[date, float] = {}
    for raw_row, candle in zip(raw_rows, batch.candles):
        day = candle.open_time.astimezone(_UTC).date()
        try:
            quote_by_day[day] = float(raw_row[7])
        except (IndexError, ValueError):
            quote_by_day[day] = 0.0
    return tuple(batch.candles), quote_by_day


def _fetch_symbol_archive_rows(
    fetch: ArchiveFetch,
    symbol: str,
    months: Sequence[str],
    *,
    sleep: Callable[[float], None],
) -> tuple[tuple[KlineRow, ...], dict[date, float], str | None]:
    """Every candle and per-day quote volume for ``symbol`` across ``months``.

    The third element is the last of ``months`` for which the archive
    actually held a zip — ``None`` when none of them did.
    """
    all_candles: list[KlineRow] = []
    all_volumes: dict[date, float] = {}
    last_month_with_data: str | None = None
    for month in months:
        result = _fetch_month(fetch, symbol, month, sleep=sleep)
        if result is None:
            continue
        candles, volumes = result
        all_candles.extend(candles)
        all_volumes.update(volumes)
        last_month_with_data = month
    return tuple(all_candles), all_volumes, last_month_with_data


def _clip_rows_to_window(
    rows: Sequence[KlineRow], first: date, last: date
) -> tuple[KlineRow, ...]:
    """Drop candles outside ``[first, last]`` — a month's zip may carry days
    either side of the window when the window does not fall on month
    boundaries."""
    return tuple(
        row for row in rows if first <= row.open_time.astimezone(_UTC).date() <= last
    )


def _month_already_written(lake_path: Path, symbol: str, month: str) -> bool:
    """True when ``symbol``'s ``month`` already has at least one written day.

    The resume check a rerun relies on: no separate progress ledger, just the
    partitions :func:`_write_bars` already left behind. A month is fetched
    and written as one atomic step (the fetch happens, then every one of its
    days is written before the next month starts), so one written day is
    enough to know the month is done.
    """
    symbol_root = lake_path / "staging" / BARS_STREAM / f"symbol={symbol}"
    if not symbol_root.is_dir():
        return False
    for partition in symbol_root.glob(f"date={month}-*"):
        if (partition / "part-0.parquet").is_file():
            return True
    return False


def _rank_cache_path(lake_path: Path, first: date, last: date) -> Path:
    return lake_path / RANK_CACHE_DIRNAME / f"rank-{first.isoformat()}_{last.isoformat()}.json"


def _load_rank_cache(
    path: Path, first: date, last: date
) -> list[tuple[str, float, str]] | None:
    """The cached whole-window ranking, or ``None`` on a miss or a bad file.

    A missing, unreadable, or malformed cache is treated exactly like a
    miss — the ranking is simply recomputed — rather than refusing the run
    over a checkpoint file's own corruption.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(payload, Mapping)
        or payload.get("first") != first.isoformat()
        or payload.get("last") != last.isoformat()
    ):
        return None
    entries = payload.get("ranking")
    if not isinstance(entries, list):
        return None
    ranking: list[tuple[str, float, str]] = []
    try:
        for entry in entries:
            ranking.append(
                (str(entry["symbol"]), float(entry["median_volume"]), str(entry["last_archived_month"]))
            )
    except (KeyError, TypeError, ValueError):
        return None
    return ranking


def _save_rank_cache(
    path: Path, first: date, last: date, ranking: Sequence[tuple[str, float, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "first": first.isoformat(),
        "last": last.isoformat(),
        "ranking": [
            {"symbol": symbol, "median_volume": median_volume, "last_archived_month": last_month}
            for symbol, median_volume, last_month in ranking
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    last_archived_month: Mapping[str, str] | None = None,
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
    # Archive mode only: the last month the archive holds for each included
    # symbol, the fact a reader tells a delisted symbol from a live one by.
    # Present (even empty) for archive, absent for REST — ``is not None``
    # rather than truthiness, so an archive run that observed no data at all
    # still carries the field.
    if last_archived_month is not None:
        payload["last_archived_month"] = dict(last_archived_month)
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
    # Archive mode only: a month that failed (bad checksum, unparseable
    # rows) while at least one other month of this same symbol still wrote —
    # reported here, and separately as its own JSON error line at the time
    # it happened, rather than failing the whole symbol over one bad month.
    failed_months: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"symbol": self.symbol, "status": self.status}
        if self.status == "ok":
            payload["rows_written"] = self.rows_written
            payload["skipped_non_positive_close"] = self.skipped_non_positive_close
            if self.failed_months:
                payload["failed_months"] = list(self.failed_months)
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


def _backfill_rest(
    lake_path: Path,
    first_date: date,
    last_date: date,
    *,
    symbols: Sequence[str] | None,
    top: int | None,
    fetch: BinanceFetch,
    sleep: Callable[[float], None],
) -> tuple[list[SymbolResult], tuple[str, ...], str]:
    if symbols is not None:
        resolved_symbols = _dedupe_symbols(symbols)
        selection_rule = f"explicit symbols: {', '.join(resolved_symbols)}"
    else:
        resolved_symbols = select_top_symbols(fetch, top, sleep=sleep)
        selection_rule = (
            f"top {top} TRADING USDT spot pairs by 24h quote volume, "
            "excluding stablecoin bases and leveraged tokens"
        )

    results: list[SymbolResult] = []
    for symbol in resolved_symbols:
        try:
            rows = _fetch_symbol_rows(fetch, symbol, first_date, last_date, sleep=sleep)
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
    return results, resolved_symbols, selection_rule


def _backfill_archive_symbol(
    lake_path: Path,
    symbol: str,
    first_date: date,
    last_date: date,
    *,
    fetch: ArchiveFetch,
    sleep: Callable[[float], None],
    emit: Callable[[str], object],
    restart: bool,
) -> tuple[SymbolResult, str | None]:
    """Fetch and write ``symbol``'s window one month at a time.

    Unless ``restart``, a month already on disk (:func:`_month_already_written`)
    is skipped with no fetch at all — the path a rerun takes after an
    interrupted run. A month that fails (bad checksum, unparseable rows, a
    non-404 HTTP status) prints its own JSON line naming ``symbol`` and the
    month and is then skipped, rather than losing the months that already
    succeeded; the symbol's own result still reads ``"ok"`` when at least one
    month wrote, with the failed months named in ``failed_months``. Returns
    the symbol's result and the last month the archive actually held data
    for (``None`` if none did).
    """
    written = 0
    skipped = 0
    failed_months: list[str] = []
    failure_messages: list[str] = []
    last_month_with_data: str | None = None

    for month in _months_between(first_date, last_date):
        if not restart and _month_already_written(lake_path, symbol, month):
            # Already on disk from an earlier run -- the archive is known to
            # have held data for this month (that is the only way it could
            # have been written), so a fully-resumed rerun must not drop it
            # from `last_month_with_data` just because this run skipped it.
            last_month_with_data = month
            continue
        try:
            result = _fetch_month(fetch, symbol, month, sleep=sleep)
        except BarsBackfillError as exc:
            emit(
                json.dumps(
                    {"phase": "error", "symbol": symbol, "month": month, "error": str(exc)}
                )
            )
            failed_months.append(month)
            failure_messages.append(str(exc))
            continue
        if result is None:
            continue
        rows, _volumes = result
        clipped = _clip_rows_to_window(rows, first_date, last_date)
        month_written, month_skipped = _write_bars(lake_path, symbol, clipped)
        written += month_written
        skipped += month_skipped
        last_month_with_data = month

    if written == 0 and skipped == 0 and failed_months:
        return (
            SymbolResult(symbol=symbol, status="error", error="; ".join(failure_messages)),
            last_month_with_data,
        )
    return (
        SymbolResult(
            symbol=symbol,
            status="ok",
            rows_written=written,
            skipped_non_positive_close=skipped,
            failed_months=tuple(failed_months),
        ),
        last_month_with_data,
    )


def _backfill_archive(
    lake_path: Path,
    first_date: date,
    last_date: date,
    *,
    symbols: Sequence[str] | None,
    top: int | None,
    fetch: ArchiveFetch,
    sleep: Callable[[float], None],
    emit: Callable[[str], object],
    restart: bool,
) -> tuple[list[SymbolResult], tuple[str, ...], str, dict[str, str]]:
    results: list[SymbolResult] = []
    last_archived_month: dict[str, str] = {}

    if symbols is not None:
        resolved_symbols = _dedupe_symbols(symbols)
        selection_rule = f"explicit symbols: {', '.join(resolved_symbols)}"
        for symbol in resolved_symbols:
            symbol_result, observed_last_month = _backfill_archive_symbol(
                lake_path,
                symbol,
                first_date,
                last_date,
                fetch=fetch,
                sleep=sleep,
                emit=emit,
                restart=restart,
            )
            results.append(symbol_result)
            if observed_last_month is not None:
                last_archived_month[symbol] = observed_last_month
        return results, resolved_symbols, selection_rule, last_archived_month

    # --top N: every USDT symbol discovery finds with data overlapping the
    # window is a candidate; each is fetched once and ranked by median daily
    # quote volume. A candidate whose fetch fails cannot be ranked and is
    # dropped — it was never selected, so it is not a selected symbol's
    # failure. The whole-window ranking (never the candle rows themselves) is
    # cached so a later run — even over a different --top — can skip this
    # crawl entirely; --restart ignores that cache and redoes it.
    cache_path = _rank_cache_path(lake_path, first_date, last_date)
    ranking = None if restart else _load_rank_cache(cache_path, first_date, last_date)
    if ranking is None:
        months_by_symbol = _list_archive_months(fetch, sleep=sleep)
        window_months = set(_months_between(first_date, last_date))
        candidates = [
            (symbol, in_window, archive_months[-1])
            for symbol, archive_months in months_by_symbol.items()
            if (in_window := tuple(m for m in archive_months if m in window_months))
        ]
        total = len(candidates)
        ranking = []
        for done, (symbol, in_window, archive_last_month) in enumerate(candidates, start=1):
            try:
                _rows, volumes, _observed = _fetch_symbol_archive_rows(
                    fetch, symbol, in_window, sleep=sleep
                )
            except BarsBackfillError:
                volumes = None
            emit(json.dumps({"phase": "rank", "symbols_done": done, "symbols_total": total}))
            if volumes is None:
                continue
            day_volumes = [
                volume for day, volume in volumes.items() if first_date <= day <= last_date
            ]
            if not day_volumes:
                continue
            median_volume = statistics.median(day_volumes)
            ranking.append((symbol, median_volume, archive_last_month))

        # Causal: computed once from the whole window and nothing past it,
        # fixed at the window's end rather than recomputed day by day.
        ranking.sort(key=lambda item: (-item[1], item[0]))
        _save_rank_cache(cache_path, first_date, last_date, ranking)

    selected = ranking[:top]
    resolved_symbols = tuple(item[0] for item in selected)
    selection_rule = (
        f"top {top} USDT spot pairs in Binance's public archive by median "
        f"daily quote volume over {first_date.isoformat()}..{last_date.isoformat()}"
    )
    for symbol, _median_volume, archive_last_month in selected:
        symbol_result, _observed = _backfill_archive_symbol(
            lake_path,
            symbol,
            first_date,
            last_date,
            fetch=fetch,
            sleep=sleep,
            emit=emit,
            restart=restart,
        )
        results.append(symbol_result)
        last_archived_month[symbol] = archive_last_month
    return results, resolved_symbols, selection_rule, last_archived_month


def backfill_bars(
    lake: str | Path,
    first: str | date,
    last: str | date,
    *,
    source: str = "rest",
    symbols: Sequence[str] | None = None,
    top: int | None = None,
    fetch: BinanceFetch | ArchiveFetch | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], datetime] | None = None,
    emit: Callable[[str], object] | None = None,
    restart: bool = False,
) -> tuple[SymbolResult, ...]:
    """Backfill daily bars for every resolved symbol; return each one's result.

    Exactly one of ``symbols`` or ``top`` must be given.  Writes
    ``<lake>/staging/bars/symbol=<S>/date=<D>/part-0.parquet`` for every
    positive-close candle found in ``[first, last]`` and
    ``<lake>/universe.json`` recording the run's provenance — written even
    when one or more symbols failed, because the universe definition names
    what was *asked for*, not only what happened to succeed.

    ``source="rest"`` (the default, feature 1) asks Binance's live REST API,
    which only ever lists today's symbols — ``survivorship_free: false``.
    ``source="archive"`` (feature 2) instead reads Binance's public data
    archive, which keeps every symbol's history for as long as it ever
    traded — ``survivorship_free: true``, and ``fetch``, when given, must
    then be an :data:`ArchiveFetch` (a single-URL callable) rather than a
    :data:`BinanceFetch`.

    A symbol whose fetch fails (an unparseable response, a non-retryable HTTP
    status, a 418/429 past :data:`MAX_RETRIES`, or — archive mode only — a
    checksum mismatch) is reported as that symbol's own error result rather
    than aborting the run — every other symbol still backfills.  The one
    exception is an archive ``--top N`` candidate: it must fetch successfully
    to be ranked at all, so a candidate's failure drops it from the
    candidate pool rather than appearing as an error result.

    ``emit``, archive mode only, is called with one JSON line at a time as
    the run makes progress — a ``"rank"`` line per candidate during
    ``--top N`` discovery, and an ``"error"`` line naming the symbol and
    month whenever one month fails — ahead of the per-symbol lines a caller
    prints from this function's return value. ``restart``, archive mode
    only, ignores the rank cache and every already-written month, exactly as
    if the lake were empty; the default resumes an interrupted run instead.
    """
    if source not in ("rest", "archive"):
        raise BarsBackfillError(f"--source must be 'rest' or 'archive', got {source!r}")
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
    if top is not None and (not isinstance(top, int) or isinstance(top, bool) or top <= 0):
        raise BarsBackfillError(f"--top must be a positive integer, got {top!r}")

    resolved_sleep = sleep if sleep is not None else _default_sleep
    resolved_clock = clock if clock is not None else _utc_now
    resolved_emit: Callable[[str], object] = emit if emit is not None else (lambda _line: None)

    if source == "rest":
        resolved_fetch = fetch if fetch is not None else urllib_fetch
        results, resolved_symbols, selection_rule = _backfill_rest(
            lake_path,
            first_date,
            last_date,
            symbols=symbols,
            top=top,
            fetch=resolved_fetch,
            sleep=resolved_sleep,
        )
        last_archived_month: dict[str, str] | None = None
    else:
        resolved_fetch = fetch if fetch is not None else urllib_archive_fetch
        results, resolved_symbols, selection_rule, last_archived_month = _backfill_archive(
            lake_path,
            first_date,
            last_date,
            symbols=symbols,
            top=top,
            fetch=resolved_fetch,
            sleep=resolved_sleep,
            emit=resolved_emit,
            restart=restart,
        )

    _write_universe(
        lake_path,
        source="binance-rest" if source == "rest" else "binance-archive",
        selection_rule=selection_rule,
        fetched_at=resolved_clock(),
        first=first_date,
        last=last_date,
        symbols=resolved_symbols,
        survivorship_free=(source == "archive"),
        last_archived_month=last_archived_month,
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
    parser.add_argument(
        "--source",
        choices=("rest", "archive"),
        default="rest",
        help=(
            "'rest' (default) asks Binance's live REST API, today's symbols "
            "only; 'archive' reads Binance's public data archive, which "
            "keeps delisted symbols too (survivorship-free)"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbols", metavar="S,S,...", help="an explicit symbol list")
    group.add_argument(
        "--top", type=int, metavar="N", help="the top N symbols by 24h quote volume"
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help=(
            "archive mode only: ignore the rank cache and every "
            "already-written month, exactly as if the lake were empty"
        ),
    )
    return parser


def _print_line(line: str) -> None:
    """Print one JSON line and flush it. When stdout is redirected to a file,
    Python block-buffers it, so a multi-hour backfill's progress lines would
    otherwise sit unseen in the buffer until exit."""
    print(line, flush=True)


def main(
    argv: Sequence[str] | None = None,
    *,
    emit: Callable[[str], object] = _print_line,
    fetch: BinanceFetch | ArchiveFetch | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """``python -m nullius_ingest.bars_backfill --lake LAKE --first D --last D [--source rest|archive] (--symbols S,S,... | --top N) [--restart]``.

    Archive mode prints a ``"rank"`` progress line per ``--top N`` candidate
    and an ``"error"`` line naming any symbol and month that failed, as the
    run makes progress; then, as before, one JSON line per symbol (its rows
    written and skipped, or its error) and one summary JSON line, through
    ``emit`` — the same lines regardless of ``--source``.  Returns
    :data:`EXIT_OK` when every symbol and every month backfilled;
    :data:`EXIT_REFUSED` when an argument was invalid (nothing is written),
    at least one symbol's own result carries an error, or a symbol otherwise
    marked ``"ok"`` still had a month fail (every other symbol's and every
    other month's data is still written). An error not already reported as
    one of the lines above — anything other than :class:`BarsBackfillError`
    — still exits :data:`EXIT_REFUSED`, with one stderr line and no
    traceback.
    """
    arguments = _build_parser().parse_args(argv)
    symbols = _parse_symbols_arg(arguments.symbols) if arguments.symbols else None

    try:
        results = backfill_bars(
            arguments.lake,
            arguments.first,
            arguments.last,
            source=arguments.source,
            symbols=symbols,
            top=arguments.top,
            fetch=fetch,
            sleep=sleep,
            clock=clock,
            emit=emit,
            restart=arguments.restart,
        )
    except BarsBackfillError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 -- an operator sees one line, never a raw traceback
        print(f"unexpected error: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    had_error = False
    total_written = 0
    total_skipped = 0
    for result in results:
        emit(json.dumps(result.to_payload()))
        if result.status == "error" or result.failed_months:
            had_error = True
        if result.status == "ok":
            total_written += result.rows_written
            total_skipped += result.skipped_non_positive_close

    emit(
        json.dumps(
            {
                "symbols": len(results),
                "failed": sum(1 for r in results if r.status == "error" or r.failed_months),
                "rows_written": total_written,
                "skipped_non_positive_close": total_skipped,
            }
        )
    )
    return EXIT_REFUSED if had_error else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
