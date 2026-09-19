"""nullius feature store — point-in-time feature identity and storage.

Workspace member for the "feature-store" plugin (app_spec.xml, category
"Point-in-Time Feature Store").  This package lands feature 48 — every
stored feature is keyed by ``feature_name``, ``feature_version``,
``snapshot_hash``, ``symbol`` and ``frequency``
(docs/nullius-tech-architecture.md §4.4) — and is the foundation the rest
of the category builds on: lazy Parquet materialisation (49), caching
(50), point-in-time reads (51/52), versioned definitions (53) and the
regime features themselves (55–58).

Importing this package registers a ``feature-store`` component with the
application factory — a deliberate import side effect, per the factory's
registration protocol (``app.module_loader``) — so ``create_app()``
discovers the store by scanning the declared workspace without the
factory ever knowing this package's name.
"""

from __future__ import annotations

from app.module_loader import register

from .bars import DailyBar, coerce_date
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
    "BreadthResult",
    "CorrelationResult",
    "DEFAULT_BREADTH_WINDOW",
    "DEFAULT_MIN_OVERLAP",
    "DailyBar",
    "DuplicateFeatureKeyError",
    "FEATURE_NAME_BREADTH",
    "FEATURE_NAME_CORRELATION",
    "FEATURE_VERSION",
    "FREQUENCIES",
    "FeatureKey",
    "FeatureKeyError",
    "FeatureRecord",
    "FeatureStore",
    "Frequency",
    "IncompleteRegimeMetricsError",
    "MARKET_WIDE_SYMBOL",
    "PricePanel",
    "RegimeFeatureStore",
    "RegimeMetrics",
    "RegimeService",
    "breadth_above_moving_average",
    "build_feature_store",
    "build_regime_metrics",
    "build_regime_service",
    "coerce_date",
    "decode_breadth",
    "decode_correlation",
    "encode_breadth",
    "encode_correlation",
    "mean_pairwise_correlation",
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
