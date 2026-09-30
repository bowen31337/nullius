"""Stage 0's venue documents: BingX VST contracts, and BingX mark prices.

``additions_spec_bingx_dry_run.xml``, feature 1: *System translates a BingX
swap contracts document into RouterSymbolFilters per symbol, taking the step
size as ten to the minus quantityPrecision, the tick size as ten to the minus
pricePrecision, ``min_qty`` from ``tradeMinQuantity`` and ``min_notional``
from ``tradeMinUSDT``, and returns a ``not_tradable`` refusal naming the
symbol when its ``status`` is not ``1`` or ``apiStateOpen`` is not
``"true"``.*  And the second half of the same feature: *It also reads a
BingX premiumIndex document into a Decimal mark price per symbol, returning a
``missing_mark_price`` refusal naming the symbol when a symbol the book holds
has no mark price.*

**A second, BingX-specific constructor of feature 310's value.**  The
integration points are explicit: *"The translator in feature 1 is a second,
BingX-specific constructor of RouterSymbolFilters;
``nullius_ingest.exchange_info`` and ``router.exchange_info.resolve_router_filters``
stay Binance-shaped and unchanged."*  So this module does **not** reach
:func:`router.exchange_info.resolve_router_filters` and does not grow that
module a second wire format: it builds the very same
:class:`~router.exchange_info.RouterSymbolFilters` from BingX's own field
names, so every gate downstream (features 312, 313, 314, 315, 317) judges a
BingX order against a value of exactly the type it already reads.

**The precisions, never the ``size`` field.**  The constraints state the trap
in one line: *"Never read the contract's ``size`` field as the quantity step:
it differs from ten to the minus ``quantityPrecision`` for ETH-USDT,
SOL-USDT and five other symbols."*  The recorded fixture shows it plainly —
ETH-USDT's ``size`` is ``"0.01"`` while its ``quantityPrecision`` is ``3``,
so the step the venue books on is ``0.001``.  The step and the tick are
therefore *computed* from the precisions, exactly as the feature sentence
says, and ``size`` is never read at all.

**Symbols keep BingX's hyphenated spelling.**  ``BTC-USDT`` end to end;
nothing here maps it to Binance's ``BTCUSDT``.  A symbol the venue would not
trade is refused rather than dropped, so the caller always knows *which*
symbol the plan may not carry — the refusal names it.

**Pure functions over parsed JSON.**  Following
:func:`router.exchange_info.resolve_router_filters`, every entry point here
accepts the document as JSON bytes, a JSON string or an already-decoded
mapping.  Nothing in this module opens a socket, reads an environment
variable, touches a clock or a store: the same document answers the same
translation in any process on any day.  That is what makes this safe for
Stage 0, whose whole point is to read a captured document and send nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .errors import RouterError
from .exchange_info import RouterSymbolFilters

__all__ = [
    "MARK_PRICE_CODE",
    "NOT_TRADABLE_CODE",
    "BingXContracts",
    "RouterMarkPriceError",
    "RouterNotTradableError",
    "RouterVehicleDocumentError",
    "resolve_bingx_filters",
    "resolve_bingx_mark_prices",
]

#: Feature 1's greppable token, for a symbol the *book holds* but the venue's
#: premiumIndex does not price.  The feature sentence spells the refusal's
#: name, so this constant is that exact string rather than a name coined in
#: the house style: an operator who read the spec and greps for it must find
#: the refusals.  A leg that cannot be marked cannot be sized, and sizing it
#: off a neighbouring symbol's price — or off nothing — would be an order the
#: book never decided to hold.
MARK_PRICE_CODE = "missing_mark_price"

#: Feature 1's greppable token for a contract the venue will not book: a
#: ``status`` that is not ``1``, or an ``apiStateOpen`` that is not the string
#: ``"true"``.  Refused rather than skipped, so the plan's reader learns the
#: symbol's name rather than wondering why a weight went missing.  Note that
#: Stage 0 records a *refusal* here and keeps the weight in the book: the
#: contract is not tradable, the plan is not silent about it.
NOT_TRADABLE_CODE = "not_tradable"


class RouterVehicleDocumentError(RouterError, ValueError):
    """A BingX vehicle document is not one this module can read.

    The shared stem of the two refusals below: both are faults of *the
    document that was handed in* — not JSON, not an object, no ``data``
    list, a row that is not an object, a field that is absent — rather than
    faults of a particular symbol's terms.  Kept separate from
    :class:`~router.errors.RouterFilterError` on purpose: that class refuses
    a document that is not a well-formed *exchangeInfo*, and these documents
    are BingX's own ``/openApi/swap/v2/quote/contracts`` and
    ``/openApi/swap/v2/quote/premiumIndex`` shapes, which no exchangeInfo
    parser has ever seen.

    It is a :class:`ValueError` as well as a :class:`RouterError`, matching
    :class:`~router.errors.RouterFilterError`'s dual inheritance, so a
    caller that catches either vocabulary catches a malformed document.
    """


class RouterNotTradableError(RouterVehicleDocumentError):
    """A contract the venue lists but will not trade.

    ``status`` other than ``1``, or ``apiStateOpen`` other than the string
    ``"true"``.  The word the feature sentence promises opens every message,
    followed by the symbol, because the repair is *do not plan this leg* and
    the operator's next question is always *which one*.

    :attr:`symbol` carries that name as a value as well as inside the
    message, so a plan that holds this refusal can print its own record —
    the feature's *"a not_tradable refusal naming the symbol"* — without
    parsing a sentence, and :attr:`code` carries the one word to grep.

    It is stored in :func:`resolve_bingx_filters`' result rather than
    raised out of it, because the feature's own worked example says the
    recorded fixture yields the tradable symbols *and* this refusal: a
    translator that could only do one or the other would have to drop the
    symbol, and a symbol silently absent is indistinguishable from a symbol
    the document never mentioned.
    """

    code = NOT_TRADABLE_CODE

    def __init__(self, message: str, *, symbol: str) -> None:
        super().__init__(message)
        self.symbol = symbol


class RouterMarkPriceError(RouterVehicleDocumentError):
    """A symbol the book holds that the premiumIndex document does not price.

    Missing, null, or not an exact decimal.  Every message opens with
    :data:`MARK_PRICE_CODE` and names the symbol — carried as
    :attr:`symbol` too, for the same reason
    :class:`RouterNotTradableError` carries its own — because a mark price
    is what turns a weight into a quantity and an absent one is not a zero.

    This one **is** raised out of :func:`resolve_bingx_mark_prices` rather
    than stored: the feature says the reader returns *"a missing_mark_price
    refusal"*, and the check is about the symbols the caller said the book
    holds — a set this module cannot enumerate from the document, so it has
    no walk to carry the refusal out of.  The two refusals differ in shape
    because their subjects do: one is per contract row, the other is per
    requested book.
    """

    code = MARK_PRICE_CODE

    def __init__(self, message: str, *, symbol: str) -> None:
        super().__init__(message)
        self.symbol = symbol


def _decode(document: object, *, what: str) -> Mapping:
    """Decode a document given as bytes, text or an already-decoded mapping.

    The three accepted spellings are exactly
    :func:`router.exchange_info.resolve_router_filters`'s, so the two
    document seams of this package are called the same way.  ``what`` names
    the document in the refusal, because "not JSON" is only useful beside
    *which* fetch was not.
    """

    if isinstance(document, (bytes, bytearray, str)):
        try:
            document = json.loads(document)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RouterVehicleDocumentError(
                f"the {what} document is not JSON: {exc}"
            ) from exc
    if not isinstance(document, Mapping):
        raise RouterVehicleDocumentError(
            f"the {what} document must be a JSON object, got "
            f"{type(document).__name__}"
        )
    return document


def _rows(document: object, *, what: str) -> list:
    """Return the ``data`` list of a BingX quote response, or refuse.

    BingX's public quote endpoints answer ``{"code": 0, "msg": "",
    "data": [...]}``.  ``code`` is deliberately *not* judged here: a
    non-zero ``code`` is the venue reporting a fault and is the transport
    seam's business, not this pure reader's, and a document with no ``data``
    list at all is refused by name rather than read as an empty result — an
    empty plan and a malformed fetch must not look alike.
    """

    payload = _decode(document, what=what)
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RouterVehicleDocumentError(
            f"the {what} document carries no 'data' list (got "
            f"{type(rows).__name__}); refused rather than read as an empty "
            "result, because a malformed fetch and a venue with nothing to "
            "say must not look alike"
        )
    return rows


def _step_from_precision(
    row: Mapping, field: str, *, symbol: str, what: str
) -> str:
    """Ten to the minus a non-negative integer precision, as a decimal string.

    Returned as a *string* rather than a :class:`~decimal.Decimal` because
    :class:`~router.exchange_info.RouterSymbolFilters` keeps every field as
    the venue's own spelling and this module is its BingX constructor: the
    spelling it records is the one the venue's precision implies, and
    decimalisation belongs to the order path (features 312-313).

    ``Decimal(10) ** -precision`` is exact for any non-negative integer —
    ``Decimal("0.0001")`` for ``4``, ``Decimal("1")`` for ``0`` — while the
    same arithmetic in binary floating point would not be.  It is then
    rendered with the ``f`` format rather than by ``str``, because
    ``str(Decimal(10) ** -7)`` is ``1E-7``: the exponent the exponent is
    spelled in is a property of the decimal context, not of the grid, and
    the grid the venue books on is ``0.0000001``.
    """

    precision = row.get(field)
    if (
        isinstance(precision, bool)
        or not isinstance(precision, int)
        or precision < 0
    ):
        raise RouterVehicleDocumentError(
            f"the {what} document states {field}={precision!r} for "
            f"{symbol!r}; a precision must be a non-negative whole number of "
            "decimal places, and a grid this module invented would be "
            "exactly the hardcoded venue constant Stage 0 exists to avoid"
        )
    return f"{Decimal(10) ** -precision:f}"


def _decimal_field(row: Mapping, field: str, *, symbol: str, what: str) -> str:
    """A venue field read as an exact decimal, returned in the venue's spelling.

    Refused when absent, null, or not a finite decimal.  A JSON number is
    accepted because ``json.loads`` reads one exactly when the document
    spells it exactly; :class:`~decimal.Decimal` of a float would not, so a
    JSON float is read through its own shortest spelling rather than through
    binary arithmetic — and the recorded fixtures spell every one of these
    fields as a string anyway.
    """

    value = row.get(field)
    if value is None:
        raise RouterVehicleDocumentError(
            f"the {what} document states no {field} for {symbol!r}; every "
            "quantity bound this translator reads is published per contract, "
            "and a bound this module defaulted would be a hardcoded venue "
            "constant"
        )
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RouterVehicleDocumentError(
            f"the {what} document states {field}={value!r} "
            f"({type(value).__name__}) for {symbol!r}; expected a decimal "
            "spelling"
        )
    text = str(value)
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise RouterVehicleDocumentError(
            f"the {what} document states {field}={value!r} for {symbol!r}, "
            "which is not a decimal"
        ) from exc
    if not parsed.is_finite():
        raise RouterVehicleDocumentError(
            f"the {what} document states {field}={value!r} for {symbol!r}, "
            "which is not a finite decimal"
        )
    return text


def _is_tradable(row: Mapping) -> bool:
    """Whether a contract's own state permits the venue to book an order.

    Two standing facts, exactly the two the feature sentence names: the
    contract's ``status`` must be the number ``1``, and ``apiStateOpen``
    must be the string ``"true"``.  ``status`` is compared as an integer
    because BingX publishes it as one and ``True == 1`` in Python, so the
    boolean is excluded explicitly rather than smuggled through.  Any other
    spelling of the open flag — the JSON boolean ``true``, the string
    ``"True"``, an absent field — is not the string the sentence states.

    Absence is refused by :func:`_flag_field` before this is reached, so a
    document that forgot to state the field at all is a malformed document
    rather than a closed contract: those are different repairs.
    """

    status = row["status"]
    if isinstance(status, bool) or status != 1:
        return False
    return row["apiStateOpen"] == "true"


def _flag_fields(row: Mapping, *, symbol: str, what: str) -> None:
    """Require the two state fields the tradability judgment reads."""

    for field in ("status", "apiStateOpen"):
        if field not in row:
            raise RouterVehicleDocumentError(
                f"the {what} document states no {field} for {symbol!r}; the "
                "contract's own trading state is what decides whether the "
                "symbol is tradable, and an absent state is not a permissive "
                "one"
            )


def _claim(symbol: str, seen: set[str], *, what: str) -> None:
    """Refuse a symbol the document has already stated once.

    A second row for one symbol is not a second contract, it is two answers
    to one question: the grid the venue books on cannot be both, and the
    trading state cannot be both.  Silently keeping the last row would hide
    a document the venue should not have sent — and if the two rows
    disagreed about tradability the symbol would land in *both* halves of
    the translation, which is exactly the ambiguity
    :meth:`BingXContracts.__getitem__` must never have to resolve.  The
    ingest member's own exchangeInfo parser refuses a duplicated symbol for
    the same reason, so this is the stance the workspace already keeps, not
    a new one.
    """

    if symbol in seen:
        raise RouterVehicleDocumentError(
            f"the {what} document states {symbol!r} more than once; one "
            "symbol has one contract, and two rows for it are two answers "
            "to a question whose whole point is that it has one"
        )
    seen.add(symbol)


def _symbol(row: Mapping, *, what: str, index: int) -> str:
    """The row's ``symbol``, required to be a non-empty string."""

    symbol = row.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise RouterVehicleDocumentError(
            f"{what} row {index} states symbol={symbol!r}; every row of this "
            "document names the contract it is about, and a row that names "
            "nothing cannot be translated"
        )
    return symbol


@dataclass(frozen=True)
class BingXContracts:
    """Feature 1's translation of one contracts document: filters and refusals.

    ``filters`` holds one
    :class:`~router.exchange_info.RouterSymbolFilters` per contract the
    venue will trade, keyed by BingX's own hyphenated spelling (``BTC-USDT``
    end to end; nothing maps it to Binance's ``BTCUSDT``).  ``refusals``
    holds one :class:`RouterNotTradableError` per contract the venue lists
    but will not, keyed the same way, its message already naming the symbol.

    **Why a value rather than a raise.**  The feature's own worked example
    is the recorded fixture, and that document yields *both* answers at
    once: ``BTC-USDT`` step ``0.0001`` tick ``0.1``, ``ETH-USDT`` step
    ``0.001`` tick ``0.01``, *and* a ``not_tradable`` refusal for
    ``NCFXUSD2ARS-USDT``.  A translator whose only failure mode was an
    exception could not answer that document at all — it would have to
    choose between dropping six symbols and dropping the refusal, and a
    symbol silently absent from a mapping is indistinguishable from a symbol
    the document never mentioned.  Stage 0 needs the opposite: the plan
    says, in one breath, which legs it would send and which leg the venue
    has closed.

    It is a value, not a component: no ``@register``, no table, no clock,
    nothing to configure.  Two calls on one document answer the same two
    mappings, which is what makes it safe to re-read mid-rebalance.

    Both mappings preserve document order, so two operators handed one
    document read the same symbols in the same sequence.
    """

    filters: dict[str, RouterSymbolFilters]
    refusals: dict[str, RouterNotTradableError]
    #: Every symbol the document named, tradable or not, in document order.
    #: Stored rather than derived from the two mappings, because the split
    #: between them is *why* a symbol was refused and not *where* it sat: a
    #: refused contract between two tradable ones belongs between them.
    symbols: tuple[str, ...]

    def __getitem__(
        self, symbol: str
    ) -> RouterSymbolFilters | RouterNotTradableError:
        """One symbol's answer: its filters, or the refusal that replaced them.

        The feature's own shape — *"into RouterSymbolFilters per symbol ...
        and returns a not_tradable refusal naming the symbol"* — is one
        answer per symbol, so this is the lookup the plan wants: ask by the
        symbol the book holds and branch on what comes back, rather than
        consulting the right one of two mappings.  A symbol the document
        never named is a :class:`KeyError`, exactly as it would be on either
        mapping, so the two halves being separate fields does not make an
        absent symbol look answered.
        """

        if symbol in self.filters:
            return self.filters[symbol]
        if symbol in self.refusals:
            return self.refusals[symbol]
        raise KeyError(symbol)

    def __contains__(self, symbol: object) -> bool:
        return symbol in self.filters or symbol in self.refusals

    def __iter__(self):
        """Iterate the document's symbols, tradable or not, in order."""

        return iter(self.symbols)

    def __len__(self) -> int:
        return len(self.symbols)


def resolve_bingx_filters(document: object) -> BingXContracts:
    """Translate a BingX swap contracts document into filters and refusals.

    The feature's own sentence, condensed: one
    :class:`~router.exchange_info.RouterSymbolFilters` per symbol, with

    * ``step_size`` = ten to the minus ``quantityPrecision``,
    * ``tick_size`` = ten to the minus ``pricePrecision``,
    * ``min_qty`` from ``tradeMinQuantity``,
    * ``min_notional`` from ``tradeMinUSDT``,

    and the four bounds the BingX document does not state — ``max_qty``,
    ``min_price``, ``max_price`` — honestly ``None``, because ``None`` in
    that value means *the document did not carry it* and inventing a bound
    would be the hardcoded venue constant the constraints forbid.

    A symbol whose ``status`` is not ``1`` or whose ``apiStateOpen`` is not
    ``"true"`` produces a :class:`RouterNotTradableError` naming it in
    :attr:`BingXContracts.refusals` rather than a filter — see
    :class:`BingXContracts` for why the recorded fixture requires the value
    and the refusal to come back together.

    A document that is not a BingX quote response at all — not JSON, no
    ``data`` list, a row that is not an object, a field the translation
    needs and the document omits, a precision that is not a whole number of
    decimal places — raises :class:`RouterVehicleDocumentError`, because
    those are faults of the *fetch* rather than facts about one contract:
    there is no answer to carry, so nothing is returned.
    """

    rows = _rows(document, what="BingX contracts")
    filters: dict[str, RouterSymbolFilters] = {}
    refusals: dict[str, RouterNotTradableError] = {}
    order: list[str] = []
    claimed: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise RouterVehicleDocumentError(
                "the BingX contracts document carries a non-object row at "
                f"index {index} ({type(row).__name__}); every row of this "
                "document is one contract"
            )
        symbol = _symbol(row, what="the BingX contracts document", index=index)
        # Claimed before the tradability branch: a duplicate is a defect of
        # the document whichever half the two rows would have landed in.
        _claim(symbol, claimed, what="BingX contracts")
        order.append(symbol)
        _flag_fields(row, symbol=symbol, what="BingX contracts")
        if not _is_tradable(row):
            refusals[symbol] = RouterNotTradableError(
                f"{NOT_TRADABLE_CODE}: {symbol!r} is listed but not tradable "
                f"(status={row['status']!r}, "
                f"apiStateOpen={row['apiStateOpen']!r}); only a contract "
                "whose status is 1 and whose apiStateOpen is the string "
                "'true' may be planned, and no order may be built against a "
                "leg the venue would refuse",
                symbol=symbol,
            )
            continue
        filters[symbol] = RouterSymbolFilters(
            symbol=symbol,
            step_size=_step_from_precision(
                row, "quantityPrecision", symbol=symbol, what="BingX contracts"
            ),
            min_qty=_decimal_field(
                row, "tradeMinQuantity", symbol=symbol, what="BingX contracts"
            ),
            max_qty=None,
            tick_size=_step_from_precision(
                row, "pricePrecision", symbol=symbol, what="BingX contracts"
            ),
            min_price=None,
            max_price=None,
            min_notional=_decimal_field(
                row, "tradeMinUSDT", symbol=symbol, what="BingX contracts"
            ),
        )
    return BingXContracts(
        filters=filters, refusals=refusals, symbols=tuple(order)
    )


def resolve_bingx_mark_prices(
    document: object, symbols: object = None
) -> dict[str, Decimal]:
    """Read a BingX premiumIndex document into a mark price per symbol.

    ``markPrice`` is read as an exact :class:`~decimal.Decimal` — the
    feature says *"a Decimal mark price per symbol"*, and a mark price is
    what the sizer divides equity by, so a binary approximation here would
    reach the wire as a quantity nobody chose.

    ``symbols``, when given, is the set of symbols *the book holds*, and
    each one must be priced: the first held symbol with no ``markPrice`` in
    the document raises :class:`RouterMarkPriceError` naming it, which is
    the feature's *"returning a missing_mark_price refusal naming the symbol
    when a symbol the book holds has no mark price"*.  Iterated in the
    order given, so the same book and the same document always name the same
    symbol.  ``None`` means *no such check was asked for* and every priced
    symbol in the document is returned; an empty collection is a real ask
    whose answer is the empty, unchecked read, so the two are told apart
    rather than conflated.

    Symbols the document prices but the book does not hold are returned
    too.  The function's contract is *one mark per priced symbol*, and
    narrowing it to the book would hide the fact that a held symbol was
    missing — the check above exists precisely because the caller, not this
    reader, knows which symbols matter.
    """

    rows = _rows(document, what="BingX premiumIndex")
    marks: dict[str, Decimal] = {}
    claimed: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise RouterVehicleDocumentError(
                "the BingX premiumIndex document carries a non-object row at "
                f"index {index} ({type(row).__name__}); every row of this "
                "document is one symbol's mark"
            )
        symbol = _symbol(
            row, what="the BingX premiumIndex document", index=index
        )
        # Claimed before the absent-mark skip, so a symbol stated twice is
        # refused rather than quietly keeping whichever row came last.
        _claim(symbol, claimed, what="BingX premiumIndex")
        raw = row.get("markPrice")
        if raw is None:
            # A symbol with no mark is not this function's fault to raise
            # unless the book holds it; the check below names it if it does.
            continue
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise RouterVehicleDocumentError(
                f"the BingX premiumIndex document states "
                f"markPrice={raw!r} ({type(raw).__name__}) for {symbol!r}; "
                "expected a decimal spelling"
            )
        try:
            mark = Decimal(str(raw))
        except InvalidOperation as exc:
            raise RouterVehicleDocumentError(
                f"the BingX premiumIndex document states markPrice={raw!r} "
                f"for {symbol!r}, which is not a decimal"
            ) from exc
        if not mark.is_finite():
            raise RouterVehicleDocumentError(
                f"the BingX premiumIndex document states markPrice={raw!r} "
                f"for {symbol!r}, which is not a finite decimal"
            )
        marks[symbol] = mark

    if symbols is not None:
        if isinstance(symbols, (Mapping, str)):
            # The two ways of handing in *not* a collection of symbols: the
            # book document itself (iterating a mapping walks its fields) or
            # a single bare symbol (iterating a string walks its
            # characters).  Either would otherwise reach the check below
            # with perfectly well-formed strings — "book_id", "B" — and come
            # back as a missing_mark_price blaming the venue for a document
            # that was never wrong.  Refused as a malformed ask instead.
            raise RouterVehicleDocumentError(
                "resolve_bingx_mark_prices takes the symbols the book "
                f"holds, got {type(symbols).__name__}; iterating that would "
                "walk the book document's own fields (or a symbol's own "
                "characters) and blame the venue for a document that is "
                "fine — hand it the symbols (e.g. mapping.keys()), or a "
                "single-element collection for one symbol"
            )
        for symbol in symbols:
            if not isinstance(symbol, str) or not symbol:
                raise RouterVehicleDocumentError(
                    "resolve_bingx_mark_prices was asked to check "
                    f"{symbol!r} ({type(symbol).__name__}) as a held symbol; "
                    "every held symbol is a non-empty string"
                )
            if symbol not in marks:
                raise RouterMarkPriceError(
                    f"{MARK_PRICE_CODE}: the book holds {symbol!r} but the "
                    "BingX premiumIndex document prices no such symbol; a leg "
                    "that cannot be marked cannot be sized, and a quantity "
                    "invented for it would be a position the book never "
                    "decided to hold",
                    symbol=symbol,
                )
    return marks
