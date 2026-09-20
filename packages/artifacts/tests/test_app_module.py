"""The member's seat inside the ``app`` package namespace.

``src/app/modules/artifacts/__init__.py`` is where the composed
artifact store is reachable from the ``app`` package without the app
package importing the member at module scope.  The member's suite owns
that file (it lives at ``src/app/modules/artifacts/``, which the
task's file claim covers), so the seat is tested here rather than in a
repository-level suite.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not
an exception — when there is none.  That degradation is pinned below,
since a module that failed import because a member was absent would
take the app package down with it.

The seat is also where the *category's* other features will reach the
store — the Parquet and JSON artifacts of 170-173, the campaign loads
of 174-180, the replay path's read-only access — so the one thing this
file guards hardest is that the accessor stays a thin composition
read: it does not grow a second spelling of ``write``/``commit``/
``read``.
"""

from __future__ import annotations

from pathlib import Path

from artifacts import COMPONENT_NAME

from app.module_loader import Application


def test_the_component_name_matches_the_member() -> None:
    # Spelled twice on purpose — once in the member, once in the seat —
    # so the two cannot drift apart silently.
    import artifacts

    assert COMPONENT_NAME == artifacts.COMPONENT_NAME == "artifacts"


def test_the_seat_exposes_the_composed_store(artifact_root: Path) -> None:
    from app.modules.artifacts import artifact_store_component

    component = artifact_store_component()
    assert type(component).__name__ == "ArtifactStore"
    assert component.root == artifact_root  # type: ignore[attr-defined]


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.artifacts import artifact_store_component

    application = Application(
        components={COMPONENT_NAME: "sentinel"}, order=(COMPONENT_NAME,)
    )
    assert artifact_store_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.artifacts import artifact_store_component

    empty = Application(components={}, order=())
    assert artifact_store_component(empty) is None


def test_feature_169_through_the_app_namespace(
    artifact_root: Path, campaign_id: str, node_id: str
) -> None:
    # The feature from the app namespace: composed store, staged write,
    # committed directory keyed campaign then node, bytes back.
    from app.modules.artifacts import artifact_store_component

    store = artifact_store_component()
    store.write(campaign_id, node_id, "signal_returns.parquet", b"composed")
    published = store.commit(campaign_id, node_id)

    assert published == artifact_root / campaign_id / node_id
    assert store.read(campaign_id, node_id, "signal_returns.parquet") == (
        b"composed"
    )


def test_the_seat_is_a_composition_read_and_not_a_second_api() -> None:
    # The seat is deliberately accessors only: a caller who has the
    # store reaches write/commit/read on it, and a second spelling here
    # would be a second thing to keep in sync.
    from app.modules import artifacts as seat

    exported = set(seat.__all__)
    assert exported == {"COMPONENT_NAME", "artifact_store_component"}
