"""Feature 55's persistence contract: the two metrics as versioned records.

app_spec.xml feature 55: *System computes multi-horizon realized volatility
plus volatility-of-volatility, persisting each as a versioned regime
feature.*  These tests pin the persisting half — the encode/decode of each
metric to its opaque payload and the round trip through a
:class:`FeatureStore` under the market-wide daily key.  The invariants:

* the **feature_version stamp is part of the key**, not a field inside the
  payload: a record is addressed by name + version + snapshot + symbol +
  frequency, so re-persisting under a new version lands *beside* the old rows
  rather than over them;
* each metric is persisted under its **own feature_name** — "persisting
  each" means two records, two names, one stamp;
* each metric round-trips losslessly through encode then decode, provenance
  (the horizons, the base and vol windows, the annualization, the universe
  size) included;
* both are stored under the market-wide sentinel symbol at the daily
  frequency — the market's magnitude and its instability describe the
  market, not one instrument;
* the two are persisted as a pair and read back as a pair — finding only one
  under a snapshot hash is an error, not half a value;
* payloads are deterministic, so the same value always encodes to the same
  bytes — the replay path compares payloads.
"""

import json
import math

import pytest
from feature_store.keys import MARKET_WIDE_SYMBOL, FeatureKey, Frequency
from feature_store.store import DuplicateFeatureKeyError, FeatureRecord, FeatureStore
from feature_store.volatility import (
    RealizedVolatilityResult,
    VolOfVolResult,
    VolatilityMetrics,
)
from feature_store.volatility_persistence import (
    FEATURE_NAME_REALIZED_VOL,
    FEATURE_NAME_VOL_OF_VOL,
    FEATURE_VERSION,
    REALIZED_VOL_DEFINITION,
    VOL_OF_VOL_DEFINITION,
    IncompleteVolatilityMetricsError,
    VolatilityFeatureStore,
    decode_realized_volatility,
    decode_vol_of_vol,
    definition_parameters,
    encode_realized_volatility,
    encode_vol_of_vol,
    feature_version,
)

SNAPSHOT = "a" * 64
OTHER_SNAPSHOT = "b" * 64

REALIZED = RealizedVolatilityResult(
    horizons=(10, 21, 63),
    volatilities=(0.71, 0.65, 0.58),
    observations=(10, 21, 63),
    annualization=365.0,
)
VOL_OF_VOL = VolOfVolResult(
    vol_of_vol=0.09,
    mean_vol=0.64,
    n=60,
    base_window=21,
    window=60,
    annualization=365.0,
)


# ---------------------------------------------------------------------------
# Payload encode/decode
# ---------------------------------------------------------------------------


def test_realized_volatility_round_trips_with_provenance() -> None:
    assert (
        decode_realized_volatility(encode_realized_volatility(REALIZED, top_n=50))
        == REALIZED
    )


def test_vol_of_vol_round_trips_with_provenance() -> None:
    payload = encode_vol_of_vol(VOL_OF_VOL, top_n=50)
    assert decode_vol_of_vol(payload) == VOL_OF_VOL


def test_payloads_are_byte_deterministic() -> None:
    # The replay path compares payloads, so the same value must encode to the
    # same bytes every time.
    assert encode_realized_volatility(
        REALIZED, top_n=50
    ) == encode_realized_volatility(REALIZED, top_n=50)
    assert encode_vol_of_vol(VOL_OF_VOL, top_n=50) == encode_vol_of_vol(
        VOL_OF_VOL, top_n=50
    )


def test_payload_carries_the_feature_version_stamp() -> None:
    # The stamp travels in the envelope as well as in the key, so a reader
    # holding only the payload can tell which definition produced the number.
    realized_payload = json.loads(encode_realized_volatility(REALIZED, top_n=50))
    vol_of_vol_payload = json.loads(encode_vol_of_vol(VOL_OF_VOL, top_n=50))
    assert realized_payload["version"] == FEATURE_VERSION
    assert vol_of_vol_payload["version"] == FEATURE_VERSION
    assert realized_payload["feature"] == FEATURE_NAME_REALIZED_VOL
    assert vol_of_vol_payload["feature"] == FEATURE_NAME_VOL_OF_VOL


def test_payload_records_what_the_number_is_a_fact_over() -> None:
    # The payload is self-describing about its sample and its definition:
    # which horizons were computed, how many slots served each, the base and
    # vol windows, the annualization, and the universe size.
    realized_payload = json.loads(encode_realized_volatility(REALIZED, top_n=50))
    vol_of_vol_payload = json.loads(encode_vol_of_vol(VOL_OF_VOL, top_n=50))
    assert realized_payload["top_n"] == 50
    assert realized_payload["horizons"] == [10, 21, 63]
    assert realized_payload["observations"] == [10, 21, 63]
    assert realized_payload["annualization"] == 365.0
    assert vol_of_vol_payload["base_window"] == 21
    assert vol_of_vol_payload["window"] == 60
    assert vol_of_vol_payload["n"] == 60
    assert realized_payload["definition"] == REALIZED_VOL_DEFINITION
    assert vol_of_vol_payload["definition"] == VOL_OF_VOL_DEFINITION


def test_nan_volatilities_survive_the_round_trip() -> None:
    # An unscored horizon is nan, and nan must come back as nan rather than
    # as a zero the reader would mistake for a measured calm.
    result = RealizedVolatilityResult(
        horizons=(10, 63),
        volatilities=(0.7, float("nan")),
        observations=(10, 0),
        annualization=365.0,
    )
    decoded = decode_realized_volatility(
        encode_realized_volatility(result, top_n=50)
    )
    assert decoded.volatilities[0] == pytest.approx(0.7)
    assert math.isnan(decoded.volatilities[1])
    assert decoded.observations == (10, 0)


def test_a_nan_vol_of_vol_survives_the_round_trip() -> None:
    # A too-thin vol window is nan with the mean still reported — both halves
    # of that honesty must survive storage.
    result = VolOfVolResult(
        vol_of_vol=float("nan"),
        mean_vol=0.6,
        n=31,
        base_window=21,
        window=60,
        annualization=365.0,
    )
    decoded = decode_vol_of_vol(encode_vol_of_vol(result, top_n=50))
    assert math.isnan(decoded.vol_of_vol)
    assert decoded.mean_vol == pytest.approx(0.6)
    assert decoded.n == 31


def test_a_payload_naming_another_feature_is_rejected() -> None:
    with pytest.raises(ValueError, match="must name"):
        decode_realized_volatility(
            b'{"feature":"something_else","version":"1"}'
        )


def test_a_payload_stamped_with_another_version_is_rejected() -> None:
    # A later-version payload is a *different stored feature*, not something
    # this version-1 decoder reinterprets.
    envelope = json.dumps(
        {"feature": FEATURE_NAME_VOL_OF_VOL, "version": "2", "vol_of_vol": 0.1,
         "mean_vol": 0.6, "n": 60, "base_window": 21, "window": 60,
         "annualization": 365.0, "top_n": 50}
    ).encode()
    with pytest.raises(ValueError, match="version"):
        decode_vol_of_vol(envelope)


# ---------------------------------------------------------------------------
# Keys and the version stamp
# ---------------------------------------------------------------------------


def test_keys_carry_the_version_stamp_and_market_wide_symbol() -> None:
    store = VolatilityFeatureStore(FeatureStore())
    for key in (
        store.realized_vol_key(SNAPSHOT),
        store.vol_of_vol_key(SNAPSHOT),
    ):
        assert isinstance(key, FeatureKey)
        assert key.feature_version == FEATURE_VERSION
        assert key.symbol == MARKET_WIDE_SYMBOL
        assert key.frequency is Frequency.D1
        assert key.snapshot_hash == SNAPSHOT


def test_each_metric_is_persisted_under_its_own_name() -> None:
    # "Persisting each" means two records, two feature names: the realized
    # volatility and the vol-of-vol are distinct stored features, never two
    # fields of one payload.
    store = VolatilityFeatureStore(FeatureStore())
    assert store.realized_vol_key(SNAPSHOT) != store.vol_of_vol_key(SNAPSHOT)
    assert store.realized_vol_key(SNAPSHOT).feature_name == (
        FEATURE_NAME_REALIZED_VOL
    )
    assert store.vol_of_vol_key(SNAPSHOT).feature_name == FEATURE_NAME_VOL_OF_VOL


def test_feature_version_is_part_of_the_key_of_path() -> None:
    # The stamp is a path segment, so two versions are two on-disk
    # addresses — the version cannot be lost in storage.
    store = VolatilityFeatureStore(FeatureStore())
    parts = store.realized_vol_key(SNAPSHOT).to_path().parts
    assert len(parts) == 5
    assert parts[1] == FEATURE_VERSION


def test_feature_version_spelling_is_shared() -> None:
    # A caller assembling a key by hand and a caller reading the stamp off a
    # record share one spelling.
    assert feature_version() == FEATURE_VERSION


def test_definition_parameters_name_the_version_they_stamp() -> None:
    # The stamp and the definition it stands for stay one lookup apart, so a
    # reader can check what version 1 means without reading the computation.
    parameters = definition_parameters()
    assert parameters["feature_version"] == FEATURE_VERSION
    assert parameters["realized_volatility"] == REALIZED_VOL_DEFINITION
    assert parameters["volatility_of_volatility"] == VOL_OF_VOL_DEFINITION
    assert len(parameters["horizons"]) >= 2  # "multi-horizon"
    assert parameters["base_window"] in parameters["horizons"]
    assert parameters["annualization"] == 365.0


# ---------------------------------------------------------------------------
# The persistence surface
# ---------------------------------------------------------------------------


def test_persist_then_load_round_trips_both_metrics() -> None:
    store = FeatureStore()
    volatility_store = VolatilityFeatureStore(store)
    metrics = VolatilityMetrics(realized=REALIZED, vol_of_vol=VOL_OF_VOL)
    keys = volatility_store.persist(SNAPSHOT, metrics, top_n=50)
    assert len(keys) == 2
    assert volatility_store.load(SNAPSHOT) == metrics
    assert volatility_store.load_realized_volatility(SNAPSHOT) == REALIZED
    assert volatility_store.load_vol_of_vol(SNAPSHOT) == VOL_OF_VOL
    assert len(store) == 2


def test_persist_stores_under_the_market_wide_daily_keys() -> None:
    # Both records are market-wide facts, so both carry the sentinel symbol —
    # feature 48's key admits no four-component form.
    store = FeatureStore()
    volatility_store = VolatilityFeatureStore(store)
    volatility_store.persist(
        SNAPSHOT,
        VolatilityMetrics(REALIZED, VOL_OF_VOL),
        top_n=50,
    )
    assert volatility_store.realized_vol_key(SNAPSHOT) in store
    assert volatility_store.vol_of_vol_key(SNAPSHOT) in store
    for key in store.keys():
        assert key.symbol == MARKET_WIDE_SYMBOL


def test_different_snapshots_do_not_share_records() -> None:
    # The snapshot hash pins which sealed bars the metrics were computed over,
    # so a replay opening different bytes reads different records.
    store = FeatureStore()
    volatility_store = VolatilityFeatureStore(store)
    volatility_store.persist(
        SNAPSHOT, VolatilityMetrics(REALIZED, VOL_OF_VOL), top_n=50
    )
    assert volatility_store.load(OTHER_SNAPSHOT) is None


def test_a_second_persist_of_the_same_key_is_an_error() -> None:
    # An exact-key collision means two writers believe they computed the same
    # thing; the store surfaces it rather than silently clobbering.
    store = FeatureStore()
    volatility_store = VolatilityFeatureStore(store)
    metrics = VolatilityMetrics(REALIZED, VOL_OF_VOL)
    volatility_store.persist(SNAPSHOT, metrics, top_n=50)
    with pytest.raises(DuplicateFeatureKeyError):
        volatility_store.persist(SNAPSHOT, metrics, top_n=50)
    # Replacing is an explicit decision.
    volatility_store.persist(SNAPSHOT, metrics, top_n=50, replace=True)
    assert len(store) == 2


def test_load_returns_none_when_neither_metric_is_stored() -> None:
    # An unpersisted snapshot is a normal point-in-time miss.
    volatility_store = VolatilityFeatureStore(FeatureStore())
    assert volatility_store.load(SNAPSHOT) is None


def test_half_a_pair_is_an_error_not_half_a_value() -> None:
    # A persist interrupted between the two writes leaves exactly one record;
    # no reader should have to paper over that.
    store = FeatureStore()
    volatility_store = VolatilityFeatureStore(store)
    store.put(
        FeatureRecord(
            key=volatility_store.realized_vol_key(SNAPSHOT),
            payload=encode_realized_volatility(REALIZED, top_n=50),
        )
    )
    with pytest.raises(IncompleteVolatilityMetricsError):
        volatility_store.load(SNAPSHOT)


def test_the_wrapper_requires_a_put_get_surface() -> None:
    with pytest.raises(TypeError, match="exposing put"):
        VolatilityFeatureStore(object())


# ---------------------------------------------------------------------------
# The version stamp as a versioning mechanism (feature 53's contract)
# ---------------------------------------------------------------------------


def test_a_new_version_lands_beside_the_old_rows() -> None:
    # The whole reason the stamp is in the key: a changed definition writes
    # under a new version and leaves the version-1 rows untouched, rather than
    # overwriting numbers a replay may still be reading.
    store = FeatureStore()
    version_1_key = FeatureKey(
        feature_name=FEATURE_NAME_REALIZED_VOL,
        feature_version=FEATURE_VERSION,
        snapshot_hash=SNAPSHOT,
        symbol=MARKET_WIDE_SYMBOL,
        frequency=Frequency.D1,
    )
    store.put(
        FeatureRecord(
            key=version_1_key,
            payload=encode_realized_volatility(REALIZED, top_n=50),
        )
    )
    version_2_key = FeatureKey(
        feature_name=FEATURE_NAME_REALIZED_VOL,
        feature_version="2",
        snapshot_hash=SNAPSHOT,
        symbol=MARKET_WIDE_SYMBOL,
        frequency=Frequency.D1,
    )
    # A different definition's numbers, stored without touching version 1.
    store.put(
        FeatureRecord(
            key=version_2_key,
            payload=encode_realized_volatility(
                RealizedVolatilityResult(
                    horizons=(20,),
                    volatilities=(0.5,),
                    observations=(20,),
                    annualization=252.0,
                ),
                top_n=50,
            ),
        )
    )
    assert len(store) == 2
    # The version-1 row is byte-identical to what was written.
    assert store.get(version_1_key).payload == encode_realized_volatility(
        REALIZED, top_n=50
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
