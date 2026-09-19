"""Feature 58's persistence contract: labels as versioned feature-store records.

app_spec.xml feature 58: *System labels market regimes using a rolling-window
fit only.*  These tests pin how the labels become feature-store records and
how they read back — the market-wide daily key, the version stamp, the opaque
payload — independent of how the labels are computed.  The invariants:

* the record is keyed market-wide, at the daily frequency, under the current
  ``feature_version`` — the stamp is a segment of the address, not a field in
  the payload;
* the payload is a deterministic, self-describing JSON envelope, so the same
  labels always encode to byte-identical bytes — the replay path compares
  payloads;
* a stored record round-trips exactly, labels aligned to dates, ``null``
  where no label was produced;
* a version bump lands beside the old rows rather than on top of them.
"""

import datetime as dt

import pytest

from feature_store.keys import FeatureKey, Frequency, MARKET_WIDE_SYMBOL
from feature_store.regime_labeler import RegimeLabels
from feature_store.regime_labeler_persistence import (
    FEATURE_NAME_LABELS,
    FEATURE_VERSION,
    LABELS_DEFINITION,
    IncompleteLabelerMetricsError,
    RegimeLabelerFeatureStore,
    decode_labels,
    definition_parameters,
    encode_labels,
    feature_version,
)
from feature_store.store import DuplicateFeatureKeyError, FeatureRecord, FeatureStore

SNAPSHOT = "a" * 64


def make_labels() -> RegimeLabels:
    """A small labels value: three dated labels, one unlabeled."""
    dates = (
        dt.date(2026, 1, 3),
        dt.date(2026, 1, 4),
        dt.date(2026, 1, 5),
        dt.date(2026, 1, 6),
    )
    labels = (None, 0, 2, 1)
    return RegimeLabels(
        dates=dates, labels=labels, k=3, window=20, n_labeled=3
    )


# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------


def test_key_is_market_wide_daily_version_stamped() -> None:
    # The record is market-wide, daily, and carries the version stamp as a
    # segment of the address — feature 48's five-component key.
    key = RegimeLabelerFeatureStore.labels_key(SNAPSHOT)
    assert key == FeatureKey(
        feature_name=FEATURE_NAME_LABELS,
        feature_version=FEATURE_VERSION,
        snapshot_hash=SNAPSHOT,
        symbol=MARKET_WIDE_SYMBOL,
        frequency=Frequency.D1,
    )


def test_feature_version_matches_the_payload_stamp() -> None:
    # The address and the envelope carry the same version, so they cannot
    # disagree about which definition produced the row.
    assert feature_version() == FEATURE_VERSION
    envelope = encode_labels(make_labels(), top_n=50)
    assert b'"version":"' + FEATURE_VERSION.encode() in envelope


# ---------------------------------------------------------------------------
# The payload
# ---------------------------------------------------------------------------


def test_encode_is_deterministic() -> None:
    # The same labels always encode to byte-identical bytes — sorted keys, no
    # incidental whitespace — so the replay path can compare payloads.
    first = encode_labels(make_labels(), top_n=50)
    second = encode_labels(make_labels(), top_n=50)
    assert first == second


def test_encode_carries_the_definition_and_fit_parameters() -> None:
    # A reader with only the payload can tell which definition it is looking at
    # and how each date was labelled.
    payload = encode_labels(make_labels(), top_n=50)
    import json

    body = json.loads(payload)
    assert body["feature"] == FEATURE_NAME_LABELS
    assert body["version"] == FEATURE_VERSION
    assert body["definition"] == LABELS_DEFINITION
    assert body["top_n"] == 50
    assert body["k"] == 3
    assert body["window"] == 20
    assert body["labels"] == [None, 0, 2, 1]
    assert body["dates"] == [d.isoformat() for d in make_labels().dates]


def test_round_trip_preserves_alignment_including_nulls() -> None:
    # The stored labels read back exactly, with the ``null`` where no label was
    # produced still aligned to its date.
    labels = make_labels()
    restored = decode_labels(encode_labels(labels, top_n=50))
    assert restored.dates == labels.dates
    assert restored.labels == labels.labels
    assert restored.k == labels.k
    assert restored.window == labels.window
    assert restored.n_labeled == labels.n_labeled


def test_decode_rejects_a_wrong_feature() -> None:
    import json

    body = json.loads(encode_labels(make_labels(), top_n=50))
    body["feature"] = "some_other_feature"
    with pytest.raises(ValueError):
        decode_labels(json.dumps(body).encode())


def test_decode_rejects_a_wrong_version() -> None:
    import json

    body = json.loads(encode_labels(make_labels(), top_n=50))
    body["version"] = "2"
    with pytest.raises(ValueError):
        decode_labels(json.dumps(body).encode())


def test_decode_rejects_a_misaligned_payload() -> None:
    # A payload whose labels and dates disagree is a malformed persist, not a
    # value to hand back.
    import json

    body = json.loads(encode_labels(make_labels(), top_n=50))
    body["labels"].append(2)  # now labels and dates disagree in length
    with pytest.raises(IncompleteLabelerMetricsError):
        decode_labels(json.dumps(body).encode())


# ---------------------------------------------------------------------------
# The persistence surface
# ---------------------------------------------------------------------------


def test_persist_and_load_round_trip() -> None:
    # Store the labels under the market-wide daily key; read them back.
    store = FeatureStore()
    wrapper = RegimeLabelerFeatureStore(store)
    key = wrapper.persist(SNAPSHOT, make_labels(), top_n=50)
    assert key == RegimeLabelerFeatureStore.labels_key(SNAPSHOT)
    restored = wrapper.load(SNAPSHOT)
    assert restored is not None
    assert restored.labels == make_labels().labels


def test_load_of_absent_snapshot_returns_none() -> None:
    # An unpersisted snapshot is a normal point-in-time miss, not an error.
    store = FeatureStore()
    assert RegimeLabelerFeatureStore(store).load(SNAPSHOT) is None


def test_persist_refuses_a_duplicate_key() -> None:
    # Re-persisting an identical key is an error, not a silent clobber — an
    # exact-key collision almost always means two writers believe they computed
    # the same thing.
    store = FeatureStore()
    wrapper = RegimeLabelerFeatureStore(store)
    wrapper.persist(SNAPSHOT, make_labels(), top_n=50)
    with pytest.raises(DuplicateFeatureKeyError):
        wrapper.persist(SNAPSHOT, make_labels(), top_n=50)
    # An explicit replace is allowed.
    wrapper.persist(SNAPSHOT, make_labels(), top_n=50, replace=True)


def test_a_version_bump_lands_beside_the_old_rows() -> None:
    # Storing the same labels under a different version produces a *different*
    # key — the rows are distinct features, so the new one never clobbers the
    # old.  (Feature 53's contract, exercised through this feature's surface.)
    store = FeatureStore()
    wrapper = RegimeLabelerFeatureStore(store)
    v1_key = wrapper.persist(SNAPSHOT, make_labels(), top_n=50)
    bumped = FeatureKey(
        feature_name=FEATURE_NAME_LABELS,
        feature_version="2",
        snapshot_hash=SNAPSHOT,
        symbol=MARKET_WIDE_SYMBOL,
        frequency=Frequency.D1,
    )
    store.put(FeatureRecord(key=bumped, payload=encode_labels(make_labels(), top_n=50)))
    assert v1_key != bumped
    assert len(store) == 2


def test_definition_parameters_names_version_1() -> None:
    params = definition_parameters()
    assert params["feature_version"] == FEATURE_VERSION
    assert params["labels"] == LABELS_DEFINITION
    assert params["k"] == 3
    assert params["window"] == 63
