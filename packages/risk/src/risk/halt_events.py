"""Feature 331: the halt event ledger, persisted for later reconciliation.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 331: *"System
persists every halt event with its trigger reason and timestamp for later
reconciliation."*  ``docs/nullius-tech-architecture.md`` §13.3 line 717
gives the category its shape — the supervisor runs *"as a separate process
with kill authority over the execution engine"* — and the trigger table
directly below it (equity floor, daily loss, IC decay, staleness, clock
skew) names the halts whose events will land here; none of them is this
feature's to fire.  ``docs/alpha-engine-prd.md`` C10 names the subject —
*"Risk and kill switches"* — and its bullets name the same triggers
again, each a feature of its own (323–329) with its own module and its
own repair.

Read together with the member this one builds on, the sentence makes a
narrower demand than *"log something when trading stops"*: **every halt
event lands, each row says why and when, and the record outlives the
process that wrote it.**  Three words carry the whole contract:

* **Every.**  The ledger is append-only.  Where feature 322's channel is
  a *state* — one row, first-write-wins, a re-send writes nothing — this
  table is the *log*: a halt that happened twice is recorded twice, and
  completeness is the feature, because a reconciliation over a ledger
  with a hole in it reconciles nothing (the kill module refused to write
  here precisely so this one would be the record's only writer, and the
  one writer a later reconciliation has to trust).  No surface this
  module exposes writes a row away — no ``clear``, no ``trim``, no
  ``erase`` — and the ``AUTOINCREMENT`` key states the never-reuse law
  at the storage layer, so even a tool that deleted rows could not mint
  an event wearing a dead event's number.
* **Its trigger reason and timestamp.**  Each row carries the reason the
  halt fired and the moment it fired (``triggered_at``), beside the
  moment the row was written (``recorded_at``) — the same split
  :mod:`canary._halt` states for its ``detected_at``/``halted_at``, kept
  because the gap between them is itself a reconciliation fact: a
  supervisor that records long after it triggered was hung, and the row
  is where an operator reads that.  The recording process's
  ``<host>/<pid>`` is on the row too, read from the kernel by
  :func:`risk.process_identity` — the one spelling of that fact, so a
  kill instruction and the halt events around it split the same under a
  single operator grep.
* **For later reconciliation.**  The read is a sweep:
  :meth:`RiskHaltEventStore.events` answers every event on record,
  oldest first, ordered by the trigger's own moment with the append
  order breaking same-instant ties; a caller anchoring the sweep at an
  instant (feature 322's ``sent_at`` is the anchor its own docstrings
  promised this feature would order against) passes ``since`` and reads
  the suffix from there.  The reconciliation itself is the caller's act
  — this module holds the record, not the verdict, for the same reason
  :mod:`risk.kill` holds the channel and not the triggers.

**The trigger vocabulary is deliberately open, and presence is the
law.**  The trigger reason is non-empty text and nothing more: §13.3's
table names the triggers, but the *words* for them belong to the features
that fire them (323's door, 324's floor, 325's limit, 328's watchdog,
329's skew), each arriving with its own module — a ledger that enumerated
their vocabulary would be five features' words wearing one table, and a
``CHECK`` that refused an unlisted word would refuse a write at the exact
moment a halt must be recorded, losing the one event this feature exists
to keep.  So the value layer refuses a reason that states nothing
(empty, whitespace, not text) and stores any word it can carry, and the
schema holds the structural laws (append-only, never-reuse) rather than
a vocabulary it cannot own.

**Like the kill channel, this is a table two processes share, and for
the same reason.**  The process that halts (or the operator pronouncing
a halt after the fact) and the process that reconciles later are
different processes, and §17 leaves no port to serve a socket on; the
relational store both already hold is the medium, and it is the medium
that survives the failure this category is for.  Each operation opens
its own connection, and the member's suite proves the cross-process case
against an actual second interpreter: an event a separate supervisor
records is an event this process reconciles.

**The ledger's absence cuts asymmetrically, the kill channel's own
split.**  :func:`record_halt` — the halting process's spelling —
*refuses* when nothing names a store: a halt event that silently went
nowhere is exactly the hole in the record that makes a later
reconciliation a confident fiction.  :func:`recorded_halt_events` — the
reconciler's spelling — answers an empty tuple when nothing names a
store, the *"no store, no status"* stance :func:`risk.require_orders_allowed`
takes: recording refuses without a store, so a deployment that names
none holds no events to reconcile, and an empty ledger is the truthful
answer, not a clean bill.

**What this module deliberately does not do.**  It does not *halt*: the
instruction is feature 322's send, the door is feature 323's, and a
ledger that also stopped trading would be two features wearing one verb.
It does not *decide* triggers: features 323–329 own their words and their
repairs, and this module records the halts that happened rather than
judging the ones that should have.  It does not *reconcile*: joining
events to kills, windows and resets is a later reader's act — this is
the record that act is performed against, which is why the read refuses
a row no event can be reconstructed as instead of skipping it (a skipped
row is a hole wearing a shrug).

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as the channel beside it is, and the schema is created
idempotently on connect, so no migration step is needed.  A URL whose
scheme is not ``sqlite`` is refused by name — as an *address* fault, in
:class:`~risk.errors.RiskStoreError`, the vocabulary that fault already
belongs to — while the event's own terms (a reason that states nothing,
a moment that states no time, a row no event can be) are refused in this
feature's own class, :class:`~risk.errors.RiskHaltEventError`.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ._identity import process_identity
from .errors import HALT_EVENT_CODE, RiskHaltEventError, RiskStoreError

__all__ = [
    "DATABASE_URL_ENV",
    "RISK_HALT_EVENT_TABLE",
    "HaltEvent",
    "RiskHaltEventStore",
    "record_halt",
    "recorded_halt_events",
]

#: The workspace-wide environment variable naming the relational store —
#: the one spelling every store in this workspace already uses, restated
#: here so this module states its own contract and imports no sibling's.
DATABASE_URL_ENV = "DATABASE_URL"

#: This feature's own table — one row per halt event, the append-only log
#: the category's reconciliation reads.  It is deliberately not the kill
#: channel's table and not a column on it: ``risk_order_kill`` is a
#: *state* (one row, first-write-wins — the instruction that stands),
#: while this is the *record of what happened* (every event, ever), and
#: forcing a log into a one-row table or a state into an append-only one
#: would break whichever law the other table exists to hold.
RISK_HALT_EVENT_TABLE = "risk_halt_event"

#: ``risk_halt_event``'s DDL, created idempotently beside the code that
#: reads it — the same member-owned-table stance :mod:`risk.kill` takes
#: for the channel and :mod:`canary._halt` for its halt rows, and
#: deliberately *not* a migration: this table has exactly one writer and
#: one reader, both in this module.
#:
#: The ``AUTOINCREMENT`` key is the ledger's own law stated where a raw
#: row disposal from another tool cannot quietly break it: event numbers are
#: monotone and never reused, so a number an operator cites in a
#: reconciliation report names one event for the life of the table.  It
#: is also the tiebreak the read orders by — two events triggered at the
#: same instant keep the order they were recorded in, which is the only
#: order they have.  There is no ``CHECK`` on ``trigger_reason``: the
#: vocabulary belongs to the features that fire halts (see the module
#: docstring), and a schema that refused an unlisted word would refuse
#: the write at the exact moment a halt must be recorded.
_SCHEMA = f"""
-- Feature 331: every halt event, appended with its trigger reason and
-- timestamp for later reconciliation.  One row per event, forever: the kill
-- channel (risk_order_kill) is the state that stands; this is the log of
-- what happened, and completeness is the feature a reconciliation depends
-- on -- nothing here updates or deletes, and `sequence` never names two
-- events.
--
-- `trigger_reason` is the word the halting feature owns (323's door, 324's
-- floor, 325's limit, 328's watchdog, 329's skew): free text, refused only
-- when it states nothing.  `triggered_at` is when the trigger fired -- the
-- sentence's own timestamp; `recorded_at` is when this row was written, and
-- the gap between the two is a fact a reconciliation reads (a supervisor
-- that records long after it triggered was hung).  Both are ISO 8601 UTC.
-- `supervisor_process_id` is the recording process's <host>/<pid>, read
-- from the kernel by risk._identity.process_identity.
CREATE TABLE IF NOT EXISTS {RISK_HALT_EVENT_TABLE} (
    sequence              INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_reason        TEXT NOT NULL,
    triggered_at          TEXT NOT NULL,
    recorded_at           TEXT NOT NULL,
    supervisor_process_id TEXT NOT NULL
);

-- The reconciliation read is always a sweep over the trigger's moment
-- (whole ledger, or the suffix from an anchor), so that is the indexed
-- column; the sequence tiebreak rides the same scan.
CREATE INDEX IF NOT EXISTS {RISK_HALT_EVENT_TABLE}_triggered_at
    ON {RISK_HALT_EVENT_TABLE} (triggered_at);
"""

#: The columns of :data:`RISK_HALT_EVENT_TABLE`, in the order the insert
#: names them and the order the read-back unpacks them.  Spelled once so
#: the write and the read cannot drift apart on a column order — the
#: failure a positional ``SELECT *`` invites.  ``sequence`` is
#: deliberately absent from the write and present in the read: it is the
#: row's own number, minted by the insert, never supplied by the caller.
_COLUMNS = "trigger_reason, triggered_at, recorded_at, supervisor_process_id"


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :mod:`risk.kill` and every other store in this
    workspace states, in this module's own words, for the reason each of
    them restates it: a store reaches into no sibling's private helper, so
    a later change to one table's address handling cannot silently move
    another's.  ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is
    absolute, and any other scheme is refused by name.

    Raises :class:`~risk.errors.RiskStoreError`, **not** this feature's
    own class: an address this member cannot speak is an *address* fault
    with an address repair — point the deployment at a database this
    store can open — which is the face :class:`~risk.errors.RiskStoreError`
    exists for, the split the kill channel already states.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RiskStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "halt event ledger speaks sqlite:/// (the spec's single-machine "
            f"allowance); point {DATABASE_URL_ENV} at the sqlite database "
            "the halt events are recorded in (feature 331)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 331)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a halt event that vanished would leave the "
            "reconciliation this feature exists for reading a ledger with "
            "a hole in it (feature 331)"
        )
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    Every row this store writes goes through here — one UTC offset, one
    format, one width policy — and the read path parses what
    :func:`datetime.fromisoformat` accepts and refuses the rest, so a row
    another tool wrote in another spelling never survives into a
    reconciliation unparsed.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* the halt was
    triggered, and an event whose moment cannot be ordered cannot take its
    place in the sweep this feature's whole second half exists for — the
    same discipline :mod:`risk.kill` holds its ``sent_at`` to, and the
    reason it is checked here rather than assumed.
    """
    if not isinstance(moment, datetime):
        raise RiskHaltEventError(
            f"{HALT_EVENT_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__} (feature 331)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RiskHaltEventError(
            f"{HALT_EVENT_CODE}: {what} must be timezone-aware; a halt "
            "event must say unambiguously when it was triggered, or the "
            "reconciliation that orders events cannot order this one "
            "(feature 331)"
        )
    return moment


def _require_text(value: object, what: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    The trigger reason is a *statement* — the one word the halting feature
    owns for why trading stopped — and a reason that states nothing is an
    event no reconciliation can attribute.  The vocabulary around it is
    deliberately open (the words belong to features 323–329); presence is
    the part this module enforces, near-miss rule included: a
    whitespace-only reason would file as a second spelling of nothing.
    """
    if not isinstance(value, str) or not value.strip():
        raise RiskHaltEventError(
            f"{HALT_EVENT_CODE}: {what} must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); a halt event that cannot "
            "say why it fired is unauditable at exactly the moment a "
            "reconciliation asks (feature 331)"
        )
    return value.strip()


def _require_sequence(value: object) -> int:
    """Return ``value`` as a ledger sequence, or refuse it by name.

    The sequence is the row's ``AUTOINCREMENT`` number — minted by the
    insert, monotone, never reused — so a caller never supplies one and a
    row carrying ``0``, a negative, a bool dressed as an int, or anything
    that is not an ``int`` is a row this store did not write.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskHaltEventError(
            f"{HALT_EVENT_CODE}: a halt event's sequence is the number the "
            f"ledger minted, an int, got {value!r} "
            f"({type(value).__name__}); the number is how an operator cites "
            "one event in a reconciliation report, and a value that cannot "
            "be one is a row no reader filed (feature 331)"
        )
    if value < 1:
        raise RiskHaltEventError(
            f"{HALT_EVENT_CODE}: a halt event's sequence is numbered from "
            f"1 upward, got {value!r}; AUTOINCREMENT never mints 0 or a "
            "negative, and a row wearing one is a row this store did not "
            "write (feature 331)"
        )
    return value


# -- The record -----------------------------------------------------------------


@dataclass(frozen=True)
class HaltEvent:
    """One halt event: why trading stopped, when, and who recorded it.

    A *value* — frozen, self-describing — carrying the whole of feature
    331's sentence: trading was halted for ``trigger_reason`` at
    ``triggered_at``, the row was written at ``recorded_at`` by
    ``supervisor_process_id``, and it holds the ledger's own number in
    ``sequence``.  It is what :meth:`RiskHaltEventStore.record` writes and
    returns and what :meth:`RiskHaltEventStore.events` reads back — one
    type for both, so the record an operator reconciles against and the
    row the ledger holds cannot be two things that disagree.

    Validated in :meth:`__post_init__` rather than only where it is built,
    because the read path reconstructs one from every stored row: a row
    edited outside this package — a reason that states nothing, a moment
    no parser accepts, a sequence the ledger never minted — fails to
    reconstruct rather than loading as a plausible-looking event, the same
    defence :class:`~risk.kill.KillInstruction` applies to its own row,
    and for the same reason: what a reconciliation trusts is the stored
    record, and a store that could hand back an event disagreeing with
    its own row would launder a hole into a ledger whose completeness is
    the feature.

    There is no ``changed`` bit, and that absence is a decision rather
    than an omission: the channel's ``changed`` answers *did this call
    write the row?* over a table where a later send writes nothing, while
    this ledger is append-only — every :meth:`RiskHaltEventStore.record`
    writes exactly one row, so the question has the same answer every
    time and the bit would only invite a caller to reason about a
    first-write-wins semantics this table refuses to have.
    """

    #: The event's number in the ledger — the ``AUTOINCREMENT`` key of the
    #: row it landed in.  Monotone, never reused, and the number an
    #: operator cites when a reconciliation report must point at one
    #: event; two events triggered at the same instant are told apart by
    #: it, in the order they were recorded.
    sequence: int
    #: Why the halt fired.  The halting feature's own word — 323's door,
    #: 324's floor, 325's limit, 328's watchdog, 329's skew — carried as
    #: given and refused only when it states nothing, because the
    #: vocabulary belongs to the features that halt and this ledger must
    #: never refuse the write that records one.
    trigger_reason: str
    #: When the trigger fired — the sentence's own timestamp, and the
    #: datum the reconciliation sweep orders by and anchors on.  The
    #: caller's to state (a halt observed late is still recorded at its
    #: own moment), timezone-aware, stored in the table's one canonical
    #: UTC spelling.
    triggered_at: datetime
    #: When the ledger wrote this row.  The store's own fact, never the
    #: caller's to state, and deliberately beside ``triggered_at``: the
    #: gap between the two is what a reconciliation reads off a
    #: supervisor that was hung between triggering and recording.
    recorded_at: datetime
    #: The identity of the process that recorded the event (see
    #: :func:`risk.process_identity`) — never accepted from an
    #: unlabelled default, keyword-only to override, so the record names
    #: the process that wrote it exactly as the kill channel's rows do.
    supervisor_process_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sequence", _require_sequence(self.sequence))
        object.__setattr__(
            self, "trigger_reason", _require_text(self.trigger_reason, "trigger_reason")
        )
        _require_aware(self.triggered_at, "triggered_at")
        _require_aware(self.recorded_at, "recorded_at")
        object.__setattr__(
            self,
            "supervisor_process_id",
            _require_text(self.supervisor_process_id, "supervisor_process_id"),
        )

    @property
    def summary(self) -> str:
        """One sentence: why trading halted, when, and who recorded it.

        Composed rather than stored, because every part of it is already a
        field — a stored copy would be a second place for the record's own
        facts to live, and an edited row would then disagree with its own
        summary.  The reason is spelled in full and the moments in the
        table's own ISO form, so an operator reading a log line can grep
        the ledger by either — and the event's number leads, because
        "which event?" is the question a reconciliation report answers
        first.
        """
        return (
            f"halt event {self.sequence}: trading was halted for "
            f"{self.trigger_reason!r} at {_isoformat_utc(self.triggered_at)}, "
            f"recorded by {self.supervisor_process_id} at "
            f"{_isoformat_utc(self.recorded_at)}"
        )


# -- The store ------------------------------------------------------------------


class RiskHaltEventStore:
    """Records every halt event, and reads the ledger back for reconciliation.

    Bound to a database URL at construction; construction performs no I/O,
    so composing an application never touches the database and a store
    costs nothing until an event is recorded or read.  Each operation
    opens its own connection (creating the schema idempotently if absent),
    the discipline every store in this workspace follows — which is what
    makes an event a *separate supervisor process* records readable from
    the process that reconciles later: the database, not any process's
    memory, is the coordination point, and §17 leaves no other channel to
    try.

    Two faces, one object: the halting process calls :meth:`record`; the
    reconciler calls :meth:`events`.  Neither face holds state of its own
    beyond the URL and this process's identity, so a restarted anything
    reads the same ledger as the process it replaced — and appends to it,
    which is the whole difference between this table and the one-row
    channel beside it.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RiskStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._process_id: str | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RiskHaltEventStore | None:
        """The ledger ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — absent is a
        discoverable deployment state, not an exception, the stance every
        store in this workspace takes.  What a caller does with the
        ``None`` is the caller's direction to decide, and the two
        directions this ledger cuts are deliberately split in this module:
        :func:`record_halt` refuses on it, :func:`recorded_halt_events`
        answers an empty tuple on it (see the module docstring for why
        the asymmetry is the feature, not an accident).
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this ledger records and reads through."""
        return self._database_url

    @property
    def process_id(self) -> str:
        """This process's identity — the label its halt event rows file under.

        Resolved once, on first use, rather than at construction, so a
        store built during composition does not read the host or the pid
        before a caller has asked it anything; the value cannot change for
        the life of the process, so caching it is a fact about the process
        rather than about the store — and it is the same
        :func:`risk.process_identity` the kill switch files its rows
        under, so one operator grep splits both tables' labels the same
        way.
        """
        if self._process_id is None:
            self._process_id = process_identity()
        return self._process_id

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    def ensure_schema(self) -> None:
        """Bring the database to the shape this ledger reads, idempotently.

        Public so a caller that reaches this store through another store's
        composition, and a test seeding an event into exactly the schema
        the store will read, can prepare the table without reaching for
        the private :meth:`_connect` — the same door :mod:`risk.kill`
        leaves open, for the same reason.  Every statement is
        ``CREATE … IF NOT EXISTS``, so a fresh database and one this
        member already prepared take the same path.
        """
        self._connect().close()

    # -- The halting process's face -------------------------------------------

    def record(
        self,
        *,
        trigger_reason: str,
        triggered_at: datetime | None = None,
        supervisor_process_id: str | None = None,
    ) -> HaltEvent:
        """Record one halt event; never overwrite, amend or drop a prior one.

        One verb, and it names the one act this feature performs: the
        event lands in the ledger, with its trigger reason and its
        timestamp, and stays there for the reconciliation this feature's
        own sentence is for.  The caller hands the reason it halted for —
        nothing else is required: ``triggered_at`` defaults to this
        instant, ``supervisor_process_id`` to *this* process's identity,
        read from the kernel rather than accepted from the caller, the
        same label and for the same reason the kill switch's send refuses
        a caller-supplied one.

        ``triggered_at`` and ``supervisor_process_id`` are keywords rather
        than defaults for the reason feature 320's ``record`` keeps its
        ``process_id`` one: a caller on the supervisor's own path should
        not pass them at all, and the one caller that *does* — an
        operator re-pronouncing a halt observed before the store was
        reachable, a replay of a recorded session — has to say so
        explicitly.  ``recorded_at`` is not a parameter at all: when the
        row was written is the ledger's own fact, and a caller that could
        set it could forge the very gap between trigger and record a
        reconciliation reads.

        **Every call writes one row.**  There is no first-write-wins here
        and no deduplication: a halt that happened twice is recorded
        twice, because completeness — not the first fact — is this
        table's law.  Returns the value that landed, carrying the number
        the ledger minted for it, so a caller logging the halt holds the
        record rather than a re-derivation of the ask.  Fails with
        :class:`~risk.errors.RiskStoreError` when the configured store
        could not take the row: a halt event that was observed and not
        persisted is exactly the hole a later reconciliation would read
        as a window where nothing halted.
        """
        reason = _require_text(trigger_reason, "trigger_reason")
        sender = (
            self.process_id
            if supervisor_process_id is None
            else _require_text(supervisor_process_id, "supervisor_process_id")
        )
        moment = _require_aware(
            datetime.now(UTC) if triggered_at is None else triggered_at,
            "triggered_at",
        )
        recorded_at = datetime.now(UTC)
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    f"""
                    INSERT INTO {RISK_HALT_EVENT_TABLE} (
                        {_COLUMNS}
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (reason, _isoformat_utc(moment), _isoformat_utc(recorded_at), sender),
                )
                sequence = cursor.lastrowid
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not record the halt event for {reason!r} from "
                f"{sender} at {_isoformat_utc(moment)}: {exc}"
            ) from exc
        if sequence is None:
            # The insert reported success and handed back no row number --
            # the one state a committed AUTOINCREMENT insert cannot be in,
            # and the one a record must never shrug past: without its
            # number the event cannot be cited, and a reconciliation
            # report would point at a row that is not addressable.
            raise RiskStoreError(
                "the halt event landed without the ledger minting it a "
                "number; an event that cannot be cited cannot be "
                "reconciled, and the ledger this feature exists for would "
                "hold a row no report can point at (feature 331)"
            )
        return HaltEvent(
            sequence=sequence,
            trigger_reason=reason,
            triggered_at=moment,
            recorded_at=recorded_at,
            supervisor_process_id=sender,
        )

    # The reconciler's face ---------------------------------------------------

    def events(self, *, since: datetime | None = None) -> tuple[HaltEvent, ...]:
        """Every halt event on record, oldest first — the reconciliation read.

        The sweep this feature's second half exists for.  Without
        ``since``, the whole ledger, in the order the halts happened;
        with it, the suffix from the anchor — the read a reconciler
        performs against feature 322's ``sent_at``, which the channel's
        own docstrings promised this feature would order against.  The
        bound is inclusive, the workspace's window convention, so an
        event triggered at exactly the anchor instant is part of the
        story the anchor begins.

        Ordering is by the trigger's own moment, with the ledger's
        sequence breaking same-instant ties in the order the events were
        recorded — a late-recorded event (``triggered_at`` in the past,
        row written since) takes its place at its own moment, not at the
        moment of the write, because the sweep answers *when did halts
        happen*, not *when did we find out*.

        **The window is a filter over the stored spelling.**  The bound
        is compared against the string the table holds, which is correct
        exactly because every row *this store* writes goes through
        :func:`_isoformat_utc` — one UTC offset, one format.  A row
        another tool wrote in another spelling may therefore sort outside
        a window it "should" fall in, and that is the safe direction:
        such a row is simply not counted, rather than being counted into
        a reconciliation on a comparison the reader cannot justify.  Rows
        that *are* inside are reconstructed through :class:`HaltEvent`'s
        own validation, so nothing survives into a reconciliation
        unparsed.

        Fails with :class:`~risk.errors.RiskStoreError` when the ledger
        could not be read, and with
        :class:`~risk.errors.RiskHaltEventError` when a stored row is not
        an event this store could have written — the refusal, not a skip:
        a skipped row is a hole wearing a shrug, and completeness is this
        table's law.
        """
        clause = ""
        parameters: list[object] = []
        if since is not None:
            clause = " WHERE triggered_at >= ?"
            parameters.append(_isoformat_utc(_require_aware(since, "since")))
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"""
                    SELECT sequence, {_COLUMNS}
                    FROM {RISK_HALT_EVENT_TABLE}{clause}
                    ORDER BY triggered_at, sequence
                    """,
                    parameters,
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not read the halt event ledger: {exc}"
            ) from exc
        return tuple(self._event_from_row(row) for row in rows)

    # -- The row plumbing ----------------------------------------------------

    @staticmethod
    def _event_from_row(row: tuple) -> HaltEvent:
        """Rebuild one stored row, refusing a value no event can be.

        The refusal is the point: this table is written by this store,
        but SQLite will accept anything another tool inserts, and a row
        wearing a moment no parser accepts, a reason that states nothing,
        or a sequence the ledger never minted would otherwise reconcile
        as a halt nobody recorded — or fail to reconcile as one somebody
        did.  The refusal names the row it came from, so an operator
        gets the row to repair rather than a complaint about a value with
        no address.
        """
        sequence, trigger_reason, triggered_at_raw, recorded_at_raw, sender = row
        moments: dict[str, datetime] = {}
        for what, raw in (
            ("triggered_at", triggered_at_raw),
            ("recorded_at", recorded_at_raw),
        ):
            try:
                moments[what] = datetime.fromisoformat(raw)
            except (TypeError, ValueError) as exc:
                raise RiskHaltEventError(
                    f"{HALT_EVENT_CODE}: the halt event row numbered "
                    f"{sequence!r} carries {what} {raw!r}, which is not an "
                    "ISO 8601 moment this store can order the sweep by "
                    "(feature 331)"
                ) from exc
        try:
            return HaltEvent(
                sequence=sequence,
                trigger_reason=trigger_reason,
                triggered_at=moments["triggered_at"],
                recorded_at=moments["recorded_at"],
                supervisor_process_id=sender,
            )
        except RiskHaltEventError as refusal:
            # The value layer validates the row, and this re-raise is what
            # makes the refusal *findable*: ``HaltEvent`` sees one row and
            # cannot know which one, while a reader holding the ledger can
            # name the number and the moments the bad row came from — so
            # an operator gets the row to repair rather than a complaint
            # about a value with no address.
            raise RiskHaltEventError(
                f"{refusal} — the row this came from is halt event "
                f"{sequence!r}, recorded by {sender!r} at "
                f"{recorded_at_raw!r} (feature 331)"
            ) from refusal


# -- The module-level spellings ---------------------------------------------------


def record_halt(
    *,
    trigger_reason: str,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    triggered_at: datetime | None = None,
    supervisor_process_id: str | None = None,
) -> HaltEvent:
    """Record one halt event, opening the ledger from the environment.

    The halting process's one call: resolve the ledger from
    ``database_url``, else from ``DATABASE_URL``, and record.  A
    deployment that names neither is refused *by name* rather than
    silently doing nothing, because a halt event that quietly skipped
    its write would leave the ledger holding a hole — and the
    reconciliation this feature's own sentence is for would read that
    hole as a moment where nothing halted, which is the one failure this
    module cannot afford (the reconciler's direction answers an empty
    tuple on the same absence; see :func:`recorded_halt_events`).

    The refusal happens before anything else, for the same reason
    :func:`risk.send_kill` resolves first: the event must land, and a
    record that goes nowhere is worse than none.  Everything after the
    resolution is :meth:`RiskHaltEventStore.record`'s, whose refusal
    vocabulary and append-only semantics this spelling inherits rather
    than restates.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise RiskHaltEventError(
            f"{HALT_EVENT_CODE}: record_halt records feature 331's halt "
            f"events and nothing names a store: {DATABASE_URL_ENV} is unset "
            "(and no database_url was supplied), so the event could not be "
            "persisted. The ledger is the record a later reconciliation "
            "sweeps — an event that silently went nowhere would leave that "
            "reconciliation reading a hole as a window where nothing halted"
        )
    return RiskHaltEventStore(url).record(
        trigger_reason=trigger_reason,
        triggered_at=triggered_at,
        supervisor_process_id=supervisor_process_id,
    )


def recorded_halt_events(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    since: datetime | None = None,
) -> tuple[HaltEvent, ...]:
    """The halt events on record — the reconciler's spelling.

    Every event the named ledger holds, oldest first, or the suffix from
    ``since`` (see :meth:`RiskHaltEventStore.events`).  A deployment that
    names no store answers an empty tuple: recording refuses without a
    store, so a deployment that names none holds no halt events to
    reconcile, and the empty answer is the truthful one — the same
    *"no store, no status"* stance :func:`risk.require_orders_allowed`
    takes, kept distinct because a caller that mistook an unconfigured
    deployment for an emptied ledger would reconcile against nothing and
    call it a clean window.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return ()
    return RiskHaltEventStore(url).events(since=since)
