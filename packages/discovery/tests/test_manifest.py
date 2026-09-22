"""Features 242 and 243: the campaign manifest, and the replay pool's admission.

The one place in this member that looks at an empty selection and says *the
campaign is complete*, and the place that reads that record back when the pool
would take it.  The tests pin the five things the two features are about:

1. **Termination is a judgement over the tree's state, not a new count.**  A
   campaign whose loop walked its tree and then selected no batch terminates
   and persists a manifest whose counts are *censused from the tree's rows* —
   branch (roots), refine (non-roots), leaf (nodes with no children), node
   (the whole tree), depth (deepest) and theme-roots (distinct ``theme_root``)
   — rather than asserted by the caller.
2. **The manifest carries the campaign's calibration status, read from the
   ``campaign`` row.**  A completed campaign whose calibration was voided
   persists that verdict verbatim, so feature 243's replay-pool gate can
   compare it.
3. **Termination is refused when there is no completed tree.**  A campaign that
   was planned but never expanded a node, or whose tree table does not exist,
   raises :class:`CampaignOrderError` naming the campaign and the table.
4. **The manifest is idempotent by campaign identity.**  Finishing the same
   completed campaign twice upserts one row rather than adding a second.
5. **A campaign §7.4 voided is refused when the pool would take it.**  Feature
   243's gate reads the *set* of completed manifests and refuses the batch
   whole, naming every voided campaign, rather than silently filtering one out
   — because a pool holding a void campaign makes every headline number
   derived from it fiction, and because membership is the caller's decision.

The database is brought to schema the way a deployment does — through the
migration files, by path — because the manifest reads the ``campaign`` and
``node`` tables the migrations own (features 232 and 97) and creates only its
own ``campaign_manifest`` table.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing

import pytest

from discovery import (
    CALIBRATION_STATUS_COLUMN,
    CAMPAIGN_ID_COLUMN,
    CAMPAIGN_TABLE,
    VOID_CAMPAIGN_CODE,
    CampaignManifest,
    CampaignManifests,
    TreeSummary,
    admit_completed_campaigns,
    errors,
    finish_campaign,
)
from discovery.campaign import ID_COLUMN as CAMPAIGN_PK_COLUMN
from discovery.manifest import (
    BRANCH_COUNT_COLUMN,
    DEPTH_MAX_COLUMN,
    LEAF_COUNT_COLUMN,
    MANIFEST_TABLE,
    NODE_COUNT_COLUMN,
    REFINE_COUNT_COLUMN,
    THEME_ROOTS_COLUMN,
)


def _insert_campaign(database_url: str, campaign: str, *, calibration_status: str = "ok") -> None:
    """Insert one campaign row — the planner's act, feature 232's row.

    Raw SQL against the migrated campaign table, the same stance the suite
    takes for planting a node: the manifest reads the campaign's
    ``calibration_status`` from this row, so a test that wants a voided
    campaign writes the verdict the KS guard would have written, rather than
    acquiring a dependency on how a campaign is normally created.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} ({CAMPAIGN_PK_COLUMN}, campaign_type, "
            f"workspace_count, null_fraction, {CALIBRATION_STATUS_COLUMN}) "
            "VALUES (?, 'type-r', 8, 0.25, ?)",
            (campaign, calibration_status),
        )


def _path_of(database_url: str):
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL in a test.

    The same three-step translation the member's store mirrors and the suite
    uses to plant a node — restated here so the test reaches the tree's rows
    without pinning the store's private ``_sqlite_path``.
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return unquote(parsed.path).removeprefix("/")


def _plant_node(database_url: str, campaign: str, *, theme_root: str, parent_id: str | None = None, depth: int = 0) -> str:
    """Insert one node with an explicit theme_root — the act feature 232 forbids first.

    Raw SQL against the migrated node table, the same stance the suite takes
    for planting a campaign row: the manifest censuses the tree's rows, so a
    test that wants a tree with several distinct theme roots must be able to
    name the theme of each node.  The ``plant_root`` fixture hardcodes
    ``theme_root="macro"`` (its keyword is not a theme), so this helper is the
    route to a multi-theme tree; ``parent_id`` stays ``NULL`` for a root.
    """
    identifier = str(uuid.uuid4())
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            f"INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            (identifier, parent_id, campaign, theme_root, depth),
        )
    return identifier


def _manifest(campaign: str, *, calibration_status: str) -> CampaignManifest:
    """One manifest built in memory, for the gate's pure-value tests.

    Feature 243's gate judges manifests, not databases, so the tests that are
    about the *comparison* — the exact spelling, a lone manifest, a batch that
    is not a batch — build the value directly rather than round-tripping a tree
    through the store.  The counts are a trivial valid census: only the status
    is load-bearing here, and a test that had to plant a tree to ask about one
    string would be pinning the census a second time over.
    """
    return CampaignManifest(
        campaign_id=campaign,
        calibration_status=calibration_status,
        branch_count=1,
        refine_count=0,
        leaf_count=1,
        node_count=1,
        depth_max=0,
        theme_roots=1,
    )


# -- The value -------------------------------------------------------------------


def test_tree_summary_counts_are_validated() -> None:
    """A census count that is not a genuine integer is refused, by name."""
    # A genuine all-non-negative-integer census is valid.
    TreeSummary(branch_count=1, refine_count=0, leaf_count=1, node_count=2, depth_max=1, theme_roots=1)
    # A boolean is not a count, even though ``True == 1``.
    with pytest.raises(errors.CampaignPlanningError):
        TreeSummary(branch_count=True, refine_count=0, leaf_count=1, node_count=2, depth_max=1, theme_roots=1)
    # A negative count is not one a tree could yield.
    with pytest.raises(errors.CampaignPlanningError):
        TreeSummary(branch_count=-1, refine_count=0, leaf_count=1, node_count=2, depth_max=1, theme_roots=1)


def test_manifest_requires_a_tree() -> None:
    """A manifest with no node is not a summary of a completed tree."""
    campaign = str(uuid.uuid4())
    with pytest.raises(errors.CampaignPlanningError):
        CampaignManifest(
            campaign_id=campaign,
            calibration_status="ok",
            branch_count=0,
            refine_count=0,
            leaf_count=0,
            node_count=0,
            depth_max=0,
            theme_roots=0,
        )


def test_manifest_requires_a_campaign_id() -> None:
    """A manifest keyed on no campaign names no completed campaign."""
    with pytest.raises(errors.CampaignPlanningError):
        CampaignManifest(
            campaign_id=None,
            calibration_status="ok",
            branch_count=1,
            refine_count=0,
            leaf_count=1,
            node_count=2,
            depth_max=1,
            theme_roots=1,
        )


def test_manifest_requires_a_status() -> None:
    """A manifest with no calibration status carries no verdict a reader could compare."""
    campaign = str(uuid.uuid4())
    with pytest.raises(errors.CampaignPlanningError):
        CampaignManifest(
            campaign_id=campaign,
            calibration_status="",
            branch_count=1,
            refine_count=0,
            leaf_count=1,
            node_count=2,
            depth_max=1,
            theme_roots=1,
        )


def test_manifest_summary_and_row() -> None:
    """A manifest's summary is the six counts, and its row names the table's columns."""
    campaign = str(uuid.uuid4())
    manifest = CampaignManifest(
        campaign_id=campaign,
        calibration_status="VOID",
        branch_count=2,
        refine_count=5,
        leaf_count=4,
        node_count=7,
        depth_max=3,
        theme_roots=3,
    )
    summary = manifest.summary()
    assert summary == TreeSummary(
        branch_count=2, refine_count=5, leaf_count=4, node_count=7, depth_max=3, theme_roots=3
    )
    row = manifest.row()
    assert row == {
        CAMPAIGN_ID_COLUMN: campaign,
        CALIBRATION_STATUS_COLUMN: "VOID",
        BRANCH_COUNT_COLUMN: 2,
        REFINE_COUNT_COLUMN: 5,
        LEAF_COUNT_COLUMN: 4,
        NODE_COUNT_COLUMN: 7,
        DEPTH_MAX_COLUMN: 3,
        THEME_ROOTS_COLUMN: 3,
    }


# -- Feature 242: termination on an empty selection --------------------------------


def test_completed_campaign_terminates_and_persists_manifest(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """The policy selected no batch: the campaign terminates and persists its tree.

    A campaign that was planned, whose loop planted a tree (one root, one
    refinement, one leaf) and then selected no batch, terminates and persists a
    manifest whose counts are censused from the tree's rows.
    """
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="ok")
    root = _plant_node(migrated_with_tree, campaign_id, theme_root="macro", depth=0)
    child = _plant_node(migrated_with_tree, campaign_id, theme_root="momentum", parent_id=root, depth=1)
    leaf = _plant_node(migrated_with_tree, campaign_id, theme_root="momentum", parent_id=child, depth=2)
    _ = leaf

    manifest = finish_campaign(campaign_id, database_url=migrated_with_tree)

    assert manifest.campaign_id == campaign_id
    assert manifest.calibration_status == "ok"
    assert manifest.branch_count == 1  # one root (parent_id NULL)
    assert manifest.refine_count == 2  # two non-roots
    assert manifest.leaf_count == 1  # the deepest node, named by no other
    assert manifest.node_count == 3  # the whole tree
    assert manifest.depth_max == 2  # deepest branch walked to depth 2
    assert manifest.theme_roots == 2  # macro and momentum


def test_manifest_is_persisted_and_readable(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """The persisted manifest is readable back, and the store's table is its own."""
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="ok")
    root = plant_root(campaign_id, depth=0, theme_root="macro")
    plant_root(campaign_id, parent_id=root, depth=1, theme_root="momentum")

    finished = finish_campaign(campaign_id, database_url=migrated_with_tree)

    # The store brings its own table up; it exists after a finish, and only
    # that table — the campaign and node tables were the migration's.
    with closing(sqlite3.connect(_path_of(migrated_with_tree))) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert MANIFEST_TABLE in tables
    assert CAMPAIGN_TABLE in tables

    store = CampaignManifests(migrated_with_tree)
    stored = store.get(campaign_id)
    assert stored is not None
    assert stored.campaign_id == finished.campaign_id
    assert stored.calibration_status == finished.calibration_status
    assert stored.node_count == finished.node_count
    assert stored.branch_count == finished.branch_count
    assert stored.refine_count == finished.refine_count
    assert stored.leaf_count == finished.leaf_count
    assert stored.depth_max == finished.depth_max
    assert stored.theme_roots == finished.theme_roots


def test_manifest_carries_a_voided_calibration(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """A completed campaign whose calibration was voided persists that verdict.

    The manifest carries the campaign row's status verbatim — it reads it, it
    does not pronounce it — so feature 243's replay-pool gate can compare it.
    """
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="VOID")
    root = plant_root(campaign_id, depth=0, theme_root="macro")
    plant_root(campaign_id, parent_id=root, depth=1, theme_root="momentum")

    manifest = finish_campaign(campaign_id, database_url=migrated_with_tree)

    assert manifest.calibration_status == "VOID"


def test_census_counts_multiple_branches(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """A tree of several branches is censused branch by branch.

    Three roots (three branches), one refinement under the first, two
    refinements under the second — the census counts each axis from the rows,
    so the manifest reflects the tree that stood, not a claim about it.  Leaves
    are the nodes no other node names as a parent: c, the child of a, and the
    two children of b.
    """
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="ok")
    a = _plant_node(migrated_with_tree, campaign_id, theme_root="macro", depth=0)
    b = _plant_node(migrated_with_tree, campaign_id, theme_root="momentum", depth=0)
    c = _plant_node(migrated_with_tree, campaign_id, theme_root="regime", depth=0)
    _plant_node(migrated_with_tree, campaign_id, theme_root="macro", parent_id=a, depth=1)
    _plant_node(migrated_with_tree, campaign_id, theme_root="momentum", parent_id=b, depth=1)
    _plant_node(migrated_with_tree, campaign_id, theme_root="momentum", parent_id=b, depth=2)
    _ = c

    manifest = finish_campaign(campaign_id, database_url=migrated_with_tree)

    assert manifest.branch_count == 3  # a, b, c — three roots
    assert manifest.refine_count == 3  # the three non-roots
    assert manifest.leaf_count == 4  # c, the child of a, the two children of b
    assert manifest.node_count == 6  # the whole tree
    assert manifest.depth_max == 2  # b's deepest branch
    assert manifest.theme_roots == 3  # macro, momentum, regime


# -- Feature 242: refusal when there is no completed tree --------------------------


def test_planned_but_unexpanded_campaign_is_refused(migrated_with_tree: str, campaign_id: str) -> None:
    """A campaign whose frontier still holds an open node is refused.

    The ordering law feature 3 and feature 7 name: the loop terminates only
    when the tree holds no open node.  The frontier is a runtime reveal-set,
    not a column on the persisted tree, so the one frontier-non-empty state a
    finished loop leaves behind is a campaign that was planned but whose loop
    never expanded a node — its roots are still open, the policy has selected
    no batch, and there is no tree to summarize.  That is this refusal, the
    mirror of feature 232's ordering law: a manifest summarizes a completed
    tree, and a campaign whose tree holds no node has walked none.
    """
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="ok")

    with pytest.raises(errors.CampaignOrderError) as caught:
        finish_campaign(campaign_id, database_url=migrated_with_tree)

    message = str(caught.value)
    assert campaign_id in message
    assert "no node" in message


def test_campaign_with_no_planning_row_is_refused(migrated_with_tree: str, campaign_id: str) -> None:
    """A campaign with no planning row has no status a manifest could carry.

    The manifest carries the campaign row's calibration status; a campaign
    nobody planned has no status to carry, so the absence is refused by name.
    """
    with pytest.raises(errors.CampaignOrderError) as caught:
        finish_campaign(campaign_id, database_url=migrated_with_tree)

    message = str(caught.value)
    assert campaign_id in message
    assert "no planning row" in message


def test_missing_campaign_table_is_refused(database_url: str, campaign_id: str) -> None:
    """A database with no campaign table is refused, not surfaced as a bare SQLite error.

    The campaign table is probed first, so a database that has never been
    migrated is refused as *no campaign table* rather than surfacing SQLite's
    bare ``no such table``.  A bare ``database_url`` — no migration — is the
    state this pins; ``migrated_database`` already has the campaign table, so
    that fixture would answer "no planning row" instead.
    """
    with pytest.raises(errors.CampaignOrderError) as caught:
        finish_campaign(campaign_id, database_url=database_url)

    message = str(caught.value)
    assert "campaign" in message.lower()
    assert "table" in message.lower()


def test_missing_node_table_is_refused(migrated_database: str, campaign_id: str) -> None:
    """A campaign with a planning row but no node table has no tree to summarize.

    The node table is probed before the census runs, so a database that holds
    the campaign row but not the tree is refused as *no tree* rather than
    surfacing SQLite's bare ``no such table``.
    """
    _insert_campaign(migrated_database, campaign_id, calibration_status="ok")

    with pytest.raises(errors.CampaignOrderError) as caught:
        finish_campaign(campaign_id, database_url=migrated_database)

    message = str(caught.value)
    assert "node" in message.lower()
    assert "table" in message.lower()


def test_finish_refuses_without_a_store(campaign_id: str) -> None:
    """A termination with no store named is refused, not silently skipped.

    A termination that quietly skipped its write would leave a completed
    campaign with no manifest, invisible to feature 243's replay-pool gate and
    feature 235's plan_grid.  So a deployment that names no store is refused by
    name.
    """
    with pytest.raises(errors.CampaignPlanningError) as caught:
        finish_campaign(campaign_id, env={})

    assert "DATABASE_URL" in str(caught.value)


def test_finish_refuses_a_non_uuid(campaign_id: str, migrated_with_tree: str) -> None:
    """A campaign id that is not a UUID names no completed campaign."""
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="ok")

    with pytest.raises(errors.CampaignPlanningError):
        finish_campaign("not-a-uuid", database_url=migrated_with_tree)


# -- Feature 242: idempotence ------------------------------------------------------


def test_finish_is_idempotent_by_campaign(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """Finishing the same completed campaign twice upserts one row, not two.

    A reclaimed spot instance that re-runs the loop's last step and re-issues
    the empty selection must not leave two manifests for one campaign.
    """
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="ok")
    root = plant_root(campaign_id, depth=0, theme_root="macro")
    plant_root(campaign_id, parent_id=root, depth=1, theme_root="momentum")

    first = finish_campaign(campaign_id, database_url=migrated_with_tree)
    second = finish_campaign(campaign_id, database_url=migrated_with_tree)

    assert second.campaign_id == first.campaign_id
    assert second.node_count == first.node_count

    with closing(sqlite3.connect(_path_of(migrated_with_tree))) as connection:
        rows = connection.execute(
            f"SELECT COUNT(*) FROM {MANIFEST_TABLE} WHERE {CAMPAIGN_ID_COLUMN} = ?",
            (campaign_id,),
        ).fetchone()[0]
    assert rows == 1


def test_finish_refreshes_a_changed_manifest(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """A second finish refreshes the one row with the new tree's census.

    The upsert's ``ON CONFLICT(campaign_id) DO UPDATE`` writes the new values,
    so a re-issued termination of a grown tree refreshes rather than
    duplicates.
    """
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="ok")
    root = plant_root(campaign_id, depth=0, theme_root="macro")
    plant_root(campaign_id, parent_id=root, depth=1, theme_root="momentum")

    first = finish_campaign(campaign_id, database_url=migrated_with_tree)
    assert first.node_count == 2

    # The tree grows another refinement, and the campaign is finished again.
    plant_root(campaign_id, parent_id=root, depth=1, theme_root="regime")
    second = finish_campaign(campaign_id, database_url=migrated_with_tree)

    assert second.node_count == 3
    with closing(sqlite3.connect(_path_of(migrated_with_tree))) as connection:
        rows = connection.execute(
            f"SELECT COUNT(*) FROM {MANIFEST_TABLE} WHERE {CAMPAIGN_ID_COLUMN} = ?",
            (campaign_id,),
        ).fetchone()[0]
    assert rows == 1


# -- The store -------------------------------------------------------------------


def test_store_get_returns_none_for_unfinished_campaign(migrated_with_tree: str, campaign_id: str) -> None:
    """A store returns None for a campaign that was never finished — not an error.

    None means *the campaign has no manifest*; it does not mean the read
    failed, which is the honest answer for an id the table does not hold.
    """
    store = CampaignManifests(migrated_with_tree)
    assert store.get(campaign_id) is None


def test_store_get_refuses_none_id(migrated_with_tree: str) -> None:
    """Reading by no id names no row."""
    store = CampaignManifests(migrated_with_tree)
    with pytest.raises(errors.CampaignPlanningError):
        store.get(None)


def test_store_requires_a_url() -> None:
    """A store built with no URL is refused."""
    with pytest.raises(errors.CampaignPlanningError):
        CampaignManifests("")


def test_store_resolves_from_env(migrated_with_tree: str) -> None:
    """The store resolves ``DATABASE_URL`` from the environment, or returns None."""
    assert CampaignManifests.resolve(env={}) is None
    assert CampaignManifests.resolve(env={"DATABASE_URL": "   "}) is None
    resolved = CampaignManifests.resolve(env={"DATABASE_URL": migrated_with_tree})
    assert resolved is not None
    assert resolved.database_url == migrated_with_tree


def test_store_does_not_create_the_tree_tables(database_url: str) -> None:
    """The manifest store creates only its own table, never the campaign or node tables.

    The writer owns the table it writes; the campaign and node tables are the
    migration's, and a store that created them would be improvising a schema it
    does not own.  A bare ``database_url`` — no migration — is the state this
    pins: after the store writes a manifest, the only table present is the one
    it brought up itself.
    """
    store = CampaignManifests(database_url)
    store.record(
        CampaignManifest(
            campaign_id=str(uuid.uuid4()),
            calibration_status="ok",
            branch_count=1,
            refine_count=0,
            leaf_count=1,
            node_count=1,
            depth_max=0,
            theme_roots=1,
        )
    )
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert tables == {MANIFEST_TABLE}


def test_store_refuses_an_in_memory_url() -> None:
    """An in-memory database would die with the connection that opened it.

    A campaign manifest must outlive the termination call that produced it,
    because feature 243's replay pool and feature 235's planner open it in
    another process entirely.
    """
    with pytest.raises(errors.CampaignPlanningError):
        CampaignManifests("sqlite:///:memory:").path


def test_store_refuses_a_non_sqlite_scheme() -> None:
    """A store speaks only sqlite:///, the spec's single-machine allowance."""
    with pytest.raises(errors.CampaignPlanningError):
        CampaignManifests("postgres://localhost/db").path


# -- Feature 243: the replay pool's admission ----------------------------------------


def test_completed_campaigns_are_readable_as_a_set(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """Every completed campaign's manifest is readable — the pool's own read.

    Feature 243 judges the campaigns a caller is about to add to the replay
    pool, and feature 235's ``plan_grid`` derives the next plan from the
    campaigns that came before.  Both reason over the *set* of completed
    manifests, so the store offers it, ordered by id so two reads agree.
    """
    other = str(uuid.uuid4())
    for campaign, status in ((campaign_id, "ok"), (other, "VOID")):
        _insert_campaign(migrated_with_tree, campaign, calibration_status=status)
        root = plant_root(campaign, depth=0, theme_root="macro")
        plant_root(campaign, parent_id=root, depth=1, theme_root="momentum")
        finish_campaign(campaign, database_url=migrated_with_tree)

    store = CampaignManifests(migrated_with_tree)
    completed = store.completed()

    assert [manifest.campaign_id for manifest in completed] == sorted(
        [campaign_id, other]
    )
    assert {manifest.calibration_status for manifest in completed} == {"ok", "VOID"}


def test_completed_is_empty_before_anything_is_finished(
    migrated_with_tree: str,
) -> None:
    """A store holding no completed campaign answers an empty tuple, not an error.

    The set-shaped twin of :meth:`CampaignManifests.get`'s ``None``: a
    deployment that has finished nothing has no completed campaigns to add to
    the pool, which is a discoverable state rather than a failure.
    """
    assert CampaignManifests(migrated_with_tree).completed() == ()


def test_gate_admits_completed_campaigns_that_are_not_void(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """The pool takes the campaigns calibration did not void — feature 243's happy path.

    A completed campaign whose status is ``'ok'`` is admitted, and it is
    returned **unmodified**: this gate is a judgement about a campaign, never
    an edit of its record.
    """
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="ok")
    root = plant_root(campaign_id, depth=0, theme_root="macro")
    plant_root(campaign_id, parent_id=root, depth=1, theme_root="momentum")
    finished = finish_campaign(campaign_id, database_url=migrated_with_tree)

    admitted = admit_completed_campaigns([finished])

    assert admitted == (finished,)
    assert admitted[0].calibration_status == "ok"
    assert admitted[0].node_count == finished.node_count


def test_gate_refuses_a_voided_campaign(
    migrated_with_tree: str, campaign_id: str, plant_root
) -> None:
    """A campaign §7.4 voided is refused when the pool would take it — feature 243.

    The refusal names the campaign, carries the code the feature's sentence is
    greppable by, and names the column the offending value came from, so an
    operator reads *which campaign, and what about it* rather than a bare
    status comparison.
    """
    _insert_campaign(migrated_with_tree, campaign_id, calibration_status="VOID")
    root = plant_root(campaign_id, depth=0, theme_root="macro")
    plant_root(campaign_id, parent_id=root, depth=1, theme_root="momentum")
    voided = finish_campaign(campaign_id, database_url=migrated_with_tree)
    assert voided.calibration_status == "VOID"  # the verdict feature 242 carried

    with pytest.raises(errors.VoidCampaignError) as caught:
        admit_completed_campaigns([voided])

    message = str(caught.value)
    assert VOID_CAMPAIGN_CODE in message
    assert campaign_id in message
    assert CALIBRATION_STATUS_COLUMN in message


def test_gate_refuses_the_whole_batch_and_names_every_offender(
    migrated_with_tree: str, plant_root
) -> None:
    """One voided campaign refuses the batch entire, and every offender is named.

    Adding the good campaigns *around* a voided one would make the pool's
    membership this gate's quiet decision; refusing names the whole of what the
    batch would have poisoned, so an operator fixes all of it at once rather
    than meeting the next offender on a re-run.
    """
    good, bad_one, bad_two = (str(uuid.uuid4()) for _ in range(3))
    for campaign, status in (
        (good, "ok"),
        (bad_one, "VOID"),
        (bad_two, "VOID"),
    ):
        _insert_campaign(migrated_with_tree, campaign, calibration_status=status)
        root = plant_root(campaign, depth=0, theme_root="macro")
        plant_root(campaign, parent_id=root, depth=1, theme_root="momentum")
        finish_campaign(campaign, database_url=migrated_with_tree)

    store = CampaignManifests(migrated_with_tree)
    batch = store.completed()

    with pytest.raises(errors.VoidCampaignError) as caught:
        admit_completed_campaigns(batch)

    message = str(caught.value)
    assert bad_one in message
    assert bad_two in message
    assert good not in message
    assert VOID_CAMPAIGN_CODE in message


def test_gate_compares_the_status_exactly(campaign_id: str) -> None:
    """``'VOID'`` is the verdict's own spelling; near-misses are not it.

    Feature 124 writes ``VOID`` onto the campaign row and feature 242 carries it
    verbatim.  This gate *reads* that verdict — it does not pronounce it — so it
    compares the exact word and lets a differently-cased status through rather
    than normalising a verdict it does not own.  ``'ok'`` is the migration's
    default and the only other value the column carries.
    """
    for status in ("ok", "void", "Void", "VOID ", "voided"):
        manifest = _manifest(campaign_id, calibration_status=status)
        admitted = admit_completed_campaigns([manifest])
        assert admitted == (manifest,), status

    with pytest.raises(errors.VoidCampaignError):
        admit_completed_campaigns([_manifest(campaign_id, calibration_status="VOID")])


def test_gate_admits_a_single_manifest_and_an_empty_batch(campaign_id: str) -> None:
    """A lone campaign and an empty batch are both legitimate asks.

    The feature's subject is *a campaign*, so refusing to judge one for not
    being a batch would be a seam making the caller's problem worse; and a
    caller with no completed campaigns to add has nothing to refuse.
    """
    manifest = _manifest(campaign_id, calibration_status="ok")
    assert admit_completed_campaigns(manifest) == (manifest,)
    assert admit_completed_campaigns([]) == ()
    assert admit_completed_campaigns(iter(())) == ()


def test_gate_refuses_a_batch_that_is_not_a_batch(campaign_id: str) -> None:
    """A batch that is not a sequence of manifests names no status to judge.

    A bare string is refused rather than iterated character by character — the
    same stance :class:`~discovery.themes.ThemeSet` takes for a single string
    standing in for a set of themes — and an entry that is not a manifest is
    refused **by position**, so the caller learns which entry to fix.
    """
    with pytest.raises(errors.CampaignPlanningError) as caught:
        admit_completed_campaigns("not-a-batch")
    assert VOID_CAMPAIGN_CODE in str(caught.value)

    with pytest.raises(errors.CampaignPlanningError):
        admit_completed_campaigns(None)

    with pytest.raises(errors.CampaignPlanningError) as caught:
        admit_completed_campaigns([_manifest(campaign_id, calibration_status="ok"), "nope"])
    assert "position 1" in str(caught.value)


def test_the_void_refusal_is_its_own_class_beside_the_planning_one() -> None:
    """A void campaign's refusal is not a malformed-ask refusal — the split is the point.

    ``CampaignPlanningError`` is the member's malformed-request class, refused
    before anything is read.  Feature 243's refusal happens *after* the
    campaign rows are read and refuses a batch that is perfectly well formed,
    so folding it in would put two different repairs behind one ``except`` —
    and would make an operator grepping for a mis-sequenced campaign find the
    voided ones.  ``IllegalThemeError`` states the same rule for feature 241,
    and this pins feature 243's instance of it.

    Both are still ``DiscoveryError``, so the member's one-``except`` property
    holds for the whole orchestrator path.
    """
    assert issubclass(errors.VoidCampaignError, errors.DiscoveryError)
    assert not issubclass(errors.VoidCampaignError, errors.CampaignPlanningError)
    assert not issubclass(errors.VoidCampaignError, errors.CampaignOrderError)
    assert not issubclass(errors.CampaignPlanningError, errors.VoidCampaignError)

    # The structural refusals — a batch that is not a batch, an entry that is
    # not a manifest — are the other way round: malformed asks, refused before
    # anything is read, and they stay the planning class.
    with pytest.raises(errors.CampaignPlanningError) as caught:
        admit_completed_campaigns("not-a-batch")
    assert not isinstance(caught.value, errors.VoidCampaignError)

    with pytest.raises(errors.CampaignPlanningError) as caught:
        admit_completed_campaigns([_manifest(str(uuid.uuid4()), calibration_status="ok"), "nope"])
    assert not isinstance(caught.value, errors.VoidCampaignError)


def test_the_member_exports_feature_243s_whole_vocabulary() -> None:
    """The feature's verb, its verdict word and its code are reachable by name.

    A caller adding completed campaigns to the pool needs the gate, the value
    it refuses on and the word its refusal opens with, and all three must be
    reachable from the member rather than by reaching into a submodule — the
    discipline ``test_themes.py`` states for feature 241's surface.
    """
    import discovery as member

    for name in (
        "CALIBRATION_STATUS_OK",
        "CALIBRATION_STATUS_VOID",
        "VOID_CAMPAIGN_CODE",
        "VoidCampaignError",
        "admit_completed_campaigns",
    ):
        assert name in member.__all__, name
        assert hasattr(member, name), name

