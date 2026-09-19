"""nullius feature store — point-in-time feature identity and storage.

Workspace member for the "feature-store" plugin (app_spec.xml, category
"Point-in-Time Feature Store").  This package lands feature 48 — every
stored feature is keyed by ``feature_name``, ``feature_version``,
``snapshot_hash``, ``symbol`` and ``frequency``
(docs/nullius-tech-architecture.md §4.4) — and is the foundation the rest
of the category builds on: lazy Parquet materialisation (49), caching
(50), point-in-time reads (51/52), versioned definitions (53) and the
regime features themselves (55–58).

Importing this package registers three components with the application
factory — a deliberate import side effect, per the factory's registration
protocol (``app.module_loader``) — so ``create_app()`` discovers them by
scanning the declared workspace without the factory ever knowing this
package's name:

* ``feature-store`` — the five-component-keyed store itself (feature 48);
* ``regime-metrics`` — feature 57's mean pairwise correlation plus breadth;
* ``dispersion-metrics`` — feature 56's cross-sectional return dispersion
  plus several-lag return autocorrelation, persisted version stamped.
"""

from __future__ import annotations

from app.module_loader import register

from .bars import DailyBar, coerce_date
from .dispersion import (
    DEFAULT_LAGS,
    DEFAULT_MIN_OBSERVATIONS,
    DEFAULT_MIN_SYMBOLS,
    AutocorrelationResult,
    DispersionMetrics,
    DispersionResult,
    build_dispersion_metrics,
    cross_sectional_dispersion,
    market_return_series,
    return_autocorrelation,
)
from .dispersion_persistence import (
    AUTOCORRELATION_DEFINITION,
    DISPERSION_DEFINITION,
    FEATURE_NAME_AUTOCORRELATION,
    FEATURE_NAME_DISPERSION,
    DispersionFeatureStore,
    IncompleteDispersionMetricsError,
    decode_autocorrelation,
    decode_dispersion,
    definition_parameters,
    encode_autocorrelation,
    encode_dispersion,
    feature_version,
)
from .dispersion_service import DispersionService, VersionMismatchError
from .keys import (
    FREQUENCIES,
    MARKET_WIDE_SYMBOL,
    FeatureKey,
    FeatureKeyError,
    Frequency,
)
from .persistence import (
    FEATURE_NAME_BREADTH,
    FEATURE_NAME_CORRELATION,
    FEATURE_VERSION,
    IncompleteRegimeMetricsError,
    RegimeFeatureStore,
    decode_breadth,
    decode_correlation,
    encode_breadth,
    encode_correlation,
)
from .regime import (
    DEFAULT_BREADTH_WINDOW,
    DEFAULT_MIN_OVERLAP,
    BreadthResult,
    CorrelationResult,
    PricePanel,
    RegimeMetrics,
    breadth_above_moving_average,
    build_regime_metrics,
    mean_pairwise_correlation,
)
from .service import RegimeService, build_regime_service
from .store import DuplicateFeatureKeyError, FeatureRecord, FeatureStore

__all__ = [
    "AUTOCORRELATION_DEFINITION",
    "DEFAULT_BREADTH_WINDOW",
    "DEFAULT_LAGS",
    "DEFAULT_MIN_OBSERVATIONS",
    "DEFAULT_MIN_OVERLAP",
    "DEFAULT_MIN_SYMBOLS",
    "DISPERSION_DEFINITION",
    "FEATURE_NAME_AUTOCORRELATION",
    "FEATURE_NAME_BREADTH",
    "FEATURE_NAME_CORRELATION",
    "FEATURE_NAME_DISPERSION",
    "FEATURE_VERSION",
    "FREQUENCIES",
    "MARKET_WIDE_SYMBOL",
    "AutocorrelationResult",
    "BreadthResult",
    "CorrelationResult",
    "DailyBar",
    "DispersionFeatureStore",
    "DispersionMetrics",
    "DispersionResult",
    "DispersionService",
    "DuplicateFeatureKeyError",
    "FeatureKey",
    "FeatureKeyError",
    "FeatureRecord",
    "FeatureStore",
    "Frequency",
    "IncompleteDispersionMetricsError",
    "IncompleteRegimeMetricsError",
    "PricePanel",
    "RegimeFeatureStore",
    "RegimeMetrics",
    "RegimeService",
    "VersionMismatchError",
    "breadth_above_moving_average",
    "build_dispersion_metrics",
    "build_dispersion_service",
    "build_feature_store",
    "build_regime_metrics",
    "build_regime_service",
    "coerce_date",
    "cross_sectional_dispersion",
    "decode_autocorrelation",
    "decode_breadth",
    "decode_correlation",
    "decode_dispersion",
    "definition_parameters",
    "encode_autocorrelation",
    "encode_breadth",
    "encode_correlation",
    "encode_dispersion",
    "feature_version",
    "market_return_series",
    "mean_pairwise_correlation",
    "return_autocorrelation",
]


@register("feature-store")
def build_feature_store() -> FeatureStore:
    """Compose-time contribution: a fresh, empty feature store.

    The builder takes no arguments and touches no globals — the factory's
    one-way contract — so every composed application gets its own store,
    keyed from the first :meth:`FeatureStore.put`.
    """
    return FeatureStore()


@register("regime-metrics")
def build_regime_service() -> RegimeService:
    """Compose-time contribution: the feature-57 regime-metrics service.

    Feature 57 computes the mean pairwise correlation of the top-50 universe
    plus breadth above an N-day moving average and persists both.  This is
    that capability as a composed component: a zero-argument builder (the
    factory's one-way contract) that computes both metrics over a snapshot's
    universe and stores them as feature-store records.  It borrows a feature
    store rather than owning one, so a deployment routes it at the composed
    ``feature-store`` component.
    """
    return RegimeService.from_env()


@register("dispersion-metrics")
def build_dispersion_service() -> DispersionService:
    """Compose-time contribution: the feature-56 dispersion-metrics service.

    Feature 56 computes cross-sectional return dispersion plus return
    autocorrelation at several lags and persists both, each stamped with its
    ``feature_version``.  This is that capability as a composed component: a
    zero-argument builder (the factory's one-way contract) that computes both
    metrics over a snapshot's universe and stores them as version-stamped
    feature-store records.  It borrows a feature store rather than owning one,
    so a deployment routes it at the composed ``feature-store`` component.

    Constructs through :meth:`DispersionService.from_env` rather than calling
    :func:`feature_store.dispersion_service.build_dispersion_service`, because
    this definition rebinds that name — calling it here would recurse.
    """
    return DispersionService.from_env()
