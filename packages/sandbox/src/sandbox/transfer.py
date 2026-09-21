"""Feature 166's law: the window and its scores cross one channel.

app_spec.xml, "Untrusted Code Sandbox", feature 166: *System transfers the
materialized window as Arrow IPC, which returns the resulting score vector
over the same channel.*

The sentence is one clause long and carries three claims, each owned here as a
seam rather than a comment:

* **the materialized window as Arrow IPC** — the inbound leg.  §5.2's call
  site spells it ``payload=window.to_arrow()    # IPC, zero-copy`` and its
  control table gives the reason the bytes exist at all: ``Filesystem | No
  mounts.  Data arrives over IPC only.``  The box has no disk to read a window
  from, so the payload *is* the window, and this module is what establishes
  that the bytes which arrived are one.

* **over the same channel** — the frame the whole feature turns on.  Not two
  channels, not a request and a separate reply pipe: one channel, one
  lifecycle, two directions.  :class:`TransferChannel` is that object, and it
  is deliberately one-shot per direction — a channel that accepted a second
  window would need a rule for whether the second replaced the first, and any
  such rule is a way for a run to be evaluated against a window other than the
  one it was dispatched with.

* **returns the resulting score vector** — the outbound leg, and the one place
  this feature *validates* rather than merely carries.  A score vector is
  positional against the window's universe (feature 11's "indexed by symbol"
  is a positional correspondence, never a labelled axis), so a return of the
  right shape and the wrong length is a misalignment that would travel
  silently into §6.1's cross-sectional reduction and poison every number after
  it.  The channel therefore holds the universe it carried and refuses a
  return that does not match it.

**Why this is a *law* about bytes rather than a runner.**  The category's
features each add a control to the same box: 157 refuses a run configured
without gVisor, 167 refuses a submission importing outside the ceiling, and
this one refuses a *transfer* that did not survive the channel.  It does not
execute anything — the evaluator's host-side runner (``evaluator._sandbox``)
is what compiles untrusted code and spawns the child (§6.1 step 2), and it
says so in its own docstring.  What crosses into that child, and what crosses
back, is this module's subject; :meth:`SandboxTransfer.round_trip` takes the
producer as a *callable* for exactly that reason, so the box's execution stays
where it belongs and this member never grows a runner.

**Both legs are self-describing, and that is how a misroute is caught.**  The
window leg is contract's payload container, which begins
``b"NLSWIPC\\x00"`` (feature 14); the score leg is this module's own container,
which begins :data:`SCORE_MAGIC`.  Neither magic can be mistaken for Arrow's
own stream continuation marker (``b"\\xff\\xff\\xff\\xff"``) or for the other,
so a buffer arriving on the wrong leg is refused *by inspection* rather than
fed to an Arrow reader and failing somewhere less informative — the same
discipline, and the same reason, that contract's payload module states for its
own magic.

**Why the score container is a framed container and not a bare IPC stream.**  A
bare Arrow IPC stream is per-*schema*, and this vector's facts — the universe
it scores, the decision time it scores at, the ABI version that produced it —
are per-*payload*.  Encoding them as a synthetic column would make the score
schema a lie, and dropping them would lose the one thing that makes the return
attributable to the window that went out.  So the score payload frames a
manifest (a zero-column IPC stream whose metadata carries the facts) ahead of
one data segment, the shape feature 14 chose for the same reason:

.. code-block:: text

    magic       b"NLSCORE\\x00"                 8 bytes
    version     uint32 LE                       4
    segments    uint32 LE                       4
    lengths     segments x uint64 LE
    body        segment 0 = manifest, segment 1 = scores

**Zero-copy on the return leg, and the claim is machine-checked.**  The reader
slices the received buffer rather than copying it, so the score array — and the
:class:`polars.Series` built over it — keeps pointing into the allocation the
channel delivered.  That claim is cheap to assert and expensive to believe, so
:func:`scores_alias_payload` checks it against real buffer addresses rather
than trusting the paragraph above; the suite uses the same helper.  Feature 14
makes the identical claim for the window leg and checks it the same way.

**What is deliberately absent: a committed artifact.**  Every other control in
this category ships one — feature 157's ``isolation_policy.json``, feature
167's ``imports_allowlist.json`` — because each is a *configuration* law, and a
configuration has to be written down before it can be checked.  This feature
has no configurable term: its sentence names a format, a direction and a
validation, and none of the three is a policy a deployment could set
differently.  Inventing an artifact here would be inventing a knob nobody
turns, so there is none, and the absence is the statement that the transfer
has nothing about it to configure.

**Error translation at the seam.**  The inbound leg reads a container feature
14 wrote, but this module does not import ``contract`` — the sandbox is the box
untrusted code is put inside, and its vocabulary and its dependencies must not
be the ones it is supposed to contain.  So the framing is re-read here against
the *format*, and every refusal is translated into this member's own
:class:`~sandbox.errors.WindowTransferError` /
:class:`~sandbox.errors.ScoreChannelError` rather than propagating the
contract's type: a caller catching :class:`~sandbox.errors.SandboxError` must
not be silently subscribed to the contract's errors, and a caller catching the
contract's must not accidentally swallow a sandbox refusal.

``pyarrow`` and ``polars`` are reached **lazily**, inside the functions that
need them, for the reason the evaluator's runner states for its own layering:
the factory scans every workspace member on every ``create_app()`` call — the
bare test process, the composition scan, the replay path §1 forbids from
reaching the evaluator — so importing this module must stay stdlib-only, and
composing the application must not pay the payload stack's import cost.
"""

from __future__ import annotations

import enum
import io
import json
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .errors import (
    ScoreChannelError,
    WindowTransferError,
)

__all__ = [
    "SCORE_CHANNEL_CODE",
    "SCORE_FRAME_NAME",
    "SCORE_MAGIC",
    "SCORE_VERSION",
    "TRANSFER_COMPONENT_NAME",
    "WINDOW_TRANSFER_CODE",
    "SandboxTransfer",
    "ScoreVector",
    "TransferChannel",
    "TransferLeg",
    "WindowFacts",
    "decode_scores",
    "encode_scores",
    "inspect_window_payload",
    "sandbox_transfer",
    "scores_alias_payload",
]

#: Eight bytes at the head of every score payload.  Distinct from the window
#: container's magic (:data:`contract.payload.PAYLOAD_MAGIC`,
#: ``b"NLSWIPC\\x00"``) and from Arrow's stream continuation marker, so a
#: buffer that arrived on the wrong leg — or a bare Arrow stream handed to the
#: score reader — is refused by inspection instead of being parsed as something
#: it is not.
SCORE_MAGIC: Final[bytes] = b"NLSCORE\x00"

#: The score container's own version.  Independent of the signal ABI's
#: ``CONTRACT_VERSION`` (feature 15), which travels *inside* the manifest as a
#: carried fact: this number versions the framing, that one versions the
#: contract the values were produced under, and a reader must be able to reject
#: an unreadable frame without first understanding the ABI.
SCORE_VERSION: Final[int] = 1

#: The greppable code every score-channel refusal carries, the discipline
#: feature 157's ``gvisor_isolation_required`` and feature 167's
#: ``disallowed_import`` take: an operator grepping a log for the rejection
#: finds it by a token rather than by prose.  It names the *outbound* leg,
#: which is the one the feature's sentence gives a return value.
SCORE_CHANNEL_CODE: Final[str] = "score_channel"

#: The greppable code every window-transfer refusal carries — the inbound
#: leg's counterpart to :data:`SCORE_CHANNEL_CODE`.  Two codes rather than one
#: because the two legs fail for unrelated reasons, and an operator paging on
#: "the window never arrived" is asking a different question from one paging on
#: "the return was not a score vector"; a single code would make the log
#: unable to answer either.
WINDOW_TRANSFER_CODE: Final[str] = "window_transfer"

#: The component name this law registers under — beside feature 157's
#: ``sandbox`` and feature 167's ``sandbox-imports``, not instead of either:
#: the factory's registry is keyed by name and a later registration of the same
#: name replaces the earlier one, so each control in this category takes its
#: own seat on the member rather than overwriting its siblings'.
TRANSFER_COMPONENT_NAME: Final[str] = "sandbox-transfer"

#: The column the score frame carries.  One column, named once: a signal
#: returns *a vector*, not a table, and a schema that admitted several columns
#: would be a different contract (feature 11) wearing this one's name.
SCORE_FRAME_NAME: Final[str] = "scores"

#: The window container's magic, spelled here rather than imported from
#: ``contract`` — see the module docstring's error-translation note.  It is a
#: *format* constant, published with feature 14, and the sandbox pins its own
#: reading of it so the box depends on nothing it is meant to contain.
WINDOW_MAGIC: Final[bytes] = b"NLSWIPC\x00"

#: The window container's framing version, for the same reason.
WINDOW_VERSION: Final[int] = 1

_MAGIC_LEN: Final[int] = len(SCORE_MAGIC)
_HEADER_FIXED: Final[int] = _MAGIC_LEN + 4 + 4  # magic + version + segments
_LENGTH_SIZE: Final[int] = 8
_MANIFEST_SEGMENT: Final[int] = 0

#: Manifest metadata keys, on both legs — the window container's own keys,
#: read tolerantly (a fact that is absent is carried as ``None`` rather than
#: refused: this member reads the *format*, and a deployment whose feature-14
#: payload carries fewer facts than this build expects is a version skew to
#: report, not a transfer to break).
_META_CONTRACT_VERSION: Final[bytes] = b"nullius.contract.version"
_META_DECISION_TIME: Final[bytes] = b"nullius.decision_time"
_META_UNIVERSE: Final[bytes] = b"nullius.universe"
_META_FRAMES: Final[bytes] = b"nullius.frames"
_META_SCORE_VERSION: Final[bytes] = b"nullius.score.version"

#: The metadata key this module adds to the *score* manifest: the window's
#: decision time, repeated on the return leg so a vector is attributable
#: without holding the payload that produced it.
_META_SCORES_FOR: Final[bytes] = b"nullius.scores_for"


def _require_arrow() -> Any:
    """Import ``pyarrow`` lazily, naming the fix when it is absent.

    Lazy for the reason the module docstring gives — composition scans this
    member on every ``create_app()`` — and named rather than bare so a
    deployment missing the payload stack learns which stack, and what to run,
    instead of meeting a ``ModuleNotFoundError`` from a function that looked
    like it only moved bytes.
    """
    try:
        import pyarrow
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise WindowTransferError(
            "the sandbox payload channel requires pyarrow, which this member "
            "declares for the Arrow IPC container both legs travel in; run "
            "`uv sync --all-packages` in the workspace root"
        ) from exc
    return pyarrow


def _require_polars() -> Any:
    """Import ``polars`` lazily, naming the fix when it is absent.

    Needed only by the return leg, to hand the scores back in the type feature
    11 declares a signal returns.  Absent, the wire format is still readable —
    but "returns the resulting score vector" means a score vector, not a
    pyarrow array a caller would have to convert, so a reader without polars
    refuses rather than answering a different question.
    """
    try:
        import polars
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ScoreChannelError(
            f"{SCORE_CHANNEL_CODE}: reading a score vector off the channel "
            f"requires polars, which this member declares for the return type "
            f"feature 11 pins (a signal returns a polars.Series indexed "
            f"positionally by the window's universe); run `uv sync "
            f"--all-packages` in the workspace root"
        ) from exc
    return polars


def _as_bytes(data: object, *, leg: str, code: str) -> bytes:
    """Coerce a channel buffer to ``bytes``, refusing anything else.

    One spelling of "what a channel carries" for both legs and both
    directions, so the four entry points cannot disagree about it.  A
    ``memoryview`` is accepted and copied: it is a view over someone else's
    allocation, and holding one across the channel's lifetime would make the
    sender's buffer — not the payload — the thing keeping the bytes alive.
    """
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)
    raise WindowTransferError(
        f"{code}: the {leg} leg of the sandbox payload channel carries bytes, got "
        f"{type(data).__name__}: {data!r}. The channel is a byte seam — "
        f"nothing but bytes crosses it, which is what lets the box run with "
        f"no filesystem mounts at all (docs/nullius-tech-architecture.md "
        f"§5.2), and a caller handing it a window object, a series or a path "
        f"has not serialized anything yet (feature 166, {code})."
    )


@dataclass(frozen=True)
class WindowFacts:
    """What the channel could prove about the window that crossed.

    Read from the payload's manifest — segment 0 only — so establishing these
    costs no frame materialization: a caller that only needs to know *which
    universe arrived at which decision time* should not pay to decode every
    frame to learn it, the property feature 14's own parse states for its
    manifest.

    ``universe`` is the load-bearing field, because it is what the return leg
    is validated against: :meth:`TransferChannel.return_scores` refuses a
    score vector whose length disagrees with it, so a misaligned return cannot
    reach §6.1's cross-sectional reduction at all.  The other three are carried
    provenance — the facts that make a transfer attributable in a log.

    ``contract_version``, ``decision_time`` and ``frame_names`` are ``None``/
    empty for a payload whose manifest does not carry them: this member reads
    the window *format*, and a deployment running a feature-14 build that
    publishes fewer facts is a version skew to report rather than a transfer to
    break.
    """

    #: The symbols the window holds, in the order a score vector is positional
    #: against.  Empty when the manifest did not carry them — and an empty
    #: universe is then a *refusal* for any non-empty return, which is the
    #: conservative direction.
    universe: tuple[str, ...]
    #: The ABI version the window was serialized under (feature 15), carried
    #: opaquely: this member does not interpret it, it keeps it attributable.
    contract_version: str | None
    #: The window's decision time, as the manifest's ISO-8601 string.
    decision_time: str | None
    #: The frames the payload holds, in segment order.  Facts, not data: the
    #: frames themselves are materialized by the caller that needs them.
    frame_names: tuple[str, ...]
    #: The payload's total size in bytes, header and manifest included.
    size: int

    @property
    def symbols(self) -> int:
        """How many symbols the window holds — the length a return must have."""
        return len(self.universe)


@dataclass(frozen=True)
class ScoreVector:
    """The score vector that came back, and the window it answers for.

    ``scores`` is a :class:`polars.Series` whose *i*-th value is the score for
    the *i*-th symbol of :attr:`universe` — feature 11's positional
    correspondence, unchanged by the round trip through Arrow.  The series
    shares the received payload's allocation rather than copying it; see
    :func:`scores_alias_payload`, which asserts exactly that.

    :meth:`require` is the verb a caller that must not proceed wants: it turns
    "this return is not a score vector" into the exception
    (:class:`~sandbox.errors.ScoreChannelError`) at the point of use, so a
    caller can put it on the last line before it feeds the vector downstream.
    """

    #: The scores, positional against :attr:`universe`.
    scores: Any
    #: The symbols the scores are for, in order.
    universe: tuple[str, ...]
    #: The decision time the vector scores at, carried from the window.
    decision_time: str | None
    #: The ABI version that produced the vector, carried from the window.
    contract_version: str | None
    #: The score container's size in bytes, header and manifest included.
    size: int

    def values(self) -> list[float]:
        """The scores as plain Python floats, in universe order.

        A convenience for a caller that wants the numbers rather than the
        column — a log line, an assertion, a test.  It copies, deliberately
        named as a method rather than a property so the cost is visible at the
        call site: the zero-copy path is :attr:`scores`.
        """
        return [float(value) for value in self.scores.to_list()]

    def as_mapping(self) -> dict[str, float]:
        """The scores keyed by symbol — the readable form of the vector.

        Positional correspondence made explicit, for an operator or a test
        asking *what did this node say about BTCUSDT?*.  Refuses when the
        universe and the scores disagree in length, which cannot happen for a
        vector that came off the channel (that alignment is validated at both
        ends) but is checkable here for one assembled by hand.
        """
        symbols = self.universe
        values = self.values()
        if len(symbols) != len(values):
            raise ScoreChannelError(
                f"{SCORE_CHANNEL_CODE}: a score vector of {len(values)} values "
                f"cannot be keyed by a universe of {len(symbols)} symbols; the "
                f"correspondence is positional, so a mismatch is a "
                f"misalignment rather than a naming problem (feature 166)."
            )
        return dict(zip(symbols, values))

    def require(self) -> ScoreVector:
        """Return this vector, or raise — the no-op-if-fine verb.

        Present so a caller can write the check unconditionally on the last
        line before it uses the vector, mirroring
        :meth:`sandbox.imports.ModuleDecision.require` and
        :meth:`sandbox.isolation.RunDecision.require`.  The channel already
        raises at the seam, so a vector that exists is a vector that validated;
        the verb is the seam's *shape* kept consistent for a caller composing
        several controls, and it re-checks the one invariant that could still
        be violated by a hand-assembled value: that the scores are a float
        column of the universe's length.
        """
        # Only the length invariant is re-checked, and deliberately *not* an
        # emptiness one: an empty universe with an empty vector is a
        # conforming return, and it is conforming *by this same criterion*.
        # The emptiness case is not an exception to the length rule, it is the
        # length rule's answer for it — a zero-length float column for a
        # zero-length universe, refused when it is anything else.  Refusing
        # emptiness on its own would make this verb disagree with
        # contract.signal.validate_signal_return, which decides the same
        # question for a live return and calls that shape conforming; two
        # checks with the same authority must not answer one question two
        # ways.  It is also a real case rather than a corner: a window can
        # legitimately hold no tradable symbols at a decision time (feature
        # 13's point-in-time universe), and that is a fact, not a failure.
        if len(self.scores) != len(self.universe):
            raise ScoreChannelError(
                f"{SCORE_CHANNEL_CODE}: the score vector carries "
                f"{len(self.scores)} values for a universe of "
                f"{len(self.universe)} symbols. The correspondence is "
                f"positional (feature 11), so a length mismatch is a "
                f"misalignment that would poison every cross-sectional "
                f"reduction downstream rather than a shape to coerce "
                f"(feature 166)."
            )
        return self


class TransferLeg(enum.StrEnum):
    """Which direction of the channel a refusal happened on.

    A str-valued enumeration — the same shape feature 157's ``RunReason`` and
    feature 167's ``ModuleReason`` take — so a refusal's leg is a token a log
    or an assertion can carry without parsing prose.  Two members, because the
    feature's sentence names two legs and a third would be a different channel.
    """

    #: Host → box: the materialized window, as Arrow IPC (feature 14's
    #: container).  A refusal here means the bytes that arrived are not a
    #: window.
    WINDOW = "window"

    #: Box → host: the resulting score vector, over the same channel.  A
    #: refusal here means the bytes that arrived are not a score vector for
    #: the window that went out.
    SCORES = "scores"


def _unpack_container(
    data: bytes, *, magic: bytes, version: int, leg: str, code: str
) -> tuple[int, tuple[int, ...]]:
    """Validate a framed container's header.

    Returns the offset at which the body begins and the segment lengths.
    Pure ``struct`` work on the bytes themselves — no Arrow, no frames — so the
    cheapest possible refusal happens before anything expensive is attempted:
    a buffer that is not a container at all, was written by a later framing
    version, or whose length table does not account for every byte after it, is
    refused here rather than fed to an Arrow reader that would report the
    damage from somewhere further away.

    Returns offsets rather than a body slice on purpose.  Slicing ``bytes``
    *copies*, and a copy here would silently break feature 166's zero-copy
    claim for the return leg — the scores would be read from a private
    allocation instead of the one the channel delivered.  The caller slices an
    Arrow buffer instead (see :func:`_segment_buffer`), which is a view.

    Shared by both legs because both legs are the same container format; the
    magic and the version are parameters because they are the two things that
    differ, and *only* those two — a second spelling of the framing would be a
    second thing to keep in sync.
    """
    size = len(data)
    if size < _HEADER_FIXED:
        raise _refusal(leg, code)(
            f"{code}: the {leg} payload is {size} bytes, too short to hold a "
            f"{_HEADER_FIXED}-byte container header; it is truncated or was "
            f"never a payload (feature 166)."
        )
    if data[:_MAGIC_LEN] != magic:
        raise _refusal(leg, code)(
            f"{code}: the {leg} payload does not begin with the container magic "
            f"{magic!r}; these bytes are not a {leg} payload. Each leg of the "
            f"channel is self-describing precisely so a buffer that arrived on "
            f"the wrong one — or a bare Arrow IPC stream handed to this reader "
            f"— is refused by inspection rather than parsed as something it is "
            f"not (feature 166)."
        )
    header_version, segments = struct.unpack(
        "<II", data[_MAGIC_LEN : _MAGIC_LEN + 8]
    )
    if header_version != version:
        raise _refusal(leg, code)(
            f"{code}: the {leg} payload declares version {header_version}, but this "
            f"reader understands version {version}; the framing moved under "
            f"this build, and reading it anyway would be guessing at the "
            f"segment layout (feature 166)."
        )
    if segments < 1:
        raise _refusal(leg, code)(
            f"{code}: the {leg} payload declares zero segments; segment 0 is the "
            f"manifest, so a container without one carries no facts and no "
            f"data (feature 166)."
        )
    lengths_end = _HEADER_FIXED + segments * _LENGTH_SIZE
    if size < lengths_end:
        raise _refusal(leg, code)(
            f"{code}: the {leg} payload declares {segments} segments but is only "
            f"{size} bytes; the length table alone needs {lengths_end} "
            f"(feature 166)."
        )
    lengths = struct.unpack(
        f"<{segments}Q", data[_HEADER_FIXED : lengths_end]
    )
    if lengths_end + sum(lengths) != size:
        raise _refusal(leg, code)(
            f"{code}: the {leg} payload's segment lengths sum to {sum(lengths)} bytes "
            f"but {size - lengths_end} bytes follow the header; the payload is "
            f"truncated or padded, and a reader that trusted the table would "
            f"slice past the end or leave bytes unaccounted for (feature 166)."
        )
    return lengths_end, tuple(lengths)


def _segment_buffer(buffer: Any, body_at: int, lengths: tuple[int, ...], index: int) -> Any:
    """A zero-copy view of segment ``index`` inside a received payload.

    The whole return leg's zero-copy claim rests on this function: ``Buffer.slice``
    is a *view* into the payload's allocation, so the arrays an Arrow reader
    builds from the result keep pointing at the bytes the channel delivered
    rather than at a private copy.  :func:`scores_alias_payload` checks exactly
    that, and the suite calls it.

    Offsets are accumulated from the length table rather than indexed, because
    the table is variable-length: segment ``index`` starts after every segment
    before it.
    """
    offset = body_at + sum(lengths[:index])
    return buffer.slice(offset, lengths[index])


def _refusal(leg: str, code: str) -> type[Exception]:
    """The error class a refusal on ``leg`` is raised as.

    One mapping, in one place, so the two legs cannot drift into raising each
    other's type: the inbound leg is a *window* that failed to arrive and the
    outbound leg is a *score vector* that failed to come back, and a caller
    reading a failure wants to know which before it wants the detail.
    """
    return WindowTransferError if leg == TransferLeg.WINDOW else ScoreChannelError


def _read_manifest(buffer: Any, body_at: int, lengths: tuple[int, ...], *, leg: str, code: str):
    """Read a container's manifest (segment 0) without materializing frames.

    Returns the Arrow schema's metadata mapping, or raises the leg's refusal
    when segment 0 is not an readable IPC stream.  Frames are never touched:
    the callers that only need the facts should not pay for the data, which is
    feature 14's own reason for framing a manifest separately — and a caller
    that only needs the facts should also not copy the bytes to read them.
    """
    arrow = _require_arrow()
    segment = _segment_buffer(buffer, body_at, lengths, _MANIFEST_SEGMENT)
    try:
        reader = arrow.ipc.open_stream(arrow.BufferReader(segment))
        return reader.schema.metadata or {}
    except Exception as exc:  # Arrow raises several shapes here
        raise _refusal(leg, code)(
            f"{code}: the {leg} payload's manifest (segment 0) is not a readable Arrow "
            f"IPC stream: {exc}. The manifest is what makes the payload "
            f"self-describing, and a container whose facts cannot be read is "
            f"refused rather than guessed at (feature 166)."
        ) from exc


def _metadata_facts(metadata: Mapping[bytes, bytes]) -> dict[str, Any]:
    """The carried facts a manifest may hold, absent-tolerant.

    Every key is optional and an undecodable one is dropped rather than raised
    on: these are *provenance* — the universe, the decision time, the ABI
    version — and this member reads the window format rather than the contract
    that wrote it.  The one fact this module will not do without is the
    universe on the *score* leg, because the length check is the law; that
    check lives at the call sites that need it, not here.
    """
    facts: dict[str, Any] = {}
    raw_universe = metadata.get(_META_UNIVERSE)
    if raw_universe is not None:
        try:
            decoded = json.loads(raw_universe.decode("utf-8"))
            if isinstance(decoded, list) and all(
                isinstance(symbol, str) for symbol in decoded
            ):
                facts["universe"] = tuple(decoded)
        except (ValueError, UnicodeDecodeError):
            pass
    raw_version = metadata.get(_META_CONTRACT_VERSION)
    if raw_version is not None:
        try:
            facts["contract_version"] = raw_version.decode("utf-8")
        except UnicodeDecodeError:
            pass
    raw_frames = metadata.get(_META_FRAMES)
    if raw_frames is not None:
        try:
            decoded = json.loads(raw_frames.decode("utf-8"))
            if isinstance(decoded, list) and all(
                isinstance(name, str) for name in decoded
            ):
                facts["frame_names"] = tuple(decoded)
        except (ValueError, UnicodeDecodeError):
            pass
    for key, target in ((_META_DECISION_TIME, "decision_time"),
                        (_META_SCORES_FOR, "scores_for")):
        raw = metadata.get(key)
        if raw is not None:
            try:
                facts[target] = raw.decode("utf-8")
            except UnicodeDecodeError:
                pass
    return facts


def inspect_window_payload(data: object) -> WindowFacts:
    """Validate the window leg and read the facts it carries.

    The inbound half of feature 166: *given the bytes that arrived over the
    channel, are they a materialized window, and for which universe?*  The
    container's header is checked with ``struct`` first — magic, framing
    version, a length table that accounts for every byte — and only then is the
    manifest read, so a misrouted or truncated buffer is refused before any
    Arrow reader touches it.

    Deliberately *not* a materialization: the frames stay in the buffer, and a
    caller that wants them hands the same bytes to the contract
    (:meth:`contract.payload.MarketWindowPayload.from_bytes`) — which is where
    frame interpretation belongs.  What this function establishes is what the
    sandbox can honestly establish on its own: that the bytes are a window, and
    what the return leg must be checked against.
    """
    raw = _as_bytes(data, leg=TransferLeg.WINDOW, code=WINDOW_TRANSFER_CODE)
    arrow = _require_arrow()
    buffer = arrow.py_buffer(raw)
    body_at, lengths = _unpack_container(
        raw,
        magic=WINDOW_MAGIC,
        version=WINDOW_VERSION,
        leg=TransferLeg.WINDOW,
        code=WINDOW_TRANSFER_CODE,
    )
    metadata = _read_manifest(
        buffer, body_at, lengths,
        leg=TransferLeg.WINDOW, code=WINDOW_TRANSFER_CODE,
    )
    facts = _metadata_facts(metadata)
    return WindowFacts(
        universe=facts.get("universe", ()),
        contract_version=facts.get("contract_version"),
        decision_time=facts.get("decision_time"),
        frame_names=facts.get("frame_names", ()),
        size=len(raw),
    )


def _as_arrow_column(scores: object, universe_size: int, *, code: str):
    """Normalize a score vector to one Arrow float64 column.

    Accepts what a caller plausibly holds — a :class:`polars.Series` (feature
    11's declared return type), a ``pyarrow`` array, or a plain sequence of
    numbers — and refuses everything else *by name*, because the alternative is
    a container that encodes a string column or a table and looks fine until a
    reader downstream tries to rank it.

    A length that disagrees with the window's universe is refused here rather
    than at the decode: the fastest way to reject a misaligned return is to
    never write it to the channel at all, and the refusal names both lengths.
    """
    arrow = _require_arrow()

    if hasattr(scores, "to_arrow") and not isinstance(scores, (bytes, str)):
        column = scores.to_arrow()
    elif isinstance(scores, (arrow.Array, arrow.ChunkedArray)):
        column = scores
    elif isinstance(scores, Sequence):
        column = arrow.array(list(scores))
    else:
        raise ScoreChannelError(
            f"{code}: a score vector must be a polars.Series, a pyarrow array "
            f"or a sequence of numbers, got {type(scores).__name__}: "
            f"{scores!r}. A signal returns a vector (feature 11), and the "
            f"channel encodes one float column — anything else is a different "
            f"contract travelling in this one's place (feature 166)."
        )

    if isinstance(column, arrow.ChunkedArray):
        if column.num_chunks > 1:
            column = column.combine_chunks()
        elif column.num_chunks == 1:
            column = column.chunk(0)

    if not arrow.types.is_floating(column.type):
        raise ScoreChannelError(
            f"{code}: a score vector must be floating point, got "
            f"{column.type}. Scores are ranked and cross-sectionally z-scored "
            f"downstream (§6.1 steps 3-4), so a non-float column is a type the "
            f"pipeline could not rank without guessing at a coercion — and "
            f"guessing is exactly how a count masquerades as a score "
            f"(feature 166)."
        )

    if len(column) != universe_size:
        raise ScoreChannelError(
            f"{code}: the score vector carries {len(column)} values for a "
            f"window of {universe_size} symbols. The correspondence is "
            f"positional — the *i*-th value is the score for the *i*-th symbol "
            f"of the window's universe (feature 11) — so a length mismatch is "
            f"a misalignment, refused before it is written to the channel "
            f"rather than discovered in the cross-sectional reduction "
            f"(feature 166)."
        )

    # A null anywhere is a score for a symbol that has none, and §6.1's
    # reduction sums across the cross-section: one null swallows the rest, the
    # failure feature 11's validator names for a live return.  Checked on the
    # wire too, because a vector can also acquire a null in transit.
    null_count = column.null_count
    if null_count:
        raise ScoreChannelError(
            f"{code}: the score vector carries {null_count} null value(s) for "
            f"a window of {universe_size} symbols. A null is not a score — it "
            f"is the absence of one — and it would be summed over by the "
            f"cross-sectional reduction downstream (feature 46), poisoning "
            f"every number after it. Return a value for every symbol or fail "
            f"the run (feature 166)."
        )

    from pyarrow import compute

    # Asked as "is *any* value non-finite?" rather than as "are all values
    # finite?", and the difference is not stylistic: ``compute.all`` over an
    # empty array returns null (Arrow's vacuous truth), and ``bool(None)`` is
    # ``False`` — so the all-are-finite spelling refuses a legitimate empty
    # vector, which contract.signal.validate_signal_return admits as the one
    # conforming return for an empty universe.  The any-non-finite spelling
    # agrees with that validator on every non-empty vector and on the empty
    # one, where the other spelling silently disagreed.
    finite = compute.is_finite(column)
    has_nonfinite = bool(finite.null_count) or bool(
        compute.any(compute.invert(finite.fill_null(False))).as_py()
    )
    if has_nonfinite:
        raise ScoreChannelError(
            f"{code}: the score vector carries a non-finite value. NaN and "
            f"infinity are not scores: the cross-sectional reduction sums "
            f"across the cross-section, and one non-finite value swallows "
            f"every other (feature 11's validator makes the same refusal for a "
            f"live return; feature 166 makes it on the wire)."
        )

    return column.cast(arrow.float64(), safe=False)


def encode_scores(
    scores: object,
    *,
    universe: Sequence[str],
    decision_time: str | None = None,
    contract_version: str | None = None,
) -> bytes:
    """Encode a score vector as an Arrow IPC container — the return leg.

    The outbound half of feature 166: the values feature 11 declares a signal
    returns, written as the second thing that crosses the one channel.  The
    container is this module's own (:data:`SCORE_MAGIC`), so it cannot be
    confused with the window that produced it, and its manifest carries the
    facts that make the vector attributable — the universe it scores, the
    decision time and the ABI version it inherited from the window.

    Refuses, before writing anything, a vector that is not a float column of
    the universe's length with every value finite: an unencodable return is a
    fact the producer should hear at the moment it returns, not one the reader
    discovers after the buffer has crossed.

    Deterministic: the same values and facts produce byte-identical output, so
    a replay can compare payloads rather than re-deriving them — the property
    feature 49's materialisation relies on for its own writes.
    """
    arrow = _require_arrow()
    symbols = tuple(universe)
    column = _as_arrow_column(scores, len(symbols), code=SCORE_CHANNEL_CODE)

    metadata = {
        _META_SCORE_VERSION: str(SCORE_VERSION).encode("ascii"),
        _META_UNIVERSE: json.dumps(list(symbols)).encode("utf-8"),
    }
    if contract_version is not None:
        metadata[_META_CONTRACT_VERSION] = str(contract_version).encode("utf-8")
    if decision_time is not None:
        metadata[_META_SCORES_FOR] = str(decision_time).encode("utf-8")

    # Segment 0: the facts, as a zero-column IPC stream.  Zero columns rather
    # than a JSON blob so the whole container stays Arrow — feature 14's reason
    # for framing its manifest the same way, and the reason a reader can learn
    # the vector's facts without decoding the column.
    manifest_schema = arrow.schema([], metadata=metadata)
    manifest_sink = io.BytesIO()
    with arrow.ipc.new_stream(manifest_sink, manifest_schema) as writer:
        writer.write_batch(arrow.record_batch([], schema=manifest_schema))
    manifest = manifest_sink.getvalue()

    # Segment 1: one float64 column, the vector itself.
    data_schema = arrow.schema([arrow.field(SCORE_FRAME_NAME, arrow.float64())],
                               metadata={})
    data_sink = io.BytesIO()
    with arrow.ipc.new_stream(data_sink, data_schema) as writer:
        writer.write_batch(
            arrow.record_batch([column], schema=data_schema)
        )
    data_segment = data_sink.getvalue()

    segments = (manifest, data_segment)
    lengths = b"".join(struct.pack("<Q", len(segment)) for segment in segments)
    header = (
        SCORE_MAGIC
        + struct.pack("<II", SCORE_VERSION, len(segments))
        + lengths
    )
    return header + b"".join(segments)


def decode_scores(data: object, *, expected: WindowFacts | None = None) -> ScoreVector:
    """Decode a score vector off the channel — the return leg, read side.

    Validates the container's header before any Arrow reader sees it, reads the
    manifest's facts, then reads the column **zero-copy**: the segment is
    sliced out of the received buffer and the :class:`polars.Series` built over
    it keeps pointing into that allocation.  :func:`scores_alias_payload`
    asserts that against real buffer addresses; this docstring does not ask to
    be believed.

    ``expected`` is the window the vector should answer for — the object
    :meth:`TransferChannel.send_window` handed back.  When it is given, the
    return is held to it: the universe and length must match, because a score
    vector that crossed the same channel as a window but disagrees with it is
    the one failure this feature exists to catch.  When it is ``None`` the
    vector is validated only against its own manifest — a legitimate read for a
    caller inspecting a stored payload, and no longer the *transfer* this
    feature names.
    """
    arrow = _require_arrow()
    polars = _require_polars()
    raw = _as_bytes(data, leg=TransferLeg.SCORES, code=SCORE_CHANNEL_CODE)
    buffer = arrow.py_buffer(raw)
    body_at, lengths = _unpack_container(
        raw,
        magic=SCORE_MAGIC,
        version=SCORE_VERSION,
        leg=TransferLeg.SCORES,
        code=SCORE_CHANNEL_CODE,
    )
    metadata = _read_manifest(
        buffer, body_at, lengths,
        leg=TransferLeg.SCORES, code=SCORE_CHANNEL_CODE,
    )
    facts = _metadata_facts(metadata)

    if len(lengths) < 2:
        raise ScoreChannelError(
            f"{SCORE_CHANNEL_CODE}: the score payload holds only the manifest "
            f"({len(lengths)} segment(s)); segment 1 is the vector itself, so "
            f"a container without one is a return that carries facts about "
            f"scores that are not there (feature 166)."
        )

    # Sliced, not copied: the arrays the IPC reader builds from this view keep
    # pointing into the buffer the channel delivered, which is what makes the
    # return leg zero-copy.  ``scores_alias_payload`` checks that against the
    # real buffer addresses rather than taking this comment's word for it.
    segment = _segment_buffer(buffer, body_at, lengths, _MANIFEST_SEGMENT + 1)
    try:
        table = arrow.ipc.open_stream(arrow.BufferReader(segment)).read_all()
    except Exception as exc:  # Arrow raises several shapes here
        raise ScoreChannelError(
            f"{SCORE_CHANNEL_CODE}: the score payload's data segment is not a "
            f"readable Arrow IPC stream: {exc}. Refused rather than guessed "
            f"at: a vector whose bytes cannot be read is not a vector "
            f"(feature 166)."
        ) from exc

    if table.num_columns != 1 or table.schema.names[0] != SCORE_FRAME_NAME:
        raise ScoreChannelError(
            f"{SCORE_CHANNEL_CODE}: the score payload's data segment carries "
            f"{table.num_columns} column(s) named {list(table.schema.names)}; "
            f"a score vector is exactly one column named "
            f"{SCORE_FRAME_NAME!r} (feature 11). A wider table is a different "
            f"contract travelling in this one's place (feature 166)."
        )

    column = table.column(0)
    if not arrow.types.is_floating(column.type):
        raise ScoreChannelError(
            f"{SCORE_CHANNEL_CODE}: the score payload's column is "
            f"{column.type}, not floating point; scores are ranked and "
            f"z-scored downstream (§6.1 steps 3-4), and a column this reader "
            f"cannot rank is refused rather than coerced (feature 166)."
        )

    vector_universe = facts.get("universe", ())
    # ``combine_chunks()`` is *not* used here, and the omission is the whole
    # zero-copy claim: it allocates a fresh buffer to glue the chunks together,
    # which would leave the returned series pointing at a private copy rather
    # than at the bytes the channel delivered.  One chunk is the normal case
    # (one writer, one batch), and it is unwrapped to the array — still a view.
    # Only a genuinely multi-chunk payload is combined, because a series must
    # be contiguous; that case pays a copy and ``scores_alias_payload`` will
    # honestly report ``False`` for it.
    if isinstance(column, arrow.ChunkedArray) and column.num_chunks == 1:
        values = column.chunk(0)
    elif isinstance(column, arrow.ChunkedArray):
        values = column.combine_chunks()
    else:
        values = column

    if expected is not None:
        if tuple(vector_universe) != tuple(expected.universe):
            raise ScoreChannelError(
                f"{SCORE_CHANNEL_CODE}: the score vector answers for "
                f"{len(vector_universe)} symbol(s) "
                f"{list(vector_universe)[:8]}, but the window that crossed "
                f"this channel holds {len(expected.universe)} "
                f"{list(expected.universe)[:8]}. A return at the same channel "
                f"that does not answer for the window that went out is a "
                f"misalignment — the vector belongs to another window, or the "
                f"window was rebuilt underneath it — and it is refused before "
                f"it reaches the cross-sectional reduction (feature 166)."
            )
        if len(values) != expected.symbols:
            raise ScoreChannelError(
                f"{SCORE_CHANNEL_CODE}: the score vector carries {len(values)} "
                f"values for the window's {expected.symbols} symbols. The "
                f"correspondence is positional (feature 11), so a length "
                f"mismatch is a misalignment rather than a shape to coerce "
                f"(feature 166)."
            )

    return ScoreVector(
        scores=polars.Series(SCORE_FRAME_NAME, values),
        universe=tuple(vector_universe),
        decision_time=facts.get("scores_for") or facts.get("decision_time"),
        contract_version=facts.get("contract_version"),
        size=len(raw),
    )


def scores_alias_payload(vector: ScoreVector, payload: object) -> bool:
    """Whether a decoded vector's values are views into the payload's buffer.

    The zero-copy claim, checked rather than asserted: this walks the score
    column's data buffers and asks whether each one's address range falls
    inside the buffer the channel delivered.  Feature 14's
    :func:`contract.payload.frames_alias_payload` makes the identical check for
    the window leg, and for the identical reason — *"that claim is cheap to
    assert and expensive to believe"* — so the suite for both features uses the
    same technique.

    A helper rather than a runtime guard: the reader does not consult it on
    every decode, because the property is a fact about the implementation,
    established once by the suite, not a per-call invariant to pay for.
    ``False`` is the safe answer for a payload this cannot address (a
    ``bytes`` copy has no relationship to the vector's buffers, and that is
    exactly what the check should say).
    """
    arrow = _require_arrow()
    try:
        if isinstance(payload, (bytes, bytearray, memoryview)):
            outer = arrow.py_buffer(bytes(payload))
        elif hasattr(payload, "buffer"):
            outer = payload.buffer
        else:
            outer = arrow.py_buffer(payload)
        outer_start = outer.address
        outer_end = outer_start + outer.size
    except (TypeError, ValueError, AttributeError):
        # A payload this cannot address is not one the vector can be a view
        # into.  Named rather than blind because the *answer* here is `False`
        # — a wrong "yes" would make the suite's zero-copy check pass
        # vacuously, which is the one failure this helper must not have.
        return False

    column = vector.scores.to_arrow()
    if isinstance(column, arrow.ChunkedArray):
        columns = list(column.chunks)
    else:
        columns = [column]
    for chunk in columns:
        for buffer in chunk.buffers():
            if buffer is None:
                continue
            if not (outer_start <= buffer.address <= outer_end):
                return False
    return True


class TransferChannel:
    """One channel, two legs — the object feature 166's sentence turns on.

    *"transfers the materialized window as Arrow IPC, which returns the
    resulting score vector over the same channel"*: the window goes out on this
    object and the scores come back on *this* object, and that identity is
    load-bearing rather than incidental.  The channel remembers the window it
    carried — :class:`WindowFacts`, whose universe is what the return is
    validated against — so "the same channel" is what makes a misaligned return
    *detectable*: a vector that crossed a different channel, or crossed this
    one after the window had been replaced, has nothing to be checked against.

    Single-shot per direction, mirroring :class:`contract.payload.PayloadChannel`
    and for the same reason: a channel that accepted a second window would need
    a rule for whether the second replaced the first, and any such rule is a way
    for a run to be evaluated against a window other than the one it was
    dispatched with.

    Deliberately *not* a transport.  There is no path, no fd and no handle here
    — just the bytes and the facts about them — which is precisely why the box
    can be run with no filesystem mounts at all (§5.2's control table).  A real
    deployment backs this with a pipe or a socket; the contract it must satisfy
    is the one pinned here.
    """

    __slots__ = ("_facts", "_scores", "_window")

    def __init__(self) -> None:
        self._window: bytes | None = None
        self._scores: bytes | None = None
        self._facts: WindowFacts | None = None

    # -- host side --------------------------------------------------------

    def send_window(self, window: object) -> WindowFacts:
        """Put a materialized window on the channel.  The host's write.

        ``window`` is a :class:`contract.window.MarketWindow` — duck-typed by
        its ``to_arrow()`` (feature 14's serialization) so this module needs no
        dependency on the contract to carry what it produces — or the already
        serialized bytes, for a host that serialized earlier and does not want
        to pay for it twice.

        Returns the :class:`WindowFacts` the payload declared, which is the
        object the return leg is validated against.  Refuses a window with no
        frames: feature 14 refuses to serialize one, and the refusal surfaces
        here translated into this member's vocabulary rather than as the
        contract's exception type.
        """
        if self._window is not None:
            raise WindowTransferError(
                f"{WINDOW_TRANSFER_CODE}: this channel already carries a window; a sandbox run is "
                f"evaluated against exactly one materialized window, and a "
                f"second send has no defensible meaning — replacing the first "
                f"would let a run be scored against a window other than the "
                f"one it was dispatched with (feature 166)."
            )

        if isinstance(window, (bytes, bytearray, memoryview)):
            raw = bytes(window)
        elif hasattr(window, "to_arrow"):
            try:
                payload = window.to_arrow()
            except Exception as exc:  # feature 14 refuses several ways
                raise WindowTransferError(
                    f"{WINDOW_TRANSFER_CODE}: the window could not be serialized for the transfer: "
                    f"{exc}. The box holds no filesystem mounts, so a window "
                    f"that cannot be sent is a window that cannot be evaluated "
                    f"at all — materialize its frames before dispatching the "
                    f"run (feature 166, feature 14's own refusal translated "
                    f"here so this member's caller never meets the contract's "
                    f"exception type)."
                ) from exc
            raw = bytes(payload)
        else:
            raise WindowTransferError(
                f"{WINDOW_TRANSFER_CODE}: the window leg of the sandbox payload channel carries a "
                f"materialized MarketWindow (or its serialized bytes), got "
                f"{type(window).__name__}. The feature's sentence transfers "
                f"*the materialized window*: a window with no frames has "
                f"nothing to send, and the failure it would cause surfaces "
                f"three systems downstream as an unexplainable zero signal "
                f"(feature 166)."
            )

        facts = inspect_window_payload(raw)
        self._window = raw
        self._facts = facts
        return facts

    def receive_scores(self, *, expected: WindowFacts | None = None) -> ScoreVector:
        """Take the score vector back off the channel.  The host's read.

        Validated against the window this channel carried unless ``expected``
        overrides it — which is the transfer's whole guarantee: the vector that
        comes back is a vector *for the window that went out*, positionally
        aligned with its universe, or the caller gets a refusal naming both
        lengths instead of a plausible-looking series.
        """
        if self._scores is None:
            raise ScoreChannelError(
                f"{SCORE_CHANNEL_CODE}: no score vector arrived over this "
                f"channel. The window crossed it, so the run returned nothing "
                f"— an exception inside the box, a killed process, a producer "
                f"that never answered — and a caller that carried on would be "
                f"normalizing the absence of a result. 'No return' is not 'a "
                f"return of zeros' (feature 166)."
            )
        baseline = expected if expected is not None else self._facts
        return decode_scores(self._scores, expected=baseline)

    # -- box side ---------------------------------------------------------

    def receive_window(self) -> WindowFacts:
        """Take the window off the channel, validated.  The box's read.

        Returns the facts the payload declared rather than the bytes: a
        consumer inside the box materializes through the contract, which owns
        frame interpretation, and handing it facts it can size itself against
        first is what keeps this member from re-implementing feature 14.  Use
        :attr:`window_bytes` for the payload itself.
        """
        if self._window is None:
            raise WindowTransferError(
                f"{WINDOW_TRANSFER_CODE}: no window arrived over this channel; the sandbox holds no "
                f"filesystem mounts, so a run without a payload has no window "
                f"to evaluate against — and an empty window is not the same "
                f"thing as no window (feature 166)."
            )
        return self._facts if self._facts is not None else inspect_window_payload(
            self._window
        )

    def return_scores(self, scores: object) -> bytes:
        """Put the score vector back on the channel.  The box's write.

        Encoded against the universe *this channel carried*, so the return is
        aligned with the window that went out before it is ever written — the
        earliest possible point to catch a misalignment.  Returns the bytes so
        a caller can observe the size it sent without a second encoding.
        """
        if self._window is None:
            raise ScoreChannelError(
                f"{SCORE_CHANNEL_CODE}: this channel never carried a window, "
                f"so there is no universe to return a score vector for. The "
                f"return leg is defined against the window it answers for "
                f"(feature 166); a vector produced before one arrived belongs "
                f"to some other run."
            )
        if self._scores is not None:
            raise ScoreChannelError(
                f"{SCORE_CHANNEL_CODE}: this channel already carries a score "
                f"vector. One run returns one vector over one channel; a "
                f"second return has no defensible meaning and would let a "
                f"reader pick up a vector the run did not produce (feature "
                f"166)."
            )
        facts = self._facts if self._facts is not None else inspect_window_payload(
            self._window
        )
        raw = encode_scores(
            scores,
            universe=facts.universe,
            decision_time=facts.decision_time,
            contract_version=facts.contract_version,
        )
        self._scores = raw
        return raw

    # -- inspection -------------------------------------------------------

    @property
    def window_bytes(self) -> bytes | None:
        """The serialized window on the channel, or ``None`` if none was sent.

        The payload itself, for a consumer that must materialize it: this
        member validates the window's framing and reads its facts, and the
        contract interprets its frames.  Reading it does not spend the channel —
        the one-shot rule is about *sending*, and a reader that could not look
        at what it received would be a poor seam.
        """
        return self._window

    @property
    def facts(self) -> WindowFacts | None:
        """What the channel knows about the window it carried, if any."""
        return self._facts

    @property
    def empty(self) -> bool:
        """True when no window has been sent. Never a substitute for receive."""
        return self._window is None

    @property
    def returned(self) -> bool:
        """True when a score vector has been written back."""
        return self._scores is not None

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        window = "empty" if self._window is None else f"{len(self._window)} bytes"
        scores = "none" if self._scores is None else f"{len(self._scores)} bytes"
        return f"TransferChannel(window={window}, scores={scores})"


class SandboxTransfer:
    """Feature 166's law, as the value a composed application carries.

    A stateless facade over this module and the channel it provides — the same
    shape :class:`sandbox.SandboxIsolation` gives feature 157 and
    :class:`sandbox.SandboxImports` gives feature 167 — so a caller holding the
    composed component can run the feature's own sentence without importing the
    member's submodules by name.  It carries nothing at all: no channel, no
    buffer, no handle, because the feature is a *transfer* and a transfer is a
    thing that happens, not a thing that is held.  A channel belongs to one
    run, and a component shared across runs that held one would be a component
    letting two runs share a window.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the framing or the alignment
    check here would be a second thing to keep in sync with the container, and
    the member's one-provenance rule exists so that cannot happen.  What the
    class adds is discoverability (the factory's scan composes it) and one
    duck-checkable seam for the category's remaining features.

    **What it does not do: execute anything.**  :meth:`round_trip` takes the
    producer as a *callable* so the box's execution stays where §6.1 step 2
    puts it (the evaluator's runner, ``evaluator._sandbox``) and this member
    never grows a runner.  The division is the honest one: that module owns
    *running untrusted code under limits*, this one owns *what crosses the
    channel into and out of it*.
    """

    __slots__ = ()

    def channel(self) -> TransferChannel:
        """A fresh channel for one run — the seam, made explicit.

        Returned rather than held, so two runs cannot share one: the caller
        that dispatches a run owns the channel for its lifetime, which is the
        only way "the same channel" means anything.
        """
        return TransferChannel()

    def send(self, window: object, *, channel: TransferChannel | None = None) -> WindowFacts:
        """Send a materialized window, returning the facts it declared.

        No channel given means a fresh one, which is right for a caller that
        only wants the window validated and serialized; a caller that intends
        to read the scores back must pass the channel it will read from, and
        :meth:`round_trip` is the spelling for that case.
        """
        target = channel if channel is not None else TransferChannel()
        return target.send_window(window)

    def receive(
        self,
        *,
        channel: TransferChannel,
        expected: WindowFacts | None = None,
    ) -> ScoreVector:
        """Take the score vector off ``channel``, validated against its window."""
        return channel.receive_scores(expected=expected)

    def scores(
        self,
        scores: object,
        *,
        channel: TransferChannel,
    ) -> bytes:
        """Return a score vector over ``channel`` — the box's write."""
        return channel.return_scores(scores)

    def round_trip(
        self,
        window: object,
        produce: Callable[[WindowFacts], object],
        *,
        channel: TransferChannel | None = None,
    ) -> ScoreVector:
        """The feature's sentence, executed end to end.

        Sends the materialized window as Arrow IPC, hands the facts to
        ``produce`` — the caller's producer, which is where the box's own
        execution belongs — and takes the score vector the producer returned
        back over *the same channel*, validated positionally against the
        window's universe.  Returns the :class:`ScoreVector`.

        ``produce`` receiving :class:`WindowFacts` rather than bytes is
        deliberate: it says what the producer is entitled to know before it
        runs (which universe, at which decision time), and it keeps the
        materialization in the contract's hands.  A producer that returns
        ``None`` — a failed run, a killed child, a signal with nothing to say —
        is refused by name rather than encoded as an empty vector, because the
        failure mode this feature exists to prevent is an absence that reads as
        a result.
        """
        target = channel if channel is not None else TransferChannel()
        facts = target.send_window(window)
        produced = produce(facts)
        if produced is None:
            raise ScoreChannelError(
                f"{SCORE_CHANNEL_CODE}: the sandboxed run produced no score "
                f"vector for the window it was sent (universe of "
                f"{facts.symbols} symbol(s), decision time "
                f"{facts.decision_time}). A run that returns nothing — a "
                f"raised signal, a timeout, a killed child — is a recorded "
                f"outcome the pipeline persists, not an empty vector it "
                f"normalizes: feature 11's contract has no spelling for 'no "
                f"score', so the transfer refuses rather than inventing one "
                f"(feature 166)."
            )
        target.return_scores(produced)
        return target.receive_scores()


def sandbox_transfer() -> SandboxTransfer:
    """The transfer law, for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs a window and a
    channel to transfer across.  This is the module-level convenience the
    member's own tests and any operator script reach, and it is the same call
    the builder below makes minus the composition.
    """
    return SandboxTransfer()
