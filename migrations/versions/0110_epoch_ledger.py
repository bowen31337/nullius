"""The epoch_ledger table, in one versioned migration (feature 105).

app_spec.xml feature 105: "System creates the epoch_ledger table tracking
promotion decisions served per sequestered epoch with a unique constraint on
epoch_id." Four columns, one table — smaller than 0108's six, one column
bigger than 0107's three, and the one the whole promotion discipline leans
on, because it is where a depleting resource is counted down.

What the table is for
---------------------

A sequestered epoch is a holdout the meta-learning loop has never shown to a
policy: the paper's stage-② score is measured on "a sequestered epoch it has
never observed in any world" (docs/alpha-engine-prd.md §"Change A"). Every
promotion decision *spends* a little of that holdout — each decision is a
chance for information about the epoch to leak into what gets promoted — so
the PRD makes the spend an invariant, §13 item 4:

    Sequestered epochs are retired permanently after **3 promotion
    decisions**. Track in a ledger. When clean epochs run out, the system
    stops. That is a legitimate terminal state.

This table is that ledger. One row per sequestered epoch, holding the moment
it was sealed, how many promotion decisions it has served, and whether it is
retired. Everything downstream of the retirement rule is another feature's
machinery and all of it reads this table:

* the ledger plugin derives epoch usage counts from it (feature 96, the
  ``GET /ledger/k-effective`` family's usage half);
* the promotion plugin persists the running decision count against the
  serving epoch (feature 294);
* selection of an epoch that has served three decisions is refused
  (feature 295);
* promotion blocks outright when no clean epoch remains — a terminal state,
  never a reused retired one (feature 296, the ``retired`` flag's reader);
* ``promotion_registry.epoch_id`` references ``epoch_ledger(epoch_id)``
  (``0108_forward_and_universe_tables``, which declares this table in its
  :data:`REQUIRES_TABLES` for exactly that reason).

The epoch namespace is shared with ``trial_ledger.epoch_id`` (feature 103),
which names the charged epoch per trial row; this table is where those names
become a countable resource rather than a label.

The unique constraint is the primary key
----------------------------------------

The feature's sentence asks for "a unique constraint on epoch_id", and the
spec's schema block delivers it as ``epoch_id TEXT PRIMARY KEY``. A primary
key *is* a unique constraint — the strictest one the dialect offers — so
this file spells the column once and does not add a redundant ``UNIQUE``:
a second index on the same column would enforce nothing the key does not
already enforce and would cost a duplicate index on every write. The prose
and the block are the same ask in two dialects; the DDL answers the block.

The one correction is the spelling ``NOT NULL PRIMARY KEY`` where the block
writes the bare key, for the reason 0107 and 0108 state and 0109 restates:
Postgres makes a primary key's columns ``NOT NULL`` implicitly, but SQLite
does **not** — on a rowid table a bare ``PRIMARY KEY`` permits NULL, and
because NULLs compare distinct it permits *several* NULL-keyed rows.
(Verified against SQLite directly, as in 0107: the bare spelling accepts
two NULL-stratum rows; the tightened one refuses a NULL and a duplicate.)
For this table the lapse would not merely be untidy — the ledger's whole
identity is one row per epoch, and a second row for the same epoch would
split its served count in half, letting feature 295's three-decision
threshold read a "clean" epoch that had already served its budget. A
uniqueness guarantee that holds in production and silently lapses in the
database every test runs against is worse than either failure on its own.

Every writer names a real epoch, so nothing that would have worked against
a bare-key table is refused here; and because the statement is ``IF NOT
EXISTS``, a database whose store created the table first is left exactly as
it was — the tightening can only apply where this migration is the thing
that creates the table.

The other three columns
-----------------------

``sealed_at TIMESTAMPTZ NOT NULL`` — when the epoch was sequestered. The
row is created *by* the sealing event, and the sealing moment is a fact the
writer carries, not something the table can mint: there is no default
because no "now-ish" timestamp would be honest about an event that happened
at a specific, externally-meaningful time. A row without a ``sealed_at``
would be an epoch that was never sequestered — the exact row this ledger
must not hold. (Contrast 0107's ``updated_at``, which *is* defaulted: that
column is the vintage of a mutable count, and now is always an honest value
for it.) Writers store the instant as ISO-8601 UTC text on SQLite, the
convention the rest of the spine writes by hand.

``promotion_decisions_served INT NOT NULL DEFAULT 0`` — the running count
the invariant budgets. The default is the point, not decoration, and the
argument is 0107's ``world_count`` argument verbatim: a freshly sealed epoch
has served zero promotion decisions, which is a fact to record as a ``0``,
not an absence — feature 295 reads ``promotion_decisions_served >= 3``
against exactly this column, and an absent row has to keep meaning "epoch
nobody sealed", a different fact. The default buys the two-column insert of
a fresh epoch: ``INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?,
?)``. The count is advanced by ``UPDATE`` (feature 294's writer contract),
and a default fires only at insert, so the promotion plugin re-supplies the
value on every advance — the same writer contract 0107 states for its
counts.

``retired BOOLEAN NOT NULL DEFAULT FALSE`` — feature 296's flag. An epoch
that has served its three decisions is retired *permanently*, and the
system stops rather than reuse it; the flag is how "permanently" survives a
restart. It defaults to ``FALSE`` so a fresh epoch is clean by construction
without naming the column, the same role ``FALSE`` defaults play in
``replay_score.is_holdout`` and ``policy_revision.selected``.

Dialect
-------

The repository runs SQLite on a single machine (the app spec's dev
allowance, and what ``tests/conftest.py`` points ``DATABASE_URL`` at) and
Postgres 16 in production (§9.1 of docs/nullius-tech-architecture.md).
Every previous migration in this tree carries a dialect split because
every previous table mints something at insert time — ``gen_random_uuid()``
for an ``id`` (0108, 0109) or ``NOW()`` for a defaulted timestamp (0107,
0108, 0109) — and neither function call survives SQLite's ``DEFAULT``
grammar. This table mints nothing: the key is a name the writer supplies,
and the timestamp is the sealing moment the writer carries. ``TEXT``,
``TIMESTAMPTZ``, ``INT``, ``BOOLEAN`` and the literal defaults ``0`` and
``FALSE`` are accepted by both dialects (SQLite applies its own affinity;
``FALSE`` has been a keyword there since 3.23), so the DDL below is one
spelling for both — the first dialect-invariant migration in the tree.

:func:`statements` keeps its ``dialect`` parameter because the tree's
uniform interface promises it — a runner or test may call
``statements("sqlite")`` and ``statements("postgres")`` against every file
and get DDL back — and the parameter is where a future defaulted column's
split would go. It currently selects nothing, and :func:`upgrade` therefore
does without 0107's ``_dialect_of`` detector rather than carry detection
machinery whose result is discarded. An unknown dialect receives the same
single spelling, which is trivially the spec's own.

Revision chaining
-----------------

This file's spec feature index is 105, but its revision id is ``0110``:
the tree's convention (stated by 0108, reaffirmed by 0109) pads the
feature's *position in the assembled chain*, not its spec index, because
the spec's feature order and the landing order have already diverged —
feature 106's two tables landed as ``0109``. This migration is the fourth
in the assembled chain, hence ``0110``. The spec-order irony is real but
harmless: feature 105 precedes 106 and 107 in the spec and follows both in
the chain, and no data dependency is violated because this table references
nothing (see :data:`REQUIRES_TABLES`).

:data:`DOWN_REVISION` names ``0109_replay_score_and_policy_revision`` — the
head this branch actually holds, a committed file rather than the
convention guess 0107 had to make. The one string to reconcile if the chain
is ever renumbered is this constant.

One fact about the assembled chain belongs here because this table is its
subject: ``0108``'s ``promotion_registry`` carries ``REFERENCES
epoch_ledger(epoch_id)``, and Postgres validates a foreign key's parent at
``CREATE TABLE`` time — so a Postgres run of the chain as assembled stops
at 0108, before this file exists to satisfy it. SQLite, the dev and test
database, resolves the parent at first row write, so the order works there.
This is precisely the dependency 0108 declared in its
:data:`REQUIRES_TABLES` precisely so it could not be read past; reconciling
the chain order for Postgres is the assembler's or 0108's fix. This file's
obligation is met by existing, with the table name and key column exactly
as referenced.

Idempotency and re-runnability
------------------------------

The statement is ``IF NOT EXISTS`` and ``downgrade`` is ``DROP TABLE IF
EXISTS``, so upgrade is re-runnable against a database that already holds
the table, and a downgrade followed by an upgrade round-trips to the same
schema. ``downgrade`` drops only this table — a downgraded database is one
the promotion plugin's next persist refills, not one left broken. One
refusal is correct and worth naming: this is the first table in the tree
that another table's foreign key points *at*, so a connection enforcing
foreign keys — every :func:`connect` here enables it, where SQLite's own
default is off — refuses the drop while ``promotion_registry`` rows
reference the table. That is the constraint doing its job, not a defect.
(Verified against SQLite directly: with a referencing row present the drop
raises ``FOREIGN KEY constraint failed``; with the table clean it
round-trips.)
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

__all__ = [
    "DATABASE_URL_ENV",
    "DOWN_REVISION",
    "INDEXES",
    "REQUIRES_TABLES",
    "REVISION",
    "TABLES",
    "apply",
    "connect",
    "downgrade",
    "statements",
    "upgrade",
]

# ── Version identity ─────────────────────────────────────────────────────────

#: This migration's revision id. The number is this file's position in the
#: assembled chain (fourth), not its spec feature index (105) — see the module
#: docstring for the divergence and why the chain position wins.
REVISION = "0110_epoch_ledger"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0109 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0109_replay_score_and_policy_revision"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: Tables that must already exist for this migration to be valid on a dialect
#: that validates foreign keys at DDL time (Postgres). Empty because this
#: table references nothing: the epochs are named by the sealing process, not
#: looked up from a parent table, and the things counted against them are
#: promotion decisions — events recorded in ``promotion_registry``, which
#: references *this* table, not the other way round.
REQUIRES_TABLES: tuple[str, ...] = ()

#: The tables this migration creates, in creation order.
TABLES = ("epoch_ledger",)

#: The indexes this migration creates — none. The table holds one row per
#: sequestered epoch, the primary key is its own index on both dialects, and
#: every reader that exists (features 96, 295, 296) looks an epoch up by its
#: key. The rule is the one 0108 states: a migration is the wrong place to
#: invent a query plan for readers that do not exist yet.
INDEXES: tuple[str, ...] = ()

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── The statements ───────────────────────────────────────────────────────────


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    ``dialect`` is part of the tree's uniform interface and currently selects
    nothing: this table mints no id and defaults no timestamp, so there is no
    ``gen_random_uuid()`` or ``NOW()`` to translate, and the single spelling
    below is valid on SQLite and Postgres alike. See the module docstring's
    Dialect section. The statement is idempotent, and the column list is the
    spec's schema block in its order with the one argued departure — ``NOT
    NULL`` on the key.
    """
    _ = dialect  # accepted for the uniform interface; selects nothing today
    return (
        # Feature 105 / §13 invariant 4. One row per sequestered epoch, holding
        # when it was sealed, how many promotion decisions it has served, and
        # whether it is retired. `epoch_id` carries NOT NULL explicitly where
        # the spec's block writes a bare `TEXT PRIMARY KEY`: the bare spelling
        # on SQLite's rowid tables accepts NULL keys (and several of them,
        # since NULLs compare distinct), and a duplicate epoch row would split
        # its served count and let a spent epoch read as clean — the primary
        # key is the feature's "unique constraint on epoch_id", made to hold
        # on the database every test runs against, not only in production.
        # `sealed_at` has no default because the sealing moment is a fact the
        # writer carries — the row *is* the sealing event. The other two
        # defaults make the fresh-epoch insert two columns long: a sealed
        # epoch has served zero decisions (a 0 to record, not an absence —
        # feature 295 budgets on exactly this column) and is not retired.
        # No f-string: there is nothing to interpolate — the one spelling is
        # the whole point of this table's dialect section.
        """
        CREATE TABLE IF NOT EXISTS epoch_ledger (
            epoch_id                   TEXT NOT NULL PRIMARY KEY,
            sealed_at                  TIMESTAMPTZ NOT NULL,
            promotion_decisions_served INT NOT NULL DEFAULT 0,
            retired                    BOOLEAN NOT NULL DEFAULT FALSE
        )
        """,
    )


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    One table and no indexes, so the sequence is a single statement; it is
    kept as a function rather than inlined so the shape matches the rest of
    the tree.
    """
    drops = [f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)]
    drops += [f"DROP INDEX IF EXISTS {index}" for index in reversed(INDEXES)]
    return tuple(drops)


# ── Running it ───────────────────────────────────────────────────────────────


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Create the table on ``connection``; returns the statements executed.

    Takes any DBAPI connection. The caller owns the transaction — this
    function neither commits nor rolls back, so a caller that is already inside
    a transaction (a migration runner, a test) does not have its unit of work
    split by an implicit commit. Use a context manager, or call
    :func:`apply`, which opens and commits its own SQLite connection.

    ``dialect`` is accepted for the tree's uniform upgrade signature; the DDL
    is dialect-invariant (see :func:`statements`), so unlike 0107/0108/0109
    there is no detection to do and the argument selects nothing.
    """
    ddl = statements(dialect if dialect is not None else "other")
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


def downgrade(connection: object) -> tuple[str, ...]:
    """Drop the table this migration created; returns the statements executed.

    Destructive by definition. It is idempotent, and it drops only the object
    this migration creates — a database downgraded here is refilled by the
    promotion plugin's next persist, which creates the table idempotently.
    A connection enforcing foreign keys refuses the drop while
    ``promotion_registry`` rows reference this table; see the module
    docstring's idempotency section.
    """
    ddl = _drop_statements()
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The same convention the rest of the spine uses, and deliberately re-stated
    rather than imported: a migration is loaded by path by its runner and must
    not depend on a workspace package being importable in order to run. A
    non-SQLite scheme is refused by name, because :func:`apply` cannot speak it
    and pretending otherwise would hide a misrouted URL behind a mysterious
    file.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError(
            f"unsupported DATABASE_URL scheme {parsed.scheme!r}: apply() opens "
            "sqlite:/// only; pass a DBAPI connection to upgrade() for another "
            "dialect"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ValueError(
            f"sqlite DATABASE_URL must not carry a host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path)
    if path.startswith("/"):
        path = path[1:]
    if not path:
        raise ValueError("sqlite DATABASE_URL carries no database path")
    return Path(path)


def connect(database_url: Optional[str] = None) -> sqlite3.Connection:
    """Open the SQLite store named by ``database_url`` (or ``DATABASE_URL``).

    Foreign keys are enabled, as in every other SQLite store in the workspace,
    so a caller reading back what this migration created sees the same
    constraint enforcement the rest of the spine sees — including the
    ``promotion_registry`` rows that reference this table.
    """
    url = database_url if database_url is not None else os.environ[DATABASE_URL_ENV]
    path = _sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def apply(database_url: Optional[str] = None) -> tuple[str, ...]:
    """Create the table in a SQLite database; returns the statements executed.

    The standalone entry point: opens the database named by ``database_url``
    (or ``DATABASE_URL``) and commits the migration in one transaction, so a
    caller with no migration runner can still bring a database to this
    revision. Safe to call repeatedly and on a database whose plugin already
    created the table.
    """
    with closing(connect(database_url)) as connection, connection:
        return upgrade(connection)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """``python <this file> [upgrade|downgrade]`` against ``DATABASE_URL``.

    A runner's escape hatch, not a replacement for one: it exists so the
    statements in this file can be exercised against a real database without
    Alembic being installed, which is the state of this workspace today.

    ``argv`` defaults to the command line's own arguments, and no argument
    means ``upgrade``. Reading ``sys.argv`` is deliberate: 0108's and 0109's
    escape hatches ignore it, which makes those files' advertised
    ``[downgrade]`` word unreachable from the shell — a defect left to their
    owners to fix, not copied here.
    """
    args = list(sys.argv[1:]) if argv is None else list(argv)
    action = args[0] if args else "upgrade"
    if action not in ("upgrade", "downgrade"):
        print(f"usage: {Path(__file__).name} [upgrade|downgrade]")
        return 2
    with closing(connect()) as connection, connection:
        executed = upgrade(connection) if action == "upgrade" else downgrade(connection)
    for statement in executed:
        print(" ".join(statement.split()).rstrip(";") + ";")
    return 0


if __name__ == "__main__":  # pragma: no cover - a runner's escape hatch
    raise SystemExit(_main())
