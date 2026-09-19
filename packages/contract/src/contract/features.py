"""Feature 9's version-exact addressing: which frame holds a feature's rows.

app_spec.xml, "Signal Contract & Market Window", feature 9: *System exposes
MarketWindow.feature taking a name plus an explicit version, which returns
rows for that exact version only.*  docs/nullius-tech-architecture.md §5.1
declares the accessor alongside the rest of the window's surface::

    def feature(self, name: str, version: str, lookback: int) -> pl.DataFrame: ...

and §4.4 fixes what the version *is* — a component of a stored feature's
identity — "A changed definition gets a new ``feature_version``; it never
overwrites."  So two versions of one feature are two different stored things,
and the whole content of feature 9 is that the accessor must return the one
that was asked for and never the other.

**Why the version is part of the frame's *name*, not a column in it.**  A
window carries its data as a mapping of frame name to Arrow table
(:attr:`contract.window.MarketWindow.frames`), and that mapping is what
feature 14 serializes to the sandbox over the payload channel.  Putting the
version in the frame name means version identity travels with the payload for
free: the payload manifest records frame names, so a window that crossed the
channel as bytes still answers ``feature("vol", "2")`` with version 2's rows
and cannot confuse them with version 1's.  A version carried as a *column*
would make identity a row-level fact a caller could forget to filter on — and
"forgot to filter on the version column" is exactly the bug feature 9 exists
to make impossible.

**The name is a total, collision-free encoding.**  A frame name is
``feature:<name>:<version>``, and both components are refused a ``:`` at
validation time.  That refusal is load-bearing rather than tidy: without it
``("a:1", "2")`` and ``("a", "1:2")`` would both spell ``feature:a:1:2`` —
two distinct feature versions addressing one frame, which is the silent
mixing of versions feature 9 forbids, arriving through the encoding rather
than through the lookup.  With the separator forbidden inside both
components, the frame name splits into exactly three parts and
:func:`parse_feature_frame_name` is its unambiguous inverse.

**A miss is an empty answer, never another version's rows.**  The lookup is
exact: :func:`select_feature_frame` matches one frame name and returns
``None`` for anything else.  There is no "latest version" resolution, no
prefix match (so ``"1"`` never picks up ``"10"``), and no fallback to the
newest frame that happens to be present.  A caller that asked for a version
the window does not carry gets nothing — which is honest, and is the *safe*
direction to fail: an empty frame cannot leak a future computation, whereas
a substituted one would silently attribute version 2's numbers to version 1.
That is the same stance the read paths of this system take elsewhere (a
missing partition is an empty result, not an error:
:meth:`snapshot.SnapshotMount.partitions`; a miss is ``None``:
:meth:`feature_store.store.FeatureStore.get`).

**Stdlib-only, and polars deferred.**  This module holds no third-party
import at module scope: the naming, the validation and the exact-match
lookup are pure functions over a plain mapping, so the version-discipline
core is testable and import-safe in every environment the workspace contract
promises one will be — the factory scan, the test sandbox, the deterministic
replay path.  Polars is reached for only by :func:`require_polars`, on the
same seam :func:`contract._arrow.require_arrow` and
:func:`contract.signal._require_signal_module` already use, and it is reached
exactly once per accessor call (:meth:`contract.window.MarketWindow.feature`,
which is where the Arrow table is handed back as the ``pl.DataFrame`` §5.1
declares).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Tuple

__all__ = [
    "FEATURE_FRAME_PREFIX",
    "FeatureAccessError",
    "feature_frame_name",
    "feature_frame_names",
    "parse_feature_frame_name",
    "require_polars",
    "select_feature_frame",
    "validate_lookback",
]

#: The prefix that marks a frame as a feature's rows, so a window's other
#: frames (``bars``, ``trades``, whatever a later feature materializes) are
#: never mistaken for one of feature 9's.
FEATURE_FRAME_PREFIX = "feature"

#: The component separator.  Forbidden *inside* a name or a version — see the
#: module docstring: allowing it is what would let two distinct
#: ``(name, version)`` pairs spell one frame name.
_SEPARATOR = ":"

#: Characters refused in a name or a version.  The separator (for the
#: collision argument above), the path separators and NUL for the same reason
#: :mod:`feature_store.keys` refuses them in a key component — a frame name
#: travels into a payload manifest and, on the materialisation side, toward a
#: filesystem, so a component that could escape its segment is not a name a
#: caller may choose.
_FORBIDDEN_CHARS = frozenset(_SEPARATOR + "/\\\0")


class FeatureAccessError(ValueError):
    """A ``MarketWindow.feature`` request was malformed.

    Subclasses :class:`ValueError` because a malformed name, version or
    lookback is a caller bug at the accessor — not a runtime condition to
    retry, and not the "this version is not in this window" state, which is
    answered with an empty frame rather than an exception.  The two are kept
    firmly apart: an exception means *the question was invalid*, an empty
    frame means *the window does not carry that version*.
    """


def _validated_component(field: str, value: object) -> str:
    """Validate one free-form component of a feature frame name.

    Mirrors the component discipline :mod:`feature_store.keys` applies to the
    identity of a stored feature (non-empty, unpadded, path-safe) without
    importing it: ``contract`` is Z0, the boundary everything else sits
    behind, and depending on a consumer of the contract would invert the
    stack.  The one rule this module adds is the separator refusal, which is
    what makes the encoding collision-free.
    """
    if not isinstance(value, str):
        raise FeatureAccessError(
            f"feature {field} must be a string; got {type(value).__name__}"
        )
    if not value or value != value.strip():
        raise FeatureAccessError(
            f"feature {field} must be non-empty and unpadded; got {value!r}"
        )
    for char in value:
        if char in _FORBIDDEN_CHARS or ord(char) < 32 or ord(char) == 127:
            raise FeatureAccessError(
                f"feature {field} must not contain {_SEPARATOR!r} or path "
                f"separators or control characters; got {value!r} — "
                f"{_SEPARATOR!r} is the frame-name separator, and a "
                "component containing it could address another version's rows"
            )
    return value


def feature_frame_name(name: str, version: str) -> str:
    """The frame name under which ``(name, version)``'s rows are carried.

    ``feature:<name>:<version>`` — one total, injective encoding of a feature
    identity into the flat frame names a window's ``frames`` mapping (and,
    through feature 14, an Arrow payload manifest) can hold.  Validation
    happens here, so every path that needs a frame name — the accessor, the
    host that materializes a window, a test — refuses a malformed component
    identically, and the *spelling* of the identity has exactly one
    definition for both sides of the join to share.  That is the point of
    exporting it: a host building a window and an accessor reading one cannot
    drift apart over where the version goes.
    """
    return _SEPARATOR.join(
        (
            FEATURE_FRAME_PREFIX,
            _validated_component("name", name),
            _validated_component("version", version),
        )
    )


def parse_feature_frame_name(frame_name: object) -> Optional[Tuple[str, str]]:
    """The ``(name, version)`` a feature frame name carries, else ``None``.

    The inverse of :func:`feature_frame_name`, and total over *any* value: a
    frame name that is not a feature frame — ``"bars"``, ``"scores"``, a bare
    ``object()``, a non-string key a caller smuggled into a frames mapping —
    is reported as ``None`` rather than raising.  Enumeration is how a caller
    asks *which features does this window carry?*, and that question must be
    answerable over a mapping that holds other frames too.

    Unambiguous by construction: the two components cannot contain the
    separator, so a feature frame name has exactly three parts.  A name
    shaped like a feature frame but with a different part count (a producer
    that wrote ``feature:vol``, or hand-built a four-part name) is refused as
    a non-feature frame rather than guessed at.
    """
    if not isinstance(frame_name, str):
        return None
    parts = frame_name.split(_SEPARATOR)
    if len(parts) != 3 or parts[0] != FEATURE_FRAME_PREFIX:
        return None
    name, version = parts[1], parts[2]
    if not name or not version:
        return None
    return name, version


def feature_frame_names(
    frames: Mapping[Any, Any]
) -> Tuple[Tuple[str, str], ...]:
    """The ``(name, version)`` pairs a window's frames carry, sorted.

    The discoverable half of feature 9's contract: the version discipline is
    enforced by :func:`select_feature_frame`, but a caller handed an empty
    frame because it asked for a version the window does not carry needs a
    way to learn which versions *are* there — otherwise "not in this window"
    and "no data yet" are indistinguishable and the caller cannot tell a typo
    from a gap.  Sorted, so the enumeration is deterministic and
    bit-reproducible, the same traversal discipline feature 46 applies to
    symbols and :meth:`feature_store.store.FeatureStore.keys` applies to
    stored keys.
    """
    return tuple(
        sorted(
            pair
            for pair in (parse_feature_frame_name(key) for key in frames)
            if pair is not None
        )
    )


def select_feature_frame(
    frames: Mapping[Any, Any], name: str, version: str
) -> Any:
    """The frame holding ``(name, version)``'s rows, or ``None`` if absent.

    Feature 9's lookup, and the whole of its guarantee: the frame name is
    derived from both components and looked up *exactly*.  Nothing here
    searches, prefixes, falls back or prefers — a window carrying version 2
    of a feature answers a question about version 1 with ``None``, never with
    version 2's rows.

    Both components are validated (through :func:`feature_frame_name`) before
    the mapping is touched, so a malformed request is reported as such even
    against a window that carries nothing at all, rather than reading as "no
    rows for that version".
    """
    return frames.get(feature_frame_name(name, version))


def validate_lookback(lookback: object) -> Optional[int]:
    """Validate a feature accessor's ``lookback``, else raise.

    ``None`` means "every row the window carries" — the state a window is in
    when the host materialized the whole feature frame.  A non-negative
    ``int`` means "the trailing ``lookback`` rows" (see
    :meth:`contract.window.MarketWindow.feature` for why trailing is the
    recent end).  A ``bool`` is refused even though Python would accept it as
    an ``int``: ``lookback=True`` is a plausible typo that would silently mean
    "the last one row", and a wrong answer that looks like a right one is the
    failure mode this whole module is built against.  A negative count is
    refused for the same reason rather than clamped.
    """
    if lookback is None:
        return None
    if isinstance(lookback, bool) or not isinstance(lookback, int):
        raise FeatureAccessError(
            f"lookback must be a non-negative int or None; got "
            f"{type(lookback).__name__}"
        )
    if lookback < 0:
        raise FeatureAccessError(
            f"lookback must be non-negative; got {lookback}"
        )
    return lookback


def require_polars():
    """Import and return polars, or raise a named, actionable error.

    Imported lazily on every call rather than cached in a module global, on
    the same grounds :func:`contract._arrow.require_arrow` states: the cost
    after the first import is a ``sys.modules`` lookup, and a cache would be a
    lie in the one environment where this matters — a test that installs,
    removes or monkeypatches polars mid-process.

    The failure is named rather than left as a bare ``ModuleNotFoundError``
    because §5.1's accessor return type is the reason the dependency is
    declared at all: a caller who reaches this without polars installed needs
    to be told that the *accessor's return type* needs it, not that some
    import three frames down failed.
    """
    try:
        import polars as pl
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModuleNotFoundError(
            "MarketWindow accessors return a polars DataFrame "
            "(docs/nullius-tech-architecture.md §5.1), and polars is a "
            "declared dependency of the nullius-contract member but is not "
            "installed in this environment; run `uv sync` (or `pip install "
            "polars`) in the workspace root"
        ) from exc
    return pl
