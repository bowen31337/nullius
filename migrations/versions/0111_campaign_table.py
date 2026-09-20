"""The campaign table, in one versioned migration.

app_spec.xml: "System creates the campaign table recording campaign type,
workspace count, null fraction and calibration_status." One table, five
columns plus the two the schema block carries beyond the headline four —
``ks_pvalue`` and ``created_at`` — and the one the whole calibration
discipline leans on, because it is where a campaign's planted-null rate is
fixed before any node is expanded.

What the table is for
---------------------

A campaign is the unit the discovery loop runs against: a discovery tree of
``W`` wells, one planted-null world, a KS guard that decides whether the run
was calibrated. The PRD fixes the planted-null fraction before the campaign
begins — §4.1.1's ``φ = clip(2/W, 0.15, 0.35)`` — and that fraction is a
property of the campaign, not of any node inside it, so it belongs on this
row. Everything downstream of a campaign reads this table:

* the discovery orchestrator writes the campaign record before any node is
  expanded (the spec's "before any node is expanded" ordering — the fraction
  is fixed at planning time, not learned from the run);
* the KS guard persists the two-sample Kolmogorov–Smirnov p-value that tests
  whether the planted nulls are detectable (PRD §4.3), and writes
  ``calibration_status = 'VOID'`` when it falls below 0.05 — the moment a
  campaign's calibration is voided it is excluded from the replay pool and
  dreaming halts (features 876, 1056);
* the metrics store records sensitivity and specificity on the planted nulls
  per campaign, keyed back here.

The ``id`` is a minted UUID, the campaign's own identity, separate from
``node.campaign_id`` — that column is a reference to this row, the link by
which every node in the tree is traced back to the campaign that spawned it
(``0108_forward_and_universe_tables`` declares ``node`` in its
:data:`REQUIRES_TABLES`; this table references nothing, so it is free to land
in either order).

The two dialect splits
----------------------

The repository runs SQLite on a single machine (the app spec's dev
allowance, and what ``tests/conftest.py`` points ``DATABASE_URL`` at) and
Postgres 16 in production (§9.1 of docs/nullius-tech-architecture.md). The
spec's DDL is Postgres spelling, and two constructs in it do not survive the
trip to SQLite's ``DEFAULT`` grammar:

* ``DEFAULT gen_random_uuid()`` is a syntax error in SQLite, whose grammar
  allows no function call in a ``DEFAULT`` clause unless it is parenthesised.
* ``DEFAULT NOW()`` fails the same way, for the same reason — and here it is
  not avoidable by omission, because this table carries a defaulted
  ``created_at``.

``UUID``, ``TIMESTAMPTZ``, ``INT``, ``REAL``, ``TEXT`` and ``BOOLEAN`` are all
accepted by SQLite as column types (it applies its own affinity), so the
column list is otherwise identical between dialects and there is no second
schema to keep in step. The two expressions are translated per dialect:

* the UUID default is an RFC 4122 version-4 UUID built from ``randomblob`` (see
  :data:`_SQLITE_UUID_DEFAULT`), so an id minted by the default is the same
  *kind* of value as ``gen_random_uuid()`` returns — the variant and version
  nibbles are the ones a v4 UUID must carry rather than whatever the random
  source produced. A caller that needs a specific id still supplies one; the
  default exists so that ``INSERT ... (campaign_type, workspace_count,
  null_fraction)`` is a complete statement.
* the timestamp default is ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` wrapped in
  the parentheses SQLite's ``DEFAULT`` grammar requires — an ISO-8601 UTC
  instant string, the textual twin of Postgres's ``timestamptz``. A caller
  reading it back gets the same wall-clock instant the production row carries,
  as text rather than as a typed timestamp; the rest of the spine stores its
  timestamps the same way, so nothing downstream is surprised.

Every primary key is spelled ``NOT NULL PRIMARY KEY``
-----------------------------------------------------

``campaign.id`` is declared by the spec as a bare ``UUID PRIMARY KEY``, and is
written here with an explicit ``NOT NULL``. That is a deliberate correction,
not fussiness, and it is worth stating because it is the one place the spec's
Postgres spelling would silently misbehave on the database every test runs
against. Postgres makes a primary key's columns ``NOT NULL`` implicitly, but
SQLite does **not** — on a rowid table a bare ``PRIMARY KEY`` permits NULL,
and because NULLs compare distinct it permits *several* NULL-keyed rows. A
second campaign row with a NULL id would split the campaign's identity: the
nodes referencing it by a real id would be orphaned from the row the fraction
was fixed on, and the KS guard's ``calibration_status`` write would land on a
row the orchestrator never meant to create. A uniqueness guarantee that holds
in production and silently lapses in the database every test runs against is
worse than either failure on its own. (Verified against SQLite directly, as in
0107 and 0108: the bare spelling accepts two NULL-id rows; the tightened one
refuses a NULL and a duplicate.) Every writer here either supplies an id or
relies on the default, which never yields NULL, so nothing that would have
worked against a bare-key table is refused.

The other columns
-----------------

``campaign_type TEXT NOT NULL`` — the campaign's assignment regime. The PRD
carries two — Type-R (~70%, a root null inherits its null status down the
whole subtree) and Type-D (~30%, all roots real, a branch flips null at a
randomised depth) — and §4.1.2 forbids mixing them within one tree, so the
value is one of a known set, recorded here so a reader can tell which regime a
completed campaign ran under. It is ``NOT NULL`` with no default because a
campaign with no type is not a campaign the planner created.

``workspace_count INT NOT NULL`` — ``W``, the well count of the discovery
tree. It is the denominator of the null fraction (§4.1.1's ``2/W``), recorded
as the count the campaign was planned with. ``INT`` and ``NOT NULL`` with no
default — a campaign is created with a known workspace count, and a null count
would be a campaign that was never planned.

``null_fraction REAL NOT NULL`` — ``φ``, the planted-null fraction, fixed at
planning time as ``clip(2/W, 0.15, 0.35)``. It is the headline design choice of
a campaign and the number the whole blinding discipline is built around, so it
is stored, not derived, and stored ``NOT NULL`` — a campaign without a null
fraction is the one thing the planner never ships. No default, because the
clip is a planning computation with a floor and a ceiling, not a constant the
table could supply; the value that lands here is the planner's, already
clipped.

``calibration_status TEXT NOT NULL DEFAULT 'ok'`` — the campaign's calibration
verdict. It defaults to ``'ok'`` so a freshly created campaign is calibrated
by construction without naming the column, and the KS guard advances it to
``'VOID'`` when its p-value falls below 0.05. The default is the point, not
decoration: it is the same role ``FALSE`` defaults play in
``replay_score.is_holdout`` and ``policy_revision.selected`` — the row is
written at campaign creation, before the KS test has run, and "not yet voided"
is the honest state for a campaign whose read has not happened. ``'ok'`` is
spelled as a literal default rather than a keyword because SQLite has no
boolean keyword for a text column; the value is the spec's own.

``ks_pvalue REAL`` — the two-sample KS p-value comparing the in-sample scores
of null nodes against real nodes (PRD §4.3). Nullable, and deliberately so: a
freshly created campaign has not been read, so it has no p-value yet, and a
``NOT NULL`` here would force a fabricated zero on a campaign whose KS test has
not run — which would read as "tested, and decisively detectable", the exact
opposite of "not yet tested". The guard fills it at read time; the orchestrator
does not.

``created_at TIMESTAMPTZ NOT NULL DEFAULT <now>`` — when the campaign record
was created. The row *is* the creation event, and the default records the
instant it happened; unlike ``null_fraction`` it is a fact the table can mint
honestly, because "now" is always the right value for the moment a row is
written. It is the one defaulted timestamp, and the reason this migration
carries the ``NOW()`` split alongside the UUID split.

Revision chaining
-----------------

This file's revision id is ``0111``: the tree's convention (stated by 0108,
reaffirmed by 0109 and 0110) pads the feature's *position in the assembled
chain*, not its spec feature index, because the spec's feature order and the
landing order have already diverged. This migration is the fifth in the
assembled chain — ``0107`` → ``0108`` → ``0109`` → ``0110`` → this one — hence
``0111``.

:data:`DOWN_REVISION` names ``0110_epoch_ledger`` — the head this branch
actually holds, a committed file. The one string to reconcile if the chain is
ever renumbered is this constant. This table references nothing (the epochs
and nodes it relates to are named by writers, not looked up here), so it
imposes no ordering constraint on the chain and :data:`REQUIRES_TABLES` is
empty.

Idempotency and re-runnability
------------------------------

The statement is ``IF NOT EXISTS`` and ``downgrade`` is ``DROP TABLE IF
EXISTS``, so upgrade is re-runnable against a database that already holds the
table, and a downgrade followed by an upgrade round-trips to the same schema.
``downgrade`` drops only this table — a downgraded database is one the
orchestrator's next campaign creation refills, not one left broken. Nothing in
the tree references this table yet, so the drop is never refused by a
dependent — the constraint that blocked 0110's drop has no counterpart here.
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
#: assembled chain (fifth), not its spec feature index — see the module
#: docstring for the convention and why the chain position wins.
REVISION = "0111_campaign_table"

#: The revision this one chains after — the head the branch actually holds when
#: this file lands. Not a convention guess: 0110 is committed, so this is the
#: one chain fact in this file that was read rather than predicted.
DOWN_REVISION = "0110_epoch_ledger"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: Tables that must already exist for this migration to be valid on a dialect
#: that validates foreign keys at DDL time (Postgres). Empty because this
#: table references nothing: the campaign's identity is minted here, and the
#: nodes, trials and metrics that relate to a campaign carry ``campaign_id`` as
#: a reference *to* this row, not the other way round.
REQUIRES_TABLES: tuple[str, ...] = ()

#: The tables this migration creates, in creation order.
TABLES = ("campaign",)

#: The indexes this migration creates — none. The table is written once per
#: campaign and read whole or looked up by its minted id, which the primary
#: key already indexes on both dialects. The rule is the one 0108 states: a
#: migration is the wrong place to invent a query plan for readers that do not
#: exist yet.
INDEXES: tuple[str, ...] = ()

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── Dialect ──────────────────────────────────────────────────────────────────

#: The Postgres default for an ``id`` column: the spec's own spelling, and the
#: reason a Postgres ``id`` needs no value supplied.
_POSTGRES_UUID_DEFAULT = "gen_random_uuid()"

#: The SQLite equivalent: an RFC 4122 version-4 UUID, built from ``randomblob``
#: so the variant and version nibbles are the ones a v4 UUID must carry rather
#: than whatever the random source happened to produce. The surrounding
#: parentheses are required — SQLite's ``DEFAULT`` grammar accepts a function
#: call only when it is parenthesised, which is precisely why the spec's
#: ``gen_random_uuid()`` is a syntax error there.
_SQLITE_UUID_DEFAULT = (
    "(lower("
    "hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || "
    "substr(hex(randomblob(2)), 2) || '-' || "
    "substr('89ab', abs(random()) % 4 + 1, 1) || "
    "substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6))"
    "))"
)

#: The Postgres default for a defaulted timestamp: the spec's own ``NOW()``.
_POSTGRES_NOW_DEFAULT = "NOW()"

#: The SQLite equivalent: the current UTC instant as an ISO-8601 string, in the
#: parentheses SQLite's ``DEFAULT`` grammar requires. It is the textual twin of
#: Postgres's ``timestamptz`` — the same wall-clock instant, read back as text
#: rather than as a typed timestamp, which is how the rest of the spine stores
#: its timestamps.
_SQLITE_NOW_DEFAULT = "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"


def _uuid_default(dialect: str) -> str:
    """The ``id`` column default for ``dialect``.

    The first of the two constructs that differ between dialects; see the
    module docstring. An unknown dialect gets the Postgres spelling, which is
    the spec's — a caller running something else is off the documented path,
    and silently handing it a SQLite expression would hide that.
    """
    return _SQLITE_UUID_DEFAULT if dialect == "sqlite" else _POSTGRES_UUID_DEFAULT


def _now_default(dialect: str) -> str:
    """The defaulted-timestamp column default for ``dialect``.

    The second of the two dialect splits; see the module docstring. Same
    unknown-dialect policy as :func:`_uuid_default`.
    """
    return _SQLITE_NOW_DEFAULT if dialect == "sqlite" else _POSTGRES_NOW_DEFAULT


def _dialect_of(connection: object) -> str:
    """Name the dialect of a DBAPI connection, conservatively.

    Only ``sqlite`` is recognised positively. Everything else is reported as
    ``other`` and receives the spec's Postgres spelling, because the production
    target is Postgres and an unrecognised driver is far likelier to be
    Postgres-compatible than to share SQLite's ``DEFAULT`` grammar.
    """
    module = type(connection).__module__ or ""
    if module.split(".")[0] == "sqlite3":
        return "sqlite"
    return "other"


# ── The statements ───────────────────────────────────────────────────────────


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    Every statement is idempotent. The column list, keys and defaults are the
    spec's, with the two dialect-only splits (the UUID and timestamp defaults)
    translated and the bare primary key tightened to ``NOT NULL``.
    """
    uuid_default = _uuid_default(dialect)
    now_default = _now_default(dialect)
    return (
        # Feature / §4.1. One row per campaign, written before any node is
        # expanded: `campaign_type` is the assignment regime (Type-R root
        # nulls or Type-D depth nulls, never mixed in one tree per §4.1.2),
        # `workspace_count` is W, the well count of the discovery tree, and
        # `null_fraction` is φ = clip(2/W, 0.15, 0.35) fixed at planning time —
        # the denominator of the whole blinding discipline, stored not
        # derived. `calibration_status` defaults to 'ok' so a freshly created
        # campaign is calibrated by construction; the KS guard advances it to
        # 'VOID' when its p-value falls below 0.05. `ks_pvalue` is nullable for
        # exactly one state — a campaign not yet read — and a NOT NULL here
        # would fabricate a decisive p-value on a campaign the guard has not
        # tested. `id` carries NOT NULL explicitly where the spec's block
        # writes a bare `UUID PRIMARY KEY`: on SQLite a bare key accepts NULL
        # and several of them, and a second NULL-id campaign row would split
        # the campaign's identity and orphan the nodes referencing it.
        f"""
        CREATE TABLE IF NOT EXISTS campaign (
            id                 UUID NOT NULL PRIMARY KEY DEFAULT {uuid_default},
            campaign_type      TEXT NOT NULL,
            workspace_count    INT NOT NULL,
            null_fraction      REAL NOT NULL,
            calibration_status TEXT NOT NULL DEFAULT 'ok',
            ks_pvalue          REAL,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT {now_default}
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

    ``dialect`` overrides detection. Detection exists so the common case needs
    no argument; see :func:`_dialect_of` for what it recognises and why an
    unrecognised connection gets the spec's Postgres spelling.
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
    """Drop the table this migration created; returns the statements executed.

    Destructive by definition. It is idempotent, and it drops only the object
    this migration creates — a database downgraded here is refilled by the
    orchestrator's next campaign creation, which creates the table
    idempotently. Nothing in the tree references this table, so the drop is
    never refused by a dependent.
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
    revision. Safe to call repeatedly and on a database whose orchestrator has
    already created the table.
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
