"""Daily bar records — the universe build's only input.

The tradable universe is ranked by *dollar* volume (quote-asset turnover),
not share or base-asset volume: a billion cheap tokens and a hundred BTC
are not the same liquidity, and ranking by base volume would put them on
one axis. Binance daily klines carry this directly as
``quote_asset_volume``; wherever the number has to be derived it is
``close * volume`` for the day.

A :class:`DailyBar` is the minimal slice of a kline the universe needs:
symbol, UTC calendar date, dollar volume. The ingest workers own the full
schema and the lake layout; this member deliberately knows nothing about
Parquet, partitions or snapshots, so the universe computation stays
testable against synthesized bars and immune to ingest churn.

Validation happens at construction, not use: a negative or non-finite
dollar volume is a corrupt bar, and a corrupt bar must fail loudly at the
boundary rather than silently tilting a median. Survivorship integrity
starts with refusing to average over data nobody vouched for. The record
is frozen — bars are facts about the past, and facts do not get edited in
place (a restatement is a new bar that supersedes the old one).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

__all__ = ["DailyBar", "coerce_date"]


@dataclass(frozen=True)
class DailyBar:
    """One daily bar: symbol, UTC date, dollar volume for the day.

    ``date`` is the calendar date the daily candle *covers* (a Binance 1d
    kline open day, UTC) — not the moment it was fetched. The universe
    build treats it as the day the turnover happened, which is what makes
    trailing-window causality checkable: a bar dated inside the effective
    month can never contribute to that month's universe.
    """

    symbol: str
    date: dt.date
    dollar_volume: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("DailyBar symbol must be a non-empty, non-blank string")
        if not isinstance(self.date, dt.date):
            raise TypeError(
                f"DailyBar date must be a datetime.date, got {type(self.date).__name__}; "
                "use coerce_date() for strings and datetimes"
            )
        # A datetime IS a date subclass; a daily bar covers a whole day, so
        # accept a datetime but pin it to its UTC calendar date.
        if isinstance(self.date, dt.datetime):
            object.__setattr__(self, "date", self.date.date())
        if not isinstance(self.dollar_volume, (int, float)):
            raise TypeError(
                "DailyBar dollar_volume must be a number, got "
                f"{type(self.dollar_volume).__name__}"
            )
        if math.isnan(self.dollar_volume) or math.isinf(self.dollar_volume):
            raise ValueError(
                "DailyBar dollar_volume must be finite, got "
                f"{self.dollar_volume} for {self.symbol}"
            )
        if self.dollar_volume < 0:
            raise ValueError(
                f"DailyBar dollar_volume must be >= 0, got {self.dollar_volume} "
                f"for {self.symbol} on {self.date.isoformat()}"
            )
        object.__setattr__(self, "dollar_volume", float(self.dollar_volume))


def coerce_date(value: "str | dt.date | dt.datetime") -> dt.date:
    """Coerce an ISO date string, date or datetime to a ``datetime.date``.

    Accepts ``"2026-04-30"`` and ``"2026-04-30T00:00:00+00:00"`` alike;
    anything else raises ``ValueError``. Keeping coercion in one place means
    every caller that feeds the universe build agrees on what a date is.
    """
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
        try:
            # A full ISO timestamp names the same UTC day.
            return dt.datetime.fromisoformat(value).date()
        except ValueError as exc:
            raise ValueError(
                f"not an ISO date: {value!r} (expected 'YYYY-MM-DD')"
            ) from exc
    raise TypeError(f"cannot coerce {type(value).__name__} to a date")
