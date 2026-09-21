"""Feature 166 — the window out, the score vector back, one channel.

app_spec.xml feature 166: *"System transfers the materialized window as Arrow
IPC, which returns the resulting score vector over the same channel."*  This
file tests the sentence clause by clause, because a channel that satisfied any
two of them would be a different and worse feature:

* **the materialized window** — what goes out is feature 14's payload, built
  from a real :class:`~contract.window.MarketWindow` over real Arrow frames,
  not a hand-written stand-in;
* **as Arrow IPC** — the bytes are a framed container of Arrow IPC streams, and
  the reader reaches the facts without materializing a frame;
* **over the same channel** — one object carries both legs, and that identity
  is what makes the return checkable: it remembers the universe the window
  declared;
* **returns the resulting score vector** — the values come back positional
  against that universe, and a vector that disagrees with it in length, dtype,
  or finiteness is refused rather than normalized.

The zero-copy claim is not asserted in prose anywhere: :func:`scores_alias_payload`
checks it against real buffer addresses, and the tests below call it.  Feature
14 makes the identical claim for the window leg and checks it the same way.

Every refusal is a raised exception rather than a returned value, which is the
shape this member's transfer law takes and not the shape its two sibling laws
take — see :class:`~sandbox.transfer.SandboxTransfer` and
:class:`~sandbox.errors.SandboxTransferError` for why a *transfer* is dispatched
by trusted host code while a *run* and a *submission* are offered unattended.
So the refusals here are asserted with ``pytest.raises``, and the reader is
entitled to check that the message carries the greppable code.
"""

from __future__ import annotations

import struct

import polars as pl
import pytest
from _documents import (
    WINDOW_FRAME_NAME,
    WINDOW_SCORES,
    WINDOW_UNIVERSE,
    contract_validate,
    materialized_window,
    score_payload,
    score_series,
    unmaterialized_window,
)
from contract.payload import MarketWindowPayload
from sandbox import (
    SCORE_CHANNEL_CODE,
    SCORE_MAGIC,
    TRANSFER_COMPONENT_NAME,
    WINDOW_TRANSFER_CODE,
    SandboxTransfer,
    ScoreChannelError,
    ScoreVector,
    TransferChannel,
    WindowFacts,
    WindowTransferError,
    decode_scores,
    encode_scores,
    inspect_window_payload,
    sandbox_transfer,
    scores_alias_payload,
)
from sandbox.errors import SandboxError, SandboxTransferError


class TestTheWindowLeg:
    """The inbound half: the materialized window, as Arrow IPC."""

    def test_a_materialized_window_crosses_and_declares_its_facts(self) -> None:
        """The host's write, and what it can prove about what it sent."""
        channel = TransferChannel()
        facts = channel.send_window(materialized_window())

        assert isinstance(facts, WindowFacts)
        assert facts.universe == WINDOW_UNIVERSE
        assert facts.symbols == len(WINDOW_UNIVERSE)
        assert facts.frame_names == (WINDOW_FRAME_NAME,)
        # The ABI version travels with the payload, so a return can be
        # attributed to the contract that produced it.
        assert facts.contract_version
        assert facts.decision_time
        assert facts.size == len(channel.window_bytes)

    def test_the_payload_is_the_contracts_own_serialization(self) -> None:
        """What crosses is feature 14's payload, byte for byte.

        The point of pinning this: if this member ever grew its own idea of
        the window container, a window serialized by the contract and one
        serialized here would both "work" while disagreeing about the format —
        and a reader downstream would be the thing that found out.
        """
        window = materialized_window()
        expected = bytes(window.to_arrow())
        channel = TransferChannel()
        channel.send_window(window)
        assert channel.window_bytes == expected

    def test_the_facts_are_read_without_materializing_a_frame(self) -> None:
        """A payload whose *data* is unreadable still yields its facts.

        The manifest is segment 0 and is read on its own — feature 14's reason
        for framing it separately — so a caller that only needs to know which
        universe arrived does not pay to decode every frame.  Corrupting the
        data segment while the manifest survives is exactly that check.
        """
        raw = bytearray(bytes(materialized_window().to_arrow()))
        # Segment 0 holds the manifest; segment 1 is the frame.  Flip the
        # frame's bytes, leaving the header, the length table and the manifest
        # intact, so only a reader that touched the frame would notice.
        manifest_length = struct.unpack("<Q", raw[16:24])[0]
        body_at = 16 + 2 * 8
        for index in range(body_at + manifest_length, len(raw)):
            raw[index] ^= 0xFF

        facts = inspect_window_payload(bytes(raw))
        assert facts.universe == WINDOW_UNIVERSE
        assert facts.frame_names == (WINDOW_FRAME_NAME,)

    def test_a_multi_frame_window_reports_its_frames_in_segment_order(self) -> None:
        """The frame names come back in the order the segments were written.

        A window here can hold more than one frame, and the container's length
        table is what makes each one findable.  ``window_frames`` builds each
        frame as its own table, so the names below are not merely present — a
        reader that indexed the wrong segment, or read one frame's length for
        another's, would report the wrong *set*, not just the wrong order.
        """
        names = ("bars:1d", "trades")
        window = materialized_window(frame_names=names)

        facts = inspect_window_payload(bytes(window.to_arrow()))
        assert facts.frame_names == names
        assert facts.universe == WINDOW_UNIVERSE

        # And through the channel, which is the path the feature describes.
        channel = TransferChannel()
        assert channel.send_window(window).frame_names == names
        assert channel.receive_window().frame_names == names

    @pytest.mark.parametrize(
        "case",
        [
            pytest.param((WINDOW_UNIVERSE, (WINDOW_FRAME_NAME,)), id="the-common-case"),
            pytest.param((WINDOW_UNIVERSE, ("bars:1d", "trades", "quotes")), id="three-frames"),
            pytest.param((("日本/USDT", "₿TC"), (WINDOW_FRAME_NAME,)), id="unicode"),
            pytest.param(((), (WINDOW_FRAME_NAME,)), id="empty-universe"),
        ],
    )
    def test_the_facts_agree_with_the_contracts_own_reading(self, case) -> None:
        """The manifest is read here *and* by the contract, and must agree.

        This member deliberately reimplements feature 14's manifest read rather
        than importing it — ``contract`` must stay out of composition time, and
        the facts have to be readable without materializing a frame.  The cost
        of that choice is a second reader of one format, so the two are pinned
        against each other here.

        The failure this prevents is quiet and total.  :func:`_metadata_facts`
        is absent-tolerant by design, so if feature 14 ever renamed a manifest
        key, this reader would report ``None`` for the universe, ``symbols``
        would become 0, and the channel would then refuse *every* return with a
        message about a zero-symbol window — a diagnosis pointing at the wrong
        file entirely.  A misspelt key and a legitimately absent one are
        indistinguishable from inside this module; only the contract can say
        which it is.
        """
        universe, frame_names = case
        window = materialized_window(universe=universe, frame_names=frame_names)
        raw = bytes(window.to_arrow())

        facts = inspect_window_payload(raw)
        theirs = MarketWindowPayload.from_bytes(raw)

        assert facts.universe == theirs.universe == universe
        assert facts.frame_names == theirs.frame_names == frame_names
        assert facts.decision_time == theirs.decision_time
        assert facts.contract_version == theirs.contract_version
        assert facts.size == theirs.size == len(raw)
        # Not merely equal — present.  Two readers that both answered ``None``
        # for a renamed key would agree perfectly and be useless.
        assert facts.contract_version is not None
        assert facts.decision_time is not None

    def test_a_unicode_universe_survives_the_round_trip(self) -> None:
        """Symbols are strings, not ASCII, and the manifest must not assume.

        A universe holding non-ASCII or non-BMP symbols is a real case for a
        venue outside the ones this system started with, and it is the case a
        hand-rolled framing that encoded the universe into a place strings do
        not belong would break on.  The payload carries the manifest as Arrow
        metadata, so the check is that the trip is lossless, not that a
        particular encoding was chosen.
        """
        universe = ("日本/USDT", "₿TC", "Ω")
        channel = TransferChannel()
        facts = channel.send_window(materialized_window(universe=universe))

        assert facts.universe == universe
        channel.return_scores(score_series([1.0, -2.0, 0.0]))
        assert channel.receive_scores().as_mapping() == pytest.approx(
            {"日本/USDT": 1.0, "₿TC": -2.0, "Ω": 0.0}
        )

    def test_the_box_side_reads_the_same_facts_the_host_wrote(self) -> None:
        """Both ends agree about the window, which is what "same channel" means."""
        channel = TransferChannel()
        sent = channel.send_window(materialized_window())
        received = channel.receive_window()
        assert received == sent
        assert received.universe == WINDOW_UNIVERSE


class TestTheReturnLeg:
    """The outbound half: the resulting score vector, back over that channel."""

    def test_the_scores_come_back_positional_against_the_universe(self) -> None:
        channel = TransferChannel()
        channel.send_window(materialized_window())
        channel.return_scores(score_series())

        vector = channel.receive_scores()
        assert isinstance(vector, ScoreVector)
        assert vector.universe == WINDOW_UNIVERSE
        assert vector.values() == pytest.approx(list(WINDOW_SCORES))
        # The correspondence is positional, and as_mapping is where it is
        # made explicit.
        assert vector.as_mapping() == pytest.approx(
            dict(zip(WINDOW_UNIVERSE, WINDOW_SCORES))
        )

    def test_the_scores_carry_the_windows_provenance(self) -> None:
        """A vector is attributable without holding the payload that made it.

        The decision time and the ABI version travel on the return leg's own
        manifest, so a run's output can be traced to the window it answered
        for even after the window itself is gone.
        """
        channel = TransferChannel()
        facts = channel.send_window(materialized_window())
        channel.return_scores(score_series())

        vector = channel.receive_scores()
        assert vector.decision_time == facts.decision_time
        assert vector.contract_version == facts.contract_version

    def test_the_return_leg_is_zero_copy(self) -> None:
        """The scores are *views into* the payload, checked, not asserted.

        The claim feature 166 shares with feature 14: a reader must not pay for
        the data twice.  ``scores_alias_payload`` walks the score column's
        real buffer addresses and asks whether they fall inside the buffer the
        channel delivered — so a future change that quietly copied (a
        ``combine_chunks()`` on a multi-chunk payload, a ``bytes`` slice in the
        framing) fails here rather than in a benchmark nobody runs.
        """
        channel = TransferChannel()
        channel.send_window(materialized_window())
        raw = channel.return_scores(score_series())

        vector = channel.receive_scores()
        assert scores_alias_payload(vector, raw)

    def test_a_copy_does_not_alias_and_the_helper_says_so(self) -> None:
        """The negative case, so the check above cannot pass vacuously.

        A helper that answered ``True`` for everything would make the
        zero-copy test meaningless.  Decoding the same bytes from a *copy*
        must report no aliasing, and a vector over unrelated bytes must too.
        """
        raw = score_payload()
        # ``bytes(raw)`` would *not* do: bytes is immutable, so CPython returns
        # the same object and the "copy" would alias itself.  A bytearray is a
        # genuinely distinct allocation, and freezing it gives bytes over it.
        copied = bytes(bytearray(raw))
        assert copied is not raw
        assert scores_alias_payload(decode_scores(copied), raw) is False

    def test_scores_round_trip_through_the_container_unchanged(self) -> None:
        """Encode then decode is identity on the values, dtype and order."""
        awkward = (0.1 + 0.2, -0.0, 1e-9)
        raw = encode_scores(score_series(awkward), universe=WINDOW_UNIVERSE)
        vector = decode_scores(raw)
        # Exact, not approx: a float64 column that survived Arrow must be bit
        # for bit the same value, and `approx` here would hide a cast.
        assert vector.values() == list(awkward)
        assert str(vector.scores.dtype) == "Float64"

    def test_the_same_values_encode_to_identical_bytes(self) -> None:
        """Determinism, so a replay can compare payloads byte for byte.

        The property feature 49's materialisation relies on for its own writes
        and §12 asks of the whole system: two encodes of one result must not
        differ, or a digest over a stored score vector would drift for reasons
        no reader could see.
        """
        first = encode_scores(score_series(), universe=WINDOW_UNIVERSE)
        second = encode_scores(score_series(), universe=WINDOW_UNIVERSE)
        assert first == second


class TestTheEmptyUniverse:
    """A window with no symbols, and the vector that is the only right answer.

    A decision time can legitimately hold no tradable symbols — feature 13's
    point-in-time universe is an intersection that can come up empty, and a
    holiday, a halt or an all-failed screen all produce one.  Feature 11's rule
    for that case is stated where it can be stated precisely, in
    :func:`contract.signal.validate_signal_return`: *"a return for an empty
    universe is conforming only when it is itself an empty float series: there
    are no symbols to score, so a series with any value would be a score for a
    symbol that does not exist, and the length check catches it."*  So there is
    exactly one conforming return, and the channel must carry it rather than
    mistake it for a malformed one — and the length rule, not a special case,
    is what makes it the only one.

    This class exists because the channel used to refuse that one conforming
    return, and the rest of the suite did not notice.  The finiteness check was
    written as "are all values finite?", and Arrow's ``compute.all`` over an
    *empty* array returns null — the vacuous truth — which ``bool()`` reads as
    ``False``.  That spelling gave the intended answer for every non-empty
    vector, so only the empty universe could tell it apart from the right one,
    and nothing here exercised the empty universe.  These tests do.
    """

    #: An empty window: the universe is empty and so is the frame it carries.
    EMPTY: tuple[str, ...] = ()

    def test_an_empty_universe_crosses_with_no_symbols(self) -> None:
        """The window leg carries an empty universe as a fact, not an error."""
        channel = TransferChannel()
        facts = channel.send_window(materialized_window(universe=self.EMPTY, rows=0))
        assert facts.universe == self.EMPTY
        assert facts.symbols == 0

    def test_an_empty_vector_is_the_conforming_return(self) -> None:
        """The whole point: an empty float series comes back, not a refusal.

        This is the regression.  The refusal it guards against is a *wrong*
        one — it rejects a return feature 11 calls conforming — so the test
        cannot merely assert that nothing raises; it asserts the round trip
        completes and that what comes back is still empty, still Float64, and
        still keyed by no symbols at all.
        """
        channel = TransferChannel()
        channel.send_window(materialized_window(universe=self.EMPTY, rows=0))
        channel.return_scores(score_series([], name="scores"))

        vector = channel.receive_scores()
        assert vector.universe == self.EMPTY
        assert vector.values() == []
        assert vector.as_mapping() == {}
        assert str(vector.scores.dtype) == "Float64"
        assert vector.require() is vector

    def test_an_empty_vector_encodes_and_decodes_alone(self) -> None:
        """The same case at the encoder, with no channel around it.

        Kept separate from the channel test because the two failures were
        separate: the finiteness check sat in :func:`encode_scores`'s
        normalization, and :meth:`ScoreVector.require` refused emptiness on
        its own.  This drives the payload functions directly, so a regression
        in either one names itself rather than hiding behind the channel.

        ``expected`` is passed so the decode re-checks alignment against a
        window with no symbols — the inbound half of the same rule.
        """
        raw = encode_scores(score_series([]), universe=self.EMPTY)
        empty_window = materialized_window(universe=self.EMPTY, rows=0)
        facts = inspect_window_payload(bytes(empty_window.to_arrow()))
        assert facts.symbols == 0

        vector = decode_scores(raw, expected=facts)
        assert vector.values() == []
        assert vector.require() is vector

    @pytest.mark.parametrize(
        "values",
        [
            pytest.param([0.0], id="one-value"),
            pytest.param([1.0, 2.0, 3.0], id="full-length"),
        ],
    )
    def test_a_vector_for_an_empty_universe_is_still_refused(self, values) -> None:
        """Conforming-when-empty is not the same as anything-goes.

        The refusal the empty case must not weaken: a vector with values for a
        universe with no symbols has no positional reading at all — the *i*-th
        value answers for a symbol that does not exist.  ``require`` stopped
        checking emptiness; it did not stop checking length.
        """
        channel = TransferChannel()
        channel.send_window(materialized_window(universe=self.EMPTY, rows=0))
        with pytest.raises(ScoreChannelError):
            channel.return_scores(score_series(values))

    def test_an_empty_vector_for_a_populated_universe_is_refused(self) -> None:
        """The mirror: emptiness is conforming only when the universe is too."""
        channel = TransferChannel()
        channel.send_window(materialized_window())
        with pytest.raises(ScoreChannelError):
            channel.return_scores(score_series([]))

    def test_the_channel_agrees_with_the_contracts_own_validator(self) -> None:
        """The two seams answer *the same question*, so they must agree.

        Feature 11's validator judges a return inside the box; this channel
        judges the same vector on the wire.  A return that the contract calls
        conforming and this channel refuses is not a stricter channel, it is a
        channel that fails a run for a reason the system does not recognise —
        and the disagreement is invisible from either side alone, since each
        is self-consistent.  So the check is made from both: the empty case,
        which is where the two spellings of "finite" diverged, and a populated
        one, so this cannot pass by both sides refusing everything.
        """
        conforming = (
            (self.EMPTY, pl.Series("scores", [], dtype=pl.Float64)),
            (WINDOW_UNIVERSE, score_series()),
        )
        for universe, series in conforming:
            assert contract_validate(series, universe) == []

            channel = TransferChannel()
            channel.send_window(materialized_window(universe=universe, rows=len(universe)))
            channel.return_scores(series)  # would raise if the channel disagreed
            assert channel.receive_scores().require().universe == universe

    def test_require_still_refuses_a_hand_assembled_misalignment(self) -> None:
        """``require`` kept the invariant it is for, having lost the other.

        Assembled by hand because a vector off the channel cannot hold this
        shape — which is exactly why the verb still needs to check it.
        """
        vector = ScoreVector(
            scores=pl.Series("scores", [1.0], dtype=pl.Float64),
            universe=self.EMPTY,
            decision_time=None,
            contract_version=None,
            size=0,
        )
        with pytest.raises(ScoreChannelError) as refusal:
            vector.require()
        assert SCORE_CHANNEL_CODE in str(refusal.value)


class TestTheChannelIsTheSameChannel:
    """One channel, two legs — and why the identity is load-bearing."""

    def test_a_return_is_validated_against_the_window_that_went_out(self) -> None:
        """A vector for a *different* universe is refused at the same channel.

        This is the failure the feature exists to catch: the right shape, the
        right length, and the wrong window.  Without the channel remembering
        what it carried there would be nothing to disagree with.
        """
        channel = TransferChannel()
        facts = channel.send_window(materialized_window())
        # Same length and same dtype, different symbols: a vector that crossed
        # this channel but answers for some other window.  Only a channel that
        # remembered what it carried can tell the difference.
        raw = score_payload(universe=("AAA", "BBB", "CCC"))

        with pytest.raises(ScoreChannelError) as refusal:
            decode_scores(raw, expected=facts)
        assert SCORE_CHANNEL_CODE in str(refusal.value)

        # And the same payload read *without* a window to answer for is fine:
        # the refusal above is about the disagreement, not about the bytes.
        assert decode_scores(raw).values() == pytest.approx(list(WINDOW_SCORES))

    def test_a_wrong_length_return_is_refused_before_it_is_written(self) -> None:
        """The earliest possible refusal: the producer hears it, not the reader.

        A misaligned vector is caught at ``return_scores`` — before the buffer
        crosses — so a run that returned the wrong number of scores is a
        failure at the source rather than a surprise in §6.1's reduction.
        """
        channel = TransferChannel()
        channel.send_window(materialized_window())
        with pytest.raises(ScoreChannelError) as refusal:
            channel.return_scores(score_series(WINDOW_SCORES[:2]))
        assert "2 values" in str(refusal.value)
        assert "3 symbols" in str(refusal.value)
        assert channel.returned is False

    def test_a_second_window_on_one_channel_is_refused(self) -> None:
        """Single-shot, so a run cannot be scored against a swapped window.

        A channel accepting a second send would need a rule for whether it
        replaced the first — and any such rule is a way for a run to be
        evaluated against a window other than the one it was dispatched with.
        """
        channel = TransferChannel()
        channel.send_window(materialized_window())
        with pytest.raises(WindowTransferError) as refusal:
            channel.send_window(materialized_window())
        assert WINDOW_TRANSFER_CODE in str(refusal.value)

    def test_a_second_return_on_one_channel_is_refused(self) -> None:
        """One run, one vector — the same rule in the other direction."""
        channel = TransferChannel()
        channel.send_window(materialized_window())
        channel.return_scores(score_series())
        with pytest.raises(ScoreChannelError):
            channel.return_scores(score_series())

    def test_reading_the_window_does_not_spend_the_channel(self) -> None:
        """Only *sending* is single-shot; a reader may look at what arrived."""
        channel = TransferChannel()
        channel.send_window(materialized_window())
        assert channel.receive_window() == channel.receive_window()
        assert channel.empty is False
        assert channel.returned is False


class TestTheInboundRefusals:
    """What cannot arrive on the window leg, refused by name."""

    def test_an_unmaterialized_window_is_refused(self) -> None:
        """A window with no frames has nothing to send (feature 14's refusal).

        Translated at the seam: the caller of *this* member must meet this
        member's error, not the contract's, or an ``except SandboxError``
        would silently not fire for the one case a host is most likely to hit.
        """
        with pytest.raises(WindowTransferError) as refusal:
            TransferChannel().send_window(unmaterialized_window())
        assert WINDOW_TRANSFER_CODE in str(refusal.value)

    def test_an_object_that_is_not_a_window_is_refused(self) -> None:
        with pytest.raises(WindowTransferError):
            TransferChannel().send_window("not a window")

    def test_a_window_is_refused_on_the_score_leg(self) -> None:
        """The two legs are self-describing, so a misroute is caught by magic.

        A window payload handed to the score reader is refused *by inspection*
        — before an Arrow reader sees it — which is the whole reason each leg
        carries its own magic rather than being any IPC stream.
        """
        window_payload = bytes(materialized_window().to_arrow())
        with pytest.raises(ScoreChannelError) as refusal:
            decode_scores(window_payload)
        assert SCORE_MAGIC in str(refusal.value).encode() or "magic" in str(refusal.value)

    def test_a_score_payload_is_refused_on_the_window_leg(self) -> None:
        with pytest.raises(WindowTransferError):
            inspect_window_payload(score_payload())

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(b"", id="empty"),
            pytest.param(b"not a payload at all, but long enough", id="foreign"),
            pytest.param(b"\xff\xff\xff\xff" + b"\x00" * 32, id="bare-arrow-marker"),
        ],
    )
    def test_bytes_that_are_not_a_container_are_refused(self, raw: bytes) -> None:
        """Truncated, foreign, or an Arrow stream on its own — all refused.

        The last case is the subtle one: a bare Arrow IPC stream is exactly
        what a naive implementation would have sent, and it is refused because
        it cannot carry the per-payload facts (decision time, universe) that
        make a window a window.
        """
        with pytest.raises(WindowTransferError):
            inspect_window_payload(raw)

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param(lambda b: b[:20], id="truncated"),
            pytest.param(lambda b: bytes(bytearray(b) + b"\x00" * 8), id="padded"),
            pytest.param(
                lambda b: bytes(bytearray(b[:8]) + struct.pack("<I", 99) + b[12:]),
                id="later-framing-version",
            ),
            pytest.param(
                lambda b: bytes(bytearray(b[:12]) + struct.pack("<I", 0) + b[16:]),
                id="zero-segments",
            ),
        ],
    )
    def test_a_damaged_container_is_refused(self, mutate) -> None:
        """Each damage is a header fact, so each refuses before Arrow is asked."""
        raw = bytes(materialized_window().to_arrow())
        with pytest.raises(WindowTransferError):
            inspect_window_payload(mutate(raw))

    def test_a_window_leg_refusal_is_a_sandbox_error(self) -> None:
        """The member's hierarchy holds, so one ``except`` catches the family."""
        assert issubclass(WindowTransferError, SandboxTransferError)
        assert issubclass(WindowTransferError, SandboxError)

    def test_nothing_arriving_is_not_a_window(self) -> None:
        """An unsent channel refuses, rather than answering with an empty one.

        The failure mode this feature exists to prevent: an absence that reads
        as a result.  The box holds no mounts, so "no payload" is a run with no
        window — not a window holding nothing.
        """
        with pytest.raises(WindowTransferError):
            TransferChannel().receive_window()
        with pytest.raises(ScoreChannelError):
            TransferChannel().receive_scores()


class TestTheOutboundRefusals:
    """What cannot come back on the score leg, refused by name."""

    @pytest.mark.parametrize(
        "produce",
        [
            # Built with an explicit dtype rather than through score_series,
            # which pins Float64: an "integers" case that went through the
            # float helper would be testing that helper, not the channel.
            pytest.param(
                lambda: pl.Series("scores", [1, 2, 3], dtype=pl.Int64),
                id="integers",
            ),
            pytest.param(
                lambda: pl.Series("scores", [1.0, 2.0, 3.0, 4.0], dtype=pl.Float64),
                id="too-long",
            ),
            pytest.param(
                lambda: pl.Series("scores", [1.0, 2.0], dtype=pl.Float64),
                id="too-short",
            ),
            pytest.param(
                lambda: pl.Series("scores", [1.0, None, 3.0], dtype=pl.Float64),
                id="null",
            ),
            pytest.param(
                lambda: pl.Series("scores", [1.0, float("nan"), 3.0], dtype=pl.Float64),
                id="nan",
            ),
            pytest.param(
                lambda: pl.Series("scores", [1.0, float("inf"), 3.0], dtype=pl.Float64),
                id="infinity",
            ),
            pytest.param(
                lambda: pl.Series("scores", ["a", "b", "c"], dtype=pl.String),
                id="strings",
            ),
        ],
    )
    def test_a_non_conforming_vector_is_refused(self, produce) -> None:
        """Every refusal is one the pipeline could not have survived.

        An integer (or string) column cannot be ranked, a wrong length is a
        misalignment, and a null or a non-finite value is swallowed by the
        cross-sectional reduction downstream — feature 11's validator makes
        each of these refusals for a live return, and this makes them on the
        wire.
        """
        channel = TransferChannel()
        channel.send_window(materialized_window())
        with pytest.raises(ScoreChannelError):
            channel.return_scores(produce())

    def test_a_degenerate_but_conforming_vector_is_admitted(self) -> None:
        """The control for the refusals above, and it is load-bearing.

        A vector whose values all coincide is a poor signal, not an invalid
        one.  If the checks above were refusing *shape* rather than validity —
        a spread test, say, or a finiteness test written as "not all equal" —
        this admits it and they would have passed anyway.  Both directions
        have to hold, or the suite cannot tell a validating channel from a
        suspicious one.
        """
        channel = TransferChannel()
        channel.send_window(materialized_window())
        channel.return_scores(score_series([0.5, 0.5, 0.5]))
        assert channel.receive_scores().values() == [0.5, 0.5, 0.5]

    def test_a_non_vector_return_is_refused(self) -> None:
        channel = TransferChannel()
        channel.send_window(materialized_window())
        with pytest.raises(ScoreChannelError):
            channel.return_scores("not a vector")

    def test_a_return_before_a_window_is_refused(self) -> None:
        """There is no universe to align against, so a vector means nothing."""
        with pytest.raises(ScoreChannelError) as refusal:
            TransferChannel().return_scores(score_series())
        assert SCORE_CHANNEL_CODE in str(refusal.value)

    def test_nothing_returning_is_refused(self) -> None:
        """A run that produced no vector is a recorded outcome, not a zero.

        Feature 11's contract has no spelling for "no score", so the channel
        refuses rather than inventing one — the same judgement
        :func:`sandbox.transfer.SandboxTransfer.round_trip` makes for a
        producer that returns ``None``.
        """
        channel = TransferChannel()
        channel.send_window(materialized_window())
        with pytest.raises(ScoreChannelError):
            channel.receive_scores()

    def test_a_damaged_score_container_is_refused(self) -> None:
        with pytest.raises(ScoreChannelError):
            decode_scores(SCORE_MAGIC + b"\x00" * 4)

    def test_a_score_leg_refusal_is_a_sandbox_error(self) -> None:
        assert issubclass(ScoreChannelError, SandboxTransferError)
        assert issubclass(ScoreChannelError, SandboxError)

    def test_the_two_legs_refuse_as_different_types(self) -> None:
        """A caller reading a failure learns which leg before it learns why.

        Deliberately not one error for both directions: "the window never
        arrived" and "the return was not a score vector" are unrelated
        situations with unrelated fixes, and a single type would force a
        caller to parse prose to tell them apart.
        """
        assert not issubclass(WindowTransferError, ScoreChannelError)
        assert not issubclass(ScoreChannelError, WindowTransferError)


class TestTheComponent:
    """Feature 166 as the value a composed application carries."""

    def test_the_member_declares_the_component_name_the_feature_owns(self) -> None:
        assert TRANSFER_COMPONENT_NAME == "sandbox-transfer"

    def test_the_law_carries_no_channel(self) -> None:
        """A transfer is a thing that happens, not a thing that is held.

        A composed component shared across runs that owned a channel would be
        a component letting two runs share a window, so the channel is handed
        out per call and the component itself is empty.
        """
        law = sandbox_transfer()
        assert isinstance(law, SandboxTransfer)
        assert law.channel() is not law.channel()

    def test_send_validates_the_window_without_a_caller_holding_a_channel(self) -> None:
        facts = sandbox_transfer().send(materialized_window())
        assert facts.universe == WINDOW_UNIVERSE

    def test_round_trip_executes_the_features_sentence(self) -> None:
        """Send the window, produce, take the vector back — end to end.

        The producer is supplied by the caller, which is the seam that keeps
        the box's execution in the evaluator (``evaluator._sandbox``, §6.1
        step 2) and this member free of a runner.
        """
        seen: list[WindowFacts] = []

        def produce(facts: WindowFacts):
            seen.append(facts)
            return score_series()

        vector = sandbox_transfer().round_trip(materialized_window(), produce)
        assert [facts.universe for facts in seen] == [WINDOW_UNIVERSE]
        assert vector.values() == pytest.approx(list(WINDOW_SCORES))

    def test_a_producer_that_returns_nothing_is_refused(self) -> None:
        """The producer's ``None`` is refused by name, never encoded as empty."""
        with pytest.raises(ScoreChannelError):
            sandbox_transfer().round_trip(materialized_window(), lambda facts: None)

    def test_a_producer_returning_a_misaligned_vector_is_refused(self) -> None:
        """A producer that returns the wrong count fails at the seam."""
        with pytest.raises(ScoreChannelError):
            sandbox_transfer().round_trip(
                materialized_window(), lambda facts: score_series([1.0])
            )

    def test_round_trip_can_be_driven_over_a_caller_owned_channel(self) -> None:
        """The caller that dispatches a run owns the channel for its lifetime."""
        channel = TransferChannel()
        sandbox_transfer().round_trip(
            materialized_window(), lambda facts: score_series(), channel=channel
        )
        assert channel.returned is True
        assert channel.receive_scores().values() == pytest.approx(list(WINDOW_SCORES))
