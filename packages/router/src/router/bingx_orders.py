"""Stage 1's order read-back and cancellation — feature 3 of the VST mirror.

``additions_spec_bingx_vst_mirror.xml``, "BingX VST Mirror", feature 3:
*System returns each of the book's VST orders, looked up by clientOrderID,
with its status (NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED or
not_found), its executed quantity and its average price.  Asked to cancel,
it returns the identifiers of the open orders it cancelled: only those whose
clientOrderID belongs to the book's rebalance.  Orders from any other book
or rebalance are left untouched.*

**Two verbs, and the identity is what makes the second one safe.**
:func:`read_back_orders` answers the first sentence: for each of the book's
orders it asks the venue by that order's ``clientOrderID`` and folds the
answer into one :class:`VSTOrderStatus` — the venue's own status word, the
executed quantity and the average price — or the system's ``not_found``
sentinel when the venue holds no record of the order at all.
:func:`cancel_rebalance_orders` answers the second: it lists the venue's
*open* orders and cancels exactly those whose ``clientOrderID`` is one of
the book's rebalance's own, returning the identifiers it cancelled.

**Why ``clientOrderID`` is the whole of the ownership test.**  The identifier
this addition places orders under is feature 3 of the Stage 0 spec
(:func:`router.bingx_client_order_id.project_bingx_client_order_id`): the
first forty characters of feature 316's digest over ``(book_id,
rebalance_ts, symbol)``
(:func:`router.client_order_id.derive_client_order_id`).  It is a *function*
of those three terms, so a clientOrderID belongs to this book's rebalance
exactly when it was derived from this ``book_id`` and this ``rebalance_ts``
and one of this rebalance's symbols.  A second book, or this book's *next*
rebalance, folds different terms and therefore projects different characters
(a sha256 collision at 160 bits is not a thing this system will meet), so
its orders can never match the set this module cancels by.  That is the
sentence's *"Orders from any other book or rebalance are left untouched"* —
not a promise made by a comment, but a consequence of building the set from
the same derivation the orders were named by.

**The read-back is per-order and the cancel is per-listing, on purpose.**
The first sentence says *looked up by clientOrderID*: the venue has a
single-order read (``GET /openApi/swap/v2/trade/order``) and
:func:`read_back_orders` uses it once per order, so a book of five legs is
five lookups and one ``not_found`` for a leg that never landed does not
hide the four that did.  The second sentence says *the open orders it
cancelled*: open-ness is a fact only the venue knows, and it publishes it
in one listing (``GET /openApi/swap/v2/trade/openOrders``), which returns
every open order **in the account** — this book's, another book's, another
rebalance's.  :func:`cancel_rebalance_orders` reads that listing and keeps
the entries whose identifier is its own; an order the venue lists but this
rebalance did not name is never passed to ``DELETE
/openApi/swap/v2/trade/order`` at all, which is the mechanical form of
*left untouched*.

**A refusal is translated, a status word is reported as the venue spelled
it.**  The venue's ``not_found`` answer is not an exception here: the venue
does not answer an empty order object for a ``clientOrderID`` it holds no
record of — it *refuses*, feature 1 raises :class:`~router.bingx_client.
RouterBingXRefusedError` carrying the venue's code, and this module judges
that code against :data:`ORDER_NOT_FOUND_CODES` (the live endpoint's
``109421`` *order not exist*, recorded in fixture
``live/query_order_not_exist.json``, beside the client's declared
:data:`~router.bingx_client.ORDER_NOT_FOUND_CODE`) — a code in the set
becomes the ``not_found`` status, any other code propagates, because an
order that never landed is a fact about the order and a signature the
venue rejected is a fault of the ask.  In the other direction, the status
word is the venue's own and is passed through verbatim: the live endpoint
reports a resting order as ``PENDING`` (fixture
``live/query_order_pending.json``), a word the sentence's list does not
carry, and refusing a word the venue actually sends would let any status
BingX coins tomorrow abort the read-back — so :data:`VST_ORDER_STATUSES`
documents the words this system knows rather than gating them, and only a
missing or unreadable status is refused.

**The read-back reads the venue's own shape.**  The single-order read's
answer wraps its order document under ``data.order`` — the nesting the
live recording carries — so :func:`_status_from` takes the object under
:data:`ORDER_FIELD` when the answer wraps one, and reads an answer that
already *is* the order object just as gladly (the shape older answers and
every injected double speak).  The venue's read also spells its echo
``clientOrderId``, one letter off the plan's ``clientOrderID``; the echo
is read under both spellings, and an answer naming a different order's
identifier under either is refused rather than reported under this one's
name.

**Money and quantities are decimals built from the venue's strings.**  The
conventions are explicit — *"Money and quantities are decimal.Decimal built
from the venue's strings"* — so ``origQty``, ``executedQty`` and
``avgPrice`` are read as exact :class:`~decimal.Decimal` values and a float
(a binary approximation of a decimal no venue ever sent) is refused by
name.  ``origQty`` is answered when the venue's document carries it and
``None`` when it does not — an answer that omits it reports no original
quantity rather than inventing one.  An order with no fills answers
``"0"`` for the executed quantity and the average price, which parses to
:data:`~decimal.Decimal` zero and is reported as measured; ``not_found``
carries ``None`` for all three, because there is no order to have executed
against.

**No table, no component, no clock, no I/O, no network.**  The client is
injected — the same ``(method, url, headers, body) -> (status, body)``
boundary feature 1 defines — so this module opens no socket, reads no
credential and consults no environment variable; it holds no store, writes
no row and reads no clock.  Both verbs are pure functions of the client and
the book's orders they are handed, which is what lets the suite drive them
over a recording double, and what the mirror's ``--status`` and ``--cancel``
rely on: nothing here places an order, and the only writes it can make are
the cancels of the rebalance's own open orders.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .bingx_client import ORDER_NOT_FOUND_CODE, RouterBingXRefusedError
from .bingx_client_order_id import BINGX_CLIENT_ORDER_ID_LENGTH
from .bingx_order import BingXRefusedLeg
from .errors import RouterError

__all__ = [
    "AVERAGE_PRICE_FIELD",
    "BINGX_ORDERS_CODE",
    "CLIENT_ORDER_ID_ECHO_FIELD",
    "CLIENT_ORDER_ID_FIELD",
    "EXECUTED_QUANTITY_FIELD",
    "OPEN_ORDERS_FIELD",
    "ORDER_FIELD",
    "ORDER_NOT_FOUND_CODES",
    "ORIGINAL_QUANTITY_FIELD",
    "STATUS_FIELD",
    "SYMBOL_FIELD",
    "VST_OPEN_ORDER_STATUSES",
    "VST_ORDER_NOT_FOUND",
    "VST_ORDER_STATUSES",
    "VST_ORDER_STATUS_CANCELED",
    "VST_ORDER_STATUS_EXPIRED",
    "VST_ORDER_STATUS_FILLED",
    "VST_ORDER_STATUS_NEW",
    "VST_ORDER_STATUS_PARTIALLY_FILLED",
    "VST_ORDER_STATUS_PENDING",
    "RouterBingXOrdersError",
    "VSTOrderStatus",
    "cancel_rebalance_orders",
    "read_back_orders",
]

#: The greppable token this module's refusals open with.  Coined on the
#: module's own name — the convention :mod:`router.bingx_dry_run` sets with
#: ``bingx_dry_run`` and :mod:`router.bingx_order` with ``bingx_order`` —
#: so an operator greps one word and lands on the read-back that refused.
#: A refusal here is a fault of the *ask* (an order payload the venue
#: shaped wrong, an item that names no order) rather than a fact about a
#: leg: the venue's own refusals keep feature 1's ``bingx_refused`` word
#: and propagate untouched.
BINGX_ORDERS_CODE = "bingx_orders"

#: The venue's own field spellings, as its order documents carry them.
#: Declared once at the venue boundary, never spelled at a call site.
SYMBOL_FIELD = "symbol"
CLIENT_ORDER_ID_FIELD = "clientOrderID"
#: The venue's single-order read spells its identifier echo one letter
#: lower — ``clientOrderId`` — as ``live/query_order_pending.json``
#: records; the plan's orders and the open-orders listing carry the
#: capital-``ID`` spelling above.  The echo is read under both.
CLIENT_ORDER_ID_ECHO_FIELD = "clientOrderId"
STATUS_FIELD = "status"
ORIGINAL_QUANTITY_FIELD = "origQty"
EXECUTED_QUANTITY_FIELD = "executedQty"
AVERAGE_PRICE_FIELD = "avgPrice"
#: The key the single-order read wraps its order document under: the live
#: endpoint answers ``{"order": {...}}`` as its ``data`` (recorded in
#: ``live/query_order_pending.json``).  An answer that carries no such key
#: is read as the order object itself.
ORDER_FIELD = "order"
#: The key the open-orders listing wraps its rows under, when it wraps
#: them at all: the venue answers either a bare array or ``{"orders": [
#: ...], "total": n}``, and both are read.
OPEN_ORDERS_FIELD = "orders"

#: The venue's status vocabulary: the words this system knows the venue to
#: use, ``PENDING`` included — the live endpoint's word for a resting
#: order, which feature 3's sentence omits.  The set documents the known
#: words and no longer gates the read-back: a status outside it is
#: reported as the venue spelled it, never refused, because a word BingX
#: coins tomorrow is a fact about the order, not a fault of the ask.
VST_ORDER_STATUS_NEW = "NEW"
VST_ORDER_STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
VST_ORDER_STATUS_FILLED = "FILLED"
VST_ORDER_STATUS_CANCELED = "CANCELED"
VST_ORDER_STATUS_EXPIRED = "EXPIRED"
VST_ORDER_STATUS_PENDING = "PENDING"
VST_ORDER_STATUSES = frozenset(
    {
        VST_ORDER_STATUS_NEW,
        VST_ORDER_STATUS_PARTIALLY_FILLED,
        VST_ORDER_STATUS_FILLED,
        VST_ORDER_STATUS_CANCELED,
        VST_ORDER_STATUS_EXPIRED,
        VST_ORDER_STATUS_PENDING,
    }
)

#: The system's own sentinel for *the venue holds no record of this order*,
#: spelled lowercase to mark it as this system's word rather than one of
#: the venue's six.  It is the answer feature 1's not-found refusal is
#: translated into, so a caller reads one vocabulary of six statuses in
#: which a missing order is a value, not an exception.
VST_ORDER_NOT_FOUND = "not_found"

#: The venue's own error codes for *it holds no record of this order* — the
#: refusal codes :func:`read_back_orders` answers as
#: :data:`VST_ORDER_NOT_FOUND` instead of a fault, and the only ones: every
#: other code keeps feature 1's refusal and propagates, because an order
#: that never landed is a fact about the order while a signature the venue
#: rejected is a fault of the ask.  Two spellings of the one fact.
#: ``109421`` is what the live VST endpoint answers — ``{"code": 109421,
#: "msg": "order not exist", "data": {}}``, recorded verbatim in fixture
#: ``live/query_order_not_exist.json`` when the first live smoke test asked
#: after an order that had been refused at placement: the venue does not
#: answer an empty order object for an unknown ``clientOrderID``, it
#: refuses, and the refusal is what there is to judge.  Beside it the
#: client's declared :data:`~router.bingx_client.ORDER_NOT_FOUND_CODE`,
#: which feature 1's own contract names as a code this read-back judges —
#: written from the spec's assumption before any live answer existed, and
#: held as the client's public spelling of the same fact.  Membership is
#: the test, not equality, because the venue has sent its codes as
#: integers and as strings across versions.
ORDER_NOT_FOUND_CODES = frozenset({ORDER_NOT_FOUND_CODE, 109421})

#: The statuses that mean an order is still working on the venue's book
#: and can therefore be cancelled — the complement, within the known
#: vocabulary, of the terminal states.  ``PENDING`` is the live endpoint's
#: word for a resting order (``live/query_order_pending.json``).  Exposed
#: so a caller can ask an answered :class:`VSTOrderStatus` whether the
#: order is still live (:attr:`VSTOrderStatus.is_open`) without
#: re-spelling the set.
VST_OPEN_ORDER_STATUSES = frozenset(
    {
        VST_ORDER_STATUS_NEW,
        VST_ORDER_STATUS_PARTIALLY_FILLED,
        VST_ORDER_STATUS_PENDING,
    }
)


class RouterBingXOrdersError(RouterError):
    """The read-back or the cancel cannot be answered at all.

    Raised for a fault of the *ask*, never for a fact about an order: a
    status the venue did not spell as readable text, an order payload that
    is not a mapping or that is missing the fields the sentence reads, an
    ``origQty``, ``executedQty`` or ``avgPrice`` offered as a float or as
    something that is not a decimal, an item handed in that names no
    order, or a client that does not expose the method the verb needs.  A
    status word outside :data:`VST_ORDER_STATUSES` is *not* one of these —
    it is reported as the venue spelled it.  The venue's own refusal —
    including the not-found answer this module translates into
    :data:`VST_ORDER_NOT_FOUND` — keeps feature 1's class and propagates
    untouched; what is raised here is what *this* module cannot read.

    Every message opens with :data:`BINGX_ORDERS_CODE` and names the one
    repair, the discipline every class in this member's vocabulary keeps.
    """


@dataclass(frozen=True)
class VSTOrderStatus:
    """One of the book's orders, as the venue answered for it.

    The value :func:`read_back_orders` answers for one ``clientOrderID``:
    the status the venue reports — its own word, spelled as it spelled it
    (:data:`VST_ORDER_STATUSES` documents the words this system knows,
    ``PENDING`` among them), or this system's :data:`VST_ORDER_NOT_FOUND`
    when the venue holds no record — beside the measurements the sentence
    names.

    * ``symbol`` — the leg, the venue's hyphenated spelling, when it is
      known: the caller's order normally names it, and a bare identifier
      handed to the verb falls back to the venue's echoed ``symbol``.  It
      is ``None`` only when neither named one — a not-found answer to a
      bare identifier — because inventing a symbol would be inventing a
      fact about which instrument an order was for.
    * ``client_order_id`` — the venue field's payload, the identifier the
      order was looked up by (feature 3's forty-character projection).
    * ``status`` — the venue's word, or :data:`VST_ORDER_NOT_FOUND`.
    * ``original_quantity`` — the venue's ``origQty`` as an exact
      :class:`~decimal.Decimal`, when the venue's document carries it, and
      ``None`` when it does not (and always for a not-found order).
    * ``executed_quantity`` — the venue's ``executedQty`` as an exact
      :class:`~decimal.Decimal`, or ``None`` when the order was not found.
    * ``average_price`` — the venue's ``avgPrice`` as an exact
      :class:`~decimal.Decimal`, or ``None`` when the order was not found.
      An order with no fills answers zero, which is a measurement, not an
      absence.

    ``executed_quantity`` and ``average_price`` are required together,
    exactly when the status is not :data:`VST_ORDER_NOT_FOUND`: a found
    order always has both (the venue answers ``"0"`` when nothing has
    filled), and a not-found order has neither.  ``original_quantity`` is
    answered exactly when the venue's document carried it, and never for a
    not-found order.  Frozen and hashable, so a read-back can stand as a
    key or sit in a set.
    """

    symbol: str | None
    client_order_id: str
    status: str
    executed_quantity: Decimal | None
    average_price: Decimal | None
    original_quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if self.symbol is not None and (
            not isinstance(self.symbol, str) or not self.symbol.strip()
        ):
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: an order status names the symbol it "
                f"is for as non-empty text or not at all, got "
                f"{self.symbol!r} ({type(self.symbol).__name__}); a leg is "
                "the unit the venue fills per symbol, and a blank name is "
                "not one"
            )
        if self.symbol is not None:
            object.__setattr__(self, "symbol", self.symbol.strip())
        if (
            not isinstance(self.client_order_id, str)
            or not self.client_order_id.strip()
            or len(self.client_order_id.strip()) > BINGX_CLIENT_ORDER_ID_LENGTH
        ):
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: an order status carries the "
                "clientOrderID the order was looked up by — at most "
                f"{BINGX_CLIENT_ORDER_ID_LENGTH} characters — got "
                f"{self.client_order_id!r}; the venue refuses a longer field "
                "and a blank one names no order"
            )
        object.__setattr__(
            self, "client_order_id", self.client_order_id.strip()
        )
        if not isinstance(self.status, str) or not self.status.strip():
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: an order status is the venue's own "
                f"word as non-empty text, got {self.status!r} "
                f"({type(self.status).__name__}); a blank or unreadable "
                "status is a response this module cannot read, whatever "
                "word it was going to report"
            )
        object.__setattr__(self, "status", self.status.strip())
        if self.original_quantity is not None and (
            not isinstance(self.original_quantity, Decimal)
            or not self.original_quantity.is_finite()
            or self.original_quantity < 0
        ):
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: the original_quantity for "
                f"{self.client_order_id!r} must be a finite, non-negative "
                f"Decimal, got {self.original_quantity!r} "
                f"({type(self.original_quantity).__name__}); a quantity "
                "that is not a number, or runs negative, is not one a "
                "venue reports"
            )
        if self.status == VST_ORDER_NOT_FOUND:
            if (
                self.executed_quantity is not None
                or self.average_price is not None
                or self.original_quantity is not None
            ):
                raise RouterBingXOrdersError(
                    f"{BINGX_ORDERS_CODE}: an order the venue holds no "
                    "record of carries neither an original quantity nor an "
                    "executed quantity nor an average price, got "
                    f"{self.original_quantity!r}, {self.executed_quantity!r} "
                    f"and {self.average_price!r}; there is no order to have "
                    "filled, and a number here would be invented"
                )
            return
        for term, value in (
            ("executed_quantity", self.executed_quantity),
            ("average_price", self.average_price),
        ):
            if value is None:
                raise RouterBingXOrdersError(
                    f"{BINGX_ORDERS_CODE}: an order the venue reports as "
                    f"{self.status!r} carries its {term} — the venue answers "
                    "zero when nothing has filled — got None; the sentence "
                    "names the measurement, and a missing one is a response "
                    "this module cannot read"
                )
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise RouterBingXOrdersError(
                    f"{BINGX_ORDERS_CODE}: the {term} for "
                    f"{self.client_order_id!r} must be a finite, "
                    f"non-negative Decimal, got {value!r} "
                    f"({type(value).__name__}); a quantity or a price that "
                    "is not a number, or runs negative, is not one a venue "
                    "reports"
                )

    @property
    def is_open(self) -> bool:
        """Whether the order is still live and so cancellable.

        True for :data:`VST_ORDER_STATUS_NEW`,
        :data:`VST_ORDER_STATUS_PARTIALLY_FILLED` and
        :data:`VST_ORDER_STATUS_PENDING` — the words for an order still
        working on the venue's book — and false for every terminal status,
        for a word this system does not know, and for
        :data:`VST_ORDER_NOT_FOUND`.
        """
        return self.status in VST_OPEN_ORDER_STATUSES

    def as_dict(self) -> dict[str, Any]:
        """The status as the venue's own field spellings, ready to print.

        ``symbol``, ``clientOrderID``, ``status``, ``origQty``,
        ``executedQty`` and ``avgPrice`` — the keys the venue's order
        document carries — with the decimals rendered as their exact
        string spellings (and ``None`` where a not-found order has no
        measurement), so a ``json.dumps`` of this answer is one line of a
        plan-like report.
        """
        return {
            SYMBOL_FIELD: self.symbol,
            CLIENT_ORDER_ID_FIELD: self.client_order_id,
            STATUS_FIELD: self.status,
            ORIGINAL_QUANTITY_FIELD: (
                None if self.original_quantity is None
                else str(self.original_quantity)
            ),
            EXECUTED_QUANTITY_FIELD: (
                None if self.executed_quantity is None
                else str(self.executed_quantity)
            ),
            AVERAGE_PRICE_FIELD: (
                None if self.average_price is None else str(self.average_price)
            ),
        }


def _require_method(client: Any, name: str) -> Any:
    """Return ``client``'s callable ``name``, or refuse a client that lacks it.

    The verbs take an injected client — feature 1's
    :class:`~router.bingx_client.BingXClient` in a deployment, a recording
    double in the suite — and a client that does not expose the method a
    verb needs is a wiring fault worth naming rather than a bare
    :class:`AttributeError` from the middle of a loop.
    """
    method = getattr(client, name, None)
    if not callable(method):
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the injected client exposes no callable "
            f"{name}(); the read-back and the cancel speak to the venue "
            "through feature 1's client, and a client without this method "
            "cannot be asked"
        )
    return method


def _book_orders(orders: Any) -> list[tuple[str | None, str]]:
    """The book's orders as ``(symbol, clientOrderID)`` pairs, in order.

    ``orders`` is the plan's legs, or any iterable of orders: a
    :class:`~router.bingx_order.BingXOrder` (or any value carrying
    ``symbol`` and ``client_order_id``) contributes its identity; a mapping
    in the venue's own spellings — the shape a written plan holds — is read
    by its ``clientOrderID``/``client_order_id`` and ``symbol``; a bare
    string is taken as a ``clientOrderID`` with no symbol; and a
    :class:`~router.bingx_order.BingXRefusedLeg` is skipped — a refused leg
    is a leg the gates closed and names no venue order, so it is not the
    read-back's business.  Anything else is a fault of the ask, refused
    naming the item, because a value that names no order would silently
    drop a leg from the read-back.  Input order is preserved, so the
    read-back answers in the order it was handed (the plan's sorted symbol
    order).
    """
    if orders is None or isinstance(orders, (str, bytes)) or not isinstance(
        orders, Iterable
    ):
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the book's orders are an iterable of "
            f"BingXOrder values or clientOrderID strings, got {orders!r} "
            f"({type(orders).__name__}); the read-back and the cancel walk "
            "the legs the plan produced, and a value that is not a "
            "collection of them names nothing to walk"
        )
    pairs: list[tuple[str | None, str]] = []
    for item in orders:
        if isinstance(item, BingXRefusedLeg):
            continue
        if isinstance(item, str):
            symbol: Any = None
            identifier: Any = item
        elif isinstance(item, Mapping):
            symbol = item.get("symbol")
            identifier = item.get("clientOrderID", item.get("client_order_id"))
        else:
            symbol = getattr(item, "symbol", None)
            identifier = getattr(item, "client_order_id", None)
        if (
            not isinstance(identifier, str)
            or not identifier.strip()
            or len(identifier.strip()) > BINGX_CLIENT_ORDER_ID_LENGTH
        ):
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: a leg of the book names no order — "
                "expected a BingXOrder (or a clientOrderID string) carrying "
                f"at most {BINGX_CLIENT_ORDER_ID_LENGTH} characters, got "
                f"{item!r} ({type(item).__name__}); an item that names no "
                "order cannot be looked up or cancelled"
            )
        name = (
            symbol.strip()
            if isinstance(symbol, str) and symbol.strip()
            else None
        )
        pairs.append((name, identifier.strip()))
    return pairs


def _decimal_field(
    document: Mapping, field: str, client_order_id: str
) -> Decimal:
    """Read one of the venue's decimal fields, exactly, or refuse it.

    The venue spells quantities and prices as strings; this reads that
    string — or an exact :class:`~decimal.Decimal`/:class:`int`, which name
    the same value — and refuses a float, because a float is a binary
    approximation of a decimal no venue ever sent.  The value must be
    finite and non-negative: an executed quantity or an average price
    cannot be negative, and a NaN or an infinity is not a measurement.
    """
    if field not in document:
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the venue's answer for "
            f"{client_order_id!r} carries no {field!r}; feature 3 reports "
            "the executed quantity and the average price, and a response "
            "that omits one cannot be read into them"
        )
    value = document[field]
    if isinstance(value, bool):
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the {field!r} for {client_order_id!r} "
            f"must be a decimal, got the boolean {value!r}; a true/false "
            "spelling is not a quantity or a price"
        )
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: the {field!r} {value!r} for "
                f"{client_order_id!r} is not a decimal"
            ) from exc
    else:
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the {field!r} for {client_order_id!r} "
            f"must be a decimal string or a Decimal, got {value!r} "
            f"({type(value).__name__}); a float is a binary approximation "
            "of a decimal no venue ever sent, and a measurement read "
            "approximately would report a fill nobody made"
        )
    if not number.is_finite() or number < 0:
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the {field!r} for {client_order_id!r} "
            f"must be finite and non-negative, got {number!r}; neither an "
            "executed quantity nor an average price runs backwards or "
            "measures nothing"
        )
    return number


def _status_from(
    document: Any, symbol: str | None, client_order_id: str
) -> VSTOrderStatus:
    """Fold a venue order document into a :class:`VSTOrderStatus`, or refuse.

    The venue's read answer wraps its order document under
    :data:`ORDER_FIELD` — the live endpoint answers ``{"order": {...}}``
    as its ``data`` — so the object under that key is read when the answer
    wraps one, and an answer that already *is* the order object is read
    just as gladly.  From the order object: its ``status`` word, reported
    verbatim whether or not :data:`VST_ORDER_STATUSES` knows it; its
    ``origQty`` when it carries one, its ``executedQty`` and ``avgPrice``;
    and — when the venue echoes it — its ``clientOrderID`` (spelled
    ``clientOrderId`` by the single-order read), which is checked against
    the identifier we asked for so an answer about a different order is
    refused rather than reported under this one's name.
    """
    if not isinstance(document, Mapping):
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the venue's answer for "
            f"{client_order_id!r} is an order object, got {document!r} "
            f"({type(document).__name__})"
        )
    if ORDER_FIELD in document:
        wrapped = document[ORDER_FIELD]
        if not isinstance(wrapped, Mapping):
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: the venue's answer for "
                f"{client_order_id!r} wraps its order under "
                f"{ORDER_FIELD!r} as an object, got {wrapped!r} "
                f"({type(wrapped).__name__})"
            )
        document = wrapped
    echoed = document.get(CLIENT_ORDER_ID_FIELD, document.get(CLIENT_ORDER_ID_ECHO_FIELD))
    if echoed is not None and (
        not isinstance(echoed, str) or echoed.strip() != client_order_id
    ):
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the venue answered for "
            f"{client_order_id!r} with {echoed!r}; the answer names a "
            "different order's clientOrderID, so it cannot be reported "
            "under this one's name"
        )
    raw_status = document.get(STATUS_FIELD)
    if not isinstance(raw_status, str) or not raw_status.strip():
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the venue's answer for "
            f"{client_order_id!r} carries no readable {STATUS_FIELD!r}, got "
            f"{raw_status!r} ({type(raw_status).__name__}); the status is "
            "the first thing the sentence reports"
        )
    status = raw_status.strip()
    answer_symbol = document.get(SYMBOL_FIELD)
    name = symbol
    if name is None and isinstance(answer_symbol, str) and answer_symbol.strip():
        name = answer_symbol.strip()
    return VSTOrderStatus(
        symbol=name,
        client_order_id=client_order_id,
        status=status,
        original_quantity=(
            _decimal_field(document, ORIGINAL_QUANTITY_FIELD, client_order_id)
            if ORIGINAL_QUANTITY_FIELD in document
            else None
        ),
        executed_quantity=_decimal_field(
            document, EXECUTED_QUANTITY_FIELD, client_order_id
        ),
        average_price=_decimal_field(
            document, AVERAGE_PRICE_FIELD, client_order_id
        ),
    )


def _is_not_found(code: Any) -> bool:
    """Whether the venue's refusal code is its *no such order* answer.

    Compared by spelling rather than by identity: the venue has sent its
    codes as integers and as strings across versions, and the client
    carries whatever it sent verbatim, so every spelling of every code in
    :data:`ORDER_NOT_FOUND_CODES` is the same answer.
    """
    if isinstance(code, bool) or code is None:
        return False
    return str(code).strip() in {str(c) for c in ORDER_NOT_FOUND_CODES}


def _open_order_entries(client: Any) -> list[Mapping]:
    """The venue's open-orders listing, as a list of order mappings, or refuse.

    Feature 1's ``open_orders()`` answers the envelope's ``data``: the
    venue sends either a bare array of orders or ``{"orders": [...],
    "total": n}``, and both are read.  Each row must be a mapping — a
    listing holding something else is a response this module cannot
    filter.
    """
    method = _require_method(client, "open_orders")
    data = method()
    entries = data
    if isinstance(data, Mapping):
        entries = data.get(OPEN_ORDERS_FIELD)
    if (
        entries is None
        or isinstance(entries, (str, bytes))
        or not isinstance(entries, Sequence)
    ):
        raise RouterBingXOrdersError(
            f"{BINGX_ORDERS_CODE}: the venue's open-orders answer is an "
            f"array of orders (or {{'orders': [...]}}), got {data!r} "
            f"({type(data).__name__}); the cancel reads the listing to learn "
            "which of the rebalance's orders are still open"
        )
    rows: list[Mapping] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: the venue's open-orders listing "
                f"holds an order object per row, got {entry!r} "
                f"({type(entry).__name__})"
            )
        rows.append(entry)
    return rows


def read_back_orders(*, client: Any, orders: Any) -> list[VSTOrderStatus]:
    """Feature 3's first sentence: the book's orders, each as the venue sees it.

    Walks ``orders`` — the plan's legs, in the order it is handed — and
    looks each up on the venue by its ``clientOrderID`` with feature 1's
    single-order read, folding the answer into a :class:`VSTOrderStatus`.
    A venue refusal is judged: a code in :data:`ORDER_NOT_FOUND_CODES` —
    the live venue *refuses* an order it holds no record of, code 109421
    ``order not exist``, rather than answering an empty order — becomes
    that order's :data:`VST_ORDER_NOT_FOUND` status and the walk continues
    with the remaining legs, so one missing leg cannot hide the placed
    ones; any other code propagates as feature 1 raised it, because a
    rejected signature is a fault of the ask rather than a fact about the
    order.  A :class:`~router.bingx_order.BingXRefusedLeg` among the legs
    is skipped: the gates closed it and it names no venue order to look
    up.

    A pure function of the injected client and the legs: it reads no clock,
    touches no store and opens no socket of its own.  Refuses
    :class:`RouterBingXOrdersError` for the ask's own faults and lets
    feature 1's errors — a transport failure, the venue's other refusals —
    propagate unchanged.
    """
    query = _require_method(client, "query_order")
    statuses: list[VSTOrderStatus] = []
    for symbol, client_order_id in _book_orders(orders):
        try:
            document = query(client_order_id, symbol=symbol)
        except RouterBingXRefusedError as exc:
            if _is_not_found(exc.code):
                statuses.append(
                    VSTOrderStatus(
                        symbol=symbol,
                        client_order_id=client_order_id,
                        status=VST_ORDER_NOT_FOUND,
                        executed_quantity=None,
                        average_price=None,
                    )
                )
                continue
            raise
        statuses.append(_status_from(document, symbol, client_order_id))
    return statuses


def cancel_rebalance_orders(*, client: Any, orders: Any) -> list[str]:
    """Feature 3's second sentence: cancel this rebalance's open orders.

    Reads the venue's open-orders listing and cancels exactly the entries
    whose ``clientOrderID`` is one of ``orders``' own — the book's
    rebalance's identifiers, by construction — returning the identifiers it
    cancelled, in the order the venue listed them.  An open order the
    listing carries that this rebalance did not name (another book's,
    another rebalance's) is never passed to the venue's cancel at all, so
    it is left untouched; that filter is the whole of the sentence's
    ownership clause, and it is exact because a ``clientOrderID`` is a
    function of the book, the rebalance and the symbol that named it.

    ``orders`` is the plan's legs (see :func:`_book_orders`): refused legs
    name no order and are skipped.  A :class:`~router.bingx_order.
    BingXRefusedLeg` is not cancellable, and neither is a filled or expired
    order — those are not in the venue's open listing to begin with.

    A pure function of the injected client and the legs apart from the
    cancels it makes, which are the one write the sentence asks for.
    Refuses :class:`RouterBingXOrdersError` for the ask's own faults and
    lets feature 1's errors propagate unchanged.
    """
    cancel = _require_method(client, "cancel_order")
    owned = {
        client_order_id: symbol
        for symbol, client_order_id in _book_orders(orders)
    }
    cancelled: list[str] = []
    for entry in _open_order_entries(client):
        raw_id = entry.get(CLIENT_ORDER_ID_FIELD)
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise RouterBingXOrdersError(
                f"{BINGX_ORDERS_CODE}: an open order from the venue carries "
                f"no readable {CLIENT_ORDER_ID_FIELD!r}, got {raw_id!r} "
                f"({type(raw_id).__name__}); the cancel decides ownership by "
                "this field, and a row without it cannot be judged — let "
                "alone safely cancelled"
            )
        client_order_id = raw_id.strip()
        if client_order_id not in owned:
            # Not this rebalance's order: another book's, or another
            # rebalance's.  It is left untouched — never handed to the
            # venue's cancel — which is the sentence's own clause.
            continue
        raw_symbol = entry.get(SYMBOL_FIELD)
        symbol = owned[client_order_id]
        if isinstance(raw_symbol, str) and raw_symbol.strip():
            symbol = raw_symbol.strip()
        cancel(client_order_id, symbol=symbol)
        cancelled.append(client_order_id)
    return cancelled
