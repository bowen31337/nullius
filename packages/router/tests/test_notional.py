"""Feature 313: above the venue's floor, or refused before anything is sent.

app_spec.xml, "Order Routing & Venue Filters", feature 313: *System rejects
an order falling below the venue minimum notional, which returns a
``below_min_notional`` error message.*  ``docs/alpha-engine-prd.md`` C9
names the field beside the two grids feature 312 judges: *"Read ``LOT_SIZE``,
``NOTIONAL``, ``PRICE_FILTER``, ``stepSize``, ``tickSize`` from
``exchangeInfo`` at startup and daily. Never hardcode."*

The tests below are organised around the sentence's own three claims,
because each is separately checkable:

* **rejects an order falling below the venue minimum notional** — the
  sentence's judgment, and the case that makes this a different fault from
  feature 312's: an order whose quantity sits on the step grid and whose
  price sits on the tick grid, and whose *value* is still too small;
* **returns a below_min_notional error message** — the token is the
  sentence's own spelling, on a class of its own, so a caller can catch the
  refusal by name and an operator can grep it;
* **the floor comes from the fetched document** — feature 310's
  ``min_notional`` or no floor at all; a venue that states no minimum
  leaves the order unjudgeable, and unjudgeable is refused, never
  defaulted.

And around the three shape decisions that keep the judgment honest:

* **the arithmetic is exact** — the product is computed under a widened
  decimal context rather than at the ambient 28-digit precision, so a
  submission the venue would book can never be refused by a representation
  error;
* **the dependency on 312 is the value itself** — the verb takes feature
  312's ``RoundedOrder``, so there is no way to ask this gate about an
  order that never passed the grids;
* **the verdict is pure** — no clock, no I/O, no store, so a restarted
  router re-judging an order agrees with the process it replaced.

No test needs a database for the arithmetic (the store-backed test uses the
isolated ``DATABASE_URL`` every test gets).  The judgment is a pure function
of the order and the fetched floor — the suite pins that too, by deleting
``DATABASE_URL`` and judging anyway.
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
    BELOW_MIN_NOTIONAL_CODE,
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
    RouterBelowMinNotionalError,
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
from router.notional import OrderValue, require_min_notional
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

#: Feature 310's own value for the fixture document's ETHUSDT row — the
#: second leg, whose floor (10.00) differs from BTCUSDT's (5.00), so "one
#: symbol's floor is not another's" is a testable claim rather than an
#: assertion about a constant.
ETH_FILTERS = RouterSymbolFilters(
    symbol="ETHUSDT",
    step_size="0.00010000",
    min_qty="0.00010000",
    max_qty="9000.00000000",
    tick_size="0.01000000",
    min_price="0.01000000",
    max_price="1000000.00000000",
    min_notional="10.00000000",
)

#: A quantity and a price that sit on both of the fixture's grids *and*
#: multiply to well above the fixture's floor: the sentence's admissible
#: case.
ON_GRID_QUANTITY = "0.50000000"
ON_GRID_PRICE = "50000.01000000"


def _order(
    quantity: object = ON_GRID_QUANTITY,
    price: object = ON_GRID_PRICE,
    symbol: str = "BTCUSDT",
) -> RoundedOrder:
    """Feature 312's verdict for one set of terms — this gate's input.

    Built through feature 312's own gate against the fixture filters for
    the symbol, so a test that means to exercise feature 313's *filter*
    validation gets an order this gate can read, rather than one feature
    312 refused first.  The order and the filters are separate arguments of
    :func:`_ask` for exactly that reason.
    """
    return require_rounded_order(
        symbol=symbol,
        quantity=quantity,
        price=price,
        filters=ETH_FILTERS if symbol == "ETHUSDT" else BTC_FILTERS,
    )


def _ask(
    order: object = None,
    filters: object = BTC_FILTERS,
    quantity: object = ON_GRID_QUANTITY,
    price: object = ON_GRID_PRICE,
    symbol: str = "BTCUSDT",
) -> OrderValue:
    """One ask of feature 313's verb, with the admissible defaults swapped.

    ``order`` and ``filters`` are separate parameters on purpose: the order
    is feature 312's verdict over *its* terms, and the filters are feature
    310's value handed to *this* gate — so a test can hand this module a
    filter value feature 312 would never have accepted and see this
    module's own refusal rather than its dependency's.
    """
    if order is None:
        order = _order(quantity=quantity, price=price, symbol=symbol)
    return require_min_notional(order=order, filters=filters)


def _verdict_for(
    symbol: str,
    quantity: object = ON_GRID_QUANTITY,
    price: object = ON_GRID_PRICE,
    *,
    step_size: object = "0.00001000",
    tick_size: object = "0.01000000",
) -> RoundedOrder:
    """Feature 312's verdict for ``symbol``, constructed rather than asked for.

    The three tests that use this one are exercising *feature 313's* own
    filter validation — a symbol this version does not carry, a filters
    value filed under a different spelling — and those asks are ones
    feature 312's gate refuses on the way in.  So the verdict is built
    directly here: feature 312's ``__post_init__`` re-runs the same
    validators and the same two modulo checks, so a hand-built verdict is
    the same kind of value the verb answers, and the terms in these tests
    are on the grids given.  Every other test goes through the real gate.
    """
    return RoundedOrder(
        symbol=symbol,
        quantity=quantity,
        price=price,
        step_size=step_size,
        tick_size=tick_size,
    )


# =============================================================================
# "rejects an order falling below the venue minimum notional"
# =============================================================================


class TestAnOrderBelowTheFloorIsRefused:
    """The value — quantity times price — is judged against the venue's floor."""

    def test_an_order_above_the_floor_is_answered(self) -> None:
        value = _ask()
        assert isinstance(value, OrderValue)
        assert value.value == Decimal("25000.00500")

    def test_an_order_worth_less_than_the_floor_is_refused(self) -> None:
        # The shape the sentence exists for: a perfectly round order whose
        # value is too small.  0.5 BTC at 8.00 is on both of the fixture's
        # grids and worth 4.00, against a floor of 5.00.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="8.00")
        message = str(raised.value)
        assert message.startswith(f"{BELOW_MIN_NOTIONAL_CODE}:")
        assert "4.000" in message
        assert "5.00000000" in message
        assert "BTCUSDT" in message
        assert "NOTIONAL.minNotional" in message
        assert "(feature 313)" in message

    def test_the_refusal_says_this_is_not_a_rounding_repair(self) -> None:
        # The two gates refuse different things and a caller sent to the
        # wrong one would re-round an order that is already round — so the
        # refusal says which repair it is not.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="8.00")
        message = str(raised.value)
        assert "step size" in message
        assert "tick size" in message
        assert "not a rounding repair" in message
        assert "size the leg up" in message

    def test_the_refusal_names_both_terms_of_the_product(self) -> None:
        # The refusal is the *only* place the shortfall lives — a value of
        # this type can never hold a below-floor order, so there is no
        # reading to take off one — which is why it names every number the
        # repair needs: both terms, their product, and the floor.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="8.00")
        message = str(raised.value)
        assert "Decimal('0.5')" in message
        assert "Decimal('8.00')" in message
        assert "Decimal('4.000')" in message
        assert "Decimal('5.00000000')" in message

    def test_an_order_worth_exactly_the_floor_is_admitted(self) -> None:
        # "Falling below" is strict: at the floor is not below it.  0.5 BTC
        # at 10.00 is exactly the fixture's 5.00 floor and the venue books
        # it, so the gate must not refuse it.
        value = _ask(quantity="0.5", price="10.00")
        assert value.value == Decimal("5.000")
        assert value.value == value.min_notional

    def test_one_tick_under_the_floor_is_refused(self) -> None:
        # One tick of price is the smallest step the venue's own grid can
        # express, and it is enough to put the order under the floor.
        with pytest.raises(RouterBelowMinNotionalError):
            _ask(quantity="0.5", price="9.99")

    def test_dust_is_refused(self) -> None:
        # The state the sentence's category exists to prevent, named one
        # layer up in C10 and §13.3: a sub-notional order is not a small
        # position, it is untradeable dust.
        with pytest.raises(RouterBelowMinNotionalError):
            _ask(quantity="0.00001", price="0.01")

    def test_the_room_above_the_floor_is_readable_off_the_value(self) -> None:
        # The repair is arithmetic, so the arithmetic is offered: a sizing
        # step weighing a leg that clears the floor by a hair against one
        # that clears it by a mile reads the difference here.
        assert _ask(quantity="0.5", price="10.00").headroom() == Decimal("0.000")
        assert _ask(quantity="0.5", price="20.00").headroom() == Decimal("5.000")

    def test_the_reading_is_never_negative(self) -> None:
        # A property of the value type rather than a claim about the world:
        # ``__post_init__`` refuses a below-floor order, so a value that
        # exists at all is one that cleared the floor — which is why the
        # reading is *headroom* and there is deliberately no method here
        # reporting a shortfall no value of this type can hold.  The
        # shortfall is in the refusal's own message.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="8.00")
        message = str(raised.value)
        assert "4.000" in message  # the value
        assert "5.00000000" in message  # the floor
        assert not hasattr(OrderValue, "shortfall")
        assert _ask(quantity="0.5", price="10.00").headroom() >= 0

    def test_the_value_is_the_exact_product_of_the_terms(self) -> None:
        value = _ask(quantity="0.5", price="10.00")
        assert value.value == value.quantity * value.price
        assert value.quantity == Decimal("0.5")
        assert value.price == Decimal("10.00")

    def test_a_big_order_is_admitted_whatever_the_bound(self) -> None:
        value = _ask(quantity="9000", price="50000.01")
        assert value.value == Decimal("450000090.00000")

    def test_the_two_gates_are_independent(self) -> None:
        # The load-bearing case: this order passes feature 312's grid gate
        # and fails this one.  A single gate that judged both would have to
        # pick a repair; two gates each name their own.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.1",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional="5.00000000",
        )
        order = require_rounded_order(
            symbol="BTCUSDT", quantity="0.5", price="8.00", filters=filters
        )
        assert order.quantity == Decimal("0.5")
        assert order.price == Decimal("8.00")
        with pytest.raises(RouterBelowMinNotionalError):
            require_min_notional(order=order, filters=filters)


class TestTheArithmeticIsExact:
    """The product is computed at full precision, not at the ambient one."""

    def test_a_product_wider_than_the_ambient_precision_is_exact(self) -> None:
        # The canonical trap, and the reason this module widens its context:
        # ``Decimal.__mul__`` rounds to the module's *ambient* 28 significant
        # digits, so a 19-digit quantity times a 19-digit price is a 38-digit
        # exact product that the ambient context silently truncates to
        # ``1.219326311370217952237463801E+33`` — a value *below* the exact
        # one.  A floor set between the two would see a submission the venue
        # would book refused by a representation error.  Both terms sit on a
        # 0.01 grid, so feature 312 admits the order; this gate must admit it
        # too.
        quantity = "12345678901234567.89"
        price = "98765432109876543.21"
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.01",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional="1219326311370217952237463801111263.5269",
        )
        value = _ask(quantity=quantity, price=price, filters=filters)
        assert value.value == Decimal(
            "1219326311370217952237463801111263.5269"
        )
        # The ambient context's answer is a *different, smaller* number —
        # which is exactly why the widening is load-bearing rather than
        # decorative.
        assert value.value != Decimal(quantity) * Decimal(price)
        assert Decimal(quantity) * Decimal(price) < value.value

    def test_the_widening_does_not_narrow_a_callers_own_context(self) -> None:
        # The local context is entered and left, so a caller that had raised
        # the precision for its own reasons still has it afterwards.
        import decimal

        with decimal.localcontext() as outer:
            outer.prec = 60
            _ask()
            assert decimal.getcontext().prec == 60

    def test_trailing_zeros_in_the_product_are_the_same_value(self) -> None:
        # The venue spells eight decimals and the sizing path may spell
        # fewer; the judgment is over values, not spellings — the rule
        # feature 312's own suite pins for its two grids.
        assert _ask(quantity="0.5", price="10.00").value == Decimal(5)
        assert _ask(quantity="0.50000000", price="10").value == Decimal("5.00000000")

    def test_the_floor_is_read_as_a_value_not_a_spelling(self) -> None:
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.1",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional="5",
        )
        value = _ask(quantity="0.5", price="10.00", filters=filters)
        assert value.min_notional == Decimal("5.00000000")

    @pytest.mark.parametrize("bad", [5.0, 0.01, 1, True])
    def test_a_float_or_int_floor_is_refused_by_name(self, bad: object) -> None:
        # A float is a binary approximation of a decimal no venue ever
        # sent — the rule feature 312 holds its own two grids to, applied
        # to the one number this module reads.  The filters value carries
        # its fields verbatim, so a hand-built value with a numeric floor
        # reaches this gate — and is refused here, by name.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.1",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional=bad,
        )
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="10.00", filters=filters)
        message = str(raised.value)
        assert "minimum notional" in message
        assert "Decimal" in message

    @pytest.mark.parametrize(
        "bad", ["NaN", "nan", "sNaN", "Infinity", "-Infinity", "+Infinity"]
    )
    def test_a_non_finite_floor_is_refused(self, bad: str) -> None:
        # These *parse* as decimals; a floor that is not a number cannot be
        # a floor.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.1",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional=bad,
        )
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="10.00", filters=filters)
        assert "finite" in str(raised.value)

    @pytest.mark.parametrize("bad", ["abc", "5.0.0", "", " ", "1,5"])
    def test_a_string_that_is_not_a_decimal_is_refused(self, bad: str) -> None:
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.1",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional=bad,
        )
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="10.00", filters=filters)
        message = str(raised.value)
        assert "not a decimal" in message
        assert repr(bad) in message

    @pytest.mark.parametrize("bad", ["-5", "-0.00000001"])
    def test_a_negative_floor_is_refused(self, bad: str) -> None:
        # A negative minimum is not a minimum: it would admit every order,
        # including the ones the sentence exists to refuse.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.1",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional=bad,
        )
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="10.00", filters=filters)
        message = str(raised.value)
        assert "must not be negative" in message
        assert "not a minimum" in message

    def test_a_zero_floor_admits_anything(self) -> None:
        # Zero is a *stated* floor and a vacuous one: a venue that publishes
        # a minimum of zero has published a minimum nothing falls below.
        # Refusing the ask would be this module inventing a bound the venue
        # did not state.
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.00001",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional="0",
        )
        value = _ask(quantity="0.00001", price="0.01", filters=filters)
        assert value.min_notional == Decimal(0)
        assert value.value == Decimal("0.0000001")

    def test_a_decimal_floor_is_accepted(self) -> None:
        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.1",
            min_qty=None,
            max_qty=None,
            tick_size="0.01",
            min_price=None,
            max_price=None,
            min_notional=Decimal("5.00000000"),
        )
        assert _ask(quantity="0.5", price="10.00", filters=filters) == _ask(
            quantity="0.5", price="10.00"
        )


# =============================================================================
# "returns a below_min_notional error message"
# =============================================================================


class TestTheErrorVocabulary:
    """Feature 313's refusal is its own class with the sentence's own token."""

    def test_the_code_is_the_one_the_sentence_spells(self) -> None:
        # Not a name coined in the house style: app_spec.xml's sentence says
        # the refusals "return a below_min_notional error message", so an
        # operator who read the spec and greps for that string must find
        # them.
        assert BELOW_MIN_NOTIONAL_CODE == "below_min_notional"

    def test_the_code_is_the_one_the_messages_open_with(self) -> None:
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="8.00")
        assert str(raised.value).startswith(f"{BELOW_MIN_NOTIONAL_CODE}:")

    def test_it_is_not_the_sibling_codes(self) -> None:
        # One grep apart, deliberately: the faults name documents,
        # deployments, orders, budgets, waits and grids, and an operator
        # sent from one to the other would edit the wrong file.
        for sibling in (
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
        ):
            assert BELOW_MIN_NOTIONAL_CODE != sibling

    def test_it_is_a_router_error_and_its_own_sibling(self) -> None:
        # Catchable through the member's one base, and *not* an instance of
        # any fault it must not be mistaken for.
        with pytest.raises(RouterError) as raised:
            _ask(quantity="0.5", price="8.00")
        for unrelated in (
            RouterFilterError,
            RouterStoreError,
            RouterSubmissionHealthError,
            RouterClientOrderIdError,
            RouterRateLimitError,
            RouterSubmissionResultError,
            RouterCrossMarginError,
            RouterOrderPostureError,
            RouterOrderRoundingError,
        ):
            assert not issubclass(RouterBelowMinNotionalError, unrelated)
            assert not isinstance(raised.value, unrelated)
            assert not issubclass(unrelated, RouterBelowMinNotionalError)

    def test_the_grid_fault_is_not_the_floor_fault(self) -> None:
        # The fine split this whole module turns on: an order can be
        # perfectly round and still too small, so a caller catching one
        # must not be told the other.  Both directions.
        with pytest.raises(RouterOrderRoundingError) as grid:
            _order(quantity="0.5000005")
        assert not isinstance(grid.value, RouterBelowMinNotionalError)
        with pytest.raises(RouterBelowMinNotionalError) as floor:
            _ask(quantity="0.5", price="8.00")
        assert not isinstance(floor.value, RouterOrderRoundingError)

    def test_a_bad_document_is_not_a_below_floor_order(self) -> None:
        # The split feature 312's own suite pins one feature over: the
        # filter fault refuses a *document* that is not a well-formed
        # exchangeInfo; this fault refuses an *order* whose value the venue
        # will not book.
        with pytest.raises(RouterFilterError):
            resolve_router_filters("not json at all {{{")
        with pytest.raises(RouterBelowMinNotionalError):
            _ask(quantity="0.5", price="8.00")

    def test_it_is_not_the_risk_members_equity_floor(self) -> None:
        # C10's "equity < 2 x min_notional" halt belongs to the risk member
        # and is a deployment-level stop; this is one order's admissibility.
        # The member owns no other member's vocabulary, so the class is
        # catchable through this member's base alone.
        assert issubclass(RouterBelowMinNotionalError, RouterError)
        assert RouterBelowMinNotionalError.__mro__[1] is RouterError


# =============================================================================
# The floor arrives as feature 310's fetched value
# =============================================================================


class TestTheFloorComesFromTheFetchedFilters:
    """Feature 313 depends on 310, and the dependency is the value itself."""

    def test_judges_against_the_fetched_document(
        self, exchange_info_document: dict
    ) -> None:
        filters = resolve_router_filters(exchange_info_document)["BTCUSDT"]
        value = _ask(quantity="0.5", price="10.00", filters=filters)
        assert value.min_notional == Decimal("5.00000000")
        with pytest.raises(RouterBelowMinNotionalError):
            _ask(quantity="0.5", price="9.99", filters=filters)

    def test_one_symbols_floor_is_not_anothers(
        self, exchange_info_document: dict
    ) -> None:
        # BTCUSDT's fixture floor is 5.00 and ETHUSDT's is 10.00 (spelled
        # with the older MIN_NOTIONAL filter type): a value that clears the
        # first is below the second, which is the whole reason the filters
        # travel with the symbol they name.
        filters = resolve_router_filters(exchange_info_document)
        assert _ask(quantity="0.5", price="10.00", filters=filters["BTCUSDT"])
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(
                quantity="0.5",
                price="10.00",
                symbol="ETHUSDT",
                filters=filters["ETHUSDT"],
            )
        assert "ETHUSDT" in str(raised.value)
        assert "10.00000000" in str(raised.value)

    def test_the_older_min_notional_spelling_is_the_same_floor(
        self, exchange_info_document: dict
    ) -> None:
        # ETHUSDT's fixture carries MIN_NOTIONAL rather than NOTIONAL.  A
        # venue that spells it the old way has not stopped having a minimum
        # order value, and feature 310's narrowing reads both.
        filters = resolve_router_filters(exchange_info_document)["ETHUSDT"]
        assert filters.min_notional == "10.00000000"
        with pytest.raises(RouterBelowMinNotionalError):
            _ask(
                quantity="0.5",
                price="19.99",
                symbol="ETHUSDT",
                filters=filters,
            )

    def test_the_stores_verbatim_columns_feed_the_gate_exactly(
        self, exchange_info_document: dict, test_database_url: str
    ) -> None:
        # The full 310 -> 312 -> 313 path: a recorded fetch, read back
        # through the store's TEXT columns, decimalised into a grid verdict
        # and then into a value verdict.  The venue's spelling survives the
        # round trip un-coerced.
        store = RouterExchangeInfoStore(test_database_url)
        store.record(
            exchange_info_document, fetched_at=datetime(2026, 9, 25, tzinfo=UTC)
        )
        filters = store.filters_for("BTCUSDT")
        assert filters is not None
        order = require_rounded_order(
            symbol="BTCUSDT", quantity="0.5", price="10.00", filters=filters
        )
        value = require_min_notional(order=order, filters=filters)
        assert value.min_notional == Decimal("5.00000000")
        with pytest.raises(RouterBelowMinNotionalError):
            require_min_notional(
                order=require_rounded_order(
                    symbol="BTCUSDT", quantity="0.5", price="9.99", filters=filters
                ),
                filters=filters,
            )

    def test_a_symbol_the_current_version_does_not_carry(
        self, exchange_info_document: dict, test_database_url: str
    ) -> None:
        # What ``filters_for`` answers for an unlisted symbol is None, and
        # the gate refuses that ask rather than improvising a floor.
        store = RouterExchangeInfoStore(test_database_url)
        store.record(
            exchange_info_document, fetched_at=datetime(2026, 9, 25, tzinfo=UTC)
        )
        assert store.filters_for("SOLUSDT") is None
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(
                order=_verdict_for("SOLUSDT"),
                filters=store.filters_for("SOLUSDT"),
            )
        message = str(raised.value)
        assert "no exchangeInfo filters" in message
        assert "SOLUSDT" in message


class TestAnAbsentFloorIsRefusedNotDefaulted:
    """No NOTIONAL / MIN_NOTIONAL means unjudgeable, not unconstrained."""

    def test_no_filters_at_all_is_refused(self) -> None:
        # A store with no version yet, or a symbol the current version
        # dropped: the honest answer is refusal, never a fallback to an
        # older version's floor or an invented one.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(filters=None)
        message = str(raised.value)
        assert message.startswith(f"{BELOW_MIN_NOTIONAL_CODE}:")
        assert "no exchangeInfo filters" in message
        assert "BTCUSDT" in message

    def test_a_venue_that_states_no_notional_is_refused(self) -> None:
        # The XRPUSDT shape feature 310's own suite pins: a symbol with a
        # LOT_SIZE and a PRICE_FILTER and no NOTIONAL at all.
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
                        },
                        {
                            "filterType": "PRICE_FILTER",
                            "tickSize": "0.0001",
                            "minPrice": "0.0001",
                            "maxPrice": "1000",
                        },
                    ],
                }
            ]
        }
        filters = resolve_router_filters(document)["XRPUSDT"]
        assert filters.min_notional is None
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(
                order=_verdict_for(
                    "XRPUSDT",
                    quantity="100",
                    price="0.5",
                    step_size="1",
                    tick_size="0.0001",
                ),
                filters=filters,
            )
        message = str(raised.value)
        assert "no minimum notional" in message
        assert "NOTIONAL" in message
        assert "XRPUSDT" in message

    def test_defaulting_a_floor_is_the_hardcode_feature_311_forbids(
        self,
    ) -> None:
        # The refusal says so itself, because the temptation it refuses is
        # the category's own named prohibition.
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
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(quantity="0.5", price="10.00", filters=filters)
        message = str(raised.value)
        assert "hardcoded venue constant" in message
        assert "feature 311" in message

    def test_a_none_floor_is_not_a_zero_floor(self) -> None:
        # The distinction feature 310's own docstring makes for every field:
        # an absent floor is a fact the order path must be able to tell
        # apart from a value of "0" — one is unjudgeable, the other admits
        # everything.
        absent = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.00001000",
            min_qty=None,
            max_qty=None,
            tick_size="0.01000000",
            min_price=None,
            max_price=None,
            min_notional=None,
        )
        zero = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="0.00001000",
            min_qty=None,
            max_qty=None,
            tick_size="0.01000000",
            min_price=None,
            max_price=None,
            min_notional="0",
        )
        with pytest.raises(RouterBelowMinNotionalError):
            _ask(quantity="0.00001", price="0.01", filters=absent)
        assert _ask(quantity="0.00001", price="0.01", filters=zero).min_notional == 0


class TestTheFiltersAreFeature310sValue:
    """The floor arrives as the fetched value or it does not arrive at all."""

    @pytest.mark.parametrize(
        "bad", [{"minNotional": "5"}, "5.00000000", 313, ("min_notional", "5")]
    )
    def test_not_the_fetched_value_is_refused_by_name(self, bad: object) -> None:
        # A raw mapping or a bare string is exactly the shape a caller
        # reaching for a hardcoded constant would hand — and there is no
        # door here it fits through.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(filters=bad)
        message = str(raised.value)
        assert "RouterSymbolFilters" in message
        assert type(bad).__name__ in message

    def test_filters_for_another_symbol_are_refused(self) -> None:
        # A value judged against another symbol's floor is a verdict about
        # the wrong instrument.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(symbol="ETHUSDT", filters=BTC_FILTERS)
        message = str(raised.value)
        assert "ETHUSDT" in message
        assert "BTCUSDT" in message

    def test_the_symbols_are_compared_verbatim(self) -> None:
        # One symbol, one spelling, one floor — the rule features 312, 316
        # and 317 hold the same term to.  A case-folded near miss is a
        # different leg, not the same one, so an order filed under a
        # re-spelled symbol is refused against the correctly-spelled
        # filters rather than matched onto them.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(order=_verdict_for("btcusdt"), filters=BTC_FILTERS)
        assert "btcusdt" in str(raised.value)
        assert "BTCUSDT" in str(raised.value)

    def test_the_refusals_run_in_a_fixed_order(self) -> None:
        # The order's own identity first, then the venue's standing facts
        # (present, the right value, the right symbol), then its absence —
        # the determinism feature 312's gate keeps, so two operators reading
        # one refusal read the same repair.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(symbol="ETHUSDT", filters=BTC_FILTERS)
        assert "ETHUSDT" in str(raised.value)  # the mismatch, not the floor
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            _ask(
                quantity="0.5",
                price="8.00",
                filters=RouterSymbolFilters(
                    symbol="BTCUSDT",
                    step_size="0.00001000",
                    min_qty=None,
                    max_qty=None,
                    tick_size="0.01000000",
                    min_price=None,
                    max_price=None,
                    min_notional=None,
                ),
            )
        assert "no minimum notional" in str(raised.value)  # the floor, not the value


# =============================================================================
# The dependency on feature 312 is the value itself
# =============================================================================


class TestTheOrderIsFeature312sVerdict:
    """The floor is judged on an order that already passed the grids."""

    @pytest.mark.parametrize(
        "bad",
        [
            None,
            {"quantity": "0.5", "price": "10.00"},
            ("0.5", "10.00"),
            "RoundedOrder",
            312,
        ],
    )
    def test_a_rounding_verdict_this_gate_cannot_read_is_refused(
        self, bad: object
    ) -> None:
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            require_min_notional(order=bad, filters=BTC_FILTERS)
        message = str(raised.value)
        assert "RoundedOrder" in message
        assert type(bad).__name__ in message

    def test_there_is_no_parameter_a_quantity_or_price_could_be_handed_to(
        self,
    ) -> None:
        # The terms arrive inside feature 312's value, so a caller cannot
        # ask this gate about an order that never passed the grids — and
        # cannot hand it a float, which feature 312 refuses one gate
        # earlier.
        with pytest.raises(TypeError):
            require_min_notional(  # type: ignore[misc]
                order=_order(), filters=BTC_FILTERS, quantity="0.5"
            )
        with pytest.raises(TypeError):
            require_min_notional(  # type: ignore[misc]
                order=_order(), filters=BTC_FILTERS, price=10.0
            )

    def test_there_is_no_parameter_a_literal_floor_could_be_handed_to(
        self,
    ) -> None:
        with pytest.raises(TypeError):
            require_min_notional(  # type: ignore[misc]
                order=_order(), reports=5, min_notional="5.00000000"
            )

    def test_the_signature_is_exactly_the_two_terms(self) -> None:
        signature = inspect.signature(require_min_notional)
        assert set(signature.parameters) == {"order", "filters"}

    def test_every_term_is_a_required_keyword(self) -> None:
        # A default would be this module naming an order or a floor the
        # deployment never stated — the law feature 312's own four terms
        # state for theirs.
        signature = inspect.signature(require_min_notional)
        for name in signature.parameters:
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default is inspect.Parameter.empty, name
        with pytest.raises(TypeError):
            require_min_notional(_order(), BTC_FILTERS)  # type: ignore[misc]

    def test_a_float_never_reaches_this_gate(self) -> None:
        # The exactness boundary is feature 312's, one gate earlier: a
        # float quantity or price is refused there, so this module owns no
        # decimalisation of the terms at all.
        with pytest.raises(RouterOrderRoundingError):
            _order(quantity=0.5)
        with pytest.raises(RouterOrderRoundingError):
            _order(price=10.0)


# =============================================================================
# The shape around the sentence
# =============================================================================


class TestTheActAnswersTheAdmissibleOrder:
    """The verb returns the verdict, with its terms beside it."""

    def test_the_terms_ride_beside_the_verdict(self) -> None:
        # A verdict alone could not say *how much* the order is worth or
        # against *what* floor; the value carries both, the audit shape
        # features 312, 314 and 316 state for their own verdicts.
        value = _ask()
        assert value.symbol == "BTCUSDT"
        assert value.quantity == Decimal("0.5")
        assert value.price == Decimal("50000.01")
        assert value.min_notional == Decimal("5.00000000")
        assert value.value == Decimal("25000.005")

    def test_the_order_rides_inside_the_verdict_unrestated(self) -> None:
        # The quantity this value multiplies is *the* quantity the grid
        # gate judged, not a second reading of the same spelling.
        value = _ask()
        assert value.order == _order()
        assert value.order.quantity is value.quantity or (
            value.order.quantity == value.quantity
        )

    def test_the_verdict_is_frozen_and_hashable(self) -> None:
        import dataclasses

        value = _ask()
        assert dataclasses.is_dataclass(value)
        with pytest.raises(dataclasses.FrozenInstanceError):
            value.value = Decimal(1)  # type: ignore[misc]
        assert {value: 1}[value] == 1

    def test_resolving_is_deterministic(self) -> None:
        first, second = _ask(), _ask()
        assert first == second
        assert hash(first) == hash(second)

    def test_the_verb_and_direct_construction_agree(self) -> None:
        assert _ask() == OrderValue(
            order=_order(),
            min_notional="5.00000000",
        )

    def test_direct_construction_computes_the_value_when_omitted(self) -> None:
        value = OrderValue(order=_order(), min_notional="5.00000000")
        assert value.value == Decimal("25000.005")

    def test_a_stated_value_is_checked_against_its_own_terms(self) -> None:
        # A record reconstructed from a log gets the same judgment the verb
        # applies — a value that lies about the order's worth is worse than
        # no value at all.
        assert OrderValue(
            order=_order(),
            min_notional="5.00000000",
            value="25000.005",
        ).value == Decimal("25000.005")
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            OrderValue(
                order=_order(),
                min_notional="5.00000000",
                value="25000.00500" + "1",
            )
        message = str(raised.value)
        assert "stated value" in message
        assert "disagrees with its own terms" in message or "not the worth" in message

    def test_a_stated_zero_value_is_a_stated_value_not_a_sentinel(self) -> None:
        # The not-stated sentinel is ``None`` exactly, and a stated
        # ``Decimal("0")`` is judged like any other stated value — here, it
        # disagrees with the terms and is refused as a lie rather than read
        # as "compute it for me".  A falsy-but-present value swallowed by a
        # truthiness check would be that lie admitted.
        with pytest.raises(RouterBelowMinNotionalError) as raised:
            OrderValue(order=_order(), min_notional="5.00000000", value=Decimal(0))
        assert "stated value" in str(raised.value)

    def test_direct_construction_re_judges_the_floor(self) -> None:
        # The value's judgment runs at construction, so a value built by
        # hand cannot describe an order below the floor.
        with pytest.raises(RouterBelowMinNotionalError):
            OrderValue(order=_order(quantity="0.5", price="8.00"), min_notional="5.00")

    def test_a_refused_ask_leaves_nothing_behind(self) -> None:
        # There is nothing to leave behind — no scope, no table, no
        # registry — and this pins that the refusal is a raise and not a
        # recorded fallback: the ask either answers or does not exist.
        with pytest.raises(RouterBelowMinNotionalError):
            _ask(quantity="0.5", price="8.00")
        assert _ask().value == Decimal("25000.005")


class TestTheJudgmentIsPure:
    """No clock, no I/O, no store — the same ask answers the same verdict."""

    def test_the_judgment_reads_no_clock_of_its_own(self) -> None:
        import router.notional as module

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
        # Nothing to persist, and the caller holds the filters it read: a
        # gate that fetched its own would be a second, racing reader on the
        # order path.  ``decimal`` is the module's own subject.
        import router.notional as module

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
            "hashlib",
        ):
            assert forbidden not in imported, forbidden
        assert "decimal" in imported
        assert "dataclasses" in imported

    def test_the_judgment_needs_no_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The feature's own shape: nothing to persist, nothing to compose.
        # If this ever needs a store, this test fails.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert _ask().value == Decimal("25000.005")

    def test_two_asks_of_one_order_agree(self) -> None:
        # What a restarted router re-derives is what the process it
        # replaced derived: the order and the floor are the whole of the
        # decision.
        first = _ask()
        second = OrderValue(order=_order(), min_notional="5.00000000")
        assert first == second
        assert first.value == second.value


class TestTheMemberStillRegistersOneComponent:
    """Feature 313 adds a module and a class — no component, no table."""

    def test_exactly_one_builder(self) -> None:
        assert [name for name in dir(member) if name.startswith("build_")] == [
            "build_router_exchange_info_store"
        ]

    def test_the_member_exports_the_feature_313_names(self) -> None:
        # Both halves, the code token and the class: one without the other
        # is a refusal no caller can catch by name, or a class no operator
        # can grep for.
        for name in (
            "BELOW_MIN_NOTIONAL_CODE",
            "OrderValue",
            "RouterBelowMinNotionalError",
            "require_min_notional",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_member_still_exports_its_other_decisions(self) -> None:
        assert "require_rounded_order" in member.__all__
        assert "RoundedOrder" in member.__all__
        assert "require_isolated_margin" in member.__all__
        assert "resolve_order_posture" in member.__all__
        assert "derive_client_order_id" in member.__all__
        assert "RouterSymbolFilters" in member.__all__

    def test_the_module_adds_no_table(self) -> None:
        # The verdict is re-derivable from the terms and the floor, and
        # both are recorded wherever the order is.
        import router.notional as module

        assert module.__all__ == ["OrderValue", "require_min_notional"]
        assert not hasattr(module, "RouterNotionalStore")
        source = inspect.getsource(module)
        assert "CREATE TABLE" not in source


class TestTheCrossProcessCase:
    """Two routers judge one deployment's orders; the verdict is the same."""

    _SCRIPT = """
from decimal import Decimal

from router.errors import RouterBelowMinNotionalError
from router.exchange_info import RouterSymbolFilters
from router.notional import require_min_notional
from router.rounding import require_rounded_order

filters = RouterSymbolFilters(
    symbol="BTCUSDT",
    step_size="0.00001000",
    min_qty=None,
    max_qty=None,
    tick_size="0.01000000",
    min_price=None,
    max_price=None,
    min_notional="5.00000000",
)
order = require_rounded_order(
    symbol="BTCUSDT", quantity="0.5", price="10.00", filters=filters
)
value = require_min_notional(order=order, filters=filters)
print(value.value == Decimal("5.000"))
print(value.min_notional == Decimal("5.00000000"))
print(value == require_min_notional(order=order, filters=filters))
try:
    require_min_notional(
        order=require_rounded_order(
            symbol="BTCUSDT", quantity="0.5", price="9.99", filters=filters
        ),
        filters=filters,
    )
except RouterBelowMinNotionalError as exc:
    print(str(exc).startswith({code!r}))
try:
    require_min_notional(
        order=require_rounded_order(
            symbol="BTCUSDT", quantity="0.5", price="8.00", filters=filters
        ),
        filters=filters,
    )
except RouterBelowMinNotionalError as exc:
    print("not a rounding repair" in str(exc))
"""
    _WIDE_SCRIPT = """
from decimal import Decimal

from router.exchange_info import RouterSymbolFilters
from router.notional import require_min_notional
from router.rounding import require_rounded_order

filters = RouterSymbolFilters(
    symbol="BTCUSDT",
    step_size="0.01",
    min_qty=None,
    max_qty=None,
    tick_size="0.01",
    min_price=None,
    max_price=None,
    min_notional="1219326311370217952237463801111263.5269",
)
value = require_min_notional(
    order=require_rounded_order(
        symbol="BTCUSDT",
        quantity="12345678901234567.89",
        price="98765432109876543.21",
        filters=filters,
    ),
    filters=filters,
)
print(value.value == Decimal("1219326311370217952237463801111263.5269"))
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
        script = self._SCRIPT.format(code=BELOW_MIN_NOTIONAL_CODE)
        finished = self._run(script)
        assert finished.returncode == 0, finished.stderr
        at_floor, floor, agree, refused, not_rounding = (
            finished.stdout.strip().splitlines()
        )
        assert at_floor == "True"
        assert floor == "True"
        assert agree == "True"
        assert refused == "True"
        assert not_rounding == "True"

    def test_the_exact_product_survives_another_interpreters_context(
        self,
    ) -> None:
        # The widening is the module's own, not a property of this process's
        # ambient context: a fresh interpreter with the stock 28-digit
        # default answers the same exact value.
        finished = self._run(self._WIDE_SCRIPT)
        assert finished.returncode == 0, finished.stderr
        assert finished.stdout.strip() == "True"
