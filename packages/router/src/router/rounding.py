"""Feature 312: the submission's arithmetic — on the venue's grids, or
refused.

app_spec.xml, "Order Routing & Venue Filters", feature 312: *System
rejects an order submission not rounded to the venue step size and tick
size.*  ``docs/alpha-engine-prd.md`` C9 names the two grids and the law
that keeps them honest in one line: *"Read ``LOT_SIZE``, ``NOTIONAL``,
``PRICE_FILTER``, ``stepSize``, ``tickSize`` from ``exchangeInfo`` at
startup and daily. Never hardcode."*  Feature 310 fetched those
constants and persisted them verbatim; this module is the point the
order path finally *uses* them — the last gate a submission passes
through before anything is keyed, priced against a weight budget, or
sent.

**Why the system rejects rather than rounds.**  Rounding is not a
transport detail; it is a sizing decision.  The quantity on the wire is
the book's final target weights (features 305, 309) made whole against
the equity and the price, and those weights are *the only output the
order layer consumes* — so a quantity silently rounded inside the send
path is the executed book drifting from the target book by a coercion
nobody chose and nothing records.  Round down and residual exposure is
left standing; round up and the position is larger than the book
decided.  Either way the drift is bounded by one step, and either way
it was decided by a ``%`` in the wrong layer.  The refusal moves the
rounding back to where its consequence is visible: the sizing step,
against the weights it answers to, where a rounded quantity is a
decision a human can read in the diff.  And the venue enforces the same
rule anyway — an unrounded order comes back refused in the venue's own
vocabulary, after feature 318's weight budget was already spent for
nothing; this gate refuses the submission *before* a single weight unit
is, in this member's vocabulary, with the offending value named.

**The judgment is exact, and decimalisation happens here.**
:mod:`router.exchange_info` keeps every fetched value as the venue's
own string spelling precisely because "decimalisation and rounding are
the order path's business (features 312-313)" — and this module is
where that business is done.  The on-grid test is
:class:`decimal.Decimal` modulo, exact for finite decimals:
``Decimal("0.3") % Decimal("0.1")`` is zero, where the float
``0.3 % 0.1`` is ``0.09999999999999998`` — a submission the venue
would happily book, refused by a representation error.  A
:class:`float` handed to this gate is therefore refused **by name**
rather than read approximately: a float is a binary approximation of a
decimal no venue ever sent, and a gate that read one would misjudge the
very grid it was offered to.  The two spellings the gate reads are the
venue's own string and an exact :class:`~decimal.Decimal`; everything
else — ``int``, ``bool``, ``None`` — is refused naming the value, the
read-exactly-or-refuse discipline feature 314 holds its durations to
one module over.

**The grids arrive as feature 310's own value, never as literals.**
The verb takes the :class:`~router.exchange_info.RouterSymbolFilters`
the order path just read
(:meth:`~router.store.RouterExchangeInfoStore.filters_for`), so the
grids this gate judges against are the fetched document's own narrowed
fields by construction — there is no second parameter a caller could
hand a constant to, which is feature 311's *"rejects any hardcoded
venue constant in the order path"* made structural one feature early.
And when the venue states no grid, the gate refuses rather than
improvises: a ``None`` step size or tick size means the current
exchangeInfo version carries no ``LOT_SIZE`` / ``PRICE_FILTER`` for
the symbol, and a submission that cannot be judged is not a submission
that passed — defaulting a grid here would be exactly the hardcoded
venue constant the category forbids, and passing the order through as
unconstrained would trade a symbol whose admissibility was never
measured.  The same refusal answers ``filters=None`` whole: a symbol
the current version does not carry (or a store with no version yet)
is not tradeable off a stale or invented grid — the same stance
:meth:`~router.store.RouterExchangeInfoStore.filters_for` itself takes
when it answers ``None`` rather than falling back to an older version.

**Two grids, and only two.**  The sentence names the step size and the
tick size, and this module judges exactly those: the quantity against
``LOT_SIZE.stepSize``, the price against ``PRICE_FILTER.tickSize``.
Feature 310 persists seven fields per symbol precisely so each later
feature reads what its own sentence names — the minimum notional is
feature 313's, and ``minQty`` / ``maxQty`` / ``minPrice`` /
``maxPrice`` are bounds the venue states and enforces on its side of
the wire; a gate that judged them here would be two features wearing
one module.  What *is* this gate's own ground is the arithmetic of its
terms: a quantity or price at or below zero is not a size or a price
any venue can book (positivity is arithmetic, not a venue constant),
and a grid that is not a positive decimal is not a grid — a step of
zero divides nothing, and the modulo would not be a quantisation at
all.

**The symbol is the join, and it is judged.**  The order's symbol and
the filters' own symbol must agree verbatim, because a quantity judged
against another symbol's step size is a verdict about the wrong
instrument — one symbol, one spelling, one grid, the rule features 316
and 317 hold the same term to.  A symbol that states nothing names no
leg, and no grid to be judged against.

**The order the refusals run in is fixed.**  Symbol, then the filters
themselves (present, the right value, the right symbol), then the two
grids, then the quantity, then the price — the venue's standing facts
before the submission's own terms, the same order feature 315's gate
judges its mode before its scope.  A submission wrong in several ways
is refused for the first one, deterministically, so two operators
reading one refusal read the same repair.

**The verdict rides beside its terms.**  :class:`RoundedOrder` carries
the decimalised quantity and price next to the grids they were judged
against — the shape :class:`~router.posture.OrderPosture` and
:class:`~router.client_order_id.ClientOrderId` state for their own
verdicts, for the same reason: the value a caller branches on is also
the record an operator audits, and the grids are the whole of the
*why*.  Direct construction re-runs the same validators and the same
two modulo checks, so a value that claimed roundedness its own terms
contradict cannot exist — the law feature 316 states for a key that
disagrees with its terms, one feature over.

**No table, no component, no clock, no I/O.**  The judgment is a pure
function of the submission's terms and the fetched filters — the same
ask answers the same verdict in any process, which is what makes it
safe for the processes §13.2 and feature 320 deliberately separate: a
restarted router re-judging an order mid-rebalance agrees with the
process it replaced without speaking to it, exactly as two processes
agree on feature 316's key.  Nothing to persist (the verdict is
re-derivable from the terms, and the terms are recorded wherever the
order is), so no ``@register`` is added — the member still registers
exactly one component, feature 310's exchangeInfo store — no seat
export and no migration either.  Stdlib only, and import-cheap —
``dataclasses``, ``decimal`` and :mod:`router.errors` — so the
factory's scan pays nothing for the gate and a deployment that never
submits an order never runs it.

**What this module deliberately does not do.**  It does not *round* —
no nearest-value answer, no floor, no ceiling helper: the refusal names
the two neighbours so the sizing step can choose, and choosing is the
decision this module exists to keep in that layer.  It does not *judge
the notional* (feature 313's sentence) or *restate the venue's min/max
bounds*.  It does not *read the store* — the caller holds the filters
it read, and a gate that fetched its own would be a second, racing
reader on the order path.  It does not *place*, *price* or *size*
anything: feature 314 decides how the order crosses, the book's
weights decided whether to trade at all, and this module only refuses
a submission the venue's own grids could not book.  And it does not
*speak to the venue* — the venue's refusal of an unrounded order
arrives too late and in the wrong vocabulary; this one is the system's
own, before the send.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import ORDER_ROUNDING_CODE, RouterOrderRoundingError
from .exchange_info import RouterSymbolFilters

__all__ = [
    "RoundedOrder",
    "require_rounded_order",
]


def _as_decimal(value: Any, term: str, ground: str) -> Decimal:
    """Return ``value`` as an exact decimal, or refuse it by name.

    The two spellings this gate reads are the venue's own string and an
    exact :class:`~decimal.Decimal`, and nothing is read approximately: a
    :class:`float` is a binary approximation of a decimal no venue ever
    sent — ``0.1`` as a float is not on a ``0.1`` grid — so a value
    offered in any other type is refused naming it.  ``NaN`` and the two
    infinities *parse* as decimals and are refused separately, because a
    size or a grid that is not a number cannot be a multiple of anything.
    """
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise RouterOrderRoundingError(
                f"{ORDER_ROUNDING_CODE}: {term} {value!r} is not a decimal "
                f"an order can carry; {ground} (feature 312)"
            ) from exc
    else:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: {term} must be a decimal string or a "
            f"Decimal, got {value!r} ({type(value).__name__}); a float is a "
            "binary approximation of a decimal no venue ever sent, and a "
            "value read approximately would be misjudged by the very grid "
            f"it was offered to; {ground} (feature 312)"
        )
    if not number.is_finite():
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: {term} must be a finite decimal, got "
            f"{number!r}; a value that is not a number cannot sit on a grid, "
            f"and {ground} (feature 312)"
        )
    return number


def _validated_symbol(value: Any) -> str:
    """Return ``value`` as the leg an order is for, or refuse what cannot be one.

    Non-empty text, stripped, otherwise **verbatim** — the venue's own
    spelling is the key the exchangeInfo filters are filed under
    (:meth:`~router.store.RouterExchangeInfoStore.filters_for`), so a
    symbol this gate case-folded or re-spelled would be judged against
    another symbol's grid, the rule features 316 and 317 hold the same
    term to.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: symbol must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); the symbol is the leg the "
            "order is for and the key the exchangeInfo filters are filed "
            "under, so a submission that names no leg names no grid to be "
            "judged against (feature 312)"
        )
    return value.strip()


def _validated_quantity(value: Any) -> Decimal:
    """Return ``value`` as an order's quantity, or refuse what cannot be one.

    An exact positive decimal.  Positivity is the term's own ground
    rather than a venue bound restated: the book's weights (features
    305, 309) decide *whether* to trade at all and a leg weighted zero
    ships no order, while a negative size would be a direction — and
    direction is the order path's to state, never this gate's to guess.
    """
    number = _as_decimal(
        value,
        "quantity",
        "the quantity names how much of the leg the order carries, and the "
        "venue reads an order's size as a spelled decimal",
    )
    if number <= 0:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: quantity must be positive, got "
            f"{number!r}; a submission of zero or negative size is not a "
            "submission — the book's weights decide whether to trade at all "
            "and a leg weighted zero ships no order, while a negative size "
            "would be a direction, and direction is the order path's to "
            "state, not this gate's to guess (feature 312)"
        )
    return number


def _validated_price(value: Any) -> Decimal:
    """Return ``value`` as an order's price, or refuse what cannot be one.

    An exact positive decimal.  *Positive* is arithmetic rather than a
    venue constant to hardcode: the venue's own minimum price
    (``PRICE_FILTER.minPrice``) is a bound the venue states and enforces
    on its side of the wire, and this gate deliberately does not restate
    it — feature 310 persisted it for whatever later feature's sentence
    names it, and this sentence names only the tick.
    """
    number = _as_decimal(
        value,
        "price",
        "the price names what the order pays per unit of the leg, and the "
        "venue reads prices as spelled decimals",
    )
    if number <= 0:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: price must be positive, got "
            f"{number!r}; a price at or below zero is not a price any venue "
            "can book, and positive is arithmetic rather than a venue "
            "constant — the venue's own minimum (PRICE_FILTER.minPrice) is a "
            "bound the venue states and enforces, and this gate does not "
            "restate it (feature 312)"
        )
    return number


def _validated_step_size(value: Any) -> Decimal:
    """Return ``value`` as the venue's quantity grid, or refuse what cannot be one.

    An exact positive decimal, read exactly as the fetched document
    spells ``LOT_SIZE.stepSize``.  A grid of zero is refused because it
    divides nothing — every value would sit "on" it and none would be
    quantised — and a negative grid because no venue states one; the
    fetched document's spelling is the only authority this module reads.
    """
    number = _as_decimal(
        value,
        "the step size",
        "the step size is the venue's quantity grid as the fetched document "
        "spells it (LOT_SIZE.stepSize)",
    )
    if number <= 0:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the step size must be a positive "
            f"decimal, got {number!r}; a grid of zero divides nothing — "
            "every value would sit on it and none would be quantised — and "
            "a negative grid is one no venue states; the fetched document's "
            "spelling is the only authority this module reads (feature 312)"
        )
    return number


def _validated_tick_size(value: Any) -> Decimal:
    """Return ``value`` as the venue's price grid, or refuse what cannot be one.

    The same rule the step size holds, term for term, over
    ``PRICE_FILTER.tickSize``: an exact positive decimal, because a tick
    of zero divides nothing and a negative tick is one no venue states.
    A separate function rather than a parameterised one for the reason
    :func:`router.margin._validated_book_id` and
    :func:`router.margin._validated_account` are: the refusal names the
    term and the term's own ground, not a placeholder.
    """
    number = _as_decimal(
        value,
        "the tick size",
        "the tick size is the venue's price grid as the fetched document "
        "spells it (PRICE_FILTER.tickSize)",
    )
    if number <= 0:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the tick size must be a positive "
            f"decimal, got {number!r}; a grid of zero divides nothing — "
            "every price would sit on it and none would be quantised — and "
            "a negative grid is one no venue states; the fetched document's "
            "spelling is the only authority this module reads (feature 312)"
        )
    return number


def _require_on_grid(
    value: Decimal,
    grid: Decimal,
    *,
    term: str,
    grid_name: str,
    venue_field: str,
    symbol: str,
) -> None:
    """The sentence's one judgment, in the one place it lives.

    Exact :class:`~decimal.Decimal` modulo — the remainder of the value
    over the grid is zero exactly when the value sits on the grid, with
    no representation error to sit between them.  Kept as one function
    rather than an inline expression at each use, so the quantity's
    check, the price's check and a caller re-verifying a record cannot
    drift the way two spellings of one comparison do.

    The refusal names the two nearest values on the grid, computed by
    subtraction rather than division so the message can never carry a
    rounding of its own: the repair — *round the order where it was
    sized* — is one arithmetic either neighbour states, and choosing
    between them is the sizing step's decision, not this gate's.
    """
    remainder = value % grid
    if remainder == 0:
        return
    below = value - remainder
    if below == 0:
        # Decimal renders a zero that carries a fine exponent as
        # ``0E-8``; the neighbour an operator reads is zero, spelled
        # plainly — the value is the same and the message is for them.
        below = Decimal(0)
    above = below + grid
    raise RouterOrderRoundingError(
        f"{ORDER_ROUNDING_CODE}: {term} {value!r} is not rounded to the "
        f"venue {grid_name} {grid!r} for {symbol!r} ({venue_field}); the "
        f"nearest values on the grid are {below!r} and {above!r} — round "
        "the order where it was sized, against the weights it answers "
        "to, not in the send (feature 312)"
    )


@dataclass(frozen=True)
class RoundedOrder:
    """One submission the venue's grids can book: the terms, decimalised.

    The value :func:`require_rounded_order` answers — the verdict a
    caller branches on and the facts it was made over, kept together
    because a verdict alone could not say *what* was admitted or against
    *which grids*, and both are the audit trail for a submission that
    passed:

    * ``symbol`` — the leg the order is for, the term feature 316 folds
      into the order's key and the one the exchangeInfo filters are
      filed under.
    * ``quantity`` — how much of the leg the order carries, as an exact
      :class:`~decimal.Decimal`.  This is where the venue's string
      spelling becomes a number: decimalisation is the order path's
      business, and this value is the order path's decimal.
    * ``price`` — what the order pays per unit, exact the same way, and
      ready for whatever reads the two together (feature 313's notional
      is one quantity-times-price away, and multiplies *these* fields
      rather than re-parsing the spelling).
    * ``step_size`` and ``tick_size`` — the two grids the terms were
      judged against, decimalised from the fetched filters and carried
      beside the verdict because they are the whole of the *why*.

    All five fields are canonicalised at construction — the symbol
    stripped and otherwise verbatim, the four numbers validated exact and
    positive, and both modulo checks re-run — so a value built by hand
    in a test or reconstructed from a record gets the same judgment the
    verb applies, and a value that claimed roundedness its own terms
    contradict cannot exist.  Frozen, and hashable: a verdict can stand
    as its own key.
    """

    symbol: str
    quantity: Decimal
    price: Decimal
    step_size: Decimal
    tick_size: Decimal

    def __post_init__(self) -> None:
        # Normalize rather than trust, and in the fixed order the verb
        # judges: the venue's standing facts (the grids) before the
        # submission's own terms (the quantity, then the price), so a
        # value wrong in several ways is refused for the first one, the
        # same determinism feature 315's gate keeps.
        symbol = _validated_symbol(self.symbol)
        step = _validated_step_size(self.step_size)
        tick = _validated_tick_size(self.tick_size)
        quantity = _validated_quantity(self.quantity)
        price = _validated_price(self.price)
        _require_on_grid(
            quantity,
            step,
            term="quantity",
            grid_name="step size",
            venue_field="LOT_SIZE.stepSize",
            symbol=symbol,
        )
        _require_on_grid(
            price,
            tick,
            term="price",
            grid_name="tick size",
            venue_field="PRICE_FILTER.tickSize",
            symbol=symbol,
        )
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "step_size", step)
        object.__setattr__(self, "tick_size", tick)


def require_rounded_order(
    *,
    symbol: Any,
    quantity: Any,
    price: Any,
    filters: Any,
) -> RoundedOrder:
    """Feature 312's verb: judge a submission against the venue's grids.

    app_spec.xml, "Order Routing & Venue Filters", feature 312: *System
    rejects an order submission not rounded to the venue step size and
    tick size.*  This is that sentence as one call: it answers the frozen
    :class:`RoundedOrder` for a submission whose quantity sits on the
    step grid and whose price sits on the tick grid, and it raises
    :class:`~router.errors.RouterOrderRoundingError` for one that does
    not — it never rounds, never answers a nearest value, and never
    sends anything.

    Each argument is a required keyword with no default.  ``quantity``
    and ``price`` are the submission's own terms (a decimal string as
    spelled or an exact :class:`~decimal.Decimal` — a float is refused
    by name), and ``filters`` is feature 310's
    :class:`~router.exchange_info.RouterSymbolFilters`, the value the
    order path reads from
    :meth:`~router.store.RouterExchangeInfoStore.filters_for` — the
    grids arrive as the fetched document's own fields or they do not
    arrive at all, which is feature 311's no-hardcoded-constant law made
    structural: there is no parameter here a caller could hand a
    literal grid to.

    **The refusals run in a fixed order.**  The symbol first (it names
    the leg and therefore the grids); then the filters themselves —
    ``None`` (the symbol the current version does not carry, or a store
    with no version yet) is refused, a value that is not feature 310's
    own is refused, and filters filed under a *different* symbol are
    refused, because a quantity judged against another symbol's step
    size is a verdict about the wrong instrument; then the two grids —
    a venue that states no ``LOT_SIZE`` or ``PRICE_FILTER`` for the
    symbol leaves the submission unjudgeable, and unjudgeable is
    refused, never defaulted; then the quantity against the step grid;
    then the price against the tick grid.  A submission wrong in
    several ways is refused for the first one.

    Deterministic by construction: the same terms against the same
    filters answer the same verdict in any process, on any machine, on
    any day, with no clock read and no state consulted — which is what
    makes it safe for the separate order-router process §13.2 and
    feature 320 demand, and the whole of the contract.
    """
    name = _validated_symbol(symbol)
    if filters is None:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: no exchangeInfo filters are held for "
            f"{name!r}; the current version does not carry the symbol (or no "
            "version has been fetched), and a submission that cannot be "
            "judged against the venue's grids is refused rather than passed "
            "as unconstrained — a symbol the venue has stopped listing must "
            "not be tradeable off a stale or hardcoded grid (feature 312)"
        )
    if not isinstance(filters, RouterSymbolFilters):
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: filters must be feature 310's "
            f"RouterSymbolFilters, got {filters!r} "
            f"({type(filters).__name__}); the grids this gate judges "
            "against are the fetched document's own narrowed values, and an "
            "ask that carries no such values states no grids to be judged "
            "against (feature 312)"
        )
    if filters.symbol != name:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the order is for {name!r} but the "
            f"filters are {filters.symbol!r}'s; a quantity judged against "
            "another symbol's step size is a verdict about the wrong "
            "instrument — one symbol, one spelling, one grid (feature 312)"
        )
    if filters.step_size is None:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the venue states no step size for "
            f"{name!r} — the current exchangeInfo version carries no "
            "LOT_SIZE filter for the symbol — so the quantity cannot be "
            "judged against a grid at all; the submission is refused rather "
            "than passed as unconstrained, because a grid this module "
            "defaulted would be exactly the hardcoded venue constant "
            "feature 311 forbids (feature 312)"
        )
    if filters.tick_size is None:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the venue states no tick size for "
            f"{name!r} — the current exchangeInfo version carries no "
            "PRICE_FILTER filter for the symbol — so the price cannot be "
            "judged against a grid at all; the submission is refused rather "
            "than passed as unconstrained, because a grid this module "
            "defaulted would be exactly the hardcoded venue constant "
            "feature 311 forbids (feature 312)"
        )
    return RoundedOrder(
        symbol=name,
        quantity=quantity,
        price=price,
        step_size=filters.step_size,
        tick_size=filters.tick_size,
    )
