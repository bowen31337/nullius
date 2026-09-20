"""Feature 65 — the passive fill fraction decayed against queue depth.

app_spec.xml, "Cost Model & Fill Simulation", feature 65: *System models
passive fill probability as exponential decay against queue depth, which
returns a fill fraction per rebalance.*  The sentence is a model, a
mechanism, a quantity and a horizon, and each can fail independently, so
the tests take them one at a time:

* **models passive fill probability** — the answer is a fraction, not a yes
  or no: the fill feature 63's gate grants is *diluted* here by the queue
  the order rests behind, and the fraction never claims more of the order
  than there is.
* **as exponential decay** — the decay is ``exp(-depth / volume)``: exactly
  ``1.0`` at the front of the queue, exactly ``1/e`` at one rebalance's
  worth of depth, half at ``ln 2`` of them, and multiplicative across
  additions to the queue.  A linear decay would miss every one of those.
* **against queue depth** — the depth is the quantity resting *ahead* of
  the order, and zero is the front of the queue rather than a missing
  input.  The order's own size and the level's traded volume enter as the
  volume bound, never as a second price on the same queue.
* **which returns a fill fraction per rebalance** — the horizon is one
  rebalance's traded volume at the level, and a level that traded nothing
  filled nothing, rather than an infinity or a division error.

And the one refusal that keeps the model honest: a document whose
``fill_probability_model`` is not §6.2's ``exp_decay_vs_queue_depth`` is
refused rather than fallen back from — the field names a model, and the
library does not carry a second one.

:mod:`cost_model.fill_probability` owns the decay and its values; the
service tests at the end pin that the composed component resolves the
model from the one cached parse.
"""

from __future__ import annotations

import math

import pytest
from cost_model import (
    CostModelConfigError,
    CostModelFillError,
    CostModelService,
    FillProbability,
    FillProbabilityModel,
    QueueObservation,
    passive_fill_fraction,
    resolve_fill_probability_model,
)
from cost_model.config import read_cost_model_document
from cost_model.fill_probability import (
    EXP_DECAY_MODEL,
    HALF_LIFE_REBALANCES,
)

# An order of 100 units resting behind 100 units of queue, at a level that
# traded 500 units during the rebalance: a deep-ish queue against generous
# flow, the ordinary middle of the model's range.
MIDDLE = QueueObservation(queue_ahead=100.0, order_quantity=100.0, rebalance_volume=500.0)


class TestTheDecayIsExponential:
    def test_the_front_of_the_queue_fills_on_the_decay_alone(self) -> None:
        # No depth ahead: the exponential is exactly 1.0, so the decay
        # declines nothing and the fraction is the volume bound alone.
        probability = passive_fill_fraction(
            QueueObservation(queue_ahead=0.0, order_quantity=100.0, rebalance_volume=500.0)
        )
        assert probability.depth_decay == 1.0

    def test_the_decay_is_exp_of_minus_depth_over_volume(self) -> None:
        # The headline formula, checked against math.exp directly rather than
        # against a remembered constant.
        probability = passive_fill_fraction(MIDDLE)
        assert probability.depth_decay == math.exp(-100.0 / 500.0)

    def test_one_rebalances_worth_of_depth_decays_to_one_over_e(self) -> None:
        # Depth equal to the volume that can clear it: the decay is 1/e,
        # the model's characteristic point, and the fraction is a shade
        # under 0.37.
        probability = passive_fill_fraction(
            QueueObservation(queue_ahead=500.0, order_quantity=100.0, rebalance_volume=500.0)
        )
        assert probability.depth_decay == pytest.approx(1.0 / math.e)
        assert probability.fill_fraction == pytest.approx(1.0 / math.e)

    def test_the_half_life_is_ln_two_rebalances(self) -> None:
        # How exponential the decay is, stated as its falsifiable
        # prediction: at ln 2 rebalances-worth of depth the fraction is
        # exactly half.  A linear decay would halve at a quarter of that
        # and would never reach the asymptote below.
        depth = HALF_LIFE_REBALANCES * 500.0
        probability = passive_fill_fraction(
            QueueObservation(queue_ahead=depth, order_quantity=100.0, rebalance_volume=500.0)
        )
        assert probability.depth_decay == pytest.approx(0.5)

    def test_each_additional_rebalance_of_queue_multiplies_the_decay(self) -> None:
        # The defining property of exponential decay, and the one a linear
        # model gets wrong: adding the same depth again *multiplies* the
        # fraction by a constant rather than subtracting a constant.
        one = passive_fill_fraction(
            QueueObservation(queue_ahead=200.0, order_quantity=100.0, rebalance_volume=500.0)
        ).depth_decay
        two = passive_fill_fraction(
            QueueObservation(queue_ahead=400.0, order_quantity=100.0, rebalance_volume=500.0)
        ).depth_decay
        three = passive_fill_fraction(
            QueueObservation(queue_ahead=600.0, order_quantity=100.0, rebalance_volume=500.0)
        ).depth_decay
        assert two == pytest.approx(one * one)
        assert three == pytest.approx(one * one * one)

    def test_a_deeper_queue_always_fills_less(self) -> None:
        # Monotone in the depth: the queue ahead never helps the order.
        fractions = [
            passive_fill_fraction(
                QueueObservation(
                    queue_ahead=depth, order_quantity=100.0, rebalance_volume=500.0
                )
            ).depth_decay
            for depth in (0.0, 50.0, 100.0, 250.0, 1_000.0)
        ]
        assert fractions == sorted(fractions, reverse=True)
        assert len(set(fractions)) == len(fractions)

    def test_a_very_deep_queue_decays_to_zero_without_refusing(self) -> None:
        # The asymptote: no finite depth makes the fraction exactly zero,
        # but a queue past the exponential's underflow does, and that is an
        # honest *did not fill* rather than a refusal.
        probability = passive_fill_fraction(
            QueueObservation(
                queue_ahead=10_000.0, order_quantity=100.0, rebalance_volume=1.0
            )
        )
        assert probability.depth_decay == 0.0
        assert probability.fill_fraction == 0.0
        assert probability.filled_quantity == 0.0


class TestTheVolumeBoundsTheFill:
    def test_an_order_smaller_than_the_volume_is_the_pure_decay(self) -> None:
        # The ordinary case: the cap binds on nothing, and the fraction is
        # bit-for-bit the exponential — no second term leaking into the
        # headline number.
        probability = passive_fill_fraction(
            QueueObservation(queue_ahead=100.0, order_quantity=10.0, rebalance_volume=500.0)
        )
        assert probability.participation_cap == 1.0
        assert probability.fill_fraction == probability.depth_decay

    def test_an_order_exactly_the_volume_is_also_uncapped(self) -> None:
        probability = passive_fill_fraction(
            QueueObservation(queue_ahead=100.0, order_quantity=500.0, rebalance_volume=500.0)
        )
        assert probability.participation_cap == 1.0
        assert probability.fill_fraction == probability.depth_decay

    def test_an_order_larger_than_the_volume_cannot_fill_more_than_it(self) -> None:
        # You cannot fill more than the market printed at your price: an
        # order ten times the rebalance's volume fills at most a tenth of
        # itself, however shallow the queue.
        probability = passive_fill_fraction(
            QueueObservation(
                queue_ahead=0.0, order_quantity=5_000.0, rebalance_volume=500.0
            )
        )
        assert probability.participation_cap == 0.1
        assert probability.fill_fraction == 0.1
        assert probability.filled_quantity == 500.0

    def test_the_cap_and_the_decay_both_apply(self) -> None:
        # Two independent constraints on one fill: the queue declines it and
        # the volume declines it, and the answer is the smaller of the two
        # — which is their product, not either one alone.
        probability = passive_fill_fraction(
            QueueObservation(
                queue_ahead=500.0, order_quantity=5_000.0, rebalance_volume=500.0
            )
        )
        assert probability.depth_decay == pytest.approx(1.0 / math.e)
        assert probability.participation_cap == 0.1
        assert probability.fill_fraction == pytest.approx((1.0 / math.e) * 0.1)

    def test_the_queue_ahead_is_not_charged_twice(self) -> None:
        # The volume bound is the order's size against the traded volume
        # alone; the queue ahead is priced once, by the decay.  Subtracting
        # the depth from the volume as well would bill the same queue twice
        # and understate every fill behind a deep queue.
        probability = passive_fill_fraction(
            QueueObservation(queue_ahead=400.0, order_quantity=100.0, rebalance_volume=500.0)
        )
        assert probability.participation_cap == 1.0


class TestTheFractionIsAFraction:
    def test_the_fraction_is_the_product_of_its_two_facts(self) -> None:
        probability = passive_fill_fraction(MIDDLE)
        assert probability.fill_fraction == (
            probability.depth_decay * probability.participation_cap
        )

    @pytest.mark.parametrize(
        "queue_ahead, order_quantity, rebalance_volume",
        [
            (0.0, 1.0, 1.0),
            (100.0, 100.0, 500.0),
            (500.0, 5_000.0, 500.0),
            (10_000.0, 1.0, 1.0),
            (1e-9, 1e9, 1e-9),
        ],
    )
    def test_the_fraction_never_leaves_the_unit_interval(
        self, queue_ahead: float, order_quantity: float, rebalance_volume: float
    ) -> None:
        # A fill fraction that could exceed 1.0 would be a model claiming
        # more of the order than exists; the bounds are structural.
        probability = passive_fill_fraction(
            QueueObservation(
                queue_ahead=queue_ahead,
                order_quantity=order_quantity,
                rebalance_volume=rebalance_volume,
            )
        )
        assert 0.0 <= probability.fill_fraction <= 1.0
        assert 0.0 <= probability.filled_quantity <= probability.queue.order_quantity

    def test_the_filled_quantity_is_the_fraction_applied_to_the_order(self) -> None:
        probability = passive_fill_fraction(MIDDLE)
        assert probability.filled_quantity == (
            probability.fill_fraction * MIDDLE.order_quantity
        )

    def test_queue_depth_is_the_queue_ahead_restated(self) -> None:
        # The feature's own word, so a reader looking for it finds it.
        assert MIDDLE.queue_depth == MIDDLE.queue_ahead

    def test_the_depth_in_rebalances_is_the_exponent(self) -> None:
        assert MIDDLE.queue_rebalances == 100.0 / 500.0
        assert passive_fill_fraction(MIDDLE).depth_decay == math.exp(
            -MIDDLE.queue_rebalances
        )


class TestAZeroVolumeRebalance:
    def test_a_level_that_traded_nothing_fills_nothing(self) -> None:
        # No flow arrived to clear the queue, so the queue is never reached
        # and the order did not fill: zero, not a division error and not an
        # infinity.
        probability = passive_fill_fraction(
            QueueObservation(queue_ahead=100.0, order_quantity=10.0, rebalance_volume=0.0)
        )
        assert probability.depth_decay == 0.0
        assert probability.fill_fraction == 0.0
        assert probability.filled_quantity == 0.0

    def test_an_empty_queue_at_a_level_that_traded_nothing_also_fills_nothing(self) -> None:
        # The one case the limit does not cover — 0/0 — answered by the tape
        # rather than by arithmetic: nothing traded, so nothing filled.  The
        # same stance the tape gate takes toward an empty tape.
        probability = passive_fill_fraction(
            QueueObservation(queue_ahead=0.0, order_quantity=10.0, rebalance_volume=0.0)
        )
        assert probability.fill_fraction == 0.0

    def test_an_unmeasurable_depth_is_reported_as_an_absence(self) -> None:
        # The depth is not *zero* rebalances-worth, it is unmeasured: with no
        # flow to measure against there is no axis, and the two states must
        # stay distinguishable for a caller logging the observation.
        observation = QueueObservation(
            queue_ahead=100.0, order_quantity=10.0, rebalance_volume=0.0
        )
        assert observation.queue_rebalances is None

    def test_a_measurable_depth_reports_a_number(self) -> None:
        assert MIDDLE.queue_rebalances is not None


class TestTheValuesAreConsistent:
    def test_a_probability_is_a_value_not_a_mutable_record(self) -> None:
        with pytest.raises((TypeError, AttributeError)):
            probability = passive_fill_fraction(MIDDLE)
            probability.queue = MIDDLE  # type: ignore[misc]

    def test_an_observation_is_a_value_not_a_mutable_record(self) -> None:
        with pytest.raises((TypeError, AttributeError)):
            MIDDLE.queue_ahead = 1.0  # type: ignore[misc]

    def test_a_probability_over_a_non_observation_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            FillProbability(queue="not an observation")  # type: ignore[arg-type]

    def test_the_summary_rebuilds_from_the_evidence(self) -> None:
        summary = passive_fill_fraction(
            QueueObservation(queue_ahead=0.0, order_quantity=100.0, rebalance_volume=500.0)
        ).summary()
        assert summary == {
            "queue_depth": 0.0,
            "order_quantity": 100.0,
            "rebalance_volume": 500.0,
            "queue_rebalances": 0.0,
            "depth_decay": 1.0,
            "participation_cap": 1.0,
            "fill_fraction": 1.0,
            "filled_quantity": 100.0,
        }

    def test_the_summary_of_an_unmeasurable_depth_carries_the_absence(self) -> None:
        summary = passive_fill_fraction(
            QueueObservation(queue_ahead=100.0, order_quantity=10.0, rebalance_volume=0.0)
        ).summary()
        assert summary["queue_rebalances"] is None
        assert summary["fill_fraction"] == 0.0


class TestRefusedInputs:
    def test_a_negative_queue_depth_is_refused(self) -> None:
        # A queue is at its shortest when it is empty.
        with pytest.raises(CostModelFillError):
            QueueObservation(queue_ahead=-1.0, order_quantity=10.0, rebalance_volume=100.0)

    def test_a_non_positive_order_quantity_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            QueueObservation(queue_ahead=0.0, order_quantity=0.0, rebalance_volume=100.0)

    def test_a_negative_rebalance_volume_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            QueueObservation(queue_ahead=0.0, order_quantity=10.0, rebalance_volume=-1.0)

    def test_a_nan_depth_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            QueueObservation(
                queue_ahead=float("nan"), order_quantity=10.0, rebalance_volume=100.0
            )

    def test_an_infinite_volume_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            QueueObservation(
                queue_ahead=0.0, order_quantity=10.0, rebalance_volume=float("inf")
            )

    def test_a_boolean_quantity_is_refused(self) -> None:
        # isinstance(True, int): a quantity of True is a broken caller, not a
        # one-unit order.
        with pytest.raises(CostModelFillError):
            QueueObservation(
                queue_ahead=0.0, order_quantity=True, rebalance_volume=100.0  # type: ignore[arg-type]
            )

    def test_a_non_numeric_depth_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            QueueObservation(
                queue_ahead="deep", order_quantity=10.0, rebalance_volume=100.0  # type: ignore[arg-type]
            )


class TestResolveFillProbabilityModel:
    def test_the_shipped_default_resolves_to_the_exp_decay_model(self) -> None:
        # The default §6.2 document carries
        # fill_probability_model: exp_decay_vs_queue_depth, so the resolved
        # model is the exponential decay.
        model = resolve_fill_probability_model(read_cost_model_document()[0])
        assert isinstance(model, FillProbabilityModel)
        assert model.fill_probability_model == EXP_DECAY_MODEL

    def test_the_model_decays_the_same_as_the_function(self) -> None:
        model = resolve_fill_probability_model()
        assert model.decide(MIDDLE).fill_fraction == passive_fill_fraction(
            MIDDLE
        ).fill_fraction

    def test_a_document_without_a_fill_model_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_fill_probability_model({"version": "2026.09.1", "venue": "x"})

    def test_a_document_without_a_passive_half_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_fill_probability_model(
                {"fill_model": {"aggressive": {"walk_book": True}}}
            )

    def test_a_document_without_the_field_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_fill_probability_model(
                {"fill_model": {"passive": {"require_trade_through": True}}}
            )

    def test_a_document_whose_passive_half_is_not_a_mapping_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_fill_probability_model({"fill_model": {"passive": "exp_decay"}})

    def test_a_document_whose_fill_model_is_not_a_mapping_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_fill_probability_model({"fill_model": "passive"})

    def test_a_non_mapping_document_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            resolve_fill_probability_model("cost_model")  # type: ignore[arg-type]

    def test_a_different_fill_probability_model_is_refused(self) -> None:
        # The field names a model; a linear decay is a different behaviour,
        # and the shared library does not carry a second one.
        with pytest.raises(CostModelConfigError):
            FillProbabilityModel(fill_probability_model="linear_vs_queue_depth")

    def test_a_fill_everything_default_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError):
            FillProbabilityModel(fill_probability_model="always")

    def test_the_passive_sections_other_fields_are_not_read(self) -> None:
        # require_trade_through (feature 63) and queue_position_penalty_bps
        # (feature 64) are tolerated but not required here — the resolver
        # answers for the fill-probability model only.
        model = resolve_fill_probability_model(
            {
                "fill_model": {
                    "passive": {
                        "fill_probability_model": EXP_DECAY_MODEL,
                    }
                }
            }
        )
        assert model.fill_probability_model == EXP_DECAY_MODEL


class TestTheServiceResolvesTheFillProbabilityModel:
    def test_the_service_exposes_the_model_from_the_default(self) -> None:
        # The composed service resolves the model from the one cached parse
        # of the shipped §6.2 document, the same seam the passive gate and
        # the aggressive walk sit on.
        service = CostModelService.from_env()
        model = service.fill_probability()
        assert isinstance(model, FillProbabilityModel)
        assert model.fill_probability_model == EXP_DECAY_MODEL

    def test_the_service_model_matches_the_module_function(
        self, test_database_url: str
    ) -> None:
        service = CostModelService.from_env()
        assert service.fill_probability().decide(MIDDLE).summary() == (
            passive_fill_fraction(MIDDLE).summary()
        )

    def test_the_service_resolves_from_the_one_cached_parse(
        self, test_database_url: str
    ) -> None:
        # The three resolvers read the same cached parse, so the halves of
        # the fill model cannot disagree about which document was loaded.
        service = CostModelService.from_env()
        assert service.fill_probability().fill_probability_model == EXP_DECAY_MODEL
        assert service.passive().require_trade_through is True
        assert service.aggressive().walk_book is True
