"""Feature 57 as a composed application component: compute then persist both metrics.

app_spec.xml, "Point-in-Time Feature Store", feature 57: *System computes
mean pairwise correlation of the top 50 symbols plus breadth above an N-day
moving average, persisting both.*  This module is the whole feature at the
service seam: it takes the daily price bars and the sealed snapshot's hash,
builds the aligned panel over that snapshot's top-50 universe, computes the
two market-wide metrics, and persists both as feature-store records.

The three responsibilities are kept on their own side of three boundaries:

* *Which symbols are tradable* is feature 40's answer — the
  :class:`~universe.monthly.MonthlyUniverse` (or its ``symbols``).  This
  service never ranks liquidity; it is *given* the membership.  A caller that
  has the universe for the snapshot's effective month passes its symbols; the
  "top 50" is whatever that universe holds, so the reduction is always over a
  point-in-time-true set, never a survivorship-biased one.
* *What the market did* across those symbols is :mod:`regime`'s answer — the
  panel, the correlation, the breadth.  This service delegates to it.
* *Storing what was computed* is :mod:`persistence`'s answer — the two
  market-wide daily keys, the opaque payloads, the put/get.  This service
  delegates to it.

So this service is the orchestrator, and it adds orchestration and nothing
else: panel from bars + membership, metrics from panel, records from metrics.

The factory's contract is one-way: a component builds itself from nothing,
and the factory asks exactly that.  :meth:`RegimeService.from_env` is that
self-construction.  It needs a feature store to persist into; the store is
composed once (feature 48) and this borrows one — a fresh, empty store by
default, or an explicit one for tests and tools that route the same service
at a shared store.  No environment is read, because feature 57 has no knobs
that survive into the key: the top-N is the universe's own ``top_n``, and the
overlap floor and breadth window are fixed definition parameters carried in
``feature_version`` — changing them is a definition change (feature 53), not
an environment tweak.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Optional, Union

from .bars import DailyBar
from .persistence import (
    RegimeFeatureStore,
    RegimeMetrics,
)
from .regime import (
    DEFAULT_BREADTH_WINDOW,
    DEFAULT_MIN_OVERLAP,
    PricePanel,
    build_regime_metrics,
)
from .store import FeatureStore

__all__ = ["RegimeService", "build_regime_service"]


class RegimeService:
    """Compute feature 57's two metrics over a snapshot's universe and persist them.

    Thin by design: every method delegates to the pure computation
    (:mod:`regime`) or the persistence layer (:mod:`persistence`), so the
    service adds panel assembly and store binding and nothing else.  The
    feature store is captured at construction and every method still accepts
    an explicit override, so tests and tools can route the same service at a
    shared store without rebuilding it.
    """

    def __init__(
        self,
        store: Optional[FeatureStore] = None,
        *,
        min_overlap: int = DEFAULT_MIN_OVERLAP,
        breadth_window: int = DEFAULT_BREADTH_WINDOW,
    ) -> None:
        self._store = store if store is not None else FeatureStore()
        self._regime_store = RegimeFeatureStore(self._store)
        self._min_overlap = min_overlap
        self._breadth_window = breadth_window

    @classmethod
    def from_env(cls) -> "RegimeService":
        """Construct the component the application factory composes.

        Feature 57 has no environment knobs (see the module docstring), so
        this is the zero-argument, default-knob construction the factory
        calls.  The store is a fresh, empty one; a deployment that must share
        the composed ``feature-store`` component routes the service at it
        explicitly via :meth:`__init__` or :meth:`persist`.
        """
        return cls()

    # -- Panel assembly -----------------------------------------------------

    @staticmethod
    def build_panel(
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[Union[str, dt.date, dt.datetime]],
    ) -> PricePanel:
        """Assemble the aligned price panel over ``symbols`` and ``dates``.

        The panel is the shared view both reductions consume: one aligned
        series of closes per symbol over the shared date axis.  ``symbols``
        is the universe membership (rank order, from feature 40); ``dates``
        is the axis (the snapshot's daily bars, in order).  Delegates to
        :meth:`PricePanel.from_bars`.
        """
        return PricePanel.from_bars(bars, symbols=symbols, dates=dates)

    # -- Computation --------------------------------------------------------

    def compute(
        self,
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[Union[str, dt.date, dt.datetime]],
        *,
        min_overlap: Optional[int] = None,
        breadth_window: Optional[int] = None,
    ) -> RegimeMetrics:
        """Compute both metrics over the panel built from the given inputs.

        Assembles the panel, then computes the mean pairwise correlation and
        the breadth above the moving average over it.  ``min_overlap`` and
        ``breadth_window`` override the service's defaults for this call;
        omit them to use the definition defaults.
        """
        panel = self.build_panel(bars, symbols, dates)
        return build_regime_metrics(
            panel,
            min_overlap=self._min_overlap if min_overlap is None else min_overlap,
            breadth_window=(
                self._breadth_window if breadth_window is None else breadth_window
            ),
        )

    # -- Persistence --------------------------------------------------------

    def persist(
        self,
        snapshot_hash: str,
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[Union[str, dt.date, dt.datetime]],
        *,
        top_n: int,
        min_overlap: Optional[int] = None,
        breadth_window: Optional[int] = None,
        store: Optional[FeatureStore] = None,
    ) -> RegimeMetrics:
        """Compute both metrics and persist them for ``snapshot_hash``.

        Computes the metrics over the panel built from ``bars``, ``symbols``
        and ``dates``, then stores both as feature-store records under the
        market-wide daily keys at ``snapshot_hash`` — the whole of feature 57
        in one call.  ``top_n`` records how many universe members the metrics
        were computed over (it travels in each payload).  ``store`` overrides
        the service's store for this call, so a caller can route the persist
        at the shared composed store.  Returns the persisted metrics.
        """
        metrics = self.compute(
            bars,
            symbols,
            dates,
            min_overlap=min_overlap,
            breadth_window=breadth_window,
        )
        regime_store = RegimeFeatureStore(store if store is not None else self._store)
        regime_store.persist(snapshot_hash, metrics, top_n=top_n)
        return metrics

    # -- Reading ------------------------------------------------------------

    def load(self, snapshot_hash: str, *, store: Optional[FeatureStore] = None):
        """Both metrics stored for ``snapshot_hash``, or ``None`` if none.

        Delegates to :meth:`RegimeFeatureStore.load`; see there for the
        semantics of the neither-present and exactly-one-present cases.
        """
        regime_store = RegimeFeatureStore(store if store is not None else self._store)
        return regime_store.load(snapshot_hash)


def build_regime_service() -> RegimeService:
    """Zero-argument builder registered with the application factory.

    Kept as a named module-level function (rather than passing
    ``RegimeService.from_env`` directly) so the registry shows an intention
    rather than a classmethod, and so tests can assert on the builder
    independently of construction.
    """
    return RegimeService.from_env()
