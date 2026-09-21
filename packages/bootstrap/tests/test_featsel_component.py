"""Feature 182's plugin seam: composition, and the app-namespace seat.

Two contracts, both held from the side this member owns:

* **composition by convention** — the factory scans the workspace,
  imports this package, the ``@register(FEATSEL_COMPONENT_NAME)``
  builder fires, and the composed application carries a
  ``bootstrap-featsel`` component.  No registry, router, entry-points
  table or factory was edited to make that true, and this suite keeps
  it true under the two loader hazards ``test_component.py`` states:
  the synthetic-name copy (pin by name, module suffix and behaviour —
  decisively, bit-identical labels — never ``isinstance``) and the
  second composition (a ``@register`` outside ``__init__.py`` would
  fire once and silently drop out of every later ``create_app()``; the
  builder lives in ``__init__.py`` and the test asserts on the *second*
  application or it passes vacuously).

* **the seat** — :mod:`app.modules.bootstrap.featsel` answers exactly
  one question (*what is the composed feature selection world?*),
  imports the member only under ``TYPE_CHECKING``, and answers
  ``None`` — not an exception — when nothing is registered.  Its
  ``None`` is the world seats' ``None`` (a statement about
  composition), never the pool seat's (a statement about the
  deployment); the two must not be read through each other.

The fourth component joins three without disturbing them: the
hyperparameter world keeps its own name, the symbolic world its own
seat, the pool its own, and the growth is additive — a new domain takes
its own component rather than renaming a key every caller already
holds.
"""

from __future__ import annotations

import inspect
import os

import bootstrap as member
import pytest

from app.module_loader import create_app
from app.modules.bootstrap import featsel as seat


def _assert_is_the_featsel_world(component: object) -> None:
    """The composed component is the featsel world, across the loader's copies.

    Name, module suffix, then behaviour — the same discipline
    ``test_component.py`` states for the hyperparameter world, because
    the loader imports the member under a synthetic name and
    ``isinstance`` across the two copies cannot hold.  The behaviour
    check is the decisive one: the composed world answers the labels
    the canonically-imported builder's world answers, to the last bit.
    """
    assert type(component).__name__ == "FeatureSelectionWorld"
    assert type(component).__module__.endswith("bootstrap._featsel")

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
    for fact in ("world_id", "benchmark", "support", "theme_root", "axes", "seed"):
        assert getattr(component, fact) is not None, fact

    node_id = component.canonical_node()  # type: ignore[attr-defined]
    composed = component.label(node_id)  # type: ignore[attr-defined]
    direct = member.feature_selection_world().label(node_id)
    assert composed.r2_holdout == direct.r2_holdout
    assert composed.coefficients == direct.coefficients
    # And the published support is the composed world's own: the truth a
    # caller is scored against is the one the committed seed draws.
    # Compared by value, not ``==`` — the composed world's
    # FeatureSupport is the scanned copy's class and the member's is the
    # canonical copy's, so dataclass equality is False across the
    # boundary however identical the values, the same hazard the labels
    # above are pinned around.
    composed_support = component.support  # type: ignore[attr-defined]
    direct_support = member.support_for_seed(member.FEATSEL_SEED)
    assert (composed_support.intercept, composed_support.terms) == (
        direct_support.intercept,
        direct_support.terms,
    )
    assert composed_support.text == direct_support.text


# -- Composition -------------------------------------------------------------------


def test_the_member_registers_under_its_own_component_name() -> None:
    # A fourth component, not a second face on the first: the domain's
    # own name, spelled by §10.6's own tree, beside the hyperparameter
    # world's name rather than in place of it.
    assert member.FEATSEL_COMPONENT_NAME == "bootstrap-featsel"
    assert member.FEATSEL_COMPONENT_NAME != member.COMPONENT_NAME
    assert member.FEATSEL_WORLD_ID == "bootstrap-featsel-20260922"


def test_the_scanned_application_carries_the_featsel_world() -> None:
    app = create_app()
    assert "bootstrap-featsel" in app
    assert "bootstrap-featsel" in app.order
    _assert_is_the_featsel_world(app.get("bootstrap-featsel"))


def test_the_composed_world_is_bound_to_the_published_id_and_seed() -> None:
    world = create_app().get("bootstrap-featsel")
    assert world.world_id == member.FEATSEL_WORLD_ID  # type: ignore[attr-defined]
    assert world.seed == member.FEATSEL_SEED  # type: ignore[attr-defined]


def test_the_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard: a ``@register`` outside
    # ``__init__.py`` fires on the first composition of a process and
    # silently drops out of every later one.  Asserts on the second and
    # third applications specifically — a test that only looked at the
    # first would pass wherever the builder lived and catch nothing.
    first = create_app()
    second = create_app()
    third = create_app()
    _assert_is_the_featsel_world(first.get("bootstrap-featsel"))
    _assert_is_the_featsel_world(second.get("bootstrap-featsel"))
    _assert_is_the_featsel_world(third.get("bootstrap-featsel"))
    assert "bootstrap-featsel" in third.order


def test_the_growth_leaves_the_first_three_components_untouched() -> None:
    # The additive rule a shared registry imposes: the hyperparameter
    # world keeps its name and its world, the symbolic world keeps its
    # seat, and the pool keeps its own — a caller composed before this
    # domain existed reads the same answers after it ships.
    app = create_app()
    assert "bootstrap" in app
    assert type(app.get("bootstrap")).__name__ == "HyperparameterWorld"
    assert app.get("bootstrap").world_id == member.HYPERPARAMETER_WORLD_ID
    assert type(app.get("bootstrap-symreg")).__name__ == "SymbolicRegressionWorld"
    assert app.get("bootstrap-symreg").world_id == member.SYMREG_WORLD_ID
    # The pool composes as the deployment allows — ``None`` here, where
    # nothing names a database — and that is its own fact, not this
    # component's.
    assert "bootstrap-pool" in app
    assert app.get("bootstrap-pool") is None or type(app.get("bootstrap-pool")).__name__ == "BootstrapPool"


def test_the_builder_never_raises_and_takes_no_arguments() -> None:
    assert list(inspect.signature(member.feature_selection_world).parameters) == []
    first = member.feature_selection_world()
    second = member.feature_selection_world()
    assert first is not second  # a fresh world per call, not a shared one
    assert first.world_id == second.world_id


def test_the_builder_needs_no_environment() -> None:
    # A generated world's whole configuration is its seed: no deployment
    # state to degrade to, so composing it cannot fail — §10.6 keeps the
    # pool-size precondition on the compute side of the ledger, and a
    # builder that could fail would put it back on the calendar side.
    scrubbed = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("NULLIUS") and not key.startswith("BOOTSTRAP")
    }
    restore = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(scrubbed)
        world = member.feature_selection_world()
        root = world.canonical_node()
        assert world.label(root).r2_holdout == pytest.approx(
            member.feature_selection_world().label(root).r2_holdout, abs=0.0
        )
    finally:
        os.environ.clear()
        os.environ.update(restore)


def test_the_alias_is_an_ordinary_function_not_a_component() -> None:
    # The second spelling exists for scripts and sibling suites; it is
    # not registered, so it cannot put a second component of one name in
    # the registry and silently win a later import.
    assert member.build_feature_selection_world is member.feature_selection_world


# -- The app-namespace seat --------------------------------------------------------


def test_the_seats_names_line_up() -> None:
    # The seat's constant, the member's constant and one spelling: two
    # spellings of one name is exactly the drift a test is cheaper
    # than.
    assert seat.COMPONENT_NAME == member.FEATSEL_COMPONENT_NAME == "bootstrap-featsel"


def test_the_seat_exposes_nothing_but_the_composition_accessor() -> None:
    assert set(seat.__all__) == {"COMPONENT_NAME", "featsel_world_component"}
    for leaked in ("FeatureSelectionWorld", "FeatureSupport", "featsel_question_for"):
        assert leaked not in seat.__all__


def test_the_seat_returns_the_composed_world() -> None:
    world = seat.featsel_world_component()
    assert world is not None
    assert type(world).__name__ == "FeatureSelectionWorld"
    assert type(world).__module__.endswith("bootstrap._featsel")
    assert world.world_id == member.FEATSEL_WORLD_ID


def test_the_seat_answers_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception —
    # and this ``None`` is the world seats' ``None`` (composition), not
    # the pool seat's (deployment): nothing about it says a database.
    class Empty:
        def get(self, name: str) -> None:
            return None

    assert seat.featsel_world_component(Empty()) is None  # type: ignore[arg-type]
    # With an application handed in, the seat reads that application and
    # composes nothing of its own.
    app = create_app()
    assert seat.featsel_world_component(app) is app.get("bootstrap-featsel")
