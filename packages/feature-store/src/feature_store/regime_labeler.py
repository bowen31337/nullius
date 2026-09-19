"""Feature 58's computation: market-regime labels from a rolling-window fit.

app_spec.xml, "Point-in-Time Feature Store", feature 58: *System labels
market regimes using a rolling-window fit only, which rejects any labeler
configured to fit over full history.*  This module is the *labelling* half of
that sentence; :mod:`feature_store.regime_labeler_persistence` is the
persisting half and :mod:`feature_store.regime_labeler_service` the seam that
joins them.

The leakage this feature is written against, stated plainly.  A regime label
is a stratum — "calm", "turbulent", "crash" — assigned to each date so that
later a signal can be tested *within* a regime.  If the labeler that assigns
those strata is fit on the *whole* history, then the label on an early date
already knows how the market behaved on later dates: the clustering's
centroids are placed using future prints, so an early date is sorted into a
bucket whose boundaries were drawn with data that did not yet exist.  A signal
that "works in regime 2" then works only because regime 2 was carved out with
the signal's own future in view.  That is look-ahead leakage, and it is the
failure docs/alpha-engine-prd.md names beside the regime labeler.

The fix is a *causal* fit.  The label on date ``t`` is produced by a model
fit on the trailing ``window`` feature vectors ending at ``t`` — data dated
``<= t`` only, never a print after ``t``, and never the series as a whole.
The model is refit at every date, so each label rests on the history that
preceded it and nothing that followed.  This is the rolling-window fit the
clause demands, and it is why the labeler carries a finite ``window`` and
*refuses* one that would span the whole series.

The model is a k-means clustering over standardized regime features — the
multi-horizon realized volatility and the rolling volatility-of-volatility of
the market return series, the same market-wide quantities feature 55 persists
(feature 58 depends on feature 55, so the regimes the labeler names are the
regimes that feature's magnitudes and instabilities describe).  k-means is
chosen deliberately over the hidden-Markov model the PRD uses as its leakage
example: the anti-leakage property is a property of the *fit span*, not of the
model, and a clustering is a stdlib computation the replay path can reproduce
bit for bit, where an HMM's EM would import an iterative optimizer the member
otherwise avoids.  The window discipline is the same either way.

Two guards enforce "rolling-window fit only", both raising
:class:`FullHistoryFitError`:

* **Configuration guard.**  The labeler takes a finite ``window`` and offers
  no way to name "all of history".  A ``window`` that is not a finite positive
  integer — ``None`` in particular, the spelling of an unbounded span — is
  refused at construction, because an unbounded window *is* a full-history fit.
* **Degeneracy guard.**  At fit time the trailing window must be strictly
  shorter than the usable series.  A ``window`` greater than or equal to the
  number of computable feature vectors would make every label's fit span the
  entire available history — indistinguishable from the full-history fit the
  feature forbids — so it is refused rather than silently accommodated.

The features are standardized *within the fit window* (z-scores against that
window's own mean and spread), so the standardization, like the centroids, is
causal: the scaling applied to date ``t`` is learned from dates ``<= t`` only.
Reaching outside the window for the scale would reintroduce the future through
the back door.

Every computation is a pure, fixed-order function of its inputs — the feature
matrix, the window, the cluster count and a fixed k-means seed — so the same
panel yields the same labels in either order of computation, bit for bit.
That is the reproducibility the replay path demands, and it is why the k-means
uses a seeded, deterministic initialization and a deterministic tie-break
rather than the default RNG.

Stdlib-only, like the rest of this member.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from .dispersion import market_return_series
from .regime import PricePanel
from .volatility import (
    DEFAULT_BASE_WINDOW,
    DEFAULT_HORIZONS,
    DEFAULT_VOL_WINDOW,
    rolling_realized_volatility,
)

__all__ = [
    "DEFAULT_K",
    "DEFAULT_MAX_ITERS",
    "DEFAULT_WINDOW",
    "KMEANS_SEED",
    "FullHistoryFitError",
    "RegimeLabels",
    "RegimeLabeler",
    "regime_feature_matrix",
]


#: Number of regime strata the labeler carves the market into.  Three, so the
#: labels line up with the three coverage strata the regime plugin names —
#: high-volatility trend, low-volatility chop and crash (app_spec.xml feature
#: 283): the labeler's clusters are the same regimes that promotion counts
#: coverage across.
DEFAULT_K = 3

#: Default trailing fit window, in feature vectors (trading days).  Sixty-three
#: (~a quarter) is long enough for a k-means over four vol features to place
#: stable centroids and short enough that each date's fit still ends at that
#: date rather than reaching toward the present.
DEFAULT_WINDOW = 63

#: Fixed seed for the k-means initialization.  A constant, not the module RNG:
#: the labels must be reproducible across runs and machines, so the
#: initialization draws from a seeded generator whose stream never depends on
#: anything else that happened to call ``random`` first.
KMEANS_SEED = 0x52341

#: Iteration cap for the k-means Lloyd steps.  Reached only on a non-converging
#: configuration; the usual case converges far sooner and stops early.
DEFAULT_MAX_ITERS = 100

#: Convergence tolerance on centroid movement (max coordinate change).  Below
#: it the Lloyd iteration stops — the centroids have settled.
_CONVERGENCE_TOL = 1e-9


class FullHistoryFitError(ValueError):
    """The labeler was asked to fit over the whole history.

    Feature 58's labeler fits on a *trailing* window only; a fit over the full
    series is look-ahead leakage (the centroids would be placed using future
    prints) and is refused.  The refusal fires in two places, both here: a
    ``window`` that is not a finite positive integer at construction — the
    spelling of an unbounded, hence full-history, span — and a ``window`` at
    least as long as the usable series at fit time, which would make every
    label's fit span all the available history.  Subclasses :class:`ValueError`
    because asking for a full-history fit is a caller bug, never a runtime
    condition to retry or catch-and-continue.
    """


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeLabels:
    """The market's regime label at each return-axis date, with its fit span.

    ``dates`` is the panel's return-axis dates (one per period, aligned to the
    market return series), and ``labels`` is parallel to it: the cluster index
    (``0 .. k-1``) assigned to that date, or ``None`` where no label was
    produced — either because the date's feature vector was not computable (a
    horizon or the vol-of-vol window was not yet full) or because fewer than
    ``window`` computable vectors preceded it.  ``k`` and ``window`` travel
    with the labels so a reader can tell a three-regime quarterly fit from any
    other; ``n_labeled`` is how many dates actually received a label.
    """

    dates: tuple[dt.date, ...]
    labels: tuple["int | None", ...]
    k: int
    window: int
    n_labeled: int


# ---------------------------------------------------------------------------
# Regime feature matrix
# ---------------------------------------------------------------------------


def _rolling_vol_of_vol(
    returns: Sequence[float],
    *,
    base_window: int,
    vol_window: int,
    annualization: float,
) -> tuple[float, ...]:
    """Trailing vol-of-vol at every return position, aligned to ``returns``.

    The base realized-volatility series (:func:`rolling_realized_volatility`
    at ``base_window``) is one vol per day; this takes, at each position, the
    population standard deviation of its trailing ``vol_window`` vols — the
    same instability feature 55 reports, but as a *series* so every date has a
    vol-of-vol feature, not just the panel's last one.  Every one of the
    trailing slots must carry a vol: a vol-of-vol over part of a window is a
    different elapsed time than the one named, so a short window yields
    ``nan``.  A position with no base window yet (the first ``base_window-1``)
    is ``nan`` too.
    """
    base = rolling_realized_volatility(
        returns, window=base_window, annualization=annualization
    )
    out: list[float] = [float("nan")] * len(base)
    for index in range(len(base)):
        if index < vol_window - 1:
            continue
        tail = base[index - vol_window + 1 : index + 1]
        if any(math.isnan(value) for value in tail):
            continue
        mean = math.fsum(tail) / len(tail)
        variance = math.fsum((value - mean) ** 2 for value in tail) / len(tail)
        out[index] = math.sqrt(variance)
    return tuple(out)


def regime_feature_matrix(
    panel: PricePanel,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    base_window: int = DEFAULT_BASE_WINDOW,
    vol_window: int = DEFAULT_VOL_WINDOW,
    annualization: float = 365.0,
) -> tuple[tuple[dt.date, ...], list[list[float]]]:
    """The per-date regime feature matrix the labeler clusters over.

    One row per return-axis date (aligned to the market return series, so the
    row for period ``i`` describes the market state ending on the panel's date
    ``i + 1``).  The columns are the market's multi-horizon realized
    volatilities — a rolling realized vol per ``horizons`` member — followed by
    the rolling vol-of-vol: four features by default, all annualized, all
    market-wide, all derived from the single equal-weighted market return
    series (feature 55's ``market_return_series``).  A column is ``nan`` where
    its window is not yet full, and a row is only *usable* for labelling once
    every column carries a finite value — so the first usable row sits a full
    vol-of-vol window into the panel, never at its start.

    Market-wide and pure: the same panel yields the same matrix in either
    order of computation, so the labels built on it are reproducible.
    """
    returns = market_return_series(panel)
    axis = panel.dates[1:]  # one return-axis date per period return
    vol_columns: list[tuple[float, ...]] = [
        rolling_realized_volatility(
            returns, window=horizon, annualization=annualization
        )
        for horizon in horizons
    ]
    vol_columns.append(
        _rolling_vol_of_vol(
            returns,
            base_window=base_window,
            vol_window=vol_window,
            annualization=annualization,
        )
    )
    rows: list[list[float]] = [
        [column[position] for column in vol_columns]
        for position in range(len(returns))
    ]
    return axis, rows


# ---------------------------------------------------------------------------
# Deterministic k-means (the model; the window discipline is the point)
# ---------------------------------------------------------------------------


def _squared_distance(point: Sequence[float], center: Sequence[float]) -> float:
    """Squared Euclidean distance, summed exactly."""
    return math.fsum(
        (p - c) * (p - c) for p, c in zip(point, center)
    )


def _nearest_center(point: Sequence[float], centers: Sequence[Sequence[float]]) -> int:
    """Index of the nearest center, lowest index winning ties.

    Deterministic tie-break on purpose: two equidistant centers must always
    claim the point the same way, or the labels would depend on iteration
    order rather than the data.
    """
    best = 0
    best_distance = _squared_distance(point, centers[0])
    for index in range(1, len(centers)):
        distance = _squared_distance(point, centers[index])
        if distance < best_distance:
            best = index
            best_distance = distance
    return best


def _kmeans_pp_init(
    std_rows: Sequence[Sequence[float]], k: int, rng: random.Random
) -> list[list[float]]:
    """k-means++ initialization, seeded for reproducibility.

    The first center is the first row; each later center is drawn with
    probability proportional to its squared distance from the centers already
    chosen — the k-means++ spread, which keeps the result from depending on an
    arbitrary start.  The draw uses ``rng`` (seeded by the caller), so the
    initialization, and therefore the whole labelling, is deterministic.  When
    every remaining point coincides with a chosen center (zero total distance)
    the farthest row by index is taken, so a degenerate window still produces
    a full set of centers rather than crashing.
    """
    n = len(std_rows)
    centers = [list(std_rows[0])]
    distances = [_squared_distance(row, centers[0]) for row in std_rows]
    for _ in range(1, k):
        total = math.fsum(distances)
        if total <= 0.0:
            # Every row coincides with an existing center; pick the first row
            # not already used, by index, so the choice is deterministic.
            used = {tuple(center) for center in centers}
            fallback = next(
                (i for i in range(n) if tuple(std_rows[i]) not in used), 0
            )
            centers.append(list(std_rows[fallback]))
            continue
        threshold = rng.random() * total
        cumulative = 0.0
        chosen = n - 1
        for index in range(n):
            cumulative += distances[index]
            if cumulative >= threshold:
                chosen = index
                break
        centers.append(list(std_rows[chosen]))
        distances = [
            min(distance, _squared_distance(row, centers[-1]))
            for row, distance in zip(std_rows, distances)
        ]
    return centers


def _kmeans(
    std_rows: Sequence[Sequence[float]], k: int, *, seed: int, max_iters: int
) -> tuple[list[list[float]], tuple[int, ...]]:
    """Lloyd's k-means over standardized rows; deterministic and seeded.

    Initializes with seeded k-means++ then iterates assignment/update until the
    centroids stop moving (below :data:`_CONVERGENCE_TOL`) or ``max_iters`` is
    reached.  An empty cluster keeps its center rather than vanishing, so the
    center count — and therefore the label space ``0 .. k-1`` — is stable.
    Returns the final centers and the per-row cluster assignments.
    """
    centers = _kmeans_pp_init(std_rows, k, random.Random(seed))
    assignments = tuple(_nearest_center(row, centers) for row in std_rows)
    for _ in range(max_iters):
        new_centers: list[list[float]] = []
        for cluster in range(k):
            members = [
                std_rows[i] for i in range(len(std_rows)) if assignments[i] == cluster
            ]
            if members:
                dims = zip(*members)
                new_centers.append([math.fsum(col) / len(members) for col in dims])
            else:
                new_centers.append(list(centers[cluster]))
        moved = max(
            abs(new_centers[c][d] - centers[c][d])
            for c in range(k)
            for d in range(len(centers[c]))
        )
        centers = new_centers
        assignments = tuple(_nearest_center(row, centers) for row in std_rows)
        if moved <= _CONVERGENCE_TOL:
            break
    return centers, assignments


def _standardize(window_rows: Sequence[Sequence[float]]) -> list[list[float]]:
    """Z-score each column within the window (causal scale).

    The mean and spread are the window's own, so the scaling applied to the
    date being labelled is learned from that date's trailing window only —
    never from rows outside it.  A zero-variance column gets unit scale, so it
    neither divides by zero nor dominates; it simply carries no discrimination.
    """
    n = len(window_rows)
    dims = len(window_rows[0])
    means = [
        math.fsum(window_rows[i][d] for i in range(n)) / n for d in range(dims)
    ]
    stds = [
        math.sqrt(
            math.fsum((window_rows[i][d] - means[d]) ** 2 for i in range(n)) / n
        )
        for d in range(dims)
    ]
    standardized: list[list[float]] = []
    for row in window_rows:
        standardized.append(
            [
                (row[d] - means[d]) / (stds[d] if stds[d] > 0.0 else 1.0)
                for d in range(dims)
            ]
        )
    return standardized


# ---------------------------------------------------------------------------
# The labeler
# ---------------------------------------------------------------------------


class RegimeLabeler:
    """Assign a market-regime stratum to each date from a trailing-window fit.

    Thin and total: it holds the two fit parameters — the cluster count ``k``
    and the trailing ``window`` — validates them once at construction, and its
    one labelling method fits a fresh k-means on the trailing ``window``
    feature vectors at each date and reads off that date's cluster.  The fit
    span is the whole point: the model that labels date ``t`` sees only rows
    dated ``<= t``, so no label is drawn with the future in view.

    The labeler offers no full-history mode.  A ``window`` that is not a finite
    positive integer is refused at construction (an unbounded span is a
    full-history fit), and a ``window`` at least as long as the usable series
    is refused at fit time (every label would then span all the available
    history).  Both refusals raise :class:`FullHistoryFitError`.
    """

    def __init__(self, *, k: int = DEFAULT_K, window: int = DEFAULT_WINDOW) -> None:
        if not isinstance(k, int) or isinstance(k, bool):
            raise TypeError(f"k must be an int; got {type(k).__name__}")
        if k < 2:
            raise ValueError(
                f"k must be >= 2, got {k}; a single regime is not a labelling — "
                "every date would carry the same stratum"
            )
        # ``None`` is refused as a full-history fit before the type check,
        # because it is the sentinel for an unbounded span — the very
        # configuration the labeler exists to forbid — not a mere type error.
        if window is None:
            raise FullHistoryFitError(
                "window must be a finite positive integer; ``None`` names an "
                "unbounded span, which is a full-history fit the rolling-window "
                "labeler refuses"
            )
        if not isinstance(window, int) or isinstance(window, bool):
            raise TypeError(f"window must be an int; got {type(window).__name__}")
        if window < 1:
            raise FullHistoryFitError(
                f"window must be >= 1, got {window}; a non-positive window has no "
                "trailing span to fit on"
            )
        self._k = k
        self._window = window

    @property
    def k(self) -> int:
        """The number of regime strata this labeler assigns."""
        return self._k

    @property
    def window(self) -> int:
        """The trailing fit window, in feature vectors."""
        return self._window

    def label_features(
        self, rows: Sequence[Sequence[float]]
    ) -> tuple["int | None", ...]:
        """The regime label of each row, fit on its trailing window only.

        ``rows`` are the usable feature vectors in date order (every column
        finite — the caller has already dropped the un-computable ones).  For
        each position ``t`` from ``window-1`` on, fits a k-means on
        ``rows[t-window+1 .. t]`` — exactly ``window`` vectors, all dated
        ``<= t`` — standardizes within that window, and takes the cluster of
        the final row as the label.  Positions before ``window-1`` carry
        ``None``: not enough history yet for a full window.

        Refuses a ``window`` that spans the whole series
        (:class:`FullHistoryFitError`): with ``window >= len(rows)`` the single
        fit window *is* the entire available history, which is the full-history
        fit the labeler exists to forbid.
        """
        n = len(rows)
        if n == 0:
            return tuple()
        if self._window >= n:
            raise FullHistoryFitError(
                f"window={self._window} spans all {n} available feature vectors; "
                "a rolling-window labeler must fit on a trailing window strictly "
                "shorter than the series, never the full history"
            )
        labels: list["int | None"] = [None] * n
        for position in range(self._window - 1, n):
            window_rows = rows[position - self._window + 1 : position + 1]
            standardized = _standardize(window_rows)
            _, assignments = _kmeans(
                standardized, self._k, seed=KMEANS_SEED, max_iters=DEFAULT_MAX_ITERS
            )
            labels[position] = assignments[-1]
        return tuple(labels)

    def label_panel(self, panel: PricePanel) -> RegimeLabels:
        """Label a panel's market history, aligned to its return-axis dates.

        Builds the regime feature matrix (:func:`regime_feature_matrix`), drops
        the dates whose feature vector is not fully computable, labels the
        remaining usable vectors with :meth:`label_features`, and maps the
        labels back onto the full return-axis so each date carries either its
        stratum or ``None`` (un-computable features, or not yet a full window
        of history).  The fit span — and with it the full-history refusal — is
        exactly :meth:`label_features`'s.
        """
        dates, rows = regime_feature_matrix(panel)
        usable_dates: list[dt.date] = []
        usable_rows: list[list[float]] = []
        for date, row in zip(dates, rows):
            if all(math.isfinite(value) for value in row):
                usable_dates.append(date)
                usable_rows.append(row)
        usable_labels = self.label_features(usable_rows)
        label_by_date = dict(zip(usable_dates, usable_labels))
        labels = tuple(label_by_date.get(date) for date in dates)
        n_labeled = sum(1 for label in labels if label is not None)
        return RegimeLabels(
            dates=dates,
            labels=labels,
            k=self._k,
            window=self._window,
            n_labeled=n_labeled,
        )
