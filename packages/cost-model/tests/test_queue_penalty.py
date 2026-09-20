"""Feature 64 — the queue-position penalty charged on every passive fill.

app_spec.xml, "Cost Model & Fill Simulation", feature 64: *System charges a
queue-position penalty in basis points on every passive fill, so a zero-maker
venue still returns a nonzero cost.*  The sentence is a charge, a scope and a
consequence, and each can fail independently, so the tests take them one at a
time:

* **charges a queue-position penalty in basis points** — the cost is adverse
  selection, spoken in the unit §6.2's fee schedule already speaks: a filled
  order at ``1.5`` bps is charged ``1.5`` bps, which is ``0.00015`` as a
  fraction, checked against the definition rather than against a remembered
  constant.
* **on every passive fill** — the charge is the *consequence* of feature 63's
  gate, not a second gate.  A filled decision is charged; a decision the tape
  merely touched, or never reached, is charged *nothing*, because there was
  no fill to be adversely selected on.  This module never re-reads the tape,
  so the charge and the gate cannot disagree.
* **so a zero-maker venue still returns a nonzero cost** — the headline
  case, and the one `docs/alpha-engine-prd.md` §10 states the reason for:
  *"Going 0%-maker does not make trading free."*  The cost returned for a
  filled passive order is strictly positive at the shipped document's rate,
  and it is a *separate input* from the fee schedule — nothing this module
  reads can cancel it.

And the two refusals that keep the charge honest: a *missing*
``queue_position_penalty_bps`` is refused rather than defaulted to zero (a
silently floored cost is exactly the simulator §10 warns about), while a
*configured* ``0.0`` is a legal document value answered honestly as a zero
cost; and a negative or non-finite rate is refused, because a penalty that
pays the taker is a rebate rather than the cost the document names.

:mod:`cost_model.queue_penalty` owns the rate and the charge; the service
tests at the end pin that the composed component resolves the rate from the
one cached parse.
"""

from __future__ import annotations

import pytest

from cost_model import (
    CostModelConfigError,
    CostModelFillError,
    CostModelService,
    PassiveFillDecision,
    PassiveOrder,
    QueuePenalty,
    QueuePositionPenaltyModel,
    RecordedTape,
    Trade,
    charge_queue_position_penalty,
    fill_passive_order,
    resolve_queue_position_penalty_model,
)
from cost_model.config import read_cost_model_document
from cost_model.passive_fill import BUY, SELL
from cost_model.queue_penalty import (
    DEFAULT_PENALTY_BPS,
    QUEUE_POSITION_PENALTY_KEY,
)

#: The shipped §6.2 document's own rate, restated here so a test that reads
#: it off the resolver is checked against the document's text and not
#: against the resolver's default.
SHIPPED_PENALTY_BPS = 1.5


def _tape(*prices: float, quantity: float = 1.0) -> RecordedTape:
    """A tape of one-unit trades at the given prices, in order."""
    return RecordedTape([Trade(price=p, quantity=quantity) for p in prices])


# A buy resting on the bid at 100.0.
BUY_AT_100 = PassiveOrder(side=BUY, limit_price=100.0)

# A sell resting on the ask at 100.0.
SELL_AT_100 = PassiveOrder(side=SELL, limit_price=100.0)

# A buy the tape trades strictly through: feature 63's gate grants it.
FILLED_BUY = fill_passive_order(_tape(100.5, 99.5), BUY_AT_100)

# A buy the tape merely touches and retreats from: the gate refuses it, and
# the touch is kept as the audit hook.
TOUCHED_BUY = fill_passive_order(_tape(100.5, 100.0), BUY_AT_100)

# A buy the tape never reaches at all.
UNREACHED_BUY = fill_passive_order(_tape(100.5, 101.0), BUY_AT_100)


class TestThePenaltyIsChargedOnAFill:
    """The charge is what a filled passive order costs."""

    def test_a_filled_order_is_charged_the_rate(self) -> None:
        charge = charge_queue_position_penalty(FILLED_BUY, SHIPPED_PENALTY_BPS)
        assert charge.charged is True
        assert charge.cost_bps == SHIPPED_PENALTY_BPS

    def test_the_rate_is_spoken_in_basis_points(self) -> None:
        # 1.5 bps is 0.00015 as a fraction — computed here from the
        # definition of a basis point, not copied from the output.
        charge = charge_queue_position_penalty(FILLED_BUY, 1.5)
        assert charge.penalty_fraction == pytest.approx(1.5 / 10_000.0)
        assert charge.penalty_fraction == pytest.approx(0.00015)

    def test_the_charge_is_the_rate_the_caller_named(self) -> None:
        # A different rate is a different cost: the module prices the rate
        # it was handed rather than a constant of its own.
        assert charge_queue_position_penalty(FILLED_BUY, 3.0).cost_bps == 3.0
        assert charge_queue_position_penalty(FILLED_BUY, 0.25).cost_bps == 0.25

    def test_an_integer_rate_is_the_same_rate_as_a_float(self) -> None:
        # One spelling: 2 and 2.0 are the same number of basis points.
        assert charge_queue_position_penalty(
            FILLED_BUY, 2
        ) == charge_queue_position_penalty(FILLED_BUY, 2.0)

    def test_the_cost_fraction_matches_the_cost_in_bps(self) -> None:
        charge = charge_queue_position_penalty(FILLED_BUY, 2.0)
        assert charge.cost_fraction == pytest.approx(2.0 / 10_000.0)

    def test_the_charge_carries_the_fill_it_was_charged_on(self) -> None:
        # The evidence travels with the cost, so a caller auditing the
        # charge can take the decision apart and re-derive it.
        charge = charge_queue_position_penalty(FILLED_BUY, SHIPPED_PENALTY_BPS)
        assert charge.fill is FILLED_BUY
        assert charge.fill.limit_price == 100.0
        assert charge.fill.side == BUY
        assert charge.fill.fill_price == 100.0


class TestAnUnfilledOrderIsChargedNothing:
    """A fill that never happened cannot have been adversely selected on."""

    def test_a_touched_order_is_charged_nothing(self) -> None:
        # Feature 63 refused this fill — the tape reached the quote but did
        # not cross it — so there was no trade to be adversely selected on,
        # and the cost is exactly zero rather than the rate.
        assert TOUCHED_BUY.fills is False
        charge = charge_queue_position_penalty(TOUCHED_BUY, SHIPPED_PENALTY_BPS)
        assert charge.charged is False
        assert charge.cost_bps == 0.0
        assert charge.cost_fraction == 0.0

    def test_an_unreached_order_is_charged_nothing(self) -> None:
        charge = charge_queue_position_penalty(UNREACHED_BUY, SHIPPED_PENALTY_BPS)
        assert charge.cost_bps == 0.0

    def test_the_zero_charge_still_reports_the_rate_it_was_not_charged_at(self) -> None:
        # The rate is a property of the document, the cost is a property of
        # the fill: an unfilled order at 1.5 bps reports both, so a caller
        # can see *why* it was free rather than only that it was.
        charge = charge_queue_position_penalty(TOUCHED_BUY, SHIPPED_PENALTY_BPS)
        assert charge.penalty_bps == SHIPPED_PENALTY_BPS
        assert charge.is_zero_cost is True

    def test_a_fill_at_a_positive_rate_is_never_reported_as_zero_cost(self) -> None:
        # The audit hook the headline case rests on.
        assert charge_queue_position_penalty(
            FILLED_BUY, SHIPPED_PENALTY_BPS
        ).is_zero_cost is False


class TestAZeroMakerVenueStillReturnsANonzeroCost:
    """The feature's headline claim, from the alpha-engine PRD's own case."""

    def test_a_filled_passive_order_costs_more_than_nothing(self) -> None:
        model = resolve_queue_position_penalty_model()
        charge = model.charge(FILLED_BUY)
        assert charge.cost_bps > 0.0
        assert charge.cost_bps == SHIPPED_PENALTY_BPS

    def test_the_cost_does_not_read_the_fee_schedule(self) -> None:
        # A zero maker fee cannot cancel this charge: the two are separate
        # inputs, and the charge is computed from the fill's gate and the
        # document's penalty rate alone.  The document's maker fee is read
        # here only to state that the model never consults it — a model
        # whose cost changed when the fee did would be the second
        # implementation feature 69 rejects.
        model = resolve_queue_position_penalty_model()
        document, _origin = read_cost_model_document()
        assert document["fees"]["maker_bps"] == 10.0
        zero_maker = {
            "fees": {"maker_bps": 0.0},
            "fill_model": {
                "passive": {QUEUE_POSITION_PENALTY_KEY: SHIPPED_PENALTY_BPS}
            },
        }
        assert model.charge(FILLED_BUY).cost_bps == (
            resolve_queue_position_penalty_model(zero_maker)
            .charge(FILLED_BUY)
            .cost_bps
        )

    def test_a_zero_configured_rate_is_answered_honestly(self) -> None:
        # 0.0 is a legal document value — an operator may have measured a
        # venue's queue cost as nil — and the honest answer is a zero cost,
        # not a refusal.  This is the *configured* zero, as opposed to the
        # omitted field below.
        model = resolve_queue_position_penalty_model(
            {"fill_model": {"passive": {QUEUE_POSITION_PENALTY_KEY: 0.0}}}
        )
        assert model.penalty_bps == 0.0
        assert model.charge(FILLED_BUY).cost_bps == 0.0
        assert model.charge(FILLED_BUY).is_zero_cost is True


class TestTheChargeIsAHonestValue:
    """The record explains itself and cannot be edited into a different one."""

    def test_the_summary_carries_the_cost_the_rate_and_the_fill(self) -> None:
        charge = charge_queue_position_penalty(FILLED_BUY, SHIPPED_PENALTY_BPS)
        assert charge.summary() == {
            "penalty_bps": SHIPPED_PENALTY_BPS,
            "charged": True,
            "cost_bps": SHIPPED_PENALTY_BPS,
            "cost_fraction": SHIPPED_PENALTY_BPS / 10_000.0,
            "is_zero_cost": False,
            "fills": True,
            "side": BUY,
            "limit_price": 100.0,
            "fill_price": 100.0,
        }

    def test_the_summary_of_an_unfilled_order_reports_no_charge(self) -> None:
        summary = charge_queue_position_penalty(
            TOUCHED_BUY, SHIPPED_PENALTY_BPS
        ).summary()
        assert summary["charged"] is False
        assert summary["cost_bps"] == 0.0
        assert summary["fills"] is False
        assert summary["fill_price"] is None

    def test_the_summary_is_rebuilt_rather_than_cached(self) -> None:
        # A view over the value, never a stored copy of it.
        charge = charge_queue_position_penalty(FILLED_BUY, 1.5)
        assert charge.summary() == charge.summary()
        assert charge.summary() is not charge.summary()

    def test_the_charge_is_frozen(self) -> None:
        charge = QueuePenalty(penalty_bps=1.5, fill=FILLED_BUY)
        with pytest.raises(AttributeError):
            charge.penalty_bps = 9.0  # type: ignore[misc]

    def test_a_hand_built_charge_is_the_same_value_as_the_functions(self) -> None:
        # The record has one shape however it was built, the way the gate's
        # own decision does.
        assert QueuePenalty(penalty_bps=1.5, fill=FILLED_BUY) == (
            charge_queue_position_penalty(FILLED_BUY, 1.5)
        )

    def test_the_model_is_frozen(self) -> None:
        model = QueuePositionPenaltyModel()
        with pytest.raises(AttributeError):
            model.penalty_bps = 9.0  # type: ignore[misc]

    def test_the_charge_can_be_hashed_and_compared(self) -> None:
        assert charge_queue_position_penalty(FILLED_BUY, 1.5) == (
            charge_queue_position_penalty(FILLED_BUY, 1.5)
        )
        assert hash(charge_queue_position_penalty(FILLED_BUY, 1.5)) == hash(
            charge_queue_position_penalty(FILLED_BUY, 1.5)
        )


class TestTheInputContract:
    """A charge the model cannot honestly levy is refused, not smoothed over."""

    def test_a_negative_rate_is_refused(self) -> None:
        # A penalty that pays the taker is a rebate — a different
        # instrument, with no field in §6.2's document.
        with pytest.raises(CostModelFillError, match="rebate"):
            charge_queue_position_penalty(FILLED_BUY, -1.5)

    def test_a_non_finite_rate_is_refused(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(CostModelFillError):
                charge_queue_position_penalty(FILLED_BUY, value)

    def test_a_non_numeric_rate_is_refused(self) -> None:
        for value in ("1.5", None, [1.5]):
            with pytest.raises(CostModelFillError):
                charge_queue_position_penalty(FILLED_BUY, value)  # type: ignore[arg-type]

    def test_a_boolean_rate_is_refused(self) -> None:
        # isinstance(True, int) — a penalty of True is a broken caller, not
        # a one-basis-point charge.
        with pytest.raises(CostModelFillError):
            charge_queue_position_penalty(FILLED_BUY, True)

    def test_a_non_decision_fill_is_refused(self) -> None:
        # The penalty is a cost of feature 63's fill, not a second gate: a
        # caller handing over a bare tape or an order has mislayered it.
        for value in (_tape(99.5), BUY_AT_100, True, None):
            with pytest.raises(CostModelFillError, match="passive fill decision"):
                charge_queue_position_penalty(value, 1.5)  # type: ignore[arg-type]

    def test_a_hand_built_decision_is_the_same_shape_as_the_gates(self) -> None:
        # The record's own invariant: a decision cannot claim a fill with no
        # triggering trade, so a charge cannot be levied on an impossible one.
        with pytest.raises(CostModelFillError):
            PassiveFillDecision(side=BUY, limit_price=100.0, fills=True)


class TestResolveQueuePositionPenaltyModel:
    def test_the_shipped_default_resolves_to_the_documents_rate(self) -> None:
        # The default §6.2 document carries queue_position_penalty_bps: 1.5,
        # so the resolved model is the document's rate — read off the
        # document's own text rather than off the resolver's default.
        document, _origin = read_cost_model_document()
        configured = document["fill_model"]["passive"][QUEUE_POSITION_PENALTY_KEY]
        model = resolve_queue_position_penalty_model(document)
        assert isinstance(model, QueuePositionPenaltyModel)
        assert model.penalty_bps == configured == SHIPPED_PENALTY_BPS

    def test_the_default_argument_reads_the_shipped_document_too(self) -> None:
        assert resolve_queue_position_penalty_model().penalty_bps == SHIPPED_PENALTY_BPS

    def test_the_resolvers_default_is_the_shipped_documents_rate(self) -> None:
        # The hand-built default is the document's behaviour, not an
        # invented one: constructing a model with no argument prices §6.2.
        assert QueuePositionPenaltyModel().penalty_bps == SHIPPED_PENALTY_BPS
        assert DEFAULT_PENALTY_BPS == SHIPPED_PENALTY_BPS

    def test_the_model_charges_the_same_as_the_function(self) -> None:
        model = resolve_queue_position_penalty_model()
        assert model.charge(FILLED_BUY) == charge_queue_position_penalty(
            FILLED_BUY, SHIPPED_PENALTY_BPS
        )

    def test_a_document_without_a_fill_model_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_queue_position_penalty_model(
                {"version": "2026.09.1", "venue": "x"}
            )

    def test_a_document_without_a_passive_half_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_queue_position_penalty_model(
                {"fill_model": {"aggressive": {"walk_book": True}}}
            )

    def test_a_document_without_the_rate_is_refused(self) -> None:
        # Unlike feature 63's flag — whose siblings are tolerated — this
        # field is this feature's one input, and defaulting a cost to zero
        # silently is exactly the floored simulator §10 warns about.
        with pytest.raises(CostModelConfigError, match="floored"):
            resolve_queue_position_penalty_model(
                {"fill_model": {"passive": {"require_trade_through": True}}}
            )

    def test_a_document_whose_rate_is_malformed_is_refused_as_a_document(self) -> None:
        # A malformed rate in a signed Z0 artifact is the *document's*
        # defect: an operator fixing it catches config errors, not fill
        # errors.
        for value in ("1.5", None, -1.5, float("nan")):
            with pytest.raises(CostModelConfigError, match="unusable"):
                resolve_queue_position_penalty_model(
                    {"fill_model": {"passive": {QUEUE_POSITION_PENALTY_KEY: value}}}
                )

    def test_a_boolean_configured_rate_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="unusable"):
            resolve_queue_position_penalty_model(
                {"fill_model": {"passive": {QUEUE_POSITION_PENALTY_KEY: True}}}
            )

    def test_a_non_mapping_section_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="not a mapping"):
            resolve_queue_position_penalty_model({"fill_model": ["passive"]})
        with pytest.raises(CostModelConfigError, match="not a mapping"):
            resolve_queue_position_penalty_model(
                {"fill_model": {"passive": ["queue_position_penalty_bps"]}}
            )

    def test_a_non_mapping_document_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="not a"):
            resolve_queue_position_penalty_model("cost_model")  # type: ignore[arg-type]

    def test_the_passive_sections_other_fields_are_not_read(self) -> None:
        # require_trade_through (feature 63) and fill_probability_model
        # (feature 65) are tolerated but not required here — the resolver
        # answers for the penalty rate only.
        model = resolve_queue_position_penalty_model(
            {"fill_model": {"passive": {QUEUE_POSITION_PENALTY_KEY: 2.5}}}
        )
        assert model.penalty_bps == 2.5

    def test_a_hand_built_model_refuses_an_impossible_rate(self) -> None:
        for value in (-1.0, float("inf"), "1.5", True):
            with pytest.raises(CostModelConfigError):
                QueuePositionPenaltyModel(penalty_bps=value)  # type: ignore[arg-type]


class TestTheServiceResolvesThePenaltyModel:
    def test_the_service_exposes_the_model_from_the_default(self) -> None:
        # The composed service resolves the rate from the one cached parse
        # of the shipped §6.2 document, the same seam the passive gate, the
        # fill-probability decay and the aggressive walk sit on.
        service = CostModelService.from_env()
        model = service.queue_penalty()
        assert isinstance(model, QueuePositionPenaltyModel)
        assert model.penalty_bps == SHIPPED_PENALTY_BPS

    def test_the_service_model_matches_the_module_function(
        self, test_database_url: str
    ) -> None:
        service = CostModelService.from_env()
        assert service.queue_penalty().charge(FILLED_BUY) == (
            charge_queue_position_penalty(FILLED_BUY, SHIPPED_PENALTY_BPS)
        )

    def test_the_service_resolves_from_the_one_cached_parse(
        self, test_database_url: str
    ) -> None:
        # The four resolvers read the same cached parse, so the halves of
        # the fill model cannot disagree about which document was loaded.
        service = CostModelService.from_env()
        assert service.queue_penalty().penalty_bps == SHIPPED_PENALTY_BPS
        assert service.passive().require_trade_through is True
        assert service.fill_probability().fill_probability_model == (
            "exp_decay_vs_queue_depth"
        )
        assert service.aggressive().walk_book is True

    def test_the_service_reads_the_penalty_out_of_a_supplied_document(
        self, document
    ) -> None:
        # The rate is the document's, routed end to end: an operator's
        # artifact changes the charge, which is the whole point of the
        # field living in the Z0 document.
        path = document(
            'version: "2026.09.1"\n'
            "venue: binance_spot\n"
            "fill_model:\n"
            "  passive:\n"
            f"    {QUEUE_POSITION_PENALTY_KEY}: 2.5\n"
        )
        service = CostModelService.from_env()
        service.load(path)
        assert service.queue_penalty().penalty_bps == 2.5

    def test_a_sell_is_charged_by_the_same_model(self) -> None:
        # The penalty is charged per fill, not per side: the side is the
        # gate's business, and the charge reads the gate's answer.
        filled_sell = fill_passive_order(_tape(99.5, 100.5), SELL_AT_100)
        assert filled_sell.fills is True
        service = CostModelService.from_env()
        assert service.queue_penalty().charge(filled_sell).cost_bps == (
            SHIPPED_PENALTY_BPS
        )


class TestThePackageExportsTheFeature:
    def test_the_public_names_are_exported(self) -> None:
        import cost_model

        for name in (
            "QUEUE_POSITION_PENALTY_KEY",
            "QueuePenalty",
            "QueuePositionPenaltyModel",
            "charge_queue_position_penalty",
            "resolve_queue_position_penalty_model",
        ):
            assert name in cost_model.__all__
            assert hasattr(cost_model, name)

    def test_the_exported_charge_is_one_implementation(self) -> None:
        # The package-level name and the module-level one are the same
        # object, not a facade over a twin.
        import cost_model
        import cost_model.queue_penalty as module

        assert cost_model.charge_queue_position_penalty is (
            module.charge_queue_position_penalty
        )
