"""Feature 5 of the VST fidelity harness — sim-versus-live gap reconciliation.

``additions_spec_vst_fidelity.xml``, "Fidelity Reconciliation and Reporting",
feature 5: *System compares every filled order's realized cost against the
cost model's pre-trade estimate and saves the per-order and per-slot
fidelity, so that each reconciled slot returns real sim-versus-live gaps
rather than fee-only figures.*

**Why this module exists beside :mod:`router.bingx_reconcile`.**  That
module's own reconciliation (feature 3 of the Stage 2 spec) measures a
fill's slippage against the order's own *reference price* — a passive
leg's limit, after repricing.  A ``PostOnly`` leg that fills always fills
*at* its own limit, so that slippage is always zero: the old reconciliation
cannot see the cost of repricing away from the mark between the decision
and the send, which is exactly the passive cost the audit found hidden.
This module prices every fill against :attr:`~router.submission_result.
OrderRecord.decision_mark` instead — the mark the plan was built from,
captured *before* any reprice — so a passive leg's drift between decision
and fill shows up as a real, nonzero, signed cost.

**What this module reads, and what it never does.**  Three stores this
member and its siblings already write, never a venue client and never a
plan:

* :class:`~router.submission_result.RouterOrderPlacementStore` — feature
  2's ``router_order_record``, read by :meth:`~router.submission_result.
  RouterOrderPlacementStore.records_for`, for the slot's decision-time
  facts (``decision_mark``, ``expected_cost_bps``) and the leg's own terms
  (``symbol``, ``side``, ``type``).
* :func:`router.bingx_reconcile.order_fill_record` — feature 3's
  ``router_order_fill``, keyed by the venue's own 40-character
  ``clientOrderID`` (:func:`~router.bingx_client_order_id.
  project_bingx_client_order_id` of the record's 64-hex key), for the
  venue's final state (``avg_price``, ``commission_bps``,
  ``place_to_fill_ms``).
* :class:`~router.bingx_funding.RouterFundingIncomeStore` — feature 4's
  ``router_funding_income``, for the slot's funding income.

So :func:`reconcile_fidelity` is a pure read-and-compute over what is
already persisted: it never places, cancels or closes an order, and it
opens no socket.  Its caller (:mod:`router.bingx_rebalance`'s step 3) is the
one place that turns its answer into the ops live metrics and the
submission-health log — this module writes only its own two tables.

**Three buckets, not two.**  Every recorded leg of the slot lands in
exactly one of :data:`FIDELITY_LEG_FILLED`, :data:`FIDELITY_LEG_PARTIAL` or
:data:`FIDELITY_LEG_REJECTED` — read from :attr:`~router.bingx_reconcile.
OrderFill.executed_quantity` against :attr:`~router.bingx_reconcile.
OrderFill.original_quantity`, never from the venue's own status word (whose
vocabulary mixes *why* an order stopped with *how much* it filled: a
``CANCELED`` order can carry a partial fill, and this module's three
buckets are about the fill alone).  **"Rejected" here means *filled
nothing by the time this slot was reconciled*** — a leg recorded as placed
but found, at read-back, with no executed quantity at all (including one
the venue holds no record of, or one this store never got a fill row for).
That covers both a genuine venue refusal and an ordinary PostOnly leg that
simply never reached its price before the next slot's cancel swept it; the
spec's own sentence — *"records each rejected leg via
RouterSubmissionHealthStore.record"* — asks this module's caller to feed
both into the one submission-health vocabulary feature 320 already has,
and this module does not invent a fourth bucket to keep them apart.

**The per-slot figures are notional-weighted, over the priced subset.**  An
order contributes to the slot's ``realized_cost_bps`` / ``expected_cost_bps``
/ ``gap_bps`` means only when *both* halves are known — its fill (to price
the slippage) and its decision-time facts (``decision_mark`` for the
slippage, ``expected_cost_bps`` for the gap) — so the three means share one
weighted subset and one denominator, and a slot with no priced order
answers ``None`` for all three (*unmeasured*, never zero).
``notional_total`` is wider: every ``fill``/``partial`` leg's own notional,
whether or not its decision-time facts happened to land, because that is
the slot's whole traded size and the denominator :attr:`SlotFidelity.
funding_bps` is expressed over.

**Funding is signed the direction every other cost figure in this member
is.**  BingX's own ``income`` is positive when the account *received*
funding and negative when it paid; :attr:`~router.bingx_reconcile.
OrderFill.commission_bps` already flips the venue's own negative-is-a-cost
commission the same way, so this module's funding figure is the same
flip: ``-income / notional_total`` in basis points, positive meaning a
cost, so a slot's ``gap_bps`` and its ``funding_bps`` read in one direction
without an operator having to remember which one is inverted.

**Append-only, idempotent per slot.**  Both tables are keyed so a second
call for the same slot writes nothing new and the row that stands is the
first one: :data:`ORDER_FIDELITY_TABLE` by ``client_order_id`` (the same
projected key feature 3's own fill table uses) and
:data:`SLOT_FIDELITY_TABLE` by ``(book_id, rebalance_ts)``, the
``INSERT ... WHERE NOT EXISTS`` shape every append-only table in this
package takes.  :func:`reconcile_fidelity` always answers the *standing*
row, read back after the write, so a re-run of the previous slot's
reconciliation returns exactly what the first run computed even if the
underlying stores had, in principle, changed in between.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .bingx_client_order_id import project_bingx_client_order_id
from .bingx_funding import RouterFundingIncomeStore
from .bingx_order import BINGX_BUY, BINGX_LIMIT_ORDER
from .bingx_orders import (
    VST_ORDER_STATUS_CANCELED,
    VST_ORDER_STATUS_CANCELLED,
    VST_ORDER_STATUS_EXPIRED,
)
from .bingx_reconcile import ORDER_FILL_TABLE, OrderFill, order_fill_record
from .errors import RouterError, RouterStoreError
from .submission_result import OrderRecord, RouterOrderPlacementStore

__all__ = [
    "FIDELITY_CODE",
    "FIDELITY_LEG_FILLED",
    "FIDELITY_LEG_PARTIAL",
    "FIDELITY_LEG_REJECTED",
    "FIDELITY_LEG_STATES",
    "FIDELITY_LEG_UNFILLED",
    "ORDER_FIDELITY_TABLE",
    "SLOT_FIDELITY_TABLE",
    "FidelitySlot",
    "OrderFidelity",
    "RouterFidelityError",
    "SlotFidelity",
    "reconcile_fidelity",
]

#: The greppable token every refusal this module raises opens with — coined
#: on the module's own name, the convention every sibling in this package
#: keeps.
FIDELITY_CODE = "fidelity"

#: A recorded leg fully filled: its executed quantity reached (or, by a
#: rounding slop the venue itself reports, exceeded) its original quantity.
FIDELITY_LEG_FILLED = "fill"
#: A recorded leg partially filled: some but not all of its original
#: quantity executed.
FIDELITY_LEG_PARTIAL = "partial"
#: A recorded leg that filled nothing and that the venue itself refused, or
#: never accepted at all — a venue rejection (status ``REJECTED``), the
#: venue holding no record of the order at all, or a fill row this module
#: never got at all (the defensive case; see :func:`_leg_fidelity`).  A leg
#: the venue *did* accept and rested unfilled is :data:`FIDELITY_LEG_UNFILLED`
#: instead — see that constant for why the two are kept apart.
FIDELITY_LEG_REJECTED = "reject"
#: A recorded leg the venue accepted — it was never refused at
#: submission — but that ended with zero executed quantity: the venue's own
#: terminal word for it is ``CANCELED`` or ``EXPIRED``.  The ordinary fate of
#: a PostOnly leg that simply never reached its price before the next slot's
#: own sweep cancelled it, and a different fact from a venue refusal: the
#: order *landed*, it just never filled, so folding it into
#: :data:`FIDELITY_LEG_REJECTED` would count an ordinary resting leg as if
#: the venue had refused it, and would fold its resting time into the fill
#: latency the way :attr:`OrderFidelity.place_to_fill_ms` measures (see
#: :attr:`OrderFidelity.unfilled_rest_ms` for its own, separate, latency).
FIDELITY_LEG_UNFILLED = "unfilled"
#: The closed vocabulary the four constants above name, in the order a
#: slot's counts are reported.
FIDELITY_LEG_STATES = (
    FIDELITY_LEG_FILLED,
    FIDELITY_LEG_PARTIAL,
    FIDELITY_LEG_REJECTED,
    FIDELITY_LEG_UNFILLED,
)

#: The venue's own terminal words for an accepted leg that filled nothing —
#: the set :func:`_leg_fidelity` judges a zero-fill leg against to tell
#: :data:`FIDELITY_LEG_UNFILLED` apart from :data:`FIDELITY_LEG_REJECTED`.
_UNFILLED_TERMINAL_STATUSES = frozenset(
    {VST_ORDER_STATUS_CANCELED, VST_ORDER_STATUS_CANCELLED, VST_ORDER_STATUS_EXPIRED}
)

#: One row per leg of a reconciled slot — the per-order half of the
#: sentence.  Keyed by the venue's own 40-character projection (the same
#: key :data:`router.bingx_reconcile.ORDER_FILL_TABLE` uses), so a re-read
#: of an already-reconciled leg changes nothing.
ORDER_FIDELITY_TABLE = "router_order_fidelity"

#: One row per reconciled slot — the per-slot half of the sentence. Keyed
#: by the rebalance's own identity, ``(book_id, rebalance_ts)``.
SLOT_FIDELITY_TABLE = "router_slot_fidelity"

#: Basis points per unit of rate or price, restated here as every module in
#: this package that measures a cost in bps restates it.
_BPS_PER_UNIT = Decimal(10_000)

#: One slot's width — the spec's own four hours
#: (``additions_spec_bingx_vst_stage2.xml``'s ``REBALANCE_SLOT_HOURS``),
#: restated rather than imported from :mod:`router.bingx_rebalance`: that
#: module is this one's caller, and importing it back here would be a
#: cycle for one constant neither module's own law ever changes
#: independently of the other's.
_SLOT_WIDTH = timedelta(hours=4)

#: The columns :data:`ORDER_FIDELITY_TABLE` has carried since this bugfix —
#: :data:`_LEGACY_ORDER_FIDELITY_COLUMNS` is the same list from before it,
#: kept side by side so :func:`_migrate_order_fidelity_table` cannot drift
#: the two apart.
_ORDER_FIDELITY_COLUMNS = (
    "client_order_id, book_id, rebalance_ts, symbol, side, type, "
    "leg_state, decision_mark, expected_cost_bps, realized_cost_bps, "
    "gap_bps, commission_bps, maker, place_to_fill_ms, unfilled_rest_ms, "
    "notional, computed_at"
)

#: :data:`ORDER_FIDELITY_TABLE`'s columns before this bugfix — no
#: ``unfilled_rest_ms``, and a ``leg_state`` CHECK with no ``'unfilled'``.
#: What :func:`_migrate_order_fidelity_table` reads a pre-existing table's
#: rows out of before rebuilding it onto :data:`_ORDER_FIDELITY_COLUMNS`.
_LEGACY_ORDER_FIDELITY_COLUMNS = (
    "client_order_id, book_id, rebalance_ts, symbol, side, type, "
    "leg_state, decision_mark, expected_cost_bps, realized_cost_bps, "
    "gap_bps, commission_bps, maker, place_to_fill_ms, notional, "
    "computed_at"
)

#: The table name :func:`_migrate_order_fidelity_table` renames a
#: pre-existing :data:`ORDER_FIDELITY_TABLE` to while it rebuilds the real
#: name fresh — never left standing past one migration's own transaction.
_LEGACY_ORDER_FIDELITY_TABLE = "router_order_fidelity_pre_unfilled"

_SLOT_FIDELITY_COLUMNS = (
    "book_id, rebalance_ts, n_legs, n_fills, n_partials, n_rejects, "
    "n_unfilled, reject_rate, unfilled_rate, notional_total, "
    "realized_cost_bps, expected_cost_bps, gap_bps, funding_bps, computed_at"
)

_LEG_STATE_CHECK = ", ".join(f"'{state}'" for state in FIDELITY_LEG_STATES)

_SCHEMA = f"""
-- Feature 5 of additions_spec_vst_fidelity.xml: the per-order half, one row
-- per leg of a reconciled slot, keyed by the venue's own 40-character
-- clientOrderID projection (the same key feature 3's router_order_fill
-- table uses) so a re-reconciliation of one slot changes nothing.
CREATE TABLE IF NOT EXISTS {ORDER_FIDELITY_TABLE} (
    client_order_id    TEXT NOT NULL PRIMARY KEY,
    book_id            TEXT NOT NULL,
    rebalance_ts       TEXT NOT NULL,
    symbol             TEXT NOT NULL,
    side               TEXT NOT NULL,
    type               TEXT NOT NULL,
    leg_state          TEXT NOT NULL CHECK (leg_state IN ({_LEG_STATE_CHECK})),
    decision_mark      TEXT,
    expected_cost_bps  REAL,
    realized_cost_bps  REAL,
    gap_bps            REAL,
    commission_bps     REAL,
    maker              INTEGER,
    place_to_fill_ms   INTEGER,
    unfilled_rest_ms   INTEGER,
    notional           TEXT,
    computed_at        TEXT NOT NULL
);

-- The per-slot half: one row per reconciled slot, keyed by the rebalance's
-- own identity so a second reconciliation of the same slot stands on the
-- first row rather than a second one.
CREATE TABLE IF NOT EXISTS {SLOT_FIDELITY_TABLE} (
    book_id            TEXT NOT NULL,
    rebalance_ts       TEXT NOT NULL,
    n_legs             INTEGER NOT NULL,
    n_fills            INTEGER NOT NULL,
    n_partials         INTEGER NOT NULL,
    n_rejects          INTEGER NOT NULL,
    n_unfilled         INTEGER NOT NULL DEFAULT 0,
    reject_rate        REAL,
    unfilled_rate      REAL,
    notional_total     TEXT NOT NULL,
    realized_cost_bps  REAL,
    expected_cost_bps  REAL,
    gap_bps            REAL,
    funding_bps        REAL,
    computed_at        TEXT NOT NULL,
    PRIMARY KEY (book_id, rebalance_ts)
);
"""

_ORDER_FIDELITY_INSERT_SQL = f"""
INSERT INTO {ORDER_FIDELITY_TABLE} ({_ORDER_FIDELITY_COLUMNS})
SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM {ORDER_FIDELITY_TABLE} WHERE client_order_id = ?
)
"""

_ORDER_FIDELITY_READ_FOR_SLOT_SQL = f"""
SELECT {_ORDER_FIDELITY_COLUMNS}
FROM {ORDER_FIDELITY_TABLE}
WHERE book_id = ? AND rebalance_ts = ?
ORDER BY rowid
"""

_SLOT_FIDELITY_INSERT_SQL = f"""
INSERT INTO {SLOT_FIDELITY_TABLE} ({_SLOT_FIDELITY_COLUMNS})
SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM {SLOT_FIDELITY_TABLE} WHERE book_id = ? AND rebalance_ts = ?
)
"""

_SLOT_FIDELITY_READ_SQL = f"""
SELECT {_SLOT_FIDELITY_COLUMNS}
FROM {SLOT_FIDELITY_TABLE}
WHERE book_id = ? AND rebalance_ts = ?
"""


class RouterFidelityError(RouterError):
    """A sim-versus-live fidelity this module cannot compute or persist.

    Raised for a fault of the ask — a ``slot`` that is not a
    :class:`FidelitySlot`, a blank ``database_url`` — never for a fact
    about a fill: a leg with no decision-time facts, no fill row or no
    funding income simply prices what it can and leaves the rest ``None``
    (see the module docstring).  The store's own failures keep
    :class:`~router.errors.RouterStoreError`.
    """


def _require_database_url(value: Any) -> str:
    """Return ``value`` as a non-empty database URL, or refuse it by name."""
    if not isinstance(value, str) or not value.strip():
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: database_url must be a non-empty string, got "
            f"{value!r} ({type(value).__name__}); the per-order and "
            "per-slot fidelity are read from and written to the store this "
            "slot's own placements and fills are recorded in, and a value "
            "that names none names no store (feature 5)"
        )
    return value.strip()


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation every store in this package restates in its own
    words: a store reaches into no sibling's private helper.
    ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is absolute, and
    any other scheme is refused by name.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterStoreError(
            f"unsupported DATABASE_URL scheme {parsed.scheme!r}: the "
            "router's fidelity store speaks sqlite:/// (the spec's "
            "single-machine allowance); point the database_url at the "
            "sqlite database this slot's placements and fills are recorded "
            "in (feature 5)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterStoreError(
            f"sqlite DATABASE_URL must not carry a host, got "
            f"{parsed.netloc!r} (feature 5)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise RouterStoreError(
            "sqlite DATABASE_URL carries no database path (feature 5)"
        )
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this store stores."""
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: Any, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name."""
    if not isinstance(moment, datetime):
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: {what} must be a datetime, got {moment!r} "
            f"({type(moment).__name__}) (feature 5)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: {what}={moment!r} names no timezone; a slot "
            "is an instant every process must agree on, and a naive moment "
            "names an offset nobody agreed on (feature 5)"
        )
    return moment


def _decimal_text_or_none(value: Decimal | None) -> str | None:
    """Render a :class:`~decimal.Decimal` in plain positional notation, or
    ``None`` — the same rendering every store in this package gives its own
    decimals."""
    return None if value is None else format(value, "f")


def _decimal_or_none(value: Any, *, what: str) -> Decimal | None:
    """``None`` verbatim, or ``value`` read as an exact Decimal, or refuse it."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: the fidelity row carries {what}={value!r}, "
            "which is not a decimal (feature 5)"
        ) from exc


@dataclass(frozen=True)
class FidelitySlot:
    """The rebalance slot :func:`reconcile_fidelity` is asked about.

    ``book_id`` and ``rebalance_ts`` are exactly the pair every store in
    this package addresses a rebalance by (``records_for``'s own terms);
    this is a value rather than two loose arguments so a caller cannot
    transpose them, and so bingx_rebalance's own call site reads as the
    identity it is — the previous slot's — rather than two positional
    strings.
    """

    book_id: str
    rebalance_ts: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.book_id, str) or not self.book_id.strip():
            raise RouterFidelityError(
                f"{FIDELITY_CODE}: a slot's book_id must be non-empty text, "
                f"got {self.book_id!r} ({type(self.book_id).__name__}); "
                "every order's terms are addressed by (book_id, "
                "rebalance_ts), and a slot that names no book names no "
                "orders to reconcile (feature 5)"
            )
        object.__setattr__(self, "book_id", self.book_id.strip())
        object.__setattr__(
            self, "rebalance_ts", _require_aware(self.rebalance_ts, "rebalance_ts")
        )


@dataclass(frozen=True)
class OrderFidelity:
    """One row of :data:`ORDER_FIDELITY_TABLE` — one leg's own fidelity.

    ``client_order_id`` is the venue's own 40-character projection (the same
    key :class:`~router.bingx_reconcile.OrderFill` is keyed by).
    ``leg_state`` is one of :data:`FIDELITY_LEG_STATES`.  ``decision_mark``
    and ``expected_cost_bps`` are feature 2's decision-time facts, carried
    whether or not the leg ever filled; ``realized_cost_bps``, ``gap_bps``,
    ``commission_bps``, ``maker``, ``place_to_fill_ms`` and ``notional`` are
    ``None`` for a :data:`FIDELITY_LEG_REJECTED` or :data:`FIDELITY_LEG_UNFILLED`
    leg, neither of which filled anything to measure them from.
    ``place_to_fill_ms`` is ``None`` for anything but a :data:`FIDELITY_LEG_FILLED`
    or :data:`FIDELITY_LEG_PARTIAL` leg — it measures time to a fill, never
    time to a cancel.  ``unfilled_rest_ms`` is the mirror image: the time the
    venue held a :data:`FIDELITY_LEG_UNFILLED` leg open before its terminal
    ``CANCELED``/``EXPIRED`` state, ``None`` for every other leg state.
    """

    client_order_id: str
    book_id: str
    rebalance_ts: datetime
    symbol: str
    side: str
    type: str
    leg_state: str
    decision_mark: Decimal | None
    expected_cost_bps: float | None
    realized_cost_bps: float | None
    gap_bps: float | None
    commission_bps: float | None
    maker: bool | None
    place_to_fill_ms: int | None
    unfilled_rest_ms: int | None
    notional: Decimal | None
    computed_at: datetime


@dataclass(frozen=True)
class SlotFidelity:
    """One row of :data:`SLOT_FIDELITY_TABLE` — the slot's own fidelity.

    ``n_legs`` is always ``n_fills + n_partials + n_rejects + n_unfilled``.
    ``reject_rate`` is ``n_rejects / n_legs`` and ``unfilled_rate`` is
    ``n_unfilled / n_legs`` — each ``None`` only when ``n_legs`` is zero,
    which cannot happen for a row this module writes (see
    :func:`reconcile_fidelity`'s own early exit), but can for a value a
    caller constructs by hand.  ``realized_cost_bps``, ``expected_cost_bps``
    and ``gap_bps`` are the notional-weighted means over the slot's priced
    legs — ``None`` when none priced.  ``funding_bps`` is ``None`` only when
    ``notional_total`` is zero (nothing to express it over).

    ``orders`` is the slot's own legs, in the module's answer — not a
    column of :data:`SLOT_FIDELITY_TABLE`, which holds only the slot's own
    aggregate row, but carried here the way
    :class:`~router.submission_health.SubmissionHealth` carries its own
    ``processes``: the caller that acts on a slot's rejects (bingx_rebalance
    step 3) needs the per-leg rows the aggregate was computed from, not a
    second read.
    """

    book_id: str
    rebalance_ts: datetime
    n_legs: int
    n_fills: int
    n_partials: int
    n_rejects: int
    n_unfilled: int
    reject_rate: float | None
    unfilled_rate: float | None
    notional_total: Decimal
    realized_cost_bps: float | None
    expected_cost_bps: float | None
    gap_bps: float | None
    funding_bps: float | None
    computed_at: datetime
    orders: tuple[OrderFidelity, ...] = field(default_factory=tuple)


def _leg_fidelity(
    record: OrderRecord, fill: OrderFill | None, *, computed_at: datetime
) -> OrderFidelity:
    """One recorded leg's fidelity, from its decision-time facts and its fill.

    ``fill`` is ``None`` when this slot's reconciliation (feature 3) never
    saved a row for this leg — a defensive case this production path should
    not reach, since :func:`~router.bingx_reconcile.
    reconcile_rebalance_fill_costs` saves every recorded leg's fill before
    this module ever runs — treated identically to a venue refusal:
    :data:`FIDELITY_LEG_REJECTED`, with every fill-derived figure ``None``.

    A zero-fill leg the venue's own terminal word reports as ``CANCELED`` or
    ``EXPIRED`` is :data:`FIDELITY_LEG_UNFILLED` instead of
    :data:`FIDELITY_LEG_REJECTED`: the venue *accepted* that leg, it simply
    never reached a fill before it was cancelled (the ordinary fate of a
    PostOnly leg the price never reached before the next slot's own sweep),
    which is a different fact from a venue refusal. Its resting time is
    :attr:`OrderFidelity.unfilled_rest_ms`, never folded into
    :attr:`OrderFidelity.place_to_fill_ms` — that figure measures time to a
    fill, and an unfilled leg had none.
    """

    projected = project_bingx_client_order_id(record.client_order_id)
    executed = fill.executed_quantity if fill is not None else None
    average = fill.avg_price if fill is not None else None
    has_fill = (
        fill is not None
        and executed is not None
        and executed > 0
        and average is not None
        and average > 0
    )

    notional: Decimal | None = None
    commission_bps: float | None = None
    maker: bool | None = None
    realized_bps: float | None = None
    place_to_fill_ms: int | None = None
    unfilled_rest_ms: int | None = None

    if not has_fill:
        if fill is not None and fill.status in _UNFILLED_TERMINAL_STATUSES:
            leg_state = FIDELITY_LEG_UNFILLED
            unfilled_rest_ms = fill.place_to_fill_ms
        else:
            leg_state = FIDELITY_LEG_REJECTED
    else:
        assert fill is not None and executed is not None and average is not None
        if fill.original_quantity is not None and executed < fill.original_quantity:
            leg_state = FIDELITY_LEG_PARTIAL
        else:
            leg_state = FIDELITY_LEG_FILLED
        notional = executed * average
        commission_bps = fill.commission_bps
        # "fill at the limit" (a PostOnly LIMIT leg always rests as a maker
        # in this bot) or a fee rate that reads negative or zero (a rebate
        # or a waived fee), which could only be true of a maker fill.
        maker = (record.type == BINGX_LIMIT_ORDER) or (
            commission_bps is not None and commission_bps <= 0
        )
        if (
            record.decision_mark is not None
            and record.decision_mark > 0
            and commission_bps is not None
        ):
            sign = Decimal(1) if record.side == BINGX_BUY else Decimal(-1)
            slippage_bps = (
                sign
                * (average - record.decision_mark)
                / record.decision_mark
                * _BPS_PER_UNIT
            )
            realized_bps = float(slippage_bps) + commission_bps
        place_to_fill_ms = fill.place_to_fill_ms

    expected_bps = record.expected_cost_bps
    gap_bps = (
        realized_bps - expected_bps
        if realized_bps is not None and expected_bps is not None
        else None
    )

    return OrderFidelity(
        client_order_id=projected,
        book_id=record.book_id,
        rebalance_ts=record.rebalance_ts,
        symbol=record.symbol,
        side=record.side,
        type=record.type,
        leg_state=leg_state,
        decision_mark=record.decision_mark,
        expected_cost_bps=expected_bps,
        realized_cost_bps=realized_bps,
        gap_bps=gap_bps,
        commission_bps=commission_bps,
        maker=maker,
        place_to_fill_ms=place_to_fill_ms,
        unfilled_rest_ms=unfilled_rest_ms,
        notional=notional,
        computed_at=computed_at,
    )


def _slot_funding_income(
    *, database_url: str, symbols: set[str], since: datetime, until: datetime
) -> Decimal:
    """The slot's traded symbols' own funding income over ``[since, until)``.

    Feature 4's own store, narrowed per symbol (its own ``rows(symbol=)``)
    and then by the slot's window in Python — the volumes this store ever
    holds are small enough that a second query per symbol costs nothing a
    caller would notice. A symbol with no funding row in the window
    contributes zero, which is a measurement, never an absence: see
    :func:`reconcile_fidelity` for why the slot's own ``funding_bps`` is
    ``None`` only when there is no notional to express it over, never when
    the funding itself happened to be zero.
    """

    if not symbols:
        return Decimal(0)
    store = RouterFundingIncomeStore(database_url)
    since_ms = int(since.timestamp() * 1000)
    until_ms = int(until.timestamp() * 1000)
    total = Decimal(0)
    for symbol in symbols:
        for row in store.rows(symbol=symbol):
            if since_ms <= row.time < until_ms:
                total += Decimal(row.income)
    return total


def _order_fidelity_params(order: OrderFidelity) -> tuple[Any, ...]:
    """The 18 bound parameters :data:`_ORDER_FIDELITY_INSERT_SQL` takes."""
    key = order.client_order_id
    return (
        key,
        order.book_id,
        _isoformat_utc(order.rebalance_ts),
        order.symbol,
        order.side,
        order.type,
        order.leg_state,
        _decimal_text_or_none(order.decision_mark),
        order.expected_cost_bps,
        order.realized_cost_bps,
        order.gap_bps,
        order.commission_bps,
        None if order.maker is None else int(order.maker),
        order.place_to_fill_ms,
        order.unfilled_rest_ms,
        _decimal_text_or_none(order.notional),
        _isoformat_utc(order.computed_at),
        key,
    )


def _order_fidelity_from_row(row: tuple) -> OrderFidelity:
    """Rebuild one stored :data:`ORDER_FIDELITY_TABLE` row, or refuse it.

    The same stance every reader in this package takes of its own table:
    SQLite is writable by any tool, so a row this module did not write is
    refused by name rather than trusted as a plausible-looking fidelity.
    """

    (
        client_order_id,
        book_id,
        rebalance_ts_raw,
        symbol,
        side,
        type_,
        leg_state,
        decision_mark_raw,
        expected_cost_bps,
        realized_cost_bps,
        gap_bps,
        commission_bps,
        maker_raw,
        place_to_fill_ms,
        unfilled_rest_ms,
        notional_raw,
        computed_at_raw,
    ) = row
    try:
        rebalance_ts = datetime.fromisoformat(rebalance_ts_raw)
        computed_at = datetime.fromisoformat(computed_at_raw)
    except (TypeError, ValueError) as exc:
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: the fidelity row for {client_order_id!r} "
            f"carries a moment this store cannot read ({rebalance_ts_raw!r}, "
            f"{computed_at_raw!r}) (feature 5)"
        ) from exc
    if leg_state not in FIDELITY_LEG_STATES:
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: the fidelity row for {client_order_id!r} "
            f"carries leg_state={leg_state!r}, which is not one of "
            f"{FIDELITY_LEG_STATES} (feature 5)"
        )
    return OrderFidelity(
        client_order_id=client_order_id,
        book_id=book_id,
        rebalance_ts=rebalance_ts,
        symbol=symbol,
        side=side,
        type=type_,
        leg_state=leg_state,
        decision_mark=_decimal_or_none(decision_mark_raw, what="decision_mark"),
        expected_cost_bps=expected_cost_bps,
        realized_cost_bps=realized_cost_bps,
        gap_bps=gap_bps,
        commission_bps=commission_bps,
        maker=None if maker_raw is None else bool(maker_raw),
        place_to_fill_ms=place_to_fill_ms,
        unfilled_rest_ms=unfilled_rest_ms,
        notional=_decimal_or_none(notional_raw, what="notional"),
        computed_at=computed_at,
    )


def _slot_fidelity_params(
    slot_fidelity: SlotFidelity, *, book_id: str, rebalance_ts: str
) -> tuple[Any, ...]:
    """The 17 bound parameters :data:`_SLOT_FIDELITY_INSERT_SQL` takes."""
    return (
        book_id,
        rebalance_ts,
        slot_fidelity.n_legs,
        slot_fidelity.n_fills,
        slot_fidelity.n_partials,
        slot_fidelity.n_rejects,
        slot_fidelity.n_unfilled,
        slot_fidelity.reject_rate,
        slot_fidelity.unfilled_rate,
        _decimal_text_or_none(slot_fidelity.notional_total),
        slot_fidelity.realized_cost_bps,
        slot_fidelity.expected_cost_bps,
        slot_fidelity.gap_bps,
        slot_fidelity.funding_bps,
        _isoformat_utc(slot_fidelity.computed_at),
        book_id,
        rebalance_ts,
    )


def _slot_fidelity_from_row(
    row: tuple, *, orders: tuple[OrderFidelity, ...]
) -> SlotFidelity:
    """Rebuild one stored :data:`SLOT_FIDELITY_TABLE` row, or refuse it."""
    (
        book_id,
        rebalance_ts_raw,
        n_legs,
        n_fills,
        n_partials,
        n_rejects,
        n_unfilled,
        reject_rate,
        unfilled_rate,
        notional_total_raw,
        realized_cost_bps,
        expected_cost_bps,
        gap_bps,
        funding_bps,
        computed_at_raw,
    ) = row
    try:
        rebalance_ts = datetime.fromisoformat(rebalance_ts_raw)
        computed_at = datetime.fromisoformat(computed_at_raw)
    except (TypeError, ValueError) as exc:
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: the slot fidelity for {book_id!r} carries a "
            f"moment this store cannot read ({rebalance_ts_raw!r}, "
            f"{computed_at_raw!r}) (feature 5)"
        ) from exc
    notional_total = _decimal_or_none(notional_total_raw, what="notional_total")
    if notional_total is None:
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: the slot fidelity for {book_id!r} carries no "
            "notional_total; every row this module writes states one "
            "(feature 5)"
        )
    return SlotFidelity(
        book_id=book_id,
        rebalance_ts=rebalance_ts,
        n_legs=n_legs,
        n_fills=n_fills,
        n_partials=n_partials,
        n_rejects=n_rejects,
        n_unfilled=n_unfilled,
        reject_rate=reject_rate,
        unfilled_rate=unfilled_rate,
        notional_total=notional_total,
        realized_cost_bps=realized_cost_bps,
        expected_cost_bps=expected_cost_bps,
        gap_bps=gap_bps,
        funding_bps=funding_bps,
        computed_at=computed_at,
        orders=orders,
    )


#: :data:`SLOT_FIDELITY_TABLE`'s columns added by this bugfix, name paired
#: with its SQLite type — :func:`_ensure_slot_fidelity_columns`'s own list,
#: the same additive-migration shape :mod:`router.submission_result` keeps
#: for its own table's growth (``_ensure_order_record_decision_columns``).
_SLOT_FIDELITY_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("n_unfilled", "INTEGER NOT NULL DEFAULT 0"),
    ("unfilled_rate", "REAL"),
)


def _ensure_slot_fidelity_columns(connection: sqlite3.Connection) -> None:
    """Add :data:`_SLOT_FIDELITY_NEW_COLUMNS` to a pre-existing table.

    A table :data:`_SCHEMA` just created fresh already carries both
    columns, so probing finds nothing missing and this is a no-op; a live
    store written by a prior version of this module is missing both, and
    this adds them without touching a row it already holds.  Unlike
    :data:`ORDER_FIDELITY_TABLE`, this table carries no CHECK constraint
    that widens, so an additive ``ALTER TABLE`` is enough — no rebuild.
    """
    rows = connection.execute(f"PRAGMA table_info({SLOT_FIDELITY_TABLE})").fetchall()
    existing = {str(row[1]) for row in rows}
    for name, sqltype in _SLOT_FIDELITY_NEW_COLUMNS:
        if name in existing:
            continue
        connection.execute(
            f"ALTER TABLE {SLOT_FIDELITY_TABLE} ADD COLUMN {name} {sqltype}"
        )


def _was_accepted_then_unfilled(
    connection: sqlite3.Connection, client_order_id: str
) -> bool:
    """Whether :data:`ORDER_FILL_TABLE` shows ``client_order_id`` as a leg
    the venue accepted and that ended ``CANCELED``/``EXPIRED`` with zero
    executed quantity — :func:`_migrate_order_fidelity_table`'s own
    reclassification test.

    Read directly off ``connection`` — the same connection, and so the
    same transaction, that is rebuilding :data:`ORDER_FIDELITY_TABLE` —
    never through :func:`~router.bingx_reconcile.order_fill_record`, which
    opens its *own* connection and would deadlock against this function's
    own write transaction on the same database file.  A database with no
    :data:`ORDER_FILL_TABLE` at all, or no fill row for this order, answers
    ``False``: a row this migration cannot verify keeps its own state
    rather than being reclassified on a guess.
    """
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (ORDER_FILL_TABLE,),
    ).fetchone()
    if exists is None:
        return False
    row = connection.execute(
        f"SELECT status, executed_quantity FROM {ORDER_FILL_TABLE} "
        "WHERE client_order_id = ?",
        (client_order_id,),
    ).fetchone()
    if row is None:
        return False
    status, executed_quantity_raw = row
    if status not in _UNFILLED_TERMINAL_STATUSES:
        return False
    if executed_quantity_raw is None:
        return True
    try:
        return Decimal(executed_quantity_raw) <= 0
    except InvalidOperation:
        return False


def _reclassify_unfilled_rejects(connection: sqlite3.Connection) -> None:
    """Turn every stored ``reject`` row that :func:`_was_accepted_then_unfilled`
    confirms into :data:`FIDELITY_LEG_UNFILLED`, in one transaction.

    This applies the legacy copy's rule to a table that already has the
    current schema. Its stored ``place_to_fill_ms`` (the rest time) moves to
    ``unfilled_rest_ms``, and ``place_to_fill_ms`` is cleared. The pass is
    idempotent: once reclassified, a row is no longer a reject.
    """
    rejects = connection.execute(
        f"SELECT client_order_id FROM {ORDER_FIDELITY_TABLE} WHERE leg_state = ?",
        (FIDELITY_LEG_REJECTED,),
    ).fetchall()
    confirmed = [
        client_order_id
        for (client_order_id,) in rejects
        if _was_accepted_then_unfilled(connection, client_order_id)
    ]
    if not confirmed:
        return
    with connection:
        connection.executemany(
            f"UPDATE {ORDER_FIDELITY_TABLE} SET leg_state = ?, "
            "unfilled_rest_ms = place_to_fill_ms, place_to_fill_ms = NULL "
            "WHERE client_order_id = ? AND leg_state = ?",
            [
                (FIDELITY_LEG_UNFILLED, client_order_id, FIDELITY_LEG_REJECTED)
                for client_order_id in confirmed
            ],
        )


def _migrate_order_fidelity_table(connection: sqlite3.Connection) -> None:
    """Rebuild a pre-existing :data:`ORDER_FIDELITY_TABLE` onto this
    bugfix's schema, in place, inside one transaction.

    A table :data:`_SCHEMA` just created fresh already carries
    ``unfilled_rest_ms`` and the widened ``leg_state`` CHECK, so probing
    the table's own recorded DDL (``sqlite_master.sql``) finds both and
    this returns immediately — the ordinary case, and what makes a second
    run of this function change nothing (idempotent).  A table a prior
    version of this module created carries neither: it is renamed aside,
    the real name is recreated fresh on this bugfix's schema, every row is
    copied across, and a ``reject`` row :func:`_was_accepted_then_unfilled`
    confirms was really an accepted leg that ended zero-fill is
    reclassified :data:`FIDELITY_LEG_UNFILLED` — its own stored
    ``place_to_fill_ms`` (the time it actually rested, recorded as a fill
    latency by the very bug this migration fixes) carried over as
    ``unfilled_rest_ms`` and its ``place_to_fill_ms`` cleared, exactly the
    two figures :func:`_leg_fidelity` would answer for it today.  Every
    other row — every ``fill``, ``partial`` and unverifiable ``reject`` —
    is preserved untouched but for the new, ``NULL``, ``unfilled_rest_ms``.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (ORDER_FIDELITY_TABLE,),
    ).fetchone()
    if row is None or row[0] is None:
        return  # no such table yet: _SCHEMA above is about to create it fresh
    existing_sql = row[0]
    if (
        "unfilled_rest_ms" in existing_sql
        and f"'{FIDELITY_LEG_UNFILLED}'" in existing_sql
    ):
        # Already this bugfix's shape. Still reclassify any reject row the
        # fill table now confirms was accepted and then unfilled: the first
        # migration ran before the live two-L "CANCELLED" was recognised,
        # and left the 2026-10-07 08:00 SOL-USDT leg as a reject.
        _reclassify_unfilled_rejects(connection)
        return

    with connection:
        connection.execute(
            f"ALTER TABLE {ORDER_FIDELITY_TABLE} "
            f"RENAME TO {_LEGACY_ORDER_FIDELITY_TABLE}"
        )
        connection.execute(
            f"""
            CREATE TABLE {ORDER_FIDELITY_TABLE} (
                client_order_id    TEXT NOT NULL PRIMARY KEY,
                book_id            TEXT NOT NULL,
                rebalance_ts       TEXT NOT NULL,
                symbol             TEXT NOT NULL,
                side               TEXT NOT NULL,
                type               TEXT NOT NULL,
                leg_state          TEXT NOT NULL CHECK (leg_state IN ({_LEG_STATE_CHECK})),
                decision_mark      TEXT,
                expected_cost_bps  REAL,
                realized_cost_bps  REAL,
                gap_bps            REAL,
                commission_bps     REAL,
                maker              INTEGER,
                place_to_fill_ms   INTEGER,
                unfilled_rest_ms   INTEGER,
                notional           TEXT,
                computed_at        TEXT NOT NULL
            )
            """
        )
        legacy_rows = connection.execute(
            f"SELECT {_LEGACY_ORDER_FIDELITY_COLUMNS} "
            f"FROM {_LEGACY_ORDER_FIDELITY_TABLE}"
        ).fetchall()
        for legacy in legacy_rows:
            (
                client_order_id,
                book_id,
                rebalance_ts,
                symbol,
                side,
                type_,
                leg_state,
                decision_mark,
                expected_cost_bps,
                realized_cost_bps,
                gap_bps,
                commission_bps,
                maker,
                place_to_fill_ms,
                notional,
                computed_at,
            ) = legacy
            unfilled_rest_ms = None
            if leg_state == FIDELITY_LEG_REJECTED and _was_accepted_then_unfilled(
                connection, client_order_id
            ):
                leg_state = FIDELITY_LEG_UNFILLED
                unfilled_rest_ms = place_to_fill_ms
                place_to_fill_ms = None
            connection.execute(
                _ORDER_FIDELITY_INSERT_SQL,
                (
                    client_order_id,
                    book_id,
                    rebalance_ts,
                    symbol,
                    side,
                    type_,
                    leg_state,
                    decision_mark,
                    expected_cost_bps,
                    realized_cost_bps,
                    gap_bps,
                    commission_bps,
                    maker,
                    place_to_fill_ms,
                    unfilled_rest_ms,
                    notional,
                    computed_at,
                    client_order_id,
                ),
            )
        connection.execute(f"DROP TABLE {_LEGACY_ORDER_FIDELITY_TABLE}")


def _persist_fidelity(slot_fidelity: SlotFidelity, *, database_url: str) -> SlotFidelity:
    """Write ``slot_fidelity`` idempotently, and answer the row that stands.

    Every order row is claimed by its own key, then the slot row by its
    own, then both are read back — so the answer is always the *standing*
    reconciliation, identical whether this call wrote it or a prior one
    did.
    """

    path = _sqlite_path(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    book_id = slot_fidelity.book_id
    rebalance_ts = _isoformat_utc(slot_fidelity.rebalance_ts)
    try:
        connection = sqlite3.connect(path)
    except sqlite3.OperationalError as exc:
        raise RouterStoreError(
            f"could not open the fidelity store at {path}: {exc}"
        ) from exc
    try:
        with connection:
            connection.executescript(_SCHEMA)
        _migrate_order_fidelity_table(connection)
        with connection:
            _ensure_slot_fidelity_columns(connection)
        for order in slot_fidelity.orders:
            with connection:
                connection.execute(
                    _ORDER_FIDELITY_INSERT_SQL, _order_fidelity_params(order)
                )
        with connection:
            connection.execute(
                _SLOT_FIDELITY_INSERT_SQL,
                _slot_fidelity_params(
                    slot_fidelity, book_id=book_id, rebalance_ts=rebalance_ts
                ),
            )
        order_rows = connection.execute(
            _ORDER_FIDELITY_READ_FOR_SLOT_SQL, (book_id, rebalance_ts)
        ).fetchall()
        slot_row = connection.execute(
            _SLOT_FIDELITY_READ_SQL, (book_id, rebalance_ts)
        ).fetchone()
    except sqlite3.Error as exc:
        raise RouterStoreError(
            f"could not persist the fidelity reconciled for book {book_id!r} "
            f"at {rebalance_ts}: {exc}"
        ) from exc
    finally:
        connection.close()
    if slot_row is None:  # pragma: no cover - written on the same connection
        raise RouterStoreError(
            f"the fidelity reconciled for book {book_id!r} at {rebalance_ts} "
            "was written and could not be read back in the transaction that "
            "wrote it (feature 5)"
        )
    standing_orders = tuple(_order_fidelity_from_row(row) for row in order_rows)
    return _slot_fidelity_from_row(slot_row, orders=standing_orders)


def reconcile_fidelity(slot: FidelitySlot, *, database_url: str) -> SlotFidelity | None:
    """Compute and persist one slot's sim-versus-live fidelity, or ``None``.

    Feature 5's one act: read every leg feature 2 recorded for ``slot``
    (:meth:`~router.submission_result.RouterOrderPlacementStore.records_for`),
    price each against its own fill (:func:`~router.bingx_reconcile.
    order_fill_record`, feature 3's table) and its own decision-time facts,
    fold in the slot's funding income (feature 4), and persist both the
    per-order and the per-slot rows — append-only, idempotent per slot (see
    the module docstring).

    A slot this module has never recorded a placed leg for — the store has
    no row at all for ``(slot.book_id, slot.rebalance_ts)`` — has nothing to
    reconcile: nothing is written and ``None`` is answered, the same stance
    :func:`~router.bingx_reconcile.reconcile_rebalance_fill_costs` takes for
    a rebalance with no filled order.

    Never places, cancels or closes anything, and opens no socket: every
    figure comes from a store this slot's own earlier steps already wrote.

    Refuses :class:`RouterFidelityError` for a ``slot`` that is not a
    :class:`FidelitySlot` or a blank ``database_url``, and fails with
    :class:`~router.errors.RouterStoreError` when a store could not be read
    or the computed fidelity could not be written.
    """

    if not isinstance(slot, FidelitySlot):
        raise RouterFidelityError(
            f"{FIDELITY_CODE}: slot must be a FidelitySlot, got {slot!r} "
            f"({type(slot).__name__}); the rebalance a fidelity is computed "
            "for is named by the pair (book_id, rebalance_ts), and a value "
            "that is not this module's own identity names no slot to "
            "reconcile (feature 5)"
        )
    url = _require_database_url(database_url)
    now = datetime.now(UTC)

    records = RouterOrderPlacementStore(url).records_for(
        slot.book_id, slot.rebalance_ts
    )
    if not records:
        return None

    orders = tuple(
        _leg_fidelity(
            record,
            order_fill_record(
                project_bingx_client_order_id(record.client_order_id),
                database_url=url,
            ),
            computed_at=now,
        )
        for record in records
    )

    n_fills = sum(1 for order in orders if order.leg_state == FIDELITY_LEG_FILLED)
    n_partials = sum(1 for order in orders if order.leg_state == FIDELITY_LEG_PARTIAL)
    n_rejects = sum(1 for order in orders if order.leg_state == FIDELITY_LEG_REJECTED)
    n_unfilled = sum(1 for order in orders if order.leg_state == FIDELITY_LEG_UNFILLED)
    n_legs = len(orders)
    reject_rate = (n_rejects / n_legs) if n_legs else None
    unfilled_rate = (n_unfilled / n_legs) if n_legs else None

    notional_total = sum(
        (order.notional for order in orders if order.notional is not None),
        Decimal(0),
    )
    traded_symbols = {order.symbol for order in orders if order.notional is not None}

    priced = [
        order
        for order in orders
        if order.gap_bps is not None and order.notional is not None
    ]
    priced_notional = sum((order.notional for order in priced), Decimal(0))
    if priced_notional > 0:
        weight = float(priced_notional)
        realized_mean: float | None = (
            sum(float(o.notional) * o.realized_cost_bps for o in priced) / weight
        )
        expected_mean: float | None = (
            sum(float(o.notional) * o.expected_cost_bps for o in priced) / weight
        )
        gap_mean: float | None = (
            sum(float(o.notional) * o.gap_bps for o in priced) / weight
        )
    else:
        realized_mean = expected_mean = gap_mean = None

    funding_bps: float | None = None
    if notional_total > 0:
        slot_start = slot.rebalance_ts.astimezone(UTC)
        funding_income = _slot_funding_income(
            database_url=url,
            symbols=traded_symbols,
            since=slot_start,
            until=slot_start + _SLOT_WIDTH,
        )
        funding_bps = float(-funding_income / notional_total * _BPS_PER_UNIT)

    slot_fidelity = SlotFidelity(
        book_id=slot.book_id,
        rebalance_ts=slot.rebalance_ts.astimezone(UTC),
        n_legs=n_legs,
        n_fills=n_fills,
        n_partials=n_partials,
        n_rejects=n_rejects,
        n_unfilled=n_unfilled,
        reject_rate=reject_rate,
        unfilled_rate=unfilled_rate,
        notional_total=notional_total,
        realized_cost_bps=realized_mean,
        expected_cost_bps=expected_mean,
        gap_bps=gap_mean,
        funding_bps=funding_bps,
        computed_at=now,
        orders=orders,
    )
    return _persist_fidelity(slot_fidelity, database_url=url)
