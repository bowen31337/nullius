"""Feature 202's wiring: the run-window store is composed by convention.

The same two halves :mod:`tests.test_pin_component` states for feature 203's
store, asked about feature 202's — and for the same reasons, worth restating
in this file's terms rather than by reference, because they are properties of
*this* feature's landing.  The **registration** half asks whether ``import
providers`` joins the application with a scheduler in it — no central
registry, router, entry-points table or factory edited, which is what lets
this feature land in parallel with every other one.  The **composition** half
asks whether ``create_app().get(...)`` hands that scheduler back under the
member's own component name.

The registration half runs through the *scanning* path, because that is the
path a deployment takes — and the second-composition test below is the live
defect guard: a ``@register`` living in a submodule fires only on the first
``create_app()`` of a process, which is precisely the trap this member's
three registrations live in the package ``__init__`` to avoid.
"""

from __future__ import annotations

import importlib
import pathlib
from datetime import timedelta

import providers

# ── The registration: by convention, in the package __init__ ──────────────────


def test_the_member_registers_its_scheduler_under_its_own_name():
    # The decorator fired when this test module imported the member, and the
    # name it registered under is feature 202's — distinct from 192's
    # interface name and 203's pin-store name, on the same plugin-plus-
    # contribution pattern the pin store set for a member's later components.
    from app.module_loader import registered_components

    names = {component.name for component in registered_components()}
    assert providers.DEPTH_RUN_WINDOW_COMPONENT in names
    assert providers.DEPTH_RUN_WINDOW_COMPONENT not in (
        providers.PROVIDERS_COMPONENT,
        providers.AGENT_MODEL_PIN_COMPONENT,
    )


def test_scanning_composes_the_scheduler_without_a_central_registry():
    # The property the plugin convention exists for: an application built by
    # *scanning* the workspace holds feature 202's component, driven through
    # the loader's own scan because that is the path a deployment takes.
    from app.module_loader import create_app

    application = create_app()
    assert providers.DEPTH_RUN_WINDOW_COMPONENT in application.order
    assert providers.DEPTH_RUN_WINDOW_COMPONENT in dict(application.components)


def test_a_second_composition_in_the_same_process_still_holds_the_scheduler():
    # The submodule-registration trap, asserted directly: the loader imports
    # each member once per process, so a ``@register`` living anywhere but
    # the package ``__init__`` would silently vanish from every composition
    # after the first.  Two calls, one assertion each — this member's third
    # registration is where the trap would bite, added long after the first
    # two made the pattern look safe.
    from app.module_loader import create_app

    first = create_app()
    second = create_app()
    for application in (first, second):
        assert providers.DEPTH_RUN_WINDOW_COMPONENT in application.order


def test_the_builder_contributes_none_when_no_store_is_named(monkeypatch):
    # A deployment with no ``DATABASE_URL`` composes a ``None`` component
    # rather than an empty scheduler or an exception: absent is a
    # discoverable state, and — the builder's own docstring draws the line —
    # a ``None`` here is a refusal to schedule, never a store that happens
    # to find every campaign unscheduled.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert providers.build_depth_run_windows() is None


def test_the_builder_contributes_a_scheduler_bound_to_the_deployments_url(
    monkeypatch, tmp_path
):
    # ...and with a ``DATABASE_URL`` set, the composed component is the store
    # for *that* deployment.  Construction still opens nothing and creates
    # nothing: composing the application must not bring the member-owned
    # ``depth_run_window`` table into being — that is the store's first
    # write's job, and nothing else's.
    url = f"sqlite:///{tmp_path / 'composed-schedule.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = providers.build_depth_run_windows()

    assert isinstance(store, providers.DepthRunWindows)
    assert store.database_url == url
    assert not (tmp_path / "composed-schedule.db").exists()


def test_the_builder_takes_no_arguments_as_the_registration_protocol_requires(
    monkeypatch,
):
    # The factory calls every registered builder with no arguments — that is
    # the protocol — so a builder that grew a parameter would break
    # composition for the whole application.  Asserted on the callable the
    # *registry* holds, because that is what the factory will actually call.
    from app.module_loader import registered_components

    monkeypatch.delenv("DATABASE_URL", raising=False)
    builder = next(
        component.builder
        for component in registered_components()
        if component.name == providers.DEPTH_RUN_WINDOW_COMPONENT
    )
    # The call is the assertion: a builder that demanded an argument raises
    # TypeError here.
    assert builder() is None


# ── The composition: the application's way to the same scheduler ──────────────


def test_the_composed_scheduler_raises_this_features_errors_by_name(
    monkeypatch, tmp_path
):
    # The composed store raises errors from the *scanned* copy of this
    # member, so ``pytest.raises(providers.DepthScheduleError)`` — the
    # canonical class — does not match them.  The workspace's answer is to
    # assert on the *name*, which the two copies agree on because they are
    # one source file; asserted here because the rest of this member's
    # schedule suite drives the directly-imported store, so nothing else
    # exercises the composed copy's vocabulary.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'vocab-schedule.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = create_app().get(providers.DEPTH_RUN_WINDOW_COMPONENT)

    # A malformed campaign id is refused before any database is opened —
    # which is enough to see the class the composed copy raises, and that
    # it is *this feature's* class by name, not a foreign error type.
    raised: BaseException | None = None
    try:
        store.schedule(
            "not-a-uuid", providers.PeakPricing(), duration=timedelta(hours=1)
        )
    except Exception as refusal:  # noqa: BLE001 - the class name is the assertion
        raised = refusal
    assert raised is not None, "the composed scheduler accepted a malformed ask"
    assert type(raised).__name__ == type(providers.DepthScheduleError()).__name__
    assert type(raised).__module__.startswith("_nullius_scanned_providers")


def test_the_composed_scheduler_schedules_the_members_card(
    monkeypatch, campaign_database, plant_campaign
):
    # The double-import remedy, exercised at the composed seam: the card a
    # caller built from the *directly imported* member is not an instance of
    # the scanned copy's PeakPricing — ``isinstance`` across the two is
    # False for one and the same source file — and the composed store takes
    # it anyway, recognising it by its parts and re-making it, so a
    # deployment's caller is never refused for holding the wrong of two
    # classes.  The campaign comes through the migration-brought table, the
    # same fixture the store suite schedules against.
    from app.module_loader import create_app

    monkeypatch.setenv("DATABASE_URL", campaign_database)
    campaign = plant_campaign(campaign_database)
    store = create_app().get(providers.DEPTH_RUN_WINDOW_COMPONENT)

    record = store.schedule(
        campaign, providers.PeakPricing(), duration=timedelta(hours=1)
    )
    # The record is the scanned copy's class — asserted rather than assumed,
    # because it is the fact the assertions below have to work around — and
    # the flat card reads back equal in the canonical spelling the two
    # copies share.
    assert type(record) is not providers.ScheduledRun
    assert record.recorded is True
    assert record.window.duration == timedelta(hours=1)
    assert record.pricing.text() == providers.PeakPricing().text()


def test_the_scanned_member_is_a_second_module_object():
    # The trap this suite works around, pinned as a fact: the loader imports
    # each member under a private name by file path, so the class a
    # *scanned* store is an instance of is not the class the
    # directly-imported ``providers`` names — ``isinstance`` across that
    # boundary is False for one and the same source file, which is exactly
    # why every entry point of this feature recognises configurations by
    # their parts.
    import providers._schedule as direct

    scanned = importlib.import_module("_nullius_scanned_providers._schedule")
    assert scanned is not direct
    assert scanned.DepthRunWindows is not direct.DepthRunWindows
    assert scanned.DepthRunWindows.__name__ == direct.DepthRunWindows.__name__


def test_the_application_hands_back_the_composed_scheduler(monkeypatch, tmp_path):
    # A caller reaching the composed application gets feature 202's store.
    # The class check is by name for the reason the scanned-module test
    # records.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'composed-schedule.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = create_app().get(providers.DEPTH_RUN_WINDOW_COMPONENT)

    assert store is not None
    assert type(store).__name__ == "DepthRunWindows"
    assert store.database_url == url
    # The composed store is the *deployment's* — its surface is the member's
    # public one, reached through the application rather than the module.
    assert callable(store.schedule) and callable(store.get)


def test_an_application_in_hand_answers_from_its_own_component_map(
    monkeypatch, tmp_path
):
    # The entry point a caller inside a request has: with the application in
    # hand, no second composition happens — asserted by composing once and
    # checking the answer is *that* application's component.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'handed-schedule.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    application = create_app()
    store = application.get(providers.DEPTH_RUN_WINDOW_COMPONENT)

    assert store is dict(application.components)[providers.DEPTH_RUN_WINDOW_COMPONENT]
    assert store.database_url == url


def test_the_application_answers_none_when_the_component_contributes_none(
    monkeypatch,
):
    # The deployed shape of "no store": the component *is* registered and
    # its builder contributed ``None``, so the application answers ``None`` —
    # faithfully reporting the application, and indistinguishable here (by
    # design) from the unregistered case below.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.module_loader import create_app

    assert create_app().get(providers.DEPTH_RUN_WINDOW_COMPONENT) is None


def test_an_empty_workspace_answers_none(tmp_path):
    # The factory's degrade-don't-break stance: an
    # application with no components at all answers ``None`` rather than
    # raising.  Composed into a *fresh* registry — the module-level one
    # already holds every component this process imported, so scanning an
    # empty root against it would still be a full application.
    from app.module_loader import Registration, create_app

    empty = create_app(tmp_path, registry=Registration())
    assert empty.order == ()
    assert empty.get(providers.DEPTH_RUN_WINDOW_COMPONENT) is None


def test_importing_the_member_imports_the_loader():
    # The direction of the dependency, checked in a fresh interpreter: the
    # member imports the loader (for ``register``) on its own import.
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parents[3]
    code = (
        "import sys; sys.path.insert(0, 'src'); sys.path.insert(0, "
        "'packages/providers/src'); import providers; "
        "print('loader' if 'app.module_loader' in sys.modules else 'no-loader')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.split() == ["loader"]
