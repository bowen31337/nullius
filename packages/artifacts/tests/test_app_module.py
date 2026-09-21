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

import os
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


# -- Feature 179's seat, beside this one -------------------------------------------


def test_the_dedup_seat_spells_the_component_name_the_member_registers() -> None:
    # Spelled twice on purpose — once in the member, once in the seat —
    # so the two cannot drift apart silently.  The second seat sitting
    # in its own module is what keeps this from being a rename hazard
    # for feature 169's seat: the store's accessor never moves.
    import artifacts

    from app.modules.artifacts import dedup

    assert dedup.COMPONENT_NAME == artifacts.DEDUP_COMPONENT_NAME
    assert dedup.COMPONENT_NAME == "artifacts-code-hash-dedup"
    assert dedup.COMPONENT_NAME != COMPONENT_NAME


def test_the_dedup_seat_exposes_the_composed_gate() -> None:
    # The composed gate, through the app namespace: a CodeHashIndex bound
    # to the database the environment names under this suite's autouse
    # isolation.  The seat lives in its own module — ``from
    # app.modules.artifacts.dedup import ...``, not out of the package's
    # ``__init__`` — because a second accessor crowded into feature 169's
    # seat would be a second thing to keep in sync with it.
    from app.modules.artifacts import dedup

    component = dedup.code_hash_dedup_component()
    assert type(component).__name__ == "CodeHashIndex"
    assert component.database_url == os.environ["DATABASE_URL"]  # type: ignore[attr-defined]


def test_the_dedup_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.artifacts import dedup

    application = Application(
        components={dedup.COMPONENT_NAME: "sentinel"}, order=(dedup.COMPONENT_NAME,)
    )
    assert dedup.code_hash_dedup_component(application) == "sentinel"


def test_an_absent_gate_is_none_rather_than_an_error() -> None:
    # The seat's ``None`` covers two states at once — an absent member and
    # a deployment with no DATABASE_URL — and both are statements about
    # the deployment, not verdicts about the tree.  That distinction is
    # the feature, so the degradation is pinned rather than assumed.
    from app.modules.artifacts import dedup

    empty = Application(components={}, order=())
    assert dedup.code_hash_dedup_component(empty) is None


def test_the_dedup_seat_is_a_composition_read_and_not_a_second_api() -> None:
    # Same rule as feature 169's seat: the comparison and the probe stay
    # on the gate, where the caller who has it reaches them.  A caller
    # holding only a list of stored hashes reaches
    # ``artifacts.reject_duplicate`` directly — the half of the feature
    # that needs no store — and neither is re-exported here.
    from app.modules.artifacts import dedup

    assert set(dedup.__all__) == {"COMPONENT_NAME", "code_hash_dedup_component"}
    for second_spelling in (
        "check",
        "probe",
        "stored",
        "canonical_code_hash",
        "reject_duplicate",
        "CodeHashIndex",
    ):
        assert not hasattr(dedup, second_spelling), second_spelling
