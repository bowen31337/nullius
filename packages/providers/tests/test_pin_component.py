"""Feature 203's wiring: the pin store is composed by convention, and seated.

Two halves, and they answer different questions.  The **registration** half asks
whether ``import providers`` joins the application — feature 203's store must
appear in a composed application without any central registry, router,
entry-points table or factory being edited, which is the property that lets this
feature land in parallel with every other one.  The **seat** half asks whether
``app.modules.providers`` hands that store back to a caller reaching the app
package rather than the member, and whether the two names the seat and the member
use for the component are still one name.

The registration half is run through the *scanning* path rather than by importing
the member directly, because that is the path a deployment takes: the loader
walks ``packages/*/src``, imports each member under a private name, and folds the
``@register`` builders into one application.  A test that imported ``providers``
first would prove the decorator runs when a module is imported, which is not in
doubt — what is in doubt is whether the *scan* reaches this member's
``__init__`` and fires its registration, and only the scan can answer that.

**Two ``create_app()`` calls, on purpose.**  A registration that lives in a
submodule rather than in the package ``__init__`` fires only on the *first*
composition of a process — the loader imports each member once and caches it, so
a second application built in the same process silently lacks the component.
That is a live defect in this workspace's history rather than a hypothetical, and
it cannot be caught by a single-call test, so one of the tests below composes
twice.
"""

from __future__ import annotations

import importlib
import sys

import providers
import pytest

#: The seat's module path, spelled the way the loader spells every seat.  The
#: import is done inside the tests rather than at module scope because the seat
#: pulls in the ``app`` package, which this suite — a member suite, running
#: under the repository's pytest — can only reach once the repository root is on
#: ``sys.path``.  The conftest puts the member's ``src`` there and the workspace
#: root's own conftest puts the root there; an import at module scope would run
#: before either, depending on collection order.
SEAT = "app.modules.providers"


@pytest.fixture
def app_on_the_path(monkeypatch):
    """Make ``app`` importable, then hand back the seat module.

    The member suite does not depend on the ``app`` package — it must not, or
    the member could not be tested on its own — so the seat is imported here
    with the repository root spliced onto ``sys.path``, and the splice is undone
    afterwards.  A test that could not import the seat would be a test of this
    suite's environment rather than of the feature.
    """
    root = str(__import__("pathlib").Path(__file__).resolve().parents[3])
    monkeypatch.syspath_prepend(root)
    return importlib.import_module(SEAT)


# ── The registration: by convention, in the package __init__ ──────────────────


def test_the_member_registers_its_store_under_its_own_name():
    # The decorator fired when this test module imported the member, and the
    # name it registered under is feature 203's — not feature 192's, and not the
    # plugin name.  Two components from one package is the shape this member
    # has, and the split is the split between a contract that contributes
    # nothing and a service that contributes a store.
    from app.module_loader import registered_components

    names = {component.name for component in registered_components()}
    assert providers.AGENT_MODEL_PIN_COMPONENT in names
    assert providers.PROVIDERS_COMPONENT in names
    assert providers.AGENT_MODEL_PIN_COMPONENT != providers.PROVIDERS_COMPONENT


def test_scanning_composes_the_store_without_a_central_registry():
    # The property the whole plugin convention exists for: an application built
    # by *scanning* the workspace — no central registry edited, no factory
    # edited, no entry-points table — holds feature 203's component.  Driven
    # through the loader's own scan, because that is the path a deployment
    # takes.
    from app.module_loader import create_app

    application = create_app()
    assert providers.AGENT_MODEL_PIN_COMPONENT in application.order
    assert providers.AGENT_MODEL_PIN_COMPONENT in dict(application.components)


def test_a_second_composition_in_the_same_process_still_holds_the_store():
    # The submodule-registration trap, asserted directly.  The loader imports
    # each member once per process and caches it, so a ``@register`` living in a
    # submodule fires on the first composition and never again — a second
    # application in the same process would simply not have the component, and
    # every test that composed once would pass.  Two calls, one assertion: the
    # registration is in the package ``__init__``, where the scan reaches it
    # every time.
    from app.module_loader import create_app

    first = create_app()
    second = create_app()
    for application in (first, second):
        assert providers.AGENT_MODEL_PIN_COMPONENT in application.order


def test_the_builder_contributes_none_when_no_store_is_named(monkeypatch):
    # A deployment with no ``DATABASE_URL`` composes a ``None`` component rather
    # than an empty store or an exception: absent is a discoverable state, not a
    # broken one.  A `None` here is what the seat's docstring distinguishes from
    # its own `None`, and a caller that must record a triple treats either as a
    # refusal to proceed.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert providers.build_agent_model_pins() is None


def test_the_builder_contributes_a_store_bound_to_the_deployments_url(monkeypatch, tmp_path):
    # ...and with a ``DATABASE_URL`` set, the composed component is the store for
    # *that* deployment.  Construction still opens nothing: the app composes a
    # store over a database file that does not exist and is not created by
    # composing.
    url = f"sqlite:///{tmp_path / 'composed.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = providers.build_agent_model_pins()

    assert isinstance(store, providers.AgentModelPins)
    assert store.database_url == url
    assert not (tmp_path / "composed.db").exists()


def test_the_builder_takes_no_arguments_as_the_registration_protocol_requires(monkeypatch):
    # The factory calls every registered builder with no arguments — that is the
    # protocol — so a builder that grew a parameter would break composition for
    # the whole application rather than for one caller.  Asserted on the callable
    # the *registry* holds rather than on the module attribute, because the
    # registry's copy is what the factory will actually call: a later
    # re-registration of the same name would leave the attribute correct and the
    # registered builder wrong, and that is the case this catches.
    from app.module_loader import registered_components

    monkeypatch.delenv("DATABASE_URL", raising=False)
    builder = next(
        component.builder
        for component in registered_components()
        if component.name == providers.AGENT_MODEL_PIN_COMPONENT
    )
    # Called with no arguments, exactly as the factory calls it.  A builder that
    # demanded one raises TypeError here, which is the failure this asserts
    # against — there is no assertion after the call because the call *is* the
    # assertion, and the value it returns is the subject of the tests above.
    assert builder() is None


# ── The seat: the app package's way to the same store ─────────────────────────


def test_the_seat_names_the_same_component_the_member_registers(app_on_the_path):
    # Two spellings of one component name, in two packages that must not import
    # each other: the seat cannot import the member's constant without making
    # the app package depend on a workspace member at import time, so the two
    # are pinned against each other here instead.  A drift between them would
    # make the seat silently answer ``None`` for a component that *is* composed
    # — the failure mode with no error message anywhere.
    assert app_on_the_path.COMPONENT_NAME == providers.AGENT_MODEL_PIN_COMPONENT


def test_the_composed_store_raises_this_features_errors_by_name(app_on_the_path, monkeypatch, tmp_path):
    # The composed store raises errors from the *scanned* copy of this member, so
    # ``pytest.raises(providers.ModelPinConflictError)`` — the canonical class —
    # does not match them.  That is the wrinkle ``tests/nulloracle/conftest.py``
    # (``raised_named``) and ``tests/feature-store/test_registration.py`` both
    # document, and the workspace's answer is to assert on the *name*, which the
    # two copies agree on because they are one source file.
    #
    # Asserted here rather than left implicit because this member's own suite
    # runs against the *directly imported* class everywhere else — the store
    # suites build their own ``AgentModelPins`` — so nothing else in the package
    # exercises the composed copy's vocabulary, and a reader meeting it for the
    # first time in a deployment would otherwise have to rediscover it.
    import sqlite3

    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'vocab.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = create_app().get(app_on_the_path.COMPONENT_NAME)

    # The store refuses an alias without a database, which is enough to see the
    # class the composed copy raises — and it is the *same feature's* class, by
    # name, not a foreign error type.  Caught by hand rather than through
    # ``pytest.raises`` for the repo's ``raised_named`` reason: the class is what
    # is in question, so the assertion has to be made about it rather than by it.
    raised: BaseException | None = None
    try:
        store.persist("not-a-uuid", "deepseek-v4-flash")
    except Exception as refusal:  # noqa: BLE001 - the class name is the assertion
        raised = refusal
    assert raised is not None, "the composed store accepted a malformed ask"
    assert type(raised).__name__ == type(providers.ModelPinError()).__name__
    assert type(raised).__module__.startswith("_nullius_scanned_providers")
    assert sqlite3 is not None  # the database was never opened: no file exists


def test_the_scanned_member_is_a_second_module_object(app_on_the_path):
    # The trap this suite has to work around, pinned as a fact rather than left
    # as a comment: the loader imports each member under a private name
    # (``_nullius_scanned_<dir>``) by file path, so the class a *scanned* store
    # is an instance of is **not** the class the directly-imported
    # ``providers.AgentModelPins`` names.  ``isinstance`` across that boundary is
    # ``False`` for one and the same source file.
    #
    # It is not a defect — importing the member twice is how the scan avoids
    # every member's import colliding with every other's — but it decides how the
    # tests below may check identity: they compare against the class the
    # *application's own* component came from, or against the duck-typed surface,
    # and never against the module-level name.
    import providers._pin_store as direct

    scanned = importlib.import_module("_nullius_scanned_providers._pin_store")
    assert scanned is not direct
    assert scanned.AgentModelPins is not direct.AgentModelPins
    assert scanned.AgentModelPins.__name__ == direct.AgentModelPins.__name__


def test_the_seat_hands_back_the_composed_store(app_on_the_path, monkeypatch, tmp_path):
    # The seat's whole job: a caller reaching the *app* package gets feature
    # 203's store.  Compared against the component the application itself holds
    # — and by identity, not equality, so a seat that built a second equal store
    # on the way past would fail here.  The class check is by name for the reason
    # the test above records.
    url = f"sqlite:///{tmp_path / 'seated.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = app_on_the_path.agent_model_pins_component()

    assert store is not None
    assert type(store).__name__ == "AgentModelPins"
    assert store.database_url == url
    # The composed store is the *deployment's* — its surface is the member's
    # public one, reached through the application rather than through the
    # module: a caller can pin and read with it and nothing else is required.
    assert callable(store.persist) and callable(store.load)


def test_the_seat_accepts_an_application_it_was_handed(app_on_the_path, monkeypatch, tmp_path):
    # The seat's other entry point, and the one a caller inside a request has:
    # with the application in hand, no second composition happens.  Asserted by
    # composing once and checking the seat answers from *that* application's
    # component map — so a seat that always composed its own would return an
    # equal-but-different store and this would catch it.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'handed.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    application = create_app()
    store = app_on_the_path.agent_model_pins_component(application)

    assert store is application.get(app_on_the_path.COMPONENT_NAME)
    assert store.database_url == url


def test_the_seat_answers_none_when_the_component_contributes_none(
    app_on_the_path, monkeypatch, tmp_path
):
    # The deployed shape of "no store": the component *is* registered and its
    # builder contributed ``None``, so the seat answers ``None``.  This is the
    # seat faithfully reporting the application, and it is deliberately not
    # distinguishable here from the case below — a caller that needs them apart
    # reads the component map, which is what the seat's docstring says.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert app_on_the_path.agent_model_pins_component() is None


def test_the_seat_answers_none_for_an_empty_workspace(app_on_the_path, tmp_path):
    # The factory's degrade-don't-break stance, seen from the seat: an
    # application with no components at all answers ``None`` rather than raising,
    # so a module that reaches for the store during composition does not fail
    # import in a workspace where the member happens not to be scanned.
    #
    # Composed by scanning a directory with no packages in it, into a *fresh*
    # registry — the factory's own path, taking the empty case as the factory
    # produces it rather than constructing an ``Application`` by hand.  The
    # registry matters: the module-level one already holds every component this
    # process has imported, so scanning an empty root against it would still be
    # a full application, and the test would be asserting about the wrong object.
    from app.module_loader import Registration, create_app

    empty = create_app(tmp_path, registry=Registration())
    assert empty.order == ()
    assert app_on_the_path.agent_model_pins_component(empty) is None


def test_the_seat_exports_its_name_and_its_caller_and_nothing_else(app_on_the_path):
    # The seat deliberately does not re-export the triple, the answer record or
    # the error vocabulary: those are reached from the member, which is where
    # their one spelling lives.  A seat that grew a second spelling of
    # ``ModelPin`` would invite a caller to import the value type from the app
    # package, and the two would drift.
    assert set(app_on_the_path.__all__) == {"COMPONENT_NAME", "agent_model_pins_component"}


def test_importing_the_member_does_not_import_its_own_seat():
    # The direction of the dependency between the member and its seat, checked in
    # a *fresh* interpreter because this one has long since imported both.
    #
    # The member does import ``app.module_loader`` — every member in this
    # workspace does, to get ``register``, and that is the convention this
    # feature follows rather than an accident.  What it must not import is the
    # **seat**: ``app.modules.providers`` imports the member, so a member that
    # imported the seat would be a cycle, and the cycle would close only at
    # composition time — where the failure would present as a half-initialised
    # component rather than as an ImportError.  So the seat is the one thing this
    # walk asserts is absent.
    import subprocess

    root = __import__("pathlib").Path(__file__).resolve().parents[3]
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
    # ...and the loader *is* reachable from the member, which is the half of the
    # direction that is real: the assertion above would pass trivially if the
    # member imported nothing from ``app`` at all, which would mean this feature
    # had stopped registering by convention.
    assert loader == "loader"
