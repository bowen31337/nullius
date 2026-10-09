"""additions_spec_tripwires_live.xml, the M1 triage figure at close-out.

*System computes the M1 triage figure at close-out, so that* ``./run.sh
closeout --campaign-id ID`` *returns the perturbation-stability AUC that
separates the campaign's planted nulls from its real nodes.*  Close-out
already walks every evaluated node to its root and asks the sidecar for that
root's null status (the same loop :mod:`orchestrator.closeout` runs for the
KS guard's split); this feature adds one more sample collected in that same
loop -- ``(perturb_stability, root-mapped label)`` for every evaluated node
whose lookback-jitter tripwire measured -- and persists the Mann-Whitney U
AUC over it, never a node id or a label.

This suite drives :func:`orchestrator.closeout.main` over a throwaway, fully
migrated SQLite database and a tmp null sidecar sealed the way
:mod:`nullius_api.demo` seals one, the same harness ``test_closeout_cli.py``
and ``test_closeout_subtree.py`` use.

One test per claim the feature sentence makes:

* **perfectly separated stabilities give AUC 1.0** -- every real node's
  ``perturb_stability`` (an instability magnitude) below every null node's.
* **a reversed ordering gives 0.0** -- every real node's below every null
  node's.
* **ties give 0.5** -- a sample that is nothing but ties.
* **too few on one side gives ``triage_auc`` null, and the rest of
  close-out is unchanged** -- the KS guard, the verdict and the other
  figures still land exactly as they would without a triage sample at all.
* **children are labelled by their root** -- a child's ``perturb_stability``
  counts on its root's side of the AUC, not refused for lacking its own
  sidecar entry.
* **a rerun refreshes the row** -- a second close-out over a changed sample
  updates the one row rather than appending a second.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory, and none holds state at module scope,
so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlparse

import discovery
import ledger
import nulloracle
import pytest
from orchestrator.closeout import (
    CLOSEOUT_TRIAGE_TABLE,
    EXIT_OK,
    EXIT_VOID,
    main,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the same resolution test_closeout_cli.py
# and test_closeout_subtree.py use.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATOR_HASH = hashlib.sha256(b"closeout-triage-test-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"closeout-triage-test-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"closeout-triage-test-cost-model").hexdigest()


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_closeout_triage_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'closeout-triage-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _path_of(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _plant_node(
    database_url: str,
    campaign_id: str,
    *,
    node_id: str,
    parent_id: str | None = None,
    depth: int = 0,
    ic_mean: float,
    ic_tstat: float,
    perturb_stability: float | None = None,
) -> str:
    """Insert one evaluated node row directly -- the state a finished
    campaign's live evaluator and tripwire step would have written."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat, perturb_stability) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                node_id,
                parent_id,
                campaign_id,
                "macro",
                depth,
                ic_mean,
                ic_tstat,
                perturb_stability,
            ),
        )
    return node_id


def _set_perturb_stability(
    database_url: str, node_id: str, perturb_stability: float | None
) -> None:
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "UPDATE node SET perturb_stability = ? WHERE id = ?",
            (perturb_stability, node_id),
        )


def _charge_ledger(
    database_url: str,
    node_id: str,
    campaign_id: str,
    *,
    epoch_id: str,
) -> None:
    ledger.TrialLedger(database_url).debit(
        node_id,
        campaign_id,
        outcome="ok",
        charges_budget=True,
        charge_units=1.0,
        epoch_id=epoch_id,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ts=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )


def _seal_sidecar(
    tmp_path: Path, assignments: list[nulloracle.NullAssignment]
) -> dict[str, str]:
    """Seal ``assignments`` into a tmp sidecar, the way
    :mod:`nullius_api.demo` seals its own, and answer the two environment
    variables a process needs to read it back."""
    material = os.urandom(nulloracle.SIDECAR_KEY_BYTES)
    path = tmp_path / "null" / "sidecar.enc"
    nulloracle.NullSidecar(path, material).write(assignments)
    return {
        nulloracle.SIDECAR_PATH_ENV: str(path),
        nulloracle.KEY_REF_ENV: f"hex:{material.hex()}",
    }


def _assignment(
    campaign_id: str, node_id: str, *, is_null: bool
) -> nulloracle.NullAssignment:
    return nulloracle.NullAssignment(
        node_id=node_id,
        is_null=is_null,
        perm_seed=nulloracle.perm_seed_for(campaign_id, node_id),
    )


def _plant_campaign(
    database_url: str,
    tmp_path: Path,
    *,
    null_stabilities: list[float],
    real_stabilities: list[float],
) -> tuple[str, dict[str, str], list[str], list[str]]:
    """A roots-only Type-R campaign: one root per stability reading, half
    planted null and half planted real, charged and sealed -- the minimal
    harness every single-side test in this suite shares. Answers the
    campaign id, its environment, and the planted null/real node ids (so a
    rerun test can change a node's own stability by id)."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=0.1, ic_tstat=0.5, perturb_stability=stability,
        )
        for stability in null_stabilities
    ]
    # The last real root clears DISCOVERY_TSTAT (2.0) -- feature 267's
    # FDR_deploy refuses the 0/0 corner of a campaign that declared nothing
    # (sensitivity 0.0, specificity 1.0 together), so every campaign this
    # harness plants needs at least one discovery, orthogonal to the triage
    # sample these tests are about.
    real_ic_tstats = [0.6] * (len(real_stabilities) - 1) + [2.5]
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=0.2, ic_tstat=ic_tstat, perturb_stability=stability,
        )
        for stability, ic_tstat in zip(real_stabilities, real_ic_tstats)
    ]
    all_ids = null_ids + real_ids
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env, null_ids, real_ids


def _triage_row(database_url: str, campaign_id: str) -> tuple:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        row = connection.execute(
            f"SELECT auc, null_count, real_count, computed_at "
            f"FROM {CLOSEOUT_TRIAGE_TABLE} WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    assert row is not None
    return row


# -- Perfect separation, and its reversal ------------------------------------


def test_perfectly_separated_stabilities_give_auc_one(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id, env, _null_ids, _real_ids = _plant_campaign(
        database_url, tmp_path,
        null_stabilities=[0.50, 0.60, 0.70],
        real_stabilities=[0.01, 0.02, 0.03],
    )

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code in (EXIT_OK, EXIT_VOID)
    payload = json.loads(lines[0])
    assert payload["triage_auc"] == 1.0
    assert payload["triage_null_count"] == 3
    assert payload["triage_real_count"] == 3

    auc, null_count, real_count, _computed_at = _triage_row(database_url, campaign_id)
    assert auc == 1.0
    assert (null_count, real_count) == (3, 3)


def test_reversed_ordering_gives_auc_zero(database_url: str, tmp_path: Path) -> None:
    campaign_id, env, _null_ids, _real_ids = _plant_campaign(
        database_url, tmp_path,
        null_stabilities=[0.01, 0.02, 0.03],
        real_stabilities=[0.50, 0.60, 0.70],
    )

    lines: list[str] = []
    main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    payload = json.loads(lines[0])
    assert payload["triage_auc"] == 0.0


# -- Ties ----------------------------------------------------------------


def test_ties_give_half(database_url: str, tmp_path: Path) -> None:
    campaign_id, env, _null_ids, _real_ids = _plant_campaign(
        database_url, tmp_path,
        null_stabilities=[0.25, 0.25, 0.25],
        real_stabilities=[0.25, 0.25, 0.25],
    )

    lines: list[str] = []
    main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    payload = json.loads(lines[0])
    assert payload["triage_auc"] == 0.5


# -- Too few on one side ---------------------------------------------------


def test_too_few_on_one_side_gives_null_auc_and_rest_unchanged(
    database_url: str, tmp_path: Path
) -> None:
    # Three null nodes measured, but only one real node's tripwire ever
    # measured (the other two carry perturb_stability NULL) -- the real
    # side of the triage sample holds one reading, below TRIAGE_MIN_SIDE.
    campaign_id, env, _null_ids, _real_ids = _plant_campaign(
        database_url, tmp_path,
        null_stabilities=[0.1, 0.2, 0.3],
        real_stabilities=[0.4, None, None],  # type: ignore[list-item]
    )

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    # The figures are saved and printed whether or not this small sample
    # votes VOID (the module's own law, unrelated to the triage sample's
    # size) -- only a refusal or config exit would mean the thin triage
    # sample broke close-out, which is the claim under test.
    assert exit_code in (EXIT_OK, EXIT_VOID)
    payload = json.loads(lines[0])
    assert payload["triage_auc"] is None
    assert payload["triage_null_count"] == 3
    assert payload["triage_real_count"] == 1
    # The rest of close-out is unaffected by the thin triage sample: the KS
    # guard split still counts every evaluated node (its own, unrelated,
    # ic_mean-based sample), and the calibration figures still land.
    assert payload["calibration_status"] in (
        nulloracle.CALIBRATION_STATUS_OK,
        nulloracle.CALIBRATION_STATUS_VOID,
    )
    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    # _plant_campaign's last real root clears DISCOVERY_TSTAT so the
    # campaign always has a discovery (see its own docstring) -- excluded
    # from the gate's own sample by the non-significance truncation
    # (bug_spec_ks_guard_root_level.xml), leaving two real roots, not three.
    assert (guard.null_count, guard.real_count) == (3, 2)

    auc, null_count, real_count, _computed_at = _triage_row(database_url, campaign_id)
    assert auc is None
    assert (null_count, real_count) == (3, 1)


# -- Children are labelled by their root --------------------------------------


def test_children_are_labelled_by_their_root(database_url: str, tmp_path: Path) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )

    root_null = str(uuid.uuid4())
    _plant_node(
        database_url, campaign_id, node_id=root_null, depth=0,
        ic_mean=0.1, ic_tstat=0.4, perturb_stability=0.60,
    )
    child_null = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_null,
        depth=1, ic_mean=0.15, ic_tstat=0.5, perturb_stability=0.70,
    )
    root_real = str(uuid.uuid4())
    _plant_node(
        database_url, campaign_id, node_id=root_real, depth=0,
        ic_mean=0.2, ic_tstat=0.6, perturb_stability=0.02,
    )
    # Clears DISCOVERY_TSTAT (2.0) -- feature 267's FDR_deploy refuses a
    # campaign that declared nothing at all, orthogonal to this test's own
    # claim about the triage sample.
    child_real = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_real,
        depth=1, ic_mean=0.25, ic_tstat=2.5, perturb_stability=0.03,
    )

    all_ids = [root_null, child_null, root_real, child_real]
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")

    assignments = [
        _assignment(campaign_id, root_null, is_null=True),
        _assignment(campaign_id, root_real, is_null=False),
    ]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code in (EXIT_OK, EXIT_VOID)
    payload = json.loads(lines[0])
    # Both children's stabilities land on their root's side: two null
    # readings (0.60, 0.70), two real readings (0.02, 0.03), perfectly
    # separated -- the child never needs its own sidecar entry.
    assert payload["triage_null_count"] == 2
    assert payload["triage_real_count"] == 2
    assert payload["triage_auc"] == 1.0
    # No node id anywhere in the printed line, except the committed pick's
    # own (additions_spec_m2_baseline_financial_worlds.xml feature 2 prints
    # committed_pick -- a node id, never a null/real label, which is what
    # PRD §4.2 actually forbids).
    committed = payload["committed_pick"]
    for node_id in all_ids:
        if node_id == committed:
            continue
        assert node_id not in lines[0]


# -- A rerun refreshes the row -------------------------------------------


def test_rerun_refreshes_the_row(database_url: str, tmp_path: Path) -> None:
    campaign_id, env, null_ids, real_ids = _plant_campaign(
        database_url, tmp_path,
        null_stabilities=[0.01, 0.02, 0.03],
        real_stabilities=[0.50, 0.60, 0.70],
    )

    first_lines: list[str] = []
    main(["--campaign-id", campaign_id], env=env, emit=first_lines.append)
    first_payload = json.loads(first_lines[0])
    assert first_payload["triage_auc"] == 0.0

    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        row_count = connection.execute(
            f"SELECT COUNT(*) FROM {CLOSEOUT_TRIAGE_TABLE}"
        ).fetchone()[0]
    assert row_count == 1

    # Swap the two sides' stabilities directly by node id -- a reversal --
    # and confirm the rerun's row reflects the new figure, not the first
    # run's.
    for node_id, stability in zip(null_ids, [0.50, 0.60, 0.70]):
        _set_perturb_stability(database_url, node_id, stability)
    for node_id, stability in zip(real_ids, [0.01, 0.02, 0.03]):
        _set_perturb_stability(database_url, node_id, stability)

    second_lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=second_lines.append)
    second_payload = json.loads(second_lines[0])

    assert exit_code in (EXIT_OK, EXIT_VOID)
    assert second_payload["triage_auc"] == 1.0

    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        row_count = connection.execute(
            f"SELECT COUNT(*) FROM {CLOSEOUT_TRIAGE_TABLE}"
        ).fetchone()[0]
    assert row_count == 1

    auc, null_count, real_count, _computed_at = _triage_row(database_url, campaign_id)
    assert auc == 1.0
    assert (null_count, real_count) == (3, 3)
