"""The Type-D flip depth: a geometric draw, persisted per branch — feature 119.

app_spec.xml, "Null Oracle & Planted Nulls", feature 119: *System persists a
Type-D flip depth drawn from a geometric distribution while every root stays
real.*  This module is that draw and the store that writes it down.  It is the
second of the two null-assignment regimes §7.3 fixes: feature 118's Type-R
draws *which roots are null* (a fraction of roots chosen without replacement,
their null status inherited by the whole subtree), and this feature draws
*how deep a Type-D branch runs before it flips null* — a depth ``d`` past which
every descendant of the branch reports a permuted target instead of a real one.

**What the flip depth is, and the one invariant the sentence carries.**  A
Type-D campaign keeps every root real and flips a branch null at a randomised
depth ``d``; docs/nullius-tech-architecture.md §7.3 spells the draw as
``d ~ Geometric(p)`` with ``p`` decreasing in the parent's true information
ratio, and docs/alpha-engine-prd.md §4.1.2 states why the depth must be
randomised and varied across campaigns rather than held constant — *"a constant
``d`` teaches the policy 'always stop at depth 4,' which is worth nothing."*
The load-bearing word in feature 119's sentence is **persists**: the depth a
branch flips at is a fact about that branch, fixed once, and the same campaign
replayed next year must flip the same branch at the same depth.  §12's
determinism contract forbids a world whose flip depth was re-drawn on every
request, exactly as it forbids a null node whose permutation seed was re-drawn;
feature 115 makes the same argument for the seed this module's sibling stores
beside the null bit.  So the depth is drawn once, sealed, and read back — never
re-derived.

**The geometric distribution, and why it is *this* one.**  The draw is a
geometric on the number of Bernoulli trials to the first success, the
``1 + floor(log(U) / log(1 - p))`` inversion of a single uniform ``U`` — the
standard library's own construction, reproduced here rather than borrowed from
``random.Random.geometric`` (which no supported Python carries as a stable,
seedable, dialect-independent primitive, and whose sampling convention this
member must pin rather than inherit).  Its support is ``{1, 2, 3, …}``: the
shallowest a branch can flip is at depth 1, never at depth 0.  That is not a
detail to be validated away — it is the whole of *"every root stays real."*  A
root sits at depth 0; a flip depth of 0 would turn a root null and make the
campaign a Type-R campaign by another name, which §7.3 forbids outright
(campaigns are homogeneous in null type, and a Type-D campaign is *all roots
real*).  The geometric's support guarantees the invariant structurally: the
draw cannot return 0, so a root can never be the flip.  The store nevertheless
refuses a persisted depth that is not a genuine positive integer, for the same
reason feature 118's sibling refuses a null bit that is not a genuine bool —
the value that decides whether a node reports a real target or a permuted one
is the single most consequential number on the branch, and a ``0`` or a
truthy-looking ``True`` that slipped through would silently retype the world.

**The probability ``p``, and why it is an argument and not a constant.**  The
draw takes ``p`` from its caller rather than computing it from a true
information ratio, and the split is deliberate.  *What the depth is drawn from*
— ``p`` decreasing in the parent's true IR, varied across campaigns — is
feature 120's, and feature 120 is the module that knows how to read a branch's
true information ratio and turn it into a probability.  *How a geometric is
drawn and persisted* is this feature's, and it is the same seam feature 117's
fraction observes: this module is the draw and the store, and it takes the
probability as a validated argument so the caller that owns the probability's
meaning supplies it.  The module validates what it owns of the transaction —
that ``p`` is a probability in the open interval ``(0, 1)`` — and names what it
refuses.  A ``p`` of exactly 1 collapses the geometric to a constant depth of 1
(a degenerate draw no campaign was designed with, and the very "always stop at
depth 1" the PRD warns against); a ``p`` of 0 makes the mean ``1/p`` infinite
and the draw never terminates; a ``p`` outside ``[0, 1]`` is not a probability.
The interval is open on both ends for both reasons, and the refusal is the
point.

**The depth is a fact about a branch, so the branch is never created here.**
The grain is the branch — identified by the id of the branch's parent node, the
node whose subtree flips at this depth — and the depth is written onto that
node's row, not onto a row this store invents.  A store that inserted the
missing node would be inventing the branch the depth belongs to, and a depth
written onto a node this store invented would be a depth nobody drew.  A node
the table does not hold raises :class:`~nulloracle.errors.KsGuardError` by
name — the same error feature 117's fraction and feature 124's verdict raise
for the same reason, because all three join the ``node`` row and a malformed id
or an unknown node is the same kind of store-contract failure for each.  The
check is a read, not a create.

**The depth is written beside the columns the tree already carries.**  Feature
97's ``node`` table carries the branch's structural skeleton — ``id``,
``parent_id``, ``campaign_id``, ``theme_root``, ``depth`` — and this module
writes the flip depth into that same ``node`` table, as one more column on the
branch's parent row.  It does not create a table of its own: the flip depth is
a fact about a node, and a node is a row in ``node``.  The store opens the
``node`` table idempotently (``CREATE TABLE IF NOT EXISTS`` on first use, the
contract every store in this workspace states) but refuses to create the row:
the node is created by the discovery loop, before any flip is drawn.

**Stdlib only, and import-cheap.**  ``math``, ``sqlite3`` and ``urllib.parse``;
no third-party import at module scope, so the factory's scan — which imports
this package to fire its ``@register`` — pays nothing for this module, the same
discipline feature 117's and feature 123's stores state and for the same
reason: the member already defers ``cryptography`` to first use, and a store
that pulled a driver in at import would undo that.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .assignment import normalize_node_id
from .errors import KsGuardError

__all__ = [
    "CAMPAIGN_TABLE",
    "DATABASE_URL_ENV",
    "FLIP_DEPTH_COLUMN",
    "P_MAX",
    "P_MIN",
    "FlipDepth",
    "flip_depth",
    "node_as_seed",
    "persist_flip_depth",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the guard's, the
#: verdict's, the fraction's, the evaluator's five, the repository-level
#: conftest's), restated here so each store states its own contract and none
#: imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the flip depth is written to — feature 97's ``node``, the table
#: that carries every node of the discovery tree.  Spelled once here so the
#: writer and the migration cannot drift apart on what the node table is
#: called.  The flip depth is a fact about a branch's parent node, and a node
#: is a row in this table.
NODE_TABLE = "node"

#: The campaign table — named so the store can confirm a flip depth's campaign
#: actually exists before writing a depth onto a node that references it.  The
#: flip depth is a fact about a node, and the node carries a ``campaign_id``
#: that joins here; a depth written onto a node whose campaign does not exist
#: would be a depth that hangs off nothing.  Spelled once here, and once in
#: :mod:`nulloracle.phi`, :mod:`nulloracle.ksguard` and :mod:`nulloracle.
#: verdict`, so the four writers of the campaign row cannot drift apart on what
#: the campaign table is called.
CAMPAIGN_TABLE = "campaign"

#: The node column the flip depth is written to — the depth at which a branch's
#: parent node's subtree flips null.  Spelled once here so the writer and the
#: migration cannot drift apart on what the column is named.
FLIP_DEPTH_COLUMN = "flip_depth"

#: The geometric probability's floor — the smallest ``p`` the draw accepts.
#: A ``p`` at or below this makes the geometric's mean ``1/p`` unbounded and
#: the draw effectively never terminates, so it is refused.  An open lower
#: bound: ``p`` must be strictly greater than 0.
P_MIN = 0.0

#: The geometric probability's ceiling — the largest ``p`` the draw accepts.
#: A ``p`` at or above this collapses the geometric to a constant depth of 1,
#: the very "always stop at depth 1" the PRD warns teaches the policy nothing,
#: so it is refused.  An open upper bound: ``p`` must be strictly less than 1.
P_MAX = 1.0


def flip_depth(p: Any, *, seed: Any) -> int:
    """§7.3's Type-D flip depth: ``d ~ Geometric(p)`` on the trial count.

    The whole of feature 119's draw in one call: invert a single uniform into
    the number of Bernoulli trials of probability ``p`` until the first
    success, which is the depth at which a Type-D branch flips null.  The
    construction is the standard inverse-CDF one — ``d = 1 + floor(log(U) /
    log(1 - p))`` for a uniform ``U`` drawn from the seeded generator — so the
    draw is reproducible from the seed alone and a campaign replayed next year
    draws the same depth, which is the determinism contract §12 imposes and the
    reason the depth is persisted rather than re-derived.

    The returned depth is always ``>= 1`` — the geometric's support is
    ``{1, 2, 3, …}`` — which is the structural guarantee behind *"every root
    stays real"*: a root sits at depth 0, and a flip depth that could be 0 would
    turn a root null and retype a Type-D campaign as Type-R, which §7.3
    forbids.  The draw cannot return 0, so a root can never be the flip.

    Refuses a ``p`` that is not a genuine probability in the open interval
    ``(0, 1)``, and names what it refuses:

    * ``p`` that is a bool — ``True`` and ``False`` are not probabilities, and
      a truthy-looking ``True`` would collapse the draw to a constant depth of
      1;
    * ``p`` that is not a real number — a probability is a real;
    * ``p <= 0`` — a non-positive probability makes the mean ``1/p``
      non-positive and the draw meaningless;
    * ``p >= 1`` — a probability of 1 or more collapses the geometric to a
      constant depth of 1, the degenerate draw the PRD warns teaches the policy
      "always stop at depth 1," which is worth nothing.

    The interval is open on both ends for both reasons; a ``p`` exactly at a
    bound is refused, not clamped, because a clamped probability would be a
    probability no campaign was designed with.
    """
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        raise KsGuardError(
            f"p must be a real number in (0, 1), got {type(p).__name__} "
            f"({p!r}); the Type-D flip depth is drawn from a geometric of "
            "probability p, and p is a probability — a truthy-looking non-real "
            "is not the probability a branch's flip was drawn from"
        )
    number = float(p)
    if not math.isfinite(number):
        raise KsGuardError(
            f"p must be a finite probability in (0, 1), got {number!r}; a "
            "non-finite p makes the geometric's log(1 - p) meaningless and the "
            "flip depth it draws no depth a campaign was designed with"
        )
    if number <= P_MIN:
        raise KsGuardError(
            f"p must be strictly greater than 0, got {number!r}; a geometric of "
            "non-positive probability has a non-positive mean 1/p and draws no "
            "depth a Type-D branch could flip at"
        )
    if number >= P_MAX:
        raise KsGuardError(
            f"p must be strictly less than 1, got {number!r}; a geometric of "
            "probability 1 collapses to a constant flip depth of 1, the "
            "degenerate draw that teaches the policy 'always stop at depth 1' "
            "(docs/alpha-engine-prd.md §4.1.2), which is worth nothing"
        )
    u = _strict_uniform(seed)
    return math.floor(math.log(u) / math.log(1.0 - number)) + 1


def _strict_uniform(seed: Any) -> float:
    """One uniform in the open interval ``(0, 1)`` from a seeded generator.

    The geometric inversion needs a uniform whose logarithm is finite: ``U = 0``
    makes ``log(U)`` ``-inf`` and ``floor(-inf) + 1`` a depth of ``-inf``, and a
    uniform that could be exactly 0 would draw a depth no branch could flip at.
    The draw therefore resamples until ``U`` is strictly positive, which it
    reaches with probability 1 and, in practice, on the first draw.  The upper
    bound is handled by ``random()`` itself, which returns ``[0.0, 1.0)`` — a
    strict ``< 1`` — so ``log(1 - p)`` is always over a genuine probability and
    ``U`` never needs an upper resample.

    The generator is a :class:`random.Random` seeded from ``seed``; the seed is
    what makes the depth reproducible, so a campaign replayed from the same seed
    draws the same flip depth.  A seed that is not a genuine integer is refused:
    the seed is the whole of the draw's reproducibility, and a seed the language
    cannot seed with would make the "same campaign, same depth" promise
    unenforceable.
    """
    import random

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise KsGuardError(
            f"seed must be an integer, got {type(seed).__name__} ({seed!r}); "
            "the flip depth is drawn from a seeded generator and the seed is "
            "the whole of the draw's reproducibility, so a seed the generator "
            "cannot seed with would make a replayed campaign draw a different "
            "depth"
        )
    rng = random.Random(seed)
    u = rng.random()
    while u <= 0.0:
        u = rng.random()
    return u


class FlipDepth:
    """The store that writes a Type-D branch's flip depth onto its parent node.

    Constructed with the database URL it reads from; :meth:`persist` draws (via
    the caller's ``p``) and writes ``d ~ Geometric(p)`` to ``node.flip_depth``
    for one branch's parent node, and :meth:`load` reads one node's stored depth
    back.  The class resolves its path lazily, so constructing one performs no
    I/O — composition-time work must not touch the disk, the contract every
    store in this workspace states, and the one feature 117's, feature 123's and
    feature 124's stores state for the same ``node`` and ``campaign`` tables.

    The store holds no scores and no labels: it writes one depth, drawn from one
    probability, onto one column.  There is no field here that could leak a
    label partition, deliberately — see :mod:`nulloracle.assignment` and §4.2.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> FlipDepth | None:
        """The flip-depth store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        flip-depth component — a discoverable state, not an exception — while
        the campaign job that must draw §7.3's Type-D flip depths is the caller
        that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store reads from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an operation
        needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the node and campaign tables exist, idempotently.

        ``CREATE TABLE IF NOT EXISTS`` on both the node table and the campaign
        table — the contract every store in this workspace states: a fresh
        database and an existing one take the same path, so no migration step is
        needed here and running the migration over a database this store created
        changes nothing.  The node table is created with feature 97's five
        columns — the ones ``migrations/versions/0118_node_table.py`` spells — so
        a store-created table and a migration-created table are the same schema.

        Feature 119's ``flip_depth`` column is added separately, by
        ``ALTER TABLE``, because the migration that owns the node table predates
        this column: a production table the migration created has the five
        structural columns and not the flip depth, and this store adds the depth
        column to it the first time it is opened.  The add is idempotent — a
        column already present is left alone — so a store-created table (which
        the ``CREATE`` below does not give a flip depth either) and a
        migration-created one both end up with the column, and re-opening a
        database changes nothing.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {NODE_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    parent_id          UUID,
                    campaign_id        UUID NOT NULL,
                    theme_root         TEXT NOT NULL,
                    depth              INT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {CAMPAIGN_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    campaign_type      TEXT NOT NULL,
                    workspace_count    INT NOT NULL,
                    null_fraction      REAL NOT NULL,
                    calibration_status TEXT NOT NULL DEFAULT 'ok',
                    ks_pvalue          REAL,
                    created_at         TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
                """
            )
            has_column = any(
                row[1] == FLIP_DEPTH_COLUMN
                for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")
            )
            if not has_column:
                connection.execute(
                    f"ALTER TABLE {NODE_TABLE} ADD COLUMN {FLIP_DEPTH_COLUMN} INT"
                )
        return connection

    # -- Feature 119: the write -------------------------------------------

    def persist(self, node_id: Any, p: Any) -> int:
        """Draw §7.3's Type-D flip depth for ``node_id``'s branch and persist it.

        The whole of feature 119 in one call: the branch's parent node is
        confirmed to exist, its campaign is confirmed to exist, the depth is
        drawn as ``d ~ Geometric(p)`` from the caller's probability, and it is
        written to ``node.flip_depth``.  The depth is written onto the node the
        caller names — the branch's parent, whose subtree flips at this depth —
        and the grain is that node: re-running it with the same ``p`` and the
        same seed leaves the depth unchanged, and with a different ``p`` refreshes
        it.  The caller's ``p`` is the source of truth, and a branch re-drawn
        with a new probability is the exact thing a refreshed depth records.

        Refuses, in this order, and each refusal names what it is about:

        1. a malformed ``node_id`` or a probability that is not a genuine
           probability in ``(0, 1)`` (:class:`~nulloracle.errors.KsGuardError`)
           — the depth is ``Geometric(p)``, and a ``p`` that is not a
           probability cannot be what it is drawn from;
        2. a node the table does not hold (:class:`~nulloracle.errors.
           KsGuardError`) — the depth is a fact about a branch's parent node,
           and writing it onto a row this store invented would fabricate the
           branch the depth belongs to;
        3. a campaign the table does not hold (:class:`~nulloracle.errors.
           KsGuardError`) — the depth is a fact about a node that references a
           campaign, and a depth that cannot be joined to the campaign its node
           belongs to is a depth that hangs off nothing;
        4. a write that could not be completed.

        The depth written is always ``>= 1`` — the geometric's support — so the
        node's own subtree, read back and resolved, keeps every root real: the
        stored depth can never be the depth of a root.
        """
        node = _validated_node_id(node_id)
        depth = flip_depth(p, seed=node_as_seed(node))
        with closing(self._connect()) as connection, connection:
            self._require_node(connection, node)
            self._require_campaign(connection, node)
            connection.execute(
                f"UPDATE {NODE_TABLE} SET {FLIP_DEPTH_COLUMN} = ? WHERE id = ?",
                (depth, node),
            )
            stored = self._read_node_flip_depth(connection, node)
            if stored != depth:
                raise KsGuardError(
                    f"node {node!r} was written half: the flip_depth row holds "
                    f"{depth!r} and the node row holds {stored!r}; §7.3's Type-D "
                    "flip depth lives on the branch's parent node and a depth "
                    "whose written value and stored value disagree is not a depth"
                )
        return depth

    def load(self, node_id: Any) -> int | None:
        """One node's stored flip depth, or ``None`` when it is not held.

        ``None`` means *the branch was never drawn* — the discovery loop has not
        flipped this branch — which is the honest answer for a node the table
        does not hold.  It does **not** mean the read failed: an unreachable
        database or a node id that cannot join the tree store's key raises, so a
        caller can never mistake a broken store for an undrawn branch.  The value
        returned is the node row's own ``flip_depth`` — the ``Geometric(p)``
        feature 119 persisted — the depth feature 121 reads to resolve a Type-D
        request: real targets below it, permuted targets at or beyond it.
        """
        node = _validated_node_id(node_id)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"SELECT {FLIP_DEPTH_COLUMN} FROM {NODE_TABLE} WHERE id = ?",
                (node,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        return row[0]

    def _require_node(self, connection: sqlite3.Connection, node: str) -> None:
        """Refuse a node the table does not hold, by name.

        The flip depth joins the node row — feature 121 resolves a Type-D
        request against it — so a depth run against a node nobody created is a
        caller bug worth learning before a depth lands nowhere.  The check is a
        read, not a create: a store that inserted the missing node would be
        inventing the branch the depth belongs to.  The discovery loop creates
        the node; this store only fills its flip depth.
        """
        cursor = connection.execute(
            f"SELECT 1 FROM {NODE_TABLE} WHERE id = ?", (node,)
        )
        try:
            found = cursor.fetchone()
        finally:
            cursor.close()
        if found is None:
            raise KsGuardError(
                f"the node table holds no row for {node!r}; §7.3's Type-D flip "
                "depth is fixed *per branch*, so a depth that cannot be joined "
                "to the branch's parent node is refused rather than written onto "
                "a row this store would have to invent — the node is created by "
                "the discovery loop, before any flip is drawn"
            )

    def _require_campaign(self, connection: sqlite3.Connection, node: str) -> None:
        """Refuse a node whose campaign the table does not hold, by name.

        The flip depth is a fact about a node, and the node carries a
        ``campaign_id`` that joins the campaign row.  A depth written onto a node
        whose campaign does not exist would be a depth that hangs off nothing, so
        the store confirms the campaign is held before it writes.  The check is a
        read, not a create: the campaign is created by its planner, before any
        node is expanded.
        """
        cursor = connection.execute(
            f"SELECT campaign_id FROM {NODE_TABLE} WHERE id = ?", (node,)
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None or row[0] is None:
            raise KsGuardError(
                f"node {node!r} names no campaign; §7.3's Type-D flip depth is "
                "a fact about a node in a campaign, and a depth whose node "
                "belongs to no campaign is a depth that hangs off nothing"
            )
        campaign = normalize_node_id(row[0])
        found = connection.execute(
            f"SELECT 1 FROM {CAMPAIGN_TABLE} WHERE id = ?", (campaign,)
        ).fetchone()
        if found is None:
            raise KsGuardError(
                f"the campaign table holds no row for {campaign!r}, the "
                f"campaign node {node!r} belongs to; §7.3's Type-D flip depth "
                "is a fact about a node in a campaign, and a depth that cannot "
                "be joined to the campaign its node belongs to is refused "
                "rather than written onto a node whose campaign does not exist"
            )

    def _read_node_flip_depth(
        self, connection: sqlite3.Connection, node: str
    ) -> Any:
        """The node row's ``flip_depth``, read back inside the transaction.

        The depth the store just wrote, read back rather than trusted, because
        the depth feature 121 will resolve a Type-D request against is the stored
        one — and a depth whose written value and stored value disagree is not a
        depth a branch was drawn with.  A node that vanished between the write and
        the read-back is refused: the depth must be accounted for, and a node that
        cannot be re-read is a node whose depth is unverifiable.
        """
        cursor = connection.execute(
            f"SELECT {FLIP_DEPTH_COLUMN} FROM {NODE_TABLE} WHERE id = ?",
            (node,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"node {node!r} vanished between the flip-depth write and its "
                "read-back; the depth must be accounted for, and a node that "
                "cannot be re-read is a node whose depth is unverifiable"
            )
        return row[0]


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's
    ``node.id``*, and ``node``'s ``id`` is the same kind of value — but
    re-raises its refusal as :class:`~nulloracle.errors.KsGuardError`.  The
    distinction is the taxonomy's: a malformed id handed to the *flip-depth*
    store is a store-contract failure, not a sidecar-schema one, and a caller
    reading ``SidecarError`` out of a flip-depth write would look in the wrong
    module for the cause.  The fraction's, the guard's, the verdict's and this
    module's stores share the same id kind and the same error, so a node whose
    flip depth is fixed and a campaign whose fraction is fixed are validated
    identically.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise KsGuardError(
            f"node_id {value!r} is not a UUID: {exc}"
        ) from exc


def node_as_seed(node: str) -> int:
    """A node id as a stable integer seed for its branch's flip-depth draw.

    The flip depth is drawn from a seeded generator, and the seed is the whole
    of the draw's reproducibility — a campaign replayed from the same seed must
    draw the same depth.  The seed is derived from the node's canonical UUID: the
    hex of the id, as an integer, is a stable, collision-free mapping from a node
    to a seed, so the same node always draws the same depth and two different
    nodes draw independently.  Spelled once here, beside the draw it feeds, so
    the seed a persist writes from and the seed a replay would draw from are one
    seed.
    """
    return int(node.replace("-", ""), 16)


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.  A
    non-SQLite scheme is refused loudly — the Postgres store arrives with the
    migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a branch's
    flip depth must outlive the draw that produced it.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise KsGuardError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a branch's flip depth must outlive the draw that fixed it"
        )
    return Path(path)


def persist_flip_depth(
    node_id: Any,
    p: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Draw §7.3's Type-D flip depth for ``node_id``'s branch and persist it — the module-level spelling.

    Feature 119's sentence as one call: the depth in, drawn from the caller's
    probability, written against its branch's parent node.  The store is resolved
    from ``database_url``, else from ``DATABASE_URL``; a deployment that names
    neither is refused *by name* rather than silently doing nothing, because a
    depth that quietly skipped its write would leave a branch looking undrawn
    while the campaign loop believed it had fixed the flip — which is the failure
    mode this whole feature exists to rule out.

    A :class:`~nulloracle.errors.KsGuardError` from the store is left to
    propagate unwrapped; see the taxonomy for why "the depth could not be written
    down" is a store-contract failure and not a computation one.
    """
    source = os.environ if env is None else env
    url = database_url if database_url is not None else source.get(DATABASE_URL_ENV, "").strip()
    if not url:
        raise KsGuardError(
            f"persist_flip_depth fixes a branch's Type-D flip depth and nothing "
            f"names a store: {DATABASE_URL_ENV} is unset (and no database_url "
            "was supplied), so the flip depth could not be written down. §7.3's "
            "Type-D flip depth is a fact that must actually land on the branch's "
            "parent node — a branch whose depth silently went nowhere would look "
            "undrawn while its campaign loop believed it had fixed the flip"
        )
    return FlipDepth(url).persist(node_id, p)
