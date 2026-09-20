"""The gate: every arrival answered, all but one path rejected.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 156: *System
rejects access to the live trading host that does not arrive through a
bastion session, because no inbound port is exposed.*  These tests
take the sentence as a contract over arrivals: every direct arrival at
the live trading host — every port, every protocol, every source, the
bastion included — is rejected with the sentence's own reason; only a
capability the broker issued, for that host, still live, is admitted.
"""

from __future__ import annotations

import pytest

from infra.security import (
    AccessReason,
    AccessRequest,
    Channel,
    SessionBroker,
    authorize_access,
)


def _direct(
    destination: str = "live-trading-1",
    port: int = 22,
    source: str = "10.20.0.7",
    protocol: str = "tcp",
) -> AccessRequest:
    return AccessRequest(
        destination=destination,
        port=port,
        source=source,
        channel=Channel.DIRECT,
        protocol=protocol,
    )


def _via_session(
    session_id: str | None,
    destination: str = "live-trading-1",
    port: int = 22,
) -> AccessRequest:
    return AccessRequest(
        destination=destination,
        port=port,
        source="10.20.0.7",
        channel=Channel.BASTION_SESSION,
        session_id=session_id,
    )


class TestDirectArrivalsAtTheLiveHost:
    """The 'because': there is no port to connect to."""

    @pytest.mark.parametrize("port", [22, 80, 443, 3389, 5432, 9092, 65535])
    def test_every_port_is_rejected(self, live_zone, port: int) -> None:
        decision = authorize_access(
            _direct(port=port), live_zone, SessionBroker()
        )
        assert not decision.allowed
        assert decision.reason is AccessReason.NO_INBOUND_PORT_EXPOSED
        assert "no inbound port" in decision.detail

    @pytest.mark.parametrize("protocol", ["tcp", "udp", "sctp"])
    def test_every_protocol_is_rejected(
        self, live_zone, protocol: str
    ) -> None:
        decision = authorize_access(
            _direct(protocol=protocol), live_zone, SessionBroker()
        )
        assert decision.reason is AccessReason.NO_INBOUND_PORT_EXPOSED

    @pytest.mark.parametrize(
        "source",
        [
            "10.20.0.7",      # an operator machine, inside the allowlist
            "203.0.113.9",    # the open internet
            "127.0.0.1",      # the host itself
            "bastion-1",      # the bastion — the drift wearing a halo
        ],
    )
    def test_every_source_is_rejected(self, live_zone, source: str) -> None:
        decision = authorize_access(
            _direct(source=source), live_zone, SessionBroker()
        )
        assert decision.reason is AccessReason.NO_INBOUND_PORT_EXPOSED

    def test_the_rejection_names_the_host_and_port(
        self, live_zone
    ) -> None:
        decision = authorize_access(_direct(port=4433), live_zone, SessionBroker())
        assert "live-trading-1" in decision.detail
        assert "4433" in decision.detail

    def test_an_unknown_channel_spelling_is_still_direct(
        self, live_zone
    ) -> None:
        """A invented channel name is not a third way in."""
        request = AccessRequest(
            destination="live-trading-1",
            port=22,
            source="10.20.0.7",
            channel="operator-vpn",   # not a Channel member
        )
        assert request.channel is Channel.DIRECT
        decision = authorize_access(request, live_zone, SessionBroker())
        assert decision.reason is AccessReason.NO_INBOUND_PORT_EXPOSED


class TestBastionSessions:
    """The carve-out: a capability the broker issued, still live."""

    def test_a_live_session_to_the_host_is_admitted(
        self, live_zone, broker_with_live_session
    ) -> None:
        broker, session = broker_with_live_session
        decision = authorize_access(
            _via_session(session.session_id), live_zone, broker
        )
        assert decision.allowed
        assert decision.reason is AccessReason.VIA_BASTION_SESSION

    def test_a_session_reaches_any_port_on_the_host(
        self, live_zone, broker_with_live_session
    ) -> None:
        """The ride touches no inbound port, so the port is not consulted."""
        broker, session = broker_with_live_session
        for port in (22, 443, 8080):
            decision = authorize_access(
                _via_session(session.session_id, port=port), live_zone, broker
            )
            assert decision.allowed

    def test_no_session_id_is_rejected(self, live_zone) -> None:
        """The channel label is not the credential."""
        broker = SessionBroker()
        decision = authorize_access(
            _via_session(None), live_zone, broker
        )
        assert not decision.allowed
        assert decision.reason is AccessReason.UNREGISTERED_SESSION

    def test_unknown_session_id_is_rejected(
        self, live_zone, broker_with_live_session
    ) -> None:
        broker, _ = broker_with_live_session
        decision = authorize_access(
            _via_session("forged-id"), live_zone, broker
        )
        assert decision.reason is AccessReason.UNREGISTERED_SESSION

    def test_another_hosts_session_is_rejected(
        self, live_zone, broker_with_live_session
    ) -> None:
        """A session id is a capability for one host, not a zone pass."""
        broker, session = broker_with_live_session
        decision = authorize_access(
            _via_session(session.session_id, destination="bastion-1"),
            live_zone,
            broker,
        )
        assert decision.reason is AccessReason.UNREGISTERED_SESSION

    def test_ended_session_is_rejected(
        self, live_zone, broker_with_live_session
    ) -> None:
        broker, session = broker_with_live_session
        broker.end_session(session.session_id)
        decision = authorize_access(
            _via_session(session.session_id), live_zone, broker
        )
        assert decision.reason is AccessReason.UNREGISTERED_SESSION

    def test_session_on_a_withdrawn_channel_is_rejected(
        self, live_zone, broker_with_live_session
    ) -> None:
        broker, session = broker_with_live_session
        broker.withdraw_host_channel(session.channel_id)
        decision = authorize_access(
            _via_session(session.session_id), live_zone, broker
        )
        assert decision.reason is AccessReason.UNREGISTERED_SESSION


class TestTheScope:
    """The law is about the live host, not a blanket over the zone."""

    def test_operators_still_reach_the_bastion_front_door(self, live_zone) -> None:
        decision = authorize_access(
            _direct(destination="bastion-1", port=22, source="10.20.0.7"),
            live_zone,
            SessionBroker(),
        )
        assert decision.allowed
        assert decision.reason is AccessReason.BY_INGRESS_RULE

    def test_bastion_door_refuses_outside_the_allowlist(
        self, live_zone
    ) -> None:
        decision = authorize_access(
            _direct(destination="bastion-1", port=22, source="203.0.113.9"),
            live_zone,
            SessionBroker(),
        )
        assert not decision.allowed
        assert decision.reason is AccessReason.SOURCE_NOT_ALLOWED

    def test_unknown_destination_is_rejected(self, live_zone) -> None:
        decision = authorize_access(
            _direct(destination="research-1"), live_zone, SessionBroker()
        )
        assert decision.reason is AccessReason.UNKNOWN_HOST

    def test_a_refused_bastion_source_is_not_an_absent_port(
        self, live_zone
    ) -> None:
        """The two rejections name different remedies, so they differ.

        The bastion's port 22 *is* exposed; this arrival is off the
        allowlist.  Reading that as ``no-inbound-port-exposed`` would
        send an operator hunting for a hole that is not there — and,
        worse, would make the live host's rejection of every source
        indistinguishable from a rule that merely omitted one.
        """
        off_list = authorize_access(
            _direct(destination="bastion-1", port=22, source="203.0.113.9"),
            live_zone,
            SessionBroker(),
        )
        closed_port = authorize_access(
            _direct(destination="bastion-1", port=9092, source="10.20.0.7"),
            live_zone,
            SessionBroker(),
        )
        assert off_list.reason is AccessReason.SOURCE_NOT_ALLOWED
        assert closed_port.reason is AccessReason.NO_INBOUND_PORT_EXPOSED
        assert off_list.reason is not closed_port.reason

    def test_the_live_host_never_answers_source_not_allowed(
        self, live_zone
    ) -> None:
        """Its surface is empty everywhere, so every source reads the same.

        ``source-not-allowed`` presupposes a rule that opens the port —
        a list this arrival is not on.  The live trading host has no
        such rule at any port, which is the feature's law: the refusal
        is "nothing to connect to", never "not on the list".
        """
        for port in (22, 443, 8080, 65535):
            for source in ("10.20.0.7", "203.0.113.9", "bastion-1"):
                decision = authorize_access(
                    _direct(port=port, source=source), live_zone, SessionBroker()
                )
                assert (
                    decision.reason is AccessReason.NO_INBOUND_PORT_EXPOSED
                ), f"{port} from {source} answered {decision.reason!r}"

    def test_allowlist_is_by_containment_not_literal(
        self, live_zone
    ) -> None:
        """10.20.0.0/24 covers 10.20.0.7 — a network, not a machine list."""
        decision = authorize_access(
            _direct(destination="bastion-1", port=22, source="10.20.0.254"),
            live_zone,
            SessionBroker(),
        )
        assert decision.allowed
