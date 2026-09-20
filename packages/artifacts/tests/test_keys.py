"""The key discipline — the two segments that address a node.

app_spec.xml feature 169 keys a node's artifact directory by
``campaign_id`` then ``node_id``, and docs/nullius-tech-architecture.md
§9.2 draws the layout that key produces.  These tests pin the narrower
thing the layout itself needs — each key is exactly one safe path
segment — and the pure resolution that turns a validated key pair into
the one address a node's artifact always lives at.  Nothing here
touches the filesystem: the store's persistence tests live in
``test_store``; these are the rules the store leans on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from artifacts import (
    ArtifactKeyError,
    campaign_directory,
    node_directory,
    validate_campaign_id,
    validate_filename,
    validate_node_id,
    validate_segment,
)

#: A root for the pure resolvers — nothing is ever created there.
ROOT = Path("/artifacts")


# -- What a key may be -----------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "11111111-2222-4333-8444-555555555555",  # §9.1's own spelling
        "camp_1",  # the evaluator's tests address campaigns this way
        "node-1",
        "a key with spaces",
        "v1.2",  # a dot inside is a version, not the reserved prefix
        "ünïcode-campaign",
    ],
)
def test_every_shape_the_tree_store_may_key_by_is_accepted(key: str) -> None:
    # The discipline is "exactly one safe segment", not a spelling rule:
    # §9.1 types the ids as UUIDs, but the store keys by whatever string
    # the system joins on, and refusing a legitimate key would break the
    # one-address promise for nodes the tree store already holds.
    assert validate_segment(key, "campaign_id") == key


def test_the_three_roles_have_their_own_validators() -> None:
    # campaign_id, node_id, filename — one check, three spellings, each
    # naming its role so a refusal says which term of the address broke.
    assert validate_campaign_id("camp") == "camp"
    assert validate_node_id("node") == "node"
    assert validate_filename("signal_returns.parquet") == (
        "signal_returns.parquet"
    )


@pytest.mark.parametrize(
    "key",
    [
        "",
        "   ",
        "\t\n",
        ".",
        "..",
        "a/b",
        "/absolute",
        "a\\b",
        "a\x00b",
        ".staging",
        ".hidden",
    ],
)
def test_a_key_that_is_not_one_safe_segment_is_refused(key: str) -> None:
    # Each of these would reshape the layout rather than address into
    # it: empty names a directory nobody could ask for again, "." and
    # ".." step outside the store, separators make one key span two
    # segments, NUL is refused by the kernel, and the dot prefix is the
    # store's own plumbing namespace (".staging" above all).
    with pytest.raises(ArtifactKeyError):
        validate_segment(key, "node_id")


@pytest.mark.parametrize(
    "key",
    [123, None, b"bytes", True, 3.5, Path("camp"), ["camp"]],
)
def test_a_key_that_is_not_a_string_is_refused(key: object) -> None:
    # Refused rather than stringified: a coerced Path or int would key
    # a directory its caller cannot ask for again by the value it
    # actually holds.
    with pytest.raises(ArtifactKeyError):
        validate_segment(key, "campaign_id")


def test_the_refusal_names_the_role_and_the_value() -> None:
    # An operator reading the message needs both halves: which term of
    # the address was refused, and what it was.
    with pytest.raises(ArtifactKeyError, match="node_id"):
        validate_node_id("a/b")
    with pytest.raises(ArtifactKeyError, match="campaign_id"):
        validate_campaign_id("")
    with pytest.raises(ArtifactKeyError, match=r"'a/b'"):
        validate_segment("a/b", "node_id")


# -- The pure resolution ---------------------------------------------------------


def test_a_campaign_resolves_to_the_first_segment() -> None:
    assert campaign_directory(ROOT, "camp") == ROOT / "camp"


def test_a_node_resolves_campaign_then_node() -> None:
    # The feature's own order: keyed by campaign_id THEN node_id.  The
    # campaign is the parent, the node the child, and no second
    # spelling of the address exists to build it the other way.
    assert node_directory(ROOT, "camp", "node") == ROOT / "camp" / "node"


def test_the_resolution_validates_before_it_builds() -> None:
    # A refused key can never leave a half-shaped tree behind it: the
    # segments are checked before any path is assembled.
    with pytest.raises(ArtifactKeyError):
        node_directory(ROOT, "camp", "../escape")
    with pytest.raises(ArtifactKeyError):
        node_directory(ROOT, "a/b", "node")
    with pytest.raises(ArtifactKeyError):
        campaign_directory(ROOT, ".staging")


def test_a_filename_is_validated_like_a_segment_because_it_is_one() -> None:
    # The §9.2 files are flat names directly inside the node's one
    # directory; a filename that could step outside it would break "one
    # directory per node" from the inside.
    assert validate_filename("decay_profile.json") == "decay_profile.json"
    with pytest.raises(ArtifactKeyError):
        validate_filename("../signal_returns.parquet")
    with pytest.raises(ArtifactKeyError):
        validate_filename("sub/dir.parquet")
    with pytest.raises(ArtifactKeyError):
        validate_filename(".staging")
