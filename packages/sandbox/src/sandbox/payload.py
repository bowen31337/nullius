"""Feature 159's law: a run whose payload did not cross the channel is refused.

app_spec.xml, "Untrusted Code Sandbox", feature 159: *System rejects a
sandboxed run whose payload did not arrive over the IPC channel, because the
sandbox holds no filesystem mounts.*  docs/nullius-tech-architecture.md §5.2
gives the feature both halves of its subject in two places — the call site
spells the arrival (``payload=window.to_arrow(),        # IPC, zero-copy``)
and the control table spells the reason (``Filesystem | No mounts.  Data
arrives over IPC only.``).  The sentence decomposes into four claims, each
owned here as a seam rather than a comment:

* **a sandboxed run** — the subject, and the same unit feature 157's gate
  answers.  Not a window, not a transfer: *one execution* of agent-authored
  code, offered to the launcher, checked before anything runs.  So this law
  composes beside :func:`sandbox.isolation.authorize_run` on the launcher's
  last lines — feature 157 asks *which box, under what isolation*, this one
  asks *did the window the box will evaluate actually reach it* — and a run
  that fails either question is refused before a process exists.

* **whose payload did not arrive over the IPC channel** — the evidence
  question, and the one this module exists to answer honestly.  Arrival is
  not a property a payload carries; it is a property of the *channel*, the
  one seam §5.2 leaves open into the box.  A run is handed in with the
  channel that would have delivered its window
  (:class:`sandbox.transfer.TransferChannel`, feature 166 — duck-typed by its
  ``window_bytes``, so a stand-in or a deployment's own channel object is
  read as happily as the member's), and the gate admits only when the
  channel holds a window **and** the payload the run was dispatched with is
  those bytes.  Bytes offered with no channel behind them are a claim, not
  an arrival: the channel is the provenance, which is why a run whose
  ``payload=`` argument disagrees with the window its channel carries is
  refused rather than read as doubly-verified.

* **because the sandbox holds no filesystem mounts** — the because-clause,
  and the reason the refusal is a refusal rather than a warning.  §5.2's
  row is structural: the box has no disk, so a payload that did not cross
  the channel is not a payload the signal inside could read *at all* —
  spawning anyway would produce a run whose window exists only on the host,
  whose score vector — if the signal survives to emit one — would be scored
  against a universe the box never saw, and whose failure mode is exactly
  the absence-that-reads-as-a-result this category's other gates exist to
  keep out of §6.1's reduction.  A payload offered as a path
  (:attr:`PayloadReason.BY_FILESYSTEM`) is the spelling this clause names
  most directly: a path names a place on a filesystem the box does not
  hold, and there is no mount for it to resolve against.

* **rejects** — the consequent, and the shape of the answer.
  :func:`authorize_payload_run` answers every run with a
  :class:`PayloadDecision` and raises for none, for the reason feature 157's
  gate raises none: §6.1 dispatches thousands of unattended candidates, and
  "this one's window never crossed" must reach an operator as a fact about a
  run rather than as a crashed evaluator.  The raise lives on
  :meth:`PayloadDecision.require` /
  :meth:`SandboxPayload.require` — the launcher's last line before the
  spawn — as :class:`~sandbox.errors.PayloadChannelRequired`.

**Why this law is not feature 166 wearing a second coat.**  The transfer law
owns *what crossed*: the bytes are a window (feature 14's container), the
return is a score vector positionally aligned with the universe that went
out.  This law owns *whether the run's payload crossed at all* — a question
about the dispatch, asked of a run rather than of bytes, and one the channel
cannot ask for itself because a run that never sends a window produces no
transfer to fail.  The two compose: a launcher that uses both sends the
window over the channel (166 validates it), then asks this gate to admit the
run on the evidence of that same channel (159), then spawns — and the gate's
decision carries the :class:`~sandbox.transfer.WindowFacts` the channel
declared, so the return leg's alignment check needs no second read.  They
refuse differently on purpose: 166's refusals are raised at the channel seam
(one dispatch by trusted host code), while this one *answers* per run like
157's gate, because the subject is a run offered thousands of times.

**§5.2's Filesystem row has three enforcements, and this is the earliest.**
The row ``Filesystem | No mounts. Data arrives over IPC only.`` is enforced
bottom-up by feature 160's seccomp ceiling — the committed artifact refuses
the ``open``/``openat`` family, so a process that reaches for a mount it was
never given is killed as §15's escape attempt — and structurally by the
runtime a deployment configures (no volumes, an empty rootfs).  This law is
the admission half, ahead of all of them: it refuses the run *before a
process exists*, which is the only point where "the window never arrived"
is still a dispatch problem with a dispatch repair, rather than a killed
child with a fail class to record.

**What is deliberately absent: a committed artifact.**  Features 157, 167,
164, 163, 162 and 160 ship one because each subject is a *setting* a
deployment writes down.  This law's subject is the box's *structure* —
§5.2 fixes "no mounts, IPC only" for every box in this deployment, and
there is nothing a deployment could set differently without leaving the
architecture.  A ``payload_policy.json`` would be a knob nobody turns, the
objection :func:`sandbox.transfer.sandbox_transfer`'s builder states for its
own absent file; a non-``None`` component at this seat proves only that the
law is loaded.

**Honest limits.**  This module is the delivery gate, not the mount
enforcement: at runtime the container's volume table and feature 160's
ceiling are what keep a path unreadable inside the box, and a Python object
graph can always be assembled by hand with a channel no law opened.  What
holds is that a launcher using this seam cannot spawn a run against bytes
that did not cross, that the answer is derived from the channel the caller
holds rather than from a constant, and that *which* way a payload failed to
arrive is a value a decision carries and an operator can read — so "the
window crossed" is a fact about the dispatch rather than a hope.

Stdlib-only, like the rest of the member.  Nothing here opens a file, mounts
a volume or reads ``os.environ`` — the module is the law and the caller
supplies the run and the channel.
"""

from __future__ import annotations

import enum
import os
from typing import Any, Final

from .errors import (
    PayloadChannelRequired,
)
from .transfer import WindowFacts

__all__ = [
    "PAYLOAD_CHANNEL_CODE",
    "PAYLOAD_COMPONENT_NAME",
    "PayloadDecision",
    "PayloadReason",
    "PayloadRun",
    "SandboxPayload",
    "authorize_payload_run",
    "sandbox_payload",
]

#: The component name this law registers under — beside feature 157's
#: ``sandbox`` and the eight other seats this member already carries, not
#: instead of any of them: the factory's registry is keyed by name and a later
#: registration of the same name *replaces* the earlier one, so a member
#: carrying eleven controls carries eleven components, each answering its own
#: feature's question.
PAYLOAD_COMPONENT_NAME: Final[str] = "sandbox-payload"

#: The greppable code every payload-delivery refusal carries — feature 159's
#: own subject written as a token, the discipline
#: :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE`
#: (``gvisor_isolation_required``), :data:`sandbox.threads.THREAD_PINNING_CODE`
#: (``thread_pinning_required``) and :data:`sandbox.seed.SEED_REQUIRED_CODE`
#: (``node_seed_required``) apply to their features.  An operator grepping a
#: log for the rejection finds it by the feature's own words.
PAYLOAD_CHANNEL_CODE: Final[str] = "payload_channel_required"

#: The attribute the gate reads a channel's window through —
#: :attr:`sandbox.transfer.TransferChannel.window_bytes`, spelled once here so
#: the duck-typed read and the docstrings that name it cannot drift into two
#: spellings of one seam.  A channel is *anything* carrying this attribute:
#: the member's own channel, a deployment's pipe-backed stand-in, or a test
#: double — the law's subject is the arrival, not the class that witnessed it.
WINDOW_ATTRIBUTE: Final[str] = "window_bytes"

#: The types this law reads as *filesystem-shaped* — the spellings a payload
#: arrives in when a dispatch reached for a mount rather than a channel.  A
#: ``str`` is a path in every shape §5.2's world produces one (the call site
#: has no spelling for a text payload at all), and ``os.PathLike`` covers the
#: ``Path`` a host-side runner would hand a staging file.  Spelled as a tuple
#: because it is spent as the second argument to :func:`isinstance`.
_FILESYSTEM_SHAPED: Final[tuple[type, ...]] = (str, os.PathLike)

#: The types this law reads as *channel-shaped* — the byte spellings a
#: serialized window exists as on the far side of a transfer.  A
#: ``memoryview`` is accepted for comparison and copied, the same stance
#: :func:`sandbox.transfer._as_bytes` takes toward a view over someone else's
#: allocation: the channel is the provenance, not the buffer.
_CHANNEL_SHAPED: Final[tuple[type, ...]] = (bytes, bytearray, memoryview)


def _row_sentence() -> str:
    """§5.2's control-table row, verbatim, for every refusal to carry.

    One body rather than six literals, so each refusal names the *law it
    enforces* in the architecture's own words — ``Filesystem | No mounts.
    Data arrives over IPC only.`` — and a reader of any one of them can find
    the row the others cite without grep.  The same one-body discipline
    :func:`sandbox.seed._refusal` takes for its five spellings.
    """
    return (
        "§5.2's control table gives the box its filesystem posture in one row "
        "— 'Filesystem | No mounts. Data arrives over IPC only.' — and §5.2's "
        "call site is the arrival itself: ``payload=window.to_arrow(), "
        "# IPC, zero-copy``"
    )


def _refusal(spelling: str, consequence: str) -> str:
    """The operator-facing sentence for a payload that did not arrive.

    The one body every refusal composes: what was found, which spelling of
    not-arriving that was, and what spawning anyway would have cost.  Every
    message begins with :data:`PAYLOAD_CHANNEL_CODE` so an operator grepping a
    log finds the rejection by the feature's own words.
    """
    return (
        f"{PAYLOAD_CHANNEL_CODE}: a sandboxed run was refused because its "
        f"payload {spelling}. {consequence} {_row_sentence()}. The run is "
        f"refused before anything executes (feature 159)."
    )


class PayloadReason(enum.StrEnum):
    """Why a run was admitted or refused — the audit vocabulary.

    One enumeration carries the acceptance and the refusals, for the reason
    :class:`sandbox.isolation.RunReason` does: a decision's reason is one fact
    with two polarities and the audit line should read the same either way —
    ``over-ipc`` names the evidence the run was admitted on, and the refusals
    name what the dispatch offered instead of an arrival.
    """

    #: Admitted: the channel handed with the run holds a validated window and
    #: the payload the run was dispatched with is those bytes — or was left
    #: to the channel entirely, which is the same arrival stated once rather
    #: than twice.  Reading the string is proof a channel was consulted and
    #: found to be carrying the window the run will be evaluated against.
    OVER_IPC = "over-ipc"

    #: Refused: the run was offered with no payload and no channel holding
    #: one.  §5.2's call site always passes ``payload=`` — a run with no
    #: window at all has nothing to evaluate, and an empty window is a
    #: different fact from an absent one (feature 166's own distinction).
    WITHOUT_PAYLOAD = "without-payload"

    #: Refused: the payload names a place on a filesystem — a path, the
    #: spelling the because-clause is about.  The box holds no mounts, so the
    #: place the payload names is a place the signal inside cannot read: the
    #: run would spawn against a window that exists only on the host.
    BY_FILESYSTEM = "by-filesystem"

    #: Refused: bytes were offered with no channel behind them.  Arrival is a
    #: property of the channel, not of the bytes — a ``payload=`` argument
    #: full of window is a *claim* to have arrived, and the only proof this
    #: law can read is the channel that would have carried it.  Bytes without
    #: a channel are exactly the smuggled window this feature exists to
    #: catch, and they are refused however well-formed they are.
    NO_CHANNEL = "no-channel"

    #: Refused: a channel was handed with the run and it holds no window.
    #: The seam exists and the send never happened — a dispatch that opened a
    #: channel, skipped ``send_window`` and spawned anyway.  Split from
    #: :attr:`NO_CHANNEL` because the repairs differ: a missing channel is
    #: looked for where the dispatch builds its run, a silent one between
    #: the channel's creation and the spawn.
    NOTHING_ARRIVED = "nothing-arrived"

    #: Refused: the payload is not what the channel carried — an object that
    #: was never serialized onto any channel (a ``MarketWindow`` handed over
    #: as a reference), or bytes that disagree with the window the channel
    #: holds, which is a run about to be evaluated against a window that
    #: never crossed.  Two spellings, one reason, because they are one fact
    #: — *these bytes did not cross* — and one repair locus: the dispatch.
    OFF_CHANNEL = "off-channel"


class PayloadRun:
    """One sandboxed run, as presented to the delivery gate.

    The unit feature 159's sentence is about — §5.2's
    ``sandbox.run(entrypoint="signal", code=node.code, payload=window.to_arrow(),
    …)`` — modelled as the half of that call this law has a claim about: the
    ``payload`` argument, the ``channel`` that would have delivered it, and
    the identity of the run for the refusal's sentence.  It is deliberately
    not the whole call: the isolation is feature 157's, the limits are 162's
    and 163's, the seed is 165's, and a boundary that also modelled them
    would be a second, divergent copy of ``evaluator._sandbox``'s call shape —
    the mistake :class:`sandbox.isolation.SandboxRun` and
    :class:`sandbox.seed.SandboxInvocation` each name for themselves.

    **The constructor refuses nothing**, for the reason
    :class:`sandbox.seed.SandboxInvocation`'s does: the caller that most
    needs to be told its run's payload never arrived is the caller holding
    that run, and it cannot be told about an object it was never allowed to
    build.  Every refusal fires at
    :func:`authorize_payload_run`/ :meth:`SandboxPayload.require`.

    **``channel`` is the provenance and ``payload`` is the claim.**  A real
    dispatch opens a channel, sends the window over it
    (:meth:`sandbox.transfer.TransferChannel.send_window`), and describes the
    run with the same bytes — the gate checks the two agree, because a run
    whose ``payload=`` is one buffer and whose channel carries another is a
    run about to be scored against a window that never reached the box.
    ``payload=None`` with a loaded channel is admitted: the channel then
    states the arrival once, in the one place it is provable, rather than
    twice in places that could disagree.
    """

    __slots__ = ("channel", "component", "node_id", "payload")

    def __init__(
        self,
        *,
        payload: Any = None,
        channel: Any = None,
        component: str = "",
        node_id: str = "",
    ) -> None:
        self.payload = payload
        self.channel = channel
        self.component = component
        self.node_id = node_id

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PayloadRun(component={self.component!r}, "
            f"node_id={self.node_id!r}, "
            f"payload={type(self.payload).__name__}, "
            f"channel={type(self.channel).__name__})"
        )


def _channel_window(channel: Any) -> bytes | None:
    """The window a channel holds, or ``None`` when it holds none.

    The duck-typed read behind every arrival question: a channel is anything
    carrying :data:`WINDOW_ATTRIBUTE`, and the law asks it one thing — *do
    you hold a window?*  A missing attribute, a ``None``, or a value that is
    not bytes means no window *this law can read*, which is the honest
    answer rather than a type error: the gate then refuses on
    :attr:`PayloadReason.NO_CHANNEL`/:attr:`PayloadReason.NOTHING_ARRIVED`
    rather than guessing at an arrival it could not witness.  The tolerance
    is the one :func:`sandbox.seed._validated_record_seed` extends to the two
    shapes a record arrives in, and for the same reason: the subject is the
    caller's object, not this module's.
    """
    window = getattr(channel, WINDOW_ATTRIBUTE, None)
    if isinstance(window, _CHANNEL_SHAPED):
        return bytes(window)
    return None


def _channel_facts(channel: Any) -> WindowFacts | None:
    """The facts the channel declared about the window it holds, or ``None``.

    Carried rather than read for meaning: :class:`WindowFacts` belongs to the
    transfer law, and this gate's only use for them is to hand them to the
    caller whose return leg will be validated against them — one read of the
    channel, two consumers, no second :func:`sandbox.transfer.inspect_window_payload`
    call the box would have to pay for.
    """
    facts = getattr(channel, "facts", None)
    return facts if isinstance(facts, WindowFacts) else None


def _payload_bytes(payload: Any) -> bytes | None:
    """The payload as bytes, or ``None`` when it is not a byte spelling."""
    if isinstance(payload, _CHANNEL_SHAPED):
        return bytes(payload)
    return None


def authorize_payload_run(run: Any) -> PayloadDecision:
    """Answer one run: admitted only when its payload provably crossed.

    The order of the checks is the order of the sentence.  What the dispatch
    *offered* is settled first — a payload that names a filesystem place or
    was never serialized is refused whatever any channel says, because those
    are spellings of a delivery this box cannot make — then the *arrival*:
    the channel is consulted, and it is the only thing that can admit.

    Every answer is a value; nothing is raised here, for the reason feature
    157's gate raises nothing: the pipeline offers thousands of runs
    unattended, and *"this one's window never crossed"* must reach an
    operator as a fact about a run rather than as a crashed evaluator.  A
    caller that must not proceed turns the answer into an exception with
    :meth:`PayloadDecision.require`.
    """
    payload = getattr(run, "payload", None)
    channel = getattr(run, "channel", None)
    component = getattr(run, "component", "") or ""
    node_id = getattr(run, "node_id", "") or ""

    named = f" (node {node_id!r}, component {component!r})" if node_id or component else ""

    if isinstance(payload, _FILESYSTEM_SHAPED):
        return PayloadDecision(
            admitted=False,
            reason=PayloadReason.BY_FILESYSTEM,
            component=component,
            node_id=node_id,
            detail=_refusal(
                f"names a place on a filesystem ({payload!r}, "
                f"{type(payload).__name__}){named}",
                consequence=(
                    "The sandbox holds no filesystem mounts, so the place "
                    "this payload names is a place the signal inside the box "
                    "cannot read: the run would spawn against a window that "
                    "exists only on the host, and a score vector produced "
                    "that way — if the signal survives to emit one — is "
                    "scored against a universe the box never saw. Serialize "
                    "the window and send it over the channel instead "
                    "(feature 166's ``send_window``); a path is not an "
                    "arrival, it is the mount this box refuses to hold."
                ),
            ),
        )

    offered = _payload_bytes(payload)
    if payload is not None and offered is None:
        return PayloadDecision(
            admitted=False,
            reason=PayloadReason.OFF_CHANNEL,
            component=component,
            node_id=node_id,
            detail=_refusal(
                f"is an object reference ({type(payload).__name__}) that was "
                f"never serialized onto any channel{named}",
                consequence=(
                    "§5.2's call site serializes before it dispatches — "
                    "``payload=window.to_arrow()`` — because the box reads "
                    "bytes off a channel, not objects out of the host's "
                    "memory. An object handed to the runner is a window the "
                    "box can never receive: serialize it and send it over "
                    "the channel (feature 166), or the run is a reference to "
                    "a window wearing a payload's name."
                ),
            ),
        )

    window = _channel_window(channel)
    if window is not None:
        if offered is None or offered == window:
            return PayloadDecision(
                admitted=True,
                reason=PayloadReason.OVER_IPC,
                component=component,
                node_id=node_id,
                payload=window,
                facts=_channel_facts(channel),
                detail=(
                    f"run{named} admitted: its payload arrived over the IPC "
                    f"channel — a {len(window)}-byte window the channel "
                    f"holds, and the payload the run was dispatched with is "
                    f"those bytes. {_row_sentence()}, so an arrival is the "
                    f"only spelling of a payload this box can read "
                    f"(feature 159, over feature 166's channel)."
                ),
            )
        return PayloadDecision(
            admitted=False,
            reason=PayloadReason.OFF_CHANNEL,
            component=component,
            node_id=node_id,
            detail=_refusal(
                f"is not the window its channel carries{named}: the run was "
                f"dispatched with {len(offered)} byte(s) of payload and the "
                f"channel holds {len(window)}",
                consequence=(
                    "Two buffers, one run: the bytes the run was dispatched "
                    "with and the bytes that actually crossed are different "
                    "windows, and a spawn here would evaluate the signal "
                    "against one of them while the channel — and every "
                    "alignment check feature 166 makes on the return leg — "
                    "describes the other. The dispatch sent one window and "
                    "passed another; send the run's own window over the "
                    "channel, or dispatch against the one it carries."
                ),
            ),
        )

    if payload is None:
        reason = PayloadReason.WITHOUT_PAYLOAD if channel is None else PayloadReason.NOTHING_ARRIVED
        consequence = (
            "§5.2's call site always passes ``payload=``: a run with no "
            "window at all has nothing to evaluate, and the run that "
            "proceeded would report an ordinary trial outcome for a "
            "candidate whose signal never saw a window. An empty window is "
            "a different fact from an absent one — the empty one crosses "
            "the channel and is feature 166's to validate; this run offered "
            "no window anywhere."
            if channel is None
            else "A channel was handed with the run and it holds no window: "
            "the seam exists and the send never happened. The run that "
            "proceeded would spawn a signal whose payload is an absence — "
            "send the window over the channel the dispatch already opened "
            "(feature 166's ``send_window``) before spawning."
        )
        spelling = (
            "did not arrive at all: none was offered, and no channel was "
            "handed for one to arrive on"
            if channel is None
            else "did not arrive: the channel handed with the run carries no "
            "window"
        )
        return PayloadDecision(
            admitted=False,
            reason=reason,
            component=component,
            node_id=node_id,
            detail=_refusal(f"{spelling}{named}", consequence=consequence),
        )

    reason = PayloadReason.NO_CHANNEL if channel is None else PayloadReason.NOTHING_ARRIVED
    consequence = (
        "Bytes without a channel are a claim, not an arrival: the only "
        "provenance this law can read is the channel that would have "
        "carried the window, and however well-formed these bytes are, a "
        "spawn here would evaluate a window nobody delivered. Open the "
        "channel (feature 166's ``channel()``), send the window over it, "
        "and dispatch the run against the channel that carries it."
        if channel is None
        else "A channel was handed with the run and it holds no window, so "
        "the bytes offered with the run are bytes that never crossed it: "
        "the dispatch skipped the send and passed the window straight to "
        "the runner. Send them over the channel the dispatch already "
        "opened, or the run is a window wearing an arrival it did not have."
    )
    spelling = (
        f"is {len(offered) if offered is not None else 0} byte(s) of serialized window offered "
        "with no channel behind them"
        if channel is None
        else "is a serialized window the channel handed with the run does "
        "not carry: nothing arrived over it"
    )
    return PayloadDecision(
        admitted=False,
        reason=reason,
        component=component,
        node_id=node_id,
        detail=_refusal(f"{spelling}{named}", consequence=consequence),
    )


class PayloadDecision:
    """The gate's whole answer: admitted or not, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed*
    from the channel the run was handed rather than set by a constant — the
    same "computed, never assumed" stance :class:`sandbox.isolation.RunDecision`
    takes for a run's isolation.  ``detail`` is the operator-facing sentence,
    and it names the spelling of not-arriving it found, because an operator
    offered six differently-worded refusals would be reading prose rather
    than reading a code.

    ``payload`` is the bytes the run was admitted on — the window the
    channel holds, which is the payload the box will evaluate — and ``None``
    for every refusal.  ``facts`` is the :class:`~sandbox.transfer.WindowFacts`
    the channel declared about that window, carried so the return leg's
    alignment check needs no second read of the channel.
    """

    __slots__ = ("admitted", "component", "detail", "facts", "node_id", "payload", "reason")

    def __init__(
        self,
        *,
        admitted: bool,
        reason: PayloadReason,
        detail: str,
        component: str = "",
        node_id: str = "",
        payload: bytes | None = None,
        facts: WindowFacts | None = None,
    ) -> None:
        self.admitted = admitted
        self.reason = reason
        self.detail = detail
        self.component = component
        self.node_id = node_id
        self.payload = payload
        self.facts = facts

    def require(self) -> bytes:
        """Return the payload that crossed, or raise the refusal.

        The bridge between the gate's returned answer and the exception a
        launcher wants on its last line before the spawn: a decision that
        admitted the run returns its payload — the bytes proven to have
        crossed, the value §5.2's call site passes on — so a caller can put
        it on the line before it forks and have the law enforced there
        rather than remembered.  A refusal raises
        :class:`~sandbox.errors.PayloadChannelRequired` carrying the gate's
        own operator-facing sentence, the same error type
        :meth:`SandboxPayload.require` raises — one law, two shapes.
        """
        if not self.admitted:
            raise PayloadChannelRequired(self.detail)
        return self.payload  # type: ignore[return-value]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PayloadDecision(admitted={self.admitted}, "
            f"reason={self.reason!r}, node_id={self.node_id!r})"
        )


class SandboxPayload:
    """Feature 159's law, as the value a composed application carries.

    A stateless facade over this module — the same shape
    :class:`sandbox.SandboxIsolation` gives feature 157 and the other eight
    facades give theirs — so a caller holding the composed component can ask
    the feature's question, *did this run's payload arrive over the IPC
    channel?*, without importing the member's submodules by name.

    **It carries nothing: no channel, no window, no handle.**  A channel
    belongs to one run, and a component shared across runs that held one
    would be a component letting two runs share a window — the property
    :class:`sandbox.transfer.SandboxTransfer` states for its channel and
    :class:`sandbox.seed.SandboxSeed` for its seed, restated here because
    the quantity is the same one in its most literal form.  It does not mint
    channels either: feature 166 owns the seam
    (:meth:`sandbox.transfer.SandboxTransfer.channel`), and a delivery law
    that opened channels would be a second owner of the one thing whose
    provenance it is supposed to judge.

    **The delegation is deliberately thin** — each verb is one call into
    this module — because a second implementation of the arrival check here
    would be a second thing to keep in sync with the channel, and the
    member's one-provenance rule exists so that cannot happen.
    """

    __slots__ = ()

    def check(self, run: Any) -> PayloadDecision:
        """Answer whether ``run``'s payload arrived over the IPC channel.

        The gate as a value, for a caller that wants to branch or to audit:
        returns a :class:`PayloadDecision` whose ``admitted`` is ``True``
        only when the channel the run was handed holds a window and the
        payload the run was dispatched with is those bytes.  Nothing raises,
        for the reason feature 157's gate raises nothing.
        """
        return authorize_payload_run(run)

    def require(self, run: Any) -> bytes:
        """Return the payload that provably crossed, or raise the refusal.

        The launcher's verb: one call, the run, and either the bytes the box
        will evaluate — proven to have crossed the channel — or
        :class:`~sandbox.errors.PayloadChannelRequired` carrying the gate's
        own operator-facing sentence.  Put on the last line before the
        spawn, it makes *"a sandboxed run whose payload did not arrive over
        the IPC channel"* refused there rather than remembered.
        """
        return authorize_payload_run(run).require()


def sandbox_payload() -> SandboxPayload:
    """The delivery law, for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the
    law would have nothing to run it *on*, since the law needs a run and the
    channel that would have delivered its payload.  This is the
    module-level convenience the member's own tests and any operator script
    reach, and it is the same call :func:`sandbox.build_sandbox_payload`
    makes minus the composition.
    """
    return SandboxPayload()
