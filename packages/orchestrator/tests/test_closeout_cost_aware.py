"""Feature 2, cost-aware discovery and commit at close-out.

additions_spec_cost_aware_selection.xml, "Cost-Aware Selection", feature 2:
*System discovers and commits on post-cost IR at close-out, so that*
``./run.sh closeout`` *returns discoveries and a committed pick chosen by
cost-adjusted evidence, not rank IC alone.*

This suite drives :func:`orchestrator.closeout.close_out` directly, over a
throwaway, fully migrated SQLite database and a tmp null sidecar sealed the
way :mod:`nullius_api.demo` seals one -- the same harness
``test_closeout_cli.py`` and ``test_closeout_commit_oos.py`` already use for
the campaign and sidecar side. Node rows are planted directly, the state a
finished campaign's live evaluator would have written.

One test per claim the feature sentence makes:

* **a high-IC, high-turnover node with negative ir_tstat is not a
  discovery** -- and the previous rule's own count still reports it through
  ``discoveries_ic``.
* **the commit picks the highest ir_tstat** -- not the highest ``ic_tstat``,
  over two eligible nodes where the two disagree.
* **the fallback applies when ir_tstat is absent** -- a tree no evaluation
  wrote ``ir_tstat`` onto falls back to the plain ``ic_tstat`` rule, named
  ``"ic-fallback"``.
* **the Type-R and Type-D paths both use the new rule** -- a Type-D branch
  whose root would discover under the old rule, but carries a negative
  ``ir_tstat``, is excluded exactly as a Type-R node is.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory, and none holds any state at module
scope, so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

import discovery
import ledger
import nulloracle
import pytest
import scoring
from orchestrator.closeout import (
    DISCOVERY_TSTAT,
    SELECTION_RULE_IC_FALLBACK,
    SELECTION_RULE_POST_COST_IR,
    close_out,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the same resolution every sibling
# closeout suite uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
# Deliberately *not* joined by an ir_tstat migration: the column is added
# by the tree writer's own probe-then-ALTER (feature 1), never by a
# migration, so a database migrated through these two alone is exactly the
# pre-feature-1 state the fallback test needs.
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATOR_HASH = hashlib.sha256(b"closeout-cost-aware-test-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"closeout-cost-aware-test-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"closeout-cost-aware-test-cost-model").hexdigest()


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_closeout_cost_aware_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'closeout-cost-aware-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _path_of(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _ensure_ir_tstat_column(connection: sqlite3.Connection) -> None:
    has_column = any(
        row[1] == "ir_tstat" for row in connection.execute("PRAGMA table_info(node)")
    )
    if not has_column:
        connection.execute("ALTER TABLE node ADD COLUMN ir_tstat REAL")


def _plant_node(
    database_url: str,
    campaign_id: str,
    *,
    node_id: str,
    parent_id: str | None = None,
    depth: int = 0,
    ic_mean: float,
    ic_tstat: float,
    ir_tstat: float | None = None,
) -> str:
    """Insert one evaluated node row directly.

    ``ir_tstat`` is written -- and the column added, by the same
    probe-then-``ALTER`` :mod:`orchestrator._tree_writer` runs -- only when
    the caller passes one; a campaign whose every node omits it never adds
    the column at all, reproducing a tree no evaluator has touched since
    feature 1 landed.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        if ir_tstat is None:
            connection.execute(
                "INSERT INTO node (id, parent_id, campaign_id, theme_root, "
                "depth, ic_mean, ic_tstat) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (node_id, parent_id, campaign_id, "macro", depth, ic_mean, ic_tstat),
            )
        else:
            _ensure_ir_tstat_column(connection)
            connection.execute(
                "INSERT INTO node (id, parent_id, campaign_id, theme_root, "
                "depth, ic_mean, ic_tstat, ir_tstat) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node_id, parent_id, campaign_id, "macro", depth,
                    ic_mean, ic_tstat, ir_tstat,
                ),
            )
    return node_id


def _set_flip_depth(database_url: str, node_id: str, flip_depth: int) -> None:
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        has_column = any(
            row[1] == "flip_depth"
            for row in connection.execute("PRAGMA table_info(node)")
        )
        if not has_column:
            connection.execute("ALTER TABLE node ADD COLUMN flip_depth INT")
        connection.execute(
            "UPDATE node SET flip_depth = ? WHERE id = ?", (flip_depth, node_id)
        )


def _charge_ledger(database_url: str, node_id: str, campaign_id: str, *, epoch_id: str) -> None:
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


def _seal_sidecar(tmp_path: Path, assignments: list[nulloracle.NullAssignment]) -> dict[str, str]:
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


def _resolved_scorer_and_sidecar(env: dict[str, str]) -> tuple[Any, Any]:
    sidecar = nulloracle.NullSidecar.resolve(env)
    scorer = scoring.NullPickScorer.resolve(env)
    assert sidecar is not None and scorer is not None
    return scorer, sidecar


# -- A Type-R campaign exercising the cost-aware rule -------------------------


def _build_type_r_campaign(
    database_url: str,
    tmp_path: Path,
    *,
    real_nodes: list[tuple[float, float, float | None]],
) -> tuple[str, dict[str, str], list[str]]:
    """Three non-significant null roots (the gate's own population) plus
    ``real_nodes`` -- each ``(ic_mean, ic_tstat, ir_tstat)``, ``ir_tstat``
    ``None`` to omit the column entirely for that node.  Returns the
    campaign id, its environment, and the planted real node ids in order.
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )
    # The null side carries ir_tstat exactly when the real side does -- a
    # mixed campaign is not this suite's claim, and a fallback test needs
    # the column absent from every row, null and real alike.
    use_ir_tstat = any(ir is not None for _v, _t, ir in real_nodes)
    null_values: tuple[tuple[float, float, float | None], ...] = (
        (0.10, 0.4, 0.2 if use_ir_tstat else None),
        (0.30, 1.1, 0.5 if use_ir_tstat else None),
        (0.50, 1.8, 0.9 if use_ir_tstat else None),
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=v, ic_tstat=t, ir_tstat=ir,
        )
        for v, t, ir in null_values
    ]
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=v, ic_tstat=t, ir_tstat=ir,
        )
        for v, t, ir in real_nodes
    ]
    all_ids = null_ids + real_ids
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env, real_ids


# -- A high-IC, high-turnover node with negative ir_tstat --------------------


def test_negative_ir_tstat_is_not_a_discovery_but_counts_in_discoveries_ic(
    database_url: str, tmp_path: Path
) -> None:
    # Two non-significant real roots (the gate's own population) plus one
    # real root with ic_tstat well past DISCOVERY_TSTAT but a negative
    # ir_tstat -- high turnover erodes the post-cost book even though the
    # in-sample IC alone looks like a clear discovery.
    campaign_id, env, _real_ids = _build_type_r_campaign(
        database_url, tmp_path,
        real_nodes=[
            (0.20, 0.9, 0.3),
            (0.40, 1.5, 0.7),
            (0.95, 3.2, -1.0),
        ],
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar)

    assert result.selection_rule == SELECTION_RULE_POST_COST_IR
    assert result.discoveries == 0
    assert result.discoveries_ic == 1  # the ic_tstat=3.2 node, under the old rule
    assert result.committed_pick is None  # no node is eligible under the new rule
    payload = result.to_payload()
    assert payload["discoveries"] == 0
    assert payload["discoveries_ic"] == 1
    assert payload["selection_rule"] == SELECTION_RULE_POST_COST_IR
    assert payload["committed_pick"] is None


# -- The commit picks the highest ir_tstat, not the highest ic_tstat ---------


def test_commit_picks_highest_ir_tstat_over_highest_ic_tstat(
    database_url: str, tmp_path: Path
) -> None:
    # Two non-significant real roots for the gate, plus two eligible
    # discoveries that disagree: the higher ic_tstat node carries the lower
    # ir_tstat, and vice versa.
    high_ic_low_ir = (0.95, 5.0, 2.1)
    low_ic_high_ir = (0.70, 2.5, 3.5)
    campaign_id, env, real_ids = _build_type_r_campaign(
        database_url, tmp_path,
        real_nodes=[
            (0.20, 0.9, 0.3),
            (0.40, 1.5, 0.7),
            high_ic_low_ir,
            low_ic_high_ir,
        ],
    )
    winner_id = real_ids[3]  # low_ic_high_ir -- the highest ir_tstat
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar)

    assert result.selection_rule == SELECTION_RULE_POST_COST_IR
    assert result.discoveries == 2  # both clear ir_tstat >= DISCOVERY_TSTAT, ic_tstat > 0
    assert result.committed_pick == winner_id
    assert result.committed_pick != real_ids[2]  # not the higher-ic_tstat node


# -- The fallback applies when ir_tstat is absent -----------------------------


def test_ic_fallback_when_ir_tstat_is_absent(database_url: str, tmp_path: Path) -> None:
    # Every node omits ir_tstat entirely -- the column is never added to
    # this database, the state a tree evaluated before feature 1 is in.
    campaign_id, env, real_ids = _build_type_r_campaign(
        database_url, tmp_path,
        real_nodes=[
            (0.20, 0.9, None),
            (0.40, 1.5, None),
            (0.95, 3.2, None),
        ],
    )
    winner_id = real_ids[2]
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        assert not any(
            row[1] == "ir_tstat" for row in connection.execute("PRAGMA table_info(node)")
        )

    result = close_out(campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar)

    assert result.selection_rule == SELECTION_RULE_IC_FALLBACK
    assert result.discoveries == 1
    assert result.discoveries_ic == 1
    assert result.committed_pick == winner_id
    payload = result.to_payload()
    assert payload["selection_rule"] == SELECTION_RULE_IC_FALLBACK
    assert payload["discoveries"] == 1
    assert payload["discoveries_ic"] == 1


# -- Type-D uses the same cost-aware rule -------------------------------------


def _build_type_d_campaign_with_ir_tstat(
    database_url: str, tmp_path: Path
) -> tuple[str, dict[str, str], str, str]:
    """Two branches (root, mid below the flip, child past it), each a real
    root (PRD §4.1.2: every Type-D root is real).  Branch 1's root would be
    an IC-only discovery but carries a negative ``ir_tstat``; branch 2's
    root is the only node eligible under the new rule and is the sole
    possible commit.  Answers the campaign id, its environment, and both
    roots' ids (excluded, winner).
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_D_CAMPAIGN_TYPE, 2, campaign_id=campaign_id, database_url=database_url,
    )

    excluded_root = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), depth=0,
        ic_mean=0.90, ic_tstat=4.0, ir_tstat=-0.5,
    )
    _set_flip_depth(database_url, excluded_root, 2)
    mid1 = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=excluded_root,
        depth=1, ic_mean=0.60, ic_tstat=0.9, ir_tstat=0.4,
    )
    child1 = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=mid1,
        depth=2, ic_mean=-0.85, ic_tstat=-1.8, ir_tstat=-1.0,
    )

    winner_root = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), depth=0,
        ic_mean=0.70, ic_tstat=2.2, ir_tstat=2.6,
    )
    _set_flip_depth(database_url, winner_root, 2)
    mid2 = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=winner_root,
        depth=1, ic_mean=0.65, ic_tstat=1.1, ir_tstat=0.6,
    )
    child2 = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=mid2,
        depth=2, ic_mean=-0.80, ic_tstat=-1.7, ir_tstat=-0.9,
    )

    all_ids = [excluded_root, mid1, child1, winner_root, mid2, child2]
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [
        _assignment(campaign_id, excluded_root, is_null=True),
        _assignment(campaign_id, winner_root, is_null=False),
    ]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env, excluded_root, winner_root


def test_type_d_path_uses_the_cost_aware_rule(database_url: str, tmp_path: Path) -> None:
    campaign_id, env, excluded_root, winner_root = _build_type_d_campaign_with_ir_tstat(
        database_url, tmp_path
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar)

    assert result.selection_rule == SELECTION_RULE_POST_COST_IR
    # Both roots clear the old ic_tstat >= DISCOVERY_TSTAT bar, but only the
    # one with a positive ir_tstat is a discovery under the new rule.
    assert result.discoveries_ic == 2
    assert result.discoveries == 1
    assert result.committed_pick == winner_root
    assert result.committed_pick != excluded_root
    assert DISCOVERY_TSTAT == 2.0
