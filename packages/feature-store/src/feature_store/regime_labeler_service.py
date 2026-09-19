"""Feature 58 as a composed application component: label then persist the regimes.

app_spec.xml, "Point-in-Time Feature Store", feature 58: *System labels
market regimes using a rolling-window fit only, which rejects any labeler
configured to fit over full history.*  This module is the whole feature at the
service seam: it takes the daily price bars and the sealed snapshot's hash,
builds the aligned panel over that snapshot's universe, labels each date with a
market-regime stratum from a trailing-window fit, and persists the labels as a
feature-store record stamped with a ``feature_version``.

The three responsibilities sit on their own side of three boundaries, exactly
as feature 56's service does:

* *Which symbols are tradable* is feature 40's answer — the universe's
  membership.  This service never ranks liquidity; it is *given* the symbols,
  so the market return the labels are taken over is always point-in-time-true.
* *What regime each date was in* is
  :mod:`feature_store.regime_labeler`'s answer — the panel, the feature matrix,
  the trailing-window k-means.  This delegates.
* *Storing what was computed, under which version* is
  :mod:`feature_store.regime_labeler_persistence`'s answer — the market-wide
  daily key, the version stamp, the opaque payload, the put/get.

So this service adds orchestration and nothing else: panel from bars +
membership, labels from panel, record from labels.

The factory's contract is one-way: a component builds itself from nothing.
:meth:`RegimeLabelerService.from_env` is that self-construction.  It needs a
feature store to persist into; the store is composed once (feature 48) and
this borrows one — a fresh, empty store by default, or an explicit one for
tests and tools that route the same service at a shared store.  No environment
is read: the cluster count and the fit window are *definition* parameters
carried by ``feature_version``, so changing them is a definition change
(feature 53) that bumps the version, not an environment tweak that would
silently reinterpret rows already stored under version 1.

One consequence is worth stating, because it is the clause this feature is
written around: the labeler offers no full-history mode.  A ``window`` that is
not a finite positive integer is refused at construction, and a ``window`` at
least as long as the usable series is refused at fit time — both raising
:class:`~feature_store.regime_labeler.FullHistoryFitError`.  That is feature
58's "rolling-window fit only" enforced at the service's own seam: a caller
that tries to fit over the full history gets the refusal, not a set of labels
drawn with the future in view.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence

from .bars import DailyBar
from .regime import PricePanel
from .regime_labeler import (
    DEFAULT_K,
    DEFAULT_WINDOW,
    FullHistoryFitError,
    RegimeLabeler,
    RegimeLabels,
)
from .regime_labeler_persistence import (
    FEATURE_VERSION,
    RegimeLabelerFeatureStore,
)
from .store import FeatureStore

__all__ = ["RegimeLabelerService", "build_regime_labeler_service"]


class RegimeLabelerService:
    """Label a snapshot's market history with a trailing-window fit and persist.

    Thin by design: every method delegates to the pure computation
    (:mod:`feature_store.regime_labeler`) or the persistence layer
    (:mod:`feature_store.regime_labeler_persistence`), so the service adds
    panel assembly, store binding and the labeler's fit-span guard, and nothing
    else.  The feature store is captured at construction and every method still
    accepts an explicit override, so tests and tools can route the same service
    at a shared store without rebuilding it.
    """

    def __init__(
        self,
        store: FeatureStore | None = None,
        *,
        k: int = DEFAULT_K,
        window: int = DEFAULT_WINDOW,
    ) -> None:
        self._store = store if store is not None else FeatureStore()
        self._labeler_store = RegimeLabelerFeatureStore(self._store)
        self._labeler = RegimeLabeler(k=k, window=window)

    @classmethod
    def from_env(cls) -> RegimeLabelerService:
        """Construct the component the application factory composes.

        Feature 58 has no environment knobs (see the module docstring), so this
        is the zero-argument, version-1-default construction the factory calls.
        The store is a fresh, empty one; a deployment that must share the
        composed ``feature-store`` component routes the service at it
        explicitly via :meth:`__init__` or :meth:`persist`.
        """
        return cls()

    # -- Panel assembly -----------------------------------------------------

    @staticmethod
    def build_panel(
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[str | dt.date | dt.datetime],
    ) -> PricePanel:
        """Assemble the aligned price panel over ``symbols`` and ``dates``.

        The panel is the view the labeler consumes: one aligned series of
        closes per symbol over the shared date axis.  ``symbols`` is the
        universe membership (rank order, from feature 40); ``dates`` is the
        axis (the snapshot's daily bars, in order).  The same panel type
        features 55, 56 and 57 use — one definition of "aligned closes" across
        the member.
        """
        return PricePanel.from_bars(bars, symbols=symbols, dates=dates)

    # -- Computation --------------------------------------------------------

    def compute(
        self,
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[str | dt.date | dt.datetime],
        *,
        k: int | None = None,
        window: int | None = None,
    ) -> RegimeLabels:
        """Label the panel built from the given inputs, on a trailing window.

        Assembles the panel and labels each date with a market-regime stratum,
        each label fit on the trailing ``window`` feature vectors ending at
        that date.  ``k`` and ``window`` override the service's defaults for
        this call; omit them to use the version-1 definition's values.

        Raises :class:`FullHistoryFitError` when the fit span would cover the
        whole series — the rolling-window fit only, which feature 58 demands.
        """
        panel = self.build_panel(bars, symbols, dates)
        labeler = RegimeLabeler(
            k=self._labeler.k if k is None else k,
            window=self._labeler.window if window is None else window,
        )
        return labeler.label_panel(panel)

    # -- Persistence --------------------------------------------------------

    def persist(
        self,
        snapshot_hash: str,
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[str | dt.date | dt.datetime],
        *,
        top_n: int,
        k: int | None = None,
        window: int | None = None,
        store: FeatureStore | None = None,
        replace: bool = False,
    ) -> RegimeLabels:
        """Label the panel and persist the labels, version stamped.

        Computes the labels over the panel built from ``bars``, ``symbols`` and
        ``dates``, then stores them as a single feature-store record under the
        market-wide daily key at ``snapshot_hash``, carrying the current
        ``feature_version``.  ``top_n`` records how many universe members the
        labels were computed over (it travels in the payload).  ``store``
        overrides the service's store for this call, so a caller can route the
        persist at the shared composed store.  Returns the persisted labels.

        Refuses a full-history fit (:class:`FullHistoryFitError`): a ``window``
        at least as long as the usable series would make every label's fit span
        all the available history, which is the leakage the feature forbids.
        """
        labels = self.compute(
            bars,
            symbols,
            dates,
            k=k,
            window=window,
        )
        labeler_store = RegimeLabelerFeatureStore(
            store if store is not None else self._store
        )
        labeler_store.persist(
            snapshot_hash, labels, top_n=top_n, replace=replace
        )
        return labels

    # -- Reading ------------------------------------------------------------

    def load(
        self, snapshot_hash: str, *, store: FeatureStore | None = None
    ) -> RegimeLabels | None:
        """The stored labels for ``snapshot_hash``, or ``None`` if absent.

        Delegates to :meth:`RegimeLabelerFeatureStore.load`; an unpersisted
        snapshot — a normal point-in-time miss — returns ``None``.
        """
        labeler_store = RegimeLabelerFeatureStore(
            store if store is not None else self._store
        )
        return labeler_store.load(snapshot_hash)


def build_regime_labeler_service() -> RegimeLabelerService:
    """Zero-argument builder registered with the application factory.

    Kept as a named module-level function (rather than passing
    ``RegimeLabelerService.from_env`` directly) so the registry shows an
    intention rather than a classmethod, and so tests can assert on the builder
    independently of construction.
    """
    return RegimeLabelerService.from_env()
