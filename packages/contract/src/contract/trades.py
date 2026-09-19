"""Feature 6's aggregated trade rows: the window's tape, sliced by seconds.

app_spec.xml, "Signal Contract & Market Window", feature 6: *System exposes
MarketWindow.trades over a lookback in seconds, which returns aggregated trade
rows truncated at the decision time.*  docs/nullius-tech-architecture.md §5.1
declares the accessor alongside the rest of the window's surface::

    def trades(self, lookback_s: int) -> pl.DataFrame: ...

and §4.1's data-layer table fixes where the rows come from — ``aggTrades |
WS | continuous | forever, compressed`` — the tape feature 18's workers
persist: every aggregated trade the venue printed, gzip-compressed, retained
permanently, and carried by the sealed snapshot's ``trades/`` partitions
(§4.2), which is what a host materializes into a window's frames.  The PRD's
use is the obvious one: the tape is the market's own record of what actually
traded, and every trade-flow, momentum and impact quantity a signal computes
is computed over it.

Four decisions shape this module, and each is load-bearing:

* **The lookback is a duration, not a count — the one accessor whose is.**
  ``feature``, ``borrow`` and ``bookfeat`` all take a lookback in *rows*,
  because their streams are bucketed (a bar, a poll, a closed second) and a
  count of buckets is a stable quantity.  The trade tape is not bucketed at
  all: a liquid book prints tens of thousands of trades a second on a quiet
  day and fewer on a slow one, so "the last 500 trades" is a *different
  amount of market* every minute, while "the last 500 seconds" is the
  quantity the caller means.  Feature 6's sentence says *over a lookback in
  seconds* and §5.1 spells the parameter ``lookback_s``; this module honours
  it structurally — the trailing slice is computed against the decision time
  on the ``event_time`` column each row carries, as the closed interval
  ``[t - lookback_s, t]``, never as a positional offset.  Both ends are
  inclusive: a trade exactly ``lookback_s`` seconds old is within "the last
  ``lookback_s`` seconds", and a trade exactly at ``t`` is not *after* the
  decision time.  ``lookback_s=0`` is therefore the instant ``t`` itself —
  normally no rows, and deliberately not the whole frame, which is the
  off-by-one worth refusing to leave ambiguous.

* **Truncated at the decision time — checked, not assumed.**  Feature 4
  makes the window a *physical* guarantee: it is constructed host-side from
  a sealed snapshot already sliced at ``t``, so an honestly-built window
  carries no row after ``t`` at all.  Feature 6 nonetheless puts the
  truncation in the accessor's own sentence — *returns aggregated trade rows
  truncated at the decision time* — and this module keeps that promise
  checked rather than documented: ``event_time <= t`` is enforced on every
  call, so a host bug, a hand-built window in a test, or a frame that
  arrived by a path that skipped the slicing cannot leak a future print
  through this accessor.  It is the one accessor that *can* check — its rows
  carry ``event_time`` by requirement, which is exactly why that column is
  required — and defence in depth in the same direction as the physical
  guarantee is never in tension with it.  On an honest window the check is a
  no-op that costs one comparison per row.

* **The frame name is fixed, not versioned.**  Like feature 8's borrow rate
  and for the same reason: an aggregated trade is an *observation* — an
  irreversible fact of the market, which is the property that makes the
  tape's retention *forever* — and an observation has no definition whose
  revision a version would name.  So there is no version component to
  address: the frame name is the stream's own name,
  :data:`TRADES_FRAME_NAME`, matching §4.2's ``trades/`` partition.  The
  namespaces cannot collide — feature frames carry the ``feature:`` prefix
  and a frame literally named ``feature:trades:1`` is feature 9's address
  for a *computed* feature called "trades", which this accessor never reads
  (and ``feature`` never returns the tape's rows).

* **The promise is about rows and about instants, so both are checked.**
  Feature 6 says *aggregated trade rows*, and a signal author reading this
  contract is entitled to know the frame holds a ``symbol`` and an
  ``event_time`` before computing on them: which book, which instant — the
  two columns the accessor's own mechanics turn on (identity, and the time
  the truncation and the seconds lookback are computed against).
  :func:`check_trades_frame` refuses a present trades frame missing either,
  on the same deliberately-minimal terms as :mod:`contract.borrow` and
  :mod:`contract.bookfeat`: the tape's own further columns — ``agg_id``,
  ``price``, ``quantity``, ``first_trade_id``/``last_trade_id``,
  ``is_buyer_maker`` — pass through untouched, and column *types* are the
  host's, the venue's verbatim string spellings included.  One check the
  siblings do not make, this module must: ``event_time`` has to carry
  *instants* for a seconds lookback to mean anything, so
  :func:`truncate_trades_frame` refuses an ``event_time`` that is not an
  Arrow timestamp column — a string or epoch-integer spelling of an instant
  is a frame this accessor cannot slice by time, and pretending otherwise
  would compare spellings where the contract promises to compare instants.
  A tz-aware column is compared *as instants* (whatever zone it displays
  in); a naive column is read as UTC — the convention every stored
  timestamp in this system already carries.

**A miss is an empty frame, never a substitute.**  A window that carries no
trades frame — the host materialized nothing for this stream, or the tape
had printed nothing by ``t`` — answers with an empty ``DataFrame``, on the
same stance features 7, 8 and 9 take: an empty answer cannot leak a wrong
number, whereas a "helpful" fallback (the bookfeat frame, the previous
window's tape) silently would.

**Stdlib-only, and the engines deferred.**  Like :mod:`contract.features`,
:mod:`contract.borrow` and :mod:`contract.bookfeat`, this module holds no
third-party import at module scope: the frame-name constant, the row-shape
check and the lookback validation are pure.  pyarrow is reached for once
per call through :func:`contract._arrow.require_arrow` (the slice is Arrow
compute over the table the window stores) and polars once per accessor
call, on the same :func:`contract.features.require_polars` seam every
accessor uses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from .features import FeatureAccessError, validate_lookback

__all__ = [
    "TRADES_FRAME_NAME",
    "TRADES_REQUIRED_COLUMNS",
    "TradesAccessError",
    "check_trades_frame",
    "truncate_trades_frame",
    "validate_trades_lookback",
]

#: The frame name under which a window carries its aggregated trade rows.
#:
#: Not versioned, unlike :func:`contract.features.feature_frame_name`'s
#: addresses and for the same reason :data:`contract.borrow.BORROW_FRAME_NAME`
#: is not: an aggregated trade is an observed fact of the market, not a
#: computed feature, so there is no definition whose revision a version would
#: name.  Exported so the host materializing a window and the accessor reading
#: one share one spelling of the tape's address — and spelled to match §4.2's
#: ``trades/`` snapshot partition, so the frame a seal carries and the frame a
#: window reads are named by the same word.
TRADES_FRAME_NAME = "trades"

#: The columns a trades frame must carry for the accessor to keep feature 6's
#: promise.  Deliberately exactly two — which book, which instant — because
#: those are the two columns the accessor's own mechanics turn on: identity,
#: and the time the truncation at ``t`` and the seconds lookback are both
#: computed against.  The tape's other columns (the ids, the price and
#: quantity, the maker flag) are the host's to carry and the accessor's to
#: pass through untouched.  A tuple, in the order a refusal message should
#: name them.
TRADES_REQUIRED_COLUMNS = ("symbol", "event_time")

_UTC = timezone.utc


class TradesAccessError(ValueError):
    """A ``MarketWindow.trades`` request could not be honoured.

    Three causes, all refusing loudly rather than approximating:

    * a malformed ``lookback_s`` — the *request* was invalid, a caller bug
      at the accessor (the same fact
      :class:`~contract.features.FeatureAccessError` states for ``feature``);
    * a window whose trades frame is present but does not carry
      :data:`TRADES_REQUIRED_COLUMNS` — a *host* bug, a frame materialized
      under the tape's name that is not aggregated trade rows;
    * a trades frame whose ``event_time`` does not carry instants (not an
      Arrow timestamp column) — the seconds lookback and the truncation are
      promises about instants, and a frame that spells them differently is
      not one this accessor can slice by time.

    All subclass :class:`ValueError` because none is a runtime condition to
    retry, and none is the "this window carries no trades frame" state, which
    is answered with an empty frame rather than an exception.  The two are
    kept firmly apart: an exception means the question or the frame was
    invalid; an empty frame means the window carries the tape's rows not at
    all.
    """


def validate_trades_lookback(lookback_s: object) -> Optional[int]:
    """Validate a ``trades`` accessor's ``lookback_s``, else raise.

    The rule itself is feature 9's (:func:`contract.features.validate_lookback`):
    one lookback discipline across every accessor, so ``trades`` cannot drift
    from ``feature``, ``borrow`` and ``bookfeat`` over what a lookback
    *counts* — ``None`` is every row the window carries, a non-negative
    ``int`` is the trailing amount, a ``bool`` and a negative value are
    refused rather than clamped.  What differs is the *unit*: here the int
    names seconds, not rows, and that difference lives in the slicing (see
    :func:`truncate_trades_frame`), not in the validation — an int is an int,
    and refusing ``2.0`` seconds for the same reason ``feature`` refuses it
    as a row count is part of the shared discipline.  Only the error's *name*
    is this module's: a stack trace out of ``ctx.trades(...)`` must not point
    the reader at ``contract.features`` for a rule about a different
    accessor, so the shared validation's refusal is re-raised as
    :class:`TradesAccessError` with its message carried over unchanged.
    """
    try:
        return validate_lookback(lookback_s)
    except FeatureAccessError as exc:
        raise TradesAccessError(str(exc)) from exc


def _column_names(frame: Any) -> List[str]:
    # The names of a frame's columns, from either spelling the ecosystem uses:
    # Arrow's ``column_names`` (Table, RecordBatch, Schema) and polars'
    # ``columns``.  A window stores Arrow — frames are coerced at construction
    # (contract.window._as_frames) — but a host may want to check the frame it
    # is *about to* materialize while still holding it as a polars DataFrame,
    # and refusing that would be checking the representation rather than the
    # row shape the check exists for.
    for attribute in ("column_names", "columns"):
        names = getattr(frame, attribute, None)
        if names is not None:
            return list(names)
    raise TradesAccessError(
        f"the trades frame is a {type(frame).__name__}, which carries no "
        "column names; a trades frame is the Arrow table a window stores — "
        "one row per aggregated trade, carrying at least "
        f"{', '.join(TRADES_REQUIRED_COLUMNS)}"
    )


def check_trades_frame(frame: Any) -> None:
    """Refuse a frame that cannot be ``trades``'s rows; return quietly if it can.

    The row-shape half of feature 6: the accessor promises *aggregated trade
    rows*, and this is the check that keeps the promise checkable rather than
    documented.  A frame that carries both :data:`TRADES_REQUIRED_COLUMNS`
    passes whatever else it holds — the tape's ids, prices, quantities and
    maker flag all pass through, because the venue's own record of its trades
    is exactly what the frame is for and the contract loses nothing by
    carrying it.  A frame missing either required column is refused with a
    message naming every missing column, so a host that materialized some
    other shape under the tape's name learns precisely what the contract
    expected.

    Checked at *accessor* time, not construction: the window is generic over
    frames (feature 4 coerces any frame without knowing its meaning), and one
    accessor's row convention must not make every window — including ones
    that never call ``trades`` — pay for it at construction.

    Names only, deliberately: whether ``event_time`` carries instants (rather
    than a string or epoch spelling of one) is checked by
    :func:`truncate_trades_frame`, which is the code whose semantics turn on
    it and which therefore reaches for pyarrow on the same lazy seam.
    """
    names = _column_names(frame)
    missing = [
        column
        for column in TRADES_REQUIRED_COLUMNS
        if column not in names
    ]
    if missing:
        raise TradesAccessError(
            f"the window's trades frame is missing {', '.join(missing)}; a "
            "trades frame is aggregated trade rows — one row per trade the "
            f"venue printed, carrying at least {', '.join(TRADES_REQUIRED_COLUMNS)} "
            "(extra columns pass through)"
        )


def _as_utc_instant(t: object) -> datetime:
    # Coerce a decision time to an aware UTC datetime, on the window's own
    # convention (contract.window._as_utc): naive means UTC — every stored
    # timestamp in this system is UTC, so a naive value can only have come
    # from a caller meaning UTC — and an aware datetime in another zone is
    # converted to the instant it names.  Stated here rather than imported so
    # this module's refusals carry this module's name, on the same grounds as
    # the component discipline :mod:`contract.bookfeat` restates.
    if not isinstance(t, datetime):
        raise TradesAccessError(
            f"the decision time to truncate at must be a datetime, "
            f"got {type(t).__name__}"
        )
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        return t.replace(tzinfo=_UTC)
    return t.astimezone(_UTC)


def _event_time_column(frame: Any) -> Any:
    # The frame's event_time column, as an Arrow column with a ``.type`` —
    # the thing the truncation compares against.  A pa.Table spells it
    # ``table.column(name)``; anything else (a polars frame handed to this
    # exported core directly, say) is refused by name rather than probed,
    # because the slice is Arrow compute over the table a window stores.
    try:
        return frame.column("event_time")
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise TradesAccessError(
            f"a {type(frame).__name__} carries no readable 'event_time' "
            "column; the truncation slices the Arrow table a window stores "
            f"(or a frame carrying at least {', '.join(TRADES_REQUIRED_COLUMNS)})"
        ) from None


def truncate_trades_frame(
    frame: Any,
    t: datetime,
    lookback_s: Optional[int],
) -> Any:
    """Slice a trades frame to ``[t - lookback_s, t]``; never widen it.

    The mechanical core of feature 6, exported so the truncation semantics
    are pinnable apart from the window: the rows that come back are the rows
    whose ``event_time`` is at most ``t`` (*truncated at the decision time*,
    on every call, whether or not a lookback was given) and — when
    ``lookback_s`` is not ``None`` — at least ``t - lookback_s`` seconds old
    (*over a lookback in seconds*, both ends of the interval inclusive).
    Row order is the frame's own; a predicate slice preserves it, so the
    tape's time-ordered rows come back time-ordered.

    Three properties, each deliberate:

    * **Instants, not spellings.**  ``event_time`` must be an Arrow
      timestamp column; anything else is refused with :class:`TradesAccessError`
      naming the actual type, because comparing a lexicographic string
      against a datetime boundary is exactly the place a "works in tests,
      wrong at a month boundary" bug would hide.  A tz-aware column is
      compared *as instants* — the bounds are converted to the column's own
      type, so a column displaying Tokyo time slices against the same
      instant a UTC column would — and a naive column is read as UTC, the
      convention every stored timestamp in this system carries.
    * **Exact arithmetic.**  ``lookback_s`` is an ``int`` count of seconds,
      so the lower bound is ``t - timedelta(seconds=lookback_s)`` — integer
      microseconds on the epoch lattice, no float ever touching an instant,
      the same discipline the tape itself persists under.
    * **A filter, not an offset.**  The sibling accessors' row-count
      lookbacks are O(1) slices of an oldest-first frame; a duration cannot
      be positional, so this is a predicate filter — one comparison per row
      over a frame the host already bounded at materialization.  That cost
      is what buys the checked truncation: an honestly-built window pays it
      as a no-op verification, and a dishonest one is caught here.

    ``t`` may be naive (read as UTC) or aware in any zone (converted to the
    instant it names), on the window's own convention; the window always
    passes its frozen aware-UTC ``t``.
    """
    from ._arrow import require_arrow

    arrow = require_arrow()
    # ``pyarrow.compute`` is *not* bound by a bare ``import pyarrow`` (the
    # same laziness :func:`contract._arrow.require_arrow` works around for
    # ``pyarrow.ipc``), so it is imported here, on the seam, where a missing
    # install already raises a named error.
    import pyarrow.compute as compute  # noqa: PLC0415 - the deferred seam
    moment = _as_utc_instant(t)
    column = _event_time_column(frame)
    column_type = getattr(column, "type", None)
    if column_type is None or not arrow.types.is_timestamp(column_type):
        raise TradesAccessError(
            f"the trades frame's event_time is "
            f"{column_type if column_type is not None else 'unreadable'}; the "
            "truncation at the decision time and the lookback in seconds are "
            "promises about instants, so event_time must be a timestamp "
            "column (tz-aware, compared as instants; naive, read as UTC) — "
            "re-spell the column at materialization, not here"
        )
    if column_type.tz is None:
        # Naive column: compare wall values against the UTC wall spelling of
        # the bounds, which is what "naive means UTC" says the column holds.
        bounds_base = moment.replace(tzinfo=None)
    else:
        # Aware column: the bounds travel as the instants they name, and
        # Arrow converts each into the column's own zone — so the comparison
        # is between instants whatever the column displays in.
        bounds_base = moment
    within = compute.less_equal(
        column, arrow.scalar(bounds_base, type=column_type)
    )
    if lookback_s is not None:
        # An int count of seconds: exact integer microseconds, both ends of
        # the closed interval inclusive.
        lower = arrow.scalar(
            bounds_base - timedelta(seconds=lookback_s), type=column_type
        )
        within = compute.and_(within, compute.greater_equal(column, lower))
    return frame.filter(within)
