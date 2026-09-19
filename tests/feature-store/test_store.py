"""Feature 48's storage contract: keyed by the full identity, or not at all.

app_spec.xml feature 48 keys every stored feature with feature_name,
feature_version, snapshot_hash, symbol and frequency.  These tests pin
the store side of that sentence: records enter only with a complete
:class:`FeatureKey`, leave only under the identical key, and an exact-key
duplicate is an error rather than a replacement.
"""

import pytest

from feature_store import (
    DuplicateFeatureKeyError,
    FeatureKey,
    FeatureRecord,
    FeatureStore,
)

SNAPSHOT = "f" * 64


def make_key(**overrides: object) -> FeatureKey:
    components: dict[str, object] = {
        "feature_name": "realized_vol_30",
        "feature_version": "1",
        "snapshot_hash": SNAPSHOT,
        "symbol": "BTCUSDT",
        "frequency": "1m",
    }
    components.update(overrides)
    return FeatureKey(**components)  # type: ignore[arg-type]


def make_record(payload: bytes = b"payload", **overrides: object) -> FeatureRecord:
    return FeatureRecord(key=make_key(**overrides), payload=payload)


def test_new_store_is_empty() -> None:
    store = FeatureStore()
    assert len(store) == 0
    assert store.keys() == ()
    assert list(store) == []


def test_put_then_get_returns_the_record_under_its_exact_key() -> None:
    store = FeatureStore()
    record = make_record()
    assert store.put(record) == record.key
    assert store.get(record.key) is record
    assert record.key in store
    assert len(store) == 1


@pytest.mark.parametrize(
    "field,other",
    [
        ("feature_name", "return_autocorr_5"),
        ("feature_version", "2"),  # feature 53: a version bump is a new key
        ("snapshot_hash", "0" * 64),
        ("symbol", "ETHUSDT"),
        ("frequency", "1d"),
    ],
)
def test_get_misses_when_any_single_component_differs(
    field: str, other: str
) -> None:
    # The store-side heart of feature 48: five components, all of them
    # load-bearing.  A stored feature is invisible to every address that
    # is not its exact key — no partial match, no fuzzy fallback.
    store = FeatureStore()
    stored = make_record()
    store.put(stored)
    miss = make_key(**{field: other})
    assert store.get(miss) is None
    assert miss not in store


def test_two_features_sharing_four_components_coexist() -> None:
    # The flip side: same name, version, snapshot and frequency, two
    # symbols — two stored features, neither shadowing the other.
    store = FeatureStore()
    btc = make_record(symbol="BTCUSDT")
    eth = make_record(symbol="ETHUSDT", payload=b"eth")
    store.put(btc)
    store.put(eth)
    assert len(store) == 2
    assert store.get(btc.key) is btc
    assert store.get(eth.key) is eth


def test_keys_are_sorted_in_canonical_component_order() -> None:
    # Deterministic traversal (the feature-46 discipline applied to keys):
    # insertion order must not leak into iteration order.
    store = FeatureStore()
    shuffled = [
        make_record(symbol="ETHUSDT"),
        make_record(feature_version="2"),
        make_record(symbol="BTCUSDT"),
        make_record(feature_name="aaa_first"),
    ]
    for record in shuffled:
        store.put(record)
    assert store.keys() == tuple(sorted(store.keys(), key=FeatureKey.to_tuple))
    assert list(store) == list(store.keys())
    # Stable across calls.
    assert store.keys() == store.keys()


def test_duplicate_exact_key_is_rejected_not_replaced() -> None:
    store = FeatureStore()
    store.put(make_record(payload=b"first"))
    with pytest.raises(DuplicateFeatureKeyError, match="already stored under"):
        store.put(make_record(payload=b"second"))
    # The original survives the refused write.
    assert store.get(make_key()) is not None
    assert store.get(make_key()).payload == b"first"
    assert len(store) == 1


def test_replace_true_makes_the_overwrite_explicit() -> None:
    store = FeatureStore()
    store.put(make_record(payload=b"first"))
    replacement = make_record(payload=b"second")
    store.put(replacement, replace=True)
    assert store.get(make_key()) is replacement
    assert len(store) == 1


def test_put_rejects_non_records() -> None:
    store = FeatureStore()
    with pytest.raises(TypeError, match="FeatureRecord"):
        store.put((make_key(), b"payload"))  # type: ignore[arg-type]


def test_get_rejects_partial_addressing() -> None:
    # There is no fetching "by name" or by a hand-rolled tuple: the only
    # address the store understands is a validated FeatureKey.
    store = FeatureStore()
    store.put(make_record())
    for not_a_key in (
        "realized_vol_30",
        ("realized_vol_30", "1", SNAPSHOT, "BTCUSDT", "1m"),
        None,
    ):
        with pytest.raises(TypeError, match="FeatureKey only"):
            store.get(not_a_key)  # type: ignore[arg-type]


def test_contains_is_boolean_for_non_keys() -> None:
    store = FeatureStore()
    store.put(make_record())
    assert "realized_vol_30" not in store  # not a KeyError, just false


def test_record_requires_a_real_key_and_real_bytes() -> None:
    with pytest.raises(TypeError, match="FeatureKey"):
        FeatureRecord(key=("name", "1", SNAPSHOT, "BTCUSDT", "1m"), payload=b"")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="bytes"):
        FeatureRecord(key=make_key(), payload="not bytes")  # type: ignore[arg-type]


def test_empty_payload_is_a_legal_feature() -> None:
    # A feature computed over an empty window has no rows; that is a
    # stored feature like any other, addressed by the same five components.
    store = FeatureStore()
    record = make_record(payload=b"")
    store.put(record)
    assert store.get(record.key) is record
