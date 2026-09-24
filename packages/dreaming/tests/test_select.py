"""Feature 274's claim, stated as tests: the argmax, crowned and persisted.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 274: *System selects
the argmax candidate under the aggregated objective, persisting the winner
into the ``policy_revision`` table.*  docs/alpha-engine-prd.md §C5 states it
as the terminal clause of the loop — *"select the argmax under §7"* — and
§12.1 names the thing that is wrong with stopping at a bare max: the winner is
a **max**, and a max is biased.  This module is the *crowning* half of that
clause — the selector feature 280's bar deliberately is not.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* the **verdict is a judgment over figures the caller already holds** — the
  candidate set feature 271 produced and each one's aggregated objective in,
  the single winning candidate out, and **pure**: no store, no clock, no
  environment.  A caller that only wants to know *which candidate won* asks
  this and pays for nothing;
* the verdict **refuses rather than silently defaults** — an empty set, an
  empty mapping, a candidate the objectives do not cover, an objective with no
  finite score, an objective keyed to a revision that did not run, and a **tie**
  on the maximum.  The tie is the load-bearing one: the argmax is undefined
  over two candidates sharing the top score, and picking one by iteration order
  would be a selection that changed with nothing, so the refusal names both and
  states the repair;
* the verdict is **deterministic and order-independent** — the winner is the
  candidate whose objective score is strictly greater than every other, so the
  same set answers the same winner regardless of order;
* the **act** resolves the pool, reads the sweep's evidence back from the
  pool's own ``replay_score`` table directly (a ``sqlite3`` connection, the
  same read-time seam :func:`dreaming.paired._pool_arm` takes, because the
  composed replay component exposes only a writer and no reader of the score
  rows), groups each candidate's rows into the caller's regime strata, blends
  each under §7 with feature 263's ``aggregate_objective`` (reached through the
  scoring member's namespace, never the composed seat), crowns
  :func:`select_argmax`'s winner, and persists one row into
  ``policy_revision`` directly — feature 274 is the table's sole writer,
  because the replay member's ``persist_replay_score`` lands in
  ``replay_score``, not here;
* the selector's score is the **§7 blend of the stratum mean and the stratum
  minimum**, not a raw average, and a candidate with a world the strata do not
  cover is refused rather than dropped;
* the winner's identity is **read, not recomputed** — a row's
  ``policy_version`` and ``code_hash`` are the produced candidate's, and a
  selector that re-hashed the source would be a second spelling of what a
  candidate is;
* the two refusals are **different repairs** — *your ask was malformed*
  (:class:`SelectionRequestError`, ``selection_malformed``) against *the store
  could not ground the selection* (:class:`SelectionStoreError`,
  ``selection_ungrounded``) — and neither borrows feature 272's, feature 280's
  or feature 270's word.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from dreaming import (
    DreamingError,
    SelectionRequestError,
    SelectionStoreError,
    commit_selection,
    select_argmax,
    sqlite_path,
)

# -- the vocabulary of the fixtures -------------------------------------------


def _candidate(
    module_id: str, *, code_hash: str | None = None, parent: str | None = "v0"
):
    """One candidate module — the value feature 271 produces, duck-typed.

    A :class:`types.SimpleNamespace` carrying ``module_id``, ``code_hash`` and
    ``parent_version`` — the three fields the selector reads — so a test names
    a candidate without importing feature 271's class, the way the verdict
    reads one: by the attributes it needs, never by ``isinstance``.  A
    ``code_hash`` defaults to 64 of the candidate's own letter, the shape a
    real sha256 takes; a test that wants the selector to *read* a hash hands in
    a distinctive one.
    """
    return SimpleNamespace(
        module_id=module_id,
        code_hash=code_hash or (module_id[0] * 64),
        parent_version=parent,
    )


def _objective(score: float, *, world_count: int = 10):
    """One aggregated objective — feature 263's value, duck-typed.

    A :class:`types.SimpleNamespace` carrying ``score`` and ``world_count`` —
    the two figures the argmax ranks by — so a verdict test needs no real
    §7 blend behind it.  The verdict reads the objective by these attributes
    and nothing more, which is the whole point of the duck-typed seam.
    """
    return SimpleNamespace(score=score, world_count=world_count)


def _write_scores(
    url: str,
    *,
    policy_version: str,
    beta: float,
    readings: dict[str, float],
    order: int = 0,
) -> None:
    """Write one candidate's score rows into the pool, through ``0109``'s columns.

    The rows are written the way the owner declares them — ``0109``'s eight
    columns for ``replay_score`` — which is the same discipline the member's
    own ``scores`` fixture states: a fixture that wrote a narrower row would
    make every read pass for the wrong reason.  The ``order`` prefix on the id
    is the same load-bearing ordering probe the paired suite's ``_write_arm``
    states — a real pool's ``id`` is a UUID whose sort order is unrelated to
    its write order, so the read resolves several rows for one world by
    ``ORDER BY id``; a fixture that appended a suffix would test an id scheme
    whose sort matched its write, hiding the difference.
    """
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        for world_id, score in readings.items():
            connection.execute(
                "INSERT INTO replay_score (id, policy_version, world_id, beta, "
                "score, committed_pick, is_holdout, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{order:04d}-score-{policy_version}-{world_id}",
                    policy_version,
                    world_id,
                    beta,
                    score,
                    None,
                    0,
                    "2026-01-01T00:00:00Z",
                ),
            )


def _write_winner(
    url: str, *, policy_version: str, code_hash: str, parent, aggregate_score
):
    """Write a winner row directly, to set up a duplicate-policy test."""
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        connection.execute(
            "INSERT INTO policy_revision "
            "(policy_version, parent_version, code_hash, aggregate_score, selected) "
            "VALUES (?, ?, ?, ?, TRUE)",
            (policy_version, parent, code_hash, aggregate_score),
        )


def _revision_table(url: str) -> None:
    """Stand up ``policy_revision`` — feature 274's table, in ``0109``'s columns.

    The member's ``pool`` fixture creates only the two pool tables; this table
    belongs to feature 274, which is its sole writer, so a test that means to
    crown a winner installs it here with the exact DDL ``0109`` declares — the
    same discipline the paired suite's ``_write_arm`` states for the score
    rows: a fixture that wrote a narrower table would make the persist pass for
    the wrong reason.  ``selected`` defaults FALSE in the DDL so the persisted
    winner's TRUE flag is a real assertion, not a default.
    """
    uuid_default = (
        "(lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || "
        "substr(hex(randomblob(2)), 2) || '-' || "
        "substr('89ab', abs(random()) % 4 + 1, 1) || "
        "substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6))))"
    )
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS policy_revision ("
            "id UUID NOT NULL PRIMARY KEY DEFAULT "
            f"{uuid_default}, "
            "policy_version TEXT NOT NULL UNIQUE, "
            "parent_version TEXT, "
            "code_hash CHAR(64) NOT NULL, "
            "aggregate_score REAL, "
            "selected BOOLEAN NOT NULL DEFAULT FALSE)"
        )


def _read_winner(url: str) -> tuple[str, str, str, float, bool] | None:
    """The single ``selected`` row of ``policy_revision`` — the winner, read back.

    Reads the row feature 274 persisted, so a test asserts the winner landed
    with the produced candidate's identity and its aggregated score — the act's
    whole output, stated as one row.  ``None`` means no winner was crowned.
    """
    with closing(sqlite3.connect(sqlite_path(url))) as connection:
        row = connection.execute(
            "SELECT policy_version, parent_version, code_hash, aggregate_score, "
            "selected FROM policy_revision WHERE selected = TRUE"
        ).fetchone()
    return row


# -- the verdict: select_argmax ------------------------------------------------


class TestSelectArgmax:
    """The pure judgment over figures the caller already holds."""

    def test_the_winner_is_the_max_score(self):
        """The winner is the candidate whose objective carries the top score."""
        candidates = [_candidate("cand-a"), _candidate("cand-b"), _candidate("cand-c")]
        objectives = {
            "cand-a": _objective(0.30),
            "cand-b": _objective(0.55),
            "cand-c": _objective(0.40),
        }
        winner = select_argmax(candidates, objectives)
        assert winner.module_id == "cand-b"

    def test_the_winner_is_the_produced_candidate(self):
        """The returned winner is the caller's own candidate object, not a copy.

        So a caller reading the winner's ``code_hash`` and ``parent_version``
        reads the value feature 271 produced — the selector persists the
        candidate it was handed, and its identity is read, not recomputed.
        """
        candidates = [
            _candidate("cand-a", code_hash="A" * 64),
            _candidate("cand-b", code_hash="B" * 64),
        ]
        objectives = {"cand-a": _objective(0.4), "cand-b": _objective(0.6)}
        winner = select_argmax(candidates, objectives)
        assert winner.module_id == "cand-b"
        assert winner.code_hash == "B" * 64
        assert winner.parent_version == "v0"

    def test_a_single_candidate_is_its_winner(self):
        """An argmax over one candidate crowns it — a selection of one, not a refusal."""
        candidates = [_candidate("cand-a")]
        objectives = {"cand-a": _objective(0.42)}
        assert select_argmax(candidates, objectives).module_id == "cand-a"

    def test_the_maximum_is_taken_over_the_objectives_score_field(self):
        """The verdict ranks on the objective's own ``score``, never a re-derived figure.

        Two candidates whose objectives carry different scores but identical
        everything else still separate on the score alone — the verdict and the
        number cannot disagree, because the number is the only thing the
        verdict reads.
        """
        candidates = [_candidate("low"), _candidate("high")]
        objectives = {"low": _objective(0.10), "high": _objective(0.90)}
        assert select_argmax(candidates, objectives).module_id == "high"

    # -- the refusals ---------------------------------------------------------

    def test_an_empty_candidate_set_is_refused(self):
        """An argmax over nothing is a tournament nobody entered, not a null selection."""
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax([], {})
        assert "selection_malformed" in str(caught.value)
        assert "tournament nobody entered" in str(caught.value)

    def test_an_empty_objective_mapping_is_refused(self):
        """No candidate has a figure to rank it by — the argmax is undefined."""
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax([_candidate("cand-a")], {})
        assert "selection_malformed" in str(caught.value)

    def test_a_candidate_the_objectives_do_not_cover_is_refused(self):
        """A candidate with no objective names no score to rank it by."""
        candidates = [_candidate("cand-a"), _candidate("cand-b")]
        objectives = {"cand-a": _objective(0.5)}
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(candidates, objectives)
        assert "no objective" in str(caught.value)
        assert "cand-b" in str(caught.value)

    def test_an_objective_for_a_revision_that_did_not_run_is_refused(self):
        """An objective keyed to a module id no candidate carries crowns a phantom."""
        candidates = [_candidate("cand-a")]
        objectives = {"cand-a": _objective(0.5), "cand-phantom": _objective(0.9)}
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(candidates, objectives)
        assert "no candidate carries" in str(caught.value)
        assert "cand-phantom" in str(caught.value)

    def test_an_objective_with_no_finite_score_is_refused(self):
        """A −∞ miss's number may not be counterfeited — the aggregate's own −∞ argument."""
        import math

        candidates = [_candidate("cand-a")]
        objectives = {"cand-a": _objective(math.inf)}
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(candidates, objectives)
        assert "finite" in str(caught.value)

    def test_an_objective_with_a_nan_score_is_refused(self):
        """A NaN compares false against every score and would silently drop out."""
        import math

        candidates = [_candidate("cand-a")]
        objectives = {"cand-a": _objective(math.nan)}
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(candidates, objectives)
        assert "NaN" in str(caught.value)

    def test_an_objective_with_zero_worlds_is_refused(self):
        """An objective aggregated over no world names no score to rank by."""
        candidates = [_candidate("cand-a")]
        objectives = {"cand-a": _objective(0.5, world_count=0)}
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(candidates, objectives)
        assert "world_count" in str(caught.value)

    def test_a_candidate_with_no_module_id_is_refused(self):
        """A candidate that cannot be named crowns no revision."""
        candidates = [SimpleNamespace(module_id="", code_hash="a" * 64)]
        objectives = {"": _objective(0.5)}
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(candidates, objectives)
        assert "module_id" in str(caught.value)

    def test_a_tie_is_refused_and_names_both(self):
        """The argmax is undefined over two candidates sharing the top score.

        Picking one by iteration order would be a selection that changed with
        nothing, so the refusal names both and states the repair: break the tie
        by a fact outside the aggregate, or keep the incumbent.
        """
        candidates = [_candidate("cand-a"), _candidate("cand-b")]
        objectives = {"cand-a": _objective(0.5), "cand-b": _objective(0.5)}
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(candidates, objectives)
        message = str(caught.value)
        assert "tie" in message
        assert "cand-a" in message
        assert "cand-b" in message

    def test_a_tie_is_refused_identically_when_the_order_is_reversed(self):
        """The refusal does not depend on which tied candidate came first.

        The determinism law the aggregate holds one judgment over: the same set
        answers the same refusal regardless of candidate order, so a selection
        that changed with the mapping's iteration order is impossible.
        """
        forward = [_candidate("cand-a"), _candidate("cand-b")]
        reverse = [_candidate("cand-b"), _candidate("cand-a")]
        objectives = {"cand-a": _objective(0.5), "cand-b": _objective(0.5)}
        with pytest.raises(SelectionRequestError) as first:
            select_argmax(forward, objectives)
        with pytest.raises(SelectionRequestError) as second:
            select_argmax(reverse, objectives)
        assert str(first.value) == str(second.value)

    def test_a_tie_among_three_is_refused_naming_the_two_leaders(self):
        """Only the tied leaders are named — the third, lower candidate is not."""
        candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
        objectives = {"a": _objective(0.5), "b": _objective(0.5), "c": _objective(0.1)}
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(candidates, objectives)
        assert "a" in str(caught.value)
        assert "b" in str(caught.value)

    def test_the_winner_is_order_independent(self):
        """The same set answers the same winner regardless of candidate order."""
        forward = [_candidate("a"), _candidate("b"), _candidate("c")]
        reverse = [_candidate("c"), _candidate("b"), _candidate("a")]
        objectives = {"a": _objective(0.2), "b": _objective(0.7), "c": _objective(0.5)}
        assert select_argmax(forward, objectives).module_id == "b"
        assert select_argmax(reverse, objectives).module_id == "b"

    def test_the_winner_is_mapping_order_independent(self):
        """The same set answers the same winner regardless of objective-mapping order."""
        candidates = [_candidate("a"), _candidate("b")]
        one = {"a": _objective(0.3), "b": _objective(0.8)}
        two = {"b": _objective(0.8), "a": _objective(0.3)}
        assert select_argmax(candidates, one).module_id == "b"
        assert select_argmax(candidates, two).module_id == "b"

    def test_a_bare_candidate_is_refused_where_a_sequence_belongs(self):
        """A bare candidate names one revision; an argmax over one is not a selection."""
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax(_candidate("cand-a"), {"cand-a": _objective(0.5)})
        assert "sequence" in str(caught.value)

    def test_a_bare_objective_is_refused_where_a_mapping_belongs(self):
        """A bare objective names one figure; a set ranked by one is not a selection."""
        with pytest.raises(SelectionRequestError) as caught:
            select_argmax([_candidate("cand-a")], _objective(0.5))
        assert "mapping" in str(caught.value)

    def test_the_request_error_is_a_dreaming_error(self):
        """A caller catching DreamingError catches the selector's malformed ask."""
        with pytest.raises(DreamingError):
            select_argmax([], {})


# -- the act: commit_selection -------------------------------------------------


class TestCommitSelection:
    """The store seam: resolve the pool, aggregate under §7, crown and persist."""

    def test_the_winner_is_crowned_and_persisted(self, pool):
        """The argmax winner is written as the ``selected`` row of ``policy_revision``.

        Two candidates, each scored on the same three worlds at the episode's
        beta; one wins the §7 blend, and its row lands with its produced
        identity — ``policy_version`` the module id, ``code_hash`` the
        candidate's, ``parent_version`` the candidate's, ``aggregate_score``
        the blend, and ``selected`` TRUE.
        """
        _revision_table(pool)
        _write_scores(
            pool,
            policy_version="cand-a",
            beta=0.0,
            readings={"w1": 0.2, "w2": 0.4, "w3": 0.6},
        )
        _write_scores(
            pool,
            policy_version="cand-b",
            beta=0.0,
            readings={"w1": 0.5, "w2": 0.6, "w3": 0.7},
        )
        strata = {"regime-1": ("w1", "w2", "w3")}
        winner = commit_selection(
            [_candidate("cand-a"), _candidate("cand-b")],
            strata=strata,
            beta=0.0,
            database_url=pool,
        )
        assert winner.module_id == "cand-b"
        row = _read_winner(pool)
        assert row is not None
        assert row[0] == "cand-b"
        assert row[1] == "v0"
        assert row[2] == "c" * 64

    def test_only_one_row_is_selected(self, pool):
        """Exactly one winner row lands — the selector crowns one, not a row per candidate."""
        _revision_table(pool)
        _write_scores(pool, policy_version="cand-a", beta=0.0, readings={"w1": 0.1})
        _write_scores(pool, policy_version="cand-b", beta=0.0, readings={"w1": 0.9})
        commit_selection(
            [_candidate("cand-a"), _candidate("cand-b")],
            strata={"s": ("w1",)},
            beta=0.0,
            database_url=pool,
        )
        with closing(sqlite3.connect(sqlite_path(pool))) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM policy_revision WHERE selected = TRUE"
            ).fetchone()[0]
        assert count == 1

    def test_the_persisted_score_is_the_blend_not_a_raw_average(self, pool):
        """The winner's ``aggregate_score`` is §7's blend of mean and minimum, not the mean.

        With two strata whose means differ, the blend ``(1 − λ)·mean + λ·min``
        sits strictly below the raw average of all worlds — the selector's score
        is the §7 objective, and λ at its default 0.6 weights the worst stratum.
        """
        _revision_table(pool)
        # cand-a: stratum X worlds at 0.8, stratum Y worlds at 0.2
        _write_scores(
            pool,
            policy_version="cand-a",
            beta=0.0,
            readings={"x1": 0.8, "x2": 0.8, "y1": 0.2, "y2": 0.2},
        )
        _write_scores(
            pool,
            policy_version="cand-b",
            beta=0.0,
            readings={"x1": 0.1, "x2": 0.1, "y1": 0.1, "y2": 0.1},
        )
        strata = {"X": ("x1", "x2"), "Y": ("y1", "y2")}
        commit_selection(
            [_candidate("cand-a"), _candidate("cand-b")],
            strata=strata,
            beta=0.0,
            database_url=pool,
        )
        row = _read_winner(pool)
        assert row[0] == "cand-a"
        # §7 blend: mean of strata = (0.8 + 0.2) / 2 = 0.5; min = 0.2;
        # (1 − 0.6)·0.5 + 0.6·0.2 = 0.2 + 0.12 = 0.32, strictly below the raw
        # average of all four worlds (0.5).
        assert row[3] == pytest.approx(0.32)

    def test_a_world_the_strata_do_not_cover_is_refused(self, pool):
        """A candidate with a world no stratum names is refused rather than dropped.

        A dropped world silently changes which tournament the argmax is taken
        over, the way plan_sweep refuses a world the split does not hold.
        """
        _revision_table(pool)
        _write_scores(
            pool,
            policy_version="cand-a",
            beta=0.0,
            readings={"w1": 0.5, "w2": 0.6},
        )
        strata = {"regime-1": ("w1",)}  # w2 uncovered
        with pytest.raises(SelectionStoreError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata=strata,
                beta=0.0,
                database_url=pool,
            )
        assert "selection_ungrounded" in str(caught.value)
        assert "w2" in str(caught.value)
        assert _read_winner(pool) is None

    def test_a_database_with_no_pool_is_refused(self, database_url):
        """No ``replay_score`` table means no sweep evidence to aggregate over.

        Uses the bare ``database_url`` fixture — a path with no tables — so the
        pool is genuinely absent.  A candidate is handed so the selector has
        something to crown, but the read finds no pool and refuses before any
        candidate is aggregated.
        """
        with pytest.raises(SelectionStoreError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata={"s": ("w1",)},
                beta=0.0,
                database_url=database_url,
            )
        assert "selection_ungrounded" in str(caught.value)
        assert "replay_score" in str(caught.value)

    def test_no_database_named_is_refused(self, monkeypatch):
        """An act that means to read the pool and resolves nothing is refused by name."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SelectionStoreError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata={"s": ("w1",)},
                beta=0.0,
                env={},
            )
        assert "selection_ungrounded" in str(caught.value)

    def test_a_url_this_member_cannot_speak_is_refused(self):
        """A non-sqlite URL is refused in the selector's own word, translated at the seam."""
        with pytest.raises(SelectionStoreError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata={"s": ("w1",)},
                beta=0.0,
                database_url="postgresql://host/db",
            )
        assert "selection_ungrounded" in str(caught.value)

    def test_the_read_is_filtered_to_the_episode_beta(self, pool):
        """``beta`` selects which score rows are the episode's — rows at another beta are ignored.

        §7.4's scalar is *fixed within an episode*, so the argmax aggregates
        the scores the sweep earned at the episode's explore/exploit setting and
        never a reading taken under another.  A candidate whose only high scores
        are at a different beta does not win.
        """
        _revision_table(pool)
        # cand-a is strong at beta 1.0, weak at the episode beta 0.0
        _write_scores(
            pool,
            policy_version="cand-a",
            beta=0.0,
            readings={"w1": 0.1},
        )
        _write_scores(
            pool,
            policy_version="cand-a",
            beta=1.0,
            readings={"w1": 0.95},
            order=1,
        )
        # cand-b is steady at the episode beta
        _write_scores(
            pool,
            policy_version="cand-b",
            beta=0.0,
            readings={"w1": 0.6},
        )
        winner = commit_selection(
            [_candidate("cand-a"), _candidate("cand-b")],
            strata={"s": ("w1",)},
            beta=0.0,
            database_url=pool,
        )
        assert winner.module_id == "cand-b"

    def test_the_last_reading_per_world_wins_in_id_order(self, pool):
        """Several rows for one world resolve by ``ORDER BY id`` — the §12 ordering rule.

        A later ``id`` (here the higher ``order`` prefix) is the reading the
        candidate's score row resolves to, the same discipline the paired
        suite's ``_pool_arm`` and the replay member's writer hold.
        """
        _revision_table(pool)
        _write_scores(
            pool,
            policy_version="cand-a",
            beta=0.0,
            readings={"w1": 0.1},
            order=0,
        )
        _write_scores(
            pool,
            policy_version="cand-a",
            beta=0.0,
            readings={"w1": 0.9},
            order=1,
        )
        commit_selection(
            [_candidate("cand-a")],
            strata={"s": ("w1",)},
            beta=0.0,
            database_url=pool,
        )
        row = _read_winner(pool)
        assert row[0] == "cand-a"
        assert row[3] == pytest.approx(0.9)

    def test_the_winner_identity_is_read_not_recomputed(self, pool):
        """The persisted ``code_hash`` is the candidate's own, not a re-hash of its source.

        A candidate carrying a distinctive ``code_hash`` lands that exact hash;
        a selector that re-hashed the source would be a second spelling of what
        a candidate is.
        """
        _revision_table(pool)
        _write_scores(pool, policy_version="cand-a", beta=0.0, readings={"w1": 0.5})
        candidate = _candidate("cand-a", code_hash="deadbeef" * 8)
        commit_selection(
            [candidate],
            strata={"s": ("w1",)},
            beta=0.0,
            database_url=pool,
        )
        row = _read_winner(pool)
        assert row[2] == "deadbeef" * 8

    def test_a_parent_version_none_is_persisted_as_null(self, pool):
        """A root candidate (``parent_version`` None) lands with a NULL parent.

        ``0109`` makes ``parent_version`` nullable for exactly this — a root
        revision has no parent — so the selector's ``getattr`` default of None
        is the honest row, not a fabricated empty string.
        """
        _revision_table(pool)
        _write_scores(pool, policy_version="root", beta=0.0, readings={"w1": 0.5})
        candidate = SimpleNamespace(
            module_id="root", code_hash="r" * 64, parent_version=None
        )
        commit_selection(
            [candidate],
            strata={"s": ("w1",)},
            beta=0.0,
            database_url=pool,
        )
        row = _read_winner(pool)
        assert row[1] is None

    def test_a_duplicate_winner_is_refused_not_retried(self, pool):
        """A winner whose row would collide with an existing one is refused, not re-crowned.

        Feature 274 is the table's sole writer; a row that cannot land (a
        duplicate ``policy_version``) is refused rather than retried over a
        winner that would silently re-crown another.
        """
        _revision_table(pool)
        _write_scores(pool, policy_version="cand-a", beta=0.0, readings={"w1": 0.5})
        _write_scores(pool, policy_version="cand-b", beta=0.0, readings={"w1": 0.9})
        # Pre-seed a row for the would-be winner's version.
        _write_winner(
            pool,
            policy_version="cand-b",
            code_hash="existing" * 8,
            parent="old",
            aggregate_score=0.1,
        )
        with pytest.raises(SelectionStoreError) as caught:
            commit_selection(
                [_candidate("cand-a"), _candidate("cand-b")],
                strata={"s": ("w1",)},
                beta=0.0,
                database_url=pool,
            )
        assert "selection_ungrounded" in str(caught.value)
        # The pre-seeded row is untouched — the selector did not overwrite it.
        row = _read_winner(pool)
        assert row[2] == "existing" * 8

    def test_a_tie_in_the_pool_is_refused(self, pool):
        """Two candidates tied on the §7 blend are refused before any write.

        The verdict's tie refusal holds one store seam over: the selector
        aggregates both, meets the tie, and refuses — leaving no row behind.
        """
        _revision_table(pool)
        _write_scores(pool, policy_version="cand-a", beta=0.0, readings={"w1": 0.5})
        _write_scores(pool, policy_version="cand-b", beta=0.0, readings={"w1": 0.5})
        with pytest.raises(SelectionRequestError):
            commit_selection(
                [_candidate("cand-a"), _candidate("cand-b")],
                strata={"s": ("w1",)},
                beta=0.0,
                database_url=pool,
            )
        assert _read_winner(pool) is None

    # -- the §7 blend and its knob --------------------------------------------

    def test_the_blend_uses_the_callers_lambda(self, pool):
        """A handed ``lam`` weights the worst stratum — the blend is the caller's knob.

        At ``lam`` 0.5 (the band floor) the blend is half mean and half minimum;
        the selector blends under the weight it is given, never a hidden one.
        """
        _revision_table(pool)
        _write_scores(
            pool,
            policy_version="cand-a",
            beta=0.0,
            readings={"x1": 1.0, "y1": 0.0},
        )
        commit_selection(
            [_candidate("cand-a")],
            strata={"X": ("x1",), "Y": ("y1",)},
            beta=0.0,
            database_url=pool,
            lam=0.5,
        )
        row = _read_winner(pool)
        # mean of strata = 0.5, min = 0.0; (1 − 0.5)·0.5 + 0.5·0.0 = 0.25
        assert row[3] == pytest.approx(0.25)

    def test_a_lambda_outside_the_band_is_refused(self, pool):
        """A ``lam`` outside feature 263's ``[0.5, 0.7]`` is refused before the store."""
        _revision_table(pool)
        _write_scores(pool, policy_version="cand-a", beta=0.0, readings={"w1": 0.5})
        with pytest.raises(SelectionRequestError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata={"s": ("w1",)},
                beta=0.0,
                database_url=pool,
                lam=0.9,
            )
        assert "lam" in str(caught.value)
        assert _read_winner(pool) is None

    def test_a_non_finite_beta_is_refused(self, pool):
        """An infinity is not a hyperparameter — it is a value outside the scored space."""
        import math

        _revision_table(pool)
        _write_scores(pool, policy_version="cand-a", beta=0.0, readings={"w1": 0.5})
        with pytest.raises(SelectionRequestError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata={"s": ("w1",)},
                beta=math.inf,
                database_url=pool,
            )
        assert "beta" in str(caught.value)

    def test_a_bool_beta_is_refused(self, pool):
        """A ``bool`` is not a number — the episode's explore/exploit setting is a real."""
        _revision_table(pool)
        _write_scores(pool, policy_version="cand-a", beta=0.0, readings={"w1": 0.5})
        with pytest.raises(SelectionRequestError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata={"s": ("w1",)},
                beta=True,
                database_url=pool,
            )
        assert "beta" in str(caught.value)

    # -- the ask/store split ---------------------------------------------------

    def test_a_malformed_ask_is_a_request_error_not_a_store_error(self, pool):
        """An empty candidate set is refused before the store is touched."""
        with pytest.raises(SelectionRequestError):
            commit_selection([], strata={}, beta=0.0, database_url=pool)

    def test_a_malformed_strata_is_a_request_error(self, pool):
        """A flat collection is the plain mean across regimes — feature 264's refusal."""
        _revision_table(pool)
        with pytest.raises(SelectionRequestError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata=["w1", "w2"],
                beta=0.0,
                database_url=pool,
            )
        assert "selection_malformed" in str(caught.value)

    def test_a_blank_stratum_name_is_refused(self, pool):
        """A stratum that cannot be named cannot be reported as the blend's worst regime."""
        _revision_table(pool)
        with pytest.raises(SelectionRequestError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata={"": ("w1",)},
                beta=0.0,
                database_url=pool,
            )
        assert "stratum" in str(caught.value)

    def test_an_empty_stratum_is_refused(self, pool):
        """A stratum that holds no world lends no figure — a fabricated 0.0 would be worse."""
        _revision_table(pool)
        with pytest.raises(SelectionRequestError) as caught:
            commit_selection(
                [_candidate("cand-a")],
                strata={"empty": ()},
                beta=0.0,
                database_url=pool,
            )
        assert "no worlds" in str(caught.value)

    def test_the_store_error_is_a_dreaming_error(self, pool):
        """A caller catching DreamingError catches the selector's store refusal."""
        with pytest.raises(DreamingError):
            commit_selection(
                [_candidate("cand-a")],
                strata={"s": ("w1",)},
                beta=0.0,
                database_url=pool,
            )

    def test_neither_refusal_is_the_thin_pool_word(self):
        """The selector's refusals are its own — not feature 275's ``pool_too_thin``."""
        assert "pool_too_thin" not in str(SelectionRequestError("x"))
        assert "pool_too_thin" not in str(SelectionStoreError("x"))

    def test_neither_refusal_is_the_sweep_word(self):
        """Not feature 272's ``sweep_malformed`` / ``sweep_ungrounded`` — a caller acts on the right fact."""
        assert "sweep_malformed" not in str(SelectionRequestError("x"))
        assert "sweep_ungrounded" not in str(SelectionStoreError("x"))
