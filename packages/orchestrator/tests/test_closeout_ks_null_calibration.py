"""bug_spec_ks_null_calibration_gate.xml -- the KS gate tests whether the
nulls still behave like nulls, never whether a real root carries edge.

Before this fix, :func:`orchestrator.closeout.close_out` decided
``calibration_status`` from a comparison of null scores against real ones
(bug_spec_ks_guard_root_level.xml's own root-level, non-significance-
truncated two-sample KS test).  A two-sample comparison rejects whenever the
two sides differ, for *any* reason -- including a real root's own, genuine
edge, which has nothing to do with whether the null branches' construction
(the block permutation and its length) leaks.  Ten synthetic archC
campaigns, each with a planted real edge too weak to individually clear the
discovery bar, voided 6 of 10 while their nulls were perfectly calibrated;
twenty-five archM campaigns with *weaker* real edge voided 0 of 25 --
rewarding weaker research with a cleaner bill of health.

The fix replaces that one comparison with two gates that can only fail on
the campaign's own nulls or its own exploration choices, never on a real
root's score:

* **Gate A, null calibration.**  A one-sample, two-sided Kolmogorov-Smirnov
  test of the campaign's null values (one ``ic_tstat`` per null root for
  Type-R, one per branch's shallowest null node for Type-D) against N(0,1).
  VOID at ``p < nulloracle.VOID_THRESHOLD``; :data:`~orchestrator.closeout.
  CALIBRATION_STATUS_INSUFFICIENT` below :data:`~orchestrator.closeout.
  GATE_A_MIN_NULL_COUNT` null values.
* **Gate B, agent behaviour.**  A two-sided Fisher exact test of whether a
  root's null status predicts whether the policy ever selected it for
  expansion.  VOID at ``p < orchestrator.closeout.GATE_B_VOID_THRESHOLD``
  (0.01, stricter than Gate A's because it is a second gate);
  ``insufficient`` when no root was ever expanded.

``calibration_status`` is VOID if either gate rejects, ok unless Gate A
itself is insufficient (Gate B's own insufficiency -- common in a short or
synthetic campaign -- does not by itself downgrade an otherwise-clean Gate A
reading; see :mod:`orchestrator.closeout`'s own "Gate A and Gate B" docstring
section for why).

One test per claim the bug's expected behaviour makes:

* **the bug's own reproduction (5 null roots with ic_tstat ~ N(0,1), 25 real
  roots each with a small true edge, t around 1 and always below the
  discovery bar) closes out ok, not VOID.**
* **nulls with a leaked edge (ic_tstat drawn as if from N(1.5, 1)) are VOID
  by Gate A.**
* **nulls expanded far more often than reals are VOID by Gate B**, while
  Gate A alone clears the same null sample -- and that VOID stays sticky
  across a rerun even once a later change would make Gate B, computed
  fresh, no longer reject.
* **fewer than three null roots gives ``insufficient``**, neither VOID nor
  ok.
* **a Type-D campaign's Gate A still VOIDs a leaking null, and clears a
  calibrated one**, sampled one value per branch (its shallowest null
  node), the same way bug_spec_closeout_type_d_ks_branch.xml's own fix
  reads a Type-D tree.
* **the diagnostics are reported** -- ``ks_pvalue_root_nonsig``,
  ``ks_pvalue_all_nodes``, ``null_tstat_mean``/``null_tstat_sd`` -- without
  ever deciding ``calibration_status``.

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
    CALIBRATION_STATUS_INSUFFICIENT,
    EXIT_OK,
    EXIT_VOID,
    GATE_A_MIN_NULL_COUNT,
    GATE_B_VOID_THRESHOLD,
    KS_VARIANT_NULL_CALIBRATION,
    main,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the same resolution the suite's
# siblings (test_closeout_cli.py, test_closeout_ks_root_level.py) use.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATOR_HASH = hashlib.sha256(b"ks-null-calibration-test-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"ks-null-calibration-test-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"ks-null-calibration-test-cost-model").hexdigest()


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_closeout_ks_null_calibration_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'ks-null-calibration-test.db'}"
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
    campaign's live evaluator would have written."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node_id, parent_id, campaign_id, "macro", depth, ic_mean, ic_tstat),
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


def _charge_all(database_url: str, campaign_id: str, node_ids: list[str]) -> None:
    for index, node_id in enumerate(node_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")


def _seal_sidecar(
    tmp_path: Path, assignments: list[nulloracle.NullAssignment]
) -> dict[str, str]:
    """Seal ``assignments`` into a tmp sidecar and answer the two
    environment variables a process needs to read it back."""
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


# -----------------------------------------------------------------------
# The bug's own reproduction: a calibrated null, a weak but genuine real edge
# -----------------------------------------------------------------------

#: Five null roots, a plausible draw from N(0,1) (mean close to zero, both
#: signs, nothing approaching the discovery bar) -- verified directly
#: against this gate's own one-sample estimator to clear 0.05 with a
#: comfortable margin (p ~= 0.99), not tuned to a boundary.
_CALIBRATED_NULL_TSTATS = (-1.1, -0.4, 0.2, 0.6, 1.0)

#: Twenty-five real roots, each with a small true edge -- t around 1, every
#: one strictly below DISCOVERY_TSTAT (2.0) so none is individually a
#: discovery -- the exact shape the bug reports: genuine, weak, real edge
#: that must never be compared against the nulls at all.
_WEAK_REAL_TSTATS = tuple(0.7 + 0.05 * i for i in range(25))


def test_reproduction_closes_out_ok_not_void(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 30, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _CALIBRATED_NULL_TSTATS
    ]
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _WEAK_REAL_TSTATS
    ]
    _charge_all(database_url, campaign_id, null_ids + real_ids)
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_OK
    assert payload["ks_variant"] == KS_VARIANT_NULL_CALIBRATION
    assert payload["gate_a_p"] >= nulloracle.VOID_THRESHOLD
    assert payload["ks_pvalue"] == payload["gate_a_p"]
    assert (
        nulloracle.load_verdict(campaign_id, database_url=database_url)
        == nulloracle.CALIBRATION_STATUS_OK
    )


# -----------------------------------------------------------------------
# Gate A: a leaked null -- ic_tstat drawn as if from N(1.5, 1) -- is VOID
# -----------------------------------------------------------------------

#: Five null roots shaped like a draw from N(1.5, 1) rather than N(0, 1):
#: systematically positive and centred well away from zero.  Each value is
#: individually unremarkable (none clears DISCOVERY_TSTAT), but the sample
#: as a whole is implausible as a draw from the calibrated distribution the
#: block permutation promises -- exactly the detectable-null leak PRD §4.3's
#: guard exists to catch.
_LEAKED_NULL_TSTATS = (0.9, 1.3, 1.6, 1.9, 2.3)


def test_leaked_null_edge_is_void_by_gate_a(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 10, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _LEAKED_NULL_TSTATS
    ]
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _CALIBRATED_NULL_TSTATS
    ]
    _charge_all(database_url, campaign_id, null_ids + real_ids)
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_VOID
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_VOID
    assert payload["gate_a_p"] < nulloracle.VOID_THRESHOLD
    assert payload["ks_pvalue"] == payload["gate_a_p"]
    # The null t mean and sd -- aggregate numbers only, never a per-root
    # value -- show the drift an operator would investigate.
    assert payload["null_tstat_mean"] == pytest.approx(
        sum(_LEAKED_NULL_TSTATS) / len(_LEAKED_NULL_TSTATS)
    )
    assert payload["null_tstat_sd"] is not None
    assert (
        nulloracle.load_verdict(campaign_id, database_url=database_url)
        == nulloracle.CALIBRATION_STATUS_VOID
    )


# -----------------------------------------------------------------------
# Gate B: nulls expanded far more often than reals
# -----------------------------------------------------------------------


def test_nulls_expanded_far_more_than_reals_is_void_by_gate_b(
    database_url: str, tmp_path: Path
) -> None:
    """Five null roots, each given one child (the policy expanded every
    one of them), and five real roots with no children at all (the policy
    never touched one) -- Gate A alone clears this null sample (the same
    well-calibrated one the reproduction above uses), so any VOID here is
    Gate B's own finding: the campaign's exploration choices predict a
    root's null status, which is the agent-behaviour leak PRD §4.3's second
    gate exists to catch.
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 10, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _CALIBRATED_NULL_TSTATS
    ]
    children = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=0.01, ic_tstat=0.3,
        )
        for root_id in null_ids
    ]
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _CALIBRATED_NULL_TSTATS
    ]
    _charge_all(database_url, campaign_id, null_ids + children + real_ids)
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_VOID
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_VOID
    # Gate A alone would have cleared this campaign -- the same calibrated
    # null sample as the reproduction above.
    assert payload["gate_a_p"] >= nulloracle.VOID_THRESHOLD
    assert payload["gate_b_p"] < GATE_B_VOID_THRESHOLD
    assert (
        nulloracle.load_verdict(campaign_id, database_url=database_url)
        == nulloracle.CALIBRATION_STATUS_VOID
    )


def test_void_stays_sticky_across_a_rerun_even_if_gate_b_would_now_clear(
    database_url: str, tmp_path: Path
) -> None:
    """The same Gate-B-leaking campaign as above, closed out twice: between
    the two runs, every real root is given a child too, so a *fresh*
    computation of Gate B on the second run would no longer reject (null and
    real roots are now expanded equally often).  The campaign must stay
    VOID anyway -- PRD §7.4's own rule, restated for this gate:
    ``calibration_status`` only ever moves toward VOID, never away from it,
    once a prior run (here, the first of these two) found it so."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 10, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _CALIBRATED_NULL_TSTATS
    ]
    null_children = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=0.01, ic_tstat=0.3,
        )
        for root_id in null_ids
    ]
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _CALIBRATED_NULL_TSTATS
    ]
    _charge_all(database_url, campaign_id, null_ids + null_children + real_ids)
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    first_lines: list[str] = []
    first_exit = main(["--campaign-id", campaign_id], env=env, emit=first_lines.append)
    assert first_exit == EXIT_VOID
    assert json.loads(first_lines[0])["calibration_status"] == (
        nulloracle.CALIBRATION_STATUS_VOID
    )

    # Every real root now gets a child too -- a fresh Gate B reading over
    # this shape alone would no longer reject (equal expansion on both
    # sides).
    for root_id in real_ids:
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=0.01, ic_tstat=0.3,
        )

    second_lines: list[str] = []
    second_exit = main(["--campaign-id", campaign_id], env=env, emit=second_lines.append)

    assert second_exit == EXIT_VOID
    payload = json.loads(second_lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_VOID
    assert (
        nulloracle.load_verdict(campaign_id, database_url=database_url)
        == nulloracle.CALIBRATION_STATUS_VOID
    )


# -----------------------------------------------------------------------
# Fewer than three null roots: insufficient
# -----------------------------------------------------------------------


def test_fewer_than_three_null_roots_gives_insufficient(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 6, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in (-0.3, 0.4)
    ]
    assert len(null_ids) < GATE_A_MIN_NULL_COUNT
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _CALIBRATED_NULL_TSTATS
    ]
    _charge_all(database_url, campaign_id, null_ids + real_ids)
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    # insufficient is neither VOID nor ok -- the command still exits 0
    # (only a VOID verdict answers EXIT_VOID).
    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == CALIBRATION_STATUS_INSUFFICIENT
    assert payload["calibration_status"] != nulloracle.CALIBRATION_STATUS_OK
    assert payload["calibration_status"] != nulloracle.CALIBRATION_STATUS_VOID
    assert payload["gate_a_p"] is None
    assert payload["ks_pvalue"] is None
    assert (
        nulloracle.load_verdict(campaign_id, database_url=database_url)
        == nulloracle.CALIBRATION_STATUS_OK
    )


# -----------------------------------------------------------------------
# A Type-D campaign: Gate A still VOIDs a leaking null, sampled per branch
# -----------------------------------------------------------------------


def test_type_d_campaign_leaked_null_is_void_by_gate_a(
    database_url: str, tmp_path: Path
) -> None:
    """Five branches, each a real root (PRD §4.1.2: every Type-D root is
    real) with a child below its own flip and a grandchild at or past it --
    the grandchild is Gate A's null representative for this type, one per
    branch, labelled by :class:`nulloracle.TypeDOracle`'s own depth
    resolution rather than the sidecar."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_D_CAMPAIGN_TYPE, 10, campaign_id=campaign_id, database_url=database_url,
    )
    real_tstats = (0.2, -0.3, 0.1, -0.1, 0.4)
    null_tstats = _LEAKED_NULL_TSTATS  # the same implausible-for-N(0,1) shape

    roots: list[str] = []
    all_ids: list[str] = []
    for real_t, null_t in zip(real_tstats, null_tstats):
        root_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            depth=0, ic_mean=0.0, ic_tstat=0.0,
        )
        _set_flip_depth(database_url, root_id, 2)
        child_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=real_t * 0.01, ic_tstat=real_t,
        )
        grandchild_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=child_id,
            depth=2, ic_mean=null_t * 0.01, ic_tstat=null_t,
        )
        roots.append(root_id)
        all_ids += [root_id, child_id, grandchild_id]
    _charge_all(database_url, campaign_id, all_ids)

    # Orthogonal sidecar seal, the same test-time convenience
    # test_closeout_ks_root_level.py's own Type-D fixture relies on: no
    # production path seals a Type-D root in the sidecar at all, but
    # scoring.NullPickScorer.calibration_figures needs a non-empty class on
    # each side of the campaign's planted root population.
    assignments = [_assignment(campaign_id, r, is_null=True) for r in roots[:2]]
    assignments += [_assignment(campaign_id, r, is_null=False) for r in roots[2:]]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_VOID
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_VOID
    assert payload["ks_variant"] == KS_VARIANT_NULL_CALIBRATION
    assert payload["gate_a_p"] < nulloracle.VOID_THRESHOLD


#: Five branches' shallowest-null tstats, a plausible draw from N(0,1) --
#: verified directly against this gate's own one-sample estimator to clear
#: 0.05 with a comfortable margin (p ~= 0.99).
_CALIBRATED_TYPE_D_NULL_TSTATS = (-1.0, -0.3, 0.2, 0.6, 0.9)


def test_type_d_campaign_closes_out_ok_when_branches_are_calibrated(
    database_url: str, tmp_path: Path
) -> None:
    """The same five-branch Type-D shape as the leaking case above, but with
    each branch's shallowest null node drawn from a plausible N(0,1) sample:
    Gate A clears it, and the campaign stays calibrated."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_D_CAMPAIGN_TYPE, 10, campaign_id=campaign_id, database_url=database_url,
    )
    real_tstats = (0.2, -0.3, 0.1, -0.1, 0.4)

    roots: list[str] = []
    all_ids: list[str] = []
    for real_t, null_t in zip(real_tstats, _CALIBRATED_TYPE_D_NULL_TSTATS):
        root_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            depth=0, ic_mean=0.0, ic_tstat=0.0,
        )
        _set_flip_depth(database_url, root_id, 2)
        child_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=real_t * 0.01, ic_tstat=real_t,
        )
        grandchild_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=child_id,
            depth=2, ic_mean=null_t * 0.01, ic_tstat=null_t,
        )
        # A sibling discovery, below the same flip -- scoring.account_errors'
        # own Type-A rate refuses an empty pick set, so every branch needs
        # one -- without disturbing the branch's "deepest real" choice above
        # (both sit at depth 1, and the gate keeps the first one seen,
        # child_id, rather than this one).
        discovery_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=0.5, ic_tstat=2.7,
        )
        roots.append(root_id)
        all_ids += [root_id, child_id, grandchild_id, discovery_id]
    _charge_all(database_url, campaign_id, all_ids)

    assignments = [_assignment(campaign_id, r, is_null=True) for r in roots[:2]]
    assignments += [_assignment(campaign_id, r, is_null=False) for r in roots[2:]]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_OK
    assert payload["ks_variant"] == KS_VARIANT_NULL_CALIBRATION
    assert payload["gate_a_p"] >= nulloracle.VOID_THRESHOLD


# -----------------------------------------------------------------------
# The diagnostics are reported, and never gate
# -----------------------------------------------------------------------


def test_diagnostics_are_reported_without_gating(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 30, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _CALIBRATED_NULL_TSTATS
    ]
    real_ids = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            ic_mean=t * 0.01, ic_tstat=t,
        )
        for t in _WEAK_REAL_TSTATS
    ]
    _charge_all(database_url, campaign_id, null_ids + real_ids)
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    # Both diagnostics are present and are plain floats -- computed and
    # reported, like the bug's own expected behaviour states, regardless of
    # what Gate A and Gate B decided.
    assert isinstance(payload["ks_pvalue_all_nodes"], float)
    assert isinstance(payload["ks_pvalue_root_nonsig"], float)
    assert isinstance(payload["ks_root_counts"], list)
    assert len(payload["ks_root_counts"]) == 2
    # The null t mean and sd -- aggregate numbers only.
    assert payload["null_tstat_mean"] == pytest.approx(
        sum(_CALIBRATED_NULL_TSTATS) / len(_CALIBRATED_NULL_TSTATS)
    )
    assert payload["null_tstat_sd"] is not None
    # Neither diagnostic decided the verdict: the diagnostic sees the real
    # side's genuine edge and (being the comparison this bug fix removed)
    # may well reject on it, while the campaign itself stays calibrated.
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_OK
    # No node id from this campaign's plant is ever printed beside a label
    # (PRD §4.2) -- every field above is a campaign-level aggregate.
    line = lines[0]
    for node_id in null_ids + real_ids:
        if node_id == payload["committed_pick"]:
            continue
        assert node_id not in line
