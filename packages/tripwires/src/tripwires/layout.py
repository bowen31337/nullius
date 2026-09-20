"""The discovery tree's shape, as this member has to spell it — feature 131.

app_spec.xml, "Leakage Tripwires", feature 131: *"System persists a tripwire
failure as poisoning the node together with its entire subtree."*  The word
doing the work in that sentence is **subtree**, and a subtree is not a thing a
verdict carries: a verdict knows the node it probed and nothing about the
discovery tree that node sits in.  So feature 131 is the first feature in this
category that has to reach *outside* the member — to the ``node`` table
``migrations/versions/0118_node_table.py`` creates and the self-referencing
``parent_id`` foreign key feature 97 puts on it — and this module is that
reach, plus the one normalization every node id in the package passes through.

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
the tree's shape and normalizes its keys; :mod:`tripwires.poison` is the walk
and the write, and it is the only module that opens a connection.
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
    "NODE_PARENT_COLUMN",
    "NODE_POISONED_COLUMN",
    "NODE_TABLE",
    "dialect_of",
    "node_bootstrap_schema",
    "sqlite_path",
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
