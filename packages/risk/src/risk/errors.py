"""The risk member's error taxonomy.

One base class (:class:`RiskError`) so a caller — the supervisor process
sending a kill instruction, the order layer consulting the switch, the
reconciler sweeping the halt event ledger — can catch every failure of
this package with a single ``except``.  The subclasses split by *which
contract* was violated, not by which line of code failed:

* :class:`RiskStoreError` — the address and persistence contract the
  member's tables share.  Feature 322's kill instruction and feature
  331's halt events both travel through the workspace's relational store
  (``DATABASE_URL``), so a URL this member cannot speak, or a row that
  could not be written and read back, is an error rather than a shrug:
  the alternative is a supervisor that believes it has killed the order
  layer while the instruction went nowhere — exactly the state §13.3's
  *"so a hung strategy process cannot prevent a flatten"* exists to rule
  out — or a halt that happened while the record of it vanished, which
  is the hole a later reconciliation would read as a window where
  nothing halted.  A store that is merely *absent* (no ``DATABASE_URL``)
  is not this error: see :mod:`risk.kill` and :mod:`risk.halt_events`
  for the stance that splits the two directions each feature's absence
  cuts.
* :class:`RiskKillSwitchError` — feature 322's own noun, the *kill
  instruction* itself: a send whose moment states no time or whose label
  names no process, a module-level send that names no store to send
  through, and a stored row no instruction can be reconstructed as.  A
  sibling of :class:`RiskStoreError` rather than a child of it, because the
  repairs differ — *point the deployment at a database this member can
  open* against *fix the ask or the row* — and a caller told the wrong one
  would edit the wrong file while the order layer kept trading.
* :class:`RiskHaltEventError` — feature 331's own noun, the *halt
  event*: a trigger reason that states nothing, a timestamp that states
  no time, a stored row no event can be reconstructed as, and a
  module-level record that names no store to record through.  A sibling
  of :class:`RiskKillSwitchError` for the same reason that class is a
  sibling of the store error — the ledger's repair is never the
  channel's — and like it, reserved for the faults whose noun is the
  record's own terms rather than the store's address.
* :class:`RiskOrdersKilledError` — the order layer's receipt of the kill,
  raised by the guard (:func:`risk.require_orders_allowed`) when a kill
  instruction stands, and the one class in this module that carries a
  value: the standing :class:`~risk.kill.KillInstruction` rides on its
  ``instruction`` attribute, because *"which process killed us, and
  when?"* is the first question the operator of a killed order layer asks
  and the refusal is where they will look for it.
* :class:`RiskFlattenError` — feature 330's own noun, the *flatten*: an
  execution engine face missing the verbs the flatten drives, a flatten
  attempted under no standing kill, an engine whose own re-reading
  reports something still standing after the flatten drove it, and a
  module-level flatten that names no store to read the authority from.
  A sibling of the others rather than a child of any, for the reason the
  others are siblings: the noun is the flatten, not the instruction, not
  the event and not the store's address — and a caller sent from a
  residue to a bad ``DATABASE_URL`` would go and edit the deployment
  while the engine still reported the very exposure the refusal named.
* :class:`RiskClockSkewError` — feature 329's own noun, the *measured
  clock skew that halted trading*: a probe reading that is naive or not a
  moment at all, a threshold that states no band (not real, not finite,
  not strictly positive), a stored row whose skew disagrees with its own
  two instants or never actually exceeded the band it claims, a
  module-level halt that names no store to record through, and a halting
  measurement that exceeded the band but could not be persisted.  A
  sibling of the others for the same reason they are siblings of each
  other: the noun is the *measurement*.  The clock's faults are the one
  family in this module that may arrive *after* the halt has already
  fired — the kill went out and the record of why is what failed — which
  is why the refusal names the skew and the band rather than the row.
* :class:`RiskFeedStalenessError` — feature 328's own noun, the *data
  feed staleness* the order layer is refused on: a reading that is naive
  or not a moment at all, a feed whose last message is stamped after the
  reading that asked how long it had been silent (a negative age is not a
  silence), a threshold that states no band (not real, not finite, not
  strictly positive), and a live reading whose age disagrees with its own
  two instants or never actually exceeded the band it was refused under.
* :class:`RiskSignalDemotionError` — feature 326's own noun, the *signal
  demotion* the supervisor persists when a promoted signal's live
  information coefficient falls below 40 percent of its backtest one: a
  node that is not a signal identity, a retention ratio that is not a
  number, a bound that is not a band (not real, not finite, not strictly
  positive), a stored row no demotion can be reconstructed as (a ratio
  that is not below the bound it claims to have fallen below), and a
  module-level demote that names no store to record through while the
  ratio fired.  A sibling of :class:`RiskStoreError` for the same reason
  :class:`RiskClockSkewError` is — the noun is the *measurement*, not the
  channel and not the store's address, and a caller sent from a malformed
  ratio to a bad ``DATABASE_URL`` would go and edit the deployment while
  the ratio stayed malformed.
  A sibling of the others, and of :class:`RiskClockSkewError`
  particularly — one duration is measured against a *band* and the other
  against the *venue's clock*, and a caller sent from one to the other
  would go and edit the wrong reading.  It is also where the malformed
  *ask* lands, because the staleness is judged at submission and there is
  no row downstream of the judgement to carry the fault.
* :class:`RiskOrdersStaleError` — the order layer's receipt of feature
  328's refusal: the feed has been silent past the configured band, so
  new order submission is refused, and it carries the
  :class:`~risk.feed_staleness.FeedStaleness` reading that refused it.
  The sibling :class:`RiskOrdersKilledError` is to feature 322's standing
  kill what this is to feature 328's live reading: the same kind of
  object — a refusal the order path catches by type — over the other kind
  of condition (a state that stands against a reading that is
  re-judged on every submission), which is why the two are told apart by
  class rather than by a flag on one of them: an operator paging on one
  performs a different repair than an operator paging on the other.

Every message names the offending value and the contract it broke, and
the feature classes open with their greppable tokens
(:data:`KILL_INSTRUCTION_CODE`, :data:`ORDERS_KILLED_CODE`,
:data:`HALT_EVENT_CODE`, :data:`FLATTEN_CODE`, :data:`CLOCK_SKEW_CODE`,
:data:`FEED_STALENESS_CODE`, :data:`ORDERS_STALE_CODE`,
:data:`SIGNAL_DEMOTION_CODE`)
so an operator scanning a log for the member's refusals greps one word
rather than a sentence — the same discipline the
``order_submission_unhealthy`` (feature 320) and ``determinism_broken``
(feature 143) tokens state for their own features.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only; both are one-way imports
    from .feed_staleness import FeedStaleness
    from .kill import KillInstruction

__all__ = [
    "CLOCK_SKEW_CODE",
    "FEED_STALENESS_CODE",
    "FLATTEN_CODE",
    "HALT_EVENT_CODE",
    "KILL_INSTRUCTION_CODE",
    "ORDERS_KILLED_CODE",
    "ORDERS_STALE_CODE",
    "SIGNAL_DEMOTION_CODE",
    "RiskClockSkewError",
    "RiskError",
    "RiskFeedStalenessError",
    "RiskFlattenError",
    "RiskHaltEventError",
    "RiskKillSwitchError",
    "RiskOrdersKilledError",
    "RiskOrdersStaleError",
    "RiskSignalDemotionError",
    "RiskStoreError",
]

#: The greppable token every :class:`RiskKillSwitchError` message opens
#: with — the spec's own noun phrase, app_spec.xml feature 322: *"which
#: sends a kill instruction to the order layer"*.  An operator scanning a
#: log for the kill channel's faults greps ``kill_instruction`` and finds
#: the malformed asks and the unreadable rows, one grep apart from the
#: order layer's refusals (:data:`ORDERS_KILLED_CODE`, which name the
#: *consequence*, not the channel).  It deliberately does not spell
#: ``supervisor``: the faults in this class are as often the order layer's
#: reads as the supervisor's sends, and a token naming the sender would
#: send an operator grepping for faults to the rows that worked.
KILL_INSTRUCTION_CODE = "kill_instruction"

#: The greppable token every :class:`RiskOrdersKilledError` message opens
#: with.  It names the state the order layer is refusing under — *orders
#: killed* — rather than the channel that set it, so a caller grepping
#: their own order path's refusals finds the kill's receipt without also
#: finding the channel's bookkeeping faults.  It deliberately does not
#: spell ``halt``: halting is feature 323's verb (its own door, its own
#: vocabulary), and a kill instruction that stands is not yet a halt
#: semantics — it is the instruction the halt features will act on.
ORDERS_KILLED_CODE = "orders_killed"

#: The greppable token every :class:`RiskHaltEventError` message opens
#: with — the spec's own noun, app_spec.xml feature 331: *"System
#: persists every halt event with its trigger reason and timestamp for
#: later reconciliation"*.  An operator scanning a log for the ledger's
#: faults greps ``halt_event`` and finds the reasons that stated nothing
#: and the rows no event can be reconstructed as — a grep apart from the
#: channel's (:data:`KILL_INSTRUCTION_CODE`) and from the order layer's
#: receipt (:data:`ORDERS_KILLED_CODE`), because the ledger's faults are
#: neither the send's nor the refusal's: they are the record's own.
HALT_EVENT_CODE = "halt_event"

#: The greppable token every :class:`RiskFlattenError` message opens with
#: — the spec's own noun, app_spec.xml feature 330: *"System flattens
#: successfully even when the strategy process is hung, which returns a
#: completed flatten result."*  An operator scanning a log for the
#: flatten's faults greps ``flatten`` and finds the faces that were
#: missing verbs, the flattens attempted under no standing kill, and the
#: residues the engine still reported — a grep apart from the channel's
#: (:data:`KILL_INSTRUCTION_CODE`), the ledger's (:data:`HALT_EVENT_CODE`)
#: and the order layer's receipt (:data:`ORDERS_KILLED_CODE`), because
#: the flatten's faults are the *act's*: the authority was read, the
#: channel worked, and the engine is the thing still holding exposure.
FLATTEN_CODE = "flatten"

#: The greppable token every :class:`RiskClockSkewError` message opens
#: with — the spec's own noun, app_spec.xml feature 329: *"System persists
#: the measured clock skew that halted trading when it exceeded the
#: threshold against exchange server time."*  An operator scanning a log
#: for the clock's faults greps ``clock_skew`` and finds the probes that
#: could not be measured, the bands that were not bands, and the halts
#: that exceeded their threshold but could not be written — a grep apart
#: from the channel's (:data:`KILL_INSTRUCTION_CODE`), the ledger's
#: (:data:`HALT_EVENT_CODE`), the flatten's (:data:`FLATTEN_CODE`) and
#: the order layer's receipt (:data:`ORDERS_KILLED_CODE`), because the
#: clock's faults are the *measurement's*: the halt may well have fired,
#: and what failed is the record of how far off the clock was.
CLOCK_SKEW_CODE = "clock_skew"

#: The greppable token every :class:`RiskFeedStalenessError` message opens
#: with — the spec's own noun, app_spec.xml feature 328: *"System rejects
#: new orders while holding positions when data feed staleness exceeds the
#: configured threshold."*  An operator scanning a log for the feed's
#: faults greps ``feed_staleness`` and finds the readings that stated no
#: instant, the ages that ran backwards, the bands that were not bands
#: and the live rows a reader cannot stand behind — a grep apart from the
#: clock's (:data:`CLOCK_SKEW_CODE`), the channel's
#: (:data:`KILL_INSTRUCTION_CODE`), the ledger's
#: (:data:`HALT_EVENT_CODE`), the flatten's (:data:`FLATTEN_CODE`) and
#: the order layer's two receipts, because the feed's faults are the
#: *staleness reading's*: the band may well be exceeded, and what failed
#: is the measurement of how long the socket has been quiet.
FEED_STALENESS_CODE = "feed_staleness"

#: The greppable token every :class:`RiskOrdersStaleError` message opens
#: with.  It names the state the order path is refusing under — *orders
#: stale* — rather than the reading that produced it, the split
#: :data:`ORDERS_KILLED_CODE` states against
#: :data:`KILL_INSTRUCTION_CODE`: a caller grepping its own order path's
#: refusals finds the feed's receipt without also finding the reader's
#: bookkeeping faults.  It deliberately does not spell ``halt`` —
#: feature 328's action is *halt new orders, hold positions*, and the
#: word ``halt`` belongs to feature 323's door, which sends a kill and
#: flattens; a refusal that stopped new orders while leaving the book
#: standing is not that act, and a token that borrowed its word would
#: send an operator looking for a flatten that never happened.
ORDERS_STALE_CODE = "orders_stale"

#: The greppable token every :class:`RiskSignalDemotionError` message opens
#: with — the spec's own noun, app_spec.xml feature 326: *"System persists
#: an automatic demotion when live information coefficient falls below 40
#: percent of its backtest value."*  An operator scanning a log for the
#: demotion's faults greps ``signal_demotion`` and finds the nodes that
#: were not signal identities, the ratios that were not numbers, the bounds
#: that were not bands, and the stored rows a demotion could not be
#: reconstructed as — a grep apart from the clock's
#: (:data:`CLOCK_SKEW_CODE`), the channel's (:data:`KILL_INSTRUCTION_CODE`)
#: and the store's address (:class:`~risk.errors.RiskStoreError`), because
#: the demotion's faults are the *measurement's*: the ratio may well be
#: below the bound, and what failed is the record of how far the live IC had
#: fallen below the backtest one.
SIGNAL_DEMOTION_CODE = "signal_demotion"


class RiskError(Exception):
    """Base class for every failure of the risk package."""


class RiskStoreError(RiskError):
    """The member's persisted record could not be written or read back.

    app_spec.xml, "Risk Supervisor & Kill Switches", feature 322: *"System
    runs the risk supervisor as a separate process, which sends a kill
    instruction to the order layer"* — and feature 331: *"System persists
    every halt event with its trigger reason and timestamp for later
    reconciliation."*  Both sentences are kept by the workspace's
    relational store (``DATABASE_URL``), so this is the failure of that
    medium itself: a URL whose scheme this member cannot speak, or a row
    that could not be written and read back within one operation.
    Raised rather than swallowed — a kill instruction that resolved but
    was never persisted is exactly the gap between a supervisor that
    believes it has killed the order layer and an order layer still
    trading, and a halt event that was never persisted is the hole a
    later reconciliation would read as a window where nothing halted.

    A store that is merely *absent* is not this error, for the same reason
    :class:`router.errors.RouterStoreError` takes that stance: an
    unconfigured deployment is a discoverable state, and the refusal
    belongs to the caller that demands a channel or a ledger anyway —
    see :mod:`risk.kill` and :mod:`risk.halt_events` for how each
    feature's two directions split on that absence.
    """


class RiskKillSwitchError(RiskError):
    """A kill instruction this module cannot send, or reconstruct.

    app_spec.xml feature 322's noun is the *kill instruction*, and this is
    the failure of that noun's own terms: a ``sent_at`` that is naive or
    not a moment at all (an instruction that cannot say when it was sent
    cannot be ordered against anything, least of all the reconciliation
    feature 331 will run), a ``supervisor_process_id`` that names no
    process (an instruction with no sender is unauditable at exactly the
    moment an operator asks *"who killed us?"*), a module-level
    :func:`risk.send_kill` that names no store to send through (the one
    refusal this class makes that is about the *deployment* rather than
    the terms, and the one direction this channel must not fail softly
    in), and a stored row wearing a word other than ``kill`` or a moment
    no parser accepts (a row no instruction can be is not an instruction
    that happens to be quiet).

    A sibling of :class:`RiskStoreError` rather than a child of it: the
    noun is the instruction, not the channel.  A caller sent from a bad
    ask to a bad address would go and edit ``DATABASE_URL`` while the
    malformed send stayed malformed — and the next send would fail the
    same way, on a channel that was fine.

    Every message opens with :data:`KILL_INSTRUCTION_CODE` and names the
    offending value, because the audience is whichever process is holding
    the wrong end of the instruction, and the repair is a term, not a
    stack trace.
    """


class RiskHaltEventError(RiskError):
    """A halt event this module cannot record, or reconstruct.

    app_spec.xml feature 331's noun is the *halt event*, and this is the
    failure of that noun's own terms: a ``trigger_reason`` that states
    nothing (an event that cannot say why it fired is unauditable at
    exactly the moment a reconciliation asks), a ``triggered_at`` that is
    naive or not a moment at all (an event that cannot say when it
    happened cannot take its place in the sweep this feature's second
    half exists for), a module-level :func:`risk.record_halt` that names
    no store to record through (the one refusal this class makes that is
    about the *deployment* rather than the terms, and the one direction
    this ledger must not fail softly in — the reconciler's direction
    answers an empty tuple on the same absence), and a stored row wearing
    a moment no parser accepts, a reason that states nothing, or a
    sequence the ledger never minted (a row no event can be is not an
    event that happens to be quiet — it is a hole in the record, and the
    read refuses it rather than skipping it, because completeness is this
    table's law).

    A sibling of :class:`RiskKillSwitchError` rather than a child of it,
    for the reason that class is a sibling of :class:`RiskStoreError`:
    the noun is the event, not the instruction and not the channel.  A
    caller sent from a bad reason to a bad address would go and edit
    ``DATABASE_URL`` while the reasonless record stayed reasonless — and
    the next halt would fail the same way, on a ledger that was fine.

    Every message opens with :data:`HALT_EVENT_CODE` and names the
    offending value, because the audience is whichever process is holding
    the wrong end of the event — the supervisor that could not record
    it, or the reconciler that could not read it back.
    """


class RiskOrdersKilledError(RiskError):
    """A kill instruction stands; the order layer refuses to trade.

    app_spec.xml feature 322: *"System runs the risk supervisor as a
    separate process, which sends a kill instruction to the order
    layer."*  This is that instruction's arrival, made catchable by type:
    the order layer's guard (:func:`risk.require_orders_allowed`) raises
    it when the switch it consults holds a standing kill, and every
    submission path that consults the guard refuses through it rather
    than through a boolean it would have to enforce at each call site.

    **It carries the instruction.**  :attr:`instruction` is the standing
    :class:`~risk.kill.KillInstruction` the guard read — which process
    sent the kill, and when — so the caller that must act on the refusal
    learns *who killed us* and *how long we have been killed* without a
    second query.  That is why this class carries a value at all, where
    its siblings carry only messages: the refusal's own payload is
    the feature's output, the same stance :class:`canary.
    CanaryDeterminismBrokenError` takes for the halt record it carries,
    and :class:`router.errors.RouterRateLimitedError` for its headroom.

    A sibling of :class:`RiskStoreError` and :class:`RiskKillSwitchError`
    rather than a child of either: this is not the channel failing to
    persist and not the ask arriving malformed — it is the channel
    working, the ask well-formed, and the order layer doing what the
    instruction it received requires.  A caller catching the base
    (:class:`RiskError`) catches it along with the channel's faults; a
    caller that must *trade* catches this class and stops.

    Every message opens with :data:`ORDERS_KILLED_CODE` and names the
    sending process and the moment it sent, because the operator paging
    on a killed order layer asks those two questions first.
    """

    #: The standing instruction the guard read.  Present on every error
    #: the guard raises; ``None`` only on a hand-built error with no
    #: instruction behind it.
    instruction: KillInstruction | None

    def __init__(
        self, message: str, instruction: KillInstruction | None = None
    ) -> None:
        super().__init__(message)
        self.instruction = instruction


class RiskFlattenError(RiskError):
    """A flatten this module cannot drive to completion — or cannot start.

    app_spec.xml feature 330's noun is the *flatten result*, and this is
    the failure of that noun's own terms: an execution engine face
    missing one of the four verbs the flatten drives (a face the
    supervisor cannot talk to cannot be ordered flat), a flatten
    attempted while no kill instruction stands on the channel (the
    flatten is the drainage of feature 322's authority, and acting
    without it would race the very submissions that authority exists to
    stop), an engine fault or a residue — the engine's own re-reading
    still reporting an order standing or a position open after the
    flatten drove everything it was shown (a completed result returned
    over a residue would be the one lie this feature exists to make
    impossible), and a module-level :func:`risk.flatten_positions` that
    names no store to read the authority from (the one refusal this
    class makes that is about the *deployment* rather than the terms,
    and the one direction of the flatten's absence that must not fail
    softly — there is no other direction, because the order layer is who
    the flatten acts *on*, not a caller of it).

    A sibling of :class:`RiskKillSwitchError`,
    :class:`RiskHaltEventError` and :class:`RiskOrdersKilledError`
    rather than a child of any: the noun is the flatten.  A caller sent
    from a missing verb to a bad address would go and edit
    ``DATABASE_URL`` while the face stayed verbless — and the next
    flatten would fail the same way, over a channel that was fine.

    It carries no value, where :class:`RiskOrdersKilledError` carries
    the instruction: the operator's recovery from a flatten refusal is
    not held in the refusal — it is to flatten again, and the next
    sweep's own enumeration of the engine is the truthful picture of
    what remains (see :mod:`risk.flatten` for the recovery protocol the
    refusal message states).

    Every message opens with :data:`FLATTEN_CODE` and names the
    offending value, because the audience is the supervisor process
    holding a book that is still open, and the repair is an act, not a
    stack trace.
    """


class RiskClockSkewError(RiskError):
    """A clock-skew measurement this module cannot judge, or reconstruct.

    app_spec.xml feature 329's noun is the *measured clock skew that
    halted trading*, and this is the failure of that noun's own terms: a
    probe reading that is naive or not a moment at all (a skew measured
    against an ambiguous instant is a skew against no instant, and the
    halt it caused could not be ordered against anything), a
    ``threshold_seconds`` that states no band — not a real number, not
    finite, or not strictly positive, the last of which is a supervisor
    that would halt on every probe rather than on a clock fault — a
    ``measured_skew_seconds`` that disagrees with the two instants beside
    it (the readings *are* the measurement, so a row where they disagree
    is one no halt can be reconstructed as), a stored row whose skew did
    not actually exceed its own band (a probe inside the band is not a
    halt, and a row filed for one reports a halt that never fired), a
    record whose sequence is not one the table minted, a
    module-level :func:`risk.halt_on_clock_skew` that names no store to
    record through (the one refusal this class makes that is about the
    *deployment* rather than the terms), and a halting measurement that
    exceeded the band but could not be persisted (a halt with nothing on
    disk to account for it is indistinguishable from a supervisor that
    died for an unrelated reason, which is the hole this feature exists
    to fill).

    A sibling of :class:`RiskStoreError` rather than a child of it, and a
    sibling of :class:`RiskKillSwitchError`, :class:`RiskHaltEventError`
    and :class:`RiskFlattenError` for the same reason they are siblings
    of each other: the noun is the *measurement*, not the channel and not
    the store's address.  A caller sent from a malformed probe to a bad
    ``DATABASE_URL`` would go and edit the deployment while the clock
    stayed off, and the next skew would fail the same way on a channel and
    a table that were both fine.

    Every message opens with :data:`CLOCK_SKEW_CODE` and names the
    offending value, because the audience is the supervisor process
    holding a clock it cannot trust, and the repair is a reading, a band
    or a deployment — not a stack trace.
    """


class RiskSignalDemotionError(RiskError):
    """A signal demotion this module cannot judge, or reconstruct.

    app_spec.xml feature 326's noun is the *signal demotion* — the
    supervisor's persisted decision that a promoted signal no longer holds
    its promotion, because its live information coefficient has fallen
    below 40 percent of the backtest coefficient it was promoted on — and
    this is the failure of that noun's own terms: a ``node_id`` that is not
    a signal identity (a demotion about a signal that cannot be named is
    unattributable), a retention ratio that is not a number — not a real,
    not finite, or a ``bool`` dressed as one (a ratio that is not one
    number leaves the 40-percent comparison with no operand), a
    ``demotion_bound`` that states no band — not real, not finite, or not
    strictly positive, the last of which is a supervisor that would demote
    on every signal rather than on a fallen one — a stored row whose ratio
    did not actually fall below the bound it claims (a signal at or above
    the bound is not demoted, and a row filed for one reports a demotion
    that never fired), and a module-level :func:`risk.demote_on_ic_drop`
    that names no store to record through while the ratio fired (the one
    refusal this class makes that is about the *deployment* rather than the
    terms, and the one direction this demotion must not fail softly in — a
    demotion that left no record is a demotion the next cycle cannot tell
    from a signal that was never judged).

    A sibling of :class:`RiskStoreError` rather than a child of it, and a
    sibling of :class:`RiskClockSkewError` for the same reason they are
    siblings of each other: the noun is the *measurement*, not the channel
    and not the store's address.  A caller sent from a malformed ratio to a
    bad ``DATABASE_URL`` would go and edit the deployment while the ratio
    stayed malformed, and the next demotion would fail the same way, on a
    channel and a table that were both fine.

    Every message opens with :data:`SIGNAL_DEMOTION_CODE` and names the
    offending value, because the audience is the supervisor process holding
    a signal it has just demoted, and the repair is a ratio, a band or a
    deployment — not a stack trace.
    """


class RiskFeedStalenessError(RiskError):
    """A feed-staleness reading this module cannot judge, or stand behind.

    app_spec.xml feature 328's noun is the *data feed staleness*, and this
    is the failure of that noun's own terms: a reading or a last-message
    instant that is naive or not a moment at all (an age measured from an
    ambiguous instant is an age against no instant, and the refusal it
    caused could not be ordered against anything), a last message stamped
    *after* the reading that asked how long the feed had been silent (an
    age that runs backwards is not a silence — it is a reading from a
    different clock or a different feed, and a negative age would quietly
    pass every band), a ``threshold_seconds`` that states no band — not a
    real number, not finite, or not strictly positive, the last of which
    is a deployment that would refuse every submission rather than a
    silent feed — a reading whose own ``staleness_seconds`` disagrees with
    the two instants beside it (the readings *are* the measurement, so a
    reading where they disagree is one no refusal can be reconstructed
    as) or whose ``exceeded`` bit disagrees with the band it states.  It
    is also where a malformed *source* lands: a feed liveness object that
    can say when the feed's most recent message arrived under no name this
    module knows, and a guard built with a band and nothing to read from.

    A sibling of :class:`RiskClockSkewError` particularly, and of the
    others for the same reason they are siblings of each other: the noun
    is the *duration*, not the venue's clock offset, not the instruction,
    not the record and not the store's address.  The two durations are
    measured against different things — feature 329 against the
    *exchange server's own reading of one probe*, feature 328 against
    *this process's reading of how long ago the last message was* — and a
    caller sent from one to the other would go and edit the wrong
    reading: a clock that has drifted is repaired with ``ntpd``, a socket
    that has gone quiet with a reconnect.

    Unlike the clock's family, this class is also where a malformed *ask*
    lands, and that asymmetry is the feature rather than an oversight: a
    staleness refusal is a judgement, not a record, so there is no row
    downstream of it to carry the fault — and a submission that was
    refused under a band nobody could evaluate must be refused, not
    waved through, because the alternative is trading on a feed whose
    silence cannot be bounded.

    Every message opens with :data:`FEED_STALENESS_CODE` and names the
    offending value, because the audience is the order path that was
    about to submit under a feed it cannot vouch for, and the repair is a
    reading, a band or a reconnect — not a stack trace.
    """


class RiskOrdersStaleError(RiskError):
    """The data feed has been silent past the band; the order path refuses.

    app_spec.xml feature 328: *"System rejects new orders while holding
    positions when data feed staleness exceeds the configured threshold."*
    ``docs/nullius-tech-architecture.md`` §13.3 line 724 fixes the action
    in four words — *"Halt new orders, hold positions"* — to be read
    against the row above it, whose action is *"Flatten, halt until manual
    reset"*: the feed going quiet is not a reason to sell a book, it is a
    reason to stop adding to it.  So this is that refusal, made catchable
    by type: the order layer's guard
    (:func:`risk.require_feed_fresh`) raises it when the reading it took
    exceeded the band, and every submission path that consults the guard
    refuses through it rather than through a boolean it would have to
    enforce at each call site.

    **It carries the reading.**  :attr:`staleness` is the
    :class:`~risk.feed_staleness.FeedStaleness` the guard measured — how
    long the feed had been silent, the band it exceeded — so the caller
    that must act on the refusal learns *how stale* and *against what
    band* without a second query, the same stance
    :class:`RiskOrdersKilledError` takes toward the instruction it
    carries.  That is why this class carries a value where most of its
    siblings carry only messages: the reading's own numbers are the
    feature's output, and an operator triaging a stalled socket needs
    them in the log line the refusal produces.

    A sibling of :class:`RiskOrdersKilledError` rather than a child or a
    special case of it, because the two refusals are answers to different
    questions and need different repairs.  The kill is a *state that
    stands* — one row, first-write-wins, monotone, cleared by nobody in
    this member — and the repair is an operator's act through the door
    that owns a reset.  The staleness is a *live reading of another
    process's liveness*, and it stops being true by itself: the moment
    the feed speaks again the very next guard call passes.  Collapsing
    them into one class would mean an operator could not tell *"a
    supervisor told us to stop"* from *"our own socket has gone quiet"* —
    which is the distinction feature 320's docstring exists to keep
    visible from the other side (*"a router that never receives a quote
    but keeps placing accepted orders reports healthy, because that is
    the truth about order submission"*: the feed's health and the order
    path's health are two facts, and here the feed's fact is what the
    order path refuses on).

    Every message opens with :data:`ORDERS_STALE_CODE` and names the
    staleness, the band and the last message's own instant, because the
    operator paging on a refused order path asks *how long has it been
    quiet* and *since when* first.
    """

    #: The staleness reading the guard measured.  Present on every error
    #: the guard raises; ``None`` only on a hand-built error with no
    #: reading behind it.
    staleness: FeedStaleness | None

    def __init__(self, message: str, staleness: FeedStaleness | None = None) -> None:
        super().__init__(message)
        self.staleness = staleness
