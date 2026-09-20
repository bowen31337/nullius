"""Feature 117: the planted-null fraction φ = clip(2/W, 0.15, 0.35), persisted.

app_spec.xml, "Null Oracle & Planted Nulls", feature 117: *System persists
the null fraction phi on the campaign, computed as a clip of 2 divided by the
workspace count against a floor of 0.15 and a ceiling of 0.35.*  This suite
pins the two halves the sentence carries:

* the *computation* — :func:`nulloracle.phi.null_fraction`, the clip itself —
  and ``test_phi.py`` pins it in isolation, the way ``test_ks.py`` pins the
  test and ``test_ksguard.py`` pins the persistence;
* the *persistence* — :class:`nulloracle.phi.PlantedNullFraction` and the
  module-level :func:`persist_null_fraction` — which writes the computed
  fraction onto ``campaign.null_fraction``, the column
  ``migrations/versions/0111_campaign_table.py`` created for it.

The sentence's load-bearing claim is that the number is *clip(2/W, 0.15,
0.35)* and not merely a number that happens to sit in a band.  So the tests
below hold it to that: the raw ``2/W`` against a hand-worked division, the
clip's floor and ceiling against the campaigns whose ``2/W`` falls outside the
band, and the boundary — a campaign whose ``2/W`` lands inside the band comes
back unchanged while one outside it is clamped.  A test that only asserted
"the fraction is between 0.15 and 0.35" would pass for a constant, which is
not what §4.1.1 fixes.

Four properties get their own sections because they are the ones a
plausible-looking implementation gets wrong:

* **the clip is applied, not merely bounded** — a small campaign (``W = 3``,
  ``2/W = 0.667``) must come back at the ceiling ``0.35``, and a large one
  (``W = 100``, ``2/W = 0.02``) at the floor ``0.15``; a campaign whose
  ``2/W`` is already inside the band (``W = 8``, ``2/W = 0.25``) comes back
  unchanged;
* **the refusals** — ``W`` that is not a genuine positive integer is refused
  by name, because a fraction computed from ``W = 0`` (a division by zero) or
  a truthy-looking ``W = True`` would plant a fraction no campaign was
  designed with;
* **the fraction is a fact about a campaign, so the campaign is never created
  here** — a store that wrote ``null_fraction`` onto a row it invented would
  be inventing the campaign the fraction belongs to, so a campaign the table
  does not hold is refused by name;
* **the stored value is the clipped one** — the fraction features 118 and 119
  read back is the clipped value, already bounded into ``[0.15, 0.35]``, and
  the write is idempotent by campaign.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    PHI_CEILING,
    PHI_FLOOR,
    KsGuardError,
    PlantedNullFraction,
    SidecarError,
    null_fraction,
    persist_null_fraction,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0111_campaign_table.py"

#: A campaign's planning-time row: the three ``NOT NULL`` columns with no
#: default, in the shape ``migrations/versions/0111_campaign_table.py``
#: describes.  ``null_fraction`` here is a placeholder the store overwrites —
#: feature 117's whole point is that the stored value is the *clipped* one, so
#: a campaign inserted with a wrong fraction must come out carrying the right
#: one.
CAMPAIGN_COLUMNS = ("campaign_type", "workspace_count", "null_fraction")


# -- Helpers ---------------------------------------------------------------------


def _store(tmp_path: Path, name: str = "phi.db") -> tuple[PlantedNullFraction, str]:
    """A fraction store over a fresh SQLite file, with its ``DATABASE_URL``."""
    path = tmp_path / name
    url = f"sqlite:///{path}"
    return PlantedNullFraction(url), url


def _campaign(store: PlantedNullFraction, campaign_id: str | None = None, **overrides) -> str:
    """Insert a campaign row the way its planner would, and return its id.

    ``null_fraction`` is given as ``0.0`` — a value no clip would ever produce
    — so that a test asserting the stored fraction is the clipped one cannot
    pass merely because the row was inserted with the right value.  The store
    under test is what must overwrite it.
    """
    identifier = campaign_id or str(uuid.uuid4())
    fields = {"campaign_type": "Type-R", "workspace_count": 12, "null_fraction": 0.0}
    fields.update(overrides)
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, {', '.join(fields)}) "
            f"VALUES (?, {', '.join('?' * len(fields))})",
            (identifier, *fields.values()),
        )
    return identifier


def _fraction(store: PlantedNullFraction, campaign_id: str) -> float:
    """The campaign row's ``null_fraction``, read raw."""
    with closing(store._connect()) as connection:
        cursor = connection.execute(
            f"SELECT {CAMPAIGN_COLUMNS[2]} FROM {CAMPAIGN_TABLE} WHERE id = ?",
            (campaign_id,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    return row[0]


def _migration():
    """``migrations/versions/0111_campaign_table.py``, loaded by path.

    By path rather than by import because that is how a migration runner loads
    it: the file is not a module on any package's ``sys.path``, and a test that
    could only reach it through an import would be testing a different
    arrangement from the one that runs.
    """
    spec = importlib.util.spec_from_file_location(
        "migration_0111_campaign_table", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


# -- The clip --------------------------------------------------------------------


class TestTheClip:
    def test_the_raw_division_is_two_over_w(self) -> None:
        # The clip's input is exactly 2/W.  These are the campaigns whose
        # 2/W already sits inside the band, so the clip is the identity and
        # the returned value is the raw division — asserted to enough places
        # that a constant, or a 1/W, cannot pass.
        assert null_fraction(8) == pytest.approx(0.25)
        assert null_fraction(10) == pytest.approx(0.20)
        assert null_fraction(12) == pytest.approx(2.0 / 12.0)

    def test_a_small_campaign_is_held_at_the_ceiling(self) -> None:
        # W = 3 → 2/3 = 0.667, well above the 0.35 ceiling.  The clip holds it
        # at the ceiling: a small campaign must not plant more than a third of
        # its wells.
        assert null_fraction(3) == PHI_CEILING
        assert null_fraction(3) < 2.0 / 3.0

    def test_a_large_campaign_is_lifted_to_the_floor(self) -> None:
        # W = 100 → 2/100 = 0.02, well below the 0.15 floor.  The clip lifts it
        # to the floor: a large campaign must not plant so few nulls that its
        # KS guard has nothing to measure.
        assert null_fraction(100) == PHI_FLOOR
        assert null_fraction(100) > 2.0 / 100.0

    def test_the_boundaries_of_the_band(self) -> None:
        # The exact W at which 2/W crosses each bound.  W = 6 → 0.333 (inside,
        # just under the ceiling); W = 5 → 0.4 (above, so clamped); W = 13 →
        # 0.1538 (inside, just above the floor); W = 14 → 0.1429 (below, so
        # clamped).  These four pin the two clip edges on both sides.
        assert null_fraction(5) == PHI_CEILING
        assert null_fraction(6) == pytest.approx(2.0 / 6.0)
        assert null_fraction(13) == pytest.approx(2.0 / 13.0)
        assert null_fraction(14) == PHI_FLOOR

    def test_the_floor_and_ceiling_are_the_specs_own_values(self) -> None:
        assert PHI_FLOOR == 0.15
        assert PHI_CEILING == 0.35
        assert PHI_FLOOR < PHI_CEILING

    def test_every_fraction_is_inside_the_band(self) -> None:
        # Across the whole range of workspace counts the system produces, the
        # returned fraction is always in [0.15, 0.35] — the clip is applied
        # unconditionally, so a caller gets a plantable fraction.
        for w in range(1, 501):
            fraction = null_fraction(w)
            assert PHI_FLOOR <= fraction <= PHI_CEILING, w
            assert fraction == min(max(2.0 / w, PHI_FLOOR), PHI_CEILING), w


class TestTheClipRefusesRatherThanGuesses:
    def test_zero_workspaces_is_refused(self) -> None:
        # W = 0 divides by zero.  A fraction computed from it would be a
        # fraction no campaign was designed with, so it is refused by name.
        with pytest.raises(KsGuardError, match="at least 1"):
            null_fraction(0)

    def test_a_negative_workspace_count_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="at least 1"):
            null_fraction(-4)

    def test_a_boolean_workspace_count_is_refused(self) -> None:
        # True and False are ints in Python, but they are not counts: a
        # truthy-looking ``True`` would plant φ = clip(2/1, …) = 0.35 for a
        # "campaign" of one well that is not a campaign at all.
        with pytest.raises(KsGuardError, match="positive integer") as raised:
            null_fraction(True)
        assert not isinstance(raised.value, bool)

    def test_a_non_integer_workspace_count_is_refused(self) -> None:
        # A fractional well count is not a count.
        with pytest.raises(KsGuardError, match="positive integer"):
            null_fraction(8.0)
        with pytest.raises(KsGuardError, match="positive integer"):
            null_fraction("8")

    def test_the_refusal_names_the_offending_value(self) -> None:
        with pytest.raises(KsGuardError) as raised:
            null_fraction(0)
        assert "0" in str(raised.value)
        assert "workspace_count" in str(raised.value)


# -- The store: the write --------------------------------------------------------


class TestTheFractionLandsOnTheCampaign:
    def test_a_planned_campaign_carries_the_clipped_fraction(self, tmp_path: Path) -> None:
        # Feature 117 in one call: W = 3 → 2/3 = 0.667, clipped to the 0.35
        # ceiling.  The campaign was inserted with a placeholder 0.0, so the
        # stored value is the store's, clipped.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=3)
        written = store.persist(campaign, 3)
        assert written == PHI_CEILING
        assert _fraction(store, campaign) == PHI_CEILING

    def test_the_stored_value_is_the_clipped_one(self, tmp_path: Path) -> None:
        # The campaign is inserted with a wrong fraction (0.0); the store must
        # overwrite it with the clipped value for W = 8 → 0.25.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=8, null_fraction=0.999)
        store.persist(campaign, 8)
        assert _fraction(store, campaign) == pytest.approx(0.25)

    def test_the_fraction_is_fixed_from_the_callers_workspace_count(
        self, tmp_path: Path
    ) -> None:
        # The workspace count is the caller's argument, not the row's: the
        # fraction is fixed at planning time, and the planner is the caller
        # that knows the W it planned with.  A campaign row whose
        # workspace_count disagrees with the caller's argument still gets the
        # caller's fraction.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=8)
        store.persist(campaign, 4)  # 2/4 = 0.5 → clipped to 0.35
        assert _fraction(store, campaign) == PHI_CEILING

    def test_the_write_is_idempotent_by_campaign(self, tmp_path: Path) -> None:
        # A campaign re-planned with the same W keeps its fraction; the grain
        # is the campaign, and what the table holds is the latest planning
        # decision and nothing else.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=10)
        first = store.persist(campaign, 10)
        second = store.persist(campaign, 10)
        assert first == second == pytest.approx(0.20)
        assert _fraction(store, campaign) == pytest.approx(0.20)

    def test_a_replan_with_a_different_w_refreshes_the_fraction(
        self, tmp_path: Path
    ) -> None:
        # A campaign re-planned with a new workspace count gets a new fraction:
        # the planner's W is the source of truth.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=10)
        store.persist(campaign, 10)
        assert _fraction(store, campaign) == pytest.approx(0.20)
        store.persist(campaign, 4)
        assert _fraction(store, campaign) == PHI_CEILING

    def test_the_campaigns_other_columns_are_untouched(self, tmp_path: Path) -> None:
        # The fraction fills one column of a row that is not its own.  The
        # planning-time facts — the type and W — are the planner's, and a
        # fraction write that rewrote any of them would be quietly redefining
        # the campaign it just planned for.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=8)
        instant_before = self._created_at(store, campaign)
        store.persist(campaign, 8)
        with closing(store._connect()) as connection:
            cursor = connection.execute(
                "SELECT campaign_type, workspace_count, created_at "
                f"FROM {CAMPAIGN_TABLE} WHERE id = ?",
                (campaign,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        assert row[0] == "Type-R"
        assert row[1] == 8
        assert row[2] == instant_before

    def _created_at(self, store: PlantedNullFraction, campaign: str):
        with closing(store._connect()) as connection:
            cursor = connection.execute(
                f"SELECT created_at FROM {CAMPAIGN_TABLE} WHERE id = ?", (campaign,)
            )
            try:
                return cursor.fetchone()[0]
            finally:
                cursor.close()

    def test_the_module_level_spelling_writes_the_same_fraction(
        self, tmp_path: Path
    ) -> None:
        # persist_null_fraction is the one-call spelling: the store resolved
        # from DATABASE_URL, the fraction in, the clipped value out.
        store, url = _store(tmp_path)
        campaign = _campaign(store, workspace_count=6)
        written = persist_null_fraction(campaign, 6, database_url=url)
        assert written == pytest.approx(2.0 / 6.0)
        assert store.load(campaign) == pytest.approx(2.0 / 6.0)


class TestTheFractionStoreRefusesRatherThanGuesses:
    def test_a_campaign_the_table_does_not_hold_is_refused_by_name(
        self, tmp_path: Path
    ) -> None:
        # The fraction is a fact about a campaign.  A store that wrote
        # null_fraction onto a row it created would be inventing the campaign
        # the fraction belongs to — and the fraction is fixed by the planner,
        # not here.
        store, _ = _store(tmp_path)
        unplanned = str(uuid.uuid4())
        with pytest.raises(KsGuardError, match="holds no row") as raised:
            store.persist(unplanned, 8)
        assert "per campaign" in str(raised.value)

    def test_a_malformed_campaign_id_is_a_store_error_not_a_sidecar_one(
        self, tmp_path: Path
    ) -> None:
        # The taxonomy's distinction: a malformed id handed to the *fraction*
        # store is a store-contract failure.  A caller reading ``SidecarError``
        # out of a fraction write would look in the wrong module for the cause.
        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="is not a UUID") as raised:
            store.persist("not-a-uuid", 8)
        assert not isinstance(raised.value, SidecarError)
        assert isinstance(raised.value.__cause__, SidecarError)

    def test_a_refused_workspace_count_leaves_no_write(self, tmp_path: Path) -> None:
        # A W that is not a count is refused before the store is opened, so a
        # refused fraction cannot leave a half behind.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=8)
        with pytest.raises(KsGuardError, match="at least 1"):
            store.persist(campaign, 0)
        assert _fraction(store, campaign) == 0.0

    def test_the_store_refuses_a_url_it_cannot_speak(self, tmp_path: Path) -> None:
        # A scheme this member cannot open is refused by name, at resolve — the
        # store never opens a database it cannot speak.
        with pytest.raises(KsGuardError, match="unsupported") as raised:
            PlantedNullFraction("postgres:///db").persist(str(uuid.uuid4()), 8)
        assert "sqlite" in str(raised.value)

    def test_a_host_carrying_sqlite_url_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(KsGuardError, match="must not carry a host"):
            PlantedNullFraction("sqlite://host/db").persist(str(uuid.uuid4()), 8)

    def test_an_in_memory_url_is_refused(self, tmp_path: Path) -> None:
        # An in-memory database dies with the connection that opened it, and a
        # campaign's fraction must outlive the planning call that fixed it.
        with pytest.raises(KsGuardError, match="no database path"):
            PlantedNullFraction("sqlite:///:memory:").persist(str(uuid.uuid4()), 8)

    def test_an_empty_database_url_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="non-empty"):
            PlantedNullFraction("   ")


# -- The store: the read -----------------------------------------------------------


class TestTheStoredFractionIsWhatDownstreamReads:
    def test_load_reads_the_clipped_fraction(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=3)
        store.persist(campaign, 3)
        assert store.load(campaign) == PHI_CEILING

    def test_an_unplanned_campaign_reads_as_none(self, tmp_path: Path) -> None:
        # None means the campaign was never planned — the honest answer for an
        # id the table does not hold.  It does not mean the read failed.
        store, _ = _store(tmp_path)
        assert store.load(str(uuid.uuid4())) is None

    def test_a_campaign_without_a_fraction_reads_its_placeholder(
        self, tmp_path: Path
    ) -> None:
        # A campaign the planner created but whose fraction has not been fixed
        # reads the row's own value — the planner's, not a fabricated clip.
        store, _ = _store(tmp_path)
        campaign = _campaign(store, workspace_count=8, null_fraction=0.0)
        assert store.load(campaign) == 0.0

    def test_a_malformed_id_reads_as_a_store_error(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="is not a UUID"):
            store.load("not-a-uuid")


# -- The store and the migration are one schema -----------------------------------


class TestTheStoreMirrorsTheMigration:
    def test_the_column_list_matches_the_migration_exactly(
        self, tmp_path: Path
    ) -> None:
        # Not "the columns the store needs are present" — *identical*, in order
        # and in type.  A store whose campaign table had an extra column, a
        # retyped one, or a different nullability would be a second schema
        # wearing the migration's table name, and the mismatch would surface
        # only in production, on the dialect the tests do not run.
        migration = _migration()
        store, _ = _store(tmp_path, "store.db")
        _campaign(store)
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")

        def _columns(path: Path) -> list[tuple]:
            with closing(sqlite3.connect(path)) as connection:
                cursor = connection.execute(f"PRAGMA table_info({CAMPAIGN_TABLE})")
                try:
                    return [
                        (row[1], row[2], row[3], row[4], row[5])
                        for row in cursor.fetchall()
                    ]
                finally:
                    cursor.close()

        mine = _columns(store.path)
        theirs = _columns(theirs_path)
        assert mine == theirs

    def test_running_the_migration_over_the_stores_database_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        # The contract every store in this workspace states: a fresh database
        # and an existing one take the same path, so no migration step is
        # needed here — and running the migration over a database the store
        # created is a no-op rather than a conflict.
        migration = _migration()
        store, url = _store(tmp_path)
        campaign = _campaign(store, workspace_count=8)
        before = store.persist(campaign, 8)
        migration.apply(url)
        assert store.load(campaign) == before

    def test_the_store_works_against_a_migration_created_table(
        self, tmp_path: Path
    ) -> None:
        # The fraction store opens a database the *migration* created — the
        # production arrangement — and writes the clipped fraction onto the
        # campaign the migration's planner inserted.
        migration = _migration()
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        campaign = str(uuid.uuid4())
        with closing(sqlite3.connect(theirs_path)) as connection, connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, 'Type-R', 8, 0.0)",
                (campaign,),
            )
        written = persist_null_fraction(campaign, 8, database_url=f"sqlite:///{theirs_path}")
        assert written == pytest.approx(0.25)
        with closing(sqlite3.connect(theirs_path)) as connection:
            cursor = connection.execute(
                f"SELECT null_fraction FROM {CAMPAIGN_TABLE} WHERE id = ?", (campaign,)
            )
            try:
                stored = cursor.fetchone()[0]
            finally:
                cursor.close()
        assert stored == pytest.approx(0.25)


# -- Resolution ------------------------------------------------------------------


class TestResolve:
    def test_an_unset_database_url_resolves_to_none(self) -> None:
        assert PlantedNullFraction.resolve() is None

    def test_a_blank_database_url_resolves_to_none(self) -> None:
        assert PlantedNullFraction.resolve(env={DATABASE_URL_ENV: "   "}) is None

    def test_a_named_database_url_resolves_to_a_store(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'phi.db'}"
        resolved = PlantedNullFraction.resolve(env={DATABASE_URL_ENV: url})
        assert isinstance(resolved, PlantedNullFraction)
        assert resolved.database_url == url
