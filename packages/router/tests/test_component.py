"""The composition seam, and feature 320's health store resolved beside it.

Mirrors ``packages/regime/tests/test_component.py``: the factory's scan
composes the store under the member's registered name, and
``create_app().get("router")`` answers *what is the composed exchangeInfo
version store?*.  The submission-health store is not a component: it is
resolved from ``DATABASE_URL`` by ``RouterSubmissionHealthStore.resolve()``.
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


def _assert_is_the_exchange_info_store(component: object) -> None:
    assert type(component).__name__ == "RouterExchangeInfoStore"
    assert type(component).__module__.endswith("router.store")
    for method in ("record", "current", "version", "filters_for"):
        assert callable(getattr(component, method)), method
    assert component.database_url is not None


# -- The registration ---------------------------------------------------------


def test_the_member_registers_under_its_own_name() -> None:
    assert member.COMPONENT_NAME == "router"


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


# -- Reading the composition -----------------------------------------------------


def test_the_composed_application_returns_the_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    store = create_app().get("router")
    assert store is not None
    assert type(store).__name__ == "RouterExchangeInfoStore"
    assert store.database_url == f"sqlite:///{tmp_path / 'composed.db'}"


def test_a_deployment_without_a_database_composes_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    assert member.COMPONENT_NAME in app  # registered
    assert app.get(member.COMPONENT_NAME) is None  # and resolved nothing


def test_an_absent_component_reads_as_none_rather_than_raising() -> None:
    assert Application().get(member.COMPONENT_NAME) is None


def test_reading_an_absent_component_composes_nothing() -> None:
    empty = Application()
    assert empty.get(member.COMPONENT_NAME) is None
    assert empty.components == {}


def test_an_empty_workspace_composes_only_the_absent_store(tmp_path: Path) -> None:
    empty = create_app(tmp_path, registry=Registration())
    assert empty.components == {}
    assert empty.get(member.COMPONENT_NAME) is None


@pytest.mark.parametrize(
    "absent", ["", "Router", "exchange-info", "router-store", "exchangeinfo"]
)
def test_a_misspelled_component_key_is_absent_not_a_near_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, absent: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'keys.db'}")
    app = create_app()
    assert app.get(absent) is None
    assert member.COMPONENT_NAME in app
    assert app.get(member.COMPONENT_NAME) is not None


# -- Feature 320's health store ---------------------------------------------


def test_the_health_store_is_not_a_component(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The distinction the feature turns on: a composed application answers
    # only for the process that composed it, and that process is the one
    # whose health is in question.  So the health store is resolved from
    # DATABASE_URL and the scan still registers exactly one component.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'health.db'}")
    app = create_app()
    assert member.COMPONENT_NAME in app
    # No second component, under any of the names a health store might have
    # been registered as -- and the scan still registers exactly one router.
    for guessed in (
        "submission_health",
        "router_submission_health",
        "router-submission-health",
        "router-health",
    ):
        assert app.get(guessed) is None, guessed
    registered = [
        component
        for component in Registration().components()
        if component.name == member.COMPONENT_NAME
    ]
    assert registered == []  # a fresh registry is empty
    registry = Registration()
    scan_components(registry=registry)
    assert [
        component.name
        for component in registry.components()
        if component.name == member.COMPONENT_NAME
    ] == [member.COMPONENT_NAME]
    # The store is reachable without the registry, which is the point.
    assert member.RouterSubmissionHealthStore.resolve() is not None


def test_the_health_store_resolves_from_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    url = f"sqlite:///{tmp_path / 'resolved-health.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = member.RouterSubmissionHealthStore.resolve()
    assert store is not None
    assert type(store).__name__ == "RouterSubmissionHealthStore"
    assert store.database_url == url


def test_a_deployment_without_a_database_resolves_no_health_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert member.RouterSubmissionHealthStore.resolve() is None


def test_resolving_the_health_store_opens_no_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A health accessor that opened a connection would make *asking about*
    # the router's liveness a way to fail, which is the one property this
    # feature cannot afford.
    database = tmp_path / "unopened.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    store = member.RouterSubmissionHealthStore.resolve()
    assert store is not None
    assert not database.exists()
    assert store.record(outcome="accepted").outcome == "accepted"
    assert database.exists()  # the demand is what wrote


def test_the_health_accessor_reads_what_another_process_wrote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from datetime import UTC, datetime

    url = f"sqlite:///{tmp_path / 'shared.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    writer = member.RouterSubmissionHealthStore.resolve()
    writer.record(
        outcome="rejected", observed_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        process_id="other-host/7",
    )
    reader = member.RouterSubmissionHealthStore.resolve()
    health = reader.health(
        now=datetime(2026, 9, 24, 12, 1, tzinfo=UTC), process_id="other-host/7"
    )
    assert health.total == 1
    assert health.unhealthy is True
    assert health.processes == ("other-host/7",)


def test_the_identity_is_the_stores_own_derivation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # There is no separate identity accessor: a caller holding the store
    # already holds the label its rows are filed under, and a pass-through
    # beside it would be a second spelling of the one fact "in its own process" is
    # about -- free to disagree with what the store writes.
    import os
    import socket

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'identity.db'}")
    store = member.RouterSubmissionHealthStore.resolve()
    assert store.process_id == f"{socket.gethostname()}/{os.getpid()}"
    assert store.record(outcome="accepted").process_id == store.process_id
