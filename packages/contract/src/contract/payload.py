"""Serializing a materialized :class:`~contract.window.MarketWindow` to Arrow IPC.

Feature 14 of app_spec.xml: "System serializes a materialized MarketWindow to
Arrow IPC so the sandbox receives data over a payload channel with zero_copy
transfer" (docs/nullius-tech-architecture.md §5.2, where the host hands the
sandbox ``payload=window.to_arrow()``).

Three words in that sentence carry the design:

*materialized*
    A window is not a view onto the lake — the sandbox holds no filesystem
    mounts (§5.2), so a window that has not pulled its frames into memory has
    nothing to send.  :func:`serialize_window` therefore refuses a window with
    no frames rather than shipping a header the sandbox cannot answer for.
    The refusal is the point: an empty payload that *looks* like a window is
    exactly the failure that would surface as an unexplainable zero signal
    three systems downstream.

*payload channel*
    The bytes travel as one self-describing payload; nothing else crosses.
    :class:`PayloadChannel` is that seam — bytes in, bytes out — and it holds
    no path, no handle and no fd, so a receiver cannot accidentally depend on
    the sender's filesystem.

*zero_copy*
    The reader must not pay for the data twice.  :meth:`MarketWindowPayload.materialize`
    hands every frame back as an Arrow table whose buffers are *views into the
    payload*, never copies of it (the one exception is documented at
    :meth:`MarketWindowPayload.from_bytes`).  That claim is cheap to assert and
    expensive to believe, so :func:`frames_alias_payload` checks it against
    real buffer addresses rather than trusting the paragraph above; the suite
    uses the same helper.

The wire format — a framed container of Arrow IPC streams
--------------------------------------------------------

A bare Arrow IPC stream cannot carry this window.  Arrow's own metadata is
per-*schema*, and the window's facts (decision time, universe, contract
version) are per-*payload*; encoding them as a synthetic column would make
every frame's schema a lie, and dropping them would lose the one thing the
window exists to pin.  So the payload is a framed container:

.. code-block:: text

    magic       b"NLSWIPC\\x00"                 8 bytes
    version     uint32 LE                       4
    segments    uint32 LE                       4
    lengths     segments x uint64 LE
    body        the segments, concatenated

    segment 0   manifest: an IPC stream with an EMPTY schema whose metadata
                carries the window's facts (decision time, universe, contract
                version, frame names, payload version)
    segment 1.. one IPC stream per frame, in manifest order

The manifest is a zero-column Arrow IPC stream rather than a JSON blob so the
whole container stays Arrow, and a reader can read the window's facts without
touching a single frame.  The order of segments is the manifest's frame order,
so a payload has exactly one parse.

Every read below slices the source buffer rather than copying it:
``pa.Buffer.slice`` is a view, and the Arrow arrays built from those slices
keep pointing into the original allocation.  :func:`frames_alias_payload`
verifies precisely that.
"""

from __future__ import annotations

import json
import struct
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Sequence, Tuple

from ._arrow import require_arrow

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pyarrow

    from .window import MarketWindow

__all__ = [
    "MANIFEST_SEGMENT",
    "PAYLOAD_MAGIC",
    "PAYLOAD_VERSION",
    "MarketWindowPayload",
    "NoPayloadError",
    "PayloadChannel",
    "PayloadFormatError",
    "frames_alias_payload",
    "window_from_payload",
    "serialize_window",
]

#: Eight bytes at the head of every payload.  Distinct from Arrow's own
#: stream continuation marker (``b"\\xff\\xff\\xff\\xff"``) so a truncated or
#: misrouted buffer is rejected by inspection instead of being fed to the
#: Arrow reader and failing somewhere less informative.
PAYLOAD_MAGIC = b"NLSWIPC\x00"

#: The container's own version.  Independent of
#: :data:`contract.CONTRACT_VERSION`, which versions the *signal ABI*: the
#: framing and the ABI are versioned by different owners and move for
#: different reasons, so folding them into one number would mean a framing
#: tweak invalidating every stored node's recorded ABI.
PAYLOAD_VERSION = 1

#: The manifest is always segment 0.  Named so the reader's ``lengths[0]``
#: does not read as an unexplained index.
MANIFEST_SEGMENT = 0

_MAGIC_LEN = len(PAYLOAD_MAGIC)
_HEADER_FIXED = _MAGIC_LEN + 4 + 4  # magic + version + segment count
_LENGTH_SIZE = 8

# Manifest metadata keys.  Namespaced, because Arrow schema metadata is a
# shared namespace and a frame's own schema travels in the same payload.
_META_PAYLOAD_VERSION = b"nullius.payload.version"
_META_CONTRACT_VERSION = b"nullius.contract.version"
_META_DECISION_TIME = b"nullius.decision_time"
_META_UNIVERSE = b"nullius.universe"
_META_FRAMES = b"nullius.frames"


class PayloadFormatError(ValueError):
    """A payload is not a well-formed Arrow IPC window payload.

    Raised for a bad magic, an unknown container version, a truncated header,
    a segment count or length that does not match the bytes actually present,
    or a manifest missing a required key.  Deliberately one class: every one
    of these means the same thing to a caller — *these bytes are not a window*
    — and a caller that wanted to distinguish them would be reading a
    malformed payload from an untrusted channel, where the right response is
    to refuse, not to branch.
    """


class NoPayloadError(RuntimeError):
    """A :class:`PayloadChannel` was asked for a payload it never received.

    This is the contract-level half of app_spec.xml feature 159 ("System
    rejects a run whose payload did not arrive over the IPC channel"): the
    sandbox holds no filesystem mounts, so a run whose bytes did not arrive
    over the channel has no other way to obtain a window, and must fail
    loudly rather than proceed against an empty one.
    """


def _utc_isoformat(t) -> str:
    """Render a decision time for the manifest.

    ``datetime.isoformat`` on an aware UTC datetime ends in ``+00:00``, which
    :func:`contract.window._as_utc` parses straight back — so the manifest
    round-trips through the same normalizer the constructor uses, and there is
    no second, divergent time parser on the read path.
    """
    return t.isoformat()


def _iter_data_buffers(table: "pyarrow.Table") -> Iterable[object]:
    """Yield every non-null bitmap/value buffer backing ``table``'s columns.

    Walks chunks, not just the first: a table read from IPC is usually
    single-chunk, but ``Table`` is free to hand back several and a zero-copy
    check that inspected only ``chunk(0)`` would pass a payload it had not
    actually verified.
    """
    for column in table.columns:
        for chunk in column.chunks:
            for buffer in chunk.buffers():
                if buffer is not None:
                    yield buffer


def _within(candidate: object, start: int, end: int) -> bool:
    """True when ``candidate`` lies inside the half-open range ``[start, end)``.

    A zero-length buffer is accepted unconditionally: the allocator is free to
    place an empty allocation outside the payload, and an empty buffer carries
    no bytes that could have been copied instead of shared.
    """
    if candidate.size == 0:  # type: ignore[attr-defined]
        return True
    return start <= candidate.address < end  # type: ignore[attr-defined]


def frames_alias_payload(window: "MarketWindow", payload: "MarketWindowPayload") -> bool:
    """True when every frame in ``window`` shares memory with ``payload``.

    The zero-copy claim, made checkable.  For each frame's data and validity
    buffers this asks whether the buffer's address falls inside the payload's
    own memory range — which is only true when the reader sliced the payload
    rather than copying out of it.  A copied payload fails this; a sliced one
    passes it.

    A window with no frames is vacuously aliasing (there is nothing that could
    have been copied).  This is a diagnostic used by the suite and by
    :class:`PayloadChannel`, not a runtime guard on the read path: the reader
    does not branch on it, because a copy is a performance regression, not a
    correctness one, and a payload channel should not fail a run over it.
    """
    if not window.frames:
        return True
    start = payload.buffer.address
    end = start + payload.buffer.size
    return all(
        _within(candidate, start, end)
        for table in window.frames.values()
        for candidate in _iter_data_buffers(table)
    )


class MarketWindowPayload:
    """One serialized window, as it travels over the payload channel.

    Immutable and single-shot in the same spirit as the window it carries: the
    buffer is bound once at construction and cannot be rebound or deleted, so
    a payload handed to the sandbox cannot have the bytes under it swapped by
    a later writer on the host side.

    The payload keeps the source :class:`pyarrow.Buffer` alive, which is what
    makes the zero-copy read sound: the frames materialized from it hold views
    into that allocation, so the buffer must outlive them.
    """

    __slots__ = ("_buffer", "_manifest", "_initialized")

    def __init__(self, arrow_buffer, manifest: Mapping[str, object]) -> None:
        if getattr(self, "_initialized", False):
            raise TypeError(
                f"{type(self).__name__} is already initialized; a payload is "
                "written once at construction"
            )
        object.__setattr__(self, "_buffer", arrow_buffer)
        object.__setattr__(self, "_manifest", dict(manifest))
        object.__setattr__(self, "_initialized", True)

    # -- construction -----------------------------------------------------

    @classmethod
    def from_window(cls, window: "MarketWindow") -> "MarketWindowPayload":
        """Serialize ``window`` into a payload.  The host-side write."""
        return serialize_window(window)

    @classmethod
    def from_bytes(cls, data: bytes) -> "MarketWindowPayload":
        """Rebuild a payload from raw bytes received over a channel.

        ``pa.py_buffer`` wraps the ``bytes`` object without copying it, so the
        frames read from the result still alias *this* byte string.  The cost
        a channel pays is the one it already paid to get the bytes here — a
        socket read, say — and the reader adds no second one on top.
        """
        arrow = require_arrow()
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(
                "payload data must be bytes, bytearray or memoryview, got "
                f"{type(data).__name__}"
            )
        arrow_buffer = arrow.py_buffer(data)
        return cls._parse(arrow_buffer)

    @classmethod
    def _parse(cls, buffer) -> "MarketWindowPayload":
        """Validate the framing and read the manifest. Frames are not touched.

        Cheap by design: the callers that only need the window's facts — a
        gate asking which universe arrived, a channel sizing the payload —
        should not pay to materialize every frame to learn them.
        """
        arrow = require_arrow()
        size = buffer.size
        if size < _HEADER_FIXED:
            raise PayloadFormatError(
                f"payload is {size} bytes, too short to hold a "
                f"{_HEADER_FIXED}-byte header"
            )
        if bytes(buffer.slice(0, _MAGIC_LEN)) != PAYLOAD_MAGIC:
            raise PayloadFormatError(
                "payload does not begin with the Arrow IPC window magic "
                f"{PAYLOAD_MAGIC!r}; these bytes are not a nullius window payload"
            )
        version, segments = struct.unpack("<II", buffer.slice(_MAGIC_LEN, 8).to_pybytes())
        if version != PAYLOAD_VERSION:
            raise PayloadFormatError(
                f"payload version {version} is not supported; this reader "
                f"understands version {PAYLOAD_VERSION}"
            )
        if segments < 1:
            raise PayloadFormatError("payload declares zero segments; segment 0 is the manifest")
        lengths_end = _HEADER_FIXED + segments * _LENGTH_SIZE
        if size < lengths_end:
            raise PayloadFormatError(
                f"payload declares {segments} segments but is only {size} "
                f"bytes; the length table alone needs {lengths_end}"
            )
        lengths = struct.unpack(
            f"<{segments}Q", buffer.slice(_HEADER_FIXED, segments * _LENGTH_SIZE).to_pybytes()
        )
        if lengths_end + sum(lengths) != size:
            raise PayloadFormatError(
                f"payload segment lengths sum to {sum(lengths)} bytes but "
                f"{size - lengths_end} bytes follow the header; the payload "
                "is truncated or padded"
            )

        # Read the manifest without materializing a frame: segment 0 only.
        manifest_segment = buffer.slice(lengths_end, lengths[MANIFEST_SEGMENT])
        try:
            manifest_schema = arrow.ipc.open_stream(
                arrow.BufferReader(manifest_segment)
            ).schema
        except Exception as exc:  # noqa: BLE001 - Arrow raises several shapes here
            raise PayloadFormatError(
                f"payload manifest (segment 0) is not a readable Arrow IPC stream: {exc}"
            ) from exc

        raw = manifest_schema.metadata or {}
        try:
            manifest = {
                "payload_version": int(raw[_META_PAYLOAD_VERSION]),
                "contract_version": raw[_META_CONTRACT_VERSION].decode("utf-8"),
                "decision_time": raw[_META_DECISION_TIME].decode("utf-8"),
                "universe": tuple(json.loads(raw[_META_UNIVERSE].decode("utf-8"))),
                "frames": tuple(json.loads(raw[_META_FRAMES].decode("utf-8"))),
                "lengths": lengths,
            }
        except KeyError as exc:
            raise PayloadFormatError(
                f"payload manifest is missing the required {exc.args[0]!r} key"
            ) from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise PayloadFormatError(f"payload manifest is not readable: {exc}") from exc

        if len(manifest["frames"]) != segments - 1:
            raise PayloadFormatError(
                f"payload manifest names {len(manifest['frames'])} frames but "
                f"{segments - 1} frame segments follow it"
            )
        return cls(buffer, manifest)

    # -- the buffer -------------------------------------------------------

    @property
    def buffer(self):
        """The underlying :class:`pyarrow.Buffer`.  Zero-copy by definition."""
        return self._buffer

    @property
    def size(self) -> int:
        """Total payload size in bytes, header and manifest included."""
        return self._buffer.size

    def __bytes__(self) -> bytes:
        """A copy of the payload as plain bytes.

        This is the copy.  Use it to cross a boundary that requires a
        ``bytes`` object (a socket write, a digest); use
        :attr:`buffer`/:meth:`materialize` to stay zero-copy.
        """
        return self._buffer.to_pybytes()

    # -- the window's facts, without materializing a frame ----------------

    @property
    def contract_version(self) -> str:
        """The signal ABI version the sending host serialized under."""
        return self._manifest["contract_version"]

    @property
    def decision_time(self) -> str:
        """The window's decision time, as the ISO-8601 string it travels as."""
        return self._manifest["decision_time"]

    @property
    def universe(self) -> Tuple[str, ...]:
        """The symbols tradable as of the decision time."""
        return self._manifest["universe"]

    @property
    def frame_names(self) -> Tuple[str, ...]:
        """The frame names, in the order their segments appear."""
        return self._manifest["frames"]

    @property
    def frame_sizes(self) -> Mapping[str, int]:
        """Per-frame segment sizes in bytes, keyed by frame name.

        Useful for reasoning about a payload's weight without reading it —
        and, in the suite, for asserting that a frame's bytes really do come
        out of the segment that claims to hold them.
        """
        lengths = self._manifest["lengths"]
        return {
            name: lengths[MANIFEST_SEGMENT + 1 + index]
            for index, name in enumerate(self.frame_names)
        }

    # -- the read ---------------------------------------------------------

    def materialize(self) -> "MarketWindow":
        """Rebuild the window, reading every frame zero-copy.

        Each frame segment is *sliced* out of the payload buffer and handed to
        the Arrow IPC reader, whose arrays keep pointing into that allocation.
        Nothing is copied, and the payload keeps the allocation alive for as
        long as the returned window holds those frames — which is why the
        window, not the caller, is the thing to keep.
        """
        return window_from_payload(self)

    def _frame_table(self, index: int):
        """Read frame ``index`` as a zero-copy table."""
        arrow = require_arrow()
        lengths = self._manifest["lengths"]
        offset = _HEADER_FIXED + len(lengths) * _LENGTH_SIZE + lengths[MANIFEST_SEGMENT]
        for prior in lengths[MANIFEST_SEGMENT + 1 : MANIFEST_SEGMENT + 1 + index]:
            offset += prior
        segment = self._buffer.slice(offset, lengths[MANIFEST_SEGMENT + 1 + index])
        name = self.frame_names[index]
        try:
            return arrow.ipc.open_stream(arrow.BufferReader(segment)).read_all()
        except Exception as exc:  # noqa: BLE001 - Arrow raises several shapes here
            raise PayloadFormatError(
                f"payload frame {name!r} (segment {index + 1}) is not a readable "
                f"Arrow IPC stream: {exc}"
            ) from exc

    # -- value semantics --------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MarketWindowPayload):
            return NotImplemented
        return self._manifest == other._manifest and self._buffer.to_pybytes() == other._buffer.to_pybytes()

    def __hash__(self) -> int:
        # Immutable, so the hash cannot drift — but hashing the bytes of a
        # multi-megabyte payload to key a dict is a poor trade, and the same
        # payload is normally compared by identity.  Hash the facts instead:
        # consistent with __eq__ (equal payloads have equal facts), cheap, and
        # honest about being a summary.
        return hash(
            (
                self._manifest["decision_time"],
                self._manifest["universe"],
                self._manifest["frames"],
                self._buffer.size,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"MarketWindowPayload(t={self.decision_time!r}, "
            f"frames={list(self.frame_names)!r}, bytes={self.size})"
        )


def serialize_window(window: "MarketWindow") -> MarketWindowPayload:
    """Serialize a materialized ``window`` to an Arrow IPC payload.

    Refuses a window that holds no frames.  The sandbox has no filesystem
    mounts (§5.2), so a window with nothing materialized cannot be answered
    for on the far side; sending a header-only payload would turn that into a
    silently empty signal vector — a failure that surfaces as an unexplainable
    zero far from its cause.  A window that genuinely means "no data" says so
    with an empty frame, which is a table with rows and columns and no rows,
    not an absent one.
    """
    arrow = require_arrow()
    from . import CONTRACT_VERSION

    frames = window.frames
    if not frames:
        raise ValueError(
            "cannot serialize an unmaterialized MarketWindow: it holds no "
            "frames, and the sandbox has no filesystem mounts to read one "
            "from. Materialize the frames on the window first "
            f"(decision time {window.t.isoformat()})."
        )

    manifest = {
        "payload_version": PAYLOAD_VERSION,
        "contract_version": CONTRACT_VERSION,
        "decision_time": _utc_isoformat(window.t),
        "universe": tuple(window.universe),
        "frames": tuple(frames),
    }

    # Segment 0 is the manifest: a zero-column IPC stream whose *schema
    # metadata* carries the window's facts.  Zero columns rather than a
    # synthetic row, so the manifest cannot be mistaken for a frame by a
    # reader that ignores names.
    segments = [
        _write_stream(
            arrow, arrow.schema([], metadata=_encode_metadata(manifest)), []
        )
    ]
    for table in frames.values():
        segments.append(_write_stream(arrow, table.schema, table.to_batches()))

    lengths = [segment.size for segment in segments]
    header = PAYLOAD_MAGIC + struct.pack("<II", PAYLOAD_VERSION, len(segments))
    length_table = b"".join(struct.pack("<Q", size) for size in lengths)
    body = b"".join(segment.to_pybytes() for segment in segments)

    # The manifest is completed with the segment layout the buffer now has, so
    # the write side hands the read side exactly the dictionary _parse would
    # rebuild from these bytes — one shape, constructed once, rather than an
    # encode-then-decode pair that could drift.
    return MarketWindowPayload(
        arrow.py_buffer(header + length_table + body),
        {**manifest, "lengths": tuple(lengths)},
    )


def _encode_metadata(manifest: Mapping[str, object]) -> dict:
    """Render a manifest into Arrow schema-metadata key/value pairs.

    The inverse of :meth:`MarketWindowPayload._parse`'s decode.  Both live in
    this module, adjacent, so a key renamed on one side cannot survive review
    on the other — the drift would be visible in the diff.
    """
    return {
        _META_PAYLOAD_VERSION: str(manifest["payload_version"]).encode("utf-8"),
        _META_CONTRACT_VERSION: str(manifest["contract_version"]).encode("utf-8"),
        _META_DECISION_TIME: str(manifest["decision_time"]).encode("utf-8"),
        _META_UNIVERSE: json.dumps(list(manifest["universe"])).encode("utf-8"),
        _META_FRAMES: json.dumps(list(manifest["frames"])).encode("utf-8"),
    }


def _write_stream(arrow, schema, batches: Sequence[object]):
    """Write one Arrow IPC stream, returning its buffer."""
    sink = arrow.BufferOutputStream()
    with arrow.ipc.new_stream(sink, schema) as writer:
        for batch in batches:
            writer.write_batch(batch)
    return sink.getvalue()


def window_from_payload(payload: MarketWindowPayload) -> "MarketWindow":
    """Rebuild the window a ``payload`` carries.

    The frames come back as Arrow tables aliasing the payload's memory; the
    decision time and universe travel through the same constructor a
    hand-built window uses, so a window that arrived over the channel is
    validated exactly as strictly as one built in-process — including the
    read-only decision time and the UTC normalization.

    Named for the payload it consumes rather than ``materialize_window``,
    which docs/nullius-tech-architecture.md §5.2 already uses for the
    *opposite* operation — the host-side builder that slices a sealed snapshot
    into a window (features 5-9 territory).  Two functions called
    ``materialize_window`` in one namespace, taking a snapshot and a payload
    respectively, is a collision the next feature would have walked into.
    """
    from .window import MarketWindow

    frames = {
        name: payload._frame_table(index)
        for index, name in enumerate(payload.frame_names)
    }
    return MarketWindow(
        payload.decision_time,
        universe=payload.universe,
        frames=frames,
    )


class PayloadChannel:
    """The host-to-sandbox payload channel.

    Deliberately thin, and deliberately not a transport.  It is the seam the
    feature names: one side puts a serialized window in, the other takes a
    serialized window out, and nothing but bytes crosses.  There is no path,
    no fd, and no handle here — which is the whole reason the sandbox can be
    run with no filesystem mounts at all (§5.2).  A real deployment backs this
    with a pipe or a socket; the contract it must satisfy is the one pinned
    here: the bytes arrive intact, or :meth:`receive` raises.

    Single-shot per side, mirroring the single-shot constructor on the window:
    a channel that accepted two sends would need a rule for whether the second
    replaced the first, and any such rule is a way for a run to be evaluated
    against a window other than the one it was dispatched with.
    """

    __slots__ = ("_payload",)

    def __init__(self) -> None:
        self._payload: Optional[MarketWindowPayload] = None

    def send(self, window: "MarketWindow") -> MarketWindowPayload:
        """Serialize ``window`` and put it on the channel.

        Returns the payload so the caller can observe what it sent — size,
        frame names — without a second serialization.
        """
        if self._payload is not None:
            raise RuntimeError(
                "this channel already carries a payload; a sandbox run is "
                "evaluated against exactly one window"
            )
        self._payload = serialize_window(window)
        return self._payload

    def receive(self) -> MarketWindowPayload:
        """Take the payload off the channel.

        Raises :class:`NoPayloadError` when nothing was sent.  This is the
        contract-level half of feature 159: with no mounts and no payload,
        there is no window, and a run must not proceed against an empty one.
        """
        if self._payload is None:
            raise NoPayloadError(
                "no payload arrived over this channel; the sandbox holds no "
                "filesystem mounts, so a run without one has no window to "
                "evaluate against"
            )
        return self._payload

    @property
    def empty(self) -> bool:
        """True when nothing has been sent.  Never a substitute for receive()."""
        return self._payload is None

    def materialize(self) -> "MarketWindow":
        """Receive and materialize in one step, zero-copy."""
        return self.receive().materialize()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"PayloadChannel({'empty' if self.empty else f'{self._payload.size} bytes'})"
