"""The bastion session: the one channel that can reach a portless host.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 156: *System
rejects access to the live trading host that does not arrive through a
bastion session, because no inbound port is exposed.*  docs/nullius-
architecture.md §17 spells the carve-out — "Access via bastion or
session manager only" — and this module is the mechanism those two
spellings name.  A "bastion" and a "session manager" differ in where
the brokering control plane lives, not in what a session *is*, so the
model keeps one word for the thing itself and calls it a bastion
session, after the feature sentence.

**A session is a channel the host opened, never one opened to it.**
That is the whole trick, and the reason "no inbound port" and "access
via bastion" are compatible at all.  The live trading host has no
listener (feature 156's law, :mod:`infra.security.network_policy`), so
nobody can connect to it — instead it *dials out*, over the egress
every live-trading host must keep to the broker
(:data:`infra.security.network_policy.SESSION_BROKER_DESTINATION`), and
registers a reverse channel (:meth:`SessionBroker.register_host_channel`).
An operator then attaches at the broker, to a channel that already
exists (:meth:`SessionBroker.attach`), and the session's bytes ride the
connection the host itself made.  Inbound exposure stays at zero not
because a firewall parries connections but because the topology offers
nothing to connect to — §5.2's doctrine, "a namespace with no
interfaces.  Not a firewall rule.", applied at host scope.

**You cannot open a session to the host; you wait for its call.**
:meth:`SessionBroker.attach` refuses an unknown channel
(:class:`UnknownChannelError`) with exactly that reading: attaching is
*answering*, not dialing, and a host that has not dialed out has
nothing to answer.  The same refusal is why an operator cannot be
handed a session for a host whose policy later went dark — a channel
withdrawn (:meth:`SessionBroker.withdraw_host_channel`) kills the
sessions that rode it, because the connection underneath them is gone.

**The session id is a capability, and the label is not.**  What
:meth:`SessionBroker.attach` returns — an opaque
``secrets.token_urlsafe`` id — is the only thing a later arrival can
present to prove it arrived through the session.  The access gate
(:func:`infra.security.host_access.authorize_access`) checks the id
*against the broker's registry*, not against the arrival's own claim
about itself: a request that says ``channel: bastion-session`` with no
id, or with an id the broker never issued, or with an id issued for a
different host, is rejected exactly as a direct connection is, because
naming the channel is not riding it.

The broker here is the policy-time model of the control plane — a
registry the gate consults — not a network service; stdlib-only, and
deliberately deterministic apart from the unguessable session ids
themselves.
"""

from __future__ import annotations

import secrets

__all__ = [
    "BastionSession",
    "BastionSessionError",
    "SessionBroker",
    "UnknownChannelError",
]


class BastionSessionError(Exception):
    """Base of the bastion-session taxonomy.

    One base class so a caller — the operator tooling that establishes
    sessions, the access gate's tests — can catch every failure of the
    session path with a single ``except``.
    """


class UnknownChannelError(BastionSessionError):
    """An operator attached to a channel that does not exist.

    The broker's signature refusal.  Attaching is *answering* a channel
    the host opened; an unknown channel id means the host never dialed
    out (or has since hung up), and there is nothing to answer.  This is
    the mechanism's honesty: with no inbound port on the live trading
    host, no amount of operator intent can create the path — only the
    host's own outbound call can.
    """


class BastionSession:
    """One operator's ride on one host-dialed channel.

    Immutable by construction: it records what happened — which broker
    channel, which host that channel belongs to, which operator
    attached.  Liveness is *not* a field, because it is not a fact
    about the session but a fact about the broker's registry (is the
    channel still registered?  was the session ended?): ask the broker
    with :meth:`SessionBroker.is_live` rather than trusting a copy of
    state that could be stale.
    """

    __slots__ = ("channel_id", "host", "operator", "session_id")

    def __init__(
        self, *, session_id: str, channel_id: str, host: str, operator: str
    ) -> None:
        self.session_id = session_id
        self.channel_id = channel_id
        self.host = host
        self.operator = operator

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"BastionSession(host={self.host!r}, operator={self.operator!r})"
        )


class SessionBroker:
    """The registry of host-dialed channels and the sessions riding them.

    The policy-time model of §17's broker — bastion or session manager
    — as seen from the access gate: something that can be asked, given
    an id an arrival presented, whether that id names a live session to
    the host the arrival targets.  Every method enforces the direction
    the mechanism depends on: hosts register (outbound), operators
    attach (to what registered), and nothing anywhere can create a
    channel *to* a host.
    """

    def __init__(self) -> None:
        # channel_id -> host name: the reverse channels hosts dialed.
        self._channels: dict[str, str] = {}
        # session_id -> BastionSession: the sessions operators opened.
        self._sessions: dict[str, BastionSession] = {}
        # session_id set: sessions ended by their operator.
        self._ended: set[str] = set()

    def register_host_channel(self, host: str) -> str:
        """The host dialed out; record its reverse channel, return the id.

        The one entry path the mechanism has, and it belongs to the
        host: nothing an operator calls creates a channel.  A host may
        hold several channels at once (a real host multiplexes), each
        dial recorded separately.
        """
        channel_id = secrets.token_urlsafe(16)
        self._channels[channel_id] = host
        return channel_id

    def withdraw_host_channel(self, channel_id: str) -> None:
        """The host hung up; its channel — and the sessions riding it — die.

        Withdrawing models the connection closing from the host side.
        Sessions that rode the channel are not patched onto some other
        path; they simply stop being live, and the next arrival citing
        one is rejected by the gate, because the bytes it would ride
        have nowhere to go.
        """
        self._channels.pop(channel_id, None)

    def attach(self, channel_id: str, operator: str) -> BastionSession:
        """An operator attaches to a host-dialed channel; the session begins.

        Refused with :class:`UnknownChannelError` when the channel is
        unknown — including a channel withdrawn since registration —
        because attaching is answering a call, and a host with no
        inbound port places no call an operator could instead place at
        it.  The returned session's id is the capability the operator
        presents on each arrival.
        """
        host = self._channels.get(channel_id)
        if host is None:
            raise UnknownChannelError(
                f"no such channel {channel_id!r} to attach to. Attaching "
                f"is answering a channel the host dialed out to the "
                f"broker — it is never dialing the host, which exposes no "
                f"inbound port to dial (§17, feature 156). Either the "
                f"host has not registered a channel or it has withdrawn "
                f"it, and in both cases there is nothing to answer: wait "
                f"for its outbound call."
            )
        session_id = secrets.token_urlsafe(16)
        session = BastionSession(
            session_id=session_id,
            channel_id=channel_id,
            host=host,
            operator=operator,
        )
        self._sessions[session_id] = session
        return session

    def end_session(self, session_id: str) -> None:
        """The operator ended the session; arrivals citing it stop passing.

        Ending a session ends the *session*, not the host's channel —
        the channel stays registered for the next attach, because the
        host, not the session, owns the outbound connection.
        """
        self._ended.add(session_id)

    def session(self, session_id: str | None) -> BastionSession | None:
        """The named session, or ``None`` when no such session was issued.

        The gate's lookup seam: it passes what the arrival presented
        and gets back what the broker knows, with ``None`` the honest
        answer for an absent, garbled, or never-issued id alike — the
        gate rejects all three the same way, because none of them is a
        capability it issued.
        """
        if session_id is None:
            return None
        return self._sessions.get(session_id)

    def is_live(self, session_id: str) -> bool:
        """Whether the id still names a rideable session.

        Live means all three of: issued by this broker, not ended by
        its operator, and riding a channel still registered — the
        connection underneath the session is the host's, and only the
        host's withdrawal can take it away.
        """
        session = self._sessions.get(session_id)
        if session is None or session_id in self._ended:
            return False
        return session.channel_id in self._channels
