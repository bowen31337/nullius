"""Feature 57's seat in the app namespace: the app-package facade over the factory.

The implementation lives in the ``feature-store`` workspace member
(``packages/feature-store``), which self-registers with the application
factory under ``"feature-store"`` (feature 48) and ``"regime-metrics"``
(feature 57).  ``src/app/modules/feature-store/`` is the member's seat in the
``app`` package namespace: it asks the factory for those components without
the ``app`` package depending on any member at import time.  These tests pin
that chain — discovery, registration, composition, facade — so the member
cannot silently fall out of the composed application.

One wrinkle is inherent to the seat's directory name: ``feature-store``
carries a hyphen, so it is not a valid dotted import path.  It is reached the
way the application factory reaches it — ``importlib.import_module`` with the
hyphenated name — which is exactly how a hyphenated package directory is
loaded anywhere in this workspace.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
    workspace_scan_roots,
)

import feature_store

MEMBER_SRC = Path(feature_store.__file__).resolve().parent.parent

# The seat's directory name is hyphenated, so it is not a valid dotted import
# path; importlib.import_module loads it the way the factory's scan does.
seat = importlib.import_module("app.modules.feature-store")


def test_member_is_declared_in_the_scanned_workspace() -> None:
    # The member's own pyproject.toml is what makes it a workspace member and
    # therefore scannable — the registration chain starts here.
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()


def test_scan_registers_both_components() -> None:
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    # Feature 48's store and feature 57's regime-metrics service, both
    # registered by the one member, both discoverable.
    assert "feature-store" in names
    assert "regime-metrics" in names


def test_composed_app_builds_both_components() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("feature-store") is not None
    regime = app.get("regime-metrics")
    assert regime is not None
    # The regime-metrics component is the service (duck-checked: the scan
    # imports the member under an alias module, so isinstance against the
    # canonical import would compare two copies of the same class).
    assert callable(regime.persist)
    assert "feature-store" in app.order
    assert "regime-metrics" in app.order


def test_app_seat_exposes_the_components() -> None:
    # src/app/modules/feature-store is the member's seat in the app namespace:
    # it names the components and asks the factory for them without the app
    # package depending on any member at import time.
    assert seat.FEATURE_STORE_COMPONENT == "feature-store"
    assert seat.REGIME_METRICS_COMPONENT == "regime-metrics"

    app = create_app(MEMBER_SRC, registry=Registration())
    store = seat.feature_store_component(app)
    assert callable(getattr(store, "put", None))
    regime = seat.regime_metrics_component(app)
    assert callable(getattr(regime, "persist", None))


def test_seat_returns_none_when_nothing_registered() -> None:
    # An application with neither component is a discoverable state, not an
    # exception — mirroring the factory's stance.
    assert seat.feature_store_component(Application()) is None
    assert seat.regime_metrics_component(Application()) is None
