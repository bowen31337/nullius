"""The KS verdict's plugin seam and its seat in the ``app`` namespace.

``test_component.py`` pins feature 109's registration and ``test_guard_component.py``
pins feature 123's; this pins feature 124's, the member's *third* component
and the one whose builder, like the guard's, resolves a database URL.  Two
things make it worth its own suite rather than a section of the guard's:

* **the member now registers three components.**  All three ``@register``
  calls live in the package's ``__init__``, and the loader re-executes
  ``__init__`` on every ``create_app()`` while caching submodules — so the
  third registration is exactly as exposed to the "fires once per process and
  then drops out" failure as the first two, and needs the same *second
  application* assertion.  A registration added in a submodule would pass a
  single-composition test.
* **the seat is a third submodule.**  ``app/modules/nulloracle/`` was a single
  ``__init__.py`` while the member contributed one component; the verdict's
  seat lives beside the other two in ``app/modules/nulloracle/verdict.py``.
  The older seats' export lists must stay exactly as they were, and the new
  module must answer the same shape of question — *what is the composed X?* —
  with the same ``None``-not-an-exception degradation and the same refusal to
  become a second API.

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
    CALIBRATION_STATUS_OK,
    CALIBRATION_STATUS_VOID,
    DATABASE_URL_ENV,
    KS_GUARD_COMPONENT_NAME,
    VERDICT_COMPONENT_NAME,
)

from app.module_loader import Application, create_app, scan_components

SEAT_MODULE = "app.modules.nulloracle.verdict"


@pytest.fixture(autouse=True)
def _no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test in this module with no ``DATABASE_URL``.

    The member's conftest isolates the sidecar's environment; the verdict
    reads a different variable, and one the *whole workspace* shares, so a test
    that wants a composed verdict has to say so explicitly rather than inherit
    one from whatever invoked pytest.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


@pytest.fixture
def database_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point ``DATABASE_URL`` at a fresh SQLite file for this test."""
    url = f"sqlite:///{tmp_path / 'verdict.db'}"
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
    if runtime_only:
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for inner in ast.walk(node):
                    guarded.add(id(inner))
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def _assert_is_the_verdict(component: object) -> None:
    assert type(component).__name__ == "CampaignVerdict"
    assert type(component).__module__.endswith("nulloracle.verdict")
    # Both halves of the feature hang off the composed component: a composition
    # carrying the write but not the read would be a plugin half-wired, and
    # feature 124 needs both — the verdict voids the campaign and the pool reads
    # its status back to reject it.
    for operation in ("void_if_detectable", "load", "resolve"):
        assert callable(getattr(component, operation)), operation
    assert component.database_url


# -- Registration -----------------------------------------------------------------


def test_the_workspace_scan_discovers_all_three_of_the_members_components() -> None:
    # One member, three components: the sidecar's file-backed one, the guard's
    # relational one and the verdict's relational one. A scan that found only
    # the first two would leave feature 124 unreachable from an assembled
    # system.
    names = [component.name for component in scan_components()]
    assert SIDECAR_COMPONENT_NAME in names
    assert KS_GUARD_COMPONENT_NAME in names
    assert VERDICT_COMPONENT_NAME in names


def test_the_member_registers_its_verdict_under_a_name_that_says_which_it_is() -> None:
    # The verdict's component name is the sidecar's name with the feature
    # suffixed, so the three cannot collide and a reader of ``app.order`` can
    # tell which is which without knowing the member.
    assert VERDICT_COMPONENT_NAME == "nulloracle-ks-verdict"
    assert VERDICT_COMPONENT_NAME != KS_GUARD_COMPONENT_NAME
    assert VERDICT_COMPONENT_NAME != SIDECAR_COMPONENT_NAME
    assert VERDICT_COMPONENT_NAME.startswith(SIDECAR_COMPONENT_NAME)


def test_scan_is_idempotent_per_component_name() -> None:
    scan_components()
    names = [component.name for component in scan_components()]
    assert names.count(VERDICT_COMPONENT_NAME) == 1
    assert names.count(KS_GUARD_COMPONENT_NAME) == 1
    assert names.count(SIDECAR_COMPONENT_NAME) == 1


def test_create_app_composes_the_verdict_when_the_environment_configures_one(
    database_url: str,
) -> None:
    app = create_app()
    _assert_is_the_verdict(app.get(VERDICT_COMPONENT_NAME))
    assert app.get(VERDICT_COMPONENT_NAME).database_url == database_url
    assert VERDICT_COMPONENT_NAME in app
    assert VERDICT_COMPONENT_NAME in app.order


def test_composing_opens_no_database(database_url: str, tmp_path) -> None:
    # Construction resolves nothing: the store translates its path on first
    # use. The factory builds every registered component on every
    # ``create_app()``, so a store that opened a connection at construction
    # would put a file — and a lock — in the path of every test and every
    # process that merely composed the app. This is a member whose whole point
    # is that nothing is written until the verdict is pronounced.
    app = create_app()
    assert app.get(VERDICT_COMPONENT_NAME) is not None
    assert not (tmp_path / "verdict.db").exists()


def test_the_component_survives_a_second_composition(database_url: str) -> None:
    # Must assert on the SECOND application or it passes vacuously: the loader
    # re-executes __init__ on every create_app(), so a @register that lived in
    # a submodule would be present in the first and absent here. The verdict's
    # registration sits in the same __init__ as the sidecar's and the guard's
    # and is exposed to the same failure.
    create_app()
    second = create_app()
    _assert_is_the_verdict(second.get(VERDICT_COMPONENT_NAME))


def test_the_builder_is_on_the_package_import_path() -> None:
    # The registration's survival depends on the builder being reachable by
    # name from the re-executed ``__init__``; a builder that only existed in
    # the module that registered it would be re-bound to nothing on the second
    # composition.
    import nulloracle

    assert callable(nulloracle.build_verdict)
    assert nulloracle.build_verdict.__module__.endswith("nulloracle")


def test_a_scan_into_an_isolated_registry_finds_the_verdict() -> None:
    from app.module_loader import Registration

    registry = Registration()
    components = scan_components(registry=registry)
    assert VERDICT_COMPONENT_NAME in [component.name for component in components]
    assert VERDICT_COMPONENT_NAME in registry


# -- Degrading rather than raising --------------------------------------------------


def test_an_environment_with_no_relational_store_still_composes() -> None:
    # The load-bearing property: with DATABASE_URL unset the builder returns
    # None and the application composes with every other member intact. A
    # deployment that keeps its campaigns in a file and its sidecar on disk is
    # a deployment, not a broken one.
    app = create_app()
    assert app.get(VERDICT_COMPONENT_NAME) is None
    assert "ledger" in app or "feature-store" in app


def test_the_verdict_does_not_depend_on_the_sidecar_environment() -> None:
    # The verdict is composed from a database URL and knows nothing about the
    # sidecar's environment, so a process configured for one and not the other
    # still gets the one it configured. Composed here with neither, the point
    # is that the *builder* reads only its own variable.
    app = create_app()
    assert app.get(VERDICT_COMPONENT_NAME) is None
    assert app.get(SIDECAR_COMPONENT_NAME) is None


def test_a_blank_database_url_is_no_store_rather_than_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty or whitespace-only value counts as unset — the same rule the
    # sidecar's path applies. It is the shape an unexpanded template leaves
    # behind, and refusing to compose on it would take down a process whose
    # every other member is fine.
    for value in ("", "   "):
        monkeypatch.setenv(DATABASE_URL_ENV, value)
        app = create_app()
        assert app.get(VERDICT_COMPONENT_NAME) is None


@pytest.mark.parametrize(
    "scheme", ["postgresql://db.internal/nullius", "kms://alias/db"]
)
def test_a_scheme_the_builder_cannot_speak_does_not_take_composition_down(
    scheme: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The builder resolves the URL but never *uses* it, so a scheme this store
    # cannot speak composes and fails — by name — at the first ``load()``. That
    # is the right place for it: raising at composition would take down every
    # other member's component, and a process that truly requires the verdict
    # asks it directly, where the named error names the URL that was wrong.
    monkeypatch.setenv(DATABASE_URL_ENV, scheme)
    app = create_app()
    component = app.get(VERDICT_COMPONENT_NAME)
    _assert_is_the_verdict(component)
    # Caught by name, not by ``pytest.raises(KsGuardError)``: the composed
    # component's classes are the *scanned* copies (the loader imports each
    # member under a synthetic module name), so the exception the composed
    # store raises is not this suite's class object.
    with pytest.raises(Exception) as raised:
        component.load(str(uuid.uuid4()))
    assert type(raised.value).__name__ == "KsGuardError"
    assert "unsupported" in str(raised.value)
    assert scheme.split(":")[0] in str(raised.value)

    # ...and every other member's component is still there, which is the point.
    assert "ledger" in app or "feature-store" in app


# -- The seat ---------------------------------------------------------------------


class TestTheSeatInTheAppNamespace:
    """``app/modules/nulloracle/verdict.py`` — the app package's way to the
    composed verdict store, without the app package importing the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        # Spelled twice on purpose — once in the member, once in the seat — so
        # the two cannot drift apart silently.
        import nulloracle

        from app.modules.nulloracle import verdict as verdict_seat

        assert (
            verdict_seat.COMPONENT_NAME
            == nulloracle.VERDICT_COMPONENT_NAME
            == VERDICT_COMPONENT_NAME
        )

    def test_the_seat_exposes_the_composed_verdict(self, database_url: str) -> None:
        from app.modules.nulloracle.verdict import verdict_component

        _assert_is_the_verdict(verdict_component())

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.nulloracle.verdict import verdict_component

        application = Application(
            components={VERDICT_COMPONENT_NAME: "sentinel"},
            order=(VERDICT_COMPONENT_NAME,),
        )
        assert verdict_component(application) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        from app.modules.nulloracle.verdict import verdict_component

        assert verdict_component(Application(components={}, order=())) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        from app.modules.nulloracle.verdict import verdict_component

        assert verdict_component() is None

    def test_the_seat_can_pronounce_a_verdict(self, database_url: str) -> None:
        # Feature 124 from the app namespace: composed verdict, a campaign with
        # a detectable p-value, the status advanced to VOID — the path an
        # assembled system takes.
        from app.modules.nulloracle.verdict import verdict_component

        verdict = verdict_component()
        campaign = str(uuid.uuid4())
        with verdict._connect() as connection:
            connection.execute(
                "INSERT INTO campaign (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 12, 0.1667)",
                (campaign,),
            )
            connection.execute(
                "UPDATE campaign SET ks_pvalue = ? WHERE id = ?", (0.01, campaign)
            )
        result = verdict.void_if_detectable(campaign)
        assert result.status == CALIBRATION_STATUS_VOID
        assert result.voided is True
        assert verdict.load(campaign) == CALIBRATION_STATUS_VOID

    def test_the_seat_can_leave_a_clean_campaign_ok(self, database_url: str) -> None:
        # The other half of the verdict: a campaign whose nulls are not
        # detectable keeps its 'ok' default through the seat.
        from app.modules.nulloracle.verdict import verdict_component

        verdict = verdict_component()
        campaign = str(uuid.uuid4())
        with verdict._connect() as connection:
            connection.execute(
                "INSERT INTO campaign (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 12, 0.1667)",
                (campaign,),
            )
            connection.execute(
                "UPDATE campaign SET ks_pvalue = ? WHERE id = ?", (0.31, campaign)
            )
        result = verdict.void_if_detectable(campaign)
        assert result.status == CALIBRATION_STATUS_OK
        assert verdict.load(campaign) == CALIBRATION_STATUS_OK

    def test_the_seat_is_a_composition_read_and_not_a_second_api(self) -> None:
        # The seat's export list, pinned: a caller who has the store reaches
        # ``void_if_detectable``/``load`` on it, and a second spelling here
        # would be a second thing to keep in sync. The one question this module
        # answers is *what is the composed verdict store?* — and the answer is
        # the component, not a re-exported store class or threshold.
        from app.modules.nulloracle import verdict as seat

        assert set(seat.__all__) == {"COMPONENT_NAME", "verdict_component"}
        assert not hasattr(seat, "CampaignVerdict")
        assert not hasattr(seat, "VOID_THRESHOLD")

    def test_the_three_seats_are_distinct_modules(self) -> None:
        import app.modules.nulloracle as sidecar_seat
        import app.modules.nulloracle.ksguard as guard_seat
        import app.modules.nulloracle.verdict as verdict_seat

        assert verdict_seat is not guard_seat
        assert verdict_seat is not sidecar_seat
        assert verdict_seat.__name__ == SEAT_MODULE
        assert verdict_seat.COMPONENT_NAME != guard_seat.COMPONENT_NAME
        assert verdict_seat.COMPONENT_NAME != sidecar_seat.COMPONENT_NAME

    def test_the_sidecar_seat_is_untouched_by_the_third_component(self) -> None:
        # The verdict's seat is a *submodule* beside the other two, precisely so
        # that the older seats' promises do not change: a caller that only wants
        # the sidecar or the guard never imports the verdict's module and sees
        # the same two names it always did.
        from app.modules import nulloracle as sidecar_seat

        assert set(sidecar_seat.__all__) == {"COMPONENT_NAME", "null_sidecar_component"}

    def test_importing_the_seat_imports_no_member(self) -> None:
        # The seat exists so the ``app`` package does not depend on a workspace
        # member at import time. Asserted on the seat's own compiled form rather
        # than on ``sys.modules`` — every other test in this suite has already
        # imported the member, so the module cache cannot answer this — and on
        # the *imports*, not on the text: the member's name appears in a
        # ``TYPE_CHECKING`` block, which never executes.
        import app.modules.nulloracle.verdict as module

        imported = _imported_names(module.__file__)
        assert "nulloracle" not in imported
        assert "app" in imported
        assert "nulloracle" in _imported_names(module.__file__, runtime_only=False)

    def test_the_seat_answers_the_members_own_builder(self) -> None:
        # The seat and the builder cannot disagree about what the component is:
        # with ``DATABASE_URL`` unset both answer None, and with it set both
        # hand back the same kind of object — which is the whole reason the seat
        # reads the factory rather than resolving the store itself.
        import nulloracle

        from app.modules.nulloracle.verdict import verdict_component

        assert nulloracle.build_verdict() is None
        assert verdict_component() is None
