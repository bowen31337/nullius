"""The regime_coverage table, in one versioned migration (feature 107).

app_spec.xml feature 107: "System creates the regime_coverage table counting
stored worlds per regime stratum." One table, three columns — the smallest
migration in the tree, and the one a promotion decision will someday read
under time pressure, so the shape is argued here as carefully as the big ones.

What the table is for
---------------------

The replay pool grows monotonically with calendar time, and that is its
danger. A pool built during six months of low-volatility chop *is* six months
of low-volatility chop; a meta-policy selected over it learns a chop-optimal
search policy, and the first thing that finding out costs you is the regime
break. That is docs/alpha-engine-prd.md §C7 — "Regime coverage ledger" — whose
risk table names this exact remedy: "Replay pool is regime-monotone | High |
§C7 coverage ledger with promotion block".

The ledger is the remedy. One row per *named* regime stratum, holding how
many stored worlds the pool carries in that stratum, makes the skew countable
where it was previously invisible. Everything downstream of the count is
another feature's machinery and all of it reads this table:

* the coverage ledger endpoint (feature 284) and ``GET /metrics/regime-coverage``
  report the rows as stored world counts per stratum;
* promotion is *blocked* when the deployment regime's row sits below the
  configured threshold (feature 285, §C7's "Block promotion");
* an ``empty_stratum`` warning fires when a named stratum holds 0 stored
  worlds (feature 286);
* a regime-diversity claim is refused while fewer than three strata hold
  stored worlds (feature 289);
* the counts themselves are persisted per stratum by the regime plugin
  (feature 283), which assigns each stored world to a stratum with the causal
  rolling-window labeler (feature 290).

The strata are names, not rows, on the writer side: feature 283 names them —
"high-volatility trend", "low-volatility chop", "crash" — and the shipped
labeler already carves exactly those three
(:data:`feature_store.regime_labeler.DEFAULT_K`, whose comment cites feature
283: the labeler's clusters are the regimes this table counts coverage
across). The migration stores whatever names the plugin writes; it does not
enumerate them, because the day the stratum set changes is a configuration
change in the labeler, not a schema change here.

Five details are load-bearing
-----------------------------

1. ``world_count`` is ``NOT NULL DEFAULT 0``, and the default is the point,
   not decoration. §C7's own example ledger is ``{high-vol trend: 2,
   low-vol chop: 14, crash: 0, …}`` — it *writes the zero*. A stratum that
   is named and empty must be a row with a 0, because feature 286's
   ``empty_stratum`` warning fires on exactly that state; an absent row means
   a stratum nobody named, which is a different fact and must stay
   distinguishable. Making the insert of a named-empty stratum a one-column
   ``INSERT INTO regime_coverage (stratum) VALUES (?)`` is what the default
   buys.
2. ``stratum`` is spelled ``NOT NULL PRIMARY KEY``, where the spec's schema
   block writes a bare ``TEXT PRIMARY KEY``. That is the same deliberate
   correction ``0108_forward_and_universe_tables`` makes for its three bare
   keys, and it is worth restating the half of the argument that applies
   here: SQLite does **not** make a rowid table's primary key ``NOT NULL``,
   and NULLs compare distinct, so a bare key accepts any number of
   NULL-stratum rows. This column is the ledger's whole identity — one row
   per named stratum — and Postgres makes the two spellings the same table,
   so the explicit spelling is the one that means the spec's sentence on
   both dialects. (Verified against SQLite directly: the corrected spelling
   refuses a NULL stratum and a duplicate; a bare key accepts two NULL
   rows.) Every writer supplies a real name, so nothing that would have
   worked is refused.
3. ``updated_at`` is ``NOT NULL DEFAULT NOW()`` — the *vintage* of the
   count. A coverage number is only evidence while you know when it was
   last true, so the column cannot be nullable, and the default stamps the
   two-row insert path for free. On ``UPDATE`` the default does not apply
   (a SQLite/Postgres default fires at insert, when the column is omitted),
   so a writer refreshing a count re-stamps explicitly — a writer contract
   the regime plugin owns; stated here so the column's meaning is readable
   from the DDL alone rather than from the plugin that happens to exist.
4. No foreign keys, deliberately. The things being counted are stored
   worlds — files in the replay pool (feature 188 persists 40-50 generated
   bootstrap worlds there on demand), not rows in any table this database
   holds; there is no ``world`` table to reference, and inventing one here
   would be schema this feature was not asked for. The stratum names come
   from the labeler's configuration, not a lookup table either. So the row
   is a materialised aggregate over facts that live outside the database —
   that is what a ledger *is* — and the honest spelling of that is no
   ``REFERENCES`` clause pretending otherwise.
5. No indexes. The table holds one row per named stratum — three today —
   and both dialects already give the primary key its own index, so the
   only access pattern (look up a stratum) is covered by the key itself.
   The rule is the one ``0108`` states: "a migration is the wrong place to
   invent a query plan for readers that do not exist yet." No shipped code
   reads this table; if the regime plugin's reader ever wants more than the
   key provides, that index is the plugin's to add, beside its queries.

Convergence with the plugin that will write it
----------------------------------------------

Unlike 0108's six tables, no shipped code creates ``regime_coverage`` today
— this migration is its *first* creator, so there is no store statement to
adopt and the shape is the spec's own: the schema block's three columns in
its order, with the two spelling corrections argued in details 2 and 3 as
the only departures. Features 283+ (the regime plugin) are being written
against the same spec block; when the plugin lands with its own
``CREATE TABLE IF NOT EXISTS``, whichever ran first is the winner and the
statements agree, because both take the spec's columns and both are
idempotent.

Dialect
-------

The repository runs SQLite on a single machine (the app spec's dev
allowance, and what ``tests/conftest.py`` points ``DATABASE_URL`` at) and
Postgres 16 in production (§9.1 of docs/nullius-tech-architecture.md).
Exactly one construct in this table's DDL does not survive that split:
``DEFAULT NOW()``. SQLite's ``DEFAULT`` grammar accepts a function call only
parenthesised, and it has no ``NOW()`` at all — the spelling there is
``DEFAULT (datetime('now'))``, which yields UTC at second resolution.
Second resolution is not a compromise: it is the clock convention the
shipped stores already use (``ledger.record.utc_now`` drops microseconds
for the stated reason that sub-second precision buys nothing a reader of
these tables needs), so a default-minted ``updated_at`` is the same *kind*
of value the rest of the spine writes by hand. Everything else —
``TIMESTAMPTZ``, ``TEXT``, ``INT`` — is accepted by SQLite as a column type
(it applies its own affinity), so there is no second schema to keep in step.

An unknown dialect receives the Postgres spelling, which is the spec's —
the same policy as 0108: a caller running something else is off the
documented path, and silently handing it a SQLite expression would hide
that.

Revision chaining
-----------------

No migration tree was assembled when 0108 landed — no ``alembic.ini``, no
``env.py`` — so it declared ids by convention: ``<feature index, zero-padded
to four>_<slug>``, chained in the spec's own feature order. This file keeps
that convention, with one difference worth stating: 0108's
:data:`DOWN_REVISION` already names ``0107_regime_coverage``. The id is
therefore *pinned by a shipped sibling* — this module's
:data:`REVISION` is not a fresh choice but the making-true of the name 0108
already chains after, and that is why it is exactly four digits plus the
table's own name.

:data:`DOWN_REVISION` is feature 106's id under the same convention. No
data dependency forces it — this table references nothing (detail 4) — but
a root revision per feature would leave the tree with multiple heads and
fail ``alembic upgrade head`` outright, whereas one guessed predecessor is
a one-line edit when the sibling lands. The slug below follows 0108's
naming style for a two-table feature (``forward_and_universe_tables``);
if feature 106's file lands under a different slug, :data:`DOWN_REVISION`
is the single string to reconcile.

Two consequences, both inherited from 0108's situation and still true here:

* This module imports nothing from Alembic. Alembic is not a dependency of
  this workspace and is not in ``uv.lock``; importing it would make this
  file unimportable and untestable. The module-level ``revision`` /
  ``down_revision`` / ``upgrade`` / ``downgrade`` names are the surface
  Alembic looks for, so it is a drop-in revision when the tooling lands —
  but the module runs today, standalone and stdlib-only, through
  :func:`apply`.
* Postgres is not spoken here without a driver. :func:`apply` opens SQLite
  itself, because the stdlib can; a Postgres caller passes its own DBAPI
  connection to :func:`upgrade` and this module never pretends to have one.

Idempotency and re-runnability
------------------------------

The statement is ``IF NOT EXISTS`` and ``downgrade`` is ``DROP TABLE IF
EXISTS``, so upgrade is re-runnable against a database that already holds
the table, and a downgrade followed by an upgrade round-trips to the same
schema. ``downgrade`` drops only this table — a downgraded database is one
the regime plugin's next persist refills (it creates the table
idempotently), not one left broken.
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

#: This migration's revision id (feature 107). Not a free choice: the shipped
#: 0108_forward_and_universe_tables chains after exactly this name, so the id
#: is the one that sibling already declares. See the module docstring.
REVISION = "0107_regime_coverage"

#: The revision this one chains after — feature 106's, under the same
#: convention. No data dependency forces it (this table references nothing);
#: the one string to reconcile if the sibling lands under another slug. See
#: the module docstring.
DOWN_REVISION = "0106_replay_and_policy_tables"

# Alembic's own module-level names, aliased to the constants above so the file
# is a drop-in revision without the values being spelled twice.
revision = REVISION
down_revision = DOWN_REVISION
branch_labels = None
depends_on = None

#: Tables that must already exist for this migration to be valid on a dialect
#: that validates foreign keys at DDL time (Postgres). Empty because this
#: table references nothing: the counted worlds live in the replay pool, not
#: in a table, and stratum names come from the labeler's configuration — see
#: detail 4 in the module docstring.
REQUIRES_TABLES: tuple[str, ...] = ()

#: The tables this migration creates, in creation order.
TABLES = ("regime_coverage",)

#: The indexes this migration creates — none. The table holds one row per
#: named stratum (three today), the primary key is its own index on both
#: dialects, and no shipped code reads the table; a query plan for readers
#: that do not exist yet is the regime plugin's to add, beside its queries.
#: See detail 5 in the module docstring.
INDEXES: tuple[str, ...] = ()

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store).
DATABASE_URL_ENV = "DATABASE_URL"

# ── Dialect ──────────────────────────────────────────────────────────────────

#: The Postgres default: the spec's own spelling for the ledger's vintage.
_POSTGRES_NOW_DEFAULT = "NOW()"

#: The SQLite equivalent. SQLite has no ``NOW()`` and its ``DEFAULT`` grammar
#: accepts a function call only parenthesised — the same trap 0108 documents
#: for ``gen_random_uuid()``, arriving here because this is the first table
#: in the tree that *does* need a defaulted timestamp. ``datetime('now')``
#: yields UTC at second resolution, which is the clock convention the shipped
#: stores already write (``ledger.record.utc_now`` drops microseconds).
_SQLITE_NOW_DEFAULT = "(datetime('now'))"


def _now_default(dialect: str) -> str:
    """The ``updated_at`` default for ``dialect``.

    The only construct in this migration that differs between dialects; see
    the module docstring. An unknown dialect gets the Postgres spelling,
    which is the spec's — a caller running something else is off the
    documented path, and silently handing it a SQLite expression would hide
    that.
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

    The statement is idempotent. The column list is the spec's schema block,
    in its order; the two departures from the block's spelling — ``NOT NULL``
    on ``stratum`` and the dialect-split ``updated_at`` default — are argued
    in the module docstring, details 2 and 3.
    """
    now_default = _now_default(dialect)
    return (
        # Feature 107 / §C7. One row per named regime stratum, holding how
        # many stored worlds the replay pool carries there. `stratum` carries
        # NOT NULL explicitly where the spec's block writes a bare
        # `TEXT PRIMARY KEY`: SQLite's rowid-table keys do not imply NOT NULL
        # and NULLs compare distinct, so the bare spelling would admit any
        # number of nameless rows against a ledger whose whole identity is
        # one row per name. `world_count` defaults to 0 because §C7's own
        # example ledger writes `crash: 0` — a named stratum with no worlds
        # is a coverage hole this row *is*, not an absence; feature 286's
        # empty_stratum warning reads exactly that state. `updated_at` is the
        # count's vintage: NOT NULL because a coverage number without a
        # timestamp is not evidence, and defaulted so the one-column insert
        # of a named-empty stratum is stamped by the table itself (an UPDATE
        # re-stamps explicitly — the plugin's writer contract).
        f"""
        CREATE TABLE IF NOT EXISTS regime_coverage (
            stratum     TEXT NOT NULL PRIMARY KEY,
            world_count INT NOT NULL DEFAULT 0,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT {now_default}
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
    regime plugin's next persist, which creates the table idempotently.
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

    The same convention ``universe.store`` uses, and deliberately re-stated
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
    means ``upgrade``. Reading ``sys.argv`` is deliberate: 0108's escape
    hatch ignores it, which makes that file's advertised ``[downgrade]``
    word unreachable from the shell — a defect left to its owner to fix,
    not copied here.
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
