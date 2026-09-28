"""``python -m nullius_api.demo``: seeding the members' public stores.

Feature 13's whole contract, read back through the same public stores
:mod:`nullius_api.demo` writes with — never through a second parser of
its own — plus the entrypoint's own subprocess boot, the way
``test_main.py`` pins ``python -m nullius_api`` itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import forward
import ledger
import nulloracle
import ops
import promotion
import pytest
import regime
import scoring
from nullius_api.demo import (
    DemoSeedReport,
    InMemoryPaperEngine,
    PAPER_ENGINE,
    main,
    seed_demo_store,
)


@pytest.fixture
def report(test_database_url: str) -> DemoSeedReport:
    """One seed, over the suite's own isolated database."""
    return seed_demo_store(test_database_url)


# -- The closed-campaign FDR rows -------------------------------------------


def test_seeds_three_closed_campaign_fdr_rows_oldest_first(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """docs/user-journeys/J02's own worked example: 0.9, ~0.61, 0.5."""
    history = scoring.FdrDeployStore(test_database_url).history()
    assert [campaign for campaign, _figure, _instant in history] == list(
        report.campaign_ids
    )
    figures = [round(figure, 4) for _campaign, figure, _instant in history]
    assert figures == [0.9, 0.6136, 0.5]


def test_the_newest_campaign_is_last_by_computed_at(
    test_database_url: str, report: DemoSeedReport
) -> None:
    history = scoring.FdrDeployStore(test_database_url).history()
    instants = [instant for _campaign, _figure, instant in history]
    assert instants == sorted(instants)


# -- Sealed epochs ------------------------------------------------------------


def test_seeds_three_sealed_epochs_one_partly_spent(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """J5's precondition: three sealed epochs, one having served 2
    decisions — still under budget, so all three answer clean."""
    assert promotion.remaining_clean_epochs(test_database_url) == 3


# -- Regime coverage -----------------------------------------------------------


def test_seeds_regime_coverage_including_an_honest_zero(
    test_database_url: str, report: DemoSeedReport
) -> None:
    counts = regime.RegimeCoverage(test_database_url).ledger().counts
    assert counts["high_vol_trend"] == 2
    assert counts["low_vol_chop"] == 14
    assert counts["crash"] == 0


# -- Instrument readings -------------------------------------------------------


def test_seeds_instrument_readings_canary_healthy_ks_lit_feed_recorded(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """J4's precondition: canary healthy, KS guard reading present, feed
    staleness recorded.  Canary needs no seed — an empty halt table is
    the honest *dreaming runs* answer."""
    status = ops.InstrumentStatusEndpoint.from_env().get()
    assert status.canary is True
    assert status.ks_guard is True
    assert status.campaign == report.campaign_ids[-1]
    assert status.ks_pvalue >= nulloracle.VOID_THRESHOLD
    assert status.ingest_lag_seconds == 1.2


# -- The pre-registered, decided node with forward observations --------------


def test_seeds_a_pre_registered_and_decided_node(
    test_database_url: str, report: DemoSeedReport
) -> None:
    record = promotion.promotion_decision(report.node_id, database_url=test_database_url)
    assert record is not None
    assert record.decided_at is not None
    assert record.decided_at >= record.pre_registered_at


def test_seeds_forward_observations_strictly_after_the_promotion_day(
    test_database_url: str, report: DemoSeedReport
) -> None:
    records = forward.ForwardRecords(test_database_url)
    opened, _created = records.open_record(report.node_id, forward_days=90)
    assert str(opened.promoted_at.date()) == "2026-03-03"
    from forward.decay import decay_curve

    curve = decay_curve(report.node_id, database_url=test_database_url)
    observed = [str(point.observed_on) for point in curve.points]
    assert observed == list(report.forward_observed_on)
    assert all(day > str(opened.promoted_at.date()) for day in observed)


# -- Trial-ledger charges and the node's provenance triple --------------------


def test_seeds_two_trial_ledger_charges_one_null_node_excluded_from_k_effective(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """A real trial's charge counts toward ``K_effective``; a null
    node's charge is booked (the ledger is append-only) but never
    inflates the count feature 93 filters on ``charges_budget``."""
    trial_ledger = ledger.TrialLedger(test_database_url)
    assert trial_ledger.count() == 2
    counts = dict(trial_ledger.k_effective().counts)
    assert counts[report.epoch_ids[0]] == 1
    assert counts.get(report.epoch_ids[1], 0) == 0


def test_the_node_row_carries_the_provenance_triple(
    test_database_url: str, report: DemoSeedReport
) -> None:
    import sqlite3
    from urllib.parse import urlparse

    path = urlparse(test_database_url).path
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT campaign_id, evaluator_hash, snapshot_hash, cost_model_hash "
            "FROM node WHERE id = ?",
            (report.node_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    campaign_id, evaluator_hash, snapshot_hash, cost_model_hash = row
    assert campaign_id == report.campaign_ids[-1]
    for term in (evaluator_hash, snapshot_hash, cost_model_hash):
        assert isinstance(term, str)
        assert len(term) == 64
        assert all(char in "0123456789abcdef" for char in term)


# -- The paper execution engine -----------------------------------------------


def test_the_paper_engine_speaks_the_flatten_face_with_open_orders_and_positions() -> None:
    assert isinstance(PAPER_ENGINE, InMemoryPaperEngine)
    assert PAPER_ENGINE.open_orders()
    assert PAPER_ENGINE.open_positions()


def test_the_paper_engine_ends_exactly_what_it_is_told_to() -> None:
    engine = InMemoryPaperEngine(orders=("o-1", "o-2"), positions=("BTCUSDT",))
    engine.cancel_order("o-1")
    assert engine.open_orders() == ["o-2"]
    engine.close_position("BTCUSDT")
    assert engine.open_positions() == []
    # Ending an id that is not standing is a no-op, never a refusal.
    engine.cancel_order("not-there")
    engine.close_position("not-there")


def test_a_fresh_server_can_drive_the_paper_engine_flat(test_database_url: str) -> None:
    """The face risk.flatten actually checks — a live end-to-end proof
    that this engine is drivable, not just duck-typed on paper."""
    import risk

    engine = InMemoryPaperEngine(orders=("o-1",), positions=("ETHUSDT",))
    switch = risk.RiskKillSwitch(test_database_url)
    switch.send()
    flattener = risk.RiskFlattener(test_database_url)
    result = flattener.flatten(engine)
    assert result.cancelled_orders == ("o-1",)
    assert result.closed_positions == ("ETHUSDT",)
    assert engine.open_orders() == []
    assert engine.open_positions() == []


# -- Idempotence ----------------------------------------------------------------


def test_seeding_twice_leaves_the_store_exactly_as_the_first_run_did(
    test_database_url: str, report: DemoSeedReport
) -> None:
    second = seed_demo_store(test_database_url)
    assert second == report
    history = scoring.FdrDeployStore(test_database_url).history()
    assert len(history) == 3


# -- The entrypoint -------------------------------------------------------------


def test_missing_database_url_refuses_plainly(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    status = main([])
    assert status == 2
    written = capsys.readouterr().err
    assert "DATABASE_URL" in written
    assert "Traceback" not in written


def test_python_dash_m_nullius_api_demo_seeds_the_named_database(
    test_database_url: str,
) -> None:
    import os

    repo_root = Path(__file__).resolve().parents[3]
    from app.module_loader import workspace_scan_roots

    entries = [str(repo_root / "src"), *(str(root) for root in workspace_scan_roots())]
    environment = dict(os.environ)
    environment["DATABASE_URL"] = test_database_url
    environment["PYTHONPATH"] = ":".join(entries)
    completed = subprocess.run(
        [sys.executable, "-m", "nullius_api.demo"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "seeded" in completed.stdout
    assert "Traceback" not in completed.stderr
    history = scoring.FdrDeployStore(test_database_url).history()
    assert len(history) == 3
