"""Feature 3, the bootstrap pool's fill CLI -- ``python -m bootstrap.fill``.

``additions_spec_operator_surfaces.xml``, "Middle Loop Operation" category,
feature 3: *System saves bootstrap worlds to the pool from* ``python -m
bootstrap.fill --count N --pool-seed S`` *(defaults 45 and 20260922), and
displays the pool's census as one JSON line.*  This suite drives
:func:`bootstrap.fill.main` directly over a throwaway SQLite database --
never a real subprocess.

Most tests run against a database this command has never done anything to
but ``ensure_schema()`` -- the one schema step the feature's own sentence
names, and the real shape of "an empty store" for a command whose only
documented preparation is that one call.  A handful of tests that are
specifically about the *financial* half of the census additionally migrate
``0109``'s ``replay_score`` table, the way ``test_closeout_cli.py``
migrates its own fixtures, to prove the command reads real figures once a
deployment's other members have put something there.

One test per claim the feature sentence makes:

* **a fill persists worlds and prints the census** -- ``n_bootstrap``
  matches ``--count``, ``pool_seed`` echoes ``--pool-seed``, and the rows
  are really in the database.
* **re-running with the same arguments writes nothing new** -- the second
  run's printed line equals the first's, the row count is unchanged, and
  every world's ``created_at`` is unchanged too.
* **a different ``pool_seed`` refuses with the code word, writing
  nothing** -- the held worlds and their count are exactly what the first
  run left.
* **``--census`` on an empty store prints zeros** -- a database this
  command has only ever run ``ensure_schema()`` against, with no
  ``replay_score`` table and no bootstrap worlds persisted yet.
* **a count outside [40, 50] refuses with exit 1**, printing
  :class:`~bootstrap.BootstrapPoolError`'s own text, and persists nothing.
* **a missing ``DATABASE_URL`` exits 2**, naming it.

Beside those sit two narrower checks on the census read itself: that a
*migrated, empty* ``replay_score`` table also reports zero (the other
"empty store" a deployment can be in), and that a migrated table carrying
a real score is actually counted -- so the zero above is proven to be a
measurement of an untouched database, not a bug that always prints zero.

No test opens a network connection or holds state at module scope, and
every test points at its own ``tmp_path`` database, so the suite passes
under pytest-xdist.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
from contextlib import closing, redirect_stderr
from pathlib import Path
from types import ModuleType

import bootstrap
import pytest
from bootstrap.fill import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REFUSED,
    FILL_CODE,
    POPULATED_CODE,
    main,
)

# This file sits beside conftest.py (packages/bootstrap/tests), so the
# repository root is the same three parents up that conftest.py resolves.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
REPLAY_SCORE_MIGRATION = "0109_replay_score_and_policy_revision"


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_bootstrap_fill_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway, entirely untouched database.

    No migration has run against it and no file exists yet -- the state a
    freshly named ``DATABASE_URL`` is in before an operator has done
    anything but point this command at it.  This is deliberately *not*
    pre-migrated for ``replay_score``: this command's own documented
    schema step is ``BootstrapPool.ensure_schema()`` alone, and the most
    literal "empty store" its census must answer zero against is a
    database with no table of either member's in it at all.
    """
    return f"sqlite:///{tmp_path / 'bootstrap-fill-test.db'}"


def _migrate_replay_score(database_url: str) -> None:
    """Bring ``database_url`` to the shape ``0109`` migrates it to.

    Used only by the tests that are specifically about the financial
    figure -- every other test in this suite deliberately runs against a
    database this migration has never touched, which is this command's
    own "empty store".
    """
    _load_migration(REPLAY_SCORE_MIGRATION).apply(database_url)


def _path_of(database_url: str) -> str:
    return database_url.removeprefix("sqlite:///")


def _seed_score(database_url: str, *, world_id: str) -> None:
    """Write one ``replay_score`` row directly, the way a replay would."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO replay_score (id, policy_version, world_id, beta, "
            "score, committed_pick, is_holdout, created_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"score-{world_id}",
                "policy-v1",
                world_id,
                1.0,
                0.5,
                None,
                False,
                "2026-09-22T00:00:00Z",
            ),
        )


# -- Filling --------------------------------------------------------------------


def test_fill_persists_worlds_and_prints_the_census(database_url: str) -> None:
    lines: list[str] = []

    exit_code = main(
        ["--count", "40", "--pool-seed", "777"],
        env={"DATABASE_URL": database_url},
        emit=lines.append,
    )

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload == {
        "n_bootstrap": 40,
        "n_financial": 0,
        "total": 40,
        "pool_seed": 777,
    }

    pool = bootstrap.BootstrapPool(database_url)
    assert pool.world_count() == 40
    worlds = pool.worlds()
    assert len(worlds) == 40
    assert {record.pool_seed for record in worlds} == {777}


def test_defaults_are_45_and_20260922(database_url: str) -> None:
    lines: list[str] = []

    exit_code = main([], env={"DATABASE_URL": database_url}, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["n_bootstrap"] == bootstrap.DEFAULT_POOL_SIZE == 45
    assert payload["pool_seed"] == bootstrap.POOL_SEED == 20260922


# -- Idempotent re-run ------------------------------------------------------------


def test_rerunning_with_the_same_arguments_writes_nothing_new(
    database_url: str,
) -> None:
    argv = ["--count", "42", "--pool-seed", "555"]
    first: list[str] = []
    second: list[str] = []

    first_exit = main(argv, env={"DATABASE_URL": database_url}, emit=first.append)
    before = bootstrap.BootstrapPool(database_url).worlds()
    second_exit = main(argv, env={"DATABASE_URL": database_url}, emit=second.append)
    after = bootstrap.BootstrapPool(database_url).worlds()

    assert first_exit == second_exit == EXIT_OK
    assert first == second
    assert len(before) == len(after) == 42
    # created_at is kept on a refresh -- the re-run reauthors no row.
    assert [record.created_at for record in before] == [
        record.created_at for record in after
    ]


# -- The different-seed refusal ---------------------------------------------------


def test_a_different_pool_seed_refuses_with_the_code_word_and_writes_nothing(
    database_url: str,
) -> None:
    first_exit = main(
        ["--pool-seed", "111"], env={"DATABASE_URL": database_url}, emit=lambda _l: None
    )
    assert first_exit == EXIT_OK

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        second_exit = main(
            ["--pool-seed", "222"],
            env={"DATABASE_URL": database_url},
            emit=lambda _line: None,
        )

    assert second_exit == EXIT_REFUSED
    message = stderr.getvalue()
    assert POPULATED_CODE in message
    assert "111" in message
    assert "222" in message
    assert "Traceback" not in message

    pool = bootstrap.BootstrapPool(database_url)
    worlds = pool.worlds()
    assert len(worlds) == bootstrap.DEFAULT_POOL_SIZE
    assert {record.pool_seed for record in worlds} == {111}


def test_rerunning_with_the_same_pool_seed_is_not_a_conflict(
    database_url: str,
) -> None:
    # The refusal is about *disagreement*, not about a pool that already
    # holds worlds -- naming the same seed twice is the idempotent refresh,
    # never the populated refusal.
    first_exit = main(
        ["--pool-seed", "333"], env={"DATABASE_URL": database_url}, emit=lambda _l: None
    )
    second_exit = main(
        ["--pool-seed", "333"], env={"DATABASE_URL": database_url}, emit=lambda _l: None
    )
    assert first_exit == second_exit == EXIT_OK


# -- ``--census`` ------------------------------------------------------------------


def test_census_only_on_an_untouched_store_prints_zeros_and_writes_nothing(
    database_url: str,
) -> None:
    # The literal "empty store": nothing has run against this database
    # except what this very call performs (ensure_schema's own
    # CREATE TABLE IF NOT EXISTS) -- no replay_score table, no bootstrap
    # worlds. The financial figure must still be a measured zero, not a
    # refusal, because this command never promised to migrate anything.
    lines: list[str] = []

    exit_code = main(["--census"], env={"DATABASE_URL": database_url}, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload == {
        "n_bootstrap": 0,
        "n_financial": 0,
        "total": 0,
        "pool_seed": bootstrap.POOL_SEED,
    }
    assert bootstrap.BootstrapPool(database_url).world_count() == 0


def test_census_only_on_a_migrated_but_scoreless_store_also_prints_zeros(
    database_url: str,
) -> None:
    # The other "empty store": a deployment that has run 0109 and simply
    # has not replayed anything yet. Both are zero, and for the same
    # reason -- nothing has happened -- but this is the state feature
    # 186's own world_census reads directly rather than this command's
    # fallback.
    _migrate_replay_score(database_url)
    lines: list[str] = []

    exit_code = main(["--census"], env={"DATABASE_URL": database_url}, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload == {
        "n_bootstrap": 0,
        "n_financial": 0,
        "total": 0,
        "pool_seed": bootstrap.POOL_SEED,
    }


def test_a_real_financial_score_is_actually_counted(database_url: str) -> None:
    # Proof that the zero above is a measurement of an untouched database,
    # not a bug that always prints zero: once replay_score holds a world
    # the bootstrap pool does not, n_financial reports it.
    _migrate_replay_score(database_url)
    _seed_score(database_url, world_id="7c1e6a48-0b93-4d2f-9a51-3e8f0d6b2c74")
    lines: list[str] = []

    exit_code = main(
        ["--count", "40", "--pool-seed", "1"],
        env={"DATABASE_URL": database_url},
        emit=lines.append,
    )

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["n_bootstrap"] == 40
    assert payload["n_financial"] == 1
    assert payload["total"] == 41


def test_census_only_reads_without_persisting_against_a_filled_pool(
    database_url: str,
) -> None:
    main(["--count", "41"], env={"DATABASE_URL": database_url}, emit=lambda _l: None)
    lines: list[str] = []

    exit_code = main(
        ["--census", "--pool-seed", "999"],
        env={"DATABASE_URL": database_url},
        emit=lines.append,
    )

    # A pool_seed that would otherwise conflict is never checked in census
    # mode -- no draw is attempted, so there is nothing to protect.
    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["n_bootstrap"] == 41
    assert payload["pool_seed"] == 999
    assert bootstrap.BootstrapPool(database_url).world_count() == 41


# -- The bad count -----------------------------------------------------------------


def test_a_count_outside_the_band_refuses_with_the_pools_own_text(
    database_url: str,
) -> None:
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            ["--count", "39"], env={"DATABASE_URL": database_url}, emit=lambda _l: None
        )

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    # The member's own BootstrapPoolError text, unwrapped and unprefixed by
    # this module's own code word -- it already names the band and the
    # value it refuses.
    assert "40" in message and "50" in message
    assert "39" in message
    assert FILL_CODE not in message
    assert "Traceback" not in message
    assert bootstrap.BootstrapPool(database_url).world_count() == 0


@pytest.mark.parametrize("bad_count", [39, 51, 0, -1])
def test_every_count_outside_the_band_is_refused(
    database_url: str, bad_count: int
) -> None:
    exit_code = main(
        ["--count", str(bad_count)],
        env={"DATABASE_URL": database_url},
        emit=lambda _l: None,
    )
    assert exit_code == EXIT_REFUSED
    assert bootstrap.BootstrapPool(database_url).world_count() == 0


# -- Missing configuration -----------------------------------------------------------


def test_missing_database_url_exits_2_naming_it() -> None:
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main([], env={}, emit=lambda _l: None)

    assert exit_code == EXIT_CONFIG
    assert "DATABASE_URL" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
