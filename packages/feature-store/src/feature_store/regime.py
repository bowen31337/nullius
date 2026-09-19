"""Feature 57's two market-wide computations: mean pairwise correlation and breadth.

app_spec.xml, "Point-in-Time Feature Store", feature 57: *System computes
mean pairwise correlation of the top 50 symbols plus breadth above an N-day
moving average, persisting both.*  Both are computed over the monthly
tradable universe (feature 40) rather than over the raw symbol list, so
"the top 50" names a fixed, point-in-time-true membership — the same
symbols the evaluator would have been able to trade at the snapshot's
effective month, never a survivorship-biased set chosen with later data.

Two reasons the computations live here, in the feature-store member, rather
than in the universe member they read from: feature 40 owns *which* symbols
are tradable (membership), and feature 57 owns *what the market did* across
those symbols (a cross-sectional reduction and a breadth count).  The
universe member deliberately knows nothing about prices or returns — it
ranks by dollar volume only — so the price-consuming half of the contract
belongs to this side of the boundary.  Both halves are keyed with the
market-wide sentinel symbol (feature 48 admits no four-component keys), and
both are pure functions of their inputs, so the same bars and the same
membership always yield the same two numbers, in either order of
computation — the bit-reproducibility the replay path demands.

Stdlib-only, like the rest of this member: the reduction is arithmetic over
plain records, and importing Polars for the lake would add a dependency the
computation does not need and a replay surface it must not gain.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Optional

from .bars import DailyBar, coerce_date

__all__ = [
    "DEFAULT_MIN_OVERLAP",
    "DEFAULT_BREADTH_WINDOW",
    "PricePanel",
    "CorrelationResult",
    "BreadthResult",
    "RegimeMetrics",
    "mean_pairwise_correlation",
    "breadth_above_moving_average",
    "build_regime_metrics",
]


#: Default minimum number of overlapping returns a pair needs to be scored.
#: A month of daily bars (~22) is far too few to trust a correlation; this
#: floor keeps the mean over pairs with a real history, and a caller with a
#: shorter panel simply gets fewer scored pairs.
DEFAULT_MIN_OVERLAP = 30

#: Default N-day moving-average lookback for the breadth count.  Fifty trading
#: days (~a quarter) is the lookback the breadth-above-MA signal names; a
#: caller with a shorter panel gets a smaller scored set, not an error.
DEFAULT_BREADTH_WINDOW = 50


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PricePanel:
    """A rectangular panel of daily closes: one aligned series per symbol.

    The correlation and breadth reductions both need, per symbol, the
    ordered list of closing prices on the dates the panel covers — and they
    need those dates to line up across symbols, so a "day" means the same
    calendar day in every series.  This is that aligned view: ``symbols``
    is the panel's membership in a stable order, and ``close(symbol)``
    returns that symbol's closes over the shared dates.

    Built from daily bars by collapsing duplicate ``(symbol, date)`` bars to
    the last one seen (the ingest layer owns exactly-once delivery; a
    restatement supersedes, it does not double-count a day) and intersecting
    each symbol's traded dates with the panel's date axis.  A symbol with no
    traded date on the axis contributes an all-missing series and simply
    drops out of whichever reduction needs a price that day.
    """

    dates: tuple[dt.date, ...]
    symbols: tuple[str, ...]
    _by_symbol: dict[str, tuple[float, ...]]

    @classmethod
    def from_bars(
        cls,
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence["str | dt.date | dt.datetime"],
    ) -> "PricePanel":
        """Assemble the panel from bars over the given membership and dates.

        ``symbols`` fixes the panel's columns (membership, in the given
        order — the universe's rank order) and ``dates`` fixes its rows (the
        shared date axis).  Every bar dated on the axis and for a panel
        symbol is placed in its cell; bars off the axis or for a non-member
        are ignored.  Duplicate ``(symbol, date)`` bars collapse to the last
        one seen.
        """
        axis = tuple(coerce_date(d) for d in dates)
        ordered_dates = tuple(dict.fromkeys(axis))  # de-dupe, keep order
        date_index = {date: position for position, date in enumerate(ordered_dates)}
        members = tuple(dict.fromkeys(symbols))  # de-dupe, keep order
        # One mutable row per member, then frozen; nan marks a missing price
        # (never None — the reductions test `math.isnan`, and a `None` in the
        # series would raise on the first `<= 0` comparison).
        rows: dict[str, list[float]] = {
            symbol: [float("nan")] * len(ordered_dates) for symbol in members
        }
        for bar in bars:
            if bar.symbol not in rows:
                continue
            position = date_index.get(bar.date)
            if position is None:
                continue
            rows[bar.symbol][position] = bar.close
        frozen = {symbol: tuple(values) for symbol, values in rows.items()}
        return cls(dates=ordered_dates, symbols=members, _by_symbol=frozen)

    def close(self, symbol: str) -> tuple[float, ...]:
        """This symbol's closes over the shared dates (missing as ``nan``)."""
        return self._by_symbol.get(symbol, ())


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorrelationResult:
    """The mean pairwise correlation, with the sample that produced it.

    ``mean`` is the average of the off-diagonal Pearson correlations over
    every symbol pair that had enough overlapping returns to score.  The
    provenance travels with the number: ``pairs`` is how many pairs were
    averaged, so a reader can tell a market-wide average over 1225 pairs
    from a thin one over three, and ``min_overlap`` is the overlap floor the
    reduction applied.
    """

    mean: float
    pairs: int
    min_overlap: int


@dataclass(frozen=True)
class BreadthResult:
    """The breadth count, with the parameters that produced it.

    ``count`` is how many of the panel's symbols closed above their own
    ``window``-day simple moving average on the breadth date; ``above`` and
    ``total`` break the same fact down as a numerator and a scored
    denominator, and ``window`` records the moving-average lookback the
    caller asked for.
    """

    count: int
    above: int
    total: int
    window: int


@dataclass(frozen=True)
class RegimeMetrics:
    """Both feature-57 metrics over one panel, as one value.

    A convenience carrier for the pair the persistence path writes together:
    the mean pairwise correlation and the breadth above the moving average,
    each with its own provenance.  The two are computed independently; this
    only bundles them so a caller that wants both — the feature-57 store —
    carries one object instead of two.
    """

    correlation: CorrelationResult
    breadth: BreadthResult


# ---------------------------------------------------------------------------
# Mean pairwise correlation
# ---------------------------------------------------------------------------


def _returns(prices: Sequence[float]) -> list[float]:
    """Period-over-period log returns of a price series (missing-aware).

    ``returns[i]`` is ``log(prices[i] / prices[i-1])`` when both prices are
    present, positive and finite; a missing, zero or non-finite price makes
    that return ``nan`` rather than raising, so one bad print degrades only
    the pairs that touch it, never the whole panel.
    """
    out: list[float] = []
    previous = prices[0] if prices else float("nan")
    for price in prices[1:]:
        if price <= 0 or previous <= 0 or math.isnan(price) or math.isnan(previous):
            out.append(float("nan"))
        else:
            out.append(math.log(price / previous))
        previous = price
    return out


def _pair_correlation(
    a: Sequence[float], b: Sequence[float], min_overlap: int
) -> Optional[float]:
    """Pearson correlation of two aligned return series, or ``None``.

    Only positions where *both* series have a finite return contribute;
    fewer than ``min_overlap`` such positions yields ``None`` (the pair is
    not scored rather than scored on too little to trust).  A pair with no
    variance in either leg is ``None`` too — correlation is undefined when a
    series is flat, and treating "0/0" as a perfect or zero correlation
    would be a number the data does not support.
    """
    xs: list[float] = []
    ys: list[float] = []
    for a_value, b_value in zip(a, b):
        if math.isnan(a_value) or math.isnan(b_value):
            continue
        xs.append(a_value)
        ys.append(b_value)
    n = len(xs)
    if n < min_overlap:
        return None
    x_mean = math.fsum(xs) / n
    y_mean = math.fsum(ys) / n
    covariance = 0.0
    x_sq = 0.0
    y_sq = 0.0
    for x_value, y_value in zip(xs, ys):
        x_delta = x_value - x_mean
        y_delta = y_value - y_mean
        covariance += x_delta * y_delta
        x_sq += x_delta * x_delta
        y_sq += y_delta * y_delta
    if x_sq == 0.0 or y_sq == 0.0:
        return None
    return covariance / math.sqrt(x_sq * y_sq)


def mean_pairwise_correlation(
    panel: PricePanel,
    *,
    min_overlap: int = 30,
) -> CorrelationResult:
    """Mean off-diagonal Pearson correlation across the panel's symbols.

    Converts each symbol's closes to log returns, correlates every unordered
    pair over their shared non-missing returns, and averages the
    off-diagonal coefficients.  A pair with fewer than ``min_overlap``
    overlapping returns, or with a flat leg, is not scored.  With fewer than
    two scorable symbols — an empty panel, or one where every series is
    missing — the mean is ``nan`` over zero pairs: the honest answer for "no
    correlation is computable here", visible as such rather than as a
    default of zero that a reader might mistake for decorrelation.

    The double loop counts each pair once (``j`` starts past ``i``), so the
    averaged set is exactly the off-diagonal coefficients — never the
    trivial self-correlations the diagonal would add, and never a pair
    twice.
    """
    if min_overlap < 1:
        raise ValueError(
            f"min_overlap must be >= 1, got {min_overlap}; a pair scored on "
            "no overlapping returns is a number the data does not support"
        )
    returns_by_symbol = {
        symbol: _returns(panel.close(symbol)) for symbol in panel.symbols
    }
    symbols = panel.symbols
    total = 0.0
    pairs = 0
    for i in range(len(symbols)):
        a = returns_by_symbol[symbols[i]]
        for j in range(i + 1, len(symbols)):
            coefficient = _pair_correlation(
                a, returns_by_symbol[symbols[j]], min_overlap
            )
            if coefficient is None:
                continue
            total += coefficient
            pairs += 1
    return CorrelationResult(
        mean=total / pairs if pairs else float("nan"),
        pairs=pairs,
        min_overlap=min_overlap,
    )


# ---------------------------------------------------------------------------
# Breadth above a moving average
# ---------------------------------------------------------------------------


def _simple_moving_average(values: Sequence[float], window: int) -> list[float]:
    """Trailing simple moving averages, aligned to the end of the window.

    ``sma[i]`` is the mean of ``values[i-window+1 .. i]`` when that many
    values are present; earlier positions, where the window is not yet full,
    are ``nan``.  The window slides over every position, missing values
    included, so the average is always over the ``window`` calendar slots
    ending at ``i`` — a gap day is an absent observation, not a reason to
    reach further back.
    """
    n = len(values)
    averages: list[float] = [float("nan")] * n
    if window < 1:
        return averages
    running = 0.0
    count = 0
    for index in range(n):
        value = values[index]
        if not math.isnan(value):
            running += value
            count += 1
        # Drop the value sliding out of the window, if it was counted.
        if index >= window:
            dropped = values[index - window]
            if not math.isnan(dropped):
                running -= dropped
                count -= 1
        if index >= window - 1 and count == window:
            averages[index] = running / window
    return averages


def breadth_above_moving_average(
    panel: PricePanel,
    *,
    window: int,
) -> BreadthResult:
    """How many symbols closed above their own ``window``-day average.

    For each panel symbol, compares its final close to the simple moving
    average of its final ``window`` closes (the breadth date's average must
    be fully formed — a symbol without ``window`` trailing closes is not
    scored), and counts those finishing above.  Returns the count together
    with the ``above`` numerator and ``total`` scored denominator; a panel
    where no symbol has a full window yields ``count = above = total = 0``,
    the honest "no breadth is computable" answer rather than a default.
    """
    if window < 1:
        raise ValueError(
            f"window must be >= 1, got {window}; a moving average over no "
            "days is undefined"
        )
    above = 0
    total = 0
    for symbol in panel.symbols:
        closes = panel.close(symbol)
        if not closes:
            continue
        averages = _simple_moving_average(closes, window)
        last_average = averages[-1]
        last_close = closes[-1]
        if math.isnan(last_average) or math.isnan(last_close):
            continue
        total += 1
        if last_close > last_average:
            above += 1
    return BreadthResult(count=above, above=above, total=total, window=window)


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------


def build_regime_metrics(
    panel: PricePanel,
    *,
    min_overlap: int = 30,
    breadth_window: int = 50,
) -> RegimeMetrics:
    """Compute both feature-57 metrics over one panel.

    A convenience over calling the two reductions separately: one panel, one
    call, the correlation and the breadth bundled in one
    :class:`RegimeMetrics`.  The two computations are independent and could be
    called apart; this exists so a single caller — the feature-57 persistence
    path — drives both from the same aligned view and carries them together.
    """
    return RegimeMetrics(
        correlation=mean_pairwise_correlation(panel, min_overlap=min_overlap),
        breadth=breadth_above_moving_average(panel, window=breadth_window),
    )
