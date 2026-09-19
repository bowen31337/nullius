"""The feature-store module — app-level entrypoint for the feature-store workspace member.

The implementation lives in the ``feature-store`` workspace member
(``packages/feature-store``, import name ``feature_store``), which
self-registers with the application factory under four component names —
``feature-store`` (feature 48, the five-component-keyed store),
``regime-metrics`` (feature 57, the mean-pairwise-correlation-plus-breadth
service), ``dispersion-metrics`` (feature 56, the
dispersion-plus-autocorrelation service, version stamped) and
``volatility-metrics`` (feature 55, the realized-volatility-plus-vol-of-vol
service, each metric persisted as a versioned regime feature) — scanning the
workspace imports it, its ``@register`` decorators fire, and ``create_app()``
composes all four components.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/feature-store/``): it exposes the composed components
without making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the
factory for the components, and a module that cannot reach them (member not
scanned, workspace empty) returns ``None`` rather than failing import,
mirroring the factory's own "degrade, don't break" stance toward absent
components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from feature_store import (
        DispersionService,
        FeatureStore,
        RegimeService,
        VolatilityService,
    )

__all__ = [
    "DISPERSION_METRICS_COMPONENT",
    "FEATURE_STORE_COMPONENT",
    "REGIME_METRICS_COMPONENT",
    "VOLATILITY_METRICS_COMPONENT",
    "dispersion_metrics_component",
    "feature_store_component",
    "regime_metrics_component",
    "volatility_metrics_component",
]

#: The component name the feature-store member registers its store under
#: (feature 48).  Kept here so anything asking the composed application for
#: the store shares one spelling.
FEATURE_STORE_COMPONENT = "feature-store"

#: The component name the feature-store member registers its regime-metrics
#: service under (feature 57).
REGIME_METRICS_COMPONENT = "regime-metrics"

#: The component name the feature-store member registers its dispersion-metrics
#: service under (feature 56).
DISPERSION_METRICS_COMPONENT = "dispersion-metrics"

#: The component name the feature-store member registers its volatility-metrics
#: service under (feature 55).
VOLATILITY_METRICS_COMPONENT = "volatility-metrics"


def feature_store_component(app: Application | None = None) -> FeatureStore | Any:
    """Return the composed feature store (feature 48).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``feature-store`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as an
    empty workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(FEATURE_STORE_COMPONENT)


def regime_metrics_component(app: Application | None = None) -> RegimeService | Any:
    """Return the composed regime-metrics service (feature 57).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``regime-metrics`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as an
    empty workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(REGIME_METRICS_COMPONENT)


def dispersion_metrics_component(app: Application | None = None) -> DispersionService | Any:
    """Return the composed dispersion-metrics service (feature 56).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``dispersion-metrics`` component is registered —
    an absent component is a discoverable state, not an exception, exactly as
    an empty workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(DISPERSION_METRICS_COMPONENT)


def volatility_metrics_component(app: Application | None = None) -> VolatilityService | Any:
    """Return the composed volatility-metrics service (feature 55).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``volatility-metrics`` component is registered —
    an absent component is a discoverable state, not an exception, exactly as
    an empty workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(VOLATILITY_METRICS_COMPONENT)
