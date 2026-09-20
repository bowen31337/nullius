"""Feature 62's fee layer: the discount-token reduction on the fee schedule.

app_spec.xml, "Cost Model & Fill Simulation", feature 62: *System applies a
discount-token fee reduction when configured, which returns an effective 7.5
bps rate in place of 10 bps.*  docs/nullius-tech-architecture.md §6.2 carries
the field in the document itself, under the fee schedule:

.. code-block:: yaml

    fees:
      taker_bps: 10.0
      maker_bps: 10.0
      discount_token: BNB        # → 7.5 bps  (feature 62)

and `docs/alpha-engine-prd.md` §10 states the arithmetic that comment
abbreviates: *"Binance VIP0 spot: 0.1% maker/taker; 0.075% with BNB
deduction."*  ``0.1%`` is ``10`` bps, ``0.075%`` is ``7.5`` bps, and the
difference between them is the **reduction** this module applies.

The sentence has three separable claims, and this module owns all three:

* **applies a discount-token fee reduction** — the mechanism is a *rate
  substitution*, not a second charge.  Feature 61 resolved the schedule
  (:class:`~cost_model.fees.FeeSchedule`) and owns the subtraction that turns
  a pre-cost return into a post-cost one; this module hands that same
  subtraction a *different rate* and nothing else.  :meth:`FeeDiscount.reduce`
  returns a :class:`~cost_model.fees.FeeSchedule` whose rates are the reduced
  ones, so the post-cost series is produced by
  :meth:`~cost_model.fees.FeeSchedule.apply` — the very call an undiscounted
  series goes through — rather than by a second, discount-aware
  implementation of the fee arithmetic.  That is feature 69's promise and
  §6.2's ``β₄`` invariant (*"they must be the same code, not two
  implementations of the same document"*) made structural for the discount
  axis: there is no arithmetic here to drift from feature 61's, because there
  is no arithmetic here at all beyond one multiplication of the rate.
* **when configured** — the document's ``discount_token`` names the token an
  account holds to earn the reduction, and its *absence* is not a defect: a
  venue whose fees are paid in the quote currency simply has no token, the
  field is omitted, and the schedule's own rate stands unchanged
  (:attr:`FeeDiscount.configured` is ``False`` and
  :meth:`FeeDiscount.effective_bps` answers the rate it was given).  What *is*
  refused is a ``discount_token`` that names nothing — a blank string, or a
  number where a token name belongs — because that is a typo in a signed Z0
  artifact, not the absence of one.  The reduction itself is **not** a
  document field: §6.2's document names the *token* and writes the arithmetic
  only as a comment, so the fraction the token earns is the shared library's
  constant (:data:`DEFAULT_DISCOUNT_FRACTION`), stated once, the same way
  ``require_trade_through: true`` and ``exp_decay_vs_queue_depth`` name a
  behaviour the library implements rather than a number it reads.
* **which returns an effective 7.5 bps rate in place of 10 bps** — the
  deliverable is the *rate*: :meth:`FeeDiscount.effective_rate` answers, for a
  side, the basis points that side now pays — the schedule's ``10`` becomes
  ``7.5`` — and :meth:`FeeDiscount.reduction_bps` names the difference.  The
  rate is derived from the schedule's own field rather than substituted for a
  constant, so the shipped document's ``10 bps`` reaches ``7.5 bps`` by the
  same rule that would take any other venue's rate to its discounted value
  (``docs/alpha-engine-prd.md`` §10 states the reduction as a *percentage of
  the venue's fee*: 25% off), and a schedule that priced ``20`` bps is not
  silently repriced to the one venue's ``7.5``.

**No token whitelist, and no per-token table.**  The reduction is applied
whenever the field names a token, not only when it names ``BNB``: a document
that says ``discount_token: something_else`` has configured a fee reduction
this library applies, and inventing a token→rate table would be inventing a
behaviour the document does not carry.  The token name travels with the
discount (:attr:`FeeDiscount.token`) so a post-cost series can name which
token bought the reduction, the way the venue travels with the schedule and
the version travels with the venue.

**Both sides, or it is not this instrument.**  The reduction lands on the
taker rate *and* the maker rate, because §6.2's document carries one
``discount_token`` for one schedule and `docs/alpha-engine-prd.md` §10 states
it that way — *"0.1% maker/taker; 0.075% with BNB deduction"* — a single
deduction on the fee the venue charges, not a side-selective one.  A token
that discounted one side only would be a different instrument the document
has no field for, and the library does not carry it.

The module holds no state and no third-party import: the schedule arrives as
a value, the discount arrives as a value, and a reduced schedule returns as a
value.  Nothing is persisted — the feature's sentence asks for an effective
rate, not a row; feature 79's evaluator ``apply_costs`` step is the
persistence, and it reaches this reduction through the injected
:class:`~evaluator.CostSchedule` seam exactly as it reaches feature 61's
charge.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .config import read_cost_model_document
from .errors import CostModelConfigError, CostModelFillError
from .fees import (
    FEES_KEY,
    FeeSchedule,
    PostCostReturn,
    _coerce_side,
)

__all__ = [
    "DEFAULT_DISCOUNT_FRACTION",
    "DISCOUNT_TOKEN_KEY",
    "FeeDiscount",
    "discount_fee_schedule",
    "resolve_fee_discount",
]

#: The fee schedule's discount-token field (§6.2:
#: ``discount_token: BNB``) — the one field this module reads, and the field
#: whose *presence* is what "when configured" means.
DISCOUNT_TOKEN_KEY = "discount_token"

#: The reduction a configured discount token earns, as a fraction of the
#: rate: ``0.25`` — 25% off, which is §6.2's own arithmetic
#: (``discount_token: BNB  # → 7.5 bps``) and `docs/alpha-engine-prd.md`
#: §10's ("0.1% maker/taker; 0.075% with BNB deduction"): ``10`` bps less a
#: quarter of itself is ``7.5`` bps.  Spelled as the *reduction* rather than
#: as the retained ``0.75`` so the number a caller reads and the number the
#: summary reports are the same fact, and so the legal range (``0`` to ``1``)
#: is the range a reduction actually has — a reduction above ``1`` would pay
#: the trader, which is a rebate and not this document's field.
DEFAULT_DISCOUNT_FRACTION = 0.25


def _non_negative(value: object) -> float | None:
    """Return ``value`` as a non-negative finite real, or ``None``.

    The shared body of this module's numeric validators — see
    :func:`_fraction` and :func:`_bps` for why the *rule* is one function
    while the *message* is two.  Booleans are refused explicitly because
    ``isinstance(True, int)``: a reduction of ``True`` is a broken caller, not
    a total discount.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number) or number < 0.0:
        return None
    return number


def _fraction(value: object) -> float:
    """Return ``value`` as a reduction fraction in ``[0, 1]``, or refuse it.

    The reduction is never a document field — §6.2's document names the token
    and nothing else (see the module docstring) — so the only value this
    validator ever sees was built by a caller, which is why a bad one is a
    :class:`~cost_model.errors.CostModelFillError` rather than a document
    error.  ``0.0`` is legal (a token that earns nothing is a fact, not a
    defect) and ``1.0`` is legal (a fee the token waives entirely); above
    ``1.0`` is refused because a fee reduction larger than the fee *pays* the
    trader, which is a rebate — a different instrument with no field in §6.2's
    document — and a non-finite fraction is refused because it would turn
    every rate it touched into a non-finite cost dressed as a measurement.
    """
    number = _non_negative(value)
    if number is None or number > 1.0:
        raise CostModelFillError(
            f"a discount-token fee reduction is a fraction of the fee between "
            f"0 and 1: a reduction above 1 pays the trader, which is a rebate "
            f"rather than the reduction §6.2's document names, and a "
            f"non-finite one would propagate into every downstream metric "
            f"dressed as a measurement (0.0 is legal — a token that earns "
            f"nothing; 1.0 is legal — a fee the token waives); got "
            f"{type(value).__name__} ({value!r})"
        )
    return number


def _bps(value: object) -> float:
    """Return ``value`` as a rate in basis points, or refuse it.

    The reduction is applied *to* a rate, and the rate a caller hands over
    beside it is a caller's value: a :class:`~cost_model.fees.FeeSchedule`
    validates its own fields before this module ever sees them, so anything
    that reaches here unchecked is a rate built by hand.  Same rule and same
    error as :func:`cost_model.fees._fee_bps`, because it is the same kind of
    value.
    """
    number = _non_negative(value)
    if number is None:
        raise CostModelFillError(
            f"a fee rate is a non-negative finite number of basis points: a "
            f"negative rate pays the trader, which is a rebate rather than "
            f"the cost §6.2's document names, and a non-finite rate would "
            f"propagate into every downstream metric dressed as a "
            f"measurement (zero is legal — a venue whose fee is nil); got "
            f"{type(value).__name__} ({value!r})"
        )
    return number


def _schedule(value: object) -> FeeSchedule:
    """Return ``value`` as a fee schedule to reduce, or refuse it.

    The reduction is applied *to* feature 61's schedule, and the schedule a
    caller hands over is a caller's value: anything that is not one has no
    rates to reduce and would otherwise fail deep inside an attribute lookup,
    so it is refused here by name — the same stance
    :func:`cost_model.fees._coerce_side` takes toward a caller's side.  Shared
    by :meth:`FeeDiscount.reduce` and :meth:`FeeDiscount.effective_rate`, so a
    caller's mistake is described the same way whichever door it arrives
    through.
    """
    if not isinstance(value, FeeSchedule):
        raise CostModelFillError(
            f"a discount-token fee reduction is applied to a fee schedule, "
            f"got {type(value).__name__} ({value!r}): the reduction is a "
            f"change to feature 61's rates, not a charge of its own"
        )
    return value


def _token(value: object) -> str | None:
    """Return ``value`` as the configured token name, or ``None``, or refuse it.

    The *document* half of this module's validation, because the token is the
    one value that arrives out of §6.2's signed artifact.  ``None`` is not a
    defect and not a token: it is YAML's spelling of a field with no value
    (``discount_token:``), which is the same statement as omitting the field —
    no token is configured and the schedule's own rate stands (see the module
    docstring's *"when configured"*).  A non-string or a blank string *is* a
    defect — ``discount_token: ""`` names no token while looking like it
    might — and is refused by name, the same stance
    :func:`cost_model.config._validated_component` takes toward a blank
    version or venue.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise CostModelConfigError(
            f"the cost model's {DISCOUNT_TOKEN_KEY} is not a token name: "
            f"expected the token whose holding earns the fee reduction (or "
            f"no {DISCOUNT_TOKEN_KEY} at all for a venue with no discount "
            f"token), got {type(value).__name__} ({value!r})"
        )
    text = value.strip()
    if not text:
        raise CostModelConfigError(
            f"the cost model's {DISCOUNT_TOKEN_KEY} is blank; a discount "
            f"token is named by the text the document carries, and a blank "
            f"one configures no reduction while looking like it does"
        )
    return text


@dataclass(frozen=True)
class FeeDiscount:
    """A fee reduction earned by holding a token, configured or not.

    Feature 62's *"discount-token fee reduction when configured"* as a value —
    the token that earns it (:attr:`token`, ``None`` when the document names
    none) and the fraction it takes off the rate
    (:attr:`fraction`, the shared library's
    :data:`DEFAULT_DISCOUNT_FRACTION`).  The two things a caller does with it
    are the two halves of the sentence: ask what a rate becomes
    (:meth:`effective_bps`, :meth:`effective_rate`) and hand that rate to
    feature 61's charge (:meth:`reduce`, :meth:`apply`)::

        schedule = resolve_fee_schedule(read_cost_model_document(path)[0])
        discount = resolve_fee_discount(read_cost_model_document(path)[0])
        discount.effective_rate(schedule, TAKER)     # 7.5 — in place of 10
        series = discount.apply(schedule, [0.05, -0.02], TAKER)

    and the post-cost series that comes back is feature 61's own subtraction
    applied at the discounted rate, which is the §6.2 invariant (``β₄``
    penalizes divergence) made structural on the discount axis.

    Attributes:
        token: The token whose holding earns the reduction — the text §6.2's
            ``discount_token`` carries, as the document spells it, or ``None``
            when the document names no token (the *"when configured"* clause:
            no token, no reduction, and the rate is the schedule's own).
        fraction: The reduction as a fraction of the fee rate.  A real in
            ``[0, 1]``: ``0.25`` is the shipped reduction, ``0.0`` is legal (a
            token that earns nothing) and ``1.0`` is legal (a fee the token
            waives entirely).  A rate reduction above ``1`` is refused because
            it would pay the trader, and §6.2's document carries no rebate.

    The dataclass is frozen and validates in ``__post_init__``, so the
    invariant holds for every instance — one the resolver built and one a test
    or a tool built by hand alike.
    """

    token: str | None = None
    fraction: float = DEFAULT_DISCOUNT_FRACTION

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", _token(self.token))
        object.__setattr__(self, "fraction", _fraction(self.fraction))

    @property
    def configured(self) -> bool:
        """Whether a discount token is configured — ``True`` exactly when the document named one.

        The feature's *"when configured"* as a flag, and the switch every
        other method on this value reads: with no token there is no reduction
        to apply, and the schedule's own rate is returned unchanged rather
        than an operator's omission being quietly repriced to the one venue's
        discounted rate.
        """
        return self.token is not None

    @property
    def retained_fraction(self) -> float:
        """The fraction of the rate that survives the reduction — ``0.75`` at 25% off.

        The complement of :attr:`fraction`, derived rather than stored so the
        fraction applied and the fraction retained cannot disagree; it is the
        number an operator reads to check the arithmetic against the
        document's comment (``10 bps × 0.75 = 7.5 bps``).
        """
        return 1.0 - self.fraction

    def reduction_bps(self, bps: float) -> float:
        """The basis points ``bps`` loses to the token — ``2.5`` for ``10`` at 25% off.

        The *difference* the feature's sentence is about (*"7.5 bps in place
        of 10 bps"*), named beside :meth:`effective_bps` so a caller auditing
        a cost can see what the discount was worth without subtracting two
        numbers itself.  With no token configured nothing is taken off, which
        is the honest answer for a schedule whose owner holds no discount
        token.
        """
        rate = _bps(bps)
        return rate * self.fraction if self.configured else 0.0

    def effective_bps(self, bps: float) -> float:
        """The rate ``bps`` becomes under this discount — ``10`` becomes ``7.5``.

        Feature 62's deliverable, and the whole of *"returns an effective 7.5
        bps rate in place of 10 bps"*: the reduced rate for the shipped
        document, and (with no token configured) the rate it was handed.  The
        reduction is *subtracted* from the rate rather than the rate being
        replaced by a constant, so the answer is the venue's own fee less the
        token's share of it — see the module docstring for why ``7.5`` is not
        a value this library substitutes for every schedule.

        Derived from :meth:`reduction_bps`, so the amount taken off and the
        amount remaining are one subtraction apart by construction.
        """
        rate = _bps(bps)
        return rate - self.reduction_bps(rate)

    def effective_rate(self, schedule: FeeSchedule, side: str) -> float:
        """The basis points ``side`` pays on ``schedule`` once the token is applied.

        The rate half of the sentence read off a schedule a caller already
        holds: :data:`~cost_model.fees.TAKER` or
        :data:`~cost_model.fees.MAKER` selects the field, exactly as
        :meth:`~cost_model.fees.FeeSchedule.rate` does, and the discount is
        applied to it — so a taker fill and a maker fill are each priced at
        their own reduced rate rather than at a blended one.  The side is
        coerced by the same :func:`cost_model.fees._coerce_side` the schedule
        uses, so this cannot accept a side the schedule would refuse.  A
        ``schedule`` that is not one is refused by :func:`_schedule`.
        """
        return self.effective_bps(_schedule(schedule).rate(_coerce_side(side)))

    def reduce(self, schedule: FeeSchedule) -> FeeSchedule:
        """Return ``schedule`` with both of its rates reduced by this discount.

        The feature's *"applies a discount-token fee reduction"* as a value:
        a :class:`~cost_model.fees.FeeSchedule` with the same venue and the
        reduced rates, which feature 61's own
        :meth:`~cost_model.fees.FeeSchedule.apply` then charges exactly as it
        charges an undiscounted one.  That is deliberate: the discount is a
        change to one *input* of the fee charge, so the charge itself stays
        one implementation (§6.2's ``β₄``, feature 69) and an evaluator and a
        live engine that both hold this reduced schedule deduct the same
        discounted fee.

        Both sides are reduced — see the module docstring for why a
        side-selective reduction is a different instrument — and the venue is
        carried through unchanged, because the discount changes what the venue
        charges, not which venue's schedule this is.

        An unconfigured discount reduces nothing and returns a schedule equal
        to the one it was handed, so a caller can route every fill through one
        call without a branch of its own.
        """
        schedule = _schedule(schedule)
        return FeeSchedule(
            venue=schedule.venue,
            taker_bps=self.effective_bps(schedule.taker_bps),
            maker_bps=self.effective_bps(schedule.maker_bps),
        )

    def apply(
        self, schedule: FeeSchedule, returns: Sequence[float], side: str
    ) -> tuple[PostCostReturn, ...]:
        """Apply the reduced ``side`` rate to a pre-cost series, returning the post-cost one.

        The end of the feature's sentence: the series goes through
        :meth:`~cost_model.fees.FeeSchedule.apply` on the *reduced* schedule,
        so each element is charged the effective rate — ``7.5`` bps for the
        shipped document — by feature 61's subtraction and by nothing else.
        A caller can check that claim structurally: this returns exactly what
        ``self.reduce(schedule).apply(returns, side)`` returns, because that
        is what it calls.
        """
        return self.reduce(schedule).apply(returns, side)

    def summary(self) -> dict[str, object]:
        """The discount as a persistable mapping: the token, the fraction, what it earns.

        The shape a caller logs beside a post-cost series: which token bought
        the reduction (or ``None``, when none is configured), the fraction it
        takes off, the fraction retained, and whether it applied at all — so a
        discounted cost explains itself and a *missing* discount is visible as
        a fact rather than inferred from a rate.  A view over the value,
        rebuilt on every call, so it can never be a stale copy of a frozen
        one.
        """
        return {
            "token": self.token,
            "configured": self.configured,
            "fraction": self.fraction,
            "retained_fraction": self.retained_fraction,
        }


def discount_fee_schedule(
    schedule: FeeSchedule, discount: FeeDiscount
) -> FeeSchedule:
    """Return ``schedule`` with ``discount`` applied — the sentence as a function.

    Delegates to :meth:`FeeDiscount.reduce`, so the module function and the
    value are one implementation, not a facade over a twin — the same stance
    :func:`cost_model.queue_penalty.charge_queue_position_penalty` takes
    toward :class:`~cost_model.queue_penalty.QueuePenalty`.
    """
    return discount.reduce(schedule)


def resolve_fee_discount(model: Mapping[str, object] | None = None) -> FeeDiscount:
    """Resolve the discount-token reduction out of a parsed §6.2 document.

    ``model`` is the model mapping :func:`cost_model.config.read_cost_model_document`
    returns (the ``cost_model`` block), read through the one cached parse
    rather than a fresh re-read — the same single-parse seam the resolved
    identity, feature 60's hash and the fee schedule sit on, so the discount a
    caller applies is the one the loaded document named.  ``None`` reads the
    shipped default document.

    The section is demanded and the field is not: §6.2's document carries the
    fee schedule this reduction reduces, so a document with no ``fees`` block
    (or one that is not a mapping) is refused by name — a discount with no fee
    to reduce prices nothing.  Inside that block, ``discount_token`` is
    optional, because *"when configured"* is the feature's condition: a venue
    whose fees are paid in the quote currency has no token, and the resolver
    answers with an unconfigured :class:`FeeDiscount` whose effective rate is
    the schedule's own.  A ``discount_token`` that is present but names
    nothing — blank, or not a string — is refused by :func:`_token`, because
    that is a typo in a signed Z0 artifact rather than an absent field.  The
    block's other fields (``taker_bps``, ``maker_bps``) belong to feature 61 —
    they are tolerated here and not read, because this resolver answers for
    the token only.

    Raises:
        CostModelConfigError: For every document defect — the ``fees`` section
            it names is absent or not a mapping, or the token it carries is
            unusable.  These are defects of the *document*, which is why they
            are config errors while a broken reduction fraction is a
            :class:`~cost_model.errors.CostModelFillError`.
    """
    if model is None:
        model, _origin = read_cost_model_document()

    if not isinstance(model, Mapping):
        raise CostModelConfigError(
            f"the parsed cost model is a {type(model).__name__}, not a "
            f"mapping: a discount-token fee reduction is resolved out of a "
            f"{FEES_KEY!r} block"
        )
    if FEES_KEY not in model:
        raise CostModelConfigError(
            f"the cost model document names no {FEES_KEY!r} block: §6.2's "
            f"discount token reduces a venue's fee schedule, and a document "
            f"that names no schedule has no fee for a token to reduce"
        )
    fees = model[FEES_KEY]
    if not isinstance(fees, Mapping):
        raise CostModelConfigError(
            f"the cost model's {FEES_KEY!r} block is a "
            f"{type(fees).__name__}, not a mapping"
        )
    if DISCOUNT_TOKEN_KEY not in fees:
        # "when configured" — no field, no reduction, no error.
        return FeeDiscount(token=None)
    return FeeDiscount(token=_token(fees[DISCOUNT_TOKEN_KEY]))
