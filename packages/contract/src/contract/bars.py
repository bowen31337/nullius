"""Feature 5's OHLC rows: the window's price bars, sliced by frequency.

app_spec.xml, "Signal Contract & Market Window", feature 5: *System exposes
MarketWindow.bars for 1m, 1h and 1d frequencies, which returns a Polars frame
containing no row later than the window decision time.*  docs/nullius-tech-
architecture.md §5.1 declares the accessor alongside the rest of the window's
surface::

    def bars(self, freq: Literal["1m","1h","1d"], lookback: int) -> pl.DataFrame: ...

and §4.1's data-layer table fixes where the rows come from — ``Klines 1m/1h/1d
| REST backfill + WS | continuous | forever`` — the candle stream feature 17's
worker persists: every closed candle the venue printed for each of the three
intervals, retained permanently, and carried by the sealed snapshot's
``bars/`` partitions (§4.2), which is what a host materializes into a window's
frames.  The PRD's use is the obvious one: the candle series is the market's
own record of price and volume at each cadence, and every return, volatility
and momentum quantity a signal computes over price is computed on it.

Four decisions shape this module, and each is load-bearing:

* **The frequency is a closed vocabulary, not a free-form name.**  This is the
  one frame-addressed accessor whose component is *not* free-form.  Feature 7's
  :mod:`contract.bookfeat` takes an open name because the derived book tier is
  the part of §4.1 that grows — a new family is a name the tier had not carried
  the day before — but the candle stream is the opposite: §4.1 names *exactly*
  three intervals (1m, 1h, 1d) and feature 17's ``INTERVALS`` validates a
  candle's cadence at the row boundary, so the reader that walks the log by
  interval must be able to trust that a "1m" candle is a 1m candle.  A
  contract that accepted an arbitrary ``freq`` would be promising a cadence it
  could not have persisted, so :func:`validate_bars_freq` refuses anything
  outside :data:`BARS_FREQUENCIES` rather than passing it through — a refusal
  of a spelling the stream has no rows under, not a refusal of the spec's own
  future.  The frame name is therefore ``bars:<freq>`` with ``<freq>`` pinned to
  the three spellings, and :func:`bars_frame_names` enumerates which of them a
  window actually carries.

* **The frame name is fixed-prefix, not versioned.**  Like feature 8's borrow
  rate and feature 6's trade tape — and for the same reason: an OHLC candle is
  an *observation*, an irreversible fact of the market (the property that makes
  the candle stream's retention *forever*), and an observation has no
  definition whose revision a version would name.  So there is no version
  component to address: the frame name is ``bars:<freq>`` — :data:`BARS_FRAME
_PREFIX` plus the one closed-vocabulary component.  The namespaces cannot
  collide — feature frames carry the ``feature:`` prefix and a frame literally
  named ``feature:bars:1`` is feature 9's address for a *computed* feature
  called "bars", which this accessor never reads (and :meth:`feature` never
  returns the candle stream's rows).  Two parts, where a feature frame spells
  three, on the same terms as :mod:`contract.bookfeat`.

* **Containing no row later than the decision time — checked, not assumed.**
  Feature 4 makes the window a *physical* guarantee: it is constructed host-side
  from a sealed snapshot already sliced at ``t``, so an honestly-built window
  carries no candle whose open instant is after ``t`` at all.  Feature 5
  nonetheless puts the truncation in the accessor's own sentence — *containing
  no row later than the window decision time* — and this module keeps that
  promise checked rather than documented: ``open_time <= t`` is enforced on
  every call, so a host bug, a hand-built window in a test, or a frame that
  arrived by a path that skipped the slicing cannot leak a future candle through
  this accessor.  It is the one frame this accessor reads that *can* be checked
  this way — its rows carry ``open_time`` by requirement, which is exactly why
  that column is required: ``open_time`` is the candle's place in the ordered
  series ("the series is ordered by ``open_time`` and a reader walks it in
  open-time order"), so it is the instant "later than the decision time" is
  measured against.  On an honest window the check is a no-op that costs one
  comparison per row.  Defence in depth in the same direction as the physical
  guarantee is never in tension with it.

* **The promise is about rows and about instants, so both are checked.**
  Feature 5 says a *Polars frame*, and a signal author reading this contract is
  entitled to know the frame holds a ``symbol`` and an ``open_time`` before
  computing on them: which book, which candle-open instant — the two columns the
  accessor's own mechanics turn on (identity, and the time the truncation is
  computed against).  :func:`check_bars_frame` refuses a present bars frame
  missing either, on the same deliberately-minimal terms as
  :mod:`contract.borrow` and :mod:`contract.bookfeat`: the candle's other
  columns — ``open``/``high_price``/``low_price``/``close``/``volume`` in the
  venue's own string spellings, ``close_time``, ``trade_count``, ``interval`` —
  pass through untouched, and column *types* are the host's, the venue's
  verbatim string spellings included.  One check the siblings do not make, this
  module must: ``open_time`` has to carry *instants* for the truncation to mean
  anything, so :func:`truncate_bars_frame` refuses an ``open_time`` that is not
  an Arrow timestamp column — a string or epoch-integer spelling of an instant
  is a frame this accessor cannot slice by time, and pretending otherwise would
  compare spellings where the contract promises to compare instants.  A tz-aware
  column is compared *as instants* (whatever zone it displays in); a naive
  column is read as UTC — the convention every stored timestamp in this system
  already carries.

**The lookback is a row count, not a duration.**  Unlike feature 6's
:func:`contract.trades.truncate_trades_frame`, whose lookback is *the one*
measured in seconds because the trade tape is not bucketed, the candle stream
*is* bucketed — one row per closed interval — so ``lookback`` here counts rows,
on the shared discipline every other accessor uses: ``None`` is every row the
window carries (still truncated at ``t``), a non-negative ``int`` is the
trailing ``lookback`` rows, and a ``bool`` or a negative value is refused rather
than clamped.  The truncation at ``t`` and the trailing slice are therefore two
distinct steps — the frame is first bounded at the decision time, *then* the
recent end is taken — which is exactly :meth:`contract.window.MarketWindow.
bookfeat`'s ordering, with the truncation of :meth:`trades` prepended.

**A miss is an empty frame, never a substitute.**  A window that carries no
frame under ``bars:<freq>`` — the host materialized nothing for this frequency,
or the candle stream had printed nothing by ``t`` — answers with an empty
``DataFrame``, on the same stance features 6, 7 and 8 take: an empty answer
cannot leak a wrong number, whereas a "helpful" fallback (another frequency's
candles, the nearest frame) silently would.

**Stdlib-only, and the engines deferred.**  Like :mod:`contract.features`,
:mod:`contract.borrow` and :mod:`contract.bookfeat`, this module holds no
third-party import at module scope: the frequency vocabulary, the frame-name
encoding, the row-shape check and the lookback validation are pure.  pyarrow is
reached for once per call through :func:`contract._arrow.require_arrow` (the
truncation is Arrow compute over the table the window stores) and polars once
per accessor call, on the same :func:`contract.features.require_polars` seam
every accessor uses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from .features import FeatureAccessError, validate_lookback

__all__ = [
    "BARS_FRAME_PREFIX",
    "BARS_FREQUENCIES",
    "BARS_REQUIRED_COLUMNS",
    "BarsAccessError",
    "bars_frame_name",
    "bars_frame_names",
    "check_bars_frame",
    "parse_bars_frame_name",
    "select_bars_frame",
    "truncate_bars_frame",
    "validate_bars_freq",
    "validate_bars_lookback",
]

#: The prefix that marks a frame as a frequency's candle rows, so a window's
#: other frames — feature 9's ``feature:`` namespace, feature 6's observed
#: ``trades`` tape, feature 8's ``borrow`` stream, whatever a later feature
#: materializes — are never mistaken for one of feature 5's.
BARS_FRAME_PREFIX = "bars"

#: The three frequencies §4.1's candle stream carries, and the only ones a
#: ``bars`` request may name.  Spelled to match feature 17's
#: :data:`~nullius_ingest.klines.INTERVALS` — the one closed vocabulary the
#: ingest tier validates a candle against — so the frequency a caller asks for
#: and the cadence a candle was persisted under share one spelling.  A tuple,
#: in the order an enumeration should report them.
BARS_FREQUENCIES: Tuple[str, ...] = ("1m", "1h", "1d")

#: The columns a bars frame must carry for the accessor to keep feature 5's
#: promise.  Deliberately exactly two — which book, which candle-open instant —
#: because those are the two columns the accessor's own mechanics turn on:
#: identity, and the instant the truncation at ``t`` is computed against (the
#: candle's place in the open-time-ordered series).  The candle's other columns
#: (the venue-spelled OHLC, ``close_time``, ``trade_count``, ``interval``) are
#: the host's to carry and the accessor's to pass through untouched.  A tuple,
#: in the order a refusal message should name them.
BARS_REQUIRED_COLUMNS = ("symbol", "open_time")

#: The component separator.  The ``freq`` component is a closed vocabulary and
#: carries no separator, but the name is still split on it to read a frame back
#: (:func:`parse_bars_frame_name`), so the spelling is stated once here, on the
#: same terms as :mod:`contract.bookfeat`.
_SEPARATOR = ":"

_UTC = timezone.utc


class BarsAccessError(ValueError):
    """A ``MarketWindow.bars`` request could not be honoured.

    Three causes, all refusing loudly rather than approximating:

    * a ``freq`` outside :data:`BARS_FREQUENCIES` or a malformed ``lookback`` —
      the *request* was invalid, a caller bug at the accessor (the same fact
      :class:`~contract.features.FeatureAccessError` states for ``feature``);
    * a window whose bars frame is present but does not carry
      :data:`BARS_REQUIRED_COLUMNS` — a *host* bug, a frame materialized under
      a frequency's name that is not candle rows;
    * a bars frame whose ``open_time`` does not carry instants (not an Arrow
      timestamp column) — the truncation at the decision time is a promise
      about instants, and a frame that spells them differently is not one this
      accessor can slice by time.

    All subclass :class:`ValueError` because none is a runtime condition to
    retry, and none is the "this window carries no bars frame for this
    frequency" state, which is answered with an empty frame rather than an
    exception.  The two are kept firmly apart: an exception means the question
    or the frame was invalid; an empty frame means the window carries that
    frequency's candles not at all.
    """


def validate_bars_freq(freq: object) -> str:
    """Validate a ``bars`` accessor's ``freq``, else raise.

    The closed-vocabulary half of feature 5: ``freq`` must be one of
    :data:`BARS_FREQUENCIES` — the three cadences §4.1's candle stream carries
    and feature 17 validates a candle against.  A caller passing a frequency
    outside the three is refused rather than passed through, because the stream
    has no rows under any other spelling and a promise of a cadence the contract
    cannot have persisted is the failure this refusal exists to make loud.  The
    error's *name* is this module's: a stack trace out of ``ctx.bars(...)`` must
    not point the reader at a generic validation for a rule about a different
    accessor.
    """
    if not isinstance(freq, str):
        raise BarsAccessError(
            f"bars freq must be a string; got {type(freq).__name__}"
        )
    if freq != freq.strip() or not freq:
        raise BarsAccessError(
            f"bars freq must be a non-empty, unpadded frequency; got {freq!r}"
        )
    if freq not in BARS_FREQUENCIES:
        raise BarsAccessError(
            f"bars freq must be one of {', '.join(BARS_FREQUENCIES)} "
            f"(the candle stream's three intervals); got {freq!r}"
        )
    return freq


def validate_bars_lookback(lookback: object) -> Optional[int]:
    """Validate a ``bars`` accessor's ``lookback``, else raise.

    The rule itself is feature 9's (:func:`contract.features.validate_lookback`):
    one lookback discipline across every accessor, so ``bars`` cannot drift from
    ``feature``, ``borrow`` and ``bookfeat`` over what a lookback *counts* —
    ``None`` is every row the window carries, a non-negative ``int`` is the
    trailing amount, a ``bool`` and a negative value are refused rather than
    clamped.  Only the error's *name* is this module's: a stack trace out of
    ``ctx.bars(...)`` must not point the reader at ``contract.features`` for a
    rule about a different accessor, so the shared validation's refusal is
    re-raised as :class:`BarsAccessError` with its message carried over
    unchanged.
    """
    try:
        return validate_lookback(lookback)
    except FeatureAccessError as exc:
        raise BarsAccessError(str(exc)) from exc


def bars_frame_name(freq: str) -> str:
    """The frame name under which a frequency's candle rows are carried.

    ``bars:<freq>`` — one total, injective encoding of a frequency's identity
    into the flat frame names a window's ``frames`` mapping (and, through
    feature 14, an Arrow payload manifest) can hold.  Validation happens here,
    so every path that needs a frame name — the accessor, the host that
    materializes a window, a test — refuses a malformed frequency identically,
    and the *spelling* of the address has exactly one definition for both sides
    of the join to share.  That is the point of exporting it: a host building a
    window and an accessor reading one cannot drift apart over where the
    frequency goes.
    """
    return _SEPARATOR.join((BARS_FRAME_PREFIX, validate_bars_freq(freq)))


def parse_bars_frame_name(frame_name: object) -> Optional[str]:
    """The frequency a bars frame name carries, else ``None``.

    The inverse of :func:`bars_frame_name`, and total over *any* value: a frame
    name that is not a bars frame — the observed ``"trades"`` or ``"borrow"``
    stream, feature 9's three-part ``feature:vol:1``, a bare ``object()`` — is
    reported as ``None`` rather than raising.  Enumeration is how a caller asks
    *which frequencies does this window carry?*, and that question must be
    answerable over a mapping that holds other frames too.

    Unambiguous by construction: a bars frame name has exactly two parts and a
    first part of ``bars``; its second part is reported only when it is one of
    the closed vocabulary :data:`BARS_FREQUENCIES`, so a producer that wrote a
    bars frame under a frequency the stream does not carry — or a bare
    ``bars:`` — is reported as not-a-bars-frame rather than guessed at.
    """
    if not isinstance(frame_name, str):
        return None
    parts = frame_name.split(_SEPARATOR)
    if len(parts) != 2 or parts[0] != BARS_FRAME_PREFIX:
        return None
    freq = parts[1]
    if freq not in BARS_FREQUENCIES:
        return None
    return freq


def bars_frame_names(frames: "Any") -> Tuple[str, ...]:
    """The candle frequencies a window's frames carry, sorted.

    The discoverable half of feature 5's contract: the frequency discipline is
    enforced by :func:`select_bars_frame`, but a caller handed an empty frame
    because it asked for a frequency the window does not carry needs a way to
    learn which frequencies *are* there — otherwise "not in this window" and "no
    data yet" are indistinguishable and the caller cannot tell a typo from a
    gap.  Sorted, so the enumeration is deterministic and bit-reproducible, the
    same traversal discipline :func:`contract.features.feature_frame_names`
    applies to versioned features.
    """
    return tuple(
        sorted(
            name
            for name in (
                parse_bars_frame_name(key) for key in frames
            )
            if name is not None
        )
    )


def select_bars_frame(frames: "Any", freq: str) -> Any:
    """The frame holding ``freq``'s candle rows, or ``None``.

    Feature 5's lookup, and the whole of its guarantee: the frame name is
    derived from the frequency and looked up *exactly*.  Nothing here searches,
    prefixes, falls back or prefers — a window carrying "1h" answers a question
    about "1m" with ``None``, never with the nearest frequency's candles.

    The frequency is validated (through :func:`bars_frame_name`) before the
    mapping is touched, so a malformed request is reported as such even against
    a window that carries nothing at all, rather than reading as "no rows for
    that frequency".
    """
    return frames.get(bars_frame_name(freq))


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
    raise BarsAccessError(
        f"the bars frame is a {type(frame).__name__}, which carries no "
        "column names; a bars frame is the Arrow table a window stores — "
        f"one row per closed candle, carrying at least "
        f"{', '.join(BARS_REQUIRED_COLUMNS)}"
    )


def check_bars_frame(frame: Any) -> None:
    """Refuse a frame that cannot be ``bars``'s rows; return quietly if it can.

    The row-shape half of feature 5: the accessor promises candle rows, and this
    is the check that keeps the promise checkable rather than documented.  A
    frame that carries both :data:`BARS_REQUIRED_COLUMNS` passes whatever else
    it holds — the venue-spelled OHLC, ``close_time``, ``trade_count``,
    ``interval`` all pass through, because the venue's own record of its candles
    is exactly what the frame is for and the contract loses nothing by carrying
    it.  A frame missing either required column is refused with a message naming
    every missing column, so a host that materialized some other shape under a
    frequency's name learns precisely what the contract expected.

    Checked at *accessor* time, not construction: the window is generic over
    frames (feature 4 coerces any frame without knowing its meaning), and one
    accessor's row convention must not make every window — including ones that
    never call ``bars`` — pay for it at construction.

    Names only, deliberately: whether ``open_time`` carries instants (rather
    than a string or epoch spelling of one) is checked by
    :func:`truncate_bars_frame`, which is the code whose semantics turn on it
    and which therefore reaches for pyarrow on the same lazy seam.
    """
    names = _column_names(frame)
    missing = [
        column
        for column in BARS_REQUIRED_COLUMNS
        if column not in names
    ]
    if missing:
        raise BarsAccessError(
            f"the window's bars frame is missing {', '.join(missing)}; a bars "
            "frame is candle rows — one row per closed candle the venue "
            f"printed, carrying at least {', '.join(BARS_REQUIRED_COLUMNS)} "
            "(extra columns pass through)"
        )


def _as_utc_instant(t: object) -> datetime:
    # Coerce a decision time to an aware UTC datetime, on the window's own
    # convention (contract.window._as_utc): naive means UTC — every stored
    # timestamp in this system is UTC, so a naive value can only have come from
    # a caller meaning UTC — and an aware datetime in another zone is converted
    # to the instant it names.  Stated here rather than imported so this
    # module's refusals carry this module's name, on the same grounds as the
    # component discipline :mod:`contract.bookfeat` restates.
    if not isinstance(t, datetime):
        raise BarsAccessError(
            f"the decision time to truncate at must be a datetime, "
            f"got {type(t).__name__}"
        )
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        return t.replace(tzinfo=_UTC)
    return t.astimezone(_UTC)


def _open_time_column(frame: Any) -> Any:
    # The frame's open_time column, as an Arrow column with a ``.type`` — the
    # thing the truncation compares against.  A pa.Table spells it
    # ``table.column(name)``; anything else (a polars frame handed to this
    # exported core directly, say) is refused by name rather than probed,
    # because the slice is Arrow compute over the table a window stores.
    try:
        return frame.column("open_time")
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise BarsAccessError(
            f"a {type(frame).__name__} carries no readable 'open_time' "
            "column; the truncation slices the Arrow table a window stores "
            f"(or a frame carrying at least {', '.join(BARS_REQUIRED_COLUMNS)})"
        ) from None


def truncate_bars_frame(frame: Any, t: datetime) -> Any:
    """Slice a bars frame to ``open_time <= t``; never widen it.

    The mechanical core of feature 5, exported so the truncation semantics are
    pinnable apart from the window: the rows that come back are the rows whose
    ``open_time`` is at most ``t`` — *containing no row later than the window
    decision time*, on every call, whether or not a lookback was given.  A
    candle's place in the series is its ``open_time`` ("the series is ordered by
    ``open_time``"), so "later than the decision time" is measured against it: a
    candle that opened after ``t`` is, by definition, one the window's slicing
    was meant to exclude, and this is what keeps it out even from a hand-built
    or host-buggy window.

    Two properties, each deliberate:

    * **Instants, not spellings.**  ``open_time`` must be an Arrow timestamp
      column; anything else is refused with :class:`BarsAccessError` naming the
      actual type, because comparing a lexicographic string against a datetime
      boundary is exactly the place a "works in tests, wrong at a month
      boundary" bug would hide.  A tz-aware column is compared *as instants* —
      the bounds are converted into the column's own zone, so a column
      displaying Tokyo time slices against the same instant a UTC column would —
      and a naive column is read as UTC, the convention every stored timestamp
      in this system carries.
    * **A filter, not an offset.**  The truncation is a predicate filter — one
      comparison per row over a frame the host already bounded at
      materialization.  That cost is what buys the checked truncation: an
      honestly-built window pays it as a no-op verification, and a dishonest one
      is caught here.  The trailing *lookback* is the positional O(1) slice of
      an oldest-first frame, applied after this, on the shared row-count
      discipline (see :meth:`contract.window.MarketWindow.bookfeat`).

    ``t`` may be naive (read as UTC) or aware in any zone (converted to the
    instant it names), on the window's own convention; the window always passes
    its frozen aware-UTC ``t``.
    """
    from ._arrow import require_arrow

    arrow = require_arrow()
    # ``pyarrow.compute`` is *not* bound by a bare ``import pyarrow`` (the same
    # laziness :func:`contract._arrow.require_arrow` works around for
    # ``pyarrow.ipc``), so it is imported here, on the seam, where a missing
    # install already raises a named error.
    import pyarrow.compute as compute  # noqa: PLC0415 - the deferred seam

    moment = _as_utc_instant(t)
    column = _open_time_column(frame)
    column_type = getattr(column, "type", None)
    if column_type is None or not arrow.types.is_timestamp(column_type):
        raise BarsAccessError(
            f"the bars frame's open_time is "
            f"{column_type if column_type is not None else 'unreadable'}; the "
            "truncation at the decision time is a promise about instants, so "
            "open_time must be a timestamp column (tz-aware, compared as "
            "instants; naive, read as UTC) — re-spell the column at "
            "materialization, not here"
        )
    if column_type.tz is None:
        # Naive column: compare wall values against the UTC wall spelling of
        # the bound, which is what "naive means UTC" says the column holds.
        bounds_base = moment.replace(tzinfo=None)
    else:
        # Aware column: the bound travels as the instant it names, and Arrow
        # converts it into the column's own zone — so the comparison is between
        # instants whatever the column displays in.
        bounds_base = moment
    within = compute.less_equal(
        column, arrow.scalar(bounds_base, type=column_type)
    )
    return frame.filter(within)
