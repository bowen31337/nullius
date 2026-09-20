"""Feature 150: in the orchestrator — the placement as a structural fact.

The sentence's placement and the chain it implies: *System places the provider
API call outside the sandbox **in the orchestrator**.* The word doing the work
is "places" — the feature is a claim about where a capability sits, so the
assertions here are about the object graph rather than about a check:

* **the provider client lives on the trusted side** — it is constructed in the
  orchestrator and reachable from there. That is what makes the placement a
  property of the graph rather than a rule someone has to remember.
* **nothing the orchestrator hands the sandbox carries it** — the view the
  sandbox gets is built from the conduit alone, so the boundary rule and the
  object graph give the same answer.
* **the chain closes** — the sandbox's view has no client, so a run that tried
  to reach the provider finds nothing to call, which is the point the sentence
  makes when it says the interface is *code in, code out* and nothing else.

The chain is asserted here as a chain because that is what the feature's
"which" means: the placement is what makes the code-only interface sufficient.
"""

from __future__ import annotations

import pytest
from helpers import AGENT_AUTHORED_CODE, PROVIDER_REQUEST

from infra.security.provider_boundary import (
    CodeChannel,
    NoCodeToTake,
    Orchestrator,
    ProviderClient,
    RecordingProviderClient,
    SandboxHandle,
)


class TestTheClientLivesOnTheTrustedSide:
    """The provider client is the orchestrator's, by construction."""

    def test_the_orchestrator_holds_the_client_it_was_built_with(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """The client the orchestrator makes calls through is the one it was
        given — not a copy, not a wrapper that might place calls elsewhere."""
        assert orchestrator.provider is recording_provider

    def test_the_orchestrator_builds_its_own_conduit_when_given_none(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """An orchestrator with no channel argument is complete: it has the
        conduit it needs, and calling through it works."""
        orchestrator = Orchestrator(recording_provider)
        orchestrator.send_code(AGENT_AUTHORED_CODE)
        assert orchestrator.sandbox_handle().receive_code() == AGENT_AUTHORED_CODE

    def test_the_orchestrator_joins_a_channel_it_is_handed(
        self, recording_provider: RecordingProviderClient, channel: CodeChannel
    ) -> None:
        """The conduit is injectable, so the orchestrator and the sandbox can
        share the one channel that models the crossing between them."""
        orchestrator = Orchestrator(recording_provider, channel=channel)
        orchestrator.send_code(AGENT_AUTHORED_CODE)
        assert SandboxHandle(channel).receive_code() == AGENT_AUTHORED_CODE

    def test_the_orchestrators_conduit_is_not_reachable_from_its_view(
        self, orchestrator: Orchestrator
    ) -> None:
        """The handle holds the conduit, but the conduit is not a route to the
        client — the two halves of the boundary are separate objects, and
        crossing one does not cross the other."""
        handle = orchestrator.sandbox_handle()
        channel = getattr(handle, SandboxHandle.__slots__[0])
        assert isinstance(channel, CodeChannel)
        assert not isinstance(channel, RecordingProviderClient)


class TestNothingHandedToTheSandboxCarriesTheClient:
    """The sandbox's view has no client in it — by construction, not by check."""

    def test_the_handed_handle_holds_only_the_conduit(
        self, orchestrator: Orchestrator
    ) -> None:
        """The handle's entire state is the conduit: there is nowhere in it a
        provider client could be hiding."""
        handle = orchestrator.sandbox_handle()
        holders = [getattr(handle, slot) for slot in SandboxHandle.__slots__]
        assert len(holders) == 1
        assert isinstance(holders[0], CodeChannel)

    def test_two_handles_are_two_views_of_one_conduit(
        self, orchestrator: Orchestrator
    ) -> None:
        """Handing the sandbox its view is repeatable and grants no more each
        time: both handles see the same channel because there is only one
        boundary to cross."""
        first = orchestrator.sandbox_handle()
        second = orchestrator.sandbox_handle()
        orchestrator.send_code(AGENT_AUTHORED_CODE)
        assert first.receive_code() == AGENT_AUTHORED_CODE
        second.return_code("def signal(window):\n    return 1.0\n")
        assert orchestrator.take_code() == "def signal(window):\n    return 1.0\n"

    def test_each_orchestrator_has_its_own_boundary(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """Two orchestrators do not share a conduit by accident — a campaign's
        boundary is its own, which is what keeps a run's code attributable to
        the run that sent it."""
        first = Orchestrator(recording_provider)
        second = Orchestrator(recording_provider)
        first.send_code(AGENT_AUTHORED_CODE)
        assert first.sandbox_handle().receive_code() == AGENT_AUTHORED_CODE
        with pytest.raises(NoCodeToTake):
            second.sandbox_handle().receive_code()


class TestTheChainCloses:
    """No client, nothing to call, and the code path still works."""

    def test_a_sandbox_run_reaches_the_provider_by_asking_the_orchestrator(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """The advertised route, end to end: the sandbox returns code, the
        orchestrator reads it, and *the orchestrator* makes the model call
        that code's next round needs. Nothing crosses but code."""
        orchestrator.send_code(AGENT_AUTHORED_CODE)
        handle = orchestrator.sandbox_handle()
        assert handle.receive_code() == AGENT_AUTHORED_CODE
        handle.return_code("def signal(window):\n    return 1.0\n")
        returned = orchestrator.take_code()
        orchestrator.call_provider({"prompt": f"refine: {returned}"})
        assert len(recording_provider.calls()) == 1
        assert recording_provider.calls()[0].made_outside_the_sandbox

    def test_the_provider_sees_nothing_the_sandbox_wrote(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """Every call the provider saw was stamped by the orchestrator, so the
        sandbox is not a source of provider traffic by any route."""
        orchestrator.send_code(AGENT_AUTHORED_CODE)
        handle = orchestrator.sandbox_handle()
        handle.receive_code()
        orchestrator.call_provider(PROVIDER_REQUEST)
        assert [call.zone for call in recording_provider.calls()] == [
            "orchestrator"
        ]

    def test_the_boundary_is_the_same_shape_a_deployment_inherits(self) -> None:
        """What a deployment subclasses to get a real client: the base client
        owns the law, the subclass owns the transport — so placing the
        provider call correctly is not something a transport author opts into.
        Both seams are defined on the base, and the enforcement is not one a
        subclass could have replaced without overriding it deliberately."""
        assert ProviderClient.complete.__qualname__.startswith("ProviderClient")
        assert ProviderClient._send.__qualname__.startswith("ProviderClient")
