"""The two seams: composition via the loader, and the app seat.

Mirrors ``packages/router/tests/test_component.py``: the factory's scan
composes the kill switch under the member's registered name, the halt
event ledger under its own, and the flattener under its own, and
``app.modules.risk`` answers *what is the risk supervisor's kill
switch, what is its halt event ledger, and what is its flattener, for
the process asking?* for a caller that holds the app namespace.
``risk`` carries no hyphen, so both the member and the seat are plain
dotted imports — no ``importlib.import_module`` trick needed (unlike the
``cost-model`` seat).

The seat's own law is pinned here too: it exposes exactly one accessor
per member component, and every accessor takes no ``app`` argument — the
channel, the ledger and the flattener are resolved from ``DATABASE_URL``
for whichever process is asking, because the supervisor that sends, the
order layer that reads, the process that records, the reconciler that
sweeps and the supervisor that flattens are different processes and
none of their compositions can answer for another.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
import risk as member

from app.module_loader import create_app
from app.modules import risk as seat
from app.modules.risk import COMPONENT_NAME as SEAT_COMPONENT_NAME
from app.modules.risk import (
    risk_flattener,
    risk_halt_endpoint,
    risk_halt_event_store,
    risk_kill_switch,
)

EXPECTED_EXPORTS = {
    "COMPONENT_NAME",
    "risk_flattener",
    "risk_halt_endpoint",
    "risk_halt_event_store",
    "risk_kill_switch",
}

NOT_THE_SEATS_BUSINESS = (
    "RiskKillSwitch",
    "KillInstruction",
    "RiskHaltEventStore",
    "HaltEvent",
    "RiskFlattener",
    "FlattenResult",
    "RiskError",
    "RiskKillSwitchError",
    "RiskHaltEventError",
    "RiskFlattenError",
    "RiskOrdersKilledError",
    "RiskStoreError",
    "send_kill",
    "require_orders_allowed",
    "orders_killed_error",
    "record_halt",
    "recorded_halt_events",
    "flatten_positions",
    "FLATTEN_STATUS_COMPLETED",
    "RISK_ORDER_KILL_TABLE",
    "RISK_HALT_EVENT_TABLE",
    "HALT_EVENTS_COMPONENT_NAME",
    "FLATTENER_COMPONENT_NAME",
    "process_identity",
)

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
    assert member.COMPONENT_NAME == SEAT_COMPONENT_NAME == "risk"
    # The ledger's and the flattener's component names live in the member
    # alone (the seat resolves rather than reflects them), but they are
    # still spelled once per speaker — and the spec's kebab-case
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


# -- The seat -------------------------------------------------------------------


def test_the_seat_exports_exactly_the_promised_names() -> None:
    assert set(seat.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(seat, name), name
    for leaked in NOT_THE_SEATS_BUSINESS:
        assert leaked not in seat.__all__, leaked


def test_the_seat_does_not_re_export_the_members_surface() -> None:
    for name in NOT_THE_SEATS_BUSINESS:
        assert not hasattr(seat, name), name


def test_the_seats_accessors_take_no_app_argument() -> None:
    # The channel's law, stated at the signature: the supervisor that
    # sends and the order layer that reads compose nothing, so the seat
    # accepting an application would suggest the answer depended on one.
    # The ledger's accessor holds the same law for one process further:
    # the reconciler is usually an operator's sweep, hours after the
    # halting supervisor wrote.  The flattener's holds it at the limit:
    # the one act that must run while another process on this seat is
    # hung can be nobody's composition.
    assert set(inspect.signature(risk_kill_switch).parameters) == set()
    assert set(inspect.signature(risk_halt_event_store).parameters) == set()
    assert set(inspect.signature(risk_flattener).parameters) == set()
    assert set(inspect.signature(risk_halt_endpoint).parameters) == set()


def test_the_seat_resolves_the_switch_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    switch = risk_kill_switch()
    _assert_is_the_kill_switch(switch)


def test_the_seat_resolves_the_ledger_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    store = risk_halt_event_store()
    _assert_is_the_halt_event_store(store)


def test_the_seat_resolves_the_flattener_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    flattener = risk_flattener()
    _assert_is_the_flattener(flattener)


def test_the_seat_resolves_the_halt_door_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    door = risk_halt_endpoint()
    _assert_is_the_halt_endpoint(door)


def test_the_seat_answers_none_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert risk_kill_switch() is None
    assert risk_halt_event_store() is None
    assert risk_flattener() is None
    assert risk_halt_endpoint() is None


def test_the_composed_reflection_and_the_resolved_switch_are_one_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The member's component and the seat's resolution construct the same
    # class over the same URL, and the row behind both is one: what the
    # supervisor sends through a resolved switch is what a caller holding
    # the composed reflection reads standing.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'one-channel.db'}")
    app = create_app()
    composed = app.get(member.COMPONENT_NAME)
    resolved = risk_kill_switch()
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
    resolved = risk_halt_event_store()
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
    resolved_switch = risk_kill_switch()
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
