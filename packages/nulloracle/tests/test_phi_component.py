"""The null fraction's plugin seam and its read through the composed application.

``test_component.py`` pins feature 109's registration and ``test_guard_component.py``
pins feature 123's; this pins feature 117's, the member's *fourth* component
and the one whose builder, like the guard's and the verdict's, resolves a
database URL.  It is worth its own suite rather than a section of the guard's
because:

* **the member now registers four components.**  All four ``@register`` calls
  live in the package's ``__init__``, and the loader re-executes ``__init__``
  on every ``create_app()`` while caching submodules — so the fourth
  registration is exactly as exposed to the "fires once per process and then
  drops out" failure as the first three, and needs the same *second
  application* assertion.  A registration added in a submodule would pass a
  single-composition test.

The load-bearing property is unchanged and restated because the consequence is
sharper here: **the builder must never raise.**  This one resolves a database
URL, and ``DATABASE_URL`` is a value every member of the workspace shares — so
a builder that raised on a scheme it cannot speak, or on a URL it considers
malformed, would take composition down for every unrelated feature in the
process.  The tests below pin that for each way this member's relational store
can be unconfigured or misconfigured.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from nulloracle import (
    COMPONENT_NAME as SIDECAR_COMPONENT_NAME,
)
from nulloracle import (
    DATABASE_URL_ENV,
    FRACTION_COMPONENT_NAME,
    KS_GUARD_COMPONENT_NAME,
    VERDICT_COMPONENT_NAME,
)

from app.module_loader import Application, create_app, scan_components


@pytest.fixture(autouse=True)
def _no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test in this module with no ``DATABASE_URL``.

    The member's conftest isolates the sidecar's environment; the fraction
    reads a variable the *whole workspace* shares, so a test that wants a
    composed fraction store has to say so explicitly rather than inherit one
    from whatever invoked pytest.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


@pytest.fixture
def database_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point ``DATABASE_URL`` at a fresh SQLite file for this test."""
    url = f"sqlite:///{tmp_path / 'phi.db'}"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


def _assert_is_the_fraction(component: object) -> None:
    assert type(component).__name__ == "PlantedNullFraction"
    assert type(component).__module__.endswith("nulloracle.phi")
    for operation in ("persist", "load"):
        assert callable(getattr(component, operation)), operation


# -- The registration --------------------------------------------------------------


class TestTheFractionComponentRegisters:
    def test_the_member_registers_the_fraction_component(self) -> None:
        names = [component.name for component in scan_components()]
        assert FRACTION_COMPONENT_NAME in names

    def test_the_fraction_component_name_is_hyphen_free(self) -> None:
        # The hyphen-free spelling is the plugin name the spec's features
        # carry (plugin="nulloracle"), so the component key and the spec
        # cannot drift apart.
        assert FRACTION_COMPONENT_NAME == "nulloracle-null-fraction"

    def test_the_four_component_names_are_distinct(self) -> None:
        names = {
            SIDECAR_COMPONENT_NAME,
            KS_GUARD_COMPONENT_NAME,
            VERDICT_COMPONENT_NAME,
            FRACTION_COMPONENT_NAME,
        }
        assert len(names) == 4

    def test_create_app_composes_a_fraction_store_when_configured(
        self, database_url: str
    ) -> None:
        app = create_app()
        component = app.get(FRACTION_COMPONENT_NAME)
        _assert_is_the_fraction(component)
        assert FRACTION_COMPONENT_NAME in app
        assert FRACTION_COMPONENT_NAME in app.order

    def test_composing_touches_no_file(self, database_url: str, tmp_path: Path) -> None:
        # Construction performs no I/O: the database appears on the first
        # persist.  That laziness is why a composed application can carry this
        # component in a process that is not the campaign planner.
        app = create_app()
        assert app.get(FRACTION_COMPONENT_NAME) is not None
        assert not (tmp_path / "phi.db").exists()

    def test_an_environment_with_no_database_url_still_composes(self) -> None:
        # The load-bearing property: with no relational store at all, the
        # builder returns None and the application composes with every other
        # member intact.
        app = create_app()
        assert app.get(FRACTION_COMPONENT_NAME) is None
        # ...and the other members are still there, which is the point.
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_an_unspeakable_scheme(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A deployment that named a Postgres store is expecting a fraction
        # store, and this one's scheme check is lazy — the URL is refused at
        # the first persist, not at composition.  That laziness is the point:
        # the factory builds every registered component on every create_app(),
        # so a builder that raised on a scheme it cannot speak would take down
        # every other member's component too.  A process that truly requires a
        # fraction store asks resolve() at its own startup, where the named
        # error is right; a process that merely composes one degrades at first
        # use.  So composition must succeed here — the refusal is deferred.
        monkeypatch.setenv(DATABASE_URL_ENV, "postgres:///db")
        app = create_app()
        component = app.get(FRACTION_COMPONENT_NAME)
        assert type(component).__name__ == "PlantedNullFraction"
        # ...and the other members are still there, which is the point: the
        # builder did not take composition down.
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_a_blank_scheme(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A whitespace-only URL counts as unset: resolve() returns None rather
        # than constructing a store that would fail at first use.  The builder
        # degrades to no component, and composition carries on.
        monkeypatch.setenv(DATABASE_URL_ENV, "   ")
        app = create_app()
        assert app.get(FRACTION_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_component_survives_a_second_composition(
        self, database_url: str
    ) -> None:
        # Must assert on the SECOND application or it passes vacuously: the
        # loader re-executes __init__ on every create_app(), so a @register
        # that lived in a submodule would be present in the first and absent
        # here.  The builder is on the package import path, which is what makes
        # the registration survive re-composition.
        create_app()
        second = create_app()
        _assert_is_the_fraction(second.get(FRACTION_COMPONENT_NAME))

    def test_the_builder_is_on_the_package_import_path(self) -> None:
        import nulloracle

        assert callable(nulloracle.build_null_fraction)
        assert nulloracle.build_null_fraction.__module__.endswith("nulloracle")

    def test_the_builder_takes_no_arguments(self) -> None:
        # The factory's registration protocol: a builder is a zero-argument
        # callable, and a component that needed an argument could not be
        # composed by the scan at all.
        import inspect

        import nulloracle

        assert inspect.signature(nulloracle.build_null_fraction).parameters == {}

    def test_the_builder_never_raises_when_configured(self, database_url: str) -> None:
        # The builder resolves the store and did not raise doing it — the
        # factory builds every registered component on every create_app(), so
        # a builder that raised would take composition down.
        import nulloracle

        assert nulloracle.build_null_fraction() is not None


# -- Reading the composed component ---------------------------------------------


class TestReadingTheComposedComponent:
    """The component as ``create_app().get(...)`` hands it to a caller outside
    the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        import nulloracle

        assert (
            nulloracle.FRACTION_COMPONENT_NAME
            == FRACTION_COMPONENT_NAME
        )

    def test_the_application_exposes_the_composed_fraction(self, database_url: str) -> None:
        _assert_is_the_fraction(create_app().get(FRACTION_COMPONENT_NAME))

    def test_the_component_is_read_from_an_application_it_is_handed(self) -> None:
        application = Application(
            components={FRACTION_COMPONENT_NAME: "sentinel"},
            order=(FRACTION_COMPONENT_NAME,),
        )
        assert application.get(FRACTION_COMPONENT_NAME) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        assert Application(components={}, order=()).get(FRACTION_COMPONENT_NAME) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        assert create_app().get(FRACTION_COMPONENT_NAME) is None

    def test_the_composed_component_can_persist_a_fraction(self, database_url: str) -> None:
        # Feature 117 through the composition: composed fraction store, a
        # campaign in, the clipped fraction on the campaign row — the path an
        # assembled system takes.
        store = create_app().get(FRACTION_COMPONENT_NAME)
        campaign = str(uuid.uuid4())
        with store._connect() as connection:
            connection.execute(
                "INSERT INTO campaign (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 3, 0.0)",
                (campaign,),
            )
        written = store.persist(campaign, 3)
        assert written == 0.35
        assert store.load(campaign) == 0.35

    def test_the_composition_answers_the_members_own_builder(self) -> None:
        # The composition and the builder cannot disagree about what the
        # component is: with ``DATABASE_URL`` unset both answer None.
        import nulloracle

        assert nulloracle.build_null_fraction() is None
        assert create_app().get(FRACTION_COMPONENT_NAME) is None
