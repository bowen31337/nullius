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
