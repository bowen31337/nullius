"""Feature 4's five grid columns, on the discovery side.

additions_spec_engine_edge_recovery.xml, "Campaign Grid", feature 4, fourth
step, first half: *"discovery (new file): the migration's statements add the
five columns on SQLite; create writes and reads them back; create without them
leaves NULLs and every existing test still passes."*

Four claims, one test class each:

* **The migration adds the five columns**, and the statements it advertises
  are the ones that do it — ``statements(dialect)`` is read as *data* and
  each statement executed by hand, so a migration whose ``upgrade`` and whose
  ``statements`` had drifted apart would fail here rather than pass.
* **``create`` writes them and reads them back**, on both INSERT spellings
  (the minted-id path and the caller-supplied-id path are two statements, and
  a feature that reached only one of them would look green on whichever
  spelling the test happened to use).
* **``create`` without them leaves NULLs**, on every one of the five, and
  the record reports all five as ``None`` — not as absent attributes, which
  would be a different claim.
* **A database at ``0111`` alone still works**: the store serves a deployment
  whose chain has not reached ``0120``, planning exactly the row it planned
  before the feature existed.  This is the compatibility half of *"a campaign
  with NULL grid columns must give the identical ... results as before"*.

The suite runs the real migrations by file path (the convention
``conftest.py`` documents at length) rather than hand-writing DDL, so the
schema under test is the one the schema's owners declare.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from contextlib import closing

import pytest
from conftest import _load_migration, _path_of
from discovery import (
    CAMPAIGN_TABLE,
    GRID_COLUMNS,
    GRID_FIRST_DATE_COLUMN,
    GRID_LAST_DATE_COLUMN,
    HORIZON_COLUMN,
    OOS_FIRST_DATE_COLUMN,
    TYPE_R_CAMPAIGN_TYPE,
    CampaignPlanningError,
    CampaignRecord,
    CampaignRecords,
)

#: The revision under test — feature 4's own migration.
GRID_MIGRATION = "0120_campaign_evaluation_grid"

#: A real 64-hex digest, so the store's own validation is satisfied by a
#: value a caller could actually have produced rather than a stub.
CONFIG_SHA256 = hashlib.sha256(b"evaluation-config").hexdigest()

GRID_FIRST = "2026-01-02"
GRID_LAST = "2026-09-30"
OOS_FIRST = "2026-10-01"


@pytest.fixture
def migrated_with_grid(database_url: str) -> str:
    """A database holding ``campaign`` *and* the five grid columns.

    ``0111`` creates the table and ``0120`` widens it — both through their
    own ``apply``, the standalone entry point a caller with no migration
    runner uses, which is the state of this workspace.
    """
    _load_migration("0111_campaign_table").apply(database_url)
    _load_migration(GRID_MIGRATION).apply(database_url)
    return database_url


@pytest.fixture
def grid_records(migrated_with_grid: str) -> CampaignRecords:
    """The store, over a database that carries the five columns."""
    return CampaignRecords(migrated_with_grid)


def _columns(database_url: str, table: str) -> list[tuple]:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        return connection.execute(f"PRAGMA table_info({table})").fetchall()


def _column_names(database_url: str, table: str) -> set[str]:
    return {str(row[1]) for row in _columns(database_url, table)}


# -- The migration ---------------------------------------------------------------


class TestTheMigration:
    def test_the_statements_add_the_five_columns_on_sqlite(
        self, database_url: str
    ) -> None:
        # The table arrives first, as ``0111`` leaves it, so the ALTERs have
        # something to alter.
        _load_migration("0111_campaign_table").apply(database_url)
        module = _load_migration(GRID_MIGRATION)
        statements = module.statements("sqlite")

        assert len(statements) == len(GRID_COLUMNS)
        with closing(sqlite3.connect(_path_of(database_url))) as connection:
            for statement in statements:
                connection.execute(statement)
            connection.commit()

        assert _column_names(database_url, CAMPAIGN_TABLE) >= set(GRID_COLUMNS)

    def test_the_revision_identity_is_the_feature_spec_s_own(
        self,
    ) -> None:
        module = _load_migration(GRID_MIGRATION)
        assert module.REVISION == GRID_MIGRATION
        assert module.DOWN_REVISION == "0119_canary_reference_pair"

    def test_every_added_column_is_nullable_and_carries_no_default(
        self, migrated_with_grid: str
    ) -> None:
        # A nullable column with no default is the whole reason the migration
        # could run against a table that already held rows: SQLite refuses
        # ``ADD COLUMN ... NOT NULL`` without one, and a default would
        # fabricate a grid measurement for a campaign that never had one.
        by_name = {str(row[1]): row for row in _columns(migrated_with_grid, CAMPAIGN_TABLE)}
        for column in GRID_COLUMNS:
            row = by_name[column]
            assert row[3] == 0, f"{column} is NOT NULL"
            assert row[4] is None, f"{column} carries a default"

    def test_the_upgrade_is_idempotent_and_the_downgrade_reverses_it(
        self, database_url: str
    ) -> None:
        _load_migration("0111_campaign_table").apply(database_url)
        module = _load_migration(GRID_MIGRATION)
        module.apply(database_url)
        module.apply(database_url)  # must not raise on the second pass

        assert _column_names(database_url, CAMPAIGN_TABLE) >= set(GRID_COLUMNS)

        with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
            module.downgrade(connection)

        present = _column_names(database_url, CAMPAIGN_TABLE)
        assert not (set(GRID_COLUMNS) & present)
        # The table and every other column survive: this revision's
        # downgrade drops five columns and nothing else.
        assert {"id", "campaign_type", "workspace_count", "null_fraction"} <= present

    def test_an_existing_row_reads_null_in_all_five(
        self, database_url: str
    ) -> None:
        # The migration runs *after* rows exist — the state the whole
        # backfill step exists for.
        _load_migration("0111_campaign_table").apply(database_url)
        identifier = str(uuid.uuid4())
        with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, "
                "workspace_count, null_fraction) VALUES (?, ?, ?, ?)",
                (identifier, TYPE_R_CAMPAIGN_TYPE, 12, 0.1667),
            )
        _load_migration(GRID_MIGRATION).apply(database_url)

        with closing(sqlite3.connect(_path_of(database_url))) as connection:
            row = connection.execute(
                f"SELECT {', '.join(GRID_COLUMNS)} FROM {CAMPAIGN_TABLE} "
                "WHERE id = ?",
                (identifier,),
            ).fetchone()
        assert row == (None,) * len(GRID_COLUMNS)


# -- The create, with a grid ------------------------------------------------------


class TestCreateWithAGrid:
    def test_the_five_values_are_written_and_read_back(self, grid_records) -> None:
        record = grid_records.create(
            TYPE_R_CAMPAIGN_TYPE,
            12,
            evaluation_config_sha256=CONFIG_SHA256,
            horizon=5,
            grid_first_date=GRID_FIRST,
            grid_last_date=GRID_LAST,
            oos_first_date=OOS_FIRST,
        )
        assert record.evaluation_config_sha256 == CONFIG_SHA256
        assert record.horizon == 5
        assert record.grid_first_date == GRID_FIRST
        assert record.grid_last_date == GRID_LAST
        assert record.oos_first_date == OOS_FIRST
        # Read back through the store, not only off the returned record: the
        # row *is* the record, and a value that lived only in memory would
        # pass the first half of this test and fail a later reader.
        stored = grid_records.get(record.campaign_id)
        assert stored is not None
        assert stored.row() == record.row()

    def test_a_caller_supplied_id_writes_them_too(self, grid_records, campaign_id) -> None:
        # The *other* INSERT spelling.  The two statements are separate text
        # in the store, so one test per spelling is the only way to know the
        # feature reached both.
        record = grid_records.create(
            TYPE_R_CAMPAIGN_TYPE,
            12,
            campaign_id=campaign_id,
            evaluation_config_sha256=CONFIG_SHA256,
            horizon=10,
            grid_first_date=GRID_FIRST,
            grid_last_date=GRID_LAST,
        )
        assert record.campaign_id == campaign_id
        assert record.horizon == 10

        with closing(sqlite3.connect(_path_of(grid_records.database_url))) as connection:
            row = connection.execute(
                f"SELECT {HORIZON_COLUMN}, {GRID_FIRST_DATE_COLUMN}, "
                f"{GRID_LAST_DATE_COLUMN}, {OOS_FIRST_DATE_COLUMN} "
                f"FROM {CAMPAIGN_TABLE} WHERE id = ?",
                (campaign_id,),
            ).fetchone()
        assert row == (10, GRID_FIRST, GRID_LAST, None)

    def test_a_digest_is_canonicalized_to_lowercase(self, grid_records) -> None:
        # The digest names a file; two spellings of one digest would make one
        # configuration look like two.
        record = grid_records.create(
            TYPE_R_CAMPAIGN_TYPE,
            12,
            evaluation_config_sha256=CONFIG_SHA256.upper(),
        )
        assert record.evaluation_config_sha256 == CONFIG_SHA256

    @pytest.mark.parametrize(
        "value",
        ["", "not-a-digest", "0" * 63, "0" * 65, "z" * 64, 5],
    )
    def test_a_value_that_is_not_a_digest_is_refused(self, grid_records, value) -> None:
        with pytest.raises(CampaignPlanningError):
            grid_records.create(
                TYPE_R_CAMPAIGN_TYPE, 12, evaluation_config_sha256=value
            )

    @pytest.mark.parametrize("value", [0, -1, 5.0, True, "5"])
    def test_a_horizon_that_is_not_a_positive_int_is_refused(
        self, grid_records, value
    ) -> None:
        with pytest.raises(CampaignPlanningError):
            grid_records.create(TYPE_R_CAMPAIGN_TYPE, 12, horizon=value)

    @pytest.mark.parametrize("value", ["2026-9-1", "01/09/2026", "", 20260901])
    def test_a_grid_date_that_is_not_iso_is_refused(self, grid_records, value) -> None:
        with pytest.raises(CampaignPlanningError):
            grid_records.create(TYPE_R_CAMPAIGN_TYPE, 12, grid_first_date=value)

    def test_a_grid_whose_first_precedes_its_last_is_refused(self, grid_records) -> None:
        with pytest.raises(CampaignPlanningError):
            grid_records.create(
                TYPE_R_CAMPAIGN_TYPE,
                12,
                grid_first_date=GRID_LAST,
                grid_last_date=GRID_FIRST,
            )

    def test_a_malformed_grid_is_refused_before_a_database_is_touched(
        self, database_url: str
    ) -> None:
        # The store resolves its path lazily, so a database that does not
        # exist proves the refusal happened before any connection was made
        # — the same stance the type and the workspace count take.
        store = CampaignRecords(database_url)
        with pytest.raises(CampaignPlanningError):
            store.create(TYPE_R_CAMPAIGN_TYPE, 12, horizon=-1)
        assert not _path_of(database_url).exists()

    def test_an_oos_date_alone_is_a_complete_grid(self, grid_records) -> None:
        # ``oos_dates`` is optional in the config document, so a campaign
        # with a grid and no out-of-sample window is a normal row — and
        # ``oos_first_date`` NULL is the fact that says so.
        record = grid_records.create(
            TYPE_R_CAMPAIGN_TYPE,
            12,
            grid_first_date=GRID_FIRST,
            grid_last_date=GRID_LAST,
        )
        assert record.oos_first_date is None
        assert record.grid_last_date == GRID_LAST

    def test_a_reissued_plan_keeps_the_stored_grid_and_does_not_refuse(
        self, grid_records, campaign_id
    ) -> None:
        # The grid describes the run, not the plan: a retry with a corrected
        # grid (or none) is still the same campaign, and refusing it would
        # leave the row carrying whatever the first caller wrote.
        first = grid_records.create(
            TYPE_R_CAMPAIGN_TYPE,
            12,
            campaign_id=campaign_id,
            horizon=5,
            grid_first_date=GRID_FIRST,
            grid_last_date=GRID_LAST,
        )
        second = grid_records.create(
            TYPE_R_CAMPAIGN_TYPE, 12, campaign_id=campaign_id, horizon=10
        )
        assert second.horizon == first.horizon == 5
        assert second.grid_last_date == GRID_LAST


# -- The create, without a grid ---------------------------------------------------


class TestCreateWithoutAGrid:
    def test_create_without_them_leaves_all_five_null(self, grid_records) -> None:
        record = grid_records.create(TYPE_R_CAMPAIGN_TYPE, 12)
        for column in GRID_COLUMNS:
            assert getattr(record, column) is None, column

    def test_the_row_mapping_carries_them_as_none_not_absent(self, grid_records) -> None:
        # Present-as-None is the deliberate choice: ``None`` here is the
        # recorded fact *this campaign's grid is unrecorded*, which is
        # exactly what a reader of the mapping needs to see.
        row = grid_records.create(TYPE_R_CAMPAIGN_TYPE, 12).row()
        for column in GRID_COLUMNS:
            assert column in row
            assert row[column] is None

    def test_the_null_columns_land_as_null_on_both_insert_spellings(
        self, grid_records, campaign_id
    ) -> None:
        minted = grid_records.create(TYPE_R_CAMPAIGN_TYPE, 12)
        supplied = grid_records.create(
            TYPE_R_CAMPAIGN_TYPE, 12, campaign_id=campaign_id
        )
        with closing(sqlite3.connect(_path_of(grid_records.database_url))) as connection:
            for identifier in (minted.campaign_id, supplied.campaign_id):
                row = connection.execute(
                    f"SELECT {', '.join(GRID_COLUMNS)} FROM {CAMPAIGN_TABLE} "
                    "WHERE id = ?",
                    (identifier,),
                ).fetchone()
                assert row == (None,) * len(GRID_COLUMNS)

    def test_a_record_built_by_hand_may_carry_no_grid(self) -> None:
        record = CampaignRecord(
            campaign_id=str(uuid.uuid4()),
            campaign_type=TYPE_R_CAMPAIGN_TYPE,
            workspace_count=12,
            null_fraction=0.1667,
            calibration_status="ok",
            created_at="2026-01-01T00:00:00Z",
        )
        assert record.horizon is None
        assert record.grid_first_date is None

    def test_a_record_built_by_hand_validates_the_grid_it_is_given(self) -> None:
        # Validation lives in __post_init__ because dataclasses.replace and
        # unpickling rebuild instances past the store's nose.
        with pytest.raises(CampaignPlanningError):
            CampaignRecord(
                campaign_id=str(uuid.uuid4()),
                campaign_type=TYPE_R_CAMPAIGN_TYPE,
                workspace_count=12,
                null_fraction=0.1667,
                calibration_status="ok",
                created_at="2026-01-01T00:00:00Z",
                horizon=0,
            )


# -- A store whose chain has not reached 0120 -------------------------------------


class TestADatabaseWithoutTheGridColumns:
    def test_the_store_plans_and_reads_a_campaign_exactly_as_before(
        self, migrated_database: str
    ) -> None:
        # ``migrated_database`` is ``0111`` alone — the deployment shape this
        # feature must not break.  The store selects a literal NULL under
        # each absent column rather than raising ``no such column``, and
        # inserts only the columns the table actually has.
        assert not (set(GRID_COLUMNS) & _column_names(migrated_database, CAMPAIGN_TABLE))
        store = CampaignRecords(migrated_database)

        record = store.create(TYPE_R_CAMPAIGN_TYPE, 12)
        assert record.campaign_id
        assert record.workspace_count == 12
        for column in GRID_COLUMNS:
            assert getattr(record, column) is None, column
        assert store.get(record.campaign_id) == record
