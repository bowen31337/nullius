"""The two seams: composition via the loader, and the app seat.

Mirrors ``packages/router/tests/test_component.py``: the factory's scan
composes the kill switch under the member's registered name, and
``app.modules.risk`` answers *what is the risk supervisor's kill switch,
for the process asking?* for a caller that holds the app namespace.
``risk`` carries no hyphen, so both the member and the seat are plain
dotted imports — no ``importlib.import_module`` trick needed (unlike the
``cost-model`` seat).

The seat's own law is pinned here too: it exposes exactly one accessor,
and that accessor takes no ``app`` argument — the channel is resolved
from ``DATABASE_URL`` for whichever process is asking, because the
supervisor that sends and the order layer that reads are different
processes and neither one's composition can answer for the other.
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
from app.modules.risk import risk_kill_switch

EXPECTED_EXPORTS = {
    "COMPONENT_NAME",
    "risk_kill_switch",
}

NOT_THE_SEATS_BUSINESS = (
    "RiskKillSwitch",
    "KillInstruction",
    "RiskError",
    "RiskKillSwitchError",
    "RiskOrdersKilledError",
    "RiskStoreError",
    "send_kill",
    "require_orders_allowed",
    "orders_killed_error",
    "RISK_ORDER_KILL_TABLE",
    "process_identity",
)

SENT = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)


def _assert_is_the_kill_switch(component: object) -> None:
    assert type(component).__name__ == "RiskKillSwitch"
    assert type(component).__module__.endswith("risk.kill")
    for method in ("send", "standing", "killed", "require_orders_allowed"):
        assert callable(getattr(component, method)), method
    assert component.database_url is not None


# -- The registration ---------------------------------------------------------


def test_the_member_registers_under_its_own_name() -> None:
    assert member.COMPONENT_NAME == SEAT_COMPONENT_NAME == "risk"


def test_the_member_exports_exactly_one_builder() -> None:
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_risk_kill_switch"
    ]


def test_the_scanned_application_carries_the_switch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.COMPONENT_NAME in app
    assert member.COMPONENT_NAME in app.order
    _assert_is_the_kill_switch(app.get(member.COMPONENT_NAME))


def test_the_component_survives_a_second_composition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The submodule-registration hazard: the loader caches imported
    # submodules, so a @register in one fires on the first composition and
    # silently drops out of every later one — the reason the builder lives
    # in __init__.py.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    for app in (create_app(), create_app(), create_app()):
        _assert_is_the_kill_switch(app.get(member.COMPONENT_NAME))
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
    assert list(inspect.signature(member.build_risk_kill_switch).parameters) == []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert member.build_risk_kill_switch() is None
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'built.db'}")
    assert isinstance(member.build_risk_kill_switch(), member.RiskKillSwitch)


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


def test_the_seats_accessor_takes_no_app_argument() -> None:
    # The channel's law, stated at the signature: the supervisor that
    # sends and the order layer that reads compose nothing, so the seat
    # accepting an application would suggest the answer depended on one.
    parameters = inspect.signature(risk_kill_switch).parameters
    assert set(parameters) == set()


def test_the_seat_resolves_the_switch_for_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    switch = risk_kill_switch()
    _assert_is_the_kill_switch(switch)


def test_the_seat_answers_none_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert risk_kill_switch() is None


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
