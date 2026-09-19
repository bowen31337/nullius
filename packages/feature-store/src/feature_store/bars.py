"""Daily price bars — feature 57's only input.

app_spec.xml feature 57 computes mean pairwise correlation and breadth above
a moving average over the top-50 universe.  Both reductions are price
reductions: correlation is Pearson over per-symbol returns, and breadth is a
count of symbols above their own trailing average — and neither exists
without a closing price per symbol per day.  The universe member's
``DailyBar`` (feature 40) deliberately carries only ``dollar_volume``,
because ranking liquidity needs no price; feature 57 needs the price, so it
owns the record that carries it.  The two ``DailyBar`` spellings are not a
collision but a boundary: feature 40 knows how liquid a symbol was, feature
57 knows what its price did, and neither record leaks the other's field.

A :class:`DailyBar` is the minimal price fact the reductions need: symbol,
UTC calendar date, close.  Validation happens at construction, not use — a
non-positive or non-finite close cannot take a log return, so a corrupt
price must fail loudly at the boundary rather than silently tilting a
correlation.  The record is frozen: a bar is a fact about the past, and a
restatement is a new bar that supersedes the old one, never an in-place edit.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

__all__ = ["DailyBar", "coerce_date"]


@dataclass(frozen=True)
class DailyBar:
    """One daily bar: symbol, UTC date, closing price for the day.

    ``date`` is the calendar date the daily candle *covers* — not the moment
    it was fetched — so the panel assembles closes onto a shared date axis by
    calendar day.  ``close`` is the day's closing price in the quote asset;
    returns and moving averages are all derived from this one field.
    """

    symbol: str
    date: dt.date
    close: float

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
        if not isinstance(self.close, (int, float)):
            raise TypeError(
                "DailyBar close must be a number, got "
                f"{type(self.close).__name__}"
            )
        if math.isnan(self.close) or math.isinf(self.close):
            raise ValueError(
                f"DailyBar close must be finite, got {self.close} for {self.symbol}"
            )
        if self.close <= 0:
            raise ValueError(
                f"DailyBar close must be > 0 (a non-positive price has no "
                f"log return), got {self.close} for {self.symbol} on "
                f"{self.date.isoformat()}"
            )
        object.__setattr__(self, "close", float(self.close))


def coerce_date(value: "str | dt.date | dt.datetime") -> dt.date:
    """Coerce an ISO date string, date or datetime to a ``datetime.date``.

    Accepts ``"2026-04-30"`` and ``"2026-04-30T00:00:00+00:00"`` alike;
    anything else raises ``ValueError``.  Keeping coercion in one place means
    every caller that feeds a panel agrees on what a date is.
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
