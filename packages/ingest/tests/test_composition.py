"""Plugin wiring: the ingest member registers with the application factory.

No central file names this package.  The root pyproject declares
``packages/*`` as the workspace; this member exists with its own
``pyproject.toml``; the factory scans the declared members, the import
fires ``@register("ingest")``, and ``create_app`` composes the component.
These tests pin that chain — discovery, registration, composition — and
the app-package facade over it, so the plugin cannot silently fall out
of the composed application.
"""

from __future__ import annotations

from pathlib import Path

import app.modules.ingest as ingest_facade
from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
    workspace_scan_roots,
)

import nullius_ingest

MEMBER_SRC = Path(nullius_ingest.__file__).resolve().parent.parent


def test_member_is_declared_in_the_scanned_workspace() -> None:
    # The member's own pyproject.toml is what makes it a workspace
    # member and therefore scannable — the registration chain starts here.
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()


def test_scan_of_the_member_registers_the_ingest_component() -> None:
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    # The scan imports the member under an alias; the name it registers
    # under is the stable contract, the module identity is not.
    assert "ingest" in [component.name for component in components]


def test_composed_app_builds_an_ingest_supervisor() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get("ingest")
    assert component is not None
    # The component is the supervisor (duck-checked: the scan imports the
    # member under an alias module, so isinstance against the canonical
    # import would compare two copies of the same class).
    assert callable(component.run_cycle)
    assert "ingest" in app.order


def test_supervisor_over_no_registered_streams_reports_a_clean_empty_cycle() -> None:
    # An ingest layer with no stream modules is a valid, running (if idle)
    # state — the stance composition is built on.  Composed from an isolated
    # empty registry, because the default one carries whatever stream modules
    # have landed (feature 24's exchangeInfo worker, below).
    from nullius_ingest import WorkerRegistry
    from nullius_ingest.registry import build_supervisor

    report = build_supervisor(registry=WorkerRegistry()).run_cycle()

    assert report.ok
    assert len(report) == 0


def test_composed_supervisor_carries_the_exchangeinfo_stream_worker() -> None:
    # Feature 24's stream module registers itself by being imported, so the
    # composed supervisor already supervises the exchangeInfo stream — the
    # whole wiring story, with no shared file naming this package's stream.
    from nullius_ingest import StreamClass

    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get("ingest")

    assert StreamClass.EXCHANGE_INFO in component
    worker = component.worker_for(StreamClass.EXCHANGE_INFO)
    # Compared by stream-class value, not identity: the scan imports the
    # member under an alias module, so the composed worker's StreamClass is a
    # second copy of the enum (the same caveat the duck-checked component
    # test above notes).  The persisted spelling is the stable contract.
    assert str(worker.stream_class) == StreamClass.EXCHANGE_INFO.value


def test_composed_supervisor_isolates_a_registered_stream_failure() -> None:
    # End to end through the factory: a registered worker factory fails,
    # the composed supervisor returns its failure per stream, and the
    # healthy stream still ingests.  Registered into an isolated
    # registry-owned supervisor so the default registry stays pristine.
    from nullius_ingest import FunctionWorker, StreamClass, WorkerRegistry
    from nullius_ingest.registry import build_supervisor

    registry = WorkerRegistry()

    def broken_klines() -> int:
        raise ValueError("backfill window refused")

    registry.register(
        StreamClass.KLINES,
        lambda: FunctionWorker(StreamClass.KLINES, broken_klines),
    )
    registry.register(
        StreamClass.AGG_TRADES,
        lambda: FunctionWorker(StreamClass.AGG_TRADES, lambda: 25),
    )

    supervisor = build_supervisor(registry=registry)
    report = supervisor.run_cycle()

    assert len(report.failures) == 1
    assert report.failures[0].stream is StreamClass.KLINES
    assert report.outcome_for(StreamClass.AGG_TRADES).rows_written == 25


def test_app_modules_ingest_facade_exposes_the_component() -> None:
    # src/app/modules/ingest is the member's seat in the app namespace:
    # it asks the factory for the component without the app package
    # depending on any member at import time.
    assert ingest_facade.COMPONENT_NAME == "ingest"

    app = create_app(MEMBER_SRC, registry=Registration())
    component = ingest_facade.ingest_component(app)
    assert callable(component.run_cycle)


def test_facade_returns_none_when_nothing_registered() -> None:
    # An application with no ingest component is a discoverable state,
    # not an exception — mirroring the factory's stance.
    assert ingest_facade.ingest_component(Application()) is None
