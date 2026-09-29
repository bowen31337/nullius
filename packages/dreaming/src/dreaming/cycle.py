"""The cycle freeze — feature 270, and the member's whole subject.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 270: *System rejects a
replay pool mutation during a dreaming iteration, holding the pool fixed for
the cycle.*  docs/alpha-engine-prd.md §C5 states the rule the sentence exists
to enforce, and it states it as the *first* clause of the loop rather than as a
caveat on it:

    Per outer iteration: **hold the replay pool fixed**, run ``M`` code
    revisions of ``π``, evaluate each on every stored tree, select the argmax
    under §7.

and §12.1 says why the qualifier is load-bearing rather than tidy:

    The dreaming loop **overfits its own replay pool**.  The paper's guarantee
    ``V^{m★} ≥ V^0`` holds on the *fixed history*; selecting the max over ``M``
    revisions scored on a handful of worlds is the same multiple-testing
    problem one level up.

**The guarantee is a guarantee about a fixed history, so the history must
actually be fixed.**  That is the whole of this module.  §10.3.1's bar — the
meta-level selection discipline, and the *paired* continuous statistic that
feature 280 will apply to the winning revision, *"same policy pair on the same
worlds"* — is only meaningful if both policies in the pair saw the same worlds
with the same scores.  A pool that grew between the first candidate's replay
and the ``M``-th's would make the comparison a comparison of two different
tournaments, and nothing in the result would look wrong: the scores would
still be finite, the argmax would still be some candidate, and the selection
bar would still be met or not.  The architecture's §12 — the determinism
contract — names exactly this shape of failure in its canary subsection,
*"Non-determinism does not announce itself; it just slowly makes every
conclusion wrong"*, beside the ``halt_dreaming()`` that a broken replay
determinism triggers; and this feature is the part of that contract which
guards the dreaming loop's own input.

Citations here are the workspace's convention rather than one document's:
``§C5`` and ``§12.1`` are ``docs/alpha-engine-prd.md`` (the loop and its pool
regime), while bare ``§10.3.1`` and ``§12`` are
``docs/nullius-tech-architecture.md`` (meta-level selection discipline; the
determinism contract, whose §12 every store in this workspace already cites
for its ordering rule).  The two documents number sections independently and
``§12`` means a different thing in each, so a reference here names the
architecture's unless it is one of the two PRD sections named above.

**One existing member obeys this rule already, and says so.**  ``tripwires.
excise`` (feature 132) exists to *"excise a poisoned subtree from the replay
pool"*, and it takes the one design decision that makes it compatible with
this feature: it never deletes a row.  Its module docstring states the reason
in this feature's own terms — *"Feature 270 forbids exactly that mutation.  An
excision that deleted rows would be a pool mutation, and it would have to
reconcile itself with a rule that says the pool must not move while a cycle is
walking it — a contradiction this design does not have, because a read-time
refusal moves nothing."*  ``canary._void`` (feature 144) makes the identical
call for the identical reason, and ``bootstrap._census`` (feature 186) reads
the pool's two halves without writing either.  So three members were built to
this rule before this module existed; what this module adds is the **refusal**
— the enforcement, and the account of which cycle is holding what.

The design
----------

**The freeze is a row, and the rule is a trigger.**  :class:`CycleFreeze`
writes one row into this member's own ``pool_freeze`` table, holding the
iteration id, the instant it opened, and the pool's **commitment** at that
moment.  While that row is un-released, a set of ``BEFORE INSERT``/``UPDATE``/
``DELETE`` triggers over the pool's two tables consults it and aborts the
statement.

**Why a trigger rather than a Python guard.**  A guard that lived only in a
wrapper method would be a rule the writer can walk around by opening the
database itself — and the pool's writers are *not* all this member's callers.
Feature 132's excision reads the pool, the replay member (features 245-255)
writes it, and an operator bisecting a deployment's pool has a ``sqlite3``
shell.  A rule about a *store* has to live in the store.  So the triggers are
the enforcement and the Python wrapper is only a translation: it turns the
database's abort into :class:`~dreaming.errors.PoolFrozenError` with the
iteration id spelled out, so the caller that used this member's API gets a
message it can read, and the caller that bypassed it is still refused — by the
database, with the raw abort.

**The one mutation a trigger cannot refuse, and what is done about it.**  A
``BEFORE ... FOR EACH ROW`` trigger fires per row, and DDL is not a row: no
trigger this member installs is consulted when a pool table is dropped,
renamed, or rebuilt.  ``bootstrap`` does exactly that in its own schema
evolution — copy the table, ``DROP TABLE bootstrap_world``, rename the copy
back — and the consequence was measured rather than reasoned about: the three
``bootstrap_world`` guards are then gone from ``sqlite_master``, the rows are
byte-identical, the commitment still compares **equal**, and every subsequent
write to the pool succeeds while the iteration still believes its history is
fixed.  That is feature 270's failure arriving without announcing itself.

So the disarm is closed from two sides, and neither is a trigger:

* :func:`missing_guards` reads the trigger names back out of ``sqlite_master``,
  and :meth:`CycleFreeze.verify` refuses with :data:`UNGUARDED_CODE` when an
  open hold's guards are not over the pool — checking the database **as found**
  rather than healing it first, because a verify that repaired what it was
  asked to judge would answer ``True`` about a pool it had just un-disarmed.
* :meth:`CycleFreeze.guard` heals on the way in (:meth:`_connect` runs
  :meth:`ensure_schema`), so a write through this member's own seam re-arms the
  pool and is then refused by the guard it just restored.

The residual case is a *foreign* connection that performs DDL and then writes
before this member next touches the database, and it is stated here rather than
papered over: the hold detects it at the next ``verify()``, not at the write.
Closing that door as well would need an authorizer callback or a filesystem
lock, and neither is a rule about the *pool* — the workspace's own answer to
"the store's contents were changed by someone else" is the canary and the
commitment, which is what this member already ships.

**What is written, and what is deliberately not.**  ``pool_freeze`` is this
member's own table and the only table it creates; it is created idempotently
beside the one module that writes it, the same member-owned-table stance
:mod:`canary._halt` takes for ``canary_dream_halt`` and :mod:`tripwires.poison`
takes for its marks.  The pool's own two tables — ``replay_score`` (migration
``0109``) and ``bootstrap_world`` (feature 188's, and feature 191's widened
shape) — are **never written by this member**, not even to create them.  That
restraint is the same one :mod:`tripwires.excise` states for its ``0109``
bootstrap and for the same reason: a member that created the pool's tables
would be legislating a schema three features short of it.  What this member
does need is to know what the pool's tables *are called* — one constant each,
spelled here with its provenance — because a trigger cannot be written over a
table whose name is not known.

**The commitment, and why the freeze is not merely a flag.**  A boolean
"frozen" would make the rule a promise.  :attr:`CycleFreeze.commitment` is a
digest over the pool's *membership* — the ``replay_score`` keys and the
``bootstrap_world`` world ids, in a total order — and :meth:`CycleFreeze.
verify` re-reads it and compares.  Two things follow, and both are properties
the bar feature 280 applies needs:

* the commitment is a **pure function of the pool's contents**, so an
  unchanged pool re-commits to the identical digest in any process, and the
  freeze's own record is reproducible rather than incidental; and
* a pool that moved *anyway* — triggers dropped, a database restored from
  backup, a table swapped by hand — is **detected** rather than assumed away,
  which is what makes "held fixed" an observable claim.

It is a digest over *membership and not over scores*, deliberately.  A score
is what the cycle itself is in the business of writing: the replay member
writes one ``replay_score`` row per ``(policy, world)`` pair as it evaluates
each candidate, and those rows are the cycle's *output*, not its input.  A
commitment that folded scores in would make every candidate's own evidence
count as a mutation of the fixed history, which would refuse the loop its own
work.  What must not move is *which worlds the tournament is held over* — §C5's
"every stored tree", §10.3.1's *"every candidate revision against every stored
world"* — and that is exactly what the commitment covers.

**The window, and what "during" means.**  §C5's rule scopes to *one outer
iteration*: the pool is held from the moment the iteration opens until the
moment it closes, and between iterations it is free again — which is what lets
the campaign loop add a completed campaign
(:func:`discovery.manifest.admit_completed_campaigns`, feature 243) and lets a
new campaign's tree join the pool.  So the freeze is explicitly
**open-then-release**, and a released freeze stays in the table as a record
rather than being deleted: an operator asking *when was the pool held, and by
which cycle?* is asking a question the table answers, and a row that vanished
on release could not.  The table's own partial unique index is what keeps §12.1's
*one cycle at a time* structural — at most one row may be open, so a second
hold is refused by the database rather than by a convention of this module's
callers.

Stdlib only, and import-cheap: ``hashlib``, ``sqlite3``, ``datetime``,
``contextlib`` and ``urllib.parse``; no third-party import at module scope, so
the factory's scan — which imports this package to fire its ``@register`` —
pays nothing for the freeze.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import FreezeRequestError, PoolFrozenError
from .layout import (
    DATABASE_URL_ENV,
    POOL_TABLES,
    REPLAY_SCORE_TABLE,
    WORLD_TABLE,
    pool_tables_present,
)

__all__ = [
    "DATABASE_URL_ENV",
    "FREEZE_CODE",
    "FREEZE_TABLE",
    "POOL_FREEZE_COMPONENT_NAME",
    "POOL_TABLES",
    "REPLAY_SCORE_TABLE",
    "UNGUARDED_CODE",
    "WORLD_TABLE",
    "CycleFreeze",
    "FreezeRecord",
    "cycle_freeze_schema",
    "expected_triggers",
    "missing_guards",
    "open_cycle_freeze",
    "pool_commitment",
    "sqlite_path",
]

#: The code a *held pool* refusal opens with — something tried to move a pool
#: an iteration is holding — so the rejection is greppable by the word that
#: names it.  Deliberately feature 270's word and not feature 275's
#: ``pool_too_thin``: this module's subject is a cycle that is *running* and
#: must not have its pool moved, and the ladder's floor is a precondition on a
#: run that has not started.
#:
#: Not the *only* code a :class:`~dreaming.errors.PoolFrozenError` carries —
#: :data:`UNGUARDED_CODE` is the other, for a hold whose enforcement has been
#: removed — but both words open a message of that one class, which is what
#: keeps the two catchable together and distinguishable by grep.
FREEZE_CODE = "pool_frozen"

#: The code the *disarmed* refusal opens with — a hold that is open but whose
#: guards are no longer over the pool.
#:
#: A second code rather than a sentence of the first because the repair is a
#: different act: ``pool_frozen`` means *the pool is held and something tried to
#: move it*, and the repair is to wait or to close the cycle; ``pool_unguarded``
#: means *the hold is open and nothing is enforcing it* — the guarantee feature
#: 270's sentence promises is absent — and the repair is to re-install the
#: guards or to restart the cycle, because a cycle that continues here is
#: reporting a fixed history it does not have.  A caller that caught only
#: :class:`~dreaming.errors.PoolFrozenError` still catches this, since the class
#: is :class:`~dreaming.errors.PoolFrozenError` and only the *word* differs —
#: which is the shape :data:`FREEZE_CODE`'s own docstring states for the
#: sibling code, one word that names the failure and greps out of a log.
UNGUARDED_CODE = "pool_unguarded"

#: The table this member owns: one row per hold on the replay pool, open or
#: released.  Member-owned and created lazily, never migrated in the shared
#: chain, for the reason :mod:`canary._halt` gives for its own halt table and
#: the pool's restated schema gives for its two: the table has one writer, this
#: module, so its shape is a fact about this feature rather than about the
#: database's history — and a chain edit would be an order-sensitive change to
#: files this member does not own.
#:
#: The pool's own table names — :data:`~dreaming.layout.REPLAY_SCORE_TABLE`,
#: :data:`~dreaming.layout.WORLD_TABLE`, :data:`~dreaming.layout.POOL_TABLES`,
#: :data:`~dreaming.layout.DATABASE_URL_ENV` — are **not** spelled here.
#: They are re-exported from :mod:`dreaming.layout`, which is the one module in
#: this member that states what the pool is called and where each name came
#: from; keeping a second copy here is the drift the whole workspace legislates
#: against for a vocabulary spelled twice.
FREEZE_TABLE = "pool_freeze"

#: The component name this member registers under.  Unprefixed, following the
#: ``discovery`` / ``ledger`` / ``artifacts`` precedent for a member's first and
#: only component, and spelled here once, and read by name through the
#: composed application (``create_app().get("dreaming")``).  ``dreaming`` sorts
#: after ``discovery`` and before ``evaluator``, so every existing adjacency
#: assertion over the name-sorted ``app.order`` is untouched.
POOL_FREEZE_COMPONENT_NAME = "dreaming"

#: The three DML operations a hold covers.  A trigger is created per operation
#: per table rather than one trigger over a mutating statement, because SQLite
#: has no such statement: ``BEFORE INSERT``, ``BEFORE UPDATE`` and
#: ``BEFORE DELETE`` are three separate trigger slots, and the guard has to be
#: written into each of them.  Spelled as a tuple so the DDL, the docstring and
#: the test that pins the count cannot drift on how many doors there are.
_POOL_OPERATIONS = ("INSERT", "UPDATE", "DELETE")

#: The row's column names, in declaration order — the one spelling of what a
#: freeze row is made of, shared by the DDL, the insert and the read-back so
#: the three cannot disagree on a column order, the failure a positional
#: ``SELECT *`` invites.
_ROW_COLUMNS = (
    "id",
    "iteration_id",
    "opened_at",
    "released_at",
    "commitment",
    "world_count",
)


def sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    Spelled here rather than imported from the member that also spells one, for
    the reason every store in this workspace spells its own: the refusal
    vocabulary is this member's (:class:`~dreaming.errors.FreezeRequestError`,
    not another feature's), and a URL this module cannot speak must be refused
    *by name* here rather than translated through a helper that raises someone
    else's error — the seam discipline the whole workspace states for error
    vocabularies.

    Non-``sqlite`` schemes are refused (the spec's single-machine allowance is
    what a stdlib store can speak), as is a URL carrying a host, and —
    load-bearing for this feature specifically — an in-memory database.  A hold
    written into ``:memory:`` dies with the connection that opened it, so the
    triggers would guard a database that no longer exists the moment the
    caller looks: an iteration would believe its pool was fixed while the pool
    it fixed had already gone, which is the one state this feature must make
    impossible rather than merely unlikely.  It is the identical refusal
    :func:`bootstrap._pool._sqlite_path` makes for its own store, made here for
    the freeze's own reason.
    """
    if not isinstance(database_url, str) or not database_url.strip():
        raise FreezeRequestError(
            f"{DATABASE_URL_ENV} must be a non-empty database URL — got "
            f"{database_url!r} ({type(database_url).__name__}); the hold lives "
            "in the database the replay pool lives in, and a value that names "
            "no database names no pool for it to hold"
        )
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise FreezeRequestError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "cycle freeze speaks sqlite:/// (the spec's single-machine "
            f"allowance); point {DATABASE_URL_ENV} at the sqlite database the "
            "replay pool already lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise FreezeRequestError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise FreezeRequestError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened it, "
            "so a hold written there would guard a pool that is already gone "
            "— an iteration would believe its history was fixed while the "
            "history it fixed no longer existed, which is the one state "
            "holding the pool fixed must make impossible"
        )
    return Path(path)


def validated_iteration_id(value: Any) -> str:
    """Check that ``value`` names a dreaming iteration, or refuse it.

    An iteration id is text and not blank.  It is the one *identity* a hold
    carries — the thing every refusal names so an operator can attribute a
    collision to a cycle — so a value that cannot name one records nothing a
    reader could act on: ``None``, a number, a blank string and an object
    whose ``str`` is a memory address are all refused rather than stringified
    into a row whose ``iteration_id`` would be a spelling nobody could match.
    """
    if not isinstance(value, str) or not value.strip():
        raise FreezeRequestError(
            f"a dreaming iteration is named by a non-empty string — got "
            f"{value!r} ({type(value).__name__}); the iteration id is how a "
            "freeze is attributed and how a refusal names the cycle that was "
            "walking the pool, and a hold that cannot say which cycle it is "
            "would leave an operator with a collision they could not place"
        )
    return value.strip()


def _validated_instant(value: Any) -> dt.datetime:
    """Check that ``value`` is a timezone-aware instant, or refuse it.

    The stamp a hold carries must be an aware datetime: a naive one would place
    a cycle's opening hours away from the process that opened it (in whatever
    zone the host happens to keep) and nothing would look wrong — the same
    reason :func:`bootstrap._pool.validated_instant` validates the instant its
    own rows are stamped with.
    """
    if not isinstance(value, dt.datetime):
        raise FreezeRequestError(
            f"a freeze instant is a datetime — got {value!r} "
            f"({type(value).__name__}); the stamp records when an iteration "
            "opened or released the pool, and a value that cannot name an "
            "instant records nothing"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise FreezeRequestError(
            f"a freeze instant must carry its timezone — got {value!r}; a "
            "naive datetime would place a cycle's opening hours away from the "
            "process that opened it, in whatever zone the host happens to "
            "keep, and nothing in the row would look wrong"
        )
    return value


def _stamp(instant: dt.datetime) -> str:
    """Render an aware instant as the row's ISO-8601 UTC, to the second.

    The textual twin of Postgres's ``timestamptz`` and the spelling every
    stamp in this workspace takes: UTC, second-truncated, ``Z``-suffixed, so
    two rows written in the same second of the same run carry the same text
    and a report ordering by ``opened_at`` orders by time rather than by
    string accident.
    """
    return _validated_instant(instant).astimezone(dt.UTC).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _parsed_instant(value: str) -> dt.datetime:
    """Read a row's stamp back into the aware instant it encodes.

    The inverse of :func:`_stamp`, and as strict: 3.12's ``fromisoformat``
    reads the ``Z`` suffix these stamps carry natively, and a value that does
    not parse at all is refused by name — a stamp the reader cannot
    reconstruct is a stamp the row should never have carried.  It is a
    :class:`~dreaming.errors.PoolFrozenError` rather than a
    :class:`~dreaming.errors.FreezeRequestError` because by the time it is
    read the row is *in the store*: the malformed value is a fact about the
    pool's own record, not about an ask a caller made.
    """
    try:
        return dt.datetime.fromisoformat(value)
    except (AttributeError, ValueError) as refusal:
        raise PoolFrozenError(
            f"{FREEZE_CODE}: a recorded freeze stamp must be ISO-8601 with a "
            f"timezone — got {value!r}; the stamp is part of the pool's hold "
            "history and a value that cannot be read back is one that was "
            "never written by this member"
        ) from refusal


#: One sentence, spelled once, said by both ends of the refusal.
#:
#: There are two places a blocked write is described — the database's own
#: abort, which a writer that bypassed this member reads, and
#: :meth:`CycleFreeze.guard`'s translation, which a writer that used this
#: member reads — and this workspace's standing rule is that a vocabulary
#: spelled twice says two different things.  So both are this template with the
#: ``{holder}`` slot filled: ``an iteration`` from the trigger, and the
#: *named* iteration from the translation.  The trigger's version is the
#: floored one — a SQLite trigger body cannot interpolate a row's value into a
#: message (see :func:`_guard_trigger`) — and the translation's version is that
#: same sentence with the holder this member can go and read.
_GUARD_TEMPLATE = (
    f"{FREEZE_CODE}: cannot {{operation}} {{table}} while {{holder}} holds the "
    "replay pool fixed for the cycle"
)

#: The holder spelling the *trigger* uses, since it cannot name one.
_TRIGGER_HOLDER = "an iteration"


def _guard_trigger(table: str, operation: str) -> str:
    """The DDL for one door of the hold — one table, one operation.

    ``CREATE TRIGGER IF NOT EXISTS`` and ``BEFORE``, deliberately:

    * **``IF NOT EXISTS``** so re-installing the guard is idempotent, which is
      what makes :meth:`CycleFreeze.ensure_schema` safe to run against a
      database this member already prepared — the same contract every store in
      this workspace states for its own DDL; and
    * **``BEFORE``** so the statement is aborted *before* it runs rather than
      rolled back after.  An ``AFTER`` trigger would let the write happen and
      then raise, which on a delete would already have removed the row the
      abort is supposed to protect.

    The ``WHEN`` clause is the hold test and it is a *table read* rather than a
    variable: the guard is stateful on purpose, because the state it reads —
    *is an iteration holding the pool?* — is the fact the refusal is about.
    It is a correlated-free ``EXISTS`` over a table whose open row is unique by
    its own partial index, so the planner has one row to find or none.

    **The message is a literal, and that is a SQLite constraint rather than a
    choice.**  ``RAISE(ABORT, ...)`` accepts a string *literal* and nothing
    else: an expression in that argument position — including the obvious
    ``'prefix ' || (SELECT iteration_id ...) || ' suffix'`` — is a ``near
    "||": syntax error`` at ``CREATE TRIGGER`` time, not a message that goes
    unbuilt at run time.  So the trigger cannot name the holding iteration; it
    says ``an iteration`` and the *Python* side names it, which is exactly the
    division of labour :meth:`CycleFreeze.guard` performs.  The message is
    still composed here in Python and inlined as a repr'd literal, so the
    sentence comes from :data:`_GUARD_TEMPLATE` and single quotes in it are
    escaped for SQL rather than hoped away.
    """
    message = _GUARD_TEMPLATE.format(
        operation=operation.lower(), table=table, holder=_TRIGGER_HOLDER
    )
    literal = message.replace("'", "''")
    return f"""
CREATE TRIGGER IF NOT EXISTS {_trigger_name(table, operation)}
BEFORE {operation} ON {table}
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM {FREEZE_TABLE} WHERE released_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, '{literal}');
END;
"""


def _trigger_name(table: str, operation: str) -> str:
    """The name of one hold trigger — table and operation, in one stable word.

    Deterministic so ``CREATE TRIGGER IF NOT EXISTS`` reaches the same trigger
    on a re-install, and spelled from the table and the operation rather than
    hand-listed so a third pool table added to :data:`POOL_TABLES` gets its
    guard under a name no reader has to look up.
    """
    return f"pool_freeze_{table}_{operation.lower()}"


def expected_triggers() -> tuple[str, ...]:
    """The trigger names a *held* pool must carry — the guards, enumerated.

    Derived from :data:`POOL_TABLES` and :data:`_POOL_OPERATIONS` rather than
    hand-listed, so this answers whatever the install loop above installs and
    the two cannot drift into disagreeing about what a guarded pool looks like.
    """
    return tuple(
        _trigger_name(table, operation)
        for table in POOL_TABLES
        for operation in _POOL_OPERATIONS
    )


def missing_guards(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Which of a held pool's guards are absent — the disarmed hold, enumerated.

    **This exists because a trigger cannot guard against its own removal.**  A
    ``BEFORE INSERT/UPDATE/DELETE`` trigger fires per row; DDL is not a row, so
    no trigger this member installs is consulted when a pool table is dropped,
    renamed, or rebuilt.  ``bootstrap`` does exactly that in its own schema
    evolution — copy, ``DROP TABLE bootstrap_world``, rename the copy back —
    and the experiment is unambiguous: after that dance the three
    ``bootstrap_world`` guards are *gone* from ``sqlite_master``, the data is
    intact, the commitment is unchanged, and every subsequent write to the pool
    succeeds while the iteration still believes its history is fixed.

    That is :data:`UNGUARDED_CODE`'s whole case: the failure feature 270 exists
    to prevent, arriving without announcing itself.  Reading the trigger names
    back is how the hold notices, and it is a ``sqlite_master`` read — the
    cheap, read-only probe :func:`dreaming.layout.pool_tables_present` already
    makes — rather than a parse of the trigger bodies, because *which* guards
    are present is the fact that matters and *what they say* this module
    already knows.

    Takes an open connection, returns the absent names in a stable order, and
    answers an empty tuple for a fully guarded pool.  A driver that cannot
    answer propagates its own error untouched.
    """
    present = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    return tuple(name for name in expected_triggers() if name not in present)


#: The hold table's body.  Two things in it are load-bearing and are stated
#: here rather than left to reader inference:
#:
#: * ``id`` is the row's key, a hash of the iteration and the opening instant —
#:   see :meth:`CycleFreeze.open` — so the freeze is an identity an operator
#:   can name rather than a bare boolean; and
#: * the partial ``UNIQUE`` index over ``(1)`` where ``released_at IS NULL``
#:   makes *at most one open hold* a fact about the table rather than a
#:   convention of this module's callers.  The index is over a **constant
#:   expression**, which is deliberate: the constraint's subject is the table,
#:   not a column — *there is at most one open row* — and a constant gives
#:   SQLite a single index key to collide on.  §12.1's ladder runs one cycle at
#:   a time (feature 279 rotates one holdout split per cycle, feature 277 caps
#:   one revision count per cycle), so two open holds would be two cycles
#:   walking one pool with neither able to say which scores were whose; the
#:   index refuses the second at the database rather than trusting every writer
#:   to have checked first.
_TABLE_BODY = """
(
    id            TEXT    NOT NULL PRIMARY KEY,
    iteration_id  TEXT    NOT NULL,
    opened_at     TEXT    NOT NULL,
    released_at   TEXT,
    commitment    TEXT    NOT NULL,
    world_count   INTEGER NOT NULL
)
"""

_ONE_OPEN_INDEX = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS one_open_{FREEZE_TABLE} "
    f"ON {FREEZE_TABLE} ((1)) WHERE released_at IS NULL;"
)

_SCHEMA_HEADER = f"""
-- Feature 270: the dreaming loop's hold on the replay pool.  One row per
-- hold, open or released -- a released hold stays as a record rather than
-- being deleted, because "when was the pool held, and by which cycle?" is a
-- question an operator asks after the fact and a vanished row could not
-- answer it.
--
-- `commitment` is the pool's membership digest at the moment the hold
-- opened, and `world_count` its size: together they are what makes "held
-- fixed" an observable claim rather than a promise, because
-- `CycleFreeze.verify` re-reads both and compares.  Neither covers scores --
-- the replay member writes those as the cycle's *output*, and a commitment
-- that folded them in would count every candidate's own evidence as a
-- mutation of the fixed history.
CREATE TABLE IF NOT EXISTS {FREEZE_TABLE} {_TABLE_BODY};
"""


def cycle_freeze_schema() -> str:
    """The DDL that brings a database to a held pool.

    Three things, in one script, in this order: the hold table, the one-open
    index, and the six guards (two pool tables × three operations).

    Returned as text rather than executed, for the reason
    :func:`tripwires.layout.node_bootstrap_schema` is: the DDL is then
    inspectable — a reader can see which doors the hold covers without opening
    a database, and a test can assert the shape without one.

    **The guards are created unconditionally, including over tables the
    database does not hold yet.**  SQLite resolves a trigger's subject table at
    ``CREATE`` time, so installing a guard on an absent ``replay_score`` is an
    error rather than a no-op — which is the honest outcome rather than a
    limitation: a hold over a pool that does not exist would be a hold over
    nothing, and the caller that opened it should find out.  So the schema
    script is meant to be run against a database where the pool lives, and
    :meth:`CycleFreeze.ensure_schema` runs it that way.  The membership
    question — *is there a pool here to hold?* — is asked separately and
    answered by the hold's own commitment read, which is what feature 275's
    ladder gate will read through this member.
    """
    statements = [_SCHEMA_HEADER, _ONE_OPEN_INDEX]
    for table in POOL_TABLES:
        for operation in _POOL_OPERATIONS:
            statements.append(_guard_trigger(table, operation))
    return "\n".join(statements)


#: The insert a hold performs.  A plain ``INSERT`` with no ``ON CONFLICT`` arm,
#: deliberately: a second open hold is a *refusal* (see the one-open index), and
#: an upsert that silently rewrote the open row would be two cycles sharing one
#: hold — the state the index exists to make impossible rather than one this
#: statement should paper over.
_OPEN_INSERT = f"""
INSERT INTO {FREEZE_TABLE} ({", ".join(_ROW_COLUMNS)})
VALUES (?, ?, ?, ?, ?, ?)
"""

#: The release: the one write this module makes to an existing row, scoped to
#: the open hold so a released row can never be released twice into a later
#: stamp and so a release cannot land on a row that is already closed.
_RELEASE = f"""
UPDATE {FREEZE_TABLE}
   SET released_at = ?
 WHERE id = ?
   AND released_at IS NULL
"""

#: The open hold, if there is one — the read every guard translation and every
#: refusal names.
_SELECT_OPEN = (
    f"SELECT {', '.join(_ROW_COLUMNS)} FROM {FREEZE_TABLE} "
    "WHERE released_at IS NULL"
)

#: One hold by id, every column of it — the read the release reconciles
#: against.
_SELECT_ROW = (
    f"SELECT {', '.join(_ROW_COLUMNS)} FROM {FREEZE_TABLE} WHERE id = ?"
)

#: The pool's membership, in one total order — the two halves of the
#: commitment.  ``replay_score`` contributes its keys (``0109`` declares ``id``
#: a ``UUID NOT NULL PRIMARY KEY``, so the key is total and the ordering is
#: well defined on any database); ``bootstrap_world`` contributes its world
#: ids (feature 188's ``world_id TEXT NOT NULL PRIMARY KEY``).
#:
#: Ordered and read as text rather than counted, because the commitment must
#: be sensitive to *which* worlds the tournament is held over and to nothing
#: else — a reader that hashed a count would miss a world swapped for another
#: of the same size, which is exactly the "the pool moved but nothing looked
#: wrong" failure §12 names.
_MEMBERSHIP_QUERIES = {
    REPLAY_SCORE_TABLE: f"SELECT id FROM {REPLAY_SCORE_TABLE} ORDER BY id",
    WORLD_TABLE: f"SELECT world_id FROM {WORLD_TABLE} ORDER BY world_id",
}


def pool_commitment(path: Path) -> tuple[str, int]:
    """The pool's commitment — its membership digest and its size.

    A pure function of the pool's contents: two reads of an unchanged pool
    return the same pair in any process, which is the property that lets a
    hold *record* its commitment and later *check* it.  The digest hashes each
    table's membership in sorted order, table by table, with the table names
    folded in — so moving a world id from one pool table to the other is a
    different commitment rather than a collision, and a world *renamed* is a
    different commitment rather than a tie.

    The size is the two halves' sum, which is the same figure
    :meth:`bootstrap.BootstrapPool.world_count` reports for the bootstrap half
    plus the replay pool's own rows.  It is carried beside the digest rather
    than derivable from it because the number is what §12.1's ladder reads —
    *"below 20 worlds"*, *"between 20 and 50"* — and a hold that could say
    only "the pool did not move" without also saying how large the pool it
    held was would leave an operator unable to tell a held cycle over 45
    worlds from one over 5.

    A table the database does not hold is **refused by name**, not counted as
    empty: the two states are different facts.  A migrated deployment whose
    replay pool has no scores yet genuinely holds zero of them, while a
    database without the table has no replay pool in it at all — and a hold
    over a pool that is not there is a hold over nothing, which is the state
    this refusal makes visible rather than silently admits.  It is the
    identical distinction :func:`bootstrap._census.world_census` draws for its
    own absent ``replay_score``, and for the same reason: an invented zero
    reaches a precondition dressed as a measurement.
    """
    digest = hashlib.sha256()
    total = 0
    with closing(sqlite3.connect(path)) as connection:
        present = pool_tables_present(connection)
        missing = [table for table in POOL_TABLES if table not in present]
        if missing:
            raise PoolFrozenError(
                f"{FREEZE_CODE}: the database at {path} holds no "
                f"{' and no '.join(missing)} table, so there is no pool here "
                "to hold — an iteration that opened over it would be holding "
                "nothing while believing its history was fixed; point "
                f"{DATABASE_URL_ENV} at the database the replay pool lives in, "
                "or migrate it"
            )
        for table in POOL_TABLES:
            digest.update(f"{table}\n".encode())
            held = 0
            for (member,) in connection.execute(_MEMBERSHIP_QUERIES[table]):
                digest.update(f"{member}\n".encode())
                held += 1
            digest.update(f"={held}\n".encode())
            total += held
    return digest.hexdigest(), total


def _guard_message(operation: str, table: str, iteration_id: str | None) -> str:
    """The refusal a blocked write raises, with the holding iteration named.

    :data:`_GUARD_TEMPLATE` with the holder slot filled with the iteration this
    member read back from the open hold, plus the prose that says what to do
    about it — §C5's rule, §12.1's reason, and the repair.  Spelled from the
    same template as the trigger's literal so the two ends of one refusal
    cannot say different things, the failure this workspace states everywhere
    for a vocabulary spelled twice.

    The fallback spelling when no iteration could be read back is deliberate.
    A hold can be released between the writer's abort and this read — the
    window is real, however narrow — and in that race the statement *was*
    refused under a hold while the holder is now unknowable.  Saying so is more
    honest than either reporting the write as legal or inventing a holder; the
    refusal stands, attributed to nobody, and the operator can read the store's
    history (:meth:`CycleFreeze.holds`) to place it.
    """
    holder = (
        "an iteration this member could no longer read"
        if iteration_id is None
        else f"iteration {iteration_id!r}"
    )
    return (
        _GUARD_TEMPLATE.format(
            operation=operation.lower(), table=table, holder=holder
        )
        + " — docs/alpha-engine-prd.md §C5 holds the pool fixed for the whole "
        "of an outer iteration, and §12.1 states why the qualifier is "
        "load-bearing: the paper's V^{m★} ≥ V^0 guarantee is a guarantee about "
        "the *fixed history*, so a pool that moved between two candidates' "
        "replays would make §10.3.1's paired statistic a comparison of two "
        "different tournaments with nothing in the result looking wrong. Close "
        "the iteration (CycleFreeze.release) and write between cycles instead"
    )


class FreezeRecord:
    """One recorded hold on the replay pool — a row, as this member reads it.

    The row's five facts and nothing derived: which iteration held the pool,
    when it opened, when it was released (``None`` while it is open), the
    pool's commitment at the moment it opened and the pool's size then.

    Held as an immutable value rather than a live cursor because it is what
    every refusal and every audit of the loop is made of — a caller that read
    the open hold to attribute a collision must not be holding a handle a
    release can move under it — the same stance
    :class:`tripwires.excise.PoolScore` takes for the pool's own rows.
    """

    __slots__ = (
        "commitment",
        "id",
        "iteration_id",
        "opened_at",
        "released_at",
        "world_count",
    )

    def __init__(
        self,
        *,
        id: str,
        iteration_id: str,
        opened_at: str,
        released_at: str | None,
        commitment: str,
        world_count: int,
    ) -> None:
        self.id = id
        self.iteration_id = iteration_id
        self.opened_at = opened_at
        self.released_at = released_at
        self.commitment = commitment
        self.world_count = world_count

    @property
    def is_open(self) -> bool:
        """Whether this hold is still on the pool."""
        return self.released_at is None

    @property
    def opened(self) -> dt.datetime:
        """When the iteration opened, as the aware instant the row encodes."""
        return _parsed_instant(self.opened_at)

    @property
    def released(self) -> dt.datetime | None:
        """When the iteration closed, or ``None`` while it still holds the pool."""
        return None if self.released_at is None else _parsed_instant(self.released_at)

    def row(self) -> dict[str, object]:
        """The record as a store-shaped mapping — a fresh dict per call."""
        return {
            "id": self.id,
            "iteration_id": self.iteration_id,
            "opened_at": self.opened_at,
            "released_at": self.released_at,
            "commitment": self.commitment,
            "world_count": self.world_count,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FreezeRecord):
            return NotImplemented
        return (
            self.id,
            self.iteration_id,
            self.opened_at,
            self.released_at,
            self.commitment,
            self.world_count,
        ) == (
            other.id,
            other.iteration_id,
            other.opened_at,
            other.released_at,
            other.commitment,
            other.world_count,
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.id,
                self.iteration_id,
                self.opened_at,
                self.released_at,
                self.commitment,
                self.world_count,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"FreezeRecord(iteration_id={self.iteration_id!r}, "
            f"opened_at={self.opened_at!r}, released_at={self.released_at!r}, "
            f"world_count={self.world_count!r})"
        )


def _record_from_row(row: tuple) -> FreezeRecord:
    """Unpack one hold row into the record it holds, in column order."""
    id_, iteration_id, opened_at, released_at, commitment, world_count = row
    return FreezeRecord(
        id=id_,
        iteration_id=iteration_id,
        opened_at=opened_at,
        released_at=released_at,
        commitment=commitment,
        world_count=int(world_count),
    )


class CycleFreeze:
    """The dreaming loop's hold on the replay pool — feature 270's store.

    Constructed with the database URL the pool lives in;
    :meth:`open` takes the hold for one iteration and returns the
    :class:`FreezeRecord` it wrote; :meth:`release` closes it;
    :meth:`verify` re-reads the pool and answers whether it is still the pool
    the hold recorded; :meth:`guard` runs a write under the hold and translates
    the database's abort into :class:`~dreaming.errors.PoolFrozenError`.

    The class resolves its path lazily, so constructing one performs no I/O —
    composition-time work must not touch the disk, the contract every store in
    this workspace states — and nothing is held until a caller's ``open()``
    does, which is the "per outer iteration" of §C5's sentence read as a
    contract: composing an application must not hold a pool.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise FreezeRequestError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # freeze is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> CycleFreeze | None:
        """The freeze ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        freeze component — a discoverable state, not an exception — while the
        operator who means to run §C5's loop is the caller that must not find
        itself in it.  The split is the one the pool's own builder states: this
        method answers *what is composed*, and the caller who needs a hold and
        resolves ``None`` refuses to proceed rather than silently holding
        nothing.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL whose pool this freeze holds."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this freeze, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it, so a freeze built from a mistyped URL fails at the
        hold that could report it, not at the composition that could not.
        """
        if self._path is None:
            self._path = sqlite_path(self._database_url)
        return self._path

    # -- The store's shape ----------------------------------------------------

    def ensure_schema(self) -> None:
        """Bring the database to a held pool's shape, idempotently.

        Public because it is a real operation and not an implementation detail:
        an operator pointing this member at a fresh database runs it once, and
        a test seeds a hold into exactly the schema the store will read.  Every
        statement is ``IF NOT EXISTS``, so running it against a fresh database
        and one this member already prepared take the same path and leave the
        same schema.

        It opens its own connection and commits it, and it does **not** go
        through :meth:`_connect`: that method calls this one, and a public
        entry point that reached back through it would be a pair of methods
        that recurse into each other until the stack ran out.

        It refuses — by the pool's own names — a database that holds no
        ``replay_score`` or no ``bootstrap_world``, because a trigger cannot be
        created over an absent table and a hold over a pool that is not there
        is a hold over nothing.  The refusal is
        :class:`~dreaming.errors.PoolFrozenError` rather than a
        :class:`~dreaming.errors.FreezeRequestError` because by the time it is
        raised the ask has been read and it is the *database* that cannot
        answer: nothing about the URL or the iteration is malformed.
        """
        with closing(sqlite3.connect(self.path)) as connection, connection:
            present = pool_tables_present(connection)
            missing = [table for table in POOL_TABLES if table not in present]
            if missing:
                raise PoolFrozenError(
                    f"{FREEZE_CODE}: the database at {self.path} holds no "
                    f"{' and no '.join(missing)} table, so there is no replay "
                    "pool here to hold — the cycle freeze installs one guard "
                    "per pool table per operation, and a database without the "
                    "pool has nothing for a guard to stand over. A hold that "
                    "quietly succeeded here would let an iteration believe its "
                    f"history was fixed while the history did not exist. Point "
                    f"{DATABASE_URL_ENV} at the database the replay pool lives "
                    "in, or migrate it"
                )
            connection.executescript(cycle_freeze_schema())

    def _connect(self) -> sqlite3.Connection:
        """Open the database, bringing it to this member's shape first.

        The caller owns the connection; use it as a context manager to commit.
        The schema work is delegated to :meth:`ensure_schema` rather than
        inlined, so a caller that only wants the schema does not have to open a
        connection it will not use.
        """
        self.ensure_schema()
        return sqlite3.connect(self.path)

    # -- The holds ------------------------------------------------------------

    def open(
        self,
        iteration_id: Any,
        *,
        opened_at: dt.datetime | None = None,
    ) -> FreezeRecord:
        """Hold the replay pool fixed for one iteration — feature 270's whole call.

        Takes the iteration id the cycle is named by, records the pool's
        commitment and size as they stand *now*, and installs this member's
        guards over the pool's tables.  Returns the :class:`FreezeRecord` the
        hold wrote.  From this call until :meth:`release`, every insert, update
        and delete on ``replay_score`` or ``bootstrap_world`` is refused — by
        this member's API with a
        :class:`~dreaming.errors.PoolFrozenError`, and by the database with a
        raw abort for a writer that never heard of this member.

        The commitment is read **before** the hold row is written, and that
        order is the honest one rather than an accident of code: what the hold
        promises is *the pool as it was when the iteration opened*, so the
        reading that defines the promise cannot itself happen under it.

        Refuses, in this order, each naming what it is about:

        1. an ``iteration_id`` that is not non-empty text, or an ``opened_at``
           that is not a timezone-aware datetime — the ask's own facts, refused
           before anything is read (:class:`~dreaming.errors.FreezeRequestError`);
        2. a database this store cannot speak, or one holding no pool table —
           refused before anything is written
           (:class:`~dreaming.errors.PoolFrozenError`);
        3. a pool **already held** by another iteration — refused with
           :class:`~dreaming.errors.PoolFrozenError`, naming the iteration that
           holds it.  §12.1 runs one cycle at a time, and the refusal carries
           the holder rather than merely the fact so an operator can see which
           cycle to wait for.

        ``opened_at`` defaults to the current UTC instant truncated to the
        second, and is a parameter so a test or a replayed script can stamp a
        deterministic instant — the same reason the pool's own authoring takes
        one.
        """
        iteration = validated_iteration_id(iteration_id)
        instant = _stamp(opened_at if opened_at is not None else dt.datetime.now(dt.UTC))
        commitment, world_count = pool_commitment(self.path)
        with closing(self._connect()) as connection, connection:
            held = connection.execute(_SELECT_OPEN).fetchone()
            if held is not None:
                record = _record_from_row(held)
                raise PoolFrozenError(
                    f"{FREEZE_CODE}: the replay pool is already held by "
                    f"iteration {record.iteration_id!r} (opened "
                    f"{record.opened_at}, {record.world_count} world(s)) — "
                    f"iteration {iteration!r} cannot open a second hold over "
                    "it. §12.1 runs one dreaming cycle at a time: the holdout "
                    "split (feature 279) rotates per cycle and the revision "
                    "cap (feature 277) is a per-cycle fact, so two open holds "
                    "would be two cycles walking one pool with neither able to "
                    "say which scores belonged to which. Close the iteration "
                    "that holds it (CycleFreeze.release), or fold this work "
                    "into it"
                )
            hold_id = _hold_id(iteration, instant)
            try:
                connection.execute(
                    _OPEN_INSERT,
                    (hold_id, iteration, instant, None, commitment, world_count),
                )
            except sqlite3.IntegrityError as refusal:
                # Which constraint spoke decides which sentence is true, so the
                # two are read apart rather than merged into one "it was taken"
                # — the discipline the bootstrap pool states for its own UNIQUE
                # translation.  The one-open index means a concurrent writer
                # took the hold between the read above and this insert; the
                # primary key means this member minted an id twice, which
                # _hold_id is built not to do and which would be a defect here
                # rather than a fact about the pool.  Reporting the second as
                # the first would send an operator waiting for a cycle that
                # does not exist.
                if "pool_freeze.id" in str(refusal):
                    raise
                held = connection.execute(_SELECT_OPEN).fetchone()
                holder = (
                    "an iteration this member could no longer read"
                    if held is None
                    else f"iteration {_record_from_row(held).iteration_id!r}"
                )
                raise PoolFrozenError(
                    f"{FREEZE_CODE}: the replay pool was taken by {holder} as "
                    f"iteration {iteration!r} was opening its hold — §12.1 "
                    "runs one dreaming cycle at a time, so the hold is "
                    "refused rather than shared; retry once the iteration "
                    "holding it has closed"
                ) from refusal
        return FreezeRecord(
            id=hold_id,
            iteration_id=iteration,
            opened_at=instant,
            released_at=None,
            commitment=commitment,
            world_count=world_count,
        )

    def release(self, hold: FreezeRecord | str, *, released_at: dt.datetime | None = None) -> FreezeRecord:
        """Close a hold, freeing the pool for the next iteration.

        Takes the :class:`FreezeRecord` :meth:`open` returned, or its id, and
        stamps ``released_at``.  Returns the released record — the row as it
        now stands, so a caller logging the cycle's close has the whole of what
        the hold was.

        The hold is **kept**, not deleted: an operator asking *when was the
        pool held, and by which cycle?* is asking a question the table answers
        and a row that vanished could not.  Releasing is idempotent in the
        sense that matters — the ``WHERE`` clause requires the row to still be
        open — so a double release cannot restamp a hold with a later instant
        and cannot land on a row a second cycle has since opened.

        Refuses a hold that is not open — already released, or never held by
        this database — with :class:`~dreaming.errors.PoolFrozenError`, naming
        the id.  That is a fact about the store rather than about the ask: the
        id was well formed and simply names no open hold here, which is the
        same distinction :class:`~discovery.errors.CampaignOrderError` draws
        for a store whose state contradicts the call.
        """
        if isinstance(hold, FreezeRecord):
            hold_id = hold.id
        else:
            hold_id = hold
            if not isinstance(hold_id, str) or not hold_id.strip():
                raise FreezeRequestError(
                    f"a hold is released by its id — got {hold!r} "
                    f"({type(hold).__name__}); the id is how a released row is "
                    "named in the store's history, and a value that is not an "
                    "id releases nothing"
                )
        instant = _stamp(
            released_at if released_at is not None else dt.datetime.now(dt.UTC)
        )
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(_RELEASE, (instant, hold_id))
            if cursor.rowcount == 0:
                row = connection.execute(_SELECT_ROW, (hold_id,)).fetchone()
                if row is None:
                    detail = (
                        "this database holds no such hold — a hold id is "
                        "either one this store wrote or it is nothing"
                    )
                else:
                    record = _record_from_row(row)
                    detail = (
                        f"it was opened by iteration "
                        f"{record.iteration_id!r} and released at "
                        f"{record.released_at}"
                    )
                raise PoolFrozenError(
                    f"{FREEZE_CODE}: the hold {hold_id!r} is not open, so it "
                    f"cannot be released — {detail}. Only the cycle that holds "
                    "the pool can free it, and a release that landed on an "
                    "already-closed row would restamp a cycle's history with "
                    "an instant it did not close at"
                )
            row = connection.execute(_SELECT_ROW, (hold_id,)).fetchone()
        return _record_from_row(row)

    def verify(self, hold: FreezeRecord) -> bool:
        """Whether the pool is still the pool ``hold`` recorded.

        Re-reads the commitment and compares it, and the size with it.  ``True``
        means the pool did not move while the iteration was supposed to be
        holding it — the claim *"holding the pool fixed for the cycle"* is true.
        ``False`` means it did move, and the caller holding a bar about to be
        applied to a tournament should not apply it.

        **Why a boolean and not a refusal.**  A pool that moved is not this
        method's to reject: the hold may have been released deliberately, a
        test may be pinning that the guard *can* be evaded, and an operator
        bisecting a deployment may be moving rows on purpose to reproduce a
        fault.  What the loop needs from this call is a *judgement it can act
        on* — the shape :func:`discovery.manifest.admit_completed_campaigns`
        takes for its own gate — so the comparison answers and the caller
        decides whether a mismatch is fatal for its cycle.

        A pool that is not there at all is the other case, and it is a
        refusal rather than ``False``: :func:`pool_commitment` raises for an
        absent table, because *"the pool did not move"* and *"there is no pool
        to compare against"* are different facts and an iteration that read the
        second as the first would report a clean verify over a database that
        holds nothing.

        **A third case, and it is a refusal too: the hold is open but its
        guards are gone.**  The commitment compares the pool's *rows*, and a
        guard is not a row — so a DDL rebuild can leave the data byte-identical
        and the commitment matching while the enforcement behind the hold has
        been removed, and ``True`` here would then report a fixed history that
        nothing is holding.  ``bootstrap`` performs exactly that rebuild in its
        own schema evolution.  A comparison that answered on the commitment
        alone would be reading *"the rows did not move"* as *"the pool is
        held"*, which is the confusion :data:`UNGUARDED_CODE` names; the check
        below refuses instead, naming the guards it found absent.
        """
        if not isinstance(hold, FreezeRecord):
            raise FreezeRequestError(
                f"a hold is verified against the record it opened with — got "
                f"{hold!r} ({type(hold).__name__}); a commitment is only "
                "meaningful beside the values it was taken with, and a value "
                "that is not a record carries none"
            )
        # The pool itself first: a dropped pool table is refused by
        # ``pool_commitment`` below ("no pool here to hold"), and that is the
        # more fundamental fact — reporting it as *three missing guards* would
        # describe the symptom of the drop rather than the drop.  The guard
        # check then only ever sees a pool that is present and can say
        # something specific about what was built over it.
        commitment, world_count = pool_commitment(self.path)
        # Whether the guards are *this hold's* to check is read from the
        # database rather than from the record handed in.  ``hold`` is a value
        # the caller has been carrying: it may be an in-memory record from an
        # iteration that released its window hours ago, whose ``released_at``
        # is still ``None`` while the row says otherwise.  The guards stand for
        # the *open* hold, so the question is about the table's state and the
        # answer has to come from the table — a check driven off a stale
        # snapshot would refuse a verify answering a question about history,
        # having never seen the release that closed the window.
        #
        # A *raw* connection, deliberately: :meth:`_connect` calls
        # :meth:`ensure_schema`, which would re-install any guard that went
        # missing and leave this check with nothing to find.  That heal is the
        # right thing for a read about to run a statement and the wrong thing
        # for this one, whose whole subject is *what the database looks like as
        # found*.  A verify that repaired the state it was asked to judge would
        # answer ``True`` about a pool it had just un-disarmed, and report no
        # fault in a cycle that had spent the interval unguarded — the
        # silent-success shape the refusal below exists to break.
        with closing(sqlite3.connect(self.path)) as connection:
            open_row = connection.execute(_SELECT_OPEN).fetchone()
            if open_row is not None and _record_from_row(open_row).id == hold.id:
                gone = missing_guards(connection)
            else:
                gone = ()
        if gone:
            raise PoolFrozenError(
                f"{UNGUARDED_CODE}: the hold opened by iteration "
                f"{hold.iteration_id!r} is still open, but "
                f"{len(gone)} of its {len(expected_triggers())} guards are "
                f"no longer over the pool ({', '.join(gone)}) — something "
                "rebuilt or dropped a pool table, and SQLite fires no "
                "trigger on DDL, so the hold's enforcement was removed "
                "without any guard being consulted. The pool's rows may "
                "still compare equal and the iteration would go on "
                "believing its history fixed while every write to it "
                "succeeds. Re-install the guards (CycleFreeze.ensure_schema) "
                "or close the cycle and open a new one"
            )
        return commitment == hold.commitment and world_count == hold.world_count

    # -- The reads ------------------------------------------------------------

    def open_hold(self) -> FreezeRecord | None:
        """The iteration currently holding the pool, or ``None``.

        The read every writer's refusal is attributed by, and the one an
        operator asks first: *is a cycle walking the pool right now, and
        which?*  ``None`` means the pool is free — the state between
        iterations, in which §C5 allows the campaign loop to add completed
        campaigns and the pool to grow.  It is deliberately **not** the same
        answer as an unconfigured store's: a caller holding a `None` *freeze*
        (no ``DATABASE_URL``) cannot ask this question at all, and the two
        states — *no pool is held* and *there is no pool to hold* — are the
        distinction the builder's own ``None`` exists to keep visible.
        """
        with closing(self._connect()) as connection:
            row = connection.execute(_SELECT_OPEN).fetchone()
        return None if row is None else _record_from_row(row)

    def holds(self) -> tuple[FreezeRecord, ...]:
        """Every hold this database records, open or released, oldest first.

        The audit read: a cycle's history of who held the pool and for how
        long, which is the account :meth:`open_hold` — a single-row read — is
        deliberately not.  Ordered by ``opened_at`` then by id, so two reads of
        one history return the same sequence whatever the storage engine's
        accident — the §12 ordering rule every store in this workspace restates
        for its own reads.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(_ROW_COLUMNS)} FROM {FREEZE_TABLE} "
                "ORDER BY opened_at, id"
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def held(self) -> bool:
        """Whether an iteration holds the pool right now.

        A boolean for the caller that is asking a question about *whether* and
        not about *who* — chiefly :meth:`guard`, whose subject is the statement
        it is about to run rather than the cycle holding it.  A caller that
        needs to name the holder asks :meth:`open_hold`.
        """
        return self.open_hold() is not None

    # -- The guard ------------------------------------------------------------

    def guard(self, statement: str, parameters: tuple[Any, ...] = ()) -> int:
        """Run a write against the pool, refusing it if an iteration holds it.

        The seam feature 270's sentence is read through by this member's own
        callers: the replay member's writer (features 245-255) and the campaign
        loop that adds completed campaigns (feature 243) run their statements
        through it, and a statement attempted while a hold is open is refused
        with :class:`~dreaming.errors.PoolFrozenError` naming the iteration.

        **It is a translation, not the enforcement.**  The rule itself lives in
        the database — :meth:`ensure_schema` installs a guard per pool table
        per operation — so a statement that reaches the pool by any other door
        is refused exactly the same way, by SQLite, with a raw abort.  This
        method exists so the *caller that went through this member* gets a
        refusal its own vocabulary can read, which is the seam discipline the
        whole workspace states: an error type raised across a member boundary
        belongs to the caller's side of it.

        Returns the rowcount the statement produced, which is what the caller
        of an ``INSERT``/``UPDATE``/``DELETE`` wants and what the guards make
        reachable only when no hold is open.

        A statement that fails for a reason **other** than the hold — a
        ``NOT NULL`` violation, a missing table, a syntax error — is re-raised
        untouched.  Only the hold's own abort is translated, and it is
        recognised by the code :data:`FREEZE_CODE` opens the trigger's message
        with: a refusal that rewrote every ``IntegrityError`` as *the pool is
        frozen* would hide a real schema fault behind a rule about cycles,
        which is the failure :mod:`discovery.errors` names for a vocabulary
        that swallows a neighbouring feature's error.
        """
        with closing(self._connect()) as connection, connection:
            try:
                cursor = connection.execute(statement, parameters)
            except sqlite3.IntegrityError as refusal:
                if FREEZE_CODE not in str(refusal):
                    raise
                held = connection.execute(_SELECT_OPEN).fetchone()
                iteration = (
                    None if held is None else _record_from_row(held).iteration_id
                )
                raise PoolFrozenError(
                    _guard_message(
                        _operation_of(statement), _table_of(statement), iteration
                    )
                ) from refusal
            return cursor.rowcount


def _hold_id(iteration_id: str, opened_at: str) -> str:
    """The id a hold is named by — ``iteration``, its opening instant, and a draw.

    Deterministic in ``iteration`` and ``opened_at`` and *distinct* for every
    call, which is a narrower claim than the first two alone and the honest one.
    A window is an occurrence, not a value: §12.1's cycle may legitimately open,
    close and open again — a retry after a failed M-revision sweep, an operator
    releasing a stuck hold, a replayed script — and that second window is a
    *different* hold, with its own opening instant and its own commitment.  Ids
    derived from ``(iteration, instant)`` alone would collide on the primary key
    for a retry stamped inside the same second, and the collision would surface
    as the *wrong* refusal — "the pool was taken by another writer" for a row
    that holds nothing, because the stale row is this iteration's own closed
    window.  Naming each window its own id keeps :meth:`CycleFreeze.release`
    exact (a released row is never re-released into a later cycle) and lets the
    one-open *index*, not the primary key, be the thing that decides whether the
    pool is held — which is what it is for.

    A sha256 hex string rather than a UUID because the inputs are text of
    unbounded shape and a UUID's fixed layout would either truncate them or
    require a namespace this member has no use for.
    """
    digest = hashlib.sha256(
        f"{iteration_id}\n{opened_at}\n{secrets.token_hex(16)}\n".encode()
    ).hexdigest()
    return f"freeze-{digest[:32]}"


def _operation_of(statement: str) -> str:
    """The DML verb a statement begins with, upper-cased.

    Read off the statement rather than passed in, so :meth:`CycleFreeze.guard`
    can be called with a bare SQL string — the shape a caller holding a
    statement already has — and the refusal still names the operation the way
    the database's own trigger message does.  A statement that does not begin
    with one of the three verbs answers ``"WRITE"``, which is honest: the
    refusal is about a write, and the statement was refused by a guard.
    """
    word = statement.lstrip().split(None, 1)[0] if statement.strip() else ""
    upper = word.upper()
    return upper if upper in _POOL_OPERATIONS else "WRITE"


def _table_of(statement: str) -> str:
    """The pool table a statement names, or a spelling of *a pool table*.

    Best-effort and deliberately not a parser: :meth:`CycleFreeze.guard`'s
    caller already passed a statement to SQLite, which is the authority on what
    it meant.  What this recovers is the *name* for the refusal's prose, so the
    message says which table was refused; a statement whose table cannot be
    found by a substring test answers the pool's two names joined, which is
    less specific than the truth and never wrong about it.
    """
    lowered = statement.lower()
    for table in POOL_TABLES:
        if table in lowered:
            return table
    return " or ".join(POOL_TABLES)


def open_cycle_freeze(
    iteration_id: Any,
    *,
    database_url: str | None = None,
    opened_at: dt.datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> FreezeRecord:
    """Hold the replay pool for one iteration, in the database ``DATABASE_URL`` names.

    The same act as :meth:`CycleFreeze.open`, without the intermediate object —
    for the caller that holds neither a freeze nor a URL and simply wants §C5's
    first clause done.  Resolves the deployment the way every store's builder
    does (an explicit URL first, then ``DATABASE_URL``), and **refuses** when
    neither names one:

        a caller that means to hold the pool and resolves nothing must not
        proceed — a cycle that believed it had fixed its history while holding
        nothing would replay its candidates across a pool free to move under
        it, which is precisely the failure feature 270 exists to prevent.

    That refusal is :class:`~dreaming.errors.FreezeRequestError` rather than a
    ``None``, and the split is the builder's: :meth:`CycleFreeze.resolve`
    answers *what is composed* and a caller may legitimately find nothing
    there, while this function *performs* the act and cannot.  So an
    unconfigured deployment meets a named refusal here and a ``None`` there,
    and neither is mistakable for the other.
    """
    url = database_url if database_url is not None else (env if env is not None else os.environ).get(
        DATABASE_URL_ENV, ""
    )
    if not isinstance(url, str) or not url.strip():
        raise FreezeRequestError(
            f"opening a cycle freeze needs the database the replay pool lives "
            f"in — pass it explicitly or set {DATABASE_URL_ENV}. A hold that "
            "resolved no database would hold nothing while the iteration "
            "believed its history was fixed, and the pool would be free to "
            "move under the candidates the cycle is comparing"
        )
    return CycleFreeze(url).open(iteration_id, opened_at=opened_at)
