"""Regression tests for bug_spec_vst_fidelity_accounting.xml.

Three defects in the VST fidelity harness, held one at a time:

1. :mod:`router.fidelity` counted every zero-fill leg as ``"reject"`` —
   including a ``PostOnly`` order the venue *accepted*, which simply never
   reached its price before the next slot's own sweep cancelled it.  That
   folded an ordinary resting leg into the reject rate, and folded its
   resting time into the fill-latency distribution.  The fix adds a fourth
   leg state, :data:`~router.fidelity.FIDELITY_LEG_UNFILLED`, for exactly
   that shape, keeps ``"reject"`` for a genuine venue refusal, and reports
   the resting time on its own as ``unfilled_rest_ms``.
2. :mod:`router.vst_fidelity`'s ``place_to_fill_ms`` distribution mixed fill
   latency with that same resting time, because it read every leg's
   ``place_to_fill_ms`` without regard to whether it ever filled.
3. :mod:`router.bingx_mirror` recorded ``target_quantity`` as the leg's
   whole *position target* (``equity × weight ÷ mark``) rather than the
   order's own pre-rounding *delta* (that target minus the position already
   held), so :func:`router.vst_fidelity._rounding_drift_bps` compared two
   quantities that were never the same thing.

Held directly over the three stores feature 5 and feature 6 already read
and write (``router_order_record``, ``router_order_fill``,
``router_order_fidelity``), the same seeding style
:mod:`test_vst_fidelity_reconcile` and :mod:`test_vst_fidelity_cli` already
use — their own ``_record``/``_fill`` helpers, reused here rather than
re-implemented.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from router.bingx_mirror import _target_quantity_or_none
from router.bingx_order import BINGX_LIMIT_ORDER, BINGX_MARKET_ORDER
from router.client_order_id import derive_client_order_id
from router.fidelity import (
    FIDELITY_LEG_FILLED,
    FIDELITY_LEG_REJECTED,
    FIDELITY_LEG_UNFILLED,
    FidelitySlot,
    reconcile_fidelity,
)
from router.submission_result import RouterOrderPlacementStore
from router.vst_fidelity import build_report

from test_vst_fidelity_reconcile import _fill, _record  # isort: skip

BOOK_ID = "fidelity-accounting-book"
REBALANCE_TS = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)


# -- A cancelled zero-fill leg is unfilled, not reject -----------------------


def test_a_cancelled_zero_fill_leg_is_unfilled_not_rejected(
    test_database_url: str,
) -> None:
    """The SOL-USDT SELL leg the bug report names: a PostOnly LIMIT order
    the venue accepted, which rested unfilled until the next slot's own
    sweep cancelled it — the ordinary fate of a leg the price never
    reached, not a venue refusal."""
    store = RouterOrderPlacementStore(test_database_url)
    cid = _record(
        store,
        symbol="SOL-USDT",
        side="SELL",
        order_type=BINGX_LIMIT_ORDER,
        quantity="0.07",
        reference_price="150",
        decision_mark=Decimal(150),
        expected_cost_bps=11.5,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        cid,
        symbol="SOL-USDT",
        status="CANCELED",
        executed_quantity=Decimal(0),
        average_price=Decimal(0),
        original_quantity=Decimal("8.524"),
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )

    assert result is not None
    assert result.orders[0].leg_state == FIDELITY_LEG_UNFILLED
    assert (result.n_rejects, result.n_unfilled) == (0, 1)
    assert result.reject_rate == pytest.approx(0.0)
    assert result.unfilled_rate == pytest.approx(1.0)


# -- A venue REJECTED leg is reject ------------------------------------------


def test_a_venue_rejected_leg_is_rejected(test_database_url: str) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    cid = _record(
        store,
        symbol="ETH-USDT",
        order_type=BINGX_LIMIT_ORDER,
        quantity="1",
        reference_price="2700",
        decision_mark=Decimal(2700),
        expected_cost_bps=11.5,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        cid,
        symbol="ETH-USDT",
        status="REJECTED",
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
    assert result.orders[0].leg_state == FIDELITY_LEG_REJECTED
    assert (result.n_rejects, result.n_unfilled) == (1, 0)


# -- Latency over fills only, unfilled_rest_ms reported separately ----------


def test_latency_is_measured_over_fills_only_and_unfilled_rest_ms_is_separate(
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
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        filled,
        symbol="BTC-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal(100),
        placed_ms=1_000,
        last_fill_ms=24_000,
        database_url=test_database_url,
    )

    unfilled = _record(
        store,
        symbol="SOL-USDT",
        side="SELL",
        order_type=BINGX_LIMIT_ORDER,
        quantity="0.07",
        reference_price="150",
        decision_mark=Decimal(150),
        expected_cost_bps=11.5,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        unfilled,
        symbol="SOL-USDT",
        status="CANCELED",
        executed_quantity=Decimal(0),
        average_price=Decimal(0),
        original_quantity=Decimal("8.524"),
        placed_ms=1_000,
        last_fill_ms=14_391_000,  # the bug's own worked example: 14,390,000 ms resting
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )
    assert result is not None
    filled_row = next(o for o in result.orders if o.symbol == "BTC-USDT")
    unfilled_row = next(o for o in result.orders if o.symbol == "SOL-USDT")

    assert filled_row.leg_state == FIDELITY_LEG_FILLED
    assert filled_row.place_to_fill_ms == 23_000
    assert filled_row.unfilled_rest_ms is None

    assert unfilled_row.leg_state == FIDELITY_LEG_UNFILLED
    assert unfilled_row.place_to_fill_ms is None
    assert unfilled_row.unfilled_rest_ms == 14_390_000

    report = build_report(test_database_url, book=BOOK_ID)
    # The cancelled leg's 14,390,000 ms never reaches the fill-latency
    # distribution: p50/p95/p99 all read the one filled leg's own 23,000 ms.
    assert report.place_to_fill_ms_p50 == pytest.approx(23_000.0)
    assert report.place_to_fill_ms_p95 == pytest.approx(23_000.0)
    assert report.place_to_fill_ms_p99 == pytest.approx(23_000.0)
    assert report.unfilled_rest_ms_p50 == pytest.approx(14_390_000.0)
    assert report.reject_rate == pytest.approx(0.0)
    assert report.unfilled_rate == pytest.approx(0.5)


# -- The in-place migration of a pre-existing table --------------------------


def test_the_order_fidelity_table_migrates_in_place(test_database_url: str) -> None:
    """A live ``router_order_fidelity`` written before this bugfix — no
    ``unfilled_rest_ms`` column, a ``leg_state`` CHECK with no ``'unfilled'``
    — rebuilds onto the new schema the first time anything in this module
    writes to the store, with its one ``reject`` row (whose own
    ``router_order_fill`` shows an accepted leg that ended ``CANCELED`` with
    zero executed quantity) reclassified ``unfilled``, its resting time
    moved from ``place_to_fill_ms`` to ``unfilled_rest_ms``, and every other
    column preserved.  A second reconciliation changes nothing further.
    """
    db_path = Path(test_database_url.removeprefix("sqlite:///"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_client_order_id = "a" * 40

    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE router_order_fidelity (
                client_order_id    TEXT NOT NULL PRIMARY KEY,
                book_id            TEXT NOT NULL,
                rebalance_ts       TEXT NOT NULL,
                symbol             TEXT NOT NULL,
                side               TEXT NOT NULL,
                type               TEXT NOT NULL,
                leg_state          TEXT NOT NULL CHECK (leg_state IN ('fill', 'partial', 'reject')),
                decision_mark      TEXT,
                expected_cost_bps  REAL,
                realized_cost_bps  REAL,
                gap_bps            REAL,
                commission_bps     REAL,
                maker              INTEGER,
                place_to_fill_ms   INTEGER,
                notional           TEXT,
                computed_at        TEXT NOT NULL
            );
            CREATE TABLE router_order_fill (
                client_order_id   TEXT NOT NULL PRIMARY KEY,
                status            TEXT NOT NULL,
                original_quantity TEXT,
                executed_quantity TEXT,
                fill_ratio        REAL NOT NULL,
                avg_price         TEXT,
                commission        TEXT,
                commission_bps    REAL,
                placed_ms         INTEGER,
                last_fill_ms      INTEGER,
                place_to_fill_ms  INTEGER,
                read_at           TEXT NOT NULL
            );
            """
        )
        with connection:
            connection.execute(
                "INSERT INTO router_order_fidelity (client_order_id, book_id, "
                "rebalance_ts, symbol, side, type, leg_state, decision_mark, "
                "expected_cost_bps, realized_cost_bps, gap_bps, commission_bps, "
                "maker, place_to_fill_ms, notional, computed_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    legacy_client_order_id,
                    "legacy-book",
                    "2026-09-01T08:00:00+00:00",
                    "SOL-USDT",
                    "SELL",
                    BINGX_LIMIT_ORDER,
                    "reject",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    14_390_000,
                    None,
                    "2026-09-01T12:00:00+00:00",
                ),
            )
            connection.execute(
                "INSERT INTO router_order_fill (client_order_id, status, "
                "original_quantity, executed_quantity, fill_ratio, avg_price, "
                "commission, commission_bps, placed_ms, last_fill_ms, "
                "place_to_fill_ms, read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    legacy_client_order_id,
                    "CANCELED",
                    "8.524",
                    "0",
                    0.0,
                    "0",
                    None,
                    None,
                    1_000,
                    14_391_000,
                    14_390_000,
                    "2026-09-01T12:00:00+00:00",
                ),
            )
    finally:
        connection.close()

    def _read_legacy_row() -> tuple:
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT leg_state, place_to_fill_ms, unfilled_rest_ms, symbol, "
                "side, notional FROM router_order_fidelity WHERE "
                "client_order_id = ?",
                (legacy_client_order_id,),
            ).fetchone()
        finally:
            connection.close()

    # Trigger the migration through an ordinary reconciliation of a
    # different slot: _persist_fidelity rebuilds the whole table before it
    # writes anything of its own.
    store = RouterOrderPlacementStore(test_database_url)
    projected = _record(
        store,
        symbol="BTC-USDT",
        order_type=BINGX_MARKET_ORDER,
        quantity="1",
        reference_price="100",
        decision_mark=Decimal(100),
        expected_cost_bps=5.0,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
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
    assert first is not None

    migrated = _read_legacy_row()
    assert migrated is not None
    leg_state, place_to_fill_ms, unfilled_rest_ms, symbol, side, notional = migrated
    assert leg_state == FIDELITY_LEG_UNFILLED
    assert place_to_fill_ms is None
    assert unfilled_rest_ms == 14_390_000
    assert (symbol, side, notional) == ("SOL-USDT", "SELL", None)

    # Idempotent: reconciling the same slot again changes nothing further.
    second = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )
    assert second == first
    assert _read_legacy_row() == migrated


# -- target_quantity is the pre-rounding order delta -------------------------


def test_target_quantity_is_the_pre_rounding_order_delta() -> None:
    """Not the position target on its own: the delta the router sized —
    the raw target minus the position already held, unrounded."""
    book = {
        "equity_usdt": "10000",
        "weights": {"SOL-USDT": "0.5"},
        "positions": {"SOL-USDT": "40"},
    }
    mark = Decimal(100)
    # raw target = 10000 * 0.5 / 100 = 50; held = 40; delta = 10.
    assert _target_quantity_or_none(book, "SOL-USDT", mark) == Decimal(10)


def test_target_quantity_reads_a_flat_symbols_held_position_as_zero() -> None:
    book = {"equity_usdt": "10000", "weights": {"BTC-USDT": "0.2"}, "positions": {}}
    mark = Decimal(100)
    assert _target_quantity_or_none(book, "BTC-USDT", mark) == Decimal(20)


# -- Rounding drift ------------------------------------------------------------


def test_rounding_drift_is_within_the_step_size_for_an_ordinary_leg(
    test_database_url: str,
) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    cid = str(
        derive_client_order_id(
            book_id=BOOK_ID, rebalance_ts=REBALANCE_TS, symbol="BTC-USDT"
        )
    )
    store.record_order(
        client_order_id=cid,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        symbol="BTC-USDT",
        side="BUY",
        order_type=BINGX_MARKET_ORDER,
        quantity="10.03",
        reference_price="100",
        target_quantity="10",
    )

    report = build_report(test_database_url, book=BOOK_ID)

    # (10.03 - 10) * 100 / (10 * 100) * 10000 = 30 bps.
    assert report.rounding_drift_bps == pytest.approx(30.0)


def test_pre_fix_rows_holding_the_position_target_are_excluded_from_drift(
    test_database_url: str,
) -> None:
    """A record from before this bugfix stored target_quantity as the
    leg's whole position target (8.524 SOL) rather than the order's own
    pre-rounding delta (0.07 SOL) — the bug's own worked example. Mixed
    with an ordinary leg's small, plausible drift, only the ordinary leg's
    drift counts."""
    store = RouterOrderPlacementStore(test_database_url)

    ordinary_cid = str(
        derive_client_order_id(
            book_id=BOOK_ID, rebalance_ts=REBALANCE_TS, symbol="BTC-USDT"
        )
    )
    store.record_order(
        client_order_id=ordinary_cid,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        symbol="BTC-USDT",
        side="BUY",
        order_type=BINGX_MARKET_ORDER,
        quantity="10.03",
        reference_price="100",
        target_quantity="10",
    )
    stale_cid = str(
        derive_client_order_id(
            book_id=BOOK_ID, rebalance_ts=REBALANCE_TS, symbol="SOL-USDT"
        )
    )
    store.record_order(
        client_order_id=stale_cid,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        symbol="SOL-USDT",
        side="SELL",
        order_type=BINGX_LIMIT_ORDER,
        quantity="0.07",
        reference_price="150",
        target_quantity="8.524",
    )

    report = build_report(test_database_url, book=BOOK_ID)

    # Exactly the ordinary leg's own 30 bps: the stale row contributes
    # nothing, rather than dragging the figure toward the bug's own
    # roughly -9,877.7 bps.
    assert report.rounding_drift_bps == pytest.approx(30.0)


def test_a_lone_pre_fix_row_measures_no_drift_at_all(test_database_url: str) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    cid = str(
        derive_client_order_id(
            book_id=BOOK_ID, rebalance_ts=REBALANCE_TS, symbol="SOL-USDT"
        )
    )
    store.record_order(
        client_order_id=cid,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
        symbol="SOL-USDT",
        side="SELL",
        order_type=BINGX_LIMIT_ORDER,
        quantity="0.07",
        reference_price="150",
        target_quantity="8.524",
    )

    report = build_report(test_database_url, book=BOOK_ID)

    assert report.rounding_drift_bps is None


# -- The bug report's own reproduce scenario, end to end ---------------------


def test_the_bug_reports_own_reproduce_scenario_end_to_end(
    test_database_url: str,
) -> None:
    """One accepted LIMIT order later ``CANCELED`` with ``executedQty`` 0,
    one other filled order and one ``MARKET`` fill — the bug report's own
    three-leg slot, where the cancelled leg used to inflate ``reject_rate``
    to 0.333 and fold its 14,390,000 ms rest time into fill latency."""
    store = RouterOrderPlacementStore(test_database_url)

    cancelled = _record(
        store,
        symbol="SOL-USDT",
        side="SELL",
        order_type=BINGX_LIMIT_ORDER,
        quantity="0.07",
        reference_price="150",
        decision_mark=Decimal(150),
        expected_cost_bps=11.5,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        cancelled,
        symbol="SOL-USDT",
        status="CANCELED",
        executed_quantity=Decimal(0),
        average_price=Decimal(0),
        original_quantity=Decimal("8.524"),
        placed_ms=1_000,
        last_fill_ms=14_391_000,
        database_url=test_database_url,
    )

    filled_limit = _record(
        store,
        symbol="ETH-USDT",
        side="BUY",
        order_type=BINGX_LIMIT_ORDER,
        quantity="1",
        reference_price="2700",
        decision_mark=Decimal(2700),
        expected_cost_bps=11.5,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        filled_limit,
        symbol="ETH-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal(2700),
        original_quantity=Decimal(1),
        placed_ms=1_000,
        last_fill_ms=5_000,
        database_url=test_database_url,
    )

    filled_market = _record(
        store,
        symbol="BTC-USDT",
        side="BUY",
        order_type=BINGX_MARKET_ORDER,
        quantity="1",
        reference_price="100",
        decision_mark=Decimal(100),
        expected_cost_bps=5.0,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        filled_market,
        symbol="BTC-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal(100),
        original_quantity=Decimal(1),
        placed_ms=1_000,
        last_fill_ms=6_000,
        database_url=test_database_url,
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )
    assert result is not None
    assert result.n_legs == 3
    assert (result.n_fills, result.n_partials, result.n_rejects, result.n_unfilled) == (
        2,
        0,
        0,
        1,
    )
    # Not 0.333: the cancelled leg is no longer a reject at all.
    assert result.reject_rate == pytest.approx(0.0)
    assert result.unfilled_rate == pytest.approx(1 / 3)

    report = build_report(test_database_url, book=BOOK_ID)
    assert report.reject_rate == pytest.approx(0.0)
    assert report.unfilled_rate == pytest.approx(1 / 3)
    # The cancelled leg's 14,390,000 ms rest time never reaches the
    # fill-latency percentiles: both filled legs took 4,000-5,000 ms.
    assert report.place_to_fill_ms_p99 < 10_000
    assert report.unfilled_rest_ms_p50 == pytest.approx(14_390_000.0)
