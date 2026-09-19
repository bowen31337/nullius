"""The monthly universe build: top-N by trailing 30-day median dollar volume.

Recomputed monthly, and strictly causal. The universe effective for a month
M is computed only from daily bars dated *before* M starts: the trailing
``window_days`` calendar days ending the day before the effective month.
For 2026-05 that window is [2026-04-01, 2026-04-30] — the whole of April,
because April has exactly 30 days; for 2026-03 it is [2026-01-30,
2026-02-28], a plain 30-day lookback rather than a calendar month. The rule
is "30 day median dollar volume", not "previous month".

Two properties are load-bearing enough to be enforced rather than implied:

*Causality.* A bar dated on or after the first day of month M cannot move
M's universe — not by exclusion, but by construction: the window filter
never admits it. The universe a decision at time t sees must be the
universe computable at t, which is what makes downstream replay honest.

*Determinism.* Ranking is a total order: median dollar volume descending,
ties broken by symbol ascending. No floating-point near-tie can flip the
order between two runs, and identical inputs produce identical members,
ranks and medians — the bit-reproducibility the replay path demands starts
here, where cross-sectional reductions get their symbol ordering.

Why the *median* rather than the mean of daily dollar volume: a single
liquidation cascade must not buy a thin symbol a month in the top-N. The
median is the spike-proof liquidity measure; the mean is the spike
amplifier.
"""

from __future__ import annotations

import datetime as dt
import statistics
from bisect import bisect_left
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Optional

from .bars import DailyBar, coerce_date
from .config import UniverseConfig

__all__ = [
    "UniverseMember",
    "MonthlyUniverse",
    "SkippedMonth",
    "UniverseBuildResult",
    "month_key",
    "month_start",
    "median_dollar_volumes",
    "build_monthly_universe",
    "build_monthly_universes",
]


# ---------------------------------------------------------------------------
# Month arithmetic (stdlib-only: no dateutil in the data spine)
# ---------------------------------------------------------------------------


def month_start(value: "str | dt.date | dt.datetime") -> dt.date:
    """Normalize any date-ish value to the first day of its month.

    ``date(2026, 5, 17)`` and ``"2026-05"`` both become ``date(2026, 5, 1)``:
    asking for "the universe for May" is asking for the month, not the day.
    Accepts an ISO ``YYYY-MM`` string (no day part) or any ISO date.
    """
    if isinstance(value, str):
        text = value.strip()
        parts = text.split("-")
        if len(parts) == 2:
            try:
                return dt.date(int(parts[0]), int(parts[1]), 1)
            except ValueError as exc:
                raise ValueError(f"not a month: {value!r}") from exc
        # Fall through to full ISO-date parsing for "YYYY-MM-DD".
        value = coerce_date(value)
    return coerce_date(value).replace(day=1)


def month_key(value: "str | dt.date | dt.datetime") -> str:
    """The canonical month identifier: ``"YYYY-MM"``."""
    start = month_start(value)
    return f"{start.year:04d}-{start.month:02d}"


def _next_month_start(start: dt.date) -> dt.date:
    # December rolls the year; no calendar library needed for one step.
    return dt.date(start.year + (start.month == 12), start.month % 12 + 1, 1)


def _iter_month_starts(first: dt.date, last: dt.date) -> Iterator[dt.date]:
    cursor = month_start(first)
    end = month_start(last)
    while cursor <= end:
        yield cursor
        cursor = _next_month_start(cursor)


def _window_bounds(effective_from: dt.date, window_days: int) -> tuple[dt.date, dt.date]:
    """The inclusive trailing window for a month starting ``effective_from``.

    Ends the day before the month starts, spans ``window_days`` calendar
    days, so a bar dated within the effective month is outside by
    construction — causality as arithmetic, not as a filter someone could
    forget to apply.
    """
    return (effective_from - dt.timedelta(days=window_days), effective_from - dt.timedelta(days=1))


def _window_has_a_date(
    sorted_dates: list[dt.date], window_start: dt.date, window_end: dt.date
) -> bool:
    """True when at least one date in ``sorted_dates`` falls in the window."""
    index = bisect_left(sorted_dates, window_start)
    return index < len(sorted_dates) and sorted_dates[index] <= window_end


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniverseMember:
    """One admitted symbol: its rank and the median that earned it."""

    symbol: str
    rank: int
    median_dollar_volume: float


@dataclass(frozen=True)
class MonthlyUniverse:
    """The tradable universe effective for one month, with its provenance.

    Carries the exact window and config it was computed from, so any later
    audit can distinguish "the data said so" from "someone rebuilt it with
    different knobs". ``symbols`` returns membership in rank order — the
    stable ordering every downstream reduction should consume.
    """

    month: str
    effective_from: dt.date
    window_start: dt.date
    window_end: dt.date
    config: UniverseConfig
    members: tuple[UniverseMember, ...]

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(member.symbol for member in self.members)

    def __len__(self) -> int:
        return len(self.members)


@dataclass(frozen=True)
class SkippedMonth:
    """A month the batch sweep declined to build, and why."""

    month: str
    reason: str


@dataclass(frozen=True)
class UniverseBuildResult:
    """Outcome of a batch sweep: what was built, and what was skipped."""

    builds: tuple[MonthlyUniverse, ...]
    skipped: tuple[SkippedMonth, ...]

    def __len__(self) -> int:
        return len(self.builds)


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def median_dollar_volumes(
    bars: Iterable[DailyBar],
    window_start: dt.date,
    window_end: dt.date,
    min_observations: int = 1,
) -> dict[str, float]:
    """Per-symbol median daily dollar volume over ``[window_start, window_end]``.

    Only bars dated inside the inclusive window contribute. A symbol with
    fewer than ``min_observations`` bars in the window has no median worth
    trusting and is absent from the result. Duplicated (symbol, date) bars
    are collapsed to the last one seen — the ingest layer owns
    exactly-once delivery; if it fails, the universe takes the freshest
    value rather than double-counting a day.

    Exposed publicly because the eligibility floor and the survivorship
    audit are the same number viewed differently: every consumer of
    "trailing 30-day median dollar volume" should compute it identically.
    """
    if window_end < window_start:
        raise ValueError(
            f"window_end {window_end} precedes window_start {window_start}"
        )
    by_symbol: dict[str, dict[dt.date, float]] = {}
    for bar in bars:
        if window_start <= bar.date <= window_end:
            by_symbol.setdefault(bar.symbol, {})[bar.date] = bar.dollar_volume
    medians: dict[str, float] = {}
    for symbol, volumes in by_symbol.items():
        if len(volumes) < min_observations:
            continue
        medians[symbol] = statistics.median(volumes.values())
    return medians


def build_monthly_universe(
    bars: Iterable[DailyBar],
    month: "str | dt.date | dt.datetime",
    config: Optional[UniverseConfig] = None,
) -> MonthlyUniverse:
    """Build the tradable universe effective for ``month`` from daily bars.

    Ranks every symbol with a median over the trailing window by median
    dollar volume (descending, ties broken by symbol ascending) and admits
    the top ``config.top_n``. A month with no eligible symbols yields an
    empty universe — the honest answer for a data gap, and visible as such
    rather than as an exception somebody caught and forgot.
    """
    cfg = config if config is not None else UniverseConfig()
    effective_from = month_start(month)
    window_start, window_end = _window_bounds(effective_from, cfg.window_days)
    medians = median_dollar_volumes(bars, window_start, window_end, cfg.min_observations)
    # Total order: liquidity descending, then symbol ascending. Deterministic
    # for any input, including exact float ties.
    ranked = sorted(medians.items(), key=lambda item: (-item[1], item[0]))
    members = tuple(
        UniverseMember(symbol=symbol, rank=position, median_dollar_volume=median)
        for position, (symbol, median) in enumerate(ranked[: cfg.top_n], start=1)
    )
    return MonthlyUniverse(
        month=month_key(effective_from),
        effective_from=effective_from,
        window_start=window_start,
        window_end=window_end,
        config=cfg,
        members=members,
    )


def build_monthly_universes(
    bars: Iterable[DailyBar],
    config: Optional[UniverseConfig] = None,
    months: Optional[Iterable["str | dt.date | dt.datetime"]] = None,
) -> UniverseBuildResult:
    """Build a universe for many months, in chronological order.

    With ``months`` given, each named month is built exactly as
    :func:`build_monthly_universe` would build it (empty universes
    included — an explicit ask gets the true answer).

    With ``months`` omitted, the sweep covers every month that contains at
    least one bar, from the first to the last. Months whose trailing window
    yields nothing are *skipped and reported*, not built empty: a data gap
    is an absence of evidence, and persisting an empty universe for it
    would launder that absence into a real observation. The skip reasons
    distinguish "no bars at all in the window" (a gap) from "bars present
    but nothing met the eligibility minimum" (a policy outcome).
    """
    cfg = config if config is not None else UniverseConfig()
    materialized = tuple(bars)

    if months is not None:
        starts = sorted({month_start(month) for month in months})
        builds = tuple(
            build_monthly_universe(materialized, start, cfg) for start in starts
        )
        return UniverseBuildResult(builds=builds, skipped=())

    if not materialized:
        return UniverseBuildResult(builds=(), skipped=())

    earliest = min(bar.date for bar in materialized)
    latest = max(bar.date for bar in materialized)
    # One sorted set of traded dates answers "any bar in this window?" per
    # month via bisect, instead of rescanning every bar for every month.
    traded_dates = sorted({bar.date for bar in materialized})
    builds: list[MonthlyUniverse] = []
    skipped: list[SkippedMonth] = []
    for start in _iter_month_starts(earliest, latest):
        universe = build_monthly_universe(materialized, start, cfg)
        window_start, window_end = _window_bounds(start, cfg.window_days)
        bars_in_window = _window_has_a_date(traded_dates, window_start, window_end)
        if universe.members:
            builds.append(universe)
        elif bars_in_window:
            skipped.append(
                SkippedMonth(
                    month=universe.month,
                    reason=(
                        f"no symbol reached the minimum of {cfg.min_observations} "
                        "daily bars in the trailing window"
                    ),
                )
            )
        else:
            skipped.append(
                SkippedMonth(
                    month=universe.month,
                    reason=f"no daily bars in the trailing window "
                    f"[{window_start.isoformat()}, {window_end.isoformat()}]",
                )
            )
    return UniverseBuildResult(builds=tuple(builds), skipped=tuple(skipped))
