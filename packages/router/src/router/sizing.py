"""Feature 2: the book's weights become the venue's own quantities.

additions_spec_bingx_dry_run.xml, "BingX VST Dry Run", feature 2 at its
seam — *System sizes final target weights into signed contract quantity
deltas against RouterSymbolFilters and a Decimal mark per symbol: equity
times weight divided by mark price, truncated toward zero onto the
symbol's step grid, minus the position currently held.*  This module is
that sentence as one call: :func:`size_contract_deltas` answers the
signed change per symbol — the order the dry run would send — and
raises :class:`RouterOrderSizingError` for a leg it cannot size.  It
sizes; it never rounds a submission (feature 312's gate judges one),
never judges a floor (313's, and the minimum quantity, are read at
assembly), and never sends anything.

**This is the step the grid refusal exists to serve.**
:mod:`router.rounding` refuses an off-grid submission and deliberately
names the two neighbouring values — *"the refusal names the two
neighbours so the sizing step can choose, and choosing is the decision
this module exists to keep in that layer."*  This module is that layer.
The choice it makes is fixed by its own sentence: *truncated toward
zero*, so the quantity it answers never exceeds its target — a long
target is rounded down and a short target toward zero shrinks in
magnitude, and on either side the executed book never overshoots the
book that was decided.  The other neighbour (feature 312's *above*) is
a position larger than the construction chose, and the residue it
leaves (feature 312's *below*) is bounded by the one step every venue
states, so the truncation is a decision with a bound, made where its
consequence is visible against the weights it answers to.

**The weights arrive through feature 305's seam, and only that way.**
``docs/nullius-tech-architecture.md`` §13.1 ends the book manager's
chain in *target weights* and §13.2 begins the execution engine that
consumes them, and feature 305's own sentence — *the only output
consumed by the order layer* — is why :func:`size_contract_deltas`
reads the published record's ``weights`` surface rather than accepting
a bare mapping: a book handed to the order path as a dict is a book
nothing published, and the spec's integration points say the dry run
publishes through :func:`book.final_target_weights` *"so the weights
arrive through feature 305's seam rather than as a bare dict."*  The
seam is read, not type-gated — any value exposing the same ``weights``
mapping of symbol to weight is sized — which is also why this module
imports nothing from the book member: the surface is the contract.

**One float crosses this seam, and it is decimalized, never
multiplied.**  The published weights are the seam's own floats —
:class:`book.FinalTargetWeights` coerces and freezes them as reals —
and every other term here is an exact
:class:`~decimal.Decimal` built from a string the venue or the book
spelled.  A float weight is read *once*, through
:func:`decimal.Decimal` on its shortest round-tripping spelling — the
number the book's author wrote (``0.1`` reads as ``Decimal("0.1")``,
never the binary ``0.1000000000000000055511151231...`` the float also
is) — and from there the arithmetic is decimal end to end: no binary
multiplication ever touches the equity or the mark, the house rule the
spec states as *money and quantities are decimal.Decimal built from the
venue's strings, never float arithmetic*.  A weight offered as anything
but a real — a string, a boolean, a NaN dressed as a number — is
refused naming it, the read-exactly-or-refuse discipline feature 312
holds every term of a submission to.

**A delta, not a level.**  The sentence says *minus the position
currently held*, and the subtraction is the point: an order is the
change that moves the account from where it stands to where the book
decided, so a symbol already sitting on its target answers ``0`` — and
a zero delta produces no order, the same rule feature 312 states for a
leg weighted zero.  A position the ``positions`` mapping does not carry
is a position not held: the book records what *is* held, and absence
there is a flat leg rather than a missing fact (the opposite call the
marks and filters below take, where absence is a leg that cannot be
sized).  A position in a symbol the published weights do not carry is
left alone — the instruction names no weight for it, and inventing a
flatten would be *a position decision the construction never made*, in
feature 305's own words: if the deployment wants a leg gone, the book
publishes it weighted zero.

**Absence is not zero where zero would trade.**  A symbol the book
holds that the filters carry no entry for, or the marks no price for,
is refused by name — never silently skipped, and never sized against a
defaulted grid or an invented price, which would each be exactly the
hardcoded venue constant feature 311 forbids and PRD C9 restates
(*"Never hardcode."*).  The refusal is what makes the join honest: the
legs the venue's own documents cannot size — a contract whose status is
not tradable, a held symbol with no mark price — are recorded as
refused legs where the documents were read (feature 1's
:mod:`router.bingx_documents` refusals), and what reaches this module
is expected to be what remains, sizeable.  A wiring that hands this
module a book holding a leg it cannot size is told which leg and which
term, before any order is built on a guess.

**The grids arrive as feature 310's own value, never as literals.**
Each leg is truncated onto the step grid of the
:class:`~router.exchange_info.RouterSymbolFilters` the caller hands
for that symbol — the same structural rule
:func:`router.rounding.require_rounded_order`
holds: no parameter of this verb accepts a bare grid, so the grid a
quantity is truncated onto is the translated document's own field by
construction, and a symbol whose filters carry no step size at all is
refused, because a quantity that cannot be put on a grid cannot be
sized onto one.  The filters must be the held symbol's own — a
quantity truncated onto *another* symbol's step grid is a size about
the wrong instrument, the one-symbol-one-spelling-one-grid rule
features 312 and 317 both hold.

**Deterministic, and cheap to import.**  A pure function of its terms:
symbols sized in sorted order, no clock, no state, no store, no I/O,
every arithmetic under the default decimal context — the same context
:mod:`router.rounding`'s modulo and :mod:`router.notional`'s product
run under — so the same book, equity, marks, filters and positions
answer the same deltas in any process on any machine, which is what
makes the verb safe for the separate order-router process §13.2 and
feature 320 separate.  Nothing to persist (the deltas are re-derivable
from the terms, and the terms are the book's own record), so no
``@register``, no seat export, no migration.  Stdlib only —
:mod:`decimal`, :class:`collections.abc.Mapping` and
:mod:`router.errors` — so a deployment that never sends an order pays
nothing to import it.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

from .errors import RouterError
from .exchange_info import RouterSymbolFilters

__all__ = [
    "ORDER_SIZING_CODE",
    "RouterOrderSizingError",
    "size_contract_deltas",
]

#: Feature 2's greppable token, for every refusal this module raises.
#:
#: One word for the whole module's refusals — the shape
#: :data:`router.errors.ORDER_ROUNDING_CODE` and
#: :data:`router.errors.ORDER_POSTURE_CODE` set — so an operator greps
#: one token and lands on the sizing layer, whatever the leg was refused
#: for: a book that arrived unpublished, a held symbol the documents
#: cannot size, a grid that is not a grid, a mark that is not a price, a
#: term offered as a float.  It deliberately does not spell ``delta`` or
#: ``quantity`` alone: the refusal is about the act of sizing, not about
#: one of its terms.
ORDER_SIZING_CODE = "order_sizing"


class RouterOrderSizingError(RouterError):
    """The book's weights could not be sized into contract quantity deltas.

    additions_spec_bingx_dry_run.xml feature 2 is the sentence this
    failure belongs to: *equity times weight divided by mark price,
    truncated toward zero onto the symbol's step grid, minus the position
    currently held.*  Every term of that arithmetic is a fact somebody
    else already guaranteed — the weights a book feature 305 published,
    the grids a venue document feature 1 translated, the mark a
    premiumIndex response carried, the position the account holds — and
    this error is raised for a term that is not there to be read: an
    unpublished book, a held symbol no document covers, another symbol's
    grid, a missing step size, a mark at or below zero, a float offered
    where a decimal is read.  Never for a *small* delta — an order the
    floors would refuse is feature 313's and feature 4's judgment at
    assembly, and a delta of exactly zero is not a failure but the
    absence of an order.

    A sibling of :class:`~router.errors.RouterOrderRoundingError` and
    :class:`~router.errors.RouterOrderPostureError` rather than a child
    of either: sizing precedes judgment, and a caller told to catch a
    rounding error for a book that was never sizeable would repair the
    wrong file.  Defined here rather than in :mod:`router.errors`
    because this addition's refusals stay in the module that raises
    them, so parallel features never edit another module's vocabulary.

    Every message opens with :data:`ORDER_SIZING_CODE` and names the
    offending value, because the sizing layer is where the book's
    arithmetic becomes an order's size, and the operator's grep is the
    first place that fact has to reach.
    """


def _as_decimal(value: Any, term: str, ground: str) -> Decimal:
    """Return ``value`` as an exact decimal, or refuse it by name.

    The two spellings this module reads are the speaker's own string and
    an exact :class:`~decimal.Decimal`, and nothing is read
    approximately — the rule :func:`router.rounding._as_decimal` states
    for a submission's terms, held here for the book's and the venue's:
    a :class:`float` is a binary approximation of a decimal no venue
    ever sent, and the one float this module legitimately sees (a
    published weight) is decimalized by name in :func:`_as_weight`, never
    read through here.  ``NaN`` and the two infinities *parse* as
    decimals and are refused separately, because an equity or a mark
    that is not a number cannot scale or price anything.
    """
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise RouterOrderSizingError(
                f"{ORDER_SIZING_CODE}: {term} {value!r} is not a decimal the "
                f"book can be sized against; {ground} (feature 2)"
            ) from exc
    else:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: {term} must be a decimal string or a "
            f"Decimal, got {value!r} ({type(value).__name__}); a float is a "
            "binary approximation of a decimal no venue ever sent, and a "
            "term read approximately would size the book approximately; "
            f"{ground} (feature 2)"
        )
    if not number.is_finite():
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: {term} must be a finite decimal, got "
            f"{number!r}; a value that is not a number cannot size a "
            f"position, and {ground} (feature 2)"
        )
    return number


def _as_weight(value: Any, symbol: str) -> Decimal:
    """Return ``value`` as one published weight, decimalized — or refuse it.

    The weight is the one term that legitimately arrives as a
    :class:`float`: feature 305's seam coerces the book's reals and
    freezes them, so the order layer reads floats however the book was
    built.  A float is read through its *shortest round-tripping
    spelling* — ``str(0.1)`` is ``"0.1"``, the number the book's author
    wrote — and decimalized once, so the arithmetic downstream is
    decimal end to end and the binary expansion the float also carries
    (``0.1000000000000000055511151231...``) never touches the equity or
    the mark.  An exact :class:`~decimal.Decimal` is read verbatim and
    an :class:`int` exactly; a boolean, a string, a NaN or an infinity
    is refused naming the value, the same fact
    :func:`book._publish._book_of` refuses at publication — a weight
    that is not a finite real is not a size any venue could hold, and a
    book that reached this layer unread is a book something else
    published.
    """
    if isinstance(value, bool):
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the target weight for {symbol!r} must be "
            f"a finite real, got {value!r} (bool); a boolean is not a size "
            "any venue could hold, and the weight is the term every "
            "quantity here is scaled by (feature 2)"
        )
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (int, float)):
        number = Decimal(str(value))
    else:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the target weight for {symbol!r} must be "
            f"a finite real (int, float or Decimal), got {value!r} "
            f"({type(value).__name__}); the book spells its weights as "
            "reals and the seam publishes them as reals, and a weight read "
            "any other way is a weight something other than the book "
            "wrote (feature 2)"
        )
    if not number.is_finite():
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the target weight for {symbol!r} is "
            f"not finite ({value!r}); a NaN or ±inf would reach the venue "
            "dressed as a position, and no truncation onto a venue's step "
            "size could make one of it (feature 2)"
        )
    return number


def _step_grid(filters: Any, symbol: str) -> Decimal:
    """Return ``filters``' step grid for ``symbol`` as a positive decimal.

    The grid a quantity is truncated onto is the translated venue
    document's own field — ``RouterSymbolFilters.step_size`` — read
    exactly as the document spelled it, and refused when it is absent or
    not a positive decimal: a leg the venue states no quantity grid for
    cannot be sized onto one, and a grid this module defaulted would be
    exactly the hardcoded venue constant feature 311 forbids.  The
    filters must also be the held symbol's own, because a quantity
    truncated onto another symbol's grid is a size about the wrong
    instrument — one symbol, one spelling, one grid, the rule
    :func:`router.rounding.require_rounded_order` holds the same term
    to.
    """
    if not isinstance(filters, RouterSymbolFilters):
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the filters held for {symbol!r} must be "
            f"feature 310's RouterSymbolFilters, got {filters!r} "
            f"({type(filters).__name__}); the grid a quantity is truncated "
            "onto is the translated venue document's own field, and a value "
            "that is not that carries no grid to size against (feature 2)"
        )
    if filters.symbol != symbol:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the book holds {symbol!r} but the "
            f"filters are {filters.symbol!r}'s; a quantity truncated onto "
            "another symbol's step grid is a size about the wrong "
            "instrument — one symbol, one spelling, one grid (feature 2)"
        )
    if filters.step_size is None:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the venue states no step size for "
            f"{symbol!r} — the translated contract document carries no "
            "quantity grid for the symbol — so its weight cannot be sized "
            "onto the venue's grid at all; the leg is refused rather than "
            "sized unsnapped, because a grid this module defaulted would "
            "be exactly the hardcoded venue constant feature 311 forbids "
            "(feature 2)"
        )
    step = _as_decimal(
        filters.step_size,
        f"the step size for {symbol!r}",
        "the step size is the venue's quantity grid as the translated "
        "contract document spells it",
    )
    if step <= 0:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the step size for {symbol!r} must be a "
            f"positive decimal, got {step!r}; a grid of zero divides "
            "nothing — every quantity would sit on it and none would be "
            "quantised — and a negative grid is one no venue states "
            "(feature 2)"
        )
    return step


def _mark_price(marks: Mapping[str, Any], symbol: str) -> Decimal:
    """Return the Decimal mark for ``symbol``, or refuse what cannot size it.

    A weight becomes a quantity only through a price, and the only
    price this module reads is the mark the caller holds for the symbol
    — feature 1's decimalized premiumIndex, exact as the venue spelled
    it.  A held symbol with no mark is refused by name rather than
    skipped or priced at an invented figure, and a mark at or below zero
    is refused because it is not a price any venue can mark at:
    dividing by it would size a mirrored or infinite book.  Positive is
    arithmetic, not a venue bound restated — the venue's own minimum
    price is a filter this module never reads.
    """
    try:
        held = marks[symbol]
    except KeyError:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: no mark price is held for {symbol!r}; a "
            "weight becomes a contract quantity only through the price it "
            "is sized against, and a mark this module invented would be a "
            "hardcoded venue constant — read the venue's own premiumIndex "
            "(router.bingx_documents) and size the legs it prices (feature 2)"
        ) from None
    mark = _as_decimal(
        held,
        f"the mark price for {symbol!r}",
        "the mark price is what a weight is sized against, as the venue's "
        "own premiumIndex spelled it",
    )
    if mark <= 0:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the mark price for {symbol!r} must be "
            f"positive, got {mark!r}; a mark at or below zero is not a "
            "price any venue can mark at, and dividing by one would size a "
            "book no account holds (feature 2)"
        )
    return mark


def _held_position(positions: Mapping[str, Any], symbol: str) -> Decimal:
    """Return the position currently held in ``symbol``, exact, or zero.

    A position the mapping does not carry is a position not held: the
    book records what *is* held, so absence here is a flat leg rather
    than a missing fact — the opposite of the marks and the filters,
    where absence is a leg that cannot be sized, and the difference is
    that a zero position trades nothing while an invented price or grid
    trades plenty.  A held position may carry either sign — a short is
    a position — and its spelling is read exactly, float refused by
    name, the same two-spelling rule every decimal term here holds.
    """
    if symbol not in positions:
        return Decimal(0)
    return _as_decimal(
        positions[symbol],
        f"the position held in {symbol!r}",
        "the position is the quantity the account already holds, and the "
        "delta is the change that moves it to the book's target",
    )


def _truncated_toward_zero(value: Decimal, step: Decimal) -> Decimal:
    """Return ``value`` snapped onto ``step``, truncated toward zero.

    The sentence's own arithmetic: the value over the step, made whole
    with :const:`decimal.ROUND_DOWN` — which rounds *toward zero*, not
    toward minus infinity, so a short target shrinks in magnitude the
    same way a long target is rounded down — then one exact
    multiplication back onto the grid.  The division runs under the
    default decimal context, the same context every other Decimal
    arithmetic in this member runs under, so the truncation is as
    deterministic as the modulo :mod:`router.rounding` judges with; the
    residue it discards is bounded by the one step, and discarding it
    is the decision — an order that never exceeds its target — that
    feature 312's refusal moves into this layer for.
    """
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _published_weights(weights: Any) -> Mapping[str, Any]:
    """Read the ``weights`` surface off feature 305's published record.

    The surface, never the type: any value exposing a ``weights``
    mapping of symbol to weight — a ``book.FinalTargetWeights``, the
    construction's own ``book.TargetWeights``, or a test's stand-in —
    is the seam's output, while a bare dict handed in its place is
    refused, because the spec's integration points are explicit that
    the weights arrive *"through feature 305's seam rather than as a
    bare dict"*: a book nothing published is a book no construction
    stands behind, and sizing it would execute arithmetic the chain
    never answered for.  An empty surface is refused the same way — an
    empty instruction is the absence of a book, not a book held flat
    (a flat book is every symbol weighted zero, and that is a decision
    publication is entitled to make).
    """
    surface = getattr(weights, "weights", None)
    if surface is None:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the weights must arrive through feature "
            "305's seam — publish the book with book.final_target_weights "
            f"and hand the record it answers, got {weights!r} "
            f"({type(weights).__name__}); a bare dict is a book nothing "
            "published, and the order layer sizes the instruction the "
            "construction issued, never one something else assembled "
            "(feature 2)"
        )
    if not isinstance(surface, Mapping):
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the published weights are a mapping of "
            f"symbol to weight, got {surface!r} ({type(surface).__name__}); "
            "the order layer holds a book one symbol at a time, and a "
            "value that is not a mapping names no book to size (feature 2)"
        )
    if not surface:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the published weights cover at least one "
            "symbol — got none; an empty instruction is the absence of a "
            "book rather than a book held flat, and a flat book is every "
            "symbol weighted zero, which is a decision publication is "
            "entitled to make (feature 2)"
        )
    return surface


def size_contract_deltas(
    *,
    weights: Any,
    equity: Any,
    marks: Any,
    filters: Any,
    positions: Any,
) -> dict[str, Decimal]:
    """Feature 2's verb: size the published book into signed order deltas.

    For every symbol the published weights carry, in sorted order:
    ``equity × weight ÷ mark``, truncated toward zero onto the symbol's
    step grid, minus the position currently held — answered as a
    ``dict`` of the signed deltas, keyed by symbol in sorted order, each
    an exact :class:`~decimal.Decimal` whose spelling is the grid's own
    (a ``0.0001`` grid answers four decimal places).  A delta of
    exactly zero is *omitted*: a leg already at its target ships no
    order, the rule feature 312 states for a leg weighted zero.

    Each argument is a required keyword with no default:

    * ``weights`` — feature 305's published record, read by its
      ``weights`` surface (:func:`_published_weights`); a bare dict is
      refused, and the one float it legitimately carries per symbol is
      decimalized by name (:func:`_as_weight`).
    * ``equity`` — the account's equity as the book spelled it, an
      exact decimal (string or :class:`~decimal.Decimal`; a float is
      refused by name).  Negative is refused — a negative equity scales
      every target into its mirror image, a book no account holds —
      while zero is sized, answering the flatten-everything book: every
      target zero, every delta the negative of the position held.
    * ``marks`` — the Decimal mark price per symbol, as feature 1's
      premiumIndex reader answers it.  Symbols the mapping carries
      beyond the book are ignored; a held symbol it does not carry is
      refused by name.
    * ``filters`` — feature 310's
      :class:`~router.exchange_info.RouterSymbolFilters` per symbol, as
      feature 1's contracts translator answers it.  The step grid is
      the document's own field or the leg is refused; extra symbols are
      ignored.
    * ``positions`` — the signed contract quantities currently held, as
      the book spells them.  A symbol the mapping does not carry is a
      flat leg; a position in a symbol the published weights do not
      carry is left alone — the instruction names no weight for it, and
      inventing a flatten would be a position decision the construction
      never made.

    **The refusals run in a fixed order.**  The published record first
    (it names the whole instruction), then the equity (the one scalar
    every target scales by), then each symbol in sorted order — its
    weight, the venue's standing facts (the filters entry, then the
    grid, then the mark), then the account's own term (the position) —
    so a book wrong in several legs is refused for the first
    deterministically, the order :func:`router.rounding.require_rounded_order`
    judges a submission's terms in.

    Deterministic by construction: a pure function of its terms under
    the default decimal context, no clock, no state, no store, no I/O —
    the same book answers the same deltas in any process, which is what
    makes the verb safe for the separate order-router process §13.2
    and feature 320 demand, and the whole of the contract.  Nothing is
    rounded for the venue (feature 312 judges the submission against
    the same grid this layer truncated onto), nothing is judged against
    a floor (feature 313's notional and the venue's minimum quantity
    are read where the order is assembled), and nothing is sent.
    """
    book = _published_weights(weights)

    equity_value = _as_decimal(
        equity,
        "equity",
        "the equity is the one scalar every target quantity is sized by",
    )
    if equity_value < 0:
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: equity must not be negative, got "
            f"{equity_value!r}; a negative equity scales every target "
            "into its mirror image — a book no account holds — while "
            "zero equity is sized and answers the flatten-everything "
            "book (feature 2)"
        )

    if not isinstance(marks, Mapping):
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the marks are a mapping of symbol to "
            f"Decimal mark price, got {marks!r} ({type(marks).__name__}); a "
            "weight becomes a quantity only through a price, and a value "
            "that is not a mapping names no price to size against "
            "(feature 2)"
        )
    if not isinstance(filters, Mapping):
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the filters are a mapping of symbol to "
            f"RouterSymbolFilters, got {filters!r} "
            f"({type(filters).__name__}); the grid each quantity is "
            "truncated onto is the venue document's own field, and a value "
            "that is not a mapping names no grid to size onto (feature 2)"
        )
    if not isinstance(positions, Mapping):
        raise RouterOrderSizingError(
            f"{ORDER_SIZING_CODE}: the positions are a mapping of symbol to "
            f"the signed quantity held, got {positions!r} "
            f"({type(positions).__name__}); the delta is the change that "
            "moves the account from what it holds to the book's target, "
            "and a value that is not a mapping names nothing held "
            "(feature 2)"
        )

    deltas: dict[str, Decimal] = {}
    for symbol in sorted(book):
        if not isinstance(symbol, str) or not symbol.strip():
            raise RouterOrderSizingError(
                f"{ORDER_SIZING_CODE}: the published weights must be keyed "
                f"by non-empty symbol names — got {symbol!r}; the order "
                "layer routes an instruction to a symbol, and a delta "
                "cannot be attributed to a name the book does not carry "
                "(feature 2)"
            )
        weight = _as_weight(book[symbol], symbol)
        try:
            symbol_filters = filters[symbol]
        except KeyError:
            raise RouterOrderSizingError(
                f"{ORDER_SIZING_CODE}: no venue filters are held for "
                f"{symbol!r}; the translated contract document states no "
                "grid for the symbol (or it was never translated), and a "
                "quantity that cannot be put on a grid cannot be sized "
                "onto one — record the leg the venue's own documents "
                "refuse (router.bingx_documents answers not_tradable and "
                "missing_mark_price) and size the legs that remain "
                "(feature 2)"
            ) from None
        step = _step_grid(symbol_filters, symbol)
        mark = _mark_price(marks, symbol)
        held = _held_position(positions, symbol)

        target = _truncated_toward_zero(
            equity_value * weight / mark, step
        )
        delta = target - held
        if delta == 0:
            # A zero delta produces no order — a leg already at its
            # target ships nothing, and an omitted key says so without
            # inventing an order the book did not decide.
            continue
        deltas[symbol] = delta
    return deltas
