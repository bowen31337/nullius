"""Feature 313: the order's value against the venue's floor, or refused.

app_spec.xml, "Order Routing & Venue Filters", feature 313: *System rejects
an order falling below the venue minimum notional, which returns a
``below_min_notional`` error message.*  ``docs/alpha-engine-prd.md`` C9 names
the field this sentence reads beside the two grids feature 312 judges —
*"Read ``LOT_SIZE``, ``NOTIONAL``, ``PRICE_FILTER``, ``stepSize``,
``tickSize`` from ``exchangeInfo`` at startup and daily. Never hardcode."* —
and feature 310 fetched it and persisted it verbatim
(:attr:`~router.exchange_info.RouterSymbolFilters.min_notional`) for exactly
this sentence to read.  One feature after the grids, this module is the
*second* way a well-rounded submission is still not bookable.

**Why this is a different fault from the grids.**  Feature 312 refuses an
order whose quantity is not a multiple of ``LOT_SIZE.stepSize`` or whose
price is not a multiple of ``PRICE_FILTER.tickSize``; this module refuses an
order whose *value* — quantity times price — is less than the
``minNotional`` the venue published.  The two are independent, and the
overlap is the interesting case: a quantity can sit exactly on the step grid
and a price exactly on the tick grid while the two multiply to less than the
venue's minimum.  ``0.5`` BTC at ``8.00`` is a perfectly round order worth
``4.00``, and a venue whose floor is ``5.00`` returns it unbooked.  So the
repairs differ — *round the order where it was sized* against *size the leg
up* — and a caller sent from this refusal to the grid gate would re-round an
order that is already round.  That is why
:class:`~router.errors.RouterBelowMinNotionalError` is its own class in this
member's vocabulary and not an instance of feature 312's, and why its message
opens with :data:`~router.errors.BELOW_MIN_NOTIONAL_CODE` — the exact token
the sentence spells — rather than a name this module chose.

**The floor is a floor, and the venue enforces it anyway.**  Two reasons to
refuse here rather than let the venue do it.  The first is the category's:
the venue's rejection arrives *after* feature 318's weight budget was already
spent on the send, and in the venue's own vocabulary, so a router that only
listened to the venue would pay for the privilege of learning what it could
have known at home.  The second is sharper and is why the sentence says
*below*: a sub-notional order is not a small position, it is **untradeable
dust** — ``docs/alpha-engine-prd.md`` C10 and
``docs/nullius-tech-architecture.md`` §13.3 both name the state one layer up
(*"Below it, stop rather than degrade into untradeable dust"*) — so the
refusal has to reach the sizing step, where the leg's weight is still a
decision, rather than arrive as a venue rejection after the position was
supposed to exist.  This module refuses the order; the risk member's equity
floor at *twice* the same constant (C10's halt) is deliberately **not** this
sentence and is not implemented here — that is a deployment-level stop, and
this is one order's admissibility.

**The judgment reads feature 312's verdict, and that is the dependency
made structural.**  :func:`require_min_notional` takes the
:class:`~router.rounding.RoundedOrder` the grid gate just answered — the
value whose ``quantity`` and ``price`` are already exact
:class:`~decimal.Decimal` values, judged on the venue's two grids — and
multiplies *those* fields rather than re-parsing a spelling.
``app_spec.xml`` says feature 313 depends on 312, and this is what the
dependency is: the floor is judged on an order that has already passed the
grids, so the two gates cannot disagree about what the order's terms are.
It follows that a :class:`float` is refused one gate earlier, by feature
312's own validator, and this module owns no decimalisation at all — it
reads its sibling's exact decimals.  There is consequently **no parameter
here for a quantity or a price**, so a caller cannot ask this gate about an
order that never passed the grids.

**The floor arrives as feature 310's value, never as a literal.**  The
``filters`` argument is the
:class:`~router.exchange_info.RouterSymbolFilters` the order path just read
(:meth:`~router.store.RouterExchangeInfoStore.filters_for`) — the same value
feature 312 judges the grids from — and only its ``min_notional`` field is
read here.  There is no second parameter a caller could hand a constant to,
which is feature 311's *"rejects any hardcoded venue constant in the order
path"* made structural, one feature over from where that law was first made
structural.  And when the venue states no floor, the gate refuses rather
than improvises: a ``None`` means the current exchangeInfo version carries
no ``NOTIONAL`` / ``MIN_NOTIONAL`` for the symbol, and a submission that
cannot be judged is not a submission that passed — defaulting a floor here
would be the hardcoded venue constant the category forbids, and passing the
order through as unconstrained would trade a symbol whose admissibility was
never measured.  The order's symbol and the filters' own symbol must agree
verbatim, for feature 312's reason: a value judged against another symbol's
floor is a verdict about the wrong instrument.

**The multiplication is exact, and the ambient context is not trusted.**
``quantity * price`` over two :class:`~decimal.Decimal` values is *not*
exact by default: the module-level context rounds every product to 28
significant digits, so a quantity and a price whose product carries more
than that would be compared against the floor as a *rounded* number — a
submission the venue would book refused, or worse, a submission it would
refuse booked, by a representation error in the gate that exists to prevent
exactly that class of mistake.  Feature 312's docstring makes the same
argument for its modulo (``Decimal("0.3") % Decimal("0.1")`` is zero, where
the float ``0.3 % 0.1`` is ``0.09999999999999998``); here the risk is in the
*ambient precision* rather than in the type, so the product is computed
under a local context wide enough to hold it exactly —
:func:`_exact_product` — and the comparison happens over the true value.
The floor itself is decimalised exactly the way feature 312 decimalises its
terms: the venue's own string or a :class:`~decimal.Decimal`, a
:class:`float` refused by name.

**"Below" is strict, and zero is a floor nothing falls below.**  The
sentence says *falling below*, so an order worth exactly the venue's minimum
is admissible: at the floor is not below it.  A stated floor of ``"0"`` is
admissible and vacuous — a venue that publishes a minimum of zero has
published a minimum nothing falls below, and refusing the ask would be this
module inventing a bound the venue did not state — while a *negative* floor
is refused, because a negative minimum is not a minimum.  The floor is read
exactly as the fetched document spells it, never coerced to a number on the
way in.

**The verdict rides beside its terms.**  :class:`OrderValue` carries the
order it judged — feature 312's own value, terms and grids together — next
to the floor and the value the two terms multiply to, the shape
:class:`~router.rounding.RoundedOrder` and
:class:`~router.posture.OrderPosture` state for their own verdicts, for the
same reason: the value a caller branches on is also the record an operator
audits, and the three numbers are the whole of the *why*.  The ``value``
field is **computed when omitted** and **checked when stated** — a record
reconstructed from a log that states a value disagreeing with its own terms
is refused, because a value that lies about the order's worth is worse than
no value at all.

**No table, no component, no clock, no I/O.**  The judgment is a pure
function of the order feature 312 answered and the floor the fetched
document states — the same ask answers the same verdict in any process,
which is what makes it safe for the processes §13.2 and feature 320
deliberately separate: a restarted router re-judging an order mid-rebalance
agrees with the process it replaced without speaking to it, exactly as two
processes agree on feature 312's verdict and feature 316's key.  Nothing to
persist (the verdict is re-derivable from the terms and the floor, and both
are recorded wherever the order is), so no ``@register`` is added — the
member still registers exactly one component, feature 310's exchangeInfo
store — no seat export and no migration either.  Stdlib only, and
import-cheap — ``dataclasses`` and ``decimal``, plus this member's own
siblings — so the factory's scan pays nothing for the gate and a deployment
that never submits an order never runs it.

**What this module deliberately does not do.**  It does not *round* and it
does not *re-round*: the grids are feature 312's judgment, made one gate
earlier, and this module neither repeats it nor repairs it.  It does not
*judge the venue's other bounds* — ``minQty``, ``maxQty``, ``minPrice`` and
``maxPrice`` are bounds the venue states and enforces, and feature 310
persisted them for whatever later feature's sentence names them; this
sentence names the minimum notional alone.  It does not *size the order*: a
leg below the floor could be sized up by the book's weights or dropped
entirely, and choosing is the sizing step's decision, which is why the
refusal names the value, the floor and both terms of the product rather than
a repair, because the *shortfall* is arithmetic the sizing step owns and this
module's refusals are the only place it is reported (see
:meth:`OrderValue.headroom` on why no value of this type carries one).  It
does not *implement
the risk member's equity floor* at twice this constant (C10, §13.3) — that
halts a deployment, and this refuses one order.  It does not *read the
store*: the caller holds the filters it read, and a gate that fetched its
own would be a second, racing reader on the order path.  And it does not
*speak to the venue* — the venue's own rejection of a sub-notional order
arrives too late and in the wrong vocabulary; this one is the system's own,
before the send.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from .errors import BELOW_MIN_NOTIONAL_CODE, RouterBelowMinNotionalError
from .exchange_info import RouterSymbolFilters
from .rounding import RoundedOrder

__all__ = [
    "OrderValue",
    "require_min_notional",
]


def _as_decimal(value: Any, term: str, ground: str) -> Decimal:
    """Return ``value`` as an exact decimal, or refuse it by name.

    The floor arrives the way every venue number arrives in this member —
    the fetched document's own string, or an exact
    :class:`~decimal.Decimal` — and nothing is read approximately: a
    :class:`float` is a binary approximation of a decimal no venue ever
    sent, and a floor read approximately would misjudge the very order it
    was compared against.  This is feature 312's rule for the two grids and
    the two terms, held here for the one number this module reads; it is
    restated rather than imported from that module's private helper because
    the refusal must name *this* module's term and *this* feature's repair,
    which is the same reason :func:`router.margin._validated_account` and
    :func:`router.client_order_id._validated_symbol` each state their own.
    """
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise RouterBelowMinNotionalError(
                f"{BELOW_MIN_NOTIONAL_CODE}: {term} {value!r} is not a "
                f"decimal a floor can be; {ground} (feature 313)"
            ) from exc
    else:
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: {term} must be a decimal string or "
            f"a Decimal, got {value!r} ({type(value).__name__}); a float is "
            "a binary approximation of a decimal no venue ever sent, and a "
            "floor read approximately would misjudge the very order it was "
            f"compared against; {ground} (feature 313)"
        )
    if not number.is_finite():
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: {term} must be a finite decimal, "
            f"got {number!r}; an order's worth cannot be compared against a "
            f"floor that is not a number, and {ground} (feature 313)"
        )
    return number


def _exact_product(quantity: Decimal, price: Decimal) -> Decimal:
    """``quantity * price``, computed exactly rather than at ambient precision.

    The one place this feature's arithmetic lives, so the verb's judgment,
    the value's verification and a caller recomputing an order's worth
    cannot drift the way two spellings of one product do.  It is a function
    rather than an inline ``quantity * price`` because the inline spelling
    is *wrong*: the module-level decimal context rounds every product to 28
    significant digits, so a product carrying more would be compared against
    the floor as a rounded number.  The local context is widened to hold the
    product exactly — an ``n``-digit coefficient times an ``m``-digit one
    has at most ``n + m`` digits — which is feature 312's exactness
    argument applied to the multiplication instead of to the modulo: a
    submission the venue would book must never be refused by a
    representation error in the gate that exists to prevent exactly that.

    A product that cannot be formed at all — an exponent beyond the
    decimal module's range, which no order this system builds will carry —
    is refused in this feature's vocabulary rather than raised as a bare
    :class:`decimal.Overflow`: the caller gets one exception type from this
    module, and the message names the two terms it could not multiply.
    """
    # At most ``n + m`` significant digits: the product of an n-digit and an
    # m-digit integer carries no more, whatever the exponents are.  The
    # ambient precision is the floor of the widening so a caller that has
    # already raised it is never narrowed.
    digits = len(quantity.as_tuple().digits) + len(price.as_tuple().digits)
    try:
        with localcontext() as context:
            context.prec = max(context.prec, digits)
            return quantity * price
    except ArithmeticError as exc:  # pragma: no cover - absurd magnitudes only
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: the order's value cannot be "
            f"computed from quantity {quantity!r} and price {price!r}; an "
            "order whose worth is not a number cannot be compared against "
            "the venue's floor, so it is refused rather than passed "
            "(feature 313)"
        ) from exc


def _validated_floor(value: Any, symbol: str) -> Decimal:
    """Return the venue's minimum notional, or refuse what cannot be one.

    An exact decimal, zero or greater.  Zero is admissible and vacuous — a
    venue that publishes a minimum of zero has published a minimum nothing
    falls below — and is *not* the same fact as ``None``, which
    :func:`require_min_notional` refuses because an absent floor leaves the
    order unjudgeable.  Negative is refused: a negative minimum is not a
    minimum, and a floor below zero would admit every order including the
    ones the sentence exists to refuse.
    """
    number = _as_decimal(
        value,
        "the minimum notional",
        "the minimum notional is the floor the fetched document states for "
        "the symbol (NOTIONAL.minNotional)",
    )
    if number < 0:
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: the minimum notional for {symbol!r} "
            f"must not be negative, got {number!r}; a negative minimum is "
            "not a minimum — it would admit every order, including the ones "
            "this feature exists to refuse (feature 313)"
        )
    return number


@dataclass(frozen=True)
class OrderValue:
    """One order's worth, judged: the order, the floor, and the value.

    The value :func:`require_min_notional` answers — the verdict a caller
    branches on and the facts it was made over, kept together because a
    verdict alone could not say *how much* the order was worth or *against
    what* floor, and both are the audit trail for an order that was
    admitted:

    * ``order`` — feature 312's :class:`~router.rounding.RoundedOrder`: the
      decimalised quantity and price, beside the two grids they passed.
      This is where the terms come from; this class does not restate them,
      so the quantity this value multiplies is *the* quantity the grid gate
      judged rather than a second reading of the same spelling.
    * ``min_notional`` — the floor the fetched document states for the
      symbol, decimalised.  Zero means *no floor worth naming* and is
      admissible; the difference between ``Decimal("0")`` and an absent
      floor is the difference between an order that is admissible and one
      that cannot be judged at all.
    * ``value`` — the order's worth, ``quantity * price``, computed exactly
      when omitted and **checked when stated**: a record reconstructed from
      a log that carries a value disagreeing with its own terms is refused,
      because a value that lies about the order's worth is worse than no
      value.  The sentinel for *not stated* is ``None`` exactly — a stated
      ``Decimal("0")`` is a stated value and is judged like any other.

    All three are canonicalised at construction — the order's own
    validators re-run through its frozen value, the floor decimalised and
    bounds-checked, the value recomputed exactly — so a value built by hand
    in a test or reconstructed from a record gets the same judgment the verb
    applies, and a value claiming a worth its own terms contradict cannot
    exist.  Frozen, and hashable: a verdict can stand as its own key.
    """

    order: RoundedOrder
    min_notional: Decimal
    value: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.order, RoundedOrder):
            raise RouterBelowMinNotionalError(
                f"{BELOW_MIN_NOTIONAL_CODE}: an order's value is judged from "
                f"feature 312's RoundedOrder, got {self.order!r} "
                f"({type(self.order).__name__}); the floor is judged on an "
                "order that has already passed the venue's grids, so the two "
                "gates cannot disagree about what the order's terms are "
                "(feature 313)"
            )
        floor = _validated_floor(self.min_notional, self.order.symbol)
        worth = _exact_product(self.order.quantity, self.order.price)
        object.__setattr__(self, "min_notional", floor)
        if self.value is None:
            object.__setattr__(self, "value", worth)
        else:
            stated = _as_decimal(
                self.value,
                "the order's value",
                "the value is what the order is worth — its quantity times "
                "its price — and it rides beside the terms it was computed "
                "from (feature 313)",
            )
            if stated != worth:
                raise RouterBelowMinNotionalError(
                    f"{BELOW_MIN_NOTIONAL_CODE}: the stated value {stated!r} "
                    f"is not the worth of the order it rides beside — "
                    f"quantity {self.order.quantity!r} times price "
                    f"{self.order.price!r} is {worth!r}; a record whose value "
                    "disagrees with its own terms would lie about the order's "
                    "worth, which is the one thing it exists to state "
                    "(feature 313)"
                )
            object.__setattr__(self, "value", stated)
        if worth < floor:
            raise RouterBelowMinNotionalError(
                f"{BELOW_MIN_NOTIONAL_CODE}: the order for "
                f"{self.order.symbol!r} is worth {worth!r} (quantity "
                f"{self.order.quantity!r} times price {self.order.price!r}), "
                f"which falls below the venue's minimum notional {floor!r} "
                "(NOTIONAL.minNotional); the quantity sits on the step size "
                "and the price on the tick size, so this is not a rounding "
                "repair — size the leg up, at the sizing step that answers "
                "to the book's weights (feature 313)"
            )

    @property
    def symbol(self) -> str:
        """The leg the order is for — feature 312's own term, read through."""
        return self.order.symbol

    @property
    def quantity(self) -> Decimal:
        """The order's size, exactly the decimal the grid gate decimalised."""
        return self.order.quantity

    @property
    def price(self) -> Decimal:
        """The order's price, exact the same way."""
        return self.order.price

    def headroom(self) -> Decimal:
        """How much the order's worth exceeds the floor — ``value - floor``.

        **Never negative, and that is a property of this value type rather
        than a claim about the world.**  ``__post_init__`` refuses a
        below-floor order outright, so a value that exists at all is one
        that cleared the floor; the reading is therefore always the *room*
        left above it — zero for an order worth exactly the minimum, and
        positive above.  A caller asking *how much more must this leg be
        worth to book?* asks that of a **refused** ask, and the answer is
        in the refusal's own message, which names the value, the floor and
        both terms of the product; there is deliberately no method here
        reporting a shortfall, because no value of this type can hold one.

        Offered as a reading rather than only as the refusal's message for
        the caller that needs it on the *admitted* side — a sizing step
        weighing a leg that clears the floor by a hair against one that
        clears it by a mile reads the difference here rather than
        re-subtracting the two fields, so the arithmetic has one home.
        """
        assert self.value is not None  # set by __post_init__, never None after
        return self.value - self.min_notional


def require_min_notional(
    *,
    order: Any,
    filters: Any,
) -> OrderValue:
    """Feature 313's verb: judge an order's value against the venue's floor.

    app_spec.xml, "Order Routing & Venue Filters", feature 313: *System
    rejects an order falling below the venue minimum notional, which
    returns a ``below_min_notional`` error message.*  This is that sentence
    as one call: it answers the frozen :class:`OrderValue` for a submission
    whose quantity times price reaches the floor the venue published for
    the symbol, and it raises
    :class:`~router.errors.RouterBelowMinNotionalError` — whose message
    opens with :data:`~router.errors.BELOW_MIN_NOTIONAL_CODE` — for one
    that falls below it.  It never sizes, never rounds and never sends
    anything.

    Each argument is a required keyword with no default.  ``order`` is
    feature 312's :class:`~router.rounding.RoundedOrder` — the verdict the
    grid gate just answered — and ``filters`` is feature 310's
    :class:`~router.exchange_info.RouterSymbolFilters`, the value the order
    path reads from
    :meth:`~router.store.RouterExchangeInfoStore.filters_for`, of which only
    ``min_notional`` is read.  There is deliberately no parameter for a
    quantity, a price or a floor: the terms arrive inside feature 312's
    value (so the two gates cannot disagree about them) and the floor
    arrives inside feature 310's (so no literal can be handed to this gate),
    which is feature 311's no-hardcoded-constant law made structural.

    **The refusals run in a fixed order.**  The order first — it carries the
    symbol that names the floor and the terms that are multiplied; then the
    filters themselves — ``None`` (the symbol the current version does not
    carry, or a store with no version yet) is refused, a value that is not
    feature 310's own is refused, and filters filed under a *different*
    symbol are refused, because a value judged against another symbol's
    floor is a verdict about the wrong instrument; then the floor — a venue
    that states no minimum leaves the order unjudgeable, and unjudgeable is
    refused, never defaulted; then the value itself, computed exactly.  A
    submission wrong in several ways is refused for the first one,
    deterministically, so two operators reading one refusal read the same
    repair — the order feature 312's own gate runs its refusals in.

    Deterministic by construction: the same order against the same floor
    answers the same verdict in any process, on any machine, on any day,
    with no clock read and no state consulted — which is what makes it safe
    for the separate order-router process §13.2 and feature 320 demand, and
    the whole of the contract.
    """
    if not isinstance(order, RoundedOrder):
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: the order must be feature 312's "
            f"RoundedOrder — the submission the venue's step size and tick "
            f"size already admitted — got {order!r} "
            f"({type(order).__name__}); the floor is judged on an order that "
            "has passed the grids, and an ask that carries no decimalised "
            "terms states no order to value (feature 313)"
        )
    symbol = order.symbol
    if filters is None:
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: no exchangeInfo filters are held for "
            f"{symbol!r}; the current version does not carry the symbol (or no "
            "version has been fetched), and an order whose value cannot be "
            "judged against the venue's floor is refused rather than passed "
            "as unconstrained — a symbol the venue has stopped listing must "
            "not be tradeable off a stale or hardcoded minimum (feature 313)"
        )
    if not isinstance(filters, RouterSymbolFilters):
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: filters must be feature 310's "
            f"RouterSymbolFilters, got {filters!r} "
            f"({type(filters).__name__}); the floor this gate judges against "
            "is the fetched document's own narrowed value, and an ask that "
            "carries no such value states no floor to be judged against "
            "(feature 313)"
        )
    if filters.symbol != symbol:
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: the order is for {symbol!r} but the "
            f"filters are {filters.symbol!r}'s; a value judged against "
            "another symbol's minimum notional is a verdict about the wrong "
            "instrument — one symbol, one spelling, one floor (feature 313)"
        )
    if filters.min_notional is None:
        raise RouterBelowMinNotionalError(
            f"{BELOW_MIN_NOTIONAL_CODE}: the venue states no minimum notional "
            f"for {symbol!r} — the current exchangeInfo version carries no "
            "NOTIONAL filter for the symbol — so the order's value cannot be "
            "judged against a floor at all; the submission is refused rather "
            "than passed as unconstrained, because a floor this module "
            "defaulted would be exactly the hardcoded venue constant feature "
            "311 forbids (feature 313)"
        )
    return OrderValue(order=order, min_notional=filters.min_notional)
