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
(323's halt door, 325's manual reset) builds on the one thing it
delivers: **a channel through which a supervisor in its own process
stops an order layer in another one.**  Feature 331 — the halt event
ledger, the member's second feature — and feature 330 — the flatten
that survives a hung strategy process, the member's third — build on it
too, and on nothing else: the ledger is the record of the halts the
channel and the doors after it produce, and the flatten is the drainage
of the authority the channel holds.  Ten pieces:

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
* :mod:`risk.flatten` — the act, feature 330: *System flattens
  successfully even when the strategy process is hung, which returns a
  completed flatten result.*  No table of its own, and that absence is
  the feature: the one thing a hung strategy process can wedge from
  outside this module is the shared store's write lock — it died
  holding it — and a flatten that had to write before answering would
  be a flatten a hung strategy process could prevent, which §13.3
  separates the processes to rule out.  So
  :meth:`~risk.flatten.RiskFlattener.flatten` reads the channel's
  standing kill through its own switch (a flatten under no kill is
  refused — the kill stops the source, the flatten drains the sink),
  drives the execution engine face's own verbs — cancel every order
  standing, then close every position open — and returns a
  :class:`~risk.flatten.FlattenResult` only when the engine's own
  re-reading reports nothing standing: *completed* is the one status
  the value layer will construct.  The module-level spelling —
  :func:`~risk.flatten.flatten_positions` — opens the flattener from
  the environment for the same reason the channel's spellings do, and
  refuses on the store's absence, because the flatten has one caller —
  the supervisor — and no direction that may fail softly.
* :mod:`risk.halt_events` — the ledger, feature 331: *System persists
  every halt event with its trigger reason and timestamp for later
  reconciliation.*  A second table in the same store
  (``risk_halt_event``), appended to by the halting process's
  :meth:`~risk.halt_events.RiskHaltEventStore.record` — one row per
  event, each carrying its trigger reason, its ``triggered_at`` moment,
  its ``recorded_at`` moment and the recording process's identity — and
  swept oldest-first by :meth:`~risk.halt_events.RiskHaltEventStore.
  events`, anchored at an instant when the reconciler passes one (the
  channel's own ``sent_at`` is the anchor its docstrings promised this
  ledger would order against).  Where the channel is the *state* that
  stands, this is the *log* of what happened: every event, ever,
  append-only, no deduplication — completeness is the feature, because a
  reconciliation over a ledger with a hole in it reconciles nothing.
  The module-level spellings — :func:`~risk.halt_events.record_halt` for
  the halting process, :func:`~risk.halt_events.recorded_halt_events`
  for the reconciler — open it from the environment for the same reason
  the channel's spellings do, and split the same way on its absence:
  recording refuses, reading answers the empty truth.
* :mod:`risk.clock_skew` — the measurement, feature 329: *System
  persists the measured clock skew that halted trading when it exceeded
  the threshold against exchange server time.*  A third table
  (``risk_clock_skew``), one row per *halting* measurement, written by
  :meth:`~risk.clock_skew.RiskClockSkewStore.halt_on_skew` — which
  measures the skew from two caller-supplied readings of one probe,
  returns ``None`` inside the band, and otherwise sends the channel's
  kill and then records the row, with ``halted_at`` read back from the
  standing instruction rather than stamped here.  Where the channel is
  the *state* that stands and the ledger is the *log* of every halt,
  this is the *measurement* that caused one: the two instants and the
  arithmetic between them, signed, so a later reader can re-derive the
  skew that stopped trading instead of taking a number's word for it.
  The module-level spellings — :func:`~risk.clock_skew.halt_on_clock_skew`
  and :func:`~risk.clock_skew.measured_clock_skews` — open it from the
  environment for the same reason the channel's and the ledger's do, and
  split the same way on its absence: a halting probe refuses without a
  store, a read answers the empty truth.
* :mod:`risk.demotion` — the demotion, feature 326: *System persists an
  automatic demotion when live information coefficient falls below 40
  percent of its backtest value.*  A fourth table (``risk_signal_demotion``),
  one row per *demoted* signal, written by
  :meth:`~risk.demotion.RiskSignalDemotionStore.record_demotion` — which
  judges the handed-over retention ratio against ``DEMOTION_BOUND`` (40
  percent, a constant of the module, not configuration), returns ``None`` at
  or above the bound, and otherwise persists the demotion with ``demoted_at``
  read back from the standing row rather than stamped here.  The ratio is
  *handed over, never derived*: neither coefficient is read by this feature,
  and the caller — the supervisor, which speaks to the forward member —
  obtains it through :func:`forward.retention.forward_ic_retention` (feature
  337) and hands the single number over, the "hand over, never derive"
  barrier the other risk guards hold toward the figures they are handed.
  The module-level spelling — :func:`~risk.demotion.demote_on_ic_drop` —
  opens it from the environment and refuses by name once the ratio has fired
  and nothing names a store; the reader's spelling,
  :func:`~risk.demotion.recorded_demotions`, answers the empty truth on the
  same absence.
* :mod:`risk.demotion_window` — the gate, feature 327: *System requires a
  statistically meaningful observation window before auto-demotion fires,
  which rejects a demotion on a thin sample.*  No table, and that absence
  is the feature: the window is a *judgement*, not a record — the count
  of observed days behind the ratio (feature 337 carries it beside the
  figure as *the evidence for it*), handed over with the ratio and never
  derived here, judged against a ``minimum_observed_days`` the deployment
  states as a required keyword with no default, because the spec says
  *"statistically meaningful"* and names no number.
  :class:`~risk.demotion_window.DemotionWindow` is the value that holds
  both counts and derives the judgement (meaningful at ``>=``, thin
  strictly below), and :func:`~risk.demotion_window.
  demote_over_meaningful_window` is the gated spelling of feature 326's
  act: a held ratio answers ``None`` with the window moot, a firing ratio
  over a thin sample is *rejected* in
  :class:`~risk.errors.RiskDemotionWindowError` with the window riding
  on the error — no row, no store opened, and a rejection that lifts by
  itself as the record accrues days — and a firing ratio over a
  meaningful window demotes by delegating wholesale to
  :func:`~risk.demotion.demote_on_ic_drop`, inheriting first-write-wins
  and the no-store refusal rather than restating them.
* :mod:`risk.feed_staleness` — the watchdog, feature 328: *System rejects
  new orders while holding positions when data feed staleness exceeds the
  configured threshold.*  No table, and that absence is the feature: the
  guard is the *order path's own act on its own submission path*, a live
  judgement re-taken from the socket's last message at the moment a
  submission asks, so it lifts by itself when the feed speaks again
  rather than standing until a door resets it.  :func:`~risk.feed_staleness.
  measure_feed_staleness` is the pure half — two caller-supplied readings,
  their difference, a negative age refused rather than clamped —
  :class:`~risk.feed_staleness.FeedStaleness` is the reading the
  judgement rides on, and :meth:`~risk.feed_staleness.RiskFeedStalenessGuard.
  require_fresh` (with :func:`~risk.feed_staleness.require_feed_fresh` as
  its module-level spelling) is the refusal.  It does not flatten, does
  not send the kill and does not record: §13.3's row for this feature is
  *halt new orders, hold positions*, one row below the daily-loss row
  that owns the flatten, and the retention of measured staleness is
  feature 350's row in the :mod:`ops` member — handed the figure by
  whoever measured it.
* :mod:`risk.daily_loss` — the limit-keeper, feature 325: *System rejects
  new orders until a manual reset once the configured daily loss limit is
  breached.*  A fifth table (``risk_daily_loss_halt``), one row per
  breach, written by :meth:`~risk.daily_loss.RiskDailyLossHaltStore.
  halt_on_loss`, guarded by :meth:`~risk.daily_loss.
  RiskDailyLossHaltStore.require_orders_allowed`, and closed — the
  member's first *liftable* standing state — by
  :meth:`~risk.daily_loss.RiskDailyLossHaltStore.reset`.  The breach is
  strict (``daily_loss > daily_loss_limit``, pinned at equality), the
  limit is a required keyword with no default (the sentence's own word
  for it is *configured*), and the day's loss is handed over, never
  derived.  Deliberately not the channel: the kill is monotone and this
  halt must lift, so it owns its standing state, its guard and its
  reset door, and neither kill nor flatten rides the breach — §13.3's
  *flatten* is this trigger's composed response, the act feature 323's
  door owns, driven from a breach by the end-to-end story that composes
  them.  The module-level spellings —
  :func:`~risk.daily_loss.halt_on_daily_loss` for the supervisor,
  :func:`~risk.daily_loss.require_within_daily_loss_limit` for the
  order layer, :func:`~risk.daily_loss.manual_reset` for the operator,
  :func:`~risk.daily_loss.recorded_daily_loss_halts` for the reconciler
  — open it from the environment and split four ways on its absence:
  the guard passes vacuously and the sweep answers empty, while the
  halt and the reset refuse by name.
* :mod:`risk.errors` — the refusal vocabulary.  One base so a single
  ``except`` catches the member, and twelve nouns apart: the tables'
  shared address and persistence (:class:`~risk.errors.RiskStoreError`),
  the instruction's own terms (:class:`~risk.errors.
  RiskKillSwitchError`), the event's own terms
  (:class:`~risk.errors.RiskHaltEventError`), the order layer's
  receipt (:class:`~risk.errors.RiskOrdersKilledError`, which carries
  the standing instruction), the flatten's own terms
  (:class:`~risk.errors.RiskFlattenError` — a face missing its verbs, a
  flatten under no standing kill, an engine whose re-reading still
  reports something standing), the measurement's own terms
  (:class:`~risk.errors.RiskClockSkewError` — a reading that is naive or
  not a moment, a threshold that states no band, a stored row whose skew
  disagrees with its own two instants or never actually exceeded the band
  it claims, and a halting measurement that could not be recorded), the
  demotion's own terms (:class:`~risk.errors.RiskSignalDemotionError` —
  a node that is not a signal identity, a ratio that is not a number, a
  bound that is not a band, and a stored row no demotion can be
  reconstructed as), the window's own terms
  (:class:`~risk.errors.RiskDemotionWindowError` — a count that is not
  a whole positive number, a minimum that states no requirement, and the
  thin-sample rejection, carrying the window it judged), and
  the watchdog's own terms (:class:`~risk.errors.RiskFeedStalenessError`
  for a reading that is not a reading and
  :class:`~risk.errors.RiskOrdersStaleError` for the order path's receipt,
  a *sibling* of the killed receipt rather than a child of it: the kill is
  a state that stands until a door resets it, the staleness is a live
  reading that stops being true by itself), and the limit-keeper's own
  terms (:class:`~risk.errors.RiskDailyLossError` — a loss that is not a
  loss, a limit nobody configured, a row no halt can be reconstructed as,
  more than one halt standing where the law allows one, and the two
  no-store refusals the feature cannot fail softly in — plus
  :class:`~risk.errors.RiskOrdersHaltedError` for the order path's third
  receipt, carrying the standing halt: a state that does not lift by
  itself but *does* lift, at the reset door, by an operator's act).
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

**The ledger's component is the same reflection, under a second name.**
:data:`HALT_EVENTS_COMPONENT_NAME` registers
:func:`build_halt_event_store` beside the switch — the convention
:mod:`canary` states for its own second and third components, kept for
the reason that member gives: the switch answers *is the order layer
killed?*, the ledger answers *what halted, when, and why?* — two
different questions on two different lifecycles, and a caller asking a
composed application for one must not be handed the other.  The halting
process and the reconciler reach the ledger without composing, exactly
as the channel's two processes do and for the same reason, and the two
doors cannot disagree for the same reason: one class, one URL, one
table.

**The flattener's component is the same reflection, under a third
name.**  :data:`FLATTENER_COMPONENT_NAME` registers
:func:`build_risk_flattener` beside the switch and the ledger — the
same convention :mod:`canary` states for its own third component.  The
reflection carries less here than its siblings do, and that is
instructive: the flattener owns no table, so what the composed object
reflects is the *authority* — the URL the standing kill is read
through — and the engine face still has to be handed to
:meth:`~risk.flatten.RiskFlattener.flatten` by the caller that holds
it, because no composition can supply the supervisor's own hold on the
execution engine (§13.3's *"kill authority"* is a process's fact, not
an application's).  The supervisor process itself reaches the
flattener without composing, exactly as it reaches the switch, and the
two doors cannot disagree for the same reason: one class, one URL, one
channel.

**The watchdog has no component, and the absence is stated rather than
left to be noticed.**  Feature 328 registers nothing beside the four names
above, for two reasons that are each sufficient.  The first is the
*lifecycle*: a component is an object a composed application carries for
as long as the application lives, and this feature's whole judgement is
that the feed is stale *now* — a guard held in an application's registry
would be a guard whose band a deployment set at composition and whose
readings nobody took, while the process that must act on the silence is
the one about to submit, and it must ask the socket at the moment it
asks.  The second is that the *guard needs nothing composed*: the flattener
owns no table and still reflects the URL its kill is read through, but
this guard owns no table *and* holds no store face at all — its band is
configuration and its reading is a last-message instant — so a composed
reflection of it would carry a band and an optional source and answer
nothing a caller could not have constructed on the spot in one line.  The
order path reaches :func:`~risk.feed_staleness.require_feed_fresh` without
composing, exactly as the supervisor reaches the switch, and for the
member's oldest reason: the process this feature must survive is the one
that must not be required to have composed anything.
"""

from __future__ import annotations

from app.module_loader import register

from ._identity import PROCESS_ID_SEPARATOR, process_identity
from .clock_skew import (
    RISK_CLOCK_SKEW_TABLE,
    ClockSkewHalt,
    RiskClockSkewStore,
    halt_on_clock_skew,
    measure_clock_skew,
    measured_clock_skews,
)
from .daily_loss import (
    RISK_DAILY_LOSS_HALT_TABLE,
    DailyLossHalt,
    RiskDailyLossHaltStore,
    halt_on_daily_loss,
    manual_reset,
    orders_halted_error,
    recorded_daily_loss_halts,
    require_within_daily_loss_limit,
)
from .demotion import (
    DEMOTION_BOUND,
    NODE_ID_COLUMN,
    RISK_SIGNAL_DEMOTION_TABLE,
    RiskSignalDemotionStore,
    SignalDemotion,
    demote_on_ic_drop,
    recorded_demotions,
)
from .demotion_window import (
    DemotionWindow,
    demote_over_meaningful_window,
)
from .errors import (
    CLOCK_SKEW_CODE,
    DAILY_LOSS_CODE,
    DEMOTION_WINDOW_CODE,
    FEED_STALENESS_CODE,
    FLATTEN_CODE,
    HALT_EVENT_CODE,
    KILL_INSTRUCTION_CODE,
    ORDERS_HALTED_CODE,
    ORDERS_KILLED_CODE,
    ORDERS_STALE_CODE,
    SIGNAL_DEMOTION_CODE,
    RiskClockSkewError,
    RiskDailyLossError,
    RiskDemotionWindowError,
    RiskError,
    RiskFeedStalenessError,
    RiskFlattenError,
    RiskHaltEventError,
    RiskKillSwitchError,
    RiskOrdersHaltedError,
    RiskOrdersKilledError,
    RiskOrdersStaleError,
    RiskSignalDemotionError,
    RiskStoreError,
)
from .feed_staleness import (
    FALLBACK_FEED_READING_ATTRIBUTES,
    FeedStaleness,
    FeedStalenessGuard,
    FeedStalenessSource,
    RiskFeedStalenessGuard,
    measure_feed_staleness,
    orders_stale_error,
    read_feed_staleness,
    require_feed_fresh,
)
from .flatten import (
    FLATTEN_STATUS_COMPLETED,
    FlattenResult,
    RiskFlattener,
    flatten_positions,
)
from .halt import (
    RISK_HALT_ROUTE,
    HaltEndpoint,
    HaltRequest,
    HaltResponse,
)
from .halt_events import (
    RISK_HALT_EVENT_TABLE,
    HaltEvent,
    RiskHaltEventStore,
    record_halt,
    recorded_halt_events,
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
    "CLOCK_SKEW_CODE",
    "COMPONENT_NAME",
    "DAILY_LOSS_CODE",
    "DATABASE_URL_ENV",
    "DEMOTION_BOUND",
    "DEMOTION_WINDOW_CODE",
    "FALLBACK_FEED_READING_ATTRIBUTES",
    "FEED_STALENESS_CODE",
    "FLATTENER_COMPONENT_NAME",
    "FLATTEN_CODE",
    "FLATTEN_STATUS_COMPLETED",
    "HALT_COMPONENT_NAME",
    "HALT_EVENTS_COMPONENT_NAME",
    "HALT_EVENT_CODE",
    "KILL_INSTRUCTION",
    "KILL_INSTRUCTION_CODE",
    "NODE_ID_COLUMN",
    "ORDERS_HALTED_CODE",
    "ORDERS_KILLED_CODE",
    "ORDERS_STALE_CODE",
    "PROCESS_ID_SEPARATOR",
    "RISK_CLOCK_SKEW_TABLE",
    "RISK_DAILY_LOSS_HALT_TABLE",
    "RISK_HALT_EVENT_TABLE",
    "RISK_HALT_ROUTE",
    "RISK_ORDER_KILL_TABLE",
    "RISK_SIGNAL_DEMOTION_TABLE",
    "SIGNAL_DEMOTION_CODE",
    "ClockSkewHalt",
    "DailyLossHalt",
    "DemotionWindow",
    "FeedStaleness",
    "FeedStalenessGuard",
    "FeedStalenessSource",
    "FlattenResult",
    "HaltEndpoint",
    "HaltEvent",
    "HaltRequest",
    "HaltResponse",
    "KillInstruction",
    "RiskClockSkewError",
    "RiskClockSkewStore",
    "RiskDailyLossError",
    "RiskDailyLossHaltStore",
    "RiskDemotionWindowError",
    "RiskError",
    "RiskFeedStalenessError",
    "RiskFeedStalenessGuard",
    "RiskFlattenError",
    "RiskFlattener",
    "RiskHaltEventError",
    "RiskHaltEventStore",
    "RiskKillSwitch",
    "RiskKillSwitchError",
    "RiskOrdersHaltedError",
    "RiskOrdersKilledError",
    "RiskOrdersStaleError",
    "RiskSignalDemotionError",
    "RiskSignalDemotionStore",
    "RiskStoreError",
    "SignalDemotion",
    "demote_on_ic_drop",
    "demote_over_meaningful_window",
    "flatten_positions",
    "halt_on_clock_skew",
    "halt_on_daily_loss",
    "manual_reset",
    "measure_clock_skew",
    "measure_feed_staleness",
    "measured_clock_skews",
    "orders_halted_error",
    "orders_killed_error",
    "orders_stale_error",
    "process_identity",
    "read_feed_staleness",
    "record_halt",
    "recorded_daily_loss_halts",
    "recorded_demotions",
    "recorded_halt_events",
    "require_feed_fresh",
    "require_orders_allowed",
    "require_within_daily_loss_limit",
    "send_kill",
]

__version__ = "0.1.0"

#: The component name this member's first component registers under —
#: unprefixed, following the ``router`` / ``book`` / ``canary`` precedent
#: for a member's first component, so the member, its seat in
#: ``app.modules.risk`` and the spec's ``plugin="risk"`` share one
#: spelling they cannot drift from silently.  The member's suite asserts
#: the two agree.
COMPONENT_NAME = "risk"

#: The component name the halt event ledger registers under — a second
#: name beside :data:`COMPONENT_NAME`, the convention :mod:`canary` states
#: for its own ``canary-dream-halt`` and that member's reason for it: the
#: switch answers *is the order layer killed?* and the ledger answers
#: *what halted, when, and why?* — two different questions on two
#: different lifecycles, and a caller asking a composed application for
#: one must not be handed the other.
HALT_EVENTS_COMPONENT_NAME = "risk-halt-events"

#: The component name the flattener registers under — a third name
#: beside the switch and the ledger, the convention :mod:`canary` states
#: for its own second and third components: the switch answers *is the
#: order layer killed?*, the ledger answers *what halted, when, and
#: why?*, and the flattener answers *flatten now* — three different
#: questions, and a caller asking a composed application for one must
#: not be handed another's verb.
FLATTENER_COMPONENT_NAME = "risk-flattener"

#: The component name the halt door registers under — a fourth name beside the
#: switch, the ledger and the flattener, the convention :mod:`canary` states
#: for registering an endpoint beside its store (as :mod:`ledger` registers
#: ``ledger-debit`` beside its store): the switch answers *is the order layer
#: killed?*, the ledger answers *what halted, when, and why?*, the flattener
#: answers *flatten now*, and the halt door answers *halt* — the composed act
#: of the kill and the flatten driven in order, and a caller asking a composed
#: application for that act must not be handed one of its halves.
HALT_COMPONENT_NAME = "risk-halt"


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


@register(HALT_EVENTS_COMPONENT_NAME)
def build_halt_event_store() -> RiskHaltEventStore | None:
    """Component builder: the halt event ledger bound to ``DATABASE_URL``.

    The same reflection, under the ledger's own name (see
    :data:`HALT_EVENTS_COMPONENT_NAME`): takes no arguments, resolves
    ``DATABASE_URL`` at build time, and returns ``None`` when nothing
    names a store — the same stance the switch's builder takes, for the
    same reason.  Construction performs no I/O: the schema is created on
    the first :meth:`~risk.halt_events.RiskHaltEventStore.record` or
    read, so composing the application never touches a database.

    What the composed ledger is *for* is the mirror of the switch's
    answer: a caller that asks a composed application for the record by
    name.  The halting process and the reconciler reach the same ledger
    without composing — see :mod:`risk.halt_events` for the two
    module-level spellings they use instead.
    """
    return RiskHaltEventStore.resolve()


@register(FLATTENER_COMPONENT_NAME)
def build_risk_flattener() -> RiskFlattener | None:
    """Component builder: the flattener bound to ``DATABASE_URL``.

    The same reflection, under the flattener's own name (see
    :data:`FLATTENER_COMPONENT_NAME`): takes no arguments, resolves
    ``DATABASE_URL`` at build time, and returns ``None`` when nothing
    names a store — the same stance the switch's and the ledger's
    builders take, for the same reason.  Construction performs no I/O
    and creates nothing: the flattener owns no table, so there is no
    schema to bring into being, and the first
    :meth:`~risk.flatten.RiskFlattener.flatten` is where the channel's
    row is read through the switch the flattener holds.

    What the composed flattener is *for* is stated in this module's
    docstring: a reflection of the authority, for callers that ask a
    composed application for the flatten verb by name.  The supervisor
    process reaches the same flattener without composing — see
    :mod:`risk.flatten` for the module-level spelling it uses instead —
    and still hands :meth:`~risk.flatten.RiskFlattener.flatten` the
    execution engine face itself, because no composition can supply the
    supervisor's own hold on the engine.
    """
    return RiskFlattener.resolve()


@register(HALT_COMPONENT_NAME)
def build_risk_halt() -> HaltEndpoint | None:
    """Component builder: the halt door bound to ``DATABASE_URL``.

    The same reflection, under the halt door's own name (see
    :data:`HALT_COMPONENT_NAME`): resolves the switch and the flattener from
    ``DATABASE_URL`` at build time — exactly as the switch's and flattener's
    builders do, so the door and the composed components point at the same
    database — and returns ``None`` when nothing names a store, the
    degrade-don't-break stance every builder in this workspace takes.
    Construction performs no I/O: the schema is created on the first send or
    flatten, so composing the application never touches a database.

    What the composed halt door is *for* is the composed act of feature 322's
    kill and feature 330's flatten, driven in order — the one place they meet.
    The supervisor process reaches the same door without composing — see
    :mod:`risk.halt` for the module-level spelling it uses instead — and still
    hands :meth:`~risk.halt.HaltEndpoint.post` the execution engine itself,
    because no composition can supply the supervisor's own hold on the engine.
    """
    switch = RiskKillSwitch.resolve()
    flattener = RiskFlattener.resolve()
    if switch is None or flattener is None:
        return None
    return HaltEndpoint(switch, flattener)
