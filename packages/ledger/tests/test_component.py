"""The ledger member's registration, composition, and seat in the app namespace.

The implementation lives in the ``ledger`` workspace member
(``packages/ledger``), which self-registers with the application factory
under ``"ledger"``.  ``src/app/modules/ledger/`` is the member's seat in
the ``app`` package namespace: it names the component and asks the
factory for it without the ``app`` package depending on any member at
import time.  These tests pin that chain — workspace declaration, scan,
registration, composition, seat — so the member cannot silently fall out
of the composed application, and so a composition without a configured
``DATABASE_URL`` degrades to "no ledger component" rather than breaking.
"""

from __future__ import annotations

from pathlib import Path

import ledger
import pytest
from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
    workspace_scan_roots,
)
from app.modules import ledger as ledger_seat

MEMBER_SRC = Path(ledger.__file__).resolve().parent.parent


def test_member_is_declared_in_the_scanned_workspace() -> None:
    # The member's own pyproject.toml is what makes it a workspace member
    # and therefore scannable — the registration chain starts here, and no
    # edit to any central file was needed to make it true.
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()


def test_scan_registers_the_ledger_component() -> None:
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert "ledger" in names
    # The scan re-imports the package under its alias; the registry
    # replaces by name, so one ledger component survives any number of
    # rescans.
    again = scan_components(MEMBER_SRC, registry=registry)
    assert [c.name for c in again].count("ledger") == 1


def test_composed_app_builds_the_ledger_component(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get("ledger")
    assert component is not None
    # Duck-checked rather than isinstance against the canonical import:
    # the scan imports the member under an alias module
    # (``_nullius_scanned_ledger``), so the composed component is
    # structurally a TrialLedger but never the same module object a
    # direct import yields.
    assert callable(component.append)
    assert callable(component.rows)
    assert callable(component.count)
    assert callable(component.get)
    # Bound to the database the process is pointed at — resolved at
    # composition time from DATABASE_URL, set per test by the fixtures —
    # and composing touched no disk: construction performs no I/O.
    assert component.database_url == test_database_url
    assert "ledger" in app.order


def test_the_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no ledger component,
    # the same degradation the factory applies to an absent workspace.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("ledger") is None


def test_the_seat_exposes_the_composed_ledger_component(
    test_database_url: str,
) -> None:
    assert ledger_seat.COMPONENT_NAME == "ledger"
    app = create_app(MEMBER_SRC, registry=Registration())
    component = ledger_seat.ledger_component(app)
    assert component is app.get("ledger")
    assert callable(component.append)


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    application = Application(
        components={ledger_seat.COMPONENT_NAME: {"sentinel": True}},
        order=(ledger_seat.COMPONENT_NAME,),
    )
    assert ledger_seat.ledger_component(application) == {"sentinel": True}


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    # A module that cannot reach the component returns None rather than
    # failing — mirroring the factory's stance toward absent components.
    assert ledger_seat.ledger_component(Application()) is None
