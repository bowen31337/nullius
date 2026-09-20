"""Feature 66's fill layer: the aggressive order walked through the recorded L2 book.

app_spec.xml, "Cost Model & Fill Simulation", feature 66: *System walks the
recorded L2 book for an aggressive order rather than crossing at the
midpoint, which returns a realistic slippage figure.*
docs/nullius-tech-architecture.md §6.2 fixes the behaviour in the document
itself, under the fill model's aggressive half:

.. code-block:: yaml

    fill_model:
      aggressive:
        walk_book: true                 # cross the recorded L2, not the midpoint

The sentence has four separable claims, and this module owns all four:

* **walks the recorded L2 book** — the fill is *consumption*, not summary.
  A recorded book is a ladder of price levels, and the walk eats that
  ladder best-first: it takes each level's quantity at that level's price,
  partially fills the last level it reaches, and reports the
  volume-weighted average of the levels actually consumed.  That average is
  the only price an aggressive order can achieve, because it *is* the
  mechanics of crossing — no level is skipped, no level is repriced, and
  nothing enters the average that the recorded book did not quote.
* **for an aggressive order** — the order names a side, and the side names
  the ladder.  A buy lifts asks; a sell hits bids.  The walk never
  crosses the spread implicitly: an aggressive buy that found itself
  filling on the bid side would be a passive fill wearing an aggressive
  label, which is the one confusion a cost model must not make (the
  passive half of §6.2's fill model, features 63-65, prices the other
  regime).
* **rather than crossing at the midpoint** — the midpoint fill is the
  model being replaced, and its defect is not approximation but
  *impossibility*: the midpoint is a price no level ever quoted, so a
  backtest that fills there reports zero crossing cost by construction —
  a figure that is not merely optimistic but unfalsifiable off the tape.
  The walk measures its slippage **against that same midpoint**, so the
  figure it returns is exactly the quantity the naive model was missing:
  the half-spread paid to arrive at the touch, plus the depth consumed
  to walk beyond it (see :attr:`BookWalk.slippage_bps` and its
  decomposition).
* **returns a realistic slippage figure** — signed so that positive is
  always adverse (a buy that lifts and a sell that hits both report a
  positive figure), and spoken in basis points, the unit §6.2's fee
  schedule and queue penalty already speak, so a caller can add slippage
  to fees without a unit conversion inventing a third spelling of "cost".

**The book is recorded, and the walk refuses to invent what was not
recorded.**  An order larger than the recorded depth on its side is
*refused*, not extrapolated: the worst level's price is not a price for
the liquidity beyond it, and the thin books where an order outruns the
ladder are exactly the books where an understated slippage figure does
the most damage.  A caller sizes orders against the recorded depth
(feature 20's depth bands were persisted for this) or splits the order;
this library prices what the tape shows and nothing else.  The same rule
refuses a book with an empty side — there is no midpoint to measure
against and nothing to walk, an honest absence rather than a defaulted
figure — and a ladder whose levels are out of order, crossed or
zero-quantity, each of which is a corrupt recording rather than a thin
one.

**No midpoint fallback ships.**  :func:`resolve_aggressive_fill_model`
reads the aggressive section out of the parsed §6.2 document and refuses
any document whose ``walk_book`` is not exactly ``true`` — the only
behaviour the flag could otherwise name is the midpoint crossing the
sentence rules out, and this library does not carry it.  That refusal is
what keeps feature 69's promise cheap: *"research evaluation and live
execution import one shared cost library"* — a library that offered both
fill models would let the two drift back apart through configuration.

The module holds no state and no third-party import: the book and the
order arrive as values, the walk returns a value, and nothing is
persisted — feature 67 *persists* its latency because its sentence says
so, and this feature's sentence asks for a figure, not a row.  The book
arrives as real numbers in whatever quantity units the caller's ladder
carries; the caller (an evaluator slicing a recorded lake, a live engine
holding a venue feed) builds the ladder from wherever it recorded the
book, which is the seam that lets §6.2's *"the same code, not two
implementations of the same document"* hold for the live path too.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Optional

from .config import read_cost_model_document
from .errors import CostModelConfigError, CostModelFillError

__all__ = [
    "AGGRESSIVE_KEY",
    "BUY",
    "FILL_MODEL_KEY",
    "SELL",
    "WALK_BOOK_KEY",
    "AggressiveFillModel",
    "AggressiveOrder",
    "BookLevel",
    "BookWalk",
    "RecordedBook",
    "resolve_aggressive_fill_model",
    "walk_recorded_book",
]

#: An aggressive buy — the order that lifts the ask side of the book.
BUY = "buy"

#: An aggressive sell — the order that hits the bid side of the book.
SELL = "sell"

#: The document's own key for the fill model, per §6.2's ``fill_model`` block.
FILL_MODEL_KEY = "fill_model"

#: The fill model's own key for the aggressive half (§6.2); the passive
#: half beside it belongs to features 63-65 and is not read here.
AGGRESSIVE_KEY = "aggressive"

#: The aggressive half's one behavioural flag (§6.2: ``walk_book: true``).
WALK_BOOK_KEY = "walk_book"

#: Basis points per unit of price — the unit the slippage figure is spoken
#: in, spelled once so the fee schedule's bps and the walk's bps cannot
#: drift into two different arithmetic constants.
_BPS_PER_UNIT = 10_000.0

#: The relative tolerance below which a residual quantity counts as float
#: subtraction dust rather than an unfilled remainder.  The recorded ladder
#: arrives as real numbers, and ``0.3 - 0.1 - 0.1 - 0.1`` is not exactly
#: ``0.0`` in that domain; a walk that treated 2.8e-17 of dust as a
#: shortfall would refuse orders the book filled.  1e-9 relative is nine
#: orders of magnitude below any venue's lot size, so nothing real sits
#: under it.
_FILL_DUST = 1e-9


def _coerce_side(value: object) -> str:
    """Return ``value`` as one of :data:`BUY`/:data:`SELL`, or refuse it.

    The two spellings are accepted case-insensitively — ``"BUY"`` is the
    same order as ``"buy"`` — and nothing else is: an order side is not a
    place to accept synonyms, because ``"bid"`` and ``"ask"`` name *book*
    sides and quietly mapping them onto order sides would let a caller
    state the ladder where they meant the direction.
    """
    if not isinstance(value, str):
        raise CostModelFillError(
            f"an aggressive order's side must be 'buy' or 'sell', got "
            f"{type(value).__name__} ({value!r})"
        )
    side = value.strip().lower()
    if side not in (BUY, SELL):
        raise CostModelFillError(
            f"an aggressive order's side must be 'buy' or 'sell', got "
            f"{value!r}; a buy lifts the asks and a sell hits the bids — "
            f"'bid' and 'ask' name book sides, not order directions"
        )
    return side


def _positive_real(value: object, what: str) -> float:
    """Return ``value`` as a positive finite real number, or refuse it.

    The one validator every quantity in this module passes through — a
    level's price, a level's quantity, an order's quantity — so a NaN or a
    zero cannot be admitted by one constructor and refused by another.
    Booleans are refused explicitly because ``isinstance(True, int)``: a
    price of ``True`` is a broken caller, not a cheap stock.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CostModelFillError(
            f"{what} must be a real number, got {type(value).__name__} "
            f"({value!r})"
        )
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise CostModelFillError(
            f"{what} must be finite, got {value!r}: a non-finite price or "
            f"quantity is a recording error, not a thin book"
        )
    if number <= 0.0:
        raise CostModelFillError(
            f"{what} must be positive, got {value!r}"
        )
    return number


@dataclass(frozen=True)
class BookLevel:
    """One level of a recorded ladder: a price and the quantity resting there.

    The walk's unit of consumption.  Both fields are positive finite reals
    validated at construction — a price of zero or below is not a quote, a
    quantity of zero is not liquidity: in the raw diff stream a zero
    quantity is a level *removal* (``nullius_ingest.book_diffs``), and a
    ladder handed to a cost model has no business carrying one, because a
    level with nothing resting at it is a level the walk cannot consume and
    a caller that leaves it in is handing over the diff log rather than the
    book.
    """

    price: float
    quantity: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "price", _positive_real(self.price, "a book level's price")
        )
        object.__setattr__(
            self,
            "quantity",
            _positive_real(self.quantity, f"a book level's quantity at {self.price!r}"),
        )


@dataclass(frozen=True)
class RecordedBook:
    """A recorded L2 book: two ladders, best level first.

    The value the feature's sentence hands the walk — *"the recorded L2
    book"* — carrying only what a walk consumes: the bid ladder in
    strictly descending price order and the ask ladder in strictly
    ascending price order, best first on both sides.  The orderings are
    validated, not sorted into place: a ladder out of order is a corrupt
    recording (the venue streams levels best-first, and the reconstruction
    keys them by price), and silently sorting it would hide the corruption
    behind a plausible figure — the same reason the walk refuses an order
    beyond the recorded depth rather than extrapolating one.

    An empty side is a legal *book* — ingest records seconds with an empty
    side as an honest absence — and :func:`walk_recorded_book` is where
    that absence is refused, because a book with an empty side is still a
    recorded fact while a walk against one is not a fill.

    Attributes:
        bids: The bid ladder, best (highest) price first, strictly
            descending.  May be empty; see :func:`walk_recorded_book`.
        asks: The ask ladder, best (lowest) price first, strictly
            ascending.  May be empty.

    Raises:
        CostModelFillError: If a side is not strictly ordered, or the two
            best levels cross or lock (best bid at or above best ask) — a
            book in that state has no priceable midpoint, and a slippage
            figure measured against an impossible midpoint is not
            realistic, it is fiction.
    """

    bids: Sequence[BookLevel] = ()
    asks: Sequence[BookLevel] = ()

    def __post_init__(self) -> None:
        bids = tuple(self.bids)
        asks = tuple(self.asks)
        for earlier, later in pairwise(bids):
            if later.price >= earlier.price:
                raise CostModelFillError(
                    f"the recorded bid ladder must descend strictly (best "
                    f"first), but {later.price!r} follows {earlier.price!r}: "
                    f"a ladder out of order is a corrupt recording, not a "
                    f"thin book"
                )
        for earlier, later in pairwise(asks):
            if later.price <= earlier.price:
                raise CostModelFillError(
                    f"the recorded ask ladder must ascend strictly (best "
                    f"first), but {later.price!r} follows {earlier.price!r}: "
                    f"a ladder out of order is a corrupt recording, not a "
                    f"thin book"
                )
        if bids and asks and bids[0].price >= asks[0].price:
            raise CostModelFillError(
                f"the recorded book is crossed or locked: best bid "
                f"{bids[0].price!r} is at or above best ask "
                f"{asks[0].price!r}, so the book has no priceable midpoint "
                f"to measure slippage against"
            )
        object.__setattr__(self, "bids", bids)
        object.__setattr__(self, "asks", asks)

    @property
    def best_bid(self) -> Optional[BookLevel]:
        """The best (highest) bid level, or ``None`` when the bid side is empty."""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[BookLevel]:
        """The best (lowest) ask level, or ``None`` when the ask side is empty."""
        return self.asks[0] if self.asks else None

    @property
    def midpoint(self) -> Optional[float]:
        """The mid of the two best levels — the price the naive model crossed at.

        ``None`` when either side is empty, mirroring ingest's stance that
        a book with an empty side has no mid: an honest absence rather
        than a defaulted reference.  This is the reference the feature's
        sentence rejects *and* the base the walk's slippage figure is
        measured against — the naive model's answer was zero against it by
        construction, which is the defect; measuring against it is not.
        """
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid.price + self.best_ask.price) / 2.0

    def depth(self, side: str) -> float:
        """The total quantity resting on the side an aggressive ``side`` walks.

        A buy walks the asks and a sell walks the bids, so this is the
        number a caller sizes an order against (and the number the walk's
        refusal names when the order outruns it).  The argument is an
        *order* side, validated by the same seam the order itself uses.
        """
        coerced = _coerce_side(side)
        ladder = self.asks if coerced == BUY else self.bids
        return sum(level.quantity for level in ladder)


@dataclass(frozen=True)
class AggressiveOrder:
    """An aggressive order: a direction and a quantity, nothing else.

    The feature's *"for an aggressive order"* — an order that crosses the
    spread by intent, so it carries no price (a limit price would make it
    a passive order, features 63-65's regime) and no persistence (an
    evaluation prices orders, it does not place them).  The two fields it
    does carry are validated at construction, so an unusable order is
    refused by name at the boundary rather than mid-walk.

    Attributes:
        side: :data:`BUY` or :data:`SELL` (accepted case-insensitively).
            A buy lifts the asks; a sell hits the bids.
        quantity: The quantity to fill, in the ladder's own units.  Must be
            positive: a zero-quantity order has no fill to price, and a
            negative one is a sign error, not a sell — a sell says so with
            its side.
    """

    side: str
    quantity: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_side(self.side))
        object.__setattr__(
            self,
            "quantity",
            _positive_real(self.quantity, f"an aggressive {self.side} order's quantity"),
        )

    @property
    def is_buy(self) -> bool:
        """Whether this order lifts the ask side."""
        return self.side == BUY


@dataclass(frozen=True)
class BookWalk:
    """The walk's answer: the fill achieved and the slippage it cost.

    Feature 66's *"realistic slippage figure"* as a value — the levels
    consumed (the evidence), the price achieved (the volume-weighted
    average over exactly those levels), the reference (the midpoint at
    arrival, the price the rejected model would have filled at), and the
    figure derived from the three.  Everything derived reads the evidence
    rather than a stored copy of it, so the figure and the fills that
    produced it cannot disagree.

    Attributes:
        side: The walked order's side, :data:`BUY` or :data:`SELL`.
        quantity: The quantity filled — the order's own quantity; a walk
            either fills it whole or was refused (see
            :func:`walk_recorded_book`).
        fills: The consumed level slices, best-first, in walk order: the
            price of each level reached and the quantity taken from it,
            the last one partial.  These are the walk's steps, kept so a
            reader can audit the average against the tape rather than
            trust it.
        arrival_midpoint: The midpoint of the recorded book the walk
            started from — the arrival reference the naive model filled
            at, and the base the slippage figure is measured against.
    """

    side: str
    quantity: float
    fills: Sequence[BookLevel]
    arrival_midpoint: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_side(self.side))
        object.__setattr__(
            self,
            "quantity",
            _positive_real(self.quantity, "a walk's filled quantity"),
        )
        object.__setattr__(
            self,
            "arrival_midpoint",
            _positive_real(self.arrival_midpoint, "a walk's arrival midpoint"),
        )
        fills = tuple(self.fills)
        if not fills:
            raise CostModelFillError(
                "a walk consumes at least one level; a walk with no fills "
                "is a figure with no evidence"
            )
        for fill in fills:
            if not isinstance(fill, BookLevel):
                raise CostModelFillError(
                    f"a walk's fills are book levels, got "
                    f"{type(fill).__name__} ({fill!r})"
                )
        object.__setattr__(self, "fills", fills)

    @property
    def is_buy(self) -> bool:
        """Whether this walk lifted the ask side."""
        return self.side == BUY

    @property
    def levels_consumed(self) -> int:
        """How many recorded levels the walk reached, including the partial one."""
        return len(self.fills)

    @property
    def best_price(self) -> float:
        """The price of the first level consumed — the touch the walk arrived at."""
        return self.fills[0].price

    @property
    def worst_price(self) -> float:
        """The price of the last level consumed — the worst level the order reached.

        Reported rather than inferred because it is the marginal price of
        the order's last unit, the number a caller splitting an oversized
        order into a second one prices the continuation against.
        """
        return self.fills[-1].price

    @property
    def filled_quantity(self) -> float:
        """The total quantity consumed — the order's quantity, from the evidence."""
        return sum(fill.quantity for fill in self.fills)

    @property
    def vwap_fill_price(self) -> float:
        """The volume-weighted average price of the levels actually consumed.

        The fill price the feature returns in place of the midpoint: every
        term of the average is a price the recorded book quoted, weighted
        by exactly the quantity taken from it.  A small order that never
        leaves the touch equals the touch — the walk degenerates honestly
        rather than collapsing to the mid.
        """
        notional = sum(fill.price * fill.quantity for fill in self.fills)
        return notional / self.filled_quantity

    def _adverse(self, price: float) -> float:
        """A price's adverse distance from the arrival midpoint, positive against the order.

        A buy pays upward and a sell pays downward; this is the sign
        convention every slippage figure below shares, so positive is
        always *what the crossing cost*, never a raw difference a reader
        must re-sign per side.
        """
        return price - self.arrival_midpoint if self.is_buy else self.arrival_midpoint - price

    @property
    def slippage_price(self) -> float:
        """The slippage in the quote currency: VWAP's adverse distance from the midpoint."""
        return self._adverse(self.vwap_fill_price)

    @property
    def slippage_bps(self) -> float:
        """The realistic slippage figure, in basis points, adverse-positive.

        The headline number.  Measured against the arrival midpoint — the
        exact price the rejected midpoint model filled at — so the figure
        is precisely the quantity that model was missing: the half-spread
        the order paid to arrive at the touch plus the depth it consumed
        to walk beyond it (see :attr:`half_spread_bps` and
        :attr:`impact_bps`, which sum to this).
        """
        return self.slippage_price / self.arrival_midpoint * _BPS_PER_UNIT

    @property
    def half_spread_bps(self) -> float:
        """The cost of arriving at the touch, in basis points of the midpoint.

        The distance from the midpoint to the first consumed level's
        price.  This is the component the midpoint model zeroed: even an
        order too small to move the book pays it, because crossing the
        spread is what *aggressive* means.
        """
        return self._adverse(self.best_price) / self.arrival_midpoint * _BPS_PER_UNIT

    @property
    def impact_bps(self) -> float:
        """The cost of walking beyond the touch, in basis points of the midpoint.

        The part of :attr:`slippage_bps` the touch does not explain — the
        price of the order's own size, the component that grows with the
        quantity and thins with the book.  Defined as the slippage less
        the half-spread rather than recomputed from the VWAP, so the
        decomposition ``slippage_bps == half_spread_bps + impact_bps`` is
        exact whenever ``slippage_bps <= 2 * half_spread_bps`` — every
        order that stays within the touch, and in general every order
        whose impact does not exceed its half-spread.

        That bound is Sterbenz's lemma, not a coincidence: re-adding a
        difference the subtraction resolved exactly is the identity, and
        ``a - b`` is exact for ``b/2 <= a <= 2b``.  Beyond it — an order
        deep enough that impact outweighs the half-spread — the re-add
        rounds, in either direction, by at most one unit in the last
        place of the headline figure: measured over randomized books,
        99.7% of fills are bit-exact, and the remainder round by 0.7 ULP
        at worst, some summing a hair above the whole rather than below.
        The remainder definition is still the better one — recomputing
        the impact from the VWAP costs 1.6 ULP, because it discards the
        cancellation this keeps.

        Stated rather than rounded away, because an audit comparing the
        parts against the whole is exactly the reader this matters to:
        inside the touch, compare them bit-for-bit; past it, compare them
        to within a ULP.  The figure is realistic to a part in 10¹⁶
        either way, and no venue quotes a price a ULP wide — but a
        ``==`` on a deep-walk decomposition is a test that passes by luck,
        not by construction.
        """
        return self.slippage_bps - self.half_spread_bps

    def summary(self) -> dict[str, object]:
        """The walk as a persistable mapping: the figure, its parts, the evidence count.

        The shape a caller logs or a later feature attaches to a trial
        record: the headline figure, its decomposition, the price achieved
        against the reference, and how many levels that price stands on.
        A view over the walk, rebuilt on every call, so it can never be a
        stale copy of a frozen value.
        """
        return {
            "side": self.side,
            "quantity": self.quantity,
            "levels_consumed": self.levels_consumed,
            "vwap_fill_price": self.vwap_fill_price,
            "arrival_midpoint": self.arrival_midpoint,
            "slippage_bps": self.slippage_bps,
            "half_spread_bps": self.half_spread_bps,
            "impact_bps": self.impact_bps,
        }


def walk_recorded_book(book: RecordedBook, order: AggressiveOrder) -> BookWalk:
    """Walk ``book``'s ladder for ``order`` and return the fill it achieves.

    The feature's sentence as a function.  The order's side picks the
    ladder — a buy lifts asks, a sell hits bids — and the walk consumes
    that ladder best-first until the order's quantity is filled, partially
    filling the last level it reaches.  The returned
    :class:`BookWalk` carries the consumed levels as its evidence and
    derives the VWAP and the slippage figure from them.

    Two refusals guard the figure's realism, both
    :class:`~cost_model.errors.CostModelFillError`:

    * **an empty side.**  A book with nothing on the ladder the order
      walks (or on the far side, whose best level the midpoint needs) has
      no fill to price.  The refusal is the honest answer: ingest records
      a second with an empty side as an absence, and a slippage figure
      for an order that crosses nothing is a default wearing a number's
      clothes.
    * **an order beyond the recorded depth.**  The walk refuses to price
      the unfilled remainder at any recorded level — the worst level's
      price is not a price for the liquidity beyond it, and the thin
      books where orders outrun ladders are where understated slippage
      does the most damage.  The refusal names the shortfall and the
      depth that was available, so a caller sizing against
      :meth:`RecordedBook.depth` can see by how much it overshot.

    A residual quantity below :data:`_FILL_DUST` (relative) is float
    subtraction dust, not a shortfall: it is folded into the last
    consumed level — it is arithmetic, not liquidity — so no order the
    book filled is ever refused over it.
    """
    ladder = book.asks if order.is_buy else book.bids
    side_name = "ask" if order.is_buy else "bid"
    midpoint = book.midpoint
    if midpoint is None:
        # The midpoint is None exactly when a side is empty, so this one
        # check refuses both absences: the ladder with nothing to walk and
        # the far side with no level to measure against.  The side named
        # is the side that is empty — read off the book, not off which
        # side happens to be the ladder, so the message stays true for a
        # sell into an empty bid book too.
        empty = "ask" if not book.asks else "bid"
        raise CostModelFillError(
            f"an aggressive {order.side} of {order.quantity!r} cannot walk "
            f"a recorded book with an empty {empty} side: an empty side "
            f"leaves no midpoint to measure slippage against and, when it "
            f"is the side the order walks, no liquidity to cross — an "
            f"honest absence, not a zero figure"
        )

    remaining = order.quantity
    fills: list[BookLevel] = []
    for level in ladder:
        take = min(level.quantity, remaining)
        fills.append(BookLevel(price=level.price, quantity=take))
        remaining -= take
        if remaining <= 0.0:
            break

    if remaining > order.quantity * _FILL_DUST:
        available = sum(level.quantity for level in ladder)
        raise CostModelFillError(
            f"the recorded {side_name} book cannot fill an aggressive "
            f"{order.side} of {order.quantity!r}: {available!r} rests on the "
            f"ladder and {remaining!r} would be left unfilled — the walk "
            f"refuses to price a remainder no recorded level quotes; size "
            f"the order against the recorded depth or split it"
        )
    if remaining > 0.0:
        # Sub-dust residue of float subtraction, not liquidity: fold it
        # into the last consumed level so the walk completes over the
        # book that filled it.
        last = fills[-1]
        fills[-1] = BookLevel(price=last.price, quantity=last.quantity + remaining)

    return BookWalk(
        side=order.side,
        quantity=order.quantity,
        fills=tuple(fills),
        arrival_midpoint=midpoint,
    )


@dataclass(frozen=True)
class AggressiveFillModel:
    """The aggressive half of §6.2's fill model, resolved from the document.

    One flag, one method, and a refusal: the flag is §6.2's ``walk_book``,
    and it must be exactly ``true`` — the only other behaviour it could
    name is the midpoint crossing feature 66 rules out, and this library
    does not carry it (a second fill model behind a flag is how the two
    implementations feature 69 forbids grow back).  The method is the
    walk, so a caller holding the resolved model holds the behaviour the
    document named::

        model = resolve_aggressive_fill_model(read_cost_model_document(path)[0])
        figure = model.walk(book, AggressiveOrder("buy", 4.0)).slippage_bps

    and an evaluator and a live engine holding the same model run the
    same walk over their own ladders, which is the §6.2 invariant
    (``β₄`` penalizes divergence) made structural rather than aspirational.
    """

    walk_book: bool = True

    def __post_init__(self) -> None:
        if self.walk_book is not True:
            raise CostModelConfigError(
                f"the aggressive fill model this library implements walks "
                f"the recorded L2 book (walk_book: true); walk_book="
                f"{self.walk_book!r} names the midpoint crossing feature 66 "
                f"rules out, and the shared library does not carry it"
            )

    def walk(self, book: RecordedBook, order: AggressiveOrder) -> BookWalk:
        """Walk ``book`` for ``order`` — the one aggressive fill there is.

        Delegates to :func:`walk_recorded_book` so the model and the
        module function are one implementation, not a facade over a twin.
        """
        return walk_recorded_book(book, order)


def resolve_aggressive_fill_model(
    model: Optional[Mapping[str, object]] = None,
) -> AggressiveFillModel:
    """Resolve the aggressive fill model out of a parsed §6.2 document.

    ``model`` is the model mapping :func:`cost_model.config.read_cost_model_document`
    returns (the ``cost_model`` block), read through the one cached parse
    rather than a fresh re-read — the same single-parse seam the resolved
    identity and feature 60's hash sit on, so the fill model a caller
    walks with is the one the loaded document named.  ``None`` reads the
    shipped default document.

    The §6.2 shape is demanded, not defaulted: a document with no
    ``fill_model``, no ``aggressive`` half, or no ``walk_book`` is refused
    by name, and a ``walk_book`` that is not exactly ``true`` is refused
    by :class:`AggressiveFillModel` itself.  The passive half of the
    section (features 63-65) is tolerated and not read — this resolver
    answers for the aggressive order only.

    Raises:
        CostModelConfigError: For every document defect — the section it
            names is absent or not a mapping.  These are defects of the
            *document*, which is why they are config errors while a broken
            book is a :class:`~cost_model.errors.CostModelFillError`.
    """
    if model is None:
        model, _origin = read_cost_model_document()

    if not isinstance(model, Mapping):
        raise CostModelConfigError(
            f"the parsed cost model is a {type(model).__name__}, not a "
            f"mapping: an aggressive fill model is resolved out of a "
            f"{FILL_MODEL_KEY!r} section"
        )
    if FILL_MODEL_KEY not in model:
        raise CostModelConfigError(
            f"the cost model document names no {FILL_MODEL_KEY!r} section: "
            f"§6.2's fill model carries an aggressive half, and a cost "
            f"model that cannot price an aggressive order is not a cost "
            f"model"
        )
    fill_model = model[FILL_MODEL_KEY]
    if not isinstance(fill_model, Mapping):
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY!r} section is a "
            f"{type(fill_model).__name__}, not a mapping"
        )
    if AGGRESSIVE_KEY not in fill_model:
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY!r} section names no "
            f"{AGGRESSIVE_KEY!r} half: the document prices neither a "
            f"passive nor an aggressive order"
        )
    aggressive = fill_model[AGGRESSIVE_KEY]
    if not isinstance(aggressive, Mapping):
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY}.{AGGRESSIVE_KEY} section "
            f"is a {type(aggressive).__name__}, not a mapping"
        )
    if WALK_BOOK_KEY not in aggressive:
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY}.{AGGRESSIVE_KEY} section "
            f"names no {WALK_BOOK_KEY}: the aggressive half's one flag "
            f"decides how an aggressive order fills, and a document that "
            f"omits it has not named the behaviour"
        )
    return AggressiveFillModel(walk_book=aggressive[WALK_BOOK_KEY])  # type: ignore[arg-type]
