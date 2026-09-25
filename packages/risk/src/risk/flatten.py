"""Feature 330: the flatten that survives a hung strategy process.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 330: *"System
flattens successfully even when the strategy process is hung, which
returns a completed flatten result."*  ``docs/nullius-tech-architecture.md``
§13.3 line 717 gives the sentence its whole reason in one clause: *"Runs
as a separate process with kill authority over the execution engine, so
a hung strategy process cannot prevent a flatten."*  The trigger table
directly below that line names the halts whose action is a flatten —
*"Daily loss limit breached | Flatten, halt until manual reset"* — and
``docs/alpha-engine-prd.md`` line 474 says the same word for the same
trigger; the trigger is feature 325's to fire, not this feature's.
``app_spec.xml`` feature 370 promises the end-to-end form of exactly
this sentence — a daily loss breach driving the supervisor to flatten
*while the strategy process is unresponsive*, returning a completed
flatten — and it is against this module's verb that that journey will be
written.

Read together, the sentence makes three claims, and each is a law here:

* **It flattens.**  :meth:`RiskFlattener.flatten` drives the execution
  engine's own verbs — enumerate the orders standing, cancel each one,
  enumerate the positions open, close each one — in the supervisor's
  process, one item at a time, so the supervisor keeps authority over
  every cancellation it orders.  The face is duck-typed and
  caller-supplied, and its verbs are named for the operations the
  router member already prices (:data:`router.limiter.OPERATION_OPEN_ORDERS`,
  :data:`router.limiter.OPERATION_CANCEL_ORDER`): the flatten is the
  supervisor's own hold on the engine, §13.3's *"kill authority over
  the execution engine"*, and this module imports nothing to exercise
  it — an instruction that travelled by importing its addressee would
  be a function call, and a function call needs the addressee's process
  to be listening.
* **Even when the strategy process is hung.**  Nothing in the flatten's
  path is served by the strategy process: not the authority (the
  standing kill is read from the channel through this flattener's own
  switch), not the enumeration, not the act.  And the claim cuts deeper
  than control flow — **the flatten performs no store write at all.**
  The one thing a hung process *can* wedge, from outside this module,
  is the shared store's write lock: a strategy process that hung
  mid-write holds it indefinitely, and every writer behind it refuses
  with *database is locked*.  A flatten that had to persist its result
  before answering would therefore be a flatten a hung strategy process
  could prevent — the exact failure §13.3 separates the processes to
  rule out.  So the flatten's only store touch is the *read* of the
  channel, and committed state is exactly what a reader still sees
  under a hung writer's lock; the completed result is returned, not
  written, and the record — if anyone wants one — is feature 331's
  ledger, written by the door that fired the halt, never by this module
  (a second writer of that record would be a second thing to wedge, and
  a second writer is what the ledger's completeness refuses).  There is
  no ``risk_flatten`` table for the same reason there is no
  :meth:`ensure_schema` on :class:`RiskFlattener`: the absence is the
  feature, stated in the object graph.  One honest ordering note: the
  kill *send* is a write — 322's own act — so the channel is killed
  before the strategy process wedges the store, which is also the only
  order the deployment runs in: the supervisor kills, the strategy
  process stops cooperating, the supervisor flattens.
* **It returns a completed flatten result.**  *Completed* is derived,
  never asserted: after the flatten has driven every order and position
  it was shown, it asks the engine again, and only an engine whose own
  re-reading reports **nothing standing** yields a result.  The value
  layer finishes the law — :class:`FlattenResult` refuses to construct
  in any status other than :data:`FLATTEN_STATUS_COMPLETED`, the one
  word, exactly as :class:`~risk.kill.KillInstruction` refuses any word
  but ``kill`` — so a completed flatten result is not a status a caller
  can hand back optimistically; the type cannot exist unless the engine
  said flat.  A residue, a fault, or an engine that cannot be asked
  raises :class:`~risk.errors.RiskFlattenError` naming what still
  stands, and the recovery is the refusal's own protocol: flatten
  again, and the next sweep's enumeration of the engine is the
  truthful picture of what remains.

**The flatten acts under the channel's standing kill, and only under
one.**  :mod:`risk.kill` promised this module would arrive and read its
instruction; it does, through the same :class:`~risk.kill.RiskKillSwitch`
over the same ``DATABASE_URL`` anyone else constructs, so the authority
the flatten cites and the row the channel holds cannot be two things
that disagree.  A flatten with no kill standing is refused: the kill
stops the source and the flatten drains the sink, and draining a sink
while the tap runs is not a flatten but a race the book loses.  The
kill is monotone — no code clears it — so an instruction read standing
at the start of a flatten stands for its whole duration; there is no
window in which the authority is withdrawn mid-drive, and the result
carries the instruction it acted under, first-write-wins, so a
restarted supervisor flattening under the first supervisor's kill says
so on the record it returns.

**The drive is best-effort; the completion is not.**  A cancellation or
close that raises does not abort the sweep — every other item is still
driven, because a flatten that stopped at its first fault would leave
the residue unattempted — but a single fault is enough to refuse the
result, however clean the re-reading looks, because the engine's
receipts are not the judge and a result that hid a thrown one would
disagree with its own run.  (A cancel that raises *"unknown order"*
because the order filled in the moment between enumeration and the
drive is still a fault on the record: the fill opened or moved a
position, the position half of the sweep ran after the order half
precisely so that such fills are seen, and the caller that re-flattens
completes over whatever the fill left.)  An engine that reports one
id twice is answered once: the duplicate is not re-driven, because a
second ask for one act is not a second act, and the residue re-reading
judges the outcome either way.

**What this module deliberately does not do.**  It does not *decide* to
flatten: the triggers are features 323–329's, each with its own module
and its own repair.  It does not *halt* or *door*: POST /risk/halt is
feature 323's, and that door will send the kill and call this verb in
order.  It does not *record*: feature 331's ledger is the record, the
halting process is its writer, and this module's no-write law would be
broken by the first convenience row.  It does not *reset*: the kill it
reads under is monotone, and the features that own recovery (325's
manual reset) open their own doors over their own vocabularies.  And it
does not *serve anything*: the flatten has exactly one direction — the
supervisor's — so where the channel's absence splits (the sender
refuses, the guard passes vacuously), this module's absence does not:
:func:`flatten_positions` refuses when nothing names a store, because a
flatten that silently skipped its authority check would return a
completed result no kill ever authorised.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from ._identity import process_identity
from .errors import FLATTEN_CODE, RiskFlattenError, RiskStoreError
from .kill import KillInstruction, RiskKillSwitch

__all__ = [
    "DATABASE_URL_ENV",
    "FLATTEN_STATUS_COMPLETED",
    "FlattenResult",
    "RiskFlattener",
    "flatten_positions",
]

#: The workspace-wide environment variable naming the relational store —
#: restated here for the same reason every module in this member restates
#: it: each states its own contract and imports no sibling's spelling.
DATABASE_URL_ENV = "DATABASE_URL"

#: The one status a flatten result can wear, as the greppable token the
#: spec's own sentence names — *"which returns a completed flatten
#: result"* — and the only word :class:`FlattenResult`'s value layer
#: accepts.  A flatten that did not complete does not return a result
#: wearing a lesser word; it raises, so a caller holding a
#: :class:`FlattenResult` holds a fact the engine itself confirmed, and
#: no caller can construct one that says otherwise.
FLATTEN_STATUS_COMPLETED = "completed"

#: The four verbs the execution engine face must carry, in the order the
#: flatten drives them.  ``open_orders`` and ``cancel_order`` are named
#: for the operations the router member already prices for the venue;
#: ``open_positions`` and ``close_position`` continue the pair for the
#: exposure half of a flatten, which no workspace member has vocabulary
#: for yet and this one therefore states for itself.  Private because the
#: contract is stated in the refusal that names a missing verb, and a
#: test that pinned the names by import would measure a copy of the list
#: rather than the face the flatten actually drives.
_FACE_VERBS = ("open_orders", "cancel_order", "open_positions", "close_position")


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the member's one canonical spelling.

    The same form the channel and the ledger store, restated here so this
    module's summary composes with the instants its record already holds
    rather than deriving a second spelling from a sibling's helper.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    The same discipline the channel holds ``sent_at`` and the ledger holds
    ``triggered_at`` to, for this module's own reason: a flatten whose
    moment states no time cannot be ordered against the kill it acted
    under, and that ordering is the audit an operator performs first.
    """
    if not isinstance(moment, datetime):
        raise RiskFlattenError(
            f"{FLATTEN_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__} (feature 330)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RiskFlattenError(
            f"{FLATTEN_CODE}: {what} must be timezone-aware; a flatten that "
            "cannot say when it completed cannot be ordered against the kill "
            "it acted under (feature 330)"
        )
    return moment


def _require_text(value: object, what: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    For the supervisor's own label — the one field this module accepts as
    a name rather than an engine report — the near-miss rule the whole
    workspace holds: a label that states nothing names no process to
    attribute the flatten to, and the record feature 331's reconciliation
    joins on is the identity.
    """
    if not isinstance(value, str) or not value.strip():
        raise RiskFlattenError(
            f"{FLATTEN_CODE}: {what} must be non-empty text, got {value!r} "
            f"({type(value).__name__}); a flatten that cannot be attributed "
            "to the process that drove it is unauditable at exactly the "
            "moment an operator asks who flattened the book (feature 330)"
        )
    return value.strip()


def _require_names(value: object, what: str) -> tuple[str, ...]:
    """Return ``value`` as a tuple of names that each state something.

    For the result's two work records — the orders cancelled, the
    positions closed — carried as given (engine ids are exact strings the
    engine must recognise again, so nothing is stripped or laundered) and
    refused when one states nothing: a record of work that names nothing
    is a completed result over an unnamed residue.  A bare string is
    refused as a container, not iterated into characters, because one
    undivided id wearing the plural of a work record is the near-miss a
    positional caller would hit first.
    """
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise RiskFlattenError(
            f"{FLATTEN_CODE}: {what} must be an iterable of names, got "
            f"{value!r} ({type(value).__name__}); the completed result "
            "records the work the flatten drove, item by item, and a value "
            "that is not the items is not that record (feature 330)"
        )
    names = tuple(value)
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise RiskFlattenError(
                f"{FLATTEN_CODE}: {what} carries {name!r} "
                f"({type(name).__name__}), which names nothing; a completed "
                "flatten result cannot record work it cannot name, or the "
                "engine's residue and the record's work would be two lists "
                "that disagree (feature 330)"
            )
    return names


def _once_each(names: list[str]) -> list[str]:
    """The names in the order given, each once.

    An engine that reports one id twice is asking twice for one act; the
    first drive is the act and the duplicate is not re-driven, because a
    second cancellation of an already-cancelled order is a second receipt
    for one fact — and the residue re-reading judges the outcome either
    way, which is why this is a convenience of the drive and not a law of
    it.
    """
    seen: set[str] = set()
    driven: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            driven.append(name)
    return driven


def _require_face(execution_engine: object) -> None:
    """Refuse a face the flatten cannot drive, naming every missing verb.

    The face is duck-typed — this module imports no engine, §13.3's whole
    point — so the contract is enforced where it is used: the four verbs
    the flatten drives must each be callable on the object handed in, and
    a face missing any of them is refused with the full list, because the
    operator's repair is one face to fix and one refusal naming all of
    its gaps beats four refusals arriving one sweep apart.  ``None`` and
    objects that are not faces at all land here too, by the same
    ``getattr`` road: the refusal names the verbs, not the type, because
    the type was never this module's business.
    """
    missing = [
        verb for verb in _FACE_VERBS if not callable(getattr(execution_engine, verb, None))
    ]
    if missing:
        raise RiskFlattenError(
            f"{FLATTEN_CODE}: the execution engine face is missing its "
            f"verbs {missing}; the flatten drives the engine itself — "
            "open_orders() and open_positions() to ask what stands, "
            "cancel_order() and close_position() to end it — and a face "
            "that cannot be asked cannot be ordered flat (feature 330)"
        )


def _enumerate(execution_engine: object, verb: str) -> list[str]:
    """Ask one face verb what stands, and refuse an answer that is not names.

    The enumeration is the flatten's eyes — both the work list and, on
    the second asking, the completion check — so an enumeration that
    raises is wrapped and named (the caller must know which ask failed),
    and an answer that is not a list of names that each state something
    is refused rather than coerced: the ids are driven back into the
    engine exactly as reported, so a laundered or skipped report would
    cancel nothing while claiming the sweep saw it.
    """
    try:
        reported = list(getattr(execution_engine, verb)())
    except Exception as exc:
        raise RiskFlattenError(
            f"{FLATTEN_CODE}: the execution engine's {verb}() could not be "
            f"asked what stands: {exc!r}; the flatten judges completion by "
            "the engine's own answer, and an enumeration that cannot be "
            "read is a face whose state cannot be known — the one "
            "condition a completed result must never be returned over "
            "(feature 330)"
        ) from exc
    for name in reported:
        if not isinstance(name, str) or not name.strip():
            raise RiskFlattenError(
                f"{FLATTEN_CODE}: {verb}() reported {name!r} "
                f"({type(name).__name__}), which names nothing; an order id "
                "or a position symbol that states nothing cannot be driven "
                "to cancellation, and a sweep that skipped it would return "
                "a completed result over an exposure it was shown "
                "(feature 330)"
            )
    return reported


# -- The record -----------------------------------------------------------------


@dataclass(frozen=True)
class FlattenResult:
    """One completed flatten: what was driven, under whose authority.

    A *value* — frozen, self-describing — carrying the whole of feature
    330's second clause: the flatten drove ``cancelled_orders`` and
    ``closed_positions`` to nothing standing, acting under ``instruction``
    (the standing kill feature 322's channel held, first-write-wins),
    from ``supervisor_process_id``, and it was complete at
    ``flattened_at``.  It is what :meth:`RiskFlattener.flatten` returns
    and the only thing that call returns — there is no incomplete
    variant of this type to hold a partial flatten, because the
    partial picture is what :class:`~risk.errors.RiskFlattenError`'s
    message names and the next sweep's enumeration re-derives.

    Validated in :meth:`__post_init__` rather than only where it is
    built, for the reason the channel's and the ledger's records do the
    same: the value is the proof, and a record that could be constructed
    disagreeing with the engine's own answer would launder a residue
    into a completed flatten — the one lie this feature exists to make
    impossible.  ``status`` is pinned to :data:`FLATTEN_STATUS_COMPLETED`
    the way the kill row's word is pinned to ``kill``: not a field a
    caller sets, but a fact the type will not state otherwise.
    """

    #: The one status, always :data:`FLATTEN_STATUS_COMPLETED`.  Carried
    #: on the record so a reader dispatching on it reads it from the
    #: thing itself; never set by a caller — the value layer refuses any
    #: other word, and the driver refuses to build this record at all
    #: while the engine reports anything standing.
    status: str
    #: The order ids the flatten cancelled, in the order it drove them.
    #: Empty when the engine held nothing standing — an already-flat
    #: book flattens, trivially and truthfully.
    cancelled_orders: tuple[str, ...]
    #: The position symbols the flatten closed, in the order it drove
    #: them, enumerated *after* the order half so that fills landing
    #: during the cancellations are seen and closed.
    closed_positions: tuple[str, ...]
    #: The standing kill instruction the flatten acted under — which
    #: supervisor killed, and when.  Not necessarily the flattening
    #: process's own send: the channel is first-write-wins, so a
    #: restarted supervisor flattens under the first kill's authority
    #: and this field says so.
    instruction: KillInstruction
    #: The identity of the process that drove the flatten (see
    #: :func:`risk.process_identity`) — kernel-read, never accepted from
    #: an unlabelled default, keyword-only to override, so the record
    #: names the process that did the work exactly as the channel's and
    #: the ledger's rows do.
    supervisor_process_id: str
    #: When the flatten drove — the ask's moment, defaulted at the verb's
    #: entry like the channel's ``sent_at``, and ordered against the
    #: instruction's own ``sent_at`` by the audit that asks how long the
    #: book stood open after the kill.
    flattened_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status != FLATTEN_STATUS_COMPLETED:
            raise RiskFlattenError(
                f"{FLATTEN_CODE}: a flatten result's status is the one word "
                f"this feature's own sentence names, "
                f"{FLATTEN_STATUS_COMPLETED!r}, got {self.status!r}; a "
                "flatten that did not complete raises rather than returning "
                "a result wearing a lesser word, so the word cannot be "
                "weakened here either (feature 330)"
            )
        object.__setattr__(
            self, "cancelled_orders", _require_names(self.cancelled_orders, "cancelled_orders")
        )
        object.__setattr__(
            self, "closed_positions", _require_names(self.closed_positions, "closed_positions")
        )
        if not isinstance(self.instruction, KillInstruction):
            raise RiskFlattenError(
                f"{FLATTEN_CODE}: a flatten result carries the standing "
                f"kill instruction it acted under, got {self.instruction!r} "
                f"({type(self.instruction).__name__}); without it the "
                "record cannot say whose authority the flatten acted on, "
                "and the audit that joins it to feature 331's ledger would "
                "join nothing (feature 330)"
            )
        object.__setattr__(
            self,
            "supervisor_process_id",
            _require_text(self.supervisor_process_id, "supervisor_process_id"),
        )
        _require_aware(self.flattened_at, "flattened_at")

    @property
    def summary(self) -> str:
        """One sentence: what was driven flat, by whom, under what authority.

        Composed rather than stored — every part is already a field, and
        a stored copy would be a second place for the record's own facts
        to disagree with itself.  The empty halves say ``none`` rather
        than nothing, because an operator reading that a flatten found
        nothing to drive needs the sentence to say it happened anyway;
        the identity and both moments are spelled in full so a log line
        joins to the channel's row and the ledger's events without a
        second query.
        """
        orders = ", ".join(self.cancelled_orders) if self.cancelled_orders else "none"
        positions = ", ".join(self.closed_positions) if self.closed_positions else "none"
        return (
            f"the flatten completed at {_isoformat_utc(self.flattened_at)}: "
            f"open orders cancelled ({orders}), positions closed "
            f"({positions}), driven by {self.supervisor_process_id} acting "
            f"under the instruction that {self.instruction.summary}"
        )


# -- The flattener --------------------------------------------------------------


class RiskFlattener:
    """Drives the execution engine flat, under the channel's standing kill.

    Bound to a database URL at construction; construction performs no I/O
    — there is no table of this feature's own to shape, and that absence
    is the design, not a shortcut (see the module docstring's second
    law).  The one store touch a flatten makes is the read of the kill
    channel, performed through this member's own
    :class:`~risk.kill.RiskKillSwitch` constructed over the same URL, so
    the authority the flattener cites and the row the order layer's guard
    refuses under are one row in one database.

    One face, one verb: the supervisor process calls
    :meth:`flatten` with the execution engine it holds — its own hold,
    never one routed through the strategy process — and the flattener
    drives the engine's verbs to a state the engine itself confirms is
    flat.  The flattener holds no state of its own beyond the URL and
    this process's identity, so a restarted supervisor flattens exactly
    as the original would have, under the original's kill.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RiskStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._switch = RiskKillSwitch(self._database_url)
        self._process_id: str | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RiskFlattener | None:
        """The flattener ``DATABASE_URL`` names, or ``None`` when it names none.

        The same resolution stance every store in this workspace takes:
        absent is a discoverable deployment state, not an exception.  The
        one direction this feature cuts on that absence is refusal —
        :func:`flatten_positions` refuses rather than flattening without
        an authority to read — so the ``None`` here is the caller's fact
        to decide with, exactly as :meth:`risk.kill.RiskKillSwitch.resolve`
        hands its ``None`` to a sender that must refuse on it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this flattener reads its authority through."""
        return self._database_url

    @property
    def process_id(self) -> str:
        """This process's identity — the label its flatten results carry.

        Resolved once, on first use, from the kernel — the same
        :func:`risk.process_identity` the channel's rows and the ledger's
        rows file under, so one operator grep splits all three tables'
        labels the same way.
        """
        if self._process_id is None:
            self._process_id = process_identity()
        return self._process_id

    # -- The verb -----------------------------------------------------------

    def flatten(
        self,
        execution_engine: object,
        *,
        flattened_at: datetime | None = None,
        supervisor_process_id: str | None = None,
    ) -> FlattenResult:
        """Flatten the book this engine holds; return only a completed result.

        The supervisor's verb, and the whole of feature 330's first
        clause.  The caller hands the engine it holds and nothing else —
        ``flattened_at`` defaults to this instant and
        ``supervisor_process_id`` to *this* process's identity, read from
        the kernel rather than accepted from the caller, for the same
        reason the channel's send refuses a caller-supplied label: a
        deployment-settable one is a label the strategy process could
        borrow.  Both are keyword-only for the same reason feature 320's
        ``record`` keeps its ``process_id`` one — a caller on the
        supervisor's own path should not pass them at all, and the one
        that does (a replay of a recorded flatten) has to say so.

        The drive, in order: read the standing kill (a flatten under no
        kill is refused — the kill stops the source, the flatten drains
        the sink, and the reverse order races the submissions the kill
        exists to stop); ask the engine what stands; cancel each order;
        ask again, for the positions — enumerated after the
        cancellations so fills that landed during them are seen; close
        each position; then ask the engine a final time, both questions.
        The result is built only if that final asking reports nothing
        standing and no drive faulted; anything else raises
        :class:`~risk.errors.RiskFlattenError` naming the residue and
        the faults, and the recovery is the refusal's own protocol —
        flatten again.

        **This verb never writes to the store.**  Its one store touch is
        the read of the channel, and that is the whole of the feature's
        hung-proofness: the write lock a hung strategy process died
        holding refuses every writer behind it, and a flatten that had
        to persist before answering would be exactly such a writer.  A
        store that cannot be read at all raises
        :class:`~risk.errors.RiskStoreError` — the channel's own address
        vocabulary, propagated unaltered, because the fault and its
        repair are the channel's, not the flatten's.
        """
        _require_face(execution_engine)
        instruction = self._switch.standing()
        if instruction is None:
            # The kill is monotone, so this is not a window that might
            # close -- it is the absence of the authority itself, and the
            # one door that fixes it is the send (or the halt door that
            # sends and flattens in order, feature 323).
            raise RiskFlattenError(
                f"{FLATTEN_CODE}: no kill instruction stands on the "
                f"channel, so there is no authority to flatten under; the "
                "kill stops the source and the flatten drains the sink -- "
                "send it first (risk.send_kill, feature 322), or through "
                "the door that does both in order (feature 323) -- because "
                "a flatten that raced the submissions it exists to stop "
                "would return a completed result over a book still "
                "filling (feature 330)"
            )
        sender = (
            self.process_id
            if supervisor_process_id is None
            else _require_text(supervisor_process_id, "supervisor_process_id")
        )
        moment = _require_aware(
            datetime.now(UTC) if flattened_at is None else flattened_at,
            "flattened_at",
        )

        # The order half first: a resting order is unfilled intent, and
        # cancelling it is what stops new exposure arriving mid-flatten.
        standing_orders = _enumerate(execution_engine, "open_orders")
        driven_orders: list[str] = []
        faults: list[str] = []
        first_fault: Exception | None = None
        for order_id in _once_each(standing_orders):
            try:
                execution_engine.cancel_order(order_id)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - the engine face is no class of this member's
                faults.append(f"cancel_order({order_id!r}) raised {exc!r}")
                if first_fault is None:
                    first_fault = exc
            else:
                driven_orders.append(order_id)

        # The position half second, over a fresh enumeration: fills that
        # landed during the cancellations moved the book after the first
        # asking, and the exposure the flatten must close is the book as
        # it stands now, not as it stood when the sweep began.
        standing_positions = _enumerate(execution_engine, "open_positions")
        driven_positions: list[str] = []
        for symbol in _once_each(standing_positions):
            try:
                execution_engine.close_position(symbol)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - the engine face is no class of this member's
                faults.append(f"close_position({symbol!r}) raised {exc!r}")
                if first_fault is None:
                    first_fault = exc
            else:
                driven_positions.append(symbol)

        # The judge is the engine's own answer, asked after everything was
        # driven: only a book the engine itself reports empty -- no
        # standing orders, no open positions -- supports the word this
        # feature's sentence hangs its claim on.
        residue_orders = _enumerate(execution_engine, "open_orders")
        residue_positions = _enumerate(execution_engine, "open_positions")
        if faults or residue_orders or residue_positions:
            because: list[str] = []
            if faults:
                because.append("the engine refused: " + "; ".join(faults))
            if residue_orders:
                because.append(
                    "open orders still standing: "
                    + ", ".join(repr(name) for name in residue_orders)
                )
            if residue_positions:
                because.append(
                    "positions still open: "
                    + ", ".join(repr(name) for name in residue_positions)
                )
            raise RiskFlattenError(
                f"{FLATTEN_CODE}: the flatten did not complete — "
                + "; ".join(because)
                + "; a completed result is returned only when the engine's "
                "own re-reading reports nothing standing, and the recovery "
                "is to flatten again — the next sweep re-reads the engine "
                "and completes over whatever remains (feature 330)"
            ) from first_fault

        return FlattenResult(
            status=FLATTEN_STATUS_COMPLETED,
            cancelled_orders=tuple(driven_orders),
            closed_positions=tuple(driven_positions),
            instruction=instruction,
            supervisor_process_id=sender,
            flattened_at=moment,
        )


# -- The module-level spelling -----------------------------------------------------


def flatten_positions(
    *,
    execution_engine: object,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    flattened_at: datetime | None = None,
    supervisor_process_id: str | None = None,
) -> FlattenResult:
    """Flatten the book, opening the flattener from the environment.

    The supervisor process's one call: resolve the authority from
    ``database_url``, else from ``DATABASE_URL``, and flatten.  A
    deployment that names neither is refused *by name* rather than
    silently doing nothing, because a flatten that skipped its authority
    check would return a completed result no kill ever authorised — and
    there is no second direction this absence cuts, because the flatten
    has one caller: the supervisor.  The order layer is who the flatten
    acts *on*, and the strategy process is who it must survive.

    The refusal happens before anything else, for the same reason
    :func:`risk.send_kill` resolves first: the authority must be read
    before the engine is driven.  Everything after the resolution is
    :meth:`RiskFlattener.flatten`'s, whose refusal vocabulary,
    best-effort drive and engine-judged completion this spelling
    inherits rather than restates.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise RiskFlattenError(
            f"{FLATTEN_CODE}: flatten_positions drives feature 330's "
            f"flatten and nothing names a store: {DATABASE_URL_ENV} is "
            "unset (and no database_url was supplied), so the standing "
            "kill instruction the flatten acts under could not be read. A "
            "flatten without its authority is not a flatten the record "
            "can stand behind -- it is the one call that must refuse "
            "rather than complete unauthorised (feature 330)"
        )
    return RiskFlattener(url).flatten(
        execution_engine,
        flattened_at=flattened_at,
        supervisor_process_id=supervisor_process_id,
    )
