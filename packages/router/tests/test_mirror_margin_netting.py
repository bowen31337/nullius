"""Tests for the preflight margin's netting: :mod:`router.bingx_mirror`.

``bug_spec_vst_slot_resilience.xml``, bug 1: the placement preflight's
required margin counted the position-increasing legs and ignored the
margin the plan's own position-reducing legs release, so a fully
invested book's rebalance was refused for a shortfall the same plan
would itself free — the forward shadow book's slots 2026-10-20T20:00 and
2026-10-21T00:00 UTC answered *"insufficient_balance: available USDT
1164.3478 is below the 1179.0264465165 this plan's orders need"* while
the plan's reducing legs released more than the 14.7 USDT shortfall.

The fix, clause by clause:

* :func:`router.bingx_mirror.plan_required_margin` nets, against the
  increasing legs' requirement, the margin the plan's position-reducing
  quantities release — each order's reducing quantity (the part of its
  size that closes existing exposure, read from the same live positions
  document) times the same reference price the increasing side uses, at
  the preflight's leverage of one.  The door's term is
  ``max(0, increase - release)`` times the standing half-percent
  headroom: an all-reducing plan still answers 0, an all-increasing plan
  answers the pre-fix computation to the last digit, and every term is
  an exact :class:`~decimal.Decimal`.
* :func:`router.bingx_mirror.mirror_place` sends the plan's
  position-reducing legs before its position-increasing legs (stable
  within each group in the plan's own order), so the venue releases
  margin before the increasing legs post.  Idempotency, the per-order
  store record and the refusal handling are unchanged.
* The term the mirror hands the preflight carries both sides of the
  netting — ``increase_usdt`` and ``release_usdt`` — beside the required
  value, so the report :func:`router.bingx_preflight.run_bingx_preflight`
  records and the ``insufficient_balance`` refusal it raises name what
  was netted (the fields ride the term itself through the keyword
  mapping the mirror already hands the preflight; the preflight's own
  signature and refusals are untouched).

Every test injects a client double — no socket, no key, no network.  The
recorded premiumIndex fixture is read for the one test that reuses the
existing margin fixture's own marks; everything else states its own
documents, the shapes pinned in ``fixtures/bingx_vst/live/``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from router.bingx_client import ORDER_NOT_FOUND_CODE, RouterBingXRefusedError
from router.bingx_mirror import (
    MIRROR_OUTCOME_PLACED,
    REQUIRED_MARGIN_HEADROOM,
    mirror_place,
    plan_required_margin,
)
from router.bingx_order import (
    BINGX_BUY,
    BINGX_LIMIT_ORDER,
    BINGX_MARKET_ORDER,
    BINGX_POST_ONLY,
    BINGX_SELL,
    BingXOrder,
)
from router.bingx_preflight import (
    RouterBingXInsufficientBalanceError,
    run_bingx_preflight,
)
from router.submission_result import RouterOrderPlacementStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: A local clock the tests pin; the preflight compares it against the
#: double's server time, which the tests keep equal so no skew is refused.
LOCAL_MILLIS = 1_700_000_000_123

#: The one price the whole netting fixture trades at: a mark, a limit and
#: a book-side quote of exactly one, so every quantity reads as its own
#: notional and the arithmetic's terms stay one-line legible.
MARK = "1"

#: The spec's own fixture symbols: A and B hold the long and the short the
#: plan trims, C is the flat leg the plan opens.
SYMBOLS = ("A-USDT", "B-USDT", "C-USDT", "D-USDT")

#: The account the spec's fixture answers: ten available against an
#: increasing side of thirty — the door's refusal before the fix, and its
#: pass once the hundred the two reducing legs release is netted.
BALANCE = {"balance": {"asset": "USDT", "availableMargin": "10"}}

#: The venue's own unsigned spelling of the fixture's holdings, the shape
#: the live capture pinned (``live/positions_one_way_short.json``): the
#: direction in ``positionSide``, the magnitude in ``positionAmt``.
HELD = (
    {"symbol": "A-USDT", "positionSide": "LONG", "positionAmt": "100"},
    {"symbol": "B-USDT", "positionSide": "SHORT", "positionAmt": "100"},
)

#: The live slot's own figures, as the spec spells them: 1164.35 available
#: (the log's 1164.3478) against an increasing side whose headroomed term
#: is 1179.3675 (the log's 1179.0264465165) — a shortfall of about 14.7
#: the plan's own reducing legs release.
LIVE_AVAILABLE = "1164.35"
LIVE_INCREASE_QUANTITY = "1173.5"  # x 1.005 headroom = 1179.3675
LIVE_RELEASE_QUANTITY = "15"


def _contracts_document(symbols) -> dict:
    """A minimal contracts document whose grids hold the fixture's terms.

    One row per symbol, the fields :func:`router.bingx_documents.
    resolve_bingx_filters` translates — precisions of four places, a
    minimum of the same, and the tradable state — so a passive leg priced
    at one with a whole-number quantity re-judges gate for gate and
    rests, exactly as the repriced legs of a placement run must.
    """
    return {
        "data": [
            {
                "symbol": symbol,
                "quantityPrecision": 4,
                "pricePrecision": 4,
                "tradeMinQuantity": "0.0001",
                "tradeMinUSDT": 2,
                "status": 1,
                "apiStateOpen": "true",
            }
            for symbol in symbols
        ]
    }


def _marks_document(symbols, mark: str = MARK) -> dict:
    """A premiumIndex document pricing every fixture symbol at ``mark``."""
    return {"data": [{"symbol": symbol, "markPrice": mark} for symbol in symbols]}


class _NettingClient:
    """A stand-in for feature 1's client: the netting fixture's own documents.

    Carries every face the mirror, the preflight and the repricer read the
    venue through, so the double is a complete stand-in and no test opens
    a socket: the three plan documents (contracts, premiumIndex,
    positions), the depth a passive leg reprices against, the preflight's
    five faces, and the order path's ``place_order`` — which records every
    order it takes, the fact the send-order tests read.
    """

    def __init__(
        self,
        *,
        positions: object = (),
        balance: object = None,
        symbols: object = SYMBOLS,
        marks: object = None,
    ) -> None:
        self._positions = list(positions)
        self._balance = BALANCE if balance is None else balance
        self._symbols = tuple(symbols)
        self._marks = marks
        self.placed: list[BingXOrder] = []

    # -- The mirror's three reads -------------------------------------------
    def contracts(self) -> object:
        return _contracts_document(self._symbols)

    def premium_index(self) -> object:
        if self._marks is not None:
            return self._marks
        return _marks_document(self._symbols)

    def positions(self, symbol: str | None = None) -> object:
        return list(self._positions)

    # -- The mirror's repricing read ----------------------------------------
    def depth(self, symbol: str) -> object:
        # Both sides quote the mark, so a repriced passive leg keeps the
        # plan's own price and every quantity stays its own notional.
        return {"bids": [[MARK, "100000"]], "asks": [[MARK, "100000"]]}

    # -- The preflight's five faces -----------------------------------------
    def server_time(self) -> int:
        return LOCAL_MILLIS

    def position_mode(self) -> bool:
        # One-way: the state every account these tests place on holds.
        return False

    def balance(self) -> object:
        return self._balance

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> object:
        return {}

    def set_leverage(
        self, symbol: str, leverage: int = 1, *, side: str = "BOTH"
    ) -> object:
        return {}

    # -- The order path ------------------------------------------------------
    def place_order(self, order: BingXOrder) -> object:
        self.placed.append(order)
        return {"orderId": order.symbol}

    def query_order(self, client_order_id: str, *, symbol: str | None = None) -> object:
        raise RouterBingXRefusedError(ORDER_NOT_FOUND_CODE, "order does not exist")


class _CountingLimiter:
    """A limiter double: answers every acquire, meters nothing."""

    def acquire(self, operation: str, *, now: object = None) -> object:
        return object()


def _book() -> dict:
    """The netting fixture's Stage 0 book: identity, durations, margins.

    Only the terms the placement path itself reads — the identity pair
    every order's name folds, the durations the posture gate judges a
    repriced leg through, the margin arrangement — because the legs in
    these tests are hand built, not sized from the weights.
    """
    return {
        "book_id": "netting-fixture-0",
        "rebalance_ts": "2026-10-21T00:00:00+00:00",
        "account": "bingx-vst",
        "margin_mode": "isolated",
        "equity_usdt": "1000",
        "expected_fill_seconds": 120,
        "weights": {"A-USDT": 0.1, "B-USDT": -0.1, "C-USDT": 0.03, "D-USDT": 0.01},
        "decay_horizon_seconds": {symbol: 14400 for symbol in SYMBOLS},
        "positions": {},
    }


def _leg(
    *,
    symbol: str,
    side: str,
    quantity: str,
    price: str | None = MARK,
    order_type: str = BINGX_LIMIT_ORDER,
) -> BingXOrder:
    """A hand-built order leg: the margin arithmetic's terms, and nothing else.

    Carries the one-way spelling every assembled order carries, so the
    plan's own value type answers :func:`plan_required_margin` and the
    placement path without a full book, sizer and gate run behind it.
    """
    return BingXOrder(
        symbol=symbol,
        side=side,
        position_side="BOTH",
        type=order_type,
        quantity=quantity,
        price=price if order_type == BINGX_LIMIT_ORDER else None,
        time_in_force=(
            BINGX_POST_ONLY if order_type == BINGX_LIMIT_ORDER else None
        ),
        client_order_id=f"netting-{symbol}".lower()[:40],
    )


def _spec_plan() -> list[BingXOrder]:
    """The spec's own three legs, in the spec's own order.

    Reduce A by 50 (SELL against the long), reduce B by 50 (BUY against
    the short), open C long 30 (BUY from flat, at limit one) — the plan
    whose increasing side needs thirty while its reducing side releases
    a hundred as it fills.
    """
    return [
        _leg(symbol="A-USDT", side=BINGX_SELL, quantity="50"),
        _leg(symbol="B-USDT", side=BINGX_BUY, quantity="50"),
        _leg(symbol="C-USDT", side=BINGX_BUY, quantity="30"),
    ]


def _place(client: _NettingClient, plan: list, database_url: str) -> dict:
    """Drive one placement run the way the command does, over the double."""
    return mirror_place(
        client=client,
        book=_book(),
        plan=plan,
        store=RouterOrderPlacementStore(database_url),
        limiter=_CountingLimiter(),
        database_url=database_url,
        clock=lambda: LOCAL_MILLIS,
        sleep=lambda _d: None,
    )


# -- The netting arithmetic -----------------------------------------------------


def test_the_reducing_legs_release_nets_the_increase_legs_requirement():
    """The spec's own fixture, as the door's term answers it.

    Before the fix the two reducing legs contributed nothing and released
    nothing, so the term answered 30 x the half-percent headroom and an
    account holding ten was refused; netted, the hundred they release
    covers the thirty C binds and the term answers zero, with both sides
    of the netting stated beside it for the operator to read.
    """
    client = _NettingClient(positions=HELD)

    margin = plan_required_margin(client=client, orders=_spec_plan())

    assert margin == Decimal(0)
    assert margin.increase_usdt == Decimal(30)
    assert margin.release_usdt == Decimal(100)


def test_an_all_reducing_plan_still_answers_zero():
    """The boundary the previous fix named, kept: nothing binds, zero.

    Every leg of a plan that only trims holdings closes exposure and
    opens none, so the door asks the account for nothing — the netting's
    floor at zero, not a negative credit an unfilled leg could spend.
    """
    client = _NettingClient(positions=HELD)
    orders = [
        _leg(symbol="A-USDT", side=BINGX_SELL, quantity="100"),
        _leg(symbol="B-USDT", side=BINGX_BUY, quantity="100"),
    ]

    margin = plan_required_margin(client=client, orders=orders)

    assert margin == Decimal(0)
    assert margin.increase_usdt == Decimal(0)
    assert margin.release_usdt == Decimal(200)


def test_a_crossing_leg_counts_only_the_beyond_zero_part_as_increasing():
    """A reducing leg larger than the position crosses to the other side.

    The part up to flat releases (here 2 of a 5 SELL against a long 2, at
    a limit of two: 4 released) and only the part beyond zero binds (the
    3 that lands as a new short: 6 required) — the crossing law today's
    ``_increasing_size`` already states, now answered on the release side
    too, so a crossing leg never nets more release than the exposure it
    closes.
    """
    client = _NettingClient(
        positions=(
            {"symbol": "A-USDT", "positionSide": "LONG", "positionAmt": "2"},
        )
    )
    order = _leg(symbol="A-USDT", side=BINGX_SELL, quantity="5", price="2")

    margin = plan_required_margin(client=client, orders=[order])

    assert margin.increase_usdt == Decimal(6)
    assert margin.release_usdt == Decimal(4)
    assert margin == (Decimal(6) - Decimal(4)) * REQUIRED_MARGIN_HEADROOM


def test_an_all_increasing_plan_answers_the_pre_fix_margin_to_the_last_digit():
    """No releases to net: the door's term is the pre-fix computation.

    The existing ``plan_required_margin`` fixture's own five legs — a
    passive BUY, a passive SELL, a leg that would cross a held position,
    a MARKET BUY and another — over a flat account, so every leg opens
    exposure and none closes any: the marks (SOL 118.392, DOGE 0.09381)
    are the recorded premiumIndex fixture's own, and the answer equals
    the arithmetic the door judged before the netting existed, to the
    last digit.
    """
    marks = json.loads((FIXTURES / "premium_index.json").read_text(encoding="utf-8"))
    client = _NettingClient(positions=(), marks=marks)
    orders = [
        _leg(
            symbol="BTC-USDT", side=BINGX_BUY, quantity="0.5", price="83000"
        ),
        _leg(
            symbol="ETH-USDT", side=BINGX_SELL, quantity="1", price="2600"
        ),
        _leg(
            symbol="1000PEPE-USDT",
            side=BINGX_SELL,
            quantity="5",
            price="0.0044",
        ),
        _leg(
            symbol="SOL-USDT",
            side=BINGX_BUY,
            quantity="8",
            order_type=BINGX_MARKET_ORDER,
        ),
        _leg(
            symbol="DOGE-USDT",
            side=BINGX_BUY,
            quantity="40",
            order_type=BINGX_MARKET_ORDER,
        ),
    ]

    margin = plan_required_margin(client=client, orders=orders)

    bare = (
        Decimal("0.5") * Decimal(83000)
        + Decimal(1) * Decimal(2600)
        + Decimal(5) * Decimal("0.0044")
        + Decimal(8) * Decimal("118.392")
        + Decimal(40) * Decimal("0.09381")
    )
    assert margin.increase_usdt == bare
    assert margin.release_usdt == Decimal(0)
    assert margin == bare * REQUIRED_MARGIN_HEADROOM
    assert margin == Decimal("45276.164952")


# -- The door and the send order -------------------------------------------------


def test_the_netted_plan_passes_the_door_and_sends_its_reducing_legs_first(
    test_database_url,
):
    """The spec's fixture places: available 10 funds a netted term of 0.

    And the two reducing legs leave before the increasing one — A and B
    ahead of C whatever the plan's own order — so the venue releases
    their margin before C's order posts and binds it.
    """
    client = _NettingClient(positions=HELD)

    outcomes = _place(client, _spec_plan(), test_database_url)

    assert [outcome.outcome for outcome in outcomes.values()] == [
        MIRROR_OUTCOME_PLACED
    ] * 3
    sent = [order.symbol for order in client.placed]
    assert set(sent) == {"A-USDT", "B-USDT", "C-USDT"}
    assert sent.index("C-USDT") > sent.index("A-USDT")
    assert sent.index("C-USDT") > sent.index("B-USDT")


def test_the_send_order_is_stable_within_each_group(test_database_url):
    """Reducing legs first, increasing legs after, each in the plan's order.

    A plan spelled [C increase, A reduce, D increase, B reduce] is sent
    [A, B, C, D]: the two groups keep the plan's own order inside them,
    so a re-run of the same plan sends the same sequence — the only
    change the fix makes to the placement path.
    """
    client = _NettingClient(positions=HELD)
    plan = [
        _leg(symbol="C-USDT", side=BINGX_BUY, quantity="30"),
        _leg(symbol="A-USDT", side=BINGX_SELL, quantity="50"),
        _leg(symbol="D-USDT", side=BINGX_BUY, quantity="10"),
        _leg(symbol="B-USDT", side=BINGX_BUY, quantity="50"),
    ]

    _place(client, plan, test_database_url)

    assert [order.symbol for order in client.placed] == [
        "A-USDT",
        "B-USDT",
        "C-USDT",
        "D-USDT",
    ]


def test_the_live_shortfall_passes_once_netted_and_refuses_without_the_release(
    test_database_url,
):
    """The live case, as Decimals: 1164.35 available, an increasing side
    of 1173.5 (1179.3675 at the door's headroom — the log's 1179.03
    shape) and a reducing leg that releases 15.

    Netted, the term answers 1164.2925 and the plan the door refused at
    20:05 and 00:05 UTC places.  The same plan with releases 0 — its
    increasing leg unchanged and no reducing leg beside it — is refused
    with the same message the door answered before the fix, naming the
    un-netted 1179.3675, and nothing is asked of the venue.
    """
    balance = {"balance": {"asset": "USDT", "availableMargin": LIVE_AVAILABLE}}
    increase_leg = _leg(
        symbol="C-USDT", side=BINGX_BUY, quantity=LIVE_INCREASE_QUANTITY
    )
    reduce_leg = _leg(
        symbol="A-USDT", side=BINGX_SELL, quantity=LIVE_RELEASE_QUANTITY
    )
    held = (
        {"symbol": "A-USDT", "positionSide": "LONG", "positionAmt": "100"},
    )

    netted = _NettingClient(positions=held, balance=balance)
    outcomes = _place(netted, [reduce_leg, increase_leg], test_database_url)
    assert [outcome.outcome for outcome in outcomes.values()] == [
        MIRROR_OUTCOME_PLACED
    ] * 2

    increase_only = _NettingClient(positions=held, balance=balance)
    with pytest.raises(RouterBingXInsufficientBalanceError) as raised:
        _place(increase_only, [increase_leg], test_database_url)

    message = str(raised.value)
    assert message.startswith(
        "insufficient_balance: available USDT 1164.35 is below the "
        "1179.3675 this plan's orders need"
    )
    assert "fund the VST account and run the preflight again" in message
    assert increase_only.placed == []
    # The refusal names what was netted: the term it carries states both
    # sides, so an operator reading the refusal sees the zero release and
    # the increase it failed to cover — no re-derivation from the plan.
    assert raised.value.required_usdt == Decimal("1179.3675")
    assert raised.value.required_usdt.increase_usdt == Decimal("1173.5")
    assert raised.value.required_usdt.release_usdt == Decimal(0)


def test_the_preflights_report_carries_both_sides_of_the_netted_term():
    """``run_bingx_preflight``'s own record answers the two netted fields.

    The term the mirror hands the preflight is the one seam the fix may
    use — the preflight's signature and refusals are untouched — so the
    two fields ride it: the report's ``required_usdt`` answers the netted
    value and, beside it, the increase and the release it netted.
    """
    client = _NettingClient(
        positions=(
            {"symbol": "A-USDT", "positionSide": "LONG", "positionAmt": "100"},
        ),
        balance={"balance": {"asset": "USDT", "availableMargin": LIVE_AVAILABLE}},
    )
    orders = [
        _leg(symbol="A-USDT", side=BINGX_SELL, quantity=LIVE_RELEASE_QUANTITY),
        _leg(symbol="C-USDT", side=BINGX_BUY, quantity=LIVE_INCREASE_QUANTITY),
    ]

    report = run_bingx_preflight(
        client,
        required_usdt=plan_required_margin(client=client, orders=orders),
        symbols=[order.symbol for order in orders],
        database_url=None,
        clock=lambda: LOCAL_MILLIS,
    )

    assert report.required_usdt == Decimal("1164.2925")
    assert report.required_usdt.increase_usdt == Decimal("1173.5")
    assert report.required_usdt.release_usdt == Decimal(15)
    assert report.symbols == ("A-USDT", "C-USDT")
