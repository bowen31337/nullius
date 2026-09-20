"""The shapes this member has to spell: the discovery tree and the replay pool.

app_spec.xml, "Leakage Tripwires", feature 131: *"System persists a tripwire
failure as poisoning the node together with its entire subtree."*  The word
doing the work in that sentence is **subtree**, and a subtree is not a thing a
verdict carries: a verdict knows the node it probed and nothing about the
discovery tree that node sits in.  So feature 131 is the first feature in this
category that has to reach *outside* the member — to the ``node`` table
``migrations/versions/0118_node_table.py`` creates and the self-referencing
``parent_id`` foreign key feature 97 puts on it — and this module is that
reach, plus the one normalization every node id in the package passes through.

**Feature 132 is the second reach, and it lands in the same place.**  Feature
131's sentence says the poisoned branch is *"excised from the replay pool"*,
and the pool is the ``replay_score`` table
``migrations/versions/0109_replay_score_and_policy_revision.py`` creates —
again a table outside this member, again owned by a member that does not exist
yet, and again restated here rather than imported for the reason above.  What
this module adds for it is the table's name, its eight columns and the DDL a
database the orchestrator has not migrated yet gets, so
:mod:`tripwires.excise` can read the pool it must refuse from.  The two
restatements sit in one module because they are one kind of fact — *the shape
of a store this member did not create but has to speak* — and because the
alternative, a second `layout`-shaped module per feature, would leave a reader
looking for the pool's shape in a file named after the tree.

**Why the tree's shape is restated here rather than imported.**  The tree
member does not exist yet (``packages/`` holds no ``tree``), and this member's
layering rule forbids importing another member even when one does arrive — the
tripwires run inside the frozen evaluator (architecture §5, "Immutable,
containerized, hash-pinned") and a member whose import pulls a second member is
a member whose determinism story (§12) has a moving part it cannot name.  So
the three names feature 131's recursion actually names — the table, the
self-referencing edge, the campaign scope — are pinned here, once, beside the
DDL a database without the table gets, for the reason feature 91's outcome
vocabulary is restated by the evaluator: a shared vocabulary spelled twice with
one provenance comment beats an import that couples two packages.

**The DDL is 0118's own five columns, verbatim, and not a sixth on this file's
authority.**  The migration that owns the table declares five structural
columns — ``id``, ``parent_id``, ``campaign_id``, ``theme_root``, ``depth`` —
and says in its own docstring that the other ``node`` columns belong to the
sibling column features 98 through 101 and are *not* its to create.  A member
that has to open a database the orchestrator has not migrated yet inherits that
same restraint: it creates the table the way 0118 creates it, five columns, and
adds only the one column *it* owns — ``poisoned_at``, the instant feature 131
marked the node.  That column is added by :mod:`tripwires.poison` through a
probe and an ``ALTER TABLE``, because a table created by the migration will not
have it and SQLite's ``ADD COLUMN`` carries no ``IF NOT EXISTS``; a table this
module creates carries it from the start.  Either way the result is a ``node``
table the migration would also accept, which is the property that makes the
store's own bootstrap safe to run against a real database.

**The dialect split is 0118's too, and it is the only one.**  ``DEFAULT
gen_random_uuid()`` is a syntax error in SQLite, whose ``DEFAULT`` grammar
accepts a function call only when it is parenthesised, so the UUID default is
translated per dialect exactly as the migration translates it — the same
RFC 4122 version-4 expression, built from ``randomblob``, with the variant and
version nibbles a v4 UUID must carry rather than whatever the random source
produced.  It is the **only** default in the schema, and the absence of a
second one is the decision worth stating: ``poisoned_at`` has none, deliberately
and unlike the ``created_at`` columns 0111 and the sibling stores give their own
tables.  A defaulted timestamp is right for *when a row came into being* and
exactly wrong for *when an irreversible act happened* — a ``DEFAULT now()`` on
``poisoned_at`` would stamp every node the discovery loop creates as already
poisoned, at the instant of its creation, and the replay pool would refuse the
whole campaign without a single tripwire firing.  ``NULL`` means *not poisoned*
and nothing else, so it can only be written by the act that poisons.

**The one node-id normalization.**  ``normalize_node_id`` below is
:mod:`nulloracle.assignment`'s function, restated rather than imported for the
reason above, down to the accepted inputs and the canonical output: a
:class:`uuid.UUID` or any text :func:`uuid.UUID` parses, returned as lowercase
hyphenated text.  Every node id in this package passes through it — the node a
verdict names, the parent an edge is walked over, the id a caller asks
``poisoned`` about — because they all join a column declared ``UUID NOT NULL
PRIMARY KEY``, and a mixed-case or braced spelling of one node would read as
two nodes in a set that decides whether a branch is replayed.

**What this module does not do.**  It does not walk, write or read.  It names
the trees' shapes and normalizes their keys; :mod:`tripwires.poison` is the
walk and the write and :mod:`tripwires.excise` is the pool's read and refusal,
and they are the only modules that open a connection.
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import TripwirePoisonError

__all__ = [
    "DATABASE_URL_ENV",
    "NODE_CAMPAIGN_COLUMN",
    "NODE_ID_COLUMN",
    "NODE_METRIC_COLUMN",
    "NODE_PARENT_COLUMN",
    "NODE_POISONED_COLUMN",
    "NODE_TABLE",
    "REPLAY_SCORE_COLUMNS",
    "REPLAY_SCORE_COMMITTED_PICK_COLUMN",
    "REPLAY_SCORE_CREATED_AT_COLUMN",
    "REPLAY_SCORE_ID_COLUMN",
    "REPLAY_SCORE_IS_HOLDOUT_COLUMN",
    "REPLAY_SCORE_POLICY_VERSION_COLUMN",
    "REPLAY_SCORE_SCORE_COLUMN",
    "REPLAY_SCORE_TABLE",
    "REPLAY_SCORE_WORLD_COLUMN",
    "STABILITY_COLUMNS",
    "STABILITY_TABLE",
    "dialect_of",
    "node_bootstrap_schema",
    "parsed_instant",
    "replay_pool_bootstrap_schema",
    "sqlite_path",
    "stability_bootstrap_schema",
    "validated_instant",
    "validated_node_id",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the evaluator's
#: five, the guard's, the verdict's), restated here so each store states its
#: own contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table feature 97 creates and feature 131 joins to.  Spelled once here
#: so the recursion, the bootstrap DDL and the column probe cannot drift apart
#: on what the discovery tree's store is called.
NODE_TABLE = "node"

#: The node's own key — the minted UUID ``parent_id`` points at, and the value
#: every ``node_id`` downstream resolves to.
NODE_ID_COLUMN = "id"

#: The self-referencing foreign key (``parent_id UUID REFERENCES node(id)``).
#: ``NULL`` for a root, and **the edge the subtree recursion follows**: a
#: subtree is exactly the transitive closure of this column from the failing
#: node.  It is the one column of the tree feature 131 actually needs, and the
#: one the recursion's correctness rests on.
NODE_PARENT_COLUMN = "parent_id"

#: The campaign that spawned the node — ``NOT NULL``, and the scope every tree
#: query in the system already carries (§9.1: "every tree query in the system
#: is already scoped to one campaign").  This module keeps that scope: a
#: recursion from a failing node never leaves the failing node's campaign, so
#: a campaign the orchestrator is mid-flight on cannot have a subtree marked
#: from another campaign's failure.
NODE_CAMPAIGN_COLUMN = "campaign_id"

#: The column feature 131 *adds* — when the tripwire failure marked this node.
#: It is not one of 0118's five and not one of 98–101's thirteen, because it
#: belongs to no earlier feature: 0118's docstring names ``created_at`` as the
#: kind of column that waits for a feature to name it, and this is that
#: circumstance.  ``TIMESTAMPTZ``/``TEXT`` by affinity, ``NULL`` until the node
#: is poisoned, and written by ``poison_node`` inside the same transaction as
#: the poison rows — so a node is never marked without the records that say why,
#: and the records are never written for a node left unmarked.
NODE_POISONED_COLUMN = "poisoned_at"

#: The Postgres default for an ``id`` column: the spec's own spelling, and the
#: reason a Postgres ``id`` needs no value supplied.  0118's constant, restated.
_POSTGRES_UUID_DEFAULT = "gen_random_uuid()"

# -- Feature 130: the node metric column ---------------------------------------

#: The ``node`` column feature 130 writes — 0114's seventh and last metric
#: column, ``perturb_stability REAL``, nullable with no default, named by
#: app_spec.xml feature 130's own sentence (*"persisting
#: perturbation_stability as a node metric"*).  Spelled once here for the
#: reason every column name in this module is: the probe, the ``ALTER TABLE``
#: and the ``UPDATE`` that write it must not be able to drift apart on what
#: the column is called, and 0114's own ``COLUMNS`` tuple is the migration's
#: to own, not this member's to import.
#:
#: **Why it is added by an ``ALTER`` and not by the bootstrap.**  The node
#: bootstrap above creates 0118's five columns plus ``poisoned_at``, which is
#: feature 131's column; this one deliberately does not join it, because the
#: restraint the bootstrap states is *what some feature of this member reads
#: or writes*, and the writer that owns this column brings it itself —
#: :mod:`tripwires.node_metric` probes ``PRAGMA table_info`` and issues the
#: ``ALTER TABLE ... ADD COLUMN perturb_stability REAL``, the same path
#: feature 131 paves for a table the migration made without its column.  The
#: end state either way is the table 0114 leaves: a node whose
#: ``perturb_stability`` is ``NULL`` until the lookback-jitter axis measures
#: it, which is the absent-versus-zero distinction the read refuses to blur.
NODE_METRIC_COLUMN = "perturb_stability"

# -- Feature 132: the replay pool's shape --------------------------------------

#: The table feature 132 excises from — *"the replay pool"* in app_spec.xml's
#: sentence and in §C6's (*"poisoned ... and its entire subtree, which is
#: excised from the replay pool"*).  ``0109`` creates it and the replay member
#: (features 245-255) is its writer; this member reads it, so the name is
#: pinned here the way the tree's three names are.
REPLAY_SCORE_TABLE = "replay_score"

#: The score row's own key.  Needed here for the reason every key is: a report
#: of *which* scores a branch contributed has to name them, and an excision
#: that could not say which rows it rejected would be unauditable.
REPLAY_SCORE_ID_COLUMN = "id"

#: **The column the whole feature turns on.**  ``replay_score.committed_pick``
#: is the policy's decision on the world that row scored — *"the ``committed_pick``
#: the policy would have made"*, in ``0109``'s own words — and it is the one
#: thing in the pool that points at the discovery tree.  A poisoned node's
#: scores are the rows whose committed pick *is that node*, so this column is
#: the join between §C6's two halves: the tree feature 131 marks and the pool
#: feature 132 must refuse.
#:
#: ``0109`` declares it nullable and says why — a candidate scored but not
#: selected has no committed pick, and a fabricated nil would read as a real
#: trade — which is a fact this module has to respect rather than repair: a
#: ``NULL`` pick names **no** node, so it can never match a poisoned one.  The
#: refusal is therefore never over a ``NULL``-pick row, and that is correct:
#: those rows contributed no node to the branch.
REPLAY_SCORE_COMMITTED_PICK_COLUMN = "committed_pick"

#: The policy revision the row scored.  Read by :mod:`tripwires.excise` for
#: one purpose only — a report of the excised branch names the revisions whose
#: evidence was rejected, so an operator can see *which* policy versions' scores
#: a poisoning cost, rather than a bare count.
REPLAY_SCORE_POLICY_VERSION_COLUMN = "policy_version"

#: The stored world the policy was replayed against.
REPLAY_SCORE_WORLD_COLUMN = "world_id"

#: The score the row carries — the number §C5's dreaming loop aggregates.
REPLAY_SCORE_SCORE_COLUMN = "score"

#: The 70/30 world holdout flag (``0109``: ``is_holdout BOOLEAN NOT NULL
#: DEFAULT FALSE``).  Read for the same reporting reason as the policy version:
#: a tournament's holdout half is what the selection is *judged* on, so an
#: operator reading an excision needs to know how much of it was holdout.
REPLAY_SCORE_IS_HOLDOUT_COLUMN = "is_holdout"

#: When the row was written (``0109``: ``TIMESTAMPTZ NOT NULL DEFAULT NOW()``).
REPLAY_SCORE_CREATED_AT_COLUMN = "created_at"

#: ``replay_score``'s columns, in the order ``0109`` declares them and the
#: order :func:`replay_pool_bootstrap_schema` writes them.  Spelled once for
#: the reason the tree's five are: the DDL, the statement that counts and any
#: statement that reads a column by name must not drift apart on what the
#: pool's row is made of.
REPLAY_SCORE_COLUMNS = (
    REPLAY_SCORE_ID_COLUMN,
    REPLAY_SCORE_POLICY_VERSION_COLUMN,
    REPLAY_SCORE_WORLD_COLUMN,
    "beta",
    REPLAY_SCORE_SCORE_COLUMN,
    REPLAY_SCORE_COMMITTED_PICK_COLUMN,
    REPLAY_SCORE_IS_HOLDOUT_COLUMN,
    REPLAY_SCORE_CREATED_AT_COLUMN,
)

#: The SQLite spelling of ``NOW()``, and ``0109``'s own expression: an ISO-8601
#: UTC timestamp string, the textual twin of Postgres's ``timestamptz``.  The
#: **outer** parentheses are load-bearing and are the whole reason this is a
#: separate constant from the call's own: SQLite's ``DEFAULT`` grammar accepts a
#: function call only when the entire expression is parenthesised, so
#: ``DEFAULT strftime(...)`` — which looks right and is the shape the migration's
#: prose describes — is a syntax error, and a single missing pair took the whole
#: ``CREATE TABLE`` down with it.
_SQLITE_NOW_DEFAULT = "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"

#: The SQLite equivalent — 0118's expression, verbatim: an RFC 4122 version-4
#: UUID built from ``randomblob``.  The surrounding parentheses are required,
#: because SQLite's ``DEFAULT`` grammar accepts a function call only when it is
#: parenthesised, which is precisely why the spec's ``gen_random_uuid()`` is a
#: syntax error there.
_SQLITE_UUID_DEFAULT = (
    "(lower("
    "hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || "
    "substr(hex(randomblob(2)), 2) || '-' || "
    "substr('89ab', abs(random()) % 4 + 1, 1) || "
    "substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6))"
    "))"
)


def _uuid_default(dialect: str) -> str:
    """The ``id`` column default for ``dialect`` — 0118's one dialect split.

    An unknown dialect gets the Postgres spelling, which is the spec's: a
    caller running something else is off the documented path, and silently
    handing it a SQLite expression would hide that.
    """
    return _SQLITE_UUID_DEFAULT if dialect == "sqlite" else _POSTGRES_UUID_DEFAULT


def _sqlite_now_default(dialect: str) -> str:
    """The ``created_at`` default for ``dialect`` — 0109's second dialect split.

    Paired with :func:`_uuid_default`, and for the same grammar reason: SQLite
    accepts a function call in a ``DEFAULT`` clause only when it is
    parenthesised, so ``NOW()`` is a syntax error and the ISO-8601 UTC string
    ``strftime`` produces is its textual twin.  An unknown dialect gets the
    spec's ``NOW()``, which is Postgres and is what production runs.
    """
    return _SQLITE_NOW_DEFAULT if dialect == "sqlite" else "NOW()"


def node_bootstrap_schema(dialect: str = "other") -> str:
    """The DDL that brings a database without a ``node`` table to this member's shape.

    One ``CREATE TABLE IF NOT EXISTS``, 0118's five structural columns in the
    order the migration names them, plus the one column this member owns —
    ``poisoned_at``.  Returned as text rather than executed so the DDL is
    inspectable, which is the property that makes it reviewable at all, and so
    a test can assert the shape without a database.

    The restraint is 0118's and it is stated there rather than here: the
    identity, provenance and authoring-model triples and the seven metrics
    belong to the sibling column features 98 through 101, and a bootstrap that
    invented them would be this member legislating a schema three features
    short of it.  What is created is exactly what the recursion reads
    (``id``, ``parent_id``, ``campaign_id``) and what this feature writes
    (``poisoned_at``), plus the two structural columns the migration's own
    ``NOT NULL`` requires a writer to supply.

    ``IF NOT EXISTS`` is deliberate and load-bearing: the table is very often
    already there — created by the migration, or by the guard store's own
    bootstrap, or by an earlier call to this function — and adopting the
    existing table is the contract every store in this workspace states.  What
    this function cannot do is add ``poisoned_at`` to a table that already
    exists without it; :meth:`~tripwires.poison.PoisonStore.ensure_schema`
    probes for the column and issues the ``ALTER TABLE``, because SQLite's
    ``ADD COLUMN`` carries no ``IF NOT EXISTS`` and there is no statement that
    both creates and migrates.
    """
    return f"""
    CREATE TABLE IF NOT EXISTS {NODE_TABLE} (
        {NODE_ID_COLUMN}          UUID NOT NULL PRIMARY KEY DEFAULT {_uuid_default(dialect)},
        {NODE_PARENT_COLUMN}      UUID REFERENCES {NODE_TABLE}({NODE_ID_COLUMN}),
        {NODE_CAMPAIGN_COLUMN}    UUID NOT NULL,
        theme_root     TEXT NOT NULL,
        depth          INT  NOT NULL,
        {NODE_POISONED_COLUMN}    TIMESTAMPTZ
    )
    """


def replay_pool_bootstrap_schema(dialect: str = "other") -> str:
    """The DDL that brings a database without a ``replay_score`` table to 0109's shape.

    Feature 132's other reach, and deliberately the *same* shape ``0109``
    creates — eight columns in the migration's order, the two dialect splits
    the migration makes (``DEFAULT gen_random_uuid()`` and ``DEFAULT NOW()``,
    neither of which SQLite's ``DEFAULT`` grammar accepts unparenthesised), and
    a ``NOT NULL`` on the primary key that the spec's bare ``UUID PRIMARY KEY``
    leaves implicit.

    **Why this member creates a table it does not own.**  The pool belongs to
    the replay member (features 245-255) and the migration owns its schema.  A
    store that has to *read* the pool against a database the orchestrator has
    not migrated yet has two options: fail on a missing table, or create the
    one the migration would.  The second is what every store in this workspace
    does, and it is safe for exactly the reason ``node_bootstrap_schema`` is:
    every statement is ``IF NOT EXISTS``, so a database the migration already
    built is left byte-for-byte as it was.

    **The restraint, and where the line is.**  Nothing here adds a column the
    migration does not declare — not even one feature 132 would find
    convenient. An ``excised_at`` column on ``replay_score`` is the tempting
    one and it is exactly wrong: it would be this member legislating a schema
    for a table three features short of it, and — worse — it would make the
    pool's refusal *stateful*, when the whole point of excising is that the
    refusal follows from facts already recorded (the node's mark, the row's
    pick) rather than from a flag this feature would then have to keep in step
    with them. Feature 132 writes nothing to this table.

    **The index is not here either**, and for once the absence is worth
    stating. ``0109``'s own ``INDEXES = ()`` says the migration creates none
    because a query plan for readers that do not exist yet is the wrong thing
    for a migration to invent; this member is now such a reader, and the
    statement it runs filters on ``committed_pick``. It still creates no index,
    and the reason is that the honest shape of feature 132's read is a *whole
    pool* read — the committed pick on every row, grouped by node — because a
    caller excising a branch has to know what it is rejecting, not merely
    whether a particular row is one. An index on a column no query can use is
    the same invention by a different author; when the replay member grows a
    read that wants one, that read's owner adds it.
    """
    return f"""
    CREATE TABLE IF NOT EXISTS {REPLAY_SCORE_TABLE} (
        {REPLAY_SCORE_ID_COLUMN} UUID NOT NULL PRIMARY KEY
            DEFAULT {_uuid_default(dialect)},
        {REPLAY_SCORE_POLICY_VERSION_COLUMN} TEXT NOT NULL,
        {REPLAY_SCORE_WORLD_COLUMN} UUID NOT NULL,
        beta                   REAL NOT NULL,
        {REPLAY_SCORE_SCORE_COLUMN} REAL NOT NULL,
        {REPLAY_SCORE_COMMITTED_PICK_COLUMN} UUID,
        {REPLAY_SCORE_IS_HOLDOUT_COLUMN} BOOLEAN NOT NULL DEFAULT FALSE,
        {REPLAY_SCORE_CREATED_AT_COLUMN} TIMESTAMPTZ NOT NULL
            DEFAULT {_sqlite_now_default(dialect)}
    )
    """


# -- Feature 129: the perturbation-stability figures ---------------------------

#: The table feature 129's persistence half writes — one row per node per
#: perturbation axis.  It is **not** a column on ``node`` and deliberately not
#: the ``perturb_stability`` column 0114 creates: that column is one number, and
#: the family §C6 declares is *four* axes (seed, window offset, universe
#: subsample, lookback jitter) whose figures are only meaningful side by side.
#: A single column would have the last axis to run overwrite the others, and the
#: operator asking *which perturbation moved this candidate* would be reading
#: whichever probe happened to be scheduled last.  So the shape is one row per
#: axis, and 130's writer is what fills the node column the migration declares.
STABILITY_TABLE = "tripwire_stability"

#: The columns of :data:`STABILITY_TABLE`, in the order the insert statement
#: names them and the order the reader unpacks them.  Spelled once so the write
#: and the read cannot drift apart on a column order — the failure a positional
#: ``SELECT *`` invites.
STABILITY_COLUMNS = (
    "node_id",
    "axis",
    "tripwire",
    "outcome",
    "rejected",
    "stability",
    "stability_threshold",
    "reference_sharpe",
    "rerun_sharpe",
    "reference_threshold",
    "seed",
    "rerun_seed",
    "subsample_fraction",
    "subsample_seed",
    "horizon",
    "measured_dates",
    "recorded_at",
)


def stability_bootstrap_schema(dialect: str = "other") -> str:
    """The DDL for :data:`STABILITY_TABLE` — feature 129's own table.

    ``IF NOT EXISTS``, like every bootstrap in this module, so a database that
    already carries the table is left byte-for-byte as it was.

    **One row per ``(node_id, axis)``, and the primary key is the decision.**
    The figures are comparable only as a set, so the table's unit is *a node's
    stability under one perturbation* rather than a node's stability.  The key
    makes a re-run of the same axis on the same node a refresh rather than a
    second figure — the property that lets a crash between the measurement and
    the write be repaired by running the feature again, and the same
    upsert-on-the-key discipline feature 131's audit table keeps for the same
    reason.

    **Why this member owns a table for a metric the migration already names.**
    ``perturb_stability`` is 0114's column and feature 130 is its writer: §C6's
    *"persisting perturbation_stability as a node metric"* is that feature's
    sentence, not this one's.  Feature 129's sentence says *"persisting the
    subsample stability figure"* — the figure, not a node metric — and the
    figure is one of four.  Writing it into the node column here would be this
    feature legislating which of the four axes the single column means, three
    features before the one that decides it.

    The columns carry the verdict's own terms, so the decision is re-derivable
    from the row alone: both statistics, the bar the figure is measured in, the
    configured bar it was judged against, the seeds and the horizon and the date
    count.  ``rerun_seed`` is nullable because an axis whose perturbation is not
    a seed has none — 128 perturbs a window offset, 130 a lookback — while this
    axis leaves it ``NULL`` and carries ``subsample_seed`` instead.  ``NULL``
    means *this axis perturbs no such knob* and nothing else, which is the
    absent-versus-zero distinction the member's other schemas keep.
    """
    return f"""
    CREATE TABLE IF NOT EXISTS {STABILITY_TABLE} (
        node_id            TEXT NOT NULL,
        axis               TEXT NOT NULL,
        tripwire           TEXT NOT NULL,
        outcome            TEXT NOT NULL,
        rejected           INTEGER NOT NULL,
        stability          REAL NOT NULL,
        stability_threshold REAL NOT NULL,
        reference_sharpe   REAL NOT NULL,
        rerun_sharpe       REAL NOT NULL,
        reference_threshold REAL NOT NULL,
        seed               INTEGER NOT NULL,
        rerun_seed         INTEGER,
        subsample_fraction REAL,
        subsample_seed     INTEGER,
        horizon            INTEGER NOT NULL,
        measured_dates     INTEGER NOT NULL,
        recorded_at        TEXT NOT NULL,
        PRIMARY KEY (node_id, axis)
    )
    """


def validated_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    Accepts a :class:`uuid.UUID` or any text :func:`uuid.UUID` parses, and
    returns the lowercased hyphenated rendering.  The same normalization — and
    the same reasoning — :func:`nulloracle.assignment.normalize_node_id` and
    :func:`ledger.record._validated_uuid` apply, because all three columns join
    the tree store's ``node.id UUID PRIMARY KEY`` and a mixed-case key would
    make one node look like two: here, in the set that decides whether a branch
    is replayed.

    A malformed id is refused with :class:`~tripwires.TripwirePoisonError`
    rather than stored.  A poison row keyed by something that cannot join the
    tree is a mark on no node: the ``UPDATE`` beside it would match nothing,
    the subtree recursion would terminate at once, and the caller would be told
    a branch was poisoned while the tree walk went on replaying it — the exact
    "looks done, is not" failure this category exists to prevent.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise TripwirePoisonError(
                "a node id must be a non-empty UUID, got an empty string; a "
                "poison record keyed by nothing names no node, and the subtree "
                "it claims to have poisoned cannot be counted"
            )
        try:
            return str(uuid.UUID(text))
        except (ValueError, AttributeError, TypeError) as exc:
            raise TripwirePoisonError(
                f"node id {value!r} is not a UUID: {exc}"
            ) from exc
    raise TripwirePoisonError(
        f"a node id must be a UUID or its text spelling, got {value!r} "
        f"({type(value).__name__}); node ids join the tree store's `node.id` "
        "column, and a key that cannot join it names no node in the tree"
    )


def validated_instant(value: Any) -> dt.datetime:
    """Validate a timestamp, returning it timezone-aware in UTC.

    A naive datetime is refused rather than assumed to be UTC: the instant a
    node was poisoned is read back beside instants every other store wrote, and
    a naive one silently reinterpreted as local time would place a poisoning
    hours away from the trial that caused it — an ordering a reader would trust
    and be wrong by.  An aware datetime is converted, not relabelled, so the
    value stored is the same instant the caller meant however they spelled it.
    """
    if not isinstance(value, dt.datetime):
        raise TripwirePoisonError(
            f"a poisoning instant must be a datetime, got {value!r} "
            f"({type(value).__name__})"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise TripwirePoisonError(
            f"a poisoning instant must be timezone-aware; got the naive "
            f"datetime {value.isoformat()!r}. A naive stamp would be read back "
            "as an instant the store never meant, placing a poisoning out of "
            "order against the trial that caused it"
        )
    return value.astimezone(dt.UTC)


def parsed_instant(value: Any) -> dt.datetime:
    """Parse a stored instant, refusing one that is not a usable stamp.

    SQLite hands back the text this member's stores wrote (``isoformat()``) or,
    for a row a migration's own default produced,
    ``strftime('%Y-%m-%dT%H:%M:%fZ')`` — both of which
    :func:`datetime.fromisoformat` parses, the second's ``Z`` being the UTC
    designator Python accepts.  A :class:`datetime.datetime` passes through
    unchanged, so a caller holding the value feature 131 returned from
    :meth:`~tripwires.poison.PoisonStore.poisoned` can hand it back.

    An unparseable value is refused by name rather than returned as a string: a
    caller comparing a string against a datetime would find them unequal always,
    and a poisoning trail that silently compares as "not poisoned" is worse than
    one that stops.

    Here rather than in either feature module because *two* of them parse stored
    instants — feature 131's mark and feature 132's ``replay_score.created_at``
    — and the one-provenance rule this member states for its vocabularies
    applies to a parser as much as to a column name.  The error is
    :class:`~tripwires.TripwirePoisonError`, the base refusal for a stored
    value that cannot be read; :mod:`tripwires.excise` catches it and re-raises
    under its own type, because a caller in the replay path catches that one.
    """
    if isinstance(value, dt.datetime):
        return value
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise TripwirePoisonError(
            f"the stored poisoning instant {value!r} could not be parsed: "
            f"{exc}; the trail's ordering against the trial that caused it "
            "rests on this column, and a stamp no reader can parse is an "
            "ordering nobody can check"
        ) from exc
    return parsed


def sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract —
    and refused by name for anything else, because the poison store speaks
    ``sqlite:///`` and pretending otherwise would hide a misrouted URL behind a
    mysterious file.  A pathless (in-memory) URL is refused too, and for a
    reason specific to this feature: an in-memory database dies with the
    connection that opened it, so a subtree marked poisoned there would be
    unmarked the moment the caller looked — a branch that looks poisoned while
    the replay pool still holds every score it contributed.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise TripwirePoisonError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "poison store speaks sqlite:/// (the spec's single-machine "
            f"allowance); point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise TripwirePoisonError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise TripwirePoisonError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened it, "
            "and a subtree marked poisoned there is unmarked the moment the "
            "caller looks — a branch that reads as poisoned while the replay "
            "pool still holds every score it contributed"
        )
    return Path(path)


def dialect_of(connection: object) -> str:
    """Name the dialect of a DBAPI connection, conservatively.

    0118's own function, restated: only ``sqlite`` is recognised positively and
    everything else is reported as ``other``, receiving the spec's Postgres
    spelling — the production target is Postgres (§9.1), and an unrecognised
    driver is far likelier to be Postgres-compatible than to share SQLite's
    ``DEFAULT`` grammar.
    """
    module = type(connection).__module__ or ""
    if module.split(".")[0] == "sqlite3":
        return "sqlite"
    return "other"
