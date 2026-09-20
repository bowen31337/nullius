"""Feature 86's store: the append, and the monotonically increasing sequence.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 86: *System
persists one trial_ledger row per evaluation under a monotonically
increasing sequence number.*  docs/nullius-tech-architecture.md §8 states
what this table is for — *"The honest ``K`` counter.  Append-only
write-ahead log, never a mutable table."* — and fixes the row's shape.
This module is the writing half of feature 86's sentence: one INSERT per
evaluation, and the number the table hands the row.

**One row per evaluation.**  :meth:`TrialLedger.append` performs exactly
one INSERT and returns exactly one
:class:`~ledger.record.TrialLedgerRecord`; a caller debits once per
evaluation and the table grows by one.  Two ``append`` calls are two
rows, even for the same node — at feature 86 the honest counter counts
what it is told, and the idempotent debit keyed by ``node_id`` is a
different operation, not a changed one: :meth:`TrialLedger.debit`
(feature 95, exposed over the wire as POST /ledger/debit by
:mod:`ledger.debit`) appends only when the node holds no row yet and is
answered by the prior row when it does — the contract §14 states for
spot-reclaimed eval workers ("Failures retry; ledger debits are
idempotent by ``node_id``").  The idempotence lives at that seam and not
in a UNIQUE constraint on the column because §8's own DDL declares none
and the raw append must keep its two-calls-two-rows contract; the
check-and-insert runs inside one transaction on one connection
(``INSERT … SELECT … WHERE NOT EXISTS``), so a debit racing its own
retry cannot double-charge.  Nothing here updates, nothing deletes: the
API offers no such spelling.

**The refusal is enforced, not merely conventional (feature 92).**  The
spec's own sentence refuses to rest at "the API offers no such spelling":
the refusal must hold against a hand that reaches past it — a raw
connection, a second package, an operator script, a bug — so every
statement the store issues runs through one guarded seam
(:meth:`TrialLedger._execute`), and an UPDATE or DELETE targeting
``trial_ledger`` is refused with :class:`~ledger.errors.TrialImmutableError`
before it touches a row.  That is the SQLite spelling of feature 103's
Postgres "role grants that deny UPDATE and DELETE": where the production
database denies the privilege to the writing role, this member denies the
statement at the connection that speaks to the database, because SQLite
has no roles to grant to.  The check is by statement shape and names the
table, so a mutation of another table, and every non-mutating statement
(``CREATE``, ``INSERT``, ``SELECT``, ``PRAGMA``), runs unchanged; the
:func:`guarded` context manager exposes the same wall to any caller that
wants a raw statement against this database without opting out of the
append-only guarantee.

**The sequence is monotonic because the table says so, not because the
rows happen to accumulate.**  The column is SQLite's ``INTEGER PRIMARY
KEY AUTOINCREMENT``, and ``AUTOINCREMENT`` is load-bearing.  Without it
the column would be a bare rowid alias, and SQLite assigns a bare rowid
as ``max(rowid) + 1`` — delete the highest row and the *next* append
reuses a number already spent, and the sequence goes down.  With it,
SQLite tracks a high-water mark in its ``sqlite_sequence`` table that
deletes never lower, so a number once assigned is never reassigned for
the life of the database.  That is the SQLite spelling of §8's Postgres
``BIGSERIAL PRIMARY KEY`` — the guarantee, not merely the type — and it
is why the monotonicity holds across connections and processes: the
sequence's state is persisted beside the rows, not derived from them.
Feature 103's versioned migration writes the Postgres DDL and adopts
this statement's shape; both spellings agree that the number is the
table's to assign, never the writer's to choose.

**The columns are the ones the append itself owns.**  ``seq``, ``ts``,
``node_id``, ``campaign_id``, ``outcome``, ``charges_budget``,
``charge_units`` — §8's
first four, the ones that say *which evaluation was charged, when, in
what order*, plus the outcome (feature 91), the one that says *how it
ended*: 'ok', 'timeout', 'error' or 'tripwire_fail', the closed
vocabulary of :mod:`ledger.outcome`, refused at the write when absent or
misspelled because a failed evaluation still consumed a hypothesis and
its charge must be classifiable; the budget directive (feature 90), the
one that says *whether it charged statistical budget*: a genuine bool
supplied by the caller (the null oracle's opaque directive), refused at
the write when it is not a bool because a ``1`` or a ``0`` or an absent
``None`` is not the oracle's directive; and the charge unit (feature
89), the one that says *what it cost*: a positive finite real defaulting
to ``1.0`` — §8's own ``DEFAULT`` — because an ordinary evaluation is
worth one unit while a cross-validated one whose folds each compare a
fit against the same forward returns states its own count.  The unit and
the directive are the two halves of the charge that are easy to confuse
and are deliberately not the same fact: the directive says whether the
trial spent statistical degrees of freedom at all, the unit says how
much evaluation it took.  The provenance triple (feature 87) and the
epoch (88) are
their features' stamps and land as columns on this same table as they
arrive, the way this store upgraded in place for the outcome, the
directive and the unit.

``ts`` is stored as ISO-8601 UTC text with an explicit
offset — canonical, lexicographically ordered for a single offset, and
revalidated through the record constructor on read, so a row that
wandered in from outside cannot smuggle a naive stamp past the write-time
check.  ``charges_budget`` is stored as the ``0``/``1`` a SQLite
``BOOLEAN`` column stores, and ``charge_units`` as the ``REAL`` the
column holds, both revalidated through the same constructor, so a stored
directive that is neither bit, or a unit that is not a positive finite
real, is refused rather than served.  The two stamps are written
explicitly by both write paths even where the column carries a
``DEFAULT``, so the row the append returns and the row the table holds
are one value however the caller reached the append; the ``DEFAULT`` is
what keeps the column honest for a writer that is not this store.

**A pre-outcome database is upgraded in place, not refused.**  ``CREATE
TABLE IF NOT EXISTS`` cannot evolve a table that already exists, so a
database written by the four-column schema of features 86-95 would
otherwise reject every append with "no column named outcome".  The
store brings such a table forward the way the universe member's store
brings a pre-floor build table forward: ``PRAGMA table_info`` names the
columns it holds, and an ``outcome`` that is missing is added by
``ALTER TABLE … ADD COLUMN outcome TEXT NOT NULL DEFAULT 'ok'`` — the
one value among the four a row that predates outcome recording can
carry honestly.  Those rows recorded no failure (the outcome-bearing
charge of feature 84 arrives with this column), so 'timeout',
'error' and 'tripwire_fail' would fabricate a failure the ledger never
observed, while 'ok' asserts only the absence of a recorded failure —
the same reasoning that gave the universe's legacy builds
``min_dollar_volume = 0``.  The ``ALTER`` is neither an ``UPDATE`` nor
a ``DELETE`` — it restates no past charge, adds no charge, and spends
no sequence number — so it passes feature 92's wall and runs on the
same guarded connection every other statement does: the wall is a
mutation wall, not a schema freeze, and this is the upgrade that proves
it.

**Storage is the workspace's relational store**, addressed by
``DATABASE_URL`` exactly as the universe and snapshot members' tables
are: ``sqlite:///`` on a single machine (the spec's allowance, and what
the shared test fixtures point at), Postgres in production once the
migration member lands.  A URL whose scheme is not ``sqlite`` is refused
by name rather than spoken with a dialect it may not match.  A
*pathless* sqlite URL — the in-memory spelling — is refused too, on a
ledger-specific ground: this store opens a connection per operation (the
workspace's discipline; the file is the coordination point), and an
in-memory SQLite database dies with its connection, so a second append
would start the sequence over at 1.  A ledger that silently restarts its
count is the exact failure this category exists to make impossible; a
caller who wants a scratch ledger points at a temporary *file*.

The schema is created idempotently on connect — and an older one
upgraded in place, as the previous paragraph states — so a fresh
database's first debit brings the table into being and no migration
step is needed for this member.

**A configured store that fails is loud; an absent one is discoverable.**
:meth:`TrialLedger.resolve` returns ``None`` when no ``DATABASE_URL`` is
set — an unconfigured ledger composes no component, mirroring the
factory's degrade-don't-break stance — while a store that *is* configured
and whose write fails raises :class:`~ledger.errors.TrialStoreError`,
because a debit that silently failed to persist is an evaluation that
consumed a hypothesis while the honest counter looked away.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from .budget import validated_charges_budget
from .epochusage import EpochUsage, derive_epoch_usage
from .errors import TrialImmutableError, TrialRecordError, TrialStoreError
from .keffective import KEffective, derive_k_effective
from .outcome import validated_outcome
from .record import TrialLedgerRecord, _validated_instant, _validated_uuid, utc_now
from .units import DEFAULT_CHARGE_UNITS, validated_charge_units

__all__ = [
    "DATABASE_URL_ENV",
    "EPOCH_LEDGER_TABLE",
    "TRIAL_LEDGER_TABLE",
    "TrialLedger",
]

#: The environment variable naming the relational store, shared with the
#: rest of the workspace (the universe and snapshot members' tables read
#: the same one; the repository-level conftest points it at a per-test
#: database).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table feature 86 appends to — §8's own name for it.
TRIAL_LEDGER_TABLE = "trial_ledger"

#: The table feature 96's usage counts are read from — feature 105's own
#: name for it, and the name ``migrations/versions/0110_epoch_ledger.py``
#: creates.  Spelled once here so the read and the migration cannot drift
#: apart on what the epoch ledger is called.
EPOCH_LEDGER_TABLE = "epoch_ledger"

#: The two columns feature 96's read projects out of ``epoch_ledger``:
#: the epoch's name (feature 105's ``TEXT NOT NULL PRIMARY KEY``) and the
#: running count of promotion decisions it has served (feature 294's
#: column, ``INT NOT NULL DEFAULT 0``).
_EPOCH_LEDGER_COLUMNS = "epoch_id, promotion_decisions_served"

#: The table's DDL.  See the module docstring for why ``AUTOINCREMENT``
#: is the load-bearing word and why these columns are this store's whole
#: column set — §8's first four plus feature 91's outcome and feature
#: 90's charges_budget directive.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TRIAL_LEDGER_TABLE} (
    -- The monotonically increasing sequence number, assigned by the
    -- table.  AUTOINCREMENT makes a spent number never reusable (SQLite
    -- keeps a high-water mark that deletes do not lower); a bare rowid
    -- alias would reuse max+1 after a delete of the maximum, and the
    -- Postgres spelling of this guarantee is §8's BIGSERIAL.
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    -- When the charge was debited: ISO-8601 UTC with an explicit offset.
    ts          TEXT NOT NULL,
    -- The evaluated node, canonical UUID spelling.
    node_id     TEXT NOT NULL,
    -- The campaign the node belongs to, canonical UUID spelling.
    campaign_id TEXT NOT NULL,
    -- How the evaluation ended (feature 91): one of the closed
    -- vocabulary 'ok' | 'timeout' | 'error' | 'tripwire_fail', §8's own
    -- comment on this column.  NOT NULL with no default — unlike
    -- charge_units (feature 89, DEFAULT 1.0, below) there is no honest
    -- presumption: the caller must say how the trial ended, and the
    -- write is refused when it does not.
    outcome     TEXT NOT NULL,
    -- Whether the trial consumed statistical budget (feature 90): the
    -- opaque directive §7.2's null oracle returns alongside the target
    -- series, True for a real trial, False for a null node.  BOOLEAN NOT
    -- NULL with no default — the directive is the caller's to state,
    -- never the table's to presume, and a row that predates the null
    -- oracle is brought forward with the honest 'TRUE' (see
    -- _upgrade_legacy_ledger_table).  Stored as the 0-or-1 a SQLite
    -- BOOLEAN column stores.
    charges_budget  BOOLEAN NOT NULL,
    -- What the trial cost, in units (feature 89): §8's own comment on
    -- the column is "1.0 default; CV folds may cost more", and the
    -- default is the load-bearing half — an ordinary evaluation is
    -- worth exactly one unit, so an append or a debit that states
    -- nothing is charged one, while a cross-validated evaluation whose
    -- folds each compare a fit against the same forward returns states
    -- its own count.  The store writes the validated value explicitly
    -- rather than leaning on this DEFAULT, so the row the append returns
    -- and the row the table holds are one value; the DEFAULT is what
    -- makes the column honest for a writer that is not this store.
    --
    -- The column closes the declaration: §8 orders charge_units before
    -- charges_budget, but this table's columns follow the order the
    -- features that own them *landed* — §8's first four, then the
    -- outcome, the directive and now the unit — which is the order the
    -- record's row() tuple mirrors and the order every reader unpacks.
    -- SQLite appends an ALTER's column after whatever the table already
    -- held, so a fresh table and a brought-forward one agree on it.
    charge_units    REAL NOT NULL DEFAULT 1.0
);
"""

# The read path's column list, in the table's declaration order.  One
# string shared by every SELECT so the reader and the record cannot drift
# apart in column order — the failure that would silently swap an
# identity for a stamp.
_COLUMNS = "seq, ts, node_id, campaign_id, outcome, charges_budget, charge_units"

# Feature 88's epoch stamp, read by feature 93's derivation when the table
# carries it.  The column arrives with a sibling feature, so it is *probed*
# for rather than assumed (see _has_epoch_column); a table that predates it
# is read as one bucket of un-named epochs rather than refused.
_EPOCH_COLUMN = "epoch_id"

# Feature 92's seam: refuse an UPDATE or DELETE against trial_ledger before
# it runs.  The check is by statement shape, not by trust — it names the
# table, so a mutation of another table on the same database is not this
# store's concern, and a statement that merely *mentions* the table in a
# SELECT is not refused.  A leading-stripped, whitespace-collapsed scan of
# the statement's first token catches the verb however it is cased and
# however it is padded or prefixed with a common table expression, because
# the refusal must meet the *attempt*, exactly as a denied privilege does.
_MUTATION_RE = re.compile(
    r"^\s*(?:WITH\s+\w+\s+AS\s*\(.*?\)\s*)?(UPDATE|DELETE)\b",
    re.IGNORECASE | re.DOTALL,
)


def _immutability_violation(statement: str) -> Optional[str]:
    """The verb of a statement that would mutate ``trial_ledger``, else ``None``.

    Returns ``"UPDATE"`` or ``"DELETE"`` when the statement's mutating verb
    targets the trial_ledger table — matched by the table's own name, the
    one constant :data:`TRIAL_LEDGER_TABLE` carries, so the check and the
    DDL cannot drift apart — and ``None`` for every statement that must run
    unchanged: a CREATE, INSERT, SELECT or PRAGMA, and a mutation of any
    other table.  The table is matched whether it is qualified or not and
    however it is separated from the verb, so ``UPDATE trial_ledger SET …``
    and ``DELETE FROM trial_ledger WHERE …`` are both caught, while
    ``DELETE FROM other_table`` and ``SELECT * FROM trial_ledger`` are not.
    """
    match = _MUTATION_RE.match(statement)
    if match is None:
        return None
    # The verb is only refused when it names trial_ledger as its target.
    # UPDATE names the table directly after the verb; DELETE names it after
    # FROM.  Both are checked against the canonical table name.
    verb = match.group(1)
    if verb.upper() == "UPDATE":
        target = _MUTATION_RE.sub("", statement, count=1)
        names_table = re.match(
            r"\s*" + re.escape(TRIAL_LEDGER_TABLE) + r"\b", target, re.IGNORECASE
        )
    else:  # DELETE
        names_table = re.search(
            r"\bFROM\s+" + re.escape(TRIAL_LEDGER_TABLE) + r"\b",
            statement,
            re.IGNORECASE,
        )
    return verb if names_table else None


def _guarded_statement(statement: str) -> None:
    """Refuse a statement that would mutate ``trial_ledger``.

    The single enforcement point every store statement runs through.  A
    mutating statement against trial_ledger raises
    :class:`~ledger.errors.TrialImmutableError`, naming the table and the
    verb, before the database is touched — so a refused mutation spends no
    sequence number and leaves the ledger exactly as it was.  Every other
    statement returns normally.
    """
    verb = _immutability_violation(statement)
    if verb is not None:
        raise TrialImmutableError(
            f"the trial_ledger table is append-only: a {verb} statement "
            f"against {TRIAL_LEDGER_TABLE} was refused before it ran.  "
            f"trial_ledger is an append-only write-ahead log (feature 92: "
            f"the refusal is enforced at the store's connection, the SQLite "
            f"spelling of feature 103's role grants that deny UPDATE and "
            f"DELETE); a mutated row would restate a past charge, which the "
            f"honest K counter never does.  Append a superseding row instead."
        )


class _GuardedConnection(sqlite3.Connection):
    """A ``sqlite3.Connection`` whose ``execute`` refuses trial_ledger mutations.

    The enforcement the store's own methods and :func:`guarded` share, made
    a property of the connection rather than of any one caller.  ``execute``
    runs :func:`_guarded_statement` first, so an UPDATE or DELETE against
    ``trial_ledger`` is refused with :class:`~ledger.errors.TrialImmutableError`
    before the statement reaches the database; every other statement runs
    unchanged.  ``executemany`` is left intact — the store never issues it,
    and a caller reaching for it is already outside the append path.  A
    subclass (selected via ``sqlite3.connect(..., factory=...)``) rather
    than a wrapped attribute, because ``Connection.execute`` is read-only.
    """

    def execute(self, statement: str, *parameters: Any) -> sqlite3.Cursor:  # type: ignore[override]
        _guarded_statement(statement)
        return super().execute(statement, *parameters)


@contextmanager
def guarded(database_url: str) -> Iterator[_GuardedConnection]:
    """A raw connection to ``database_url`` that keeps trial_ledger append-only.

    The enforcement a caller reaches for when it needs a raw statement
    against this database — an operator script, a derived view that must
    read with its own SQL — without opting out of feature 92's guarantee.
    Every statement executed on the yielded connection runs through the
    same wall the store's own methods do (:class:`_GuardedConnection`), so
    an UPDATE or DELETE against trial_ledger is refused with
    :class:`~ledger.errors.TrialImmutableError` however it is reached; a
    caller that wants to mutate must do so on a bare ``sqlite3.connect``
    of its own, fully outside this store, and cannot mistake that for the
    ledger's own API.

    The caller owns the connection and its transaction, exactly as a raw
    ``sqlite3.connect`` would give: commit or roll back before the block
    exits.  This is the SQLite counterpart of feature 103's Postgres role
    grants — where the production database denies the privilege to the
    writing role, this denies the statement at the seam that speaks to the
    database.
    """
    path = _sqlite_path(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, factory=_GuardedConnection)
    try:
        with connection:
            connection.executescript(_SCHEMA)
            _upgrade_legacy_ledger_table(connection)
        yield connection
    finally:
        connection.close()


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    Follows the SQLAlchemy convention the workspace's ``DATABASE_URL``
    already uses: ``sqlite:///foo.db`` is a relative path, and an absolute
    path carries its leading slash after the triple.  Any other scheme is
    refused loudly rather than silently mis-parsed — the Postgres store
    arrives with the migration member (feature 103), and pretending to
    speak it here would hide a misrouted URL behind a mysterious file.  A
    pathless URL (the in-memory spelling, bare or explicit) is refused on
    the ground the module docstring states: an in-memory database dies
    with its connection, and a ledger whose sequence restarts is worse
    than no ledger, because it is a wrong count wearing a right one's
    clothes.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise TrialStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            "the Postgres trial ledger arrives with the versioned migration"
        )
    if parsed.netloc not in ("", "localhost"):
        raise TrialStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path)
    if path.startswith("/"):
        path = path[1:]
    if not path or path == ":memory:":
        raise TrialStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and the trial sequence must survive the append that spent "
            "it — point at a file (a temporary one for a scratch ledger)"
        )
    return Path(path)


def _upgrade_legacy_ledger_table(connection: sqlite3.Connection) -> None:
    """Bring a pre-stamp ledger table up to the current schema, in place.

    ``CREATE TABLE IF NOT EXISTS`` cannot evolve a table that already
    exists, so a database written by an older schema would otherwise
    reject every append with "no column named …".  The upgrade adds each
    missing stamp column, in the order the features that own them landed,
    with the one default each can honestly carry:

    * ``outcome`` (feature 91) is added with the default 'ok' — the rows
      predate outcome recording, so they recorded no failure, and among
      the four outcomes only 'ok' asserts the absence of a recorded
      failure rather than fabricating one the ledger never observed.
    * ``charges_budget`` (feature 90) is added with the default ``TRUE`` —
      the rows predate the null oracle (features 109 on), so no null node
      was ever among them; every one was a real trial that consumed
      statistical degrees of freedom, and ``TRUE`` asserts exactly that
      and nothing more.  It is also the safe direction for the honest
      counter: counting a legacy row as budget-charging can only ever
      understate the deflation the null nodes introduce, never overstate
      it.  This is not a derivation and not the forbidden label — a
      legacy row names no null node to detect — it is the one honest
      statement a row that predates the directive can make.
    * ``charge_units`` (feature 89) is added with ``1.0`` — which is
      §8's own ``DEFAULT`` for the column rather than a value chosen
      here, and the honest statement a row that predates the unit stamp
      can make: those rows were written before a caller could state more
      than one unit, so every one of them was an ordinary evaluation
      worth exactly one.  ``1.0`` also keeps the honest counter's
      arithmetic unchanged across the upgrade — the legacy rows' cost is
      what it always was — where any other value would silently restate
      what those trials spent.

    Each ``ALTER`` is issued on the caller's connection (the guarded one
    every store operation opens) and passes feature 92's wall by its own
    terms: it is neither an ``UPDATE`` nor a ``DELETE``, restates no past
    charge and spends no sequence number — the wall is a mutation wall,
    not a schema freeze.  Idempotent by construction: a table that
    already holds the column is left untouched, so every connect after
    the first takes the same cheap path.  The columns are added in the
    order the features that own them landed — outcome, then the budget
    directive, then the unit — so a table written between any two of them
    (say one holding outcome but not charges_budget, a database written
    between features 91 and 90) is brought forward correctly rather than
    skipped.  That order is this upgrade's own and deliberately not the
    table's declaration order (§8 declares ``charge_units`` before
    ``charges_budget``): what matters is that every column a reader needs
    exists by the time this returns, and SQLite appends each ``ADD
    COLUMN`` after whatever the table already held, so a brought-forward
    table's physical order is its own history — which is exactly why the
    read path names its columns explicitly (:data:`_COLUMNS`) instead of
    relying on ``SELECT *``.
    """
    columns = {
        row[1] for row in connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
    }
    if "outcome" not in columns:
        connection.execute(
            f"ALTER TABLE {TRIAL_LEDGER_TABLE} "
            "ADD COLUMN outcome TEXT NOT NULL DEFAULT 'ok'"
        )
    if "charges_budget" not in columns:
        connection.execute(
            f"ALTER TABLE {TRIAL_LEDGER_TABLE} "
            "ADD COLUMN charges_budget BOOLEAN NOT NULL DEFAULT TRUE"
        )
    if "charge_units" not in columns:
        # Feature 89's unit, added with §8's own default (1.0) — the
        # column's DEFAULT in the spec's DDL, not a presumption invented
        # here.  The rows predate the unit stamp, so no cross-validated
        # evaluation is among them: every one was an ordinary trial worth
        # exactly one unit, and 1.0 asserts precisely that.  The read
        # coerces the stored REAL to a float, so the legacy rows read
        # back exactly as a fresh ordinary append's row does.
        connection.execute(
            f"ALTER TABLE {TRIAL_LEDGER_TABLE} "
            "ADD COLUMN charge_units REAL NOT NULL DEFAULT 1.0"
        )


def _has_epoch_column(connection: sqlite3.Connection) -> bool:
    """Whether the ledger table carries feature 88's ``epoch_id`` stamp yet.

    The probe the derived-view read uses to decide whether there is an
    epoch dimension to group by.  ``epoch_id`` is a *sibling* feature's
    column (feature 88: *System records epoch_id naming which sequestered
    epoch a trial charged*), so a table written before that stamp landed
    genuinely has no such column — and asking it to group by one would
    fail with "no such column" rather than answer.  Probing with ``PRAGMA
    table_info`` — the same seam the legacy upgrade reads columns through —
    lets feature 93's derivation answer honestly on both tables: one
    un-named bucket before the column exists, a real per-epoch breakdown
    after.  It reads the schema and never the rows, so it is a safe
    question to ask of an append-only table on every read.
    """
    columns = {
        row[1] for row in connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
    }
    return _EPOCH_COLUMN in columns


def _has_epoch_ledger_table(connection: sqlite3.Connection) -> bool:
    """Whether the ``epoch_ledger`` table exists yet.

    The probe feature 96's read uses to tell "no epoch was ever sealed"
    from "this deployment has an epoch ledger and it says nothing".  The
    table is feature 105's, created by the versioned migration
    (``migrations/versions/0110_epoch_ledger.py``) or by the promotion
    plugin's own idempotent create — not by this store, which owns no
    part of it — so on a database that has never sealed an epoch it is
    genuinely absent, and asking it for rows would fail with "no such
    table" rather than answer.  ``sqlite_master`` is read (never the
    rows), which makes it a safe question to ask on every read, and it is
    asked of the *table* rather than assumed because a store that
    answered a missing table with a zero would be inventing a pool size.
    """
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (EPOCH_LEDGER_TABLE,),
    ).fetchone()
    return row is not None


def _record_from_row(row: tuple[Any, ...]) -> TrialLedgerRecord:
    """Rebuild one row as a record, refusing a malformed row by its seq.

    The record constructor revalidates every field, so this is where a
    row that wandered in from outside the append — a hand-edited ``ts``,
    a zeroed ``seq`` — is refused rather than served.  The error carries
    the offending row's ``seq`` so an operator can find it: in an
    append-only log, one unreadable row is evidence, not noise.
    """
    try:
        return TrialLedgerRecord(
            seq=row[0],
            ts=row[1],
            node_id=row[2],
            campaign_id=row[3],
            outcome=row[4],
            charges_budget=row[5],
            charge_units=row[6],
        )
    except TrialRecordError as exc:
        raise TrialRecordError(
            f"trial_ledger row with seq={row[0]!r} is malformed and cannot "
            f"be read back: {exc}"
        ) from exc


def _validated_charge(
    node_id: Any,
    campaign_id: Any,
    outcome: Any,
    charges_budget: Any,
    charge_units: Any,
    ts: Optional[datetime],
    clock: Optional[Callable[[], datetime]],
) -> tuple[str, str, str, bool, float, datetime]:
    """Validate a charge's arguments, returning the canonical sextuple.

    The one spelling both write paths — :meth:`TrialLedger.append` and
    :meth:`TrialLedger.debit` — share, so the two cannot drift on what
    they accept: identities canonicalised to UUID text, the outcome held
    to feature 91's closed vocabulary (:func:`~ledger.outcome.
    validated_outcome` refuses an absent or misspelled one), the budget
    directive held to a genuine bool (:func:`~ledger.budget.
    validated_charges_budget` refuses a ``1``, a ``0`` or an absent
    ``None`` — the directive is supplied by the caller, never derived),
    the unit held to a positive finite real (:func:`~ledger.units.
    validated_charge_units` refuses a non-number, a NaN or an infinity,
    and anything at or below zero), and the stamp resolved from ``ts``
    when the caller knows when the charge happened (a replay debits the
    instant it reproduces, so the clock is never read when ``ts`` is
    given) and from ``clock()`` otherwise, defaulting to
    :func:`~ledger.record.utc_now`.  Every refusal lands here, *before*
    the database is touched, so a refused charge spends no sequence
    number and leaves the ledger exactly as it was.
    """
    node = _validated_uuid(node_id, "node_id")
    campaign = _validated_uuid(campaign_id, "campaign_id")
    ended = validated_outcome(outcome)
    directive = validated_charges_budget(charges_budget, strict=True)
    units = validated_charge_units(charge_units)
    if ts is not None:
        instant = _validated_instant(ts, "ts")
    else:
        source = utc_now if clock is None else clock
        if not callable(source):
            raise TrialRecordError(
                f"clock must be callable and return a datetime; got "
                f"{type(source).__name__}"
            )
        instant = _validated_instant(source(), "ts")
    return node, campaign, ended, directive, units, instant


class TrialLedger:
    """Reads and appends the ``trial_ledger`` table for one database.

    Bound to a database URL at construction; construction performs no
    I/O, so composing an application never touches the database.  Each
    operation opens its own connection (creating the schema idempotently
    if the table is absent), so the store holds no file handle across
    calls and the database file — not any process's memory — is the
    coordination point.  That is what makes the sequence's monotonicity
    a property of the ledger rather than of one session: two stores, two
    processes, two connections all draw from the same persisted
    high-water mark.

    The write surface is two spellings of one INSERT — :meth:`append`,
    the raw feature-86 charge that counts what it is told, and
    :meth:`debit`, feature 95's idempotent charge keyed by ``node_id`` —
    and neither ever issues an UPDATE or a DELETE.  There is no such
    method to call, by design; and feature 92's refusal is enforced at the
    connection itself — every operation opens a :class:`_GuardedConnection`
    whose ``execute`` refuses an UPDATE or DELETE against trial_ledger
    before it runs — so the same wall meets every client this package never
    met, not merely the append and debit methods.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise TrialStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Optional[Path] = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["TrialLedger"]:
        """The ledger ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the same way
        the shared fixtures and the snapshot member's manifest store treat
        their configuration.  Absent is not an error: it is a deployment
        without a relational store, which composes no ledger component —
        a discoverable state, not an exception — while the *evaluator*
        that needs to debit a trial is the caller that must not find
        itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this ledger appends to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this ledger, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time an
        operation needs it.  There is no ``None`` case: a pathless URL is
        refused rather than mapped to an in-memory database, for the
        reason the module docstring gives.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database, ensure the ledger's table, and arm the guard.

        The schema is created idempotently on every connect — upgrading a
        pre-outcome table in place, so a fresh database and an existing
        one take the same path and no migration step is needed for this
        member, the same contract the universe member's ``connect``
        states.  The connection is a
        :class:`_GuardedConnection`, so every statement the store issues —
        the append's INSERT, the debit's check-and-insert, the read paths'
        SELECT — runs through feature 92's wall: an UPDATE or DELETE
        against trial_ledger is refused with
        :class:`~ledger.errors.TrialImmutableError` before it touches a
        row, whatever method reached for it.  The refusal is thus a
        property of the store's connection, not of any one method's
        convention.  The caller owns the connection; use it as a context
        manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        # A _GuardedConnection: its execute refuses an UPDATE or DELETE
        # against trial_ledger before it runs (feature 92), so the append's
        # INSERT, the debit's check-and-insert and the read paths' SELECT
        # all run through the same wall, whatever method reached for the
        # table.  A subclass via ``factory=`` rather than a wrapped
        # attribute, because ``Connection.execute`` is read-only.
        connection = sqlite3.connect(path, factory=_GuardedConnection)
        with connection:
            connection.executescript(_SCHEMA)
            _upgrade_legacy_ledger_table(connection)
        return connection

    # -- Writing ------------------------------------------------------------

    def append(
        self,
        node_id: Any,
        campaign_id: Any,
        outcome: Any = None,
        charges_budget: Any = None,
        charge_units: Any = DEFAULT_CHARGE_UNITS,
        *,
        ts: Optional[datetime] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> TrialLedgerRecord:
        """Debit one evaluation: one INSERT, one sequence number, one row.

        The whole of feature 86 at its seam, carrying feature 91's
        outcome stamp, feature 90's budget directive and feature 89's
        charge unit.  The evaluation
        is named by ``node_id`` and ``campaign_id`` (a
        :class:`~uuid.UUID` or its text spelling, canonicalised on the
        way in) and by ``outcome`` — how it ended, one of 'ok',
        'timeout', 'error', 'tripwire_fail'
        (:data:`~ledger.outcome.OUTCOMES`).  The outcome has no default
        and is refused when absent: §6.1's step 11 debits *even when the
        node fails*, so the append must be told which of the four it is
        recording, and a row that could not say would be a charge no
        audit could classify.  ``charges_budget`` is the opaque budget
        directive — ``True`` when the trial consumed statistical budget,
        ``False`` for a null node — supplied by the caller (the null
        oracle returns it alongside the target series) and never derived
        by the ledger; it has no default and is refused when it is not a
        genuine bool, because a ``1`` or a ``0`` or an absent ``None`` is
        not the oracle's directive.  ``charge_units`` is what the trial
        *cost* (feature 89) — a positive finite real, defaulting to
        :data:`~ledger.units.DEFAULT_CHARGE_UNITS` (``1.0``, §8's own
        default for the column), because an ordinary evaluation is worth
        exactly one unit and a cross-validated one whose folds each
        compare a fit against the same forward returns states its own
        count.  Unlike the directive it *does* have a default, and the
        difference is the spec's: one unit is a real trial's honest
        weight, while there is no honest weight for a budget directive
        the oracle is supposed to supply.  The stamp is ``ts`` when the
        caller knows when the charge happened — a replay debits the
        instant it is reproducing, so it does not depend on when it ran —
        and otherwise ``clock()`` (defaulting to :func:`~ledger.record.
        utc_now`, aware UTC at second resolution).  The sequence number
        is not a parameter and never will be: the table assigns it, and
        the returned :class:`~ledger.record.TrialLedgerRecord` carries
        what was assigned.

        Every argument is validated *before* the database is touched, so
        a refused append spends no sequence number and leaves the ledger
        exactly as it was.  A configured store whose INSERT fails raises
        :class:`~ledger.errors.TrialStoreError` — a debit that silently
        failed to persist is the state this feature exists to prevent —
        and concurrent appends serialise on the database and receive
        distinct, increasing sequences.
        """
        node, campaign, ended, directive, units, instant = _validated_charge(
            node_id, campaign_id, outcome, charges_budget, charge_units, ts, clock
        )
        # Already aware-UTC (the validator normalises), so isoformat() ends
        # "+00:00" and the stored text is canonical and orderable.
        stamp = instant.isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        f"INSERT INTO {TRIAL_LEDGER_TABLE} "
                        "(ts, node_id, campaign_id, outcome, charges_budget, "
                        "charge_units) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            stamp,
                            node,
                            campaign,
                            ended,
                            1 if directive else 0,
                            units,
                        ),
                    )
                    assigned = cursor.lastrowid
        except sqlite3.Error as exc:
            raise TrialStoreError(
                f"the trial ledger at {self._database_url} could not debit "
                f"node {node!r}: {exc}"
            ) from exc
        if assigned is None:  # pragma: no cover - sqlite assigns one on INSERT
            raise TrialStoreError(
                "sqlite assigned no sequence number to the appended trial "
                "row; the debit did not land and must be retried"
            )
        return TrialLedgerRecord(
            seq=assigned,
            ts=instant,
            node_id=node,
            campaign_id=campaign,
            outcome=ended,
            charges_budget=directive,
            charge_units=units,
        )

    def debit(
        self,
        node_id: Any,
        campaign_id: Any,
        outcome: Any = None,
        charges_budget: Any = None,
        charge_units: Any = DEFAULT_CHARGE_UNITS,
        *,
        ts: Optional[datetime] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> tuple[TrialLedgerRecord, bool]:
        """Charge one evaluation idempotently, keyed by ``node_id``.

        Feature 95's store seam — the half the POST /ledger/debit
        endpoint (:mod:`ledger.debit`) speaks for.  The node is the
        idempotency key because the node *is* the evaluation's identity:
        one evaluation is one charge is one row, so a second request for
        a node that already holds a row is by construction a retry of
        the same charge, never a new one.  Returns ``(record,
        appended)`` — the node's row, and whether *this* call appended
        it.  On a retry the record is the prior row and ``appended`` is
        ``False``, so the caller is answered with the very sequence the
        original request returned and the two accounts never diverge.

        The charge carries feature 91's outcome — one of 'ok',
        'timeout', 'error', 'tripwire_fail', refused when absent for
        the same reason :meth:`append` refuses it: the failure the
        debit is charged *for* is the fact the row exists to record —
        and feature 90's budget directive — a genuine bool, the opaque
        directive the null oracle returned, refused when it is not a
        bool because a ``1`` or a ``0`` or an absent ``None`` is not the
        oracle's directive — and feature 89's charge unit: what the trial
        cost, a positive finite real defaulting to ``1.0`` for an
        ordinary evaluation, which a cross-validated one states as its
        folds' count.

        The check and the insert are one statement in one transaction —
        ``INSERT … SELECT … WHERE NOT EXISTS (… node_id = ?)`` — on the
        one connection the operation opens, so there is no window
        between "the node has no row" and "the row is written" for a
        retry to slip a second charge through: concurrent debits of one
        node serialise on the database's write lock and every caller
        after the first is answered by the first's row.  (A UNIQUE
        constraint on ``node_id`` would move the guard into the schema,
        but §8's DDL declares none and the raw :meth:`append` must keep
        counting what it is told; the guarantee is the debit's to hold,
        and it holds it at the seam.)

        On a retry, nothing is written — not the stamp, not the
        campaign, not the outcome, not the directive, not the unit: the
        prior row stands exactly as first written, because this is
        append-only accounting and a charge is never restated.  A ``ts``,
        an ``outcome``, a ``charges_budget`` or a ``charge_units`` handed
        to a retry is silently the *loser* of that rule — the outcome,
        the directive and the unit of the charge are the ones the
        evaluation ended with when it was first debited, not the ones a
        later retry would guess; callers that need to know which landed
        read them off the returned record.  When several rows exist for
        the node — only raw :meth:`append` calls can leave that — the
        earliest by ``seq`` is the prior row: the first charge ever
        debited for the node is the one whose retry this is.

        Validation is the append's own (see :func:`_validated_charge`)
        and happens before the database is touched, so a refused debit
        spends no sequence number; a *skipped* one — the retry — spends
        none either, which is the whole point: the next node's first
        debit draws the very next number.
        """
        node, campaign, ended, directive, units, instant = _validated_charge(
            node_id, campaign_id, outcome, charges_budget, charge_units, ts, clock
        )
        stamp = instant.isoformat()
        appended = False
        assigned: Optional[int] = None
        prior: Optional[tuple[Any, ...]] = None
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        f"INSERT INTO {TRIAL_LEDGER_TABLE} "
                        "(ts, node_id, campaign_id, outcome, charges_budget, "
                        "charge_units) SELECT ?, ?, ?, ?, ?, ? WHERE NOT EXISTS ("
                        f"SELECT 1 FROM {TRIAL_LEDGER_TABLE} WHERE node_id = ?)",
                        (
                            stamp,
                            node,
                            campaign,
                            ended,
                            1 if directive else 0,
                            units,
                            node,
                        ),
                    )
                    if cursor.rowcount == 1:
                        appended = True
                        assigned = cursor.lastrowid
                    else:
                        prior = connection.execute(
                            f"SELECT {_COLUMNS} FROM {TRIAL_LEDGER_TABLE} "
                            "WHERE node_id = ? ORDER BY seq LIMIT 1",
                            (node,),
                        ).fetchone()
        except sqlite3.Error as exc:
            raise TrialStoreError(
                f"the trial ledger at {self._database_url} could not debit "
                f"node {node!r}: {exc}"
            ) from exc
        if appended:
            if assigned is None:  # pragma: no cover - sqlite assigns on INSERT
                raise TrialStoreError(
                    "sqlite assigned no sequence number to the debited trial "
                    "row; the charge did not land and must be retried"
                )
            return (
                TrialLedgerRecord(
                    seq=assigned,
                    ts=instant,
                    node_id=node,
                    campaign_id=campaign,
                    outcome=ended,
                    charges_budget=directive,
                    charge_units=units,
                ),
                True,
            )
        if prior is None:  # pragma: no cover - NOT EXISTS saw what the SELECT misses
            raise TrialStoreError(
                f"the trial ledger at {self._database_url} holds no row for "
                f"node {node!r} yet the debit was skipped; the ledger's state "
                "changed under the charge and it must be retried"
            )
        return _record_from_row(prior), False

    # -- Reading ------------------------------------------------------------

    def get(self, seq: Any) -> Optional[TrialLedgerRecord]:
        """The row assigned ``seq``, or ``None`` when the ledger holds none.

        A ``seq`` the ledger could never have assigned — not an integer,
        a bool, below 1 — is a miss rather than an error, the same read
        discipline the snapshot member's store applies: it names no row
        this ledger ever appended.  (It is checked here because SQLite's
        column affinity would otherwise coerce ``"1"`` into a hit on row
        1, and a type bug must not masquerade as a found charge.)
        """
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM {TRIAL_LEDGER_TABLE} WHERE seq = ?",
                (seq,),
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def rows(self) -> tuple[TrialLedgerRecord, ...]:
        """Every row, in sequence order — the log's own order.

        Ordered by ``seq``, not by ``ts``: the sequence is the order the
        charges were actually debited in, and the log is replayed in the
        order it was written.  Feature 93's ``K_effective`` derivation
        (:meth:`k_effective`) reads the whole log in this order; feature
        96's epoch-usage counts read the ``epoch_ledger`` table instead
        (:meth:`epoch_usage`) and so never touch these rows at all — the
        two derived views of §8 are two reads over two tables.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM {TRIAL_LEDGER_TABLE} ORDER BY seq"
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def count(self) -> int:
        """How many rows the ledger holds.

        The plain count — every row, unfiltered.  ``K_effective``
        (feature 93) is *not* this number and is deliberately a separate
        read (:meth:`k_effective`): it counts only budget-charging
        trials, filtering on ``charges_budget`` (feature 90), so the
        honest ``K`` and the effective ``K`` are two different numbers
        and this one stays the plain total.  The two are equal only when
        no null node was ever charged.
        """
        with closing(self._connect()) as connection:
            (total,) = connection.execute(
                f"SELECT COUNT(*) FROM {TRIAL_LEDGER_TABLE}"
            ).fetchone()
        return int(total)

    def k_effective(self) -> KEffective:
        """``K_effective`` per epoch — the budget-charging trials (feature 93).

        The derivation §8 names among the ledger's derived views —
        *"``K_effective`` per epoch (filtered on ``charges_budget``)"* —
        read straight off this table: every row, grouped by the epoch it
        charged, counting only the ones whose ``charges_budget`` is true.
        A null node is stamped ``False`` by the null oracle's opaque
        directive (feature 90) and so contributes nothing, however many
        of them a campaign ran; that is the whole point of the filter.
        The result is a :class:`~ledger.keffective.KEffective`, which
        carries the per-epoch breakdown and the total.

        The plain :meth:`count` is *not* this number and this is not that
        method: ``count`` answers how many rows the ledger holds, this
        answers how many of them consumed statistical degrees of freedom.
        The two are equal only when no null node was ever charged.

        **The epoch dimension is feature 88's, and is read when present.**
        The table carries an ``epoch_id`` column once feature 88's stamp
        lands; until then every row is grouped under the un-named epoch
        (``None``).  The column is probed for rather than assumed, so this
        read is correct on a table written before 88 and becomes a genuine
        per-epoch view the moment its column appears — with no edit here,
        and without this feature presuming the shape of another's write
        seam.  A row whose stored directive is neither ``0`` nor ``1`` is
        refused by the derivation rather than quietly counted as "not
        true", because understating ``K`` is the one error direction that
        lets a false discovery through.

        An epoch whose trials were all null nodes is reported with a count
        of ``0`` rather than omitted — the deflation term must be told that
        epoch contributed no degrees of freedom, not left to infer it.
        """
        with closing(self._connect()) as connection:
            # The stamp's column is a sibling feature's, so the read asks
            # the schema whether there is an epoch dimension to group by
            # rather than assuming one — and never touches the rows to ask.
            stamped = _has_epoch_column(connection)
            projection = (
                f"{_EPOCH_COLUMN}, charges_budget" if stamped else "charges_budget"
            )
            rows = connection.execute(
                f"SELECT {projection} FROM {TRIAL_LEDGER_TABLE} ORDER BY seq"
            ).fetchall()
        if stamped:
            return derive_k_effective((row[0], row[1]) for row in rows)
        return derive_k_effective((None, row[0]) for row in rows)

    def epoch_usage(self) -> EpochUsage:
        """Promotion decisions served per sequestered epoch (feature 96).

        The second of §8's derived views — *"epoch usage counts (retire
        at 3 promotion decisions)"* — read off ``epoch_ledger``
        (:data:`EPOCH_LEDGER_TABLE`): one row per sequestered epoch,
        carrying the running count the promotion plugin's persist
        (feature 294) advances.  The result is an
        :class:`~ledger.epochusage.EpochUsage`, which carries the
        per-epoch breakdown, the number of epochs the pool holds and the
        pool-wide burn.

        **This is not** :meth:`k_effective` **and neither reads the
        other's table.**  ``K_effective`` counts *trial charges* out of
        the append-only ``trial_ledger`` — statistical degrees of freedom
        spent — while this counts *promotion decisions* out of
        ``epoch_ledger`` — sequestration spent.  §6.1's step 11 debits a
        trial and a promotion decision debits an epoch, so the two
        numbers move on different events and are equal only by
        coincidence.  Feature 295's retirement threshold and feature
        296's "no clean epoch remains" terminal state read *this* figure;
        the deflation term (feature 259) reads the other.

        **A missing table is an empty pool, honestly reported.**  This
        store does not create ``epoch_ledger`` — the table is feature
        105's and the migration or the promotion plugin creates it — so a
        database where no epoch was ever sealed simply has no such table.
        That is answered with an empty :class:`~ledger.epochusage.
        EpochUsage` rather than an exception, and it is the safe
        direction: no epochs observed means no clean epoch remains, which
        §15 names as a legitimate terminal state, whereas a raised error
        (or an invented count) could be worked around into a promotion.
        A table that *exists* and cannot be read is the opposite case and
        stays loud — see below.

        **Every sealed epoch is reported, unspent ones included.**  An
        epoch that has served nothing is reported at ``0`` and listed, so
        feature 297's depleting-epoch figure is *told* the pool's size
        rather than left to infer it from the rows that happen to be
        non-zero.  A retired epoch is reported at what it served: the
        ``retired`` column is feature 296's and is deliberately not read
        here, because hiding a spent epoch's count would understate the
        burn at the moment an operator asks how the pool got here.

        A row that cannot be believed is refused rather than served — an
        ``epoch_id`` that names no epoch, a count that is not a
        non-negative integer, or (impossibly, given the primary key) two
        rows for one epoch.  See :mod:`ledger.epochusage` for why each
        refusal is in the direction that keeps a spent epoch from reading
        as clean.  Unlike an absent table, a configured store whose read
        *fails* raises :class:`~ledger.errors.TrialStoreError`: a usage
        count that silently fell back to zero is a pool size the ledger
        never stated.
        """
        try:
            with closing(self._connect()) as connection:
                # The table is a sibling feature's, so its existence is
                # asked of the schema rather than assumed — and a database
                # that has never sealed an epoch has none.
                if not _has_epoch_ledger_table(connection):
                    return EpochUsage(())
                rows = connection.execute(
                    f"SELECT {_EPOCH_LEDGER_COLUMNS} FROM {EPOCH_LEDGER_TABLE} "
                    "ORDER BY epoch_id"
                ).fetchall()
        except sqlite3.Error as exc:
            raise TrialStoreError(
                f"the epoch ledger at {self._database_url} could not be read: "
                f"{exc}.  Its usage counts (feature 96) are what the "
                "promotion discipline retires epochs on (feature 295) and what "
                "the operator surface reports as remaining clean epochs, so a "
                "failed read is raised rather than answered with a zero this "
                "store did not state."
            ) from exc
        return derive_epoch_usage((row[0], row[1]) for row in rows)
