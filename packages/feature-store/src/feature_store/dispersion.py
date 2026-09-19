"""Feature 56's two market-wide computations: dispersion and return autocorrelation.

app_spec.xml, "Point-in-Time Feature Store", feature 56: *System computes
cross-sectional return dispersion plus return autocorrelation at several
lags, persisting them with feature_version stamps.*  This module is the
*computing* half of that sentence; :mod:`feature_store.dispersion_persistence`
is the persisting half.

The two are distinct kinds of fact about the same panel, and both are worth
stating plainly:

* **Cross-sectional dispersion** is a *width* — how far apart the universe's
  members' returns were, on the panel's final date.  A narrow cross-section
  is a market moving as one block; a wide one is a market where selection
  mattered.  It is a single number per date, over the cross-section, and its
  scale is the scale of the returns themselves.
* **Return autocorrelation** is a *memory* — how much a return resembles the
  return some ``lag`` days earlier.  It is computed at several lags at once
  (1, 2, 3, 5, 10 by default) because trend and mean-reversion live at
  different horizons: an autocorrelation of +0.2 at lag 1 and -0.15 at lag 10
  says something a single lag cannot.  It is a property of a *series* — here
  the panel's equal-weighted market return, one number per date — so it
  consumes the panel's whole history rather than its final column.

Both reductions are pure functions of their inputs: the same panel yields the
same numbers, in either order of computation, bit for bit.  That is the
reproducibility the replay path demands, and it is why the arithmetic here is
plain and its accumulation order fixed.

The two use the same definition of "return" as feature 57's correlation
(:func:`feature_store.regime._returns`: period-over-period log return,
missing-aware) and the same Pearson reduction
(:func:`feature_store.regime._pair_correlation`, pairwise-complete, refuse to
score too-little evidence) — deliberately shared rather than re-derived, so
two features of one store can never disagree about what a return is or what a
coefficient is.  They are sibling reductions of one member, not strangers.

Stdlib-only, like the rest of this member.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .regime import (
    PricePanel,
    _pair_correlation,
    _returns,
)

__all__ = [
    "DEFAULT_LAGS",
    "DEFAULT_MIN_OBSERVATIONS",
    "DEFAULT_MIN_SYMBOLS",
    "AutocorrelationResult",
    "DispersionMetrics",
    "DispersionResult",
    "build_dispersion_metrics",
    "cross_sectional_dispersion",
    "market_return_series",
    "return_autocorrelation",
]


#: Default autocorrelation lags, in trading days.  Several lags rather than one
#: because short-horizon trend (lag 1–3) and medium-horizon mean reversion
#: (lag 5–10) are different facts about the same series, and a regime feature
#: that reported only lag 1 would hide whichever one was absent.
DEFAULT_LAGS: tuple[int, ...] = (1, 2, 3, 5, 10)

#: Default minimum number of overlapping return pairs a lag needs to be
#: scored.  Ten pairs is a floor on "there is something to correlate here";
#: below it the coefficient is ``nan`` and the lag is reported as unscored,
#: rather than a number the data does not support.
DEFAULT_MIN_OBSERVATIONS = 10

#: Default minimum number of scored symbols before a dispersion is reported.
#: A spread over one symbol is not a cross-section, so ``n < min_symbols``
#: yields ``nan`` — the honest "no dispersion is computable" answer.
DEFAULT_MIN_SYMBOLS = 2


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispersionResult:
    """The cross-sectional dispersion, with the cross-section that produced it.

    ``dispersion`` is the population standard deviation of the scored
    symbols' final-period log returns — population rather than sample, because
    the scored cross-section *is* the set being described (the eligible
    universe on that date), not a sample drawn from a larger one.  ``mean_return``
    is the equal-weighted mean of the same returns, so a reader can tell a
    wide-but-drifting cross-section from a wide-and-flat one, and ``n`` is how
    many symbols were scored: a dispersion over 50 members and one over 3 are
    different facts wearing the same field.
    """

    dispersion: float
    mean_return: float
    n: int


@dataclass(frozen=True)
class AutocorrelationResult:
    """Return autocorrelation at several lags, with the sample behind each.

    ``lags`` and ``coefficients`` are parallel tuples in the same order: the
    coefficient at ``lags[i]`` is the Pearson correlation between the return
    series and itself shifted by that many observations, over the overlapping
    pairs.  ``observations`` records, per lag, how many pairs the coefficient
    was computed over (a lag the caller's history cannot serve is ``nan`` over
    zero pairs, never a default of zero), and ``min_observations`` is the floor
    the reduction applied.
    """

    lags: tuple[int, ...]
    coefficients: tuple[float, ...]
    observations: tuple[int, ...]
    min_observations: int

    def as_dict(self) -> dict[int, float]:
        """The coefficients keyed by lag, for a reader that wants one."""
        return dict(zip(self.lags, self.coefficients))

    def at(self, lag: int) -> float:
        """The coefficient at ``lag``; ``KeyError`` if it was not requested."""
        try:
            position = self.lags.index(lag)
        except ValueError:
            raise KeyError(
                f"lag {lag} was not computed; this result carries lags "
                f"{list(self.lags)}"
            ) from None
        return self.coefficients[position]

    def scored(self) -> dict[int, float]:
        """Only the lags that produced a finite coefficient."""
        return {
            lag: coefficient
            for lag, coefficient in zip(self.lags, self.coefficients)
            if not math.isnan(coefficient)
        }


@dataclass(frozen=True)
class DispersionMetrics:
    """Both feature-56 metrics over one panel, as one value.

    A convenience carrier for the pair the persistence path writes together,
    mirroring :class:`feature_store.regime.RegimeMetrics`.  The two are
    computed independently — one from the panel's final cross-section, one from
    its whole return history — and this only bundles them so a caller that
    wants both carries one object instead of two.
    """

    dispersion: DispersionResult
    autocorrelation: AutocorrelationResult


# ---------------------------------------------------------------------------
# Cross-sectional dispersion
# ---------------------------------------------------------------------------


def cross_sectional_dispersion(
    panel: PricePanel,
    *,
    min_symbols: int = DEFAULT_MIN_SYMBOLS,
) -> DispersionResult:
    """Cross-sectional dispersion of the panel's final-period returns.

    Takes each panel symbol's final-period log return — the return from the
    panel's second-to-last date to its final one — and reports the population
    standard deviation across those returns together with their equal-weighted
    mean and the count scored.

    A symbol whose close is missing, zero or non-finite on the panel's final
    *or* second-to-last date contributes no return and is **not scored**; it
    neither widens nor narrows the spread.  No fallback to the symbol's last
    traded pair is attempted, because the cross-section being measured is the
    one that existed on the panel's final date: reaching further back for one
    member would give that member a return spanning a different interval from
    every other member's, which is not a cross-section at one instant.  A gap
    day is an absent observation, not a reason to look further back — the same
    rule the breadth moving average follows.

    Fewer than ``min_symbols`` scored symbols, or a cross-section with no
    spread to measure, yields ``nan``: a dispersion over one symbol is not a
    cross-section, and reporting ``0.0`` would be a claim that the universe
    moved in lockstep when in truth nothing was measured.  ``n`` still reports
    how many symbols the answer rests on.
    """
    if min_symbols < 2:
        raise ValueError(
            f"min_symbols must be >= 2, got {min_symbols}; dispersion is a "
            "spread across a cross-section, which one symbol cannot form"
        )
    values: list[float] = []
    for symbol in panel.symbols:
        symbol_returns = _returns(panel.close(symbol))
        if not symbol_returns:
            continue
        latest = symbol_returns[-1]
        if math.isnan(latest):
            continue
        values.append(latest)
    n = len(values)
    if n == 0:
        return DispersionResult(
            dispersion=float("nan"), mean_return=float("nan"), n=0
        )
    mean_return = math.fsum(values) / n
    if n < min_symbols:
        return DispersionResult(
            dispersion=float("nan"), mean_return=mean_return, n=n
        )
    variance = math.fsum((value - mean_return) ** 2 for value in values) / n
    return DispersionResult(
        dispersion=math.sqrt(variance), mean_return=mean_return, n=n
    )


# ---------------------------------------------------------------------------
# Return autocorrelation
# ---------------------------------------------------------------------------


def market_return_series(panel: PricePanel) -> tuple[float, ...]:
    """The panel's equal-weighted market return, one value per *period return*.

    Aligned to returns, not to dates: with an ``n``-date panel this carries
    ``n - 1`` values, and element ``i`` is the market's return from the panel's
    date ``i`` to date ``i + 1`` — the same alignment
    :func:`feature_store.regime._returns` uses for one symbol, applied across
    the cross-section.  It is a cross-sectional reduction to one series per
    period, so the memory :func:`return_autocorrelation` measures is the
    *market's* memory rather than any single symbol's, which is what makes this
    a regime feature rather than a signal.

    Each value is the mean of the members that have a return over that period,
    skipping members that do not.  A period where no member has a return is
    ``nan`` — an absent observation, not a zero return — and
    :func:`return_autocorrelation` skips it pairwise rather than treating it as
    a flat day.
    """
    per_symbol = [_returns(panel.close(symbol)) for symbol in panel.symbols]
    length = max((len(series) for series in per_symbol), default=0)
    out: list[float] = []
    for position in range(length):
        present = [
            series[position]
            for series in per_symbol
            if position < len(series) and not math.isnan(series[position])
        ]
        out.append(math.fsum(present) / len(present) if present else float("nan"))
    return tuple(out)


def return_autocorrelation(
    series: Iterable[float],
    *,
    lags: Sequence[int] = DEFAULT_LAGS,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> AutocorrelationResult:
    """Pearson autocorrelation of ``series`` at each of ``lags``.

    For each lag, correlates the series against itself shifted by that many
    observations over the overlapping pairs, skipping pairs where either side
    is missing.  A lag with fewer than ``min_observations`` overlapping pairs,
    or with a flat leg either side of the shift, is not scored and reports
    ``nan`` — correlation is undefined without variance, and a default of zero
    would be indistinguishable from a measured absence of memory.

    ``lags`` must be distinct positive integers; duplicates would make
    "the coefficient at lag k" ambiguous and ``0`` would correlate the series
    with itself (a meaningless, always-perfect result), so both are rejected
    rather than silently accommodated.

    The reduction is the same pairwise-complete Pearson used for feature 57's
    mean pairwise correlation — one definition of a coefficient across the
    member.
    """
    values = tuple(float(value) for value in series)
    requested = tuple(lags)
    if not requested:
        raise ValueError("lags must name at least one lag to compute")
    for lag in requested:
        if not isinstance(lag, int) or isinstance(lag, bool):
            raise TypeError(f"lags must be integers; got {type(lag).__name__}")
        if lag < 1:
            raise ValueError(
                f"lags must be >= 1, got {lag}; lag 0 correlates the series "
                "with itself, which is not a memory"
            )
    if len(set(requested)) != len(requested):
        raise ValueError(f"lags must be distinct; got {list(requested)}")
    if min_observations < 2:
        raise ValueError(
            f"min_observations must be >= 2, got {min_observations}; a "
            "correlation over fewer than two pairs is not a correlation"
        )
    coefficients: list[float] = []
    observations: list[int] = []
    for lag in requested:
        if lag >= len(values):
            coefficients.append(float("nan"))
            observations.append(0)
            continue
        leading = values[:-lag]
        trailing = values[lag:]
        pairs = sum(
            1
            for left, right in zip(leading, trailing)
            if not math.isnan(left) and not math.isnan(right)
        )
        observations.append(pairs)
        coefficient = _pair_correlation(leading, trailing, min_observations)
        coefficients.append(float("nan") if coefficient is None else coefficient)
    return AutocorrelationResult(
        lags=requested,
        coefficients=tuple(coefficients),
        observations=tuple(observations),
        min_observations=min_observations,
    )


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------


def build_dispersion_metrics(
    panel: PricePanel,
    *,
    min_symbols: int = DEFAULT_MIN_SYMBOLS,
    lags: Sequence[int] = DEFAULT_LAGS,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> DispersionMetrics:
    """Compute both feature-56 metrics over one panel.

    One panel, one call, the cross-sectional dispersion and the several-lag
    autocorrelation of the panel's market return bundled in one
    :class:`DispersionMetrics` — the combined entry point the feature-56
    service and its persistence path drive, mirroring
    :func:`feature_store.regime.build_regime_metrics`.
    """
    return DispersionMetrics(
        dispersion=cross_sectional_dispersion(panel, min_symbols=min_symbols),
        autocorrelation=return_autocorrelation(
            market_return_series(panel),
            lags=lags,
            min_observations=min_observations,
        ),
    )
