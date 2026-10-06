"""``python -m nullius_api.demo``: seeding the members' public stores.

Feature 13's whole contract, read back through the same public stores
:mod:`nullius_api.demo` writes with — never through a second parser of
its own — plus the entrypoint's own subprocess boot, the way
``test_main.py`` pins ``python -m nullius_api`` itself.
"""

from __future__ import annotations

import datetime as dt
import re
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import forward
import ledger
import nulloracle
import ops
import promotion
import pytest
import regime
import scoring
from nullius_api.demo import (
    PAPER_ENGINE,
    DemoSeedReport,
    InMemoryPaperEngine,
    main,
    seed_demo_store,
)

#: The demo seeder's path from this file: tests -> api -> packages -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def report(test_database_url: str) -> DemoSeedReport:
    """One seed, over the suite's own isolated database."""
    return seed_demo_store(test_database_url)


# -- The sealed demo sidecar ---------------------------------------------------
#
# Journey J12 (docs/user-journeys/J12-api-null-oracle-target.md) reads
# ``POST /target`` off a store the shipped seeder produced, and the route
# answers from §7.1's sidecar — a *file* beside the database, not a table.
# Without one the composed ``nulloracle-target-route`` component is absent
# and every node answers 503 ``component_unconfigured``, so neither the
# unknown-node 404 nor the null/real barrier can be exercised from the
# documented demo at all.  The tests below hold the seeder's half of that:
# the file exists, at the mode §7.1 requires, holds one null node and one
# real one, opens under the key the report hands back, and *is* the file
# the composed route serves from once the two variables are exported.


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_seed_seals_a_sidecar_beside_the_database(
    test_database_url: str, report: DemoSeedReport, tmp_path: Path
) -> None:
    """The file is where the report says, and §7.1's modes go with it.

    ``0o700`` on the directory and ``0o600`` on the file are not decoration:
    :meth:`nulloracle.sidecar.NullSidecar.open` refuses a sidecar whose group
    or other bits are set, so a demo that wrote the file world-readable
    would compose a route that refuses every request.
    """
    assert report.null_sidecar_path
    sidecar_path = Path(report.null_sidecar_path)
    assert sidecar_path.is_file()
    assert sidecar_path.name == nulloracle.SIDECAR_FILENAME == "sidecar.enc"
    assert _mode(sidecar_path) == nulloracle.SIDECAR_FILE_MODE == 0o600
    assert _mode(sidecar_path.parent) == 0o700
    # Beside the database, so an operator who names one path has named the
    # pair: the store and its sidecar travel together.
    database = Path(unquote(urlparse(test_database_url).path).removeprefix("/"))
    assert sidecar_path.parent.parent == database.parent

    # And the location is *derived* from DATABASE_URL alone — the one thing
    # the seeder is told — rather than from a constant somewhere in the
    # repository: a store named elsewhere gets its sidecar elsewhere, which
    # is the constraint that the demo writes only where the operator
    # pointed it.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other_report = seed_demo_store(f"sqlite:///{elsewhere / 'demo.db'}")
    assert Path(other_report.null_sidecar_path).parent.parent == elsewhere
    assert Path(other_report.null_sidecar_path).is_file()


def test_the_sealed_sidecar_holds_one_null_node_and_one_real_node(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """The pair the barrier needs, openable under the printed key.

    Read back through the member's own :class:`NullSidecar` rather than by
    decrypting by hand, so what the test holds is the artifact the composed
    route will hold.  Both seeds carry a permutation seed derived from the
    node's own identity (the member's own
    :func:`nulloracle.perm_seed_for`), so a replayed campaign reproduces the
    same series rather than drawing a fresh permutation.
    """
    sidecar = nulloracle.NullSidecar(
        report.null_sidecar_path, bytes.fromhex(report.null_sidecar_key)
    )
    assignments = sidecar.open()
    assert set(assignments) == {report.real_node_id, report.null_node_id}
    assert assignments[report.null_node_id].is_null is True
    assert assignments[report.real_node_id].is_null is False
    for node_id, assignment in assignments.items():
        assert assignment.perm_seed == nulloracle.perm_seed_for(
            report.campaign_ids[-1], node_id
        )
        assert assignment.block_days == nulloracle.DEFAULT_BLOCK_DAYS == 20


def test_the_demo_key_is_a_fresh_32_byte_secret_never_written_into_the_repository(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """A demo key is generated per seeding, and the repository never holds it.

    Two seeds of the same store are two keys and two names, so the demo
    cannot be replayed from a checked-in secret.  The last assertion is the
    constraint read literally: the key *material* is a string this process
    holds, and it must not appear as text in any tracked source of the
    checkout — a key that landed in a fixture, a log or a doc would be a
    key in the repository however it got there.
    """
    assert re.fullmatch(r"[0-9a-f]{64}", report.null_sidecar_key)
    assert report.null_sidecar_key_ref == f"hex:{report.null_sidecar_key}"
    second = seed_demo_store(test_database_url)
    assert second.null_sidecar_key != report.null_sidecar_key
    assert second.null_sidecar_path == report.null_sidecar_path
    # The second run's report is what stands on disk, and it still opens.
    nulloracle.NullSidecar(
        second.null_sidecar_path, bytes.fromhex(second.null_sidecar_key)
    ).open()

    # Scanned in the *checkout's* tracked source trees, not the whole
    # worktree: pytest's own scratch is under ``.claw-forge/tmp``, which is
    # where the report's key legitimately is not either — the sealed file
    # holds ciphertext.
    material = report.null_sidecar_key.encode()
    for name in ("packages", "tests", "src", "docs", "migrations"):
        tree = REPO_ROOT / name
        if not tree.is_dir():  # pragma: no cover - the checkout has all five
            continue
        for path in tree.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            assert material not in path.read_bytes(), (
                f"the demo key was written into {path}; §7.1's secret lives "
                "only in the process that printed it"
            )


def test_the_sidecar_holds_only_nodes_the_tree_store_already_carries(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """Constraint: existing demo rows and their identifiers are unchanged.

    The pair the sidecar names are identities the store *already* had —
    the pre-registered node the forward curve and the charges read, and
    the node whose bare charge is already in the trial ledger — so sealing
    a sidecar adds no node row and moves nothing an earlier journey sees.
    Both are also rows of the ``node`` table, because §7.1's file is about
    nodes and a sealed assignment naming a node the tree store does not
    hold is one an audit could not join.
    """
    import sqlite3

    path = unquote(urlparse(test_database_url).path).removeprefix("/")
    connection = sqlite3.connect(path)
    try:
        identifiers = {row[0] for row in connection.execute("SELECT id FROM node")}
    finally:
        connection.close()
    assert report.node_id in identifiers
    assert {report.real_node_id, report.null_node_id} <= identifiers
    assert report.null_node_id != report.real_node_id
    # The identifiers are the fixed constants the earlier journeys read, so
    # a re-seeded store is still the store J4/J5/J11 were validated on.
    assert report.node_id == "00000000-0000-4000-8000-0000000000a1"
    assert report.null_node_id == "00000000-0000-4000-8000-0000000000b2"


def test_the_real_node_is_a_demo_node_the_forward_curve_already_tracks(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """The real branch is the node the store already promotes, not a new one.

    A *known real* node is one the sidecar holds an entry for; making it
    the node whose forward observations and charges J10/J11 already read
    keeps the demo's world one world rather than two, and gives the
    documented steps a node whose other routes answer too.
    """
    assert report.real_node_id == report.node_id


def test_exporting_the_printed_values_composes_a_route_that_knows_the_barrier(
    test_database_url: str, report: DemoSeedReport, monkeypatch
) -> None:
    """The documented demo's own two exports, read one step short of HTTP.

    This is the defect's reproduction: with nothing exported the composed
    component is absent — the 503 ``component_unconfigured`` the journey
    recorded — and with the report's two strings exported the composed
    ``nulloracle-target-route`` knows §7.2's world.  An unknown node is the
    member's own :data:`nulloracle.NOT_FOUND`, and a known node is reached
    far enough to be *refused for want of a series supply* rather than for
    want of a sidecar — and refused identically on both branches, which is
    the barrier's whole shape.
    """
    from app.module_loader import create_app

    monkeypatch.delenv(nulloracle.SIDECAR_PATH_ENV, raising=False)
    monkeypatch.delenv(nulloracle.KEY_REF_ENV, raising=False)
    assert create_app().get("nulloracle-target-route") is None

    monkeypatch.setenv(nulloracle.SIDECAR_PATH_ENV, report.null_sidecar_path)
    monkeypatch.setenv(nulloracle.KEY_REF_ENV, report.null_sidecar_key_ref)
    endpoint = create_app().get("nulloracle-target-route")
    assert endpoint is not None
    assert endpoint.sidecar.path == Path(report.null_sidecar_path)

    def ask(node_id: str) -> nulloracle.TargetResponse:
        return endpoint.post(
            nulloracle.TargetRequest(
                node_id=node_id,
                campaign_id=report.campaign_ids[-1],
                depth=0,
                horizon=5,
                symbols=("BTCUSDT",),
                date_range=(dt.date(2026, 1, 1), dt.date(2026, 2, 20)),
            )
        )

    unknown = ask("ffffffff-0000-4000-8000-000000000000")
    assert unknown.status == nulloracle.NOT_FOUND
    assert unknown.known is False

    # A known node is one the sidecar holds an entry for; a bare demo wires
    # no series supply (``build_target_route`` leaves step 4's alignment to
    # the evaluator), so the member refuses to serve half a world rather
    # than answering — and refuses *both* branches with the same refusal.
    #
    # The refusal is recognised by *name* rather than by ``isinstance``, for
    # the reason this workspace states at every cross-module seam: the
    # factory's scan imports the member under a synthetic module alias, so
    # the composed endpoint's ``TargetPayloadError`` is structurally the
    # member's class and never the same class object a direct import yields.
    refusals = []
    for node_id in (report.real_node_id, report.null_node_id):
        assert endpoint.sidecar.assignment(node_id) is not None
        with pytest.raises(Exception) as raised:
            ask(node_id)
        assert type(raised.value).__name__ == "TargetPayloadError"
        refusals.append(str(raised.value).replace(node_id, "<node>"))
    assert refusals[0] == refusals[1]
    assert endpoint.sidecar.assignment(report.null_node_id).is_null is True
    assert endpoint.sidecar.assignment(report.real_node_id).is_null is False


# -- The entrypoint -------------------------------------------------------------


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


def test_seeds_instrument_readings_canary_no_reading_ks_lit_feed_recorded(
    test_database_url: str, report: DemoSeedReport
) -> None:
    """J4's precondition: KS guard reading present, feed staleness
    recorded.  The canary lamp seeds no run of its own (feature 342's
    freshness window is relative to wall-clock *now*, which a demo's
    fixed, idempotently-reseedable rows cannot satisfy), so it answers
    the honest *no reading* rather than a fabricated healthy bit."""
    status = ops.InstrumentStatusEndpoint.from_env().get()
    assert status.canary is None
    assert status.canary_last_run_at is None
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
    """The *store* is idempotent; the demo's key deliberately is not.

    Every row, every identifier and the sidecar's location are what a
    first run left, so a repeated seed does not grow the store or move the
    world — that is the law this test has always held.  What a second run
    *does* change is the key the sidecar is sealed under: the demo's key is
    generated per seeding and held by no file (see the module docstring),
    so a run that is not the run printed by :func:`main` has replaced the
    file under a secret only that run printed.  The fields that are not the
    key are compared whole, then the key is asserted fresh and *used* —
    which is what makes the fresh seal a working sidecar rather than a
    rewrite.
    """
    second = seed_demo_store(test_database_url)
    differing = {
        field: (getattr(report, field), getattr(second, field))
        for field in (
            "campaign_ids",
            "node_id",
            "epoch_ids",
            "forward_observed_on",
            "real_node_id",
            "null_node_id",
            "null_sidecar_path",
        )
        if getattr(report, field) != getattr(second, field)
    }
    assert differing == {}
    assert second.null_sidecar_key != report.null_sidecar_key
    assert second.null_sidecar_key_ref == f"hex:{second.null_sidecar_key}"
    nulloracle.NullSidecar(
        second.null_sidecar_path, bytes.fromhex(second.null_sidecar_key)
    ).open()
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


def _run_demo(test_database_url: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """``python -m nullius_api.demo`` against ``test_database_url``.

    The environment is a *fresh* one seeded from this process's, carrying
    only ``DATABASE_URL`` and the path bootstrap — the seeder takes no
    flags and reads no variable but the one naming the database, so the
    sidecar lands beside the store rather than wherever a test's own
    environment happened to point.  ``tmp_path`` is accepted and unused for
    that reason: it documents that the store under test lives there.
    """
    _ = tmp_path
    import os

    from app.module_loader import workspace_scan_roots

    entries = [str(REPO_ROOT / "src"), *(str(root) for root in workspace_scan_roots())]
    environment = dict(os.environ)
    environment["DATABASE_URL"] = test_database_url
    environment["PYTHONPATH"] = ":".join(entries)
    return subprocess.run(
        [sys.executable, "-m", "nullius_api.demo"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_python_dash_m_nullius_api_demo_seeds_the_named_database(
    test_database_url: str, tmp_path: Path
) -> None:
    completed = _run_demo(test_database_url, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert "seeded" in completed.stdout
    assert "Traceback" not in completed.stderr
    history = scoring.FdrDeployStore(test_database_url).history()
    assert len(history) == 3


def test_the_entrypoint_prints_the_two_values_the_documented_steps_must_export(
    test_database_url: str, tmp_path: Path
) -> None:
    """The defect's other half: nothing told the operator how to configure a
    sidecar.  The summary now names both variables and both values.

    Parsed back out of the printed lines rather than recomputed, so the test
    reads what an operator reads — ``export NULL_SIDECAR_PATH=…`` and
    ``export NULL_SIDECAR_KEY_REF=hex:…`` — and then *uses* them: the
    sealed file at the printed path opens under the printed key, which is
    what makes the printed pair worth exporting.
    """
    completed = _run_demo(test_database_url, tmp_path)
    assert completed.returncode == 0, completed.stderr
    path = re.search(r"NULL_SIDECAR_PATH=(\S+)", completed.stdout)
    key_ref = re.search(r"NULL_SIDECAR_KEY_REF=(\S+)", completed.stdout)
    assert path is not None, completed.stdout
    assert key_ref is not None, completed.stdout
    assert key_ref.group(1).startswith("hex:")
    assert key_ref.group(1).removeprefix("hex:") not in completed.stderr

    sidecar = nulloracle.NullSidecar(
        path.group(1), bytes.fromhex(key_ref.group(1).removeprefix("hex:"))
    )
    assignments = sidecar.open()
    assert assignments
    assert any(entry.is_null for entry in assignments.values())
    assert any(not entry.is_null for entry in assignments.values())
