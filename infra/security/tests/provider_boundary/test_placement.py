"""Feature 150: the placement — a call made in the orchestrator reaches the provider.

The sentence's subject and its placement: *System places the provider API call
outside the sandbox in the orchestrator.* Two claims are asserted here, and
they are different claims:

* **a call made in the orchestrator reaches the provider** — the placement's
  normal case, the one the feature exists to make possible. The provider is
  dialled and its answer comes back.
* **the zone is stamped by the object that made the call** — the placement is
  a fact about *who called*, not about what the request said. That is what
  makes it unspoofable from the request: there is no parameter by which the
  sandbox's side of the boundary could place a call in the orchestrator's
  name, because the stamp is not an argument at all.
"""

from __future__ import annotations

import pytest
from helpers import AGENT_AUTHORED_CODE, PROVIDER_REQUEST

from infra.security.provider_boundary import (
    ORCHESTRATOR_ZONE,
    SANDBOX_ZONE,
    Orchestrator,
    ProviderBoundaryError,
    ProviderCall,
    RecordingProviderClient,
)

# ---------------------------------------------------------------------------
# The zones are a closed set — the vocabulary the placement is written in.
# ---------------------------------------------------------------------------


class TestTheZones:
    """Two zones, named once, and no third one admitted by accident."""

    def test_the_two_zones_are_the_systems_two_sides(self) -> None:
        """The boundary has the trusted side and the sandbox, spelled as the
        architecture doc spells them (§18's orchestrator, §17's sandbox)."""
        assert {ORCHESTRATOR_ZONE, SANDBOX_ZONE} == {"orchestrator", "sandbox"}

    def test_the_two_zones_are_distinct(self) -> None:
        """A call outside the sandbox is not a call in it — the whole law
        rests on the two being different names for different places."""
        assert ORCHESTRATOR_ZONE != SANDBOX_ZONE

    def test_a_call_carries_the_zone_it_was_made_from(self) -> None:
        """A call is the request plus its placement, and the placement is
        readable."""
        call = ProviderCall(request=PROVIDER_REQUEST, zone=ORCHESTRATOR_ZONE)
        assert call.zone == ORCHESTRATOR_ZONE
        assert call.request is PROVIDER_REQUEST

    def test_a_call_in_the_orchestrator_is_outside_the_sandbox(self) -> None:
        """The feature's placement, as one readable fact rather than a string
        comparison each caller would have to get right."""
        call = ProviderCall(request=PROVIDER_REQUEST, zone=ORCHESTRATOR_ZONE)
        assert call.made_outside_the_sandbox is True

    def test_a_call_in_the_sandbox_is_not_outside_it(self) -> None:
        """And the same question about a sandbox-stamped call answers no."""
        call = ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
        assert call.made_outside_the_sandbox is False

    def test_an_unknown_zone_is_refused(self) -> None:
        """A third zone is a typo, not a third place — the closed set refuses
        it rather than letting a call be placed where no law covers it."""
        with pytest.raises(ProviderBoundaryError):
            ProviderCall(request=PROVIDER_REQUEST, zone="dev-box")

    def test_an_unknown_zone_is_refused_in_words(self) -> None:
        """The refusal names the zones, so the drift is findable."""
        with pytest.raises(
            ProviderBoundaryError, match=r"orchestrator.*sandbox|sandbox.*orchestrator"
        ):
            ProviderCall(request=PROVIDER_REQUEST, zone="staging")

    @pytest.mark.parametrize(
        "zone",
        [
            None,
            42,
            True,
            ["orchestrator"],
            {"orchestrator"},
            {"zone": "orchestrator"},
            object(),
        ],
    )
    def test_a_zone_of_the_wrong_type_is_refused_by_the_taxonomy(
        self, zone: object
    ) -> None:
        """A zone that is not a string is refused with this boundary's own
        error, not with whatever the membership test happened to raise.

        An unhashable value is the case that matters: the closed set is a
        ``frozenset``, so a plain ``zone not in _ZONES`` would leak a bare
        ``TypeError`` from the set lookup and defeat the single ``except
        ProviderBoundaryError`` the taxonomy exists to support. The seam's
        error vocabulary is this module's, never the standard library's —
        the same discipline :func:`infra.security.network_policy.
        compile_zone_policy` and :class:`infra.security.credential_isolation.
        CredentialScope` keep at their own closed sets.
        """
        with pytest.raises(ProviderBoundaryError):
            ProviderCall(request=PROVIDER_REQUEST, zone=zone)

    def test_a_wrong_typed_zone_names_its_type_in_the_refusal(self) -> None:
        """The message carries the type, so a caller that passed the wrong
        object can see which one it was."""
        with pytest.raises(ProviderBoundaryError, match="list"):
            ProviderCall(request=PROVIDER_REQUEST, zone=["orchestrator"])

    def test_a_wrong_typed_zone_is_refused_identically_to_a_typo(self) -> None:
        """Both are the closed set declining a value: a caller does not get
        two different problems out of one rule."""
        with pytest.raises(ProviderBoundaryError) as wrong_type:
            ProviderCall(request=PROVIDER_REQUEST, zone=["orchestrator"])
        with pytest.raises(ProviderBoundaryError) as typo:
            ProviderCall(request=PROVIDER_REQUEST, zone="dev-box")
        assert type(wrong_type.value) is type(typo.value)

    def test_a_call_must_stamp_a_zone(self) -> None:
        """The zone is required: a default would be a placement chosen by
        omission, and an accidental placement is the one thing this attribute
        may never be."""
        with pytest.raises(TypeError):
            ProviderCall(request=PROVIDER_REQUEST)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# The placement's normal case: the orchestrator calls, the provider answers.
# ---------------------------------------------------------------------------


class TestTheOrchestratorPlacesTheCall:
    """A model call made on the trusted side reaches the provider."""

    def test_the_orchestrator_dials_the_provider(
        self, orchestrator: Orchestrator
    ) -> None:
        """The feature's whole point, in its expected case: the call happens,
        and the provider returns an answer the orchestrator can use."""
        completion = orchestrator.call_provider(PROVIDER_REQUEST)
        assert isinstance(completion, dict)
        assert "text" in completion

    def test_the_provider_is_actually_reached(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """Not merely "no exception": the client's backend ran, which is what
        separates an admitted call from a call that silently went nowhere."""
        orchestrator.call_provider(PROVIDER_REQUEST)
        assert len(recording_provider.calls()) == 1
        assert recording_provider.requests() == (PROVIDER_REQUEST,)

    def test_the_bare_client_admits_an_orchestrator_call(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """The law lives on the client's own seam — ``complete`` — not in the
        orchestrator wrapper, so a deployment that holds a client directly
        still gets it."""
        completion = recording_provider.complete(
            ProviderCall(request=PROVIDER_REQUEST, zone=ORCHESTRATOR_ZONE)
        )
        assert isinstance(completion, dict)

    def test_two_calls_are_two_calls(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """A client serves a campaign, not a single call — the record is a
        sequence, in the order the calls reached the provider."""
        orchestrator.call_provider(PROVIDER_REQUEST)
        orchestrator.call_provider(PROVIDER_REQUEST)
        assert len(recording_provider.calls()) == 2

    def test_every_recorded_call_went_out_from_the_orchestrator(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """What reached the provider was, every time, a call placed outside
        the sandbox — so the record itself is evidence the law held, rather
        than a log that could contain both."""
        orchestrator.call_provider(PROVIDER_REQUEST)
        orchestrator.call_provider(PROVIDER_REQUEST)
        assert {call.zone for call in recording_provider.calls()} == {
            ORCHESTRATOR_ZONE
        }
        assert all(
            call.made_outside_the_sandbox for call in recording_provider.calls()
        )

    def test_a_refused_call_leaves_no_record(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """The record is what the provider saw. A refused call was never
        dialled, so it is absent — the distinction between a refused call and
        a failed one."""
        with pytest.raises(ProviderBoundaryError):
            recording_provider.complete(
                ProviderCall(request=PROVIDER_REQUEST, zone=SANDBOX_ZONE)
            )
        assert recording_provider.calls() == ()


# ---------------------------------------------------------------------------
# The stamp records who called — never what the caller claimed.
# ---------------------------------------------------------------------------


class TestTheStampIsBoundByTheHolder:
    """The zone comes from the calling object, not from the caller's words."""

    def test_the_orchestrators_call_is_stamped_orchestrator(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """Every call the orchestrator makes carries the orchestrator's zone,
        because the orchestrator is the object making it."""
        orchestrator.call_provider(PROVIDER_REQUEST)
        assert recording_provider.calls()[0].zone == ORCHESTRATOR_ZONE

    def test_the_orchestrator_offers_no_way_to_place_the_call_elsewhere(
        self, orchestrator: Orchestrator
    ) -> None:
        """There is no zone parameter to get wrong: ``call_provider`` takes
        the request and nothing else, so a caller cannot ask for the call to
        be placed in the sandbox."""
        import inspect

        parameters = set(
            inspect.signature(Orchestrator.call_provider).parameters
        )
        assert parameters == {"self", "request"}

    def test_a_request_cannot_smuggle_a_zone(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """A request that claims to be a sandbox call is still placed by the
        orchestrator — the placement reads the caller, not the payload, so
        the payload has no say in it."""
        request = {
            "prompt": "propose a signal",
            "zone": SANDBOX_ZONE,
            "made_outside_the_sandbox": False,
        }
        orchestrator.call_provider(request)
        call = recording_provider.calls()[0]
        assert call.zone == ORCHESTRATOR_ZONE
        assert call.request is request

    def test_a_request_cannot_vouch_for_itself(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """Even presenting the correct zone inside the request changes
        nothing: the client reads the call's stamp, which is set by the
        object that made the call."""
        with pytest.raises(ProviderBoundaryError):
            recording_provider.complete(
                ProviderCall(
                    request={"zone": ORCHESTRATOR_ZONE},
                    zone=SANDBOX_ZONE,
                )
            )
        assert recording_provider.calls() == ()

    def test_the_client_refuses_a_non_client_provider(
        self, recording_provider: RecordingProviderClient
    ) -> None:
        """An orchestrator holding something that is not a client would hold
        a call path with no law on it — refused at construction."""
        with pytest.raises(ProviderBoundaryError):
            Orchestrator(provider=object())  # type: ignore[arg-type]

    def test_a_client_whose_responder_is_not_callable_is_refused(self) -> None:
        """A scripted client with nothing to answer with is broken rather
        than scripted, and says so at construction."""
        with pytest.raises(ProviderBoundaryError):
            RecordingProviderClient(responder="not callable")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The round trip the sentence describes runs end to end on the trusted side.
# ---------------------------------------------------------------------------


class TestTheRoundTripRuns:
    """Call, send code in, take code out — in the order the sentence gives."""

    def test_the_orchestrator_walks_the_whole_sentence(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """The feature's three verbs in one flow: the provider is called, the
        code it produced goes in, and the sandbox's code comes out."""
        completion = orchestrator.call_provider(PROVIDER_REQUEST)
        assert isinstance(completion, dict)
        orchestrator.send_code(AGENT_AUTHORED_CODE)
        handle = orchestrator.sandbox_handle()
        assert handle.receive_code() == AGENT_AUTHORED_CODE
        handle.return_code("def signal(window):\n    return window['close']\n")
        assert orchestrator.take_code() == "def signal(window):\n    return window['close']\n"
        assert len(recording_provider.calls()) == 1

    def test_the_client_is_reachable_from_the_trusted_side(
        self, orchestrator: Orchestrator, recording_provider: RecordingProviderClient
    ) -> None:
        """The orchestrator exposes the client it makes calls through, so an
        operator script or a suite can inspect what reached the provider."""
        assert orchestrator.provider is recording_provider
