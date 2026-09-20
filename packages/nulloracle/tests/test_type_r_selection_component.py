"""Feature 118's plugin seam and its seat in the ``app`` namespace.

``test_component.py`` pins feature 109's registration, ``test_guard_component.py``
feature 123's, ``test_phi_component.py`` feature 117's, ``test_flip_depth_component.py``
feature 119's, ``test_irprob_component.py`` feature 120's; this pins feature
118's — the member's *eighth* component, and the first whose builder needs two
things to resolve rather than one.

Three things make it worth its own suite rather than a section of feature 120's:

* **the member now registers eight components, and the eighth is the one most
  exposed to the registration trap.**  All eight ``@register`` calls live in the
  package's ``__init__``, and the loader re-executes ``__init__`` on every
  ``create_app()`` while caching submodules — so a registration that lived in
  ``nulloracle.selection`` would fire on the first composition of a process and
  silently drop out of every later one.  The second-application assertion below
  is what catches that, and a single-composition test would pass for it.

* **the seat needs two composed halves.**  Every other seat answers for a
  component that resolves from a single source.  This one's store reads the tree
  and the campaign row from a relational database *and* seals the drawn status
  into §7.1's sidecar, so the composed component exists only where both resolve
  — and ``None`` therefore means *one of the two is unconfigured*, never *the
  campaign planted no nulls*.  The half-configured cases are pinned
  individually, because a builder that resolved only one half would compose a
  store that can draw but not persist, or persist but not draw.

* **the seat is an eighth submodule.**  ``app/modules/nulloracle/`` was a single
  ``__init__.py`` while the member contributed one component; the older seats'
  export lists must stay exactly as they were, and the new module must answer
  the same shape of question — *what is the composed X?* — with the same
  ``None``-not-an-exception degradation and the same refusal to become a second
  API.

The load-bearing property is unchanged and restated because the consequence is
sharper here: **the builder must never raise.**  It resolves ``DATABASE_URL``
and the sidecar's two variables, all of which the whole workspace shares, so a
builder that raised on a scheme it cannot speak or a key reference it cannot
parse would take composition down for every unrelated feature in the process.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    FLIP_DEPTH_COMPONENT_NAME,
    FRACTION_COMPONENT_NAME,
    KEY_REF_ENV,
    KS_GUARD_COMPONENT_NAME,
    NODE_TABLE,
    RESOLUTION_COMPONENT_NAME,
    SIDECAR_PATH_ENV,
    TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
    TYPE_R_COMPONENT_NAME,
    VERDICT_COMPONENT_NAME,
)
from nulloracle import (
    COMPONENT_NAME as SIDECAR_COMPONENT_NAME,
)

from app.module_loader import Application, create_app, scan_components

SEAT_MODULE = "app.modules.nulloracle.selection"

#: The 32-byte test key the member's conftest and suite use. Not a secret and
#: not derived from anything: every assertion about "the right key opens it" is
#: really an assertion that the same bytes were used twice.
TEST_KEY_HEX = "0f" * 32

#: A campaign id that is a canonical UUID, so a test about the *seam* is never
#: accidentally about id validation.
CAMPAIGN = "7c2e1a40-0000-4000-8000-000000000118"

#: A node id in the same spirit.
NODE = "7c2e1a40-0000-4000-8000-000000000119"


@pytest.fixture(autouse=True)
def _no_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test in this module with neither half configured.

    The member's conftest isolates the sidecar's environment — but this
    component's builder *reads* that environment, so a test that wants a
    composed store has to say so explicitly rather than inherit a configuration
    from whatever invoked pytest.  The database URL is dropped here too: it is a
    variable the whole workspace shares.
    """
    for name in (DATABASE_URL_ENV, SIDECAR_PATH_ENV, KEY_REF_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def both_halves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, Path]:
    """Configure a relational store *and* a sidecar: a composeable deployment."""
    url = f"sqlite:///{tmp_path / 'selection.db'}"
    path = tmp_path / "z0" / "null" / "sidecar.enc"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    monkeypatch.setenv(SIDECAR_PATH_ENV, str(path))
    monkeypatch.setenv(KEY_REF_ENV, f"hex:{TEST_KEY_HEX}")
    return url, path


def _assert_is_the_type_r_selection(component: object) -> None:
    assert type(component).__name__ == "TypeRSelection"
    assert type(component).__module__.endswith("nulloracle.selection")
    for operation in ("persist", "load", "null_status"):
        assert callable(getattr(component, operation)), operation


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


class TestTheTypeRSelectionComponentRegisters:
    def test_the_member_registers_the_type_r_selection_component(self) -> None:
        names = [component.name for component in scan_components()]
        assert TYPE_R_COMPONENT_NAME in names

    def test_the_component_name_is_the_expected_spelling(self) -> None:
        # The hyphen-free spelling is the plugin name the spec's features carry
        # (plugin="nulloracle"), so the component key, the app-namespace seat and
        # the spec cannot drift apart.  The ``type-r-`` prefix is feature 121's
        # convention, kept so the name-sorted ``app.order`` leaves feature 123's
        # guard immediately after the sidecar.
        assert TYPE_R_COMPONENT_NAME == "nulloracle-type-r-selection"

    def test_the_eight_component_names_are_distinct(self) -> None:
        # Feature 118's component is not a second component under any other
        # name: the eight hold different things on different lifecycles (§7.1's
        # sealed file, the guard journal, the verdict, the fraction, the flip
        # depth, the Type-D resolution, the true-IR probability and this
        # selection), and a deployment can carry any of them without the others.
        names = {
            SIDECAR_COMPONENT_NAME,
            KS_GUARD_COMPONENT_NAME,
            VERDICT_COMPONENT_NAME,
            FRACTION_COMPONENT_NAME,
            FLIP_DEPTH_COMPONENT_NAME,
            RESOLUTION_COMPONENT_NAME,
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
            TYPE_R_COMPONENT_NAME,
        }
        assert len(names) == 8
        assert TYPE_R_COMPONENT_NAME not in {
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
            FLIP_DEPTH_COMPONENT_NAME,
            RESOLUTION_COMPONENT_NAME,
        }

    def test_create_app_composes_a_store_when_both_halves_are_configured(
        self, both_halves: tuple[str, Path]
    ) -> None:
        app = create_app()
        _assert_is_the_type_r_selection(app.get(TYPE_R_COMPONENT_NAME))
        assert TYPE_R_COMPONENT_NAME in app
        assert TYPE_R_COMPONENT_NAME in app.order

    def test_composing_touches_no_file(self, both_halves: tuple[str, Path]) -> None:
        # Construction performs no I/O: the store resolves its path on first use
        # and the sidecar opens nothing until the first write() or open().  That
        # laziness is why a composed application can carry this component in a
        # process that is not the account §7.1's file is readable by.
        _url, sidecar_path = both_halves
        app = create_app()
        assert app.get(TYPE_R_COMPONENT_NAME) is not None
        assert not sidecar_path.exists()

    def test_an_environment_with_no_database_url_still_composes(self) -> None:
        # The load-bearing property: with no relational store at all, the builder
        # returns None and the application composes with every other member
        # intact.
        app = create_app()
        assert app.get(TYPE_R_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_a_database_with_no_sidecar_composes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Half a configuration is not a configuration.  A store holding only the
        # database could draw §7.3's selection but could not persist it — and the
        # bit may only be written into §7.1's sealed file (feature 110), so there
        # is no second place to put it.
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'selection.db'}")
        app = create_app()
        assert app.get(TYPE_R_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_a_sidecar_with_no_database_composes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The other half: a sidecar with no tree to read φ, W and the wells from
        # has nothing to draw.  A builder that composed a store here would be a
        # store whose every call fails at first use.
        monkeypatch.setenv(SIDECAR_PATH_ENV, str(tmp_path / "sidecar.enc"))
        monkeypatch.setenv(KEY_REF_ENV, f"hex:{TEST_KEY_HEX}")
        app = create_app()
        assert app.get(TYPE_R_COMPONENT_NAME) is None

    def test_the_builder_never_raises_on_an_unspeakable_scheme(
        self, both_halves: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A deployment that named a Postgres store is expecting a store, and this
        # one's scheme check is lazy — the URL is refused at the first operation,
        # not at composition.  That laziness is the point: the factory builds
        # every registered component on every create_app(), so a builder that
        # raised on a scheme it cannot speak would take down every other member's
        # component too.
        monkeypatch.setenv(DATABASE_URL_ENV, "postgres:///db")
        app = create_app()
        component = app.get(TYPE_R_COMPONENT_NAME)
        assert type(component).__name__ == "TypeRSelection"
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_a_blank_scheme(
        self, both_halves: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A whitespace-only URL counts as unset: resolve() returns None rather
        # than constructing a store that would fail at first use.
        monkeypatch.setenv(DATABASE_URL_ENV, "   ")
        app = create_app()
        assert app.get(TYPE_R_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_an_unspeakable_key_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The sidecar's own resolution degrades on a key it cannot supply, and
        # that degradation must reach this builder as "no sidecar", not as an
        # exception: a ``kms:`` reference in a deployment that cannot speak KMS
        # is an unconfigured half, and one member's unconfigured environment is
        # not a fault the other members should pay for.
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'selection.db'}")
        monkeypatch.setenv(SIDECAR_PATH_ENV, str(tmp_path / "sidecar.enc"))
        monkeypatch.setenv(KEY_REF_ENV, "kms:arn:aws:kms:eu-west-1:0:key/not-here")
        app = create_app()
        assert app.get(TYPE_R_COMPONENT_NAME) is None
        assert "ledger" in app or "feature-store" in app

    def test_the_builder_never_raises_on_a_malformed_key_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'selection.db'}")
        monkeypatch.setenv(SIDECAR_PATH_ENV, str(tmp_path / "sidecar.enc"))
        monkeypatch.setenv(KEY_REF_ENV, "a-bare-path-with-no-scheme")
        app = create_app()
        assert app.get(TYPE_R_COMPONENT_NAME) is None

    def test_the_component_survives_a_second_composition(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # Must assert on the SECOND application or it passes vacuously: the
        # loader re-executes __init__ on every create_app(), so a @register that
        # lived in ``nulloracle.selection`` would be present in the first and
        # absent here.
        create_app()
        second = create_app()
        _assert_is_the_type_r_selection(second.get(TYPE_R_COMPONENT_NAME))

    def test_the_builder_is_on_the_package_import_path(self) -> None:
        import nulloracle

        assert callable(nulloracle.build_type_r_selection)
        assert nulloracle.build_type_r_selection.__module__.endswith("nulloracle")

    def test_the_builder_takes_no_arguments(self) -> None:
        # The factory's registration protocol: a builder is a zero-argument
        # callable, and a component that needed an argument could not be composed
        # by the scan at all.
        import nulloracle

        assert inspect.signature(nulloracle.build_type_r_selection).parameters == {}

    def test_the_builder_never_raises_when_configured(
        self, both_halves: tuple[str, Path]
    ) -> None:
        import nulloracle

        assert nulloracle.build_type_r_selection() is not None

    def test_the_builder_needs_no_database_url_argument(self, both_halves) -> None:
        # The resolution is the store's own, so the builder stays a zero-argument
        # callable the scan can invoke — the property every component in this
        # member shares.
        import nulloracle

        builder = nulloracle.build_type_r_selection
        assert "database_url" not in inspect.signature(builder).parameters
        assert builder() is not None

    def test_composing_it_leaves_the_guard_adjacent_to_the_sidecar(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The names are sorted, and feature 123's guard must stay immediately
        # after the sidecar in ``app.order``; the ``type-r-`` prefix places this
        # component after every existing family, so the adjacency is untouched.
        app = create_app()
        order = list(app.order)
        assert order.index(KS_GUARD_COMPONENT_NAME) == order.index(SIDECAR_COMPONENT_NAME) + 1

    def test_the_selection_sorts_after_the_other_null_families(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The prefix is not cosmetic: ``app.order`` is name-sorted, so the
        # selection landing before the ``true-ir-`` family would mean the family
        # ordering the member's seats document had silently changed.
        app = create_app()
        order = list(app.order)
        assert order.index(TYPE_R_COMPONENT_NAME) > order.index(
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME
        )


# -- The seat -----------------------------------------------------------------------


class TestTheSeatInTheAppNamespace:
    """``app/modules/nulloracle/selection.py`` — the app package's way to the
    composed store, without the app package importing the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        # Spelled twice on purpose — once in the member, once in the seat — so
        # the two cannot drift apart silently.
        import nulloracle

        from app.modules.nulloracle import selection as seat

        assert (
            seat.COMPONENT_NAME
            == nulloracle.TYPE_R_COMPONENT_NAME
            == TYPE_R_COMPONENT_NAME
        )

    def test_the_seat_exposes_the_composed_store(
        self, both_halves: tuple[str, Path]
    ) -> None:
        from app.modules.nulloracle.selection import type_r_selection_component

        _assert_is_the_type_r_selection(type_r_selection_component())

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.nulloracle.selection import type_r_selection_component

        application = Application(
            components={TYPE_R_COMPONENT_NAME: "sentinel"},
            order=(TYPE_R_COMPONENT_NAME,),
        )
        assert type_r_selection_component(application) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        from app.modules.nulloracle.selection import type_r_selection_component

        empty = Application(components={}, order=())
        assert type_r_selection_component(empty) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        from app.modules.nulloracle.selection import type_r_selection_component

        assert type_r_selection_component() is None

    def test_a_half_configured_environment_yields_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This seat is the one whose ``None`` carries a second meaning worth
        # stating: *one of the store's two halves is unconfigured*.  It must
        # never be read as *the campaign's roots are all real* — that is a fact
        # about a world, and the member's error taxonomy exists to keep the two
        # apart.
        from app.modules.nulloracle.selection import type_r_selection_component

        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'selection.db'}")
        assert type_r_selection_component() is None

    def test_the_seat_can_draw_and_seal_a_selection(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # Feature 118 from the app namespace, end to end: composed store, a
        # campaign's wells in, the drawn roots sealed into §7.1's file and
        # inherited by a descendant — the path an assembled campaign loop takes.
        from app.modules.nulloracle.selection import type_r_selection_component

        _url, sidecar_path = both_halves
        store = type_r_selection_component()
        with store._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 12, 0.1667)",
                (CAMPAIGN,),
            )
            for _ in range(12):
                connection.execute(
                    f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth) "
                    "VALUES (?, ?, 'macro', 0)",
                    (str(uuid.uuid4()), CAMPAIGN),
                )
        selection = store.persist(CAMPAIGN)
        assert len(selection.null_roots) == 2
        assert store.load(CAMPAIGN) == selection
        assert store.null_status(selection.null_roots[0]) is True
        assert sidecar_path.is_file()

    def test_the_seat_can_answer_a_descendants_status(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The sentence's third claim, reached from the app namespace: a node one
        # level below a root inherits the root's status — whichever way the draw
        # went, the descendant agrees with its root.
        from app.modules.nulloracle.selection import type_r_selection_component

        store = type_r_selection_component()
        with store._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 12, 0.1667)",
                (CAMPAIGN,),
            )
            for _ in range(12):
                connection.execute(
                    f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, "
                    "theme_root, depth) VALUES (?, NULL, ?, 'macro', 0)",
                    (str(uuid.uuid4()), CAMPAIGN),
                )
        selection = store.persist(CAMPAIGN)
        root = selection.null_roots[0]
        child = str(uuid.uuid4())
        with store._connect() as connection:
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, theme_root, "
                "depth) VALUES (?, ?, ?, 'macro', 1)",
                (child, root, CAMPAIGN),
            )
        assert store.null_status(child) is True
        assert store.null_status(child) is store.null_status(root)

    def test_the_seat_is_a_composition_read_and_not_a_second_api(self) -> None:
        # The seat's export list, pinned: a caller who has the store reaches
        # ``persist``/``load``/``null_status`` on it, and a second spelling here
        # would be a second thing to keep in sync.  The one question this module
        # answers is *what is the composed store?*
        from app.modules.nulloracle import selection as seat

        assert set(seat.__all__) == {
            "COMPONENT_NAME",
            "type_r_selection_component",
        }
        assert not hasattr(seat, "TypeRSelection")
        assert not hasattr(seat, "RootSelection")
        assert not hasattr(seat, "draw_null_roots")
        assert not hasattr(seat, "persist_type_r_selection")

    def test_the_sidecar_seat_is_untouched_by_the_eighth_component(self) -> None:
        # This seat is a *submodule* beside feature 109's, precisely so that the
        # older seat's promise does not change: a caller that only wants the
        # sidecar never imports this module and sees the same two names it always
        # did.
        from app.modules import nulloracle as seat

        assert set(seat.__all__) == {"COMPONENT_NAME", "null_sidecar_component"}
        assert seat.COMPONENT_NAME == SIDECAR_COMPONENT_NAME

    def test_the_other_seats_are_untouched_by_the_eighth_component(self) -> None:
        # Every older seat's promise is exactly what it was: an eighth submodule
        # beside them does not change what a caller importing any one of them
        # sees.
        from app.modules.nulloracle import flipdepth as flip_seat
        from app.modules.nulloracle import irprob as irprob_seat
        from app.modules.nulloracle import ksguard as guard_seat

        assert set(flip_seat.__all__) == {"COMPONENT_NAME", "flip_depth_component"}
        assert set(irprob_seat.__all__) == {
            "COMPONENT_NAME",
            "true_ir_flip_depth_component",
        }
        assert set(guard_seat.__all__) == {"COMPONENT_NAME", "ks_guard_component"}

    def test_importing_the_seat_imports_no_member(self) -> None:
        # The seat exists so the ``app`` package does not depend on a workspace
        # member at import time.  Asserted on the seat's own compiled form
        # rather than on ``sys.modules`` — every other test in this suite has
        # already imported the member, so the module cache cannot answer this —
        # and on the *imports*, not on the text: the member's name appears in a
        # ``TYPE_CHECKING`` block, which never executes, and a substring scan
        # over the file cannot tell that from a real import.
        import app.modules.nulloracle.selection as module

        imported = _imported_names(module.__file__)
        assert "nulloracle" not in imported
        assert "app" in imported
        assert "nulloracle" in _imported_names(module.__file__, runtime_only=False)

    def test_the_seats_are_distinct_modules(self) -> None:
        import app.modules.nulloracle as sidecar_seat
        import app.modules.nulloracle.flipdepth as flip_seat
        import app.modules.nulloracle.irprob as irprob_seat
        import app.modules.nulloracle.ksguard as guard_seat
        import app.modules.nulloracle.phi as phi_seat
        import app.modules.nulloracle.selection as selection_seat
        import app.modules.nulloracle.verdict as verdict_seat

        assert selection_seat is not sidecar_seat
        assert selection_seat is not guard_seat
        assert selection_seat is not phi_seat
        assert selection_seat is not verdict_seat
        assert selection_seat is not flip_seat
        assert selection_seat is not irprob_seat
        assert selection_seat.__name__ == SEAT_MODULE

    def test_the_seat_answers_the_members_own_builder(self) -> None:
        # The seat and the builder cannot disagree about what the component is:
        # with neither half configured both answer None, and with both set both
        # hand back the same kind of object — which is the whole reason the seat
        # reads the factory rather than resolving the store itself.
        import nulloracle

        from app.modules.nulloracle.selection import type_r_selection_component

        assert nulloracle.build_type_r_selection() is None
        assert type_r_selection_component() is None
