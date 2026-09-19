"""The member's seat inside the ``app`` package namespace.

``src/app/modules/contract/__init__.py`` is where the composed contract
component is reachable from the ``app`` package without the app package
importing the member at module scope. The contract suite owns this file's
subject (the seat is inside this feature's declared footprint), so the seat
is tested here alongside the composition tests that pin how the component
gets there.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not an
exception — when there is none. That degradation is pinned below, since a
module that failed import because a member was absent would take the app
package down with it.
"""

from __future__ import annotations

from app.module_loader import Application


def test_the_seat_exposes_the_composed_contract_component() -> None:
    from app.modules.contract import COMPONENT_NAME, contract_component

    assert COMPONENT_NAME == "contract"
    component = contract_component()
    assert component["contract_version"] == "0.1.0"
    assert component["market_window"] == "contract:MarketWindow"


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.contract import COMPONENT_NAME, contract_component

    application = Application(
        components={COMPONENT_NAME: {"sentinel": True}}, order=(COMPONENT_NAME,)
    )
    assert contract_component(application) == {"sentinel": True}


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.contract import contract_component

    empty = Application(components={}, order=())
    assert contract_component(empty) is None
