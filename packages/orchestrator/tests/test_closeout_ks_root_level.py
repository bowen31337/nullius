"""bug_spec_ks_guard_root_level.xml and bug_spec_ks_null_calibration_gate.xml
-- the root/branch-level, non-significance-truncated null-vs-real comparison
this suite was written for is no longer the gate (it is now
``ks_pvalue_root_nonsig``, a diagnostic -- see the latter spec and
:mod:`orchestrator.closeout`'s own "Gate A and Gate B" docstring section),
but every scenario this suite plants still exercises its own, still-relevant
claim about that diagnostic's sample construction, and (now) about Gate A's
one-sample test over the same campaigns.

Before bug_spec_ks_guard_root_level.xml, :func:`orchestrator.closeout.
close_out` fed :class:`nulloracle.KsGuard` every evaluated node's own
``ic_mean`` -- root and child alike, split only by the root's sidecar label.
Two problems followed (PRD §4.3; archT2 voided at ``p=0.013`` while its four
sibling campaigns, drawn from the same mechanism, gave 0.08-0.42): on a
window where real signals have power, the real side became a mixture of
genuine edge and noise while the null side stayed noise alone, so the
two-sample test rejected "real roots have edge" and reported it as "the
null is detectable"; and a child inherits its root's label, so a policy
that refined one root several times counted its correlated children as
independent samples, inflating whichever side that root sat on.  That fix
-- one ``ic_mean`` per root, truncated to roots whose own ``|ic_tstat|`` has
not cleared :data:`~orchestrator.closeout.DISCOVERY_TSTAT` on either side --
narrowed the same defect without removing it: it was still a comparison of
null scores against real ones, and bug_spec_ks_null_calibration_gate.xml's
own archC/archM campaigns (a weaker, still genuine real edge) show it still
voids on a real root's own edge rather than the null's construction.  So
that comparison is demoted to a diagnostic (:attr:`CloseoutResult.
ks_pvalue_root_nonsig`, computed and persisted exactly as before, never
gating), and Gate A -- a one-sample KS test of the campaign's own null
values against N(0,1) -- decides ``calibration_status`` instead.

One test per claim the bugs' expected behaviour makes:

* **the root-level bug's own reproduction (25 null roots, 140 real roots
  40% carrying true edge, plus children copied from the top roots) closes
  out ok under Gate A, not VOID, while both diagnostics still reject.**
* **a leaking null -- every null root strictly positive -- is still VOID,
  now because Gate A reads the null side alone and finds it implausible as
  a draw from N(0,1), not because of a two-sample difference.**
* **children are excluded from Gate A's own sample and from the
  diagnostic**, even when, if leaked into the diagnostic, they would flip
  it.
* **the "insufficient" path**: fewer than :data:`~orchestrator.closeout.
  GATE_A_MIN_NULL_COUNT` null roots leaves the campaign neither ok nor
  VOID, whether or not the (now unrelated) diagnostic can be computed.
* **the diagnostic's truncation is still applied to both sides**, not only
  the one a bug might remember to filter -- Gate A itself needs no
  truncation at all, and this test shows both facts side by side.
* **a Type-D campaign's Gate A samples branches, not roots** -- every
  Type-D root is real (PRD §4.1.2), so a root-level reading would find zero
  nulls in any Type-D campaign; Gate A's unit for this type is one value
  per branch (bug_spec_closeout_type_d_ks_branch.xml), and a branch
  refined past its own flip still contributes only its shallowest null.

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
    KS_VARIANT_NULL_CALIBRATION,
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
    # Gate A: the 25 null roots' own ic_tstat still look like N(0,1) on
    # their own -- the campaign is not VOID, although 40% of its real roots
    # carry genuine edge, because that edge never enters Gate A's sample at
    # all (bug_spec_ks_null_calibration_gate.xml).
    assert exit_code == EXIT_OK
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_OK
    assert payload["ks_variant"] == KS_VARIANT_NULL_CALIBRATION
    assert payload["gate_a_p"] >= 0.05
    assert payload["ks_pvalue"] == payload["gate_a_p"]
    # The diagnostics -- never gating -- still show what each previous
    # design would have found: every node's realised ic_mean (root and
    # child alike) rejects outright, the original bug this module's
    # bug_spec_ks_guard_root_level.xml fix solved; that fix's own
    # root-level, non-significance-truncated comparison does *not* reject
    # here (its whole reason for existing), which is exactly why this
    # reproduction used to stay calibrated under that design -- until a
    # weaker, still-genuine real edge (archC/archM) showed the same
    # null-vs-real comparison, at any truncation, is still the wrong test.
    assert payload["ks_pvalue_all_nodes"] < 0.05
    assert payload["ks_pvalue_root_nonsig"] >= 0.05

    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert guard.pvalue == payload["ks_pvalue_root_nonsig"]
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
    """Thirty null roots, every one strictly positive (``ic_tstat`` from 0.2
    to 1.95, well under ``DISCOVERY_TSTAT`` so none would individually clear
    the discovery bar) against thirty real roots spanning both signs.  Gate A
    reads the null side alone and finds it is never negative at all --
    nothing like a draw from N(0,1) -- and VOIDs on that basis; the previous
    design's reasoning (the two populations differ enough in aggregate for a
    two-sample test to detect it) no longer applies, but the same leak §7.4's
    guard exists to catch is still caught, now by testing the nulls against
    their own known distribution instead of against the real side."""
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
    assert payload["gate_a_p"] < nulloracle.VOID_THRESHOLD
    assert payload["ks_pvalue"] == payload["gate_a_p"]
    assert tuple(payload["ks_root_counts"]) == (count, count)


# -----------------------------------------------------------------------
# Children are excluded from the gate
# -----------------------------------------------------------------------


def test_children_are_excluded_from_the_gate(
    database_url: str, tmp_path: Path
) -> None:
    """Three null roots, well-calibrated on their own (Gate A clears them),
    and three real roots -- plus ten children planted under one real root
    with an extreme, non-significant ``ic_mean`` of 5.0 each (also giving
    that root ten children, so Gate B has one expanded root to read, too
    few to reject on).  If those children's ``ic_mean`` leaked into the
    diagnostic's population it would reject (the same ten-point population
    computed directly against nulloracle's own test rejects at p<0.05);
    with children correctly excluded from both the diagnostic and Gate A's
    own null sample, the campaign stays calibrated."""
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
    assert payload["gate_a_p"] >= nulloracle.VOID_THRESHOLD
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
    """Two null roots and three real roots.  Gate A's own floor
    (:data:`~orchestrator.closeout.GATE_A_MIN_NULL_COUNT`, three) is not
    met -- only two null roots exist at all, one of them individually
    significant, so Gate A never runs -- and Gate B has no expansion
    evidence either (a roots-only campaign): the campaign is marked
    ``insufficient`` rather than refused, voided or cleared.  The all-node
    diagnostic still has enough points on each side to compute (two null,
    three real), so it is not this scenario's refusal; the
    root-level-truncated diagnostic (now purely reported, never gating) is
    what falls short on the null side (one of its two null roots clears
    ``DISCOVERY_TSTAT`` and is truncated away, leaving one -- below
    ``nulloracle.KS_MIN_SAMPLE``)."""
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
    assert payload["gate_a_p"] is None
    assert payload["gate_b_p"] is None
    assert payload["ks_pvalue_root_nonsig"] is None
    assert tuple(payload["ks_root_counts"]) == (1, 3)
    assert isinstance(payload["ks_pvalue_all_nodes"], float)

    # Gate A never ran, so the diagnostic's own store never wrote either --
    # no guard row, no verdict pronounced -- the campaign row is exactly as
    # an un-read campaign's would be.
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
    significant, at opposite extremes) and five real roots (the same
    shape).  Gate A reads every null's own ic_tstat untruncated -- it needs
    no truncation at all, since it never compares against the real side a
    truncation would have to keep symmetric -- and still clears here
    (0.1, 0.2, 0.3, 5.0, -5.0 is not implausible for a 5-point draw from
    N(0,1)): the campaign stays calibrated on Gate A's own merits.  The
    diagnostic this bug fix demoted (bug_spec_ks_guard_root_level.xml's own
    fix) still truncates both labels: it must drop the significant pair
    from *both*, leaving three a side -- never five, and never an
    asymmetric three-versus-five a truncation applied to only one label
    would produce -- which is the property this test still pins."""
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
    assert payload["gate_a_p"] >= 0.05
    assert tuple(payload["ks_root_counts"]) == (3, 3)

    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert (guard.null_count, guard.real_count) == (3, 3)
    assert guard.pvalue == payload["ks_pvalue_root_nonsig"]


# -----------------------------------------------------------------------
# A Type-D campaign: the gate's sample is per-branch, not per-root
# -----------------------------------------------------------------------


def test_type_d_gate_samples_branches_not_roots_and_excludes_pseudo_replication(
    database_url: str, tmp_path: Path
) -> None:
    """Every Type-D root is real (PRD §4.1.2) -- a root-level gate, read the
    Type-R way, would find zero nulls in any Type-D campaign at all (this
    bug: bug_spec_closeout_type_d_ks_branch.xml).  Five branches, each a
    real root with a child below its own flip and a grandchild at or
    beyond it: the grandchild is the gate's null representative, never the
    (always-real) root.  One branch also carries a great-grandchild
    further past the same flip, with an extreme, individually
    non-significant ic_mean that would VOID the campaign on this sample
    alone if the gate counted every past-flip node instead of only the
    branch's shallowest -- the same pseudo-replication exclusion the Type-R
    rule applies to a root's own children.
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_D_CAMPAIGN_TYPE, 8, campaign_id=campaign_id, database_url=database_url,
    )

    # Five branches: root (depth 0, real, trivially non-significant) ->
    # child (depth 1, real, below the flip at depth 2) -> grandchild
    # (depth 2, null, at the flip).  Fully separated child/grandchild
    # ic_mean, both individually non-significant.
    real_values = [(0.60, 0.9), (0.70, 1.1), (0.80, 1.3), (0.95, 1.5), (0.55, 0.7)]
    null_values = [(-0.90, -1.9), (-0.80, -1.7), (-0.70, -1.5), (-0.60, -1.3), (-0.85, -1.8)]

    roots: list[str] = []
    grandchildren: list[str] = []
    all_ids: list[str] = []
    for (real_mean, real_tstat), (null_mean, null_tstat) in zip(real_values, null_values):
        root_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()),
            depth=0, ic_mean=0.0, ic_tstat=0.0,
        )
        _set_flip_depth(database_url, root_id, 2)
        child_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=real_mean, ic_tstat=real_tstat,
        )
        grandchild_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=child_id,
            depth=2, ic_mean=null_mean, ic_tstat=null_tstat,
        )
        # A sibling discovery, below the same flip -- so every branch
        # declares one discovery (scoring.account_errors' own Type-A rate
        # refuses an empty pick set) without disturbing the branch's
        # "deepest real" choice above: both sit at depth 1, and the gate
        # keeps the first one seen (``child_id``) rather than this one.
        discovery_id = _plant_node(
            database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=root_id,
            depth=1, ic_mean=0.5, ic_tstat=2.7,
        )
        roots.append(root_id)
        grandchildren.append(grandchild_id)
        all_ids += [root_id, child_id, grandchild_id, discovery_id]

    # One branch's null side is pseudo-replicated: a great-grandchild sits
    # even further past the same flip, with an extreme ic_mean that would
    # VOID the campaign by itself if the gate counted every past-flip node
    # rather than only the branch's shallowest.
    great_grandchild_id = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), parent_id=grandchildren[0],
        depth=3, ic_mean=50.0, ic_tstat=1.0,
    )
    all_ids.append(great_grandchild_id)
    _charge_all(database_url, campaign_id, all_ids)

    # Two of the five roots sealed null and three real in the sidecar --
    # orthogonal to the depth-based branch labels above, needed only so
    # scoring.NullPickScorer.calibration_figures (fed this campaign's root
    # population regardless of type) sees a non-empty class on each side;
    # no production path seals a Type-D root in the sidecar at all.
    assignments = [_assignment(campaign_id, r, is_null=True) for r in roots[:2]]
    assignments += [_assignment(campaign_id, r, is_null=False) for r in roots[2:]]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    lines: list[str] = []
    exit_code = main(["--campaign-id", campaign_id], env=env, emit=lines.append)

    assert exit_code == EXIT_VOID
    payload = json.loads(lines[0])
    assert payload["calibration_status"] == nulloracle.CALIBRATION_STATUS_VOID
    assert payload["ks_variant"] == KS_VARIANT_NULL_CALIBRATION
    # Gate A: the five branches' shallowest-null tstats are far from N(0,1)
    # on their own -- this is what voids the campaign now, never a
    # comparison against the real side.
    assert payload["gate_a_p"] < nulloracle.VOID_THRESHOLD
    assert payload["ks_pvalue"] == payload["gate_a_p"]
    # Five branches, five null values and five real values -- never the
    # root-level zero a Type-D campaign (every root real) would give, and
    # never six on the null side, which the leaked great-grandchild would
    # have produced.  This is the diagnostic's own count, unchanged.
    assert tuple(payload["ks_root_counts"]) == (5, 5)

    guard = nulloracle.load_ks_guard(campaign_id, database_url=database_url)
    assert guard is not None
    assert (guard.null_count, guard.real_count) == (5, 5)
