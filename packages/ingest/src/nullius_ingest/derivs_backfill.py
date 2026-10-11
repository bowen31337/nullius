"""Backfill USD-M futures derivatives into point-in-time daily lake streams.

``additions_spec_derivatives_inputs.xml``: *System backfills USD-M futures
funding rates, futures daily klines and daily open-interest metrics from the
free archive into point-in-time daily lake streams*, so that::

    ./run.sh lake-derivs-backfill --lake L --first A --last B \\
        --symbols-from L/universe.json

returns ``funding/``, ``futbars/`` (the basis-input stream) and, opt-in,
``metrics/`` partitions for the spot universe :mod:`nullius_ingest.bars_backfill`
already wrote to ``L/universe.json``.

**Reuse, not a second implementation.** The archive this module reads is the
same S3-compatible bucket :mod:`nullius_ingest.bars_backfill`'s ``--source
archive`` feature already pages: the same listing endpoint, the same
``<zip>``/``<zip>.CHECKSUM`` pair-and-verify contract, the same on-disk
verified-file cache. That module's archive helpers are now parametrized by
archive prefix, key pattern and interval (with no behaviour change for its
own spot bars — the existing bars tests still pass unchanged) precisely so
this module can call them directly rather than re-implement them:
:func:`~nullius_ingest.bars_backfill._list_archive_months` (the S3 listing,
reduced through a caller-supplied ``prefix`` and ``key_re``),
:func:`~nullius_ingest.bars_backfill._archive_zip_url` (one period's URL,
built from a caller-supplied ``prefix``, ``interval`` and ``subdir``), and
:func:`~nullius_ingest.bars_backfill.fetch_verified_archive_zip` (the zip
cache and its :func:`~nullius_ingest.bars_backfill._verify_checksum` call,
parametrized by a caller-chosen ``cache_key`` so this module's own UM
futures fetches never collide with that module's spot fetches). ``--workers``
(bounded the same way, imported from the same module) and ``--restart``
follow the same shape bars_backfill already established for its own archive
mode.

**Symbol mapping, written once, reused across runs.** A spot symbol ``S``
backed by USD-M futures trades either as the perpetual ``S`` itself, or —
when the underlying is cheap enough that Binance only lists a scaled
contract — as ``1000S`` (``PEPEUSDT`` to ``1000PEPEUSDT``). Resolved once
per symbol by one S3 listing crawl of the UM klines tree (the "rank-free"
counterpart of bars_backfill's own ``--top N`` discovery: no ranking, just a
membership test against ``universe.json``'s own symbol list), the mapping —
including the scale factor a reader needs to bring a scaled contract's price
back to the spot scale — is written to ``<lake>/staging-meta/um-symbol-map.json``
and reused on a later run without re-crawling, as long as every requested
symbol is already a key in it. A spot symbol with no UM perpetual at all
(neither spelling present in the archive) is recorded with a null mapping
and produces no rows in any stream — not an error, just nothing to add.

**Three streams, one write convention.** Every row lands at
``<lake>/staging/<stream>/symbol=<S>/date=<D>/part-0.parquet`` (``S`` always
the *spot* symbol, never the UM one — a reader joining this against spot
bars never needs to know the mapping happened), one row per day, with a
``symbol`` column, a ``date`` column (that day's UTC midnight,
``timestamp("us", "UTC")``, matching the magnitude-based ms/µs
normalization :mod:`nullius_ingest.klines` already applies to every other
epoch instant this ingest member reads) and the stream's own fields as the
venue's verbatim string spelling — the same convention
:mod:`nullius_ingest.bars_backfill` keeps for OHLCV, except for a field that
is fundamentally a count (``n_settlements``), kept as an integer exactly as
that module keeps ``trade_count``. Nothing is ever forward-filled past a
symbol's last archived day: a day with no settlement, no candle or no
snapshot in the source archive simply has no row.

* ``funding/``, from ``data/futures/um/monthly/fundingRate``: one row per
  symbol per day ``D`` with ``funding_rate_sum`` (the exact decimal sum of
  every settlement with ``calcTime`` in ``(D 00:00, D+1 00:00]``),
  ``funding_rate_last`` (the last settlement in that window, verbatim) and
  ``n_settlements``. The half-open-then-closed window is deliberate: a
  settlement timestamped exactly at a day's own midnight belongs to the
  *previous* day's window, and a settlement at ``D+1 00:00`` belongs to
  ``D`` — both corollaries of the same ``(D 00:00, D+1 00:00]`` rule, applied
  by subtracting one microsecond before taking the calendar date
  (:func:`_day_bucket`). A day with no settlement in it has no row.
* ``futbars/``, from ``data/futures/um/monthly/klines/<symbol>/1d``: one row
  per day with ``fut_close``, ``fut_volume``, ``taker_buy_volume`` and
  ``quote_volume``. The first three are rescaled by the symbol's own scale
  factor — divided for a price, multiplied for a volume — so that
  ``fut_close`` lands on the spot price scale and ``fut_close *
  fut_volume`` still reconciles against ``quote_volume`` (always USDT,
  unaffected by the contract's own unit size, so never rescaled). Candle
  parsing itself is not re-implemented: each month's rows go through
  :func:`nullius_ingest.klines.parse_klines`, exactly as
  :mod:`nullius_ingest.bars_backfill` already does for spot — the one
  difference is this module also reads the raw CSV's quote-volume and
  taker-buy-volume columns directly, since :class:`~nullius_ingest.klines.KlineRow`
  does not carry them.
* ``metrics/`` (opt-in via ``--streams metrics`` — roughly 30x more files
  than the other two streams, one zip per symbol per *day* rather than per
  month), from ``data/futures/um/daily/metrics``: one row per day built from
  the last 5-minute snapshot *strictly before* ``D+1 00:00`` — the opposite
  half-open rule from funding's, since a trailing snapshot the venue stamps
  exactly at the next day's midnight is a boundary artifact to drop, not a
  settlement to credit back a day. ``sum_open_interest``,
  ``sum_open_interest_value``, ``count_toptrader_long_short_ratio``,
  ``sum_toptrader_long_short_ratio``, ``count_long_short_ratio`` and
  ``sum_taker_long_short_vol_ratio`` are carried verbatim from that one
  snapshot — including an empty string the venue itself sometimes reports
  for the ratio fields — with no computation.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import sys
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .bars_backfill import (  # shared, generic primitives reused here
    ARCHIVE_CACHE_DIRNAME,
    DEFAULT_WORKERS,
    MAX_WORKERS,
    MIN_WORKERS,
    RANK_CACHE_DIRNAME,
    ArchiveFetch,
    BarsBackfillError,
    _archive_zip_url,
    _list_archive_months,
    _months_between,
    fetch_verified_archive_zip,
    urllib_archive_fetch,
)
from .klines import KlineParseError, parse_klines

__all__ = [
    "ALL_STREAMS",
    "DEFAULT_STREAMS",
    "EXIT_OK",
    "EXIT_REFUSED",
    "FUNDING_STREAM",
    "FUTBARS_STREAM",
    "METRICS_STREAM",
    "SCALE_PREFIX",
    "SYMBOL_MAP_FILENAME",
    "DerivsBackfillError",
    "StreamSymbolResult",
    "backfill_derivs",
    "main",
]

#: The three streams this module writes.
FUNDING_STREAM = "funding"
FUTBARS_STREAM = "futbars"
METRICS_STREAM = "metrics"
ALL_STREAMS: tuple[str, ...] = (FUNDING_STREAM, FUTBARS_STREAM, METRICS_STREAM)

#: ``--streams``' default: metrics is opt-in (about 30x more files — one zip
#: per symbol per *day* rather than per month).
DEFAULT_STREAMS: tuple[str, ...] = (FUNDING_STREAM, FUTBARS_STREAM)

#: The UM futures archive's own key prefixes, one per stream this module reads.
_UM_KLINES_PREFIX = "data/futures/um/monthly/klines/"
_UM_FUNDING_PREFIX = "data/futures/um/monthly/fundingRate/"
_UM_METRICS_PREFIX = "data/futures/um/daily/metrics/"

#: Where a spot symbol maps to a scaled contract (``PEPEUSDT`` ->
#: ``1000PEPEUSDT``) when only that contract trades.
SCALE_PREFIX = "1000"

#: The file this module writes beside ``staging/``, never inside it — a
#: sibling of bars_backfill's own ``universe.json`` and rank cache.
SYMBOL_MAP_FILENAME = "um-symbol-map.json"

#: A monthly UM kline key, e.g.
#: ``data/futures/um/monthly/klines/1000PEPEUSDT/1d/1000PEPEUSDT-1d-2023-05.zip``
#: — the ``key_re`` this module hands to
#: :func:`nullius_ingest.bars_backfill._list_archive_months` (named
#: ``symbol`` and ``month`` groups, exactly as that function's own default
#: pattern carries) to discover which UM symbols exist at all; a
#: klines-backed perpetual is assumed to also carry funding, which every
#: perpetual contract does by construction.
_UM_KLINES_SYMBOL_RE = re.compile(
    r"^data/futures/um/monthly/klines/(?P<symbol>[A-Z0-9]+)/1d/"
    r"(?P=symbol)-1d-(?P<month>\d{4}-\d{2})\.zip$"
)

#: Per-stream archive layout: the key prefix, the filename's own middle
#: token and the path segment between the symbol and the filename (``None``
#: when there is none) — the "prefix, key pattern and interval"
#: parametrization :mod:`nullius_ingest.bars_backfill`'s own
#: ``_archive_zip_url`` and ``_list_archive_months`` now take, called here
#: with this module's own values rather than re-implemented.
_MONTHLY_LAYOUT: dict[str, dict[str, str | None]] = {
    FUNDING_STREAM: {"prefix": _UM_FUNDING_PREFIX, "interval": "fundingRate", "subdir": None},
    FUTBARS_STREAM: {"prefix": _UM_KLINES_PREFIX, "interval": "1d", "subdir": "1d"},
}

#: The six metrics fields carried verbatim from the selected snapshot, in
#: the archive CSV's own column order (after ``create_time`` and ``symbol``).
_METRICS_FIELDS: tuple[str, ...] = (
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)

#: The epoch-magnitude bands a venue instant's unit is read from — the same
#: thresholds :mod:`nullius_ingest.klines` uses, duplicated here because
#: this module parses ``calcTime``/``create_time`` columns directly rather
#: than through a :class:`~nullius_ingest.klines.KlineRow`.
_EPOCH_MILLIS_CEILING = 10**14
_EPOCH_MICROS_FLOOR = 10**15
_EPOCH_MICROS_CEILING = 10**17
_MICROS_PER_MILLI = 1000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

EXIT_OK = 0
EXIT_REFUSED = 1


class DerivsBackfillError(Exception):
    """A derivatives backfill request could not be honoured.

    Raised for a malformed argument, an unreadable ``--symbols-from`` file,
    an archive row this module cannot parse, or an HTTP failure that is not
    a plain 404. A per-(stream, symbol, period) failure is reported on that
    period's own result and JSON line rather than aborting the whole run —
    every other period, symbol and stream still backfills.
    """


# -- Timestamps: ms or µs, by magnitude --------------------------------------


def _epoch_to_utc(raw: str, where: str) -> datetime:
    """Parse ``raw`` as an epoch instant, reading its unit from its magnitude.

    Mirrors :mod:`nullius_ingest.klines`'s own rule: below
    :data:`_EPOCH_MILLIS_CEILING` the value is milliseconds; from
    :data:`_EPOCH_MICROS_FLOOR` up to (not including)
    :data:`_EPOCH_MICROS_CEILING` it is already microseconds. Anything else
    is refused rather than guessed.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise DerivsBackfillError(
            f"{where} is {raw!r}; expected an epoch instant"
        ) from exc
    if value < 0:
        raise DerivsBackfillError(f"{where} is {value}; an epoch instant is non-negative")
    if value < _EPOCH_MILLIS_CEILING:
        micros = value * _MICROS_PER_MILLI
    elif _EPOCH_MICROS_FLOOR <= value < _EPOCH_MICROS_CEILING:
        micros = value
    else:
        raise DerivsBackfillError(
            f"{where} is {value}; its magnitude is neither a millisecond epoch "
            f"(below {_EPOCH_MILLIS_CEILING}) nor a microsecond epoch "
            f"({_EPOCH_MICROS_FLOOR} to {_EPOCH_MICROS_CEILING})"
        )
    return _EPOCH + timedelta(microseconds=micros)


def _day_bucket(instant: datetime) -> date:
    """The day ``instant`` belongs to under the ``(D 00:00, D+1 00:00]`` rule.

    Subtracting one microsecond before taking the calendar date is exactly
    that rule: an instant at a day's own midnight rolls back to the
    *previous* day (it is that day's own closing instant), and an instant at
    the *next* day's midnight stays on the day whose window it closes.
    """
    return (instant - timedelta(microseconds=1)).date()


def _coerce_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise DerivsBackfillError(
                f"{value!r} is not an ISO-8601 date (YYYY-MM-DD)"
            ) from exc
    raise DerivsBackfillError(
        f"a date must be a date or an ISO-8601 string, got {type(value).__name__}"
    )


def _default_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


# -- Symbol mapping ------------------------------------------------------------


def _discover_um_symbols(fetch: ArchiveFetch, *, sleep: Callable[[float], None]) -> frozenset[str]:
    """Every UM symbol the archive's klines tree has ever held.

    :func:`nullius_ingest.bars_backfill._list_archive_months` is the same
    S3-listing-to-regex walk bars_backfill's own ``--top N`` discovery
    crawls — reused here, unmodified, over this module's own prefix and key
    pattern (:data:`_UM_KLINES_PREFIX`, :data:`_UM_KLINES_SYMBOL_RE`) rather
    than re-implemented. This module only ever needs *whether* a UM
    contract exists, never its months, so only the returned mapping's keys
    are kept.
    """
    months_by_symbol = _list_archive_months(
        fetch, sleep=sleep, prefix=_UM_KLINES_PREFIX, key_re=_UM_KLINES_SYMBOL_RE
    )
    return frozenset(months_by_symbol)


def _map_symbol(spot_symbol: str, um_symbols: frozenset[str]) -> tuple[str, int] | None:
    """``(um_symbol, scale)`` for ``spot_symbol``, or ``None`` with no perpetual."""
    if spot_symbol in um_symbols:
        return spot_symbol, 1
    scaled = f"{SCALE_PREFIX}{spot_symbol}"
    if scaled in um_symbols:
        return scaled, 1000
    return None


def _symbol_map_path(lake_path: Path) -> Path:
    return lake_path / RANK_CACHE_DIRNAME / SYMBOL_MAP_FILENAME


def _load_symbol_map(path: Path) -> dict[str, dict[str, object]] | None:
    """The cached mapping, or ``None`` on a miss or a malformed file.

    A missing, unreadable or malformed cache is treated exactly like a
    miss — the mapping is simply rebuilt — rather than refusing the run
    over a checkpoint file's own corruption.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    result: dict[str, dict[str, object]] = {}
    for symbol, entry in payload.items():
        if not isinstance(entry, Mapping):
            return None
        result[str(symbol)] = dict(entry)
    return result


def _save_symbol_map(path: Path, mapping: Mapping[str, Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {symbol: dict(entry) for symbol, entry in mapping.items()}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_symbol_map(
    lake_path: Path,
    spot_symbols: Sequence[str],
    *,
    fetch: ArchiveFetch,
    sleep: Callable[[float], None],
    restart: bool,
) -> dict[str, dict[str, object]]:
    """The UM symbol map covering every one of ``spot_symbols``.

    Reused from ``um-symbol-map.json`` without crawling the archive when
    every requested symbol is already a key in it; otherwise (a cache miss,
    a new symbol the cached map has never seen, or ``--restart``) one fresh
    S3 listing crawl resolves every symbol at once and the file is
    rewritten, merging into — never dropping — whatever the cache already
    recorded for symbols outside this run's request.
    """
    path = _symbol_map_path(lake_path)
    existing = None if restart else _load_symbol_map(path)
    if existing is not None and all(symbol in existing for symbol in spot_symbols):
        return existing

    um_symbols = _discover_um_symbols(fetch, sleep=sleep)
    mapping: dict[str, dict[str, object]] = dict(existing) if existing else {}
    for symbol in spot_symbols:
        if symbol in mapping:
            continue
        resolved = _map_symbol(symbol, um_symbols)
        if resolved is None:
            mapping[symbol] = {"um_symbol": None, "scale": None}
        else:
            um_symbol, scale = resolved
            mapping[symbol] = {"um_symbol": um_symbol, "scale": scale}
    _save_symbol_map(path, mapping)
    return mapping


# -- Reading the spot universe -------------------------------------------------


def _read_symbols_from(path: str | Path) -> tuple[str, ...]:
    resolved = Path(path).expanduser()
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise DerivsBackfillError(
            f"--symbols-from {resolved}: could not read the file: {exc}"
        ) from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise DerivsBackfillError(
            f"--symbols-from {resolved}: not valid JSON: {exc}"
        ) from exc
    symbols_field = payload.get("symbols") if isinstance(payload, Mapping) else None
    if not isinstance(symbols_field, list):
        raise DerivsBackfillError(
            f"--symbols-from {resolved}: no 'symbols' list found "
            f"(expected a universe.json carrying one)"
        )
    seen: dict[str, None] = {}
    for entry in symbols_field:
        symbol = str(entry).strip()
        if symbol:
            seen.setdefault(symbol, None)
    if not seen:
        raise DerivsBackfillError(f"--symbols-from {resolved}: the 'symbols' list is empty")
    return tuple(seen)


# -- The archive: bars_backfill's own URL builder, one verified-fetch call --
# -- per period (:func:`~nullius_ingest.bars_backfill._archive_zip_url`,     --
# -- reused directly rather than re-implemented) ------------------------------


def _unzip_csv_rows(zip_bytes: bytes, filename: str) -> list[list[str]]:
    """Every row of the zip's single CSV member, header row included."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as bundle:
            names = bundle.namelist()
            if not names:
                raise DerivsBackfillError(f"{filename}: the zip carries no files")
            csv_bytes = bundle.read(names[0])
    except zipfile.BadZipFile as exc:
        raise DerivsBackfillError(f"{filename}: not a valid zip: {exc}") from exc
    return [row for row in csv.reader(io.StringIO(csv_bytes.decode("utf-8"))) if row]


# -- funding/ -------------------------------------------------------------


def _parse_funding_rows(raw_rows: Sequence[list[str]], filename: str) -> dict[date, dict[str, object]]:
    settlements: list[tuple[datetime, str]] = []
    for row in raw_rows:
        if row[0].strip().lower() == "calc_time":
            continue  # the archive's own header row
        if len(row) < 3:
            raise DerivsBackfillError(
                f"{filename}: a funding row needs calc_time, funding_interval_hours "
                f"and last_funding_rate, got {row!r}"
            )
        instant = _epoch_to_utc(row[0], f"{filename}: calc_time")
        settlements.append((instant, row[2]))
    settlements.sort(key=lambda item: item[0])

    by_day: dict[date, list[tuple[datetime, str]]] = {}
    for instant, rate in settlements:
        by_day.setdefault(_day_bucket(instant), []).append((instant, rate))

    result: dict[date, dict[str, object]] = {}
    for day, entries in by_day.items():
        total = Decimal(0)
        for _instant, rate in entries:
            try:
                total += Decimal(rate)
            except InvalidOperation as exc:
                raise DerivsBackfillError(
                    f"{filename}: last_funding_rate {rate!r} is not a decimal"
                ) from exc
        result[day] = {
            "funding_rate_sum": format(total, "f"),
            "funding_rate_last": entries[-1][1],  # entries are in ascending calc_time order
            "n_settlements": len(entries),
        }
    return result


# -- futbars/ -------------------------------------------------------------


def _parse_futbars_rows(
    raw_rows: Sequence[list[str]], filename: str, *, symbol: str, scale: int
) -> dict[date, dict[str, object]]:
    data_rows = [row for row in raw_rows if row[0].strip().lower() not in ("open_time", "opentime")]
    if not data_rows:
        return {}
    try:
        batch = parse_klines(data_rows, "1d", symbol=symbol)
    except KlineParseError as exc:
        raise DerivsBackfillError(f"{filename}: could not parse rows: {exc}") from exc

    scale_dec = Decimal(scale)
    result: dict[date, dict[str, object]] = {}
    for raw_row, candle in zip(data_rows, batch.candles):
        if len(raw_row) < 10:
            raise DerivsBackfillError(
                f"{filename}: a futures kline row needs a quote_volume and a "
                f"taker_buy_volume column, got {raw_row!r}"
            )
        day = candle.open_time.astimezone(UTC).date()
        try:
            fut_close = Decimal(candle.close) / scale_dec
            fut_volume = Decimal(candle.volume) * scale_dec
            taker_buy_volume = Decimal(raw_row[9]) * scale_dec
        except InvalidOperation as exc:
            raise DerivsBackfillError(
                f"{filename}: a price or volume field is not a decimal: {exc}"
            ) from exc
        result[day] = {
            "fut_close": format(fut_close, "f"),
            "fut_volume": format(fut_volume, "f"),
            "taker_buy_volume": format(taker_buy_volume, "f"),
            "quote_volume": raw_row[7],
        }
    return result


# -- The shared monthly-stream engine (funding, futbars) ----------------------


def _month_already_written(lake_path: Path, stream: str, symbol: str, month: str) -> bool:
    """True when ``symbol``'s ``month`` already has at least one written day
    in ``stream`` — the resume check a rerun relies on, generalizing
    bars_backfill's own (which is pinned to the ``bars`` stream)."""
    symbol_root = lake_path / "staging" / stream / f"symbol={symbol}"
    if not symbol_root.is_dir():
        return False
    for partition in symbol_root.glob(f"date={month}-*"):
        if (partition / "part-0.parquet").is_file():
            return True
    return False


def _day_already_written(lake_path: Path, stream: str, symbol: str, day: date) -> bool:
    path = lake_path / "staging" / stream / f"symbol={symbol}" / f"date={day.isoformat()}" / "part-0.parquet"
    return path.is_file()


def _write_row(lake_path: Path, stream: str, symbol: str, day: date, fields: Mapping[str, object]) -> None:
    """Write one day's row for ``symbol`` in ``stream``.

    A string field is kept verbatim, matching :mod:`nullius_ingest.bars_backfill`'s
    own OHLCV convention; an integer field (a count, e.g. ``n_settlements``)
    is kept as ``int64``, matching that module's own ``trade_count``.
    """
    timestamp_type = pa.timestamp("us", tz="UTC")
    day_instant = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    columns: dict[str, object] = {
        "symbol": [symbol],
        "date": pa.array([day_instant], type=timestamp_type),
    }
    for key, value in fields.items():
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise DerivsBackfillError(
                f"{stream} field {key!r} is {type(value).__name__}; expected a "
                f"str or an int count"
            )
        columns[key] = pa.array([value], type=pa.int64()) if isinstance(value, int) else [value]
    table = pa.table(columns)
    partition = lake_path / "staging" / stream / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, partition / "part-0.parquet")


@dataclass(frozen=True)
class StreamSymbolResult:
    """One stream's outcome for one symbol — the unit the per-line JSON reports.

    ``status`` is ``"ok"`` (at least nothing failed outright — ``rows_written``
    may still be zero, e.g. a window before the contract's first archived
    day), ``"error"`` (every period failed and nothing was written) or
    ``"skipped"`` (the symbol carries no UM perpetual at all — reported once,
    not once per stream, since the fact is stream-independent).
    """

    stream: str
    symbol: str
    status: str
    rows_written: int = 0
    failed_periods: tuple[str, ...] = ()
    error: str | None = None
    reason: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "stream": self.stream,
            "symbol": self.symbol,
            "status": self.status,
        }
        if self.status == "skipped":
            payload["reason"] = self.reason
            return payload
        payload["rows_written"] = self.rows_written
        if self.failed_periods:
            payload["failed_periods"] = list(self.failed_periods)
        if self.status == "error":
            payload["error"] = self.error
        return payload


def _backfill_monthly_stream(
    lake_path: Path,
    stream: str,
    spot_symbol: str,
    um_symbol: str,
    first: date,
    last: date,
    *,
    prefix: str,
    interval: str,
    subdir: str | None,
    parse_rows: Callable[[Sequence[list[str]], str], dict[date, dict[str, object]]],
    fetch: ArchiveFetch,
    sleep: Callable[[float], None],
    emit: Callable[[str], object],
    restart: bool,
) -> StreamSymbolResult:
    """Fetch and write ``spot_symbol``'s window, one month at a time.

    Unless ``restart``, a month already on disk (:func:`_month_already_written`)
    is skipped with no fetch at all. A month that fails (a bad checksum, an
    HTTP failure, or an unparseable row) prints its own error line and is
    skipped; the symbol's own result still reads ``"ok"`` when at least one
    other month wrote, with the failed periods named.
    """
    written = 0
    failed_periods: list[str] = []
    failure_messages: list[str] = []
    cache_key = f"{stream}/{um_symbol}"

    for month in _months_between(first, last):
        if not restart and _month_already_written(lake_path, stream, spot_symbol, month):
            continue

        url, filename = _archive_zip_url(um_symbol, month, prefix=prefix, interval=interval, subdir=subdir)
        try:
            zip_bytes = fetch_verified_archive_zip(fetch, lake_path, cache_key, url, filename, sleep=sleep)
        except BarsBackfillError as exc:
            emit(json.dumps(
                {"phase": "error", "stream": stream, "symbol": spot_symbol, "period": month, "error": str(exc)}
            ))
            failed_periods.append(month)
            failure_messages.append(str(exc))
            continue
        if zip_bytes is None:
            continue

        try:
            raw_rows = _unzip_csv_rows(zip_bytes, filename)
            by_day = parse_rows(raw_rows, filename)
        except DerivsBackfillError as exc:
            emit(json.dumps(
                {"phase": "error", "stream": stream, "symbol": spot_symbol, "period": month, "error": str(exc)}
            ))
            failed_periods.append(month)
            failure_messages.append(str(exc))
            continue

        for day, fields in by_day.items():
            if first <= day <= last:
                _write_row(lake_path, stream, spot_symbol, day, fields)
                written += 1

    if written == 0 and failed_periods:
        return StreamSymbolResult(
            stream=stream,
            symbol=spot_symbol,
            status="error",
            failed_periods=tuple(failed_periods),
            error="; ".join(failure_messages),
        )
    return StreamSymbolResult(
        stream=stream,
        symbol=spot_symbol,
        status="ok",
        rows_written=written,
        failed_periods=tuple(failed_periods),
    )


def _backfill_funding_symbol(
    lake_path: Path, spot_symbol: str, um_symbol: str, first: date, last: date,
    *, fetch: ArchiveFetch, sleep: Callable[[float], None], emit: Callable[[str], object], restart: bool,
) -> StreamSymbolResult:
    layout = _MONTHLY_LAYOUT[FUNDING_STREAM]
    return _backfill_monthly_stream(
        lake_path, FUNDING_STREAM, spot_symbol, um_symbol, first, last,
        prefix=layout["prefix"], interval=layout["interval"], subdir=layout["subdir"],
        parse_rows=_parse_funding_rows,
        fetch=fetch, sleep=sleep, emit=emit, restart=restart,
    )


def _backfill_futbars_symbol(
    lake_path: Path, spot_symbol: str, um_symbol: str, scale: int, first: date, last: date,
    *, fetch: ArchiveFetch, sleep: Callable[[float], None], emit: Callable[[str], object], restart: bool,
) -> StreamSymbolResult:
    layout = _MONTHLY_LAYOUT[FUTBARS_STREAM]

    def parse_rows(raw_rows: Sequence[list[str]], filename: str) -> dict[date, dict[str, object]]:
        return _parse_futbars_rows(raw_rows, filename, symbol=um_symbol, scale=scale)

    return _backfill_monthly_stream(
        lake_path, FUTBARS_STREAM, spot_symbol, um_symbol, first, last,
        prefix=layout["prefix"], interval=layout["interval"], subdir=layout["subdir"],
        parse_rows=parse_rows,
        fetch=fetch, sleep=sleep, emit=emit, restart=restart,
    )


# -- metrics/ (opt-in, daily-keyed) -------------------------------------------


def _parse_metrics_timestamp(raw: str, filename: str) -> datetime:
    text = raw.strip()
    if text.lstrip("-").isdigit():
        return _epoch_to_utc(text, f"{filename}: create_time")
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise DerivsBackfillError(
            f"{filename}: create_time {raw!r} is neither an epoch instant nor "
            f"'YYYY-MM-DD HH:MM:SS'"
        ) from exc


def _select_metrics_snapshot(
    rows: Sequence[list[str]], day: date, filename: str
) -> dict[str, object] | None:
    """The last 5-minute snapshot strictly before ``day``'s next midnight.

    A snapshot stamped *at or after* that midnight — the trailing boundary
    row the venue sometimes appends — is excluded from consideration
    entirely, never merely out-ranked: the window is strictly-before, with
    no closing boundary to include.
    """
    next_midnight = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    best: tuple[datetime, list[str]] | None = None
    for row in rows:
        if row[0].strip().lower() == "create_time":
            continue  # the archive's own header row
        if len(row) < 2 + len(_METRICS_FIELDS):
            raise DerivsBackfillError(
                f"{filename}: a metrics row needs create_time, symbol and "
                f"{len(_METRICS_FIELDS)} fields, got {row!r}"
            )
        instant = _parse_metrics_timestamp(row[0], filename)
        if instant >= next_midnight:
            continue
        if best is None or instant > best[0]:
            best = (instant, row)
    if best is None:
        return None
    _instant, row = best
    fields = row[2 : 2 + len(_METRICS_FIELDS)]
    return dict(zip(_METRICS_FIELDS, fields))


def _backfill_metrics_symbol(
    lake_path: Path, spot_symbol: str, um_symbol: str, first: date, last: date,
    *, fetch: ArchiveFetch, sleep: Callable[[float], None], emit: Callable[[str], object], restart: bool,
) -> StreamSymbolResult:
    """Fetch and write ``spot_symbol``'s window, one day at a time.

    Unlike :func:`_backfill_monthly_stream`, the archive itself is keyed by
    day here (one zip per symbol per day), so resume (:func:`_day_already_written`)
    and the verified-file cache both operate at day granularity.
    """
    written = 0
    failed_periods: list[str] = []
    failure_messages: list[str] = []
    cache_key = f"{METRICS_STREAM}/{um_symbol}"

    day = first
    while day <= last:
        day_text = day.isoformat()
        if not restart and _day_already_written(lake_path, METRICS_STREAM, spot_symbol, day):
            day += timedelta(days=1)
            continue

        url, filename = _archive_zip_url(
            um_symbol, day_text, prefix=_UM_METRICS_PREFIX, interval="metrics", subdir=None
        )
        try:
            zip_bytes = fetch_verified_archive_zip(fetch, lake_path, cache_key, url, filename, sleep=sleep)
        except BarsBackfillError as exc:
            emit(json.dumps(
                {"phase": "error", "stream": METRICS_STREAM, "symbol": spot_symbol, "period": day_text, "error": str(exc)}
            ))
            failed_periods.append(day_text)
            failure_messages.append(str(exc))
            day += timedelta(days=1)
            continue

        if zip_bytes is not None:
            try:
                rows = _unzip_csv_rows(zip_bytes, filename)
                fields = _select_metrics_snapshot(rows, day, filename)
            except DerivsBackfillError as exc:
                emit(json.dumps(
                    {"phase": "error", "stream": METRICS_STREAM, "symbol": spot_symbol, "period": day_text, "error": str(exc)}
                ))
                failed_periods.append(day_text)
                failure_messages.append(str(exc))
                day += timedelta(days=1)
                continue
            if fields is not None:
                _write_row(lake_path, METRICS_STREAM, spot_symbol, day, fields)
                written += 1

        day += timedelta(days=1)

    if written == 0 and failed_periods:
        return StreamSymbolResult(
            stream=METRICS_STREAM,
            symbol=spot_symbol,
            status="error",
            failed_periods=tuple(failed_periods),
            error="; ".join(failure_messages),
        )
    return StreamSymbolResult(
        stream=METRICS_STREAM,
        symbol=spot_symbol,
        status="ok",
        rows_written=written,
        failed_periods=tuple(failed_periods),
    )


# -- --restart ------------------------------------------------------------


def _clear_derivs_caches(lake_path: Path) -> None:
    """``--restart``: clear the symbol map and every stream's verified-file
    cache, exactly as if the lake held none of them. Already-written
    partitions are left alone — a refetch overwrites them with the same
    bytes, exactly as bars_backfill's own ``--restart`` does."""
    _symbol_map_path(lake_path).unlink(missing_ok=True)
    cache_root = lake_path / RANK_CACHE_DIRNAME / ARCHIVE_CACHE_DIRNAME
    for stream in ALL_STREAMS:
        stream_dir = cache_root / stream
        if stream_dir.is_dir():
            shutil.rmtree(stream_dir)


# -- The orchestration ----------------------------------------------------


def _dedupe_streams(streams: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for stream in streams:
        stream = stream.strip()
        if not stream:
            continue
        if stream not in ALL_STREAMS:
            raise DerivsBackfillError(
                f"--streams names {stream!r}; must be one of {', '.join(ALL_STREAMS)}"
            )
        seen.setdefault(stream, None)
    if not seen:
        raise DerivsBackfillError(
            f"--streams must name at least one of {', '.join(ALL_STREAMS)}"
        )
    return tuple(seen)


def backfill_derivs(
    lake: str | Path,
    first: str | date,
    last: str | date,
    *,
    symbols_from: str | Path,
    streams: Sequence[str] = DEFAULT_STREAMS,
    fetch: ArchiveFetch | None = None,
    sleep: Callable[[float], None] | None = None,
    emit: Callable[[str], object] | None = None,
    restart: bool = False,
    workers: int = DEFAULT_WORKERS,
) -> tuple[StreamSymbolResult, ...]:
    """Backfill ``streams`` for every symbol ``symbols_from`` names.

    ``symbols_from`` is a path to a JSON file carrying a ``"symbols"``
    list — :mod:`nullius_ingest.bars_backfill`'s own ``universe.json`` is
    the intended caller, but any file with that shape works. Every symbol is
    mapped to a UM perpetual once (:func:`_resolve_symbol_map`, cached at
    ``<lake>/staging-meta/um-symbol-map.json``); a symbol with none produces
    one ``"skipped"`` result and no rows in any stream.

    ``emit``, when given, is called with one JSON line per (stream, symbol,
    period) failure as the run makes progress, ahead of the per-result lines
    a caller prints from this function's return value. ``restart`` clears
    the symbol map and every stream's verified-file cache
    (:func:`_clear_derivs_caches`) and ignores every already-written period,
    exactly as if the lake held none of them; the default resumes an
    interrupted run instead. ``workers`` bounds how many (stream, symbol)
    jobs run in parallel over a thread pool — the result order is always the
    requested streams' order, then the requested symbols' order, never
    completion order.
    """
    lake_path = Path(lake).expanduser()
    lake_path.mkdir(parents=True, exist_ok=True)
    first_date = _coerce_date(first)
    last_date = _coerce_date(last)
    if first_date > last_date:
        raise DerivsBackfillError(
            f"--first {first_date.isoformat()} is after --last {last_date.isoformat()}"
        )
    stream_list = _dedupe_streams(streams)
    if not isinstance(workers, int) or isinstance(workers, bool) or not (
        MIN_WORKERS <= workers <= MAX_WORKERS
    ):
        raise DerivsBackfillError(
            f"--workers must be an integer from {MIN_WORKERS} to {MAX_WORKERS}, "
            f"got {workers!r}"
        )

    resolved_fetch = fetch if fetch is not None else urllib_archive_fetch
    resolved_sleep = sleep if sleep is not None else _default_sleep
    resolved_emit: Callable[[str], object] = emit if emit is not None else (lambda _line: None)

    spot_symbols = _read_symbols_from(symbols_from)

    if restart:
        _clear_derivs_caches(lake_path)

    symbol_map = _resolve_symbol_map(
        lake_path, spot_symbols, fetch=resolved_fetch, sleep=resolved_sleep, restart=restart
    )

    results: list[StreamSymbolResult] = []
    for symbol in spot_symbols:
        entry = symbol_map.get(symbol, {})
        if entry.get("um_symbol") is None:
            results.append(
                StreamSymbolResult(
                    stream="*", symbol=symbol, status="skipped", reason="no UM perpetual mapped"
                )
            )

    jobs: list[tuple[str, str, str, int]] = [
        (stream, symbol, symbol_map[symbol]["um_symbol"], symbol_map[symbol]["scale"])
        for stream in stream_list
        for symbol in spot_symbols
        if symbol_map.get(symbol, {}).get("um_symbol") is not None
    ]

    def _run_job(job: tuple[str, str, str, int]) -> StreamSymbolResult:
        stream, spot_symbol, um_symbol, scale = job
        if stream == FUNDING_STREAM:
            return _backfill_funding_symbol(
                lake_path, spot_symbol, um_symbol, first_date, last_date,
                fetch=resolved_fetch, sleep=resolved_sleep, emit=resolved_emit, restart=restart,
            )
        if stream == FUTBARS_STREAM:
            return _backfill_futbars_symbol(
                lake_path, spot_symbol, um_symbol, scale, first_date, last_date,
                fetch=resolved_fetch, sleep=resolved_sleep, emit=resolved_emit, restart=restart,
            )
        return _backfill_metrics_symbol(
            lake_path, spot_symbol, um_symbol, first_date, last_date,
            fetch=resolved_fetch, sleep=resolved_sleep, emit=resolved_emit, restart=restart,
        )

    if jobs:
        job_results: dict[tuple[str, str, str, int], StreamSymbolResult] = {}
        with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            future_map = {pool.submit(_run_job, job): job for job in jobs}
            for future in as_completed(future_map):
                job_results[future_map[future]] = future.result()
        # Deterministic order -- requested streams, then requested symbols --
        # never completion order, which a thread pool would otherwise leave
        # to chance.
        for job in jobs:
            results.append(job_results[job])

    return tuple(results)


# -- The command line ----------------------------------------------------------


def _parse_streams_arg(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m nullius_ingest.derivs_backfill",
        description=(
            "Backfill USD-M futures funding rates, basis-input daily bars "
            "and (opt-in) open-interest metrics from Binance's public data "
            "archive into the lake's derivatives staging layout, with no "
            "API key."
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
        "--symbols-from",
        required=True,
        metavar="PATH",
        help="a JSON file (e.g. universe.json) carrying a 'symbols' list",
    )
    parser.add_argument(
        "--streams",
        default=",".join(DEFAULT_STREAMS),
        metavar="S,S,...",
        help=(
            f"comma-separated subset of {', '.join(ALL_STREAMS)} "
            f"(default: {','.join(DEFAULT_STREAMS)}; 'metrics' is opt-in, "
            f"about 30x more files than the other two)"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        metavar="N",
        help=f"how many (stream, symbol) jobs run in parallel (default {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="ignore and clear the symbol map and every stream's verified-file "
        "cache, and every already-written period, exactly as if the lake were empty",
    )
    return parser


def _print_line(line: str) -> None:
    print(line, flush=True)


def main(
    argv: Sequence[str] | None = None,
    *,
    emit: Callable[[str], object] = _print_line,
    fetch: ArchiveFetch | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """``python -m nullius_ingest.derivs_backfill --lake LAKE --first D --last D --symbols-from PATH [--streams S,S,...] [--workers N] [--restart]``.

    Prints an ``"error"`` line naming any (stream, symbol, period) that
    failed as the run makes progress, then one JSON line per (stream,
    symbol) result (or one per symbol with no UM perpetual) and one summary
    line. Returns :data:`EXIT_OK` when every stream, symbol and period
    backfilled (an unmapped symbol does not count against this);
    :data:`EXIT_REFUSED` when an argument was invalid (nothing is written),
    or any result carries an error or a failed period. An error not already
    reported as one of the lines above gives one stderr line and no
    traceback.
    """
    arguments = _build_parser().parse_args(argv)
    streams = _parse_streams_arg(arguments.streams)

    try:
        results = backfill_derivs(
            arguments.lake,
            arguments.first,
            arguments.last,
            symbols_from=arguments.symbols_from,
            streams=streams,
            fetch=fetch,
            sleep=sleep,
            emit=emit,
            restart=arguments.restart,
            workers=arguments.workers,
        )
    except DerivsBackfillError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 -- an operator sees one line, never a raw traceback
        print(f"unexpected error: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    had_error = False
    total_written = 0
    skipped = 0
    for result in results:
        emit(json.dumps(result.to_payload()))
        if result.status == "error" or result.failed_periods:
            had_error = True
        if result.status == "skipped":
            skipped += 1
        total_written += result.rows_written

    emit(json.dumps(
        {
            "results": len(results),
            "skipped": skipped,
            "failed": sum(1 for r in results if r.status == "error" or r.failed_periods),
            "rows_written": total_written,
        }
    ))
    return EXIT_REFUSED if had_error else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
