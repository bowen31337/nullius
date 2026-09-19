"""Feature 57 end to end: compute the two metrics over a universe, persist both.

app_spec.xml feature 57: *System computes mean pairwise correlation of the
top 50 symbols plus breadth above an N-day moving average, persisting both.*
This suite drives the whole feature through the service seam — panel from
bars + membership, metrics from panel, records from metrics — and through the
application factory, so feature 57 is verified as a composed component, not
just as a set of modules.

The membership is the universe's symbols: feature 57 never ranks liquidity
(feature 40 does), it is *given* the top-N, and it computes what the market
did across exactly those symbols over the snapshot's daily bars.
"""

import datetime as dt
import json
import math

import pytest

from app.module_loader import create_app, scan_components
from feature_store.bars import DailyBar
from feature_store.persistence import (
    FEATURE_NAME_BREADTH,
    FEATURE_NAME_CORRELATION,
    RegimeFeatureStore,
)
from feature_store.regime import build_regime_metrics
from feature_store.service import RegimeService, build_regime_service
from feature_store.store import FeatureStore

SNAPSHOT = "c" * 64


def rising(count: int, *, start: float = 100.0, drift: float = 0.01) -> list[float]:
    return [start * math.exp(drift * offset) for offset in range(count)]


def falling(count: int, *, start: float = 200.0, drift: float = 0.01) -> list[float]:
    return [start * math.exp(-drift * offset) for offset in range(count)]


def price_bars(
    series: dict[str, list[float]], first: dt.date = dt.date(2026, 1, 1)
) -> list[DailyBar]:
    dates = [first + dt.timedelta(days=offset) for offset in range(len(next(iter(series.values()))))]
    return [
        DailyBar(symbol, dates[i], levels[i])
        for symbol, levels in series.items()
        for i in range(len(levels))
    ]


# ---------------------------------------------------------------------------
# Computation through the service
# ---------------------------------------------------------------------------


def test_compute_over_a_universe_membership() -> None:
    # The membership is the universe's symbols; the service computes what the
    # market did across exactly those symbols over the daily bars.
    service = RegimeService()
    bars = price_bars(
        {
            "AAAUSDT": rising(60),
            "BBBUSDT": rising(60),
            "CCCUSDT": rising(60),
            "DDDUSDT": falling(60),
        }
    )
    metrics = service.compute(
        bars,
        symbols=["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"],
        dates=[dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(60)],
    )
    # Three rising, one falling: breadth counts the three rising above their
    # own average.
    assert metrics.breadth.above == 3
    assert metrics.breadth.total == 4
    assert metrics.correlation.pairs == 6  # 4 choose 2


def test_compute_uses_the_membership_as_given() -> None:
    # A five-symbol universe is scored over five symbols; a three-symbol one
    # over three.  The service never invents or trims membership — "the top
    # 50" is whatever the caller passes.
    service = RegimeService()
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(60)]
    three = service.compute(
        price_bars({"AUSDT": rising(60), "BUSDT": rising(60), "CUSDT": rising(60)}),
        symbols=["AUSDT", "BUSDT", "CUSDT"],
        dates=dates,
    )
    assert three.correlation.pairs == 3


# ---------------------------------------------------------------------------
# Persist through the service
# ---------------------------------------------------------------------------


def test_persist_stores_both_metrics_under_the_snapshot_hash() -> None:
    store = FeatureStore()
    service = RegimeService(store=store)
    bars = price_bars({"AUSDT": rising(60), "BUSDT": rising(60), "CUSDT": falling(60)})
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(60)]
    metrics = service.persist(
        SNAPSHOT, bars, symbols=["AUSDT", "BUSDT", "CUSDT"], dates=dates, top_n=50
    )
    # The metrics travel through the store under the market-wide daily keys.
    regime_store = RegimeFeatureStore(store)
    assert regime_store.load(SNAPSHOT) == metrics
    assert regime_store.load_correlation(SNAPSHOT) == metrics.correlation
    assert regime_store.load_breadth(SNAPSHOT) == metrics.breadth


def test_persist_records_top_n_in_the_payload() -> None:
    # The top-N (how many universe members the metrics were computed over)
    # travels in each persisted payload, so a reader knows the sample size.
    store = FeatureStore()
    service = RegimeService(store=store)
    bars = price_bars({"AUSDT": rising(60), "BUSDT": rising(60)})
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(60)]
    service.persist(SNAPSHOT, bars, symbols=["AUSDT", "BUSDT"], dates=dates, top_n=50)
    correlation_record = store.get(RegimeFeatureStore(store).correlation_key(SNAPSHOT))
    payload = json.loads(correlation_record.payload)
    assert payload["top_n"] == 50


def test_persist_routes_at_an_explicit_store() -> None:
    # A caller can route the persist at a shared composed store without
    # rebuilding the service.
    shared = FeatureStore()
    service = RegimeService(store=FeatureStore())  # its own default store
    bars = price_bars({"AUSDT": rising(60), "BUSDT": rising(60)})
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(60)]
    service.persist(
        SNAPSHOT, bars, symbols=["AUSDT", "BUSDT"], dates=dates, top_n=50, store=shared
    )
    assert RegimeFeatureStore(shared).load(SNAPSHOT) is not None
    # Nothing leaked into the service's own default store.
    assert RegimeFeatureStore(service._store).load(SNAPSHOT) is None


def test_load_returns_none_for_an_unpersisted_snapshot() -> None:
    # A snapshot hash that was never persisted is a normal point-in-time miss.
    service = RegimeService()
    assert service.load("d" * 64) is None


# ---------------------------------------------------------------------------
# Composition through the application factory
# ---------------------------------------------------------------------------


def test_workspace_scan_registers_the_regime_metrics_component() -> None:
    components = scan_components()
    names = [component.name for component in components]
    assert "regime-metrics" in names
    assert "feature-store" in names


def test_create_app_composes_the_regime_service() -> None:
    app = create_app()
    service = app.get("regime-metrics")
    assert service is not None
    assert type(service).__qualname__ == "RegimeService"
    assert type(service).__module__.endswith("feature_store.service")
    assert "regime-metrics" in app.order


def test_regime_service_persists_into_a_routed_store() -> None:
    # The factory's one-way contract means a zero-arg builder cannot reach the
    # composed feature-store component, so the service owns a fresh store by
    # default (like the universe service owns its DB via env). A caller that
    # must share the composed store routes it explicitly — here the composed
    # feature-store component, duck-typed so the scan-alias module world does
    # not matter.  The pair is read back through the service itself, which
    # lives in the same scanned module world as the composed store (the
    # framework's two module worlds are never bridged by isinstance).
    app = create_app()
    service = app.get("regime-metrics")
    composed_store = app.get("feature-store")
    bars = price_bars({"AUSDT": rising(60), "BUSDT": rising(60), "CUSDT": falling(60)})
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(60)]
    metrics = service.persist(
        SNAPSHOT,
        bars,
        symbols=["AUSDT", "BUSDT", "CUSDT"],
        dates=dates,
        top_n=50,
        store=composed_store,
    )
    assert service.load(SNAPSHOT, store=composed_store) == metrics


def test_builder_is_zero_argument_and_composable() -> None:
    # The factory's one-way contract: the builder takes nothing and builds a
    # service.
    service = build_regime_service()
    assert isinstance(service, RegimeService)
