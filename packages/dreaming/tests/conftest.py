"""Fixtures for the dreaming member's own suite.

This suite lives inside the workspace member (``packages/dreaming/tests``)
rather than under the repository-level ``tests/`` tree, because the member —
including its tests — is this feature's file-claim scope, and the placement is
the one the bootstrap, artifacts, canary and tripwires members take for the
same reason: same-basename files collide under one pytest run, so each member's
suite is collected under its own conftest.

**Everything here is a database, and that is a fact about the feature rather
than an omission.**  Feature 270 is not a computation — it is a *state*: the
pool is held or it is not, and a writer is refused or it is not.  So the
fixtures below are the vocabulary the tests are written in: a SQLite file only
this test can see, a *pool* standing in it, and the freeze over that pool, each
asked for by name.

**The pool is stood up, the freeze is not.**  ``pool`` runs
:func:`dreaming.pool_bootstrap_schema`'s stand-in DDL — the *pool's* two
tables, restated from ``0109`` and from features 188/191 — while ``freeze``
only *constructs* the store.  That split is the member's own restraint held in
the suite: the member never creates the pool's tables (a member that authored
the pool's schema would be legislating a schema three features short of it, the
stance :mod:`tripwires.excise` states for its own ``0109`` bootstrap), so a
fixture that had the member create them would be testing a behaviour the member
deliberately does not have.  What the freeze *does* create — ``pool_freeze``
and the guards — it creates lazily, on the first hold, which is where
:meth:`~dreaming.cycle.CycleFreeze.ensure_schema` runs.

The isolation is the repository-level conftest's pattern, restated here because
that conftest genuinely does not reach this directory: ``tmp_path`` for the
file, so two tests never share a database and no test can write into a
deployment's real store.  Deliberately **not** autouse, and deliberately not
exported into the environment: a test of the *schema text* or of a
*validation refusal* must not acquire a database by accident, and the tests
that want one ask for these fixtures by name.

The path bootstrap puts both import roots on ``sys.path`` regardless of how
pytest was invoked — the workspace's ``src/`` (for ``app.module_loader``, which
the member's package imports to fire its ``@register``) and this member's
``src/`` (for ``dreaming`` itself) — the same bootstrap every member suite in
this workspace performs, so the suite is identical under ``uv run pytest``
(where the venv also provides both) and under a bare ``pytest``.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

# conftest.py -> packages/dreaming/tests -> packages/dreaming -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"
PACKAGE_SRC = REPO_ROOT / "packages" / "dreaming" / "src"

for _root in (APP_SRC, PACKAGE_SRC):
    _root_str = str(_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

from dreaming import (
    REPLAY_SCORE_TABLE,
    WORLD_TABLE,
    CycleFreeze,
    pool_bootstrap_schema,
)


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a database only this test can see.

    The repository-level conftest points ``DATABASE_URL`` at a per-test SQLite
    file for every suite under ``tests/``; this suite is not under ``tests/``,
    so the isolation is restated rather than inherited — the same fixture the
    tripwires and bootstrap member suites spell for their own stores.
    Deliberately **not** autouse and deliberately not exported into the
    environment: a test of a refusal that happens before anything is read must
    not acquire a database by accident.
    """
    return f"sqlite:///{tmp_path / 'dreaming-cycle-test.db'}"


@pytest.fixture
def pool(database_url: str) -> str:
    """A database with the replay pool's two tables in it, and nothing else.

    Returns the URL rather than a store, because there is no store to return:
    the pool belongs to the replay member and to features 188/191, and this
    member reads it through nothing but its own commitment query.  What the
    fixture hands back is the *precondition* every hold needs — two tables with
    the pool's names in them — and the tests then hold, write and verify
    against it with no intermediary, which is exactly the shape of the
    behaviour under test.

    The DDL is this member's own restatement
    (:func:`dreaming.pool_bootstrap_schema`), not a hand-written
    ``CREATE TABLE`` in the fixture and not a run of the shared migration
    chain: the stand-in exists so the suite does not drag in a sibling member's
    package or a migration stack to have a pool to hold, and using the
    restatement here is what keeps that text *exercised* rather than merely
    present.  A ``replay_score`` and a ``bootstrap_world``, empty, in
    :data:`~dreaming.POOL_TABLES` order.
    """
    from dreaming import sqlite_path

    with closing(sqlite3.connect(sqlite_path(database_url))) as connection, connection:
        connection.executescript(pool_bootstrap_schema())
    return database_url


@pytest.fixture
def scores(pool: str) -> tuple[str, tuple[str, ...]]:
    """A pool with three worlds and six scores, and the ids it holds.

    The smallest pool that can say anything about membership: three worlds so
    an inserted or deleted row is a *change* rather than an emptiness, and two
    scores per world so a change to one world's rows is distinguishable from a
    change to the pool's set of worlds.  Returns the ids it wrote, in the order
    the commitment orders them, so a test comparing commitments writes what it
    means rather than a literal nobody can check.

    The rows are written the way the owners declare them — ``0109``'s eight
    columns for ``replay_score``, features 188/191's for ``bootstrap_world`` —
    which is the same discipline the tripwires member's own pool fixture
    states: a fixture that wrote a *narrower* row would make every read pass
    for the wrong reason, and the pool's shape is exactly what this member's
    restatement is here to keep honest.
    """
    from dreaming import sqlite_path

    world_ids = ("world-aaa", "world-bbb", "world-ccc")
    score_ids = []
    with closing(sqlite3.connect(sqlite_path(pool))) as connection, connection:
        for index, world_id in enumerate(world_ids):
            connection.execute(
                f"INSERT INTO {WORLD_TABLE} (world_id, seed, label, provenance, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (world_id, index, f"label-{index}", None, "2026-01-01T00:00:00Z"),
            )
        for index, world_id in enumerate(world_ids):
            for beta in (0.0, 1.0):
                score_id = f"score-{world_id}-{beta}"
                score_ids.append(score_id)
                connection.execute(
                    f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                    "world_id, beta, score, committed_pick, is_holdout, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        score_id,
                        "pi-0",
                        world_id,
                        beta,
                        index + beta,
                        None,
                        "0",
                        "2026-01-01T00:00:00Z",
                    ),
                )
    return pool, tuple(score_ids)


@pytest.fixture
def freeze(scores: tuple[str, tuple[str, ...]]) -> CycleFreeze:
    """The cycle freeze over this test's pool, with nothing held yet.

    Derived from the ``scores`` fixture rather than from ``pool`` so a test
    that asks for the freeze gets a pool with something *in* it — the
    commitment a hold records is a digest over membership, and a hold over an
    empty pool would commit to the empty digest, which no test could tell from
    a commitment that had failed to read anything at all.  A test that wants
    the empty pool asks for ``pool`` and builds its own freeze.
    """
    return CycleFreeze(scores[0])


#: The two pool tables, re-exported so a test can spell them without importing
#: the member's ``layout`` module directly — the fixtures are the vocabulary,
#: and a test that reached past them for a name would be reading the
#: implementation rather than stating a claim about the pool.
POOL_TABLE_NAMES = (REPLAY_SCORE_TABLE, WORLD_TABLE)
