"""Feature 65's fill layer: the passive fill probability decayed against queue depth.

app_spec.xml, "Cost Model & Fill Simulation", feature 65: *System models
passive fill probability as exponential decay against queue depth, which
returns a fill fraction per rebalance.*
docs/nullius-tech-architecture.md §6.2 fixes the behaviour in the document
itself, under the fill model's passive half:

.. code-block:: yaml

    fill_model:
      passive:
        require_trade_through: true     # fill only if tape trades THROUGH the price
        queue_position_penalty_bps: 1.5
        fill_probability_model: exp_decay_vs_queue_depth

The sentence has four separable claims, and this module owns all four:

* **models passive fill probability** — the fill stops being a yes/no and
  becomes a fraction.  Feature 63 (:mod:`cost_model.passive_fill`) decides
  *whether* a resting order filled at all, from the tape; this feature
  answers the question that gate leaves open — *how much of it* filled
  inside one rebalance.  A backtest that sized every filled passive order
  at its whole quantity would report a fill rate the market never granted:
  a resting order is not a trade, it is a claim on tradable flow, and the
  claim is diluted by everyone who got to the price first.
* **as exponential decay against queue depth** — the dilution is the
  *queue ahead* of the order at its price level: the quantity that was
  already resting there when the order arrived.  The fraction decays
  exponentially in that depth, measured in units of the volume the level
  actually traded during the rebalance.  Exponential rather than linear on
  purpose: the first unit of queue ahead costs the most, each further unit
  costs proportionally less, and the fraction approaches zero
  asymptotically instead of hitting a cliff — a queue twice as deep halves
  the fill, which is what makes the half-life below a constant.  This is
  precisely §6.2's ``exp_decay_vs_queue_depth``, and nothing else is: see
  :func:`resolve_fill_probability_model`, which refuses any other model.
* **against queue depth** — the depth is the quantity resting *ahead* of
  the order, not the level's total size: an order that arrives at an empty
  price level is at the front of its queue and fills on the flow that
  reaches the level, while an identical order arriving behind a deep queue
  is filled only if that queue clears first.  A depth of zero is therefore
  a legal, meaningful value — the front of the queue — and not a missing
  input (see :class:`QueueObservation`).
* **which returns a fill fraction per rebalance** — the answer is a
  fraction of the order in ``[0, 1]``, and its horizon is *one* rebalance:
  the volume that traded at the level during that rebalance is the flow
  that can reach the order, so the fraction is what one rebalance's flow
  grants.  A caller pricing several rebalances re-observes the queue on
  each one — the caller recording the book knows the depth that actually
  stood there, and this module prices the depth it was handed rather than
  projecting an invented future one.

**The fraction is two honest facts, multiplied.**  :attr:`FillProbability.depth_decay`
is the exponential decay itself — ``exp(-queue_ahead / rebalance_volume)``,
the feature's headline claim, which is exactly ``1.0`` at the front of the
queue and ``1/e`` at one rebalance's worth of depth.
:attr:`FillProbability.participation_cap` is the volume bound —
``min(1, rebalance_volume / order_quantity)`` — because the tape traded a
finite quantity at that level and an order larger than it cannot fill more
than it: *you cannot fill more than the market printed at your price*,
which is the same refusal to invent a figure the tape did not earn that
feature 66's walk applies to the ladder.  For the ordinary case the cap
binds on nothing — an order smaller than the rebalance's volume has a cap
of exactly ``1.0`` and the returned fraction *is* the pure exponential,
bit-for-bit — and it binds only where ignoring it would report a fill the
recorded flow could not have produced.  The depth is priced once, by the
decay: the cap is the volume bound alone, so the queue ahead is not
charged for twice (that is feature 64's queue-position *penalty*, a cost
in basis points; this is a quantity).

**No other fill-probability model ships.**  §6.2's field names a model,
not a flag, so :func:`resolve_fill_probability_model` reads it and refuses
any document whose ``fill_probability_model`` is not exactly
``exp_decay_vs_queue_depth`` — a linear decay, a constant fill probability
or a "fill the whole order" default are each a different behaviour, and a
library that carried them behind a string would let research evaluation
and live execution drift apart through configuration, which is exactly the
divergence §6.2's ``β₄`` penalizes and feature 69 forbids.  The section's
other two fields (``require_trade_through``, ``queue_position_penalty_bps``)
belong to features 63 and 64 and are tolerated here and not read.

The module holds no state and no third-party import: the queue arrives as
a value, the fraction returns as a value, and nothing is persisted — the
feature's sentence asks for a fraction, not a row.  The queue arrives in
whatever quantity units the caller's recording carries (an evaluator
slicing a recorded lake, a live engine holding a venue feed), which is the
seam that lets §6.2's *"the same code, not two implementations of the same
document"* hold for the live path too.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .config import read_cost_model_document
from .errors import CostModelConfigError, CostModelFillError

__all__ = [
    "EXP_DECAY_MODEL",
    "FILL_MODEL_KEY",
    "FILL_PROBABILITY_KEY",
    "HALF_LIFE_REBALANCES",
    "PASSIVE_KEY",
    "FillProbability",
    "FillProbabilityModel",
    "QueueObservation",
    "passive_fill_fraction",
    "resolve_fill_probability_model",
]

#: The document's own key for the fill model, per §6.2's ``fill_model`` block.
FILL_MODEL_KEY = "fill_model"

#: The fill model's own key for the passive half (§6.2); the aggressive half
#: beside it belongs to feature 66 and is not read here.
PASSIVE_KEY = "passive"

#: The passive half's fill-probability field (§6.2:
#: ``fill_probability_model: exp_decay_vs_queue_depth``) — the one field this
#: module reads, and the one place §6.2 names a *model* rather than a flag.
FILL_PROBABILITY_KEY = "fill_probability_model"

#: §6.2's own name for the model this library implements.  Spelled once, so
#: the value the document carries and the value the resolver demands are the
#: same string and cannot drift into two spellings of one model.
EXP_DECAY_MODEL = "exp_decay_vs_queue_depth"

#: The queue depth, expressed in rebalances-worth of traded volume, at which
#: the fill fraction is exactly half — ``ln 2``, a constant with no dependence
#: on the level, the order or the venue.  That is what *exponential* buys: the
#: decay is measured in units of the flow that can clear the queue, so the
#: half-life is the same at every price and in every size.  Stated as a
#: constant because it is the falsifiable prediction of the model — a caller
#: measuring real fills can test it — and because a reader comparing the
#: halves of a decay profile should not have to re-derive it from ``exp``.
HALF_LIFE_REBALANCES = math.log(2.0)


def _positive_real(value: object, what: str) -> float:
    """Return ``value`` as a positive finite real number, or refuse it.

    The validator an order's quantity and the rebalance volume pass through,
    so a NaN, an infinity or a zero cannot be admitted by one constructor and
    refused by another.  Booleans are refused explicitly because
    ``isinstance(True, int)``: a quantity of ``True`` is a broken caller, not
    a one-unit order.  A non-positive value here is not a thin market — it is
    an order that does not exist or a level whose scale is undefined — and
    both are refused by name rather than smoothed into a fraction.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CostModelFillError(
            f"{what} must be a real number, got {type(value).__name__} "
            f"({value!r})"
        )
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise CostModelFillError(
            f"{what} must be finite, got {value!r}: a non-finite quantity is "
            f"a recording error, not a thin level"
        )
    if number <= 0.0:
        raise CostModelFillError(f"{what} must be positive, got {value!r}")
    return number


def _non_negative_real(value: object, what: str) -> float:
    """Return ``value`` as a non-negative finite real number, or refuse it.

    :func:`_positive_real` minus the strictness, for the one quantity in
    this module where zero is a *fact* rather than a defect: the queue ahead
    of the order.  An order that arrives at a price level where nothing
    rests ahead of it is at the front of its queue — the best position there
    is — so refusing a zero would refuse the case the model exists to price
    at its maximum.  Negative depth is still nonsense (a queue cannot be
    shorter than empty) and is refused, as are the non-finite values that
    would make the decay term meaningless.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CostModelFillError(
            f"{what} must be a real number, got {type(value).__name__} "
            f"({value!r})"
        )
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise CostModelFillError(
            f"{what} must be finite, got {value!r}: a non-finite queue depth "
            f"is a recording error, not a thin level"
        )
    if number < 0.0:
        raise CostModelFillError(
            f"{what} cannot be negative, got {value!r}: a queue is at its "
            f"shortest when it is empty, and an order at an empty level is "
            f"at the front of it"
        )
    return number


@dataclass(frozen=True)
class QueueObservation:
    """One rebalance's view of the queue a passive order rests in.

    The value the feature's sentence hands the decay — *"queue depth"* and
    the order it dilutes — carrying only what the decay needs: how much was
    already resting ahead of the order at its price, how large the order is,
    and how much the level traded during the rebalance.  All three are
    recorded facts about one rebalance, and all three are validated at
    construction, so an observation the decay cannot honestly price is
    refused by name at the boundary rather than turned into a fraction.

    Attributes:
        queue_ahead: The quantity resting at the order's price level *ahead*
            of it — the orders that got there first.  A non-negative finite
            real: zero is the front of the queue (the best position, and a
            legal one), and a negative depth is refused because a queue is
            at its shortest when it is empty.
        order_quantity: The size of the resting order whose fill is being
            fractioned.  Positive and finite — a zero-quantity order is not
            an order, and in the raw diff stream a zero quantity is a level
            *removal* (``nullius_ingest.book_diffs``) rather than liquidity.
        rebalance_volume: The quantity the recorded tape traded at this
            price level during one rebalance — the flow that can reach the
            order, and the unit the depth is measured in.  Non-negative: a
            level that traded nothing during the rebalance is a real state
            (see :attr:`FillProbability.depth_decay` for what the decay
            answers it), not a refusal.
    """

    queue_ahead: float
    order_quantity: float
    rebalance_volume: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "queue_ahead",
            _non_negative_real(self.queue_ahead, "a queue observation's queue_ahead"),
        )
        object.__setattr__(
            self,
            "order_quantity",
            _positive_real(
                self.order_quantity, "a queue observation's order_quantity"
            ),
        )
        object.__setattr__(
            self,
            "rebalance_volume",
            _non_negative_real(
                self.rebalance_volume, "a queue observation's rebalance_volume"
            ),
        )

    @property
    def queue_depth(self) -> float:
        """The queue depth the feature's sentence names — the quantity ahead of the order.

        A restatement of :attr:`queue_ahead` in the feature's own word, the
        way :attr:`~cost_model.passive_fill.PassiveFillDecision.traded_through`
        restates ``fills``: the sentence decays against *queue depth*, and a
        reader looking for that phrase should find it rather than have to
        learn that this module spells it ``queue_ahead``.
        """
        return self.queue_ahead

    @property
    def queue_rebalances(self) -> float | None:
        """The queue depth in units of the flow that can clear it, or ``None``.

        ``queue_ahead / rebalance_volume`` — how many rebalances-worth of the
        level's traded volume stand in front of the order, which is the
        exponent of the decay and the axis the half-life is stated on.  A
        depth of one means the queue ahead is exactly what one rebalance
        traded at the level; :data:`HALF_LIFE_REBALANCES` of them halves the
        fill.

        ``None`` when the level traded nothing during the rebalance: there is
        then no flow to measure the depth against and the depth is not *zero*
        rebalances-worth, it is *unmeasured* — the queue never clears,
        however long the order waits.  Reported as an absence rather than as
        an infinity so a caller logging the observation writes down a value
        its encoder can carry, and so the two cases (a shallow queue, an
        unmeasurable one) stay distinguishable.
        """
        if self.rebalance_volume <= 0.0:
            return None
        return self.queue_ahead / self.rebalance_volume


@dataclass(frozen=True)
class FillProbability:
    """The decay's answer: what fraction of the order one rebalance fills, and why.

    Feature 65's *"fill fraction per rebalance"* as a value — the recorded
    observation (the evidence), the two facts derived from it, and the
    fraction their product gives.  Everything is derived from
    :attr:`queue` rather than stored beside it, so the fraction and the
    queue that decided it cannot disagree, and a caller auditing a fill can
    take the observation apart and re-derive every term.

    Attributes:
        queue: The :class:`QueueObservation` this fraction was computed
            from — the depth ahead of the order, the order's size and the
            volume the level traded during the rebalance.
    """

    queue: QueueObservation

    def __post_init__(self) -> None:
        if not isinstance(self.queue, QueueObservation):
            raise CostModelFillError(
                f"a fill probability's queue is a queue observation, got "
                f"{type(self.queue).__name__} ({self.queue!r})"
            )

    @property
    def depth_decay(self) -> float:
        """The exponential decay the queue depth imposes — ``exp(-depth / volume)``.

        The feature's headline claim as a number: the fill fraction decays
        exponentially as the queue ahead of the order deepens, with the depth
        measured in units of the volume the level traded during the
        rebalance.  Exactly ``1.0`` at the front of the queue (no depth, no
        decay), ``1/e`` at one rebalance's worth of depth, and half at
        :data:`HALF_LIFE_REBALANCES` of them.

        The decay is asymptotic, so no finite depth makes the fraction
        exactly zero — only one so deep that the exponential underflows to
        ``0.0``, past roughly 745 rebalances-worth, which is a queue no
        horizon this model prices will clear.  A rebalance in which the level
        traded *nothing* is answered ``0.0`` rather than computed: the limit
        of ``exp(-d / V)`` as ``V → 0`` is zero for any real ``d`` (the
        queue is never reached because no flow arrives to clear it), and
        taking that limit rather than evaluating it is also the only honest
        way through the one case the limit does not cover — an empty queue at
        a level that traded nothing, where ``0/0`` has no value and *nothing
        traded, so nothing filled* is the answer the tape supports.  The same
        stance :func:`cost_model.passive_fill.fill_passive_order` takes
        toward an empty tape.
        """
        volume = self.queue.rebalance_volume
        if volume <= 0.0:
            return 0.0
        return math.exp(-self.queue.queue_ahead / volume)

    @property
    def participation_cap(self) -> float:
        """The most of the order one rebalance's traded volume can take — ``min(1, V / q)``.

        The volume bound, and the second of the fraction's two facts: the
        tape traded a finite quantity at this price level during the
        rebalance, and no order can fill more than the market printed at its
        price.  ``1.0`` whenever the level's volume covers the order whole —
        the ordinary case, where this term drops out and the fraction *is*
        the pure exponential — and ``volume / order_quantity`` for an order
        larger than the flow, which is the case a fill-everything model
        reports as full.

        The queue ahead is deliberately *not* subtracted from the volume
        here: that depth is priced once, by :attr:`depth_decay`, and charging
        it again in the cap would bill the same queue twice.  This term is
        the volume bound alone.
        """
        volume = self.queue.rebalance_volume
        quantity = self.queue.order_quantity
        if volume >= quantity:
            return 1.0
        return volume / quantity

    @property
    def fill_fraction(self) -> float:
        """The fill fraction per rebalance — the feature's deliverable.

        ``depth_decay × participation_cap``: the flow reaches the order only
        if the queue ahead of it clears, and even then only the volume that
        traded at the level can be filled.  In ``[0, 1]`` by construction —
        both factors are, and the product of two values in ``[0, 1]`` is —
        so the fraction can never claim more of the order than there is.  For
        an order no larger than the rebalance's volume the cap is exactly
        ``1.0`` and this is bit-for-bit :attr:`depth_decay`.

        Multiplied rather than alternated because they are the two
        independent constraints on one fill, not two models of it: the depth
        can decline a fill the volume would have allowed, and the volume can
        decline a fill the depth would have reached, and the honest answer in
        either state is the smaller one.  A fraction of exactly ``0.0`` is a
        legal answer, not a refusal — nothing traded at the level, or the
        queue ahead stands deeper than any flow this rebalance brought, and
        the order did not fill, which is the true answer.
        """
        return self.depth_decay * self.participation_cap

    @property
    def filled_quantity(self) -> float:
        """The quantity filled — the fraction applied to the order's size.

        What a caller charges costs against: a fill fraction is a proportion,
        and this is the same fact in the units the rest of §6.2 speaks —
        the quantity a fee schedule, a slippage figure or a queue-position
        penalty is applied to.  ``fill_fraction × order_quantity``, so it is
        derived from the evidence like everything else here and can never
        exceed the order.
        """
        return self.fill_fraction * self.queue.order_quantity

    def summary(self) -> dict[str, object]:
        """The fraction as a persistable mapping: the answer, its two facts, the evidence.

        The shape a caller logs or a later feature attaches to a trial
        record: the fraction and the quantity it comes to, the decay and the
        cap it decomposes into, and the queue that produced all four.  A view
        over the value, rebuilt on every call, so it can never be a stale
        copy of a frozen one.
        """
        return {
            "queue_depth": self.queue.queue_depth,
            "order_quantity": self.queue.order_quantity,
            "rebalance_volume": self.queue.rebalance_volume,
            "queue_rebalances": self.queue.queue_rebalances,
            "depth_decay": self.depth_decay,
            "participation_cap": self.participation_cap,
            "fill_fraction": self.fill_fraction,
            "filled_quantity": self.filled_quantity,
        }


def passive_fill_fraction(queue: QueueObservation) -> FillProbability:
    """Decay ``queue``'s depth and return the fraction of the order one rebalance fills.

    The feature's sentence as a function.  The exponential decay against the
    queue depth is :attr:`FillProbability.depth_decay`, the volume bound on
    the fill is :attr:`FillProbability.participation_cap`, and their product
    is :attr:`FillProbability.fill_fraction` — the fraction this returns,
    with both facts still readable beside it so a caller can see which of the
    two declined the fill rather than only how much it declined by.
    """
    return FillProbability(queue=queue)


@dataclass(frozen=True)
class FillProbabilityModel:
    """The passive half's fill-probability decay, resolved from the document.

    One model name, one method, and a refusal: the name is §6.2's
    ``fill_probability_model``, and it must be exactly
    :data:`EXP_DECAY_MODEL` — every other value names a different model of
    the same fill (a linear decay, a constant probability, a
    fill-everything assumption), and this library carries one, because a
    second model behind a string is how the two implementations feature 69
    forbids grow back.  The method is the decay, so a caller holding the
    resolved model holds the behaviour the document named::

        model = resolve_fill_probability_model(read_cost_model_document(path)[0])
        fraction = model.decide(QueueObservation(200.0, 100.0, 1_000.0)).fill_fraction

    and an evaluator and a live engine holding the same model fraction the
    same queue the same way, which is the §6.2 invariant (``β₄`` penalizes
    divergence) made structural rather than aspirational.
    """

    fill_probability_model: str = EXP_DECAY_MODEL

    def __post_init__(self) -> None:
        if self.fill_probability_model != EXP_DECAY_MODEL:
            raise CostModelConfigError(
                f"the passive fill-probability model this library implements "
                f"is {EXP_DECAY_MODEL!r} — exponential decay of the fill "
                f"fraction against the queue depth; "
                f"fill_probability_model={self.fill_probability_model!r} names "
                f"a different model of the same fill, and the shared library "
                f"does not carry a second one"
            )

    def decide(self, queue: QueueObservation) -> FillProbability:
        """Decay ``queue`` — the one passive fill-probability model there is.

        Delegates to :func:`passive_fill_fraction` so the model and the
        module function are one implementation, not a facade over a twin.
        """
        return passive_fill_fraction(queue)


def resolve_fill_probability_model(
    model: Mapping[str, object] | None = None,
) -> FillProbabilityModel:
    """Resolve the passive fill-probability model out of a parsed §6.2 document.

    ``model`` is the model mapping :func:`cost_model.config.read_cost_model_document`
    returns (the ``cost_model`` block), read through the one cached parse
    rather than a fresh re-read — the same single-parse seam the resolved
    identity, feature 60's hash and the fill gates sit on, so the decay a
    caller fractions with is the one the loaded document named.  ``None``
    reads the shipped default document.

    The §6.2 shape is demanded, not defaulted: a document with no
    ``fill_model``, no ``passive`` half, or no ``fill_probability_model`` is
    refused by name, and a value that is not exactly
    :data:`EXP_DECAY_MODEL` is refused by :class:`FillProbabilityModel`
    itself.  The section's other two fields (``require_trade_through``,
    ``queue_position_penalty_bps``) belong to features 63 and 64 — they are
    tolerated here and not read, because this resolver answers for the
    fill-probability model only.

    Raises:
        CostModelConfigError: For every document defect — the section it
            names is absent or not a mapping.  These are defects of the
            *document*, which is why they are config errors while a broken
            observation is a :class:`~cost_model.errors.CostModelFillError`.
    """
    if model is None:
        model, _origin = read_cost_model_document()

    if not isinstance(model, Mapping):
        raise CostModelConfigError(
            f"the parsed cost model is a {type(model).__name__}, not a "
            f"mapping: a fill-probability model is resolved out of a "
            f"{FILL_MODEL_KEY!r} section"
        )
    if FILL_MODEL_KEY not in model:
        raise CostModelConfigError(
            f"the cost model document names no {FILL_MODEL_KEY!r} section: "
            f"§6.2's fill model carries a passive half, and a cost model "
            f"that cannot fraction a passive order is not a cost model"
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
    if FILL_PROBABILITY_KEY not in passive:
        raise CostModelConfigError(
            f"the cost model's {FILL_MODEL_KEY}.{PASSIVE_KEY} section names "
            f"no {FILL_PROBABILITY_KEY}: the passive half's fill-probability "
            f"model decides how much of a resting order fills per rebalance, "
            f"and a document that omits it has not named the behaviour"
        )
    return FillProbabilityModel(  # type: ignore[arg-type]
        fill_probability_model=passive[FILL_PROBABILITY_KEY]
    )
