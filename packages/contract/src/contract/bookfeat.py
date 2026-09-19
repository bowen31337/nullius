"""Feature 7's name-addressed frames: the derived order-book features.

app_spec.xml, "Signal Contract & Market Window", feature 7: *System exposes
MarketWindow.bookfeat by feature name, which returns derived order-book
features at 1 second resolution.*  docs/nullius-tech-architecture.md §5.1
declares the accessor alongside the rest of the window's surface::

    def bookfeat(self, name: str, lookback: int) -> pl.DataFrame: ...

and §4.1 fixes where the rows come from — the *derived tier* of the L2
retention decision: raw diffs are kept for a rolling 90 days *"so feature
definitions can be revised and backfilled recently, and permanently persist
derived book features at 1s resolution."*  The families that tier holds are
named right there in §4.1 — depth at 5/10/25/50 bps each side, microprice,
spread, OFI over several windows, cancel/replace rate, trade-size
distribution moments — and the sealed snapshot carries them under its
``bookfeat/`` partitions (§4.2), which is what a host materializes into a
window's frames.

Three decisions shape this module, and each is load-bearing:

* **The name is free-form, not a closed vocabulary.**  The derived tier is
  the part of §4.1 that grew: feature 20 persisted the depth ladder,
  feature 21 added microprice/spread/OFI, feature 22 added cancel-replace
  and trade-size moments — each a new name the tier had not carried the day
  before.  A contract that enumerated the names could only ever be wrong by
  one feature, and a refused name is a *refusal of the spec's own future*,
  so the accessor validates the component (non-empty, unpadded,
  separator- and path-free — the same discipline
  :func:`contract.features.feature_frame_name` applies) and leaves what the
  tier holds to the window.  :func:`bookfeat_frame_names` over
  :attr:`contract.window.MarketWindow.frames` is the discoverable half: a
  caller can ask which features this window carries before asking for one.

* **Addressed by name alone, not by version.**  Feature 9's frames carry a
  version component because §4.4 makes ``feature_version`` part of a stored
  feature's identity — "a changed definition gets a new ``feature_version``;
  it never overwrites" — for the Z0 feature store's *base* features.  The
  derived book tier is a different thing: a §4.1 *stream*, persisted by the
  ingest workers as an append-only log keyed by sequence, whose revision
  story is the raw window itself (a revised definition backfills from the
  90 days of raw diffs and accumulates forward, which §4.1 states as an
  honest constraint rather than a version coordinate).  The accessor §5.1
  declares for it takes a name and a lookback, and no version — so the
  frame name is ``bookfeat:<name>``, and the namespaces cannot collide:
  a feature frame always spells ``feature:<name>:<version>`` (three parts),
  a bookfeat frame always spells two, and a frame literally named
  ``feature:depth:1`` is feature 9's address for a *base* feature called
  "depth", which this accessor never reads (and ``feature`` never returns
  the derived tier's rows).

* **The promise is about rows, so it is checked.**  Feature 7 does not say
  "returns a frame"; it says "returns derived order-book features at 1
  second resolution", and the resolution is a promise about *rows* — every
  derived row, in every family the tier holds, is one symbol's features for
  one closed 1 second window, stamped with the window it belongs to.  The
  three streams the ingest tier persists share exactly two columns:
  ``symbol`` and ``window_start``.  :func:`check_bookfeat_frame` refuses a
  present frame missing either — a loud, named failure at the accessor
  rather than a ``ColumnNotFoundError`` three frames inside the signal —
  and checks nothing else, because each family's value columns are the
  family's own (the ladder's depth bands, the microstructure row's
  microprice and spread, the flow row's rates and moments) and the contract
  has no reason to forbid what it cannot promise.  Column *types* are the
  host's, on the same terms as :mod:`contract.borrow`: the derived tier
  persists canonical fixed-point strings, and this accessor returns
  whatever it was handed rather than re-rendering it.

**A miss is an empty frame, never a substitute.**  A window that carries no
frame under the name — the host materialized nothing for that family, or
the stream had not produced a row for it by ``t`` — answers with an empty
``DataFrame``, on the same stance features 8 and 9 take: an empty answer
cannot leak a wrong number, whereas a "helpful" fallback (another family's
rows, the nearest name) silently would.  It is the same posture the read
paths take elsewhere (a missing partition is an empty result, not an
error; a store miss is ``None``).

**Stdlib-only, and polars deferred.**  Like :mod:`contract.features` and
:mod:`contract.borrow`, this module holds no third-party import at module
scope: the frame-name constant, the component validation, the exact-match
lookup and the row-shape check are pure, so they are import-safe in every
environment the workspace contract promises one will be — the factory
scan, the test sandbox, the deterministic replay path.  Polars is reached
for exactly once per accessor call, on the same
:func:`contract.features.require_polars` seam every accessor uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, List, Optional, Tuple

from .features import FeatureAccessError, validate_lookback

__all__ = [
    "BOOKFEAT_FRAME_PREFIX",
    "BOOKFEAT_REQUIRED_COLUMNS",
    "BookfeatAccessError",
    "bookfeat_frame_name",
    "bookfeat_frame_names",
    "check_bookfeat_frame",
    "parse_bookfeat_frame_name",
    "select_bookfeat_frame",
    "validate_bookfeat_lookback",
]

#: The prefix that marks a frame as a derived book feature's rows, so a
#: window's other frames — feature 9's ``feature:`` namespace, feature 8's
#: observed borrow stream, whatever a later feature materializes — are never
#: mistaken for one of feature 7's.
BOOKFEAT_FRAME_PREFIX = "bookfeat"

#: The columns a bookfeat frame must carry for the accessor to keep feature
#: 7's promise.  Deliberately exactly two — which symbol, which 1 second
#: window — because those are the two columns every family in the derived
#: tier shares (the depth ladder, the microstructure row, the trade-flow row
#: all carry them); each family's value columns are the family's own and
#: pass through untouched.  A tuple, in the order a refusal message should
#: name them.
BOOKFEAT_REQUIRED_COLUMNS = ("symbol", "window_start")

#: The component separator.  Forbidden *inside* a feature name — see the
#: module docstring: with the separator allowed, ``bookfeat:a:1`` would be a
#: name that :func:`parse_bookfeat_frame_name` cannot read back, breaking
#: the round trip the enumeration is.  The same set :mod:`contract.features`
#: refuses, for the same reason: a frame name travels into a payload
#: manifest and, on the materialisation side, toward a filesystem (§4.2's
#: ``bookfeat/`` partitions), so a component that could escape its segment
#: is not a name a caller may choose.
_SEPARATOR = ":"
_FORBIDDEN_CHARS = frozenset(_SEPARATOR + "/\\\0")


class BookfeatAccessError(ValueError):
    """A ``MarketWindow.bookfeat`` request could not be honoured.

    Two causes, both refusing loudly rather than approximating:

    * a malformed ``name`` or ``lookback`` — the *request* was invalid, a
      caller bug at the accessor (the same fact
      :class:`~contract.features.FeatureAccessError` states for
      ``feature``);
    * a window whose bookfeat frame is present but does not carry
      :data:`BOOKFEAT_REQUIRED_COLUMNS` — a *host* bug, a frame materialized
      under a derived feature's name that is not 1 second resolution rows.

    Both subclass :class:`ValueError` because neither is a runtime condition
    to retry, and neither is the "this window carries no such feature"
    state, which is answered with an empty frame rather than an exception.
    The three are kept firmly apart: an exception means the question or the
    frame was invalid; an empty frame means the window carries that
    feature's rows not at all.
    """


def _validated_name(name: object) -> str:
    """Validate one derived book feature name, else raise.

    Mirrors the component discipline :mod:`contract.features` applies to a
    feature frame's components (non-empty, unpadded, path-safe) without
    importing its private helpers: the rule is stated here a second time so
    this module's refusals carry this module's name, and a stack trace out
    of ``ctx.bookfeat(...)`` points the reader at the bookfeat contract
    rather than at feature 9's.
    """
    if not isinstance(name, str):
        raise BookfeatAccessError(
            f"bookfeat name must be a string; got {type(name).__name__}"
        )
    if not name or name != name.strip():
        raise BookfeatAccessError(
            f"bookfeat name must be non-empty and unpadded; got {name!r}"
        )
    for char in name:
        if char in _FORBIDDEN_CHARS or ord(char) < 32 or ord(char) == 127:
            raise BookfeatAccessError(
                f"bookfeat name must not contain {_SEPARATOR!r} or path "
                f"separators or control characters; got {name!r} — "
                f"{_SEPARATOR!r} is the frame-name separator, and a name "
                "containing it could not be read back as one component"
            )
    return name


def bookfeat_frame_name(name: str) -> str:
    """The frame name under which a derived book feature's rows are carried.

    ``bookfeat:<name>`` — one total, injective encoding of a derived
    feature's identity into the flat frame names a window's ``frames``
    mapping (and, through feature 14, an Arrow payload manifest) can hold.
    Validation happens here, so every path that needs a frame name — the
    accessor, the host that materializes a window, a test — refuses a
    malformed component identically, and the *spelling* of the address has
    exactly one definition for both sides of the join to share.  That is the
    point of exporting it: a host building a window and an accessor reading
    one cannot drift apart over where the name goes.
    """
    return _SEPARATOR.join((BOOKFEAT_FRAME_PREFIX, _validated_name(name)))


def parse_bookfeat_frame_name(frame_name: object) -> Optional[str]:
    """The feature name a bookfeat frame name carries, else ``None``.

    The inverse of :func:`bookfeat_frame_name`, and total over *any* value:
    a frame name that is not a bookfeat frame — ``"bars"``, the observed
    ``"borrow"`` stream, feature 9's three-part ``feature:vol:1``, a bare
    ``object()`` — is reported as ``None`` rather than raising.  Enumeration
    is how a caller asks *which derived features does this window carry?*,
    and that question must be answerable over a mapping that holds other
    frames too.

    Unambiguous by construction: the name cannot contain the separator, so
    a bookfeat frame name has exactly two parts.  A name shaped like a
    bookfeat frame but with a different part count (a producer that wrote
    ``bookfeat:depth:1``, or a bare ``bookfeat:``) is refused as a
    non-bookfeat frame rather than guessed at.
    """
    if not isinstance(frame_name, str):
        return None
    parts = frame_name.split(_SEPARATOR)
    if len(parts) != 2 or parts[0] != BOOKFEAT_FRAME_PREFIX:
        return None
    name = parts[1]
    if not name:
        return None
    return name


def bookfeat_frame_names(frames: Mapping[Any, Any]) -> Tuple[str, ...]:
    """The derived feature names a window's frames carry, sorted.

    The discoverable half of feature 7's contract: the name discipline is
    enforced by :func:`select_bookfeat_frame`, but a caller handed an empty
    frame because it asked for a feature the window does not carry needs a
    way to learn which features *are* there — otherwise "not in this
    window" and "no data yet" are indistinguishable and the caller cannot
    tell a typo from a gap.  Sorted, so the enumeration is deterministic
    and bit-reproducible, the same traversal discipline
    :func:`contract.features.feature_frame_names` applies to versioned
    features.
    """
    return tuple(
        sorted(
            name
            for name in (
                parse_bookfeat_frame_name(key) for key in frames
            )
            if name is not None
        )
    )


def select_bookfeat_frame(
    frames: Mapping[Any, Any], name: str
) -> Any:
    """The frame holding the named derived feature's rows, or ``None``.

    Feature 7's lookup, and the whole of its guarantee: the frame name is
    derived from the name and looked up *exactly*.  Nothing here searches,
    prefixes, falls back or prefers — a window carrying "microprice" answers
    a question about "micro_price" with ``None``, never with the nearest
    name's rows.

    The name is validated (through :func:`bookfeat_frame_name`) before the
    mapping is touched, so a malformed request is reported as such even
    against a window that carries nothing at all, rather than reading as
    "no rows for that feature".
    """
    return frames.get(bookfeat_frame_name(name))


def validate_bookfeat_lookback(lookback: object) -> Optional[int]:
    """Validate a ``bookfeat`` accessor's ``lookback``, else raise.

    The rule itself is feature 9's (:func:`contract.features.validate_lookback`):
    one lookback discipline across every accessor, so ``bookfeat`` cannot
    drift from ``feature`` and ``borrow`` over what a lookback *means* —
    ``None`` is every row the window carries, a non-negative ``int`` is the
    trailing rows, a ``bool`` and a negative count are refused rather than
    clamped.  Only the error's *name* is this module's: a stack trace out
    of ``ctx.bookfeat(...)`` must not point the reader at
    ``contract.features`` for a rule about a different accessor, so the
    shared validation's refusal is re-raised as
    :class:`BookfeatAccessError` with its message carried over unchanged.
    """
    try:
        return validate_lookback(lookback)
    except FeatureAccessError as exc:
        raise BookfeatAccessError(str(exc)) from exc


def _column_names(frame: Any) -> List[str]:
    # The names of a frame's columns, from either spelling the ecosystem uses:
    # Arrow's ``column_names`` (Table, RecordBatch, Schema) and polars'
    # ``columns``.  A window stores Arrow — frames are coerced at construction
    # (contract.window._as_frames) — but a host may want to check the frame it
    # is *about* to materialize while still holding it as a polars DataFrame,
    # and refusing that would be checking the representation rather than the
    # row shape the check exists for.
    for attribute in ("column_names", "columns"):
        names = getattr(frame, attribute, None)
        if names is not None:
            return list(names)
    raise BookfeatAccessError(
        f"the bookfeat frame is a {type(frame).__name__}, which carries no "
        "column names; a bookfeat frame is the Arrow table a window stores — "
        "one row per symbol per closed 1 second window, carrying at least "
        f"{', '.join(BOOKFEAT_REQUIRED_COLUMNS)}"
    )


def check_bookfeat_frame(frame: Any) -> None:
    """Refuse a frame that is not ``bookfeat``'s rows; return quietly if it is.

    The row-shape half of feature 7: the accessor promises *derived
    order-book features at 1 second resolution*, and this is the check that
    keeps the promise checkable rather than documented.  A frame that
    carries both :data:`BOOKFEAT_REQUIRED_COLUMNS` passes whatever else it
    holds — the depth ladder's bands, the microstructure row's microprice
    and spread, the flow row's rates and moments all pass through, because
    each family's value columns are the family's own and the contract loses
    nothing by carrying them.  A frame missing either required column is
    refused with a message naming every missing column, so a host that
    materialized some other shape under a derived feature's name learns
    precisely what the contract expected.

    Checked at *accessor* time, not construction: the window is generic over
    frames (feature 4 coerces any frame without knowing its meaning), and one
    accessor's row convention must not make every window — including ones
    that never call ``bookfeat`` — pay for it at construction.
    """
    names = _column_names(frame)
    missing = [
        column
        for column in BOOKFEAT_REQUIRED_COLUMNS
        if column not in names
    ]
    if missing:
        raise BookfeatAccessError(
            f"the window's bookfeat frame is missing {', '.join(missing)}; a "
            "bookfeat frame is 1 second resolution rows — one row per symbol "
            f"per closed second, carrying at least "
            f"{', '.join(BOOKFEAT_REQUIRED_COLUMNS)} (extra columns pass "
            "through)"
        )
