"""nullius feature store — point-in-time feature identity and storage.

Workspace member for the "feature-store" plugin (app_spec.xml, category
"Point-in-Time Feature Store").  This package lands feature 48 — every
stored feature is keyed by ``feature_name``, ``feature_version``,
``snapshot_hash``, ``symbol`` and ``frequency``
(docs/nullius-tech-architecture.md §4.4) — and is the foundation the rest
of the category builds on: lazy Parquet materialisation (49), caching
(50), point-in-time row stamping (51) and reads (52), versioned
definitions (53) and the regime features themselves (55–58).

Feature 51 is the row layer (:mod:`feature_store.rows`): feature 48 left a
record's payload opaque and deferred row-level stamping to "the payload
layer those features add", so ``rows`` supplies it — a frozen
:class:`~feature_store.rows.FeatureRow` carrying ``computed_as_of``, and
:func:`~feature_store.rows.stamp_rows`, which reads the clock once per
write so every row in a batch shares one instant.  Feature 52's
``computed_as_of <= t`` read filter builds on that seam.

Importing this package registers five components with the application
factory — a deliberate import side effect, per the factory's registration
protocol (``app.module_loader``) — so ``create_app()`` discovers them by
scanning the declared workspace without the factory ever knowing this
package's name.  Feature 51's row layer registers nothing: it is a pure
function over rows, not an orchestration service with composed state, so
it stays a module plus its package re-exports.

* ``feature-store`` — the five-component-keyed store itself (feature 48);
* ``regime-metrics`` — feature 57's mean pairwise correlation plus breadth;
* ``dispersion-metrics`` — feature 56's cross-sectional return dispersion
  plus several-lag return autocorrelation, persisted version stamped;
* ``volatility-metrics`` — feature 55's multi-horizon realized volatility
  plus volatility-of-volatility, each persisted as a versioned regime
  feature;
* ``regime-labeler`` — feature 58's market-regime labels, a k-means fit on
  a trailing window only, persisted as a versioned regime feature.
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
from .regime_labeler import (
    DEFAULT_K,
    DEFAULT_WINDOW,
    FullHistoryFitError,
    RegimeLabeler,
    RegimeLabels,
    regime_feature_matrix,
)
from .regime_labeler_persistence import (
    FEATURE_NAME_LABELS,
    LABELS_DEFINITION,
    RegimeLabelerFeatureStore,
    IncompleteLabelerMetricsError,
    decode_labels,
    encode_labels,
)
from .regime_labeler_service import (
    RegimeLabelerService,
    build_regime_labeler_service,
)
from .rows import (
    COMPUTED_AS_OF_FIELD,
    FeatureRow,
    FeatureRowError,
    decode_rows,
    encode_rows,
    stamp_rows,
    utc_now,
)
from .service import RegimeService, build_regime_service
from .store import DuplicateFeatureKeyError, FeatureRecord, FeatureStore
from .volatility import (
    ANNUALIZATION_PERIODS,
    DEFAULT_BASE_WINDOW,
    DEFAULT_HORIZONS,
    DEFAULT_VOL_WINDOW,
    RealizedVolatilityResult,
    VolOfVolResult,
    VolatilityMetrics,
    build_volatility_metrics,
    realized_volatility,
    rolling_realized_volatility,
    volatility_of_volatility,
)
from .volatility_persistence import (
    FEATURE_NAME_REALIZED_VOL,
    FEATURE_NAME_VOL_OF_VOL,
    REALIZED_VOL_DEFINITION,
    VOL_OF_VOL_DEFINITION,
    IncompleteVolatilityMetricsError,
    VolatilityFeatureStore,
    decode_realized_volatility,
    decode_vol_of_vol,
    encode_realized_volatility,
    encode_vol_of_vol,
)
from .volatility_service import (
    VolatilityService,
    VersionMismatchError as VolatilityVersionMismatchError,
)

# Names the volatility modules share with their siblings' modules
# (FEATURE_VERSION, definition_parameters, feature_version) stay at their
# module paths: feature 56's spellings already hold the package namespace,
# and a re-export would silently rebind them to a different feature's rows.

__all__ = [
    "ANNUALIZATION_PERIODS",
    "AUTOCORRELATION_DEFINITION",
    "COMPUTED_AS_OF_FIELD",
    "DEFAULT_BASE_WINDOW",
    "DEFAULT_BREADTH_WINDOW",
    "DEFAULT_HORIZONS",
    "DEFAULT_LAGS",
    "DEFAULT_MIN_OBSERVATIONS",
    "DEFAULT_MIN_OVERLAP",
    "DEFAULT_K",
    "DEFAULT_MIN_SYMBOLS",
    "DEFAULT_VOL_WINDOW",
    "DEFAULT_WINDOW",
    "DISPERSION_DEFINITION",
    "FEATURE_NAME_AUTOCORRELATION",
    "FEATURE_NAME_BREADTH",
    "FEATURE_NAME_CORRELATION",
    "FEATURE_NAME_DISPERSION",
    "FEATURE_NAME_LABELS",
    "FEATURE_NAME_REALIZED_VOL",
    "FEATURE_NAME_VOL_OF_VOL",
    "FEATURE_VERSION",
    "FREQUENCIES",
    "MARKET_WIDE_SYMBOL",
    "REALIZED_VOL_DEFINITION",
    "VOL_OF_VOL_DEFINITION",
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
    "FeatureRow",
    "FeatureRowError",
    "FeatureStore",
    "Frequency",
    "FullHistoryFitError",
    "IncompleteDispersionMetricsError",
    "IncompleteLabelerMetricsError",
    "IncompleteRegimeMetricsError",
    "IncompleteVolatilityMetricsError",
    "LABELS_DEFINITION",
    "PricePanel",
    "RealizedVolatilityResult",
    "RegimeFeatureStore",
    "RegimeLabeler",
    "RegimeLabelerFeatureStore",
    "RegimeLabelerService",
    "RegimeLabels",
    "RegimeMetrics",
    "RegimeService",
    "VersionMismatchError",
    "VolOfVolResult",
    "VolatilityFeatureStore",
    "VolatilityMetrics",
    "VolatilityService",
    "VolatilityVersionMismatchError",
    "breadth_above_moving_average",
    "build_dispersion_metrics",
    "build_dispersion_service",
    "build_feature_store",
    "build_regime_labeler_service",
    "build_regime_metrics",
    "build_regime_service",
    "build_volatility_metrics",
    "build_volatility_service",
    "coerce_date",
    "cross_sectional_dispersion",
    "decode_autocorrelation",
    "decode_breadth",
    "decode_correlation",
    "decode_dispersion",
    "decode_labels",
    "decode_realized_volatility",
    "decode_rows",
    "decode_vol_of_vol",
    "definition_parameters",
    "encode_autocorrelation",
    "encode_breadth",
    "encode_correlation",
    "encode_dispersion",
    "encode_labels",
    "encode_realized_volatility",
    "encode_rows",
    "encode_vol_of_vol",
    "feature_version",
    "market_return_series",
    "mean_pairwise_correlation",
    "realized_volatility",
    "regime_feature_matrix",
    "return_autocorrelation",
    "rolling_realized_volatility",
    "stamp_rows",
    "utc_now",
    "volatility_of_volatility",
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


@register("volatility-metrics")
def build_volatility_service() -> VolatilityService:
    """Compose-time contribution: the feature-55 volatility-metrics service.

    Feature 55 computes multi-horizon realized volatility plus
    volatility-of-volatility and persists each as a versioned regime feature.
    This is that capability as a composed component: a zero-argument builder
    (the factory's one-way contract) that computes both metrics over a
    snapshot's universe and stores each under its own market-wide daily key,
    both stamped with the current ``feature_version``.  It borrows a feature
    store rather than owning one, so a deployment routes it at the composed
    ``feature-store`` component.

    Constructs through :meth:`VolatilityService.from_env` rather than calling
    :func:`feature_store.volatility_service.build_volatility_service`, because
    this definition rebinds that name — calling it here would recurse.
    """
    return VolatilityService.from_env()


@register("regime-labeler")
def build_regime_labeler_service() -> RegimeLabelerService:
    """Compose-time contribution: the feature-58 regime-labeler service.

    Feature 58 labels each date with a market-regime stratum from a k-means
    fit on a trailing window only — never the full history — and persists the
    labels as a versioned regime feature.  This is that capability as a
    composed component: a zero-argument builder (the factory's one-way
    contract) that labels a snapshot's market history and stores the labels
    under the market-wide daily key.  It borrows a feature store rather than
    owning one, so a deployment routes it at the composed ``feature-store``
    component.

    Constructs through :meth:`RegimeLabelerService.from_env` rather than
    calling :func:`feature_store.regime_labeler_service.build_regime_labeler_service`,
    because this definition rebinds that name — calling it here would recurse.
    """
    return RegimeLabelerService.from_env()
