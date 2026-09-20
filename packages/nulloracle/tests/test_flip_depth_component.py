"""Feature 119's seat inside the ``app`` package namespace.

``src/app/modules/nulloracle/flipdepth.py`` is where the composed flip-depth
store is reachable from the ``app`` package without the app package importing
the member at module scope.  The member's suite owns this file (it lives at
``src/app/modules/nulloracle/``, which the task's file claim covers), so the
seat is tested here rather than in a repository-level suite.

The point of the seat is that composition stays the factory's job: this module
asks the factory for the component, and answers ``None`` — not an exception —
when there is none.  That degradation is pinned below, since a module that
failed import because a member was absent would take the app package down with
it.  The seat is also deliberately accessors only: a caller who has the store
reaches ``persist``/``load`` on it, and a second spelling here would be a
second thing to keep in sync.
"""

from __future__ import annotations

from nulloracle import FLIP_DEPTH_COMPONENT_NAME

from app.module_loader import Application


def test_the_component_name_matches_the_member() -> None:
    # Spelled twice on purpose — once in the member, once in the seat — so
    # the two cannot drift apart silently.
    import nulloracle

    assert FLIP_DEPTH_COMPONENT_NAME == nulloracle.FLIP_DEPTH_COMPONENT_NAME == "nulloracle-null-flip-depth"


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.nulloracle.flipdepth import flip_depth_component

    application = Application(
        components={FLIP_DEPTH_COMPONENT_NAME: "sentinel"},
        order=(FLIP_DEPTH_COMPONENT_NAME,),
    )
    assert flip_depth_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.nulloracle.flipdepth import flip_depth_component

    empty = Application(components={}, order=())
    assert flip_depth_component(empty) is None


def test_an_unconfigured_environment_yields_none_not_an_exception() -> None:
    from app.modules.nulloracle.flipdepth import flip_depth_component

    assert flip_depth_component() is None


def test_the_seat_is_a_composition_read_and_not_a_second_api() -> None:
    # The seat is deliberately accessors only: a caller who has the store
    # reaches persist/load on it, and a second spelling here would be a
    # second thing to keep in sync.
    from app.modules import nulloracle

    seat_all = set(nulloracle.flipdepth.__all__)
    assert seat_all == {"COMPONENT_NAME", "flip_depth_component"}
