"""Feature 118, end to end: the assembled system persists the Type-R selection.

app_spec.xml, "Null Oracle & Planted Nulls", feature 118: *System persists
Type-R null status drawn without replacement across roots, inherited by the
whole subtree.*

The member's own suite (``packages/nulloracle/tests``) pins each contract in
isolation — the draw, the count, the refusals, the record, the store, the
walk, the component.  This suite pins the sentence those contracts are *for*,
through the assembled system: the selection store composed by the application
factory, read through ``create_app().get``, reading a discovery tree
from a relational store and sealing the drawn status into §7.1's sidecar.

That distinction is the whole point here, and it is sharper for this feature
than for any of its siblings in the category, because **this is the one store
in the member that needs two composed halves**: the tree and the campaign row
from a relational store, and §7.1's sealed sidecar for the bit.  Every other
feature in §7 either draws (and needs no store) or persists into one artifact.
So the integration question is not "does the draw work" but:

* does the composed system carry the store at all, in a deployment whose
  ``DATABASE_URL`` the root conftest supplies *and* whose sidecar the
  ``sidecar_path``/``key_ref`` fixtures configure;
* are the drawn roots the ones the campaign's own fraction asks for — φ and
  ``W`` read from the campaign row the orchestrator wrote, not from a caller;
* does the bit land **only** in the sealed file, with the tree store's
  structural columns untouched and no ``is_null`` column anywhere (feature
  110);
* is the status *inherited*: a descendant of a null root reads null, a
  descendant of a real root reads real, all the way down;
* and does the assembled system's read path — the composed component —
  hand a caller the same selection the write sealed.

A member that passed its unit suite while the composed application carried no
store at all would satisfy every requirement of the draw tests and none of
these.
"""

from __future__ import annotations

import uuid

import pytest
from nulloracle import DATABASE_URL_ENV, NODE_TABLE, TYPE_R_COMPONENT_NAME

from app.module_loader import create_app

CAMPAIGN_TABLE = "campaign"

#: §7.3's Type-R fraction and well count, as a campaign is planned with them.
NULL_FRACTION = 0.1667
WORKSPACE_COUNT = 12
EXPECTED_NULL_ROOTS = 2  # round(0.1667 * 12)


def campaign_row(**overrides) -> tuple:
    """A campaign's planning-time columns, as the migration spells them.

    The three ``NOT NULL`` columns with no default — the type, ``W`` and
    ``φ`` — in the shape ``0111_campaign_table.py`` describes a campaign as
    being planned with.  A campaign is written by its planner *before any
    node is expanded*, which is why this suite inserts the row itself rather
    than expecting the store to: the store reads a campaign, it does not
    invent one.
    """
    fields = {
        "campaign_type": "Type-R",
        "workspace_count": WORKSPACE_COUNT,
        "null_fraction": NULL_FRACTION,
    }
    fields.update(overrides)
    return tuple(fields.values())


@pytest.fixture
def composed_selection(sidecar_path, key_ref: str):
    """The selection store the *composed application* carries for this environment.

    Read out of the application the factory builds — not constructed
    directly — because the claim under test is about the assembled system: a
    deployment sets ``DATABASE_URL`` and configures a sidecar, and the
    composed application must carry a usable selection store pointed at both.
    The root conftest points the database at a per-test SQLite file and this
    suite's fixtures point the sidecar into the test's temporary directory,
    so every test here is isolated from every other.

    Both fixtures are requested *before* the composition, because the
    builder resolves both halves at ``create_app()`` time: a test that
    composed first and configured afterwards would be testing a different
    deployment from the one it described.
    """
    return create_app().get(TYPE_R_COMPONENT_NAME)


@pytest.fixture
def planned_campaign(composed_selection):
    """A campaign the orchestrator has planned, and its id.

    Inserted through the store's own connection so the row lands in the same
    database the store reads — which is the point: one table, the
    orchestrator's, with this feature filling no column of it.
    """
    identifier = str(uuid.uuid4())
    with composed_selection._connect() as connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
            "null_fraction) VALUES (?, ?, ?, ?)",
            (identifier, *campaign_row()),
        )
    return identifier


def _statuses(sidecar) -> dict[str, tuple[bool, int, int]]:
    """A sidecar's map as plain tuples: ``{node_id: (is_null, perm_seed, block_days)}``.

    Read through the accessors rather than compared as ``NullAssignment``
    values, because the factory's scan and a direct ``import nulloracle``
    yield two structurally identical classes that are not the same object —
    the wrinkle this suite's conftest documents. Comparing the *fields* is
    comparing what §7.1's schema actually fixes.
    """
    return {
        node: (entry.is_null, entry.perm_seed, entry.block_days)
        for node, entry in sidecar.open().items()
    }


def plant_tree(store, campaign: str, *, roots: int = WORKSPACE_COUNT, depth: int = 2):
    """A discovery tree of ``roots`` wells, each carrying ``depth`` descendants.

    Inserted the way the discovery loop inserts one: a root whose
    ``parent_id`` is ``NULL``, and children that name their parent.
    ``migrations/versions/0118_node_table.py`` — *"A root node carries
    ``NULL``; every other node names its parent."*

    Returns ``{root: [child, grandchild, ...]}`` so a test can ask about a
    specific root's subtree rather than about the tree in aggregate.
    """
    tree: dict[str, list[str]] = {}
    with store._connect() as connection:
        for _ in range(roots):
            root = str(uuid.uuid4())
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, theme_root, "
                "depth) VALUES (?, NULL, ?, 'macro', 0)",
                (root, campaign),
            )
            descendants: list[str] = []
            parent = root
            for level in range(1, depth + 1):
                child = str(uuid.uuid4())
                connection.execute(
                    f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, "
                    "theme_root, depth) VALUES (?, ?, ?, 'macro', ?)",
                    (child, parent, campaign, level),
                )
                descendants.append(child)
                parent = child
            tree[root] = descendants
    return tree


class TestTheComposedSystemCarriesTheSelectionStore:
    def test_the_factory_composes_a_store_for_the_environment(
        self, composed_selection, test_database_url: str
    ) -> None:
        assert composed_selection is not None
        assert composed_selection.database_url == test_database_url

    def test_a_fresh_composition_reaches_the_same_store(
        self, composed_selection, sidecar_path
    ) -> None:
        # ``create_app().get`` is how the rest of this category's features
        # reach the selection, so it must resolve to the store the factory
        # composed.
        store = create_app().get(TYPE_R_COMPONENT_NAME)
        assert store is not None
        assert store.database_url == composed_selection.database_url
        assert store.sidecar.path == sidecar_path

    def test_both_of_the_stores_halves_are_the_configured_ones(
        self, composed_selection, test_database_url: str, sidecar_path
    ) -> None:
        # This is the one component in the member that needs two things
        # composed — the tree *and* §7.1's sealed file — so the integration
        # claim is specifically that a deployment configured for both gets a
        # store holding both, pointed at the fixtures' own paths.
        assert composed_selection.database_url == test_database_url
        assert composed_selection.sidecar.path == sidecar_path

    def test_a_deployment_with_no_sidecar_composes_no_store(
        self, monkeypatch: pytest.MonkeyPatch, sidecar_path
    ) -> None:
        # Half a configuration is not a configuration: a store holding only
        # the database could draw but not persist, and the bit may only be
        # written into §7.1's file (feature 110). Degrade, don't break — the
        # rest of the workspace still composes.
        from nulloracle import KEY_REF_ENV, SIDECAR_PATH_ENV

        monkeypatch.delenv(SIDECAR_PATH_ENV, raising=False)
        monkeypatch.delenv(KEY_REF_ENV, raising=False)
        monkeypatch.setenv("LAKE_ROOT", str(sidecar_path.parent.parent))
        app = create_app()
        # The lake root names a path, but no key: still no sidecar, so still
        # no selection store.
        assert app.get(TYPE_R_COMPONENT_NAME) is None
        assert len(app.order) > 5  # ...and the rest of the workspace is there

    def test_an_unconfigured_deployment_composes_no_store(
        self, monkeypatch: pytest.MonkeyPatch, sidecar_path, key_ref: str
    ) -> None:
        # The other half: no relational store at all, however well the sidecar
        # is configured.
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        app = create_app()
        assert app.get(TYPE_R_COMPONENT_NAME) is None
        assert len(app.order) > 5

    def test_composing_the_store_creates_no_sidecar_file(
        self, composed_selection, sidecar_path
    ) -> None:
        # Construction resolves nothing: the factory builds every registered
        # component on every create_app(), and a store that opened — or
        # worse, *wrote* — §7.1's file at construction would put the null
        # labels on disk in the path of every process that merely composed
        # the app.
        assert composed_selection is not None
        assert not sidecar_path.exists()


class TestTheDrawReadsTheCampaignsOwnRow:
    def test_the_drawn_count_is_the_fractions(
        self, composed_selection, planned_campaign
    ) -> None:
        # The headline claim of feature 118, end to end: round(φ·W) roots of
        # the campaign's tree, with φ and W read from the row the orchestrator
        # wrote and not from an argument anyone passed in.
        plant_tree(composed_selection, planned_campaign)
        selection = composed_selection.persist(planned_campaign)
        assert len(selection.null_roots) == EXPECTED_NULL_ROOTS
        assert selection.null_fraction == NULL_FRACTION
        assert selection.workspace_count == WORKSPACE_COUNT

    def test_the_drawn_roots_are_distinct_and_are_roots(
        self, composed_selection, planned_campaign
    ) -> None:
        # The load-bearing word of the sentence, through the assembled system:
        # without replacement, so no collision — and every drawn root really
        # is a well of this campaign's tree.
        tree = plant_tree(composed_selection, planned_campaign)
        selection = composed_selection.persist(planned_campaign)
        assert len(set(selection.null_roots)) == len(selection.null_roots)
        assert set(selection.null_roots) <= set(tree)
        assert set(selection.real_roots) <= set(tree)
        assert not set(selection.null_roots) & set(selection.real_roots)

    def test_a_replanned_workspace_count_changes_the_draw(
        self, composed_selection, planned_campaign
    ) -> None:
        # φ and W are the campaign's, so a campaign re-planned with a new W —
        # the very thing a refresh is for — draws a different number of roots
        # without the caller supplying anything.
        plant_tree(composed_selection, planned_campaign, roots=24)
        with composed_selection._connect() as connection:
            connection.execute(
                "UPDATE campaign SET workspace_count = ?, null_fraction = ? WHERE id = ?",
                (24, 0.25, planned_campaign),
            )
        second = composed_selection.persist(planned_campaign)
        assert len(second.null_roots) == round(0.25 * 24)

    def test_the_selection_is_reproducible_from_the_campaign(
        self, composed_selection, planned_campaign
    ) -> None:
        # §12: the same campaign replays into the same world, which is what
        # makes an FDR measured over it a number rather than an anecdote.
        plant_tree(composed_selection, planned_campaign)
        first = composed_selection.persist(planned_campaign)
        again = composed_selection.persist(planned_campaign)
        assert first == again


class TestTheBitLandsOnlyInTheSealedFile:
    def test_the_drawn_status_is_sealed_into_the_sidecar(
        self, composed_selection, planned_campaign, sidecar_path
    ) -> None:
        # Feature 118's persistence half, end to end: §7.1's file exists
        # afterwards, holds an entry per root, and the entries agree with the
        # selection the draw returned.
        tree = plant_tree(composed_selection, planned_campaign)
        selection = composed_selection.persist(planned_campaign)
        assert sidecar_path.is_file()
        held = composed_selection.sidecar.open()
        assert set(held) == set(tree)
        assert {root for root in tree if held[root].is_null} == set(selection.null_roots)

    def test_the_tree_store_learns_no_is_null_column(
        self, composed_selection, planned_campaign
    ) -> None:
        # Feature 110's rule, asserted through the assembled system: the only
        # place the bit is written down is §7.1's sealed file. A schema that
        # grew an ``is_null`` column would be a plaintext mirror of the
        # labels, which is the one thing the sidecar exists to prevent.
        plant_tree(composed_selection, planned_campaign)
        composed_selection.persist(planned_campaign)
        with composed_selection._connect() as connection:
            columns = [
                row[1]
                for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")
            ]
        assert "is_null" not in columns
        assert columns == ["id", "parent_id", "campaign_id", "theme_root", "depth"]

    def test_the_structural_columns_are_untouched(
        self, composed_selection, planned_campaign
    ) -> None:
        # The selection writes no column at all — the discovery-time facts
        # belong to the loop that placed the nodes, and a writer that also
        # rewrote them would make the tree's provenance unattributable.
        tree = plant_tree(composed_selection, planned_campaign)
        before = self._rows(composed_selection, planned_campaign)
        composed_selection.persist(planned_campaign)
        assert self._rows(composed_selection, planned_campaign) == before
        assert len(before) == len(tree) * 3  # a root and two descendants per well

    @staticmethod
    def _rows(store, campaign: str) -> list[tuple]:
        """Every node row of a campaign, in a stated order."""
        with store._connect() as connection:
            return sorted(
                connection.execute(
                    f"SELECT id, parent_id, theme_root, depth FROM {NODE_TABLE} "
                    "WHERE campaign_id = ?",
                    (campaign,),
                ).fetchall()
            )

    def test_reopening_the_sealed_file_yields_the_same_map(
        self, composed_selection, planned_campaign, key_ref: str
    ) -> None:
        # The file is the record, so a second process holding the same key
        # reads the same world — the property the whole calibration rests on.
        #
        # Compared field by field rather than by ``==`` on the mappings: the
        # factory's scan imports the member under a synthetic module alias, so
        # the composed store's ``NullAssignment`` is structurally but not
        # identically the class a direct ``import nulloracle`` yields — the
        # same two-module-worlds wrinkle ``tests/feature-store/test_registration.py``
        # documents, and the same answer: assert on the values the two copies
        # agree on because they are the same source.
        from nulloracle import NullSidecar

        plant_tree(composed_selection, planned_campaign)
        composed_selection.persist(planned_campaign)
        reopened = NullSidecar.resolve()
        assert reopened is not None
        assert _statuses(reopened) == _statuses(composed_selection.sidecar)


class TestTheStatusIsInheritedAcrossTheAssembledSystem:
    def test_every_node_of_the_tree_agrees_with_its_root(
        self, composed_selection, planned_campaign
    ) -> None:
        # The sentence's third claim, end to end and stated as one assertion
        # over the whole tree: for every node, the status equals its root's.
        tree = plant_tree(composed_selection, planned_campaign)
        selection = composed_selection.persist(planned_campaign)
        expected = dict.fromkeys(selection.null_roots, True)
        expected.update(dict.fromkeys(selection.real_roots, False))
        for root, descendants in tree.items():
            for node in [root, *descendants]:
                assert composed_selection.null_status(node) is expected[root]

    def test_a_descendant_is_null_though_the_file_never_names_it(
        self, composed_selection, planned_campaign
    ) -> None:
        # §7.3 inherits rather than records: the file holds the *roots*, so a
        # descendant's status is derived by walking to its root. This is the
        # assertion that would fail for a store that answered None — or
        # False — for a node the map does not hold.
        tree = plant_tree(composed_selection, planned_campaign)
        selection = composed_selection.persist(planned_campaign)
        root = selection.null_roots[0]
        child, grandchild = tree[root]
        held = composed_selection.sidecar.open()
        assert child not in held and grandchild not in held
        assert composed_selection.null_status(child) is True
        assert composed_selection.null_status(grandchild) is True

    def test_the_inheritance_survives_a_replan(
        self, composed_selection, planned_campaign
    ) -> None:
        # A re-planned campaign re-draws, and a descendant's answer follows
        # the *new* selection rather than a value cached from the old one.
        tree = plant_tree(composed_selection, planned_campaign)
        first = composed_selection.persist(planned_campaign)
        with composed_selection._connect() as connection:
            connection.execute(
                "UPDATE campaign SET workspace_count = ?, null_fraction = ? WHERE id = ?",
                (12, 1.0, planned_campaign),
            )
        second = composed_selection.persist(planned_campaign)
        assert len(second.null_roots) == 12
        # Every well is now null, so every descendant reads null.
        for root, descendants in tree.items():
            for node in [root, *descendants]:
                assert composed_selection.null_status(node) is True
        assert set(first.null_roots) <= set(second.null_roots)


class TestTheReadPathThroughTheComposition:
    def test_a_fresh_composition_returns_the_selection_the_write_sealed(
        self, composed_selection, planned_campaign
    ) -> None:
        plant_tree(composed_selection, planned_campaign)
        written = composed_selection.persist(planned_campaign)
        store = create_app().get(TYPE_R_COMPONENT_NAME)
        assert store.load(planned_campaign) == written

    def test_a_campaign_never_drawn_reads_as_none(
        self, composed_selection, planned_campaign
    ) -> None:
        # None means *this campaign's roots are not in the file*. It must
        # never be read as "the campaign planted no nulls" — the distinction
        # the whole member's error taxonomy is built around.
        plant_tree(composed_selection, planned_campaign)
        composed_selection.persist(planned_campaign)
        undrawn = str(uuid.uuid4())
        with composed_selection._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, ?, ?, ?)",
                (undrawn, *campaign_row()),
            )
        plant_tree(composed_selection, undrawn)
        assert create_app().get(TYPE_R_COMPONENT_NAME).load(undrawn) is None

    def test_a_type_d_campaign_is_refused_by_the_assembled_system(
        self, composed_selection
    ) -> None:
        # §7.3 keeps the two regimes' null-ness in different places: a
        # Type-D campaign's null-ness is feature 119's flip depth, and a root
        # selection drawn onto one would be a bit no read path serves.
        campaign = str(uuid.uuid4())
        with composed_selection._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-D', ?, ?)",
                (campaign, WORKSPACE_COUNT, NULL_FRACTION),
            )
        plant_tree(composed_selection, campaign)
        with pytest.raises(Exception) as raised:
            create_app().get(TYPE_R_COMPONENT_NAME).persist(campaign)
        assert type(raised.value).__name__ == "KsGuardError"
        assert "Type-D" in str(raised.value)
