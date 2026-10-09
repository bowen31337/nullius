"""Feature 13, the campaign close-out CLI -- ``python -m orchestrator.closeout``.

additions_spec_operator_surfaces.xml, "Campaign Close-out" category,
feature 13: *System closes out a finished campaign from* ``python -m
orchestrator.closeout --campaign-id ID``. This suite drives
:func:`orchestrator.closeout.main` directly over a throwaway, fully
migrated SQLite database and a tmp null sidecar built the way
:mod:`nullius_api.demo` builds one (:class:`nulloracle.NullSidecar` sealed
with :class:`nulloracle.NullAssignment` entries for the campaign's own node
ids), never a real subprocess.

One test per claim the feature sentence makes:

* **a small Type-R campaign closes out calibrated** -- the KS guard, the
  verdict, the calibration figures, ``FDR_deploy``, the discovery rate and
  their five stores all land, ``type_b`` is ``null``, and the command exits
  0.
* **a small Type-D campaign with a detectable split voids and measures
  Type-B** -- the verdict is ``VOID``, the figures are still saved, the
  command exits 3, and ``type_b`` carries the campaign's depth-past-flip
  count.
* **running it twice saves no duplicate row and prints the same line** --
  idempotence across all five stores.
* **no stdout line pairs a node id with a null label** -- every node id this
  suite plants is checked absent from the printed line (PRD §4.2).
* **an unknown campaign, or a one-sided plant too small for the KS
  guard's minimum sample, refuses with exit 1** and no traceback, and
  touches no store.
* **a missing ``DATABASE_URL`` or sidecar variable exits 2**, naming it.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory, and none holds any state at module
scope, so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import uuid
from contextlib import closing, redirect_stderr
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlparse

import discovery
import ledger
import nulloracle
import pytest
from orchestrator.closeout import (
    CLOSEOUT_CODE,
    CLOSEOUT_UNEVALUATED_CODE,
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_VOID,
    KS_VARIANT_BRANCH_NONSIG,
    main,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the same resolution test_campaign_cli.py
# and test_live_tree.py use.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATOR_HASH = hashlib.sha256(b"closeout-test-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"closeout-test-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"closeout-test-cost-model").hexdigest()


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_closeout_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'closeout-test.db'}"
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
) -> str:
    """Insert one evaluated node row directly -- the state a finished
    campaign's live evaluator would have written through
    :mod:`orchestrator._tree_writer`."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node_id, parent_id, campaign_id, "macro", depth, ic_mean, ic_tstat),
        )
    return node_id


def _set_flip_depth(database_url: str, node_id: str, flip_depth: int) -> None:
    """Fix node ``flip_depth`` directly -- §7.3's draw, pinned to one value
    for a reproducible test rather than drawn through
    :class:`nulloracle.FlipDepth` (whose column this adds idempotently, the
    same probe that store's own ``_connect`` performs)."""
    path = _path_of(database_url)
    with closing(sqlite3.connect(path)) as connection, connection:
        has_column = any(
            row[1] == "flip_depth"
            for row in connection.execute("PRAGMA table_info(node)")
        )
        if not has_column:
            connection.execute("ALTER TABLE node ADD COLUMN flip_depth INT")
        connection.execute(
            "UPDATE node SET flip_depth = ? WHERE id = ?", (flip_depth, node_id)
        )


def _charge_ledger(
    database_url: str,
    node_id: str,
    campaign_id: str,
    *,
    charges_budget: bool,
    epoch_id: str,
) -> None:
    ledger.TrialLedger(database_url).debit(
        node_id,
        campaign_id,
        outcome="ok",
        charges_budget=charges_budget,
        charge_units=1.0,
        epoch_id=epoch_id,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ts=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )


def _seal_sidecar(tmp_path: Path, assignments: list[nulloracle.NullAssignment]) -> dict[str, str]:
    """Seal ``assignments`` into a tmp sidecar, the way
    :mod:`nullius_api.demo` seals its own (through the member's one door,
    :meth:`nulloracle.NullSidecar.write`), and answer the two environment
    variables a process needs to read it back."""
    material = os.urandom(nulloracle.SIDECAR_KEY_BYTES)
    path = tmp_path / "null" / "sidecar.enc"
    nulloracle.NullSidecar(path, material).write(assignments)
    return {
        nulloracle.SIDECAR_PATH_ENV: str(path),
        nulloracle.KEY_REF_ENV: f"hex:{material.hex()}",
    }


def _assignment(campaign_id: str, node_id: str, *, is_null: bool) -> nulloracle.NullAssignment:
    return nulloracle.NullAssignment(
        node_id=node_id,
        is_null=is_null,
        perm_seed=nulloracle.perm_seed_for(campaign_id, node_id),
    )


# -- A small Type-R campaign, interleaved (indistinguishable) scores ----------


def _build_type_r_campaign(database_url: str, tmp_path: Path) -> tuple[str, dict[str, str], list[str]]:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE,
        4,
        campaign_id=campaign_id,
        database_url=database_url,
    )
    # Interleaved null/real ic_mean, the same shape
    # docs/user-journeys/J02's worked example (and nullius_api.demo) uses to
    # pin the KS test at its maximum p-value: the two samples are not
    # distinguishable, so the campaign stays calibrated.
    null_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((0.10, 0.4), (0.30, 1.1), (0.50, 1.8))
    ]
    real_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((0.20, 0.9), (0.40, 1.5), (0.95, 3.2))
    ]
    all_ids = null_ids + real_ids
    for index, node_id in enumerate(all_ids):
        _charge_ledger(
            database_url, node_id, campaign_id,
            charges_budget=True, epoch_id=f"epoch-{index}",
        )
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env, all_ids


# -- A small Type-D campaign, fully separated (detectable) scores ------------


def _build_type_d_campaign(database_url: str, tmp_path: Path) -> tuple[str, dict[str, str], list[str]]:
    """Four branches, each a real root (PRD §4.1.2: every Type-D root is
    real) with a child below its own flip and a grandchild past it -- the
    shape bug_spec_closeout_type_d_ks_branch.xml requires, where the Type-D
    gate's null sample lives in descendants past the flip, never in a root.

    Per branch: the root (depth 0) is itself a discovery (``ic_tstat`` well
    past :data:`~orchestrator.closeout.DISCOVERY_TSTAT`); its child (depth
    1, below the branch's flip at depth 2) is the gate's **deepest real**
    representative, non-significant; its grandchild (depth 2, at the flip)
    is the gate's **shallowest null** representative, also non-significant
    -- the same fully-separated values
    (``bug_spec_ks_guard_root_level.xml``'s own reproduction) the pre-fix
    all-root fixture used, so the KS test is just as decisive (exact
    two-sample, n=m=4: p ~= 0.0286) and the campaign is still voided.

    Two of the four roots are additionally sealed null and two real in the
    sidecar -- orthogonal to the depth-based branch labels above, and
    needed only so :meth:`scoring.NullPickScorer.calibration_figures` (fed
    this campaign's root population regardless of type) sees a non-empty
    class on each side; no production path seals a Type-D root in the
    sidecar at all (nulloracle's own sidecar is Type-R-only), so this is
    the same test-time convenience the existing Type-D subtree fixture
    already relies on.
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_D_CAMPAIGN_TYPE,
        4,
        campaign_id=campaign_id,
        database_url=database_url,
    )
    root_ic = ((0.60, 2.7), (0.70, 3.1), (0.80, 3.6), (0.95, 4.2))
    mid_ic = ((0.60, 0.9), (0.70, 1.1), (0.80, 1.3), (0.95, 1.5))
    child_ic = ((-0.90, -1.9), (-0.80, -1.7), (-0.70, -1.5), (-0.60, -1.3))
    roots: list[str] = []
    mids: list[str] = []
    children: list[str] = []
    for (root_mean, root_tstat), (mid_mean, mid_tstat), (child_mean, child_tstat) in zip(
        root_ic, mid_ic, child_ic
    ):
        root_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), depth=0,
            ic_mean=root_mean, ic_tstat=root_tstat,
        )
        # The flip is drawn on the branch's root (nulloracle's own
        # convention): depth 0-1 stays real, depth 2 and past is null.
        _set_flip_depth(database_url, root_id, 2)
        mid_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=mid_mean, ic_tstat=mid_tstat,
        )
        child_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=mid_id,
            depth=2, ic_mean=child_mean, ic_tstat=child_tstat,
        )
        roots.append(root_id)
        mids.append(mid_id)
        children.append(child_id)
    all_ids = roots + mids + children
    for index, node_id in enumerate(all_ids):
        _charge_ledger(
            database_url, node_id, campaign_id,
            charges_budget=True, epoch_id=f"epoch-{index}",
        )
    assignments = [_assignment(campaign_id, n, is_null=True) for n in roots[:2]]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in roots[2:]]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env, all_ids


# -- Type-R: calibrated ---------------------------------------------------------


def test_type_r_campaign_closes_out_calibrated(database_url: str, tmp_path: Path) -> None:
    campaign_id, env, _node_ids = _build_type_r_campaign(database_url, tmp_path / "r")
    lines: list[str] = []

    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["campaign_id"] == campaign_id
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_OK
    assert payload["type_b"] is None
    assert payload["discoveries"] == 1  # only the ic_tstat=3.2 real node clears 2.0
    assert payload["budget_charging_trials"] == 6
    assert payload["ledger_trials"] == 6
    assert 0.0 <= payload["sensitivity"] <= 1.0
    assert 0.0 <= payload["specificity"] <= 1.0
    assert isinstance(payload["ks_pvalue"], float)
    assert isinstance(payload["fdr_deploy"], float)

    # All five stores hold the campaign's row.
    import ops
    import scoring

    assert scoring.FdrDeployStore(database_url).fdr(campaign_id) == pytest.approx(
        payload["fdr_deploy"]
    )
    calibration = ops.NullCalibrations(database_url).calibration(campaign_id)
    assert calibration is not None
    assert calibration.sensitivity == payload["sensitivity"]
    assert calibration.specificity == payload["specificity"]
    assert ops.TypeBDepths(database_url).depth(campaign_id) is None
    rate = ops.DiscoveryRates(database_url).rate(campaign_id)
    assert rate is not None
    assert rate.discoveries == 1
    assert nulloracle.load_verdict(campaign_id, database_url=database_url) == (
        nulloracle.CALIBRATION_STATUS_OK
    )
    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert guard.pvalue == payload["ks_pvalue"]


# -- Type-D: VOID, with Type-B depth ---------------------------------------------


def test_type_d_campaign_voids_and_measures_type_b(database_url: str, tmp_path: Path) -> None:
    campaign_id, env, _node_ids = _build_type_d_campaign(database_url, tmp_path / "d")
    lines: list[str] = []

    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_VOID
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_VOID
    assert payload["ks_variant"] == KS_VARIANT_BRANCH_NONSIG
    assert payload["type_b"] == 4  # the four grandchildren past their flip
    assert payload["discoveries"] == 4  # all four roots clear ic_tstat 2.0
    assert payload["budget_charging_trials"] == 12
    assert payload["ledger_trials"] == 12

    import ops
    import scoring

    # The figures are saved in all five stores even though the campaign
    # voided -- exit 3 lets an alert fire, it does not skip the write.
    assert ops.TypeBDepths(database_url).depth(campaign_id).depth_past_flip_errors == 4
    calibration = ops.NullCalibrations(database_url).calibration(campaign_id)
    assert calibration is not None
    assert calibration.sensitivity == payload["sensitivity"]
    assert calibration.specificity == payload["specificity"]
    rate = ops.DiscoveryRates(database_url).rate(campaign_id)
    assert rate is not None
    assert rate.discoveries == 4
    assert scoring.FdrDeployStore(database_url).fdr(campaign_id) == pytest.approx(
        payload["fdr_deploy"]
    )
    assert (
        nulloracle.load_verdict(campaign_id, database_url=database_url)
        == nulloracle.CALIBRATION_STATUS_VOID
    )
    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert guard.pvalue == payload["ks_pvalue"]
    assert guard.pvalue < nulloracle.VOID_THRESHOLD


# -- Idempotence -----------------------------------------------------------------


def test_rerun_saves_no_duplicate_row_and_prints_the_same_line(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id, env, _node_ids = _build_type_r_campaign(database_url, tmp_path / "r")
    first: list[str] = []
    second: list[str] = []

    first_exit = main(["--campaign-id", campaign_id], env=env, emit=first.append)
    second_exit = main(["--campaign-id", campaign_id], env=env, emit=second.append)

    assert first_exit == second_exit == EXIT_OK
    assert first == second

    import ops

    assert len(ops.NullCalibrations(database_url).history()) == 1
    assert len(ops.DiscoveryRates(database_url).history()) == 1


# -- The information barrier: no node id beside a null label ------------------


def test_stdout_never_pairs_a_node_id_with_a_null_label(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id, env, node_ids = _build_type_r_campaign(database_url, tmp_path / "r")
    lines: list[str] = []

    main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    line = lines[0]
    # additions_spec_m2_baseline_financial_worlds.xml feature 2 now prints
    # the committed node's own id as committed_pick -- PRD §4.2 forbids a
    # node id beside its null/real *label*, not the pick's bare identity
    # (closeout's own docstring: "the pick's null status is used only for
    # calibration, never printed"). So every node id but the committed
    # pick's own must still be absent, and the committed one must appear
    # nowhere but that one field.
    committed = json.loads(line)["committed_pick"]
    for node_id in node_ids:
        if node_id == committed:
            continue
        assert node_id not in line
    if committed is not None:
        assert line.count(committed) == 1


# -- Refusals -----------------------------------------------------------------


def test_a_one_sided_plant_refuses_with_exit_1_and_no_traceback(
    database_url: str, tmp_path: Path
) -> None:
    # Only one evaluated null node and one evaluated real node: the KS
    # guard's minimum sample (two per side) is not met, so this
    # collaborator refuses before any store is touched -- the same
    # exit-1, no-traceback contract the spec names for a one-sided plant.
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE,
        2,
        campaign_id=campaign_id,
        database_url=database_url,
    )
    null_id = _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=0.1, ic_tstat=0.5)
    real_id = _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=0.3, ic_tstat=1.2)
    for node_id in (null_id, real_id):
        _charge_ledger(database_url, node_id, campaign_id, charges_budget=True, epoch_id="epoch-0")
    assignments = [
        _assignment(campaign_id, null_id, is_null=True),
        _assignment(campaign_id, real_id, is_null=False),
    ]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--campaign-id", campaign_id], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert message.strip()
    assert "Traceback" not in message

    import ops

    # No store was touched by the refused run.
    assert ops.NullCalibrations(database_url).calibration(campaign_id) is None


def test_unknown_campaign_refuses_with_exit_1_and_no_traceback(
    database_url: str, tmp_path: Path
) -> None:
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path / "unknown", [])}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--campaign-id", str(uuid.uuid4())], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert "closeout:" in message
    assert "Traceback" not in message


def test_metric_less_node_table_refuses_as_closeout_unevaluated(
    tmp_path: Path,
) -> None:
    # A node table built by a migration chain that stops before 0114 (the
    # same state python -m nullius_api.demo leaves its store in) carries the
    # five structural columns and none of the seven metrics. Closeout must
    # name this rather than let sqlite3's own "no such column: ic_mean"
    # reach the CLI, as it did for this bug's own repro.
    url = f"sqlite:///{tmp_path / 'closeout-unevaluated.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    _load_migration("0118_node_table").apply(url)

    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 2, campaign_id=campaign_id, database_url=url,
    )
    env = {"DATABASE_URL": url, **_seal_sidecar(tmp_path / "sidecar", [])}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--campaign-id", campaign_id], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert message.startswith(CLOSEOUT_UNEVALUATED_CODE)
    assert campaign_id in message
    assert "no evaluation has written metrics" in message
    assert "nothing to calibrate" in message
    assert "Traceback" not in message
    assert "no such column" not in message


def test_other_sqlite_error_while_reading_is_translated(tmp_path: Path) -> None:
    # A node table malformed in some other way -- missing campaign_id
    # entirely -- raises a different sqlite3.Error than the metric-less
    # case above; it must be translated into a named refusal the same way,
    # not let through raw either.
    url = f"sqlite:///{tmp_path / 'closeout-sqlite-error.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 2, campaign_id=campaign_id, database_url=url,
    )
    # Built after the campaign record, so discovery's own planning-ordering
    # check (an absent node table is not a refusal) never sees it.
    with closing(sqlite3.connect(_path_of(url))) as connection, connection:
        connection.execute("CREATE TABLE node (id TEXT PRIMARY KEY)")
    env = {"DATABASE_URL": url, **_seal_sidecar(tmp_path / "sidecar", [])}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--campaign-id", campaign_id], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert message.startswith(f"{CLOSEOUT_CODE}:")
    assert campaign_id in message
    assert url in message
    assert "Traceback" not in message


def test_missing_database_url_exits_2_naming_it(tmp_path: Path) -> None:
    env = _seal_sidecar(tmp_path, [])

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--campaign-id", str(uuid.uuid4())], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_CONFIG
    assert "DATABASE_URL" in stderr.getvalue()


def test_missing_sidecar_path_exits_2_naming_it(database_url: str) -> None:
    env = {"DATABASE_URL": database_url, nulloracle.KEY_REF_ENV: "hex:" + "ab" * 32}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--campaign-id", str(uuid.uuid4())], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_CONFIG
    assert nulloracle.SIDECAR_PATH_ENV in stderr.getvalue()


def test_missing_sidecar_key_ref_exits_2_naming_it(database_url: str, tmp_path: Path) -> None:
    env = {
        "DATABASE_URL": database_url,
        nulloracle.SIDECAR_PATH_ENV: str(tmp_path / "sidecar.enc"),
    }

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--campaign-id", str(uuid.uuid4())], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_CONFIG
    assert nulloracle.KEY_REF_ENV in stderr.getvalue()
