"""The null fraction's plugin seam and its seat in the ``app`` namespace.

``test_component.py`` pins feature 109's registration and ``test_guard_component.py``
pins feature 123's; this pins feature 117's, the member's *fourth* component
and the one whose builder, like the guard's and the verdict's, resolves a
database URL.  Two things make it worth its own suite rather than a section of
the guard's:

* **the member now registers four components.**  All four ``@register`` calls
  live in the package's ``__init__``, and the loader re-executes ``__init__``
  on every ``create_app()`` while caching submodules — so the fourth
  registration is exactly as exposed to the "fires once per process and then
  drops out" failure as the first three, and needs the same *second
  application* assertion.  A registration added in a submodule would pass a
  single-composition test.
* **the seat is a fourth submodule.**  ``app/modules/nulloracle/`` was a
  single ``__init__.py`` while the member contributed one component; the
  fraction's seat lives beside the other three in
  ``app/modules/nulloracle/phi.py``.  The older seats' export lists must stay
  exactly as they were, and the new module must answer the same shape of
  question — *what is the composed X?* — with the same ``None``-not-an-
  exception degradation and the same refusal to become a second API.

The load-bearing property is unchanged and restated because the consequence is
sharper here: **the builder must never raise.**  This one resolves a database
URL, and ``DATABASE_URL`` is a value every member of the workspace shares — so
a builder that raised on a scheme it cannot speak, or on a URL it considers
malformed, would take composition down for every unrelated feature in the
process.  The tests below pin that for each way this member's relational store
can be unconfigured or misconfigured.
"""

from __future__ import annotations

import ast
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

SEAT_MODULE = "app.modules.nulloracle.phi"


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


def _imported_names(path: str | None, *, runtime_only: bool = True) -> set[str]:
    """The top-level modules ``path`` imports, optionally excluding typing blocks.

    Parsed rather than scanned: a module's *docstring* discusses the members it
    deliberately does not import — that is where the decision is argued — so a
    substring search over the file reports imports that are not there.

    With ``runtime_only`` (the default), names imported inside an
    ``if TYPE_CHECKING:`` guard are left out, because the guard is exactly the
    mechanism a module uses to name a type it does not depend on.  Which is the
    question this suite is actually asking: what does importing the seat bind,
    as opposed to what does it merely describe.
    """
    assert path is not None
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            guarded.update(
                sub.lineno for sub in ast.walk(node) if hasattr(sub, "lineno")
            )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if runtime_only and node.lineno in guarded:
                    continue
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            if runtime_only and node.lineno in guarded:
                continue
            imported.add(node.module.split(".")[0])
    return imported


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
        # carry (plugin="nulloracle"), so the component key, the app-namespace
        # seat and the spec cannot drift apart.
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


# -- The seat ----------------------------------------------------------------------


class TestTheSeatInTheAppNamespace:
    """``app/modules/nulloracle/phi.py`` — the app package's way to the
    composed fraction store, without the app package importing the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        # Spelled twice on purpose — once in the member, once in the seat —
        # so the two cannot drift apart silently.
        import nulloracle

        from app.modules.nulloracle import phi as phi_seat

        assert (
            phi_seat.COMPONENT_NAME
            == nulloracle.FRACTION_COMPONENT_NAME
            == FRACTION_COMPONENT_NAME
        )

    def test_the_seat_exposes_the_composed_fraction(self, database_url: str) -> None:
        from app.modules.nulloracle.phi import fraction_component

        _assert_is_the_fraction(fraction_component())

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.nulloracle.phi import fraction_component

        application = Application(
            components={FRACTION_COMPONENT_NAME: "sentinel"},
            order=(FRACTION_COMPONENT_NAME,),
        )
        assert fraction_component(application) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        from app.modules.nulloracle.phi import fraction_component

        assert fraction_component(Application(components={}, order=())) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        from app.modules.nulloracle.phi import fraction_component

        assert fraction_component() is None

    def test_the_seat_can_persist_a_fraction(self, database_url: str) -> None:
        # Feature 117 from the app namespace: composed fraction store, a
        # campaign in, the clipped fraction on the campaign row — the path an
        # assembled system takes.
        from app.modules.nulloracle.phi import fraction_component

        store = fraction_component()
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

    def test_the_seat_is_a_composition_read_and_not_a_second_api(self) -> None:
        # The seat's export list, pinned: a caller who has the store reaches
        # ``persist``/``load`` on it, and a second spelling here would be a
        # second thing to keep in sync.  The one question this module answers
        # is *what is the composed fraction store?* — and the answer is the
        # component, not a re-exported clip or store class.
        from app.modules.nulloracle import phi as seat

        assert set(seat.__all__) == {"COMPONENT_NAME", "fraction_component"}
        assert not hasattr(seat, "PlantedNullFraction")
        assert not hasattr(seat, "null_fraction")

    def test_the_sidecar_seat_is_untouched_by_the_fourth_component(self) -> None:
        # The fraction's seat is a *submodule* beside feature 109's, precisely
        # so that the older seat's promise does not change: a caller that only
        # wants the sidecar never imports the fraction's module and sees the
        # same two names it always did.
        from app.modules import nulloracle as seat

        assert set(seat.__all__) == {"COMPONENT_NAME", "null_sidecar_component"}
        assert seat.COMPONENT_NAME == SIDECAR_COMPONENT_NAME

    def test_the_verdict_seat_is_untouched_by_the_fourth_component(self) -> None:
        # And feature 124's seat keeps its own two names, unchanged.
        from app.modules.nulloracle import verdict as verdict_seat

        assert set(verdict_seat.__all__) == {"COMPONENT_NAME", "verdict_component"}

    def test_the_seats_are_distinct_modules(self) -> None:
        import app.modules.nulloracle as sidecar_seat
        import app.modules.nulloracle.ksguard as guard_seat
        import app.modules.nulloracle.phi as phi_seat
        import app.modules.nulloracle.verdict as verdict_seat

        assert phi_seat is not sidecar_seat
        assert phi_seat is not guard_seat
        assert phi_seat is not verdict_seat
        assert phi_seat.__name__ == SEAT_MODULE

    def test_importing_the_seat_imports_no_member(self) -> None:
        # The seat exists so the ``app`` package does not depend on a workspace
        # member at import time.  Asserted on the seat's own compiled form
        # rather than on ``sys.modules`` — every other test in this suite has
        # already imported the member, so the module cache cannot answer this —
        # and on the *imports*, not on the text: the member's name appears in a
        # ``TYPE_CHECKING`` block, which never executes, and a substring scan
        # over the file cannot tell that from a real import.
        import app.modules.nulloracle.phi as module

        imported = _imported_names(module.__file__)
        assert "nulloracle" not in imported
        assert "app" in imported
        assert "nulloracle" in _imported_names(module.__file__, runtime_only=False)

    def test_the_seat_answers_the_members_own_builder(self) -> None:
        # The seat and the builder cannot disagree about what the component is:
        # with ``DATABASE_URL`` unset both answer None, and with it set both
        # hand back the same kind of object — which is the whole reason the
        # seat reads the factory rather than resolving the store itself.
        import nulloracle

        from app.modules.nulloracle.phi import fraction_component

        assert nulloracle.build_null_fraction() is None
        assert fraction_component() is None
