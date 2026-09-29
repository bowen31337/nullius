"""Feature 118's plugin seam and its read through the composed application.

``test_component.py`` pins feature 109's registration, ``test_guard_component.py``
feature 123's, ``test_phi_component.py`` feature 117's, ``test_flip_depth_component.py``
feature 119's, ``test_irprob_component.py`` feature 120's; this pins feature
118's — the member's *eighth* component, and the first whose builder needs two
things to resolve rather than one.

Two things make it worth its own suite rather than a section of feature 120's:

* **the member now registers eight components, and the eighth is the one most
  exposed to the registration trap.**  All eight ``@register`` calls live in the
  package's ``__init__``, and the loader re-executes ``__init__`` on every
  ``create_app()`` while caching submodules — so a registration that lived in
  ``nulloracle.selection`` would fire on the first composition of a process and
  silently drop out of every later one.  The second-application assertion below
  is what catches that, and a single-composition test would pass for it.

* **the component needs two composed halves.**  Every other component
  resolves from a single source.  This one's store reads the tree
  and the campaign row from a relational database *and* seals the drawn status
  into §7.1's sidecar, so the composed component exists only where both resolve
  — and ``None`` therefore means *one of the two is unconfigured*, never *the
  campaign planted no nulls*.  The half-configured cases are pinned
  individually, because a builder that resolved only one half would compose a
  store that can draw but not persist, or persist but not draw.

The load-bearing property is unchanged and restated because the consequence is
sharper here: **the builder must never raise.**  It resolves ``DATABASE_URL``
and the sidecar's two variables, all of which the whole workspace shares, so a
builder that raised on a scheme it cannot speak or a key reference it cannot
parse would take composition down for every unrelated feature in the process.
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


# -- The registration ---------------------------------------------------------------


class TestTheTypeRSelectionComponentRegisters:
    def test_the_member_registers_the_type_r_selection_component(self) -> None:
        names = [component.name for component in scan_components()]
        assert TYPE_R_COMPONENT_NAME in names

    def test_the_component_name_is_the_expected_spelling(self) -> None:
        # The hyphen-free spelling is the plugin name the spec's features carry
        # (plugin="nulloracle"), so the component key and
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
        # ordering the member's components document had silently changed.
        app = create_app()
        order = list(app.order)
        assert order.index(TYPE_R_COMPONENT_NAME) > order.index(
            TRUE_IR_FLIP_DEPTH_COMPONENT_NAME
        )


# -- Reading the composed component ---------------------------------------------


class TestReadingTheComposedComponent:
    """The component as ``create_app().get(...)`` hands it to a caller outside
    the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        import nulloracle

        assert (
            nulloracle.TYPE_R_COMPONENT_NAME
            == TYPE_R_COMPONENT_NAME
        )

    def test_the_application_exposes_the_composed_store(
        self, both_halves: tuple[str, Path]
    ) -> None:
        _assert_is_the_type_r_selection(create_app().get(TYPE_R_COMPONENT_NAME))

    def test_the_component_is_read_from_an_application_it_is_handed(self) -> None:
        application = Application(
            components={TYPE_R_COMPONENT_NAME: "sentinel"},
            order=(TYPE_R_COMPONENT_NAME,),
        )
        assert application.get(TYPE_R_COMPONENT_NAME) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        empty = Application(components={}, order=())
        assert empty.get(TYPE_R_COMPONENT_NAME) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        assert create_app().get(TYPE_R_COMPONENT_NAME) is None

    def test_a_half_configured_environment_yields_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This component is the one whose ``None`` carries a second meaning worth
        # stating: *one of the store's two halves is unconfigured*.  It must
        # never be read as *the campaign's roots are all real* — that is a fact
        # about a world, and the member's error taxonomy exists to keep the two
        # apart.
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'selection.db'}")
        assert create_app().get(TYPE_R_COMPONENT_NAME) is None

    def test_the_composed_component_can_draw_and_seal_a_selection(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # Feature 118 through the composition, end to end: composed store, a
        # campaign's wells in, the drawn roots sealed into §7.1's file and
        # inherited by a descendant — the path an assembled campaign loop takes.
        _url, sidecar_path = both_halves
        store = create_app().get(TYPE_R_COMPONENT_NAME)
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

    def test_the_composed_component_can_answer_a_descendants_status(
        self, both_halves: tuple[str, Path]
    ) -> None:
        # The sentence's third claim, reached through the composition: a node one
        # level below a root inherits the root's status — whichever way the draw
        # went, the descendant agrees with its root.
        store = create_app().get(TYPE_R_COMPONENT_NAME)
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

    def test_the_composition_answers_the_members_own_builder(self) -> None:
        # The composition and the builder cannot disagree about what the
        # component is: unconfigured, both answer None.
        import nulloracle

        assert nulloracle.build_type_r_selection() is None
        assert create_app().get(TYPE_R_COMPONENT_NAME) is None
