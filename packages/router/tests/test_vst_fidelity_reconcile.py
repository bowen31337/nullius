"""Tests for feature 5 of ``additions_spec_vst_fidelity.xml`` —
:mod:`router.fidelity` and its wiring into :mod:`router.bingx_rebalance`'s
step 3.

*System compares every filled order's realized cost against the cost
model's pre-trade estimate and saves the per-order and per-slot fidelity,
so that each reconciled slot returns real sim-versus-live gaps rather than
fee-only figures.*  Held clause by clause, directly over the three stores
this module reads (``router_order_record``, ``router_order_fill``,
``router_funding_income``) rather than through the full mirror/placement
machinery — :func:`reconcile_fidelity` takes no client and builds no plan,
so seeding its inputs through their own public write APIs is a faithful
exercise of exactly what it reads:

* a ``MARKET`` fill slipping 5 bps against the mark, with a 4 bps expected
  cost, gives a gap of 1 bp plus the fee;
* a ``PostOnly`` fill repriced away from the mark shows the passive cost
  the old (:mod:`router.bingx_reconcile`) reconciliation hides, because
  that module prices a fill against its own limit — always zero for a
  maker fill — while this one prices it against the mark the plan was
  built from;
* funding is attributed to the slot's traded notional, narrowed to the
  slot's own window and its own traded symbols;
* a leg that filled nothing by the time it was read back — including one
  this module never got a fill row for at all — increments the slot's
  reject count and its rate;
* the whole reconciliation is idempotent per slot.

The tail of the suite drives :func:`router.bingx_rebalance.main` for two
consecutive slots — the same doubles :mod:`test_bingx_rebalance` proves the
command against — to prove the wiring the spec's second half names: step 3
calls :func:`~router.fidelity.reconcile_fidelity` after the existing
reconciliation (which it leaves alone), writes ``fill_cost_bps`` and
``reject_rate`` to the ops member's live metrics, and records a rejected
leg to this member's own submission-health log.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from router.bingx_client_order_id import project_bingx_client_order_id
from router.bingx_funding import FundingIncome, RouterFundingIncomeStore
from router.bingx_order import BINGX_LIMIT_ORDER, BINGX_MARKET_ORDER
from router.bingx_orders import VSTOrderStatus
from router.bingx_rebalance import EXIT_OK
from router.bingx_reconcile import save_order_fills
from router.client_order_id import derive_client_order_id
from router.fidelity import (
    FIDELITY_LEG_FILLED,
    FIDELITY_LEG_PARTIAL,
    FIDELITY_LEG_REJECTED,
    FidelitySlot,
    RouterFidelityError,
    reconcile_fidelity,
)
from router.submission_health import (
    ORDER_SUBMISSION_REJECTED,
    RouterSubmissionHealthStore,
)
from router.submission_result import RouterOrderPlacementStore

from test_bingx_mirror import _book, _CountingLimiter  # isort: skip
from test_bingx_rebalance import (  # isort: skip
    SLOT_MORNING,
    _client,
    _filled_answers,
    _run,
)

BOOK_ID = "fidelity-book"
REBALANCE_TS = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)


def _record(
    store: RouterOrderPlacementStore,
    *,
    symbol: str,
    side: str = "BUY",
    order_type: str = BINGX_MARKET_ORDER,
    quantity: str = "1",
    reference_price: str = "100",
    decision_mark: Decimal | None = None,
    expected_cost_bps: float | None = None,
    book_id: str = BOOK_ID,
    rebalance_ts: datetime = REBALANCE_TS,
) -> str:
    """Record one leg's placement terms; return its 40-char projected key."""
    cid = str(
        derive_client_order_id(
            book_id=book_id, rebalance_ts=rebalance_ts, symbol=symbol
        )
    )
    store.record_order(
        client_order_id=cid,
        book_id=book_id,
        rebalance_ts=rebalance_ts,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        reference_price=reference_price,
        decision_mark=decision_mark,
        expected_cost_bps=expected_cost_bps,
    )
    return project_bingx_client_order_id(cid)


def _fill(
    projected_id: str,
    *,
    symbol: str,
    database_url: str,
    status: str = "FILLED",
    executed_quantity: Decimal = Decimal(1),
    average_price: Decimal = Decimal(100),
    original_quantity: Decimal = Decimal(1),
    commission: Decimal = Decimal(0),
    placed_ms: int = 1_000,
    last_fill_ms: int = 24_000,
) -> None:
    """Save one leg's final venue state through feature 3's own writer."""
    save_order_fills(
        [
            VSTOrderStatus(
                symbol=symbol,
                client_order_id=projected_id,
                status=status,
                executed_quantity=executed_quantity,
                average_price=average_price,
                original_quantity=original_quantity,
                commission=commission,
                placed_ms=placed_ms,
                last_fill_ms=last_fill_ms,
            )
        ],
        database_url=database_url,
    )


# -- A MARKET fill slipping 5 bps, 4 bps expected: gap 1 bp plus fees --------


def test_market_fill_slipping_five_bps_with_four_bps_expected_gives_gap_one_bp_plus_fees(
    test_database_url: str,
) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    decision_mark = Decimal(100)
    avg_price = Decimal("100.05")
    executed = Decimal(10)
    commission = Decimal("-0.030015")

    projected = _record(
        store,
        symbol="BTC-USDT",
        side="BUY",
        order_type=BINGX_MARKET_ORDER,
        quantity="10",
        reference_price="100.05",
        decision_mark=decision_mark,
        expected_cost_bps=4.0,
    )
    _fill(
        projected,
        symbol="BTC-USDT",
        executed_quantity=executed,
        average_price=avg_price,
        original_quantity=executed,
        commission=commission,
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    assert len(result.orders) == 1
    order = result.orders[0]
    notional = executed * avg_price
    commission_bps = float(-commission / notional * Decimal(10_000))
    slippage_bps = 5.0  # (100.05 - 100) / 100 * 10000, a BUY so adverse-positive

    assert order.leg_state == FIDELITY_LEG_FILLED
    assert order.realized_cost_bps == pytest.approx(slippage_bps + commission_bps)
    assert order.expected_cost_bps == pytest.approx(4.0)
    assert order.gap_bps == pytest.approx(1.0 + commission_bps)
    assert order.maker is False  # a MARKET leg with a positive fee rate
    assert order.place_to_fill_ms == 23_000
    assert result.gap_bps == pytest.approx(1.0 + commission_bps)
    assert (result.n_fills, result.n_partials, result.n_rejects) == (1, 0, 0)


# -- A PostOnly fill repriced away from the mark: the hidden passive cost ----


def test_postonly_fill_repriced_away_from_mark_shows_the_hidden_passive_cost(
    test_database_url: str,
) -> None:
    """The old reconciliation measures a maker fill against its own limit —

    always zero, because a PostOnly leg fills *at* its limit.  This module
    measures it against ``decision_mark`` instead — the mark the plan was
    built from, before the leg was ever repriced — so the drift between the
    decision and the repriced send is a real, nonzero, signed cost.
    """
    store = RouterOrderPlacementStore(test_database_url)
    decision_mark = Decimal(100)
    repriced_limit = Decimal("100.5")  # the market moved up after the decision
    commission = Decimal("-0.0201")  # exactly 2.0 bps of this fill's notional

    projected = _record(
        store,
        symbol="ETH-USDT",
        side="BUY",
        order_type=BINGX_LIMIT_ORDER,
        quantity="1",
        reference_price=str(repriced_limit),
        decision_mark=decision_mark,
        expected_cost_bps=11.5,
    )
    _fill(
        projected,
        symbol="ETH-USDT",
        executed_quantity=Decimal(1),
        average_price=repriced_limit,  # filled exactly at its own repriced limit
        original_quantity=Decimal(1),
        commission=commission,
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    order = result.orders[0]
    # The order's own reference price (its repriced limit) equals its own
    # average fill price: a reconciliation measured against that reference
    # — router.bingx_reconcile's own — would read exactly zero slippage
    # here.  This module's reference is decision_mark, and the 50 bps
    # between the decision and the repriced limit is the cost that
    # comparison hides.
    assert order.realized_cost_bps == pytest.approx(52.0)  # 50 bps slippage + 2 bps fee
    assert order.gap_bps == pytest.approx(52.0 - 11.5)
    assert order.maker is True  # a LIMIT leg always rests as a maker in this bot


# -- Funding is attributed to the slot, over its notional --------------------


def test_funding_is_attributed_to_the_slot_over_its_notional(
    test_database_url: str,
) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    projected = _record(
        store,
        symbol="ETH-USDT",
        order_type=BINGX_MARKET_ORDER,
        quantity="2",
        reference_price="50",
        decision_mark=Decimal(50),
        expected_cost_bps=5.0,
    )
    _fill(
        projected,
        symbol="ETH-USDT",
        executed_quantity=Decimal(2),
        average_price=Decimal(50),
        original_quantity=Decimal(2),
        database_url=test_database_url,
    )  # notional = 2 * 50 = 100

    funding_store = RouterFundingIncomeStore(test_database_url)
    slot_start_ms = int(REBALANCE_TS.timestamp() * 1000)
    funding_store.ingest(
        [
            FundingIncome(
                tran_id="in-window",
                symbol="ETH-USDT",
                income="-1.00",  # a cost: the account paid 1 USDT of funding
                asset="VST",
                time=slot_start_ms + 1_000,
            ),
            FundingIncome(
                tran_id="before-the-slot",
                symbol="ETH-USDT",
                income="-50.00",  # excluded: before the slot started
                asset="VST",
                time=slot_start_ms - 1_000,
            ),
            FundingIncome(
                tran_id="untraded-symbol",
                symbol="SOL-USDT",  # excluded: not a symbol this slot traded
                income="-50.00",
                asset="VST",
                time=slot_start_ms + 1_000,
            ),
        ]
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    # -(-1.00) / 100 * 10000 = 100.0 bps -- a cost, the same sign convention
    # commission_bps already takes of the venue's own negative-is-a-cost fee.
    assert result.funding_bps == pytest.approx(100.0)


def test_an_empty_slot_measures_zero_funding_not_an_absence(
    test_database_url: str,
) -> None:
    """A slot with nothing to fund still measures a real zero: ``None`` is
    reserved for a slot with no notional to express funding over at all."""
    store = RouterOrderPlacementStore(test_database_url)
    projected = _record(
        store,
        symbol="BTC-USDT",
        order_type=BINGX_MARKET_ORDER,
        quantity="1",
        reference_price="100",
        decision_mark=Decimal(100),
        expected_cost_bps=5.0,
    )
    _fill(
        projected,
        symbol="BTC-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal(100),
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    assert result.funding_bps == pytest.approx(0.0)


# -- A rejected leg increments the slot's reject count and rate --------------


def test_a_rejected_leg_increments_the_slots_reject_rate(
    test_database_url: str,
) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    filled = _record(
        store,
        symbol="BTC-USDT",
        order_type=BINGX_MARKET_ORDER,
        quantity="1",
        reference_price="100",
        decision_mark=Decimal(100),
        expected_cost_bps=5.0,
    )
    _fill(
        filled,
        symbol="BTC-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal(100),
        database_url=test_database_url,
    )
    rejected = _record(
        store,
        symbol="ETH-USDT",
        order_type=BINGX_LIMIT_ORDER,
        quantity="1",
        reference_price="2700",
        decision_mark=Decimal(2700),
        expected_cost_bps=11.5,
    )
    _fill(
        rejected,
        symbol="ETH-USDT",
        status="CANCELED",
        executed_quantity=Decimal(0),
        average_price=Decimal(0),
        original_quantity=Decimal(1),
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    assert result.n_legs == 2
    assert (result.n_fills, result.n_rejects) == (1, 1)
    assert result.reject_rate == pytest.approx(0.5)
    rejected_row = next(o for o in result.orders if o.symbol == "ETH-USDT")
    assert rejected_row.leg_state == FIDELITY_LEG_REJECTED
    assert rejected_row.realized_cost_bps is None
    assert rejected_row.gap_bps is None
    assert rejected_row.maker is None
    assert rejected_row.notional is None


def test_a_leg_with_no_saved_fill_row_is_also_treated_as_rejected(
    test_database_url: str,
) -> None:
    """A recorded leg this module never got a fill row for at all — the
    defensive case the production path should not reach, since step 3
    always reconciles fills before fidelity — buckets the same way a
    zero-fill read-back does."""
    store = RouterOrderPlacementStore(test_database_url)
    _record(
        store,
        symbol="BTC-USDT",
        order_type=BINGX_MARKET_ORDER,
        quantity="1",
        reference_price="100",
        decision_mark=Decimal(100),
        expected_cost_bps=5.0,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    assert result.n_rejects == 1
    assert result.orders[0].leg_state == FIDELITY_LEG_REJECTED
    assert result.orders[0].place_to_fill_ms is None


def test_a_partial_fill_is_bucketed_separately_from_a_full_fill(
    test_database_url: str,
) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    projected = _record(
        store,
        symbol="BTC-USDT",
        order_type=BINGX_LIMIT_ORDER,
        quantity="4",
        reference_price="100",
        decision_mark=Decimal(100),
        expected_cost_bps=2.0,
    )
    _fill(
        projected,
        symbol="BTC-USDT",
        status="PARTIALLY_FILLED",
        executed_quantity=Decimal(1),
        average_price=Decimal(100),
        original_quantity=Decimal(4),
        commission=Decimal("-0.001"),
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    assert (result.n_fills, result.n_partials, result.n_rejects) == (0, 1, 0)
    assert result.orders[0].leg_state == FIDELITY_LEG_PARTIAL


# -- A leg missing decision-time facts is not priced, but still counted -----


def test_a_leg_missing_decision_time_facts_is_counted_but_not_priced(
    test_database_url: str,
) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    projected = _record(
        store,
        symbol="BTC-USDT",
        order_type=BINGX_MARKET_ORDER,
        quantity="1",
        reference_price="100",
        decision_mark=None,
        expected_cost_bps=None,
    )
    _fill(
        projected,
        symbol="BTC-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal(100),
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    assert result.n_fills == 1
    order = result.orders[0]
    assert order.realized_cost_bps is None
    assert order.gap_bps is None
    assert order.notional == Decimal(100)
    # Unmeasured, not zero: no leg priced this slot at all.
    assert result.realized_cost_bps is None
    assert result.gap_bps is None
    # The slot still traded a nonzero notional, so funding is still measured.
    assert result.funding_bps == pytest.approx(0.0)


# -- A rebalance with no recorded legs reconciles nothing --------------------


def test_a_slot_with_no_recorded_legs_reconciles_nothing(
    test_database_url: str,
) -> None:
    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )
    assert result is None


# -- The step is idempotent --------------------------------------------------


def test_reconciling_the_same_slot_twice_returns_the_standing_row(
    test_database_url: str,
) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    projected = _record(
        store,
        symbol="BTC-USDT",
        order_type=BINGX_MARKET_ORDER,
        quantity="1",
        reference_price="100",
        decision_mark=Decimal(100),
        expected_cost_bps=5.0,
    )
    _fill(
        projected,
        symbol="BTC-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal(100),
        database_url=test_database_url,
    )

    first = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )
    second = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert first is not None and second is not None
    assert first == second
    assert first.computed_at == second.computed_at


# -- Validation ---------------------------------------------------------------


def test_a_blank_database_url_is_refused(test_database_url: str) -> None:
    with pytest.raises(RouterFidelityError):
        reconcile_fidelity(
            FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
            database_url="   ",
        )


def test_a_non_fidelityslot_is_refused(test_database_url: str) -> None:
    with pytest.raises(RouterFidelityError):
        reconcile_fidelity(
            (BOOK_ID, REBALANCE_TS),  # type: ignore[arg-type]
            database_url=test_database_url,
        )


def test_a_naive_rebalance_ts_is_refused() -> None:
    with pytest.raises(RouterFidelityError):
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=datetime(2026, 1, 1))  # noqa: DTZ001


def test_a_blank_book_id_is_refused() -> None:
    with pytest.raises(RouterFidelityError):
        FidelitySlot(book_id="   ", rebalance_ts=REBALANCE_TS)


# -- Wired into bingx_rebalance's step 3 --------------------------------------


def _two_symbol_book(tmp_path: Path) -> Path:
    """The synthetic book, narrowed to two always-tradable legs.

    Both ``BTC-USDT`` and ``ETH-USDT`` resolve to real placed orders in the
    full fixture (neither is a gate-skipped shallow symbol), so the only
    way either is missing from a slot's recorded terms is the scenario this
    suite stages on purpose.
    """
    book = _book()
    weights = {
        "BTC-USDT": book["weights"]["BTC-USDT"],
        "ETH-USDT": book["weights"]["ETH-USDT"],
    }
    book["weights"] = weights
    book["decay_horizon_seconds"] = {
        symbol: book["decay_horizon_seconds"][symbol] for symbol in weights
    }
    path = Path(tmp_path) / "book.json"
    path.write_text(json.dumps(book), encoding="utf-8")
    return path


def test_bingx_rebalance_writes_live_metrics_and_submission_health_for_a_rejected_leg(
    tmp_path, test_database_url: str
) -> None:
    """The spec's second half: step 3's own wiring of feature 5's answer.

    The morning slot places two legs; the afternoon slot reconciles it with
    one leg filled and the other read back as a zero-fill ``CANCELED``
    order — the ordinary fate of a PostOnly leg the price never reached
    before the next slot's own sweep cancelled it.  Step 3 must then write
    the slot's gap and reject rate to the ops member's live metrics and
    record the rejected leg to this member's own submission-health log —
    without changing the existing reconciliation's own answer or the
    slot's exit code.
    """
    from ops.live_metrics import LiveMetricsStore

    book_path = _two_symbol_book(tmp_path)
    store = RouterOrderPlacementStore(test_database_url)
    limiter = _CountingLimiter()

    morning = _client()
    code, _lines = _run(
        book_path,
        client=morning,
        url=test_database_url,
        store=store,
        limiter=limiter,
        now=datetime(2026, 10, 4, 8, 7, tzinfo=UTC),
    )
    assert code == EXIT_OK
    assert len(morning.placed) == 2

    answers = _filled_answers(store, book_id="synthetic-vst-0", slot=SLOT_MORNING)
    eth_record = next(
        record
        for record in store.records_for("synthetic-vst-0", SLOT_MORNING)
        if record.symbol == "ETH-USDT"
    )
    eth_key = project_bingx_client_order_id(eth_record.client_order_id)
    answers[eth_key] = {
        "order": {
            "symbol": "ETH-USDT",
            "clientOrderId": eth_key,
            "type": "LIMIT",
            "status": "CANCELED",
            "origQty": str(eth_record.quantity),
            "executedQty": "0",
            "avgPrice": "0",
            "commission": "0.000000",
            "time": 1_791_076_418_000,
            "updateTime": 1_791_076_420_000,
        }
    }

    afternoon = _client()
    afternoon._query_answers = answers
    code, lines = _run(
        book_path,
        client=afternoon,
        url=test_database_url,
        store=store,
        limiter=limiter,
    )

    assert code == EXIT_OK
    assert lines[0]["reconciled"] is True  # the existing reconciliation, unchanged

    metrics = LiveMetricsStore(test_database_url)
    latest = metrics.latest()
    assert latest["reject_rate"] == pytest.approx(0.5)
    assert latest["fill_cost_bps"] is not None

    health = RouterSubmissionHealthStore(test_database_url)
    observed = health.observations(
        since=datetime(2020, 1, 1, tzinfo=UTC),
        until=datetime(2035, 1, 1, tzinfo=UTC),
    )
    rejected = [o for o in observed if o.outcome == ORDER_SUBMISSION_REJECTED]
    assert len(rejected) == 1
    assert rejected[0].symbol == "ETH-USDT"
    assert rejected[0].client_order_id == eth_key
