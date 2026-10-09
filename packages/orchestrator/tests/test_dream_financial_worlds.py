"""Feature 3, financial worlds in dreaming -- ``additions_spec_m2_baseline_
financial_worlds.xml``, "Out-of-Sample Evaluation".

*System scores dreaming candidates on admitted financial worlds with the
same per-commit OOS IR, so that a dreaming cycle returns paired ΔIR on real
campaigns, not on bootstrap worlds alone.*

This suite drives :func:`orchestrator.dream.run_cycle` and
:func:`orchestrator._financial_eval.score_on_financial_world` directly over
a throwaway, fully migrated SQLite database -- the campaign and node tables
``test_closeout_commit_oos.py`` migrates, beside the bootstrap pool and
``0109``'s ``replay_score``/``policy_revision`` tables
``test_dream_cli.py`` migrates -- never a subprocess and never a mock of the
dreaming, bootstrap, discovery, policy-runtime or replay libraries.
``evaluate_on_dates`` is the one thing stubbed (monkeypatched on
:mod:`orchestrator._financial_eval`): it is the expensive, sandboxed act this
feature exists to cache around, and a real signal, a real sealed snapshot and
a real sandbox are ``test_closeout_commit_oos.py``'s own concern, not this
module's.

One test per claim the feature sentence and the spec's test list make:

* **a cycle scores both arms** -- the bootstrap figures are unchanged and a
  ``financial_arm`` paired-statistic figure is reported beside them.
* **rows carry the ``#financial`` suffix** -- every widened candidate's
  financial-world rows are filed under ``f"{module_id}#financial"``, never
  under the bootstrap row's bare ``module_id``.
* **a VOID campaign is excluded** -- admitted as neither a financial world
  nor a ``#financial`` row's world, while the two ``ok`` campaigns still are.
* **the per-node cache is hit for a second policy** -- two distinct
  candidate sources that commit the same node of one campaign's tree share
  one ``evaluate_on_dates`` call.
* **a thin financial pool reports thin** -- fewer than
  ``DREAMING_MIN_FINANCIAL_WORLDS`` admitted reports the arm ``"thin"``
  without computing it, while the bootstrap arm still runs.
* **existing bootstrap-only behaviour is unchanged** -- no
  ``NULLIUS_EVALUATION_CONFIG`` (``evaluation_context=None``) reports
  ``"thin"`` regardless of how many campaigns are admitted, and the
  bootstrap figures read exactly as ``test_dream_cli.py``'s own cycle test
  reads them.

No test opens a network connection or reads a real credential, and no state
is kept at module scope across tests, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

import bootstrap
import discovery
import pytest
import replay as replay_member
from artifacts import ArtifactStore
from orchestrator import _financial_eval
from orchestrator._financial_eval import FinancialEvalContext, score_on_financial_world
from orchestrator.closeout import M2_FIXED_POLICY_VERSION
from orchestrator.dream import DREAMING_MIN_FINANCIAL_WORLDS, run_cycle
from policy_runtime import CommittedPick
from replay import TerminalPick

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the resolution every sibling dream and
# closeout suite uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

REPLAY_MIGRATION = "0109_replay_score_and_policy_revision"
CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

#: Enough bootstrap worlds to clear the ladder floor (20) but stay on the
#: capped rung (below 50), so ``M = 10`` -- ``test_dream_cli.py``'s own
#: figure, reused here because this suite's subject is the financial arm
#: beside an otherwise ordinary bootstrap sweep, not the ladder.
POOL_WORLD_COUNT = 40
#: The exact pool seed ``test_dream_cli.py`` uses for this same incumbent
#: source -- chosen here (rather than a fresh one) because "cycle-5" is
#: already confirmed tie-free for this precise (incumbent, pool_seed,
#: world_count, round_cap) combination by that suite's own passing test, the
#: same reason ``test_incumbent_example.py`` pins its own probed iteration
#: id rather than drawing a fresh one per run (``dreaming``'s own argmax
#: refuses a tie between two revised candidates' aggregated scores, which a
#: distance-minimising incumbent like this one hits for some iteration ids
#: and not others).
POOL_SEED = 20261006
ROUND_CAP = 5

#: A commit-reachable, screening-admissible incumbent -- the same shape
#: ``test_dream_cli.INCUMBENT_SOURCE`` takes (one jitterable numeric
#: constant, no hardcoded node id, no comparison against a bare score), read
#: here under ``obs.r2_train``. :class:`orchestrator._financial_eval.
#: _FinancialObservation` answers that name too (aliasing the live tree's own
#: ``r2_insample``), which is exactly what lets one incumbent source run
#: unmodified against a bootstrap world's question *and* a financial world's
#: -- the property the feature's own "the same per-commit OOS IR" rests on.
INCUMBENT_SOURCE = """
THRESHOLD = 0.37


def select(question):
    roots = question.legal_roots()
    observed = question.observed()
    if not observed:
        fallback = None
        for root in roots:
            fallback = root
            break
        question.commit(fallback)
        return list(roots)
    best = None
    best_distance = None
    for node_id, obs in observed.items():
        diff = obs.r2_train - THRESHOLD
        distance = diff * diff
        if best_distance is None or distance < best_distance:
            best = node_id
            best_distance = distance
    question.commit(best)
    frontier = []
    for node_id in observed:
        for action in question.legal_actions(node_id):
            if action not in observed and action not in frontier:
                frontier.append(action)
    return frontier
"""

#: A second, textually distinct candidate -- same contract, a different rule
#: (lexicographically-smallest node id rather than closest-to-threshold) --
#: used only to prove the per-node cache is keyed by the node a policy
#: commits to, not by which policy committed it. Reads directly off
#: ``observed()`` with no "nothing observed yet" branch at all, unlike
#: ``INCUMBENT_SOURCE``'s: a financial-world replay (:func:`replay.run_replay`)
#: pre-seeds the tree's roots into the prefix before the first round, so
#: ``observed()`` is never empty when this candidate is asked -- and a branch
#: that fell through to a ``return`` with no preceding ``commit()`` would (and,
#: pinned by this module's own first draft, did) fail feature 230's static
#: admission on that unreachable-in-practice path alone.
SECOND_POLICY_SOURCE = """
def select(question):
    observed = question.observed()
    best = sorted(observed)[0]
    question.commit(best)
    frontier = []
    for node_id in observed:
        for action in question.legal_actions(node_id):
            if action not in observed and action not in frontier:
                frontier.append(action)
    return frontier
"""


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_dream_financial_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sqlite_path(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _migrated_database(tmp_path: Path, *, world_count: int = POOL_WORLD_COUNT) -> str:
    """A throwaway database carrying every table this suite's cycle touches.

    The bootstrap pool and ``0109``'s replay tables (``test_dream_cli.py``'s
    own recipe), plus the campaign and node tables
    ``test_closeout_commit_oos.py`` migrates for its own M2 commit suite --
    this feature's financial worlds are read off exactly those two tables.
    """
    database_url = f"sqlite:///{tmp_path / 'dream-financial-test.db'}"
    pool = bootstrap.BootstrapPool(database_url)
    pool.persist_worlds(world_count, pool_seed=POOL_SEED)
    _load_migration(REPLAY_MIGRATION).apply(database_url)
    _load_migration(CAMPAIGN_MIGRATION).apply(database_url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)
    return database_url


def _plant_node(
    database_url: str,
    campaign_id: str,
    *,
    node_id: str,
    ic_mean: float,
    ic_tstat: float = 1.0,
) -> None:
    """Plant one evaluated root node -- the state a finished campaign's own
    live evaluator would have written. Every node here is planted as a root
    (no ``parent_id``), so each campaign's tree is the smallest one a replay
    can walk: one node, one legal root, no frontier past it."""
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, NULL, ?, ?, 0, ?, ?)",
            (node_id, campaign_id, "macro", ic_mean, ic_tstat),
        )


def _build_completed_campaign(
    database_url: str, *, ic_mean: float = 0.4
) -> tuple[str, str]:
    """A minimal completed campaign: one root node, finished and admitted.

    Answers ``(campaign_id, node_id)``. No ledger charge and no sealed
    sidecar -- :func:`discovery.finish_campaign` reads only the ``campaign``
    and ``node`` tables, and this feature's own admission
    (:func:`discovery.admit_completed_campaigns`) reads only the manifest
    those two tables produce.
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url
    )
    node_id = str(uuid.uuid4())
    _plant_node(database_url, campaign_id, node_id=node_id, ic_mean=ic_mean)
    discovery.finish_campaign(campaign_id, database_url=database_url)
    return campaign_id, node_id


def _void_campaign(database_url: str) -> str:
    """A completed campaign whose calibration_status reads VOID -- the KS
    guard's own verdict, set directly here rather than through a replayed
    detectable split, because this suite's subject is the admission gate
    reading the status, not the guard that writes it."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url
    )
    node_id = str(uuid.uuid4())
    _plant_node(database_url, campaign_id, node_id=node_id, ic_mean=0.6)
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "UPDATE campaign SET calibration_status = 'VOID' WHERE id = ?",
            (campaign_id,),
        )
    discovery.finish_campaign(campaign_id, database_url=database_url)
    return campaign_id


def _write_code_artifact(artifact_dir: Path, campaign_id: str, node_id: str) -> None:
    store = ArtifactStore(artifact_dir)
    store.write(campaign_id, node_id, "code.py", "# a stored node's signal\n")
    store.commit(campaign_id, node_id)


def _write_m2_fixed_row(
    database_url: str, *, campaign_id: str, node_id: str, score: float
) -> None:
    """One ``m2-fixed`` baseline row, the fact close-out's own M2 commit
    already leaves behind for every admitted, non-VOID completed campaign --
    reused here directly (:func:`replay.persist_replay_score`) rather than
    through a full :func:`orchestrator.closeout.close_out`, because this
    suite's subject is the *financial* arm's own candidate rows and the
    paired comparison that reads this one, not the M2 commit that writes it.
    """
    replay_member.persist_replay_score(
        TerminalPick(pick=CommittedPick(node_id=node_id), score=score),
        M2_FIXED_POLICY_VERSION,
        campaign_id,
        0.5,
        is_holdout=True,
        database_url=database_url,
    )


def _fake_evaluation_context(
    *, database_url: str, artifact_dir: Path, oos_dates: tuple[dt.date, ...]
) -> Any:
    """A duck-typed stand-in for :class:`orchestrator._context.
    EvaluationContext` -- every field :func:`score_on_financial_world` and
    its own collaborators read by attribute
    (:func:`orchestrator._live_tree.live_question`'s ``database_url``/
    ``evaluation_dates``, :func:`orchestrator._targets.
    snapshot_forward_returns`'s ``closes``/``horizon``,
    :mod:`orchestrator._financial_eval`'s own ``artifact_dir``/``oos_dates``)
    and nothing :func:`orchestrator._evaluate.evaluate_on_dates` itself would
    need, because that call is stubbed in every test here -- a real sealed
    snapshot and sandbox are ``test_closeout_commit_oos.py``'s own concern.
    """
    return SimpleNamespace(
        database_url=database_url,
        artifact_dir=artifact_dir,
        evaluation_dates=(dt.date(2026, 1, 1),),
        oos_dates=oos_dates,
        closes={},
        horizon=1,
    )


def _counting_stub(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple]]:
    """Monkeypatch ``evaluate_on_dates`` with a deterministic, call-counted
    stub, answering one fixed IR per node id -- and nothing else -- so a
    test can assert both *that* the cache was hit and *what* it was hit with.
    """
    calls: list[tuple[str, tuple]] = []

    def _stub(node_id: str, _code: str, *, context: Any, oracle: Any, dates: Any) -> tuple[Any, float]:
        calls.append((node_id, tuple(dates)))
        return SimpleNamespace(), 0.1 + 0.01 * len(calls)

    monkeypatch.setattr(_financial_eval, "evaluate_on_dates", _stub)
    return calls


# -- score_on_financial_world, direct: the per-node cache ----------------------


def test_second_policy_committing_the_same_node_hits_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A bare node/campaign database -- no bootstrap pool needed for this
    # direct call, so only the campaign and node migrations are applied.
    database_url = f"sqlite:///{tmp_path / 'cache-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(database_url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)

    campaign_id, node_id = _build_completed_campaign(database_url, ic_mean=0.5)
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_id, node_id)
    calls = _counting_stub(monkeypatch)

    context = FinancialEvalContext(
        evaluation=_fake_evaluation_context(
            database_url=database_url,
            artifact_dir=artifact_dir,
            oos_dates=(dt.date(2026, 6, 1),),
        )
    )

    first = score_on_financial_world(INCUMBENT_SOURCE, campaign_id, context=context)
    second = score_on_financial_world(SECOND_POLICY_SOURCE, campaign_id, context=context)

    assert first.pick is not None and second.pick is not None
    assert first.pick.node_id == node_id
    assert second.pick.node_id == node_id
    assert first.score == second.score
    assert len(calls) == 1
    assert calls[0][0] == node_id


# -- dream.run_cycle: both arms, the #financial suffix, VOID exclusion --------


def _run_cycle(
    database_url: str,
    *,
    iteration_id: str,
    evaluation_context: Any,
) -> dict[str, Any]:
    pool = bootstrap.BootstrapPool(database_url)
    census = bootstrap.world_census(pool)
    return run_cycle(
        incumbent_source=INCUMBENT_SOURCE,
        database_url=database_url,
        iteration_id=iteration_id,
        beta=0.5,
        seed=iteration_id,
        round_cap=ROUND_CAP,
        replay_component=replay_member.ReplayEngine(),
        census=census,
        pool=pool,
        evaluation_context=evaluation_context,
    )


def _financial_rows(database_url: str) -> list[tuple[str, str, int]]:
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection:
        return connection.execute(
            "SELECT policy_version, world_id, is_holdout FROM replay_score "
            "WHERE policy_version LIKE '%#financial' ORDER BY policy_version, world_id"
        ).fetchall()


def test_cycle_scores_both_arms_with_financial_suffixed_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _migrated_database(tmp_path)
    campaign_a, node_a = _build_completed_campaign(database_url, ic_mean=0.3)
    campaign_b, node_b = _build_completed_campaign(database_url, ic_mean=0.6)
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_a, node_a)
    _write_code_artifact(artifact_dir, campaign_b, node_b)
    _write_m2_fixed_row(database_url, campaign_id=campaign_a, node_id=node_a, score=0.05)
    _write_m2_fixed_row(database_url, campaign_id=campaign_b, node_id=node_b, score=-0.02)
    _counting_stub(monkeypatch)

    evaluation_context = _fake_evaluation_context(
        database_url=database_url,
        artifact_dir=artifact_dir,
        oos_dates=(dt.date(2026, 6, 1),),
    )

    summary = _run_cycle(
        database_url, iteration_id="cycle-5", evaluation_context=evaluation_context
    )

    # The bootstrap arm reads exactly as test_dream_cli.py's own cycle test
    # reads it -- unaffected by the financial arm beside it.
    assert summary["n_bootstrap"] == POOL_WORLD_COUNT
    assert isinstance(summary["train_mean"], float)
    assert isinstance(summary["holdout_mean"], float)
    assert summary["gap"] == pytest.approx(summary["train_mean"] - summary["holdout_mean"])

    # The financial arm: two admitted campaigns, a computed paired figure.
    assert summary["n_financial"] == 2
    financial_arm = summary["financial_arm"]
    assert isinstance(financial_arm, dict)
    assert financial_arm["paired_worlds"] == 2
    assert isinstance(financial_arm["mean_difference"], float)
    assert isinstance(financial_arm["p_value"], float)

    # Every widened candidate's financial rows carry the #financial suffix,
    # one row per (candidate, admitted campaign) pair -- never the bootstrap
    # row's bare module_id.
    rows = _financial_rows(database_url)
    versions = {version for version, _world, _holdout in rows}
    worlds = {campaign_a, campaign_b}
    assert all(version.endswith("#financial") for version in versions)
    assert {world for _v, world, _h in rows} == worlds
    assert all(holdout == 1 for _v, _w, holdout in rows)
    revision_count = summary["revision_cap"] + 1
    assert len(versions) == revision_count
    assert len(rows) == revision_count * 2
    assert f"{summary['module_id']}#financial" in versions

    # The bootstrap row for the winner is filed under its bare module_id,
    # never the financial suffix -- a financial row and a bootstrap row
    # never share one version.
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection:
        bootstrap_rows = connection.execute(
            "SELECT COUNT(*) FROM replay_score WHERE policy_version = ?",
            (summary["module_id"],),
        ).fetchone()[0]
    assert bootstrap_rows > 0


def test_void_campaign_is_excluded_from_admission_and_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _migrated_database(tmp_path)
    campaign_a, node_a = _build_completed_campaign(database_url, ic_mean=0.3)
    campaign_b, node_b = _build_completed_campaign(database_url, ic_mean=0.6)
    void_campaign = _void_campaign(database_url)
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_a, node_a)
    _write_code_artifact(artifact_dir, campaign_b, node_b)
    _write_m2_fixed_row(database_url, campaign_id=campaign_a, node_id=node_a, score=0.05)
    _write_m2_fixed_row(database_url, campaign_id=campaign_b, node_id=node_b, score=-0.02)
    _counting_stub(monkeypatch)

    evaluation_context = _fake_evaluation_context(
        database_url=database_url,
        artifact_dir=artifact_dir,
        oos_dates=(dt.date(2026, 6, 1),),
    )

    summary = _run_cycle(
        database_url, iteration_id="cycle-5", evaluation_context=evaluation_context
    )

    # The VOID campaign never clears admission, so it is neither counted...
    assert summary["n_financial"] == 2
    # ...nor swept: no #financial row names it as a world, however many
    # candidates this cycle widened to.
    rows = _financial_rows(database_url)
    assert void_campaign not in {world for _v, world, _h in rows}
    assert {campaign_a, campaign_b} == {world for _v, world, _h in rows}


# -- A thin financial pool, and no evaluation context at all ------------------


def test_thin_financial_pool_reports_thin_and_bootstrap_arm_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _migrated_database(tmp_path)
    campaign_a, node_a = _build_completed_campaign(database_url)
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_a, node_a)
    _write_m2_fixed_row(database_url, campaign_id=campaign_a, node_id=node_a, score=0.05)
    _counting_stub(monkeypatch)
    assert 1 < DREAMING_MIN_FINANCIAL_WORLDS

    evaluation_context = _fake_evaluation_context(
        database_url=database_url,
        artifact_dir=artifact_dir,
        oos_dates=(dt.date(2026, 6, 1),),
    )

    summary = _run_cycle(
        database_url, iteration_id="cycle-5", evaluation_context=evaluation_context
    )

    assert summary["n_financial"] == 1
    assert summary["financial_arm"] == "thin"
    assert _financial_rows(database_url) == []
    # The bootstrap arm is unaffected by a thin (but non-empty) financial pool.
    assert summary["n_bootstrap"] == POOL_WORLD_COUNT
    assert isinstance(summary["train_mean"], float)
    assert isinstance(summary["holdout_mean"], float)


def test_no_evaluation_context_reports_thin_and_bootstrap_behaviour_is_unchanged(
    tmp_path: Path,
) -> None:
    database_url = _migrated_database(tmp_path)
    campaign_a, node_a = _build_completed_campaign(database_url, ic_mean=0.3)
    campaign_b, node_b = _build_completed_campaign(database_url, ic_mean=0.6)
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_a, node_a)
    _write_code_artifact(artifact_dir, campaign_b, node_b)
    _write_m2_fixed_row(database_url, campaign_id=campaign_a, node_id=node_a, score=0.05)
    _write_m2_fixed_row(database_url, campaign_id=campaign_b, node_id=node_b, score=-0.02)
    # evaluate_on_dates is deliberately left unstubbed: with no evaluation
    # context, score_on_financial_world is never called at all, so a real,
    # unstubbed evaluate_on_dates that would reach for a sealed snapshot is
    # never reached either -- the honest proof that this path is untouched.

    summary = _run_cycle(
        database_url, iteration_id="cycle-5", evaluation_context=None
    )

    # Two campaigns are honestly admitted and counted, even though the
    # missing evaluation context means neither is ever swept.
    assert summary["n_financial"] == 2
    assert summary["financial_arm"] == "thin"
    assert _financial_rows(database_url) == []

    # The bootstrap arm reads exactly as test_dream_cli.py's own
    # one-cycle test reads it -- the existing, bootstrap-only behaviour.
    assert summary["n_bootstrap"] == POOL_WORLD_COUNT
    assert summary["revision_cap"] == 10  # 40 worlds: the 20-50 rung, M = 10
    assert isinstance(summary["module_id"], str) and summary["module_id"]
    assert isinstance(summary["code_hash"], str) and len(summary["code_hash"]) == 64
    assert isinstance(summary["train_mean"], float)
    assert isinstance(summary["holdout_mean"], float)
    assert summary["gap"] == pytest.approx(summary["train_mean"] - summary["holdout_mean"])

    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        train_rows = connection.execute(
            "SELECT COUNT(*) FROM replay_score WHERE is_holdout = 0 "
            "AND policy_version NOT LIKE '%#financial' AND policy_version != ?",
            (M2_FIXED_POLICY_VERSION,),
        ).fetchone()[0]
    revision_count = summary["revision_cap"] + 1
    train_world_count = round(POOL_WORLD_COUNT * 0.7)
    assert train_rows == revision_count * train_world_count
