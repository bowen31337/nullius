"""Tests for :mod:`router.bingx_order` — a sized delta becomes a BingX order.

Feature 4 of additions_spec_bingx_dry_run.xml, first two sentences: *System
assembles each sized delta into the parameters of a BingX POST
/openApi/swap/v2/trade/order request by passing it through the router's
existing gates in a fixed order: posture (314), step and tick grids (312),
the notional floor (313), the minimum quantity, and isolated margin (315).
A passive leg returns type LIMIT, timeInForce PostOnly and a price at the
mark rounded onto the tick grid on the passive side (down for BUY, up for
SELL).  An aggressive leg returns type MARKET with no price, judged
against the notional floor at the mark.  A refused leg returns its router
code word and the symbol instead of an order.*  These tests hold the verb
to those three clauses over the recorded VST fixtures — the exact five
orders and one gate refusal the spec spells — and to the fixed gate order,
the passive-side price choice, the new minimum-quantity gate and the
ask-fault refusals that must *not* fold into refused legs.

The fixtures under ``fixtures/bingx_vst/`` are inputs and are never edited
here.  The ``RouterSymbolFilters`` these tests hand the assembler are
built inline from ``contracts.json`` the way feature 1's translator builds
them at runtime — step as ten to the minus ``quantityPrecision``, never
the contract's ``size`` field — the same discipline
:mod:`tests.test_sizing` states for its own hand-built filters.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from router.bingx_client_order_id import (
    BINGX_CLIENT_ORDER_ID_LENGTH,
    project_bingx_client_order_id,
)
from router.bingx_order import (
    BELOW_MIN_QUANTITY_CODE,
    BINGX_ORDER_CODE,
    BINGX_POSITION_SIDE_BOTH,
    BINGX_POST_ONLY,
    BingXOrder,
    BingXRefusedLeg,
    RouterBelowMinQuantityError,
    RouterBingXOrderError,
    assemble_bingx_order,
)
from router.client_order_id import derive_client_order_id
from router.errors import (
    BELOW_MIN_NOTIONAL_CODE,
    CROSS_MARGIN_CODE,
    ORDER_POSTURE_CODE,
    ORDER_ROUNDING_CODE,
    RouterError,
)
from router.exchange_info import RouterSymbolFilters
from router.margin import CROSS_MARGIN, ISOLATED_MARGIN

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"


def _fixture(name: str) -> dict:
    """One recorded VST fixture, decoded verbatim from disk."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _synthetic_book() -> dict:
    """The hand-written Stage 0 book, as captured."""
    return _fixture("synthetic_book.json")


def _vst_filters() -> dict[str, RouterSymbolFilters]:
    """The tradable symbols' filters, built as feature 1 translates them.

    Step is ten to the minus ``quantityPrecision`` and tick ten to the
    minus ``pricePrecision`` — the ``size`` field is never read as the
    step, the constraint the spec states for ETH-USDT, SOL-USDT and five
    other symbols where the two differ.  A contract whose status is not 1
    is not translated at all; feature 1 answers ``not_tradable`` for it
    and the dry run records the refused leg before any gate runs.
    """
    filters: dict[str, RouterSymbolFilters] = {}
    for row in _fixture("contracts.json")["data"]:
        if row["status"] != 1:
            continue
        filters[row["symbol"]] = RouterSymbolFilters(
            symbol=row["symbol"],
            step_size=str(Decimal(1).scaleb(-int(row["quantityPrecision"]))),
            min_qty=str(row["tradeMinQuantity"]),
            max_qty=None,
            tick_size=str(Decimal(1).scaleb(-int(row["pricePrecision"]))),
            min_price=None,
            max_price=None,
            min_notional=str(row["tradeMinUSDT"]),
        )
    return filters


def _vst_marks() -> dict[str, Decimal]:
    """The Decimal mark per symbol, as feature 1's premiumIndex reader answers."""
    return {
        row["symbol"]: Decimal(row["markPrice"])
        for row in _fixture("premium_index.json")["data"]
    }


def _durations(symbol: str) -> tuple[timedelta, timedelta]:
    """The book's own two durations for ``symbol``, as timedeltas.

    The book states them in seconds; the posture gate reads lengths of
    time.  Every symbol in the recorded book carries a decay horizon of
    14400 seconds except DOGE-USDT's 60, against an expected fill time of
    120 — which is why exactly DOGE-USDT crosses.
    """
    book = _synthetic_book()
    return (
        timedelta(seconds=book["decay_horizon_seconds"][symbol]),
        timedelta(seconds=book["expected_fill_seconds"]),
    )


def _identity(symbol: str) -> object:
    """Feature 316's identifier for one leg of the recorded book."""
    book = _synthetic_book()
    return derive_client_order_id(
        book_id=book["book_id"],
        rebalance_ts=datetime.fromisoformat(book["rebalance_ts"]),
        symbol=symbol,
    )


def _assemble(
    symbol: str,
    delta: Decimal,
    *,
    mark: object = None,
    filters: object = None,
    signal_decay_horizon: object = None,
    mode: str = ISOLATED_MARGIN,
) -> object:
    """Assemble one recorded leg, defaulting every term from the fixtures.

    The deltas handed in are the spec's own six numbers — feature 2's
    answer over the same fixtures, restated here so a failure in this
    suite is about the assembly, not the sizing.
    """
    book = _synthetic_book()
    horizon, fill = _durations(symbol)
    return assemble_bingx_order(
        symbol=symbol,
        delta=delta,
        mark=_vst_marks()[symbol] if mark is None else mark,
        filters=_vst_filters()[symbol] if filters is None else filters,
        signal_decay_horizon=horizon if signal_decay_horizon is None else signal_decay_horizon,
        expected_fill_time=fill,
        client_order_id=_identity(symbol),
        book_id=book["book_id"],
        account=book["account"],
        mode=mode,
    )


def _hand_filters(
    symbol: str,
    *,
    step: str | None = "1",
    tick: str | None = "0.01",
    min_qty: str | None = "10",
    min_notional: str | None = "2",
) -> RouterSymbolFilters:
    """One symbol's filters with hand-stated bounds and no others.

    The bounds the two floor gates judge, and none of the maxima this
    addition never reads — a one-symbol grid built to fail exactly one
    gate at a time.
    """
    return RouterSymbolFilters(
        symbol=symbol,
        step_size=step,
        min_qty=min_qty,
        max_qty=None,
        tick_size=tick,
        min_price=None,
        max_price=None,
        min_notional=min_notional,
    )


#: The four passive legs the spec spells, with the deltas feature 2 answers
#: over the recorded fixtures: the side, the exact quantity string and the
#: exact price string are the spec's own pinned values.
PASSIVE_LEGS = (
    ("BTC-USDT", "BUY", "0.0140", "83137.3"),
    ("ETH-USDT", "SELL", "0.558", "2685.87"),
    ("SOL-USDT", "BUY", "8.44", "118.392"),
    ("1000PEPE-USDT", "BUY", "69446", "0.0043199"),
)

#: The same legs' signed deltas, keyed by symbol — the sign becomes the
#: side, the magnitude the quantity.
RECORDED_DELTAS = {
    "BTC-USDT": Decimal("0.0140"),
    "ETH-USDT": Decimal("-0.558"),
    "SOL-USDT": Decimal("8.44"),
    "DOGE-USDT": Decimal(-5329),
    "1000PEPE-USDT": Decimal(69446),
    "AGLD-USDT": Decimal("4.84"),
}


def test_the_recorded_passive_legs_answer_the_specified_limit_orders() -> None:
    """LIMIT, PostOnly, and the mark's own spelling as the price — exactly.

    Every recorded mark sits on its symbol's tick grid, so the passively
    rounded price *is* the mark verbatim: BTC-USDT's 83137.3, ETH-USDT's
    2685.87, SOL-USDT's 118.392, 1000PEPE-USDT's 0.0043199.  The quantity
    keeps the spelling the grid answered — BTC-USDT's ``0.0140`` with its
    trailing zero — and positionSide is the one-way ``BOTH`` the signed
    book speaks.
    """
    for symbol, side, quantity, price in PASSIVE_LEGS:
        order = _assemble(symbol, RECORDED_DELTAS[symbol])
        assert isinstance(order, BingXOrder), symbol
        assert order.side == side
        assert order.type == "LIMIT"
        assert order.time_in_force == BINGX_POST_ONLY == "PostOnly"
        assert order.position_side == BINGX_POSITION_SIDE_BOTH == "BOTH"
        assert order.parameters() == {
            "symbol": symbol,
            "side": side,
            "positionSide": "BOTH",
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": "PostOnly",
            "clientOrderID": project_bingx_client_order_id(_identity(symbol)),
        }


def test_the_recorded_aggressive_leg_answers_a_market_order_with_no_price() -> None:
    """DOGE-USDT's 60-second decay outruns the 120-second queue, so it crosses.

    Type MARKET, quantity 5329, side SELL — and *no price and no
    timeInForce at all*: the parameters the request would carry omit both
    keys rather than spelling nulls of them, because a market order
    crosses at the venue's own price.  Its value was still judged — at
    the mark, 5329 × 0.09381 ≈ 499.91 against the 2-USDT floor.
    """
    order = _assemble("DOGE-USDT", RECORDED_DELTAS["DOGE-USDT"])
    assert isinstance(order, BingXOrder)
    assert order.price is None
    assert order.time_in_force is None
    assert order.parameters() == {
        "symbol": "DOGE-USDT",
        "side": "SELL",
        "positionSide": "BOTH",
        "type": "MARKET",
        "quantity": "5329",
        "clientOrderID": project_bingx_client_order_id(_identity("DOGE-USDT")),
    }


def test_every_client_order_id_is_feature_3s_projection_and_at_most_40_characters() -> None:
    """The venue field is feature 3's answer over feature 316's identifier.

    Applied once, at the boundary — never re-derived or re-truncated here
    — and never a character over the venue's 40-field cap.  BTC-USDT's
    projection is pinned literally as well, so a drift in either the
    identity or the projection is caught by name.
    """
    for symbol, delta in RECORDED_DELTAS.items():
        if symbol == "AGLD-USDT":
            continue  # the leg the notional floor refuses; it carries no id
        order = _assemble(symbol, delta)
        assert isinstance(order, BingXOrder), symbol
        expected = project_bingx_client_order_id(_identity(symbol))
        assert order.client_order_id == expected
        assert len(order.client_order_id) <= 40
        assert BINGX_CLIENT_ORDER_ID_LENGTH == 40
    assert (
        _assemble("BTC-USDT", RECORDED_DELTAS["BTC-USDT"]).client_order_id
        == "cd2a5cafc184c765919a0a3e923135ace3e43079"
    )


def test_the_recorded_below_floor_leg_is_refused_below_min_notional() -> None:
    """AGLD-USDT: 4.84 contracts at 0.2065 is 0.99946 USDT — under the 2 floor.

    And *below_min_notional*, not ``below_min_quantity``, although 4.84
    also falls under the venue's 9.7-contract minimum: the notional floor
    is judged one gate earlier in the sentence's fixed order, so the
    refusal a reader greps is the first gate that refused — the value
    repair, not the units repair the same leg would also need.
    """
    leg = _assemble("AGLD-USDT", RECORDED_DELTAS["AGLD-USDT"])
    assert leg == BingXRefusedLeg(
        symbol="AGLD-USDT", code=BELOW_MIN_NOTIONAL_CODE
    )
    assert leg.code == "below_min_notional"


def test_the_gates_refuse_in_the_sentence_fixed_order() -> None:
    """A leg wrong at several gates is refused for the first, deterministically.

    Five legs, each wrong from a different gate onward, each refusing
    with that gate's own code word:

    * posture — a decay horizon offered as a bare number states no unit,
      and the posture gate refuses it before any other gate is read;
    * grids — a quantity off the step grid is refused even when the
      notional floor, the minimum quantity and the margin mode would
      each refuse it too;
    * notional — AGLD-USDT's recorded leg refuses on value even under a
      cross margin mode, because the floor is judged before the margin;
    * minimum quantity — a leg that clears value but not units;
    * margin — a leg that clears all four judgments and then arrives
      under a cross arrangement.
    """
    book = _synthetic_book()
    identity = _identity("X-USDT")
    common = {
        "client_order_id": identity,
        "book_id": book["book_id"],
        "account": book["account"],
    }

    # Posture first: an unreadable duration is the posture gate's own
    # refusal, whatever else the leg would fail.
    assert assemble_bingx_order(
        symbol="X-USDT",
        delta=Decimal("5.5"),
        mark=Decimal(1),
        filters=_hand_filters("X-USDT", min_notional="1000000", min_qty="999999"),
        signal_decay_horizon=14400,
        expected_fill_time=timedelta(seconds=120),
        mode=CROSS_MARGIN,
        **common,
    ) == BingXRefusedLeg(symbol="X-USDT", code=ORDER_POSTURE_CODE)

    # Then the grids: 5.5 is off the unit step grid, and the leg would
    # also fail the 1000000-USDT floor, the 999999 minimum and the mode.
    assert assemble_bingx_order(
        symbol="X-USDT",
        delta=Decimal("5.5"),
        mark=Decimal(1),
        filters=_hand_filters("X-USDT", min_notional="1000000", min_qty="999999"),
        signal_decay_horizon=timedelta(seconds=14400),
        expected_fill_time=timedelta(seconds=120),
        mode=CROSS_MARGIN,
        **common,
    ) == BingXRefusedLeg(symbol="X-USDT", code=ORDER_ROUNDING_CODE)

    # Then the notional floor: the recorded AGLD-USDT leg, arrived under
    # a cross mode, still refuses on value — the floor outranks the mode.
    assert _assemble(
        "AGLD-USDT", RECORDED_DELTAS["AGLD-USDT"], mode=CROSS_MARGIN
    ) == BingXRefusedLeg(symbol="AGLD-USDT", code=BELOW_MIN_NOTIONAL_CODE)

    # Then the minimum quantity: 5 units at 1.00 is 5 USDT of value —
    # over the 2 floor — but 5 is under the 10-contract minimum.
    assert assemble_bingx_order(
        symbol="X-USDT",
        delta=Decimal(5),
        mark=Decimal(1),
        filters=_hand_filters("X-USDT", min_qty="10", min_notional="2"),
        signal_decay_horizon=timedelta(seconds=14400),
        expected_fill_time=timedelta(seconds=120),
        mode=CROSS_MARGIN,
        **common,
    ) == BingXRefusedLeg(symbol="X-USDT", code=BELOW_MIN_QUANTITY_CODE)

    # And isolated margin last: the same leg at the minimum trades under
    # the book's own isolated mode and refuses only under a cross one.
    leg = assemble_bingx_order(
        symbol="X-USDT",
        delta=Decimal(5),
        mark=Decimal(1),
        filters=_hand_filters("X-USDT", min_qty="5", min_notional="2"),
        signal_decay_horizon=timedelta(seconds=14400),
        expected_fill_time=timedelta(seconds=120),
        mode=CROSS_MARGIN,
        **common,
    )
    assert leg == BingXRefusedLeg(symbol="X-USDT", code=CROSS_MARGIN_CODE)


def test_an_order_at_exactly_the_minimums_trades() -> None:
    """Both floors are strict-below, so a leg exactly at them trades.

    Two contracts at 1.00 is exactly the 2-USDT floor and exactly the
    2-contract minimum: *below* is strict in both gates, and a leg at
    the bound is at the bound, not under it.
    """
    order = assemble_bingx_order(
        symbol="X-USDT",
        delta=Decimal(2),
        mark=Decimal(1),
        filters=_hand_filters("X-USDT", min_qty="2", min_notional="2"),
        signal_decay_horizon=timedelta(seconds=14400),
        expected_fill_time=timedelta(seconds=120),
        client_order_id=_identity("X-USDT"),
        book_id=_synthetic_book()["book_id"],
        account=_synthetic_book()["account"],
    )
    assert isinstance(order, BingXOrder)
    assert order.quantity == "2"
    # The mark 1 is already on the 0.01 grid, so the price keeps the
    # mark's own spelling, verbatim.
    assert order.price == "1"


def test_a_passive_buy_rounds_down_and_a_passive_sell_rounds_up() -> None:
    """The mark's own off-grid neighbours, on the side that does not cross.

    A BUY at 83137.36 on a 0.1 grid takes 83137.30 — down, because a bid
    rounded up could post at or through the ask and a PostOnly order
    that crosses is refused by the venue.  A SELL at 2685.879 on a 0.01
    grid takes 2685.880 — up, for the mirror reason against the bid —
    spelled in the scale its own arithmetic answered (2685.870 + 0.010),
    exactly as the quantity keeps the grid's spelling.  Both answers
    keep the quantity the sizer chose, untouched: the gates judge, they
    never round.
    """
    buy = _assemble("BTC-USDT", RECORDED_DELTAS["BTC-USDT"], mark=Decimal("83137.36"))
    assert isinstance(buy, BingXOrder)
    assert buy.price == "83137.30"
    assert Decimal(buy.price) < Decimal("83137.36")
    assert buy.quantity == "0.0140"

    sell = _assemble("ETH-USDT", RECORDED_DELTAS["ETH-USDT"], mark=Decimal("2685.879"))
    assert isinstance(sell, BingXOrder)
    assert sell.price == "2685.880"
    assert Decimal(sell.price) > Decimal("2685.879")
    assert sell.quantity == "0.558"


def test_an_aggressive_leg_whose_mark_is_off_the_grid_is_refused_by_the_grids() -> None:
    """A market order carries no price, so the grids judge the mark itself.

    DOGE-USDT crosses (its 60-second decay outruns the 120-second queue)
    and the mark 0.093815 does not sit on the venue's own 1e-5 tick grid
    — and a mark that cannot sit on the grid its venue publishes is
    refused rather than silently snapped, the read-exactly-or-refuse
    discipline every gate in this member holds its terms to.
    """
    leg = _assemble(
        "DOGE-USDT", RECORDED_DELTAS["DOGE-USDT"], mark=Decimal("0.093815")
    )
    assert leg == BingXRefusedLeg(symbol="DOGE-USDT", code=ORDER_ROUNDING_CODE)


def test_a_leg_with_no_stated_minimum_quantity_is_refused_not_passed() -> None:
    """A venue that states no minimum leaves the leg unjudgeable — refused.

    ``min_qty=None`` is the translated document's own statement that it
    carries no ``tradeMinQuantity`` for the symbol; passing the leg as
    unconstrained would be a bound this module defaulted, which is
    exactly the hardcoded venue constant feature 311 forbids.
    """
    leg = assemble_bingx_order(
        symbol="X-USDT",
        delta=Decimal(5),
        mark=Decimal(1),
        filters=_hand_filters("X-USDT", min_qty=None, min_notional="2"),
        signal_decay_horizon=timedelta(seconds=14400),
        expected_fill_time=timedelta(seconds=120),
        client_order_id=_identity("X-USDT"),
        book_id=_synthetic_book()["book_id"],
        account=_synthetic_book()["account"],
    )
    assert leg == BingXRefusedLeg(symbol="X-USDT", code=BELOW_MIN_QUANTITY_CODE)
    # The new refusal is this addition's own vocabulary, subclassing the
    # router's base — the convention the spec states for it.
    assert issubclass(RouterBelowMinQuantityError, RouterError)


def test_filters_for_another_symbol_are_refused_by_the_grids() -> None:
    """A price rounded onto another symbol's grid is about the wrong instrument.

    The passive path reads the tick grid before it chooses a price, so
    the ETH-USDT filters under a BTC-USDT leg refuse as a grids failure
    — the same judgment feature 312's gate makes, stated at the read.
    """
    leg = _assemble(
        "BTC-USDT",
        RECORDED_DELTAS["BTC-USDT"],
        filters=_vst_filters()["ETH-USDT"],
    )
    assert leg == BingXRefusedLeg(symbol="BTC-USDT", code=ORDER_ROUNDING_CODE)


def test_an_unreadable_ask_propagates_rather_than_folding_into_a_refused_leg() -> None:
    """A float delta or mark is a fault of the call, not a market fact.

    The gates' refusals are answers about a leg; a term the assembler
    cannot read is a wiring fault, and a plan that printed its caller's
    bugs as ``order_rounding`` legs would be a plan nobody could trust
    on the legs that mattered.  So these raise, with this module's own
    code word, naming the float by name.
    """
    with pytest.raises(RouterBingXOrderError) as raised:
        _assemble("BTC-USDT", 0.014)
    assert str(raised.value).startswith(f"{BINGX_ORDER_CODE}: ")
    assert "float" in str(raised.value)

    with pytest.raises(RouterBingXOrderError) as raised:
        _assemble("BTC-USDT", RECORDED_DELTAS["BTC-USDT"], mark=83137.3)
    assert str(raised.value).startswith(f"{BINGX_ORDER_CODE}: ")
    assert "float" in str(raised.value)

    with pytest.raises(RouterBingXOrderError):
        assemble_bingx_order(
            symbol="   ",
            delta=RECORDED_DELTAS["BTC-USDT"],
            mark=_vst_marks()["BTC-USDT"],
            filters=_vst_filters()["BTC-USDT"],
            signal_decay_horizon=timedelta(seconds=14400),
            expected_fill_time=timedelta(seconds=120),
            client_order_id=_identity("BTC-USDT"),
            book_id="synthetic-vst-0",
            account="bingx-vst",
        )


def _hand_order(**overrides: object) -> BingXOrder:
    """One hand-built order, validated exactly as the verb's answers are."""
    fields: dict[str, object] = {
        "symbol": "X-USDT",
        "side": "BUY",
        "position_side": "BOTH",
        "type": "LIMIT",
        "quantity": "1",
        "price": "1.00",
        "time_in_force": "PostOnly",
        "client_order_id": "a" * 40,
    }
    fields.update(overrides)
    return BingXOrder(**fields)  # type: ignore[arg-type]


def test_the_order_value_validates_the_venues_own_vocabularies() -> None:
    """A value built by hand gets the judgment the verb applies.

    The side, type and position-side vocabularies are closed; a LIMIT
    without both a price and a timeInForce — or a MARKET with either —
    is a request shape no posture compels; a quantity at or below zero,
    or a decimal spelling the arithmetic never answered, is refused; and
    the clientOrderID is held to the venue's own 40-character cap rather
    than re-truncated to fit.
    """
    with pytest.raises(RouterBingXOrderError):
        _hand_order(side="buy")
    with pytest.raises(RouterBingXOrderError):
        _hand_order(type="FOK")
    with pytest.raises(RouterBingXOrderError):
        _hand_order(type="MARKET", price="1.00", time_in_force=None)
    with pytest.raises(RouterBingXOrderError):
        _hand_order(time_in_force=None)
    with pytest.raises(RouterBingXOrderError):
        _hand_order(quantity="0")
    with pytest.raises(RouterBingXOrderError):
        _hand_order(client_order_id="a" * 41)
    # Canonicalised, not trusted: the symbol is stripped, and a value
    # built with padding compares equal to the verb's own spelling.
    assert _hand_order(symbol="  X-USDT  ").symbol == "X-USDT"


def test_the_refused_leg_value_names_its_leg_and_carries_a_code_word() -> None:
    """A refusal that names no leg answers nothing; one without a code greps nothing.

    The code word is the gate's address — the whole reason gates spell
    them — and the symbol is the operator's first question, so both are
    required and canonicalised at construction.
    """
    with pytest.raises(RouterBingXOrderError):
        BingXRefusedLeg(symbol="   ", code="below_min_notional")
    with pytest.raises(RouterBingXOrderError):
        BingXRefusedLeg(symbol="X-USDT", code="  ")
    assert BingXRefusedLeg(symbol=" X-USDT ", code=" cross_margin ").symbol == "X-USDT"
