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


# ---------------------------------------------------------------------------
# The version query surface (feature 53's observable coexistence)
# ---------------------------------------------------------------------------


def test_versions_lists_distinct_versions_for_a_feature_name() -> None:
    # Feature 53: a changed definition writes under a new version and leaves
    # the prior-version rows untouched, so one feature_name holds several
    # versions.  versions() makes that coexistence observable rather than
    # leaving the old rows reachable only by hand-reconstructing each key.
    store = FeatureStore()
    store.put(make_record(feature_name="vol", feature_version="1", symbol="BTCUSDT"))
    store.put(make_record(feature_name="vol", feature_version="2", symbol="BTCUSDT"))
    store.put(make_record(feature_name="other", feature_version="1", symbol="BTCUSDT"))
    assert store.versions("vol") == ("1", "2")
    assert store.versions("other") == ("1",)


def test_versions_are_sorted_and_deduplicated() -> None:
    # Deterministic and de-duplicated, like keys(): the same version under
    # many snapshots/symbols/frequencies is reported once, in sorted order.
    store = FeatureStore()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for snap in (SNAPSHOT, "0" * 64):
            store.put(make_record(feature_name="vol", feature_version="2", symbol=symbol, snapshot_hash=snap))
    store.put(make_record(feature_name="vol", feature_version="10", symbol="BTCUSDT"))
    store.put(make_record(feature_name="vol", feature_version="1", symbol="BTCUSDT"))
    # String sort, so "10" precedes "2" — versions are opaque strings, and
    # the ordering is the canonical one, not a numeric assumption.
    assert store.versions("vol") == ("1", "10", "2")


def test_versions_of_an_unstored_name_is_empty_not_an_error() -> None:
    store = FeatureStore()
    store.put(make_record(feature_name="vol", feature_version="1", symbol="BTCUSDT"))
    assert store.versions("never_stored") == ()


def test_records_returns_all_versions_across_every_other_component() -> None:
    # The reach half of feature 53: the prior-version rows left untouched are
    # all returned, spanning every snapshot, symbol and frequency under the
    # name, sorted in canonical component order.
    store = FeatureStore()
    v1 = make_record(feature_name="vol", feature_version="1", symbol="BTCUSDT", payload=b"v1")
    v2 = make_record(feature_name="vol", feature_version="2", symbol="ETHUSDT", payload=b"v2")
    store.put(v1)
    store.put(v2)
    records = store.records("vol")
    assert records == (v1, v2)
    assert [r.payload for r in records] == [b"v1", b"v2"]


def test_records_are_sorted_in_canonical_component_order() -> None:
    store = FeatureStore()
    shuffled = [
        make_record(feature_name="vol", feature_version="2", symbol="ETHUSDT"),
        make_record(feature_name="vol", feature_version="1", symbol="BTCUSDT"),
        make_record(feature_name="vol", feature_version="1", symbol="ETHUSDT"),
    ]
    for record in shuffled:
        store.put(record)
    names = [r.key.feature_name for r in store.records("vol")]
    assert names == ["vol", "vol", "vol"]
    assert store.records("vol") == tuple(
        sorted(store.records("vol"), key=lambda r: FeatureKey.to_tuple(r.key))
    )


def test_versions_and_records_filter_out_other_feature_names() -> None:
    store = FeatureStore()
    store.put(make_record(feature_name="vol", feature_version="1", symbol="BTCUSDT"))
    store.put(make_record(feature_name="corr", feature_version="1", symbol="BTCUSDT"))
    assert store.versions("vol") == ("1",)
    assert [r.key.feature_name for r in store.records("vol")] == ["vol"]


def test_versions_rejects_an_impossible_feature_name() -> None:
    # feature_name is a key component; a value that could never be part of a
    # key (empty, padded, path-unsafe) is a caller bug, not a silent miss.
    store = FeatureStore()
    for bad in ("", "  padded  ", "a/b", ".", ".."):
        with pytest.raises(Exception, match="feature_name"):
            store.versions(bad)
        with pytest.raises(Exception, match="feature_name"):
            store.records(bad)


def test_a_version_bump_leaves_prior_rows_untouched_and_reachable() -> None:
    # The whole of feature 53, observed end to end: a changed definition
    # persists under a new version; the version-1 row is neither overwritten
    # nor orphaned — it is still the record under its exact key, still listed
    # by versions(), and still returned by records().
    store = FeatureStore()
    v1 = make_record(feature_name="vol", feature_version="1", payload=b"v1-numbers")
    v2 = make_record(feature_name="vol", feature_version="2", payload=b"v2-numbers")
    store.put(v1)
    store.put(v2)  # a different key, so no DuplicateFeatureKeyError

    # The version-1 row is untouched: still the record under its exact key.
    assert store.get(v1.key) is v1
    assert store.get(v1.key).payload == b"v1-numbers"
    # Both versions now coexist under the one name.
    assert store.versions("vol") == ("1", "2")
    # And both prior and new rows are reachable by the query surface.
    assert store.records("vol") == (v1, v2)
