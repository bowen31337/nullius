"""Persisting §7.4's p-value against its campaign — feature 123's store half.

app_spec.xml, "Null Oracle & Planted Nulls", feature 123: *System persists
the p-value of a two-sample Kolmogorov-Smirnov test comparing in-sample
scores of null nodes against real nodes per campaign.*  :mod:`nulloracle.ks`
is the *test*; this module writes its answer down.  The split is the one
this member already uses twice — :mod:`nulloracle.assignment` states the
schema and :mod:`nulloracle.sidecar` writes the file, :mod:`nulloracle.
envelope` holds the cipher and the sidecar holds the bytes — and for the
same reason: the arithmetic can be tested with no database in the way, and
the store can be tested with a hand-built measurement rather than a
hand-built sample.

**Where the number lands, and why it is not a new table.**  The spec
declares the column: ``migrations/versions/0111_campaign_table.py`` creates
``campaign`` with ``ks_pvalue REAL`` and states exactly what it is for —
*"the two-sample KS p-value comparing the in-sample scores of null nodes
against real nodes (PRD §4.3) … the guard fills it at read time; the
orchestrator does not"* — and it is ``Nullable`` on purpose, so that *"a
freshly created campaign has not been read, so it has no p-value yet"*
stays distinguishable from *"tested, and decisively detectable"*.  This
module is the writer that column was created for, and it writes it there
rather than into a table of its own: feature 124's verdict, the dashboard's
``GET /metrics/instrument-status`` and anything else in the system that
wants the number will look for it on the campaign row, and a second
location would be a second answer.

**What the guard's own table is for, then.**  One row per campaign in
``campaign_ks_guard``, carrying what the campaign column cannot: the
statistic ``D``, the two sample sizes, and *which estimator* produced the
p-value (feature 123's own provenance, the way ``evaluator_identity`` is
feature 70's record that the hash landed and ``node_persist`` is feature
85's).  A bare ``REAL`` on a campaign row is a number nobody can check —
``0.31`` from 400 nodes and ``0.31`` from four are the same value and
opposite findings — so the guard row is what makes the stored p-value
*interpretable* rather than merely present.  It is **not** a second home
for the p-value: the two columns are written in one transaction and the
read path refuses a half, so the number on the campaign row and the
provenance beside it cannot disagree.

**The verdict is feature 124's, and this module deliberately does not
write it.**  §7.4 spells the consequence — *"``if ks_pvalue < 0.05:
campaign.calibration_status = VOID``"* — and app_spec.xml gives that
comparison to feature 124 (*"System persists a campaign calibration_status
of VOID when the KS p-value falls below 0.05, which halts dreaming and
excludes the campaign from the pool"*).  So ``calibration_status`` is left
exactly as the campaign row carries it — ``'ok'`` by its own ``DEFAULT``,
and never touched here.  The separation is not pedantry: this feature
*measures*, the next one *decides*, and a guard that also wrote the verdict
would be a threshold nobody could audit without changing what a measurement
means.  The threshold constant is 124's to spell for the same reason.

**Unless the caller asks for the verdict, in which case it is still not
this module's.**  A campaign driver that has just run the guard and wants
the campaign voided calls feature 124 with the p-value this module
returned.  What this module will not do is infer it.

**One campaign, one row, one transaction.**  The grain is the campaign:
``campaign_id`` is the primary key of the guard table, so re-running the
guard on the same campaign — a re-read after an operator investigates the
block length, a retry after a crash — refreshes the stored provenance
rather than appending a second reading, and the ``UPDATE`` of the campaign
row is keyed by the same id.  A *changed* number under an existing key is
not refused: the campaign is the key, the guard measures the campaign, and
a campaign re-read after its permutation scheme was changed is the exact
thing §7.4's alert asks an operator to do.  Last write wins, and the
returned record says what was written.

**The store refuses a campaign it does not hold.**  The p-value is a fact
*about a campaign*; a guard that wrote ``ks_pvalue`` onto a row it created
would be inventing the campaign the number belongs to.  ``campaign`` is
created here with ``CREATE TABLE IF NOT EXISTS`` — the contract every store
in this workspace states, and the one ``migrations/versions/0111_campaign_
table.py`` itself describes for its orchestrator (a store that creates its
table idempotently takes the same path on a fresh database and an existing
one) — but the *row* is never created here.  A missing campaign raises
:class:`~nulloracle.errors.KsGuardError` by name.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime`` and
``urllib.parse``; no third-party import at module scope, so the factory's
scan — which imports
this package to fire its ``@register`` — pays nothing for this module.
That matters here more than usual: the member already defers
``cryptography`` to first use, and a store that pulled a driver in at
import would undo that.

**The sample is never stored, and never logged.**  §4.2 draws the
information barrier and §7.4 names the single process allowed past it; the
guard row carries counts, not scores, and not one node id.  See
:mod:`nulloracle.ks` — the same rule stated where the samples are read.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from .assignment import normalize_node_id
from .errors import KsGuardError
from .ks import KS_ASYMPTOTIC, KS_EXACT, KolmogorovSmirnov, ks_two_sample

__all__ = [
    "CAMPAIGN_TABLE",
    "DATABASE_URL_ENV",
    "KS_GUARD_TABLE",
    "KsGuard",
    "KsGuardRecord",
    "load_ks_guard",
    "persist_ks_pvalue",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the evaluator's
#: five, the repository-level conftest's), restated here so each store states
#: its own contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the p-value's headline column lives on — feature 104's
#: ``campaign``, created by ``migrations/versions/0111_campaign_table.py``.
#: Spelled once here so the writer and the migration cannot drift apart on
#: what the campaign table is called.
CAMPAIGN_TABLE = "campaign"

#: The table this feature's own provenance lives in — one row per campaign,
#: named for the guard rather than for the campaign so that a reader looking
#: for *what the guard recorded* does not have to know which columns of
#: ``campaign`` are whose.
KS_GUARD_TABLE = "campaign_ks_guard"

#: ``campaign``'s DDL as ``migrations/versions/0111_campaign_table.py``
#: spells it for SQLite, restated rather than imported: a migration is loaded
#: by path by its runner and must not depend on a workspace package being
#: importable in order to run, and this store must not depend on the
#: migration file being on ``sys.path`` in order to open a database.  The two
#: spellings are held together by the columns they name, which is the thing
#: they have to agree on — and ``test_ksguard.py`` asserts the agreement
#: against the migration's own ``statements("sqlite")``.
#:
#: The two dialect splits the migration argues (a parenthesised
#: ``randomblob`` UUID default, and ``strftime`` in place of ``NOW()``) are
#: carried verbatim, so a database this store creates is the database the
#: migration would have created and a test that runs the migration over it
#: changes nothing.  So is every declared *type* — SQLite applies its own
#: affinity, so ``UUID`` and ``TIMESTAMPTZ`` are as usable here as ``TEXT``
#: would be, and spelling them the migration's way is what makes the two
#: files one schema rather than two that happen to agree on the columns.  A
#: reader inspecting the table this store created sees the table the
#: migration describes.
_CAMPAIGN_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {CAMPAIGN_TABLE} (
    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    campaign_type      TEXT NOT NULL,
    workspace_count    INT NOT NULL,
    null_fraction      REAL NOT NULL,
    calibration_status TEXT NOT NULL DEFAULT 'ok',
    ks_pvalue          REAL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

#: This feature's provenance table.  One row per campaign: the campaign the
#: reading belongs to, the statistic and p-value, the two sample sizes, the
#: estimator, and when the guard ran.  ``campaign_id`` is the primary key
#: because the grain is the campaign — a re-read refreshes, it does not
#: append — and the row is deliberately *not* the campaign's own record:
#: nothing here names a node, and nothing here is a label.
_SCHEMA = f"""
-- Feature 123: one row per campaign, the provenance behind the campaign's
-- `ks_pvalue`. A bare REAL on the campaign row says what the number is and
-- not what it was computed from; this row carries the statistic, the two
-- sample sizes and the estimator, so a stored p-value is checkable rather
-- than merely present. The campaign row's `calibration_status` is
-- feature 124's to write and is not touched here.
CREATE TABLE IF NOT EXISTS {KS_GUARD_TABLE} (
    campaign_id  TEXT PRIMARY KEY,  -- the campaign this reading belongs to
    pvalue       REAL NOT NULL,     -- §7.4's number, mirrored from the campaign row
    statistic    REAL NOT NULL,     -- the two-sample KS statistic D
    null_count   INT  NOT NULL,     -- how many null nodes were scored
    real_count   INT  NOT NULL,     -- how many real nodes were scored
    method       TEXT NOT NULL,     -- 'exact' or 'asymptotic' — which estimator
    seen_at      TEXT NOT NULL      -- when the guard ran (ISO-8601 UTC)
);
"""

_COLUMNS = "campaign_id, pvalue, statistic, null_count, real_count, method, seen_at"


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's
    ``node.id``*, and ``campaign``'s ``id`` is the same kind of value — but
    re-raises its refusal as :class:`~nulloracle.errors.KsGuardError`.
    The distinction is the taxonomy's: a malformed id handed to the *guard*
    is a store-contract failure, not a sidecar-schema one, and a caller
    reading ``SidecarError`` out of a KS guard would look in the wrong
    module for the cause.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:  # noqa: BLE001 - re-raised by name below
        raise KsGuardError(
            f"campaign_id {value!r} is not a UUID: {exc}"
        ) from exc


def _utc_now() -> datetime:
    """The current instant, timezone-aware UTC — the guard's own clock.

    Second resolution with microseconds dropped rather than rounded, the
    same spelling :func:`ledger.record.utc_now` uses and for the same
    reason: the stamp orders guard runs against one another, and dropping —
    not rounding — keeps it never *after* the instant observed.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass(frozen=True)
class KsGuardRecord:
    """One campaign's persisted detectability reading.

    The measurement (:class:`~nulloracle.ks.KolmogorovSmirnov`) plus the
    campaign it belongs to and the instant the guard ran.  Frozen, and
    validated in :meth:`__post_init__` rather than only where it is built,
    because the read path reconstructs one from a stored row: a row whose
    p-value is not a probability, whose counts are not positive, or whose
    method names an estimator this member does not carry fails to
    reconstruct rather than loading as a plausible-looking lie — the same
    discipline :func:`evaluator.identity_from_row` applies to a stored
    evaluator, and it is here for the same reason.  What downstream trusts
    is the stored number, and a store that could hand back a row
    disagreeing with itself would launder a tamper.
    """

    #: The campaign this reading belongs to, canonical UUID text.
    campaign_id: str
    #: §7.4's p-value — the value written to ``campaign.ks_pvalue``.
    pvalue: float
    #: The two-sample KS statistic the p-value was computed from.
    statistic: float
    #: How many null nodes were scored.
    null_count: int
    #: How many real nodes were scored.
    real_count: int
    #: Which estimator produced the p-value — ``'exact'`` or ``'asymptotic'``.
    method: str
    #: When the guard ran.
    seen_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _validated_campaign_id(self.campaign_id)
        )
        for name in ("pvalue", "statistic"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise KsGuardError(
                    f"{name} must be a real number, got {value!r} "
                    f"({type(value).__name__})"
                )
            number = float(value)
            if not 0.0 <= number <= 1.0:
                raise KsGuardError(
                    f"{name} must lie in [0, 1], got {number!r}; both a KS "
                    "statistic and its p-value are probabilities, and a "
                    "stored value outside that range would enter feature "
                    "124's comparison as a number no test produced"
                )
        for name in ("null_count", "real_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise KsGuardError(
                    f"{name} must be a positive integer, got {value!r}; a "
                    "reading with no sample on one side is not a comparison "
                    "of two populations"
                )
        if self.method not in (KS_EXACT, KS_ASYMPTOTIC):
            raise KsGuardError(
                f"method must be {KS_EXACT!r} or {KS_ASYMPTOTIC!r}, got "
                f"{self.method!r}; which estimator produced a stored p-value "
                "is part of what the number means"
            )
        if not isinstance(self.seen_at, datetime):
            raise KsGuardError(
                f"seen_at must be a datetime, got "
                f"{type(self.seen_at).__name__}"
            )
        if self.seen_at.tzinfo is None or self.seen_at.utcoffset() is None:
            raise KsGuardError(
                f"seen_at must be timezone-aware; got the naive datetime "
                f"{self.seen_at.isoformat()!r}. A guard reading is ranged by "
                "its stamp and compared across campaigns, so a naive one "
                "would raise far from the write that omitted the offset"
            )

    @property
    def measurement(self) -> KolmogorovSmirnov:
        """The reading's test result, rebuilt as the value it came from.

        A property rather than a stored field: the five columns of
        :class:`~nulloracle.ks.KolmogorovSmirnov` are exactly the five this
        record already validates, and re-deriving is what keeps the two
        from ever being two copies of a measurement that could disagree.
        """
        return KolmogorovSmirnov(
            statistic=self.statistic,
            pvalue=self.pvalue,
            null_count=self.null_count,
            real_count=self.real_count,
            method=self.method,
        )

    def to_payload(self) -> dict[str, Any]:
        """The record as a plain mapping, for a log line or an operator's report.

        The field names are the record's own, so a stored row, a rendered
        mapping and a structured log record name the same things the same
        way — and the instant renders as the ISO-8601 text the table stores,
        so a round trip through this mapping and back is the same instant.
        """
        return {
            "campaign_id": self.campaign_id,
            "pvalue": self.pvalue,
            "statistic": self.statistic,
            "null_count": self.null_count,
            "real_count": self.real_count,
            "method": self.method,
            "seen_at": self.seen_at.isoformat(),
        }


def guard_record_from_row(row: Any) -> KsGuardRecord:
    """Rebuild a :class:`KsGuardRecord` from a stored row.

    ``row`` is the ``(campaign_id, pvalue, statistic, null_count, real_count,
    method, seen_at)`` tuple this store writes, in
    :data:`_COLUMNS`' order. The stamp is parsed back from the ISO-8601 text
    the table holds and every field re-validates through the record's own
    ``__post_init__``, so a row edited outside this package fails to
    reconstruct instead of loading as a plausible-looking reading — the
    defence :func:`evaluator.identity_from_row` states for the evaluator's
    hash, and the same reason it exists: the stored p-value is what feature
    124 will void a campaign on, and a store that could return a number
    disagreeing with its own row would launder a tamper.
    """
    campaign_id, pvalue, statistic, null_count, real_count, method, seen_at = row
    try:
        instant = datetime.fromisoformat(seen_at)
    except (TypeError, ValueError) as exc:
        raise KsGuardError(
            f"the stored guard reading for campaign {campaign_id!r} carries "
            f"the unparseable stamp {seen_at!r}: {exc}"
        ) from exc
    return KsGuardRecord(
        campaign_id=campaign_id,
        pvalue=pvalue,
        statistic=statistic,
        null_count=null_count,
        real_count=real_count,
        method=method,
        seen_at=instant,
    )


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.
    A non-SQLite scheme is refused loudly — the Postgres store arrives with
    the migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a guard
    reading that vanished would leave a campaign looking un-read when it had
    in fact been read and voided.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise KsGuardError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a campaign's detectability reading must outlive the "
            "guard run that produced it"
        )
    return Path(path)


class KsGuard:
    """§7.4's guard journal: the p-value written against its campaign.

    Constructed with the database URL it appends to; :meth:`guard` runs the
    test and writes both halves, :meth:`load` reads one campaign's reading
    back.  The class resolves its path lazily, so constructing one performs
    no I/O — composition-time work must not touch the disk, the contract
    every store in this workspace states.

    The store holds no samples: it takes them, computes the measurement
    through :mod:`nulloracle.ks`, writes the counts and the number, and lets
    the caller's mapping go out of scope with the call.  There is no field
    here that could leak a label partition, deliberately — see the module
    docstring and §4.2.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(
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
    ) -> Optional["KsGuard"]:
        """The guard journal ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no guard component — a discoverable state, not an exception — while
        the campaign job that must run §7.4's guard is the caller that must
        not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this guard writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this journal, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure both tables exist, idempotently.

        ``CREATE TABLE IF NOT EXISTS`` on the campaign table as well as this
        feature's own, the contract every store in this workspace states and
        the one ``migrations/versions/0111_campaign_table.py`` describes for
        its orchestrator: a fresh database and an existing one take the same
        path, so no migration step is needed here and running the migration
        over a database this store created changes nothing.  The caller owns
        the connection; use it as a context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_CAMPAIGN_SCHEMA)
            connection.executescript(_SCHEMA)
        return connection

    # -- Feature 123: the write ---------------------------------------------

    def guard(
        self,
        campaign_id: Any,
        null_scores: Mapping[Any, Any] | Iterable[float],
        real_scores: Mapping[Any, Any] | Iterable[float],
        *,
        seen_at: Optional[datetime] = None,
    ) -> KsGuardRecord:
        """Run §7.4's test and persist its p-value against ``campaign_id``.

        The whole of feature 123 in one call: the two samples go to
        :func:`~nulloracle.ks.ks_two_sample`, the campaign is confirmed to
        exist, and both halves are written in one transaction — the
        provenance row in ``campaign_ks_guard`` and ``ks_pvalue`` on the
        campaign row itself.

        ``calibration_status`` is **not** written.  §7.4's ``p < 0.05``
        comparison and the ``VOID`` verdict are feature 124's, and a guard
        that also decided would be a threshold nobody could audit without
        changing what a measurement means.  A caller that wants the campaign
        voided hands the returned p-value to that feature.

        Refuses, in this order, and each refusal names what it is about:

        1. a malformed ``campaign_id`` or a campaign the table does not hold
           (:class:`~nulloracle.errors.KsGuardError`) — a p-value is a fact
           about a campaign, and writing it onto a row this store invented
           would fabricate the campaign the number belongs to;
        2. a sample the test cannot support
           (:class:`~nulloracle.errors.KsTestError`, raised by
           :mod:`nulloracle.ks`) — *before* the campaign is touched, so a
           refused measurement leaves no row claiming it happened;
        3. a write that could not be completed, in either half.

        The write is idempotent by campaign: a re-read after an operator
        investigates the block length refreshes the reading rather than
        appending a second one — §7.4's own instruction is *"investigate the
        block length and permutation scheme before proceeding"*, so a
        campaign is expected to be guarded more than once, and what the
        table should hold is the latest reading and nothing else.

        ``seen_at`` defaults to the current UTC instant at second
        resolution; a caller replaying a recorded run supplies its own, so a
        replayed guard stamps the instant the original did.
        """
        campaign = _validated_campaign_id(campaign_id)
        # The measurement first, deliberately: a refused sample must leave
        # no row behind, and the test is the thing that can refuse it.
        measured = ks_two_sample(null_scores, real_scores)
        instant = _utc_now() if seen_at is None else seen_at
        record = KsGuardRecord(
            campaign_id=campaign,
            pvalue=measured.pvalue,
            statistic=measured.statistic,
            null_count=measured.null_count,
            real_count=measured.real_count,
            method=measured.method,
            seen_at=instant,
        )
        with closing(self._connect()) as connection, connection:
            self._require_campaign(connection, campaign)
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET ks_pvalue = ? WHERE id = ?",
                (record.pvalue, campaign),
            )
            connection.execute(
                f"INSERT INTO {KS_GUARD_TABLE} ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(campaign_id) DO UPDATE SET "
                "pvalue = excluded.pvalue, statistic = excluded.statistic, "
                "null_count = excluded.null_count, "
                "real_count = excluded.real_count, method = excluded.method, "
                "seen_at = excluded.seen_at",
                (
                    record.campaign_id,
                    record.pvalue,
                    record.statistic,
                    record.null_count,
                    record.real_count,
                    record.method,
                    record.seen_at.isoformat(),
                ),
            )
            stored = self._read_campaign_pvalue(connection, campaign)
            if stored != record.pvalue:
                raise KsGuardError(
                    f"campaign {campaign!r} was written half: the guard row "
                    f"holds {record.pvalue!r} and the campaign row holds "
                    f"{stored!r}; §7.4's number lives on the campaign and its "
                    "provenance lives beside it, and a reading whose two "
                    "halves disagree is not a reading"
                )
        return record

    def _require_campaign(self, connection: sqlite3.Connection, campaign: str) -> None:
        """Refuse a campaign the table does not hold, by name.

        The p-value joins the campaign row — feature 124's verdict is written
        there, ``GET /metrics/instrument-status`` reads it there — so a guard
        run against a campaign nobody planned is a caller bug worth learning
        before a number lands nowhere.  The check is a read, not a
        create: a store that inserted the missing campaign would be inventing
        the row the fraction and the type belong on.
        """
        cursor = connection.execute(
            f"SELECT 1 FROM {CAMPAIGN_TABLE} WHERE id = ?", (campaign,)
        )
        try:
            found = cursor.fetchone()
        finally:
            cursor.close()
        if found is None:
            raise KsGuardError(
                f"the campaign table holds no row for {campaign!r}; §7.4's "
                "guard persists a p-value *per campaign*, so a reading that "
                "cannot be joined to the campaign it was measured for is "
                "refused rather than written onto a row this store would "
                "have to invent — the campaign is created by its planner, "
                "before any node is expanded"
            )

    def _read_campaign_pvalue(
        self, connection: sqlite3.Connection, campaign: str
    ) -> Any:
        """The campaign row's ``ks_pvalue``, read back inside the transaction.

        The half-check: what the campaign row actually holds after the
        update, compared against what the guard row holds.  Reading it back
        rather than trusting the statement is the same defence the signal
        returns store applies to a stored net that does not equal its own
        gross less its own charge — the value downstream trusts is the
        stored one, so it is the stored one that is checked.
        """
        cursor = connection.execute(
            f"SELECT ks_pvalue FROM {CAMPAIGN_TABLE} WHERE id = ?", (campaign,)
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"campaign {campaign!r} vanished between the guard write and "
                "its read-back; the reading's two halves must both be "
                "accounted for, and a campaign that cannot be re-read is a "
                "campaign whose p-value is unverifiable"
            )
        return row[0]

    # -- The read-back -------------------------------------------------------

    def load(self, campaign_id: Any) -> Optional[KsGuardRecord]:
        """One campaign's persisted reading, or ``None`` — refusing a half.

        ``None`` means *the guard has not run for this campaign*, which is
        the honest answer for a campaign the orchestrator has created and no
        job has read yet.  It does **not** mean the read failed: an
        unreachable database or a campaign id that cannot join the tree
        store's key raises, so a caller can never mistake a broken store for
        an unguarded campaign — the distinction the sidecar's read path
        draws between an empty sidecar and an unopenable one.

        A campaign whose guard row exists but whose campaign column is
        ``NULL``, or the reverse, is refused with
        :class:`~nulloracle.errors.KsGuardError`: the two halves are one
        reading's content, and a reader must never see one without the
        other. That is the defence ``_capacity_store`` applies to a capacity
        row without its attribution, applied to the pair §7.4 writes.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"SELECT ks_pvalue FROM {CAMPAIGN_TABLE} WHERE id = ?",
                (campaign,),
            )
            try:
                campaign_row = cursor.fetchone()
            finally:
                cursor.close()
            if campaign_row is None:
                # No campaign: there is nothing a reading could belong to,
                # which is the same answer as an unguarded one and comes
                # from the same place — the orchestrator has not planned it.
                return None
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM {KS_GUARD_TABLE} WHERE campaign_id = ?",
                (campaign,),
            )
            try:
                guard_row = cursor.fetchone()
            finally:
                cursor.close()
        campaign_pvalue = campaign_row[0]
        if guard_row is None:
            if campaign_pvalue is not None:
                raise KsGuardError(
                    f"campaign {campaign!r} carries ks_pvalue "
                    f"{campaign_pvalue!r} but this store holds no guard "
                    "reading for it; §7.4's number and the provenance it was "
                    "computed from are one reading's content, and a reader "
                    "must never see one without the other"
                )
            return None
        record = guard_record_from_row(guard_row)
        if campaign_pvalue is None or float(campaign_pvalue) != record.pvalue:
            raise KsGuardError(
                f"campaign {campaign!r} carries ks_pvalue {campaign_pvalue!r} "
                f"and its guard reading holds {record.pvalue!r}; the two "
                "halves of one reading may not disagree — §7.4's number is "
                "what feature 124 voids a campaign on, so a store that could "
                "hand back either half of a disagreeing pair would launder a "
                "tamper"
            )
        return record


def load_ks_guard(
    campaign_id: Any,
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[KsGuardRecord]:
    """One campaign's stored reading, opening its own store — a single spelling.

    The read half of the module-level API: resolves the store from
    ``database_url`` (else ``DATABASE_URL``), and answers ``None`` when
    nothing names one at all — the same "no store, no reading" answer
    :meth:`KsGuard.load` gives for an unguarded campaign, kept distinct
    because a caller that mistook an unconfigured deployment for an
    unguarded campaign would skip §7.4's guard entirely.
    """
    if database_url is None:
        source = os.environ if env is None else env
        database_url = source.get(DATABASE_URL_ENV, "").strip()
        if not database_url:
            return None
    return KsGuard(database_url).load(campaign_id)


def persist_ks_pvalue(
    campaign_id: Any,
    null_scores: Mapping[Any, Any] | Iterable[float],
    real_scores: Mapping[Any, Any] | Iterable[float],
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    seen_at: Optional[datetime] = None,
) -> KsGuardRecord:
    """Run §7.4's guard and persist its p-value — the module-level spelling.

    Feature 123's sentence as one call: the two samples in, the p-value out,
    written against its campaign.  The store is resolved from
    ``database_url``, else from ``DATABASE_URL``; a deployment that names
    neither is refused *by name* rather than silently doing nothing,
    because a guard that quietly skipped its write would leave a campaign
    looking un-read while §7.4's job believed it had run — which is the
    failure mode this whole feature exists to rule out.

    A :class:`~nulloracle.errors.KsTestError` from the sample and a
    :class:`~nulloracle.errors.KsGuardError` from the store are both left to
    propagate unwrapped; see the taxonomy for why the two are kept apart.
    """
    source = os.environ if env is None else env
    url = database_url if database_url is not None else source.get(DATABASE_URL_ENV, "").strip()
    if not url:
        raise KsGuardError(
            f"persist_ks_pvalue persists a campaign's detectability reading "
            f"and nothing names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so the p-value could not be written "
            "down. §7.4's guard is a job that must actually run — a campaign "
            "whose reading silently went nowhere would look un-read"
        )
    return KsGuard(url).guard(
        campaign_id, null_scores, real_scores, seen_at=seen_at
    )
