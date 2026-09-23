"""Feature 270's claims, stated as tests.

app_spec.xml: *"System rejects a replay pool mutation during a dreaming
iteration, holding the pool fixed for the cycle."*  docs/alpha-engine-prd.md
§C5 states it as the first clause of the outer loop; §12.1 gives the reason —
the paper's ``V^{m★} ≥ V^0`` guarantee is a guarantee about the *fixed
history*.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* a hold **refuses every write** to the pool's tables — insert, update and
  delete, on both tables — and the refusal names the iteration holding it;
* the refusal is the **database's**, not a wrapper's: a writer that never
  heard of this member (a raw ``sqlite3`` connection, which is what an operator
  bisecting a deployment has) is refused exactly the same way;
* the pool is held **for the cycle and not beyond**: a release frees it, and
  the same writes then land;
* **at most one hold is open**, refused by the table rather than by a
  convention of this module's callers, because §12.1 runs one cycle at a time;
* the commitment makes *"held fixed"* **observable**: a pool that moved anyway
  — triggers dropped, a database restored — is detected rather than assumed
  away, and the commitment is a *pure function of membership*, so it is
  insensitive to the scores the cycle itself writes;
* a pool that is **not there** is refused by name rather than held; and
* the **restated** pool spellings agree with the members that own them, so this
  member's copy of the pool's shape cannot drift from the thing it restates.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing

import pytest
from dreaming import (
    FREEZE_CODE,
    FREEZE_TABLE,
    POOL_TABLES,
    REPLAY_SCORE_TABLE,
    UNGUARDED_CODE,
    WORLD_TABLE,
    CycleFreeze,
    FreezeRecord,
    FreezeRequestError,
    PoolFrozenError,
    cycle_freeze_schema,
    expected_triggers,
    missing_guards,
    open_cycle_freeze,
    pool_commitment,
    sqlite_path,
)
from dreaming.cycle import _SELECT_OPEN
from dreaming.layout import POOL_SCHEMA_BY_TABLE, pool_tables_present

#: A fixed, aware instant, so a hold's stamps are deterministic and a test that
#: asserts on one is asserting about the freeze rather than about the clock.
NOON = dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=dt.UTC)

#: A second instant later in the same cycle, for releases and re-holds.
LATER = dt.datetime(2026, 3, 1, 12, 30, 0, tzinfo=dt.UTC)


def _write(pool_url: str, statement: str, parameters: tuple = ()) -> None:
    """Run one statement against the pool on a connection of its own.

    A *raw* connection, deliberately: the whole claim under test is that the
    refusal lives in the database rather than in this member's API, so the
    writer that proves it has to be one that never went near the API.  Every
    test that writes to the pool while a hold is open goes through here, which
    is what makes each of them a test of the *trigger* and not of the wrapper
    — and :meth:`CycleFreeze.guard` gets its own tests separately, as the
    translation it is.
    """
    with closing(sqlite3.connect(sqlite_path(pool_url))) as connection, connection:
        connection.execute(statement, parameters)


#: The three writes a hold must refuse, one per table — each a statement a
#: legitimate writer would really run, so the refusal is tested against the
#: shape of the work and not against a syntax made up to be refused.  The
#: delete removes a row the fixture wrote, the update restates a score, and the
#: insert adds a new world's score; between them they are every door
#: :data:`dreaming.cycle._POOL_OPERATIONS` covers.
REFUSED_WRITES = (
    (
        REPLAY_SCORE_TABLE,
        (
            f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, world_id, "
            "beta, score, committed_pick, is_holdout, created_at) "
            "VALUES ('score-new', 'pi-1', 'world-aaa', 0.5, 0.5, NULL, '0', "
            "'2026-03-01T00:00:00Z')"
        ),
    ),
    (
        REPLAY_SCORE_TABLE,
        f"UPDATE {REPLAY_SCORE_TABLE} SET score = 99.0 WHERE id = 'score-world-aaa-0.0'",
    ),
    (
        REPLAY_SCORE_TABLE,
        f"DELETE FROM {REPLAY_SCORE_TABLE} WHERE id = 'score-world-aaa-0.0'",
    ),
    (
        WORLD_TABLE,
        (
            f"INSERT INTO {WORLD_TABLE} (world_id, seed, label, provenance, "
            "created_at) VALUES ('world-new', 9, 'label-new', NULL, "
            "'2026-03-01T00:00:00Z')"
        ),
    ),
    (
        WORLD_TABLE,
        f"UPDATE {WORLD_TABLE} SET label = 'renamed' WHERE world_id = 'world-aaa'",
    ),
    (
        WORLD_TABLE,
        f"DELETE FROM {WORLD_TABLE} WHERE world_id = 'world-aaa'",
    ),
)


class TestTheHold:
    """Opening a hold: what it records, and what it refuses to open over."""

    def test_open_records_the_iteration_instant_and_pool(self, freeze):
        """A hold records which cycle it is, when, and the pool's size then."""
        hold = freeze.open("cycle-1", opened_at=NOON)

        assert isinstance(hold, FreezeRecord)
        assert hold.iteration_id == "cycle-1"
        assert hold.opened_at == "2026-03-01T12:00:00Z"
        assert hold.released_at is None
        assert hold.is_open
        assert hold.world_count == 9  # three worlds plus six scores
        assert hold.commitment
        assert hold.opened == NOON

    def test_open_installs_the_guards_and_the_hold_table(self, freeze):
        """What a hold creates is ``pool_freeze`` and the six guards."""
        freeze.open("cycle-1", opened_at=NOON)

        with closing(sqlite3.connect(freeze.path)) as connection:
            triggers = {
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
        assert triggers == {
            f"pool_freeze_{table}_{operation}"
            for table in POOL_TABLES
            for operation in ("insert", "update", "delete")
        }

    def test_open_does_not_hold_anything_before_it_is_called(self, freeze):
        """Constructing the freeze holds nothing — §C5's hold is per iteration."""
        assert freeze.open_hold() is None
        assert freeze.held() is False
        assert freeze.holds() == ()

    def test_a_second_open_is_refused_and_names_the_holder(self, freeze):
        """§12.1 runs one cycle at a time; the second is told which to wait for."""
        freeze.open("cycle-1", opened_at=NOON)

        with pytest.raises(PoolFrozenError) as refusal:
            freeze.open("cycle-2", opened_at=LATER)

        message = str(refusal.value)
        assert message.startswith(FREEZE_CODE)
        assert "cycle-1" in message
        assert "cycle-2" in message
        assert "one dreaming cycle at a time" in message

    def test_the_one_open_hold_is_a_fact_about_the_table(self, freeze):
        """A *raw* second open is refused too — by the index, not by the read."""
        freeze.open("cycle-1", opened_at=NOON)

        with pytest.raises(sqlite3.IntegrityError, match="one_open_pool_freeze"):
            _write(
                freeze.database_url,
                f"INSERT INTO {FREEZE_TABLE} (id, iteration_id, opened_at, "
                "released_at, commitment, world_count) "
                "VALUES ('hand-made', 'cycle-9', ?, NULL, 'x', 0)",
                (LATER.isoformat(),),
            )

    def test_one_iteration_may_open_a_second_window_after_releasing(self, freeze):
        """A retry after a release is a *new* window, not a collision.

        §12.1's cycle may close and reopen — a failed M-revision sweep retried,
        a stuck hold released by hand, a replayed script — and the retry is
        stamped inside the same second far more often than not.  A hold id
        derived from ``(iteration, instant)`` alone would collide on the primary
        key there and surface as the *wrong* refusal, "the pool was taken by
        another writer", for a row holding nothing.
        """
        first = freeze.open("cycle-1", opened_at=NOON)
        freeze.release(first.id, released_at=NOON)

        second = freeze.open("cycle-1", opened_at=NOON)

        assert second.id != first.id
        assert second.iteration_id == "cycle-1"
        assert second.is_open
        assert freeze.open_hold() == second
        # both windows are on the record: the audit read keeps the closed one.
        # Compared as a *set* rather than a sequence, because both windows carry
        # the same ``opened_at`` and ``holds()`` orders by ``(opened_at, id)`` —
        # so which of the two comes first is decided by random ids and is not a
        # fact about the cycle.  A sequence assertion here would be pinning the
        # test's own stamping, not the store's behaviour.
        recorded = {h.id: h for h in freeze.holds()}
        assert set(recorded) == {first.id, second.id}
        assert recorded[first.id].is_open is False
        assert recorded[second.id].is_open is True

    def test_a_held_window_is_never_released_by_a_second_open(self, freeze):
        """The retry above is permitted because the first window *closed*.

        Pinned separately because the two are one edit apart: permitting the
        reopen must not be achieved by weakening the release, whose exactness
        is what keeps a closed window closed.
        """
        first = freeze.open("cycle-1", opened_at=NOON)

        with pytest.raises(PoolFrozenError, match="already held"):
            freeze.open("cycle-1", opened_at=NOON)

        assert freeze.verify(first) is True
        assert freeze.open_hold() == first
        assert first.is_open

    def test_open_refuses_an_iteration_id_that_names_nothing(self, freeze):
        """An id is how a collision is attributed; a value that names none is refused."""
        for bad in (None, "", "   ", 7, object()):
            with pytest.raises(FreezeRequestError, match="non-empty string"):
                freeze.open(bad, opened_at=NOON)

    def test_open_refuses_a_naive_instant(self, freeze):
        """A naive stamp would place a cycle's opening hours away from its process."""
        with pytest.raises(FreezeRequestError, match="timezone"):
            # The naive instant *is* the refusal's subject, so the call is
            # deliberate rather than an oversight — the sibling suites spell
            # the same exception the same way.
            freeze.open("cycle-1", opened_at=dt.datetime(2026, 3, 1, 12, 0, 0))  # noqa: DTZ001

    def test_the_cycle_opens_before_it_holds(self, pool):
        """A hold over a database with no pool table is refused, by name.

        The order matters: the commitment is read *before* the hold row is
        written, so a database with no pool never records a hold over nothing.
        """
        with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
            connection.execute(f"DROP TABLE {WORLD_TABLE}")

        with pytest.raises(PoolFrozenError) as refusal:
            CycleFreeze(pool).open("cycle-1", opened_at=NOON)

        message = str(refusal.value)
        assert message.startswith(FREEZE_CODE)
        assert WORLD_TABLE in message
        assert "no pool here to hold" in message


class TestTheRefusal:
    """The rule itself: every door into the pool is shut while a hold is open."""

    @pytest.mark.parametrize(("table", "statement"), REFUSED_WRITES)
    def test_every_write_is_refused_by_the_database(self, freeze, table, statement):
        """Insert, update and delete on both pool tables — refused raw.

        Raw is the point: the writer here never heard of this member, and it is
        refused anyway, because the rule lives in the trigger rather than in a
        wrapper its caller could walk around.  The abort names the code and
        both ends of the collision — the operation, the table.
        """
        freeze.open("cycle-1", opened_at=NOON)

        with pytest.raises(sqlite3.IntegrityError) as refusal:
            _write(freeze.database_url, statement)

        message = str(refusal.value)
        assert FREEZE_CODE in message
        assert table in message
        assert statement.split()[0].lower() in message

    @pytest.mark.parametrize(("table", "statement"), REFUSED_WRITES)
    def test_the_refusal_leaves_the_pool_exactly_as_it_was(
        self, freeze, table, statement
    ):
        """A refused write changes nothing — not the rows, not the commitment."""
        before, count_before = pool_commitment(freeze.path)
        freeze.open("cycle-1", opened_at=NOON)

        with pytest.raises(sqlite3.IntegrityError):
            _write(freeze.database_url, statement)

        after, count_after = pool_commitment(freeze.path)
        assert (after, count_after) == (before, count_before)

    @pytest.mark.parametrize(("table", "statement"), REFUSED_WRITES)
    def test_guard_translates_the_database_abort(self, freeze, table, statement):
        """Through this member's API the same refusal arrives in *its* vocabulary.

        ``guard`` is a translation and not the enforcement — the test above
        proves the enforcement is the trigger — and what it owes its caller is
        a :class:`~dreaming.errors.PoolFrozenError` naming the iteration
        holding the pool, which the raw abort cannot do.
        """
        freeze.open("cycle-1", opened_at=NOON)

        with pytest.raises(PoolFrozenError) as refusal:
            freeze.guard(statement)

        message = str(refusal.value)
        assert message.startswith(FREEZE_CODE)
        assert "cycle-1" in message
        assert table in message
        assert "Close the iteration" in message

    def test_guard_lets_a_write_through_when_nothing_is_held(self, freeze):
        """Between iterations the pool is free — which is the whole window rule."""
        freeze.guard(
            f"UPDATE {REPLAY_SCORE_TABLE} SET score = 42.0 "
            "WHERE id = 'score-world-aaa-0.0'"
        )
        assert freeze.verify(freeze.open("cycle-1", opened_at=NOON)) is True

    def test_guard_lets_a_write_through_after_a_release(self, freeze):
        """The cycle's own output is written *between* cycles, not during one.

        §C5 runs ``M`` candidates over a held pool and the evidence they
        produce lands in ``replay_score``; that write is the *next* iteration's
        input, and the window rule is what makes it legal — which is the repair
        this member's refusal names (*"close the iteration and write between
        cycles"*).
        """
        freeze.release(freeze.open("cycle-1", opened_at=NOON), released_at=LATER)

        written = freeze.guard(
            f"UPDATE {REPLAY_SCORE_TABLE} SET score = 42.0 "
            "WHERE id = 'score-world-aaa-0.0'",
            (),
        )
        assert written == 1

        with closing(sqlite3.connect(freeze.path)) as connection:
            (score,) = connection.execute(
                f"SELECT score FROM {REPLAY_SCORE_TABLE} "
                "WHERE id = 'score-world-aaa-0.0'"
            ).fetchone()
        assert score == 42.0

    def test_guard_does_not_swallow_a_neighbouring_failure(self, freeze):
        """A statement that fails for another reason is re-raised untouched.

        A translation that rewrote *every* ``IntegrityError`` as "the pool is
        frozen" would hide a real schema fault behind a rule about cycles —
        the failure the workspace names for a vocabulary that swallows a
        neighbouring feature's error.  Here nothing is held at all, so a
        ``NOT NULL`` violation can only be the schema speaking.
        """
        with pytest.raises(sqlite3.IntegrityError) as refusal:
            freeze.guard(
                f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, world_id) "
                "VALUES ('score-bad', NULL, 'world-aaa')"
            )

        assert FREEZE_CODE not in str(refusal.value)
        assert "NOT NULL" in str(refusal.value)

    def test_a_release_underneath_a_writer_frees_the_pool_immediately(self, freeze):
        """The window is the *state* of the hold, not a snapshot a writer took.

        A hold released a moment before a writer arrives does not license a
        retroactive refusal: the pool is free, and the write lands.  That is
        the ``for the cycle`` half of feature 270's sentence read strictly —
        §C5 lets the campaign loop add a completed campaign *between*
        iterations, so a release that still refused writes would make the pool
        unusable for the loop that owns it.
        """
        hold = freeze.open("cycle-1", opened_at=NOON)
        freeze.release(hold, released_at=LATER)

        _write(
            freeze.database_url,
            f"DELETE FROM {WORLD_TABLE} WHERE world_id = 'world-aaa'",
        )

    def test_the_unattributed_refusal_spelling_is_a_race_not_a_licence(
        self, freeze, monkeypatch
    ):
        """The refusal stands even when the holder can no longer be read back.

        A hold can be released between the writer's abort and this member's
        read of the open row — a real window across processes, though not one a
        single-threaded test can step into deterministically.  What is pinned
        here is the branch's *spelling*: the statement *was* refused under a
        hold, and saying so without attribution is honest about a race the
        caller lost, where inventing a holder would not be.  (The test above
        pins the other half — that the same release *before* the write is a
        genuine permission, so the two branches are not one behaviour.)
        """
        freeze.open("cycle-1", opened_at=NOON)

        # Force the race's *effect*: the trigger fires against a hold that the
        # read-back can no longer see, by making the read find no open row.
        # The statement is the real one with an unsatisfiable tail, so the
        # branch under test is reached with the row shape it really unpacks.
        monkeypatch.setattr(
            "dreaming.cycle._SELECT_OPEN",
            f"{_SELECT_OPEN} AND 0",
        )

        with pytest.raises(PoolFrozenError) as refusal:
            freeze.guard(f"DELETE FROM {WORLD_TABLE} WHERE world_id = 'world-aaa'")

        message = str(refusal.value)
        assert message.startswith(FREEZE_CODE)
        assert "could no longer read" in message
        assert WORLD_TABLE in message


class TestTheWindow:
    """``for the cycle`` — the hold ends when the iteration does, and not before."""

    @pytest.mark.parametrize(("table", "statement"), REFUSED_WRITES)
    def test_a_release_frees_the_pool(self, freeze, table, statement):
        """The same writes that were refused land once the cycle closes."""
        hold = freeze.open("cycle-1", opened_at=NOON)
        freeze.release(hold, released_at=LATER)

        _write(freeze.database_url, statement)  # no refusal

    def test_release_keeps_the_hold_as_a_record(self, freeze):
        """A released hold stays in the table — the audit question needs it."""
        hold = freeze.open("cycle-1", opened_at=NOON)
        released = freeze.release(hold, released_at=LATER)

        assert released.released_at == "2026-03-01T12:30:00Z"
        assert released.released == LATER
        assert released.is_open is False
        assert freeze.holds() == (released,)
        assert freeze.open_hold() is None
        assert freeze.held() is False

    def test_the_pool_can_be_held_again_after_a_release(self, freeze):
        """Between cycles the pool is free to be held by the next iteration."""
        freeze.release(freeze.open("cycle-1", opened_at=NOON), released_at=LATER)
        second = freeze.open("cycle-2", opened_at=LATER)

        assert second.iteration_id == "cycle-2"
        assert freeze.open_hold() == second
        assert [hold.iteration_id for hold in freeze.holds()] == ["cycle-1", "cycle-2"]

    def test_release_refuses_a_hold_that_is_not_open(self, freeze):
        """A double release cannot restamp a cycle's history."""
        hold = freeze.open("cycle-1", opened_at=NOON)
        freeze.release(hold, released_at=LATER)

        with pytest.raises(PoolFrozenError, match="not open"):
            freeze.release(hold, released_at=LATER)

    def test_a_statement_that_matches_no_row_is_not_a_mutation(self, freeze):
        """``FOR EACH ROW`` — a write that changes nothing is not refused.

        A property of the guard worth stating rather than leaving to be
        discovered: the trigger is ``FOR EACH ROW``, so a ``DELETE`` whose
        ``WHERE`` matches nothing never fires it.  That is correct, and correct
        for feature 270's own reason — the sentence forbids a pool *mutation*,
        and a statement that leaves the pool byte-for-byte as it was has not
        mutated it.  §C5's concern is that the history a tournament is held
        over must not move; a no-op cannot move it.
        """
        freeze.open("cycle-1", opened_at=NOON)

        # Both of these are writes, and both leave the pool exactly as it was.
        assert freeze.guard(
            "DELETE FROM bootstrap_world WHERE world_id = 'world-not-here'"
        ) == 0
        assert freeze.guard(
            "UPDATE replay_score SET score = 1.0 WHERE id = 'score-not-here'"
        ) == 0

    def test_release_refuses_an_id_this_database_never_wrote(self, freeze):
        """A hold id is either one this store wrote or it is nothing."""
        with pytest.raises(PoolFrozenError, match="no such hold"):
            freeze.release("freeze-nothing")

    def test_release_refuses_a_value_that_is_no_id(self, freeze):
        """An ask's own fault is refused in the ask's own vocabulary."""
        with pytest.raises(FreezeRequestError, match="released by its id"):
            freeze.release(7)

    def test_release_accepts_the_hold_id_as_well_as_the_record(self, freeze):
        """A caller that kept only the id can still close the cycle."""
        hold = freeze.open("cycle-1", opened_at=NOON)
        released = freeze.release(hold.id, released_at=LATER)

        assert released.id == hold.id
        assert released.released_at == "2026-03-01T12:30:00Z"


class TestTheCommitment:
    """``held fixed`` as an observable claim rather than a promise."""

    def test_verify_answers_true_for_an_unmoved_pool(self, freeze):
        """The claim the cycle needs to make after its candidates have run."""
        hold = freeze.open("cycle-1", opened_at=NOON)

        assert freeze.verify(hold) is True

    def test_verify_answers_false_when_the_pool_moved(self, freeze):
        """A pool that moved anyway — triggers dropped — is *detected*.

        This is what makes the commitment load-bearing rather than decorative:
        the guard is a rule, and a rule can be evaded (an ``AFTER``-the-fact
        rebuild, a database restored from backup, a guard dropped by hand).  A
        boolean "frozen" flag would report a clean cycle over a pool that had
        moved; a digest over membership cannot.

        The guard is **put back** after the sneaky write, and that is the
        stronger story rather than a softened one: the evasion that needs
        detecting is the one that covered its tracks, and a rebuilt-then-healed
        pool is exactly what an operator restoring from backup leaves behind.
        A test that left the guard missing would be caught by the *disarm*
        check (:meth:`test_verify_refuses_a_hold_whose_guards_were_removed`)
        before the commitment was ever compared, and the property under test
        here — the digest notices a moved pool — would not be exercised at all.
        """
        hold = freeze.open("cycle-1", opened_at=NOON)

        with closing(sqlite3.connect(freeze.path)) as connection, connection:
            connection.execute("DROP TRIGGER pool_freeze_replay_score_insert")
            connection.execute(
                f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, world_id, "
                "beta, score, committed_pick, is_holdout, created_at) "
                "VALUES ('score-sneak', 'pi-1', 'world-aaa', 0.0, 0.0, NULL, "
                "'0', '2026-03-01T00:00:00Z')"
            )
        freeze.ensure_schema()

        assert freeze.verify(hold) is False

    def test_the_commitment_is_a_pure_function_of_membership(self, freeze):
        """Two reads of an unchanged pool commit to the identical digest.

        The property that lets a hold *record* a commitment and later *check*
        it, in any process: nothing here is incidental — not a clock, not a
        row's insertion order, not the connection that read it.
        """
        first = pool_commitment(freeze.path)
        second = pool_commitment(freeze.path)

        assert first == second

    def test_the_commitment_covers_which_worlds_and_not_how_many(self, freeze):
        """A world swapped for another of the same size is a different pool.

        A reader that hashed only a count — or that hashed the rows in storage
        order — would miss this, and it is exactly the "the pool moved but
        nothing looked wrong" failure §12 names.
        """
        before, count_before = pool_commitment(freeze.path)
        freeze.ensure_schema()  # the guards have to exist before they are dropped

        with closing(sqlite3.connect(freeze.path)) as connection, connection:
            connection.execute("DROP TRIGGER pool_freeze_bootstrap_world_update")
            connection.execute(
                f"UPDATE {WORLD_TABLE} SET world_id = 'world-zzz' "
                "WHERE world_id = 'world-aaa'"
            )

        after, count_after = pool_commitment(freeze.path)
        assert count_after == count_before  # same size
        assert after != before  # different pool

    def test_the_commitment_needs_the_guards_to_have_been_installed(self, freeze):
        """Nothing is guarded until a hold installs the guards — by design.

        Stated as a test because it is the member's restraint and not an
        oversight: this member creates ``pool_freeze`` and the guards lazily, on
        the first hold, so a database it has merely been *pointed* at carries
        no rule this member wrote.  The commitment read, which is what a hold
        takes *before* it writes anything, therefore works over a pool nobody
        has held yet — and a write made before the first hold is a write made
        *between cycles*, which §C5 permits.
        """
        with closing(sqlite3.connect(freeze.path)) as connection:
            (triggers,) = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'"
            ).fetchone()
        assert triggers == 0

        # The commitment is readable without one, because it is a read.
        assert pool_commitment(freeze.path)[1] == 9

    def test_the_commitment_ignores_the_scores_the_cycle_writes(self, freeze):
        """The cycle's *output* is not a mutation of the fixed history.

        §C5's loop runs ``M`` candidates and each one's replay writes evidence
        into ``replay_score``; a commitment that folded scores in would count
        every candidate's own work as a mutation of the pool it was measured
        on, which would refuse the loop its own output.  What must not move is
        *which worlds the tournament is held over*.
        """
        hold = freeze.open("cycle-1", opened_at=NOON)

        with closing(sqlite3.connect(freeze.path)) as connection, connection:
            connection.execute("DROP TRIGGER pool_freeze_replay_score_update")
            connection.execute(
                f"UPDATE {REPLAY_SCORE_TABLE} SET score = 0.75 "
                "WHERE id = 'score-world-aaa-0.0'"
            )
        # the guard back on, so the *commitment* is the thing answering — see
        # the sibling test above for why the heal is part of this story
        freeze.ensure_schema()

        assert freeze.verify(hold) is True

    def test_verify_refuses_a_value_that_is_not_a_record(self, freeze):
        """A commitment is only meaningful beside the values it was taken with."""
        with pytest.raises(FreezeRequestError, match="record it opened with"):
            freeze.verify("cycle-1")

    def test_verify_refuses_a_pool_that_is_not_there(self, freeze):
        """*"Did not move"* and *"cannot compare"* are different facts.

        An iteration that read the second as the first would report a clean
        verify over a database that holds nothing.
        """
        hold = freeze.open("cycle-1", opened_at=NOON)

        with closing(sqlite3.connect(freeze.path)) as connection, connection:
            connection.execute(f"DROP TABLE {WORLD_TABLE}")

        with pytest.raises(PoolFrozenError, match="no pool here to hold"):
            freeze.verify(hold)


class TestTheDisarmedHold:
    """A hold that is open while its guards are not over the pool.

    **Why this class exists.**  A trigger fires per row, and DDL is not a row:
    no guard this member installs is consulted when a pool table is dropped,
    renamed or rebuilt, so *removing the enforcement* is the one mutation no
    trigger can refuse.  ``bootstrap`` performs exactly that rebuild in its own
    schema evolution (copy the table, ``DROP`` it, rename the copy back), and
    the consequence is that the data survives byte-identical while the guards
    over it are gone — a hold that reports a fixed history nothing is holding.

    The commitment cannot see this: it hashes *membership*, and a rebuild
    preserves membership.  So the disarm is checked on its own, by reading the
    trigger names back, which is what these tests pin.
    """

    def test_missing_guards_enumerates_what_the_pool_lacks(self, freeze):
        """The probe: every expected guard present is an empty answer."""
        freeze.ensure_schema()

        with closing(sqlite3.connect(freeze.path)) as connection:
            assert missing_guards(connection) == ()
            assert len(expected_triggers()) == len(POOL_TABLES) * 3

            connection.execute("DROP TRIGGER pool_freeze_replay_score_update")
            connection.commit()

            assert missing_guards(connection) == (
                "pool_freeze_replay_score_update",
            )

    def test_verify_refuses_a_hold_whose_guards_were_removed(self, freeze):
        """A rebuilt table preserves the rows and destroys the enforcement.

        ``verify()`` answering ``True`` here is the failure feature 270 exists
        to prevent, arriving without announcing itself: the iteration goes on
        believing its history fixed while every write to it succeeds.
        """
        hold = freeze.open("cycle-1", opened_at=NOON)

        with closing(sqlite3.connect(freeze.path)) as connection, connection:
            for operation in ("insert", "update", "delete"):
                connection.execute(
                    f"DROP TRIGGER pool_freeze_{WORLD_TABLE}_{operation}"
                )

        with pytest.raises(PoolFrozenError) as refusal:
            freeze.verify(hold)

        message = str(refusal.value)
        assert message.startswith(UNGUARDED_CODE)
        assert "cycle-1" in message
        assert "3 of its 6 guards" in message
        assert f"pool_freeze_{WORLD_TABLE}_insert" in message

    def test_a_rebuild_that_preserves_the_rows_is_still_refused(self, freeze):
        """The exact dance ``bootstrap`` performs, and the reason it is caught.

        The commitment compares *equal* after this — membership is unchanged —
        so a verify that answered on the digest alone would report a clean
        cycle over a pool with no enforcement left on it.
        """
        hold = freeze.open("cycle-1", opened_at=NOON)

        with closing(sqlite3.connect(freeze.path)) as connection, connection:
            connection.execute(f"CREATE TABLE staging AS SELECT * FROM {WORLD_TABLE}")
            connection.execute(f"DROP TABLE {WORLD_TABLE}")
            connection.execute(f"ALTER TABLE staging RENAME TO {WORLD_TABLE}")

        with pytest.raises(PoolFrozenError, match=UNGUARDED_CODE):
            freeze.verify(hold)

    def test_the_members_own_write_seam_heals_and_still_refuses(self, freeze):
        """``guard()`` goes through ``_connect``, which re-installs the guards.

        So the member's own door is never the exposed one: a statement run
        through this member re-arms the pool first and is then refused by the
        guard it just restored.  Pinned because the two paths differ on purpose
        — ``verify`` reports as-found, ``guard`` repairs then rules — and a
        later reader could reasonably assume they were the same path.
        """
        freeze.open("cycle-1", opened_at=NOON)

        with closing(sqlite3.connect(freeze.path)) as connection, connection:
            connection.execute("DROP TRIGGER pool_freeze_replay_score_insert")

        assert missing_guards(sqlite3.connect(freeze.path)) != ()

        with pytest.raises(PoolFrozenError, match=FREEZE_CODE):
            freeze.guard(
                f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, world_id, "
                "beta, score, committed_pick, is_holdout, created_at) "
                "VALUES ('x', 'pi-1', 'world-aaa', 0.0, 0.0, NULL, '0', "
                "'2026-03-01T00:00:00Z')"
            )

        # ...and the heal it performed is real, not incidental
        with closing(sqlite3.connect(freeze.path)) as connection:
            assert missing_guards(connection) == ()

    def test_a_released_hold_is_not_checked(self, freeze):
        """The guards are only a hold's while it is open.

        A released window leaves the rows behind and the guards installed —
        they are conditional on an open hold, not dropped with one — so
        checking a *closed* record against them would refuse a verify that is
        answering a question about history rather than about the present.
        """
        hold = freeze.open("cycle-1", opened_at=NOON)
        freeze.release(hold.id, released_at=NOON)

        with closing(sqlite3.connect(freeze.path)) as connection, connection:
            connection.execute("DROP TRIGGER pool_freeze_replay_score_update")

        assert freeze.verify(hold) is True


class TestTheSchema:
    """What the member creates, as text — inspectable without a database."""

    def test_the_schema_names_the_hold_table_and_the_index(self):
        """The table, the one-open index, and every guard — in one script."""
        schema = cycle_freeze_schema()

        assert f"CREATE TABLE IF NOT EXISTS {FREEZE_TABLE}" in schema
        assert "one_open_pool_freeze" in schema
        assert "((1)) WHERE released_at IS NULL" in schema

    def test_the_schema_covers_every_table_and_operation(self):
        """Two tables × three operations, and the schema says so itself."""
        schema = cycle_freeze_schema()

        for table in POOL_TABLES:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                assert f"BEFORE {operation} ON {table}" in schema
                assert f"pool_freeze_{table}_{operation.lower()}" in schema

    def test_the_schema_is_idempotent(self, freeze):
        """Running it twice leaves one schema — the contract every store states."""
        freeze.open("cycle-1", opened_at=NOON)
        freeze.ensure_schema()

        with closing(sqlite3.connect(freeze.path)) as connection:
            (triggers,) = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'"
            ).fetchone()
        assert triggers == 2 * 3

    def test_the_guards_are_not_a_sql_expression(self):
        """``RAISE`` takes a literal — SQLite rejects a ``||`` in that position.

        Pinned because it is a constraint rather than a choice: an expression
        in ``RAISE``'s message argument is a ``near "||": syntax error`` at
        ``CREATE TRIGGER`` time, which is why the trigger says ``an iteration``
        and the *member* names it.  A future edit that "improved" the message
        by interpolating the holder would break the DDL, and this test says so
        where the edit would be made.
        """
        schema = cycle_freeze_schema()

        assert "RAISE(ABORT, '" in schema
        # The only ``||`` in the script would be a concatenation inside a
        # RAISE, which is exactly the construct that does not parse.
        assert "RAISE(ABORT, '" + "x' || " not in schema
        for line in schema.splitlines():
            if "RAISE" in line and "||" in line:
                pytest.fail(f"RAISE carries an expression: {line.strip()}")

    def test_the_stand_in_pool_schema_is_the_owners_names(self):
        """The restatement carries the pool's tables under their own spellings."""
        assert set(POOL_SCHEMA_BY_TABLE) == set(POOL_TABLES)
        for table in POOL_TABLES:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in POOL_SCHEMA_BY_TABLE[table]

    def test_the_stand_in_schema_refuses_a_dialect_it_cannot_speak(self):
        """A dialect this member has never seen is refused by name."""
        from dreaming import pool_bootstrap_schema

        with pytest.raises(ValueError, match="sqlite only"):
            pool_bootstrap_schema("postgres")

    def test_pool_tables_present_reports_membership(self, pool):
        """The membership probe: what is there, in a stable order."""
        with closing(sqlite3.connect(sqlite_path(pool))) as connection:
            assert pool_tables_present(connection) == POOL_TABLES
            connection.execute(f"DROP TABLE {REPLAY_SCORE_TABLE}")
            assert pool_tables_present(connection) == (WORLD_TABLE,)


class TestTheEntryPoint:
    """The function form, for a caller that holds neither a freeze nor a URL."""

    def test_it_holds_the_pool_the_explicit_url_names(self, scores):
        """The same act as ``CycleFreeze.open``, without the intermediate object."""
        url, _ = scores

        hold = open_cycle_freeze("cycle-1", database_url=url, opened_at=NOON)

        assert hold.iteration_id == "cycle-1"
        assert CycleFreeze(url).open_hold() == hold

    def test_it_resolves_the_environment_when_given_no_url(self, scores, monkeypatch):
        """A deployment's URL is the default, the way every store resolves one."""
        url, _ = scores
        monkeypatch.setenv("DATABASE_URL", url)

        hold = open_cycle_freeze("cycle-1", opened_at=NOON)

        assert hold.iteration_id == "cycle-1"

    def test_it_refuses_when_nothing_names_a_database(self, monkeypatch):
        """A cycle that held nothing must not proceed believing it held something."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(FreezeRequestError, match="needs the database"):
            open_cycle_freeze("cycle-1")

    def test_it_refuses_an_in_memory_database(self, monkeypatch):
        """A hold in ``:memory:`` dies with the connection that opened it."""
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

        with pytest.raises(FreezeRequestError, match="no database path"):
            open_cycle_freeze("cycle-1")

    def test_it_refuses_a_scheme_this_member_cannot_speak(self, monkeypatch):
        """The spec's single-machine allowance is what a stdlib store can speak."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/nullius")

        with pytest.raises(FreezeRequestError, match="unsupported"):
            open_cycle_freeze("cycle-1")

    def test_a_bad_url_is_refused_when_it_is_used_and_not_before(self):
        """Composition-time work must not touch the disk — or refuse on its behalf."""
        freeze = CycleFreeze("postgresql://localhost/nullius")

        assert freeze.database_url == "postgresql://localhost/nullius"
        with pytest.raises(FreezeRequestError, match="unsupported"):
            _ = freeze.path
