"""The KS verdict's plugin seam and its read through the composed application.

``test_component.py`` pins feature 109's registration and ``test_guard_component.py``
pins feature 123's; this pins feature 124's, the member's *third* component
and the one whose builder, like the guard's, resolves a database URL.  It is
worth its own suite rather than a section of the guard's because:

* **the member now registers three components.**  All three ``@register``
  calls live in the package's ``__init__``, and the loader re-executes
  ``__init__`` on every ``create_app()`` while caching submodules — so the
  third registration is exactly as exposed to the "fires once per process and
  then drops out" failure as the first two, and needs the same *second
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


# -- Reading the composed component ---------------------------------------------


class TestReadingTheComposedComponent:
    """The component as ``create_app().get(...)`` hands it to a caller outside
    the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        import nulloracle

        assert (
            nulloracle.VERDICT_COMPONENT_NAME
            == VERDICT_COMPONENT_NAME
        )

    def test_the_application_exposes_the_composed_verdict(self, database_url: str) -> None:
        _assert_is_the_verdict(create_app().get(VERDICT_COMPONENT_NAME))

    def test_the_component_is_read_from_an_application_it_is_handed(self) -> None:
        application = Application(
            components={VERDICT_COMPONENT_NAME: "sentinel"},
            order=(VERDICT_COMPONENT_NAME,),
        )
        assert application.get(VERDICT_COMPONENT_NAME) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        assert Application(components={}, order=()).get(VERDICT_COMPONENT_NAME) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        assert create_app().get(VERDICT_COMPONENT_NAME) is None

    def test_the_composed_component_can_pronounce_a_verdict(self, database_url: str) -> None:
        # Feature 124 through the composition: composed verdict, a campaign with
        # a detectable p-value, the status advanced to VOID — the path an
        # assembled system takes.
        verdict = create_app().get(VERDICT_COMPONENT_NAME)
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

    def test_the_composed_component_can_leave_a_clean_campaign_ok(self, database_url: str) -> None:
        # The other half of the verdict: a campaign whose nulls are not
        # detectable keeps its 'ok' default through the composition.
        verdict = create_app().get(VERDICT_COMPONENT_NAME)
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

    def test_the_composition_answers_the_members_own_builder(self) -> None:
        # The composition and the builder cannot disagree about what the
        # component is: unconfigured, both answer None.
        import nulloracle

        assert nulloracle.build_verdict() is None
        assert create_app().get(VERDICT_COMPONENT_NAME) is None
