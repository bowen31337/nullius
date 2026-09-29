"""Feature 272's claim, stated as tests: every candidate against every world.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 272: *System evaluates
every candidate revision against every stored world, persisting one score per
pair.*  docs/alpha-engine-prd.md §C5 places the act as the middle clause of the
loop — *"hold the replay pool fixed, run M code revisions of π, evaluate each
on every stored tree, select the argmax under §7"* — and §10.3.1 puts the
figure on it: *"200 worlds × 40 policy revisions … embarrassingly parallel"*.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* **the coverage law is the feature.**  ``M`` candidates and ``n`` worlds is
  exactly ``M × n`` pairs — no pair skipped and none taken twice — and the plan
  :func:`~dreaming.sweep.plan_sweep` answers is that claim *before* a single
  replay is paid for.  A test that only checked *rows were written* would pass
  against a sweep that wrote a plausible number of them over the wrong cross
  product;
* **the plan is pure.**  It reads no database, opens no policy and runs
  nothing, so ``plan_sweep`` is asserted against the documents with no fixture
  at all — the shape :func:`dreaming.split.split_pool` and
  :func:`dreaming.ceiling.rejects_uncapped_sweep` are pinned in;
* **the row is the replay member's, and the sweep writes none of it itself.**
  Persistence is delegated to the composed replay component's own
  ``persist_replay_score``, reached through the composed application
  (``create_app().get("replay")``) without any member importing another — so
  the store seam is exercised against a real ``replay_score`` row, read back
  with ``PRAGMA table_info`` and a ``SELECT``;
* **the two axes are validated separately and named separately**, because a
  sweep's asks are many: a candidate that is not a candidate module, a bare
  candidate where a set belongs, an empty set, two candidates under one
  version, a bare string where worlds belong, a world twice, a blank id, a
  beta that is not a finite number — each refused with its own subject in the
  message;
* **the marking comes from the split's own predicate.**  A split passed in
  marks each row's ``is_holdout`` through
  :meth:`~dreaming.split.PoolSplit.is_holdout` — the seam ``0109``'s column
  exists to carry — and a set taken with no split writes ``False``, which is
  what that column's default means for *the row that never asked*;
* **the hold is feature 270's, translated and never bent.**  A sweep attempted
  while a cycle holds the pool is **refused** in feature 270's own word
  (:class:`~dreaming.errors.PoolFrozenError`), and the refusal is *translated
  at the sweep's seam* from the replay member's wrapper — the discipline the
  member's other seams state — rather than swallowed, worked around or written
  through a second connection;
* **the store's two failures are different repairs**, and neither is the
  sweep's ask: a database with no pool to sweep over, and a pair whose
  evidence measured but never landed.
"""

from __future__ import annotations

import ast
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from dreaming import (
    FREEZE_CODE,
    REPLAY_SCORE_TABLE,
    SWEEP_CODE,
    SWEEP_STORE_CODE,
    DreamingError,
    PoolFrozenError,
    PoolSplit,
    SplitStoreError,
    SweepPair,
    SweepRequestError,
    SweepStoreError,
    candidate_module,
    plan_sweep,
    pool_worlds,
    revise_policy,
    split_pool,
    sqlite_path,
    sweep_candidates,
)

#: §C5's own figures, spelled once so every test below is written against the
#: documents rather than against a number this file invented.  The section:
#: *"200 worlds × 40 policy revisions"*, and §10.3.1's ``M = 40`` on the full
#: rung.  The suite never *runs* 8000 pairs — it plans them, which is the claim
#: ``plan_sweep`` exists to make checkable without paying for the replay.
PRD_WORLDS = 200
PRD_REVISIONS = 40

#: The incumbent §C5's loop revises, small enough to perturb deterministically.
INCUMBENT = """\
def decide(observation):
    return 0.42 * observation
"""


def _candidates(count: int = 3):
    """``count`` distinct candidate modules, produced the way the loop produces them."""
    return revise_policy(INCUMBENT, count)


class _Carrier:
    """A terminal pick carrier answering a miss — feature 255's own two facts.

    The replay member's :class:`~replay.TerminalPick` is the carrier feature
    255's writer reads (``pick`` absent-able, ``score`` always present), but
    this module reads it duck-typed — *no member imports another* — so the
    suite stands in a carrier of the same two facts: the sweep never inspects
    the type, only hands the value to the writer.  ``pick`` is ``None``
    because the miss *is* the absent pick, and the score is a parameter
    because the sweep persists whatever the evaluator answered.
    """

    def __init__(self, score: float = -float("inf")) -> None:
        self.pick = None
        self.score = score


def _miss(score: float = -float("inf")) -> _Carrier:
    """One miss, scored — the smallest complete answer a replay can give."""
    return _Carrier(score)


class _Pick:
    """A committed pick, duck-typed the way feature 222's carries one.

    ``0125``-era committed picks carry the node the policy terminated at; the
    replay member's writer reads the node id off whatever it is handed and
    stores it in ``replay_score``'s nullable ``committed_pick`` column.  This
    stands in for that shape: an object carrying an id and nothing else, so
    the sweep's persistence of a *committing* evaluator is exercised without
    this suite importing the replay member.
    """

    def __init__(self, node_id: str = "node-committed") -> None:
        self.node_id = node_id


def _committed(score: float = 1.0, *, node_id: str = "node-committed") -> _Carrier:
    """One committed answer — a pick *and* a score, the ordinary replay outcome."""
    carrier = _Carrier(score)
    carrier.pick = _Pick(node_id)
    return carrier


def _split_of(worlds: tuple[str, ...], holdout: tuple[str, ...] = ()) -> PoolSplit:
    """A split over ``worlds`` with a stated reporting half — built, not taken.

    The ``scores`` fixture's pool holds three worlds, which is **below** §12.1's
    ladder floor, so :func:`~dreaming.split.split_pool` correctly refuses to
    split it — a pool too thin to dream on has no halves to rotate, and the
    refusal is feature 275's, in the floor's own word.  The sweep's own seam
    takes any object answering ``is_holdout``, so these tests build the
    :class:`~dreaming.split.PoolSplit` directly and thereby exercise the
    duck-typing the seam is written to: the sweep asks the predicate, never the
    type.  The tests that pin the *taken* split's arithmetic run against
    ``split_pool`` over a pool that meets the floor — pure, with no store.
    """
    return PoolSplit(
        train=tuple(world for world in worlds if world not in set(holdout)),
        holdout=holdout,
    )


def _written(url: str, policy_version: str | None = None) -> list[tuple]:
    """Every ``replay_score`` row this database holds, newest last.

    Read back with the eight columns ``0109`` legislates, so a test asserts
    about *the rows the store actually holds* rather than about a return value
    the sweep could have fabricated — the discipline the member's other store
    seams are pinned with.
    """
    with closing(sqlite3.connect(sqlite_path(url))) as connection:
        rows = connection.execute(
            f"SELECT id, policy_version, world_id, beta, score, committed_pick, "
            f"is_holdout, created_at FROM {REPLAY_SCORE_TABLE} ORDER BY rowid"
        ).fetchall()
    if policy_version is not None:
        rows = [row for row in rows if row[1] == policy_version]
    return rows


class TestTheCoverageLaw:
    """``M × n`` pairs, and the plan is what makes that checkable."""

    def test_every_candidate_is_crossed_with_every_world(self):
        """The feature's sentence, as an arithmetic identity."""
        candidates = _candidates(3)
        worlds = ("w-a", "w-b", "w-c", "w-d")

        plan = plan_sweep(candidates, worlds)

        assert len(plan) == len(candidates) * len(worlds) == 12
        assert {pair.world_id for pair in plan} == set(worlds)
        assert {pair.module_id for pair in plan} == {
            candidate.module_id for candidate in candidates
        }
        # Every pair, exactly once — the cross product itself, not merely its
        # cardinality.  A sweep that skipped one pair and repeated another
        # would answer the same length.
        assert len(set(plan)) == len(plan)
        assert {
            (pair.module_id, pair.world_id) for pair in plan
        } == {
            (candidate.module_id, world_id)
            for candidate in candidates
            for world_id in worlds
        }

    def test_the_documents_figures_are_the_cross_product(self):
        """§C5's 200 worlds × 40 revisions is 8000 pairs — planned, not run.

        The one test that speaks the documents' own scale, and the reason
        :func:`plan_sweep` is a pure function: the coverage claim is checkable
        without paying for the replays it describes.
        """
        worlds = tuple(f"world-{index:03d}" for index in range(PRD_WORLDS))
        candidates = [
            candidate_module(f"def decide(observation):\n    return {index}.0\n",
                             revision_index=index + 1)
            for index in range(PRD_REVISIONS)
        ]

        plan = plan_sweep(candidates, worlds)

        assert len(plan) == PRD_WORLDS * PRD_REVISIONS == 8000
        assert len(set(plan)) == 8000

    def test_each_candidate_owns_a_full_column_of_the_product(self):
        """One candidate's worlds are *all* the worlds — the column is square."""
        candidates = _candidates(4)
        worlds = ("w-a", "w-b", "w-c")

        plan = plan_sweep(candidates, worlds)

        for candidate in candidates:
            column = [pair.world_id for pair in plan if pair.module_id == candidate.module_id]
            assert column == list(worlds)

    def test_the_plan_follows_the_candidates_order(self):
        """The candidates' own order, and the worlds' within each — no second sort."""
        candidates = _candidates(2)
        worlds = ("w-a", "w-b")

        plan = plan_sweep(candidates, worlds)

        assert [pair.module_id for pair in plan] == [
            candidates[0].module_id,
            candidates[0].module_id,
            candidates[1].module_id,
            candidates[1].module_id,
        ]

    def test_the_pair_carries_the_facts_the_evidence_is_filed_under(self):
        """``code_hash`` and ``module_id`` cross into the plan, and the row's name agrees."""
        (candidate,) = _candidates(1)

        (pair,) = plan_sweep([candidate], ("w-a",))

        assert pair.code_hash == candidate.code_hash
        assert pair.module_id == candidate.module_id
        assert pair.policy_version == candidate.module_id
        assert pair.revision_index == candidate.revision_index == 1

    def test_the_plan_is_pure_and_reads_nothing(self):
        """No database, no store, no fixture — the verdict shape the member states."""
        plan = plan_sweep(_candidates(2), ("w-a", "w-b"))

        assert all(isinstance(pair, SweepPair) for pair in plan)

    def test_the_documents_call_site_runs(self):
        """§10.3.1's ``train, holdout = pool.split(0.7, ...)`` feeds the axis.

        The split's two halves recombined are the pool — so a plan taken over
        ``train + holdout`` covers exactly the world set the split was drawn
        over, and every pair's ``is_holdout`` is the split's own answer rather
        than a second derivation of the 70/30 rule here.
        """
        worlds = tuple(f"world-{index:03d}" for index in range(30))
        split = split_pool(worlds)
        train, holdout = split

        plan = plan_sweep(_candidates(2), train + holdout, split=split)

        assert {pair.world_id for pair in plan} == set(worlds)
        assert {pair.world_id for pair in plan if pair.is_holdout} == set(holdout)
        assert {pair.world_id for pair in plan if not pair.is_holdout} == set(train)

    def test_the_marking_is_the_splits_own_predicate(self):
        """The seam ``0109``'s column exists to carry, read from the split itself."""
        worlds = tuple(f"world-{index:03d}" for index in range(20))
        split = split_pool(worlds)

        plan = plan_sweep(_candidates(1), worlds, split=split)

        for pair in plan:
            assert pair.is_holdout is split.is_holdout(pair.world_id)
            assert pair.is_holdout is not split.is_train(pair.world_id)

    def test_a_sweep_with_no_split_taken_marks_nothing_holdout(self):
        """``False`` is the column's default for exactly the row that never asked."""
        plan = plan_sweep(_candidates(2), ("w-a", "w-b"))

        assert all(pair.is_holdout is False for pair in plan)


class TestTheAsksAreNamedOneByOne:
    """A sweep's asks are many, so each malformed one names itself."""

    @pytest.mark.parametrize(
        "candidates",
        [
            pytest.param("a candidate module", id="a-bare-string"),
            pytest.param(None, id="no-candidates"),
            pytest.param([], id="an-empty-set"),
            pytest.param((), id="an-empty-tuple"),
        ],
    )
    def test_a_set_that_names_no_cross_product_is_refused(self, candidates):
        """The first axis, refused before any world is read."""
        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep(candidates, ("w-a",))

        assert str(refusal.value).startswith(SWEEP_CODE)

    def test_a_bare_candidate_module_is_refused_where_a_set_belongs(self):
        """One candidate is a *set of one*, and it has to be said so."""
        (candidate,) = _candidates(1)

        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep(candidate, ("w-a",))

        assert str(refusal.value).startswith(SWEEP_CODE)

    def test_a_candidate_without_an_identity_is_refused_and_names_what_is_missing(self):
        """A score nobody could attribute to a revision is not evidence."""

        class _Anonymous:
            module_id = "cand-1"

        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep([_Anonymous()], ("w-a",))

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert "code_hash" in str(refusal.value)

    @pytest.mark.parametrize("identity", [1, "", "   ", None, b"bytes"])
    def test_a_candidate_identity_that_is_not_text_is_refused(self, identity):
        """``module_id`` files the row; a value that is not text files nothing."""

        class _Candidate:
            module_id = identity
            code_hash = "a" * 64

        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep([_Candidate()], ("w-a",))

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert "module_id" in str(refusal.value)

    @pytest.mark.parametrize("index", [0, -1, 1.5, True])
    def test_a_revision_index_that_is_not_an_index_is_refused(self, index):
        """The candidate's place in the sweep, as a genuine positive integer."""
        (candidate,) = _candidates(1)

        class _Candidate:
            module_id = candidate.module_id
            code_hash = candidate.code_hash
            revision_index = index

        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep([_Candidate()], ("w-a",))

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert "revision_index" in str(refusal.value)

    def test_two_candidates_under_one_version_are_refused(self):
        """Two revisions' evidence under one ``policy_version`` is unattributable."""
        (first,) = _candidates(1)

        class _Twin:
            module_id = first.module_id
            code_hash = "b" * 64

        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep([first, _Twin()], ("w-a",))

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert first.module_id in str(refusal.value)

    @pytest.mark.parametrize(
        "worlds",
        [
            pytest.param("world-a", id="a-bare-string"),
            pytest.param(None, id="no-worlds"),
            pytest.param([], id="an-empty-set"),
            pytest.param((1, 2), id="non-text-ids"),
            pytest.param(("world-a", "  "), id="a-blank-id"),
        ],
    )
    def test_a_second_axis_that_names_no_worlds_is_refused(self, worlds):
        """The pool's worlds, refused for the reason the split refuses its own."""
        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep(_candidates(1), worlds)

        assert str(refusal.value).startswith(SWEEP_CODE)

    def test_a_world_twice_is_refused_rather_than_double_written(self):
        """A world on both sides of the product writes two rows for one pair."""
        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep(_candidates(1), ("w-a", "w-b", "w-a"))

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert "w-a" in str(refusal.value)

    def test_a_world_the_split_does_not_hold_is_refused_in_the_sweeps_word(self):
        """Feature 278's refusal, translated at this seam — a sweep asked about it."""
        split = split_pool(tuple(f"world-{index:03d}" for index in range(20)))

        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep(_candidates(1), ("world-not-in-the-pool",), split=split)

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert "world-not-in-the-pool" in str(refusal.value)
        assert refusal.value.__cause__ is not None
        assert isinstance(refusal.value.__cause__, DreamingError)

    def test_a_split_without_the_predicate_is_refused_before_any_marking(self):
        """A split-shaped value the marking cannot ask would mark every row ``False``."""

        class _NotASplit:
            train = ("w-a",)
            holdout = ("w-b",)

        with pytest.raises(SweepRequestError) as refusal:
            plan_sweep(_candidates(1), ("w-a",), split=_NotASplit())

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert "is_holdout" in str(refusal.value)

    @pytest.mark.parametrize(
        "beta",
        [
            pytest.param(True, id="a-bool"),
            pytest.param("0.5", id="a-string"),
            pytest.param(None, id="nothing"),
            pytest.param(float("inf"), id="an-infinity"),
            pytest.param(float("nan"), id="a-nan"),
        ],
    )
    def test_a_beta_that_is_not_a_finite_number_is_refused(self, beta, pool):
        """The scoring setting, refused before a pair is planned or a row written."""
        with pytest.raises(SweepRequestError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=beta,
                worlds=("world-aaa",),
                database_url=pool,
            )

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert _written(pool) == []

    def test_an_evaluator_that_cannot_be_called_is_refused(self, pool):
        """The one collaborator this member cannot supply, named before any pair."""
        with pytest.raises(SweepRequestError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=None,
                beta=0.5,
                worlds=("world-aaa",),
                database_url=pool,
            )

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert "evaluator" in str(refusal.value)

    def test_the_asks_are_refused_before_the_store_is_ever_touched(self):
        """Every ask's own fact, checked before a URL is resolved or a store opened.

        The member's ordering law, and the reason it matters here more than
        elsewhere: a sweep's asks are ``M × n`` of them, so an ask that is
        wrong is *the same wrong* however many times it is re-sent — while a
        store touched by a malformed sweep is a store some other act is now
        racing.  Proved by handing a URL this member *cannot speak* together
        with each broken ask: the ask's own class must win, and its message
        must be the sweep's ask code rather than the URL's.
        """
        for broken in (
            {"candidates": "a bare candidate"},
            {"candidates": []},
            {"beta": None},
            {"beta": float("nan")},
            {"evaluator": None},
            {"split": object()},
        ):
            arguments = {
                "candidates": _candidates(1),
                "evaluator": lambda candidate, world_id: _miss(),
                "beta": 0.5,
                "worlds": ("world-aaa",),
                "database_url": "postgresql://a-url-this-member-cannot-speak/db",
            }
            arguments.update(broken)

            with pytest.raises(SweepRequestError) as refusal:
                sweep_candidates(**arguments)

            assert str(refusal.value).startswith(SWEEP_CODE), broken
            assert "postgresql" not in str(refusal.value), broken

    def test_no_database_named_is_refused(self, monkeypatch):
        """§C5's *every stored world* is a claim about a store."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(SweepRequestError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
            )

        assert str(refusal.value).startswith(SWEEP_CODE)

    def test_a_url_this_member_cannot_speak_is_refused_in_the_sweeps_word(self):
        """Feature 270's URL translation, re-raised as the sweep's ask."""
        with pytest.raises(SweepRequestError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
                database_url="postgresql://host/db",
            )

        assert str(refusal.value).startswith(SWEEP_CODE)
        assert refusal.value.__cause__ is not None


class TestTheStoreSeam:
    """One ``replay_score`` row per pair, written through the replay member's writer."""

    def test_one_row_lands_per_pair_and_none_is_skipped(self, scores):
        """The coverage law, read back out of the store rather than off the report."""
        url, _ = scores
        candidates = _candidates(2)
        worlds = ("world-aaa", "world-bbb", "world-ccc")

        report = sweep_candidates(
            candidates,
            evaluator=lambda candidate, world_id: _miss(),
            beta=0.5,
            worlds=worlds,
            database_url=url,
        )

        rows = _written(url)
        # The fixture's own six rows are the pool's *input*; the sweep's rows
        # are the ones filed under its candidates.
        swept = [
            row for row in rows
            if row[1] in {candidate.module_id for candidate in candidates}
        ]
        assert len(swept) == len(candidates) * len(worlds) == 6
        assert len(report) == 6
        assert len(report.rows) == 6
        assert {
            (row[1], row[2]) for row in swept
        } == {
            (candidate.module_id, world_id)
            for candidate in candidates
            for world_id in worlds
        }

    def test_the_row_carries_the_four_facts_the_sweep_hands_over(self, scores):
        """``policy_version``, ``world_id``, ``beta`` and ``is_holdout`` — the writer's own row."""
        url, _ = scores
        (candidate,) = _candidates(1)

        report = sweep_candidates(
            [candidate],
            evaluator=lambda candidate, world_id: _miss(-3.25),
            beta=0.25,
            worlds=("world-aaa",),
            database_url=url,
        )

        (row,) = [
            row for row in _written(url) if row[1] == candidate.module_id
        ]
        assert row[0] == report.rows[0]
        assert row[1] == candidate.module_id
        assert row[2] == "world-aaa"
        assert row[3] == 0.25
        assert row[4] == -3.25
        assert row[5] is None
        assert row[6] in (0, False)

    def test_a_committing_evaluator_persists_its_pick_beside_its_score(self, scores):
        """The ordinary replay outcome: a pick *and* a score, both on the row.

        The miss is the case the coverage law is easiest to state for — the row
        is written either way — but a *committing* answer is what a real replay
        usually produces, and ``replay_score``'s nullable ``committed_pick``
        column is the one field the sweep never names: it crosses from the
        evaluator's carrier to the writer untouched, which is what keeps the
        decision that *was* made distinguishable from the one that was not
        (``0109``'s own polarity, feature 255's).
        """
        url, _ = scores
        (candidate,) = _candidates(1)

        sweep_candidates(
            [candidate],
            evaluator=lambda candidate, world_id: _committed(2.5, node_id="node-x"),
            beta=0.25,
            worlds=("world-aaa",),
            database_url=url,
        )

        (row,) = [row for row in _written(url) if row[1] == candidate.module_id]
        assert row[4] == 2.5
        assert row[5] == "node-x"
        # With no split taken the column holds ``0109``'s default, which is the
        # honest reading of a row that was never asked the question.
        assert row[6] in (0, False)

    def test_the_split_marks_the_row_the_column_exists_to_carry(self, scores):
        """``is_holdout`` on the row, read from the split's own predicate."""
        url, _ = scores
        worlds = ("world-aaa", "world-bbb", "world-ccc")
        split = _split_of(worlds, holdout=("world-ccc",))
        (candidate,) = _candidates(1)

        sweep_candidates(
            [candidate],
            evaluator=lambda candidate, world_id: _miss(),
            beta=0.5,
            worlds=worlds,
            split=split,
            database_url=url,
        )

        marked = {
            row[2]: bool(row[6])
            for row in _written(url)
            if row[1] == candidate.module_id
        }
        assert marked == {"world-aaa": False, "world-bbb": False, "world-ccc": True}
        assert marked == {world_id: split.is_holdout(world_id) for world_id in worlds}

    def test_the_worlds_are_read_from_the_store_when_none_are_handed_over(self, scores):
        """*Every **stored** world* — the feature's own words, taken literally."""
        url, _ = scores

        report = sweep_candidates(
            _candidates(1),
            evaluator=lambda candidate, world_id: _miss(),
            beta=0.5,
            database_url=url,
        )

        assert report.worlds == pool_worlds(sqlite_path(url))
        assert report.world_count == 3
        assert report.pair_count == 3

    def test_the_report_is_a_summary_and_no_verdict(self, scores):
        """No average, no argmax, no ranking — the selection is feature 274's."""
        url, _ = scores

        report = sweep_candidates(
            _candidates(3),
            evaluator=lambda candidate, world_id: _miss(-1.0),
            beta=0.5,
            worlds=("world-aaa", "world-bbb"),
            database_url=url,
        )

        row = report.row()
        assert row["candidate_count"] == 3
        assert row["world_count"] == 2
        assert row["pair_count"] == 6
        assert row["worlds"] == ["world-aaa", "world-bbb"]
        assert len(row["pairs"]) == 6
        assert not hasattr(report, "winner")
        assert not hasattr(report, "best")

    def test_a_candidates_column_is_the_worlds_it_ran(self, scores):
        """The read feature 274 takes before it aggregates one candidate."""
        url, _ = scores
        candidates = _candidates(2)
        worlds = ("world-aaa", "world-bbb")

        report = sweep_candidates(
            candidates,
            evaluator=lambda candidate, world_id: _miss(),
            beta=0.5,
            worlds=worlds,
            database_url=url,
        )

        column = report.scores_for(candidates[0].module_id)
        assert [pair.world_id for pair in column] == list(worlds)
        with pytest.raises(SweepRequestError) as refusal:
            report.scores_for("cand-never-ran")
        assert str(refusal.value).startswith(SWEEP_CODE)

    def test_the_evaluator_is_asked_once_per_pair_in_the_plans_order(self, scores):
        """``M × n`` calls, each naming its own pair — no pair left unevaluated."""
        url, _ = scores
        candidates = _candidates(2)
        worlds = ("world-aaa", "world-bbb", "world-ccc")
        asked: list[tuple[str, str]] = []

        def evaluator(candidate, world_id):
            asked.append((candidate.module_id, world_id))
            return _miss()

        report = sweep_candidates(
            candidates,
            evaluator=evaluator,
            beta=0.5,
            worlds=worlds,
            database_url=url,
        )

        assert asked == [(pair.module_id, pair.world_id) for pair in report]
        assert len(asked) == 6

    def test_the_sweep_persists_through_the_replay_members_own_writer(self, scores):
        """The row is feature 255's; the sweep spells none of its columns itself.

        A *spy* writer stands in for the composed component here so the seam is
        asserted directly: the sweep hands it the answer and the pair's four
        facts under feature 255's own parameter names, and takes back the id
        the writer minted.
        """
        url, _ = scores
        calls: list[tuple] = []

        class _Writer:
            def persist_replay_score(
                self, pick, policy_version, world_id, beta, *, is_holdout=False,
                database_url=None,
            ):
                calls.append((pick, policy_version, world_id, beta, is_holdout, database_url))
                return f"row-{len(calls)}"

        (candidate,) = _candidates(1)

        report = sweep_candidates(
            [candidate],
            evaluator=lambda candidate, world_id: _miss(-2.0),
            beta=0.75,
            worlds=("world-aaa",),
            split=_split_of(("world-aaa",), holdout=("world-aaa",)),
            database_url=url,
            replay=_Writer(),
        )

        assert len(calls) == 1
        answer, version, world_id, beta, is_holdout, named = calls[0]
        assert answer.score == -2.0
        assert version == candidate.module_id
        assert world_id == "world-aaa"
        assert beta == 0.75
        assert is_holdout is True
        assert named == url
        assert report.rows == ("row-1",)

    def test_a_carrier_without_the_writer_is_refused_by_name(self, scores):
        """A seam that names no store the evidence could reach."""
        url, _ = scores

        with pytest.raises(SweepStoreError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
                worlds=("world-aaa",),
                database_url=url,
                replay=object(),
            )

        assert str(refusal.value).startswith(SWEEP_STORE_CODE)

    def test_a_database_with_no_pool_is_refused_before_any_pair_is_planned(
        self, database_url
    ):
        """No pool here to sweep over — a store fact, not an ask."""
        import sqlite3 as driver

        with closing(driver.connect(sqlite_path(database_url))):
            pass

        with pytest.raises(SweepStoreError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
                database_url=database_url,
            )

        assert str(refusal.value).startswith(SWEEP_STORE_CODE)
        assert REPLAY_SCORE_TABLE in str(refusal.value)
        assert refusal.value.__cause__ is not None
        assert isinstance(refusal.value.__cause__, SplitStoreError)

    def test_a_row_that_will_not_land_is_refused_rather_than_skipped(self, scores):
        """§C5's coverage law: a report whose pairs outnumber its rows is a lie."""
        url, _ = scores

        class _RefusingWriter:
            def persist_replay_score(self, *args, **kwargs):
                raise RuntimeError("the disk is full")

        with pytest.raises(SweepStoreError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
                worlds=("world-aaa", "world-bbb"),
                database_url=url,
                replay=_RefusingWriter(),
            )

        assert str(refusal.value).startswith(SWEEP_STORE_CODE)
        assert isinstance(refusal.value.__cause__, RuntimeError)

    def test_an_evaluator_that_raises_is_not_reported_as_a_landed_score(self, scores):
        """The one boundary :func:`sweep_candidates` does not own.

        ``evaluator`` is the caller's callable — the replay path, in another
        member — and a fault inside it is that member's error, not this one's.
        So it **propagates untouched**: this module does not catch it, does not
        wrap it in :class:`SweepStoreError` (nothing was stored), and does not
        swallow it into a shorter report.

        What it deliberately does *not* do is leave the caller unable to tell
        what landed.  The rows written before the fault stay — the sweep does
        not roll back a writer it does not own — so the honest reading is
        *these pairs landed, the run did not finish*, and the refusal the
        caller already has (the evaluator's own) is what says so.  A sweep that
        reported here instead would be answering a tournament it did not run.
        """
        url, _ = scores
        (candidate,) = _candidates(1)
        asked: list[str] = []

        def evaluator(candidate, world_id):
            asked.append(world_id)
            if world_id == "world-bbb":
                raise RuntimeError("the replay member fell over")
            return _miss()

        with pytest.raises(RuntimeError, match="fell over"):
            sweep_candidates(
                [candidate],
                evaluator=evaluator,
                beta=0.5,
                worlds=("world-aaa", "world-bbb"),
                database_url=url,
            )

        # Asked in the plan's order and stopped exactly where it fell: the third
        # world was never reached, which is the difference between *the
        # evaluator raised* and *the coverage law was claimed*.
        assert asked == ["world-aaa", "world-bbb"]
        landed = _written(url, candidate.module_id)
        assert [row[2] for row in landed] == ["world-aaa"]


class TestTheHoldIsFeature270s:
    """§C5's first clause meets its middle one, and the sweep does not bend either."""

    def test_a_sweep_under_an_open_hold_is_refused_in_feature_270s_word(self, freeze):
        """The decisive claim: the hold refuses the sweep's writes, and the sweep says so."""
        freeze.ensure_schema()
        hold = freeze.open("cycle-1")

        with pytest.raises(PoolFrozenError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
                worlds=("world-aaa",),
                database_url=freeze.database_url,
            )

        assert hold.iteration_id == "cycle-1"
        assert str(refusal.value).startswith(FREEZE_CODE)
        assert _candidates(1)[0].module_id in str(refusal.value)
        assert "world-aaa" in str(refusal.value)
        # The cause is the *sibling's* wrapper — the replay member's own
        # ``ReplayScoreError``, chained so an operator still reads the
        # database's words — and deliberately not a class of this member: the
        # translation happens at the seam, and what crosses it is the fact.
        assert refusal.value.__cause__ is not None
        assert FREEZE_CODE in str(refusal.value.__cause__)

    def test_the_refusal_is_not_the_sweeps_own_store_class(self, freeze):
        """*The pool is held* is not *the store is broken* — the repairs differ."""
        freeze.ensure_schema()
        freeze.open("cycle-1")

        with pytest.raises(PoolFrozenError) as refusal:
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
                worlds=("world-aaa",),
                database_url=freeze.database_url,
            )

        assert not isinstance(refusal.value, SweepStoreError)
        assert not isinstance(refusal.value, SweepRequestError)
        assert isinstance(refusal.value, DreamingError)

    def test_the_refused_sweep_wrote_nothing_and_holds_nothing(self, freeze):
        """No guard dropped, no second connection, no hold re-taken to slip a row under."""
        freeze.ensure_schema()
        freeze.open("cycle-1")
        before = _written(freeze.database_url)

        with pytest.raises(PoolFrozenError):
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
                worlds=("world-aaa",),
                database_url=freeze.database_url,
            )

        assert _written(freeze.database_url) == before
        assert freeze.open_hold() is not None

    def test_a_sweep_after_the_release_writes_its_evidence(self, freeze):
        """The ordering §C5 asks for, made to run: release, then write."""
        freeze.ensure_schema()
        hold = freeze.open("cycle-1")
        with pytest.raises(PoolFrozenError):
            sweep_candidates(
                _candidates(1),
                evaluator=lambda candidate, world_id: _miss(),
                beta=0.5,
                worlds=("world-aaa",),
                database_url=freeze.database_url,
            )
        freeze.release(hold)

        report = sweep_candidates(
            _candidates(1),
            evaluator=lambda candidate, world_id: _miss(-1.5),
            beta=0.5,
            worlds=("world-aaa",),
            database_url=freeze.database_url,
        )

        assert len(report) == 1
        assert freeze.open_hold() is None


class TestTheSurfaceAndTheRestraint:
    """The module's public names, and what it deliberately is not."""

    def test_the_module_is_reachable_from_the_member(self):
        """The feature's surface is the member's, as the ladder's other rungs are."""
        import dreaming

        for name in (
            "SWEEP_CODE",
            "SWEEP_STORE_CODE",
            "SweepPair",
            "SweepReport",
            "SweepRequestError",
            "SweepStoreError",
            "plan_sweep",
            "sweep_candidates",
        ):
            assert name in dreaming.__all__, name
            assert hasattr(dreaming, name), name

    def test_the_module_is_stdlib_only_and_imports_no_member(self):
        """The factory's scan imports this package, so the module must be import-cheap."""
        import sys

        import dreaming.sweep as module

        source = Path(module.__file__).read_text()
        for forbidden in (
            "import numpy",
            "import scipy",
            "import pandas",
            "from replay",
            "import replay",
            "from policy_runtime",
        ):
            assert forbidden not in source, forbidden
        # ``from app.module_loader import create_app`` inside the replay
        # resolver is the one deferred import, and it is the *app namespace*
        # it reaches — never a member's own import name.  At module level the
        # app namespace is not imported at all.
        top_level = [
            node
            for node in ast.parse(source).body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        for node in top_level:
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
            assert all(name.split(".")[0] != "app" for name in names), ast.unparse(node)
        assert sys.modules["dreaming.sweep"] is module

    def test_the_module_creates_no_table_of_its_own(self):
        """The member's one table is ``pool_freeze``; the sweep adds none.

        ``replay_score`` is feature 255's and ``0109``'s, written through that
        member's writer and never created here; a sweep that ran ``CREATE
        TABLE`` would be a second claimant to a schema it does not own.
        """
        import dreaming.sweep as module

        source = Path(module.__file__).read_text()
        assert "CREATE TABLE" not in source
        assert "CREATE TRIGGER" not in source
        assert "INSERT INTO" not in source

    def test_the_member_still_registers_exactly_one_component(self):
        """The sweep is free functions beside the store, not a second component."""
        import dreaming

        assert dreaming.COMPONENT_NAME == "dreaming"
        assert dreaming.__all__.count("build_cycle_freeze") == 1

    def test_every_refusal_is_the_members_own_base(self):
        """A caller that wants every failure of this member's path catches one class."""
        assert issubclass(SweepRequestError, DreamingError)
        assert issubclass(SweepStoreError, DreamingError)

    def test_the_two_codes_are_distinct_and_name_their_halves(self):
        """The ask and the store are greppable apart, as the cap's and the split's are."""
        assert SWEEP_CODE != SWEEP_STORE_CODE
        assert SWEEP_CODE.startswith("sweep_")
        assert SWEEP_STORE_CODE.startswith("sweep_")
        assert FREEZE_CODE not in (SWEEP_CODE, SWEEP_STORE_CODE)

    def test_a_world_the_split_refuses_stays_the_splits_class_at_the_splits_seam(self):
        """The translation is one way: the split's own callers still read its word."""
        split = split_pool(tuple(f"world-{index:03d}" for index in range(20)))

        with pytest.raises(DreamingError) as refusal:
            split.is_holdout("world-not-in-the-pool")

        assert not isinstance(refusal.value, SweepRequestError)

    def test_the_pair_and_the_report_are_values_that_do_not_move(self):
        """A plan a caller holds is not a handle the sweep can move under it."""
        pair = SweepPair(module_id="cand-1", code_hash="a" * 64, world_id="w-a")
        assert pair == SweepPair(
            module_id="cand-1", code_hash="a" * 64, world_id="w-a"
        )
        assert pair != SweepPair(
            module_id="cand-1", code_hash="a" * 64, world_id="w-b"
        )
        assert isinstance(hash(pair), int)
        assert pair.row() == {
            "policy_version": "cand-1",
            "code_hash": "a" * 64,
            "world_id": "w-a",
            "is_holdout": False,
            "revision_index": None,
        }
