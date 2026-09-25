"""The risk member's seat in the ``app`` package namespace.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 322: *System runs
the risk supervisor as a separate process, which sends a kill instruction
to the order layer* — feature 331: *System persists every halt event with
its trigger reason and timestamp for later reconciliation* — and feature
330: *System flattens successfully even when the strategy process is
hung, which returns a completed flatten result.*  All three sentences'
nouns live in the ``risk`` workspace member (``packages/risk``, import
name ``risk``); this module is how the ``app`` package reaches that
channel, that ledger and that flatten verb without importing the member
at module scope.

**The seat's questions are asked by processes, and none of them
composed this application.**  Feature 320's health-store seat (:mod:
`app.modules.router`) already stated the shape: a reading a *composed
application* hands out is a reading that application's lifetime bounds,
and the process whose state is in question is the one that cannot answer.
Feature 322 is that argument at its limit — the supervisor that *sends*
the kill and the order layer that *reads* it are different processes by
the feature's own first clause, and the one process this channel must
survive is the hung strategy process that would otherwise be composing
for everybody.  So this seat exposes one accessor per member question,
and all of them take **no ``app`` argument at all**: there is no registry
to consult, and accepting one would suggest the answer depended on it.
:func:`risk_kill_switch` resolves the channel from ``DATABASE_URL`` for
whatever process is asking — the supervisor's process gets the send face,
the order layer's process gets the reads and the guard, and which is
which is the caller's own fact, answered by the switch's
:attr:`~risk.kill.RiskKillSwitch.process_id` rather than by a second
accessor here (a caller holding the switch already holds the identity its
rows are filed under; a pass-through beside it would be a second spelling
of one fact with nothing to keep them in sync but care).
:func:`risk_halt_event_store` resolves feature 331's ledger the same
way, for the same reason pushed one process further: the process that
records a halt event and the process that reconciles the ledger later
are different processes too — the reconciler usually an operator's
sweep, hours after the halting supervisor wrote — and the record this
feature's own sentence is for must outlive both.
:func:`risk_flattener` resolves feature 330's flattener the same way,
for the reason that is this category's whole shape: the flatten is the
one act that must run while another process on this seat is hung, so
the object that drives it can be nobody's composition — and the engine
face the caller hands its :meth:`~risk.flatten.RiskFlattener.flatten`
is the supervisor's own hold on the execution engine (§13.3's *"kill
authority"*, a process's fact, not an application's), which no accessor
here could supply anyway.

**``None`` is about the deployment, not about the kill, the ledger or
the flatten.**  All three accessors answer ``None`` — not an exception —
when no ``DATABASE_URL`` is configured: an unconfigured deployment has
no channel, so no supervisor ever sent a kill through one, and no
ledger, so no halt event was ever recorded in one — and no authority
for a flatten to act under.  A caller that must *send*, *record* or
*flatten* must treat the ``None`` as a refusal to proceed rather than as
an empty channel — there is deliberately no fallback here that opens a
default database, because a kill, a halt event or a completed flatten
returned against a database nobody named would be invisible to every
order-layer process that reads this seat — and the member's own
:func:`risk.send_kill`, :func:`risk.record_halt` and
:func:`risk.flatten_positions` make that refusal for the processes that
use them.  A caller that must *refuse under* a kill passes vacuously on
the ``None``, the stance :func:`risk.require_orders_allowed` takes for
it, and a caller sweeping the ledger gets the empty truth, the stance
:func:`risk.recorded_halt_events` takes for its side.

**Composition stays the factory's job, and the member's components are
not this seat's answer.**  The member does register components (the same
switch, the same ledger and the same flattener, resolved at build time —
see the member's own ``__init__``), so a composed application carries
them under :data:`COMPONENT_NAME` and the member's ``risk-halt-events``
and ``risk-flattener`` names; this
seat deliberately does not add accessors that read them out of an
application, because the questions this seat answers — *what is the
kill switch, what is the halt event ledger, and what is the flattener,
for the process asking?* — each have one honest answer, and it is the
resolution.  A
caller that wants the composed reflection can ask the factory for
:data:`COMPONENT_NAME` itself; a second spelling here would
be a second thing to keep in sync.  The same discipline holds for the
member's surface: this module re-exports nothing — a caller who has the
switch reaches ``send()``, ``standing()``, ``killed()`` and
``require_orders_allowed()`` on it, and a caller that wants the value
types or the refusal vocabulary reaches the member's own namespace.
The ledger accessor keeps the same discipline against the member's
second component: a caller holding the store reaches ``record()`` and
``events()`` on it, and the flattener's accessor against its third: a
caller holding it reaches ``flatten()``.

**Construction touches no database.**  All three accessors resolve
their path on first use and open nothing until an operation needs it, so
asking for the channel, the ledger or the flattener is always safe — the
same promise the member's own builders make — and the first
:meth:`~risk.kill.RiskKillSwitch.send` or
:meth:`~risk.halt_events.RiskHaltEventStore.record` is where a row is
actually written (the flattener writes none, ever — feature 330's own
law, and the reason a hung strategy process cannot wedge it).

The member is imported at call time rather than at module scope, per the
workspace rule every seat follows: a module-scope member import here would
put the member on ``sys.path`` during the factory's scan of ``src/app``,
which is not a member.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from risk import RiskFlattener, RiskHaltEventStore, RiskKillSwitch

__all__ = [
    "COMPONENT_NAME",
    "risk_flattener",
    "risk_halt_event_store",
    "risk_kill_switch",
]

#: The component name the risk member registers under.  Kept here as well
#: as in the member — every seat in this workspace spells its own name
#: twice for the same reason — so the two cannot drift apart silently, and
#: a caller that wants the composed reflection (the member's component,
#: not this seat's answer) asks the factory for this one name.
COMPONENT_NAME = "risk"


def risk_kill_switch() -> RiskKillSwitch | Any:
    """Feature 322's kill switch, resolved for whatever process is asking.

    Resolved from ``DATABASE_URL`` through the member's own
    :meth:`risk.kill.RiskKillSwitch.resolve` rather than read out of a
    composed application, and that is the feature rather than an
    implementation detail: the supervisor that sends the kill and the
    order layer that refuses under it are different processes, and the
    channel must reach both without either having to be alive to serve
    the other.  Takes no ``app`` argument for the same reason — there is
    no registry to consult, so accepting one would suggest the answer
    depended on it.

    ``None`` when no ``DATABASE_URL`` is configured — an unconfigured
    store is a discoverable deployment state, not an exception, the same
    stance :func:`app.modules.router.router_exchange_info_component`
    takes.  Construction performs no I/O, so asking about the channel can
    never itself fail; see the module docstring for how a sender and a
    reader must each treat the ``None``.
    """
    from risk import RiskKillSwitch

    return RiskKillSwitch.resolve()


def risk_halt_event_store() -> RiskHaltEventStore | Any:
    """Feature 331's halt event ledger, resolved for whatever process is asking.

    Resolved from ``DATABASE_URL`` through the member's own
    :meth:`risk.halt_events.RiskHaltEventStore.resolve`, on the same road
    :func:`risk_kill_switch` takes and for a stronger version of its
    reason: the process that records a halt event (the supervisor, or
    whatever door fired the halt) and the process that reconciles the
    ledger later (usually an operator's sweep, after the night is over)
    are different processes, and the record must reach both without
    either having to be alive to serve the other.  Takes no ``app``
    argument for the same reason the switch's accessor does.

    ``None`` when no ``DATABASE_URL`` is configured — the same
    discoverable deployment state, and the same split the member's own
    module-level spellings make on it: recording refuses on the ``None``
    (:func:`risk.record_halt`), reading answers the empty truth
    (:func:`risk.recorded_halt_events`), and a caller here decides its
    direction the same way.  Construction performs no I/O.
    """
    from risk import RiskHaltEventStore

    return RiskHaltEventStore.resolve()


def risk_flattener() -> RiskFlattener | Any:
    """Feature 330's flattener, resolved for whatever process is asking.

    Resolved from ``DATABASE_URL`` through the member's own
    :meth:`risk.flatten.RiskFlattener.resolve`, on the same road the
    switch and the ledger accessors take and for the reason that is this
    category's whole shape: the flatten must run while the strategy
    process is hung, so the flattener can be nobody's composition — a
    flattened-in-a-composed-app would be a flatten that app's lifetime
    bounded, and the process this feature must outlive is the one that
    is hung.  Takes no ``app`` argument for the same reason the other
    accessors do.

    The accessor supplies the *authority*; the caller supplies the
    *engine*: :meth:`~risk.flatten.RiskFlattener.flatten` takes the
    execution engine face as its one ask, because §13.3's kill authority
    is the supervisor process's own hold on the engine and no seat could
    — or should — hand one out.

    ``None`` when no ``DATABASE_URL`` is configured — the same
    discoverable deployment state, and the member's own
    :func:`risk.flatten_positions` refuses on it, because a flatten
    without an authority to read must not complete.  Construction
    performs no I/O and creates no table: the flattener owns none, which
    is feature 330's hung-proofness stated in the object graph.
    """
    from risk import RiskFlattener

    return RiskFlattener.resolve()
