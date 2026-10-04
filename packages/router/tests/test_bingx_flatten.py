"""Tests for :mod:`router.bingx_flatten` — Stage 2 feature 1, the flatten.

``additions_spec_bingx_vst_stage2.xml``, "BingX VST Stage 2", feature 1:
*System flattens the VST sub-account from* ``python -m router.bingx_flatten
--confirm``: *it cancels every open order on the account, then closes every
position with one reduce-only MARKET order per symbol (side opposite to
positionSide, quantity the unsigned positionAmt, positionSide BOTH,
reduceOnly true).  It prints one JSON line per cancelled order and per
close, and returns exit 0 only when a final read shows no open orders and
no positions.  Without* ``--confirm`` *it prints what it would do and
changes nothing.  A close the venue refuses is printed with its code and
message, and the run exits 1.*

These tests hold the verb to every clause of that sentence over a
recording double — never a socket.  Every venue answer the double serves
is a recorded fixture from ``fixtures/bingx_vst/live/`` or a value
derived from one: the one-resting-order listing, the one-way short
account's positions, the venue's own refusal code and message, and the
code-0 envelope its cancel answers with.  The last section drives the
real :class:`~router.bingx_client.BingXClient` over an injected transport
that serves the same recordings, so the requests the flatten makes are
pinned too: a DELETE whose signed parameters ride in the query string
(the live defect the Stage 1 client was fixed for) and a POST whose
body carries the close's exact parameters under a signature these tests
recompute.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from router.bingx_client import (
    OPEN_ORDERS_PATH,
    ORDER_PATH,
    POSITIONS_PATH,
    BingXClient,
    RouterBingXRefusedError,
    RouterBingXTransportError,
)
from router.bingx_flatten import (
    BINGX_FLATTEN_CODE,
    BINGX_REDUCE_ONLY_TRUE,
    FLATTEN_OUTCOME_CANCELLED,
    FLATTEN_OUTCOME_CLOSED,
    FLATTEN_OUTCOME_REFUSED,
    FlattenCancel,
    FlattenCancelOutcome,
    FlattenClose,
    FlattenCloseOutcome,
    RouterBingXFlattenError,
    flatten_account,
    main,
    open_order_cancel_targets,
    plan_flatten,
    position_close_orders,
)

#: The recorded VST fixtures, as every suite in this member reaches them:
#: inputs, never edited.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: The recorded resting order's identifier — an order that belongs to no
#: book and no rebalance (an operator's probe), which is exactly the order
#: a rebalance-scoped cancel leaves untouched and a flatten must cancel.
FOREIGN_ORDER_ID = "nulliusprobe0000000000000000000000000000"


def _live(name: str) -> dict:
    """One recorded fixture, verbatim."""
    return json.loads((FIXTURES / "live" / name).read_text(encoding="utf-8"))


def _live_listing() -> dict:
    """The live open-orders ``data``: one resting order, wrapped in orders."""
    return _live("open_orders_one_resting.json")["data"]


def _live_resting_row() -> dict:
    """The single resting row of the live recording."""
    return _live_listing()["orders"][0]


def _live_positions() -> list:
    """The live positions ``data``: a DOGE short of 5402 beside a BTC long
    of 0.0236, both spelled with an *unsigned* positionAmt and the
    direction in positionSide — the account the smoke test recorded."""
    return _live("positions_one_way_short.json")["data"]


def _empty_listing() -> dict:
    """The recorded empty listing's ``data`` (``live/open_orders.json``)."""
    return _live("open_orders.json")["data"]


def _recorded_refusal() -> Exception:
    """The venue's own refusal, carried by the recording that caught it.

    ``live/cancel_order_body_params_refused.json`` holds a verbatim
    ``(code, msg)`` pair the venue worded — the answer to the DELETE whose
    signed parameters rode in a body.  It is used here as the scripted
    refusal of a cancel or a close: a *recorded* code and message, so the
    lines a refused target prints are pinned against words the venue
    actually sent, never words a test invented.
    """
    envelope = _live("cancel_order_body_params_refused.json")
    return RouterBingXRefusedError(envelope["code"], envelope["msg"])


#: The recorded code-0 envelope's ``data``: an echoed order document, the
#: shape ``live/cancel_order_ok.json`` carries.  The venue's answer to a
#: *placement* was never recorded (the smoke test's placements were
#: refused, or the answer not kept), and the flatten never reads the
#: answer's payload — it only needs the client to accept it — so the
#: double answers both the cancel and the close with this recorded data
#: rather than inventing a placement shape.
_RECORDED_OK_DATA = _live("cancel_order_ok.json")["data"]


class _FakeVenue:
    """A recording stand-in for feature 1's client at the flatten's seams.

    Serves ``open_orders`` and ``positions`` from scripted payloads — one
    per call, in order, the last repeating — so a test can stage an
    account that changes under the walk (an order that stays open, a
    position that vanishes) and the final read sees what the test wants
    the venue to still hold.  ``cancel_order`` and ``place_order`` record
    what they were handed and answer with the recorded code-0 data, and a
    test stages a refusal per identifier (cancels) or per call number
    (closes) by parking the exception to raise.
    """

    def __init__(
        self,
        *,
        open_orders_data: list | None = None,
        positions_data: list | None = None,
    ) -> None:
        self._open_orders = list(open_orders_data or [[]])
        self._positions = list(positions_data or [[]])
        self.open_orders_calls = 0
        self.positions_calls = 0
        #: Every call in the order it arrived, method first — so a test
        #: can prove the cancels ran before the closes.
        self.calls: list[tuple] = []
        self.cancelled: list[tuple[str, str | None]] = []
        self.placed: list[dict] = []
        self.cancel_refusals: dict[str, Exception] = {}
        self.place_refusals: dict[int, Exception] = {}

    def open_orders(self, symbol: str | None = None):
        self.open_orders_calls += 1
        self.calls.append(("open_orders", symbol))
        return self._open_orders[min(self.open_orders_calls, len(self._open_orders)) - 1]

    def positions(self, symbol: str | None = None):
        self.positions_calls += 1
        self.calls.append(("positions", symbol))
        return self._positions[min(self.positions_calls, len(self._positions)) - 1]

    def cancel_order(self, client_order_id: str, *, symbol: str | None = None):
        self.calls.append(("cancel_order", client_order_id, symbol))
        self.cancelled.append((client_order_id, symbol))
        refusal = self.cancel_refusals.get(client_order_id)
        if refusal is not None:
            raise refusal
        return _RECORDED_OK_DATA

    def place_order(self, order):
        self.calls.append(("place_order", dict(order)))
        self.placed.append(dict(order))
        refusal = self.place_refusals.get(len(self.placed))
        if refusal is not None:
            raise refusal
        return _RECORDED_OK_DATA


def _stdout_lines(capsys) -> list[dict]:
    """The command's stdout as decoded JSON lines."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


# -- The plan: every open order on the account, every position -----------------


def test_the_plan_cancels_every_open_order_the_account_holds() -> None:
    """The live listing's one resting order — an operator's probe that
    belongs to no book and no rebalance — is a target, because a flatten
    empties the account rather than one rebalance's corner of it."""
    client = _FakeVenue(open_orders_data=[_live_listing()])

    plan = plan_flatten(client=client)

    assert plan.cancels == (
        FlattenCancel(client_order_id=FOREIGN_ORDER_ID, symbol="SOL-USDT"),
    )


def test_a_row_spelled_with_the_placement_identifier_is_read_as_well() -> None:
    """The listing's own spelling is ``clientOrderId`` (one letter off the
    placement parameter); a row carrying the capital-``ID`` spelling names
    the same order and is read the same."""
    row = dict(_live_resting_row())
    del row["clientOrderId"]
    row["clientOrderID"] = FOREIGN_ORDER_ID
    client = _FakeVenue(open_orders_data=[{"orders": [row]}])

    plan = plan_flatten(client=client)

    assert plan.cancels == (
        FlattenCancel(client_order_id=FOREIGN_ORDER_ID, symbol="SOL-USDT"),
    )


@pytest.mark.parametrize(
    "listing",
    [
        pytest.param([], id="a bare empty array"),
        pytest.param({"orders": []}, id="the recorded wrapped empty listing"),
    ],
)
def test_an_account_with_no_open_order_plans_no_cancels(listing: object) -> None:
    """Both shapes the venue answers an empty listing in are read as
    empty: the bare array, and the wrapped ``{"orders": []}`` the
    recording carries."""
    client = _FakeVenue(open_orders_data=[listing])

    assert plan_flatten(client=client).cancels == ()


def test_every_row_of_the_listing_is_a_target_in_the_venues_own_order() -> None:
    """Three rows — this book's, another book's, an operator's probe — are
    three targets, in the order the venue listed them."""
    rows = [
        {"clientOrderId": "a" * 40, "symbol": "BTC-USDT"},
        {"clientOrderId": "b" * 40, "symbol": "ETH-USDT"},
        dict(_live_resting_row()),
    ]
    client = _FakeVenue(open_orders_data=[{"orders": rows}])

    targets = open_order_cancel_targets(client=client)

    assert [target.client_order_id for target in targets] == [
        "a" * 40,
        "b" * 40,
        FOREIGN_ORDER_ID,
    ]


def test_a_row_that_names_no_identifier_is_refused_not_skipped() -> None:
    """Every row of the listing is a target of this act, so a row naming no
    order under either spelling is a row the flatten cannot address —
    refused, never skipped as foreign the way a rebalance-scoped cancel
    skips it, because a silent skip would print a successful-looking run
    over an order the account still holds."""
    client = _FakeVenue(open_orders_data=[{"orders": [{"symbol": "BTC-USDT"}]}])

    with pytest.raises(RouterBingXFlattenError, match=BINGX_FLATTEN_CODE):
        plan_flatten(client=client)


def test_a_listing_that_is_not_a_listing_is_refused() -> None:
    """A response that is not an array of order objects cannot be read into
    targets at all."""
    client = _FakeVenue(open_orders_data=[{"total": 0}])

    with pytest.raises(RouterBingXFlattenError, match=BINGX_FLATTEN_CODE):
        plan_flatten(client=client)


def test_a_listing_row_that_is_not_an_object_is_refused() -> None:
    client = _FakeVenue(open_orders_data=[["not-an-order"]])

    with pytest.raises(RouterBingXFlattenError, match=BINGX_FLATTEN_CODE):
        plan_flatten(client=client)


def test_a_client_without_the_listing_method_is_refused() -> None:
    class _NoListing:
        def positions(self, symbol=None):
            return []

    with pytest.raises(RouterBingXFlattenError, match="open_orders"):
        plan_flatten(client=_NoListing())


def test_a_row_without_a_symbol_is_still_cancelled_by_its_identifier() -> None:
    """The cancel is addressed by identifier; a symbol the row never
    carried is not one to invent, and the target holds ``None``."""
    row = {key: value for key, value in _live_resting_row().items()
           if key != "symbol"}
    client = _FakeVenue(open_orders_data=[{"orders": [row]}])

    plan = plan_flatten(client=client)

    assert plan.cancels == (
        FlattenCancel(client_order_id=FOREIGN_ORDER_ID, symbol=None),
    )


# -- The plan's closes: one per symbol, read off the position document ---------


def test_the_live_one_way_short_account_plans_one_close_per_symbol() -> None:
    """The recorded account — a DOGE short of 5402 beside a BTC long of
    0.0236 — answers exactly two closes: the side opposite to each row's
    own positionSide, the quantity the row's own unsigned positionAmt,
    positionSide BOTH, type MARKET, reduceOnly true."""
    client = _FakeVenue(positions_data=[_live_positions()])

    closes = position_close_orders(client=client)

    assert [close.parameters() for close in closes] == [
        {
            "symbol": "DOGE-USDT",
            "side": "BUY",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "5402",
            "reduceOnly": "true",
        },
        {
            "symbol": "BTC-USDT",
            "side": "SELL",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "0.0236",
            "reduceOnly": "true",
        },
    ]


def test_a_short_is_closed_by_a_buy_and_a_long_by_a_sell() -> None:
    """The side is the *opposite* of the position's own positionSide — the
    sentence's own word — read off the signed quantity Stage 1's reader
    answers, so a short can never be closed by a sell that doubles it."""
    client = _FakeVenue(positions_data=[_live_positions()])

    closes = position_close_orders(client=client)

    assert [close.side for close in closes] == ["BUY", "SELL"]


def test_the_quantity_is_the_plain_positional_spelling_of_the_position_amt() -> None:
    """``"5402"`` stays ``"5402"`` and a magnitude with scale keeps its
    scale, in plain positional notation — never an exponent form a venue
    never sent and never a float's re-serialisation."""
    row = {
        "symbol": "ETH-USDT",
        "positionAmt": "1.4000",
        "positionSide": "SHORT",
    }
    client = _FakeVenue(positions_data=[[row]])

    closes = position_close_orders(client=client)

    assert [close.quantity for close in closes] == ["1.4000"]


def test_a_position_of_zero_closes_nothing() -> None:
    """A row with nothing held has no position to close, and an order for
    zero units is not one any venue books."""
    client = _FakeVenue(
        positions_data=[[{"symbol": "BTC-USDT", "positionAmt": "0",
                          "positionSide": "LONG"}]]
    )

    assert position_close_orders(client=client) == []


def test_a_flat_account_closes_nothing() -> None:
    """The empty positions array — the flat account — answers no closes,
    which is the state a flatten of an already-empty account is."""
    client = _FakeVenue(positions_data=[[]])

    assert position_close_orders(client=client) == []


# -- The close order value -------------------------------------------------------


def test_a_close_spells_its_parameters_in_the_venues_own_fields() -> None:
    """``symbol``, ``side``, ``positionSide``, ``type``, ``quantity``,
    ``reduceOnly`` — the venue's own field spellings, every value a
    string, and no ``clientOrderID``: the identity feature 316 folds
    belongs to book orders, and a flatten holds no book."""
    close = FlattenClose(symbol="DOGE-USDT", side="BUY", quantity="5402")

    assert close.parameters() == {
        "symbol": "DOGE-USDT",
        "side": "BUY",
        "positionSide": "BOTH",
        "type": "MARKET",
        "quantity": "5402",
        "reduceOnly": "true",
    }


def test_a_close_carries_the_venues_own_lowercase_true() -> None:
    """``reduceOnly`` is the exact string ``"true"`` — the spelling the
    venue's own documents write — because ``urlencode`` would render a
    Python ``True`` as ``"True"``, a capitalised spelling no venue
    document carries."""
    close = FlattenClose(symbol="DOGE-USDT", side="BUY", quantity="5402")

    assert close.parameters()["reduceOnly"] == BINGX_REDUCE_ONLY_TRUE
    assert BINGX_REDUCE_ONLY_TRUE == "true"


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"side": "HOLD"}, id="a side outside the two"),
        pytest.param({"type": "LIMIT"}, id="a type other than MARKET"),
        pytest.param(
            {"position_side": "LONG"}, id="a positionSide other than BOTH"
        ),
        pytest.param({"reduce_only": "false"}, id="a reduceOnly other than true"),
        pytest.param({"quantity": "0"}, id="a quantity of zero"),
        pytest.param({"quantity": "-1"}, id="a negative quantity"),
        pytest.param({"quantity": "NaN"}, id="a quantity that is not a number"),
        pytest.param({"quantity": "five"}, id="a quantity that is not a decimal"),
    ],
)
def test_a_close_that_cannot_close_a_position_is_refused(kwargs: dict) -> None:
    """A value built by hand gets the judgment the verb applies: a side
    that does not close the holding, a resting close, a hedge-mode
    positionSide, a close that could open a position, and a size no venue
    books are each refused naming the repair."""
    fields = {"symbol": "DOGE-USDT", "side": "BUY", "quantity": "5402"}
    fields.update(kwargs)

    with pytest.raises(RouterBingXFlattenError, match=BINGX_FLATTEN_CODE):
        FlattenClose(**fields)


def test_a_close_refuses_a_quantity_offered_as_a_number() -> None:
    """The quantity is the exact decimal spelling the position document
    carried; a float or an int handed in its place is refused by name,
    because a number re-serialised at the send would be a second spelling
    of a magnitude the venue already chose."""
    with pytest.raises(RouterBingXFlattenError, match="float"):
        FlattenClose(symbol="DOGE-USDT", side="BUY", quantity=5402.0)


def test_a_cancel_target_refuses_an_identifier_that_names_no_order() -> None:
    with pytest.raises(RouterBingXFlattenError, match=BINGX_FLATTEN_CODE):
        FlattenCancel(client_order_id="   ", symbol="BTC-USDT")
    with pytest.raises(RouterBingXFlattenError, match=BINGX_FLATTEN_CODE):
        FlattenCancel(client_order_id="x" * 41, symbol="BTC-USDT")


# -- The confirmed walk ----------------------------------------------------------


def test_every_open_order_is_cancelled_by_identifier_with_its_symbol() -> None:
    client = _FakeVenue(open_orders_data=[_live_listing(), _empty_listing()])

    flatten_account(client=client)

    assert client.cancelled == [(FOREIGN_ORDER_ID, "SOL-USDT")]


def test_the_cancels_run_before_the_closes() -> None:
    """The sentence's own order, and the safe one: a resting order is a
    promise the account may still keep, so every cancel precedes the
    first close.  The whole call sequence is pinned — one listing read,
    every cancel, one positions read, every close, then the final read of
    each — because the order is the clause."""
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[_live_positions(), []],
    )

    flatten_account(client=client)

    assert [call[0] for call in client.calls] == [
        "open_orders",
        "cancel_order",
        "positions",
        "place_order",
        "place_order",
        "open_orders",
        "positions",
    ]


def test_one_close_is_placed_per_symbol_reduce_only() -> None:
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[_live_positions(), []],
    )

    flatten_account(client=client)

    assert client.placed == [
        {
            "symbol": "DOGE-USDT",
            "side": "BUY",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "5402",
            "reduceOnly": "true",
        },
        {
            "symbol": "BTC-USDT",
            "side": "SELL",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "0.0236",
            "reduceOnly": "true",
        },
    ]


def test_one_json_line_per_cancelled_order_and_per_close(capsys) -> None:
    """One line for the cancelled probe and one per close, in the order the
    walk performed them, each a standalone JSON object."""
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[_live_positions(), []],
    )

    flatten_account(client=client)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        {"clientOrderID": FOREIGN_ORDER_ID},
        {
            "symbol": "DOGE-USDT",
            "side": "BUY",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "5402",
            "reduceOnly": "true",
        },
        {
            "symbol": "BTC-USDT",
            "side": "SELL",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "0.0236",
            "reduceOnly": "true",
        },
    ]


def test_the_report_carries_the_outcomes_and_the_final_reads_verdict() -> None:
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[_live_positions(), []],
    )

    report = flatten_account(client=client)

    assert report.cancelled_ids == (FOREIGN_ORDER_ID,)
    assert [o.outcome for o in report.cancel_outcomes] == [
        FLATTEN_OUTCOME_CANCELLED
    ]
    assert [o.outcome for o in report.close_outcomes] == [
        FLATTEN_OUTCOME_CLOSED,
        FLATTEN_OUTCOME_CLOSED,
    ]
    assert report.remaining_open_orders == ()
    assert report.remaining_positions == ()
    assert report.flat
    assert not report.refused
    assert report.succeeded


def test_a_client_without_the_place_method_is_refused() -> None:
    class _ReadOnly:
        def open_orders(self, symbol=None):
            return _empty_listing()

        def positions(self, symbol=None):
            return []

        def cancel_order(self, client_order_id, *, symbol=None):
            return _RECORDED_OK_DATA

    with pytest.raises(RouterBingXFlattenError, match="place_order"):
        flatten_account(client=_ReadOnly())


def test_a_client_without_the_cancel_method_is_refused() -> None:
    class _NoCancel:
        def open_orders(self, symbol=None):
            return _empty_listing()

        def positions(self, symbol=None):
            return []

        def place_order(self, order):
            return _RECORDED_OK_DATA

    with pytest.raises(RouterBingXFlattenError, match="cancel_order"):
        flatten_account(client=_NoCancel())


# -- Refusals: printed with the venue's own code and message ---------------------


def test_a_close_the_venue_refuses_is_printed_with_its_code_and_message(
    capsys,
) -> None:
    """The sentence's own clause: the refused close prints *its* parameters
    beside the recorded code and the venue's own message, and the run
    exits 1."""
    refusal = _recorded_refusal()
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[_live_positions(), []],
    )
    client.place_refusals[1] = refusal

    report = flatten_account(client=client)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[1] == {
        "symbol": "DOGE-USDT",
        "side": "BUY",
        "positionSide": "BOTH",
        "type": "MARKET",
        "quantity": "5402",
        "reduceOnly": "true",
        "code": "109400",
        "message": _live("cancel_order_body_params_refused.json")["msg"],
    }
    assert report.close_outcomes[0].outcome == FLATTEN_OUTCOME_REFUSED
    assert report.close_outcomes[0].code == "109400"
    assert not report.succeeded


def test_a_refused_close_does_not_stop_the_other_closes() -> None:
    """One leg's refusal never answers for its siblings: the DOGE close is
    refused and the BTC close is still placed."""
    client = _FakeVenue(
        open_orders_data=[_empty_listing()],
        positions_data=[_live_positions(), []],
    )
    client.place_refusals[1] = _recorded_refusal()

    report = flatten_account(client=client)

    assert [o.outcome for o in report.close_outcomes] == [
        FLATTEN_OUTCOME_REFUSED,
        FLATTEN_OUTCOME_CLOSED,
    ]
    assert [order["symbol"] for order in client.placed] == ["DOGE-USDT", "BTC-USDT"]


def test_a_refused_close_exits_one_even_when_the_final_read_is_flat() -> None:
    """Exit 0 is not the final read's alone to give: a close the venue
    refused hands the run exit 1 even if the position vanished around it,
    because a run that reported success over a refusal it printed would be
    a run nobody could trust on the closes that mattered."""
    client = _FakeVenue(
        open_orders_data=[_empty_listing()],
        positions_data=[_live_positions(), []],
    )
    client.place_refusals[1] = _recorded_refusal()
    client.place_refusals[2] = _recorded_refusal()

    report = flatten_account(client=client)

    assert report.flat
    assert report.refused
    assert not report.succeeded


def test_a_cancel_the_venue_refuses_is_printed_with_its_code_and_message(
    capsys,
) -> None:
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[[], []],
    )
    client.cancel_refusals[FOREIGN_ORDER_ID] = _recorded_refusal()

    report = flatten_account(client=client)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        {
            "clientOrderID": FOREIGN_ORDER_ID,
            "code": "109400",
            "message": _live("cancel_order_body_params_refused.json")["msg"],
        }
    ]
    assert report.cancel_outcomes[0].outcome == FLATTEN_OUTCOME_REFUSED
    assert not report.succeeded


def test_a_transport_failure_on_one_close_is_a_refused_line_not_a_crash() -> None:
    """A dropped connection on one close is that close's refused line —
    the code column carrying the refusal's own token — and the walk keeps
    closing what it can, because a flatten is the one act that must not
    stop halfway for a single target's fault."""
    client = _FakeVenue(
        open_orders_data=[_empty_listing()],
        positions_data=[_live_positions(), []],
    )
    client.place_refusals[1] = RouterBingXTransportError(
        "POST", "https://open-api-vst.bingx.com/openApi/swap/v2/trade/order",
        "the connection dropped", outcome_unknown=True,
    )

    report = flatten_account(client=client)

    assert [o.code for o in report.close_outcomes] == [
        "RouterBingXTransportError",
        None,
    ]
    assert report.close_outcomes[0].message is None
    assert len(client.placed) == 2
    assert not report.succeeded


def test_an_outcome_word_outside_the_two_is_refused() -> None:
    target = FlattenCancel(client_order_id=FOREIGN_ORDER_ID, symbol="SOL-USDT")
    with pytest.raises(RouterBingXFlattenError, match=BINGX_FLATTEN_CODE):
        FlattenCancelOutcome(target=target, outcome="gone")


def test_an_outcome_the_venue_took_carries_no_refusal_terms() -> None:
    close = FlattenClose(symbol="DOGE-USDT", side="BUY", quantity="5402")
    with pytest.raises(RouterBingXFlattenError, match="nothing to explain"):
        FlattenCloseOutcome(
            close=close, outcome=FLATTEN_OUTCOME_CLOSED, code="109400"
        )


# -- The final read is the arbiter of exit 0 --------------------------------------


def test_the_run_exits_one_when_an_order_is_still_open(capsys) -> None:
    """The cancel was taken, the closes were taken, and still the account
    holds an open order — the final read's verdict, named on stderr."""
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _live_listing()],
        positions_data=[[], []],
    )

    exit_code = main(["--confirm"], client=client)

    assert exit_code == 1
    assert FOREIGN_ORDER_ID in capsys.readouterr().err


def test_the_run_exits_one_when_a_position_is_still_held(capsys) -> None:
    client = _FakeVenue(
        open_orders_data=[_empty_listing(), _empty_listing()],
        positions_data=[_live_positions(), _live_positions()],
    )

    report = flatten_account(client=client)

    assert not report.flat
    assert [close.symbol for close in report.remaining_positions] == [
        "DOGE-USDT",
        "BTC-USDT",
    ]
    assert main(["--confirm"], client=client) == 1
    assert "DOGE-USDT" in capsys.readouterr().err


def test_a_flat_final_read_with_nothing_refused_succeeds() -> None:
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[_live_positions(), []],
    )

    assert flatten_account(client=client).succeeded
    assert main([], client=client) == 0


def test_an_already_flat_account_confirms_to_exit_zero_printing_nothing(
    capsys,
) -> None:
    """The re-run of a successful flatten: nothing to cancel, nothing to
    close, and the final read agrees — exit 0, one JSON line for nothing,
    which is the state the exit-0 clause itself describes."""
    client = _FakeVenue(
        open_orders_data=[_empty_listing(), _empty_listing()],
        positions_data=[[], []],
    )

    exit_code = main(["--confirm"], client=client)

    assert exit_code == 0
    assert capsys.readouterr().out == ""


# -- Without --confirm: print what it would do, change nothing -------------------


def test_without_confirm_it_prints_what_it_would_do_and_changes_nothing(
    capsys,
) -> None:
    """The dry run prints the same lines a confirmed run prints — the
    cancel line and each close's parameters — and sends no cancel and no
    close."""
    client = _FakeVenue(
        open_orders_data=[_live_listing()],
        positions_data=[_live_positions()],
    )

    exit_code = main([], client=client)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(lines) == 3
    assert lines[0] == {"clientOrderID": FOREIGN_ORDER_ID}
    assert lines[1]["symbol"] == "DOGE-USDT"
    assert lines[2]["symbol"] == "BTC-USDT"
    assert client.cancelled == []
    assert client.placed == []


def test_without_confirm_it_reads_once_and_makes_no_final_read() -> None:
    """The dry run makes exactly the two reads the plan needs — the listing
    and the positions — and no final read, because nothing changed."""
    client = _FakeVenue(
        open_orders_data=[_live_listing()],
        positions_data=[_live_positions()],
    )

    main([], client=client)

    assert client.open_orders_calls == 1
    assert client.positions_calls == 1


def test_without_confirm_a_refusal_scripted_on_the_venue_is_never_met() -> None:
    """Nothing is sent, so a venue that would refuse everything is never
    asked: the dry run changes nothing, refusals included."""
    client = _FakeVenue(
        open_orders_data=[_live_listing()],
        positions_data=[_live_positions()],
    )
    client.cancel_refusals[FOREIGN_ORDER_ID] = _recorded_refusal()
    client.place_refusals[1] = _recorded_refusal()

    assert main([], client=client) == 0


def test_with_confirm_the_command_flattens_the_recorded_account(capsys) -> None:
    """The operator's door: ``--confirm`` performs the walk, prints one
    line per cancelled order and per close, and exits 0 over an account
    the final read shows flat."""
    client = _FakeVenue(
        open_orders_data=[_live_listing(), _empty_listing()],
        positions_data=[_live_positions(), []],
    )

    exit_code = main(["--confirm"], client=client)

    assert exit_code == 0
    assert len(_stdout_lines(capsys)) == 3
    assert client.cancelled == [(FOREIGN_ORDER_ID, "SOL-USDT")]
    assert len(client.placed) == 2


def test_a_read_fault_is_reported_on_stderr_and_exits_one(capsys) -> None:
    """A listing the module cannot read is a fault of the ask: reported on
    stderr under the module's code word, with nothing printed on stdout."""
    client = _FakeVenue(open_orders_data=[{"total": 0}])

    exit_code = main(["--confirm"], client=client)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert BINGX_FLATTEN_CODE in captured.err


# -- The wire: the requests the real client makes ---------------------------------


class _WireStandIn:
    """A transport for the real client, serving the recorded envelopes.

    Records every request — method, path, decoded parameters, headers —
    and serves the account's documents from the recordings: the
    one-resting-order listing, the one-way short positions, the venue's
    code-0 cancel answer, and (for the placement no recording covers, and
    whose payload the flatten never reads) the same code-0 envelope.  The
    account flattens under the walk — the second listing is the recorded
    empty one, the second positions answer an empty array of the recorded
    shape — so a full ``--confirm`` over the real client exits 0.  No
    socket is opened: the transport is the client's own injected seam.
    """

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self._listings = [_live("open_orders_one_resting.json"), _live("open_orders.json")]
        self._positions = [
            _live("positions_one_way_short.json"),
            {"code": 0, "msg": "", "data": []},
        ]

    def __call__(self, method: str, url: str, headers: dict, body: bytes):
        query = urlsplit(url).query
        raw = body.decode("ascii") if method == "POST" and body else query
        self.requests.append(
            {
                "method": method,
                "path": urlsplit(url).path,
                "params": dict(parse_qsl(raw)),
                "headers": dict(headers),
            }
        )
        if method == "GET" and urlsplit(url).path == OPEN_ORDERS_PATH:
            return 200, json.dumps(self._listings.pop(0)).encode("utf-8")
        if method == "GET" and urlsplit(url).path == POSITIONS_PATH:
            return 200, json.dumps(self._positions.pop(0)).encode("utf-8")
        if method == "DELETE":
            return 200, json.dumps(_live("cancel_order_ok.json")).encode("utf-8")
        return 200, json.dumps(_live("cancel_order_ok.json")).encode("utf-8")


def _wire_client(stand_in: _WireStandIn) -> BingXClient:
    """The real client over the stand-in: VST host, signed, host-guarded."""
    return BingXClient(
        api_key="wire-fake-key",
        secret_key="wire-fake-secret",
        transport=stand_in,
    )


def _verified_params(params: dict) -> dict:
    """Assert the request's signature recomputes, and answer its terms.

    The same check the loopback suite makes: the sorted, encoded
    parameters minus the signature, HMAC-SHA256 keyed by the fake secret,
    compared to the signature the client appended.  A request that fails
    this is not a request the venue would have honoured.
    """
    signed = {k: v for k, v in params.items() if k != "signature"}
    expected = hmac.new(
        b"wire-fake-secret",
        urlencode(sorted(signed.items())).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(expected, params.get("signature", ""))
    assert "timestamp" in signed and "recvWindow" in signed
    return signed


def test_the_cancel_is_a_delete_with_its_signed_parameters_in_the_query_string() -> None:
    """The live defect, pinned at the flatten's own door: BingX reads a
    DELETE's parameters from the query string only — a DELETE whose
    signed string rode in a body was refused with code 109400 (the
    recorded refusal these tests also script) — so the cancel the flatten
    sends carries its identifier, symbol and signature in the URL."""
    stand_in = _WireStandIn()
    main(["--confirm"], client=_wire_client(stand_in))

    delete = [r for r in stand_in.requests if r["method"] == "DELETE"]
    assert len(delete) == 1
    assert delete[0]["path"] == ORDER_PATH
    signed = _verified_params(delete[0]["params"])
    assert signed["clientOrderID"] == FOREIGN_ORDER_ID
    assert signed["symbol"] == "SOL-USDT"


def test_the_close_is_a_post_carrying_the_exact_parameters() -> None:
    """The close the venue is asked to take is exactly the sentence's
    parameters — DOGE first (the venue's own positions order), the side
    opposite to the row's positionSide, the unsigned positionAmt,
    positionSide BOTH, reduceOnly true — under a signature that
    recomputes."""
    stand_in = _WireStandIn()
    main(["--confirm"], client=_wire_client(stand_in))

    posts = [r for r in stand_in.requests if r["method"] == "POST"]
    assert len(posts) == 2
    assert [r["path"] for r in posts] == [ORDER_PATH, ORDER_PATH]
    first = _verified_params(posts[0]["params"])
    second = _verified_params(posts[1]["params"])
    assert first == {
        "symbol": "DOGE-USDT",
        "side": "BUY",
        "positionSide": "BOTH",
        "type": "MARKET",
        "quantity": "5402",
        "reduceOnly": "true",
        "timestamp": first["timestamp"],
        "recvWindow": first["recvWindow"],
    }
    assert second["symbol"] == "BTC-USDT"
    assert second["side"] == "SELL"
    assert second["quantity"] == "0.0236"
    assert second["reduceOnly"] == "true"
    assert "clientOrderID" not in first and "clientOrderID" not in second


def test_a_full_flatten_over_the_real_client_exits_zero(capsys) -> None:
    """End to end over the real signed client: the recorded account — one
    resting probe order, a DOGE short, a BTC long — flattens in the
    sentence's order (cancel, then closes), the final read over the same
    client shows no open orders and no positions, and the command exits 0
    with one JSON line per cancelled order and per close."""
    stand_in = _WireStandIn()

    exit_code = main(["--confirm"], client=_wire_client(stand_in))

    assert exit_code == 0
    assert _stdout_lines(capsys) == [
        {"clientOrderID": FOREIGN_ORDER_ID},
        {
            "symbol": "DOGE-USDT",
            "side": "BUY",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "5402",
            "reduceOnly": "true",
        },
        {
            "symbol": "BTC-USDT",
            "side": "SELL",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "0.0236",
            "reduceOnly": "true",
        },
    ]
    methods = [request["method"] for request in stand_in.requests]
    assert methods.index("DELETE") < methods.index("POST")


def test_the_dry_run_over_the_real_client_sends_no_delete_and_no_post() -> None:
    stand_in = _WireStandIn()

    exit_code = main([], client=_wire_client(stand_in))

    assert exit_code == 0
    assert [r["method"] for r in stand_in.requests] == ["GET", "GET"]
