"""The persistence — one artifact directory per node, published as one unit.

app_spec.xml feature 169: *"System persists one artifact directory per
node keyed by campaign_id then node_id."*  These tests hold the store
to that sentence literally: a node's directory exists, exactly one per
node, at the address its two keys derive; writes to it are staged and
published as one directory by a commit; a failure before the commit
publishes nothing.  The read side's listings live in ``test_discovery``;
the composition seam lives in ``test_component``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from artifacts import (
    ArtifactKeyError,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
)

# -- One directory per node -------------------------------------------------------


def test_a_nodes_directory_is_persisted_under_its_campaign(
    store: ArtifactStore,
    artifact_root: Path,
    campaign_id: str,
    node_id: str,
) -> None:
    # The feature's sentence as an operation: asking for the node's
    # directory persists it, keyed campaign first then node — the §9.2
    # layout, at the root the environment names.
    directory = store.node_directory(campaign_id, node_id)

    assert directory == artifact_root / campaign_id / node_id
    assert directory.is_dir()


def test_asking_again_returns_the_same_directory(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
) -> None:
    # The address is a pure function of the two keys, so the persist is
    # idempotent: no error, no second directory, exactly one entry for
    # the node under its campaign.
    first = store.node_directory(campaign_id, node_id)
    second = store.node_directory(campaign_id, node_id)

    assert first == second
    assert [entry.name for entry in first.parent.iterdir()] == [node_id]


def test_two_nodes_of_one_campaign_share_the_campaign_parent(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    other_node_id: str,
) -> None:
    # Campaign first is what groups a campaign's nodes under one
    # parent — the grouping the campaign-level loads of features 174
    # and §9.3 sweep.
    one = store.node_directory(campaign_id, node_id)
    two = store.node_directory(campaign_id, other_node_id)

    assert one.parent == two.parent
    assert sorted(entry.name for entry in one.parent.iterdir()) == sorted(
        [node_id, other_node_id]
    )


def test_two_campaigns_key_the_same_node_id_apart(
    store: ArtifactStore,
    campaign_id: str,
    other_campaign_id: str,
    node_id: str,
) -> None:
    # §9.1 makes campaign_id part of a node's identity in the tree
    # store; the artifact store keys the same way, so one node_id
    # under two campaigns is two nodes with two directories — never a
    # collision, never a shared artifact.
    here = store.node_directory(campaign_id, node_id)
    there = store.node_directory(other_campaign_id, node_id)

    assert here != there
    assert here.is_dir()
    assert there.is_dir()


def test_a_campaign_parent_exists_only_when_one_of_its_nodes_does(
    store: ArtifactStore, artifact_root: Path, campaign_id: str
) -> None:
    # There is no artifact to persist for a campaign that holds no
    # nodes, so no directory is created for one: the campaign level of
    # the layout comes into being as the parent of a node directory.
    assert not store.campaign_root(campaign_id).exists()
    store.node_directory(campaign_id, "n1")
    assert store.campaign_root(campaign_id).is_dir()


def test_a_bad_key_refuses_before_anything_is_created(
    store: ArtifactStore, artifact_root: Path, campaign_id: str
) -> None:
    # The key is the layout; a key that would reshape it is refused at
    # the boundary, and the refusal leaves the store exactly as it was.
    with pytest.raises(ArtifactKeyError):
        store.node_directory(campaign_id, "../escape")
    with pytest.raises(ArtifactKeyError):
        store.node_directory(".staging", "n1")

    assert list(artifact_root.iterdir()) == []  # not even the campaign


# -- Staged writes, one commit ----------------------------------------------------


def test_writes_are_staged_out_of_sight_until_committed(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    artifact_root: Path,
) -> None:
    # The staged half of the publication path: bytes land under the
    # hidden plumbing, invisible to every read, so a reader never
    # observes a half-written node directory under its key.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")
    store.write(campaign_id, node_id, "exec_trace.json", b"{}")

    assert store.staged(campaign_id, node_id) == (
        "exec_trace.json",
        "signal_returns.parquet",
    )
    assert not store.has_node(campaign_id, node_id)
    with pytest.raises(ArtifactNotFoundError):
        store.files(campaign_id, node_id)
    assert not (artifact_root / campaign_id / node_id).exists()


def test_commit_publishes_the_staged_set_as_one_directory(
    store: ArtifactStore,
    artifact_root: Path,
    campaign_id: str,
    node_id: str,
) -> None:
    # The commit point: the staged set becomes the node's one
    # directory, keyed where the tree store's row will point, and every
    # file lands in it at once.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")
    store.write(campaign_id, node_id, "code.py", "def signal():\n    ...\n")

    published = store.commit(campaign_id, node_id)

    assert published == artifact_root / campaign_id / node_id
    assert store.has_node(campaign_id, node_id)
    assert store.files(campaign_id, node_id) == (
        "code.py",
        "signal_returns.parquet",
    )
    assert store.read(campaign_id, node_id, "signal_returns.parquet") == (
        b"returns"
    )
    assert store.read(campaign_id, node_id, "code.py") == (
        b"def signal():\n    ...\n"
    )
    assert store.staged(campaign_id, node_id) == ()  # consumed by the commit


def test_commit_replaces_the_prior_version_wholesale(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A refresh is not a merge: the newly staged set is the whole
    # directory, so a file the retry did not stage is gone and a file
    # it re-staged carries the new bytes.  One unit, one version.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"v1")
    store.write(campaign_id, node_id, "stale.json", b"stale")
    store.commit(campaign_id, node_id)

    store.write(campaign_id, node_id, "signal_returns.parquet", b"v2")
    store.write(campaign_id, node_id, "fresh.json", b"fresh")
    store.commit(campaign_id, node_id)

    assert store.files(campaign_id, node_id) == (
        "fresh.json",
        "signal_returns.parquet",
    )
    assert store.read(campaign_id, node_id, "signal_returns.parquet") == b"v2"


def test_a_refresh_never_leaves_two_directories_for_the_node(
    store: ArtifactStore,
    artifact_root: Path,
    campaign_id: str,
    node_id: str,
) -> None:
    # The invariant that holds across a refresh: one directory per
    # node, never two.  The replaced version steps aside *inside* the
    # plumbing, never beside the node under the campaign.
    for version in (b"v1", b"v2", b"v3"):
        store.write(campaign_id, node_id, "signal_returns.parquet", version)
        store.commit(campaign_id, node_id)

    campaign = artifact_root / campaign_id
    assert [entry.name for entry in campaign.iterdir()] == [node_id]
    assert store.read(campaign_id, node_id, "signal_returns.parquet") == b"v3"


def test_commit_without_staged_writes_refuses_and_changes_nothing(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # An empty commit would replace a node's artifact with nothing —
    # a silent deletion wearing a success's clothes.  It refuses, and
    # the refusal does not disturb what is already published.
    with pytest.raises(ArtifactStoreError, match="nothing is staged"):
        store.commit(campaign_id, node_id)

    store.write(campaign_id, node_id, "code.py", b"# v1")
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactStoreError, match="nothing is staged"):
        store.commit(campaign_id, node_id)
    assert store.files(campaign_id, node_id) == ("code.py",)
    assert store.read(campaign_id, node_id, "code.py") == b"# v1"


def test_discard_rolls_the_staged_writes_back(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The rollback half of the staged path: an interrupted pipeline
    # leaves nothing behind — no node directory, no staged residue.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"partial")
    store.discard(campaign_id, node_id)

    assert store.staged(campaign_id, node_id) == ()
    assert not store.has_node(campaign_id, node_id)


def test_discard_is_idempotent_and_keeps_the_published_directory(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A rollback a caller cannot repeat safely is a rollback a retrying
    # pipeline will skip; and the published artifact is not the failed
    # retry's to delete.
    store.write(campaign_id, node_id, "code.py", b"# published")
    store.commit(campaign_id, node_id)

    store.write(campaign_id, node_id, "code.py", b"# failed retry")
    store.discard(campaign_id, node_id)
    store.discard(campaign_id, node_id)  # idempotent

    assert store.read(campaign_id, node_id, "code.py") == b"# published"


def test_staging_the_same_filename_twice_keeps_the_last_bytes(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The staged set is a mapping, one entry per filename — exactly
    # like the directory it will become.
    store.write(campaign_id, node_id, "code.py", b"first")
    store.write(campaign_id, node_id, "code.py", b"second")

    store.commit(campaign_id, node_id)
    assert store.read(campaign_id, node_id, "code.py") == b"second"


def test_write_encodes_text_as_utf8(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # §9.2's JSON and code files arrive as text; the store renders text
    # to the one byte encoding JSON is specified over.
    store.write(campaign_id, node_id, "exec_trace.json", '{"h": "ü"}')
    store.commit(campaign_id, node_id)
    assert store.read(campaign_id, node_id, "exec_trace.json") == (
        '{"h": "ü"}'.encode()
    )


def test_write_refuses_a_payload_that_is_not_bytes_or_text(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A file holds bytes; a value that is neither bytes-like nor text
    # is a payload the encoding features (170-173) render, not the
    # directory store's to guess at.
    with pytest.raises(ArtifactStoreError, match="holds bytes"):
        store.write(campaign_id, node_id, "signal_returns.parquet", 3.5)
    assert store.staged(campaign_id, node_id) == ()


def test_a_filename_cannot_escape_the_nodes_directory(
    store: ArtifactStore, artifact_root: Path, campaign_id: str, node_id: str
) -> None:
    # "One directory per node" holds from the inside too: every file of
    # the artifact lives in the one directory its key addresses, and a
    # filename that would step outside refuses before touching disk.
    for escape in ("../escape", "sub/inner", "..", ".staging"):
        with pytest.raises(ArtifactKeyError):
            store.write(campaign_id, node_id, escape, b"bytes")

    assert store.staged(campaign_id, node_id) == ()
    assert list(artifact_root.iterdir()) == []


def test_the_staging_area_is_never_a_campaign(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The plumbing lives beside the campaigns, hidden: a staging write
    # (and the aside of a refresh) never shows up as a campaign, so the
    # two key levels read back exactly what was persisted for nodes.
    store.write(campaign_id, node_id, "code.py", b"staged")
    store.write(campaign_id, node_id, "code.py", b"refresh")

    assert store.staging_root.is_dir()  # present on disk while staged…
    assert store.campaign_ids() == ()  # …and listed nowhere

    store.commit(campaign_id, node_id)

    assert store.campaign_ids() == (campaign_id,)
    # The commit consumed the staging directory, and the prune left no
    # empty plumbing behind: the root holds campaigns, and nothing else.
    assert [
        entry.name for entry in store.root.iterdir()
    ] == [campaign_id]


def test_an_address_occupied_by_a_file_refuses_rather_than_removes(
    store: ArtifactStore, artifact_root: Path, campaign_id: str, node_id: str
) -> None:
    # The store will not delete a foreign object to make room for a
    # node's directory — that is a human's call, not a commit's.
    occupied = artifact_root / campaign_id / node_id
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(b"not a directory")

    store.write(campaign_id, node_id, "code.py", b"code")
    with pytest.raises(ArtifactStoreError, match="not a directory"):
        store.commit(campaign_id, node_id)

    assert occupied.read_bytes() == b"not a directory"


def test_the_root_must_be_a_real_path() -> None:
    # Path("") would silently become "." — persisting into whatever
    # directory the process happened to start in is never what a
    # caller meant.
    with pytest.raises(ArtifactStoreError):
        ArtifactStore("  ")
    with pytest.raises(ArtifactStoreError):
        ArtifactStore("")
