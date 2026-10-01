"""Feature 4: the sized delta becomes a BingX order, through the gates.

additions_spec_bingx_dry_run.xml, "BingX VST Dry Run", feature 4: *System
assembles each sized delta into the parameters of a BingX POST
/openApi/swap/v2/trade/order request by passing it through the router's
existing gates in a fixed order: posture (314), step and tick grids (312),
the notional floor (313), the minimum quantity, and isolated margin (315).
A passive leg returns type LIMIT, timeInForce PostOnly and a price at the
mark rounded onto the tick grid on the passive side (down for BUY, up for
SELL).  An aggressive leg returns type MARKET with no price, judged
against the notional floor at the mark.  A refused leg returns its router
code word and the symbol instead of an order.*  This module is the first
two sentences as one call — :func:`assemble_bingx_order` — and the dry run
(:mod:`router.bingx_dry_run`) is the third sentence over it.

**Why an assembler at all.**  Everything upstream already answers in its
own vocabulary: feature 2 (:func:`router.sizing.size_contract_deltas`)
answers a signed delta per symbol, feature 314 answers a posture, features
312 and 313 answer verdicts over a submission, feature 315 an arrangement,
feature 3 (:func:`router.bingx_client_order_id.
project_bingx_client_order_id`) the venue's 40-character field payload.
None of them speaks BingX, and the category's own law is that none of
them may: :mod:`router.posture` refuses to spell the venue's flags (*"the
caller that speaks to the venue translates; this module decides"*), and
feature 311 rejects any hardcoded venue constant in the order path.  So
the translation — ``passive`` to ``LIMIT`` plus ``PostOnly``, ``aggressive``
to ``MARKET``, a signed delta to a ``BUY``/``SELL`` side over a magnitude,
``positionSide`` to the one-way ``BOTH`` — lives here, in the module whose
name says which venue it is for, exactly as feature 3's 40-character cap
does.  The order-path gates stay venue-neutral, and the venue boundary
stays the only place the venue's words are spelled.

**The gates are read, never re-implemented, and their order is the
sentence's.**  Posture first (314, :func:`router.posture.
resolve_order_posture`) — it decides which of the two request shapes the
leg is assembling into.  Then the step and tick grids (312,
:func:`router.rounding.require_rounded_order`) over the quantity the
sizer truncated onto the step grid and the price this module chose onto
the tick grid.  Then the notional floor (313,
:func:`router.notional.require_min_notional`) over the order the grids
just answered, so the two gates cannot disagree about the terms.  Then
the minimum quantity — the one judgment in the sentence's list no
existing module owns (feature 312 judges the two grids and feature 313
the one floor; ``minQty`` is a bound neither sentence names), so it is
added here as :func:`_require_min_quantity` in this addition's own
vocabulary, reading the ``min_qty`` the venue's own document stated
through feature 1's translation.  And isolated margin last (315,
:func:`router.margin.require_isolated_margin`), under the book's own mode
and account label.  A leg wrong at several gates is refused for the
first, deterministically — the order every gate in this member already
judges in.

**The price is this layer's one choice, and the gates judge it.**  The
quantity a venue receives was chosen where it was sized (feature 2's
truncation toward zero, so an order never exceeds its target); the price
gets the same treatment one layer along.  A passive order must not cross
the spread — a ``PostOnly`` limit that crossed is refused by the venue —
so the mark is rounded onto the tick grid *away* from the crossing: down
for a ``BUY`` (a bid at or below the mark), up for a ``SELL`` (an offer
at or above it), the same never-exceed-the-target arithmetic feature 2
states for quantities, read on the price.  The choice is made from the
exact decimals the venue spelled, and it is then *judged* — feature 312's
gate refuses a price off the tick grid, and the
:class:`~router.rounding.RoundedOrder` it answers is the value feature
313's floor is read over.  An aggressive order carries no price at all,
so the price term its gates read is the mark itself: the grids judge the
mark the venue published against the tick grid the same venue publishes,
and the notional floor is judged *"at the mark"*, the sentence's own
words — a mark that cannot sit on its venue's own price grid is refused
rather than silently snapped, the read-exactly-or-refuse discipline every
gate in this member holds its terms to.

**A refused leg is a value, not an exception — because a plan is a
breath, not a call stack.**  Every gate here refuses by raising, and one
leg's refusal must not answer for its siblings: the dry run's whole
shape is *one JSON object per would-send order and one per refused leg*,
so a leg the grids close is a fact the plan states beside the orders its
neighbours became.  :func:`assemble_bingx_order` therefore answers
:class:`BingXRefusedLeg` — the refusing gate's own code word
(:data:`router.errors.ORDER_POSTURE_CODE`,
:data:`router.errors.ORDER_ROUNDING_CODE`, …) beside the symbol — for
exactly the five gates in the sentence's list, and lets anything else
propagate: a fault in the *ask* (a delta offered as a float, a symbol
that states nothing) is a wiring fault, not a leg the venue refused, and
a caller that caught it as one would print a plan that called its own
bugs market facts.

**The identity is feature 316's, read through feature 3's projection.**
``clientOrderID`` is the request's idempotency name, and the system's own
name for the order is the 64-hex identifier feature 316 derives from the
book, the rebalance and the symbol; the venue's field caps it at 40, and
the only place in the workspace that spells the short form is
:func:`router.bingx_client_order_id.project_bingx_client_order_id`.  This
module reads that answer and never re-derives or re-truncates it — the
projection is applied once, at the venue boundary, by the function the
spec names for it — and nothing downstream may join on the 40 characters
(the placement store's idempotency key stays the full identifier), which
is why :class:`BingXOrder` carries the projection as the venue field it
is and nothing else reads it.

**Strings, because the venue reads strings.**  Every parameter the value
carries — ``quantity``, ``price``, ``clientOrderID`` — is the exact
decimal spelling the arithmetic answered (a ``0.0001`` grid answers four
decimal places, and BTC-USDT's ``0.0140`` keeps its trailing zero), the
same verbatim-spelling discipline :class:`~router.exchange_info.
RouterSymbolFilters` keeps for the venue's own constants.  A number
re-serialised at the send would be a second spelling of a decimal this
module already chose.

**No table, no component, no clock, no I/O, no network.**  Stage 0's own
law: nothing here opens a socket, signs, reads a credential or consults
an environment variable — the module imports :mod:`decimal`,
:mod:`dataclasses` and its own siblings only, and a deployment that never
dries-runs a book pays nothing to import it.  Nothing is placed, nothing
is persisted and nothing is rounded by a gate; the assembler is a pure
function of its terms, so the same delta, mark, filters, durations,
identity and margin arrangement answer the same order — or the same
refused leg — in any process, on any machine, on any day.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .bingx_client_order_id import (
    BINGX_CLIENT_ORDER_ID_LENGTH,
    project_bingx_client_order_id,
)
from .errors import (
    BELOW_MIN_NOTIONAL_CODE,
    CROSS_MARGIN_CODE,
    ORDER_POSTURE_CODE,
    ORDER_ROUNDING_CODE,
    RouterBelowMinNotionalError,
    RouterCrossMarginError,
    RouterError,
    RouterOrderPostureError,
    RouterOrderRoundingError,
)
from .exchange_info import RouterSymbolFilters
from .margin import ISOLATED_MARGIN, require_isolated_margin
from .notional import require_min_notional
from .posture import resolve_order_posture
from .rounding import require_rounded_order

__all__ = [
    "BELOW_MIN_QUANTITY_CODE",
    "BINGX_BUY",
    "BINGX_MARKET_ORDER",
    "BINGX_ORDER_CODE",
    "BINGX_ORDER_TYPES",
    "BINGX_POSITION_SIDE_BOTH",
    "BINGX_POST_ONLY",
    "BINGX_SELL",
    "BINGX_SIDES",
    "BingXOrder",
    "BingXRefusedLeg",
    "RouterBelowMinQuantityError",
    "RouterBingXOrderError",
    "assemble_bingx_order",
]

#: The greppable token for the one judgment this module adds to the gate
#: order — the venue's minimum quantity, from the ``tradeMinQuantity``
#: field feature 1's translation carries as
#: :attr:`~router.exchange_info.RouterSymbolFilters.min_qty`.  Coined on
#: the exact shape of feature 313's own
#: :data:`router.errors.BELOW_MIN_NOTIONAL_CODE` (``below_`` + the bound
#: that was fallen short of), because the two refusals are siblings: an
#: order can clear the floor with its value and still be too *small in
#: units* for the venue to book, and an operator sent from one to the
#: other would re-judge an order that passed.  Defined here rather than in
#: :mod:`router.errors` because this addition's refusals stay in the
#: module that raises them, so parallel features never edit another
#: module's vocabulary.
BELOW_MIN_QUANTITY_CODE = "below_min_quantity"

#: The greppable token for an ask this module cannot read — a delta or a
#: mark offered as a float, a symbol that states nothing — the faults of
#: the *call* rather than facts about a leg the venue refused.  The spec's
#: conventions state this addition's new refusals subclass
#: :class:`~router.errors.RouterError` in the module that raises them;
#: this is the assembly's own, beside :mod:`router.bingx_documents`'
#: document-shape class for the same reason: a caller handed the wrong
#: repair by a mislabelled fault edits the wrong file.
BINGX_ORDER_CODE = "bingx_order"

#: BingX's own spelling of the two sides an order can take.  The venue's
#: vocabulary, not the system's: a signed delta is the book's arithmetic,
#: and ``BUY`` / ``SELL`` is how this venue spells the sign on the wire —
#: declared here at the venue boundary, the one home for the venue's
#: words, rather than derived ad hoc at each send.
BINGX_BUY = "BUY"
BINGX_SELL = "SELL"

#: The closed side vocabulary, exactly two, so a value of this module's
#: own cannot be built carrying a side no venue states.
BINGX_SIDES = frozenset({BINGX_BUY, BINGX_SELL})

#: BingX's position-side mode for the order path: ``BOTH`` — one-way
#: position mode, where the account holds one signed position per symbol
#: and the side of the order *is* the direction.  It is the mode the book
#: member's signed weights (a positive and a negative target on the same
#: symbol's line) and feature 2's signed deltas already speak, so the
#: parameter is a constant of this venue's order shape rather than a
#: decision made per leg.
BINGX_POSITION_SIDE_BOTH = "BOTH"

#: BingX's order types, and the posture translation: feature 314's
#: ``passive`` is a ``LIMIT`` order that sits on the book and waits
#: (:data:`BINGX_POST_ONLY` below), and ``aggressive`` is a ``MARKET``
#: order that crosses and takes.  The mapping lives here — not in
#: :mod:`router.posture`, which refuses to spell venue flags — because
#: the flags are this venue's constants, and feature 311's law places
#: them at the venue boundary only.
BINGX_LIMIT_ORDER = "LIMIT"
BINGX_MARKET_ORDER = "MARKET"
BINGX_ORDER_TYPES = frozenset({BINGX_LIMIT_ORDER, BINGX_MARKET_ORDER})

#: BingX's time-in-force spelling of §13.2's *post-only*: the order rests
#: on the book as a maker order or is refused — it never crosses.  This
#: is the venue's own token for feature 314's :data:`~router.posture.
#: PASSIVE_ORDER`, spelled once, here, for the same reason the
#: 40-character cap is spelled in :mod:`router.bingx_client_order_id`.
BINGX_POST_ONLY = "PostOnly"


class RouterBingXOrderError(RouterError):
    """An ask the assembler cannot read — a wiring fault, not a refused leg.

    Raised for a term of the *call* rather than a fact about a leg the
    venue refused: a delta or a mark that is not an exact decimal (a
    float is a binary approximation of a number no venue ever sent), a
    symbol that states nothing, a value of :class:`BingXOrder` built with
    a side, a type or a field spelling the venue does not carry.  These
    propagate out of :func:`assemble_bingx_order` rather than folding
    into a :class:`BingXRefusedLeg`, because a plan that printed its own
    caller's bugs as market facts would be a plan nobody could trust on
    the legs that mattered.

    Every message opens with :data:`BINGX_ORDER_CODE` and names the one
    repair, the discipline every class in this member's vocabulary keeps.
    """


class RouterBelowMinQuantityError(RouterError):
    """An order whose size in units falls below the venue's minimum quantity.

    The fourth gate in the spec's fixed order, and the one judgment on
    that list no existing module owns: feature 312 judges the two grids
    and feature 313 the one floor, while ``tradeMinQuantity`` — carried
    verbatim as :attr:`~router.exchange_info.RouterSymbolFilters.min_qty`
    by feature 1's translation — is a bound neither sentence names.  An
    order can sit exactly on the step grid and clear the notional floor
    and still be too small in *units* for the venue to book, which is a
    different repair from either of those refusals: *size the leg up*,
    at the sizing step that answers to the book's weights, the same
    repair feature 313's refusal names one gate earlier.

    A sibling of :class:`~router.errors.RouterBelowMinNotionalError`
    rather than a child of it: the notional floor judges an order's
    *value* and this judges its *size*, an order can pass either while
    failing the other, and a caller told the wrong one would re-judge an
    order that passed.  Defined here rather than in :mod:`router.errors`
    so this addition never edits another module's vocabulary — the same
    placement :mod:`router.sizing` gives its own refusal.

    Every message opens with :data:`BELOW_MIN_QUANTITY_CODE` and names
    the symbol, the quantity and the floor, because the shortfall is
    arithmetic the sizing step owns and this refusal is the only place
    it is reported.
    """


@dataclass(frozen=True)
class BingXRefusedLeg:
    """One leg the gates closed: the refusing gate's code word, and the symbol.

    The value a refused leg *returns ... instead of an order*, in the
    spec's words.  A plan states which legs it would send and which leg
    the venue's own standing facts close, side by side — a leg the
    notional floor refused beside the five orders its siblings became —
    so a refusal is an answer of the same act as an order, not an
    exception that unwinds it.

    * ``symbol`` — the leg the refusal is about, BingX's own hyphenated
      spelling end to end (``BTC-USDT``; nothing here maps it to
      Binance's ``BTCUSDT``).
    * ``code`` — the refusing gate's own greppable token, read from the
      gate that raised rather than re-spelled here: ``order_posture``,
      ``order_rounding``, ``below_min_notional``, ``below_min_quantity``
      or ``cross_margin`` for the five gates in the spec's list, and the
      feature 1 document codes (``not_tradable``, ``missing_mark_price``)
      for a leg the venue's documents closed before any gate ran.  An
      operator greps the code word and lands on the gate that refused,
      which is the whole reason gates spell code words.

    It deliberately carries no message: the code word *is* the gate's
    address, and the gate's own message — with its terms and its repair
    — is where the code word leads.  Frozen and hashable, so a plan can
    hold its legs in any structure the caller wants.
    """

    symbol: str
    code: str

    def __post_init__(self) -> None:
        # Canonicalised at construction for the same reason every value in
        # this member is: a plan holding a leg built by hand and a leg the
        # verb answered compares them as the same fact.  The code is not
        # checked against a closed set here because the set is the gates'
        # own vocabularies — this value carries whatever gate refused, and
        # inventing a second spelling of a gate's token to check it
        # against would be two vocabularies for one word.
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: a refused leg names the symbol the "
                f"gate refused, got {self.symbol!r} "
                f"({type(self.symbol).__name__}); an operator's next "
                "question is always *which leg*, and a refusal that names "
                "no leg answers nothing"
            )
        if not isinstance(self.code, str) or not self.code.strip():
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: a refused leg carries its gate's code "
                f"word, got {self.code!r} ({type(self.code).__name__}); the "
                "code word is what an operator greps to reach the gate that "
                "refused, and a refusal without it greps nothing"
            )
        object.__setattr__(self, "symbol", self.symbol.strip())
        object.__setattr__(self, "code", self.code.strip())


@dataclass(frozen=True)
class BingXOrder:
    """One would-send BingX order: the request's parameters, as strings.

    The value :func:`assemble_bingx_order` answers for a leg every gate
    admitted — the parameters POST /openApi/swap/v2/trade/order would
    receive, in the venue's own field spellings and the exact decimal
    spellings the arithmetic answered:

    * ``symbol`` — the leg, BingX's hyphenated spelling end to end.
    * ``side`` — :data:`BINGX_BUY` or :data:`BINGX_SELL`: the sign of
      the sized delta, spelled the way the venue reads it.
    * ``position_side`` — :data:`BINGX_POSITION_SIDE_BOTH`, the one-way
      position mode the signed book already speaks.
    * ``type`` — :data:`BINGX_LIMIT_ORDER` for a passive leg,
      :data:`BINGX_MARKET_ORDER` for an aggressive one.
    * ``quantity`` — the magnitude of the sized delta, as the exact
      string its :class:`~decimal.Decimal` spells (a ``0.0001`` grid
      answers four decimal places; BTC-USDT's ``0.0140`` keeps its
      trailing zero).
    * ``price`` — the passively-rounded mark, for a ``LIMIT`` leg;
      ``None`` for a ``MARKET`` leg, which carries no price — *"type
      MARKET with no price"*, the sentence's own words.
    * ``time_in_force`` — :data:`BINGX_POST_ONLY` for a ``LIMIT`` leg;
      ``None`` for a ``MARKET`` leg, which takes no time in force at all.
    * ``client_order_id`` — feature 3's projection of feature 316's
      identifier: the venue field's payload, never the system's own name
      for the order (the placement store's idempotency key stays the
      full 64-hex identifier, and nothing joins on the projection).

    All fields are canonicalised at construction — the closed side, type
    and position-side vocabularies checked, the price/time-in-force pair
    required exactly when the type is ``LIMIT`` and refused otherwise,
    the decimal spellings read as exact finite decimals, the
    ``client_order_id`` held to the venue's own 40-character cap — so
    a value built by hand in a test or reconstructed from a record gets
    the same judgment the verb applies.  Frozen, and hashable: an order
    can stand as its own key.
    """

    symbol: str
    side: str
    position_side: str
    type: str
    quantity: str
    price: str | None
    time_in_force: str | None
    client_order_id: str

    def __post_init__(self) -> None:
        # Normalize rather than trust, in the fixed order the verb builds
        # the fields in: the identity of the leg, then the venue's
        # vocabularies, then the terms, then the identity payload.
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: symbol must be non-empty text, got "
                f"{self.symbol!r} ({type(self.symbol).__name__}); the symbol "
                "is the leg the order is for and the key the venue's "
                "filters are filed under, so an order that names no leg "
                "names no grid to have been judged against"
            )
        symbol = self.symbol.strip()
        if self.side not in BINGX_SIDES:
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: a BingX order's side is one of "
                f"{sorted(BINGX_SIDES)}, got {self.side!r} "
                f"({type(self.side).__name__}); the side is the sign of "
                "the sized delta as this venue spells it, and a value "
                "outside the vocabulary is a direction no venue books"
            )
        if self.type not in BINGX_ORDER_TYPES:
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: a BingX order's type is one of "
                f"{sorted(BINGX_ORDER_TYPES)}, got {self.type!r} "
                f"({type(self.type).__name__}); the type is feature 314's "
                "posture as this venue spells it, and a value outside the "
                "vocabulary is a crossing no posture compelled"
            )
        if not isinstance(self.position_side, str) or not self.position_side:
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: a BingX order's positionSide is "
                f"{BINGX_POSITION_SIDE_BOTH!r} in the one-way position mode "
                f"the signed book speaks, got {self.position_side!r} "
                f"({type(self.position_side).__name__})"
            )
        if self.type == BINGX_MARKET_ORDER and (
            self.price is not None or self.time_in_force is not None
        ):
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: a {BINGX_MARKET_ORDER} order carries "
                "no price and no timeInForce — it crosses at the venue's "
                f"own price — got price {self.price!r} and timeInForce "
                f"{self.time_in_force!r} for {symbol!r}"
            )
        if self.type == BINGX_LIMIT_ORDER and (
            self.price is None or self.time_in_force is None
        ):
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: a {BINGX_LIMIT_ORDER} order carries "
                "both a price and a timeInForce — it rests on the book "
                "until its force says otherwise — got price "
                f"{self.price!r} and timeInForce {self.time_in_force!r} "
                f"for {symbol!r}"
            )
        for term, value in (("quantity", self.quantity), ("price", self.price)):
            if value is None:
                continue
            if not isinstance(value, str):
                raise RouterBingXOrderError(
                    f"{BINGX_ORDER_CODE}: {term} is the exact decimal "
                    f"spelling the arithmetic answered, got {value!r} "
                    f"({type(value).__name__}); a number re-serialised at "
                    "the send would be a second spelling of a decimal this "
                    "module already chose"
                )
            try:
                parsed = Decimal(value)
            except InvalidOperation as exc:
                raise RouterBingXOrderError(
                    f"{BINGX_ORDER_CODE}: {term} {value!r} is not a decimal "
                    f"an order can carry for {symbol!r}"
                ) from exc
            if not parsed.is_finite() or parsed <= 0:
                raise RouterBingXOrderError(
                    f"{BINGX_ORDER_CODE}: {term} {value!r} must be a "
                    f"positive finite decimal for {symbol!r}; a size or a "
                    "price at or below zero is not one any venue books"
                )
        if (
            not isinstance(self.client_order_id, str)
            or not self.client_order_id
            or len(self.client_order_id) > BINGX_CLIENT_ORDER_ID_LENGTH
        ):
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: clientOrderID is feature 3's "
                "projection of feature 316's identifier — at most "
                f"{BINGX_CLIENT_ORDER_ID_LENGTH} characters — got "
                f"{self.client_order_id!r}; the venue refuses a longer "
                "field, and a value this module re-truncated to fit would "
                "be a second projection of one order"
            )
        object.__setattr__(self, "symbol", symbol)

    def parameters(self) -> dict[str, str]:
        """The request's parameters, in the venue's own field spellings.

        One line of the dry run's plan is ``json.dumps`` of this answer.
        The keys are the endpoint's own — ``symbol``, ``side``,
        ``positionSide``, ``type``, ``quantity``, ``price``,
        ``timeInForce``, ``clientOrderID`` — and every value is a string,
        the spelling the venue reads.  A ``MARKET`` leg's object carries
        no ``price`` and no ``timeInForce`` key at all rather than null
        spellings of them: the request would not carry the fields, so
        the plan does not either, and a reader counting the parameters
        counts the ones the venue would read.
        """
        parameters: dict[str, str] = {
            "symbol": self.symbol,
            "side": self.side,
            "positionSide": self.position_side,
            "type": self.type,
            "quantity": self.quantity,
        }
        if self.type == BINGX_LIMIT_ORDER:
            assert self.price is not None  # required by __post_init__
            parameters["price"] = self.price
            parameters["timeInForce"] = self.time_in_force
        parameters["clientOrderID"] = self.client_order_id
        return parameters


#: The gates in the spec's fixed order, keyed by the exception each one
#: raises, valued by that gate's own code word — so a refused leg carries
#: the token of the gate that refused it, read from :mod:`router.errors`
#: rather than re-spelled here.  Exactly the five judgments the sentence
#: lists; any other :class:`~router.errors.RouterError` is a fault of the
#: ask rather than a leg the venue refused, and propagates.
_GATE_REFUSAL_CODES = {
    RouterOrderPostureError: ORDER_POSTURE_CODE,
    RouterOrderRoundingError: ORDER_ROUNDING_CODE,
    RouterBelowMinNotionalError: BELOW_MIN_NOTIONAL_CODE,
    RouterBelowMinQuantityError: BELOW_MIN_QUANTITY_CODE,
    RouterCrossMarginError: CROSS_MARGIN_CODE,
}


def _as_decimal(value: Any, term: str, symbol: str) -> Decimal:
    """Return ``value`` as an exact decimal, or refuse it by name.

    The two spellings this module reads are the speaker's own string and
    an exact :class:`~decimal.Decimal`, the rule every decimal term in
    this member holds: a :class:`float` is a binary approximation of a
    decimal no venue ever sent, and a delta or a mark read approximately
    would price an order nobody chose.  ``NaN`` and the two infinities
    parse as decimals and are refused separately, because a size or a
    price that is not a number cannot be judged by any gate downstream.
    """
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise RouterBingXOrderError(
                f"{BINGX_ORDER_CODE}: {term} {value!r} for {symbol!r} is "
                "not a decimal an order can be assembled from"
            ) from exc
    else:
        raise RouterBingXOrderError(
            f"{BINGX_ORDER_CODE}: {term} for {symbol!r} must be a decimal "
            f"string or a Decimal, got {value!r} ({type(value).__name__}); a "
            "float is a binary approximation of a decimal no venue ever "
            "sent, and a term read approximately would reach the wire as "
            "a quantity or a price nobody chose"
        )
    if not number.is_finite():
        raise RouterBingXOrderError(
            f"{BINGX_ORDER_CODE}: {term} for {symbol!r} must be a finite "
            f"decimal, got {number!r}; a value that is not a number cannot "
            "be sized, priced or judged by any gate in the order's path"
        )
    return number


def _tick_grid(filters: Any, symbol: str) -> Decimal:
    """Return the venue's price grid for ``symbol``, or refuse what cannot price a leg.

    Read here — before the grids gate runs — for one purpose: a passive
    leg's price is *chosen* onto the tick grid, and the choice needs the
    grid the venue stated, exactly as feature 2 needed the step grid to
    truncate a quantity onto.  The standing facts are judged in feature
    312's own order and vocabulary: the filters must be feature 310's
    own value, they must be the leg's symbol's own (a price rounded onto
    another symbol's grid is a price about the wrong instrument), and a
    venue that states no tick size leaves the leg unpriceable — refused,
    never defaulted, because a grid this module invented would be exactly
    the hardcoded venue constant feature 311 forbids.  The gate re-judges
    all of this when it judges the chosen price; this read exists so the
    choice can be made at all.
    """
    if filters is None or not isinstance(filters, RouterSymbolFilters):
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the filters held for {symbol!r} must be "
            f"feature 310's RouterSymbolFilters, got {filters!r} "
            f"({type(filters).__name__}); a passive price is chosen on the "
            "venue's own tick grid, and a value that is not that carries "
            "no grid to choose on (feature 312)"
        )
    if filters.symbol != symbol:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the order is for {symbol!r} but the "
            f"filters are {filters.symbol!r}'s; a price rounded onto another "
            "symbol's tick grid is a price about the wrong instrument — one "
            "symbol, one spelling, one grid (feature 312)"
        )
    if filters.tick_size is None:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the venue states no tick size for "
            f"{symbol!r} — the translated contract document carries no price "
            "grid for the symbol — so a passive leg cannot be priced onto "
            "the venue's grid at all; the leg is refused rather than priced "
            "unsnapped, because a grid this module defaulted would be "
            "exactly the hardcoded venue constant feature 311 forbids "
            "(feature 312)"
        )
    tick = Decimal(str(filters.tick_size))
    if not tick.is_finite() or tick <= 0:
        raise RouterOrderRoundingError(
            f"{ORDER_ROUNDING_CODE}: the tick size for {symbol!r} must be a "
            f"positive decimal, got {tick!r}; a grid of zero divides nothing "
            "— every price would sit on it and none would be quantised — and "
            "a negative grid is one no venue states (feature 312)"
        )
    return tick


def _passive_price(mark: Decimal, tick: Decimal, side: str) -> Decimal:
    """The mark rounded onto the tick grid, away from the crossing.

    The one choice this layer owns, and the price-side spelling of the
    arithmetic feature 2 states for quantities: a passive order must not
    cross the spread — the venue refuses a ``PostOnly`` order that would
    — so the mark is rounded to the neighbouring grid value on the
    *passive* side.  Down for a ``BUY``: a bid below the mark rests on
    the book, and rounding up could post a bid at or through the ask.
    Up for a ``SELL``: an offer above the mark rests, and rounding down
    could cross the bid.  Exact :class:`~decimal.Decimal` modulo — the
    remainder of the mark over the tick — computes the neighbour by
    subtraction rather than division, so the answer never carries a
    rounding of its own, and a mark already on the grid is returned
    verbatim, in its own spelling.  The grids gate then judges the
    chosen value, exactly as it judges the quantity feature 2 chose.
    """
    remainder = mark % tick
    if remainder == 0:
        return mark
    below = mark - remainder
    return below if side == BINGX_BUY else below + tick


def _require_min_quantity(quantity: Decimal, filters: Any, symbol: str) -> None:
    """The sentence's fourth gate: the venue's minimum quantity.

    The one judgment in the fixed order no existing module owns — feature
    312's sentence names the two grids, feature 313's the one floor, and
    ``tradeMinQuantity`` is a bound neither names — so it is stated here,
    in this addition's own vocabulary, reading the ``min_qty`` feature
    1's translation carried verbatim from the venue's own document.  The
    bound arrives as feature 310's value or not at all (feature 311's
    law, one gate over from where it was first made structural): a venue
    that states no minimum quantity leaves the leg unjudgeable, and
    unjudgeable is refused, never defaulted.  *Below* is strict, as
    feature 313's floor is strict with the notional: an order of exactly
    the minimum units is at the bound, not below it, and trades.  A
    stated bound of zero is admissible and vacuous, while a negative one
    is refused because a negative minimum is not a minimum.
    """
    if not isinstance(filters, RouterSymbolFilters):
        # The grids gate has already judged the filters' shape by the time
        # this gate runs (it is one gate earlier in the fixed order), so
        # this branch is the value-layer restatement of that judgment —
        # stated rather than assumed, the discipline every validator here
        # keeps.
        raise RouterBelowMinQuantityError(
            f"{BELOW_MIN_QUANTITY_CODE}: the filters held for {symbol!r} "
            f"must be feature 310's RouterSymbolFilters, got {filters!r} "
            f"({type(filters).__name__}); a quantity is judged against the "
            "venue's own minimum as the translated contract document "
            "spells it, and a value that is not that carries no bound to "
            "judge against"
        )
    if filters.min_qty is None:
        raise RouterBelowMinQuantityError(
            f"{BELOW_MIN_QUANTITY_CODE}: the venue states no minimum "
            f"quantity for {symbol!r} — the translated contract document "
            "carries no tradeMinQuantity for the symbol — so the order's "
            "size cannot be judged against a bound at all; the leg is "
            "refused rather than passed as unconstrained, because a bound "
            "this module defaulted would be exactly the hardcoded venue "
            "constant feature 311 forbids"
        )
    if isinstance(filters.min_qty, Decimal):
        floor = filters.min_qty
    elif isinstance(filters.min_qty, str):
        try:
            floor = Decimal(filters.min_qty)
        except InvalidOperation as exc:
            raise RouterBelowMinQuantityError(
                f"{BELOW_MIN_QUANTITY_CODE}: the minimum quantity "
                f"{filters.min_qty!r} for {symbol!r} is not a decimal an "
                "order can be judged against"
            ) from exc
    else:
        raise RouterBelowMinQuantityError(
            f"{BELOW_MIN_QUANTITY_CODE}: the minimum quantity for "
            f"{symbol!r} must be a decimal string or a Decimal, got "
            f"{filters.min_qty!r} ({type(filters.min_qty).__name__}); a "
            "float is a binary approximation of a decimal no venue ever "
            "sent, and a bound read approximately would misjudge the very "
            "size it was offered"
        )
    if not floor.is_finite():
        raise RouterBelowMinQuantityError(
            f"{BELOW_MIN_QUANTITY_CODE}: the minimum quantity for "
            f"{symbol!r} must be a finite decimal, got {floor!r}; a size "
            "cannot be judged against a bound that is not a number"
        )
    if floor < 0:
        raise RouterBelowMinQuantityError(
            f"{BELOW_MIN_QUANTITY_CODE}: the minimum quantity for "
            f"{symbol!r} must not be negative, got {floor!r}; a negative "
            "minimum is not a minimum — it would admit every order, "
            "including the ones this gate exists to refuse"
        )
    if quantity < floor:
        raise RouterBelowMinQuantityError(
            f"{BELOW_MIN_QUANTITY_CODE}: the order for {symbol!r} carries "
            f"{quantity!r}, which falls below the venue's minimum quantity "
            f"{floor!r} (tradeMinQuantity); the quantity sits on the step "
            "size and the order's value clears the notional floor, so this "
            "is not a rounding or a notional repair — size the leg up, at "
            "the sizing step that answers to the book's weights"
        )


def assemble_bingx_order(
    *,
    symbol: Any,
    delta: Any,
    mark: Any,
    filters: Any,
    signal_decay_horizon: Any,
    expected_fill_time: Any,
    client_order_id: Any,
    book_id: Any,
    account: Any,
    mode: Any = ISOLATED_MARGIN,
) -> BingXOrder | BingXRefusedLeg:
    """Feature 4's verb: assemble one sized delta into a BingX order.

    The sentence's fixed order, one gate at a time — posture (314), the
    step and tick grids (312), the notional floor (313), the minimum
    quantity, isolated margin (315) — and the answer is the frozen
    :class:`BingXOrder` carrying the parameters POST
    /openApi/swap/v2/trade/order would receive, or the
    :class:`BingXRefusedLeg` carrying the refusing gate's code word and
    the symbol.  Nothing is sent: this is the plan the dry run prints,
    not the request the venue receives.

    Each argument is a required keyword with no default except ``mode``,
    which defaults to :data:`~router.margin.ISOLATED_MARGIN` for the same
    reason :func:`router.margin.require_isolated_margin`'s own does —
    *system uses isolated margin* is the configured default, and a caller
    states another mode only to state the configuration being judged:

    * ``symbol`` — the leg, BingX's own hyphenated spelling end to end.
    * ``delta`` — feature 2's signed contract quantity for the leg: its
      sign becomes the side and its magnitude the quantity, exactly as
      the sizer truncated it onto the step grid (this module never
      re-rounds a quantity — the gates judge it).
    * ``mark`` — the Decimal mark the leg was sized against, as feature
      1's premiumIndex reader answered it.  A passive leg's price is
      this mark rounded onto the tick grid away from the crossing (down
      for a ``BUY``, up for a ``SELL``); an aggressive leg carries no
      price, and its value is judged at the mark.
    * ``filters`` — feature 310's
      :class:`~router.exchange_info.RouterSymbolFilters` for the symbol,
      as feature 1's contracts translator answered it: the grids, the
      floor and the minimum the gates judge against.
    * ``signal_decay_horizon`` and ``expected_fill_time`` — the two
      durations feature 314 reads, the book's decay horizon for the
      symbol and its expected fill time.
    * ``client_order_id`` — feature 316's
      :class:`~router.client_order_id.ClientOrderId` for this order;
      the venue's ``clientOrderID`` field is feature 3's projection of
      it, applied here once, at the boundary.
    * ``book_id`` and ``account`` — the margin arrangement's own terms,
      judged by feature 315's gate under ``mode``.

    **The gates' refusals are answers, not exceptions** — a plan states
    which legs it would send and which the gates closed, side by side —
    so each of the five gates' own errors folds into the refused leg
    with that gate's code word.  Anything else propagates: a term this
    module cannot read is a fault of the ask, and the identity
    projection's refusals are feature 316's own (read through
    :func:`router.client_order_id.normalize_client_order_id`, never
    re-implemented here).

    Deterministic by construction: a pure function of its terms under the
    default decimal context, no clock, no state, no store, no I/O — the
    same ask answers the same order, or the same refused leg, in any
    process, which is what makes the dry run safe to run anywhere and
    the whole of the contract.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise RouterBingXOrderError(
            f"{BINGX_ORDER_CODE}: symbol must be non-empty text, got "
            f"{symbol!r} ({type(symbol).__name__}); the symbol is the leg "
            "the order is for, the key the venue's filters are filed under "
            "and a term of the order's own identity, so an ask that names "
            "no leg assembles no order"
        )
    name = symbol.strip()
    signed = _as_decimal(delta, "the sized delta", name)
    mark_price = _as_decimal(mark, "the mark price", name)

    try:
        # Gate 1 — posture (314).  First because it decides which of the
        # two request shapes the leg is assembling into: a LIMIT that
        # rests, or a MARKET that crosses.  The verb takes no posture
        # argument, so the single door to an aggressive order is this
        # comparison, and the assembly reads the verdict it compels.
        posture = resolve_order_posture(
            signal_decay_horizon=signal_decay_horizon,
            expected_fill_time=expected_fill_time,
        )
        side = BINGX_BUY if signed > 0 else BINGX_SELL
        size = abs(signed)

        # Gate 2 — the step and tick grids (312).  A passive leg's price
        # is chosen first, on the tick grid and away from the crossing,
        # and then judged with the quantity: the gates judge every order
        # and never round one, so the choice is made here — the layer
        # whose consequence is visible against the weights it answers
        # to — exactly as feature 2 chooses the quantity one layer up.
        # An aggressive leg carries no price, so the price term its gates
        # read is the mark itself: the grids judge the mark the venue
        # published against the tick grid that same venue publishes, and
        # the notional floor below is judged on that order, at the mark.
        if posture.is_aggressive:
            rounded = require_rounded_order(
                symbol=name, quantity=size, price=mark_price, filters=filters
            )
        else:
            rounded = require_rounded_order(
                symbol=name,
                quantity=size,
                price=_passive_price(
                    mark_price, _tick_grid(filters, name), side
                ),
                filters=filters,
            )

        # Gate 3 — the notional floor (313), over the order the grids
        # just answered, so the two gates cannot disagree about the
        # terms: the passive leg at its own limit price, the aggressive
        # leg at the mark.
        require_min_notional(order=rounded, filters=filters)

        # Gate 4 — the minimum quantity, the one judgment on the list
        # this module owns.
        _require_min_quantity(size, filters, name)

        # Gate 5 — isolated margin (315), under the book's own mode and
        # account label, before anything is placed.
        require_isolated_margin(book_id=book_id, account=account, mode=mode)
    except RouterError as exc:
        # A leg the gates closed is an answer of this same act — the plan
        # states it beside the orders its siblings became — carrying the
        # refusing gate's own code word.  A RouterError no gate in the
        # fixed order owns is a fault of the ask rather than a fact about
        # the leg, and propagates.
        code = _GATE_REFUSAL_CODES.get(type(exc))
        if code is None:
            raise
        return BingXRefusedLeg(symbol=name, code=code)

    # The identity, projected once at the boundary: the venue field's
    # payload is feature 3's answer over feature 316's value, and this
    # module never re-derives or re-truncates it.
    projected = project_bingx_client_order_id(client_order_id)

    if posture.is_aggressive:
        return BingXOrder(
            symbol=name,
            side=side,
            position_side=BINGX_POSITION_SIDE_BOTH,
            type=BINGX_MARKET_ORDER,
            quantity=str(size),
            price=None,
            time_in_force=None,
            client_order_id=projected,
        )
    return BingXOrder(
        symbol=name,
        side=side,
        position_side=BINGX_POSITION_SIDE_BOTH,
        type=BINGX_LIMIT_ORDER,
        quantity=str(size),
        price=str(rounded.price),
        time_in_force=BINGX_POST_ONLY,
        client_order_id=projected,
    )
