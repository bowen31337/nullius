"""Feature 56's persistence contract: the two metrics as version-stamped records.

app_spec.xml feature 56: *System computes cross-sectional return dispersion
plus return autocorrelation at several lags, persisting them with
feature_version stamps.*  These tests pin the persisting half — the
encode/decode of each metric to its opaque payload and the round trip through
a :class:`FeatureStore` under the market-wide daily key.  The invariants:

* the **feature_version stamp is part of the key**, not a field inside the
  payload: a record is addressed by name + version + snapshot + symbol +
  frequency, so re-persisting under a new version lands *beside* the old rows
  rather than over them;
* each metric round-trips losslessly through encode then decode, provenance
  (the lags, the observation floor, the universe size) included;
* both are stored under the market-wide sentinel symbol at the daily
  frequency — a cross-section's width and the market's memory describe the
  market, not one instrument;
* the two are persisted as a pair and read back as a pair — finding only one
  under a snapshot hash is an error, not half a value;
* payloads are deterministic, so the same value always encodes to the same
  bytes — the replay path compares payloads.
"""

import json
import math

import pytest
from feature_store.dispersion import (
    AutocorrelationResult,
    DispersionMetrics,
    DispersionResult,
)
from feature_store.dispersion_persistence import (
    FEATURE_NAME_AUTOCORRELATION,
    FEATURE_NAME_DISPERSION,
    FEATURE_VERSION,
    DispersionFeatureStore,
    IncompleteDispersionMetricsError,
    decode_autocorrelation,
    decode_dispersion,
    definition_parameters,
    encode_autocorrelation,
    encode_dispersion,
)
from feature_store.keys import MARKET_WIDE_SYMBOL, FeatureKey, Frequency
from feature_store.store import DuplicateFeatureKeyError, FeatureRecord, FeatureStore

SNAPSHOT = "a" * 64
OTHER_SNAPSHOT = "b" * 64

DISPERSION = DispersionResult(dispersion=0.0182, mean_return=0.0007, n=50)
AUTOCORRELATION = AutocorrelationResult(
    lags=(1, 2, 3, 5, 10),
    coefficients=(0.12, -0.04, 0.03, -0.11, 0.06),
    observations=(99, 98, 97, 95, 90),
    min_observations=10,
)


# ---------------------------------------------------------------------------
# Payload encode/decode
# ---------------------------------------------------------------------------


def test_dispersion_round_trips_with_provenance() -> None:
    assert decode_dispersion(encode_dispersion(DISPERSION, top_n=50)) == DISPERSION


def test_autocorrelation_round_trips_with_provenance() -> None:
    payload = encode_autocorrelation(AUTOCORRELATION, top_n=50)
    assert decode_autocorrelation(payload) == AUTOCORRELATION


def test_payloads_are_byte_deterministic() -> None:
    # The replay path compares payloads, so the same value must encode to the
    # same bytes every time.
    assert encode_dispersion(DISPERSION, top_n=50) == encode_dispersion(
        DISPERSION, top_n=50
    )
    assert encode_autocorrelation(
        AUTOCORRELATION, top_n=50
    ) == encode_autocorrelation(AUTOCORRELATION, top_n=50)


def test_payload_carries_the_feature_version_stamp() -> None:
    # The stamp travels in the envelope as well as in the key, so a reader
    # holding only the payload can tell which definition produced the number.
    dispersion_payload = json.loads(encode_dispersion(DISPERSION, top_n=50))
    autocorrelation_payload = json.loads(
        encode_autocorrelation(AUTOCORRELATION, top_n=50)
    )
    assert dispersion_payload["version"] == FEATURE_VERSION
    assert autocorrelation_payload["version"] == FEATURE_VERSION
    assert dispersion_payload["feature"] == FEATURE_NAME_DISPERSION
    assert autocorrelation_payload["feature"] == FEATURE_NAME_AUTOCORRELATION


def test_payload_records_the_universe_size_and_lag_set() -> None:
    # The payload is self-describing about what it is a fact over: how many
    # universe members, and which lags were actually computed.
    dispersion_payload = json.loads(encode_dispersion(DISPERSION, top_n=50))
    autocorrelation_payload = json.loads(
        encode_autocorrelation(AUTOCORRELATION, top_n=50)
    )
    assert dispersion_payload["top_n"] == 50
    assert autocorrelation_payload["top_n"] == 50
    assert autocorrelation_payload["lags"] == [1, 2, 3, 5, 10]
    assert autocorrelation_payload["observations"] == [99, 98, 97, 95, 90]


def test_nan_coefficients_survive_the_round_trip() -> None:
    # An unscored lag is nan, and nan must come back as nan rather than as a
    # zero the reader would mistake for a measured absence of memory.
    result = AutocorrelationResult(
        lags=(1, 50),
        coefficients=(0.2, float("nan")),
        observations=(40, 0),
        min_observations=10,
    )
    decoded = decode_autocorrelation(encode_autocorrelation(result, top_n=50))
    assert decoded.coefficients[0] == pytest.approx(0.2)
    assert math.isnan(decoded.coefficients[1])
    assert decoded.observations == (40, 0)


def test_a_payload_naming_another_feature_is_rejected() -> None:
    with pytest.raises(ValueError, match="must name"):
        decode_dispersion(b'{"feature":"something_else","version":"1"}')


def test_a_payload_stamped_with_another_version_is_rejected() -> None:
    # A later-version payload is a *different stored feature*, not something
    # this version-1 decoder reinterprets.
    envelope = json.dumps(
        {"feature": FEATURE_NAME_DISPERSION, "version": "2", "n": 1,
         "mean_return": 0.0, "dispersion": 0.0, "top_n": 50}
    ).encode()
    with pytest.raises(ValueError, match="version"):
        decode_dispersion(envelope)


# ---------------------------------------------------------------------------
# Keys and the version stamp
# ---------------------------------------------------------------------------


def test_keys_carry_the_version_stamp_and_market_wide_symbol() -> None:
    store = DispersionFeatureStore(FeatureStore())
    for key in (
        store.dispersion_key(SNAPSHOT),
        store.autocorrelation_key(SNAPSHOT),
    ):
        assert isinstance(key, FeatureKey)
        assert key.feature_version == FEATURE_VERSION
        assert key.symbol == MARKET_WIDE_SYMBOL
        assert key.frequency is Frequency.D1
        assert key.snapshot_hash == SNAPSHOT


def test_the_two_metrics_are_two_distinct_keys() -> None:
    store = DispersionFeatureStore(FeatureStore())
    assert store.dispersion_key(SNAPSHOT) != store.autocorrelation_key(SNAPSHOT)


def test_feature_version_is_part_of_the_key_of_path() -> None:
    # The stamp is a path segment, so two versions are two on-disk
    # addresses — the version cannot be lost in storage.
    store = DispersionFeatureStore(FeatureStore())
    parts = store.dispersion_key(SNAPSHOT).to_path().parts
    assert len(parts) == 5
    assert parts[1] == FEATURE_VERSION


def test_definition_parameters_name_the_version_they_stamp() -> None:
    # The stamp and the definition it stands for stay one lookup apart, so a
    # reader can check what version 1 means without reading the computation.
    parameters = definition_parameters()
    assert parameters["feature_version"] == FEATURE_VERSION
    assert "definition" not in parameters  # spelled per metric below
    assert parameters["dispersion"]
    assert parameters["autocorrelation"]
    assert len(parameters["lags"]) >= 2  # "at several lags"


# ---------------------------------------------------------------------------
# The persistence surface
# ---------------------------------------------------------------------------


def test_persist_then_load_round_trips_both_metrics() -> None:
    store = FeatureStore()
    dispersion_store = DispersionFeatureStore(store)
    metrics = DispersionMetrics(
        dispersion=DISPERSION, autocorrelation=AUTOCORRELATION
    )
    keys = dispersion_store.persist(SNAPSHOT, metrics, top_n=50)
    assert len(keys) == 2
    assert dispersion_store.load(SNAPSHOT) == metrics
    assert dispersion_store.load_dispersion(SNAPSHOT) == DISPERSION
    assert dispersion_store.load_autocorrelation(SNAPSHOT) == AUTOCORRELATION
    assert len(store) == 2


def test_persist_stores_under_the_market_wide_daily_keys() -> None:
    # Both records are market-wide facts, so both carry the sentinel symbol —
    # feature 48's key admits no four-component form.
    store = FeatureStore()
    dispersion_store = DispersionFeatureStore(store)
    dispersion_store.persist(
        SNAPSHOT,
        DispersionMetrics(DISPERSION, AUTOCORRELATION),
        top_n=50,
    )
    assert dispersion_store.dispersion_key(SNAPSHOT) in store
    assert dispersion_store.autocorrelation_key(SNAPSHOT) in store
    for key in store.keys():
        assert key.symbol == MARKET_WIDE_SYMBOL


def test_different_snapshots_do_not_share_records() -> None:
    # The snapshot hash pins which sealed bars the metrics were computed over,
    # so a replay opening different bytes reads different records.
    store = FeatureStore()
    dispersion_store = DispersionFeatureStore(store)
    dispersion_store.persist(
        SNAPSHOT, DispersionMetrics(DISPERSION, AUTOCORRELATION), top_n=50
    )
    assert dispersion_store.load(OTHER_SNAPSHOT) is None


def test_a_second_persist_of_the_same_key_is_an_error() -> None:
    # An exact-key collision means two writers believe they computed the same
    # thing; the store surfaces it rather than silently clobbering.
    store = FeatureStore()
    dispersion_store = DispersionFeatureStore(store)
    metrics = DispersionMetrics(DISPERSION, AUTOCORRELATION)
    dispersion_store.persist(SNAPSHOT, metrics, top_n=50)
    with pytest.raises(DuplicateFeatureKeyError):
        dispersion_store.persist(SNAPSHOT, metrics, top_n=50)
    # Replacing is an explicit decision.
    dispersion_store.persist(SNAPSHOT, metrics, top_n=50, replace=True)
    assert len(store) == 2


def test_load_returns_none_when_neither_metric_is_stored() -> None:
    # An unpersisted snapshot is a normal point-in-time miss.
    dispersion_store = DispersionFeatureStore(FeatureStore())
    assert dispersion_store.load(SNAPSHOT) is None


def test_half_a_pair_is_an_error_not_half_a_value() -> None:
    # A persist interrupted between the two writes leaves exactly one record;
    # no reader should have to paper over that.
    store = FeatureStore()
    dispersion_store = DispersionFeatureStore(store)
    store.put(
        FeatureRecord(
            key=dispersion_store.dispersion_key(SNAPSHOT),
            payload=encode_dispersion(DISPERSION, top_n=50),
        )
    )
    with pytest.raises(IncompleteDispersionMetricsError):
        dispersion_store.load(SNAPSHOT)


# ---------------------------------------------------------------------------
# The version stamp as a versioning mechanism (feature 53's contract)
# ---------------------------------------------------------------------------


def test_a_new_version_lands_beside_the_old_rows() -> None:
    # The whole reason the stamp is in the key: a changed definition writes
    # under a new version and leaves the version-1 rows untouched, rather than
    # overwriting numbers a replay may still be reading.
    store = FeatureStore()
    version_1_key = FeatureKey(
        feature_name=FEATURE_NAME_DISPERSION,
        feature_version=FEATURE_VERSION,
        snapshot_hash=SNAPSHOT,
        symbol=MARKET_WIDE_SYMBOL,
        frequency=Frequency.D1,
    )
    store.put(
        FeatureRecord(
            key=version_1_key, payload=encode_dispersion(DISPERSION, top_n=50)
        )
    )
    version_2_key = FeatureKey(
        feature_name=FEATURE_NAME_DISPERSION,
        feature_version="2",
        snapshot_hash=SNAPSHOT,
        symbol=MARKET_WIDE_SYMBOL,
        frequency=Frequency.D1,
    )
    # A different definition's numbers, stored without touching version 1.
    store.put(
        FeatureRecord(
            key=version_2_key,
            payload=encode_dispersion(
                DispersionResult(dispersion=0.0, mean_return=0.0, n=1), top_n=50
            ),
        )
    )
    assert len(store) == 2
    # The version-1 row is byte-identical to what was written.
    assert store.get(version_1_key).payload == encode_dispersion(
        DISPERSION, top_n=50
    )
    # And the two keys differ in exactly the version component.
    differing = [
        index
        for index, (left, right) in enumerate(
            zip(version_1_key.to_tuple(), version_2_key.to_tuple())
        )
        if left != right
    ]
    assert differing == [1]  # only the version segment
