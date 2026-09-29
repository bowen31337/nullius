"""Feature 312: on the venue's grids, or refused before anything is sent.

app_spec.xml, "Order Routing & Venue Filters", feature 312: *System
rejects an order submission not rounded to the venue step size and tick
size.*  ``docs/alpha-engine-prd.md`` C9 names the two grids and the law
behind them: *"Read ``LOT_SIZE``, ``NOTIONAL``, ``PRICE_FILTER``,
``stepSize``, ``tickSize`` from ``exchangeInfo`` at startup and daily.
Never hardcode."*

The tests below are organised around the sentence's two grids, because
each can be missed while the other is hit:

* **not rounded to the venue step size** — a quantity off the
  ``LOT_SIZE`` grid is refused, naming the quantity, the step and the
  two nearest values on the grid;
* **and tick size** — a price off the ``PRICE_FILTER`` grid is refused
  the same way.

And around the four shape decisions that make the rejection honest:

* **the grids arrive as feature 310's fetched value** — never literals,
  never defaulted: a symbol the current version does not carry and a
  filter the venue never stated are both refused, not waved through;
* **the arithmetic is exact** — :class:`decimal.Decimal` modulo, with
  floats refused by name so a submission the venue would book can never
  be refused by a representation error;
* **two grids and only two** — the venue's own min/max bounds and
  feature 313's notional floor are not this sentence's;
* **the verdict is pure** — no clock, no I/O, no store, so a restarted
  router re-judging an order agrees with the process it replaced.

No test needs a database for the arithmetic (the two store-backed tests
use the isolated ``DATABASE_URL`` every test gets).  The judgment is a
pure function of the terms and the fetched filters — the suite pins
that too, by deleting ``DATABASE_URL`` and judging anyway.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import router as member
from router.errors import (
    CLIENT_ORDER_ID_CODE,
    CROSS_MARGIN_CODE,
    ORDER_POSTURE_CODE,
    ORDER_ROUNDING_CODE,
    ORDER_SUBMISSION_UNHEALTHY_CODE,
    RATE_LIMITED_CODE,
    RETRY_BACKOFF_CODE,
    SUBMISSION_RESULT_CODE,
    WEIGHT_BUCKET_CODE,
    WEIGHT_SCHEDULE_CODE,
    RouterClientOrderIdError,
    RouterCrossMarginError,
    RouterError,
    RouterFilterError,
    RouterOrderPostureError,
    RouterOrderRoundingError,
    RouterRateLimitError,
    RouterStoreError,
    RouterSubmissionHealthError,
    RouterSubmissionResultError,
)
from router.exchange_info import RouterSymbolFilters, resolve_router_filters
from router.rounding import RoundedOrder, require_rounded_order
from router.store import RouterExchangeInfoStore

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Feature 310's own value for the fixture document's BTCUSDT row, built
#: directly so the arithmetic tests do not depend on the resolver, and
#: spelled exactly as the venue spells it — trailing zeros and all — so
#: the messages these tests read carry the venue's own spellings.
BTC_FILTERS = RouterSymbolFilters(
    symbol="BTCUSDT",
    step_size="0.00001000",
    min_qty="0.00001000",
    max_qty="9000.00000000",
    tick_size="0.01000000",
    min_price="0.01000000",
    max_price="1000000.00000000",
    min_notional="5.00000000",
)

#: A quantity and a price that sit on both of the fixture's grids: the
#: sentence's admissible case, the submission the gate answers.
ON_GRID_QUANTITY = "0.50000000"
ON_GRID_PRICE = "50000.01000000"


def _ask(
    quantity: object = ON_GRID_QUANTITY,
    price: object = ON_GRID_PRICE,
    filters: object = BTC_FILTERS,
    symbol: str = "BTCUSDT",
):
    """One ask of feature 312's verb, with the admissible defaults swapped."""
    return require_rounded_order(
        symbol=symbol, quantity=quantity, price=price, filters=filters
    )


# =============================================================================
# "rejects an order submission not rounded to the venue step size"
# =============================================================================


class TestTheQuantityMustSitOnTheStepGrid:
    """The quantity is judged against ``LOT_SIZE.stepSize``, exactly."""

    def test_a_quantity_on_the_grid_is_answered(self) -> None:
        order = _ask()
        assert isinstance(order, RoundedOrder)

    def test_half_a_step_off_is_refused(self) -> None:
        # The smallest miss a grid can express: half of one step.  The
        # venue would return this order unbooked; the gate refuses it
        # before a single weight unit is spent on it.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity="0.000005")
        message = str(raised.value)
        assert message.startswith(f"{ORDER_ROUNDING_CODE}:")
        assert "quantity" in message
        assert "0.000005" in message
        assert "step size" in message
        assert "LOT_SIZE.stepSize" in message
        assert "BTCUSDT" in message
        assert "(feature 312)" in message

    def test_the_refusal_names_the_two_nearest_values_on_the_grid(
        self,
    ) -> None:
        # The repair is one rounding either neighbour states, and the
        # choosing is the sizing step's — the refusal supplies the two
        # candidates, computed by subtraction so the message itself can
        # never carry a rounding of its own.
        quantity, step = Decimal("0.5000005"), Decimal("0.00001000")
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity="0.5000005")
        message = str(raised.value)
        remainder = quantity % step
        below = quantity - remainder
        assert str(below) in message
        assert str(below + step) in message
        assert "round" in message

    def test_below_one_whole_step_names_zero_and_the_step(self) -> None:
        # A quantity smaller than its own grid: the neighbours are zero
        # and one step.  Zero is named honestly (and spelled plainly,
        # not as Decimal's ``0E-8``) even though no venue would book it
        # — whether the floor is admissible is the venue's bound and
        # feature 313's floor, not this gate's.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity="0.000005")
        message = str(raised.value)
        assert "Decimal('0') and Decimal('0.00001000')" in message

    def test_one_step_satoshi_off_at_the_top_of_the_range(self) -> None:
        # From dust to the top of the venue's own range the rule is the
        # same rule: only the exact modulo decides, never the scale.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity="9000.00000001")
        assert "9000.00000001" in str(raised.value)

    def test_a_submission_wrong_on_both_grids_is_refused_for_the_quantity(
        self,
    ) -> None:
        # The refusals run in a fixed order — the sentence names the
        # step size first — so two operators reading one refusal read
        # the same repair.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity="0.5000005", price="50000.015")
        message = str(raised.value)
        assert "quantity" in message
        assert "price" not in message

    def test_the_venue_never_sees_the_adjustment(self) -> None:
        # The gate rounds nothing: there is no nearest-value answer, no
        # floor, no ceiling helper anywhere in the module, because a
        # quantity silently adjusted is a position the book never
        # decided to hold.
        import router.rounding as module

        assert module.__all__ == ["RoundedOrder", "require_rounded_order"]
        helpers = [
            name
            for name in vars(module)
            if name.startswith(("round_", "nearest", "floor", "ceil"))
        ]
        assert helpers == []


class TestTheArithmeticIsExact:
    """Decimal modulo, not float — decimalisation happens here."""

    def test_a_third_of_a_decimal_is_on_the_grid(self) -> None:
        # The canonical float trap: ``0.3 % 0.1`` is 0.0999... in
        # binary, and a gate that read floats would refuse a submission
        # the venue would book.  Exact decimals put the boundary where
        # the venue puts it.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.1",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional=None,
        )
        order = _ask(quantity="0.3", price="50000.01", filters=filters)
        assert order.quantity == Decimal("0.3")

    def test_trailing_zeros_are_the_same_value(self) -> None:
        # The venue spells eight decimals; the sizing path may spell
        # fewer.  The judgment is over values, not spellings.
        short = _ask(quantity="0.5")
        long = _ask(quantity="0.50000000")
        assert short == long
        assert short.quantity == long.quantity == Decimal("0.5")

    def test_scientific_notation_is_judged_by_its_value(self) -> None:
        # Decimal arithmetic produces exponents lawfully; a spelling
        # with one is still the exact same decimal.
        assert _ask(quantity="5E-1") == _ask(quantity="0.5")
        assert _ask(quantity="5e-1") == _ask(quantity="0.5")

    @pytest.mark.parametrize("bad", [0.5, 50000.01, 1e-5, 3, True])
    def test_a_float_or_int_quantity_is_refused_by_name(
        self, bad: object
    ) -> None:
        # A float is a binary approximation of a decimal no venue ever
        # sent — ``0.1`` as a float is not on a ``0.1`` grid — and a
        # bare number states no spelling the venue could read.  The
        # value is refused rather than read approximately.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity=bad)
        message = str(raised.value)
        assert message.startswith(f"{ORDER_ROUNDING_CODE}:")
        assert "quantity" in message
        assert "Decimal" in message

    @pytest.mark.parametrize("bad", [0.01, 50000.5, 3, False])
    def test_a_float_or_int_price_is_refused_by_name(self, bad: object) -> None:
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(price=bad)
        assert "price" in str(raised.value)

    @pytest.mark.parametrize("bad", [0.001, 1e-5, 1, True])
    def test_a_float_or_int_grid_is_refused_by_name(self, bad: object) -> None:
        # The filters value validates its symbol but carries its fields
        # verbatim, so a hand-built value with a numeric grid reaches
        # this gate — and is refused here, by name.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size=bad,
            min_qty=None,
            max_qty=None,
            tick_size="0.01000000",
            min_price=None,
            max_price=None,
            min_notional=None,
        )
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(filters=filters)
        assert "step size" in str(raised.value)

    @pytest.mark.parametrize(
        "bad", ["NaN", "nan", "sNaN", "Infinity", "-Infinity", "+Infinity"]
    )
    def test_a_non_finite_decimal_is_refused(self, bad: str) -> None:
        # These *parse* as decimals; a size or a grid that is not a
        # number cannot be a multiple of anything.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity=bad)
        assert "finite" in str(raised.value)

    @pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
    def test_a_non_finite_decimal_value_is_refused(self, bad: Decimal) -> None:
        with pytest.raises(RouterOrderRoundingError):
            _ask(quantity=bad)

    @pytest.mark.parametrize("bad", ["abc", "0.5.0", "", " ", "1,5"])
    def test_a_string_that_is_not_a_decimal_is_refused(self, bad: str) -> None:
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity=bad)
        message = str(raised.value)
        assert "not a decimal" in message
        assert repr(bad) in message

    def test_a_decimal_quantity_is_accepted_and_kept_exact(self) -> None:
        # The sizing path computes in decimals; the gate reads its own
        # kind back, exactly.
        order = _ask(quantity=Decimal("0.5"), price=Decimal("50000.01"))
        assert order.quantity == Decimal("0.5")
        assert order.price == Decimal("50000.01")
        assert order == _ask()


# =============================================================================
# "and tick size"
# =============================================================================


class TestThePriceMustSitOnTheTickGrid:
    """The price is judged against ``PRICE_FILTER.tickSize``, the same way."""

    def test_a_price_off_the_tick_is_refused(self) -> None:
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(price="50000.015")
        message = str(raised.value)
        assert message.startswith(f"{ORDER_ROUNDING_CODE}:")
        assert "price" in message
        assert "50000.015" in message
        assert "tick size" in message
        assert "PRICE_FILTER.tickSize" in message
        assert "BTCUSDT" in message
        assert "(feature 312)" in message

    def test_the_refusal_names_the_two_nearest_ticks(self) -> None:
        price, tick = Decimal("50000.015"), Decimal("0.01000000")
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(price="50000.015")
        message = str(raised.value)
        remainder = price % tick
        below = price - remainder
        assert str(below) in message
        assert str(below + tick) in message

    def test_a_sub_tick_fraction_is_refused(self) -> None:
        with pytest.raises(RouterOrderRoundingError):
            _ask(price="50000.005")

    def test_a_whole_number_price_is_on_the_tick_grid(self) -> None:
        # An integer price is a multiple of any decimal tick that
        # divides it exactly — spelled without a fraction, still on the
        # grid, because the judgment is over values.
        assert _ask(price="50000").price == Decimal(50000)

    def test_a_good_quantity_does_not_excuse_a_bad_price(self) -> None:
        # Each grid can be hit while the other is missed; the sentence
        # requires both.
        with pytest.raises(RouterOrderRoundingError):
            _ask(quantity="0.5", price="50000.015")


# =============================================================================
# The grids arrive as feature 310's fetched value
# =============================================================================


class TestTheGridsComeFromTheFetchedFilters:
    """Feature 312 depends on 310, and the dependency is the value itself."""

    def test_judges_against_the_fetched_document(
        self, exchange_info_document: dict
    ) -> None:
        filters = resolve_router_filters(exchange_info_document)["BTCUSDT"]
        order = _ask(filters=filters)
        assert order.step_size == Decimal("0.00001000")
        assert order.tick_size == Decimal("0.01000000")
        with pytest.raises(RouterOrderRoundingError):
            _ask(quantity="0.5000005", filters=filters)

    def test_one_symbols_grid_is_not_anothers(
        self, exchange_info_document: dict
    ) -> None:
        # BTCUSDT steps by 0.00001 and ETHUSDT by 0.0001 in the fixture:
        # a quantity on the first grid is off the second, which is the
        # whole reason the filters travel with the symbol they name.
        filters = resolve_router_filters(exchange_info_document)
        assert _ask(quantity="0.00005", price="0.02", filters=filters["BTCUSDT"])
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity="0.00005", price="0.02", filters=filters["ETHUSDT"])
        assert "ETHUSDT" in str(raised.value)

    def test_the_stores_verbatim_columns_feed_the_gate_exactly(
        self, exchange_info_document: dict, test_database_url: str
    ) -> None:
        # The full 310 → 312 path: a recorded fetch, read back through
        # the store's TEXT columns, decimalised into a verdict.  The
        # venue's spelling survives the round trip un-coerced.
        store = RouterExchangeInfoStore(test_database_url)
        store.record(
            exchange_info_document, fetched_at=datetime(2026, 9, 25, tzinfo=UTC)
        )
        filters = store.filters_for("BTCUSDT")
        assert filters is not None
        order = _ask(filters=filters)
        assert order.step_size == Decimal("0.00001000")
        assert order.tick_size == Decimal("0.01000000")
        with pytest.raises(RouterOrderRoundingError):
            _ask(quantity="0.5000005", filters=filters)

    def test_a_symbol_the_current_version_does_not_carry(
        self, exchange_info_document: dict, test_database_url: str
    ) -> None:
        # What ``filters_for`` answers for an unlisted symbol is None,
        # and the gate refuses that ask rather than improvising a grid.
        store = RouterExchangeInfoStore(test_database_url)
        store.record(
            exchange_info_document, fetched_at=datetime(2026, 9, 25, tzinfo=UTC)
        )
        assert store.filters_for("SOLUSDT") is None
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(symbol="SOLUSDT", filters=store.filters_for("SOLUSDT"))
        message = str(raised.value)
        assert "no exchangeInfo filters" in message
        assert "SOLUSDT" in message


class TestAnAbsentGridIsRefusedNotDefaulted:
    """No LOT_SIZE / PRICE_FILTER means unjudgeable, not unconstrained."""

    def test_no_filters_at_all_is_refused(self) -> None:
        # A store with no version yet, or a symbol the current version
        # dropped: the honest answer is refusal, never a fallback to an
        # older version's grid or an invented one.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(filters=None)
        message = str(raised.value)
        assert message.startswith(f"{ORDER_ROUNDING_CODE}:")
        assert "no exchangeInfo filters" in message
        assert "BTCUSDT" in message

    def test_a_venue_that_states_no_step_size_is_refused(self) -> None:
        # The XRPUSDT shape feature 310's own suite pins: a symbol with
        # a LOT_SIZE and nothing else.
        document = {
            "symbols": [
                {
                    "symbol": "XRPUSDT",
                    "filters": [
                        {
                            "filterType": "LOT_SIZE",
                            "stepSize": "1",
                            "minQty": "1",
                            "maxQty": "1000000",
                        }
                    ],
                }
            ]
        }
        filters = resolve_router_filters(document)["XRPUSDT"]
        assert filters.step_size == "1"
        assert filters.tick_size is None
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(symbol="XRPUSDT", quantity="100", price="0.5", filters=filters)
        message = str(raised.value)
        assert "no tick size" in message
        assert "PRICE_FILTER" in message
        assert "XRPUSDT" in message

    def test_a_venue_that_states_no_tick_size_is_refused(self) -> None:
        document = {
            "symbols": [
                {
                    "symbol": "XRPUSDT",
                    "filters": [
                        {
                            "filterType": "PRICE_FILTER",
                            "tickSize": "0.0001",
                            "minPrice": "0.0001",
                            "maxPrice": "1000",
                        }
                    ],
                }
            ]
        }
        filters = resolve_router_filters(document)["XRPUSDT"]
        assert filters.step_size is None
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(symbol="XRPUSDT", quantity="100", price="0.5", filters=filters)
        message = str(raised.value)
        assert "no step size" in message
        assert "LOT_SIZE" in message

    def test_defaulting_a_grid_is_the_hardcode_feature_311_forbids(
        self,
    ) -> None:
        # The refusal says so itself, because the temptation it refuses
        # is the category's own named prohibition.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size=None,
            min_qty=None,
            max_qty=None,
            tick_size="0.01000000",
            min_price=None,
            max_price=None,
            min_notional=None,
        )
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(filters=filters)
        message = str(raised.value)
        assert "hardcoded venue constant" in message
        assert "feature 311" in message


class TestTheFiltersAreFeature310sValue:
    """The grids arrive as the fetched value or they do not arrive at all."""

    @pytest.mark.parametrize(
        "bad", [{"stepSize": "0.001"}, "0.001", 310, ("step_size", "0.001")]
    )
    def test_not_the_fetched_value_is_refused_by_name(
        self, bad: object
    ) -> None:
        # A raw mapping or a bare string is exactly the shape a caller
        # reaching for a hardcoded constant would hand — and there is no
        # door here it fits through.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(filters=bad)
        message = str(raised.value)
        assert "RouterSymbolFilters" in message
        assert type(bad).__name__ in message

    def test_filters_for_another_symbol_are_refused(self) -> None:
        # A quantity judged against another symbol's step size is a
        # verdict about the wrong instrument.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(symbol="ETHUSDT", filters=BTC_FILTERS)
        message = str(raised.value)
        assert "ETHUSDT" in message
        assert "BTCUSDT" in message

    def test_the_symbols_are_compared_verbatim(self) -> None:
        # One symbol, one spelling, one grid — the rule features 316
        # and 317 hold the same term to.  A case-folded near miss is a
        # different leg, not the same one.
        with pytest.raises(RouterOrderRoundingError):
            _ask(symbol="btcusdt", filters=BTC_FILTERS)

    @pytest.mark.parametrize("bad", ["", "   ", None, 312, b"BTCUSDT"])
    def test_a_symbol_that_names_no_leg_is_refused(self, bad: object) -> None:
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(symbol=bad)
        message = str(raised.value)
        assert "symbol" in message
        assert "non-empty" in message

    def test_the_refusals_run_in_a_fixed_order(self) -> None:
        # Identity before content, the venue's standing facts before the
        # submission's own terms — the same determinism feature 315's
        # gate keeps, so two operators read the same repair.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(symbol="ETHUSDT", quantity=0.5, filters=BTC_FILTERS)
        assert "ETHUSDT" in str(raised.value)  # the mismatch, not the float
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(
                quantity=0.5,
                filters=RouterSymbolFilters(
                    symbol="BTCUSDT",
                    step_size="0.00001000",
                    min_qty=None,
                    max_qty=None,
                    tick_size=None,
                    min_price=None,
                    max_price=None,
                    min_notional=None,
                ),
            )
        assert "tick size" in str(raised.value)  # the grid, not the float


# =============================================================================
# Two grids, and only two
# =============================================================================


class TestTwoGridsAndOnlyTwo:
    """The sentence names the step and the tick; the rest is not its."""

    def test_below_the_venues_minimum_quantity_is_not_this_gates_refusal(
        self,
    ) -> None:
        # minQty is a bound the venue states and enforces; feature 310
        # persisted it for whatever later feature's sentence names it.
        # This gate judges the grid, and 0.00002 is on it.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.00001000",
            min_qty="1.00000000",
            max_qty="2.00000000",
            tick_size="0.01000000",
            min_price="100.00000000",
            max_price="200.00000000",
            min_notional="1000.00000000",
        )
        order = _ask(quantity="0.00002", price="0.02", filters=filters)
        assert order.quantity == Decimal("0.00002")

    def test_above_the_venues_maximum_bounds_is_not_this_gates_refusal(
        self,
    ) -> None:
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.00001000",
            min_qty="1.00000000",
            max_qty="2.00000000",
            tick_size="0.01000000",
            min_price="100.00000000",
            max_price="200.00000000",
            min_notional="1000.00000000",
        )
        order = _ask(quantity="9000.0", price="1000000.0", filters=filters)
        assert order.quantity == Decimal("9000.0")

    @pytest.mark.parametrize("bad", ["0", "0.00000000", "-0.5", "-100"])
    def test_a_quantity_that_is_not_a_size_is_refused(self, bad: str) -> None:
        # Positivity is the term's own ground: a leg weighted zero
        # ships no order, and a negative size would be a direction.
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity=bad)
        assert "positive" in str(raised.value)

    @pytest.mark.parametrize("bad", ["0", "0.00", "-0.01", "-50000"])
    def test_a_price_that_is_not_a_price_is_refused(self, bad: str) -> None:
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(price=bad)
        message = str(raised.value)
        assert "positive" in message
        # Positive is arithmetic, not a venue constant restated.
        assert "minPrice" in message

    @pytest.mark.parametrize("bad", ["0", "0.0", "-0.00001"])
    def test_a_step_that_divides_nothing_is_refused(self, bad: str) -> None:
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size=bad,
            min_qty=None,
            max_qty=None,
            tick_size="0.01000000",
            min_price=None,
            max_price=None,
            min_notional=None,
        )
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(filters=filters)
        assert "grid of zero divides nothing" in str(raised.value)

    @pytest.mark.parametrize("bad", ["0", "-0.01"])
    def test_a_tick_that_divides_nothing_is_refused(self, bad: str) -> None:
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.00001000",
            min_qty=None,
            max_qty=None,
            tick_size=bad,
            min_price=None,
            max_price=None,
            min_notional=None,
        )
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(filters=filters)
        assert "grid of zero divides nothing" in str(raised.value)


# =============================================================================
# The shape around the sentence
# =============================================================================


class TestTheActAnswersTheAdmissibleSubmission:
    """The verb returns the verdict, with its terms decimalised beside it."""

    def test_the_terms_ride_beside_the_verdict(self) -> None:
        # A verdict alone could not say *what* was admitted or against
        # *which grids*; the value carries both, the audit shape
        # features 316 and 314 state for their own verdicts.
        order = _ask()
        assert order.symbol == "BTCUSDT"
        assert order.quantity == Decimal("0.5")
        assert order.price == Decimal("50000.01")
        assert order.step_size == Decimal("0.00001000")
        assert order.tick_size == Decimal("0.01000000")

    def test_the_answer_is_decimalised_for_whatever_reads_it_next(
        self,
    ) -> None:
        # Feature 313's notional is one multiply away, and it multiplies
        # *these* fields rather than re-parsing the spelling.
        order = _ask()
        assert isinstance(order.quantity, Decimal)
        assert isinstance(order.price, Decimal)
        assert order.quantity * order.price == Decimal("25000.005")

    def test_the_verdict_is_frozen_and_hashable(self) -> None:
        import dataclasses

        order = _ask()
        assert dataclasses.is_dataclass(order)
        with pytest.raises(dataclasses.FrozenInstanceError):
            order.quantity = Decimal(1)  # type: ignore[misc]
        assert {order: 1}[order] == 1

    def test_resolving_is_deterministic(self) -> None:
        first, second = _ask(), _ask()
        assert first == second
        assert hash(first) == hash(second)

    def test_the_verb_and_direct_construction_agree(self) -> None:
        assert _ask() == RoundedOrder(
            symbol="BTCUSDT",
            quantity="0.5",
            price="50000.01",
            step_size="0.00001000",
            tick_size="0.01000000",
        )

    def test_direct_construction_re_judges_the_grids(self) -> None:
        # A value built by hand or reconstructed from a record gets the
        # same judgment the verb applies — a value that claimed
        # roundedness its own terms contradict cannot exist.
        with pytest.raises(RouterOrderRoundingError):
            RoundedOrder(
                symbol="BTCUSDT",
                quantity="0.5000005",
                price="50000.01",
                step_size="0.00001000",
                tick_size="0.01000000",
            )

    def test_a_refused_ask_leaves_nothing_behind(self) -> None:
        # There is nothing to leave behind — no scope, no table, no
        # registry — and this pins that the refusal is a raise and not
        # a recorded fallback: the ask either answers or does not exist.
        with pytest.raises(RouterOrderRoundingError):
            _ask(quantity="0.5000005")
        assert _ask().quantity == Decimal("0.5")


class TestTheVerbAdmitsExactlyTheFourTerms:
    """No literal grids, no defaults — feature 311's law, made structural."""

    def test_the_signature_is_exactly_the_four_terms(self) -> None:
        signature = inspect.signature(require_rounded_order)
        assert set(signature.parameters) == {"symbol", "quantity", "price", "filters"}

    def test_every_term_is_a_required_keyword(self) -> None:
        # A default would be this module naming a leg, a size, a price
        # or a grid the deployment never stated — the law feature 316's
        # own ``rebalance_ts`` states for its term.
        signature = inspect.signature(require_rounded_order)
        for name in signature.parameters:
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default is inspect.Parameter.empty, name
        with pytest.raises(TypeError):
            require_rounded_order("BTCUSDT", "0.5", "50000.01", BTC_FILTERS)  # type: ignore[misc]

    def test_there_is_no_parameter_a_literal_grid_could_be_handed_to(
        self,
    ) -> None:
        # The caller who reaches for a hardcoded constant has nowhere to
        # put it: the grids arrive inside feature 310's value or not at
        # all.
        with pytest.raises(TypeError):
            _ask(step_size="0.001")  # type: ignore[misc]

    def test_a_symbol_can_be_re_stated_stripped(self) -> None:
        # Stripped, otherwise verbatim — the same rule 316 and 317 hold
        # the term to, so one leg cannot wear two names.
        assert _ask(symbol="  BTCUSDT  ").symbol == "BTCUSDT"


class TestTheErrorVocabulary:
    """Feature 312's refusal is its own class with its own greppable word."""

    def test_the_code_is_the_one_the_messages_open_with(self) -> None:
        with pytest.raises(RouterOrderRoundingError) as raised:
            _ask(quantity="0.5000005")
        assert str(raised.value).startswith(f"{ORDER_ROUNDING_CODE}:")
        assert ORDER_ROUNDING_CODE == "order_rounding"

    def test_it_is_not_the_sibling_codes(self) -> None:
        # One grep apart, deliberately: the faults name documents,
        # deployments, orders, budgets and waits, and an operator sent
        # from one to the other would edit the wrong file.
        for sibling in (
            CLIENT_ORDER_ID_CODE,
            CROSS_MARGIN_CODE,
            ORDER_POSTURE_CODE,
            ORDER_SUBMISSION_UNHEALTHY_CODE,
            RATE_LIMITED_CODE,
            RETRY_BACKOFF_CODE,
            SUBMISSION_RESULT_CODE,
            WEIGHT_BUCKET_CODE,
            WEIGHT_SCHEDULE_CODE,
        ):
            assert ORDER_ROUNDING_CODE != sibling

    def test_it_is_a_router_error_and_its_own_sibling(self) -> None:
        # Catchable through the member's one base, and *not* an
        # instance of any fault it must not be mistaken for.
        with pytest.raises(RouterError) as raised:
            _ask(quantity="0.5000005")
        for unrelated in (
            RouterFilterError,
            RouterStoreError,
            RouterSubmissionHealthError,
            RouterClientOrderIdError,
            RouterRateLimitError,
            RouterSubmissionResultError,
            RouterCrossMarginError,
            RouterOrderPostureError,
        ):
            assert not issubclass(RouterOrderRoundingError, unrelated)
            assert not isinstance(raised.value, unrelated)
            assert not issubclass(unrelated, RouterOrderRoundingError)

    def test_a_bad_document_is_not_a_bad_order(self) -> None:
        # The split the category's whole shape turns on: the filter
        # fault refuses a *document* that is not a well-formed
        # exchangeInfo; this fault refuses an *order* against one that
        # is.  One bad fetch, many bad orders, and the repairs differ.
        with pytest.raises(RouterFilterError):
            resolve_router_filters("not json at all {{{")
        with pytest.raises(RouterOrderRoundingError):
            _ask(quantity="0.5000005")

    def test_it_is_not_the_posture_fault(self) -> None:
        # The fine split between two facts about one order: posture
        # refuses durations the crossing choice cannot read; this
        # refuses values the venue's grids cannot book.
        assert not issubclass(RouterOrderRoundingError, RouterOrderPostureError)
        assert not issubclass(RouterOrderPostureError, RouterOrderRoundingError)

    def test_it_is_not_the_placement_fault(self) -> None:
        # Chronological, not taxonomic: a submission this class refused
        # never reached the placement ask, so no row ever existed.
        assert not issubclass(
            RouterOrderRoundingError, RouterSubmissionResultError
        )
        assert not issubclass(
            RouterSubmissionResultError, RouterOrderRoundingError
        )


class TestTheMemberStillRegistersOneComponent:
    """Feature 312 adds a module and a class — no component, no table."""

    def test_exactly_one_builder(self) -> None:
        assert [name for name in dir(member) if name.startswith("build_")] == [
            "build_router_exchange_info_store"
        ]

    def test_the_member_exports_the_feature_312_names(self) -> None:
        # Both halves, the code token and the class: one without the
        # other is a refusal no caller can catch by name.
        for name in (
            "ORDER_ROUNDING_CODE",
            "RoundedOrder",
            "RouterOrderRoundingError",
            "require_rounded_order",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_member_still_exports_its_other_decisions(self) -> None:
        assert "require_isolated_margin" in member.__all__
        assert "resolve_order_posture" in member.__all__
        assert "derive_client_order_id" in member.__all__
        assert "RouterSymbolFilters" in member.__all__


class TestTheJudgmentIsPure:
    """No clock, no I/O, no store — the same ask answers the same verdict."""

    def test_the_judgment_reads_no_clock_of_its_own(self) -> None:
        import router.rounding as module

        tree = ast.parse(inspect.getsource(module))
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"now", "perf_counter", "monotonic"}
        ]
        assert reads == []

    def test_the_module_imports_no_store(self) -> None:
        # Nothing to persist, and the caller holds the filters it read:
        # a gate that fetched its own would be a second, racing reader
        # on the order path.  ``decimal`` is the module's own subject.
        import router.rounding as module

        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in (
            "sqlite3",
            "os",
            "socket",
            "pathlib",
            "subprocess",
            "time",
            "random",
        ):
            assert forbidden not in imported, forbidden
        assert "decimal" in imported
        assert "dataclasses" in imported

    def test_the_judgment_needs_no_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The feature's own shape: nothing to persist, nothing to
        # compose.  If this ever needs a store, this test fails.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert _ask().quantity == Decimal("0.5")

    def test_two_asks_of_one_order_agree(self) -> None:
        # What a restarted router re-derives is what the process it
        # replaced derived: the terms and the filters are the whole of
        # the decision.
        first = _ask()
        second = RoundedOrder(
            symbol="BTCUSDT",
            quantity="0.5",
            price="50000.01",
            step_size="0.00001000",
            tick_size="0.01000000",
        )
        assert first == second
        assert first.quantity == second.quantity


class TestTheCrossProcessCase:
    """Two routers judge one deployment's orders; the verdict is the same."""

    _SCRIPT = """
from decimal import Decimal

from router.errors import RouterOrderRoundingError
from router.exchange_info import RouterSymbolFilters
from router.rounding import require_rounded_order

filters = RouterSymbolFilters(
    symbol="BTCUSDT",
    step_size="0.00001000",
    min_qty=None,
    max_qty=None,
    tick_size="0.01000000",
    min_price=None,
    max_price=None,
    min_notional=None,
)
order = require_rounded_order(
    symbol="BTCUSDT", quantity="0.5", price="50000.01", filters=filters
)
print(order.quantity == Decimal("0.5"))
print(order.price == Decimal("50000.01"))
print(order == require_rounded_order(
    symbol="BTCUSDT",
    quantity=Decimal("0.5"),
    price=Decimal("50000.01"),
    filters=filters,
))
try:
    require_rounded_order(
        symbol="BTCUSDT", quantity="0.5000005", price="50000.01", filters=filters
    )
except RouterOrderRoundingError as exc:
    print(str(exc).startswith({code!r}))
try:
    require_rounded_order(
        symbol="BTCUSDT", quantity=0.5, price="50000.01", filters=filters
    )
except RouterOrderRoundingError as exc:
    print("binary approximation" in str(exc))
"""

    def _run(self, script: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "router" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_another_interpreter_answers_the_same_verdict(self) -> None:
        script = self._SCRIPT.format(code=ORDER_ROUNDING_CODE)
        finished = self._run(script)
        assert finished.returncode == 0, finished.stderr
        quantity, price, agree, refused, float_refused = (
            finished.stdout.strip().splitlines()
        )
        assert quantity == "True"
        assert price == "True"
        assert agree == "True"
        assert refused == "True"
        assert float_refused == "True"
