"""Feature 159's law: a run whose payload did not cross the channel is refused.

app_spec.xml, "Untrusted Code Sandbox", feature 159: *System rejects a
sandboxed run whose payload did not arrive over the IPC channel, because the
sandbox holds no filesystem mounts.*  This file tests that sentence clause by
clause, because a gate that admitted any two of them would be a different and
worse feature:

* **a sandboxed run** — the subject, the same unit feature 157's gate answers;
  it is modelled here as a :class:`~sandbox.payload.PayloadRun`, the half of
  §5.2's call this law has a claim about — the ``payload`` and the ``channel``
  that would have delivered it;
* **whose payload did not arrive over the IPC channel** — the evidence
  question, and the one this module exists to answer honestly.  Arrival is a
  property of the *channel*, not of the bytes, so every test hands the gate a
  real :class:`~sandbox.transfer.TransferChannel` (feature 166) that a real
  :class:`~contract.window.MarketWindow` was sent over, and asks whether the
  run's ``payload`` is the bytes that crossed;
* **because the sandbox holds no filesystem mounts** — the because-clause, the
  reason the refusal is total rather than a warning, and what the
  ``by-filesystem`` spelling names most directly;
* **rejects** — the shape of the answer: :func:`authorize_payload_run` *answers*
  every run with a :class:`~sandbox.payload.PayloadDecision` and raises for
  none, for the reason feature 157's gate raises none — a pipeline offers
  thousands of runs unattended, and *"this one's window never crossed"* must
  reach an operator as a fact about a run rather than a crashed evaluator.  The
  raise lives on :meth:`~sandbox.payload.PayloadDecision.require`, the
  launcher's last line before the spawn.

The spellings of not-arriving are the audit vocabulary, and each test pins the
one reason it expects — :class:`~sandbox.payload.PayloadReason` — because a
caller repairing a dispatch needs to know which side of the send went wrong, and
a gate that collapsed them would send an operator looking for the wrong repair.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import materialized_window
from sandbox import (
    PAYLOAD_CHANNEL_CODE,
    PayloadChannelRequired,
    PayloadReason,
    PayloadRun,
    SandboxPayload,
    authorize_payload_run,
    sandbox_payload,
)
from sandbox.payload import WINDOW_ATTRIBUTE
from sandbox.transfer import TransferChannel

#: The member's ``src/`` — the package-parent the loader scans.
MEMBER_SRC = Path(sandbox.__file__).resolve().parent.parent


def _run(payload: object = None, channel: object = None, *, node_id: str = "") -> PayloadRun:
    """A run handed to the gate: the payload the run was dispatched with, and
    the channel that would have delivered it."""
    return PayloadRun(payload=payload, channel=channel, node_id=node_id)


class TestAdmission:
    """The one path to a spawn: the channel holds a window and the payload is it."""

    def test_a_run_dispatched_with_the_window_that_crossed_is_admitted(self) -> None:
        channel = TransferChannel()
        channel.send_window(materialized_window())
        window = channel.window_bytes

        decision = authorize_payload_run(_run(payload=window, channel=channel))

        assert decision.admitted is True
        assert decision.reason is PayloadReason.OVER_IPC
        # The payload the box will evaluate is the window the channel holds,
        # read back off the channel rather than trusted from the argument.
        assert decision.payload == window

    def test_require_returns_the_window_that_crossed(self) -> None:
        channel = TransferChannel()
        channel.send_window(materialized_window())
        window = channel.window_bytes

        returned = authorize_payload_run(_run(payload=window, channel=channel)).require()

        assert returned == window

    def test_a_run_with_no_payload_argument_is_admitted_on_the_channel_alone(self) -> None:
        # ``payload=None`` with a loaded channel: the channel states the arrival
        # once, in the one place it is provable, rather than twice in places
        # that could disagree.  This is the §5.2 call site — the window goes
        # over the channel and the run is dispatched against that channel.
        channel = TransferChannel()
        channel.send_window(materialized_window())

        decision = authorize_payload_run(_run(payload=None, channel=channel))

        assert decision.admitted is True
        assert decision.reason is PayloadReason.OVER_IPC
        assert decision.payload == channel.window_bytes

    def test_the_admitted_decision_carries_the_channels_facts(self) -> None:
        # The return leg's alignment check needs no second read of the channel:
        # the gate hands the caller the :class:`~sandbox.transfer.WindowFacts`
        # the channel declared about the window it holds.
        channel = TransferChannel()
        facts = channel.send_window(materialized_window())

        decision = authorize_payload_run(_run(payload=channel.window_bytes, channel=channel))

        assert decision.facts is facts

    def test_a_memoryview_payload_is_accepted_and_copied(self) -> None:
        # The channel is the provenance, not the buffer: a view over someone
        # else's allocation is read for comparison and copied, the stance
        # feature 166's transfer law takes toward the same quantity.
        channel = TransferChannel()
        channel.send_window(materialized_window())
        window = channel.window_bytes

        decision = authorize_payload_run(_run(payload=memoryview(window), channel=channel))

        assert decision.admitted is True
        assert decision.payload == window


class TestTheBecauseClause:
    """A payload that names a filesystem place — the spelling the row is about."""

    def test_a_path_payload_is_refused_as_by_filesystem(self) -> None:
        decision = authorize_payload_run(_run(payload="/data/window.arrow"))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.BY_FILESYSTEM

    def test_a_pathlib_payload_is_also_by_filesystem(self) -> None:
        decision = authorize_payload_run(_run(payload=Path("/data/window.arrow")))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.BY_FILESYSTEM

    def test_a_path_is_refused_whatever_a_channel_holds(self) -> None:
        # A path names a place on a filesystem the box does not hold; a channel
        # that happens to be loaded cannot redeem the spelling.
        channel = TransferChannel()
        channel.send_window(materialized_window())

        decision = authorize_payload_run(_run(payload="/data/window.arrow", channel=channel))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.BY_FILESYSTEM


class TestOffChannel:
    """The payload is not what the channel carried — these bytes did not cross."""

    def test_an_object_reference_never_serialized_is_off_channel(self) -> None:
        # A ``MarketWindow`` handed over as a reference, not serialized onto any
        # channel: the box reads bytes off a channel, not objects out of the
        # host's memory.
        decision = authorize_payload_run(_run(payload=materialized_window()))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.OFF_CHANNEL

    def test_bytes_that_disagree_with_the_window_are_off_channel(self) -> None:
        # Two buffers, one run: the dispatch sent one window and passed another.
        channel = TransferChannel()
        channel.send_window(materialized_window())

        wrong = b"a different window entirely"
        decision = authorize_payload_run(_run(payload=wrong, channel=channel))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.OFF_CHANNEL

    def test_the_off_channel_sentence_names_the_size_mismatch(self) -> None:
        channel = TransferChannel()
        channel.send_window(materialized_window())

        decision = authorize_payload_run(_run(payload=b"short", channel=channel))

        assert decision.admitted is False
        assert f"the channel holds {len(channel.window_bytes)}" in decision.detail


class TestNoChannel:
    """Bytes offered with no channel behind them — a claim, not an arrival."""

    def test_serialized_bytes_with_no_channel_are_no_channel(self) -> None:
        channel = TransferChannel()
        channel.send_window(materialized_window())
        window = channel.window_bytes

        decision = authorize_payload_run(_run(payload=window, channel=None))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.NO_CHANNEL

    def test_a_bytearray_offered_with_no_channel_is_still_no_channel(self) -> None:
        channel = TransferChannel()
        channel.send_window(materialized_window())
        window = bytearray(channel.window_bytes)

        decision = authorize_payload_run(_run(payload=window, channel=None))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.NO_CHANNEL


class TestNothingArrived:
    """A channel was handed, but the send never happened."""

    def test_a_payload_none_with_an_empty_channel_is_nothing_arrived(self) -> None:
        decision = authorize_payload_run(_run(payload=None, channel=TransferChannel()))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.NOTHING_ARRIVED

    def test_bytes_offered_over_a_channel_that_holds_no_window_is_nothing_arrived(self) -> None:
        # The dispatch skipped the send and passed the window straight to the
        # runner: the bytes never crossed the channel it was handed with.
        channel = TransferChannel()
        channel.send_window(materialized_window())
        window = channel.window_bytes

        decision = authorize_payload_run(_run(payload=window, channel=TransferChannel()))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.NOTHING_ARRIVED

    def test_nothing_arrived_is_split_from_no_channel_because_the_repairs_differ(self) -> None:
        # A missing channel is looked for where the dispatch builds its run; a
        # silent one between the channel's creation and the spawn.  One reason
        # each, so an operator reading the refusal is pointed at the right locus.
        assert PayloadReason.NOTHING_ARRIVED is not PayloadReason.NO_CHANNEL
        assert authorize_payload_run(_run(payload=None, channel=None)).reason is (
            PayloadReason.WITHOUT_PAYLOAD
        )
        assert authorize_payload_run(_run(payload=None, channel=TransferChannel())).reason is (
            PayloadReason.NOTHING_ARRIVED
        )


class TestWithoutPayload:
    """No payload and no channel holding one — nothing to evaluate at all."""

    def test_a_run_with_no_payload_and_no_channel_is_without_payload(self) -> None:
        decision = authorize_payload_run(_run(payload=None, channel=None))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.WITHOUT_PAYLOAD


class TestTheRefusal:
    """Every refusal carries the greppable code and §5.2's row, and ``require`` raises."""

    def test_every_refusal_message_starts_with_the_channel_code(self) -> None:
        refusals = [
            authorize_payload_run(_run(payload="/data/window.arrow")).detail,
            authorize_payload_run(_run(payload=materialized_window())).detail,
            authorize_payload_run(_run(payload=b"x", channel=None)).detail,
            authorize_payload_run(_run(payload=None, channel=None)).detail,
            authorize_payload_run(_run(payload=None, channel=TransferChannel())).detail,
        ]
        for message in refusals:
            assert message.startswith(PAYLOAD_CHANNEL_CODE), message

    def test_every_refusal_message_carries_the_control_table_row(self) -> None:
        # One body rather than six literals: each refusal names the law it
        # enforces in the architecture's own words.
        message = authorize_payload_run(_run(payload="/data/window.arrow")).detail
        assert "Filesystem | No mounts. Data arrives over IPC only." in message

    def test_require_raises_the_sibling_error_not_the_transfers(self) -> None:
        # The raise lives on the decision's ``require``, the launcher's last
        # line before the spawn.  It is :class:`PayloadChannelRequired`, a
        # sibling of the transfer's error rather than a subclass — a caller
        # reading a refusal wants to know which half of the channel fired.
        decision = authorize_payload_run(_run(payload="/data/window.arrow"))
        with pytest.raises(PayloadChannelRequired) as raised:
            decision.require()
        assert str(raised.value).startswith(PAYLOAD_CHANNEL_CODE)

    def test_require_on_an_admitted_run_returns_the_window(self) -> None:
        channel = TransferChannel()
        channel.send_window(materialized_window())
        window = channel.window_bytes

        returned = authorize_payload_run(_run(payload=window, channel=channel)).require()

        assert returned == window


class TestTheDuckTypedChannel:
    """The gate reads a channel by its ``window_bytes``, not by its class."""

    def test_a_stand_in_channel_carrying_the_window_attribute_is_read(self) -> None:
        # A deployment's pipe-backed stand-in, or a test double: the law's
        # subject is the arrival, not the class that witnessed it.
        channel = TransferChannel()
        channel.send_window(materialized_window())

        class StandIn:
            window_bytes = channel.window_bytes
            facts = None

        stand_in = StandIn()
        assert getattr(stand_in, WINDOW_ATTRIBUTE) == channel.window_bytes

        decision = authorize_payload_run(_run(payload=channel.window_bytes, channel=stand_in))

        assert decision.admitted is True
        assert decision.reason is PayloadReason.OVER_IPC

    def test_an_object_without_the_window_attribute_reads_as_no_window(self) -> None:
        # A channel was handed with the run and it holds no window this law can
        # read — a missing attribute is ``nothing-arrived``, the honest answer
        # rather than a type error.  (``no-channel`` is reserved for a run with
        # no channel object at all.)
        class NoWindow:
            pass

        decision = authorize_payload_run(_run(payload=b"some bytes", channel=NoWindow()))

        assert decision.admitted is False
        assert decision.reason is PayloadReason.NOTHING_ARRIVED


class TestTheFacade:
    """``SandboxPayload`` — the law as the value a composed application carries."""

    def test_check_answers_and_require_raises(self) -> None:
        law = sandbox_payload()

        channel = TransferChannel()
        channel.send_window(materialized_window())
        window = channel.window_bytes

        assert law.check(_run(payload=window, channel=channel)).admitted is True
        assert law.require(_run(payload=window, channel=channel)) == window

    def test_require_raises_on_a_run_whose_payload_did_not_cross(self) -> None:
        law = sandbox_payload()
        with pytest.raises(PayloadChannelRequired):
            law.require(_run(payload="/data/window.arrow"))

    def test_the_facade_is_stateless_and_carries_no_channel(self) -> None:
        # A channel belongs to one run; a component shared across runs that held
        # one would let two runs share a window.  So the facade carries nothing —
        # it is ``__slots__ = ()``, so an instance has no place to hold state.
        first = sandbox_payload()
        second = sandbox_payload()
        assert first is not second
        assert SandboxPayload.__slots__ == ()
        with pytest.raises(AttributeError):
            first.window_bytes = b"x"

    def test_the_component_exposes_the_same_verbs(self) -> None:
        # The composed component answers the same questions as the facade — the
        # read side a deployment audits with, and the launcher verb.
        component = sandbox.sandbox_payload()
        for operation in ("check", "require"):
            assert callable(getattr(component, operation)), operation
