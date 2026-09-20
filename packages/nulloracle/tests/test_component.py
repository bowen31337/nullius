"""The plugin seam: composition via the module loader.

This is the registration contract from the other side — the factory scans
the workspace members, imports this package, and the ``@register`` builder
lands in the composed application as the ``nulloracle`` component.  No
registry, router or factory was edited to make that true; this test exists
to keep it true.

Two properties of the loader shape these tests:

* it imports each member under a synthetic module name
  (``_nullius_scanned_nulloracle``), so a package this suite also imported
  canonically as ``nulloracle`` exists in the process twice, with two
  distinct class objects.  ``isinstance`` across the copies cannot hold, so
  the composed component is pinned by class name and by behaviour.
* it re-executes a package's ``__init__`` on **every** ``create_app()`` but
  does not re-execute an already-cached submodule.  So a ``@register`` that
  lived in a submodule would fire on the first composition of a process and
  silently drop out of every later one —
  :func:`test_the_component_survives_a_second_composition` is what catches
  that, and it must assert on the *second* application or it passes
  vacuously.

The load-bearing property, and the one this member is most exposed on: **the
builder must never raise.**  The factory builds every registered component on
every ``create_app()``, so a builder that raised on an unconfigured
environment would take composition down for every unrelated feature in the
workspace.  The tests below pin that for each way this member's environment
can be unconfigured — no path, no key, a key reference naming a backend it
does not speak.
"""

from __future__ import annotations

import pytest

from app.module_loader import Registration, create_app, scan_components
from nulloracle import COMPONENT_NAME


def _assert_is_the_null_sidecar(component: object) -> None:
    assert type(component).__name__ == "NullSidecar"
    assert type(component).__module__.endswith("nulloracle.sidecar")
    # The write and the read both hang off the composed component: a
    # composition that carried one but not the other would be a plugin
    # half-wired, and feature 109 needs both directions.
    for operation in ("write", "open", "assignment", "exists"):
        assert callable(getattr(component, operation)), operation


def test_workspace_scan_discovers_the_nulloracle_component() -> None:
    # Bare scan_components() follows the declared workspace: the member
    # under packages/nulloracle/ is imported and its @register fires.
    names = [component.name for component in scan_components()]
    assert COMPONENT_NAME in names


def test_scan_is_idempotent_per_component_name() -> None:
    # A rescan re-imports the package under its scanned alias; the registry
    # replaces by name, so exactly one component survives however many scans
    # ran.
    scan_components()
    names = [component.name for component in scan_components()]
    assert names.count(COMPONENT_NAME) == 1


def test_the_member_registers_under_a_name_matching_its_directory() -> None:
    # The hyphen-free spelling is the plugin name the spec's features carry
    # (plugin="nulloracle"), so the component key, the app-namespace seat
    # and the spec cannot drift apart.
    assert COMPONENT_NAME == "nulloracle"


def test_create_app_composes_a_sidecar_when_the_environment_configures_one(
    sidecar_path, key_ref: str
) -> None:
    app = create_app()
    component = app.get(COMPONENT_NAME)
    _assert_is_the_null_sidecar(component)
    assert component.path == sidecar_path
    assert COMPONENT_NAME in app
    assert COMPONENT_NAME in app.order


def test_composing_touches_no_file(sidecar_path, key_ref: str) -> None:
    # Construction performs no I/O: the directory appears on the first
    # write.  That laziness is why a composed application can carry this
    # component in a process that is not the one service account — holding
    # the handle opens nothing.
    app = create_app()
    assert app.get(COMPONENT_NAME) is not None
    assert not sidecar_path.exists()
    assert not sidecar_path.parent.exists()


def test_an_environment_with_no_sidecar_configuration_still_composes() -> None:
    # The load-bearing property: with no path and no key at all, the builder
    # returns None and the application composes with every other member
    # intact.
    app = create_app()
    assert app.get(COMPONENT_NAME) is None
    # ...and the other members are still there, which is the point.
    assert "ledger" in app or "feature-store" in app


def test_an_environment_with_a_path_but_no_key_still_composes(sidecar_path) -> None:
    app = create_app()
    assert app.get(COMPONENT_NAME) is None


def test_an_environment_with_a_key_but_no_place_still_composes(
    monkeypatch: pytest.MonkeyPatch, key_ref: str
) -> None:
    import app.module_loader as loader

    monkeypatch.setattr(loader, "find_workspace_root", lambda *a, **k: None)
    monkeypatch.delenv("LAKE_ROOT", raising=False)
    app = create_app()
    assert app.get(COMPONENT_NAME) is None


@pytest.mark.parametrize("scheme", ["kms", "sops"])
def test_a_backend_reference_does_not_take_composition_down(
    sidecar_path, monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    # A deployment that named a KMS is a deployment expecting a sidecar, and
    # this component still does not compose for it — but it degrades rather
    # than raising, because raising here would take down every other
    # member's component too.  A process that truly requires a sidecar asks
    # ensure_key() at its own startup, where the named error is right.
    from nulloracle import KEY_REF_ENV

    monkeypatch.setenv(KEY_REF_ENV, f"{scheme}:some-target")
    app = create_app()
    assert app.get(COMPONENT_NAME) is None


def test_the_component_survives_a_second_composition(
    sidecar_path, key_ref: str
) -> None:
    # Must assert on the SECOND application or it passes vacuously: the
    # loader re-executes __init__ on every create_app(), so a @register that
    # lived in a submodule would be present in the first and absent here.
    create_app()
    second = create_app()
    _assert_is_the_null_sidecar(second.get(COMPONENT_NAME))


def test_the_builder_is_on_the_package_import_path() -> None:
    # A @register in a submodule fires once per process and then silently
    # drops out; the builder importable from the package root is what makes
    # the registration survive re-composition.
    import nulloracle

    assert callable(nulloracle.build_null_sidecar)
    assert nulloracle.build_null_sidecar.__module__.endswith("nulloracle")


def test_a_scan_into_an_isolated_registry_finds_the_component() -> None:
    # The registry is a first-class object rather than a hidden global, so a
    # scan into one of the caller's own must find this member too.
    registry = Registration()
    components = scan_components(registry=registry)
    assert COMPONENT_NAME in [component.name for component in components]
    assert COMPONENT_NAME in registry


def test_the_builder_takes_no_arguments() -> None:
    # The factory's registration protocol: a builder is a zero-argument
    # callable, and a component that needed an argument could not be
    # composed by the scan at all.
    import inspect

    import nulloracle

    assert inspect.signature(nulloracle.build_null_sidecar).parameters == {}


class TestTheScannedCopyInteroperates:
    """The composed component's classes are not this suite's classes.

    The loader imports each member under a synthetic module name, so a
    process that both scans and imports canonically holds two of every class.
    An ``isinstance`` check anywhere in the write path would refuse the very
    values the composed component hands out — which is a real failure, not a
    theoretical one: the composed sidecar's ``open()`` and this suite's
    ``NullAssignment`` are different classes, and a caller round-tripping an
    assignment through both must be understood.

    These tests exercise exactly that: values and keys minted by the
    *scanned* classes, handed to the *canonically imported* API.
    """

    def _scanned_sidecar(self, sidecar_path, key_ref: str):
        app = create_app()
        component = app.get(COMPONENT_NAME)
        assert component is not None
        return component

    def test_a_scanned_assignment_is_accepted_by_the_canonical_api(
        self, sidecar_path, key_ref: str
    ) -> None:
        from nulloracle import NullAssignment, canonical_assignments

        scanned = self._scanned_sidecar(sidecar_path, key_ref)
        # An assignment minted by the scanned copy of the class...
        scanned.write(
            [
                NullAssignment(
                    node_id="6ee6bf93-8326-48f8-b4d5-921662768f45",
                    is_null=True,
                    perm_seed=4,
                )
            ]
        )
        # ...reads back through the scanned component as the scanned class...
        reopened = scanned.open()
        (value,) = reopened.values()
        assert type(value) is not NullAssignment
        # ...and the canonical API still seals it, because the contract it
        # needs is the schema, not the class object.
        assert canonical_assignments(reopened) == canonical_assignments(
            {value.node_id: NullAssignment(
                node_id=value.node_id, is_null=True, perm_seed=4
            )}
        )

    def test_a_scanned_key_is_accepted_by_the_canonical_seal(
        self, sidecar_path, key_ref: str
    ) -> None:
        # The composed sidecar holds a SidecarKey minted by the scanned
        # module; the canonical seal() must accept it rather than refusing
        # the key the factory handed out.
        from nulloracle import open_envelope, seal

        scanned = self._scanned_sidecar(sidecar_path, key_ref)
        scanned_key = scanned._key
        from nulloracle import SidecarKey

        assert type(scanned_key) is not SidecarKey
        assert open_envelope(seal(b"payload", scanned_key), scanned_key) == b"payload"

    def test_an_object_with_a_useless_reveal_is_refused(
        self, test_key: SidecarKey
    ) -> None:
        # The structural acceptance is only one step deep: whatever reveal()
        # produces must still be key material of the accepted length, so an
        # unrelated object cannot ride in on a duck-typed attribute.
        from nulloracle import SidecarKeyError, seal

        class NotAKey:
            def reveal(self):
                return "not key material"

        with pytest.raises(SidecarKeyError, match="must be a SidecarKey or 32 raw"):
            seal(b"payload", NotAKey())

    def test_an_object_whose_reveal_raises_is_refused(self) -> None:
        from nulloracle import SidecarKeyError, seal

        class Exploding:
            def reveal(self):
                raise RuntimeError("boom")

        with pytest.raises(SidecarKeyError, match="reveal\\(\\) raised"):
            seal(b"payload", Exploding())
