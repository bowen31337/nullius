"""Feature 55 as a composed application component: compute then persist both metrics.

app_spec.xml, "Point-in-Time Feature Store", feature 55: *System computes
multi-horizon realized volatility plus volatility-of-volatility, persisting
each as a versioned regime feature.*  This module is the whole feature at the
service seam: it takes the daily price bars and the sealed snapshot's hash,
builds the aligned panel over that snapshot's universe, takes the market
return series, computes the multi-horizon realized volatility and the
volatility-of-volatility over it, and persists each as its own versioned
feature-store record.

The three responsibilities sit on their own side of three boundaries, exactly
as features 56 and 57's services do:

* *Which symbols are tradable* is feature 40's answer — the universe's
  membership.  This service never ranks liquidity; it is *given* the symbols,
  so the market return the volatilities are taken over is always
  point-in-time-true.
* *What the market did* across them is :mod:`feature_store.volatility`'s
  answer — the panel, the market return series, the two reductions.  This
  delegates.
* *Storing what was computed, under which version* is
  :mod:`feature_store.volatility_persistence`'s answer — the two market-wide
  daily keys, the version stamps, the opaque payloads, the put/get.

So this service adds orchestration and nothing else: panel from bars +
membership, metrics from panel, records from metrics.

The factory's contract is one-way: a component builds itself from nothing.
:meth:`VolatilityService.from_env` is that self-construction.  It needs a
feature store to persist into; the store is composed once (feature 48) and
this borrows one — a fresh, empty store by default, or an explicit one for
tests and tools that route the same service at a shared store.  No
environment is read: the horizon set, the base and vol windows and the
annualization factor are *definition* parameters carried by
``feature_version``, so changing them is a definition change (feature 53)
that bumps the version, not an environment tweak that would silently
reinterpret rows already stored under version 1.

One consequence is worth stating, because it is the clause this feature is
written around: computing with different horizons than the version-1
definition names still stamps version 1 unless the caller stamps otherwise,
and the payload's definition block then disagrees with the definition it
names.  :meth:`VolatilityService.persist` therefore rejects that combination
outright — see its docstring.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence

from .bars import DailyBar
from .regime import PricePanel
from .store import FeatureStore
from .volatility import (
    ANNUALIZATION_PERIODS,
    DEFAULT_BASE_WINDOW,
    DEFAULT_HORIZONS,
    DEFAULT_VOL_WINDOW,
    VolatilityMetrics,
    build_volatility_metrics,
)
from .volatility_persistence import (
    FEATURE_VERSION,
    REALIZED_VOL_DEFINITION,
    VOL_OF_VOL_DEFINITION,
    VolatilityFeatureStore,
    definition_parameters,
)

__all__ = ["VolatilityService", "VersionMismatchError", "build_volatility_service"]


class VersionMismatchError(ValueError):
    """Computed parameters disagree with the definition the version stamp names.

    ``feature_version`` is part of a stored feature's identity (feature 48)
    and the payload records the definition that version 1 stands for.  A call
    that computes with, say, one horizon while stamping the version whose
    definition names the three-horizon set would store numbers under an
    address that promises something else — a record that is wrong by
    construction and that no reader could detect from the key alone.  That
    combination is refused rather than stamped.  (Feature 56's service raises
    a same-named, same-reasoned error of its own; the two spellings are
    independent definitions, one per feature, so neither feature's callers
    couple to the other's module.)
    """


class VolatilityService:
    """Compute feature 55's two metrics over a snapshot's universe and persist them.

    Thin by design: every method delegates to the pure computation
    (:mod:`feature_store.volatility`) or the persistence layer
    (:mod:`feature_store.volatility_persistence`), so the service adds panel
    assembly, store binding and the stamp/definition check, and nothing else.
    The feature store is captured at construction and every method still
    accepts an explicit override, so tests and tools can route the same
    service at a shared store without rebuilding it.
    """

    def __init__(
        self,
        store: FeatureStore | None = None,
        *,
        horizons: Sequence[int] = DEFAULT_HORIZONS,
        base_window: int = DEFAULT_BASE_WINDOW,
        vol_window: int = DEFAULT_VOL_WINDOW,
        annualization: float = ANNUALIZATION_PERIODS,
    ) -> None:
        self._store = store if store is not None else FeatureStore()
        self._volatility_store = VolatilityFeatureStore(self._store)
        self._horizons = tuple(horizons)
        self._base_window = base_window
        self._vol_window = vol_window
        self._annualization = annualization

    @classmethod
    def from_env(cls) -> VolatilityService:
        """Construct the component the application factory composes.

        Feature 55 has no environment knobs (see the module docstring), so
        this is the zero-argument, version-1-default construction the factory
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
        dates: Sequence[str | dt.date | dt.datetime],
    ) -> PricePanel:
        """Assemble the aligned price panel over ``symbols`` and ``dates``.

        The panel is the shared view every market-wide reduction consumes:
        one aligned series of closes per symbol over the shared date axis.
        ``symbols`` is the universe membership (rank order, from feature 40);
        ``dates`` is the axis (the snapshot's daily bars, in order).  The same
        panel type features 56 and 57 use — one definition of "aligned
        closes" across the member.
        """
        return PricePanel.from_bars(bars, symbols=symbols, dates=dates)

    # -- Computation --------------------------------------------------------

    def compute(
        self,
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[str | dt.date | dt.datetime],
        *,
        horizons: Sequence[int] | None = None,
        base_window: int | None = None,
        vol_window: int | None = None,
        annualization: float | None = None,
    ) -> VolatilityMetrics:
        """Compute both metrics over the panel built from the given inputs.

        Assembles the panel, takes its equal-weighted market return series,
        and computes the realized volatility at each horizon and the
        volatility-of-volatility of the rolling base series.  The keyword
        arguments override the service's defaults for this call; omit them to
        use the version-1 definition's values.
        """
        panel = self.build_panel(bars, symbols, dates)
        return build_volatility_metrics(
            panel,
            horizons=self._horizons if horizons is None else tuple(horizons),
            base_window=(
                self._base_window if base_window is None else base_window
            ),
            vol_window=self._vol_window if vol_window is None else vol_window,
            annualization=(
                self._annualization if annualization is None else annualization
            ),
        )

    # -- Persistence --------------------------------------------------------

    def persist(
        self,
        snapshot_hash: str,
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[str | dt.date | dt.datetime],
        *,
        top_n: int,
        horizons: Sequence[int] | None = None,
        base_window: int | None = None,
        vol_window: int | None = None,
        annualization: float | None = None,
        store: FeatureStore | None = None,
        replace: bool = False,
    ) -> VolatilityMetrics:
        """Compute both metrics and persist them, each version stamped.

        Computes the metrics over the panel built from ``bars``, ``symbols``
        and ``dates``, then stores each as its own feature-store record under
        its own market-wide daily feature name at ``snapshot_hash``, both
        carrying the current ``feature_version`` — "persisting each as a
        versioned regime feature" in one call.  ``top_n`` records how many
        universe members the metrics were computed over (it travels in each
        payload).  ``store`` overrides the service's store for this call, so
        a caller can route the persist at the shared composed store.  Returns
        the persisted metrics.

        Refuses a computation whose parameters disagree with the definition
        the stamp names (:class:`VersionMismatchError`): a horizon set, base
        window, vol window or annualization other than the version-1 ones
        would store numbers under an address that promises the version-1
        definition.  A genuinely different definition needs a new
        ``feature_version``, which is a change to this member's declaration
        (feature 53), not a keyword argument at a call site — so there is
        deliberately no way to pass one here.
        """
        effective_horizons = tuple(
            self._horizons if horizons is None else horizons
        )
        effective_base_window = (
            self._base_window if base_window is None else base_window
        )
        effective_vol_window = (
            self._vol_window if vol_window is None else vol_window
        )
        effective_annualization = (
            self._annualization if annualization is None else annualization
        )
        expected = definition_parameters()
        self._require_version_1_definition(
            "horizons", list(effective_horizons), expected["horizons"]
        )
        self._require_version_1_definition(
            "base_window", effective_base_window, expected["base_window"]
        )
        self._require_version_1_definition(
            "vol_window", effective_vol_window, expected["vol_window"]
        )
        self._require_version_1_definition(
            "annualization", effective_annualization, expected["annualization"]
        )
        metrics = self.compute(
            bars,
            symbols,
            dates,
            horizons=effective_horizons,
            base_window=effective_base_window,
            vol_window=effective_vol_window,
            annualization=effective_annualization,
        )
        volatility_store = VolatilityFeatureStore(
            store if store is not None else self._store
        )
        volatility_store.persist(
            snapshot_hash, metrics, top_n=top_n, replace=replace
        )
        return metrics

    @staticmethod
    def _require_version_1_definition(
        name: str, actual: object, declared: object
    ) -> None:
        """Reject a persist whose parameter contradicts the version stamp."""
        if actual != declared:
            raise VersionMismatchError(
                f"{name}={actual!r} does not match the version-"
                f"{FEATURE_VERSION} definition ({name}={declared!r}, "
                f"{REALIZED_VOL_DEFINITION}; {VOL_OF_VOL_DEFINITION}); a "
                "changed definition is a new feature_version, which leaves "
                "these rows untouched rather than storing a different thing "
                "under this address"
            )

    # -- Reading ------------------------------------------------------------

    def load(
        self, snapshot_hash: str, *, store: FeatureStore | None = None
    ) -> VolatilityMetrics | None:
        """Both metrics stored for ``snapshot_hash``, or ``None`` if none.

        Delegates to :meth:`VolatilityFeatureStore.load`; see there for the
        semantics of the neither-present and exactly-one-present cases.
        """
        volatility_store = VolatilityFeatureStore(
            store if store is not None else self._store
        )
        return volatility_store.load(snapshot_hash)


def build_volatility_service() -> VolatilityService:
    """Zero-argument builder registered with the application factory.

    Kept as a named module-level function (rather than passing
    ``VolatilityService.from_env`` directly) so the registry shows an intention
    rather than a classmethod, and so tests can assert on the builder
    independently of construction.
    """
    return VolatilityService.from_env()
