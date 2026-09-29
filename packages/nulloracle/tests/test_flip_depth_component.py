"""Feature 119's flip-depth store as the composed application exposes it.

The composed flip-depth store is reached through the factory:
``create_app().get("nulloracle-null-flip-depth")``.  Composition stays the
factory's job, and a read answers ``None`` — not an exception — when there is
no component.  That degradation is pinned below.  A caller who has the store
reaches ``persist``/``load`` on it.
"""

from __future__ import annotations

from nulloracle import FLIP_DEPTH_COMPONENT_NAME

from app.module_loader import Application, create_app


def test_the_component_name_matches_the_member() -> None:
    # Pinned against the literal the composition is read by, so the member's
    # constant cannot drift silently.
    import nulloracle

    assert FLIP_DEPTH_COMPONENT_NAME == nulloracle.FLIP_DEPTH_COMPONENT_NAME == "nulloracle-null-flip-depth"


def test_the_component_is_read_from_an_application_it_is_handed() -> None:
    application = Application(
        components={FLIP_DEPTH_COMPONENT_NAME: "sentinel"},
        order=(FLIP_DEPTH_COMPONENT_NAME,),
    )
    assert application.get(FLIP_DEPTH_COMPONENT_NAME) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    empty = Application(components={}, order=())
    assert empty.get(FLIP_DEPTH_COMPONENT_NAME) is None


def test_an_unconfigured_environment_yields_none_not_an_exception() -> None:
    assert create_app().get(FLIP_DEPTH_COMPONENT_NAME) is None
