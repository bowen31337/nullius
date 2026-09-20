"""Feature 64's fill layer: the queue-position penalty charged on every passive fill.

app_spec.xml, "Cost Model & Fill Simulation", feature 64: *System charges a
queue-position penalty in basis points on every passive fill, so a zero-maker
venue still returns a nonzero cost.*
docs/nullius-tech-architecture.md §6.2 fixes the behaviour in the document
itself, under the fill model's passive half:

.. code-block:: yaml

    fill_model:
      passive:
        require_trade_through: true     # fill only if tape trades THROUGH the price
        queue_position_penalty_bps: 1.5
        fill_probability_model: exp_decay_vs_queue_depth

The sentence has three separable claims, and this module owns all three:

* **charges a queue-position penalty in basis points** — the cost is
  *adverse selection*, paid in the unit §6.2's fee schedule already speaks.
  A passive order that fills did so because the market came to it, and the
  market came to it because the order was on the wrong side of a move:
  someone with better information or better speed chose to trade against
  the resting quote.  That is the cost a maker pays instead of a fee, and
  it is charged in basis points of the fill for the same reason fees are —
  a caller adds the two without a unit conversion inventing a third
  spelling of "cost" (the same argument
  :attr:`cost_model.book_walk.BookWalk.slippage_bps` makes for the
  aggressive half).  The rate is the document's
  ``queue_position_penalty_bps`` and nothing else: no depth is consulted
  here, because the *depth* is priced by feature 65's decay as a quantity
  and charging the same queue twice would bill one fact at two rates
  (see :mod:`cost_model.fill_probability`, which states that split from
  the other side).
* **on every passive fill** — the charge is a *consequence* of the fill
  feature 63's gate granted, not a second gate.  A decision that filled is
  charged; a decision that did not fill is charged nothing, because there
  was no trade to be adversely selected on — an order the tape merely
  touched, or never reached, cost its owner nothing at all.  This module
  therefore never decides *whether* an order filled: it takes the
  :class:`~cost_model.passive_fill.PassiveFillDecision` as evidence and
  answers what that fill cost, which is exactly the layering feature 64's
  ``depends_on="63"`` states.  The penalty is flat rather than proportional
  to size, because the sentence charges it *per fill* and not per unit: a
  larger order fills less often (feature 65), so the penalty is already
  diluted by the fill probability rather than by a second size term here.
* **so a zero-maker venue still returns a nonzero cost** — the claim this
  feature exists to make true.  `docs/alpha-engine-prd.md` §10 states the
  failure it prevents: *"Going 0%-maker does not make trading free. It
  converts fee cost into adverse-selection cost on passive fills, which the
  evaluator must model explicitly (queue-position penalty, fill only when
  the tape trades through your price) or the simulator will lie."*  A venue
  that charges a zero maker fee is not a venue where a passive strategy
  trades free — it is a venue where the maker's cost has moved from the fee
  schedule into the queue.  Without this charge a backtest on a zero-maker
  venue reports a round trip that costs nothing, which is not a conservative
  approximation but a fabricated one: the number does not describe a market
  that exists.  So a filled passive order at any positive configured rate
  returns a strictly positive :attr:`QueuePenalty.cost_bps`, and the zero
  maker fee has no way to cancel it — the two are separate inputs and this
  module never reads the fee schedule.

**A zero rate is a legal document, and it is answered honestly.**  The
charge is not *demanded* to be positive: an operator may write
``queue_position_penalty_bps: 0.0`` for a venue whose queue cost they have
measured as negligible, and the honest answer to that document is a zero
cost rather than a refusal — refusing it would invent a policy the spec does
not state, the same stance
:class:`cost_model.passive_fill.PassiveFillModel` takes toward a
``require_trade_through`` it *does* refuse.  What is refused is a *missing*
field, because this field is this feature's one input and a cost defaulted
to zero silently is precisely the floored simulator §10 warns about; and a
negative rate, because a penalty that pays the taker is a rebate, a
different instrument the document has no field for.

**No other penalty ships.**  :func:`resolve_queue_position_penalty_model`
reads §6.2's ``queue_position_penalty_bps`` and refuses a document that does
not carry it — a defect *of the document*, which is why it is a
:class:`~cost_model.errors.CostModelConfigError` while a broken fill is a
:class:`~cost_model.errors.CostModelFillError`.  There is no depth-scaled
variant, no per-venue override table and no "waive the penalty for the
first fill" mode: each would be a different behaviour behind configuration,
and a library that carried them would let research evaluation and live
execution drift apart — exactly the divergence §6.2's ``β₄`` penalizes and
feature 69 forbids.  The section's other two fields (``require_trade_through``,
``fill_probability_model``) belong to features 63 and 65 and are tolerated
here and not read.

The module holds no state and no third-party import: the fill arrives as a
value, the charge returns as a value, and nothing is persisted — the
feature's sentence asks for a charge, not a row.  Feature 79's evaluator
``apply_costs`` step is the persistence, and it reaches this charge through
the injected :class:`~evaluator.CostSchedule` seam rather than by
re-implementing it, which is how §6.2's *"the same code, not two
implementations of the same document"* holds for the cost axis too.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .config import read_cost_model_document
from .errors import CostModelConfigError, CostModelFillError
from .passive_fill import FILL_MODEL_KEY, PASSIVE_KEY, PassiveFillDecision

__all__ = [
    "FILL_MODEL_KEY",
    "PASSIVE_KEY",
    "QUEUE_POSITION_PENALTY_KEY",
    "QueuePenalty",
    "QueuePositionPenaltyModel",
    "charge_queue_position_penalty",
    "resolve_queue_position_penalty_model",
]

#: The passive half's queue-position penalty field (§6.2:
#: ``queue_position_penalty_bps: 1.5``) — the one field this module reads,
#: and the one §6.2 spells in basis points.
QUEUE_POSITION_PENALTY_KEY = "queue_position_penalty_bps"

#: Basis points per unit of rate — the unit the penalty is spoken in,
#: spelled once so the fee schedule's bps, the aggressive walk's bps and
#: this charge's bps cannot drift into three different arithmetic
#: constants.  ``1 bps`` is ``1e-4`` as a fraction, so ``1.5 bps`` is
#: ``0.00015`` and a caller multiplying the fraction into a notional gets
#: the cost in the same units as the return it is deducted from.
_BPS_PER_UNIT = 10_000.0

#: The penalty rate the shipped §6.2 document carries, used as the default
#: for :class:`QueuePositionPenaltyModel` so a hand-built model prices the
#: document's behaviour rather than an invented one.  A model resolved from
#: a document always takes the document's value; this is only the fallback
#: for a caller constructing one with no argument, the same stance
#: :class:`~cost_model.passive_fill.PassiveFillModel` and
#: :class:`~cost_model.fill_probability.FillProbabilityModel` take.
DEFAULT_PENALTY_BPS = 1.5


def _non_negative_bps(value: object) -> float:
    """Return ``value`` as a non-negative finite penalty rate, or ``None``.

    The shared body of the module's two validators — see
    :func:`_penalty_bps` and :func:`_configured_penalty_bps` for why the
    *rule* is one function while the *error* it raises is two.  Booleans are
    refused explicitly because ``isinstance(True, int)``: a penalty of
    ``True`` is a broken caller, not a one-basis-point charge.

    Zero is accepted and is a *fact*, not a defect: an operator may
    genuinely measure a venue's queue cost as negligible (see the module
    docstring).  Negative is refused because a penalty that pays the taker
    is a rebate — a different instrument, with no field in §6.2's document —
    and a non-finite value is refused because it would propagate silently
    into every downstream metric dressed as a measurement.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number) or number < 0.0:
        return None
    return number


#: What is wrong with a rate, phrased for the two callers that can supply
#: one — the fill-input value and the configured model.  Spelled once so
#: the two validators below cannot drift into describing the same defect
#: two different ways.
_PENALTY_RULE = (
    "a queue-position penalty is a non-negative finite number of basis "
    "points: a negative rate pays the taker, which is a rebate rather than "
    "the cost §6.2's document names, and a non-finite rate would propagate "
    "into every downstream metric dressed as a measurement (zero is legal — "
    "a venue whose queue cost is nil)"
)


def _penalty_bps(value: object) -> float:
    """Return ``value`` as a penalty rate for a :class:`QueuePenalty`, or refuse it.

    The *fill-input* half of the module's validation: a rate a caller handed
    to :func:`charge_queue_position_penalty` alongside a fill.  The defect
    is in the value the caller built, so it is a
    :class:`~cost_model.errors.CostModelFillError`, the same error the
    sibling input values (:class:`~cost_model.passive_fill.PassiveOrder`,
    :class:`~cost_model.fill_probability.QueueObservation`) raise.
    """
    number = _non_negative_bps(value)
    if number is None:
        raise CostModelFillError(
            f"{_PENALTY_RULE}; got {type(value).__name__} ({value!r})"
        )
    return number


def _configured_penalty_bps(value: object) -> float:
    """Return ``value`` as a penalty rate for the model, or refuse the document.

    The *document* half of the module's validation, and the same rule as
    :func:`_penalty_bps` under a different contract: a rate that arrived
    out of §6.2's parsed ``queue_position_penalty_bps`` is a defect of the
    *signed artifact*, so it is a
    :class:`~cost_model.errors.CostModelConfigError` — the error an
    operator fixing the document catches — exactly as
    :class:`~cost_model.passive_fill.PassiveFillModel`'s and
    :class:`~cost_model.fill_probability.FillProbabilityModel`'s own
    constructor refusals are.
    """
    number = _non_negative_bps(value)
    if number is None:
        raise CostModelConfigError(
            f"the cost model's {QUEUE_POSITION_PENALTY_KEY} is unusable: "
            f"{_PENALTY_RULE}; got {type(value).__name__} ({value!r})"
        )
    return number


@dataclass(frozen=True)
class QueuePenalty:
    """The penalty a passive fill was charged: the rate, the fill, and the cost.

    Feature 64's sentence as a value — the fill it is charged *on*
    (:attr:`fill`, feature 63's own decision) and the rate it is charged
    *at* (:attr:`penalty_bps`), from which the cost reads.  The cost is
    derived rather than stored, so the number a caller deducts and the
    evidence that decided it cannot disagree, and a caller auditing a
    passive fill can see which of the two states it was in — filled and
    charged, or unfilled and free.

    Attributes:
        penalty_bps: The queue-position penalty rate in basis points, as
            §6.2's ``queue_position_penalty_bps`` carries it.  A
            non-negative finite real: ``1.5`` is the shipped document's
            rate, and ``0.0`` is a legal document value (see the module
            docstring) answered as a zero cost.
        fill: The passive fill decision the penalty is charged on — the
            gate, the limit price and the triggering trade.  The charge is
            the fill's consequence, so the evidence travels with it and
            :attr:`cost_bps` can be re-derived from this alone.
    """

    penalty_bps: float
    fill: PassiveFillDecision

    def __post_init__(self) -> None:
        object.__setattr__(self, "penalty_bps", _penalty_bps(self.penalty_bps))
        if not isinstance(self.fill, PassiveFillDecision):
            raise CostModelFillError(
                f"a queue-position penalty is charged on a passive fill "
                f"decision, got {type(self.fill).__name__} ({self.fill!r}): "
                f"the penalty is a cost of feature 63's fill, not a second "
                f"gate over the tape"
            )

    @property
    def penalty_fraction(self) -> float:
        """The rate as a fraction of the fill — ``1.5 bps`` is ``0.00015``.

        The form a caller multiplies into a notional or a return series:
        basis points are the unit the *document* and the fee schedule speak,
        and a fraction is the unit the arithmetic speaks, so both are
        readable off one value rather than converted by each caller.
        """
        return self.penalty_bps / _BPS_PER_UNIT

    @property
    def charged(self) -> bool:
        """Whether the penalty was charged — ``True`` exactly when the order filled.

        The feature's *"on every passive fill"* as a flag.  Restated from
        the fill's own gate rather than stored beside it, so a caller
        logging a cost cannot record a charge for an order the tape never
        filled.
        """
        return self.fill.fills

    @property
    def cost_bps(self) -> float:
        """The penalty actually charged, in basis points — the rate, or zero.

        Feature 64's deliverable, and the number that makes the feature's
        second clause true: :attr:`penalty_bps` when the order filled, and
        exactly ``0.0`` when it did not, because a fill that never happened
        cannot have been adversely selected.  For a filled order at the
        shipped ``1.5`` bps this is ``1.5`` — *nonzero* — no matter what the
        venue charges a maker, which is the whole of *"so a zero-maker venue
        still returns a nonzero cost"*.
        """
        return self.penalty_bps if self.fill.fills else 0.0

    @property
    def cost_fraction(self) -> float:
        """The charge as a fraction — :attr:`cost_bps` over ten thousand.

        The same fact in the units a return series is denominated in, so a
        caller deducts the queue cost and a fee with one subtraction rather
        than converting one of them first.
        """
        return self.cost_bps / _BPS_PER_UNIT

    @property
    def is_zero_cost(self) -> bool:
        """Whether this passive fill cost nothing — an unfilled order, or a zero rate.

        The audit hook for the feature's headline case: a *filled* order at
        a positive rate is never zero-cost, and if a caller ever reads
        ``is_zero_cost`` on one, the charge they are about to skip is the
        adverse selection §10 says a zero-maker venue still carries.
        """
        return self.cost_bps == 0.0

    def summary(self) -> dict[str, object]:
        """The charge as a persistable mapping: the cost, the rate, and the fill.

        The shape a caller logs or feature 79's cost schedule attaches to a
        trial record: what the fill cost in both units, whether it was
        charged at all, and the decision that decided it — including the
        gate and the quoted price, so the cost explains itself.  A view over
        the value, rebuilt on every call, so it can never be a stale copy of
        a frozen one.
        """
        return {
            "penalty_bps": self.penalty_bps,
            "charged": self.charged,
            "cost_bps": self.cost_bps,
            "cost_fraction": self.cost_fraction,
            "is_zero_cost": self.is_zero_cost,
            "fills": self.fill.fills,
            "side": self.fill.side,
            "limit_price": self.fill.limit_price,
            "fill_price": self.fill.fill_price,
        }


def charge_queue_position_penalty(
    fill: PassiveFillDecision, penalty_bps: float
) -> QueuePenalty:
    """Charge ``penalty_bps`` on ``fill`` and return what the passive fill cost.

    The feature's sentence as a function, and its layering made literal: the
    fill arrives already decided by feature 63's gate, and this charges it.
    A filled decision is charged the rate; a decision that merely touched or
    never reached the quote is charged nothing, because there was no fill
    for the penalty to be charged on.

    The function does not read the tape and does not re-gate the order — it
    cannot, since it is handed a decision and not the trades behind it — so
    there is no way for this charge and the gate to disagree about whether
    the order filled.
    """
    return QueuePenalty(penalty_bps=penalty_bps, fill=fill)


@dataclass(frozen=True)
class QueuePositionPenaltyModel:
    """The passive half's queue-position penalty, resolved from the document.

    One rate, one method, and a refusal to invent the rate: the rate is
    §6.2's ``queue_position_penalty_bps``, and the method charges it on a
    fill, so a caller holding the resolved model holds the behaviour the
    document named::

        model = resolve_queue_position_penalty_model(read_cost_model_document(path)[0])
        decision = model_fill.decide(RecordedTape([Trade(99.0, 5.0)]), PassiveOrder("buy", 100.0))
        cost_bps = model.charge(decision).cost_bps

    and an evaluator and a live engine holding the same model charge the
    same fill the same way, which is the §6.2 invariant (``β₄`` penalizes
    divergence) made structural rather than aspirational.
    """

    penalty_bps: float = DEFAULT_PENALTY_BPS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "penalty_bps", _configured_penalty_bps(self.penalty_bps)
        )

    def charge(self, fill: PassiveFillDecision) -> QueuePenalty:
        """Charge this model's rate on ``fill`` — the one queue-position penalty there is.

        Delegates to :func:`charge_queue_position_penalty` so the model and
        the module function are one implementation, not a facade over a twin.
        """
        return charge_queue_position_penalty(fill, self.penalty_bps)


def resolve_queue_position_penalty_model(
    model: Mapping[str, object] | None = None,
) -> QueuePositionPenaltyModel:
    """Resolve the passive queue-position penalty out of a parsed §6.2 document.

    ``model`` is the model mapping :func:`cost_model.config.read_cost_model_document`
    returns (the ``cost_model`` block), read through the one cached parse
    rather than a fresh re-read — the same single-parse seam the resolved
    identity, feature 60's hash and the fill gates sit on, so the rate a
    caller charges is the one the loaded document named.  ``None`` reads the
    shipped default document.

    The §6.2 shape is demanded, not defaulted: a document with no
    ``fill_model``, no ``passive`` half, or no
    ``queue_position_penalty_bps`` is refused by name — a cost defaulted to
    zero would be the floored simulator `docs/alpha-engine-prd.md` §10 warns
    about — and a value that is not a non-negative finite real is refused by
    :class:`QueuePositionPenaltyModel` itself, in the *document's* own
    vocabulary (:class:`~cost_model.errors.CostModelConfigError`), because a
    malformed rate in a signed Z0 artifact is an operator's problem and not
    a caller's.  Zero *is* accepted: a document that says a venue's queue
    cost is nil is answered honestly rather than refused.  The section's
    other two fields
    (``require_trade_through``, ``fill_probability_model``) belong to
    features 63 and 65 — they are tolerated here and not read, because this
    resolver answers for the penalty rate only.

    Raises:
        CostModelConfigError: For every document defect — the section it
            names is absent or not a mapping.  These are defects of the
            *document*, which is why they are config errors while a broken
            fill is a :class:`~cost_model.errors.CostModelFillError`.
    """
    if model is None:
        model, _origin = read_cost_model_document()

    if not isinstance(model, Mapping):
        raise CostModelConfigError(
            f"the parsed cost model is a {type(model).__name__}, not a "
            f"mapping: a queue-position penalty is resolved out of a "
            f"{FILL_MODEL_KEY!r} section"
        )
    if FILL_MODEL_KEY not in model:
        raise CostModelConfigError(
            f"the cost model document names no {FILL_MODEL_KEY!r} section: "
            f"§6.2's fill model carries a passive half, and a cost model "
            f"that cannot charge a passive fill is not a cost model"
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
    if QUEUE_POSITION_PENALTY_KEY not in passive:
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY}.{PASSIVE_KEY} section names "
            f"no {QUEUE_POSITION_PENALTY_KEY}: the passive half's "
            f"queue-position penalty is what a passive fill costs beyond "
            f"its fee, and a document that omits it has not named the "
            f"behaviour — a cost defaulted to zero is the floored simulator "
            f"§6.2's zero-maker case exists to prevent"
        )
    return QueuePositionPenaltyModel(
        penalty_bps=passive[QUEUE_POSITION_PENALTY_KEY]  # type: ignore[arg-type]
    )
