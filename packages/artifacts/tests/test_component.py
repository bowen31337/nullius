"""The plugin seam: composition via the module loader.

This is the registration contract from the other side — the factory
scans the workspace members, imports this package, and the
``@register`` builder lands in the composed application as the
``artifacts`` component, bound to the root ``ARTIFACT_ROOT`` names.  No
registry, router or factory was edited to make that true; this test
exists to keep it true.

Two properties of the loader shape these tests (the same two the
snapshot and null-oracle suites state):

* it imports each member under a synthetic module name
  (``_nullius_scanned_artifacts``), so a package this suite also
  imported canonically as ``artifacts`` exists in the process twice,
  with two distinct class objects.  ``isinstance`` across the copies
  cannot hold, so the composed component is pinned by class name,
  module suffix and — decisively — behaviour.
* it re-executes a package's ``__init__`` on **every** ``create_app()``
  but does not re-execute an already-cached submodule.  So a
  ``@register`` that lived in a submodule would fire on the first
  composition of a process and silently drop out of every later one —
  :func:`test_the_component_survives_a_second_composition` is what
  catches that, and it must assert on the *second* application or it
  passes vacuously.

The builder must also never raise for want of configuration: the
factory builds every registered component on every ``create_app()``,
so a builder that blew up on an unset ``ARTIFACT_ROOT`` would take
composition down for every unrelated feature in the workspace.  The
default root (``artifacts/`` beside the workspace root) is what keeps
it composed everywhere — and the refusal it falls back to when no
root can be named at all is pinned here too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from artifacts import (
    ARTIFACT_ROOT_ENV,
    COMPONENT_NAME,
    ArtifactStore,
    ArtifactStoreError,
)

from app.module_loader import create_app, scan_components


def _assert_is_the_artifact_store(component: object) -> None:
    assert type(component).__name__ == "ArtifactStore"
    assert type(component).__module__.endswith("artifacts._store")
    # Both directions of the store hang off the composed component: the
    # persistence (node_directory, write, commit, discard) and the read
    # the replay path stands on (files, read, campaign_ids, node_ids) —
    # a composition that carried one but not the other would be a
    # plugin half-wired.
    for operation in (
        "node_directory",
        "write",
        "commit",
        "discard",
        "staged",
        "has_node",
        "campaign_ids",
        "node_ids",
        "files",
        "read",
    ):
        assert callable(getattr(component, operation)), operation


def test_workspace_scan_discovers_the_artifacts_component() -> None:
    # Bare scan_components() follows the declared workspace: the member
    # under packages/artifacts/ is imported and its @register fires.
    names = [component.name for component in scan_components()]
    assert COMPONENT_NAME in names


def test_scan_is_idempotent_per_component_name() -> None:
    # A rescan re-imports the package under its scanned alias; the
    # registry replaces by name, so exactly one component survives
    # however many scans ran.
    scan_components()
    names = [component.name for component in scan_components()]
    assert names.count(COMPONENT_NAME) == 1


def test_the_member_registers_under_the_plugin_name() -> None:
    # The hyphen-free spelling is the plugin name the spec's features
    # carry (plugin="artifacts"), so the component key, the
    # app-namespace seat and the spec cannot drift apart.
    assert COMPONENT_NAME == "artifacts"


def test_create_app_composes_a_store_bound_to_the_configured_root(
    artifact_root: Path,
) -> None:
    app = create_app()
    component = app.get(COMPONENT_NAME)
    _assert_is_the_artifact_store(component)
    assert component.root == artifact_root  # type: ignore[attr-defined]


def test_feature_169_through_the_composed_store(
    artifact_root: Path, campaign_id: str, node_id: str
) -> None:
    # The feature through the path an assembled system takes: compose,
    # persist a node's artifact, read it back under the same two keys.
    component = create_app().get(COMPONENT_NAME)
    _assert_is_the_artifact_store(component)

    component.write(  # type: ignore[attr-defined]
        campaign_id, node_id, "code.py", "def signal(): ..."
    )
    published = component.commit(campaign_id, node_id)  # type: ignore[attr-defined]

    assert published == artifact_root / campaign_id / node_id
    assert component.read(campaign_id, node_id, "code.py") == (  # type: ignore[attr-defined]
        b"def signal(): ..."
    )


def test_builder_rebinds_when_the_environment_moves(
    artifact_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The builder resolves the root at build time, so moving the
    # environment and recomposing points the next application at the
    # new store — the property a deployment relies on when it re-mounts
    # the artifact volume.
    moved = tmp_path / "moved-artifacts"
    moved.mkdir()
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(moved))

    component = create_app().get(COMPONENT_NAME)
    _assert_is_the_artifact_store(component)
    assert component.root == moved  # type: ignore[attr-defined]


def test_the_component_survives_a_second_composition(
    artifact_root: Path,
) -> None:
    # The @register lives in the package __init__, never a submodule:
    # the loader re-executes the __init__ on every composition, so the
    # second application carries the component exactly as the first
    # did.  Asserting on the second is the whole point — the first
    # would pass even if the registration dropped out thereafter.
    first = create_app()
    second = create_app()

    assert COMPONENT_NAME in first.components
    assert COMPONENT_NAME in second.components
    _assert_is_the_artifact_store(second.get(COMPONENT_NAME))


# -- The root the environment names -----------------------------------------------


def test_from_env_prefers_the_environment_root(tmp_path: Path) -> None:
    store = ArtifactStore.from_env(
        env={ARTIFACT_ROOT_ENV: str(tmp_path / "named")}
    )
    assert store.root == tmp_path / "named"


def test_from_env_treats_an_empty_root_as_unset() -> None:
    # An empty or whitespace-only ARTIFACT_ROOT counts as unset — the
    # same treatment the shared fixtures give an empty
    # TEST_DATABASE_URL — so a placeholder in the environment falls to
    # the default root rather than keying a store at "".
    from artifacts._store import DEFAULT_ROOT_NAME

    from app.module_loader import find_workspace_root

    for empty in ("", "   "):
        store = ArtifactStore.from_env(env={ARTIFACT_ROOT_ENV: empty})
        assert store.root == find_workspace_root() / DEFAULT_ROOT_NAME


def test_from_env_defaults_to_beside_the_workspace_root() -> None:
    # With no ARTIFACT_ROOT, the store defaults to ``artifacts/``
    # beside the workspace root — the same discovery the snapshot
    # member's ``lake/`` default uses, so a composed application
    # always carries a store, and the builder never raises for want of
    # configuration inside a workspace.
    from artifacts._store import DEFAULT_ROOT_NAME

    from app.module_loader import find_workspace_root

    store = ArtifactStore.from_env(env={})
    assert store.root == find_workspace_root() / DEFAULT_ROOT_NAME


def test_from_env_refuses_when_no_root_can_be_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Outside a workspace and with no ARTIFACT_ROOT there is no honest
    # place to persist a node's artifact: raising a clear error beats
    # writing into "/" — a directory the tree store's artifact_uri
    # could never find again.
    from artifacts import _store

    monkeypatch.setattr(_store, "find_workspace_root", lambda: None)
    with pytest.raises(ArtifactStoreError, match=ARTIFACT_ROOT_ENV):
        ArtifactStore.from_env(env={})
