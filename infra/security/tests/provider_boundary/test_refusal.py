"""Feature 150: outside the sandbox — the refusal, from both sides.

The sentence's law and the claim that orders everything else: *places the
provider API call outside the sandbox.* Two refusals carry it, and they are
one law seen from its two sides:

* **the client refuses a sandbox-stamped call** — the call is not *made* in
  the sandbox. This is the check at the seam that would otherwise perform the
  call, and its ordering is the load-bearing part: it runs before any backend,
  so a refused call never presents a credential and never opens a socket.
* **the sandbox end refuses to originate one at all** — the call is not
  *accepted from* the sandbox either. The handle holds no client, for the
  reason that makes the refusal structural rather than a check: there is no
  argument by which one could be handed in.

§17's first half — "Z1 sandboxes: egress denied by default" — is the runtime
fact underneath both, and its own feature (149) owns its enforcement; what is
asserted here is that the provider call is not the thing sandboxed code uses
to get around it.
"""

from __future__ import annotations

import pytest
from helpers import PROVIDER_REQUEST

from infra.security.provider_boundary import (
    ORCHESTRATOR_ZONE,
    SANDBOX_ZONE,
    CodeChannel,
    Orchestrator,
    ProviderBoundaryError,
    ProviderCall,
    ProviderClient,
    RecordingProviderClient,
    SandboxHandle,
    SandboxProviderCallRefused,
)


class TestTheClientRefusesASandboxCall:
    """The call is not made in the sandbox — the client's seam says so."""

    def test_a_sandbox_stamped_call_is_refused(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """The feature's law at its one enforcement point."""
        with pytest.raises(SandboxProviderCallRefused):
            recording_provider.complete(
                ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
            )

    def test_the_refusal_names_the_placement(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """The refusal says what the rule is and where the call belongs, so an
        operator reading a trace can act on it rather than guess."""
        with pytest.raises(SandboxProviderCallRefused, match="outside"):
            recording_provider.complete(
                ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
            )

    def test_the_refusal_names_both_zones(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """It names where the call was placed and where it is admitted."""
        with pytest.raises(
            SandboxProviderCallRefused,
            match=rf"{SANDBOX_ZONE}.*{ORCHESTRATOR_ZONE}",
        ):
            recording_provider.complete(
                ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
            )

    def test_a_refused_call_never_reaches_the_backend(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """The ordering that makes the refusal a law rather than a warning:
        the check runs first, so no transport is selected and no credential is
        presented for a call made from the wrong side."""
        with pytest.raises(SandboxProviderCallRefused):
            recording_provider.complete(
                ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
            )
        assert recording_provider.calls() == ()

    def test_the_refusal_is_repeatable_and_never_partially_admits(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """Refusing is not a state that can be worn down: the same call
        refused twice is refused twice, and the record is untouched."""
        for _ in range(3):
            with pytest.raises(SandboxProviderCallRefused):
                recording_provider.complete(
                    ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
                )
        assert recording_provider.calls() == ()

    def test_a_refusal_does_not_poison_a_later_admitted_call(
        self,
        orchestrator: Orchestrator,
        recording_provider: RecordingProviderClient,
    ) -> None:
        """The uninterrupted case: a refusal is answered and the boundary goes
        on working, because refusing is a normal answer, not a fault."""
        with pytest.raises(SandboxProviderCallRefused):
            recording_provider.complete(
                ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
            )
        orchestrator.call_provider(PROVIDER_REQUEST)
        assert len(recording_provider.calls()) == 1

    def test_the_refusal_is_a_boundary_error(
        self,
    ) -> None:
        """So a caller that treats every failure of this boundary alike catches
        the taxonomy with one ``except``."""
        assert issubclass(SandboxProviderCallRefused, ProviderBoundaryError)

    def test_the_base_client_refuses_a_sandbox_call_too(self) -> None:
        """The refusal is base behaviour, inherited by every client — an
        author who wrote a transport and never thought about zones still
        gets the law."""

        class Transport(ProviderClient):
            def __init__(self) -> None:
                self.dialed: list[object] = []

            def _send(self, request: object) -> object:
                self.dialed.append(request)
                return "answered"

        client = Transport()
        with pytest.raises(SandboxProviderCallRefused):
            client.complete(
                ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
            )
        assert client.dialed == []
        assert (
            client.complete(
                ProviderCall(request=PROVIDER_REQUEST, zone=ORCHESTRATOR_ZONE)
            )
            == "answered"
        )
        assert client.dialed == [PROVIDER_REQUEST]


class TestTheSandboxCannotOriginateACall:
    """The call is not accepted from the sandbox either — the other side."""

    def test_the_sandbox_handle_refuses_to_call_the_provider(
        self, channel: CodeChannel
    ) -> None:
        """A run that reaches for the provider is refused, plainly."""
        handle = SandboxHandle(channel)
        with pytest.raises(SandboxProviderCallRefused):
            handle.call_provider(PROVIDER_REQUEST)

    def test_the_sandbox_refusal_names_the_zone(
        self, channel: CodeChannel
    ) -> None:
        """It says which side refused, so the operator knows whether the
        client caught it or the sandbox itself did."""
        handle = SandboxHandle(channel)
        with pytest.raises(SandboxProviderCallRefused, match=SANDBOX_ZONE):
            handle.call_provider(PROVIDER_REQUEST)

    def test_the_sandbox_refusal_points_at_the_clause_it_enforces(
        self, channel: CodeChannel
    ) -> None:
        """The message cites the placement and the egress denial underneath
        it, so the code is traceable to the sentence."""
        handle = SandboxHandle(channel)
        with pytest.raises(
            SandboxProviderCallRefused,
            match=r"outside the sandbox.*orchestrator",
        ):
            handle.call_provider(PROVIDER_REQUEST)

    def test_the_attempt_is_answered_the_same_way_whatever_it_asks(
        self, channel: CodeChannel
    ) -> None:
        """The request is accepted and deliberately unread: a run cannot probe
        the boundary by varying its question, so there is no shape of request
        that gets a different answer."""
        handle = SandboxHandle(channel)
        for request in (PROVIDER_REQUEST, None, "", {"zone": ORCHESTRATOR_ZONE}):
            with pytest.raises(SandboxProviderCallRefused):
                handle.call_provider(request)

    def test_the_sandbox_holds_no_provider_client(
        self, channel: CodeChannel
    ) -> None:
        """The refusal is structural, not a check: the handle has no client
        attribute to be bypassed."""
        handle = SandboxHandle(channel)
        assert not hasattr(handle, "provider")
        assert not hasattr(handle, "_provider")

    def test_the_sandbox_handle_takes_only_the_conduit(self) -> None:
        """Its constructor's single parameter is the conduit, so there is no
        argument by which a caller could hand the sandbox a provider seam."""
        import inspect

        parameters = set(inspect.signature(SandboxHandle.__init__).parameters)
        assert parameters == {"self", "channel"}

    def test_the_handle_the_orchestrator_hands_out_has_no_provider(
        self, orchestrator: Orchestrator
    ) -> None:
        """The view the trusted side builds carries the conduit and nothing
        else — the placement is a property of the object graph, not a rule
        someone remembers."""
        handle = orchestrator.sandbox_handle()
        assert not hasattr(handle, "provider")
        with pytest.raises(SandboxProviderCallRefused):
            handle.call_provider(PROVIDER_REQUEST)

    def test_the_orchestrator_hands_out_a_usable_conduit(
        self, orchestrator: Orchestrator
    ) -> None:
        """Refusing the call does not cost the sandbox its actual job: code
        still arrives and code still goes back."""
        handle = orchestrator.sandbox_handle()
        orchestrator.send_code("def signal(window):\n    return 1.0\n")
        assert handle.receive_code() == "def signal(window):\n    return 1.0\n"
        handle.return_code("def signal(window):\n    return 2.0\n")
        assert orchestrator.take_code() == "def signal(window):\n    return 2.0\n"


class TestEgressIsNotTheProviderRoute:
    """The reason the refusal is a real control rather than a formality."""

    def test_the_sandbox_refusal_cites_the_egress_denial(self, channel: CodeChannel) -> None:
        """§17 denies sandbox egress by default; the message says so, because
        the placement only holds *because* there is nowhere for a call to go
        even if one were made."""
        handle = SandboxHandle(channel)
        with pytest.raises(SandboxProviderCallRefused, match="egress|no route"):
            handle.call_provider(PROVIDER_REQUEST)

    def test_a_sandbox_call_has_nothing_under_it_to_dial(
        self, channel: CodeChannel
    ) -> None:
        """There is no client, and a call with no client cannot present a
        credential — the fact the placement rests on. The handle's slots are
        its whole state, so the absence is exhaustive rather than a spot
        check."""
        handle = SandboxHandle(channel)
        with pytest.raises(SandboxProviderCallRefused):
            handle.call_provider(PROVIDER_REQUEST)
        holders = [
            getattr(handle, slot) for slot in SandboxHandle.__slots__
        ]
        assert not any(isinstance(value, ProviderClient) for value in holders)
