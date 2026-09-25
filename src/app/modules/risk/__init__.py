"""The risk member's seat in the ``app`` package namespace — feature 322.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 322: *System runs
the risk supervisor as a separate process, which sends a kill instruction
to the order layer.*  The channel that sentence names lives in the
``risk`` workspace member (``packages/risk``, import name ``risk``); this
module is how the ``app`` package reaches that channel without importing
the member at module scope.

**The seat's one question is asked by two processes, and neither of them
composed this application.**  Feature 320's health-store seat (:mod:
`app.modules.router`) already stated the shape: a reading a *composed
application* hands out is a reading that application's lifetime bounds,
and the process whose state is in question is the one that cannot answer.
Feature 322 is that argument at its limit — the supervisor that *sends*
the kill and the order layer that *reads* it are different processes by
the feature's own first clause, and the one process this channel must
survive is the hung strategy process that would otherwise be composing
for everybody.  So this seat exposes exactly one accessor,
:func:`risk_kill_switch`, and it takes **no ``app`` argument at all**:
there is no registry to consult, and accepting one would suggest the
answer depended on it.  The switch is resolved from ``DATABASE_URL`` for
whatever process is asking — the supervisor's process gets the send face,
the order layer's process gets the reads and the guard, and which is
which is the caller's own fact, answered by the switch's
:attr:`~risk.kill.RiskKillSwitch.process_id` rather than by a second
accessor here (a caller holding the switch already holds the identity its
rows are filed under; a pass-through beside it would be a second spelling
of one fact with nothing to keep them in sync but care).

**``None`` is about the deployment, not about the kill.**  The accessor
answers ``None`` — not an exception — when no ``DATABASE_URL`` is
configured: an unconfigured deployment has no channel, so no supervisor
ever sent a kill through one.  A caller that must *send* must treat the
``None`` as a refusal to proceed rather than as an empty channel — there
is deliberately no fallback here that opens a default database, because a
kill persisted into a database nobody named would be invisible to every
order-layer process that reads this seat — and the member's own
:func:`risk.send_kill` makes that refusal for the supervisor that uses
it.  A caller that must *refuse under* a kill passes vacuously on the
``None``, the stance :func:`risk.require_orders_allowed` takes for it.

**Composition stays the factory's job, and the member's component is not
this seat's answer.**  The member does register a component (the same
switch, resolved at build time — see the member's own ``__init__``), so a
composed application carries one under :data:`COMPONENT_NAME`; this seat
deliberately does not add a second accessor that reads it out of an
application, because the one question this seat answers — *what is the
kill switch for the process asking?* — has one honest answer, and it is
the resolution.  A caller that wants the composed reflection can ask the
factory for :data:`COMPONENT_NAME` itself; a second spelling here would
be a second thing to keep in sync.  The same discipline holds for the
member's surface: this module re-exports nothing — a caller who has the
switch reaches ``send()``, ``standing()``, ``killed()`` and
``require_orders_allowed()`` on it, and a caller that wants the value
types or the refusal vocabulary reaches the member's own namespace.

**Construction touches no database.**  The switch resolves its path on
first use and opens nothing until an operation needs it, so asking for
the channel is always safe — the same promise the member's own builder
makes — and the first :meth:`~risk.kill.RiskKillSwitch.send` is where a
kill instruction is actually written.

The member is imported at call time rather than at module scope, per the
workspace rule every seat follows: a module-scope member import here would
put the member on ``sys.path`` during the factory's scan of ``src/app``,
which is not a member.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from risk import RiskKillSwitch

__all__ = ["COMPONENT_NAME", "risk_kill_switch"]

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
