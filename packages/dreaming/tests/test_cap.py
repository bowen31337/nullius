"""Feature 277's claim, stated as tests: the revision cap and its record.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 277: *System persists
the revision cap used per cycle, raising M to 40 once the pool holds 50 or
more worlds.*  docs/alpha-engine-prd.md §C5 runs ``M`` revisions per outer
iteration, §12.1's ladder caps them by the pool's size — *"20–50: M capped at
8–10"*, *"50+: full dreaming, M = 30–40"* — and Appendix B's bar reads ``M``
back (``advantage > √(2 ln M) · σ_V / √n_worlds``, feature 280's test).  So
the claims worth pinning are these, and they are what the classes below are
arranged around:

* the schedule is §12.1's ladder in one answer — 10 on the middle rung, 40 at
  50 or more worlds, refused below the floor in feature 275's own word;
* the cap a cycle used is a row in the store, not a fact about the caller's
  memory — one row per cycle, read back as history, retry included;
* the record decides the cap itself (a caller cannot hand one in) and refuses
  a database that holds no pool, before leaving a trace;
* the vocabulary is the cap's own pair of siblings — never feature 270's
  request class for a cap's ask, never its held-pool class for a cap's store.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing

import pytest
from dreaming import (
    CAPPED_SWEEP_CAP,
    CYCLE_CAP_TABLE,
    FULL_DREAMING_CAP,
    FULL_DREAMING_WORLDS,
    CapRecord,
    CapRecordError,
    CapRequestError,
    DreamingError,
    FreezeRequestError,
    PoolFrozenError,
    PoolTooThinError,
    cycle_cap_schema,
    cycle_caps,
    record_cycle_cap,
    revision_cap,
    sqlite_path,
)
from dreaming.ladder import LADDER_FLOOR_WORLDS, POOL_TOO_THIN_CODE


def dt_at(hour: int) -> dt.datetime:
    """An aware instant, fixed so a test's stamps are deterministic."""
    return dt.datetime(2026, 3, 1, hour, 0, 0, tzinfo=dt.UTC)


def _table_exists(url: str, table: str) -> bool:
    """Whether the database at ``url`` holds ``table`` — the shape probe."""
    with closing(sqlite3.connect(sqlite_path(url))) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None


def _row_count(url: str) -> int:
    """How many cap rows the database at ``url`` holds (0 when no table).

    The honest spelling of *nothing was written*: a refused record leaves no
    trace at all, so the table may be absent as well as empty, and both are
    zero rows written.
    """
    if not _table_exists(url, CYCLE_CAP_TABLE):
        return 0
    with closing(sqlite3.connect(sqlite_path(url))) as connection:
        return connection.execute(
            f"SELECT COUNT(*) FROM {CYCLE_CAP_TABLE}"
        ).fetchone()[0]


class TestTheSchedule:
    """The judgment: §12.1's ladder, answered over a count the caller has."""

    def test_the_cap_is_raised_to_forty_at_fifty_worlds(self):
        """Feature 277's own edge: 50 or more worlds runs full dreaming."""
        assert revision_cap(50) == FULL_DREAMING_CAP == 40

    def test_the_boundary_is_exact(self):
        """49 stays on the capped sweep; 50 is the raise — no rung between."""
        assert revision_cap(49) == CAPPED_SWEEP_CAP == 10
        assert revision_cap(50) == FULL_DREAMING_CAP == 40

    def test_the_middle_rung_runs_the_capped_sweep(self):
        """§12.1's 20–50 band: M capped at 8–10, at the 10 feature 276 fixes."""
        for worlds in (20, 21, 30, 49):
            assert revision_cap(worlds) == CAPPED_SWEEP_CAP == 10

    def test_the_top_rung_holds_forty_above_the_boundary(self):
        """Full dreaming keeps the raised cap — there is no higher rung."""
        for worlds in (50, 51, 100, 1000):
            assert revision_cap(worlds) == FULL_DREAMING_CAP == 40

    def test_the_constants_are_the_prd_figures(self):
        """The ladder's own numbers: §12.1's 50, its bar calculation's 40,
        and the band's 8–10 at feature 276's ceiling."""
        assert FULL_DREAMING_WORLDS == 50
        assert FULL_DREAMING_CAP == 40
        assert CAPPED_SWEEP_CAP == 10
        assert LADDER_FLOOR_WORLDS == 20

    def test_a_thin_pool_is_refused_in_the_ladders_own_word(self):
        """The bottom rung is feature 275's refusal, delegated — same word.

        A pool below the floor needs no cap because it may not run, and the
        refusal it meets is the one §12.1's floor already mints, not a second
        spelling of it: the message opens with ``pool_too_thin`` and names
        §12.1.
        """
        with pytest.raises(PoolTooThinError) as refusal:
            revision_cap(19)

        assert str(refusal.value).startswith(POOL_TOO_THIN_CODE)
        assert "§12.1" in str(refusal.value)

    def test_the_judgment_is_pure_over_a_count(self):
        """A verdict is not a count: ints in, int out, no store attached.

        The figure is the pool's size — the count a feature-270 hold records
        as ``world_count`` — passed in rather than read, the same shape the
        ladder floor's judgment takes.
        """
        assert revision_cap(52) == 40
        assert revision_cap(30) == 10
        with pytest.raises(PoolTooThinError):
            revision_cap(3)

    def test_the_boundary_is_a_parameter(self):
        """The raise's edge is §12.1's 50 by default, and settable.

        A deployment that dreams fully only above 60 keeps the capped sweep
        at 50–59 — the boundary is the ladder's own fact, like the floor's
        ``gate``.
        """
        assert revision_cap(50, full_dreaming=60) == 10
        assert revision_cap(59, full_dreaming=60) == 10
        assert revision_cap(60, full_dreaming=60) == 40

    def test_the_floor_passes_through_to_the_ladder(self):
        """One spelling of the bottom rung: the schedule's floor is the
        floor's own keyword, so the two judgments cannot disagree."""
        with pytest.raises(PoolTooThinError):
            revision_cap(29, floor=30)
        assert revision_cap(30, floor=30) == 10
        assert revision_cap(31, floor=30, full_dreaming=31) == 40


class TestTheScheduleInputs:
    """A malformed figure or rung is refused, not answered — the ask's fault."""

    def test_a_bool_figure_is_refused_where_a_count_belongs(self):
        """``True`` is ``1`` in Python, so a flag where a pool size belongs
        would name a pool of one world — refused as a malformed ask rather
        than answered as a thin pool."""
        with pytest.raises(CapRequestError):
            revision_cap(True)

    def test_a_float_figure_is_refused(self):
        """A world count is a whole number; a fraction names no pool."""
        with pytest.raises(CapRequestError):
            revision_cap(49.5)

    def test_a_non_numeric_figure_is_refused(self):
        with pytest.raises(CapRequestError):
            revision_cap("fifty")

    def test_a_negative_figure_is_refused(self):
        with pytest.raises(CapRequestError):
            revision_cap(-1)

    def test_a_malformed_floor_is_refused_in_the_ladders_vocabulary(self):
        """The floor is feature 275's fact, so its malformed shape is refused
        by the ladder's own validation, in the ladder's own class."""
        with pytest.raises(PoolTooThinError):
            revision_cap(30, floor="20")

    def test_a_malformed_boundary_is_refused(self):
        with pytest.raises(CapRequestError):
            revision_cap(30, full_dreaming="50")

    def test_a_bool_boundary_is_refused(self):
        with pytest.raises(CapRequestError):
            revision_cap(30, full_dreaming=True)

    def test_a_negative_boundary_is_refused(self):
        with pytest.raises(CapRequestError):
            revision_cap(30, full_dreaming=-5)

    def test_a_boundary_below_the_floor_erases_the_middle_rung(self):
        """A raise edge under the floor leaves no rung between them, and
        would hand every admissible pool the cap §12.1 reserves for the top
        of the ladder — refused, naming both edges."""
        with pytest.raises(CapRequestError) as refusal:
            revision_cap(25, floor=30, full_dreaming=10)

        message = str(refusal.value)
        assert "10" in message and "30" in message

    def test_a_boundary_at_the_floor_is_a_ladder(self):
        """The degenerate-but-coherent case: floor and boundary equal means
        every admissible pool dreams fully — no rung is erased."""
        assert revision_cap(20, floor=20, full_dreaming=20) == 40


class TestTheRecord:
    """The store's half: one row per cycle, decided by the schedule alone."""

    def test_the_record_answers_the_schedules_cap(self, pool):
        """The row's cap is the ladder's answer over the row's figure."""
        record = record_cycle_cap("cycle-1", 52, database_url=pool)

        assert isinstance(record, CapRecord)
        assert record.revision_cap == FULL_DREAMING_CAP
        assert record.world_count == 52
        assert record.iteration_id == "cycle-1"

    def test_the_middle_rung_records_ten(self, pool):
        record = record_cycle_cap("cycle-1", 30, database_url=pool)

        assert record.revision_cap == CAPPED_SWEEP_CAP

    def test_the_row_is_persisted_and_reads_back_equal(self, pool):
        """The cap is in the store, not the caller's memory: the audit read
        returns the record the write returned."""
        record = record_cycle_cap(
            "cycle-1", 52, database_url=pool, recorded_at=dt_at(12)
        )

        history = cycle_caps(database_url=pool)

        assert history == (record,)

    def test_the_history_is_ordered_oldest_first(self, pool):
        """§12's ordering rule: ``(recorded_at, id)``, so two reads of one
        history return the same sequence."""
        first = record_cycle_cap("cycle-1", 52, database_url=pool, recorded_at=dt_at(10))
        second = record_cycle_cap("cycle-2", 52, database_url=pool, recorded_at=dt_at(11))
        third = record_cycle_cap("cycle-3", 30, database_url=pool, recorded_at=dt_at(12))

        assert cycle_caps(database_url=pool) == (first, second, third)

    def test_a_retry_is_a_new_occurrence_not_an_overwrite(self, pool):
        """A retried cycle is re-decided over the pool as it stands, so it is
        a second row — even inside the same second, where a value-derived id
        would collide on the primary key."""
        first = record_cycle_cap(
            "cycle-1", 52, database_url=pool, recorded_at=dt_at(12)
        )
        second = record_cycle_cap(
            "cycle-1", 30, database_url=pool, recorded_at=dt_at(12)
        )

        assert first.id != second.id
        assert first.revision_cap == 40
        assert second.revision_cap == 10
        assert len(cycle_caps(database_url=pool)) == 2

    def test_the_recorded_instant_is_stamped_to_the_second(self, pool):
        """The member's one stamp shape: UTC, truncated, ``Z``-suffixed —
        the same spelling a hold row carries in the same database."""
        record = record_cycle_cap(
            "cycle-1", 52, database_url=pool, recorded_at=dt_at(12)
        )

        assert record.recorded_at == "2026-03-01T12:00:00Z"
        assert record.recorded == dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=dt.UTC)

    def test_a_default_instant_is_stamped(self, pool):
        """Without ``recorded_at`` the row carries the current UTC instant —
        truncated to the second, so the ordering rule stays textual."""
        before = dt.datetime.now(dt.UTC)
        record = record_cycle_cap("cycle-1", 52, database_url=pool)
        after = dt.datetime.now(dt.UTC)

        assert record.recorded_at.endswith("Z")
        # The stamp is truncated to the second, so the parsed instant may sit
        # up to one second below the clock the test read — never more.
        slack = dt.timedelta(seconds=1)
        assert before - slack <= record.recorded <= after

    def test_the_row_is_the_store_shaped_mapping(self, pool):
        record = record_cycle_cap(
            "cycle-1", 52, database_url=pool, recorded_at=dt_at(12)
        )

        assert record.row() == {
            "id": record.id,
            "iteration_id": "cycle-1",
            "recorded_at": "2026-03-01T12:00:00Z",
            "world_count": 52,
            "revision_cap": 40,
        }

    def test_the_records_cap_agrees_with_the_judgment(self, pool):
        """Schedule and record cannot disagree: for every rung, the row's cap
        is what ``revision_cap`` answers over the row's figure."""
        for figure in (20, 30, 49, 50, 51, 120):
            record = record_cycle_cap(
                f"cycle-{figure}", figure, database_url=pool, recorded_at=dt_at(12)
            )
            assert record.revision_cap == revision_cap(figure)

    def test_the_table_is_created_lazily_by_the_record(self, pool):
        """A pool that has never dreamed holds no ``cycle_cap`` table, and
        the first record — not the composition, not the read of the pool —
        is what creates it."""
        assert not _table_exists(pool, CYCLE_CAP_TABLE)

        record_cycle_cap("cycle-1", 52, database_url=pool)

        assert _table_exists(pool, CYCLE_CAP_TABLE)

    def test_an_untouched_pool_answers_an_empty_history(self, pool):
        """Between a migrated deployment and its first dreaming cycle, the
        audit read is empty rather than refused — the table is created
        lazily by the read itself, as the freeze's own reads are."""
        assert cycle_caps(database_url=pool) == ()

        assert _table_exists(pool, CYCLE_CAP_TABLE)

    def test_the_floor_and_boundary_pass_through_to_the_record(self, pool):
        """A deployment sizing its own ladder records under it."""
        record = record_cycle_cap(
            "cycle-1", 60, floor=20, full_dreaming=60, database_url=pool
        )

        assert record.revision_cap == FULL_DREAMING_CAP


class TestTheRecordRefusals:
    """What the store refuses, and that a refusal leaves no trace."""

    def test_a_thin_figure_is_refused_before_any_database_is_opened(self, pool):
        """The bottom rung is the ladder's: 19 worlds is refused with
        ``pool_too_thin`` and nothing is written."""
        with pytest.raises(PoolTooThinError) as refusal:
            record_cycle_cap("cycle-1", 19, database_url=pool)

        assert str(refusal.value).startswith(POOL_TOO_THIN_CODE)
        assert _row_count(pool) == 0

    def test_a_malformed_iteration_id_is_refused_and_writes_nothing(self, pool):
        with pytest.raises(CapRequestError):
            record_cycle_cap("   ", 52, database_url=pool)

        assert _row_count(pool) == 0

    def test_a_naive_instant_is_refused_in_the_caps_vocabulary(self, pool):
        """The ask's instant is refused by the cap's own class — never by
        feature 270's request class for an act that held nothing."""
        with pytest.raises(CapRequestError) as refusal:
            record_cycle_cap(
                "cycle-1", 52, database_url=pool,
                # The naive instant *is* the refusal's subject.
                recorded_at=dt.datetime(2026, 3, 1, 12, 0, 0),  # noqa: DTZ001
            )

        assert not isinstance(refusal.value, FreezeRequestError)
        assert _row_count(pool) == 0

    def test_no_database_named_is_refused(self):
        """An act that means to write and resolves no store is refused by
        name — a cap "recorded" over no database is a cap the store does not
        hold, and Appendix B's bar would read nothing back."""
        with pytest.raises(CapRequestError) as refusal:
            record_cycle_cap("cycle-1", 52, env={})

        assert "DATABASE_URL" in str(refusal.value)

    def test_an_unspeakable_url_is_refused_in_the_caps_vocabulary(self):
        """A URL this member cannot speak is refused by the cap's class —
        translated at the seam from the one spelling of what a sqlite URL
        names, so the caller never meets the freeze's word."""
        for url in ("postgres://host/db", "sqlite:///:memory:", "sqlite://"):
            with pytest.raises(CapRequestError) as refusal:
                record_cycle_cap("cycle-1", 52, database_url=url)

            assert not isinstance(refusal.value, FreezeRequestError)

    def test_a_database_with_no_pool_is_refused_before_the_table_is_created(
        self, database_url
    ):
        """A cap over a pool that is not there caps nothing: the probe comes
        before the DDL, so the refused record leaves no trace — not even the
        table."""
        with pytest.raises(CapRecordError) as refusal:
            record_cycle_cap("cycle-1", 52, database_url=database_url)

        assert "replay_pool" in str(refusal.value) or "pool" in str(refusal.value)
        assert not _table_exists(database_url, CYCLE_CAP_TABLE)

    def test_the_read_refuses_a_database_with_no_pool(self, database_url):
        """A database without the pool holds no dreaming cycles and so no
        caps — answering ``()`` there would read *no cycle ever dreamed* off
        a store that never could."""
        with pytest.raises(CapRecordError):
            cycle_caps(database_url=database_url)

    def test_a_corrupt_stamp_refuses_in_the_caps_class(self, pool):
        """A row nobody should be able to write (a hand-edited stamp) reads
        back as a refusal in this module's vocabulary — not feature 270's
        held-pool word."""
        record = record_cycle_cap("cycle-1", 52, database_url=pool)
        with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
            connection.execute(
                f"UPDATE {CYCLE_CAP_TABLE} SET recorded_at = 'nonsense' "
                "WHERE id = ?",
                (record.id,),
            )

        (corrupt,) = cycle_caps(database_url=pool)
        with pytest.raises(CapRecordError) as refusal:
            _ = corrupt.recorded

        assert not isinstance(refusal.value, PoolFrozenError)


class TestTheSchema:
    """The table's shape: append-only history, nothing to guard or close."""

    def test_the_schema_names_the_table_and_its_five_columns(self):
        schema = cycle_cap_schema()

        assert f"CREATE TABLE IF NOT EXISTS {CYCLE_CAP_TABLE}" in schema
        for column in (
            "id",
            "iteration_id",
            "recorded_at",
            "world_count",
            "revision_cap",
        ):
            assert column in schema

    def test_the_schema_carries_the_persistence_comment(self):
        """Why the cap is persisted is part of the DDL an operator reads."""
        assert "Appendix B's selection bar reads M" in cycle_cap_schema()

    def test_the_schema_installs_no_guards_and_no_unique_index(self):
        """A cap is a judgment, not a hold: there is no pool write to refuse
        and no window to close, and the history is append-only — so no
        trigger and no uniqueness claim, unlike ``pool_freeze``'s one-open
        index."""
        schema = cycle_cap_schema()

        assert "TRIGGER" not in schema.upper()
        assert "UNIQUE" not in schema.upper()

    def test_the_schema_is_idempotent(self, pool):
        """Every statement is ``IF NOT EXISTS``, so preparing a database this
        member already prepared takes the same path and leaves one table."""
        with closing(sqlite3.connect(sqlite_path(pool))) as connection:
            for _ in range(2):
                connection.executescript(cycle_cap_schema())
            count = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                "AND name = ?",
                (CYCLE_CAP_TABLE,),
            ).fetchone()[0]

        assert count == 1

    def test_the_table_is_the_members_own_not_the_pools(self):
        """``cycle_cap`` is this member's table, spelled beside the pool's
        two and never among them, and never the freeze's either."""
        from dreaming import FREEZE_TABLE, POOL_TABLES

        assert CYCLE_CAP_TABLE not in POOL_TABLES
        assert CYCLE_CAP_TABLE != FREEZE_TABLE


class TestTheVocabulary:
    """The cap's two classes: siblings under the base, borrowing nothing."""

    def test_both_classes_share_one_base(self):
        assert issubclass(CapRequestError, DreamingError)
        assert issubclass(CapRecordError, DreamingError)
        assert issubclass(DreamingError, Exception)

    def test_the_two_classes_are_siblings_of_each_other(self):
        assert not issubclass(CapRequestError, CapRecordError)
        assert not issubclass(CapRecordError, CapRequestError)

    def test_the_classes_borrow_none_of_the_members_existing_three(self):
        """A caller must be able to catch a cap's refusal without catching a
        hold's, a thin pool's, or a malformed freeze ask's — and vice versa."""
        for cap_class in (CapRequestError, CapRecordError):
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
            ):
                assert not issubclass(cap_class, sibling)
                assert not issubclass(sibling, cap_class)

    def test_the_thin_refusal_is_still_the_ladders(self):
        """The one refusal this module mints for a thin pool is feature
        275's, delegated — so ``PoolTooThinError`` is not re-spelled here."""
        import dreaming

        assert dreaming.PoolTooThinError is PoolTooThinError
        with pytest.raises(PoolTooThinError):
            dreaming.record_cycle_cap("cycle-1", 5, env={})
