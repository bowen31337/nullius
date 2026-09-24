"""The two seams: composition via the loader, and the app seat.

Mirrors ``packages/regime/tests/test_component.py``: the factory's scan
composes the store under the member's registered name, and
``app.modules.router`` answers *what is the composed exchangeInfo version
store?* for a caller that holds the app namespace.  ``router`` carries no
hyphen, so both the member and the seat are plain dotted imports — no
``importlib.import_module`` trick needed (unlike the ``cost-model`` seat).
"""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from datetime import UTC
from pathlib import Path

import pytest
import router as member

from app.module_loader import Application, Registration, create_app, scan_components
from app.modules import router as seat
from app.modules.router import COMPONENT_NAME as SEAT_COMPONENT_NAME
from app.modules.router import router_exchange_info_component

EXPECTED_EXPORTS = {"COMPONENT_NAME", "router_exchange_info_component"}

NOT_THE_SEATS_BUSINESS = (
    "RouterExchangeInfoVersion",
    "RouterSymbolFilters",
    "resolve_router_filters",
    "RouterError",
    "RouterFilterError",
    "RouterStoreError",
)


def _assert_is_the_exchange_info_store(component: object) -> None:
    assert type(component).__name__ == "RouterExchangeInfoStore"
    assert type(component).__module__.endswith("router.store")
    for method in ("record", "current", "version", "filters_for"):
        assert callable(getattr(component, method)), method
    assert component.database_url is not None


# -- The registration ---------------------------------------------------------


def test_the_member_registers_under_its_own_name() -> None:
    assert member.COMPONENT_NAME == SEAT_COMPONENT_NAME == "router"


def test_the_member_exports_exactly_one_builder() -> None:
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_router_exchange_info_store"
    ]


def test_the_scanned_application_carries_the_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.COMPONENT_NAME in app
    assert member.COMPONENT_NAME in app.order
    _assert_is_the_exchange_info_store(app.get(member.COMPONENT_NAME))


def test_the_component_survives_a_second_composition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The submodule-registration hazard: the loader caches imported
    # submodules, so a @register in one fires on the first composition and
    # silently drops out of every later one — the reason the builder lives
    # in __init__.py.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    for app in (create_app(), create_app(), create_app()):
        _assert_is_the_exchange_info_store(app.get(member.COMPONENT_NAME))
        assert member.COMPONENT_NAME in app.order


def test_the_builder_degrades_to_none_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert create_app().get(member.COMPONENT_NAME) is None


def test_an_empty_database_url_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert create_app().get(member.COMPONENT_NAME) is None


def test_the_builder_never_raises_and_takes_no_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert list(inspect.signature(member.build_router_exchange_info_store).parameters) == []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert member.build_router_exchange_info_store() is None
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'built.db'}")
    assert isinstance(
        member.build_router_exchange_info_store(), member.RouterExchangeInfoStore
    )


def test_scanning_registers_the_component_exactly_once() -> None:
    registry = Registration()
    scan_components(registry=registry)
    named = [
        component
        for component in registry.components()
        if component.name == member.COMPONENT_NAME
    ]
    assert len(named) == 1


# -- On demand ------------------------------------------------------------------


def test_composing_writes_nothing_and_persisting_is_on_demand(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exchange_info_document: dict
) -> None:
    from datetime import datetime

    database = tmp_path / "on-demand.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    app = create_app()
    assert not database.exists()  # composing wrote nothing
    store = app.get(member.COMPONENT_NAME)
    assert store is not None
    assert not database.exists()  # asking for the component neither
    store.record(exchange_info_document, fetched_at=datetime.now(UTC))
    assert database.exists()  # the demand is what wrote
    with closing(sqlite3.connect(database)) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM router_exchange_info_version"
        ).fetchone()
    assert count[0] == 1


# -- The seat ---------------------------------------------------------------------


def test_the_seat_exposes_nothing_but_the_composition_accessor() -> None:
    assert set(seat.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(seat, name), name
    for leaked in NOT_THE_SEATS_BUSINESS:
        assert leaked not in seat.__all__, leaked


def test_the_seat_returns_the_composed_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    store = router_exchange_info_component()
    assert store is not None
    assert type(store).__name__ == "RouterExchangeInfoStore"
    assert store.database_url == f"sqlite:///{tmp_path / 'seated.db'}"


def test_the_seat_reads_the_application_it_is_handed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'handed.db'}")
    app = create_app()
    assert router_exchange_info_component(app) is app.get(member.COMPONENT_NAME)


def test_a_deployment_without_a_database_seats_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    assert member.COMPONENT_NAME in app  # registered
    assert router_exchange_info_component(app) is None  # and resolved nothing


def test_an_absent_component_reads_as_none_rather_than_raising() -> None:
    assert router_exchange_info_component(Application()) is None


def test_the_seat_composes_nothing_of_its_own() -> None:
    empty = Application()
    assert router_exchange_info_component(empty) is None
    assert empty.components == {}


def test_an_empty_workspace_still_seats_only_the_absent_store(tmp_path: Path) -> None:
    empty = create_app(tmp_path, registry=Registration())
    assert empty.components == {}
    assert router_exchange_info_component(empty) is None


@pytest.mark.parametrize(
    "absent", ["", "Router", "exchange-info", "router-store", "exchangeinfo"]
)
def test_a_misspelled_component_key_is_absent_not_a_near_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, absent: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'keys.db'}")
    app = create_app()
    assert app.get(absent) is None
    assert SEAT_COMPONENT_NAME in app
    assert router_exchange_info_component(app) is not None
