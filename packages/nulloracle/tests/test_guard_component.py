"""The KS guard's plugin seam and its read through the composed application.

``test_component.py`` pins feature 109's registration; this pins feature 123's,
which is the member's *second* component and the first one whose builder is
not about the sidecar file at all.  It is worth its own suite rather than a
section of that one because **the member now registers two components.**  Both
``@register`` calls live in the package's ``__init__``, and the loader
re-executes ``__init__`` on every ``create_app()`` while caching submodules —
so the second registration is exactly as exposed to the "fires once per
process and then drops out" failure as the first, and needs the same *second
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
    DATABASE_URL_ENV,
    KS_GUARD_COMPONENT_NAME,
)

from app.module_loader import Application, create_app, scan_components


@pytest.fixture(autouse=True)
def _no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test in this module with no ``DATABASE_URL``.

    The member's conftest isolates the sidecar's environment; the guard reads
    a different variable, and one the *whole workspace* shares, so a test that
    wants a composed guard has to say so explicitly rather than inherit one
    from whatever invoked pytest.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


@pytest.fixture
def database_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point ``DATABASE_URL`` at a fresh SQLite file for this test."""
    url = f"sqlite:///{tmp_path / 'guard.db'}"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


def _assert_is_the_guard(component: object) -> None:
    assert type(component).__name__ == "KsGuard"
    assert type(component).__module__.endswith("nulloracle.ksguard")
    # Both halves of the feature hang off the composed component: a
    # composition carrying the write but not the read would be a plugin
    # half-wired, and feature 123 needs both — the guard writes the p-value
    # and the system reads it back to report it.
    for operation in ("guard", "load", "resolve"):
        assert callable(getattr(component, operation)), operation
    assert component.database_url


# -- Registration -----------------------------------------------------------------


def test_the_workspace_scan_discovers_both_of_the_members_components() -> None:
    # One member, two components: the sidecar's file-backed one and the
    # guard's relational one. A scan that found only the first would leave
    # feature 123 unreachable from an assembled system.
    names = [component.name for component in scan_components()]
    assert SIDECAR_COMPONENT_NAME in names
    assert KS_GUARD_COMPONENT_NAME in names


def test_the_member_registers_its_guard_under_a_name_that_says_which_it_is() -> None:
    # The guard's component name is the sidecar's name with the feature
    # suffixed, so the two cannot collide and a reader of ``app.order`` can
    # tell which is which without knowing the member.
    assert KS_GUARD_COMPONENT_NAME == "nulloracle-ks-guard"
    assert KS_GUARD_COMPONENT_NAME != SIDECAR_COMPONENT_NAME
    assert KS_GUARD_COMPONENT_NAME.startswith(SIDECAR_COMPONENT_NAME)


def test_scan_is_idempotent_per_component_name() -> None:
    scan_components()
    names = [component.name for component in scan_components()]
    assert names.count(KS_GUARD_COMPONENT_NAME) == 1
    assert names.count(SIDECAR_COMPONENT_NAME) == 1


def test_create_app_composes_the_guard_when_the_environment_configures_one(
    database_url: str,
) -> None:
    app = create_app()
    _assert_is_the_guard(app.get(KS_GUARD_COMPONENT_NAME))
    assert app.get(KS_GUARD_COMPONENT_NAME).database_url == database_url
    assert KS_GUARD_COMPONENT_NAME in app
    assert KS_GUARD_COMPONENT_NAME in app.order


def test_both_components_compose_together(sidecar_path, key_ref: str, database_url: str) -> None:
    # The two are not alternatives: a deployment that has both a sidecar
    # location and a relational store composes the whole of §7.4 — the labels
    # in the file and the guard's reading in the database.
    app = create_app()
    assert type(app.get(SIDECAR_COMPONENT_NAME)).__name__ == "NullSidecar"
    _assert_is_the_guard(app.get(KS_GUARD_COMPONENT_NAME))


def test_composing_opens_no_database(database_url: str, tmp_path) -> None:
    # Construction resolves nothing: the store translates its path on first
    # use. The factory builds every registered component on every
    # ``create_app()``, so a store that opened a connection at construction
    # would put a file — and a lock — in the path of every test and every
    # process that merely composed the app. This is a member whose whole
    # point is that nothing is written until the guard runs.
    app = create_app()
    assert app.get(KS_GUARD_COMPONENT_NAME) is not None
    assert not (tmp_path / "guard.db").exists()


def test_the_component_survives_a_second_composition(database_url: str) -> None:
    # Must assert on the SECOND application or it passes vacuously: the
    # loader re-executes __init__ on every create_app(), so a @register that
    # lived in a submodule would be present in the first and absent here.
    # The guard's registration sits in the same __init__ as the sidecar's and
    # is exposed to the same failure.
    create_app()
    second = create_app()
    _assert_is_the_guard(second.get(KS_GUARD_COMPONENT_NAME))


def test_the_builder_is_on_the_package_import_path() -> None:
    # The registration's survival depends on the builder being reachable by
    # name from the re-executed ``__init__``; a builder that only existed in
    # the module that registered it would be re-bound to nothing on the
    # second composition.
    import nulloracle

    assert callable(nulloracle.build_ks_guard)
    assert nulloracle.build_ks_guard.__module__.endswith("nulloracle")


def test_the_builder_takes_no_arguments() -> None:
    # The factory's registration protocol: a builder is a zero-argument
    # callable, and a component that needed an argument could not be composed
    # by the scan at all.
    import inspect

    import nulloracle

    assert inspect.signature(nulloracle.build_ks_guard).parameters == {}


def test_a_scan_into_an_isolated_registry_finds_the_guard() -> None:
    from app.module_loader import Registration

    registry = Registration()
    components = scan_components(registry=registry)
    assert KS_GUARD_COMPONENT_NAME in [component.name for component in components]
    assert KS_GUARD_COMPONENT_NAME in registry


def test_the_guard_composes_after_the_sidecar_on_the_order_the_factory_records(
    sidecar_path, key_ref: str, database_url: str
) -> None:
    # The member's two builders are registered in one module, so the order is
    # the registration order. Pinned because ``app.order`` is what a caller
    # reasoning about "which of the member's components came up" reads.
    app = create_app()
    order = list(app.order)
    assert order.index(KS_GUARD_COMPONENT_NAME) == order.index(SIDECAR_COMPONENT_NAME) + 1


# -- Degrading rather than raising --------------------------------------------------


def test_an_environment_with_no_relational_store_still_composes() -> None:
    # The load-bearing property: with DATABASE_URL unset the builder returns
    # None and the application composes with every other member intact. A
    # deployment that keeps its campaigns in a file and its sidecar on disk
    # is a deployment, not a broken one.
    app = create_app()
    assert app.get(KS_GUARD_COMPONENT_NAME) is None
    assert "ledger" in app or "feature-store" in app


def test_the_guard_does_not_depend_on_the_sidecar_environment() -> None:
    # The guard is composed from a database URL and knows nothing about the
    # sidecar's environment, so a process configured for one and not the other
    # still gets the one it configured. Composed here with neither, the point
    # is that the *builder* reads only its own variable — a guard that
    # consulted the sidecar's location would refuse to compose in a process
    # that keeps its labels elsewhere.
    app = create_app()
    assert app.get(KS_GUARD_COMPONENT_NAME) is None
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
        assert app.get(KS_GUARD_COMPONENT_NAME) is None


@pytest.mark.parametrize(
    "scheme", ["postgresql://db.internal/nullius", "kms://alias/db"]
)
def test_a_scheme_the_builder_cannot_speak_does_not_take_composition_down(
    scheme: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The builder resolves the URL but never *uses* it, so a scheme this store
    # cannot speak composes and fails — by name — at the first ``guard()`` or
    # ``load()``. That is the right place for it: raising at composition would
    # take down every other member's component, and a process that truly
    # requires the guard asks it directly, where the named error names the URL
    # that was wrong.
    monkeypatch.setenv(DATABASE_URL_ENV, scheme)
    app = create_app()
    component = app.get(KS_GUARD_COMPONENT_NAME)
    _assert_is_the_guard(component)
    # Caught by name, not by ``pytest.raises(KsGuardError)``: the composed
    # component's classes are the *scanned* copies (the loader imports each
    # member under a synthetic module name), so the exception the composed
    # store raises is not this suite's class object. That is the interoperability
    # fact ``test_component.py`` documents for the sidecar, and it applies here
    # unchanged — a caller must not have to know which copy it holds.
    with pytest.raises(Exception) as raised:
        component.load(str(uuid.uuid4()))
    assert type(raised.value).__name__ == "KsGuardError"
    assert "unsupported" in str(raised.value)
    assert scheme.split(":")[0] in str(raised.value)

    # ...and every other member's component is still there, which is the point.
    assert "ledger" in app or "feature-store" in app


# -- Reading the composed guard ---------------------------------------------------


class TestReadingTheComposedGuard:
    """``create_app().get("nulloracle-ks-guard")`` — the way to the composed
    journal from outside the member.
    """

    def test_the_component_name_matches_the_member(self) -> None:
        import nulloracle

        assert nulloracle.KS_GUARD_COMPONENT_NAME == KS_GUARD_COMPONENT_NAME == "nulloracle-ks-guard"

    def test_the_application_exposes_the_composed_guard(self, database_url: str) -> None:
        _assert_is_the_guard(create_app().get(KS_GUARD_COMPONENT_NAME))

    def test_the_component_is_read_from_an_application_it_is_handed(self) -> None:
        application = Application(
            components={KS_GUARD_COMPONENT_NAME: "sentinel"},
            order=(KS_GUARD_COMPONENT_NAME,),
        )
        assert application.get(KS_GUARD_COMPONENT_NAME) == "sentinel"

    def test_an_absent_component_is_none_rather_than_an_error(self) -> None:
        assert Application(components={}, order=()).get(KS_GUARD_COMPONENT_NAME) is None

    def test_an_unconfigured_environment_yields_none_not_an_exception(self) -> None:
        assert create_app().get(KS_GUARD_COMPONENT_NAME) is None

    def test_the_composed_guard_can_persist_a_pvalue(self, database_url: str) -> None:
        # Feature 123 through the composition: composed guard, two samples in,
        # the number on the campaign row — the path an assembled system takes.
        journal = create_app().get(KS_GUARD_COMPONENT_NAME)
        campaign = str(uuid.uuid4())
        with journal._connect() as connection:
            connection.execute(
                "INSERT INTO campaign (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 12, 0.1667)",
                (campaign,),
            )
        record = journal.guard(campaign, [1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0])
        assert record.pvalue < 0.05
        assert journal.load(campaign) == record

    def test_the_composition_answers_the_members_own_builder(self) -> None:
        # The composition and the builder cannot disagree about what the
        # component is: with ``DATABASE_URL`` unset both answer None.
        import nulloracle

        assert nulloracle.build_ks_guard() is None
        assert create_app().get(KS_GUARD_COMPONENT_NAME) is None
