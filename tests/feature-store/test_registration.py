"""The plugin's wiring into the application factory.

The feature store is a self-contained plugin: it registers a
``feature-store`` component from its own package (a deliberate import
side effect), and the factory discovers it by scanning the declared uv
workspace — no edit to any shared registry, router or app factory.  These
tests pin that auto-discovery contract (the "Point-in-Time Feature
Store" member of ``packages/*``).

One wrinkle is inherent to the wiring: the factory imports member
packages under scan aliases (``_nullius_scanned_<pkg>``, see
``app.module_loader._import_package``), so the class a composed store
has is *structurally* this package's FeatureStore but never the same
module object a direct ``import feature_store`` yields.  The assertions
below therefore verify type and behaviour, not ``isinstance`` across the
two module worlds.
"""

import sys

from app.module_loader import create_app, scan_components


def test_workspace_scan_discovers_the_feature_store_component() -> None:
    # Bare scan_components() follows the declared workspace: the member
    # under packages/feature-store/ is imported and its @register fires.
    components = scan_components()
    names = [component.name for component in components]
    assert "feature-store" in names


def test_scan_is_idempotent_per_component_name() -> None:
    # A rescan re-imports the package under its scanned alias; the
    # registry replaces by name, so exactly one feature-store component
    # survives no matter how many scans ran.
    scan_components()
    names = [component.name for component in scan_components()]
    assert names.count("feature-store") == 1


def test_create_app_composes_a_feature_store() -> None:
    app = create_app()
    store = app.get("feature-store")
    assert store is not None
    assert type(store).__qualname__ == "FeatureStore"
    # "<alias>.store" for the factory's scan alias, "feature_store.store"
    # for a direct import — both end in this package's module.
    assert type(store).__module__.endswith("feature_store.store")
    # A fresh store, keyed from the first put (feature 48's contract).
    assert len(store) == 0
    assert "feature-store" in app
    assert "feature-store" in app.order


def test_composed_store_round_trips_a_feature() -> None:
    # Integration smoke: the composed instance actually stores features
    # under the full five-component key.  The record class comes from the
    # exact module world the factory imported (reached via the store's
    # own class, not a hardcoded alias), so put/get see one identity.
    app = create_app()
    store = app.get("feature-store")
    assert store is not None
    store_module = sys.modules[type(store).__module__]
    record = store_module.FeatureRecord(
        key=store_module.FeatureKey(
            feature_name="realized_vol_30",
            feature_version="1",
            snapshot_hash="f" * 64,
            symbol="BTCUSDT",
            frequency="1m",
        ),
        payload=b"smoke",
    )
    assert store.put(record) is record.key
    assert store.get(record.key) is record
    assert len(store) == 1
