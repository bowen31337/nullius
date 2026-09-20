"""The member's seat inside the ``app`` package namespace.

``src/app/modules/nulloracle/__init__.py`` is where the composed null sidecar
is reachable from the ``app`` package without the app package importing the
member at module scope.  The member's suite owns this file (it lives at
``src/app/modules/nulloracle/``, which the task's file claim covers), so the
seat is tested here rather than in a repository-level suite.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not an
exception — when there is none.  That degradation is pinned below, since a
module that failed import because a member was absent would take the app
package down with it.

The seat is also where the *category's* other features will reach the
sidecar — the ``POST /target`` resolution of 112-113, the campaign
assignment of 117-122, the KS guard of 123 — so the one thing this file
guards hardest is that the accessor stays a thin composition read: it does
not grow a second spelling of ``write``/``open``/``assignment``.
"""

from __future__ import annotations

from app.module_loader import Application
from nulloracle import COMPONENT_NAME


def test_the_component_name_matches_the_member() -> None:
    # Spelled twice on purpose — once in the member, once in the seat — so
    # the two cannot drift apart silently.
    import nulloracle

    assert COMPONENT_NAME == nulloracle.COMPONENT_NAME == "nulloracle"


def test_the_seat_exposes_the_composed_sidecar(sidecar_path, key_ref: str) -> None:
    from app.modules.nulloracle import null_sidecar_component

    component = null_sidecar_component()
    assert type(component).__name__ == "NullSidecar"
    assert component.path == sidecar_path


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.nulloracle import null_sidecar_component

    application = Application(
        components={COMPONENT_NAME: "sentinel"}, order=(COMPONENT_NAME,)
    )
    assert null_sidecar_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.nulloracle import null_sidecar_component

    empty = Application(components={}, order=())
    assert null_sidecar_component(empty) is None


def test_an_unconfigured_environment_yields_none_not_an_exception() -> None:
    from app.modules.nulloracle import null_sidecar_component

    assert null_sidecar_component() is None


def test_the_seat_can_persist_an_assignment(sidecar_path, key_ref: str) -> None:
    # Feature 109 from the app namespace: composed sidecar, written map,
    # sealed file — the path an assembled system takes.
    from app.modules.nulloracle import null_sidecar_component
    from nulloracle import NullAssignment

    sidecar = null_sidecar_component()
    node_id = "6ee6bf93-8326-48f8-b4d5-921662768f45"
    sidecar.write([NullAssignment(node_id=node_id, is_null=True, perm_seed=1)])
    assert sidecar.path.exists()
    assert sidecar.open()[node_id].is_null is True


def test_the_seat_is_a_composition_read_and_not_a_second_api(
    sidecar_path, key_ref: str
) -> None:
    # The seat is deliberately accessors only: a caller who has the sidecar
    # reaches write/open/assignment on it, and a second spelling here would
    # be a second thing to keep in sync.
    from app.modules import nulloracle as seat

    exported = set(seat.__all__)
    assert exported == {"COMPONENT_NAME", "null_sidecar_component"}
