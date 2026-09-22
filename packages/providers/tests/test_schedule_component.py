"""Feature 202's wiring: the run-window store is composed by convention, and seated.

The same two halves :mod:`tests.test_pin_component` states for feature 203's
store, asked about feature 202's — and for the same reasons, worth restating
in this file's terms rather than by reference, because they are properties of
*this* feature's landing.  The **registration** half asks whether ``import
providers`` joins the application with a scheduler in it — no central
registry, router, entry-points table or factory edited, which is what lets
this feature land in parallel with every other one.  The **seat** half asks
whether ``app.modules.providers`` hands that scheduler back to a caller
reaching the app package rather than the member, and whether the seat's name
for it and the member's are still one name.

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
import pytest

#: The seat's module path, spelled the way the loader spells every seat.  The
#: import happens inside the tests rather than at module scope for the reason
#: :mod:`tests.test_pin_component` gives: the seat pulls in the ``app``
#: package, and this member suite only reaches it once the repository root is
#: on ``sys.path``.
SEAT = "app.modules.providers"


@pytest.fixture
def app_on_the_path(monkeypatch):
    """Make ``app`` importable, then hand back the seat module.

    The member suite does not depend on the ``app`` package — it must not, or
    the member could not be tested on its own — so the seat is imported here
    with the repository root spliced onto ``sys.path``, and the splice is
    undone afterwards.
    """
    root = str(pathlib.Path(__file__).resolve().parents[3])
    monkeypatch.syspath_prepend(root)
    return importlib.import_module(SEAT)


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


# ── The seat: the app package's way to the same scheduler ─────────────────────


def test_the_seat_names_the_same_component_the_member_registers(app_on_the_path):
    # Two spellings of one component name, in two packages that must not
    # import each other: the seat cannot import the member's constant
    # without making the app package depend on a workspace member, so the
    # two are pinned against each other here.  A drift would make the seat
    # silently answer ``None`` for a component that *is* composed — the
    # failure mode with no error message anywhere.
    assert app_on_the_path.DEPTH_RUN_WINDOWS_NAME == providers.DEPTH_RUN_WINDOW_COMPONENT


def test_the_seat_carries_this_features_two_exports(app_on_the_path):
    # The seat's shape for this feature, asserted by membership (the
    # exhaustive what-else assertion lives in the pin suite's seat test,
    # which this feature widened rather than replaced): a name and an
    # accessor, and no re-export of the records or the error vocabulary —
    # those are the member's one spelling.
    assert "DEPTH_RUN_WINDOWS_NAME" in app_on_the_path.__all__
    assert "depth_run_windows_component" in app_on_the_path.__all__
    assert callable(app_on_the_path.depth_run_windows_component)


def test_the_composed_scheduler_raises_this_features_errors_by_name(
    app_on_the_path, monkeypatch, tmp_path
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
    store = create_app().get(app_on_the_path.DEPTH_RUN_WINDOWS_NAME)

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
    app_on_the_path, monkeypatch, campaign_database, plant_campaign
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
    store = create_app().get(app_on_the_path.DEPTH_RUN_WINDOWS_NAME)

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


def test_the_scanned_member_is_a_second_module_object(app_on_the_path):
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


def test_the_seat_hands_back_the_composed_scheduler(app_on_the_path, monkeypatch, tmp_path):
    # The seat's whole job: a caller reaching the *app* package gets feature
    # 202's store.  The class check is by name for the reason the scanned-
    # module test records; the identity check is real, because the store is
    # compared against the application's own component.
    url = f"sqlite:///{tmp_path / 'seated-schedule.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = app_on_the_path.depth_run_windows_component()

    assert store is not None
    assert type(store).__name__ == "DepthRunWindows"
    assert store.database_url == url
    # The composed store is the *deployment's* — its surface is the member's
    # public one, reached through the application rather than the module.
    assert callable(store.schedule) and callable(store.get)


def test_the_seat_accepts_an_application_it_was_handed(app_on_the_path, monkeypatch, tmp_path):
    # The seat's other entry point, the one a caller inside a request has:
    # with the application in hand, no second composition happens — asserted
    # by composing once and checking the seat answers from *that*
    # application's component map.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'handed-schedule.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    application = create_app()
    store = app_on_the_path.depth_run_windows_component(application)

    assert store is application.get(app_on_the_path.DEPTH_RUN_WINDOWS_NAME)
    assert store.database_url == url


def test_the_seat_answers_none_when_the_component_contributes_none(
    app_on_the_path, monkeypatch
):
    # The deployed shape of "no store": the component *is* registered and
    # its builder contributed ``None``, so the seat answers ``None`` —
    # faithfully reporting the application, and indistinguishable here (by
    # design) from the unregistered case below.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert app_on_the_path.depth_run_windows_component() is None


def test_the_seat_answers_none_for_an_empty_workspace(app_on_the_path, tmp_path):
    # The factory's degrade-don't-break stance, seen from the seat: an
    # application with no components at all answers ``None`` rather than
    # raising.  Composed into a *fresh* registry — the module-level one
    # already holds every component this process imported, so scanning an
    # empty root against it would still be a full application.
    from app.module_loader import Registration, create_app

    empty = create_app(tmp_path, registry=Registration())
    assert empty.order == ()
    assert app_on_the_path.depth_run_windows_component(empty) is None


def test_importing_the_member_does_not_import_its_own_seat():
    # The direction of the dependency, checked in a fresh interpreter: the
    # member imports the loader (for ``register``) but must not import the
    # seat — ``app.modules.providers`` imports the member, so a member that
    # imported the seat would be a cycle closing only at composition time.
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parents[3]
    code = (
        "import sys; sys.path.insert(0, 'src'); sys.path.insert(0, "
        "'packages/providers/src'); import providers; "
        "print([m for m in sys.modules if m.startswith('app.modules')]); "
        "print('loader' if 'app.module_loader' in sys.modules else 'no-loader')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    seats, loader = completed.stdout.split()
    assert seats == "[]"
    assert loader == "loader"
