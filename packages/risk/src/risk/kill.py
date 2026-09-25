"""Feature 322: the kill instruction the separate supervisor process sends.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 322: *"System runs
the risk supervisor as a separate process, which sends a kill instruction
to the order layer."*  ``docs/nullius-tech-architecture.md`` §13.3 line 717
gives the sentence its reason in one clause: *"Runs as a separate process
with kill authority over the execution engine, so a hung strategy process
cannot prevent a flatten."*  ``docs/alpha-engine-prd.md`` C10 names the
whole subject — *"Risk and kill switches"* — and §13.3's trigger table
(equity floor, daily loss, IC decay, staleness, clock skew) names the
triggers that will fire later; none of them is this feature's.

Read together, those lines say something narrower and harder than *"have a
stop button"*: **the kill must travel from one process to another through
a medium neither of them has to be alive to serve.**  An instruction held
in the supervisor's own memory dies with the supervisor; an instruction
delivered by a function call needs the order layer to be listening to the
*same* process; and an instruction delivered over a socket needs a port,
which §17 rules out flatly (*"No inbound ports on the live trading host"*)
for exactly the host this feature lives on.  So this module does the two
things the sentence's own words do, and nothing else:

* **It runs in a separate process.**  The switch is addressed by
  ``DATABASE_URL`` and constructed by whoever sends or reads — the
  supervisor process on its own path, the order layer on its own, an
  operator's sweep in a third — the same road feature 320's submission
  health store takes and for the same reason, pushed to its limit: a kill
  switch composed into an application would be a switch that application's
  lifetime bounds, and the process this feature must survive is the one
  that is hung.  Each operation opens its own connection, so the row one
  process writes is the row the next process reads, and the send and the
  guard below are proven against an actual second interpreter by the
  member's suite.
* **It sends one instruction, once.**  :meth:`RiskKillSwitch.send` is the
  supervisor's verb; :meth:`RiskKillSwitch.standing`,
  :meth:`RiskKillSwitch.killed` and :meth:`RiskKillSwitch.
  require_orders_allowed` are the order layer's reads.  The instruction is
  one row — the table's ``singleton`` primary key holds it to that at the
  storage layer, so not even a raw ``INSERT`` from another tool can mint a
  second standing kill — and it is **first-write-wins**: the first kill's
  sender and moment stay on record, and every later send (a supervisor's
  re-sweep, a restarted supervisor) writes nothing and returns the stored
  instruction with ``changed=False``.  A kill that a later send could
  move forward would quietly shrink the record of how long the order
  layer has been obliged to stop — the same aging of bad state into good
  state feature 143's halt refuses for its ``detected_at``.

**The sender's identity is on the row, and that is what makes "a separate
process" checkable.**  Every instruction carries the ``<host>/<pid>`` of
the process that sent it (:func:`process_identity`), read from the kernel
rather than accepted from the caller: a kill is a statement about *this*
supervisor, and a caller-supplied label would let the strategy process
file its own kill under the supervisor's name — the exact confusion §13.3
separates the processes to prevent.  The identity is a *label*, not an
address; nothing here dials it, for §17's reason.

**The kill is monotone, and no code clears it.**  There is no ``clear``,
no ``resume``, no ``unkill`` — in this module or in its schema — and no
path that writes the row away.  §13.3's recovery from a kill is an
operator's act (feature 323's halt door and feature 325's manual reset
will build on this channel and own their own vocabularies for it), and a
kill that code could clear would make *"has the order layer been told to
stop since T?"* unanswerable at exactly the moment feature 331's halt
event reconciliation asks it.  The reads never delete and the guard never
amends: a caller that trades without consulting the guard has not been
un-killed; it has skipped the one door this feature leaves open.

**What this module deliberately does not do.**  It does not *decide* to
kill: the triggers are features 323–329's, each with its own module and
its own repair, and a switch that also judged equity or staleness would
be five features wearing one verb.  It does not *flatten*: cancelling
open positions while the strategy process is hung is feature 330's act,
which reads this channel's standing instruction and acts on it.  It
does not *log events*: one row is the standing state, not the halt ledger
— feature 331 persists every halt event for reconciliation, and
duplicating that log here would be a second writer of a record whose
completeness that feature depends on.  And it does not *reset*: manual or
otherwise, for the monotonicity reason above.

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as this category's sibling member's tables are, and the schema is
created idempotently on connect, so no migration step is needed.  A URL
whose scheme is not ``sqlite`` is refused by name — as an *address* fault,
in :class:`~risk.errors.RiskStoreError`, the vocabulary that fault already
belongs to, rather than in this feature's own class; the split is the one
:mod:`router.submission_health` states for its own table.

**The channel's absence cuts asymmetrically, and the two directions are
split deliberately.**  :func:`send_kill` — the supervisor's spelling —
*refuses* when nothing names a store: a kill that silently went nowhere
would leave a supervisor believing it had stopped the order layer while
the order layer kept trading, which is the one failure this feature exists
to rule out.  :func:`require_orders_allowed` — the order layer's spelling
— *passes vacuously* when nothing names a store: a deployment with no
relational store has no supervisor channel, so no kill was ever sent
through one, and there is no standing instruction to refuse on — the same
*"no store, no status"* stance :func:`canary.require_dreaming_allowed`
takes, kept distinct because a caller that mistook an unconfigured
deployment for a checked one would trade believing the supervisor had
run.
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
from .errors import (
    KILL_INSTRUCTION_CODE,
    ORDERS_KILLED_CODE,
    RiskKillSwitchError,
    RiskOrdersKilledError,
    RiskStoreError,
)

__all__ = [
    "DATABASE_URL_ENV",
    "KILL_INSTRUCTION",
    "RISK_ORDER_KILL_TABLE",
    "KillInstruction",
    "RiskKillSwitch",
    "orders_killed_error",
    "require_orders_allowed",
    "send_kill",
]

#: The workspace-wide environment variable naming the relational store —
#: the one spelling every store in this workspace already uses, restated
#: here so this module states its own contract and imports no sibling's.
DATABASE_URL_ENV = "DATABASE_URL"

#: This member's own table — the *one* row that is the standing kill
#: instruction, the state every submission path asks about.  It is not a
#: column on another member's table and not a row per trigger: the
#: instruction feature 322's sentence names is addressed to the order
#: layer as a whole, and a table per trigger would be five features
#: sharing one verb this module refused to give them.  The halt *events*
#: feature 331 will persist are a different table in a different module.
RISK_ORDER_KILL_TABLE = "risk_order_kill"

#: The one instruction this channel carries, as the greppable token the
#: row stores and the value layer refuses to widen: app_spec.xml feature
#: 322 names exactly one instruction — *a kill instruction* — and a row
#: wearing any other word would be a row no reader of ``kill`` could
#: find, the same stance feature 143's ``DETERMINISM_BROKEN`` takes for
#: the one alert it emits.  Feature 323's halt will arrive as its own
#: door reading this channel, not as a second word in this column.
KILL_INSTRUCTION = "kill"

#: ``risk_order_kill``'s DDL, created idempotently beside the code that
#: reads it — the same member-owned-table stance :mod:`canary._halt` takes
#: for ``canary_dream_halt``, and deliberately *not* a migration: this
#: table has exactly one writer and one reader, both in this module.
#:
#: The ``singleton`` primary key is the one-row law stated where neither
#: this module's discipline nor a reviewer's attention has to hold it: the
#: kill instruction is a *state*, not a log, and a second row — from a
#: racing supervisor, a looping restart, or a raw ``INSERT`` at a sqlite3
#: prompt — would leave two standing kills for the order layer to
#: arbitrate.  ``CHECK (singleton = 0)`` pins the value as well as the
#: count, so the table cannot grow a second *kind* of row either.  The
#: ``instruction`` column is checked against the one token for the same
#: reason the outcome vocabulary of feature 320's table is: the table and
#: the value layer cannot drift apart if the schema itself refuses to.
_SCHEMA = f"""
-- Feature 322: the standing kill instruction, sent by the separate risk
-- supervisor process to the order layer.  Exactly one row, ever: the first
-- kill's sender and moment are the fact on record, and every later send
-- writes nothing (first-write-wins, like feature 143's halt rows).
--
-- `supervisor_process_id` is the sending process's <host>/<pid>, read from
-- the kernel by risk._identity.process_identity and never accepted from
-- the caller -- the label that makes "a separate process" a checkable fact
-- rather than a deployment assertion.  `sent_at` is ISO 8601 UTC, the
-- moment the order layer first became obliged to stop.
CREATE TABLE IF NOT EXISTS {RISK_ORDER_KILL_TABLE} (
    singleton              INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 0),
    instruction            TEXT NOT NULL CHECK (instruction = 'kill'),
    supervisor_process_id  TEXT NOT NULL,
    sent_at                TEXT NOT NULL
);
"""

#: The columns of :data:`RISK_ORDER_KILL_TABLE`, in the order the read
#: names them and the order the reconstruction unpacks them.  Spelled once
#: so the write and the read cannot drift apart on a column order — the
#: failure a positional ``SELECT *`` invites.  The ``singleton`` key is
#: deliberately absent: it names the one-row law, not the instruction.
_COLUMNS = "instruction, supervisor_process_id, sent_at"


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :mod:`router.submission_health` and every other
    store in this workspace states, in this module's own words, for the
    reason each of them restates it: a store reaches into no sibling's
    private helper, so a later change to one table's address handling
    cannot silently move another's.  ``sqlite:///foo.db`` is relative,
    ``sqlite:////foo.db`` is absolute, and any other scheme is refused by
    name.

    Raises :class:`~risk.errors.RiskStoreError`, **not** this feature's
    own class: an address this member cannot speak is an *address* fault
    with an address repair — point the deployment at a database this store
    can open — which is the face :class:`~risk.errors.RiskStoreError`
    exists for.  The member keeps one vocabulary for one fault, and this
    feature's own class is reserved for the faults whose noun is the kill
    instruction itself (see :mod:`risk.errors`).
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RiskStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "kill switch speaks sqlite:/// (the spec's single-machine "
            f"allowance); point {DATABASE_URL_ENV} at the sqlite database "
            "the supervisor's kill instruction is sent through (feature 322)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 322)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a kill instruction that vanished would leave the order "
            "layer trading under a supervisor that believed it had killed "
            "it (feature 322)"
        )
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    Every row this switch writes goes through here — one UTC offset, one
    format, one width — and the read path parses what
    :func:`datetime.fromisoformat` accepts and refuses the rest, so a row
    another tool wrote in another spelling never survives into a standing
    instruction unparsed.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* the kill was sent,
    and an instruction whose moment cannot be ordered cannot anchor the
    window feature 331's reconciliation will sweep — the same discipline
    feature 310's and feature 320's stores hold their callers to, and the
    reason it is checked here rather than assumed.
    """
    if not isinstance(moment, datetime):
        raise RiskKillSwitchError(
            f"{KILL_INSTRUCTION_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__} (feature 322)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RiskKillSwitchError(
            f"{KILL_INSTRUCTION_CODE}: {what} must be timezone-aware; a "
            "kill instruction must say unambiguously when it was sent, or "
            "the order layer cannot order its obligation against anything "
            "(feature 322)"
        )
    return moment


def _require_text(value: object, what: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    The sender's identity is a *name*, and a name that states nothing
    names no process to attribute the kill to — the near-miss rule the
    workspace's id validations take toward a label with a trailing
    newline, which would be a second identity against a row keyed by the
    first.
    """
    if not isinstance(value, str) or not value.strip():
        raise RiskKillSwitchError(
            f"{KILL_INSTRUCTION_CODE}: {what} must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); a kill instruction that "
            "cannot be attributed to the process that sent it is not "
            "auditable, and feature 331's reconciliation asks exactly that "
            "question (feature 322)"
        )
    return value.strip()


# -- The record -----------------------------------------------------------------


@dataclass(frozen=True)
class KillInstruction:
    """One kill instruction: what was sent, by whom, when.

    A *value* — frozen, self-describing — carrying the whole of feature
    322's second clause: the order layer was sent ``kill`` by
    ``supervisor_process_id`` at ``sent_at``, and that instruction stands
    until the features that own a reset add one.  It is what
    :meth:`RiskKillSwitch.send` writes and returns, what the raised
    :class:`~risk.errors.RiskOrdersKilledError` carries on its
    ``instruction`` attribute, and what :meth:`RiskKillSwitch.standing`
    reads back — one type for all three, so the record an operator pages
    on and the row the switch holds cannot be two things that disagree.

    Validated in :meth:`__post_init__` rather than only where it is built,
    because the read path reconstructs one from a stored row: a row edited
    outside this package — an ``instruction`` wearing a word this feature
    never sends, a sender that names no process, a moment no parser
    accepts — fails to reconstruct rather than loading as a
    plausible-looking kill, the same defence :class:`canary.DreamHalt`
    applies to its own arithmetic, and for the same reason: what the order
    layer refuses under is the stored record, and a switch that could hand
    back an instruction disagreeing with its own row would launder a
    tamper into a stop nobody sent.

    ``changed`` answers the question a re-send asks — whether *this* call
    wrote the row.  The first kill writes it (``True``); a later send —
    the same supervisor sweeping again, a restarted supervisor — finds it
    already held and reports ``False`` while the stored record, the
    *first* kill, is the one returned.  The distinction is the one
    feature 143's halt takes for its own one-shot write: a re-sent kill
    must not read as a new one.
    """

    #: The instruction itself.  Always :data:`KILL_INSTRUCTION`; carried on
    #: the record so a reader dispatching on the word reads it from the
    #: thing itself, and so a stored row wearing any other word fails to
    #: reconstruct.
    instruction: str
    #: The identity of the process that sent the kill (see
    #: :func:`risk.process_identity`) — never the order layer's, never the
    #: venue's, and never accepted from an unlabelled default.
    supervisor_process_id: str
    #: When the supervisor sent the kill, timezone-aware.  The moment the
    #: order layer's obligation began, and the datum feature 331's halt
    #: event reconciliation will order against.
    sent_at: datetime
    #: Whether the call that produced this record wrote the row.  ``False``
    #: on a read-back and on a re-send that found the kill already
    #: standing.
    changed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.instruction, str) or self.instruction != KILL_INSTRUCTION:
            raise RiskKillSwitchError(
                f"{KILL_INSTRUCTION_CODE}: a kill instruction's word is the "
                f"one this channel sends, {KILL_INSTRUCTION!r}, got "
                f"{self.instruction!r}; the feature names exactly one "
                "instruction, and a record carrying any other word is a "
                "row no reader of 'kill' could find (feature 322)"
            )
        object.__setattr__(
            self,
            "supervisor_process_id",
            _require_text(self.supervisor_process_id, "supervisor_process_id"),
        )
        _require_aware(self.sent_at, "sent_at")
        if isinstance(self.changed, bool) is False:
            raise RiskKillSwitchError(
                f"{KILL_INSTRUCTION_CODE}: changed must be a bool, got "
                f"{self.changed!r} ({type(self.changed).__name__}); whether "
                "this call wrote the row is one bit, and a truthy-looking "
                "non-bool is the value that would silently misreport a "
                "re-sent kill as a first one (feature 322)"
            )

    @property
    def summary(self) -> str:
        """One sentence: which process sent the kill, and when.

        Composed rather than stored, because every part of it is already a
        field — a stored copy would be a second place for the record's own
        facts to live, and an edited row would then disagree with its own
        summary.  The identity is spelled in full and the moment in the
        table's own ISO form, so an operator reading a log line can grep
        the supervisor's process and join feature 331's halt events to
        this instruction without a second query.
        """
        return (
            f"the order layer was sent {self.instruction!r} by "
            f"{self.supervisor_process_id} at {_isoformat_utc(self.sent_at)}"
        )


# -- The refusal ----------------------------------------------------------------


def orders_killed_error(instruction: KillInstruction) -> RiskOrdersKilledError:
    """Build the order layer's refusal from its record — the one spelling.

    The refusal's message is composed from the instruction's own fields,
    so the page an operator reads and the row the switch holds say the
    same thing — the same reason :func:`canary.determinism_broken_error`
    exists rather than letting every caller compose its own message.  The
    consequence is stated in the operator's terms (orders are refused
    until the door that owns a reset opens one), because the reader is
    deciding what to do at three in the morning.
    """
    if not isinstance(instruction, KillInstruction):
        raise RiskKillSwitchError(
            f"{KILL_INSTRUCTION_CODE}: orders_killed_error takes a "
            "KillInstruction — the record of the standing kill — got "
            f"{instruction!r}; the refusal's message is composed from the "
            "record's own fields, and an error built from anything else "
            "would be a refusal with no instruction behind it (feature 322)"
        )
    return RiskOrdersKilledError(
        f"{ORDERS_KILLED_CODE}: {instruction.summary}; orders are refused "
        "until the door that owns a reset (feature 323's halt, 325's "
        "manual reset) opens one — this channel sends, it does not clear",
        instruction,
    )


# -- The switch -----------------------------------------------------------------


class RiskKillSwitch:
    """Sends and reads the one standing kill instruction.

    Bound to a database URL at construction; construction performs no I/O,
    so composing an application never touches the database and a switch
    costs nothing until an instruction is sent or read.  Each operation
    opens its own connection (creating the schema idempotently if absent),
    the discipline every store in this workspace follows — which is what
    makes the instruction readable from a *different* process than the one
    that sent it: the database, not any process's memory, is the
    coordination point, and §17 leaves no other channel to try.

    Two faces, one object: the supervisor process calls :meth:`send`; the
    order layer calls :meth:`standing`, :meth:`killed` and
    :meth:`require_orders_allowed`.  Neither face holds state of its own
    beyond the URL and this process's identity, so a restarted anything
    reconstructs the same standing instruction as the process it replaced.
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
    ) -> RiskKillSwitch | None:
        """The switch ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — absent is a
        discoverable deployment state, not an exception, the stance every
        store in this workspace takes.  What a caller does with the
        ``None`` is the caller's direction to decide, and the two
        directions this channel cuts are deliberately split in this
        module: :func:`send_kill` refuses on it, :func:
        `require_orders_allowed` passes vacuously on it (see the module
        docstring for why the asymmetry is the feature, not an accident).
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this switch sends and reads through."""
        return self._database_url

    @property
    def process_id(self) -> str:
        """This process's identity — the label its kill rows are filed under.

        Resolved once, on first use, rather than at construction, so a
        switch built during composition does not read the host or the pid
        before a caller has asked it anything; the value cannot change for
        the life of the process, so caching it is a fact about the process
        rather than about the switch.
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
        """Bring the database to the shape this switch reads, idempotently.

        Public so a caller that reaches this switch through another
        store's composition, and a test seeding a kill into exactly the
        schema the switch will read, can prepare the table without
        reaching for the private :meth:`_connect` — the same door
        :class:`canary.CanaryHaltStore` leaves open, for the same reason.
        Every statement is ``CREATE TABLE IF NOT EXISTS``, so a fresh
        database and one this member already prepared take the same path.
        """
        self._connect().close()

    # -- The supervisor's face ------------------------------------------------

    def send(
        self,
        *,
        sent_at: datetime | None = None,
        supervisor_process_id: str | None = None,
    ) -> KillInstruction:
        """Send the kill instruction to the order layer; never un-send it.

        One verb, and it names the one act this feature performs: the
        instruction lands in the channel, and the order layer that reads
        the switch is refused from that moment on.  The caller hands
        nothing but the ask — ``sent_at`` defaults to this instant and
        ``supervisor_process_id`` to *this* process's identity, read from
        the kernel rather than accepted from the caller, because a label a
        deployment could set is a label the strategy process could borrow.

        ``supervisor_process_id`` is a keyword rather than the default
        spelling for the same reason feature 320's ``record`` keeps its
        ``process_id`` one: a caller on the supervisor's own path should
        not pass it at all, and the one caller that *does* — a replay of
        a recorded kill, an operator re-pronouncing a kill under the
        identity that first sent it — has to say so explicitly.

        **First-write-wins, and the first kill is the fact on record.**
        The table holds one row (its ``singleton`` key is the one-row law
        at the storage layer), so a send over an already-killed channel
        writes nothing and returns the stored instruction with
        ``changed=False``: the first kill's sender and moment are what the
        order layer was obliged by and what feature 331 will reconcile
        against, and a later send that moved them would quietly shrink
        the record of how long the order layer has been killed.  The
        one-statement ``INSERT OR IGNORE`` is also the race answer: two
        supervisors sending concurrently both succeed, the row's first
        writer is the supervisor on record, and the loser reads the
        winner's instruction back as the standing one.

        Returns the value that stands — the stored first kill, not the
        ask — so a caller logging the send holds the record rather than a
        re-derivation of it.  Fails with
        :class:`~risk.errors.RiskStoreError` when the configured channel
        could not take the row: an instruction that was sent and not
        persisted is exactly the gap between a supervisor that believes
        it has killed the order layer and an order layer still trading.
        """
        sender = (
            self.process_id
            if supervisor_process_id is None
            else _require_text(supervisor_process_id, "supervisor_process_id")
        )
        moment = _require_aware(
            datetime.now(UTC) if sent_at is None else sent_at, "sent_at"
        )
        candidate = KillInstruction(
            instruction=KILL_INSTRUCTION,
            supervisor_process_id=sender,
            sent_at=moment,
            changed=True,
        )
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    f"""
                    INSERT OR IGNORE INTO {RISK_ORDER_KILL_TABLE} (
                        singleton, instruction, supervisor_process_id, sent_at
                    ) VALUES (0, ?, ?, ?)
                    """,
                    (
                        candidate.instruction,
                        candidate.supervisor_process_id,
                        _isoformat_utc(candidate.sent_at),
                    ),
                )
                changed = cursor.rowcount == 1
                row = self._read_row(connection)
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not send the kill instruction from "
                f"{candidate.supervisor_process_id} at "
                f"{_isoformat_utc(candidate.sent_at)}: {exc}"
            ) from exc
        if row is None:
            # The write reported success and the read inside the same
            # transaction found nothing -- the one state that cannot be
            # true of a committed INSERT, and the one a send must never
            # shrug into a quiet return: the kill did not land.
            raise RiskStoreError(
                "the kill instruction vanished inside its own write; a "
                "kill that cannot be read back has not been sent, and the "
                "order layer this send was about to stop is still trading "
                "(feature 322)"
            )
        return self._instruction_from_row(row, changed=changed)

    # -- The order layer's face -------------------------------------------------

    def standing(self) -> KillInstruction | None:
        """The instruction in force, or ``None`` when the channel holds none.

        The order layer's primary read: *has the supervisor sent a kill?*
        ``None`` means no instruction stands — the channel is empty, not
        unread — and is deliberately not a default or a zeroed
        instruction, because a deployment with no supervisor running and a
        deployment whose supervisor sent a kill are different facts, the
        same distinction feature 320's three-valued health verdict keeps.

        The row is reconstructed through :class:`KillInstruction`'s own
        validation, so a row edited outside this package fails to
        reconstruct rather than loading as a plausible-looking kill — the
        defence the record's own docstring states, and the reason a
        tampered table refuses to stop the order layer under a kill
        nobody sent.  ``changed`` is ``False`` on every read-back; the bit
        names the call that wrote the row, and a read wrote nothing.
        """
        try:
            with closing(self._connect()) as connection:
                row = self._read_row(connection)
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not read the standing kill instruction: {exc}"
            ) from exc
        if row is None:
            return None
        return self._instruction_from_row(row, changed=False)

    def killed(self) -> bool:
        """Whether a kill instruction stands — the state, as one bit.

        ``True`` when any instruction is on record, which by the one-row
        law is at most one.  The kill is monotone — nothing in this module
        writes the row away — so once ``True`` it stays ``True`` until the
        door that owns a reset (feature 323's halt, 325's manual reset)
        opens one, in its own module, over its own vocabulary.
        """
        return self.standing() is not None

    def require_orders_allowed(self) -> None:
        """The guard: pass while no kill stands, refuse when one does.

        The read-time refusal the order layer's submission path consults —
        the same shape :meth:`canary.CanaryHaltStore.require_dreaming_allowed`
        gives the dreaming cycle: the row is never deleted from, and the
        refusal is derived from it, so the kill holds no matter which
        supervisor process set it.  When an instruction stands this raises
        :class:`~risk.errors.RiskOrdersKilledError` carrying it, so the
        caller that reaches for an order learns *which* process killed the
        order layer and *when* — the two questions an operator asks first.
        A caller that submits without asking has not been un-killed; it
        has skipped the one door this feature leaves open.
        """
        instruction = self.standing()
        if instruction is not None:
            raise orders_killed_error(instruction)

    # -- The row plumbing ----------------------------------------------------

    @staticmethod
    def _read_row(connection: sqlite3.Connection) -> tuple | None:
        """The standing row, or ``None`` when the channel is empty.

        No ``ORDER BY`` is needed and none is stated: the one-row law in
        the schema makes the question *which row* unaskable, which is the
        whole point of stating that law in the table rather than in this
        module's discipline.
        """
        cursor = connection.execute(
            f"SELECT {_COLUMNS} FROM {RISK_ORDER_KILL_TABLE}"
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    @staticmethod
    def _instruction_from_row(row: tuple, *, changed: bool) -> KillInstruction:
        """Rebuild one stored row, refusing a value no instruction can be.

        The refusal is the point: this table is written by this switch,
        but SQLite will accept anything another tool inserts, and a row
        wearing a word other than ``kill``, a sender that names no
        process, or a moment no parser accepts would otherwise stand as a
        kill nobody sent — or fail to stand as one somebody did.  The
        refusal names the row it came from, so an operator gets the row to
        repair rather than a complaint about a value with no address.
        """
        instruction, supervisor_process_id, sent_at_raw = row
        try:
            sent_at = datetime.fromisoformat(sent_at_raw)
        except (TypeError, ValueError) as exc:
            raise RiskKillSwitchError(
                f"{KILL_INSTRUCTION_CODE}: the kill row filed under "
                f"{supervisor_process_id!r} carries {sent_at_raw!r}, which "
                "is not an ISO 8601 moment this switch can order the "
                "instruction by (feature 322)"
            ) from exc
        try:
            return KillInstruction(
                instruction=instruction,
                supervisor_process_id=supervisor_process_id,
                sent_at=sent_at,
                changed=changed,
            )
        except RiskKillSwitchError as refusal:
            # The value layer validates the row, and this re-raise is what
            # makes the refusal *findable*: ``KillInstruction`` sees one
            # row and cannot know which one, while a reader holding the
            # switch can name the sender and the moment the bad row came
            # from -- so an operator gets the row to repair rather than a
            # complaint about a value with no address.
            raise RiskKillSwitchError(
                f"{refusal} — the row this came from is the kill filed "
                f"under {supervisor_process_id!r} at {sent_at_raw!r} "
                "(feature 322)"
            ) from refusal


# -- The module-level spellings --------------------------------------------------


def send_kill(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    sent_at: datetime | None = None,
    supervisor_process_id: str | None = None,
) -> KillInstruction:
    """Send the kill instruction, opening the switch from the environment.

    The supervisor process's one call: resolve the channel from
    ``database_url``, else from ``DATABASE_URL``, and send.  A deployment
    that names neither is refused *by name* rather than silently doing
    nothing, because a kill that quietly skipped its write would leave the
    supervisor believing it had stopped the order layer while the order
    layer kept trading — which is the failure mode this whole feature
    exists to rule out, and the one direction of the channel's absence
    that must not fail softly (the order layer's direction passes
    vacuously; see :func:`require_orders_allowed`).

    The refusal happens before anything else, for the same reason
    :func:`canary.halt_dreaming` resolves first: the kill must land, and a
    break that goes nowhere is worse than none.  Everything after the
    resolution is :meth:`RiskKillSwitch.send`'s, whose refusal vocabulary
    and first-write-wins semantics this spelling inherits rather than
    restates.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise RiskKillSwitchError(
            f"{KILL_INSTRUCTION_CODE}: send_kill sends feature 322's kill "
            f"instruction and nothing names a channel: {DATABASE_URL_ENV} "
            "is unset (and no database_url was supplied), so the "
            "instruction could not be sent. The kill is a state that must "
            "reach the order layer's process — a send that silently went "
            "nowhere would leave the order layer trading under a "
            "supervisor that believed it had killed it"
        )
    return RiskKillSwitch(url).send(
        sent_at=sent_at, supervisor_process_id=supervisor_process_id
    )


def require_orders_allowed(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """The guard, opening its own switch — the order layer's spelling.

    Passes while no kill instruction stands and raises
    :class:`~risk.errors.RiskOrdersKilledError` carrying the standing one
    when it does (see :meth:`RiskKillSwitch.require_orders_allowed`).  A
    deployment that names no store passes vacuously: with no relational
    store there is no channel, so no supervisor ever sent a kill through
    one, and there is no standing instruction to refuse on — the same
    *"no store, no status"* answer :func:`canary.require_dreaming_allowed`
    gives, kept distinct because a caller that mistook an unconfigured
    deployment for a checked one would trade believing a supervisor had
    been running.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return
    RiskKillSwitch(url).require_orders_allowed()
