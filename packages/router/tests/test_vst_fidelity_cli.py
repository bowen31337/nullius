"""Tests for feature 6 of ``additions_spec_vst_fidelity.xml`` —
:mod:`router.vst_fidelity`, the ``python -m router.vst_fidelity`` report.

*System reports the fidelity distributions from* ``python -m
router.vst_fidelity [--since YYYY-MM-DD] [--book ID]`` *and displays one
JSON object.*  Held clause by clause, over fixtures built the way the
reconciliation suite (:mod:`test_vst_fidelity_reconcile`) already builds
its own — :func:`router.fidelity.reconcile_fidelity` over placement terms
and fills seeded through their own public write APIs, never a client, a
plan or a socket:

* the distributions themselves, over a two-leg, one-slot, funded fixture
  whose every figure is hand-computed below;
* ``--since`` and ``--book`` each narrow the scope to the slot or book
  named, and leave the rest out entirely;
* rounding drift reads :data:`router.submission_result.ORDER_RECORD_TABLE`
  on its own, independent of whether the slot it belongs to was ever
  fidelity-reconciled — the asymmetry the module docstring states;
* an empty store (never a written row) answers ``n_orders`` 0 and exits 0,
  not a fault;
* a missing ``DATABASE_URL`` exits 2;
* the ``within_tolerance`` flag follows PRD §11.1's own
  :data:`router.vst_fidelity.GAP_BPS_TOLERANCE_BPS` bar in both
  directions;
* the seeded bootstrap interval is byte-for-byte identical across two
  reports over the same data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from router.bingx_funding import FundingIncome, RouterFundingIncomeStore
from router.bingx_order import BINGX_MARKET_ORDER
from router.client_order_id import derive_client_order_id
from router.fidelity import FidelitySlot, reconcile_fidelity
from router.submission_result import RouterOrderPlacementStore
from router.vst_fidelity import (
    EXIT_CONFIG,
    EXIT_OK,
    GAP_BPS_TOLERANCE_BPS,
    build_report,
    main,
)

from test_vst_fidelity_reconcile import _fill, _record  # isort: skip

BOOK_ID = "cli-fidelity-book"
REBALANCE_TS = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)


def _run_main(
    *, database_url: str | None = None, env: dict | None = None, argv=()
) -> tuple[int, list[str]]:
    """Drive :func:`router.vst_fidelity.main`, capturing every emitted line.

    ``argv`` defaults to no arguments at all — never ``None``, which would
    have ``argparse`` fall back to the *test runner's own* ``sys.argv``.
    """
    lines: list[str] = []
    code = main(list(argv), database_url=database_url, env=env, emit=lines.append)
    return code, lines


def _seed_two_leg_funded_slot(test_database_url: str) -> None:
    """One slot, two legs, one funding row — every figure below is
    hand-computed from exactly these numbers.

    Leg A (``BTC-USDT``, MARKET): a 5 bps adverse slip against a 100
    decision mark, a 0.3 bps fee, against a 4 bps expected cost — the same
    numbers :mod:`test_vst_fidelity_reconcile`'s own first test proves
    give ``realized_cost_bps`` 5.3 and ``gap_bps`` 1.3.  Notional 1000.5.

    Leg B (``ETH-USDT``, LIMIT): repriced 50 bps away from a 100 decision
    mark before filling exactly at its own repriced limit, plus a 2 bps
    fee, against an 11.5 bps expected cost — that suite's second test's
    own numbers, giving ``realized_cost_bps`` 52.0 and ``gap_bps`` 40.5.
    Notional 100.5.

    Neither leg's placement carries a ``target_quantity``, so this slot
    contributes nothing to rounding drift (see
    ``test_rounding_drift_reads_its_own_wider_universe`` below for that
    figure on its own).

    The slot's total notional is 1000.5 + 100.5 = 1101.0.  One funding row
    of -1.101 (a cost) lands inside the slot's window on ``BTC-USDT``, so
    ``funding_bps`` = 1.101 / 1101.0 * 10000 = 10.0 exactly.
    """
    store = RouterOrderPlacementStore(test_database_url)

    leg_a = _record(
        store,
        symbol="BTC-USDT",
        side="BUY",
        order_type=BINGX_MARKET_ORDER,
        quantity="10",
        reference_price="100.05",
        decision_mark=Decimal(100),
        expected_cost_bps=4.0,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        leg_a,
        symbol="BTC-USDT",
        executed_quantity=Decimal(10),
        average_price=Decimal("100.05"),
        original_quantity=Decimal(10),
        commission=Decimal("-0.030015"),
        database_url=test_database_url,
    )

    leg_b = _record(
        store,
        symbol="ETH-USDT",
        side="BUY",
        order_type="LIMIT",
        quantity="1",
        reference_price="100.5",
        decision_mark=Decimal(100),
        expected_cost_bps=11.5,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        leg_b,
        symbol="ETH-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal("100.5"),
        original_quantity=Decimal(1),
        commission=Decimal("-0.0201"),
        database_url=test_database_url,
    )

    funding_store = RouterFundingIncomeStore(test_database_url)
    slot_start_ms = int(REBALANCE_TS.timestamp() * 1000)
    funding_store.ingest(
        [
            FundingIncome(
                tran_id="cli-funding-row",
                symbol="BTC-USDT",
                income="-1.101",
                asset="VST",
                time=slot_start_ms + 1_000,
            )
        ]
    )

    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )
    assert result is not None
    assert result.n_fills == 2  # both legs filled, sanity on the fixture itself


# -- The distributions, over the seeded fixture ------------------------------


def test_reports_order_and_slot_level_distributions_over_a_seeded_fixture_store(
    test_database_url: str,
) -> None:
    _seed_two_leg_funded_slot(test_database_url)

    code, lines = _run_main(database_url=test_database_url, argv=["--book", BOOK_ID])
    assert code == EXIT_OK
    payload = json.loads(lines[0])

    assert payload["n_orders"] == 2
    assert payload["n_slots"] == 1

    gap_bps = payload["gap_bps"]
    assert gap_bps["mean"] == pytest.approx(20.9)  # (1.3 + 40.5) / 2
    # A 95% bootstrap interval over {1.3, 40.5} can never leave that range
    # (allowing float slop from the resampled-mean arithmetic itself).
    assert 1.3 - 1e-9 <= gap_bps["ci_low"] <= gap_bps["mean"]
    assert gap_bps["mean"] <= gap_bps["ci_high"] <= 40.5 + 1e-9

    realized = payload["realized_cost_bps"]
    assert realized["p50"] == pytest.approx(28.65)  # midpoint of 5.3 and 52.0
    assert realized["p95"] == pytest.approx(49.665)

    expected = payload["expected_cost_bps"]
    assert expected["p50"] == pytest.approx(7.75)  # midpoint of 4.0 and 11.5
    assert expected["p95"] == pytest.approx(11.125)

    place_to_fill = payload["place_to_fill_ms"]
    assert place_to_fill == {"p50": 23_000.0, "p95": 23_000.0, "p99": 23_000.0}

    assert payload["fill_ratio_mean"] == pytest.approx(1.0)  # both legs filled in full
    assert payload["maker_share"] == pytest.approx(0.5)  # only the LIMIT leg is a maker
    assert payload["reject_rate"] == pytest.approx(0.0)  # nothing rejected

    # Neither leg's placement carried a target_quantity.
    assert payload["rounding_drift_bps"] is None

    assert payload["funding_bps_per_day"] == pytest.approx(60.0)  # 10.0 bps/slot * (24h/4h)

    assert payload["within_tolerance"] is False  # |20.9| > GAP_BPS_TOLERANCE_BPS


def test_the_seeded_bootstrap_interval_is_deterministic_across_repeated_reports(
    test_database_url: str,
) -> None:
    _seed_two_leg_funded_slot(test_database_url)

    first = build_report(test_database_url, book=BOOK_ID)
    second = build_report(test_database_url, book=BOOK_ID)

    assert first == second
    assert (first.gap_bps_ci_low, first.gap_bps_ci_high) == (
        second.gap_bps_ci_low,
        second.gap_bps_ci_high,
    )


# -- Rounding drift reads its own, wider, universe ---------------------------


def test_rounding_drift_reads_its_own_wider_universe(test_database_url: str) -> None:
    """Rounding drift is read from ``router_order_record`` alone, never
    joined to the fidelity table — so it is measured here even though this
    order was never filled or fidelity-reconciled at all, and ``n_orders``
    (which counts the fidelity table) stays 0."""
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
        quantity="10.05",
        reference_price="100",
        target_quantity="10",
    )

    report = build_report(test_database_url, book=BOOK_ID)

    assert report.n_orders == 0
    assert report.rounding_drift_bps == 50.0  # (10.05 - 10) * 100 / (10 * 100) * 10000


# -- --since and --book narrow the scope -------------------------------------


def test_since_narrows_to_slots_at_or_after_the_given_date(test_database_url: str) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    early_slot = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    late_slot = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)

    for slot in (early_slot, late_slot):
        projected = _record(
            store,
            symbol="BTC-USDT",
            order_type=BINGX_MARKET_ORDER,
            quantity="1",
            reference_price="100",
            decision_mark=Decimal(100),
            expected_cost_bps=1.0,
            book_id="since-book",
            rebalance_ts=slot,
        )
        _fill(
            projected,
            symbol="BTC-USDT",
            executed_quantity=Decimal(1),
            average_price=Decimal(100),
            original_quantity=Decimal(1),
            database_url=test_database_url,
        )
        result = reconcile_fidelity(
            FidelitySlot(book_id="since-book", rebalance_ts=slot),
            database_url=test_database_url,
        )
        assert result is not None

    everything = build_report(test_database_url, book="since-book")
    assert (everything.n_orders, everything.n_slots) == (2, 2)

    narrowed = build_report(
        test_database_url,
        book="since-book",
        since=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert (narrowed.n_orders, narrowed.n_slots) == (1, 1)


def test_book_narrows_to_the_given_book_id(test_database_url: str) -> None:
    store = RouterOrderPlacementStore(test_database_url)
    for book_id in ("book-a", "book-b"):
        projected = _record(
            store,
            symbol="BTC-USDT",
            order_type=BINGX_MARKET_ORDER,
            quantity="1",
            reference_price="100",
            decision_mark=Decimal(100),
            expected_cost_bps=1.0,
            book_id=book_id,
            rebalance_ts=REBALANCE_TS,
        )
        _fill(
            projected,
            symbol="BTC-USDT",
            executed_quantity=Decimal(1),
            average_price=Decimal(100),
            original_quantity=Decimal(1),
            database_url=test_database_url,
        )
        result = reconcile_fidelity(
            FidelitySlot(book_id=book_id, rebalance_ts=REBALANCE_TS),
            database_url=test_database_url,
        )
        assert result is not None

    narrowed = build_report(test_database_url, book="book-a")
    assert (narrowed.n_orders, narrowed.n_slots) == (1, 1)

    everything = build_report(test_database_url)
    assert (everything.n_orders, everything.n_slots) == (2, 2)


# -- The empty store ----------------------------------------------------------


def test_an_empty_store_gives_n_orders_zero_and_exits_0(test_database_url: str) -> None:
    code, lines = _run_main(database_url=test_database_url)
    assert code == EXIT_OK
    payload = json.loads(lines[0])

    assert payload["n_orders"] == 0
    assert payload["n_slots"] == 0
    assert payload["gap_bps"] == {"mean": None, "ci_low": None, "ci_high": None}
    assert payload["realized_cost_bps"] == {"p50": None, "p95": None}
    assert payload["expected_cost_bps"] == {"p50": None, "p95": None}
    assert payload["place_to_fill_ms"] == {"p50": None, "p95": None, "p99": None}
    assert payload["fill_ratio_mean"] is None
    assert payload["maker_share"] is None
    assert payload["reject_rate"] is None
    assert payload["rounding_drift_bps"] is None
    assert payload["funding_bps_per_day"] is None
    assert payload["within_tolerance"] is None


# -- A missing DATABASE_URL exits 2 ------------------------------------------


def test_a_missing_database_url_exits_2(capsys) -> None:
    code, lines = _run_main(database_url=None, env={})
    assert code == EXIT_CONFIG
    assert lines == []  # no JSON line: there was no store to report on
    captured = capsys.readouterr()
    assert "DATABASE_URL" in captured.err


# -- within_tolerance follows the PRD §11.1 bar -------------------------------


def test_within_tolerance_is_true_when_the_mean_gap_is_inside_the_bar(
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
        expected_cost_bps=2.0,
        book_id=BOOK_ID,
        rebalance_ts=REBALANCE_TS,
    )
    _fill(
        projected,
        symbol="BTC-USDT",
        executed_quantity=Decimal(1),
        average_price=Decimal(100),  # no slippage
        original_quantity=Decimal(1),
        commission=Decimal(0),  # no fee
        database_url=test_database_url,
    )
    result = reconcile_fidelity(
        FidelitySlot(book_id=BOOK_ID, rebalance_ts=REBALANCE_TS),
        database_url=test_database_url,
    )
    assert result is not None
    assert result.gap_bps == -2.0  # realized 0.0 - expected 2.0

    report = build_report(test_database_url, book=BOOK_ID)
    assert report.gap_bps_mean == -2.0
    assert abs(report.gap_bps_mean) <= GAP_BPS_TOLERANCE_BPS
    assert report.within_tolerance is True


def test_within_tolerance_is_false_when_the_mean_gap_is_outside_the_bar(
    test_database_url: str,
) -> None:
    _seed_two_leg_funded_slot(test_database_url)  # mean gap 20.9, well past the bar

    report = build_report(test_database_url, book=BOOK_ID)
    assert abs(report.gap_bps_mean) > GAP_BPS_TOLERANCE_BPS
    assert report.within_tolerance is False
