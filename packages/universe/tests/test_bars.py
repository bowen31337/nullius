"""Acceptance tests for daily bar construction and coercion.

A corrupt bar must fail at the boundary, loudly: the universe ranks by
median dollar volume, so a negative or NaN volume that slips through
becomes a silently wrong liquidity ranking — exactly the class of quiet
corruption survivorship integrity exists to prevent.
"""

import datetime as dt
import math

import pytest

from universe import DailyBar, coerce_date

APRIL_1 = dt.date(2026, 4, 1)


def test_valid_bar_constructs() -> None:
    bar = DailyBar("BTCUSDT", APRIL_1, 1_250_000.5)
    assert bar.symbol == "BTCUSDT"
    assert bar.date == APRIL_1
    assert bar.dollar_volume == 1_250_000.5


def test_integer_volume_becomes_float() -> None:
    bar = DailyBar("ETHUSDT", APRIL_1, 1000)
    assert bar.dollar_volume == 1000.0
    assert isinstance(bar.dollar_volume, float)


def test_zero_volume_is_valid() -> None:
    # A day with no turnover is a fact, not corruption.
    assert DailyBar("XUSDT", APRIL_1, 0.0).dollar_volume == 0.0


@pytest.mark.parametrize("symbol", ["", "   "])
def test_blank_symbol_rejected(symbol: str) -> None:
    with pytest.raises(ValueError):
        DailyBar(symbol, APRIL_1, 1.0)


@pytest.mark.parametrize("volume", [-1.0, -0.01, -math.inf, math.inf])
def test_negative_or_non_finite_volume_rejected(volume: float) -> None:
    with pytest.raises(ValueError, match="dollar_volume"):
        DailyBar("BTCUSDT", APRIL_1, volume)


def test_nan_volume_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        DailyBar("BTCUSDT", APRIL_1, math.nan)


def test_non_numeric_volume_rejected() -> None:
    with pytest.raises(TypeError):
        DailyBar("BTCUSDT", APRIL_1, "1000")  # type: ignore[arg-type]


def test_non_date_rejected_with_hint() -> None:
    with pytest.raises(TypeError, match="coerce_date"):
        DailyBar("BTCUSDT", "2026-04-01", 1.0)  # type: ignore[arg-type]


def test_datetime_pins_to_calendar_date() -> None:
    stamp = dt.datetime(2026, 4, 1, 23, 59, 59, tzinfo=dt.timezone.utc)
    assert DailyBar("BTCUSDT", stamp, 1.0).date == APRIL_1


def test_error_names_symbol_and_date() -> None:
    with pytest.raises(ValueError, match="BTCUSDT.*2026-04-01"):
        DailyBar("BTCUSDT", APRIL_1, -5.0)


class TestCoerceDate:
    def test_date_passthrough(self) -> None:
        assert coerce_date(APRIL_1) == APRIL_1

    def test_datetime_to_date(self) -> None:
        assert coerce_date(dt.datetime(2026, 4, 1, 12)) == APRIL_1

    def test_iso_string(self) -> None:
        assert coerce_date("2026-04-01") == APRIL_1

    def test_iso_datetime_string(self) -> None:
        assert coerce_date("2026-04-01T00:00:00+00:00") == APRIL_1

    def test_bad_string_raises(self) -> None:
        with pytest.raises(ValueError, match="not an ISO date"):
            coerce_date("1 Apr 2026")

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(TypeError):
            coerce_date(20260401)  # type: ignore[arg-type]
