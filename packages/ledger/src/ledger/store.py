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

**The columns are the four the append itself owns.**  ``seq``, ``ts``,
``node_id``, ``campaign_id`` — §8's first four, the ones that say *which
evaluation was charged, when, in what order*.  The provenance triple
(feature 87), the epoch (88), the charge semantics (89-90) and the
outcome (91) are their features' stamps and land as columns on this same
table as they arrive, the way the universe member's store upgrades its
own tables in place.  ``ts`` is stored as ISO-8601 UTC text with an
explicit offset — canonical, lexicographically ordered for a single
offset, and revalidated through the record constructor on read, so a row
that wandered in from outside cannot smuggle a naive stamp past the
write-time check.

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

The schema is created idempotently on connect, so a fresh database's
first debit brings the table into being and no migration step is needed
for this member.

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

from .errors import TrialImmutableError, TrialRecordError, TrialStoreError
from .record import TrialLedgerRecord, _validated_instant, _validated_uuid, utc_now

__all__ = [
    "DATABASE_URL_ENV",
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

#: The table's DDL.  See the module docstring for why ``AUTOINCREMENT``
#: is the load-bearing word and why these four columns are this feature's
#: whole column set.
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
    campaign_id TEXT NOT NULL
);
"""

# The read path's column list, in the table's declaration order.  One
# string shared by every SELECT so the reader and the record cannot drift
# apart in column order — the failure that would silently swap an
# identity for a stamp.
_COLUMNS = "seq, ts, node_id, campaign_id"

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
            seq=row[0], ts=row[1], node_id=row[2], campaign_id=row[3]
        )
    except TrialRecordError as exc:
        raise TrialRecordError(
            f"trial_ledger row with seq={row[0]!r} is malformed and cannot "
            f"be read back: {exc}"
        ) from exc


def _validated_charge(
    node_id: Any,
    campaign_id: Any,
    ts: Optional[datetime],
    clock: Optional[Callable[[], datetime]],
) -> tuple[str, str, datetime]:
    """Validate a charge's arguments, returning the canonical triple.

    The one spelling both write paths — :meth:`TrialLedger.append` and
    :meth:`TrialLedger.debit` — share, so the two cannot drift on what
    they accept: identities canonicalised to UUID text, the stamp resolved
    from ``ts`` when the caller knows when the charge happened (a replay
    debits the instant it reproduces, so the clock is never read when
    ``ts`` is given) and from ``clock()`` otherwise, defaulting to
    :func:`~ledger.record.utc_now`.  Every refusal lands here, *before*
    the database is touched, so a refused charge spends no sequence
    number and leaves the ledger exactly as it was.
    """
    node = _validated_uuid(node_id, "node_id")
    campaign = _validated_uuid(campaign_id, "campaign_id")
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
    return node, campaign, instant


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

        The schema is created idempotently on every connect, so a fresh
        database and an existing one take the same path and no migration
        step is needed for this member — the same contract the universe
        member's ``connect`` states.  The connection is a
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
        return connection

    # -- Writing ------------------------------------------------------------

    def append(
        self,
        node_id: Any,
        campaign_id: Any,
        *,
        ts: Optional[datetime] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> TrialLedgerRecord:
        """Debit one evaluation: one INSERT, one sequence number, one row.

        The whole of feature 86 at its seam.  The evaluation is named by
        ``node_id`` and ``campaign_id`` (a :class:`~uuid.UUID` or its text
        spelling, canonicalised on the way in); the stamp is ``ts`` when
        the caller knows when the charge happened — a replay debits the
        instant it is reproducing, so it does not depend on when it ran —
        and otherwise ``clock()`` (defaulting to :func:`~ledger.record.
        utc_now`, aware UTC at second resolution).  The sequence number is
        not a parameter and never will be: the table assigns it, and the
        returned :class:`~ledger.record.TrialLedgerRecord` carries what
        was assigned.

        Every argument is validated *before* the database is touched, so
        a refused append spends no sequence number and leaves the ledger
        exactly as it was.  A configured store whose INSERT fails raises
        :class:`~ledger.errors.TrialStoreError` — a debit that silently
        failed to persist is the state this feature exists to prevent —
        and concurrent appends serialise on the database and receive
        distinct, increasing sequences.
        """
        node, campaign, instant = _validated_charge(node_id, campaign_id, ts, clock)
        # Already aware-UTC (the validator normalises), so isoformat() ends
        # "+00:00" and the stored text is canonical and orderable.
        stamp = instant.isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        f"INSERT INTO {TRIAL_LEDGER_TABLE} "
                        "(ts, node_id, campaign_id) VALUES (?, ?, ?)",
                        (stamp, node, campaign),
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
            seq=assigned, ts=instant, node_id=node, campaign_id=campaign
        )

    def debit(
        self,
        node_id: Any,
        campaign_id: Any,
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
        campaign: the prior row stands exactly as first written, because
        this is append-only accounting and a charge is never restated.
        A ``ts`` handed to a retry is silently the *loser* of that rule;
        callers that need to know which stamp landed read it off the
        returned record.  When several rows exist for the node — only
        raw :meth:`append` calls can leave that — the earliest by
        ``seq`` is the prior row: the first charge ever debited for the
        node is the one whose retry this is.

        Validation is the append's own (see :func:`_validated_charge`)
        and happens before the database is touched, so a refused debit
        spends no sequence number; a *skipped* one — the retry — spends
        none either, which is the whole point: the next node's first
        debit draws the very next number.
        """
        node, campaign, instant = _validated_charge(node_id, campaign_id, ts, clock)
        stamp = instant.isoformat()
        appended = False
        assigned: Optional[int] = None
        prior: Optional[tuple[Any, ...]] = None
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        f"INSERT INTO {TRIAL_LEDGER_TABLE} "
                        "(ts, node_id, campaign_id) "
                        "SELECT ?, ?, ? WHERE NOT EXISTS ("
                        f"SELECT 1 FROM {TRIAL_LEDGER_TABLE} WHERE node_id = ?)",
                        (stamp, node, campaign, node),
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
                    seq=assigned, ts=instant, node_id=node, campaign_id=campaign
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
        order it was written.  This is the seam the derived views of
        features 93-94 and 96 read through when they arrive.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM {TRIAL_LEDGER_TABLE} ORDER BY seq"
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def count(self) -> int:
        """How many rows the ledger holds.

        The plain count — every row, unfiltered.  ``K_effective``
        (feature 93) is *not* this number and is deliberately not here:
        it counts only budget-charging trials, and deriving it before
        feature 90's ``charges_budget`` column exists would be deriving it
        from nothing.
        """
        with closing(self._connect()) as connection:
            (total,) = connection.execute(
                f"SELECT COUNT(*) FROM {TRIAL_LEDGER_TABLE}"
            ).fetchone()
        return int(total)
