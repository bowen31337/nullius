"""Feature 255 — one replay_score row per run, into the relational store.

app_spec.xml, "Replay Engine", feature 255: *System persists one replay_score
row per run carrying policy version, world id, beta, score and committed
pick.*  The parent (249) reads the committed pick at termination and answers
the score a policy earns — the pair this feature writes — and this feature is
the row that records it.  docs §10.1 names the row in its own sentence —
*"every replay emits ``(policy_version, world_id, beta, score,
committed_pick)``"* — and migration 0109 legislates the schema it lands in.

These tests pin the feature as the facts it is made of, in the order a
deployment meets them:

* **the row is the record of a completed scoring, not a verdict on it** — a
  low or ``-inf`` score (the miss, feature 249's floor) is persisted, never
  refused, because the row is the record of a scoring that *completed*; the
  miss is a score the comparison keeps (prd §438, docs §598);
* **the value written is feature 249's TerminalPick, read duck-typed** — a
  carrier with a ``pick`` (absent-able) and a ``score`` (always present); a
  carrier with neither is refused, naming what arrived, never ``isinstance``-d
  (the loader's synthetic module name would make the check refuse the very
  value composition produces);
* **the ask is validated before the store is touched** — the carrier, the
  score, the ids and the beta are each validated before a connection is
  opened, and a broken ask is refused without opening so much as one, the
  ordering of every refusal in this member;
* **the score is a real number or -inf** — a NaN is refused (it compares false
  against everything and would drop out of every argmax, reading as "no
  scoring"); an infinity is the miss, persisted as the floor, never refused;
* **the policy version and world id are non-empty strings** — an id that names
  nothing writes a row no ``(policy, world)`` pair names;
* **the beta is a finite number** — the row's beta field is required, and an
  infinity is a value outside the space the scoring was made in;
* **the committed pick is the node id, or NULL for the miss** — a committing
  policy's pick is read through its one ``node_id``; a policy that emitted no
  pick writes NULL, so the decision that was never made stays distinguishable
  from one that was (migration 0109's nullable ``committed_pick``);
* **the write lands** — one row per run, a per-row uuid, carrying the five
  named columns; the store is addressed the way every store here is —
  ``DATABASE_URL`` by default, an explicit URL over it, a missing one refused
  by name and a non-sqlite scheme refused loudly;
* **a write that did not land is surfaced, never swallowed** — a store that
  cannot take the write raises in this member's vocabulary, chained to the
  database's own refusal;
* **no component** — a store addressed by ``DATABASE_URL`` is never composed:
  the member's one ``@register`` contribution stays feature 245's facade;
* **the vocabulary joins the member's one base class** — the persistence
  write's refusal is a sibling of the read's, the tree's and the report's, not
  nested under any of them.

The store under test is a per-test SQLite file under pytest's temporary
directory, spelled as a ``sqlite:///`` URL the way the root conftest spells
its own isolation — the member suite has no ambient ``DATABASE_URL`` to lean
on, and leaning on one would make the suite's answers depend on the
environment it ran in rather than the feature.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from replay import (
    NON_COMMITTING_SCORE,
    REPLAY_SCORE_TABLE,
    ReplayError,
    ReplayMetricsError,
    ReplayScoreError,
    TerminalPick,
    persist_replay_score,
)


class CommittedNode:
    """A committed pick — feature 222's CommittedPick, read through node_id.

    Duck-typed deliberately, and not an ``isinstance`` of the policy-runtime
    record: the module loader imports a member under a synthetic name and
    re-executes it, so the record ``create_app()``'s wiring produces may be a
    second class object of the same name, and the seam reads what the pick
    *is* — a carrier answering ``node_id`` — rather than which module defined
    it.
    """

    __slots__ = ("node_id",)

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


def committing_pick(node_id: str, score: float) -> TerminalPick:
    """A TerminalPick for a policy that committed to a node.

    The pair the row is shaped around — the pick (present) and the score
    (always present) — exactly as feature 249's ``committed_pick`` hands it.
    """
    return TerminalPick(pick=CommittedNode(node_id), score=score)


def miss(score: float = NON_COMMITTING_SCORE) -> TerminalPick:
    """A TerminalPick for a policy that emitted no pick — the miss.

    ``pick`` absent rather than nil-valued: the miss is a decision that was
    never made, and it stays distinguishable from one that was.  The score is
    the floor, which is the feature's whole point.
    """
    return TerminalPick(pick=None, score=score)


def store_url(tmp_path: Path) -> str:
    """The replay-score store's URL — a per-test SQLite file.

    Four slashes in total (``sqlite:///`` plus the absolute path's own), the
    SQLAlchemy convention the workspace's ``DATABASE_URL`` uses.
    """
    return f"sqlite:///{tmp_path / 'score.db'}"


# ---------------------------------------------------------------------------
# The row is the record of a completed scoring, not a verdict on it
# ---------------------------------------------------------------------------


def test_a_made_pick_is_persisted_whole(tmp_path: Path) -> None:
    # The feature's sentence, made concrete: one row carrying the five named
    # columns — the policy version, the world id, the beta, the score, and the
    # committed pick (the node id the policy committed to).  Read off the raw
    # table so the assertion is about what *landed*, not what a reader
    # reconstructs.
    url = store_url(tmp_path)
    row_id = persist_replay_score(
        committing_pick("m1x", 1.25),
        "policy-v0007",
        "world-financial-0042",
        0.02,
        database_url=url,
    )
    with sqlite3.connect(tmp_path / "score.db") as connection:
        rows = connection.execute(
            f"SELECT id, policy_version, world_id, beta, score, "
            f"committed_pick, is_holdout FROM {REPLAY_SCORE_TABLE}"
        ).fetchall()
    assert len(rows) == 1
    landed_id, version, world, beta, score, node, holdout = rows[0]
    assert landed_id == row_id
    assert version == "policy-v0007"
    assert world == "world-financial-0042"
    assert beta == 0.02
    assert score == 1.25
    assert node == "m1x"
    assert holdout == 0


def test_a_low_score_is_persisted_never_refused(tmp_path: Path) -> None:
    # A bad pick is still a completed scoring: the row records it, and the
    # store does not censor a score an operator holds the miss rate against.
    url = store_url(tmp_path)
    persist_replay_score(committing_pick("m1", -4.7), "p", "w", 0.02, database_url=url)
    with sqlite3.connect(tmp_path / "score.db") as connection:
        (score,) = connection.execute(
            f"SELECT score FROM {REPLAY_SCORE_TABLE}"
        ).fetchone()
    assert score == -4.7


def test_the_miss_is_persisted_as_the_floor(tmp_path: Path) -> None:
    # The miss — a policy that terminated without committing — is scored -inf,
    # and that score is persisted, not refused: it is the row an operator
    # counts, and dropping it would re-introduce at the write the exception
    # feature 249 removed from the comparison.  The committed_pick is NULL, so
    # the decision that was never made stays distinguishable from one that was.
    url = store_url(tmp_path)
    persist_replay_score(miss(), "p", "w", 0.02, database_url=url)
    with sqlite3.connect(tmp_path / "score.db") as connection:
        score, node = connection.execute(
            f"SELECT score, committed_pick FROM {REPLAY_SCORE_TABLE}"
        ).fetchone()
    assert score == float("-inf")
    assert node is None


def test_a_holdout_scoring_is_flagged(tmp_path: Path) -> None:
    # The holdout flag is a boolean beside the row: a scoring made as holdout
    # is written with the flag set, so the per-(policy, world) verdict can be
    # read on the holdout half alone.
    url = store_url(tmp_path)
    persist_replay_score(committing_pick("m1x", 0.5), "p", "w", 0.02, is_holdout=True, database_url=url)
    with sqlite3.connect(tmp_path / "score.db") as connection:
        (holdout,) = connection.execute(
            f"SELECT is_holdout FROM {REPLAY_SCORE_TABLE}"
        ).fetchone()
    assert holdout == 1


def test_two_runs_of_one_pair_are_two_rows(tmp_path: Path) -> None:
    # One row per run is the feature's whole point: a fresh uuid4 per call
    # keeps two runs of one ``(policy, world)`` pair as two rows, never one
    # upserted onto the other — unlike feature 254's latency table, whose key
    # is the snapshot instant.  Here there is no natural key; each run is its
    # own row.
    url = store_url(tmp_path)
    first = persist_replay_score(committing_pick("m1x", 0.5), "p", "w", 0.02, database_url=url)
    second = persist_replay_score(committing_pick("m1x", 0.7), "p", "w", 0.02, database_url=url)
    with sqlite3.connect(tmp_path / "score.db") as connection:
        ids = [row[0] for row in connection.execute(
            f"SELECT id FROM {REPLAY_SCORE_TABLE}"
        ).fetchall()]
    assert first != second
    assert len(ids) == 2


# ---------------------------------------------------------------------------
# The value written is feature 249's TerminalPick, read duck-typed
# ---------------------------------------------------------------------------


def test_a_foreign_terminal_pick_is_persisted(tmp_path: Path) -> None:
    # The seam reads what a TerminalPick *is* — a carrier with a ``pick``
    # (absent-able) and a ``score`` (always present) — never which module
    # defined it, because the loader imports a member under a synthetic name
    # and re-executes it: the value a composed application's path produced is
    # a second class object of the same name, and an isinstance would refuse
    # the very value composition produces.
    class ForeignPick:
        __slots__ = ("pick", "score")

        def __init__(self, pick: object, score: float) -> None:
            self.pick = pick
            self.score = score

    url = store_url(tmp_path)
    persist_replay_score(ForeignPick(CommittedNode("m1x"), 0.9), "p", "w", 0.02, database_url=url)
    with sqlite3.connect(tmp_path / "score.db") as connection:
        (score, node) = connection.execute(
            f"SELECT score, committed_pick FROM {REPLAY_SCORE_TABLE}"
        ).fetchone()
    assert score == 0.9
    assert node == "m1x"


def test_a_carrier_with_neither_pick_nor_score_is_refused(tmp_path: Path) -> None:
    # A value that is not a TerminalPick at all — no ``pick`` and no ``score``
    # — is refused, naming what arrived, rather than being scored or written.
    # The repair is the argument, on the caller's side of the seam.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(object(), "p", "w", 0.02, database_url=store_url(tmp_path))
    assert "score" in str(raised.value)


# ---------------------------------------------------------------------------
# The ask is validated before the store is touched
# ---------------------------------------------------------------------------


def test_a_nan_score_is_refused_before_the_store_is_touched(tmp_path: Path) -> None:
    # A NaN compares false against everything and would drop out of every
    # argmax, reading as "no scoring" — refused before the store is touched,
    # pinned over a URL that would itself refuse so which refusal answered is
    # unambiguous.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(
            TerminalPick(pick=None, score=float("nan")), "p", "w", 0.02,
            database_url="postgres://x/y",
        )
    assert "NaN" in str(raised.value)


def test_an_empty_policy_version_is_refused_before_the_store_is_touched(
    tmp_path: Path,
) -> None:
    # An id that names nothing writes a row no ``(policy, world)`` pair names —
    # the record of a scoring that did not happen.  Refused before the store
    # is touched, pinned over a URL that would itself refuse.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(
            miss(), "   ", "w", 0.02, database_url="postgres://x/y"
        )
    assert "policy version" in str(raised.value)


def test_an_empty_world_id_is_refused_before_the_store_is_touched(
    tmp_path: Path,
) -> None:
    # The same law as the policy version: an id that names nothing writes a
    # row no ``(policy, world)`` pair names.  Refused before the store is
    # touched.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(
            miss(), "p", "", 0.02, database_url="postgres://x/y"
        )
    assert "world id" in str(raised.value)


def test_a_non_finite_beta_is_refused_before_the_store_is_touched(
    tmp_path: Path,
) -> None:
    # The row's beta field is required, and a beta that is not finite would be
    # a hyperparameter no reader could reproduce the scoring under — an
    # infinity is a value outside the space the scoring was made in.  Refused
    # before the store is touched.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(
            miss(), "p", "w", float("inf"), database_url="postgres://x/y"
        )
    assert "beta" in str(raised.value)


def test_a_non_bool_holdout_flag_is_refused(tmp_path: Path) -> None:
    # The row records whether the scoring was made as holdout, and a flag that
    # is not a bool is an answer the flag was never asked for — a truthy
    # string or a non-zero int names no holdout decision.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(miss(), "p", "w", 0.02, is_holdout="yes", database_url=store_url(tmp_path))
    assert "holdout" in str(raised.value)


def test_a_non_number_score_is_refused(tmp_path: Path) -> None:
    # A score that is not a number names no scoring — the comparison's verdict
    # is a number, and the miss is -inf, not a non-number.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(
            TerminalPick(pick=None, score="0.5"), "p", "w", 0.02, database_url=store_url(tmp_path)
        )
    assert "real number" in str(raised.value)


# ---------------------------------------------------------------------------
# The committed pick is the node id, or NULL for the miss
# ---------------------------------------------------------------------------


def test_the_miss_writes_null_not_a_node(tmp_path: Path) -> None:
    # A policy that emitted no pick writes NULL, so the decision that was
    # never made stays distinguishable from one that was — NULL is not the
    # same fact as a node id the policy committed to.
    url = store_url(tmp_path)
    persist_replay_score(miss(0.5), "p", "w", 0.02, database_url=url)
    with sqlite3.connect(tmp_path / "score.db") as connection:
        (node,) = connection.execute(
            f"SELECT committed_pick FROM {REPLAY_SCORE_TABLE}"
        ).fetchone()
    assert node is None


def test_a_pick_without_a_node_id_is_refused(tmp_path: Path) -> None:
    # A pick that is not a committed pick — a carrier with no node_id — names
    # no node the policy committed to, and a committed_pick column holding it
    # would name a decision no node answers.  Refused, naming what arrived.
    class Nodeless:
        __slots__ = ("pick", "score")

        def __init__(self) -> None:
            self.pick = object()
            self.score = 0.5

    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(Nodeless(), "p", "w", 0.02, database_url=store_url(tmp_path))
    assert "node id" in str(raised.value)


# ---------------------------------------------------------------------------
# The write lands, and the store is addressed the way every store here is
# ---------------------------------------------------------------------------


def test_database_url_is_the_default_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The one ambient the workspace's stores share: without an explicit URL the
    # write goes to DATABASE_URL, so a deployment configures its store exactly
    # once and every member's store resolves the same way.
    url = store_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    row_id = persist_replay_score(committing_pick("m1x", 0.5), "p", "w", 0.02)
    assert row_id
    with sqlite3.connect(tmp_path / "score.db") as connection:
        assert connection.execute(
            f"SELECT COUNT(*) FROM {REPLAY_SCORE_TABLE}"
        ).fetchone()[0] == 1


def test_an_unconfigured_store_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A missing DATABASE_URL — and no explicit URL — is refused by name rather
    # than by a bare KeyError: the caller asked for a store it did not
    # configure, and the message says which variable would have named one.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(miss(), "p", "w", 0.02)
    assert "DATABASE_URL" in str(raised.value)


def test_a_non_sqlite_scheme_is_refused_loudly(tmp_path: Path) -> None:
    # The store speaks sqlite:/// (the spec's single-machine allowance), and
    # any other scheme is refused loudly rather than silently mis-parsed — a
    # misrouted Postgres URL cannot hide behind a mysterious file.  The same
    # refusal the cost-model member's stores document for theirs.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(
            miss(), "p", "w", 0.02, database_url="postgres://metrics/nullius"
        )
    assert "scheme" in str(raised.value)


def test_the_schema_is_created_idempotently(tmp_path: Path) -> None:
    # CREATE TABLE IF NOT EXISTS on connect — the contract every store in this
    # workspace states — so a fresh database and an existing one take one path,
    # and writing twice creates nothing new and breaks nothing existing.
    url = store_url(tmp_path)
    persist_replay_score(committing_pick("m1x", 0.5), "p", "w", 0.02, database_url=url)
    persist_replay_score(committing_pick("m1", 0.3), "p", "w", 0.02, database_url=url)
    with sqlite3.connect(tmp_path / "score.db") as connection:
        assert connection.execute(
            f"SELECT COUNT(*) FROM {REPLAY_SCORE_TABLE}"
        ).fetchone()[0] == 2


def test_a_store_that_cannot_take_the_write_is_surfaced(tmp_path: Path) -> None:
    # A score that was measured but never landed is the state the feature
    # exists to rule out: the database's own refusal (here, a database file
    # that is actually a directory) is translated into this member's
    # vocabulary, chained to the original so the operator still sees the
    # database's words — surfaced, never swallowed.
    with pytest.raises(ReplayScoreError) as raised:
        persist_replay_score(
            committing_pick("m1x", 0.5), "p", "w", 0.02,
            database_url=f"sqlite:///{tmp_path}",  # a directory, not a file
        )
    assert isinstance(raised.value.__cause__, sqlite3.Error)


# ---------------------------------------------------------------------------
# The vocabulary and the composed surface
# ---------------------------------------------------------------------------


def test_the_refusals_are_this_members_vocabulary(tmp_path: Path) -> None:
    # The persistence write's failures join the member's one base class — a
    # caller's single ``except ReplayError`` catches every way a score can fail
    # to land — and the class is a sibling of the read's, the tree's and the
    # report's, not nested under any of them: a caller skipping a bad campaign
    # must not silently skip a broken write, and vice versa.
    assert issubclass(ReplayScoreError, ReplayError)
    assert not issubclass(ReplayScoreError, ReplayMetricsError)
    from replay import ReplayReturnsError, ReplayTreeError

    assert not issubclass(ReplayScoreError, ReplayTreeError)
    assert not issubclass(ReplayScoreError, ReplayReturnsError)
    # A NaN score refuses in this member's vocabulary — a caller's single
    # ``except ReplayError`` catches it, over a store that would otherwise take
    # the write.
    with pytest.raises(ReplayError):
        persist_replay_score(miss(float("nan")), "p", "w", 0.02, database_url=store_url(tmp_path))


def test_the_persistence_surface_is_the_members_public_surface() -> None:
    # The package fronts the whole feature — the write, the table name, the
    # error — the way it fronts 252's timer and record, so a caller (the
    # dreaming loop, a benchmark, a dashboard's loader) holds one import and no
    # private module path.
    import replay

    for name in (
        "persist_replay_score",
        "ReplayScoreError",
        "REPLAY_SCORE_TABLE",
    ):
        assert name in replay.__all__, name
        assert getattr(replay, name, None) is not None, name


def test_the_composed_facade_carries_the_verb() -> None:
    # The composed spelling is the verb ReplayEngine.persist_replay_score on
    # feature 245's stateless facade — one import, no private module path — so
    # a caller holding the application persists a score the same way it takes a
    # pick.
    from replay import ReplayEngine

    engine = ReplayEngine()
    assert callable(getattr(engine, "persist_replay_score", None))


def test_the_feature_registers_no_component(tmp_path: Path) -> None:
    # A store addressed by DATABASE_URL is never composed — the stance every
    # store in this workspace takes — so the member's one @register
    # contribution stays feature 245's stateless facade, and composition still
    # spends no I/O on the persistence path.  A fresh registry, not the
    # process default: the question is exactly *what does this member
    # register?*
    import replay as replay_module

    from app.module_loader import Registration, scan_components

    member_src = Path(replay_module.__file__).resolve().parent.parent
    components = scan_components(member_src, registry=Registration())
    assert [component.name for component in components] == ["replay"]
