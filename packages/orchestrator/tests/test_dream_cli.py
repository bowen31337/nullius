"""Feature 11, the dreaming-cycle CLI -- ``python -m orchestrator.dream``.

additions_spec_operator_surfaces.xml, "Middle Loop Operation" category,
feature 11: *System runs one dreaming cycle over the stored world pool from*
``python -m orchestrator.dream --incumbent PATH [--iteration-id ID] [--beta
0.5] [--seed S] [--round-cap 30]``. *It prints the selected policy revision
and its train-vs-holdout gap.* This suite drives :func:`orchestrator.dream.main`
directly over a throwaway, real :class:`bootstrap.BootstrapPool` and the real
``0109`` migration's ``replay_score``/``policy_revision`` tables, never a
subprocess and never a mock of the dreaming, bootstrap, canary or
policy-runtime libraries.

One test per claim the feature sentence and the spec's test list make:

* **one cycle exits 0**, writes one ``replay_score`` row per (candidate,
  train world) and one per holdout world for the winner and the incumbent
  (deduplicated into one row when the incumbent is itself the winner), one
  ``selected`` ``policy_revision`` row and one meta-overfit row, and carries
  ``incumbent_holdout_mean`` beside ``holdout_mean``.
* **a rerun at the same iteration id and seed selects the same code_hash**,
  and still exits 0 -- ``revise_policy``'s own determinism, read back
  through the store's ``UNIQUE policy_version`` rather than crashing on it.
* **two cycles at the same seed and different iteration ids report means
  over their own rows only** -- a second cycle's ``train_mean`` and
  ``holdout_mean`` are unaffected by an earlier cycle run at the same seed,
  even when a jittered revision's content-addressed ``module_id`` is shared
  between the two.
* **an empty pool exits 1 with pool_too_thin and writes nothing.**
* **a recorded canary halt exits 1 with determinism_broken.**
* **--reviser llm exits 1 with policy_isolation_required.**
* **an incumbent that fails screening exits 1.**

Every ``main()`` call that is meant to reach the cycle itself first seeds a
recent, passing, evaluation-covering ``canary_run`` row
(:func:`_seed_passing_canary`) -- feature 143's own extension requires one
on record before ``require_dreaming_allowed`` lets a cycle through, the
same real path :func:`_seed_canary_halt` below drives for the halted case.

No test opens a network connection or reads a real credential, and no
state is kept at module scope across tests, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import importlib.util
import io
import json
import math
import sqlite3
import uuid
from contextlib import closing, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

import bootstrap
import pytest
import replay as replay_member
from canary import (
    DEFAULT_TOLERANCE,
    CanaryReferencePair,
    CanaryRunStore,
    CanaryTree,
    halt_dreaming,
    replay_pair,
)
from canary._reference import CanaryPolicy
from orchestrator.dream import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REFUSED,
    POLICY_ISOLATION_CODE,
    main,
)

#: The miss sentinel, taken from the member that defines it rather than
#: re-spelled: a stored non-committing reading is exactly
#: :data:`replay.NON_COMMITTING_SCORE`, and the tests below read it back out of
#: ``replay_score`` to recompute the summary's own flat book.
NON_COMMITTING_SCORE = replay_member.NON_COMMITTING_SCORE

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the resolution test_closeout_cli.py and
# test_campaign_cli.py already use.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

REPLAY_MIGRATION = "0109_replay_score_and_policy_revision"

#: A commit-reachable, screening-admissible incumbent with exactly one
#: jitterable magnitude (``THRESHOLD``). Deliberately avoids every numeric
#: literal used as a list index or in a comparison: ``revise_policy``'s
#: default reviser jitters *every* numeric ``ast.Constant`` it finds, so an
#: incumbent that indexed with a literal (``roots[0]``) would have that very
#: ``0`` jittered into a float and crash at replay -- a trap this incumbent
#: is written to avoid by walking every sequence instead of indexing it.
#: ``screen_policy`` refuses any ``ast.Compare`` against a numeric literal
#: (feature 230's ``absolute-score`` check), so the stopping rule compares
#: two *expressions* (a squared distance against the running best) rather
#: than either side against a bare number.
INCUMBENT_SOURCE = """
THRESHOLD = 0.37


def select(question):
    roots = question.legal_roots()
    observed = question.observed()
    if not observed:
        fallback = None
        for root in roots:
            fallback = root
            break
        question.commit(fallback)
        return list(roots)
    best = None
    best_distance = None
    for node_id, obs in observed.items():
        diff = obs.r2_train - THRESHOLD
        distance = diff * diff
        if best_distance is None or distance < best_distance:
            best = node_id
            best_distance = distance
    question.commit(best)
    frontier = []
    for node_id in observed:
        for action in question.legal_actions(node_id):
            if action not in observed and action not in frontier:
                frontier.append(action)
    return frontier
"""

#: No ``commit()`` call anywhere -- refused by ``policy_runtime.screen_policy``
#: before anything is imported or run, the same shape
#: ``test_bootstrap_eval.py``'s ``FAILS_SCREENING_SOURCE`` takes.
FAILS_SCREENING_SOURCE = "def select(question):\n    return question.legal_roots()\n"

#: An incumbent that **may abstain**: it commits the highest-revealed node only
#: when that node clears :data:`ABSTAINING_THRESHOLD`, and declares
#: ``question.abstain()`` otherwise.  This is the shape defect M3-INC-1 is
#: about -- a policy that commits no pick on *some* bootstrap worlds scores
#: ``-inf`` there (``replay.NON_COMMITTING_SCORE``), and before the fix the
#: selection aggregate refused the whole candidate for it, so no cycle could
#: ever select such a policy, its own authoring incumbent included.
#:
#: At :data:`ABSTAINING_THRESHOLD` over
#: :data:`ABSTAINING_POOL_WORLD_COUNT` the incumbent abstains on some worlds of
#: *both* halves: the cycles below run at ``--iteration-id dream-flat-A`` (the
#: seed, and through it the halves' rotation and every jitter, is the iteration
#: id) and the winning revision still commits everywhere while the incumbent
#: abstains on 7 of the 14 holdout worlds.  A seed whose jitters tie on the
#: blend is a *different* defect's subject -- the argmax's own
#: ``selection_malformed`` refusal -- and ``cli-flat`` and ``m3-attempt-1`` are
#: both such seeds over this pool, which is why neither is used here.
ABSTAINING_THRESHOLD = 0.98

#: The ``--iteration-id`` the two tests below run over, and the only part of
#: the cycle that turns the pool's rotation and the reviser's jitters into a
#: tie-free tournament.  Named once so the select test and its refuse-under-
#: the-default twin cannot drift onto different seeds.
ABSTAINING_ITERATION_ID = "dream-flat-A"

ABSTAINING_INCUMBENT_SOURCE = f'''
"""An incumbent that commits only where a revealed node clears the bar."""

THRESHOLD = {ABSTAINING_THRESHOLD}


def select(question):
    roots = question.legal_roots()
    observed = question.observed()
    if not observed:
        question.abstain()
        return list(roots)
    best = None
    best_value = None
    for node_id, obs in observed.items():
        value = obs.r2_train
        if best_value is None or value > best_value:
            best = node_id
            best_value = value
    if best_value > THRESHOLD:
        question.commit(best)
    else:
        question.abstain()
    frontier = []
    for node_id in observed:
        for action in question.legal_actions(node_id):
            if action not in observed and action not in frontier:
                frontier.append(action)
    return frontier
'''

#: Enough worlds to clear the ladder floor (20) but stay on the capped rung
#: (below 50), so ``M = 10`` -- a sweep small enough for a fast suite.
POOL_WORLD_COUNT = 40
POOL_SEED = 20261006

#: The pool :data:`ABSTAINING_INCUMBENT_SOURCE` is swept over -- 45 worlds, the
#: size the refused ``m3-attempt-1`` cycle actually ran on, chosen because at
#: :data:`ABSTAINING_THRESHOLD` it is the pool on which that incumbent abstains
#: on *some* worlds of both halves without any candidate tying on the blend
#: (the argmax's own refusal, a different defect's subject).  A pool the
#: incumbent abstains on *everywhere* would select nothing there either, and
#: one it never abstains on would not exercise the fix at all.
ABSTAINING_POOL_WORLD_COUNT = 45


class _FakeApp:
    """Answers the one composed component this CLI reads -- ``replay``.

    A real :class:`replay.ReplayEngine` (``replay.build_replay_engine()``
    takes no configuration, so constructing one directly is the same object
    a real ``create_app()`` would hand back), without paying for the full
    composition scan every other component's ``@register`` would run. This
    suite's subject is the dreaming join (:mod:`orchestrator.dream`), not
    composition -- :mod:`test_campaign_cli` makes the identical call for the
    identical reason, with fakes standing in for components this module
    does not even read.
    """

    def get(self, name: str) -> Any:
        if name == "replay":
            return replay_member.ReplayEngine()
        return None


_APP = _FakeApp()


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_dream_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sqlite_path(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _table_row_count(database_url: str, table: str) -> int:
    """How many rows ``table`` holds, or 0 when the table does not exist yet.

    Every table this cycle writes is created lazily (``CREATE TABLE IF NOT
    EXISTS``) by the first write to it, so a refused run that touched none
    of them leaves the table itself absent -- zero, not a missing-table
    error, is the honest count of what a refusal wrote.
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        try:
            (count,) = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        except sqlite3.OperationalError:
            return 0
    return int(count)


def _migrated_pool(tmp_path: Path, *, world_count: int | None = POOL_WORLD_COUNT) -> str:
    """A throwaway SQLite database with the pool's real shape.

    ``bootstrap.BootstrapPool.persist_worlds`` authors ``bootstrap_world``
    (``world_count`` worlds, or none at all for the thin-pool case), and the
    real ``0109`` migration brings up ``replay_score`` and
    ``policy_revision`` -- the same two steps the dream CLI itself never
    performs (CLAUDE.md's migration tree stays out of every feature's file
    claim), so a cycle run against this database sees exactly what a
    migrated deployment's does.
    """
    database_url = f"sqlite:///{tmp_path / 'dream-test.db'}"
    pool = bootstrap.BootstrapPool(database_url)
    if world_count:
        pool.persist_worlds(world_count, pool_seed=POOL_SEED)
    else:
        pool.ensure_schema()
    _load_migration(REPLAY_MIGRATION).apply(database_url)
    return database_url


def _write_incumbent(tmp_path: Path, source: str, *, name: str = "incumbent.py") -> str:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _seed_canary_halt(database_url: str) -> None:
    """Record a real determinism break -- §12's halt, through the real path.

    A frozen pair whose recorded constant the replay misses by a wide
    margin, replayed for real through :func:`canary.replay_pair`, then
    recorded through :func:`canary.halt_dreaming` -- the same two calls a
    nightly canary run makes, not a hand-written row.
    """
    policy = CanaryPolicy.freeze(
        version="canary-v1",
        policy={"scoring": {"weights": {"a": 0.5, "b": 0.5}}, "threshold": 0.7},
    )
    tree = CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root", "kind": "decision", "score": 0.0}),
            "left": ("root", 1, {"label": "left", "weight": 0.3, "score": 0.8}),
            "right": ("root", 1, {"label": "right", "weight": 0.7, "score": 0.6}),
        }
    )
    expected_score = 0.8 * 0.3 + 0.6 * 0.7
    broken_pair = CanaryReferencePair(
        policy=policy,
        tree=tree,
        recorded_score=expected_score + 0.5,
        id=None,
        is_active=True,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    result = replay_pair(broken_pair)
    with pytest.raises(Exception):  # noqa: B017 - halt_dreaming raises after recording
        halt_dreaming(broken_pair, result, database_url=database_url)


def _seed_passing_canary(database_url: str) -> None:
    """Record a recent, passing, evaluation-covering ``canary_run`` row.

    ``require_dreaming_allowed`` refuses a cycle with no halt on record
    unless the *newest* canary run also passed, ran recently and covered
    the evaluation canary -- this helper is the minimal row that clears all
    three, recorded directly through :class:`canary.CanaryRunStore` (the
    store the guard itself reads) rather than through a full
    ``python -m canary.run``, the same "drive the real store, not the CLI"
    stance :func:`_seed_canary_halt` takes for the halted case above.
    """
    CanaryRunStore(database_url).record(
        str(uuid.uuid4()),
        score=0.0,
        recorded_score=0.0,
        deviation=0.0,
        tolerance=DEFAULT_TOLERANCE,
        within_tolerance=True,
        evaluation_canary=True,
        ran_at=datetime.now(timezone.utc),
    )


# -- One cycle ------------------------------------------------------------------


def test_one_cycle_exits_0_and_writes_expected_rows(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path)
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}
    lines: list[str] = []

    exit_code = main(
        ["--incumbent", incumbent_path, "--iteration-id", "cycle-5", "--round-cap", "5"],
        env=env,
        emit=lines.append,
        app=_APP,
    )

    assert exit_code == EXIT_OK
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["iteration_id"] == "cycle-5"
    assert payload["n_bootstrap"] == POOL_WORLD_COUNT
    assert payload["n_financial"] == 0
    assert payload["revision_cap"] == 10  # 40 worlds: the 20-50 rung, M = 10
    assert isinstance(payload["module_id"], str) and payload["module_id"]
    assert isinstance(payload["code_hash"], str) and len(payload["code_hash"]) == 64
    assert isinstance(payload["train_mean"], float)
    assert isinstance(payload["holdout_mean"], float)
    assert isinstance(payload["incumbent_holdout_mean"], float)
    assert payload["gap"] == pytest.approx(payload["train_mean"] - payload["holdout_mean"])

    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        train_rows = connection.execute(
            "SELECT COUNT(*) FROM replay_score WHERE is_holdout = 0"
        ).fetchone()[0]
        holdout_rows = connection.execute(
            "SELECT COUNT(*) FROM replay_score WHERE is_holdout = 1"
        ).fetchone()[0]
        selected = connection.execute(
            "SELECT policy_version, code_hash FROM policy_revision WHERE selected = 1"
        ).fetchall()

    # M = 10 revisions + the incumbent = 11 candidates, each scored once per
    # train world; the holdout half is scored for the winner and the
    # incumbent (the module docstring's two-phase sweep), deduplicated into
    # one sweep entry on the holdout half when the incumbent is itself the
    # winner -- the only case :mod:`orchestrator.dream` itself can tell
    # apart from this test's own read of the stored rows.
    revision_count = payload["revision_cap"] + 1
    train_world_count = round(POOL_WORLD_COUNT * 0.7)
    holdout_world_count = POOL_WORLD_COUNT - train_world_count
    holdout_candidate_count = 1 if payload["module_id"].startswith("incumbent-") else 2
    assert train_rows == revision_count * train_world_count
    assert holdout_rows == holdout_candidate_count * holdout_world_count
    assert payload["replay_score_rows"] == train_rows + holdout_rows

    assert len(selected) == 1
    assert selected[0] == (payload["module_id"], payload["code_hash"])

    assert _table_row_count(database_url, "ops_meta_overfit_gap") == 1


def test_rerun_same_iteration_id_and_seed_selects_same_code_hash(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path)
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}
    argv = [
        "--incumbent", incumbent_path,
        "--iteration-id", "cycle-8",
        "--round-cap", "5",
    ]

    first: list[str] = []
    second: list[str] = []
    first_exit = main(argv, env=env, emit=first.append, app=_APP)
    second_exit = main(argv, env=env, emit=second.append, app=_APP)

    assert first_exit == EXIT_OK
    assert second_exit == EXIT_OK

    first_payload = json.loads(first[0])
    second_payload = json.loads(second[0])
    assert first_payload["code_hash"] == second_payload["code_hash"]
    assert first_payload["module_id"] == second_payload["module_id"]

    # No duplicate winner row: the rerun read the first cycle's row back
    # rather than re-inserting it.
    assert _table_row_count(database_url, "policy_revision") == 1


def test_two_cycles_same_seed_different_iteration_report_own_rows_only(
    tmp_path: Path,
) -> None:
    """A second cycle at the same ``--seed`` reports over its own rows only.

    ``revise_policy``'s candidates are deterministic in ``(incumbent, count,
    seed)`` -- independent of ``--iteration-id`` -- so a jittered revision's
    ``module_id`` is identical whether it is produced by "cycle-5" or
    "cycle-5b" at ``--seed cycle-5``.  "cycle-5" then "cycle-5b" is this
    exact (``INCUMBENT_SOURCE``, ``POOL_SEED``, ``POOL_WORLD_COUNT``,
    ``round_cap=5``) combination's own confirmed-deterministic pair: the
    same candidate, ``cand-77f12e77be3865d308ed57b21999e4c9``, wins both
    cycles, so the second cycle's own ``replay_score`` rows for its winner
    sit beside the first cycle's leftover rows for the identical
    ``policy_version`` -- the exact collision :func:`orchestrator.dream.
    run_cycle`'s own comment names. A query scoped only by ``policy_version``
    (the pre-fix shape) would then average in the first cycle's rows too,
    over a train/holdout split the first cycle's own rotation drew
    differently; this test proves the second cycle's reported
    ``train_mean``/``holdout_mean`` disagree with exactly that naive query,
    which is only possible when they are read from the second cycle's own
    measurements instead.
    """
    database_url = _migrated_pool(tmp_path)
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}

    first: list[str] = []
    second: list[str] = []
    first_exit = main(
        ["--incumbent", incumbent_path, "--iteration-id", "cycle-5", "--round-cap", "5"],
        env=env,
        emit=first.append,
        app=_APP,
    )
    second_exit = main(
        [
            "--incumbent", incumbent_path,
            "--iteration-id", "cycle-5b",
            "--seed", "cycle-5",
            "--round-cap", "5",
        ],
        env=env,
        emit=second.append,
        app=_APP,
    )

    assert first_exit == EXIT_OK
    assert second_exit == EXIT_OK

    first_payload = json.loads(first[0])
    second_payload = json.loads(second[0])

    # The scenario's own precondition: the two cycles' rows really do
    # collide under one policy_version, which is what makes the rest of
    # this test meaningful rather than vacuous.
    assert first_payload["module_id"] == second_payload["module_id"]

    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT score, is_holdout FROM replay_score "
            "WHERE policy_version = ? AND beta = 0.5",
            (second_payload["module_id"],),
        ).fetchall()
    naive_train = [score for score, is_holdout in rows if not is_holdout]
    naive_holdout = [score for score, is_holdout in rows if is_holdout]

    # Both cycles' own rows are really there, under the one shared
    # policy_version -- twice the row count either cycle alone would write.
    assert len(naive_train) == 2 * round(POOL_WORLD_COUNT * 0.7)
    assert len(naive_holdout) == 2 * (POOL_WORLD_COUNT - round(POOL_WORLD_COUNT * 0.7))

    naive_train_mean = sum(naive_train) / len(naive_train)
    naive_holdout_mean = sum(naive_holdout) / len(naive_holdout)

    # The second cycle's own reported means disagree with the naive,
    # unscoped query over the very same policy_version -- the only way
    # that can happen is that they were never read from it.
    assert second_payload["train_mean"] != pytest.approx(naive_train_mean)
    assert second_payload["holdout_mean"] != pytest.approx(naive_holdout_mean)


def test_incumbent_is_swept_on_holdout_beside_the_winner(tmp_path: Path) -> None:
    """The incumbent is swept over holdout beside the winner, as its own entry.

    "cycle-5" is this exact (``INCUMBENT_SOURCE``, ``POOL_SEED``,
    ``POOL_WORLD_COUNT``, ``round_cap=5``) combination's own confirmed case
    where the winner is a jittered revision rather than the incumbent (see
    :func:`test_two_cycles_same_seed_different_iteration_report_own_rows_only`),
    so the incumbent's holdout sweep here is a genuinely separate sweep
    entry, never the deduplicated case where the incumbent is itself the
    winner.
    """
    database_url = _migrated_pool(tmp_path)
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}
    lines: list[str] = []

    exit_code = main(
        ["--incumbent", incumbent_path, "--iteration-id", "cycle-5", "--round-cap", "5"],
        env=env,
        emit=lines.append,
        app=_APP,
    )

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    incumbent_version = f"incumbent-{payload['iteration_id']}"
    assert payload["module_id"] != incumbent_version

    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        incumbent_holdout_rows = connection.execute(
            "SELECT score FROM replay_score WHERE policy_version = ? AND is_holdout = 1",
            (incumbent_version,),
        ).fetchall()

    holdout_world_count = POOL_WORLD_COUNT - round(POOL_WORLD_COUNT * 0.7)
    assert len(incumbent_holdout_rows) == holdout_world_count
    expected_mean = sum(score for (score,) in incumbent_holdout_rows) / holdout_world_count
    assert payload["incumbent_holdout_mean"] == pytest.approx(expected_mean)


# -- Refusals ---------------------------------------------------------------


def test_empty_pool_exits_1_pool_too_thin_and_writes_nothing(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path, world_count=None)
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            ["--incumbent", incumbent_path], env=env, emit=lambda _line: None, app=_APP
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert "pool_too_thin" in message
    assert "0" in message
    assert "20" in message
    assert "Traceback" not in message

    for table in ("cycle_cap", "pool_freeze", "cycle_holdout", "policy_revision", "replay_score"):
        assert _table_row_count(database_url, table) == 0


def test_recorded_canary_halt_exits_1_determinism_broken(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path)
    _seed_canary_halt(database_url)
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            ["--incumbent", incumbent_path], env=env, emit=lambda _line: None, app=_APP
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert "determinism_broken" in message
    assert "Traceback" not in message

    for table in ("cycle_cap", "pool_freeze", "cycle_holdout", "policy_revision"):
        assert _table_row_count(database_url, table) == 0


def test_reviser_llm_exits_1_policy_isolation_required(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path)
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            ["--incumbent", incumbent_path, "--reviser", "llm"],
            env=env,
            emit=lambda _line: None,
            app=_APP,
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert POLICY_ISOLATION_CODE in message
    assert "Traceback" not in message

    for table in ("cycle_cap", "pool_freeze", "cycle_holdout", "policy_revision"):
        assert _table_row_count(database_url, table) == 0


def test_incumbent_that_fails_screening_exits_1(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path)
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, FAILS_SCREENING_SOURCE)
    env = {"DATABASE_URL": database_url}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            ["--incumbent", incumbent_path], env=env, emit=lambda _line: None, app=_APP
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert "unreachable-commit" in message
    assert "Traceback" not in message

    for table in ("cycle_cap", "pool_freeze", "cycle_holdout", "policy_revision"):
        assert _table_row_count(database_url, table) == 0


def test_missing_database_url_exits_2_naming_it(tmp_path: Path) -> None:
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--incumbent", incumbent_path], env={}, emit=lambda _line: None)

    assert exit_code == EXIT_CONFIG
    assert "DATABASE_URL" in stderr.getvalue()


# -- --write-selected -----------------------------------------------------------


def test_write_selected_writes_the_winner_source_and_refuses_to_overwrite(
    tmp_path: Path,
) -> None:
    database_url = _migrated_pool(tmp_path)
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}
    destination = tmp_path / "next-policy.py"

    exit_code = main(
        [
            "--incumbent", incumbent_path,
            "--iteration-id", "cycle-5",
            "--round-cap", "5",
            "--write-selected", str(destination),
        ],
        env=env,
        emit=lambda _line: None,
        app=_APP,
    )

    assert exit_code == EXIT_OK
    assert destination.is_file()
    assert destination.read_text(encoding="utf-8").strip()

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        second_exit = main(
            [
                "--incumbent", incumbent_path,
                "--iteration-id", "cycle-write-2",
                "--round-cap", "5",
                "--write-selected", str(destination),
            ],
            env=env,
            emit=lambda _line: None,
        )

    assert second_exit == EXIT_REFUSED
    assert "already exists" in stderr.getvalue()


# -- the flat book in selection (M3-INC-1) --------------------------------------


def test_an_abstaining_incumbent_selects_and_the_summary_counts_the_flat_book(
    tmp_path: Path,
) -> None:
    """A cycle whose incumbent abstains on some worlds still selects and exits 0.

    M3-INC-1's reproduction, end to end: :data:`ABSTAINING_INCUMBENT_SOURCE` on
    :data:`ABSTAINING_POOL_WORLD_COUNT` worlds abstains on some train worlds,
    so its ``replay_score`` rows carry ``replay.NON_COMMITTING_SCORE``
    (``-inf``).  Before the fix the selection aggregate handed that reading to
    ``scoring.aggregate_objective``, which refuses it, and the whole cycle
    exited 1 with ``selection_ungrounded`` — *every* candidate, not only the
    abstaining one, because the memory of a miss made the tournament
    unselectable.  The incumbent is the policy already in force, so a cycle
    can never select a policy that may abstain, which is exactly what the
    pre-registration's Addendum 3 incumbent does.

    Now ``commit_selection`` is asked for ``non_committing="flat"``: a miss
    enters the §7 blend as the flat book's ``0.0``, the argmax crowns a
    winner, and the summary's three means are finite — each one the hand
    computation with ``0.0`` substituted for every sentinel row, over the
    worlds *this* call measured.  The commit rates ride beside them, read from
    the raw sentinel before the substitution: the winner committed on every
    world, and the incumbent on ``7/14`` of the holdout worlds, so the two
    rates disagree and neither could have been recovered from a flattened
    mean (a genuine ``0.0`` and a flattened miss are the same number).
    """
    database_url = _migrated_pool(
        tmp_path, world_count=ABSTAINING_POOL_WORLD_COUNT
    )
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, ABSTAINING_INCUMBENT_SOURCE)
    env = {"DATABASE_URL": database_url}
    lines: list[str] = []

    exit_code = main(
        [
            "--incumbent", incumbent_path,
            "--iteration-id", ABSTAINING_ITERATION_ID,
            "--round-cap", "5",
        ],
        env=env,
        emit=lines.append,
        app=_APP,
    )

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])

    # Every mean is a real number, not -inf: the sentinel never reached the
    # arithmetic the summary reports.
    for key in ("train_mean", "holdout_mean", "incumbent_holdout_mean"):
        assert math.isfinite(payload[key]), key

    winner = payload["module_id"]
    incumbent = f"incumbent-{payload['iteration_id']}"
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT policy_version, is_holdout, score FROM replay_score "
            "WHERE beta = 0.5 AND policy_version IN (?, ?)",
            (winner, incumbent),
        ).fetchall()

    arm: dict[tuple[str, int], list[float]] = {}
    for policy_version, is_holdout, score in rows:
        arm.setdefault((policy_version, int(is_holdout)), []).append(score)

    def flat_mean(policy_version: str, holdout: int) -> float:
        readings = arm[(policy_version, holdout)]
        return sum(
            0.0 if reading == NON_COMMITTING_SCORE else reading for reading in readings
        ) / len(readings)

    def commit_rate(policy_version: str, holdout: int) -> float:
        readings = arm[(policy_version, holdout)]
        return sum(
            1 for reading in readings if reading != NON_COMMITTING_SCORE
        ) / len(readings)

    assert payload["train_mean"] == pytest.approx(flat_mean(winner, 0))
    assert payload["holdout_mean"] == pytest.approx(flat_mean(winner, 1))
    assert payload["incumbent_holdout_mean"] == pytest.approx(flat_mean(incumbent, 1))
    assert payload["train_commit_rate"] == pytest.approx(commit_rate(winner, 0))
    assert payload["holdout_commit_rate"] == pytest.approx(commit_rate(winner, 1))
    assert payload["incumbent_holdout_commit_rate"] == pytest.approx(
        commit_rate(incumbent, 1)
    )

    # The scenario is real rather than vacuous: the incumbent really does
    # abstain, and the winner really is one of the abortive incumbent's own
    # jittered revisions -- so this cycle's selection was decided on a
    # tournament a miss had entered.
    assert payload["incumbent_holdout_commit_rate"] < 1.0
    assert payload["incumbent_holdout_commit_rate"] == pytest.approx(0.5)
    assert arm[(incumbent, 1)].count(NON_COMMITTING_SCORE) == 7
    assert arm[(incumbent, 0)].count(NON_COMMITTING_SCORE) > 0
    assert winner != incumbent
    assert payload["gap"] == pytest.approx(
        payload["train_mean"] - payload["holdout_mean"]
    )


def test_the_default_still_refuses_an_abstaining_incumbent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scope, held end to end: the flat book is opted into, never the default.

    The cycle asks for ``non_committing="flat"`` *by name* -- that is the fix.
    The validator's own default is still today's refusal, so a caller that
    reaches the selection seam without asking for the flat book meets the
    ``selection_ungrounded`` refusal this defect reported.  The same pool the
    test above selects on is run with the cycle's one call forced back to
    ``"refuse"``: the ``-inf`` reading is refused and the CLI exits 1, which
    proves the pool really does carry the sentinel (rather than the winner
    being one that never misses) and that the flat book is the only thing
    standing between this incumbent and the reported refusal.
    """
    from orchestrator import dream as dream_module

    calls: list[object] = []
    real_commit = dream_module.dreaming.commit_selection

    def spiral(candidates, **kwargs):
        calls.append(kwargs.get("non_committing"))
        return real_commit(candidates, **{**kwargs, "non_committing": "refuse"})

    database_url = _migrated_pool(
        tmp_path, world_count=ABSTAINING_POOL_WORLD_COUNT
    )
    _seed_passing_canary(database_url)
    incumbent_path = _write_incumbent(tmp_path, ABSTAINING_INCUMBENT_SOURCE)

    monkeypatch.setattr(dream_module.dreaming, "commit_selection", spiral)

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "--incumbent", incumbent_path,
                "--iteration-id", ABSTAINING_ITERATION_ID,
                "--round-cap", "5",
            ],
            env={"DATABASE_URL": database_url},
            emit=lambda _line: None,
            app=_APP,
        )

    # The cycle wired its own spelling through, and only the flat book was
    # rewritten underneath it -- so the refusal that follows is the reported
    # defect, not a differently-configured run.
    assert calls == [dream_module._NON_COMMITTING_FLAT]
    assert exit_code == EXIT_REFUSED
    assert "selection_ungrounded" in stderr.getvalue()
