"""Acceptance tests for the universe definition value object.

The definition enters the snapshot hash (§4.2), so it must be immutable
and hashable — a value, not a bag of state.
"""

import dataclasses

import pytest

from universe import UniverseConfig


def test_defaults_encode_the_spec() -> None:
    # 100-symbol universe per the architecture; 30-day median window per
    # the feature; eligibility floor left at the spec's exact rule.
    config = UniverseConfig()
    assert config.top_n == 100
    assert config.window_days == 30
    assert config.min_observations == 1


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
