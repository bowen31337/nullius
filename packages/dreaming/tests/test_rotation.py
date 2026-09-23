"""Feature 279's claim, stated as tests: the holdout rotates, and is recorded.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 279: *System rotates
the holdout split every cycle, persisting which worlds were held out per
iteration.*  docs/alpha-engine-prd.md §12.1 puts the rotation on the ladder's
top rung — *"50+: Full dreaming, ``M = 30–40``, 70/30 train/holdout split on
worlds, holdout rotated each cycle"* — and the section's risk table names the
failure the rotation mitigates: *"Dreaming overfits the pool … rotate the
70/30 split; block dreaming below 20 worlds."*

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* **the rotation is the cycle's own name** — the identity over the validated
  id, deterministic and recomputable, so the split a caller takes directly
  during a cycle and the split this member records for it are *one* split,
  not two that merely agree;
* **the holdout moves with the cycle** — different cycles answer different
  holdout halves, and across enough cycles every world is held out sometimes
  and selected on sometimes: no world is the grader forever, none the graded
  forever, which is what makes the M3 exit criterion's *"evaluated on worlds
  held out of the dreaming loop"* a claim about transfer rather than about
  tenancy;
* **the record persists which worlds were held out** — one row per cycle
  occurrence, carrying the holdout half in the split's own rank order beside
  the pool's size and the exact share, readable back without re-running the
  split, with a retried cycle re-decided over the pool as it stands;
* **the record is decided here, not accepted** — there is no spelling of the
  call that hands worlds in, so a record can never disagree with the split;
* **the refusals are the rotation's own pair**, ask and store, with the thin
  pool delegated to feature 275's judgment in the floor's own word — and
  refused before the table is created, so a refused record leaves no trace.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path

import pytest
from dreaming import (
    CYCLE_CAP_TABLE,
    CYCLE_HOLDOUT_TABLE,
    DATABASE_URL_ENV,
    FREEZE_CODE,
    FREEZE_TABLE,
    POOL_TABLES,
    POOL_TOO_THIN_CODE,
    TRAIN_FRACTION,
    DreamingError,
    FreezeRequestError,
    HoldoutRecord,
    HoldoutRecordError,
    HoldoutRequestError,
    PoolFrozenError,
    PoolTooThinError,
    SplitRequestError,
    SplitStoreError,
    cycle_holdout_schema,
    cycle_holdouts,
    cycle_rotation,
    pool_bootstrap_schema,
    record_cycle_holdout,
    split_replay_pool,
    sqlite_path,
)


def dt_at(hour: int) -> dt.datetime:
    """An aware instant on a fixed day, deterministic per hour."""
    return dt.datetime(2026, 3, 1, hour, 0, 0, tzinfo=dt.UTC)


def dt_now() -> dt.datetime:
    """The suite's default stamp — the same spelling the cap's suite uses."""
    return dt_at(12)


def _table_exists(url: str, table: str) -> bool:
    """Whether the store at ``url`` holds the named table — the lazy-DDL probe."""
    with closing(sqlite3.connect(sqlite_path(url))) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", table),
        ).fetchone()
    return bool(row[0])


def _row_count(url: str, table: str = CYCLE_HOLDOUT_TABLE) -> int:
    """How many rows the record table holds — the history's own figure."""
    with closing(sqlite3.connect(sqlite_path(url))) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _add_worlds(url: str, count: int, *, start: int = 0) -> None:
    """Author ``count`` more worlds into the pool — the grown-pool retry's act."""
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        for index in range(start, start + count):
            connection.execute(
                "INSERT INTO bootstrap_world (world_id, label) VALUES (?, ?)",
                (f"world-{index:03d}", f"label-{index}"),
            )


class TestTheRotation:
    """§12.1's *"holdout rotated each cycle"* — the law that names the rotation."""

    def test_a_cycles_rotation_is_its_own_name(self):
        """The identity, over the member's one iteration rule.

        ``cycle_rotation`` answers the validated id verbatim — no counter, no
        digest of one — so *the split of cycle N* is recomputable from the
        cycle's name alone, and the row that records it carries its own
        rotation in its ``iteration_id`` already.
        """
        for name in ("cycle-1", "iter/2026-03-01", "outer-7"):
            assert cycle_rotation(name) == name

    def test_the_name_is_stripped_as_the_member_strips_it(self):
        """Surrounding whitespace is not part of a cycle's name.

        The member's one iteration rule strips, and the rotation is that rule
        answered — so ``' cycle-7 '`` and ``'cycle-7'`` are one rotation, and
        a row recorded for either names the one cycle.
        """
        assert cycle_rotation("  cycle-7\n") == "cycle-7"
        assert cycle_rotation("cycle-7 ") == cycle_rotation("cycle-7")

    def test_the_same_cycle_answers_the_same_rotation_in_any_process(self):
        """§12's determinism contract, restated for a partition.

        No clock, no counter, no store read — the rotation of a named cycle
        is a fact about the name, so two processes that agree on the name
        agree on the split.
        """
        assert cycle_rotation("cycle-7") == cycle_rotation("cycle-7")

    def test_a_malformed_id_is_refused_in_this_modules_vocabulary(self):
        """Translated at the seam — never feature 270's word.

        A caller that asked for a cycle's rotation and caught the freeze's
        request class would read *your hold was malformed* about an act that
        held nothing — the seam discipline the cap and the split apply to the
        member's shared rules.
        """
        for bad in ("", "   ", None, 42, b"cycle-7"):
            with pytest.raises(HoldoutRequestError) as refusal:
                cycle_rotation(bad)

            assert not isinstance(refusal.value, FreezeRequestError)
            assert "non-empty" in str(refusal.value)

    def test_the_split_taken_at_the_rotation_is_the_recorded_split(self, pool):
        """One spelling: the caller's direct split and the record's are one.

        §10.3.1's own call is ``pool.split(0.7, rotate_each_cycle=True)``,
        and this module's rotation is the cycle's name — so
        ``split_replay_pool(rotation=cycle_rotation(n))`` over the pool this
        record read answers the identical halves, and a caller marking
        ``replay_score`` rows through the split's own predicates and this
        module recording the cycle run one split, not two that merely agree.
        """
        _add_worlds(pool, 24)

        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )
        direct = split_replay_pool(
            database_url=pool, rotation=cycle_rotation("cycle-1")
        )

        assert record.holdout == direct.holdout
        assert record.world_count == direct.world_count
        assert record.fraction == direct.train_fraction


class TestTheRotationMoves:
    """The rotation's *point* — the holdout of cycle N+1 is not cycle N's."""

    def test_two_cycles_answer_two_holdouts(self, pool):
        """The halves move with the cycle name — the sentence's own verb.

        A holdout that never moved would be a holdout the loop could *learn*:
        the winner of every cycle selected on the same 70% and reported on
        the same 30%, which is §12.1's multiple-testing problem one level up,
        spread over time.
        """
        _add_worlds(pool, 24)

        first = record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())
        second = record_cycle_holdout("cycle-2", database_url=pool, recorded_at=dt_now())

        assert first.holdout != second.holdout
        assert first.id != second.id

    def test_two_cycles_of_the_same_name_answer_the_one_holdout(self, pool):
        """The other half of the law: the name decides, not the calendar.

        A re-recorded cycle over an unchanged pool answers the same half —
        determinism is not *always differ*, it is *same name, same split* —
        which is what makes a recorded row recomputable rather than merely
        believable.
        """
        _add_worlds(pool, 24)

        first = record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_at(9))
        second = record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_at(10))

        assert first.holdout == second.holdout
        assert first.world_count == second.world_count
        assert first.id != second.id  # but they are two occurrences

    def test_the_rotation_sweeps_the_pool(self, pool):
        """No world is the grader forever, none the graded forever.

        Over twenty cycles of a floor-sized pool, every world is held out at
        least once — so every world sits under the report's reading sometimes
        — and no world is held out every time, so every world is selected on
        sometimes too.  That is the whole mitigation of §12.1's risk row, as
        a coverage fact rather than a hope.
        """
        _add_worlds(pool, 20)
        worlds = {f"world-{index:03d}" for index in range(20)}
        held_out_by_cycle = []
        for cycle in range(20):
            record = record_cycle_holdout(
                f"cycle-{cycle}", database_url=pool, recorded_at=dt_now()
            )
            held_out_by_cycle.append(set(record.holdout))

        graded = set().union(*held_out_by_cycle)
        assert graded == worlds  # everyone reports sometimes
        assert all(
            len(worlds - half) == 14 for half in held_out_by_cycle
        )  # and fourteen train under every one of these cycles
        assert not set.intersection(*held_out_by_cycle)  # nobody grades always

    def test_the_sweep_is_recorded_not_remembered(self, pool):
        """The audit read answers every cycle's half, oldest first.

        *Which worlds did each cycle report on?* is a question the store
        answers after the fact — ordered by ``(recorded_at, id)`` so two
        reads of one history return the same sequence, with the cycles in
        the order their splits were taken.
        """
        _add_worlds(pool, 20)
        for cycle in range(6):
            record_cycle_holdout(
                f"cycle-{cycle}",
                database_url=pool,
                recorded_at=dt_at(6 + cycle),  # one hour each: order is causal
            )

        history = cycle_holdouts(database_url=pool)

        assert [record.iteration_id for record in history] == [
            f"cycle-{cycle}" for cycle in range(6)
        ]
        assert [record.recorded_at for record in history] == sorted(
            record.recorded_at for record in history
        )
        for record in history:
            assert len(record.holdout) == 6


class TestTheRecord:
    """The sentence's second clause — *persisting which worlds were held out*."""

    def test_the_record_reads_back_equal(self, pool):
        """A row written is the row the store holds.

        The record returned and the record the audit read answers are one
        value — the same six facts, no drift between the write and the read.
        """
        _add_worlds(pool, 24)

        written = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )

        assert isinstance(written, HoldoutRecord)
        assert cycle_holdouts(database_url=pool) == (written,)

    def test_the_row_carries_which_worlds_were_held_out(self, pool):
        """The sentence's own payload: the held-out half, in rank order.

        The half is the split's own order — the digest rank the record was
        decided in — so two reads of one row answer the same sequence, and a
        caller reads the worlds without re-running the split.
        """
        _add_worlds(pool, 24)

        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )
        direct = split_replay_pool(database_url=pool, rotation="cycle-1")

        assert record.holdout == direct.holdout
        assert record.holdout == tuple(direct.holdout)
        assert json.loads(record.holdout_worlds) == list(direct.holdout)
        assert len(record.holdout) == 7  # 24 worlds at 7/10: 17 train, 7 report

    def test_the_row_names_the_pool_and_the_share_it_was(self, pool):
        """``world_count`` and ``train_fraction`` — *which* 70/30 of *which* pool.

        An operator reading a row sees the half, the pool it was a share of
        and the exact share it was taken by, so a holdout of 7 from 24 is
        never read as one of 7 from 50.
        """
        _add_worlds(pool, 24)

        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )

        assert record.world_count == 24
        assert record.train_fraction == "7/10"
        assert record.fraction == Fraction(7, 10) == TRAIN_FRACTION

    def test_the_train_half_is_not_persisted(self, pool):
        """The row carries the reporting half and names no selection half.

        The sentence names the held-out worlds, and the train half is the
        complement at the moment of the split — recomputable from the pool at
        the row's own rotation through feature 278's seam, rather than a
        second list this member would have to keep agreeing with the first.
        """
        _add_worlds(pool, 24)

        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )

        assert set(record.row()) == {
            "id",
            "iteration_id",
            "recorded_at",
            "world_count",
            "train_fraction",
            "holdout_worlds",
        }
        direct = split_replay_pool(database_url=pool, rotation="cycle-1")
        assert not (set(record.holdout) & set(direct.train))
        assert set(record.holdout) | set(direct.train) == {
            f"world-{index:03d}" for index in range(24)
        }

    def test_the_row_is_a_fresh_dict_per_call(self, pool):
        """A store-shaped mapping, and a new object each time."""
        _add_worlds(pool, 24)
        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )

        first = record.row()
        first["holdout_worlds"] = "tampered"

        assert record.row()["holdout_worlds"] != "tampered"

    def test_the_recorded_instant_is_stamped_and_parsed_back(self, pool):
        """The member's one stamp shape — aware, UTC, second-truncated."""
        _add_worlds(pool, 24)

        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_at(9)
        )

        assert record.recorded_at == "2026-03-01T09:00:00Z"
        assert record.recorded == dt_at(9)

    def test_a_default_instant_is_stamped_when_none_is_given(self, pool):
        """The caller that passes no instant still records one.

        The stamp is part of the cycle's own history, so it defaults to the
        current UTC instant rather than to NULL — a row that could not be
        ordered is a row the audit read cannot sequence.
        """
        _add_worlds(pool, 24)

        # The stamp is second-truncated, so the bounds are read in the
        # stamp's own terms — a wall clock that started the second before
        # the call still brackets it.
        before = dt.datetime.now(dt.UTC).replace(microsecond=0)
        record = record_cycle_holdout("cycle-1", database_url=pool)
        after = dt.datetime.now(dt.UTC).replace(microsecond=0)

        assert before <= record.recorded <= after
        assert record.recorded.tzinfo is not None

    def test_a_retry_is_a_new_occurrence_not_an_overwrite(self, pool):
        """§12.1's cycle may open, close and open again — the retry is re-decided.

        Two records of one cycle name inside the same second stand as two
        rows with two ids, because both were true: the per-occurrence id is
        the same shape the hold's and the cap's are, for the same reason —
        an id derived from ``(iteration, instant)`` alone would collide on
        exactly this retry.
        """
        _add_worlds(pool, 24)

        first = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )
        second = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )

        assert _row_count(pool) == 2
        assert first.id != second.id
        assert {first.id, second.id} == {
            record.id for record in cycle_holdouts(database_url=pool)
        }

    def test_a_retry_over_a_grown_pool_is_re_decided(self, pool):
        """The worlds are read at record time, never accepted from the caller.

        Between the attempts the pool may grow — the retried cycle's split is
        a new fact over the pool as it stands, with the row's own
        ``world_count`` naming the pool it was a share of.
        """
        _add_worlds(pool, 24)
        first = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_at(9)
        )

        _add_worlds(pool, 6, start=24)
        second = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_at(10)
        )

        assert first.world_count == 24
        assert second.world_count == 30
        assert len(first.holdout) == 7 and len(second.holdout) == 9
        history = cycle_holdouts(database_url=pool)
        assert [record.world_count for record in history] == [24, 30]

    def test_the_record_is_a_value_not_a_view_of_the_store(self, pool):
        """A caller that keeps writing the pool cannot move a record read.

        The worlds are carried as text inside the row, cut at write time, so
        a pool that grows afterwards leaves a recorded half answering what it
        answered when the cycle took it.
        """
        _add_worlds(pool, 24)
        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )

        _add_worlds(pool, 6, start=24)

        assert record.world_count == 24
        assert len(record.holdout) == 7

    def test_the_record_compares_and_hashes_by_value(self, pool):
        """Two records of one occurrence are one record."""
        _add_worlds(pool, 24)
        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )
        read_back = cycle_holdouts(database_url=pool)[0]

        assert record == read_back
        assert hash(record) == hash(read_back)
        assert record != object()

    def test_the_table_is_created_lazily_by_the_first_record(self, pool):
        """An untouched pool holds no record table — the first record brings it.

        The table is this member's own, created beside the one module that
        writes it, so a deployment that has never run a dreaming cycle
        carries no empty artifact of one.
        """
        assert not _table_exists(pool, CYCLE_HOLDOUT_TABLE)

        _add_worlds(pool, 24)
        record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())

        assert _table_exists(pool, CYCLE_HOLDOUT_TABLE)

    def test_an_untouched_pool_answers_an_empty_history(self, pool):
        """The state between a migrated deployment and its first cycle.

        The audit read creates the table lazily and answers ``()`` — no
        cycle has dreamed, and that is a finding about the deployment, not a
        refusal.
        """
        history = cycle_holdouts(database_url=pool)

        assert history == ()
        assert _table_exists(pool, CYCLE_HOLDOUT_TABLE)

    def test_the_pool_union_is_read_whole(self, pool):
        """The worlds are the pool's own membership — both halves, once each.

        ``pool_worlds``' union law, reached through the record: a world
        authored into ``bootstrap_world`` and never replayed is still held
        out sometimes, and a financial world named only by score rows is
        still selected on sometimes.
        """
        with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
            for index in range(24):
                connection.execute(
                    "INSERT INTO bootstrap_world (world_id, label) VALUES (?, ?)",
                    (f"world-{index:03d}", f"label-{index}"),
                )
            for index in range(24, 30):  # financial only: no bootstrap row
                for revision in range(3):
                    connection.execute(
                        "INSERT INTO replay_score (id, policy_version, world_id, "
                        "beta, score, committed_pick, is_holdout, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"score-fin-{index}-{revision}",
                            f"pi-{revision}",
                            f"world-{index:03d}",
                            0.0,
                            float(revision),
                            None,
                            0,
                            "2026-01-01T00:00:00Z",
                        ),
                    )

        record = record_cycle_holdout(
            "cycle-1", database_url=pool, recorded_at=dt_now()
        )

        assert record.world_count == 30
        assert set(record.holdout) <= {
            f"world-{index:03d}" for index in range(30)
        }

    def test_the_env_mapping_names_the_database(self, pool):
        """``env`` is honoured the way every store seam in this member honours it.

        A caller that holds its own view of the deployment's variables names
        the database through it, without monkeypatching the process.
        """
        _add_worlds(pool, 24)

        record = record_cycle_holdout(
            "cycle-1", recorded_at=dt_now(), env={DATABASE_URL_ENV: pool}
        )

        assert record.world_count == 24
        assert cycle_holdouts(env={DATABASE_URL_ENV: pool}) == (record,)

    def test_the_record_writes_nothing_to_the_pools_tables(self, pool):
        """Feature 270's subject is not writing them, and neither is this one.

        The record is a judgment's persistence over the pool, not a mutation
        of it: the pool's row counts are the probe, over a pool that already
        holds rows so an insert of any kind would show.
        """
        with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
            for index in range(24):
                connection.execute(
                    "INSERT INTO bootstrap_world (world_id, label) VALUES (?, ?)",
                    (f"world-{index:03d}", f"label-{index}"),
                )
                connection.execute(
                    "INSERT INTO replay_score (id, policy_version, world_id, "
                    "beta, score, committed_pick, is_holdout, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"score-{index}-0",
                        "pi-0",
                        f"world-{index:03d}",
                        0.0,
                        0.5,
                        None,
                        0,
                        "2026-01-01T00:00:00Z",
                    ),
                )
        with closing(sqlite3.connect(sqlite_path(pool))) as connection:
            before = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in POOL_TABLES
            }

        record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())

        with closing(sqlite3.connect(sqlite_path(pool))) as connection:
            after = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in POOL_TABLES
            }
        assert after == before == {"bootstrap_world": 24, "replay_score": 24}


class TestTheRecordRefusals:
    """Every refusal names its subject — the ask's facts, the store's, the floor's."""

    def test_a_thin_pool_is_the_ladders_refusal(self, pool):
        """§12.1's floor — *"below 20 worlds: do not run dreaming"* — delegated.

        A pool too thin to dream on has no halves to rotate, so the refusal
        is feature 275's own, in the floor's own word, refused by the
        split's judgment exactly as the cap's, the ceiling's and the split's
        own seams delegate it.
        """
        _add_worlds(pool, 19)

        with pytest.raises(PoolTooThinError) as refusal:
            record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())

        message = str(refusal.value)
        assert message.startswith(POOL_TOO_THIN_CODE)
        assert "19 world(s)" in message

    def test_the_thin_pool_refusal_comes_after_the_stores(self, database_url):
        """The figure the floor judges is one this call has to read to know.

        The same ordering :func:`dreaming.split.split_replay_pool` documents:
        a poolless database is the store's refusal even though a thin pool
        would be refused too, because the caller's repair differs — point at
        the pool, against grow the pool.
        """
        with pytest.raises(HoldoutRecordError):
            record_cycle_holdout("cycle-1", database_url=database_url, recorded_at=dt_now())

    def test_the_thin_pool_refusal_leaves_no_table(self, pool):
        """A refused record leaves not even an empty table behind.

        The pool is probed, read and split *before* the DDL runs, so the
        floor's refusal lands on a database that holds no artifact of the
        record it refused.
        """
        _add_worlds(pool, 19)

        with pytest.raises(PoolTooThinError):
            record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())

        assert not _table_exists(pool, CYCLE_HOLDOUT_TABLE)

    def test_the_floor_passes_through_as_the_ladders_keyword(self, pool):
        """A deployment's own floor is the ladder's keyword, not a second one.

        Pinned in both directions so the two spellings of the bottom rung
        cannot disagree: the same pool is refused at the default floor and
        recorded at a lower one.
        """
        _add_worlds(pool, 10)

        with pytest.raises(PoolTooThinError):
            record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())
        assert (
            record_cycle_holdout(
                "cycle-1", floor=5, database_url=pool, recorded_at=dt_now()
            ).world_count
            == 10
        )

    def test_a_malformed_iteration_id_is_refused_before_the_store(self, pool):
        """Ask facts first — the cycle's own name, in this module's word."""
        for bad in ("", "   ", None, 42, b"cycle-1"):
            with pytest.raises(HoldoutRequestError) as refusal:
                record_cycle_holdout(bad, database_url=pool, recorded_at=dt_now())

            assert not isinstance(refusal.value, FreezeRequestError)
            assert "non-empty" in str(refusal.value)

    def test_a_fraction_outside_the_split_is_translated_not_borrowed(self, pool):
        """The 70/30 arithmetic is feature 278's — its rule, this module's word.

        A caller recording a rotation must not meet the split's request
        class for an act that split nothing, the same seam discipline the
        cap applies to the member's shared rules.
        """
        _add_worlds(pool, 24)

        for bad in (0.0, 1.0, 1.5, -0.1, "nonsense"):
            with pytest.raises(HoldoutRequestError) as refusal:
                record_cycle_holdout(
                    "cycle-1",
                    train_fraction=bad,
                    database_url=pool,
                    recorded_at=dt_now(),
                )

            assert not isinstance(refusal.value, SplitRequestError)
            assert "exact share" in str(refusal.value)

    def test_a_lower_fraction_records_its_own_share(self, pool):
        """The fraction is a parameter, read exactly and recorded exactly.

        3/4 of 24 trains 18 and reports 6, and the row says which share it
        was — *which* 70/30 (or 75/25) is part of what the record persists.
        """
        _add_worlds(pool, 24)

        record = record_cycle_holdout(
            "cycle-1",
            train_fraction=Fraction(3, 4),
            database_url=pool,
            recorded_at=dt_now(),
        )

        assert record.fraction == Fraction(3, 4)
        assert record.train_fraction == "3/4"
        assert len(record.holdout) == 6

    def test_a_naive_instant_is_refused_in_this_modules_vocabulary(self, pool):
        """The stamp rule is the member's one spelling; the word is this module's.

        A naive instant would place a cycle's split hours away from the
        process that took it, in whatever zone the host happens to keep, and
        nothing in the row would look wrong.
        """
        _add_worlds(pool, 24)

        with pytest.raises(HoldoutRequestError) as refusal:
            record_cycle_holdout(
                "cycle-1",
                database_url=pool,
                # The naive instant *is* the refusal's subject.
                recorded_at=dt.datetime(2026, 3, 1, 12, 0, 0),  # noqa: DTZ001
            )

        assert not isinstance(refusal.value, FreezeRequestError)
        assert "timezone-aware" in str(refusal.value)

    def test_no_database_named_is_refused_by_name(self, monkeypatch):
        """An act that means to write and resolves nothing is refused by name.

        Not answered with ``None``: a holdout "recorded" over no database is
        a holdout the store does not hold, and the audit read would find
        nothing — §12's exit criterion read over worlds nobody recorded.
        """
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

        with pytest.raises(HoldoutRequestError) as refusal:
            record_cycle_holdout("cycle-1", recorded_at=dt_now(), env={})

        assert DATABASE_URL_ENV in str(refusal.value)

    def test_a_url_the_member_cannot_speak_is_translated(self, pool, monkeypatch):
        """Never feature 270's word — pinned by class, since the message quotes.

        The seam discipline the whole workspace states: a caller recording a
        rotation must not read *your hold was malformed* about an act that
        held nothing.
        """
        monkeypatch.setenv(DATABASE_URL_ENV, pool)

        with pytest.raises(HoldoutRequestError) as refusal:
            record_cycle_holdout(
                "cycle-1",
                database_url="postgresql://h/db",
                recorded_at=dt_now(),
            )

        assert not isinstance(refusal.value, FreezeRequestError)

    def test_a_database_with_no_pool_is_refused_before_the_table(
        self, database_url
    ):
        """No pool tables means no pool to hold worlds out of.

        A row written against a poolless database would name worlds that
        were never read while the cycle believed its reporting half existed
        — refused in this module's own store class, before any DDL, so a
        refused record leaves no trace.
        """
        with pytest.raises(HoldoutRecordError) as refusal:
            record_cycle_holdout(
                "cycle-1", database_url=database_url, recorded_at=dt_now()
            )

        assert "no pool" in str(refusal.value)
        assert not isinstance(refusal.value, SplitStoreError)
        assert not _table_exists(database_url, CYCLE_HOLDOUT_TABLE)

    def test_the_audit_read_refuses_a_poolless_database_too(self, database_url):
        """``()`` would read *no cycle ever dreamed* off a store that never could."""
        with pytest.raises(HoldoutRecordError):
            cycle_holdouts(database_url=database_url)

    def test_a_corrupt_stamp_refuses_at_the_property(self, pool):
        """The parsed faces refuse in this module's word, never the freeze's.

        A stamp that will not parse is a value this member never writes,
        arrived by a hand — and a caller that met feature 270's class here
        would read *a held pool* refusal out of a table that holds nothing.
        """
        _add_worlds(pool, 24)
        record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())
        with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
            connection.execute(
                f"UPDATE {CYCLE_HOLDOUT_TABLE} SET recorded_at = 'not-a-stamp'"
            )

        (corrupt,) = cycle_holdouts(database_url=pool)

        with pytest.raises(HoldoutRecordError) as refusal:
            _ = corrupt.recorded

        assert not isinstance(refusal.value, FreezeRequestError)

    def test_a_holdout_half_that_is_not_json_refuses_at_the_property(self, pool):
        """The row's payload is a JSON array; anything else never was written."""
        _add_worlds(pool, 24)
        record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())
        with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
            connection.execute(
                f"UPDATE {CYCLE_HOLDOUT_TABLE} SET holdout_worlds = 'not json['"
            )

        (corrupt,) = cycle_holdouts(database_url=pool)

        with pytest.raises(HoldoutRecordError):
            _ = corrupt.holdout

    def test_a_holdout_half_that_is_not_world_ids_refuses_at_the_property(self, pool):
        """Numbers and blanks belong in no cycle's half — refused, not coerced."""
        _add_worlds(pool, 24)
        record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())
        for payload in ('["world-000", 42]', '["world-000", "  "]', '"world-000"'):
            with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
                connection.execute(
                    f"UPDATE {CYCLE_HOLDOUT_TABLE} SET holdout_worlds = ?",
                    (payload,),
                )

            (corrupt,) = cycle_holdouts(database_url=pool)

            with pytest.raises(HoldoutRecordError) as refusal:
                _ = corrupt.holdout

            assert "world ids" in str(refusal.value)

    def test_a_fraction_that_names_no_share_refuses_at_the_property(self, pool):
        """The row's fraction is the exact text of a rational, or a hand's work."""
        _add_worlds(pool, 24)
        record_cycle_holdout("cycle-1", database_url=pool, recorded_at=dt_now())
        with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
            connection.execute(
                f"UPDATE {CYCLE_HOLDOUT_TABLE} SET train_fraction = 'mostly'"
            )

        (corrupt,) = cycle_holdouts(database_url=pool)

        with pytest.raises(HoldoutRecordError) as refusal:
            _ = corrupt.fraction

        assert "rational" in str(refusal.value)


class TestTheSchema:
    """``cycle_holdout`` — the member's own table, pinned as text and as DDL."""

    def test_the_table_is_named_and_commented(self):
        """The name, and the feature's own reason for the table, in the DDL."""
        schema = cycle_holdout_schema()

        assert CYCLE_HOLDOUT_TABLE == "cycle_holdout"
        assert f"CREATE TABLE IF NOT EXISTS {CYCLE_HOLDOUT_TABLE}" in schema
        assert "-- Feature 279:" in schema
        assert "holdout rotated each cycle" in schema.lower()

    def test_the_row_is_six_columns(self):
        """Identity, cycle, stamp, pool size, share, and the half itself."""
        schema = cycle_holdout_schema()

        for column in (
            "id",
            "iteration_id",
            "recorded_at",
            "world_count",
            "train_fraction",
            "holdout_worlds",
        ):
            assert column in schema, column

    def test_no_guards_no_unique_index_no_conflict_arm(self):
        """History, not a hold: nothing to guard, nothing to close, nothing to upsert.

        The one rewrite this table exists not to perform is an upsert over
        an existing row, so there is no ``ON CONFLICT`` arm to find and no
        unique index a retried cycle could collide with.
        """
        schema = cycle_holdout_schema()

        assert "TRIGGER" not in schema.upper()
        assert "UNIQUE" not in schema.upper()
        assert "ON CONFLICT" not in schema.upper()

    def test_the_ddl_is_idempotent(self, pool):
        """``IF NOT EXISTS`` — the lazy creation is safe to repeat."""
        with closing(sqlite3.connect(sqlite_path(pool))) as connection:
            for _ in range(3):
                connection.executescript(cycle_holdout_schema())
            connection.execute("PRAGMA integrity_check")

        assert _table_exists(pool, CYCLE_HOLDOUT_TABLE)

    def test_the_table_is_this_members_own(self):
        """Neither the pool's tables nor the freeze's nor the cap's."""
        schema = cycle_holdout_schema()

        for other in (*POOL_TABLES, FREEZE_TABLE, CYCLE_CAP_TABLE):
            assert f"CREATE TABLE IF NOT EXISTS {other}" not in schema, other

    def test_the_ddl_creates_the_table_it_names(self, database_url):
        """The text and the database agree — the schema is executable as spelled."""
        with closing(sqlite3.connect(sqlite_path(database_url))) as connection:
            connection.executescript(cycle_holdout_schema())

        assert _table_exists(database_url, CYCLE_HOLDOUT_TABLE)


class TestTheVocabulary:
    """Feature 279's two classes, and the line between them and their neighbours."""

    def test_both_classes_share_the_member_base(self):
        """One member, one base — the workspace's per-member rule."""
        for refusal in (HoldoutRequestError, HoldoutRecordError):
            assert issubclass(refusal, DreamingError)
        assert issubclass(DreamingError, Exception)

    def test_the_two_classes_are_siblings(self):
        """*Your ask was wrong* is not *your store holds nothing*.

        The repairs differ — re-consider what was asked for, against point at
        the database the replay pool lives in — so a caller that must react
        differently must be able to catch them apart.
        """
        assert not issubclass(HoldoutRequestError, HoldoutRecordError)
        assert not issubclass(HoldoutRecordError, HoldoutRequestError)

    def test_the_classes_are_siblings_of_every_existing_class(self):
        """A caller catches a rotation's refusal without catching anyone else's."""
        import dreaming

        for refusal in (HoldoutRequestError, HoldoutRecordError):
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
                dreaming.CapRequestError,
                dreaming.CapRecordError,
                dreaming.RevisionCeilingError,
                SplitRequestError,
                SplitStoreError,
                dreaming.ProportionComparisonError,
                dreaming.PairedComparisonError,
                dreaming.TransferRequestError,
                dreaming.TransferStoreError,
                dreaming.BarRequestError,
                dreaming.BarRecordError,
                dreaming.SelectionBarError,
            ):
                assert not issubclass(refusal, sibling), sibling
                assert not issubclass(sibling, refusal), sibling

    def test_no_refusal_mints_a_code_word_this_member_already_carries(self):
        """Feature 279's sentence mandates no code, so the subject opens the message.

        The one vocabulary this module never borrows is the thin pool's and
        the freeze's: the floor is delegated in the floor's own word, and a
        rotation never held anything.
        """
        with pytest.raises(HoldoutRequestError) as refusal:
            cycle_rotation(None)

        message = str(refusal.value)
        assert POOL_TOO_THIN_CODE not in message
        assert FREEZE_CODE not in message

    def test_the_module_is_reachable_from_the_member(self):
        """The feature's surface is the member's, as the ladder's other rungs are."""
        import dreaming

        for name in (
            "CYCLE_HOLDOUT_TABLE",
            "HoldoutRecord",
            "HoldoutRecordError",
            "HoldoutRequestError",
            "cycle_holdout_schema",
            "cycle_holdouts",
            "cycle_rotation",
            "record_cycle_holdout",
        ):
            assert name in dreaming.__all__, name
            assert hasattr(dreaming, name), name

    def test_the_module_is_stdlib_only_and_imports_no_member(self):
        """The rotation is stdlib-only, and the member imports no sibling.

        The factory's scan imports this package to fire its ``@register``, so
        a module-scope third-party import would make composition pay for a
        feature it is not using — the restraint every rung of this member's
        ladder states for its own module.
        """
        import sys

        import dreaming.rotation as module

        source = Path(module.__file__).read_text()
        for forbidden in (
            "import numpy",
            "import scipy",
            "import pandas",
            "from bootstrap",
            "from app",
        ):
            assert forbidden not in source, forbidden
        assert sys.modules["dreaming.rotation"] is module


def test_the_pool_fixture_exists(pool):
    """The pool this suite rotates over is a real one.

    A guard against the whole record class silently skipping: the same guard
    ``test_transfer.py`` states for its own seam, restated here because this
    file's record classes lean on the same fixture.
    """
    assert sqlite_path(pool).exists()
    assert pool_bootstrap_schema().count("CREATE TABLE") == 2
