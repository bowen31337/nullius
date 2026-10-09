"""Feature 2, the M2 commit -- one pick per campaign, scored out of sample.

additions_spec_m2_baseline_financial_worlds.xml, "Out-of-Sample Evaluation",
feature 2: *System commits one pick per campaign at close-out and scores it
out of sample, so that* ``./run.sh closeout --campaign-id ID`` *returns the
M2 per-commit OOS IR and persists it as the campaign's financial replay-world
score.*

This suite drives :func:`orchestrator.closeout.close_out` directly (the
function :func:`orchestrator.closeout.main` wraps), over a throwaway, fully
migrated SQLite database and a tmp null sidecar sealed the way
:mod:`nullius_api.demo` seals one -- the same harness ``test_closeout_cli.py``
and ``test_closeout_triage.py`` use for the campaign and sidecar side, and
``test_oos_evaluation.py``'s own sealed-snapshot recipe (an AR(1) world, a
hand-written momentum signal, ``sandbox_runtime="unisolated"``) for the one
test that needs a real out-of-sample reading.

One test per claim the feature sentence makes:

* **a campaign with a discovery commits the top node, persists one
  m2-fixed replay_score row, and a rerun keeps it one row** -- and the
  world census then counts ``n_financial == 1``.
* **a no-discovery campaign is persisted as a miss** -- no node clears
  ``DISCOVERY_TSTAT``, so ``committed_pick`` is ``null`` and the row's score
  is the miss floor.
* **a VOID campaign is not persisted** -- the figures (and the commit) are
  still computed, but ``discovery.admit_completed_campaigns``'s own gate
  refuses the world, and no row lands.
* **no oos_dates gives oos_ir null with the world still persisted using the
  miss rule** -- a context is configured, but its ``oos_dates`` is empty, so
  the committed node's OOS reading is unavailable and the persisted score
  falls back to the miss rule even though a pick was made.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory, and none holds state at module scope,
so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import math
import os
import random
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

import bootstrap
import discovery
import ledger
import nulloracle
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import scoring
from artifacts import ArtifactStore
from cost_model import FeeSchedule, load_cost_model
from orchestrator._context import EvaluationContext
from orchestrator.closeout import M2_FIXED_BETA, M2_FIXED_POLICY_VERSION, close_out
from snapshot import SnapshotService

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the resolution every sibling closeout
# suite uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATOR_HASH = hashlib.sha256(b"closeout-commit-oos-test-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"closeout-commit-oos-test-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"closeout-commit-oos-test-cost-model").hexdigest()

# -- The sealed world evaluate_on_dates actually runs over -------------------

SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(80))
LOOKBACK = 10
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + 30]
OOS_DATES = BAR_DAYS[LOOKBACK + 30 : LOOKBACK + 60]
WORLD_SEED = 931007
AUTOCORRELATION = 0.5
HORIZON = 1
EPOCH_ID = "epoch-2026-10-09-commit-oos"

#: The same trailing-momentum signal test_oos_evaluation.py's own suite uses.
MOMENTUM_SIGNAL_CODE = f"""
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
    if len(bars) <= 0:
        raise ValueError("the window carries no bars to score against")
    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    momentum = {{}}
    for symbol in ctx.universe:
        series = frame.filter(pl.col("symbol") == symbol).sort("open_time")
        if len(series) < {LOOKBACK}:
            momentum[symbol] = 0.0
        else:
            first = float(series[-{LOOKBACK}]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_closeout_commit_oos_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'closeout-commit-oos-test.db'}"
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


def _resolved_scorer_and_sidecar(env: dict[str, str]) -> tuple[Any, Any]:
    """The pair :func:`orchestrator.closeout.main` resolves from the
    environment, built the same way here so this suite calls
    :func:`~orchestrator.closeout.close_out` under the identical collaborators
    the CLI would hand it."""
    sidecar = nulloracle.NullSidecar.resolve(env)
    scorer = scoring.NullPickScorer.resolve(env)
    assert sidecar is not None and scorer is not None
    return scorer, sidecar


# -- A small, interleaved Type-R campaign, one real root past the bar --------


def _build_campaign_with_one_discovery(
    database_url: str, tmp_path: Path
) -> tuple[str, dict[str, str], str]:
    """The same interleaved recipe ``test_closeout_cli.py``'s Type-R campaign
    uses (indistinguishable KS split, one real root past ``DISCOVERY_TSTAT``)
    -- every node planted as a root, so the winning node needs no parent
    chain. Answers the campaign id, its environment, and the one node id that
    clears the bar (the only eligible commit)."""
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
    winner_id = real_ids[-1]
    all_ids = null_ids + real_ids
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env, winner_id


def _build_campaign_with_no_discovery(
    database_url: str, tmp_path: Path
) -> tuple[str, dict[str, str]]:
    """The same shape, with every node below ``DISCOVERY_TSTAT`` -- no
    eligible commit."""
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
        for v, t in ((0.20, 0.9), (0.40, 1.5), (0.55, 1.9))
    ]
    all_ids = null_ids + real_ids
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env


def _build_void_campaign(database_url: str, tmp_path: Path) -> tuple[str, dict[str, str]]:
    """A detectable split -- every null root's ``ic_mean`` far below every
    real root's -- the same fully-separated shape ``test_closeout_cli.py``'s
    Type-D recipe uses (exact two-sample, n=m=4: p ~= 0.0286, below
    ``nulloracle.VOID_THRESHOLD``), but with every one of those roots'
    ``ic_tstat`` kept under ``DISCOVERY_TSTAT`` so none is truncated from the
    gate's own "non-significant roots" sample
    (bug_spec_ks_guard_root_level.xml).  One further real root sits past the
    bar on its own, separate from the gate's sample, so the campaign still
    carries a node for the commit to pick -- the world gate must refuse this
    campaign's *world*, never the commit itself."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((-0.90, 0.4), (-0.80, 0.6), (-0.70, 0.8), (-0.60, 1.0))
    ]
    real_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=v, ic_tstat=t)
        for v, t in ((0.60, 0.4), (0.70, 0.6), (0.80, 0.8), (0.95, 1.0))
    ]
    discovery_id = _plant_node(
        database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=0.50, ic_tstat=3.0
    )
    all_ids = [*null_ids, *real_ids, discovery_id]
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in (*real_ids, discovery_id)]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign_id, env


# -- The sealed snapshot the one real out-of-sample read runs over -----------


def _seal_the_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(WORLD_SEED)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol in SYMBOLS:
        price = 100.0 + generator.uniform(-20.0, 20.0)
        previous_return = 0.0
        path: dict[dt.date, float] = {}
        for day in BAR_DAYS:
            shock = generator.gauss(0.0, 0.02)
            return_ = (
                AUTOCORRELATION * previous_return + (1.0 - AUTOCORRELATION) * shock
            )
            price = max(1.0, price * (1.0 + return_))
            path[day] = round(price, 2)
            previous_return = return_
        closes[symbol] = path

    for symbol in SYMBOLS:
        for day in BAR_DAYS:
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ],
                        "close": [f"{closes[symbol][day]:.2f}"],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 12, 1, tzinfo=dt.UTC))
    mount = service.mount(sealed.name)
    return mount, closes


@pytest.fixture(scope="module")
def sealed_world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("closeout-commit-oos-world")
    return _seal_the_world(workdir)


def _oos_context(
    database_url: str,
    tmp_path: Path,
    sealed_world: tuple[Any, dict],
    *,
    oos_dates: tuple[dt.date, ...],
) -> EvaluationContext:
    mount, closes = sealed_world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    return EvaluationContext(
        snapshot=mount,
        closes=closes,
        cost_model=config,
        cost_schedule=schedule,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        epoch_id=EPOCH_ID,
        database_url=database_url,
        artifact_dir=tmp_path / "artifacts",
        seed=WORLD_SEED,
        horizon=HORIZON,
        evaluation_dates=EVALUATION_DATES,
        sandbox_runtime="unisolated",
        oos_dates=oos_dates,
    )


def _write_code_artifact(
    context: EvaluationContext, campaign_id: str, node_id: str, code: str
) -> None:
    store = ArtifactStore(context.artifact_dir)
    store.write(campaign_id, node_id, "code.py", code)
    store.commit(campaign_id, node_id)


def _replay_score_rows(database_url: str, *, world_id: str) -> list[tuple]:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        try:
            return connection.execute(
                "SELECT policy_version, world_id, beta, score, committed_pick, "
                "is_holdout FROM replay_score WHERE world_id = ? ORDER BY created_at",
                (world_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            # A VOID campaign is never persisted, so a suite that closes out
            # nothing else over this database never creates the table at all.
            return []


# -- A campaign with a discovery: commits, scores out of sample, persists ----


def test_discovery_commits_scores_oos_and_persists_one_row_on_rerun(
    database_url: str, tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    campaign_id, env, winner_id = _build_campaign_with_one_discovery(
        database_url, tmp_path / "campaign"
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)
    context = _oos_context(
        database_url, tmp_path / "ctx", sealed_world, oos_dates=OOS_DATES
    )
    _write_code_artifact(context, campaign_id, winner_id, MOMENTUM_SIGNAL_CODE)

    result = close_out(
        campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar,
        context=context,
    )

    assert result.committed_pick == winner_id
    assert result.world_persisted is True
    assert isinstance(result.oos_ir, float)
    assert isinstance(result.oos_ic_tstat, float)
    payload = result.to_payload()
    assert payload["committed_pick"] == winner_id
    assert payload["oos_ir"] == result.oos_ir
    assert payload["world_persisted"] is True

    rows = _replay_score_rows(database_url, world_id=campaign_id)
    assert len(rows) == 1
    policy_version, world_id, beta, score, committed_pick, is_holdout = rows[0]
    assert policy_version == M2_FIXED_POLICY_VERSION
    assert world_id == campaign_id
    assert beta == M2_FIXED_BETA
    assert score == pytest.approx(result.oos_ir)
    assert committed_pick == winner_id
    assert is_holdout == 1  # no prior rotation -- defaults to held out

    # The world census now counts this campaign as one financial world.
    census = bootstrap.world_census(bootstrap.BootstrapPool(database_url))
    assert census.n_financial == 1

    # Rerunning close-out refreshes the row rather than duplicating it.
    second = close_out(
        campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar,
        context=context,
    )
    assert second.committed_pick == winner_id
    rows_after_rerun = _replay_score_rows(database_url, world_id=campaign_id)
    assert len(rows_after_rerun) == 1
    assert rows_after_rerun[0][3] == pytest.approx(result.oos_ir)


# -- A no-discovery campaign is persisted as a miss --------------------------


def test_no_discovery_campaign_is_persisted_as_a_miss(
    database_url: str, tmp_path: Path
) -> None:
    campaign_id, env = _build_campaign_with_no_discovery(database_url, tmp_path)
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(
        campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar,
    )

    assert result.committed_pick is None
    assert result.oos_ir is None
    assert result.oos_ic_tstat is None
    assert result.world_persisted is True

    rows = _replay_score_rows(database_url, world_id=campaign_id)
    assert len(rows) == 1
    policy_version, world_id, _beta, score, committed_pick, is_holdout = rows[0]
    assert policy_version == M2_FIXED_POLICY_VERSION
    assert world_id == campaign_id
    assert committed_pick is None
    assert math.isinf(score) and score < 0
    assert is_holdout == 1


# -- A VOID campaign is not persisted ----------------------------------------


def test_void_campaign_is_not_persisted(database_url: str, tmp_path: Path) -> None:
    campaign_id, env = _build_void_campaign(database_url, tmp_path)
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(
        campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar,
    )

    assert result.calibration_status == nulloracle.CALIBRATION_STATUS_VOID
    assert result.world_persisted is False
    # The commit itself still ran -- a VOID verdict voids the *world*, not
    # the figures close-out already computed (the module's own law: "the
    # figures are saved either way").
    assert result.committed_pick is not None

    rows = _replay_score_rows(database_url, world_id=campaign_id)
    assert rows == []


# -- No oos_dates gives oos_ir null, with the world persisted as a miss -----


def test_no_oos_dates_gives_null_oos_ir_and_persists_as_a_miss(
    database_url: str, tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    campaign_id, env, winner_id = _build_campaign_with_one_discovery(
        database_url, tmp_path / "campaign"
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)
    # A context is configured (unlike the no-context case above), but it
    # carries no OOS window -- the documented "no oos_dates" state feature 2
    # names explicitly, distinct from an unconfigured deployment.
    context = _oos_context(
        database_url, tmp_path / "ctx", sealed_world, oos_dates=()
    )

    result = close_out(
        campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar,
        context=context,
    )

    assert result.committed_pick == winner_id
    assert result.oos_ir is None
    assert result.oos_ic_tstat is None
    assert result.world_persisted is True

    rows = _replay_score_rows(database_url, world_id=campaign_id)
    assert len(rows) == 1
    _policy_version, _world_id, _beta, score, committed_pick, _is_holdout = rows[0]
    # The pick is still recorded (a node was committed), but the score falls
    # back to the miss rule because no OOS reading was ever taken.
    assert committed_pick == winner_id
    assert math.isinf(score) and score < 0
