"""Feature 8's margin borrow rate rows: the window's crowding proxy.

app_spec.xml, "Signal Contract & Market Window", feature 8: *System exposes
MarketWindow.borrow which returns margin borrow rate rows used as a real-time
crowding proxy.*  docs/nullius-tech-architecture.md §5.1 declares the accessor
alongside the rest of the window's surface::

    def borrow(self, lookback: int) -> pl.DataFrame: ...

and §4.1's data-layer table fixes where the rows come from — ``Funding /
borrow rate | REST | 1m | forever`` — the one stream that is polled rather
than streamed, every 60 seconds, retained permanently (feature 23's ingest
side).  The PRD names the use: margin borrow rate *"is a real-time crowding
indicator that substitutes for paid short-interest data."*  A borrow rate
rising means borrowing to short is getting more expensive, which means short
interest is building — the crowding quantity a proxy wants, observed from the
free margin API rather than bought from a vendor, and fresh to within one
poll interval of the window's decision time.  That last clause is why
"real-time" is honest here: the cadence is 60 seconds, so the newest row a
window carries is at most about a minute older than ``t``, which is as fresh
as the sealed lake can be at the instant the decision is made.

Three decisions shape this module, and each is load-bearing:

* **The frame name is fixed, not versioned.**  A window carries its data as
  a mapping of frame name to Arrow table, and feature 9's frames are named
  ``feature:<name>:<version>`` because §4.4 makes ``feature_version`` part of
  a *computed* feature's identity — "a changed definition gets a new
  ``feature_version``; it never overwrites."  A margin borrow rate is not a
  computed feature; it is an *observation* of what the venue quoted at an
  instant, and an observation has no definition to revise.  So there is no
  version component to address: the frame name is the stream's own name,
  :data:`BORROW_FRAME_NAME`.  The two namespaces cannot collide — feature
  frames carry the ``feature:`` prefix, and a frame literally named
  ``feature:borrow:1`` is feature 9's address for a *computed* feature called
  "borrow", which this accessor never reads (and the borrow frame is never
  returned by :meth:`contract.window.MarketWindow.feature`, which only reads
  prefixed names).

* **The promise is about rows, so it is checked.**  Feature 8 does not say
  "returns a frame"; it says "returns margin borrow rate *rows*", and a
  signal author reading this contract is entitled to know that the frame
  holds a ``symbol`` and a ``borrow_rate`` column before computing on them.
  :func:`check_borrow_frame` therefore refuses a present borrow frame that
  is missing either required column — a loud, named failure at the accessor
  rather than a ``ColumnNotFoundError`` three frames inside the signal, from
  a window whose host materialized some other shape under the stream's name.
  The check is deliberately minimal: :data:`BORROW_REQUIRED_COLUMNS` is
  exactly what every consumer of borrow rate rows needs (which symbol, what
  rate), and any further column — ``utilization``, ``funding_rate``, the
  conventional ``reading_time`` — passes through untouched, because the
  contract has no reason to forbid what it cannot promise and the crowding
  proxy legitimately reads those too.  Column *types* are likewise the
  host's: the ingest side keeps the venue's own string spelling verbatim
  (``"0.0001"``, not ``0.0001``), and this accessor preserves whatever it
  was handed rather than re-rendering it — a rounding introduced here would
  be indistinguishable from the venue's own in an audit.

* **A miss is an empty frame, never a substitute.**  A window that carries
  no borrow frame — the host materialized nothing for this stream, or the
  poll had not run yet at ``t`` — answers with an empty ``DataFrame``, on
  the same stance feature 9 takes: an empty answer cannot leak a wrong
  number, whereas a "helpful" fallback (the funding frame, the previous
  window's rates) silently would.  It is the same posture the read paths
  take elsewhere (a missing partition is an empty result, not an error;
  a store miss is ``None``).

**Stdlib-only, and polars deferred.**  Like :mod:`contract.features`, this
module holds no third-party import at module scope: the frame-name constant,
the row-shape check and the lookback validation are pure, so they are
import-safe in every environment the workspace contract promises one will
be — the factory scan, the test sandbox, the deterministic replay path.
Polars is reached for exactly once per accessor call, on the same
:func:`contract.features.require_polars` seam every accessor uses.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .features import FeatureAccessError, validate_lookback

__all__ = [
    "BORROW_FRAME_NAME",
    "BORROW_REQUIRED_COLUMNS",
    "BorrowAccessError",
    "check_borrow_frame",
    "validate_borrow_lookback",
]

#: The frame name under which a window carries its margin borrow rate rows.
#:
#: Not versioned, unlike :func:`contract.features.feature_frame_name`'s
#: addresses: a borrow rate is an observed stream, not a computed feature, so
#: there is no definition whose revision a version would name.  Exported so
#: the host materializing a window and the accessor reading one share one
#: spelling of the stream's address — the same reason
#: :func:`contract.features.feature_frame_name` is exported for feature 9.
BORROW_FRAME_NAME = "borrow"

#: The columns a borrow frame must carry for the accessor to keep feature 8's
#: promise.  Deliberately exactly two — which symbol, what rate — because that
#: is what every consumer of borrow rate rows needs; anything further is the
#: host's to add and the accessor's to pass through untouched.  A tuple, in
#: the order a refusal message should name them.
BORROW_REQUIRED_COLUMNS = ("symbol", "borrow_rate")


class BorrowAccessError(ValueError):
    """A ``MarketWindow.borrow`` request could not be honoured.

    Two causes, both refusing loudly rather than approximating:

    * a malformed ``lookback`` — the *request* was invalid, a caller bug at
      the accessor (the same fact :class:`~contract.features.FeatureAccessError`
      states for ``feature``);
    * a window whose borrow frame is present but does not carry
      :data:`BORROW_REQUIRED_COLUMNS` — a *host* bug, a frame materialized
      under the stream's name that is not margin borrow rate rows.

    Both subclass :class:`ValueError` because neither is a runtime condition
    to retry, and neither is the "this window carries no borrow frame" state,
    which is answered with an empty frame rather than an exception.  The
    three are kept firmly apart: an exception means the question or the frame
    was invalid; an empty frame means the window carries the stream's rows
    not at all.
    """


def validate_borrow_lookback(lookback: object) -> Optional[int]:
    """Validate a ``borrow`` accessor's ``lookback``, else raise.

    The rule itself is feature 9's (:func:`contract.features.validate_lookback`):
    one lookback discipline across every accessor, so ``borrow`` cannot drift
    from ``feature`` over what a lookback *means* — ``None`` is every row the
    window carries, a non-negative ``int`` is the trailing rows, a ``bool``
    and a negative count are refused rather than clamped.  Only the error's
    *name* is this module's: a stack trace out of ``ctx.borrow(...)`` must not
    point the reader at ``contract.features`` for a rule about a different
    accessor, so the shared validation's refusal is re-raised as
    :class:`BorrowAccessError` with its message carried over unchanged.
    """
    try:
        return validate_lookback(lookback)
    except FeatureAccessError as exc:
        raise BorrowAccessError(str(exc)) from exc


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
    raise BorrowAccessError(
        f"the borrow frame is a {type(frame).__name__}, which carries no "
        "column names; a borrow frame is the Arrow table a window stores — "
        "one row per symbol per poll, carrying at least "
        f"{', '.join(BORROW_REQUIRED_COLUMNS)}"
    )


def check_borrow_frame(frame: Any) -> None:
    """Refuse a frame that cannot be ``borrow``'s rows; return quietly if it can.

    The row-shape half of feature 8: the accessor promises *margin borrow rate
    rows*, and this is the check that keeps the promise checkable rather than
    documented.  A frame that carries both :data:`BORROW_REQUIRED_COLUMNS`
    passes whatever else it holds — extra columns pass through because the
    crowding proxy legitimately reads them and the contract loses nothing by
    carrying them.  A frame missing either required column is refused with a
    message naming every missing column, so a host that materialized some
    other shape under the stream's name learns precisely what the contract
    expected.

    Checked at *accessor* time, not construction: the window is generic over
    frames (feature 4 coerces any frame without knowing its meaning), and one
    accessor's row convention must not make every window — including ones
    that never call ``borrow`` — pay for it at construction.
    """
    names = _column_names(frame)
    missing = [
        column
        for column in BORROW_REQUIRED_COLUMNS
        if column not in names
    ]
    if missing:
        raise BorrowAccessError(
            f"the window's borrow frame is missing {', '.join(missing)}; a "
            "borrow frame is margin borrow rate rows — one row per symbol "
            f"per poll, carrying at least {', '.join(BORROW_REQUIRED_COLUMNS)} "
            "(extra columns pass through)"
        )
