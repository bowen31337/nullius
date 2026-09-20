"""Feature 118: the Type-R root selection — drawn without replacement, inherited by the subtree.

app_spec.xml, "Null Oracle & Planted Nulls", feature 118: *System persists
Type-R null status drawn without replacement across roots, inherited by the
whole subtree.*  This suite pins the three claims the sentence carries, plus
the one thing §7.3's ``replace=False`` makes easy to get silently wrong:

* **the draw** — :func:`nulloracle.selection.draw_null_roots`, §7.3's
  ``rng.choice(roots, size=round(phi * W), replace=False)`` — pinned in
  isolation the way ``test_phi.py`` pins the clip and ``test_flipdepth.py``
  pins the geometric;
* **without replacement** — the drawn roots are **distinct**, and the count is
  ``round(φ·W)`` exactly.  A draw *with* replacement looks identical from the
  outside — a list of roots, each of them a root — and is wrong in the one way
  nothing downstream can see: every collision is a well that should have been
  null and stayed real, so the campaign plants fewer nulls than its fraction
  states and its Type-A rate is measured against a smaller planted set than
  the world was designed with.  A test that only asserted "the draw returns
  ``round(φ·W)`` roots" would pass for ``choices``, which is why the
  distinctness section exists;
* **persistence** — :class:`nulloracle.selection.TypeRSelection` lands the
  status in §7.1's **sealed sidecar** and nowhere else, one entry per root, and
  the campaign's φ and ``W`` are read from the campaign's own row rather than
  taken from a caller;
* **inheritance** — :meth:`nulloracle.selection.TypeRSelection.null_status`
  answers a *descendant*'s status from its root's, which is the half of the
  sentence the draw alone does not deliver.

Four properties get their own sections because they are the ones a
plausible-looking implementation gets wrong:

* the draw is ``round(φ·W)`` distinct roots, reproducible from the campaign's
  own seed and independent of the order the rows came back in;
* every root is recorded — the drawn ones *and* the ones left real — so
  "drawn, and nothing was null" stays distinguishable from "never drawn";
* the bit lands in the sidecar and in no plaintext artifact of the tree store
  (feature 110's rule, asserted from this feature's side);
* a Type-D campaign is refused by name, because §7.3 keeps the two regimes'
  null-ness in different places and a root selection drawn onto a Type-D tree
  would be a bit no read path serves.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import random
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    CAMPAIGN_TYPE_COLUMN,
    DATABASE_URL_ENV,
    NODE_TABLE,
    NULL_FRACTION_COLUMN,
    TYPE_R_CAMPAIGN_TYPE,
    WORKSPACE_COUNT_COLUMN,
    KsGuardError,
    NullAssignment,
    NullSidecar,
    RootSelection,
    SidecarDecryptionError,
    SidecarError,
    SidecarStoreError,
    TypeRSelection,
    campaign_as_seed,
    draw_null_roots,
    null_root_count,
    perm_seed_for,
    persist_type_r_selection,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0118_node_table.py"

#: The 32-byte test key, the same constant the member's conftest uses.
TEST_KEY_HEX = "0f" * 32

#: A campaign id that is a canonical UUID, so a test about the *seam* is never
#: accidentally about id validation.
CAMPAIGN = "7c2e1a40-0000-4000-8000-000000000118"


# -- Helpers ---------------------------------------------------------------------


def _store(
    tmp_path: Path, sidecar: NullSidecar, name: str = "selection.db"
) -> tuple[TypeRSelection, str]:
    """A selection store over a fresh SQLite file and the sidecar it seals into."""
    path = tmp_path / name
    url = f"sqlite:///{path}"
    return TypeRSelection(url, sidecar), url


def _campaign(
    store: TypeRSelection,
    campaign_id: str | None = None,
    *,
    campaign_type: str = TYPE_R_CAMPAIGN_TYPE,
    workspace_count: int = 12,
    null_fraction: float = 0.1667,
) -> str:
    """Insert a campaign row the way its planner would, and return its id.

    The three ``NOT NULL`` planning-time columns plus the type — the shape
    ``migrations/versions/0111_campaign_table.py`` describes a campaign as being
    planned with.  This suite inserts the row itself rather than expecting the
    store to, because a campaign is written by its planner *before any node is
    expanded*: the store reads a campaign, it does not invent one.
    """
    identifier = campaign_id or str(uuid.uuid4())
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, {CAMPAIGN_TYPE_COLUMN}, "
            f"{WORKSPACE_COUNT_COLUMN}, {NULL_FRACTION_COLUMN}) VALUES (?, ?, ?, ?)",
            (identifier, campaign_type, workspace_count, null_fraction),
        )
    return identifier


def _node(
    store: TypeRSelection,
    campaign_id: str,
    node_id: str | None = None,
    *,
    parent_id: str | None = None,
    depth: int = 0,
    theme_root: str = "macro",
) -> str:
    """Insert a node row the way the discovery loop would, and return its id.

    ``parent_id`` defaults to ``None``, which is what makes the row a *root*:
    ``migrations/versions/0118_node_table.py`` — *"A root node carries ``NULL``;
    every other node names its parent."*
    """
    identifier = node_id or str(uuid.uuid4())
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            (identifier, parent_id, campaign_id, theme_root, depth),
        )
    return identifier


def _wells(store: TypeRSelection, campaign: str, count: int) -> list[str]:
    """``count`` roots for ``campaign``, inserted the way the loop would."""
    return [_node(store, campaign) for _ in range(count)]


def _sidecar(tmp_path: Path, name: str = "z0/null/sidecar.enc") -> NullSidecar:
    """A sidecar at a path under this test's tmpdir, sealed with the test key."""
    from nulloracle import SidecarKey

    return NullSidecar(tmp_path / name, SidecarKey.from_hex(TEST_KEY_HEX))


def _migration():
    """``migrations/versions/0118_node_table.py``, loaded by path.

    By path rather than by import because that is how a migration runner loads
    it: the file is not a module on any package's ``sys.path``, and a test that
    could only reach it through an import would be testing a different
    arrangement from the one that runs.
    """
    spec = importlib.util.spec_from_file_location(
        "migration_0118_node_table_for_selection", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _database_url_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no ``DATABASE_URL`` in the environment.

    Autouse and unconditional, mirroring the member's other isolation fixtures:
    the default state of a test is a deployment that names no relational store,
    and the tests that assert on the *unconfigured* behaviour then do not fight
    a fixture that helpfully configured one.  Each test that wants a store
    builds its own over ``tmp_path``, so no test in this suite can reach a real
    database.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


@pytest.fixture
def node_ids() -> callable:
    """A factory for ``n`` distinct canonical node UUIDs."""

    def _make(count: int) -> list[str]:
        return [str(uuid.uuid4()) for _ in range(count)]

    return _make


# -- The draw --------------------------------------------------------------------


class TestTheDrawIsWithoutReplacement:
    def test_the_draw_returns_round_phi_w_roots(self) -> None:
        # §7.3: size=round(phi * W).  W = 12, phi = 0.1667 -> round(2.0004) = 2.
        roots = [str(uuid.uuid4()) for _ in range(12)]
        drawn = draw_null_roots(roots, 0.1667, workspace_count=12, seed=7)
        assert len(drawn) == 2
        assert null_root_count(0.1667, workspace_count=12) == 2

    def test_the_drawn_roots_are_distinct(self) -> None:
        # The load-bearing word of the sentence.  A draw *with* replacement
        # returns a list of roots too, and every collision is a well that
        # should have been null and stayed real — so distinctness is asserted
        # by identity of the returned collection, not by its length.
        roots = [str(uuid.uuid4()) for _ in range(6)]
        drawn = draw_null_roots(roots, 0.35, workspace_count=6, seed=11)
        assert len(drawn) == 2
        assert len(set(drawn)) == len(drawn)

    def test_no_draw_ever_repeats_a_root(self) -> None:
        # The claim over many seeds: a sample that could collide would collide
        # somewhere in this many draws of a tight well set.
        roots = [str(uuid.uuid4()) for _ in range(4)]
        for seed in range(500):
            drawn = draw_null_roots(roots, 0.5, workspace_count=4, seed=seed)
            assert len(set(drawn)) == len(drawn) == 2

    def test_the_draw_matches_the_seeded_sample(self) -> None:
        # The draw is random.Random(seed).sample over the sorted wells, so it
        # is reproducible by a reader who knows only the campaign.  Reproduced
        # here independently, so a "pick the first N" cannot pass.
        roots = sorted(str(uuid.uuid4()) for _ in range(8))
        expected = sorted(random.Random(99).sample(roots, 2))
        assert list(draw_null_roots(roots, 0.25, workspace_count=8, seed=99)) == expected

    def test_the_draw_is_reproducible_from_the_seed(self) -> None:
        # §12's determinism contract: the same campaign draws the same world.
        roots = [str(uuid.uuid4()) for _ in range(12)]
        first = draw_null_roots(roots, 0.1667, workspace_count=12, seed=1234)
        second = draw_null_roots(roots, 0.1667, workspace_count=12, seed=1234)
        assert first == second

    def test_the_draw_does_not_depend_on_the_row_order(self) -> None:
        # Feature 138's rule: an explicit sort before every reduction, because
        # an iteration order that varies with the storage engine is
        # non-determinism wearing a stable-looking result.
        roots = [str(uuid.uuid4()) for _ in range(12)]
        assert draw_null_roots(roots, 0.1667, workspace_count=12, seed=5) == (
            draw_null_roots(list(reversed(roots)), 0.1667, workspace_count=12, seed=5)
        )

    def test_two_seeds_draw_different_worlds(self) -> None:
        # The seed is the campaign's, so two campaigns plant different wells —
        # otherwise every campaign in the pool is one world re-labelled.
        roots = [str(uuid.uuid4()) for _ in range(12)]
        draws = {
            draw_null_roots(roots, 0.1667, workspace_count=12, seed=campaign_as_seed(str(uuid.uuid4())))
            for _ in range(50)
        }
        assert len(draws) > 1

    def test_every_unselected_root_stays_real(self) -> None:
        # §7.3's invariant from the draw's side: the complement of the draw is
        # the campaign's remaining wells, and it is empty of nulls.
        roots = [str(uuid.uuid4()) for _ in range(12)]
        drawn = set(draw_null_roots(roots, 0.1667, workspace_count=12, seed=3))
        assert set(roots) - drawn
        assert drawn <= set(roots)


class TestTheDrawRefusesRatherThanGuesses:
    def test_a_count_larger_than_the_tree_is_refused(self) -> None:
        # Without replacement cannot draw more distinct roots than exist.
        roots = [str(uuid.uuid4()) for _ in range(3)]
        with pytest.raises(KsGuardError, match="without replacement"):
            draw_null_roots(roots, 0.9, workspace_count=12, seed=1)

    def test_an_empty_tree_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="holds no roots"):
            draw_null_roots([], 0.2, workspace_count=12, seed=1)

    def test_a_duplicated_root_is_refused(self) -> None:
        # "Without replacement" is a statement about a set of *distinct* wells;
        # a well list with a well in it twice is not one.
        root = str(uuid.uuid4())
        with pytest.raises(KsGuardError, match="duplicate"):
            draw_null_roots([root, root], 0.5, workspace_count=2, seed=1)

    def test_a_root_that_is_not_a_uuid_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="not a UUID"):
            draw_null_roots(["not-a-uuid"], 0.5, workspace_count=2, seed=1)

    def test_a_seed_that_is_not_an_integer_is_refused(self) -> None:
        roots = [str(uuid.uuid4()) for _ in range(4)]
        with pytest.raises(KsGuardError, match="seed must be an integer"):
            draw_null_roots(roots, 0.5, workspace_count=4, seed=True)

    def test_a_fraction_that_is_not_a_fraction_is_refused(self) -> None:
        roots = [str(uuid.uuid4()) for _ in range(4)]
        for bad in (True, "0.2", 0.0, -0.5, 1.5, float("nan")):
            with pytest.raises(KsGuardError):
                draw_null_roots(roots, bad, workspace_count=4, seed=1)

    def test_a_fraction_of_exactly_one_is_allowed(self) -> None:
        # φ = 1 is "every well is a null", which is an extreme but a real
        # fraction: it plants W nulls and no real ones.  Only values outside
        # (0, 1] are not fractions.
        roots = [str(uuid.uuid4()) for _ in range(3)]
        assert len(draw_null_roots(roots, 1.0, workspace_count=3, seed=1)) == 3

    def test_a_fraction_that_rounds_to_no_nulls_is_refused(self) -> None:
        # §7.3's own floor argument: a tree needs >=2 null and >=2 real roots
        # to contribute to both sensitivity and specificity.  A draw of zero
        # contributes no sensitivity at all.
        with pytest.raises(KsGuardError, match="contributes no sensitivity"):
            null_root_count(0.02, workspace_count=12)

    def test_a_workspace_count_that_is_not_a_count_is_refused(self) -> None:
        for bad in (True, 2.5, "12", 0, -3):
            with pytest.raises(KsGuardError):
                null_root_count(0.2, workspace_count=bad)


class TestTheRoundingIsHalfToEven:
    def test_a_tie_rounds_to_even(self) -> None:
        # §7.3's round(phi * W) is *reproduced*, not reinterpreted: Python's
        # round is half-to-even, the same convention numpy's own rounding uses.
        # 0.25 * 10 = 2.5 -> 2 (not 3), and 0.35 * 10 = 3.5 -> 4.
        assert null_root_count(0.25, workspace_count=10) == 2
        assert null_root_count(0.35, workspace_count=10) == 4

    def test_a_non_tie_rounds_to_nearest(self) -> None:
        assert null_root_count(0.1667, workspace_count=12) == 2
        assert null_root_count(0.3, workspace_count=10) == 3


# -- The permutation seed --------------------------------------------------------


class TestThePermSeedIsDerivedAndStable:
    def test_two_roots_get_two_seeds(self, node_ids) -> None:
        campaign, first, second = node_ids(3)
        assert perm_seed_for(campaign, first) != perm_seed_for(campaign, second)

    def test_two_campaigns_get_two_seeds(self, node_ids) -> None:
        campaign_a, campaign_b, node = node_ids(3)
        assert perm_seed_for(campaign_a, node) != perm_seed_for(campaign_b, node)

    def test_the_seed_is_stable_across_calls(self, node_ids) -> None:
        # §12: the seed is a fact of the campaign, not of the call.
        campaign, node = node_ids(2)
        assert perm_seed_for(campaign, node) == perm_seed_for(campaign, node)

    def test_the_seed_is_a_non_negative_int_below_two_to_the_63(self, node_ids) -> None:
        # §7.1's schema fixes perm_seed as a non-negative int, and 63 bits
        # keeps the value inside the signed 64-bit range a relational store
        # can hold if the seed is ever mirrored beside the bit.
        campaign, node = node_ids(2)
        seed = perm_seed_for(campaign, node)
        assert isinstance(seed, int) and not isinstance(seed, bool)
        assert 0 <= seed < 2**63

    def test_the_seed_is_not_the_process_hash(self, node_ids) -> None:
        # sha256, not hash() — which is salted per process (feature 138 pins
        # PYTHONHASHSEED for exactly this class of reason).  The expected
        # value is computed here from the same digest, independently of the
        # implementation's own call.
        import hashlib

        campaign, node = node_ids(2)
        expected = int.from_bytes(
            hashlib.sha256(f"{campaign}\x00{node}".encode()).digest()[:8], "big"
        ) >> 1
        assert perm_seed_for(campaign, node) == expected

    def test_a_malformed_id_is_refused(self, node_ids) -> None:
        campaign, _ = node_ids(2)
        with pytest.raises(KsGuardError, match="not a UUID"):
            perm_seed_for(campaign, "nope")


# -- The record ------------------------------------------------------------------


class TestTheRootSelectionRecord:
    def test_a_coherent_selection_constructs(self, node_ids) -> None:
        campaign, *roots = node_ids(4)
        selection = RootSelection(
            campaign_id=campaign,
            null_roots=tuple(roots[:2]),
            real_roots=tuple(roots[2:]),
            null_fraction=0.5,
            workspace_count=4,
        )
        assert selection.roots == tuple(sorted(roots))
        assert selection.is_null_root(roots[0]) is True
        assert selection.is_null_root(roots[2]) is False

    def test_an_overlapping_selection_is_refused(self, node_ids) -> None:
        # §7.3's draw is without replacement, so the drawn and the unselected
        # roots are two disjoint sets of wells.
        campaign, *roots = node_ids(3)
        with pytest.raises(KsGuardError, match="both null and real"):
            RootSelection(
                campaign_id=campaign,
                null_roots=(roots[0],),
                real_roots=(roots[0], roots[1]),
                null_fraction=0.25,
                workspace_count=4,
            )

    def test_a_selection_that_draws_no_null_root_is_refused(self, node_ids) -> None:
        campaign, *roots = node_ids(3)
        with pytest.raises(KsGuardError, match="at least one null root"):
            RootSelection(
                campaign_id=campaign,
                null_roots=(),
                real_roots=tuple(roots),
                null_fraction=0.25,
                workspace_count=4,
            )

    def test_a_selection_disagreeing_with_its_fraction_is_refused(self, node_ids) -> None:
        # The check that keeps a selection *checkable*: a world whose planted
        # count disagrees with its stated fraction is a calibration number
        # computed over a design that was never applied.
        campaign, *roots = node_ids(4)
        with pytest.raises(KsGuardError, match="was never applied"):
            RootSelection(
                campaign_id=campaign,
                null_roots=(roots[0],),
                real_roots=tuple(roots[1:]),
                null_fraction=0.5,  # round(0.5 * 4) = 2, not 1
                workspace_count=4,
            )

    def test_a_node_that_is_not_a_root_is_refused_rather_than_answered_false(
        self, node_ids
    ) -> None:
        # False means "drawn, and left real".  A node outside the selection is
        # a node this campaign never planted, which is a different fact.
        campaign, *roots = node_ids(3)
        selection = RootSelection(
            campaign_id=campaign,
            null_roots=(roots[0],),
            real_roots=(roots[1],),
            null_fraction=0.5,
            workspace_count=2,
        )
        stranger = str(uuid.uuid4())
        with pytest.raises(KsGuardError, match="not a root"):
            selection.is_null_root(stranger)

    def test_the_record_is_frozen(self, node_ids) -> None:
        campaign, *roots = node_ids(3)
        selection = RootSelection(
            campaign_id=campaign,
            null_roots=(roots[0],),
            real_roots=(roots[1],),
            null_fraction=0.5,
            workspace_count=2,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            selection.null_fraction = 0.9  # type: ignore[misc]

    def test_the_payload_names_the_records_own_fields(self, node_ids) -> None:
        campaign, *roots = node_ids(3)
        selection = RootSelection(
            campaign_id=campaign,
            null_roots=(roots[0],),
            real_roots=(roots[1],),
            null_fraction=0.5,
            workspace_count=2,
        )
        payload = selection.to_payload()
        assert set(payload) == {
            "campaign_id",
            "null_roots",
            "real_roots",
            "null_fraction",
            "workspace_count",
        }


# -- The store: the write --------------------------------------------------------


class TestTheSelectionLandsInTheSidecar:
    def test_a_campaigns_selection_is_drawn_and_sealed(self, tmp_path: Path) -> None:
        # Feature 118 in one call: 12 wells, φ = 0.1667 -> 2 null roots, every
        # root sealed.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        selection = store.persist(campaign)
        assert len(selection.null_roots) == 2
        assert len(selection.real_roots) == 10
        assert sidecar.path.exists()

    def test_every_root_is_recorded_not_only_the_null_ones(self, tmp_path: Path) -> None:
        # With all roots present the file itself says the selection *happened*,
        # so "drawn, and nothing was null" stays distinguishable from "never
        # drawn" without holding φ or W.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        roots = _wells(store, campaign, 12)
        store.persist(campaign)
        held = sidecar.open()
        assert set(held) == set(roots)
        assert sum(1 for entry in held.values() if entry.is_null) == 2

    def test_the_sealed_bit_is_the_drawn_one(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        selection = store.persist(campaign)
        held = sidecar.open()
        for root in selection.null_roots:
            assert held[root].is_null is True
        for root in selection.real_roots:
            assert held[root].is_null is False

    def test_the_sealed_perm_seed_is_the_derived_one(self, tmp_path: Path) -> None:
        # §7.1 seals the seed *beside* the bit, and feature 115 reproduces the
        # permutation from it — so the stored seed is the derived one, not a
        # value the draw happened to leave behind.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        roots = _wells(store, campaign, 12)
        store.persist(campaign)
        held = sidecar.open()
        for root in roots:
            assert held[root].perm_seed == perm_seed_for(campaign, root)
        assert len({held[root].perm_seed for root in roots}) == len(roots)

    def test_the_sealed_block_length_is_the_schema_default(self, tmp_path: Path) -> None:
        # §7.1's 20 days, applied by NullAssignment rather than restated here.
        from nulloracle import DEFAULT_BLOCK_DAYS

        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        store.persist(campaign)
        assert {entry.block_days for entry in sidecar.open().values()} == {
            DEFAULT_BLOCK_DAYS
        }

    def test_the_write_is_reproducible_from_the_campaign(self, tmp_path: Path) -> None:
        # §12: a campaign replayed next year plants the same wells.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        first = store.persist(campaign)
        second = store.persist(campaign)
        assert first.null_roots == second.null_roots

    def test_a_redraw_with_a_new_workspace_count_refreshes_the_selection(
        self, tmp_path: Path
    ) -> None:
        # A campaign re-planned with a new W is the exact thing a refreshed
        # selection records: the campaign's own row is the source of truth.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store, workspace_count=12, null_fraction=0.1667)
        _wells(store, campaign, 12)
        first = store.persist(campaign)
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET {WORKSPACE_COUNT_COLUMN} = ?, "
                f"{NULL_FRACTION_COLUMN} = ? WHERE id = ?",
                (24, 0.15, campaign),
            )
        second = store.persist(campaign)
        assert len(first.null_roots) == 2
        assert len(second.null_roots) == round(0.15 * 24)

    def test_another_campaigns_entries_are_preserved(self, tmp_path: Path) -> None:
        # §7.1's file holds one map for the deployment, so a campaign's write
        # must not drop every other campaign's roots.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        first_campaign = _campaign(store)
        second_campaign = _campaign(store)
        first_roots = _wells(store, first_campaign, 12)
        second_roots = _wells(store, second_campaign, 12)
        store.persist(first_campaign)
        store.persist(second_campaign)
        held = sidecar.open()
        assert set(held) == set(first_roots) | set(second_roots)

    def test_the_trees_other_columns_are_untouched(self, tmp_path: Path) -> None:
        # The selection writes no column at all: feature 110 keeps is_null out
        # of the tree store entirely, and this feature's persistence half is
        # the sealed file.  The discovery-time facts are the loop's.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        root = _node(store, campaign, depth=0, theme_root="momentum")
        _wells(store, campaign, 11)
        store.persist(campaign)
        with closing(store._connect()) as connection:
            cursor = connection.execute(
                f"SELECT campaign_id, theme_root, depth FROM {NODE_TABLE} WHERE id = ?",
                (root,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        assert row == (campaign, "momentum", 0)

    def test_the_tree_store_learns_no_is_null_column(self, tmp_path: Path) -> None:
        # Feature 110's rule, asserted from feature 118's side: the only place
        # the bit is written down is §7.1's sealed file.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        store.persist(campaign)
        with closing(store._connect()) as connection:
            columns = [
                row[1] for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")
            ]
        assert "is_null" not in columns

    def test_the_bit_appears_in_no_plaintext_artifact_of_the_write(
        self, tmp_path: Path
    ) -> None:
        # The sealed file is ciphertext; nothing else this write touches may
        # carry the label in the clear.  A strict reading of "the only place
        # the system writes the bit" from this feature's side.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        roots = _wells(store, campaign, 12)
        store.persist(campaign)
        assert sidecar.path.is_file()
        assert b"is_null" not in sidecar.path.read_bytes()
        # The ids themselves are in the clear in the tree store — they are
        # structural, not labels — but the *status* is not.
        assert b"is_null" not in store.path.read_bytes()
        assert b"is_null" not in b"".join(root.encode() for root in roots)

    def test_the_module_level_spelling_writes_the_same_selection(self, tmp_path: Path) -> None:
        # persist_type_r_selection is the one-call spelling: the store resolved
        # from DATABASE_URL, the drawn roots out, sealed into the sidecar the
        # caller holds.
        sidecar = _sidecar(tmp_path)
        store, url = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        selection = persist_type_r_selection(campaign, sidecar, database_url=url)
        assert store.load(campaign).null_roots == selection.null_roots

    def test_the_module_level_spelling_refuses_an_unnamed_store(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        with pytest.raises(KsGuardError, match="DATABASE_URL is unset"):
            persist_type_r_selection(str(uuid.uuid4()), sidecar, env={})


# -- The store: the read ---------------------------------------------------------


class TestTheSelectionReadsBack:
    def test_a_persisted_selection_loads_back_identically(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        written = store.persist(campaign)
        assert store.load(campaign) == written

    def test_a_campaign_never_drawn_loads_as_none(self, tmp_path: Path) -> None:
        # None means *this campaign's roots are not in the sidecar* — the
        # selection was never persisted — which is the honest answer for a
        # campaign whose wells the file does not mention.  The file must exist
        # for the question to be answerable at all: a *missing* file is a
        # different fact, and :meth:`NullSidecar.open` raises for it rather than
        # answering an empty map (see the test below).
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        drawn = _campaign(store)
        _wells(store, drawn, 12)
        store.persist(drawn)
        undrawn = _campaign(store)
        _wells(store, undrawn, 12)
        assert store.load(undrawn) is None

    def test_a_missing_sidecar_file_raises_rather_than_answering_none(
        self, tmp_path: Path
    ) -> None:
        # The taxonomy's most important rule: a sidecar that will not open must
        # never be reported as a store-contract problem, because "the key was
        # lost" and "this campaign was never drawn" are opposite findings about
        # every score the system has recorded.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        with pytest.raises(SidecarStoreError):
            store.load(campaign)

    def test_an_unopenable_sidecar_raises_rather_than_answering_none(
        self, tmp_path: Path
    ) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        store.persist(campaign)
        raw = bytearray(sidecar.path.read_bytes())
        raw[-1] ^= 0x01
        sidecar.path.write_bytes(bytes(raw))
        with pytest.raises(SidecarDecryptionError):
            store.load(campaign)

    def test_a_half_written_selection_is_refused_by_name(self, tmp_path: Path) -> None:
        # A file holding some of a campaign's roots and not others is a half:
        # the roots it omits are recorded nowhere, so the world cannot be read
        # back as one.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        roots = _wells(store, campaign, 12)
        store.persist(campaign)
        held = sidecar.open()
        del held[roots[0]]
        sidecar.write(held)
        with pytest.raises(KsGuardError, match="is a half"):
            store.load(campaign)

    def test_the_loaded_fraction_is_the_campaign_rows(self, tmp_path: Path) -> None:
        # The file holds the bit and its perm parameters — §7.1's schema —
        # and φ is the campaign's own column (feature 117's).
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store, workspace_count=24, null_fraction=0.15)
        _wells(store, campaign, 24)
        store.persist(campaign)
        loaded = store.load(campaign)
        assert loaded.null_fraction == 0.15
        assert loaded.workspace_count == 24


# -- The store: inheritance ------------------------------------------------------


class TestTheStatusIsInheritedByTheWholeSubtree:
    def _planted(self, tmp_path: Path) -> tuple[TypeRSelection, str, dict[str, list[str]]]:
        """A campaign with 12 wells at depth 0, each carrying two descendants."""
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        roots = _wells(store, campaign, 12)
        tree: dict[str, list[str]] = {}
        for root in roots:
            child = _node(store, campaign, parent_id=root, depth=1)
            grandchild = _node(store, campaign, parent_id=child, depth=2)
            tree[root] = [child, grandchild]
        store.persist(campaign)
        return store, campaign, tree

    def test_a_descendant_of_a_null_root_is_null(self, tmp_path: Path) -> None:
        store, campaign, tree = self._planted(tmp_path)
        selection = store.load(campaign)
        for root in selection.null_roots:
            for descendant in tree[root]:
                assert store.null_status(descendant) is True

    def test_a_descendant_of_a_real_root_is_real(self, tmp_path: Path) -> None:
        # §7.3: every *unselected* root stays real, and so does its subtree.
        store, campaign, tree = self._planted(tmp_path)
        selection = store.load(campaign)
        for root in selection.real_roots:
            for descendant in tree[root]:
                assert store.null_status(descendant) is False

    def test_a_root_answers_its_own_status(self, tmp_path: Path) -> None:
        store, campaign, _ = self._planted(tmp_path)
        selection = store.load(campaign)
        for root in selection.null_roots:
            assert store.null_status(root) is True
        for root in selection.real_roots:
            assert store.null_status(root) is False

    def test_the_whole_subtree_agrees_with_its_root(self, tmp_path: Path) -> None:
        # The sentence's third claim, stated as one assertion over the tree:
        # for every node, the status equals its root's.
        store, campaign, tree = self._planted(tmp_path)
        selection = store.load(campaign)
        expected = {root: True for root in selection.null_roots}
        expected.update({root: False for root in selection.real_roots})
        for root, descendants in tree.items():
            for node in [root, *descendants]:
                assert store.null_status(node) == expected[root]

    def test_a_deep_descendant_inherits_the_same_status(self, tmp_path: Path) -> None:
        # The walk is not bounded by depth: a node ten levels down inherits its
        # root's status exactly as its parent does.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store, workspace_count=8, null_fraction=0.35)
        _wells(store, campaign, 8)
        selection = store.persist(campaign)
        root = selection.null_roots[0]
        current = root
        for depth in range(1, 11):
            current = _node(store, campaign, parent_id=current, depth=depth)
        assert store.null_status(current) is True

    def test_a_node_the_table_does_not_hold_is_refused(self, tmp_path: Path) -> None:
        store, _, _ = self._planted(tmp_path)
        with pytest.raises(KsGuardError, match="holds no row"):
            store.null_status(str(uuid.uuid4()))

    def test_a_dangling_parent_edge_is_refused_by_name(self, tmp_path: Path) -> None:
        # A chain that dangles at a node the discovery loop never placed has no
        # root to inherit from.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        store.persist(campaign)
        orphan = _node(store, campaign, parent_id=str(uuid.uuid4()), depth=1)
        with pytest.raises(KsGuardError, match="dangles"):
            store.null_status(orphan)

    def test_a_cyclic_chain_is_refused_by_name(self, tmp_path: Path) -> None:
        # A chain that cycles has no root for a status to be inherited from.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        store.persist(campaign)
        first = _node(store, campaign, depth=1)
        second = _node(store, campaign, parent_id=first, depth=2)
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {NODE_TABLE} SET parent_id = ? WHERE id = ?", (second, first)
            )
        with pytest.raises(KsGuardError, match="revisits"):
            store.null_status(first)

    def test_a_chain_crossing_campaigns_is_refused_by_name(self, tmp_path: Path) -> None:
        # §7.3 scopes a discovery tree to one campaign, and a node whose
        # ancestor belongs elsewhere is a node whose root this campaign never
        # planted.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        first_campaign = _campaign(store)
        second_campaign = _campaign(store)
        _wells(store, first_campaign, 12)
        store.persist(first_campaign)
        foreign_root = _node(store, second_campaign)
        child = _node(store, first_campaign, parent_id=foreign_root, depth=1)
        with pytest.raises(KsGuardError, match="crosses from campaign"):
            store.null_status(child)

    def test_a_root_recorded_nowhere_is_refused_rather_than_answered_false(
        self, tmp_path: Path
    ) -> None:
        # §7.3 records *every* root, so a root missing from the file is a
        # campaign whose selection was never persisted — and serving False
        # there would report a real world for a campaign that planted nulls.
        # The late root is inserted *after* the selection was sealed, which is
        # what a root the discovery loop placed after the draw looks like.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        store.persist(campaign)
        late_root = _node(store, campaign)
        with pytest.raises(KsGuardError, match="recorded nowhere"):
            store.null_status(late_root)


# -- The store: refusals ---------------------------------------------------------


class TestTheStoreRefusesRatherThanGuesses:
    def test_a_campaign_the_table_does_not_hold_is_refused_by_name(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        with pytest.raises(KsGuardError, match="holds no row"):
            store.persist(str(uuid.uuid4()))

    def test_a_type_d_campaign_is_refused_with_its_type_named(self, tmp_path: Path) -> None:
        # §7.3: campaigns are homogeneous in null type.  A root selection drawn
        # onto a Type-D tree would be a bit no read path serves — feature 121
        # resolves a Type-D request against the depth rule, not the sidecar.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store, campaign_type="Type-D")
        _wells(store, campaign, 12)
        with pytest.raises(KsGuardError, match="is a 'Type-D' campaign") as raised:
            store.persist(campaign)
        assert TYPE_R_CAMPAIGN_TYPE in str(raised.value)

    def test_a_type_d_campaign_is_refused_on_the_read_path_too(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store, campaign_type="Type-D")
        _wells(store, campaign, 12)
        with pytest.raises(KsGuardError, match="Type-D"):
            store.load(campaign)

    def test_a_type_d_campaign_is_refused_by_the_inheritance_rule(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store, campaign_type="Type-D")
        root = _node(store, campaign)
        with pytest.raises(KsGuardError, match="Type-D"):
            store.null_status(root)

    def test_a_tree_with_no_roots_is_refused_by_name(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        with pytest.raises(KsGuardError, match="holds no roots"):
            store.persist(campaign)

    def test_a_fraction_the_tree_cannot_satisfy_is_refused(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store, workspace_count=12, null_fraction=0.35)
        _wells(store, campaign, 3)
        with pytest.raises(KsGuardError, match="without replacement"):
            store.persist(campaign)

    def test_a_stored_fraction_that_is_not_a_fraction_is_refused(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET {NULL_FRACTION_COLUMN} = 0.0 WHERE id = ?",
                (campaign,),
            )
        with pytest.raises(KsGuardError, match=NULL_FRACTION_COLUMN):
            store.persist(campaign)

    def test_a_stored_workspace_count_that_is_not_a_count_is_refused(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET {WORKSPACE_COUNT_COLUMN} = 0 WHERE id = ?",
                (campaign,),
            )
        with pytest.raises(KsGuardError, match=WORKSPACE_COUNT_COLUMN):
            store.persist(campaign)

    def test_a_malformed_campaign_id_is_refused_as_a_store_error(self, tmp_path: Path) -> None:
        # The taxonomy's split: a malformed id handed to the *selection* store
        # is a store-contract failure, not a sidecar-schema one.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        with pytest.raises(KsGuardError, match="not a UUID"):
            store.persist("not-a-uuid")

    def test_an_empty_database_url_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(KsGuardError, match="non-empty"):
            TypeRSelection("   ", _sidecar(tmp_path))

    def test_a_non_sidecar_is_refused_by_name(self, tmp_path: Path) -> None:
        # The bit may only be written into §7.1's sealed file — so a store
        # handed something else is refused rather than sealing anything.
        with pytest.raises(KsGuardError, match="sealed into"):
            TypeRSelection("sqlite:///whatever.db", "not-a-sidecar")  # type: ignore[arg-type]

    def test_a_non_sqlite_url_is_refused(self, tmp_path: Path) -> None:
        store = TypeRSelection("postgresql://host/db", _sidecar(tmp_path))
        with pytest.raises(KsGuardError, match="sqlite"):
            store.persist(str(uuid.uuid4()))

    def test_an_in_memory_url_is_refused(self, tmp_path: Path) -> None:
        store = TypeRSelection("sqlite:///:memory:", _sidecar(tmp_path))
        with pytest.raises(KsGuardError, match="no database path"):
            store.persist(str(uuid.uuid4()))


# -- Composition -----------------------------------------------------------------


class TestResolve:
    def test_no_database_url_resolves_to_none(self, tmp_path: Path) -> None:
        assert TypeRSelection.resolve({}) is None

    def test_a_blank_database_url_resolves_to_none(self) -> None:
        assert TypeRSelection.resolve({DATABASE_URL_ENV: "   "}) is None

    def test_a_database_with_no_sidecar_resolves_to_none(self) -> None:
        # The one component that needs *both* halves: a deployment carrying a
        # relational store without a sidecar composes no selection store
        # rather than a half-store that could draw but not persist.
        assert TypeRSelection.resolve({DATABASE_URL_ENV: "sqlite:///x.db"}) is None

    def test_both_halves_resolve_to_a_store(self, tmp_path: Path, monkeypatch) -> None:
        from nulloracle import KEY_REF_ENV, SIDECAR_PATH_ENV

        monkeypatch.setenv(SIDECAR_PATH_ENV, str(tmp_path / "sidecar.enc"))
        monkeypatch.setenv(KEY_REF_ENV, f"hex:{TEST_KEY_HEX}")
        store = TypeRSelection.resolve(
            {
                DATABASE_URL_ENV: f"sqlite:///{tmp_path / 'x.db'}",
                SIDECAR_PATH_ENV: str(tmp_path / "sidecar.enc"),
                KEY_REF_ENV: f"hex:{TEST_KEY_HEX}",
            }
        )
        assert store is not None
        assert store.sidecar.path == tmp_path / "sidecar.enc"

    def test_construction_touches_no_file(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        assert store.database_url.startswith("sqlite:///")
        assert not sidecar.path.exists()
        assert not store.path.exists()


# -- The store mirrors the migration ----------------------------------------------


def _table_info(path: Path, table: str) -> list[tuple]:
    """``PRAGMA table_info`` for ``table`` on the SQLite file at ``path``."""
    connection = sqlite3.connect(path)
    try:
        cursor = connection.execute(f"PRAGMA table_info({table})")
        try:
            return cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()


class TestTheStoreMirrorsTheMigration:
    def test_the_migration_creates_the_five_column_node_table(self, tmp_path: Path) -> None:
        # The node table is owned by feature 97's migration, which creates it
        # with exactly the five structural columns — id, parent_id, campaign_id,
        # theme_root, depth.  This feature adds no column: feature 110 keeps
        # is_null out of the tree store entirely, and this store's storage half
        # is §7.1's sealed file.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        columns = [row[1] for row in _table_info(theirs_path, NODE_TABLE)]
        assert columns == ["id", "parent_id", "campaign_id", "theme_root", "depth"]
        assert "is_null" not in columns

    def test_the_store_creates_the_same_five_columns(self, tmp_path: Path) -> None:
        # A store-created table and a migration-created table are the same
        # schema — the contract every store in this workspace states.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        store._connect().close()
        assert [row[1] for row in _table_info(store.path, NODE_TABLE)] == [
            row[1] for row in _table_info(theirs_path, NODE_TABLE)
        ]

    def test_the_store_works_against_a_migration_created_database(
        self, tmp_path: Path
    ) -> None:
        # The production arrangement: the tree and the campaign row live in a
        # database the *migration* brought to its revision, and the store reads
        # them without recreating anything.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        url = f"sqlite:///{theirs_path}"
        sidecar = _sidecar(tmp_path)
        store = TypeRSelection(url, sidecar)
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, {CAMPAIGN_TYPE_COLUMN}, "
                f"{WORKSPACE_COUNT_COLUMN}, {NULL_FRACTION_COLUMN}) "
                "VALUES (?, 'Type-R', 12, 0.1667)",
                (CAMPAIGN,),
            )
            for _ in range(12):
                connection.execute(
                    f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth) "
                    "VALUES (?, ?, 'macro', 0)",
                    (str(uuid.uuid4()), CAMPAIGN),
                )
        selection = store.persist(CAMPAIGN)
        assert len(selection.null_roots) == 2

    def test_the_campaign_table_carries_the_column_feature_117_writes(
        self, tmp_path: Path
    ) -> None:
        # The φ this draw reads back is the column feature 117 persisted.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        store._connect().close()
        columns = {row[1] for row in _table_info(store.path, CAMPAIGN_TABLE)}
        assert {CAMPAIGN_TYPE_COLUMN, WORKSPACE_COUNT_COLUMN, NULL_FRACTION_COLUMN} <= columns

    def test_reopening_a_database_changes_nothing(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        store._connect().close()
        before = _table_info(store.path, NODE_TABLE)
        store._connect().close()
        assert _table_info(store.path, NODE_TABLE) == before

    def test_the_migration_runs_over_a_store_created_database(self, tmp_path: Path) -> None:
        # Running the migration over a database this store created changes
        # nothing — the same path on a fresh database and an existing one.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        store._connect().close()
        before = _table_info(store.path, NODE_TABLE)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            _migration().upgrade(connection, dialect="sqlite")
        assert _table_info(store.path, NODE_TABLE) == before


class TestTheRootReading:
    def test_a_root_is_a_node_with_no_parent(self, tmp_path: Path) -> None:
        # migrations/versions/0118_node_table.py: "A root node carries NULL;
        # every other node names its parent."
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        roots = _wells(store, campaign, 12)
        for root in roots:
            _node(store, campaign, parent_id=root, depth=1)
        selection = store.persist(campaign)
        assert set(selection.roots) == set(roots)

    def test_only_this_campaigns_roots_are_read(self, tmp_path: Path) -> None:
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        first_campaign = _campaign(store)
        second_campaign = _campaign(store)
        first_roots = _wells(store, first_campaign, 12)
        _wells(store, second_campaign, 12)
        selection = store.persist(first_campaign)
        assert set(selection.roots) == set(first_roots)


class TestTheSidecarIsWrittenWhole:
    def test_a_malformed_assignment_is_never_sealed(self, tmp_path: Path) -> None:
        # NullAssignment validates at construction, so the store cannot seal a
        # status that is not a genuine bool — the schema's refusal, from the
        # writer's side.
        with pytest.raises(SidecarError):
            NullAssignment(node_id=str(uuid.uuid4()), is_null="true", perm_seed=1)

    def test_the_write_merges_rather_than_replaces(self, tmp_path: Path) -> None:
        # The merge is what makes two campaigns coexist in one deployment's
        # file: an entry the new write does not name survives it.
        sidecar = _sidecar(tmp_path)
        store, _ = _store(tmp_path, sidecar)
        campaign = _campaign(store)
        _wells(store, campaign, 12)
        stranger = str(uuid.uuid4())
        sidecar.write([NullAssignment(node_id=stranger, is_null=True, perm_seed=1)])
        store.persist(campaign)
        assert stranger in sidecar.open()
