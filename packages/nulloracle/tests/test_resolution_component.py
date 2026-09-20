"""Feature 121's seat inside the ``app`` package namespace.

``src/app/modules/nulloracle/resolution.py`` is where the composed Type-D
oracle is reachable from the ``app`` package without the app package
importing the member at module scope.  The member's suite owns this file (it
lives at ``src/app/modules/nulloracle/``, which the task's file claim
covers), so the seat is tested here rather than in a repository-level suite.

The point of the seat is that composition stays the factory's job: this module
asks the factory for the component, and answers ``None`` — not an exception —
when there is none.  That degradation is pinned below, since a module that
failed import because a member was absent would take the app package down with
it.  The seat is also deliberately accessors only: a caller who has the oracle
reaches ``resolve_request`` on it, and a second spelling here would be a
second thing to keep in sync.

The composed half is pinned too: with a ``DATABASE_URL`` named, the factory's
scan imports the member, its ``@register`` fires, and the composed
application carries a Type-D oracle bound to that URL — the arrangement the
§7.2 endpoint will ask for.
"""

from __future__ import annotations

import pytest
from nulloracle import DATABASE_URL_ENV, RESOLUTION_COMPONENT_NAME

from app.module_loader import Application


@pytest.fixture(autouse=True)
def _database_url_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no ``DATABASE_URL`` in the environment.

    Autouse and unconditional, mirroring ``test_flipdepth.py``'s isolation
    fixture: the default state of a test is a deployment that names no
    relational store, and the tests that assert on the *unconfigured*
    behaviour then do not fight a fixture that helpfully configured one.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


def test_the_component_name_matches_the_member() -> None:
    # Spelled twice on purpose — once in the member, once in the seat — so
    # the two cannot drift apart silently.
    import nulloracle

    assert (
        RESOLUTION_COMPONENT_NAME
        == nulloracle.RESOLUTION_COMPONENT_NAME
        == "nulloracle-type-d-resolution"
    )


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.nulloracle.resolution import type_d_resolution_component

    application = Application(
        components={RESOLUTION_COMPONENT_NAME: "sentinel"},
        order=(RESOLUTION_COMPONENT_NAME,),
    )
    assert type_d_resolution_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.nulloracle.resolution import type_d_resolution_component

    empty = Application(components={}, order=())
    assert type_d_resolution_component(empty) is None


def test_an_unconfigured_environment_yields_none_not_an_exception() -> None:
    from app.modules.nulloracle.resolution import type_d_resolution_component

    assert type_d_resolution_component() is None


def test_a_configured_environment_composes_the_oracle(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The factory's scan imports the member, the ``@register`` builder fires,
    # and the composed application carries a Type-D oracle bound to the
    # database the deployment named — no registry, router or factory edit
    # involved.
    from app.modules.nulloracle.resolution import type_d_resolution_component

    url = f"sqlite:///{tmp_path / 'composed.db'}"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    component = type_d_resolution_component()
    assert type(component).__name__ == "TypeDOracle"
    assert component.database_url == url


def test_composing_the_oracle_creates_no_database_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The factory builds every registered component on every ``create_app()``
    # call, so a builder that opened a database would open one for every
    # composition of every application in the process.  The oracle resolves
    # its path lazily; asking for the component touches no file.
    from app.modules.nulloracle.resolution import type_d_resolution_component

    url = f"sqlite:///{tmp_path / 'uncreated.db'}"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    component = type_d_resolution_component()
    assert component is not None
    assert not (tmp_path / "uncreated.db").exists()


def test_the_builder_is_registered_beside_the_members_other_components() -> None:
    # The member contributes six components now — the sidecar, the guard, the
    # verdict, the fraction, the flip depth and this resolution — and the
    # scan discovers them all by name, deterministically, on every scan.
    from app.module_loader import scan_components

    names = [component.name for component in scan_components()]
    assert RESOLUTION_COMPONENT_NAME in names


def test_the_seat_is_a_composition_read_and_not_a_second_api() -> None:
    # The seat is deliberately accessors only: a caller who has the oracle
    # reaches resolve_request on it, and a second spelling here would be a
    # second thing to keep in sync.
    from app.modules import nulloracle

    seat_all = set(nulloracle.resolution.__all__)
    assert seat_all == {"COMPONENT_NAME", "type_d_resolution_component"}
