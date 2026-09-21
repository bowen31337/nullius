"""Feature 232: the campaign record, and the clip behind its headline number.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 232: *System
creates a campaign record capturing type, workspace count and null fraction
before any node is expanded.*  Three things are asserted here, in the order
the feature's own sentence names them — the *fraction* (derived before
anything exists), the *record* (the value that holds the three facts), and the
*create* (the act, with its ordering law).

**The clip is tested against §4.1.1's own worked numbers.**  ``φ =
clip(max(2/W, 0.15), 0.15, 0.35)`` is not monotone across the whole domain — it is
``2/W`` in the middle and flat at either end — so the test that catches a
mis-spelled clip is not "is it between the floor and the ceiling" (a constant
0.2 would pass that) but the three-regime sweep below: a ``W`` small enough to
sit on the ceiling, one in the middle where the arithmetic shows through, and
one large enough to sit on the floor.  §4.1.1 argues the band from the counts
it produces — *"at W = 10 a flat 0.15 yields 1.5 expected nulls, which is too
thin; at W = 32 it yields 5 and is fine"* — and the last test in that section
takes the argument at its word, asserting the expected-null counts the sentence
names.  A clip that returned a plausible constant would fail there.

**The ordering law is tested against the tree, not against a convention.**
Feature 232's clause is *"before any node is expanded"*, and the only honest
evidence of an expansion is a ``node`` row.  The tests below cover all four
states that clause can be in — no ``node`` table at all, an empty one, one
holding rows under *another* campaign, and one holding a row under *this* one —
because the interesting failure is not the obvious refusal but a check that is
too eager (refusing a campaign whose table merely exists, or whose sibling
campaigns have trees) or too lax.

**The row is the record.**  Every read path in this file goes back through the
table: the minted id, ``created_at`` and ``calibration_status`` are asserted
against values the *table* produced, never against the arguments the call was
given.  That is the feature's own claim — the row *is* the creation event —
and it is the claim a store that returned its own arguments would silently
break while looking correct.  The distinctive-``created_at`` test is the
sharpest of them: a row written by another writer, read back through
``create()``, proves the value came off the table rather than from a clock this
call consulted.

Errors are asserted on the class, not on the message text.  The two classes are
this member's own (``discovery.errors``) and reachable by a direct import, so
``pytest.raises`` matches them exactly — the composed/scan-copy wrinkle the
nulloracle integration suite documents does not apply here.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from discovery import (
    CAMPAIGN_TABLE,
    PHI_CEILING,
    PHI_FLOOR,
    REGIMES,
    TYPE_D_CAMPAIGN_TYPE,
    TYPE_R_CAMPAIGN_TYPE,
    CampaignOrderError,
    CampaignPlanningError,
    CampaignRecord,
    CampaignRecords,
    create_campaign,
    null_fraction,
)


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for the raw-SQL staging.

    The same three steps the member's own private ``_sqlite_path`` takes, and
    deliberately local rather than imported: a test reaching into a private
    helper would be pinning an implementation detail it should be free to
    change.  What is being relied on here is not the store's code but
    ``0111``'s URL grammar, which is a fact about the deployment.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


#: §7.3's Type-R fraction and well count, as the plan-gate suite also plans
#: them: ``2/12 = 0.1667``, inside the band, so the middle regime is the one
#: the store is exercised with by default.
TYPE_R_WELLS = 12
TYPE_R_FRACTION = 2.0 / 12.0


def _write_row(
    database_url: str,
    campaign_id: str,
    *,
    campaign_type: str = TYPE_R_CAMPAIGN_TYPE,
    workspace_count: int = TYPE_R_WELLS,
    null_fraction_value: float = TYPE_R_FRACTION,
    created_at: str | None = None,
) -> None:
    """Insert one campaign row with raw SQL, for the states a test must stage.

    The shape ``0111_campaign_table.py`` spells: four named columns and the
    timestamp when the test wants to name it.  ``ks_pvalue`` and
    ``calibration_status`` are left off, so the table's own defaults land —
    which is the state a fresh campaign is in.
    """
    columns = ["id", "campaign_type", "workspace_count", "null_fraction"]
    values: list[object] = [campaign_id, campaign_type, workspace_count, null_fraction_value]
    if created_at is not None:
        columns.append("created_at")
        values.append(created_at)
    placeholders = ", ".join("?" for _ in columns)
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            values,
        )


def _stored_row(database_url: str, campaign_id: str) -> tuple:
    """The whole campaign row as the table holds it, for reading back a column.

    ``SELECT *`` is right *here* — the assertion is about what the table
    holds, so the column order this suite reads must be the table's rather
    than a list this file chose.  ``0111``'s order is ``id, campaign_type,
    workspace_count, null_fraction, calibration_status, ks_pvalue,
    created_at``.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            f"SELECT * FROM {CAMPAIGN_TABLE} WHERE id = ?", (campaign_id,)
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    assert row is not None, f"no campaign row for {campaign_id!r}"
    return row


KS_PVALUE_INDEX = 5
CREATED_AT_INDEX = 6
CALIBRATION_STATUS_INDEX = 4


# -- §4.1.1: the clip ------------------------------------------------------------


class TestTheClip:
    def test_the_band_is_the_prds(self) -> None:
        # §4.1.1 states both ends as literals; they are this member's own
        # constants because no member may import another's.
        assert (PHI_FLOOR, PHI_CEILING) == (0.15, 0.35)
        assert PHI_FLOOR < PHI_CEILING

    def test_the_expression_is_the_prds_term_for_term(self) -> None:
        # §4.1.1 writes "φ = clip( max(2/W, 0.15), 0.15, 0.35 )" — an inner
        # max *and* an outer clip.  The two spellings are numerically
        # indistinguishable (the inner max only engages where 2/W < 0.15, and
        # the outer clip lifts that whole region to the floor anyway), so no
        # behavioural test can tell them apart — which is exactly why the
        # *source* is checked here.  A later reader who saw only
        # ``clip(2/W, …)`` in the docstring could "simplify" the max away and
        # every other test in this file would stay green.
        #
        # Reading the implementation's source rather than its behaviour is a
        # deliberate one-off: this is a transcription-fidelity claim, not a
        # behavioural one, and the PRD's expression is what a reviewer checks.
        import inspect

        source = inspect.getsource(null_fraction)
        # The two bounds are applied in the PRD's order — floor first, then
        # ceiling — over the raw quotient.
        assert "min(max(raw, PHI_FLOOR), PHI_CEILING)" in source
        assert "clip(max(2/W, 0.15), 0.15, 0.35)" in inspect.getdoc(null_fraction)

    def test_the_prd_expression_agrees_with_the_plain_clip_everywhere(self) -> None:
        # And the equivalence itself, asserted rather than assumed: the PRD's
        # spelling and the shorter ``clip(2/W, …)`` give the same answer at
        # every W — including W > 13, where the inner max engages and the
        # outer clip would have covered it anyway.  This is what makes the
        # term-for-term transcription above a matter of fidelity rather than
        # of behaviour.
        for wells in range(1, 500):
            prd = min(max(max(2.0 / wells, PHI_FLOOR), PHI_FLOOR), PHI_CEILING)
            plain = min(max(2.0 / wells, PHI_FLOOR), PHI_CEILING)
            assert prd == plain == null_fraction(wells), wells

    def test_small_workspace_sits_on_the_ceiling(self) -> None:
        # W = 2 gives a raw 1.0 — a fraction that would plant every well as a
        # null — and the clip is what makes it §4.1.1's largest sensible
        # fraction instead.  The ceiling binds for W ≤ 5, which is exactly
        # where 2/W ≥ 0.35; W = 6 is already inside the band.
        assert null_fraction(1) == PHI_CEILING  # raw 2.0
        assert null_fraction(2) == PHI_CEILING  # raw 1.0
        assert null_fraction(5) == PHI_CEILING  # raw 0.4
        assert 2 / 5 >= PHI_CEILING > 2 / 6

    def test_the_middle_regime_is_the_arithmetic_itself(self) -> None:
        # Between the ends the clip does nothing and 2/W shows through — the
        # only regime where a plausible constant would be caught.
        assert PHI_FLOOR < 2 / 7 < PHI_CEILING
        assert null_fraction(7) == pytest.approx(2 / 7)
        assert null_fraction(TYPE_R_WELLS) == pytest.approx(TYPE_R_FRACTION)
        assert null_fraction(13) == pytest.approx(2 / 13)  # 0.1538, just inside

    def test_large_workspace_is_lifted_to_the_floor(self) -> None:
        # A campaign large enough that 2/W falls under 0.15 is held at the
        # floor — §4.1.1's "floor problem, not a rate problem".
        assert null_fraction(14) == PHI_FLOOR  # raw 0.1428…
        assert null_fraction(32) == PHI_FLOOR
        assert null_fraction(1000) == PHI_FLOOR

    def test_the_fraction_is_never_outside_the_band(self) -> None:
        # Swept rather than sampled: the clip's whole contract is the range,
        # and a branch that forgot one end would show up in a sweep.
        for wells in range(1, 200):
            fraction = null_fraction(wells)
            assert PHI_FLOOR <= fraction <= PHI_CEILING, (wells, fraction)

    def test_the_expected_null_counts_of_the_prds_own_argument(self) -> None:
        # §4.1.1 argues the floor from the counts it produces: "at W = 10 a
        # flat 0.15 yields 1.5 expected nulls, which is too thin; at W = 32 it
        # yields 5 and is fine".  The sentence's subject is the *floor*, so
        # the claim to check is the one it makes about a flat 0.15 — the
        # product PHI_FLOOR·W, which is what a deployment that skipped the
        # clip's upper arm would plant.  (W = 10 is not itself in the floor
        # regime: the clip answers 2/10 = 0.2 there, i.e. 2.0 nulls, which is
        # why the floor's thinness is argued at the *large* end.)
        assert PHI_FLOOR * 10 == pytest.approx(1.5)
        assert PHI_FLOOR * 32 == pytest.approx(4.8)
        assert null_fraction(32) * 32 == pytest.approx(4.8)  # the clip at W = 32
        # And the floor is what the clip actually answers from W = 14 up, so
        # the two agree exactly where the argument is made about real runs.
        assert null_fraction(32) == PHI_FLOOR
        assert null_fraction(10) * 10 == pytest.approx(2.0)  # the clip's own W = 10

    def test_a_small_workspace_still_plants_the_two_roots_the_prd_asks_for(
        self,
    ) -> None:
        # §4.1.1's premise — "a tree needs at least two null roots and two
        # real roots" — read as a property of the clip across the ceiling
        # regime: from W = 6 up, a third of the wells is at least two, and
        # two real roots remain at every W the clip answers the ceiling for.
        for wells in (6, 8, 10, 12):
            assert null_fraction(wells) * wells >= 2.0, wells
            assert (1 - null_fraction(wells)) * wells >= 2.0, wells

    @pytest.mark.parametrize(
        "bad", [0, -1, -12, True, False, 2.5, "12", None, [12], 12.0]
    )
    def test_a_workspace_count_that_is_not_a_count_is_refused(self, bad) -> None:
        # True and False are refused *first* among the integers and named
        # separately from 1 and 0 in the message: a truthy-looking True would
        # plan a full campaign from a value that means "yes".
        with pytest.raises(CampaignPlanningError):
            null_fraction(bad)

    def test_one_well_is_a_count(self) -> None:
        # W = 1 is the boundary the refusal does *not* take: it is a
        # (degenerate) positive count, and the clip answers the ceiling for
        # it.  Pinned so a later tightening of the guard is a deliberate act.
        assert null_fraction(1) == PHI_CEILING


# -- The record ------------------------------------------------------------------


class TestTheRecord:
    def test_a_record_carries_the_features_three_facts(self, records) -> None:
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert record.campaign_type == TYPE_R_CAMPAIGN_TYPE
        assert record.workspace_count == TYPE_R_WELLS
        assert record.null_fraction == pytest.approx(TYPE_R_FRACTION)
        # And the three the table carries beside them, read back rather than
        # invented: the row is the creation event.
        assert uuid.UUID(record.campaign_id)
        assert record.calibration_status == "ok"
        assert isinstance(record.created_at, str) and record.created_at

    def test_the_expected_null_count_is_derived_not_stored(self, records) -> None:
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert record.planted_nulls == pytest.approx(TYPE_R_FRACTION * TYPE_R_WELLS)

    def test_the_row_mapping_names_the_columns(self, records) -> None:
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        row = record.row()
        assert row["id"] == record.campaign_id
        assert row["campaign_type"] == TYPE_R_CAMPAIGN_TYPE
        assert row["workspace_count"] == TYPE_R_WELLS
        assert row["null_fraction"] == pytest.approx(TYPE_R_FRACTION)
        assert row["calibration_status"] == "ok"
        assert row["created_at"] == record.created_at
        # ks_pvalue is absent, not None: the planner has no opinion about a
        # number the guard has not read.
        assert "ks_pvalue" not in row

    def test_a_record_is_frozen(self, records) -> None:
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        with pytest.raises(FrozenInstanceError):
            record.campaign_type = TYPE_D_CAMPAIGN_TYPE  # type: ignore[misc]

    def test_the_row_mapping_is_a_fresh_dict_each_time(self, records) -> None:
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        first, second = record.row(), record.row()
        assert first == second
        first["campaign_type"] = "tampered"
        assert record.row()["campaign_type"] == TYPE_R_CAMPAIGN_TYPE

    def test_a_record_cannot_hold_a_declaration_that_is_not_a_regime(self) -> None:
        # Validated in __post_init__, so the refusal holds for a record built
        # by hand as well as one that came through the store — dataclasses
        # .replace and unpickling both rebuild instances past a factory.
        with pytest.raises(CampaignPlanningError):
            CampaignRecord(
                campaign_id=str(uuid.uuid4()),
                campaign_type="Type R",
                workspace_count=12,
                null_fraction=0.1667,
                calibration_status="ok",
                created_at="2024-01-01T00:00:00Z",
            )

    @pytest.mark.parametrize("stored", [0.0, 1.0, -0.1, 1.5, 0, True])
    def test_a_record_cannot_hold_a_number_that_is_not_a_fraction(self, stored) -> None:
        with pytest.raises(CampaignPlanningError):
            CampaignRecord(
                campaign_id=str(uuid.uuid4()),
                campaign_type=TYPE_R_CAMPAIGN_TYPE,
                workspace_count=12,
                null_fraction=stored,
                calibration_status="ok",
                created_at="2024-01-01T00:00:00Z",
            )

    def test_a_record_may_hold_a_fraction_outside_the_band_but_inside_the_interval(
        self,
    ) -> None:
        # The record's bound is (0, 1), deliberately *not* §4.1.1's band: the
        # band is feature 117's and 0111 declares no CHECK, so a planner that
        # refused a stored 0.10 would be tightening a schema it does not own.
        record = CampaignRecord(
            campaign_id=str(uuid.uuid4()),
            campaign_type=TYPE_D_CAMPAIGN_TYPE,
            workspace_count=12,
            null_fraction=0.10,
            calibration_status="ok",
            created_at="2024-01-01T00:00:00Z",
        )
        assert record.null_fraction == 0.10

    def test_a_record_may_carry_a_status_the_planner_did_not_write(self) -> None:
        # Feature 124's verdict advances the column to 'VOID'; a record read
        # back must be able to say so, and the planner must not be the second
        # place that word is spelled.
        record = CampaignRecord(
            campaign_id=str(uuid.uuid4()),
            campaign_type=TYPE_R_CAMPAIGN_TYPE,
            workspace_count=12,
            null_fraction=0.1667,
            calibration_status="VOID",
            created_at="2024-01-01T00:00:00Z",
        )
        assert record.calibration_status == "VOID"

    def test_a_record_cannot_hold_the_write_paths_minted_it(self) -> None:
        # None is the *ask's* "let the table mint it"; no stored row holds it,
        # so a record carrying one is not a row this feature could have read.
        with pytest.raises(CampaignPlanningError):
            CampaignRecord(
                campaign_id=None,  # type: ignore[arg-type]
                campaign_type=TYPE_R_CAMPAIGN_TYPE,

                workspace_count=12,
                null_fraction=0.1667,
                calibration_status="ok",
                created_at="2024-01-01T00:00:00Z",
            )

    def test_an_id_is_canonicalized(self, records) -> None:
        # A mixed-case key would make one campaign look like two: the id joins
        # node.campaign_id and every reader of the row.
        identifier = uuid.uuid4()
        record = records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=str(identifier).upper()
        )
        assert record.campaign_id == str(identifier)


# -- The create ------------------------------------------------------------------


class TestTheCreate:
    def test_the_three_facts_land_in_the_row(
        self, records, migrated_database: str
    ) -> None:
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        row = _stored_row(migrated_database, record.campaign_id)
        assert row[1] == TYPE_R_CAMPAIGN_TYPE
        assert row[2] == TYPE_R_WELLS
        assert row[3] == pytest.approx(TYPE_R_FRACTION)

    def test_a_fresh_campaign_is_calibrated_and_unread(
        self, records, migrated_database: str
    ) -> None:
        # The two columns this feature deliberately does not name: the status
        # takes the table's 'ok' (a freshly created campaign is calibrated by
        # construction, before the KS guard has read it) and the p-value is
        # NULL (a NOT NULL there would fabricate a decisive read).
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        row = _stored_row(migrated_database, record.campaign_id)
        assert row[CALIBRATION_STATUS_INDEX] == "ok"
        assert row[KS_PVALUE_INDEX] is None

    def test_the_id_is_minted_by_the_table_when_the_caller_names_none(
        self, records, migrated_database: str
    ) -> None:
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        # A v4 UUID, and the *stored* one — not a value this call made up.
        parsed = uuid.UUID(record.campaign_id)
        assert parsed.version == 4
        assert record.campaign_id == _stored_row(migrated_database, record.campaign_id)[0]

    def test_two_campaigns_minted_in_one_database_are_two_campaigns(
        self, records
    ) -> None:
        first = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        second = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert first.campaign_id != second.campaign_id

    def test_a_caller_supplied_id_is_what_lands(self, records, campaign_id) -> None:
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id)
        assert record.campaign_id == campaign_id
        assert records.get(campaign_id) is not None

    def test_the_timestamp_comes_off_the_table_not_from_this_call(
        self, records, migrated_database: str, campaign_id
    ) -> None:
        # The sharpest read-back test: a row written by another writer, with a
        # timestamp no clock of this call's could have produced, read back
        # through create().  A store that stamped its own instant would pass
        # every other test in this file and fail this one.
        planted = "1999-12-31T23:59:59.000Z"
        _write_row(migrated_database, campaign_id, created_at=planted)
        record = records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
        )
        assert record.created_at == planted

    def test_a_malformed_id_is_refused_before_any_write(
        self, records, migrated_database: str
    ) -> None:
        with pytest.raises(CampaignPlanningError):
            records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id="not-a-uuid")
        assert _campaign_rows(migrated_database) == 0

    @pytest.mark.parametrize("bad", ["Type R", "type-r", "TYPER", "R", "", None, 7])
    def test_a_declaration_that_is_not_a_regime_is_refused(self, records, bad) -> None:
        with pytest.raises(CampaignPlanningError):
            records.create(bad, TYPE_R_WELLS)

    def test_both_regimes_are_accepted(self, records) -> None:
        assert records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS).campaign_type == (
            TYPE_R_CAMPAIGN_TYPE
        )
        assert records.create(TYPE_D_CAMPAIGN_TYPE, TYPE_R_WELLS).campaign_type == (
            TYPE_D_CAMPAIGN_TYPE
        )
        assert set(REGIMES) == {TYPE_R_CAMPAIGN_TYPE, TYPE_D_CAMPAIGN_TYPE}

    def test_a_malformed_plan_writes_nothing(self, records, migrated_database: str) -> None:
        # Validation happens before anything is opened, so a refused ask leaves
        # no trace at all — the property that makes "the record is the creation
        # event" hold even for calls that fail.
        for bad_wells in (0, -3, True, 1.5):
            with pytest.raises(CampaignPlanningError):
                records.create(TYPE_R_CAMPAIGN_TYPE, bad_wells)
        assert _campaign_rows(migrated_database) == 0

    def test_an_unmigrated_database_is_named_rather_than_given_a_table(
        self, database_url: str
    ) -> None:
        # This store is the *writer*, and the one thing a writer must not do is
        # invent the schema it writes into: 0111 owns the column list, the
        # defaults and the NOT NULLs.  So the failure an unmigrated deployment
        # gets is SQLite's own, naming the table — instead of a table this
        # member guessed at, which would let a campaign land in a schema
        # nobody declared.
        with pytest.raises(sqlite3.OperationalError, match=CAMPAIGN_TABLE):
            CampaignRecords(database_url).create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)

    def test_composing_a_store_writes_nothing(self, migrated_database: str) -> None:
        before = _campaign_rows(migrated_database)
        CampaignRecords(migrated_database)
        assert _campaign_rows(migrated_database) == before


# -- Feature 232's ordering law --------------------------------------------------


class TestTheOrderingLaw:
    def test_the_record_is_created_before_any_node_exists(
        self, tree_records, migrated_with_tree: str
    ) -> None:
        # The satisfied case, and the one the feature is *for*: a campaign
        # created into a database whose tree is empty.
        record = tree_records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert _node_rows(migrated_with_tree, record.campaign_id) == 0
        assert tree_records.get(record.campaign_id) is not None

    def test_a_campaign_whose_tree_is_growing_is_refused(
        self, tree_records, migrated_with_tree: str, campaign_id, plant_root
    ) -> None:
        plant_root(campaign_id)
        with pytest.raises(CampaignOrderError) as raised:
            tree_records.create(
                TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
            )
        # The refusal names the campaign and the count, because the repair is
        # "re-plan under a fresh id" and an operator has to know which tree is
        # in the way.
        assert campaign_id in str(raised.value)
        assert _campaign_rows(migrated_with_tree) == 0

    def test_the_refusal_counts_the_nodes(
        self, tree_records, campaign_id, plant_root
    ) -> None:
        plant_root(campaign_id)
        plant_root(campaign_id, depth=1)
        plant_root(campaign_id, depth=2)
        with pytest.raises(CampaignOrderError) as raised:
            tree_records.create(
                TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
            )
        assert "3 nodes" in str(raised.value)

    def test_a_sibling_campaigns_tree_does_not_block_this_one(
        self, tree_records, campaign_id, plant_root
    ) -> None:
        # The check is scoped to *this* campaign.  A planner that refused
        # whenever the node table was non-empty would refuse the second
        # campaign of every deployment — and §7's whole design runs many
        # campaigns against one store.
        other = str(uuid.uuid4())
        plant_root(other)
        plant_root(other, depth=1)
        record = tree_records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
        )
        assert record.campaign_id == campaign_id

    def test_an_absent_node_table_is_not_a_refusal(
        self, records, migrated_database: str
    ) -> None:
        # A store that has never held a node is one where nothing has been
        # expanded — exactly the state feature 232 wants a campaign created
        # in.  The probe is read-only, so asking the question must not bring
        # the tree table into being: this member does not own its schema.
        record = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert record.campaign_id
        assert not _table_exists(migrated_database, "node")

    def test_an_empty_node_table_is_not_a_refusal(self, tree_records) -> None:
        record = tree_records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert record.campaign_id

    def test_a_node_table_without_the_column_the_probe_reads_fails_loudly(
        self, migrated_database: str, campaign_id
    ) -> None:
        # A `node` table that exists but is not *this* tree's — some other
        # deployment's, or a stale revision of feature 97's — has no
        # ``campaign_id`` for the ordering question to be asked of.  The store
        # must fail loudly and name the missing column, and must not degrade
        # to "assume nothing was expanded": silently treating an unreadable
        # tree as an empty one would create a campaign over a tree that may
        # well be growing, which is the exact state feature 232's clause
        # exists to make impossible.
        #
        # The explicit ``campaign_id`` is what makes the probe run at all.  A
        # minted id skips the check by construction (a fresh UUID is in no
        # tree), so a test without one would pass here vacuously — a trap this
        # suite fell into once, which is why the case is pinned.
        _create_node_table_without_campaign_id(migrated_database)
        with pytest.raises(sqlite3.OperationalError, match="campaign_id"):
            tree_records_over(migrated_database).create(
                TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
            )
        # And the refused call left nothing behind: the probe and the INSERT
        # share one transaction, so a failed check rolls the whole unit back.
        assert _campaign_rows(migrated_database) == 0

    def test_a_minted_id_never_asks_the_tree(
        self, tree_records, migrated_with_tree: str, plant_root
    ) -> None:
        # A minted id is a fresh v4 UUID, so no node can carry it — the tree
        # the check would be asking about does not exist yet.  Pinned by
        # planting nodes under *every* campaign this test knows about and
        # minting a new one anyway; the check is vacuous by construction, not
        # by convenience, and this is the construction.
        for _ in range(3):
            plant_root(str(uuid.uuid4()))
        assert _total_node_rows(migrated_with_tree) == 3
        assert tree_records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS).campaign_id

    def test_the_check_and_the_insert_are_one_transaction(
        self, tree_records, campaign_id, plant_root
    ) -> None:
        # The window is *closed* rather than narrowed: the probe and the INSERT
        # share a transaction, so a node expanded between them cannot slip past.
        # Asserted by outcome — the refusal left the database untouched, and a
        # node planted after the check still blocks the retry.
        plant_root(campaign_id)
        with pytest.raises(CampaignOrderError):
            tree_records.create(
                TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
            )
        plant_root(campaign_id, depth=1)
        with pytest.raises(CampaignOrderError):
            tree_records.create(
                TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
            )


# -- Idempotence -----------------------------------------------------------------


class TestReIssuingAPlan:
    def test_the_identical_plan_returns_the_stored_record(self, records) -> None:
        first = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        second = records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=first.campaign_id
        )
        assert second == first

    def test_a_retry_does_not_move_the_creation_instant(self, records, campaign_id) -> None:
        # The row *is* the creation event.  A retry is the same planning call
        # arriving twice, and it did not move the moment the campaign began.
        first = records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
        )
        second = records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
        )
        assert second.created_at == first.created_at

    def test_a_retry_of_a_minted_campaign_creates_a_second_one(
        self, records, migrated_database: str
    ) -> None:
        # Nothing identifies a minted campaign to a caller that did not keep
        # the id, so a second call with no id is a second campaign — not a
        # duplicate-suppression this store has no key to perform.
        records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert _campaign_rows(migrated_database) == 2

    def test_a_disagreeing_regime_is_refused(self, records, campaign_id) -> None:
        records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id)
        with pytest.raises(CampaignOrderError) as raised:
            records.create(TYPE_D_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id)
        # Both values are named: "you asked for Type-D, the row says Type-R" is
        # actionable in a way that "the plan disagrees" is not.
        assert TYPE_D_CAMPAIGN_TYPE in str(raised.value)
        assert TYPE_R_CAMPAIGN_TYPE in str(raised.value)

    def test_a_disagreeing_workspace_count_is_refused(self, records, campaign_id) -> None:
        records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id)
        with pytest.raises(CampaignOrderError) as raised:
            records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS + 8, campaign_id=campaign_id)
        assert "workspace_count" in str(raised.value)

    def test_a_disagreement_is_not_an_update(
        self, records, campaign_id, migrated_database: str
    ) -> None:
        # §7.3 fixes a campaign's regime and §4.1.1 its W at planning time, so
        # a second declaration naming different ones is two campaigns wearing
        # one id — and the row must be exactly as the first call left it.
        first = records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
        )
        with pytest.raises(CampaignOrderError):
            records.create(TYPE_D_CAMPAIGN_TYPE, 20, campaign_id=campaign_id)
        row = _stored_row(migrated_database, campaign_id)
        assert row[1] == TYPE_R_CAMPAIGN_TYPE
        assert row[2] == TYPE_R_WELLS
        assert records.get(campaign_id) == first

    def test_a_stored_fraction_that_is_not_this_arithmetic_is_named(
        self, records, migrated_database: str, campaign_id
    ) -> None:
        # The count is right and the fraction is not: 0111's own words are
        # "the value that lands here is the planner's, already clipped", so a
        # mismatch with an equal count means the row was written by something
        # else — worth naming separately rather than folding into the count's
        # comparison, which is exactly what the elif does.
        _write_row(migrated_database, campaign_id, null_fraction_value=0.20)
        with pytest.raises(CampaignOrderError) as raised:
            records.create(
                TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
            )
        assert "null_fraction" in str(raised.value)

    def test_a_retry_of_an_already_expanded_campaign_is_not_re_refused(
        self, tree_records, campaign_id, plant_root
    ) -> None:
        # The asymmetry, and why it is deliberate: where a record already
        # exists the ordering law was settled in the past, and re-refusing a
        # retry would punish the retry without changing any fact about the
        # world.  A node planted *after* a campaign was correctly created must
        # not make the campaign un-read.
        planted = tree_records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
        )
        plant_root(campaign_id)
        again = tree_records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
        )
        assert again == planted

    def test_a_voided_calibration_is_not_resurrected(
        self, records, migrated_database: str, campaign_id
    ) -> None:
        # Feature 124's verdict advances the status; a re-run of the *planner*
        # must not write it back to 'ok'.
        records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id)
        with closing(sqlite3.connect(_path_of(migrated_database))) as connection, connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET calibration_status = 'VOID' WHERE id = ?",
                (campaign_id,),
            )
        again = records.create(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id
        )
        assert again.calibration_status == "VOID"

    def test_the_read_back_row_survives_being_refused_a_re_plan(
        self, records, campaign_id
    ) -> None:
        records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id)
        with pytest.raises(CampaignOrderError):
            records.create(TYPE_R_CAMPAIGN_TYPE, 99, campaign_id=campaign_id)
        assert records.get(campaign_id).workspace_count == TYPE_R_WELLS


# -- Reading one back ------------------------------------------------------------


class TestTheGet:
    def test_a_planned_campaign_is_readable(self, records) -> None:
        created = records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert records.get(created.campaign_id) == created

    def test_an_unplanned_campaign_is_none(self, records) -> None:
        # None means *the campaign was never planned* — not that the read
        # failed.  A caller must be able to tell the two apart, which is why
        # an unreachable store raises instead.
        assert records.get(str(uuid.uuid4())) is None

    def test_a_corrupt_row_is_refused_by_name(self, records, migrated_database, campaign_id) -> None:
        # A fraction at either end is not a fraction — §4.1.1's own premise is
        # that a tree needs at least two null roots and two real roots — and
        # the refusal names the campaign it came off rather than only the
        # number that was wrong.
        _write_row(migrated_database, campaign_id, null_fraction_value=1.0)
        with pytest.raises(CampaignPlanningError) as raised:
            records.get(campaign_id)
        assert campaign_id in str(raised.value)

    def test_an_unknown_regime_in_the_row_is_refused(self, records, migrated_database, campaign_id) -> None:
        _write_row(migrated_database, campaign_id, campaign_type="Type-X")
        with pytest.raises(CampaignPlanningError):
            records.get(campaign_id)

    def test_an_id_is_canonicalized_on_the_read_too(self, records, campaign_id) -> None:
        records.create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, campaign_id=campaign_id)
        assert records.get(campaign_id.upper()) is not None

    def test_reading_without_an_id_is_refused(self, records) -> None:
        # None is the *write* path's "let the table mint it" and names no row.
        with pytest.raises(CampaignPlanningError):
            records.get(None)

    def test_a_malformed_id_is_refused(self, records) -> None:
        with pytest.raises(CampaignPlanningError):
            records.get("nope")


# -- The module-level spelling ---------------------------------------------------


class TestTheModuleLevelCall:
    def test_the_environment_names_the_store(self, migrated_database: str, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", migrated_database)
        record = create_campaign(TYPE_D_CAMPAIGN_TYPE, 20)
        assert record.campaign_type == TYPE_D_CAMPAIGN_TYPE
        assert record.workspace_count == 20
        assert CampaignRecords(migrated_database).get(record.campaign_id) == record

    def test_an_explicit_url_wins_over_the_environment(
        self, migrated_database: str, monkeypatch
    ) -> None:
        # The argument is the caller's own deployment fact; the environment is
        # what a process inherits.
        monkeypatch.setenv("DATABASE_URL", "sqlite:///does-not-exist.db")
        record = create_campaign(
            TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS, database_url=migrated_database
        )
        assert CampaignRecords(migrated_database).get(record.campaign_id) is not None

    def test_nothing_naming_a_store_is_refused_by_name(self, monkeypatch) -> None:
        # A planning call that quietly skipped its write would leave the
        # orchestrator expanding a tree whose campaign does not exist — and
        # every node of it would be refused by the seven readers that join
        # this row.  So the missing store is a refusal, not a no-op.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(CampaignPlanningError) as raised:
            create_campaign(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)
        assert "DATABASE_URL" in str(raised.value)

    def test_an_empty_environment_value_counts_as_unset(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "   ")
        with pytest.raises(CampaignPlanningError):
            create_campaign(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)

    def test_a_url_the_store_cannot_speak_is_refused(self) -> None:
        # The spec's single-machine allowance is what a stdlib store can speak.
        with pytest.raises(CampaignPlanningError):
            CampaignRecords("postgresql://localhost/nullius").create(
                TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS
            )

    def test_an_in_memory_url_is_refused(self) -> None:
        # A record must outlive the planning call: the tree's nodes, the KS
        # guard's p-value and the replay pool's census all join this row from
        # another process.
        with pytest.raises(CampaignPlanningError):
            CampaignRecords("sqlite://").create(TYPE_R_CAMPAIGN_TYPE, TYPE_R_WELLS)

    def test_a_store_with_no_url_is_refused(self) -> None:
        for bad in ("", "   "):
            with pytest.raises(CampaignPlanningError):
                CampaignRecords(bad)


# -- helpers ---------------------------------------------------------------------


def tree_records_over(database_url: str) -> CampaignRecords:
    """A store over a database a test has staged by hand.

    The ``tree_records`` fixture builds its store over the *fixture's* URL; a
    test that stages its own schema (a node table shaped wrongly, say) needs a
    store pointed at that same database, which is all this is.
    """
    return CampaignRecords(database_url)


def _create_node_table_without_campaign_id(database_url: str) -> None:
    """A ``node`` table missing the one column the ordering probe reads.

    Not ``0118``'s DDL — deliberately, because the case under test is a tree
    table that is *not* the one feature 97 declares.  Two columns are enough
    for the table to exist and for the probe to find it; the third, which the
    probe's ``WHERE`` clause needs, is what is absent.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute("CREATE TABLE node (id TEXT, parent_id TEXT)")


def _campaign_rows(database_url: str) -> int:
    return _count(database_url, CAMPAIGN_TABLE)


def _node_rows(database_url: str, campaign_id: str) -> int:
    if not _table_exists(database_url, "node"):
        return 0
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            "SELECT COUNT(*) FROM node WHERE campaign_id = ?", (campaign_id,)
        )
        try:
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()


def _total_node_rows(database_url: str) -> int:
    return _count(database_url, "node")


def _count(database_url: str, table: str) -> int:
    if not _table_exists(database_url, table):
        return 0
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(f"SELECT COUNT(*) FROM {table}")
        try:
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()


def _table_exists(database_url: str, table: str) -> bool:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        )
        try:
            return cursor.fetchone() is not None
        finally:
            cursor.close()
