"""Stage 2's fill-cost reconciliation — feature 3 of the VST Stage 2 spec.

``additions_spec_bingx_vst_stage2.xml``, "BingX VST Stage 2", feature 3:
*System reconciles one finished rebalance's fill costs.  It reads back the
rebalance's orders with read_back_orders and takes each filled order's
executedQty and avgPrice.  The realized cost in basis points is the
notional-weighted signed slippage of avgPrice against the order's reference
price (adverse is positive), plus the fee rate the order paid.  The fee is
makerFeeRate for a PostOnly LIMIT and takerFeeRate for a MARKET order, from
the contracts document.  The modeled cost is that same fee rate alone.  It
records both through forward.reconciliation.reconcile_fill_costs(book_id,
rebalance_ts=, realized_cost_bps=, modeled_cost_bps=), and returns the
recorded reconciliation.  A rebalance with no filled order records nothing
and returns none.  Reconciling the same rebalance twice returns the first
record unchanged.*

**Two measurements and one difference, and the difference is not this
module's to state.**  Feature 340 of ``app_spec.xml`` — *"System reconciles
realized fill costs against modeled costs in basis points, persisting the
difference per rebalance"* — owns the table and computes the difference
(``realized − modeled``); this module owns the *realized* side of that
sentence for one venue's fills.  So :func:`reconcile_rebalance_fill_costs`
measures two figures and hands them to
:func:`forward.reconciliation.reconcile_fill_costs`, which computes the
difference, lands the row and answers with it.  Nothing here re-derives the
difference, and feature 340's own per-rebalance row is still the one
store this module never writes to directly — it is addressed by
``DATABASE_URL``, the same store the rebalance's placements and the
daily-loss halt live in.

**A second, per-order table is this module's own.**  Feature 3 of the VST
fidelity spec — *"System saves each order's final venue state to a new
append-only router_order_fill table at reconciliation, so that every order
of a reconciled slot returns its fill ratio, average price, actual
commission and fill latency"* — is a different grain of the same read-back:
feature 340's row is one figure *per rebalance*, computed only when
something filled, while :data:`ORDER_FILL_TABLE` is one row *per order*,
saved for every order :func:`~router.bingx_orders.read_back_orders`
answers, filled or not.  :func:`save_order_fills` is this module's own
write to its own table (the schema is authored here, the same stance
:mod:`router.submission_result` takes for its own tables), called from
inside :func:`reconcile_rebalance_fill_costs` right after the read-back and
before any of the pricing below, so a slot's per-order facts are saved even
on the path that still answers the per-rebalance reconciliation with
``None``.

**What each figure is.**  For every order the venue reports as *filled* —
``executedQty`` strictly greater than zero — the module reads the executed
quantity and the average price the read-back answered, and prices the fill
against the order's **reference price**:

* the order's own limit price for a passive ``LIMIT`` leg, and
* the symbol's mark price for an aggressive ``MARKET`` leg that carries no
  price of its own.

That is exactly the reference the mirror's own
:func:`router.bingx_mirror.plan_required_margin` reads for the same two
legs, reused rather than re-decided, so the price a fill is reconciled
against is the price the order path already benchmarked it to.

**The reference is what was *placed at*, never a mark re-read here.**  When
the terms come from placement's own record — the scheduled slot's spelling,
and the fix the reconciliation bug spec names — every leg carries the price
the venue was actually asked at: a ``LIMIT``'s limit *after repricing*, and a
``MARKET``'s mark *read in the run that placed it*.  A recorded leg therefore
never falls back to the premiumIndex document, which is fetched only for a
plan's price-less ``MARKET`` leg.  Re-reading a mark at reconciliation time
would price a finished fill against a market the rebalance never traded in —
the very defect this module was fixed for.

The **signed slippage** of one fill is the executed price's distance from
that reference, signed so that *adverse is positive*: a buy that paid above
its reference and a sell that received below it both report a positive
distance, the convention :attr:`cost_model.book_walk.BookWalk.slippage_bps`
and :meth:`cost_model.passive_fill.PassiveFill._signed_past` already speak.
Divided by the reference and multiplied by ten thousand, it is basis
points.  The **fee the order paid** is added to it: ``makerFeeRate`` for a
``LIMIT`` leg (feature 314 posts it ``PostOnly``, so it rests as a maker)
and ``takerFeeRate`` for a ``MARKET`` leg (it crosses as a taker), read
from the contracts document as a fraction and read here in basis points.
The realized cost of the rebalance is those per-order costs *notional
weighted* — each order by ``executedQty × avgPrice``, the notional that
actually traded — and the modeled cost is the very same weighting over the
fee alone, since the cost model's charge for a fill is the fee and nothing
else.  A model that charged no slippage is exactly the optimism feature
340's difference exposes.

**One row's worth of rebalance, or none.**  The orders are read with
feature 3's :func:`router.bingx_orders.read_back_orders`, so a leg the
venue holds no record of is that leg's ``not_found`` status rather than a
fault, a leg a gate refused names no venue order and is skipped, and the
statuses arrive in the plan's order.  A rebalance whose every leg filled
nothing contributes no notional, so there is no fill cost to reconcile:
this module records nothing and answers ``None``, the sentence's *"A
rebalance with no filled order records nothing and returns none"* — the
refusal to persist a figure measured from zero fills being the point, not
an omission.  A rebalance reconciled twice measures the same two figures
from the same fills and hands feature 340 the same pair, which its store
answers with the standing row untouched: *"Reconciling the same rebalance
twice returns the first record unchanged"* is that store's idempotence,
reached by this module measuring deterministically rather than by holding
state of its own.

**The store is feature 340's, reached deferred.**  The ``forward`` member
is imported inside the act, never at module scope, for the reason every
cross-member import in this package is deferred past module scope: the
factory's workspace scan imports this package to fire its ``@register``
with one member's ``src/`` on ``sys.path`` at a time, and a module-scope
import would make this module's importability depend on scan order.  The
store is resolved from ``database_url`` when handed one, else from
``DATABASE_URL``, exactly as the sibling calls in this package resolve
theirs — and a deployment that names neither is refused *by the store*,
not silently answered, because a divergence that went nowhere is the hole
feature 340 exists to close.

**The orders come from where they were *placed*, not from a plan.**  The
sentence says the module reads back *"the rebalance's orders"*; a plan is
not those orders.  A plan is a function of the book, today's positions and
today's marks, so a plan rebuilt at reconciliation time is re-sized against
a world the rebalance never traded in — it drops a leg whose target the
account has since reached, and it carries pre-repricing prices the venue
was never asked at.  So when the caller hands no ``orders`` the act reads
the terms :meth:`~router.submission_result.RouterOrderPlacementStore.record_order`
wrote at *placement* time, addressed by ``(book_id, rebalance_ts)`` — the
side, the type, the size and, above all, the reference price the order was
actually placed at.  That is the scheduled slot's spelling (feature 4 of
the Stage 2 spec) and the fix ``bug_spec_bingx_reconcile_refs.xml`` names.
The ``orders`` parameter stays, and remains the way a caller *holding* the
plan hands it in — the suite's own spelling, and the one a same-process
caller may use.

**The injected client, and no socket.**  ``client`` is feature 1's
:class:`~router.bingx_client.BingXClient` in a deployment and a recording
double in the suite: the read-back walks it per order, and the contracts
and premiumIndex documents are fetched through it too — unless the caller
hands them in, which the suite does with the recorded fixtures and a
rebalance slot with the documents it already read.  Nothing here opens a
socket, reads a credential or consults a clock; the only I/O is the store
feature 340 owns and the placement store the terms are read from, and the
only write is feature 340's one row.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .bingx_client_order_id import project_bingx_client_order_id
from .bingx_documents import RouterMarkPriceError, resolve_bingx_mark_prices
from .bingx_order import (
    BINGX_BUY,
    BINGX_LIMIT_ORDER,
    BINGX_MARKET_ORDER,
    BINGX_ORDER_TYPES,
    BINGX_SIDES,
    BingXRefusedLeg,
)
from .bingx_orders import VSTOrderStatus, read_back_orders
from .errors import RouterError, RouterStoreError

__all__ = [
    "BINGX_RECONCILE_CODE",
    "DATABASE_URL_ENV",
    "MAKER_FEE_RATE_FIELD",
    "ORDER_FILL_TABLE",
    "TAKER_FEE_RATE_FIELD",
    "OrderFill",
    "RouterBingXReconcileError",
    "order_fill_record",
    "reconcile_rebalance_fill_costs",
    "save_order_fills",
]

#: The greppable token every refusal this module raises opens with — coined
#: on the member's own name, the discipline :mod:`router.bingx_orders` and
#: :mod:`router.bingx_order` keep for theirs, so an operator greps one word
#: to find every fault of this act.
BINGX_RECONCILE_CODE = "bingx_reconcile"

#: The contracts document's own field names for the two rates a fill can
#: pay, spelled once because the fee this module charges a leg is *read*
#: from the venue's document rather than hardcoded — the same reason
#: feature 311 forbids a hardcoded venue constant anywhere in this member.
MAKER_FEE_RATE_FIELD = "makerFeeRate"
TAKER_FEE_RATE_FIELD = "takerFeeRate"

#: Basis points per unit of rate or price — the unit every figure this
#: module measures is spoken in, spelled once so the slippage and the fee
#: cannot drift into two different constants.
_BPS_PER_UNIT = Decimal(10_000)

#: The workspace-wide environment variable naming the relational store —
#: restated here rather than imported from :mod:`router.submission_result`,
#: the discipline every store in this member keeps for its own address
#: translation (see :func:`_fill_sqlite_path`).
DATABASE_URL_ENV = "DATABASE_URL"

#: One row per order :func:`read_back_orders` reported, appended once per
#: ``client_order_id`` — the venue's own 40-character projection, the
#: identifier the read-back actually looked the order up by.  This is the
#: table the module docstring's companion sentence (feature 3 of the VST
#: fidelity spec) names: *"System saves each order's final venue state to a
#: new append-only router_order_fill table at reconciliation."*
ORDER_FILL_TABLE = "router_order_fill"

#: The columns of :data:`ORDER_FILL_TABLE`, in the order every statement
#: below spells them — written once so the INSERT, the SELECT and the value
#: class cannot drift apart on a column order, the failure a positional
#: ``SELECT *`` would invite.
_ORDER_FILL_COLUMNS = (
    "client_order_id, status, original_quantity, executed_quantity, "
    "fill_ratio, avg_price, commission, commission_bps, placed_ms, "
    "last_fill_ms, place_to_fill_ms, read_at"
)

_ORDER_FILL_SCHEMA = f"""
-- Feature 3 of the VST fidelity spec: one row per order the read-back
-- reported at reconciliation, holding the venue's final state for it —
-- its fill ratio, its average price, the commission it actually paid and
-- how long it took to fill.  Decimals the venue reports are kept as TEXT in
-- their exact spelling (the discipline every store in this member keeps);
-- the ratios and the commission rate this module *computes* are REAL,
-- exactly as :func:`reconcile_rebalance_fill_costs` already stores its own
-- computed bps figures as floats rather than as text.  PRIMARY KEY makes
-- the "once per client_order_id" law a fact of the schema, not only of the
-- insert below, for the reason this member always states it: SQLite
-- accepts a raw INSERT from any tool.
CREATE TABLE IF NOT EXISTS {ORDER_FILL_TABLE} (
    client_order_id   TEXT NOT NULL PRIMARY KEY,
    status            TEXT NOT NULL,
    original_quantity TEXT,
    executed_quantity TEXT,
    fill_ratio        REAL NOT NULL,
    avg_price         TEXT,
    commission        TEXT,
    commission_bps    REAL,
    placed_ms         INTEGER,
    last_fill_ms      INTEGER,
    place_to_fill_ms  INTEGER,
    read_at           TEXT NOT NULL
);
"""

#: The one write this module makes to the table: claim the key iff it has
#: no row yet — the same ``WHERE NOT EXISTS`` shape
#: :mod:`router.submission_result` uses for its own append-only tables, and
#: for the same reason: the check and the claim are one statement, so a
#: re-read of an already-reconciled order changes nothing.
_ORDER_FILL_INSERT_SQL = f"""
INSERT INTO {ORDER_FILL_TABLE} ({_ORDER_FILL_COLUMNS})
SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM {ORDER_FILL_TABLE} WHERE client_order_id = ?
)
"""

_ORDER_FILL_READ_SQL = f"""
SELECT {_ORDER_FILL_COLUMNS}
FROM {ORDER_FILL_TABLE}
WHERE client_order_id = ?
"""


class RouterBingXReconcileError(RouterError):
    """A fill-cost reconciliation this module cannot compute.

    Raised for a fault of the *ask* rather than a fact about a fill: a plan
    leg that names no order or states no side or type, a ``LIMIT`` leg with
    no readable price, a contracts document that states no fee for a filled
    symbol, or a reconciliation that cannot be computed from what was
    handed over.  A refused reconciliation is better than a persisted one
    measured from an invented reference or a defaulted fee, because feature
    340's difference is read by β₄'s recalibration and by §16's live metric
    and a figure nobody can trust there is worse than an absent one.

    Every message opens with :data:`BINGX_RECONCILE_CODE` and names the one
    repair.  The venue's own refusals — a transport failure, a rejected
    signature — keep feature 1's classes and propagate unchanged, and the
    store's own refusals keep feature 340's classes and propagate too: this
    class is only for the faults this act adds.
    """


@dataclass(frozen=True)
class _PlanLeg:
    """One plan leg this module needs to price a fill: its terms, not its
    price.

    The venue's read-back answers a status per ``clientOrderID`` but carries
    no order *type* and no reference *price* — the two terms a fill's
    reference price and fee are read from.  Those terms travel either on the
    plan the order path built or on the record placement wrote, so this value
    is that leg's terms and is keyed by the identifier the read-back answers
    under: the symbol, the side, the venue's order type, and the reference
    price when it is known *without* a document.

    ``reference`` is the price a fill's slippage is measured against, held
    only when the leg carries it itself: a plan's ``LIMIT`` leg holds its own
    limit price, and a **recorded** leg holds the price the venue was
    actually asked at — the limit after repricing, or the mark read in the
    run that placed a ``MARKET`` order.  It is ``None`` only for a *plan's*
    ``MARKET`` leg, which carries no price of its own, so the caller-holding-
    the-plan spelling still reads that symbol's mark at reconcile time.  A
    recorded leg never needs that read: its reference is a fact placement
    wrote down, and re-reading a mark here would price a finished fill
    against a market the rebalance never traded in — the defect the
    reconciliation bug spec names.
    """

    client_order_id: str
    symbol: str
    side: str
    type: str
    reference: Decimal | None


def _rebalance_instant(value: Any) -> datetime:
    """Return ``value`` as a timezone-aware instant, from a datetime or ISO text.

    The book file carries its ``rebalance_ts`` as an ISO 8601 string
    (``"2026-09-30T00:00:00+00:00"``), while a caller that built the instant
    in memory hands a :class:`~datetime.datetime`; both are the same fact and
    both are read here, so the rebalance's identity is the pair the book
    states rather than whichever spelling a caller happened to hold.  A
    string is parsed before anything is read or written; a naive or
    unparsable value is refused up front with this module's own code word,
    naming the value, so a value that would otherwise surface deep inside the
    forward member's store is refused here instead.
    """

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: rebalance_ts={value!r} is not an ISO "
                "8601 instant; the rebalance's instant is the second half of "
                "the pair (book_id, rebalance_ts) that names the rebalance "
                "being reconciled, and a string that will not parse names no "
                "rebalance (feature 3)"
            ) from exc
    if not isinstance(value, datetime):
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: rebalance_ts must be a datetime or an "
            f"ISO 8601 string, got {value!r} ({type(value).__name__}); the "
            "reconcile is addressed by the rebalance's instant, and a value "
            "that names no instant names no rebalance to reconcile (feature 3)"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: rebalance_ts={value!r} names no "
            "timezone; a naive instant folds into the rebalance's identity an "
            "offset nobody agreed on, and one rebalance would read as two "
            "(feature 3)"
        )
    return value.astimezone(UTC)


@dataclass(frozen=True)
class _LiteralOrder:
    """One recorded placement, shaped as the leg the read-back consumes.

    The recorded terms (see
    :class:`~router.submission_result.OrderRecord`) read into the same
    ``symbol`` / ``client_order_id`` surface a
    :class:`~router.bingx_order.BingXOrder` carries, so
    :func:`read_back_orders` looks each order up by the identifier it was
    recorded under — the full 64-hex key, which is *not* the venue's
    40-character projection and is exactly what the venue's own read-back
    accepts.
    """

    client_order_id: str
    symbol: str


def _recorded_orders(
    *,
    database_url: str | None,
    env: Mapping[str, str] | None,
    book_id: Any,
    rebalance_ts: datetime,
) -> Sequence[Any]:
    """The rebalance's recorded placements, or refuse a store that cannot answer.

    Reads :meth:`~router.submission_result.RouterOrderPlacementStore.records_for`
    — the terms placement wrote when it sent each order — addressed by the
    rebalance's own identity.  The store is resolved from ``database_url``,
    else ``DATABASE_URL``, exactly as :func:`_forward_reconcile` resolves its
    own; a deployment that names neither is refused by the store itself.  The
    import is deferred past module scope for the same reason every
    cross-member import in this package is: a module never imports a sibling
    at import time, so scan order cannot decide whether this module loads.
    """

    try:
        from .submission_result import RouterOrderPlacementStore
    except ModuleNotFoundError as exc:  # pragma: no cover - same package
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the rebalance's recorded placements are "
            "read from router.submission_result, which is not importable in "
            "this environment (feature 3)"
        ) from exc
    store = RouterOrderPlacementStore.resolve(env) if database_url is None else (
        RouterOrderPlacementStore(database_url)
    )
    if store is None:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: a rebalance is reconciled from the terms "
            "placement recorded, and neither database_url nor "
            "DATABASE_URL names the store they were written to; set "
            "DATABASE_URL to the store the router places orders in, or hand "
            "the plan's legs as `orders` (feature 3)"
        )
    return store.records_for(book_id, rebalance_ts)


def _require_callable(client: Any, name: str) -> Any:
    """Return ``client``'s callable ``name``, or refuse a client lacking it."""

    method = getattr(client, name, None)
    if not callable(method):
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the injected client exposes no "
            f"callable {name}(); this act reads the rebalance's orders back "
            "through feature 1's client and fetches the venue's contracts "
            "and premiumIndex documents through it, and a client without "
            "this method cannot be asked (feature 3)"
        )
    return method


def _document(fetched: Any) -> Mapping:
    """A fetched payload as the document shape Stage 0's readers read.

    Feature 1's client answers the venue envelope's ``data`` field — the
    list of contract rows or mark rows — while
    :func:`router.bingx_documents.resolve_bingx_mark_prices` (and this
    module's own fee reader) read the *documents* Stage 0 is handed, which
    carry that list under ``data``.  The gap is the envelope the client
    already unwrapped, so this rejoins it: a payload that is already a
    document (a mapping carrying ``data``) passes through untouched — the
    shape a recorded read answers — and a bare list is wrapped under
    ``data``.  The envelope's ``code`` is deliberately not restated: the
    client owns the venue's answer, and inventing one here would be a fact
    this module has no basis for.
    """

    if isinstance(fetched, Mapping):
        return fetched
    return {"data": fetched}


def _rows(document: Any, what: str) -> list[Any]:
    """The ``data`` list of a venue document, or a refusal naming it."""

    if isinstance(document, (bytes, bytearray, str)):
        try:
            document = json.loads(document)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: the {what} document is not JSON: "
                f"{exc}; a fill's fee and reference price are read from the "
                "venue's own documents, and a document that cannot be read "
                "cannot price one (feature 3)"
            ) from exc
    rows = document.get("data") if isinstance(document, Mapping) else document
    if isinstance(rows, list):
        return rows
    raise RouterBingXReconcileError(
        f"{BINGX_RECONCILE_CODE}: the {what} document carries no 'data' "
        f"list (got {type(rows).__name__}); refused rather than read as an "
        "empty result, because a malformed fetch and a venue with nothing "
        "to say must not look alike (feature 3)"
    )


def _rate(value: Any, field: str, symbol: str) -> Decimal:
    """One contracts-document rate as an exact non-negative Decimal, or refuse.

    The venue publishes the two rates as JSON numbers —
    ``"makerFeeRate": 0.0002`` — so a ``str``, an ``int`` and a JSON
    ``float`` are all read, the float through its own shortest spelling
    (``str(0.0002)`` is ``'0.0002'``), the discipline
    :func:`router.bingx_documents._decimal_field` already keeps for the same
    document: ``json.loads`` reads a JSON number exactly when the document
    spells it exactly, so the shortest spelling recovers the decimal the
    venue sent rather than a binary approximation of it.  A boolean, an
    absent field or a non-finite value is refused — a fee this module could
    not read is never defaulted to zero, because feature 311 forbids a
    hardcoded venue constant.
    """

    if isinstance(value, bool) or value is None:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the contracts document states no "
            f"readable {field} for {symbol!r} (got {value!r}); a fill's fee "
            "is the rate the venue publishes for its symbol, and a rate "
            "this module defaulted would be a hardcoded venue constant "
            "(feature 3)"
        )
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (str, int, float)):
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: the contracts document states "
                f"{field}={value!r} for {symbol!r}, which is not a decimal "
                "(feature 3)"
            ) from exc
    else:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the contracts document states "
            f"{field}={value!r} ({type(value).__name__}) for {symbol!r}; a "
            "fee rate is an exact decimal, and a value that is not one "
            "cannot be read into the fee a fill paid (feature 3)"
        )
    if not number.is_finite() or number < 0:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the contracts document states "
            f"{field}={value!r} for {symbol!r}; a fee rate is finite and "
            "non-negative, and a rate that is not is not one a venue "
            "charges (feature 3)"
        )
    return number


def _contract_fee_rates(document: Any) -> dict[str, tuple[Decimal, Decimal]]:
    """The contracts document's ``(maker, taker)`` rate per symbol.

    One entry per contract row — the maker and taker rates the venue
    publishes for that symbol, as exact Decimals in the fraction the
    document states (``0.0002`` is two basis points).  A row naming no
    symbol, or stating neither rate, is refused by name: a filled leg whose
    symbol the document does not price cannot have its fee read, and the
    honest answer is the refusal rather than a defaulted zero.
    """

    rates: dict[str, tuple[Decimal, Decimal]] = {}
    for index, row in enumerate(_rows(document, "BingX contracts")):
        if not isinstance(row, Mapping):
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: the contracts document carries a "
                f"non-object row at index {index} "
                f"({type(row).__name__}); every row of this document is one "
                "contract's terms (feature 3)"
            )
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: contracts row {index} names no "
                f"symbol (got {symbol!r}); every row of this document is "
                "about one contract, and a row naming nothing cannot price "
                "a fill (feature 3)"
            )
        name = symbol.strip()
        rates[name] = (
            _rate(row.get(MAKER_FEE_RATE_FIELD), MAKER_FEE_RATE_FIELD, name),
            _rate(row.get(TAKER_FEE_RATE_FIELD), TAKER_FEE_RATE_FIELD, name),
        )
    return rates


def _leg_price(value: Any, symbol: str) -> Decimal:
    """A ``LIMIT`` leg's own price as an exact positive Decimal, or refuse.

    Read the same way as a document's decimal — a ``str`` (the venue's own
    spelling, and what a plan leg carries), an ``int`` or a JSON ``float``
    through its shortest spelling — so a plan read from a written file and a
    plan built in memory price a fill identically.
    """

    if isinstance(value, Decimal):
        number: Decimal | None = value
    elif isinstance(value, bool) or value is None:
        number = None
    elif isinstance(value, (str, int, float)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            number = None
    else:
        number = None
    if number is None or not number.is_finite() or number <= 0:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the LIMIT leg for {symbol!r} carries "
            f"no readable price (got {value!r}); a passive order's fill is "
            "measured against the price it was placed at, and a leg that "
            "names none names no reference to measure against (feature 3)"
        )
    return number


def _plan_legs(orders: Any) -> list[_PlanLeg]:
    """The plan's legs as :class:`_PlanLeg` values, in the order handed.

    ``orders`` is the plan the order path built — a sequence of
    :class:`~router.bingx_order.BingXOrder` values, or any iterable of
    values carrying the same terms (a mapping in the venue's own spellings,
    the shape a written plan holds).  A
    :class:`~router.bingx_order.BingXRefusedLeg` is skipped: a refused leg
    is one the gates closed and names no venue order, so it is not the
    read-back's business and not this act's.  Anything else is a fault of
    the ask, refused naming the item, because a leg that cannot be read
    would silently drop a fill from the reconciliation.
    """

    if orders is None or isinstance(orders, (str, bytes)) or not isinstance(
        orders, Iterable
    ):
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the rebalance's orders are an iterable "
            f"of plan legs, got {orders!r} ({type(orders).__name__}); the "
            "read-back walks the legs the plan produced, and a value that "
            "is not a collection of them names nothing to reconcile "
            "(feature 3)"
        )
    legs: list[_PlanLeg] = []
    for item in orders:
        if isinstance(item, BingXRefusedLeg):
            continue
        if isinstance(item, Mapping):
            symbol = item.get("symbol")
            identifier = item.get(
                "clientOrderID", item.get("client_order_id")
            )
            side = item.get("side")
            kind = item.get("type", item.get("order_type"))
            price = item.get("price")
        else:
            symbol = getattr(item, "symbol", None)
            identifier = getattr(item, "client_order_id", None)
            side = getattr(item, "side", None)
            kind = getattr(item, "type", None)
            price = getattr(item, "price", None)
        if not isinstance(identifier, str) or not identifier.strip():
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: a leg of the rebalance names no "
                f"order — expected a plan leg carrying a clientOrderID, got "
                f"{item!r} ({type(item).__name__}); an item that names no "
                "order has no fill to reconcile (feature 3)"
            )
        if not isinstance(symbol, str) or not symbol.strip():
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: the leg named by {identifier!r} "
                f"names no symbol (got {symbol!r}); a fill is priced against "
                "its symbol's own reference, and a leg naming none names no "
                "reference (feature 3)"
            )
        if side not in BINGX_SIDES:
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: the leg named by {identifier!r} "
                f"states side={side!r} ({type(side).__name__}); a fill's "
                "signed slippage is adverse-positive only against a known "
                "side, and a side outside the venue's vocabulary is one no "
                "order was placed with (feature 3)"
            )
        if kind not in BINGX_ORDER_TYPES:
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: the leg named by {identifier!r} "
                f"states type={kind!r} ({type(kind).__name__}); the fee a "
                "fill paid is the maker rate for a LIMIT leg and the taker "
                "rate for a MARKET leg, and a type outside that pair names "
                "neither (feature 3)"
            )
        name = symbol.strip()
        legs.append(
            _PlanLeg(
                client_order_id=identifier.strip(),
                symbol=name,
                side=side,
                type=kind,
                reference=(
                    _leg_price(price, name)
                    if kind == BINGX_LIMIT_ORDER
                    else None
                ),
            )
        )
    return legs


def _fee_bps(
    leg: _PlanLeg, rates: dict[str, tuple[Decimal, Decimal]]
) -> Decimal:
    """The fee, in basis points, the filled ``leg`` paid.

    The maker rate for a ``LIMIT`` leg and the taker rate for a ``MARKET``
    leg, from the contracts document — the sentence's own rule.  A symbol
    the document does not price is refused by name, because a fee this
    module defaulted would be the hardcoded venue constant feature 311
    forbids.
    """

    pair = rates.get(leg.symbol)
    if pair is None:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the contracts document prices no "
            f"contract for {leg.symbol!r}, whose order {leg.client_order_id!r} "
            "filled; a fill's fee is the rate the venue publishes for its "
            "symbol, and a document that prices no contract for it cannot "
            "be asked what the fill paid (feature 3)"
        )
    maker, taker = pair
    rate = maker if leg.type == BINGX_LIMIT_ORDER else taker
    return rate * _BPS_PER_UNIT


def _forward_reconcile():
    """The store's ``reconcile_fill_costs``, imported deferred.

    The ``forward`` member is reached inside the act, never at module
    scope, for the reason every cross-member import in this package is
    deferred past module scope (see the module docstring).  A member that
    is not importable is named rather than shown as a bare ImportError.
    """

    try:
        from forward.reconciliation import reconcile_fill_costs
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the fill-cost reconciliation is "
            "recorded through the forward member "
            "(forward.reconciliation.reconcile_fill_costs), and that member "
            "is not importable in this environment; run `uv sync "
            "--all-packages` in the workspace root (or put "
            "packages/forward/src on sys.path) so the store feature 340 "
            "declares can be reached (feature 3)"
        ) from exc
    return reconcile_fill_costs


@dataclass(frozen=True)
class OrderFill:
    """One row of :data:`ORDER_FILL_TABLE` — an order's final venue state.

    What :func:`save_order_fills` wrote for one ``client_order_id`` (the
    venue's own 40-character projection, the identifier
    :func:`~router.bingx_orders.read_back_orders` looked the order up by):
    the venue's status, its two measurements and the two figures this
    module derives from them (:attr:`fill_ratio`, :attr:`commission_bps`),
    its commission as the venue reported it, its two venue instants and
    their difference (:attr:`place_to_fill_ms`), and when this row was
    saved.  Every field mirrors the same-named attribute of
    :class:`~router.bingx_orders.VSTOrderStatus` (``avg_price`` beside that
    class's ``average_price``), so a caller reading this row back reads the
    same facts the read-back answered, plus the one fact only the store
    knows: ``read_at``.
    """

    client_order_id: str
    status: str
    original_quantity: Decimal | None
    executed_quantity: Decimal | None
    fill_ratio: float
    avg_price: Decimal | None
    commission: Decimal | None
    commission_bps: float | None
    placed_ms: int | None
    last_fill_ms: int | None
    place_to_fill_ms: int | None
    read_at: datetime


def _require_fill_database_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The store's address from ``database_url``, else ``DATABASE_URL``.

    The same resolution :func:`_recorded_orders` takes of its own store —
    an explicit value wins, else the environment (``env`` when handed one,
    else ``os.environ``) — refused by name when neither names a store: a
    reconciled order's final venue state going nowhere is exactly the hole
    this feature closes, so it is not a silent no-op.
    """

    if database_url is not None:
        url = database_url.strip()
    else:
        source = os.environ if env is None else env
        url = source.get(DATABASE_URL_ENV, "").strip()
    if not url:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: an order's final venue state is saved "
            f"to {ORDER_FILL_TABLE}, and neither database_url nor "
            f"{DATABASE_URL_ENV} names the store to save it in; set "
            f"{DATABASE_URL_ENV} to the store the router places orders in "
            "(feature 3)"
        )
    return url


def _fill_sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :func:`router.submission_result._sqlite_path`
    states, in this module's own words, for the reason every store in this
    workspace restates it: a store reaches into no sibling's private
    helper, so a later change to one table's address handling cannot
    silently move another's.  ``sqlite:///foo.db`` is relative,
    ``sqlite:////foo.db`` is absolute, and any other scheme is refused by
    name.
    """

    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: unsupported {DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}; the order-fill store speaks sqlite:/// "
            "(feature 3)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: sqlite {DATABASE_URL_ENV} must not "
            f"carry a host, got {parsed.netloc!r} (feature 3)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: sqlite {DATABASE_URL_ENV} carries no "
            "database path (feature 3)"
        )
    return Path(path)


def _decimal_text_or_none(value: Decimal | None) -> str | None:
    """Render a :class:`~decimal.Decimal` in plain positional notation, or
    ``None``.

    The same rendering :func:`router.submission_result._decimal_text`
    gives its own tables, for the same reason: ``str(Decimal("1E+3"))`` is
    ``'1E+3'``, which an operator at a sqlite prompt would not read as one
    thousand, while ``format(value, 'f')`` renders the venue's own spelling.
    """

    return None if value is None else format(value, "f")


def _require_read_at(now: Any) -> datetime:
    """Return ``now`` as a timezone-aware instant, or the wall clock.

    The one moment this module's own write stamps a row with — never an
    identity, only a label of when it was saved — so a naive value is
    refused by name rather than silently misdating every row it touches.
    """

    if now is None:
        return datetime.now(UTC)
    if not isinstance(now, datetime):
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: now must be a datetime, got {now!r} "
            f"({type(now).__name__}) (feature 3)"
        )
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: now={now!r} names no timezone; a "
            "naive instant folds into the saved row an offset nobody "
            "agreed on (feature 3)"
        )
    return now.astimezone(UTC)


def _order_fill_from_status(status: VSTOrderStatus, *, read_at: datetime) -> OrderFill:
    """One :class:`VSTOrderStatus` as the row this module saves for it."""

    return OrderFill(
        client_order_id=status.client_order_id,
        status=status.status,
        original_quantity=status.original_quantity,
        executed_quantity=status.executed_quantity,
        fill_ratio=status.fill_ratio,
        avg_price=status.average_price,
        commission=status.commission,
        commission_bps=status.commission_bps,
        placed_ms=status.placed_ms,
        last_fill_ms=status.last_fill_ms,
        place_to_fill_ms=status.place_to_fill_ms,
        read_at=read_at,
    )


def _order_fill_from_row(row: tuple) -> OrderFill:
    """Rebuild one stored row, refusing a value no fill record can be.

    The same stance :mod:`router.submission_result`'s own row readers take:
    this table is writable by any tool and SQLite columns are dynamically
    typed, so a raw ``INSERT`` can land a ``read_at`` no parser accepts.
    The refusal names the row's key so an operator can find it.
    """

    (
        client_order_id,
        status,
        original_quantity_raw,
        executed_quantity_raw,
        fill_ratio,
        avg_price_raw,
        commission_raw,
        commission_bps,
        placed_ms,
        last_fill_ms,
        place_to_fill_ms,
        read_at_raw,
    ) = row

    def _decimal_or_none(value: Any, field: str) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: the fill saved for order "
                f"{client_order_id!r} carries {field}={value!r}, which is "
                "not a decimal (feature 3)"
            ) from exc

    try:
        read_at = datetime.fromisoformat(read_at_raw)
    except (TypeError, ValueError) as exc:
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: the fill saved for order "
            f"{client_order_id!r} carries read_at={read_at_raw!r}, which is "
            "not an ISO 8601 moment (feature 3)"
        ) from exc
    return OrderFill(
        client_order_id=client_order_id,
        status=status,
        original_quantity=_decimal_or_none(original_quantity_raw, "original_quantity"),
        executed_quantity=_decimal_or_none(executed_quantity_raw, "executed_quantity"),
        fill_ratio=fill_ratio,
        avg_price=_decimal_or_none(avg_price_raw, "avg_price"),
        commission=_decimal_or_none(commission_raw, "commission"),
        commission_bps=commission_bps,
        placed_ms=placed_ms,
        last_fill_ms=last_fill_ms,
        place_to_fill_ms=place_to_fill_ms,
        read_at=read_at,
    )


def save_order_fills(
    statuses: Sequence[VSTOrderStatus],
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> tuple[OrderFill, ...]:
    """Save each of ``statuses`` to :data:`ORDER_FILL_TABLE`, once each.

    The write the module docstring's companion sentence names: *"System
    saves each order's final venue state to a new append-only
    router_order_fill table at reconciliation."*  ``statuses`` is what
    :func:`~router.bingx_orders.read_back_orders` answered — every order of
    the reconciled slot, filled or not — and each is saved under its own
    ``client_order_id`` exactly once: a key that already has a row is left
    untouched, so a slot reconciled twice (or an order whose remaining
    quantity the next slot's step 2 later cancels) never overwrites the
    partial fill this call already recorded.  An empty ``statuses`` saves
    nothing and touches no store at all.

    ``database_url``, else ``DATABASE_URL`` (read from ``env`` when handed
    one, else ``os.environ``), names the store — refused by name when
    neither does, because an order's final state going nowhere is the hole
    this feature exists to close.  ``now`` stamps every row's ``read_at``
    and defaults to the wall clock; a naive value is refused.

    Returns the row saved for each status, in the order handed in — the row
    that now stands, which is the fresh write on a first save and the prior
    row, untouched, on a re-read.

    Refuses :class:`RouterBingXReconcileError` for a malformed address or a
    naive ``now``, and fails with
    :class:`~router.errors.RouterStoreError` when the store could not take
    or read back a row.
    """

    if not statuses:
        return ()
    read_at = _require_read_at(now)
    url = _require_fill_database_url(database_url, env)
    path = _fill_sqlite_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    saved: list[OrderFill] = []
    try:
        connection = sqlite3.connect(path)
    except sqlite3.OperationalError as exc:
        raise RouterStoreError(
            f"could not open the {ORDER_FILL_TABLE} store at {path}: {exc}"
        ) from exc
    try:
        with connection:
            connection.executescript(_ORDER_FILL_SCHEMA)
        for status in statuses:
            fill = _order_fill_from_status(status, read_at=read_at)
            try:
                with connection:
                    connection.execute(
                        _ORDER_FILL_INSERT_SQL,
                        (
                            fill.client_order_id,
                            fill.status,
                            _decimal_text_or_none(fill.original_quantity),
                            _decimal_text_or_none(fill.executed_quantity),
                            fill.fill_ratio,
                            _decimal_text_or_none(fill.avg_price),
                            _decimal_text_or_none(fill.commission),
                            fill.commission_bps,
                            fill.placed_ms,
                            fill.last_fill_ms,
                            fill.place_to_fill_ms,
                            fill.read_at.isoformat(),
                            fill.client_order_id,
                        ),
                    )
                row = connection.execute(
                    _ORDER_FILL_READ_SQL, (fill.client_order_id,)
                ).fetchone()
            except sqlite3.Error as exc:
                raise RouterStoreError(
                    f"could not save the fill reconciled for order "
                    f"{fill.client_order_id}: {exc}"
                ) from exc
            if row is None:  # pragma: no cover - written on the same connection
                raise RouterStoreError(
                    f"the fill for order {fill.client_order_id} was saved "
                    "and could not be read back in the transaction that "
                    "wrote it (feature 3)"
                )
            saved.append(_order_fill_from_row(row))
    finally:
        connection.close()
    return tuple(saved)


def order_fill_record(
    client_order_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> OrderFill | None:
    """The :data:`ORDER_FILL_TABLE` row saved for ``client_order_id``, or ``None``.

    The read a caller takes when it holds the identifier
    :func:`~router.bingx_orders.read_back_orders` looked an order up by and
    wants the row :func:`save_order_fills` landed for it.  ``None`` is the
    honest answer for an order this table has never recorded — including
    when the store itself has never been created.
    """

    if not isinstance(client_order_id, str) or not client_order_id.strip():
        raise RouterBingXReconcileError(
            f"{BINGX_RECONCILE_CODE}: client_order_id must be non-empty "
            f"text, got {client_order_id!r} (feature 3)"
        )
    key = client_order_id.strip()
    url = _require_fill_database_url(database_url, env)
    path = _fill_sqlite_path(url)
    if not path.exists():
        return None
    try:
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.executescript(_ORDER_FILL_SCHEMA)
            row = connection.execute(_ORDER_FILL_READ_SQL, (key,)).fetchone()
    except (sqlite3.Error, OSError) as exc:
        raise RouterStoreError(
            f"could not read the {ORDER_FILL_TABLE} row for order {key}: {exc}"
        ) from exc
    if row is None:
        return None
    return _order_fill_from_row(row)


def reconcile_rebalance_fill_costs(
    *,
    client: Any,
    book_id: Any,
    rebalance_ts: Any,
    orders: Any = None,
    contracts: Any = None,
    marks: Any = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> Any:
    """Reconcile one finished rebalance's fill costs, or answer ``None``.

    Feature 3's one act: read the rebalance's orders back through feature 3's
    :func:`router.bingx_orders.read_back_orders`, price every filled order's
    signed slippage against its reference price and add the fee it paid,
    notional-weight the two per-order costs into the rebalance's realized
    and modeled figures in basis points, and record both through
    :func:`forward.reconciliation.reconcile_fill_costs` — answering the
    recorded reconciliation.  The steps, in the order they must happen:

    0. **Save every order's venue state** — right after step 2 below reads
       the orders back, each :class:`~router.bingx_orders.VSTOrderStatus` is
       saved to :data:`ORDER_FILL_TABLE` through :func:`save_order_fills`,
       once per ``client_order_id``: every order of this slot, filled or
       not, so a PENDING order's fill ratio is recorded as zero rather than
       left unrecorded.  This happens before any refusal below can stop the
       function short, and before this function's own early return for a
       slot with no filled notional — the per-order save and the per-slot
       cost reconciliation are two different facts with two different
       conditions for existing.
    1. **Read the rebalance's terms** — with ``orders`` handed in, the
       plan's legs (symbols, sides, types and limit prices), refused by name
       where a leg cannot be read; with no ``orders``, the terms placement
       recorded, each leg carrying the reference price the venue was actually
       asked at.
    2. **Read the orders back** — feature 3's verb, over the same legs, so a
       leg the venue holds no record of is that leg's ``not_found`` and a
       refused leg is skipped.
    3. **Price the fills** — for each order the venue reports with an
       ``executedQty`` strictly greater than zero, its signed slippage in
       basis points (adverse positive) plus its fee in basis points, and the
       notional it traded at.  A leg's reference is what its terms carry: a
       ``LIMIT`` leg's limit price and any *recorded* leg's reference (the
       limit actually sent after repricing, or the mark read in the run that
       placed a ``MARKET`` order).  Only a plan's price-less ``MARKET`` leg
       falls back to its symbol's mark, read from the premiumIndex document —
       fetched through the client, unless ``marks`` names one — and only when
       such a filled leg needs it.
    4. **Weight and record** — the notional-weighted mean of
       ``slippage + fee`` is ``realized_cost_bps`` and of ``fee`` alone is
       ``modeled_cost_bps``; both are handed to feature 340's store, which
       computes the difference and lands the row.  No filled notional means
       no fill cost: nothing is recorded and ``None`` is answered.

    ``contracts`` and ``marks`` are the venue's own documents; when
    ``contracts`` is ``None`` it is fetched through ``client.contracts()``,
    and when ``marks`` is ``None`` and a filled ``MARKET`` leg needs one it
    is fetched through ``client.premium_index()`` — so a rebalance slot may
    hand in the documents it already read, and the suite hands in the
    recorded fixtures.  ``database_url``, else ``DATABASE_URL``, names the
    store, exactly as feature 340's own seam resolves it: a deployment that
    names neither is refused by that store rather than silently answered —
    and the same resolution now also gates step 0's save.  ``now`` stamps
    every saved fill's ``read_at`` and defaults to the wall clock.

    Refuses :class:`RouterBingXReconcileError` for the faults this act adds
    — a leg that names no order, a contracts document that prices no fee
    for a filled symbol, a ``MARKET`` leg whose symbol no mark prices.  The
    venue's own refusals keep feature 1's classes and propagate unchanged,
    and the store's keep feature 340's.
    """

    instant = _rebalance_instant(rebalance_ts)
    if orders is None:
        # The scheduled slot's spelling, and the one a *later* process must
        # use: the rebalance's orders and their reference prices are read back
        # from what placement recorded, never from a plan rebuilt today —
        # today's plan is re-sized against today's positions and marks, so it
        # neither lists every order the rebalance placed nor carries the
        # prices the venue was asked at.  A rebalance with no recorded terms
        # is not an error: it was never placed by a run that recorded, so
        # there is nothing to reconcile and ``None`` is the honest answer.
        records = _recorded_orders(
            database_url=database_url,
            env=env,
            book_id=book_id,
            rebalance_ts=instant,
        )
        if not records:
            return None
        # The venue addresses an order by feature 3's 40-character
        # projection of the recorded 64-hex key, so both the legs and the
        # read-back are keyed by that projection: the read-back echoes it
        # back, and the pricing loop joins the two on one spelling.
        legs = [
            _PlanLeg(
                client_order_id=project_bingx_client_order_id(
                    record.client_order_id
                ),
                symbol=record.symbol,
                side=record.side,
                type=record.type,
                # The reference placement recorded for *every* leg — the
                # limit actually sent after repricing, or the mark read in
                # the run that placed a MARKET order.  Never re-derived here:
                # the whole point of recording the terms is that a finished
                # fill is priced against what it was placed at, not against a
                # mark re-read in a later process.
                reference=record.reference_price,
            )
            for record in records
        ]
        read_back = [
            _LiteralOrder(
                client_order_id=project_bingx_client_order_id(
                    record.client_order_id
                ),
                symbol=record.symbol,
            )
            for record in records
        ]
    else:
        legs = _plan_legs(orders)
        read_back = list(orders)
    statuses = read_back_orders(client=client, orders=read_back)
    # Feature 3 of the VST fidelity spec: every order of this reconciled
    # slot — filled or not — is saved to router_order_fill right here,
    # before any downstream refusal (a contracts document pricing no fee,
    # say) can stop this function short.  A partially filled order's
    # executedQty is exactly what the venue reports even after it is later
    # cancelled, so this capture is correct whether or not the next slot's
    # step 2 has already cancelled the remainder.
    save_order_fills(statuses, database_url=database_url, env=env, now=now)
    by_id = {status.client_order_id: status for status in statuses}

    # Every read uses the rebalance's *parsed* instant, so a caller that
    # handed the book's own ISO string and one that built the datetime read
    # and write the identical row.
    rebalance_ts = instant

    if contracts is None:
        contracts = _require_callable(client, "contracts")()
    rates = _contract_fee_rates(_document(contracts))

    # Only a filled MARKET leg that carries no reference of its own needs a
    # mark; read the document lazily, as plan_required_margin does, so an
    # all-passive rebalance — and a rebalance reconciled from placement's own
    # records, every leg of which carries its reference — costs the client
    # nothing beyond the read-back it already did.  The document is reached
    # only for a *plan's* MARKET leg, whose limit-free terms carry no price.
    market_symbols = sorted(
        {
            leg.symbol
            for leg in legs
            if leg.type == BINGX_MARKET_ORDER
            and leg.reference is None
            and (status := by_id.get(leg.client_order_id)) is not None
            and status.executed_quantity is not None
            and status.executed_quantity > 0
        }
    )
    mark_prices: dict[str, Decimal] = {}
    if market_symbols:
        document = marks
        if document is None:
            document = _require_callable(client, "premium_index")()
        try:
            mark_prices = resolve_bingx_mark_prices(
                _document(document), market_symbols
            )
        except RouterMarkPriceError as refusal:
            raise RouterBingXReconcileError(
                f"{BINGX_RECONCILE_CODE}: the venue's premiumIndex document "
                f"states no mark price for {refusal.symbol!r}; a MARKET "
                "leg's fill is measured against its symbol's mark, and a "
                "leg that traded cannot be reconciled against a reference "
                "the document does not state (feature 3)"
            ) from refusal
        for symbol, mark in mark_prices.items():
            if mark <= 0:
                # A mark of zero (or a negative one) is a measurement the
                # slippage is a *fraction* of: dividing by it is a fault of
                # the ask's reference, refused by name rather than raised as
                # a bare ZeroDivisionError from the middle of the pricing
                # loop, exactly as a LIMIT leg's non-positive price is.
                raise RouterBingXReconcileError(
                    f"{BINGX_RECONCILE_CODE}: the venue's premiumIndex "
                    f"document states markPrice={mark!r} for {symbol!r}, "
                    "which is not a positive price; a MARKET leg's fill is "
                    "measured as a fraction of its symbol's mark, and a mark "
                    "of zero is no reference to measure one against "
                    "(feature 3)"
                )

    notional_total = Decimal(0)
    realized_total = Decimal(0)
    modeled_total = Decimal(0)
    for leg in legs:
        status = by_id.get(leg.client_order_id)
        if status is None or status.executed_quantity is None:
            continue
        quantity = status.executed_quantity
        average_price = status.average_price
        if quantity <= 0 or average_price is None or average_price <= 0:
            continue
        # The leg's own reference when it carries one — a plan LIMIT's limit
        # price, or any *recorded* leg's reference (the limit actually sent,
        # or the mark read at placement) — else the mark fetched for a plan's
        # price-less MARKET leg.  A recorded leg never falls through to the
        # mark, so a finished fill is never priced against a re-read market.
        reference = (
            leg.reference
            if leg.reference is not None
            else mark_prices[leg.symbol]
        )
        assert reference is not None  # every leg resolves a reference here
        sign = Decimal(1) if leg.side == BINGX_BUY else Decimal(-1)
        slippage_bps = (
            sign * (average_price - reference) / reference * _BPS_PER_UNIT
        )
        fee_bps = _fee_bps(leg, rates)
        notional = quantity * average_price
        notional_total += notional
        realized_total += notional * (slippage_bps + fee_bps)
        modeled_total += notional * fee_bps

    if notional_total == 0:
        # No order filled: there is no fill cost to reconcile, and the
        # sentence says record nothing and answer none.  Returning before
        # the store is reached means a deployment with no database still
        # answers the honest ``None`` for an unfilled rebalance.
        return None

    realized_cost_bps = float(realized_total / notional_total)
    modeled_cost_bps = float(modeled_total / notional_total)
    record = _forward_reconcile()
    return record(
        book_id,
        rebalance_ts=rebalance_ts,
        realized_cost_bps=realized_cost_bps,
        modeled_cost_bps=modeled_cost_bps,
        database_url=database_url,
        env=env,
    )
