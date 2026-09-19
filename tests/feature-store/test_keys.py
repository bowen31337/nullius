"""Feature 48's identity contract: the five-component FeatureKey.

app_spec.xml, "Point-in-Time Feature Store", feature 48: *System keys
every stored feature with feature_name, feature_version, snapshot_hash,
symbol and frequency.*  These tests pin that a key always carries all
five components, always in canonical order, always validated and
normalised — and that differing in exactly one component yields a
different key.
"""

from dataclasses import FrozenInstanceError
from pathlib import Path, PurePosixPath

import pytest

from feature_store import (
    FREQUENCIES,
    MARKET_WIDE_SYMBOL,
    FeatureKey,
    FeatureKeyError,
    Frequency,
)

SNAPSHOT = "f" * 64  # a canonical lowercase sha256 hexdigest


def make_key(**overrides: object) -> FeatureKey:
    """A valid key, with any single component overridden."""
    components: dict[str, object] = {
        "feature_name": "realized_vol_30",
        "feature_version": "1",
        "snapshot_hash": SNAPSHOT,
        "symbol": "BTCUSDT",
        "frequency": "1m",
    }
    components.update(overrides)
    return FeatureKey(**components)  # type: ignore[arg-type]


def test_key_carries_all_five_components() -> None:
    key = make_key()
    assert key.feature_name == "realized_vol_30"
    assert key.feature_version == "1"
    assert key.snapshot_hash == SNAPSHOT
    assert key.symbol == "BTCUSDT"
    assert key.frequency == Frequency.M1


def test_canonical_order_is_name_version_snapshot_symbol_frequency() -> None:
    # The order the spec text and §4.4 both state — and the one to_path()
    # and str() must never drift from.
    key = make_key()
    assert key.to_tuple() == ("realized_vol_30", "1", SNAPSHOT, "BTCUSDT", "1m")
    assert str(key) == f"realized_vol_30/1/{SNAPSHOT}/BTCUSDT/1m"
    assert key.to_path() == PurePosixPath("realized_vol_30", "1", SNAPSHOT, "BTCUSDT", "1m")


@pytest.mark.parametrize(
    "field,other",
    [
        ("feature_name", "return_autocorr_5"),  # a different definition
        ("feature_version", "2"),  # a changed definition (feature 53)
        ("snapshot_hash", "0" * 64),  # a different sealed snapshot
        ("symbol", "ETHUSDT"),  # a different instrument
        ("frequency", "1d"),  # a different bar grid
    ],
)
def test_keys_differing_in_exactly_one_component_are_distinct(
    field: str, other: str
) -> None:
    # The heart of feature 48: every component participates in identity.
    base = make_key()
    variant = make_key(**{field: other})
    assert variant != base
    assert len({base, variant}) == 2


def test_equal_keys_are_interchangeable_dict_addresses() -> None:
    assert make_key() == make_key()
    assert hash(make_key()) == hash(make_key())
    table = {make_key(): "first"}
    table[make_key()] = "second"  # same address, one entry
    assert table == {make_key(): "second"}


def test_snapshot_hash_uppercase_is_normalised_to_lowercase() -> None:
    # Content addressing: two spellings of one digest are one identity,
    # never two stored features.
    upper = make_key(snapshot_hash=SNAPSHOT.upper())
    assert upper == make_key()
    assert upper.snapshot_hash == SNAPSHOT


@pytest.mark.parametrize(
    "bad_hash",
    [
        "",
        "   ",
        "f" * 63,  # one short
        "f" * 65,  # one long
        "z" * 64,  # not hex
        "not-a-hash",
        "f" * 32,  # md5-length, still wrong
    ],
)
def test_malformed_snapshot_hash_is_rejected(bad_hash: str) -> None:
    with pytest.raises(FeatureKeyError, match="snapshot_hash"):
        make_key(snapshot_hash=bad_hash)


@pytest.mark.parametrize("field", ["feature_name", "feature_version", "symbol"])
@pytest.mark.parametrize(
    "bad_value",
    ["", "   ", " padded", "padded ", "a/b", "a\\b", ".", "..", "a\tb", "a\nb"],
)
def test_path_unsafe_or_padded_components_are_rejected(
    field: str, bad_value: str
) -> None:
    # A key doubles as a relative POSIX path, so a component that could
    # escape its segment — or is merely ambiguous padding — cannot exist.
    with pytest.raises(FeatureKeyError, match=field):
        make_key(**{field: bad_value})


@pytest.mark.parametrize("field", ["feature_name", "feature_version", "symbol"])
def test_non_string_components_are_rejected(field: str) -> None:
    with pytest.raises(FeatureKeyError, match=field):
        make_key(**{field: 42})


def test_non_string_snapshot_hash_is_rejected() -> None:
    with pytest.raises(FeatureKeyError, match="snapshot_hash"):
        make_key(snapshot_hash=64)  # type: ignore[dict-item]


@pytest.mark.parametrize("freq", FREQUENCIES)
def test_frequency_accepts_exactly_the_window_contract_values(freq: str) -> None:
    # §5.1's Literal["1m","1h","1d"]: the key and MarketWindow must agree.
    key = make_key(frequency=freq)
    assert str(key.frequency) == freq
    assert key.frequency == Frequency(freq)


def test_frequency_accepts_enum_members_canonically() -> None:
    assert make_key(frequency=Frequency.D1) == make_key(frequency="1d")
    assert make_key(frequency="1h").frequency is Frequency.H1


@pytest.mark.parametrize("bad_freq", ["2m", "1M", "daily", "", " 1d", None, 60])
def test_unknown_frequency_is_rejected_naming_the_valid_values(
    bad_freq: object,
) -> None:
    with pytest.raises(FeatureKeyError, match="frequency must be one of 1m, 1h, 1d"):
        make_key(frequency=bad_freq)


def test_key_is_immutable() -> None:
    key = make_key()
    with pytest.raises(FrozenInstanceError):
        key.symbol = "ETHUSDT"  # type: ignore[misc]


def test_path_round_trip() -> None:
    key = make_key()
    assert FeatureKey.from_path(key.to_path()) == key
    assert FeatureKey.from_path(str(key)) == key


@pytest.mark.parametrize(
    "path",
    [
        "realized_vol_30/1/" + SNAPSHOT,  # too few segments
        f"realized_vol_30/1/{SNAPSHOT}/BTCUSDT/1m/extra",  # too many
        f"/realized_vol_30/1/{SNAPSHOT}/BTCUSDT/1m",  # absolute
        "",
    ],
)
def test_from_path_rejects_malformed_paths(path: str) -> None:
    with pytest.raises(FeatureKeyError, match="five relative segments"):
        FeatureKey.from_path(path)


def test_from_path_still_validates_components() -> None:
    with pytest.raises(FeatureKeyError, match="snapshot_hash"):
        FeatureKey.from_path(f"name/1/not-a-hash/BTCUSDT/1m")


def test_market_wide_features_carry_the_sentinel_symbol() -> None:
    # Cross-sectional features (56/57) are still keyed with a symbol —
    # feature 48 admits no four-component keys — so they carry the
    # sentinel, and the sentinel is a valid symbol like any other.
    key = make_key(symbol=MARKET_WIDE_SYMBOL, feature_name="return_dispersion")
    assert key.symbol == MARKET_WIDE_SYMBOL
    assert key == make_key(symbol=MARKET_WIDE_SYMBOL, feature_name="return_dispersion")


def test_key_composes_under_a_lake_root(lake_root: Path) -> None:
    # §4.2 integration: the five segments mount under any root without
    # escaping their segment — here the test lake the fixtures provide.
    key = make_key()
    mounted = lake_root / "features" / key.to_path()
    assert mounted.relative_to(lake_root).parts == (
        "features",
        "realized_vol_30",
        "1",
        SNAPSHOT,
        "BTCUSDT",
        "1m",
    )
