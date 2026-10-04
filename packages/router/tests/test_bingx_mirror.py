"""Tests for :mod:`router.bingx_mirror` — the command's own behaviour.

Feature 4 of additions_spec_bingx_vst_mirror.xml, held clause by clause:

*It fetches the contracts and premiumIndex documents from VST, replaces the
book's positions with the account's live VST positions, and builds the plan
with dry_run_plan.  Without ``--place`` it prints the plan in Stage 0's
JSON-lines format and exits 0 while placing nothing.  With ``--place`` it
requires ``DATABASE_URL`` and runs the preflight.  Then it places each order
through RouterOrderPlacementStore.place, acquiring RouterRateLimiter weight
and retrying 429s with retry_rate_limited.  It prints one JSON line per leg:
placed, prior (already placed), or refused with its code.  It exits 0 when
every order was placed or was already placed, and 1 otherwise.  When a POST
/trade/order times out or its connection drops, the outcome is unknown.  The
mirror then queries that clientOrderID before doing anything else.  A found
order is recorded as placed, and only a not_found answer is re-posted, so a
blind retry never meets BingX's duplicate-clientOrderID refusal for an order
that actually landed.  ``--status`` prints feature 3's read-back, and
``--cancel`` cancels the rebalance's open orders.*

Every test injects a client double, a store and a limiter — no test opens a
socket.  The fixtures are inputs and are never edited; the plan is read
through :func:`router.bingx_dry_run.dry_run_plan` exactly as the mirror
builds it.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from router.bingx_client import (
    ORDER_NOT_FOUND_CODE,
    VST_HOST,
    RouterBingXRefusedError,
    RouterBingXTransportError,
)
from router.bingx_mirror import (
    DATABASE_URL_MISSING_CODE,
    MIRROR_CODE,
    MIRROR_OUTCOME_PLACED,
    MIRROR_OUTCOME_PRIOR,
    MIRROR_OUTCOME_REFUSED,
    PLACEMENT_FIELD,
    REQUIRED_MARGIN_HEADROOM,
    VST_MIRROR_WEIGHT_SCHEDULE,
    MirrorLeg,
    RouterBingXMirrorError,
    _full_identifier,
    build_mirror_plan,
    live_positions,
    main,
    mirror_place,
    plan_required_margin,
    rebalance_order_identities,
)
from router.bingx_order import (
    BINGX_BUY,
    BINGX_LIMIT_ORDER,
    BINGX_MARKET_ORDER,
    BINGX_POST_ONLY,
    BINGX_SELL,
    BingXOrder,
    BingXRefusedLeg,
)
from router.bingx_preflight import RouterBingXInsufficientBalanceError
from router.errors import RouterRateLimitedError
from router.limiter import (
    DEFAULT_WEIGHT_SCOPE,
    OPERATION_PLACE_ORDER,
    OPERATION_QUERY_ORDER,
    RateLimitHeadroom,
)
from router.retry import RetryEventLog
from router.submission_result import RouterOrderPlacementStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: A local clock the tests pin; the preflight compares it against the
#: double's server time, which the tests keep equal so no skew is refused.
LOCAL_MILLIS = 1_700_000_000_123

#: The venue's well-formed account payloads the preflight reads.  The
#: balance is comfortably above the synthetic book's 10000 USDT equity.
BALANCE = {"balance": {"asset": "USDT", "availableMargin": "100000"}}


def _clock() -> int:
    """The pinned local clock the preflight's skew is measured against."""
    return LOCAL_MILLIS


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _book() -> dict:
    return _load("synthetic_book.json")


def _live_positions_data() -> list:
    """The recorded VST one-way account's positions, verbatim.

    The fixture is an input and is never edited: it is the live capture
    (``capture.json`` of 2026-10-03) that pinned this defect — a SHORT
    reported with an *unsigned* positive ``positionAmt`` and the direction
    only in ``positionSide``.  Every regression test below reads it through
    :func:`router.bingx_client.BingXClient.positions`' own envelope, never a
    hand-written row.
    """
    document = _load("live/positions_one_way_short.json")
    return document["data"]


def _live_depth_data() -> dict:
    """The recorded VST order book for ETH-USDT, verbatim under ``data``.

    The fixture is an input and is never edited: it is the live capture
    (``capture.json`` of 2026-10-03) that pinned this defect — a book whose
    best bid is 2665.89 and best ask 2673.27 while the premiumIndex's mark
    is 2685.87, several ticks *above* the ask.  A PostOnly BUY priced at the
    mark crosses that book and the venue refuses it (BingX 101215 — three
    of the four orders in the live smoke test); priced at the book's own
    side, the best bid, it rests.  Tests read it through
    :func:`router.bingx_client.BingXClient.depth`'s own envelope, never a
    hand-written row.
    """
    document = _load("live/depth_eth_usdt.json")
    return document["data"]


def _live_balance_data() -> dict:
    """The recorded VST account's balance row, verbatim under ``data``.

    The fixture is an input and is never edited: it is the live capture
    (``live/balance.json`` of 2026-10-03) that pinned this defect — an
    account answering ``availableMargin`` 7503.0716 with 2496.2791
    already used by the book's own BTC long and DOGE short, against a
    book whose whole ``equity_usdt`` is 10000.  Tests read it through the
    client's own ``balance()`` envelope, never a hand-written row.
    """
    document = _load("live/balance.json")
    return document["data"]


def _book_with_eth_buy() -> dict:
    """The synthetic book with ETH's weight flipped, so ETH is a BUY leg.

    The book's own ETH weight is -0.15 (a SELL on a flat account); +0.15
    makes ETH the one passive BUY leg whose mark, 2685.87, sits above the
    recorded book's best ask, 2673.27 — the exact shape the reproduce
    clause names: *a BUY leg whose mark is above the best ask in a recorded
    depth answer*.
    """
    book = _book()
    book["weights"] = dict(book["weights"])
    book["weights"]["ETH-USDT"] = 0.15
    return book


#: The DOGE weight whose target truncates onto the contract grid to exactly
#: ``-5402`` — the size the recorded one-way short account holds — so a
#: plan built over that account sizes no DOGE leg at all: the symbol is
#: already at its target.  The identity terms are untouched, so DOGE's
#: clientOrderID is the same as the plain book's.
DOGE_AT_TARGET_WEIGHT = -0.0506762


def _book_with_doge_at_target() -> dict:
    """The synthetic book with DOGE's weight set to the recorded holding.

    The state the nullius01 account reached once its rebalance's DOGE leg
    filled: the account holds DOGE ``-5402`` (the recorded fixture), this
    book's DOGE target is exactly that, and today's plan — re-sized against
    the live positions — ships no DOGE leg while the rebalance's placed
    DOGE order still sits on the venue's book.
    """
    book = _book()
    book["weights"] = dict(book["weights"])
    book["weights"]["DOGE-USDT"] = DOGE_AT_TARGET_WEIGHT
    return book


def _placed_ids() -> dict[str, str]:
    """The 40-character projections of the rebalance's five placed orders.

    One per symbol the flat-account plan orders, each derived from the same
    ``(book_id, rebalance_ts, symbol)`` terms placement names orders with —
    the weights play no part, so the at-target book's DOGE order keeps this
    same identifier.
    """
    return {
        symbol: _full_identifier(_book(), symbol)[:40]
        for symbol in (
            "1000PEPE-USDT", "BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT"
        )
    }


class _MirrorClient:
    """A stand-in for feature 1's client: canned documents, recorded calls.

    Carries every face the mirror and the preflight read the venue through,
    so the double is a complete stand-in and no test opens a socket.
    ``place_effects`` is a list of callables consumed one per
    ``place_order`` call — each either returns (the venue took the order) or
    raises — so a test can stage a transport failure, a venue refusal or a
    429 on any attempt.  ``orders_held`` names the clientOrderIDs the venue
    claims to hold, which ``query_order`` answers for; everything else is
    the not-found refusal feature 3 translates.  ``query_answers`` stages a
    whole answer document per clientOrderID and wins over the plain held
    spelling — the state the recorded incident answers for its filled and
    resting legs.
    """

    def __init__(
        self,
        *,
        contracts: object = None,
        marks: object = None,
        positions: object = (),
        depths: dict[str, object] | None = None,
        server_time: int = LOCAL_MILLIS,
        balance: object = BALANCE,
        place_effects: list | None = None,
        orders_held: set[str] | None = None,
        query_answers: dict[str, dict] | None = None,
        open_orders: object = (),
    ) -> None:
        self._contracts = _load("contracts.json") if contracts is None else contracts
        self._marks = _load("premium_index.json") if marks is None else marks
        self._positions = positions
        self._depths = dict(depths or {})
        self._server_time = server_time
        self._balance = balance
        self._place_effects = list(place_effects or [])
        self._orders_held = set(orders_held or ())
        self._query_answers = dict(query_answers or {})
        self._open_orders = open_orders
        self.calls: list[tuple] = []
        self.placed: list[BingXOrder] = []

    # -- The mirror's three reads -------------------------------------------
    def contracts(self) -> object:
        self.calls.append(("contracts",))
        return self._contracts

    def premium_index(self) -> object:
        self.calls.append(("premium_index",))
        return self._marks

    def positions(self, symbol: str | None = None) -> object:
        self.calls.append(("positions", symbol))
        return self._positions

    # -- The mirror's repricing read ----------------------------------------
    def depth(self, symbol: str) -> object:
        """The symbol's order book, as the venue's depth answer spells it.

        A symbol staged under ``depths`` is answered with that payload
        verbatim (the recorded live capture for ETH-USDT); every other
        symbol is answered with a one-level book around its own mark, so a
        test that stages no depth still reprices at the price the plan
        already carries and the placed orders keep their shapes.
        """
        self.calls.append(("depth", symbol))
        staged = self._depths.get(symbol)
        if staged is not None:
            return staged
        mark = self._mark_price(symbol)
        return {"bids": [[mark, "1"]], "asks": [[mark, "1"]]}

    def _mark_price(self, symbol: str) -> str:
        rows = self._marks.get("data") if isinstance(self._marks, dict) else self._marks
        for row in rows or ():
            if row.get("symbol") == symbol:
                return row["markPrice"]
        raise AssertionError(f"the double holds no mark price for {symbol!r}")

    # -- The preflight's five faces -----------------------------------------
    def server_time(self) -> int:
        self.calls.append(("server_time",))
        return self._server_time

    def position_mode(self) -> bool:
        # One-way: the state every account these tests place on holds.
        self.calls.append(("position_mode",))
        return False

    def balance(self) -> object:
        self.calls.append(("balance",))
        return self._balance

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> object:
        self.calls.append(("set_margin_type", symbol, margin_type))
        return {}

    def set_leverage(
        self, symbol: str, leverage: int = 1, *, side: str = "BOTH"
    ) -> object:
        self.calls.append(("set_leverage", symbol, leverage, side))
        return {}

    # -- The order path ------------------------------------------------------
    def place_order(self, order: BingXOrder) -> object:
        self.calls.append(("place_order", order.symbol))
        self.placed.append(order)
        if self._place_effects:
            effect = self._place_effects.pop(0)
            return effect()
        return {"orderId": order.symbol}

    def query_order(self, client_order_id: str, *, symbol: str | None = None) -> object:
        self.calls.append(("query_order", client_order_id, symbol))
        staged = self._query_answers.get(client_order_id)
        if staged is not None:
            return staged
        if client_order_id in self._orders_held:
            return {
                "symbol": symbol,
                "clientOrderID": client_order_id,
                "status": "NEW",
                "executedQty": "0",
                "avgPrice": "0",
            }
        raise RouterBingXRefusedError(ORDER_NOT_FOUND_CODE, "order does not exist")

    def open_orders(self, symbol: str | None = None) -> object:
        self.calls.append(("open_orders", symbol))
        return self._open_orders

    def cancel_order(self, client_order_id: str, *, symbol: str | None = None) -> object:
        self.calls.append(("cancel_order", client_order_id, symbol))
        return {}


def _rate_limited(operation: str = OPERATION_PLACE_ORDER) -> RouterRateLimitedError:
    """A well-formed rate-limit refusal, as feature 1 raises on a 429.

    Every field a :class:`RateLimitHeadroom` requires, so the refusal
    carries a reading feature 319's backoff can pace — the shape feature 1
    raises when the venue answers HTTP 429.
    """
    reading = RateLimitHeadroom(
        scope=DEFAULT_WEIGHT_SCOPE,
        operation=operation,
        weight=1,
        allowed=False,
        remaining=0,
        capacity=VST_MIRROR_WEIGHT_SCHEDULE.allowance,
        accrued=0,
        observed_at=datetime.now(UTC),
        schedule=VST_MIRROR_WEIGHT_SCHEDULE,
    )
    return RouterRateLimitedError(
        f"rate_limited: the venue refused {operation!r}", headroom=reading
    )


class _CountingLimiter:
    """A limiter double: records every acquire, meters nothing.

    The mirror's law is that every send — every attempt, including a
    re-send — prices itself through :meth:`RouterRateLimiter.acquire`.  The
    suite proves exactly that by counting the calls; the real bucket is
    exercised end to end elsewhere, and using it here would make the store
    and the limiter contend for one sqlite file while a placement is still
    open.  A 429 in these tests is raised by the *venue* — feature 1's
    refusal, out of ``place_order`` — which is what the backoff absorbs and
    what makes the re-send re-acquire.
    """

    def __init__(self) -> None:
        self.operations: list[str] = []

    def acquire(self, operation: str, *, now: datetime | None = None):
        self.operations.append(operation)
        return object()


def _transport_unknown() -> RouterBingXTransportError:
    """A write whose response never arrived — the unknown outcome."""
    return RouterBingXTransportError(
        "POST", f"https://{VST_HOST}/openApi/swap/v2/trade/order",
        "socket timed out", outcome_unknown=True,
    )


def _plan(client: _MirrorClient, book: dict | None = None) -> list:
    return build_mirror_plan(book=book or _book(), client=client)


def _order_symbols(plan: list) -> list[str]:
    return [leg.symbol for leg in plan if isinstance(leg, BingXOrder)]


def _manual_order(
    *, symbol: str, side: str, order_type: str, quantity: str, price: str | None = None
) -> BingXOrder:
    """A hand-built order leg, for driving the margin arithmetic directly.

    Carries the one-way spelling every assembled order carries, so the
    plan's own value type answers :func:`plan_required_margin` without a
    full book, sizer and gate run behind it — the arithmetic's terms
    (side, type, quantity, price) stated and nothing else.
    """
    return BingXOrder(
        symbol=symbol,
        side=side,
        position_side="BOTH",
        type=order_type,
        quantity=quantity,
        price=price,
        time_in_force=BINGX_POST_ONLY if order_type == BINGX_LIMIT_ORDER else None,
        client_order_id=f"margin-{symbol}-{side}".lower()[:40],
    )


# -- Reading the plan ----------------------------------------------------------


def test_plan_fetches_the_venues_own_documents_once_each():
    client = _MirrorClient()
    _plan(client)
    fetches = [c for c in client.calls if c[0] in ("contracts", "premium_index")]
    assert fetches == [("contracts",), ("premium_index",)]


def test_plan_reads_the_accounts_live_positions():
    client = _MirrorClient()
    _plan(client)
    assert ("positions", None) in client.calls


def test_flat_account_yields_five_orders_and_two_refusals():
    plan = _plan(_MirrorClient())
    assert _order_symbols(plan) == [
        "1000PEPE-USDT", "BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT"
    ]
    refusals = {
        leg.symbol: leg.code for leg in plan if isinstance(leg, BingXRefusedLeg)
    }
    assert refusals == {
        "AGLD-USDT": "below_min_notional",
        "NCFXUSD2ARS-USDT": "not_tradable",
    }


def test_replaced_positions_change_the_sized_delta():
    """A held BTC position is subtracted from its target, unlike a flat one."""
    flat = {leg.symbol: leg for leg in _plan(_MirrorClient())}
    held = {
        leg.symbol: leg
        for leg in _plan(
            _MirrorClient(
                positions=[{"symbol": "BTC-USDT", "positionAmt": "0.0100"}]
            )
        )
        if isinstance(leg, BingXOrder)
    }
    assert flat["BTC-USDT"].quantity != held["BTC-USDT"].quantity


def test_the_book_document_is_never_mutated():
    book = _book()
    original = dict(book)
    _plan(_MirrorClient(), book=book)
    assert book == original
    assert book["positions"] == {"BTC-USDT": "0.0100"}


def test_the_plan_uses_the_venues_marks_not_the_books_positions():
    """A held position the book never states is still sized away."""
    client = _MirrorClient(
        positions=[{"symbol": "ETH-USDT", "positionAmt": "-0.5"}]
    )
    orders = {leg.symbol: leg for leg in _plan(client) if isinstance(leg, BingXOrder)}
    # ETH's book weight is -0.15; with 0.5 already held short the delta is
    # smaller than the flat-account delta would be.
    flat = {leg.symbol: leg for leg in _plan(_MirrorClient()) if isinstance(leg, BingXOrder)}
    assert orders["ETH-USDT"].quantity != flat["ETH-USDT"].quantity


def test_a_non_mapping_book_is_refused():
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        build_mirror_plan(book=[], client=_MirrorClient())
    assert MIRROR_CODE in str(excinfo.value)


# -- Live positions ------------------------------------------------------------


def test_live_positions_none_is_a_flat_account():
    assert live_positions(_MirrorClient(positions=None)) == {}


def test_live_positions_reads_the_position_amt_spelling():
    # A row carrying no ``positionSide`` has only the amount's own sign to
    # read, and the answer is the exact Decimal the sizer reads verbatim.
    client = _MirrorClient(
        positions=[{"symbol": "BTC-USDT", "positionAmt": "-0.0100"}]
    )
    assert live_positions(client) == {"BTC-USDT": Decimal("-0.0100")}


def test_live_positions_reads_the_older_position_spelling():
    client = _MirrorClient(positions=[{"symbol": "DOGE-USDT", "position": "12"}])
    assert live_positions(client) == {"DOGE-USDT": Decimal(12)}


# -- The recorded live account: a short is reported unsigned -------------------


def test_live_positions_reads_the_recorded_short_as_negative():
    """The defect, pinned against the verbatim VST capture.

    ``live/positions_one_way_short.json`` is the live account's own answer:
    a DOGE-USDT short of 5402 reported as ``positionAmt`` ``"5402"`` — a
    positive amount — with the direction only in ``positionSide``
    ``"SHORT"``, beside a LONG BTC-USDT row.  A reader that trusts the
    amount alone answers ``+5402`` and doubles the short on the next
    placement, so the signed answer is asserted here, not a hand-written
    row's.
    """
    client = _MirrorClient(positions=_live_positions_data())
    assert live_positions(client) == {
        "DOGE-USDT": Decimal(-5402),
        "BTC-USDT": Decimal("0.0236"),
    }


def test_live_positions_answers_exact_decimals():
    """The signed answer is exact — never a float approximation."""
    client = _MirrorClient(positions=_live_positions_data())
    held = live_positions(client)
    assert all(isinstance(value, Decimal) for value in held.values())


def test_live_positions_a_both_row_keeps_its_own_sign():
    """One-way labelling aside, a BOTH row's amount is already signed."""
    client = _MirrorClient(
        positions=[{"symbol": "ETH-USDT", "positionAmt": "-0.5", "positionSide": "BOTH"}]
    )
    assert live_positions(client) == {"ETH-USDT": Decimal("-0.5")}


def test_live_positions_a_lone_negative_amount_keeps_its_sign():
    """A row stating no side carries the sign in the amount it spells."""
    client = _MirrorClient(positions=[{"symbol": "ETH-USDT", "positionAmt": "-0.5"}])
    assert live_positions(client) == {"ETH-USDT": Decimal("-0.5")}


def test_live_positions_a_short_with_a_negative_amount_is_refused():
    """SHORT beside a negative amount disagrees; refuse it, never guess."""
    client = _MirrorClient(
        positions=[
            {"symbol": "DOGE-USDT", "positionAmt": "-5402", "positionSide": "SHORT"}
        ]
    )
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        live_positions(client)
    assert "DOGE-USDT" in str(excinfo.value)


def test_live_positions_a_long_with_a_negative_amount_is_refused():
    client = _MirrorClient(
        positions=[
            {"symbol": "BTC-USDT", "positionAmt": "-0.01", "positionSide": "LONG"}
        ]
    )
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        live_positions(client)
    assert "BTC-USDT" in str(excinfo.value)


def test_live_positions_a_short_with_a_negative_older_spelling_is_refused():
    """The older ``position`` spelling carries the same disagreement."""
    client = _MirrorClient(
        positions=[
            {"symbol": "DOGE-USDT", "position": "-5402", "positionSide": "SHORT"}
        ]
    )
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        live_positions(client)
    assert "DOGE-USDT" in str(excinfo.value)


def test_live_positions_refuses_an_unknown_symbol_side():
    """A side the venue's vocabulary does not carry is refused, not assumed."""
    client = _MirrorClient(
        positions=[{"symbol": "DOGE-USDT", "positionAmt": "5", "positionSide": "FLAT"}]
    )
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        live_positions(client)
    assert "DOGE-USDT" in str(excinfo.value)


def test_a_symbol_already_at_its_target_ships_no_order():
    """The recorded short, at its own target, sizes to nothing.

    With the account's DOGE holding read as ``-5402`` (the fixture) and a
    book whose DOGE target truncates to exactly ``-5402`` contracts, the
    delta is zero and no order ships.  Read as ``+5402`` — the defect —
    the delta would be ``-10804`` and a market SELL of about 10804 would
    be sent, doubling the short.
    """
    book = _book()
    # -5402 × 0.09381 (DOGE's mark) ÷ 10000 equity, as a weight whose
    # target truncates onto the contract grid to exactly -5402.
    book["weights"] = dict(book["weights"])
    book["weights"]["DOGE-USDT"] = -0.0506762
    client = _MirrorClient(positions=_live_positions_data())
    legacy = build_mirror_plan(book=book, client=client)
    by_symbol = {leg.symbol: leg for leg in legacy}
    assert "DOGE-USDT" not in _order_symbols(legacy)
    # BTC-USDT is held long (0.0236) at a target of 0.0240: a small BUY
    # remains, so the plan is not empty.
    assert by_symbol["BTC-USDT"].quantity == "0.0004"


def test_live_positions_refuses_a_float_size():
    client = _MirrorClient(positions=[{"symbol": "BTC-USDT", "positionAmt": 0.01}])
    with pytest.raises(RouterBingXMirrorError):
        live_positions(client)


def test_live_positions_refuses_a_row_without_a_symbol():
    client = _MirrorClient(positions=[{"positionAmt": "1"}])
    with pytest.raises(RouterBingXMirrorError):
        live_positions(client)


def test_live_positions_refuses_a_row_without_a_size():
    client = _MirrorClient(positions=[{"symbol": "BTC-USDT"}])
    with pytest.raises(RouterBingXMirrorError):
        live_positions(client)


def test_live_positions_refuses_a_non_array_payload():
    client = _MirrorClient(positions={"BTC-USDT": "1"})
    with pytest.raises(RouterBingXMirrorError):
        live_positions(client)


def test_live_positions_refuses_a_client_without_the_method():
    class Bare:
        pass

    with pytest.raises(RouterBingXMirrorError):
        live_positions(Bare())


# -- The full identifier -------------------------------------------------------


def test_full_identifier_is_sixty_four_hex_and_prefixes_the_projection():
    book = _book()
    for leg in _plan(_MirrorClient()):
        if isinstance(leg, BingXOrder):
            full = _full_identifier(book, leg.symbol)
            assert len(full) == 64
            assert full.startswith(leg.client_order_id)


def test_full_identifier_needs_a_book_id():
    with pytest.raises(RouterBingXMirrorError):
        _full_identifier({"rebalance_ts": "2026-09-30T00:00:00+00:00"}, "BTC-USDT")


def test_full_identifier_refuses_a_naive_rebalance():
    with pytest.raises(RouterBingXMirrorError):
        _full_identifier(
            {"book_id": "b", "rebalance_ts": "2026-09-30T00:00:00"}, "BTC-USDT"
        )


# -- The rebalance's order identities -------------------------------------------


def test_rebalance_order_identities_answers_one_name_per_book_symbol():
    """The order set --status and --cancel address: one identifier per
    symbol the book's weights name — including the two the gates refuse —
    in the book's own order, each the 40-character projection of the same
    derivation placement names its orders with."""
    book = _book()
    orders = rebalance_order_identities(book)

    assert [order["symbol"] for order in orders] == list(book["weights"])
    assert all(len(order["clientOrderID"]) == 40 for order in orders)
    for symbol in book["weights"]:
        expected = _full_identifier(book, symbol)[:40]
        order = next(o for o in orders if o["symbol"] == symbol)
        assert order["clientOrderID"] == expected


def test_rebalance_order_identities_ignores_the_weights_own_values():
    """Identity folds (book_id, rebalance_ts, symbol) — never the weight —
    so the at-target book's DOGE order keeps the plain book's name, which
    is the whole reason a dropped leg can still be found by it."""
    plain = rebalance_order_identities(_book())
    at_target = rebalance_order_identities(_book_with_doge_at_target())
    assert plain == at_target


def test_rebalance_order_identities_refuses_a_book_without_weights():
    book = _book()
    del book["weights"]
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        rebalance_order_identities(book)
    assert MIRROR_CODE in str(excinfo.value)


def test_rebalance_order_identities_refuses_an_empty_weights_mapping():
    book = _book()
    book["weights"] = {}
    with pytest.raises(RouterBingXMirrorError):
        rebalance_order_identities(book)


def test_rebalance_order_identities_refuses_a_weight_keyed_by_no_symbol():
    book = _book()
    book["weights"] = {**book["weights"], "": 0.1}
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        rebalance_order_identities(book)
    assert MIRROR_CODE in str(excinfo.value)


# -- mirror_place: the happy path ---------------------------------------------


def _place(client, plan, store, limiter, book=None, **kwargs):
    return mirror_place(
        client=client,
        book=book or _book(),
        plan=plan,
        store=store,
        limiter=limiter,
        database_url=kwargs.pop("database_url", "sqlite:///:memory:"),
        clock=kwargs.pop("clock", _clock),
        sleep=kwargs.pop("sleep", lambda _d: None),
        **kwargs,
    )


def test_place_runs_the_preflight_before_any_order_leaves(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    first_place = next(
        i for i, call in enumerate(client.calls) if call[0] == "place_order"
    )
    # Every preflight read precedes the first placement.
    for read in ("server_time", "balance", "set_margin_type", "set_leverage"):
        assert any(call[0] == read for call in client.calls[:first_place])


def test_place_sends_each_order_once_and_reports_placed(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert len(client.placed) == 5
    assert all(o.outcome == MIRROR_OUTCOME_PLACED for o in outcomes.values())
    assert set(outcomes) == set(_order_symbols(_plan(_MirrorClient())))


def test_a_second_place_sends_nothing_and_reports_prior(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    assert len(client.placed) == 5

    second = _MirrorClient()
    outcomes = _place(
        second, _plan(second), store, limiter, database_url=test_database_url
    )
    assert second.placed == []
    assert all(o.outcome == MIRROR_OUTCOME_PRIOR for o in outcomes.values())


def test_the_weight_is_acquired_once_per_send(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    assert limiter.operations == [OPERATION_PLACE_ORDER] * 5


def test_a_refused_leg_is_not_placed_but_its_siblings_are(test_database_url):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    plan = _plan(client)
    outcomes = _place(client, plan, store, limiter, database_url=test_database_url)
    placed_symbols = set(outcomes)
    refused = {
        leg.symbol for leg in plan if isinstance(leg, BingXRefusedLeg)
    }
    assert placed_symbols.isdisjoint(refused)


# -- mirror_place: the balance door judges the plan's own orders ----------------


def test_rebalancing_a_book_that_already_holds_positions_passes_the_balance_door(
    test_database_url,
):
    """The defect, replayed over the recorded account.

    The reproduce clause's exact state: a book of equity 10000 whose BTC
    long 0.0236 and DOGE short 5402 (the verbatim rows of
    ``live/positions_one_way_short.json``) already use 2496.28 of margin,
    against the verbatim balance row of ``live/balance.json`` answering
    availableMargin 7503.0716.  The plan then needs only the remaining
    legs — about 2800 of new margin at 1x, well within 7503 — but the old
    door compared availableMargin with the book's whole equity_usdt and
    refused every rebalance of a holding book (and comparing the
    account's equity, 9999.28, would have refused too, after the
    unrealised loss).  The door now judges the margin the orders about to
    be sent need, so the remaining legs leave.
    """
    client = _MirrorClient(
        positions=_live_positions_data(), balance=_live_balance_data()
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)

    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )

    # The DOGE leg reduces the recorded short and the BTC leg tops up the
    # recorded long; both are orders about to be sent, and both leave.
    assert client.placed, "the balance door refused a fundable rebalance"
    assert all(o.outcome == MIRROR_OUTCOME_PLACED for o in outcomes.values())
    assert {o.symbol for o in client.placed} == set(outcomes)


def test_the_balance_door_refuses_when_the_account_cannot_fund_the_plan(
    test_database_url,
):
    """Below the required margin the door refuses, and nothing is asked.

    The same recorded account with its availableMargin read down to 100 —
    below the about-2800 the remaining legs need — refuses with the
    correction's own message, naming both decimals and the one repair,
    and the door closes before the venue is asked to hold a single margin
    arrangement or book a single order.
    """
    client = _MirrorClient(
        positions=_live_positions_data(),
        balance={"balance": {"asset": "USDT", "availableMargin": "100"}},
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)

    with pytest.raises(RouterBingXInsufficientBalanceError) as raised:
        _place(client, _plan(client), store, limiter, database_url=test_database_url)

    message = str(raised.value)
    assert message.startswith(
        "insufficient_balance: available USDT 100 is below the "
    )
    assert "this plan's orders need; fund the VST account and run the " \
        "preflight again" in message
    assert client.placed == []
    assert not [call for call in client.calls if call[0] == "set_margin_type"]


def test_the_required_margin_counts_only_what_grows_a_position():
    """The arithmetic the door judges, term by term.

    Five legs over three held positions, one of every shape the law
    names: a passive BUY from flat (BTC, at its own limit price), a
    passive SELL that only reduces a long (ETH, free), a passive SELL
    that crosses through zero (1000PEPE, counted only beyond it), a
    MARKET BUY from flat (SOL, at the fixture document's own mark
    118.392) and a MARKET BUY that only reduces a short (DOGE, free).
    Only the growing parts count, at the preflight's leverage of one,
    and the total carries the half-percent headroom.
    """
    client = _MirrorClient(
        positions=(
            {"symbol": "ETH-USDT", "positionSide": "LONG", "positionAmt": "2"},
            {"symbol": "DOGE-USDT", "positionSide": "SHORT", "positionAmt": "100"},
            {"symbol": "1000PEPE-USDT", "positionSide": "LONG", "positionAmt": "2"},
        )
    )
    orders = [
        # From flat: the whole 0.5 × the order's own limit price.
        _manual_order(
            symbol="BTC-USDT",
            side=BINGX_BUY,
            order_type=BINGX_LIMIT_ORDER,
            quantity="0.5",
            price="83000",
        ),
        # Reduces a long of 2: no new margin at any price.
        _manual_order(
            symbol="ETH-USDT",
            side=BINGX_SELL,
            order_type=BINGX_LIMIT_ORDER,
            quantity="1",
            price="2600",
        ),
        # Crosses through zero: only the 3 beyond it counts.
        _manual_order(
            symbol="1000PEPE-USDT",
            side=BINGX_SELL,
            order_type=BINGX_LIMIT_ORDER,
            quantity="5",
            price="0.0044",
        ),
        # MARKET from flat: the mark price the order itself does not carry.
        _manual_order(
            symbol="SOL-USDT",
            side=BINGX_BUY,
            order_type=BINGX_MARKET_ORDER,
            quantity="8",
        ),
        # Reduces a short of 100: free, though it is a BUY.
        _manual_order(
            symbol="DOGE-USDT",
            side=BINGX_BUY,
            order_type=BINGX_MARKET_ORDER,
            quantity="40",
        ),
    ]

    margin = plan_required_margin(client=client, orders=orders)

    bare = (
        Decimal("0.5") * Decimal(83000)
        + Decimal(3) * Decimal("0.0044")
        + Decimal(8) * Decimal("118.392")
    )
    assert margin == bare * REQUIRED_MARGIN_HEADROOM
    assert margin == Decimal("42659.384946")


def test_an_all_reducing_or_empty_plan_needs_no_margin(test_database_url):
    """Zero need passes the door on an account with nothing available.

    The bug spec's own boundary: a plan whose every leg shrinks a holding
    binds none of the account's money, so availableMargin 0 funds it; an
    empty plan — every leg already at its target — binds none either and
    prepares nothing, while the door still opens and answers.
    """
    reducing = _MirrorClient(
        positions=(
            {"symbol": "ETH-USDT", "positionSide": "LONG", "positionAmt": "10"},
        ),
        balance={"balance": {"asset": "USDT", "availableMargin": "0"}},
    )
    outcomes = _place(
        reducing,
        [
            _manual_order(
                symbol="ETH-USDT",
                side=BINGX_SELL,
                order_type=BINGX_MARKET_ORDER,
                quantity="1",
            )
        ],
        RouterOrderPlacementStore(test_database_url),
        _CountingLimiter(),
        database_url=test_database_url,
    )
    assert outcomes["ETH-USDT"].outcome == MIRROR_OUTCOME_PLACED

    flat = _MirrorClient(
        balance={"balance": {"asset": "USDT", "availableMargin": "0"}}
    )
    assert _place(
        flat, [], RouterOrderPlacementStore(test_database_url),
        _CountingLimiter(),
        database_url=test_database_url,
    ) == {}


# -- mirror_place: passive legs price at the order book -------------------------


def test_a_passive_buy_leg_is_priced_at_the_best_bid_not_the_mark(test_database_url):
    """The defect, pinned against the recorded book.

    The premiumIndex mark for ETH-USDT is 2685.87 — several ticks above the
    recorded book's best ask of 2673.27 — so a PostOnly BUY priced at the
    mark crosses the book and the venue refuses it (101215, three of the
    four orders in the live smoke test).  Priced at the book's own side —
    the best bid, 2665.89, on the tick grid — the order rests.  The double
    accepts either price, which is the point: only the venue's book says
    which one crosses, so the mirror must ask it before placing.
    """
    book = _book_with_eth_buy()
    client = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, build_mirror_plan(book=book, client=client), store, limiter,
        book=book, database_url=test_database_url,
    )
    assert outcomes["ETH-USDT"].outcome == MIRROR_OUTCOME_PLACED
    eth = next(order for order in client.placed if order.symbol == "ETH-USDT")
    assert eth.side == "BUY"
    assert eth.type == "LIMIT"
    assert eth.price == "2665.89"


def test_a_passive_sell_leg_is_priced_at_the_best_ask_not_the_mark(test_database_url):
    """The SELL mirror of the BUY defect, against the same recorded book.

    The book's own ETH weight is -0.15, so the flat-account plan already
    carries the SELL leg; at the recorded book the best ask is 2673.27,
    below the mark of 2685.87 — a PostOnly SELL priced at the mark is
    *through* the bid side by the same several ticks, and refuses.
    """
    book = _book()
    client = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, build_mirror_plan(book=book, client=client), store, limiter,
        book=book, database_url=test_database_url,
    )
    assert outcomes["ETH-USDT"].outcome == MIRROR_OUTCOME_PLACED
    eth = next(order for order in client.placed if order.symbol == "ETH-USDT")
    assert eth.side == "SELL"
    assert eth.price == "2673.27"


def test_a_book_quote_off_the_tick_grid_rounds_onto_it_away_from_crossing(
    test_database_url,
):
    """The quote is rounded by Stage 0's own grid rule, never sent raw.

    A staged best bid of 2665.895 sits half a tick off ETH's 0.01 grid; a
    BUY may not round up toward the crossing, so the price rests at
    2665.89.  The rounding is the gate's own — the mirror hands the quote
    to the one door that owns the grid — and so is the answer's exact
    spelling: the grid's subtraction keeps the operand's scale
    (``"2665.890"``), a trailing zero this module must not re-format, so
    the assertion judges the value the venue reads, not the string.
    """
    book = _book_with_eth_buy()
    client = _MirrorClient(
        depths={"ETH-USDT": {"bids": [["2665.895", "45.451"]], "asks": []}}
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(
        client, build_mirror_plan(book=book, client=client), store, limiter,
        book=book, database_url=test_database_url,
    )
    eth = next(order for order in client.placed if order.symbol == "ETH-USDT")
    assert Decimal(eth.price) == Decimal("2665.89")


def test_an_aggressive_market_leg_is_sent_verbatim_without_a_depth_read(
    test_database_url,
):
    """A MARKET leg carries no price, so no book is read and no leg changes.

    DOGE is the plan's one aggressive leg (its decay horizon of 60s is
    shorter than the book's 120s fill expectation), and the bug report's
    own constraint fixes it: *aggressive (MARKET) legs are unchanged*.
    """
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    assert ("depth", "DOGE-USDT") not in client.calls
    doge = next(order for order in client.placed if order.symbol == "DOGE-USDT")
    assert doge.type == "MARKET"
    assert "price" not in doge.parameters()
    # The passive legs around it are the ones the book was read for.
    assert ("depth", "ETH-USDT") in client.calls


def test_the_repriced_order_keeps_the_plans_identity_and_the_store_key(
    test_database_url,
):
    """Identity folds book, rebalance and symbol — never price.

    The repriced leg must answer the same clientOrderID the plan derived
    and the same full 64-hex store key, or a re-run would not find the
    row and would place the same order twice under two names.
    """
    book = _book_with_eth_buy()
    client = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    plan = build_mirror_plan(book=book, client=client)
    _place(client, plan, store, limiter, book=book, database_url=test_database_url)
    planned = next(
        leg for leg in plan if isinstance(leg, BingXOrder) and leg.symbol == "ETH-USDT"
    )
    placed = next(order for order in client.placed if order.symbol == "ETH-USDT")
    assert placed.client_order_id == planned.client_order_id
    assert placed.price != planned.price  # the price moved to the book
    key = _full_identifier(book, "ETH-USDT")
    assert store.prior_result(key) is not None


def test_a_side_with_no_quote_refuses_the_leg_as_no_book(test_database_url):
    """A book with no bid on it leaves a BUY nowhere to rest.

    The staged ETH book quotes only asks — a BUY has no side of the book
    to price at — and the bug report names the answer: *a symbol whose
    book has no quote on that side is refused as no_book*.  A leg-level
    refusal: nothing is placed, nothing is recorded, the siblings still
    go.
    """
    book = _book_with_eth_buy()
    client = _MirrorClient(
        depths={"ETH-USDT": {"bids": [], "asks": [["2673.27", "39.807"]]}}
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, build_mirror_plan(book=book, client=client), store, limiter,
        book=book, database_url=test_database_url,
    )
    assert outcomes["ETH-USDT"].outcome == MIRROR_OUTCOME_REFUSED
    assert outcomes["ETH-USDT"].code == "no_book"
    assert all(o.symbol != "ETH-USDT" for o in client.placed)
    assert store.prior_result(_full_identifier(book, "ETH-USDT")) is None
    # The refusal is one leg's, not the run's.
    assert outcomes["BTC-USDT"].outcome == MIRROR_OUTCOME_PLACED


def test_a_repriced_leg_below_the_notional_floor_is_refused(test_database_url):
    """The repriced order is re-judged against the floor at its new price.

    1000PEPE's leg is 69446 contracts; at the staged best bid of 0.0000200
    the order is worth 1.39 USDT, below the venue's 2 USDT floor — a value
    the mark price (0.0043199, about 300 USDT) hid.  The gate's own code
    word refuses the leg, exactly as it would have at plan time.
    """
    client = _MirrorClient(
        depths={"1000PEPE-USDT": {"bids": [["0.0000200", "1000000"]], "asks": []}}
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_REFUSED
    assert outcomes["1000PEPE-USDT"].code == "below_min_notional"
    assert all(o.symbol != "1000PEPE-USDT" for o in client.placed)
    assert store.prior_result(_full_identifier(_book(), "1000PEPE-USDT")) is None


def test_a_prior_leg_is_never_repriced(test_database_url):
    """The store's send is the only place the book is read.

    A leg the store answers ``prior`` was placed by an earlier run at the
    price that run's book quoted; repricing it now would either send a
    second order for a leg the venue already holds or refuse a leg that
    already landed.  The depth read lives inside the send, so a prior
    answer reads no book at all.
    """
    first = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(first, _plan(first), store, limiter, database_url=test_database_url)

    second = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    outcomes = _place(
        second, _plan(second), store, limiter, database_url=test_database_url
    )
    assert second.placed == []
    assert all(o.outcome == MIRROR_OUTCOME_PRIOR for o in outcomes.values())
    assert not [call for call in second.calls if call[0] == "depth"]


class _DepthlessClient(_MirrorClient):
    """A client with every face but ``depth`` — the wiring fault."""

    depth = None


def test_a_client_without_a_depth_face_refuses_before_the_preflight(test_database_url):
    """The face is checked before the run's first side effect.

    A client that cannot read the book cannot price a passive leg, and the
    check must not wait for a leg to fail mid-run: it refuses with the
    method named, before the preflight's margin and leverage POSTs — the
    ordering that keeps a wiring fault from moving the account first.
    """
    client = _DepthlessClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    with pytest.raises(RouterBingXMirrorError) as excinfo:
        _place(client, _plan(client), store, limiter, database_url=test_database_url)
    assert "depth" in str(excinfo.value)
    assert client.placed == []
    assert not [call for call in client.calls if call[0] == "set_margin_type"]


def test_the_placed_line_prints_the_book_price_not_the_mark(
    tmp_path, test_database_url
):
    """The operator's line reports the order the venue was asked to take."""
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book_with_eth_buy()), encoding="utf-8")
    client = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    code, out, err = _run_main(
        ["--book", str(book_path), "--place"],
        client=client,
        store=store,
        limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 0
    assert err == ""
    eth = next(
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get("symbol") == "ETH-USDT"
    )
    assert eth["price"] == "2665.89"
    assert "2685.87" not in eth


def test_a_no_book_run_exits_one(tmp_path, test_database_url):
    """A refused leg still fails the run, even though nothing crossed."""
    book = _book_with_eth_buy()
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(book), encoding="utf-8")
    client = _MirrorClient(
        depths={"ETH-USDT": {"bids": [], "asks": [["2673.27", "39.807"]]}}
    )
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    code, out, _ = _run_main(
        ["--book", str(book_path), "--place"],
        client=client,
        store=store,
        limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 1
    refused = next(
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get("symbol") == "ETH-USDT"
    )
    assert refused[PLACEMENT_FIELD] == MIRROR_OUTCOME_REFUSED
    assert refused["code"] == "no_book"


def test_a_mirror_leg_refuses_a_sent_order_that_is_not_an_order():
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(symbol="BTC-USDT", outcome=MIRROR_OUTCOME_PLACED, order="LIMIT")


# -- mirror_place: refusals and the rate limit ---------------------------------


def test_a_venue_refusal_is_reported_with_its_code(test_database_url):
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(
            RouterBingXRefusedError(101204, "insufficient margin")
        )]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    first = outcomes["1000PEPE-USDT"]
    assert first.outcome == MIRROR_OUTCOME_REFUSED
    assert first.code == "101204"


def test_a_venue_refusal_is_reported_with_its_message(test_database_url):
    """The live smoke test's symptom: a code no documentation explains.

    Three PostOnly orders were refused as ``101215`` — a code in none of
    BingX's published pages — and the printed line carried the code alone,
    so the refusal's one legible fact, the venue's own ``msg``, was dropped
    between the client (which carries it verbatim) and the report.
    """
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(
            RouterBingXRefusedError(101215, "post-only order would take the market")
        )]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    first = outcomes["1000PEPE-USDT"]
    assert first.outcome == MIRROR_OUTCOME_REFUSED
    assert first.code == "101215"
    assert first.message == "post-only order would take the market"


def test_a_refusal_without_a_venue_message_carries_none(test_database_url):
    """A transport failure words nothing; its token is the class name."""
    client = _MirrorClient(
        place_effects=[
            lambda: (_ for _ in ()).throw(_transport_unknown()),
            lambda: (_ for _ in ()).throw(_transport_unknown()),
        ]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    first = outcomes["1000PEPE-USDT"]
    assert first.outcome == MIRROR_OUTCOME_REFUSED
    assert first.code == "RouterBingXTransportError"
    assert first.message is None


def test_a_rate_limited_send_is_retried_and_succeeds(test_database_url):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_rate_limited())])
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_PLACED
    # The refused attempt plus the re-send: two places for the first leg.
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 2


def test_a_retried_send_re_acquires_the_weight(test_database_url):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_rate_limited())])
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    # Five legs, six sends: the retried leg acquired twice.
    assert limiter.operations.count(OPERATION_PLACE_ORDER) == 6


def test_every_retry_emits_one_event(test_database_url):
    log = RetryEventLog()
    client = _MirrorClient(
        place_effects=[
            lambda: (_ for _ in ()).throw(_rate_limited()),
            lambda: (_ for _ in ()).throw(_rate_limited()),
        ]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(
        client, _plan(client), store, limiter,
        database_url=test_database_url, on_retry=log.record,
    )
    assert len(log) == 2


def test_an_exhausted_budget_reports_refused(test_database_url):
    client = _MirrorClient(
        place_effects=[
            lambda: (_ for _ in ()).throw(_rate_limited())
            for _ in range(4)
        ]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter,
        database_url=test_database_url, retries=3,
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_REFUSED


# -- The unknown outcome -------------------------------------------------------


def test_an_unknown_outcome_found_on_the_venue_is_placed_and_not_reposted(
    test_database_url,
):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_transport_unknown())])
    order_id = _plan(client)[0].client_order_id
    client._orders_held.add(order_id)
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_PLACED
    # Exactly one POST for that leg: the failure was resolved by asking.
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 1
    assert ("query_order", order_id, "1000PEPE-USDT") in client.calls


def test_an_unknown_outcome_not_found_is_reposted(test_database_url):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_transport_unknown())])
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_PLACED
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 2


def test_the_query_precedes_the_repost(test_database_url):
    client = _MirrorClient(place_effects=[lambda: (_ for _ in ()).throw(_transport_unknown())])
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    leg_calls = [
        call for call in client.calls
        if call[0] in ("place_order", "query_order")
        and "1000PEPE-USDT" in call
    ]
    assert [call[0] for call in leg_calls] == [
        "place_order", "query_order", "place_order"
    ]


def test_an_unknown_outcome_never_found_twice_is_refused(test_database_url):
    """A venue that keeps dropping the connection is not re-sent forever."""
    client = _MirrorClient(
        place_effects=[
            lambda: (_ for _ in ()).throw(_transport_unknown()),
            lambda: (_ for _ in ()).throw(_transport_unknown()),
        ]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_REFUSED
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 2


def test_a_read_transport_failure_is_refused_without_a_repost(test_database_url):
    """A GET whose connection failed cannot be resolved by asking again."""
    def fail_read(*_args, **_kwargs):
        raise RouterBingXTransportError(
            "GET", f"https://{VST_HOST}/openApi/swap/v2/trade/order",
            "connection reset", outcome_unknown=False,
        )

    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(_transport_unknown())]
    )
    client.query_order = fail_read  # type: ignore[assignment]
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    # The unresolved write is a refused leg, never a second POST.
    assert outcomes["1000PEPE-USDT"].outcome == MIRROR_OUTCOME_REFUSED
    assert outcomes["1000PEPE-USDT"].code == "RouterBingXTransportError"
    assert client.calls.count(("place_order", "1000PEPE-USDT")) == 1
    # The siblings are unaffected: the failure is one leg's, not the run's.
    assert outcomes["BTC-USDT"].outcome == MIRROR_OUTCOME_PLACED


def test_a_refused_order_is_not_recorded_in_the_store(test_database_url):
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(
            RouterBingXRefusedError(101204, "insufficient margin")
        )]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)
    key = _full_identifier(_book(), "1000PEPE-USDT")
    assert store.prior_result(key) is None


# -- MirrorLeg ---------------------------------------------------------------


def test_mirror_leg_refuses_an_unknown_outcome_word():
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(symbol="BTC-USDT", outcome="maybe")


def test_mirror_leg_refuses_a_refusal_without_a_code():
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(symbol="BTC-USDT", outcome=MIRROR_OUTCOME_REFUSED)


def test_mirror_leg_refuses_a_code_on_a_placed_leg():
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(symbol="BTC-USDT", outcome=MIRROR_OUTCOME_PLACED, code="x")


def test_mirror_leg_refuses_a_message_on_a_placed_leg():
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(
            symbol="BTC-USDT",
            outcome=MIRROR_OUTCOME_PLACED,
            message="the venue said something",
        )


def test_mirror_leg_refuses_a_blank_message():
    """A message that states nothing is no message; the leg carries none."""
    with pytest.raises(RouterBingXMirrorError):
        MirrorLeg(
            symbol="BTC-USDT",
            outcome=MIRROR_OUTCOME_REFUSED,
            code="101215",
            message="  ",
        )


# -- main: the command ---------------------------------------------------------


def _run_main(argv, **kwargs) -> tuple[int, str, str]:
    kwargs.setdefault("clock", _clock)
    kwargs.setdefault("sleep", lambda _d: None)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv, **kwargs)
    return code, out.getvalue(), err.getvalue()


def test_without_place_prints_the_plan_and_places_nothing(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient()
    code, out, err = _run_main(["--book", str(book_path)], client=client)
    assert code == 0
    assert client.placed == []
    lines = [json.loads(line) for line in out.splitlines()]
    assert len(lines) == 7
    orders = [line for line in lines if "clientOrderID" in line]
    refusals = [line for line in lines if "refusal" in line]
    assert len(orders) == 5
    assert len(refusals) == 2
    assert err == ""


def test_the_plan_lines_are_stage_zeros_parameters(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    code, out, _ = _run_main(["--book", str(book_path)], client=_MirrorClient())
    assert code == 0
    btc = next(
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get("symbol") == "BTC-USDT"
    )
    assert btc == {
        "symbol": "BTC-USDT",
        "side": "BUY",
        "positionSide": "BOTH",
        "type": "LIMIT",
        "quantity": "0.0240",
        "price": "83137.3",
        "timeInForce": "PostOnly",
        "clientOrderID": _full_identifier(_book(), "BTC-USDT")[:40],
    }


def test_place_without_database_url_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient()
    code, out, err = _run_main(
        ["--book", str(book_path), "--place"], client=client, env={}
    )
    assert code == 1
    assert out == ""
    assert DATABASE_URL_MISSING_CODE in err
    assert client.placed == []


def test_place_prints_placed_and_exits_zero(tmp_path, test_database_url):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient()
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    code, out, err = _run_main(
        ["--book", str(book_path), "--place"],
        client=client,
        store=store,
        limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 0
    assert err == ""
    placed = [
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get(PLACEMENT_FIELD) == MIRROR_OUTCOME_PLACED
    ]
    assert len(placed) == 5


def test_a_second_place_prints_prior_for_all_five(tmp_path, test_database_url):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    _run_main(
        ["--book", str(book_path), "--place"],
        client=_MirrorClient(), store=store, limiter=limiter,
        database_url=test_database_url,
    )
    second = _MirrorClient()
    code, out, _ = _run_main(
        ["--book", str(book_path), "--place"],
        client=second, store=store, limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 0
    assert second.placed == []
    priors = [
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get(PLACEMENT_FIELD) == MIRROR_OUTCOME_PRIOR
    ]
    assert len(priors) == 5


def test_place_refused_leg_exits_one(tmp_path, test_database_url):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(
            RouterBingXRefusedError(101204, "insufficient margin")
        )]
    )
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    code, out, _ = _run_main(
        ["--book", str(book_path), "--place"],
        client=client, store=store, limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 1
    refused = [
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get(PLACEMENT_FIELD) == MIRROR_OUTCOME_REFUSED
    ]
    assert refused and refused[0]["code"] == "101204"


def test_place_refused_leg_prints_the_venues_message(
    tmp_path, test_database_url
):
    """The line an operator greps carries the venue's own ``msg`` verbatim.

    The live smoke test printed ``{"placement": "refused", "code":
    "101215"}`` and nothing else, and 101215 is in none of BingX's published
    documentation — the message is the only fact that says why.  The exit
    code stays 1 and the store still records nothing for the refused order.
    """
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(
            RouterBingXRefusedError(101215, "post-only order would take the market")
        )]
    )
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()
    code, out, _ = _run_main(
        ["--book", str(book_path), "--place"],
        client=client, store=store, limiter=limiter,
        database_url=test_database_url,
    )
    assert code == 1
    refused = [
        json.loads(line)
        for line in out.splitlines()
        if json.loads(line).get(PLACEMENT_FIELD) == MIRROR_OUTCOME_REFUSED
    ]
    assert refused and refused[0]["code"] == "101215"
    assert refused[0]["message"] == "post-only order would take the market"
    # The refused order is still recorded nowhere: the row a re-run would
    # answer from exists only for an order the venue took.
    key = _full_identifier(_book(), "1000PEPE-USDT")
    assert store.prior_result(key) is None


def test_status_prints_the_read_back(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    plan = _plan(_MirrorClient())
    held = {leg.client_order_id for leg in plan if isinstance(leg, BingXOrder)}
    client = _MirrorClient(orders_held=held)
    code, out, err = _run_main(
        ["--book", str(book_path), "--status"], client=client
    )
    assert code == 0
    assert err == ""
    lines = [json.loads(line) for line in out.splitlines()]
    # One line per book symbol, in the book's own order: the five the
    # venue holds answer NEW, and the two the gates refused — named by
    # identity, never by today's plan — answer not_found.
    book = _book()
    assert [line["symbol"] for line in lines] == list(book["weights"])
    statuses = {line["symbol"]: line["status"] for line in lines}
    assert statuses == {
        **{symbol: "NEW" for symbol in _order_symbols(plan)},
        "AGLD-USDT": "not_found",
        "NCFXUSD2ARS-USDT": "not_found",
    }


def test_cancel_prints_the_identifiers_it_cancelled(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(_book()), encoding="utf-8")
    plan = _plan(_MirrorClient())
    owned = [leg.client_order_id for leg in plan if isinstance(leg, BingXOrder)]
    open_orders = [
        {"clientOrderID": owned[0], "symbol": "1000PEPE-USDT"},
        {"clientOrderID": "a" * 40, "symbol": "OTHER-USDT"},
    ]
    client = _MirrorClient(open_orders=open_orders)
    code, out, err = _run_main(
        ["--book", str(book_path), "--cancel"], client=client
    )
    assert code == 0
    assert err == ""
    cancelled = [json.loads(line)["clientOrderID"] for line in out.splitlines()]
    assert cancelled == [owned[0]]
    # The foreign order was never handed to the venue's cancel.
    assert ("cancel_order", "a" * 40, "OTHER-USDT") not in client.calls


def test_status_addresses_the_rebalances_orders_by_identity_not_todays_plan(
    tmp_path,
):
    """The recorded incident, reproduced.

    The nullius01 rebalance placed five orders; the venue filled BTC, DOGE
    and ETH and left SOL and 1000PEPE resting.  ``--status`` printed three
    lines — DOGE (filled, and at its target once the fill landed, so sized
    to no leg by today's plan) and SOL (resting) missing — because it
    addressed ``build_mirror_plan``'s legs, a plan re-sized against the
    account's live positions that holds only the legs today still wants.
    The rebalance's orders are addressed by identity instead: one line per
    book symbol, in the book's order, with DOGE's and SOL's among them and
    the two the gates refused answering ``not_found``.
    """
    book = _book_with_doge_at_target()
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(book), encoding="utf-8")
    ids = _placed_ids()
    client = _MirrorClient(
        positions=_live_positions_data(),
        query_answers={
            ids["BTC-USDT"]: {
                "symbol": "BTC-USDT",
                "clientOrderID": ids["BTC-USDT"],
                "status": "FILLED",
                "origQty": "0.0240",
                "executedQty": "0.0240",
                "avgPrice": "83137.3",
            },
            ids["DOGE-USDT"]: {
                "symbol": "DOGE-USDT",
                "clientOrderID": ids["DOGE-USDT"],
                "status": "FILLED",
                "origQty": "5402",
                "executedQty": "5402",
                "avgPrice": "0.09381",
            },
            ids["ETH-USDT"]: {
                "symbol": "ETH-USDT",
                "clientOrderID": ids["ETH-USDT"],
                "status": "FILLED",
                "origQty": "0.5590",
                "executedQty": "0.5590",
                "avgPrice": "2685.87",
            },
            ids["SOL-USDT"]: {
                "symbol": "SOL-USDT",
                "clientOrderID": ids["SOL-USDT"],
                "status": "PENDING",
                "origQty": "0.0370",
                "executedQty": "0",
                "avgPrice": "0",
            },
            ids["1000PEPE-USDT"]: {
                "symbol": "1000PEPE-USDT",
                "clientOrderID": ids["1000PEPE-USDT"],
                "status": "PENDING",
                "origQty": "69850",
                "executedQty": "0",
                # The venue's own seven-decimal zero — the value the
                # operator's --status printed as "0E-7".
                "avgPrice": "0.0000000",
            },
        },
    )
    code, out, err = _run_main(
        ["--book", str(book_path), "--status"], client=client
    )
    assert code == 0
    assert err == ""
    lines = [json.loads(line) for line in out.splitlines()]
    assert [line["symbol"] for line in lines] == list(book["weights"])
    by_symbol = {line["symbol"]: line for line in lines}
    assert by_symbol["DOGE-USDT"]["status"] == "FILLED"
    assert by_symbol["SOL-USDT"]["status"] == "PENDING"
    assert by_symbol["AGLD-USDT"]["status"] == "not_found"
    assert by_symbol["NCFXUSD2ARS-USDT"]["status"] == "not_found"
    # The venue's seven-decimal zero prints as the venue spelled it, in
    # plain positional notation — never Decimal's exponent form.
    assert by_symbol["1000PEPE-USDT"]["avgPrice"] == "0.0000000"
    # No plan was built and nothing was placed: the command asks only the
    # venue's order face, over the identities the book itself names.
    plan_reads = [
        c for c in client.calls if c[0] in ("contracts", "premium_index", "positions")
    ]
    assert plan_reads == []
    assert client.placed == []


def test_cancel_addresses_the_rebalances_orders_by_identity_not_todays_plan(
    tmp_path,
):
    """The incident's other half: ``--cancel`` used the same plan-derived
    order set, so a resting order the plan dropped was never cancelled and
    stayed on the venue's book — the operator's SOL order would have been
    left resting forever.  The cancel owns every identifier this rebalance
    could ever have placed, whatever today's plan says, and the foreign
    order stays untouched."""
    book = _book_with_doge_at_target()
    book_path = tmp_path / "book.json"
    book_path.write_text(json.dumps(book), encoding="utf-8")
    doge = _placed_ids()["DOGE-USDT"]
    client = _MirrorClient(
        positions=_live_positions_data(),
        open_orders=[
            {"clientOrderID": doge, "symbol": "DOGE-USDT"},
            {"clientOrderID": "a" * 40, "symbol": "OTHER-USDT"},
        ],
    )
    code, out, err = _run_main(
        ["--book", str(book_path), "--cancel"], client=client
    )
    assert code == 0
    assert err == ""
    cancelled = [json.loads(line)["clientOrderID"] for line in out.splitlines()]
    assert cancelled == [doge]
    # The foreign order was never handed to the venue's cancel.
    assert ("cancel_order", "a" * 40, "OTHER-USDT") not in client.calls
    assert client.placed == []


def test_a_missing_book_path_refuses(tmp_path):
    client = _MirrorClient()
    code, out, err = _run_main(
        ["--book", str(tmp_path / "absent.json")], client=client
    )
    assert code == 1
    assert out == ""
    assert MIRROR_CODE in err
    assert client.calls == []


def test_a_book_that_is_not_json_refuses(tmp_path):
    book_path = tmp_path / "book.json"
    book_path.write_text("not json", encoding="utf-8")
    code, _out, err = _run_main(["--book", str(book_path)], client=_MirrorClient())
    assert code == 1
    assert MIRROR_CODE in err


def test_the_schedule_is_the_one_the_integration_points_name():
    assert VST_MIRROR_WEIGHT_SCHEDULE.allowance == 10
    assert VST_MIRROR_WEIGHT_SCHEDULE.window == timedelta(seconds=1)
    for operation in (
        OPERATION_PLACE_ORDER,
        OPERATION_QUERY_ORDER,
        "cancel_order",
        "open_orders",
        "account",
    ):
        assert VST_MIRROR_WEIGHT_SCHEDULE.weight_for(operation) == 1


# -- mirror_place: the terms it records as it places ---------------------------
#
# The bug spec ``bug_spec_bingx_reconcile_refs.xml``: an order's terms — the
# side, the type, the size and, above all, the reference price the venue was
# actually asked at — cannot be recovered from a hash, and a plan rebuilt at
# reconciliation time is re-sized against today's positions and marks.  So
# placement writes them down.  The tests below hold that write: that it
# happens for a leg the venue actually took, that it does not happen twice
# for a replay, and that the reference recorded is the *sent* price (the
# repriced limit at the book), never the plan's pre-repricing one.


def _records(store, book: dict | None = None):
    """Every term the store recorded for the plain book's rebalance."""
    source = book or _book()
    return store.records_for(source["book_id"], source["rebalance_ts"])


def test_place_records_each_placed_orders_terms(test_database_url):
    """One row per sent order, carrying the terms a fill is priced against."""
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)

    records = _records(store)
    assert len(records) == 5
    assert {record.symbol for record in records} == {
        order.symbol for order in client.placed
    }
    by_symbol = {record.symbol: record for record in records}
    sent = {order.symbol: order for order in client.placed}
    for symbol, record in by_symbol.items():
        # Every term is the order the venue was actually asked to take.
        assert record.side == sent[symbol].side
        assert record.type == sent[symbol].type
        assert record.quantity == Decimal(sent[symbol].quantity)
        # A LIMIT leg's reference is its sent limit; a MARKET leg's is its
        # symbol's mark read in the same run.
        if sent[symbol].type == BINGX_LIMIT_ORDER:
            assert record.reference_price == Decimal(sent[symbol].price)
        else:
            assert record.reference_price == Decimal(_mark_of(client, symbol))
        # The key is feature 316's own, spelled out in full.
        assert record.client_order_id == _full_identifier(_book(), symbol)
        assert record.book_id == _book()["book_id"]
        assert record.rebalance_ts == datetime.fromisoformat(
            _book()["rebalance_ts"]
        )


def test_place_records_the_repriced_limit_not_the_plans_own_price(test_database_url):
    """The defect's exact figure: what the venue was asked at, not what the
    plan proposed before repricing at the book.

    ETH is a SELL whose plan price is the mark, 2685.87; the recorded live
    depth's best ask is 2673.27, and the order is repriced down to it just
    before it leaves.  The recorded reference must be 2673.27 — the price a
    fill will actually be measured against.
    """
    client = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)

    eth = {record.symbol: record for record in _records(store)}["ETH-USDT"]
    sent = next(order for order in client.placed if order.symbol == "ETH-USDT")
    assert sent.price == "2673.27"
    assert eth.reference_price == Decimal("2673.27")
    # And not the plan's own pre-repricing price.
    assert eth.reference_price != Decimal("2685.87")


def test_a_replay_records_no_second_row_and_leaves_the_reference_alone(
    test_database_url,
):
    """A ``prior`` leg is answered from its row: the reference cannot move.

    A second run in the same rebalance sends nothing (Stage 1's law), so it
    reaches the recorder for no leg at all — the row that stands is the
    first placement's, and a fill is measured against the price the order
    was actually placed at, never a price a later run would have proposed.
    """
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()

    first = _MirrorClient()
    _place(first, _plan(first), store, limiter, database_url=test_database_url)
    before = _records(store)

    second = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    outcomes = _place(
        second, _plan(second), store, limiter, database_url=test_database_url
    )

    assert second.placed == []
    assert all(o.outcome == MIRROR_OUTCOME_PRIOR for o in outcomes.values())
    assert _records(store) == before


def test_a_refused_leg_records_nothing(test_database_url):
    """An order the venue never took has no terms to remember.

    The store's claim rolls back on the refusal, so no row is written — an
    order that was refused has no fill to price, and a row for it would
    invite a reconciliation to price one that never happened.
    """
    refusal = RouterBingXRefusedError("101215", "the PostOnly order would have crossed")
    client = _MirrorClient(
        place_effects=[lambda: (_ for _ in ()).throw(refusal)]
    )
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )

    assert any(o.outcome == MIRROR_OUTCOME_REFUSED for o in outcomes.values())
    refused_symbol = next(
        symbol for symbol, o in outcomes.items() if o.outcome == MIRROR_OUTCOME_REFUSED
    )
    recorded = {record.symbol for record in _records(store)}
    assert refused_symbol not in recorded
    assert len(recorded) == 4


def test_a_gate_closed_leg_is_never_recorded(test_database_url):
    """A leg the gates closed names no venue order, so it has no terms.

    The synthetic book's AGLD and NCFXUSD2ARS legs never reach placement, so
    the table carries rows for the five orders and nothing for the two
    refusals.
    """
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)

    recorded = {record.symbol for record in _records(store)}
    assert "AGLD-USDT" not in recorded
    assert "NCFXUSD2ARS-USDT" not in recorded


def test_a_store_without_the_terms_write_still_places(test_database_url):
    """The terms write is optional at the store seam: a double with only
    ``place`` keeps placing exactly as before this recording existed."""
    inner = RouterOrderPlacementStore(test_database_url)

    class _BarePlacementStore:
        """A store exposing feature 317's one contract and nothing more."""

        def place(self, *args, **kwargs):
            return inner.place(*args, **kwargs)

    client = _MirrorClient()
    limiter = _CountingLimiter()
    outcomes = _place(
        client,
        _plan(client),
        _BarePlacementStore(),
        limiter,
        database_url=test_database_url,
    )

    assert len(client.placed) == 5
    assert all(o.outcome == MIRROR_OUTCOME_PLACED for o in outcomes.values())
    assert _records(inner) == ()


def _mark_of(client: _MirrorClient, symbol: str) -> str:
    """The mark the double holds for ``symbol`` — the recorded fixture's own."""
    return client._mark_price(symbol)
