"""Feature 156's gate: every arrival answered, all but one path rejected.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 156: *System
rejects access to the live trading host that does not arrive through a
bastion session, because no inbound port is exposed.*  docs/nullius-
architecture.md §17 fixes both halves — "No inbound ports on the live
trading host.  Access via bastion or session manager only." — and this
module is the seam where an arrival meets them:

* **System rejects** — the deliverable is an *answer*, not an
  exception.  A gate sees arrivals of every shape, well-formed and
  hostile alike, and a rejection is a normal answer to a hostile one,
  so :func:`authorize_access` returns an :class:`AccessDecision` for
  every request and raises for none.  Failing closed is the shape of
  the logic, not an exception handler: every path through the gate
  either proves the arrival rode a live bastion session or falls out
  the bottom rejected.

* **does not arrive through a bastion session** — the carve-out is
  *narrower than a channel label*.  An arrival presenting
  :attr:`Channel.BASTION_SESSION` passes only when the id it carries
  names a session the broker actually issued, for the host the arrival
  targets, on a channel still registered and not yet ended — anything
  less (no id, an unknown id, another host's id, a dead session's id)
  is rejected with :attr:`AccessReason.UNREGISTERED_SESSION`, because
  naming the channel is not riding it.  The capability is the id
  checked against the registry, never the string in the request.

* **because no inbound port is exposed** — the *reason*, and the
  feature's own explanation of itself.  A direct arrival is evaluated
  against the destination's compiled ingress surface
  (:class:`infra.security.network_policy.HostPolicy`), and for a
  live-trading host that surface is empty — the compiler refuses any
  document saying otherwise — so the rejection cites
  :attr:`AccessReason.NO_INBOUND_PORT_EXPOSED` and means it: there is
  no port to connect to, not a port someone forgot to allowlist.  The
  gate does not special-case the live host by name; the emptiness of
  its surface *is* the special case, which is why a second
  live-trading host added to the zone is covered the moment its role
  is written.

* **the live trading host** — the sentence scopes the law, and the
  gate respects the scope rather than widening it into a blanket deny.
  The zone's front door still works: a direct SSH to the *bastion*
  from the operator allowlist is admitted
  (:attr:`AccessReason.BY_INGRESS_RULE`), because the bastion is the
  one host §17's "no inbound ports" was never said about.  What the
  gate refuses is the path around the front door — every direct
  arrival at the live trading host, from every source, on every port.

The gate is a pure consultation — policy in, broker in, request in,
decision out; stdlib-only, no network, no state.  It is the same shape
a host firewall's policy hook or a session-manager's admission check
would call, so the rejection the spec names is the one this code
returns.
"""

from __future__ import annotations

import enum

from .bastion import SessionBroker
from .network_policy import ZonePolicy

__all__ = [
    "AccessDecision",
    "AccessReason",
    "AccessRequest",
    "Channel",
    "authorize_access",
]


class Channel(enum.StrEnum):
    """How an arrival claims to have reached the host.

    Two members, because §17's topology leaves exactly two ways in:
    the front door (a socket dialed at an exposed port — which for the
    live trading host does not exist) and the brokered ride (a session
    on a channel the host dialed out).  An arrival presenting any other
    string is treated as :attr:`DIRECT` by the gate's fall-through —
    an unknown channel is not a third way in, it is a direct arrival
    with an unusual name, and it is evaluated against the same empty
    surface.
    """

    DIRECT = "direct"
    BASTION_SESSION = "bastion-session"


class AccessReason(enum.StrEnum):
    """Why a decision came out the way it did — the audit vocabulary.

    One enumeration carries both the acceptance and the rejection
    reasons, because a decision's reason is one fact with two polarities,
    and the audit line should read the same either way:
    ``no-inbound-port-exposed`` is the feature's own "because" verbatim.
    """

    #: Accepted: riding a live bastion session the broker issued for
    #: exactly this destination — the single carve-out of §17.
    VIA_BASTION_SESSION = "via-bastion-session"

    #: Accepted: a direct arrival at a port the destination genuinely
    #: exposes, from a source its rule genuinely admits — reachable
    #: only for non-live hosts (the bastion's own SSH).
    BY_INGRESS_RULE = "by-ingress-rule"

    #: Rejected: the destination exposes no port for this arrival.  For
    #: the live trading host this is the permanent case — its compiled
    #: ingress surface is empty — and the reason the feature's sentence
    #: gives for every rejection it names.
    NO_INBOUND_PORT_EXPOSED = "no-inbound-port-exposed"

    #: Rejected: the port is exposed but this source is not admitted
    #: by the rule that opened it (the bastion's SSH from outside the
    #: operator allowlist).
    SOURCE_NOT_ALLOWED = "source-not-allowed"

    #: Rejected: the arrival named the bastion-session channel but
    #: carried no capability the broker ever issued — no id, an
    #: unknown id, another host's id, or a session already ended.
    UNREGISTERED_SESSION = "unregistered-session"

    #: Rejected: the destination is not in the compiled zone at all.
    UNKNOWN_HOST = "unknown-host"


class AccessRequest:
    """One arrival at the zone, as presented.

    Deliberately unvalidated beyond types: the gate models what came
    over the wire, hostile shapes included, and *answers* them rather
    than refusing to parse them.  ``session_id`` rides along as
    presented — absent, garbled, or borrowed — and the gate's check
    against the broker's registry is what separates a capability from
    a claim.
    """

    __slots__ = ("channel", "destination", "port", "protocol", "session_id", "source")

    def __init__(
        self,
        *,
        destination: str,
        port: int,
        source: str,
        channel: Channel | str,
        protocol: str = "tcp",
        session_id: str | None = None,
    ) -> None:
        self.destination = destination
        self.port = port
        self.source = source
        try:
            self.channel = Channel(channel)
        except ValueError:
            # An unknown channel spelling is not a third way in; it is a
            # direct arrival with an unusual name, and it is evaluated
            # against the same (for the live host: empty) surface.
            self.channel = Channel.DIRECT
        self.protocol = protocol
        self.session_id = session_id

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"AccessRequest(destination={self.destination!r}, "
            f"port={self.port}, source={self.source!r}, "
            f"channel={self.channel!r})"
        )


class AccessDecision:
    """The gate's whole answer: allowed, why, and in what words.

    ``detail`` carries the operator-facing sentence — the one place the
    mechanism explains itself at rejection time, naming the host, the
    port and the surface consulted, so "no inbound port is exposed" is
    a finding an operator can act on rather than a slogan.
    """

    __slots__ = ("allowed", "detail", "reason")

    def __init__(self, *, allowed: bool, reason: AccessReason, detail: str) -> None:
        self.allowed = allowed
        self.reason = reason
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"AccessDecision(allowed={self.allowed}, reason={self.reason!r})"


def authorize_access(
    request: AccessRequest, policy: ZonePolicy, broker: SessionBroker
) -> AccessDecision:
    """Answer one arrival: ride a live bastion session, or be rejected.

    The order of the checks is the order of the sentence.  A session
    arrival is settled by the broker's registry alone — the compiled
    ingress surface is never consulted for it, because a session rides
    a channel the *host* dialed outbound and touches no inbound port at
    all.  Every other arrival is settled by that surface alone, and for
    the live trading host the surface is empty, so everything that is
    not a bastion session — every port, every protocol, every source,
    bastion included — falls to
    :attr:`AccessReason.NO_INBOUND_PORT_EXPOSED`.
    """
    host = policy.host(request.destination)
    if host is None:
        return AccessDecision(
            allowed=False,
            reason=AccessReason.UNKNOWN_HOST,
            detail=(
                f"destination {request.destination!r} is not a host of "
                f"zone {policy.zone!r}. The gate answers for the compiled "
                f"zone and nothing else; an arrival naming a host outside "
                f"it has no surface to be evaluated against and is "
                f"rejected (feature 156)."
            ),
        )

    if request.channel is Channel.BASTION_SESSION:
        session = broker.session(request.session_id)
        if session is None:
            return _unregistered_session(request, policy)
        if not broker.is_live(session.session_id):
            return AccessDecision(
                allowed=False,
                reason=AccessReason.UNREGISTERED_SESSION,
                detail=(
                    f"arrival for {request.destination!r} presented session "
                    f"id {request.session_id!r}, which the broker has "
                    f"ended or whose host channel is withdrawn. A bastion "
                    f"session rides a channel the host dialed out; with "
                    f"the channel gone there is nothing under the id to "
                    f"ride, and the arrival is rejected as surely as a "
                    f"direct one — the live trading host exposes no "
                    f"inbound port to fall back to (§17, feature 156)."
                ),
            )
        if session.host != request.destination:
            return AccessDecision(
                allowed=False,
                reason=AccessReason.UNREGISTERED_SESSION,
                detail=(
                    f"arrival targets {request.destination!r} but session "
                    f"{session.session_id!r} was issued for "
                    f"{session.host!r}. A session id is a capability for "
                    f"one host's channel, not a zone-wide pass — "
                    f"presenting it anywhere else is the label wearing a "
                    f"credential it was never given, and it is rejected "
                    f"(feature 156)."
                ),
            )
        return AccessDecision(
            allowed=True,
            reason=AccessReason.VIA_BASTION_SESSION,
            detail=(
                f"arrival for {request.destination!r} rides bastion "
                f"session {session.session_id!r} — a channel the host "
                f"dialed outbound to the broker, on which "
                f"{session.operator!r} attached. No inbound port is "
                f"consulted or needed: this is §17's single carve-out, "
                f"the one way in (feature 156)."
            ),
        )

    if host.exposes(request.port, request.protocol, request.source):
        return AccessDecision(
            allowed=True,
            reason=AccessReason.BY_INGRESS_RULE,
            detail=(
                f"direct arrival for {request.destination!r} at "
                f"{request.protocol}/{request.port} from "
                f"{request.source!r} matches the host's compiled ingress "
                f"surface. Only a host §17's 'no inbound ports' was never "
                f"said about can answer this way — the bastion, the "
                f"zone's front door (feature 156)."
            ),
        )

    spans = host.inbound_spans()
    if not spans:
        return AccessDecision(
            allowed=False,
            reason=AccessReason.NO_INBOUND_PORT_EXPOSED,
            detail=(
                f"direct arrival for {request.destination!r} at "
                f"{request.protocol}/{request.port} from "
                f"{request.source!r} is rejected because no inbound port "
                f"is exposed on that host: its compiled ingress surface "
                f"is empty, by §17 and by the law that refuses any "
                f"document saying otherwise — not an allowlist that "
                f"forgot this source, but nothing to connect to at all. "
                f"Access is via bastion session only (feature 156)."
            ),
        )
    if host.opening_rules(request.port, request.protocol):
        return AccessDecision(
            allowed=False,
            reason=AccessReason.SOURCE_NOT_ALLOWED,
            detail=(
                f"direct arrival for {request.destination!r} at "
                f"{request.protocol}/{request.port} from "
                f"{request.source!r} is rejected: the host does expose "
                f"that port, but no rule opening it admits this source — "
                f"access there is by allowlist, and this arrival is not "
                f"on it. The distinction matters: the port exists, so the "
                f"remedy is the allowlist or a bastion session, not a "
                f"hunt for a hole that is not there (feature 156)."
            ),
        )
    return AccessDecision(
        allowed=False,
        reason=AccessReason.NO_INBOUND_PORT_EXPOSED,
        detail=(
            f"direct arrival for {request.destination!r} at "
            f"{request.protocol}/{request.port} from {request.source!r} "
            f"is rejected: the host exposes inbound "
            f"{_describe_spans(spans)} and this arrival is not at any of "
            f"them. On the live trading host this reason never fires — "
            f"its surface is empty, so every port is refused with the "
            f"same words (feature 156)."
        ),
    )


def _unregistered_session(
    request: AccessRequest, policy: ZonePolicy
) -> AccessDecision:
    """The label-without-capability rejection, in its own words."""
    return AccessDecision(
        allowed=False,
        reason=AccessReason.UNREGISTERED_SESSION,
        detail=(
            f"arrival for {request.destination!r} claims the bastion-"
            f"session channel but presented session id "
            f"{request.session_id!r}, which the broker of zone "
            f"{policy.zone!r} never issued. Naming the channel is not "
            f"riding it: the only capability the gate honours is an id "
            f"the broker issued for a channel this host dialed out, and "
            f"without one the arrival is judged as what it is — access "
            f"to a host that exposes no inbound port, rejected (§17, "
            f"feature 156)."
        ),
    )


def _describe_spans(spans: tuple[tuple[int, int], ...]) -> str:
    """Render port spans as a human list — ``22``, ``30000-40000``."""
    return ", ".join(
        str(lo) if lo == hi else f"{lo}-{hi}" for lo, hi in spans
    )
