"""Acceptance tests for the component registration and service facade.

The factory's one-way contract, exercised end to end: the package opts in
by registering a zero-argument builder; the factory discovers it by
scanning the declared workspace — no central file names this package —
and composes the builder's result into the application. A fresh
:class:`Registration` per test keeps the process-wide registry out of the
assertions.
"""

import datetime as dt
import inspect
from pathlib import Path

import pytest

from app.module_loader import Application, Registration, create_app, scan_components
from universe import (
    DailyBar,
    PriceBar,
    UniverseConfig,
    UniverseService,
    build_universe_service,
)

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"

APRIL_1 = dt.date(2026, 4, 1)
MAY_1 = dt.date(2026, 5, 1)


def april_bars() -> list[DailyBar]:
    return [
        DailyBar("AAAUSDT", APRIL_1 + dt.timedelta(days=offset), 100.0)
        for offset in range(30)
    ]


def march_through_april_bars() -> list[DailyBar]:
    start = dt.date(2026, 3, 1)
    end = dt.date(2026, 4, 30)
    return [
        DailyBar("AAAUSDT", start + dt.timedelta(days=offset), 100.0)
        for offset in range((end - start).days + 1)
    ]


class TestFactoryRegistration:
    def test_scan_discovers_the_universe_component(self) -> None:
        registry = Registration()
        components = scan_components(str(PACKAGE_SRC), registry=registry)
        assert "universe" in [component.name for component in components]

    def test_registered_builder_takes_no_arguments(self) -> None:
        registry = Registration()
        (component,) = [
            c for c in scan_components(str(PACKAGE_SRC), registry=registry) if c.name == "universe"
        ]
        signature = inspect.signature(component.builder)
        assert all(
            parameter.default is not inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )

    def test_create_app_composes_the_service(self, test_database_url: str) -> None:
        app = create_app(str(PACKAGE_SRC), registry=Registration())
        assert isinstance(app, Application)
        service = app.get("universe")
        # The loader imports scanned packages under its own mangled module
        # name, so the composed service is the scanned copy's class — a
        # sibling of the one imported here as `universe`. Assert on the
        # observable contract, not on cross-copy isinstance.
        assert type(service).__qualname__ == "UniverseService"
        assert service.config.top_n == 100
        assert service.config.window_days == 30
        assert service.config.min_observations == 1
        assert service.config.min_dollar_volume == 0.0
        assert service.database_url == test_database_url

    def test_default_roots_follow_the_declared_workspace(self) -> None:
        # No explicit roots: the factory scans what the root pyproject
        # declares, which is how this member is discovered in production.
        app = create_app(registry=Registration())
        assert "universe" in app


class TestServiceFromEnv:
    def test_from_env_applies_spec_defaults(self, test_database_url: str) -> None:
        service = UniverseService.from_env()
        assert service.config == UniverseConfig()
        assert service.database_url == test_database_url

    def test_from_env_honors_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NULLIUS_UNIVERSE_TOP_N", "7")
        monkeypatch.setenv("NULLIUS_UNIVERSE_WINDOW_DAYS", "60")
        monkeypatch.setenv("NULLIUS_UNIVERSE_MIN_OBSERVATIONS", "10")
        monkeypatch.setenv("NULLIUS_UNIVERSE_MIN_DOLLAR_VOLUME", "25000")
        assert UniverseService.from_env().config == UniverseConfig(
            top_n=7, window_days=60, min_observations=10, min_dollar_volume=25_000.0
        )

    def test_from_env_rejects_a_bad_floor_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NULLIUS_UNIVERSE_MIN_DOLLAR_VOLUME", "ten thousand")
        with pytest.raises(ValueError, match="NULLIUS_UNIVERSE_MIN_DOLLAR_VOLUME"):
            UniverseService.from_env()

    def test_from_env_rejects_a_non_finite_floor_via_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # float("nan") parses, but a NaN floor must still fail the build:
        # the env parser delegates finiteness to the config's validation.
        monkeypatch.setenv("NULLIUS_UNIVERSE_MIN_DOLLAR_VOLUME", "nan")
        with pytest.raises(ValueError, match="min_dollar_volume"):
            UniverseService.from_env()

    def test_from_env_rejects_a_bad_override_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NULLIUS_UNIVERSE_TOP_N", "hundred")
        with pytest.raises(ValueError, match="NULLIUS_UNIVERSE_TOP_N"):
            UniverseService.from_env()

    def test_named_builder_builds_a_service(self) -> None:
        assert isinstance(build_universe_service(), UniverseService)


class TestServiceEndToEnd:
    def test_build_persist_load_through_the_service(
        self, test_database_url: str
    ) -> None:
        service = UniverseService(config=UniverseConfig(top_n=1))
        universe = service.build(april_bars(), "2026-05")
        assert service.persist(universe) == 1
        assert service.load("2026-05") == universe
        assert universe.symbols == ("AAAUSDT",)

    def test_service_sweep_persists_each_month(self, test_database_url: str) -> None:
        service = UniverseService(config=UniverseConfig(top_n=5))
        result = service.build_all(march_through_april_bars())
        # The sweep covers months that contain bars, so it ends at April
        # (May holds no data and is not invented); March is skipped — its
        # February window is empty. April builds and persists.
        assert [universe.month for universe in result.builds] == ["2026-04"]
        assert [skip.month for skip in result.skipped] == ["2026-03"]
        for universe in result.builds:
            service.persist(universe)
        for universe in result.builds:
            assert service.load(universe.month) == universe

    def test_floor_flows_build_persist_load_through_the_service(
        self, test_database_url: str
    ) -> None:
        # The configured floor is the operator's whole interface to
        # feature 47: set it on the service and the exclusion travels with
        # the build into the store and back, reason intact.
        service = UniverseService(
            config=UniverseConfig(top_n=5, min_dollar_volume=50.0)
        )
        bars = april_bars() + [
            DailyBar("BBBUSDT", APRIL_1 + dt.timedelta(days=offset), 5.0)
            for offset in range(30)
        ]
        universe = service.build(bars, "2026-05")
        assert universe.symbols == ("AAAUSDT",)
        assert universe.excluded_symbols == ("BBBUSDT",)
        assert service.persist(universe) == 1
        loaded = service.load("2026-05")
        assert loaded == universe
        assert loaded is not None
        assert "falls below the configured floor of 50.0" in loaded.exclusions[0].reason


class TestResolveAsOfDecisionTime:
    """Feature 43's resolution: membership as of a decision time, not now."""

    def _service(self, url: str) -> UniverseService:
        return UniverseService(config=UniverseConfig(top_n=1), database_url=url)

    def _scenario(self, service: UniverseService) -> None:
        # April: BBB outranks AAA, so BBB is the sole member. May: AAA
        # outranks BBB, so AAA is admitted and BBB's interval closes on May 1.
        service.persist(service.build(_two_symbol_april(), "2026-04"))
        service.persist(service.build(_two_symbol_may(), "2026-05"))

    def test_resolve_returns_the_member_during_its_interval(
        self, test_database_url: str
    ) -> None:
        service = self._service(test_database_url)
        self._scenario(service)
        # Mid-April: BBB is the member.
        assert service.resolve(dt.date(2026, 4, 15)) == ("BBBUSDT",)

    def test_resolve_excludes_a_symbol_after_it_leaves(
        self, test_database_url: str
    ) -> None:
        service = self._service(test_database_url)
        self._scenario(service)
        # Mid-May: BBB has left; AAA is the member.
        assert service.resolve(dt.date(2026, 5, 15)) == ("AAAUSDT",)

    def test_resolve_before_any_membership_is_empty(
        self, test_database_url: str
    ) -> None:
        service = self._service(test_database_url)
        self._scenario(service)
        assert service.resolve(dt.date(2026, 1, 1)) == ()

    def test_resolve_accepts_an_iso_string(self, test_database_url: str) -> None:
        service = self._service(test_database_url)
        self._scenario(service)
        assert service.resolve("2026-04-15") == ("BBBUSDT",)

    def test_resolve_is_sorted(self, test_database_url: str) -> None:
        # Two symbols both admitted across both months resolve together, sorted.
        service = UniverseService(
            config=UniverseConfig(top_n=5), database_url=test_database_url
        )
        service.persist(service.build(_two_symbol_april(), "2026-04"))
        service.persist(service.build(_two_symbol_may(), "2026-05"))
        assert service.resolve(dt.date(2026, 4, 15)) == ("AAAUSDT", "BBBUSDT")


class TestPriceHistoryAndAuditFacade:
    """Feature 43/44 through the service: ingest prices and audit windows."""

    def _service(self, url: str) -> UniverseService:
        return UniverseService(config=UniverseConfig(top_n=1), database_url=url)

    def test_ingest_prices_persists_and_audits(
        self, test_database_url: str
    ) -> None:
        service = self._service(test_database_url)
        service.persist(service.build(_two_symbol_april(), "2026-04"))
        service.persist(service.build(_two_symbol_may(), "2026-05"))
        count = service.ingest_prices(
            [PriceBar("BBBUSDT", APRIL_1 + dt.timedelta(days=offset), 20.0) for offset in range(30)]
        )
        assert count == 30
        # BBB won April, lost May — a delisting — and has April closes, so the
        # May window (April 1–30) reports it.
        audits = service.survivorship_audit()
        may = [a for a in audits if a.month == "2026-05"]
        assert len(may) == 1
        assert may[0].delisted_present == ("BBBUSDT",)

    def test_price_history_window_query_through_the_service(
        self, test_database_url: str
    ) -> None:
        service = self._service(test_database_url)
        service.ingest_prices([PriceBar("BBBUSDT", APRIL_1, 20.0), PriceBar("AAAUSDT", APRIL_1, 10.0)])
        assert service.price_history.symbols_in_window(
            dt.date(2026, 4, 1), dt.date(2026, 4, 1)
        ) == ("AAAUSDT", "BBBUSDT")

    def test_render_report_through_the_service(
        self, test_database_url: str
    ) -> None:
        service = self._service(test_database_url)
        service.persist(service.build(_two_symbol_april(), "2026-04"))
        service.persist(service.build(_two_symbol_may(), "2026-05"))
        service.ingest_prices(
            [PriceBar("BBBUSDT", APRIL_1 + dt.timedelta(days=offset), 20.0) for offset in range(30)]
        )
        (line,) = service.render_survivorship_report(months=["2026-05"])
        assert line == "2026-05 [2026-04-01, 2026-04-30] delisted=1: BBBUSDT"


def _two_symbol_april() -> list[DailyBar]:
    # April's trailing window is March 2–31; BBB (100) outranks AAA (50) there,
    # so top_n=1 admits BBB.
    march_2 = dt.date(2026, 3, 2)
    return [
        DailyBar("BBBUSDT", march_2 + dt.timedelta(days=offset), 100.0)
        for offset in range(30)
    ] + [
        DailyBar("AAAUSDT", march_2 + dt.timedelta(days=offset), 50.0)
        for offset in range(30)
    ]


def _two_symbol_may() -> list[DailyBar]:
    # May's trailing window is April 1–30; AAA (100) now outranks BBB (50).
    return [
        DailyBar("AAAUSDT", APRIL_1 + dt.timedelta(days=offset), 100.0)
        for offset in range(30)
    ] + [
        DailyBar("BBBUSDT", APRIL_1 + dt.timedelta(days=offset), 50.0)
        for offset in range(30)
    ]
