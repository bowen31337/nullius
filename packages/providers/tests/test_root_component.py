"""Feature 196's wiring: the root-provenance store is composed by convention.

The same two halves :mod:`tests.test_pin_component` states for feature 203's
store and :mod:`tests.test_cache_component` restates for 200's, asked about
feature 196's — and worth restating in this file's terms rather than by
reference, because they are properties of *this* feature's landing.  The
**registration** half asks whether ``import providers`` joins the application
with a root-serving-provider store in it — no central registry, router,
entry-points table or factory edited, which is what lets this feature land in
parallel with every other one.  The **composition** half asks whether
``create_app().get(...)`` hands that store back under the member's own
component name.

The registration half runs through the *scanning* path, because that is the
path a deployment takes — and the second-composition test below is the live
defect guard: a ``@register`` living in a submodule fires only on the first
``create_app()`` of a process, which is precisely the trap this member's five
registrations live in the package ``__init__`` to avoid.  This one is the
fifth, added after the first four had made the pattern look safe.
"""

from __future__ import annotations

import providers

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


# ── The composition: the application's way to the same store ──────────────────


def test_the_application_hands_back_the_store_the_factory_built(
    monkeypatch, tmp_path
):
    # With an application in hand, a ``get`` under the member's component
    # name hands back the store the factory built for this deployment — the
    # same object, not a copy.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'composed-root-providers.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    application = create_app()
    store = application.get(providers.ROOT_SERVING_PROVIDER_COMPONENT)
    assert store is dict(application.components)[
        providers.ROOT_SERVING_PROVIDER_COMPONENT
    ]
    # By class *name*, not by ``isinstance``: the composed store is built by
    # the scanned copy of this member, so it is the same source file's class
    # and not this test module's import of it — the double-import the member's
    # seams exist to absorb, and the reason the assertion below is spelled
    # this way rather than reached through ``providers``.
    assert type(store).__name__ == "RootProviderRotation"
    assert type(store).__module__.startswith("_nullius_scanned_providers")
    assert store.database_url == url


def test_the_composed_store_raises_this_features_errors_by_name(
    monkeypatch, tmp_path
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
    store = create_app().get(providers.ROOT_SERVING_PROVIDER_COMPONENT)

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
