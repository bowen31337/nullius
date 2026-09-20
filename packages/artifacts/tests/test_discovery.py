"""The read side — the two key levels, walked back off the disk.

The store persists one directory per node (``test_store``); these
tests pin how the persisted tree answers questions: which campaigns
hold nodes, which nodes a campaign holds, which files a node carries,
and what a missing node or file looks like.  This is the surface §1
grants the replay engine read access to — and nothing else — so its
answers are keyed exactly the way the writes were.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from artifacts import ArtifactNotFoundError, ArtifactStore


def _persist(
    store: ArtifactStore, campaign: str, node: str, *files: str
) -> None:
    """Persist one node carrying ``files``, the §9.2 names as bytes."""
    store.node_directory(campaign, node)
    for name in files:
        store.write(campaign, node, name, f"{campaign}/{node}/{name}".encode())
    store.commit(campaign, node)


def test_a_fresh_store_holds_nothing(store: ArtifactStore) -> None:
    # An empty store is not an error state: the listings answer empty,
    # and a lookup answers false rather than refusing.
    assert store.campaign_ids() == ()
    assert store.node_ids("11111111-1111-4111-8111-111111111111") == ()
    assert not store.has_node("c", "n")


def test_the_two_key_levels_read_back_what_was_persisted(
    store: ArtifactStore,
    campaign_id: str,
    other_campaign_id: str,
) -> None:
    # Campaigns first, nodes second — the same order the writes keyed
    # by, sorted so a caller's traversal is deterministic.
    _persist(store, campaign_id, "node-b", "code.py")
    _persist(store, campaign_id, "node-a", "code.py")
    _persist(store, other_campaign_id, "node-c", "code.py")

    assert store.campaign_ids() == tuple(sorted([campaign_id, other_campaign_id]))
    assert store.node_ids(campaign_id) == ("node-a", "node-b")
    assert store.node_ids(other_campaign_id) == ("node-c",)


def test_a_campaign_with_no_nodes_is_not_a_fact(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A listing is not a lookup: an unknown campaign and a campaign
    # with no persisted nodes are the same fact to a store keyed by
    # nodes, so both answer empty rather than refusing.
    _persist(store, campaign_id, "n1", "code.py")
    assert "missing-campaign" not in store.campaign_ids()
    assert store.node_ids("missing-campaign") == ()


def test_has_node_is_true_for_an_empty_node_directory(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # "Persisted" is a fact about the directory existing, not about the
    # files inside it — an empty node directory is the honest state of
    # a node whose writer has not committed anything yet, and files()
    # (not has_node) is what distinguishes it from a full artifact.
    store.node_directory(campaign_id, node_id)

    assert store.has_node(campaign_id, node_id)
    assert store.files(campaign_id, node_id) == ()


def test_files_lists_the_nodes_files_sorted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    _persist(
        store,
        campaign_id,
        node_id,
        "signal_returns.parquet",
        "ic_series.parquet",
        "turnover_series.parquet",
        "decay_profile.json",
        "regime_attribution.json",
        "exec_trace.json",
        "code.py",
    )

    # §9.2's own set, walked back flat and ordered.
    assert store.files(campaign_id, node_id) == (
        "code.py",
        "decay_profile.json",
        "exec_trace.json",
        "ic_series.parquet",
        "regime_attribution.json",
        "signal_returns.parquet",
        "turnover_series.parquet",
    )


def test_read_returns_what_was_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    _persist(store, campaign_id, node_id, "code.py")
    assert store.read(campaign_id, node_id, "code.py") == (
        f"{campaign_id}/{node_id}/code.py".encode()
    )


def test_reading_an_unpersisted_node_names_the_node(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A missing node is a fact, not a breakage — and the message says
    # which of the two keys came up empty, so a sweep can tell a node
    # that never persisted from a campaign nobody wrote under.
    with pytest.raises(ArtifactNotFoundError, match="no artifact directory"):
        store.files(campaign_id, node_id)
    with pytest.raises(ArtifactNotFoundError, match=node_id):
        store.read(campaign_id, node_id, "code.py")


def test_reading_a_file_the_node_does_not_hold_names_the_file(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The node exists, the directory answers, and the file is missing:
    # a different fact from a missing node, kept apart so a
    # reconciliation sweep can flag the half-written artifact.
    _persist(store, campaign_id, node_id, "code.py")

    with pytest.raises(ArtifactNotFoundError, match="holds no 'exec_trace.json'"):
        store.read(campaign_id, node_id, "exec_trace.json")


def test_a_read_refuses_a_filename_that_could_step_outside(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The read side holds the same boundary the write side does: a
    # traversal dressed as a lookup finds no file to serve.
    _persist(store, campaign_id, node_id, "code.py")

    from artifacts import ArtifactKeyError

    with pytest.raises(ArtifactKeyError):
        store.read(campaign_id, node_id, "../code.py")
    with pytest.raises(ArtifactKeyError):
        store.read(campaign_id, node_id, ".staging")


def test_a_stray_file_under_the_root_is_not_a_campaign(
    store: ArtifactStore, artifact_root: Path, campaign_id: str
) -> None:
    # The campaign level lists directories that key campaigns; a loose
    # file another hand left under the root is not one, and the §9.2
    # plumbing never was.
    _persist(store, campaign_id, "n1", "code.py")
    (artifact_root / "README.txt").write_text("stray")
    (artifact_root / ".junk").mkdir()

    assert store.campaign_ids() == (campaign_id,)


def test_a_stray_directory_inside_a_campaign_is_not_a_node_file(
    store: ArtifactStore, artifact_root: Path, campaign_id: str, node_id: str
) -> None:
    # files() reports the store's own flat artifacts; a hand-made
    # subdirectory inside a node directory is not a file this store
    # persisted, and serving it as one would blur the layout's shape.
    _persist(store, campaign_id, node_id, "code.py")
    (artifact_root / campaign_id / node_id / "handmade").mkdir()

    assert store.files(campaign_id, node_id) == ("code.py",)
