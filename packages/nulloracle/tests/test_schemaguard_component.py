"""Feature 110's plugin seam and its read through the composed application.

``test_component.py`` pins feature 109's registration, ``test_guard_component.py``
feature 123's, ``test_verdict_component.py`` feature 124's,
``test_phi_component.py`` feature 117's, ``test_flip_depth_component.py``
feature 119's, ``test_irprob_component.py`` feature 120's,
``test_type_r_selection_component.py`` feature 118's,
``test_plan_component.py`` feature 122's, ``test_target_component.py``
features 112-114's and ``test_key_alert_component.py`` feature 111's; this
pins feature 110's — the member's *twelfth* component, and the first whose
component holds no data at all: it is the standing audit over a *schema*.

Three things make it worth its own suite rather than a section of another's:

* **the member now registers twelve components, and every new one re-runs
  the registration trap.**  All twelve ``@register`` calls live in the
  package's ``__init__``, and the loader re-executes ``__init__`` on every
  ``create_app()`` while caching submodules — so a registration that lived
  in ``nulloracle.schemaguard`` would fire on the first composition of a
  process and silently drop out of every later one.  The
  second-application assertion below is what catches that, and a
  single-composition test would pass for it.

* **``None`` means something new here, and the tests must hold it apart
  from the two things it must never be read as.**  An unconfigured guard
  composes ``None`` — that is a statement about the *deployment* (no
  ``DATABASE_URL``, so no store to audit).  It is not *"the barrier holds"*
  — that is a fact about a *store*, answerable only by the audit — and the
  end-to-end tests below exercise both facts separately so the difference
  is pinned by behaviour rather than asserted in a docstring.

* **the component's name had to be chosen.**
  ``app.order`` is name-sorted, and feature 123's guard must stay
  immediately after the sidecar in it; a component sorting between
  ``nulloracle`` and ``nulloracle-ks-guard`` would silently break that
  adjacency.  The ``tree-`` prefix lands after ``target-`` and before
  ``true-ir-`` — the narrow gap between feature 112's route and feature
  120's store — and the ordering assertions below pin both directions so
  the choice cannot be unmade by a rename nobody reviews.

The load-bearing property is unchanged and restated because the
consequence is the same as every sibling's: **the builder must never
raise.**  It resolves ``DATABASE_URL``, a variable the whole workspace
shares, so a builder that raised on a scheme it cannot speak would take
composition down for every unrelated feature in the process — and this
builder has a second reason the others do not: a guard that broke
composition would make the application *less* deployable because the
audit existed, which is backwards.
"""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from nulloracle import (
    COMPONENT_NAME as SIDECAR_COMPONENT_NAME,
)
from nulloracle import (
    DATABASE_URL_ENV,
    FLIP_DEPTH_COMPONENT_NAME,
    FRACTION_COMPONENT_NAME,
    KEY_ALERT_COMPONENT_NAME,
    KEY_REF_ENV,
    KS_GUARD_COMPONENT_NAME,
    PLAN_COMPONENT_NAME,
    RESOLUTION_COMPONENT_NAME,
    SIDECAR_PATH_ENV,
    TARGET_COMPONENT_NAME,
    TREE_STORE_COMPONENT_NAME,
    TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
    TYPE_R_COMPONENT_NAME,
    VERDICT_COMPONENT_NAME,
)

from app.module_loader import Application, create_app, scan_components

#: The lawful five feature 97 names — the declaration a clean store carries.
NODE_FIVE_CREATE = (
    "CREATE TABLE node ("
    "id UUID NOT NULL PRIMARY KEY, "
    "parent_id UUID, "
    "campaign_id UUID NOT NULL, "
    "theme_root TEXT NOT NULL, "
    "depth INT NOT NULL)"
)


@pytest.fixture(autouse=True)
def _no_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test in this module with nothing configured.

    The member's conftest isolates the sidecar's environment; this
    component's builder reads ``DATABASE_URL``, a variable the whole
    workspace shares, so a test that wants a composed guard has to say so
    explicitly rather than inherit a configuration from whatever invoked
    pytest.
    """
    for name in (DATABASE_URL_ENV, SIDECAR_PATH_ENV, KEY_REF_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def configured_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    """A ``DATABASE_URL`` naming a fresh SQLite location — the store to audit."""
    path = tmp_path / "tree.db"
    url = f"sqlite:///{path}"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url, path


def _assert_is_the_tree_store_guard(component: object) -> None:
    # The two-module-worlds wrinkle every sibling's suite states: the
    # factory's scan imports the member under a synthetic name, so identity
    # is asserted on the type's own name and module tail rather than with
    # ``isinstance`` against the package's class.
    assert type(component).__name__ == "TreeStoreGuard"
    assert type(component).__module__.endswith("nulloracle.schemaguard")
    assert callable(component.audit)
    assert callable(component.columns)


# -- The registration ---------------------------------------------------------------


class TestTheTreeStoreGuardComponentRegisters:
    def test_the_member_registers_the_tree_store_guard_component(self) -> None:
        names = [component.name for component in scan_components()]
        assert TREE_STORE_COMPONENT_NAME in names

    def test_the_component_name_is_the_expected_spelling(self) -> None:
        # The hyphen-free ``nulloracle`` prefix is the plugin name the spec's
        # features carry, and the ``tree-`` family prefix places this
        # component after ``target-`` and before ``true-ir-`` in the
        # name-sorted ``app.order`` — the one narrow gap left between the
        # families, and the placement that leaves feature 123's guard
        # immediately after the sidecar, pinned by the ordering assertions
        # below.
        assert TREE_STORE_COMPONENT_NAME == "nulloracle-tree-store-guard"

    def test_the_twelve_component_names_are_distinct(self) -> None:
        # Feature 110's component is not a second component under any other
        # name: the twelve hold different things on different lifecycles
        # (§7.1's sealed file, the guard journal, the verdict, the fraction,
        # the flip depth, the Type-D resolution, the true-IR probability,
        # the Type-R selection, the planning gate, the target route, the key
        # alert and this schema audit), and a deployment can carry any of
        # them without the others.
        names = {
            SIDECAR_COMPONENT_NAME,
            KS_GUARD_COMPONENT_NAME,
            VERDICT_COMPONENT_NAME,
            FRACTION_COMPONENT_NAME,
            FLIP_DEPTH_COMPONENT_NAME,
            RESOLUTION_COMPONENT_NAME,
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
            TYPE_R_COMPONENT_NAME,
            PLAN_COMPONENT_NAME,
            TARGET_COMPONENT_NAME,
            KEY_ALERT_COMPONENT_NAME,
            TREE_STORE_COMPONENT_NAME,
        }
        assert len(names) == 12
        assert TREE_STORE_COMPONENT_NAME not in {
            KS_GUARD_COMPONENT_NAME,
            TARGET_COMPONENT_NAME,
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
        }

    def test_create_app_composes_a_guard_when_a_store_is_configured(
        self, configured_store: tuple[str, Path]
    ) -> None:
        app = create_app()
        _assert_is_the_tree_store_guard(app.get(TREE_STORE_COMPONENT_NAME))
        assert TREE_STORE_COMPONENT_NAME in app
        assert TREE_STORE_COMPONENT_NAME in app.order

    def test_composing_touches_no_file(self, configured_store: tuple[str, Path]) -> None:
        # Construction performs no I/O: the guard resolves its path on first
        # use, so a composed application never opens — and this audit, unlike
        # the member's stores, never *creates* — a database at composition
        # time.  A deployment can compose the guard against a store that is
        # spun up later, and composing it against a store that never appears
        # changes nothing on disk.
        _url, path = configured_store
        app = create_app()
        assert app.get(TREE_STORE_COMPONENT_NAME) is not None
        assert not path.exists()

    def test_an_environment_with_no_database_url_still_composes(self) -> None:
        # The load-bearing property, with the state it must not be read as
        # stated beside it: no store named, so no guard — and ``None`` is a
        # statement about the deployment, never *"the barrier holds"*.  A
        # caller that needed the audit is the one that must not find itself
        # in this state; the application composes either way.
        app = create_app()
        assert app.get(TREE_STORE_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_an_unspeakable_scheme(
        self, configured_store: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A deployment that named a Postgres store is expecting an audit, and
        # this one's scheme check is lazy — the URL is refused at the first
        # audit, not at composition.  That laziness is the point: the factory
        # builds every registered component on every create_app(), so a
        # builder that raised on a scheme it cannot speak would take down
        # every other member's component too.
        monkeypatch.setenv(DATABASE_URL_ENV, "postgres:///db")
        app = create_app()
        component = app.get(TREE_STORE_COMPONENT_NAME)
        assert type(component).__name__ == "TreeStoreGuard"
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_a_blank_scheme(
        self, configured_store: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A whitespace-only URL counts as unset: resolve() returns None
        # rather than constructing a guard that would fail at first use.
        monkeypatch.setenv(DATABASE_URL_ENV, "   ")
        app = create_app()
        assert app.get(TREE_STORE_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_component_survives_a_second_composition(
        self, configured_store: tuple[str, Path]
    ) -> None:
        # Must assert on the SECOND application or it passes vacuously: the
        # loader re-executes __init__ on every create_app(), so a @register
        # that lived in ``nulloracle.schemaguard`` would be present in the
        # first and absent here.
        create_app()
        second = create_app()
        _assert_is_the_tree_store_guard(second.get(TREE_STORE_COMPONENT_NAME))

    def test_the_builder_is_on_the_package_import_path(self) -> None:
        import nulloracle

        assert callable(nulloracle.build_tree_store_guard)
        assert nulloracle.build_tree_store_guard.__module__.endswith("nulloracle")

    def test_the_builder_takes_no_arguments(self) -> None:
        # The factory's registration protocol: a builder is a zero-argument
        # callable, and a component that needed an argument could not be
        # composed by the scan at all.
        import nulloracle

        assert inspect.signature(nulloracle.build_tree_store_guard).parameters == {}

    def test_the_builder_never_raises_when_configured(
        self, configured_store: tuple[str, Path]
    ) -> None:
        import nulloracle

        assert nulloracle.build_tree_store_guard() is not None

    def test_the_builder_resolves_no_sidecar(self, configured_store: tuple[str, Path]) -> None:
        # The audit is over the tree store's *schema*, and the schema has
        # nothing to do with §7.1's file: the guard must compose wherever a
        # relational store is named, in a deployment that holds no sidecar
        # key and never will — the writer's store and the reader's secret
        # are different lifecycles, which is the whole reason this is a
        # twelfth name rather than a feature of the sidecar's.
        import nulloracle

        assert nulloracle.build_tree_store_guard() is not None

    def test_composing_it_leaves_the_guard_adjacent_to_the_sidecar(
        self, configured_store: tuple[str, Path]
    ) -> None:
        # The names are sorted, and feature 123's guard must stay immediately
        # after the sidecar in ``app.order``; the ``tree-`` prefix places
        # this component far after both, so the adjacency is untouched.
        app = create_app()
        order = list(app.order)
        assert order.index(KS_GUARD_COMPONENT_NAME) == order.index(SIDECAR_COMPONENT_NAME) + 1

    def test_the_guard_sorts_after_the_target_and_key_alert_families(
        self, configured_store: tuple[str, Path]
    ) -> None:
        # One direction of the prefix choice: after ``target-`` (and after
        # the ``sidecar-`` and every earlier family), so the guard could
        # never land between the sidecar and feature 123's guard.
        app = create_app()
        order = list(app.order)
        assert order.index(TREE_STORE_COMPONENT_NAME) > order.index(
            TARGET_COMPONENT_NAME
        )
        assert order.index(TREE_STORE_COMPONENT_NAME) > order.index(
            KEY_ALERT_COMPONENT_NAME
        )

    def test_the_guard_sorts_before_the_true_ir_and_type_families(
        self, configured_store: tuple[str, Path]
    ) -> None:
        # The other direction, pinned with it: the ``tree-`` family lands
        # before ``true-ir-`` and ``type-*`` (``tre`` < ``tru`` < ``typ``),
        # in the one gap the sorted names had left.  A rename that moved it
        # either way crosses a family boundary, and these two assertions
        # are the review it cannot skip.
        app = create_app()
        order = list(app.order)
        assert order.index(TREE_STORE_COMPONENT_NAME) < order.index(
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME
        )
        assert order.index(TREE_STORE_COMPONENT_NAME) < order.index(
            TYPE_R_COMPONENT_NAME
        )
        assert order.index(TREE_STORE_COMPONENT_NAME) < order.index(
            RESOLUTION_COMPONENT_NAME
        )


# -- Reading the composed component ---------------------------------------------


class TestReadingTheComposedComponent:
    """The component as ``create_app().get(...)`` hands it to a caller outside
    the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        import nulloracle

        assert (
            nulloracle.TREE_STORE_COMPONENT_NAME
            == TREE_STORE_COMPONENT_NAME
        )

    def test_the_application_exposes_the_composed_guard(
        self, configured_store: tuple[str, Path]
    ) -> None:
        _assert_is_the_tree_store_guard(create_app().get(TREE_STORE_COMPONENT_NAME))

    def test_the_component_is_read_from_an_application_it_is_handed(self) -> None:
        application = Application(
            components={TREE_STORE_COMPONENT_NAME: "sentinel"},
            order=(TREE_STORE_COMPONENT_NAME,),
        )
        assert application.get(TREE_STORE_COMPONENT_NAME) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        empty = Application(components={}, order=())
        assert empty.get(TREE_STORE_COMPONENT_NAME) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(
        self,
    ) -> None:
        assert create_app().get(TREE_STORE_COMPONENT_NAME) is None

    def test_the_composed_component_can_audit_a_lawful_store(
        self, configured_store: tuple[str, Path]
    ) -> None:
        # Feature 110 through the composition, the quiet half: an operator
        # script or nightly job asks the composed application for the guard
        # and learns §7.1's rule holds over a store that declares the
        # lawful five.
        _url, path = configured_store
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(NODE_FIVE_CREATE)
        guard = create_app().get(TREE_STORE_COMPONENT_NAME)
        assert guard is not None
        audit = guard.audit()
        assert audit.holds is True
        assert audit.columns == ("id", "parent_id", "campaign_id", "theme_root", "depth")

    def test_the_composed_component_can_refuse_a_broken_store(
        self, configured_store: tuple[str, Path]
    ) -> None:
        # The sentence's own path, end to end through the composition: the
        # column added out-of-band — the path that skipped every review —
        # and the composed guard pronouncing the ``is_null_column``
        # refusal on the live store.
        _url, path = configured_store
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(NODE_FIVE_CREATE)
        guard = create_app().get(TREE_STORE_COMPONENT_NAME)
        assert guard is not None and guard.audit().holds is True
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("ALTER TABLE node ADD COLUMN is_null BOOLEAN")
        # Caught by name, not by ``pytest.raises(IsNullColumnError)``: the
        # composed guard's class is the *scanned* copy (the loader imports
        # each member under a synthetic module name), so the exception it
        # raises is not this suite's class object — the interoperability
        # fact ``test_guard_component.py`` documents, applying here
        # unchanged.
        with pytest.raises(Exception) as raised:
            guard.audit()
        assert type(raised.value).__name__ == "IsNullColumnError"
        assert str(raised.value).startswith("is_null_column")

    def test_the_composition_answers_the_members_own_builder(self) -> None:
        # The composition and the builder cannot disagree about what the
        # component is: unconfigured, both answer None.
        import nulloracle

        assert nulloracle.build_tree_store_guard() is None
        assert create_app().get(TREE_STORE_COMPONENT_NAME) is None
