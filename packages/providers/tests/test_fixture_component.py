"""Feature 194's wiring: the fixture store is composed by convention, and seated.

The same two halves :mod:`tests.test_cache_component` states for feature 200's
store and :mod:`tests.test_rotation_component` for feature 197's, asked about
feature 194's — and restated in this file's terms rather than by reference,
because they are properties of *this* feature's landing.  The **registration**
half asks whether ``import providers`` joins the application with a fixture
store in it, with no central registry, router, entry-points table or factory
edited — which is what lets this feature land in parallel with every other one.
The **seat** half asks whether ``app.modules.providers`` hands that store back
to a caller reaching the app package rather than the member, and whether the
seat's name for it and the member's are still one name.

Two things are particular to this feature rather than transposed, and both come
from the store being a *directory* where every other seated service in this
member is a *table*:

* the builder resolves ``PROVIDER_FIXTURE_DIR``, not ``DATABASE_URL``, so the
  composition tests below set that variable and deliberately leave the database
  one alone — a fixture store must compose for a deployment that has no
  database at all, or the store would be unusable by exactly the offline
  capture runs it exists for;
* composing must create **nothing**, which is asserted by observing the
  directory rather than by trusting the docstring.  Every other store in this
  member defers its table to its first write; this one defers its *root*, and
  the failure it prevents is a ``create_app()`` that scatters a directory into
  whatever tree the process started in, on every composition, whether or not a
  fixture was ever recorded.

The registration half runs through the *scanning* path, because that is the
path a deployment takes — and the second-composition test is the live defect
guard: a ``@register`` living in a submodule fires only on the first
``create_app()`` of a process, which is precisely the trap this member's
registrations live in the package ``__init__`` to avoid.  This one is the
seventh, added long after the first six made the pattern look safe.
"""

from __future__ import annotations

import importlib
import pathlib

import providers
import pytest

#: The seat's module path, spelled the way the loader spells every seat.  The
#: import happens inside the tests rather than at module scope for the reason
#: :mod:`tests.test_cache_component` gives: the seat pulls in the ``app``
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


@pytest.fixture
def fixture_dir(monkeypatch, tmp_path):
    """Name a fixture root for the deployment, and hand back the path.

    The directory is deliberately **not** created: several tests below assert
    that composing the application does not bring it into being, and a fixture
    that made the directory itself would make those assertions vacuous.
    """
    root = tmp_path / "captured-fixtures"
    monkeypatch.setenv(providers.FIXTURE_DIR_ENV, str(root))
    return root


# ── The registration: by convention, in the package __init__ ──────────────────


def test_the_member_registers_its_store_under_its_own_name():
    # The decorator fired when this test module imported the member, and the
    # name it registered under is feature 194's — distinct from the
    # interface's, the pin store's, the run-window store's, the cache-rate
    # store's, the root-serving store's and the rotation store's, on the same
    # plugin-plus-contribution pattern the pin store set for a member's later
    # components.
    from app.module_loader import registered_components

    names = {component.name for component in registered_components()}
    assert providers.FIXTURE_STORE_COMPONENT in names
    assert providers.FIXTURE_STORE_COMPONENT not in (
        providers.PROVIDERS_COMPONENT,
        providers.AGENT_MODEL_PIN_COMPONENT,
        providers.DEPTH_RUN_WINDOW_COMPONENT,
        providers.DEPTH_CACHE_RATE_COMPONENT,
        providers.ROOT_SERVING_PROVIDER_COMPONENT,
        providers.ROOT_ROTATION_COMPONENT,
    )


def test_scanning_composes_the_store_without_a_central_registry():
    # The property the plugin convention exists for: an application built by
    # *scanning* the workspace holds feature 194's component, driven through
    # the loader's own scan because that is the path a deployment takes.
    from app.module_loader import create_app

    application = create_app()
    assert providers.FIXTURE_STORE_COMPONENT in application.order
    assert providers.FIXTURE_STORE_COMPONENT in dict(application.components)


def test_a_second_composition_in_the_same_process_still_holds_the_store():
    # The submodule-registration trap, asserted directly: the loader imports
    # each member once per process, so a ``@register`` living anywhere but the
    # package ``__init__`` would silently vanish from every composition after
    # the first.  Two calls, one assertion each — this member's seventh
    # registration is where the trap would bite, added long after the first six
    # made the pattern look safe.
    from app.module_loader import create_app

    first = create_app()
    second = create_app()
    for application in (first, second):
        assert providers.FIXTURE_STORE_COMPONENT in application.order


def test_the_builder_contributes_none_when_no_directory_is_named(monkeypatch):
    # A deployment with no ``PROVIDER_FIXTURE_DIR`` composes a ``None``
    # component rather than an empty store or an exception: absent is a
    # discoverable state, and — the builder's own docstring draws the line — a
    # ``None`` here is a refusal to capture, never a store that happens to have
    # recorded nothing yet.  The distinction matters because an empty *store*
    # would accept a `record` and write somewhere; there is no somewhere.
    monkeypatch.delenv(providers.FIXTURE_DIR_ENV, raising=False)
    assert providers.build_fixture_store() is None


def test_the_builder_ignores_the_database_url_entirely(monkeypatch, fixture_dir):
    # The one thing this builder does *not* share with its six siblings, and it
    # is the feature's whole point rather than an accident: a fixture store is a
    # directory, so it must compose for a deployment that names no database —
    # which is exactly the offline capture run a fixture exists for.  A store
    # that read ``DATABASE_URL`` would be unusable there.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = providers.build_fixture_store()

    assert isinstance(store, providers.FixtureStore)
    assert store.root == fixture_dir


def test_the_builder_contributes_a_store_bound_to_the_deployments_directory(
    monkeypatch, fixture_dir
):
    # ...and with the variable named, the composed component is the store for
    # *that* deployment.  Composing still creates nothing: the directory must
    # not come into being on ``create_app()`` — that is the store's first
    # ``record``'s job, and nothing else's.
    store = providers.build_fixture_store()

    assert store.root == fixture_dir
    assert not fixture_dir.exists()


def test_the_builder_takes_no_arguments_as_the_registration_protocol_requires(
    monkeypatch, fixture_dir
):
    # The factory calls every registered builder with no arguments — that is the
    # protocol — so a builder that grew a parameter would break composition for
    # the whole application.  Asserted on the callable the *registry* holds,
    # because that is what the factory will actually call.
    from app.module_loader import registered_components

    builder = next(
        component.builder
        for component in registered_components()
        if component.name == providers.FIXTURE_STORE_COMPONENT
    )
    # The call is the assertion: a builder that demanded an argument raises
    # TypeError here.
    assert builder().root == fixture_dir


# ── The seat: the app package's way to the same store ─────────────────────────


def test_the_seat_names_the_same_component_the_member_registers(app_on_the_path):
    # Two spellings of one component name, in two packages that must not import
    # each other: the seat cannot import the member's constant without making
    # the app package depend on a workspace member, so the two are pinned
    # against each other here.  A drift would make the seat silently answer
    # ``None`` for a component that *is* composed — the failure mode with no
    # error message anywhere.
    assert (
        app_on_the_path.FIXTURE_STORE_NAME == providers.FIXTURE_STORE_COMPONENT
    )


def test_the_seat_carries_this_features_two_exports(app_on_the_path):
    # The seat's shape for this feature, asserted by membership (the exhaustive
    # what-else assertion lives in the pin suite's seat test, which this feature
    # widened rather than replaced): a name and an accessor, and no re-export of
    # the records or the error vocabulary — those are the member's one spelling.
    assert "FIXTURE_STORE_NAME" in app_on_the_path.__all__
    assert "fixture_store_component" in app_on_the_path.__all__
    assert callable(app_on_the_path.fixture_store_component)


def test_the_composed_store_raises_this_features_errors_by_name(
    app_on_the_path, fixture_dir
):
    # The composed store raises errors from the *scanned* copy of this member,
    # so ``pytest.raises(providers.FixtureStoreError)`` — the canonical class —
    # does not match them.  The workspace's answer is to assert on the *name*,
    # which the two copies agree on because they are one source file; asserted
    # here because the rest of this member's fixture suite drives the
    # directly-imported store, so nothing else exercises the composed copy's
    # vocabulary.
    from app.module_loader import create_app

    store = create_app().get(app_on_the_path.FIXTURE_STORE_NAME)

    # A blank root is refused before anything is opened — which is enough to see
    # the class the composed copy raises, and that it is *this feature's* class
    # by name, not a foreign error type.  (`FixtureStore("")` rather than a
    # malformed capture, because the refusal has to happen without the store
    # having a root to write into.)
    raised: BaseException | None = None
    try:
        type(store)("")
    except Exception as refusal:  # noqa: BLE001 - the class name is the assertion
        raised = refusal
    assert raised is not None, "the composed store accepted a blank root"
    assert type(raised).__name__ == type(providers.FixtureStoreError()).__name__
    assert type(raised).__module__.startswith("_nullius_scanned_providers")


def test_the_composed_store_files_the_members_exchanges(app_on_the_path, fixture_dir):
    # The double-import remedy, exercised at the composed seam: an Exchange built
    # from the *directly imported* member is not made of the scanned copy's
    # Request class — ``isinstance`` across the two is False for one and the same
    # source file — and the composed store takes it anyway, recognising the pair
    # by its two named parts and re-making both from its own classes.  A store
    # that gated on ``isinstance`` would refuse a caller for holding the wrong of
    # two classes, which is the whole defect the recognition seam exists for.
    from app.module_loader import create_app

    store = create_app().get(app_on_the_path.FIXTURE_STORE_NAME)
    request = providers.Request(
        messages=(providers.Message(role="user", content="q"),), model="m"
    )
    exchange = providers.Exchange(
        request=request,
        completion=providers.Completion(
            content="a",
            model="m",
            usage=providers.Usage(input_tokens=1, output_tokens=2),
        ),
    )

    filed = store.record(exchange)

    # The fixture is the scanned copy's `FixtureFile` — asserted rather than
    # assumed, because it is the fact the assertions below have to work around —
    # and it is filed under *this* module's canonical key, which is the property
    # the seam exists to guarantee.
    assert type(filed) is not providers.FixtureFile
    assert filed.path.is_file()
    assert filed.key == providers.prompt_hash(request)
    assert type(filed.request) is not providers.Request
    assert filed.request.messages[0].content == "q"


def test_the_scanned_member_is_a_second_module_object(app_on_the_path):
    # The trap this suite works around, pinned as a fact: the loader imports
    # each member under a private name by file path, so the class a *scanned*
    # store is an instance of is not the class the directly-imported
    # ``providers`` names — ``isinstance`` across that boundary is False for one
    # and the same source file, which is exactly why every entry point of this
    # feature recognises values by their parts.
    import providers._fixture as direct

    scanned = importlib.import_module("_nullius_scanned_providers._fixture")
    assert scanned is not direct
    assert scanned.FixtureStore is not direct.FixtureStore
    assert scanned.FixtureStore.__name__ == direct.FixtureStore.__name__


def test_the_seat_hands_back_the_composed_store(app_on_the_path, fixture_dir):
    # The seat's whole job: a caller reaching the *app* package gets feature
    # 194's store.  The class check is by name for the reason the scanned-module
    # test records; the identity check is real, because the store is compared
    # against the application's own component.
    store = app_on_the_path.fixture_store_component()

    assert store is not None
    assert type(store).__name__ == "FixtureStore"
    assert store.root == fixture_dir
    # The composed store is the *deployment's* — its surface is the member's
    # public one, reached through the application rather than the module.
    assert callable(store.record) and callable(store.get)
    # ...and asking for it still created nothing.
    assert not fixture_dir.exists()


def test_the_seat_accepts_an_application_it_was_handed(app_on_the_path, fixture_dir):
    # The seat's other entry point, the one a caller inside a request has: with
    # the application in hand, no second composition happens — asserted by
    # composing once and checking the seat answers from *that* application's
    # component map.
    from app.module_loader import create_app

    application = create_app()
    store = app_on_the_path.fixture_store_component(application)

    assert store is application.get(app_on_the_path.FIXTURE_STORE_NAME)
    assert store.root == fixture_dir


def test_the_seat_answers_none_when_the_component_contributes_none(
    app_on_the_path, monkeypatch
):
    # The deployed shape of "no store": the component *is* registered and its
    # builder contributed ``None``, so the seat answers ``None`` — faithfully
    # reporting the application, and indistinguishable here (by design) from the
    # unregistered case below.
    monkeypatch.delenv(providers.FIXTURE_DIR_ENV, raising=False)
    assert app_on_the_path.fixture_store_component() is None


def test_the_seat_answers_none_for_an_empty_workspace(app_on_the_path, tmp_path):
    # The factory's degrade-don't-break stance, seen from the seat: an
    # application with no components at all answers ``None`` rather than
    # raising.  Composed into a *fresh* registry — the module-level one already
    # holds every component this process imported, so scanning an empty root
    # against it would still be a full application.
    from app.module_loader import Registration, create_app

    empty = create_app(tmp_path, registry=Registration())
    assert empty.order == ()
    assert app_on_the_path.fixture_store_component(empty) is None


def test_importing_the_member_does_not_import_its_own_seat():
    # The direction of the dependency, checked in a fresh interpreter: the
    # member imports the loader (for ``register``) but must not import the seat
    # — ``app.modules.providers`` imports the member, so a member that imported
    # the seat would be a cycle closing only at composition time.
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
