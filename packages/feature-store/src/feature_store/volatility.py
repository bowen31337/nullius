"""Feature 55's two market-wide computations: realized volatility and vol-of-vol.

app_spec.xml, "Point-in-Time Feature Store", feature 55: *System computes
multi-horizon realized volatility plus volatility-of-volatility, persisting
each as a versioned regime feature.*  This module is the *computing* half of
that sentence; :mod:`feature_store.volatility_persistence` is the persisting
half, :mod:`feature_store.volatility_service` the seam that joins them.

The two are distinct kinds of fact about the same series, and both are worth
stating plainly:

* **Multi-horizon realized volatility** is a *magnitude* — how far the market
  moved, per day, as measured over each of several trailing windows.  Several
  horizons at once (10, 21, 63 by default) because calm-at-a-month and
  violent-at-a-fortnight are different regimes wearing one number if only the
  longest window is reported: a spike inside a tranquil quarter shows at the
  short horizon and is averaged away at the long one, and a regime feature
  that reported only one horizon would hide whichever contrast was absent.
* **Volatility-of-volatility** is an *instability* — how much the magnitude
  itself moved.  It is the population standard deviation of a trailing window
  of the base realized-volatility series (a rolling 21-day realized vol, one
  value per day), so a market whose vol is high but steady reads differently
  from one whose vol is the same on average but swinging — the distinction a
  regime labeler needs and a plain vol cannot express.

Both consume the market return series — the equal-weighted cross-sectional
mean of the universe's log returns, one value per period — the same series
feature 56's autocorrelation measures the memory of
(:func:`feature_store.dispersion.market_return_series`), and the same
definition of "return" feature 57's correlation uses
(:func:`feature_store.regime._returns`).  Deliberately shared rather than
re-derived: sibling reductions of one member must never disagree about what a
return is, and a regime feature keyed market-wide must describe the *market*,
never one instrument.

Estimator choices, stated once so the version stamp has something to name:

* realized volatility is ``sqrt(mean of squared returns)`` over the trailing
  ``horizon`` returns — squared returns, *not* squared deviations from a
  mean: over daily windows the mean return is noise, and demeaning would
  import the error of a mean estimate into a variance estimate.  The
  per-period root-mean-square keeps the horizons comparable (a raw sum of
  squares would grow with ``sqrt(horizon)`` for identical markets), and an
  ``annualization`` factor of ``sqrt(365)`` scales it to the familiar yearly
  units — crypto trades every calendar day.
* the window is *strict*: the trailing ``horizon`` slots of the series must
  all carry a return.  A gap is an absent observation, not a reason to reach
  further back — the same rule the breadth moving average follows — because a
  window that quietly reached back would average a different elapsed time at
  different horizons.
* vol-of-vol is the *population* standard deviation of the trailing vol
  observations (the scored window is the set being described, not a sample
  from a larger one — the same reasoning feature 56's dispersion applies),
  with the window's mean vol travelling beside it so a reader can tell a
  wide-and-high vol regime from a wide-but-low one.

Both reductions are pure functions of their inputs: the same series yields
the same numbers, in either order of computation, bit for bit.  That is the
reproducibility the replay path demands.

Stdlib-only, like the rest of this member.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .dispersion import market_return_series
from .regime import PricePanel

__all__ = [
    "ANNUALIZATION_PERIODS",
    "DEFAULT_BASE_WINDOW",
    "DEFAULT_HORIZONS",
    "DEFAULT_VOL_WINDOW",
    "RealizedVolatilityResult",
    "VolOfVolResult",
    "VolatilityMetrics",
    "build_volatility_metrics",
    "realized_volatility",
    "rolling_realized_volatility",
    "volatility_of_volatility",
]


#: Default realized-volatility horizons, in trading days.  Several horizons
#: rather than one because "multi-horizon" is the contract: the short window
#: (10) resolves spikes the long ones average away, the medium (21) is the
#: classic one-month estimate, and the long (63) a quarter's — a market calm
#: at two of the three and violent at the third is a fact only the pair of
#: them can state.
DEFAULT_HORIZONS: tuple[int, ...] = (10, 21, 63)

#: Default base window of the realized-volatility series the vol-of-vol is
#: the volatility of.  Twenty-one days (the classic trading month) is also a
#: member of :data:`DEFAULT_HORIZONS`, so the vol whose instability is
#: measured is the same vol the multi-horizon feature already reports at one
#: of its horizons — one definition of "the vol", not two.
DEFAULT_BASE_WINDOW = 21

#: Default number of base realized-vol observations the vol-of-vol is taken
#: over.  Sixty days (~a quarter of vols) is long enough for the vol's own
#: drift to register and short enough to still be a regime statement rather
#: than a market biography.
DEFAULT_VOL_WINDOW = 60

#: Periods per year the per-day estimates are annualized by (the multiplier
#: is its square root).  Crypto quotes trade every calendar day, so 365 —
#: not the 252 of equity convention; the panel's daily bars are calendar
#: days, and annualizing by the wrong calendar would bias every horizon by
#: the same wrong factor, silently.
ANNUALIZATION_PERIODS = 365.0


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealizedVolatilityResult:
    """Realized volatility at several horizons, with the sample behind each.

    ``horizons`` and ``volatilities`` are parallel tuples in the order asked
    for: ``volatilities[i]`` is the annualized root-mean-square of the final
    ``horizons[i]`` returns.  ``observations`` records, per horizon, how many
    of those trailing slots actually carried a return — a horizon the history
    cannot serve, or whose trailing window holds a gap, reports ``nan`` with
    the count saying *why* (zero slots served, or fewer than the window), never
    a default of zero a reader would mistake for a measured calm.
    ``annualization`` records the periods-per-year the per-day estimates were
    scaled by, so the numbers are self-describing about their units.
    """

    horizons: tuple[int, ...]
    volatilities: tuple[float, ...]
    observations: tuple[int, ...]
    annualization: float

    def at(self, horizon: int) -> float:
        """The volatility at ``horizon``; ``KeyError`` if it was not requested."""
        try:
            position = self.horizons.index(horizon)
        except ValueError:
            raise KeyError(
                f"horizon {horizon} was not computed; this result carries "
                f"horizons {list(self.horizons)}"
            ) from None
        return self.volatilities[position]

    def scored(self) -> dict[int, float]:
        """Only the horizons that produced a finite volatility."""
        return {
            horizon: volatility
            for horizon, volatility in zip(self.horizons, self.volatilities)
            if not math.isnan(volatility)
        }


@dataclass(frozen=True)
class VolOfVolResult:
    """The volatility-of-volatility, with the window that produced it.

    ``vol_of_vol`` is the population standard deviation of the trailing
    ``window`` observations of the annualized ``base_window``-day realized
    volatility.  ``mean_vol`` is the mean of the same observations, so a
    reader can tell a wide-but-low vol regime from a wide-and-high one — the
    two ask for different regime labels and different risk budgets.
    ``n`` is how many of the trailing slots carried a vol; fewer than
    ``window`` yields ``nan`` (with the mean still reported when ``n > 0``,
    exactly as feature 56's dispersion reports its mean over a thin
    cross-section), because a volatility over part of a window is a different
    elapsed time than the one asked for.
    """

    vol_of_vol: float
    mean_vol: float
    n: int
    base_window: int
    window: int
    annualization: float


@dataclass(frozen=True)
class VolatilityMetrics:
    """Both feature-55 metrics over one panel, as one value.

    A convenience carrier for the pair the persistence path writes together,
    mirroring :class:`feature_store.regime.RegimeMetrics` and
    :class:`feature_store.dispersion.DispersionMetrics`.  The two are computed
    independently — one from the market return series directly, one from the
    rolling vol series derived from it — and this only bundles them so a
    caller that wants both carries one object instead of two.
    """

    realized: RealizedVolatilityResult
    vol_of_vol: VolOfVolResult


# ---------------------------------------------------------------------------
# Multi-horizon realized volatility
# ---------------------------------------------------------------------------


def _require_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    """Validate a horizon set, returning it as a tuple in the given order."""
    requested = tuple(horizons)
    if not requested:
        raise ValueError("horizons must name at least one horizon to compute")
    for horizon in requested:
        if not isinstance(horizon, int) or isinstance(horizon, bool):
            raise TypeError(f"horizons must be integers; got {type(horizon).__name__}")
        if horizon < 1:
            raise ValueError(
                f"horizons must be >= 1, got {horizon}; a realized volatility "
                "over zero returns is not a magnitude"
            )
    if len(set(requested)) != len(requested):
        raise ValueError(f"horizons must be distinct; got {list(requested)}")
    return requested


def _require_annualization(annualization: float) -> float:
    """Validate the annualization factor, returning it as a float."""
    value = float(annualization)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"annualization must be a finite positive periods-per-year count; "
            f"got {annualization!r}"
        )
    return value


def realized_volatility(
    series: Iterable[float],
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    annualization: float = ANNUALIZATION_PERIODS,
) -> RealizedVolatilityResult:
    """Annualized root-mean-square return over each trailing ``horizons[i]``.

    For each horizon, takes the final ``horizon`` returns of ``series`` and
    reports ``sqrt(mean of their squares) * sqrt(annualization)``.  Squared
    returns, not squared deviations: see the module docstring for why the
    estimator is deliberately not demeaned.  The window is strict — every one
    of the trailing slots must carry a return, and a horizon whose window
    holds a gap (or extends past the start of the series) reports ``nan``,
    with ``observations`` saying how many slots were actually present.  A gap
    is an absent observation, not a reason to reach further back: reaching
    back would average a different elapsed time than the horizon names, and
    the horizons would stop being comparable.
    """
    values = tuple(float(value) for value in series)
    requested = _require_horizons(horizons)
    scale = math.sqrt(_require_annualization(annualization))
    volatilities: list[float] = []
    observations: list[int] = []
    for horizon in requested:
        if horizon > len(values):
            # The horizon extends past the start of the series: no window of
            # that length exists, so nothing was measured over it.
            volatilities.append(float("nan"))
            observations.append(0)
            continue
        window = values[-horizon:]
        present = sum(1 for value in window if not math.isnan(value))
        observations.append(present)
        if present < horizon:
            volatilities.append(float("nan"))
            continue
        mean_square = math.fsum(value * value for value in window) / horizon
        volatilities.append(math.sqrt(mean_square) * scale)
    return RealizedVolatilityResult(
        horizons=requested,
        volatilities=tuple(volatilities),
        observations=tuple(observations),
        annualization=float(annualization),
    )


def rolling_realized_volatility(
    series: Iterable[float],
    *,
    window: int,
    annualization: float = ANNUALIZATION_PERIODS,
) -> tuple[float, ...]:
    """Trailing realized volatility at every position, aligned to the series.

    ``out[i]`` is the annualized realized volatility over ``series[i-window+1
    .. i]`` when all ``window`` of those returns are present; earlier
    positions, and positions whose window holds a gap, are ``nan``.  The
    window slides over every position, missing values included — the same
    strict-slot rule :func:`feature_store.regime._simple_moving_average`
    follows — so a value at position ``i`` is always over exactly the
    ``window`` periods ending at ``i``, never a mixture reached further back.

    Each window is summed with :func:`math.fsum` — the same exact summation
    :func:`realized_volatility` applies to the trailing window — so when the
    base window equals one of the horizons (the version-1 default: 21), the
    final element of this series and ``result.at(21)`` agree bit for bit:
    one definition of "the vol", not two spellings of it that differ in the
    last ulp.

    This is the base series :func:`volatility_of_volatility` takes the
    instability of: one realized vol per day, not just the final one, because
    an instability is a property of a *series* of magnitudes, not of a
    single one.
    """
    if not isinstance(window, int) or isinstance(window, bool):
        raise TypeError(f"window must be an int; got {type(window).__name__}")
    if window < 1:
        raise ValueError(
            f"window must be >= 1, got {window}; a realized volatility over "
            "no returns is not a magnitude"
        )
    values = tuple(float(value) for value in series)
    scale = math.sqrt(_require_annualization(annualization))
    out: list[float] = [float("nan")] * len(values)
    for index in range(window - 1, len(values)):
        window_values = values[index - window + 1 : index + 1]
        if any(math.isnan(value) for value in window_values):
            continue  # the window holds a gap: nothing measured at position
        mean_square = math.fsum(value * value for value in window_values) / window
        out[index] = math.sqrt(mean_square) * scale
    return tuple(out)


# ---------------------------------------------------------------------------
# Volatility-of-volatility
# ---------------------------------------------------------------------------


def volatility_of_volatility(
    series: Iterable[float],
    *,
    base_window: int = DEFAULT_BASE_WINDOW,
    window: int = DEFAULT_VOL_WINDOW,
    annualization: float = ANNUALIZATION_PERIODS,
) -> VolOfVolResult:
    """The population standard deviation of the trailing realized-vol series.

    Builds the rolling ``base_window``-day realized volatility of ``series``
    (:func:`rolling_realized_volatility`), then reports the population
    standard deviation — and the mean — of its final ``window`` observations.
    Every one of those observations must be present: a vol-of-vol over part
    of a window is a volatility over a different elapsed time than the one
    asked for, so ``n < window`` yields ``nan`` rather than a number averaged
    over fewer days than the definition names (``mean_vol`` is still reported
    when ``n > 0``, the same courtesy dispersion extends to a thin
    cross-section).

    ``base_window`` and ``window`` must each be at least 2: a volatility over
    one return is a single absolute value with no averaging in it, and a
    spread over one vol observation is not a spread — the same floor feature
    56's dispersion places under its cross-section.
    """
    if not isinstance(base_window, int) or isinstance(base_window, bool):
        raise TypeError(f"base_window must be an int; got {type(base_window).__name__}")
    if base_window < 2:
        raise ValueError(
            f"base_window must be >= 2, got {base_window}; a realized "
            "volatility over one return is a single absolute value, not an "
            "estimate of a variance"
        )
    if not isinstance(window, int) or isinstance(window, bool):
        raise TypeError(f"window must be an int; got {type(window).__name__}")
    if window < 2:
        raise ValueError(
            f"window must be >= 2, got {window}; a spread over one vol "
            "observation is not an instability"
        )
    values = tuple(float(value) for value in series)
    vols = rolling_realized_volatility(
        values, window=base_window, annualization=annualization
    )
    annualized = _require_annualization(annualization)
    if window > len(vols):
        return VolOfVolResult(
            vol_of_vol=float("nan"),
            mean_vol=float("nan"),
            n=0,
            base_window=base_window,
            window=window,
            annualization=annualized,
        )
    tail = [vol for vol in vols[-window:] if not math.isnan(vol)]
    n = len(tail)
    if n == 0:
        return VolOfVolResult(
            vol_of_vol=float("nan"),
            mean_vol=float("nan"),
            n=0,
            base_window=base_window,
            window=window,
            annualization=annualized,
        )
    mean_vol = math.fsum(tail) / n
    if n < window:
        return VolOfVolResult(
            vol_of_vol=float("nan"),
            mean_vol=mean_vol,
            n=n,
            base_window=base_window,
            window=window,
            annualization=annualized,
        )
    variance = math.fsum((vol - mean_vol) ** 2 for vol in tail) / n
    return VolOfVolResult(
        vol_of_vol=math.sqrt(variance),
        mean_vol=mean_vol,
        n=n,
        base_window=base_window,
        window=window,
        annualization=annualized,
    )


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------


def build_volatility_metrics(
    panel: PricePanel,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    base_window: int = DEFAULT_BASE_WINDOW,
    vol_window: int = DEFAULT_VOL_WINDOW,
    annualization: float = ANNUALIZATION_PERIODS,
) -> VolatilityMetrics:
    """Compute both feature-55 metrics over one panel.

    One panel, one call: the market return series is taken once
    (:func:`feature_store.dispersion.market_return_series` — the same series
    the autocorrelation measures, so the member's regime features share one
    definition of "the market's return"), and both reductions run over it —
    the multi-horizon realized volatility directly, the vol-of-vol through
    its rolling base series.  Bundled in one :class:`VolatilityMetrics`, the
    combined entry point the feature-55 service and its persistence path
    drive, mirroring :func:`feature_store.regime.build_regime_metrics` and
    :func:`feature_store.dispersion.build_dispersion_metrics`.
    """
    returns = market_return_series(panel)
    return VolatilityMetrics(
        realized=realized_volatility(
            returns, horizons=horizons, annualization=annualization
        ),
        vol_of_vol=volatility_of_volatility(
            returns,
            base_window=base_window,
            window=vol_window,
            annualization=annualization,
        ),
    )
