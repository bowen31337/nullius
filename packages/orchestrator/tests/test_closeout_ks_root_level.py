"""bug_spec_ks_guard_root_level.xml -- the KS guard's gate is root-level and
truncated to the non-significant band, not every evaluated node's realised
ic_mean.

Before this fix, :func:`orchestrator.closeout.close_out` fed
:class:`nulloracle.KsGuard` every evaluated node's own ``ic_mean`` -- root
and child alike, split only by the root's sidecar label.  Two problems
followed (PRD §4.3; archT2 voided at ``p=0.013`` while its four sibling
campaigns, drawn from the same mechanism, gave 0.08-0.42): on a window
where real signals have power, the real side became a mixture of genuine
edge and noise while the null side stayed noise alone, so the two-sample
test rejected "real roots have edge" and reported it as "the null is
detectable"; and a child inherits its root's label, so a policy that
refined one root several times counted its correlated children as
independent samples, inflating whichever side that root sat on.

The fix: the gate's sample is one ``ic_mean`` per root -- never a child's --
truncated to roots whose own ``|ic_tstat|`` has not already cleared
:data:`~orchestrator.closeout.DISCOVERY_TSTAT` on either side, so the
comparison is "no edge vs no edge".  The previous, all-node statistic is
still computed and reported as a diagnostic
(``ks_pvalue_all_nodes``), never as the figure the verdict is pronounced on.
A gate whose non-significant roots number fewer than
:data:`nulloracle.KS_MIN_SAMPLE` on either side is not computed at all:
:data:`~orchestrator.closeout.CALIBRATION_STATUS_INSUFFICIENT` names that
state.

One test per claim the bug's expected behaviour makes:

* **the bug's own reproduction (25 null roots, 140 real roots 40% carrying
  true edge, plus children copied from the top roots) closes out ok, not
  VOID, while the diagnostic still rejects.**
* **a leaking null -- null roots systematically offset, every one of them
  individually inside the non-significant band -- is still VOID.**
* **children are excluded from the gate**, even when, if leaked in, they
  would flip the verdict.
* **the "insufficient" path**: too few non-significant roots on one side
  after truncation leaves the campaign neither ok nor VOID.
* **the truncation is applied to both sides**, not only the one a bug might
  remember to filter.

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
import random
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
    KS_VARIANT_ROOT_NONSIG,
    main,
)

EVALUATOR_HASH = hashlib.sha256(b"ks-root-level-test-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"ks-root-level-test-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"ks-root-level-test-cost-model").hexdigest()

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the same resolution test_closeout_cli.py
# and test_closeout_subtree.py use.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_closeout_ks_root_level_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'ks-root-level-test.db'}"
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


def _plant_many(
    database_url: str,
    campaign_id: str,
    rows: list[tuple[str, str | None, int, float, float]],
) -> None:
    """Bulk-insert evaluated node rows -- ``(node_id, parent_id, depth,
    ic_mean, ic_tstat)`` -- in one connection, for the large synthetic
    campaign the reproduction test plants."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.executemany(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (node_id, parent_id, campaign_id, "macro", depth, ic_mean, ic_tstat)
                for node_id, parent_id, depth, ic_mean, ic_tstat in rows
            ],
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
# The bug's own reproduction: edge + pseudo-replicated children
# -----------------------------------------------------------------------

#: The reproduction's own shape, verbatim from the bug report: 25 null
#: roots, 140 real roots, 40% of the real roots carrying a true IC of 0.05.
_NOISE_SIGMA = 0.01
_EDGE_IC = 0.05
_NULL_COUNT = 25
_REAL_COUNT = 140
_EDGE_FRACTION = 0.4
#: Chosen by direct computation against nulloracle's own exact KS estimator
#: (not tuned for a target p-value): the gate's root-level, truncated sample
#: clears 0.05 with a comfortable margin while the all-node diagnostic
#: rejects by five orders of magnitude, so neither claim rides a boundary.
_REPRODUCTION_SEED = 42


def _build_reproduction_campaign(
    database_url: str, tmp_path: Path, *, seed: int = _REPRODUCTION_SEED
) -> tuple[str, dict[str, str]]:
    """25 null roots (``ic_mean ~ N(0, sigma)``) and 140 real roots -- 60%
    drawn from the identical no-edge distribution, 40% carrying a true IC of
    0.05 on top of the same noise -- plus four children copied from each of
    the ten highest-scoring real roots, simulating a policy that refined
    those roots repeatedly.  The null side and the no-edge real roots are
    one population; only the edge roots (and their copied children) differ,
    which is exactly the "genuine edge", not "detectable null", the bug
    describes.
    """
    rng = random.Random(seed)
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 8, campaign_id=campaign_id, database_url=database_url,
    )

    edge_count = round(_REAL_COUNT * _EDGE_FRACTION)
    no_edge_count = _REAL_COUNT - edge_count

    null_ids = [str(uuid.uuid4()) for _ in range(_NULL_COUNT)]
    no_edge_real_ids = [str(uuid.uuid4()) for _ in range(no_edge_count)]
    edge_real_ids = [str(uuid.uuid4()) for _ in range(edge_count)]

    rows: list[tuple[str, str | None, int, float, float]] = []
    for node_id in null_ids:
        ic_mean = rng.gauss(0.0, _NOISE_SIGMA)
        rows.append((node_id, None, 0, ic_mean, ic_mean / _NOISE_SIGMA))
    for node_id in no_edge_real_ids:
        ic_mean = rng.gauss(0.0, _NOISE_SIGMA)
        rows.append((node_id, None, 0, ic_mean, ic_mean / _NOISE_SIGMA))
    edge_means: dict[str, float] = {}
    for node_id in edge_real_ids:
        ic_mean = _EDGE_IC + rng.gauss(0.0, _NOISE_SIGMA)
        edge_means[node_id] = ic_mean
        rows.append((node_id, None, 0, ic_mean, ic_mean / _NOISE_SIGMA))

    # Children copied from the top real (edge) roots -- a policy that
    # refined the same handful of roots repeatedly, inflating the real
    # side's node count with correlated, near-identical readings.
    top_roots = sorted(edge_means, key=lambda node: edge_means[node], reverse=True)[:10]
    for root_id in top_roots:
        for _ in range(4):
            child_id = str(uuid.uuid4())
            ic_mean = edge_means[root_id] + rng.gauss(0.0, _NOISE_SIGMA * 0.1)
            rows.append((child_id, root_id, 1, ic_mean, ic_mean / _NOISE_SIGMA))

    _plant_many(database_url, campaign_id, rows)
    _charge_all(database_url, campaign_id, [node_id for node_id, *_ in rows])

    real_ids = no_edge_real_ids + edge_real_ids
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env


def test_reproduction_is_ok_not_void_while_diagnostic_still_rejects(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id, env = _build_reproduction_campaign(database_url, tmp_path)

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    payload = json.loads(lines[0])
    # The gate: roots without individually detectable edge on both sides are
    # "no edge vs no edge", exactly what the null branch's construction is
    # -- the campaign is not VOID, although 40% of its real roots carry
    # genuine edge.
    assert exit_code == EXIT_OK
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_OK
    assert payload["ks_variant"] == KS_VARIANT_ROOT_NONSIG
    assert payload["ks_pvalue"] >= 0.05
    # The diagnostic -- every node's realised ic_mean, root and child alike,
    # the sample this module gated on before the fix -- still rejects: the
    # genuine edge on 40% of the real roots, amplified by their copied
    # children, is exactly what makes the two populations distinguishable,
    # which is not a fact about the null branch's own construction.
    assert payload["ks_pvalue_all_nodes"] < 0.05

    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert guard.pvalue == payload["ks_pvalue"]
    assert (guard.null_count, guard.real_count) == tuple(payload["ks_root_counts"])
    assert (
        nulloracle.load_verdict(campaign_id, database_url=database_url)
        == nulloracle.CALIBRATION_STATUS_OK
    )


# -----------------------------------------------------------------------
# A leaking null: systematically offset, individually non-significant
# -----------------------------------------------------------------------


def test_leaking_null_inside_the_nonsignificant_band_is_still_void(
    database_url: str, tmp_path: Path
) -> None:
    """Thirty null roots systematically offset from thirty real roots --
    every single root's own ``|ic_tstat|`` stays well under
    ``DISCOVERY_TSTAT`` (max 1.95), so none would individually clear the
    discovery bar -- yet the two populations differ enough in aggregate
    that the gate must still detect it.  This is the leak §7.4's guard
    exists to catch, and the fix must not filter it away along with
    genuine edge."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 8, campaign_id=campaign_id, database_url=database_url,
    )

    count = 30
    null_values = [0.002 + i * (0.0195 - 0.002) / (count - 1) for i in range(count)]
    real_values = [-0.0095 + i * (0.0095 - -0.0095) / (count - 1) for i in range(count)]

    rows: list[tuple[str, str | None, int, float, float]] = []
    null_ids = []
    for value in null_values:
        node_id = str(uuid.uuid4())
        null_ids.append(node_id)
        rows.append((node_id, None, 0, value, value / 0.01))
    real_ids = []
    for value in real_values:
        node_id = str(uuid.uuid4())
        real_ids.append(node_id)
        rows.append((node_id, None, 0, value, value / 0.01))
    _plant_many(database_url, campaign_id, rows)
    _charge_all(database_url, campaign_id, null_ids + real_ids)

    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_VOID
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_VOID
    assert payload["ks_pvalue"] < nulloracle.VOID_THRESHOLD
    assert tuple(payload["ks_root_counts"]) == (count, count)


# -----------------------------------------------------------------------
# Children are excluded from the gate
# -----------------------------------------------------------------------


def test_children_are_excluded_from_the_gate(
    database_url: str, tmp_path: Path
) -> None:
    """Three null roots and three real roots, individually and jointly
    indistinguishable (the roots-only gate's own p-value is 1.0) -- plus ten
    children planted under one real root with an extreme, non-significant
    ``ic_mean`` of 5.0 each.  If those children leaked into the gate's
    population the campaign would VOID (the same ten-point population
    computed directly against nulloracle's own test rejects at p<0.05); with
    children correctly excluded, the gate never sees them and the campaign
    stays calibrated."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 8, campaign_id=campaign_id, database_url=database_url,
    )

    null_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((0.01, 0.1), (0.02, 0.2), (0.03, 0.3))
    ]
    real_root_1 = str(uuid.uuid4())
    _plant_node(database_url, campaign_id, node_id=real_root_1, ic_mean=0.015, ic_tstat=0.15)
    real_ids = [real_root_1] + [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((0.025, 0.25), (0.035, 0.35))
    ]
    children = [
        _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=real_root_1,
            depth=1, ic_mean=5.0, ic_tstat=0.1,
        )
        for _ in range(10)
    ]
    _charge_all(database_url, campaign_id, null_ids + real_ids + children)

    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_OK
    assert tuple(payload["ks_root_counts"]) == (3, 3)
    # The diagnostic sees the children (and their extreme ic_mean) and
    # rejects, confirming they were planted the way the test claims and
    # that their absence from the gate above was exclusion, not accident.
    assert payload["ks_pvalue_all_nodes"] < 0.05

    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert (guard.null_count, guard.real_count) == (3, 3)


# -----------------------------------------------------------------------
# The "insufficient" path
# -----------------------------------------------------------------------


def test_insufficient_when_too_few_nonsignificant_roots_remain(
    database_url: str, tmp_path: Path
) -> None:
    """Two null roots (one individually significant, excluded by the
    truncation, leaving only one -- below ``nulloracle.KS_MIN_SAMPLE``) and
    three non-significant real roots.  The all-node diagnostic has enough
    points on each side to compute (two null, three real), so it is not
    this scenario's refusal; the gate's own, root-level, truncated sample
    is what falls short, and the campaign is marked ``insufficient`` rather
    than refused, voided or cleared."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )

    null_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=0.01, ic_tstat=0.5),
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=0.30, ic_tstat=3.0),
    ]
    real_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((0.01, 0.4), (0.02, 0.6), (0.03, 0.8))
    ]
    _charge_all(database_url, campaign_id, null_ids + real_ids)

    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_OK
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == CALIBRATION_STATUS_INSUFFICIENT
    assert payload["calibration_status"] != nulloracle.CALIBRATION_STATUS_VOID
    assert payload["calibration_status"] != nulloracle.CALIBRATION_STATUS_OK
    assert payload["ks_pvalue"] is None
    assert tuple(payload["ks_root_counts"]) == (1, 3)
    assert isinstance(payload["ks_pvalue_all_nodes"], float)

    # The gate never ran: no guard row, no verdict pronounced -- the
    # campaign row is exactly as an un-read campaign's would be.
    assert nulloracle.load_ks_guard(campaign_id, database_url=database_url) is None
    assert (
        nulloracle.load_verdict(campaign_id, database_url=database_url)
        == nulloracle.CALIBRATION_STATUS_OK
    )


# -----------------------------------------------------------------------
# Truncation is applied to both sides
# -----------------------------------------------------------------------


def test_truncation_is_applied_to_both_sides(
    database_url: str, tmp_path: Path
) -> None:
    """Five null roots (three non-significant, two individually
    significant) and five real roots (the same shape).  The gate's sample
    must drop the significant pair from *both* labels, leaving three a
    side -- never five, and never an asymmetric three-versus-five that a
    truncation applied to only one label would produce."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 8, campaign_id=campaign_id, database_url=database_url,
    )

    null_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((0.01, 0.1), (0.02, 0.2), (0.03, 0.3), (9.0, 5.0), (9.1, -5.0))
    ]
    real_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((0.015, 0.15), (0.025, 0.25), (0.035, 0.35), (9.5, 5.0), (9.6, -5.0))
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
    assert tuple(payload["ks_root_counts"]) == (3, 3)

    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert (guard.null_count, guard.real_count) == (3, 3)
