"""The feature-store member's components as the application factory composes them.

The implementation lives in the ``feature-store`` workspace member
(``packages/feature-store``), which self-registers with the application
factory under ``"feature-store"`` (feature 48), ``"feature-materialiser"``
(feature 49), ``"regime-metrics"`` (feature 57), ``"dispersion-metrics"``
(feature 56) and ``"volatility-metrics"`` (feature 55); a caller reads each
by name from the composed application (``create_app().get(<name>)``).  These
tests pin that chain — discovery, registration, composition — so the member
cannot silently fall out of the composed application.
"""

from __future__ import annotations

from pathlib import Path

import feature_store

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
    workspace_scan_roots,
)

MEMBER_SRC = Path(feature_store.__file__).resolve().parent.parent


def test_member_is_declared_in_the_scanned_workspace() -> None:
    # The member's own pyproject.toml is what makes it a workspace member and
    # therefore scannable — the registration chain starts here.
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()


def test_scan_registers_all_five_components() -> None:
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    # Feature 48's store, feature 49's lazy Parquet materialiser, feature 57's
    # regime-metrics service, feature 56's dispersion-metrics service and
    # feature 55's volatility-metrics service — all registered by the one
    # member, all discoverable.
    assert "feature-store" in names
    assert "feature-materialiser" in names
    assert "regime-metrics" in names
    assert "dispersion-metrics" in names
    assert "volatility-metrics" in names


def test_composed_app_builds_all_five_components() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("feature-store") is not None
    materialiser = app.get("feature-materialiser")
    assert materialiser is not None
    regime = app.get("regime-metrics")
    assert regime is not None
    dispersion = app.get("dispersion-metrics")
    assert dispersion is not None
    volatility = app.get("volatility-metrics")
    assert volatility is not None
    # The services expose persist/load (duck-checked: the scan imports the
    # member under an alias module, so isinstance against the canonical import
    # would compare two copies of the same class).
    assert callable(regime.persist)
    assert callable(dispersion.persist)
    assert callable(dispersion.load)
    assert callable(volatility.persist)
    assert callable(volatility.load)
    # The materialiser exposes the lazy materialise/load seam (feature 49).
    assert callable(materialiser.materialise)
    assert callable(materialiser.load)
    assert callable(materialiser.path_for)
    for name in (
        "feature-store",
        "feature-materialiser",
        "regime-metrics",
        "dispersion-metrics",
        "volatility-metrics",
    ):
        assert name in app.order


def test_the_composed_components_answer_their_seams() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    store = app.get("feature-store")
    assert callable(getattr(store, "put", None))
    materialiser = app.get("feature-materialiser")
    assert callable(getattr(materialiser, "materialise", None))
    regime = app.get("regime-metrics")
    assert callable(getattr(regime, "persist", None))
    dispersion = app.get("dispersion-metrics")
    assert callable(getattr(dispersion, "persist", None))
    volatility = app.get("volatility-metrics")
    assert callable(getattr(volatility, "persist", None))


def test_the_application_returns_none_when_nothing_registered() -> None:
    # An application with no component registered is a discoverable state, not
    # an exception — mirroring the factory's stance.
    assert Application().get("feature-store") is None
    assert Application().get("feature-materialiser") is None
    assert Application().get("regime-metrics") is None
    assert Application().get("dispersion-metrics") is None
    assert Application().get("volatility-metrics") is None
