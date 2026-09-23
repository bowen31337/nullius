"""Feature 255 in the assembled system — the persistence write over the real
duck-typed seam.

app_spec.xml, "Replay Engine", feature 255: *System persists one replay_score
row per run carrying policy version, world id, beta, score and committed
pick.*  The member's own suite (``packages/replay/tests/test_score.py``) pins
the writer and its refusals over hand-rolled doubles; this suite pins the
**duck-typed seam** against the two objects the composed system actually
produces — the composed component's ``persist_replay_score`` verb and the
:class:`~replay.TerminalPick` the composed ``pick`` verb answers — which is
what a member's suite structurally cannot do:

* **the write runs over the composed value** — the ``TerminalPick`` the
  composed ``pick`` verb answers is a *second* class object (the loader
  re-executes the member under a synthetic name), and the persistence write
  reads it duck-typed, never ``isinstance``-ing it; this is the only place the
  two halves of one terminal moment — the requirement's answer and the
  persistence's row — are checked against each other;
* **the miss persists as the floor** — a policy that emitted no pick writes a
  row whose score is ``-inf`` and whose ``committed_pick`` is NULL, over the
  real composed miss path;
* **the five values land in a real sqlite store** — one row per run, carrying
  policy_version, world_id, beta, score and committed_pick, into a store the
  composed verb is handed by URL.

**Nothing here asserts ``isinstance`` or ``pytest.raises(<canonical class>)``
across the composition seam.**  The module loader imports each workspace
member under a synthetic name (``_nullius_scanned_<name>``), so the
``ReplayScoreError`` the composed path raises and the ``TerminalPick`` the
wiring builds are *second* class objects with the same names — an
``isinstance`` across that seam is False even though nothing is wrong.  The
checks below name the behaviour and compare ``type(exc).__name__``, the same
answer ``tests/replay/test_pick_wiring.py`` gives for the same wrinkle.
"""

from __future__ import annotations

import sqlite3

import pytest

policy_runtime = pytest.importorskip("policy_runtime")
CampaignTree = policy_runtime.CampaignTree
PolicyQuestion = policy_runtime.PolicyQuestion
episode_commit = policy_runtime.episode_commit

POLICY = "policy-v0007"
WORLD = "world-financial-0042"
BETA = 0.02


def create_app():
    from app.module_loader import create_app

    return create_app()


@pytest.fixture(scope="module")
def campaign_tree() -> CampaignTree:
    """The real campaign tree a deployment would hold — two themes, one branch."""
    return CampaignTree.freeze(
        {
            "r-mom": (None, 0, {"depth": 0, "r2_insample": None}),
            "m1": ("r-mom", 1, {"parent_id": "r-mom", "depth": 1, "r2_insample": 0.20}),
            "m1x": ("m1", 2, {"parent_id": "m1", "depth": 2, "r2_insample": 0.51}),
            "r-event": (None, 0, {"depth": 0, "r2_insample": None}),
        }
    )


@pytest.fixture
def component():
    """The composed replay component, reached the way a runtime reaches it."""
    return create_app().get("replay")


def _row(url: str, table: str) -> tuple:
    """Read the one persisted replay_score row back off the raw table.

    Positional, matching the store conventions of this workspace (the
    connections set no row factory): the SELECT's order is the contract.
    """
    with sqlite3.connect(_path_of(url)) as connection:
        return connection.execute(
            f"SELECT policy_version, world_id, beta, score, committed_pick "
            f"FROM {table}"
        ).fetchone()


def _path_of(url: str) -> str:
    """The sqlite URL's file path — the ``sqlite:///`` prefix stripped."""
    return url.removeprefix("sqlite:///")


# ---------------------------------------------------------------------------
# The write runs over the composed value, into a real store
# ---------------------------------------------------------------------------


def test_the_composed_verb_persists_one_row_carrying_the_five_values(
    campaign_tree, component, tmp_path
) -> None:
    # The whole seam end to end: the composed ``pick`` verb answers a real
    # CommittedPick beside the score, and the composed ``persist_replay_score``
    # verb writes that TerminalPick — read duck-typed, never isinstance-ed —
    # as one row carrying the five named columns.
    record = episode_commit(PolicyQuestion(campaign_tree))
    record.commit("m1x")
    answer = component.pick(record, lambda pick: 1.25)

    url = f"sqlite:///{tmp_path / 'score.db'}"
    component.persist_replay_score(answer, POLICY, WORLD, BETA, database_url=url)

    version, world, beta, score, node = _row(url, "replay_score")
    assert version == POLICY
    assert world == WORLD
    assert beta == BETA
    assert score == 1.25
    assert node == "m1x"


def test_the_composed_miss_persists_as_the_floor_with_a_null_pick(
    campaign_tree, component, tmp_path
) -> None:
    # The miss over the real composed path: a policy that emitted no pick is
    # scored -inf, and that score is persisted — never refused — with a NULL
    # committed_pick, so the decision that was never made stays
    # distinguishable from one that was.  The scorer would betray itself if
    # called (it raises), so this also pins the never-called property over the
    # composed write path.
    record = episode_commit(PolicyQuestion(campaign_tree))

    def betraying(pick) -> float:
        raise AssertionError("the scorer was called on a pick that was never emitted")

    answer = component.pick(record, betraying)
    assert answer.pick is None

    url = f"sqlite:///{tmp_path / 'score.db'}"
    component.persist_replay_score(answer, POLICY, WORLD, BETA, database_url=url)

    version, world, beta, score, node = _row(url, "replay_score")
    assert version == POLICY
    assert world == WORLD
    assert beta == BETA
    assert score == float("-inf")
    assert node is None


def test_two_runs_write_two_rows(campaign_tree, component, tmp_path) -> None:
    # One row per run: two writes of one (policy, world) pair are two rows,
    # each with its own id, never one upserted onto the other.
    record = episode_commit(PolicyQuestion(campaign_tree))
    record.commit("m1x")
    answer = component.pick(record, lambda pick: 0.5)

    url = f"sqlite:///{tmp_path / 'score.db'}"
    component.persist_replay_score(answer, POLICY, WORLD, BETA, database_url=url)
    component.persist_replay_score(answer, POLICY, WORLD, BETA, database_url=url)

    with sqlite3.connect(_path_of(url)) as connection:
        ids = [row[0] for row in connection.execute(
            "SELECT id FROM replay_score"
        ).fetchall()]
    assert len(ids) == 2
    assert ids[0] != ids[1]


# ---------------------------------------------------------------------------
# The refusals, over the composed seam
# ---------------------------------------------------------------------------


def test_a_store_that_cannot_take_the_write_is_surfaced_at_the_seam(
    campaign_tree, component, tmp_path
) -> None:
    # A score that was measured but never landed is surfaced, never swallowed:
    # the database's own refusal (a URL whose path is a directory) is
    # translated into the member's vocabulary at the composed seam.  Named by
    # type name, not isinstance, for the synthetic-module-name wrinkle.
    record = episode_commit(PolicyQuestion(campaign_tree))
    record.commit("m1x")
    answer = component.pick(record, lambda pick: 0.5)

    with pytest.raises(Exception) as raised:
        component.persist_replay_score(
            answer, POLICY, WORLD, BETA, database_url=f"sqlite:///{tmp_path}"
        )
    assert type(raised.value).__name__ == "ReplayScoreError"


def test_a_non_terminal_pick_is_refused_at_the_seam(component, tmp_path) -> None:
    # A carrier that is not a TerminalPick — no pick and no score — is refused
    # at the composed seam, naming what arrived, never isinstance-ed.
    url = f"sqlite:///{tmp_path / 'score.db'}"
    with pytest.raises(Exception) as raised:
        component.persist_replay_score(object(), POLICY, WORLD, BETA, database_url=url)
    assert type(raised.value).__name__ == "ReplayScoreError"
    assert "score" in str(raised.value)
