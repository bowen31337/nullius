"""The M2 commit skips planted-null branches -- bug fix tests.

Campaigns 46db5446 and 6717ee2b (M2-wide-h5-v2) committed nodes 1e00d94c and
f3896a87, both planted-null branches, writing m2-fixed replay_score rows read
on the permuted branch.  The commit rule
(additions_spec_cost_aware_selection.xml feature 2) was written against the
discovery bar alone; null branches were assumed to fall below it, which held
only while the null reference was unbiased.  The fix: the commit considers
only nodes whose root the sidecar labels real -- the per-node labels the
close-out's KS-split loop already resolved in the same run, nothing new read,
no label persisted -- and the JSON line gains one integer field,
``null_discoveries``, counting the bar-clearing null branches so skipped.

This suite drives :func:`orchestrator.closeout.close_out` directly over a
throwaway, fully migrated SQLite database and a tmp null sidecar sealed the
way :mod:`nullius_api.demo` seals one -- the same harness
``test_closeout_cost_aware.py`` and ``test_closeout_commit_oos.py`` use.
Node rows are planted directly, the state a finished campaign's live
evaluator would have written.

One test per claim the fix makes:

* **a campaign whose only bar-clearing node is a null branch abstains** --
  ``committed_pick`` ``null``, the world persisted under the miss rule
  (``replay.NON_COMMITTING_SCORE``), exactly as a no-discovery campaign is,
  and ``null_discoveries`` reports ``1`` while ``discoveries`` still counts
  the null (the calibration figures are untouched by the fix).
* **a real node that also clears the bar is committed over the null** -- the
  same fixture with the real root's ``ir_tstat`` raised to the null's, so
  the two tie and the null carries the *lower* node id: a ranking that still
  counted nulls would pick the null, the fix picks the real.
* **a campaign with no bar-clearing null branch closes out exactly as it
  did before the fix** -- the payload's key set is the pre-fix one plus
  ``null_discoveries`` (``0``), every pre-fix field still mirrors its
  :class:`~orchestrator.closeout.CloseoutResult` attribute, and the CLI
  prints the one new field and still exits 0.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory, and none holds any state at module
scope, so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
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
import replay
import scoring
from orchestrator.closeout import (
    EXIT_OK,
    M2_FIXED_BETA,
    M2_FIXED_POLICY_VERSION,
    close_out,
    main,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the same resolution every sibling
# closeout suite uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATOR_HASH = hashlib.sha256(b"closeout-commit-skips-nulls-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"closeout-commit-skips-nulls-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"closeout-commit-skips-nulls-cost-model").hexdigest()

#: The payload's key set as it stood before this fix -- every field
#: :meth:`orchestrator.closeout.CloseoutResult.to_payload` printed, copied
#: here so the "a campaign with no null branch closes out byte-identically
#: apart from the new field" claim is checked against the pre-fix shape
#: itself rather than against whatever the current source happens to print.
PRE_FIX_PAYLOAD_KEYS = frozenset(
    {
        "campaign_id",
        "ks_pvalue",
        "ks_pvalue_all_nodes",
        "ks_pvalue_root_nonsig",
        "ks_variant",
        "ks_root_counts",
        "gate_a_p",
        "gate_b_p",
        "null_tstat_mean",
        "null_tstat_sd",
        "calibration_status",
        "sensitivity",
        "specificity",
        "fdr_deploy",
        "type_b",
        "selection_rule",
        "discoveries_ic",
        "discoveries",
        "budget_charging_trials",
        "ledger_trials",
        "triage_auc",
        "triage_null_count",
        "triage_real_count",
        "committed_pick",
        "oos_ir",
        "oos_ic_tstat",
        "world_persisted",
    }
)


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_closeout_commit_skips_nulls_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'closeout-commit-skips-nulls-test.db'}"
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
    ic_mean: float,
    ic_tstat: float,
    ir_tstat: float,
) -> str:
    """Insert one evaluated root node row directly, ``ir_tstat`` written by
    the same probe-then-``ALTER`` :mod:`orchestrator._tree_writer` runs --
    every node this suite plants carries one, so the whole campaign runs
    under the post-cost rule."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        has_column = any(
            row[1] == "ir_tstat" for row in connection.execute("PRAGMA table_info(node)")
        )
        if not has_column:
            connection.execute("ALTER TABLE node ADD COLUMN ir_tstat REAL")
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat, ir_tstat) VALUES (?, NULL, ?, ?, 0, ?, ?, ?)",
            (node_id, campaign_id, "macro", ic_mean, ic_tstat, ir_tstat),
        )
    return node_id


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


def _replay_score_rows(database_url: str, *, world_id: str) -> list[tuple]:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        return connection.execute(
            "SELECT policy_version, world_id, beta, score, committed_pick, "
            "is_holdout FROM replay_score WHERE world_id = ? ORDER BY created_at",
            (world_id,),
        ).fetchall()


# -- The bug's own fixture: a bar-clearing null root beside a real one --------


def _build_campaign_with_null_and_real_contenders(
    database_url: str,
    tmp_path: Path,
    *,
    real_contender_ir: float,
) -> tuple[str, dict[str, str], str, str]:
    """A Type-R campaign whose only bar-clearing node is a planted-null root
    (``ir_tstat`` 2.5, ``ic_tstat`` 3.0 -- the bug report's own fixture),
    beside a real root at ``real_contender_ir``.

    Four further non-significant null roots and two further non-significant
    real roots keep Gate A and the KS diagnostic samples on both sides of
    their floors, with the nulls' ``ic_tstat`` spread
    ``(-1.2, -0.5, 0.3, 1.0, 3.0)`` landing Gate A comfortably clear of
    ``nulloracle.VOID_THRESHOLD`` -- the campaign closes out calibrated, so
    the abstention the fix produces is observed on a world that *is*
    persisted, not swallowed by a VOID refusal.

    The two contenders carry fixed node ids chosen so the null's sorts
    *below* the real's: at equal ``ir_tstat`` (the second test's fixture) a
    ranking that still counted nulls would break the tie toward the null,
    so committing the real one is the fix's own doing, not the tie-break's.
    Both are valid UUID spellings (the trial ledger parses a node id as
    one) with the ordering carried in the hex tail.  Answers the campaign
    id, its environment, and the two contenders' ids (null, real).
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )
    null_clear = _plant_node(
        database_url, campaign_id, node_id="00000000-0000-0000-0000-000000000001",
        ic_mean=0.20, ic_tstat=3.0, ir_tstat=2.5,
    )
    null_quiet = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=ic_mean, ic_tstat=ic_tstat, ir_tstat=ir_tstat,
        )
        for ic_mean, ic_tstat, ir_tstat in (
            (-0.05, -1.2, -0.9),
            (0.02, -0.5, -0.4),
            (-0.12, 0.3, 0.2),
            (0.07, 1.0, 0.8),
        )
    ]
    real_clear = _plant_node(
        database_url, campaign_id, node_id="00000000-0000-0000-0000-000000000002",
        ic_mean=0.25, ic_tstat=1.6, ir_tstat=real_contender_ir,
    )
    real_quiet = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=ic_mean, ic_tstat=ic_tstat, ir_tstat=ir_tstat,
        )
        for ic_mean, ic_tstat, ir_tstat in ((-0.08, -0.8, -0.6), (0.03, 0.5, 0.3))
    ]
    null_ids = [null_clear, *null_quiet]
    real_ids = [real_clear, *real_quiet]
    for index, node_id in enumerate([*null_ids, *real_ids]):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env, null_clear, real_clear


# -- A campaign whose only bar-clearing node is a null branch abstains --------


def test_null_branch_clearing_the_bar_is_skipped_and_the_campaign_abstains(
    database_url: str, tmp_path: Path
) -> None:
    # The bug report's own reproduce fixture: a null root at ir_tstat 2.5,
    # ic_tstat 3.0 beside a real root at ir_tstat 1.5 (below the bar).
    campaign_id, env, null_clear, _real_clear = _build_campaign_with_null_and_real_contenders(
        database_url, tmp_path, real_contender_ir=1.5
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar)

    # The commit abstains exactly as a no-discovery campaign does.
    assert result.committed_pick is None
    assert result.oos_ir is None
    assert result.oos_ic_tstat is None
    assert result.committed_pick != null_clear
    # The null still counts as a discovery for the calibration figures --
    # FDR_deploy, sensitivity and specificity are untouched by the fix --
    # and the new field reports the one the commit skipped.
    assert result.discoveries == 1
    assert result.null_discoveries == 1
    assert not result.is_void
    assert result.world_persisted is True
    payload = result.to_payload()
    assert payload["committed_pick"] is None
    assert payload["null_discoveries"] == 1

    # The world lands under the miss rule, no pick recorded on the row.
    rows = _replay_score_rows(database_url, world_id=campaign_id)
    assert len(rows) == 1
    policy_version, world_id, beta, score, committed_pick, _is_holdout = rows[0]
    assert policy_version == M2_FIXED_POLICY_VERSION
    assert world_id == campaign_id
    assert beta == M2_FIXED_BETA
    assert committed_pick is None
    assert score == replay.NON_COMMITTING_SCORE
    assert math.isinf(score) and score < 0


# -- A real contender that also clears the bar is committed over the null -----


def test_real_contender_is_committed_over_the_tied_null(
    database_url: str, tmp_path: Path
) -> None:
    # The same fixture with the real root raised to the null's ir_tstat, so
    # the two tie -- and the null's node id sorts below the real's, so a
    # ranking that still counted nulls would break the tie toward the null.
    campaign_id, env, null_clear, real_clear = _build_campaign_with_null_and_real_contenders(
        database_url, tmp_path, real_contender_ir=2.5
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar)

    assert result.committed_pick == real_clear
    assert result.committed_pick != null_clear
    # Both cleared the bar and both still count as discoveries; the commit
    # skipped exactly the null one.
    assert result.discoveries == 2
    assert result.null_discoveries == 1
    payload = result.to_payload()
    assert payload["committed_pick"] == real_clear
    assert payload["null_discoveries"] == 1

    # No OOS window was configured, so the row carries the pick under the
    # miss rule -- the same state test_closeout_commit_oos.py's own
    # "no oos_dates" test pins for a real commit.
    rows = _replay_score_rows(database_url, world_id=campaign_id)
    assert len(rows) == 1
    _policy_version, _world_id, _beta, score, committed_pick, _is_holdout = rows[0]
    assert committed_pick == real_clear
    assert math.isinf(score) and score < 0


# -- A campaign with no bar-clearing null branch closes out as before ---------


def _build_campaign_with_no_null_discovery(
    database_url: str, tmp_path: Path
) -> tuple[str, dict[str, str], str]:
    """``test_closeout_commit_oos.py``'s own one-discovery recipe -- three
    non-significant null roots, three real roots with one past the bar --
    a campaign the pre-fix close-out already closed out cleanly.  Answers
    the campaign id, its environment, and the winner's node id."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=ic_mean, ic_tstat=ic_tstat, ir_tstat=ir_tstat,
        )
        for ic_mean, ic_tstat, ir_tstat in ((0.10, 0.4, 0.2), (0.30, 1.1, 0.5), (0.50, 1.8, 0.9))
    ]
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=ic_mean, ic_tstat=ic_tstat, ir_tstat=ir_tstat,
        )
        for ic_mean, ic_tstat, ir_tstat in ((0.20, 0.9, 0.3), (0.40, 1.5, 0.7), (0.95, 3.2, 3.2))
    ]
    winner_id = real_ids[-1]
    for index, node_id in enumerate([*null_ids, *real_ids]):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env, winner_id


def test_campaign_with_no_null_discovery_payload_unchanged_apart_from_new_field(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id, env, winner_id = _build_campaign_with_no_null_discovery(database_url, tmp_path)
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar)

    # The behaviour the pre-fix close-out already had: the one real
    # discovery is committed, one discovery counted.
    assert result.committed_pick == winner_id
    assert result.discoveries == 1
    assert result.null_discoveries == 0

    payload = result.to_payload()
    # Exactly the pre-fix key set plus the one new integer field, carrying 0
    # for a clean campaign -- nothing else about the line changed.
    assert set(payload) == PRE_FIX_PAYLOAD_KEYS | {"null_discoveries"}
    assert payload["null_discoveries"] == 0
    # Every pre-fix field still mirrors its result attribute, unchanged in
    # shape and value (the one non-attribute spelling, ks_root_counts, is
    # printed as the list of the result's own tuple).
    for key in PRE_FIX_PAYLOAD_KEYS:
        expected = (
            list(result.ks_root_counts) if key == "ks_root_counts" else getattr(result, key)
        )
        assert payload[key] == expected, key

    # The CLI's own JSON line -- the surface the operator reads -- gains the
    # same one field and still exits 0 for a calibrated campaign.
    lines: list[str] = []
    code = main(
        ["--campaign-id", campaign_id], env=env, emit=lines.append
    )
    assert code == EXIT_OK
    assert len(lines) == 1
    printed = json.loads(lines[0])
    assert set(printed) == PRE_FIX_PAYLOAD_KEYS | {"null_discoveries"}
    assert printed["null_discoveries"] == 0
    assert printed["committed_pick"] == winner_id
