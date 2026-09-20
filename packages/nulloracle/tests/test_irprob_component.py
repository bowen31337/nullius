"""Feature 120's plugin seam and its seat in the ``app`` namespace.

``test_component.py`` pins feature 109's registration, ``test_guard_component.py``
feature 123's, ``test_phi_component.py`` feature 117's, ``test_flip_depth_component.py``
feature 119's; this pins feature 120's — the member's *seventh* component, and
the second whose builder resolves a database URL for the flip-depth family.
Two things make it worth its own suite rather than a section of feature 119's:

* **the member now registers seven components.**  All seven ``@register`` calls
  live in the package's ``__init__``, and the loader re-executes ``__init__`` on
  every ``create_app()`` while caching submodules — so the seventh registration
  is exactly as exposed to the "fires once per process and then drops out"
  failure as the first six, and needs the same *second application* assertion.
  A registration added in a submodule would pass a single-composition test.

* **the seat is a seventh submodule.**  ``app/modules/nulloracle/`` was a single
  ``__init__.py`` while the member contributed one component; this feature's seat
  lives beside the other six in ``app/modules/nulloracle/irprob.py``.  The older
  seats' export lists must stay exactly as they were, and the new module must
  answer the same shape of question — *what is the composed X?* — with the same
  ``None``-not-an-exception degradation and the same refusal to become a second
  API.

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
    KS_GUARD_COMPONENT_NAME,
    RESOLUTION_COMPONENT_NAME,
    TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,
    VERDICT_COMPONENT_NAME,
)
from nulloracle import (
    COMPONENT_NAME as SIDECAR_COMPONENT_NAME,
)

from app.module_loader import Application, create_app, scan_components

SEAT_MODULE = "app.modules.nulloracle.irprob"

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
        # (plugin="nulloracle"), so the component key, the app-namespace seat and
        # the spec cannot drift apart.
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


# -- The seat -----------------------------------------------------------------------


class TestTheSeatInTheAppNamespace:
    """``app/modules/nulloracle/irprob.py`` — the app package's way to the
    composed store, without the app package importing the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        # Spelled twice on purpose — once in the member, once in the seat — so
        # the two cannot drift apart silently.
        import nulloracle

        from app.modules.nulloracle import irprob as seat

        assert (
            seat.COMPONENT_NAME
            == nulloracle.TRUE_IR_FLIP_DEPTH_COMPONENT_NAME
            == TRUE_IR_FLIP_DEPTH_COMPONENT_NAME
        )

    def test_the_seat_exposes_the_composed_store(self, database_url: str) -> None:
        from app.modules.nulloracle.irprob import true_ir_flip_depth_component

        _assert_is_the_true_ir_flip_depth(true_ir_flip_depth_component())

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.nulloracle.irprob import true_ir_flip_depth_component

        application = Application(
            components={TRUE_IR_FLIP_DEPTH_COMPONENT_NAME: "sentinel"},
            order=(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME,),
        )
        assert true_ir_flip_depth_component(application) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        from app.modules.nulloracle.irprob import true_ir_flip_depth_component

        assert true_ir_flip_depth_component(Application(components={}, order=())) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        from app.modules.nulloracle.irprob import true_ir_flip_depth_component

        assert true_ir_flip_depth_component() is None

    def test_the_seat_can_report_a_distribution_with_no_database(
        self, database_url: str, tmp_path: Path
    ) -> None:
        # Feature 120 from the app namespace, and the property that separates
        # this component from feature 119's: the campaign's shift is a function
        # of its id, so *what does this campaign draw?* is answerable from a
        # composed component whose file has never been opened.
        from app.modules.nulloracle.irprob import true_ir_flip_depth_component

        store = true_ir_flip_depth_component()
        distribution = store.distribution(CAMPAIGN, 1.0)
        assert 0.0 < distribution.probability < 1.0
        assert distribution.campaign_id == CAMPAIGN
        assert not (tmp_path / "irprob.db").exists()

    def test_the_seat_can_draw_a_depth(self, database_url: str) -> None:
        # Feature 120 from the app namespace, end to end: composed store, a
        # branch's true IR in, the drawn depth on the node's column — the path an
        # assembled campaign loop takes.
        from app.modules.nulloracle.irprob import true_ir_flip_depth_component

        store = true_ir_flip_depth_component()
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

    def test_the_seat_is_a_composition_read_and_not_a_second_api(self) -> None:
        # The seat's export list, pinned: a caller who has the store reaches
        # ``draw``/``distribution``/``distribution_for_node`` on it, and a second
        # spelling here would be a second thing to keep in sync.  The one
        # question this module answers is *what is the composed store?*
        from app.modules.nulloracle import irprob as seat

        assert set(seat.__all__) == {
            "COMPONENT_NAME",
            "true_ir_flip_depth_component",
        }
        assert not hasattr(seat, "TrueIRFlipDepth")
        assert not hasattr(seat, "probability_from_true_ir")
        assert not hasattr(seat, "FlipDepthDistribution")

    def test_the_sidecar_seat_is_untouched_by_the_seventh_component(self) -> None:
        # This seat is a *submodule* beside feature 109's, precisely so that the
        # older seat's promise does not change: a caller that only wants the
        # sidecar never imports this module and sees the same two names it always
        # did.
        from app.modules import nulloracle as seat

        assert set(seat.__all__) == {"COMPONENT_NAME", "null_sidecar_component"}
        assert seat.COMPONENT_NAME == SIDECAR_COMPONENT_NAME

    def test_the_flip_depth_seat_is_untouched_by_the_seventh_component(self) -> None:
        from app.modules.nulloracle import flipdepth as flip_seat

        assert set(flip_seat.__all__) == {
            "COMPONENT_NAME",
            "flip_depth_component",
        }

    def test_the_seats_are_distinct_modules(self) -> None:
        import app.modules.nulloracle as sidecar_seat
        import app.modules.nulloracle.flipdepth as flip_seat
        import app.modules.nulloracle.irprob as irprob_seat
        import app.modules.nulloracle.ksguard as guard_seat
        import app.modules.nulloracle.phi as phi_seat
        import app.modules.nulloracle.verdict as verdict_seat

        assert irprob_seat is not sidecar_seat
        assert irprob_seat is not guard_seat
        assert irprob_seat is not phi_seat
        assert irprob_seat is not verdict_seat
        assert irprob_seat is not flip_seat
        assert irprob_seat.__name__ == SEAT_MODULE

    def test_importing_the_seat_imports_no_member(self) -> None:
        # The seat exists so the ``app`` package does not depend on a workspace
        # member at import time.  Asserted on the seat's own compiled form rather
        # than on ``sys.modules`` — every other test in this suite has already
        # imported the member, so the module cache cannot answer this — and on
        # the *imports*, not on the text: the member's name appears in a
        # ``TYPE_CHECKING`` block, which never executes, and a substring scan
        # over the file cannot tell that from a real import.
        import app.modules.nulloracle.irprob as module

        imported = _imported_names(module.__file__)
        assert "nulloracle" not in imported
        assert "app" in imported
        assert "nulloracle" in _imported_names(module.__file__, runtime_only=False)

    def test_the_seat_answers_the_members_own_builder(self) -> None:
        # The seat and the builder cannot disagree about what the component is:
        # with ``DATABASE_URL`` unset both answer None, and with it set both hand
        # back the same kind of object — which is the whole reason the seat reads
        # the factory rather than resolving the store itself.
        import nulloracle

        from app.modules.nulloracle.irprob import true_ir_flip_depth_component

        assert nulloracle.build_true_ir_flip_depth() is None
        assert true_ir_flip_depth_component() is None
