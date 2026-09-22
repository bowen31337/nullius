"""The campaign manifest, persisted when the policy selects no batch — feature 242.

app_spec.xml, "Discovery Orchestrator &amp; Campaigns", feature 242: *System
terminates a campaign when the policy selects no batch, persisting a campaign
manifest summarizing the completed tree.*  docs/nullius-tech-architecture.md
§5 states the unit this is about — *"one campaign = one discovery tree
``T_t``"* — and §9.1 states the loop it closes: the inner exploration loop
runs ``CONTINUE(v)`` on the policy's selected batch, and the loop ends when
the policy selects no batch.  That ending is the termination this feature
makes concrete, and the manifest is the record it leaves behind.

**This is the caller's judgement that the pool and the retry defer.**  The two
modules before it in the chain deliberately stop short of terminating:
:func:`discovery.workers.run_batch` answers an empty selection with an empty
stream — *"the policy selected no batch: feature 242's termination is the
caller's judgement, and this pool's answer to nothing selected is nothing"* —
and :func:`discovery.retry.retry_interrupted` does the same for an empty
interrupted batch.  Neither raises and neither decides; both hand the *state*
— *nothing was selected* — to the caller, and feature 242 is that caller.  It
is the one place in this member that looks at an empty selection and says *the
campaign is complete*, and it is a **judgement over the tree's state** rather
than a new count: the campaign is complete when the policy has selected no
batch and every node it did select has been expanded, so the tree that stands
is the whole tree.

**The manifest is a summary of the tree that stands, read from the tree
itself.**  The counts it carries — the branch count, the refine count, the
leaf count, the node count, the deepest depth and the number of distinct
theme roots — are not asserted by the caller and not carried in from the
plan; they are **censused** from the ``node`` rows the tree already holds,
each scoped to the one campaign.  That is deliberate, and it is the same
stance feature 240 takes when it assembles a node row from the columns the
table actually has rather than from a plan: the summary reflects the tree
that was walked, not a claim about it.  A branch is a root (``parent_id``
``IS NULL``), a refine is a non-root (``parent_id`` ``IS NOT NULL``), a leaf
is a node no other node names as its parent, and the census counts each by
reading the rows rather than by trusting the loop's own tally — so a manifest
is answerable to the tree, and a reader (feature 235's ``plan_grid``, which
derives its branch and refine counts from prior manifests) reads numbers that
were measured rather than declared.

**The manifest carries the campaign's ``calibration_status``, and it reads
that status rather than pronouncing it.**  app_spec.xml feature 243 — *"System
rejects a campaign whose ``calibration_status`` is ``VOID`` when adding
completed campaigns to the replay pool"* — reads the manifest the replay pool
holds and refuses the ones calibration voided.  So the manifest must carry the
status, and it carries the one the ``campaign`` row already holds (feature
232's row, feature 124's verdict) rather than spelling the ``VOID`` vocabulary
itself: the verdict module is the one place that word is pronounced, and a
manifest that invented it would be the second place it lived.  This module
therefore **reads** ``calibration_status`` from the ``campaign`` table — the
authority on it — and stores it verbatim, the same read-back discipline
feature 232 applies to its own row.  A campaign with no planning row has no
status to carry, and is refused, because a manifest of a campaign nobody
planned is a summary of nothing.

**Termination is refused when there is no completed tree to summarize.**  The
one ordering law this feature enforces is the mirror of feature 232's: where
feature 232 refuses to create a campaign record once a node has been expanded,
this feature refuses to persist a manifest for a campaign whose tree holds no
node — a campaign that was planned but whose loop never walked a single node
has no tree, and a manifest is *a summary of a completed tree*.  The check is
against the ``node`` table (probed, never created — feature 97 owns it) and
against the ``campaign`` table (the source of the status), each read-only and
each named in the refusal, so an operator learns *which campaign and which
table* rather than a bare SQLite error.  It is :class:`~discovery.errors.
CampaignOrderError`, the ordering class: nothing about the request is
malformed, the world simply holds no completed tree for this campaign.

**The store that persists the manifest is the writer of its own table, and
that is the load-bearing reason no migration is touched.**  The
``campaign_manifest`` table is created by the store itself, idempotently, on
first use — ``CREATE TABLE IF NOT EXISTS`` on every connection, the shape
:mod:`ledger.store` takes for the trial ledger and :mod:`nulloracle.universe`
for its store: the writer owns the table it writes, so no migration step is
needed for this member.  This is not a shortcut and it is not the member
improvising a schema it does not own: feature 232's ``campaign`` and feature
97's ``node`` are *read* here and never created, because the migration is the
authority on those columns, but the ``campaign_manifest`` table is **this
feature's own** — no migration declares it, no feature before 242 names it,
and a migration that created it would be a schema the spec did not ask for
(the honest form of a column the spec withholds is a feature that names it,
which is exactly what ``0118``'s docstring argues for ``created_at``).  So the
store brings its own table up, and the constraint is enforced by the writer,
not by a database constraint this feature was not asked to spell — the same
choice ``0111`` states for ``campaign_id`` and this member restates for every
table it owns the row of.

**Idempotent by campaign identity.**  A manifest is keyed on ``campaign_id``,
and finishing the same completed campaign twice upserts one row rather than
adding a second — the second finish writes the same values the first did and
returns the stored manifest unchanged.  That is the whole of the idempotence a
termination needs: a reclaimed spot instance that re-runs the loop's last step
and re-issues the empty selection must not leave two manifests for one
campaign, any more than feature 240's retry may leave two node rows.  The
``ON CONFLICT(campaign_id) DO UPDATE`` upsert is what makes it so, and the
read-back after the write is what makes the returned value the stored one.

**No component, and the reason is feature 240's with a sharper face.**  A
:class:`CampaignManifests` store closes over a database URL, exactly as
feature 232's :class:`CampaignRecords` does, and it still composes nothing.
The first face is 240's: the manifest is a *value the loop persists and a
reader consumes*, not a policy decision the factory must discover — there is
no judgement here for ``create_app()`` to make, only a row to write and read,
and a builder that registered one would be a function wearing a component's
name, the reason feature 241 gives for the legal set and feature 238 for the
pool.  The sharper second face is this feature's own: a component is built on
**every** ``create_app()`` call, and a registered manifest store would have to
answer *which campaign's manifest does this hold?* — a question with no
answer, because the store holds every completed campaign's, and a builder that
picked one would be a reader pointed at a single campaign's tree.  The
member's registered surface stays feature 232's single store, and the campaign
loop reaches termination the only way the spec allows: by calling
:func:`finish_campaign`, with the campaign id it planned.

**Stdlib only, and import-cheap.**  ``os``, ``sqlite3`` and ``urllib.parse``,
over this member's own values; no third-party import at module scope, so the
factory's scan — which imports this package to fire its ``@register`` — pays
nothing for this module, and a composed application that never terminates a
campaign never opens a database.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import CampaignOrderError, CampaignPlanningError

__all__ = [
    "BRANCH_COUNT_COLUMN",
    "CALIBRATION_STATUS_COLUMN",
    "CAMPAIGN_ID_COLUMN",
    "CAMPAIGN_TABLE",
    "DATABASE_URL_ENV",
    "DEPTH_MAX_COLUMN",
    "LEAF_COUNT_COLUMN",
    "MANIFEST_TABLE",
    "NODE_COUNT_COLUMN",
    "NODE_TABLE",
    "PARENT_ID_COLUMN",
    "REFINE_COUNT_COLUMN",
    "THEME_ROOTS_COLUMN",
    "THEME_ROOT_COLUMN",
    "CampaignManifest",
    "CampaignManifests",
    "TreeSummary",
    "finish_campaign",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the null
#: oracle's seven, the campaign store's, the bootstrap pool's), restated here
#: so this store states its own contract and imports nobody else's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the campaign's planning row lives in — feature 104's, created by
#: ``migrations/versions/0111_campaign_table.py``.  Read here for exactly one
#: question — *what calibration status does this campaign carry?* — and never
#: created: this member owns the manifest row, and the campaign table's schema
#: belongs to the migration that declares it.
CAMPAIGN_TABLE = "campaign"

#: The tree store's node table — feature 97's, created by
#: ``migrations/versions/0118_node_table.py``.  Read here for the whole of the
#: census — every branch, refine and leaf is a row — and never created: the
#: manifest summarizes the tree, it does not own it.
NODE_TABLE = "node"

#: The table this feature owns and the store brings into being — the campaign
#: manifest.  No migration declares it (see the module docstring for why the
#: writer, not a migration, is its authority), so the store creates it
#: idempotently on first use and every manifest row lands here.
MANIFEST_TABLE = "campaign_manifest"

#: The manifest row's key — the campaign whose completed tree it summarizes.
#: One row per campaign, upserted, so a re-issued termination refreshes rather
#: than duplicates.
CAMPAIGN_ID_COLUMN = "campaign_id"

#: The campaign table's own primary key — ``id``, not ``campaign_id``.  The
#: node table references the campaign by ``campaign_id`` (feature 97's column),
#: but the campaign row itself is keyed on ``id`` (feature 104's, migration
#: ``0111``), so reading a campaign's ``calibration_status`` back must join on
#: ``id``.  Named separately so the manifest never confuses the row's key with
#: the node table's reference column.
CAMPAIGN_PK_COLUMN = "id"

#: The manifest row's carried calibration status — read from the ``campaign``
#: table, feature 124's word, stored verbatim so feature 243's replay-pool gate
#: can compare it.
CALIBRATION_STATUS_COLUMN = "calibration_status"

#: The manifest row's branch count — the number of roots (``parent_id`` is
#: ``NULL``), each root the top of one branch the loop planted.
BRANCH_COUNT_COLUMN = "branch_count"

#: The manifest row's refine count — the number of non-root nodes
#: (``parent_id`` is not ``NULL``), each a refinement of its parent.
REFINE_COUNT_COLUMN = "refine_count"

#: The manifest row's leaf count — the nodes no other node names as a parent,
#: the unexpanded frontier the policy left standing when it selected no batch.
LEAF_COUNT_COLUMN = "leaf_count"

#: The manifest row's node count — the whole tree, branches and refinements
#: alike.  A manifest always carries at least one, because a campaign whose
#: tree holds no node has no completed tree to summarize and is refused.
NODE_COUNT_COLUMN = "node_count"

#: The manifest row's deepest depth — how far the deepest branch was walked.
DEPTH_MAX_COLUMN = "depth_max"

#: The manifest row's theme-root count — the distinct ``theme_root`` values the
#: tree spans, the figure feature 234's "at least three distinct theme roots"
#: and feature 235's plan derive from prior manifests.
THEME_ROOTS_COLUMN = "theme_roots"

#: The node table's own columns the census reads — the self-referencing key and
#: its parent, the campaign scope, the theme and the depth.  Named once, so the
#: aggregate statements and the classification agree on which column is which.
ID_COLUMN = "id"
PARENT_ID_COLUMN = "parent_id"
THEME_ROOT_COLUMN = "theme_root"
DEPTH_COLUMN = "depth"

#: The read-only probe that answers *does this database hold a given table at
#: all?*  ``sqlite_master`` is read (never the rows), which makes the check
#: safe on a database this process has no business writing to — the idiom
#: feature 232 uses for its own absent-table refusal and :mod:`bootstrap.
#: _census` uses for the same.  A parameterised statement, so the table name is
#: a bound value rather than interpolated text.
_TABLE_EXISTS_SQL = (
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
)


# -- The value -------------------------------------------------------------------


@dataclass(frozen=True)
class TreeSummary:
    """The census of one campaign's completed tree.

    The six counts the tree yields when it is read row by row, and nothing
    else: the branch count (roots), the refine count (non-roots), the leaf
    count (nodes with no children), the node count (the whole tree), the
    deepest depth and the number of distinct theme roots.  Frozen, so a census
    that has been taken cannot be edited into a different tree by a caller who
    kept a reference — the same discipline :class:`CampaignRecord` states, and
    for the same reason: this value is the record of what the tree held, and a
    mutable one would let a caller retype a completed campaign in memory while
    the rows said otherwise.

    Validated in :meth:`__post_init__`: every count is a genuine non-negative
    integer (a ``bool`` is not a count, and a negative count is not one a tree
    could yield), so a census is a census however it is rebuilt — through
    ``dataclasses.replace`` or unpickling, both of which pass back through the
    check.
    """

    branch_count: int
    refine_count: int
    leaf_count: int
    node_count: int
    depth_max: int
    theme_roots: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "branch_count", _validated_count(self.branch_count, BRANCH_COUNT_COLUMN))
        object.__setattr__(self, "refine_count", _validated_count(self.refine_count, REFINE_COUNT_COLUMN))
        object.__setattr__(self, "leaf_count", _validated_count(self.leaf_count, LEAF_COUNT_COLUMN))
        object.__setattr__(self, "node_count", _validated_count(self.node_count, NODE_COUNT_COLUMN))
        object.__setattr__(self, "depth_max", _validated_count(self.depth_max, DEPTH_MAX_COLUMN))
        object.__setattr__(self, "theme_roots", _validated_count(self.theme_roots, THEME_ROOTS_COLUMN))


@dataclass(frozen=True)
class CampaignManifest:
    """One completed campaign's manifest, as the ``campaign_manifest`` row holds it.

    The whole of what feature 242 persists: ``campaign_id`` (the completed
    campaign's identity, the value feature 243 and feature 235 join by),
    ``calibration_status`` (read from the ``campaign`` row, feature 124's word
    carried verbatim so the replay pool can refuse a voided campaign) and the
    six counts of the completed tree (:class:`TreeSummary`).  Frozen, for the
    same reason :class:`TreeSummary` is — a manifest is the record of a
    termination, and a mutable one would let a caller retype a completed
    campaign in memory while the row said otherwise.

    Validated in :meth:`__post_init__` in addition to the summary's counts: the
    id is canonicalized to the spelling every reader joins it by (a mixed-case
    key would make one campaign look like two), and the calibration status is
    checked only for being present text — its vocabulary is feature 124's
    (``'ok'`` and ``'VOID'``), and a manifest that refused an unknown status
    would be re-spelling a verdict it does not pronounce.
    """

    campaign_id: str
    calibration_status: str
    branch_count: int
    refine_count: int
    leaf_count: int
    node_count: int
    depth_max: int
    theme_roots: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "campaign_id", _validated_campaign_id(self.campaign_id))
        if not isinstance(self.calibration_status, str) or not self.calibration_status.strip():
            raise CampaignPlanningError(
                f"a campaign manifest for {self.campaign_id!r} carries no "
                f"calibration_status ({self.calibration_status!r}); the manifest "
                "carries the ``campaign`` row's status so feature 243's replay-pool "
                "gate can compare it, and a status that is not text is no status a "
                "reader could refuse"
            )
        object.__setattr__(self, "branch_count", _validated_count(self.branch_count, BRANCH_COUNT_COLUMN))
        object.__setattr__(self, "refine_count", _validated_count(self.refine_count, REFINE_COUNT_COLUMN))
        object.__setattr__(self, "leaf_count", _validated_count(self.leaf_count, LEAF_COUNT_COLUMN))
        object.__setattr__(self, "node_count", _validated_count(self.node_count, NODE_COUNT_COLUMN, minimum=1))
        object.__setattr__(self, "depth_max", _validated_count(self.depth_max, DEPTH_MAX_COLUMN))
        object.__setattr__(self, "theme_roots", _validated_count(self.theme_roots, THEME_ROOTS_COLUMN))

    def summary(self) -> TreeSummary:
        """This manifest's :class:`TreeSummary` — the tree, without the campaign.

        Offered because feature 235's ``plan_grid`` reasons over the counts
        (branch, refine, leaf, node, depth, theme roots) and not over the id or
        the status, and a reader that wants the tree alone should not have to
        reach past the two campaign facts.  It is derived, never stored: the
        row holds all eight, and this is the six the census took.
        """
        return TreeSummary(
            branch_count=self.branch_count,
            refine_count=self.refine_count,
            leaf_count=self.leaf_count,
            node_count=self.node_count,
            depth_max=self.depth_max,
            theme_roots=self.theme_roots,
        )

    def row(self) -> dict[str, Any]:
        """The manifest as a store-shaped mapping — a fresh dict per call.

        The column names are the ``campaign_manifest`` table's own, the same
        discipline :meth:`CampaignRecord.row` states: a rendered mapping names
        the same things the table's columns do.
        """
        return {
            CAMPAIGN_ID_COLUMN: self.campaign_id,
            CALIBRATION_STATUS_COLUMN: self.calibration_status,
            BRANCH_COUNT_COLUMN: self.branch_count,
            REFINE_COUNT_COLUMN: self.refine_count,
            LEAF_COUNT_COLUMN: self.leaf_count,
            NODE_COUNT_COLUMN: self.node_count,
            DEPTH_MAX_COLUMN: self.depth_max,
            THEME_ROOTS_COLUMN: self.theme_roots,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(campaign_id={self.campaign_id!r}, "
            f"calibration_status={self.calibration_status!r}, "
            f"node_count={self.node_count!r}, branch_count={self.branch_count!r}, "
            f"refine_count={self.refine_count!r}, leaf_count={self.leaf_count!r})"
        )


# -- The census ------------------------------------------------------------------


def _census(connection: sqlite3.Connection, campaign: str) -> TreeSummary:
    """Read one campaign's completed tree and count it — the census.

    Every aggregate is scoped to ``campaign`` and read from the ``node`` rows
    rather than asserted, so the summary is answerable to the tree.  A branch
    is a root (``parent_id`` is ``NULL``), a refine is a non-root, a leaf is a
    node that no other node names as a parent — computed with a subquery that
    **excludes ``NULL`` parents**, because ``id NOT IN (… , NULL)`` would
    return no rows at all and silently report zero leaves, the one SQL trap the
    census must not fall into.  The distinct-theme-root count and the deepest
    depth are the two remaining axes the manifest carries.

    The connection is the caller's and already open; this reads only.  It
    creates nothing, because the census summarizes a tree it does not own.
    """
    scope = "WHERE campaign_id = ?"
    node_count = int(
        connection.execute(
            f"SELECT COUNT(*) FROM {NODE_TABLE} {scope}", (campaign,)
        ).fetchone()[0]
    )
    branch_count = int(
        connection.execute(
            f"SELECT COUNT(*) FROM {NODE_TABLE} {scope} AND {PARENT_ID_COLUMN} IS NULL",
            (campaign,),
        ).fetchone()[0]
    )
    refine_count = node_count - branch_count
    leaf_count = int(
        connection.execute(
            f"SELECT COUNT(*) FROM {NODE_TABLE} {scope} AND {ID_COLUMN} NOT IN "
            f"(SELECT {PARENT_ID_COLUMN} FROM {NODE_TABLE} {scope} AND "
            f"{PARENT_ID_COLUMN} IS NOT NULL)",
            (campaign, campaign),
        ).fetchone()[0]
    )
    depth_max_row = connection.execute(
        f"SELECT MAX({DEPTH_COLUMN}) FROM {NODE_TABLE} {scope}", (campaign,)
    ).fetchone()
    depth_max = 0 if depth_max_row[0] is None else int(depth_max_row[0])
    theme_roots = int(
        connection.execute(
            f"SELECT COUNT(DISTINCT {THEME_ROOT_COLUMN}) FROM {NODE_TABLE} {scope}",
            (campaign,),
        ).fetchone()[0]
    )
    return TreeSummary(
        branch_count=branch_count,
        refine_count=refine_count,
        leaf_count=leaf_count,
        node_count=node_count,
        depth_max=depth_max,
        theme_roots=theme_roots,
    )


# -- The store -------------------------------------------------------------------


class CampaignManifests:
    """The store that persists and reads a completed campaign's manifest.

    Constructed with the database URL it writes to; :meth:`record` upserts one
    manifest row keyed on the campaign id (so a re-issued termination refreshes
    rather than duplicates), and :meth:`get` reads one back.  The class
    resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store in
    this workspace states.

    **The store is the writer of its own table, and it creates that table
    rather than expecting a migration to.**  :meth:`_connect` runs ``CREATE
    TABLE IF NOT EXISTS`` on every connection — the ledger's and the universe
    member's shape for a table the member owns — so a fresh database and an
    existing one take the same path and no migration step is needed for this
    member.  It creates *only* ``campaign_manifest``: the ``campaign`` and
    ``node`` tables are read, never created, because the migration is the
    authority on those (feature 232 and feature 97 own them), while
    ``campaign_manifest`` is this feature's own and no migration declares it.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise CampaignPlanningError(
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
    ) -> CampaignManifests | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        manifest store — a discoverable state, not an exception — while the
        orchestrator that must terminate a campaign and record it is the caller
        that must not find itself without a store to write through.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the manifest's table — the writer's act.

        The schema is created idempotently on every connection, so a fresh
        database and an existing one take the same path and no migration step
        is needed for this member — the contract the ledger and universe
        members state for their own tables.  The caller owns the connection;
        use it as a context manager to commit, which is what :meth:`record`
        does.

        **Only ``campaign_manifest`` is created here.**  The ``campaign`` and
        ``node`` tables this feature reads are the migration's — feature 232's
        and feature 97's — and creating them would be this member improvising a
        schema it does not own.  So an unmigrated database raises SQLite's own
        ``no such table`` on the read paths rather than being silently given a
        table this member guessed at; a deployment reaches the revision by
        running the migration, and one that has not is a fact an operator
        should read.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_MANIFEST_SCHEMA)
        return connection

    # -- Feature 242: record and read ---------------------------------------

    def record(self, manifest: CampaignManifest) -> None:
        """Upsert one campaign's manifest row — idempotent by campaign id.

        The write names all eight columns explicitly rather than ``INSERT``-ing
        a whole row blindly, and the ``ON CONFLICT(campaign_id) DO UPDATE``
        clause is the load-bearing half: a second finish of the same completed
        campaign refreshes the one row rather than adding a second, so a
        reclaimed spot instance that re-issues the empty selection leaves one
        manifest, not two.  The values written are the manifest's own, so the
        upsert and the read-back are one value.
        """
        row = manifest.row()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {MANIFEST_TABLE} "
                f"({CAMPAIGN_ID_COLUMN}, {CALIBRATION_STATUS_COLUMN}, "
                f"{BRANCH_COUNT_COLUMN}, {REFINE_COUNT_COLUMN}, {LEAF_COUNT_COLUMN}, "
                f"{NODE_COUNT_COLUMN}, {DEPTH_MAX_COLUMN}, {THEME_ROOTS_COLUMN}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                f"ON CONFLICT({CAMPAIGN_ID_COLUMN}) DO UPDATE SET "
                f"{CALIBRATION_STATUS_COLUMN}=excluded.{CALIBRATION_STATUS_COLUMN}, "
                f"{BRANCH_COUNT_COLUMN}=excluded.{BRANCH_COUNT_COLUMN}, "
                f"{REFINE_COUNT_COLUMN}=excluded.{REFINE_COUNT_COLUMN}, "
                f"{LEAF_COUNT_COLUMN}=excluded.{LEAF_COUNT_COLUMN}, "
                f"{NODE_COUNT_COLUMN}=excluded.{NODE_COUNT_COLUMN}, "
                f"{DEPTH_MAX_COLUMN}=excluded.{DEPTH_MAX_COLUMN}, "
                f"{THEME_ROOTS_COLUMN}=excluded.{THEME_ROOTS_COLUMN}",
                (
                    row[CAMPAIGN_ID_COLUMN],
                    row[CALIBRATION_STATUS_COLUMN],
                    row[BRANCH_COUNT_COLUMN],
                    row[REFINE_COUNT_COLUMN],
                    row[LEAF_COUNT_COLUMN],
                    row[NODE_COUNT_COLUMN],
                    row[DEPTH_MAX_COLUMN],
                    row[THEME_ROOTS_COLUMN],
                ),
            )

    def get(self, campaign_id: Any) -> CampaignManifest | None:
        """One campaign's stored manifest, or ``None`` when it is not held.

        ``None`` means *the campaign has no manifest* — it was never finished —
        which is the honest answer for an id the table does not hold.  It does
        **not** mean the read failed: an unreachable database raises, so a
        caller can never mistake a broken store for an unfinished campaign.
        The same distinction :meth:`CampaignRecords.get` draws for the campaign
        row.
        """
        campaign = _validated_campaign_id(campaign_id)
        if campaign is None:
            raise CampaignPlanningError(
                "get() reads one campaign's manifest and needs the id to read "
                "it by; got None, which names no row"
            )
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {CAMPAIGN_ID_COLUMN}, {CALIBRATION_STATUS_COLUMN}, "
                f"{BRANCH_COUNT_COLUMN}, {REFINE_COUNT_COLUMN}, {LEAF_COUNT_COLUMN}, "
                f"{NODE_COUNT_COLUMN}, {DEPTH_MAX_COLUMN}, {THEME_ROOTS_COLUMN} "
                f"FROM {MANIFEST_TABLE} WHERE {CAMPAIGN_ID_COLUMN} = ?",
                (campaign,),
            ).fetchone()
        if row is None:
            return None
        return _manifest_from_row(row)


# -- The termination -------------------------------------------------------------


def finish_campaign(
    campaign_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CampaignManifest:
    """Terminate one campaign and persist its manifest — feature 242 as one call.

    The caller's judgement the pool and the retry defer: the campaign id in,
    the stored manifest out.  The steps, and why each is where it is:

    1. **Resolve the store.**  From ``database_url``, else from
       ``DATABASE_URL``; a deployment that names neither is refused *by name*
       rather than silently doing nothing, because a termination that quietly
       skipped its write would leave a completed campaign with no manifest —
       and feature 243's replay-pool gate and feature 235's ``plan_grid`` would
       have no completed tree to read.
    2. **Prove there is a campaign to summarize.**  Read the ``campaign``
       row's ``calibration_status`` — the status the manifest carries — and
       refuse when the campaign was never planned, because a manifest of a
       campaign nobody planned is a summary of nothing.
    3. **Prove there is a completed tree.**  Refuse when the ``node`` table
       holds no node under this campaign.  The frontier the loop walks is a
       runtime reveal-set (architecture §10.1: the ``revealed`` set the policy
       selects from), not a column on the persisted tree — the node table
       records only ``id, parent_id, campaign_id, theme_root, depth`` and no
       "open"/"expanded" marker, because a persisted child is terminal only
       when the loop reveals no recorded child.  The one frontier-non-empty
       state a finished loop can leave behind is a campaign that was *planned*
       but whose loop never expanded a node: its roots are still open, the
       policy has selected no batch, and there is no tree to summarize.  That
       is the ordering law feature 3 names — terminate only when the tree holds
       no open node — and it is the same ``node_count == 0`` refusal here, the
       mirror of feature 232's ordering law.
    4. **Census the tree** — the branch, refine, leaf, node, depth and
       theme-root counts, read from the rows.
    5. **Build and upsert the manifest**, then read it back and return what the
       table holds rather than what the census computed, so the returned value
       is the stored one.

    Refuses, each naming what it is about: a campaign id that is not a UUID
    (:class:`~discovery.errors.CampaignPlanningError`); a campaign with no
    planning row or no node in its tree
    (:class:`~discovery.errors.CampaignOrderError`) — the ordering law, the
    mirror of feature 232's; a database with no ``campaign`` or ``node`` table,
    which raises the store's own named refusal rather than a bare SQLite error.
    """
    campaign = _validated_campaign_id(campaign_id)
    if campaign is None:
        raise CampaignPlanningError(
            "finish_campaign terminates a campaign and needs its id; got None, "
            "which names no campaign"
        )
    resolved = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV, "").strip()
    )
    if not resolved:
        raise CampaignPlanningError(
            f"finish_campaign terminates a campaign and persists its manifest, "
            f"and nothing names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so the manifest could not be recorded. "
            "Feature 242's manifest is a fact that must actually land in the "
            "table — a completed campaign with no manifest would be invisible to "
            "feature 243's replay-pool gate and to feature 235's plan_grid, which "
            "derive the next campaign's plan from prior manifests"
        )
    store = CampaignManifests(resolved)
    with closing(store._connect()) as connection, connection:
        status = _calibration_status_of(connection, campaign)
        if not _table_exists(connection, NODE_TABLE):
            raise CampaignOrderError(
                f"campaign {campaign!r} has no tree: the {NODE_TABLE} table does "
                "not exist, so there is no completed tree for a manifest to "
                "summarize — feature 242 terminates a campaign whose loop walked "
                "its tree, and a campaign with no node table has walked none"
            )
        node_count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {NODE_TABLE} WHERE {CAMPAIGN_ID_COLUMN} = ?",
                (campaign,),
            ).fetchone()[0]
        )
        if node_count == 0:
            raise CampaignOrderError(
                f"campaign {campaign!r} has no node in the tree, so its frontier "
                "still holds an open node — feature 242 terminates a campaign "
                "whose loop walked its tree, and a campaign that was planned but "
                "never expanded has no tree to summarize. Terminate a campaign "
                "whose policy selected no batch and every selected node has been "
                "expanded, not one whose roots were never expanded"
            )
        summary = _census(connection, campaign)
    manifest = CampaignManifest(
        campaign_id=campaign,
        calibration_status=status,
        branch_count=summary.branch_count,
        refine_count=summary.refine_count,
        leaf_count=summary.leaf_count,
        node_count=summary.node_count,
        depth_max=summary.depth_max,
        theme_roots=summary.theme_roots,
    )
    store.record(manifest)
    stored = store.get(campaign)
    if stored is None:  # pragma: no cover - the upsert always lands a row
        raise CampaignOrderError(
            f"the manifest for campaign {campaign!r} could not be read back "
            "after it was written; a completed campaign's manifest is a fact "
            "that must be accounted for, and a row that cannot be re-read is a "
            "termination this store cannot vouch for"
        )
    return stored


# -- The words -------------------------------------------------------------------


def _manifest_from_row(row: tuple[Any, ...]) -> CampaignManifest:
    """Build a :class:`CampaignManifest` from a stored row, named.

    The read path's one constructor, so :meth:`CampaignManifests.get` and
    :func:`finish_campaign`'s read-back cannot disagree about which column is
    which.  A validation refusal raised from the row names the campaign it came
    off.
    """
    campaign = row[0]
    try:
        return CampaignManifest(
            campaign_id=row[0],
            calibration_status=row[1],
            branch_count=row[2],
            refine_count=row[3],
            leaf_count=row[4],
            node_count=row[5],
            depth_max=row[6],
            theme_roots=row[7],
        )
    except CampaignPlanningError as exc:
        raise CampaignPlanningError(
            f"the manifest row for {campaign!r} could not be read as a "
            f"campaign manifest: {exc}"
        ) from exc


def _calibration_status_of(
    connection: sqlite3.Connection, campaign: str
) -> str:
    """The ``campaign`` row's ``calibration_status`` — read, never created.

    The status the manifest carries is the campaign's own, read from the table
    feature 232's row lives in.  A campaign with no planning row has no status
    to carry: the manifest would be summarizing a campaign nobody planned, so
    the absence is refused by name rather than defaulted — a defaulted status
    would be a verdict the manifest invented, and feature 243's gate compares
    the real one.  The ``campaign`` table is probed first, so an unmigrated
    database is refused as *no campaign table* rather than surfacing SQLite's
    bare ``no such table``.
    """
    if not _table_exists(connection, CAMPAIGN_TABLE):
        raise CampaignOrderError(
            f"campaign {campaign!r} has no planning row: the {CAMPAIGN_TABLE} "
            "table does not exist, so there is no calibration status a manifest "
            "could carry — feature 242 summarizes a campaign that was planned "
            "(feature 232's row), and a database with no campaign table has "
            "planned none. Run the migration before terminating"
        )
    cursor = connection.execute(
        f"SELECT {CALIBRATION_STATUS_COLUMN} FROM {CAMPAIGN_TABLE} "
        f"WHERE {CAMPAIGN_PK_COLUMN} = ?",
        (campaign,),
    )
    try:
        row = cursor.fetchone()
    finally:
        cursor.close()
    if row is None:
        raise CampaignOrderError(
            f"campaign {campaign!r} has no planning row, so there is no "
            "calibration status a manifest could carry — feature 242 summarizes "
            "a campaign that was planned (feature 232's row), and a campaign "
            "with no row was never planned. Finish a campaign that was planned "
            "and expanded, not one that was planned only"
        )
    status = row[0]
    if not isinstance(status, str) or not status.strip():
        raise CampaignPlanningError(
            f"campaign {campaign!r} carries no calibration_status "
            f"({status!r}); the manifest carries the campaign row's status so "
            "feature 243's replay-pool gate can compare it, and a status that "
            "is not text is no status a reader could refuse"
        )
    return status


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    """Whether ``connection`` holds a table named ``name`` — read-only.

    The ``sqlite_master`` probe feature 232 uses for its own absent-table
    refusal: the rows are never read, only the schema, so the check is safe on
    a database this process has no business writing to and costs nothing when
    the table is absent.  A parameterised statement, so the table name is a
    bound value rather than interpolated text.
    """
    return (
        connection.execute(_TABLE_EXISTS_SQL, (name,)).fetchone() is not None
    )


def _validated_campaign_id(value: Any) -> str | None:
    """Validate a campaign id, returning canonical UUID text or ``None``.

    ``None`` is refused here rather than passed through — unlike feature 232's
    write path, which lets the table mint an id — because a manifest is keyed
    on an id that already exists (the campaign was planned and expanded before
    termination), so *"let the table mint it"* is not a supported ask: there is
    no minting left to do, only a join.  Anything else must be a
    :class:`uuid.UUID` or text ``uuid.UUID`` parses, canonicalized the way
    every id in this workspace is, because the value joins the ``node`` rows
    and the ``campaign`` row and a mixed-case key would make one campaign look
    like two.
    """
    import uuid as _uuid  # local import: only the census path needs it

    if value is None:
        raise CampaignPlanningError(
            "a campaign manifest is keyed on the id of a campaign that was "
            "already planned and expanded, so there is no id left to mint — "
            "got None, which is the *write* path's 'let the table mint it' and "
            "names no completed campaign"
        )
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(_uuid.UUID(text))
            except ValueError:
                pass
    raise CampaignPlanningError(
        f"campaign_id {value!r} is not a UUID; a campaign's id is the value "
        "the node rows and the campaign row join by, so an id that cannot be "
        "canonicalized names no completed campaign a manifest could summarize"
    )


def _validated_count(value: Any, field_name: str, *, minimum: int = 0) -> int:
    """Refuse a census count that is not a genuine integer at least ``minimum``.

    The same check feature 232 applies to ``workspace_count``, restated for the
    manifest's counts: a ``bool`` is not a count (a truthy ``True`` would
    report a branch count of one for a tree of any size), a non-``int`` is not
    a count (a fractional branch count is not a count), and a count below
    ``minimum`` is not one a tree could yield.  ``node_count`` requires at
    least one — a manifest summarizes a tree that stands — while the other
    counts floor at zero.  Named with its field and its floor, so a refusal
    says which count and how far below.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CampaignPlanningError(
            f"a campaign manifest's {field_name} must be a genuine integer, "
            f"got {value!r} ({type(value).__name__}); the manifest's counts are "
            "a census of the tree's rows, and a non-integer count is no census"
        )
    if value < minimum:
        raise CampaignPlanningError(
            f"a campaign manifest's {field_name} must be at least {minimum}, "
            f"got {value!r}; the manifest's counts are a census of the tree's "
            f"rows, and a count below {minimum} is not one a completed tree "
            "could yield"
        )
    return value


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same convention the rest of the spine uses, and deliberately re-stated
    rather than imported: a store states its own contract and the refusal is
    this member's own error class.  A non-SQLite scheme is refused loudly — the
    spec's single-machine allowance is what a stdlib store can speak — and a
    pathless (in-memory) URL is refused too: an in-memory database dies with
    the connection that opened it, and a campaign manifest must outlive the
    termination call that produced it, because feature 243's replay pool and
    feature 235's planner open it in another process entirely.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CampaignPlanningError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the manifest "
            "table already lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CampaignPlanningError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CampaignPlanningError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened it, "
            "and a campaign manifest must outlive the termination call that "
            "made it — feature 243's replay pool and feature 235's planner join "
            "this row from another process"
        )
    return Path(path)


#: The manifest table's DDL, created idempotently by the store on first use.
#: One row per completed campaign, keyed on ``campaign_id``.  The columns are
#: this feature's own — no migration declares this table — and the types are
#: the tree's own (``INT`` for the counts, ``TEXT`` for the status), the same
#: spellings ``0118`` and ``0111`` use for the columns they declare, so the
#: manifest's counts and the tree's are one kind of value.  ``calibration_status``
#: is ``NOT NULL``: a manifest always carries the campaign's status, read from
#: the ``campaign`` row, and a manifest with no status would be a verdict no
#: reader could compare.
_MANIFEST_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {MANIFEST_TABLE} (
    {CAMPAIGN_ID_COLUMN}     UUID NOT NULL PRIMARY KEY,
    {CALIBRATION_STATUS_COLUMN} TEXT NOT NULL,
    {BRANCH_COUNT_COLUMN}    INT  NOT NULL,
    {REFINE_COUNT_COLUMN}    INT  NOT NULL,
    {LEAF_COUNT_COLUMN}      INT  NOT NULL,
    {NODE_COUNT_COLUMN}      INT  NOT NULL,
    {DEPTH_MAX_COLUMN}       INT  NOT NULL,
    {THEME_ROOTS_COLUMN}     INT  NOT NULL
)
"""
