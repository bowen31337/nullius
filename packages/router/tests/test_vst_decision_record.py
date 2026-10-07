"""Tests for feature 2 of ``additions_spec_vst_fidelity.xml`` — the
decision-time facts and pre-trade cost estimate ``router_order_record``
carries beside feature 317's original terms.

*System saves each placed order's decision-time facts and its pre-trade
expected cost to router_order_record, so that every order row returns what
the simulator predicted before the venue answered.*  Held clause by clause,
over the pinned plan fixtures the mirror's own suite already builds its
plan from (``test_bingx_mirror``'s synthetic book, its live depth capture
for ETH-USDT, its recorded premiumIndex and contracts documents) — never a
hand-written plan, so a row this suite checks is a row the real placement
path actually produced:

* every placed leg's row carries the nine new fields, populated wherever
  the fact behind it was actually read;
* a MARKET leg's ``best_bid``/``best_ask`` are null — it is never repriced,
  so it never reads a book's own side the way a LIMIT leg's repricing does;
* a cost model the shared library refuses (an unreadable document) gives a
  null ``expected_cost_bps`` and a null ``cost_model_version`` for every
  leg, never a placement that stops;
* a MARKET leg whose recorded depth cannot fill its own size is the same
  refusal from the other side — ``book_walk`` over a thin book, never a
  zero;
* an existing ``vst.db`` written before this feature existed — the original
  nine ``router_order_record`` columns and nothing past them — upgrades in
  place, keeping the row it already held;
* the orders the venue actually receives are untouched: a store that
  records every decision-time fact and a store that records none of them
  send the identical bytes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest
from cost_model import COST_MODEL_PATH_ENV
from router.bingx_mirror import (
    MIRROR_OUTCOME_PLACED,
    build_mirror_plan,
)
from router.bingx_order import BINGX_LIMIT_ORDER, BINGX_MARKET_ORDER, BingXOrder
from router.submission_result import RouterOrderPlacementStore

from test_bingx_mirror import (  # isort: skip
    _book_with_eth_buy,
    _CountingLimiter,
    _live_depth_data,
    _MirrorClient,
    _place,
    _plan,
    _records,
)

#: The shipped default cost model's own fee and penalty rates
#: (``packages/cost-model/src/cost_model/cost_model.yaml``): maker and
#: taker both 10 bps, a 1.5 bps queue-position penalty.  A LIMIT leg's
#: pre-trade estimate assumes the fill (there is no tape to gate a
#: pre-trade estimate on; see ``_limit_expected_cost_bps``), so it is
#: exactly ``queue_position_penalty_bps + maker_bps`` for *any* leg,
#: independent of its own size or price.
_SHIPPED_VERSION = "2026.09.1"
_SHIPPED_LIMIT_EXPECTED_COST_BPS = 1.5 + 10.0


# -- Every placed leg's row carries the new fields -----------------------------


def test_every_placed_legs_row_carries_the_decision_time_facts(
    test_database_url,
):
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert all(o.outcome == MIRROR_OUTCOME_PLACED for o in outcomes.values())

    records = {record.symbol: record for record in _records(store)}
    assert set(records) == {
        "1000PEPE-USDT", "BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT",
    }

    for record in records.values():
        # Every leg's cost model identity and its two instants are read
        # regardless of its type.
        assert record.cost_model_version == _SHIPPED_VERSION
        assert isinstance(record.sent_at, datetime)
        assert isinstance(record.acked_at, datetime)
        assert record.sent_at.tzinfo is not None
        assert record.acked_at.tzinfo is not None
        assert record.acked_at >= record.sent_at
        # decision_mark and target_quantity are leg-shape independent: the
        # venue's premiumIndex prices every symbol this plan ordered.
        assert record.decision_mark is not None
        assert record.decision_mark > 0
        assert record.target_quantity is not None
        assert record.target_quantity > 0

    for symbol, record in records.items():
        if record.type == BINGX_LIMIT_ORDER:
            assert record.pre_reprice_limit is not None
            assert record.best_bid is not None
            assert record.best_ask is not None
            # Every LIMIT leg's pre-trade estimate is the assumed-fill
            # queue penalty plus the maker fee, exactly — see the module
            # docstring for why this is a constant rather than a per-leg
            # figure.
            assert record.expected_cost_bps == pytest.approx(
                _SHIPPED_LIMIT_EXPECTED_COST_BPS
            )
        else:
            assert record.type == BINGX_MARKET_ORDER
            assert symbol == "DOGE-USDT"


# -- A MARKET leg's best_bid/best_ask are null ---------------------------------


def test_a_market_legs_best_bid_and_best_ask_are_null(test_database_url):
    """DOGE is the plan's one MARKET leg; it is never repriced and never
    reads a book's own side the way a LIMIT leg's repricing does."""
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)

    doge = {record.symbol: record for record in _records(store)}["DOGE-USDT"]
    assert doge.type == BINGX_MARKET_ORDER
    assert doge.best_bid is None
    assert doge.best_ask is None
    assert doge.pre_reprice_limit is None


def test_a_market_leg_whose_recorded_depth_cannot_fill_it_gives_a_null_cost(
    test_database_url,
):
    """A fact the cost model refuses is null, never zero.

    The double answers every unstaged symbol's ``depth()`` with a one-level
    book of quantity ``1`` around its own mark (``test_bingx_mirror``'s own
    convention); DOGE's sized leg is thousands of contracts, so
    ``book_walk`` refuses it as a size beyond the recorded depth — exactly
    the cost model's own refusal, from the MARKET side of the estimate.
    """
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    _place(client, _plan(client), store, limiter, database_url=test_database_url)

    doge = {record.symbol: record for record in _records(store)}["DOGE-USDT"]
    assert Decimal(doge.quantity) > 1
    assert doge.expected_cost_bps is None
    # The refusal is scoped to the one fact the cost model could not price:
    # every other decision-time fact this leg carries still landed.
    assert doge.decision_mark is not None
    assert doge.cost_model_version == _SHIPPED_VERSION


# -- A cost model refusal gives a null expected_cost_bps (and version) --------


def test_an_unreadable_cost_model_document_leaves_every_leg_null_but_still_places(
    tmp_path, test_database_url, monkeypatch: pytest.MonkeyPatch,
):
    """A deployment pointed at a document this run cannot read still places
    every order exactly as it would without one — the decision record is a
    diagnostic layer, never a gate."""
    monkeypatch.setenv(COST_MODEL_PATH_ENV, str(tmp_path / "does-not-exist.yaml"))
    client = _MirrorClient()
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    outcomes = _place(
        client, _plan(client), store, limiter, database_url=test_database_url
    )
    assert all(o.outcome == MIRROR_OUTCOME_PLACED for o in outcomes.values())

    records = _records(store)
    assert len(records) == 5
    for record in records:
        assert record.expected_cost_bps is None
        assert record.cost_model_version is None
        # The refusal is scoped to the cost model's own two facts: every
        # other decision-time fact is unaffected by a document this run
        # never needed to read either of them from.
        assert record.decision_mark is not None
        assert record.sent_at is not None
        assert record.acked_at is not None


# -- pre_reprice_limit and best_bid/best_ask are the repricing's own read ------


def test_pre_reprice_limit_and_best_quotes_are_the_books_own_values(
    test_database_url,
):
    """ETH is repriced from the mark (2685.87) to the live book's best bid
    (2665.89); the record keeps both the price the plan proposed *before*
    that reprice and the book's own two sides it was repriced against."""
    book = _book_with_eth_buy()
    client = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    limiter = _CountingLimiter()
    store = RouterOrderPlacementStore(test_database_url)
    plan = build_mirror_plan(book=book, client=client)
    planned_eth = next(
        leg for leg in plan if isinstance(leg, BingXOrder) and leg.symbol == "ETH-USDT"
    )
    _place(client, plan, store, limiter, book=book, database_url=test_database_url)

    eth = {record.symbol: record for record in _records(store, book)}["ETH-USDT"]
    assert eth.reference_price == Decimal("2665.89")  # the sent, repriced limit
    assert eth.pre_reprice_limit == Decimal(planned_eth.price)
    assert eth.pre_reprice_limit != eth.reference_price
    assert eth.best_bid == Decimal("2665.89")
    assert eth.best_ask == Decimal("2673.27")


# -- An existing vst.db without the columns upgrades in place -----------------

#: feature 317's original nine columns, verbatim -- the shape a ``vst.db``
#: written before this feature existed carries, and nothing more.
_LEGACY_ORDER_RECORD_SCHEMA = """
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

_LEGACY_ROW = (
    "a" * 64,
    "legacy-book",
    "2026-01-01T00:00:00+00:00",
    "BTC-USDT",
    "BUY",
    "LIMIT",
    "0.01",
    "50000",
    "2026-01-01T00:00:01+00:00",
)


def test_an_existing_vst_db_without_the_new_columns_upgrades_in_place(
    tmp_path,
):
    """A ``vst.db`` from before this feature carries only the original nine
    columns; opening it through the store adds the rest without touching
    the row already held, and a fresh write lands every new fact beside it.
    """
    path = tmp_path / "vst.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(_LEGACY_ORDER_RECORD_SCHEMA)
        connection.execute(
            "INSERT INTO router_order_record VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _LEGACY_ROW,
        )

    url = f"sqlite:///{path}"
    store = RouterOrderPlacementStore(url)

    # The legacy row survived the upgrade, and its new columns read as the
    # honest None a row from before this feature existed must carry.
    (legacy,) = store.records_for("legacy-book", "2026-01-01T00:00:00+00:00")
    assert legacy.client_order_id == "a" * 64
    assert legacy.reference_price == Decimal(50000)
    assert legacy.decision_mark is None
    assert legacy.best_bid is None
    assert legacy.best_ask is None
    assert legacy.pre_reprice_limit is None
    assert legacy.target_quantity is None
    assert legacy.expected_cost_bps is None
    assert legacy.cost_model_version is None
    assert legacy.sent_at is None
    assert legacy.acked_at is None

    # A fresh write, after the upgrade, carries every new fact.
    now = datetime.fromisoformat("2026-01-02T00:00:00+00:00")
    written = store.record_order(
        client_order_id="b" * 64,
        book_id="legacy-book",
        rebalance_ts="2026-01-02T00:00:00+00:00",
        symbol="ETH-USDT",
        side="SELL",
        order_type="LIMIT",
        quantity="1",
        reference_price="2700",
        now=now,
        decision_mark=Decimal(2701),
        best_bid=Decimal(2699),
        best_ask=Decimal("2700.5"),
        pre_reprice_limit=Decimal(2705),
        target_quantity=Decimal("1.2"),
        expected_cost_bps=11.5,
        cost_model_version="2026.09.1",
        sent_at=now,
        acked_at=now,
    )
    assert written.decision_mark == Decimal(2701)
    assert written.expected_cost_bps == pytest.approx(11.5)
    assert written.cost_model_version == "2026.09.1"

    (still_legacy,) = store.records_for("legacy-book", "2026-01-01T00:00:00+00:00")
    assert still_legacy == legacy


# -- Placement bodies are byte-identical to before -----------------------------


class _BarePlacementStore:
    """A store exposing feature 317's one contract and nothing more.

    The stand-in every pre-existing test in this member's own suite
    (``test_bingx_mirror``) uses to prove a store without the terms write
    keeps placing exactly as it did before that recording existed; reused
    here to prove the same of *this* feature's decision-time recording.
    """

    def __init__(self, inner: RouterOrderPlacementStore) -> None:
        self._inner = inner

    def place(self, *args, **kwargs):
        return self._inner.place(*args, **kwargs)


def test_decision_time_recording_never_changes_what_is_sent(test_database_url):
    """Two placements of the one plan — one recording every decision-time
    fact, one recording nothing at all — send the identical order bytes."""
    book = _book_with_eth_buy()
    limiter = _CountingLimiter()

    bare_client = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    bare_store = _BarePlacementStore(RouterOrderPlacementStore(test_database_url))
    _place(
        bare_client, build_mirror_plan(book=book, client=bare_client), bare_store,
        limiter, book=book, database_url=test_database_url,
    )

    full_client = _MirrorClient(depths={"ETH-USDT": _live_depth_data()})
    full_store = RouterOrderPlacementStore(f"{test_database_url}-full")
    _place(
        full_client, build_mirror_plan(book=book, client=full_client), full_store,
        limiter, book=book, database_url=f"{test_database_url}-full",
    )

    bare_sent = {order.symbol: order.parameters() for order in bare_client.placed}
    full_sent = {order.symbol: order.parameters() for order in full_client.placed}
    assert bare_sent == full_sent
    assert set(bare_sent) == {
        "1000PEPE-USDT", "BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT",
    }
