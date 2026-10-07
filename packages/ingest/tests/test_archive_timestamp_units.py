"""Archive epoch timestamps are read by magnitude, not assumed to be milliseconds.

Binance's public kline archive carries millisecond epochs through its
2024-12 file and switched to microsecond epochs from its 2025-01 file on,
with no flag distinguishing the two.  ``nullius_ingest.klines`` used to run
every ``open_time``/``close_time`` through ``_as_epoch_millis`` and
``_millis_to_utc`` unconditionally, so a 2025-on archive row's 16-digit
microsecond value got multiplied by another thousand and overflowed
:class:`~datetime.datetime` (``OverflowError: date value out of range``),
killing the survivorship-free backfill on the first 2025 file it read.

These tests pin the two real monthly files the bug report names
(``BTCUSDT-1d-2024-12.zip``, millisecond epochs; ``BTCUSDT-1d-2025-01.zip``,
microsecond epochs) under ``fixtures/binance_archive/``, verify each
fixture's checksum before trusting its bytes, and cover: both pinned files
parsing to the correct UTC instants, a batch mixing both units across the
2024/2025 year boundary, a value whose magnitude is neither unit being
refused with the named :class:`~nullius_ingest.klines.KlineTimestampUnitError`,
and the live REST path's millisecond rows parsing exactly as before.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nullius_ingest import KlineParseError, parse_klines
from nullius_ingest.klines import KlineTimestampUnitError

UTC = timezone.utc

_FIXTURES = Path(__file__).parent / "fixtures" / "binance_archive"

#: The two pinned monthly files the bug report names, each with its own
#: ``.CHECKSUM`` sidecar: 2024-12 carries 13-digit millisecond epochs
#: (``1733011200000``), 2025-01 carries 16-digit microsecond epochs
#: (``1735689600000000``) for the very same kind of instant — Binance's own
#: unit switch, mid-archive, with no flag naming it.
_ARCHIVE_CASES = {
    "2024-12-millis": (
        "BTCUSDT-1d-2024-12.zip",
        datetime(2024, 12, 1, tzinfo=UTC),
        datetime(2024, 12, 1, 23, 59, 59, 999000, tzinfo=UTC),
    ),
    "2025-01-micros": (
        "BTCUSDT-1d-2025-01.zip",
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, 23, 59, 59, 999999, tzinfo=UTC),
    ),
}


def _verify_checksum(zip_name: str) -> None:
    # The fixtures are real archive downloads; a corrupt or substituted file
    # would make every assertion below meaningless, so the checksum is
    # checked before a single byte of it is trusted.
    zip_path = _FIXTURES / zip_name
    checksum_path = _FIXTURES / f"{zip_name}.CHECKSUM"
    expected = checksum_path.read_text().split()[0]
    actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert actual == expected, (
        f"{zip_name} does not match its pinned .CHECKSUM; refusing to trust "
        f"its bytes"
    )


def _rows(zip_name: str) -> list[list[str]]:
    # Binance's archive kline CSV is positional, unheadered: open_time, open,
    # high, low, close, volume, close_time, quote_volume, count,
    # taker_buy_volume, taker_buy_quote_volume, ignore.  Read as plain
    # strings, exactly as a CSV reader hands them over with no type
    # conversion of its own — the venue's own spelling, same as a real
    # archive reader would pass to ``parse_klines``.
    zip_path = _FIXTURES / zip_name
    with zipfile.ZipFile(zip_path) as archive:
        [csv_name] = archive.namelist()
        with archive.open(csv_name) as handle:
            return list(csv.reader(io.TextIOWrapper(handle, encoding="utf-8")))


@pytest.mark.parametrize("case", sorted(_ARCHIVE_CASES))
def test_pinned_archive_checksum_matches(case: str) -> None:
    zip_name, _, _ = _ARCHIVE_CASES[case]
    _verify_checksum(zip_name)


@pytest.mark.parametrize("case", sorted(_ARCHIVE_CASES))
def test_pinned_archive_first_row_parses_to_the_right_utc_instants(
    case: str,
) -> None:
    zip_name, expected_open, expected_close = _ARCHIVE_CASES[case]
    _verify_checksum(zip_name)

    rows = _rows(zip_name)
    batch = parse_klines([rows[0]], "1d", symbol="BTCUSDT")

    assert len(batch) == 1
    only = batch.candles[0]
    assert only.open_time == expected_open
    assert only.close_time == expected_close
    assert only.open_time.tzinfo is UTC
    assert only.close_time.tzinfo is UTC


def test_a_mixed_unit_batch_spans_the_year_boundary_correctly() -> None:
    # The real backfill reads monthly files back to back; the last day of
    # 2024-12 (millisecond epoch) and the first day of 2025-01 (microsecond
    # epoch) land in the same kind of batch a multi-month fill produces, and
    # both units must resolve to the correct, adjacent UTC days in one parse.
    millis_row = [
        "1733961600000",  # 2024-12-12T00:00:00Z, 13-digit milliseconds
        "97000.00000000",
        "98000.00000000",
        "96000.00000000",
        "97500.00000000",
        "1000.00000000",
        "1734047999999",  # close: 2024-12-12T23:59:59.999Z
        "97000000.00000000",
        "100000",
        "500.00000000",
        "48500000.00000000",
        "0",
    ]
    micros_row = [
        "1735689600000000",  # 2025-01-01T00:00:00Z, 16-digit microseconds
        "93576.00000000",
        "95151.15000000",
        "92888.00000000",
        "94591.79000000",
        "10373.32613000",
        "1735775999999999",  # close: 2025-01-01T23:59:59.999999Z
        "975444194.13799830",
        "1516556",
        "5347.73648000",
        "502914035.64059070",
        "0",
    ]

    batch = parse_klines([millis_row, micros_row], "1d", symbol="BTCUSDT")

    assert len(batch) == 2
    first, second = batch.candles
    assert first.open_time == datetime(2024, 12, 12, tzinfo=UTC)
    assert first.close_time == datetime(2024, 12, 12, 23, 59, 59, 999000, tzinfo=UTC)
    assert second.open_time == datetime(2025, 1, 1, tzinfo=UTC)
    assert second.close_time == datetime(2025, 1, 1, 23, 59, 59, 999999, tzinfo=UTC)
    # The two candles are one calendar day apart; neither unit's conversion
    # drifted the other's instant off its true place on the series.
    assert (second.open_time - first.open_time).days == 20


def test_a_19_digit_epoch_value_is_refused_by_name() -> None:
    # Neither a 13-digit millisecond epoch nor a 16-to-17-digit microsecond
    # epoch: refused with the named error rather than guessed or let to
    # overflow datetime.
    bad_row = [
        "1735689600000000000",  # 19 digits
        "93576.00000000",
        "95151.15000000",
        "92888.00000000",
        "94591.79000000",
        "10373.32613000",
        "1735775999999999000",
        "975444194.13799830",
        "1516556",
        "5347.73648000",
        "502914035.64059070",
        "0",
    ]

    with pytest.raises(KlineTimestampUnitError) as excinfo:
        parse_klines([bad_row], "1d", symbol="BTCUSDT")

    assert isinstance(excinfo.value, KlineParseError)
    assert "1735689600000000000" in str(excinfo.value)


def test_rest_fixtures_millisecond_rows_are_unaffected() -> None:
    # The live REST/WS path stays millisecond-only; a 13-digit epoch must
    # keep parsing exactly as it did before the archive's microsecond epochs
    # were recognized.
    rest_open_ms = 1_772_366_400_000
    rest_close_ms = 1_772_366_460_000
    rest_candle = {
        "symbol": "BTCUSDT",
        "open": "61234.50",
        "high": "61300.00",
        "low": "61200.00",
        "close": "61250.00",
        "volume": "12.5",
        "open_time": rest_open_ms,
        "close_time": rest_close_ms,
        "trades": 42,
    }

    batch = parse_klines({"klines": [rest_candle]}, "1m")

    only = batch.candles[0]
    assert only.open_time == datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    assert only.close_time == datetime(2026, 3, 1, 12, 1, 0, tzinfo=UTC)
