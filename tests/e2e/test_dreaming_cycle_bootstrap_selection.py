"""Feature: the dreaming cycle's end-to-end journey — a seeded bootstrap pool,
a held cycle, one replay_score row per pair, and a crowned policy revision.

app_spec.xml, "End-to-End Verification": *"System passes an end-to-end test
where a dreaming cycle over a seeded bootstrap pool selects a policy revision
and persists a replay_score row per pair."*  The sentence is the whole of the
dreaming loop's outer iteration, stated as one journey through the assembled
system, and ``docs/alpha-engine-prd.md`` §C5 gives its shape — *"hold the
replay pool fixed, run ``M`` code revisions of ``π``, evaluate each on every
stored tree, select the argmax under §7"* — while ``docs/nullius-tech-
architecture.md`` §10.3.1 puts the figure on the middle clause: *"every
candidate revision against every stored world"*, one score per pair.

Read as one story, the sentence is five acts, and this module runs them in the
order the deployment runs them in:

* **A seeded bootstrap pool.**  Feature 188's own verb — the bootstrap member
    authors §10.6's 40–50 worlds into ``bootstrap_world`` (the replay pool's
    bootstrap half), each named by a pure function of a signed-64 seed, so the
    pool the cycle dreams over is a real membership rather than a number.  This
    is the journey's *input*: the worlds the tournament is held over, and the
    thing feature 270's hold takes a commitment over.
* **A dreaming cycle held over it.**  Feature 270's own verb — the dreaming
    member's :class:`~dreaming.CycleFreeze` opens a hold naming the iteration
    and recording the pool's **commitment** (a sha256 digest over which worlds
    the pool holds) and its size, and installs a database guard over each of
    the pool's two tables.  The hold is the honest statement of *"over a seeded
    bootstrap pool"*: it fixes the input, and its record carries the world
    count the cycle ran over.
* **M revisions of the policy.**  Feature 271's own verb — the dreaming
    member's :func:`~dreaming.revise_policy` answers ``M`` candidate modules,
    one per revision index ``1..M``, each a complete policy source the replay
    engine can replay, each carrying the code hash feature 274 persists.
* **One replay_score row per pair.**  Features 272 and 255's verb — the
    dreaming member's :func:`~dreaming.sweep_candidates` drives a replay
    evaluator once per ``(candidate, world)`` and persists each answer as one
    ``replay_score`` row through the composed replay member's own writer,
    read as ``create_app().get("replay")`` rather than imported.  The
    coverage law is the feature: ``M`` candidates and ``n`` worlds is exactly
    ``M × n`` rows, no pair skipped and none taken twice.  The evidence is
    written **after the hold is released** — feature 270's guards refuse every
    write to the pool's tables while the iteration holds them, so the hold
    fixes the input and the tournament's scores land once the pool is free to
    take them, which is the loop's own ordering, not a bend of the rule.
* **A crowned policy revision.**  Feature 274's verb — the dreaming member's
    :func:`~dreaming.commit_selection` reads the sweep's evidence back from the
    pool's own ``replay_score`` rows, aggregates each candidate under §7 over
    the regime strata, takes the argmax, and persists the winner directly into
    ``policy_revision`` (the table's sole writer) with ``selected`` TRUE.

**One ordering note, stated honestly.**  The sweep writes ``replay_score``, and
``replay_score`` is one of the two tables feature 270's triggers guard, so the
sweep cannot run while the cycle holds the pool.  This module drives the
deployment's order exactly: seed, hold (recording the commitment), produce the
``M`` revisions, *release*, sweep the evidence in, then select and crown.  The
hold's record — the commitment and the world count it captured at open — is the
proof the cycle ran over the seeded pool; the ``M × n`` rows are the proof the
tournament covered every pair; the one ``selected`` row is the proof a revision
was chosen.

**What this module deliberately is not.**  It is not a second suite for the
members' own laws — the refusals, the races, the value layers and the near-
misses live in ``packages/{bootstrap,dreaming,replay}/tests``, and nothing here
re-tests them; this is the journey, once, through the assembled system's public
seams.  It runs in one process, because the sentence names no second interpreter
and no concurrency the journey must stage — the store is one SQLite file and
the five acts are one ordered story, not the risk supervisor's three-process
wedge.  And it does not reset or repair: the hold stands released, the kill of
a prior journey is not this journey's, and the committed rows are read as the
morning-after record the journey leaves behind.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest
from bootstrap import BootstrapPool
from dreaming import (
    REPLAY_SCORE_TABLE,
    WORLD_TABLE,
    CycleFreeze,
    commit_selection,
    pool_worlds,
    revise_policy,
    sqlite_path,
    sweep_candidates,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: §C5's ``M`` — the number of code revisions the loop runs of ``π`` between
#: iterations.  Small on purpose: the journey exercises the coverage law, not
#: the documents' full-rung 40, and a pool this size sits inside feature 188's
#: 40–50 band so the seeded pool is itself in-band.
M_REVISIONS = 3

#: The pool's size for the journey — inside feature 188's ``[40, 50]`` band, so
#: the seeded pool the cycle dreams over is one an operator could stand up, and
#: the hold's recorded world count is a figure §12.1's ladder would let dream.
POOL_SIZE = 45

#: The draw's identity — feature 188's pool seed, the whole of the world draw.
POOL_SEED = 20260922

#: §7.4's single scalar, fixed within the episode — the explore/exploit setting
#: every score row and the selection are measured at.
BETA = 0.5

#: The iteration the cycle is named by — the hold's id, the selection's tag, and
#: the seed the ``M`` revisions are drawn from, so a retried cycle reproduces
#: the same candidates (docs §12's determinism contract).
ITERATION = "cycle-0001"

#: The incumbent policy source §C5's loop revises — small enough to perturb
#: deterministically, carrying a numeric literal the default reviser can jitter.
INCUMBENT = """\
def decide(observation):
    return 0.42 * observation
"""


class _Carrier:
    """A terminal pick carrier answering a miss — feature 255's own two facts.

    The replay member's :class:`~replay.TerminalPick` is the carrier feature
    255's writer reads (``pick`` absent-able, ``score`` always present), but
    this journey reads it duck-typed — *no member imports another* — so it
    stands in a carrier of the same two facts and hands it to the composed
    writer.  ``pick`` is ``None`` because the miss *is* the absent pick, and
    the score is the candidate's revision index, so the tournament's scores
    differ per candidate and the argmax the selection crowns is fixed rather
    than a tie.
    """

    def __init__(self, score: float) -> None:
        self.pick = None
        self.score = score


def _evaluator(candidate: object, world_id: str) -> _Carrier:
    """The replay path's stand-in: one score per candidate, deterministic.

    The journey's only collaborator this module cannot supply — the replay
    path lives in the ``replay`` member and arrives here as a callable taking
    ``(candidate, world_id)``.  It answers the candidate's revision index as
    the score, so every world a candidate ran carries the same figure and the
    §7 aggregate over one stratum is that figure; the highest-indexed revision
    therefore wins the argmax, which the selection facet asserts.
    """
    return _Carrier(score=float(candidate.revision_index))


@dataclass(frozen=True)
class _Journey:
    """What the journey reported, frozen at its end.

    The facts are captured in the order the journey produced them — the seeded
    pool, the hold's recorded commitment, the sweep's coverage and the crowned
    revision — so the facet tests below assert over one story rather than re-
    running the choreography per assertion.
    """

    url: str
    pool_size: int
    world_ids: tuple[str, ...]
    world_seeds: tuple[int, ...]
    hold_opened_worlds: int
    hold_commitment: str
    hold_released: bool
    freeze_rows: int
    freeze_row_world_count: int
    freeze_row_released: bool
    candidate_count: int
    pair_count: int
    replay_score_rows: int
    distinct_pairs: int
    winner_module_id: str
    winner_revision_index: int
    selected_rows: int
    selected_policy_version: str
    selected_code_hash: str


def _migration_apply(module_name: str, path: Path, database_url: str) -> None:
    """Load a standalone migration module by path and run its ``apply``.

    The migration chain is not an importable package — it is a directory of
    standalone modules the migration runner loads by path — so it is loaded the
    same way here: by file location, not by import name.  Feature 1's own
    migration creates ``replay_score`` and ``policy_revision`` in ``0109``'s
    columns, the single source of truth for the tables the sweep writes and the
    selection crowns over, rather than a restatement that could drift.
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.apply(database_url)


def _stand_up_pool_tables(url: str) -> None:
    """Bring a fresh database to the pool's shape — both pool tables present.

    The two halves of the replay pool, each stood up by its own owner: feature
    188's ``bootstrap_world`` by the bootstrap member's own ``ensure_schema``
    (the table's sole author, with its real columns and provenance widening),
    and migration ``0109``'s ``replay_score`` + ``policy_revision`` by feature
    1's own migration — the single source of truth for the tables the sweep
    writes and the selection crowns over.  Both are present before the hold
    opens, because feature 270's ``open()`` refuses a database holding no pool
    table.
    """
    BootstrapPool(url).ensure_schema()
    _migration_apply(
        "migration_0109",
        REPO_ROOT / "migrations/versions/0109_replay_score_and_policy_revision.py",
        url,
    )


@pytest.fixture(scope="module")
def journey(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Journey]:
    """Run the journey once, and hand its captured facts to the facets.

    The journey's own SQLite URL, not the suite's isolated ``DATABASE_URL``:
    the five acts are one ordered story over one throwaway store, and the
    committed-record assertions read it back with the driver directly.
    """
    workdir = tmp_path_factory.mktemp("dreaming-cycle")
    url = f"sqlite:///{workdir / 'nullius-e2e.db'}"

    # Both pool tables present before the hold opens (open() refuses a missing
    # pool table), then the bootstrap member authors the worlds into its half.
    _stand_up_pool_tables(url)
    pool = BootstrapPool(url)
    pool.persist_worlds(POOL_SIZE, pool_seed=POOL_SEED)

    world_ids = pool_worlds(sqlite_path(url))
    with closing(sqlite3.connect(url.removeprefix("sqlite:///"))) as connection:
        world_seeds = tuple(
            row[0] for row in connection.execute(f"SELECT seed FROM {WORLD_TABLE}").fetchall()
        )

    # The cycle opens its hold over the seeded pool, recording the commitment.
    freeze = CycleFreeze(url)
    hold = freeze.open(ITERATION)

    # M revisions of the incumbent, produced the way the loop produces them.
    candidates = revise_policy(INCUMBENT, M_REVISIONS, seed=ITERATION)

    # The hold fixes the input; the evidence is written once it is released.
    released = freeze.release(hold)

    # One replay_score row per (candidate, world) pair, through the composed replay.
    report = sweep_candidates(
        candidates,
        evaluator=_evaluator,
        beta=BETA,
        database_url=url,
    )

    # Select the argmax over the sweep's evidence and crown the winner.
    strata = {"regime": world_ids}
    winner = commit_selection(
        candidates,
        strata=strata,
        beta=BETA,
        database_url=url,
        iteration_id=ITERATION,
    )

    # The committed record, read with the driver after the journey has run.
    with closing(sqlite3.connect(url.removeprefix("sqlite:///"))) as connection:
        replay_score_rows = int(
            connection.execute(f"SELECT COUNT(*) FROM {REPLAY_SCORE_TABLE}").fetchone()[0]
        )
        distinct_pairs = int(
            connection.execute(
                f"SELECT COUNT(DISTINCT policy_version || '|' || world_id) "
                f"FROM {REPLAY_SCORE_TABLE}"
            ).fetchone()[0]
        )
        freeze_rows = int(
            connection.execute("SELECT COUNT(*) FROM pool_freeze").fetchone()[0]
        )
        freeze_row = connection.execute(
            "SELECT world_count, released_at FROM pool_freeze ORDER BY id LIMIT 1"
        ).fetchone()
        selected = connection.execute(
            "SELECT policy_version, code_hash FROM policy_revision WHERE selected = TRUE"
        ).fetchall()

    (selected_policy_version, selected_code_hash) = selected[0]
    (freeze_row_world_count, freeze_row_released_at) = freeze_row

    yield _Journey(
        url=url,
        pool_size=len(world_ids),
        world_ids=world_ids,
        world_seeds=world_seeds,
        hold_opened_worlds=hold.world_count,
        hold_commitment=hold.commitment,
        hold_released=not released.is_open,
        freeze_rows=freeze_rows,
        freeze_row_world_count=freeze_row_world_count,
        freeze_row_released=freeze_row_released_at is not None,
        candidate_count=len(candidates),
        pair_count=len(report),
        replay_score_rows=replay_score_rows,
        distinct_pairs=distinct_pairs,
        winner_module_id=winner.module_id,
        winner_revision_index=int(winner.revision_index),
        selected_rows=len(selected),
        selected_policy_version=selected_policy_version,
        selected_code_hash=selected_code_hash,
    )


# -- Facet 1: the seeded bootstrap pool ----------------------------------------


class TestTheSeededBootstrapPool:
    """The journey's input — a real pool of worlds, in feature 188's band."""

    def test_the_pool_is_in_the_documented_band(self, journey: _Journey) -> None:
        """§10.6's 40–50 worlds — the band feature 188's count refuses to leave."""
        assert 40 <= journey.pool_size <= 50
        assert journey.pool_size == POOL_SIZE

    def test_every_world_is_named(self, journey: _Journey) -> None:
        """One non-empty world id per seeded world, and none twice."""
        assert journey.pool_size == len(journey.world_ids)
        assert all(isinstance(world_id, str) and world_id.strip() for world_id in journey.world_ids)
        assert len(set(journey.world_ids)) == len(journey.world_ids)

    def test_the_worlds_carry_signed_64_seeds(self, journey: _Journey) -> None:
        """Feature 188's seeds are signed 64-bit integers, one per world."""
        assert journey.pool_size == len(journey.world_seeds)
        assert all(isinstance(seed, int) and not isinstance(seed, bool) for seed in journey.world_seeds)
        assert all(-(2**63) <= seed < 2**63 for seed in journey.world_seeds)


# -- Facet 2: the cycle held the seeded pool -----------------------------------


class TestTheCycleHeldTheSeededPool:
    """Feature 270's hold — the commitment over the seeded worlds, recorded."""

    def test_the_hold_recorded_the_pool_it_opened_over(self, journey: _Journey) -> None:
        """The hold's recorded world count is the seeded pool's size."""
        assert journey.hold_opened_worlds == journey.pool_size

    def test_the_commitment_is_a_membership_digest(self, journey: _Journey) -> None:
        """The commitment is a 64-hex sha256 over which worlds the pool holds."""
        assert len(journey.hold_commitment) == 64
        int(journey.hold_commitment, 16)  # a hex digest, not a flag

    def test_the_hold_row_stands_and_records_the_pool(self, journey: _Journey) -> None:
        """Exactly one ``pool_freeze`` row, carrying the pool's size, now released."""
        assert journey.freeze_rows == 1
        assert journey.freeze_row_world_count == journey.pool_size
        assert journey.freeze_row_released is True

    def test_the_hold_was_released(self, journey: _Journey) -> None:
        """The cycle ended its hold before the evidence was written."""
        assert journey.hold_released is True


# -- Facet 3: one replay_score row per pair ------------------------------------


class TestTheSweepPersistedAPerPairScore:
    """Features 272/255 — the coverage law, read back out of the store."""

    def test_one_row_landed_per_pair(self, journey: _Journey) -> None:
        """``M × n`` rows — no pair skipped and none taken twice."""
        assert journey.replay_score_rows == M_REVISIONS * journey.pool_size
        assert journey.pair_count == M_REVISIONS * journey.pool_size
        assert journey.distinct_pairs == M_REVISIONS * journey.pool_size

    def test_every_candidate_ran_every_world(self, journey: _Journey) -> None:
        """Each of the ``M`` candidates carries exactly ``n`` score rows."""
        assert journey.replay_score_rows == journey.candidate_count * journey.pool_size
        assert journey.candidate_count == M_REVISIONS

    def test_the_rows_were_scored_at_the_episodes_beta(self, journey: _Journey) -> None:
        """§7.4's single scalar, fixed within the episode — every row at ``BETA``."""
        path = journey.url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            at_beta = connection.execute(
                f"SELECT COUNT(*) FROM {REPLAY_SCORE_TABLE} WHERE beta = ?", (BETA,)
            ).fetchone()[0]
        assert int(at_beta) == journey.replay_score_rows


# -- Facet 4: the argmax crowned one revision ----------------------------------


class TestTheSelectionCrownedOneRevision:
    """Feature 274 — the winner persisted as the ``selected`` row of ``policy_revision``."""

    def test_exactly_one_revision_was_selected(self, journey: _Journey) -> None:
        """The selector crowns one, not a row per candidate."""
        assert journey.selected_rows == 1

    def test_the_crowned_revision_is_the_argmax_winner(self, journey: _Journey) -> None:
        """The persisted ``policy_version`` is the winner's module id, with its hash."""
        assert journey.selected_policy_version == journey.winner_module_id
        assert len(journey.selected_code_hash) == 64
        int(journey.selected_code_hash, 16)

    def test_the_winner_is_the_highest_scored_revision(self, journey: _Journey) -> None:
        """The evaluator scored each candidate by its revision index, so the
        top-indexed revision — the one every world scored highest — wins the
        §7 argmax, and the crowned row carries that identity.
        """
        assert journey.winner_revision_index == M_REVISIONS
        assert journey.selected_policy_version == journey.winner_module_id
