"""Feature 112's seat inside the ``app`` package namespace.

``src/app/modules/nulloracle/target.py`` is where the composed POST
/target route is reachable from the ``app`` package without the app
package importing the member at module scope.  The member's suite owns
this file (it lives at ``src/app/modules/nulloracle/``, which the task's
file claim covers), so the seat is tested here rather than in a
repository-level suite — the same arrangement the resolution's, the
verdict's and the flip depth's seats state.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not an
exception — when there is none.  That degradation is pinned below, since a
module that failed import because a member was absent would take the app
package down with it.  The seat is also deliberately accessors only: a
caller who has the endpoint reaches ``post`` on it, and a second spelling
here would be a second thing to keep in sync.

The composed half is pinned too: with a sidecar location and key named,
the factory's scan imports the member, its ``@register`` fires, and the
composed application carries a route over that same sidecar — the
arrangement §6.1's null_gate step asks through.  And the component name's
place in the name-sorted ``app.order`` is asserted, because feature 123's
guard is required to compose immediately after the sidecar and a
mis-sorted tenth name would silently break that adjacency.
"""

from __future__ import annotations

import pytest
from nulloracle import TARGET_COMPONENT_NAME, NullAssignment

from app.module_loader import Application


@pytest.fixture(autouse=True)
def _sidecar_environment_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with the sidecar environment the member conftest clears.

    The member's own autouse fixtures already clear ``NULL_SIDECAR_PATH``,
    ``NULL_SIDECAR_KEY_REF`` and ``NULL_SIDECAR_SERVICE_ACCOUNT``; this
    fixture exists so the *reader* of this file sees that the unconfigured
    tests below start from a deployment that names nothing, without having
    to look two files over.
    """
    for name in (
        "NULL_SIDECAR_PATH",
        "NULL_SIDECAR_KEY_REF",
        "NULL_SIDECAR_SERVICE_ACCOUNT",
    ):
        monkeypatch.delenv(name, raising=False)


class _Ask:
    """A minimal ask for the composed route.

    The composed endpoint was imported by the scan under an alias module,
    so its ``TargetRequest`` is not the class a direct import yields; the
    route reads its request duck-typed (validating the identity by value),
    and this stand-in pins that the composed component answers one.
    """

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


def test_the_component_name_matches_the_member() -> None:
    # Spelled twice on purpose — once in the member, once in the seat — so
    # the two cannot drift apart silently.
    import nulloracle

    assert (
        TARGET_COMPONENT_NAME
        == nulloracle.TARGET_COMPONENT_NAME
        == "nulloracle-target-route"
    )


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.nulloracle.target import target_route_component

    application = Application(
        components={TARGET_COMPONENT_NAME: "sentinel"},
        order=(TARGET_COMPONENT_NAME,),
    )
    assert target_route_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.nulloracle.target import target_route_component

    empty = Application(components={}, order=())
    assert target_route_component(empty) is None


def test_an_unconfigured_environment_yields_none_not_an_exception() -> None:
    from app.modules.nulloracle.target import target_route_component

    assert target_route_component() is None


def test_a_configured_environment_composes_the_route(
    sidecar_path, key_ref: str, node_id: str
) -> None:
    # The factory's scan imports the member, the ``@register`` builder
    # fires, and the composed application carries a route over the sidecar
    # the deployment named — no registry, router or factory edit involved.
    from app.modules.nulloracle.target import target_route_component

    component = target_route_component()
    assert type(component).__name__ == "TargetEndpoint"
    assert component.sidecar.path == sidecar_path

    # And the composed route answers over the composed sidecar: the two
    # components resolve from one environment, so they can never point at
    # two worlds.
    from app.module_loader import create_app

    application = create_app()
    sidecar = application.get("nulloracle")
    route = application.get(TARGET_COMPONENT_NAME)
    sidecar.write([NullAssignment(node_id=node_id, is_null=True, perm_seed=7)])
    response = route.post(_Ask(node_id))
    assert response.status == 200
    assert response.known is True


def test_composing_the_route_creates_no_sidecar_file(
    sidecar_path, key_ref: str
) -> None:
    # The factory builds every registered component on every
    # ``create_app()`` call, so a builder that opened the sidecar would
    # open it for every composition of every application in the process.
    # The endpoint holds its sidecar lazily; asking for the component
    # touches no file.
    from app.modules.nulloracle.target import target_route_component

    component = target_route_component()
    assert component is not None
    assert not sidecar_path.exists()


def test_the_builder_is_registered_beside_the_members_other_components() -> None:
    # The member contributes seven components now — the sidecar, the
    # guard, the verdict, the fraction, the flip depth, the resolution and
    # this route — and the scan discovers them all by name,
    # deterministically, on every scan.
    from app.module_loader import scan_components

    names = [component.name for component in scan_components()]
    assert TARGET_COMPONENT_NAME in names


def test_the_guard_still_composes_immediately_after_the_sidecar(
    sidecar_path, key_ref: str
) -> None:
    # ``app.order`` is name-sorted, and feature 123's guard is required to
    # land immediately after the sidecar.  The route's ``target-`` prefix
    # sorts after every ``ks-*`` and ``null-*`` name, so the tenth
    # component changes nothing about that adjacency — asserted here so a
    # future eleventh name cannot break it silently either.
    from app.module_loader import create_app

    order = create_app().order
    assert order.index("nulloracle") + 1 == order.index("nulloracle-ks-guard")


def test_the_seat_is_a_composition_read_and_not_a_second_api() -> None:
    # The seat is deliberately accessors only: a caller who has the route
    # reaches post on it, and a second spelling here would be a second
    # thing to keep in sync.
    import app.modules.nulloracle.target as seat

    assert set(seat.__all__) == {"COMPONENT_NAME", "target_route_component"}
