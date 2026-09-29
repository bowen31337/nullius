"""The two seams: composition via the loader, and per-process resolution.

Mirrors ``packages/router/tests/test_component.py``: the factory's scan
composes the kill switch under the member's registered name, the halt
event ledger under its own, the flattener under its own and the halt door
under its own.  The member also resolves each of them straight from
``DATABASE_URL`` (``RiskKillSwitch.resolve()``,
``RiskHaltEventStore.resolve()``, ``RiskFlattener.resolve()``,
``HaltEndpoint.from_env()``) for whichever process is asking, because the
supervisor that sends, the order layer that reads, the process that
records, the reconciler that sweeps and the supervisor that flattens are
different processes and none of their compositions can answer for
another.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
import risk as member

from app.module_loader import create_app

SENT = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)


def _assert_is_the_kill_switch(component: object) -> None:
    assert type(component).__name__ == "RiskKillSwitch"
    assert type(component).__module__.endswith("risk.kill")
    for method in ("send", "standing", "killed", "require_orders_allowed"):
        assert callable(getattr(component, method)), method
    assert component.database_url is not None


def _assert_is_the_halt_event_store(component: object) -> None:
    assert type(component).__name__ == "RiskHaltEventStore"
    assert type(component).__module__.endswith("risk.halt_events")
    for method in ("record", "events"):
        assert callable(getattr(component, method)), method
    assert component.database_url is not None


def _assert_is_the_flattener(component: object) -> None:
    assert type(component).__name__ == "RiskFlattener"
    assert type(component).__module__.endswith("risk.flatten")
    assert callable(component.flatten)  # type: ignore[attr-defined]
    assert component.database_url is not None


def _assert_is_the_halt_endpoint(component: object) -> None:
    assert type(component).__name__ == "HaltEndpoint"
    assert type(component).__module__.endswith("risk.halt")
    assert component.route == "/risk/halt"
    assert component.switch is not None
    assert component.flattener is not None


# -- The registration ---------------------------------------------------------


def test_the_member_registers_under_its_own_name() -> None:
    assert member.COMPONENT_NAME == "risk"
    # The ledger's and the flattener's component names live in the member
    # alone, but they are still spelled once per speaker — and the spec's kebab-case
    # convention for a member's second and third components holds.
    assert member.HALT_EVENTS_COMPONENT_NAME == "risk-halt-events"
    assert member.FLATTENER_COMPONENT_NAME == "risk-flattener"
    # The halt door is the fourth component — the composed act of the
    # kill and the flatten, driven in order, under its own kebab-case name.
    assert member.HALT_COMPONENT_NAME == "risk-halt"


def test_the_member_exports_exactly_four_builders() -> None:
    # The halt door is a fourth component, registered beside the switch,
    # the ledger and the flattener — the composed act of feature 322's
    # kill and feature 330's flatten, driven in order.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_halt_event_store",
        "build_risk_flattener",
        "build_risk_halt",
        "build_risk_kill_switch",
    ]


def test_the_scanned_application_carries_the_switch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.COMPONENT_NAME in app
    assert member.COMPONENT_NAME in app.order
    _assert_is_the_kill_switch(app.get(member.COMPONENT_NAME))


def test_the_scanned_application_carries_the_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Two different questions on two different lifecycles — is the
    # order layer killed, and what halted — so two different names a
    # caller asking for one is never handed the other.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.HALT_EVENTS_COMPONENT_NAME in app
    assert member.HALT_EVENTS_COMPONENT_NAME in app.order
    _assert_is_the_halt_event_store(app.get(member.HALT_EVENTS_COMPONENT_NAME))


def test_the_scanned_application_carries_the_flattener(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A third question — flatten now — on the shortest lifecycle of the
    # three: the one act that must run while another process is hung.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.FLATTENER_COMPONENT_NAME in app
    assert member.FLATTENER_COMPONENT_NAME in app.order
    _assert_is_the_flattener(app.get(member.FLATTENER_COMPONENT_NAME))


def test_the_scanned_application_carries_the_halt_door(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A fourth question — halt now — composed of the kill and the flatten
    # driven in order, on its own name so a caller asking for the act is
    # not handed one of its halves.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.HALT_COMPONENT_NAME in app
    assert member.HALT_COMPONENT_NAME in app.order
    _assert_is_the_halt_endpoint(app.get(member.HALT_COMPONENT_NAME))


def test_the_component_survives_a_second_composition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The submodule-registration hazard: the loader caches imported
    # submodules, so a @register in one fires on the first composition and
    # silently drops out of every later one — the reason all four
    # builders live in __init__.py.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    for app in (create_app(), create_app(), create_app()):
        _assert_is_the_kill_switch(app.get(member.COMPONENT_NAME))
        assert member.COMPONENT_NAME in app.order
        _assert_is_the_halt_event_store(app.get(member.HALT_EVENTS_COMPONENT_NAME))
        assert member.HALT_EVENTS_COMPONENT_NAME in app.order
        _assert_is_the_flattener(app.get(member.FLATTENER_COMPONENT_NAME))
        assert member.FLATTENER_COMPONENT_NAME in app.order
        _assert_is_the_halt_endpoint(app.get(member.HALT_COMPONENT_NAME))
        assert member.HALT_COMPONENT_NAME in app.order


def test_the_builder_degrades_to_none_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert create_app().get(member.COMPONENT_NAME) is None
    assert create_app().get(member.HALT_EVENTS_COMPONENT_NAME) is None
    assert create_app().get(member.FLATTENER_COMPONENT_NAME) is None
    assert create_app().get(member.HALT_COMPONENT_NAME) is None


def test_an_empty_database_url_counts_as_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert create_app().get(member.COMPONENT_NAME) is None
    assert create_app().get(member.HALT_EVENTS_COMPONENT_NAME) is None
    assert create_app().get(member.FLATTENER_COMPONENT_NAME) is None
    assert create_app().get(member.HALT_COMPONENT_NAME) is None


def test_the_builders_never_raise_and_take_no_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert list(inspect.signature(member.build_risk_kill_switch).parameters) == []
    assert list(inspect.signature(member.build_halt_event_store).parameters) == []
    assert list(inspect.signature(member.build_risk_flattener).parameters) == []
    assert list(inspect.signature(member.build_risk_halt).parameters) == []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert member.build_risk_kill_switch() is None
    assert member.build_halt_event_store() is None
    assert member.build_risk_flattener() is None
    assert member.build_risk_halt() is None
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'built.db'}")
    assert isinstance(member.build_risk_kill_switch(), member.RiskKillSwitch)
    assert isinstance(member.build_halt_event_store(), member.RiskHaltEventStore)
    assert isinstance(member.build_risk_flattener(), member.RiskFlattener)
    assert isinstance(member.build_risk_halt(), member.HaltEndpoint)


# -- Per-process resolution ------------------------------------------------------


def test_the_member_resolves_the_switch_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'resolved.db'}")
    switch = member.RiskKillSwitch.resolve()
    _assert_is_the_kill_switch(switch)


def test_the_member_resolves_the_ledger_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'resolved.db'}")
    store = member.RiskHaltEventStore.resolve()
    _assert_is_the_halt_event_store(store)


def test_the_member_resolves_the_flattener_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'resolved.db'}")
    flattener = member.RiskFlattener.resolve()
    _assert_is_the_flattener(flattener)


def test_the_member_resolves_the_halt_door_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'resolved.db'}")
    door = member.HaltEndpoint.from_env()
    _assert_is_the_halt_endpoint(door)


def test_the_member_resolves_none_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert member.RiskKillSwitch.resolve() is None
    assert member.RiskHaltEventStore.resolve() is None
    assert member.RiskFlattener.resolve() is None
    assert member.HaltEndpoint.from_env() is None


def test_the_composed_reflection_and_the_resolved_switch_are_one_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The member's component and its own resolution construct the same
    # class over the same URL, and the row behind both is one: what the
    # supervisor sends through a resolved switch is what a caller holding
    # the composed reflection reads standing.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'one-channel.db'}")
    app = create_app()
    composed = app.get(member.COMPONENT_NAME)
    resolved = member.RiskKillSwitch.resolve()
    assert composed is not None and resolved is not None
    sent = resolved.send(sent_at=SENT)
    assert sent.changed is True
    assert composed.killed() is True
    standing = composed.standing()
    assert standing is not None
    assert standing.supervisor_process_id == resolved.process_id


def test_the_composed_reflection_and_the_resolved_ledger_are_one_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The same one-door law for the ledger: what the halting process
    # records through a resolved store is what a caller holding the
    # composed reflection reconciles.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'one-record.db'}")
    app = create_app()
    composed = app.get(member.HALT_EVENTS_COMPONENT_NAME)
    resolved = member.RiskHaltEventStore.resolve()
    assert composed is not None and resolved is not None
    event = resolved.record(trigger_reason="manual_halt", triggered_at=SENT)
    assert event.sequence == 1
    swept = composed.events()
    assert len(swept) == 1
    assert swept[0].trigger_reason == "manual_halt"
    assert swept[0].supervisor_process_id == resolved.process_id


def test_the_composed_reflection_and_the_resolved_flattener_are_one_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The one-door law at the flattener: a kill sent through a resolved
    # switch is the authority a caller holding the composed reflection
    # flattens under.  The reflection carries less than its siblings do
    # — no table, so the engine face is still the caller's own — but the
    # authority is the same one row, and the record says so.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'one-authority.db'}")
    app = create_app()
    composed = app.get(member.FLATTENER_COMPONENT_NAME)
    resolved_switch = member.RiskKillSwitch.resolve()
    assert composed is not None and resolved_switch is not None
    sent = resolved_switch.send(sent_at=SENT, supervisor_process_id="supervisor/4711")
    assert sent.changed is True

    class Engine:
        def __init__(self):
            self.orders = ["order-a"]

        def open_orders(self):
            return tuple(self.orders)

        def cancel_order(self, order_id):
            self.orders = [o for o in self.orders if o != order_id]
            return {"client_order_id": order_id, "status": "CANCELED"}

        def open_positions(self):
            return ()

        def close_position(self, symbol):
            return {"symbol": symbol, "status": "CLOSED"}

    result = composed.flatten(Engine(), flattened_at=SENT)
    assert result.status == member.FLATTEN_STATUS_COMPLETED
    assert result.cancelled_orders == ("order-a",)
    assert result.instruction.supervisor_process_id == "supervisor/4711"
