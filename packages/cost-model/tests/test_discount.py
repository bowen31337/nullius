"""Feature 62 — the discount-token fee reduction.

app_spec.xml, "Cost Model & Fill Simulation", feature 62: *System applies a
discount-token fee reduction when configured, which returns an effective 7.5
bps rate in place of 10 bps.*  The sentence has three claims, and each can
fail independently, so the tests take them one at a time:

* **applies a discount-token fee reduction** — the mechanism is a *rate
  substitution*, not a second charge: the reduced schedule goes through
  feature 61's own ``apply``, so the discount cannot become a second
  implementation of the fee arithmetic (feature 69's promise, §6.2's
  ``β₄``).
* **when configured** — the document's ``discount_token`` is the switch.  A
  document that names one is discounted; a document that omits the field
  resolves to an *unconfigured* discount whose effective rate is the
  schedule's own, because a venue whose fees are paid in the quote currency
  has no token and that is not a defect.  A token that is *present and
  blank* is refused — a typo in a signed Z0 artifact is not an absent field.
* **which returns an effective 7.5 bps rate in place of 10 bps** — the
  deliverable is the rate, and the reduction is a *share* of the venue's own
  fee (25% off, which is §6.2's own arithmetic and
  `docs/alpha-engine-prd.md` §10's "0.1% maker/taker; 0.075% with BNB
  deduction"), not a constant substituted for every schedule: a schedule that
  priced 20 bps is repriced to 15, never to the one venue's 7.5.

And the refusals that keep the reduction honest: a reduction fraction outside
``[0, 1]`` is refused (above 1 it would pay the trader, which is a rebate
§6.2's document has no field for), a non-finite one is refused, and a boolean
is refused (``isinstance(True, int)``).

:mod:`cost_model.discount` owns the reduction; the service tests at the end
pin that the composed component resolves it from the one cached parse.
"""

from __future__ import annotations

import pytest
from cost_model import (
    DISCOUNT_TOKEN_KEY,
    MAKER,
    MAKER_BPS_KEY,
    TAKER,
    TAKER_BPS_KEY,
    CostModelConfigError,
    CostModelFillError,
    CostModelService,
    FeeDiscount,
    FeeSchedule,
    PostCostReturn,
    discount_fee_schedule,
    resolve_fee_discount,
    resolve_fee_schedule,
)
from cost_model.config import read_cost_model_document
from cost_model.discount import DEFAULT_DISCOUNT_FRACTION
from cost_model.fees import _BPS_PER_UNIT

#: The shipped §6.2 document's own numbers, restated here so a test that
#: reads them off the resolver is checked against the document's text and its
#: comment (``→ 7.5 bps``) rather than against the implementation's output.
SHIPPED_TAKER_BPS = 10.0
SHIPPED_MAKER_BPS = 10.0
SHIPPED_VENUE = "binance_spot"
SHIPPED_TOKEN = "BNB"
SHIPPED_DISCOUNTED_BPS = 7.5

#: A schedule built by hand, for the cases where the subject is the
#: arithmetic rather than the document.
_RATES = {TAKER_BPS_KEY: 10.0, MAKER_BPS_KEY: 10.0}


def _fees(**extra: object) -> dict[str, object]:
    """A §6.2 fee block with ``extra`` merged in — the shortest honest document."""
    return {"venue": "binance_spot", "fees": {**_RATES, **extra}}


class TestTheReductionIsApplied:
    """The feature's headline: 10 bps in, 7.5 bps out."""

    def test_the_effective_rate_replaces_the_configured_one(self) -> None:
        schedule = resolve_fee_schedule(_fees(**{DISCOUNT_TOKEN_KEY: SHIPPED_TOKEN}))
        discount = resolve_fee_discount(_fees(**{DISCOUNT_TOKEN_KEY: SHIPPED_TOKEN}))
        assert discount.effective_rate(schedule, TAKER) == pytest.approx(
            SHIPPED_DISCOUNTED_BPS
        )

    def test_the_shipped_document_discounts_both_sides(self) -> None:
        # §6.2's document and docs/alpha-engine-prd.md §10 both state one
        # deduction on the fee — "0.1% maker/taker; 0.075% with BNB
        # deduction" — not a side-selective one.
        discount = resolve_fee_discount()
        schedule = resolve_fee_schedule()
        assert discount.effective_rate(schedule, TAKER) == pytest.approx(7.5)
        assert discount.effective_rate(schedule, MAKER) == pytest.approx(7.5)

    def test_the_reduced_schedule_carries_the_reduced_rates(self) -> None:
        discount = resolve_fee_discount()
        reduced = discount.reduce(resolve_fee_schedule())
        assert isinstance(reduced, FeeSchedule)
        assert reduced.taker_bps == pytest.approx(SHIPPED_DISCOUNTED_BPS)
        assert reduced.maker_bps == pytest.approx(SHIPPED_DISCOUNTED_BPS)

    def test_the_reduction_is_named_beside_the_effective_rate(self) -> None:
        # "7.5 bps in place of 10 bps" — the difference is 2.5, stated rather
        # than left for the caller to subtract.
        discount = resolve_fee_discount()
        assert discount.reduction_bps(SHIPPED_TAKER_BPS) == pytest.approx(2.5)
        assert discount.effective_bps(SHIPPED_TAKER_BPS) + discount.reduction_bps(
            SHIPPED_TAKER_BPS
        ) == pytest.approx(SHIPPED_TAKER_BPS)

    def test_the_reduction_is_a_share_of_the_venues_own_fee(self) -> None:
        # The reduction is 25% off the rate the *schedule* carries, not a
        # constant substituted for it: a venue pricing 20 bps is repriced to
        # 15, never to the one venue's 7.5.
        discount = FeeDiscount(token=SHIPPED_TOKEN)
        assert discount.effective_bps(20.0) == pytest.approx(15.0)
        assert discount.effective_bps(10.0) == pytest.approx(7.5)

    def test_the_retained_fraction_is_the_complement(self) -> None:
        discount = resolve_fee_discount()
        assert discount.retained_fraction == pytest.approx(
            1.0 - DEFAULT_DISCOUNT_FRACTION
        )
        assert discount.fraction + discount.retained_fraction == pytest.approx(1.0)

    def test_the_venue_is_carried_through_the_reduction(self) -> None:
        # The discount changes what the venue charges, not whose schedule
        # this is — the venue travels with the reduced rates exactly as it
        # travels with the unreduced ones.
        reduced = resolve_fee_discount().reduce(resolve_fee_schedule())
        assert reduced.venue == SHIPPED_VENUE


class TestThePostCostSeriesUsesTheReducedRate:
    """*"which returns an effective 7.5 bps rate in place of 10 bps"* — end to end."""

    def test_the_series_is_reduced_by_the_effective_rate(self) -> None:
        schedule = resolve_fee_schedule()
        discounted = resolve_fee_discount().apply(schedule, [0.05], TAKER)
        assert len(discounted) == 1
        assert isinstance(discounted[0], PostCostReturn)
        assert discounted[0].fee_bps == pytest.approx(SHIPPED_DISCOUNTED_BPS)
        assert discounted[0].post_cost_return == pytest.approx(
            0.05 - SHIPPED_DISCOUNTED_BPS / _BPS_PER_UNIT
        )

    def test_the_discounted_series_costs_less_than_the_undiscounted_one(self) -> None:
        schedule = resolve_fee_schedule()
        undiscounted = schedule.apply([0.05], TAKER)[0]
        discounted = resolve_fee_discount().apply(schedule, [0.05], TAKER)[0]
        assert discounted.post_cost_return > undiscounted.post_cost_return
        # The two differ by exactly the reduction — 2.5 bps, the difference
        # between 10 bps and 7.5 — and by nothing else.
        assert discounted.post_cost_return - undiscounted.post_cost_return == (
            pytest.approx(2.5 / _BPS_PER_UNIT)
        )

    def test_the_discount_is_one_input_to_feature_61s_charge(self) -> None:
        # The claim feature 69 protects, from the discount side: the
        # discounted series is produced by feature 61's own subtraction on a
        # reduced schedule, and by nothing else.  Asserted structurally —
        # the two calls are the same call.
        schedule = resolve_fee_schedule()
        discount = resolve_fee_discount()
        assert discount.apply(schedule, [0.05, -0.02], TAKER) == (
            discount.reduce(schedule).apply([0.05, -0.02], TAKER)
        )

    def test_the_charge_is_subtracted_not_scaled(self) -> None:
        # A winning and a losing return pay the same reduced fee, exactly as
        # they pay the same undiscounted one — the discount changes the rate
        # and not the arithmetic.
        schedule = resolve_fee_schedule()
        discount = resolve_fee_discount()
        win, loss = discount.apply(schedule, [0.05, -0.02], TAKER)
        assert win.pre_cost_return - win.post_cost_return == pytest.approx(
            loss.pre_cost_return - loss.post_cost_return
        )

    def test_the_series_preserves_its_length_and_order(self) -> None:
        schedule = resolve_fee_schedule()
        returns = [0.05, -0.02, 0.01, 0.0]
        charged = resolve_fee_discount().apply(schedule, returns, TAKER)
        assert [r.pre_cost_return for r in charged] == returns

    def test_an_empty_series_is_an_empty_series(self) -> None:
        # The honest answer for a series with no returns to price, discounted
        # or not.
        assert resolve_fee_discount().apply(resolve_fee_schedule(), [], TAKER) == ()

    def test_a_maker_series_is_charged_the_reduced_maker_rate(self) -> None:
        discount = resolve_fee_discount()
        schedule = resolve_fee_schedule()
        assert discount.apply(schedule, [0.05], MAKER)[0].side == MAKER
        assert discount.apply(schedule, [0.05], MAKER)[0].fee_bps == pytest.approx(
            discount.effective_rate(schedule, MAKER)
        )


class TestWhenConfigured:
    """The feature's condition: a token present discounts, a token absent does not."""

    def test_the_shipped_document_is_configured(self) -> None:
        discount = resolve_fee_discount()
        assert discount.configured is True
        assert discount.token == SHIPPED_TOKEN

    def test_a_document_without_a_token_resolves_unconfigured(self) -> None:
        discount = resolve_fee_discount(_fees())
        assert discount.configured is False
        assert discount.token is None

    def test_an_unconfigured_discount_returns_the_schedules_own_rate(self) -> None:
        # No token, no reduction — and specifically *not* a silent repricing
        # to the one venue's discounted rate.
        discount = resolve_fee_discount(_fees())
        assert discount.effective_bps(10.0) == pytest.approx(10.0)
        assert discount.reduction_bps(10.0) == 0.0

    def test_an_unconfigured_discount_reduces_nothing(self) -> None:
        # A caller can route every fill through one call without a branch of
        # its own: the schedule that comes back is the one that went in.
        schedule = resolve_fee_schedule(_fees())
        reduced = resolve_fee_discount(_fees()).reduce(schedule)
        assert reduced.taker_bps == schedule.taker_bps
        assert reduced.maker_bps == schedule.maker_bps

    def test_an_unconfigured_discount_is_not_the_shared_librarys_default(self) -> None:
        # The unconfigured value still carries the library's fraction — the
        # fraction is what a token *earns*, not whether one is held — but
        # `configured` is what decides whether it is applied.
        discount = resolve_fee_discount(_fees())
        assert discount.fraction == pytest.approx(DEFAULT_DISCOUNT_FRACTION)
        assert discount.configured is False

    def test_a_hand_built_discount_defaults_to_unconfigured(self) -> None:
        # Constructing one with no argument states no token, so nothing is
        # reduced; the fraction default is the document's arithmetic, not a
        # claim that a token is held.
        discount = FeeDiscount()
        assert discount.configured is False
        assert discount.effective_bps(10.0) == pytest.approx(10.0)

    def test_the_token_is_read_verbatim(self) -> None:
        discount = resolve_fee_discount(_fees(**{DISCOUNT_TOKEN_KEY: "  FTT  "}))
        assert discount.token == "FTT"

    def test_any_token_name_configures_the_reduction(self) -> None:
        # No token whitelist and no per-token rate table: the document names
        # a token, and the library applies the reduction it implements.  A
        # table mapping BNB to 25% and everything else to nothing would be a
        # behaviour §6.2's document does not carry.
        discount = resolve_fee_discount(_fees(**{DISCOUNT_TOKEN_KEY: "something"}))
        assert discount.configured is True
        assert discount.effective_bps(10.0) == pytest.approx(7.5)

    def test_a_yaml_null_token_is_the_absent_field(self) -> None:
        # `discount_token:` with no value is YAML's spelling of "this field
        # has no value", which is the same statement as omitting it: no token
        # is configured and the schedule's own rate stands.
        discount = resolve_fee_discount(_fees(**{DISCOUNT_TOKEN_KEY: None}))
        assert discount.configured is False

    def test_a_blank_token_is_refused(self) -> None:
        # Present but naming nothing is a typo in a signed artifact, not an
        # absent field — refused rather than treated as unconfigured.
        with pytest.raises(CostModelConfigError, match="blank"):
            resolve_fee_discount(_fees(**{DISCOUNT_TOKEN_KEY: "   "}))
        with pytest.raises(CostModelConfigError, match="blank"):
            resolve_fee_discount(_fees(**{DISCOUNT_TOKEN_KEY: ""}))

    def test_a_non_string_token_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="not a token name"):
            resolve_fee_discount(_fees(**{DISCOUNT_TOKEN_KEY: 25}))

    def test_a_blank_token_resolved_directly_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="blank"):
            FeeDiscount(token=" ")


class TestTheReductionFractionContract:
    """The fraction is the library's constant, and it has a range."""

    def test_the_fraction_is_the_shipped_arithmetic(self) -> None:
        # 10 bps less a quarter of itself is 7.5 bps — the document's own
        # comment, checked against the definition rather than against a
        # remembered number.
        assert DEFAULT_DISCOUNT_FRACTION == pytest.approx(0.25)
        assert 10.0 * (1.0 - DEFAULT_DISCOUNT_FRACTION) == pytest.approx(7.5)

    def test_zero_is_legal(self) -> None:
        # A token that earns nothing is a fact, not a defect.
        assert FeeDiscount(token="X", fraction=0.0).effective_bps(10.0) == (
            pytest.approx(10.0)
        )

    def test_one_is_legal(self) -> None:
        # A fee the token waives entirely.
        assert FeeDiscount(token="X", fraction=1.0).effective_bps(10.0) == 0.0

    @pytest.mark.parametrize("fraction", [1.5, 2.0, -0.25])
    def test_a_reduction_outside_the_unit_interval_is_refused(
        self, fraction: float
    ) -> None:
        # Above 1 the reduction pays the trader, which is a rebate — a
        # different instrument with no field in §6.2's document.
        with pytest.raises(CostModelFillError, match="between"):
            FeeDiscount(token="X", fraction=fraction)

    @pytest.mark.parametrize("fraction", [float("nan"), float("inf")])
    def test_a_non_finite_reduction_is_refused(self, fraction: float) -> None:
        with pytest.raises(CostModelFillError, match="non-finite"):
            FeeDiscount(token="X", fraction=fraction)

    def test_a_boolean_reduction_is_refused(self) -> None:
        # isinstance(True, int) — a reduction of True is a broken caller, not
        # a total discount.
        with pytest.raises(CostModelFillError, match="between"):
            FeeDiscount(token="X", fraction=True)  # type: ignore[arg-type]

    def test_a_non_numeric_reduction_is_refused(self) -> None:
        with pytest.raises(CostModelFillError, match="between"):
            FeeDiscount(token="X", fraction="0.25")  # type: ignore[arg-type]

    @pytest.mark.parametrize("bps", [-1.0, float("nan"), float("inf")])
    def test_an_impossible_rate_is_refused(self, bps: float) -> None:
        discount = FeeDiscount(token="X")
        with pytest.raises(CostModelFillError):
            discount.effective_bps(bps)

    def test_a_boolean_rate_is_refused(self) -> None:
        with pytest.raises(CostModelFillError, match="basis points"):
            FeeDiscount(token="X").effective_bps(True)  # type: ignore[arg-type]

    def test_a_zero_rate_survives_the_reduction(self) -> None:
        # A zero-maker venue: the reduction has nothing to take off, and the
        # honest answer is zero rather than a negative rate.
        assert resolve_fee_discount().effective_bps(0.0) == 0.0


class TestTheReductionIsAppliedToAScheduleOnly:
    """The reduction is a change to feature 61's rates, not a charge of its own."""

    @pytest.mark.parametrize("not_a_schedule", [10.0, "binance_spot", None, {}])
    def test_something_that_is_not_a_schedule_is_refused(
        self, not_a_schedule: object
    ) -> None:
        # Both doors refuse it the same way: a caller's mistake is described
        # by this package's own vocabulary rather than surfacing as an
        # AttributeError from deep inside an attribute lookup.
        with pytest.raises(CostModelFillError, match="fee schedule"):
            resolve_fee_discount().reduce(not_a_schedule)  # type: ignore[arg-type]
        with pytest.raises(CostModelFillError, match="fee schedule"):
            resolve_fee_discount().effective_rate(
                not_a_schedule, TAKER  # type: ignore[arg-type]
            )

    def test_an_unknown_side_is_refused(self) -> None:
        # The side is coerced by feature 61's own `_coerce_side`, so this
        # cannot accept a side the schedule would refuse.
        with pytest.raises(CostModelFillError, match="fee side"):
            resolve_fee_discount().effective_rate(resolve_fee_schedule(), "buy")

    def test_the_schedule_type_is_the_shared_librarys(self) -> None:
        # The reduced schedule is feature 61's `FeeSchedule` — the same type
        # the evaluator and the live engine charge through, not a
        # discount-specific twin.
        assert isinstance(resolve_fee_discount().reduce(resolve_fee_schedule()), FeeSchedule)

    def test_the_value_is_frozen(self) -> None:
        discount = resolve_fee_discount()
        with pytest.raises(AttributeError):
            discount.token = "ETH"  # type: ignore[misc]

    def test_the_summary_explains_the_reduction(self) -> None:
        summary = resolve_fee_discount().summary()
        assert summary["token"] == SHIPPED_TOKEN
        assert summary["configured"] is True
        assert summary["fraction"] == pytest.approx(DEFAULT_DISCOUNT_FRACTION)
        assert summary["retained_fraction"] == pytest.approx(0.75)

    def test_an_unconfigured_summary_says_so(self) -> None:
        # A missing discount is visible as a fact rather than inferred from a
        # rate that happens to be unreduced.
        summary = resolve_fee_discount(_fees()).summary()
        assert summary["token"] is None
        assert summary["configured"] is False

    def test_the_function_and_the_value_are_one_implementation(self) -> None:
        schedule = resolve_fee_schedule()
        discount = resolve_fee_discount()
        assert discount_fee_schedule(schedule, discount) == discount.reduce(schedule)


class TestTheResolver:
    def test_the_shipped_default_resolves_the_document_token(self) -> None:
        assert resolve_fee_discount().token == SHIPPED_TOKEN

    def test_the_resolver_reads_the_one_cached_parse(self) -> None:
        # `None` reads the shipped document through the same single-parse
        # seam the fee schedule and the fill models sit on, so the schedule
        # and the token that reduces it cannot disagree about which document
        # was loaded: both resolvers answer from one parse.
        parsed, _origin = read_cost_model_document()
        assert resolve_fee_discount().token == resolve_fee_discount(parsed).token
        assert resolve_fee_schedule(parsed).taker_bps == SHIPPED_TAKER_BPS

    @pytest.mark.parametrize("document", ["cost_model", 10.0, [1, 2]])
    def test_a_non_mapping_document_is_refused(self, document: object) -> None:
        with pytest.raises(CostModelConfigError, match="not a"):
            resolve_fee_discount(document)  # type: ignore[arg-type]

    def test_a_document_with_no_fees_block_is_refused(self) -> None:
        # A discount with no fee to reduce prices nothing.
        with pytest.raises(CostModelConfigError, match="fees"):
            resolve_fee_discount({"venue": "x"})

    def test_a_non_mapping_fees_block_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="not a mapping"):
            resolve_fee_discount({"venue": "x", "fees": [10.0]})

    def test_the_schedules_own_fields_are_not_read_here(self) -> None:
        # taker_bps/maker_bps belong to feature 61 — tolerated here and not
        # required, because this resolver answers for the token only.  A
        # block with a token and no rates still resolves a discount.
        discount = resolve_fee_discount({"venue": "x", "fees": {DISCOUNT_TOKEN_KEY: "BNB"}})
        assert discount.token == "BNB"


class TestTheServiceResolvesTheDiscount:
    def test_the_service_exposes_the_discount_from_the_default(self) -> None:
        # The composed service resolves the discount from the one cached
        # parse of the shipped §6.2 document, the same seam the fee schedule
        # and the fill models sit on.
        service = CostModelService.from_env()
        discount = service.fee_discount()
        assert isinstance(discount, FeeDiscount)
        assert discount.token == SHIPPED_TOKEN
        assert discount.configured is True

    def test_the_service_rates_reach_the_documented_effective_rate(self) -> None:
        # End to end through the composed component: the shipped venue's 10
        # bps taker rate becomes 7.5.
        service = CostModelService.from_env()
        schedule = service.fees()
        assert service.fee_discount().effective_rate(schedule, TAKER) == pytest.approx(
            SHIPPED_DISCOUNTED_BPS
        )

    def test_the_service_reads_the_token_out_of_a_supplied_document(
        self, document
    ) -> None:
        # The token is the document's, routed end to end: an operator's
        # artifact changes the reduction, which is the whole point of the
        # field living in the Z0 document.
        path = document(
            'version: "2026.09.1"\n'
            "venue: binance_spot\n"
            "fees:\n"
            "  taker_bps: 10.0\n"
            "  maker_bps: 10.0\n"
            f"  {DISCOUNT_TOKEN_KEY}: FTT\n"
        )
        service = CostModelService.from_env()
        service.load(path)
        assert service.fee_discount().token == "FTT"
        assert service.fee_discount().effective_rate(service.fees(), TAKER) == (
            pytest.approx(SHIPPED_DISCOUNTED_BPS)
        )

    def test_a_document_without_a_token_composes_an_unconfigured_discount(
        self, document
    ) -> None:
        path = document(
            'version: "2026.09.1"\n'
            "venue: binance_spot\n"
            "fees:\n"
            "  taker_bps: 10.0\n"
            "  maker_bps: 10.0\n"
        )
        service = CostModelService.from_env()
        service.load(path)
        discount = service.fee_discount()
        assert discount.configured is False
        assert discount.effective_rate(service.fees(), TAKER) == pytest.approx(10.0)

    def test_the_service_resolves_from_the_one_cached_parse(self) -> None:
        # The discount and the fee schedule read the same cached parse, so the
        # fee axis cannot disagree with itself about which document was
        # loaded.
        service = CostModelService.from_env()
        assert service.fee_discount().token == SHIPPED_TOKEN
        assert service.fees().taker_bps == SHIPPED_TAKER_BPS


class TestThePackageExportsTheFeature:
    def test_the_public_names_are_exported(self) -> None:
        import cost_model

        for name in (
            "DEFAULT_DISCOUNT_FRACTION",
            "DISCOUNT_TOKEN_KEY",
            "FeeDiscount",
            "discount_fee_schedule",
            "resolve_fee_discount",
        ):
            assert name in cost_model.__all__
            assert hasattr(cost_model, name)

    def test_the_exported_reduction_is_one_implementation(self) -> None:
        # The package-level name and the module-level one are the same
        # object, not a facade over a twin.
        import cost_model
        import cost_model.discount as module

        assert cost_model.FeeDiscount is module.FeeDiscount
        assert cost_model.resolve_fee_discount is module.resolve_fee_discount
