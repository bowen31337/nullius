"""Feature 120's plugin seam and its read through the composed application.

``test_component.py`` pins feature 109's registration, ``test_guard_component.py``
feature 123's, ``test_phi_component.py`` feature 117's, ``test_flip_depth_component.py``
feature 119's; this pins feature 120's — the member's *seventh* component, and
the second whose builder resolves a database URL for the flip-depth family.
It is worth its own suite rather than a section of feature 119's because:

* **the member now registers seven components.**  All seven ``@register`` calls
  live in the package's ``__init__``, and the loader re-executes ``__init__`` on
  every ``create_app()`` while caching submodules — so the seventh registration
  is exactly as exposed to the "fires once per process and then drops out"
  failure as the first six, and needs the same *second application* assertion.
  A registration added in a submodule would pass a single-composition test.

Two feature-120-specific properties get their own tests, because they are what
separates this component from feature 119's:

* **the two flip-depth components are distinct names holding different things.**
  Feature 119's carries the store that draws a geometric from a probability the
  *caller* supplies; this one carries the store that derives that probability
  from a branch's true information ratio and its campaign.  A deployment can
  legitimately carry either without the other, so the two must not collapse onto
  one name.

* **the composed store answers *what does this campaign draw?* with no database.**
  The campaign's shift is a function of its id, so the pure ``distribution()``
  call works on a composed component whose file has never been opened — which is
  what makes the component usable in a report or a plan.

The load-bearing property is unchanged and restated because the consequence is
sharper here: **the builder must never raise.**  It resolves ``DATABASE_URL``, a
value the whole workspace shares, so a builder that raised on a scheme it cannot
speak would take composition down for every unrelated feature in the process.
The tests below pin that for each way this member's relational store can be
unconfigured or misconfigured.
"""

from __future__ import annotations

import inspect
import uuid
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    FLIP_DEPTH_COMPONENT_NAME,
    FRACTION_COMPONENT_NAME,
    KS_GUARD_COMPONENT_NAME,
    RESOLUTION_COMPONENT_NAME,
    TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
    VERDICT_COMPONENT_NAME,
)
from nulloracle import (
    COMPONENT_NAME as SIDECAR_COMPONENT_NAME,
)

from app.module_loader import Application, create_app, scan_components

#: A campaign id that is a canonical UUID, so a test about the *seam* is never
#: accidentally about id validation.
CAMPAIGN = "7c2e1a40-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test in this module with no ``DATABASE_URL``.

    The member's conftest isolates the sidecar's environment; this store reads a
    variable the *whole workspace* shares, so a test that wants a composed store
    has to say so explicitly rather than inherit one from whatever invoked
    pytest.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


@pytest.fixture
def database_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point ``DATABASE_URL`` at a fresh SQLite file for this test."""
    url = f"sqlite:///{tmp_path / 'irprob.db'}"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


def _assert_is_the_true_ir_flip_depth(component: object) -> None:
    assert type(component).__name__ == "TrueIRFlipDepth"
    assert type(component).__module__.endswith("nulloracle.irprob")
    for operation in ("draw", "distribution", "distribution_for_node"):
        assert callable(getattr(component, operation)), operation


# -- The registration ---------------------------------------------------------------


class TestTheTrueIRFlipDepthComponentRegisters:
    def test_the_member_registers_the_true_ir_flip_depth_component(self) -> None:
        names = [component.name for component in scan_components()]
        assert TRUE_IR_FLIP_DEPTH_COMPONENT_NAME in names

    def test_the_component_name_is_hyphen_free(self) -> None:
        # The hyphen-free spelling is the plugin name the spec's features carry
        # (plugin="nulloracle"), so the component key and the spec cannot drift
        # apart.
        assert TRUE_IR_FLIP_DEPTH_COMPONENT_NAME == "nulloracle-true-ir-flip-depth"

    def test_the_seven_component_names_are_distinct(self) -> None:
        # Feature 120's component is not a second component under feature 119's
        # name: the two hold different things (a draw from a supplied
        # probability, and the map that derives the probability), and a
        # deployment can carry either without the other.
        names = {
            SIDECAR_COMPONENT_NAME,
            KS_GUARD_COMPONENT_NAME,
            VERDICT_COMPONENT_NAME,
            FRACTION_COMPONENT_NAME,
            FLIP_DEPTH_COMPONENT_NAME,
            RESOLUTION_COMPONENT_NAME,
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
        }
        assert len(names) == 7
        assert TRUE_IR_FLIP_DEPTH_COMPONENT_NAME != FLIP_DEPTH_COMPONENT_NAME

    def test_create_app_composes_a_store_when_configured(self, database_url: str) -> None:
        app = create_app()
        _assert_is_the_true_ir_flip_depth(app.get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME))
        assert TRUE_IR_FLIP_DEPTH_COMPONENT_NAME in app
        assert TRUE_IR_FLIP_DEPTH_COMPONENT_NAME in app.order

    def test_composing_touches_no_file(self, database_url: str, tmp_path: Path) -> None:
        # Construction performs no I/O: the database appears on the first draw.
        # That laziness is why a composed application can carry this component in
        # a process that is not the campaign loop.
        app = create_app()
        assert app.get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME) is not None
        assert not (tmp_path / "irprob.db").exists()

    def test_an_environment_with_no_database_url_still_composes(self) -> None:
        # The load-bearing property: with no relational store at all, the builder
        # returns None and the application composes with every other member
        # intact.
        app = create_app()
        assert app.get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_an_unspeakable_scheme(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A deployment that named a Postgres store is expecting a store, and this
        # one's scheme check is lazy — the URL is refused at the first draw, not
        # at composition.  That laziness is the point: the factory builds every
        # registered component on every create_app(), so a builder that raised on
        # a scheme it cannot speak would take down every other member's component
        # too.
        monkeypatch.setenv(DATABASE_URL_ENV, "postgres:///db")
        app = create_app()
        component = app.get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME)
        assert type(component).__name__ == "TrueIRFlipDepth"
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_a_blank_scheme(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A whitespace-only URL counts as unset: resolve() returns None rather
        # than constructing a store that would fail at first use.
        monkeypatch.setenv(DATABASE_URL_ENV, "   ")
        app = create_app()
        assert app.get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_component_survives_a_second_composition(self, database_url: str) -> None:
        # Must assert on the SECOND application or it passes vacuously: the
        # loader re-executes __init__ on every create_app(), so a @register that
        # lived in a submodule would be present in the first and absent here.
        create_app()
        second = create_app()
        _assert_is_the_true_ir_flip_depth(second.get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME))

    def test_the_builder_is_on_the_package_import_path(self) -> None:
        import nulloracle

        assert callable(nulloracle.build_true_ir_flip_depth)
        assert nulloracle.build_true_ir_flip_depth.__module__.endswith("nulloracle")

    def test_the_builder_takes_no_arguments(self) -> None:
        # The factory's registration protocol: a builder is a zero-argument
        # callable, and a component that needed an argument could not be composed
        # by the scan at all.
        import nulloracle

        assert inspect.signature(nulloracle.build_true_ir_flip_depth).parameters == {}

    def test_the_builder_never_raises_when_configured(self, database_url: str) -> None:
        import nulloracle

        assert nulloracle.build_true_ir_flip_depth() is not None

    def test_composing_it_leaves_the_guard_adjacent_to_the_sidecar(
        self, database_url: str
    ) -> None:
        # The names are sorted, and feature 123's guard must stay immediately
        # after the sidecar in ``app.order``; the ``true-ir-`` prefix places this
        # component after every existing family, so the adjacency is untouched.
        app = create_app()
        order = list(app.order)
        assert order.index(KS_GUARD_COMPONENT_NAME) == order.index(SIDECAR_COMPONENT_NAME) + 1


# -- Reading the composed store ----------------------------------------------------


class TestReadingTheComposedStore:
    """``create_app().get("nulloracle-true-ir-flip-depth")`` — the way to the
    composed store from outside the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        import nulloracle

        assert nulloracle.TRUE_IR_FLIP_DEPTH_COMPONENT_NAME == TRUE_IR_FLIP_DEPTH_COMPONENT_NAME == "nulloracle-true-ir-flip-depth"

    def test_the_application_exposes_the_composed_store(self, database_url: str) -> None:
        _assert_is_the_true_ir_flip_depth(create_app().get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME))

    def test_the_component_is_read_from_an_application_it_is_handed(self) -> None:
        application = Application(
            components={TRUE_IR_FLIP_DEPTH_COMPONENT_NAME: "sentinel"},
            order=(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,),
        )
        assert application.get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        assert Application(components={}, order=()).get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        assert create_app().get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME) is None

    def test_the_composed_store_can_report_a_distribution_with_no_database(
        self, database_url: str, tmp_path: Path
    ) -> None:
        # The property that separates this component from feature 119's: the
        # campaign's shift is a function of its id, so *what does this campaign
        # draw?* is answerable from a composed component whose file has never
        # been opened.
        store = create_app().get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME)
        distribution = store.distribution(CAMPAIGN, 1.0)
        assert 0.0 < distribution.probability < 1.0
        assert distribution.campaign_id == CAMPAIGN
        assert not (tmp_path / "irprob.db").exists()

    def test_the_composed_store_can_draw_a_depth(self, database_url: str) -> None:
        # Feature 120 through the composition, end to end: composed store, a
        # branch's true IR in, the drawn depth on the node's column — the path an
        # assembled campaign loop takes.
        store = create_app().get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME)
        node = str(uuid.uuid4())
        with store._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} "
                "(id, campaign_type, workspace_count, null_fraction) "
                "VALUES (?, 'Type-D', 40, 0.15)",
                (CAMPAIGN,),
            )
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, 'macro', 2)",
                (node, CAMPAIGN),
            )
        depth = store.draw(node, 0.9)
        assert depth >= 1
        assert store.draw(node, 0.9) == depth

    def test_the_composition_answers_the_members_own_builder(self) -> None:
        # The composition and the builder cannot disagree about what the
        # component is: with ``DATABASE_URL`` unset both answer None.
        import nulloracle

        assert nulloracle.build_true_ir_flip_depth() is None
        assert create_app().get(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME) is None
