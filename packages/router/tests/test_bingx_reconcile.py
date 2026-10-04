"""Tests for :mod:`router.bingx_reconcile` — feature 3's fill-cost act.

Feature 3 of additions_spec_bingx_vst_stage2.xml: *System reconciles one
finished rebalance's fill costs.  It reads back the rebalance's orders with
read_back_orders and takes each filled order's executedQty and avgPrice.
The realized cost in basis points is the notional-weighted signed slippage
of avgPrice against the order's reference price (adverse is positive), plus
the fee rate the order paid.  The fee is makerFeeRate for a PostOnly LIMIT
and takerFeeRate for a MARKET order, from the contracts document.  The
modeled cost is that same fee rate alone.  It records both through
forward.reconciliation.reconcile_fill_costs(book_id, rebalance_ts=,
realized_cost_bps=, modeled_cost_bps=), and returns the recorded
reconciliation.  A rebalance with no filled order records nothing and
returns none.  Reconciling the same rebalance twice returns the first
record unchanged.*

Every clause of that sentence is held below, over a recording double that
stands in for feature 1's client (never a socket).  The double serves the
two order documents this act reads — the single-order read nested under
``data.order`` — and refuses an order it holds no record of with the
venue's own not-found code, exactly as the live endpoint does.  The
contracts and premiumIndex documents are the recorded fixtures
``fixtures/bingx_vst/contracts.json`` and
``fixtures/bingx_vst/premium_index.json``, and the order answers are
derived from the live recording ``live/query_order_pending.json``'s order
document rather than invented, so the venue's own field spellings are what
the act is exercised against.

The figures are asserted against arithmetic written out in the test — the
reference price, the signed slippage in basis points, the fee in basis
points and the notional weights — so the test proves *which* reference and
*which* rate were read, rather than re-running the implementation's own
formula.  The store is feature 340's own: the reconciliation is read back
through :func:`forward.reconciliation.reconciled_fill_costs`, so a row that
landed is proven to have landed where β₄'s recalibration and §16's live
metric will look for it.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from forward.reconciliation import (
    ForwardCostReconciliations,
    reconciled_fill_costs,
)
from router.bingx_client import ORDER_NOT_FOUND_CODE, RouterBingXRefusedError
from router.bingx_client_order_id import project_bingx_client_order_id
from router.bingx_order import BingXRefusedLeg
from router.bingx_orders import RouterBingXOrdersError
from router.bingx_reconcile import (
    BINGX_RECONCILE_CODE,
    RouterBingXReconcileError,
    reconcile_rebalance_fill_costs,
)
from router.client_order_id import derive_client_order_id

BOOK_ID = "synthetic-vst-0"
REBALANCE_TS = datetime.fromisoformat("2026-09-30T00:00:00+00:00")

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: The recorded rates the fixtures carry: ``0.0002`` maker and ``0.0005``
#: taker, as basis points.  Every symbol in the contracts fixture states
#: both, so a fee read off the document is 2 bps for a LIMIT leg and 5 bps
#: for a MARKET leg.
MAKER_BPS = Decimal(2)
TAKER_BPS = Decimal(5)


def _identifier(symbol: str) -> str:
    """Feature 3's projection of feature 316's identifier for one leg."""
    return project_bingx_client_order_id(
        derive_client_order_id(
            book_id=BOOK_ID, rebalance_ts=REBALANCE_TS, symbol=symbol
        )
    )


def _leg(
    symbol: str, *, side: str = "BUY", type_: str = "LIMIT", price: str = "100"
) -> dict:
    """A plan-shaped leg — the venue's own field spellings."""
    leg = {
        "symbol": symbol,
        "side": side,
        "positionSide": "BOTH",
        "type": type_,
        "quantity": "1",
        "clientOrderID": _identifier(symbol),
    }
    if type_ == "LIMIT":
        leg["price"] = price
        leg["timeInForce"] = "PostOnly"
    return leg


def _recorded_answer() -> dict:
    """The live single-order answer, as feature 1's ``query_order`` hands it.

    Read from ``live/query_order_pending.json`` — the venue's verbatim
    answer for a resting order — so the order document this suite derives
    every filled answer from carries the venue's own field spellings.  The
    fixture is an input and is never edited.
    """
    answer = json.loads(
        (FIXTURES / "live" / "query_order_pending.json").read_text(
            encoding="utf-8"
        )
    )
    return answer["data"]


def _filled_answer(
    client_order_id: str, *, symbol: str, type_: str, qty: str, price: str
) -> dict:
    """A filled order answer, derived from the recorded one.

    The recorded order document, with the status, the type, the symbol and
    the two measurements replaced by this fill's — so the answer speaks the
    venue's own shape (nested under ``order``, decimals spelled as strings)
    while describing a completely filled order, which the live account
    happened not to be holding when the fixture was captured.
    """
    order = dict(_recorded_answer()["order"])
    order["clientOrderId"] = client_order_id
    order["symbol"] = symbol
    order["type"] = type_
    order["status"] = "FILLED"
    order["executedQty"] = qty
    order["avgPrice"] = price
    return {"order": order}


def _contracts_document() -> dict:
    """The recorded contracts document, as feature 1's ``contracts`` hands it.

    ``client.contracts()`` answers the envelope's ``data`` list, so this is
    that list — the recorded fixture's, never edited.
    """
    return json.loads((FIXTURES / "contracts.json").read_text(encoding="utf-8"))["data"]


def _marks_document() -> dict:
    """The recorded premiumIndex document, as feature 1's hand answers it."""
    return json.loads(
        (FIXTURES / "premium_index.json").read_text(encoding="utf-8")
    )["data"]


def _mark(symbol: str) -> Decimal:
    """The recorded mark price for ``symbol``, exactly as the fixture spells it."""
    for row in _marks_document():
        if row["symbol"] == symbol:
            return Decimal(row["markPrice"])
    raise AssertionError(f"the recorded premiumIndex prices no {symbol}")


class _FakeClient:
    """A recording stand-in for feature 1's client.

    Answers ``query_order`` from a scripted map keyed by ``clientOrderID``
    (an order answer, or an exception to raise) and serves the two venue
    documents from the recorded fixtures.  Records every lookup, so a test
    can assert exactly which orders were read back and that the two
    documents were fetched through the client rather than assumed.
    """

    def __init__(self, *, queries: dict | None = None) -> None:
        self._queries = queries or {}
        self.queried: list[tuple[str, str | None]] = []
        self.contracts_calls = 0
        self.premium_index_calls = 0

    def query_order(self, client_order_id: str, *, symbol: str | None = None):
        self.queried.append((client_order_id, symbol))
        answer = self._queries.get(client_order_id)
        if answer is None:
            raise RouterBingXRefusedError(ORDER_NOT_FOUND_CODE, "order not exist")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def contracts(self):
        self.contracts_calls += 1
        return _contracts_document()

    def premium_index(self):
        self.premium_index_calls += 1
        return _marks_document()


# -- A filled LIMIT leg: limit reference, maker fee ----------------------------


def test_a_filled_limit_leg_is_priced_against_its_limit_at_the_maker_rate(
    test_database_url: str,
) -> None:
    """The sentence's whole arithmetic for one passive fill.

    A BUY that filled above its limit is adverse: slippage is positive.  The
    fee is the maker rate — 2 bps from the fixture — because the leg is a
    PostOnly LIMIT.  Modeled is the fee alone, and the difference the store
    computes is the slippage.
    """
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="BTC-USDT", type_="LIMIT", qty="2", price="101")}
    )

    record = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("BTC-USDT", price="100")],
        database_url=test_database_url,
    )

    assert record is not None
    # slippage = (101 - 100) / 100 * 10000 = 100 bps; fee = 2 bps.
    assert record.realized_cost_bps == pytest.approx(102.0)
    assert record.modeled_cost_bps == pytest.approx(float(MAKER_BPS))
    assert record.difference_bps == pytest.approx(100.0)
    assert record.book_id == BOOK_ID
    # The read-back looked the leg up by its own identifier.
    assert client.queried == [(cid, "BTC-USDT")]


def test_a_filled_market_leg_is_priced_against_its_mark_at_the_taker_rate(
    test_database_url: str,
) -> None:
    """An aggressive fill's reference is its symbol's mark, its fee the taker rate.

    A MARKET leg carries no price, so the reference is read from the venue's
    premiumIndex document; and the leg crossed, so it pays the taker rate —
    5 bps — never the maker's 2.
    """
    cid = _identifier("ETH-USDT")
    mark = _mark("ETH-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="ETH-USDT", type_="MARKET", qty="1", price="2700")}
    )

    record = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("ETH-USDT", type_="MARKET")],
        database_url=test_database_url,
    )

    assert record is not None
    expected_slippage = float((Decimal(2700) - mark) / mark * Decimal(10_000))
    assert record.realized_cost_bps == pytest.approx(expected_slippage + float(TAKER_BPS))
    assert record.modeled_cost_bps == pytest.approx(float(TAKER_BPS))
    # The mark was needed, so the client was asked for the document.
    assert client.premium_index_calls == 1


# -- Slippage is adverse-positive on both sides --------------------------------


@pytest.mark.parametrize(
    "side, average",
    [
        ("BUY", "101"),   # bought above the reference -> adverse
        ("SELL", "99"),   # sold below the reference -> adverse
    ],
)
def test_the_slippage_is_adverse_positive_on_both_sides(
    test_database_url: str, side: str, average: str
) -> None:
    """A buy that paid up and a sell that took less are both positive.

    The sign convention is the same one the workspace's own slippage
    figures speak (``cost_model.book_walk``): a fill is *adverse* when it
    moved against the order, whichever side it was.
    """
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="BTC-USDT", type_="LIMIT", qty="1", price=average)}
    )

    record = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("BTC-USDT", side=side, price="100")],
        database_url=test_database_url,
    )

    assert record is not None
    # |slippage| = 1% = 100 bps either way, plus the 2 bps maker fee.
    assert record.realized_cost_bps == pytest.approx(102.0)


# -- Notional weighting --------------------------------------------------------


def test_the_two_figures_are_notional_weighted_across_the_fills(
    test_database_url: str,
) -> None:
    """Each fill contributes in proportion to the notional it actually traded.

    One BUY of 2 at 101 (notional 202, slippage 100 bps) and one BUY of 3 at
    99 (notional 297, slippage -100 bps) — the realized figure is the
    notional-weighted mean, and the modeled figure is the same weighting over
    the fee alone (2 bps, both legs passive).
    """
    ids = {s: _identifier(s) for s in ("BTC-USDT", "ETH-USDT")}
    client = _FakeClient(
        queries={
            ids["BTC-USDT"]: _filled_answer(
                ids["BTC-USDT"], symbol="BTC-USDT", type_="LIMIT", qty="2", price="101"
            ),
            ids["ETH-USDT"]: _filled_answer(
                ids["ETH-USDT"], symbol="ETH-USDT", type_="LIMIT", qty="3", price="99"
            ),
        }
    )
    orders = [_leg("BTC-USDT", price="100"), _leg("ETH-USDT", price="100")]

    record = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=orders,
        database_url=test_database_url,
    )

    assert record is not None
    # notional @ 101 == 2 * 101 == 202 ; @ 99 == 3 * 99 == 297
    # realized = (202 * (100 + 2) + 297 * (-100 + 2)) / (202 + 297)
    expected = (Decimal(202) * Decimal(102) + Decimal(297) * Decimal(-98)) / Decimal(499)
    assert record.realized_cost_bps == pytest.approx(float(expected))
    # modeled = weighted fee alone = 2 bps exactly.
    assert record.modeled_cost_bps == pytest.approx(float(MAKER_BPS))


# -- No filled order: record nothing, answer none ------------------------------


def test_a_rebalance_with_no_filled_order_records_nothing_and_answers_none(
    test_database_url: str,
) -> None:
    """The sentence's third-to-last clause.

    A leg that never filled (``executedQty`` zero) contributes no notional,
    so there is no fill cost to reconcile: no row is written and the answer
    is ``None`` — not a zero cost, which would read as a *perfectly
    calibrated* model.
    """
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="BTC-USDT", type_="LIMIT", qty="0", price="0")}
    )

    answer = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("BTC-USDT")],
        database_url=test_database_url,
    )

    assert answer is None
    assert reconciled_fill_costs(database_url=test_database_url) == ()


def test_a_rebalance_of_only_not_found_legs_records_nothing(
    test_database_url: str,
) -> None:
    """A leg the venue holds no record of has no fill either: still no row."""
    client = _FakeClient()  # every lookup refuses with the venue's not-found code

    answer = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("BTC-USDT"), _leg("ETH-USDT")],
        database_url=test_database_url,
    )

    assert answer is None
    assert reconciled_fill_costs(database_url=test_database_url) == ()


def test_an_unfilled_leg_is_omitted_and_the_filled_one_priced(
    test_database_url: str,
) -> None:
    """A zero-executed leg contributes nothing, and does not hide the filled one."""
    ids = {s: _identifier(s) for s in ("BTC-USDT", "ETH-USDT")}
    client = _FakeClient(
        queries={
            ids["BTC-USDT"]: _filled_answer(
                ids["BTC-USDT"], symbol="BTC-USDT", type_="LIMIT", qty="0", price="0"
            ),
            ids["ETH-USDT"]: _filled_answer(
                ids["ETH-USDT"], symbol="ETH-USDT", type_="LIMIT", qty="1", price="101"
            ),
        }
    )

    record = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("BTC-USDT"), _leg("ETH-USDT", price="100")],
        database_url=test_database_url,
    )

    assert record is not None
    # Only the ETH fill counts: 100 bps slippage + 2 bps maker fee.
    assert record.realized_cost_bps == pytest.approx(102.0)


# -- Idempotence and persistence -----------------------------------------------


def test_reconciling_twice_returns_the_first_record_unchanged(
    test_database_url: str,
) -> None:
    """The sentence's last clause, reached by measuring deterministically.

    The same rebalance measured twice reads the same fills back and hands
    feature 340 the same pair, so its store answers the standing row
    untouched — same sequence, same difference — rather than writing a
    second row.
    """
    cid = _identifier("BTC-USDT")
    answer = _filled_answer(cid, symbol="BTC-USDT", type_="LIMIT", qty="2", price="101")

    def run() -> object:
        client = _FakeClient(queries={cid: answer})
        return reconcile_rebalance_fill_costs(
            client=client,
            book_id=BOOK_ID,
            rebalance_ts=REBALANCE_TS,
            orders=[_leg("BTC-USDT", price="100")],
            database_url=test_database_url,
        )

    first = run()
    second = run()

    assert first == second
    assert reconciled_fill_costs(database_url=test_database_url) == (first,)


def test_the_documents_may_be_handed_in_and_are_then_not_fetched(
    test_database_url: str,
) -> None:
    """A caller holding the two documents hands them in; the client is not asked.

    A rebalance slot has already read both documents for its plan, so the
    acts this module exposes are handed them rather than forcing a second
    fetch — and the fill is priced identically to the fetched path, which is
    what makes handing them in an optimisation rather than a second rule.
    """
    cid = _identifier("ETH-USDT")
    mark = _mark("ETH-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="ETH-USDT", type_="MARKET", qty="1", price="2700")}
    )

    record = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("ETH-USDT", type_="MARKET")],
        contracts=_contracts_document(),
        marks=_marks_document(),
        database_url=test_database_url,
    )

    assert record is not None
    assert client.contracts_calls == 0
    assert client.premium_index_calls == 0
    expected_slippage = float((Decimal(2700) - mark) / mark * Decimal(10_000))
    assert record.realized_cost_bps == pytest.approx(expected_slippage + float(TAKER_BPS))
    assert record.modeled_cost_bps == pytest.approx(float(TAKER_BPS))


def test_the_record_lands_in_the_database_url_store(test_database_url: str) -> None:
    """The recording is feature 340's own store, addressed by ``DATABASE_URL``.

    No URL is handed in, so the store resolves ``DATABASE_URL`` — the one
    the deployment names and the same store the placements and the
    daily-loss halt live in — and the row is read back through that member's
    reader.
    """
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="BTC-USDT", type_="LIMIT", qty="2", price="101")}
    )

    record = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("BTC-USDT", price="100")],
    )

    assert record is not None
    stored = ForwardCostReconciliations(test_database_url).get(
        book_id=BOOK_ID, rebalance_ts=REBALANCE_TS
    )
    assert stored == record


# -- The documents come from the client when not handed in ----------------------


def test_the_contracts_document_is_fetched_through_the_client(
    test_database_url: str,
) -> None:
    """With no document handed in, the fee is read from the venue's own fetch."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="BTC-USDT", type_="LIMIT", qty="1", price="100")}
    )

    record = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("BTC-USDT", price="100")],
        database_url=test_database_url,
    )

    assert record is not None
    assert client.contracts_calls == 1
    # An at-the-limit fill: no slippage, only the fee.
    assert record.realized_cost_bps == pytest.approx(float(MAKER_BPS))
    # An all-passive rebalance needs no mark, so the second document is not fetched.
    assert client.premium_index_calls == 0


# -- Refusals ------------------------------------------------------------------


def test_a_refused_leg_is_skipped() -> None:
    """A gate-refused leg names no venue order: it is not read and not priced."""
    cid = _identifier("BTC-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="BTC-USDT", type_="LIMIT", qty="1", price="101")}
    )
    refused = BingXRefusedLeg(symbol="ETH-USDT", code="not_tradable")

    answer = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("BTC-USDT", price="100"), refused],
    )

    assert answer is not None
    # Only the BTC leg was looked up.
    assert client.queried == [(cid, "BTC-USDT")]


def test_a_limit_leg_with_no_readable_price_is_refused() -> None:
    """A passive leg's fill is measured against its own price; a leg with
    none names no reference, so the ask is refused before the venue is asked."""
    leg = _leg("BTC-USDT")
    del leg["price"]
    client = _FakeClient()

    with pytest.raises(RouterBingXReconcileError) as info:
        reconcile_rebalance_fill_costs(
            client=client,
            book_id=BOOK_ID,
            rebalance_ts=REBALANCE_TS,
            orders=[leg],
        )

    assert str(info.value).startswith(BINGX_RECONCILE_CODE)
    assert client.queried == []


def test_a_leg_naming_no_side_is_refused(test_database_url: str) -> None:
    """A fill's signed slippage needs the side; a side outside the venue's
    vocabulary is a fault of the ask."""
    leg = _leg("BTC-USDT")
    leg["side"] = "SIDEWAYS"

    with pytest.raises(RouterBingXReconcileError) as info:
        reconcile_rebalance_fill_costs(
            client=_FakeClient(),
            book_id=BOOK_ID,
            rebalance_ts=REBALANCE_TS,
            orders=[leg],
            database_url=test_database_url,
        )

    assert str(info.value).startswith(BINGX_RECONCILE_CODE)


def test_a_contract_the_document_does_not_price_is_refused(
    test_database_url: str,
) -> None:
    """A filled symbol the contracts document prices no fee for is refused,
    never charged a defaulted rate."""
    cid = _identifier("UNKNOWN-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="UNKNOWN-USDT", type_="LIMIT", qty="1", price="100")}
    )
    orders = [{"symbol": "UNKNOWN-USDT", "side": "BUY", "type": "LIMIT", "price": "100", "clientOrderID": cid}]

    with pytest.raises(RouterBingXReconcileError) as info:
        reconcile_rebalance_fill_costs(
            client=client,
            book_id=BOOK_ID,
            rebalance_ts=REBALANCE_TS,
            orders=orders,
            database_url=test_database_url,
        )

    assert str(info.value).startswith(BINGX_RECONCILE_CODE)
    assert reconciled_fill_costs(database_url=test_database_url) == ()


def test_a_filled_market_leg_with_no_mark_is_refused(
    test_database_url: str,
) -> None:
    """A MARKET leg's reference is its symbol's mark; a document that prices
    none cannot reconcile the fill it made."""
    cid = _identifier("UNKNOWN-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="UNKNOWN-USDT", type_="MARKET", qty="1", price="100")}
    )
    orders = [{"symbol": "UNKNOWN-USDT", "side": "BUY", "type": "MARKET", "clientOrderID": cid}]

    with pytest.raises(RouterBingXReconcileError) as info:
        reconcile_rebalance_fill_costs(
            client=client,
            book_id=BOOK_ID,
            rebalance_ts=REBALANCE_TS,
            orders=orders,
            database_url=test_database_url,
        )

    assert str(info.value).startswith(BINGX_RECONCILE_CODE)


def test_a_zero_mark_is_refused_by_name(test_database_url: str) -> None:
    """A MARKET fill is a fraction of its symbol's mark; a zero mark is no
    reference, and the refusal is this member's own rather than a bare
    ``ZeroDivisionError`` from the pricing loop."""
    cid = _identifier("ETH-USDT")
    client = _FakeClient(
        queries={cid: _filled_answer(cid, symbol="ETH-USDT", type_="MARKET", qty="1", price="2700")}
    )
    zero_mark = {"data": [{"symbol": "ETH-USDT", "markPrice": "0"}]}

    with pytest.raises(RouterBingXReconcileError) as info:
        reconcile_rebalance_fill_costs(
            client=client,
            book_id=BOOK_ID,
            rebalance_ts=REBALANCE_TS,
            orders=[_leg("ETH-USDT", type_="MARKET")],
            marks=zero_mark,
            database_url=test_database_url,
        )

    assert str(info.value).startswith(BINGX_RECONCILE_CODE)
    assert reconciled_fill_costs(database_url=test_database_url) == ()


def test_a_float_measurement_is_refused_before_it_reaches_the_store(
    test_database_url: str,
) -> None:
    """The venue spells its measurements as strings; a float is a binary
    approximation no venue sent, and the read-back refuses one by name."""
    cid = _identifier("BTC-USDT")
    answer = _filled_answer(cid, symbol="BTC-USDT", type_="LIMIT", qty="1", price="101")
    answer["order"]["avgPrice"] = 101.0  # a float, not the venue's string
    client = _FakeClient(queries={cid: answer})

    with pytest.raises(RouterBingXOrdersError):
        reconcile_rebalance_fill_costs(
            client=client,
            book_id=BOOK_ID,
            rebalance_ts=REBALANCE_TS,
            orders=[_leg("BTC-USDT", price="100")],
            database_url=test_database_url,
        )

    assert reconciled_fill_costs(database_url=test_database_url) == ()
