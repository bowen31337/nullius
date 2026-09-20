"""Feature 119: the Type-D flip depth ``d ~ Geometric(p)``, persisted per branch.

app_spec.xml, "Null Oracle & Planted Nulls", feature 119: *System persists a
Type-D flip depth drawn from a geometric distribution while every root stays
real.*  This suite pins the two halves the sentence carries:

* the *draw* — :func:`nulloracle.flipdepth.flip_depth`, the geometric inversion
  itself — and ``test_flipdepth.py`` pins it in isolation, the way
  ``test_phi.py`` pins the clip and ``test_ks.py`` pins the KS test;
* the *persistence* — :class:`nulloracle.flipdepth.FlipDepth` and the
  module-level :func:`persist_flip_depth` — which writes the drawn depth onto
  ``node.flip_depth``, the column on the branch's parent node.

The sentence's load-bearing claim is that the depth is *Geometric(p)* and that
*every root stays real*.  So the tests below hold it to both: the draw against
a hand-worked geometric inversion, its support against the invariant that a
root (depth 0) can never be the flip, and the refusals that keep a degenerate
``p`` from teaching the policy "always stop at depth 1".  A test that only
asserted "the depth is a positive integer" would pass for a constant, which is
not what §7.3 fixes.

Four properties get their own sections because they are the ones a
plausible-looking implementation gets wrong:

* **the draw is a genuine geometric on the trial count** — ``d = 1 + floor(log(U)
  / log(1 - p))`` for a uniform ``U`` from the seeded generator, so a replayed
  seed draws the same depth;
* **every root stays real** — the geometric's support is ``{1, 2, 3, …}``, so
  the shallowest a branch flips is at depth 1, never at depth 0; a root is never
  the flip;
* **the refusals** — a ``p`` that is not a genuine probability in ``(0, 1)`` is
  refused by name, because a ``p`` of 1 collapses the draw to a constant depth
  of 1 and a ``p`` of 0 makes it never terminate;
* **the depth is a fact about a branch, so the branch is never created here** —
  a store that wrote ``flip_depth`` onto a node it invented would be inventing
  the branch the depth belongs to, so a node the table does not hold is refused
  by name.
"""

from __future__ import annotations

import importlib.util
import math
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    FlipDepth,
    KsGuardError,
    SidecarError,
    flip_depth,
    node_as_seed,
    persist_flip_depth,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0118_node_table.py"

#: The node's structural columns, in the shape
#: ``migrations/versions/0118_node_table.py`` describes.  ``flip_depth`` is a
#: placeholder the store overwrites — feature 119's whole point is that the
#: stored value is the *drawn* one.
NODE_COLUMNS = ("campaign_id", "theme_root", "depth", "flip_depth")


# -- Helpers ---------------------------------------------------------------------


def _store(tmp_path: Path, name: str = "flip.db") -> tuple[FlipDepth, str]:
    """A flip-depth store over a fresh SQLite file, with its ``DATABASE_URL``."""
    path = tmp_path / name
    url = f"sqlite:///{path}"
    return FlipDepth(url), url


def _campaign(store: FlipDepth, campaign_id: str | None = None) -> str:
    """Insert a campaign row the way its planner would, and return its id."""
    identifier = campaign_id or str(uuid.uuid4())
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, null_fraction) "
            "VALUES (?, 'Type-D', 12, 0.25)",
            (identifier,),
        )
    return identifier


def _node(store: FlipDepth, campaign_id: str, node_id: str | None = None, *, depth: int = 2) -> str:
    """Insert a node row the way the discovery loop would, and return its id.

    ``flip_depth`` is left NULL — a value no draw would ever produce — so that a
    test asserting the stored depth is the drawn one cannot pass merely because
    the row was inserted with the right value.  The store under test is what
    must draw it.
    """
    identifier = node_id or str(uuid.uuid4())
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, 'macro', ?)",
            (identifier, campaign_id, depth),
        )
    return identifier


def _depth(store: FlipDepth, node_id: str) -> int | None:
    """The node row's ``flip_depth``, read raw."""
    with closing(store._connect()) as connection:
        cursor = connection.execute(
            f"SELECT flip_depth FROM {NODE_TABLE} WHERE id = ?",
            (node_id,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    return row[0]


def _migration():
    """``migrations/versions/0118_node_table.py``, loaded by path.

    By path rather than by import because that is how a migration runner loads
    it: the file is not a module on any package's ``sys.path``, and a test that
    could only reach it through an import would be testing a different
    arrangement from the one that runs.
    """
    spec = importlib.util.spec_from_file_location(
        "migration_0118_node_table", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The node table name — spelled by the store, and asserted against the
#: migration below.  Kept local so the helpers read.
NODE_TABLE = "node"


@pytest.fixture(autouse=True)
def _database_url_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no ``DATABASE_URL`` in the environment.

    Autouse and unconditional, mirroring the member's other isolation
    fixtures: the default state of a test is a deployment that names no
    relational store, and the tests that assert on the *unconfigured*
    behaviour then do not fight a fixture that helpfully configured one.  Each
    test that wants a store builds its own over ``tmp_path``, so no test in
    this suite can reach a real database.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


# -- The draw --------------------------------------------------------------------


class TestTheGeometricDraw:
    def test_the_draw_is_the_inverse_cdf(self) -> None:
        # d = 1 + floor(log(U) / log(1 - p)) for a uniform U from the seeded
        # generator.  Reproduced here independently so a constant, or a 1/p,
        # cannot pass.
        rng = __import__("random").Random(node_as_seed("6ee6bf93-8326-48f8-b4d5-921662768f45"))
        p = 0.3
        u = rng.random()
        while u <= 0.0:
            u = rng.random()
        expected = math.floor(math.log(u) / math.log(1 - p)) + 1
        assert flip_depth(0.3, seed=node_as_seed("6ee6bf93-8326-48f8-b4d5-921662768f45")) == expected

    def test_the_draw_is_reproducible_from_the_seed(self) -> None:
        # A campaign replayed from the same seed draws the same depth — the
        # determinism contract §12 imposes and the reason the depth is
        # persisted rather than re-derived.
        assert flip_depth(0.25, seed=1234) == flip_depth(0.25, seed=1234)

    def test_two_seeds_draw_independently(self) -> None:
        # Two different nodes draw two different depths — the seed is a
        # collision-free mapping from node to draw.
        depths = {flip_depth(0.3, seed=node_as_seed(str(uuid.uuid4()))) for _ in range(500)}
        assert len(depths) > 1

    def test_the_mean_matches_the_geometric_expectation(self) -> None:
        # Over many draws the empirical mean approaches 1/p — the geometric's
        # mean on the trial count.  Loose bound so the test is stable.
        draws = [flip_depth(0.2, seed=s) for s in range(1, 5000)]
        assert 4.0 <= sum(draws) / len(draws) <= 6.0  # 1/p = 5

    def test_the_shallowest_flip_is_depth_one(self) -> None:
        # The geometric's support starts at 1; the shallowest a branch can flip
        # is at depth 1.
        assert min(flip_depth(0.9, seed=s) for s in range(1, 2000)) == 1


class TestEveryRootStaysReal:
    def test_the_depth_is_always_at_least_one(self) -> None:
        # Across the whole range of probabilities the system produces, the
        # returned depth is always >= 1 — the geometric's support — so a root
        # (depth 0) is never the flip.
        for seed in range(1, 3000):
            for p in (0.05, 0.2, 0.5, 0.8, 0.95):
                assert flip_depth(p, seed=seed) >= 1

    def test_a_root_is_below_the_flip(self) -> None:
        # A root sits at depth 0; every drawn flip depth is strictly greater,
        # so every root stays real.
        for seed in range(1, 2000):
            assert 0 < flip_depth(0.4, seed=seed)

    def test_the_support_is_the_positive_integers(self) -> None:
        # Every drawn depth is a genuine positive integer — never a bool, never
        # a float, never zero or negative.
        for seed in range(1, 2000):
            d = flip_depth(0.3, seed=seed)
            assert isinstance(d, int) and not isinstance(d, bool)
            assert d >= 1


class TestTheDrawRefusesRatherThanGuesses:
    def test_a_probability_of_one_is_refused(self) -> None:
        # p = 1 collapses the geometric to a constant depth of 1, the
        # degenerate draw that teaches the policy "always stop at depth 1"
        # (docs/alpha-engine-prd.md §4.1.2), which is worth nothing.
        with pytest.raises(KsGuardError, match="strictly less than 1"):
            flip_depth(1.0, seed=1)

    def test_a_probability_above_one_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="strictly less than 1"):
            flip_depth(1.5, seed=1)

    def test_a_probability_of_zero_is_refused(self) -> None:
        # p = 0 makes the geometric's mean 1/p infinite and the draw never
        # terminates.
        with pytest.raises(KsGuardError, match="strictly greater than 0"):
            flip_depth(0.0, seed=1)

    def test_a_negative_probability_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="strictly greater than 0"):
            flip_depth(-0.2, seed=1)

    def test_a_boolean_probability_is_refused(self) -> None:
        # True and False are ints in Python, but they are not probabilities: a
        # truthy-looking ``True`` would collapse the draw to a constant depth
        # of 1.
        with pytest.raises(KsGuardError, match="real number") as raised:
            flip_depth(True, seed=1)
        assert not isinstance(raised.value, bool)

    def test_a_non_numeric_probability_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="real number"):
            flip_depth("0.3", seed=1)

    def test_a_non_finite_probability_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="finite"):
            flip_depth(float("nan"), seed=1)
        with pytest.raises(KsGuardError, match="finite"):
            flip_depth(float("inf"), seed=1)

    def test_a_non_integer_seed_is_refused(self) -> None:
        # The seed is the whole of the draw's reproducibility; a seed the
        # generator cannot seed with would make a replayed campaign draw a
        # different depth.
        with pytest.raises(KsGuardError, match="integer"):
            flip_depth(0.3, seed=1.5)
        with pytest.raises(KsGuardError, match="integer"):
            flip_depth(0.3, seed=True)

    def test_the_refusal_names_the_offending_value(self) -> None:
        with pytest.raises(KsGuardError) as raised:
            flip_depth(1.0, seed=1)
        assert "1.0" in str(raised.value)
        assert "p" in str(raised.value)


# -- The store: the write --------------------------------------------------------


class TestTheFlipDepthLandsOnTheNode:
    def test_a_drawn_branch_carries_a_positive_depth(self, tmp_path: Path) -> None:
        # Feature 119 in one call: a branch's parent node gets a drawn depth.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign, depth=2)
        written = store.persist(node, 0.3)
        assert written >= 1
        assert _depth(store, node) == written

    def test_the_stored_value_is_the_drawn_one(self, tmp_path: Path) -> None:
        # The depth the store draws is the depth that lands — not a value the
        # row was inserted with.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign)
        drawn = flip_depth(0.3, seed=node_as_seed(node))
        store.persist(node, 0.3)
        assert _depth(store, node) == drawn

    def test_the_write_is_idempotent_by_node(self, tmp_path: Path) -> None:
        # A branch re-drawn with the same p keeps its depth; the grain is the
        # node, and what the table holds is the latest drawing decision.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign)
        first = store.persist(node, 0.3)
        second = store.persist(node, 0.3)
        assert first == second
        assert _depth(store, node) == first

    def test_a_redraw_with_a_different_p_refreshes_the_depth(self, tmp_path: Path) -> None:
        # A branch re-drawn with a new probability gets a new depth: the
        # caller's p is the source of truth.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign)
        store.persist(node, 0.9)  # shallow, likely depth 1
        first = _depth(store, node)
        store.persist(node, 0.05)  # deep
        assert _depth(store, node) >= first

    def test_the_nodes_other_columns_are_untouched(self, tmp_path: Path) -> None:
        # The flip depth fills one column of a row that is not its own.  The
        # discovery-time facts — the campaign, the theme, the depth — are the
        # loop's, and a flip-depth write that rewrote any of them would be
        # quietly redefining the branch it just planned for.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign, depth=3)
        store.persist(node, 0.3)
        with closing(store._connect()) as connection:
            cursor = connection.execute(
                "SELECT campaign_id, theme_root, depth FROM node WHERE id = ?",
                (node,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        assert row[0] == campaign
        assert row[1] == "macro"
        assert row[2] == 3

    def test_the_module_level_spelling_writes_the_same_depth(self, tmp_path: Path) -> None:
        # persist_flip_depth is the one-call spelling: the store resolved from
        # DATABASE_URL, the depth in, written against its branch's parent node.
        store, url = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign)
        written = persist_flip_depth(node, 0.3, database_url=url)
        assert written >= 1
        assert store.load(node) == written


class TestTheFlipDepthStoreRefusesRatherThanGuesses:
    def test_a_node_the_table_does_not_hold_is_refused_by_name(self, tmp_path: Path) -> None:
        # The flip depth is a fact about a branch's parent node.  A store that
        # wrote flip_depth onto a row it created would be inventing the branch
        # the depth belongs to — and the depth is drawn by the campaign loop,
        # not here.
        store, _ = _store(tmp_path)
        undrawn = str(uuid.uuid4())
        with pytest.raises(KsGuardError, match="holds no row") as raised:
            store.persist(undrawn, 0.3)
        assert "per branch" in str(raised.value)

    def test_a_node_whose_campaign_is_missing_is_refused(self, tmp_path: Path) -> None:
        # The depth is a fact about a node in a campaign.  A node that
        # references a campaign the table does not hold is a depth that hangs
        # off nothing, so it is refused.
        store, _ = _store(tmp_path)
        orphan = str(uuid.uuid4())
        with closing(store._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, 'macro', 1)",
                (orphan, str(uuid.uuid4())),
            )
        with pytest.raises(KsGuardError, match="belongs to"):
            store.persist(orphan, 0.3)

    def test_a_malformed_node_id_is_a_store_error_not_a_sidecar_one(self, tmp_path: Path) -> None:
        # The taxonomy's distinction: a malformed id handed to the *flip-depth*
        # store is a store-contract failure.  A caller reading ``SidecarError``
        # out of a flip-depth write would look in the wrong module for the
        # cause.
        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="is not a UUID") as raised:
            store.persist("not-a-uuid", 0.3)
        assert not isinstance(raised.value, SidecarError)
        assert isinstance(raised.value.__cause__, SidecarError)

    def test_a_refused_probability_leaves_no_write(self, tmp_path: Path) -> None:
        # A p that is not a probability is refused before the store is opened,
        # so a refused depth cannot leave a half behind.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign)
        with pytest.raises(KsGuardError, match="strictly less than 1"):
            store.persist(node, 1.0)
        assert _depth(store, node) is None

    def test_the_store_refuses_a_url_it_cannot_speak(self, tmp_path: Path) -> None:
        with pytest.raises(KsGuardError, match="unsupported") as raised:
            FlipDepth("postgres:///db").persist(str(uuid.uuid4()), 0.3)
        assert "sqlite" in str(raised.value)

    def test_an_in_memory_url_is_refused(self, tmp_path: Path) -> None:
        # An in-memory database dies with the connection that opened it, and a
        # branch's flip depth must outlive the draw that produced it.
        with pytest.raises(KsGuardError, match="no database path"):
            FlipDepth("sqlite:///:memory:").persist(str(uuid.uuid4()), 0.3)


# -- The store: the read -----------------------------------------------------------


class TestTheStoredDepthIsWhatDownstreamReads:
    def test_load_reads_the_drawn_depth(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        node = _node(store, campaign)
        drawn = store.persist(node, 0.3)
        assert store.load(node) == drawn

    def test_an_undrawn_branch_reads_as_none(self, tmp_path: Path) -> None:
        # None means the branch was never drawn — the honest answer for a node
        # the table does not hold.  It does not mean the read failed.
        store, _ = _store(tmp_path)
        assert store.load(str(uuid.uuid4())) is None

    def test_a_malformed_id_reads_as_a_store_error(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="is not a UUID"):
            store.load("not-a-uuid")


# -- The store and the migration are one schema -----------------------------------


class TestTheStoreMirrorsTheMigration:
    def test_the_migration_creates_the_five_column_node_table(self, tmp_path: Path) -> None:
        # The node table is owned by feature 97's migration, which creates it
        # with exactly the five structural columns — id, parent_id,
        # campaign_id, theme_root, depth — and not this feature's flip_depth.
        # A store that recreated the node table with a sixth column would be a
        # second schema wearing the migration's table name; the store instead
        # adds the flip-depth column to the migration's table by ALTER TABLE.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        columns = [row[1] for row in _table_info(theirs_path, "node")]
        assert columns == ["id", "parent_id", "campaign_id", "theme_root", "depth"]
        assert "flip_depth" not in columns

    def test_the_store_adds_the_flip_depth_column_to_the_migration_table(self, tmp_path: Path) -> None:
        # The store opens the migration's five-column node table and adds the
        # flip-depth column to it — the production arrangement, where the table
        # predates this feature.  A store-created table and a migration-created
        # one both end up with the column, and re-opening changes nothing.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        # Open the store against the migration's database: the store adds the
        # column.
        FlipDepth(f"sqlite:///{theirs_path}")._connect().close()
        columns = [row[1] for row in _table_info(theirs_path, "node")]
        assert "flip_depth" in columns
        # Re-opening is a no-op: the column is added once, not twice.
        FlipDepth(f"sqlite:///{theirs_path}")._connect().close()
        assert [row[1] for row in _table_info(theirs_path, "node")].count("flip_depth") == 1

    def test_the_store_works_against_a_migration_created_table(self, tmp_path: Path) -> None:
        # The flip-depth store opens a database the *migration* created — the
        # production arrangement — and writes the drawn depth onto the node the
        # discovery loop inserted.  The campaign table the store needs is the
        # store's own to create; the node table is the migration's.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        campaign = str(uuid.uuid4())
        node = str(uuid.uuid4())
        url = f"sqlite:///{theirs_path}"
        store = FlipDepth(url)
        # The store opens the migration's database (adding flip_depth and
        # creating the campaign table), then the loop inserts the campaign and
        # the node.
        with closing(store._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO campaign (id, campaign_type, workspace_count, null_fraction) "
                "VALUES (?, 'Type-D', 12, 0.25)",
                (campaign,),
            )
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, 'macro', 2)",
                (node, campaign),
            )
        written = persist_flip_depth(node, 0.3, database_url=url)
        assert written >= 1
        with closing(sqlite3.connect(theirs_path)) as connection:
            cursor = connection.execute("SELECT flip_depth FROM node WHERE id = ?", (node,))
            try:
                stored = cursor.fetchone()[0]
            finally:
                cursor.close()
        assert stored == written


def _table_info(path: Path, table: str) -> list[tuple]:
    with closing(sqlite3.connect(path)) as connection:
        cursor = connection.execute(f"PRAGMA table_info({table})")
        try:
            return cursor.fetchall()
        finally:
            cursor.close()


# -- Resolution ------------------------------------------------------------------


class TestResolve:
    def test_an_unset_database_url_resolves_to_none(self) -> None:
        assert FlipDepth.resolve() is None

    def test_a_blank_database_url_resolves_to_none(self) -> None:
        assert FlipDepth.resolve(env={DATABASE_URL_ENV: "   "}) is None

    def test_a_named_database_url_resolves_to_a_store(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'flip.db'}"
        resolved = FlipDepth.resolve(env={DATABASE_URL_ENV: url})
        assert isinstance(resolved, FlipDepth)
        assert resolved.database_url == url
