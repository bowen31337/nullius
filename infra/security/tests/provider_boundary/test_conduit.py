"""Feature 150: code in, code out — the conduit, and why it is enough.

The sentence's mechanism and its reason for existing: *which sends code in and
takes code out.* Two claims, and the second is the one the feature rests on:

* **code goes in and code comes back** — the round trip, both directions, in
  the order the sentence gives. The two directions are kept apart because they
  are different facts: the source the agent wrote is not the source the sandbox
  handed back, and a run spends most of its time holding both.
* **only code crosses** — the conduit's law. The check is a *type* check and
  deliberately not a content check: a conduit that scanned source for
  suspicious strings would be enforcing a judgement no string comparison can
  make, whereas "the thing crossing is the thing the boundary is for" is a
  claim a type check can actually keep. What makes the interface sufficient is
  structural and lies outside the conduit — no client, no credential, no egress
  on the sandbox's side (``test_boundary.py``, ``test_refusal.py``) — which is
  why the code-only interface is a complete description rather than a leak.

A blank payload is *not* refused here, and ``test_the_payload_is_not_inspected``
says so on purpose: content is the evaluator's question (feature 148), not the
conduit's, and a law that quietly grew a content rule would be one this boundary
could not honestly claim to keep.
"""

from __future__ import annotations

import pytest
from helpers import AGENT_AUTHORED_CODE, SANDBOX_RETURNED_CODE

from infra.security.provider_boundary import (
    CodeChannel,
    NoCodeToTake,
    Orchestrator,
    PayloadNotCode,
    ProviderBoundaryError,
    SandboxHandle,
)


class TestCodeGoesInAndComesBack:
    """The round trip, direction by direction."""

    def test_code_sent_in_is_received(self, channel: CodeChannel) -> None:
        """The in direction, in its expected case."""
        channel.send_code(AGENT_AUTHORED_CODE)
        assert channel.receive_code() == AGENT_AUTHORED_CODE

    def test_code_returned_comes_back_out(self, channel: CodeChannel) -> None:
        """The out direction, in its expected case."""
        channel.return_code(SANDBOX_RETURNED_CODE)
        assert channel.take_code() == SANDBOX_RETURNED_CODE

    def test_the_two_directions_are_different_payloads(
        self, channel: CodeChannel
    ) -> None:
        """The conduit holds a send and its answer at once — which is the
        state a run spends most of its time in, and the reason one slot would
        not do."""
        channel.send_code(AGENT_AUTHORED_CODE)
        channel.return_code(SANDBOX_RETURNED_CODE)
        assert channel.pending_inbound() == 1
        assert channel.pending_outbound() == 1
        assert channel.receive_code() == AGENT_AUTHORED_CODE
        assert channel.take_code() == SANDBOX_RETURNED_CODE

    def test_the_whole_round_trip_through_the_boundary(
        self, orchestrator: Orchestrator
    ) -> None:
        """The sentence as one flow, through the two ends a deployment uses:
        the orchestrator sends, the sandbox reads and answers, the orchestrator
        takes."""
        handle = orchestrator.sandbox_handle()
        orchestrator.send_code(AGENT_AUTHORED_CODE)
        assert handle.receive_code() == AGENT_AUTHORED_CODE
        handle.return_code(SANDBOX_RETURNED_CODE)
        assert orchestrator.take_code() == SANDBOX_RETURNED_CODE

    def test_each_direction_is_fifo(
        self, orchestrator: Orchestrator
    ) -> None:
        """Two sends are answered in the order they were sent, so what came
        out is attributable to what went in without a correlation id the
        feature never mentions."""
        handle = orchestrator.sandbox_handle()
        orchestrator.send_code("first")
        orchestrator.send_code("second")
        assert handle.receive_code() == "first"
        assert handle.receive_code() == "second"

    def test_the_returned_direction_is_fifo(self, orchestrator: Orchestrator) -> None:
        """And the same on the way back."""
        handle = orchestrator.sandbox_handle()
        handle.return_code("one")
        handle.return_code("two")
        assert orchestrator.take_code() == "one"
        assert orchestrator.take_code() == "two"

    def test_a_drained_inbound_direction_is_empty(
        self, channel: CodeChannel
    ) -> None:
        """Once taken, the payload is gone: the conduit is a channel, not a
        buffer that re-serves what it already handed over."""
        channel.send_code(AGENT_AUTHORED_CODE)
        channel.receive_code()
        assert channel.pending_inbound() == 0
        with pytest.raises(NoCodeToTake):
            channel.receive_code()

    def test_a_drained_outbound_direction_is_empty(
        self, channel: CodeChannel
    ) -> None:
        """Same for the returned code — a second take does not re-read the
        sandbox's answer."""
        channel.return_code(SANDBOX_RETURNED_CODE)
        channel.take_code()
        assert channel.pending_outbound() == 0
        with pytest.raises(NoCodeToTake):
            channel.take_code()

    def test_a_fresh_conduit_holds_nothing(self, channel: CodeChannel) -> None:
        """A run starts with an empty channel, in both directions."""
        assert channel.pending_inbound() == 0
        assert channel.pending_outbound() == 0


class TestAnEmptyDirectionIsRefused:
    """A missing payload is not an empty one."""

    def test_reading_code_that_was_never_sent_is_refused(
        self, channel: CodeChannel
    ) -> None:
        """The sandbox's read with nothing queued is refused, because a
        sandbox that executed an empty payload believing it had been sent
        code would report on a run that never happened."""
        with pytest.raises(NoCodeToTake):
            channel.receive_code()

    def test_taking_code_that_was_never_returned_is_refused(
        self, channel: CodeChannel
    ) -> None:
        """And the orchestrator's read on the way back, for the same reason."""
        with pytest.raises(NoCodeToTake):
            channel.take_code()

    def test_an_empty_send_does_not_satisfy_a_later_read(
        self, channel: CodeChannel
    ) -> None:
        """Sending nothing is not sending: the direction stays empty and the
        read is still refused."""
        channel.send_code("")
        assert channel.pending_inbound() == 1
        assert channel.receive_code() == ""
        with pytest.raises(NoCodeToTake):
            channel.receive_code()

    def test_the_sandbox_read_is_refused_through_the_handle(
        self, channel: CodeChannel
    ) -> None:
        """The refusal is the handle's too, since the handle is a view of the
        conduit rather than a place with its own state."""
        handle = SandboxHandle(channel)
        with pytest.raises(NoCodeToTake):
            handle.receive_code()

    def test_the_orchestrator_take_is_refused_through_the_wrapper(
        self, orchestrator: Orchestrator
    ) -> None:
        """And through the orchestrator's own take."""
        with pytest.raises(NoCodeToTake):
            orchestrator.take_code()

    def test_no_code_to_take_is_a_boundary_error(self) -> None:
        """So one ``except`` catches every failure of this boundary."""
        assert issubclass(NoCodeToTake, ProviderBoundaryError)


class TestOnlyCodeCrosses:
    """The conduit's type law, in both directions."""

    @pytest.mark.parametrize(
        "payload",
        [
            b"def signal(window): ...",
            {"prompt": "propose a signal"},
            ["def signal(window): ..."],
            42,
            None,
        ],
    )
    def test_a_non_source_payload_sent_in_is_refused(
        self, channel: CodeChannel, payload: object
    ) -> None:
        """Anything that is not source text is refused rather than coerced:
        the conduit carries code, and only code."""
        with pytest.raises(PayloadNotCode):
            channel.send_code(payload)
        assert channel.pending_inbound() == 0

    @pytest.mark.parametrize(
        "payload",
        [
            b"def signal(window): ...",
            {"text": "def signal(window): ..."},
            {"score_vector": [0.1, 0.2]},
            3.14,
            None,
        ],
    )
    def test_a_non_source_payload_returned_is_refused(
        self, channel: CodeChannel, payload: object
    ) -> None:
        """And on the way out — the sandbox's answer is code, and a *result*
        smuggled back as if it were source is refused. Feature 166 carries the
        score vector over the IPC channel; keeping the two apart is what stops
        the answer channel becoming a general-purpose pipe out."""
        with pytest.raises(PayloadNotCode):
            channel.return_code(payload)
        assert channel.pending_outbound() == 0

    def test_the_refusal_names_what_was_offered(self, channel: CodeChannel) -> None:
        """The message names the type, so a caller that passed the wrong
        object can see which one it was."""
        with pytest.raises(PayloadNotCode, match="dict"):
            channel.send_code({"prompt": "propose a signal"})

    def test_a_provider_request_offered_as_code_is_refused(
        self, channel: CodeChannel
    ) -> None:
        """The case that matters: a bug that routed the request object into
        the conduit is caught at the door rather than stringified through
        it."""
        with pytest.raises(PayloadNotCode):
            channel.send_code({"prompt": "propose a signal", "model": "frontier"})

    def test_payload_not_code_is_a_boundary_error(self) -> None:
        """One ``except`` for the taxonomy."""
        assert issubclass(PayloadNotCode, ProviderBoundaryError)

    def test_the_payload_is_not_inspected(self, channel: CodeChannel) -> None:
        """A blank module is *not* refused: this conduit's law is a type
        check, and what a blank module means is the evaluator's question
        (feature 148), not the boundary's. A conduit that grew a content rule
        would be claiming a judgement no string comparison can make."""
        channel.send_code("")
        assert channel.receive_code() == ""

    def test_source_text_of_any_content_crosses(self, channel: CodeChannel) -> None:
        """And a payload that no content rule would like still crosses: the
        boundary does not pretend to tell innocent source from hostile
        source, because what actually holds is that there is no provider
        client and no egress on the far side of the conduit."""
        source = "import socket\nsocket.socket().connect(('provider.example', 443))\n"
        channel.send_code(source)
        assert channel.receive_code() == source

    def test_the_sandbox_handle_holds_the_conduit_to_the_same_law(self) -> None:
        """The handle's return is the conduit's return — the law is written
        once, at the conduit, and the handle does not restate it."""
        handle = SandboxHandle(CodeChannel())
        with pytest.raises(PayloadNotCode):
            handle.return_code({"score_vector": [0.1, 0.2]})

    def test_the_orchestrators_send_is_held_to_the_same_law(
        self, orchestrator: Orchestrator
    ) -> None:
        """And the orchestrator's send, for the same reason."""
        with pytest.raises(PayloadNotCode):
            orchestrator.send_code(object())


class TestTheConduitIsTheSandboxsWholeSurface:
    """What the sandbox can reach across the boundary, exhaustively."""

    def test_the_handle_exposes_the_three_things_the_sentence_names(self) -> None:
        """Code in, code out, and the refusal — a sandbox's surface is the
        sentence's verbs and nothing wider."""
        surface = {
            name
            for name in dir(SandboxHandle)
            if not name.startswith("_")
        }
        assert surface == {"call_provider", "receive_code", "return_code"}

    def test_the_conduit_exposes_only_the_two_directions(self) -> None:
        """And the conduit's own surface: two directions, each readable from
        its own end, plus the depth an operator inspects."""
        surface = {
            name
            for name in dir(CodeChannel)
            if not name.startswith("_")
        }
        assert surface == {
            "pending_inbound",
            "pending_outbound",
            "receive_code",
            "return_code",
            "send_code",
            "take_code",
        }

    def test_a_sandbox_that_receives_and_returns_never_touches_the_provider(
        self, orchestrator: Orchestrator
    ) -> None:
        """The sandbox's actual job — read code, return code — leaves the
        provider record empty, which is the placement holding under use
        rather than at rest."""
        handle = orchestrator.sandbox_handle()
        orchestrator.send_code(AGENT_AUTHORED_CODE)
        received = handle.receive_code()
        handle.return_code(received.replace("24", "12"))
        assert orchestrator.take_code() == received.replace("24", "12")
        assert orchestrator.provider.calls() == ()
