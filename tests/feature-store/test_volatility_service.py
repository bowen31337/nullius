"""Feature 55 end to end: compute both metrics over a universe, persist them.

app_spec.xml feature 55: *System computes multi-horizon realized volatility
plus volatility-of-volatility, persisting each as a versioned regime
feature.*  This suite drives the whole feature through the service seam —
panel from bars + membership, market return series from panel, metrics from
the series, records from metrics — and through the application factory, so
feature 55 is verified as a composed component, not just as a set of
modules.

The membership is the universe's symbols: feature 55 never ranks liquidity
(feature 40 does), it is *given* the cross-section and computes how far the
market that formed it moved, at several horizons, and how unstable that
movement was.

The clauses this suite guards most closely are *multi-horizon* and *each*:
the persisted realized-volatility record carries several horizons at once,
the vol-of-vol is a record of its own (not a field of the first), and both
are stored under a version stamp the service refuses to contradict.
"""

import datetime as dt
import json
import math

import pytest
from feature_store.bars import DailyBar
from feature_store.store import FeatureStore
from feature_store.volatility import (
    ANNUALIZATION_PERIODS,
    DEFAULT_BASE_WINDOW,
    DEFAULT_HORIZONS,
    DEFAULT_VOL_WINDOW,
)
from feature_store.volatility_persistence import (
    FEATURE_NAME_REALIZED_VOL,
    FEATURE_NAME_VOL_OF_VOL,
    FEATURE_VERSION,
    VolatilityFeatureStore,
)
from feature_store.volatility_service import (
    VersionMismatchError,
    VolatilityService,
    build_volatility_service,
)

from app.module_loader import create_app, scan_components

SNAPSHOT = "c" * 64


def returns_path(count: int, *, amplitude: float = 0.02) -> list[float]:
    """A constant-magnitude, sign-flipping return path."""
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
    # The membership is the universe's symbols; the service computes how far
    # the market they average to moved, per day, at each horizon, and how
    # unstable that movement was.
    service = VolatilityService()
    series = {
        "AAAUSDT": levels(100.0, returns_path(130)),
        "BBBUSDT": levels(100.0, returns_path(130, amplitude=0.01)),
        "CCCUSDT": levels(100.0, returns_path(130, amplitude=0.03)),
    }
    metrics = service.compute(
        price_bars(series), symbols=list(series), dates=axis(130)
    )
    assert metrics.realized.horizons == DEFAULT_HORIZONS
    # All three members alternate with the same period, so the equal-weighted
    # market return alternates at the average amplitude 0.02: every horizon
    # reads 0.02 * sqrt(365).
    for horizon in DEFAULT_HORIZONS:
        assert metrics.realized.at(horizon) == pytest.approx(
            0.02 * math.sqrt(ANNUALIZATION_PERIODS)
        )
    # And the alternating market's vol is steady, so its instability is ~0.
    assert metrics.vol_of_vol.vol_of_vol == pytest.approx(0.0, abs=1e-9)
    assert metrics.vol_of_vol.n == DEFAULT_VOL_WINDOW


def test_compute_uses_the_membership_as_given() -> None:
    # A five-symbol universe is a market of five; a two-symbol one of two.
    # The service never invents or trims membership.
    service = VolatilityService()
    two = {
        "AAAUSDT": levels(100.0, returns_path(130)),
        "BBBUSDT": levels(100.0, returns_path(130, amplitude=0.01)),
    }
    metrics = service.compute(price_bars(two), symbols=list(two), dates=axis(130))
    # The mean amplitude of the alternating market is now 0.015.
    assert metrics.realized.at(10) == pytest.approx(
        0.015 * math.sqrt(ANNUALIZATION_PERIODS)
    )


def test_compute_reports_several_horizons_by_default() -> None:
    service = VolatilityService()
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    metrics = service.compute(
        price_bars(series), symbols=list(series), dates=axis(130)
    )
    assert len(metrics.realized.horizons) >= 2


def test_compute_accepts_overrides_for_this_call() -> None:
    # The keyword arguments override the service's defaults without rebuilding
    # it, so a caller can explore a different horizon set (persisting it,
    # however, is a definition change — see the version-mismatch tests below).
    service = VolatilityService()
    series = {"AAAUSDT": levels(100.0, returns_path(60))}
    metrics = service.compute(
        price_bars(series),
        symbols=list(series),
        dates=axis(60),
        horizons=(5,),
        base_window=5,
        vol_window=20,
    )
    assert metrics.realized.horizons == (5,)
    assert metrics.vol_of_vol.window == 20


# ---------------------------------------------------------------------------
# Persist through the service
# ---------------------------------------------------------------------------


def test_persist_stores_both_metrics_under_the_snapshot_hash() -> None:
    store = FeatureStore()
    service = VolatilityService(store=store)
    series = {
        "AAAUSDT": levels(100.0, returns_path(130)),
        "BBBUSDT": levels(100.0, returns_path(130, amplitude=0.01)),
    }
    metrics = service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(130),
        top_n=50,
    )
    volatility_store = VolatilityFeatureStore(store)
    assert volatility_store.load(SNAPSHOT) == metrics
    assert volatility_store.load_realized_volatility(SNAPSHOT) == metrics.realized
    assert volatility_store.load_vol_of_vol(SNAPSHOT) == metrics.vol_of_vol


def test_persisted_records_are_stamped_with_the_feature_version() -> None:
    # The feature's defining clause: what is persisted is versioned, and the
    # stamp is a segment of the record's address.
    store = FeatureStore()
    service = VolatilityService(store=store)
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(130),
        top_n=50,
    )
    assert len(store) == 2
    for key in store.keys():
        assert key.feature_version == FEATURE_VERSION
        assert key.snapshot_hash == SNAPSHOT
        assert key.feature_name in (
            FEATURE_NAME_REALIZED_VOL,
            FEATURE_NAME_VOL_OF_VOL,
        )
    # And the stamp is in the payload too, checkable without the key.
    for key in store.keys():
        assert json.loads(store.get(key).payload)["version"] == FEATURE_VERSION


def test_each_metric_is_persisted_as_its_own_record() -> None:
    # "Persisting each as a versioned regime feature": the realized
    # volatility and the vol-of-vol are two records under two names, never
    # two fields of one payload.
    store = FeatureStore()
    service = VolatilityService(store=store)
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(130),
        top_n=50,
    )
    names = {key.feature_name for key in store.keys()}
    assert names == {FEATURE_NAME_REALIZED_VOL, FEATURE_NAME_VOL_OF_VOL}


def test_persist_records_top_n_in_the_payload() -> None:
    # The universe size travels in each payload, so a reader knows what the
    # number is a fact over.
    store = FeatureStore()
    service = VolatilityService(store=store)
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(130),
        top_n=50,
    )
    volatility_store = VolatilityFeatureStore(store)
    record = store.get(volatility_store.vol_of_vol_key(SNAPSHOT))
    assert json.loads(record.payload)["top_n"] == 50


def test_persist_routes_at_an_explicit_store() -> None:
    # A caller can route the persist at a shared composed store without
    # rebuilding the service.
    shared = FeatureStore()
    service = VolatilityService(store=FeatureStore())  # its own default store
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(130),
        top_n=50,
        store=shared,
    )
    assert VolatilityFeatureStore(shared).load(SNAPSHOT) is not None
    assert VolatilityFeatureStore(service._store).load(SNAPSHOT) is None


def test_load_returns_none_for_an_unpersisted_snapshot() -> None:
    assert VolatilityService().load("d" * 64) is None


# ---------------------------------------------------------------------------
# The version stamp is not a fig leaf
# ---------------------------------------------------------------------------


def test_persist_refuses_horizons_that_contradict_the_stamp() -> None:
    # Computing with a different horizon set while stamping the version whose
    # definition names the default horizons would store numbers under an
    # address that promises something else — undetectable from the key alone.
    store = FeatureStore()
    service = VolatilityService(store=store)
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    with pytest.raises(VersionMismatchError, match="horizons"):
        service.persist(
            SNAPSHOT,
            price_bars(series),
            symbols=list(series),
            dates=axis(130),
            top_n=50,
            horizons=(10,),
        )
    # Nothing was written: a refused persist leaves no half-stamped record.
    assert len(store) == 0


def test_persist_refuses_a_contradictory_window() -> None:
    service = VolatilityService(store=FeatureStore())
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    with pytest.raises(VersionMismatchError, match="base_window"):
        service.persist(
            SNAPSHOT,
            price_bars(series),
            symbols=list(series),
            dates=axis(130),
            top_n=50,
            base_window=10,
        )


def test_persist_refuses_a_contradictory_vol_window() -> None:
    service = VolatilityService(store=FeatureStore())
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    with pytest.raises(VersionMismatchError, match="vol_window"):
        service.persist(
            SNAPSHOT,
            price_bars(series),
            symbols=list(series),
            dates=axis(130),
            top_n=50,
            vol_window=30,
        )


def test_persist_refuses_a_contradictory_annualization() -> None:
    service = VolatilityService(store=FeatureStore())
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    with pytest.raises(VersionMismatchError, match="annualization"):
        service.persist(
            SNAPSHOT,
            price_bars(series),
            symbols=list(series),
            dates=axis(130),
            top_n=50,
            annualization=252.0,
        )


def test_persist_accepts_the_version_1_definition_spelled_out() -> None:
    # Passing the definition's own values explicitly is the same computation,
    # so it stamps cleanly — the check is on the values, not on whether a
    # keyword was used.
    service = VolatilityService(store=FeatureStore())
    series = {"AAAUSDT": levels(100.0, returns_path(130))}
    metrics = service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(130),
        top_n=50,
        horizons=DEFAULT_HORIZONS,
        base_window=DEFAULT_BASE_WINDOW,
        vol_window=DEFAULT_VOL_WINDOW,
        annualization=ANNUALIZATION_PERIODS,
    )
    assert metrics.realized.horizons == tuple(DEFAULT_HORIZONS)
    assert metrics.vol_of_vol.base_window == DEFAULT_BASE_WINDOW


# ---------------------------------------------------------------------------
# Composition through the application factory
# ---------------------------------------------------------------------------


def test_workspace_scan_registers_the_volatility_metrics_component() -> None:
    names = [component.name for component in scan_components()]
    assert "volatility-metrics" in names
    assert "feature-store" in names


def test_create_app_composes_the_volatility_service() -> None:
    app = create_app()
    service = app.get("volatility-metrics")
    assert service is not None
    assert type(service).__qualname__ == "VolatilityService"
    assert type(service).__module__.endswith("feature_store.volatility_service")
    assert "volatility-metrics" in app.order


def test_volatility_service_persists_into_a_routed_store() -> None:
    # The factory's one-way contract means a zero-arg builder cannot reach the
    # composed feature-store component, so the service owns a fresh store by
    # default.  A caller that must share the composed store routes it
    # explicitly — duck-typed, so the scan-alias module world does not matter.
    app = create_app()
    service = app.get("volatility-metrics")
    composed_store = app.get("feature-store")
    series = {
        "AAAUSDT": levels(100.0, returns_path(130)),
        "BBBUSDT": levels(100.0, returns_path(130, amplitude=0.01)),
    }
    metrics = service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(130),
        top_n=50,
        store=composed_store,
    )
    assert service.load(SNAPSHOT, store=composed_store) == metrics


def test_builder_is_zero_argument_and_composable() -> None:
    # The factory's one-way contract: the builder takes nothing and builds a
    # service.  It is also not the registered name in the package namespace —
    # the registration rebinds that spelling — so this pins the original.
    service = build_volatility_service()
    assert isinstance(service, VolatilityService)
    assert type(service).__qualname__ == "VolatilityService"


def test_registered_builder_does_not_recurse() -> None:
    # The member's @register("volatility-metrics") builder shares its name
    # with this module's builder after the package __init__ rebinds it;
    # calling the registered one must still construct rather than call itself.
    component = next(
        component
        for component in scan_components()
        if component.name == "volatility-metrics"
    )
    service = component.builder()
    assert type(service).__qualname__ == "VolatilityService"


def test_the_package_namespace_keeps_the_two_features_apart() -> None:
    # The member's package namespace exports dispersion's VersionMismatchError
    # under its bare name (feature 56 claimed the spelling first) and
    # volatility's under its own — so a caller cannot confuse which feature's
    # stamp a mismatch is about.
    import feature_store

    from feature_store import volatility_service

    assert feature_store.VolatilityVersionMismatchError is (
        volatility_service.VersionMismatchError
    )
    assert issubclass(feature_store.VolatilityVersionMismatchError, ValueError)
