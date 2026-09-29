"""Feature 197's wiring: the rotation store is composed by convention.

The same two halves :mod:`tests.test_root_component` states for feature 196's
store, asked about feature 197's — and worth restating in this file's own
terms rather than by reference, because they are properties of *this*
feature's landing.  The **registration** half asks whether ``import
providers`` joins the application with a root-rotation store in it — no
central registry, router, entry-points table or factory edited, which is what
lets this feature land in parallel with every other one.  The **composition**
half asks whether ``create_app().get(...)`` hands that store back under the
member's own component name.

This is the member's **sixth** registration.  The second-composition test
below is the live defect guard for the trap that fact creates: a ``@register``
living in a submodule fires only on the first ``create_app()`` of a process,
so every registration must live in the package ``__init__`` — asserted here
because it is the one failure mode of this feature's wiring that produces no
error message anywhere.
"""

from __future__ import annotations

import providers

# ── The registration: by convention, in the package __init__ ──────────────────


def test_the_member_registers_its_store_under_its_own_name():
    # The decorator fired when this test module imported the member, and the
    # name it registered under is feature 197's — distinct from feature 196's
    # *root-serving-provider*, which is the pair's other half and the one
    # name a careless copy would collide with.
    from app.module_loader import registered_components

    names = {component.name for component in registered_components()}
    assert providers.ROOT_ROTATION_COMPONENT in names
    assert providers.ROOT_ROTATION_COMPONENT != (
        providers.ROOT_SERVING_PROVIDER_COMPONENT
    )


def test_the_two_root_components_are_two_registrations():
    # Both halves of the act are separately discoverable: a deployment can
    # compose the rotation without the provenance record and the other way
    # round, because they are two features' sentences.
    from app.module_loader import registered_components

    names = [component.name for component in registered_components()]
    assert names.count(providers.ROOT_ROTATION_COMPONENT) == 1
    assert names.count(providers.ROOT_SERVING_PROVIDER_COMPONENT) == 1


def test_scanning_composes_the_store_without_a_central_registry():
    from app.module_loader import create_app

    application = create_app()
    assert providers.ROOT_ROTATION_COMPONENT in application.order
    assert providers.ROOT_ROTATION_COMPONENT in dict(application.components)


def test_a_second_composition_in_the_same_process_still_holds_the_store():
    # The submodule-registration trap, asserted directly.  This is the
    # member's sixth registration — added after the first five made the
    # pattern look safe — so the trap is asserted for *this* name rather than
    # inherited from the sibling suite's assertion about another one.
    from app.module_loader import create_app

    first = create_app()
    second = create_app()
    for application in (first, second):
        assert providers.ROOT_ROTATION_COMPONENT in application.order


def test_the_builder_contributes_none_when_no_store_is_named(monkeypatch):
    # A deployment with no ``DATABASE_URL`` composes a ``None`` component
    # rather than an empty store or an exception: absent is a discoverable
    # state, and the caller that *must* decide a campaign's rotation is the
    # caller that must not find itself in it.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert providers.build_root_rotation() is None


def test_the_builder_contributes_a_store_bound_to_the_deployments_url(
    monkeypatch, tmp_path
):
    # ...and with a ``DATABASE_URL`` set, the composed component is the store
    # for *that* deployment.  Construction still opens nothing and creates
    # nothing: composing the application must not bring the member-owned
    # ``root_provider_rotation`` table into being — that is the store's first
    # ``assign``'s job, and nothing else's.
    url = f"sqlite:///{tmp_path / 'composed-rotation.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = providers.build_root_rotation()

    assert isinstance(store, providers.RootRotation)
    assert store.database_url == url
    assert not (tmp_path / "composed-rotation.db").exists()


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
        if component.name == providers.ROOT_ROTATION_COMPONENT
    )
    # The call is the assertion: a builder that demanded an argument raises
    # TypeError here.
    assert builder() is None


# ── The composition: the application's way to the same store ──────────────────


def test_the_application_hands_back_the_store_the_factory_built(
    monkeypatch, tmp_path
):
    # With an application in hand, a ``get`` under the member's component name
    # hands back the store the factory built for this deployment — the same
    # object, not a copy.  It is a *different* object from the sibling root
    # store, because the two are two features' sentences.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'composed-rotation.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    application = create_app()
    store = application.get(providers.ROOT_ROTATION_COMPONENT)
    assert store is dict(application.components)[providers.ROOT_ROTATION_COMPONENT]
    assert store is not application.get(providers.ROOT_SERVING_PROVIDER_COMPONENT)
    # By class *name*, not by ``isinstance``: the composed store is built by
    # the scanned copy of this member, so it is the same source file's class
    # and not this test module's import of it — the double-import the member's
    # seams exist to absorb.
    assert type(store).__name__ == "RootRotation"
    assert type(store).__module__.startswith("_nullius_scanned_providers")
    assert store.database_url == url


def test_the_composed_store_raises_this_features_errors_by_name(
    monkeypatch, tmp_path
):
    # The composed store raises errors from the *scanned* copy of this member,
    # so ``pytest.raises(providers.RootRotationError)`` — the canonical class
    # — does not match them.  The workspace's answer is to assert on the
    # *name*, which the two copies agree on because they are one source file;
    # asserted here because the rest of this member's rotation suite drives
    # the directly-imported store, so nothing else exercises the composed
    # copy's vocabulary.
    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'vocab-rotation.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = create_app().get(providers.ROOT_ROTATION_COMPONENT)

    # A malformed campaign id is refused before any database is opened — which
    # is enough to see the class the composed copy raises, and that it is
    # *this feature's* class by name, not a foreign error type.
    raised: BaseException | None = None
    try:
        store.get("not-a-uuid", "not-a-uuid")
    except Exception as refusal:  # noqa: BLE001 - the class name is the assertion
        raised = refusal
    assert raised is not None, "the composed store accepted a malformed ask"
    assert type(raised).__name__ == type(providers.RootRotationError()).__name__
    assert type(raised).__module__.startswith("_nullius_scanned_providers")


def test_the_composed_stores_flagship_path_works_end_to_end(
    monkeypatch, tmp_path
):
    # Feature 197's sentence, driven through the *composed* store: composition
    # must hand back something that actually assigns a root, not merely
    # something with the right class name.  The node is planted through the
    # same raw statement the member suite's fixture uses, because the composed
    # application is the only thing under test here.
    import sqlite3
    import uuid
    from contextlib import closing

    from conftest import create_schema, load_migration, sqlite_path_of

    from app.module_loader import create_app

    url = f"sqlite:///{tmp_path / 'e2e-rotation.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    # ``0118_node_table`` alone: feature 196's probe reads the tree, and the
    # authoring trio 0115 adds is feature 203's premise, not this feature's.
    assert load_migration("0118_node_table") is not None
    create_schema(url, "0118_node_table")

    node, campaign = str(uuid.uuid4()), str(uuid.uuid4())
    with closing(sqlite3.connect(sqlite_path_of(url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            (node, None, campaign, "macro", 0),
        )

    store = create_app().get(providers.ROOT_ROTATION_COMPONENT)
    tier = providers.FrontierTier(
        providers=(
            providers.FrontierProvider(provider="anthropic", model="claude-opus-5"),
            providers.FrontierProvider(provider="openai", model="gpt-5.6-sol"),
        )
    )

    class Call:
        node_id = node
        campaign_id = campaign
        depth = 0

    assignment = store.assign(Call(), tier)
    assert assignment.node_id == node
    assert assignment.assigned_provider in tier
    assert type(assignment).__name__ == "RootAssignment"
    assert type(assignment).__module__.startswith("_nullius_scanned_providers")
    assert set(store.rotation(campaign)) == {node}
