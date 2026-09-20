"""The trial_ledger table, in one versioned migration (feature 103).

app_spec.xml feature 103: "System creates the trial_ledger table with a
bigserial primary key and role grants that deny UPDATE and DELETE." One
table, eleven columns, and the one the system's honesty rests on, because it
is an append-only write-ahead log rather than a mutable table — the honest
``K`` counter that the deflation term and the epoch-usage budget both read.

What the table is for
---------------------

Every evaluation the discovery loop runs is one appended row: the moment it
charged, which node it scored, which campaign that node belongs to, the
provenance triple (evaluator/snapshot/cost-model hashes — feature 87), which
sequestered epoch it spent (feature 88, ``epoch_id`` names the row in
``epoch_ledger``), how many charge units it cost (feature 89, defaulting to
``1.0`` so an ordinary evaluation is one unit and a cross-validated one may
cost more), whether it drew down the epoch's statistical budget
(feature 90, ``charges_budget`` — supplied by the null oracle as an opaque
directive, ``FALSE`` for a null node whose signal was never compared to real
forward returns and so consumed no degrees of freedom), and how it ended
(feature 91, one of ``ok``, ``timeout``, ``error``, ``tripwire_fail``).

Everything downstream of a trial reads this table and none of it mutates it:

* ``K_effective`` per epoch counts only rows with ``charges_budget`` true, so
  null nodes never inflate the trial count (feature 93, the ``GET
  /ledger/k-effective`` family's deflation half);
* epoch usage counts how many promotion decisions each sequestered epoch has
  served, retiring it at three (feature 96);
* ``POST /ledger/debit`` appends one row idempotently keyed by ``node_id`` and
  returns the prior sequence on a retry (feature 95).

The append-only shape is not a convention this table asks writers to honour;
it is enforced by the database, which is the feature's second half.

The bigserial primary key and its dialect
-----------------------------------------

The spec's schema block spells the key ``seq BIGSERIAL PRIMARY KEY`` and the
architecture doc calls it out as "a monotonically increasing sequence
number". ``BIGSERIAL`` is Postgres spelling — an 8-byte auto-incrementing
key backed by a sequence, whose values are never reused. SQLite has no
``BIGSERIAL`` (indeed no ``SERIAL``) type, and this is the first table in the
migration tree to need a serial key, so it is the first to carry that split.

SQLite's closest equivalent is ``INTEGER PRIMARY KEY AUTOINCREMENT``. Two
facts make it the right translation rather than a bare ``INTEGER PRIMARY
KEY``:

* SQLite ``INTEGER`` is always 8-byte signed, so it matches ``BIGSERIAL``'s
  width — there is no separate "big" integer to reach for.
* A bare ``INTEGER PRIMARY KEY`` is an alias for the rowid and auto-increments
  too, *but* a deleted row's rowid can be reused. ``AUTOINCREMENT`` adds the
  ``sqlite_sequence`` bookkeeping that forbids reuse, giving ``BIGSERIAL``'s
  "monotonic, never reused" guarantee — the property an append-only ledger's
  sequence number must carry, where a retried or reordered append must never
  observe a sequence it has already seen.

``AUTOINCREMENT`` forbids a ``DEFAULT`` clause, and ``BIGSERIAL`` carries none
(it is a sequence, not a default), so the two spellings share nothing but the
column name; :func:`_primary_key_definition` returns the whole column line per
dialect rather than a single expression.

The one defaulted timestamp
---------------------------

``ts TIMESTAMPTZ NOT NULL DEFAULT NOW()`` is the row's creation instant, and
the row *is* the append event, so "now" is always the honest value — the same
role ``NOW()`` plays on ``node.created_at`` and ``campaign.created_at``. It is
the second of this migration's two dialect splits: ``DEFAULT NOW()`` is a
syntax error in SQLite, whose ``DEFAULT`` grammar admits a function call only
when it is parenthesised, so the SQLite spelling is
``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` — an ISO-8601 UTC instant string,
the textual twin of Postgres's ``timestamptz``, stored the same way the rest
of the spine stores its timestamps. ``TIMESTAMPTZ``, ``UUID``, ``CHAR``,
``REAL``, ``BOOLEAN``, ``TEXT`` and the literal ``1.0`` default are all
accepted by SQLite (it applies its own affinity), so beyond the serial key and
this one timestamp the column list is identical between dialects.

The role grants that deny UPDATE and DELETE (feature 92)
--------------------------------------------------------

The feature's second half — "enforced by role grants rather than by
application convention" — is what makes the ledger append-only at the
database rather than by the good intentions of callers. This migration
creates a dedicated role, ``trial_ledger_writer``, grants it exactly the two
privileges the append path needs (``SELECT`` to read the prior sequence on a
retry, ``INSERT`` to append), and explicitly revokes every privilege that
would let it alter or destroy a row once written. Granting ``SELECT`` and
``INSERT`` alone would already refuse ``UPDATE`` and ``DELETE`` — in Postgres
an ungranted privilege is simply denied — but the explicit ``REVOKE`` makes
the append-only intent legible in the DDL and defeats any later ``GRANT`` to
``PUBLIC`` that would otherwise re-open the table to mutation. The application
writes through this role, so a mutation attempt is refused by the database's
privilege check with a permission error, not caught (or, worse, silently
allowed) in application code.

This is a Postgres-only construct and the reason the migration carries a
third dialect branch beyond the key and the timestamp. SQLite has no roles,
no ``GRANT`` and no ``REVOKE`` — there is no privilege model to enforce
against — so the role-grant statements are emitted for the Postgres dialect
alone and a SQLite database sees only the ``CREATE TABLE``. On SQLite the
append-only guarantee is carried by the writers (feature 95 appends; nothing
updates or deletes), and the database the acceptance gate runs against never
sees a statement it cannot parse. ``CREATE ROLE`` has no ``IF NOT EXISTS`` in
Postgres, so the creation is guarded by a ``DO`` block that creates the role
only when it is absent — the migration stays re-runnable, as the ``IF NOT
EXISTS`` table and the idempotent ``GRANT``/``REVOKE`` already are.

The other columns
-----------------

``node_id UUID NOT NULL`` and ``campaign_id UUID NOT NULL`` name the node the
trial scored and the campaign that node belongs to. The spec's schema block
carries no ``REFERENCES`` on either — they are labels the writer supplies, not
foreign keys looked up here — so this table references nothing and imposes no
DDL-time ordering constraint (see :data:`REQUIRES_TABLES`). ``evaluator_hash``,
``snapshot_hash`` and ``cost_model_hash`` are the ``CHAR(64)`` provenance
triple (feature 87), ``NOT NULL`` because a trial without its evaluation
provenance is not a ledger row the system can stand behind. ``epoch_id TEXT
NOT NULL`` names the charged epoch; a write whose epoch is absent is refused
(feature 88) because the epoch is a depleting resource counted in
``epoch_ledger``. ``charge_units REAL NOT NULL DEFAULT 1.0`` and
``charges_budget BOOLEAN NOT NULL`` are the two feature-89/90 columns above;
``charges_budget`` carries no default because the null oracle supplies it per
request, never derived. ``outcome TEXT NOT NULL`` is feature 91's verdict,
``NOT NULL`` with no default because a trial that has not ended has no outcome
to record — the row is written when the evaluation finishes.

Revision chaining
-----------------

This file's spec feature index is 103, but its revision id is ``0112``: the
tree's convention (stated by 0108, reaffirmed by 0109, 0110 and 0111) pads the
feature's *position in the assembled chain*, not its spec index, because the
spec's feature order and the landing order have diverged — feature 104's
campaign landed as 0111 and feature 105's epoch_ledger as 0110. This
migration is the sixth in the assembled chain — ``0107`` → ``0108`` →
``0109`` → ``0110`` → ``0111`` → this one — hence ``0112``.

:data:`DOWN_REVISION` names ``0111_campaign_table`` — the head this branch
actually holds, a committed file rather than a convention guess. The one
string to reconcile if the chain is ever renumbered is this constant. This
table references nothing (node, campaign and epoch are named by writers, not
looked up here), so it imposes no ordering constraint on the chain and
:data:`REQUIRES_TABLES` is empty.

Idempotency and re-runnability
------------------------------

The ``CREATE TABLE`` is ``IF NOT EXISTS`` and the role is created only when
absent, so upgrade is re-runnable against a database that already holds the
table and the role; the ``GRANT`` and ``REVOKE`` are idempotent (re-granting
is a no-op, and revoking an ungranted privilege is a no-op). ``downgrade`` is
``DROP TABLE IF EXISTS`` followed by ``DROP ROLE IF EXISTS`` — the role is
dropped only after the table, because a role that still holds privileges on a
table is refused by ``DROP ROLE``; a downgrade followed by an upgrade
round-trips to the same schema. On SQLite the role statements are never
emitted, so downgrade is the single ``DROP TABLE IF EXISTS`` the other
SQLite-only migrations run. This table is referenced by no foreign key (it
references nothing, and nothing references it yet), so the drop is never
refused by a dependent — the constraint that blocked 0110's drop has no
counterpart here.
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
    "ROLE",
    "TABLES",
    "apply",
    "connect",
    "downgrade",
    "statements",
    "upgrade",
]

# ── Version identity ─────────────────────────────────────────────────────────

#: This migration's revision id. The number is this file's position in the
#: assembled chain (sixth), not its spec feature index (103) — see the module
#: docstring for the convention and why the chain position wins.
REVISION = "0112_trial_ledger"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0111 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0111_campaign_table"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: Tables that must already exist for this migration to be valid on a dialect
#: that validates foreign keys at DDL time (Postgres). Empty because this
#: table references nothing: ``node_id``, ``campaign_id`` and ``epoch_id`` are
#: labels the writer supplies, and the spec's schema block carries no
#: ``REFERENCES`` on any of them — the things that relate to a trial are
#: written by the plugins that append the row, not looked up here.
REQUIRES_TABLES: tuple[str, ...] = ()

#: The tables this migration creates, in creation order.
TABLES = ("trial_ledger",)

#: The append-only role this migration creates on Postgres — the identity the
#: write path connects as, granted ``SELECT`` and ``INSERT`` and denied every
#: privilege that would let it mutate a row once written (feature 92). Created
#: on Postgres only; SQLite has no roles and never sees it.
ROLE = "trial_ledger_writer"

#: The indexes this migration creates — none. The table is appended to one row
#: at a time and read by readers that derive per-epoch counts and per-node
#: retries; the primary key is its own index on both dialects, and the rule is
#: the one 0108 states: a migration is the wrong place to invent a query plan
#: for readers that do not exist yet.
INDEXES: tuple[str, ...] = ()

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── Dialect ──────────────────────────────────────────────────────────────────

#: The Postgres serial-key spelling: the spec's own ``BIGSERIAL``, an 8-byte
#: auto-incrementing key backed by a sequence whose values are never reused.
_POSTGRES_PK = "seq BIGSERIAL PRIMARY KEY"

#: The SQLite serial-key spelling: ``INTEGER`` is always 8-byte here, and
#: ``AUTOINCREMENT`` (not a bare ``INTEGER PRIMARY KEY``) gives ``BIGSERIAL``'s
#: "monotonic, never reused" guarantee — the property an append-only ledger's
#: sequence number must carry. ``AUTOINCREMENT`` forbids a ``DEFAULT``.
_SQLITE_PK = "seq INTEGER PRIMARY KEY AUTOINCREMENT"

#: The Postgres default for a defaulted timestamp: the spec's own ``NOW()``.
_POSTGRES_NOW_DEFAULT = "NOW()"

#: The SQLite equivalent: the current UTC instant as an ISO-8601 string, in the
#: parentheses SQLite's ``DEFAULT`` grammar requires — the textual twin of
#: Postgres's ``timestamptz``, stored the way the rest of the spine stores its
#: timestamps.
_SQLITE_NOW_DEFAULT = "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"


def _primary_key_definition(dialect: str) -> str:
    """The ``seq`` primary-key column line for ``dialect``.

    The first of the migration's dialect splits; see the module docstring.
    Returns the whole column definition (not a single expression) because the
    two spellings share only the column name — ``BIGSERIAL`` is a sequence with
    no ``DEFAULT``, and ``AUTOINCREMENT`` forbids one — so there is no common
    line to parameterise a fragment of. An unknown dialect gets the Postgres
    spelling, the spec's own; see :func:`_dialect_of` for why an unrecognised
    driver is treated as Postgres.
    """
    return _SQLITE_PK if dialect == "sqlite" else _POSTGRES_PK


def _now_default(dialect: str) -> str:
    """The defaulted-timestamp column default for ``dialect``.

    The second of the migration's dialect splits; see the module docstring.
    Same unknown-dialect policy as :func:`_primary_key_definition`.
    """
    return _SQLITE_NOW_DEFAULT if dialect == "sqlite" else _POSTGRES_NOW_DEFAULT


def _dialect_of(connection: object) -> str:
    """Name the dialect of a DBAPI connection, conservatively.

    Only ``sqlite`` is recognised positively. Everything else is reported as
    ``other`` and receives the Postgres spelling — including the role grants —
    because the production target is Postgres and an unrecognised driver is far
    likelier to share Postgres's ``DEFAULT`` grammar and its role model than
    SQLite's, which has neither.
    """
    module = type(connection).__module__ or ""
    if module.split(".")[0] == "sqlite3":
        return "sqlite"
    return "other"


# ── The statements ───────────────────────────────────────────────────────────


def _role_grant_statements(role: str = ROLE) -> tuple[str, ...]:
    """The Postgres role grants that make ``trial_ledger`` append-only.

    Feature 92's enforcement half: a role permitted only to read and append,
    with every row-mutating privilege explicitly revoked. Granting ``SELECT``
    and ``INSERT`` alone would already refuse ``UPDATE`` and ``DELETE`` (an
    ungranted privilege is denied), but the explicit ``REVOKE`` makes the
    append-only intent legible in the DDL and defeats any later ``GRANT`` to
    ``PUBLIC``. Postgres-only: SQLite has no roles and never sees these.
    """
    return (
        # CREATE ROLE has no IF NOT EXISTS, so guard it: the migration stays
        # re-runnable on a database whose cluster already holds the role.
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            CREATE ROLE {role} LOGIN;
          END IF;
        END
        $$;
        """,
        # The only two privileges the append path needs: read the prior
        # sequence on a retry (feature 95), and append the new row.
        f"GRANT SELECT, INSERT ON trial_ledger TO {role}",
        # Explicitly deny every privilege that would let the write path alter
        # or destroy a row once written. Revoking an ungranted privilege is a
        # no-op, so this is idempotent alongside the GRANT above.
        f"REVOKE UPDATE, DELETE, TRUNCATE ON trial_ledger FROM {role}",
    )


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    Every statement is idempotent. The column list, keys and defaults are the
    spec's schema block in its order, with three dialect-only branches: the
    serial primary key (:func:`_primary_key_definition`), the one defaulted
    timestamp (:func:`_now_default`), and the role grants, which are appended
    for the Postgres dialect only — SQLite has no roles, so a SQLite run sees
    the ``CREATE TABLE`` alone.
    """
    pk = _primary_key_definition(dialect)
    now_default = _now_default(dialect)
    create = f"""
    CREATE TABLE IF NOT EXISTS trial_ledger (
        {pk},
        ts               TIMESTAMPTZ NOT NULL DEFAULT {now_default},
        node_id          UUID NOT NULL,
        campaign_id      UUID NOT NULL,
        evaluator_hash   CHAR(64) NOT NULL,
        snapshot_hash    CHAR(64) NOT NULL,
        cost_model_hash  CHAR(64) NOT NULL,
        epoch_id         TEXT NOT NULL,
        charge_units     REAL NOT NULL DEFAULT 1.0,
        charges_budget   BOOLEAN NOT NULL,
        outcome          TEXT NOT NULL
    )
    """
    stmts = [create]
    # Feature 92: the append-only enforcement is a Postgres role model. SQLite
    # has no roles, so the grants are a Postgres-only branch — a SQLite run
    # (the database every test executes against) sees the table alone.
    if dialect != "sqlite":
        stmts += _role_grant_statements()
    return tuple(stmts)


def _drop_statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    One table and no indexes. The role is cluster-global and holds privileges
    on the table, so it is dropped only *after* the table — ``DROP ROLE``
    refuses a role that still holds privileges on a live object. The role drop
    is a Postgres-only branch, mirroring :func:`statements`: a SQLite downgrade
    is the single ``DROP TABLE IF EXISTS`` the other SQLite-only migrations run.
    """
    drops = [f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)]
    drops += [f"DROP INDEX IF EXISTS {index}" for index in reversed(INDEXES)]
    if dialect != "sqlite":
        drops.append(f"DROP ROLE IF EXISTS {ROLE}")
    return tuple(drops)


# ── Running it ───────────────────────────────────────────────────────────────


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Create the table (and, on Postgres, the role) on ``connection``.

    Returns the statements executed. Takes any DBAPI connection; the caller
    owns the transaction — this function neither commits nor rolls back, so a
    caller already inside a transaction (a migration runner, a test) does not
    have its unit of work split by an implicit commit. Use a context manager,
    or call :func:`apply`, which opens and commits its own SQLite connection.

    ``dialect`` overrides detection. Detection exists so the common case needs
    no argument; see :func:`_dialect_of` for what it recognises and why an
    unrecognised connection receives the Postgres spelling, role grants
    included.
    """
    resolved = dialect if dialect is not None else _dialect_of(connection)
    ddl = statements(resolved)
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


def downgrade(connection: object) -> tuple[str, ...]:
    """Drop the table (and, on Postgres, the role) this migration created.

    Destructive by definition. It is idempotent, and it drops only what this
    migration creates — a database downgraded here is refilled by the write
    path's next append, which creates the table idempotently. The role is
    dropped after the table so ``DROP ROLE`` is not refused by a lingering
    privilege; see :func:`_drop_statements`. The dialect is detected so a
    SQLite downgrade runs the single-table drop and never meets a role
    statement SQLite cannot parse.
    """
    resolved = _dialect_of(connection)
    ddl = _drop_statements(resolved)
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
    constraint enforcement the rest of the spine sees.
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
    revision. Safe to call repeatedly and on a database whose write path has
    already appended rows. On SQLite this creates the table alone; the Postgres
    role grants are never part of a SQLite ``apply``.
    """
    with closing(connect(database_url)) as connection, connection:
        return upgrade(connection)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """``python <this file> [upgrade|downgrade]`` against ``DATABASE_URL``.

    A runner's escape hatch, not a replacement for one: it exists so the
    statements in this file can be exercised against a real database without
    Alembic being installed, which is the state of this workspace today.

    ``argv`` reads the command line, and no argument means ``upgrade``. Reading
    ``sys.argv`` is deliberate: 0108's and 0109's escape hatches ignore it,
    which makes those files' advertised ``[downgrade]`` word unreachable from
    the shell — a defect this file does not repeat.
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
