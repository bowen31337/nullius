"""The mechanism: sessions ride channels the host dialed out.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 156 — the
"arrives through a bastion session" half.  These tests hold the
broker to the direction the whole design depends on: hosts register
(outbound), operators attach to what registered, and nothing anywhere
can create a channel *to* a host with no inbound port.
"""

from __future__ import annotations

import pytest

from infra.security import (
    BastionSession,
    SessionBroker,
    UnknownChannelError,
)


class TestHostDialsOut:
    """The only entry path the mechanism has belongs to the host."""

    def test_registration_returns_an_opaque_channel_id(self) -> None:
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        assert isinstance(channel, str) and channel

    def test_two_registrations_are_two_channels(self) -> None:
        """A host may multiplex; each dial is recorded separately."""
        broker = SessionBroker()
        first = broker.register_host_channel("live-trading-1")
        second = broker.register_host_channel("live-trading-1")
        assert first != second


class TestAttach:
    """Attaching is answering a call, never placing one at the host."""

    def test_attach_to_a_registered_channel_opens_a_session(self) -> None:
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        session = broker.attach(channel, operator="on-call")
        assert isinstance(session, BastionSession)
        assert session.host == "live-trading-1"
        assert session.operator == "on-call"
        assert session.channel_id == channel

    def test_attach_to_an_unknown_channel_is_refused(self) -> None:
        broker = SessionBroker()
        with pytest.raises(UnknownChannelError) as caught:
            broker.attach("never-registered", operator="on-call")
        assert "dialed" in str(caught.value) or "outbound" in str(caught.value)

    def test_attach_after_withdrawal_is_refused(self) -> None:
        """The host hung up; there is nothing left to answer."""
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        broker.withdraw_host_channel(channel)
        with pytest.raises(UnknownChannelError):
            broker.attach(channel, operator="on-call")

    def test_session_ids_are_unguessable_in_practice(self) -> None:
        """Distinct attach, distinct capability — no shared secret."""
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        first = broker.attach(channel, operator="on-call")
        second = broker.attach(channel, operator="on-call")
        assert first.session_id != second.session_id


class TestLiveness:
    """A session is live while its channel stands and it is not ended."""

    def test_fresh_session_is_live(self) -> None:
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        session = broker.attach(channel, operator="on-call")
        assert broker.is_live(session.session_id)

    def test_ended_session_is_not_live(self) -> None:
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        session = broker.attach(channel, operator="on-call")
        broker.end_session(session.session_id)
        assert not broker.is_live(session.session_id)

    def test_withdrawing_the_channel_kills_its_sessions(self) -> None:
        """The bytes ride the host's connection; gone connection, no ride."""
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        session = broker.attach(channel, operator="on-call")
        broker.withdraw_host_channel(channel)
        assert not broker.is_live(session.session_id)

    def test_ending_a_session_keeps_the_channel(self) -> None:
        """The host owns the connection, not the operator's session."""
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        session = broker.attach(channel, operator="on-call")
        broker.end_session(session.session_id)
        reattached = broker.attach(channel, operator="on-call-2")
        assert broker.is_live(reattached.session_id)


class TestTheLookupSeam:
    """What the gate passes, and what the broker answers."""

    def test_session_by_id(self) -> None:
        broker = SessionBroker()
        channel = broker.register_host_channel("live-trading-1")
        session = broker.attach(channel, operator="on-call")
        assert broker.session(session.session_id) is session

    def test_none_in_none_out(self) -> None:
        """An arrival with no id gets the honest no-capability answer."""
        assert SessionBroker().session(None) is None

    def test_garbled_id_is_none_not_an_error(self) -> None:
        """The gate rejects all unknown spellings the same way."""
        assert SessionBroker().session("not-an-id") is None
