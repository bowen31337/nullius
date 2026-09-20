"""Discovery-tree builders for the tripwires suite — pure functions, no fixtures.

The tripwires suite asserted, until feature 131, that its member touched no
database: ``conftest.py`` says so in as many words, and the absence of a lake
or a database fixture was itself a property under test.  Feature 131 is the
first feature in the category that *must* reach a tree — "the node together
with its entire subtree" is the transitive closure of the discovery tree's own
``parent_id``, and nothing in a verdict carries it — so the member's suite
grows a database after all, and this module is the half of it that builds the
*input*.

**Why the builders live here and not in ``conftest.py``.**  The same reason
:mod:`_panels` gives, and the same sharp edge: a member suite's ``conftest`` is
a top-level module called ``conftest``, and so is every other member's, so two
member suites cannot be collected together if either imports helpers from it.
This file is uniquely named, so no other member can shadow it.

**The builders write the tree the way feature 97's migration declares it.**
Five columns — ``id``, ``parent_id``, ``campaign_id``, ``theme_root``,
``depth`` — with ``parent_id`` ``NULL`` at a root, because that is the shape
``migrations/versions/0118_node_table.py`` creates and the shape the poison
store's recursion reads.  A builder that inserted a *convenient* shape (a flat
table of ids, a ``parent_id`` that pointed across campaigns) would let the
store's tests pass against a tree the system does not have, which is the one
kind of green that is worse than red.

Every id is a real UUID text because that is what the column holds and what the
store's normalization expects.  Nothing here is seeded from a random source a
test has to know about: a caller that needs to name a node passes its own id
in, and a caller that does not gets ids back from the return value.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterable, Mapping

__all__ = [
    "Tree",
    "seed_campaign",
    "seed_tree",
]

#: The ``node`` table's structural columns, in 0118's order.  Spelled once so
#: every insert below names the same five and a column added by a later feature
#: is a visible edit here rather than a silent ``INSERT`` of the wrong arity.
_NODE_COLUMNS = "id, parent_id, campaign_id, theme_root, depth"


class Tree:
    """A seeded discovery tree, and the ids a test needs to talk about it.

    A value, not a fixture-heavy object: it carries the campaign, the root, the
    interior node, the leaf and an unrelated sibling root, which are the five
    things every feature-131 test names, plus the connection it was built on so
    a test can assert on the raw rows the store wrote.  Held as plain
    attributes rather than properties because there is nothing to validate —
    the ids came from :func:`uuid.uuid4` and the table's own primary key.
    """

    __slots__ = (
        "campaign_id",
        "child_id",
        "connection",
        "depth",
        "leaf_id",
        "root_id",
        "sibling_root_id",
    )

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        campaign_id: str,
        root_id: str,
        child_id: str,
        leaf_id: str,
        sibling_root_id: str,
        depth: int,
    ) -> None:
        self.connection = connection
        self.campaign_id = campaign_id
        self.root_id = root_id
        self.child_id = child_id
        self.leaf_id = leaf_id
        self.sibling_root_id = sibling_root_id
        self.depth = depth

    @property
    def subtree_ids(self) -> tuple[str, ...]:
        """The root's whole subtree, root first then down the chain.

        The shape feature 131's sentence describes, in the order the store's
        walk returns it (depth, then id) for a *chain* — which is what this
        tree is, so the expected order is written down here rather than
        recomputed by a second walk in the test.
        """
        return (self.root_id, self.child_id, self.leaf_id)


def seed_campaign(
    connection: sqlite3.Connection,
    *,
    theme_root: str = "test-theme",
    depth: int = 3,
) -> Tree:
    """Seed one campaign's tree: a root, a child, a grandchild, a sibling root.

    The chain ``root → child → leaf`` is the smallest tree that can tell
    "poison the node" apart from "poison the node and its subtree": a two-node
    tree would make the feature's central claim true by accident of arithmetic
    (the subtree of a root with one child has size two, and so does a walk that
    simply returns the node twice), so the third node is the one that makes the
    assertion mean what the spec says.

    ``sibling_root_id`` is a *second* root in the **same** campaign, with no
    parent and no children.  It is the control the subtree tests need: a walk
    that ignored ``parent_id`` and marked the whole campaign would poison it,
    and a walk that leaked across campaigns would too — one node catches both,
    and it is in the same campaign so the two failures are not confused with a
    correct scope.

    ``depth`` is the tree's depth, defaulting to three (root, child, leaf);
    a caller may ask for a longer chain to make a subtree large enough for a
    size assertion to be interesting.  The extra nodes are appended beneath the
    leaf, so ``root → child → leaf`` keeps its meaning at any depth.
    """
    campaign_id = str(uuid.uuid4())
    root_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    leaf_id = str(uuid.uuid4())
    sibling_root_id = str(uuid.uuid4())

    chain = [root_id, child_id, leaf_id]
    # The first three ids are fixed names a test talks about; a deeper tree
    # extends the chain beneath the leaf, so the named three keep their places.
    while len(chain) < max(depth, 3):
        chain.append(str(uuid.uuid4()))

    rows = [
        (
            node_id,
            None if index == 0 else chain[index - 1],
            campaign_id,
            theme_root,
            index,
        )
        for index, node_id in enumerate(chain)
    ]
    rows.append((sibling_root_id, None, campaign_id, theme_root, 0))
    connection.executemany(
        f"INSERT INTO node ({_NODE_COLUMNS}) VALUES (?, ?, ?, ?, ?)", rows
    )
    connection.commit()
    return Tree(
        connection=connection,
        campaign_id=campaign_id,
        root_id=root_id,
        child_id=child_id,
        leaf_id=leaf_id,
        sibling_root_id=sibling_root_id,
        depth=len(chain),
    )


def seed_tree(
    connection: sqlite3.Connection,
    children: Mapping[str, Iterable[str]],
    *,
    campaign_id: str | None = None,
    theme_root: str = "test-theme",
) -> str:
    """Seed an arbitrary graph from a ``{parent: [children]}`` mapping.

    For the shapes :func:`seed_campaign` cannot make: a *branching* tree (one
    parent, several children), a forest (several roots), and — the one that
    matters — a **cycle**, built by inserting the rows with foreign keys
    disabled so ``parent_id`` can be made to point back up the chain.  The
    store must refuse a walk over that rather than loop forever, and a test
    cannot build the input through the constraint the store itself enables.

    **Caller-named ids, and the graph read literally.**  Every id is the
    caller's, because the shapes above need a test to talk about specific
    nodes.  The mapping is read as *the graph*, not as a set of insert
    instructions: a node named as a key exists (a key no child list mentions is
    a root), a node named only as a child exists with the parent it appeared
    under, and a node named both ways exists once with the parent its *child*
    mention gave it.

    That last rule is what lets a cycle be written down.  ``{root: [a], a: [b],
    b: [a]}`` says "``a`` is a node, ``a`` is ``b``'s child, and ``a``'s own
    child is ``b``" — and ``root`` gives the walk its entry point, which a
    pure cycle cannot have because the store's walk begins at the node the
    *verdict* named.  A graph with no ``NULL`` parent anywhere is refused, and
    with the message above rather than a silent insertion of rows nothing can
    reach.

    ``depth`` is written plausibly rather than computed exactly — see
    :func:`_depth_of`.  Both the graph and the column are the store's problem
    to interpret; this function's job is to put rows in the table that
    ``0118`` would accept.

    Returns the campaign the nodes were written under, which is the one thing
    a caller cannot derive from ids it supplied.
    """
    campaign = campaign_id or str(uuid.uuid4())
    parents: dict[str, str | None] = {}
    order: list[str] = []

    def _seen(node: str) -> None:
        if node not in order:
            order.append(node)

    # Two passes, because a node can be named twice and the two mentions mean
    # different things.  A *key* names a node into existence and says it has
    # children; a *child* says which node its ``parent_id`` points at.  So the
    # keys are collected first (a key that no child list mentions is a root),
    # and the child lists then overwrite those parents — which is what makes a
    # cycle expressible at all: ``{a: [b], b: [c], c: [a]}`` needs ``a`` to be
    # both "a node this graph has" and "the child of ``c``", and a column
    # holding one value can only record the second.
    for parent in children:
        if parent is not None:
            parents.setdefault(parent, None)
            _seen(parent)
    for parent, kids in children.items():
        for kid in kids:
            if kid not in parents:
                parents[kid] = None
                _seen(kid)
            if parent is not None:
                parents[kid] = parent

    roots = [node for node in order if parents[node] is None]
    if not roots:
        raise ValueError(
            "a seeded graph needs at least one node whose `parent_id` is NULL; "
            "this mapping gives every node a parent, so no walk could enter it "
            "and the rows would be unreachable rather than merely cyclic. Add "
            "the entry point — a key of `None` listing the root — beside the "
            "edge that closes the loop"
        )

    rows = [
        (node, parents[node], campaign, theme_root, _depth_of(node, parents))
        for node in order
    ]

    # A foreign key cannot be satisfied by a cycle in any insertion order, so
    # the rows go in with the constraint off and the store's own walk is what
    # has to notice.  That is the honest way to build the input: production
    # cannot create a cycle through the constraint either, but the walk must
    # not depend on that being true forever.  Nor can a *diamond* be built
    # through the constraint and still be one — so a shape that needs one gets
    # it the same way, for the same reason.
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executemany(
        f"INSERT INTO node ({_NODE_COLUMNS}) VALUES (?, ?, ?, ?, ?)", rows
    )
    connection.execute("PRAGMA foreign_keys = ON")
    connection.commit()
    return campaign


def _depth_of(node: str, parents: Mapping[str, str | None]) -> int:
    """How far ``node`` sits beneath its root, following ``parent_id`` upward.

    Walks with a visited set, so a cycle returns a finite depth instead of
    spinning: the column is ``INT NOT NULL`` and this function's job is to fill
    it plausibly, not to be the cycle check — that is the store's, and the test
    that seeds a cycle exists to watch the store refuse it.
    """
    depth = 0
    seen = {node}
    current = parents.get(node)
    while current is not None and current not in seen:
        seen.add(current)
        depth += 1
        current = parents.get(current)
    return depth
