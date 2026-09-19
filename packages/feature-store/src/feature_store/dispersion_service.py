"""Feature 56 as a composed application component: compute then persist both metrics.

app_spec.xml, "Point-in-Time Feature Store", feature 56: *System computes
cross-sectional return dispersion plus return autocorrelation at several
lags, persisting them with feature_version stamps.*  This module is the whole
feature at the service seam: it takes the daily price bars and the sealed
snapshot's hash, builds the aligned panel over that snapshot's universe,
computes the cross-sectional dispersion and the several-lag autocorrelation,
and persists both as feature-store records stamped with a ``feature_version``.

The three responsibilities sit on their own side of three boundaries, exactly
as feature 57's service does:

* *Which symbols are tradable* is feature 40's answer — the universe's
  membership.  This service never ranks liquidity; it is *given* the symbols,
  so the cross-section is always point-in-time-true.
* *What the market did* across them is :mod:`feature_store.dispersion`'s
  answer — the panel, the dispersion, the autocorrelation.  This delegates.
* *Storing what was computed, under which version* is
  :mod:`feature_store.dispersion_persistence`'s answer — the two market-wide
  daily keys, the version stamps, the opaque payloads, the put/get.

So this service adds orchestration and nothing else: panel from bars +
membership, metrics from panel, records from metrics.

The factory's contract is one-way: a component builds itself from nothing.
:meth:`DispersionService.from_env` is that self-construction.  It needs a
feature store to persist into; the store is composed once (feature 48) and
this borrows one — a fresh, empty store by default, or an explicit one for
tests and tools that route the same service at a shared store.  No environment
is read: the lag set, the dispersion floor and the observation floor are
*definition* parameters carried by ``feature_version``, so changing them is a
definition change (feature 53) that bumps the version, not an environment
tweak that would silently reinterpret rows already stored under version 1.

One consequence is worth stating, because it is the clause this feature is
written around: computing with different lags than the version-1 definition
names still stamps version 1 unless the caller stamps otherwise, and the
payload's ``parameters`` block then disagrees with the definition it names.
:meth:`DispersionService.persist` therefore rejects that combination outright
— see its docstring.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence

from .bars import DailyBar
from .dispersion import (
    DEFAULT_LAGS,
    DEFAULT_MIN_OBSERVATIONS,
    DEFAULT_MIN_SYMBOLS,
    DispersionMetrics,
    build_dispersion_metrics,
)
from .dispersion_persistence import (
    AUTOCORRELATION_DEFINITION,
    DISPERSION_DEFINITION,
    FEATURE_VERSION,
    DispersionFeatureStore,
    definition_parameters,
)
from .regime import PricePanel
from .store import FeatureStore

__all__ = ["DispersionService", "VersionMismatchError", "build_dispersion_service"]


class VersionMismatchError(ValueError):
    """Computed parameters disagree with the definition the version stamp names.

    ``feature_version`` is part of a stored feature's identity (feature 48)
    and the payload records the definition that version 1 stands for.  A call
    that computes with, say, three lags while stamping the version whose
    definition names the five-lag set would store numbers under an address
    that promises something else — a record that is wrong by construction and
    that no reader could detect from the key alone.  That combination is
    refused rather than stamped.
    """


class DispersionService:
    """Compute feature 56's two metrics over a snapshot's universe and persist them.

    Thin by design: every method delegates to the pure computation
    (:mod:`feature_store.dispersion`) or the persistence layer
    (:mod:`feature_store.dispersion_persistence`), so the service adds panel
    assembly, store binding and the stamp/definition check, and nothing else.
    The feature store is captured at construction and every method still
    accepts an explicit override, so tests and tools can route the same
    service at a shared store without rebuilding it.
    """

    def __init__(
        self,
        store: FeatureStore | None = None,
        *,
        lags: Sequence[int] = DEFAULT_LAGS,
        min_symbols: int = DEFAULT_MIN_SYMBOLS,
        min_observations: int = DEFAULT_MIN_OBSERVATIONS,
    ) -> None:
        self._store = store if store is not None else FeatureStore()
        self._dispersion_store = DispersionFeatureStore(self._store)
        self._lags = tuple(lags)
        self._min_symbols = min_symbols
        self._min_observations = min_observations

    @classmethod
    def from_env(cls) -> DispersionService:
        """Construct the component the application factory composes.

        Feature 56 has no environment knobs (see the module docstring), so this
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

        The panel is the shared view both reductions consume: one aligned
        series of closes per symbol over the shared date axis.  ``symbols`` is
        the universe membership (rank order, from feature 40); ``dates`` is the
        axis (the snapshot's daily bars, in order).  The same panel type
        feature 57 uses — one definition of "aligned closes" across the member.
        """
        return PricePanel.from_bars(bars, symbols=symbols, dates=dates)

    # -- Computation --------------------------------------------------------

    def compute(
        self,
        bars: Iterable[DailyBar],
        symbols: Sequence[str],
        dates: Sequence[str | dt.date | dt.datetime],
        *,
        lags: Sequence[int] | None = None,
        min_symbols: int | None = None,
        min_observations: int | None = None,
    ) -> DispersionMetrics:
        """Compute both metrics over the panel built from the given inputs.

        Assembles the panel, then computes the cross-sectional dispersion of
        its latest returns and the autocorrelation of its market return at
        each lag.  The keyword arguments override the service's defaults for
        this call; omit them to use the version-1 definition's values.
        """
        panel = self.build_panel(bars, symbols, dates)
        return build_dispersion_metrics(
            panel,
            min_symbols=(
                self._min_symbols if min_symbols is None else min_symbols
            ),
            lags=self._lags if lags is None else tuple(lags),
            min_observations=(
                self._min_observations
                if min_observations is None
                else min_observations
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
        lags: Sequence[int] | None = None,
        min_symbols: int | None = None,
        min_observations: int | None = None,
        store: FeatureStore | None = None,
        replace: bool = False,
    ) -> DispersionMetrics:
        """Compute both metrics and persist them, version stamped.

        Computes the metrics over the panel built from ``bars``, ``symbols``
        and ``dates``, then stores both as feature-store records under the
        market-wide daily keys at ``snapshot_hash``, each carrying the current
        ``feature_version`` — the whole of feature 56 in one call.  ``top_n``
        records how many universe members the metrics were computed over (it
        travels in each payload).  ``store`` overrides the service's store for
        this call, so a caller can route the persist at the shared composed
        store.  Returns the persisted metrics.

        Refuses a computation whose parameters disagree with the definition
        the stamp names (:class:`VersionMismatchError`): a lag set, dispersion
        floor or observation floor other than the version-1 ones would store
        numbers under an address that promises the version-1 definition.  A
        genuinely different definition needs a new ``feature_version``, which
        is a change to this member's declaration (feature 53), not a keyword
        argument at a call site — so there is deliberately no way to pass one
        here.
        """
        effective_lags = tuple(self._lags if lags is None else lags)
        effective_min_symbols = (
            self._min_symbols if min_symbols is None else min_symbols
        )
        effective_min_observations = (
            self._min_observations
            if min_observations is None
            else min_observations
        )
        expected = definition_parameters()
        self._require_version_1_definition(
            "lags", list(effective_lags), expected["lags"]
        )
        self._require_version_1_definition(
            "min_symbols", effective_min_symbols, expected["min_symbols"]
        )
        self._require_version_1_definition(
            "min_observations",
            effective_min_observations,
            expected["min_observations"],
        )
        metrics = self.compute(
            bars,
            symbols,
            dates,
            lags=effective_lags,
            min_symbols=effective_min_symbols,
            min_observations=effective_min_observations,
        )
        dispersion_store = DispersionFeatureStore(
            store if store is not None else self._store
        )
        dispersion_store.persist(
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
                f"{DISPERSION_DEFINITION}; {AUTOCORRELATION_DEFINITION}); a "
                "changed definition is a new feature_version, which leaves "
                "these rows untouched rather than storing a different thing "
                "under this address"
            )

    # -- Reading ------------------------------------------------------------

    def load(
        self, snapshot_hash: str, *, store: FeatureStore | None = None
    ) -> DispersionMetrics | None:
        """Both metrics stored for ``snapshot_hash``, or ``None`` if none.

        Delegates to :meth:`DispersionFeatureStore.load`; see there for the
        semantics of the neither-present and exactly-one-present cases.
        """
        dispersion_store = DispersionFeatureStore(
            store if store is not None else self._store
        )
        return dispersion_store.load(snapshot_hash)


def build_dispersion_service() -> DispersionService:
    """Zero-argument builder registered with the application factory.

    Kept as a named module-level function (rather than passing
    ``DispersionService.from_env`` directly) so the registry shows an intention
    rather than a classmethod, and so tests can assert on the builder
    independently of construction.
    """
    return DispersionService.from_env()
