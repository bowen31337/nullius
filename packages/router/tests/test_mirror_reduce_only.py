"""Tests for the reduce-only legs: :mod:`router.bingx_mirror` and :mod:`router.bingx_order`.

``bug_spec_vst_reduce_only_legs.xml``, bug 1.  After the margin-partial fix
merged, every 04:00, 08:00 and 12:00 UTC slot of the VST shadow book ended
with the same shape (2026-10-25T12:00: *"14.7867 USDT answered against
636.2532 before; 50 increasing legs deferred; exit 1"*).  The mirror sent
its five or six position-reducing legs as plain passive LIMIT orders, and
the venue reserves initial margin for a resting LIMIT order whatever its
direction unless the order carries ``reduceOnly`` — so the legs meant to
release margin locked it, the balance re-read collapsed, and every
increasing leg was deferred.

The fix, clause by clause:

* :class:`router.bingx_order.BingXOrder` gains an optional ``reduce_only``
  flag.  Set, :meth:`~router.bingx_order.BingXOrder.parameters` emits it
  under :data:`router.bingx_flatten.REDUCE_ONLY_FIELD` with the value
  :data:`router.bingx_flatten.BINGX_REDUCE_ONLY_TRUE` — the spellings
  ``bingx_flatten`` already sends on its closes, imported, never restated.
  Unset, the parameters are today's, key for key.
* :func:`router.bingx_mirror.mirror_place` sends every leg that only
  shrinks a held position (increasing size zero, reducing size positive)
  with the flag set, still before any increasing leg.
* A leg that would cross zero cannot be split: the client-order-id law
  admits no suffix (a fixed 64-hex digest of the three terms, projected to
  its first 40 characters), so the crossing leg is sent plain as it always
  was and counted in the report's ``crossing_legs``.
* The recorder writes the flag to the leg's ``router_order_record`` row, a
  nullable column added by the member's probe-then-ALTER, so a
  reconciliation can tell a reduceOnly fill from a plain one.

* The per-leg fidelity row (``router_order_fidelity``) carries the same flag,
  read off the order record it is reconciled from, so a reduceOnly fill and
  a plain one are told apart in the reconciliation's own rows.

The fake client below models the venue's reservation: it answers its
starting balance before any order, takes a plain order's notional (leverage
one) out of the available figure, and gives a reduceOnly order's notional
back.  Every test injects it — no socket, no key, no network — in the style
of :mod:`test_mirror_margin_netting`, whose fixtures this suite reuses.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest
import test_mirror_margin_netting as netting_fixtures
from router.bingx_client_order_id import project_bingx_client_order_id
from router.bingx_flatten import BINGX_REDUCE_ONLY_TRUE, REDUCE_ONLY_FIELD
from router.bingx_mirror import (
    MARGIN_DEFERRED_CODE,
    MIRROR_OUTCOME_PLACED,
    MIRROR_OUTCOME_PRIOR,
    mirror_place,
)
from router.bingx_order import (
    BINGX_BUY,
    BINGX_MARKET_ORDER,
    BINGX_SELL,
    BingXOrder,
    RouterBingXOrderError,
)
from router.bingx_orders import VSTOrderStatus
from router.bingx_reconcile import save_order_fills
from router.client_order_id import derive_client_order_id
from router.errors import RouterClientOrderIdError, RouterSubmissionResultError
from router.fidelity import FIDELITY_LEG_STATES, FidelitySlot, reconcile_fidelity
from router.submission_result import RouterOrderPlacementStore

#: The five symbols the plans trade; the double's contracts and premiumIndex
#: documents price every one, and the book states a decay horizon for each
#: (a repriced leg is judged through its symbol's horizon).
PLAN_SYMBOLS = ("A-USDT", "B-USDT", "C-USDT", "D-USDT", "E-USDT")


def _held() -> tuple[dict, ...]:
    """A long A and a short B of 100 each — the two legs the plan trims."""
    return netting_fixtures.HELD


def _book() -> dict:
    """The netting fixture's book, widened to the five legs."""
    book = netting_fixtures._book()
    book["weights"] = {symbol: 0.01 for symbol in PLAN_SYMBOLS}
    book["decay_horizon_seconds"] = {symbol: 14400 for symbol in PLAN_SYMBOLS}
    return book


class _ReservingClient(netting_fixtures._NettingClient):
    """The netting client, with the venue's margin reservation modelled.

    ``balance()`` answers ``start`` less the notional of every plain order
    the venue has taken plus the notional of every reduceOnly one — at the
    fixture's price of one and the preflight's leverage of one, so a leg's
    quantity is its own margin.  Every figure the mirror reads is kept in
    ``reads``, in order, so a test states what the re-read answered.
    """

    def __init__(self, *, start: str, **kwargs) -> None:
        kwargs.setdefault("symbols", PLAN_SYMBOLS)
        super().__init__(**kwargs)
        self._start = Decimal(start)
        self.reserved = Decimal(0)
        self.released = Decimal(0)
        self.reads: list[Decimal] = []

    def balance(self) -> object:
        available = self._start - self.reserved + self.released
        self.reads.append(available)
        return {"balance": {"asset": "USDT", "availableMargin": str(available)}}

    def place_order(self, order: BingXOrder) -> object:
        parameters = order.parameters()
        notional = Decimal(parameters["price"]) * Decimal(parameters["quantity"])
        if parameters.get(REDUCE_ONLY_FIELD) == BINGX_REDUCE_ONLY_TRUE:
            self.released += notional
        else:
            self.reserved += notional
        return super().place_order(order)


def _leg(symbol: str, side: str, quantity: str) -> BingXOrder:
    return netting_fixtures._leg(symbol=symbol, side=side, quantity=quantity)


def _place(client, plan, database_url):
    return mirror_place(
        client=client,
        book=_book(),
        plan=plan,
        store=RouterOrderPlacementStore(database_url),
        limiter=netting_fixtures._CountingLimiter(),
        database_url=database_url,
        clock=lambda: netting_fixtures.LOCAL_MILLIS,
        sleep=lambda _d: None,
    )


def _records(database_url) -> dict:
    book = _book()
    store = RouterOrderPlacementStore(database_url)
    return {
        record.symbol: record
        for record in store.records_for(book["book_id"], book["rebalance_ts"])
    }


def _sent(client) -> dict[str, BingXOrder]:
    return {order.symbol: order for order in client.placed}


def _identity(symbol: str) -> str:
    """The venue id the identity law gives ``symbol``'s leg in this slot."""
    book = _book()
    return project_bingx_client_order_id(
        derive_client_order_id(
            book_id=book["book_id"],
            rebalance_ts=datetime.fromisoformat(book["rebalance_ts"]),
            symbol=symbol,
        )
    )


def _flag(order: BingXOrder) -> str | None:
    """The reduceOnly parameter an order carries on the wire, if any."""
    return order.parameters().get(REDUCE_ONLY_FIELD)


# -- (a) the order's own parameters ----------------------------------------------


def test_a_reduce_only_legs_parameters_carry_the_flatten_constants():
    plain = _leg("A-USDT", BINGX_SELL, "50")

    reducing = dataclasses.replace(plain, reduce_only=True)

    assert reducing.parameters()[REDUCE_ONLY_FIELD] == BINGX_REDUCE_ONLY_TRUE
    # Nothing else moves: the flag is one key beside the plain parameters.
    assert reducing.parameters() == {
        **plain.parameters(),
        REDUCE_ONLY_FIELD: BINGX_REDUCE_ONLY_TRUE,
    }
    # The identity stays the last key, as it is on every order.
    assert list(reducing.parameters())[-1] == "clientOrderID"


def test_a_plain_legs_parameters_equal_the_pre_fix_dict_byte_for_byte():
    plain = _leg("A-USDT", BINGX_SELL, "50")

    assert plain.reduce_only is False
    assert plain.parameters() == {
        "symbol": "A-USDT",
        "side": "SELL",
        "positionSide": "BOTH",
        "type": "LIMIT",
        "quantity": "50",
        "price": "1",
        "timeInForce": "PostOnly",
        "clientOrderID": "netting-a-usdt",
    }
    assert json.dumps(plain.parameters()) == (
        '{"symbol": "A-USDT", "side": "SELL", "positionSide": "BOTH", '
        '"type": "LIMIT", "quantity": "50", "price": "1", '
        '"timeInForce": "PostOnly", "clientOrderID": "netting-a-usdt"}'
    )


def test_a_market_leg_carries_the_flag_too_and_a_plain_one_does_not():
    market = netting_fixtures._leg(
        symbol="A-USDT",
        side=BINGX_SELL,
        quantity="50",
        order_type=BINGX_MARKET_ORDER,
    )

    assert REDUCE_ONLY_FIELD not in market.parameters()
    reducing = dataclasses.replace(market, reduce_only=True)
    assert reducing.parameters()[REDUCE_ONLY_FIELD] == BINGX_REDUCE_ONLY_TRUE
    assert "price" not in reducing.parameters()


@pytest.mark.parametrize("bogus", ["true", "false", 1, 0, "yes"])
def test_the_flag_is_a_boolean_never_a_spelling(bogus):
    """A string ``"false"`` is truthy; the order refuses anything but a bool."""
    with pytest.raises(RouterBingXOrderError):
        dataclasses.replace(_leg("A-USDT", BINGX_SELL, "50"), reduce_only=bogus)


# -- (b) the live scenario: reducing legs must release margin --------------------


def test_reducing_legs_release_margin_instead_of_locking_it(test_database_url):
    """The slot of 2026-10-25T12:00 UTC, at fixture scale.

    100 available; A and B trim by 50 each (100 of notional); C, D and E
    need 100, 60 and 50.  Sent plain, the reducing legs lock the whole 100
    and the re-read answers 0, so all three increasing legs are deferred.
    Sent reduceOnly, the venue gives their 100 back: the re-read answers
    200, C and D (160) are admitted and only E (which would take the total
    to 210) is deferred.
    """
    client = _ReservingClient(start="100", positions=_held())
    plan = [
        _leg("A-USDT", BINGX_SELL, "50"),
        _leg("B-USDT", BINGX_BUY, "50"),
        _leg("C-USDT", BINGX_BUY, "100"),
        _leg("D-USDT", BINGX_BUY, "60"),
        _leg("E-USDT", BINGX_BUY, "50"),
    ]

    outcomes = _place(client, plan, test_database_url)

    # The re-read answered more than before the reducing legs left.
    assert client.reads[0] == Decimal(100)
    assert max(client.reads[1:]) == Decimal(200)
    assert client.reads[-1] > client.reads[0]
    # The increasing legs are admitted as the fake's margin allows.
    deferred = {
        symbol
        for symbol, outcome in outcomes.items()
        if outcome.code == MARGIN_DEFERRED_CODE
    }
    assert deferred == {"E-USDT"}
    assert [order.symbol for order in client.placed] == [
        "A-USDT",
        "B-USDT",
        "C-USDT",
        "D-USDT",
    ]
    # What went out: the reducing legs reduceOnly, the increasing legs not.
    sent = _sent(client)
    assert _flag(sent["A-USDT"]) == BINGX_REDUCE_ONLY_TRUE
    assert _flag(sent["B-USDT"]) == BINGX_REDUCE_ONLY_TRUE
    assert _flag(sent["C-USDT"]) is None
    assert _flag(sent["D-USDT"]) is None
    # The reducing legs keep the plan's own terms and identity.
    for symbol, quantity in (("A-USDT", "50"), ("B-USDT", "50")):
        assert sent[symbol].quantity == quantity
        assert sent[symbol].client_order_id == _identity(symbol)


def test_a_reducing_leg_that_reprices_stays_reduce_only(test_database_url):
    """The venue is asked for the repriced order; the flag must survive it.

    The depth quotes the leg's own side away from the plan's price, so the
    repricer assembles a fresh order at the book — and that order is the
    one the venue receives and the store records.
    """

    class _Moved(_ReservingClient):
        def depth(self, symbol: str) -> object:
            return {"bids": [["0.9", "100000"]], "asks": [["1.1", "100000"]]}

    client = _Moved(start="1000", positions=_held())

    outcomes = _place(
        client, [_leg("A-USDT", BINGX_SELL, "50")], test_database_url
    )

    sent = _sent(client)["A-USDT"]
    assert sent.price == "1.1"  # repriced off the plan's "1"
    assert _flag(sent) == BINGX_REDUCE_ONLY_TRUE
    assert outcomes["A-USDT"].order == sent
    assert _records(test_database_url)["A-USDT"].reduce_only is True


# -- (c) a leg that would cross zero ---------------------------------------------


def test_the_identity_law_admits_no_suffix():
    """Why a crossing leg is not split: one leg, one key, no second name.

    The key is the sha256 of the three terms and the venue's field is its
    first 40 hex characters; a second id for the remainder leg would have to
    be a suffix on that digest, which the law refuses, or a different
    symbol term, which would be a leg the cancel, the read-back and the
    reconciliation (all addressed by one id per symbol) never look for.
    """
    book = _book()
    identity = derive_client_order_id(
        book_id=book["book_id"],
        rebalance_ts=datetime.fromisoformat(book["rebalance_ts"]),
        symbol="A-USDT",
    )
    assert project_bingx_client_order_id(identity) == _identity("A-USDT")
    assert len(_identity("A-USDT")) == 40
    with pytest.raises(RouterClientOrderIdError):
        project_bingx_client_order_id(f"{identity}-reopen")
    with pytest.raises(RouterClientOrderIdError):
        project_bingx_client_order_id(f"{identity}0")


def test_a_leg_that_crosses_zero_is_sent_plain_whole_and_counted(
    test_database_url,
):
    """A holds a long of 30 and the plan sells 50: reduce 30, re-open 20.

    The leg grows a position (the 20 beyond zero), so it keeps the growing
    group's place — after every purely reducing leg — and the plain shape it
    always had: one order, the plan's own quantity and identity, no
    reduceOnly (the venue would refuse or clip a reduceOnly order larger
    than the position, and a clipped leg would leave the re-open unplaced).
    The report names it.
    """
    positions = (
        {"symbol": "A-USDT", "positionSide": "LONG", "positionAmt": "30"},
        {"symbol": "B-USDT", "positionSide": "SHORT", "positionAmt": "100"},
    )
    client = _ReservingClient(start="1000", positions=positions)
    plan = [
        _leg("A-USDT", BINGX_SELL, "50"),  # crosses zero
        _leg("B-USDT", BINGX_BUY, "50"),  # purely reducing
        _leg("C-USDT", BINGX_BUY, "40"),  # increasing from flat
    ]

    outcomes = _place(client, plan, test_database_url)

    assert outcomes.crossing_legs == 1
    assert outcomes.crossing_symbols == ("A-USDT",)
    assert [order.symbol for order in client.placed] == [
        "B-USDT",
        "A-USDT",
        "C-USDT",
    ]
    sent = _sent(client)
    assert _flag(sent["B-USDT"]) == BINGX_REDUCE_ONLY_TRUE
    assert _flag(sent["A-USDT"]) is None
    assert sent["A-USDT"].quantity == "50"
    assert sent["A-USDT"].client_order_id == _identity("A-USDT")
    assert _flag(sent["C-USDT"]) is None
    assert all(o.outcome == MIRROR_OUTCOME_PLACED for o in outcomes.values())
    flags = {s: r.reduce_only for s, r in _records(test_database_url).items()}
    assert flags == {"A-USDT": False, "B-USDT": True, "C-USDT": False}


def test_a_plan_with_no_crossing_leg_counts_none(test_database_url):
    client = _ReservingClient(start="1000", positions=_held())
    plan = [
        _leg("A-USDT", BINGX_SELL, "100"),  # exactly flat: reduces, never crosses
        _leg("C-USDT", BINGX_BUY, "40"),
    ]

    outcomes = _place(client, plan, test_database_url)

    assert outcomes.crossing_legs == 0
    assert outcomes.crossing_symbols == ()
    assert _flag(_sent(client)["A-USDT"]) == BINGX_REDUCE_ONLY_TRUE


def test_the_report_is_still_the_symbol_keyed_mapping_its_callers_read(
    test_database_url,
):
    client = _ReservingClient(start="1000", positions=_held())

    outcomes = _place(
        client, [_leg("A-USDT", BINGX_SELL, "50")], test_database_url
    )

    assert isinstance(outcomes, dict)
    assert list(outcomes) == ["A-USDT"]
    assert outcomes["A-USDT"].symbol == "A-USDT"


# -- (d) a second run in the slot places nothing; the flag reads back ------------


def test_a_second_run_places_nothing_and_the_recorded_flag_reads_back(
    test_database_url,
):
    plan = [
        _leg("A-USDT", BINGX_SELL, "50"),
        _leg("B-USDT", BINGX_BUY, "50"),
        _leg("C-USDT", BINGX_BUY, "100"),
        _leg("D-USDT", BINGX_BUY, "60"),
    ]
    first = _ReservingClient(start="1000", positions=_held())
    _place(first, plan, test_database_url)
    assert len(first.placed) == 4
    recorded = _records(test_database_url)
    assert {s: r.reduce_only for s, r in recorded.items()} == {
        "A-USDT": True,
        "B-USDT": True,
        "C-USDT": False,
        "D-USDT": False,
    }

    second = _ReservingClient(start="1000", positions=_held())
    outcomes = _place(second, plan, test_database_url)

    assert second.placed == []
    assert all(o.outcome == MIRROR_OUTCOME_PRIOR for o in outcomes.values())
    # The first placement's rows win: nothing was rewritten.
    assert _records(test_database_url) == recorded


# -- the recorder column: probe-then-ALTER ---------------------------------------

#: The ``router_order_record`` table as a ``vst.db`` written before this
#: column existed carries it — the original nine columns, nothing more.
_LEGACY_SCHEMA = """
CREATE TABLE router_order_record (
    client_order_id TEXT NOT NULL PRIMARY KEY,
    book_id         TEXT NOT NULL,
    rebalance_ts    TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    type            TEXT NOT NULL,
    quantity        TEXT NOT NULL,
    reference_price TEXT NOT NULL,
    placed_at       TEXT NOT NULL
);
"""


def test_an_existing_vst_db_gains_the_column_and_keeps_its_rows(tmp_path):
    path = tmp_path / "vst.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(_LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO router_order_record VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "a" * 64,
                "legacy-book",
                "2026-01-01T00:00:00+00:00",
                "BTC-USDT",
                "BUY",
                "LIMIT",
                "0.01",
                "50000",
                "2026-01-01T00:00:01+00:00",
            ),
        )
    store = RouterOrderPlacementStore(f"sqlite:///{path}")

    (legacy,) = store.records_for("legacy-book", "2026-01-01T00:00:00+00:00")
    # A row from before the column reads as unknown, never as plain.
    assert legacy.reduce_only is None

    def record(identifier: str, **extra):
        return store.record_order(
            client_order_id=identifier,
            book_id="legacy-book",
            rebalance_ts="2026-01-02T00:00:00+00:00",
            symbol="ETH-USDT",
            side="SELL",
            order_type="LIMIT",
            quantity="1",
            reference_price="2700",
            **extra,
        )

    assert record("b" * 64, reduce_only=True).reduce_only is True
    assert record("c" * 64, reduce_only=False).reduce_only is False
    assert record("d" * 64).reduce_only is None
    with pytest.raises(RouterSubmissionResultError):
        record("e" * 64, reduce_only="true")
    # A second open of the upgraded file changes nothing.
    assert RouterOrderPlacementStore(f"sqlite:///{path}").records_for(
        "legacy-book", "2026-01-01T00:00:00+00:00"
    ) == (legacy,)


# -- the fidelity rows carry the flag too ----------------------------------------

FIDELITY_BOOK = "fidelity-book"
FIDELITY_SLOT = datetime.fromisoformat("2026-10-04T08:00:00+00:00")


def _record_and_fill(
    store: RouterOrderPlacementStore,
    database_url: str,
    *,
    symbol: str,
    reduce_only: bool | None,
    slot: datetime = FIDELITY_SLOT,
) -> None:
    """Record one MARKET leg's terms with ``reduce_only``, and save its fill."""
    identifier = str(
        derive_client_order_id(
            book_id=FIDELITY_BOOK, rebalance_ts=slot, symbol=symbol
        )
    )
    store.record_order(
        client_order_id=identifier,
        book_id=FIDELITY_BOOK,
        rebalance_ts=slot,
        symbol=symbol,
        side="BUY",
        order_type="MARKET",
        quantity="1",
        reference_price="100",
        decision_mark=Decimal(100),
        expected_cost_bps=5.0,
        reduce_only=reduce_only,
    )
    save_order_fills(
        [
            VSTOrderStatus(
                symbol=symbol,
                client_order_id=project_bingx_client_order_id(identifier),
                status="FILLED",
                executed_quantity=Decimal(1),
                average_price=Decimal(100),
                original_quantity=Decimal(1),
                commission=Decimal(0),
                placed_ms=1_000,
                last_fill_ms=24_000,
            )
        ],
        database_url=database_url,
    )


def test_a_reduce_only_fill_and_a_plain_one_are_told_apart_in_the_fidelity_rows(
    test_database_url,
):
    store = RouterOrderPlacementStore(test_database_url)
    _record_and_fill(store, test_database_url, symbol="A-USDT", reduce_only=True)
    _record_and_fill(store, test_database_url, symbol="B-USDT", reduce_only=False)
    # A record written before the flag was recorded: unknown, not plain.
    _record_and_fill(store, test_database_url, symbol="C-USDT", reduce_only=None)
    slot = FidelitySlot(book_id=FIDELITY_BOOK, rebalance_ts=FIDELITY_SLOT)

    first = reconcile_fidelity(slot, database_url=test_database_url)

    assert first is not None
    assert {o.symbol: o.reduce_only for o in first.orders} == {
        "A-USDT": True,
        "B-USDT": False,
        "C-USDT": None,
    }
    # A second reconciliation of the slot stands on the first rows.
    assert reconcile_fidelity(slot, database_url=test_database_url) == first


def test_an_existing_fidelity_table_gains_the_column_and_keeps_its_rows(
    tmp_path,
):
    """A ``vst.db`` whose fidelity table predates the column upgrades in place."""
    path = tmp_path / "vst.db"
    states = ", ".join(f"'{state}'" for state in FIDELITY_LEG_STATES)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE router_order_fidelity (
                client_order_id    TEXT NOT NULL PRIMARY KEY,
                book_id            TEXT NOT NULL,
                rebalance_ts       TEXT NOT NULL,
                symbol             TEXT NOT NULL,
                side               TEXT NOT NULL,
                type               TEXT NOT NULL,
                leg_state          TEXT NOT NULL CHECK (leg_state IN ({states})),
                decision_mark      TEXT,
                expected_cost_bps  REAL,
                realized_cost_bps  REAL,
                gap_bps            REAL,
                commission_bps     REAL,
                maker              INTEGER,
                place_to_fill_ms   INTEGER,
                unfilled_rest_ms   INTEGER,
                notional           TEXT,
                computed_at        TEXT NOT NULL
            );
            INSERT INTO router_order_fidelity VALUES (
                'old', 'old-book', '2026-01-01T00:00:00+00:00', 'BTC-USDT',
                'BUY', 'MARKET', 'fill', '100', 5.0, 6.0, 1.0, 0.0, 0,
                23000, NULL, '100', '2026-01-01T04:00:00+00:00'
            );
            """
        )
    url = f"sqlite:///{path}"
    store = RouterOrderPlacementStore(url)
    _record_and_fill(store, url, symbol="A-USDT", reduce_only=True)

    result = reconcile_fidelity(
        FidelitySlot(book_id=FIDELITY_BOOK, rebalance_ts=FIDELITY_SLOT),
        database_url=url,
    )

    assert result is not None
    assert [o.reduce_only for o in result.orders] == [True]
    with sqlite3.connect(path) as connection:
        rows = dict(
            connection.execute(
                "SELECT client_order_id, reduce_only FROM router_order_fidelity"
            ).fetchall()
        )
    assert rows["old"] is None
    assert list(rows.values()).count(1) == 1
