"""Feature 57's persistence contract: the two metrics as feature-store records.

app_spec.xml feature 57: *System computes mean pairwise correlation of the
top 50 symbols plus breadth above an N-day moving average, persisting both.*
These tests pin the persisting half of that sentence — the encode/decode of
each metric to its opaque payload, and the round trip through a
:class:`FeatureStore` under the market-wide daily key — independent of how the
numbers are computed.  The invariants:

* each metric round-trips losslessly through encode then decode, provenance
  (top-N, overlap floor, breadth window) included;
* both are stored under the market-wide sentinel symbol at the daily
  frequency, keyed by feature name + version + snapshot hash (feature 48's
  five-component identity, which admits no four-component keys);
* the two are persisted as a pair and read back as a pair — finding only one
  under a snapshot hash is an error, not half a value;
* the payloads are deterministic, so the same metric always encodes to the
  same bytes — the replay path compares payloads.
"""

import json

import pytest

from feature_store.keys import (
    MARKET_WIDE_SYMBOL,
    FeatureKey,
    Frequency,
)
from feature_store.persistence import (
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
from feature_store.regime import (
    BreadthResult,
    CorrelationResult,
    RegimeMetrics,
)
from feature_store.store import DuplicateFeatureKeyError, FeatureRecord, FeatureStore

SNAPSHOT = "a" * 64
OTHER_SNAPSHOT = "b" * 64

CORRELATION = CorrelationResult(mean=0.42, pairs=1225, min_overlap=30)
BREADTH = BreadthResult(count=27, above=27, total=50, window=50)


# ---------------------------------------------------------------------------
# Payload encode/decode
# ---------------------------------------------------------------------------


def test_correlation_round_trips_with_provenance() -> None:
    payload = encode_correlation(CORRELATION, top_n=50)
    assert decode_correlation(payload) == CORRELATION


def test_breadth_round_trips_with_provenance() -> None:
    payload = encode_breadth(BREADTH, top_n=50)
    assert decode_breadth(payload) == BREADTH


def test_payload_is_a_self_describing_json_envelope() -> None:
    # The opaque bytes are a JSON envelope naming the feature, its version,
    # the top-N, and the metric's own provenance — so a reader can interpret
    # the bytes without guessing.
    envelope = json.loads(encode_correlation(CORRELATION, top_n=50))
    assert envelope["feature"] == FEATURE_NAME_CORRELATION
    assert envelope["version"] == FEATURE_VERSION
    assert envelope["top_n"] == 50
    assert envelope["min_overlap"] == 30
    assert envelope["pairs"] == 1225
    assert envelope["mean"] == 0.42


def test_payload_is_deterministic() -> None:
    # The same metric encodes to byte-identical payload, so a replay that
    # compares payloads does not flake.
    assert encode_correlation(CORRELATION, top_n=50) == encode_correlation(
        CORRELATION, top_n=50
    )
    assert encode_breadth(BREADTH, top_n=50) == encode_breadth(BREADTH, top_n=50)


def test_decode_rejects_a_payload_for_the_other_feature() -> None:
    with pytest.raises(ValueError, match="correlation"):
        decode_correlation(encode_breadth(BREADTH, top_n=50))
    with pytest.raises(ValueError, match="breadth"):
        decode_breadth(encode_correlation(CORRELATION, top_n=50))


# ---------------------------------------------------------------------------
# The keys: market-wide, daily, five-component
# ---------------------------------------------------------------------------


def test_keys_are_market_wide_daily_and_five_component() -> None:
    store = RegimeFeatureStore(FeatureStore())
    correlation_key = store.correlation_key(SNAPSHOT)
    breadth_key = store.breadth_key(SNAPSHOT)
    assert correlation_key.feature_name == FEATURE_NAME_CORRELATION
    assert breadth_key.feature_name == FEATURE_NAME_BREADTH
    assert correlation_key.feature_version == FEATURE_VERSION
    assert breadth_key.feature_version == FEATURE_VERSION
    assert correlation_key.snapshot_hash == SNAPSHOT
    assert breadth_key.snapshot_hash == SNAPSHOT
    # Market-wide features still carry a symbol — feature 48 admits no
    # four-component keys — the sentinel, not an instrument.
    assert correlation_key.symbol == MARKET_WIDE_SYMBOL
    assert breadth_key.symbol == MARKET_WIDE_SYMBOL
    # Daily frequency: the universe is ranked monthly, but the metrics are
    # computed over daily bars, so they are keyed at the daily bar grid.
    assert correlation_key.frequency == Frequency.D1
    assert breadth_key.frequency == Frequency.D1


def test_two_metrics_differ_only_in_feature_name() -> None:
    store = RegimeFeatureStore(FeatureStore())
    # Same version, snapshot, symbol and frequency — the two records are one
    # snapshot's pair, distinguished only by which metric they hold.
    assert (
        store.correlation_key(SNAPSHOT).to_tuple()[1:]
        == store.breadth_key(SNAPSHOT).to_tuple()[1:]
    )
    assert (
        store.correlation_key(SNAPSHOT).feature_name
        != store.breadth_key(SNAPSHOT).feature_name
    )


# ---------------------------------------------------------------------------
# Persist and read back
# ---------------------------------------------------------------------------


def test_persist_then_load_returns_both_metrics() -> None:
    store = RegimeFeatureStore(FeatureStore())
    metrics = RegimeMetrics(correlation=CORRELATION, breadth=BREADTH)
    keys = store.persist(SNAPSHOT, metrics, top_n=50)
    assert keys == (store.correlation_key(SNAPSHOT), store.breadth_key(SNAPSHOT))
    assert store.load(SNAPSHOT) == metrics


def test_load_separates_the_two_metrics() -> None:
    store = RegimeFeatureStore(FeatureStore())
    store.persist(SNAPSHOT, RegimeMetrics(correlation=CORRELATION, breadth=BREADTH), top_n=50)
    assert store.load_correlation(SNAPSHOT) == CORRELATION
    assert store.load_breadth(SNAPSHOT) == BREADTH


def test_load_misses_an_unpersisted_snapshot() -> None:
    # A snapshot with neither metric stored is a normal point-in-time miss:
    # None, not an error.
    store = RegimeFeatureStore(FeatureStore())
    assert store.load(OTHER_SNAPSHOT) is None
    assert store.load_correlation(OTHER_SNAPSHOT) is None
    assert store.load_breadth(OTHER_SNAPSHOT) is None


def test_persisting_a_second_snapshot_is_a_distinct_pair() -> None:
    # Feature 48: the snapshot hash is part of the key, so two snapshots are
    # two independent pairs of records, neither shadowing the other.
    store = RegimeFeatureStore(FeatureStore())
    metrics = RegimeMetrics(correlation=CORRELATION, breadth=BREADTH)
    store.persist(SNAPSHOT, metrics, top_n=50)
    other = RegimeMetrics(correlation=CorrelationResult(0.1, 10, 30), breadth=BREADTH)
    store.persist(OTHER_SNAPSHOT, other, top_n=50)
    assert store.load(SNAPSHOT) == metrics
    assert store.load(OTHER_SNAPSHOT) == other


def test_re_persist_is_rejected_not_replaced() -> None:
    # Storing the same snapshot twice is a duplicate-key error on the
    # underlying store, not a silent overwrite — a second computation surfaces
    # rather than clobbering the first.
    store = RegimeFeatureStore(FeatureStore())
    store.persist(SNAPSHOT, RegimeMetrics(correlation=CORRELATION, breadth=BREADTH), top_n=50)
    with pytest.raises(DuplicateFeatureKeyError):
        store.persist(SNAPSHOT, RegimeMetrics(correlation=CORRELATION, breadth=BREADTH), top_n=50)


def test_only_one_metric_stored_is_an_incomplete_pair() -> None:
    # The pair must be persisted together; finding only one under a snapshot
    # hash is a persist that was interrupted, raised rather than returned as
    # half a value.
    store = FeatureStore()
    store.put(
        FeatureRecord(
            key=RegimeFeatureStore(store).correlation_key(SNAPSHOT),
            payload=encode_correlation(CORRELATION, top_n=50),
        )
    )
    regime_store = RegimeFeatureStore(store)
    assert regime_store.load_correlation(SNAPSHOT) == CORRELATION
    assert regime_store.load_breadth(SNAPSHOT) is None
    with pytest.raises(IncompleteRegimeMetricsError):
        regime_store.load(SNAPSHOT)
