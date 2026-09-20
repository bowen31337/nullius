"""Feature 61's fee layer: taker and maker fees in basis points, per venue.

app_spec.xml, "Cost Model & Fill Simulation", feature 61: *System applies
taker and maker fees in basis points per venue, which returns a post-cost
return series.*  docs/nullius-tech-architecture.md §6.2 fixes the fee
schedule in the document itself, under its own ``fees`` block:

.. code-block:: yaml

    cost_model:
      version: "2026.09.1"
      venue: binance_spot
      fees:
        taker_bps: 10.0
        maker_bps: 10.0
        discount_token: BNB        # → 7.5 bps  (feature 62: cost_model.discount)

The sentence has four separable claims, and this module owns all four:

* **taker and maker fees** — the schedule carries *two* rates, because a
  fill reaches the book on one of two sides and each side pays a different
  price for liquidity.  A *taker* order crosses the spread by intent — it
  lifts the ask or hits the bid, consuming resting liquidity, and pays the
  taker rate for the immediacy it took (the aggressive order of feature 66
  is a taker).  A *maker* order rests and waits — it posts a quote and lets
  the tape come to it, providing the liquidity the taker consumes, and pays
  the maker rate (the passive order of feature 63 is a maker).  The two
  rates are distinct inputs with distinct fields (:attr:`FeeSchedule.taker_bps`
  and :attr:`FeeSchedule.maker_bps`), and a caller selects the one its fill
  earned by naming the side — :data:`TAKER` or :data:`MAKER` — so a taker
  fill can never be priced at the maker rate by a sign error, and the two
  cannot collapse into one blended number the document never named.
* **in basis points** — the cost is spoken in the unit §6.2's whole fee
  schedule already speaks, and the same unit the aggressive walk's slippage
  (:attr:`cost_model.book_walk.BookWalk.slippage_bps`) and the queue
  penalty (:attr:`cost_model.queue_penalty.QueuePenalty.cost_bps`) report —
  so a caller can add a fee, a slippage figure and a queue cost with one
  sum rather than converting each through a different unit and inventing a
  third spelling of "cost".  A basis point is ``1e-4`` as a fraction, so
  ``10 bps`` is ``0.001``, and the fee is deducted from a return — itself a
  fraction of the notional — in the units the return is denominated in.
* **per venue** — the schedule is *identified by the venue it prices*.  The
  taker and maker rates are not free-floating numbers: they are
  ``binance_spot``'s rates, or whoever else's schedule is loaded, and they
  travel with the venue name (:attr:`FeeSchedule.venue`) so a post-cost
  series names whose fees were taken off it.  This is the same pairing
  feature 59 persists — a version *with* its venue, meaningless apart —
  applied to the fee axis: ``10`` bps alone does not say whose 10 bps, and
  a cost model that priced two venues would carry two schedules, not one.
* **which returns a post-cost return series** — the deliverable, and the
  claim that makes the fee a *cost* rather than a number: a pre-cost return
  series goes in and a post-cost one comes out, each element reduced by the
  fee the fill that earned it was charged.  The fee is a cost of *trading* —
  it is paid on the notional that turned over, regardless of which way the
  price moved — so it is subtracted from the return rather than scaled by
  it: a winning return and a losing return pay the same fee, because the
  exchange charges the trade and not the outcome.  Each element of the
  series is one unit of traded notional and one application of the side's
  per-trade rate, so ``post = pre − rate/10 000``; a strategy that opens
  *and* closes a position applies the fee on both legs, which is two
  elements, which is the round trip priced honestly rather than a single
  doubled figure this module would have to invent.

**The rate is a resolved value, and feature 62 substitutes it.**  What this
feature resolves out of §6.2 is the *rate* — :meth:`FeeSchedule.rate`
answers, for a side, the basis points that side pays — and what it applies
is that rate.  Feature 62's discount token does not re-derive the cost: it
hands this module a *different rate* (an effective ``7.5`` bps in place of
``10``) and the same subtraction produces the post-cost series, so the
discount is a change to one input rather than a second implementation of
the charge (feature 69's promise, and §6.2's ``β₄`` — the evaluator and
the live engine deduct the fee the same way because they call
:func:`apply_fee` on the same :class:`FeeSchedule`).  That substitution is
:mod:`cost_model.discount`'s: it reads the section's ``discount_token`` and
returns a :class:`FeeSchedule` whose rates are already reduced, so the charge
below stays the only arithmetic there is.

**No blended rate, no direction waiver.**  :func:`resolve_fee_schedule`
reads §6.2's ``fees.taker_bps`` and ``fees.maker_bps`` and refuses a
document that omits either — a fee defaulted to zero silently is the
floored simulator `docs/alpha-engine-prd.md` §10 warns about, and a cost
model that cannot price one side of a fill is not a cost model.  There is
no "average the two" mode and no "waive the maker fee" toggle: each would
be a different fee behind configuration, and a library that carried them
would let research evaluation and live execution drift apart — exactly the
divergence §6.2's ``β₄`` penalizes and feature 69 forbids.  The section's
``discount_token`` field belongs to feature 62 — it is tolerated here and
not read, because this resolver answers for the two plain rates only and
:func:`cost_model.discount.resolve_fee_discount` is the resolver that reads
the token and reduces the rates this one returns.

The module holds no state and no third-party import: the schedule arrives
as a value, the return series arrives as values, the post-cost series
returns as values, and nothing is persisted — feature 79's evaluator
``apply_costs`` step is the persistence, and it reaches this charge through
the injected :class:`~evaluator.CostSchedule` seam rather than by
re-implementing it, which is how §6.2's *"the same code, not two
implementations of the same document"* holds for the fee axis too.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .config import read_cost_model_document
from .errors import CostModelConfigError, CostModelFillError

__all__ = [
    "FEES_KEY",
    "MAKER",
    "MAKER_BPS_KEY",
    "TAKER",
    "TAKER_BPS_KEY",
    "FeeSchedule",
    "PostCostReturn",
    "apply_fee",
    "resolve_fee_schedule",
]

#: A taker fill — the order that crosses the spread and consumes resting
#: liquidity, paying the taker rate for its immediacy.  One of the two
#: sides :func:`apply_fee` prices; the other is :data:`MAKER`.
TAKER = "taker"

#: A maker fill — the order that rests and provides the liquidity a taker
#: consumes, paying the maker rate.  The other of the two sides
#: :func:`apply_fee` prices.
MAKER = "maker"

#: The two fee sides, in the order a summary reports them.  A side names
#: which of a schedule's two rates a fill is charged — there is no third.
_SIDES = (TAKER, MAKER)

#: The document's own key for the fee schedule (§6.2: the ``fees`` block).
FEES_KEY = "fees"

#: The fee schedule's taker rate (§6.2: ``taker_bps: 10.0``) — the rate a
#: crossing order pays, and one of the two this module resolves.
TAKER_BPS_KEY = "taker_bps"

#: The fee schedule's maker rate (§6.2: ``maker_bps: 10.0``) — the rate a
#: resting order pays, and the other of the two this module resolves.
MAKER_BPS_KEY = "maker_bps"

#: Basis points per unit of rate — the unit the fee is spoken in, spelled
#: once so the fee schedule's bps, the aggressive walk's bps and the queue
#: penalty's bps cannot drift into three different arithmetic constants.
#: ``1 bps`` is ``1e-4`` as a fraction, so ``10 bps`` is ``0.001`` and a
#: caller deducting the fraction from a return gets the cost in the same
#: units as the return it is taken from.
_BPS_PER_UNIT = 10_000.0


def _non_negative_bps(value: object) -> float | None:
    """Return ``value`` as a non-negative finite fee rate, or ``None``.

    The shared body of the module's two validators — see
    :func:`_fee_bps` and :func:`_configured_fee_bps` for why the *rule* is
    one function while the *error* it raises is two.  Booleans are refused
    explicitly because ``isinstance(True, int)``: a fee of ``True`` is a
    broken caller, not a one-basis-point charge.

    Zero is accepted and is a *fact*, not a defect: an operator may
    genuinely measure a venue's fee as nil (a zero-maker venue is a real
    schedule, and feature 64 prices what its queue costs instead).
    Negative is refused because a fee that pays the trader is a rebate — a
    different instrument, with no field in §6.2's document — and a
    non-finite value is refused because it would propagate silently into
    every downstream metric dressed as a measurement.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number) or number < 0.0:
        return None
    return number


#: What is wrong with a rate, phrased for the two callers that can supply
#: one — the fill-input value and the configured schedule.  Spelled once so
#: the two validators below cannot drift into describing the same defect
#: two different ways.
_FEE_RULE = (
    "a fee is a non-negative finite number of basis points: a negative "
    "rate pays the trader, which is a rebate rather than the cost §6.2's "
    "document names, and a non-finite rate would propagate into every "
    "downstream metric dressed as a measurement (zero is legal — a venue "
    "whose fee is nil)"
)


def _fee_bps(value: object) -> float:
    """Return ``value`` as a fee rate for an :func:`apply_fee`, or refuse it.

    The *fill-input* half of the module's validation: a rate a caller handed
    to :func:`apply_fee` alongside a return.  The defect is in the value the
    caller built, so it is a
    :class:`~cost_model.errors.CostModelFillError`, the same error the
    sibling input values (a side, a return) raise.
    """
    number = _non_negative_bps(value)
    if number is None:
        raise CostModelFillError(
            f"{_FEE_RULE}; got {type(value).__name__} ({value!r})"
        )
    return number


def _configured_fee_bps(value: object) -> float:
    """Return ``value`` as a fee rate for a :class:`FeeSchedule`, or refuse the document.

    The *document* half of the module's validation, and the same rule as
    :func:`_fee_bps` under a different contract: a rate that arrived out of
    §6.2's parsed ``taker_bps``/``maker_bps`` is a defect of the *signed
    artifact*, so it is a
    :class:`~cost_model.errors.CostModelConfigError` — the error an operator
    fixing the document catches — exactly as the fill model's own
    constructor refusals are.
    """
    number = _non_negative_bps(value)
    if number is None:
        raise CostModelConfigError(
            f"the cost model's fee rate is unusable: {_FEE_RULE}; got "
            f"{type(value).__name__} ({value!r})"
        )
    return number


def _coerce_side(value: object) -> str:
    """Return ``value`` as one of :data:`TAKER`/:data:`MAKER`, or refuse it.

    The two spellings are accepted case-insensitively — ``"Taker"`` is the
    same side as ``"taker"`` — and nothing else is: a fee side is not a
    place to accept synonyms, because ``"buy"``/``"sell"`` name *order*
    directions and ``"bid"``/``"ask"`` name *book* sides, and quietly
    mapping any of those onto a fee side would let a caller state the wrong
    axis where they meant the liquidity role.  A taker consumes and a maker
    provides — the side says which, and the schedule reads the rate off it.
    """
    if not isinstance(value, str):
        raise CostModelFillError(
            f"a fee side must be {TAKER!r} or {MAKER!r}, got "
            f"{type(value).__name__} ({value!r})"
        )
    side = value.strip().lower()
    if side not in _SIDES:
        raise CostModelFillError(
            f"a fee side must be {TAKER!r} or {MAKER!r}, got {value!r}; a "
            f"taker crosses the spread and consumes liquidity, a maker "
            f"rests and provides it — 'buy'/'sell' name order directions "
            f"and 'bid'/'ask' name book sides, not a fee side"
        )
    return side


def _non_blank_venue(value: object) -> str:
    """Return ``value`` as the schedule's venue, or refuse it by name.

    The venue is the schedule's identity (see the module docstring's
    *"per venue"*), so a non-string or a blank one is not a schedule at all.
    The message mirrors :func:`cost_model.config._validated_component`,
    which refuses the same defect for the resolved pair: a venue is a name,
    and a whitespace-only name is a typo, not a venue.
    """
    if not isinstance(value, str):
        raise CostModelConfigError(
            f"the cost model's venue must be a string, got "
            f"{type(value).__name__} ({value!r})"
        )
    text = value.strip()
    if not text:
        raise CostModelConfigError(
            "the cost model's venue is blank; a fee schedule prices a "
            "non-empty venue"
        )
    return text


@dataclass(frozen=True)
class PostCostReturn:
    """One pre-cost return with its fee applied: the return, the fee, the side.

    Feature 61's charge as a value — the return before cost
    (:attr:`pre_cost_return`), the rate it was charged at
    (:attr:`fee_bps`) and the side that rate came from (:attr:`side`), from
    which the post-cost figure reads.  The cost is derived rather than
    stored, so the number a caller deducts and the rate that decided it
    cannot disagree, and a caller auditing a return can see which side's fee
    was taken off it.

    Attributes:
        pre_cost_return: The return before any fee — a fraction of the
            traded notional, in the units the fee is deducted from.
        fee_bps: The fee rate applied, in basis points — the side's rate
            from :class:`FeeSchedule`.  A non-negative finite real: ``10``
            is the shipped document's rate, and ``0.0`` is a legal value
            (a venue whose fee is nil) answered as a zero cost.
        side: The fee side the rate came from — :data:`TAKER` or
            :data:`MAKER`.  The side says which of the schedule's two rates
            was charged, so a post-cost return explains its own deduction.
    """

    pre_cost_return: float
    fee_bps: float
    side: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_side(self.side))
        object.__setattr__(self, "fee_bps", _fee_bps(self.fee_bps))
        if not isinstance(self.pre_cost_return, (int, float)) or isinstance(
            self.pre_cost_return, bool
        ):
            raise CostModelFillError(
                f"a post-cost return's pre_cost_return must be a real number, "
                f"got {type(self.pre_cost_return).__name__} "
                f"({self.pre_cost_return!r})"
            )
        if math.isnan(self.pre_cost_return) or math.isinf(self.pre_cost_return):
            raise CostModelFillError(
                f"a post-cost return's pre_cost_return must be finite, got "
                f"{self.pre_cost_return!r}: a non-finite return is a recording "
                f"error, not a thin market"
            )

    @property
    def fee_fraction(self) -> float:
        """The fee as a fraction of the notional — ``10 bps`` is ``0.001``.

        The form a caller deducts from a return: basis points are the unit
        the *document* and the fee schedule speak, and a fraction is the
        unit the arithmetic speaks, so both are readable off one value
        rather than converted by each caller.
        """
        return self.fee_bps / _BPS_PER_UNIT

    @property
    def post_cost_return(self) -> float:
        """The return after the fee — the feature's deliverable, per element.

        ``pre_cost_return − fee_fraction``: the fee is a cost of trading,
        paid on the notional that turned over regardless of which way the
        price moved, so it is subtracted from the return rather than scaled
        by it.  A winning return and a losing return pay the same fee, and
        the post-cost figure can fall below the pre-cost one by exactly the
        fee — no clamping, because a fee that exceeds a return is a real
        state (a small edge eaten whole by costs), not an error to hide.
        """
        return self.pre_cost_return - self.fee_fraction

    def summary(self) -> dict[str, object]:
        """The charge as a persistable mapping: the two returns, the fee, the side.

        The shape a caller logs or feature 79's cost schedule attaches to a
        trial record: what the return was, what it became, the rate and the
        side that took the difference off it — including both unit spellings
        of the fee, so the cost explains itself.  A view over the value,
        rebuilt on every call, so it can never be a stale copy of a frozen
        one.
        """
        return {
            "side": self.side,
            "fee_bps": self.fee_bps,
            "fee_fraction": self.fee_fraction,
            "pre_cost_return": self.pre_cost_return,
            "post_cost_return": self.post_cost_return,
        }


def apply_fee(
    pre_cost_return: float, fee_bps: float, side: str
) -> PostCostReturn:
    """Charge ``fee_bps`` on ``pre_cost_return`` for ``side`` and return the post-cost figure.

    The feature's sentence as a function on one element, and its layering
    made literal: the return and the rate arrive as values, and this
    subtracts the fee.  Delegates to :class:`PostCostReturn`, so the module
    function and the value are one implementation, not a facade over a twin
    — the same stance :func:`cost_model.queue_penalty.charge_queue_position_penalty`
    takes toward :class:`~cost_model.queue_penalty.QueuePenalty`.
    """
    return PostCostReturn(
        pre_cost_return=pre_cost_return, fee_bps=fee_bps, side=side
    )


@dataclass(frozen=True)
class FeeSchedule:
    """A venue's taker and maker fee schedule, resolved from the document.

    Feature 61's *"taker and maker fees in basis points per venue"* as a
    value — the venue it prices (:attr:`venue`) and the two rates it
    charges (:attr:`taker_bps`, :attr:`maker_bps`), with the side-selecting
    accessors a caller applies a return through.  The two rates are distinct
    inputs, so a taker fill and a maker fill are priced off the field each
    earned rather than a blended number the document never named::

        schedule = resolve_fee_schedule(read_cost_model_document(path)[0])
        post = schedule.apply([0.05, -0.02, 0.01], "taker")
        series = [r.post_cost_return for r in post]  # each reduced by 10 bps

    and an evaluator and a live engine holding the same schedule deduct the
    same fee from the same return the same way, which is the §6.2 invariant
    (``β₄`` penalizes divergence) made structural rather than aspirational.
    """

    venue: str
    taker_bps: float
    maker_bps: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _non_blank_venue(self.venue))
        object.__setattr__(self, "taker_bps", _configured_fee_bps(self.taker_bps))
        object.__setattr__(self, "maker_bps", _configured_fee_bps(self.maker_bps))

    def rate(self, side: str) -> float:
        """The basis points ``side`` pays — the taker rate or the maker rate.

        The one accessor a caller reaches for to price a fill: a taker fill
        names :data:`TAKER` and gets :attr:`taker_bps`, a maker fill names
        :data:`MAKER` and gets :attr:`maker_bps`.  A side it does not know
        is refused by :func:`_coerce_side`, so the rate a caller charges is
        always one the schedule actually carries.
        """
        return self.maker_bps if _coerce_side(side) == MAKER else self.taker_bps

    def fee_fraction(self, side: str) -> float:
        """The ``side`` rate as a fraction of the notional — :meth:`rate` over ten thousand.

        The form a caller deducts from a return, sparing it the unit
        conversion the fee schedule's bps would otherwise demand at every
        call site — the same reason :attr:`PostCostReturn.fee_fraction`
        spells the fraction beside the basis points.
        """
        return self.rate(side) / _BPS_PER_UNIT

    def apply(self, returns: Sequence[float], side: str) -> tuple[PostCostReturn, ...]:
        """Apply ``side``'s fee to a pre-cost return series, returning the post-cost one.

        Feature 61's *"returns a post-cost return series"* — each element
        of ``returns`` is charged the side's rate and comes back a
        :class:`PostCostReturn`, so the series in and the series out are the
        same length and each post-cost figure carries the rate and side that
        produced it.  A caller wanting the bare figures reads
        ``[r.post_cost_return for r in ...]``; a caller auditing the charge
        keeps the values whole.  The order is preserved — the fee does not
        reorder a series — and an empty series returns an empty tuple, which
        is the honest answer for a series with no returns to price.
        """
        coerced = _coerce_side(side)
        rate = self.rate(coerced)
        return tuple(
            PostCostReturn(pre_cost_return=r, fee_bps=rate, side=coerced)
            for r in returns
        )

    def summary(self) -> dict[str, object]:
        """The schedule as a persistable mapping: the venue and the two rates.

        The shape a caller logs or a later feature attaches to a trial
        record: whose schedule this is and what each side pays, in basis
        points and in fraction form so the cost explains itself.  A view
        over the value, rebuilt on every call, so it can never be a stale
        copy of a frozen one.
        """
        return {
            "venue": self.venue,
            "taker_bps": self.taker_bps,
            "maker_bps": self.maker_bps,
            "taker_fraction": self.taker_bps / _BPS_PER_UNIT,
            "maker_fraction": self.maker_bps / _BPS_PER_UNIT,
        }


def resolve_fee_schedule(model: Mapping[str, object] | None = None) -> FeeSchedule:
    """Resolve a venue's taker and maker fee schedule out of a parsed §6.2 document.

    ``model`` is the model mapping :func:`cost_model.config.read_cost_model_document`
    returns (the ``cost_model`` block), read through the one cached parse
    rather than a fresh re-read — the same single-parse seam the resolved
    identity, feature 60's hash and the fill models sit on, so the fee
    schedule a caller charges is the one the loaded document named.  ``None``
    reads the shipped default document.

    The §6.2 shape is demanded, not defaulted: a document with no ``fees``
    block, or with a ``taker_bps`` or ``maker_bps`` that is absent or not a
    non-negative finite real, is refused by name — a fee defaulted to zero
    would be the floored simulator `docs/alpha-engine-prd.md` §10 warns
    about, and a cost model that cannot price one side of a fill is not a
    cost model.  The venue is read from the block's own ``venue`` and
    travels with the schedule.  The section's ``discount_token`` field
    belongs to feature 62 — it is tolerated here and not read, because this
    resolver answers for the two plain rates only;
    :func:`cost_model.discount.resolve_fee_discount` is what reads it and
    reduces the rates this resolver returns.

    Raises:
        CostModelConfigError: For every document defect — the ``fees``
            section it names is absent or not a mapping, a rate that is not
            a non-negative finite real, or a missing/blank venue.  These are
            defects of the *document*, which is why they are config errors
            while a broken return input is a
            :class:`~cost_model.errors.CostModelFillError`.
    """
    if model is None:
        model, _origin = read_cost_model_document()

    if not isinstance(model, Mapping):
        raise CostModelConfigError(
            f"the parsed cost model is a {type(model).__name__}, not a "
            f"mapping: a fee schedule is resolved out of a {FEES_KEY!r} block "
            f"carrying {TAKER_BPS_KEY!r} and {MAKER_BPS_KEY!r}"
        )
    if FEES_KEY not in model:
        raise CostModelConfigError(
            f"the cost model document names no {FEES_KEY!r} block: §6.2's "
            f"fee schedule carries a taker rate and a maker rate, and a cost "
            f"model that cannot price one side of a fill is not a cost model"
        )
    fees = model[FEES_KEY]
    if not isinstance(fees, Mapping):
        raise CostModelConfigError(
            f"the cost model's {FEES_KEY!r} block is a "
            f"{type(fees).__name__}, not a mapping"
        )
    if TAKER_BPS_KEY not in fees:
        raise CostModelConfigError(
            f"the cost model's {FEES_KEY} block names no {TAKER_BPS_KEY}: a "
            f"taker order crosses the spread and pays a fee, and a document "
            f"that omits the taker rate has not named the behaviour — a cost "
            f"defaulted to zero is the floored simulator §6.2's zero-maker "
            f"case exists to prevent"
        )
    if MAKER_BPS_KEY not in fees:
        raise CostModelConfigError(
            f"the cost model's {FEES_KEY} block names no {MAKER_BPS_KEY}: a "
            f"maker order rests and provides liquidity, and a document that "
            f"omits the maker rate has not named the behaviour — a cost "
            f"defaulted to zero is the floored simulator §6.2's zero-maker "
            f"case exists to prevent"
        )
    if "venue" not in model:
        raise CostModelConfigError(
            f"the cost model document names no venue: a fee schedule is "
            f"priced per venue, and {FEES_KEY!r}'s rates are meaningless "
            f"apart from the venue they belong to"
        )
    return FeeSchedule(
        venue=_non_blank_venue(model["venue"]),
        taker_bps=_configured_fee_bps(fees[TAKER_BPS_KEY]),  # type: ignore[arg-type]
        maker_bps=_configured_fee_bps(fees[MAKER_BPS_KEY]),  # type: ignore[arg-type]
    )
