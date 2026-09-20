"""Feature 63's fill layer: the passive order filled only on a tape trade-through.

app_spec.xml, "Cost Model & Fill Simulation", feature 63: *System fills a
passive order only when the recorded tape trades through the quoted price,
which rejects fills that merely touch it.*
docs/nullius-tech-architecture.md §6.2 fixes the behaviour in the document
itself, under the fill model's passive half:

.. code-block:: yaml

    fill_model:
      passive:
        require_trade_through: true     # fill only if tape trades THROUGH the price
        queue_position_penalty_bps: 1.5
        fill_probability_model: exp_decay_vs_queue_depth

The sentence has three separable claims, and this module owns all three:

* **fills a passive order** — the order is *resting* liquidity, not a cross.
  It names a side and a limit price and then waits: a passive buy rests on
  the bid wanting to buy at the quote or below it, a passive sell rests on
  the ask wanting to sell at the quote or above it.  It carries no urgency
  and no crossing intent — the aggressive order of feature 66 lifts the
  spread by choice, this one posts a price and lets the tape come to it
  (the two are the two regimes §6.2's fill model prices, and a cost model
  that confused a resting bid with a lifting buy would price the wrong side
  of the spread entirely).
* **only when the recorded tape trades through the quoted price** — the
  fill is *picked off*, not granted.  The tape is the record of trades that
  actually printed; the order fills only when one of those trades crosses
  to the far side of the quote — strictly below a resting bid, strictly
  above a resting ask.  A trade through the quote is the only honest
  evidence that the order's liquidity was taken: it proves the market moved
  past the price the order rested at, which is precisely when a passive
  provider is filled against (see :attr:`PassiveFillDecision.traded_through`
  and the :data:`Trade` that triggered it).
* **which rejects fills that merely touch it** — a trade that prints
  *exactly* at the quote is not a fill here.  A touch means the market
  arrived at the price but did not cross it — the order was at the touch,
  still queued behind whatever was ahead of it, not traded through.  The
  naive model fills a passive order the instant the tape reaches its price;
  this feature's whole point is that reaching is not crossing, so a tape
  that touches and retreats leaves the order unfilled (see
  :attr:`PassiveFillDecision.touch_trade` — the would-be fill the trade-
  through gate refuses).

**The quote is the order's own limit price, and the tape is recorded.**
The "quoted price" the sentence gates on is the passive order's limit — the
price it posted — and the gate is measured against the trades the tape
actually printed, nothing invented.  A trade strictly on the far side of
the quote trades through; a trade within a sliver of the quote (float dust
either side of an equal price) counts as a touch, not a through, so a fill
never flips on the last unit in the last place; a trade on the near side
never reached the quote at all.  The module holds no book and crosses no
spread implicitly — the tape and the order arrive as values, the decision
returns a value, and nothing is persisted.  Feature 64 layers the queue-
position penalty onto a fill this module has already granted, and feature
65 the fill-probability decay; this feature decides *whether* the order
fills at all, which is the gate both of those build on.

**No touch fallback ships.**  :func:`resolve_passive_fill_model` reads the
passive section out of the parsed §6.2 document and refuses any document
whose ``require_trade_through`` is not exactly ``true`` — the only other
behaviour the flag could name is "fill on the touch", the regime the
sentence rules out, and this library does not carry it.  That refusal is
what keeps feature 69's promise cheap: *"research evaluation and live
execution import one shared cost library"* — a library that offered both
gates would let the two drift back apart through configuration.  The
section's other two fields (``queue_position_penalty_bps``,
``fill_probability_model``) belong to features 64 and 65 and are tolerated
here and not read — this resolver answers for the trade-through gate only.

The module holds no state and no third-party import: the tape and the
order arrive as values, the decision returns a value.  The tape arrives as
real prices and quantities in whatever units the caller's recording carries
(a caller builds it from wherever it recorded the tape — an evaluator
slicing a recorded lake, a live engine holding a venue feed), which is the
seam that lets §6.2's *"the same code, not two implementations of the same
document"* hold for the live path too.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .config import read_cost_model_document
from .errors import CostModelConfigError, CostModelFillError

__all__ = [
    "BUY",
    "FILL_MODEL_KEY",
    "PASSIVE_KEY",
    "REQUIRE_TRADE_THROUGH_KEY",
    "SELL",
    "PassiveFillDecision",
    "PassiveFillModel",
    "PassiveOrder",
    "RecordedTape",
    "Trade",
    "fill_passive_order",
    "resolve_passive_fill_model",
]

#: A passive buy — the order that rests on the bid, wanting to buy at or
#: below its limit price; it fills when the tape trades strictly below it.
BUY = "buy"

#: A passive sell — the order that rests on the ask, wanting to sell at or
#: above its limit price; it fills when the tape trades strictly above it.
SELL = "sell"

#: The document's own key for the fill model, per §6.2's ``fill_model`` block.
FILL_MODEL_KEY = "fill_model"

#: The fill model's own key for the passive half (§6.2); the aggressive half
#: beside it belongs to feature 66 and is not read here.
PASSIVE_KEY = "passive"

#: The passive half's trade-through flag (§6.2: ``require_trade_through: true``).
REQUIRE_TRADE_THROUGH_KEY = "require_trade_through"

#: The relative band within which a trade counts as *touching* the quote
#: rather than trading *through* it.  The tape and the order's limit price
#: both arrive as real numbers, so a trade that "should" print exactly at
#: the quote can land a unit in the last place either side of it; a gate
#: that treated ``P - 2.8e-17`` as a trade-through would flip a fill on
#: float dust.  ``1e-9`` relative is nine orders of magnitude below any
#: venue's tick at any price this model prices, so nothing real sits under
#: it — a trade inside the band is at the quote, and only a trade past the
#: band has traded through.
_TOUCH_EPS = 1e-9


def _coerce_side(value: object) -> str:
    """Return ``value`` as one of :data:`BUY`/:data:`SELL`, or refuse it.

    The two spellings are accepted case-insensitively — ``"BUY"`` is the
    same order as ``"buy"`` — and nothing else is: an order side is not a
    place to accept synonyms, because ``"bid"`` and ``"ask"`` name *book*
    sides and quietly mapping them onto order sides would let a caller
    state the resting side where they meant the direction.  A passive buy
    rests on the bid and a passive sell rests on the ask — the side says
    which, and the fill gate reads it.
    """
    if not isinstance(value, str):
        raise CostModelFillError(
            f"a passive order's side must be 'buy' or 'sell', got "
            f"{type(value).__name__} ({value!r})"
        )
    side = value.strip().lower()
    if side not in (BUY, SELL):
        raise CostModelFillError(
            f"a passive order's side must be 'buy' or 'sell', got "
            f"{value!r}; a buy rests on the bid and a sell rests on the "
            f"ask — 'bid' and 'ask' name book sides, not order directions"
        )
    return side


def _positive_price(value: object, what: str) -> float:
    """Return ``value`` as a positive finite real number, or refuse it.

    The one validator every price and quantity in this module passes
    through — a trade's price, a trade's quantity, an order's limit price —
    so a NaN, an infinity or a zero cannot be admitted by one constructor
    and refused by another.  A trade price of zero is not a quote, a
    quantity of zero is not a printed trade (in the raw diff stream a zero
    quantity is a level *removal*, ``nullius_ingest.book_diffs``), and a
    limit price of zero is not a price a passive order can rest at.
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
            f"quantity is a recording error, not a thin tape"
        )
    if number <= 0.0:
        raise CostModelFillError(f"{what} must be positive, got {value!r}")
    return number


@dataclass(frozen=True)
class Trade:
    """One printed trade on the recorded tape: a price and the quantity that changed hands.

    The tape's unit of evidence.  Both fields are positive finite reals
    validated at construction — a price of zero or below is not a print, a
    quantity of zero is not a trade: a zero-quantity entry in the tape is a
    correction or a removal, not liquidity that changed hands, and a tape
    handed to a cost model has no business carrying one.  A trade is a fact
    the market recorded; the fill gate measures the order's quote against
    these and nothing else.
    """

    price: float
    quantity: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "price", _positive_price(self.price, "a trade's price")
        )
        object.__setattr__(
            self,
            "quantity",
            _positive_price(self.quantity, f"a trade's quantity at {self.price!r}"),
        )


@dataclass(frozen=True)
class RecordedTape:
    """A recorded tape: the trades that printed, in the order they printed.

    The value the feature's sentence hands the gate — *"the recorded tape"*
    — carrying only what a trade-through needs: the trades, chronological,
    each a :class:`Trade`.  The order is the order the trades arrived in,
    not a price ordering — a tape climbs and falls through a quote over
    time, and the gate answers *when* the order first filled, so the
    chronology is the evidence, not a sorted ladder.  No ordering is
    validated: unlike a book level ladder, a tape is not monotonic in price,
    and demanding it would refuse the very climbs and falls the gate prices.

    An empty tape is a legal tape — ingest records seconds with no prints —
    and :func:`fill_passive_order` answers it with an honest *no fill*
    rather than a refusal: there was no trade, so nothing traded through, so
    the order did not fill, which is the true answer and not an absence to
    refuse.
    """

    trades: Sequence[Trade] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "trades", tuple(self.trades))
        for trade in self.trades:
            if not isinstance(trade, Trade):
                raise CostModelFillError(
                    f"a recorded tape's trades are trades, got "
                    f"{type(trade).__name__} ({trade!r})"
                )

    def __len__(self) -> int:
        return len(self.trades)


@dataclass(frozen=True)
class PassiveOrder:
    """A passive order: a resting side and a limit price, nothing else.

    The feature's *"a passive order"* — an order that posts liquidity and
    waits, so it carries a limit price (the quote it rests at — the very
    price the gate measures against) and no urgency (a market order would
    make it the aggressive order of feature 66).  The two fields it does
    carry are validated at construction, so an unusable order is refused by
    name at the boundary rather than mid-gate.

    Attributes:
        side: :data:`BUY` or :data:`SELL` (accepted case-insensitively).  A
            buy rests on the bid; a sell rests on the ask.
        limit_price: The price the order rests at — the *quoted price* the
            sentence gates on.  A positive finite real: the tape trades
            through it or touches it or never reaches it, and a non-positive
            price is not a quote a passive order can post.
    """

    side: str
    limit_price: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_side(self.side))
        object.__setattr__(
            self,
            "limit_price",
            _positive_price(self.limit_price, f"a passive {self.side} order's limit price"),
        )

    @property
    def is_buy(self) -> bool:
        """Whether this order rests on the bid side."""
        return self.side == BUY

    def _signed_past(self, price: float) -> float:
        """A trade ``price``'s signed distance past the quote, adverse-positive.

        Positive when the trade is strictly on the far side of the quote —
        below a resting bid, above a resting ask, the direction in which the
        order would be picked off; negative when the trade never reached the
        quote; zero at the quote.  One seam for both sides, so a buy and a
        sell share the sign convention and the gate reads it the same way.
        """
        return (self.limit_price - price) if self.is_buy else (price - self.limit_price)


@dataclass(frozen=True)
class PassiveFillDecision:
    """The gate's answer: whether the passive order filled, and the evidence.

    Feature 63's sentence as a value — the gate (:attr:`traded_through`),
    the trade that triggered the fill when it filled (:attr:`through_trade`),
    and the touch the naive model would have filled on that this gate
    refuses (:attr:`touch_trade`).  Everything derived reads the evidence
    rather than a stored copy of it, so the gate and the trades that decided
    it cannot disagree.

    Attributes:
        side: The order's side, :data:`BUY` or :data:`SELL`.
        limit_price: The order's quoted price — the level the tape was
            measured against.
        fills: Whether the order filled — ``True`` only when the tape
            traded strictly through the quote, ``False`` when it merely
            touched or never reached it.
        through_trade: The first trade that traded through the quote — the
            fill trigger — or ``None`` when none did.
        touch_trade: The first trade that touched the quote (printed at it,
            within :data:`_TOUCH_EPS`) — the would-be fill a touch-based
            model would have granted — or ``None`` when the tape never
            reached the quote.
    """

    side: str
    limit_price: float
    fills: bool
    through_trade: Trade | None = None
    touch_trade: Trade | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_side(self.side))
        object.__setattr__(
            self,
            "limit_price",
            _positive_price(self.limit_price, "a decision's limit price"),
        )
        fills = bool(self.fills)
        # A fill must have the trade that traded through to show for it, and
        # a non-fill must not: the gate and its evidence are one fact, so a
        # decision that asserts a fill with no triggering trade — or denies
        # one while naming a through-trade — is refused rather than let
        # stand as an inconsistent answer.
        through = self.through_trade
        if through is not None and not isinstance(through, Trade):
            raise CostModelFillError(
                f"a decision's through_trade is a trade, got "
                f"{type(through).__name__} ({through!r})"
            )
        touch = self.touch_trade
        if touch is not None and not isinstance(touch, Trade):
            raise CostModelFillError(
                f"a decision's touch_trade is a trade, got "
                f"{type(touch).__name__} ({touch!r})"
            )
        if fills != (through is not None):
            raise CostModelFillError(
                f"a passive fill decision is inconsistent: fills={fills!r} "
                f"but through_trade={'present' if through else 'absent'} — "
                f"the order fills if and only if the tape traded through the quote"
            )
        object.__setattr__(self, "fills", fills)

    @property
    def is_buy(self) -> bool:
        """Whether this decision was for a resting bid."""
        return self.side == BUY

    @property
    def traded_through(self) -> bool:
        """Whether the tape traded strictly through the quote — the gate, restated."""
        return self.fills

    @property
    def touched(self) -> bool:
        """Whether the tape reached the quote without (necessarily) trading through.

        The audit hook for the feature's rejection: a decision that
        ``touched`` and did not ``traded_through`` is exactly the fill the
        naive touch-based model would have granted and this gate refused.
        """
        return self.touch_trade is not None

    @property
    def fill_price(self) -> float | None:
        """The price the order filled at — its quoted limit price — or ``None``.

        A passive limit order, when it fills, fills at its own quote or
        better; the trade-through only decides *whether* it filled, and the
        price it rested at is the price it is charged.  ``None`` when the
        gate refused the fill, mirroring the absent :attr:`through_trade`.
        """
        return self.limit_price if self.fills else None

    def summary(self) -> dict[str, object]:
        """The decision as a persistable mapping: the gate, the two candidate trades.

        The shape a caller logs or a later feature attaches to a trial
        record: whether the order filled, the trade that picked it off when
        it did, and the touch it survived when it did not.  A view over the
        decision, rebuilt on every call, so it can never be a stale copy of
        a frozen value.
        """
        return {
            "side": self.side,
            "limit_price": self.limit_price,
            "fills": self.fills,
            "traded_through": self.traded_through,
            "touched": self.touched,
            "through_price": self.through_trade.price if self.through_trade else None,
            "touch_price": self.touch_trade.price if self.touch_trade else None,
            "fill_price": self.fill_price,
        }


def fill_passive_order(tape: RecordedTape, order: PassiveOrder) -> PassiveFillDecision:
    """Gate ``order`` against ``tape`` and return whether it filled.

    The feature's sentence as a function.  The order's side picks the
    direction to measure — a buy is picked off when the tape trades strictly
    below its limit, a sell when it trades strictly above — and the walk
    scans the tape chronologically for the first trade that crosses to the
    far side of the quote.  That trade is the fill trigger; the returned
    :class:`PassiveFillDecision` carries it as evidence, along with the
    first trade that merely touched the quote.

    The gate is a strict trade-through, guarded by :data:`_TOUCH_EPS`: a
    trade strictly past the quote (by more than the band) trades through and
    fills the order; a trade inside the band touches it and does not; a
    trade that never reached it leaves the order unfilled.  The one band
    comparison is the whole of the realism — a fill that flipped on a unit
    in the last place either side of an equal price would be a figure the
    tape did not earn.
    """
    band = order.limit_price * _TOUCH_EPS
    through_trade: Trade | None = None
    touch_trade: Trade | None = None
    for trade in tape.trades:
        signed_past = order._signed_past(trade.price)
        if signed_past > band:
            # Strictly past the quote on the adverse side — the tape has
            # traded through the quote, and this is the first trade that
            # did: the fill trigger.  A passive order is picked off the
            # moment the market crosses its price, so the gate closes here.
            through_trade = trade
            break
        if abs(signed_past) <= band and touch_trade is None:
            # Inside the band: the trade printed at the quote.  It is not a
            # fill — reaching is not crossing — but it is the touch the
            # naive model would have filled on, kept as the first one so the
            # refusal is auditable.
            touch_trade = trade

    return PassiveFillDecision(
        side=order.side,
        limit_price=order.limit_price,
        fills=through_trade is not None,
        through_trade=through_trade,
        touch_trade=touch_trade,
    )


@dataclass(frozen=True)
class PassiveFillModel:
    """The passive half's trade-through gate, resolved from the document.

    One flag, one method, and a refusal: the flag is §6.2's
    ``require_trade_through``, and it must be exactly ``true`` — the only
    other behaviour it could name is "fill on the touch", the regime feature
    63 rules out, and this library does not carry it (a second fill gate
    behind a flag is how the two implementations feature 69 forbids grow
    back).  The method is the gate, so a caller holding the resolved model
    holds the behaviour the document named::

        model = resolve_passive_fill_model(read_cost_model_document(path)[0])
        filled = model.decide(RecordedTape([Trade(99.0, 5.0)]), PassiveOrder("buy", 100.0)).fills

    and an evaluator and a live engine holding the same model gate the same
    tape the same way, which is the §6.2 invariant (``β₄`` penalizes
    divergence) made structural rather than aspirational.
    """

    require_trade_through: bool = True

    def __post_init__(self) -> None:
        if self.require_trade_through is not True:
            raise CostModelConfigError(
                f"the passive fill model this library implements fills an "
                f"order only when the recorded tape trades through the quoted "
                f"price (require_trade_through: true); require_trade_through="
                f"{self.require_trade_through!r} names filling on a mere touch, "
                f"which feature 63 rules out and the shared library does not carry"
            )

    def decide(self, tape: RecordedTape, order: PassiveOrder) -> PassiveFillDecision:
        """Gate ``order`` against ``tape`` — the one passive fill gate there is.

        Delegates to :func:`fill_passive_order` so the model and the module
        function are one implementation, not a facade over a twin.
        """
        return fill_passive_order(tape, order)


def resolve_passive_fill_model(
    model: Mapping[str, object] | None = None,
) -> PassiveFillModel:
    """Resolve the passive fill model's trade-through gate out of a parsed §6.2 document.

    ``model`` is the model mapping :func:`cost_model.config.read_cost_model_document`
    returns (the ``cost_model`` block), read through the one cached parse
    rather than a fresh re-read — the same single-parse seam the resolved
    identity, feature 60's hash and the aggressive resolver sit on, so the
    fill gate a caller decides with is the one the loaded document named.
    ``None`` reads the shipped default document.

    The §6.2 shape is demanded, not defaulted: a document with no
    ``fill_model``, no ``passive`` half, or no ``require_trade_through`` is
    refused by name, and a ``require_trade_through`` that is not exactly
    ``true`` is refused by :class:`PassiveFillModel` itself.  The
    section's other two fields (``queue_position_penalty_bps``,
    ``fill_probability_model``) belong to features 64 and 65 — they are
    tolerated here and not read, because this resolver answers for the
    trade-through gate only.

    Raises:
        CostModelConfigError: For every document defect — the section it
            names is absent or not a mapping.  These are defects of the
            *document*, which is why they are config errors while a broken
            tape is a :class:`~cost_model.errors.CostModelFillError`.
    """
    if model is None:
        model, _origin = read_cost_model_document()

    if not isinstance(model, Mapping):
        raise CostModelConfigError(
            f"the parsed cost model is a {type(model).__name__}, not a "
            f"mapping: a passive fill model is resolved out of a "
            f"{FILL_MODEL_KEY!r} section"
        )
    if FILL_MODEL_KEY not in model:
        raise CostModelConfigError(
            f"the cost model document names no {FILL_MODEL_KEY!r} section: "
            f"§6.2's fill model carries a passive half, and a cost model "
            f"that cannot price a passive order is not a cost model"
        )
    fill_model = model[FILL_MODEL_KEY]
    if not isinstance(fill_model, Mapping):
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY!r} section is a "
            f"{type(fill_model).__name__}, not a mapping"
        )
    if PASSIVE_KEY not in fill_model:
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY!r} section names no "
            f"{PASSIVE_KEY!r} half: the document prices neither a passive "
            f"nor an aggressive order"
        )
    passive = fill_model[PASSIVE_KEY]
    if not isinstance(passive, Mapping):
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY}.{PASSIVE_KEY} section is a "
            f"{type(passive).__name__}, not a mapping"
        )
    if REQUIRE_TRADE_THROUGH_KEY not in passive:
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY}.{PASSIVE_KEY} section names "
            f"no {REQUIRE_TRADE_THROUGH_KEY}: the passive half's trade-through "
            f"gate decides whether a passive order fills at all, and a "
            f"document that omits it has not named the behaviour"
        )
    return PassiveFillModel(  # type: ignore[arg-type]
        require_trade_through=passive[REQUIRE_TRADE_THROUGH_KEY]
    )
