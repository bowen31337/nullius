"""Feature 56 end to end: compute both metrics over a universe, persist them.

app_spec.xml feature 56: *System computes cross-sectional return dispersion
plus return autocorrelation at several lags, persisting them with
feature_version stamps.*  This suite drives the whole feature through the
service seam — panel from bars + membership, metrics from panel, records from
metrics — and through the application factory, so feature 56 is verified as a
composed component, not just as a set of modules.

The membership is the universe's symbols: feature 56 never ranks liquidity
(feature 40 does), it is *given* the cross-section and computes how wide it
was and how much memory the market that formed it carried.

The clause this suite guards most closely is the *version stamp*: a stored
record's version is part of its address, and the service refuses to store a
computation whose parameters contradict the definition the stamp names.
"""

import datetime as dt
import json
import math

import pytest
from feature_store.bars import DailyBar
from feature_store.dispersion_persistence import (
    FEATURE_NAME_AUTOCORRELATION,
    FEATURE_NAME_DISPERSION,
    FEATURE_VERSION,
    DispersionFeatureStore,
)
from feature_store.dispersion_service import (
    DispersionService,
    VersionMismatchError,
    build_dispersion_service,
)
from feature_store.store import FeatureStore

from app.module_loader import create_app, scan_components

SNAPSHOT = "c" * 64


def returns_path(count: int, *, amplitude: float = 0.02) -> list[float]:
    """A strongly alternating return path — clearly autocorrelated at lag 1."""
    return [amplitude if index % 2 == 0 else -amplitude for index in range(count)]


def levels(initial: float, step_returns: list[float]) -> list[float]:
    """Price levels from log returns, one price per arrival."""
    out = [initial]
    for step in step_returns:
        out.append(out[-1] * math.exp(step))
    return out


def price_bars(
    series: dict[str, list[float]], first: dt.date = dt.date(2026, 1, 1)
) -> list[DailyBar]:
    count = len(next(iter(series.values())))
    dates = [first + dt.timedelta(days=offset) for offset in range(count)]
    return [
        DailyBar(symbol, dates[i], values[i])
        for symbol, values in series.items()
        for i in range(len(values))
    ]


def axis(count: int, first: dt.date = dt.date(2026, 1, 1)) -> list[dt.date]:
    return [first + dt.timedelta(days=offset) for offset in range(count)]


# ---------------------------------------------------------------------------
# Computation through the service
# ---------------------------------------------------------------------------


def test_compute_over_a_universe_membership() -> None:
    # The membership is the universe's symbols; the service computes how wide
    # that cross-section's latest returns were and how much memory the market
    # they form carries.
    service = DispersionService()
    series = {
        "AAAUSDT": levels(100.0, returns_path(60)),
        "BBBUSDT": levels(100.0, returns_path(60, amplitude=0.01)),
        "CCCUSDT": levels(100.0, returns_path(60, amplitude=0.03)),
    }
    metrics = service.compute(
        price_bars(series), symbols=list(series), dates=axis(60)
    )
    assert metrics.dispersion.n == 3
    assert metrics.dispersion.dispersion > 0.0
    # All three carry the same alternating pattern, so the market return they
    # average to alternates too: lag 1 is strongly negative.
    assert metrics.autocorrelation.at(1) < -0.5


def test_compute_uses_the_membership_as_given() -> None:
    # A five-symbol universe is a cross-section of five; a two-symbol one of
    # two.  The service never invents or trims membership.
    service = DispersionService()
    two = {
        "AAAUSDT": levels(100.0, returns_path(60)),
        "BBBUSDT": levels(100.0, returns_path(60, amplitude=0.01)),
    }
    metrics = service.compute(price_bars(two), symbols=list(two), dates=axis(60))
    assert metrics.dispersion.n == 2


def test_compute_reports_several_lags_by_default() -> None:
    service = DispersionService()
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    metrics = service.compute(
        price_bars(series), symbols=list(series), dates=axis(60)
    )
    assert len(metrics.autocorrelation.lags) >= 2


def test_compute_accepts_overrides_for_this_call() -> None:
    # The keyword arguments override the service's defaults without rebuilding
    # it, so a caller can explore a different lag set (persisting it, however,
    # is a definition change — see the version-mismatch tests below).
    service = DispersionService()
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    metrics = service.compute(
        price_bars(series),
        symbols=list(series),
        dates=axis(60),
        lags=(1,),
        min_observations=5,
    )
    assert metrics.autocorrelation.lags == (1,)


# ---------------------------------------------------------------------------
# Persist through the service
# ---------------------------------------------------------------------------


def test_persist_stores_both_metrics_under_the_snapshot_hash() -> None:
    store = FeatureStore()
    service = DispersionService(store=store)
    series = {
        "AAAUSDT": levels(100.0, returns_path(60)),
        "BBBUSDT": levels(100.0, returns_path(60, amplitude=0.01)),
    }
    metrics = service.persist(
        SNAPSHOT, price_bars(series), symbols=list(series), dates=axis(60), top_n=50
    )
    dispersion_store = DispersionFeatureStore(store)
    assert dispersion_store.load(SNAPSHOT) == metrics
    assert dispersion_store.load_dispersion(SNAPSHOT) == metrics.dispersion
    assert (
        dispersion_store.load_autocorrelation(SNAPSHOT)
        == metrics.autocorrelation
    )


def test_persisted_records_are_stamped_with_the_feature_version() -> None:
    # The feature's defining clause: what is persisted carries a version stamp,
    # and the stamp is a segment of the record's address.
    store = FeatureStore()
    service = DispersionService(store=store)
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(60),
        top_n=50,
    )
    assert len(store) == 2
    for key in store.keys():
        assert key.feature_version == FEATURE_VERSION
        assert key.snapshot_hash == SNAPSHOT
        assert key.feature_name in (
            FEATURE_NAME_DISPERSION,
            FEATURE_NAME_AUTOCORRELATION,
        )
    # And the stamp is in the payload too, checkable without the key.
    for key in store.keys():
        assert json.loads(store.get(key).payload)["version"] == FEATURE_VERSION


def test_persist_records_top_n_in_the_payload() -> None:
    # The universe size travels in each payload, so a reader knows what the
    # number is a fact over.
    store = FeatureStore()
    service = DispersionService(store=store)
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(60),
        top_n=50,
    )
    dispersion_store = DispersionFeatureStore(store)
    record = store.get(dispersion_store.dispersion_key(SNAPSHOT))
    assert json.loads(record.payload)["top_n"] == 50


def test_persist_routes_at_an_explicit_store() -> None:
    # A caller can route the persist at a shared composed store without
    # rebuilding the service.
    shared = FeatureStore()
    service = DispersionService(store=FeatureStore())  # its own default store
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(60),
        top_n=50,
        store=shared,
    )
    assert DispersionFeatureStore(shared).load(SNAPSHOT) is not None
    assert DispersionFeatureStore(service._store).load(SNAPSHOT) is None


def test_load_returns_none_for_an_unpersisted_snapshot() -> None:
    assert DispersionService().load("d" * 64) is None


# ---------------------------------------------------------------------------
# The version stamp is not a fig leaf
# ---------------------------------------------------------------------------


def test_persist_refuses_parameters_that_contradict_the_stamp() -> None:
    # Computing with a different lag set while stamping the version whose
    # definition names the default lags would store numbers under an address
    # that promises something else — undetectable from the key alone.
    store = FeatureStore()
    service = DispersionService(store=store)
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    with pytest.raises(VersionMismatchError, match="lags"):
        service.persist(
            SNAPSHOT,
            price_bars(series),
            symbols=list(series),
            dates=axis(60),
            top_n=50,
            lags=(1,),
        )
    # Nothing was written: a refused persist leaves no half-stamped record.
    assert len(store) == 0


def test_persist_refuses_a_contradictory_floor() -> None:
    service = DispersionService(store=FeatureStore())
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    with pytest.raises(VersionMismatchError, match="min_observations"):
        service.persist(
            SNAPSHOT,
            price_bars(series),
            symbols=list(series),
            dates=axis(60),
            top_n=50,
            min_observations=3,
        )


def test_persist_accepts_the_version_1_definition_spelled_out() -> None:
    # Passing the definition's own values explicitly is the same computation,
    # so it stamps cleanly — the check is on the values, not on whether a
    # keyword was used.
    from feature_store.dispersion import DEFAULT_LAGS, DEFAULT_MIN_OBSERVATIONS

    service = DispersionService(store=FeatureStore())
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    metrics = service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(60),
        top_n=50,
        lags=DEFAULT_LAGS,
        min_observations=DEFAULT_MIN_OBSERVATIONS,
    )
    assert metrics.autocorrelation.lags == tuple(DEFAULT_LAGS)


# ---------------------------------------------------------------------------
# Composition through the application factory
# ---------------------------------------------------------------------------


def test_workspace_scan_registers_the_dispersion_metrics_component() -> None:
    names = [component.name for component in scan_components()]
    assert "dispersion-metrics" in names
    assert "feature-store" in names


def test_create_app_composes_the_dispersion_service() -> None:
    app = create_app()
    service = app.get("dispersion-metrics")
    assert service is not None
    assert type(service).__qualname__ == "DispersionService"
    assert type(service).__module__.endswith("feature_store.dispersion_service")
    assert "dispersion-metrics" in app.order


def test_dispersion_service_persists_into_a_routed_store() -> None:
    # The factory's one-way contract means a zero-arg builder cannot reach the
    # composed feature-store component, so the service owns a fresh store by
    # default.  A caller that must share the composed store routes it
    # explicitly — duck-typed, so the scan-alias module world does not matter.
    app = create_app()
    service = app.get("dispersion-metrics")
    composed_store = app.get("feature-store")
    series = {
        "AAAUSDT": levels(100.0, returns_path(60)),
        "BBBUSDT": levels(100.0, returns_path(60, amplitude=0.01)),
    }
    metrics = service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(60),
        top_n=50,
        store=composed_store,
    )
    assert service.load(SNAPSHOT, store=composed_store) == metrics


def test_builder_is_zero_argument_and_composable() -> None:
    # The factory's one-way contract: the builder takes nothing and builds a
    # service.  It is also not the registered name in the package namespace —
    # the registration rebinds that spelling — so this pins the original.
    service = build_dispersion_service()
    assert isinstance(service, DispersionService)
    assert type(service).__qualname__ == "DispersionService"


def test_registered_builder_does_not_recurse() -> None:
    # The member's @register("dispersion-metrics") builder shares its name with
    # this module's builder after the package __init__ rebinds it; calling the
    # registered one must still construct rather than call itself.
    component = next(
        component
        for component in scan_components()
        if component.name == "dispersion-metrics"
    )
    service = component.builder()
    assert type(service).__qualname__ == "DispersionService"
