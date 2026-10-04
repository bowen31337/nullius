"""Tests for :mod:`router.bingx_orders` — feature 3's read-back and cancel.

Feature 3 of additions_spec_bingx_vst_mirror.xml: *System returns each of
the book's VST orders, looked up by clientOrderID, with its status (NEW,
PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED or not_found), its executed
quantity and its average price.  Asked to cancel, it returns the identifiers
of the open orders it cancelled: only those whose clientOrderID belongs to
the book's rebalance.  Orders from any other book or rebalance are left
untouched.*

These tests hold the two verbs to every clause of that sentence over a
recording double — never a socket.  The double stands in for feature 1's
client and records what it was handed, so the suite can prove *which*
orders were looked up, *which* identifiers reached the venue's cancel, and
that an order belonging to another book or another rebalance was never
passed to it at all.  The identifier the double answers under is derived
here through feature 316 and projected through feature 3 of Stage 0, so
*belongs to the book's rebalance* is exercised as the real function of the
book, the rebalance and the symbol — not a hand-written stand-in for it.

Every refusal a verb raises is a fault of the ask, opening with
``bingx_orders``; the venue's own not-found refusal is translated into the
``not_found`` status rather than surfaced, and any other venue refusal
propagates unchanged.  All of this is asserted below.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from router.bingx_client import (
    ORDER_NOT_FOUND_CODE,
    RouterBingXRefusedError,
    RouterBingXTransportError,
)
from router.bingx_client_order_id import project_bingx_client_order_id
from router.bingx_order import BingXRefusedLeg
from router.bingx_orders import (
    BINGX_ORDERS_CODE,
    VST_ORDER_NOT_FOUND,
    RouterBingXOrdersError,
    VSTOrderStatus,
    cancel_rebalance_orders,
    read_back_orders,
)
from router.client_order_id import derive_client_order_id

#: The book and rebalance the fixtures use, so the identifiers below are the
#: ones the synthetic book's plan actually places.
BOOK_ID = "synthetic-vst-0"
REBALANCE_TS = datetime.fromisoformat("2026-09-30T00:00:00+00:00")
#: A different book and a different rebalance of the same book — the two
#: ways an order can be *not this rebalance's*, exercised by the cancel tests.
OTHER_BOOK_ID = "synthetic-vst-1"
OTHER_REBALANCE_TS = datetime.fromisoformat("2026-09-30T01:00:00+00:00")

SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT")

#: The recorded VST fixtures, as every suite in this member reaches them:
#: inputs, never edited.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"


def _identifier(symbol: str, *, book_id: str = BOOK_ID, ts: datetime = REBALANCE_TS) -> str:
    """Feature 3's projection of feature 316's identifier for one leg."""
    return project_bingx_client_order_id(
        derive_client_order_id(book_id=book_id, rebalance_ts=ts, symbol=symbol)
    )


def _order(symbol: str, *, book_id: str = BOOK_ID, ts: datetime = REBALANCE_TS) -> dict:
    """A plan-shaped order for ``symbol`` — the venue's own field spellings."""
    return {
        "symbol": symbol,
        "side": "BUY",
        "positionSide": "BOTH",
        "type": "LIMIT",
        "quantity": "1",
        "price": "1",
        "timeInForce": "PostOnly",
        "clientOrderID": _identifier(symbol, book_id=book_id, ts=ts),
    }


class _FakeClient:
    """A recording stand-in for feature 1's client.

    Answers ``query_order`` from a scripted map keyed by ``clientOrderID``
    (a value may be an order mapping, or an exception to raise) and
    ``open_orders`` from a scripted listing, recording every call so a test
    can assert exactly which identifiers were looked up or cancelled.
    """

    def __init__(self, *, queries: dict | None = None, listing: object = None) -> None:
        self._queries = queries or {}
        self._listing = listing if listing is not None else []
        self.queried: list[tuple[str, str | None]] = []
        self.cancelled: list[tuple[str, str | None]] = []
        self.listing_calls = 0

    def query_order(self, client_order_id: str, *, symbol: str | None = None):
        self.queried.append((client_order_id, symbol))
        answer = self._queries.get(client_order_id)
        if answer is None:
            raise RouterBingXRefusedError(ORDER_NOT_FOUND_CODE, "order not exist")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def open_orders(self, symbol: str | None = None):
        self.listing_calls += 1
        return self._listing

    def cancel_order(self, client_order_id: str, *, symbol: str | None = None):
        self.cancelled.append((client_order_id, symbol))
        return {"clientOrderID": client_order_id, "status": "CANCELED"}


def _filled(client_order_id: str, *, status: str, qty: str = "0", price: str = "0") -> dict:
    """A venue order document for ``client_order_id``."""
    return {
        "clientOrderID": client_order_id,
        "status": status,
        "executedQty": qty,
        "avgPrice": price,
    }


def _read_answer(
    client_order_id: str, *, status: str, qty: str = "0", price: str = "0"
) -> dict:
    """The venue's read answer for ``client_order_id``, in its real shape.

    The single-order read wraps its order document under ``data.order`` —
    the nesting ``live/query_order_pending.json`` records — so the answers
    this suite scripts for ``query_order`` speak that shape, never the
    flat one the stand-in used to serve (the reason these tests never saw
    the real document the live venue answers).
    """
    return {"order": _filled(client_order_id, status=status, qty=qty, price=price)}


# -- The read-back: one order per leg, looked up by clientOrderID --------------


def test_each_order_is_looked_up_by_its_client_order_id_in_the_order_handed() -> None:
    """The sentence's first clause: *each of the book's orders, looked up by
    clientOrderID*.  One query per leg, carrying that leg's identifier, in
    the order the legs arrive."""
    orders = [_order("BTC-USDT"), _order("ETH-USDT"), _order("SOL-USDT")]
    ids = [_order(s)["clientOrderID"] for s in SYMBOLS]
    client = _FakeClient(
        queries={i: _read_answer(i, status="NEW") for i in ids}
    )

    statuses = read_back_orders(client=client, orders=orders)

    assert [entry.client_order_id for entry in statuses] == ids
    assert [q[0] for q in client.queried] == ids
    # The symbol travels with the lookup, so the venue can disambiguate.
    assert [q[1] for q in client.queried] == list(SYMBOLS)


def test_the_status_is_the_venue_word_and_the_two_measurements_are_decimals() -> None:
    """The sentence's status vocabulary and its two measurements: the status
    word is passed through, and executedQty/avgPrice are exact Decimals
    built from the venue's strings — including a partially filled order."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: _read_answer(cid, status="PARTIALLY_FILLED", qty="0.0040", price="83137.3")}
    )

    (status,) = read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert status.status == "PARTIALLY_FILLED"
    assert status.executed_quantity == Decimal("0.0040")
    assert status.average_price == Decimal("83137.3")
    assert status.is_open is True
    assert status.symbol == "BTC-USDT"


@pytest.mark.parametrize(
    "word, open_",
    [
        ("NEW", True),
        ("PARTIALLY_FILLED", True),
        ("PENDING", True),
        ("FILLED", False),
        ("CANCELED", False),
        ("EXPIRED", False),
    ],
)
def test_the_known_status_words_are_passed_through(word: str, open_: bool) -> None:
    """Every venue word this system knows is admissible and passed through,
    and only the working states — NEW, PARTIALLY_FILLED and the resting
    order's PENDING — read as open."""
    cid = _identifier("ETH-USDT")
    client = _FakeClient(queries={cid: _read_answer(cid, status=word)})

    (status,) = read_back_orders(client=client, orders=[_order("ETH-USDT")])

    assert status.status == word
    assert status.is_open is open_


def test_an_order_the_venue_does_not_hold_is_not_found_not_an_exception() -> None:
    """The sixth status: a venue not-found refusal becomes the ``not_found``
    status with no measurements, rather than propagating — an order that
    never landed is a fact about the order, not a fault of the read."""
    client = _FakeClient()  # every query refuses with ORDER_NOT_FOUND_CODE

    (status,) = read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert status.status == VST_ORDER_NOT_FOUND
    assert status.executed_quantity is None
    assert status.average_price is None
    assert status.is_open is False
    assert status.symbol == "BTC-USDT"


def test_a_not_found_among_found_orders_does_not_hide_the_others() -> None:
    """A book of several legs answers one status each: a missing leg is
    ``not_found`` beside the found legs, not a run that unwinds."""
    ids = {s: _identifier(s) for s in SYMBOLS}
    client = _FakeClient(
        queries={
            ids["BTC-USDT"]: _read_answer(ids["BTC-USDT"], status="FILLED", qty="1", price="2"),
            # ETH-USDT is absent -> not_found
            ids["SOL-USDT"]: _read_answer(ids["SOL-USDT"], status="NEW"),
        }
    )

    statuses = read_back_orders(client=client, orders=[_order(s) for s in SYMBOLS])

    assert [s.status for s in statuses] == ["FILLED", VST_ORDER_NOT_FOUND, "NEW"]


def test_a_not_found_spelled_as_a_string_code_is_also_not_found() -> None:
    """The venue has sent its not-found code as text across versions; the
    translation judges both spellings."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(queries={cid: RouterBingXRefusedError(str(ORDER_NOT_FOUND_CODE), "no")})

    (status,) = read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert status.status == VST_ORDER_NOT_FOUND


def _live_not_exist_refusal() -> RouterBingXRefusedError:
    """The venue's verbatim refusal for an order it holds no record of.

    Read from the live recording ``live/query_order_not_exist.json`` — the
    answer the first live smoke test met when ``--status`` asked after an
    order that had been refused at placement: ``{"code": 109421, "msg":
    "order not exist", "data": {}}``.  The fixture is an input and is never
    edited; reading the recording pins the translation against what the
    venue actually answers, not what a spec assumed it would.
    """
    answer = json.loads(
        (FIXTURES / "live" / "query_order_not_exist.json").read_text()
    )
    return RouterBingXRefusedError(answer["code"], answer["msg"])


def test_the_live_order_not_exist_refusal_is_that_orders_not_found() -> None:
    """The venue does not answer an empty order object for a
    ``clientOrderID`` it holds no record of — it *refuses*, code 109421
    ``order not exist``.  That refusal is one leg's ``not_found`` status
    with no measurements: a fact about the order, not a fault that unwinds
    the whole read-back and hides the legs that were placed."""
    ids = {s: _identifier(s) for s in SYMBOLS}
    client = _FakeClient(
        queries={
            ids["BTC-USDT"]: _read_answer(ids["BTC-USDT"], status="FILLED", qty="1", price="2"),
            ids["ETH-USDT"]: _live_not_exist_refusal(),  # never placed
            ids["SOL-USDT"]: _read_answer(ids["SOL-USDT"], status="NEW"),
        }
    )

    statuses = read_back_orders(client=client, orders=[_order(s) for s in SYMBOLS])

    assert [(s.status, s.executed_quantity, s.average_price) for s in statuses] == [
        ("FILLED", Decimal("1"), Decimal("2")),
        (VST_ORDER_NOT_FOUND, None, None),
        ("NEW", Decimal("0"), Decimal("0")),
    ]
    # The read-back kept going: every leg was still asked of the venue.
    assert [q[0] for q in client.queried] == [ids[s] for s in SYMBOLS]


def _live_pending_answer() -> dict:
    """The venue's verbatim read answer for a resting order, as feature 1's
    ``query_order`` hands it to this module: the envelope's ``data``.

    Read from the live recording ``live/query_order_pending.json`` — the
    answer the operator's ``--status`` met for one of three PostOnly orders
    resting on VST.  The order details sit under ``data.order`` and the
    resting order's status word is ``PENDING``, a word the Stage 1
    sentence's list does not carry.  The fixture is an input and is never
    edited; reading the recording pins the read-back against what the venue
    actually answers, not what a spec assumed it would.
    """
    answer = json.loads(
        (FIXTURES / "live" / "query_order_pending.json").read_text(
            encoding="utf-8"
        )
    )
    return answer["data"]


def test_the_live_pending_answer_is_read_in_the_venues_nested_shape() -> None:
    """The defect, pinned against the recording that caught it.

    The venue's read answer nests the order under ``data.order`` and reports
    a resting order as ``PENDING`` — a word outside the list the Stage 1
    sentence wrote.  The read-back reads the object under ``order``, reports
    the venue's word verbatim and answers the order's measurements, so the
    operator's ``--status`` answers one line per order instead of refusing
    with *carries no readable 'status'*.
    """
    data = _live_pending_answer()
    recorded_id = data["order"]["clientOrderId"]
    client = _FakeClient(queries={recorded_id: data})

    (status,) = read_back_orders(client=client, orders=[recorded_id])

    assert status.status == "PENDING"
    assert status.symbol == "1000PEPE-USDT"
    assert status.original_quantity == Decimal("69850")
    assert status.executed_quantity == Decimal("0")
    assert status.average_price == Decimal("0.0000000")
    assert status.is_open is True
    # The decimals render back as this module always renders them — the
    # exact Decimal spellings — which for the recording's all-zero
    # seven-decimal avgPrice is Decimal's own "0E-7".
    assert status.as_dict() == {
        "symbol": "1000PEPE-USDT",
        "clientOrderID": recorded_id,
        "status": "PENDING",
        "origQty": str(Decimal("69850")),
        "executedQty": str(Decimal("0")),
        "avgPrice": str(Decimal("0.0000000")),
    }


def test_the_live_not_exist_code_spelled_as_text_is_also_not_found() -> None:
    """The live code is judged by spelling like the declared one: the venue
    has sent its codes as integers and as strings across versions."""
    cid = _identifier("BTC-USDT")
    refusal = _live_not_exist_refusal()
    client = _FakeClient(
        queries={cid: RouterBingXRefusedError(str(refusal.code), refusal.msg)}
    )

    (status,) = read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert status.status == VST_ORDER_NOT_FOUND


def test_a_neighbouring_venue_code_keeps_raising() -> None:
    """Only the not-found spellings become a status: a neighbouring order
    code — the venue's duplicate-clientOrderID answer to a re-post — keeps
    feature 1's refusal and propagates, because it is a fault of the ask
    and translating it would report an order the venue did hold."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: RouterBingXRefusedError(109404, "duplicate clientOrderID")}
    )

    with pytest.raises(RouterBingXRefusedError) as raised:
        read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert raised.value.code == 109404


def test_any_other_venue_refusal_propagates_unchanged() -> None:
    """A rejection that is not *no such order* is a fault of the ask: it is
    feature 1's refusal and is not swallowed into a status."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(queries={cid: RouterBingXRefusedError(80001, "invalid signature")})

    with pytest.raises(RouterBingXRefusedError) as raised:
        read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert raised.value.code == 80001


def test_a_transport_failure_propagates_unchanged() -> None:
    """A transport fault is not a status either."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: RouterBingXTransportError("GET", "u", "boom", outcome_unknown=False)}
    )

    with pytest.raises(RouterBingXTransportError):
        read_back_orders(client=client, orders=[_order("BTC-USDT")])


def test_a_refused_leg_is_skipped_because_it_names_no_venue_order() -> None:
    """The gates' refused legs are not the read-back's business: they are
    skipped, so only real orders reach the venue."""
    good = _order("BTC-USDT")
    client = _FakeClient(queries={good["clientOrderID"]: _read_answer(good["clientOrderID"], status="NEW")})

    statuses = read_back_orders(
        client=client,
        orders=[BingXRefusedLeg(symbol="AGLD-USDT", code="below_min_notional"), good],
    )

    assert [s.client_order_id for s in statuses] == [good["clientOrderID"]]
    assert len(client.queried) == 1


def test_a_bare_identifier_is_read_and_its_symbol_taken_from_the_venue() -> None:
    """A leg handed as a bare string has no symbol; the venue's echoed symbol
    supplies it rather than the answer carrying none."""
    cid = _identifier("SOL-USDT")
    document = _filled(cid, status="NEW")
    document["symbol"] = "SOL-USDT"
    client = _FakeClient(queries={cid: {"order": document}})

    (status,) = read_back_orders(client=client, orders=[cid])

    assert status.client_order_id == cid
    assert status.symbol == "SOL-USDT"
    assert client.queried == [(cid, None)]


def test_a_plan_shaped_mapping_leg_is_read() -> None:
    """The read-back reads the shape a written plan holds — the venue's own
    field spellings — not only the frozen BingXOrder value."""
    order = _order("BTC-USDT")
    client = _FakeClient(queries={order["clientOrderID"]: _read_answer(order["clientOrderID"], status="NEW")})

    (status,) = read_back_orders(client=client, orders=[order])

    assert status.status == "NEW"
    assert status.symbol == "BTC-USDT"


# -- The read-back's own refusals ---------------------------------------------


def test_a_status_word_outside_the_known_set_is_reported_as_spelled() -> None:
    """The status word is the venue's own and is never refused for its
    spelling: a word this system does not know — one BingX could coin
    tomorrow, the way it coins ``PENDING`` for a resting order — is
    reported exactly as the venue spelled it, so a new status cannot abort
    the read-back.  Only the measurements are refused when unreadable."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(queries={cid: _read_answer(cid, status="PENDING_CANCEL")})

    (status,) = read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert status.status == "PENDING_CANCEL"
    assert status.is_open is False  # not a word this system knows as working
    assert status.executed_quantity == Decimal("0")


def test_a_bare_order_object_is_still_read_when_the_answer_wraps_no_order() -> None:
    """An answer that already *is* the order object — the shape older
    venue answers and every injected double speak — is read just as the
    wrapped one is; only a missing or unreadable field is refused."""
    cid = _identifier("ETH-USDT")
    client = _FakeClient(queries={cid: _filled(cid, status="NEW")})

    (status,) = read_back_orders(client=client, orders=[_order("ETH-USDT")])

    assert status.status == "NEW"
    assert status.executed_quantity == Decimal("0")


def test_an_answer_wrapping_something_other_than_an_order_object_is_refused() -> None:
    """An answer whose ``order`` key holds a non-object cannot be read into
    a status; it is refused naming what it wrapped."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(queries={cid: {"order": [cid]}})

    with pytest.raises(RouterBingXOrdersError) as raised:
        read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert str(raised.value).startswith(BINGX_ORDERS_CODE)
    assert "order" in str(raised.value)


def test_a_missing_measurement_is_refused() -> None:
    """A found order answers both measurements (zero when nothing filled); a
    response omitting one cannot be read."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(queries={cid: {"status": "NEW", "executedQty": "0"}})

    with pytest.raises(RouterBingXOrdersError):
        read_back_orders(client=client, orders=[_order("BTC-USDT")])


def test_a_float_measurement_is_refused_by_name() -> None:
    """A float is a binary approximation of a decimal no venue ever sent."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: {"status": "FILLED", "executedQty": 0.1, "avgPrice": "1"}}
    )

    with pytest.raises(RouterBingXOrdersError) as raised:
        read_back_orders(client=client, orders=[_order("BTC-USDT")])

    assert "float" in str(raised.value)


def test_a_negative_measurement_is_refused() -> None:
    """An executed quantity or an average price does not run backwards."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: {"status": "FILLED", "executedQty": "-1", "avgPrice": "1"}}
    )

    with pytest.raises(RouterBingXOrdersError):
        read_back_orders(client=client, orders=[_order("BTC-USDT")])


def test_an_answer_for_a_different_order_is_refused() -> None:
    """An echoed clientOrderID that is not the one asked for is refused
    rather than reported under this order's name — under either spelling
    the venue writes the echo, plan capitalisation or the read's own
    ``clientOrderId``."""
    cid = _identifier("BTC-USDT")
    other = _identifier("ETH-USDT")
    wrong_caps = {"order": {"clientOrderId": other, "status": "NEW"}}
    client = _FakeClient(queries={cid: wrong_caps})

    with pytest.raises(RouterBingXOrdersError):
        read_back_orders(client=client, orders=[_order("BTC-USDT")])


def test_an_item_that_names_no_order_is_refused() -> None:
    """A leg that names no order would silently drop from the read-back, so
    it is refused naming the item."""
    client = _FakeClient()

    with pytest.raises(RouterBingXOrdersError):
        read_back_orders(client=client, orders=[object()])


def test_a_client_without_the_query_method_is_refused() -> None:
    """A client that cannot be asked is a wiring fault worth naming."""
    with pytest.raises(RouterBingXOrdersError) as raised:
        read_back_orders(client=object(), orders=[_order("BTC-USDT")])

    assert "query_order" in str(raised.value)


def test_an_empty_book_answers_no_statuses_and_queries_nothing() -> None:
    """A book held flat names no orders, so nothing is looked up."""
    client = _FakeClient()

    assert read_back_orders(client=client, orders=[]) == []
    assert client.queried == []


# -- The cancel: only this rebalance's open orders ----------------------------


def test_only_the_rebalances_own_orders_are_cancelled() -> None:
    """The sentence's ownership clause: of the venue's open orders, exactly
    those whose clientOrderID belongs to this book's rebalance are
    cancelled.  An order from another book and one from another rebalance of
    the same book are left untouched — never passed to the venue's cancel."""
    mine = [_identifier("BTC-USDT"), _identifier("ETH-USDT")]
    other_book = _identifier("SOL-USDT", book_id=OTHER_BOOK_ID)
    other_rebalance = _identifier("SOL-USDT", ts=OTHER_REBALANCE_TS)
    client = _FakeClient(
        listing=[
            _filled(mine[0], status="NEW"),
            _filled(other_book, status="NEW"),
            _filled(mine[1], status="PARTIALLY_FILLED"),
            _filled(other_rebalance, status="NEW"),
        ]
    )

    cancelled = cancel_rebalance_orders(
        client=client, orders=[_order("BTC-USDT"), _order("ETH-USDT")]
    )

    assert cancelled == mine
    assert [c[0] for c in client.cancelled] == mine
    assert other_book not in [c[0] for c in client.cancelled]
    assert other_rebalance not in [c[0] for c in client.cancelled]


def test_the_listing_is_read_once_and_only_owned_orders_are_deleted() -> None:
    """One listing read decides open-ness, and one DELETE per owned open
    order — not one per leg."""
    ids = [_identifier(s) for s in SYMBOLS]
    client = _FakeClient(listing=[_filled(ids[0], status="NEW")])

    cancelled = cancel_rebalance_orders(client=client, orders=[_order(s) for s in SYMBOLS])

    assert cancelled == [ids[0]]
    assert client.listing_calls == 1
    assert len(client.cancelled) == 1


def test_the_cancel_carries_the_symbol_it_knows_for_the_order() -> None:
    """The DELETE names the order's symbol, taken from the leg when it is
    known and otherwise from the venue's row."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(listing=[_filled(cid, status="NEW")])

    cancel_rebalance_orders(client=client, orders=[_order("BTC-USDT")])

    assert client.cancelled == [(cid, "BTC-USDT")]


def test_a_bare_listing_is_read_as_well_as_the_wrapped_one() -> None:
    """The venue answers either a bare array or ``{"orders": [...]}``."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(listing={"orders": [_filled(cid, status="NEW")], "total": 1})

    assert cancel_rebalance_orders(client=client, orders=[_order("BTC-USDT")]) == [cid]


def test_nothing_owned_means_nothing_is_cancelled() -> None:
    """When the listing holds none of this rebalance's orders, no DELETE is
    made at all."""
    other = _identifier("SOL-USDT", book_id=OTHER_BOOK_ID)
    client = _FakeClient(listing=[_filled(other, status="NEW")])

    assert cancel_rebalance_orders(client=client, orders=[_order("BTC-USDT")]) == []
    assert client.cancelled == []


def test_a_refused_leg_is_never_a_cancel_target() -> None:
    """A refused leg names no order, so it contributes nothing to the owned
    set and nothing is cancelled on its behalf."""
    client = _FakeClient(listing=[])

    cancelled = cancel_rebalance_orders(
        client=client, orders=[BingXRefusedLeg(symbol="AGLD-USDT", code="below_min_notional")]
    )

    assert cancelled == []


# -- The cancel's own refusals ------------------------------------------------


def test_an_open_order_with_no_readable_identifier_is_refused() -> None:
    """Ownership is decided by clientOrderID; a listing row without one is
    refused rather than guessed at."""
    client = _FakeClient(listing=[{"status": "NEW", "symbol": "BTC-USDT"}])

    with pytest.raises(RouterBingXOrdersError):
        cancel_rebalance_orders(client=client, orders=[_order("BTC-USDT")])


def test_a_listing_that_is_not_a_listing_is_refused() -> None:
    """A response that is not an array of orders cannot be filtered."""
    client = _FakeClient(listing={"total": 0})

    with pytest.raises(RouterBingXOrdersError):
        cancel_rebalance_orders(client=client, orders=[_order("BTC-USDT")])


def test_a_client_without_the_cancel_method_is_refused() -> None:
    """A client that cannot cancel is a wiring fault worth naming."""
    class _ReadOnly:
        def open_orders(self, symbol=None):
            return []

    with pytest.raises(RouterBingXOrdersError) as raised:
        cancel_rebalance_orders(client=_ReadOnly(), orders=[_order("BTC-USDT")])

    assert "cancel_order" in str(raised.value)


# -- The value's own contract -------------------------------------------------


def test_a_not_found_status_carries_no_measurements() -> None:
    with pytest.raises(RouterBingXOrdersError):
        VSTOrderStatus(
            symbol="BTC-USDT",
            client_order_id="a" * 40,
            status=VST_ORDER_NOT_FOUND,
            executed_quantity=Decimal(0),
            average_price=Decimal(0),
        )


def test_a_found_status_must_carry_both_measurements() -> None:
    with pytest.raises(RouterBingXOrdersError):
        VSTOrderStatus(
            symbol="BTC-USDT",
            client_order_id="a" * 40,
            status="NEW",
            executed_quantity=Decimal(0),
            average_price=None,
        )


def test_a_not_found_status_carries_no_original_quantity_either() -> None:
    with pytest.raises(RouterBingXOrdersError):
        VSTOrderStatus(
            symbol="BTC-USDT",
            client_order_id="a" * 40,
            status=VST_ORDER_NOT_FOUND,
            executed_quantity=None,
            average_price=None,
            original_quantity=Decimal(1),
        )


def test_an_original_quantity_that_runs_backwards_is_refused() -> None:
    with pytest.raises(RouterBingXOrdersError):
        VSTOrderStatus(
            symbol="BTC-USDT",
            client_order_id="a" * 40,
            status="NEW",
            executed_quantity=Decimal(0),
            average_price=Decimal(0),
            original_quantity=Decimal("-1"),
        )


def test_an_over_long_identifier_is_refused() -> None:
    with pytest.raises(RouterBingXOrdersError):
        VSTOrderStatus(
            symbol="BTC-USDT",
            client_order_id="a" * 41,
            status="NEW",
            executed_quantity=Decimal(0),
            average_price=Decimal(0),
        )


def test_no_credential_or_secret_appears_in_a_status_answer() -> None:
    """A status is measurements and words only — it cannot leak a credential."""
    cid = _identifier("BTC-USDT")
    document = _read_answer(cid, status="NEW", qty="0", price="0")
    document["order"]["origQty"] = "1"
    client = _FakeClient(queries={cid: document})

    (status,) = read_back_orders(client=client, orders=[_order("BTC-USDT")])

    rendered = repr(status) + str(status.as_dict())
    assert "BINGX_VST" not in rendered
    assert status.as_dict() == {
        "symbol": "BTC-USDT",
        "clientOrderID": cid,
        "status": "NEW",
        "origQty": "1",
        "executedQty": "0",
        "avgPrice": "0",
    }
