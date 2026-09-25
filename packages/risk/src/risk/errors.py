"""The risk member's error taxonomy.

One base class (:class:`RiskError`) so a caller — the supervisor process
sending a kill instruction, the order layer consulting the switch — can
catch every failure of this package with a single ``except``.  The
subclasses split by *which contract* was violated, not by which line of
code failed:

* :class:`RiskStoreError` — the channel's address and persistence
  contract.  Feature 322's kill instruction travels through the workspace's
  relational store (``DATABASE_URL``), so a URL this member cannot speak, or
  a row that could not be written and read back, is an error rather than a
  shrug: the alternative is a supervisor that believes it has killed the
  order layer while the instruction went nowhere — exactly the state §13.3's
  *"so a hung strategy process cannot prevent a flatten"* exists to rule
  out.  A store that is merely *absent* (no ``DATABASE_URL``) is not this
  error: see :mod:`risk.kill` for the stance that splits the two directions
  the channel's absence cuts.
* :class:`RiskKillSwitchError` — feature 322's own noun, the *kill
  instruction* itself: a send whose moment states no time or whose label
  names no process, a module-level send that names no store to send
  through, and a stored row no instruction can be reconstructed as.  A
  sibling of :class:`RiskStoreError` rather than a child of it, because the
  repairs differ — *point the deployment at a database this member can
  open* against *fix the ask or the row* — and a caller told the wrong one
  would edit the wrong file while the order layer kept trading.
* :class:`RiskOrdersKilledError` — the order layer's receipt of the kill,
  raised by the guard (:func:`risk.require_orders_allowed`) when a kill
  instruction stands, and the one class in this module that carries a
  value: the standing :class:`~risk.kill.KillInstruction` rides on its
  ``instruction`` attribute, because *"which process killed us, and
  when?"* is the first question the operator of a killed order layer asks
  and the refusal is where they will look for it.

Every message names the offending value and the contract it broke, and the
two feature classes open with their greppable tokens
(:data:`KILL_INSTRUCTION_CODE`, :data:`ORDERS_KILLED_CODE`) so an operator
scanning a log for the kill channel's refusals greps one word rather than a
sentence — the same discipline the ``order_submission_unhealthy`` (feature
320) and ``determinism_broken`` (feature 143) tokens state for their own
features.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only; kill.py imports this
    from .kill import KillInstruction

__all__ = [
    "KILL_INSTRUCTION_CODE",
    "ORDERS_KILLED_CODE",
    "RiskError",
    "RiskKillSwitchError",
    "RiskOrdersKilledError",
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


class RiskError(Exception):
    """Base class for every failure of the risk package."""


class RiskStoreError(RiskError):
    """The kill instruction could not be persisted or read back.

    app_spec.xml, "Risk Supervisor & Kill Switches", feature 322: *"System
    runs the risk supervisor as a separate process, which sends a kill
    instruction to the order layer."*  The channel that sentence's second
    clause names is the workspace's relational store, so this is the
    failure of the channel itself: a ``DATABASE_URL`` whose scheme this
    member cannot speak, or a row that could not be written and read back
    within one send.  Raised rather than swallowed — a kill instruction
    that resolved but was never persisted is exactly the gap between a
    supervisor that believes it has killed the order layer and an order
    layer still trading.

    A store that is merely *absent* is not this error, for the same reason
    :class:`router.errors.RouterStoreError` takes that stance: an
    unconfigured deployment is a discoverable state, and the refusal
    belongs to the caller that demands a channel anyway.
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
    its two siblings carry only messages: the refusal's own payload is
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

    def __init__(self, message: str, instruction: KillInstruction | None = None) -> None:
        super().__init__(message)
        self.instruction = instruction
