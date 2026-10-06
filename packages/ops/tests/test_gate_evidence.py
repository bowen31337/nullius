"""Feature 6's four read routes: the M3 gate evidence, served read-only.

additions_spec_operator_surfaces.xml, "Gate Evidence Surfaces", feature 6:
*System serves the M3 gate evidence through four read endpoints in a new
ops/gate_evidence.py, following the ops/regime_coverage.py pattern.*

This suite pins the shared law across all four routes (parametrized over
:data:`SURFACES`, below, one entry per route) and each route's own
identity (route string, component name, response and error types):

* each ``get()`` takes no arguments and answers a frozen response holding
  the owning store's :meth:`history` (oldest first) and that trend's
  newest row, derived as the last entry — never a separate store call;
* an empty store answers an empty history and a ``newest`` of ``None``,
  never a zero, and a store that records a genuine zero-valued row serves
  it like any other row (the absence and the measurement stay distinct);
* a store read that fails is translated into
  :class:`~ops.GateEvidenceMetricError`, chained, and a carrier bug that
  is not the store's own declared error propagates raw;
* ``from_env`` composes no endpoint without ``DATABASE_URL`` (absent,
  empty or whitespace-only), delegates entirely to the owning store's own
  ``resolve()``, and never touches the disk before the first read; and
* no response type's record carries an ``is_null`` label or a
  ``node_id`` paired with one — these stores hold only aggregates.

Fixtures use a real SQLite file under ``tmp_path`` with each store's own
class, mirroring ``test_regime_coverage.py`` and the member's other route
suites.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from ops import (
    DISCOVERY_RATE_ROUTE,
    META_OVERFIT_ROUTE,
    NULL_CALIBRATION_ROUTE,
    OPS_DISCOVERY_RATE_ROUTE_COMPONENT_NAME,
    OPS_META_OVERFIT_ROUTE_COMPONENT_NAME,
    OPS_NULL_CALIBRATION_ROUTE_COMPONENT_NAME,
    OPS_TYPE_B_DEPTH_ROUTE_COMPONENT_NAME,
    TYPE_B_DEPTH_ROUTE,
    DiscoveryRate,
    DiscoveryRateEndpoint,
    DiscoveryRateError,
    DiscoveryRateHistoryResponse,
    DiscoveryRates,
    GateEvidenceMetricError,
    MetaOverfitEndpoint,
    MetaOverfitGap,
    MetaOverfitGapError,
    MetaOverfitGaps,
    MetaOverfitHistoryResponse,
    NullCalibration,
    NullCalibrationEndpoint,
    NullCalibrationError,
    NullCalibrationHistoryResponse,
    NullCalibrations,
    TypeBDepth,
    TypeBDepthEndpoint,
    TypeBDepthError,
    TypeBDepthHistoryResponse,
    TypeBDepths,
)


def _write_null_calibration(store: NullCalibrations, key: str, recorded_at: str):
    return store.record(
        key, sensitivity=0.8, specificity=0.9, recorded_at=recorded_at
    )


def _write_zero_null_calibration(store: NullCalibrations, key: str, recorded_at: str):
    return store.record(
        key, sensitivity=0.0, specificity=1.0, recorded_at=recorded_at
    )


def _write_type_b_depth(store: TypeBDepths, key: str, recorded_at: str):
    return store.record(key, depth_past_flip_errors=3, recorded_at=recorded_at)


def _write_zero_type_b_depth(store: TypeBDepths, key: str, recorded_at: str):
    return store.record(key, depth_past_flip_errors=0, recorded_at=recorded_at)


def _write_discovery_rate(store: DiscoveryRates, key: str, recorded_at: str):
    return store.record(
        key,
        discoveries=2,
        budget_charging_trials=100,
        ledger_trials=120,
        recorded_at=recorded_at,
    )


def _write_zero_discovery_rate(store: DiscoveryRates, key: str, recorded_at: str):
    return store.record(
        key,
        discoveries=0,
        budget_charging_trials=100,
        ledger_trials=100,
        recorded_at=recorded_at,
    )


def _write_meta_overfit(store: MetaOverfitGaps, key: str, recorded_at: str):
    return store.record(
        key,
        train_mean=0.5,
        holdout_mean=0.2,
        train_worlds=10,
        holdout_worlds=5,
        recorded_at=recorded_at,
    )


def _write_zero_meta_overfit(store: MetaOverfitGaps, key: str, recorded_at: str):
    return store.record(
        key,
        train_mean=0.3,
        holdout_mean=0.3,
        train_worlds=10,
        holdout_worlds=5,
        recorded_at=recorded_at,
    )


class _Surface(NamedTuple):
    """One route's whole identity, for the shared tests below."""

    endpoint_cls: type
    response_cls: type
    record_type: type
    store_cls: type
    error_cls: type
    route: str
    component_name: str
    keys: tuple[str, str]
    write: Callable[[Any, str, str], Any]
    write_zero: Callable[[Any, str, str], Any]


SURFACES = [
    _Surface(
        NullCalibrationEndpoint,
        NullCalibrationHistoryResponse,
        NullCalibration,
        NullCalibrations,
        NullCalibrationError,
        NULL_CALIBRATION_ROUTE,
        OPS_NULL_CALIBRATION_ROUTE_COMPONENT_NAME,
        (
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        _write_null_calibration,
        _write_zero_null_calibration,
    ),
    _Surface(
        TypeBDepthEndpoint,
        TypeBDepthHistoryResponse,
        TypeBDepth,
        TypeBDepths,
        TypeBDepthError,
        TYPE_B_DEPTH_ROUTE,
        OPS_TYPE_B_DEPTH_ROUTE_COMPONENT_NAME,
        (
            "33333333-3333-3333-3333-333333333333",
            "44444444-4444-4444-4444-444444444444",
        ),
        _write_type_b_depth,
        _write_zero_type_b_depth,
    ),
    _Surface(
        DiscoveryRateEndpoint,
        DiscoveryRateHistoryResponse,
        DiscoveryRate,
        DiscoveryRates,
        DiscoveryRateError,
        DISCOVERY_RATE_ROUTE,
        OPS_DISCOVERY_RATE_ROUTE_COMPONENT_NAME,
        (
            "55555555-5555-5555-5555-555555555555",
            "66666666-6666-6666-6666-666666666666",
        ),
        _write_discovery_rate,
        _write_zero_discovery_rate,
    ),
    _Surface(
        MetaOverfitEndpoint,
        MetaOverfitHistoryResponse,
        MetaOverfitGap,
        MetaOverfitGaps,
        MetaOverfitGapError,
        META_OVERFIT_ROUTE,
        OPS_META_OVERFIT_ROUTE_COMPONENT_NAME,
        ("cycle-1", "cycle-2"),
        _write_meta_overfit,
        _write_zero_meta_overfit,
    ),
]


@pytest.fixture(params=SURFACES, ids=lambda surface: surface.route)
def surface(request: pytest.FixtureRequest) -> _Surface:
    return request.param


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A real SQLite file under the test's temporary directory."""
    return tmp_path / "gate-evidence.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """A ``sqlite:///`` URL naming the test-only database."""
    return f"sqlite:///{store_path}"


@pytest.fixture
def store(surface: _Surface, store_url: str) -> Any:
    """The surface's own store, bound to the test-only database."""
    return surface.store_cls(store_url)


@pytest.fixture
def endpoint(surface: _Surface, store: Any) -> Any:
    """The route over the surface's own store."""
    return surface.endpoint_cls(store)


# -- The route's name and shape --------------------------------------------


def test_the_route_is_the_one_the_spec_writes(surface: _Surface) -> None:
    assert surface.endpoint_cls.route == surface.route


def test_get_takes_no_arguments(surface: _Surface) -> None:
    signature = inspect.signature(surface.endpoint_cls.get)
    assert list(signature.parameters) == ["self"]


def test_the_route_strings_match_the_spec() -> None:
    assert NULL_CALIBRATION_ROUTE == "/metrics/null-calibration"
    assert TYPE_B_DEPTH_ROUTE == "/metrics/type-b-depth"
    assert DISCOVERY_RATE_ROUTE == "/metrics/discovery-rate"
    assert META_OVERFIT_ROUTE == "/metrics/meta-overfit"


def test_the_component_names_match_the_spec() -> None:
    assert OPS_NULL_CALIBRATION_ROUTE_COMPONENT_NAME == "ops-null-calibration-route"
    assert OPS_TYPE_B_DEPTH_ROUTE_COMPONENT_NAME == "ops-type-b-depth-route"
    assert OPS_DISCOVERY_RATE_ROUTE_COMPONENT_NAME == "ops-discovery-rate-route"
    assert OPS_META_OVERFIT_ROUTE_COMPONENT_NAME == "ops-meta-overfit-route"


def test_the_component_name_is_this_surfaces_own(surface: _Surface) -> None:
    assert surface.component_name.endswith("-route")


# -- Empty and populated stores ----------------------------------------------


def test_an_empty_store_answers_an_empty_history_and_no_newest(
    surface: _Surface, endpoint: Any
) -> None:
    response = endpoint.get()
    assert isinstance(response, surface.response_cls)
    assert response.history == ()
    assert response.newest is None
    assert not response
    assert len(response) == 0


def test_a_single_row_is_both_the_only_entry_and_the_newest(
    surface: _Surface, store: Any, endpoint: Any
) -> None:
    only = surface.write(store, surface.keys[0], "2026-01-01T00:00:00+00:00")
    response = endpoint.get()
    assert response.history == (only,)
    assert response.newest == only
    assert response
    assert len(response) == 1


def test_a_populated_store_answers_history_oldest_first_and_the_newest_row(
    surface: _Surface, store: Any, endpoint: Any
) -> None:
    older = surface.write(store, surface.keys[0], "2026-01-01T00:00:00+00:00")
    newer = surface.write(store, surface.keys[1], "2026-02-01T00:00:00+00:00")
    response = endpoint.get()
    assert response.history == (older, newer)
    assert response.newest == newer
    assert response.newest is response.history[-1]


def test_the_route_reads_the_store_every_time(
    surface: _Surface, store: Any, endpoint: Any
) -> None:
    # No memo of a previous answer: a row written between two reads must
    # move the second answer.
    assert endpoint.get().newest is None
    written = surface.write(store, surface.keys[0], "2026-01-01T00:00:00+00:00")
    assert endpoint.get().newest == written


def test_a_zero_measurement_is_served_as_a_row_not_an_absence(
    surface: _Surface, store: Any, endpoint: Any
) -> None:
    # The family's law, restated at the route: a store's own zero is a
    # measurement that store persists happily, and only the absence of a
    # row — never a zero one — answers None.
    zero = surface.write_zero(store, surface.keys[0], "2026-01-01T00:00:00+00:00")
    response = endpoint.get()
    assert response.history == (zero,)
    assert response.newest == zero
    assert response.newest is not None


# -- The response's own validation ------------------------------------------


def test_the_response_is_frozen(surface: _Surface, store: Any) -> None:
    row = surface.write(store, surface.keys[0], "2026-01-01T00:00:00+00:00")
    response = surface.response_cls(history=(row,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.history = ()  # type: ignore[misc]


def test_the_response_refuses_an_entry_of_the_wrong_type(surface: _Surface) -> None:
    with pytest.raises(GateEvidenceMetricError):
        surface.response_cls(history=("not a row",))


def test_the_response_refuses_a_non_sequence_history(surface: _Surface) -> None:
    with pytest.raises(GateEvidenceMetricError):
        surface.response_cls(history="not a sequence")  # type: ignore[arg-type]


def test_the_response_refuses_a_history_that_runs_backwards(
    surface: _Surface, store: Any
) -> None:
    newer = surface.write(store, surface.keys[0], "2026-02-01T00:00:00+00:00")
    older = surface.write(store, surface.keys[1], "2026-01-01T00:00:00+00:00")
    with pytest.raises(GateEvidenceMetricError) as caught:
        surface.response_cls(history=(newer, older))
    assert "backwards" in str(caught.value)


# -- The store seam -----------------------------------------------------------


def test_the_endpoint_refuses_a_carrier_that_cannot_read_history(
    surface: _Surface,
) -> None:
    with pytest.raises(TypeError) as caught:
        surface.endpoint_cls(object())
    assert "history()" in str(caught.value)


def test_a_failing_read_is_translated_not_answered_around(surface: _Surface) -> None:
    class Refusing:
        def history(self) -> object:
            raise surface.error_cls("the store's own words")

    endpoint = surface.endpoint_cls(Refusing())
    with pytest.raises(GateEvidenceMetricError) as caught:
        endpoint.get()
    assert surface.route in str(caught.value)
    assert isinstance(caught.value.__cause__, surface.error_cls)
    assert "the store's own words" in str(caught.value.__cause__)


def test_a_carrier_bug_is_not_dressed_up_as_a_store_failure(
    surface: _Surface,
) -> None:
    class Buggy:
        def history(self) -> object:
            raise ValueError("a bug, not a refusal")

    endpoint = surface.endpoint_cls(Buggy())
    with pytest.raises(ValueError, match="a bug, not a refusal"):
        endpoint.get()


def test_the_endpoint_exposes_the_store_it_was_built_with(
    surface: _Surface, store: Any, endpoint: Any
) -> None:
    assert endpoint.store is store


# -- from_env ------------------------------------------------------------------


def test_from_env_answers_none_without_a_url(
    surface: _Surface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert surface.endpoint_cls.from_env() is None


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_from_env_refuses_a_blank_url(
    surface: _Surface, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", value)
    assert surface.endpoint_cls.from_env() is None


def test_from_env_builds_over_the_url_without_touching_disk(
    surface: _Surface,
    store_url: str,
    store_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", store_url)
    endpoint = surface.endpoint_cls.from_env()
    assert endpoint is not None
    assert endpoint.store.database_url == store_url
    assert not store_path.exists()


def test_from_env_reads_a_mapping_it_is_handed(
    surface: _Surface, store_url: str
) -> None:
    endpoint = surface.endpoint_cls.from_env({"DATABASE_URL": store_url})
    assert endpoint is not None
    assert endpoint.store.database_url == store_url


def test_the_endpoint_built_by_from_env_reaches_the_real_store(
    surface: _Surface, store_url: str, store: Any
) -> None:
    endpoint = surface.endpoint_cls.from_env({"DATABASE_URL": store_url})
    assert endpoint is not None
    assert endpoint.get().history == ()
    written = surface.write(store, surface.keys[0], "2026-01-01T00:00:00+00:00")
    response = endpoint.get()
    assert response.history == (written,)
    assert response.newest == written


# -- No per-node null status anywhere -----------------------------------------


def test_no_response_type_can_carry_a_per_node_null_label() -> None:
    # These stores hold only aggregates (§4.2's sidecar key is granted to
    # exactly one process, and it is not this one).
    for record_type in (NullCalibration, TypeBDepth, DiscoveryRate, MetaOverfitGap):
        fields = set(record_type.__dataclass_fields__)
        assert "is_null" not in fields
        assert "node_id" not in fields
