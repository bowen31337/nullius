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

from .keys import (
    FREQUENCIES,
    MARKET_WIDE_SYMBOL,
    FeatureKey,
    FeatureKeyError,
    Frequency,
)
from .store import DuplicateFeatureKeyError, FeatureRecord, FeatureStore

__all__ = [
    "FREQUENCIES",
    "MARKET_WIDE_SYMBOL",
    "DuplicateFeatureKeyError",
    "FeatureKey",
    "FeatureKeyError",
    "FeatureRecord",
    "FeatureStore",
    "Frequency",
    "build_feature_store",
]


@register("feature-store")
def build_feature_store() -> FeatureStore:
    """Compose-time contribution: a fresh, empty feature store.

    The builder takes no arguments and touches no globals — the factory's
    one-way contract — so every composed application gets its own store,
    keyed from the first :meth:`FeatureStore.put`.
    """
    return FeatureStore()
