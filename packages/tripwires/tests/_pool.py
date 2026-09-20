"""Replay-pool builders for the tripwires suite — pure functions, no fixtures.

Feature 132 joins two stores: the discovery tree feature 131 marks, and the
``replay_score`` pool ``0109`` creates.  :mod:`_trees` is the first half's
builder; this module is the second's, and it lives beside that one for the same
reason it lives beside :mod:`_panels` — a member suite's ``conftest`` is a
top-level module called ``conftest``, and so is every other member's, so two
member suites cannot be collected together if either imports helpers from it.
Unique names, no shadowing.

**The rows are written the way ``0109`` declares them.**  Eight columns —
``id``, ``policy_version``, ``world_id``, ``beta``, ``score``, ``committed_pick``,
``is_holdout``, ``created_at`` — with ``committed_pick`` nullable, because that
is the shape the migration creates and feature 132's join reads.  A builder that
inserted a *convenient* shape would let the pool's tests pass against a table
the system does not have, which is the one kind of green worse than red.

**The created_at values are caller-controlled and strictly increasing.**  The
pool's read orders by ``(created_at, id)``, and a suite that let the database
stamp ``NOW()`` would be asserting on an order SQLite happened to produce from
identical instants — the exact fragility feature 131's ``subtree_of`` docstring
warns about for minted UUIDs.  Every row this module writes carries an explicit
instant, one second apart in insertion order, so an ordering assertion is a
fixed fact rather than a coincidence.

**``NULL`` picks are written on purpose.**  ``0109`` declares
``committed_pick`` nullable — a candidate scored but not selected has no pick,
and a fabricated nil would read as a real trade — and feature 132's central
claim includes the fact that such a row is *never* excised.  A builder that
always supplied a pick would make that half of the feature untestable, so the
default is a real pick and ``pick=None`` writes the nullable case.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from collections.abc import Iterable, Mapping

__all__ = [
    "Pool",
    "seed_pool",
    "seed_score",
]

#: ``0109``'s eight columns, in the migration's order.  Spelled once so every
#: insert below names the same eight and a column added by a later feature is a
#: visible edit here rather than a silent ``INSERT`` of the wrong arity.
_SCORE_COLUMNS = (
    "id, policy_version, world_id, beta, score, committed_pick, is_holdout, created_at"
)

#: The instant the first seeded row carries.  Fixed rather than "now" so a test
#: asserting on the pool's order is asserting on a written-down value.
_EPOCH = dt.datetime(2024, 6, 3, 9, 0, 0, tzinfo=dt.UTC)


class Pool:
    """A seeded replay pool, and the ids a test needs to talk about it.

    A value, not a fixture-heavy object: it carries the connection it was built
    on (so a test can assert on the raw rows the pool's refusal left alone), the
    row ids in insertion order, and the policy version and world the rows share.
    Held as plain attributes because there is nothing to validate — the ids came
    from :func:`uuid.uuid4` and the table's own key.
    """

    __slots__ = (
        "connection",
        "policy_version",
        "score_ids",
        "world_id",
    )

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        policy_version: str,
        world_id: str,
        score_ids: dict[str, str],
    ) -> None:
        self.connection = connection
        self.policy_version = policy_version
        self.world_id = world_id
        self.score_ids = score_ids

    def ids_for(self, node_id: str) -> tuple[str, ...]:
        """The score-row ids written against ``node_id``, in insertion order.

        A node may carry more than one row — the pool is per ``(policy, world)``
        pair, and §C5 replays one policy across many worlds — so the answer is a
        tuple rather than an id.
        """
        return tuple(
            score_id
            for key, score_id in self.score_ids.items()
            if key.split("|")[0] == node_id
        )

    def row(self, score_id: str) -> tuple:
        """The raw row ``score_id`` names, read straight from the table."""
        return self.connection.execute(
            f"SELECT {_SCORE_COLUMNS} FROM replay_score WHERE id = ?",
            (score_id,),
        ).fetchone()


def seed_pool(
    connection: sqlite3.Connection,
    picks: Mapping[str, int] | Iterable[str | None],
    *,
    policy_version: str = "policy-v1",
    world_id: str | None = None,
    beta: float = 1.0,
) -> Pool:
    """Seed one ``replay_score`` row per pick named, and return the pool.

    ``picks`` is either a mapping of ``{node_id: how many rows that node
    committed to}`` or a plain iterable of node ids (one row each); ``None`` in
    the iterable writes a ``NULL`` pick.  The mapping form exists because the
    interesting case for feature 132 is a branch node that contributed *several*
    scores — §C5 replays a policy across many worlds, so "every score that
    branch contributed" is a set per node and not a row per node — and a builder
    that could only write one row per pick would make the feature's plural
    untestable.

    Every row shares one ``policy_version`` and ``world_id`` by default, which is
    the *easy* case for a join: rows are told apart by their pick alone.  A
    caller can override the world to seed a second world's rows, and ``beta``
    likewise.  ``created_at`` advances one second per row written, so the pool's
    own ``(created_at, id)`` order is the insertion order by construction.
    """
    if isinstance(picks, Mapping):
        expanded: list[str | None] = []
        for node_id, count in picks.items():
            expanded.extend([node_id] * count)
    else:
        expanded = list(picks)

    world = world_id or str(uuid.uuid4())
    rows: list[tuple] = []
    score_ids: dict[str, str] = {}
    for index, pick in enumerate(expanded):
        score_id = str(uuid.uuid4())
        rows.append(
            (
                score_id,
                policy_version,
                world,
                beta,
                float(index),
                pick,
                False,
                (_EPOCH + dt.timedelta(seconds=index)).isoformat(),
            )
        )
        # The key keeps the pick and the index, so `ids_for` can answer for a
        # node that committed to several rows and two rows for one node do not
        # collide in the mapping.
        score_ids[f"{pick}|{index}"] = score_id

    connection.executemany(
        f"INSERT INTO replay_score ({_SCORE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    return Pool(
        connection=connection,
        policy_version=policy_version,
        world_id=world,
        score_ids=score_ids,
    )


def seed_score(
    connection: sqlite3.Connection,
    *,
    pick: str | None,
    policy_version: str = "policy-v1",
    world_id: str | None = None,
    beta: float = 1.0,
    score: float = 0.0,
    is_holdout: bool = False,
    created_at: dt.datetime | None = None,
) -> str:
    """Write one ``replay_score`` row and return its id.

    The single-row spelling, for the tests that are about one row's *contents*
    rather than about the pool's shape — a blank policy version, a
    non-finite score, a hand-written ``created_at`` that cannot be parsed.  Every
    field is a keyword so a test names exactly the one it is bending.
    """
    score_id = str(uuid.uuid4())
    connection.execute(
        f"INSERT INTO replay_score ({_SCORE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            score_id,
            policy_version,
            world_id or str(uuid.uuid4()),
            beta,
            score,
            pick,
            is_holdout,
            (created_at or _EPOCH).isoformat(),
        ),
    )
    connection.commit()
    return score_id
