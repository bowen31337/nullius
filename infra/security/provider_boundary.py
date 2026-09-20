"""Feature 150's law: the provider API call is placed outside the sandbox.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 150: *System places
the provider API call outside the sandbox in the orchestrator, which sends
code in and takes code out.*  docs/nullius-tech-architecture.md §17 fixes the
clause in one line — "Z1 sandboxes: egress denied by default.  The LLM API
call happens **outside** the sandbox, in the orchestrator, which passes code
in and gets code out." — and the sentence decomposes into four claims, each
of which this module owns as a seam rather than a comment:

* **the provider API call** — the subject is one *call*: a request to the
  model provider (the LLM API), the thing whose *placement* the feature
  fixes.  This module models it as :class:`ProviderCall` — a request, plus
  the zone the call was made from — and deliberately models nothing about
  what a request or a completion *contains*.  That shape is the provider
  interface's contract (feature 192, the providers plugin), and a boundary
  that also re-specified the payload would be a second, divergent copy of
  it.  What is owned here is where the call happens, not what it says.

* **outside the sandbox** — the placement law, and the whole of the refusal.
  A provider call stamped with :data:`SANDBOX_ZONE` is refused at the one
  seam that performs a call (:meth:`ProviderClient.complete`), *before* any
  backend runs, so nothing leaves the process on the strength of it; and the
  sandbox end of the boundary refuses to originate one at all
  (:meth:`SandboxHandle.call_provider`), because what sits on that side holds
  no client, no credential and no route.  The two refusals are one law seen
  from its two sides: the call is not made *in* the sandbox, and it is not
  accepted *from* it either.

* **in the orchestrator** — the subject of the placement: the trusted side,
  and the only holder of the provider client (:class:`Orchestrator`).  The
  zone stamp on a call is *bound by the holder* — the orchestrator stamps
  :data:`ORCHESTRATOR_ZONE` because it *is* the orchestrator, the sandbox
  handle stamps :data:`SANDBOX_ZONE` because it *is* the sandbox — and never
  taken from a string the caller supplied.  That is the same discipline as
  the bastion session id (:mod:`infra.security.bastion`): a capability is
  checked at the seam, not believed from the request.  The provider client is
  constructed inside the orchestrator and reachable only from there, so
  "the call happens in the orchestrator" is a property of the object graph,
  not a rule someone has to remember.

* **which sends code in and takes code out** — the mechanism, and the reason
  the placement is compatible with running agent-authored code at all.  The
  only things that cross this boundary are *code*: the orchestrator sends the
  agent-authored source in, and takes the sandbox's returned source out
  (:class:`CodeChannel`).  The conduit checks that what crosses is code — a
  source text, not some other object smuggled behind the name "code" — and it
  deliberately does **not** inspect that code's content: it is a conduit, not
  a content filter, and a boundary that claimed to tell innocent source from
  hostile source would be claiming a judgement no string comparison can make.
  The enforcement that matters is structural and lies outside the conduit: the
  sandbox has no egress (§17's first half; the law itself belongs to feature
  149), no credential (features 151 and 153), and no provider client in its
  namespace — so source that *tried* to reach the provider would find nothing
  to call and nowhere to send it.  That is why "passes code in and gets code
  out" is a complete description of the interface rather than a leak: the
  code is the only thing there is to pass.

**The refusal is the deliverable, and it is raised rather than returned.**  A
provider call is made by trusted code in the orchestrator — not by an arrival
from an untrusted zone, which is what the access gate answers
(:func:`infra.security.host_access.authorize_access` answers *arrivals* with a
decision) — so the shape here is an attempt that is refused, exactly as a
compile-time policy refusal is (:class:`infra.security.network_policy.
IngressRuleRejected`).  A caller that tried to place the provider call on the
wrong side of the boundary gets an exception it cannot ignore, which is the
point: the failure mode this feature exists to prevent is a model call quietly
happening where agent-authored code can see the key, and a silent fallback
would be that failure mode with better manners.

**Honest limits.**  The zone stamp is a string and a Python object can lie
about its own attributes — in-process, nothing can prevent a hostile object
from claiming :data:`ORCHESTRATOR_ZONE`.  What actually holds is the runtime
fact the stamp models: the sandbox runs with no egress and no credential, so
even a call that lied about its zone would have nowhere to go.  The stamp's
job is to make the placement *checkable* at the seam and to make the policy
explicit in the code that a reader — or a test — can point at, which is the
same role the bare-host-name CIDR test plays in
:mod:`infra.security.network_policy`.  This module does not pretend to be the
runtime enforcement; it is the law the runtime enforcement is written against.

Stdlib-only, like the rest of this tree.  Nothing here dials a network, and
the one client the module supplies (:class:`RecordingProviderClient`) holds no
transport and no credential at all: it is the honest shape of the seam and the
double every suite uses, in the same spirit as
:class:`infra.security.secrets_manager.InMemorySecretsStore`.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Final, NoReturn

__all__ = [
    "ORCHESTRATOR_ZONE",
    "SANDBOX_ZONE",
    "CodeChannel",
    "NoCodeToTake",
    "Orchestrator",
    "PayloadNotCode",
    "ProviderBoundaryError",
    "ProviderCall",
    "ProviderClient",
    "RecordingProviderClient",
    "SandboxHandle",
    "SandboxProviderCallRefused",
]

#: The trusted zone: the orchestrator, which owns the model calls and the
#: job they feed (§19's ``discovery/orchestrator`` — "campaign driver").
#: Keyed as a constant rather than written as a literal at each seam, so the
#: string the client accepts and the string the orchestrator stamps cannot
#: drift apart into two spellings of one zone.
ORCHESTRATOR_ZONE: Final[str] = "orchestrator"

#: The untrusted zone: where agent-authored code runs, in the gVisor sandbox
#: of §18.  Every model call made from here is refused — not because a
#: sandbox is assumed hostile at this seam, but because the call is the
#: orchestrator's to make: the credential lives there (§17), the egress
#: exists there, and neither exists inside.
SANDBOX_ZONE: Final[str] = "sandbox"

#: The zones this boundary has.  A closed set for the same reason feature
#: 153's environments are one: a call stamped with a third name is a typo,
#: not a third zone, and a client that accepted it would be accepting a
#: placement nobody wrote a law about.
_ZONES: Final[frozenset[str]] = frozenset({ORCHESTRATOR_ZONE, SANDBOX_ZONE})


class ProviderBoundaryError(Exception):
    """Base of the provider-boundary taxonomy.

    One base class so a caller — the orchestrator's campaign driver, a signal
    runner invoking :class:`SandboxHandle`, a CI check that the model call is
    not reachable from agent-authored code — can catch every failure of this
    boundary with a single ``except``.  The subclasses split by *which
    contract* was violated, never by which line of code failed, in the same
    discipline as :mod:`infra.security.network_policy`'s and
    :mod:`infra.security.audit_log`'s taxonomies.
    """


class SandboxProviderCallRefused(ProviderBoundaryError):
    """A provider API call was made from — or attempted for — the sandbox.

    Feature 150's placement, as the thing that is refused when it is
    violated.  Raised at both sides of the boundary: by
    :meth:`ProviderClient.complete` for a call carrying
    :data:`SANDBOX_ZONE`, and by :meth:`SandboxHandle.call_provider` for the
    attempt itself.  One exception type for both, because a caller does not
    have two problems when this fires — it has the feature's law, whichever
    side of the seam noticed, and the message says which.
    """


class PayloadNotCode(ProviderBoundaryError):
    """Something that is not code was offered to the conduit.

    ``sends code in and takes code out``: the conduit carries source text,
    and this is the refusal of everything else — bytes, a dict, a provider
    request object offered in the name of code.  Deliberately a *type* check
    and not a content check: a conduit that scanned source for suspicious
    strings would be enforcing a law it cannot enforce (see the module
    docstring's honest limits), whereas "the thing crossing the boundary is
    the thing the boundary is for" is a claim a type check can actually keep.
    """


class NoCodeToTake(ProviderBoundaryError):
    """The conduit was asked for code it does not hold.

    One of the two directions was empty: the sandbox end was asked for code
    that was never sent in, or the orchestrator was asked for code the
    sandbox has not returned.  Refused rather than answered with ``None`` or
    an empty string, because an empty module and a missing one are different
    facts and a round trip that conflated them would be the one place the
    boundary silently invented a payload.
    """


def _require_zone(zone: object, what: str) -> str:
    """Return ``zone`` as one of :data:`_ZONES`, refusing anything else.

    The membership test is guarded rather than written bare, because a zone
    that is not a string is refused for two different reasons and only one of
    them is about policy.  A ``str`` that is not a zone is a *typo* — a third
    place someone invented — while a list, a dict or any other unhashable
    object is a *wrong type* that would otherwise surface as the bare
    ``TypeError`` the set lookup happens to raise.  Both must leave as
    :class:`ProviderBoundaryError`, so the caller that catches this boundary
    with one ``except`` gets the same answer whichever it passed — the seam's
    error vocabulary is this module's, never the standard library's.
    """
    try:
        known = zone in _ZONES
    except TypeError:
        known = False
    if not known:
        raise ProviderBoundaryError(
            f"{what} must be one of the boundary's zones "
            f"({ORCHESTRATOR_ZONE!r}, {SANDBOX_ZONE!r}), got {zone!r} "
            f"({type(zone).__name__}). The zones are a closed set — a call "
            f"placed in a zone the deployment does not have is a typo, and a "
            f"boundary that accepted it would be inventing a placement no law "
            f"covers (feature 150: the provider API call is placed in the "
            f"orchestrator, outside the sandbox, and nowhere else)."
        )
    return zone


class ProviderCall:
    """One provider API call, and the zone that made it.

    The whole of what this boundary needs to know about a model call: the
    ``request`` it carries — opaque here, because a request's shape is the
    provider interface's contract (feature 192), not this module's — and the
    ``zone`` it was made from, which is the only thing the placement law
    reads.

    The zone is a required keyword with no default, and that is deliberate:
    a default would be a zone chosen by omission, and the one thing this
    attribute may never be is accidental.  In practice it is never chosen by
    a caller at all — :meth:`Orchestrator.call_provider` stamps
    :data:`ORCHESTRATOR_ZONE` because the orchestrator is the object making
    the call, and :meth:`SandboxHandle.call_provider` stamps
    :data:`SANDBOX_ZONE` because the sandbox handle is the object making the
    attempt — so the stamp records *who made the call*, never what the caller
    said about itself.
    """

    __slots__ = ("request", "zone")

    def __init__(self, *, request: object, zone: str) -> None:
        self.request = request
        self.zone = _require_zone(zone, "a provider call's zone")

    @property
    def made_outside_the_sandbox(self) -> bool:
        """Whether this call was placed on the trusted side of the boundary.

        The feature's placement as a single readable fact, so a caller — an
        audit line, a test, the client itself — asks about the placement
        instead of comparing zone strings and re-deciding which one is the
        safe one.
        """
        return self.zone != SANDBOX_ZONE

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ProviderCall(zone={self.zone!r})"


class ProviderClient:
    """The seam that performs a provider API call — and refuses the rest.

    A base class rather than a bare protocol, because the refusal *is* base
    behaviour: :meth:`complete` reads the call's zone and refuses anything not
    stamped :data:`ORCHESTRATOR_ZONE` before it reaches :meth:`_send`, so
    every client in the deployment inherits the placement law whether or not
    its author thought about it.  A real client subclasses this with the HTTP
    transport of §18's stack in :meth:`_send` — and holds the exchange-key-
    style credential that goes with it, out of a secrets manager (feature
    151) — and is injected wherever
    :class:`RecordingProviderClient` sits in a suite.

    The check happens *before* the backend, which is the load-bearing
    ordering: a refused call never reaches a transport, so a credential is
    never presented and no socket is ever opened on the strength of a call
    made from the wrong side.  "System places the provider API call outside
    the sandbox" is therefore not a caller's discipline but this method's
    first statement.
    """

    def complete(self, call: ProviderCall) -> object:
        """Perform one provider API call, or refuse it.

        The boundary's one enforcement point.  A call stamped
        :data:`SANDBOX_ZONE` raises :class:`SandboxProviderCallRefused` and
        is not recorded anywhere — the provider was never dialled, which is
        the difference between a refused call and a failed one.
        """
        if not call.made_outside_the_sandbox:
            raise SandboxProviderCallRefused(
                f"a provider API call was presented with zone {call.zone!r}; "
                f"feature 150 places the call *outside* the sandbox and this "
                f"client accepts it only from {ORCHESTRATOR_ZONE!r}. The call "
                f"is refused before any backend runs, so no credential is "
                f"presented and no request leaves the process — the sandbox "
                f"has no egress and holds no key (§17; features 149, 151), "
                f"and a placement that let one through would be the model "
                f"call happening where agent-authored code can see the "
                f"credential."
            )
        return self._send(call.request)

    def _send(self, request: object) -> object:
        """Perform the call the placement law has already admitted.

        The deployment's seam: a subclass puts its transport here.  Never
        reached by a refused call, which is why the zone check may not be
        moved down into it — a check that ran after the transport had been
        selected would be a comment about the transport, not a law about the
        call.
        """
        raise NotImplementedError(
            "a provider client must implement _send; this module's concrete "
            "client is RecordingProviderClient, and a deployment's real one "
            "puts its transport (and the credential that goes with it) here, "
            "on the orchestrator's side of the boundary (feature 150)."
        )


class RecordingProviderClient(ProviderClient):
    """A provider client whose answers are scripted and whose calls are kept.

    The module's one concrete client, and the honest shape of the seam: it
    holds a ``responder`` and nothing else — no transport, no endpoint, no
    credential — so it dials nothing and can be handed to a suite freely.  A
    deployment's real client subclasses :class:`ProviderClient` in exactly the
    same way, with its HTTP transport in :meth:`_send`; this one exists so the
    boundary can be exercised without a provider, the way feature 151's
    in-memory store exists so the committed-file rule can be exercised without
    a real secrets manager.

    What a suite actually asserts through it is the *record*: which calls
    reached the provider, in order.  A refused call leaves no entry, so "the
    provider was never dialled" is a checkable fact rather than a reading of
    the control flow.
    """

    def __init__(self, responder: Callable[[object], object]) -> None:
        if not callable(responder):
            raise ProviderBoundaryError(
                f"a provider client's responder must be callable, got "
                f"{responder!r} ({type(responder).__name__}). The responder "
                f"is how a scripted client answers a request — a value that "
                f"is not callable would leave every admitted call with "
                f"nothing to return, which is a broken client rather than a "
                f"scripted one (feature 150)."
            )
        self._responder = responder
        self._calls: list[ProviderCall] = []

    def _send(self, request: object) -> object:
        # Admitted by the base's zone check, so this is the record of what
        # the provider actually saw: one entry per call that reached it, in
        # the order it reached it.
        self._calls.append(ProviderCall(request=request, zone=ORCHESTRATOR_ZONE))
        return self._responder(request)

    def calls(self) -> tuple[ProviderCall, ...]:
        """Every call the provider was actually asked to make, in order.

        Entries only ever carry :data:`ORCHESTRATOR_ZONE`, because a call
        from anywhere else never got this far — so a non-empty record is
        itself the confirmation that the placement held, and a suite that
        expected a refusal asserts the record is still empty.
        """
        return tuple(self._calls)

    def requests(self) -> tuple[object, ...]:
        """The requests the provider saw, in order — the calls, unwrapped."""
        return tuple(call.request for call in self._calls)


class CodeChannel:
    """The conduit across the boundary: code in, code out, and nothing else.

    ``which sends code in and takes code out`` — the whole interface between
    the orchestrator and the sandbox that runs agent-authored code, modelled
    as two directions rather than one: what the orchestrator *sends in*
    (``send_code`` / ``receive_code``) and what the sandbox *returns out*
    (``return_code`` / ``take_code``).  They are kept apart because they are
    different facts — the source an agent wrote is not the source the sandbox
    handed back, and a conduit with a single slot would be unable to hold both
    a send and its answer, which is exactly the state a run spends most of its
    time in.

    Both directions are queues rather than a single slot, and both are FIFO:
    an orchestrator that sends two modules takes the sandbox's answers in the
    order the sandbox returned them, so what came out is attributable to what
    went in without a correlation id the feature never mentions.

    One object, two ends, and the model is honest about what that means: in a
    deployment the ends live in different processes, and the conduit is the
    policy-time shape of the channel between them — the same relationship
    :class:`infra.security.bastion.SessionBroker` has to the control plane it
    models.  What a reader should take from it is not that two Python objects
    grant two privileges, but that the thing crossing is code and the thing
    that performs provider calls is not on the sandbox's side of it.
    """

    __slots__ = ("_inbound", "_outbound")

    def __init__(self) -> None:
        self._inbound: deque[str] = deque()
        self._outbound: deque[str] = deque()

    def send_code(self, code: object) -> None:
        """Send one piece of code in — orchestrator to sandbox.

        The type check is the conduit's whole law: what crosses this boundary
        is source text (the agent-authored signal function of §14.1 that the
        sandbox executes), and an object that is not source text is refused
        with :class:`PayloadNotCode` rather than coerced with ``str()``.  A
        provider request offered here is the case that matters — it is not
        code, and a conduit that stringified it would have carried the one
        thing the feature keeps outside the sandbox straight through the
        boundary's own door.
        """
        self._inbound.append(_require_code(code, "code sent into the sandbox"))

    def receive_code(self) -> str:
        """Take the next piece of code that was sent in — sandbox side.

        What the sandbox's runner reads: the source it is about to execute.
        A run with nothing queued is refused (:class:`NoCodeToTake`) rather
        than handed a blank module, because a sandbox that executed an empty
        payload in the belief it had been sent code would report on a run that
        never happened.
        """
        return _take(self._inbound, "sent into the sandbox")

    def return_code(self, code: object) -> None:
        """Return one piece of code out — sandbox to orchestrator.

        The other half of the sentence, checked by the same law and for the
        same reason: the sandbox's answer is code, and the boundary does not
        accept a *result* smuggled back as if it were source.  Feature 166
        carries the score vector over the IPC channel; what this conduit
        carries is the code, and keeping the two apart is what stops the
        answer channel from becoming a general-purpose pipe out of the
        sandbox.
        """
        self._outbound.append(_require_code(code, "code returned from the sandbox"))

    def take_code(self) -> str:
        """Take the next piece of code the sandbox returned — orchestrator side.

        The orchestrator's read, and the end of the round trip: what the
        agent-authored source became.  Refused when the sandbox has not
        returned anything, for the same reason :meth:`receive_code` is — an
        empty answer is not an answer.
        """
        return _take(self._outbound, "returned from the sandbox")

    def pending_inbound(self) -> int:
        """How much code is waiting to be received — the conduit's depth."""
        return len(self._inbound)

    def pending_outbound(self) -> int:
        """How much returned code is waiting to be taken."""
        return len(self._outbound)


def _require_code(code: object, what: str) -> str:
    """Return ``code`` as a source string, refusing anything else.

    ``str`` exactly, not "anything stringifiable": the boundary carries
    source text and nothing else, and a payload that needed converting to
    become source was never source.  A blank string is *not* refused — that
    check would be a judgement about the code's content, and this conduit's
    law is a type check; what a blank module means is the evaluator's
    question (feature 148), not the conduit's.
    """
    if not isinstance(code, str):
        raise PayloadNotCode(
            f"{what} must be source text, got {code!r} "
            f"({type(code).__name__}). Feature 150's boundary carries code "
            f"in and code out, and only code: an object that is not source "
            f"text — a provider request, a response, a binary payload — is "
            f"refused by type rather than converted, because a conduit that "
            f"stringified whatever it was handed would carry the one thing "
            f"this boundary exists to keep in the orchestrator straight "
            f"through its own door."
        )
    return code


def _take(queue: deque[str], what: str) -> str:
    """Pop the next payload, refusing an empty direction."""
    if not queue:
        raise NoCodeToTake(
            f"the conduit holds no code {what}. 'Sends code in and takes code "
            f"out' is a round trip, and each direction is a real payload: "
            f"answering this read with an empty module would report on a "
            f"transfer that never happened, so it is refused instead "
            f"(feature 150)."
        )
    return queue.popleft()


class SandboxHandle:
    """The sandbox end of the boundary: code in, code out, and no provider.

    What the orchestrator hands to whatever executes agent-authored code —
    the gVisor runner of §18, which feature 157's plugin builds behind this
    same seam.  Its surface is the conduit's two ends and one refusal, and
    the refusal is the feature: :meth:`call_provider` raises
    :class:`SandboxProviderCallRefused` rather than failing with an
    ``AttributeError``, because the absence of a provider client here is a
    *law* rather than a missing attribute.  A run that tried to reach the
    provider should be told why it cannot — and the source it was sent, which
    is the only thing it can act on, is exactly what it cannot use to change
    that answer.

    The handle holds no zone parameter and no client: it takes the conduit
    and nothing else, so there is no constructor argument by which a caller
    could hand the sandbox a provider seam.  The refusal is not a
    configuration this object can be given the wrong value for.
    """

    __slots__ = ("_channel",)

    def __init__(self, channel: CodeChannel) -> None:
        self._channel = channel

    def receive_code(self) -> str:
        """Take the next piece of code sent in — the sandbox's read."""
        return self._channel.receive_code()

    def return_code(self, code: object) -> None:
        """Return code out — the sandbox's answer, by the conduit's law."""
        self._channel.return_code(code)

    def call_provider(self, request: object) -> NoReturn:
        """Attempt a provider API call from inside the sandbox — always refused.

        Feature 150's refusal, reached from the side that must never be able
        to place the call.  It raises before consulting anything: there is no
        client to consult, no credential to present, no egress to dial
        (§17's "egress denied by default"; feature 149's law), and no
        condition under which this method returns.  The ``request`` is
        accepted and deliberately unread — the attempt is answered the same
        way whatever it asked for, so a run cannot probe the boundary by
        varying its question.
        """
        raise SandboxProviderCallRefused(
            f"agent-authored code attempted a provider API call from the "
            f"sandbox (zone {SANDBOX_ZONE!r}); feature 150 places the "
            f"provider API call outside the sandbox, in the orchestrator. "
            f"This side of the boundary holds no provider client, no "
            f"credential and no route to the provider API — §17 denies "
            f"sandbox egress by default (feature 149) and keeps the key in "
            f"the orchestrator — so the call cannot be made from here and is "
            f"refused rather than attempted. Code goes in and code comes "
            f"out; the model call is the orchestrator's."
        )


class Orchestrator:
    """The trusted side: it holds the provider client, and it holds the conduit.

    The feature's placement made into an object.  The provider client is
    constructed *here* and reachable only from here — through
    :meth:`call_provider`, which stamps :data:`ORCHESTRATOR_ZONE` because this
    object is the orchestrator — so "the model call happens in the
    orchestrator" is a property of the object graph rather than a rule the
    campaign driver has to remember.  Nothing this class hands out carries the
    client: :meth:`sandbox_handle` builds the sandbox's view from the conduit
    alone, so the boundary is crossed by code and by nothing else.

    The three methods are the sentence's two halves and their order: the
    orchestrator calls the provider (§19's campaign driver asking a model for
    a signal), sends the code it got back in, and takes the sandbox's code
    out.  Nothing here runs the sandbox or drives a campaign — that is the
    discovery orchestrator's job, and this class is the seam it does those
    three things through.
    """

    __slots__ = ("_channel", "_provider")

    def __init__(
        self, provider: ProviderClient, channel: CodeChannel | None = None
    ) -> None:
        if not isinstance(provider, ProviderClient):
            raise ProviderBoundaryError(
                f"an orchestrator's provider must be a ProviderClient, got "
                f"{provider!r} ({type(provider).__name__}). The client is the "
                f"seam the placement law is enforced at, so an orchestrator "
                f"holding something else would hold a call path with no law "
                f"on it — and the call would then be placed wherever that "
                f"object happened to put it (feature 150)."
            )
        self._provider = provider
        self._channel = channel if channel is not None else CodeChannel()

    @property
    def provider(self) -> ProviderClient:
        """The client this orchestrator makes model calls through.

        Exposed for the trusted side's own use — an operator script that
        inspects the record, a suite that asserts what reached the provider.
        Reading it does not widen the boundary: the sandbox's view of this
        object is :meth:`sandbox_handle`'s, and the client is not in it.
        """
        return self._provider

    def call_provider(self, request: object) -> object:
        """Make one provider API call — the feature's placement, performed.

        The call is stamped :data:`ORCHESTRATOR_ZONE` here, at the object that
        *is* the orchestrator, and handed to the client, which admits it on
        that strength alone.  There is no parameter by which a caller could
        place this call elsewhere: the placement is what this method *is*, the
        way the session id :meth:`infra.security.bastion.SessionBroker.attach`
        returns is what riding a session *is*.
        """
        return self._provider.complete(
            ProviderCall(request=request, zone=ORCHESTRATOR_ZONE)
        )

    def send_code(self, code: object) -> None:
        """Send code in — the orchestrator's half of crossing the boundary."""
        self._channel.send_code(code)

    def take_code(self) -> str:
        """Take code out — what the sandbox returned, on this side."""
        return self._channel.take_code()

    def sandbox_handle(self) -> SandboxHandle:
        """The sandbox's view of this boundary: the conduit, and nothing else.

        Built from the channel alone, so the handle cannot carry the provider
        client by construction — there is no argument to get wrong and no
        field to forget.  This is the method that makes the placement
        structural: whatever executes agent-authored code is handed *this*,
        and this has no way to reach the provider.
        """
        return SandboxHandle(self._channel)
