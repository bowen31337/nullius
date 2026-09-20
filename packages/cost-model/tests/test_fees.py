"""Feature 61 — taker and maker fees in basis points per venue.

app_spec.xml, "Cost Model & Fill Simulation", feature 61: *System applies
taker and maker fees in basis points per venue, which returns a post-cost
return series.*  The sentence is a rate, a scope, a unit and a deliverable,
and each can fail independently, so the tests take them one at a time:

* **taker and maker fees** — the schedule carries two distinct rates, one
  per side, and a caller selects the one its fill earned by naming the
  side; a taker fill is never priced at the maker rate by a sign error.
* **in basis points** — the cost is spoken in the unit §6.2's fee schedule
  already speaks, and the same unit the walk's slippage and the queue
  penalty report: ``10 bps`` is ``0.001`` as a fraction, checked against the
  definition rather than against a remembered constant.
* **per venue** — the schedule is identified by the venue it prices, and
  the venue travels with the rates so a post-cost series names whose fees
  were taken off it.
* **which returns a post-cost return series** — a pre-cost series goes in
  and a post-cost one comes out, each element reduced by the fee the fill
  that earned it was charged, subtracted (not scaled) because the fee is a
  cost of trading, paid on the notional that turned over regardless of
  which way the price moved.

And the refusals that keep the charge honest: a *missing* taker or maker
rate is refused rather than defaulted to zero (a silently floored cost is
exactly the simulator `docs/alpha-engine-prd.md` §10 warns about), a
*configured* ``0.0`` is a legal value answered honestly as a zero cost, and
a negative or non-finite rate is refused, because a fee that pays the
trader is a rebate rather than the cost the document names.

:mod:`cost_model.fees` owns the schedule and the charge; the service tests
at the end pin that the composed component resolves the schedule from the
one cached parse.
"""

from __future__ import annotations

import pytest
from cost_model import (
    MAKER,
    MAKER_BPS_KEY,
    TAKER,
    TAKER_BPS_KEY,
    CostModelConfigError,
    CostModelFillError,
    CostModelService,
    FeeSchedule,
    PostCostReturn,
    apply_fee,
    resolve_fee_schedule,
)
from cost_model.config import read_cost_model_document
from cost_model.fees import _BPS_PER_UNIT

#: The shipped §6.2 document's own rate, restated here so a test that reads
#: it off the resolver is checked against the document's text and not
#: against the resolver's default.
SHIPPED_TAKER_BPS = 10.0
SHIPPED_MAKER_BPS = 10.0
SHIPPED_VENUE = "binance_spot"


class TestTakerAndMakerFees:
    """The schedule carries two distinct rates, and a caller picks the side."""

    def test_the_schedule_carries_both_rates(self) -> None:
        schedule = resolve_fee_schedule()
        assert schedule.taker_bps == SHIPPED_TAKER_BPS
        assert schedule.maker_bps == SHIPPED_MAKER_BPS

    def test_a_taker_fill_is_charged_the_taker_rate(self) -> None:
        assert resolve_fee_schedule().rate(TAKER) == SHIPPED_TAKER_BPS

    def test_a_maker_fill_is_charged_the_maker_rate(self) -> None:
        assert resolve_fee_schedule().rate(MAKER) == SHIPPED_MAKER_BPS

    def test_the_two_rates_are_independent_inputs(self) -> None:
        # A document can price the two sides differently — a venue that
        # rewards a resting maker with a zero maker fee still charges its
        # takers — and each side reads its own field.
        schedule = resolve_fee_schedule(
            {
                "venue": "x",
                "fees": {TAKER_BPS_KEY: 10.0, MAKER_BPS_KEY: 0.0},
            }
        )
        assert schedule.rate(TAKER) == 10.0
        assert schedule.rate(MAKER) == 0.0

    def test_the_side_is_case_insensitive(self) -> None:
        # "Taker" is the same side as "taker": the side is a role, not a
        # spelling.
        assert resolve_fee_schedule().rate("TAKER") == SHIPPED_TAKER_BPS
        assert resolve_fee_schedule().rate(" maker ") == SHIPPED_MAKER_BPS


class TestTheFeeIsInBasisPoints:
    """The cost is spoken in the unit §6.2's fee schedule already speaks."""

    def test_the_rate_is_spoken_in_basis_points(self) -> None:
        # 10 bps is 0.001 as a fraction — computed here from the definition
        # of a basis point, not copied from the output.
        charge = apply_fee(0.05, 10.0, TAKER)
        assert charge.fee_fraction == pytest.approx(10.0 / 10_000.0)
        assert charge.fee_fraction == pytest.approx(0.001)

    def test_the_fraction_matches_the_rate(self) -> None:
        charge = apply_fee(0.05, 2.5, MAKER)
        assert charge.fee_fraction == pytest.approx(2.5 / _BPS_PER_UNIT)

    def test_an_integer_rate_is_the_same_rate_as_a_float(self) -> None:
        assert apply_fee(0.05, 10, TAKER) == apply_fee(0.05, 10.0, TAKER)


class TestPerVenue:
    """The schedule is identified by the venue it prices."""

    def test_the_schedule_carries_its_venue(self) -> None:
        schedule = resolve_fee_schedule()
        assert schedule.venue == SHIPPED_VENUE

    def test_two_venues_carry_two_schedules(self) -> None:
        # The rates travel with the venue name, so a post-cost series names
        # whose fees were taken off it.
        a = resolve_fee_schedule({"venue": "a", "fees": {TAKER_BPS_KEY: 5.0, MAKER_BPS_KEY: 5.0}})
        b = resolve_fee_schedule({"venue": "b", "fees": {TAKER_BPS_KEY: 15.0, MAKER_BPS_KEY: 15.0}})
        assert (a.venue, a.taker_bps) == ("a", 5.0)
        assert (b.venue, b.taker_bps) == ("b", 15.0)


class TestAPostCostReturnSeries:
    """A pre-cost series goes in; a post-cost one comes out, each element reduced."""

    def test_a_single_return_is_reduced_by_the_fee(self) -> None:
        charge = apply_fee(0.05, SHIPPED_TAKER_BPS, TAKER)
        # The fee is subtracted, not scaled: a cost of trading, paid on the
        # notional that turned over regardless of which way the price moved.
        assert charge.pre_cost_return == pytest.approx(0.05)
        assert charge.post_cost_return == pytest.approx(0.05 - 0.001)

    def test_a_winning_and_a_losing_return_pay_the_same_fee(self) -> None:
        # A +5% and a -2% return are both reduced by exactly 10 bps: the
        # exchange charges the trade, not the outcome.
        charge = apply_fee(-0.02, SHIPPED_TAKER_BPS, TAKER)
        assert charge.post_cost_return == pytest.approx(-0.02 - 0.001)

    def test_the_charge_carries_the_rate_and_side_it_was_charged_at(self) -> None:
        charge = apply_fee(0.05, SHIPPED_TAKER_BPS, TAKER)
        assert charge.fee_bps == SHIPPED_TAKER_BPS
        assert charge.side == TAKER

    def test_a_post_cost_return_can_fall_below_the_pre_cost_one(self) -> None:
        # A fee that exceeds a return is a real state — a small edge eaten
        # whole by costs — not an error to hide, so there is no clamping.
        charge = apply_fee(0.0005, SHIPPED_TAKER_BPS, TAKER)
        assert charge.post_cost_return == pytest.approx(0.0005 - 0.001)
        assert charge.post_cost_return < 0.0

    def test_a_zero_fee_returns_the_return_unchanged(self) -> None:
        # A venue whose fee is nil is a legal schedule, answered honestly.
        charge = apply_fee(0.05, 0.0, TAKER)
        assert charge.fee_bps == 0.0
        assert charge.post_cost_return == pytest.approx(0.05)
        assert charge.summary()["post_cost_return"] == pytest.approx(0.05)

    def test_applying_to_a_series_returns_one_value_per_element(self) -> None:
        schedule = resolve_fee_schedule()
        pre = [0.05, -0.02, 0.01]
        post = schedule.apply(pre, TAKER)
        assert len(post) == len(pre)
        assert [r.post_cost_return for r in post] == pytest.approx(
            [r - 0.001 for r in pre]
        )

    def test_applying_preserves_the_order(self) -> None:
        # The fee does not reorder a series: element i in maps to element i
        # out, each carrying the same rate and side.
        schedule = resolve_fee_schedule()
        post = schedule.apply([0.05, -0.02, 0.01], MAKER)
        for r in post:
            assert r.fee_bps == SHIPPED_MAKER_BPS
            assert r.side == MAKER

    def test_an_empty_series_returns_an_empty_tuple(self) -> None:
        assert resolve_fee_schedule().apply([], TAKER) == ()


class TestTheChargeIsAHonestValue:
    """The record explains itself and cannot be edited into a different one."""

    def test_the_summary_carries_the_two_returns_the_fee_and_the_side(self) -> None:
        charge = apply_fee(0.05, SHIPPED_TAKER_BPS, TAKER)
        assert charge.summary() == {
            "side": TAKER,
            "fee_bps": SHIPPED_TAKER_BPS,
            "fee_fraction": SHIPPED_TAKER_BPS / 10_000.0,
            "pre_cost_return": pytest.approx(0.05),
            "post_cost_return": pytest.approx(0.05 - 0.001),
        }

    def test_the_summary_is_rebuilt_rather_than_cached(self) -> None:
        charge = apply_fee(0.05, 10.0, TAKER)
        assert charge.summary() == charge.summary()
        assert charge.summary() is not charge.summary()

    def test_the_charge_is_frozen(self) -> None:
        charge = PostCostReturn(pre_cost_return=0.05, fee_bps=10.0, side=TAKER)
        with pytest.raises(AttributeError):
            charge.fee_bps = 9.0  # type: ignore[misc]

    def test_a_hand_built_charge_is_the_same_value_as_the_functions(self) -> None:
        # The record has one shape however it was built.
        assert PostCostReturn(pre_cost_return=0.05, fee_bps=10.0, side=TAKER) == (
            apply_fee(0.05, 10.0, TAKER)
        )

    def test_the_schedule_is_frozen(self) -> None:
        schedule = resolve_fee_schedule()
        with pytest.raises(AttributeError):
            schedule.taker_bps = 9.0  # type: ignore[misc]

    def test_the_charge_can_be_hashed_and_compared(self) -> None:
        assert apply_fee(0.05, 10.0, TAKER) == apply_fee(0.05, 10.0, TAKER)
        assert hash(apply_fee(0.05, 10.0, TAKER)) == hash(apply_fee(0.05, 10.0, TAKER))


class TestTheInputContract:
    """A charge the module cannot honestly levy is refused, not smoothed over."""

    def test_a_negative_rate_is_refused(self) -> None:
        # A fee that pays the trader is a rebate — a different instrument,
        # with no field in §6.2's document.
        with pytest.raises(CostModelFillError, match="rebate"):
            apply_fee(0.05, -10.0, TAKER)

    def test_a_non_finite_rate_is_refused(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(CostModelFillError):
                apply_fee(0.05, value, TAKER)

    def test_a_non_numeric_rate_is_refused(self) -> None:
        for value in ("10.0", None, [10.0]):
            with pytest.raises(CostModelFillError):
                apply_fee(0.05, value, TAKER)  # type: ignore[arg-type]

    def test_a_boolean_rate_is_refused(self) -> None:
        # isinstance(True, int) — a fee of True is a broken caller, not a
        # one-basis-point charge.
        with pytest.raises(CostModelFillError):
            apply_fee(0.05, True, TAKER)

    def test_a_non_finite_return_is_refused(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(CostModelFillError, match="finite"):
                apply_fee(value, 10.0, TAKER)

    def test_a_non_numeric_return_is_refused(self) -> None:
        with pytest.raises(CostModelFillError):
            apply_fee("0.05", 10.0, TAKER)  # type: ignore[arg-type]

    def test_an_unknown_side_is_refused(self) -> None:
        # A fee side is a role, not a direction: 'buy'/'sell' name order
        # directions and 'bid'/'ask' name book sides, and neither is a fee
        # side.
        with pytest.raises(CostModelFillError, match="fee side"):
            apply_fee(0.05, 10.0, "buy")
        with pytest.raises(CostModelFillError, match="fee side"):
            apply_fee(0.05, 10.0, None)  # type: ignore[arg-type]


class TestResolveFeeSchedule:
    """The §6.2 shape is demanded, not defaulted."""

    def test_the_shipped_default_resolves_to_the_documents_rates(self) -> None:
        document, _origin = read_cost_model_document()
        fees = document["fees"]
        schedule = resolve_fee_schedule(document)
        assert isinstance(schedule, FeeSchedule)
        assert schedule.venue == SHIPPED_VENUE
        assert schedule.taker_bps == fees[TAKER_BPS_KEY] == SHIPPED_TAKER_BPS
        assert schedule.maker_bps == fees[MAKER_BPS_KEY] == SHIPPED_MAKER_BPS

    def test_the_default_argument_reads_the_shipped_document_too(self) -> None:
        assert resolve_fee_schedule().venue == SHIPPED_VENUE

    def test_the_model_rates_match_the_module_function(self) -> None:
        # The schedule's apply and the module function are one charge: the
        # schedule applies its rate to each element, so a one-element series
        # is the single-element tuple of that charge.
        schedule = resolve_fee_schedule()
        assert schedule.apply([0.05], TAKER) == (
            apply_fee(0.05, SHIPPED_TAKER_BPS, TAKER),
        )

    def test_a_document_without_a_fees_block_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="no 'fees' block"):
            resolve_fee_schedule({"venue": "x"})

    def test_a_document_without_a_taker_rate_is_refused(self) -> None:
        # Unlike a fill-model flag — whose siblings are tolerated — a fee is
        # this feature's input, and defaulting a cost to zero silently is
        # exactly the floored simulator §10 warns about.
        with pytest.raises(CostModelConfigError, match="floored"):
            resolve_fee_schedule(
                {"venue": "x", "fees": {MAKER_BPS_KEY: 10.0}}
            )

    def test_a_document_without_a_maker_rate_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="floored"):
            resolve_fee_schedule(
                {"venue": "x", "fees": {TAKER_BPS_KEY: 10.0}}
            )

    def test_a_document_without_a_venue_is_refused(self) -> None:
        # A fee schedule is priced per venue, and the rates are meaningless
        # apart from the venue they belong to.
        with pytest.raises(CostModelConfigError, match="no venue"):
            resolve_fee_schedule({"fees": {TAKER_BPS_KEY: 10.0, MAKER_BPS_KEY: 10.0}})

    def test_a_blank_venue_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="blank"):
            resolve_fee_schedule(
                {"venue": "   ", "fees": {TAKER_BPS_KEY: 10.0, MAKER_BPS_KEY: 10.0}}
            )

    def test_a_document_whose_rate_is_malformed_is_refused_as_a_document(self) -> None:
        # A malformed rate in a signed Z0 artifact is the *document's*
        # defect: an operator fixing it catches config errors, not fill
        # errors.
        for value in ("10.0", None, -10.0, float("nan")):
            with pytest.raises(CostModelConfigError, match="unusable"):
                resolve_fee_schedule(
                    {"venue": "x", "fees": {TAKER_BPS_KEY: value, MAKER_BPS_KEY: 10.0}}
                )

    def test_a_boolean_configured_rate_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="unusable"):
            resolve_fee_schedule(
                {"venue": "x", "fees": {TAKER_BPS_KEY: True, MAKER_BPS_KEY: 10.0}}
            )

    def test_a_zero_configured_rate_is_answered_honestly(self) -> None:
        # 0.0 is a legal document value — an operator may have measured a
        # venue's fee as nil — and the honest answer is a zero cost, not a
        # refusal.
        schedule = resolve_fee_schedule(
            {"venue": "x", "fees": {TAKER_BPS_KEY: 0.0, MAKER_BPS_KEY: 0.0}}
        )
        assert schedule.rate(TAKER) == 0.0
        assert schedule.apply([0.05], TAKER)[0].post_cost_return == pytest.approx(0.05)

    def test_a_non_mapping_fees_block_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="not a mapping"):
            resolve_fee_schedule({"venue": "x", "fees": [10.0]})

    def test_a_non_mapping_document_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="not a"):
            resolve_fee_schedule("cost_model")  # type: ignore[arg-type]

    def test_the_discount_token_field_is_not_read(self) -> None:
        # §6.2's discount_token belongs to feature 62 — tolerated here and
        # not required, because this resolver answers for the two plain
        # rates only.
        schedule = resolve_fee_schedule(
            {
                "venue": "x",
                "fees": {
                    TAKER_BPS_KEY: 10.0,
                    MAKER_BPS_KEY: 10.0,
                    "discount_token": "BNB",
                },
            }
        )
        assert schedule.rate(TAKER) == 10.0
        assert schedule.rate(MAKER) == 10.0


class TestTheServiceResolvesTheFeeSchedule:
    def test_the_service_exposes_the_schedule_from_the_default(self) -> None:
        # The composed service resolves the schedule from the one cached
        # parse of the shipped §6.2 document, the same seam the fill gates,
        # the fill-probability decay, the aggressive walk and the queue
        # penalty sit on.
        service = CostModelService.from_env()
        schedule = service.fees()  # type: ignore[attr-defined]
        assert isinstance(schedule, FeeSchedule)
        assert schedule.venue == SHIPPED_VENUE
        assert schedule.taker_bps == SHIPPED_TAKER_BPS

    def test_the_service_resolves_from_the_one_cached_parse(
        self, test_database_url: str
    ) -> None:
        # The fee schedule and the fill model read the same cached parse, so
        # the halves of the cost model cannot disagree about which document
        # was loaded.
        service = CostModelService.from_env()
        assert service.fees().taker_bps == SHIPPED_TAKER_BPS  # type: ignore[attr-defined]
        assert service.passive().require_trade_through is True

    def test_the_service_reads_the_schedule_out_of_a_supplied_document(
        self, document
    ) -> None:
        # The rates are the document's, routed end to end: an operator's
        # artifact changes the charge, which is the whole point of the
        # fields living in the Z0 document.
        path = document(
            'version: "2026.09.1"\n'
            "venue: binance_spot\n"
            "fees:\n"
            f"  {TAKER_BPS_KEY}: 12.0\n"
            f"  {MAKER_BPS_KEY}: 8.0\n"
        )
        service = CostModelService.from_env()
        service.load(path)
        assert service.fees().taker_bps == 12.0  # type: ignore[attr-defined]
        assert service.fees().maker_bps == 8.0  # type: ignore[attr-defined]


class TestThePackageExportsTheFeature:
    def test_the_public_names_are_exported(self) -> None:
        import cost_model

        for name in (
            "FEES_KEY",
            "MAKER",
            "MAKER_BPS_KEY",
            "TAKER",
            "TAKER_BPS_KEY",
            "FeeSchedule",
            "PostCostReturn",
            "apply_fee",
            "resolve_fee_schedule",
        ):
            assert name in cost_model.__all__
            assert hasattr(cost_model, name)

    def test_the_exported_charge_is_one_implementation(self) -> None:
        # The package-level name and the module-level one are the same
        # object, not a facade over a twin.
        import cost_model
        import cost_model.fees as module

        assert cost_model.apply_fee is module.apply_fee
        assert cost_model.resolve_fee_schedule is module.resolve_fee_schedule
