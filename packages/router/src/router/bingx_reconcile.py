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
difference, and nothing here writes a row of its own: the one store is the
one feature 340 already declares, addressed by ``DATABASE_URL``, the same
store the rebalance's placements and the daily-loss halt live in.

**What each figure is.**  For every order the venue reports as *filled* —
``executedQty`` strictly greater than zero — the module reads the executed
quantity and the average price the read-back answered, and prices the fill
against the order's **reference price**:

* the order's own limit price for a passive ``LIMIT`` leg, and
* the symbol's mark price for an aggressive ``MARKET`` leg, which carries
  no price of its own.

That is exactly the reference the mirror's own
:func:`router.bingx_mirror.plan_required_margin` reads for the same two
legs, reused rather than re-decided, so the price a fill is reconciled
against is the price the order path already benchmarked it to.

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

**The injected client, and no socket.**  ``client`` is feature 1's
:class:`~router.bingx_client.BingXClient` in a deployment and a recording
double in the suite: the read-back walks it per order, and the contracts
and premiumIndex documents are fetched through it too — unless the caller
hands them in, which the suite does with the recorded fixtures and a
rebalance slot with the documents it already read.  Nothing here opens a
socket, reads a credential or consults a clock; the only I/O is the store
feature 340 owns, and the only write is its one row.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .bingx_documents import RouterMarkPriceError, resolve_bingx_mark_prices
from .bingx_order import (
    BINGX_BUY,
    BINGX_LIMIT_ORDER,
    BINGX_MARKET_ORDER,
    BINGX_ORDER_TYPES,
    BINGX_SIDES,
    BingXRefusedLeg,
)
from .bingx_orders import read_back_orders
from .errors import RouterError

__all__ = [
    "BINGX_RECONCILE_CODE",
    "MAKER_FEE_RATE_FIELD",
    "TAKER_FEE_RATE_FIELD",
    "RouterBingXReconcileError",
    "reconcile_rebalance_fill_costs",
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
    no order *type* and no limit *price* — the two terms a fill's reference
    price and fee are read from.  Those terms travel on the plan the order
    path built, so this value is that leg's terms drawn off the plan and
    keyed by the identifier the read-back answers under: the symbol, the
    side, the venue's order type, and the limit price (``None`` for a
    ``MARKET`` leg, which carries none).
    """

    client_order_id: str
    symbol: str
    side: str
    type: str
    price: Decimal | None


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
                price=(
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


def reconcile_rebalance_fill_costs(
    *,
    client: Any,
    book_id: Any,
    rebalance_ts: Any,
    orders: Any,
    contracts: Any = None,
    marks: Any = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Any:
    """Reconcile one finished rebalance's fill costs, or answer ``None``.

    Feature 3's one act: read the rebalance's orders back through feature 3's
    :func:`router.bingx_orders.read_back_orders`, price every filled order's
    signed slippage against its reference price and add the fee it paid,
    notional-weight the two per-order costs into the rebalance's realized
    and modeled figures in basis points, and record both through
    :func:`forward.reconciliation.reconcile_fill_costs` — answering the
    recorded reconciliation.  The steps, in the order they must happen:

    1. **Read the plan's terms** — the legs' symbols, sides, types and limit
       prices, refused by name where a leg cannot be read.
    2. **Read the orders back** — feature 3's verb, over the same legs, so a
       leg the venue holds no record of is that leg's ``not_found`` and a
       refused leg is skipped.
    3. **Price the fills** — for each order the venue reports with an
       ``executedQty`` strictly greater than zero, its signed slippage in
       basis points (adverse positive) plus its fee in basis points, and the
       notional it traded at.  A ``MARKET`` leg's reference is its symbol's
       mark, read from the premiumIndex document — fetched through the
       client, unless ``marks`` names one — only when a filled ``MARKET``
       leg needs it; a ``LIMIT`` leg's reference is its own limit price.
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
    names neither is refused by that store rather than silently answered.

    Refuses :class:`RouterBingXReconcileError` for the faults this act adds
    — a leg that names no order, a contracts document that prices no fee
    for a filled symbol, a ``MARKET`` leg whose symbol no mark prices.  The
    venue's own refusals keep feature 1's classes and propagate unchanged,
    and the store's keep feature 340's.
    """

    legs = _plan_legs(orders)
    statuses = read_back_orders(client=client, orders=orders)
    by_id = {status.client_order_id: status for status in statuses}

    if contracts is None:
        contracts = _require_callable(client, "contracts")()
    rates = _contract_fee_rates(_document(contracts))

    # Only a filled MARKET leg needs a mark; read the document lazily, as
    # plan_required_margin does, so an all-passive rebalance costs the
    # client nothing beyond the read-back it already did.
    market_symbols = sorted(
        {
            leg.symbol
            for leg in legs
            if leg.type == BINGX_MARKET_ORDER
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
        reference = (
            leg.price
            if leg.type == BINGX_LIMIT_ORDER
            else mark_prices[leg.symbol]
        )
        assert reference is not None  # LIMIT legs carry one; MARKET has a mark
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
