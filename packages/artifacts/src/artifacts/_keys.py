"""The layout's key discipline — the two segments that address a node.

app_spec.xml feature 169: *"System persists one artifact directory per
node keyed by campaign_id then node_id."*  docs/nullius-tech-
architecture.md §9.2 draws the layout that sentence keys:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      signal_returns.parquet    # per-symbol, per-period, post-cost
      ic_series.parquet
      ...

This module owns the discipline that makes the key *be* the layout.
A node's directory has no name of its own — no seal time, no hash
prefix, nothing content-derived — because the feature says the
directory is **keyed** by the two identities the rest of the system
already joins on: the campaign the node belongs to, then the node
itself.  The node table (§9.1) carries ``campaign_id`` and ``id``; the
evaluator's final pipeline step hands its artifact writer exactly
``(node_id, campaign_id)``; replay later walks a campaign's nodes by
the same two names (features 174-180).  One spelling of the address,
from the tree store to the disk and back, is what "keyed by" buys.

Two rules follow, and both are enforced here rather than trusted to
callers:

**Each key is exactly one path segment.**  A ``campaign_id`` or
``node_id`` carrying ``/`` would silently reshape the tree — a node
keyed ``a/b`` under campaign ``c`` would land at ``c/a/b``, three
levels deep, and no reader keying ``c/<node_id>`` would find it.  A
``..`` would step outside the store entirely.  Both are refused with
:class:`~artifacts._errors.ArtifactKeyError` before any directory is
created, so a bad key can never leave a half-shaped tree behind.  The
same rule covers the dot-prefixed names — ``.staging`` above all —
that the store reserves for its own plumbing under the root, the same
reservation the snapshot member's ``.sealing-<random>`` working
directories make beside the snapshots they build.  A campaign named
``.staging`` would collide with the staging area itself, and the only
honest answer to it is a refusal at the boundary.

**The order is campaign, then node.**  The two segments are not
interchangeable, and the address is built in exactly one place
(:func:`node_directory`) so it cannot be built two ways.  Campaign
first is what groups a campaign's nodes under one parent — the
grouping feature 174's dense array load and §9.3's resident campaign
arrays sweep — and it is what keeps two campaigns from ever sharing a
node directory even when a ``node_id`` string coincides (§9.1's
``campaign_id`` is part of a node's identity in the tree store; the
artifact store keys the same way, or a node could only ever be
addressed by half its identity).

The keys stay opaque otherwise.  §9.1 types them as UUIDs, but this
module does not enforce it: the evaluator's own tests address nodes as
``"node_1"`` under ``"camp_1"``, the tree store owns identity
validation, and a store that demanded UUIDs would refuse callers the
system actually has.  What this module demands is the narrower thing
the layout itself needs — one segment, safely — and nothing more.
"""

from __future__ import annotations

import os
from pathlib import Path

from ._errors import ArtifactKeyError

__all__ = [
    "CAMPAIGN_ROLE",
    "FILENAME_ROLE",
    "NODE_ROLE",
    "campaign_directory",
    "node_directory",
    "validate_campaign_id",
    "validate_filename",
    "validate_node_id",
    "validate_segment",
]

#: The three roles a segment plays in the layout, carried into refusal
#: messages so an operator reading one knows which term of the address
#: was refused — a bad ``campaign_id`` and a bad ``node_id`` break the
#: lookup at different depths.
CAMPAIGN_ROLE = "campaign_id"
NODE_ROLE = "node_id"
FILENAME_ROLE = "filename"

# Characters that would make a key more or less than one path segment:
# both separators (POSIX's and Windows', so a layout cannot be reshaped
# by moving the store between them) and the NUL the kernel refuses in
# any path component.
_SEPARATORS = ("/", "\\")

#: The prefix reserving the store's own plumbing namespace — the staging
#: area, and the aside-directory a commit moves a replaced version
#: through.  Everything the store itself creates under its root and
#: does not owe to a node's key starts with a dot, so no campaign,
#: node or file key may start with one.  ``.`` and ``..`` are refused
#: explicitly below as well (they are dot-prefixed, but they earn their
#: own words in the refusal).
RESERVED_PREFIX = "."


def validate_segment(value: object, role: str) -> str:
    """Return ``value`` as one safe directory segment, or refuse it.

    The one check the layout of feature 169 needs, applied identically
    to a ``campaign_id``, a ``node_id`` and a ``filename``: the value
    must be a :class:`str` (never a ``Path``, never an int — a coerced
    value would key a directory its caller cannot ask for again by the
    value it actually holds), non-empty and not whitespace-only, free
    of path separators and NUL, neither ``.`` nor ``..``, and not
    dot-prefixed (the store's reserved plumbing namespace).  Refusals
    raise :class:`~artifacts._errors.ArtifactKeyError` naming the role
    and the offending value.

    Everything else a key may legitimately be — a UUID, a name with
    spaces, dots inside (``v1.2``), any Unicode — is accepted: the
    discipline is "exactly one safe segment", not a spelling rule.  The
    tree store owns identity; this module owns only the shape the
    on-disk layout depends on.
    """
    if not isinstance(value, str):
        raise ArtifactKeyError(
            f"a {role} must be a string — one path segment of the §9.2 "
            f"layout — got {type(value).__name__} {value!r}; the key is "
            "the layout (feature 169), and a value that is not a string "
            "cannot be keyed back to the node it addresses"
        )
    if not value.strip():
        raise ArtifactKeyError(
            f"a {role} must name a directory — got {value!r}; an empty "
            "or whitespace-only key would persist a node under a "
            "directory nobody could ask for again"
        )
    if value in (".", ".."):
        raise ArtifactKeyError(
            f"a {role} of {value!r} is a path step, not a name — it "
            "would address the store's own parent rather than a node's "
            "directory, and the layout keys nodes by campaign then "
            "node, never by stepping outside the root"
        )
    for separator in _SEPARATORS:
        if separator in value:
            raise ArtifactKeyError(
                f"a {role} must be exactly one path segment — got "
                f"{value!r}, which carries a {separator!r} separator; "
                "a key of two segments would reshape the layout "
                "('<campaign_id>/<node_id>') and no reader keying the "
                "node could find the directory it names"
            )
    if "\x00" in value:
        raise ArtifactKeyError(
            f"a {role} must be a usable path component — got {value!r}, "
            "which carries a NUL; no filesystem accepts it, so it can "
            "key no directory"
        )
    if value.startswith(RESERVED_PREFIX):
        raise ArtifactKeyError(
            f"a {role} must not start with {RESERVED_PREFIX!r} — got "
            f"{value!r}; dot-prefixed names under the artifact root are "
            "the store's own plumbing (the staging area above all), and "
            "a key squatting on that namespace would collide with it"
        )
    return value


def validate_campaign_id(campaign_id: object) -> str:
    """Validate the first segment of the two-segment key."""
    return validate_segment(campaign_id, CAMPAIGN_ROLE)


def validate_node_id(node_id: object) -> str:
    """Validate the second segment of the two-segment key."""
    return validate_segment(node_id, NODE_ROLE)


def validate_filename(filename: object) -> str:
    """Validate one §9.2 filename — a flat name inside the node directory.

    The §9.2 files (``signal_returns.parquet``, ``decay_profile.json``,
    ``code.py``, …) are flat names directly inside the node's one
    directory, and this member keeps them that way: a filename refusing
    separators and ``..`` is what makes "one directory per node" literal
    — every byte of a node's artifact lives in the one directory its key
    addresses, and nothing can reach past it.
    """
    return validate_segment(filename, FILENAME_ROLE)


def campaign_directory(root: Path, campaign_id: object) -> Path:
    """The campaign's subtree root: ``<root>/<campaign_id>`` — pure.

    Resolves the first segment of the key; creates nothing.  The write
    path creates this directory only as the parent of some node's
    directory, because a campaign exists in the store exactly when one
    of its nodes does — there is no artifact to persist for a campaign
    that holds no nodes.
    """
    validate_campaign_id(campaign_id)
    return Path(root) / str(campaign_id)


def node_directory(root: Path, campaign_id: object, node_id: object) -> Path:
    """The one directory a node's artifact persists at — pure.

    Resolves ``<root>/<campaign_id>/<node_id>`` — campaign first, then
    node, the order the feature keys by — validating both segments
    before any path is built, so a refused key can never leave a
    half-shaped tree behind it.  Creates nothing; the store decides
    when the directory comes to exist (and it comes to exist exactly
    once per node).
    """
    campaign = campaign_directory(root, campaign_id)
    validate_node_id(node_id)
    return campaign / str(node_id)


def is_plumbing(name: str) -> bool:
    """Whether a name under the root belongs to the store's plumbing.

    Everything dot-prefixed under the artifact root is the store's own
    working area, invisible to the campaign and node listings — the
    staging area, and the aside-directories a commit moves a replaced
    version through.  The listing side filters by this rather than by
    the one name ``.staging`` so later plumbing (a trash root, a
    lock file) is born already hidden.
    """
    return name.startswith(RESERVED_PREFIX) or name in {os.curdir, os.pardir}
