"""Feature 110's plugin seam and its seat in the ``app`` namespace.

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

* **the seat is a twelfth module, and its name had to be chosen.**
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

import ast
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

SEAT_MODULE = "app.modules.nulloracle.schemaguard"

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


# -- The seat -----------------------------------------------------------------------


class TestTheSeatInTheAppNamespace:
    """``app/modules/nulloracle/schemaguard.py`` — the app package's way to
    the composed guard, without the app package importing the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        # Spelled twice on purpose — once in the member, once in the seat —
        # so the two cannot drift apart silently.
        import nulloracle

        from app.modules.nulloracle import schemaguard as seat

        assert (
            seat.COMPONENT_NAME
            == nulloracle.TREE_STORE_COMPONENT_NAME
            == TREE_STORE_COMPONENT_NAME
        )

    def test_the_seat_exposes_the_composed_guard(
        self, configured_store: tuple[str, Path]
    ) -> None:
        from app.modules.nulloracle.schemaguard import tree_store_guard_component

        _assert_is_the_tree_store_guard(tree_store_guard_component())

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.nulloracle.schemaguard import tree_store_guard_component

        application = Application(
            components={TREE_STORE_COMPONENT_NAME: "sentinel"},
            order=(TREE_STORE_COMPONENT_NAME,),
        )
        assert tree_store_guard_component(application) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        from app.modules.nulloracle.schemaguard import tree_store_guard_component

        empty = Application(components={}, order=())
        assert tree_store_guard_component(empty) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(
        self,
    ) -> None:
        from app.modules.nulloracle.schemaguard import tree_store_guard_component

        assert tree_store_guard_component() is None

    def test_the_seat_can_audit_a_lawful_store(
        self, configured_store: tuple[str, Path]
    ) -> None:
        # Feature 110 from the app namespace, the quiet half: an operator
        # script or nightly job asks the composed application for the guard
        # and learns §7.1's rule holds over a store that declares the
        # lawful five.
        from app.modules.nulloracle.schemaguard import tree_store_guard_component

        _url, path = configured_store
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(NODE_FIVE_CREATE)
        guard = tree_store_guard_component()
        assert guard is not None
        audit = guard.audit()
        assert audit.holds is True
        assert audit.columns == ("id", "parent_id", "campaign_id", "theme_root", "depth")

    def test_the_seat_can_refuse_a_broken_store(
        self, configured_store: tuple[str, Path]
    ) -> None:
        # The sentence's own path, end to end from the app namespace: the
        # column added out-of-band — the path that skipped every review —
        # and the composed guard pronouncing the ``is_null_column``
        # refusal on the live store.
        from app.modules.nulloracle.schemaguard import tree_store_guard_component

        _url, path = configured_store
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(NODE_FIVE_CREATE)
        guard = tree_store_guard_component()
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

    def test_the_seat_is_a_composition_read_and_not_a_second_api(self) -> None:
        # The seat's export list, pinned: a caller who wants the reviews or
        # the audit record imports the member, and a second spelling here
        # would be a second thing to keep in sync.  The one question this
        # module answers is *what is the composed tree-store guard?*
        from app.modules.nulloracle import schemaguard as seat

        assert set(seat.__all__) == {
            "COMPONENT_NAME",
            "tree_store_guard_component",
        }
        assert not hasattr(seat, "TreeStoreGuard")
        assert not hasattr(seat, "SchemaAudit")
        assert not hasattr(seat, "review_node_columns")
        assert not hasattr(seat, "review_ddl")
        assert not hasattr(seat, "audit_tree_store")
        assert not hasattr(seat, "IsNullColumnError")

    def test_the_sidecar_seat_is_untouched_by_the_twelfth_component(self) -> None:
        # This seat is a *submodule* beside feature 109's, precisely so that
        # the older seat's promise does not change: a caller that only wants
        # the sidecar never imports this module and sees the same two names
        # it always did.
        from app.modules import nulloracle as seat

        assert set(seat.__all__) == {"COMPONENT_NAME", "null_sidecar_component"}
        assert seat.COMPONENT_NAME == SIDECAR_COMPONENT_NAME

    def test_the_other_seats_are_untouched_by_the_twelfth_component(self) -> None:
        # Every older seat's promise is exactly what it was: a twelfth
        # submodule beside them does not change what a caller importing any
        # one of them sees.
        from app.modules.nulloracle import flipdepth as flip_seat
        from app.modules.nulloracle import irprob as irprob_seat
        from app.modules.nulloracle import keyalert as key_alert_seat
        from app.modules.nulloracle import ksguard as guard_seat
        from app.modules.nulloracle import plan as plan_seat
        from app.modules.nulloracle import selection as selection_seat

        assert set(flip_seat.__all__) == {"COMPONENT_NAME", "flip_depth_component"}
        assert set(irprob_seat.__all__) == {
            "COMPONENT_NAME",
            "true_ir_flip_depth_component",
        }
        assert set(key_alert_seat.__all__) == {
            "COMPONENT_NAME",
            "key_alert_component",
        }
        assert set(guard_seat.__all__) == {"COMPONENT_NAME", "ks_guard_component"}
        assert set(plan_seat.__all__) == {"COMPONENT_NAME", "plan_gate_component"}
        assert set(selection_seat.__all__) == {
            "COMPONENT_NAME",
            "type_r_selection_component",
        }

    def test_importing_the_seat_imports_no_member(self) -> None:
        # The seat exists so the ``app`` package does not depend on a
        # workspace member at import time.  Asserted on the seat's own
        # compiled form rather than on ``sys.modules`` — every other test in
        # this suite has already imported the member, so the module cache
        # cannot answer this — and on the *imports*, not on the text: the
        # member's name appears in a ``TYPE_CHECKING`` block, which never
        # executes, and a substring scan over the file cannot tell that from
        # a real import.
        import app.modules.nulloracle.schemaguard as module

        imported = _imported_names(module.__file__)
        assert "nulloracle" not in imported
        assert "app" in imported
        assert "nulloracle" in _imported_names(module.__file__, runtime_only=False)

    def test_the_seats_are_distinct_modules(self) -> None:
        import app.modules.nulloracle as sidecar_seat
        import app.modules.nulloracle.flipdepth as flip_seat
        import app.modules.nulloracle.irprob as irprob_seat
        import app.modules.nulloracle.keyalert as key_alert_seat
        import app.modules.nulloracle.ksguard as guard_seat
        import app.modules.nulloracle.phi as phi_seat
        import app.modules.nulloracle.plan as plan_seat
        import app.modules.nulloracle.schemaguard as tree_store_seat
        import app.modules.nulloracle.selection as selection_seat
        import app.modules.nulloracle.target as target_seat
        import app.modules.nulloracle.verdict as verdict_seat

        assert tree_store_seat is not sidecar_seat
        assert tree_store_seat is not guard_seat
        assert tree_store_seat is not phi_seat
        assert tree_store_seat is not verdict_seat
        assert tree_store_seat is not flip_seat
        assert tree_store_seat is not irprob_seat
        assert tree_store_seat is not selection_seat
        assert tree_store_seat is not plan_seat
        assert tree_store_seat is not target_seat
        assert tree_store_seat is not key_alert_seat
        assert tree_store_seat.__name__ == SEAT_MODULE

    def test_the_seat_answers_the_members_own_builder(self) -> None:
        # The seat and the builder cannot disagree about what the component
        # is: with nothing configured both answer None, which is the whole
        # reason the seat reads the factory rather than resolving the guard
        # itself.
        import nulloracle

        from app.modules.nulloracle.schemaguard import tree_store_guard_component

        assert nulloracle.build_tree_store_guard() is None
        assert tree_store_guard_component() is None
