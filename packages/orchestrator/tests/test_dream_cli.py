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
  train world) and one per holdout world for the winner, one ``selected``
  ``policy_revision`` row and one meta-overfit row.
* **a rerun at the same iteration id and seed selects the same code_hash**,
  and still exits 0 -- ``revise_policy``'s own determinism, read back
  through the store's ``UNIQUE policy_version`` rather than crashing on it.
* **an empty pool exits 1 with pool_too_thin and writes nothing.**
* **a recorded canary halt exits 1 with determinism_broken.**
* **--reviser llm exits 1 with policy_isolation_required.**
* **an incumbent that fails screening exits 1.**

No test opens a network connection or reads a real credential, and no
state is kept at module scope across tests, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import importlib.util
import io
import sqlite3
from contextlib import closing, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

import bootstrap
import pytest
import replay as replay_member
from canary import CanaryReferencePair, CanaryTree, halt_dreaming, replay_pair
from canary._reference import CanaryPolicy
from orchestrator.dream import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REFUSED,
    POLICY_ISOLATION_CODE,
    main,
)

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

#: Enough worlds to clear the ladder floor (20) but stay on the capped rung
#: (below 50), so ``M = 10`` -- a sweep small enough for a fast suite.
POOL_WORLD_COUNT = 40
POOL_SEED = 20261006


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


# -- One cycle ------------------------------------------------------------------


def test_one_cycle_exits_0_and_writes_expected_rows(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path)
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
    import json

    payload = json.loads(lines[0])
    assert payload["iteration_id"] == "cycle-5"
    assert payload["n_bootstrap"] == POOL_WORLD_COUNT
    assert payload["n_financial"] == 0
    assert payload["revision_cap"] == 10  # 40 worlds: the 20-50 rung, M = 10
    assert isinstance(payload["module_id"], str) and payload["module_id"]
    assert isinstance(payload["code_hash"], str) and len(payload["code_hash"]) == 64
    assert isinstance(payload["train_mean"], float)
    assert isinstance(payload["holdout_mean"], float)
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
    # train world; the holdout half is scored for the winner only (the
    # module docstring's two-phase sweep).
    revision_count = payload["revision_cap"] + 1
    train_world_count = round(POOL_WORLD_COUNT * 0.7)
    holdout_world_count = POOL_WORLD_COUNT - train_world_count
    assert train_rows == revision_count * train_world_count
    assert holdout_rows == holdout_world_count
    assert payload["replay_score_rows"] == train_rows + holdout_rows

    assert len(selected) == 1
    assert selected[0] == (payload["module_id"], payload["code_hash"])

    assert _table_row_count(database_url, "ops_meta_overfit_gap") == 1


def test_rerun_same_iteration_id_and_seed_selects_same_code_hash(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path)
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

    import json

    first_payload = json.loads(first[0])
    second_payload = json.loads(second[0])
    assert first_payload["code_hash"] == second_payload["code_hash"]
    assert first_payload["module_id"] == second_payload["module_id"]

    # No duplicate winner row: the rerun read the first cycle's row back
    # rather than re-inserting it.
    assert _table_row_count(database_url, "policy_revision") == 1


# -- Refusals ---------------------------------------------------------------


def test_empty_pool_exits_1_pool_too_thin_and_writes_nothing(tmp_path: Path) -> None:
    database_url = _migrated_pool(tmp_path, world_count=None)
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
