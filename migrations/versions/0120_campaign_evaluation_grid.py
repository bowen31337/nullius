"""The campaign's evaluation grid, in one versioned migration.

additions_spec_engine_edge_recovery.xml, "Campaign Grid", feature 4:
*System records on every campaign the evaluation grid it ran on*
(``evaluation_config_sha256``, ``horizon``, ``grid_first_date``,
``grid_last_date``, ``oos_first_date``) *and backfills the existing campaigns
from their stored artifacts, so that any later reader can tell whether a
campaign's in-sample period precedes a given out-of-sample grid and at which
horizon its picks were selected.*  Five nullable columns, added to the
``campaign`` table ``0111_campaign_table.py`` creates, and nothing else.

Why the row, and not the node
-----------------------------

A campaign selected its picks on **one** grid: ``campaign``'s own row is the
object the diagnosis needed to filter on.  The 17 of 103 campaigns M3 scored
as financial holdout worlds whose in-sample grids ended *inside* the
out-of-sample window (docs/preregistration/2026-10-17-m3-dreaming.RESULT.md,
the erratum) are campaigns, not nodes, and "nothing records a campaign's
grid, so nothing could filter on it" is the admission defect
``docs/research/2026-10-19-alpha-diagnosis.md`` names.  The five columns land
on the row every reader of a campaign already opens.

Why each column is nullable, and carries no default
---------------------------------------------------

Every one of the five is **measured off the run**, not decided at planning
time: ``horizon`` and the grid's two ends come from the evaluation context a
particular deployment ran under, ``evaluation_config_sha256`` from the file
``NULLIUS_EVALUATION_CONFIG`` named, and ``oos_first_date`` from the
out-of-sample grid that config carried — which a configuration may omit
entirely (``oos_dates`` is optional; ``_context``: *"an empty tuple when the
document omits it, which means no OOS window rather than an invented one"*).
A campaign the backfill cannot place on one of the three known grids is
reported and left ``NULL``, and a fabricated default would read as a grid
that was actually measured.  So each column is a bare ``ADD COLUMN`` with no
``NOT NULL`` and no ``DEFAULT`` — the same reading ``0114_node_metrics``
states from its own side for the seven metrics: *"a pre-metric row has no
honest value to assert"*, and SQLite's ``ADD COLUMN`` grammar permits no
other spelling for a table that may already hold rows.

All five columns take types both dialects accept (``TEXT``, ``INTEGER``), so
there is no second schema to keep in step and no dialect branch is needed:
SQLite applies its own affinity to both.

Dates are ISO text
------------------

``grid_first_date``, ``grid_last_date`` and ``oos_first_date`` are stored as
ISO-8601 calendar-date text (``YYYY-MM-DD``), which is what the evaluation
config document itself carries (``"evaluation_dates": ["2026-09-01", ...]``)
and what sorts correctly as text — the comparison a reader makes with them is
*does this grid end before that one*, and lexical order is date order for a
zero-padded ISO date.  The alternative, a date column, buys nothing a reader
of this column needs and costs a dialect split.

Existing rows read NULL
-----------------------

Every row the table already holds gains the five columns valued ``NULL``: the
artifact a campaign ran is not on its row, which is exactly why
:mod:`orchestrator.backfill_campaign_grid` exists — it reads the grid back
off one of the campaign's stored ``ic_series.parquet`` files and fills these
columns, one JSON line per campaign it fills or leaves ``NULL``.

Revision identity
-----------------

``0120`` is this file's position in the assembled chain and its predecessor
is the chain's previous head, ``0119_canary_reference_pair`` — the id and the
``down_revision`` link, per the convention every file in this tree states.
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
    "COLUMNS",
    "DATABASE_URL_ENV",
    "DOWN_REVISION",
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

#: This migration's revision id.  ``0120`` because it follows ``0119`` in the
#: assembled chain — the id is the chain position, the convention this tree
#: states in every file.
REVISION = "0120_campaign_evaluation_grid"

#: The revision this one chains after — the chain's head when this file lands.
DOWN_REVISION = "0119_canary_reference_pair"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: The table this migration alters.  Feature 104's ``0111`` creates it; this
#: file adds the five grid columns to it and nothing else.
CAMPAIGN_TABLE = "campaign"

#: Tables that must already exist for this migration to be valid.  ``campaign``
#: is the one, and ``0111`` — a sibling feature this file does not own — is
#: what creates it; on both dialects an ``ALTER`` against a missing table fails
#: loudly rather than silently altering nothing.
REQUIRES_TABLES: tuple[str, ...] = (CAMPAIGN_TABLE,)

#: The tables this migration creates — none.  It alters a table a sibling
#: feature creates, and the constant is kept so ``TABLES + COLUMNS`` stays the
#: uniform shape a reader can iterate over every migration in this tree.
TABLES: tuple[str, ...] = ()

#: The five columns this migration adds to ``campaign``, in the order the
#: feature sentence names them.  No sixth column is added on this file's
#: authority, and every one is nullable with no default (see the module
#: docstring).
COLUMNS: tuple[str, ...] = (
    "evaluation_config_sha256",
    "horizon",
    "grid_first_date",
    "grid_last_date",
    "oos_first_date",
)

#: The column type each of the five carries.  Two types, ``TEXT`` for the
#: digest and the three ISO dates and ``INTEGER`` for the horizon, both of
#: which SQLite and Postgres 16 accept as written.
_TYPES: dict[str, str] = {
    "evaluation_config_sha256": "TEXT",
    "horizon": "INTEGER",
    "grid_first_date": "TEXT",
    "grid_last_date": "TEXT",
    "oos_first_date": "TEXT",
}

#: The environment variable naming the relational store, shared with every
#: other member of the data spine.
DATABASE_URL_ENV = "DATABASE_URL"


# ── The statements ───────────────────────────────────────────────────────────


def _add_statement(column: str) -> str:
    """The ``ALTER TABLE ... ADD COLUMN`` statement for ``column``.

    Written with an explicit ``NULL`` rather than a bare type so the
    nullability is stated where a reader looks for it: a column added to a
    table that may already hold rows must be nullable, and SQLite's grammar
    permits no ``NOT NULL`` there without a ``DEFAULT`` (which would fabricate
    a measurement).
    """
    return f"ALTER TABLE {CAMPAIGN_TABLE} ADD COLUMN {column} {_TYPES[column]} NULL"


def statements(dialect: str = "other") -> tuple[str, ...]:
    """The DDL this migration runs, for ``dialect``, in execution order.

    Returned as data rather than executed so the DDL is inspectable — a reader
    (or a test) can see what a migration will do without a database, which is
    the property that makes a migration reviewable at all.

    ``dialect`` selects nothing: this migration mints no id, defaults no
    timestamp and grants no role, and ``ALTER TABLE ... ADD COLUMN ... TEXT
    NULL`` is valid on SQLite and Postgres alike.  The parameter is part of
    this tree's uniform interface.
    """
    _ = dialect  # accepted for the uniform interface; selects nothing today
    return tuple(_add_statement(column) for column in COLUMNS)


def _drop_statements() -> tuple[str, ...]:
    """The DDL that reverses :func:`statements`, in reverse creation order.

    Five column drops and nothing else: the ``campaign`` table and every row
    in it belong to the features that create and write it, and a downgrade of
    *this* revision must leave them exactly as it found them.  ``DROP COLUMN``
    is supported by the workspace's SQLite and by Postgres, so no dialect
    branch is needed.
    """
    return tuple(
        f"ALTER TABLE {CAMPAIGN_TABLE} DROP COLUMN {column}"
        for column in reversed(COLUMNS)
    )


# ── Running it ───────────────────────────────────────────────────────────────


def _present_columns(connection: object) -> set[str]:
    """The set of column names ``campaign`` already carries on ``connection``.

    The probe :func:`upgrade` uses to decide which ``ALTER`` statements to run:
    a column already present is left untouched, so a database that already
    holds some or all of the five — a prior run of this migration, or a store
    that wrote one — is a no-op rather than a duplicate ``ADD COLUMN`` (which
    SQLite and Postgres both refuse).  SQLite's ``ADD COLUMN`` carries no
    ``IF NOT EXISTS``, so the probe is what makes the upgrade re-runnable.
    """
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({CAMPAIGN_TABLE})")  # type: ignore[attr-defined]
    }


def upgrade(connection: object, dialect: Optional[str] = None) -> tuple[str, ...]:
    """Add the five grid columns to ``campaign`` on ``connection``.

    Returns the statements executed.  Takes any DBAPI connection; the caller
    owns the transaction — this function neither commits nor rolls back, so a
    caller already inside a transaction (a migration runner, a test) does not
    have its unit of work split by an implicit commit.  Use a context manager,
    or call :func:`apply`, which opens and commits its own SQLite connection.

    Only columns the table does not already hold are added, so the upgrade is
    idempotent.  Every row the table already holds reads ``NULL`` in the five
    columns afterwards — the grid a campaign ran on is not on its row, which
    is what :mod:`orchestrator.backfill_campaign_grid` fills.
    """
    _ = dialect  # accepted for the uniform interface; dialect selects nothing
    present = _present_columns(connection)
    ddl = tuple(
        _add_statement(column) for column in COLUMNS if column not in present
    )
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        for statement in ddl:
            cursor.execute(statement)
    finally:
        cursor.close()
    return ddl


def downgrade(connection: object) -> tuple[str, ...]:
    """Drop the five grid columns this migration added; returns them run.

    Destructive only to what this revision added.  It is idempotent, it never
    drops the ``campaign`` table, and it never deletes a row — a database
    downgraded here keeps every campaign the system planned and loses only the
    grid record, which :func:`upgrade` puts back and the backfill refills.
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
    not depend on a workspace package being importable in order to run.
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
    """Open the SQLite store named by ``database_url`` (or ``DATABASE_URL``)."""
    url = database_url if database_url is not None else os.environ[DATABASE_URL_ENV]
    path = _sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def apply(database_url: Optional[str] = None) -> tuple[str, ...]:
    """Add the five columns in a SQLite database; returns the statements run.

    The standalone entry point: opens the database named by ``database_url``
    (or ``DATABASE_URL``) and commits the migration in one transaction, so a
    caller with no migration runner can still bring a database to this
    revision.  Safe to call repeatedly.
    """
    with closing(connect(database_url)) as connection, connection:
        return upgrade(connection)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """``python <this file> [upgrade|downgrade]`` against ``DATABASE_URL``."""
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
