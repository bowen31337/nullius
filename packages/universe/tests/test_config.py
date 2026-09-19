"""Acceptance tests for the universe definition value object.

The definition enters the snapshot hash (§4.2), so it must be immutable
and hashable — a value, not a bag of state.
"""

import dataclasses

import pytest

from universe import UniverseConfig


def test_defaults_encode_the_spec() -> None:
    # 100-symbol universe per the architecture; 30-day median window per
    # the feature; observation floor left at the spec's exact rule; dollar
    # floor of 0 configures no floor, so feature 40's plain ranking rule
    # is the default behavior.
    config = UniverseConfig()
    assert config.top_n == 100
    assert config.window_days == 30
    assert config.min_observations == 1
    assert config.min_dollar_volume == 0.0


def test_config_is_frozen() -> None:
    config = UniverseConfig(top_n=25)
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.top_n = 50  # type: ignore[misc]


def test_config_is_hashable_and_equal_by_value() -> None:
    # Hashable, so a definition can key a cache or enter a snapshot hash.
    first = UniverseConfig(top_n=25, window_days=30, min_observations=2)
    second = UniverseConfig(top_n=25, window_days=30, min_observations=2)
    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1
    assert first != UniverseConfig(top_n=26)


@pytest.mark.parametrize("field", ["top_n", "window_days", "min_observations"])
def test_below_one_rejected(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        UniverseConfig(**{field: 0})


@pytest.mark.parametrize("field", ["top_n", "window_days", "min_observations"])
def test_non_integer_rejected(field: str) -> None:
    with pytest.raises(TypeError, match=field):
        UniverseConfig(**{field: "10"})  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["top_n", "window_days", "min_observations"])
def test_bool_rejected_even_though_bool_is_int(field: str) -> None:
    # True == 1 numerically, but a definition knob set to a boolean is a
    # caller error the config should surface, not absorb.
    with pytest.raises(TypeError, match=field):
        UniverseConfig(**{field: True})  # type: ignore[arg-type]


class TestDollarVolumeFloor:
    def test_floor_accepts_int_and_pins_to_float(self) -> None:
        # 10_000 and 10_000.0 must be the same definition — one spelling.
        config = UniverseConfig(min_dollar_volume=10_000)
        assert config.min_dollar_volume == 10_000.0
        assert isinstance(config.min_dollar_volume, float)
        assert config == UniverseConfig(min_dollar_volume=10_000.0)

    def test_negative_floor_rejected(self) -> None:
        with pytest.raises(ValueError, match="min_dollar_volume"):
            UniverseConfig(min_dollar_volume=-0.01)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_floor_rejected(self, bad: float) -> None:
        # float("nan") parses from the environment too; a NaN floor would
        # silently exclude nothing and everything at once.
        with pytest.raises(ValueError, match="min_dollar_volume"):
            UniverseConfig(min_dollar_volume=bad)

    def test_non_numeric_floor_rejected(self) -> None:
        with pytest.raises(TypeError, match="min_dollar_volume"):
            UniverseConfig(min_dollar_volume="10k")  # type: ignore[arg-type]

    def test_bool_floor_rejected_even_though_bool_is_numeric(self) -> None:
        with pytest.raises(TypeError, match="min_dollar_volume"):
            UniverseConfig(min_dollar_volume=True)  # type: ignore[arg-type]

    def test_floor_participates_in_equality_and_hash(self) -> None:
        # The definition enters the snapshot hash, so a changed floor must
        # be a changed (unequal) definition — and equal floors must hash
        # equal, whatever notation spelled them.
        floor_one = UniverseConfig(min_dollar_volume=25_000.0)
        assert floor_one == UniverseConfig(min_dollar_volume=25_000)
        assert hash(floor_one) == hash(UniverseConfig(min_dollar_volume=25_000))
        assert floor_one != UniverseConfig(min_dollar_volume=25_001.0)
        assert len({floor_one, UniverseConfig(min_dollar_volume=25_000)}) == 1
