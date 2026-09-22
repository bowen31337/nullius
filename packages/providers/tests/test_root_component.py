"""Feature 196's wiring: the root-provenance store is composed by convention, and seated.

The same two halves :mod:`tests.test_pin_component` states for feature 203's
store and :mod:`tests.test_cache_component` restates for 200's, asked about
feature 196's — and worth restating in this file's terms rather than by
reference, because they are properties of *this* feature's landing.  The
**registration** half asks whether ``import providers`` joins the application
with a root-serving-provider store in it — no central registry, router,
entry-points table or factory edited, which is what lets this feature land in
parallel with every other one.  The **seat** half asks whether
``app.modules.providers`` hands that store back to a caller reaching the app
package rather than the member, and whether the seat's name for it and the
member's are still one name.

The registration half runs through the *scanning* path, because that is the
path a deployment takes — and the second-composition test below is the live
defect guard: a ``@register`` living in a submodule fires only on the first
``create_app()`` of a process, which is precisely the trap this member's five
registrations live in the package ``__init__`` to avoid.  This one is the
fifth, added after the first four had made the pattern look safe.
"""

from __future__ import annotations

import importlib
import pathlib

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


def test_the_member_registers_its_store_under_its_own_name():
    # The decorator fired when this test module imported the member, and the
    # name it registered under is feature 196's — distinct from the
    # interface's and from every other store's, on the same
    # plugin-plus-contribution pattern the pin store set for a member's later
    # components.
    from app.module_loader import registered_components

    names = {component.name for component in registered_components()}
    assert providers.ROOT_SERVING_PROVIDER_COMPONENT in names
    assert providers.ROOT_SERVING_PROVIDER_COMPONENT not in (
        providers.PROVIDERS_COMPONENT,
        providers.AGENT_MODEL_PIN_COMPONENT,
        providers.DEPTH_RUN_WINDOW_COMPONENT,
        providers.DEPTH_CACHE_RATE_COMPONENT,
    )


def test_scanning_composes_the_store_without_a_central_registry():
    # The property the plugin convention exists for: an application built by
    # *scanning* the workspace holds feature 196's component, driven through
    # the loader's own scan because that is the path a deployment takes.
    from app.module_loader import create_app

    application = create_app()
    assert providers.ROOT_SERVING_PROVIDER_COMPONENT in application.order
    assert providers.ROOT_SERVING_PROVIDER_COMPONENT in dict(application.components)


def test_a_second_composition_in_the_same_process_still_holds_the_store():
    # The submodule-registration trap, asserted directly: the loader imports
    # each member once per process, so a ``@register`` living anywhere but
    # the package ``__init__`` would silently vanish from every composition
    # after the first.  Two calls, one assertion each — this member's fifth
    # registration is where the trap would bite, added long after the first
    # four made the pattern look safe.
    from app.module_loader import create_app

    first = create_app()
    second = create_app()
    for application in (first, second):
        assert providers.ROOT_SERVING_PROVIDER_COMPONENT in application.order


def test_the_builder_contributes_none_when_no_store_is_named(monkeypatch):
    # A deployment with no ``DATABASE_URL`` composes a ``None`` component
    # rather than an empty store or an exception: absent is a discoverable
    # state, and — the builder's own docstring draws the line — a ``None``
    # here is a refusal to record, never a store that happens to find every
    # root call unrecorded.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert providers.build_root_provider_rotation() is None


def test_the_builder_contributes_a_store_bound_to_the_deployments_url(
    monkeypatch, tmp_path
):
    # ...and with a ``DATABASE_URL`` set, the composed component is the store
    # for *that* deployment.  Construction still opens nothing and creates
    # nothing: composing the application must not bring the member-owned
    # ``root_serving_provider`` table into being — that is the store's first
    # ``record``'s job, and nothing else's.  A ``get`` does not do it either,
    # which is the one place this store differs from its siblings: it reads
    # ``sqlite_master`` and answers ``None``.
    url = f"sqlite:///{tmp_path / 'composed-root-providers.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = providers.build_root_provider_rotation()

    assert isinstance(store, providers.RootProviderRotation)
    assert store.database_url == url
    assert not (tmp_path / "composed-root-providers.db").exists()


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
        if component.name == providers.ROOT_SERVING_PROVIDER_COMPONENT
    )
    # The call is the assertion: a builder that demanded an argument raises
    # TypeError here.
    assert builder() is None


# ── The seat: the app package's way to the same store ─────────────────────────


def test_the_seat_names_the_same_component_the_member_registers(app_on_the_path):
    # Two spellings of one component name, in two packages that must not
    # import each other: the seat cannot import the member's constant
    # without making the app package depend on a workspace member, so the
    # two are pinned against each other here.  A drift would make the seat
    # silently answer ``None`` for a component that *is* composed — the
    # failure mode with no error message anywhere.
    assert (
        app_on_the_path.ROOT_SERVING_PROVIDER_NAME
        == providers.ROOT_SERVING_PROVIDER_COMPONENT
    )


def test_the_seat_carries_this_features_two_exports(app_on_the_path):
    # The seat's shape for this feature, asserted by membership (the
    # exhaustive what-else assertion lives in the pin suite's seat test,
    # which this feature widened rather than replaced): a name and an
    # accessor, and no re-export of the records or the error vocabulary —
    # those are the member's one spelling.
    assert "ROOT_SERVING_PROVIDER_NAME" in app_on_the_path.__all__
    assert "root_serving_providers_component" in app_on_the_path.__all__
    assert callable(app_on_the_path.root_serving_providers_component)
    # ...and the records stay the member's: a seat that re-exported
    # ``RootCallProvider`` would be a second spelling of the member's surface.
    assert not hasattr(app_on_the_path, "RootCallProvider")
    assert not hasattr(app_on_the_path, "RootProviderError")


def test_the_seat_asks_the_factory_for_the_component_it_names(
    app_on_the_path, monkeypatch, tmp_path
):
    # The accessor's contract, on the seat's own terms: with an application
    # in hand it reads that application, and what it hands back is the store
    # the factory built for this deployment — the same object, not a copy.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'seated-root-providers.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    application = create_app()
    store = app_on_the_path.root_serving_providers_component(application)
    assert store is application.get(app_on_the_path.ROOT_SERVING_PROVIDER_NAME)
    # By class *name*, not by ``isinstance``: the composed store is built by
    # the scanned copy of this member, so it is the same source file's class
    # and not this test module's import of it — the double-import the member's
    # seams exist to absorb, and the reason the assertion below is spelled
    # this way rather than reached through ``providers``.
    assert type(store).__name__ == "RootProviderRotation"
    assert type(store).__module__.startswith("_nullius_scanned_providers")
    assert store.database_url == url


def test_the_composed_store_raises_this_features_errors_by_name(
    app_on_the_path, monkeypatch, tmp_path
):
    # The composed store raises errors from the *scanned* copy of this
    # member, so ``pytest.raises(providers.RootProviderError)`` — the
    # canonical class — does not match them.  The workspace's answer is to
    # assert on the *name*, which the two copies agree on because they are
    # one source file; asserted here because the rest of this member's root
    # suite drives the directly-imported store, so nothing else exercises
    # the composed copy's vocabulary.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'vocab-root-providers.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = create_app().get(app_on_the_path.ROOT_SERVING_PROVIDER_NAME)

    # A malformed node id is refused before any database is opened — which
    # is enough to see the class the composed copy raises, and that it is
    # *this feature's* class by name, not a foreign error type.
    raised: BaseException | None = None
    try:
        store.get("not-a-uuid")
    except Exception as refusal:  # noqa: BLE001 - the class name is the assertion
        raised = refusal
    assert raised is not None, "the composed store accepted a malformed ask"
    assert type(raised).__name__ == type(providers.RootProviderError()).__name__
    assert type(raised).__module__.startswith("_nullius_scanned_providers")
