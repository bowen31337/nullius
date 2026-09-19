"""The Arrow IPC payload channel for a materialized MarketWindow.

Feature 14 of app_spec.xml: "System serializes a materialized MarketWindow to
Arrow IPC so the sandbox receives data over a payload channel with zero_copy
transfer" (docs/nullius-tech-architecture.md §5.2, ``payload=window.to_arrow()``).

Of the three claims in that sentence, two are easy to assert and one is not:

* **serializes to Arrow IPC** — a round-trip equality test covers the value.
* **over a payload channel** — :class:`PayloadChannel` is a seam, and the test
  is that nothing but bytes crosses it: no path, no fd, no handle.
* **zero_copy** — the claim this suite spends the most effort on, because it
  is the one a reader can believe while being wrong.  A copy and a view
  produce *identical values*; equality cannot tell them apart.  So the
  zero-copy tests assert on buffer identity (``frames_alias_payload``) and
  include a negative control proving that check can actually fail — a
  zero-copy assertion that passes on a copying implementation is worse than
  no assertion at all.

The framing is pinned too, including every way a payload can be malformed:
these bytes arrive from a channel, so the reader's first job is to refuse
anything that is not a window rather than to interpret it.
"""

from __future__ import annotations

import copy
import pickle
import struct
from datetime import datetime, timedelta, timezone

import pytest

# pyarrow is a declared dependency of the contract member, so under the
# canonical invocation (`uv run --all-packages pytest`, which is what the
# acceptance gate runs) it is always present.  It is imported at module scope
# here — not lazily — because this module is meaningless without it, but the
# guard below keeps a *partially installed* environment from turning a missing
# wheel into a collection error that takes the whole repository suite down with
# it.  A bare `pytest` on a machine that has not run `uv sync` then reports one
# skipped module instead of zero tests run.
pa = pytest.importorskip(
    "pyarrow", reason="the Arrow IPC payload suite requires pyarrow (a declared dependency)"
)

from contract import (
    CONTRACT_VERSION,
    PAYLOAD_MAGIC,
    PAYLOAD_VERSION,
    MarketWindow,
    MarketWindowPayload,
    NoPayloadError,
    PayloadChannel,
    PayloadFormatError,
    frames_alias_payload,
    window_from_payload,
    serialize_window,
)

T = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

#: Bytes before the length table: magic, version, segment count.  Spelled as a
#: derivation rather than ``16`` so the tests below read as a description of
#: the format instead of a set of magic numbers that happen to agree with it.
HEADER = len(PAYLOAD_MAGIC) + 4 + 4


@pytest.fixture
def bars() -> pa.Table:
    return pa.table(
        {
            "ts": pa.array([1_700_000_000_000, 1_700_000_060_000], type=pa.int64()),
            "symbol": pa.array(["BTCUSDT", "ETHUSDT"]),
            "close": pa.array([61000.5, 2400.25], type=pa.float64()),
        }
    )


@pytest.fixture
def trades() -> pa.Table:
    return pa.table(
        {
            "ts": pa.array([1_700_000_030_000], type=pa.int64()),
            "px": pa.array([61001.0], type=pa.float64()),
            "qty": pa.array([0.75], type=pa.float64()),
        }
    )


@pytest.fixture
def window(bars: pa.Table, trades: pa.Table) -> MarketWindow:
    return MarketWindow(T, UNIVERSE, frames={"bars": bars, "trades": trades})


# --------------------------------------------------------------------------
# The value survives the channel
# --------------------------------------------------------------------------


def test_a_materialized_window_serializes_to_bytes(window: MarketWindow):
    payload = window.to_arrow()
    assert isinstance(payload, MarketWindowPayload)
    assert payload.size > 0
    assert bytes(payload).startswith(PAYLOAD_MAGIC)


def test_serialization_round_trips_the_window_value(window: MarketWindow):
    assert window.to_arrow().materialize() == window


def test_round_trip_preserves_the_decision_time(window: MarketWindow):
    # The whole reason the window exists; if this drifted, every downstream
    # point-in-time guarantee would drift with it.
    assert window.to_arrow().materialize().t == T


def test_round_trip_preserves_the_universe(window: MarketWindow):
    assert window.to_arrow().materialize().universe == UNIVERSE


def test_round_trip_preserves_frame_names_and_contents(window: MarketWindow, bars):
    rebuilt = window.to_arrow().materialize()
    assert list(rebuilt.frames) == ["bars", "trades"]
    assert rebuilt.frames["bars"].equals(bars)


def test_round_trip_preserves_rows_and_schema(window: MarketWindow, bars):
    rebuilt = window.to_arrow().materialize()
    assert rebuilt.frames["bars"].num_rows == bars.num_rows
    assert rebuilt.frames["bars"].column_names == bars.column_names
    assert rebuilt.frames["bars"].schema.types == bars.schema.types


def test_round_trip_is_stable_across_two_hops(window: MarketWindow):
    # A window may cross more than one boundary (host -> queue -> sandbox).
    once = window.to_arrow().materialize()
    twice = once.to_arrow().materialize()
    assert twice == window


def test_serialize_and_materialize_functions_match_the_methods(window: MarketWindow):
    # The module-level functions are the documented seam; the methods delegate.
    payload = serialize_window(window)
    assert window_from_payload(payload) == window
    assert payload == window.to_arrow()


def test_a_receiving_host_rebuilds_the_window_from_bytes(window: MarketWindow):
    # The channel's actual wire shape: plain bytes at the boundary.
    received = MarketWindowPayload.from_bytes(bytes(window.to_arrow()))
    assert received.materialize() == window


def test_nullable_columns_survive():
    table = pa.table({"score": pa.array([1.0, None, 3.0], type=pa.float64())})
    window = MarketWindow(T, ("A", "B", "C"), frames={"scores": table})
    rebuilt = window.to_arrow().materialize()
    assert rebuilt.frames["scores"].equals(table)
    assert rebuilt.frames["scores"].column("score").to_pylist() == [1.0, None, 3.0]


def test_a_frame_with_zero_rows_round_trips():
    # "No data" is an empty frame, not an absent one — a window that means it
    # must still be serializable.
    empty = pa.table({"ts": pa.array([], type=pa.int64())})
    window = MarketWindow(T, ("BTCUSDT",), frames={"bars": empty})
    rebuilt = window.to_arrow().materialize()
    assert rebuilt == window
    assert rebuilt.frames["bars"].num_rows == 0
    assert rebuilt.frames["bars"].column_names == ["ts"]


def test_unicode_and_large_payloads_survive():
    table = pa.table({"symbol": pa.array(["日本/USDT", "₿TC"])})
    window = MarketWindow(T, ("日本/USDT", "₿TC"), frames={"bars": table})
    assert window.to_arrow().materialize().frames["bars"].equals(table)

    big = pa.table({"i": pa.array(range(200_000), type=pa.int64())})
    big_window = MarketWindow(T, UNIVERSE, frames={"big": big})
    rebuilt = big_window.to_arrow().materialize()
    assert rebuilt.frames["big"].num_rows == 200_000
    assert rebuilt == big_window


def test_a_polars_frame_is_accepted_and_normalized():
    # Polars arrives through the Arrow C data interface; the window pins the
    # Arrow representation so equality and serialization stay well defined.
    pl = pytest.importorskip("polars")
    frame = pl.DataFrame({"symbol": ["BTCUSDT"], "close": [61000.0]})
    window = MarketWindow(T, ("BTCUSDT",), frames={"bars": frame})
    assert isinstance(window.frames["bars"], pa.Table)
    assert window.to_arrow().materialize() == window


# --------------------------------------------------------------------------
# zero_copy — asserted on buffer identity, with a negative control
# --------------------------------------------------------------------------


def test_materialized_frames_alias_the_payload_buffer(window: MarketWindow):
    # The feature's central claim.  Value equality cannot establish it: a
    # copying reader returns identical tables.  Only buffer addresses can.
    payload = window.to_arrow()
    rebuilt = payload.materialize()
    assert frames_alias_payload(rebuilt, payload)


def test_every_frame_aliases_the_payload(window: MarketWindow):
    # Not just the first: a reader that sliced one segment and copied the rest
    # would pass a single-frame check.
    payload = window.to_arrow()
    rebuilt = payload.materialize()
    for name in payload.frame_names:
        single = MarketWindow(rebuilt.t, rebuilt.universe, frames={name: rebuilt.frames[name]})
        assert frames_alias_payload(single, payload), f"frame {name!r} was copied"


def test_the_zero_copy_check_can_actually_fail(window: MarketWindow):
    # The negative control.  A zero-copy assertion that cannot fail is worse
    # than none, because it certifies a copying implementation.  Reading from
    # a *different* buffer must report non-aliasing: same values, different memory.
    original = window.to_arrow()
    copy_payload = MarketWindowPayload.from_bytes(bytes(original))
    rebuilt = copy_payload.materialize()

    assert rebuilt == window  # same value...
    assert frames_alias_payload(rebuilt, copy_payload)  # ...aliasing its own bytes
    assert not frames_alias_payload(rebuilt, original)  # ...but not the other buffer


def test_a_copied_payload_is_detected_by_identity_not_value(window: MarketWindow):
    # Restates the control in the form that matters: the two payloads are
    # byte-identical and yet only one of them aliases the rebuilt frames.
    a = window.to_arrow()
    b = MarketWindowPayload.from_bytes(bytes(a))
    assert bytes(a) == bytes(b)
    rebuilt_from_a = a.materialize()
    assert frames_alias_payload(rebuilt_from_a, a)
    assert not frames_alias_payload(rebuilt_from_a, b)


def test_reading_does_not_copy_the_payload_bytes(window: MarketWindow):
    # A circular check from the other direction: the frames' buffers must fall
    # inside the payload's own address range, which a copy could never do.
    payload = window.to_arrow()
    rebuilt = payload.materialize()
    start = payload.buffer.address
    end = start + payload.buffer.size
    seen = 0
    for name in payload.frame_names:
        for chunk in rebuilt.frames[name].column(0).chunks:
            for buffer in chunk.buffers():
                if buffer is not None and buffer.size:
                    assert start <= buffer.address < end
                    seen += 1
    assert seen > 0


def test_an_unmaterialized_window_has_nothing_to_alias():
    # Vacuous truth, stated rather than hidden: a window with no frames cannot
    # have had one copied, so the check reports aliasing rather than inventing
    # a failure.  (An unmaterialized window cannot be *serialized* — see below —
    # but a materialized one whose frames were all dropped can still be asked.)
    empty_window = MarketWindow(T)
    assert not empty_window.frames
    assert frames_alias_payload(empty_window, MarketWindow(T, UNIVERSE, frames={"a": pa.table({"x": [1]})}).to_arrow())


# --------------------------------------------------------------------------
# The payload channel
# --------------------------------------------------------------------------


def test_the_channel_carries_a_window_end_to_end(window: MarketWindow):
    channel = PayloadChannel()
    channel.send(window)
    assert channel.materialize() == window


def test_the_channel_reports_the_bytes_it_carries(window: MarketWindow):
    channel = PayloadChannel()
    sent = channel.send(window)
    assert channel.receive() is sent
    assert sent.size == channel.receive().size


def test_the_channel_hands_over_a_zero_copy_window(window: MarketWindow):
    channel = PayloadChannel()
    channel.send(window)
    rebuilt = channel.materialize()
    assert frames_alias_payload(rebuilt, channel.receive())


def test_a_channel_with_no_payload_is_empty():
    assert PayloadChannel().empty


def test_receiving_from_an_empty_channel_is_an_error():
    # Feature 159's contract-level half: no mounts plus no payload means no
    # window, and a run must not proceed against one that never arrived.
    channel = PayloadChannel()
    with pytest.raises(NoPayloadError, match="no payload arrived"):
        channel.receive()
    with pytest.raises(NoPayloadError):
        channel.materialize()


def test_a_failed_receive_leaves_the_channel_empty():
    channel = PayloadChannel()
    with pytest.raises(NoPayloadError):
        channel.receive()
    assert channel.empty


def test_a_channel_carries_exactly_one_payload(window: MarketWindow):
    # Two sends would need a rule for whether the second replaces the first;
    # any such rule is a way to run against a window other than the dispatch one.
    channel = PayloadChannel()
    channel.send(window)
    with pytest.raises(RuntimeError, match="already carries a payload"):
        channel.send(MarketWindow(T, ("ADAUSDT",), frames={"bars": window.frames["bars"]}))


def test_the_channel_exposes_no_filesystem_handle(window: MarketWindow):
    # "Payload channel" is a claim about what does NOT cross.  The sandbox has
    # no mounts (§5.2), so anything path-shaped on this object would be a
    # promise the sandbox cannot keep.
    channel = PayloadChannel()
    payload = channel.send(window)
    transit = " ".join(
        str(getattr(payload, attribute, "")) + str(getattr(channel, attribute, ""))
        for attribute in ("buffer", "path", "handle", "fd", "filename", "mount")
    )
    assert "/" not in transit
    assert bytes(payload)[: len(PAYLOAD_MAGIC)] == PAYLOAD_MAGIC


def test_the_channel_survives_a_plain_bytes_boundary(window: MarketWindow):
    # What a socket or a pipe actually hands across: bytes, nothing else.
    channel = PayloadChannel()
    wire = bytes(channel.send(window))
    received = PayloadChannel()
    received._payload = MarketWindowPayload.from_bytes(wire)
    assert received.materialize() == window


# --------------------------------------------------------------------------
# The payload's own facts, readable without materializing a frame
# --------------------------------------------------------------------------


def test_the_manifest_carries_the_window_facts(window: MarketWindow):
    payload = window.to_arrow()
    assert payload.decision_time == "2026-09-01T12:00:00+00:00"
    assert payload.universe == UNIVERSE
    assert payload.frame_names == ("bars", "trades")
    assert payload.contract_version == CONTRACT_VERSION


def test_the_manifest_carries_the_abi_version(window: MarketWindow):
    # Feature 15 versions the signal ABI; the payload records which ABI the
    # host serialized under, so a stored node's ABI can never drift from the
    # code that described it.
    assert window.to_arrow().contract_version == CONTRACT_VERSION


def test_the_manifest_reports_per_frame_sizes(window: MarketWindow):
    payload = window.to_arrow()
    sizes = payload.frame_sizes
    assert set(sizes) == {"bars", "trades"}
    assert all(size > 0 for size in sizes.values())
    # The frame segments plus the manifest and header are exactly the payload.
    assert sum(sizes.values()) < payload.size


def test_the_decision_time_survives_as_an_exact_instant():
    # A non-UTC zone and a sub-second instant are the two ways a decision time
    # is commonly mangled by a serialization format.  Neither may shift.
    plus_two = timezone(timedelta(hours=2))
    t = datetime(2026, 9, 1, 14, 0, 0, 123456, tzinfo=plus_two)
    window = MarketWindow(t, ("BTCUSDT",), frames={"bars": pa.table({"a": [1]})})
    rebuilt = window.to_arrow().materialize()
    assert rebuilt.t == window.t
    assert rebuilt.t.microsecond == 123456
    assert rebuilt.t.tzinfo is not None
    assert rebuilt.t.utcoffset() == timedelta(0)


def test_a_rebuilt_window_is_exactly_as_immutable(window: MarketWindow):
    # The read path must not be a hole in the feature-4 guarantee: a window
    # that arrived over the channel is the same contract as one built in-process.
    rebuilt = window.to_arrow().materialize()
    with pytest.raises(AttributeError):
        rebuilt.t = T + timedelta(days=1)
    with pytest.raises(AttributeError):
        rebuilt.universe = ("DOGEUSDT",)
    with pytest.raises(AttributeError):
        rebuilt.frames = {}
    assert rebuilt.t == T
    assert rebuilt.universe == UNIVERSE


def test_a_rebuilt_window_cannot_gain_a_frame(window: MarketWindow):
    # Widening a window after the fact is the failure this whole contract
    # exists to prevent; a frame added post-hoc is a widening.
    rebuilt = window.to_arrow().materialize()
    with pytest.raises(AttributeError):
        rebuilt.frames = {"late": pa.table({"a": [1]})}


def test_a_rebuilt_window_is_hashable_and_comparable(window: MarketWindow):
    rebuilt = window.to_arrow().materialize()
    assert rebuilt == window
    assert hash(rebuilt) == hash(window)
    assert len({window, rebuilt}) == 1


def test_windows_with_different_frames_are_not_equal(window: MarketWindow):
    other = MarketWindow(T, UNIVERSE, frames={"bars": pa.table({"a": [999]})})
    assert other != window
    assert window.to_arrow().materialize() != other


def test_windows_with_differently_named_frames_are_not_equal(window: MarketWindow):
    renamed = MarketWindow(T, UNIVERSE, frames={"candles": window.frames["bars"]})
    assert renamed != window


def test_a_payload_reports_its_own_size(window: MarketWindow):
    payload = window.to_arrow()
    assert payload.size == len(bytes(payload))
    assert payload.size == payload.buffer.size


# --------------------------------------------------------------------------
# An unmaterialized window is refused
# --------------------------------------------------------------------------


def test_an_unmaterialized_window_cannot_be_serialized():
    # The sandbox has no mounts, so a window with nothing materialized has no
    # data behind it.  Sending a header would surface as an unexplainable zero
    # signal far from its cause.
    with pytest.raises(ValueError, match="unmaterialized"):
        MarketWindow(T, UNIVERSE).to_arrow()


def test_a_window_with_an_empty_frame_is_serializable():
    # The legitimate "no data" case, distinguished from the unmaterialized one.
    empty = pa.table({"ts": pa.array([], type=pa.int64())})
    window = MarketWindow(T, UNIVERSE, frames={"bars": empty})
    assert window.to_arrow().materialize() == window


def test_the_unmaterialized_refusal_names_the_decision_time():
    with pytest.raises(ValueError, match="2026-09-01"):
        MarketWindow(T, UNIVERSE).to_arrow()


def test_an_explicitly_empty_frame_mapping_is_still_unmaterialized():
    with pytest.raises(ValueError, match="unmaterialized"):
        MarketWindow(T, UNIVERSE, frames={}).to_arrow()


# --------------------------------------------------------------------------
# Malformed payloads are refused
# --------------------------------------------------------------------------


def _corrupt(window: MarketWindow, mutate) -> bytes:
    return mutate(bytes(window.to_arrow()))


def test_bytes_that_are_not_a_window_payload_are_refused():
    with pytest.raises(PayloadFormatError, match="magic"):
        MarketWindowPayload.from_bytes(b"\x00" * 256)


def test_a_truncated_payload_is_refused(window: MarketWindow):
    with pytest.raises(PayloadFormatError, match="truncated|sum"):
        MarketWindowPayload.from_bytes(bytes(window.to_arrow())[:-32])


def test_a_payload_shorter_than_its_header_is_refused():
    with pytest.raises(PayloadFormatError, match="too short"):
        MarketWindowPayload.from_bytes(PAYLOAD_MAGIC)


def test_a_padded_payload_is_refused(window: MarketWindow):
    # Padding is as much a format error as truncation: the lengths must account
    # for every byte, or the framing is not what it claims.
    with pytest.raises(PayloadFormatError, match="truncated or padded"):
        MarketWindowPayload.from_bytes(bytes(window.to_arrow()) + b"\x00" * 16)


def test_an_unknown_payload_version_is_refused(window: MarketWindow):
    def mutate(data: bytes) -> bytes:
        return data[: len(PAYLOAD_MAGIC)] + struct.pack("<I", 999) + data[len(PAYLOAD_MAGIC) + 4 :]

    with pytest.raises(PayloadFormatError, match="version 999"):
        MarketWindowPayload.from_bytes(_corrupt(window, mutate))


def test_a_payload_declaring_zero_segments_is_refused(window: MarketWindow):
    def mutate(data: bytes) -> bytes:
        offset = len(PAYLOAD_MAGIC) + 4
        return data[:offset] + struct.pack("<I", 0) + data[offset + 4 :]

    with pytest.raises(PayloadFormatError, match="zero segments"):
        MarketWindowPayload.from_bytes(_corrupt(window, mutate))


def test_a_payload_with_a_wrong_magic_is_refused(window: MarketWindow):
    def mutate(data: bytes) -> bytes:
        return b"NOTAWNDR" + data[8:]

    with pytest.raises(PayloadFormatError, match="magic"):
        MarketWindowPayload.from_bytes(_corrupt(window, mutate))


def test_a_corrupt_manifest_is_refused(window: MarketWindow):
    # Corrupt the manifest segment's body: the framing is intact, so the
    # failure must be reported as an unreadable manifest, not as a framing error.
    data = bytearray(bytes(window.to_arrow()))
    offset = HEADER + 8 * (1 + len(window.frames))  # past header and the length table
    data[offset + 40 : offset + 80] = b"\xde\xad\xbe\xef" * 10
    with pytest.raises(PayloadFormatError, match="manifest|readable"):
        MarketWindowPayload.from_bytes(bytes(data))


def test_a_corrupt_frame_is_refused(window: MarketWindow):
    # Walk to the frame segments and corrupt them, leaving the manifest readable
    # — so the failure is reported against the frame, not the container.
    payload = window.to_arrow()
    data = bytearray(bytes(payload))
    segments = struct.unpack("<I", bytes(data[len(PAYLOAD_MAGIC) + 4 : len(PAYLOAD_MAGIC) + 8]))[0]
    lengths = struct.unpack(f"<{segments}Q", bytes(data[HEADER : HEADER + 8 * segments]))
    frame_start = HEADER + 8 * segments + lengths[0]  # past the header and the manifest
    data[frame_start + 20 : frame_start + 60] = b"\xba\xad" * 20
    with pytest.raises(PayloadFormatError, match="readable"):
        MarketWindowPayload.from_bytes(bytes(data)).materialize()


def test_a_lookalike_payload_does_not_accept_str():
    # A str is iterable and would silently index as one "byte" per character;
    # it is refused rather than coerced.
    with pytest.raises(TypeError, match="bytes"):
        MarketWindowPayload.from_bytes("not-bytes")


def test_a_lookalike_payload_does_not_accept_a_path():
    # The channel carries bytes, never a location.
    with pytest.raises(TypeError, match="bytes"):
        MarketWindowPayload.from_bytes("/lake/snapshots/2026-09-01T00_00_00Z_a3f91c")


# --------------------------------------------------------------------------
# The container framing itself
# --------------------------------------------------------------------------


def test_the_payload_declares_its_format_version(window: MarketWindow):
    data = bytes(window.to_arrow())
    version, segments = struct.unpack("<II", data[len(PAYLOAD_MAGIC) : len(PAYLOAD_MAGIC) + 8])
    assert version == PAYLOAD_VERSION
    # The manifest plus one segment per frame.
    assert segments == 1 + len(window.frames)


def test_the_length_table_accounts_for_every_byte(window: MarketWindow):
    payload = window.to_arrow()
    data = bytes(payload)
    segments = struct.unpack("<I", data[len(PAYLOAD_MAGIC) + 4 : len(PAYLOAD_MAGIC) + 8])[0]
    lengths = struct.unpack(f"<{segments}Q", data[HEADER : HEADER + 8 * segments])
    assert HEADER + 8 * segments + sum(lengths) == len(data)


def test_the_manifest_is_the_first_segment(window: MarketWindow):
    # A reader must be able to read the window's facts without touching a
    # frame; that requires the manifest to be segment 0, always.
    payload = window.to_arrow()
    assert payload.decision_time == "2026-09-01T12:00:00+00:00"
    assert payload.universe == UNIVERSE


def test_each_frame_has_its_own_segment(window: MarketWindow):
    # The manifest names as many frames as segments follow it, which is the
    # invariant that lets a reader trust frame order.
    payload = window.to_arrow()
    data = bytes(payload)
    segments = struct.unpack("<I", data[len(PAYLOAD_MAGIC) + 4 : len(PAYLOAD_MAGIC) + 8])[0]
    assert segments - 1 == len(payload.frame_names)


# --------------------------------------------------------------------------
# Construction-time validation of frames
# --------------------------------------------------------------------------


def test_frames_must_be_a_mapping():
    with pytest.raises(TypeError, match="mapping"):
        MarketWindow(T, UNIVERSE, frames=[("bars", pa.table({"a": [1]}))])


def test_frame_names_must_be_non_empty_strings():
    with pytest.raises(TypeError, match="frame names"):
        MarketWindow(T, UNIVERSE, frames={"": pa.table({"a": [1]})})
    with pytest.raises(TypeError, match="frame names"):
        MarketWindow(T, UNIVERSE, frames={7: pa.table({"a": [1]})})


def test_a_none_frame_is_refused():
    with pytest.raises(TypeError, match="not None"):
        MarketWindow(T, UNIVERSE, frames={"bars": None})


def test_a_non_tabular_frame_is_refused():
    with pytest.raises(TypeError, match="cannot be converted"):
        MarketWindow(T, UNIVERSE, frames={"bars": object()})


def test_frame_conversion_is_eager_so_a_bad_frame_fails_at_construction():
    # A window that only failed when someone asked it for a frame would carry
    # the bad frame silently through sealing and dispatch.
    with pytest.raises(TypeError):
        MarketWindow(T, UNIVERSE, frames={"bars": 12345})


def test_a_caller_cannot_widen_a_window_through_the_frames_mapping():
    # The mapping handed in is copied at construction, so holding a reference
    # to it is not a way to add a frame to a live window afterwards.
    supplied = {"bars": pa.table({"a": [1]})}
    window = MarketWindow(T, UNIVERSE, frames=supplied)
    supplied["late"] = pa.table({"b": [2]})
    assert list(window.frames) == ["bars"]
    assert window.to_arrow().frame_names == ("bars",)


def test_the_frames_mapping_refuses_mutation(window: MarketWindow):
    # A writable mapping would be a window-widening hole: a signal holding the
    # window could attach data after the decision time was fixed.  `t` being
    # read-only is not enough on its own if the frames beside it are not.
    with pytest.raises(TypeError):
        window.frames["late"] = pa.table({"a": [1]})
    with pytest.raises(TypeError):
        del window.frames["bars"]
    # The mutating dict methods are absent outright rather than raising a
    # per-call error — also a refusal, and the stronger kind.
    assert not hasattr(window.frames, "clear")
    assert not hasattr(window.frames, "pop")
    assert not hasattr(window.frames, "update")
    assert list(window.frames) == ["bars", "trades"]


def test_a_signal_cannot_attach_a_frame_to_a_live_window(window: MarketWindow):
    # The threat model, stated directly — the same shape as feature 4's
    # "reassignment refused from inside a signal".
    def signal(ctx: MarketWindow):
        ctx.frames["future"] = pa.table({"ts": [10**18]})
        return None

    with pytest.raises(TypeError):
        signal(window)
    assert list(window.frames) == ["bars", "trades"]


def test_a_rebuilt_window_also_refuses_frame_mutation(window: MarketWindow):
    # The read path must not be a weaker contract than the constructor.
    rebuilt = window.to_arrow().materialize()
    with pytest.raises(TypeError):
        rebuilt.frames["late"] = pa.table({"a": [1]})
    assert list(rebuilt.frames) == ["bars", "trades"]


def test_the_frames_view_still_reports_the_windows_own_frames(window: MarketWindow, bars):
    # The read-only mapping is a live view, not a copy: reading through it is
    # the point, and it must not have been frozen into something detached.
    assert window.frames["bars"] is bars
    assert len(window.frames) == 2
    assert "trades" in window.frames
    assert dict(window.frames).keys() == {"bars", "trades"}


def test_a_callers_frame_table_is_not_copied_into_the_window(window: MarketWindow, bars):
    # Passing a table through must not copy it: the window captures the table.
    assert window.frames["bars"] is bars


def test_frames_default_to_empty():
    assert dict(MarketWindow(T, UNIVERSE).frames) == {}


def test_a_record_batch_is_accepted_as_a_frame():
    batch = pa.record_batch({"a": pa.array([1, 2], type=pa.int64())})
    window = MarketWindow(T, UNIVERSE, frames={"bars": batch})
    assert window.frames["bars"].num_rows == 2
    assert window.to_arrow().materialize() == window


def test_a_frame_that_is_a_plain_arrow_convertible_is_accepted():
    window = MarketWindow(T, UNIVERSE, frames={"bars": {"a": [1, 2, 3]}})
    assert window.frames["bars"].num_rows == 3


# --------------------------------------------------------------------------
# Copy, pickle, and the surrounding contract
# --------------------------------------------------------------------------


def test_copy_and_pickle_carry_the_frames(window: MarketWindow):
    # A window is a value that travels; losing its frames on copy would make
    # the copy a different window that still compared equal on (t, universe).
    for rebuilt in (
        copy.copy(window),
        copy.deepcopy(window),
        pickle.loads(pickle.dumps(window)),
    ):
        assert rebuilt == window
        assert list(rebuilt.frames) == ["bars", "trades"]
        assert rebuilt.frames["bars"].equals(window.frames["bars"])


def test_a_pickled_window_is_still_immutable(window: MarketWindow):
    rebuilt = pickle.loads(pickle.dumps(window))
    with pytest.raises(AttributeError):
        rebuilt.t = T + timedelta(days=1)


def test_a_payload_is_immutable_once_written(window: MarketWindow):
    # The host must not be able to swap the bytes under a dispatched payload.
    # The constructor is single-shot (TypeError), matching MarketWindow's own
    # convention; the slots and the absent setters cover the rest.
    payload = window.to_arrow()
    before = bytes(payload)
    with pytest.raises(AttributeError):
        payload.buffer = None
    with pytest.raises(AttributeError):
        del payload.buffer
    with pytest.raises(TypeError, match="already initialized"):
        payload.__init__(payload.buffer, {})
    assert bytes(payload) == before


def test_payload_equality_is_by_content():
    table = pa.table({"a": [1]})
    window = MarketWindow(T, UNIVERSE, frames={"bars": table})
    assert window.to_arrow() == window.to_arrow()
    other = MarketWindow(T, UNIVERSE, frames={"bars": pa.table({"a": [2]})})
    assert window.to_arrow() != other.to_arrow()


def test_a_payload_is_hashable():
    window = MarketWindow(T, UNIVERSE, frames={"bars": pa.table({"a": [1]})})
    assert len({window.to_arrow(), window.to_arrow()}) == 1


def test_the_abi_record_still_composes_after_this_feature():
    # Whatever else changed, the composed component is unchanged — a payload
    # API must not perturb the ABI record the factory advertises.
    from app.module_loader import create_app

    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "packages" / "contract" / "src"
    component = create_app(src).get("contract")
    assert component["contract_version"] == CONTRACT_VERSION
    assert component["market_window"] == "contract:MarketWindow"
