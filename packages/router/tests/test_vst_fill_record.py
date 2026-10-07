"""Tests for feature 3 of ``additions_spec_vst_fidelity.xml`` — the
``router_order_fill`` append-only table.

*System saves each order's final venue state to a new append-only
router_order_fill table at reconciliation, so that every order of a
reconciled slot returns its fill ratio, average price, actual commission
and fill latency.*  The sentence has two halves, held below over the pinned
live fixtures and a recording double (never a socket):

* :mod:`router.bingx_orders` also parses ``commission`` (signed), ``time``
  and ``updateTime`` — this suite proves :class:`~router.bingx_orders.
  VSTOrderStatus` reads the pinned ``query_order_filled.json`` and
  ``query_order_pending.json`` into exactly the derived figures the spec
  names: the FILLED fixture's fill ratio is 1.0, its commission in basis
  points and its place-to-fill latency is 23000 ms (``updateTime`` minus
  ``time``, both read verbatim from the fixture); the PENDING fixture's
  fill ratio is 0.0.
* :func:`router.bingx_reconcile.save_order_fills` persists
  :func:`~router.bingx_orders.read_back_orders`'s results once per
  ``client_order_id``: a re-read of the same order — or a different answer
  under the same identifier — changes nothing, and
  :func:`router.bingx_reconcile.reconcile_rebalance_fill_costs` calls it for
  every order of the slot it reconciles, filled or not, even on the path
  that still answers the cost reconciliation itself with ``None``.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from router.bingx_orders import VSTOrderStatus, read_back_orders
from router.bingx_reconcile import (
    BINGX_RECONCILE_CODE,
    RouterBingXReconcileError,
    order_fill_record,
    reconcile_rebalance_fill_costs,
    save_order_fills,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"


class _FakeClient:
    """A recording stand-in for feature 1's client — ``query_order`` only."""

    def __init__(self, *, queries: dict) -> None:
        self._queries = queries
        self.queried: list[tuple[str, str | None]] = []

    def query_order(self, client_order_id: str, *, symbol: str | None = None):
        self.queried.append((client_order_id, symbol))
        return self._queries[client_order_id]


def _live_data(name: str) -> dict:
    """The live recording's ``data`` — feature 1's own shape for an answer.

    Read from ``fixtures/bingx_vst/live/<name>``, never edited: both
    ``query_order_filled.json`` and ``query_order_pending.json`` are pinned
    recordings this spec names by name.
    """
    return json.loads((FIXTURES / "live" / name).read_text(encoding="utf-8"))[
        "data"
    ]


def _status_from_fixture(name: str) -> VSTOrderStatus:
    """Read ``name``'s single recorded order back through the real verb."""
    data = _live_data(name)
    cid = data["order"]["clientOrderId"]
    client = _FakeClient(queries={cid: data})
    (status,) = read_back_orders(client=client, orders=[cid])
    return status


def _filled_status() -> VSTOrderStatus:
    """The pinned FILLED fixture, read back: ETH-USDT, fully filled."""
    return _status_from_fixture("query_order_filled.json")


def _pending_status() -> VSTOrderStatus:
    """The pinned PENDING fixture, read back: 1000PEPE-USDT, resting."""
    return _status_from_fixture("query_order_pending.json")


# -- VSTOrderStatus's new parses: commission, time, updateTime -----------------


def test_the_filled_fixtures_commission_time_and_update_time_are_parsed() -> None:
    """The raw fields the pinned fixture carries, read exactly."""
    status = _filled_status()

    assert status.status == "FILLED"
    assert status.commission == Decimal("-0.004213")
    assert status.placed_ms == 1791360321000
    assert status.last_fill_ms == 1791360344000


def test_the_filled_fixture_yields_a_fill_ratio_of_one() -> None:
    """A fully filled order's executed quantity equals its original one."""
    status = _filled_status()

    assert status.executed_quantity == Decimal("0.008")
    assert status.original_quantity == Decimal("0.008")
    assert status.fill_ratio == 1.0


def test_the_filled_fixtures_commission_bps_is_positive_and_exact() -> None:
    """Commission in bps of filled notional, positive meaning a cost.

    The venue's own sign is negative (a fee the account paid); this reads
    the opposite direction, the same convention every other cost figure in
    this workspace speaks.
    """
    status = _filled_status()

    notional = Decimal("0.008") * Decimal("2632.84")
    expected = float(-Decimal("-0.004213") / notional * Decimal(10_000))
    assert status.commission_bps == pytest.approx(expected)
    assert status.commission_bps > 0


def test_the_filled_fixtures_place_to_fill_ms_is_23000() -> None:
    """``updateTime`` minus ``time``, both read verbatim from the fixture."""
    status = _filled_status()

    assert status.place_to_fill_ms == 23000


def test_the_pending_fixture_yields_a_fill_ratio_of_zero() -> None:
    """A resting order with nothing executed fills zero of its size."""
    status = _pending_status()

    assert status.status == "PENDING"
    assert status.executed_quantity == Decimal(0)
    assert status.original_quantity == Decimal(69850)
    assert status.fill_ratio == 0.0


def test_the_pending_fixtures_commission_bps_is_none() -> None:
    """Nothing filled, so there is no notional to measure a fee against."""
    status = _pending_status()

    assert status.commission == Decimal("0.000000")
    assert status.commission_bps is None


def test_a_partially_filled_order_records_its_fractional_fill_ratio() -> None:
    """A partial fill's executed quantity is a strict fraction of its
    original one — the quantity a slot's step 3 reconciliation must record
    *before* the next slot's step 2 cancels the unfilled remainder, never
    rounded down to zero or up to the full size."""
    base = _live_data("query_order_pending.json")["order"]
    order = dict(base)
    order["clientOrderId"] = "b" * 40
    order["status"] = "PARTIALLY_FILLED"
    order["executedQty"] = "17462.5"  # exactly one quarter of origQty 69850
    order["avgPrice"] = "0.0042697"
    order["commission"] = "-0.0298"
    client = _FakeClient(queries={order["clientOrderId"]: {"order": order}})

    (status,) = read_back_orders(client=client, orders=[order["clientOrderId"]])

    assert status.status == "PARTIALLY_FILLED"
    assert status.original_quantity == Decimal(69850)
    assert status.executed_quantity == Decimal("17462.5")
    assert status.fill_ratio == pytest.approx(0.25)

    notional = Decimal("17462.5") * Decimal("0.0042697")
    expected_bps = float(-Decimal("-0.0298") / notional * Decimal(10_000))
    assert status.commission_bps == pytest.approx(expected_bps)
    assert status.commission_bps > 0


def test_a_partial_fills_executed_quantity_is_saved_not_zero_or_full(
    test_database_url: str,
) -> None:
    """The row ``save_order_fills`` lands carries the partial quantity that
    actually executed — the fact a cancel of the remainder must not erase."""
    base = _live_data("query_order_pending.json")["order"]
    order = dict(base)
    order["clientOrderId"] = "c" * 40
    order["status"] = "PARTIALLY_FILLED"
    order["executedQty"] = "17462.5"
    order["avgPrice"] = "0.0042697"
    client = _FakeClient(queries={order["clientOrderId"]: {"order": order}})
    (status,) = read_back_orders(client=client, orders=[order["clientOrderId"]])

    (saved,) = save_order_fills([status], database_url=test_database_url)

    assert saved.status == "PARTIALLY_FILLED"
    assert saved.executed_quantity == Decimal("17462.5")
    assert saved.fill_ratio == pytest.approx(0.25)


def test_a_not_found_order_carries_none_of_the_new_fields() -> None:
    """The venue holds no record of the order, so there is nothing to parse."""
    (status,) = read_back_orders(
        client=_FakeNotFoundClient(), orders=["a" * 40]
    )

    assert status.commission is None
    assert status.placed_ms is None
    assert status.last_fill_ms is None
    assert status.place_to_fill_ms is None
    assert status.fill_ratio == 0.0
    assert status.commission_bps is None


class _FakeNotFoundClient:
    """A client whose every lookup answers the venue's own not-found refusal."""

    def query_order(self, client_order_id: str, *, symbol: str | None = None):
        from router.bingx_client import ORDER_NOT_FOUND_CODE, RouterBingXRefusedError

        raise RouterBingXRefusedError(ORDER_NOT_FOUND_CODE, "order not exist")


# -- save_order_fills: persisted once per client_order_id -----------------------


def test_the_filled_fixture_is_saved_with_its_derived_figures(
    test_database_url: str,
) -> None:
    """The row ``save_order_fills`` lands carries the same derived figures
    the status itself answers — fill_ratio 1.0, the commission bps, and a
    place_to_fill_ms of 23000."""
    status = _filled_status()

    (saved,) = save_order_fills([status], database_url=test_database_url)

    assert saved.client_order_id == status.client_order_id
    assert saved.status == "FILLED"
    assert saved.original_quantity == Decimal("0.008")
    assert saved.executed_quantity == Decimal("0.008")
    assert saved.fill_ratio == 1.0
    assert saved.avg_price == Decimal("2632.84")
    assert saved.commission == Decimal("-0.004213")
    assert saved.commission_bps == pytest.approx(status.commission_bps)
    assert saved.placed_ms == 1791360321000
    assert saved.last_fill_ms == 1791360344000
    assert saved.place_to_fill_ms == 23000
    assert isinstance(saved.read_at, datetime)


def test_the_pending_fixture_is_saved_with_a_fill_ratio_of_zero(
    test_database_url: str,
) -> None:
    status = _pending_status()

    (saved,) = save_order_fills([status], database_url=test_database_url)

    assert saved.status == "PENDING"
    assert saved.fill_ratio == 0.0
    assert saved.executed_quantity == Decimal(0)


def test_a_saved_row_reads_back_through_order_fill_record(
    test_database_url: str,
) -> None:
    status = _filled_status()
    (saved,) = save_order_fills([status], database_url=test_database_url)

    read_back = order_fill_record(
        status.client_order_id, database_url=test_database_url
    )

    assert read_back == saved


def test_an_unrecorded_order_reads_as_none(test_database_url: str) -> None:
    assert order_fill_record("a" * 40, database_url=test_database_url) is None


def test_a_re_read_of_the_same_status_writes_no_duplicate(
    test_database_url: str,
) -> None:
    """Reconciling the same order twice persists one row, not two."""
    status = _filled_status()

    first, = save_order_fills([status], database_url=test_database_url)
    second, = save_order_fills([status], database_url=test_database_url)

    assert second == first


def test_a_different_answer_under_the_same_id_does_not_overwrite_the_first(
    test_database_url: str,
) -> None:
    """The law is *per client_order_id*, not *per distinct answer*: once a
    row stands, a later call under the same identifier — even one carrying
    a different venue answer, as a stale re-ask after the order moved on
    would — changes nothing.  The first save is the one that stands."""
    status = _filled_status()
    first, = save_order_fills([status], database_url=test_database_url)

    changed = VSTOrderStatus(
        symbol=status.symbol,
        client_order_id=status.client_order_id,
        status="CANCELED",
        executed_quantity=Decimal("0.008"),
        average_price=Decimal("2632.84"),
    )
    second, = save_order_fills([changed], database_url=test_database_url)

    assert second == first
    assert (
        order_fill_record(status.client_order_id, database_url=test_database_url)
        == first
    )


def test_an_empty_list_saves_nothing_and_touches_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No orders to save means no store is even addressed."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert save_order_fills([]) == ()


def test_saving_with_no_database_configured_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    status = _filled_status()

    with pytest.raises(RouterBingXReconcileError) as raised:
        save_order_fills([status])

    assert str(raised.value).startswith(BINGX_RECONCILE_CODE)


def test_a_naive_now_is_refused(test_database_url: str) -> None:
    status = _filled_status()

    with pytest.raises(RouterBingXReconcileError):
        save_order_fills(
            [status],
            database_url=test_database_url,
            now=datetime(2026, 1, 1),  # noqa: DTZ001 - the naive stamp IS the input
        )


def test_order_fill_record_refuses_an_empty_identifier(
    test_database_url: str,
) -> None:
    with pytest.raises(RouterBingXReconcileError):
        order_fill_record("", database_url=test_database_url)


def test_multiple_statuses_each_save_their_own_row(
    test_database_url: str,
) -> None:
    filled = _filled_status()
    pending = _pending_status()

    saved = save_order_fills([filled, pending], database_url=test_database_url)

    assert {row.client_order_id for row in saved} == {
        filled.client_order_id,
        pending.client_order_id,
    }
    assert {row.fill_ratio for row in saved} == {1.0, 0.0}


# -- Wired into reconciliation: every order of the slot, filled or not ---------


def test_reconcile_saves_a_pending_leg_even_though_it_answers_none(
    test_database_url: str,
) -> None:
    """A slot with nothing filled still has its order's venue state saved —
    *"every order of a reconciled slot"* — even though the cost
    reconciliation this function otherwise performs still records nothing
    and answers ``None`` for a rebalance with no filled order."""
    from test_bingx_reconcile import (  # isort: skip
        BOOK_ID,
        REBALANCE_TS,
        _FakeClient as _ReconcileFakeClient,
        _identifier,
        _leg,
        _recorded_answer,
    )

    cid = _identifier("1000PEPE-USDT")
    order_document = dict(_recorded_answer()["order"])
    order_document["clientOrderId"] = cid
    client = _ReconcileFakeClient(queries={cid: {"order": order_document}})

    answer = reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=[_leg("1000PEPE-USDT")],
        database_url=test_database_url,
    )

    assert answer is None  # the existing sentence still holds
    saved = order_fill_record(cid, database_url=test_database_url)
    assert saved is not None
    assert saved.status == "PENDING"
    assert saved.fill_ratio == 0.0


def test_reconciling_the_same_slot_twice_saves_the_fill_once(
    test_database_url: str,
) -> None:
    from test_bingx_reconcile import (  # isort: skip
        BOOK_ID,
        REBALANCE_TS,
        _FakeClient as _ReconcileFakeClient,
        _filled_answer,
        _identifier,
        _leg,
    )

    cid = _identifier("BTC-USDT")
    client = _ReconcileFakeClient(
        queries={
            cid: _filled_answer(
                cid, symbol="BTC-USDT", type_="LIMIT", qty="2", price="101"
            )
        }
    )
    orders = [_leg("BTC-USDT", price="100")]

    reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=orders,
        database_url=test_database_url,
    )
    first = order_fill_record(cid, database_url=test_database_url)

    reconcile_rebalance_fill_costs(
        client=client,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        orders=orders,
        database_url=test_database_url,
    )
    second = order_fill_record(cid, database_url=test_database_url)

    assert second == first
    assert first.status == "FILLED"
    assert first.executed_quantity == Decimal(2)
