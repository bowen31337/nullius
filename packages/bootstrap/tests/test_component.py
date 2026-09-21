"""The plugin seam: composition via the module loader.

This is feature 181's registration contract from the other side — the
factory scans the workspace members, imports this package, the
``@register`` builder at the foot of ``bootstrap/__init__.py`` fires, and
the composed application carries a ``bootstrap`` component.  No registry,
router, entry-points table or factory was edited to make that true, and
this suite exists to keep it true.

Two properties of the loader shape these tests, and both are the same two
the artifacts, snapshot and null-oracle suites state for their own
members:

* **the loader imports each member under a synthetic module name**
  (``_nullius_scanned_bootstrap``), so a package this suite also imported
  canonically as ``bootstrap`` exists in the process twice, with two
  distinct class objects.  ``isinstance`` across the two copies cannot
  hold, so the composed component is pinned by class name, module suffix
  and — decisively — behaviour: the world the factory hands out answers
  the same labels the canonically-imported one does, to the last bit.
* **it re-executes a package's ``__init__`` on every ``create_app()`` but
  does not re-execute an already-cached submodule.**  So a ``@register``
  that lived in a submodule would fire on the first composition of a
  process and silently drop out of every later one.
  :func:`test_the_component_survives_a_second_composition` is what
  catches that, and it must assert on the *second* application or it
  passes vacuously.  This is the reason the builder lives in
  ``__init__.py`` and not beside the world it builds.

The builder must also never raise and needs no configuration — unlike
every other component in this workspace, which has a deployment state it
degrades to (``ARTIFACT_ROOT`` unset, ``DATABASE_URL`` absent).  A
generated world has none: its whole configuration *is* its seed.  That is
a property of §10.6 rather than an accident, and
:func:`test_the_builder_needs_no_environment` pins it, because a world
that could fail to compose would put §10.3.1's precondition (*"is a
compute problem"*) back where it started.

**What this suite deliberately does not test.**  Whether a *world* is
honest — that its labels are ground truth, discriminating and
seed-derived — belongs to ``test_world.py``, ``test_label.py`` and
``test_fit.py``, which exercise it directly rather than through the seam.
Here the only question is whether composition happened at all.
"""

from __future__ import annotations

import os

#: The member's own package, imported by this suite through the
#: ``conftest.py`` path bootstrap — the *canonical* copy, distinct from
#: the one the loader makes.
import bootstrap as member
import pytest

from app.module_loader import Application, Registration, create_app, scan_components


def _assert_is_the_hyperparameter_world(component: object) -> None:
    """The composed component is a world, pinned across the loader's copies.

    Name, module suffix, then behaviour — in that order, because the first
    two are what a synthetic-name copy *can* be compared on and the third
    is what actually matters.  The behaviour check is the strongest of the
    three and the least likely to pass by accident: it asks the composed
    world for a label and compares it to the canonically-imported world's,
    bit for bit.
    """
    assert type(component).__name__ == "HyperparameterWorld"
    assert type(component).__module__.endswith("bootstrap._world")

    # The whole of the world's answer surface, so a composition carrying a
    # stub — or one wired to a lattice but not to the fit — fails here
    # rather than at the first caller.  Split by whether the attribute is
    # a question asked (callable) or a fact read (property), because
    # ``callable`` on a property *value* is a false failure rather than a
    # signal — and getting that wrong once already made this test report a
    # perfectly good world as broken.
    for question in (
        "canonical_node",
        "setting",
        "steps",
        "node_id",
        "legal_moves",
        "legal_roots",
        "depth",
        "label",
        "label_setting",
        "label_all",
        "cells",
    ):
        assert callable(getattr(component, question)), question
    for fact in ("world_id", "dataset", "axes", "seed", "canonical_setting"):
        assert getattr(component, fact) is not None, fact

    # And the decisive check: the composed world answers what the member's
    # own world answers, to the last bit.
    node_id = component.canonical_node()  # type: ignore[attr-defined]
    composed = component.label(node_id)  # type: ignore[attr-defined]
    direct = member.hyperparameter_world().label(node_id)
    assert composed.r2_holdout == direct.r2_holdout
    assert composed.coefficients == direct.coefficients


# -- Composition -------------------------------------------------------------------


def test_the_member_registers_under_the_bootstrap_component_name() -> None:
    # The component name is the *plugin* name the spec's features carry
    # (``plugin="bootstrap"``), so the component key, this member's seat
    # and the spec cannot drift apart.
    assert member.COMPONENT_NAME == "bootstrap"
    assert member.HYPERPARAMETER_WORLD_ID == member.DEFAULT_WORLD_ID


def test_the_scanned_application_carries_the_world() -> None:
    app = create_app()
    assert "bootstrap" in app
    assert "bootstrap" in app.order
    _assert_is_the_hyperparameter_world(app.get("bootstrap"))


def test_the_composed_world_is_bound_to_the_published_id_and_seed() -> None:
    # The application carries *a named* world rather than an anonymous
    # one: §10.6's pool is reported per pool and an operator reading a
    # replay score wants to know which world it came from, so the id the
    # component answers with must be the one the module publishes.
    world = create_app().get("bootstrap")
    assert world.world_id == member.HYPERPARAMETER_WORLD_ID  # type: ignore[attr-defined]
    assert world.seed == member.PRICED_SEED  # type: ignore[attr-defined]


def test_the_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard, and the reason the builder lives
    # in ``__init__.py``.  The loader caches imported submodules, so a
    # ``@register`` in one fires on the first ``create_app()`` of a
    # process and not on later ones — the component would be present the
    # first time and quietly absent every time after.
    #
    # Asserts on the *second* application specifically: a test that only
    # looked at the first would pass whichever module the builder lived
    # in, and would have caught nothing.
    first = create_app()
    second = create_app()
    _assert_is_the_hyperparameter_world(first.get("bootstrap"))
    _assert_is_the_hyperparameter_world(second.get("bootstrap"))
    assert "bootstrap" in second.order

    # And a third, for the same reason one more time: the hazard is about
    # *every* composition after the first, not about the second alone.
    third = create_app()
    _assert_is_the_hyperparameter_world(third.get("bootstrap"))


def test_the_builder_never_raises_and_takes_no_arguments() -> None:
    # The factory builds every registered component on every
    # ``create_app()``, so a builder that raised would take composition
    # down for every unrelated feature in the workspace.  And the
    # registration protocol passes nothing, so a builder with a required
    # parameter could not be called at all.
    import inspect

    assert list(inspect.signature(member.hyperparameter_world).parameters) == []
    first = member.hyperparameter_world()
    second = member.hyperparameter_world()
    assert first is not second  # a fresh world per call, not a shared one
    assert first.world_id == second.world_id  # bound to the same identity


def test_the_builder_needs_no_environment() -> None:
    # Unlike every other component in this workspace — the store needs a
    # root, the null sidecar needs its files — a generated world has no
    # deployment state to degrade to, because its whole configuration *is*
    # its seed.  §10.6 makes the pool's precondition *"a compute problem
    # rather than a calendar problem"*; a world that could fail to compose
    # would put the precondition back where it started, so this is a
    # property of the category rather than a convenience.
    #
    # Checked by constructing the world and labelling a node with the
    # environment *stripped*, which is the state a misconfigured
    # deployment presents.
    scrubbed = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("NULLIUS") and not key.startswith("BOOTSTRAP")
    }
    restore = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(scrubbed)
        world = member.hyperparameter_world()
        assert world.label(world.canonical_node()).r2_holdout == pytest.approx(
            member.hyperparameter_world().label(world.canonical_node()).r2_holdout,
            abs=0.0,
        )
    finally:
        os.environ.clear()
        os.environ.update(restore)


def test_scanning_registers_exactly_one_component() -> None:
    # A second registration of the same name would be silently overridden
    # by whichever import landed later (``Registration.add``: "a later
    # import of the same component name wins"), so a duplicate would be
    # invisible at runtime and would make the composed world depend on
    # scan order.  Counted against a *fresh* registry so the assertion is
    # about this member's contribution rather than about the workspace's.
    registry = Registration()
    components = scan_components(registry=registry)
    named = [component for component in components if component.name == "bootstrap"]
    assert len(named) == 1


def test_the_build_helper_is_not_registered() -> None:
    # ``build_hyperparameter_world`` is a second *spelling* of the
    # builder for a caller that wants the world without the composed
    # application — not a second component.  Registering it would put two
    # components of one name in the registry, and the later import would
    # silently win.
    registry = Registration()
    scan_components(registry=registry)
    assert [c.name for c in registry.components()].count("bootstrap") == 1
    # And the two spellings are one function, so they cannot drift.
    assert member.build_hyperparameter_world is member.hyperparameter_world


def test_the_component_reads_from_a_handed_application() -> None:
    # ``Application`` is a plain dataclass, so a caller can hand a
    # deliberately incomplete one to check the absent case without
    # depending on the scan having failed.  Here: the seat reads the
    # component from whatever application it is given, rather than
    # composing its own behind the caller's back.
    #
    # The seat's own suite is ``test_app_module.py``; this is the
    # composition-level half of it, kept here because what it exercises is
    # the loader's ``Application`` shape rather than the seat's API.
    app = create_app()
    assert member_seat().hyperparameter_world_component(app) is app.get("bootstrap")
    assert member_seat().hyperparameter_world_component(Application()) is None


def member_seat():
    """The app-package seat for this member, imported on demand.

    Imported inside a helper rather than at module scope because the
    ``app`` package is not a dependency of this member — the twin of the
    seat's own ``TYPE_CHECKING`` import of ``bootstrap`` — and because the
    conftest path bootstrap has already put ``src/`` on ``sys.path`` by
    the time any test runs.
    """
    from app.modules import bootstrap as seat

    return seat
