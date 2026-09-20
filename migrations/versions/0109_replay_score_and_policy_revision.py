"""The replay_score and policy_revision tables, in one versioned migration.

app_spec.xml feature (index 1, the tree's root): "System creates the
replay_score table plus the policy_revision table recording policy version,
world id, beta and committed pick." Two tables, one migration: they are the
two ends of the same act — ``policy_revision`` names a candidate policy and
whether it was chosen, and ``replay_score`` is the per-world evidence that the
choice was made well.

Why these two tables belong together
------------------------------------

They are the ledger of a single decision. A dreaming cycle (the ``dreaming``
plugin, app_spec.xml §"Dreaming & policy revision") evaluates every candidate
revision against every stored world, writes one ``replay_score`` row per
(candidate, world) pair, aggregates those scores, and records the argmax winner
as the ``selected`` row of ``policy_revision``. Neither table is meaningful
without the other:

* ``replay_score`` is the *evidence* — one row per run carrying the policy
  version under test, the world it was replayed against, the ``beta`` at which
  it was scored, the resulting ``score``, and the ``committed_pick`` the policy
  would have made. Read whole it is the objective surface the selection walks;
  read per ``policy_version`` it is that version's aggregate.
* ``policy_revision`` is the *outcome* — the versioned policy identity
  (``policy_version``, ``parent_version``, ``code_hash``), its
  ``aggregate_score`` over the pool, and the ``selected`` flag that marks the
  one the cycle committed to.

They are read together — a revision's aggregate is the aggregation of its
scores — so they share one schema version rather than a window where the
scores exist but the revision they belong to does not. This is also the honest
grouping of the spec, which put both tables in one feature.

Dialect
-------

The repository runs SQLite on a single machine (the app spec's dev allowance,
and what ``tests/conftest.py`` points ``DATABASE_URL`` at) and Postgres 16 in
production (§9.1). The spec's DDL is Postgres spelling, and two constructs in
it do not survive the trip:

* ``DEFAULT gen_random_uuid()`` is a syntax error in SQLite, whose grammar
  allows no function call in a ``DEFAULT`` clause unless it is parenthesised.
* ``DEFAULT NOW()`` fails the same way, for the same reason — and here it is
  not avoidable by omission, because both tables carry a defaulted
  ``created_at``.

``UUID``, ``TIMESTAMPTZ``, ``REAL``, ``TEXT``, ``CHAR(64)`` and ``BOOLEAN`` are
all accepted by SQLite as column types (it applies its own affinity), so the
column lists are otherwise identical between dialects and there is no second
schema to keep in step.

The two expressions are translated per dialect:

* the UUID default is an RFC 4122 version-4 UUID built from ``randomblob`` (see
  :data:`_SQLITE_UUID_DEFAULT`), so an id minted by the default is the same
  *kind* of value as ``gen_random_uuid()`` returns — the variant and version
  nibbles are the ones a v4 UUID must carry rather than whatever the random
  source produced. A caller that needs a specific id still supplies one; the
  default exists so that ``INSERT ... (policy_version, world_id, beta, score)``
  is a complete statement.
* the timestamp default is ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` wrapped in
  the parentheses SQLite's ``DEFAULT`` grammar requires — an ISO-8601 UTC
  timestamp string, the textual twin of Postgres's ``timestamptz``. A caller
  reading it back gets the same wall-clock instant the production row carries,
  as text rather than as a typed timestamp; the rest of the spine stores its
  timestamps the same way, so nothing downstream is surprised.

Every primary key is spelled ``NOT NULL PRIMARY KEY``
-----------------------------------------------------

Both ``replay_score.id`` and ``policy_revision.id`` are declared by the spec as
a bare ``UUID PRIMARY KEY``, and both are written here with an explicit
``NOT NULL``. That is a deliberate correction, not fussiness, and it is worth
stating because the opposite choice looks harmless.

Postgres makes a primary key's columns ``NOT NULL`` implicitly, so on
production the two spellings are the same table. SQLite does **not**: on a
rowid table a bare ``PRIMARY KEY`` permits NULL, and because NULLs compare
distinct from one another it permits *several* NULL-keyed rows. So the bare
spelling would let a SQLite database hold two rows with a null ``id`` — a state
these tables exist to make impossible, since every row must be addressable by a
real key (``policy_revision`` is the identity of a committed policy;
``replay_score`` is the evidence keyed to it). A uniqueness guarantee that
holds in production and silently lapses in the database every test runs against
is worse than either failure on its own.

Anything that writes these tables supplies a real key, so nothing that works
against a bare-key table is refused here; and because the statements are
``IF NOT EXISTS``, a database whose stores created the tables first is left
exactly as it was — the tightening can only apply where this migration is the
thing that creates the table.

``policy_version`` uniqueness
-----------------------------

``policy_revision.policy_version`` is ``TEXT NOT NULL UNIQUE``. The ``UNIQUE``
constraint is load-bearing rather than decorative: a policy version is a name
for a specific policy, and two revisions sharing a version string would be two
different policies answering to one name — the exact ambiguity that makes a
replay_score's ``policy_version`` column unreadable, since a score row would no
longer point at one revision. Postgres and SQLite both enforce ``UNIQUE`` at
row-write time, so unlike the UUID default this construct survives the dialect
trip unchanged and needs no translation.

``replay_score.committed_pick`` is nullable
-------------------------------------------

``committed_pick UUID`` carries no ``NOT NULL`` — a candidate that was scored
but not selected has no committed pick to record, and a fabricated nil would
read as a real trade. The column is the policy's *decision*, and a decision
that was never made must stay distinguishable from one that was. ``is_holdout``
defaults to ``FALSE`` for the same reason ``world_count`` does in
``0107_regime_coverage``: the flag is written by an insert that need not name
it, and the default keeps that insert a one-column-shorter statement.

Revision chaining
-----------------

This migration chains after ``0108_forward_and_universe_tables`` under the
repository's convention — the id is ``<feature index, zero-padded to four>_<slug>``
and ``down_revision`` is the predecessor's id. Feature 108 is this file's
predecessor in the spec's own ordering. The spec's feature index for this pair
of tables is 1 (the tree's declared root), but the *revision id* follows the
migration-tree convention of :mod:`0108_forward_and_universe_tables`, which
pads the feature's position in the assembled chain rather than the spec's
feature index — hence ``0109``. This is the one fact a reader assembling the
tree should reconcile, and it is stated here rather than discovered later.

Idempotency and re-runnability
------------------------------

Every statement is ``IF NOT EXISTS`` and ``downgrade`` is ``DROP TABLE IF
EXISTS`` in reverse dependency order, so upgrade is re-runnable against a
database that already holds the tables, and a downgrade followed by an upgrade
round-trips to the same schema.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

__all__ = [
    "DATABASE_URL_ENV",
    "DOWN_REVISION",
    "INDEXES",
    "REVISION",
    "TABLES",
    "apply",
    "connect",
    "downgrade",
    "statements",
    "upgrade",
]

# ── Version identity ─────────────────────────────────────────────────────────

#: This migration's revision id. See the module docstring for the naming
#: convention and why it is ``0109`` rather than the spec's feature index.
REVISION = "0109_replay_score_and_policy_revision"

#: The revision this one chains after — feature 108's, under the same
#: convention.
DOWN_REVISION = "0108_forward_and_universe_tables"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: The tables this migration creates, in creation order. ``replay_score``
#: references nothing that ``policy_revision`` creates, so the order is
#: immaterial; it is listed first because it is the evidence the revision
#: aggregates.
TABLES = (
    "replay_score",
    "policy_revision",
)

#: This migration creates no indexes. Both tables are keyed by their ``id``
#: primary keys and ``policy_revision.policy_version`` is ``UNIQUE`` (which
#: carries its own implicit index); a query plan for readers that do not exist
#: yet is the wrong thing for a migration to invent.
INDEXES = ()

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

    The only ``id`` construct that differs between dialects; see the module
    docstring. An unknown dialect gets the Postgres spelling, which is the
    spec's — a caller running something else is off the documented path, and
    silently handing it a SQLite expression would hide that.
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

    Every statement is idempotent. Column lists, keys and constraints are the
    spec's, with the two dialect-only splits (the UUID and timestamp defaults)
    translated and the two bare primary keys tightened to ``NOT NULL``.
    """
    uuid_default = _uuid_default(dialect)
    now_default = _now_default(dialect)
    return (
        # Feature 1 / §"Dreaming & policy revision". One row per (candidate
        # policy, stored world) replay: `policy_version` names the policy under
        # test, `world_id` the world it was replayed against, `beta` the
        # risk-aversion at which it was scored, `score` the resulting objective,
        # and `committed_pick` the trade the policy would have made. `score` is
        # ``NOT NULL`` — a row in this table is the record of a completed
        # scoring, and a null score would be a scoring that did not happen; the
        # spec writes it ``REAL NOT NULL`` and this is the spelling that means
        # it. `committed_pick` is nullable on purpose — it is absent for a
        # candidate that was scored but never selected, and a fabricated nil
        # would read as a real trade. `is_holdout` defaults to FALSE so the
        # holdout flag need not be named on insert.
        f"""
        CREATE TABLE IF NOT EXISTS replay_score (
            id             UUID NOT NULL PRIMARY KEY DEFAULT {uuid_default},
            policy_version TEXT NOT NULL,
            world_id       UUID NOT NULL,
            beta           REAL NOT NULL,
            score          REAL NOT NULL,
            committed_pick UUID,
            is_holdout     BOOLEAN NOT NULL DEFAULT FALSE,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT {now_default}
        )
        """,
        # Feature 1 / §"Dreaming & policy revision". The versioned policy
        # identity: `policy_version` is its name (UNIQUE — two revisions may
        # not share one, or a replay_score's policy_version would no longer
        # point at a single revision), `parent_version` the version it was
        # derived from, `code_hash` the hash of the policy's code,
        # `aggregate_score` its score aggregated over the pool, and `selected`
        # the flag marking the one the cycle committed to. `parent_version` and
        # `aggregate_score` are nullable — a root revision has no parent, and a
        # revision not yet aggregated has no score. `selected` defaults to
        # FALSE so the flag need not be named on insert.
        f"""
        CREATE TABLE IF NOT EXISTS policy_revision (
            id              UUID NOT NULL PRIMARY KEY DEFAULT {uuid_default},
            policy_version  TEXT NOT NULL UNIQUE,
            parent_version  TEXT,
            code_hash       CHAR(64) NOT NULL,
            aggregate_score REAL,
            selected        BOOLEAN NOT NULL DEFAULT FALSE
        )
        """,
    )


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse dependency order.

    Referencing tables are dropped before what they reference, so the sequence
    is valid on a dialect that checks a drop's dependents. (Neither table here
    declares a foreign key, so the order is immaterial, but it is kept
    consistent with the rest of the tree.)
    """
    drops = [f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)]
    drops += [f"DROP INDEX IF EXISTS {index}" for index in reversed(INDEXES)]
    return tuple(drops)


# ── Running it ───────────────────────────────────────────────────────────────


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Create the tables on ``connection``; returns the statements executed.

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
    """Drop the tables this migration created; returns the statements executed.

    Destructive by definition. It is idempotent, and it drops only the objects
    this migration creates — a database downgraded here is refilled by the next
    persist of each store, which creates its own table idempotently.
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
    """Create the tables in a SQLite database; returns the statements executed.

    The standalone entry point: opens the database named by ``database_url`` (or
    ``DATABASE_URL``) and commits the migration in one transaction, so a caller
    with no migration runner can still bring a database to this revision. Safe
    to call repeatedly and on a database whose stores already created the
    tables.
    """
    with closing(connect(database_url)) as connection, connection:
        return upgrade(connection)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """``python <this file> [upgrade|downgrade]`` against ``DATABASE_URL``.

    A runner's escape hatch, not a replacement for one: it exists so the
    statements in this file can be exercised against a real database without
    Alembic being installed, which is the state of this workspace today.
    """
    args = list(argv if argv is not None else ("upgrade",))
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
