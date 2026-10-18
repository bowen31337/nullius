"""Feature 1 (additions_spec_operator_surfaces.xml) -- ``python -m canary.run``.

*System runs the determinism canary from* ``python -m canary.run``, *which
records every run so that "the canary ran and passed" is a stored fact
rather than the absence of a halt.*  This suite drives :func:`canary.run.main`
directly over a throwaway, per-test SQLite file -- never a real subprocess,
the same discipline :mod:`orchestrator.closeout`'s own CLI suite uses.

One test per claim the feature sentence makes:

* **freeze then run** gives exit 0, writes exactly one ``canary_run`` row,
  and reports ``within_tolerance`` true -- the pair's recorded constant is
  its own replay score, so the first plain run always holds.
* **a second freeze is refused** with the code word
  :data:`~canary.run.CANARY_REFERENCE_EXISTS`, changing nothing: the active
  reference count stays one.
* **a tampered recorded_score** -- the active pair's own stored constant,
  edited directly, past the pair's replay score -- gives exit 3, a
  ``canary_dream_halt`` row and a ``canary_run`` row, both written before
  the broken line is printed.
* **an empty store** (no freeze ever run) gives
  :data:`~canary.run.CANARY_REFERENCE_ABSENT`.
* **more than one active reference** gives
  :data:`~canary.run.CANARY_REFERENCE_AMBIGUOUS` -- the cardinality this
  module enforces, not the store.
* **a missing DATABASE_URL** exits 2, naming the variable.
* **newest()** returns the latest of two directly-recorded rows, ordered by
  ``ran_at``, not by insertion order.
* **the store composes as "canary-run-store"** through the application
  factory, ``None`` without a ``DATABASE_URL`` and degrading nothing else.

No test opens a network connection or writes outside a pytest temporary
directory, and none holds state at module scope, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from collections.abc import Callable
from contextlib import closing, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

import pytest
from canary import REFERENCE_TABLE
from canary.run import (
    CANARY_EVALUATION_CONFIG_MISMATCH,
    CANARY_EVALUATION_REFERENCE_EXISTS,
    CANARY_EVALUATION_SCORE_NOT_FINITE,
    CANARY_REFERENCE_ABSENT,
    CANARY_REFERENCE_AMBIGUOUS,
    CANARY_REFERENCE_EXISTS,
    DATABASE_URL_ENV,
    EVALUATION_CAMPAIGN_ID_ENV,
    EVALUATION_NODE_ID_ENV,
    EVALUATION_REFERENCE_TABLE,
    EXIT_BROKEN,
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REFUSED,
    RUN_TABLE,
    CanaryRunStore,
    main,
)


def _url(tmp_path: Path, name: str = "canary.db") -> str:
    return f"sqlite:///{tmp_path / name}"


def _path(url: str) -> Path:
    return Path(url.removeprefix("sqlite:///"))


def _table_count(url: str, table: str) -> int:
    path = _path(url)
    if not path.exists():
        return 0
    with closing(sqlite3.connect(path)) as connection:
        try:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            return 0


def _freeze(url: str) -> str:
    """Freeze the built-in reference pair and return its id."""
    lines: list[str] = []
    exit_code = main(["--freeze-reference"], env={"DATABASE_URL": url}, emit=lines.append)
    assert exit_code == EXIT_OK, lines
    return lines[0]


# -- Freeze then run: exit 0, one row, within tolerance -----------------------


def test_freeze_then_run_gives_exit_0_one_row_and_within_tolerance_true(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    env = {"DATABASE_URL": url}

    reference_id = _freeze(url)
    assert uuid.UUID(reference_id)  # the printed line is the bare id, nothing else

    run_lines: list[str] = []
    exit_code = main([], env=env, emit=run_lines.append)

    assert exit_code == EXIT_OK
    assert len(run_lines) == 1
    payload = json.loads(run_lines[0])
    assert payload["reference_id"] == reference_id
    assert payload["within_tolerance"] is True
    assert payload["deviation"] == 0.0
    assert payload["score"] == payload["recorded_score"]
    assert set(payload) == {
        "reference_id",
        "score",
        "recorded_score",
        "deviation",
        "within_tolerance",
        "evaluation_canary",
        "ran_at",
    }
    assert payload["evaluation_canary"] is False  # no evaluation canary frozen

    assert _table_count(url, RUN_TABLE) == 1

    newest = CanaryRunStore(url).newest()
    assert newest is not None
    assert newest.reference_id == reference_id
    assert newest.within_tolerance is True
    assert newest.score == payload["score"]
    assert newest.evaluation_canary is False


# -- A second freeze is refused, changing nothing ------------------------------


def test_a_second_freeze_is_refused(tmp_path: Path) -> None:
    url = _url(tmp_path)
    env = {"DATABASE_URL": url}
    first_id = _freeze(url)

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--freeze-reference"], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert CANARY_REFERENCE_EXISTS in message
    assert first_id in message
    assert "Traceback" not in message

    # Nothing changed: exactly one active reference pair is still on record.
    with closing(sqlite3.connect(_path(url))) as connection:
        active = connection.execute(
            f"SELECT reference_id FROM {REFERENCE_TABLE} WHERE is_active = 1"
        ).fetchall()
    assert [row[0] for row in active] == [first_id]


# -- A tampered recorded_score breaks the canary: exit 3, halt row, run row ---


def test_a_tampered_recorded_score_gives_exit_3_a_halt_row_and_a_run_row(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    env = {"DATABASE_URL": url}
    reference_id = _freeze(url)

    # Tamper the pair's own recorded constant, directly -- the "the world
    # moved" case, well past the 1e-12 band.
    with closing(sqlite3.connect(_path(url))) as connection, connection:
        connection.execute(
            f"UPDATE {REFERENCE_TABLE} SET recorded_score = recorded_score + 0.5 "
            "WHERE reference_id = ?",
            (reference_id,),
        )

    run_lines: list[str] = []
    exit_code = main([], env=env, emit=run_lines.append)

    assert exit_code == EXIT_BROKEN
    payload = json.loads(run_lines[0])
    assert payload["reference_id"] == reference_id
    assert payload["within_tolerance"] is False
    assert payload["deviation"] == pytest.approx(0.5)

    assert _table_count(url, RUN_TABLE) == 1
    assert _table_count(url, "canary_dream_halt") == 1

    from canary import CanaryHaltStore

    assert CanaryHaltStore(url).halted() is True

    newest = CanaryRunStore(url).newest()
    assert newest is not None
    assert newest.within_tolerance is False


# -- An empty store: canary_reference_absent -----------------------------------


def test_an_empty_store_gives_canary_reference_absent(tmp_path: Path) -> None:
    url = _url(tmp_path)
    env = {"DATABASE_URL": url}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main([], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert CANARY_REFERENCE_ABSENT in message
    assert "Traceback" not in message
    assert _table_count(url, RUN_TABLE) == 0


# -- More than one active reference: canary_reference_ambiguous ---------------


def test_more_than_one_active_reference_gives_canary_reference_ambiguous(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    env = {"DATABASE_URL": url}
    first_id = _freeze(url)
    second_id = str(uuid.uuid4())

    # A second active row, inserted directly -- the invariant this module
    # enforces (never the store) having been violated by something else.
    with closing(sqlite3.connect(_path(url))) as connection, connection:
        connection.execute(
            f"INSERT INTO {REFERENCE_TABLE} "
            "(reference_id, recorded_score, is_active, created_at) "
            "VALUES (?, ?, 1, ?)",
            (second_id, 0.5, datetime.now(timezone.utc).isoformat()),
        )

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main([], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert CANARY_REFERENCE_AMBIGUOUS in message
    assert first_id in message
    assert second_id in message
    assert "Traceback" not in message
    assert _table_count(url, RUN_TABLE) == 0


# -- No DATABASE_URL: exit 2, one line, naming it ------------------------------


def test_missing_database_url_exits_2_naming_it() -> None:
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main([], env={}, emit=lambda _line: None)

    assert exit_code == EXIT_CONFIG
    message = stderr.getvalue()
    assert DATABASE_URL_ENV in message
    assert "Traceback" not in message
    assert message.count("\n") == 1


# -- newest() returns the latest row, not the last inserted -------------------


def test_newest_returns_the_latest_row(tmp_path: Path) -> None:
    url = _url(tmp_path)
    store = CanaryRunStore(url)
    reference_id = str(uuid.uuid4())

    older = store.record(
        reference_id,
        score=0.5,
        recorded_score=0.5,
        deviation=0.0,
        tolerance=1e-12,
        within_tolerance=True,
        ran_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    newer = store.record(
        reference_id,
        score=0.9,
        recorded_score=0.9,
        deviation=0.0,
        tolerance=1e-12,
        within_tolerance=True,
        ran_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )

    newest = store.newest()
    assert newest is not None
    assert newest.id == newer.id
    assert newest.id != older.id
    assert newest.ran_at == newer.ran_at


def test_newest_is_none_for_a_store_that_has_never_run(tmp_path: Path) -> None:
    store = CanaryRunStore(_url(tmp_path))
    assert store.newest() is None


# -- newest_passing() skips a broken row, even the newest one ------------------


def test_newest_passing_skips_a_broken_newest_row(tmp_path: Path) -> None:
    # require_dreaming_allowed's own question is "the newest *passing* run",
    # not merely the newest row -- a run recorded broken must not read as
    # recent, complete evidence just because nothing else happened to halt
    # on it.
    url = _url(tmp_path)
    store = CanaryRunStore(url)
    reference_id = str(uuid.uuid4())

    passing = store.record(
        reference_id,
        score=0.5,
        recorded_score=0.5,
        deviation=0.0,
        tolerance=1e-12,
        within_tolerance=True,
        evaluation_canary=True,
        ran_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    store.record(
        reference_id,
        score=0.9,
        recorded_score=0.1,
        deviation=0.8,
        tolerance=1e-12,
        within_tolerance=False,
        evaluation_canary=True,
        ran_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )

    newest = store.newest()
    assert newest is not None
    assert newest.within_tolerance is False  # the broken row is the newest

    newest_passing = store.newest_passing()
    assert newest_passing is not None
    assert newest_passing.id == passing.id
    assert newest_passing.within_tolerance is True


def test_newest_passing_is_none_when_every_row_is_broken_or_absent(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    store = CanaryRunStore(url)
    assert store.newest_passing() is None

    store.record(
        str(uuid.uuid4()),
        score=0.9,
        recorded_score=0.1,
        deviation=0.8,
        tolerance=1e-12,
        within_tolerance=False,
        evaluation_canary=True,
    )
    assert store.newest_passing() is None


# -- Registered as the "canary-run-store" component ---------------------------


def test_the_store_is_registered_as_canary_run_store_and_none_without_a_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The composition contract the feature sentence states directly:
    # exported from canary and registered as "canary-run-store", composing
    # None (degrade, don't break) without a DATABASE_URL -- while the rest
    # of the workspace still composes.
    from app.module_loader import create_app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    assert app.get("canary-run-store") is None
    assert len(app.order) > 5

    url = _url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    app2 = create_app()
    store = app2.get("canary-run-store")
    assert store is not None
    assert store.database_url == url
    # Construction resolves nothing: composing the store must not touch the
    # disk, the contract every store in this package states.
    assert not _path(url).exists()

    # A fresh composition reaches an equivalent store, pointed at the same
    # database.
    app3 = create_app()
    store2 = app3.get("canary-run-store")
    assert store2.database_url == store.database_url


# -- The evaluation canary: a second comparison, through an injected evaluator -


def _stub_evaluators(
    node_score: float = 0.42, replay_score: float = 0.77
) -> tuple[Callable[[str, str], float], Callable[[str], float]]:
    """A node evaluator and a tree-replay evaluator, each a constant function.

    Stands in for the real sandbox and evaluation config a campaign uses --
    this suite never starts one. Each returns whatever score the test is
    about, so a freeze records it as the constant and a later replay with a
    different stub reproduces a mismatch on demand.
    """

    def evaluate_node(campaign_id: str, node_id: str) -> float:
        return node_score

    def replay_policy(campaign_id: str) -> float:
        return replay_score

    return evaluate_node, replay_policy


def _evaluation_env(url: str) -> dict[str, str]:
    return {
        "DATABASE_URL": url,
        EVALUATION_CAMPAIGN_ID_ENV: "campaign-1",
        EVALUATION_NODE_ID_ENV: "node-1",
    }


def test_the_evaluation_canary_is_frozen_and_replays_as_a_full_pass(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    env = _evaluation_env(url)
    evaluate_node, replay_policy = _stub_evaluators()

    freeze_lines: list[str] = []
    exit_code = main(
        ["--freeze-reference"],
        env=env,
        emit=freeze_lines.append,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
    )
    assert exit_code == EXIT_OK, freeze_lines
    assert _table_count(url, EVALUATION_REFERENCE_TABLE) == 1

    run_lines: list[str] = []
    exit_code = main(
        [],
        env=env,
        emit=run_lines.append,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
    )

    assert exit_code == EXIT_OK
    payload = json.loads(run_lines[0])
    assert payload["within_tolerance"] is True
    assert payload["evaluation_canary"] is True

    newest = CanaryRunStore(url).newest()
    assert newest is not None
    assert newest.evaluation_canary is True

    from canary import CanaryHaltStore

    assert CanaryHaltStore(url).halted() is False


def test_refreezing_an_already_frozen_evaluation_reference_is_refused(
    tmp_path: Path,
) -> None:
    # Unchanged refusal: an evaluation reference already on record is named
    # with its own code word on both deployment shapes -- a fresh store that
    # froze both, and one that froze the toy pair first.
    for freeze_toy_first in (False, True):
        url = _url(tmp_path, f"double-{freeze_toy_first}.db")
        if freeze_toy_first:
            _freeze(url)
        evaluate_node, replay_policy = _stub_evaluators()
        exit_code = main(
            ["--freeze-reference"],
            env=_evaluation_env(url),
            emit=lambda _line: None,
            evaluate_node=evaluate_node,
            replay_policy=replay_policy,
        )
        assert exit_code == EXIT_OK

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(
                ["--freeze-reference"],
                env=_evaluation_env(url),
                emit=lambda _line: None,
                evaluate_node=evaluate_node,
                replay_policy=replay_policy,
            )
        assert exit_code == EXIT_REFUSED
        message = stderr.getvalue()
        assert CANARY_EVALUATION_REFERENCE_EXISTS in message
        assert "Traceback" not in message
        assert _table_count(url, EVALUATION_REFERENCE_TABLE) == 1


def test_the_evaluation_canary_freezes_on_a_deployment_that_already_froze_the_toy_pair(
    tmp_path: Path,
) -> None:
    # The reported defect: a deployment that froze the toy pair before the
    # evaluation canary existed could never freeze it afterwards --
    # `_freeze_reference` refused with canary_reference_exists before it
    # ever reached the evaluation freeze, so every later run recorded
    # evaluation_canary=0 and dreaming was refused forever.
    url = _url(tmp_path)
    toy_reference_id = _freeze(url)
    evaluate_node, replay_policy = _stub_evaluators()

    freeze_lines: list[str] = []
    exit_code = main(
        ["--freeze-reference"],
        env=_evaluation_env(url),
        emit=freeze_lines.append,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
    )

    assert exit_code == EXIT_OK, freeze_lines
    # The existing toy reference id is what gets printed -- the toy pair was
    # not re-frozen, and a second pair was not added.
    assert freeze_lines == [toy_reference_id]
    with closing(sqlite3.connect(_path(url))) as connection:
        active = connection.execute(
            f"SELECT reference_id FROM {REFERENCE_TABLE} WHERE is_active = 1"
        ).fetchall()
    assert [row[0] for row in active] == [toy_reference_id]
    assert _table_count(url, EVALUATION_REFERENCE_TABLE) == 1

    # And a plain run on such a deployment now records a full pass.
    run_lines: list[str] = []
    exit_code = main(
        [],
        env=_evaluation_env(url),
        emit=run_lines.append,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
    )
    assert exit_code == EXIT_OK, run_lines
    assert json.loads(run_lines[0])["evaluation_canary"] is True


def test_a_freeze_refuses_a_non_finite_evaluation_score(
    tmp_path: Path,
) -> None:
    # A policy that commits nothing replays to -inf, and |(-inf) - (-inf)| is
    # NaN -- which would make every later night a recorded break for a reason
    # that has nothing to do with determinism. Refused, naming the half and
    # the value, with nothing written.
    url = _url(tmp_path)
    for half, node_score, replay_score in (
        ("node", float("-inf"), 0.77),
        ("replay", 0.42, float("-inf")),
        ("node", float("nan"), 0.77),
    ):
        bad_evaluate_node, bad_replay_policy = _stub_evaluators(
            node_score=node_score, replay_score=replay_score
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(
                ["--freeze-reference"],
                env=_evaluation_env(url),
                emit=lambda _line: None,
                evaluate_node=bad_evaluate_node,
                replay_policy=bad_replay_policy,
            )

        assert exit_code == EXIT_REFUSED
        message = stderr.getvalue()
        assert CANARY_EVALUATION_SCORE_NOT_FINITE in message
        assert half in message
        assert "Traceback" not in message
        # Nothing was written: neither the toy pair nor the evaluation
        # reference -- a retry with a finite evaluator can still freeze both.
        assert _table_count(url, REFERENCE_TABLE) == 0
        assert _table_count(url, EVALUATION_REFERENCE_TABLE) == 0


def test_the_evaluation_config_sha256_is_stored_and_a_mismatch_is_refused(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    env = _evaluation_env(url)
    evaluate_node, replay_policy = _stub_evaluators()

    exit_code = main(
        ["--freeze-reference"],
        env=env,
        emit=lambda _line: None,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
        evaluation_config_sha256="sha-a",
    )
    assert exit_code == EXIT_OK

    # A run under the same config replays normally.
    run_lines: list[str] = []
    exit_code = main(
        [],
        env=env,
        emit=run_lines.append,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
        evaluation_config_sha256="sha-a",
    )
    assert exit_code == EXIT_OK
    assert json.loads(run_lines[0])["evaluation_canary"] is True

    # A run under a different config refuses, before writing a run row.
    for mismatched in ("sha-b", None):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(
                [],
                env=env,
                emit=lambda _line: None,
                evaluate_node=evaluate_node,
                replay_policy=replay_policy,
                evaluation_config_sha256=mismatched,
            )
        assert exit_code == EXIT_REFUSED
        message = stderr.getvalue()
        assert CANARY_EVALUATION_CONFIG_MISMATCH in message
        assert "Traceback" not in message
    assert _table_count(url, RUN_TABLE) == 1  # only the matching run's row


def test_a_stored_null_config_sha256_accepts_any_value(tmp_path: Path) -> None:
    # A reference frozen before this seam existed stores NULL and must keep
    # working: it refuses no run, whatever the caller supplies.
    url = _url(tmp_path)
    env = _evaluation_env(url)
    evaluate_node, replay_policy = _stub_evaluators()
    exit_code = main(
        ["--freeze-reference"],
        env=env,
        emit=lambda _line: None,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
        evaluation_config_sha256="sha-a",
    )
    assert exit_code == EXIT_OK
    with closing(sqlite3.connect(_path(url))) as connection, connection:
        connection.execute(
            f"UPDATE {EVALUATION_REFERENCE_TABLE} SET config_sha256 = NULL"
        )

    run_lines: list[str] = []
    exit_code = main(
        [],
        env=env,
        emit=run_lines.append,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
        evaluation_config_sha256="anything-at-all",
    )
    assert exit_code == EXIT_OK, run_lines
    assert json.loads(run_lines[0])["evaluation_canary"] is True


def test_a_pre_existing_evaluation_reference_table_gains_the_config_column(
    tmp_path: Path,
) -> None:
    # A table created before `config_sha256` existed must be upgraded in
    # place by the freeze/read path, not left for the INSERT to fail on.
    url = _url(tmp_path)
    path = _path(url)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            f"CREATE TABLE {EVALUATION_REFERENCE_TABLE} ("
            "id TEXT NOT NULL PRIMARY KEY, campaign_id TEXT NOT NULL, "
            "node_id TEXT NOT NULL, node_score REAL NOT NULL, "
            "replay_score REAL NOT NULL, created_at TEXT NOT NULL);"
        )

    env = _evaluation_env(url)
    evaluate_node, replay_policy = _stub_evaluators()
    exit_code = main(
        ["--freeze-reference"],
        env=env,
        emit=lambda _line: None,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
        evaluation_config_sha256="sha-a",
    )
    assert exit_code == EXIT_OK

    with closing(sqlite3.connect(path)) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({EVALUATION_REFERENCE_TABLE})"
            )
        }
        stored = connection.execute(
            f"SELECT config_sha256 FROM {EVALUATION_REFERENCE_TABLE}"
        ).fetchone()[0]
    assert "config_sha256" in columns
    assert stored == "sha-a"

    # And a plain run reads the upgraded column rather than raising.
    run_lines: list[str] = []
    exit_code = main(
        [],
        env=env,
        emit=run_lines.append,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
        evaluation_config_sha256="sha-a",
    )
    assert exit_code == EXIT_OK, run_lines


def test_freezing_the_evaluation_canary_without_an_evaluator_is_refused(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    env = _evaluation_env(url)

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--freeze-reference"], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert EVALUATION_CAMPAIGN_ID_ENV in message
    assert "Traceback" not in message
    # Nothing was changed: neither reference was frozen, so a retry with
    # both evaluators wired can still freeze the toy pair too.
    assert _table_count(url, REFERENCE_TABLE) == 0
    assert _table_count(url, EVALUATION_REFERENCE_TABLE) == 0


def test_replaying_a_frozen_evaluation_canary_without_an_evaluator_is_refused(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    env = _evaluation_env(url)
    evaluate_node, replay_policy = _stub_evaluators()
    exit_code = main(
        ["--freeze-reference"],
        env=env,
        emit=lambda _line: None,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
    )
    assert exit_code == EXIT_OK

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main([], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert "no evaluator" in message
    assert "Traceback" not in message
    # The run was refused before anything was recorded: a toy-only pass must
    # never be silently recorded in place of a configured evaluation canary.
    assert _table_count(url, RUN_TABLE) == 0


def test_an_evaluation_canary_mismatch_halts_dreaming(tmp_path: Path) -> None:
    url = _url(tmp_path)
    env = _evaluation_env(url)
    freeze_evaluate_node, freeze_replay_policy = _stub_evaluators(
        node_score=0.42, replay_score=0.77
    )
    exit_code = main(
        ["--freeze-reference"],
        env=env,
        emit=lambda _line: None,
        evaluate_node=freeze_evaluate_node,
        replay_policy=freeze_replay_policy,
    )
    assert exit_code == EXIT_OK

    # The world moved: the node now re-evaluates to a different score than
    # the one frozen as its constant -- well past the 1e-12 band. The
    # replay side still matches, so only the node sub-check breaks.
    mismatched_evaluate_node, matching_replay_policy = _stub_evaluators(
        node_score=0.42 + 0.5, replay_score=0.77
    )

    run_lines: list[str] = []
    exit_code = main(
        [],
        env=env,
        emit=run_lines.append,
        evaluate_node=mismatched_evaluate_node,
        replay_policy=matching_replay_policy,
    )

    assert exit_code == EXIT_BROKEN
    payload = json.loads(run_lines[0])
    assert payload["within_tolerance"] is True  # the toy canary still holds
    assert payload["evaluation_canary"] is True

    assert _table_count(url, "canary_dream_halt") == 1

    from canary import CanaryHaltStore

    assert CanaryHaltStore(url).halted() is True

    newest = CanaryRunStore(url).newest()
    assert newest is not None
    assert newest.evaluation_canary is True


# -- No runpy RuntimeWarning: a subprocess, not an in-process call ------------


def test_module_run_prints_nothing_to_stderr(tmp_path: Path) -> None:
    # Regression: ``canary/__init__.py`` used to import ``canary.run`` eagerly,
    # which left "canary.run" in ``sys.modules`` by the time runpy imported it
    # to execute as ``__main__`` -- the exact condition runpy's own
    # RuntimeWarning fires under. Only a real subprocess invocation (as the
    # systemd timer and an operator actually run this command) reproduces it;
    # an in-process call to ``canary.run.main`` never goes through runpy.
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "canary.run", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
