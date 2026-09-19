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
evaluation and the table grows by one.  Two calls are two rows, even for
the same node — at feature 86 the honest counter counts what it is told,
and the idempotent debit keyed by ``node_id`` is feature 95's contract,
layered on this seam when it arrives.  Nothing here updates, nothing
deletes: the API offers no such spelling, and the *enforced* refusal
(role grants that deny UPDATE and DELETE) is feature 92's, arriving with
the database role that carries it.

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
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from .errors import TrialRecordError, TrialStoreError
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

    The write surface is exactly one method, :meth:`append`, and it
    performs exactly one INSERT.  There is no update and no delete to
    call, by design; feature 92's role grants make the same refusal at
    the database itself, for every client this package never met.
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
        """Open the database and ensure the ledger's table exists.

        The schema is created idempotently on every connect, so a fresh
        database and an existing one take the same path and no migration
        step is needed for this member — the same contract the universe
        member's ``connect`` states.  The caller owns the connection; use
        it as a context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
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
