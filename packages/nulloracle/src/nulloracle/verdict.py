"""Persisting §7.4's verdict against its campaign — feature 124's store half.

app_spec.xml, "Null Oracle & Planted Nulls", feature 124: *System persists a
campaign calibration_status of VOID when the KS p-value falls below 0.05,
which halts dreaming and excludes the campaign from the pool.*  :mod:`nulloracle.
ks` is the *test*, :mod:`nulloracle.ksguard` is the *measurement persisted*,
and this module is the *decision*: the comparison §7.4 spells and the
``VOID`` it sets on the campaign row.

**The threshold, and why it is a constant of this module.**  §7.4 writes the
whole rule in one line::

    if ks_pvalue < 0.05:
        campaign.calibration_status = VOID
        alert("nulls may be detectable — investigate block length")
        halt_dreaming()

and app_spec.xml gives *this* feature the comparison and the verdict — feature
123 stops at the number, this one decides what the number means.  So the level
that separates "calibrated" from "void" lives here, as :data:`VOID_THRESHOLD`,
rather than in the test that produced the number: feature 123's module
docstring argues that a test which also decided would be "two features wearing
one name", and the same argument runs in reverse — the verdict module is the
one place the 0.05 belongs, because it is the one place the verdict is
pronounced.  A reader tuning the tolerance finds it spelled once, beside the
comparison that uses it, rather than hunting every caller that voids a campaign.

**What this module writes, and what it pointedly does not.**  It writes
exactly one column — ``calibration_status`` on the campaign row — and only to
one value, ``'VOID'``.  It does **not** write the p-value (feature 123's), the
planning columns (the orchestrator's), or the guard's provenance row.  It does
not reset a campaign to ``'ok'``: ``'ok'`` is the default a freshly created
campaign carries, and a verdict module that could *clear* a VOID would be a
second decision wearing the first one's name — the only transition this
feature makes is *measured detectable → voided*, and a campaign that has been
voided stays voided until its planner, having investigated the block length
and permutation scheme as §7.4 instructs, creates a fresh campaign to re-read.
The comparison is strict ``<``, verbatim from §7.4: a p-value exactly at the
threshold is not below it, so it is not voided — the boundary errs toward
keeping a campaign in, and the operator's alert, not a silent exclusion, is
what §7.4 asks for at the margin.

**The verdict is a fact about a campaign, so the campaign must exist.**  The
same rule feature 123's store holds: a p-value is a fact *about a campaign*,
and a verdict that wrote ``calibration_status`` onto a row it invented would
be voiding a campaign nobody planned.  This module confirms the campaign is
held before it writes, and a missing campaign raises
:class:`~nulloracle.errors.KsGuardError` by name — the same error the guard's
store raises for the same reason, because *the campaign the verdict belongs to
is unknown* is the same contract failure whether the number or the verdict is
the thing being written.  The row is never created here: the campaign is
created by its planner, before any node is expanded.

**The p-value it compares, and the barrier it keeps.**  The verdict is
computed from the p-value feature 123 persisted — read back from
``campaign.ks_pvalue`` — not from a p-value the caller hands in.  That is
deliberate, and it is the whole reason this module reaches the database at
all: the number feature 124 voids a campaign on must be the number the system
actually persisted, read back and compared in one place, so a caller cannot
void a campaign on a p-value that never landed, or on a different one than the
guard recorded.  A caller that has just run the guard takes the whole path —
:func:`~nulloracle.ksguard.persist_ks_pvalue` writes the number, then
:func:`void_if_detectable` reads it back and decides — and the two are one
reading because the second reads what the first wrote.  What this module will
**not** do is take a p-value as an argument and void on it: that would be a
second, un-persisted p-value crossing the §4.2 barrier, and it would let a
caller void a campaign on a number the store never saw.  The verdict is
pronounced on the stored number, or not at all.

**One campaign, one row, one write.**  The grain is the campaign, the same
key the guard keyed its provenance on.  The verdict is an ``UPDATE`` of the
campaign row by its id, so re-running it — a replay, a retry after a crash —
sets the same value on the same row and leaves the campaign exactly as voided.
A campaign the guard found *not* detectable is left ``'ok'`` — the verdict
module does not touch a campaign whose p-value is at or above the threshold,
so a clean campaign's status is never rewritten and its default survives.

**The verdict is not the whole consequence, and this module says so.**  §7.4's
rule has three legs — set ``VOID``, ``alert(...)``, ``halt_dreaming()`` — and
app_spec.xml scopes this feature to the first and its downstream effect
(*"which halts dreaming and excludes the campaign from the pool"*).  So this
module persists the verdict and nothing else: the alert is the operator's
channel and the dreaming-halt and pool-exclusion are *consequences* of the
status being ``VOID``, enforced where the pool is read (features 876/1056) and
where promotion is decided — not here.  A verdict module that also tried to
halt dreaming would be reaching past its one column into the orchestrator's
control flow, and the pool's own refusal is the place that exclusion must live
so it holds no matter what set the status.  This module makes the status true;
the rest of the system is built to react to a ``VOID`` status, which is the
design §7.4's *"which halts dreaming and excludes the campaign from the pool"*
clause describes.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime`` and
``urllib.parse``; no third-party import at module scope, so the factory's
scan — which imports this package to fire its ``@register`` — pays nothing for
this module.  That matters the same way it matters for the guard: the member
already defers ``cryptography`` to first use, and a verdict that pulled a
driver in at import would undo that.  The verdict shares the guard's store
conventions — the same ``DATABASE_URL_ENV``, the same ``_sqlite_path`` shape,
the same ``CREATE TABLE IF NOT EXISTS`` idempotency — restated here rather than
imported, because a migration is loaded by path and a store must not depend on
a workspace package being importable, and this module must not depend on the
guard's module being on ``sys.path`` in order to open a database.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from .assignment import normalize_node_id
from .errors import KsGuardError

__all__ = [
    "CAMPAIGN_TABLE",
    "CALIBRATION_STATUS_OK",
    "CALIBRATION_STATUS_VOID",
    "DATABASE_URL_ENV",
    "VOID_THRESHOLD",
    "CampaignVerdict",
    "Verdict",
    "load_verdict",
    "void_if_detectable",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the guard's, the
#: evaluator's five, the repository-level conftest's), restated here so each
#: store states its own contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the verdict is written to — feature 104's ``campaign``, created
#: by ``migrations/versions/0111_campaign_table.py``.  Spelled once here, and
#: once in :mod:`nulloracle.ksguard`, so the verdict writer and the guard
#: writer cannot drift apart on what the campaign table is called; both name
#: the column the migration created.
CAMPAIGN_TABLE = "campaign"

#: The campaign table's calibration column — the one §7.4's verdict sets.
CALIBRATION_COLUMN = "calibration_status"

#: The verdict this module pronounces: a campaign whose nulls are detectable.
#: The spec's own spelling, and the value features 876 and 1056 reject a
#: campaign on.
CALIBRATION_STATUS_VOID = "VOID"

#: The status a campaign carries until it is voided — the migration's default,
#: restated so this module names the value it *leaves* a clean campaign in
#: rather than only the value it sets.  This module never writes it; it is
#: here so a returned :class:`Verdict` can name the state a clean campaign is
#: in, and so the two statuses the system distinguishes are spelled together.
CALIBRATION_STATUS_OK = "ok"

#: §7.4's level, verbatim: ``if ks_pvalue < 0.05``.  A p-value strictly below
#: this voids the campaign; a p-value at or above it leaves the campaign as it
#: is.  Strict ``<`` rather than ``<=`` is deliberate — the boundary errs
#: toward keeping a campaign in, and the value is a constant of this module
#: because this module is the one place the verdict is pronounced.
VOID_THRESHOLD = 0.05


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's
    ``node.id``*, and ``campaign``'s ``id`` is the same kind of value — but
    re-raises its refusal as :class:`~nulloracle.errors.KsGuardError`.
    The distinction is the taxonomy's: a malformed id handed to the *verdict*
    is a store-contract failure, not a sidecar-schema one, and a caller
    reading ``SidecarError`` out of a KS verdict would look in the wrong
    module for the cause.  The guard's verdict and this module's share the
    same id kind and the same error, so a campaign that is voided and a
    campaign whose p-value is persisted are validated identically.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:  # noqa: BLE001 - re-raised by name below
        raise KsGuardError(
            f"campaign_id {value!r} is not a UUID: {exc}"
        ) from exc


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.
    A non-SQLite scheme is refused loudly — the Postgres store arrives with
    the migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a verdict
    written to a database that then vanished would leave a campaign looking
    calibrated when it had in fact been voided.
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
            "it, and a campaign's verdict must outlive the guard run that "
            "produced the p-value it is pronounced on"
        )
    return Path(path)


class Verdict:
    """The outcome of pronouncing §7.4's verdict on one campaign.

    What the verdict *was*, not merely what the status *is now*: a campaign
    already voided, re-run through the verdict, is still void, and the record
    says so — the caller is entitled to know whether this call changed
    anything.  Frozen and validated in :meth:`__init__` — the four fields are
    set through ``object.__setattr__`` and every other assignment is refused —
    because a verdict is the value an operator reads and the pool's refusals
    act on, and a verdict that could state a status this module never writes,
    or a campaign id that is not a UUID, would be a decision that could not be
    trusted.
    """

    __slots__ = ("_campaign_id", "_pvalue", "_status", "_voided")

    def __init__(self, *, campaign_id: Any, status: str, pvalue: float, voided: bool) -> None:
        object.__setattr__(self, "_campaign_id", _validated_campaign_id(campaign_id))
        status_text = status if isinstance(status, str) else str(status)
        if status_text not in (CALIBRATION_STATUS_VOID, CALIBRATION_STATUS_OK):
            raise KsGuardError(
                f"calibration_status must be {CALIBRATION_STATUS_VOID!r} or "
                f"{CALIBRATION_STATUS_OK!r}, got {status!r}; those are the only "
                "two statuses §7.4's discipline distinguishes, and a verdict "
                "stating any other would be a status no reader of the campaign "
                "row expects"
            )
        object.__setattr__(self, "_status", status_text)
        if isinstance(pvalue, bool) or not isinstance(pvalue, (int, float)):
            raise KsGuardError(
                f"pvalue must be a real number, got {pvalue!r} "
                f"({type(pvalue).__name__}); the verdict is pronounced on the "
                "stored p-value, and a non-numeric one is a number no test produced"
            )
        number = float(pvalue)
        if not 0.0 <= number <= 1.0:
            raise KsGuardError(
                f"pvalue must lie in [0, 1], got {number!r}; a KS p-value is a "
                "probability, and a value outside that range would enter the "
                "`p < 0.05` comparison as a number no test produced"
            )
        object.__setattr__(self, "_pvalue", number)
        if not isinstance(voided, bool):
            raise KsGuardError(
                f"voided must be a bool, got {voided!r} "
                f"({type(voided).__name__}); whether this call changed the "
                "campaign is one bit, and a truthy-looking non-bool is the "
                "value that would silently misreport the verdict"
            )
        # The status and the voided bit cannot disagree in the one way that
        # would be a verdict that cannot explain itself: a call that did not
        # void and did not find the campaign already voided must leave it ok.
        # The reverse — VOID with voided=False — is legitimate: a verdict
        # re-run on a campaign an earlier call already voided. What is refused
        # is a call claiming to void (voided=True) while the status is ok.
        if voided and status_text != CALIBRATION_STATUS_VOID:
            raise KsGuardError(
                f"status {status_text!r} and voided={voided!r} disagree: a "
                "call that voided the campaign must leave it VOID, and a call "
                "that left it ok must report voided=False"
            )
        object.__setattr__(self, "_voided", voided)

    @property
    def campaign_id(self) -> str:
        """The campaign this verdict was pronounced on, canonical UUID text."""
        return self._campaign_id

    @property
    def status(self) -> str:
        """The campaign's calibration status after this verdict."""
        return self._status

    @property
    def pvalue(self) -> float:
        """The stored p-value the verdict was pronounced on."""
        return self._pvalue

    @property
    def voided(self) -> bool:
        """Whether this call set the campaign to VOID.

        ``True`` means this call wrote ``VOID``; a campaign already voided
        before this call reports ``voided`` as ``False`` but ``status`` as
        ``VOID`` — the verdict is stable, and the record distinguishes *this
        call changed it* from *it was already void*.
        """
        return self._voided

    @property
    def is_void(self) -> bool:
        """Whether the campaign is void after this verdict."""
        return self._status == CALIBRATION_STATUS_VOID

    def to_payload(self) -> dict[str, Any]:
        """The verdict as a plain mapping, for a log line or an operator's report.

        The field names are the record's own, so a rendered mapping and a
        structured log record name the same things the same way.
        """
        return {
            "campaign_id": self._campaign_id,
            "status": self._status,
            "pvalue": self._pvalue,
            "voided": self._voided,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Verdict):
            return NotImplemented
        return (
            self._campaign_id == other._campaign_id
            and self._status == other._status
            and self._pvalue == other._pvalue
            and self._voided == other._voided
        )

    def __repr__(self) -> str:
        action = "voided" if self._voided else "unchanged"
        return (
            f"Verdict(campaign_id={self._campaign_id!r}, status={self._status!r}, "
            f"pvalue={self._pvalue!r}, {action})"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        # Frozen: the verdict is the value an operator reads and the pool's
        # refusals act on, so once pronounced it cannot be edited into a
        # different decision.  The slots hold only the four fields, all set in
        # ``__init__`` via ``object.__setattr__``; anything else is refused.
        raise AttributeError(
            f"{type(self).__name__} is frozen; a pronounced verdict cannot be "
            "edited into a different decision"
        )


class CampaignVerdict:
    """§7.4's verdict: the ``p < 0.05`` comparison and the ``VOID`` it sets.

    Constructed with the database URL it reads from; :meth:`void_if_detectable`
    reads the stored p-value, compares it to :data:`VOID_THRESHOLD`, and sets
    ``calibration_status = VOID`` when it falls below; :meth:`load` reads one
    campaign's status back.  The class resolves its path lazily, so
    constructing one performs no I/O — composition-time work must not touch the
    disk, the contract every store in this workspace states.

    The verdict holds no scores and no labels: it reads one number off the
    campaign row, compares it to a constant, and writes one column.  There is
    no field here that could leak a label partition, deliberately — see the
    module docstring and §4.2.
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
    ) -> Optional["CampaignVerdict"]:
        """The verdict store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no verdict component — a discoverable state, not an exception — while
        the campaign job that must pronounce §7.4's verdict is the caller that
        must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this verdict store reads from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the campaign table exists, idempotently.

        ``CREATE TABLE IF NOT EXISTS`` on the campaign table — the contract
        every store in this workspace states and the one
        ``migrations/versions/0111_campaign_table.py`` describes for its
        orchestrator: a fresh database and an existing one take the same path,
        so no migration step is needed here and running the migration over a
        database this store created changes nothing.  The caller owns the
        connection; use it as a context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(
                f"""
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
            )
        return connection

    # -- Feature 124: the verdict -----------------------------------------

    def void_if_detectable(self, campaign_id: Any) -> Verdict:
        """Pronounce §7.4's verdict on ``campaign_id`` and persist it.

        The whole of feature 124 in one call: the campaign is confirmed to
        exist, its stored p-value is read back from ``campaign.ks_pvalue``,
        and when that p-value is strictly below :data:`VOID_THRESHOLD` the
        campaign's ``calibration_status`` is set to ``VOID``.

        The p-value compared is the **stored** one, read back inside the same
        transaction that writes the verdict — not a p-value the caller hands
        in.  That is deliberate: the number feature 124 voids a campaign on
        must be the number feature 123 actually persisted, so a caller cannot
        void a campaign on a p-value that never landed or on a different one
        than the guard recorded.  A campaign with no stored p-value yet — the
        guard has not run — is left ``'ok'`` and reported ``voided`` as
        ``False``: an un-read campaign has not been measured, so there is no
        detectability finding to void it on, which is the honest state for a
        campaign whose read has not happened.

        Refuses, in this order, and each refusal names what it is about:

        1. a malformed ``campaign_id`` or a campaign the table does not hold
           (:class:`~nulloracle.errors.KsGuardError`) — the verdict is a fact
           about a campaign, and writing it onto a row this store invented
           would fabricate the campaign the verdict belongs to;
        2. a stored p-value that is not a probability in ``[0, 1]``
           (:class:`~nulloracle.errors.KsGuardError`) — a number outside that
           range is not a p-value any test produced, and voiding a campaign on
           it would be the exact plausible-looking number this member exists
           to keep out of the calibration record;
        3. a write that could not be completed.

        The verdict is idempotent by campaign: re-running it on an already
        voided campaign leaves the campaign void and reports ``voided`` as
        ``False`` — the verdict is stable, and §7.4's instruction to
        "investigate the block length and permutation scheme before
        proceeding" means a campaign is expected to be judged more than once.
        A campaign whose p-value is at or above the threshold is left exactly
        as it was — its ``'ok'`` default survives, and this call reports
        ``voided`` as ``False``.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection, connection:
            self._require_campaign(connection, campaign)
            stored = self._read_campaign_pvalue(connection, campaign)
            already = self._read_campaign_status(connection, campaign)
            if stored is None:
                # The guard has not run: no p-value, no finding, no verdict to
                # pronounce. The campaign keeps its 'ok' default; this call
                # changes nothing and says so.
                return Verdict(
                    campaign_id=campaign,
                    status=CALIBRATION_STATUS_OK,
                    pvalue=1.0,
                    voided=False,
                )
            below = stored < VOID_THRESHOLD
            # The verdict is pronounced on the stored number, but the *write*
            # is conditional on the campaign not already being voided: a
            # verdict re-run on an already-voided campaign leaves it void and
            # reports that this call did not change it. The verdict is stable,
            # and the record distinguishes *this call changed it* from *it was
            # already void*.
            changed_this_call = below and already != CALIBRATION_STATUS_VOID
            if changed_this_call:
                connection.execute(
                    f"UPDATE {CAMPAIGN_TABLE} SET {CALIBRATION_COLUMN} = ? "
                    "WHERE id = ?",
                    (CALIBRATION_STATUS_VOID, campaign),
                )
            status = self._read_campaign_status(connection, campaign)
            expected = CALIBRATION_STATUS_VOID if (already == CALIBRATION_STATUS_VOID or below) else CALIBRATION_STATUS_OK
            if status != expected:
                raise KsGuardError(
                    f"campaign {campaign!r} was written {CALIBRATION_COLUMN}="
                    f"{status!r} against a verdict expecting {expected!r}; the "
                    "status the campaign row actually holds and the verdict "
                    "pronounced on it must agree, and a disagreement is not a "
                    "verdict"
                )
        return Verdict(
            campaign_id=campaign,
            status=status,
            pvalue=stored,
            voided=changed_this_call,
        )

    def load(self, campaign_id: Any) -> Optional[str]:
        """One campaign's calibration status, or ``None`` when it is not held.

        ``None`` means *the campaign was never planned* — the orchestrator has
        not created it — which is the honest answer for an id the table does
        not hold.  It does **not** mean the read failed: an unreachable
        database or a campaign id that cannot join the tree store's key raises,
        so a caller can never mistake a broken store for an unplanned campaign.
        The status returned is the campaign row's own ``calibration_status`` —
        ``'ok'`` by default, ``VOID`` once feature 124 has voided it — the
        value features 876 and 1056 read to reject a campaign from the replay
        pool and from promotion.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"SELECT {CALIBRATION_COLUMN} FROM {CAMPAIGN_TABLE} WHERE id = ?",
                (campaign,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        return row[0]

    def _require_campaign(self, connection: sqlite3.Connection, campaign: str) -> None:
        """Refuse a campaign the table does not hold, by name.

        The verdict joins the campaign row — it is written there, the pool's
        refusals read it there — so a verdict run against a campaign nobody
        planned is a caller bug worth learning before a status lands nowhere.
        The check is a read, not a create: a store that inserted the missing
        campaign would be inventing the row the fraction and the type belong on.
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
                "verdict voids a campaign *per campaign*, so a verdict that "
                "cannot be joined to the campaign it was pronounced on is "
                "refused rather than written onto a row this store would have "
                "to invent — the campaign is created by its planner, before "
                "any node is expanded"
            )

    def _read_campaign_pvalue(
        self, connection: sqlite3.Connection, campaign: str
    ) -> Any:
        """The campaign row's ``ks_pvalue``, read back inside the transaction.

        The number the verdict is pronounced on — read back rather than
        trusted from a caller's argument, because the p-value feature 124 voids
        a campaign on must be the one feature 123 persisted.  A campaign that
        vanished between the read and the write is refused: the verdict's
        number and the status it sets must both be accounted for, and a
        campaign that cannot be re-read is a campaign whose verdict is
        unverifiable.
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
                f"campaign {campaign!r} vanished between the verdict read and "
                "its write; the verdict's number and the status it sets must "
                "both be accounted for, and a campaign that cannot be re-read "
                "is a campaign whose verdict is unverifiable"
            )
        return row[0]

    def _read_campaign_status(
        self, connection: sqlite3.Connection, campaign: str
    ) -> str:
        """The campaign row's ``calibration_status``, read back inside the write.

        The half-check: what the campaign row actually holds after the update,
        compared against the verdict pronounced.  Reading it back rather than
        trusting the statement is the same defence the guard applies to a
        stored p-value that does not equal its own write — the status the pool
        will read is the stored one, so it is the stored one that is checked.
        """
        cursor = connection.execute(
            f"SELECT {CALIBRATION_COLUMN} FROM {CAMPAIGN_TABLE} WHERE id = ?",
            (campaign,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"campaign {campaign!r} vanished between the verdict write and "
                "its read-back; the verdict's number and the status it sets "
                "must both be accounted for, and a campaign that cannot be "
                "re-read is a campaign whose verdict is unverifiable"
            )
        return row[0]


def load_verdict(
    campaign_id: Any,
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """One campaign's calibration status, opening its own store — a single spelling.

    The read half of the module-level API: resolves the store from
    ``database_url`` (else ``DATABASE_URL``), and answers ``None`` when
    nothing names one at all — the same "no store, no status" answer
    :meth:`CampaignVerdict.load` gives for an unplanned campaign, kept distinct
    because a caller that mistook an unconfigured deployment for an unjudged
    campaign would skip §7.4's verdict entirely.
    """
    if database_url is None:
        source = os.environ if env is None else env
        database_url = source.get(DATABASE_URL_ENV, "").strip()
        if not database_url:
            return None
    return CampaignVerdict(database_url).load(campaign_id)


def void_if_detectable(
    campaign_id: Any,
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Verdict:
    """Pronounce §7.4's verdict and persist it — the module-level spelling.

    Feature 124's sentence as one call: the campaign's stored p-value is read
    back and compared to :data:`VOID_THRESHOLD`, and when it falls below, the
    campaign is voided.  The store is resolved from ``database_url``, else from
    ``DATABASE_URL``; a deployment that names neither is refused *by name*
    rather than silently doing nothing, because a verdict that quietly skipped
    its write would leave a campaign looking calibrated while §7.4's job
    believed it had been judged — which is the failure mode this whole feature
    exists to rule out.

    A :class:`~nulloracle.errors.KsGuardError` from the store is left to
    propagate unwrapped; see the taxonomy for why the verdict's store failures
    share the guard's error.
    """
    source = os.environ if env is None else env
    url = database_url if database_url is not None else source.get(DATABASE_URL_ENV, "").strip()
    if not url:
        raise KsGuardError(
            f"void_if_detectable pronounces §7.4's verdict and nothing names a "
            f"store: {DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the verdict could not be written down. §7.4's "
            "verdict is a judgment that must actually be recorded — a campaign "
            "whose verdict silently went nowhere would look calibrated while "
            "its nulls were detectable"
        )
    return CampaignVerdict(url).void_if_detectable(campaign_id)
