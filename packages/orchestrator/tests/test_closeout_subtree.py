"""bug_spec_closeout_subtree.xml -- close-out resolves a node's null label
through its root, not through the node's own id.

The sidecar seals one assignment per root (:mod:`orchestrator._oracle`'s
``SubtreeOracle`` applies the same rule during evaluation), but before this
fix :func:`orchestrator.closeout.close_out` asked the sidecar about every
evaluated node's own id -- so the first child ever evaluated past a
campaign's roots raised ``CloseoutError`` and no campaign that refines past
its roots could ever be closed out or calibrated.

This suite drives :func:`orchestrator.closeout.main` over a throwaway, fully
migrated SQLite database and a tmp null sidecar sealed the way
:mod:`nullius_api.demo` seals one, the same harness ``test_closeout_cli.py``
uses -- but plants real multi-level trees (``parent_id`` chains), which that
suite never did.

One test per claim the bug's expected behaviour makes:

* **a two-root campaign with children closes out, and its KS split counts
  children on their root's side** -- the KS guard's persisted sample sizes
  include every evaluated node, root or child.
* **a child discovery under a null root counts as a null pick** -- lowers
  specificity exactly as a root-level false discovery would.
* **two discoveries in one subtree count once** -- two children of one real
  root both clearing the discovery bar still answer sensitivity 1.0 over a
  single true positive, not two.
* **a child whose root is missing from the sidecar is refused, naming the
  root** -- the refusal names the root the walk found, not just the node.
* **a Type-D campaign with a child past the flip records Type-B** -- the
  depth-past-flip accounting resolves each node by its own id (a fact of
  depths, not of the sidecar) and is never refused for a child.
* **a roots-only campaign behaves exactly as before** -- the fix changes
  nothing when every evaluated node already is a root.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory, and none holds state at module scope,
so the suite passes under pytest-xdist.
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
    DISCOVERY_TSTAT,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_VOID,
    main,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the same resolution test_closeout_cli.py
# and test_oracle.py use.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATOR_HASH = hashlib.sha256(b"closeout-subtree-test-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"closeout-subtree-test-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"closeout-subtree-test-cost-model").hexdigest()


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_closeout_subtree_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'closeout-subtree-test.db'}"
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
    :mod:`orchestrator._tree_writer`, including a real ``parent_id`` edge."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node_id, parent_id, campaign_id, "macro", depth, ic_mean, ic_tstat),
        )
    return node_id


def _plant_unevaluated_root(
    database_url: str, campaign_id: str, *, node_id: str, depth: int = 0
) -> str:
    """Insert one root row with no ``ic_mean``/``ic_tstat`` -- a root the
    campaign planted but that :func:`_read_evaluated_nodes` excludes, so a
    test can give a child a root that is part of the population without
    that root itself being the first evaluated node the close-out loop
    reaches."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, None, campaign_id, "macro", depth),
        )
    return node_id


def _set_flip_depth(database_url: str, node_id: str, flip_depth: int) -> None:
    """Fix one node's ``flip_depth`` directly -- §7.3's draw, pinned to one
    value for a reproducible test rather than drawn through
    :class:`nulloracle.FlipDepth`."""
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


# -- A two-root Type-R campaign, each root with children ---------------------


def test_subtree_campaign_closes_out_and_ks_split_counts_children_on_root_side(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )

    root_null = str(uuid.uuid4())
    root_real = str(uuid.uuid4())
    _plant_node(database_url, campaign_id, node_id=root_null, depth=0, ic_mean=0.10, ic_tstat=0.4)
    child_null_1 = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_null,
        depth=1, ic_mean=0.30, ic_tstat=1.1,
    )
    # A discovery under the null root -- the "null pick" this fix must count
    # on the null root's side, not refuse for lacking its own sidecar entry.
    child_null_2 = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_null,
        depth=1, ic_mean=0.50, ic_tstat=DISCOVERY_TSTAT + 0.5,
    )
    _plant_node(database_url, campaign_id, node_id=root_real, depth=0, ic_mean=0.20, ic_tstat=0.9)
    # Two discoveries under the one real root -- must collapse to one pick.
    child_real_1 = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_real,
        depth=1, ic_mean=0.40, ic_tstat=DISCOVERY_TSTAT + 0.3,
    )
    child_real_2 = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_real,
        depth=1, ic_mean=0.95, ic_tstat=DISCOVERY_TSTAT + 1.2,
    )
    all_ids = [root_null, child_null_1, child_null_2, root_real, child_real_1, child_real_2]
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")

    assignments = [
        _assignment(campaign_id, root_null, is_null=True),
        _assignment(campaign_id, root_real, is_null=False),
    ]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    # The discovery count is every evaluated node that cleared the bar,
    # unchanged by root-mapping: three (both null-root and both real-root
    # discoveries), the ledger and discovery-rate counts the raw trials.
    assert payload["discoveries"] == 3
    # The child discovery under the null root is a false discovery (a "null
    # pick"), and it is the campaign's only null root -- specificity 0.0.
    assert payload["specificity"] == 0.0
    # The one real root was discovered (through either or both children,
    # collapsed to one pick) -- sensitivity 1.0, not clipped or doubled.
    assert payload["sensitivity"] == 1.0

    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    # Every evaluated node landed on its root's side: three null-root nodes
    # (the root and its two children), three real-root nodes likewise.
    assert guard.null_count == 3
    assert guard.real_count == 3

    import ops

    rate = ops.DiscoveryRates(database_url).rate(campaign_id)
    assert rate is not None
    assert rate.discoveries == 3
    assert rate.ledger_trials == 6


# -- A child whose root the sidecar does not hold -----------------------------


def test_child_whose_root_the_sidecar_lacks_is_refused_naming_the_root(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 2, campaign_id=campaign_id, database_url=database_url,
    )
    orphan_root = str(uuid.uuid4())
    _plant_unevaluated_root(database_url, campaign_id, node_id=orphan_root, depth=0)
    orphan_child = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=orphan_root,
        depth=1, ic_mean=0.3, ic_tstat=0.6,
    )
    _charge_ledger(database_url, orphan_child, campaign_id, epoch_id="epoch-0")

    # The sidecar is sealed with no entry for this campaign's only root.
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, [])}

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(["--campaign-id", campaign_id], env=env, emit=lambda _line: None)

    assert exit_code == EXIT_REFUSED
    message = stderr.getvalue()
    assert "Traceback" not in message
    assert orphan_root in message
    assert orphan_child in message


# -- A Type-D campaign with a child past the flip -----------------------------


def test_type_d_campaign_with_a_child_past_the_flip_records_type_b(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_D_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )

    # A real root whose branch flips at depth 2: the root and its immediate
    # child stay below the flip, the grandchild sits past it.
    root_real = str(uuid.uuid4())
    _plant_node(database_url, campaign_id, node_id=root_real, depth=0, ic_mean=0.3, ic_tstat=1.0)
    _set_flip_depth(database_url, root_real, 2)
    child_real = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_real,
        depth=1, ic_mean=0.4, ic_tstat=1.0,
    )
    grandchild_real = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_real,
        depth=2, ic_mean=0.5, ic_tstat=DISCOVERY_TSTAT + 0.5,
    )

    # A null root with its own child, neither past its (irrelevant, high)
    # flip -- padding the KS guard's null-side sample to its minimum of two.
    root_null = str(uuid.uuid4())
    _plant_node(database_url, campaign_id, node_id=root_null, depth=0, ic_mean=0.6, ic_tstat=1.0)
    _set_flip_depth(database_url, root_null, 3)
    child_null = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_null,
        depth=1, ic_mean=0.7, ic_tstat=1.0,
    )

    all_ids = [root_real, child_real, grandchild_real, root_null, child_null]
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")

    assignments = [
        _assignment(campaign_id, root_real, is_null=False),
        _assignment(campaign_id, root_null, is_null=True),
    ]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    # Whether or not this small, separated sample votes VOID, the figures
    # are saved either way (the module's own law) -- only a config/refusal
    # exit would mean the child broke close-out, which is the bug.
    assert exit_code in (EXIT_OK, EXIT_VOID)
    payload = json.loads(lines[0])
    # Only the grandchild sits at or beyond its branch's flip (depth 2 >=
    # flip_depth 2); the root and its immediate child stay below it, and
    # the whole null-root branch never reaches its own (uninvolved) flip.
    assert payload["type_b"] == 1

    import ops

    assert ops.TypeBDepths(database_url).depth(campaign_id).depth_past_flip_errors == 1


# -- A roots-only campaign behaves exactly as before --------------------------


def test_roots_only_campaign_behaves_exactly_as_before(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )
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
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["campaign_id"] == campaign_id
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_OK
    assert payload["type_b"] is None
    assert payload["discoveries"] == 1
    assert payload["budget_charging_trials"] == 6
    assert payload["ledger_trials"] == 6

    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert guard.null_count == 3
    assert guard.real_count == 3
