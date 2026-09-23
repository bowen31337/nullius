"""Feature 255 — one replay_score row per run, into the relational store.

app_spec.xml, "Replay Engine", feature 255 (``depends_on=249``): *System
persists one replay_score row per run carrying policy version, world id, beta,
score and committed pick.*  It is the *persistence* half of the terminal
moment feature 249 completes: 249 reads the committed pick at termination and
answers the score a policy earns — the pair this module writes — and this
feature is the row that records it.  docs/nullius-tech-architecture.md §10.1
names the row in its own sentence — *"every replay emits ``(policy_version,
world_id, beta, score, committed_pick)``"* — and migration 0109 legislates the
schema it lands in, but nothing in this workspace calls that migration's
``apply()``; the row is written by this module, into a row space this module
ensures exists idempotently on connect, the contract every store in this
workspace states.

**The row is the record of a completed scoring, not a verdict on it.**  The
natural mistake on the persistence side would be to refuse a low score — to
treat a ``-inf`` (the miss, feature 249's floor) or a bad pick as a row the
store should not hold.  This module refuses the *ask*, never the score: a low
or ``-inf`` score is persisted, because the row is the record of a scoring
that *completed* — the miss is a score the comparison keeps (prd §438, docs
§598, and feature 249's whole point that a policy which emitted no pick is
*scored* ``-inf``, not dropped).  To refuse the miss at the store would be to
drop exactly the row an operator holds the miss rate against, and to
re-introduce at the write the exception feature 249 removed from the
comparison.  What is refused is what a *row* is: the ask that would name
nothing (a NaN score, an empty id) or a store that will not take it.

**The value written is feature 249's :class:`~replay.TerminalPick`, read
duck-typed.**  The ``pick`` argument is that object — the pick absent-able,
the score always present, the pair the row is shaped around — but the seam
does not ``isinstance`` it: the module loader imports a member under a
synthetic name and re-executes it, so the record a *composed* application's
path produced can be a second class object of the same name, and an
``isinstance`` would refuse the very value composition produces.  The seam
reads what a TerminalPick *is*: a carrier with a ``pick`` attribute (absent,
for the miss) and a ``score`` attribute (always present).  A carrier with
neither is refused, naming what arrived — the repair is the argument, on the
caller's side of the seam, exactly as 249's ``committed_pick`` refuses a
carrier with no ``terminate``.

**The ask is validated before the store is touched.**  The ordering is the
member's law — 245's refusal before the tree is read, 251's before the arena
is touched, 249's before the record is terminated — and it holds here too: a
malformed ask is the caller's to repair, and the store should never see it.
So the carrier, the score, the ids and the beta are each validated before a
connection is opened, and a broken ask is refused without opening so much as
one.

* the **score** — a real number or ``-inf``.  A NaN is refused: it compares
  false against everything and would drop out of every argmax, reading as "no
  scoring" (the same reason 249 refuses to score a NaN and migration 0109's
  ``score REAL NOT NULL`` forbids a null one).  An infinity is the miss,
  persisted as the floor — never refused, because the miss is the row an
  operator counts.
* the **policy version** and **world id** — non-empty strings.  An id that
  names nothing writes a row no ``(policy, world)`` pair names, and a row that
  names no pair is the record of a scoring that did not happen.
* the **beta** — a finite number.  The row's beta field is required (migration
  0109), and a beta that is not finite would be a hyperparameter no reader
  could reproduce the scoring under.

**The committed pick is the node id, or NULL for the miss.**  A committing
policy's pick is feature 222's :class:`~policy_runtime.CommittedPick`, read
through its one ``node_id`` — the node the policy committed to — and written
as the row's ``committed_pick``.  A policy that emitted no pick writes NULL:
the decision that was never made stays distinguishable from one that was
(migration 0109's nullable ``committed_pick``), and NULL is not the same fact
as a node id the policy committed to.  The node id is read, not re-validated:
:class:`~policy_runtime.CommittedPick` validated it at construction, and a
second statement here would be a second place the same law could drift.

**The store is the one relational store every member store addresses by
``DATABASE_URL``.**  ``sqlite:///`` on a single machine, Postgres when a
deployment grows into one — the cost-model member's identity and latency
tables, the evaluator's metric tables, discovery's campaign records, feature
254's latency table all speak it, and this module is the replay-score-side
echo.  The row space is ensured to exist on connect (idempotent, so a fresh
database and an existing one take one path and no migration step is needed
and no shared schema file is touched).  A store that cannot take the write —
unconfigured, an unsupported URL scheme, a locked or unwritable database —
refuses as :class:`~replay.ReplayScoreError`, chained to the store's own
refusal, never swallowed: a score that was measured but never landed is the
state the feature exists to rule out, exactly as feature 254's write refuses
on its side.

**What this module deliberately does not do.**  It does not *score*: the
arithmetic is feature 249's curried scorer, and this module is handed the
already-scored :class:`~replay.TerminalPick` — it persists, it does not
compute.  It does not *widen* or *edit* migration 0109: the schema the row
lands in is the migration's, and this module neither creates that migration
nor alters it — it ensures the row space exists on connect, the contract
every member store states, and the migration remains the schema's source of
record.  It does not *register a component*: a store addressed by
``DATABASE_URL`` is never composed, the stance every store in this workspace
takes, so the member's one ``@register`` contribution stays feature 245's
stateless facade and no builder here can spend I/O inside ``create_app()``.
The composed spelling is the verb :meth:`replay.ReplayEngine.persist_replay_score`
on that facade.

Stdlib only — :mod:`datetime` for the row's id, :mod:`json` for the samples
this module does not need but the store's contract shares, :mod:`math` for
the finite check, :mod:`os` for the one ambient the workspace's stores share
(``DATABASE_URL``), :mod:`sqlite3` for the store itself, :mod:`contextlib` and
:mod:`pathlib` and :mod:`urllib.parse` for the connection's plumbing,
:mod:`typing` for the seam — no numerics, no Polars, no PyArrow, so importing
this member on every factory scan still costs composition nothing, per §12's
rule that the replay path may not grow a numerical stack.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import ReplayScoreError

__all__ = [
    "DATABASE_URL_ENV",
    "REPLAY_SCORE_TABLE",
    "persist_replay_score",
]

#: The environment variable naming the relational store — the one spelling
#: every member store in this workspace already uses (the cost-model identity
#: and latency stores, the evaluator's metric stores, discovery's campaign
#: records, feature 254's observability metrics store), restated here so this
#: module states its own contract and imports no sibling's.  The replay-score
#: store is that store: §16's "single Postgres metrics table", ``sqlite:///``
#: on a single machine.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the replay_score rows live in — this member's own, in the
#: relational store ``DATABASE_URL`` names, created idempotently on connect so
#: no migration step is needed and no shared schema file is touched.  Named
#: for what it holds (the score of each replay run) the way feature 254's
#: ``replay_latency_metrics`` is, so a reader of the store can tell whose row
#: it is holding.  Its schema is migration 0109's — this module does not edit
#: that migration; it ensures the row space exists on connect.
REPLAY_SCORE_TABLE = "replay_score"

_SCHEMA = f"""
-- Feature 255: one replay_score row per run, carrying the policy version,
-- the world id, the beta, the score and the committed pick.
--
-- The schema is migration 0109's, of which this module is the writer, not
-- the author: this module ensures the row space exists on connect so no
-- migration step is needed, but the migration remains the schema's source of
-- record.  `id` is a per-row uuid; `committed_pick` is nullable so a policy
-- that emitted no pick (the miss, scored -inf) stays distinguishable from one
-- that committed to a node.
CREATE TABLE IF NOT EXISTS {REPLAY_SCORE_TABLE} (
    id             TEXT NOT NULL,   -- per-row uuid; the row's own identity
    policy_version TEXT NOT NULL,   -- the policy revision under test
    world_id       TEXT NOT NULL,   -- the world the policy was replayed against
    beta           REAL NOT NULL,   -- the beta the scoring was made at
    score          REAL NOT NULL,   -- the resulting score (-inf for a miss)
    committed_pick TEXT,            -- the node id committed to, or NULL for a miss
    is_holdout     INTEGER NOT NULL DEFAULT 0,  -- 1 if scored as holdout, else 0
    created_at     TEXT NOT NULL,   -- ISO 8601 UTC: when the row was written
    PRIMARY KEY (id)
);
"""


def persist_replay_score(
    pick: Any,
    policy_version: Any,
    world_id: Any,
    beta: Any,
    *,
    is_holdout: bool = False,
    database_url: str | None = None,
) -> str:
    """Persist one replay_score row per run; return the row's id.

    Feature 255's sentence, made concrete: feature 249's
    :class:`~replay.TerminalPick` — the pick (absent-able) and the score
    (always present) — is written as exactly one row into the relational
    store ``DATABASE_URL`` names, carrying the policy version under test, the
    world it was replayed against, the beta it was scored at, the resulting
    score, and the committed pick.

    **The ask is validated before the store is touched.**  The ordering is the
    member's law (245's refusal before the tree is read, 251's before the
    arena is touched, 249's before the record is terminated): a malformed ask
    is the caller's to repair, and the store should never see it — so the
    carrier, the score, the ids and the beta are each validated before a
    connection is opened, and a broken ask is refused without opening so much
    as one.

    Args:
        pick: Feature 249's :class:`~replay.TerminalPick` — the pick
            (absent-able, ``None`` for a policy that emitted none) and the
            score (always present).  Read duck-typed: a carrier with neither a
            ``pick`` nor a ``score`` attribute is refused, naming what arrived.
        policy_version: The policy revision under test — a non-empty string.
        world_id: The world the policy was replayed against — a non-empty
            string.
        beta: The beta the scoring was made at — a finite number.
        is_holdout: Whether this scoring was scored as holdout; defaults to
            ``False``.  Persisted as a boolean flag beside the row.
        database_url: The relational store to write to; defaults to
            ``DATABASE_URL``.

    The score itself is never refused — a low or ``-inf`` score is persisted,
    because the row is the record of a completed scoring (the miss is a score
    the comparison keeps).  What is refused is the ask (a carrier that is not
    a TerminalPick, a NaN score, an empty id, a non-finite beta) or a store
    that cannot take the write (unconfigured, an unsupported URL scheme, a
    locked or unwritable database) — surfaced as
    :class:`~replay.ReplayScoreError`, chained to the store's own refusal,
    never swallowed: a score that measured but never landed is the state the
    feature exists to rule out.

    Returns:
        The ``id`` of the row written — a per-row uuid, so a caller can name
        the row it just persisted without a second read.
    """
    # The ask first, the store second: the carrier, the score, the ids and the
    # beta are each validated before a connection is opened, so a broken ask
    # never reaches the store and the ordering of the member's other refusals
    # holds here too.  The row id is minted before the write so the id and the
    # row are one fact.
    node_id = _committed_node_id(pick)
    score = _score_of(pick)
    version = _policy_version_of(policy_version)
    world = _world_id_of(world_id)
    beta_value = _beta_of(beta)
    holdout = _holdout_of(is_holdout)
    row_id = _row_id()
    instant = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    try:
        with closing(_open_store(database_url)) as connection, connection:
            connection.execute(
                f"""
                INSERT INTO {REPLAY_SCORE_TABLE} (
                    id, policy_version, world_id, beta, score,
                    committed_pick, is_holdout, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    version,
                    world,
                    beta_value,
                    score,
                    node_id,
                    1 if holdout else 0,
                    instant,
                ),
            )
    except ReplayScoreError:
        raise
    except (sqlite3.Error, OSError) as exc:
        # The store's own failure, translated: a caller catching this
        # member's base class must catch a score that measured but never
        # landed, and the original is chained so the operator still sees the
        # database's own words.
        raise ReplayScoreError(
            f"could not persist the replay score for policy {version!r} "
            f"against world {world!r} into the relational store: {exc!r}. "
            "A score that was measured but never landed is the state feature "
            "255 exists to rule out — the row is how an operator holds the "
            "miss rate and the per-(policy, world) verdict against — so the "
            "failure is surfaced, never swallowed; the repair is the store's "
            "(the original refusal is chained), never a re-run over a scoring "
            "that already completed"
        ) from exc
    return row_id


# -- the ask, validated before the store is touched -----------------------------------------


def _score_of(pick: Any) -> float:
    """The score to persist — a real number or -inf, read from the TerminalPick.

    The score is the row's reason for existing, and it is read from what a
    TerminalPick *is*: a carrier with a ``score`` attribute answering a real
    number or ``-inf``.  A NaN is refused — it compares false against
    everything and would drop out of every argmax, reading as "no scoring"
    (the same reason feature 249 refuses to score a NaN and migration 0109's
    ``score REAL NOT NULL`` forbids a null one).  An infinity is the miss,
    persisted as the floor — never refused, because the miss is the row an
    operator counts.  A carrier with no ``score`` is not a TerminalPick at
    all.
    """
    score = getattr(pick, "score", None)
    if score is None and not _has_score_attr(pick):
        raise ReplayScoreError(
            f"a replay score is persisted from feature 249's TerminalPick — "
            f"got {pick!r} ({type(pick).__name__}), which has no `score`. "
            "The row is shaped around the pair the terminal requirement "
            "answers — the pick (absent-able) and the score (always present) "
            "— and a carrier with no score answers no completed scoring; hand "
            "the TerminalPick the requirement produced (feature 255, docs "
            "§10.1)"
        )
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ReplayScoreError(
            f"a replay score is a real number or -inf — got {score!r} "
            f"({type(score).__name__}) from {pick!r}. The score is the row's "
            "reason for existing and the comparison's verdict, and a value "
            "that is not a number names no scoring; the miss is -inf, not a "
            "non-number (feature 249, docs §10.1)"
        )
    value = float(score)
    if math.isnan(value):
        raise ReplayScoreError(
            f"a replay score cannot be NaN — got {value!r} from {pick!r}. A "
            "NaN compares false against everything and would drop out of "
            "every argmax, reading as 'no scoring' rather than a score, which "
            "is the same fact feature 249 refuses to score and migration "
            "0109's `score REAL NOT NULL` forbids; the miss is -inf, which "
            "the comparison keeps (feature 255, docs §10.1)"
        )
    return value


def _committed_node_id(pick: Any) -> str | None:
    """The committed pick's node id — or None for the miss.

    A committing policy's pick is feature 222's CommittedPick, read through
    its one ``node_id`` — the node the policy committed to — and written as
    the row's ``committed_pick``.  A policy that emitted no pick (``pick is
    None``) writes None: the decision that was never made stays
    distinguishable from one that was (migration 0109's nullable
    ``committed_pick``).  The node id is read, not re-validated: CommittedPick
    validated it at construction, and a second statement here would be a
    second place the same law could drift.
    """
    carried = getattr(pick, "pick", None)
    if carried is None:
        # The miss: no pick was emitted.  Persisted as NULL, so the decision
        # that was never made stays distinguishable from one that was.
        return None
    node_id = getattr(carried, "node_id", None)
    if node_id is None:
        # A pick that is not a committed pick — a carrier with no node_id names
        # no node the policy committed to, and a committed_pick column holding
        # it would name a decision no node answers.  Refused, naming what
        # arrived.
        raise ReplayScoreError(
            f"the committed pick has no node id — got {carried!r} "
            f"({type(carried).__name__}) from {pick!r}. The row's "
            "committed_pick is the node the policy committed to (feature "
            "222's CommittedPick.node_id), and a pick with no node id names "
            "no node a row could record; hand the TerminalPick the "
            "requirement produced (feature 255, docs §10.1)"
        )
    return str(node_id)


def _has_score_attr(pick: Any) -> bool:
    """Whether the carrier answers a ``score`` at all — distinct from its value.

    A carrier whose ``score`` is ``None`` is a different fact from a carrier
    with no ``score`` attribute: the first answers the attribute (with a value
    this module refuses, since a null score is a scoring that did not happen),
    the second is not a TerminalPick at all.  ``getattr`` with a sentinel
    keeps the two apart, the same distinction feature 249's ``_ABSENT`` draws
    between a read that carried no ``pick`` and one that carried ``pick =
    None``.
    """
    return hasattr(pick, "score")


def _policy_version_of(policy_version: Any) -> str:
    """The policy version under test — a non-empty string.

    An id that names nothing writes a row no ``(policy, world)`` pair names,
    and a row that names no pair is the record of a scoring that did not
    happen.  Refused before the store is touched, naming the value.
    """
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ReplayScoreError(
            f"a replay score's policy version is a non-empty string — got "
            f"{policy_version!r} ({type(policy_version).__name__}). The row "
            "names the policy revision under test, and a version that is not "
            "a non-empty string writes a row no (policy, world) pair names — "
            "the record of a scoring that did not happen (feature 255, docs "
            "§10.1)"
        )
    return policy_version


def _world_id_of(world_id: Any) -> str:
    """The world the policy was replayed against — a non-empty string.

    The same law as the policy version: an id that names nothing writes a row
    no ``(policy, world)`` pair names.  Refused before the store is touched,
    naming the value.
    """
    if not isinstance(world_id, str) or not world_id.strip():
        raise ReplayScoreError(
            f"a replay score's world id is a non-empty string — got "
            f"{world_id!r} ({type(world_id).__name__}). The row names the "
            "world the policy was replayed against, and an id that is not a "
            "non-empty string writes a row no (policy, world) pair names — "
            "the record of a scoring that did not happen (feature 255, docs "
            "§10.1)"
        )
    return world_id


def _beta_of(beta: Any) -> float:
    """The beta the scoring was made at — a finite number.

    The row's beta field is required (migration 0109), and a beta that is not
    finite would be a hyperparameter no reader could reproduce the scoring
    under — an infinity is not a hyperparameter, it is a value outside the
    space the scoring was made in.  Refused before the store is touched.
    """
    if isinstance(beta, bool) or not isinstance(beta, (int, float)):
        raise ReplayScoreError(
            f"a replay score's beta is a finite number — got {beta!r} "
            f"({type(beta).__name__}). The beta is the hyperparameter the "
            "scoring was made at, and a value that is not a number names no "
            "scoring a reader could reproduce; the field is required "
            "(feature 255, docs §10.1)"
        )
    value = float(beta)
    if not math.isfinite(value):
        raise ReplayScoreError(
            f"a replay score's beta is a finite number — got {value!r}. The "
            "beta is the hyperparameter the scoring was made at, and an "
            "infinity is not a hyperparameter — it is a value outside the "
            "space the scoring was made in, which no reader could reproduce "
            "the scoring under; the field is required and finite (feature "
            "255, docs §10.1)"
        )
    return value


def _holdout_of(is_holdout: Any) -> bool:
    """The holdout flag — a bool, persisted as the row's holdout marker.

    A flag that is not a bool would be a holdout marker no reader could trust:
    the row records whether the scoring was made as holdout, and a non-bool
    (a truthy string, a non-zero int) is an answer the flag was never asked
    for.  Refused before the store is touched.
    """
    if not isinstance(is_holdout, bool):
        raise ReplayScoreError(
            f"a replay score's holdout flag is a bool — got {is_holdout!r} "
            f"({type(is_holdout).__name__}). The row records whether the "
            "scoring was made as holdout, and a flag that is not a bool is an "
            "answer the flag was never asked for — a truthy string or a "
            "non-zero int names no holdout decision; pass True or False "
            "(feature 255, docs §10.1)"
        )
    return is_holdout


# -- the store ---------------------------------------------------------------------------


def _row_id() -> str:
    """The row's own identity — a fresh uuid4, one per persisted scoring.

    The row is the record of one completed scoring, and one row per run is the
    feature's whole point: a fresh uuid4 per call keeps two runs of one
    ``(policy, world)`` pair as two rows, never one upserted onto the other —
    unlike feature 254's latency table, whose key is the snapshot instant and
    whose re-measurement at the same instant upserts.  Here there is no
    natural key: each run is its own row, and the id is that row's own name.
    """
    return str(uuid.uuid4())


def _open_store(database_url: str | None) -> sqlite3.Connection:
    """Open the relational store ``DATABASE_URL`` names.

    The member's own spelling of the open every store in this workspace
    performs: the URL comes from the argument or the one ambient the
    workspace's stores share (``DATABASE_URL``), a missing one is refused by
    name rather than by a bare error, and only ``sqlite:///`` speaks — the
    spec's single-machine allowance — with any other scheme refused loudly
    rather than silently mis-parsed, so a misrouted Postgres URL cannot hide
    behind a mysterious file.  The row space is created idempotently on
    connect (``CREATE TABLE IF NOT EXISTS``, the contract every store here
    states), so a fresh database and an existing one take one path and no
    migration step is needed for this member.  The caller owns the connection;
    use it as a context manager to commit.
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url:
        raise ReplayScoreError(
            f"no relational store configured: pass a database URL or set "
            f"{DATABASE_URL_ENV} to one (sqlite:///path/to/store.db on a "
            "single machine — docs §16's 'single Postgres metrics table', the "
            "simpler option the section defends at this scale). The replay "
            "score is persisted into that store, one row per run (feature "
            "255, docs §10.1)"
        )
    parsed = urlparse(url)
    if parsed.scheme != "sqlite":
        raise ReplayScoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "relational store speaks sqlite:/// (the spec's single-machine "
            "allowance), the same refusal every store in this workspace "
            "documents — a Postgres table arrives with the versioned "
            "migration member, and pretending to speak it here would hide a "
            "misrouted URL behind a mysterious file"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ReplayScoreError(
            f"the relational store's sqlite {DATABASE_URL_ENV} must not carry "
            f"a host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise ReplayScoreError(
            f"the relational store's sqlite {DATABASE_URL_ENV} carries no "
            "database path"
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    with connection:
        connection.executescript(_SCHEMA)
    return connection
