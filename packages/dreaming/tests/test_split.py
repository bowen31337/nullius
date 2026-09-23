"""Feature 278's claim, stated as tests: the 70/30 train/holdout split.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 278: *System splits the
pool 70 to 30 into train and holdout, which returns selection on train with
reporting on holdout.*  docs/alpha-engine-prd.md §12.1 puts the split on the
ladder's top rung (*"50+: full dreaming, M = 30–40, 70/30 train/holdout split
on worlds"*), and docs/nullius-tech-architecture.md §10.3.1 spells the call in
code with the feature's own clause as its comment — ``train, holdout =
pool.split(0.7, ...)  # select on train, report on holdout``.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* the **arithmetic** is exact: 20 worlds split 14/6, 50 split 35/15, an
  indivisible pool's odd world goes to the larger remainder, and a tie goes to
  the holdout — the half the split exists to protect;
* the **assignment** is a digest rank, so it is deterministic in any process
  (pinned here by recomputing the rank independently, not by re-running the
  split), covers the pool disjointly, and rotates with the discriminator
  feature 279 will vary;
* the **two faces** are the return: the record unpacks as ``train, holdout``
  — §10.3.1's own line — and answers which half a world is in, refusing a
  world the pool does not hold rather than answering either half;
* the **pool's worlds** are read as a union — a world once, whichever half
  names it and however many score rows name it — and a database without the
  pool is refused rather than split as empty;
* a pool **below the ladder floor** is refused by feature 275's own judgment
  in its own word, exactly as the cap and the ceiling delegate theirs.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path

import pytest
from dreaming import (
    REPLAY_SCORE_TABLE,
    TRAIN_FRACTION,
    WORLD_TABLE,
    CycleFreeze,
    FreezeRequestError,
    PoolSplit,
    PoolTooThinError,
    SplitRequestError,
    SplitStoreError,
    pool_worlds,
    split_pool,
    split_replay_pool,
    sqlite_path,
)

#: Twenty ids — §12.1's own floor, and the smallest pool whose 70/30 needs no
#: rounding: 14 train, 6 holdout, exact.
TWENTY = tuple(f"world-{index:02d}" for index in range(20))


def _rank(rotation: str, world_id: str) -> tuple[str, str]:
    """The split's rank, spelled independently of the module under test.

    The module ranks worlds by a sha256 digest over the rotation and the id,
    newline-framed, with the id itself as the tiebreak.  Recomputing that
    here — rather than calling the split twice and comparing the split to
    itself — is what makes the determinism claim a claim about the *algorithm*
    rather than about Python's ``sorted`` being stable: any process that
    spells the same digest answers the same order, and this test is that
    other process.
    """
    digest = hashlib.sha256(f"{rotation}\n{world_id}\n".encode()).hexdigest()
    return (digest, world_id)


def _seed(url: str, bootstrap_ids, financial_ids, *, scores_per_world: int = 3):
    """Stand a pool up with both halves and score rows over both.

    ``bootstrap_ids`` are authored into ``bootstrap_world`` (and given score
    rows too, because an authored world that has been replayed is the honest
    shape of a dreaming pool); ``financial_ids`` exist only as
    ``replay_score`` rows — the half the census counts as financial.  Several
    score rows per world are written deliberately: a world replayed by ``M``
    revisions is named by ``M`` score rows, and every read below must still
    hold it once.  The rows are written the way the owners declare them —
    ``0109``'s eight columns, features 188/191's five — the same discipline
    the suite's ``scores`` fixture states.
    """
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        for index, world_id in enumerate(bootstrap_ids):
            connection.execute(
                f"INSERT INTO {WORLD_TABLE} (world_id, seed, label, provenance, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (world_id, index, f"label-{index}", None, "2026-01-01T00:00:00Z"),
            )
        for world_id in (*bootstrap_ids, *financial_ids):
            for revision in range(scores_per_world):
                connection.execute(
                    f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                    "world_id, beta, score, committed_pick, is_holdout, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"score-{world_id}-{revision}",
                        f"pi-{revision}",
                        world_id,
                        0.0,
                        float(revision),
                        None,
                        0,
                        "2026-01-01T00:00:00Z",
                    ),
                )


class TestTheSeventyThirty:
    """The arithmetic: exact, rational, largest remainder, ties to the holdout."""

    def test_twenty_worlds_split_fourteen_and_six(self):
        """§12.1's floor-sized pool, exact: 14 to select on, 6 to report on."""
        split = split_pool(TWENTY)

        assert len(split.train) == 14
        assert len(split.holdout) == 6

    def test_fifty_worlds_split_thirty_five_and_fifteen(self):
        """The top rung's own boundary pool, exact — 50+ is where §12.1 runs
        the split, and 50 needs no rounding either."""
        split = split_pool(tuple(f"world-{index:02d}" for index in range(50)))

        assert len(split.train) == 35
        assert len(split.holdout) == 15

    def test_an_indivisible_pool_gives_the_odd_world_to_the_larger_remainder(self):
        """53 worlds: 3/10 of 53 is 15.9 against 7/10 of 53 at 37.1, so the
        leftover world is the holdout's — 37/16."""
        split = split_pool(tuple(f"world-{index:02d}" for index in range(53)))

        assert len(split.train) == 37
        assert len(split.holdout) == 16

    def test_a_tie_goes_to_the_holdout(self):
        """25 worlds: 17.5 against 7.5, exactly level, and the holdout takes
        the odd world — the half the split exists to protect is never the one
        a tie rule under-funds.  35 worlds ties the same way, 24/11."""
        twenty_five = split_pool(tuple(f"world-{index:02d}" for index in range(25)))
        thirty_five = split_pool(tuple(f"world-{index:02d}" for index in range(35)))

        assert len(twenty_five.train) == 17
        assert len(twenty_five.holdout) == 8
        assert len(thirty_five.train) == 24
        assert len(thirty_five.holdout) == 11

    def test_every_tenth_pool_is_exact(self):
        """Pools divisible by ten cut exactly — 30% of the pool, no remainder —
        and every size here clears the floor, because a pool below it is the
        floor's refusal rather than a figure the arithmetic ever reaches."""
        for count in (20, 30, 40, 60, 100):
            split = split_pool(tuple(f"world-{index:02d}" for index in range(count)))

            assert len(split.holdout) == 3 * count // 10, count
            assert len(split.train) == 7 * count // 10, count

    def test_every_pool_is_the_nearest_split(self):
        """For any size, the halves sum to the pool and the holdout is within
        half a world of its exact share — the whole of the largest-remainder
        law, over every pool size the ladder can dream on."""
        for count in range(20, 61):
            split = split_pool(tuple(f"world-{index:02d}" for index in range(count)))

            assert len(split.train) + len(split.holdout) == count
            deviation = abs(Fraction(len(split.holdout), count) - Fraction(3, 10))
            assert deviation <= Fraction(1, 2 * count)

    def test_the_default_fraction_is_the_documents_seventy_thirtieths(self):
        """TRAIN_FRACTION is exactly 7/10 — a rational, not the float 0.7."""
        assert TRAIN_FRACTION == Fraction(7, 10)

    def test_the_fraction_is_a_parameter_read_exactly(self):
        """§10.3.1's call passes the fraction in, and a float is read through
        its shortest text so 0.7 is exactly 7/10, never its binary tail —
        the three spellings answer the one 70/30, and a three-quarter split
        over 40 answers its own exact figure."""
        forty = tuple(f"world-{index:02d}" for index in range(40))

        assert len(split_pool(forty, train_fraction=Fraction(3, 4)).holdout) == 10
        assert len(split_pool(forty, train_fraction=0.7).holdout) == 12
        assert len(split_pool(forty, train_fraction="7/10").holdout) == 12


class TestTheAssignment:
    """Which worlds: a digest rank — deterministic, disjoint, rotatable."""

    def test_the_holdout_is_the_digest_rank_head(self):
        """The assignment is sha256 over (rotation, id): this test recomputes
        the rank independently and takes its head, and the split answers the
        same six worlds — the determinism claim, pinned against a second
        spelling of the algorithm rather than against the module itself."""
        ranked = sorted(TWENTY, key=lambda world: _rank("", world))

        assert split_pool(TWENTY).holdout == tuple(ranked[:6])

    def test_the_train_half_is_the_same_order_complement(self):
        """Both halves carry the rank order, so the record is reproducible
        rather than incidental — the same pool at the same rotation constructs
        the same record in any process."""
        ranked = sorted(TWENTY, key=lambda world: _rank("", world))

        split = split_pool(TWENTY)

        assert split.train == tuple(ranked[6:])
        assert split.holdout == tuple(ranked[:6])

    def test_the_two_halves_partition_the_pool(self):
        """Disjoint and covering: no world is selected on and reported on, and
        no world is neither — the disjointness §10.3.1's paired statistic and
        feature 280's bar both stand on."""
        split = split_pool(TWENTY)

        assert not (set(split.train) & set(split.holdout))
        assert set(split.train) | set(split.holdout) == set(TWENTY)

    def test_the_assignment_is_not_the_alphabetical_head(self):
        """A sort-and-cut split would hold out the alphabetically first 30%
        forever — deterministic, and never rotating.  The digest order is
        uniform over the ids, so the un-rotated holdout is not the prefix."""
        split = split_pool(TWENTY)

        assert split.holdout != tuple(sorted(TWENTY)[:6])

    def test_a_rotation_moves_the_holdout(self):
        """The rotation is folded into every world's rank, so a different
        rotation answers a different holdout over the same pool — feature
        279's per-cycle act, on the seam this module hands it."""
        first = split_pool(TWENTY)
        second = split_pool(TWENTY, rotation="cycle-1")

        assert first != second
        assert second.holdout == tuple(
            sorted(TWENTY, key=lambda world: _rank("cycle-1", world))[:6]
        )

    def test_the_rotation_sweeps_the_pool(self):
        """Across rotations the holdout boundary moves over the whole pool —
        no world is permanently held out and none permanently selected on,
        which is what §12.1's "holdout rotated each cycle" buys over a fixed
        cut.  The bounds are loose because a digest is uniform, not exact."""
        held = {
            world: sum(
                split_pool(TWENTY, rotation=f"cycle-{turn}").is_holdout(world)
                for turn in range(20)
            )
            for world in TWENTY
        }

        # 20 rotations × 6 holdout seats = 120 holdings over 20 worlds, so a
        # uniform rank puts each world near 6 — never always, never never.
        assert all(1 <= count <= 11 for count in held.values())
        assert sum(held.values()) == 120

    def test_the_same_rotation_answers_the_same_split(self):
        """Two calls at one rotation are one value — reproducible, and equal
        by all four facts the record carries."""
        assert split_pool(TWENTY, rotation="cycle-9") == split_pool(
            TWENTY, rotation="cycle-9"
        )


class TestTheTwoFaces:
    """The return: selection on train, reporting on holdout, by name."""

    def test_the_record_unpacks_as_the_documents_own_line(self):
        """§10.3.1 spells the call ``train, holdout = pool.split(0.7, ...)``;
        the record's one derived protocol is that line made to run."""
        train, holdout = split_pool(TWENTY)

        assert len(train) == 14
        assert len(holdout) == 6

    def test_the_record_counts_its_pool(self):
        """``world_count`` is both halves — the pool the split was taken over."""
        assert split_pool(TWENTY).world_count == 20

    def test_every_world_answers_exactly_one_half(self):
        """The two predicates are exclusive and exhaustive over the pool: each
        world is one to select on or one to report on, never both, never
        neither."""
        split = split_pool(TWENTY)

        for world in TWENTY:
            assert split.is_train(world) != split.is_holdout(world)

    def test_a_world_the_split_does_not_hold_is_refused_not_answered(self):
        """A world outside the pool is neither train nor holdout, and a
        ``False`` here would let a caller mark an unseen world ``train`` —
        the leak the split exists to prevent, arriving as a return value."""
        split = split_pool(TWENTY)

        with pytest.raises(SplitRequestError) as refusal:
            split.is_holdout("world-that-is-not-in-the-pool")

        assert "is not one of them" in str(refusal.value)

        with pytest.raises(SplitRequestError):
            split.is_train("world-that-is-not-in-the-pool")

    def test_a_non_text_world_is_refused_by_the_predicates(self):
        """The predicates are asked about world ids; a value that names no
        world belongs to neither half."""
        with pytest.raises(SplitRequestError):
            split_pool(TWENTY).is_train(None)

    def test_the_record_carries_what_it_was_decided_over(self):
        """``row()`` names the two halves, the rotation and the fraction —
        *which* 70/30 it was, not only that it was one."""
        split = split_pool(TWENTY, rotation="cycle-2")

        assert split.row() == {
            "train": split.train,
            "holdout": split.holdout,
            "rotation": "cycle-2",
            "train_fraction": Fraction(7, 10),
        }

    def test_a_hand_built_split_may_not_share_a_world(self):
        """The record is a test's prerogative to build and the constructor's
        to police: a world in both halves is the corruption the split exists
        to prevent, refused wherever it is attempted."""
        with pytest.raises(SplitRequestError) as refusal:
            PoolSplit(
                train=("world-aaa", "world-bbb"),
                holdout=("world-bbb", "world-ccc"),
            )

        assert "'world-bbb'" in str(refusal.value)

    def test_two_splits_hash_like_the_values_they_are(self):
        """Immutable values, hashable as their facts — a split is what
        selection and reporting are both made of, and a caller may key on it."""
        first = split_pool(TWENTY, rotation="cycle-3")
        second = split_pool(TWENTY, rotation="cycle-4")

        assert hash(first) == hash(split_pool(TWENTY, rotation="cycle-3"))
        assert len({first, second, first}) == 2


class TestTheFloor:
    """A pool below the ladder floor: feature 275's refusal, delegated."""

    def test_a_pool_below_the_floor_is_refused_in_the_ladders_word(self):
        """Too thin to dream on is too thin to split, and the refusal is the
        floor's own — delegated, not respelled."""
        with pytest.raises(PoolTooThinError) as refusal:
            split_pool(TWENTY[:19])

        assert str(refusal.value).startswith("pool_too_thin")

    def test_a_pool_at_the_floor_splits(self):
        """Meeting the floor is enough; 20 worlds split 14/6."""
        assert len(split_pool(TWENTY).holdout) == 6

    def test_the_floor_is_a_parameter_passed_through_as_the_ladders_gate(self):
        """A deployment that sets its own floor is judged against it, through
        the ladder's own keyword, so the two spellings cannot disagree."""
        with pytest.raises(PoolTooThinError):
            split_pool(TWENTY[:9], floor=10)

        assert len(split_pool(TWENTY[:10], floor=10).holdout) == 3

    def test_a_malformed_floor_is_refused_in_the_ladders_vocabulary(self):
        """The floor is feature 275's fact; a malformed one meets the ladder's
        own class, not the split's."""
        with pytest.raises(PoolTooThinError) as refusal:
            split_pool(TWENTY, floor="20")

        assert str(refusal.value).startswith("pool_too_thin")


class TestThePoolWorlds:
    """The membership read: a world once, whichever half names it."""

    def test_a_world_is_held_once_however_many_score_rows_name_it(self, pool):
        """``replay_score`` names a world once per (policy, world) pair; the
        enumeration answers the worlds, not the replays — and an authored
        world that has also been replayed is still one world."""
        _seed(
            pool,
            ("world-aaa", "world-bbb"),
            ("world-fin-1",),
        )

        assert pool_worlds(sqlite_path(pool)) == (
            "world-aaa",
            "world-bbb",
            "world-fin-1",
        )

    def test_the_enumeration_covers_both_halves_in_id_order(self, pool):
        """Authored worlds and score-only worlds together, each once, in one
        total order — the discipline the commitment reads membership in."""
        _seed(pool, ("world-bbb",), ("world-aaa", "world-ccc"))

        assert pool_worlds(sqlite_path(pool)) == (
            "world-aaa",
            "world-bbb",
            "world-ccc",
        )

    def test_a_database_without_the_pool_is_refused_not_split_empty(
        self, tmp_path: Path
    ):
        """No pool tables is not an empty pool: a split answered over them
        would hand the cycle halves that hold nothing."""
        path = tmp_path / "unrelated.db"
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE unrelated (id TEXT)")

        with pytest.raises(SplitStoreError) as refusal:
            pool_worlds(path)

        assert "no replay_score" in str(refusal.value)

    def test_an_empty_pool_enumerates_empty_and_refuses_to_split(self, pool):
        """Tables and no rows is a genuine pool of zero worlds: it enumerates
        ``()`` — and the split over it is the floor's refusal, not a silent
        0/0 answer, which is the honest division between a read and a gate."""
        assert pool_worlds(sqlite_path(pool)) == ()

        with pytest.raises(PoolTooThinError):
            split_replay_pool(database_url=pool)


class TestTheCall:
    """``split_replay_pool``: the feature's own call, over the store."""

    def test_it_splits_the_pool_it_reads(self, pool):
        """The one act the sentence names: resolve the database, read the
        worlds, answer the two halves — and the document's line unpacks it.
        35 worlds tie at 24.5/10.5 and the odd world goes to the holdout."""
        _seed(pool, tuple(f"world-{index:02d}" for index in range(35)), ())

        train, holdout = split_replay_pool(database_url=pool)

        assert len(train) == 24
        assert len(holdout) == 11

    def test_it_resolves_the_deployments_database(self, pool, monkeypatch):
        """Without an explicit URL the call reads ``DATABASE_URL``, the same
        resolution order every store seam in this member takes."""
        _seed(pool, TWENTY, ())
        monkeypatch.setenv("DATABASE_URL", pool)

        assert split_replay_pool().world_count == 20

    def test_a_deployment_that_names_no_database_is_refused(self, monkeypatch):
        """A split taken over no database would be a split of a pool that
        does not exist — refused by name, never answered ``None``."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(SplitRequestError) as refusal:
            split_replay_pool()

        assert "DATABASE_URL" in str(refusal.value)

    def test_a_url_this_member_cannot_speak_is_translated_at_the_seam(self):
        """The URL rule is the member's one spelling, and the refusal meets
        the caller in the split's vocabulary — never the freeze's."""
        with pytest.raises(SplitRequestError) as refusal:
            split_replay_pool(database_url="postgres://elsewhere/pool")

        message = str(refusal.value)
        assert "sqlite" in message
        assert "refusal it raised" in message
        assert not isinstance(refusal.value, FreezeRequestError)

    def test_the_world_count_is_worlds_not_rows(self, scores):
        """The split's floor judges the pool's *worlds*; a hold's
        ``world_count`` judges its rows — score rows included.  The same
        database answers both figures, and the split pins the divergence
        rather than reconciling it: three worlds, six score rows, one hold
        at nine, one split at three."""
        pool, _ = scores

        hold = CycleFreeze(pool).open("cycle-1")

        split = split_replay_pool(database_url=pool, floor=3)

        assert hold.world_count == 9
        assert split.world_count == 3

    def test_a_thin_pool_meets_the_ladders_refusal_over_the_store(self, scores):
        """The three-world fixture pool, split over the store: below the
        default floor, refused in the floor's own word."""
        pool, _ = scores

        with pytest.raises(PoolTooThinError) as refusal:
            split_replay_pool(database_url=pool)

        assert str(refusal.value).startswith("pool_too_thin")


class TestTheInputs:
    """A malformed ask is refused, not answered — a split is not a guess."""

    def test_a_bare_string_is_refused_as_an_ask_not_split_as_characters(self):
        """Python would iterate a string's characters, and a nine-character
        world id would become nine one-character worlds with nothing looking
        wrong.  The refusal names the trap; it does not fall into it."""
        with pytest.raises(SplitRequestError) as refusal:
            split_pool("world-aaa")

        assert "single" in str(refusal.value)

    def test_a_non_iterable_is_refused(self):
        with pytest.raises(SplitRequestError):
            split_pool(19)

    def test_one_world_twice_is_refused(self):
        """The pool's enumeration is a union; a caller that hands one world
        twice has not enumerated the pool."""
        with pytest.raises(SplitRequestError) as refusal:
            split_pool((*TWENTY, TWENTY[0]))

        assert repr(TWENTY[0]) in str(refusal.value)

    def test_a_non_text_world_is_refused(self):
        with pytest.raises(SplitRequestError):
            split_pool((*TWENTY[:19], 20))

    def test_a_blank_world_is_refused(self):
        with pytest.raises(SplitRequestError):
            split_pool((*TWENTY[:19], "  "))

    def test_a_non_text_rotation_is_refused(self):
        """The rotation is folded into a digest; a discriminator of shifting
        type would make the same rotation answer different splits."""
        with pytest.raises(SplitRequestError):
            split_pool(TWENTY, rotation=7)

    def test_a_fraction_that_empties_a_half_names_no_split(self):
        """A split needs a half to select on and a half to report on."""
        for fraction in (0, 1, Fraction(7, 5), Fraction(-3, 10)):
            with pytest.raises(SplitRequestError):
                split_pool(TWENTY, train_fraction=fraction)

    def test_a_fraction_that_names_no_exact_share_is_refused(self):
        with pytest.raises(SplitRequestError):
            split_pool(TWENTY, train_fraction="most of it")

    def test_a_bool_is_refused_where_a_fraction_belongs(self):
        """``True`` is ``1`` in Python: a flag where a fraction belongs would
        name a pool with no holdout."""
        with pytest.raises(SplitRequestError):
            split_pool(TWENTY, train_fraction=True)
