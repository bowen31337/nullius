"""Feature 323: the halt door — ``POST /risk/halt``.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 323: *"System
exposes POST /risk/halt, which flattens open positions and rejects new order
submission."*  ``docs/nullius-tech-architecture.md`` §13.3 line 717 gives the
sentence its whole reason in one clause: *"Runs as a separate process with
kill authority over the execution engine, so a hung strategy process cannot
prevent a flatten."*  ``docs/alpha-engine-prd.md`` C10 names the subject —
*"Risk and kill switches"* — and its daily-loss bullet names the trigger whose
repair is feature 325's; the trigger is not this feature's to fire.

Read together, the sentence is not a new act but the **composed act of two
acts this member already owns, driven in order**: feature 322's kill channel
and feature 330's flatten. The door is the one place they meet — it sends the
kill through the channel the supervisor already holds, then drives the flatten
over the book, and the two cannot be separated because a flatten under no
standing kill is refused by the flatten's own authority check (:mod:`risk.flatten`
promised the kill stops the source before the flatten drains the sink), and a
kill that does not flatten leaves the exposure standing. So this module does
the two things the sentence's own words do, and nothing else:

* **It flattens open positions.**  Not by a verb of its own — by driving
  :meth:`risk.flatten.RiskFlattener.flatten` over the execution engine the
  caller hands in, exactly as the supervisor does. The engine face is the
  supervisor's own hold on the execution engine, and no composition can supply
  it (§13.3's *"kill authority"* is a process's fact, not an application's), so
  the request carries it and the flatten drives it: cancel every order
  standing, close every position open, and return only when the engine's own
  re-reading reports nothing standing.
* **It rejects new order submission.**  Not by a second enforcement of its
  own — by the *consequence* of the kill it just sent. The order layer's
  submission path already consults :func:`risk.require_orders_allowed`
  (feature 322's guard), which raises :class:`~risk.errors.RiskOrdersKilledError`
  while a kill stands; once the door has sent the kill the order layer is
  refused by the channel that already exists. The door does not reach into the
  order path, does not hold order authority and does not enforce the refusal
  itself — it sets the standing state the order path already refuses under, and
  the shared row between the send and the guard is what makes the sentence true
  without the door holding any authority of its own.

**The order is the law, and the door keeps it.**  The kill is sent first
(first-write-wins: the first kill's sender and moment stay on record), so the
standing instruction is on the row before anything is flattened; the flatten is
driven second, so its authority check finds the kill it just sent and the book
is drained while the tap is shut. A flatten driven before the send would be
refused for want of authority; a kill sent after the flatten would leave the
source running while the sink drained — the race the kill exists to stop. The
door performs no store write of its own: the flatten's only store touch is the
read of the channel, which is the whole of the hung-proofness, and the kill
send is 322's own write over 322's own row.

**What this module deliberately does not do.**  It does not *decide* to halt:
the triggers are features 324–329's, each with its own module and its own
repair, and a door that also judged equity or staleness would be five features
wearing one verb. It does not *decide* the kill or the flatten: those are
322's and 330's, and this module composes them rather than re-owning them. It
does not *add a table*: the kill lands in 322's ``risk_order_kill`` and the
flatten writes nothing, so the halt door owns no schema. It does not *reset*:
the kill it sends is monotone, and the features that own recovery (325's manual
reset) open their own doors over their own vocabularies. And it does not
*serve a socket*: §17 leaves no inbound port on the live trading host, so
``POST /risk/halt`` is a Python seam over the composed components — the stance
:mod:`forward.record` takes for ``POST /forward/promote`` and :mod:`ledger.debit`
for ``POST /ledger/debit`` — not an HTTP server.

The refusal vocabulary is inherited, not restated: a bad kill ask raises in
:class:`~risk.errors.RiskKillSwitchError` (opening ``kill_instruction``), a
store that cannot take the row in :class:`~risk.errors.RiskStoreError`, a
residue or engine fault in :class:`~risk.errors.RiskFlattenError` (opening
``flatten``). The endpoint composes no message and no error class of its own —
a caller catching the member's errors catches the channel's and the flatten's
refusals unchanged, which is the point of a seam that composes rather than
owns.

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as the channel and the flatten beside it are. A URL whose scheme is not
``sqlite`` is refused by name, as an *address* fault, in
:class:`~risk.errors.RiskStoreError` — the vocabulary that fault already
belongs to — and the door reaches the switch and the flattener through their
own resolution, so the four doors (send, flatten, halt, guard) cannot disagree:
one class, one URL, one row.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import RiskFlattenError, RiskKillSwitchError, RiskStoreError
from .flatten import FlattenResult, RiskFlattener
from .kill import KillInstruction, RiskKillSwitch

__all__ = [
    "DATABASE_URL_ENV",
    "RISK_HALT_ROUTE",
    "HaltEndpoint",
    "HaltRequest",
    "HaltResponse",
]

#: The workspace-wide environment variable naming the relational store —
#: the one spelling every store in this member already uses, restated here so
#: this module states its own contract and imports no sibling's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The route this endpoint serves — app_spec.xml's API summary row for feature
#: 323, pinned as a class attribute (:attr:`HaltEndpoint.route`) so the
#: endpoint, the spec's summary and whatever routes the deployment can match on
#: one spelling, exactly as :data:`risk.flatten`'s and :data:`risk.kill`'s
#: greppable tokens do for their own nouns.
RISK_HALT_ROUTE = "/risk/halt"


def _require_engine(execution_engine: object) -> None:
    """Refuse a halt request that carries no engine to drive.

    The engine is the supervisor's own hold on the execution engine — the one
    field the request carries and the one thing no composition can supply
    (§13.3's *"kill authority over the execution engine"* is a process's fact,
    not an application's). A halt with no engine is not a halt over a
    flat book; it is a halt over nothing, and the flatten's own face check
    would refuse it a moment later with a less direct message, so the request
    names the gap here, at the thing that stated it.
    """
    if execution_engine is None:
        raise RiskFlattenError(
            "flatten: a halt request carries the execution engine the flatten "
            "must drive, and this one carries none; the halt door flattens the "
            "book the supervisor holds — open_orders() and open_positions() to "
            "ask what stands, cancel_order() and close_position() to end it — "
            "and a request with no engine has no book to flatten (feature 323)"
        )


# -- The request and the response -------------------------------------------------


@dataclass(frozen=True)
class HaltRequest:
    """The body of one ``POST /risk/halt``: the engine to drive flat.

    **One field, and the short list is the design.**  Everything else the halt
    acts on is either read from the channel or absent by construction:

    * ``execution_engine`` — the supervisor's own hold on the execution engine,
      the face the flatten drives (cancel every order, close every position).
      Caller-supplied and duck-typed, never composed, because no composition
      can supply the supervisor's hold on the engine (§13.3's whole point).

    There is deliberately **no kill moment and no sender label**. The kill the
    door sends is 322's, and 322 defaults its ``sent_at`` to the instant of the
    send and its ``supervisor_process_id`` to the calling process's kernel-read
    identity, refusing a caller-supplied one — a deployment-settable label is a
    label the strategy process could borrow. The halt door inherits that
    refusal rather than restating it: it sends through the channel's own
    :meth:`RiskKillSwitch.send`, which keeps the moment and the label honest.
    There is likewise **no flatten instant**: 330's flatten defaults its
    ``flattened_at`` to the instant of the drive, and the audit that orders the
    flatten against the kill reads both from the records the two acts return.

    Frozen, because a request is a fact the caller stated; editing one in flight
    would be driving a different engine than was asked for.
    """

    #: The execution engine the flatten drives — the supervisor's hold, never
    #: one routed through the strategy process.
    execution_engine: object

    def __post_init__(self) -> None:
        _require_engine(self.execution_engine)


@dataclass(frozen=True)
class HaltResponse:
    """The answer to one ``POST /risk/halt``: the kill sent, the book flattened.

    **Two records, and the pair is the testimony.**  The halt is two acts
    driven in order, and the response carries the record of both, so a caller
    holding a :class:`HaltResponse` holds what the door did rather than a
    re-derivation of the ask:

    * ``instruction`` — the standing kill the door sent (which process killed,
      and when), first-write-wins, so a retry over an already-killed channel
      returns the first kill's record rather than this call's.
    * ``result`` — the completed flatten (what was cancelled, what was closed,
      when it completed), built only when the engine's own re-reading reported
      nothing standing — the one status :class:`FlattenResult` will construct.

    Frozen, because the response is the endpoint's testimony about two states at
    one moment; two responses that disagreed for one request would be the door
    revising what it did, and a halt is the act an operator acts on at three in
    the morning.
    """

    #: The standing kill instruction the door sent — first-write-wins.
    instruction: KillInstruction
    #: The completed flatten the door drove — the book, drained flat.
    result: FlattenResult

    def __post_init__(self) -> None:
        if not isinstance(self.instruction, KillInstruction):
            raise RiskKillSwitchError(
                "kill_instruction: a halt response carries the standing kill "
                f"instruction the door sent, got {self.instruction!r} "
                f"({type(self.instruction).__name__}); without it the response "
                "cannot say whose authority the halt acted on, and the audit "
                "that joins it to feature 331's ledger would join nothing "
                "(feature 323)"
            )
        if not isinstance(self.result, FlattenResult):
            raise RiskFlattenError(
                "flatten: a halt response carries the completed flatten the "
                f"door drove, got {self.result!r} "
                f"({type(self.result).__name__}); the halt flattens the book "
                "the supervisor holds, and a response without the flatten's "
                "own completed result would be a halt that flattened nothing "
                "(feature 323)"
            )


# -- The endpoint -----------------------------------------------------------------


class HaltEndpoint:
    """Serves ``POST /risk/halt`` over one kill switch and one flattener.

    Constructed with the switch it sends through and the flattener it drives —
    both resolved over the same ``DATABASE_URL``, so the kill the door sets and
    the flatten the door drives are one row in one database. The endpoint holds
    no state of its own — no memo of halted books, no cache of instructions —
    because a halt remembered in the endpoint would be one a second process, a
    restart or a recycled worker silently loses sight of, and the supervisor
    that pronounced the halt ran in another process entirely. The row in the
    channel and the book the engine holds are the only records of what was
    done, so they are the only things the answer is drawn from, on every
    request, in every process.
    """

    #: The route this endpoint serves — :data:`RISK_HALT_ROUTE`, pinned as a
    #: class attribute so ``HaltEndpoint.route`` states the contract without an
    #: instance, exactly as :class:`forward.record.PromoteEndpoint` and
    #: :class:`ledger.debit.DebitEndpoint` pin their own routes.
    route = RISK_HALT_ROUTE

    def __init__(
        self,
        switch: RiskKillSwitch,
        flattener: RiskFlattener,
    ) -> None:
        # Duck-checked rather than isinstance-guarded: the factory's scan
        # imports this member under an alias module, so the *composed* switch
        # and flattener are structurally a RiskKillSwitch / RiskFlattener but
        # never the same class object a direct import yields — an isinstance
        # here would refuse the very components the factory hands out. The
        # contract is the send / flatten seams, and that is what is checked.
        if not callable(getattr(switch, "send", None)):
            raise TypeError(
                "HaltEndpoint speaks a RiskKillSwitch (something with a "
                f"send() seam); got {type(switch).__name__}"
            )
        if not callable(getattr(flattener, "flatten", None)):
            raise TypeError(
                "HaltEndpoint speaks a RiskFlattener (something with a "
                f"flatten(engine) seam); got {type(flattener).__name__}"
            )
        self._switch = switch
        self._flattener = flattener

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> HaltEndpoint | None:
        """The endpoint over the switch and flattener ``DATABASE_URL`` names, or ``None``.

        Resolves the switch and the flattener exactly as the member's own
        builders do (:meth:`RiskKillSwitch.resolve` and
        :meth:`RiskFlattener.resolve`), so the endpoint and the composed
        ``risk`` / ``risk-flattener`` components always point at the same
        database. No ``DATABASE_URL`` composes no endpoint — an unconfigured
        store is a discoverable state, not an error, and the degrade-don't-break
        stance every builder in this workspace takes — while the supervisor that
        must pronounce a halt is, again, the one that must not find itself
        without a store to send through.
        """
        switch = RiskKillSwitch.resolve(env)
        flattener = RiskFlattener.resolve(env)
        if switch is None or flattener is None:
            return None
        return cls(switch, flattener)

    @property
    def switch(self) -> RiskKillSwitch:
        """The kill switch this endpoint sends through."""
        return self._switch

    @property
    def flattener(self) -> RiskFlattener:
        """The flattener this endpoint drives."""
        return self._flattener

    # -- The route ----------------------------------------------------------

    def post(
        self,
        request: HaltRequest,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> HaltResponse:
        """Answer one ``POST /risk/halt``: send the kill, then flatten the book.

        The whole of feature 323 at its seam, and the two acts in the order the
        sentence names. **First the kill**: the endpoint sends feature 322's
        kill instruction through the switch it holds — first-write-wins, so a
        halt over an already-killed channel writes nothing and returns the
        standing record with ``changed=False`` — and the instruction lands on
        record. **Then the flatten**: the endpoint drives feature 330's flatten
        over the engine the request carries, which reads the standing kill it
        just sent (the authority check passes, because the send wrote the row
        first-write-wins and the flatten reads it back), cancels every order
        standing, closes every position open, and returns only a completed
        result — an engine whose own re-reading reports nothing standing.

        ``clock`` drives both instants when supplied (tests and replays route
        their own time through it); left alone, the kill takes the instant of
        the send and the flatten the instant of the drive, each read once from
        the member's own clock.

        The rejection of new order submission is the *consequence*, not a third
        act: the kill now standing is the state the order layer's own
        ``risk.require_orders_allowed`` guard (feature 322) refuses under, so
        the door has done its work once the response returns — every later
        submission the guard refuses is the kill standing.

        Refusals are the channel's and the flatten's own, propagated unchanged:
        a bad kill ask raises :class:`~risk.errors.RiskKillSwitchError`, a store
        that cannot take the row :class:`~risk.errors.RiskStoreError`, and a
        residue or engine fault :class:`~risk.errors.RiskFlattenError`. The
        endpoint composes no message of its own.
        """
        instant = clock() if clock is not None else datetime.now(UTC)
        instruction = self._switch.send(sent_at=instant)
        result = self._flattener.flatten(request.execution_engine, flattened_at=instant)
        return HaltResponse(instruction=instruction, result=result)
