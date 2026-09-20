"""Excising a poisoned subtree from the replay pool — feature 132.

app_spec.xml, "Leakage Tripwires", feature 132: *"System excises a poisoned
subtree from the replay pool, which rejects every score that branch
contributed."*  docs/alpha-engine-prd.md §C6 states the act in the sentence that
gives it its weight — *"a failure poisons the node **and its entire subtree**,
which is excised from the replay pool"* — and feature 131
(:mod:`tripwires.poison`) wrote the mark this module reads.  Feature 131
answered *what did the failure mark?*; this module answers *so which scores
does the pool still serve?*

**The refusal is a read, and the pool is never deleted from — that is the
module's one design decision and everything below follows from it.**  §C6's
word is "excised", which invites a ``DELETE``, and a ``DELETE`` is wrong four
times over:

* **The pool is the evidence, and §C5's loop is what reads it.**  A
  ``replay_score`` row is *why* a policy revision was selected — ``0109``'s own
  docstring calls it "the *evidence*" and the revision "the *outcome*" — so a
  deletion does not merely refuse a score, it rewrites the reason a past
  selection was made.  A revision already selected would keep its
  ``aggregate_score`` with nothing under it, and "was this branch replayed
  after it was poisoned?" would become unanswerable at exactly the moment an
  operator asks it.
* **Feature 270 forbids exactly that mutation.**  app_spec.xml: *"System
  rejects a replay pool mutation during a dreaming iteration, holding the pool
  fixed for the cycle."*  An excision that deleted rows would be a pool
  mutation, and it would have to reconcile itself with a rule that says the
  pool must not move while a cycle is walking it — a contradiction this design
  does not have, because a read-time refusal moves nothing.
* **Feature 131's row is per-node and irreversible for a reason this feature
  spends.**  :mod:`tripwires.poison` records *which* failure marked *which*
  node and states that nothing ever clears a mark.  A refusal derived from
  those marks is therefore **monotone**: the surviving set can only shrink,
  and never grows back, because no code path exists that un-marks a node.
  That is the whole observable behaviour a deletion would give — "these scores
  are gone and stay gone" — with the evidence still on disk.
* **Idempotence is free, and a deletion's is not.**  Running the refusal again
  is the same read; a ``DELETE`` re-run against a pool that has grown (the
  replay member writes rows; §C5 replays *stored* trees) would have to catch
  rows that arrived after the first excision, and would have to justify why its
  second pass is not the pool mutation feature 270 forbids.

So "excised" means **the pool does not serve them**, and this module is the
thing that says which ones and why.  :meth:`ReplayPool.survivors` is the pool
as §C5's dreaming loop must read it — every row whose committed pick is not
poisoned — and :meth:`ReplayPool.excise` is the per-branch account of one
failure: the branch, the scores it contributed, and the pool that remains.

**The join, and it is one column wide.**  ``replay_score.committed_pick`` is
the policy's decision on the world that row scored — ``0109``'s words, *"the
``committed_pick`` the policy would have made"* — and it holds **a node id**.
That column is the only thing in the pool that points at the discovery tree, so
it is the whole of the join between §C6's two halves: feature 131 marks the
nodes, and a pool row belongs to the branch iff the node it committed to is one
of them.  ``0109`` declares the column nullable and says why (a candidate
scored but not selected has no pick, and a fabricated nil would read as a real
trade), and this module respects that rather than repairing it: a ``NULL`` pick
names **no node**, so it can never match a poisoned one, and a ``NULL``-pick
row is correctly never excised — it contributed no node to the branch.

**The mark is the authority for the refusal; the record supplies the membership
and the attribution.**  A node is excised because ``node.poisoned_at`` is set —
the column feature 131's docstring names as "what the tree walk and the replay
path read", and this *is* the replay path.  The branch's *membership* comes from
the audit table (:meth:`~tripwires.poison.PoisonStore.subtree_of`), for the
reason that method states: the table records the acts, so a branch is the set of
nodes a failure actually marked rather than what a re-walk of a tree grown since
would return today.  And the attribution — *which* failure, and *which*
tripwire — comes from the same table through a ``LEFT`` join, so the report can
name the root that condemned a row.

**The three ``LEFT`` joins and the states they keep legible.**  A row whose pick
the tree does not hold (a stale id, a ``NULL``) is not excised — nothing marked
it — and must stay *visible* in the pool rather than dropping out of both the
survivors and the refused set, which is the one outcome a refusal must not
produce; an inner join would silently lose it.  A marked node with no audit row
beside it is the third state, and it is refused loudly rather than served
quietly: see :func:`_excised`.

**The scope, and the four refusals.**  A branch is read within its campaign
(§9.1, as feature 131 states it), and excising one branch never touches another
campaign's rows — the tests walk a two-campaign database to pin that.  And
because the refusal has two sources of truth about the same node — the mark and
the record — :meth:`ReplayPool.excise` refuses the state where they disagree in
the direction that matters: the record describing a failure for a node whose
mark is absent is **not** an excision, and the call stops rather than reporting
a branch whose scores the pool would go on serving.

**Stdlib only, and import-cheap**, on the same terms as :mod:`tripwires.poison`:
``sqlite3``, ``datetime`` and the member's own modules, no third-party import at
module scope, and no I/O at construction — the path is resolved on first use, so
composing the application never opens a database.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from .errors import TripwireExcisionError, TripwirePoisonError
from .layout import (
    DATABASE_URL_ENV,
    NODE_ID_COLUMN,
    NODE_POISONED_COLUMN,
    NODE_TABLE,
    REPLAY_SCORE_COLUMNS,
    REPLAY_SCORE_COMMITTED_PICK_COLUMN,
    REPLAY_SCORE_CREATED_AT_COLUMN,
    REPLAY_SCORE_ID_COLUMN,
    REPLAY_SCORE_TABLE,
    dialect_of,
    parsed_instant,
    replay_pool_bootstrap_schema,
    sqlite_path,
    validated_node_id,
)
from .poison import POISON_TABLE, PoisonStore

__all__ = [
    "COMPONENT_NAME",
    "ExcisedBranch",
    "ExcisedScore",
    "PoolScore",
    "ReplayPool",
    "excise_subtree",
    "surviving_scores",
]

#: The component name this member registers its replay pool under — a fourth
#: name rather than a fourth component under ``"tripwires"``, the convention
#: :mod:`tripwires.poison` states for its own: this answers *what is the
#: composed replay pool?* while that one answers *what is the composed store a
#: tripwire failure is persisted to?*, and a caller in the replay path asking
#: for the pool must not be handed the thing that writes marks.
COMPONENT_NAME = "tripwires-excise"

#: The score row's columns as the statement below selects them, aliased to the
#: pool's own ``s``.  Built from
#: :data:`~tripwires.layout.REPLAY_SCORE_COLUMNS` rather than re-spelled, so
#: this SELECT and feature 132's bootstrap DDL cannot drift apart on what a
#: score row is made of — the failure a hand-written column list invites.
_SELECT_COLUMNS = ", ".join(f"s.{column}" for column in REPLAY_SCORE_COLUMNS)

#: How many values each row of :data:`_POOL_QUERY` carries: the pool's own
#: eight columns, then the three the two joins add.  Named because
#: :meth:`ReplayPool.entries` and :meth:`ReplayPool._confirm` both index past
#: the eighth, and `row[8]` spelled four times is how an off-by-one becomes
#: "the tripwire fired" instead of "the mark is present".
_ROW_WIDTH = len(REPLAY_SCORE_COLUMNS)

#: The one statement this module runs to answer *what is in the pool, and is
#: the node each row committed to poisoned?*.  Spelled once because the four
#: public reads below are four *filters* of one question — served, refused,
#: one node's contribution, the whole account — and a second spelling of the
#: join is how two of them come to disagree about which rows exist.
#:
#: Not a recursive CTE and not a sub-select, deliberately: the join is
#: ``committed_pick = node.id``, a foreign-key-shaped equality onto a primary
#: key, and there is nothing here for the planner to walk.
_POOL_QUERY = f"""
    SELECT {_SELECT_COLUMNS},
           n.{NODE_POISONED_COLUMN} AS poisoned_at,
           p.root_node_id,
           p.tripwire
    FROM {REPLAY_SCORE_TABLE} AS s
    LEFT JOIN {NODE_TABLE} AS n
        ON n.{NODE_ID_COLUMN} = s.{REPLAY_SCORE_COMMITTED_PICK_COLUMN}
    LEFT JOIN {POISON_TABLE} AS p
        ON p.node_id = s.{REPLAY_SCORE_COMMITTED_PICK_COLUMN}
    ORDER BY s.{REPLAY_SCORE_CREATED_AT_COLUMN}, s.{REPLAY_SCORE_ID_COLUMN}
"""


# -- The values ----------------------------------------------------------------


class PoolScore:
    """One ``replay_score`` row — a pool entry as the pool actually holds it.

    The row, validated: the eight columns ``0109`` declares, each held to what
    its column means rather than to whatever the database handed back.  A value
    rather than a live cursor, because the pool's reader is the *replay path*
    (features 245-255) and a score a policy's selection is aggregated from must
    not be a mutable handle onto a row another writer can move under it.

    Deliberately a different class from :class:`ExcisedScore`.  A surviving row
    and an excised row differ by *why they are being reported* — the one is
    served and the other is refused on the strength of a named failure — and a
    single class carrying an optional ``poisoned_by`` would make "no
    attribution" mean both "served" and "excised by a mark with no record",
    which are opposite answers.  The nested shape keeps them apart: an
    :class:`ExcisedScore` *has* a row, and the row alone never claims to know.
    """

    __slots__ = (
        "_beta",
        "_committed_pick",
        "_created_at",
        "_id",
        "_is_holdout",
        "_policy_version",
        "_score",
        "_world_id",
    )

    def __init__(
        self,
        *,
        id: Any,
        policy_version: str,
        world_id: Any,
        beta: float,
        score: float,
        committed_pick: Any,
        is_holdout: bool,
        created_at: Any,
    ) -> None:
        # ``id`` and ``world_id`` join UUID columns, so both pass through the
        # member's one UUID normalization — the same call feature 131 makes for
        # a campaign id, which is a UUID that is not a node.  A row whose key
        # cannot be spelled canonically is one a report could not name, and one
        # whose world id is mixed-case would read as two worlds.
        object.__setattr__(self, "_id", _pool_node_id(id))
        object.__setattr__(self, "_world_id", _pool_node_id(world_id))
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise TripwireExcisionError(
                f"a replay score must name the policy version it scored, got "
                f"{policy_version!r}; a row with no version cannot be "
                "attributed to a revision, and a revision's aggregate is the "
                "sum of exactly these rows"
            )
        object.__setattr__(self, "_policy_version", policy_version)
        for name, value in (("beta", beta), ("score", score)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwireExcisionError(
                    f"a replay score's {name} must be a number, got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwireExcisionError(
                    f"a replay score's {name} is not finite ({value!r}); a NaN "
                    "or ±inf would reach an aggregate dressed as a measured "
                    "number, and §C5 selects the argmax of these"
                )
        object.__setattr__(self, "_beta", float(beta))
        object.__setattr__(self, "_score", float(score))
        # ``None`` is the migration's own spelling of "no pick was made" and is
        # carried through as ``None`` rather than as a nil UUID: a fabricated
        # key would read as a real trade, which is what 0109's nullable column
        # exists to prevent, and it would also make this row *matchable* by a
        # poisoned node whose id happened to be nil.
        object.__setattr__(
            self,
            "_committed_pick",
            None if committed_pick is None else _pool_node_id(committed_pick),
        )
        # A ``BOOLEAN`` column is SQLite's own type by affinity only: the
        # driver hands back the integer the row holds, so ``0`` and ``1`` are
        # this column's two legitimate spellings and are read as the two bits
        # they are.  Anything *else* is refused, which is the point of checking
        # rather than calling ``bool()``: ``bool(2)`` is ``True``, so a
        # corrupted or hand-written row would silently join the holdout half —
        # the half §7 judges a selection on — with nothing looking wrong.
        if isinstance(is_holdout, bool):
            held = is_holdout
        elif isinstance(is_holdout, int) and is_holdout in (0, 1):
            held = bool(is_holdout)
        else:
            raise TripwireExcisionError(
                f"a replay score's is_holdout must be a bool or the integer "
                f"0/1 a BOOLEAN column holds, got {is_holdout!r} "
                f"({type(is_holdout).__name__}); the holdout half is what §7 "
                "judges a selection on, and a value that is neither is a row "
                "whose half cannot be told"
            )
        object.__setattr__(self, "_is_holdout", held)
        object.__setattr__(self, "_created_at", _pool_instant(created_at))

    @property
    def id(self) -> str:
        """The row's key, canonical UUID text."""
        return self._id

    @property
    def policy_version(self) -> str:
        """The policy revision this run scored — ``policy_revision.policy_version``."""
        return self._policy_version

    @property
    def world_id(self) -> str:
        """The stored world the policy was replayed against."""
        return self._world_id

    @property
    def beta(self) -> float:
        """The budget-penalty coefficient the run was scored at."""
        return self._beta

    @property
    def score(self) -> float:
        """The scalar the run returned — what §C5 aggregates."""
        return self._score

    @property
    def committed_pick(self) -> str | None:
        """The node the policy committed to, or ``None`` when it committed to none.

        **The column feature 132 joins on**, and the only thing in the pool that
        points at the discovery tree.  ``None`` names no node, so such a row is
        never excised: it contributed no node to any branch.
        """
        return self._committed_pick

    @property
    def is_holdout(self) -> bool:
        """Whether this row sits in the 70/30 world holdout §7 judges selection on."""
        return self._is_holdout

    @property
    def created_at(self) -> dt.datetime:
        """When the row was written, UTC."""
        return self._created_at

    def to_payload(self) -> dict[str, Any]:
        """The row as a plain mapping, for a log line or an operator's report."""
        return {
            "id": self._id,
            "policy_version": self._policy_version,
            "world_id": self._world_id,
            "beta": self._beta,
            "score": self._score,
            "committed_pick": self._committed_pick,
            "is_holdout": self._is_holdout,
            "created_at": self._created_at.isoformat(),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PoolScore):
            return NotImplemented
        return all(
            getattr(self, slot) == getattr(other, slot)
            for slot in type(self).__slots__
        )

    def __hash__(self) -> int:
        return hash(tuple(getattr(self, slot) for slot in type(self).__slots__))

    def __repr__(self) -> str:
        return (
            f"PoolScore(policy={self._policy_version!r}, "
            f"world={self._world_id!r}, score={self._score!r}, "
            f"pick={self._committed_pick!r})"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(
            f"{type(self).__name__} is frozen; a pool row a selection was "
            "aggregated from cannot be edited into a different one"
        )


class ExcisedScore:
    """A pool row this feature *refuses*, and the failure that condemned it.

    The pairing is the point: "this score is excised" is only an answer an
    operator can act on beside *which* tripwire failure excised it, so the row
    travels with the failing node it descends from (``poisoned_by``) and the
    probe that fired (``tripwire``).

    ``poisoned_by`` is the *root* of the poisoning — the node the verdict
    probed — and not the node this row committed to, which the row carries as
    its own ``score.committed_pick``.  The distinction is feature 131's central
    claim read from the other side: a descendant was not probed, it was *in the
    wrong branch*, and the row's accounting belongs to the failure that marked
    that branch rather than to the descendant that happened to be picked.

    ``tripwire`` is ``None`` only where a caller built one directly around a row
    with no record behind it; :func:`_excised` refuses that state rather than
    producing it, so every value this module returns carries a named probe.
    """

    __slots__ = ("_poisoned_by", "_score", "_tripwire")

    def __init__(
        self,
        *,
        score: PoolScore,
        poisoned_by: Any,
        tripwire: str | None,
    ) -> None:
        if not isinstance(score, PoolScore):
            raise TripwireExcisionError(
                f"an excised score wraps a pool row, got {score!r} "
                f"({type(score).__name__}); the refusal is *about* a row, and "
                "a report that carried a bare number would not say which row "
                "the pool stopped serving"
            )
        object.__setattr__(self, "_score", score)
        object.__setattr__(self, "_poisoned_by", _pool_node_id(poisoned_by))
        if tripwire is not None and (
            not isinstance(tripwire, str) or not tripwire.strip()
        ):
            raise TripwireExcisionError(
                f"an excised score's tripwire is a probe name or None, got "
                f"{tripwire!r}; a blank name would read as an attribution "
                "where there is none"
            )
        object.__setattr__(self, "_tripwire", tripwire)

    @property
    def score(self) -> PoolScore:
        """The pool row the pool stopped serving."""
        return self._score

    @property
    def poisoned_by(self) -> str:
        """The failing node whose subtree this row's committed pick belongs to."""
        return self._poisoned_by

    @property
    def tripwire(self) -> str | None:
        """Which probe fired the failure; ``None`` only for a hand-built value."""
        return self._tripwire

    def to_payload(self) -> dict[str, Any]:
        """The refusal as a plain mapping, for a log line or a report."""
        payload = self._score.to_payload()
        payload.update({"poisoned_by": self._poisoned_by, "tripwire": self._tripwire})
        return payload

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExcisedScore):
            return NotImplemented
        return (
            self._score == other._score
            and self._poisoned_by == other._poisoned_by
            and self._tripwire == other._tripwire
        )

    def __hash__(self) -> int:
        return hash((self._score, self._poisoned_by, self._tripwire))

    def __repr__(self) -> str:
        return (
            f"ExcisedScore(score={self._score.id!r}, "
            f"pick={self._score.committed_pick!r}, "
            f"poisoned_by={self._poisoned_by!r}, tripwire={self._tripwire!r})"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(
            f"{type(self).__name__} is frozen; a recorded refusal cannot be "
            "edited into a different one"
        )


class ExcisedBranch:
    """Feature 132's answer for one failure: the branch, its scores, and the pool left.

    A *value* — frozen, self-describing — carrying both halves of the feature's
    sentence.  "A poisoned subtree" is :attr:`node_ids`, the set of nodes the
    failure marked, in feature 131's walk order (the failing node first).  "Every
    score that branch contributed" is :attr:`scores`, one :class:`ExcisedScore`
    per pool row this refusal stops serving.  And because the sentence is about a
    *pool* and not about a set of rows, :attr:`surviving_score_count` reports
    what the pool still serves afterwards — the number §C5's loop will actually
    aggregate — so a caller can read the cost of a poisoning without a second
    query.  It is **measured** off the pool rather than derived from the two
    parts above it, and the difference is reachable: because feature 131 keys
    its record by ``node_id``, a descendant later poisoned as its own origin
    rewrites that node's row and narrows this branch's :attr:`node_ids` — so
    :attr:`scores` can be a strict subset of the rows the pool refuses, and only
    the pool can say how many survive.  See :meth:`ReplayPool.excise`.

    :attr:`picks` is the honest middle term and it is worth naming: the branch
    nodes that *actually contributed* a score.  A poisoned node that was never
    committed to appears in :attr:`node_ids` and not in :attr:`picks`, which is
    the ordinary case for a deep subtree — the loop expanded most of its nodes
    long before any policy replay committed to them.  Reporting only the branch,
    or only the scores, would hide which of the two a poisoning actually cost.

    :attr:`surviving_picks` is app_spec.xml feature 365's sentence as a value —
    *"the replay pool returns 0 surviving nodes from that branch"* — and it is
    **measured**, by the second query :meth:`ReplayPool._confirm` runs, rather
    than asserted or assumed.  The constructor refuses a non-empty answer, so a
    value of this type is a proof that the refusal landed rather than a claim
    that it should have.
    """

    __slots__ = (
        "_campaign_id",
        "_node_ids",
        "_picks",
        "_poisoned_at",
        "_pool_size",
        "_root_node_id",
        "_scores",
        "_surviving_picks",
        "_surviving_score_count",
        "_tripwire",
    )

    def __init__(
        self,
        *,
        root_node_id: Any,
        campaign_id: Any,
        node_ids: Sequence[str],
        scores: Sequence[ExcisedScore],
        poisoned_at: Any,
        pool_size: int,
        tripwire: str | None,
        surviving_picks: Sequence[str] = (),
        surviving_score_count: int | None = None,
    ) -> None:
        object.__setattr__(self, "_root_node_id", _pool_node_id(root_node_id))
        object.__setattr__(self, "_campaign_id", _pool_node_id(campaign_id))
        marked = tuple(_pool_node_id(node) for node in node_ids)
        if not marked:
            raise TripwireExcisionError(
                "an excised branch names at least the failing node itself; an "
                "empty branch would be an excision of nothing, which is the "
                "one thing this feature must never report as a success"
            )
        if marked[0] != object.__getattribute__(self, "_root_node_id"):
            raise TripwireExcisionError(
                f"an excised branch's first node must be the failing node "
                f"{object.__getattribute__(self, '_root_node_id')!r}, got "
                f"{marked[0]!r}; the branch is the record's own subtree, and a "
                "set that does not contain its root did not come from that "
                "record"
            )
        if len(set(marked)) != len(marked):
            raise TripwireExcisionError(
                "an excised branch names each node once; a repeated node means "
                "the record reached one by two paths, which a tree with one "
                "parent per node cannot do"
            )
        object.__setattr__(self, "_node_ids", marked)

        root = object.__getattribute__(self, "_root_node_id")
        refused = tuple(scores)
        for entry in refused:
            if not isinstance(entry, ExcisedScore):
                raise TripwireExcisionError(
                    f"an excised branch's scores are ExcisedScore values, got "
                    f"{entry!r} ({type(entry).__name__})"
                )
            if entry.poisoned_by != root:
                raise TripwireExcisionError(
                    f"an excised branch is one failure's account, but a score "
                    f"in it was excised by {entry.poisoned_by!r} rather than "
                    f"by this branch's root {root!r}; folding two failures "
                    "into one report would make the branch unanswerable for an "
                    "operator reading it"
                )
        object.__setattr__(self, "_scores", refused)

        picks = {
            entry.score.committed_pick
            for entry in refused
            if entry.score.committed_pick is not None
        }
        stray = picks - set(marked)
        if stray:
            raise TripwireExcisionError(
                f"an excised branch's scores commit to {', '.join(sorted(stray))}, "
                "which the branch does not contain; a row outside the subtree is "
                "another branch's score, and excising it would refuse evidence "
                "a tripwire never condemned"
            )
        object.__setattr__(self, "_picks", tuple(sorted(picks)))

        # Feature 365, measured. The reader that produces this value runs a
        # second query over exactly the branch's rows and reports which ones the
        # pool still serves; a non-empty answer means the account and the pool
        # disagree, and this class refuses to exist in that state rather than
        # publishing a number that contradicts its own `scores`.
        survivors = tuple(sorted(_pool_node_id(node) for node in surviving_picks))
        if survivors:
            raise TripwireExcisionError(
                f"an excised branch still has {len(survivors)} node(s) the pool "
                f"serves ({', '.join(survivors)}); app_spec.xml feature 365 "
                "requires the pool to return 0 surviving nodes from a branch "
                "whose tripwire failed, so a value that reports survivors is a "
                "refusal that did not land and must not be handed to a caller "
                "as one"
            )
        object.__setattr__(self, "_surviving_picks", survivors)

        object.__setattr__(self, "_poisoned_at", _pool_instant(poisoned_at))
        if isinstance(pool_size, bool) or not isinstance(pool_size, int):
            raise TripwireExcisionError(
                f"an excised branch's pool_size must be an integer, got "
                f"{pool_size!r} ({type(pool_size).__name__})"
            )
        if pool_size < 0:
            raise TripwireExcisionError(
                f"an excised branch's pool_size must not be negative, got "
                f"{pool_size!r}"
            )
        if len(refused) > pool_size:
            raise TripwireExcisionError(
                f"an excised branch refuses {len(refused)} score(s) out of a "
                f"pool of {pool_size}; the survivors cannot be fewer than "
                "none, so the count and the rows describe different pools"
            )
        object.__setattr__(self, "_pool_size", pool_size)
        # ``surviving_score_count`` is **measured, not derived**, and the
        # distinction is a bug this signature was changed to close. The tempting
        # spelling is ``pool_size - len(scores)``, which is right whenever this
        # branch is the only failure in the pool — and wrong the moment a
        # *descendant* is later poisoned as its own branch. Feature 131's record
        # is keyed by ``node_id`` and upserts, so the second poisoning rewrites
        # the descendant's row to name the descendant as its own root, the first
        # failure's :meth:`~tripwires.poison.PoisonStore.subtree_of` narrows, and
        # this branch's ``scores`` becomes a strict *subset* of the rows the pool
        # refuses. The subtraction would then report rows as served that
        # :meth:`ReplayPool.survivors` — the read §C5 actually aggregates from —
        # does not return, which is the one number this value exists to state.
        # The pool measures it in the same read that produces ``surviving_picks``
        # and hands it in; the subtraction remains only as the fallback for a
        # value built by hand, where there is no pool to measure.
        if surviving_score_count is None:
            surviving_score_count = pool_size - len(refused)
        if isinstance(surviving_score_count, bool) or not isinstance(
            surviving_score_count, int
        ):
            raise TripwireExcisionError(
                f"an excised branch's surviving_score_count must be an integer, "
                f"got {surviving_score_count!r} "
                f"({type(surviving_score_count).__name__})"
            )
        if surviving_score_count < 0:
            raise TripwireExcisionError(
                f"an excised branch's surviving_score_count must not be "
                f"negative, got {surviving_score_count!r}"
            )
        if surviving_score_count > pool_size:
            raise TripwireExcisionError(
                f"an excised branch reports {surviving_score_count} surviving "
                f"score(s) from a pool of {pool_size}; a pool cannot serve more "
                "rows than it holds, so the count and the rows describe "
                "different pools"
            )
        object.__setattr__(self, "_surviving_score_count", surviving_score_count)
        if tripwire is not None and (
            not isinstance(tripwire, str) or not tripwire.strip()
        ):
            raise TripwireExcisionError(
                f"an excised branch's tripwire is a probe name or None, got "
                f"{tripwire!r}"
            )
        object.__setattr__(self, "_tripwire", tripwire)

    @property
    def root_node_id(self) -> str:
        """The failing node — the one the verdict probed.  Canonical UUID text."""
        return self._root_node_id

    @property
    def campaign_id(self) -> str:
        """The campaign whose branch was excised, read from the record."""
        return self._campaign_id

    @property
    def node_ids(self) -> tuple[str, ...]:
        """The poisoned branch: the failing node first, then its descendants.

        The *record's* own subtree — feature 131's
        :meth:`~tripwires.poison.PoisonStore.subtree_of` — so this is the set a
        past failure marked, and not what a re-walk of a tree grown since would
        return.

        **The record's subtree can narrow, and that is feature 131's semantics
        rather than a loss here.**  Its rows are keyed by ``node_id`` and
        upserted, so a *descendant* later poisoned as the origin of its own
        failure rewrites that descendant's row to name itself as the root, and
        this read narrows to the nodes still attributed to *this* failure.  The
        nodes it drops are not un-poisoned — their marks stand, and the pool
        still refuses their scores, which is why
        :attr:`surviving_score_count` is measured rather than derived from
        :attr:`scores`.  So this attribute answers *which nodes this failure is
        still the recorded origin of*, and a caller that wants the full set of
        nodes the pool refuses asks :meth:`ReplayPool.refused` or
        ``poisoned``.
        """
        return self._node_ids

    @property
    def size(self) -> int:
        """How many nodes the failure marked — one, for a leaf failure."""
        return len(self._node_ids)

    @property
    def picks(self) -> tuple[str, ...]:
        """The branch's nodes that actually contributed a score, sorted.

        A subset of :attr:`node_ids`.  The rest of the branch was poisoned
        without ever being committed to, which is the ordinary case: §C6 runs on
        candidates, and a candidate the loop expanded but no policy replay
        picked contributed nothing for this feature to refuse.
        """
        return self._picks

    @property
    def scores(self) -> tuple[ExcisedScore, ...]:
        """Every score the branch contributed — now refused by the pool."""
        return self._scores

    @property
    def excised_score_count(self) -> int:
        """How many pool rows this refusal stops serving."""
        return len(self._scores)

    @property
    def pool_size(self) -> int:
        """How many rows the pool held when this refusal was computed."""
        return self._pool_size

    @property
    def surviving_score_count(self) -> int:
        """How many rows the pool still serves — the number §C5 aggregates.

        **Measured by the pool, not derived from this value's own parts.**  The
        two agree whenever this branch is the only failure in the pool, and they
        diverge when a descendant was later poisoned as its own branch, because
        then :attr:`scores` is a subset of the rows the pool refuses. Deriving
        the count here would report rows as served that
        :meth:`ReplayPool.survivors` does not return; see the constructor for
        the full account.
        """
        return self._surviving_score_count

    @property
    def surviving_picks(self) -> tuple[str, ...]:
        """The branch's nodes the pool still serves — feature 365's count, measured.

        Always empty, and that is not a tautology: it is the answer of a second
        query (:meth:`ReplayPool._confirm`) run against the pool over exactly
        the branch's rows, and this class refuses to be constructed with a
        non-empty answer.  Exposed as a tuple rather than collapsed to the
        integer ``0`` so a caller reads *which* nodes were checked and finds
        none, rather than trusting a count.
        """
        return self._surviving_picks

    @property
    def poisoned_at(self) -> dt.datetime:
        """When the branch was halted — the failing node's own mark, UTC."""
        return self._poisoned_at

    @property
    def tripwire(self) -> str | None:
        """Which probe fired the failure; ``None`` only where nothing recorded it."""
        return self._tripwire

    def to_payload(self) -> dict[str, Any]:
        """The branch as a plain mapping, for a log line or an operator's report."""
        return {
            "root_node_id": self._root_node_id,
            "campaign_id": self._campaign_id,
            "size": self.size,
            "node_ids": list(self._node_ids),
            "picks": list(self._picks),
            "surviving_picks": list(self._surviving_picks),
            "excised_score_count": self.excised_score_count,
            "pool_size": self._pool_size,
            "surviving_score_count": self.surviving_score_count,
            "poisoned_at": self._poisoned_at.isoformat(),
            "tripwire": self._tripwire,
            "scores": [entry.to_payload() for entry in self._scores],
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExcisedBranch):
            return NotImplemented
        return (
            self._root_node_id == other._root_node_id
            and self._campaign_id == other._campaign_id
            and self._node_ids == other._node_ids
            and self._scores == other._scores
            and self._poisoned_at == other._poisoned_at
            and self._pool_size == other._pool_size
            and self._tripwire == other._tripwire
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._root_node_id,
                self._campaign_id,
                self._node_ids,
                self._scores,
                self._poisoned_at,
                self._pool_size,
                self._tripwire,
            )
        )

    def __repr__(self) -> str:
        return (
            f"ExcisedBranch(root={self._root_node_id!r}, nodes={self.size}, "
            f"excised={self.excised_score_count}, "
            f"surviving={self.surviving_score_count})"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(
            f"{type(self).__name__} is frozen; a branch that has been excised "
            "cannot be edited into a different one"
        )


# -- Addressing the pool ----------------------------------------------------------


def _pool_path(database_url: str) -> Path:
    """The file ``database_url`` names, under *this* module's error.

    :func:`~tripwires.layout.sqlite_path` refuses a URL this member cannot speak
    with :class:`~tripwires.TripwirePoisonError` — the member's one refusal for a
    stored value it cannot read, and feature 131's, whose own suite pins it.  A
    *pool* handed one of those has to answer in the pool's vocabulary, and that
    is not pedantry: the seat's docstring tells a caller that ``None`` from it
    means *a recorded failure cannot be acted on*, and a caller that writes
    ``except TripwireExcisionError`` around the replay path — which is the one
    thing that catches "a poisoned branch's scores could not be refused" — would
    miss a misrouted ``DATABASE_URL`` entirely and take the process down with an
    error from a module it never imported.  :func:`_pool_instant` wraps the
    other shared parser for the same reason; these two are the only places the
    pool reads a value it did not write.
    """
    try:
        return sqlite_path(database_url)
    except TripwirePoisonError as exc:
        raise TripwireExcisionError(
            f"the replay pool could not be addressed: {exc}"
        ) from exc


# -- The store -------------------------------------------------------------------


class ReplayPool:
    """Feature 132's read: the pool, as the replay path must see it.

    Constructed with the database URL it reads; :meth:`survivors` is the pool
    with every poisoned branch's scores refused, :meth:`excise` is one failure's
    account of a branch, and :meth:`scores_of` is the pool's rows for a single
    node.  The class resolves its path lazily, so constructing one performs no
    I/O — the contract every store in this workspace states.

    **It writes nothing.**  No ``INSERT``, no ``UPDATE``, no ``DELETE``, and no
    column this member adds to a table it does not own: the pool is the replay
    member's (features 245-255) and the schema is ``0109``'s, and a member that
    reached into either would be legislating for a feature three hundred indexes
    away.  What it does write is the one thing this member owns — the ``node``
    table's ``poisoned_at`` column and the member's own audit table — and it
    writes those only through :class:`~tripwires.poison.PoisonStore`, the module
    that owns them.

    The pool holds a poison store rather than re-reading the marks itself, and
    that is the one-provenance rule applied across the member's two feature
    modules: the branch's membership, its campaign and its failing node's
    instant are all questions feature 131 already answers, and a second walk of
    ``parent_id`` here would be a second opinion about what a past failure
    marked.
    """

    def __init__(
        self, database_url: str, *, store: PoisonStore | None = None
    ) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise TripwireExcisionError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # The marks live in the same database and are read through the module
        # that writes them. A store may be handed in so a test pins one, but it
        # must name the same file — see :meth:`_poison_store`.
        self._store = store
        # Resolved on first use rather than at construction: building the pool
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> ReplayPool | None:
        """The pool ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        pool component — a discoverable state, not an exception — while a replay
        path that must refuse a poisoned branch's scores is the caller that must
        not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this pool reads."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this pool, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name, under this module's own
        error: see :func:`_pool_path`) the first time an operation needs it.
        """
        if self._path is None:
            self._path = _pool_path(self._database_url)
        return self._path

    @property
    def marks(self) -> PoisonStore:
        """Feature 131's store — where the marks and the record live.

        Exposed because the two features answer different halves of §C6 and a
        caller auditing an excision needs both: the pool says *which scores are
        refused*, and the store says *when and by what* the branch was marked.
        Handing back the composed instance rather than a fresh one keeps the two
        on one lifecycle, which is what makes "the pool refuses exactly what the
        store marked" a property of one object graph.
        """
        return self._poison_store()

    def _poison_store(self) -> PoisonStore:
        """The poison store this pool reads its marks through.

        A store handed to the constructor is used only when it names the same
        file; one pointed elsewhere would make "the pool refuses what the store
        marked" a sentence about two different databases, and the failure would
        be invisible — a pool serving every score while an operator read a fully
        marked tree.
        """
        if self._store is None:
            self._store = PoisonStore(self._database_url)
        elif self._store.path != self.path:
            raise TripwireExcisionError(
                f"the pool reads {self.path} but was handed a store reading "
                f"{self._store.path}; a pool refusing marks from another "
                "database would serve every score of every poisoned branch "
                "while the record showed the branch marked"
            )
        return self._store

    def ensure_schema(self) -> None:
        """Bring the database to the shape this pool reads, idempotently.

        Feature 131's schema first — the ``node`` table, its ``poisoned_at``
        column and the audit table — then ``0109``'s ``replay_score`` through
        :func:`~tripwires.layout.replay_pool_bootstrap_schema`.  The order is
        the dependency order and not a formality: this pool's own read joins
        ``replay_score`` to ``node``, so a pool created before the tree would be
        one every query fails against.

        Public for the same reason
        :meth:`~tripwires.poison.PoisonStore.ensure_schema` is: an operator
        pointing this member at a database the orchestrator has not migrated yet
        runs it once, and a test seeds a pool into exactly the schema the store
        will read.  Every statement is ``IF NOT EXISTS``, so running it against
        a fresh database, a migrated one and one this member already prepared
        all take the same path and leave the same schema.
        """
        self._poison_store().ensure_schema()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript(
                replay_pool_bootstrap_schema(dialect_of(connection))
            )

    def _connect(self) -> sqlite3.Connection:
        """Open the database, bringing it to this pool's shape first.

        Foreign keys are enabled, as in every SQLite store in the workspace, and
        the caller owns the connection: use it as a context manager to commit.
        This store issues no statement that could need committing, but the
        contract is the workspace's and a reader should not have to work out
        which stores differ.  The schema work is delegated to
        :meth:`ensure_schema` rather than inlined, so a caller that only wants
        the schema does not have to open a connection it will not use.

        The path is resolved *before* the schema is brought up, and the order is
        load-bearing: :meth:`ensure_schema` delegates to the poison store, whose
        own translation of the URL refuses in feature 131's vocabulary, and a
        pool handed a URL this member cannot speak must answer as the *pool*
        rather than as the store whose schema it borrows.  Resolving here means
        :func:`_pool_path` refuses the misrouted URL first.
        """
        path = self.path
        self.ensure_schema()
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    # -- Feature 132: the refusal ---------------------------------------------

    def entries(self) -> tuple[tuple[PoolScore, bool, str | None, str | None], ...]:
        """The whole pool, each row beside whether it is excised and by what.

        The one read every other method filters, returned rather than kept
        private because it is the *answer* to §C6's question at pool scale —
        "which rows are refused, and by which failure" — and because four public
        methods deriving from one query is how they cannot disagree about which
        rows exist.

        Each entry is ``(row, excised, root_node_id, tripwire)``.  ``excised`` is
        whether the row's committed pick names a node carrying a mark; the two
        trailing values are the audit table's attribution, and are ``None`` both
        for a served row and for a marked node whose failure nothing recorded.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(_POOL_QUERY).fetchall()
        return tuple(
            (
                _row_from(row[:_ROW_WIDTH]),
                row[_ROW_WIDTH] is not None,
                None
                if row[_ROW_WIDTH + 1] is None
                else _pool_node_id(row[_ROW_WIDTH + 1]),
                row[_ROW_WIDTH + 2],
            )
            for row in rows
        )

    def survivors(self) -> tuple[PoolScore, ...]:
        """The pool as §C5's dreaming loop must read it — the refusal applied.

        Every row whose committed pick is not poisoned, in
        ``(created_at, id)`` order.  This is feature 132's sentence at pool
        scale: *"excises a poisoned subtree from the replay pool, which rejects
        every score that branch contributed"* — the branch's scores are absent
        from what this returns, and every other branch's and campaign's scores
        are present exactly as they were.

        Nothing is deleted to make this true.  The rows are still in the table,
        which is what lets an operator ask afterwards what a poisoned branch
        contributed; the pool simply does not *serve* them, and because no code
        path un-marks a node, this set can only shrink.
        """
        return tuple(entry[0] for entry in self.entries() if not entry[1])

    def refused(self) -> tuple[ExcisedScore, ...]:
        """Every score the pool refuses, each beside the failure that condemned it.

        The whole-pool complement of :meth:`survivors`, and the read an operator
        wants when the question is *what have the tripwires cost us?* rather than
        *what may I replay?*.
        """
        return tuple(
            _excised(entry[0], entry[2], entry[3])
            for entry in self.entries()
            if entry[1]
        )

    def scores_of(self, node_id: Any) -> tuple[PoolScore, ...]:
        """Every pool row that committed to ``node_id`` — the node's contribution.

        Whether those rows are refused is not this method's question: it answers
        *what did this node contribute*, and a caller deciding whether to serve
        them asks :meth:`survivors` or reads :meth:`poisoned`.  Keeping the two
        apart is deliberate — a method answering both would have to return the
        same empty tuple for a poisoned node with no scores and for a clean node
        with no scores, which are different facts a replay path must not
        confuse.
        """
        node = _pool_node_id(node_id)
        return tuple(
            entry[0] for entry in self.entries() if entry[0].committed_pick == node
        )

    def poisoned(self, node_id: Any) -> bool:
        """Whether the pool refuses ``node_id``'s scores — asked of the marks.

        Reads feature 131's answer through the store that wrote it, so the
        pool's one-bit question and the tree's own mark are one answer rather
        than two that can drift.
        """
        return self._poison_store().is_poisoned(node_id)

    def excise(self, root_node_id: Any) -> ExcisedBranch:
        """Excise the branch ``root_node_id`` was poisoned with — feature 132.

        The whole of the feature in one call, by way of a read: the failing
        node's failure is confirmed from feature 131's record, the branch is the
        record's own subtree, feature 131's mark on the failing node is confirmed
        present, and the pool is partitioned by membership in that branch — every
        row whose committed pick is one of its nodes is refused, every other row
        is served.  Nothing is written.

        **Why the failing node's mark is required and not merely its record.**
        The record is what a failure *wrote*; the mark is what the replay path
        *reads*, and feature 131 states the mark's residence for exactly that
        reason.  A record beside an absent mark is the half-written state feature
        131's own ``_confirm`` exists to make impossible, and an excision
        computed from it would report a branch refused while the pool served
        every score of it — the silent-divergence failure this category exists to
        prevent.  So it is refused by name, and nothing is reported.

        Refuses, in this order, each naming what it is about:

        1. a node id that cannot join the record's key
           (:class:`~tripwires.TripwireExcisionError`);
        2. a node no poisoning ever recorded — "excise this branch" and "this
           branch was never poisoned" are different sentences, and the second is
           not an excision of nothing;
        3. a record whose own row for the failing node is missing;
        4. a failure whose mark is absent from the tree (see above);
        5. a branch whose rows the final read-back shows served anyway
           (:meth:`_confirm`), or a marked node whose failure nothing
           attributed (:func:`_excised`).

        Returns the :class:`ExcisedBranch`, which answers *what did that branch
        contribute, and what does the pool still serve?* — including
        :attr:`ExcisedBranch.surviving_picks`, which is app_spec.xml feature
        365's "0 surviving nodes from that branch" measured rather than
        asserted.
        """
        root = _pool_node_id(root_node_id)
        store = self._poison_store()
        branch = store.subtree_of(root)
        if not branch:
            raise TripwireExcisionError(
                f"no poisoning ever recorded {root!r} as a failing node, so "
                "there is no branch to excise; a clean node is not an excision "
                "of nothing, and a pool that answered one with an empty success "
                "would let a caller report an excision it never performed — the "
                "failure §C6 exists to prevent, arriving as a quiet green "
                "rather than as a red"
            )
        record = store.load(root)
        if record is None:
            raise TripwireExcisionError(
                f"the record holds a subtree for {root!r} but no row for the "
                "node itself; the failing node is the row the rest of the "
                "branch is read through, and its absence means the record was "
                "written by something other than this member's poisoning"
            )
        marked_at = store.poisoned(root)
        if marked_at is None:
            raise TripwireExcisionError(
                f"the record says {root!r} was poisoned but the tree carries no "
                "mark on it; the replay path reads the mark, so excising on the "
                "record alone would report the branch refused while the pool "
                "went on serving every score it contributed. Repair the mark "
                "and re-run; this excision wrote nothing"
            )

        contained = set(branch)
        entries = self.entries()
        refused = tuple(
            _excised(entry[0], entry[2], entry[3])
            for entry in entries
            if entry[1] and entry[0].committed_pick in contained
        )
        surviving_picks = self._confirm(root, contained, refused)
        return ExcisedBranch(
            root_node_id=root,
            campaign_id=record.campaign_id,
            node_ids=branch,
            scores=refused,
            poisoned_at=marked_at,
            pool_size=len(entries),
            tripwire=record.tripwire,
            surviving_picks=surviving_picks,
            # Measured off the same read that answered the branch, not derived
            # from `pool_size - len(refused)`: a descendant poisoned as its own
            # branch makes this branch's `refused` a subset of the rows the pool
            # actually refuses, and the subtraction would overstate what is
            # served — contradicting `survivors()`, which is the read §C5 makes.
            surviving_score_count=sum(1 for entry in entries if not entry[1]),
        )

    def _confirm(
        self,
        root: str,
        contained: set[str],
        refused: Sequence[ExcisedScore],
    ) -> tuple[str, ...]:
        """Read the branch's rows back; return the nodes the pool still serves.

        The same discipline feature 131's ``_confirm`` applies to a write, on the
        read side: the set this method reports and the set the database actually
        holds must agree, and a disagreement is not an excision.

        **Two checks, and the second is the one that carries the feature.**

        The second is feature 365's, and it is the check a caller actually
        depends on.  It asks the question the spec's own end-to-end sentence asks
        — *"the replay pool returns 0 surviving nodes from that branch"* — by
        naming which of the branch's nodes still have a served row, and returns
        that (always empty) set rather than a count, so the caller publishes
        *which* nodes were checked and found none.  It is what refuses a branch
        whose descendant's mark was cleared out from under the record: the row
        goes on being served, so a node of the branch survives, and the account
        cannot be published.

        The first is a *cross-read consistency* guard, and its scope is worth
        stating precisely because it looks like the second and is not.  It asks
        whether the rows the branch's picks hold are exactly the rows refused.
        Both sides are derived from the same two facts — a pick's node being
        marked, and that node being in the branch — so against one unchanging
        database this comparison cannot fail: :meth:`entries` and this method are
        two connections, and one query each.  What it catches is the database
        changing *between* them (a concurrent writer, or feature 131's own write
        landing mid-read), which would otherwise let the account above refuse
        fewer rows than the branch holds, with the missing ones quietly served.
        It is therefore deliberately kept although no single-connection test can
        reach it: a guard whose absence is invisible is exactly the guard worth
        having, and its cost is one comparison over a set already in hand.

        Both checks are one query: the pool's rows whose committed pick is in the
        branch, each beside the tree's mark for that pick.  ``poisoned_at`` null
        means the pool still serves that row, so its pick is a surviving node.
        """
        placeholders = ", ".join("?" for _ in contained)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT s.{REPLAY_SCORE_ID_COLUMN}, "
                f"       s.{REPLAY_SCORE_COMMITTED_PICK_COLUMN}, "
                f"       n.{NODE_POISONED_COLUMN} "
                f"FROM {REPLAY_SCORE_TABLE} AS s "
                f"LEFT JOIN {NODE_TABLE} AS n "
                f"ON n.{NODE_ID_COLUMN} = s.{REPLAY_SCORE_COMMITTED_PICK_COLUMN} "
                f"WHERE s.{REPLAY_SCORE_COMMITTED_PICK_COLUMN} "
                f"IN ({placeholders}) "
                f"ORDER BY s.{REPLAY_SCORE_ID_COLUMN}",
                tuple(sorted(contained)),
            ).fetchall()

        held = {_pool_node_id(row[0]) for row in rows if row[2] is not None}
        reported = {entry.score.id for entry in refused}
        if held != reported:
            missed = sorted(held - reported)
            invented = sorted(reported - held)
            detail = (
                f"{', '.join(missed)} came back marked but unrefused"
                if missed
                else f"{', '.join(invented)} were refused without a mark"
            )
            raise TripwireExcisionError(
                f"the excision of {root!r} partitioned the branch "
                f"incompletely: {detail}. A branch whose scores the pool still "
                "serves while the account says they were excised is the failure "
                "this feature exists to prevent, so the pool refuses rather "
                "than reporting a branch it did not fully refuse"
            )

        # Feature 365, measured: which of the branch's nodes still have a row the
        # pool serves. A row whose mark is null is served, so its pick — a node
        # of this branch by the query's own WHERE — is a surviving node. This is
        # the check that fires for a branch half-unmarked by hand, and it fires
        # *before* the branch value is built, so the value's own refusal of a
        # non-empty surviving set is a second line rather than the only one.
        return tuple(
            sorted(
                {
                    _pool_node_id(row[1])
                    for row in rows
                    if row[2] is None and row[1] is not None
                }
            )
        )

    def excised_roots(self) -> tuple[str, ...]:
        """Every failing node a poisoning recorded, in the record's own order.

        The pool's answer to *which branches is this database holding refused?* —
        read from feature 131's audit table, which is the record of the acts, so
        a branch whose failure happened before this process started is listed
        exactly as one it watched happen.

        Ordered by the earliest row of each root, which is the order the failures
        were recorded in: ``rowid`` is SQLite's insertion sequence for a table
        whose key is a UUID (so it is not a rowid alias and the insert order is
        preserved), and the ``MIN(rowid)`` is the root's first-written row —
        while the outer ``root_node_id`` term keeps the result deterministic for
        a tie no writer can actually produce, since one root's rows are written
        in one statement.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT root_node_id FROM {POISON_TABLE} "
                "GROUP BY root_node_id HAVING MIN(rowid) >= 0 "
                "ORDER BY MIN(rowid), root_node_id"
            ).fetchall()
        return tuple(_pool_node_id(row[0]) for row in rows)


# -- Row building -----------------------------------------------------------------


def _pool_node_id(value: Any) -> str:
    """Validate a node id — :func:`~tripwires.layout.validated_node_id`, pool-side.

    The member has exactly one node-id normalization, and this is not a second
    one: it is that function under :class:`~tripwires.TripwireExcisionError`
    instead of :class:`~tripwires.TripwirePoisonError`, for the reason
    :func:`_pool_path` gives at length.  Every id this module reads joins a UUID
    column — the row's own key, its world, the pick it committed to, the nodes a
    branch's record names — and a mixed-case or braced spelling of one node
    would read as two nodes in the set that decides whether a branch's scores
    are served, so the validation itself is not optional here.

    A caller in the replay path catches this module's error and only this
    module's error.  The alternative — letting the tree store's type escape —
    would mean the one function a §C5 loop calls to stop aggregating rejected
    evidence refuses in a vocabulary that loop explicitly did not catch.
    """
    try:
        return validated_node_id(value)
    except TripwirePoisonError as exc:
        raise TripwireExcisionError(f"the replay pool could not read it: {exc}") from exc


def _row_from(values: Sequence[Any]) -> PoolScore:
    """Build a :class:`PoolScore` from the tuple :data:`_SELECT_COLUMNS` selects.

    Positional, and that is why the column tuple is spelled once in
    :mod:`tripwires.layout` and shared between the DDL and this read: a
    ``SELECT *`` and a hand-counted unpack are the pair that drifts apart
    silently, and the drift shows up as a score row whose world is its policy
    version.
    """
    (
        score_id,
        policy_version,
        world_id,
        beta,
        score,
        committed_pick,
        is_holdout,
        created_at,
    ) = values
    return PoolScore(
        id=score_id,
        policy_version=policy_version,
        world_id=world_id,
        beta=beta,
        score=score,
        committed_pick=committed_pick,
        is_holdout=is_holdout,
        created_at=created_at,
    )


def _excised(
    row: PoolScore, poisoned_by: str | None, tripwire: str | None
) -> ExcisedScore:
    """Pair a refused row with its attribution, refusing an unattributable one.

    ``poisoned_by`` is ``None`` when the row's node carries a mark with no audit
    row beside it.  That is a state feature 131 cannot write — it writes the mark
    and the record in one transaction — and it is *refused* rather than repaired
    or reported, for a reason specific to what this feature refuses by: the unit
    is the *branch*, so a marked node whose failure nothing recorded would leave
    the pool unable to say which failure it was refusing.  Serving the scores
    would be wrong (the mark says they are condemned) and inventing a root would
    be worse (an excision attributed to a failure that may not have caused it),
    so the pool stops and names the row.
    """
    if poisoned_by is None:
        raise TripwireExcisionError(
            f"the pool row {row.id!r} commits to {row.committed_pick!r}, whose "
            "node carries a poisoning mark but no record naming the failure "
            "that wrote it; this feature refuses scores *by branch*, so a mark "
            "nothing attributes cannot be excised without the pool inventing "
            "which failure condemned it"
        )
    return ExcisedScore(score=row, poisoned_by=poisoned_by, tripwire=tripwire)


def _pool_instant(value: Any) -> dt.datetime:
    """Parse a stored instant, refusing one that is not a usable stamp.

    :func:`~tripwires.layout.parsed_instant` under this module's error, for the
    reason the two modules have two error types at all: a caller in the replay
    path catches :class:`~tripwires.TripwireExcisionError`, and an unparseable
    ``created_at`` surfacing as a *poison* error would send it looking in the
    wrong module for the cause.  The parser itself is shared, so the two features
    cannot disagree about what a stored instant is.
    """
    try:
        return parsed_instant(value)
    except TripwirePoisonError as exc:
        raise TripwireExcisionError(
            f"a replay score's stored instant could not be parsed: {exc}"
        ) from exc


# -- The two module-level entry points -------------------------------------------


def excise_subtree(
    root_node_id: Any,
    *,
    database_url: str | None = None,
    pool: ReplayPool | None = None,
    store: PoisonStore | None = None,
) -> ExcisedBranch:
    """Excise the branch a poisoning marked — feature 132, spelled for a caller.

    The module-level spelling of :meth:`ReplayPool.excise`, for a caller that has
    a failing node and wants the feature rather than an object: it composes a
    pool from ``DATABASE_URL`` (or the URL handed to it) and runs the excision.
    A ``pool`` may be handed in instead, which is what the composed component is
    and what a test passes to pin the database it read.

    Refuses a call that names no pool — neither a ``pool`` nor a
    ``database_url`` nor a ``DATABASE_URL`` — with
    :class:`~tripwires.TripwireExcisionError`, and that is deliberate rather than
    a fall-through.  A deployment with no relational store cannot apply feature
    132 *at all*, and a version of this function that quietly returned an empty
    branch would let a replay path believe the tripwires had excised a poisoned
    branch while every score it contributed went on being aggregated.
    """
    resolved = pool if pool is not None else _pool_from(database_url, store=store)
    return resolved.excise(root_node_id)


def surviving_scores(
    *,
    database_url: str | None = None,
    pool: ReplayPool | None = None,
    store: PoisonStore | None = None,
) -> tuple[PoolScore, ...]:
    """The pool with every poisoned branch's scores refused — §C5's read.

    The shape a replay loop wants: it holds no pool object, it needs the scores
    it may aggregate, and the refusal must be applied for it rather than left as
    an exercise.  Returns the same tuple :meth:`ReplayPool.survivors` carries, so
    a caller that needs the per-branch account asks for the branch instead and is
    not served by a second code path.
    """
    resolved = pool if pool is not None else _pool_from(database_url, store=store)
    return resolved.survivors()


def _pool_from(
    database_url: str | None, *, store: PoisonStore | None = None
) -> ReplayPool:
    """The pool a module-level call runs against, or a refusal naming why not.

    An explicit ``database_url`` wins over the environment, so a caller with a
    URL in hand never depends on ambient state — the same precedence feature
    131's own entry point gives its argument.  Absent both, the refusal names the
    variable, because "nothing was configured" is the one failure a caller can
    fix without reading this module.
    """
    if database_url is not None:
        return ReplayPool(database_url, store=store)
    resolved = ReplayPool.resolve()
    if resolved is None:
        raise TripwireExcisionError(
            f"no pool to excise from: {DATABASE_URL_ENV} names no relational "
            "store and no explicit database_url was passed. Feature 132 rejects "
            "the scores a poisoned branch contributed, and a caller that cannot "
            "apply that refusal must not proceed as though it had — §C5's "
            "dreaming loop would go on aggregating the very evidence the "
            "tripwire rejected"
        )
    return resolved
