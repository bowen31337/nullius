"""``risk`` — Risk Supervisor & Kill Switches: the kill instruction.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 322: *System runs
the risk supervisor as a separate process, which sends a kill instruction
to the order layer.*  ``docs/nullius-tech-architecture.md`` §13.3 line 717
fixes why that sentence is shaped the way it is: *"Runs as a separate
process with kill authority over the execution engine, so a hung strategy
process cannot prevent a flatten."*  ``docs/alpha-engine-prd.md`` C10
names the subject — *"Risk and kill switches"* — and its bullets name the
triggers (equity floor, daily loss, IC decay, staleness watchdog) that the
category's later features own, one each.

This member is the category's first feature, and everything after it
(323's halt door, 325's manual reset, 330's flatten-while-hung, 331's
halt event ledger) builds on the one thing it delivers: **a channel
through which a supervisor in its own process stops an order layer in
another one.**  Three pieces:

* :mod:`risk.kill` — the channel.  One row in the workspace's relational
  store (``DATABASE_URL``), held to one row by the table's own
  ``singleton`` key, written by the supervisor's
  :meth:`~risk.kill.RiskKillSwitch.send` and read by the order layer's
  :meth:`~risk.kill.RiskKillSwitch.standing` /
  :meth:`~risk.kill.RiskKillSwitch.require_orders_allowed` — first-write-
  wins, monotone, no clear.  The module-level spellings —
  :func:`~risk.kill.send_kill` for the supervisor's process,
  :func:`~risk.kill.require_orders_allowed` for the order layer's — open
  the switch from the environment so neither process composes anything
  to use it.
* :mod:`risk.errors` — the refusal vocabulary.  One base so a single
  ``except`` catches the member, and three nouns apart: the channel's
  address and persistence (:class:`~risk.errors.RiskStoreError`), the
  instruction's own terms (:class:`~risk.errors.RiskKillSwitchError`),
  and the order layer's receipt (:class:`~risk.errors.
  RiskOrdersKilledError`, which carries the standing instruction).
* :mod:`risk._identity` — the ``<host>/<pid>`` label that makes *"a
  separate process"* a checkable fact: a kill row names the process that
  sent it, read from the kernel and never accepted from the caller.

**Why the channel is a table and not a call.**  The supervisor and the
order layer are two processes, so no in-process call can join them; §17
leaves no port to serve a socket on (*"No inbound ports on the live
trading host"*); and §14 puts live trading on its own host with its own
credentials, so the one medium both processes already hold is the shared
relational store.  That is also the medium that survives the failure
this feature is for: a hung strategy process cannot serve anything, but
it cannot stop the database from answering either.  Each operation opens
its own connection, so the row one process writes is the row the next
process reads — and the member's suite proves the send and the guard
against an actual second interpreter, not against the same process's
memory.

This package also *is* a component of the composed application: importing
it registers a builder with the application factory
(``app.module_loader.register``), so the module loader discovers it by
scanning the workspace members the root pyproject.toml declares.  No
central registry, router table or app factory is edited to wire it in —
registration happens as an import side effect right here.

The registration lives in this module and deliberately not in a submodule:
``app.module_loader._import_package`` re-executes a package's
``__init__.py`` on every ``create_app()`` call, but a submodule already
cached in ``sys.modules`` under the loader's synthetic name is not
re-executed — so a ``@register`` in a submodule would fire on the first
composition of a process and silently drop out of every later one (the
same discipline :mod:`router` and :mod:`cost_model` state for
themselves).

**The component is the channel's composed reflection, not its canonical
door.**  The builder below resolves ``DATABASE_URL`` and hands back the
same :class:`~risk.kill.RiskKillSwitch` any caller could construct,
exactly as :func:`canary.build_halt_store` hands back the halt store —
so a composed application *carries* the kill switch and can hand it to a
caller that asked for one by name.  But the two processes this feature's
own sentence names — the supervisor that sends, the order layer that
reads — do not and must not go through composition: a switch composed
into an application is a switch that application's lifetime bounds, and
the process this feature must survive is precisely the one that is hung.
Both processes construct the switch from ``DATABASE_URL`` for
themselves, through :func:`~risk.kill.RiskKillSwitch.resolve` or the
module-level spellings, the same road feature 320's submission-health
store takes and for a stronger version of its reason (the router member
names *"a supervisor in another process entirely"* as one of *its*
store's readers; this member's supervisor is that reader, and its order
layer is the writer's counterpart).  The two doors cannot disagree,
because both construct the same class over the same URL, and the row
behind both is one.
"""

from __future__ import annotations

from app.module_loader import register

from ._identity import PROCESS_ID_SEPARATOR, process_identity
from .errors import (
    KILL_INSTRUCTION_CODE,
    ORDERS_KILLED_CODE,
    RiskError,
    RiskKillSwitchError,
    RiskOrdersKilledError,
    RiskStoreError,
)
from .kill import (
    DATABASE_URL_ENV,
    KILL_INSTRUCTION,
    RISK_ORDER_KILL_TABLE,
    KillInstruction,
    RiskKillSwitch,
    orders_killed_error,
    require_orders_allowed,
    send_kill,
)

__all__ = [
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "KILL_INSTRUCTION",
    "KILL_INSTRUCTION_CODE",
    "ORDERS_KILLED_CODE",
    "PROCESS_ID_SEPARATOR",
    "RISK_ORDER_KILL_TABLE",
    "KillInstruction",
    "RiskError",
    "RiskKillSwitch",
    "RiskKillSwitchError",
    "RiskOrdersKilledError",
    "RiskStoreError",
    "orders_killed_error",
    "process_identity",
    "require_orders_allowed",
    "send_kill",
]

__version__ = "0.1.0"

#: The component name this member registers under — unprefixed, following
#: the ``router`` / ``book`` / ``canary`` precedent for a member's first
#: and only component, so the member, its seat in ``app.modules.risk`` and
#: the spec's ``plugin="risk"`` share one spelling they cannot drift from
#: silently.  The member's suite asserts the two agree.
COMPONENT_NAME = "risk"


@register(COMPONENT_NAME)
def build_risk_kill_switch() -> RiskKillSwitch | None:
    """Component builder: the kill switch bound to ``DATABASE_URL``.

    Takes no arguments — the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application
    always carries a switch for whatever the process is actually pointed
    at (the shared test fixtures set one per test).

    Returns ``None`` when no ``DATABASE_URL`` is configured — an
    unconfigured store is a discoverable deployment state, not an
    exception, the same stance :meth:`router.store.
    RouterExchangeInfoStore.resolve` and :meth:`canary.CanaryHaltStore.
    resolve` take.  Construction performs no I/O: the schema is created
    on the first :meth:`~risk.kill.RiskKillSwitch.send` or read, so
    composing the application never touches a database.

    What the composed switch is *for* is stated in this module's
    docstring: a reflection, for callers that ask a composed application
    for the channel by name.  The supervisor and the order layer reach
    the same switch without composing — see :mod:`risk.kill` for the two
    module-level spellings they use instead.
    """
    return RiskKillSwitch.resolve()
